"""Tests for modules.marking.page_segmenter using synthetic PDFs."""
from __future__ import annotations

import io
from types import SimpleNamespace

import pdfplumber
import pytest
from fpdf import FPDF

from modules.marking.page_segmenter import (
    _CLIP_TOP_PAD,
    PageClip,
    QuestionRegion,
    _accepted_garbled_subs,
    _accepted_garbled_subsubs,
    _Boundary,
    _BoundaryKind,
    _build_char_mapping,
    _build_regions,
    _detect_format,
    _extract_boundaries,
    _is_cid_encoded,
    _load_pages,
    _match_boundaries,
    _SegPage,
    _SegWord,
    _snap_to_line_top,
    match_scanned,
    scan_document,
    segment_questions_report,
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
) -> list[_SegPage]:
    """Create a synthetic PDF and load it into the neutral page model.

    Each page is a list of (x, y, text) tuples where y is the baseline.
    Returns list[_SegPage] (pdfminer.six-backed) — no resource to close.
    """
    return _load_pages(_make_pdf_bytes(pages, width, height))


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


def _readable_sub_label(letter: str) -> str:
    """A sub-question marker as a READABLE paper prints it: "(a)"."""
    return f"({letter})"


# ── Helpers: genuinely CID-encoded (garbled) pages ─────────────────
#
# FPDF can only emit readable text, so a garbled paper cannot be built
# through _make_doc. These construct the neutral page model directly.
# Bracket glyphs are (113, 114) — the low-byte pair 9701 chemistry uses,
# which a magnitude-based gate would wrongly reject.

_OPEN_CP, _CLOSE_CP = 113, 114


def _cid(cps: list[int]) -> str:
    """Render code points the way pdfminer renders a CID-encoded word."""
    return "".join(f"(cid:{c})" for c in cps)


def _cid_sub_label(letter_cp: int) -> str:
    """A garbled "(a)"-style marker, with the usual trailing glue glyph."""
    return _cid([_OPEN_CP, letter_cp, _CLOSE_CP, 5])


#: Body copy on these papers sets at ~10.8pt, so a word's box is that tall.
_LINE_H = 10.8


def _page_of(words: list[tuple[float, float, str]]) -> _SegPage:
    """A _SegPage built straight from (x0, top, text) — no PDF needed."""
    return _SegPage(
        width=612.0,
        height=792.0,
        words=[
            _SegWord(text=t, x0=x, top=y, bottom=y + _LINE_H)
            for x, y, t in words
        ],
        has_curves=False,
    )


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
        # Page numbers 1/2/3 encoded as glyphs 125/126/33, so the char map
        # decodes glyph 125 to "1" — the left-margin span on page 1 reuses
        # that glyph and would otherwise be read as question number 1.
        page0 = _page_of([(306.0, 30.0, _cid([125]))])
        page1 = _page_of([
            (306.0, 30.0, _cid([126])),
            (72.4, 200.0, _cid([125])),
            (93.7, 200.0, _cid_sub_label(44)),
        ])
        page2 = _page_of([
            (306.0, 30.0, _cid([33])),
            (72.4, 400.0, _cid([125])),
            (93.7, 400.0, _cid_sub_label(46)),
        ])
        boundaries = _extract_boundaries(
            [page0, page1, page2], skip_pages=set()
        )

        mains = [b for b in boundaries if b.kind == _BoundaryKind.MAIN]
        subs = [b for b in boundaries if b.kind == _BoundaryKind.SUB]
        assert len(mains) == 0
        assert len(subs) == 2

    def test_detect_main_question(self) -> None:
        page_spans = _make_cie_page(main_q="Q1")
        pdf = _make_doc([page_spans])
        boundaries = _extract_boundaries(pdf, skip_pages=set())

        mains = [b for b in boundaries if b.kind == _BoundaryKind.MAIN]
        assert len(mains) == 1
        assert mains[0].page_idx == 0

    def test_detect_sub_question(self) -> None:
        page = _page_of([
            (72.4, 53.0, _cid([15, 5])),          # main question number
            (72.4, 100.0, _cid([5])),             # (a) row's margin glyph
            (93.7, 100.0, _cid_sub_label(44)),
            (72.4, 350.0, _cid([5])),             # (b) row's margin glyph
            (93.7, 350.0, _cid_sub_label(46)),
            (72.4, 746.0, _cid([106, 5, 84])),    # footer
        ])
        boundaries = _extract_boundaries([page], skip_pages=set())

        subs = [b for b in boundaries if b.kind == _BoundaryKind.SUB]
        assert len(subs) == 2
        assert subs[0].y == pytest.approx(100.0, abs=15)
        assert subs[1].y == pytest.approx(350.0, abs=15)

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

    def test_footer_excluded(self) -> None:
        page_spans = [
            (72.4, 53.0, "Q1"),
            (72.4, 755.0, "XX"),
        ]
        pdf = _make_doc([page_spans])
        boundaries = _extract_boundaries(pdf, skip_pages=set())

        assert len(boundaries) == 1
        assert boundaries[0].y == pytest.approx(53.0, abs=15)

    def test_skip_pages(self) -> None:
        page0 = _make_cie_page(main_q="Q0")
        page1 = _make_cie_page(main_q="Q1")
        pdf = _make_doc([page0, page1])
        boundaries = _extract_boundaries(pdf, skip_pages={0})

        assert len(boundaries) == 1
        assert boundaries[0].page_idx == 1

    def test_no_text_page(self) -> None:
        """A page with no text spans yields no boundaries."""
        pdf = _make_doc([[]])
        boundaries = _extract_boundaries(pdf, skip_pages=set())
        assert boundaries == []


class TestBuildCharMapping:
    def test_catches_page_number_with_tall_header(self) -> None:
        """The original motivating case: a page-number span whose bbox top
        sits at y~=46 (a taller-than-usual header) must still be captured."""
        page0 = [(306.0, 57.6, "A")]
        page1 = [(306.0, 30.0, "B")]
        page2 = [(306.0, 30.0, "C")]
        pdf = _make_doc([page0, page1, page2])
        mapping = _build_char_mapping(pdf)

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
        # The first sub-part anchors at the MAIN boundary (y=50), not its
        # own (a) marker (y=90), so the question stem between the two is
        # included in Q1a's crop rather than lost above it.
        assert matches[0] == ("Q1a", 0, 50)
        assert matches[1] == ("Q1b", 0, 350)

    def test_first_roman_anchors_at_its_letter_marker(self) -> None:
        """The letter's own stem sits between the (b) marker and (b)(i).

        Anchoring (b)(i) at its own roman marker leaves that stem above the
        region, so it lands in the PREVIOUS question's crop instead — on
        9701 the "(b) The shorthand electronic configuration ..." line was
        cropped into Q1(a)(iv). Same rule as the MAIN-group stem: the first
        child anchors at its parent's marker.
        """
        boundaries = [
            _Boundary(kind=_BoundaryKind.MAIN, page_idx=0, y=50),
            _Boundary(kind=_BoundaryKind.SUB, page_idx=0, y=90),     # (a)
            _Boundary(kind=_BoundaryKind.SUBSUB, page_idx=0, y=120),  # (a)(i)
            _Boundary(kind=_BoundaryKind.SUBSUB, page_idx=0, y=200),  # (a)(ii)
            _Boundary(kind=_BoundaryKind.SUB, page_idx=0, y=300),     # (b) + stem
            _Boundary(kind=_BoundaryKind.SUBSUB, page_idx=0, y=340),  # (b)(i)
            _Boundary(kind=_BoundaryKind.SUBSUB, page_idx=0, y=420),  # (b)(ii)
        ]
        question_ids = [
            "Q1(a)(i)", "Q1(a)(ii)", "Q1(b)(i)", "Q1(b)(ii)",
        ]
        matches = _match_boundaries(boundaries, question_ids)

        assert len(matches) == 4
        # Group's first child still pulls all the way back to MAIN.
        assert matches[0] == ("Q1(a)(i)", 0, 50)
        assert matches[1] == ("Q1(a)(ii)", 0, 200)
        # (b)(i) anchors at the (b) marker, not at its own roman marker, so
        # the letter stem at y=300..340 is inside (b)(i) and NOT inside
        # (a)(ii)'s region (which now ends at 300).
        assert matches[2] == ("Q1(b)(i)", 0, 300)
        assert matches[3] == ("Q1(b)(ii)", 0, 420)

    def test_first_sub_of_next_main_does_not_leave_stem_behind(self) -> None:
        """Q2's stem text sits between the MAIN "2" marker and its (a)
        marker. The previous region (Q1b) ends where the next one starts,
        so Q2a must start at Q2's MAIN boundary — otherwise the stem is
        swallowed into Q1b's crop."""
        boundaries = [
            _Boundary(kind=_BoundaryKind.MAIN, page_idx=0, y=50),
            _Boundary(kind=_BoundaryKind.SUB, page_idx=0, y=90),
            _Boundary(kind=_BoundaryKind.SUB, page_idx=0, y=350),
            # Q2: main marker at top of page 1, stem paragraph, then (a)
            _Boundary(kind=_BoundaryKind.MAIN, page_idx=1, y=60),
            _Boundary(kind=_BoundaryKind.SUB, page_idx=1, y=300),
        ]
        question_ids = ["Q1a", "Q1b", "Q2a"]
        matches = _match_boundaries(boundaries, question_ids)

        assert len(matches) == 3
        assert matches[1] == ("Q1b", 0, 350)
        # Q2a anchors at the MAIN boundary so Q1b's region ends there too.
        assert matches[2] == ("Q2a", 1, 60)

    def test_first_roman_sub_part_anchors_at_main(self) -> None:
        """Nested first sub-part ("(a)(i)") also pulls back to MAIN."""
        boundaries = [
            _Boundary(kind=_BoundaryKind.MAIN, page_idx=0, y=50),
            _Boundary(kind=_BoundaryKind.SUB, page_idx=0, y=120),
            _Boundary(kind=_BoundaryKind.SUBSUB, page_idx=0, y=400),
        ]
        question_ids = ["Q1(a)(i)", "Q1(a)(ii)"]
        matches = _match_boundaries(boundaries, question_ids)

        assert len(matches) == 2
        assert matches[0] == ("Q1(a)(i)", 0, 50)
        assert matches[1] == ("Q1(a)(ii)", 0, 400)

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

    def test_subsub_overdetection_falls_back_to_sub(self) -> None:
        # Two romans in the mark scheme, but three SUBSUBs detected. Blind
        # indexing would shift crops; the guard anchors all romans to the
        # letter's SUB boundary instead.
        boundaries = [
            _Boundary(kind=_BoundaryKind.MAIN, page_idx=0, y=50),
            _Boundary(kind=_BoundaryKind.SUB, page_idx=0, y=90),
            _Boundary(kind=_BoundaryKind.SUBSUB, page_idx=0, y=120),
            _Boundary(kind=_BoundaryKind.SUBSUB, page_idx=0, y=200),
            _Boundary(kind=_BoundaryKind.SUBSUB, page_idx=0, y=300),
        ]
        question_ids = ["Q1(a)(i)", "Q1(a)(ii)"]
        matches = _match_boundaries(boundaries, question_ids)

        # First qid is pulled back to MAIN (stem); the second anchors to the
        # SUB, NOT to some mis-indexed SUBSUB.
        assert matches[0] == ("Q1(a)(i)", 0, 50)
        assert matches[1] == ("Q1(a)(ii)", 0, 90)


# ── Tests: line-top snapping ──────────────────────────────────────

class TestSnapToLineTop:
    def _page(self, words: list[_SegWord]) -> _SegPage:
        return _SegPage(width=612.0, height=792.0, words=words, has_curves=False)

    def test_lifts_to_the_tallest_thing_on_the_line(self) -> None:
        page = self._page([
            _SegWord(text="above", x0=100.0, top=40.0, bottom=50.8),
            _SegWord(text="(b)", x0=93.7, top=70.0, bottom=80.8),
            # Display maths on the same line: its box hangs down past the
            # marker's top edge, which is what puts it on this line.
            _SegWord(text="sum", x0=250.0, top=58.0, bottom=90.0),
        ])
        b = _Boundary(kind=_BoundaryKind.SUB, page_idx=0, y=70.0)

        assert _snap_to_line_top([b], [page])[0].y == 58.0

    def test_ignores_the_margin_rail(self) -> None:
        # "DO NOT WRITE IN THIS MARGIN" runs down the right edge as rotated
        # text: one tall box overlapping every line on the page.
        page = self._page([
            _SegWord(text="(b)", x0=93.7, top=70.0, bottom=80.8),
            _SegWord(text="rail", x0=578.0, top=30.0, bottom=700.0),
        ])
        b = _Boundary(kind=_BoundaryKind.SUB, page_idx=0, y=70.0)

        assert _snap_to_line_top([b], [page])[0].y == 70.0


# ── Tests: region building ────────────────────────────────────────

class TestBuildRegions:
    def test_single_page_two_questions(self) -> None:
        matches = [("Q1a", 0, 50.0), ("Q1b", 0, 400.0)]
        regions = _build_regions(matches, page_count=1, footer_y=740.0, top_margin=45.0)

        assert len(regions) == 2
        assert regions[0].question_id == "Q1a"
        assert len(regions[0].clips) == 1
        # A clip opens above its boundary — see _CLIP_TOP_PAD — while the
        # bottom stays exactly where the next question starts.
        assert regions[0].clips[0].y_top == 50.0 - _CLIP_TOP_PAD
        assert regions[0].clips[0].y_bottom == 400.0

        assert regions[1].question_id == "Q1b"
        assert regions[1].clips[0].y_top == 400.0 - _CLIP_TOP_PAD
        assert regions[1].clips[0].y_bottom == 740.0

    def test_cross_page_region(self) -> None:
        matches = [("Q1b", 0, 500.0), ("Q2", 2, 200.0)]
        regions = _build_regions(matches, page_count=3, footer_y=740.0, top_margin=45.0)

        q1b = regions[0]
        assert q1b.question_id == "Q1b"
        assert len(q1b.clips) == 3
        assert q1b.clips[0] == PageClip(
            page_idx=0, y_top=500.0 - _CLIP_TOP_PAD, y_bottom=740.0,
        )
        assert q1b.clips[1] == PageClip(page_idx=1, y_top=45.0, y_bottom=740.0)
        assert q1b.clips[2] == PageClip(page_idx=2, y_top=45.0, y_bottom=200.0)

    def test_empty_matches(self) -> None:
        regions = _build_regions([], page_count=1, footer_y=740.0, top_margin=45.0)
        assert regions == []

    def test_collapsed_siblings_are_dropped_not_emitted_empty(self) -> None:
        # Sub-questions whose boundaries were never detected all get
        # anchored to the same coordinate. Such a region has nothing to
        # crop, so it must not be returned at all.
        matches = [("Q1a", 0, 60.0), ("Q1b", 0, 60.0), ("Q1c", 0, 400.0)]
        reasons: dict[str, str] = {}
        regions = _build_regions(
            matches, page_count=1, footer_y=740.0, top_margin=45.0,
            reasons=reasons,
        )

        assert [r.question_id for r in regions] == ["Q1b", "Q1c"]
        assert all(r.clips for r in regions)
        assert reasons == {"Q1a": "degenerate"}

    def test_out_of_order_boundaries_reported_distinctly(self) -> None:
        matches = [("Q1a", 0, 400.0), ("Q1b", 0, 100.0)]
        reasons: dict[str, str] = {}
        regions = _build_regions(
            matches, page_count=1, footer_y=740.0, top_margin=45.0,
            reasons=reasons,
        )

        assert [r.question_id for r in regions] == ["Q1b"]
        assert reasons == {"Q1a": "out_of_order"}

    def test_delta_at_min_clip_height_boundary(self) -> None:
        # Exactly _MIN_CLIP_HEIGHT is kept; one point under is dropped.
        keep = _build_regions(
            [("Q1", 0, 100.0), ("Q2", 0, 120.0)],
            page_count=1, footer_y=740.0, top_margin=45.0,
        )
        assert keep[0].question_id == "Q1"

        drop = _build_regions(
            [("Q1", 0, 100.0), ("Q2", 0, 119.0)],
            page_count=1, footer_y=740.0, top_margin=45.0,
        )
        assert [r.question_id for r in drop] == ["Q2"]

    def test_reasons_optional(self) -> None:
        # Callers that don't pass `reasons` must still work.
        regions = _build_regions(
            [("Q1", 0, 60.0), ("Q2", 0, 60.0)],
            page_count=1, footer_y=740.0, top_margin=45.0,
        )
        assert [r.question_id for r in regions] == ["Q2"]


# ── Tests: format detection ───────────────────────────────────────

class TestDetectFormat:
    def test_letter(self) -> None:
        assert _detect_format(SimpleNamespace(width=612)) == "letter"  # type: ignore[arg-type]

    def test_a4(self) -> None:
        assert _detect_format(SimpleNamespace(width=595)) == "a4"  # type: ignore[arg-type]

    def test_unknown_defaults_to_letter(self) -> None:
        assert _detect_format(SimpleNamespace(width=500)) == "letter"  # type: ignore[arg-type]


# ── Tests: garbled sub-part acceptance (RC1) ──────────────────────

def _sub_span(y: float, cps: list[int], x: float = 93.7) -> dict:
    """A sub-column span dict as _extract_boundaries builds them."""
    return {"x0": x, "y0": y, "text": "", "len": len(cps), "cps": cps}


class TestAcceptedGarbledSubs:
    """The RC1 fix: detect (a)/(b)/(c) without a left-margin companion.

    Bracket pair is (240, 241); letter glyphs 35/37/248 = a/b/c. These
    take span dicts directly, so no PDF is needed.
    """

    def _per_page(self, pages_spans: list[list[dict]]) -> list:
        # (page_idx, left_spans, sub_q_spans, subsub_spans, spans_at_y)
        out = []
        for i, sub_spans in enumerate(pages_spans):
            sat: dict[float, list[dict]] = {}
            for s in sub_spans:
                sat.setdefault(s["y0"], []).append(s)
            out.append((i, [], sub_spans, [], sat))
        return out

    def test_subs_detected_without_companion(self) -> None:
        # (a)/(b)/(c) on two pages, no left-margin span anywhere.
        page = [
            _sub_span(60.0, [240, 35, 241, 5]),   # (a) + trailing glue
            _sub_span(300.0, [240, 37, 241, 5]),  # (b)
            _sub_span(500.0, [240, 248, 241, 5]),  # (c)
        ]
        per_page = self._per_page([page, page])
        acc = _accepted_garbled_subs(per_page, (240, 241), lx=72.4)
        assert [m for _y, m in acc[0]] == [35, 37, 248]

    def test_readable_paper_gets_nothing(self) -> None:
        # bracket_pair None (readable) → never emit garbled subs.
        page = [_sub_span(60.0, [40, ord("a"), 41])]
        acc = _accepted_garbled_subs(self._per_page([page]), None, lx=72.4)
        assert acc == {}

    def test_body_text_left_of_marker_rejected(self) -> None:
        # A bracketed token with a real word to its left is a phrase, not a
        # marker. Companion word sits between the margin and the marker.
        y = 60.0
        marker = _sub_span(y, [240, 35, 241, 5])
        body = {"x0": 80.0, "y0": y, "text": "", "len": 4, "cps": [1, 2, 3, 4]}
        per_page = [(0, [], [marker], [], {y: [body, marker]})]
        # Two clean occurrences on later pages so glyph 35 clears the
        # recurrence filter on its own — isolating the left-of-marker test
        # from the singleton filter.
        for i, cy in ((1, 90.0), (2, 120.0)):
            clean = _sub_span(cy, [240, 35, 241, 5])
            per_page.append((i, [], [clean], [], {cy: [clean]}))
        acc = _accepted_garbled_subs(per_page, (240, 241), lx=72.4)
        # page 0's marker is preempted by body text; the others are clean.
        assert 0 not in acc
        assert acc[1] == [(90.0, 35)]
        assert acc[2] == [(120.0, 35)]

    def test_left_margin_number_is_not_preemption(self) -> None:
        # The question number shares the first sub-part's line at x≈lx —
        # that companion is expected and must NOT reject the marker.
        y = 60.0
        qnum = {"x0": 72.4, "y0": y, "text": "", "len": 2, "cps": [61, 5]}
        marker = _sub_span(y, [240, 35, 241, 5])
        p0 = (0, [], [marker], [], {y: [qnum, marker]})
        m2 = _sub_span(90.0, [240, 35, 241, 5])
        p1 = (1, [], [m2], [], {90.0: [m2]})
        acc = _accepted_garbled_subs([p0, p1], (240, 241), lx=72.4)
        assert acc[0] == [(60.0, 35)]

    def test_singleton_glyph_filtered_out(self) -> None:
        # A glyph seen only once is likely a coincidental bracket shape.
        page = [_sub_span(60.0, [240, 99, 241, 5])]
        acc = _accepted_garbled_subs(self._per_page([page]), (240, 241), lx=72.4)
        assert acc == {}


def _ss_span(y: float, cps: list[int]) -> dict:
    """A subsub-column span dict (x ≈ 112.0)."""
    return {"x0": 112.0, "y0": y, "text": "", "len": len(cps), "cps": cps}


class TestAcceptedGarbledSubsubs:
    """The RC2 fix: detect roman sub-subs "(i)/(ii)/(iii)" in a CID font.

    Roman glyph is 38; "(ii)"/"(iii)" repeat it. A trailing glue glyph (5)
    follows the closing bracket, so the close is found by value, not index.
    """

    def _per_page(self, pages_spans: list[list[dict]]) -> list:
        return [(i, [], [], spans, {}) for i, spans in enumerate(pages_spans)]

    def test_roman_markers_detected(self) -> None:
        page = [
            _ss_span(100.0, [240, 38, 241, 5]),       # (i)
            _ss_span(300.0, [240, 38, 38, 241, 5]),   # (ii)
            _ss_span(500.0, [240, 38, 38, 38, 241, 5]),  # (iii)
        ]
        acc = _accepted_garbled_subsubs(self._per_page([page]), (240, 241))
        assert acc[0] == [100.0, 300.0, 500.0]

    def test_iv_detected_despite_new_v_glyph(self) -> None:
        # "(iv)" introduces a SECOND roman glyph (32 = 'v'), which never
        # appears as a bare "(v)" marker. Learning the alphabet only from
        # single-glyph interiors therefore never sees it and drops every
        # "(iv)" in the paper — on 9701 that cost Q1(a)(iv) its boundary and
        # shifted every roman crop under (a) by one.
        page = [
            _ss_span(100.0, [240, 38, 241, 5]),          # (i)
            _ss_span(200.0, [240, 38, 38, 241, 5]),      # (ii)
            _ss_span(300.0, [240, 38, 38, 38, 241, 5]),  # (iii)
            _ss_span(400.0, [240, 38, 32, 241, 5]),      # (iv)
        ]
        # Two pages so the 'v' glyph recurs, as it does in a real paper.
        acc = _accepted_garbled_subsubs(self._per_page([page, page]), (240, 241))
        assert acc[0] == [100.0, 200.0, 300.0, 400.0]

    def test_body_text_at_column_rejected(self) -> None:
        # A wrapped body line indented to the subsub column: bracket-shaped
        # by coincidence but its interior glyph isn't the roman glyph.
        page = [
            _ss_span(100.0, [240, 38, 241, 5]),        # (i) — real
            _ss_span(200.0, [240, 77, 78, 79, 241, 5]),  # body: mixed glyphs
        ]
        acc = _accepted_garbled_subsubs(self._per_page([page]), (240, 241))
        assert acc[0] == [100.0]

    def test_readable_paper_gets_nothing(self) -> None:
        page = [_ss_span(100.0, [40, ord("i"), 41])]
        acc = _accepted_garbled_subsubs(self._per_page([page]), None)
        assert acc == {}


# ── Tests: CID-encoding detection ─────────────────────────────────

class TestIsCidEncoded:
    def test_garbled_paper_detected(self) -> None:
        page = _page_of([
            (72.4, 100.0, _cid([15, 5])),
            (93.7, 100.0, _cid_sub_label(44)),
        ])
        assert _is_cid_encoded([page, page], skip=set()) is True

    def test_readable_paper_not_detected(self) -> None:
        page = _page_of([(72.4, 100.0, "1"), (93.7, 100.0, "Fig")])
        assert _is_cid_encoded([page, page], skip=set()) is False

    def test_readable_cover_does_not_mask_garbled_body(self) -> None:
        # Cover pages are skipped by the segmenter; a readable cover in front
        # of a garbled body must not drag the ratio below the threshold.
        cover = _page_of([(x, 100.0, f"word{x}") for x in range(60, 200, 10)])
        body = _page_of([
            (72.4, 100.0, _cid([15, 5])),
            (93.7, 100.0, _cid_sub_label(44)),
        ])
        assert _is_cid_encoded([cover, body, body], skip={0}) is True

    def test_empty_document_is_not_cid(self) -> None:
        assert _is_cid_encoded([], skip=set()) is False


class TestBracketPairTrust:
    """The bracket pair must be gated on whether the PDF is CID-encoded.

    The previous gate required both bracket code points to be >= 128, on the
    assumption that a garbled font's bracket glyph is always a high byte.
    9701 chemistry encodes them as (113, 114) — low bytes — so the real pair
    was thrown away and every sub-part boundary with it (4/42 questions
    matched). Code-point magnitude says nothing about whether the font is
    garbled; whether the document uses CID encoding says it directly.
    """

    def _garbled_pages(self) -> list[_SegPage]:
        # Two pages, each: a 1-cp left-margin span sharing its line with a
        # bracket-shaped sub-column marker "(a)". Two occurrences clear both
        # the pair-count and glyph-recurrence filters, so the only thing that
        # can reject them is the gate.
        return [
            _page_of([
                (72.4, 100.0, _cid([5])),
                (93.7, 100.0, _cid_sub_label(44)),
                (136.4, 120.0, _cid([98, 25, 11, 13])),
            ])
            for _ in range(2)
        ]

    def test_low_byte_bracket_pair_is_trusted_when_cid_encoded(self) -> None:
        boundaries = _extract_boundaries(self._garbled_pages(), skip_pages=set())
        subs = [b for b in boundaries if b.kind == _BoundaryKind.SUB]
        assert len(subs) == 2, f"expected both (a) markers, got {boundaries}"

    def test_readable_paper_noise_pair_still_rejected(self) -> None:
        # "Fig" is (F=70, i=105, g=103) → cps[0], cps[2] = (70, 103), the exact
        # noise pair measured on readable 9700. Trusting it injects phantom
        # SUBs that displace the genuine readable-text ones.
        pages = [
            _page_of([
                (72.4, 100.0, "x"),
                (93.7, 100.0, "Fig"),
                (136.4, 120.0, "body text"),
            ])
            for _ in range(2)
        ]
        boundaries = _extract_boundaries(pages, skip_pages=set())
        subs = [b for b in boundaries if b.kind == _BoundaryKind.SUB]
        assert subs == [], f"phantom SUBs from readable text: {boundaries}"


# ── Tests: validate_regions ───────────────────────────────────────

def _clip(page: int = 0) -> PageClip:
    """A clip tall enough to be usable, for match/unmatch assertions."""
    return PageClip(page_idx=page, y_top=100.0, y_bottom=400.0)


class TestValidateRegions:
    def test_all_matched(self) -> None:
        regions = [
            QuestionRegion(question_id="Q1a", clips=[_clip()]),
            QuestionRegion(question_id="Q1b", clips=[_clip()]),
        ]
        matched, unmatched = validate_regions(regions, ["Q1a", "Q1b"])
        assert matched == ["Q1a", "Q1b"]
        assert unmatched == []

    def test_partial_match(self) -> None:
        regions = [QuestionRegion(question_id="Q1a", clips=[_clip()])]
        matched, unmatched = validate_regions(regions, ["Q1a", "Q1b", "Q2"])
        assert matched == ["Q1a"]
        assert unmatched == ["Q1b", "Q2"]

    def test_clipless_region_is_not_a_match(self) -> None:
        # A region with no clips cannot be cropped or graded — counting it
        # as matched is what made the UI report "30/30" on a paper where
        # two thirds of the questions were unusable.
        regions = [
            QuestionRegion(question_id="Q1a", clips=[_clip()]),
            QuestionRegion(question_id="Q1b", clips=[]),
        ]
        matched, unmatched = validate_regions(regions, ["Q1a", "Q1b"])
        assert matched == ["Q1a"]
        assert unmatched == ["Q1b"]


# ── Tests: full pipeline ──────────────────────────────────────────

class TestSegmentQuestions:
    def test_full_pipeline(self) -> None:
        """Multi-page synthetic PDF with CIE-like layout (readable text).

        Garbled papers cannot be synthesised through FPDF, so the bytes-in
        pipeline is exercised on the readable path; the garbled path is
        covered from _extract_boundaries down (see TestBracketPairTrust).
        """
        page0 = _make_cie_page(
            main_q="Q1",
            subs=[
                (90.0, _readable_sub_label("a")),
                (400.0, _readable_sub_label("b")),
            ],
        )
        page1 = _make_cie_page(
            main_q="Q2",
        )
        pdf_bytes = _make_pdf_bytes([page0, page1])

        regions, _ = segment_questions_report(
            pdf_bytes, ["Q1a", "Q1b", "Q2"], skip_pages=set()
        )

        assert len(regions) == 3
        assert regions[0].question_id == "Q1a"
        assert regions[1].question_id == "Q1b"
        assert regions[2].question_id == "Q2"

    def test_default_skips_first_page(self) -> None:
        page0 = _make_cie_page(main_q="XX")
        page1 = _make_cie_page(main_q="Q1")
        pdf_bytes = _make_pdf_bytes([page0, page1])

        regions, _ = segment_questions_report(pdf_bytes, ["Q1"])

        assert len(regions) == 1
        assert regions[0].clips[0].page_idx == 1

    def test_empty_page_returns_empty(self) -> None:
        pdf_bytes = _make_pdf_bytes([[]])
        regions, _ = segment_questions_report(
            pdf_bytes, ["Q1", "Q2"], skip_pages=set()
        )
        assert regions == []


class TestTwoPhaseSegmentation:
    """scan_document + match_scanned must equal the one-shot call.

    The Mark tab runs the scan concurrently with the mark-scheme parse and
    only matches once the question ids arrive, so the split has to be exact.
    """

    def _pdf(self) -> bytes:
        return _make_pdf_bytes([
            _make_cie_page(
                main_q="Q1",
                subs=[
                    (90.0, _readable_sub_label("a")),
                    (400.0, _readable_sub_label("b")),
                ],
            ),
            _make_cie_page(main_q="Q2"),
        ])

    def test_split_matches_one_shot(self) -> None:
        pdf_bytes = self._pdf()
        q_ids = ["Q1a", "Q1b", "Q2"]

        expected, exp_report = segment_questions_report(
            pdf_bytes, q_ids, skip_pages=set(),
        )
        doc = scan_document(pdf_bytes, skip_pages=set())
        actual, act_report = match_scanned(doc, q_ids)

        assert actual == expected
        assert act_report == exp_report

    def test_one_scan_serves_different_question_ids(self) -> None:
        # The point of the split: the PDF is read once, then matched against
        # whatever the mark scheme turns out to contain.
        pdf_bytes = self._pdf()
        doc = scan_document(pdf_bytes, skip_pages=set())

        full, _ = match_scanned(doc, ["Q1a", "Q1b", "Q2"])
        partial, report = match_scanned(doc, ["Q1a"])

        assert [r.question_id for r in full] == ["Q1a", "Q1b", "Q2"]
        assert [r.question_id for r in partial] == ["Q1a"]
        assert report.unmatched == []

    def test_page_count_needs_no_second_load(self) -> None:
        doc = scan_document(self._pdf(), skip_pages=set())
        assert doc.page_count == 2

    def test_empty_pdf_scans_without_error(self) -> None:
        doc = scan_document(_make_pdf_bytes([[]]), skip_pages=set())
        regions, report = match_scanned(doc, ["Q1"])
        assert regions == []
        assert report.unmatched == ["Q1"]
