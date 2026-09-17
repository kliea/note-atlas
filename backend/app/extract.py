"""Turn raw notes into structured topics via the local LLM."""

from __future__ import annotations

import json
import re
from collections.abc import Callable

from pydantic import ValidationError

from app.llm import LlmError, chat
from app.models import ExtractionPayload

CompleteFn = Callable[[str], str]

_SCHEMA_HINT = (
    '{"topics":[{"title":"string","points":["string"],"tags":["kebab-case"]}]}'
)

_EXTRACT_INSTRUCTIONS = """You extract key topics from raw notes.

Return JSON only that matches this schema:
{"topics":[{"title":"string","points":["string"],"tags":["kebab-case"]}]}

Rules:
- Key topics only (typically 3–7).
- Each topic has a short title, 2–6 terse bullet points, and 2–4 tags.
- Tags are lowercase and hyphenated (example: disk-io, b-tree).
- No markdown fences, no commentary, no extra keys.
"""


class ExtractionError(Exception):
    """The model did not produce valid extraction JSON."""


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


def _complete(prompt: str, complete: CompleteFn | None) -> str:
    if complete is not None:
        return complete(prompt)
    try:
        return chat([{"role": "user", "content": prompt}], json_mode=True)
    except LlmError as exc:
        raise ExtractionError(str(exc)) from exc


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


def _try_parse(text: str) -> tuple[ExtractionPayload | None, str | None]:
    try:
        data = json.loads(_strip_fences(text))
        return ExtractionPayload.model_validate(data), None
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
        return None, str(exc)


def _strip_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()
