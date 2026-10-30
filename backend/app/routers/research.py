"""Research Track HTTP API: upload Papers and browse the Library."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Response, UploadFile

import json
from collections.abc import Iterator

from fastapi.responses import StreamingResponse

from app import openalex, research_ask, research_store, scholarly, sources
from app.ambient import ingest_note
from app.db import create_note, delete_note
from app.llm import LlmError
from app.config import openalex_api_key, s2_api_key
from app.models import (
    ApiStatus,
    ApiToggle,
    Claim,
    ClaimCreate,
    ClaimPatch,
    IdentityDecision,
    LeadDismissal,
    NoteCreate,
    ParentMarkUpdate,
    ReextractAll,
    ResearchAskRequest,
    SendToBoard,
    StudyDetail,
    StudySummary,
)
from app.research_jobs import FIRST_STEP, resolver, worker

router = APIRouter(prefix="/research", tags=["research"])

_MAX_PDF_BYTES = 100 * 1024 * 1024


@router.post("/papers", response_model=list[StudySummary], status_code=201)
async def upload_papers(files: list[UploadFile]) -> list[StudySummary]:
    """Store each PDF as a Paper and queue it; parsing happens in the background."""
    payloads: list[tuple[str, bytes]] = []
    for upload in files:
        data = await upload.read()
        name = upload.filename or "paper.pdf"
        if not data.startswith(b"%PDF"):
            raise HTTPException(status_code=400, detail=f"{name} is not a PDF")
        if len(data) > _MAX_PDF_BYTES:
            raise HTTPException(status_code=413, detail=f"{name} is larger than 100 MB")
        payloads.append((name, data))
    if not payloads:
        raise HTTPException(status_code=400, detail="no files uploaded")

    created: list[StudySummary] = []
    for name, data in payloads:
        study_id = research_store.create_paper_upload(name, data, FIRST_STEP)
        study = research_store.get_study(study_id)
        if study is not None:
            created.append(study)
    worker.notify()
    return created


@router.get("/studies", response_model=list[StudySummary])
def list_studies(
    state: Literal["all", "paper", "lead"] = "all",
    q: str = Query(default="", max_length=200),
) -> list[StudySummary]:
    return research_store.list_studies(state, q)


@router.get("/studies/{study_id}", response_model=StudyDetail)
def get_study(study_id: int) -> StudyDetail:
    study = research_store.get_study(study_id)
    if study is None:
        raise HTTPException(status_code=404, detail="study not found")
    return study


@router.post("/studies/{study_id}/retry", response_model=StudyDetail)
def retry_study(study_id: int) -> StudyDetail:
    """Re-queue a failed job; it resumes from the step that failed."""
    if not research_store.retry_job(study_id):
        raise HTTPException(status_code=409, detail="no failed job for this study")
    worker.notify()
    study = research_store.get_study(study_id)
    if study is None:
        raise HTTPException(status_code=404, detail="study not found")
    return study


@router.post("/studies/{study_id}/claims", response_model=Claim, status_code=201)
def add_claim(study_id: int, payload: ClaimCreate) -> Claim:
    """Add the reader's own Limitation to a Paper."""
    claim = research_store.add_reader_claim(study_id, payload.kind, payload.text)
    if claim is None:
        raise HTTPException(status_code=404, detail="paper not found")
    research_ask.reindex_quietly(study_id)
    return claim


@router.patch("/claims/{claim_id}", response_model=Claim)
def edit_claim(claim_id: int, payload: ClaimPatch) -> Claim:
    claim = research_store.edit_claim(claim_id, payload.text)
    if claim is None:
        raise HTTPException(status_code=404, detail="claim not found")
    research_ask.reindex_quietly(research_store.claim_study_id(claim_id))
    return claim


@router.post("/claims/{claim_id}/keep", response_model=Claim)
def keep_claim(claim_id: int) -> Claim:
    """Keep a Claim that re-extraction flagged as "not in the latest extraction"."""
    claim = research_store.keep_claim(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="claim not found")
    return claim


@router.delete("/claims/{claim_id}", status_code=204)
def delete_claim(claim_id: int) -> Response:
    study_id = research_store.claim_study_id(claim_id)
    if not research_store.delete_claim(claim_id):
        raise HTTPException(status_code=404, detail="claim not found")
    research_ask.reindex_quietly(study_id)
    return Response(status_code=204)


def _as_float(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


@router.get("/api-status", response_model=ApiStatus)
def api_status() -> ApiStatus:
    """What the header pill shows: whether the scholarly API is on, and today's OpenAlex budget."""
    budget = openalex.budget()
    return ApiStatus(
        enabled=scholarly.api_enabled(),
        source=sources.active().name,
        sources=sources.available(),
        openalex_key=bool(openalex_api_key()),
        s2_key=bool(s2_api_key()),
        remaining_usd=_as_float(budget["remaining_usd"]),
        limit_usd=_as_float(budget["limit_usd"]),
        reset_at=budget["reset_at"],
        waiting=research_store.count_waiting_for_budget(),
    )


@router.put("/api-status", response_model=ApiStatus)
def set_api_status(payload: ApiToggle) -> ApiStatus:
    if payload.source is not None and payload.source != sources.active().name:
        try:
            sources.choose(payload.source)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        # Re-resolve every Paper and its Leads against the new source (responses are cached).
        research_store.requeue_resolution(("done", "failed", "waiting_budget"))
        research_store.requeue_leads(("done", "failed", "waiting_budget"))
        resolver.notify()
    if payload.enabled is None:
        return api_status()
    research_store.set_settings({"scholarly_api": "on" if payload.enabled else "off"})
    if payload.enabled:
        research_store.requeue_resolution(("off",))
        # Leads found with the API off came only from the Library; widen them now.
        research_store.requeue_leads(("done", "failed"))
        resolver.notify()
    return api_status()


@router.post("/studies/{study_id}/identity", response_model=StudyDetail)
def decide_identity(study_id: int, payload: IdentityDecision) -> StudyDetail:
    """Answer 'Is this the Lead you already have?' for a fuzzy match."""
    study = research_store.get_study(study_id)
    if study is None or study.possible_match is None:
        raise HTTPException(status_code=409, detail="no pending match for this study")
    if payload.same:
        research_store.merge_studies(study_id, study.possible_match.study_id)
        research_store.set_possible_match(study_id, None)
    else:
        research_store.reject_match(study_id, study.possible_match.study_id)
    updated = research_store.get_study(study_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="study not found")
    return updated


@router.post("/studies/{study_id}/resolve", response_model=StudyDetail)
def retry_resolution(study_id: int) -> StudyDetail:
    study = research_store.get_study(study_id)
    if study is None or study.state != "paper":
        raise HTTPException(status_code=404, detail="paper not found")
    research_store.set_resolve_status(study_id, "pending")
    resolver.notify()
    updated = research_store.get_study(study_id)
    assert updated is not None
    return updated


@router.put("/studies/{paper_id}/parents/{study_id}", response_model=StudyDetail)
def mark_parent(paper_id: int, study_id: int, payload: ParentMarkUpdate) -> StudyDetail:
    """Pin a Reference as a Parent, unpin it, or clear the mark (back to the model's call)."""
    if not research_store.set_parent_mark(paper_id, study_id, payload.mark):
        raise HTTPException(status_code=404, detail="that study is not a reference of this paper")
    study = research_store.get_study(paper_id)
    assert study is not None
    return study


@router.post("/studies/{paper_id}/parents/refresh", response_model=StudyDetail)
def refresh_parents(paper_id: int) -> StudyDetail:
    """Re-run Parent selection in the background. Marks are kept."""
    study = research_store.get_study(paper_id)
    if study is None or study.state != "paper":
        raise HTTPException(status_code=404, detail="paper not found")
    if not research_store.queue_step(paper_id, "parents"):
        raise HTTPException(status_code=409, detail="this paper is already being processed")
    worker.notify()
    updated = research_store.get_study(paper_id)
    assert updated is not None
    return updated


@router.post("/studies/{paper_id}/leads/refresh", response_model=StudyDetail)
def refresh_leads(paper_id: int) -> StudyDetail:
    """Recompute Siblings and Ancestors on the network worker. Dismissals are kept."""
    study = research_store.get_study(paper_id)
    if study is None or study.state != "paper":
        raise HTTPException(status_code=404, detail="paper not found")
    research_store.request_leads(paper_id)
    resolver.notify()
    updated = research_store.get_study(paper_id)
    assert updated is not None
    return updated


@router.put("/studies/{paper_id}/leads/{study_id}", response_model=StudyDetail)
def dismiss_lead(paper_id: int, study_id: int, payload: LeadDismissal) -> StudyDetail:
    """Mark a Sibling or Ancestor "not relevant" for this Paper (or undo that)."""
    if not research_store.set_dismissed(paper_id, study_id, payload.dismissed):
        raise HTTPException(status_code=404, detail="study not found")
    study = research_store.get_study(paper_id)
    assert study is not None
    return study


@router.post("/claims/{claim_id}/send", response_model=StudyDetail, status_code=201)
def send_claim_to_board(claim_id: int, payload: SendToBoard, background: BackgroundTasks) -> StudyDetail:
    """Put a Claim on the board as a verbatim note linked back to its Paper (a snapshot)."""
    found = research_store.claim_for_board(claim_id)
    if found is None:
        raise HTTPException(status_code=404, detail="claim not found")
    claim, study = found
    if claim["sent_note_id"] is not None:
        raise HTTPException(status_code=409, detail="this claim is already on the board")
    title, body = research_store.board_note_text(claim, study)
    centre = (payload.x, payload.y) if payload.x is not None and payload.y is not None else None
    position = research_store.board_position(int(study["id"]), centre)
    try:
        note = create_note(
            NoteCreate(
                title=title,
                source="paper",
                raw_text=body,
                x=position[0] if position else None,
                y=position[1] if position else None,
                board_id=payload.board_id,
            )
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="board not found") from None
    try:
        research_store.link_board_note(note.id, int(study["id"]), claim_id)
    except Exception:
        delete_note(note.id)
        raise
    # Verbatim (no rephrase), but indexed and topic-extracted so it gets related-link suggestions.
    ingest_note(background, note.id, extract=True)
    updated = research_store.get_study(int(study["id"]))
    assert updated is not None
    return updated


def _sse(event: str, payload: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


@router.post("/ask")
def ask_papers(body: ResearchAskRequest) -> StreamingResponse:
    """Answer from the selected Papers' Extractions and Claims (or the whole Library)."""
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    def events() -> Iterator[str]:
        try:
            plan = research_ask.plan_ask(question, study_ids=body.study_ids)
            yield _sse(
                "meta",
                {"grounded": plan.grounded, "citations": [c.model_dump() for c in plan.citations]},
            )
            for token in research_ask.stream_answer(plan):
                yield _sse("token", {"text": token})
            yield _sse("done", {})
        except LlmError as exc:
            yield _sse("error", {"detail": str(exc)})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# Re-extraction re-runs from the Extraction step (Parents follow, marks kept); the parse and
# its References stay. It is user-triggered only.
_REEXTRACT_FROM = "extract"


@router.post("/studies/{paper_id}/reextract", response_model=StudyDetail)
def reextract_paper(paper_id: int) -> StudyDetail:
    """Re-run extraction; edited, sent, reader, and deleted Claims are respected."""
    study = research_store.get_study(paper_id)
    if study is None or study.state != "paper":
        raise HTTPException(status_code=404, detail="paper not found")
    if study.extracted_at is None:
        raise HTTPException(status_code=409, detail="this paper hasn't been extracted yet")
    if not research_store.queue_step(paper_id, _REEXTRACT_FROM):
        raise HTTPException(status_code=409, detail="this paper is already being processed")
    worker.notify()
    updated = research_store.get_study(paper_id)
    assert updated is not None
    return updated


@router.post("/reextract-all", response_model=ReextractAll)
def reextract_all() -> ReextractAll:
    """After a model or parser upgrade: queue every extracted Paper that isn't busy."""
    queued = busy = 0
    for paper_id in research_store.extracted_paper_ids():
        if research_store.queue_step(paper_id, _REEXTRACT_FROM):
            queued += 1
        else:
            busy += 1
    worker.notify()
    return ReextractAll(queued=queued, busy=busy)
