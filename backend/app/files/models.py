"""Pydantic models for the Files pipeline."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, computed_field, field_validator

DocumentStatus = Literal["uploaded", "indexing", "indexed", "failed"]


class FileFolder(BaseModel):
    id: int
    name: str
    created_at: str
    document_count: int
    chunk_count: int


class FolderName(BaseModel):
    """Body for creating or renaming a folder."""

    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped


class FileDocument(BaseModel):
    id: int
    folder_id: int
    filename: str
    mime: str
    size_bytes: int
    sha256: str
    page_count: int | None
    chunk_count: int
    status: DocumentStatus
    error: str | None
    indexed_at: str | None
    created_at: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def encoding(self) -> str | None:
        """For .txt uploads, the charset the file was read with (enhancement 2)."""
        from app.files.repo import text_encoding

        return text_encoding(self.mime)


class SkippedUpload(BaseModel):
    filename: str
    reason: str


class UploadResult(BaseModel):
    """Duplicates are reported as skipped, not as errors."""

    added: list[FileDocument]
    skipped: list[SkippedUpload]


class ChunkPreview(BaseModel):
    idx: int
    text: str
    page_start: int
    char_start: int


class ChunkPreviewResult(BaseModel):
    """The document's chunks as the index would store them (no embeddings yet)."""

    document_id: int
    page_count: int
    chunk_size: int
    overlap: int
    total_chunks: int
    chunks: list[ChunkPreview]


JobStatus = Literal["queued", "running", "done", "failed"]


class FileJob(BaseModel):
    """A folder index build started from the API."""

    id: int
    folder_id: int
    status: JobStatus
    done: int
    total: int
    error: str | None
    created_at: str
    updated_at: str


class BuildSummary(BaseModel):
    indexed: int
    skipped: int
    failed: int
    chunks: int


class FolderIndexStatus(BaseModel):
    folder_id: int
    name: str
    chunk_count: int


class IndexStatus(BaseModel):
    """Knowledge Base Status: chunks stored in ChromaDB, in total and per folder."""

    total_chunks: int
    folders: list[FolderIndexStatus]


class RetrievedChunk(BaseModel):
    """A chunk returned by similarity search, with where it came from."""

    id: str
    document_id: int
    folder_id: int
    filename: str
    page_start: int
    chunk_idx: int
    text: str
    score: float  # cosine similarity, 1 - distance
    # Which search found it: vector (the lab default), bm25, or both (hybrid, enhancement 4).
    retriever: Literal["vector", "bm25", "both"] = "vector"


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    folder_ids: list[int] | None = None  # None or empty: every folder
    top_k: int | None = Field(default=None, ge=1, le=20)
    model: str | None = Field(default=None, min_length=1, max_length=200)  # enhancement 6


class FileAsk(BaseModel):
    """One question and answer in the Files Chat History."""

    id: int
    question: str
    answer: str
    folder_ids: list[int] | None
    chunks: list[RetrievedChunk]
    model: str
    created_at: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sources(self) -> list[str] | None:
        """`filename · p.N` for each distinct source (enhancement 3); None when turned off or refused."""
        from app.files.answer import source_line

        return source_line(self.answer, self.chunks)


class FilesSettings(BaseModel):
    """What the UIs need to know about which enhancements are on."""

    accepted: list[str]
    default_model: str
    top_k: int
    show_sources: bool
    hybrid: bool
    memory_turns: int
    model_picker: bool
    score_threshold: float | None


class ModelList(BaseModel):
    default: str
    models: list[str]
    error: str | None = None
