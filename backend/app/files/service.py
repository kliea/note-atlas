"""The Files pipeline's entry points, shared by the FastAPI router and the Streamlit lab app."""

from __future__ import annotations

from app.files import repo
from app.files.chunk import Chunk, chunk_pages
from app.files.config import chunk_overlap, chunk_size
from app.files.extract import ExtractionError, extract_text
from app.files.models import ChunkPreview, ChunkPreviewResult


def document_chunks(document_id: int) -> tuple[int, list[Chunk]]:
    """Extract and chunk a stored document: (page_count, chunks). Records the page count.

    Raises LookupError for an unknown document and ExtractionError (after marking the
    document failed with the reason) when it has no readable text.
    """
    document = repo.get_document(document_id)
    path = repo.document_path(document_id)
    if document is None or path is None:
        raise LookupError(f"document {document_id} not found")
    try:
        pages = extract_text(path, document.mime)
    except ExtractionError as exc:
        repo.mark_failed(document_id, str(exc))
        raise
    repo.set_page_count(document_id, len(pages))
    return len(pages), chunk_pages(pages, chunk_size(), chunk_overlap())


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
