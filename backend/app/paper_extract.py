"""Extract a Paper's research question, method, key results, scope, and Claims with the local model.

Rules (docs/specs/research-track.md, "Extraction rules"):
- A Contribution is what the authors claim is new about their own work; findings are not Contributions.
- A paper's Limitation is kept only if its quote is found in the Paper's full text (fuzzily) AND a
  second check confirms the quote actually states a limitation.
- One Claim per distinct point; umbrella items that merely group others are dropped.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from app.llm import LlmError, chat

# Bodies longer than this are split into chunks and merged (fits the 32K context bucket).
MAX_BODY_CHARS = 80_000
_QUOTE_MATCH_THRESHOLD = 0.85
_MIN_QUOTE_TOKENS = 4

_FIELDS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "research_question": {"type": "string"},
        "contributions": {"type": "array", "items": {"type": "string"}},
        "method": {"type": "string"},
        "key_results": {"type": "string"},
        "scope": {"type": "string"},
    },
    "required": ["research_question", "contributions", "method", "key_results", "scope"],
}

_LIMITATIONS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "limitations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "quote": {"type": "string"}},
                "required": ["text", "quote"],
            },
        }
    },
    "required": ["limitations"],
}

# One verdict object per item: a bare list of booleans collapses to all-false on small models.
_CONFIRM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "number": {"type": "integer"},
                    "admits_weakness": {"type": "boolean"},
                },
                "required": ["number", "admits_weakness"],
            },
        }
    },
    "required": ["verdicts"],
}

_FIELDS_RULES = (
    "research_question: the question this paper investigates, written as one question about its subject "
    "matter (e.g. 'How does X affect Y in Z?').\n"
    "contributions: one item per distinct thing the authors claim is NEW about their own work "
    "(a dataset, method, system, analysis, or synthesis), usually 2-5. Write each as one direct sentence "
    "starting with what was made or done (e.g. 'A benchmark of ...'), not 'The authors claim'. "
    "A finding or a number is NOT a contribution; never restate key results here. "
    "Do not add an item that merely summarises other items.\n"
    "method: how they answered the question.\n"
    "key_results: the main findings, keeping the paper's own numbers.\n"
    "scope: the conditions under which the results are claimed to hold (domain, data, setting).\n"
    "Use only what the text says. Do not invent anything."
)


@dataclass
class ExtractedFields:
    research_question: str
    contributions: list[str]
    method: str
    key_results: str
    scope: str


@dataclass
class LimitationCandidate:
    text: str
    quote: str


def _ask(prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
    raw = chat(
        [{"role": "user", "content": prompt}],
        schema=schema,
        temperature=0,
        priority="research",
        timeout=900.0,
    )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LlmError("model returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise LlmError("model returned a non-object")
    return data


def chunk_body(body: str, max_chars: int = MAX_BODY_CHARS) -> list[str]:
    """Split on section boundaries ("## " headings), then paragraphs, keeping chunks under max_chars."""
    if len(body) <= max_chars:
        return [body]
    pieces = re.split(r"(?=^## )", body, flags=re.MULTILINE)
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        while len(piece) > max_chars:
            cut = piece.rfind("\n", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            if current:
                chunks.append(current)
                current = ""
            chunks.append(piece[:cut])
            piece = piece[cut:]
        if len(current) + len(piece) > max_chars and current:
            chunks.append(current)
            current = ""
        current += piece
    if current.strip():
        chunks.append(current)
    return chunks


def _fields_from(data: dict[str, Any]) -> ExtractedFields:
    contributions = [str(c).strip() for c in data.get("contributions", []) if str(c).strip()]
    return ExtractedFields(
        research_question=str(data.get("research_question", "")).strip(),
        contributions=contributions,
        method=str(data.get("method", "")).strip(),
        key_results=str(data.get("key_results", "")).strip(),
        scope=str(data.get("scope", "")).strip(),
    )


def extract_fields(title: str, abstract: str, body: str) -> ExtractedFields:
    chunks = chunk_body(body)
    header = f"TITLE: {title}\nABSTRACT: {abstract}\n\n"
    if len(chunks) == 1:
        prompt = (
            "You are reading an academic paper. Return JSON with these fields.\n"
            f"{_FIELDS_RULES}\n\n{header}BODY:\n{body}"
        )
        return _fields_from(_ask(prompt, _FIELDS_SCHEMA))

    partials = []
    for index, chunk in enumerate(chunks, start=1):
        prompt = (
            f"You are reading part {index} of {len(chunks)} of an academic paper. "
            "Return JSON with these fields, using only this part (leave a field empty if this part "
            f"doesn't cover it).\n{_FIELDS_RULES}\n\n{header}PART:\n{chunk}"
        )
        partials.append(_ask(prompt, _FIELDS_SCHEMA))
    merge_prompt = (
        "These JSON objects were extracted from consecutive parts of one academic paper. Merge them "
        "into one object with the same fields: combine and de-duplicate contributions, and write each "
        f"text field once for the whole paper.\n{_FIELDS_RULES}\n\n{header}PARTS:\n"
        + json.dumps(partials, ensure_ascii=False)
    )
    return _fields_from(_ask(merge_prompt, _FIELDS_SCHEMA))


def propose_limitations(body: str) -> list[LimitationCandidate]:
    candidates: list[LimitationCandidate] = []
    seen: set[str] = set()
    for chunk in chunk_body(body):
        prompt = (
            "List the LIMITATIONS this paper explicitly admits about its OWN work: threats to validity, "
            "weaknesses, boundaries, or future work that names a gap. For each: text = the limitation in "
            "one sentence; quote = an EXACT sentence or clause copied verbatim from the text that states "
            "it. One item per distinct limitation; do not add an item that only summarises others. "
            "If the paper admits none, return an empty list. Never invent a limitation.\n\n"
            f"TEXT:\n{chunk}"
        )
        for item in _ask(prompt, _LIMITATIONS_SCHEMA).get("limitations", []):
            text = str(item.get("text", "")).strip()
            quote = str(item.get("quote", "")).strip()
            key = normalize(text)
            if text and quote and key not in seen:
                seen.add(key)
                candidates.append(LimitationCandidate(text=text, quote=quote))
    return candidates


def normalize(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def quote_in_text(quote: str, full_text: str, threshold: float = _QUOTE_MATCH_THRESHOLD) -> bool:
    """True when the quote appears in the text, tolerating hyphenation, line breaks, and small edits."""
    q = normalize(quote).split()
    if len(q) < _MIN_QUOTE_TOKENS:
        return False
    text_tokens = normalize(full_text).split()
    if " ".join(q) in " ".join(text_tokens):
        return True
    # Anchor candidate windows on any trigram of the quote, then compare the window.
    trigrams = {tuple(q[i : i + 3]) for i in range(len(q) - 2)}
    starts: set[int] = set()
    for i in range(len(text_tokens) - 2):
        if tuple(text_tokens[i : i + 3]) in trigrams:
            starts.update(range(max(0, i - len(q)), i + 1))
    for start in starts:
        window = text_tokens[start : start + len(q)]
        if SequenceMatcher(None, q, window, autojunk=False).ratio() >= threshold:
            return True
    return False


def confirm_limitations(candidates: list[LimitationCandidate]) -> list[bool]:
    """Second check: does each quote itself admit a weakness of the authors' own work?"""
    if not candidates:
        return []
    listing = "\n".join(
        f'{i}. Claimed limitation: {c.text}\n   Quote: "{c.quote}"' for i, c in enumerate(candidates)
    )
    prompt = (
        "Each numbered item pairs a claimed limitation of a paper with a quote from that paper. Decide "
        "whether the QUOTE ITSELF admits a weakness of the authors' own work. It does if it says something "
        "was not done, not measured, not tested, not resolved, could not be computed, is too small or too "
        "few, is biased, is restricted to certain data or settings, or is left for future work. It does not "
        "if it only describes what the authors did, their data, or their results, without admitting a "
        "shortcoming.\nReturn one verdict per item: number and admits_weakness.\n\n" + listing
    )
    verdicts: dict[int, bool] = {}
    for item in _ask(prompt, _CONFIRM_SCHEMA).get("verdicts", []):
        try:
            verdicts[int(item.get("number"))] = bool(item.get("admits_weakness"))
        except (TypeError, ValueError):
            continue
    return [verdicts.get(i, False) for i in range(len(candidates))]


def extract_limitations(body: str, full_text: str) -> list[LimitationCandidate]:
    found = [c for c in propose_limitations(body) if quote_in_text(c.quote, full_text)]
    confirmed = confirm_limitations(found)
    return [c for c, ok in zip(found, confirmed, strict=True) if ok]
