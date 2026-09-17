"""Background extraction + indexing triggered by capture and meaningful edits."""

from __future__ import annotations

from fastapi import BackgroundTasks

from app.db import (
    delete_chunks_for_note,
    get_note,
    replace_note_extraction,
    set_extract_status,
)
from app.extract import ExtractionError, extract_topics
from app.index import index_note
from app.llm import LlmError

_busy: set[int] = set()


def schedule_extraction(background: BackgroundTasks, note_id: int) -> None:
    set_extract_status(note_id, "pending")
    background.add_task(run_extraction_job, note_id)


def run_extraction_job(note_id: int) -> None:
    if note_id in _busy:
        return
    _busy.add(note_id)
    try:
        note = get_note(note_id)
        if note is None:
            return
        set_extract_status(note_id, "running")
        try:
            payload = extract_topics(note.raw_text)
        except (ExtractionError, LlmError):
            set_extract_status(note_id, "error")
            return
        delete_chunks_for_note(note_id)
        replace_note_extraction(note_id, payload.topics)
        try:
            index_note(note_id)
        except Exception:  # noqa: BLE001
            pass
        set_extract_status(note_id, "done")
    finally:
        _busy.discard(note_id)
