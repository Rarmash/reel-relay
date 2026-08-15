import asyncio
import contextlib
import ipaddress
import json
import os
from pathlib import Path
import shutil
from urllib.parse import unquote, urlsplit
from uuid import uuid4


class DownloadError(Exception): pass
class DownloadTimeout(DownloadError): pass
class FileTooLarge(DownloadError): pass


def validate_instagram_url(value: str) -> str:
    if any(c in value for c in "\r\n\t"):
        raise ValueError("invalid URL")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("only ordinary HTTPS Instagram URLs are allowed")
    host = (parsed.hostname or "").rstrip(".").lower()
    if host not in {"instagram.com", "www.instagram.com", "m.instagram.com"}:
        raise ValueError("URL must use an allowed Instagram hostname")
    try:
        ipaddress.ip_address(host)
        raise ValueError("IP addresses are not allowed")
    except ValueError as exc:
        if str(exc) == "IP addresses are not allowed": raise
    parts = [unquote(p) for p in parsed.path.split("/") if p]
    if len(parts) < 2 or parts[0].lower() not in {"reel", "reels", "p"} or parts[1] in {".", ".."}:
        raise ValueError("URL is not an Instagram Reel or post")
    return value


class Downloader:
    def __init__(self, settings):
        self.settings = settings
        self.semaphore = asyncio.Semaphore(settings.max_concurrent_downloads)

    async def download(self, url: str) -> tuple[Path, Path]:
        request_dir = self.settings.temp_root / uuid4().hex
        request_dir.mkdir(parents=True, exist_ok=False)
        output = request_dir / "video.%(ext)s"
        args = [
            "yt-dlp", "--no-playlist", "--no-progress", "--no-warnings",
            "--ies", "Instagram",
            "--max-filesize", str(self.settings.max_file_size_bytes),
            "-f", "bv*[vcodec^=avc1]+ba[acodec^=mp4a]/b[vcodec^=avc1]/bv*+ba/b",
            "--merge-output-format", "mp4", "--remux-video", "mp4",
            "--print", "after_move:filepath", "-o", os.fspath(output),
        ]
        if self.settings.cookies_file:
            args += ["--cookies", os.fspath(self.settings.cookies_file)]
        args.append(url)
        process = None
        try:
            async with self.semaphore:
                process = await asyncio.create_subprocess_exec(
                    *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )
                try:
                    stdout, _ = await asyncio.wait_for(
                        process.communicate(), self.settings.download_timeout_seconds
                    )
                except asyncio.TimeoutError as exc:
                    process.kill()
                    await process.wait()
                    raise DownloadTimeout from exc
            if process.returncode != 0:
                raise DownloadError(f"yt-dlp exited with code {process.returncode}")
            lines = [line.strip() for line in stdout.decode("utf-8", "replace").splitlines() if line.strip()]
            if not lines:
                raise DownloadError("yt-dlp did not report an output file")
            file_path = Path(lines[-1]).resolve()
            root = request_dir.resolve()
            if root not in file_path.parents or not file_path.is_file():
                raise DownloadError("yt-dlp reported an invalid output file")
            file_path = await self._ensure_iphone_compatible(file_path, request_dir)
            if file_path.stat().st_size > self.settings.max_file_size_bytes:
                raise FileTooLarge
            return request_dir, file_path
        except BaseException:
            if process and process.returncode is None:
                process.kill()
                with contextlib.suppress(Exception): await process.wait()
            shutil.rmtree(request_dir, ignore_errors=True)
            raise

    async def _run_media_tool(self, *args: str) -> bytes:
        process = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, _ = await asyncio.wait_for(
                process.communicate(), self.settings.download_timeout_seconds
            )
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise DownloadTimeout from exc
        except BaseException:
            if process.returncode is None:
                process.kill()
                with contextlib.suppress(Exception):
                    await process.wait()
            raise
        if process.returncode != 0:
            raise DownloadError(f"media tool exited with code {process.returncode}")
        return stdout

    async def _ensure_iphone_compatible(self, source: Path, request_dir: Path) -> Path:
        probe = await self._run_media_tool(
            "ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name",
            "-of", "json", os.fspath(source),
        )
        try:
            streams = json.loads(probe)["streams"]
            video_codecs = [s.get("codec_name") for s in streams if s.get("codec_type") == "video"]
            audio_codecs = [s.get("codec_name") for s in streams if s.get("codec_type") == "audio"]
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise DownloadError("ffprobe returned invalid output") from exc
        if video_codecs == ["h264"] and all(codec == "aac" for codec in audio_codecs):
            return source
        if not video_codecs:
            raise DownloadError("downloaded file has no video stream")

        compatible = request_dir / "iphone.mp4"
        await self._run_media_tool(
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
            "-i", os.fspath(source), "-map", "0:v:0", "-map", "0:a:0?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.1",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
            "-y", os.fspath(compatible),
        )
        if not compatible.is_file():
            raise DownloadError("ffmpeg did not create a compatible output file")
        source.unlink()
        return compatible
