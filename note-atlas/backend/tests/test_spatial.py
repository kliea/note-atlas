from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import get_connection, init_db, migrate, migrate_down
from app.layout import ORIGIN_X, ORIGIN_Y, grid_position
from app.main import app

_REAL_DB = Path(__file__).resolve().parents[2] / "data" / "notes.db"


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "notes.db"))
    init_db()
    return TestClient(app)


def test_grid_position_never_origin() -> None:
    for index in range(12):
        x, y = grid_position(index)
        assert (x, y) != (0.0, 0.0)
        assert x >= ORIGIN_X
        assert y >= ORIGIN_Y


def test_patch_note_position_and_style(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    created = client.post(
        "/notes",
        json={"title": "Move me", "source": "", "raw_text": "body"},
    ).json()
    note_id = created["id"]

    patched = client.patch(
        f"/notes/{note_id}",
        json={"x": 640.5, "y": 410.0, "z": 3, "color": "#c45", "kind": "clip", "pinned": True},
    )
    assert patched.status_code == 200
    body = patched.json()
    assert body["x"] == 640.5
    assert body["y"] == 410.0
    assert body["z"] == 3
    assert body["color"] == "#c45"
    assert body["kind"] == "clip"
    assert body["pinned"] is True
    assert body["raw_text"] == "body"

    missing = client.patch("/notes/999", json={"x": 1})
    assert missing.status_code == 404


def test_patch_title_and_delete_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    created = client.post(
        "/notes",
        json={"title": "Draft", "source": "", "raw_text": "hello", "x": 400.0, "y": 300.0},
    ).json()
    assert created["x"] == 400.0
    assert created["y"] == 300.0
    note_id = created["id"]

    patched = client.patch(
        f"/notes/{note_id}",
        json={"title": "Renamed", "raw_text": "hello\nworld"},
    )
    assert patched.status_code == 200
    assert patched.json()["title"] == "Renamed"
    assert patched.json()["raw_text"] == "hello\nworld"

    deleted = client.delete(f"/notes/{note_id}")
    assert deleted.status_code == 204
    assert client.get(f"/notes/{note_id}").status_code == 404
    assert client.delete(f"/notes/{note_id}").status_code == 404


def test_connections_unordered_unique_and_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    left = client.post(
        "/notes", json={"title": "A", "source": "", "raw_text": "a"}
    ).json()
    right = client.post(
        "/notes", json={"title": "B", "source": "", "raw_text": "b"}
    ).json()

    created = client.post(
        "/connections",
        json={"from_note_id": left["id"], "to_note_id": right["id"]},
    )
    assert created.status_code == 201
    conn_body = created.json()
    assert conn_body["from_note_id"] == left["id"]
    assert conn_body["to_note_id"] == right["id"]
    assert set(conn_body.keys()) == {
        "id",
        "from_note_id",
        "to_note_id",
        "kind",
        "created_at",
    }

    listed = client.get("/connections")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    reverse = client.post(
        "/connections",
        json={"from_note_id": right["id"], "to_note_id": left["id"]},
    )
    assert reverse.status_code == 409

    loop = client.post(
        "/connections",
        json={"from_note_id": left["id"], "to_note_id": left["id"]},
    )
    assert loop.status_code == 400

    deleted = client.delete(f"/connections/{conn_body['id']}")
    assert deleted.status_code == 204
    assert client.get("/connections").json() == []
    assert client.delete(f"/connections/{conn_body['id']}").status_code == 404


def _note_snapshot(db_path: Path) -> tuple[list[tuple[int, str, str, str]], int]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        notes = [
            (int(row["id"]), row["title"], row["source"], row["raw_text"])
            for row in conn.execute(
                "SELECT id, title, source, raw_text FROM notes ORDER BY id"
            )
        ]
        topics = int(conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0])
        return notes, topics
    finally:
        conn.close()


def test_v3_migration_roundtrip_on_copy_of_real_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not _REAL_DB.is_file():
        pytest.skip("live notes.db is not present")
    copy = tmp_path / "notes.db"
    shutil.copy2(_REAL_DB, copy)
    monkeypatch.setenv("DB_PATH", str(copy))

    before_notes, before_topics = _note_snapshot(copy)
    assert len(before_notes) >= 1

    migrate()
    after_up_notes, after_up_topics = _note_snapshot(copy)
    assert after_up_notes == before_notes
    assert after_up_topics == before_topics

    conn = get_connection()
    try:
        versions = {
            int(row["version"])
            for row in conn.execute("SELECT version FROM schema_migrations")
        }
        assert 3 in versions
        positions = conn.execute(
            "SELECT id, x, y FROM notes ORDER BY id"
        ).fetchall()
        seen: set[tuple[float, float]] = set()
        for row in positions:
            assert row["x"] is not None and row["y"] is not None
            assert (float(row["x"]), float(row["y"])) != (0.0, 0.0)
            pair = (float(row["x"]), float(row["y"]))
            assert pair not in seen
            seen.add(pair)
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert "connections" in tables
    finally:
        conn.close()

    migrate_down(2)
    after_down_notes, after_down_topics = _note_snapshot(copy)
    assert after_down_notes == before_notes
    assert after_down_topics == before_topics
    probe = sqlite3.connect(copy)
    try:
        names = {str(row[1]) for row in probe.execute("PRAGMA table_info(notes)")}
        assert "x" not in names
        tables = {
            str(row[0])
            for row in probe.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert "connections" not in tables
    finally:
        probe.close()

    migrate()
    restored_notes, restored_topics = _note_snapshot(copy)
    assert restored_notes == before_notes
    assert restored_topics == before_topics
    conn = get_connection()
    try:
        row = conn.execute("SELECT x, y FROM notes ORDER BY id LIMIT 1").fetchone()
        assert (float(row["x"]), float(row["y"])) != (0.0, 0.0)
    finally:
        conn.close()
