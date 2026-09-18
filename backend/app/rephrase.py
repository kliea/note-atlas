"""Turn a terse jot into a clearer note via the local LLM."""

from __future__ import annotations

import json
import re
from collections.abc import Callable

from pydantic import ValidationError

from app.llm import LlmError, chat
from app.models import RephrasedNote

CompleteFn = Callable[[str], str]

_SCHEMA_HINT = '{"title":"string","body":"string"}'

_REPHRASE_INSTRUCTIONS = """You rewrite a rough jot into a proper notebook entry.

Return JSON only that matches this schema:
{"title":"string","body":"string"}

Rules:
- title: a clear, short note title (not a full sentence unless needed).
- body: a polished note that expands the jot into complete thoughts.
- Add useful detail that is clearly implied by the jot (definitions, context, next steps).
- Do not invent facts, names, numbers, or claims that are not grounded in the jot.
- Prefer short paragraphs or bullet lines; keep it concise (about 80–220 words).
- No markdown fences, no commentary, no extra keys.
"""


class RephraseError(Exception):
    """The model did not produce a valid rephrased note."""


def rephrase_jot(
    raw_text: str,
    title: str = "",
    complete: CompleteFn | None = None,
) -> RephrasedNote:
    """Ask the model to polish a jot; retry once if the JSON/schema is invalid."""
    first_prompt = _build_prompt(raw_text, title)
    first_reply = _complete(first_prompt, complete)
    parsed, first_error = _try_parse(first_reply)
    if parsed is not None:
        return parsed

    retry_prompt = _build_retry_prompt(raw_text, title, first_reply, first_error)
    second_reply = _complete(retry_prompt, complete)
    parsed, second_error = _try_parse(second_reply)
    if parsed is not None:
        return parsed

    detail = second_error or first_error or "invalid JSON"
    raise RephraseError(f"model output failed validation: {detail}")


def _complete(prompt: str, complete: CompleteFn | None) -> str:
    if complete is not None:
        return complete(prompt)
    try:
        return chat([{"role": "user", "content": prompt}], json_mode=True)
    except LlmError as exc:
        raise RephraseError(str(exc)) from exc


def _build_prompt(raw_text: str, title: str) -> str:
    heading = title.strip()
    jot = raw_text.strip()
    if heading and jot and not jot.startswith(heading):
        jot = f"{heading}\n{jot}"
    elif heading and not jot:
        jot = heading
    return f"{_REPHRASE_INSTRUCTIONS}\nJot:\n---\n{jot}\n---"


def _build_retry_prompt(
    raw_text: str,
    title: str,
    previous: str,
    error: str | None,
) -> str:
    why = error or "could not parse JSON"
    heading = title.strip()
    jot = raw_text.strip()
    if heading and jot and not jot.startswith(heading):
        jot = f"{heading}\n{jot}"
    return (
        f"{_REPHRASE_INSTRUCTIONS}\n"
        f"Your previous reply was not valid {_SCHEMA_HINT}.\n"
        f"Error: {why}\n"
        f"Previous reply:\n{previous[:2000]}\n"
        f"Return corrected JSON only.\n"
        f"Jot:\n---\n{jot}\n---"
    )


def _try_parse(text: str) -> tuple[RephrasedNote | None, str | None]:
    try:
        data = json.loads(_strip_fences(text))
        return RephrasedNote.model_validate(data), None
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
        return None, str(exc)


def _strip_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()
