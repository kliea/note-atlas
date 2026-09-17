"""Chunk text, embed it, and query sqlite-vec."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from app.db import clear_chunk_index, get_note, list_note_ids, replace_note_chunks, search_chunk_rows
from app.embed import embed_texts, serialize_embedding
from app.models import NoteDetail, SearchHit

EmbedFn = Callable[[Sequence[str]], list[list[float]]]


def topic_chunk_text(title: str, points: Sequence[str]) -> str:
    return title.strip() + "\n" + "\n".join(item.strip() for item in points if item.strip())


def note_summary_text(note: NoteDetail) -> str:
    return f"{note.title}\n{note.source}\n{note.raw_text}".strip()


def index_note(note_id: int, embed: EmbedFn | None = None) -> int:
    """Replace chunks + vectors for one note. Returns how many chunks were written."""
    note = get_note(note_id)
    if note is None:
        raise ValueError(f"note {note_id} not found")
    texts, meta = _chunk_payloads(note)
    encode = embed or embed_texts
    vectors = encode(texts) if texts else []
    if len(vectors) != len(texts):
        raise RuntimeError("embed function returned the wrong number of vectors")
    items = [
        (topic_id, text, serialize_embedding(vector))
        for (topic_id, text), vector in zip(meta, vectors, strict=True)
    ]
    return replace_note_chunks(note_id, items)


def reindex_all(embed: EmbedFn | None = None) -> dict[str, int]:
    """Drop the whole vector index and rebuild from every stored note."""
    clear_chunk_index()
    note_ids = list_note_ids()
    chunks = 0
    for note_id in note_ids:
        chunks += index_note(note_id, embed=embed)
    return {"notes": len(note_ids), "chunks": chunks}


def search(query: str, k: int = 5, embed: EmbedFn | None = None) -> list[SearchHit]:
    encode = embed or embed_texts
    vector = encode([query])[0]
    rows = search_chunk_rows(serialize_embedding(vector), k)
    hits: list[SearchHit] = []
    for row in rows:
        distance = float(row["distance"])
        # cosine distance ≈ 1 - similarity for L2-normalized MiniLM vectors
        score = max(0.0, min(1.0, 1.0 - distance))
        topic_id = row["topic_id"]
        hits.append(
            SearchHit(
                chunk_id=int(row["id"]),
                note_id=int(row["note_id"]),
                topic_id=int(topic_id) if topic_id is not None else None,
                text=str(row["text"]),
                score=score,
            )
        )
    return hits


def _chunk_payloads(note: NoteDetail) -> tuple[list[str], list[tuple[int | None, str]]]:
    meta: list[tuple[int | None, str]] = [(None, note_summary_text(note))]
    for topic in note.topics:
        text = topic_chunk_text(topic.title, [point.text for point in topic.points])
        meta.append((topic.id, text))
    return [item[1] for item in meta], meta
