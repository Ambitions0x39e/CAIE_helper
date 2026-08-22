"""Tests for ``modules.marking.mistake_pdf`` — the 错题本's PDF export.

Three layers, because they fail differently:

* the layout arithmetic (``plan_pages``) is pure and gets exact assertions;
* dropping the answer space is measured against a synthesised paper laid out
  the way a real one is — question text, a ruled table, then rows of dots;
* the composition is checked through the clip rectangles pypdf writes into
  the output. That is the only machine-checkable proof that the crop holds:
  text extraction ignores clip paths, so an un-clipped page and a correctly
  clipped one extract identical text.
"""
from __future__ import annotations

import datetime
import io
import re
from pathlib import Path

import pytest
from fpdf import FPDF
from pdfminer.high_level import extract_pages
from pypdf import PdfReader

from core.models import MistakeRecord
from modules.marking.mistake_pdf import (
    Band,
    QuestionCrop,
    _page_extents,
    build_export,
    compose_pdf,
    content_bands,
    main_question_id,
    main_questions_by_paper,
    plan_pages,
)

_TS = datetime.datetime(2026, 8, 20, 15, 0, 0)
_PAGE_H = 792.0
_PAGE_W = 612.0


def _record(question_id: str, paper_id: str = "9231_s22_qp_41") -> MistakeRecord:
    return MistakeRecord(
        paper_id=paper_id,
        question_id=question_id,
        topic_id=None,
        topic_name=None,
        score=1.0,
        max_score=5.0,
        comment="",
        timestamp=_TS,
    )


def _clip_rects(path: Path) -> list[list[str]]:
    """The `x y w h re W n` rectangles pypdf wrote, per output page."""
    out = []
    for page in PdfReader(str(path)).pages:
        stream = page.get_contents().get_data().decode("latin-1")
        out.append(
            re.findall(r"([-\d.]+ [-\d.]+ [-\d.]+ [-\d.]+)\s+re\s+W\s+n", stream)
        )
    return out


# ── Grouping ──────────────────────────────────────────────────────


class TestMainQuestionId:
    @pytest.mark.parametrize(
        ("question_id", "expected"),
        [
            ("Q4b", "Q4"),
            ("Q4", "Q4"),
            ("Q10", "Q10"),
            ("Q10(a)(ii)", "Q10"),
            ("4a", "4"),
            ("  Q7e  ", "Q7"),
        ],
    )
    def test_strips_to_the_main_number(
        self, question_id: str, expected: str
    ) -> None:
        assert main_question_id(question_id) == expected

    def test_an_id_with_no_number_survives_unchanged(self) -> None:
        assert main_question_id("intro") == "intro"


def test_main_questions_are_deduped_in_first_seen_order() -> None:
    records = [
        _record("Q4b"), _record("Q2a"), _record("Q4a"), _record("Q2c"),
        _record("Q1", paper_id="9709_s25_qp_12"),
    ]

    assert main_questions_by_paper(records) == {
        "9231_s22_qp_41": ["Q4", "Q2"],
        "9709_s25_qp_12": ["Q1"],
    }


# ── Layout ────────────────────────────────────────────────────────


class TestPlanPages:
    def _band(self, height: float) -> Band:
        return Band(page_idx=0, y_top=0.0, y_bottom=height)

    def test_bands_stack_down_one_page(self) -> None:
        pages = plan_pages(
            [self._band(100), self._band(100)], 800, margin=20, gap=10
        )

        assert len(pages) == 1
        assert [p.y_top for p in pages[0]] == [20, 130]

    def test_wraps_when_the_next_band_would_not_fit(self) -> None:
        pages = plan_pages(
            [self._band(400), self._band(400)], 500, margin=20, gap=10
        )

        assert [len(p) for p in pages] == [1, 1]
        assert pages[1][0].y_top == 20

    def test_a_band_taller_than_a_page_still_gets_one(self) -> None:
        """Dropping it would be worse than letting it run over."""
        pages = plan_pages([self._band(900)], 500, margin=20, gap=10)

        assert len(pages) == 1
        assert pages[0][0].band.height == 900

    def test_no_bands_means_no_pages(self) -> None:
        assert plan_pages([], 800) == []


# ── Dropping the answer space ─────────────────────────────────────


#: Where CIE really prints main question numbers on a 612pt-wide page —
#: the same constant ``page_segmenter`` matches boundaries against. The
#: fixture used to put them at x62, which no paper does, and that is why it
#: kept passing while real exports came out with the number sliced off.
_NUMBER_X = 72.4
_COLUMN_X = 94.0
#: Where the ruling goes when a question's answer space is all under a
#: sub-part — 21pt right of the writing column, measured on 9231 s25 P1.
_INDENT_X = 115.0
_BAR_X = 26.0


def _paper_pdf(path: Path) -> Path:
    """A page shaped like a real one: stem, ruled table, then answer space."""
    pdf = FPDF(unit="pt", format=(_PAGE_W, _PAGE_H))
    pdf.set_auto_page_break(auto=False)
    pdf.set_font("Helvetica", size=10)
    pdf.add_page()
    pdf.rect(_BAR_X, 0, 20, _PAGE_H)            # the margin bar CIE prints
    pdf.text(36, 36, "8")                       # page number, above the region
    pdf.text(_NUMBER_X, 60, "4")                # the number, in its gutter
    pdf.text(_COLUMN_X, 60, "A scientist is investigating butterflies.")
    pdf.text(_COLUMN_X, 74, "The table shows the observed frequencies.")
    pdf.rect(104, 100, 420, 40)                 # the table: graphics, not text
    pdf.text(_COLUMN_X, 170, "(a)  Find the values of p and q.")
    for i in range(10):                         # answer space
        pdf.text(_COLUMN_X, 195 + i * 24, "." * 90)
    pdf.text(_COLUMN_X, 450, "(b)  Carry out a goodness of fit test.")
    for i in range(8):
        pdf.text(_COLUMN_X, 475 + i * 24, "." * 90)
    pdf.output(str(path))
    return path


class TestContentBands:
    def _bands(self, tmp_path: Path) -> list[Band]:
        pdf = _paper_pdf(tmp_path / "qp.pdf")
        whole = [Band(page_idx=0, y_top=50.0, y_bottom=740.0)]
        return content_bands(str(pdf), whole)

    def test_rows_of_dots_are_dropped(self, tmp_path: Path) -> None:
        bands = self._bands(tmp_path)

        # Two blocks: the stem+table+(a), and (b). The ~250pt of ruling
        # between them is gone.
        assert len(bands) == 2
        assert sum(b.height for b in bands) < 250

    def test_the_stem_and_its_table_stay_together(
        self, tmp_path: Path
    ) -> None:
        """The table is drawn, not written — graphics have to count as
        content or every diagram would be cropped away."""
        first = self._bands(tmp_path)[0]

        assert first.y_top < 60          # starts at the question number
        assert first.y_bottom > 170      # runs past the table to "(a)"

    def test_the_second_block_is_the_b_part(self, tmp_path: Path) -> None:
        """It spans from the end of one ruling block to the start of the
        next, not from the text — the gap is kept whole because on a paper
        whose question text isn't in the text layer, shrinking to the text
        would cut the question away."""
        second = self._bands(tmp_path)[1]

        assert second.y_top < 450 < second.y_bottom   # "(b)" is at y=450
        assert second.height < 60

    def test_no_band_starts_above_the_region(self, tmp_path: Path) -> None:
        """The page number sits just outside the region and used to graze
        it, becoming a five-point band on every page of pure answer space."""
        bands = content_bands(
            str(_paper_pdf(tmp_path / "qp.pdf")),
            [Band(page_idx=0, y_top=45.0, y_bottom=740.0)],
        )

        assert all(b.height > 6 for b in bands)
        assert all(b.y_top >= 45 for b in bands)

    def test_ruling_is_recognised_whatever_the_glyph_decodes_to(
        self, tmp_path: Path
    ) -> None:
        """Half the papers embed fonts with no ToUnicode map, so pdfminer
        reports the ruling as ``(cid:155)`` rather than a full stop. What a
        ruling is, in any encoding, is one glyph repeated across the line —
        so this paper rules with 'o' and must be trimmed just the same.
        """
        pdf = FPDF(unit="pt", format=(_PAGE_W, _PAGE_H))
        pdf.set_auto_page_break(auto=False)
        pdf.set_font("Helvetica", size=10)
        pdf.add_page()
        pdf.text(62, 60, "4  A scientist is investigating butterflies.")
        for i in range(10):
            pdf.text(62, 100 + i * 24, "o" * 90)
        pdf.text(62, 360, "(b)  Carry out a test.")
        path = tmp_path / "odd.pdf"
        pdf.output(str(path))

        bands = content_bands(
            str(path), [Band(page_idx=0, y_top=50.0, y_bottom=740.0)]
        )

        assert len(bands) == 2
        assert sum(b.height for b in bands) < 200   # the ruling is gone

    def test_the_number_survives_answer_space_that_is_indented(
        self, tmp_path: Path
    ) -> None:
        """The writing column is not where the ruling is.

        A question whose answer space all sits under a sub-part is ruled
        21pt further right, and deriving the crop's left edge from the
        ruling then put it right of the question number: measured across the
        52 papers on disk, 16 cropped at x79 and two at x100, against
        numbers printed at x72.4. Every one of those lost its number.
        """
        pdf = FPDF(unit="pt", format=(_PAGE_W, _PAGE_H))
        pdf.set_auto_page_break(auto=False)
        pdf.set_font("Helvetica", size=10)
        pdf.add_page()
        pdf.rect(_BAR_X, 0, 20, _PAGE_H)
        pdf.text(_NUMBER_X, 60, "7")
        pdf.text(_COLUMN_X, 60, "The curve C has the equation given below.")
        pdf.text(_INDENT_X, 90, "(a)  Find the equations of the asymptotes.")
        for i in range(12):                      # ruled under the sub-part
            pdf.text(_INDENT_X, 110 + i * 24, "." * 80)
        path = tmp_path / "indented.pdf"
        pdf.output(str(path))

        band = content_bands(
            str(path), [Band(page_idx=0, y_top=50.0, y_bottom=740.0)]
        )[0]

        assert band.x_left is not None
        assert band.x_left < _NUMBER_X          # the number is in the crop
        assert band.x_left > _BAR_X + 20        # the margin bar is not

    def test_tall_maths_on_the_first_line_is_not_sliced(
        self, tmp_path: Path
    ) -> None:
        """A region starts at the top of the question *number*, which is not
        the top of its line. Measured on 9231 s25 P1 Q7: the displayed
        fraction beside "7" tops out 8pt higher, so the crop cut its
        numerator in half — the defect that started this."""
        pdf = FPDF(unit="pt", format=(_PAGE_W, _PAGE_H))
        pdf.set_auto_page_break(auto=False)
        pdf.set_font("Helvetica", size=10)
        pdf.add_page()
        pdf.text(_NUMBER_X, 80, "7")
        pdf.text(_COLUMN_X, 80, "The curve C has equation y =")
        pdf.set_font("Helvetica", size=30)       # stands in for the fraction
        pdf.text(240, 80, "N")
        pdf.set_font("Helvetica", size=10)
        for i in range(12):
            pdf.text(_COLUMN_X, 130 + i * 24, "." * 80)
        path = tmp_path / "fraction.pdf"
        pdf.output(str(path))

        # 70.5 is where the segmenter puts the boundary: the top of the "7".
        band = content_bands(
            str(path), [Band(page_idx=0, y_top=70.5, y_bottom=740.0)]
        )[0]

        # The 30pt glyph's box tops out at 56.2; the "7" beside it at 70.5.
        assert band.y_top < 57.0        # the whole glyph is in the crop

    def test_a_denominator_hanging_into_the_ruling_is_not_sliced(
        self, tmp_path: Path
    ) -> None:
        """The band ends where the answer space starts, and a displayed
        fraction on the last line hangs below the line it sits on — measured
        on 9231 s25 P1, 22 of the paper's bands ended 3–5pt inside one."""
        pdf = FPDF(unit="pt", format=(_PAGE_W, _PAGE_H))
        pdf.set_auto_page_break(auto=False)
        pdf.set_font("Helvetica", size=10)
        pdf.add_page()
        pdf.text(_NUMBER_X, 80, "7")
        pdf.text(_COLUMN_X, 80, "Find the exact value of")
        pdf.set_font("Helvetica", size=30)      # stands in for the fraction
        pdf.text(240, 80, "N")                  # its box runs down to 86.2
        pdf.set_font("Helvetica", size=10)
        for i in range(12):                     # ruling starts at 82.4
            pdf.text(_COLUMN_X, 92 + i * 24, "." * 80)
        path = tmp_path / "denominator.pdf"
        pdf.output(str(path))

        band = content_bands(
            str(path), [Band(page_idx=0, y_top=70.5, y_bottom=740.0)]
        )[0]

        assert band.y_bottom > 86.0

    def test_a_region_holding_only_the_next_question_yields_nothing(
        self, tmp_path: Path
    ) -> None:
        """A question's last page can carry none of it — the region there
        runs from the page's top margin to the next question's number, and
        the only thing in that strip is the tall part of *that* question's
        first line. Measured on 9231 s25 P1 p8: Q4's matrix was 68% inside
        Q3's region, over the 60% membership bar, and came out stuck to the
        end of Q3 with no question of its own attached."""
        pdf = FPDF(unit="pt", format=(_PAGE_W, _PAGE_H))
        pdf.set_auto_page_break(auto=False)
        pdf.set_font("Helvetica", size=10)
        pdf.add_page()
        pdf.text(303, 45, "8")               # page number, above the region
        pdf.text(240, 72.5, "M")             # 64.6–74.6: 62% inside, so it
        pdf.text(_NUMBER_X, 79, "4")         # used to qualify as content
        pdf.text(_COLUMN_X, 79, "The matrix M is given by")
        path = tmp_path / "spill.pdf"
        pdf.output(str(path))

        assert content_bands(
            str(path), [Band(page_idx=0, y_top=45.0, y_bottom=70.8)]
        ) == []

    def test_a_band_never_grows_into_the_next_question(
        self, tmp_path: Path
    ) -> None:
        """The bottom edge is bounded by the region and the top edge is not,
        and that asymmetry is deliberate: what sits above a question number
        on its own line is *its* maths, but what sits below the next
        question's number is the *next* question's."""
        pdf = FPDF(unit="pt", format=(_PAGE_W, _PAGE_H))
        pdf.set_auto_page_break(auto=False)
        pdf.set_font("Helvetica", size=10)
        pdf.add_page()
        # Ends at 72.1, so the crop's bottom edge lands at 75.1 — inside the
        # next question's 30pt glyph, which runs from 71.2 down to 101.2.
        pdf.text(_COLUMN_X, 70, "the tail of the previous question.")
        pdf.set_font("Helvetica", size=30)
        pdf.text(240, 95, "N")              # the next question's fraction
        pdf.set_font("Helvetica", size=10)
        pdf.text(_NUMBER_X, 95, "8")        # …and the next question's number
        for i in range(12):
            pdf.text(_COLUMN_X, 130 + i * 24, "." * 80)
        path = tmp_path / "next.pdf"
        pdf.output(str(path))

        # The region ends at the top of "8"; Q8's 30pt glyph starts above it.
        bands = content_bands(
            str(path), [Band(page_idx=0, y_top=50.0, y_bottom=80.5)]
        )

        assert bands, "the previous question's own line must still be kept"
        assert all(b.y_bottom <= 80.5 for b in bands)

    def test_the_margin_copyright_ladder_does_not_drag_the_crop_up(
        self, tmp_path: Path
    ) -> None:
        """CIE sets its copyright line sideways down the page margin, one
        glyph box per character with each touching the next. Grown through,
        that ladder walks a band's top up the page a few points at a time —
        measured on 9231 s25 P1 p7, from y57 to y49, which brought the
        barcode strip at y51–56 into the crop.
        """
        pdf = FPDF(unit="pt", format=(_PAGE_W, _PAGE_H))
        pdf.set_auto_page_break(auto=False)
        pdf.add_page()
        pdf.set_font("Helvetica", size=6)
        for i in range(14):                     # the ladder, x36: outside
            pdf.text(36, 50 + i * 5, "x")       # the writing column
        pdf.set_font("Helvetica", size=5)
        pdf.text(87, 55, "|" * 60)              # the barcode: inside it
        pdf.set_font("Helvetica", size=10)
        pdf.text(_NUMBER_X, 80, "7")
        pdf.text(_COLUMN_X, 80, "The curve C has equation y =")
        pdf.set_font("Helvetica", size=24)
        pdf.text(240, 80, "N")                  # tops out at 61.0
        pdf.set_font("Helvetica", size=10)
        for i in range(12):
            pdf.text(_COLUMN_X, 130 + i * 24, "." * 80)
        path = tmp_path / "ladder.pdf"
        pdf.output(str(path))

        band = content_bands(
            str(path), [Band(page_idx=0, y_top=70.5, y_bottom=740.0)]
        )[0]

        assert band.y_top < 62.0        # the 24pt glyph is still kept whole
        assert band.y_top > 58.0        # …and the climb stopped there

    def test_the_barcode_is_not_a_superscript(self, tmp_path: Path) -> None:
        """The rule that keeps a 7.5pt exponent has to keep out a 4.7pt
        barcode. Both are small and both sit inside the writing column; only
        the exponent shares its line with full-size glyphs."""
        pdf = FPDF(unit="pt", format=(_PAGE_W, _PAGE_H))
        pdf.set_auto_page_break(auto=False)
        pdf.add_page()
        pdf.set_font("Helvetica", size=4.7)
        # Varied glyphs, or it reads as ruling and never reaches the size
        # rule at all — a real barcode strip extracts as a mixed run.
        pdf.text(87, 55, "IHFEGDCBA" * 6)       # barcode, alone up top
        pdf.set_font("Helvetica", size=10)
        pdf.text(_COLUMN_X, 80, "The curve C has equation y = 2x")
        pdf.set_font("Helvetica", size=7)
        pdf.text(210, 75, "2")                  # the exponent, on that line
        path = tmp_path / "sizes.pdf"
        pdf.output(str(path))

        extents = _page_extents(
            next(extract_pages(str(path))), _PAGE_H, (69.4, 544.0)
        )

        # The exponent's box (69.4–76.5) is there; the barcode's (51.0–56.0)
        # is not.
        assert any(69.0 < top < 70.0 for top, _ in extents)
        assert not any(top < 60.0 for top, _ in extents)

    def test_the_first_line_grows_no_further_than_the_top_margin(
        self, tmp_path: Path
    ) -> None:
        """Growing the top is for a question's own line, not for the page's
        running head — a question starting at the top of a page has nothing
        above it worth keeping."""
        pdf = FPDF(unit="pt", format=(_PAGE_W, _PAGE_H))
        pdf.set_auto_page_break(auto=False)
        pdf.set_font("Helvetica", size=12)
        pdf.add_page()
        pdf.text(_COLUMN_X, 50, "9231/11/M/J/25")   # straddles y=45
        pdf.set_font("Helvetica", size=10)
        pdf.text(_COLUMN_X, 70, "continued from the previous page.")
        for i in range(12):
            pdf.text(_COLUMN_X, 100 + i * 24, "." * 80)
        path = tmp_path / "head.pdf"
        pdf.output(str(path))

        bands = content_bands(
            str(path), [Band(page_idx=0, y_top=45.0, y_bottom=740.0)]
        )

        assert all(b.y_top >= 45.0 for b in bands)

    def _blank_page_pdf(self, path: Path, text: str, centred: bool) -> Path:
        """A page CIE fills with one line and nothing else."""
        pdf = FPDF(unit="pt", format=(_PAGE_W, _PAGE_H))
        pdf.set_auto_page_break(auto=False)
        pdf.add_page()
        pdf.set_font("Helvetica", size=4.7)
        pdf.text(87, 40, "IHFEGDCBA" * 6)               # barcode, up in the
        pdf.set_font("Helvetica", size=10)              # running head
        number = "12"
        pdf.text((_PAGE_W - pdf.get_string_width(number)) / 2, 42, number)
        pdf.set_font("Helvetica", size=12)
        width = pdf.get_string_width(text)
        pdf.text((_PAGE_W - width) / 2 if centred else 126.0, 400, text)
        pdf.output(str(path))
        return path

    def test_a_blank_page_inside_a_question_contributes_nothing(
        self, tmp_path: Path
    ) -> None:
        """CIE drops blank pages between questions and a region runs
        straight through them, so one lands in the middle of a crop — the
        band it produced said "BLANK PAGE" and nothing else.

        Matched on shape, not on those words: half the papers embed their
        fonts with no ToUnicode map and there the words extract as
        "(cid:220)(cid:221)…".
        """
        path = self._blank_page_pdf(
            tmp_path / "blank.pdf", "BLANK PAGE", centred=True
        )

        assert content_bands(
            str(path), [Band(page_idx=0, y_top=45.0, y_bottom=740.0)]
        ) == []

    def test_an_unruled_page_that_carries_content_is_kept(
        self, tmp_path: Path
    ) -> None:
        """Only *centred* is a blank page. 9618 sets its code-listing
        answers on pages with no ruling and no graphics either, indented but
        left-aligned — six such pages on the papers to hand, and dropping
        them would have thrown away real questions."""
        path = self._blank_page_pdf(
            tmp_path / "code.pdf",
            "IF Count > 0 THEN OUTPUT Total / Count",
            centred=False,
        )

        assert content_bands(
            str(path), [Band(page_idx=0, y_top=45.0, y_bottom=740.0)]
        ) != []

    def test_a_page_of_pure_answer_space_yields_nothing(
        self, tmp_path: Path
    ) -> None:
        """Which is the point: those pages add nothing to the export."""
        pdf = FPDF(unit="pt", format=(_PAGE_W, _PAGE_H))
        pdf.set_auto_page_break(auto=False)
        pdf.set_font("Helvetica", size=10)
        pdf.add_page()
        pdf.text(36, 36, "9")                    # page number, outside
        for i in range(28):
            pdf.text(62, 72 + i * 24, "." * 90)
        path = tmp_path / "blank.pdf"
        pdf.output(str(path))

        assert content_bands(
            str(path), [Band(page_idx=0, y_top=45.0, y_bottom=740.0)]
        ) == []


# ── Composition ───────────────────────────────────────────────────


class TestComposePdf:
    def test_one_page_per_question_with_the_bands_clipped(
        self, tmp_path: Path
    ) -> None:
        source = _paper_pdf(tmp_path / "qp.pdf")
        crops = [
            QuestionCrop("p", "Q1", str(source), [
                Band(page_idx=0, y_top=60.0, y_bottom=180.0),
                Band(page_idx=0, y_top=445.0, y_bottom=465.0),
            ]),
            QuestionCrop("p", "Q2", str(source), [
                Band(page_idx=0, y_top=60.0, y_bottom=100.0),
            ]),
        ]

        out = tmp_path / "out.pdf"
        out.write_bytes(compose_pdf(crops))

        rects = _clip_rects(out)
        assert len(rects) == 2                    # a page per question
        assert len(rects[0]) == 2                 # both of Q1's bands
        assert len(rects[1]) == 1
        # y measured up from the page bottom; height is the band's.
        assert rects[0][0].startswith("0.0 612 612 120")
        assert rects[1][0].startswith("0.0 692 612 40")

    def test_the_crop_is_narrowed_to_the_writing_column(
        self, tmp_path: Path
    ) -> None:
        """Cropping the full page width drags in what CIE prints down the
        sides — the margin bar and the registration marks — which is what
        made the crops look like scraps rather than questions."""
        source = _paper_pdf(tmp_path / "qp.pdf")
        bands = content_bands(
            str(source), [Band(page_idx=0, y_top=50.0, y_bottom=740.0)]
        )
        out = tmp_path / "out.pdf"
        out.write_bytes(compose_pdf([
            QuestionCrop("p", "Q1", str(source), bands)
        ]))

        rect = _clip_rects(out)[0][0].split()
        x, width = float(rect[0]), float(rect[2])
        assert x > _BAR_X + 20      # the margin bar is outside the crop
        assert x < _NUMBER_X        # …but the question number is inside it
        assert width < _PAGE_W - x  # and so is whatever sits down the right

    def test_pages_keep_the_source_size(self, tmp_path: Path) -> None:
        source = _paper_pdf(tmp_path / "qp.pdf")
        crops = [QuestionCrop("p", "Q1", str(source), [
            Band(page_idx=0, y_top=60.0, y_bottom=180.0),
        ])]

        out = tmp_path / "out.pdf"
        out.write_bytes(compose_pdf(crops))

        page = PdfReader(str(out)).pages[0]
        assert (float(page.mediabox.width), float(page.mediabox.height)) == (
            _PAGE_W, _PAGE_H
        )

    def test_nothing_to_export_raises(self, tmp_path: Path) -> None:
        """An empty PDF is not a useful thing to hand back as a file."""
        source = _paper_pdf(tmp_path / "qp.pdf")

        with pytest.raises(ValueError, match="没有可导出"):
            compose_pdf([QuestionCrop("p", "Q1", str(source), [])])


# ── The whole export ──────────────────────────────────────────────


class TestBuildExport:
    """Orchestration only.

    Locating a question inside a QP is the segmenter's job and has its own
    tests (and its own real-paper fixtures); it is stubbed here so these
    stay about what ``build_export`` decides — which papers it can use, and
    what it says about the ones it can't.
    """

    @pytest.fixture
    def _stub_crops(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> Path:
        source = _paper_pdf(tmp_path / "qp.pdf")

        def _fake(
            paper_id: str, qp_path: str, wanted: list[str]
        ) -> tuple[list[QuestionCrop], list[str]]:
            return [
                QuestionCrop(paper_id, q, qp_path, [
                    Band(page_idx=0, y_top=60.0, y_bottom=180.0),
                ])
                for q in wanted
            ], []

        monkeypatch.setattr(
            "modules.marking.mistake_pdf.crops_for_paper", _fake
        )
        return source

    def test_a_paper_with_no_qp_on_disk_is_named_not_skipped(
        self, _stub_crops: Path, tmp_path: Path
    ) -> None:
        records = [
            _record("Q1", paper_id="9231_s22_qp_41"),
            _record("Q1", paper_id="9709_s25_qp_12"),
        ]

        data, warnings = build_export(records, {
            "9231_s22_qp_41": str(_stub_crops),
            "9709_s25_qp_12": str(tmp_path / "gone.pdf"),
        })

        assert data.startswith(b"%PDF")
        assert len(warnings) == 1
        assert "9709_s25_qp_12" in warnings[0]

    def test_a_paper_with_no_recorded_qp_path_is_named_too(
        self, _stub_crops: Path
    ) -> None:
        _, warnings = build_export(
            [_record("Q1"), _record("Q1", paper_id="9702_s25_qp_21")],
            {"9231_s22_qp_41": str(_stub_crops), "9702_s25_qp_21": ""},
        )

        assert any("9702_s25_qp_21" in w for w in warnings)

    def test_an_untrimmable_paper_says_so(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Some papers embed fonts with no ToUnicode map: pdfminer reports
        every glyph as "(cid:155)" and cannot group them into lines, so the
        answer ruling is indistinguishable from the question. Measured on a
        real 2025 paper — 10k cid tokens, zero readable words. The export
        falls back to the whole region and has to admit it."""
        source = _paper_pdf(tmp_path / "qp.pdf")

        def _fake(
            paper_id: str, qp_path: str, wanted: list[str]
        ) -> tuple[list[QuestionCrop], list[str]]:
            return [
                QuestionCrop(paper_id, q, qp_path, [
                    Band(page_idx=0, y_top=60.0, y_bottom=700.0),
                ], trimmed=False)
                for q in wanted
            ], []

        monkeypatch.setattr(
            "modules.marking.mistake_pdf.crops_for_paper", _fake
        )

        _, warnings = build_export(
            [_record("Q1")], {"9231_s22_qp_41": str(source)}
        )

        assert len(warnings) == 1
        assert "乱码" in warnings[0]
        assert "整题区域" in warnings[0]

    def test_a_trimmed_paper_warns_about_nothing(
        self, _stub_crops: Path
    ) -> None:
        _, warnings = build_export(
            [_record("Q1")], {"9231_s22_qp_41": str(_stub_crops)}
        )

        assert warnings == []

    def test_one_page_per_main_question_across_papers(
        self, _stub_crops: Path
    ) -> None:
        """Sub-questions collapse into their parent before anything is cut."""
        records = [_record("Q1a"), _record("Q1b"), _record("Q3")]

        data, warnings = build_export(
            records, {"9231_s22_qp_41": str(_stub_crops)}
        )

        assert warnings == []
        assert len(PdfReader(io.BytesIO(data)).pages) == 2

    def test_every_paper_missing_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="没有可导出"):
            build_export([_record("Q1")], {"9231_s22_qp_41": ""})
