"""Background extraction + enrichment + indexing triggered by capture and edits."""

from __future__ import annotations

from fastapi import BackgroundTasks

from app.db import (
    apply_point_additions,
    delete_chunks_for_note,
    get_note,
    replace_note_extraction,
    set_extract_status,
)
from app.extract import EnrichmentError, ExtractionError, enrich, extract_topics
from app.index import index_note
from app.llm import LlmError

_busy: set[int] = set()


def schedule_extraction(background: BackgroundTasks, note_id: int) -> None:
    set_extract_status(note_id, "pending")
    background.add_task(run_extraction_job, note_id)


def schedule_enrichment(background: BackgroundTasks, note_id: int) -> None:
    background.add_task(run_enrichment_job, note_id)


def run_extraction_job(note_id: int) -> None:
    if note_id in _busy:
        return
    _busy.add(note_id)
    try:
        note = get_note(note_id)
        if note is None:
            return
        if note.source == "ask":
            set_extract_status(note_id, "done")
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
        _enrich_note(note_id)
        set_extract_status(note_id, "done")
    finally:
        _busy.discard(note_id)


def run_enrichment_job(note_id: int) -> None:
    _enrich_note(note_id)


def _enrich_note(note_id: int) -> None:
    note = get_note(note_id)
    if note is None or not note.topics:
        return
    try:
        payload = enrich(note)
    except (EnrichmentError, LlmError):
        return
    apply_point_additions(payload.additions)
