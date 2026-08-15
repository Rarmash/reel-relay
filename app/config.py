from dataclasses import dataclass
import os
from pathlib import Path


def _secret(name: str, default: str | None = None) -> str:
    file_name = os.getenv(f"{name}_FILE")
    if file_name:
        return Path(file_name).read_text(encoding="utf-8").strip()
    value = os.getenv(name, default)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


@dataclass(frozen=True)
class Settings:
    admin_token: str
    database_path: Path
    temp_root: Path
    max_concurrent_downloads: int
    download_timeout_seconds: int
    max_file_size_mb: int
    cookies_file: Path | None

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024


def load_settings() -> Settings:
    cookies = os.getenv("COOKIES_FILE")
    return Settings(
        admin_token=_secret("ADMIN_TOKEN"),
        database_path=Path(os.getenv("DATABASE_PATH", "/data/reel-relay.db")),
        temp_root=Path(os.getenv("TEMP_ROOT", "/run/reel-downloader")),
        max_concurrent_downloads=max(1, int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "5"))),
        download_timeout_seconds=max(1, int(os.getenv("DOWNLOAD_TIMEOUT_SECONDS", "120"))),
        max_file_size_mb=max(1, int(os.getenv("MAX_FILE_SIZE_MB", "500"))),
        cookies_file=Path(cookies) if cookies else None,
    )
