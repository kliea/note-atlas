from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.models import Citation, NoteDetail, SearchHit, Topic
from app.rag import DECLINE_TEXT, AskPlan, build_prompt, lexical_score, plan_ask, stream_answer


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
    monkeypatch.setattr("app.rag.search", lambda q, k=5, board_id=None: [_hit(score=0.12)])
    monkeypatch.setattr("app.rag.get_note", lambda _id: _note())
    plan = plan_ask("What is the capital of France?")
    assert plan.grounded is False
    assert plan.citations == []


def test_plan_ask_cites_strong_topic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.rag.search", lambda q, k=5, board_id=None: [_hit(score=0.81)])
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
    assert declined.grounded is True
    assert [item.note_id for item in declined.citations] == [3]
    assert any("fanout" in hit.text.lower() for hit in declined.context_hits)


def test_lexical_score_matches_punctuated_title_query() -> None:
    text = (
        "MIDV 2020: A Comprehensive Benchmark Dataset for Identity Document Analysis\n"
        "identity documents recognition"
    )
    assert lexical_score("what is midv:2020", text) >= 0.8
    assert (
        lexical_score(
            "what is midv:2020",
            "MIDV 500: A Comprehensive Benchmark Dataset\n"
            "https://smartengines.com/wp-content/uploads/2020/04/datasets-of-id-documents-midv-500.pdf",
        )
        < 0.8
    )
    assert lexical_score("What is the capital of France?", text) < 0.35


def test_plan_ask_grounds_low_vector_when_title_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    note = NoteDetail(
        id=13,
        title="MIDV 2020: A Comprehensive Benchmark Dataset for Identity Document Analysis",
        source="lecture",
        created_at="2026-09-21T00:00:00+00:00",
        raw_text="identity documents recognition",
        topics=[],
    )
    monkeypatch.setattr("app.rag.get_note", lambda _id: note)
    hit = SearchHit(
        chunk_id=7,
        note_id=13,
        topic_id=None,
        text="MIDV 2020: A Comprehensive Benchmark Dataset for Identity Document Analysis",
        score=0.19,
    )
    plan = plan_ask("what is midv:2020", retrieve=lambda _q, _k: [hit])
    assert plan.grounded is True
    assert plan.citations[0].note_id == 13
    assert plan.context_hits[0].score >= 0.35


def test_plan_ask_scoped_summarize_uses_selected_notes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lasso + 'summarize these notes' must not decline just because the query
    does not look like the note text in embedding space."""
    first = _note()
    second = NoteDetail(
        id=7,
        title="Pasta recipes",
        source="kitchen",
        created_at="2026-09-17T00:00:00+00:00",
        raw_text="Boil water and salt the pasta water.",
        topics=[],
    )
    notes = {first.id: first, second.id: second}
    monkeypatch.setattr("app.rag.get_note", lambda note_id: notes.get(note_id))

    def retrieve(_question: str, _k: int) -> list[SearchHit]:
        return [
            _hit(score=0.11, note_id=3),
            _hit(score=0.09, note_id=7, topic_id=None),
        ]

    plan = plan_ask(
        "summarize all contents of this note",
        note_ids=[3, 7],
        retrieve=retrieve,
    )
    assert plan.grounded is True
    texts = "\n".join(hit.text.lower() for hit in plan.context_hits)
    assert "fanout" in texts
    assert "pasta" in texts
    assert {item.note_id for item in plan.citations} == {3, 7}
    prompt = build_prompt(plan)[1]["content"].lower()
    assert "fanout" in prompt
    assert "pasta" in prompt


def test_plan_ask_unscoped_summarize_still_declines_weak_hits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.rag.search", lambda q, k=5, board_id=None: [_hit(score=0.11)])
    monkeypatch.setattr("app.rag.get_note", lambda _id: _note())
    plan = plan_ask("summarize all contents of this note")
    assert plan.grounded is False
    assert plan.citations == []
