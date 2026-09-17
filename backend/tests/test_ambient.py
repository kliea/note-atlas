from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import init_db, replace_note_extraction
from app.embed import EMBEDDING_DIM
from app.index import index_note
from app.main import app
from app.models import ExtractedTopic, RephrasedNote

SAMPLE_NOTE = """
Lecture: B+ trees in database indexes
- Leaf nodes store keys plus pointers to records
- Internal nodes only route the search
"""

VALID_JSON = {
    "topics": [
        {
            "title": "B+ tree structure",
            "points": [
                "Leaves hold keys and record pointers",
                "Internal nodes route searches",
            ],
            "tags": ["b-tree", "indexes"],
        }
    ]
}

PASTA_JSON = {
    "topics": [
        {
            "title": "Boiling pasta",
            "points": ["Salt the water before the pasta goes in"],
            "tags": ["cooking", "recipe"],
        }
    ]
}


def _axis(index: int) -> list[float]:
    vector = [0.0] * EMBEDDING_DIM
    vector[index] = 1.0
    return vector


def _fake_embed(texts: Sequence[str]) -> list[list[float]]:
    encoded: list[list[float]] = []
    for text in texts:
        lower = text.lower()
        if "b+" in lower or "b-tree" in lower or "leaf" in lower:
            encoded.append(_axis(0))
        elif "pasta" in lower or "recipe" in lower:
            encoded.append(_axis(1))
        else:
            encoded.append(_axis(2))
    return encoded


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "notes.db"))
    init_db()
    return TestClient(app)


def test_spatial_patch_does_not_queue_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    created = client.post(
        "/notes", json={"title": "Stay idle-ish", "source": "", "raw_text": "body"}
    ).json()
    patched = client.patch(f"/notes/{created['id']}", json={"x": 12.0, "y": 34.0})
    assert patched.status_code == 200
    assert patched.json()["extract_status"] == "pending"
    assert patched.json()["x"] == 12.0
    assert patched.json()["raw_text"] == "body"


@pytest.mark.ambient
def test_create_extracts_in_background(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    replies = [json.dumps(VALID_JSON)]
    monkeypatch.setattr(
        "app.extract.chat",
        lambda messages, json_mode=False: replies.pop(0),
    )
    monkeypatch.setattr(
        "app.ambient.rephrase_jot",
        lambda text, title="": RephrasedNote(
            title="B+ trees",
            body=(
                "Leaf nodes store keys plus pointers to records.\n"
                "Internal nodes only route the search."
            ),
        ),
    )
    monkeypatch.setattr("app.index.embed_texts", _fake_embed)
    client = _client(tmp_path, monkeypatch)
    created = client.post(
        "/notes",
        json={
            "title": "B+ trees",
            "source": "lecture",
            "raw_text": SAMPLE_NOTE,
        },
    )
    assert created.status_code == 201
    assert created.json()["extract_status"] == "pending"
    body = client.get(f"/notes/{created.json()['id']}").json()
    assert body["extract_status"] == "done"
    assert body["title"] == "B+ trees"
    assert "Leaf nodes store keys" in body["raw_text"]
    assert len(body["topics"]) == 1
    assert body["topics"][0]["title"] == "B+ tree structure"
    assert [tag["tag"] for tag in body["topics"][0]["tags"]] == ["b-tree", "indexes"]
    assert replies == []


@pytest.mark.ambient
def test_create_rephrases_jot_before_topics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    replies = [json.dumps(VALID_JSON)]
    monkeypatch.setattr(
        "app.extract.chat",
        lambda messages, json_mode=False: replies.pop(0),
    )
    monkeypatch.setattr(
        "app.ambient.rephrase_jot",
        lambda text, title="": RephrasedNote(
            title="B+ tree range scans",
            body=(
                "Linked leaves let you walk keys in order without hashing. "
                "Fanout still beats binary trees on disk I/O."
            ),
        ),
    )
    monkeypatch.setattr("app.index.embed_texts", _fake_embed)
    client = _client(tmp_path, monkeypatch)
    created = client.post(
        "/notes",
        json={
            "title": "b+ scan",
            "source": "",
            "raw_text": "linked leaves, high fanout, less disk io",
        },
    ).json()
    body = client.get(f"/notes/{created['id']}").json()
    assert body["extract_status"] == "done"
    assert body["title"] == "B+ tree range scans"
    assert "Linked leaves" in body["raw_text"]
    assert body["topics"][0]["title"] == "B+ tree structure"


@pytest.mark.ambient
def test_text_patch_reextracts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    replies = [json.dumps(VALID_JSON), json.dumps(PASTA_JSON)]
    monkeypatch.setattr(
        "app.extract.chat",
        lambda messages, json_mode=False: replies.pop(0),
    )
    polished = [
        RephrasedNote(title="B+ trees", body=SAMPLE_NOTE.strip()),
        RephrasedNote(title="Pasta", body="Salt the pasta water before boiling."),
    ]
    monkeypatch.setattr(
        "app.ambient.rephrase_jot",
        lambda text, title="": polished.pop(0),
    )
    monkeypatch.setattr("app.index.embed_texts", _fake_embed)
    client = _client(tmp_path, monkeypatch)
    created = client.post(
        "/notes",
        json={"title": "Draft", "source": "", "raw_text": SAMPLE_NOTE},
    ).json()
    first = client.get(f"/notes/{created['id']}").json()
    assert first["topics"][0]["title"] == "B+ tree structure"
    patched = client.patch(
        f"/notes/{created['id']}",
        json={"title": "Pasta", "raw_text": "Salt the pasta water."},
    )
    assert patched.status_code == 200
    assert patched.json()["extract_status"] == "pending"
    body = client.get(f"/notes/{created['id']}").json()
    assert body["extract_status"] == "done"
    assert body["title"] == "Pasta"
    assert "Salt the pasta water before boiling" in body["raw_text"]
    assert body["topics"][0]["title"] == "Boiling pasta"
    assert replies == []
    assert polished == []

@pytest.mark.ambient
def test_suggestions_prefer_embeddings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.index.embed_texts", _fake_embed)
    client = _client(tmp_path, monkeypatch)
    trees = client.post(
        "/notes",
        json={
            "title": "B+ trees",
            "source": "lecture",
            "raw_text": "Leaf nodes store keys.",
        },
    ).json()
    cousin = client.post(
        "/notes",
        json={
            "title": "Index internals",
            "source": "lecture",
            "raw_text": "B+ tree leaf nodes walk in order.",
        },
    ).json()
    pasta = client.post(
        "/notes",
        json={
            "title": "Pasta recipes",
            "source": "kitchen",
            "raw_text": "Boil water and salt the pasta water.",
        },
    ).json()
    replace_note_extraction(
        trees["id"],
        [
            ExtractedTopic(
                title="B+ tree leaves",
                points=["Leaf nodes store keys"],
                tags=["b-tree", "indexes"],
            )
        ],
    )
    replace_note_extraction(
        cousin["id"],
        [
            ExtractedTopic(
                title="Leaf walk",
                points=["B+ tree leaf nodes"],
                tags=["b-tree"],
            )
        ],
    )
    replace_note_extraction(
        pasta["id"],
        [
            ExtractedTopic(
                title="Boiling pasta",
                points=["Salt the pasta"],
                tags=["cooking", "recipe"],
            )
        ],
    )
    index_note(trees["id"], embed=_fake_embed)
    index_note(cousin["id"], embed=_fake_embed)
    index_note(pasta["id"], embed=_fake_embed)

    response = client.get(f"/notes/{trees['id']}/suggestions")
    assert response.status_code == 200
    items = response.json()
    assert items
    assert items[0]["note_id"] == cousin["id"]
    assert items[0]["reason"] == "embedding"
    assert items[0]["score"] >= 0.42
    assert all(item["note_id"] != pasta["id"] for item in items)
    assert set(items[0].keys()) == {"note_id", "title", "score", "reason"}


def test_suggestions_shared_tag_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    trees = client.post(
        "/notes",
        json={"title": "B+ trees", "source": "", "raw_text": "indexes"},
    ).json()
    cousin = client.post(
        "/notes",
        json={"title": "Hash vs tree", "source": "", "raw_text": "indexes too"},
    ).json()
    pasta = client.post(
        "/notes",
        json={"title": "Pasta", "source": "", "raw_text": "noodles"},
    ).json()
    replace_note_extraction(
        trees["id"],
        [
            ExtractedTopic(
                title="Indexes",
                points=["B+ trees"],
                tags=["b-tree", "indexes"],
            )
        ],
    )
    replace_note_extraction(
        cousin["id"],
        [
            ExtractedTopic(
                title="Indexes again",
                points=["Hash indexes"],
                tags=["b-tree", "hash-index"],
            )
        ],
    )
    replace_note_extraction(
        pasta["id"],
        [
            ExtractedTopic(
                title="Dinner",
                points=["Salt water"],
                tags=["cooking"],
            )
        ],
    )

    response = client.get(f"/notes/{trees['id']}/suggestions")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["note_id"] == cousin["id"]
    assert items[0]["reason"] == "shared-tag"


def test_suggestions_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    assert client.get("/notes/999/suggestions").status_code == 404
