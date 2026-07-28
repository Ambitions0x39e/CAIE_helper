"""Tests for modules.renderer pure helpers (source normalization + clip building).

The NativeRenderer's async bridge to the flet page loop needs a running app, so
it's verified at runtime (2B.3) rather than here. These tests cover the pure,
app-independent logic.
"""
from __future__ import annotations

import asyncio
import tempfile
import threading
from pathlib import Path

import pytest
from fpdf import FPDF

from modules import renderer as renderer_mod
from modules.page_segmenter import PageClip
from modules.renderer import (
    NativeRenderer,
    _extract_pages,
    full_page_clips,
    page_count,
    to_pdf_bytes,
)


def _make_pdf_bytes(n_pages: int, width: float = 612, height: float = 792) -> bytes:
    pdf = FPDF(unit="pt", format=(width, height))
    pdf.set_auto_page_break(auto=False)
    for i in range(n_pages):
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        pdf.text(72, 100, f"page {i}")
    return bytes(pdf.output())


def test_to_pdf_bytes_passthrough() -> None:
    data = b"%PDF-1.4 fake"
    assert to_pdf_bytes(data) is data


def test_to_pdf_bytes_reads_path() -> None:
    data = _make_pdf_bytes(1)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(data)
        path = tmp.name
    assert to_pdf_bytes(path) == data
    assert to_pdf_bytes(Path(path)) == data


def test_page_count() -> None:
    assert page_count(_make_pdf_bytes(4)) == 4


def test_extract_pages_subset_and_remap() -> None:
    pdf = _make_pdf_bytes(6)
    sub, remap = _extract_pages(pdf, [1, 3, 4])

    # Only the requested pages, remapped to contiguous 0-based indices.
    assert remap == {1: 0, 3: 1, 4: 2}
    assert page_count(sub) == 3


def test_extract_pages_shrinks_large_source() -> None:
    # A big page (lots of text) dwarfs the others; extracting the small pages
    # must produce a sub-PDF far smaller than the source — the whole point of
    # the optimization (don't ship a 30MB PDF over the RPC per question).
    big = FPDF(unit="pt", format=(612, 792))
    big.set_auto_page_break(auto=False)
    big.add_page()  # page 0: tiny
    big.set_font("Helvetica", size=12)
    big.text(72, 100, "small")
    big.add_page()  # page 1: heavy
    for i in range(400):
        big.text(72, 20 + (i % 700), "x" * 80)
    pdf = bytes(big.output())

    sub, remap = _extract_pages(pdf, [0])
    assert remap == {0: 0}
    assert page_count(sub) == 1
    assert len(sub) < len(pdf)


def test_local_render_produces_png_per_clip() -> None:
    # In-process rendering (pypdfium2) is the desktop path that sidesteps the
    # RPC. Each clip must yield one PNG, regardless of the native service.
    pdf = _make_pdf_bytes(2)
    clips = [
        PageClip(page_idx=0, y_top=0.0, y_bottom=792.0),
        PageClip(page_idx=1, y_top=50.0, y_bottom=400.0),
    ]
    out = NativeRenderer(None, None).render_regions(pdf, clips)  # type: ignore[arg-type]
    assert len(out) == 2
    assert all(b[:8] == b"\x89PNG\r\n\x1a\n" for b in out)


class _StallingService:
    """A PdfRenderer stand-in whose render never completes."""

    async def render_regions(
        self, pdf: bytes, clips: list, dpi: int,
    ) -> list[bytes]:
        await asyncio.Event().wait()  # never set → hangs forever
        return []


def test_render_regions_times_out_instead_of_hanging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A stalled native render must raise (surfacing an error the grading loop
    # can show) rather than block future.result() forever — the root cause of
    # "grading never returns" on an oversized scanned PDF.
    # Force the native path (as on iOS, where pypdfium2 is absent) so this
    # exercises the RPC fallback rather than the in-process renderer.
    monkeypatch.setattr(renderer_mod, "_try_local_render", lambda *a: None)
    monkeypatch.setattr(renderer_mod, "_RENDER_TIMEOUT_S", 0.3)

    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    try:
        r = NativeRenderer(_StallingService(), loop)  # type: ignore[arg-type]
        pdf = _make_pdf_bytes(2)
        clips = [PageClip(page_idx=0, y_top=0.0, y_bottom=100.0)]
        with pytest.raises(TimeoutError, match="渲染超时"):
            r.render_regions(pdf, clips)
    finally:
        # render_regions' future.cancel() only *schedules* the task
        # cancellation; the loop needs another turn to deliver CancelledError
        # into the stalled coroutine. Stopping the loop in the same batch left
        # the task pending forever, so asyncio printed "Task was destroyed but
        # it is pending!" from the GC on every run of the suite. Drain from
        # inside the loop (where all_tasks() is safe) before stopping it.
        async def _cancel_pending() -> None:
            others = [
                task for task in asyncio.all_tasks()
                if task is not asyncio.current_task()
            ]
            for task in others:
                task.cancel()
            await asyncio.gather(*others, return_exceptions=True)

        asyncio.run_coroutine_threadsafe(_cancel_pending(), loop).result(
            timeout=2,
        )
        loop.call_soon_threadsafe(loop.stop)
        t.join(timeout=2)
        loop.close()


def test_full_page_clips_one_per_page() -> None:
    pdf = _make_pdf_bytes(3, width=612, height=792)
    clips = full_page_clips(pdf)

    assert len(clips) == 3
    for i, c in enumerate(clips):
        assert isinstance(c, PageClip)
        assert c.page_idx == i
        assert c.y_top == 0.0
        assert abs(c.y_bottom - 792) < 1.0  # full page height in points
