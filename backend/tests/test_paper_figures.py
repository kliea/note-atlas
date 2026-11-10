"""Framework and results figures are the graphics sitting under their captions."""

from __future__ import annotations

import pymupdf

from app.paper_figures import extract_figures


def _png(value: int) -> bytes:
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 160, 80), 0)
    pixmap.clear_with(value)
    return pixmap.tobytes("png")


def _paper() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=576, height=900)
    # A header logo is too small, and too far from a caption, to be a figure.
    page.insert_image(pymupdf.Rect(460, 16, 530, 32), stream=_png(10))
    page.insert_image(pymupdf.Rect(70, 70, 480, 230), stream=_png(40))
    page.insert_text((70, 248), "FIGURE 2. Proposed flow diagram.", fontsize=11)
    page.insert_image(pymupdf.Rect(70, 280, 480, 460), stream=_png(80))
    page.insert_text((70, 478), "FIGURE 1. Architecture of the proposed system.", fontsize=11)
    page.insert_image(pymupdf.Rect(300, 520, 520, 640), stream=_png(140))
    page.insert_text((300, 658), "FIGURE 4. Model precision vs overall performance.", fontsize=11)
    page.insert_image(pymupdf.Rect(40, 700, 250, 820), stream=_png(200))
    page.insert_text((40, 838), "FIGURE 7. Comparative analysis.", fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


def test_architecture_beats_a_flow_and_comparison_beats_a_chart() -> None:
    framework, results = extract_figures(_paper())
    assert framework is not None and results is not None
    assert framework.caption.startswith("FIGURE 1.")
    assert "Architecture" in framework.caption
    assert framework.png.startswith(b"\x89PNG")
    assert results.caption.startswith("FIGURE 7.")
    assert "Comparative" in results.caption


def test_a_pdf_without_captions_has_no_figures() -> None:
    doc = pymupdf.open()
    doc.new_page()
    data = doc.tobytes()
    doc.close()
    assert extract_figures(data) == (None, None)
