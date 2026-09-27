"""ChromaDB storage for Files chunks (lab Part 6: `add_to_vector_db`).

One persistent client per path per process, one cosine collection named `files`. Chunk ids are
deterministic (`"{document_id}:{chunk_idx}"`) and written with upsert, so a rebuild replaces
vectors instead of duplicating them. Chroma's persistent client is single-process: the FastAPI
backend and the Streamlit lab app should not build indexes at the same time.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import chromadb
from chromadb.api.models.Collection import Collection
from chromadb.config import Settings

from app.files.chunk import Chunk
from app.files.config import chroma_path
from app.files.models import FileDocument

COLLECTION = "files"

_clients: dict[Path, Any] = {}
_clients_lock = threading.Lock()


def collection() -> Collection:
    path = chroma_path()
    with _clients_lock:
        client = _clients.get(path)
        if client is None:
            path.mkdir(parents=True, exist_ok=True)
            # Local-only: no telemetry leaves the machine.
            client = chromadb.PersistentClient(path=str(path), settings=Settings(anonymized_telemetry=False))
            _clients[path] = client
    return client.get_or_create_collection(
        COLLECTION, configuration={"hnsw": {"space": "cosine"}}, embedding_function=None
    )


def chunk_id(document_id: int, chunk_idx: int) -> str:
    return f"{document_id}:{chunk_idx}"


def upsert_chunks(document: FileDocument, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
    if len(chunks) != len(embeddings):
        raise ValueError("one embedding per chunk is required")
    if not chunks:
        return
    collection().upsert(
        ids=[chunk_id(document.id, c.idx) for c in chunks],
        embeddings=embeddings,
        documents=[c.text for c in chunks],
        metadatas=[
            {
                "folder_id": document.folder_id,
                "document_id": document.id,
                "filename": document.filename,
                "page_start": c.page_start,
                "chunk_idx": c.idx,
                "char_start": c.char_start,
            }
            for c in chunks
        ],
    )


def delete_document(document_id: int) -> None:
    collection().delete(where={"document_id": document_id})


def delete_folder(folder_id: int) -> None:
    collection().delete(where={"folder_id": folder_id})


def count() -> int:
    return collection().count()


def count_document(document_id: int) -> int:
    return len(collection().get(where={"document_id": document_id}, include=[])["ids"])


def count_folder(folder_id: int) -> int:
    return len(collection().get(where={"folder_id": folder_id}, include=[])["ids"])
