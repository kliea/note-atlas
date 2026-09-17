"""Turn raw notes into structured topics via the local LLM."""

from __future__ import annotations

import json
import re
from collections.abc import Callable

from pydantic import ValidationError

from app.llm import LlmError, chat
from app.models import EnrichmentPayload, ExtractionPayload, NoteDetail

CompleteFn = Callable[[str], str]

_SCHEMA_HINT = (
    '{"topics":[{"title":"string","points":["string"],"tags":["kebab-case"]}]}'
)

_ENRICH_SCHEMA_HINT = '{"additions":[{"point_id":0,"context":"string"}]}'

_EXTRACT_INSTRUCTIONS = """You extract key topics from raw notes.

Return JSON only that matches this schema:
{"topics":[{"title":"string","points":["string"],"tags":["kebab-case"]}]}

Rules:
- Key topics only (typically 3–7).
- Each topic has a short title, 2–6 terse bullet points, and 2–4 tags.
- Tags are lowercase and hyphenated (example: disk-io, b-tree).
- No markdown fences, no commentary, no extra keys.
"""

_ENRICH_INSTRUCTIONS = """You annotate, you do not rewrite. Do not change, rephrase, or restate the user's words.

Add a short "Context:" note (1–3 sentences, plain language) ONLY to points that are too terse to stand alone — undefined terms, bare arrows, or name-drops (e.g. "flywheel model", "vertical AI", "domain-specific feature engineering", a named case study). When a point pairs two things (e.g. "Traditional SaaS vs AI-as-a-service > flywheel model"), explain what the term means AND how it relates to the pairing.

Use only well-established general knowledge. If you don't have reliable context for a term, return NO addition for it — never guess.

Never invent specifics about this particular lecture, and never phrase an addition as if the note itself said it. It is clearly your explanatory context.

Skip points that are already self-explanatory. Do not pad.

Return JSON only that matches this schema:
{"additions":[{"point_id":int,"context":"string"}]}

Rules:
- additions ONLY for points that need context; omit the rest.
- Reference points by id. Do not return or replace the original text.
- The context value is 1–3 sentences of explanatory context (no heading, do not quote the user's words).
- No markdown fences, no commentary, no extra keys.
"""


class ExtractionError(Exception):
    """The model did not produce valid extraction JSON."""


class EnrichmentError(Exception):
    """The model did not produce valid enrichment JSON."""


def extract_topics(raw_text: str, complete: CompleteFn | None = None) -> ExtractionPayload:
    """Ask the model for topics; retry once if the JSON/schema is invalid."""
    first_prompt = _build_prompt(raw_text)
    first_reply = _complete(first_prompt, complete)
    parsed, first_error = _try_parse(first_reply)
    if parsed is not None:
        return parsed

    retry_prompt = _build_retry_prompt(raw_text, first_reply, first_error)
    second_reply = _complete(retry_prompt, complete)
    parsed, second_error = _try_parse(second_reply)
    if parsed is not None:
        return parsed

    detail = second_error or first_error or "invalid JSON"
    raise ExtractionError(f"model output failed validation: {detail}")


def enrich(note: NoteDetail, complete: CompleteFn | None = None) -> EnrichmentPayload:
    """Ask the model for additive context; retry once if the JSON/schema is invalid.

    Input is already-extracted points (verbatim, with ids) plus raw_text.
    Output is additions keyed by point_id. Original text is never returned.
    """
    known_ids = {point.id for topic in note.topics for point in topic.points}
    if not known_ids:
        return EnrichmentPayload(additions=[])

    first_prompt = _build_enrich_prompt(note)
    first_reply = _complete(first_prompt, complete, EnrichmentError)
    parsed, first_error = _try_parse_enrich(first_reply)
    if parsed is not None:
        return _filter_additions(parsed, known_ids)

    retry_prompt = _build_enrich_retry_prompt(note, first_reply, first_error)
    second_reply = _complete(retry_prompt, complete, EnrichmentError)
    parsed, second_error = _try_parse_enrich(second_reply)
    if parsed is not None:
        return _filter_additions(parsed, known_ids)

    detail = second_error or first_error or "invalid JSON"
    raise EnrichmentError(f"model output failed validation: {detail}")


def _complete(
    prompt: str,
    complete: CompleteFn | None,
    error_cls: type[Exception] = ExtractionError,
) -> str:
    if complete is not None:
        return complete(prompt)
    try:
        return chat([{"role": "user", "content": prompt}], json_mode=True)
    except LlmError as exc:
        raise error_cls(str(exc)) from exc


def _build_prompt(raw_text: str) -> str:
    return f"{_EXTRACT_INSTRUCTIONS}\nNotes:\n---\n{raw_text.strip()}\n---"


def _build_retry_prompt(raw_text: str, previous: str, error: str | None) -> str:
    why = error or "could not parse JSON"
    return (
        f"{_EXTRACT_INSTRUCTIONS}\n"
        f"Your previous reply was not valid {_SCHEMA_HINT}.\n"
        f"Error: {why}\n"
        f"Previous reply:\n{previous[:2000]}\n"
        f"Return corrected JSON only.\n"
        f"Notes:\n---\n{raw_text.strip()}\n---"
    )


def _build_enrich_prompt(note: NoteDetail) -> str:
    return (
        f"{_ENRICH_INSTRUCTIONS}\n"
        f"Points (verbatim; do not modify):\n{_points_json(note)}\n"
        f"Raw note (for context only; do not rewrite):\n---\n{note.raw_text}\n---"
    )


def _build_enrich_retry_prompt(
    note: NoteDetail, previous: str, error: str | None
) -> str:
    why = error or "could not parse JSON"
    return (
        f"{_ENRICH_INSTRUCTIONS}\n"
        f"Your previous reply was not valid {_ENRICH_SCHEMA_HINT}.\n"
        f"Error: {why}\n"
        f"Previous reply:\n{previous[:2000]}\n"
        f"Return corrected JSON only. Additions by point_id; do not include original text.\n"
        f"Points (verbatim; do not modify):\n{_points_json(note)}\n"
        f"Raw note (for context only; do not rewrite):\n---\n{note.raw_text}\n---"
    )


def _points_json(note: NoteDetail) -> str:
    payload = [
        {"id": point.id, "text": point.text}
        for topic in note.topics
        for point in topic.points
    ]
    return json.dumps(payload, ensure_ascii=False)


def _filter_additions(
    payload: EnrichmentPayload, known_ids: set[int]
) -> EnrichmentPayload:
    seen: set[int] = set()
    kept = []
    for item in payload.additions:
        if item.point_id not in known_ids or item.point_id in seen:
            continue
        seen.add(item.point_id)
        kept.append(item)
    return EnrichmentPayload(additions=kept)


def _try_parse(text: str) -> tuple[ExtractionPayload | None, str | None]:
    try:
        data = json.loads(_strip_fences(text))
        return ExtractionPayload.model_validate(data), None
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
        return None, str(exc)


def _try_parse_enrich(text: str) -> tuple[EnrichmentPayload | None, str | None]:
    try:
        data = json.loads(_strip_fences(text))
        return EnrichmentPayload.model_validate(data), None
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
        return None, str(exc)


def _strip_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()
