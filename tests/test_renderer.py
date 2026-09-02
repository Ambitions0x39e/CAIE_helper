"""Tests for the renderer's pure helpers (source normalization + clip building).

The rasterizing itself is pinned by tests/test_local_renderer.py, which asserts
on returned pixels. These cover the app-independent logic around it.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fpdf import FPDF

from modules.marking.page_segmenter import PageClip
from modules.marking.renderer import (
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


def test_full_page_clips_one_per_page() -> None:
    pdf = _make_pdf_bytes(3, width=612, height=792)
    clips = full_page_clips(pdf)

    assert len(clips) == 3
    for i, c in enumerate(clips):
        assert isinstance(c, PageClip)
        assert c.page_idx == i
        assert c.y_top == 0.0
        assert abs(c.y_bottom - 792) < 1.0  # full page height in points
