"""Files F3: Ollama embeddings and the ChromaDB store."""

from __future__ import annotations

import io
import json
from typing import Any

import pytest

from app import llm
from app.files import embed, store
from app.files.chunk import Chunk
from app.files.models import FileDocument
from app.llm import embed as real_llm_embed  # bound before the autouse fake replaces app.llm.embed

from .conftest import FakeEmbedder, fake_vector


def _doc(document_id: int, folder_id: int, filename: str = "a.txt") -> FileDocument:
    return FileDocument(
        id=document_id, folder_id=folder_id, filename=filename, mime="text/plain", size_bytes=1,
        sha256="x", page_count=1, chunk_count=0, status="uploaded", error=None, indexed_at=None,
        created_at="now",
    )


def _chunks(*texts: str) -> list[Chunk]:
    return [Chunk(idx=i, text=t, page_start=i + 1, char_start=i * 500) for i, t in enumerate(texts)]


def _put(document: FileDocument, *texts: str) -> None:
    chunks = _chunks(*texts)
    store.upsert_chunks(document, chunks, [fake_vector(c.text) for c in chunks])


def test_upsert_uses_deterministic_ids_and_metadata() -> None:
    _put(_doc(7, 3, "week1.pdf"), "alpha", "beta")
    got = store.collection().get(include=["metadatas", "documents"])
    rows = sorted(zip(got["ids"], got["documents"], got["metadatas"]))
    assert [(i, d) for i, d, _ in rows] == [("7:0", "alpha"), ("7:1", "beta")]
    assert rows[1][2] == {
        "folder_id": 3, "document_id": 7, "filename": "week1.pdf", "page_start": 2, "chunk_idx": 1,
        "char_start": 500,
    }


def test_upserting_again_never_duplicates() -> None:
    document = _doc(7, 3)
    _put(document, "alpha", "beta")
    _put(document, "alpha", "beta")
    assert store.count() == 2


def test_collection_uses_cosine_space() -> None:
    assert store.collection().configuration_json["hnsw"]["space"] == "cosine"


def test_deletes_are_scoped_to_document_and_folder() -> None:
    _put(_doc(1, 10), "a", "b")
    _put(_doc(2, 10), "c")
    _put(_doc(3, 20), "d", "e")
    store.delete_document(1)
    assert (store.count_document(1), store.count_document(2), store.count()) == (0, 1, 3)
    store.delete_folder(10)
    assert (store.count_folder(10), store.count_folder(20)) == (0, 2)


def test_embed_texts_batches_with_the_files_model(embedder: FakeEmbedder, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FILES_EMBED_BATCH", "2")
    vectors = embed.embed_texts(["a", "b", "c"])
    assert vectors == [fake_vector(t) for t in "abc"]
    assert embedder.calls == [("nomic-embed-text", ["a", "b"]), ("nomic-embed-text", ["c"])]


@pytest.mark.parametrize(
    ("error", "hint"),
    [
        ("Ollama model nomic-embed-text not found (HTTP 404)", "ollama pull nomic-embed-text"),
        ("[Errno 61] Connection refused", "ollama serve"),
    ],
)
def test_embed_errors_say_how_to_fix_them(monkeypatch: pytest.MonkeyPatch, error: str, hint: str) -> None:
    def fail(_texts: list[str], *, model: str) -> list[list[float]]:
        raise llm.LlmError(error)

    monkeypatch.setattr("app.llm.embed", fail)
    with pytest.raises(embed.EmbeddingError, match=hint):
        embed.embed_texts(["a"])


def test_llm_embed_posts_to_api_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The shared client's embed call (the real one, not the fixture's fake)."""
    sent: dict[str, Any] = {}

    def urlopen(request: Any, timeout: float) -> io.BytesIO:
        sent["url"] = request.full_url
        sent["body"] = json.loads(request.data)
        return io.BytesIO(json.dumps({"embeddings": [[0.1, 0.2], [0.3, 0.4]]}).encode())

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    assert real_llm_embed(["x", "y"], model="nomic-embed-text") == [[0.1, 0.2], [0.3, 0.4]]
    assert sent["url"].endswith("/api/embed")
    assert sent["body"] == {"model": "nomic-embed-text", "input": ["x", "y"]}
