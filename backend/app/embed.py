"""Local sentence-transformer embeddings.

The MiniLM model is loaded once per process and reused. Tests inject a fake
`embed_texts` so they never download weights.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from typing import Any

from app.config import embed_model

# all-MiniLM-L6-v2 output size. sqlite-vec column dim must match.
EMBEDDING_DIM = 384

_model: Any | None = None
_model_lock = threading.Lock()


def _load_model() -> Any:
    """Load the embedder once. A lock prevents concurrent first-load crashes."""
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(embed_model())
        return _model


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]


def embed_texts(texts: Sequence[str]) -> list[list[float]]:
    if len(texts) == 0:
        return []
    model = _load_model()
    with _model_lock:
        vectors = model.encode(list(texts), normalize_embeddings=True)
    return [row.tolist() for row in vectors]


def serialize_embedding(vector: Sequence[float]) -> bytes:
    """Pack a float32 vector for sqlite-vec."""
    from sqlite_vec import serialize_float32

    if len(vector) != EMBEDDING_DIM:
        raise ValueError(f"expected {EMBEDDING_DIM}-d vector, got {len(vector)}")
    return serialize_float32(list(vector))
