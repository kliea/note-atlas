"""Retrieve note chunks and answer only from that context."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass

from app.db import get_note
from app.index import search
from app.llm import chat_stream
from app.models import Citation, SearchHit

# Live unrelated hits sat around 0.02–0.22; on-topic topics were ~0.75+.
SCORE_THRESHOLD = 0.35
DECLINE_TEXT = "I don't have that in the notes."

_SYSTEM = """You answer questions using ONLY the notes context in the user message.
If the context does not contain the answer, reply exactly:
I don't have that in the notes.
Do not use outside knowledge. Do not invent facts. Be concise.
Output only the answer — no preamble or analysis.
"""


@dataclass(frozen=True)
class AskPlan:
    question: str
    grounded: bool
    citations: list[Citation]
    context_hits: list[SearchHit]


def plan_ask(
    question: str,
    k: int = 5,
    retrieve: Callable[[str, int], list[SearchHit]] | None = None,
) -> AskPlan:
    """Retrieve chunks and decide whether the context is strong enough."""
    fetch = retrieve or (lambda q, top_k: search(q, k=top_k))
    hits = fetch(question.strip(), k)
    strong = [hit for hit in hits if hit.score >= SCORE_THRESHOLD]
    citations = _citations(strong)
    return AskPlan(
        question=question.strip(),
        grounded=len(strong) > 0,
        citations=citations,
        context_hits=strong,
    )


def build_prompt(plan: AskPlan) -> list[dict[str, str]]:
    blocks: list[str] = []
    for index, hit in enumerate(plan.context_hits, start=1):
        citation = next(
            (
                item
                for item in plan.citations
                if item.note_id == hit.note_id and item.topic_id == hit.topic_id
            ),
            None,
        )
        label = citation.note_title if citation else f"note {hit.note_id}"
        topic = citation.topic_title if citation and citation.topic_title else "summary"
        blocks.append(f"[{index}] Note: {label} | Topic: {topic}\n{hit.text}")
    context = "\n\n".join(blocks) if blocks else "(no matching notes)"
    user = f"Context:\n{context}\n\nQuestion: {plan.question}"
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user},
    ]


def stream_answer(
    plan: AskPlan,
    generate: Callable[[list[dict[str, str]]], Iterator[str]] | None = None,
) -> Iterator[str]:
    """Yield answer tokens. Weak context never calls the model."""
    if not plan.grounded:
        yield DECLINE_TEXT
        return
    stream = generate or chat_stream
    yield from stream(build_prompt(plan))


def _citations(hits: Sequence[SearchHit]) -> list[Citation]:
    seen: set[tuple[int, int | None]] = set()
    citations: list[Citation] = []
    for hit in hits:
        key = (hit.note_id, hit.topic_id)
        if key in seen:
            continue
        seen.add(key)
        note = get_note(hit.note_id)
        if note is None:
            continue
        topic_title: str | None = None
        if hit.topic_id is not None:
            for topic in note.topics:
                if topic.id == hit.topic_id:
                    topic_title = topic.title
                    break
        citations.append(
            Citation(
                note_id=note.id,
                note_title=note.title,
                topic_id=hit.topic_id,
                topic_title=topic_title,
                score=hit.score,
            )
        )
    return citations
