# modules/pdf_renderer.py
"""Shared PDF-to-PNG rendering utilities.

Used by both the mark scheme parser (full-page rendering for VL extraction)
and the grader (answer page rendering for AI grading).
"""
from __future__ import annotations

from pathlib import Path

import fitz


def render_pdf_pages(
    doc: fitz.Document,
    page_numbers: list[int],
    dpi: int = 200,
) -> list[bytes]:
    """Render specified PDF pages to PNG images.

    Args:
        doc: Opened PyMuPDF document.
        page_numbers: 1-indexed page numbers to render.
        dpi: Render resolution.

    Returns:
        List of PNG bytes, one per page.
    """
    images: list[bytes] = []
    for page_num in page_numbers:
        page = doc[page_num - 1]
        pix = page.get_pixmap(dpi=dpi)
        images.append(pix.tobytes("png"))
    return images


def render_pages_from_path(
    pdf_path: str | Path,
    start_page: int,
    dpi: int = 200,
) -> list[bytes]:
    """Open a PDF and render all pages from *start_page* onward.

    Args:
        pdf_path: Path to the PDF file.
        start_page: First page to render (1-indexed).
        dpi: Render resolution.

    Returns:
        List of PNG bytes, one per page.
    """
    doc = fitz.open(str(pdf_path))
    try:
        page_numbers = list(range(start_page, len(doc) + 1))
        return render_pdf_pages(doc, page_numbers, dpi=dpi)
    finally:
        doc.close()
