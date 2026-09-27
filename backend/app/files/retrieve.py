"""Similarity search for the Files pipeline (lab Part 6: `retrieve_context`).

The question is embedded with the same model as the chunks and matched in ChromaDB, top-k 3
by default, optionally limited to some folders. No score gate unless FILES_SCORE_THRESHOLD is set.
"""

from __future__ import annotations

from typing import Any

from app.files import store
from app.files.config import score_threshold, top_k as default_top_k
from app.files.embed import embed_texts
from app.files.models import RetrievedChunk


def folder_filter(folder_ids: list[int] | None) -> dict[str, Any] | None:
    if not folder_ids:
        return None
    if len(folder_ids) == 1:
        return {"folder_id": folder_ids[0]}
    return {"folder_id": {"$in": list(folder_ids)}}


def scope_chunk_count(folder_ids: list[int] | None) -> int:
    if not folder_ids:
        return store.count()
    return sum(store.count_folder(folder_id) for folder_id in set(folder_ids))


def retrieve_context(
    question: str, folder_ids: list[int] | None = None, top_k: int | None = None
) -> list[RetrievedChunk]:
    k = top_k or default_top_k()
    (query_vector,) = embed_texts([question])
    results = store.collection().query(
        query_embeddings=[query_vector],
        n_results=k,
        where=folder_filter(folder_ids),
        include=["documents", "metadatas", "distances"],
    )
    ids = results["ids"][0]
    documents = (results["documents"] or [[]])[0]
    metadatas = (results["metadatas"] or [[]])[0]
    distances = (results["distances"] or [[]])[0]
    chunks = [
        RetrievedChunk(
            id=chunk_id,
            document_id=int(meta["document_id"]),
            folder_id=int(meta["folder_id"]),
            filename=str(meta["filename"]),
            page_start=int(meta["page_start"]),
            chunk_idx=int(meta["chunk_idx"]),
            text=text or "",
            score=round(1.0 - float(distance), 4),
        )
        for chunk_id, text, meta, distance in zip(ids, documents, metadatas, distances)
    ]
    threshold = score_threshold()
    if threshold is not None:
        chunks = [chunk for chunk in chunks if chunk.score >= threshold]
    return chunks
