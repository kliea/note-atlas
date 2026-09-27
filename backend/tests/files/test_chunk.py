"""Files F2: fixed-size character chunking (lab `chunk_text`)."""

from __future__ import annotations

import pytest

from app.files.chunk import Chunk, chunk_pages, chunk_text
from app.files.extract import PageText


def test_lab_default_cuts_every_500_characters() -> None:
    text = "a" * 500 + "b" * 500 + "c" * 123
    windows = chunk_text(text)
    assert [(start, len(chunk)) for start, chunk in windows] == [(0, 500), (500, 500), (1000, 123)]
    assert [chunk[0] for _, chunk in windows] == ["a", "b", "c"]
    assert "".join(chunk for _, chunk in windows) == text


def test_exact_multiple_has_no_empty_tail() -> None:
    assert [start for start, _ in chunk_text("x" * 1000)] == [0, 500]
    assert chunk_text("") == []


def test_overlap_steps_by_size_minus_overlap() -> None:
    text = "".join(chr(ord("a") + i % 26) for i in range(1100))
    windows = chunk_text(text, chunk_size=500, overlap=100)
    assert [(start, len(chunk)) for start, chunk in windows] == [(0, 500), (400, 500), (800, 300)]
    # Consecutive chunks share exactly `overlap` characters.
    assert windows[0][1][-100:] == windows[1][1][:100]
    assert windows[1][1][-100:] == windows[2][1][:100]


def test_overlap_does_not_emit_a_chunk_already_covered() -> None:
    assert [start for start, _ in chunk_text("x" * 900, chunk_size=500, overlap=100)] == [0, 400]


@pytest.mark.parametrize(("size", "overlap"), [(0, 0), (500, 500), (500, -1)])
def test_invalid_settings_are_rejected(size: int, overlap: int) -> None:
    with pytest.raises(ValueError):
        chunk_text("text", chunk_size=size, overlap=overlap)


def test_chunks_record_the_page_they_start_on() -> None:
    pages = [PageText(1, "a" * 700), PageText(2, "b" * 400), PageText(3, "c" * 50)]
    chunks = chunk_pages(pages)
    assert [(c.idx, c.char_start, c.page_start) for c in chunks] == [(0, 0, 1), (1, 500, 1), (2, 1000, 2)]
    # The second chunk straddles the page break: it starts on page 1, ends on page 2.
    assert chunks[1].text == "a" * 200 + "b" * 300
    assert chunks[2].text == "b" * 100 + "c" * 50


def test_page_start_on_the_boundary_is_the_new_page() -> None:
    pages = [PageText(1, "a" * 500), PageText(2, "b" * 10)]
    assert [c.page_start for c in chunk_pages(pages)] == [1, 2]


def test_empty_pages_are_skipped_in_the_page_map() -> None:
    pages = [PageText(1, "a" * 500), PageText(2, ""), PageText(3, "c" * 10)]
    assert [c.page_start for c in chunk_pages(pages)] == [1, 3]


def test_whitespace_only_chunks_are_dropped_and_idx_stays_dense() -> None:
    pages = [PageText(1, "a" * 10 + " " * 490), PageText(2, " \n" * 250), PageText(3, "z")]
    chunks = chunk_pages(pages)
    assert chunks == [
        Chunk(idx=0, text="a" * 10 + " " * 490, page_start=1, char_start=0),
        Chunk(idx=1, text="z", page_start=3, char_start=1000),
    ]
