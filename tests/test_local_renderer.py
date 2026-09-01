"""Tests for the in-process pypdfium2 renderer.

The point of interest is geometry. ``PageClip`` measures from the *top* of the
page, PDFium's ``crop`` takes an inset from every *edge*, and a mix-up between
the two produces a picture that looks entirely plausible — a crisp render of
the wrong part of the page. So these tests build pages out of solid colour
bands and assert on the pixels that come back.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from fpdf import FPDF
from PIL import Image

from modules.marking.page_segmenter import PageClip
from modules.marking.renderer import LocalRenderer

#: Four stacked bands, top to bottom, on a 600x800pt page.
BANDS = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
BAND_PT = 200.0
PAGE_W, PAGE_H = 600.0, 800.0


def _banded_pdf(n_pages: int = 1) -> bytes:
    pdf = FPDF(unit="pt", format=(PAGE_W, PAGE_H))
    pdf.set_auto_page_break(auto=False)
    for _ in range(n_pages):
        pdf.add_page()
        for i, (r, g, b) in enumerate(BANDS):
            pdf.set_fill_color(r, g, b)
            pdf.rect(0, i * BAND_PT, PAGE_W, BAND_PT, style="F")
    return bytes(pdf.output())


def _open(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png)).convert("RGB")


def _dominant(img: Image.Image) -> tuple[int, int, int]:
    return img.getpixel((img.width // 2, img.height // 2))  # type: ignore[return-value]


@pytest.mark.parametrize("band", range(4))
def test_clip_lands_on_the_band_it_asked_for(band: int) -> None:
    """y_top/y_bottom are measured from the top of the page, not the bottom."""
    clip = PageClip(
        page_idx=0, y_top=band * BAND_PT, y_bottom=(band + 1) * BAND_PT,
    )
    (png,) = LocalRenderer().render_regions(_banded_pdf(), [clip], dpi=72)
    assert _dominant(_open(png)) == BANDS[band]


def test_clip_dimensions_scale_with_dpi() -> None:
    clip = PageClip(page_idx=0, y_top=0.0, y_bottom=BAND_PT)
    for dpi, expected in ((72, (600, 200)), (144, (1200, 400))):
        (png,) = LocalRenderer().render_regions(_banded_pdf(), [clip], dpi=dpi)
        assert _open(png).size == expected


def test_clip_spanning_two_bands_contains_both() -> None:
    clip = PageClip(page_idx=0, y_top=0.0, y_bottom=2 * BAND_PT)
    (png,) = LocalRenderer().render_regions(_banded_pdf(), [clip], dpi=72)
    img = _open(png)
    assert img.size == (600, 400)
    assert img.getpixel((300, 100)) == BANDS[0]
    assert img.getpixel((300, 300)) == BANDS[1]


def test_each_clip_gets_its_own_image_across_pages() -> None:
    clips = [
        PageClip(page_idx=0, y_top=0.0, y_bottom=BAND_PT),
        PageClip(page_idx=1, y_top=2 * BAND_PT, y_bottom=3 * BAND_PT),
        PageClip(page_idx=0, y_top=3 * BAND_PT, y_bottom=4 * BAND_PT),
    ]
    pngs = LocalRenderer().render_regions(_banded_pdf(2), clips, dpi=72)
    assert [_dominant(_open(p)) for p in pngs] == [BANDS[0], BANDS[2], BANDS[3]]


def test_a_region_running_past_the_bottom_edge_is_clamped() -> None:
    """A negative inset makes PDFium render *outside* the page, so clamp."""
    clip = PageClip(page_idx=0, y_top=3 * BAND_PT, y_bottom=PAGE_H + 500)
    (png,) = LocalRenderer().render_regions(_banded_pdf(), [clip], dpi=72)
    img = _open(png)
    assert img.size == (600, 200)
    assert _dominant(img) == BANDS[3]


@pytest.mark.parametrize(
    "y_top,y_bottom",
    [(400.0, 400.0), (400.0, 400.5), (500.0, 100.0), (-50.0, -10.0)],
)
def test_degenerate_clips_are_dropped_not_returned_broken(
    y_top: float, y_bottom: float,
) -> None:
    """Callers pass the list straight to the grader without re-pairing it with
    the clips, so a short list is safe — a zero-height PNG is not."""
    clip = PageClip(page_idx=0, y_top=y_top, y_bottom=y_bottom)
    assert LocalRenderer().render_regions(_banded_pdf(), [clip], dpi=72) == []


def test_no_clips_renders_nothing() -> None:
    assert LocalRenderer().render_regions(_banded_pdf(), [], dpi=72) == []


def test_renders_from_a_path_as_well_as_bytes(tmp_path: Path) -> None:
    pdf = tmp_path / "banded.pdf"
    pdf.write_bytes(_banded_pdf())
    clip = PageClip(page_idx=0, y_top=0.0, y_bottom=BAND_PT)
    from_bytes = LocalRenderer().render_regions(_banded_pdf(), [clip], dpi=72)
    for source in (str(pdf), pdf):
        assert LocalRenderer().render_regions(source, [clip], dpi=72) == from_bytes


def test_missing_file_is_reported_before_pdfium_sees_it(tmp_path: Path) -> None:
    clip = PageClip(page_idx=0, y_top=0.0, y_bottom=BAND_PT)
    with pytest.raises(FileNotFoundError, match="PDF 不存在或不可读"):
        LocalRenderer().render_regions(tmp_path / "nope.pdf", [clip])


def test_render_pages_selects_whole_pages_by_1_indexed_number() -> None:
    pngs = LocalRenderer().render_pages(_banded_pdf(3), [1, 3], dpi=72)
    assert len(pngs) == 2
    for png in pngs:
        img = _open(png)
        assert img.size == (600, 800)
        # A whole page carries every band, in order.
        seen = [img.getpixel((300, int((i + 0.5) * BAND_PT))) for i in range(4)]
        assert seen == BANDS
