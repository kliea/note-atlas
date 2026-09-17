"""Serialize a note (and its extraction) to JSON or Markdown, and parse imports."""

from __future__ import annotations

import re

from app.models import BundleNote, BundleTopic, ExtractedTopic, NoteBundle, NoteDetail

_TOPIC_HEADING = re.compile(r"^###\s+(.+)\s*$")
_SOURCE_LINE = re.compile(r"^Source:\s*(.*)\s*$", re.IGNORECASE)
_CREATED_LINE = re.compile(r"^Created:\s*(.*)\s*$", re.IGNORECASE)
_TAGS_LINE = re.compile(r"^Tags:\s*(.*)\s*$", re.IGNORECASE)
_BULLET = re.compile(r"^[-*]\s+(.+)\s*$")


def bundle_from_note(note: NoteDetail) -> NoteBundle:
    topics = [
        BundleTopic(
            title=topic.title,
            points=[point.text for point in topic.points],
            tags=[tag.tag for tag in topic.tags],
        )
        for topic in note.topics
    ]
    return NoteBundle(
        note=BundleNote(
            title=note.title,
            source=note.source,
            raw_text=note.raw_text,
            created_at=note.created_at,
            topics=topics,
        )
    )


def note_to_markdown(note: NoteDetail) -> str:
    lines = [
        f"# {note.title}",
        "",
        f"Source: {note.source}" if note.source else "Source:",
        f"Created: {note.created_at}",
        "",
        "## Raw notes",
        "",
        note.raw_text.strip(),
        "",
        "## Topics",
        "",
    ]
    if not note.topics:
        lines.append("_No topics extracted._")
        lines.append("")
    for topic in note.topics:
        lines.append(f"### {topic.title}")
        lines.append("")
        for point in topic.points:
            lines.append(f"- {point.text}")
        tags = ", ".join(tag.tag for tag in topic.tags)
        if tags:
            lines.append("")
            lines.append(f"Tags: {tags}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def parse_markdown(text: str) -> NoteBundle:
    stripped = text.strip()
    if not stripped:
        raise ValueError("markdown is empty")
    lines = stripped.splitlines()
    if not lines or not lines[0].startswith("# "):
        raise ValueError("markdown must start with a # title")
    title = lines[0][2:].strip()
    source = ""
    created_at: str | None = None
    raw_lines: list[str] = []
    section: str | None = None
    topics: list[BundleTopic] = []
    current_title: str | None = None
    current_points: list[str] = []
    current_tags: list[str] = []

    def flush_topic() -> None:
        nonlocal current_title, current_points, current_tags
        if current_title is None:
            return
        topics.append(
            BundleTopic(title=current_title, points=current_points, tags=current_tags)
        )
        current_title = None
        current_points = []
        current_tags = []

    for line in lines[1:]:
        if line.strip() == "## Raw notes":
            section = "raw"
            continue
        if line.strip() == "## Topics":
            section = "topics"
            continue
        if section is None:
            source_match = _SOURCE_LINE.match(line)
            if source_match:
                source = source_match.group(1).strip()
                continue
            created_match = _CREATED_LINE.match(line)
            if created_match:
                value = created_match.group(1).strip()
                created_at = value or None
                continue
            continue
        if section == "raw":
            raw_lines.append(line)
            continue
        heading = _TOPIC_HEADING.match(line)
        if heading:
            flush_topic()
            current_title = heading.group(1).strip()
            continue
        if current_title is None:
            continue
        tags_match = _TAGS_LINE.match(line)
        if tags_match:
            current_tags = [
                part.strip()
                for part in tags_match.group(1).split(",")
                if part.strip()
            ]
            continue
        bullet = _BULLET.match(line)
        if bullet:
            current_points.append(bullet.group(1).strip())
    flush_topic()
    raw_text = "\n".join(raw_lines).strip()
    if not title or not raw_text:
        raise ValueError("markdown is missing title or raw notes")
    return NoteBundle(
        note=BundleNote(
            title=title,
            source=source,
            raw_text=raw_text,
            created_at=created_at,
            topics=topics,
        )
    )


def extracted_topics(bundle: NoteBundle) -> list[ExtractedTopic]:
    extracted: list[ExtractedTopic] = []
    for topic in bundle.note.topics:
        points = [item.strip() for item in topic.points if item.strip()]
        tags = [item.strip() for item in topic.tags if item.strip()]
        if not points:
            raise ValueError(f"topic {topic.title!r} has no points")
        if not tags:
            tags = [topic.title]
        extracted.append(ExtractedTopic(title=topic.title.strip(), points=points, tags=tags))
    return extracted
