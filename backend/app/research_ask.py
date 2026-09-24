"""Ask across Papers: retrieve Extraction fields and Claims, and answer only from them.

Decision (docs/specs/research-track.md, "Ask"; issue #14):
- Its own index (research_chunks + research_vec): research question, method, key results,
  scope, and every live Claim of each Paper. No full text, no Leads, and never the board's
  notes; board Ask likewise never sees this index.
- Scope: the Papers selected in the Library, or the whole Library.
- Reuses the board Ask's grounding: MiniLM retrieval, lexical boost, decline when weak.
- Citations are numbered like the context blocks, so "[2]" in an answer is citation 2,
  and each one names the exact Claim or field it came from.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, replace

from app.db import get_connection
from app.embed import embed_texts, serialize_embedding
from app.llm import chat_stream
from app.models import ResearchCitation
from app.rag import SCORE_THRESHOLD, lexical_score

log = logging.getLogger(__name__)

DECLINE_TEXT = "I don't have that in these papers."
MAX_CONTEXT = 24
_POOL = 80

FIELDS: tuple[tuple[str, str], ...] = (
    ("research_question", "Research question"),
    ("method", "Method"),
    ("key_results", "Key results"),
    ("scope", "Scope"),
)
_FIELD_LABELS = dict(FIELDS)

# "What limitations do these papers share?" doesn't look like any one Limitation in embedding
# space, so a question that names a kind of entry pulls in entries of that kind.
_KIND_WORDS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\blimitations?\b|\bweakness(?:es)?\b|\bshortcomings?\b|\bgaps?\b", re.I), "limitation"),
    (re.compile(r"\bcontributions?\b|\bnovelty\b|\bwhat(?:'s| is) new\b", re.I), "contribution"),
    (re.compile(r"\bmethods?\b|\bmethodolog(?:y|ies)\b|\bapproach(?:es)?\b", re.I), "method"),
    (re.compile(r"\bresearch questions?\b", re.I), "research_question"),
    (re.compile(r"\bresults?\b|\bfindings?\b", re.I), "key_results"),
    (re.compile(r"\bscopes?\b", re.I), "scope"),
)
# Overview prompts over a selection read the selected Papers whole, as board Ask does for a lasso.
_OVERVIEW = re.compile(r"summar(?:y|ize|ise)|overview|tldr|compare|what(?:'s| is| are) in (?:these|this)", re.I)

_SYSTEM = """You answer questions about research papers using ONLY the numbered context in the user message.
Each context entry is one field or one claim from one paper. Cite the entries you use inline, like [2] or [1][3].
If the context does not contain the answer, reply exactly:
I don't have that in these papers.
Do not use outside knowledge. Do not invent facts. Be concise.
Output only the answer — no preamble or analysis.
"""

EmbedFn = Callable[[Sequence[str]], list[list[float]]]


@dataclass(frozen=True)
class Entry:
    chunk_id: int
    study_id: int
    study_title: str
    field: str | None
    claim_id: int | None
    kind: str  # a field name, "contribution", or "limitation"
    label: str
    text: str
    score: float = 0.0


# --- index ---------------------------------------------------------------------------


def _entries_for(conn: sqlite3.Connection, study_id: int) -> list[tuple[str | None, int | None, str]]:
    """(field, claim_id, text) for one Paper; nothing for a Lead or an unextracted Paper."""
    study = conn.execute("SELECT * FROM studies WHERE id = ?", (study_id,)).fetchone()
    if study is None or study["state"] != "paper":
        return []
    out: list[tuple[str | None, int | None, str]] = []
    for field, label in FIELDS:
        value = (study[field] or "").strip()
        if value:
            out.append((field, None, f"{label}: {value}"))
    for claim in conn.execute(
        "SELECT * FROM claims WHERE study_id = ? AND deleted = 0 ORDER BY kind, order_idx", (study_id,)
    ):
        kind = "Contribution" if claim["kind"] == "contribution" else "Limitation"
        whose = "" if claim["author"] == "paper" else " (the reader's)"
        quote = f'\nQuote: "{claim["quote"]}"' if claim["quote"] else ""
        out.append((None, int(claim["id"]), f"{kind}{whose}: {claim['text']}{quote}"))
    return out


def _clear(conn: sqlite3.Connection, study_id: int) -> None:
    ids = [int(r[0]) for r in conn.execute("SELECT id FROM research_chunks WHERE study_id = ?", (study_id,))]
    for chunk_id in ids:
        conn.execute("DELETE FROM research_vec WHERE rowid = ?", (chunk_id,))
    conn.execute("DELETE FROM research_chunks WHERE study_id = ?", (study_id,))


def index_paper(study_id: int, embed: EmbedFn | None = None) -> int:
    """Replace one Paper's entries in the Research Ask index. Returns how many were written."""
    conn = get_connection()
    try:
        entries = _entries_for(conn, study_id)
    finally:
        conn.close()
    vectors = (embed or embed_texts)([text for _, _, text in entries]) if entries else []
    conn = get_connection()
    try:
        _clear(conn, study_id)
        for (field, claim_id, text), vector in zip(entries, vectors, strict=True):
            cursor = conn.execute(
                "INSERT INTO research_chunks (study_id, field, claim_id, text) VALUES (?, ?, ?, ?)",
                (study_id, field, claim_id, text),
            )
            conn.execute(
                "INSERT INTO research_vec (rowid, embedding) VALUES (?, ?)",
                (int(cursor.lastrowid), serialize_embedding(vector)),
            )
        conn.commit()
        return len(entries)
    finally:
        conn.close()


def reindex_quietly(study_id: int | None) -> None:
    """Best effort after a Claim or Extraction change: Ask must never block an edit."""
    if study_id is None:
        return
    try:
        index_paper(study_id)
    except Exception:  # noqa: BLE001
        log.exception("could not re-index study %s for Research Ask", study_id)


def _index_missing(study_ids: Sequence[int] | None) -> None:
    """Extracted Papers with no entries yet (e.g. extracted before this index existed)."""
    conn = get_connection()
    try:
        scope = ""
        params: list[object] = []
        if study_ids:
            scope = f" AND s.id IN ({','.join('?' for _ in study_ids)})"
            params = list(study_ids)
        rows = conn.execute(
            f"""
            SELECT s.id FROM studies s
            WHERE s.state = 'paper' AND s.extracted_at IS NOT NULL{scope}
              AND NOT EXISTS (SELECT 1 FROM research_chunks c WHERE c.study_id = s.id)
            """,
            params,
        ).fetchall()
    finally:
        conn.close()
    for row in rows:
        index_paper(int(row[0]))


# --- retrieval -----------------------------------------------------------------------


def _kind(field: str | None, text: str) -> str:
    if field:
        return field
    return "contribution" if text.startswith("Contribution") else "limitation"


def _label(field: str | None, kind: str, text: str) -> str:
    if field:
        return _FIELD_LABELS[field]
    base = "Contribution" if kind == "contribution" else "Limitation"
    return f"{base} (yours)" if "(the reader's)" in text.split(":", 1)[0] else base


def _all_entries(study_ids: Sequence[int] | None) -> list[Entry]:
    conn = get_connection()
    try:
        scope, params = "", []
        if study_ids:
            scope = f" WHERE c.study_id IN ({','.join('?' for _ in study_ids)})"
            params = list(study_ids)
        rows = conn.execute(
            f"""
            SELECT c.id, c.study_id, c.field, c.claim_id, c.text, s.title
            FROM research_chunks c JOIN studies s ON s.id = c.study_id{scope}
            ORDER BY c.study_id, c.id
            """,
            params,
        ).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        kind = _kind(r["field"], r["text"])
        out.append(
            Entry(
                chunk_id=int(r["id"]), study_id=int(r["study_id"]), study_title=r["title"], field=r["field"],
                claim_id=r["claim_id"], kind=kind, label=_label(r["field"], kind, r["text"]), text=r["text"],
            )
        )
    return out


def _vector_scores(question: str, embed: EmbedFn | None) -> dict[int, float]:
    conn = get_connection()
    try:
        total = int(conn.execute("SELECT COUNT(*) FROM research_chunks").fetchone()[0])
        if total == 0:
            return {}
        vector = (embed or embed_texts)([question])[0]
        rows = conn.execute(
            "SELECT rowid, distance FROM research_vec WHERE embedding MATCH ? AND k = ? ORDER BY distance",
            (serialize_embedding(vector), min(total, _POOL)),
        ).fetchall()
        # cosine distance ≈ 1 - similarity for L2-normalized MiniLM vectors
        return {int(r["rowid"]): max(0.0, min(1.0, 1.0 - float(r["distance"]))) for r in rows}
    finally:
        conn.close()


@dataclass(frozen=True)
class ResearchAskPlan:
    question: str
    grounded: bool
    context: list[Entry]
    citations: list[ResearchCitation]


def plan_ask(
    question: str,
    study_ids: Sequence[int] | None = None,
    embed: EmbedFn | None = None,
) -> ResearchAskPlan:
    """Pick the entries to answer from, or decide there aren't any worth answering from."""
    question = question.strip()
    _index_missing(study_ids)
    entries = _all_entries(study_ids)
    scores = _vector_scores(question, embed) if entries else {}
    kinds = {kind for pattern, kind in _KIND_WORDS if pattern.search(question)}

    scored: list[Entry] = []
    for entry in entries:
        score = scores.get(entry.chunk_id, 0.0)
        if lexical_score(question, entry.text) >= 0.8:
            score = max(score, 1.0)
        if entry.kind in kinds:
            score = max(score, SCORE_THRESHOLD)
        scored.append(replace(entry, score=score))

    strong = [e for e in scored if e.score >= SCORE_THRESHOLD]
    if study_ids and _OVERVIEW.search(question):
        strong = scored  # "summarize these": the selection already names the sources
    strong.sort(key=lambda e: (-e.score, e.study_id, e.chunk_id))
    context = strong[:MAX_CONTEXT]
    # Group by Paper for a readable prompt; numbering follows this order.
    context.sort(key=lambda e: (e.study_id, e.chunk_id))
    citations = [
        ResearchCitation(
            number=i, study_id=e.study_id, study_title=e.study_title, field=e.field,
            claim_id=e.claim_id, label=e.label, text=e.text.split(": ", 1)[-1].split("\nQuote:")[0],
            score=round(e.score, 4),
        )
        for i, e in enumerate(context, start=1)
    ]
    return ResearchAskPlan(question=question, grounded=bool(context), context=context, citations=citations)


def build_prompt(plan: ResearchAskPlan) -> list[dict[str, str]]:
    blocks = [f"[{i}] Paper: {e.study_title} | {e.label}\n{e.text}" for i, e in enumerate(plan.context, start=1)]
    context = "\n\n".join(blocks) if blocks else "(no matching entries)"
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {plan.question}"},
    ]


def stream_answer(
    plan: ResearchAskPlan,
    generate: Callable[[list[dict[str, str]]], Iterator[str]] | None = None,
) -> Iterator[str]:
    """Yield answer tokens. Weak context never calls the model."""
    if not plan.grounded:
        yield DECLINE_TEXT
        return
    yield from (generate or chat_stream)(build_prompt(plan))
