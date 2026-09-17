"""Pydantic models for notes, topics, points, and tags."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

NoteKind = Literal["typed", "voice", "ink", "clip"]
NOTE_KINDS: tuple[NoteKind, ...] = ("typed", "voice", "ink", "clip")
ExtractStatus = Literal["idle", "pending", "running", "done", "error"]
EXTRACT_STATUSES: tuple[ExtractStatus, ...] = ("idle", "pending", "running", "done", "error")


class NoteCreate(BaseModel):
    title: str = Field(min_length=1)
    source: str = ""
    raw_text: str = Field(min_length=1)
    x: float | None = None
    y: float | None = None


class NoteSummary(BaseModel):
    id: int
    title: str
    source: str
    created_at: str
    x: float = 240.0
    y: float = 180.0
    z: int = 0
    color: str | None = None
    kind: NoteKind = "typed"
    pinned: bool = False
    extract_status: ExtractStatus = "idle"


class Point(BaseModel):
    id: int
    topic_id: int
    text: str
    order_idx: int


class Tag(BaseModel):
    id: int
    topic_id: int
    tag: str


class Topic(BaseModel):
    id: int
    note_id: int
    title: str
    order_idx: int
    points: list[Point] = Field(default_factory=list)
    tags: list[Tag] = Field(default_factory=list)


class NoteDetail(NoteSummary):
    raw_text: str
    topics: list[Topic] = Field(default_factory=list)
    ink_json: str | None = None


class NotePatch(BaseModel):
    """Partial update. Unset fields are left unchanged."""

    x: float | None = None
    y: float | None = None
    z: int | None = None
    color: str | None = None
    kind: NoteKind | None = None
    pinned: bool | None = None
    ink_json: str | None = None
    title: str | None = Field(default=None, min_length=1)
    source: str | None = None
    raw_text: str | None = Field(default=None, min_length=1)


class LinkSuggestion(BaseModel):
    note_id: int
    title: str
    score: float
    reason: Literal["embedding", "shared-tag"]


class ConnectionCreate(BaseModel):
    from_note_id: int
    to_note_id: int
    kind: str = "link"


class Connection(BaseModel):
    id: int
    from_note_id: int
    to_note_id: int
    kind: str
    created_at: str


class ExtractedTopic(BaseModel):
    """LLM output for one topic, before it is persisted."""

    title: str = Field(min_length=1)
    points: list[str] = Field(min_length=1)
    tags: list[str] = Field(min_length=1)

    @field_validator("title", mode="before")
    @classmethod
    def _strip_title(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("points")
    @classmethod
    def _clean_points(cls, values: list[str]) -> list[str]:
        return [item.strip() for item in values if item.strip()]

    @field_validator("tags")
    @classmethod
    def _kebab_tags(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for raw in values:
            tag = re.sub(r"[^a-z0-9]+", "-", raw.strip().lower()).strip("-")
            if tag and tag not in cleaned:
                cleaned.append(tag)
        return cleaned


class ExtractionPayload(BaseModel):
    topics: list[ExtractedTopic] = Field(min_length=1)


class SearchHit(BaseModel):
    chunk_id: int
    note_id: int
    topic_id: int | None
    text: str
    score: float


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    k: int = Field(default=5, ge=1, le=20)
    note_ids: list[int] | None = None

    @field_validator("note_ids")
    @classmethod
    def _positive_unique_ids(cls, value: list[int] | None) -> list[int] | None:
        if not value:
            return None
        cleaned: list[int] = []
        for item in value:
            if item >= 1 and item not in cleaned:
                cleaned.append(item)
        return cleaned or None


class Citation(BaseModel):
    note_id: int
    note_title: str
    topic_id: int | None
    topic_title: str | None
    score: float


class BundleTopic(BaseModel):
    title: str = Field(min_length=1)
    points: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class BundleNote(BaseModel):
    title: str = Field(min_length=1)
    source: str = ""
    raw_text: str = Field(min_length=1)
    created_at: str | None = None
    topics: list[BundleTopic] = Field(default_factory=list)


class NoteBundle(BaseModel):
    format: str = "note-atlas.note"
    version: int = 1
    note: BundleNote


class MarkdownImport(BaseModel):
    format: str = "markdown"
    text: str = Field(min_length=1)
