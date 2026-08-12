"""Tests for the renderer's pure helpers (source normalization + clip building).

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

from modules.marking import renderer as renderer_mod
from modules.marking.page_segmenter import PageClip
from modules.marking.renderer import (
    NativeRenderer,
    _as_local_path,
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


def test_as_local_path_passes_a_path_through_untouched() -> None:
    # A caller that already has a path must reach the native side unchanged —
    # no copy, no temp file. This is the production flow for both the answer
    # paper and the mark scheme, and the reason the RPC payload is constant.
    data = _make_pdf_bytes(1)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(data)
        path = tmp.name

    with _as_local_path(path) as p:
        assert p == path
    with _as_local_path(Path(path)) as p:
        assert Path(p) == Path(path)
    # Never deletes a caller-owned file.
    assert Path(path).exists()


def test_as_local_path_rejects_a_missing_file_with_a_clear_error() -> None:
    # pdfrx cannot distinguish "file missing" from "file encrypted" —
    # FPDF_LoadDocument returns null for both, so a bad path surfaces as
    # "PdfException: No password supplied by PasswordProvider" and sends the
    # user hunting for a password. Catch it on this side, where the real
    # cause is still known. (Observed for real: the render harness pointed at
    # a stale path and reported exactly that.)
    with (
        pytest.raises(FileNotFoundError, match="不存在或不可读"),
        _as_local_path("no/such/file.pdf"),
    ):
        pass


def test_as_local_path_spills_bytes_and_cleans_up() -> None:
    data = _make_pdf_bytes(2)
    with _as_local_path(data) as p:
        spilled = Path(p)
        assert spilled.read_bytes() == data
    # The temp file is the renderer's own; it must not outlive the call.
    assert not spilled.exists()


class _CapturingService:
    """A PdfRenderer stand-in that records what it was handed."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int]] = []

    async def render_regions(
        self, pdf_path: str, clips: list[object], dpi: int,
    ) -> list[bytes]:
        self.calls.append((pdf_path, len(clips), dpi))
        return [b"\x89PNG\r\n\x1a\n" for _ in clips]


def test_render_regions_sends_a_path_not_the_pdf_bytes() -> None:
    # The whole point of the path-based service: whatever the caller holds,
    # the RPC carries a filesystem path. Shipping bytes is what used to stall
    # the transport on a 35MB scan.
    svc = _CapturingService()
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    try:
        data = _make_pdf_bytes(2)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(data)
            path = tmp.name

        clips = [
            PageClip(page_idx=0, y_top=0.0, y_bottom=792.0),
            PageClip(page_idx=1, y_top=50.0, y_bottom=400.0),
        ]
        r = NativeRenderer(svc, loop)

        out = r.render_regions(path, clips)
        assert len(out) == 2
        assert svc.calls == [(path, 2, 200)]

        # A bytes caller still works — via a temp file, still a path.
        out = r.render_regions(data, clips)
        assert len(out) == 2
        sent, n_clips, _ = svc.calls[1]
        assert sent != path and sent.endswith(".pdf") and n_clips == 2
    finally:
        loop.call_soon_threadsafe(loop.stop)
        t.join(timeout=2)
        loop.close()


class _StallingService:
    """A PdfRenderer stand-in whose render never completes."""

    async def render_regions(
        self, pdf_path: str, clips: list[object], dpi: int,
    ) -> list[bytes]:
        await asyncio.Event().wait()  # never set → hangs forever
        return []


def test_render_regions_times_out_instead_of_hanging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A stalled native render must raise (surfacing an error the grading loop
    # can show) rather than block future.result() forever — the root cause of
    # "grading never returns" on an oversized scanned PDF. Path-based
    # rendering removed the payload that caused that stall, but the guard has
    # to keep working for any future one.
    monkeypatch.setattr(renderer_mod, "_RENDER_TIMEOUT_S", 0.3)

    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    try:
        r = NativeRenderer(_StallingService(), loop)
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
