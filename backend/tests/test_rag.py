from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.models import Citation, NoteDetail, SearchHit, Topic
from app.rag import DECLINE_TEXT, AskPlan, build_prompt, plan_ask, stream_answer


def _hit(*, score: float, note_id: int = 3, topic_id: int | None = 2) -> SearchHit:
    return SearchHit(
        chunk_id=1,
        note_id=note_id,
        topic_id=topic_id,
        text="High fanout keeps the tree short and reduces disk I/O.",
        score=score,
    )


def _note() -> NoteDetail:
    return NoteDetail(
        id=3,
        title="Lecture: B+ trees",
        source="lecture",
        created_at="2026-09-17T00:00:00+00:00",
        raw_text="fanout notes",
        topics=[
            Topic(
                id=2,
                note_id=3,
                title="Disk I/O efficiency",
                order_idx=1,
                points=[],
                tags=[],
            )
        ],
    )


def test_plan_ask_declines_weak_scores(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.rag.search", lambda q, k=5: [_hit(score=0.12)])
    monkeypatch.setattr("app.rag.get_note", lambda _id: _note())
    plan = plan_ask("What is the capital of France?")
    assert plan.grounded is False
    assert plan.citations == []


def test_plan_ask_cites_strong_topic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.rag.search", lambda q, k=5: [_hit(score=0.81)])
    monkeypatch.setattr("app.rag.get_note", lambda _id: _note())
    plan = plan_ask("Why does fanout reduce disk I/O?")
    assert plan.grounded is True
    assert plan.citations == [
        Citation(
            note_id=3,
            note_title="Lecture: B+ trees",
            topic_id=2,
            topic_title="Disk I/O efficiency",
            score=0.81,
        )
    ]
    prompt = build_prompt(plan)
    assert "Disk I/O efficiency" in prompt[1]["content"]
    assert "fanout" in prompt[1]["content"].lower()


def test_stream_answer_skips_llm_when_ungrounded() -> None:
    called = {"n": 0}

    def fake_generate(_messages: list[dict[str, str]]) -> Iterator[str]:
        called["n"] += 1
        yield "hallucination"

    plan = AskPlan(question="moon cheese?", grounded=False, citations=[], context_hits=[])
    tokens = list(stream_answer(plan, generate=fake_generate))
    assert tokens == [DECLINE_TEXT]
    assert called["n"] == 0


def test_stream_answer_uses_model_when_grounded() -> None:
    plan = AskPlan(
        question="fanout?",
        grounded=True,
        citations=[],
        context_hits=[_hit(score=0.8)],
    )
    tokens = list(stream_answer(plan, generate=lambda _m: iter(["High ", "fanout."])))
    assert "".join(tokens) == "High fanout."


def test_plan_ask_note_ids_drops_outside_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.rag.get_note", lambda note_id: _note() if note_id == 3 else None)

    def retrieve(_question: str, _k: int) -> list[SearchHit]:
        return [_hit(score=0.9, note_id=3), _hit(score=0.95, note_id=9, topic_id=4)]

    scoped = plan_ask("fanout?", note_ids=[3], retrieve=retrieve)
    assert scoped.grounded is True
    assert [item.note_id for item in scoped.citations] == [3]

    def only_outside(_question: str, _k: int) -> list[SearchHit]:
        return [_hit(score=0.95, note_id=9, topic_id=4)]

    declined = plan_ask("fanout?", note_ids=[3], retrieve=only_outside)
    assert declined.grounded is False
    assert declined.citations == []
