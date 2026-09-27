"""Pydantic models for the Files pipeline."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

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
