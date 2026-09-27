"""Files pipeline settings. Defaults live in app.config so `.env` and shell exports apply."""

from __future__ import annotations

import os
from pathlib import Path

from app.config import load_env

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _repo_path(raw: str) -> Path:
    """Relative paths are resolved from the repo root, like DB_PATH."""
    path = Path(raw)
    return path if path.is_absolute() else _REPO_ROOT / path


def files_dir() -> Path:
    """Where uploads are stored: <files_dir>/<folder_id>/<document_id>_<filename>."""
    load_env()
    return _repo_path(os.environ["FILES_DIR"])


def chunk_size() -> int:
    """Characters per chunk (the lab uses 500)."""
    load_env()
    return int(os.environ["FILES_CHUNK_SIZE"])


def chunk_overlap() -> int:
    """Characters shared by consecutive chunks; 0 is lab-faithful."""
    load_env()
    return int(os.environ["FILES_CHUNK_OVERLAP"])


def chroma_path() -> Path:
    """ChromaDB persistence directory; the Files pipeline's only vector store."""
    load_env()
    return _repo_path(os.environ["FILES_CHROMA_PATH"])


def embed_model() -> str:
    """Ollama embedding model (the lab uses nomic-embed-text)."""
    load_env()
    return os.environ["FILES_EMBED_MODEL"]


def embed_provider() -> str:
    """Where Files embeddings come from: "ollama" (the lab) or "sentence-transformers" (comparisons)."""
    load_env()
    return os.environ["FILES_EMBED_PROVIDER"].strip().lower()


def embed_batch_size() -> int:
    load_env()
    return max(1, int(os.environ["FILES_EMBED_BATCH"]))


def llm_model() -> str:
    """Ollama chat model for answers (the lab uses phi3). OLLAMA_MODEL is not used here."""
    load_env()
    return os.environ["FILES_LLM_MODEL"]


def top_k() -> int:
    """Chunks retrieved per question (the lab uses 3)."""
    load_env()
    return max(1, int(os.environ["FILES_TOP_K"]))


def score_threshold() -> float | None:
    """Minimum cosine similarity a chunk needs to reach the model; blank (the default) is off."""
    load_env()
    raw = os.environ["FILES_SCORE_THRESHOLD"].strip()
    return float(raw) if raw else None


# --- lab enhancement toggles (F6) ------------------------------------------------


def _flag(name: str) -> bool:
    load_env()
    return os.environ[name].strip().lower() not in {"0", "false", "no", "off", ""}


def docx_enabled() -> bool:
    """Enhancement 1: accept Word .docx uploads."""
    return _flag("FILES_DOCX")


def txt_fallback_enabled() -> bool:
    """Enhancement 2: .txt that isn't UTF-8 is read as Windows-1252 instead of rejected."""
    return _flag("FILES_TXT_FALLBACK")


def show_sources() -> bool:
    """Enhancement 3: show a `filename · p.N` source line under each answer."""
    return _flag("FILES_SHOW_SOURCES")


def hybrid_enabled() -> bool:
    """Enhancement 4: fuse BM25 keyword search with vector search (Reciprocal Rank Fusion)."""
    return _flag("FILES_HYBRID")


def memory_turns() -> int:
    """Enhancement 5: earlier question/answer pairs (same scope) included in the prompt; 0 is off."""
    load_env()
    return max(0, int(os.environ["FILES_MEMORY_TURNS"] or 0))


def model_picker_enabled() -> bool:
    """Enhancement 6: a question may name any pulled Ollama model instead of FILES_LLM_MODEL."""
    return _flag("FILES_MODEL_PICKER")
