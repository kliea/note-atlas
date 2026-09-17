"""Environment loading for Note Atlas.

Reads a local `.env` file if present. Values already in the process
environment win, so shell exports override the file.
"""

from __future__ import annotations

import os
from pathlib import Path

_DEFAULTS: dict[str, str] = {
    "OLLAMA_HOST": "http://127.0.0.1:11434",
    "OLLAMA_MODEL": "qwen2.5:3b-instruct",
    "EMBED_MODEL": "all-MiniLM-L6-v2",
    "DB_PATH": "./data/notes.db",
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
