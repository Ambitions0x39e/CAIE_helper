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
