"""Files pipeline tests run against a temp database, uploads dir, and Chroma dir, never Ollama."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import init_db
from app.main import app

EMBED_DIM = 8


def fake_vector(text: str) -> list[float]:
    """Deterministic, non-zero vector per text."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [b / 255 + 0.01 for b in digest[:EMBED_DIM]]


class FakeEmbedder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    def __call__(self, texts: list[str], *, model: str, timeout: float = 0.0) -> list[list[float]]:
        self.calls.append((model, list(texts)))
        return [fake_vector(t) for t in texts]

    @property
    def texts(self) -> list[str]:
        return [t for _, batch in self.calls for t in batch]


@pytest.fixture(autouse=True)
def files_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the DB, uploads, and Chroma at tmp_path; returns the uploads directory."""
    uploads = tmp_path / "files"
    monkeypatch.setenv("DB_PATH", str(tmp_path / "notes.db"))
    monkeypatch.setenv("FILES_DIR", str(uploads))
    monkeypatch.setenv("FILES_CHROMA_PATH", str(tmp_path / "chroma"))
    init_db()
    return uploads


@pytest.fixture(autouse=True)
def embedder(monkeypatch: pytest.MonkeyPatch) -> FakeEmbedder:
    """Ollama's /api/embed is always faked in Files tests."""
    fake = FakeEmbedder()
    monkeypatch.setattr("app.llm.embed", fake)
    return fake


@pytest.fixture(autouse=True)
def _pulled_models(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ollama's /api/tags is faked too: only the Files default model is pulled."""
    from app.llm import OllamaModel

    monkeypatch.setattr("app.llm.list_models", lambda: [OllamaModel(name="phi3", family="phi3")])


@pytest.fixture(autouse=True)
def _no_active_builds() -> Iterator[None]:
    """The in-process build registry never leaks between tests."""
    from app.files import build

    yield
    build._active.clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
