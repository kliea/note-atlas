from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import init_db
from app.main import app
from app.models import Citation, SearchHit
from app.rag import DECLINE_TEXT, AskPlan


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "notes.db"))
    init_db()
    return TestClient(app)


def test_ask_streams_grounded_sse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    plan = AskPlan(
        question="fanout",
        grounded=True,
        citations=[
            Citation(
                note_id=3,
                note_title="Lecture: B+ trees",
                topic_id=2,
                topic_title="Disk I/O efficiency",
                score=0.8,
            )
        ],
        context_hits=[
            SearchHit(
                chunk_id=1,
                note_id=3,
                topic_id=2,
                text="High fanout reduces disk I/O.",
                score=0.8,
            )
        ],
    )
    monkeypatch.setattr("app.routers.ask.plan_ask", lambda question, k=5: plan)

    def fake_stream(_plan: AskPlan) -> Iterator[str]:
        yield "High "
        yield "fanout."

    monkeypatch.setattr("app.routers.ask.stream_answer", fake_stream)

    response = client.post("/ask", json={"question": "Why fanout?"})
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    body = response.text
    assert "event: meta" in body
    assert '"grounded": true' in body
    assert "Disk I/O efficiency" in body
    assert "High " in body
    assert "fanout." in body
    assert "event: done" in body


def test_ask_streams_decline_when_ungrounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "app.routers.ask.plan_ask",
        lambda question, k=5: AskPlan(
            question=question, grounded=False, citations=[], context_hits=[]
        ),
    )

    response = client.post("/ask", json={"question": "capital of France?"})
    assert response.status_code == 200
    assert '"grounded": false' in response.text
    assert DECLINE_TEXT in response.text
    assert "event: done" in response.text
