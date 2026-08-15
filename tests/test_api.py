import asyncio
from datetime import datetime, timezone
from pathlib import Path
import time

from app.auth import hash_token
from app.downloader import DownloadError


def test_health_and_auth(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.post("/api/v1/download", json={"url": "https://instagram.com/reel/x/"}).status_code == 401


def test_token_is_hashed_and_revocation_is_immediate(client, admin_headers, user, app):
    data, headers = user
    listed = client.get("/api/v1/admin/tokens", headers=admin_headers).json()["tokens"]
    assert "token" not in listed[0] and "token_hash" not in listed[0]
    row = asyncio.run(app.state.db.run(lambda c: c.execute("SELECT token_hash FROM api_tokens").fetchone()))
    assert row[0] == hash_token(data["token"])
    assert data["token"] not in row[0]
    assert client.post(f"/api/v1/admin/tokens/{data['id']}/revoke", headers=admin_headers).status_code == 200
    assert client.post("/api/v1/download", headers=headers, json={"url": "https://instagram.com/reel/x/"}).status_code == 401


class FakeDownloader:
    def __init__(self, root: Path, fail=False): self.root, self.fail = root, fail
    async def download(self, _url):
        directory = self.root / "request-id"
        directory.mkdir(parents=True)
        if self.fail:
            import shutil
            shutil.rmtree(directory)
            raise DownloadError("private URL omitted")
        path = directory / "out.mp4"
        path.write_bytes(b"mock-mp4")
        return directory, path


def test_download_stream_stats_and_cleanup(client, admin_headers, user, app, settings):
    _, headers = user
    app.state.downloader = FakeDownloader(settings.temp_root)
    response = client.post("/api/v1/download", headers=headers, json={"url": "https://instagram.com/reel/x/"})
    assert response.status_code == 200
    assert response.content == b"mock-mp4"
    assert response.headers["content-type"] == "video/mp4"
    assert not (settings.temp_root / "request-id").exists()
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    stats = client.get(f"/api/v1/admin/stats?month={month}", headers=admin_headers).json()
    assert stats["total"]["downloads"] == 1
    assert stats["total"]["bytes_sent"] == 8


def test_downloader_failure_is_normalized(client, admin_headers, user, app, settings):
    _, headers = user
    app.state.downloader = FakeDownloader(settings.temp_root, fail=True)
    response = client.post("/api/v1/download", headers=headers, json={"url": "https://instagram.com/reel/x/"})
    assert response.status_code == 502
    assert response.json()["error"] == "download_failed"
    assert "private" not in response.text


def wait_for_job(client, headers, job_id):
    for _ in range(100):
        response = client.get(f"/api/v1/jobs/{job_id}", headers=headers)
        assert response.status_code == 200
        if response.json()["status"] in {"ready", "failed"}:
            return response
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_job_download_stats_cleanup_and_single_use(client, admin_headers, user, app, settings):
    _, headers = user
    app.state.downloader = FakeDownloader(settings.temp_root)
    created = client.post(
        "/api/v1/jobs", headers=headers, json={"url": "https://instagram.com/reel/x/"}
    )
    assert created.status_code == 202
    job_id = created.json()["id"]
    status = wait_for_job(client, headers, job_id)
    assert status.json() == {"id": job_id, "status": "ready", "size": 8}

    downloaded = client.get(f"/api/v1/jobs/{job_id}/download", headers=headers)
    assert downloaded.status_code == 200
    assert downloaded.content == b"mock-mp4"
    assert not (settings.temp_root / "request-id").exists()
    assert client.get(f"/api/v1/jobs/{job_id}", headers=headers).status_code == 404

    month = datetime.now(timezone.utc).strftime("%Y-%m")
    stats = client.get(f"/api/v1/admin/stats?month={month}", headers=admin_headers).json()
    assert stats["total"]["downloads"] == 1
    assert stats["total"]["bytes_sent"] == 8


def test_job_is_private_to_its_token(client, admin_headers, user, app, settings):
    _, owner_headers = user
    other = client.post(
        "/api/v1/admin/tokens", headers=admin_headers, json={"name": "second-user"}
    ).json()
    other_headers = {"Authorization": f"Bearer {other['token']}"}
    app.state.downloader = FakeDownloader(settings.temp_root)
    created = client.post(
        "/api/v1/jobs", headers=owner_headers, json={"url": "https://instagram.com/reel/x/"}
    )
    job_id = created.json()["id"]
    assert client.get(f"/api/v1/jobs/{job_id}", headers=other_headers).status_code == 404


def test_job_failure_is_normalized(client, admin_headers, user, app, settings):
    _, headers = user
    app.state.downloader = FakeDownloader(settings.temp_root, fail=True)
    created = client.post(
        "/api/v1/jobs", headers=headers, json={"url": "https://instagram.com/reel/x/"}
    )
    job_id = created.json()["id"]
    status = wait_for_job(client, headers, job_id)
    assert status.json()["error"] == "download_failed"
    assert "private" not in status.text
    download = client.get(f"/api/v1/jobs/{job_id}/download", headers=headers)
    assert download.status_code == 409
    assert download.json()["status"] == "failed"

    month = datetime.now(timezone.utc).strftime("%Y-%m")
    stats = client.get(f"/api/v1/admin/stats?month={month}", headers=admin_headers).json()
    assert stats["total"]["failed"] == 1


def test_atomic_concurrent_event_updates(app):
    async def run():
        await app.state.db.initialize()
        token = await app.state.db.create_token("parallel", hash_token("secret"))
        await asyncio.gather(*(app.state.db.record_event(token["id"], True, 10, 10) for _ in range(40)))
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        return await app.state.db.stats(month)
    result = asyncio.run(run())
    assert result["total"]["downloads"] == 40
    assert result["total"]["bytes_sent"] == 400
