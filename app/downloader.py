import asyncio
import contextlib
import ipaddress
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
            if file_path.stat().st_size > self.settings.max_file_size_bytes:
                raise FileTooLarge
            return request_dir, file_path
        except BaseException:
            if process and process.returncode is None:
                process.kill()
                with contextlib.suppress(Exception): await process.wait()
            shutil.rmtree(request_dir, ignore_errors=True)
            raise
