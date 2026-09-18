"""Note ingestion routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from pydantic import ValidationError

from app.ambient import schedule_enrichment, schedule_extraction
from app.db import (
    create_note,
    delete_chunks_for_note,
    delete_note,
    get_note,
    list_notes,
    patch_note,
    replace_note_extraction,
    set_extract_status,
)
from app.export import bundle_from_note, extracted_topics, note_to_markdown, parse_markdown
from app.extract import ExtractionError, extract_topics
from app.index import index_note
from app.llm import LlmError
from app.models import (
    LinkSuggestion,
    MarkdownImport,
    NoteBundle,
    NoteCreate,
    NoteDetail,
    NotePatch,
    NoteSummary,
)
from app.suggest import suggest_links

router = APIRouter(prefix="/notes", tags=["notes"])


@router.post("", response_model=NoteDetail, status_code=201)
def post_note(payload: NoteCreate, background: BackgroundTasks) -> NoteDetail:
    created = create_note(payload)
    if payload.source == "ask":
        set_extract_status(created.id, "done")
    else:
        schedule_extraction(background, created.id)
    pending = get_note(created.id)
    if pending is None:
        raise HTTPException(status_code=500, detail="note vanished after create")
    return pending


@router.get("", response_model=list[NoteSummary])
def get_notes() -> list[NoteSummary]:
    return list_notes()


@router.post("/import", response_model=NoteDetail, status_code=201)
def post_import(payload: dict[str, Any]) -> NoteDetail:
    try:
        if payload.get("format") == "markdown":
            markdown = MarkdownImport.model_validate(payload)
            bundle = parse_markdown(markdown.text)
        else:
            bundle = NoteBundle.model_validate(payload)
        topics = extracted_topics(bundle)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    created = create_note(
        NoteCreate(
            title=bundle.note.title,
            source=bundle.note.source,
            raw_text=bundle.note.raw_text,
        )
    )
    if topics:
        replace_note_extraction(created.id, topics)
        try:
            index_note(created.id)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"indexing failed: {exc}") from exc
        set_extract_status(created.id, "done")
    updated = get_note(created.id)
    if updated is None:
        raise HTTPException(status_code=500, detail="note vanished during import")
    return updated


@router.get("/{note_id}/export", response_model=None)
def export_note(
    note_id: int,
    export_format: str = Query(default="json", alias="format"),
) -> Response:
    note = get_note(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="note not found")
    slug = _slug(note.title)
    if export_format in {"md", "markdown"}:
        body = note_to_markdown(note)
        return PlainTextResponse(
            body,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{slug}.md"',
            },
        )
    if export_format != "json":
        raise HTTPException(status_code=400, detail="format must be json or markdown")
    bundle = bundle_from_note(note)
    return JSONResponse(
        bundle.model_dump(),
        headers={
            "Content-Disposition": f'attachment; filename="{slug}.json"',
        },
    )


@router.get("/{note_id}", response_model=NoteDetail)
def get_note_by_id(note_id: int) -> NoteDetail:
    note = get_note(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="note not found")
    return note


@router.get("/{note_id}/suggestions", response_model=list[LinkSuggestion])
def get_note_suggestions(note_id: int) -> list[LinkSuggestion]:
    note = get_note(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="note not found")
    return suggest_links(note_id)


@router.patch("/{note_id}", response_model=NoteDetail)
def patch_note_by_id(note_id: int, payload: NotePatch, background: BackgroundTasks) -> NoteDetail:
    existing = get_note(note_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="note not found")
    updated = patch_note(note_id, payload)
    if updated is None:
        raise HTTPException(status_code=404, detail="note not found")
    changes = payload.model_dump(exclude_unset=True)
    text_changed = (
        ("title" in changes and changes["title"] != existing.title)
        or ("raw_text" in changes and changes["raw_text"] != existing.raw_text)
    )
    if text_changed:
        schedule_extraction(background, note_id)
        refreshed = get_note(note_id)
        if refreshed is None:
            raise HTTPException(status_code=500, detail="note vanished during extract")
        return refreshed
    return updated


@router.delete("/{note_id}", status_code=204)
def delete_note_by_id(note_id: int) -> None:
    if not delete_note(note_id):
        raise HTTPException(status_code=404, detail="note not found")


@router.post("/{note_id}/extract", response_model=NoteDetail)
def extract_note(note_id: int, background: BackgroundTasks) -> NoteDetail:
    note = get_note(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="note not found")
    set_extract_status(note_id, "running")
    try:
        payload = extract_topics(note.raw_text)
    except (ExtractionError, LlmError) as exc:
        set_extract_status(note_id, "error")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    delete_chunks_for_note(note_id)
    replace_note_extraction(note_id, payload.topics)
    updated = get_note(note_id)
    if updated is None:
        raise HTTPException(status_code=500, detail="note vanished during extraction")
    try:
        index_note(note_id)
    except Exception as exc:  # noqa: BLE001
        set_extract_status(note_id, "error")
        raise HTTPException(status_code=502, detail=f"indexing failed: {exc}") from exc
    set_extract_status(note_id, "done")
    finished = get_note(note_id)
    if finished is None:
        raise HTTPException(status_code=500, detail="note vanished during extraction")
    schedule_enrichment(background, note_id)
    return finished


def _slug(title: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in title).strip("-")
    collapsed = "-".join(part for part in cleaned.split("-") if part)
    return collapsed[:48] or "note"
