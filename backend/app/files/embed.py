"""Embeddings for the Files pipeline (lab Part 6: `create_embedding`) via Ollama `/api/embed`."""

from __future__ import annotations

from app import llm
from app.files.config import embed_batch_size, embed_model


class EmbeddingError(Exception):
    """Ollama could not embed; the message says how to fix it."""


def embed_texts(texts: list[str]) -> list[list[float]]:
    """One vector per text, in order, embedded in batches of FILES_EMBED_BATCH."""
    model = embed_model()
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
