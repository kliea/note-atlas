from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import get_connection, init_db, migrate_down, replace_note_chunks
from app.embed import EMBEDDING_DIM, serialize_embedding
from app.index import search
from app.main import app


def _axis(index: int) -> list[float]:
    vector = [0.0] * EMBEDDING_DIM
    vector[index] = 1.0
    return vector


def _fake_embed(texts: Sequence[str]) -> list[list[float]]:
    return [_axis(0) for _ in texts]


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "notes.db"))
    monkeypatch.setattr("app.index.embed_texts", _fake_embed)
    init_db()
    return TestClient(app)


def _note(client: TestClient, title: str, board_id: int | None = None) -> dict:
    body = {"title": title, "source": "test", "raw_text": title}
    if board_id is not None:
        body["board_id"] = board_id
    response = client.post("/notes", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_migration_puts_everything_in_general(client: TestClient) -> None:
    boards = client.get("/boards").json()
    assert [b["name"] for b in boards] == ["General"]
    note = _note(client, "Old habit")
    assert note["board_id"] == boards[0]["id"]


def test_existing_notes_move_into_general_on_upgrade(client: TestClient) -> None:
    _note(client, "Before boards")
    migrate_down(12)
    conn = get_connection()
    try:
        assert "board_id" not in {r["name"] for r in conn.execute("PRAGMA table_info(notes)")}
    finally:
        conn.close()
    init_db()
    general = client.get("/boards").json()[0]
    assert general["note_count"] == 1


def test_create_board_rejects_duplicate_names(client: TestClient) -> None:
    created = client.post("/boards", json={"name": "Networking", "description": " CCNA notes "})
    assert created.status_code == 201
    assert created.json()["slug"] == "networking"
    assert created.json()["description"] == "CCNA notes"
    clash = client.post("/boards", json={"name": "networking"})
    assert clash.status_code == 409


def test_notes_and_strings_stay_on_their_board(client: TestClient) -> None:
    general = client.get("/boards").json()[0]["id"]
    other = client.post("/boards", json={"name": "Cooking"}).json()["id"]
    a = _note(client, "Pasta", other)
    b = _note(client, "Sauce", other)
    c = _note(client, "Routing", general)

    assert {n["id"] for n in client.get(f"/notes?board_id={other}").json()} == {a["id"], b["id"]}
    assert client.post("/connections", json={"from_note_id": a["id"], "to_note_id": b["id"]}).status_code == 201
    cross = client.post("/connections", json={"from_note_id": a["id"], "to_note_id": c["id"]})
    assert cross.status_code == 400
    assert len(client.get(f"/connections?board_id={other}").json()) == 1
    assert client.get(f"/connections?board_id={general}").json() == []


def test_search_is_scoped_to_one_board(client: TestClient) -> None:
    general = client.get("/boards").json()[0]["id"]
    other = client.post("/boards", json={"name": "Cooking"}).json()["id"]
    home = _note(client, "Home", general)
    away = _note(client, "Away", other)
    replace_note_chunks(home["id"], [(None, "home chunk", serialize_embedding(_axis(0)))])
    replace_note_chunks(away["id"], [(None, "away chunk", serialize_embedding(_axis(0)))])

    hits = search("anything", k=5, embed=_fake_embed, board_id=other)
    assert [hit.note_id for hit in hits] == [away["id"]]


def test_new_notes_land_in_the_last_opened_board(client: TestClient) -> None:
    general = client.get("/boards").json()[0]["id"]
    other = client.post("/boards", json={"name": "Cooking"}).json()["id"]
    client.post(f"/boards/{general}/open")
    assert _note(client, "Default")["board_id"] == general
    client.post(f"/boards/{other}/open")
    assert _note(client, "Default again")["board_id"] == other


def test_rename_and_describe_board(client: TestClient) -> None:
    other = client.post("/boards", json={"name": "Cooking"}).json()["id"]
    renamed = client.patch(f"/boards/{other}", json={"name": "Home cooking", "description": ""})
    assert renamed.status_code == 200
    assert renamed.json()["slug"] == "home-cooking"
    assert renamed.json()["description"] is None


def test_delete_board_removes_its_notes_but_not_the_last_board(client: TestClient) -> None:
    general = client.get("/boards").json()[0]["id"]
    assert client.delete(f"/boards/{general}").status_code == 409
    other = client.post("/boards", json={"name": "Scratch"}).json()["id"]
    gone = _note(client, "Temporary", other)
    kept = _note(client, "Keeper", general)
    assert client.delete(f"/boards/{other}").status_code == 204
    assert client.get(f"/notes/{gone['id']}").status_code == 404
    assert client.get(f"/notes/{kept['id']}").status_code == 200
    assert [b["id"] for b in client.get("/boards").json()] == [general]


def test_moving_a_note_cuts_strings_to_notes_left_behind(client: TestClient) -> None:
    general = client.get("/boards").json()[0]["id"]
    other = client.post("/boards", json={"name": "Cooking"}).json()["id"]
    a = _note(client, "A", general)
    b = _note(client, "B", general)
    client.post("/connections", json={"from_note_id": a["id"], "to_note_id": b["id"]})

    moved = client.post(f"/notes/{a['id']}/move", json={"board_id": other})
    assert moved.status_code == 200
    assert moved.json()["board_id"] == other
    assert client.get("/connections").json() == []
    assert client.post(f"/notes/{a['id']}/move", json={"board_id": 999}).status_code == 404
