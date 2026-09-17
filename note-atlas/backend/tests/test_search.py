from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import init_db, replace_note_extraction
from app.embed import EMBEDDING_DIM
from app.index import index_note, reindex_all
from app.main import app
from app.models import ExtractedTopic


def _axis(index: int) -> list[float]:
    vector = [0.0] * EMBEDDING_DIM
    vector[index] = 1.0
    return vector


def _fake_embed(texts: Sequence[str]) -> list[list[float]]:
    """Fixed embeddings so ranking does not depend on MiniLM weights."""
    encoded: list[list[float]] = []
    for text in texts:
        lower = text.lower()
        if "b+ tree" in lower or "b-tree" in lower or "leaf node" in lower:
            encoded.append(_axis(0))
        elif "pasta" in lower or "recipe" in lower:
            encoded.append(_axis(1))
        else:
            encoded.append(_axis(2))
    return encoded


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "notes.db"))
    monkeypatch.setattr("app.index.embed_texts", _fake_embed)
    init_db()
    return TestClient(app)


def test_search_ranks_relevant_chunk_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)

    trees = client.post(
        "/notes",
        json={
            "title": "B+ trees",
            "source": "lecture",
            "raw_text": "Leaf nodes store keys. Internal nodes route searches.",
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
                points=["Leaf nodes store keys and record pointers"],
                tags=["b-tree", "indexes"],
            )
        ],
    )
    replace_note_extraction(
        pasta["id"],
        [
            ExtractedTopic(
                title="Boiling pasta",
                points=["Salt the water before the pasta goes in"],
                tags=["cooking", "recipe"],
            )
        ],
    )
    index_note(trees["id"], embed=_fake_embed)
    index_note(pasta["id"], embed=_fake_embed)

    response = client.get("/search", params={"q": "b+ tree leaf nodes", "k": 5})
    assert response.status_code == 200
    hits = response.json()
    assert len(hits) >= 2
    assert hits[0]["score"] >= hits[1]["score"]
    top = hits[0]["text"].lower()
    assert "tree" in top or "leaf" in top
    assert hits[0]["note_id"] == trees["id"]
    assert hits[0]["topic_id"] is not None or "b+ trees" in top


def test_reindex_rebuilds_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    created = client.post(
        "/notes",
        json={
            "title": "B+ trees",
            "source": "lecture",
            "raw_text": "Leaf nodes store keys.",
        },
    ).json()
    replace_note_extraction(
        created["id"],
        [
            ExtractedTopic(
                title="B+ tree leaves",
                points=["Leaf nodes store keys"],
                tags=["b-tree"],
            )
        ],
    )
    first = index_note(created["id"], embed=_fake_embed)
    rebuilt = reindex_all(embed=_fake_embed)
    assert rebuilt["notes"] == 1
    assert rebuilt["chunks"] == first

    via_http = client.post("/reindex")
    assert via_http.status_code == 200
    body = via_http.json()
    assert body["notes"] == 1
    assert body["chunks"] == first

    ranked = client.get("/search", params={"q": "leaf node"})
    assert ranked.status_code == 200
    assert ranked.json()[0]["note_id"] == created["id"]
