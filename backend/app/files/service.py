"""The Files pipeline's entry points, shared by the FastAPI router and the Streamlit lab app."""

from __future__ import annotations

from app.files import build, repo, store
from app.files.build import Progress, document_chunks
from app.files.config import chunk_overlap, chunk_size
from app.files.models import (
    BuildSummary,
    ChunkPreview,
    ChunkPreviewResult,
    FolderIndexStatus,
    IndexStatus,
)


class BuildInProgress(Exception):
    """The folder is being indexed; clearing or deleting it must wait."""


def preview_chunks(document_id: int, limit: int = 20) -> ChunkPreviewResult:
    page_count, chunks = document_chunks(document_id)
    return ChunkPreviewResult(
        document_id=document_id,
        page_count=page_count,
        chunk_size=chunk_size(),
        overlap=chunk_overlap(),
        total_chunks=len(chunks),
        chunks=[
            ChunkPreview(idx=c.idx, text=c.text, page_start=c.page_start, char_start=c.char_start)
            for c in chunks[:limit]
        ],
    )


def build_folder(folder_id: int, on_progress: Progress | None = None) -> BuildSummary:
    """Build Knowledge Base, synchronously (the Streamlit app calls this)."""
    if repo.get_folder(folder_id) is None:
        raise LookupError(f"folder {folder_id} not found")
    return build.build_folder(folder_id, on_progress)


def clear_folder_index(folder_id: int) -> bool:
    """Clear Knowledge Base for one folder: remove its vectors and reset its documents to uploaded."""
    if repo.get_folder(folder_id) is None:
        return False
    _refuse_while_building(folder_id)
    store.delete_folder(folder_id)
    repo.reset_folder_index(folder_id)
    return True


def delete_folder(folder_id: int) -> bool:
    if repo.get_folder(folder_id) is None:
        return False
    _refuse_while_building(folder_id)
    store.delete_folder(folder_id)
    return repo.delete_folder(folder_id)


def delete_document(document_id: int) -> bool:
    document = repo.get_document(document_id)
    if document is None:
        return False
    _refuse_while_building(document.folder_id)
    store.delete_document(document_id)
    return repo.delete_document(document_id)


def index_status() -> IndexStatus:
    """Knowledge Base Status, counted from ChromaDB itself."""
    return IndexStatus(
        total_chunks=store.count(),
        folders=[
            FolderIndexStatus(folder_id=f.id, name=f.name, chunk_count=store.count_folder(f.id))
            for f in repo.list_folders()
        ],
    )


def _refuse_while_building(folder_id: int) -> None:
    if build.is_building(folder_id):
        raise BuildInProgress(f"folder {folder_id} is being indexed")
