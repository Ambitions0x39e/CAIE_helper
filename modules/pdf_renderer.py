# modules/pdf_renderer.py
"""Shared PDF-to-PNG rendering utilities.

Used by both the mark scheme parser (full-page rendering for VL extraction)
and the grader (answer page rendering for AI grading).
"""
from __future__ import annotations

import io
from pathlib import Path

import pdfplumber
from pdfplumber.page import Page
from pdfplumber.pdf import PDF


def _page_to_png(page: Page, dpi: int = 200) -> bytes:
    """Render a single pdfplumber page to PNG bytes."""
    img = page.to_image(resolution=dpi)
    buf = io.BytesIO()
    img.original.save(buf, format="PNG")
    return buf.getvalue()


def render_pdf_pages(
    pdf: PDF,
    page_numbers: list[int],
    dpi: int = 200,
) -> list[bytes]:
    """Render specified PDF pages to PNG images.

    Args:
        pdf: Opened pdfplumber PDF.
        page_numbers: 1-indexed page numbers to render.
        dpi: Render resolution.

    Returns:
        List of PNG bytes, one per page.
    """
    images: list[bytes] = []
    for page_num in page_numbers:
        page = pdf.pages[page_num - 1]
        images.append(_page_to_png(page, dpi=dpi))
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
    with pdfplumber.open(str(pdf_path)) as pdf:
        page_numbers = list(range(start_page, len(pdf.pages) + 1))
        return render_pdf_pages(pdf, page_numbers, dpi=dpi)
