from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import init_db, replace_note_extraction
from app.export import note_to_markdown, parse_markdown
from app.main import app
from app.models import ExtractedTopic


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "notes.db"))
    monkeypatch.setattr("app.routers.notes.index_note", lambda _note_id: 1)
    init_db()
    return TestClient(app)


def _seed(client: TestClient) -> int:
    created = client.post(
        "/notes",
        json={
            "title": "Lecture: B+ trees",
            "source": "lecture",
            "raw_text": "High fanout keeps the tree short.",
        },
    )
    note_id = int(created.json()["id"])
    replace_note_extraction(
        note_id,
        [
            ExtractedTopic(
                title="Disk I/O efficiency",
                points=["High fanout keeps the tree short"],
                tags=["disk-io", "fanout"],
            )
        ],
    )
    return note_id


def test_json_export_import_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    note_id = _seed(client)
    exported = client.get(f"/notes/{note_id}/export?format=json")
    assert exported.status_code == 200
    body = exported.json()
    assert body["format"] == "note-atlas.note"
    assert body["note"]["title"] == "Lecture: B+ trees"
    assert body["note"]["topics"][0]["title"] == "Disk I/O efficiency"

    imported = client.post("/notes/import", json=body)
    assert imported.status_code == 201
    copy = imported.json()
    assert copy["id"] != note_id
    assert copy["title"] == "Lecture: B+ trees"
    assert copy["topics"][0]["title"] == "Disk I/O efficiency"
    assert [tag["tag"] for tag in copy["topics"][0]["tags"]] == ["disk-io", "fanout"]


def test_markdown_export_import_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    note_id = _seed(client)
    exported = client.get(f"/notes/{note_id}/export?format=markdown")
    assert exported.status_code == 200
    assert "text/markdown" in exported.headers["content-type"]
    markdown = exported.text
    assert markdown.startswith("# Lecture: B+ trees")
    assert "Disk I/O efficiency" in markdown

    imported = client.post(
        "/notes/import",
        json={"format": "markdown", "text": markdown},
    )
    assert imported.status_code == 201
    copy = imported.json()
    assert copy["raw_text"] == "High fanout keeps the tree short."
    assert copy["topics"][0]["points"][0]["text"] == "High fanout keeps the tree short"


def test_parse_markdown_rejects_empty() -> None:
    with pytest.raises(ValueError, match="empty"):
        parse_markdown("   ")
    with pytest.raises(ValueError, match="title"):
        parse_markdown("no heading")


def test_markdown_helper_roundtrip() -> None:
    from app.models import NoteDetail, Point, Tag, Topic

    note = NoteDetail(
        id=1,
        title="SQLite ingestion",
        source="lecture",
        created_at="2026-09-17T00:00:00+00:00",
        raw_text="Notes live in SQLite.",
        topics=[
            Topic(
                id=1,
                note_id=1,
                title="Persistence",
                order_idx=0,
                points=[Point(id=1, topic_id=1, text="Rows survive restarts", order_idx=0)],
                tags=[Tag(id=1, topic_id=1, tag="sqlite")],
            )
        ],
    )
    markdown = note_to_markdown(note)
    bundle = parse_markdown(markdown)
    assert bundle.note.title == "SQLite ingestion"
    assert bundle.note.topics[0].tags == ["sqlite"]
