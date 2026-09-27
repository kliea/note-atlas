"""SQLite persistence and upload storage for the Files pipeline: folders and their documents.

Uploads live at <files_dir>/<folder_id>/<document_id>_<sanitized filename>; the row keeps the
path relative to files_dir. SQLite holds metadata only; vectors live in ChromaDB (F3).
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath

from app.db import get_connection
from app.files.config import files_dir
from app.files.models import (
    FileAsk,
    FileDocument,
    FileFolder,
    FileJob,
    RetrievedChunk,
    SkippedUpload,
    UploadResult,
)

MAX_UPLOAD_BYTES = 100 * 1024 * 1024
_MAX_STORED_NAME = 120
_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")

MIME_PDF = "application/pdf"
MIME_TEXT = "text/plain"


class FolderNameTaken(Exception):
    """Another folder already has this name."""


class UnsupportedFile(Exception):
    """The upload is not a PDF (by magic bytes) or UTF-8 text."""


class UploadTooLarge(Exception):
    """The upload exceeds MAX_UPLOAD_BYTES."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- folders -------------------------------------------------------------------

_FOLDER_SELECT = """
    SELECT f.id, f.name, f.created_at,
           COUNT(d.id) AS document_count,
           COALESCE(SUM(d.chunk_count), 0) AS chunk_count
    FROM file_folders f
    LEFT JOIN file_documents d ON d.folder_id = f.id
"""


def _folder(row: sqlite3.Row) -> FileFolder:
    return FileFolder(
        id=int(row["id"]),
        name=str(row["name"]),
        created_at=str(row["created_at"]),
        document_count=int(row["document_count"]),
        chunk_count=int(row["chunk_count"]),
    )


def list_folders() -> list[FileFolder]:
    conn = get_connection()
    try:
        rows = conn.execute(f"{_FOLDER_SELECT} GROUP BY f.id ORDER BY f.name COLLATE NOCASE").fetchall()
    finally:
        conn.close()
    return [_folder(row) for row in rows]


def get_folder(folder_id: int) -> FileFolder | None:
    conn = get_connection()
    try:
        row = conn.execute(f"{_FOLDER_SELECT} WHERE f.id = ? GROUP BY f.id", (folder_id,)).fetchone()
    finally:
        conn.close()
    return _folder(row) if row is not None else None


def create_folder(name: str) -> FileFolder:
    conn = get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO file_folders (name, created_at) VALUES (?, ?)", (name, _now())
        )
        conn.commit()
        folder_id = int(cursor.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise FolderNameTaken(name) from exc
    finally:
        conn.close()
    folder = get_folder(folder_id)
    assert folder is not None
    return folder


def rename_folder(folder_id: int, name: str) -> FileFolder | None:
    conn = get_connection()
    try:
        cursor = conn.execute("UPDATE file_folders SET name = ? WHERE id = ?", (name, folder_id))
        conn.commit()
        updated = cursor.rowcount > 0
    except sqlite3.IntegrityError as exc:
        raise FolderNameTaken(name) from exc
    finally:
        conn.close()
    return get_folder(folder_id) if updated else None


def delete_folder(folder_id: int) -> bool:
    """Remove the folder, its document rows (cascade), and its stored files."""
    conn = get_connection()
    try:
        cursor = conn.execute("DELETE FROM file_folders WHERE id = ?", (folder_id,))
        conn.commit()
        deleted = cursor.rowcount > 0
    finally:
        conn.close()
    if deleted:
        shutil.rmtree(_folder_dir(folder_id), ignore_errors=True)
    return deleted


# --- documents -----------------------------------------------------------------

_DOCUMENT_COLUMNS = """
    id, folder_id, filename, mime, size_bytes, sha256, page_count, chunk_count,
    status, error, indexed_at, created_at
"""


def _document(row: sqlite3.Row) -> FileDocument:
    return FileDocument(
        id=int(row["id"]),
        folder_id=int(row["folder_id"]),
        filename=str(row["filename"]),
        mime=str(row["mime"]),
        size_bytes=int(row["size_bytes"]),
        sha256=str(row["sha256"]),
        page_count=row["page_count"],
        chunk_count=int(row["chunk_count"]),
        status=row["status"],
        error=row["error"],
        indexed_at=row["indexed_at"],
        created_at=str(row["created_at"]),
    )


def list_documents(folder_id: int) -> list[FileDocument]:
    conn = get_connection()
    try:
        rows = conn.execute(
            f"SELECT {_DOCUMENT_COLUMNS} FROM file_documents WHERE folder_id = ? ORDER BY id",
            (folder_id,),
        ).fetchall()
    finally:
        conn.close()
    return [_document(row) for row in rows]


def get_document(document_id: int) -> FileDocument | None:
    conn = get_connection()
    try:
        row = conn.execute(
            f"SELECT {_DOCUMENT_COLUMNS} FROM file_documents WHERE id = ?", (document_id,)
        ).fetchone()
    finally:
        conn.close()
    return _document(row) if row is not None else None


def document_path(document_id: int) -> Path | None:
    """Absolute path of a stored upload, or None if the document is unknown."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT stored_path FROM file_documents WHERE id = ?", (document_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return _inside(files_dir(), files_dir() / str(row["stored_path"]))


def delete_document(document_id: int) -> bool:
    path = document_path(document_id)
    conn = get_connection()
    try:
        cursor = conn.execute("DELETE FROM file_documents WHERE id = ?", (document_id,))
        conn.commit()
        deleted = cursor.rowcount > 0
    finally:
        conn.close()
    if deleted and path is not None:
        path.unlink(missing_ok=True)
    return deleted


def set_page_count(document_id: int, page_count: int) -> None:
    _update_document(document_id, page_count=page_count)


def mark_failed(document_id: int, reason: str) -> None:
    """Record why a document could not be read; it stays failed until it is rebuilt."""
    _update_document(document_id, status="failed", error=reason[:500])


def mark_indexing(document_id: int) -> None:
    _update_document(document_id, status="indexing", error=None)


def mark_indexed(document_id: int, chunk_count: int) -> None:
    _update_document(document_id, status="indexed", chunk_count=chunk_count, error=None, indexed_at=_now())


def reset_folder_index(folder_id: int) -> None:
    """After its vectors are cleared, every document in the folder is back to `uploaded`."""
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE file_documents
            SET status = 'uploaded', chunk_count = 0, error = NULL, indexed_at = NULL
            WHERE folder_id = ?
            """,
            (folder_id,),
        )
        conn.commit()
    finally:
        conn.close()


def _update_document(document_id: int, **fields: object) -> None:
    assignments = ", ".join(f"{name} = ?" for name in fields)
    conn = get_connection()
    try:
        conn.execute(
            f"UPDATE file_documents SET {assignments} WHERE id = ?", (*fields.values(), document_id)
        )
        conn.commit()
    finally:
        conn.close()


# --- uploads -------------------------------------------------------------------


def display_name(filename: str) -> str:
    """The client's filename without any directory part (either separator)."""
    name = PureWindowsPath(PurePosixPath(filename).name).name.strip()
    return name or "file"


def sanitize_filename(filename: str) -> str:
    """A filesystem-safe name: [A-Za-z0-9._-] only, no leading dots, bounded length."""
    safe = _UNSAFE_CHARS.sub("_", display_name(filename)).lstrip(".")
    return safe[-_MAX_STORED_NAME:] or "file"


def classify_upload(filename: str, data: bytes) -> str:
    """The upload's MIME type: PDF by `%PDF` magic bytes, `.txt` as UTF-8 text."""
    name = display_name(filename)
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadTooLarge(f"{name} is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    if not data:
        raise UnsupportedFile(f"{name} is empty")
    suffix = Path(name).suffix.lower()
    if suffix == ".pdf":
        if not data.startswith(b"%PDF"):
            raise UnsupportedFile(f"{name} is not a PDF")
        return MIME_PDF
    if suffix == ".txt":
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UnsupportedFile(f"{name} is not UTF-8 text") from exc
        return MIME_TEXT
    raise UnsupportedFile(f"{name}: only .pdf and .txt files are supported")


def add_documents(folder_id: int, uploads: list[tuple[str, bytes]]) -> UploadResult:
    """Validate every upload first, then store each one; duplicates in the folder are skipped.

    Raises LookupError for an unknown folder, UnsupportedFile / UploadTooLarge for a bad file
    (nothing is stored in that case).
    """
    if get_folder(folder_id) is None:
        raise LookupError(f"folder {folder_id} not found")
    typed = [(display_name(name), data, classify_upload(name, data)) for name, data in uploads]

    added: list[FileDocument] = []
    skipped: list[SkippedUpload] = []
    for name, data, mime in typed:
        document_id = _store_upload(folder_id, name, data, mime)
        if document_id is None:
            skipped.append(SkippedUpload(filename=name, reason="already in this folder"))
            continue
        document = get_document(document_id)
        assert document is not None
        added.append(document)
    return UploadResult(added=added, skipped=skipped)


def _store_upload(folder_id: int, name: str, data: bytes, mime: str) -> int | None:
    """Insert the row and write the file together; None when the same bytes are already there."""
    sha256 = hashlib.sha256(data).hexdigest()
    folder_dir = _folder_dir(folder_id)
    conn = get_connection()
    target: Path | None = None
    try:
        cursor = conn.execute(
            """
            INSERT INTO file_documents
                (folder_id, filename, mime, size_bytes, sha256, stored_path, created_at)
            VALUES (?, ?, ?, ?, ?, '', ?)
            """,
            (folder_id, name, mime, len(data), sha256, _now()),
        )
        document_id = int(cursor.lastrowid)
        target = _inside(folder_dir, folder_dir / f"{document_id}_{sanitize_filename(name)}")
        folder_dir.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        conn.execute(
            "UPDATE file_documents SET stored_path = ? WHERE id = ?",
            (target.relative_to(files_dir().resolve()).as_posix(), document_id),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        return None
    except Exception:
        conn.rollback()
        if target is not None:
            target.unlink(missing_ok=True)
        raise
    finally:
        conn.close()
    return document_id


def _folder_dir(folder_id: int) -> Path:
    root = files_dir()
    return _inside(root, root / str(int(folder_id)))


def _inside(root: Path, path: Path) -> Path:
    """Resolve `path` and refuse anything that escapes `root`."""
    resolved_root = root.resolve()
    resolved = path.resolve()
    if resolved != resolved_root and not resolved.is_relative_to(resolved_root):
        raise ValueError(f"path escapes the files directory: {path}")
    return resolved


# --- build jobs ----------------------------------------------------------------

_JOB_COLUMNS = "id, folder_id, status, done, total, error, created_at, updated_at"


def _job(row: sqlite3.Row) -> FileJob:
    return FileJob(**{key: row[key] for key in row.keys()})


def create_job(folder_id: int, total: int) -> FileJob:
    now = _now()
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO file_jobs (folder_id, status, total, created_at, updated_at)
            VALUES (?, 'queued', ?, ?, ?)
            """,
            (folder_id, total, now, now),
        )
        conn.commit()
        job_id = int(cursor.lastrowid)
    finally:
        conn.close()
    job = get_job(job_id)
    assert job is not None
    return job


def get_job(job_id: int) -> FileJob | None:
    conn = get_connection()
    try:
        row = conn.execute(f"SELECT {_JOB_COLUMNS} FROM file_jobs WHERE id = ?", (job_id,)).fetchone()
    finally:
        conn.close()
    return _job(row) if row is not None else None


def unfinished_jobs(folder_id: int) -> list[FileJob]:
    conn = get_connection()
    try:
        rows = conn.execute(
            f"SELECT {_JOB_COLUMNS} FROM file_jobs WHERE folder_id = ? AND status IN ('queued', 'running')",
            (folder_id,),
        ).fetchall()
    finally:
        conn.close()
    return [_job(row) for row in rows]


def update_job(job_id: int, **fields: object) -> None:
    assignments = ", ".join(f"{name} = ?" for name in fields)
    conn = get_connection()
    try:
        conn.execute(
            f"UPDATE file_jobs SET {assignments}, updated_at = ? WHERE id = ?",
            (*fields.values(), _now(), job_id),
        )
        conn.commit()
    finally:
        conn.close()


# --- Ask history ---------------------------------------------------------------
# Each row keeps the retrieved chunks' text, so history still shows its sources after the
# documents are deleted or the index is cleared.


def _ask(row: sqlite3.Row) -> FileAsk:
    folder_ids = json.loads(row["folder_ids_json"])
    return FileAsk(
        id=int(row["id"]),
        question=str(row["question"]),
        answer=str(row["answer"]),
        folder_ids=folder_ids or None,
        chunks=[RetrievedChunk(**chunk) for chunk in json.loads(row["chunk_refs_json"])],
        model=str(row["model"]),
        created_at=str(row["created_at"]),
    )


def add_ask(
    question: str, answer: str, folder_ids: list[int] | None, chunks: list[RetrievedChunk], model: str
) -> FileAsk:
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO file_asks (question, answer, folder_ids_json, chunk_refs_json, model, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                question,
                answer,
                json.dumps(folder_ids or []),
                json.dumps([chunk.model_dump() for chunk in chunks]),
                model,
                _now(),
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM file_asks WHERE id = ?", (cursor.lastrowid,)).fetchone()
    finally:
        conn.close()
    return _ask(row)


def list_asks(limit: int = 50) -> list[FileAsk]:
    """Newest first."""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM file_asks ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    finally:
        conn.close()
    return [_ask(row) for row in rows]


def clear_asks() -> int:
    conn = get_connection()
    try:
        cursor = conn.execute("DELETE FROM file_asks")
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()
