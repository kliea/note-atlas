"""Text extraction for the Files pipeline (lab Part 6: `extract_text`).

PDFs go through PyMuPDF page by page (`page.get_text()`, as the lab does with `fitz`, which is
PyMuPDF's old import name). A .txt file is one page.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf

from app.files.repo import MIME_PDF, MIME_TEXT


@dataclass(frozen=True)
class PageText:
    page_no: int  # 1-based
    text: str


class ExtractionError(Exception):
    """The file has no text we can read; the message is shown to the user."""


def extract_text(path: Path, mime: str) -> list[PageText]:
    if mime == MIME_PDF:
        pages = _extract_pdf(path)
    elif mime == MIME_TEXT:
        pages = [PageText(page_no=1, text=path.read_text(encoding="utf-8"))]
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
