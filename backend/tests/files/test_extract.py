"""Files F2: PyMuPDF extraction and the chunk preview endpoint."""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.files import repo
from app.files.extract import ExtractionError, extract_text


def _pdf(pages: list[str], *, password: str | None = None) -> bytes:
    """A small real PDF with one text line per page; an empty string makes a blank page."""
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_textbox(pymupdf.Rect(72, 72, 540, 770), text, fontsize=9)
    if password is None:
        data = doc.tobytes()
    else:
        data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=password, owner_pw=password + "!")
    doc.close()
    return data


def _write(tmp_path: Path, data: bytes, name: str = "doc.pdf") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_pdf_pages_are_extracted_in_order(tmp_path: Path) -> None:
    pages = extract_text(_write(tmp_path, _pdf(["Retrieval basics.", "Vector stores."])), repo.MIME_PDF)
    assert [p.page_no for p in pages] == [1, 2]
    assert "Retrieval basics." in pages[0].text
    assert "Vector stores." in pages[1].text


def test_txt_is_one_page(tmp_path: Path) -> None:
    pages = extract_text(_write(tmp_path, "héllo\nworld".encode(), "n.txt"), repo.MIME_TEXT)
    assert [(p.page_no, p.text) for p in pages] == [(1, "héllo\nworld")]


def test_image_only_pdf_has_a_readable_reason(tmp_path: Path) -> None:
    with pytest.raises(ExtractionError, match="scanned or image-only"):
        extract_text(_write(tmp_path, _pdf(["", ""])), repo.MIME_PDF)


def test_password_protected_pdf_has_a_readable_reason(tmp_path: Path) -> None:
    with pytest.raises(ExtractionError, match="password-protected"):
        extract_text(_write(tmp_path, _pdf(["secret"], password="pw")), repo.MIME_PDF)


def test_damaged_pdf_has_a_readable_reason(tmp_path: Path) -> None:
    with pytest.raises(ExtractionError, match="could not open"):
        extract_text(_write(tmp_path, b"%PDF-1.4\ngarbage"), repo.MIME_PDF)


def _upload(client: TestClient, name: str, data: bytes) -> dict:
    folder = client.post("/files/folders", json={"name": "Lectures"}).json()
    body = client.post(
        f"/files/folders/{folder['id']}/documents", files=[("files", (name, data, "application/pdf"))]
    ).json()
    return body["added"][0]


def test_preview_returns_chunks_with_pages_and_records_page_count(client: TestClient) -> None:
    long_page = "Lorem ipsum dolor sit amet. " * 40  # ~1,120 characters
    doc = _upload(client, "lecture.pdf", _pdf([long_page, "Second page text. " * 40]))

    response = client.get(f"/files/documents/{doc['id']}/chunks", params={"limit": 2})
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["page_count"], body["chunk_size"], body["overlap"]) == (2, 500, 0)
    assert body["total_chunks"] >= 3
    assert [c["idx"] for c in body["chunks"]] == [0, 1]
    assert all(len(c["text"]) == 500 for c in body["chunks"])
    assert [c["page_start"] for c in body["chunks"]] == [1, 1]

    everything = client.get(f"/files/documents/{doc['id']}/chunks", params={"limit": 100}).json()
    assert everything["chunks"][-1]["page_start"] == 2

    listed = client.get(f"/files/folders/{doc['folder_id']}/documents").json()[0]
    assert (listed["page_count"], listed["status"], listed["chunk_count"]) == (2, "uploaded", 0)


def test_overlap_comes_from_config(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FILES_CHUNK_OVERLAP", "100")
    doc = _upload(client, "lecture.pdf", _pdf(["x" * 1200]))
    body = client.get(f"/files/documents/{doc['id']}/chunks").json()
    assert body["overlap"] == 100
    assert [c["char_start"] for c in body["chunks"]][:3] == [0, 400, 800]


def test_scanned_pdf_is_marked_failed_with_the_reason(client: TestClient) -> None:
    doc = _upload(client, "scan.pdf", _pdf([""]))
    response = client.get(f"/files/documents/{doc['id']}/chunks")
    assert response.status_code == 422
    assert "scanned or image-only" in response.json()["detail"]
    listed = client.get(f"/files/folders/{doc['folder_id']}/documents").json()[0]
    assert listed["status"] == "failed"
    assert "scanned or image-only" in listed["error"]


def test_preview_unknown_document_is_404(client: TestClient) -> None:
    assert client.get("/files/documents/999/chunks").status_code == 404
