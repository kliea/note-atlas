"""Keyword search over the Files chunks for hybrid retrieval (enhancement 4).

BM25 (Okapi) runs over the same chunk texts ChromaDB stores, one index per scope (a folder, a set
of folders, or all), rebuilt only when that scope's chunks change.
"""

from __future__ import annotations

import hashlib
import re
import threading

from rank_bm25 import BM25Okapi

from app.files import store

_TOKEN = re.compile(r"\w+", re.UNICODE)

# scope key → (content signature, index, chunk ids in index order)
_indexes: dict[tuple[object, ...], tuple[str, BM25Okapi, list[str]]] = {}
_lock = threading.Lock()


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def search(query: str, folder_ids: list[int] | None, limit: int) -> list[tuple[str, float]]:
    """(chunk id, BM25 score) for chunks sharing at least one term with the query, best first."""
    terms = tokenize(query)
    if not terms:
        return []
    got = store.collection().get(where=store.folder_filter(folder_ids), include=["documents"])
    ids: list[str] = list(got["ids"])
    texts = [text or "" for text in (got["documents"] or [])]
    if not ids:
        return []
    signature = hashlib.sha1("\0".join(ids + ["\1"] + texts).encode("utf-8")).hexdigest()
    key: tuple[object, ...] = tuple(sorted(folder_ids)) if folder_ids else ("all",)
    with _lock:
        cached = _indexes.get(key)
        if cached is None or cached[0] != signature:
            order = sorted(range(len(ids)), key=lambda i: ids[i])  # Chroma's get order isn't guaranteed
            ids = [ids[i] for i in order]
            index = BM25Okapi([tokenize(texts[i]) or [""] for i in order])
            cached = (signature, index, ids)
            _indexes[key] = cached
    _, index, ordered_ids = cached
    scores = index.get_scores(terms)
    query_terms = set(terms)
    ranked = sorted(
        (
            (chunk_id, float(score))
            for chunk_id, score, tokens in zip(ordered_ids, scores, index_tokens(index))
            if query_terms & tokens
        ),
        key=lambda pair: pair[1],
        reverse=True,
    )
    return ranked[:limit]


def index_tokens(index: BM25Okapi) -> list[set[str]]:
    """Each indexed chunk's distinct terms (from BM25's per-document frequency tables)."""
    return [set(freqs) for freqs in index.doc_freqs]
