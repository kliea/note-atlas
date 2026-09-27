"""Build a folder's ChromaDB index: extract → chunk → embed → upsert, one document at a time.

`build_folder` is synchronous so the Streamlit lab app can call it directly. The API wraps it
in a job (`start_job` + `run_job`) whose progress lives in `file_jobs`. A document already
indexed whose vectors are all still in Chroma is skipped, so building again adds nothing.
A failing document is marked failed and the build moves on.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from app.files import repo, store
from app.files.chunk import Chunk, chunk_pages
from app.files.config import chunk_overlap, chunk_size
from app.files.embed import EmbeddingError, embed_texts
from app.files.extract import ExtractionError, extract_text
from app.files.models import BuildSummary, FileDocument, FileJob

log = logging.getLogger(__name__)

INTERRUPTED = "interrupted: the server stopped before the build finished"

# folder_id → job_id for builds running in this process.
_active: dict[int, int] = {}
_active_lock = threading.Lock()

Progress = Callable[[int, int, FileDocument], None]


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


def build_folder(folder_id: int, on_progress: Progress | None = None) -> BuildSummary:
    """Index every document in the folder that isn't already indexed. `on_progress(done, total, doc)`."""
    documents = repo.list_documents(folder_id)
    summary = BuildSummary(indexed=0, skipped=0, failed=0, chunks=0)
    for done, document in enumerate(documents, start=1):
        if _up_to_date(document):
            summary.skipped += 1
            summary.chunks += document.chunk_count
        else:
            repo.mark_indexing(document.id)
            try:
                store.delete_document(document.id)
                _, chunks = document_chunks(document.id)
                vectors = embed_texts([c.text for c in chunks])
                store.upsert_chunks(document, chunks, vectors)
                repo.mark_indexed(document.id, len(chunks))
                summary.indexed += 1
                summary.chunks += len(chunks)
            except ExtractionError:
                summary.failed += 1  # document_chunks already recorded the reason
            except EmbeddingError as exc:
                repo.mark_failed(document.id, str(exc))
                summary.failed += 1
            except Exception as exc:  # noqa: BLE001 — one bad file never aborts the folder
                log.exception("indexing file document %s failed", document.id)
                repo.mark_failed(document.id, f"indexing failed: {exc}")
                summary.failed += 1
        if on_progress is not None:
            on_progress(done, len(documents), document)
    return summary


def _up_to_date(document: FileDocument) -> bool:
    # Bytes never change for a stored document (sha256 is fixed), so indexed + all vectors
    # present means nothing to do. A missing vector (e.g. the Chroma dir was deleted) rebuilds it.
    return (
        document.status == "indexed"
        and document.chunk_count > 0
        and store.count_document(document.id) == document.chunk_count
    )


# --- API jobs ------------------------------------------------------------------


def start_job(folder_id: int) -> tuple[FileJob, bool]:
    """Queue a build for the folder, or return the one already under way. (job, newly created)."""
    with _active_lock:
        running = _active.get(folder_id)
        if running is not None:
            job = repo.get_job(running)
            if job is not None:
                return job, False
        for stale in repo.unfinished_jobs(folder_id):
            repo.update_job(stale.id, status="failed", error=INTERRUPTED)
        job = repo.create_job(folder_id, total=len(repo.list_documents(folder_id)))
        _active[folder_id] = job.id
    return job, True


def run_job(job_id: int) -> None:
    job = repo.get_job(job_id)
    if job is None:
        return
    try:
        repo.update_job(job_id, status="running")
        build_folder(
            job.folder_id,
            on_progress=lambda done, total, _doc: repo.update_job(job_id, done=done, total=total),
        )
        repo.update_job(job_id, status="done")
    except Exception as exc:  # noqa: BLE001 — recorded on the job
        log.exception("file build job %s failed", job_id)
        repo.update_job(job_id, status="failed", error=str(exc)[:500])
    finally:
        with _active_lock:
            if _active.get(job.folder_id) == job_id:
                del _active[job.folder_id]


def get_job(job_id: int) -> FileJob | None:
    """The job; an unfinished job no thread in this process owns is reported as interrupted."""
    job = repo.get_job(job_id)
    if job is None or job.status in ("done", "failed"):
        return job
    with _active_lock:
        owned = job_id in _active.values()
    if not owned:
        repo.update_job(job_id, status="failed", error=INTERRUPTED)
        return repo.get_job(job_id)
    return job


def is_building(folder_id: int) -> bool:
    with _active_lock:
        return folder_id in _active
