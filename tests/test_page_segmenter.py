"""Tests for modules.page_segmenter using synthetic PDFs."""
from __future__ import annotations

import io
import tempfile
from types import SimpleNamespace

import pdfplumber
import pytest
from fpdf import FPDF
from pdfplumber.pdf import PDF

from modules.page_segmenter import (
    PageClip,
    QuestionRegion,
    _Boundary,
    _BoundaryKind,
    _build_char_mapping,
    _build_regions,
    _detect_format,
    _extract_boundaries,
    _load_pages,
    _match_boundaries,
    segment_questions,
    validate_regions,
)


def _make_pdf_bytes(
    pages: list[list[tuple[float, float, str]]],
    width: float = 612,
    height: float = 792,
) -> bytes:
    """Like _make_doc but returns raw PDF bytes (each page: (x, y, text) spans)."""
    pdf = FPDF(unit="pt", format=(width, height))
    pdf.set_auto_page_break(auto=False)
    for spans in pages:
        pdf.add_page()
        pdf.set_font("Helvetica", size=10.8)
        for x, y, text in spans:
            pdf.text(x, y, text)
    return bytes(pdf.output())

# ── Helpers ────────────────────────────────────────────────────────

def _make_doc(
    pages: list[list[tuple[float, float, str]]],
    width: float = 612,
    height: float = 792,
) -> PDF:
    """Create a synthetic PDF with text at specific positions.

    Each page is a list of (x, y, text) tuples where y is the baseline.
    Returns an opened pdfplumber PDF (caller must close).
    """
    pdf = FPDF(unit="pt", format=(width, height))
    pdf.set_auto_page_break(auto=False)
    for spans in pages:
        pdf.add_page()
        pdf.set_font("Helvetica", size=10.8)
        for x, y, text in spans:
            pdf.text(x, y, text)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        pdf.output(tmp.name)
    return pdfplumber.open(tmp.name)


def _make_cie_page(
    main_q: str | None = None,
    subs: list[tuple[float, str]] | None = None,
    extra: list[tuple[float, float, str]] | None = None,
    width: float = 612,
) -> list[tuple[float, float, str]]:
    """Build a CIE-like page with spans at correct positions.

    Args:
        main_q: If set, place a 2-char main question span at (72.4, 53).
        subs: list of (y, sub_label) to place sub-question markers.
              sub_label should start with chr(0xa8) for detection.
        extra: additional (x, y, text) spans.
    """
    spans = []
    if main_q is not None:
        spans.append((72.4, 53.0, main_q))

    if subs:
        for y, label in subs:
            spans.append((72.4, y, "}"))
            spans.append((93.7, y, label))

    if extra:
        spans.extend(extra)

    spans.append((72.4, 746.0, "footer text here"))
    return spans


def _sub_label(letter: str) -> str:
    """Create a garbled sub-question label starting with 0xa8."""
    return chr(0xA8) + letter + chr(0xAA) + " text"


# ── Tests: pdfminer neutral loader ────────────────────────────────

class TestLoadPages:
    def test_words_match_pdfplumber_geometry(self) -> None:
        pdf_bytes = _make_pdf_bytes(
            [[(72.4, 100.0, "Hello"), (300.0, 100.0, "World")]]
        )

        seg_pages = _load_pages(pdf_bytes)
        assert len(seg_pages) == 1
        assert abs(seg_pages[0].width - 612) < 1
        seg_words = {
            w.text: (round(w.x0, 1), round(w.top, 1)) for w in seg_pages[0].words
        }

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pp:
            pp_words = {
                w["text"]: (round(w["x0"], 1), round(w["top"], 1))
                for w in pp.pages[0].extract_words()
            }

        # Same words, same x0/top (within 1pt) as pdfplumber.
        for text, (x0, top) in pp_words.items():
            assert text in seg_words, f"missing word {text!r}: {seg_words}"
            assert abs(seg_words[text][0] - x0) <= 1.0
            assert abs(seg_words[text][1] - top) <= 1.0

    def test_has_curves_false_for_text_only(self) -> None:
        pages = _load_pages(_make_pdf_bytes([[(72.4, 100.0, "text")]]))
        assert pages[0].has_curves is False


# ── Tests: boundary detection ─────────────────────────────────────

class TestExtractBoundaries:
    def test_len1_char_map_collision_prefers_sub_over_main(self) -> None:
        """A 1-char left-margin marker whose byte happens to decode to a
        digit via the page-number char map must still be classified as SUB
        when it has a genuine bracket-pair companion at sub_q_x — a
        char-map collision is not proof the span is a MAIN question number.
        """
        page0 = [(306.0, 30.0, "}")]
        page1 = [
            (306.0, 30.0, "~"),
            (72.4, 200.0, "}"),
            (93.7, 200.0, _sub_label("a")),
        ]
        page2 = [
            (306.0, 30.0, "!"),
            (72.4, 400.0, "}"),
            (93.7, 400.0, _sub_label("b")),
        ]
        pdf = _make_doc([page0, page1, page2])
        boundaries = _extract_boundaries(pdf, skip_pages=set())

        mains = [b for b in boundaries if b.kind == _BoundaryKind.MAIN]
        subs = [b for b in boundaries if b.kind == _BoundaryKind.SUB]
        assert len(mains) == 0
        assert len(subs) == 2
        pdf.close()

    def test_detect_main_question(self) -> None:
        page_spans = _make_cie_page(main_q="Q1")
        pdf = _make_doc([page_spans])
        boundaries = _extract_boundaries(pdf, skip_pages=set())

        mains = [b for b in boundaries if b.kind == _BoundaryKind.MAIN]
        assert len(mains) == 1
        assert mains[0].page_idx == 0
        pdf.close()

    def test_detect_sub_question(self) -> None:
        page_spans = _make_cie_page(
            main_q="Q1",
            subs=[(100.0, _sub_label("a")), (350.0, _sub_label("b"))],
        )
        pdf = _make_doc([page_spans])
        boundaries = _extract_boundaries(pdf, skip_pages=set())

        subs = [b for b in boundaries if b.kind == _BoundaryKind.SUB]
        assert len(subs) == 2
        assert subs[0].y == pytest.approx(100.0, abs=15)
        assert subs[1].y == pytest.approx(350.0, abs=15)
        pdf.close()

    def test_context_line_ignored(self) -> None:
        """A len=1 span at x=72.4 without a \\xa8 companion is not a SUB."""
        page_spans = _make_cie_page(
            main_q="Q1",
            extra=[
                (72.4, 200.0, "}"),
                (93.7, 200.0, "some context text"),
            ],
        )
        pdf = _make_doc([page_spans])
        boundaries = _extract_boundaries(pdf, skip_pages=set())

        subs = [b for b in boundaries if b.kind == _BoundaryKind.SUB]
        assert len(subs) == 0
        pdf.close()

    def test_footer_excluded(self) -> None:
        page_spans = [
            (72.4, 53.0, "Q1"),
            (72.4, 755.0, "XX"),
        ]
        pdf = _make_doc([page_spans])
        boundaries = _extract_boundaries(pdf, skip_pages=set())

        assert len(boundaries) == 1
        assert boundaries[0].y == pytest.approx(53.0, abs=15)
        pdf.close()

    def test_skip_pages(self) -> None:
        page0 = _make_cie_page(main_q="Q0")
        page1 = _make_cie_page(main_q="Q1")
        pdf = _make_doc([page0, page1])
        boundaries = _extract_boundaries(pdf, skip_pages={0})

        assert len(boundaries) == 1
        assert boundaries[0].page_idx == 1
        pdf.close()

    def test_no_text_page(self) -> None:
        """A page with no text spans yields no boundaries."""
        pdf = _make_doc([[]])
        boundaries = _extract_boundaries(pdf, skip_pages=set())
        assert boundaries == []
        pdf.close()


class TestBuildCharMapping:
    def test_catches_page_number_with_tall_header(self) -> None:
        """The original motivating case: a page-number span whose bbox top
        sits at y~=46 (a taller-than-usual header) must still be captured."""
        page0 = [(306.0, 57.6, "A")]
        page1 = [(306.0, 30.0, "B")]
        page2 = [(306.0, 30.0, "C")]
        pdf = _make_doc([page0, page1, page2])
        mapping = _build_char_mapping(pdf)
        pdf.close()

        assert mapping is not None
        assert mapping[ord("A")] == "1"

    def test_ignores_near_center_text_below_the_header_band(self) -> None:
        """A near-center span whose bbox top sits at y~=55 (clearly past the
        header band, before the widened threshold existed this would already
        be page-content) must NOT be treated as a page-number candidate, even
        if its length coincidentally matches the expected digit count."""
        page0 = [(306.0, 30.0, "A")]
        page1 = [(306.0, 30.0, "B")]
        page2 = [(306.0, 66.6, "X")]
        page3 = [(306.0, 30.0, "C")]
        pdf = _make_doc([page0, page1, page2, page3])
        mapping = _build_char_mapping(pdf)
        pdf.close()

        assert mapping is not None
        assert ord("X") not in mapping


# ── Tests: matching ───────────────────────────────────────────────

class TestMatchBoundaries:
    def test_main_with_subs(self) -> None:
        boundaries = [
            _Boundary(kind=_BoundaryKind.MAIN, page_idx=0, y=50),
            _Boundary(kind=_BoundaryKind.SUB, page_idx=0, y=90),
            _Boundary(kind=_BoundaryKind.SUB, page_idx=0, y=350),
        ]
        question_ids = ["Q1a", "Q1b"]
        matches = _match_boundaries(boundaries, question_ids)

        assert len(matches) == 2
        assert matches[0] == ("Q1a", 0, 90)
        assert matches[1] == ("Q1b", 0, 350)

    def test_standalone_question(self) -> None:
        boundaries = [
            _Boundary(kind=_BoundaryKind.MAIN, page_idx=0, y=50),
            _Boundary(kind=_BoundaryKind.MAIN, page_idx=1, y=50),
        ]
        question_ids = ["Q1", "Q2"]
        matches = _match_boundaries(boundaries, question_ids)

        assert len(matches) == 2
        assert matches[0] == ("Q1", 0, 50)
        assert matches[1] == ("Q2", 1, 50)

    def test_mixed_standalone_and_subs(self) -> None:
        boundaries = [
            _Boundary(kind=_BoundaryKind.MAIN, page_idx=0, y=50),
            _Boundary(kind=_BoundaryKind.SUB, page_idx=0, y=90),
            _Boundary(kind=_BoundaryKind.SUB, page_idx=0, y=350),
            _Boundary(kind=_BoundaryKind.MAIN, page_idx=1, y=50),
        ]
        question_ids = ["Q1a", "Q1b", "Q2"]
        matches = _match_boundaries(boundaries, question_ids)

        assert len(matches) == 3
        assert matches[0][0] == "Q1a"
        assert matches[1][0] == "Q1b"
        assert matches[2][0] == "Q2"

    def test_partial_match(self) -> None:
        """More question_ids than boundaries → partial match."""
        boundaries = [
            _Boundary(kind=_BoundaryKind.MAIN, page_idx=0, y=50),
        ]
        question_ids = ["Q1", "Q2", "Q3"]
        matches = _match_boundaries(boundaries, question_ids)

        assert len(matches) == 1
        assert matches[0][0] == "Q1"

    def test_empty_inputs(self) -> None:
        assert _match_boundaries([], ["Q1"]) == []
        assert _match_boundaries(
            [_Boundary(kind=_BoundaryKind.MAIN, page_idx=0, y=50)], []
        ) == []


# ── Tests: region building ────────────────────────────────────────

class TestBuildRegions:
    def test_single_page_two_questions(self) -> None:
        matches = [("Q1a", 0, 50.0), ("Q1b", 0, 400.0)]
        regions = _build_regions(matches, page_count=1, footer_y=740.0, top_margin=45.0)

        assert len(regions) == 2
        assert regions[0].question_id == "Q1a"
        assert len(regions[0].clips) == 1
        assert regions[0].clips[0].y_top == 50.0
        assert regions[0].clips[0].y_bottom == 400.0

        assert regions[1].question_id == "Q1b"
        assert regions[1].clips[0].y_top == 400.0
        assert regions[1].clips[0].y_bottom == 740.0

    def test_cross_page_region(self) -> None:
        matches = [("Q1b", 0, 500.0), ("Q2", 2, 200.0)]
        regions = _build_regions(matches, page_count=3, footer_y=740.0, top_margin=45.0)

        q1b = regions[0]
        assert q1b.question_id == "Q1b"
        assert len(q1b.clips) == 3
        assert q1b.clips[0] == PageClip(page_idx=0, y_top=500.0, y_bottom=740.0)
        assert q1b.clips[1] == PageClip(page_idx=1, y_top=45.0, y_bottom=740.0)
        assert q1b.clips[2] == PageClip(page_idx=2, y_top=45.0, y_bottom=200.0)

    def test_empty_matches(self) -> None:
        regions = _build_regions([], page_count=1, footer_y=740.0, top_margin=45.0)
        assert regions == []


# ── Tests: format detection ───────────────────────────────────────

class TestDetectFormat:
    def test_letter(self) -> None:
        assert _detect_format(SimpleNamespace(width=612)) == "letter"  # type: ignore[arg-type]

    def test_a4(self) -> None:
        assert _detect_format(SimpleNamespace(width=595)) == "a4"  # type: ignore[arg-type]

    def test_unknown_defaults_to_letter(self) -> None:
        assert _detect_format(SimpleNamespace(width=500)) == "letter"  # type: ignore[arg-type]


# ── Tests: validate_regions ───────────────────────────────────────

class TestValidateRegions:
    def test_all_matched(self) -> None:
        regions = [
            QuestionRegion(question_id="Q1a", clips=[]),
            QuestionRegion(question_id="Q1b", clips=[]),
        ]
        matched, unmatched = validate_regions(regions, ["Q1a", "Q1b"])
        assert matched == ["Q1a", "Q1b"]
        assert unmatched == []

    def test_partial_match(self) -> None:
        regions = [QuestionRegion(question_id="Q1a", clips=[])]
        matched, unmatched = validate_regions(regions, ["Q1a", "Q1b", "Q2"])
        assert matched == ["Q1a"]
        assert unmatched == ["Q1b", "Q2"]


# ── Tests: full pipeline ──────────────────────────────────────────

class TestSegmentQuestions:
    def test_full_pipeline(self) -> None:
        """Multi-page synthetic PDF with CIE-like layout."""
        page0 = _make_cie_page(
            main_q="Q1",
            subs=[(90.0, _sub_label("a")), (400.0, _sub_label("b"))],
        )
        page1 = _make_cie_page(
            main_q="Q2",
        )
        pdf = _make_doc([page0, page1])

        regions = segment_questions(pdf, ["Q1a", "Q1b", "Q2"], skip_pages=set())
        pdf.close()

        assert len(regions) == 3
        assert regions[0].question_id == "Q1a"
        assert regions[1].question_id == "Q1b"
        assert regions[2].question_id == "Q2"

    def test_default_skips_first_page(self) -> None:
        page0 = _make_cie_page(main_q="XX")
        page1 = _make_cie_page(main_q="Q1")
        pdf = _make_doc([page0, page1])

        regions = segment_questions(pdf, ["Q1"])
        pdf.close()

        assert len(regions) == 1
        assert regions[0].clips[0].page_idx == 1

    def test_empty_page_returns_empty(self) -> None:
        pdf = _make_doc([[]])
        regions = segment_questions(pdf, ["Q1", "Q2"], skip_pages=set())
        pdf.close()
        assert regions == []
