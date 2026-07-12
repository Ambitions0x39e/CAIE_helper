"""Unified PDF rendering, backed by the native pdfrx Flet extension.

Replaces the pdfplumber-based rendering (`render_question_regions`,
`render_pages`, `render_pdf_pages`) so the Mark tab works on iOS. pdfrx renders
natively on every platform, so this is the single rendering path everywhere.

The extension's `PdfRenderer` service is async and lives on the flet page;
`NativeRenderer` bridges it to the synchronous, background-thread grading loop
via `run_coroutine_threadsafe` against the page's event loop. The pure helpers
(`to_pdf_bytes`, `full_page_clips`) are app-independent and unit-tested.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, cast

from modules.page_segmenter import PageClip, _load_pages

if TYPE_CHECKING:
    from asyncio import AbstractEventLoop

    from flet_pdf_render import PdfRenderer


def to_pdf_bytes(source: str | bytes | Path) -> bytes:
    """Normalize a PDF source (raw bytes or a filesystem path) to bytes."""
    if isinstance(source, bytes):
        return source
    return Path(source).read_bytes()


def page_count(source: str | bytes | Path) -> int:
    """Number of pages in the PDF (via pdfminer — iOS-safe, no pdfplumber)."""
    return len(_load_pages(to_pdf_bytes(source)))


def full_page_clips(source: str | bytes | Path) -> list[PageClip]:
    """One full-page clip per page (page sizes read via pdfminer — iOS-safe)."""
    pages = _load_pages(to_pdf_bytes(source))
    return [
        PageClip(page_idx=i, y_top=0.0, y_bottom=p.height)
        for i, p in enumerate(pages)
    ]


class NativeRenderer:
    """Sync-callable renderer bridging to the async pdfrx `PdfRenderer` service.

    Construct once per grading run with the page's `PdfRenderer` service and the
    page's event loop, then call from any (background) thread.
    """

    def __init__(self, service: PdfRenderer, loop: AbstractEventLoop) -> None:
        self._service = service
        self._loop = loop

    def render_regions(
        self,
        source: str | bytes | Path,
        clips: list[PageClip],
        dpi: int = 200,
    ) -> list[bytes]:
        """Render each clip (full-width vertical slice) to a PNG."""
        from flet_pdf_render import RenderClip

        pdf = to_pdf_bytes(source)
        rclips = [
            RenderClip(page=c.page_idx, y_top=c.y_top, y_bottom=c.y_bottom)
            for c in clips
        ]
        coro = self._service.render_regions(pdf, rclips, dpi)
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return cast("list[bytes]", future.result())

    def render_pages(
        self,
        source: str | bytes | Path,
        page_numbers: list[int],
        dpi: int = 200,
    ) -> list[bytes]:
        """Render whole pages (1-indexed page numbers) to PNGs."""
        pdf = to_pdf_bytes(source)
        all_clips = full_page_clips(pdf)
        selected = [all_clips[n - 1] for n in page_numbers]
        return self.render_regions(pdf, selected, dpi)
