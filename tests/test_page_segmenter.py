"""Tests for modules.page_segmenter using synthetic PDFs."""
from __future__ import annotations

import fitz
import pytest

from modules.page_segmenter import (
    PageClip,
    QuestionRegion,
    _Boundary,
    _BoundaryKind,
    _build_regions,
    _detect_format,
    _extract_boundaries,
    _match_boundaries,
    segment_questions,
    validate_regions,
)

# ── Helpers ────────────────────────────────────────────────────────

def _make_doc(
    pages: list[list[tuple[float, float, str]]],
    width: float = 612,
    height: float = 792,
) -> fitz.Document:
    """Create a synthetic PDF with text at specific positions.

    Each page is a list of (x, y, text) tuples.
    """
    doc = fitz.open()
    for spans in pages:
        page = doc.new_page(width=width, height=height)
        for x, y, text in spans:
            page.insert_text((x, y), text, fontsize=10.8)
    return doc


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
        # Main question: 2-char span at left margin
        spans.append((72.4, 53.0, main_q))

    if subs:
        for y, label in subs:
            # 1-char marker at left margin
            spans.append((72.4, y, "}"))
            # Sub-question label at sub_q_x position
            spans.append((93.7, y, label))

    if extra:
        spans.extend(extra)

    # Footer (should be excluded)
    spans.append((72.4, 746.0, "footer text here"))
    return spans


def _sub_label(letter: str) -> str:
    """Create a garbled sub-question label starting with 0xa8."""
    return chr(0xA8) + letter + chr(0xAA) + " text"


# ── Tests: boundary detection ─────────────────────────────────────

class TestExtractBoundaries:
    def test_detect_main_question(self) -> None:
        page_spans = _make_cie_page(main_q="Q1")
        doc = _make_doc([page_spans])
        boundaries = _extract_boundaries(doc, skip_pages=set())

        mains = [b for b in boundaries if b.kind == _BoundaryKind.MAIN]
        assert len(mains) == 1
        assert mains[0].page_idx == 0
        doc.close()

    def test_detect_sub_question(self) -> None:
        page_spans = _make_cie_page(
            main_q="Q1",
            subs=[(100.0, _sub_label("a")), (350.0, _sub_label("b"))],
        )
        doc = _make_doc([page_spans])
        boundaries = _extract_boundaries(doc, skip_pages=set())

        subs = [b for b in boundaries if b.kind == _BoundaryKind.SUB]
        assert len(subs) == 2
        # insert_text y is the baseline; bbox y0 is the ascent above it
        assert subs[0].y == pytest.approx(100.0, abs=15)
        assert subs[1].y == pytest.approx(350.0, abs=15)
        doc.close()

    def test_context_line_ignored(self) -> None:
        """A len=1 span at x=72.4 without a \\xa8 companion is not a SUB."""
        page_spans = _make_cie_page(
            main_q="Q1",
            extra=[
                (72.4, 200.0, "}"),
                (93.7, 200.0, "some context text"),
            ],
        )
        doc = _make_doc([page_spans])
        boundaries = _extract_boundaries(doc, skip_pages=set())

        subs = [b for b in boundaries if b.kind == _BoundaryKind.SUB]
        assert len(subs) == 0
        doc.close()

    def test_footer_excluded(self) -> None:
        # insert_text y is baseline; bbox y0 = y - ascent (~11.6pt for size 10.8)
        # Place footer text high enough that bbox top > 740 threshold
        page_spans = [
            (72.4, 53.0, "Q1"),
            (72.4, 755.0, "XX"),
        ]
        doc = _make_doc([page_spans])
        boundaries = _extract_boundaries(doc, skip_pages=set())

        assert len(boundaries) == 1
        assert boundaries[0].y == pytest.approx(53.0, abs=15)
        doc.close()

    def test_skip_pages(self) -> None:
        page0 = _make_cie_page(main_q="Q0")
        page1 = _make_cie_page(main_q="Q1")
        doc = _make_doc([page0, page1])
        boundaries = _extract_boundaries(doc, skip_pages={0})

        assert len(boundaries) == 1
        assert boundaries[0].page_idx == 1
        doc.close()

    def test_empty_document(self) -> None:
        doc = fitz.open()
        boundaries = _extract_boundaries(doc, skip_pages=set())
        assert boundaries == []
        doc.close()

    def test_no_text_layer(self) -> None:
        """A page with only an image has no text spans."""
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        # Insert a dummy rectangle (no text)
        page.draw_rect(fitz.Rect(100, 100, 200, 200), color=(0, 0, 0))
        boundaries = _extract_boundaries(doc, skip_pages=set())
        assert boundaries == []
        doc.close()


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
        assert matches[0] == ("Q1a", 0, 50)  # uses stem Y
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
        doc = fitz.open()
        doc.new_page(width=612, height=792)

        regions = _build_regions(matches, doc, footer_y=740.0, top_margin=45.0)
        doc.close()

        assert len(regions) == 2
        assert regions[0].question_id == "Q1a"
        assert len(regions[0].clips) == 1
        assert regions[0].clips[0].y_top == 50.0
        assert regions[0].clips[0].y_bottom == 400.0

        assert regions[1].question_id == "Q1b"
        assert regions[1].clips[0].y_top == 400.0
        assert regions[1].clips[0].y_bottom == 740.0  # last → footer

    def test_cross_page_region(self) -> None:
        matches = [("Q1b", 0, 500.0), ("Q2", 2, 60.0)]
        doc = fitz.open()
        for _ in range(3):
            doc.new_page(width=612, height=792)

        regions = _build_regions(matches, doc, footer_y=740.0, top_margin=45.0)
        doc.close()

        q1b = regions[0]
        assert q1b.question_id == "Q1b"
        assert len(q1b.clips) == 3
        assert q1b.clips[0] == PageClip(page_idx=0, y_top=500.0, y_bottom=740.0)
        assert q1b.clips[1] == PageClip(page_idx=1, y_top=45.0, y_bottom=740.0)
        assert q1b.clips[2] == PageClip(page_idx=2, y_top=45.0, y_bottom=60.0)

    def test_empty_matches(self) -> None:
        doc = fitz.open()
        doc.new_page()
        regions = _build_regions([], doc, footer_y=740.0, top_margin=45.0)
        doc.close()
        assert regions == []


# ── Tests: format detection ───────────────────────────────────────

class TestDetectFormat:
    def test_letter(self) -> None:
        doc = fitz.open()
        doc.new_page(width=612, height=792)
        assert _detect_format(doc[0]) == "letter"
        doc.close()

    def test_a4(self) -> None:
        doc = fitz.open()
        doc.new_page(width=595, height=842)
        assert _detect_format(doc[0]) == "a4"
        doc.close()

    def test_unknown_defaults_to_letter(self) -> None:
        doc = fitz.open()
        doc.new_page(width=500, height=700)
        assert _detect_format(doc[0]) == "letter"
        doc.close()


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
        doc = _make_doc([page0, page1])

        regions = segment_questions(doc, ["Q1a", "Q1b", "Q2"], skip_pages=set())
        doc.close()

        assert len(regions) == 3
        assert regions[0].question_id == "Q1a"
        assert regions[1].question_id == "Q1b"
        assert regions[2].question_id == "Q2"

    def test_default_skips_first_page(self) -> None:
        page0 = _make_cie_page(main_q="XX")  # cover page
        page1 = _make_cie_page(main_q="Q1")
        doc = _make_doc([page0, page1])

        regions = segment_questions(doc, ["Q1"])
        doc.close()

        assert len(regions) == 1
        assert regions[0].clips[0].page_idx == 1

    def test_empty_doc_returns_empty(self) -> None:
        doc = fitz.open()
        regions = segment_questions(doc, ["Q1", "Q2"])
        doc.close()
        assert regions == []
