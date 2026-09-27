"""Files pipeline HTTP API: folders of uploaded PDFs and text files (the lab RAG)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Response, UploadFile

from app.files import repo, service
from app.files.extract import ExtractionError
from app.files.models import ChunkPreviewResult, FileDocument, FileFolder, FolderName, UploadResult

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
    if not repo.delete_folder(folder_id):
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
    if not repo.delete_document(document_id):
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
