"""Local sentence-transformer embeddings.

The MiniLM model is loaded once per process and reused. Tests inject a fake
`embed_texts` so they never download weights.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from typing import Any

from app.config import embed_model

# all-MiniLM-L6-v2 output size. sqlite-vec column dim must match.
EMBEDDING_DIM = 384


@lru_cache(maxsize=1)
def _load_model() -> Any:
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(embed_model())


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]


def embed_texts(texts: Sequence[str]) -> list[list[float]]:
    if len(texts) == 0:
        return []
    model = _load_model()
    vectors = model.encode(list(texts), normalize_embeddings=True)
    return [row.tolist() for row in vectors]


def serialize_embedding(vector: Sequence[float]) -> bytes:
    """Pack a float32 vector for sqlite-vec."""
    from sqlite_vec import serialize_float32

    if len(vector) != EMBEDDING_DIM:
        raise ValueError(f"expected {EMBEDDING_DIM}-d vector, got {len(vector)}")
    return serialize_float32(list(vector))
