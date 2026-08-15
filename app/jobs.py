import asyncio
from dataclasses import dataclass, field
import logging
from pathlib import Path
import shutil
import time
from uuid import uuid4

from app.downloader import DownloadError, DownloadTimeout, FileTooLarge


log = logging.getLogger("reel_relay.jobs")


@dataclass
class Job:
    id: str
    user_id: int
    user_name: str
    status: str = "queued"
    directory: Path | None = None
    path: Path | None = None
    size: int = 0
    error: str | None = None
    message: str | None = None
    expires_at: float | None = None
    task: asyncio.Task | None = field(default=None, repr=False)


class JobManager:
    def __init__(self, app):
        self.app = app
        self.jobs: dict[str, Job] = {}
        self.lock = asyncio.Lock()
        self.sweeper: asyncio.Task | None = None

    async def start(self) -> None:
        # A container restart invalidates in-memory ownership, so remove any stale tmpfs jobs.
        for child in self.app.state.settings.temp_root.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
        self.sweeper = asyncio.create_task(self._sweep_loop(), name="job-sweeper")

    async def stop(self) -> None:
        if self.sweeper:
            self.sweeper.cancel()
        async with self.lock:
            tasks = [j.task for j in self.jobs.values() if j.task and not j.task.done()]
            directories = [j.directory for j in self.jobs.values() if j.directory]
            self.jobs.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self.sweeper:
            await asyncio.gather(self.sweeper, return_exceptions=True)
        for directory in directories:
            shutil.rmtree(directory, ignore_errors=True)

    async def create(self, user: dict, url: str) -> Job:
        job = Job(id=uuid4().hex, user_id=user["id"], user_name=user["name"])
        async with self.lock:
            self.jobs[job.id] = job
            job.task = asyncio.create_task(self._process(job, url), name=f"job-{job.id}")
        return job

    async def _process(self, job: Job, url: str) -> None:
        job.status = "processing"
        try:
            directory, path = await self.app.state.downloader.download(url)
        except asyncio.CancelledError:
            raise
        except DownloadTimeout:
            await self._fail(job, "download_timeout", "The download timed out.")
        except FileTooLarge:
            await self._fail(job, "file_too_large", "The Reel exceeds the configured size limit.")
        except DownloadError as exc:
            log.warning("job=%s user_id=%s status=failed reason=%s", job.id[:12], job.user_id, exc)
            await self._fail(job, "download_failed", "Instagram did not allow this Reel to be downloaded.")
        except Exception:
            log.exception("job=%s user_id=%s status=failed", job.id[:12], job.user_id)
            await self._fail(job, "download_failed", "The Reel could not be processed.")
        else:
            async with self.lock:
                job.directory = directory
                job.path = path
                job.size = path.stat().st_size
                job.status = "ready"
                job.expires_at = time.monotonic() + self.app.state.settings.job_ttl_seconds

    async def _fail(self, job: Job, error: str, message: str) -> None:
        async with self.lock:
            job.status = "failed"
            job.error = error
            job.message = message
            job.expires_at = time.monotonic() + self.app.state.settings.job_ttl_seconds
        await self.app.state.db.record_event(job.user_id, False)

    async def get(self, job_id: str, user_id: int) -> Job | None:
        async with self.lock:
            job = self.jobs.get(job_id)
            return job if job and job.user_id == user_id else None

    async def claim(self, job_id: str, user_id: int) -> Job | None:
        async with self.lock:
            job = self.jobs.get(job_id)
            if not job or job.user_id != user_id:
                return None
            if job.status == "ready":
                job.status = "delivering"
                job.expires_at = time.monotonic() + self.app.state.settings.job_ttl_seconds
            return job

    async def finish(self, job: Job, success: bool, sent: int) -> None:
        if job.directory:
            shutil.rmtree(job.directory, ignore_errors=True)
        async with self.lock:
            self.jobs.pop(job.id, None)
        await self.app.state.db.record_event(job.user_id, success, job.size, sent)
        log.info(
            "job=%s user_id=%s user=%s status=%s size=%s",
            job.id[:12], job.user_id, job.user_name, "success" if success else "interrupted", sent,
        )

    async def _sweep_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(30)
                now = time.monotonic()
                async with self.lock:
                    expired = [
                        j for j in self.jobs.values()
                        if j.status in {"ready", "failed"} and j.expires_at and j.expires_at <= now
                    ]
                    for job in expired:
                        self.jobs.pop(job.id, None)
                for job in expired:
                    if job.directory:
                        shutil.rmtree(job.directory, ignore_errors=True)
        except asyncio.CancelledError:
            pass
