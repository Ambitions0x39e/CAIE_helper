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
from pypdf import PdfReader

from core.models import MistakeRecord
from modules.marking.mistake_pdf import (
    Band,
    QuestionCrop,
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


def _paper_pdf(path: Path) -> Path:
    """A page shaped like a real one: stem, ruled table, then answer space."""
    pdf = FPDF(unit="pt", format=(_PAGE_W, _PAGE_H))
    pdf.set_auto_page_break(auto=False)
    pdf.set_font("Helvetica", size=10)
    pdf.add_page()
    pdf.text(36, 36, "8")                       # page number, above the region
    pdf.text(62, 60, "4  A scientist is investigating butterflies.")
    pdf.text(62, 74, "The table shows the observed frequencies.")
    pdf.rect(104, 100, 420, 40)                 # the table: graphics, not text
    pdf.text(62, 170, "(a)  Find the values of p and q.")
    for i in range(10):                         # answer space
        pdf.text(62, 195 + i * 24, "." * 90)
    pdf.text(62, 450, "(b)  Carry out a goodness of fit test.")
    for i in range(8):
        pdf.text(62, 475 + i * 24, "." * 90)
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
        assert x > 40           # the margin bar at x26-45 is outside
        assert width < _PAGE_W  # and so is whatever sits down the right

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
