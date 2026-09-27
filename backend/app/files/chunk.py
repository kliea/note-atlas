"""Fixed-size character chunking for the Files pipeline (lab Part 6: `chunk_text`).

As in the lab, the document's pages are concatenated and cut every `chunk_size` characters.
An offset → page map records the page each chunk starts on. Whitespace-only chunks are
dropped; `idx` counts the chunks that are kept.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass

from app.files.extract import PageText


@dataclass(frozen=True)
class Chunk:
    idx: int
    text: str
    page_start: int
    char_start: int


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 0) -> list[tuple[int, str]]:
    """(char_start, text) windows of `chunk_size`, each starting `chunk_size - overlap` after the last."""
    if chunk_size < 1:
        raise ValueError("chunk_size must be at least 1")
    if not 0 <= overlap < chunk_size:
        raise ValueError("overlap must be at least 0 and smaller than chunk_size")
    step = chunk_size - overlap
    windows: list[tuple[int, str]] = []
    for start in range(0, len(text), step):
        windows.append((start, text[start : start + chunk_size]))
        if start + chunk_size >= len(text):
            break
    return windows


def chunk_pages(pages: list[PageText], chunk_size: int = 500, overlap: int = 0) -> list[Chunk]:
    page_starts: list[int] = []
    offset = 0
    for page in pages:
        page_starts.append(offset)
        offset += len(page.text)
    text = "".join(page.text for page in pages)

    chunks: list[Chunk] = []
    for start, window in chunk_text(text, chunk_size, overlap):
        if not window.strip():
            continue
        # An empty page shares its offset with the next page; bisect_right picks the later one.
        page_no = pages[bisect_right(page_starts, start) - 1].page_no
        chunks.append(Chunk(idx=len(chunks), text=window, page_start=page_no, char_start=start))
    return chunks
