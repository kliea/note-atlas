"""Environment loading for Note Atlas.

Reads a local `.env` file if present. Values already in the process
environment win, so shell exports override the file.
"""

from __future__ import annotations

import os
from pathlib import Path

_DEFAULTS: dict[str, str] = {
    "OLLAMA_HOST": "http://127.0.0.1:11434",
    "OLLAMA_MODEL": "qwen3:4b",
    "EMBED_MODEL": "all-MiniLM-L6-v2",
    "DB_PATH": "./data/notes.db",
    "GROBID_URL": "http://127.0.0.1:8070",
    "GROBID_IMAGE": "grobid/grobid:0.9.1-crf",
    "GROBID_AUTOSTART": "1",
    "OPENALEX_API_KEY": "",
    "S2_API_KEY": "",
    "CROSSREF_MAILTO": "",
    # Files pipeline (lab RAG); its settings are read through app.files.config.
    "FILES_DIR": "./data/files",
    "FILES_CHUNK_SIZE": "500",
    "FILES_CHUNK_OVERLAP": "0",
    "FILES_CHROMA_PATH": "./data/chroma_files",
    "FILES_EMBED_MODEL": "nomic-embed-text",
    "FILES_EMBED_BATCH": "32",
    "FILES_LLM_MODEL": "phi3",
    "FILES_TOP_K": "3",
    "FILES_SCORE_THRESHOLD": "",
}

# Repo root is two levels above this file: note-atlas/backend/app/config.py
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_env() -> None:
    """Populate os.environ from `.env` then apply documented defaults."""
    file_values = _parse_env_file(_REPO_ROOT / ".env")
    for key, value in file_values.items():
        os.environ.setdefault(key, value)
    for key, value in _DEFAULTS.items():
        os.environ.setdefault(key, value)


def ollama_host() -> str:
    load_env()
    return os.environ["OLLAMA_HOST"].rstrip("/")


def ollama_model() -> str:
    load_env()
    return os.environ["OLLAMA_MODEL"]


def embed_model() -> str:
    load_env()
    return os.environ["EMBED_MODEL"]


def db_path() -> str:
    load_env()
    return os.environ["DB_PATH"]


def grobid_url() -> str:
    load_env()
    return os.environ["GROBID_URL"].rstrip("/")


def grobid_image() -> str:
    load_env()
    return os.environ["GROBID_IMAGE"]


def grobid_autostart() -> bool:
    """Start the GROBID container on demand when it is not already reachable."""
    load_env()
    return os.environ["GROBID_AUTOSTART"].strip().lower() not in {"0", "false", "no", ""}


def openalex_api_key() -> str:
    """Optional; raises OpenAlex's daily budget from $0.10 to $1."""
    load_env()
    return os.environ["OPENALEX_API_KEY"].strip()


def s2_api_key() -> str:
    """Optional; the user's own Semantic Scholar key (never shipped with Atlas)."""
    load_env()
    return os.environ["S2_API_KEY"].strip()


def crossref_mailto() -> str:
    """Optional; opts into Crossref's polite pool. Blank by default because it identifies the user."""
    load_env()
    return os.environ["CROSSREF_MAILTO"].strip()
