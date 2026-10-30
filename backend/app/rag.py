"""Retrieve note chunks and answer only from that context."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass

from app.db import get_note
from app.index import search
from app.llm import chat_stream
from app.models import Citation, SearchHit

# Live unrelated hits sat around 0.02–0.22; on-topic topics were ~0.75+.
# Title questions like "what is midv:2020" often land ~0.20 on MiniLM, so
# plan_ask also boosts chunks that lexically contain the query.
SCORE_THRESHOLD = 0.35
DECLINE_TEXT = "I don't have that in the notes."

_QUESTION_PREFIX = re.compile(
    r"^(please )?(what(?:s| is| are| was| were)? |"
    r"who(?: is| are)? |where(?: is| are)? |when(?: is| was)? |"
    r"why(?: is| are| do| does)? |how(?: do| does| is| are)? |"
    r"explain |define |describe |tell me about |summarize )"
)

# "summarize these notes" does not look like the note text, so vector search
# scores it as off-topic even when the user just lassoed the sources.
_OVERVIEW_QUESTION = re.compile(
    r"(summar(?:y|ize|ise)|overview|tldr|all contents?|"
    r"what(?:'s| is) in (?:these|this|the) notes?)",
    re.I,
)

_SYSTEM = """You answer questions using ONLY the notes context in the user message.
If the question asks to summarize, outline, or list what is in the notes, do that from the context.
If the context does not contain the answer, reply exactly:
I don't have that in the notes.
Do not use outside knowledge. Do not invent facts. Be concise.
Output only the answer — no preamble or analysis.
"""


def _normalized(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def lexical_score(question: str, text: str) -> float:
    """Phrase/token overlap after stripping question syntax and punctuation."""
    query = _normalized(question)
    haystack = _normalized(text)
    if not query or not haystack:
        return 0.0
    core = _QUESTION_PREFIX.sub("", query).strip() or query
    if len(core) >= 4 and core in haystack:
        return 1.0
    terms = [token for token in core.split() if len(token) >= 3]
    if not terms:
        return 0.0
    tokens = haystack.split()
    need = set(terms)
    span = max(len(terms) + 1, 4)
    for index in range(len(tokens)):
        if need <= set(tokens[index : index + span]):
            return 1.0
    return 0.0


def _boost_hits(question: str, hits: Sequence[SearchHit]) -> list[SearchHit]:
    boosted: list[SearchHit] = []
    for hit in hits:
        lex = lexical_score(question, hit.text)
        # Token overlap of 0.5 (one of two words) is not enough to override MiniLM.
        score = max(hit.score, lex) if lex >= 0.8 else hit.score
        boosted.append(hit.model_copy(update={"score": score}) if score != hit.score else hit)
    return boosted


@dataclass(frozen=True)
class AskPlan:
    question: str
    grounded: bool
    citations: list[Citation]
    context_hits: list[SearchHit]


def _selected_note_hits(note_ids: Sequence[int]) -> list[SearchHit]:
    """Build context from the notes the user pointed at, not from query similarity."""
    hits: list[SearchHit] = []
    for note_id in note_ids:
        note = get_note(note_id)
        if note is None:
            continue
        parts = [note.title.strip(), note.raw_text.strip()]
        for topic in note.topics:
            points = [point.text.strip() for point in topic.points if point.text.strip()]
            if topic.title.strip():
                parts.append(topic.title.strip())
            parts.extend(points)
        text = "\n".join(part for part in parts if part)
        if not text:
            continue
        hits.append(
            SearchHit(
                chunk_id=0,
                note_id=note.id,
                topic_id=None,
                text=text,
                score=1.0,
            )
        )
    return hits


def plan_ask(
    question: str,
    k: int = 5,
    note_ids: Sequence[int] | None = None,
    retrieve: Callable[[str, int], list[SearchHit]] | None = None,
    board_id: int | None = None,
) -> AskPlan:
    """Retrieve chunks and decide whether the context is strong enough."""
    if retrieve is not None:
        hits = retrieve(question.strip(), k)
    elif note_ids:
        hits = search(
            question.strip(),
            k=max(k, len(note_ids) * 2),
            note_ids=list(note_ids),
            board_id=board_id,
        )
    else:
        hits = search(question.strip(), k=max(k, 10), board_id=board_id)
    if note_ids:
        allowed = set(note_ids)
        hits = [hit for hit in hits if hit.note_id in allowed]
    hits = _boost_hits(question.strip(), hits)
    strong = [hit for hit in hits if hit.score >= SCORE_THRESHOLD]
    # A lasso/selection already names the sources. Overview prompts and weak
    # vector scores must still read those notes instead of declining.
    if note_ids and (not strong or _OVERVIEW_QUESTION.search(question)):
        selected = _selected_note_hits(note_ids)
        if selected:
            strong = selected
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
