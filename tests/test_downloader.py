import asyncio
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
