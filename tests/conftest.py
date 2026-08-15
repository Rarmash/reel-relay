import os
os.environ.setdefault("ADMIN_TOKEN", "test-admin-secret")

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path: Path):
    return Settings("test-admin-secret", tmp_path / "db.sqlite", tmp_path / "tmp", 5, 5, 5, None)


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin_headers():
    return {"Authorization": "Bearer test-admin-secret"}


@pytest.fixture
def user(client, admin_headers):
    created = client.post("/api/v1/admin/tokens", headers=admin_headers, json={"name": "andrey"})
    assert created.status_code == 201
    data = created.json()
    return data, {"Authorization": f"Bearer {data['token']}"}
