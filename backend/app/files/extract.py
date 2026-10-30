"""Text extraction for the Files pipeline (lab Part 6: `extract_text`).

PDFs go through PyMuPDF page by page (`page.get_text()`, as the lab does with `fitz`, which is
PyMuPDF's old import name). A .txt file is one page.

A Word .docx (enhancement 1) is also one page: Word has no fixed pagination to recover, so
rather than invent page numbers, every chunk of a .docx reports p.1. Paragraphs and table rows
are read in document order; each table row becomes its cells joined by " | ".
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf

from app.files.repo import MIME_DOCX, MIME_PDF, text_encoding


@dataclass(frozen=True)
class PageText:
    page_no: int  # 1-based
    text: str


class ExtractionError(Exception):
    """The file has no text we can read; the message is shown to the user."""


def extract_text(path: Path, mime: str) -> list[PageText]:
    encoding = text_encoding(mime)
    if mime == MIME_PDF:
        pages = _extract_pdf(path)
    elif encoding is not None:
        # utf-8-sig also drops a leading byte-order mark, which Notepad adds.
        codec = "utf-8-sig" if encoding == "utf-8" else encoding
        pages = [PageText(page_no=1, text=path.read_bytes().decode(codec))]
    elif mime == MIME_DOCX:
        pages = [PageText(page_no=1, text=_extract_docx(path))]
    else:
        raise ExtractionError(f"unsupported file type {mime}")
    if not any(page.text.strip() for page in pages):
        if mime == MIME_PDF:
            raise ExtractionError(
                "no extractable text: this looks like a scanned or image-only PDF (OCR is not supported)"
            )
        raise ExtractionError("the file contains no text")
    return pages


def _extract_pdf(path: Path) -> list[PageText]:
    try:
        doc = pymupdf.open(path)
    except Exception as exc:  # noqa: BLE001 — PyMuPDF raises several types for a damaged file
        raise ExtractionError(f"could not open the PDF: {exc}") from exc
    try:
        if doc.needs_pass:
            raise ExtractionError("the PDF is password-protected")
        return [PageText(page_no=index + 1, text=page.get_text()) for index, page in enumerate(doc)]
    finally:
        doc.close()


def _extract_docx(path: Path) -> str:
    import docx
    from docx.table import Table

    try:
        document = docx.Document(str(path))
    except Exception as exc:  # noqa: BLE001
        raise ExtractionError(f"could not open the Word document: {exc}") from exc
    lines: list[str] = []
    for block in document.iter_inner_content():
        if isinstance(block, Table):
            for row in block.rows:
                cells: list[str] = []
                for cell in row.cells:
                    text = cell.text.strip()
                    # A merged cell repeats across the columns it spans; keep it once.
                    if text and (not cells or cells[-1] != text):
                        cells.append(text)
                if cells:
                    lines.append(" | ".join(cells))
        elif block.text.strip():
            lines.append(block.text)
    return "\n".join(lines)
