"""Unified PDF rendering, backed by the native pdfrx Flet extension.

pdfrx renders natively on every platform, so this is the single rendering path
in the app — nothing here goes through pdfplumber, which is a dev-only dep.

**The native side is handed a path, never the PDF's bytes.** Python and Dart
are two sides of one process, so the file it needs is already on disk where it
can reach it. A bytes-based call ships the whole document over the Flet RPC,
which stalls the transport on a large answer export — a 35MB GoodNotes scan
hangs forever with no result. A path keeps the payload constant-size whatever
the document weighs.

The extension's `PdfRenderer` service is async and lives on the flet page;
`NativeRenderer` bridges it to the synchronous, background-thread grading loop
via `run_coroutine_threadsafe` against the page's event loop. The pure helpers
(`to_pdf_bytes`, `full_page_clips`) are app-independent and unit-tested.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, cast

from modules.marking.page_segmenter import PageClip, _load_pages

if TYPE_CHECKING:
    from asyncio import AbstractEventLoop
    from collections.abc import Iterator

    from flet_pdf_render import PdfRenderer

_log = logging.getLogger("cie_helper.renderer")

# Upper bound on a single question's native render. Without it, a stalled RPC
# left future.result() blocking forever, hanging the whole grading run with no
# error — the "grading never returns" symptom on a 35MB scan. Path-based
# rendering removed the payload that caused that stall, but the guard stays:
# it converts any future hang into a message the grading loop can show.
_RENDER_TIMEOUT_S = 120.0


def to_pdf_bytes(source: str | bytes | Path) -> bytes:
    """Normalize a PDF source (raw bytes or a filesystem path) to bytes."""
    if isinstance(source, bytes):
        return source
    return Path(source).read_bytes()


def page_count(source: str | bytes | Path) -> int:
    """Number of pages in the PDF (via pdfminer, not pdfplumber)."""
    return len(_load_pages(to_pdf_bytes(source)))


@contextmanager
def _as_local_path(source: str | bytes | Path) -> Iterator[str]:
    """Yield a filesystem path for *source*, spilling raw bytes to a temp file.

    Callers hold a path in every production flow (the answer paper and the
    mark scheme both come from a file picker or the PDF store), so the spill
    is a compatibility shim for callers that only have bytes — tests, mostly.
    Keeping it means `render_regions` accepts the same argument types it
    always did.

    An unreadable path is rejected *here*, before the RPC. pdfrx reports a
    file it cannot open as ``PdfException: No password supplied by
    PasswordProvider`` — FPDF_LoadDocument returns null for a missing file
    exactly as it does for an encrypted one, and pdfrx can't tell them apart.
    Surfacing that to the user would send them hunting for a password on a
    document that simply isn't there.
    """
    if not isinstance(source, bytes):
        path = Path(source)
        if not path.is_file():
            raise FileNotFoundError(f"PDF 不存在或不可读：{path}")
        yield str(path)
        return

    fd, tmp = tempfile.mkstemp(suffix=".pdf", prefix="cie_render_")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(source)
        yield tmp
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp)


def full_page_clips(source: str | bytes | Path) -> list[PageClip]:
    """One full-page clip per page (page sizes read via pdfminer)."""
    pages = _load_pages(to_pdf_bytes(source))
    return [
        PageClip(page_idx=i, y_top=0.0, y_bottom=p.height)
        for i, p in enumerate(pages)
    ]


#: A slice thinner than this rasterizes to nothing useful, and asking PDFium
#: for it raises ("Crop exceeds page dimensions" when the two insets meet).
_MIN_SLICE_PT = 1.0


class LocalRenderer:
    """Sync, in-process renderer backed by pypdfium2 — no RPC, no event loop.

    Same PDFium engine the native path reaches through Dart, so the pixels
    match; it just runs on this side of the process. That makes it the whole
    dependency of a grading run on the UI stack: construct one and
    :func:`grade_paper` needs nothing else from the app.

    **The clip is applied before rasterizing, not after.** ``render``'s ``crop``
    takes an inset in points from each edge — verified against a banded page:
    an 800pt page with ``crop=(0, 400, 0, 200)`` returns exactly the 200pt band
    starting 200pt down. Rendering the full page and cropping the bitmap would
    instead hold a whole page of pixels per clip, which on a large scan is the
    memory the RPC-era workaround used to spend.

    pypdfium2 and pillow are imported lazily because this module is also
    imported by the Flet app, whose bundle does not carry them.
    """

    def render_regions(
        self,
        source: str | bytes | Path,
        clips: list[PageClip],
        dpi: int = 200,
    ) -> list[bytes]:
        """Render each clip (full-width vertical slice) to a PNG.

        Degenerate clips are dropped rather than returned as broken images:
        callers hand the whole list to the grader without pairing it back up
        with `clips`, so a short list is safe and a zero-height PNG is not.
        """
        if not clips:
            return []

        import io

        import pypdfium2 as pdfium

        if not isinstance(source, bytes) and not Path(source).is_file():
            raise FileNotFoundError(f"PDF 不存在或不可读：{source}")

        scale = dpi / 72.0
        out: list[bytes] = []
        doc = pdfium.PdfDocument(source)
        try:
            for clip in clips:
                page = doc[clip.page_idx]
                _, height = page.get_size()
                # Clamp into the page: a region running past the bottom edge
                # would otherwise become a negative inset, which PDFium honours
                # by rendering *outside* the page.
                top = min(max(clip.y_top, 0.0), height)
                bottom = min(max(clip.y_bottom, 0.0), height)
                if bottom - top < _MIN_SLICE_PT:
                    continue
                bitmap = page.render(
                    scale=scale, crop=(0, height - bottom, 0, top),
                )
                buf = io.BytesIO()
                bitmap.to_pil().save(buf, format="PNG")
                out.append(buf.getvalue())
        finally:
            doc.close()

        _log.info("render_regions(local): %d image(s) from %d clip(s)",
                  len(out), len(clips))
        return out

    def render_pages(
        self,
        source: str | bytes | Path,
        page_numbers: list[int],
        dpi: int = 200,
    ) -> list[bytes]:
        """Render whole pages (1-indexed page numbers) to PNGs."""
        all_clips = full_page_clips(source)
        selected = [all_clips[n - 1] for n in page_numbers]
        return self.render_regions(source, selected, dpi)


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
        if not clips:
            return []

        from flet_pdf_render import RenderClip

        rclips = [
            RenderClip(page=c.page_idx, y_top=c.y_top, y_bottom=c.y_bottom)
            for c in clips
        ]
        pages = sorted({c.page_idx + 1 for c in clips})

        with _as_local_path(source) as pdf_path:
            _log.info(
                "render_regions: %d clip(s) on page(s) %s, dpi=%d",
                len(clips), pages, dpi,
            )
            coro = self._service.render_regions(pdf_path, rclips, dpi)
            future = asyncio.run_coroutine_threadsafe(coro, self._loop)
            try:
                result = cast("list[bytes]", future.result(
                    timeout=_RENDER_TIMEOUT_S,
                ))
            except TimeoutError:
                future.cancel()
                raise TimeoutError(
                    f"原生渲染超时（>{_RENDER_TIMEOUT_S:.0f}s）："
                    f"第 {pages} 页。可能是答卷 PDF 过大/扫描件，"
                    "请换用更小的答卷或降低 DPI。"
                ) from None
        _log.info("render_regions: got %d image(s)", len(result))
        return result

    def render_pages(
        self,
        source: str | bytes | Path,
        page_numbers: list[int],
        dpi: int = 200,
    ) -> list[bytes]:
        """Render whole pages (1-indexed page numbers) to PNGs."""
        all_clips = full_page_clips(source)
        selected = [all_clips[n - 1] for n in page_numbers]
        return self.render_regions(source, selected, dpi)
