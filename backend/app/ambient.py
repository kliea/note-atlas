"""Background ingest: corpus index first, then optional extraction + enrichment."""

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
_pending_retry: set[int] = set()


def _try_index(note_id: int) -> None:
    """Best-effort index so Ask keeps a corpus even when LLM work fails."""
    try:
        index_note(note_id)
    except Exception:  # noqa: BLE001
        pass


def ingest_note(
    background: BackgroundTasks,
    note_id: int,
    *,
    extract: bool = True,
) -> None:
    """Pipeline for a new or updated note: always add to the corpus, then extract.

    1. Embed title + raw text (+ any topics) into sqlite-vec.
    2. If extract=True, queue topic extraction in the background.
    3. After topics land, re-index so Ask sees the formal corpus.
    """
    _try_index(note_id)
    if not extract:
        set_extract_status(note_id, "done")
        return
    set_extract_status(note_id, "pending")
    background.add_task(run_extraction_job, note_id)


def schedule_extraction(background: BackgroundTasks, note_id: int) -> None:
    """Re-ingest after a text edit (corpus refresh + extract)."""
    ingest_note(background, note_id, extract=True)


def schedule_enrichment(background: BackgroundTasks, note_id: int) -> None:
    background.add_task(run_enrichment_job, note_id)


def run_extraction_job(note_id: int) -> None:
    if note_id in _busy:
        _pending_retry.add(note_id)
        return
    _busy.add(note_id)
    try:
        note = get_note(note_id)
        if note is None:
            return
        if note.source == "ask":
            _try_index(note_id)
            set_extract_status(note_id, "done")
            return
        set_extract_status(note_id, "running")
        try:
            payload = extract_topics(note.raw_text)
        except (ExtractionError, LlmError):
            # Keep the raw note searchable even when topics never arrive.
            _try_index(note_id)
            set_extract_status(note_id, "error")
            return
        delete_chunks_for_note(note_id)
        replace_note_extraction(note_id, payload.topics)
        _try_index(note_id)
        _enrich_note(note_id)
        set_extract_status(note_id, "done")
    finally:
        _busy.discard(note_id)
        if note_id in _pending_retry:
            _pending_retry.discard(note_id)
            run_extraction_job(note_id)


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
    if payload.additions:
        _try_index(note_id)
