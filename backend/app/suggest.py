"""Nearest-neighbor link suggestions, with a shared-tag fallback."""

from __future__ import annotations

from app.db import chunk_count, connected_note_ids, get_note, list_notes
from app.index import note_summary_text, search
from app.models import LinkSuggestion, NoteDetail

_EMBED_THRESHOLD = 0.42
_MAX_SUGGESTIONS = 3
_SEARCH_K = 12


def suggest_links(note_id: int) -> list[LinkSuggestion]:
    note = get_note(note_id)
    if note is None:
        return []
    connected = connected_note_ids(note_id)
    if chunk_count() > 0:
        hits = _embedding_suggestions(note, connected)
        if hits:
            return hits
    return _tag_suggestions(note, connected)


def _embedding_suggestions(
    note: NoteDetail, connected: set[int]
) -> list[LinkSuggestion]:
    total = chunk_count()
    if total == 0:
        return []
    try:
        hits = search(note_summary_text(note), k=min(_SEARCH_K, total), board_id=note.board_id)
    except Exception:  # noqa: BLE001
        return []
    best: dict[int, float] = {}
    titles: dict[int, str] = {}
    for hit in hits:
        other_id = hit.note_id
        if other_id == note.id or other_id in connected:
            continue
        if hit.score < _EMBED_THRESHOLD:
            continue
        previous = best.get(other_id, 0.0)
        if hit.score > previous:
            best[other_id] = hit.score
            other = get_note(other_id)
            titles[other_id] = other.title if other is not None else ""
    ranked = sorted(best.items(), key=lambda item: item[1], reverse=True)
    return [
        LinkSuggestion(
            note_id=other_id,
            title=titles.get(other_id, ""),
            score=round(score, 4),
            reason="embedding",
        )
        for other_id, score in ranked[:_MAX_SUGGESTIONS]
    ]


def _tag_suggestions(note: NoteDetail, connected: set[int]) -> list[LinkSuggestion]:
    tags = _note_tags(note)
    if not tags:
        return []
    scored: list[LinkSuggestion] = []
    for summary in list_notes(note.board_id):
        if summary.id == note.id or summary.id in connected:
            continue
        other = get_note(summary.id)
        if other is None:
            continue
        overlap = tags & _note_tags(other)
        if not overlap:
            continue
        union = tags | _note_tags(other)
        score = len(overlap) / len(union)
        scored.append(
            LinkSuggestion(
                note_id=other.id,
                title=other.title,
                score=round(score, 4),
                reason="shared-tag",
            )
        )
    scored.sort(key=lambda item: item.score, reverse=True)
    return scored[:_MAX_SUGGESTIONS]


def _note_tags(note: NoteDetail) -> set[str]:
    return {tag.tag for topic in note.topics for tag in topic.tags}
