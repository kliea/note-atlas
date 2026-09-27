"""Files pipeline HTTP API: folders of uploaded PDFs and text files (the lab RAG)."""

from __future__ import annotations

import json
from collections.abc import Iterator

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Response, UploadFile
from fastapi.responses import StreamingResponse

from app.files import build, repo, service
from app.files.embed import EmbeddingError
from app.files.extract import ExtractionError
from app.llm import LlmError
from app.files.models import (
    AskRequest,
    ChunkPreviewResult,
    FileAsk,
    FileDocument,
    FileFolder,
    FileJob,
    FilesSettings,
    FolderName,
    IndexStatus,
    ModelList,
    UploadResult,
)

router = APIRouter(prefix="/files", tags=["files"])


@router.get("/folders", response_model=list[FileFolder])
def list_folders() -> list[FileFolder]:
    return repo.list_folders()


@router.post("/folders", response_model=FileFolder, status_code=201)
def create_folder(body: FolderName) -> FileFolder:
    try:
        return repo.create_folder(body.name)
    except repo.FolderNameTaken as exc:
        raise HTTPException(status_code=409, detail=f"a folder named {body.name} already exists") from exc


@router.patch("/folders/{folder_id}", response_model=FileFolder)
def rename_folder(folder_id: int, body: FolderName) -> FileFolder:
    try:
        folder = repo.rename_folder(folder_id, body.name)
    except repo.FolderNameTaken as exc:
        raise HTTPException(status_code=409, detail=f"a folder named {body.name} already exists") from exc
    if folder is None:
        raise HTTPException(status_code=404, detail="folder not found")
    return folder


@router.delete("/folders/{folder_id}", status_code=204)
def delete_folder(folder_id: int) -> Response:
    """Remove the folder, its stored files, and its vectors."""
    try:
        deleted = service.delete_folder(folder_id)
    except service.BuildInProgress as exc:
        raise HTTPException(status_code=409, detail="the folder is being indexed; try again when it finishes") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="folder not found")
    return Response(status_code=204)


@router.get("/folders/{folder_id}/documents", response_model=list[FileDocument])
def list_documents(folder_id: int) -> list[FileDocument]:
    if repo.get_folder(folder_id) is None:
        raise HTTPException(status_code=404, detail="folder not found")
    return repo.list_documents(folder_id)


@router.post("/folders/{folder_id}/documents", response_model=UploadResult)
async def upload_documents(folder_id: int, files: list[UploadFile]) -> UploadResult:
    """Store PDFs and UTF-8 .txt files; anything else rejects the whole batch with 415."""
    uploads = [(upload.filename or "file", await upload.read()) for upload in files]
    if not uploads:
        raise HTTPException(status_code=400, detail="no files uploaded")
    try:
        return repo.add_documents(folder_id, uploads)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="folder not found") from exc
    except repo.UnsupportedFile as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except repo.UploadTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: int) -> Response:
    """Remove the document, its stored file, and exactly its vectors."""
    try:
        deleted = service.delete_document(document_id)
    except service.BuildInProgress as exc:
        raise HTTPException(status_code=409, detail="the folder is being indexed; try again when it finishes") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="document not found")
    return Response(status_code=204)


@router.get("/documents/{document_id}/chunks", response_model=ChunkPreviewResult)
def preview_chunks(document_id: int, limit: int = Query(default=20, ge=1, le=1000)) -> ChunkPreviewResult:
    """Debug view: the document's chunks as they would be indexed. An unreadable file is marked failed."""
    try:
        return service.preview_chunks(document_id, limit)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="document not found") from exc
    except ExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/folders/{folder_id}/build", response_model=FileJob, status_code=202)
def build_folder(folder_id: int, background: BackgroundTasks) -> FileJob:
    """Build Knowledge Base for the folder in the background; returns the job to poll.

    If the folder is already building, that job is returned instead of starting another.
    """
    if repo.get_folder(folder_id) is None:
        raise HTTPException(status_code=404, detail="folder not found")
    job, created = build.start_job(folder_id)
    if created:
        background.add_task(build.run_job, job.id)
    return job


@router.get("/jobs/{job_id}", response_model=FileJob)
def get_job(job_id: int) -> FileJob:
    job = build.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@router.delete("/folders/{folder_id}/index", status_code=204)
def clear_folder_index(folder_id: int) -> Response:
    """Clear Knowledge Base for one folder: its vectors go, its files stay (reset to uploaded)."""
    try:
        cleared = service.clear_folder_index(folder_id)
    except service.BuildInProgress as exc:
        raise HTTPException(status_code=409, detail="the folder is being indexed; try again when it finishes") from exc
    if not cleared:
        raise HTTPException(status_code=404, detail="folder not found")
    return Response(status_code=204)


@router.get("/status", response_model=IndexStatus)
def index_status() -> IndexStatus:
    """Knowledge Base Status: stored chunks in total and per folder."""
    return service.index_status()


def _sse(event: str, payload: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


@router.post("/ask")
def ask(body: AskRequest) -> StreamingResponse:
    """Stream a grounded answer (`token` events), then `done` with the retrieved chunks and the
    saved history row. An empty scope sends `done` with `empty` set and never calls the model."""
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    def events() -> Iterator[str]:
        try:
            plan = service.plan_ask(question, body.folder_ids, body.top_k, body.model)
            chunks = [chunk.model_dump() for chunk in plan.chunks]
            if plan.empty_message is not None:
                yield _sse("done", {"empty": plan.empty_message, "chunks": [], "ask": None})
                return
            pieces: list[str] = []
            for token in service.stream_answer(plan):
                pieces.append(token)
                yield _sse("token", {"text": token})
            saved = service.record_ask(plan, "".join(pieces))
            yield _sse(
                "done",
                {"empty": None, "chunks": chunks, "ask": saved.model_dump() if saved else None},
            )
        except (EmbeddingError, LlmError) as exc:
            yield _sse("error", {"detail": str(exc)})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/asks", response_model=list[FileAsk])
def list_asks(limit: int = Query(default=50, ge=1, le=500)) -> list[FileAsk]:
    """Chat History, newest first."""
    return repo.list_asks(limit)


@router.delete("/asks", status_code=204)
def clear_asks() -> Response:
    repo.clear_asks()
    return Response(status_code=204)


@router.get("/settings", response_model=FilesSettings)
def files_settings() -> FilesSettings:
    """Which lab enhancements are on, for the UIs."""
    return service.settings()


@router.get("/models", response_model=ModelList)
def files_models() -> ModelList:
    """Pulled Ollama chat models for the model picker (enhancement 6)."""
    return service.available_models()
