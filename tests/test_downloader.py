import asyncio
import json
from pathlib import Path
import pytest

from app.downloader import Downloader, DownloadError


def test_subprocess_failure_cleans_directory(settings, monkeypatch):
    class Process:
        returncode = 1
        async def communicate(self): return b"", b"contains sensitive URL"
    async def fake_exec(*_args, **_kwargs): return Process()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    with pytest.raises(DownloadError): asyncio.run(Downloader(settings).download("https://instagram.com/reel/x/"))
    assert list(Path(settings.temp_root).glob("*")) == []


def test_compatible_h264_is_not_transcoded(settings, tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    downloader = Downloader(settings)
    calls = []
    async def fake_tool(*args):
        calls.append(args)
        return json.dumps({"streams": [
            {"codec_type": "video", "codec_name": "h264"},
            {"codec_type": "audio", "codec_name": "aac"},
        ]}).encode()
    monkeypatch.setattr(downloader, "_run_media_tool", fake_tool)
    result = asyncio.run(downloader._ensure_iphone_compatible(source, tmp_path))
    assert result == source
    assert len(calls) == 1


def test_vp9_is_transcoded_for_iphone(settings, tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"vp9")
    downloader = Downloader(settings)
    calls = []
    async def fake_tool(*args):
        calls.append(args)
        if args[0] == "ffprobe":
            return json.dumps({"streams": [
                {"codec_type": "video", "codec_name": "vp9"},
            ]}).encode()
        Path(args[-1]).write_bytes(b"h264")
        return b""
    monkeypatch.setattr(downloader, "_run_media_tool", fake_tool)
    result = asyncio.run(downloader._ensure_iphone_compatible(source, tmp_path))
    assert result == tmp_path / "iphone.mp4"
    assert result.read_bytes() == b"h264"
    assert not source.exists()
    assert calls[1][0] == "ffmpeg"
    assert "libx264" in calls[1]
    assert "ultrafast" in calls[1]
    assert "scale=720:1280:force_original_aspect_ratio=decrease:force_divisible_by=2" in calls[1]
