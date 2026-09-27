"""The Files pipeline's entry points, shared by the FastAPI router and the Streamlit lab app."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from app.db import init_db
from app.files import answer, build, repo, retrieve, store
from app.files.build import Progress, document_chunks
from app.files.config import chunk_overlap, chunk_size, llm_model, score_threshold
from app.files.models import (
    BuildSummary,
    ChunkPreview,
    ChunkPreviewResult,
    FileAsk,
    FileDocument,
    FileFolder,
    FolderIndexStatus,
    IndexStatus,
    RetrievedChunk,
    UploadResult,
)

EMPTY_SCOPE = "No chunks are indexed in this scope yet. Upload files and build the knowledge base first."


def init() -> None:
    """Apply pending migrations; the Streamlit app calls this since no FastAPI lifespan runs."""
    init_db()


# --- folders and files (thin pass-throughs so callers need only this module) ---


def list_folders() -> list[FileFolder]:
    return repo.list_folders()


def create_folder(name: str) -> FileFolder:
    """Raises repo.FolderNameTaken."""
    return repo.create_folder(name.strip())


def list_documents(folder_id: int) -> list[FileDocument]:
    return repo.list_documents(folder_id)


def add_files(folder_id: int, uploads: list[tuple[str, bytes]]) -> UploadResult:
    """Store uploads in the folder; duplicates are skipped. Raises repo.UnsupportedFile / UploadTooLarge."""
    return repo.add_documents(folder_id, uploads)


def chat_history(limit: int = 50) -> list[FileAsk]:
    return repo.list_asks(limit)


def clear_chat_history() -> None:
    repo.clear_asks()


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


# --- Ask -----------------------------------------------------------------------


@dataclass
class AskPlan:
    """What an Ask will do before any tokens are generated.

    `empty_message` set: nothing is indexed in scope, so neither the embedder nor the model runs.
    `chunks` empty with a score threshold on: nothing was close enough, so the answer is the
    refusal line and the model does not run.
    """

    question: str
    folder_ids: list[int] | None
    chunks: list[RetrievedChunk]
    empty_message: str | None = None

    @property
    def calls_model(self) -> bool:
        return self.empty_message is None and bool(self.chunks)


def plan_ask(question: str, folder_ids: list[int] | None = None, top_k: int | None = None) -> AskPlan:
    """Retrieve context for the question. Raises EmbeddingError if Ollama can't embed it."""
    question = question.strip()
    scope = sorted(set(folder_ids)) if folder_ids else None
    if retrieve.scope_chunk_count(scope) == 0:
        return AskPlan(question=question, folder_ids=scope, chunks=[], empty_message=EMPTY_SCOPE)
    chunks = retrieve.retrieve_context(question, scope, top_k)
    return AskPlan(question=question, folder_ids=scope, chunks=chunks)


def stream_answer(plan: AskPlan) -> Iterator[str]:
    """Answer tokens. Raises LlmError if Ollama fails mid-answer."""
    if plan.empty_message is not None:
        return
    if not plan.chunks:
        # Only reachable with FILES_SCORE_THRESHOLD on: nothing cleared the gate.
        yield answer.REFUSAL
        return
    yield from answer.stream_answer(plan.question, plan.chunks)


def record_ask(plan: AskPlan, text: str) -> FileAsk | None:
    """Write the Chat History row; an empty-scope ask is not recorded."""
    if plan.empty_message is not None:
        return None
    model = llm_model() if plan.calls_model else f"none (score threshold {score_threshold()})"
    return repo.add_ask(plan.question, text.strip(), plan.folder_ids, plan.chunks, model)


def ask(question: str, folder_ids: list[int] | None = None, top_k: int | None = None) -> tuple[AskPlan, str]:
    """Plan, answer, and record in one call (the Streamlit app and scripts use this)."""
    plan = plan_ask(question, folder_ids, top_k)
    if plan.empty_message is not None:
        return plan, plan.empty_message
    text = "".join(stream_answer(plan)).strip()
    record_ask(plan, text)
    return plan, text
