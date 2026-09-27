"""Files pipeline tests run against a temp database and a temp uploads directory."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import init_db
from app.main import app


@pytest.fixture(autouse=True)
def files_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the DB and uploads at tmp_path; returns the uploads directory."""
    uploads = tmp_path / "files"
    monkeypatch.setenv("DB_PATH", str(tmp_path / "notes.db"))
    monkeypatch.setenv("FILES_DIR", str(uploads))
    init_db()
    return uploads


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
