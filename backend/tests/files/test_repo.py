"""Files F1: folders and uploaded documents, storage only."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.db import get_connection, migrate_down
from app.files import repo

PDF = b"%PDF-1.4\n%fake but magic-correct\n"
TXT = "Plain notes. Café.".encode("utf-8")

_FILES_TABLES = {"file_folders", "file_documents", "file_jobs", "file_asks"}


def _tables() -> set[str]:
    conn = get_connection()
    try:
        return {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


def test_migration_v12_creates_and_drops_files_tables() -> None:
    assert _FILES_TABLES <= _tables()
    migrate_down(11)
    names = _tables()
    assert not (_FILES_TABLES & names)
    assert "studies" in names and "notes" in names


def test_same_bytes_cannot_be_added_twice_to_a_folder() -> None:
    folder = repo.create_folder("Lectures")
    conn = get_connection()
    try:
        row = (folder.id, "a.pdf", repo.MIME_PDF, 1, "abc", "x", "now")
        sql = """INSERT INTO file_documents
                 (folder_id, filename, mime, size_bytes, sha256, stored_path, created_at)
                 VALUES (?, ?, ?, ?, ?, ?, ?)"""
        conn.execute(sql, row)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(sql, row)
    finally:
        conn.close()


def test_folder_crud_and_unique_names() -> None:
    lectures = repo.create_folder("Lectures")
    repo.create_folder("Labs")
    assert [f.name for f in repo.list_folders()] == ["Labs", "Lectures"]
    with pytest.raises(repo.FolderNameTaken):
        repo.create_folder("Labs")
    with pytest.raises(repo.FolderNameTaken):
        repo.rename_folder(lectures.id, "Labs")
    renamed = repo.rename_folder(lectures.id, "Week 1")
    assert renamed is not None and renamed.name == "Week 1"
    assert repo.rename_folder(999, "Nope") is None
    assert repo.delete_folder(999) is False


def test_uploads_are_stored_under_the_folder_and_duplicates_skipped(files_env: Path) -> None:
    folder = repo.create_folder("Lectures")
    result = repo.add_documents(
        folder.id, [("week1.pdf", PDF), ("notes.txt", TXT), ("copy.pdf", PDF)]
    )
    assert [d.filename for d in result.added] == ["week1.pdf", "notes.txt"]
    assert [(s.filename, s.reason) for s in result.skipped] == [("copy.pdf", "already in this folder")]
    assert all(d.status == "uploaded" and d.chunk_count == 0 for d in result.added)
    assert [d.mime for d in result.added] == [repo.MIME_PDF, repo.MIME_TEXT]

    pdf = result.added[0]
    stored = repo.document_path(pdf.id)
    assert stored == (files_env / str(folder.id) / f"{pdf.id}_week1.pdf").resolve()
    assert stored.read_bytes() == PDF

    again = repo.add_documents(folder.id, [("week1.pdf", PDF)])
    assert again.added == [] and len(again.skipped) == 1

    # The same file is welcome in a different folder.
    other = repo.create_folder("Other")
    assert len(repo.add_documents(other.id, [("week1.pdf", PDF)]).added) == 1

    counted = repo.get_folder(folder.id)
    assert counted is not None and counted.document_count == 2


def test_bad_file_rejects_the_whole_batch() -> None:
    folder = repo.create_folder("Lectures")
    with pytest.raises(repo.UnsupportedFile):
        repo.add_documents(folder.id, [("ok.pdf", PDF), ("slides.pptx", b"PK\x03\x04")])
    assert repo.list_documents(folder.id) == []


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("fake.pdf", b"not a pdf"),
        ("latin.txt", "café".encode("cp1252")),
        ("empty.txt", b""),
        ("image.png", b"\x89PNG"),
        ("noext", PDF),
    ],
)
def test_classify_rejects_unsupported_files(name: str, data: bytes) -> None:
    with pytest.raises(repo.UnsupportedFile):
        repo.classify_upload(name, data)


def test_classify_rejects_oversized_uploads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repo, "MAX_UPLOAD_BYTES", 8)
    with pytest.raises(repo.UploadTooLarge):
        repo.classify_upload("big.pdf", PDF)


@pytest.mark.parametrize(
    ("raw", "safe", "shown"),
    [
        ("../../etc/passwd.txt", "passwd.txt", "passwd.txt"),
        ("..\\..\\win.ini.txt", "win.ini.txt", "win.ini.txt"),
        ("My Lecture (1).pdf", "My_Lecture_1_.pdf", "My Lecture (1).pdf"),
        ("..hidden.txt", "hidden.txt", "..hidden.txt"),
        ("..", "file", ".."),
    ],
)
def test_filenames_cannot_escape_the_folder(raw: str, safe: str, shown: str) -> None:
    assert repo.sanitize_filename(raw) == safe
    assert repo.display_name(raw) == shown


def test_traversal_filename_is_stored_inside_the_folder(files_env: Path) -> None:
    folder = repo.create_folder("Lectures")
    doc = repo.add_documents(folder.id, [("../../../escape.txt", TXT)]).added[0]
    stored = repo.document_path(doc.id)
    assert stored is not None and stored.parent == (files_env / str(folder.id)).resolve()
    assert not (files_env.parent / "escape.txt").exists()


def test_delete_document_and_folder_remove_files_from_disk(files_env: Path) -> None:
    folder = repo.create_folder("Lectures")
    first, second = repo.add_documents(folder.id, [("a.pdf", PDF), ("b.txt", TXT)]).added
    first_path = repo.document_path(first.id)
    assert first_path is not None and first_path.exists()

    assert repo.delete_document(first.id) is True
    assert not first_path.exists()
    assert repo.get_document(first.id) is None
    assert repo.delete_document(first.id) is False

    assert repo.delete_folder(folder.id) is True
    assert repo.get_document(second.id) is None
    assert not (files_env / str(folder.id)).exists()
