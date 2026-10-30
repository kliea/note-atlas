from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import apply_point_additions, get_note, init_db, replace_note_extraction
from app.embed import EMBEDDING_DIM
from app.index import index_note, reindex_all, search
from app.main import app
from app.models import ExtractedTopic, PointAddition
from app.rag import plan_ask


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
    assert set(hits[0].keys()) == {"chunk_id", "note_id", "topic_id", "text", "score"}
    assert hits[0]["score"] >= hits[1]["score"]
    top = hits[0]["text"].lower()
    assert "tree" in top or "leaf" in top
    assert hits[0]["note_id"] == trees["id"]
    assert hits[0]["topic_id"] is not None or "b+ trees" in top


def test_search_note_ids_keeps_only_scoped_notes(
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
                tags=["b-tree"],
            )
        ],
    )
    replace_note_extraction(
        pasta["id"],
        [
            ExtractedTopic(
                title="Boiling pasta",
                points=["Salt the water before the pasta goes in"],
                tags=["cooking"],
            )
        ],
    )
    index_note(trees["id"], embed=_fake_embed)
    index_note(pasta["id"], embed=_fake_embed)

    trees_only = search("pasta recipe", k=5, embed=_fake_embed, note_ids=[trees["id"]])
    assert trees_only
    assert all(hit.note_id == trees["id"] for hit in trees_only)
    pasta_only = search("b+ tree leaf nodes", k=5, embed=_fake_embed, note_ids=[pasta["id"]])
    assert pasta_only
    assert all(hit.note_id == pasta["id"] for hit in pasta_only)


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


FLYWHEEL = "Traditional SaaS vs AI-as-a-service > flywheel model"
FLYWHEEL_CONTEXT = (
    "A flywheel is a loop where usage improves the product, which attracts more usage."
)


def _context_embed(texts: Sequence[str]) -> list[list[float]]:
    encoded: list[list[float]] = []
    for text in texts:
        lower = text.lower()
        if "loop where usage" in lower:
            encoded.append(_axis(0))
        else:
            encoded.append(_axis(2))
    return encoded


def test_index_includes_suggested_point_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "notes.db"))
    monkeypatch.setattr("app.index.embed_texts", _context_embed)
    init_db()
    client = TestClient(app)
    created = client.post(
        "/notes",
        json={"title": "Matsuo Lab", "source": "lecture", "raw_text": FLYWHEEL},
    ).json()
    replace_note_extraction(
        created["id"],
        [
            ExtractedTopic(
                title="AI-as-a-Service Models",
                points=[FLYWHEEL],
                tags=["ai"],
            )
        ],
    )
    note = get_note(created["id"])
    assert note is not None
    point_id = note.topics[0].points[0].id
    apply_point_additions([PointAddition(point_id=point_id, context=FLYWHEEL_CONTEXT)])

    index_note(created["id"], embed=_context_embed)
    query = "loop where usage improves the product"
    hits = search(query, k=5, embed=_context_embed)
    assert hits
    assert "loop where usage" in hits[0].text.lower()
    plan = plan_ask(query, retrieve=lambda q, k: search(q, k=k, embed=_context_embed))
    assert plan.grounded is True


def test_index_omits_dismissed_point_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "notes.db"))
    monkeypatch.setattr("app.index.embed_texts", _context_embed)
    init_db()
    client = TestClient(app)
    created = client.post(
        "/notes",
        json={"title": "Matsuo Lab", "source": "lecture", "raw_text": FLYWHEEL},
    ).json()
    replace_note_extraction(
        created["id"],
        [
            ExtractedTopic(
                title="AI-as-a-Service Models",
                points=[FLYWHEEL],
                tags=["ai"],
            )
        ],
    )
    note = get_note(created["id"])
    assert note is not None
    point = note.topics[0].points[0]
    apply_point_additions([PointAddition(point_id=point.id, context=FLYWHEEL_CONTEXT)])
    from app.db import patch_point
    from app.models import PointPatch

    patch_point(point.id, PointPatch(context_status="dismissed"))
    index_note(created["id"], embed=_context_embed)
    hits = search("loop where usage improves the product", k=5, embed=_context_embed)
    assert hits
    assert "loop where usage" not in hits[0].text.lower()
    plan = plan_ask(
        "loop where usage improves the product",
        retrieve=lambda q, k: search(q, k=k, embed=_context_embed),
    )
    assert plan.grounded is False


def test_search_scoped_to_notes_past_the_vec_k_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """sqlite-vec caps k at 4096; selected-note search must not ask for every chunk."""
    from app.db import replace_note_chunks
    from app.embed import serialize_embedding

    client = _client(tmp_path, monkeypatch)
    crowd = client.post(
        "/notes", json={"title": "Crowd", "source": "test", "raw_text": "B+ tree crowd"}
    ).json()
    target = client.post(
        "/notes", json={"title": "Target", "source": "test", "raw_text": "pasta"}
    ).json()
    near = serialize_embedding(_axis(0))
    replace_note_chunks(crowd["id"], [(None, f"crowd {i}", near) for i in range(4100)])
    replace_note_chunks(target["id"], [(None, "target pasta", serialize_embedding(_axis(1)))])

    hits = search("b+ tree", k=3, embed=_fake_embed, note_ids=[target["id"]])

    assert [hit.note_id for hit in hits] == [target["id"]]
    assert hits[0].text == "target pasta"
