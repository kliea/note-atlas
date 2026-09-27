"""Similarity search for the Files pipeline (lab Part 6: `retrieve_context`).

The question is embedded with the same model as the chunks and matched in ChromaDB, top-k 3
by default, optionally limited to some folders. No score gate unless FILES_SCORE_THRESHOLD is set.

With FILES_HYBRID on (enhancement 4), BM25 keyword search runs over the same chunks and the two
rankings are fused by Reciprocal Rank Fusion (k = 60); each chunk records which search found it.
`score` stays the cosine similarity either way, so the threshold means the same thing.
"""

from __future__ import annotations

import math
from typing import Any

from app.files import bm25, store
from app.files.config import hybrid_enabled, score_threshold, top_k as default_top_k
from app.files.embed import embed_texts
from app.files.models import RetrievedChunk

RRF_K = 60
_HYBRID_CANDIDATES = 20  # per retriever, before fusion (at least 4 × k)


def scope_chunk_count(folder_ids: list[int] | None) -> int:
    if not folder_ids:
        return store.count()
    return sum(store.count_folder(folder_id) for folder_id in set(folder_ids))


def retrieve_context(
    question: str, folder_ids: list[int] | None = None, top_k: int | None = None
) -> list[RetrievedChunk]:
    k = top_k or default_top_k()
    (query_vector,) = embed_texts([question])
    if hybrid_enabled():
        chunks = _hybrid(question, query_vector, folder_ids, k)
    else:
        chunks = _vector(query_vector, folder_ids, k)
    threshold = score_threshold()
    if threshold is not None:
        chunks = [chunk for chunk in chunks if chunk.score >= threshold]
    return chunks


def _vector(query_vector: list[float], folder_ids: list[int] | None, n: int) -> list[RetrievedChunk]:
    results = store.collection().query(
        query_embeddings=[query_vector],
        n_results=n,
        where=store.folder_filter(folder_ids),
        include=["documents", "metadatas", "distances"],
    )
    return [
        _chunk(chunk_id, text, meta, 1.0 - float(distance))
        for chunk_id, text, meta, distance in zip(
            results["ids"][0],
            (results["documents"] or [[]])[0],
            (results["metadatas"] or [[]])[0],
            (results["distances"] or [[]])[0],
        )
    ]


def _hybrid(question: str, query_vector: list[float], folder_ids: list[int] | None, k: int) -> list[RetrievedChunk]:
    candidates = max(_HYBRID_CANDIDATES, 4 * k)
    by_vector = _vector(query_vector, folder_ids, candidates)
    by_keyword = [chunk_id for chunk_id, _ in bm25.search(question, folder_ids, candidates)]

    fused: dict[str, float] = {}
    for ranking in ([c.id for c in by_vector], by_keyword):
        for rank, chunk_id in enumerate(ranking, start=1):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)
    chosen = sorted(fused, key=lambda chunk_id: fused[chunk_id], reverse=True)[:k]

    vector_hits = {c.id: c for c in by_vector}
    keyword_hits = set(by_keyword)
    keyword_only = _fetch([cid for cid in chosen if cid not in vector_hits], query_vector)
    out: list[RetrievedChunk] = []
    for chunk_id in chosen:
        chunk = vector_hits.get(chunk_id) or keyword_only[chunk_id]
        retriever = "both" if chunk_id in vector_hits and chunk_id in keyword_hits else (
            "vector" if chunk_id in vector_hits else "bm25"
        )
        out.append(chunk.model_copy(update={"retriever": retriever}))
    return out


def _fetch(ids: list[str], query_vector: list[float]) -> dict[str, RetrievedChunk]:
    """Chunks BM25 found but vector search didn't, scored by cosine similarity to the question."""
    if not ids:
        return {}
    got = store.collection().get(ids=ids, include=["documents", "metadatas", "embeddings"])
    return {
        chunk_id: _chunk(chunk_id, text, meta, _cosine(query_vector, list(embedding)))
        for chunk_id, text, meta, embedding in zip(
            got["ids"], got["documents"] or [], got["metadatas"] or [], got["embeddings"]
        )
    }


def _cosine(a: list[float], b: list[float]) -> float:
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b)) / norm if norm else 0.0


def _chunk(chunk_id: str, text: str | None, meta: Any, similarity: float) -> RetrievedChunk:
    return RetrievedChunk(
        id=chunk_id,
        document_id=int(meta["document_id"]),
        folder_id=int(meta["folder_id"]),
        filename=str(meta["filename"]),
        page_start=int(meta["page_start"]),
        chunk_idx=int(meta["chunk_idx"]),
        text=text or "",
        score=round(similarity, 4),
    )
