"""Files F3: building, rebuilding, clearing, and deleting a folder's index."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import llm
from app.files import build, repo, service, store

from .conftest import FakeEmbedder

TXT_A = ("Retrieval augmented generation grounds answers in documents. " * 20).encode()  # 1,240 chars → 3 chunks
TXT_B = ("Vector databases store embeddings for similarity search. " * 10).encode()  # 570 chars → 2 chunks
SCANNED = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"  # opens as nothing readable


def _folder(name: str, *files: tuple[str, bytes]) -> int:
    folder = repo.create_folder(name)
    repo.add_documents(folder.id, list(files))
    return folder.id


def test_build_indexes_every_document(embedder: FakeEmbedder) -> None:
    folder_id = _folder("Lectures", ("a.txt", TXT_A), ("b.txt", TXT_B))
    progress: list[tuple[int, int]] = []
    summary = service.build_folder(folder_id, on_progress=lambda d, t, _doc: progress.append((d, t)))

    assert summary.model_dump() == {"indexed": 2, "skipped": 0, "failed": 0, "chunks": 5}
    assert progress == [(1, 2), (2, 2)]
    docs = repo.list_documents(folder_id)
    assert [(d.status, d.chunk_count, d.page_count) for d in docs] == [("indexed", 3, 1), ("indexed", 2, 1)]
    assert all(d.indexed_at for d in docs)
    assert store.count() == 5 and store.count_folder(folder_id) == 5
    assert len(embedder.texts) == 5
    assert repo.get_folder(folder_id).chunk_count == 5  # type: ignore[union-attr]


def test_building_again_adds_nothing_and_embeds_nothing(embedder: FakeEmbedder) -> None:
    folder_id = _folder("Lectures", ("a.txt", TXT_A), ("b.txt", TXT_B))
    service.build_folder(folder_id)
    calls = len(embedder.calls)

    summary = service.build_folder(folder_id)
    assert summary.model_dump() == {"indexed": 0, "skipped": 2, "failed": 0, "chunks": 5}
    assert store.count() == 5
    assert len(embedder.calls) == calls


def test_new_upload_is_the_only_thing_embedded_on_rebuild(embedder: FakeEmbedder) -> None:
    folder_id = _folder("Lectures", ("a.txt", TXT_A))
    service.build_folder(folder_id)
    embedder.calls.clear()
    repo.add_documents(folder_id, [("b.txt", TXT_B)])
    assert service.build_folder(folder_id).indexed == 1
    assert len(embedder.texts) == 2 and store.count() == 5


def test_missing_vectors_are_rebuilt() -> None:
    folder_id = _folder("Lectures", ("a.txt", TXT_A))
    service.build_folder(folder_id)
    document = repo.list_documents(folder_id)[0]
    store.delete_document(document.id)  # e.g. the Chroma directory was wiped
    assert service.build_folder(folder_id).indexed == 1
    assert store.count_document(document.id) == 3


def test_one_failing_document_does_not_abort_the_folder() -> None:
    folder_id = _folder("Lectures", ("scan.pdf", SCANNED), ("a.txt", TXT_A))
    summary = service.build_folder(folder_id)
    assert (summary.indexed, summary.failed) == (1, 1)
    scan, text = repo.list_documents(folder_id)
    assert scan.status == "failed" and scan.error
    assert text.status == "indexed"
    assert store.count() == 3


def test_ollama_down_marks_documents_failed_with_a_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    def down(_texts: list[str], *, model: str) -> list[list[float]]:
        raise llm.LlmError("[Errno 61] Connection refused")

    monkeypatch.setattr("app.llm.embed", down)
    folder_id = _folder("Lectures", ("a.txt", TXT_A))
    assert service.build_folder(folder_id).failed == 1
    document = repo.list_documents(folder_id)[0]
    assert document.status == "failed" and "ollama serve" in (document.error or "")
    assert store.count() == 0


def test_clear_empties_only_that_folder() -> None:
    lectures = _folder("Lectures", ("a.txt", TXT_A))
    labs = _folder("Labs", ("b.txt", TXT_B))
    service.build_folder(lectures)
    service.build_folder(labs)

    assert service.clear_folder_index(lectures) is True
    assert (store.count_folder(lectures), store.count_folder(labs)) == (0, 2)
    assert [(d.status, d.chunk_count, d.indexed_at) for d in repo.list_documents(lectures)] == [
        ("uploaded", 0, None)
    ]
    assert repo.list_documents(labs)[0].status == "indexed"
    assert service.clear_folder_index(999) is False


def test_deleting_a_document_removes_exactly_its_vectors() -> None:
    folder_id = _folder("Lectures", ("a.txt", TXT_A), ("b.txt", TXT_B))
    service.build_folder(folder_id)
    first, second = repo.list_documents(folder_id)
    assert service.delete_document(first.id) is True
    assert store.count_document(first.id) == 0
    assert store.count_document(second.id) == 2
    assert store.count() == 2


def test_deleting_a_folder_removes_its_vectors() -> None:
    lectures = _folder("Lectures", ("a.txt", TXT_A))
    labs = _folder("Labs", ("b.txt", TXT_B))
    service.build_folder(lectures)
    service.build_folder(labs)
    assert service.delete_folder(lectures) is True
    assert store.count() == 2 and store.count_folder(labs) == 2


# --- API -----------------------------------------------------------------------


def test_build_job_status_and_clear_over_http(client: TestClient) -> None:
    folder_id = _folder("Lectures", ("a.txt", TXT_A), ("b.txt", TXT_B))
    other = _folder("Labs", ("c.txt", TXT_B + b" more"))

    response = client.post(f"/files/folders/{folder_id}/build")
    assert response.status_code == 202
    job = response.json()
    assert job["folder_id"] == folder_id and job["total"] == 2
    # TestClient runs background tasks before returning, so the job has finished.
    finished = client.get(f"/files/jobs/{job['id']}").json()
    assert (finished["status"], finished["done"], finished["total"]) == ("done", 2, 2)

    client.post(f"/files/folders/{other}/build")
    status = client.get("/files/status").json()
    assert status["total_chunks"] == 7
    assert {f["name"]: f["chunk_count"] for f in status["folders"]} == {"Lectures": 5, "Labs": 2}

    assert client.delete(f"/files/folders/{folder_id}/index").status_code == 204
    status = client.get("/files/status").json()
    assert status["total_chunks"] == 2
    listed = client.get(f"/files/folders/{folder_id}/documents").json()
    assert {d["status"] for d in listed} == {"uploaded"}

    assert client.post("/files/folders/999/build").status_code == 404
    assert client.get("/files/jobs/999").status_code == 404
    assert client.delete("/files/folders/999/index").status_code == 404


def test_build_while_building_returns_the_same_job(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    folder_id = _folder("Lectures", ("a.txt", TXT_A))
    job, created = build.start_job(folder_id)  # queued, owned by this process, not yet run
    assert created
    ran: list[int] = []
    monkeypatch.setattr(build, "run_job", lambda job_id: ran.append(job_id))

    response = client.post(f"/files/folders/{folder_id}/build")
    assert response.json()["id"] == job.id
    assert ran == []  # not scheduled twice

    assert client.delete(f"/files/folders/{folder_id}/index").status_code == 409
    assert client.delete(f"/files/folders/{folder_id}").status_code == 409
    document = repo.list_documents(folder_id)[0]
    assert client.delete(f"/files/documents/{document.id}").status_code == 409



def test_orphaned_job_is_reported_interrupted(client: TestClient) -> None:
    folder_id = _folder("Lectures", ("a.txt", TXT_A))
    orphan = repo.create_job(folder_id, total=1)  # as if the server died mid-build
    body = client.get(f"/files/jobs/{orphan.id}").json()
    assert body["status"] == "failed" and "interrupted" in body["error"]
