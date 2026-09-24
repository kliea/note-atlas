"""Research Track HTTP API: upload Papers and browse the Library."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response, UploadFile

from app import openalex, research_store, scholarly
from app.config import openalex_api_key, s2_api_key
from app.models import (
    ApiStatus,
    ApiToggle,
    Claim,
    ClaimCreate,
    ClaimPatch,
    IdentityDecision,
    LeadDismissal,
    ParentMarkUpdate,
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
    return claim


@router.patch("/claims/{claim_id}", response_model=Claim)
def edit_claim(claim_id: int, payload: ClaimPatch) -> Claim:
    claim = research_store.edit_claim(claim_id, payload.text)
    if claim is None:
        raise HTTPException(status_code=404, detail="claim not found")
    return claim


@router.delete("/claims/{claim_id}", status_code=204)
def delete_claim(claim_id: int) -> Response:
    if not research_store.delete_claim(claim_id):
        raise HTTPException(status_code=404, detail="claim not found")
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
        openalex_key=bool(openalex_api_key()),
        s2_key=bool(s2_api_key()),
        remaining_usd=_as_float(budget["remaining_usd"]),
        limit_usd=_as_float(budget["limit_usd"]),
        reset_at=budget["reset_at"],
        waiting=research_store.count_waiting_for_budget(),
    )


@router.put("/api-status", response_model=ApiStatus)
def set_api_status(payload: ApiToggle) -> ApiStatus:
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
