"""Files F1 HTTP API: folders and multi-file uploads."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

PDF = b"%PDF-1.4\n%fake but magic-correct\n"
TXT = b"Plain lecture notes."


def _folder(client: TestClient, name: str = "Lectures") -> dict:
    response = client.post("/files/folders", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def _upload(client: TestClient, folder_id: int, *files: tuple[str, bytes, str]):
    parts = [("files", (name, data, mime)) for name, data, mime in files]
    return client.post(f"/files/folders/{folder_id}/documents", files=parts)


def test_folder_lifecycle(client: TestClient) -> None:
    folder = _folder(client, "  Lectures  ")
    assert folder["name"] == "Lectures"
    assert folder["document_count"] == 0 and folder["chunk_count"] == 0

    assert client.post("/files/folders", json={"name": "Lectures"}).status_code == 409
    assert client.post("/files/folders", json={"name": "   "}).status_code == 422

    renamed = client.patch(f"/files/folders/{folder['id']}", json={"name": "Week 1"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "Week 1"
    assert client.patch("/files/folders/999", json={"name": "x"}).status_code == 404

    assert [f["name"] for f in client.get("/files/folders").json()] == ["Week 1"]
    assert client.delete(f"/files/folders/{folder['id']}").status_code == 204
    assert client.delete(f"/files/folders/{folder['id']}").status_code == 404
    assert client.get("/files/folders").json() == []


def test_upload_lists_documents_and_skips_duplicates(client: TestClient, files_env: Path) -> None:
    folder = _folder(client)
    response = _upload(
        client,
        folder["id"],
        ("a.pdf", PDF, "application/pdf"),
        ("b.pdf", PDF + b"other", "application/pdf"),
        ("notes.txt", TXT, "text/plain"),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [d["filename"] for d in body["added"]] == ["a.pdf", "b.pdf", "notes.txt"]
    assert body["skipped"] == []

    again = _upload(client, folder["id"], ("a-again.pdf", PDF, "application/pdf")).json()
    assert again["added"] == []
    assert again["skipped"] == [{"filename": "a-again.pdf", "reason": "already in this folder"}]

    listed = client.get(f"/files/folders/{folder['id']}/documents").json()
    assert [(d["filename"], d["status"]) for d in listed] == [
        ("a.pdf", "uploaded"),
        ("b.pdf", "uploaded"),
        ("notes.txt", "uploaded"),
    ]
    assert "stored_path" not in listed[0]

    assert client.delete(f"/files/documents/{listed[0]['id']}").status_code == 204
    assert client.delete(f"/files/documents/{listed[0]['id']}").status_code == 404
    assert len(client.get(f"/files/folders/{folder['id']}/documents").json()) == 2

    assert client.delete(f"/files/folders/{folder['id']}").status_code == 204
    assert not (files_env / str(folder["id"])).exists()


def test_unsupported_upload_is_415_and_stores_nothing(client: TestClient) -> None:
    folder = _folder(client)
    response = _upload(
        client,
        folder["id"],
        ("a.pdf", PDF, "application/pdf"),
        ("slides.docx", b"PK\x03\x04", "application/octet-stream"),
    )
    assert response.status_code == 415
    assert "slides.docx" in response.json()["detail"]
    assert client.get(f"/files/folders/{folder['id']}/documents").json() == []

    renamed_png = _upload(client, folder["id"], ("photo.pdf", b"\x89PNG", "application/pdf"))
    assert renamed_png.status_code == 415


def test_unknown_folder_is_404(client: TestClient) -> None:
    assert client.get("/files/folders/42/documents").status_code == 404
    assert _upload(client, 42, ("a.pdf", PDF, "application/pdf")).status_code == 404
