"""New notes must be searchable even when extraction is slow or fails."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import chunk_count, create_note, get_note, init_db
from app.embed import EMBEDDING_DIM
from app.extract import ExtractionError
from app.index import search
from app.main import app
from app.models import EnrichmentPayload, ExtractionPayload, ExtractedTopic, NoteCreate
from app.rag import plan_ask


def _axis(index: int) -> list[float]:
    vector = [0.0] * EMBEDDING_DIM
    vector[index] = 1.0
    return vector


def _fake_embed(texts: Sequence[str]) -> list[list[float]]:
    encoded: list[list[float]] = []
    for text in texts:
        lower = text.lower()
        if "fanout" in lower or "b+" in lower or "leaf" in lower:
            encoded.append(_axis(0))
        else:
            encoded.append(_axis(1))
    return encoded


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "notes.db"))
    monkeypatch.setattr("app.index.embed_texts", _fake_embed)
    init_db()
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_ambient_state() -> None:
    from app import ambient

    ambient._busy.clear()
    ambient._pending_retry.clear()
    yield
    ambient._busy.clear()
    ambient._pending_retry.clear()



def test_create_indexes_raw_note_while_extract_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ask can hit a note before the LLM finishes extracting topics."""
    client = _client(tmp_path, monkeypatch)
    created = client.post(
        "/notes",
        json={
            "title": "B+ trees",
            "source": "lecture",
            "raw_text": "High fanout keeps the tree short.",
        },
    ).json()
    assert created["extract_status"] == "pending"
    assert chunk_count() >= 1
    plan = plan_ask(
        "Why does high fanout help?",
        note_ids=[created["id"]],
        retrieve=lambda q, k: search(
            q, k=k, embed=_fake_embed, note_ids=[created["id"]]
        ),
    )
    assert plan.grounded is True
    assert any("fanout" in hit.text.lower() for hit in plan.context_hits)


def test_ask_note_also_enters_corpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    created = client.post(
        "/notes",
        json={
            "title": "Why fanout?",
            "source": "ask",
            "raw_text": "High fanout keeps the tree short.",
        },
    ).json()
    assert created["extract_status"] == "done"
    assert chunk_count() >= 1
    plan = plan_ask(
        "Why does high fanout help?",
        note_ids=[created["id"]],
        retrieve=lambda q, k: search(
            q, k=k, embed=_fake_embed, note_ids=[created["id"]]
        ),
    )
    assert plan.grounded is True


@pytest.mark.ambient
def test_failed_extraction_still_leaves_note_searchable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import ambient

    monkeypatch.setenv("DB_PATH", str(tmp_path / "notes.db"))
    monkeypatch.setattr("app.index.embed_texts", _fake_embed)
    monkeypatch.setattr(
        "app.ambient.extract_topics",
        lambda _text: (_ for _ in ()).throw(ExtractionError("ollama down")),
    )
    init_db()
    note = create_note(
        NoteCreate(
            title="B+ trees",
            source="lecture",
            raw_text="High fanout keeps the tree short.",
        )
    )
    ambient.run_extraction_job(note.id)
    refreshed = get_note(note.id)
    assert refreshed is not None
    assert refreshed.extract_status == "error"
    assert refreshed.topics == []
    assert chunk_count() >= 1
    plan = plan_ask(
        "Why does high fanout help?",
        note_ids=[note.id],
        retrieve=lambda q, k: search(q, k=k, embed=_fake_embed, note_ids=[note.id]),
    )
    assert plan.grounded is True


@pytest.mark.ambient
def test_busy_note_reschedules_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import ambient

    monkeypatch.setenv("DB_PATH", str(tmp_path / "notes.db"))
    monkeypatch.setattr("app.index.embed_texts", _fake_embed)
    calls = {"n": 0}

    def slow_extract(_text: str) -> ExtractionPayload:
        calls["n"] += 1
        return ExtractionPayload(
            topics=[
                ExtractedTopic(
                    title=f"pass-{calls['n']}",
                    points=["High fanout keeps the tree short."],
                    tags=["indexes"],
                )
            ]
        )

    monkeypatch.setattr("app.ambient.extract_topics", slow_extract)
    monkeypatch.setattr("app.ambient.enrich", lambda _note: EnrichmentPayload())
    init_db()
    note = create_note(
        NoteCreate(
            title="B+ trees",
            source="lecture",
            raw_text="High fanout keeps the tree short.",
        )
    )
    ambient._busy.add(note.id)
    ambient.run_extraction_job(note.id)
    assert calls["n"] == 0
    assert note.id in ambient._pending_retry
    ambient._busy.discard(note.id)
    ambient.run_extraction_job(note.id)
    assert calls["n"] >= 1
    refreshed = get_note(note.id)
    assert refreshed is not None
    assert refreshed.extract_status == "done"
    assert refreshed.topics[0].title.startswith("pass-")
