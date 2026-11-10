"""Pull a Paper's framework figure and results figure out of its PDF.

A caption is a line like "FIGURE 1. Architecture of the proposed system."
The graphic is the image sitting just above that caption. Header logos are
too far from any caption to be picked. One figure is kept for the theoretical
and conceptual framework (architecture or framework diagram first, then a flow),
and one for the results (a comparison first, then a performance chart).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pymupdf

_CAPTION = re.compile(r"FIGURE\s+(\d+)\.\s*(.+)", re.IGNORECASE)
_FRAMEWORK = re.compile(
    r"architectur|conceptual|theoret|framework|flow diagram|proposed system",
    re.IGNORECASE,
)
_RESULTS = re.compile(
    r"result|precision|recall|\bf1\b|performance|compar|heat\s*map|metric|accuracy",
    re.IGNORECASE,
)
# Caption sits a few points under its graphic. Farther than this is a different block.
_MAX_GAP = 36.0


@dataclass(frozen=True)
class PaperFigure:
    number: int
    caption: str
    png: bytes


def extract_figures(pdf_bytes: bytes) -> tuple[PaperFigure | None, PaperFigure | None]:
    """(framework figure, results figure). Either is None when the PDF has no match."""
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        found = [item for page in doc for item in _page_figures(page)]
    return _choose(found, _FRAMEWORK, _framework_rank), _choose(found, _RESULTS, _results_rank)


def _page_figures(page: pymupdf.Page) -> list[PaperFigure]:
    blocks = page.get_text("dict")["blocks"]
    images = [pymupdf.Rect(block["bbox"]) for block in blocks if block.get("type") == 1]
    figures: list[PaperFigure] = []
    for block in blocks:
        if block.get("type") != 0:
            continue
        match = _CAPTION.search(_block_text(block))
        if match is None:
            continue
        caption_box = pymupdf.Rect(block["bbox"])
        graphic = _graphic_above(images, caption_box)
        if graphic is None:
            continue
        number = int(match.group(1))
        caption = f"FIGURE {number}. {match.group(2).strip()}"
        clip = pymupdf.Rect(graphic.x0 - 2, graphic.y0 - 2, graphic.x1 + 2, graphic.y1 + 2)
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), clip=clip, alpha=False)
        figures.append(PaperFigure(number=number, caption=caption, png=pixmap.tobytes("png")))
    return figures


def _graphic_above(images: list[pymupdf.Rect], caption: pymupdf.Rect) -> pymupdf.Rect | None:
    candidates: list[tuple[float, pymupdf.Rect]] = []
    for image in images:
        gap = caption.y0 - image.y1
        overlap = min(image.x1, caption.x1) - max(image.x0, caption.x0)
        if -2 <= gap <= _MAX_GAP and overlap > 12 and image.height > 40 and image.width > 40:
            candidates.append((gap, image))
    if not candidates:
        return None
    return min(candidates, key=lambda item: item[0])[1]


def _block_text(block: dict) -> str:
    parts = [
        span.get("text", "")
        for line in block.get("lines", [])
        for span in line.get("spans", [])
    ]
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def _choose(figures: list[PaperFigure], pattern: re.Pattern[str], rank) -> PaperFigure | None:
    matches = [figure for figure in figures if pattern.search(figure.caption)]
    if not matches:
        return None
    return min(matches, key=lambda figure: (rank(figure.caption), figure.number))


def _framework_rank(caption: str) -> int:
    text = caption.lower()
    if any(word in text for word in ("architectur", "framework", "conceptual", "theoret")):
        return 0
    if "proposed system" in text:
        return 1
    return 2


def _results_rank(caption: str) -> int:
    text = caption.lower()
    if "compar" in text:
        return 0
    if "heat" in text:
        return 1
    return 2
