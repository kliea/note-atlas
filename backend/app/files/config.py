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
