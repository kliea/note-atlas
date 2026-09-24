from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import init_db
from app.main import app


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "notes.db"))
    init_db()
    return TestClient(app)


def test_create_list_and_reopen_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    payload = {
        "title": "Standup 17 Sep",
        "source": "meeting",
        "raw_text": "Shipped health check.\nNext: ingest notes.",
    }

    created = client.post("/notes", json=payload)
    assert created.status_code == 201
    body = created.json()
    assert body["title"] == payload["title"]
    assert body["source"] == payload["source"]
    assert body["raw_text"] == payload["raw_text"]
    assert body["id"] >= 1
    assert body["topics"] == []
    assert set(body.keys()) == {
        "id",
        "title",
        "source",
        "raw_text",
        "created_at",
        "topics",
        "x",
        "y",
        "z",
        "color",
        "kind",
        "pinned",
        "ink_json",
        "extract_status",
        "study_id",
        "claim_id",
        "study_title",
    }
    assert (body["study_id"], body["claim_id"], body["study_title"]) == (None, None, None)
    assert body["extract_status"] == "pending"
    assert (body["x"], body["y"]) != (0, 0)
    assert body["kind"] == "typed"
    assert body["pinned"] is False

    listed = client.get("/notes")
    assert listed.status_code == 200
    summaries = listed.json()
    assert len(summaries) == 1
    assert summaries[0]["id"] == body["id"]
    assert summaries[0]["title"] == payload["title"]
    assert "raw_text" not in summaries[0]
    assert "ink_json" not in summaries[0]
    assert set(summaries[0].keys()) == {
        "id",
        "title",
        "source",
        "created_at",
        "x",
        "y",
        "z",
        "color",
        "kind",
        "pinned",
        "extract_status",
        "study_id",
        "claim_id",
        "study_title",
    }

    reopened = client.get(f"/notes/{body['id']}")
    assert reopened.status_code == 200
    detail = reopened.json()
    assert detail["raw_text"] == payload["raw_text"]
    assert detail["topics"] == []


def test_get_note_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    response = client.get("/notes/999")
    assert response.status_code == 404


def test_create_ask_note_skips_background_extract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db import chunk_count
    from app.embed import EMBEDDING_DIM

    monkeypatch.setattr(
        "app.index.embed_texts",
        lambda texts: [[0.0] * EMBEDDING_DIM for _ in texts],
    )
    client = _client(tmp_path, monkeypatch)
    created = client.post(
        "/notes",
        json={
            "title": "Why fanout?",
            "source": "ask",
            "raw_text": "I don't have that in the notes.",
        },
    )
    assert created.status_code == 201
    assert created.json()["extract_status"] == "done"
    assert created.json()["topics"] == []
    assert chunk_count() >= 1
