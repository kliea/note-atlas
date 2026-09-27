"""Embeddings for the Files pipeline (lab Part 6: `create_embedding`).

The lab path is Ollama `/api/embed` with nomic-embed-text. For the F7 comparison there is also a
Files-local sentence-transformers adapter (FILES_EMBED_PROVIDER=sentence-transformers, e.g.
all-MiniLM-L6-v2). It loads weights from the local cache only, and it is separate from the Board
pipeline's embedder.
"""

from __future__ import annotations

import threading
from typing import Any

from app import llm
from app.files.config import embed_batch_size, embed_model, embed_provider

SENTENCE_TRANSFORMERS = "sentence-transformers"

_st_models: dict[str, Any] = {}
_st_lock = threading.Lock()


class EmbeddingError(Exception):
    """The embedder could not run; the message says how to fix it."""


def embed_texts(texts: list[str]) -> list[list[float]]:
    """One vector per text, in order, embedded in batches of FILES_EMBED_BATCH."""
    model = embed_model()
    provider = embed_provider()
    if provider == SENTENCE_TRANSFORMERS:
        return _embed_local(texts, model)
    if provider != "ollama":
        raise EmbeddingError(f"unknown FILES_EMBED_PROVIDER {provider!r}; use ollama or {SENTENCE_TRANSFORMERS}")
    size = embed_batch_size()
    vectors: list[list[float]] = []
    for start in range(0, len(texts), size):
        try:
            vectors.extend(llm.embed(texts[start : start + size], model=model))
        except llm.LlmError as exc:
            raise EmbeddingError(_explain(model, str(exc))) from exc
    return vectors


def _explain(model: str, error: str) -> str:
    if "not found" in error:
        return f"embedding model {model} is not pulled; run `ollama pull {model}`"
    return f"could not reach Ollama to embed ({error}); is `ollama serve` running?"


def _embed_local(texts: list[str], model_name: str) -> list[list[float]]:
    if not texts:
        return []
    model = _sentence_transformer(model_name)
    with _st_lock:
        vectors = model.encode(list(texts), normalize_embeddings=True, batch_size=embed_batch_size())
    return [[float(x) for x in row] for row in vectors]


def _sentence_transformer(model_name: str) -> Any:
    with _st_lock:
        cached = _st_models.get(model_name)
        if cached is not None:
            return cached
        try:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(model_name, local_files_only=True)
        except ImportError as exc:
            raise EmbeddingError("sentence-transformers is not installed") from exc
        except Exception as exc:  # noqa: BLE001 — missing weights surface as several error types
            raise EmbeddingError(
                f"could not load {model_name} from the local cache ({exc}); download it once while online"
            ) from exc
        _st_models[model_name] = model
        return model
