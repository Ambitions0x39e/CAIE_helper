"""Tests for ``modules.marking.syllabus_parser``.

Both syllabus families must be covered, because they are parsed by two
entirely separate branches and keep two different topic granularities
(math ``N.M``, science ``N``) — a green test on one proves nothing about
the other.

No real syllabus PDF is checked in. The fixtures are synthesised with fpdf2
(same approach as ``test_gt_parser.py``) to the *structure* the design doc
records for each family:

* math — a three-column ``Content section | Assessment component |
  Topics included`` table, including a topic cell that wraps onto a
  continuation line. It is built twice, because pdfminer reconstructs such a
  table one of two ways depending on how wide the column gaps are: as whole
  rows, or as one text box per column. The parser has to survive both;
* science — two flat numbered lists under category headings, plus the
  "should study topics 1-22" anchor sentence and the per-paper "based on the
  AS/A Level syllabus content" statements that resolve paper → level.

Ranges are written with an ASCII hyphen: fpdf2's core fonts are latin-1 and
cannot encode the en dash the real PDFs use. The parser accepts both.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fpdf import FPDF

from core.settings import app_settings
from modules.marking.syllabus_parser import (
    SyllabusParseError,
    parse_syllabus,
    parse_syllabus_text,
)

# ── Fixture builders ──────────────────────────────────────────────


def _lines_pdf(path: Path, pages: list[list[str]]) -> Path:
    """One text line per string, one page per inner list."""
    pdf = FPDF(unit="pt", format=(612, 792))
    pdf.set_auto_page_break(auto=False)
    pdf.set_font("Helvetica", size=9)
    for lines in pages:
        pdf.add_page()
        y = 60.0
        for line in lines:
            pdf.text(50, y, line)
            y += 14.0
    pdf.output(str(path))
    return path


def _placed_pdf(path: Path, cells: list[tuple[float, float, str]]) -> Path:
    """Draw each (x, y, text) at that exact spot — one page, no flowing."""
    pdf = FPDF(unit="pt", format=(612, 792))
    pdf.set_auto_page_break(auto=False)
    pdf.set_font("Helvetica", size=9)
    pdf.add_page()
    for x, y, text in cells:
        pdf.text(x, y, text)
    pdf.output(str(path))
    return path


# Column x offsets and row spacing copied from the real 9231 document's line
# boxes, so the fixture exercises the same geometry the parser was written
# against rather than a tidied-up version of it.
_SECTION_X = 62.4
_COMPONENT_X = 211.7
_TOPICS_X = 290.5
#: Where a cell's text restarts when its id extracted as its own fragment.
_TOPIC_TEXT_X = 340.0


def _real_shaped_math_pdf(path: Path) -> Path:
    """The math table as pdfminer actually reports it, traps included.

    Every awkward feature here was read off the real 9231 content-overview
    page (``697357-2026-2027-syllabus.pdf``), and each one broke the original
    text-based parser:

    * three columns whose cells are separate text lines sharing a baseline —
      no "section / component / topics" row ever forms;
    * a topic whose id and name extracted as two fragments on one baseline
      (``2.4`` / ``Integration``);
    * a topic whose name sits 2.6pt *above* its id's baseline, because a
      superscript raised the fragment's box — the name is nearer the id below
      it than the one it reads under;
    * a section title wrapping onto its own line in the first column
      (``Statistics``), which must not attach to a topic;
    * closing prose naming more papers than the table has rows;
    * a page number in the footer, inside the topics column's x range.
    """
    cells: list[tuple[float, float, str]] = [
        (_SECTION_X, 40, "Content overview"),
        (_SECTION_X, 60, "Content section"),
        (_COMPONENT_X, 60, "Assessment"),
        (_TOPICS_X, 60, "Topics included"),
        (_COMPONENT_X, 72, "component"),
        # ── Row 1 ──
        (_SECTION_X, 100, "1   Further Pure Mathematics 1"),
        (_COMPONENT_X, 100, "Paper 1"),
        (_TOPICS_X, 100, "1.1  Roots of polynomial equations"),
        (_TOPICS_X, 116, "1.2  Rational functions and graphs"),
        (_TOPICS_X, 132, "1.3  Summation of series"),
        # ── Row 2 ──
        (_SECTION_X, 160, "2  Further Pure Mathematics 2"),
        (_COMPONENT_X, 160, "Paper 2"),
        (_TOPICS_X, 160, "2.1  Hyperbolic functions"),
        # id and name as two fragments on one baseline
        (_TOPICS_X, 176, "2.2"),
        (_TOPIC_TEXT_X, 176, "Integration"),
        # ── Row 3 ──
        (_SECTION_X, 220, "3   Further Probability &"),
        (_COMPONENT_X, 220, "Paper 3"),
        (_TOPICS_X, 220, "3.1  Continuous random variables"),
        (_SECTION_X + 10, 236, "Statistics"),
        (_TOPICS_X, 236, "3.2"),
        (_TOPIC_TEXT_X, 236, "Inference using normal and t-distributions"),
        # Raised by 2.6pt above the id it belongs to, exactly as the real
        # superscript does.
        (_TOPIC_TEXT_X, 249.4, "chi2-tests"),
        (_TOPICS_X, 252, "3.3"),
        (_TOPICS_X, 268, "3.4  Non-parametric tests"),
        # ── Everything after the table ──
        (56.7, 400, "Paper 1 and Paper 3"),
        (56.7, 420, "Paper 1, 2 and 3"),
        (56.7, 440, "Candidates may not combine Paper 2 with Paper 3."),
        (569.9, 760, "9"),
    ]
    return _placed_pdf(path, cells)


_INDENT = " " * 46


def _math_pdf(path: Path) -> Path:
    """9709-style: a 3-column content-overview table, extracted row-major.

    Cells sit on one baseline close enough together that pdfminer keeps them
    in a single text line, so each row comes back as
    ``"1 Pure Mathematics 1  Paper 1  1.1 Quadratics, …"``. Assessment
    overview is on its own page, as in the real document.
    """
    overview = [
        "Content overview",
        "Content section        Assessment component   Topics included",
        "1 Pure Mathematics 1   Paper 1                "
        "1.1 Quadratics, 1.2 Functions,",
        # A wrapped topics cell — the continuation line carries no section
        # or component text at all.
        _INDENT + "1.3 Coordinate geometry, 1.4 Circular measure",
        "2 Pure Mathematics 2   Paper 2                "
        "2.1 Algebra, 2.2 Logarithmic and exponential functions",
        "3 Pure Mathematics 3   Paper 3                "
        "3.1 Algebra, 3.2 Complex numbers",
        "4 Mechanics            Paper 4                "
        "4.1 Forces and equilibrium,",
        _INDENT + "4.2 Kinematics of motion in a straight line",
        "5 Probability & Statistics 1  Paper 5          "
        "5.1 Representation of data, 5.2 Probability",
        "6 Probability & Statistics 2  Paper 6          "
        "6.1 The Poisson distribution, 6.2 Sampling",
    ]
    assessment = [
        "Assessment overview",
        "Paper 1 Pure Mathematics 1 1 hour 50 minutes 75 marks",
    ]
    return _lines_pdf(path, [overview, assessment])


def _math_column_major_pdf(path: Path) -> Path:
    """The same table, extracted column-major — no row ever forms.

    pdfminer does this whenever the column gaps are wide enough to split the
    table into per-column text boxes, which is why the parser cannot rely on
    row heads alone.
    """
    overview = [
        "Content overview",
        "Content section",
        "1 Pure Mathematics 1",
        "2 Pure Mathematics 2",
        "Assessment component",
        "Paper 1",
        "Paper 2",
        "Topics included",
        "1.1 Quadratics, 1.2 Functions",
        "2.1 Algebra, 2.2 Logarithmic and exponential functions",
    ]
    return _lines_pdf(path, [overview, ["Assessment overview"]])


_AS_TOPICS: list[tuple[str, str, str]] = [
    ("Physical chemistry", "1", "Atoms, molecules and stoichiometry"),
    ("Physical chemistry", "2", "Atomic structure"),
    ("Physical chemistry", "3", "Chemical bonding"),
    ("Physical chemistry", "4", "States of matter"),
    ("Physical chemistry", "5", "Chemical energetics"),
    ("Physical chemistry", "6", "Electrochemistry"),
    ("Physical chemistry", "7", "Equilibria"),
    ("Physical chemistry", "8", "Reaction kinetics"),
    ("Inorganic chemistry", "9", "The Periodic Table: chemical periodicity"),
    ("Inorganic chemistry", "10", "Group 2"),
    ("Inorganic chemistry", "11", "Group 17"),
    ("Inorganic chemistry", "12", "Nitrogen and sulfur"),
    ("Organic chemistry", "13", "An introduction to AS Level organic chemistry"),
    ("Organic chemistry", "14", "Hydrocarbons"),
    ("Organic chemistry", "15", "Halogen compounds"),
    ("Organic chemistry", "16", "Hydroxy compounds"),
    ("Organic chemistry", "17", "Carbonyl compounds"),
    ("Organic chemistry", "18", "Carboxylic acids and derivatives"),
    ("Organic chemistry", "19", "Nitrogen compounds"),
    ("Organic chemistry", "20", "Polymerisation"),
    ("Analysis", "21", "Organic synthesis"),
    ("Analysis", "22", "Analytical techniques"),
]

_A_TOPICS: list[tuple[str, str, str]] = [
    ("Physical chemistry", "23", "Chemical energetics"),
    ("Physical chemistry", "24", "Electrochemistry"),
    ("Physical chemistry", "25", "Equilibria"),
    ("Physical chemistry", "26", "Reaction kinetics"),
    ("Inorganic chemistry", "27", "Chemistry of transition elements"),
    ("Organic chemistry", "28", "An introduction to A Level organic chemistry"),
    ("Organic chemistry", "29", "Organic nitrogen compounds"),
    ("Analysis", "30", "Analytical techniques"),
]


def _content_lines(entries: list[tuple[str, str, str]]) -> list[str]:
    lines: list[str] = []
    current: str | None = None
    for category, topic_id, name in entries:
        if category != current:
            lines.append(category)
            current = category
        lines.append(f"{topic_id} {name}")
    return lines


def _science_pdf(path: Path) -> Path:
    """9701-style: two flat lists, an anchor sentence, per-paper statements."""
    toc = [
        "Contents",
        "1 Why choose this syllabus? ........................ 2",
        "2 Syllabus overview ................................ 6",
        "Content overview ................................... 8",
        "Assessment overview ................................ 9",
        "3 Subject content ................................. 12",
    ]
    overview = [
        "Content overview",
        "AS Level subject content",
        *_content_lines(_AS_TOPICS),
        "A Level subject content",
        *_content_lines(_A_TOPICS),
    ]
    assessment = [
        "Assessment overview",
        "Paper 1 Multiple Choice 1 hour 40 marks 31% of AS Level",
        "Paper 2 AS Level Structured Questions 1 hour 15 minutes 60 marks",
        "Paper 3 Advanced Practical Skills 2 hours 40 marks",
        "Paper 4 A Level Structured Questions 2 hours 100 marks",
        "Paper 5 Planning, Analysis and Evaluation 1 hour 15 minutes 30 marks",
    ]
    subject_content = [
        "3 Subject content",
        "Candidates for Cambridge International AS Level should study",
        "topics 1-22.",
        "Candidates for Cambridge International A Level should study all",
        "topics.",
    ]
    details = [
        "4 Details of the assessment",
        "Paper 1 Multiple Choice",
        "Written paper, 1 hour, 40 marks.",
        "All questions will be based on the AS Level syllabus content.",
        "Paper 2 AS Level Structured Questions",
        "Written paper, 1 hour 15 minutes, 60 marks.",
        "All questions will be based on the AS Level syllabus content.",
        "Paper 3 Advanced Practical Skills",
        "Practical paper, 2 hours, 40 marks.",
        "This paper assesses experimental skills, not content knowledge.",
        "Paper 4 A Level Structured Questions",
        "Written paper, 2 hours, 100 marks.",
        "All questions will be based on the A Level syllabus content.",
        "Paper 5 Planning, Analysis and Evaluation",
        "Written paper, 1 hour 15 minutes, 30 marks.",
        "This paper assesses experimental skills, not content knowledge.",
    ]
    return _lines_pdf(
        path, [toc, overview, assessment, subject_content, details]
    )


@pytest.fixture(autouse=True)
def _temp_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep every parse's cache inside tmp_path, never ~/.cie_helper."""
    monkeypatch.setattr(app_settings, "base_dir", tmp_path / "home")
    app_settings.syllabus_cache_dir.mkdir(parents=True, exist_ok=True)


# ── Math family ───────────────────────────────────────────────────


class TestMathFamily:
    def test_topics_parse_at_dotted_granularity(self, tmp_path: Path) -> None:
        info = parse_syllabus(_math_pdf(tmp_path / "9709.pdf"), "9709")

        assert info.subject_id == "9709"
        # N.M, not N — the math table's own depth is kept.
        assert all("." in tid for tid in info.topics)
        assert info.topics["1.1"].name == "Quadratics"
        assert info.topics["1.2"].name == "Functions"
        # Last topic of a row: its name must stop before the next row's head
        # ("… Circular measure 2 Pure Mathematics 2 Paper 2 …").
        assert info.topics["1.4"].name == "Circular measure"
        assert (
            info.topics["4.2"].name == "Kinematics of motion in a straight line"
        )
        assert info.topics["6.1"].name == "The Poisson distribution"
        assert info.topics["1.1"].category is None
        # 4 + 2 + 2 + 2 + 2 + 2 across the six content sections.
        assert len(info.topics) == 14

    def test_component_topics_map_each_paper_to_its_section(
        self, tmp_path: Path
    ) -> None:
        info = parse_syllabus(_math_pdf(tmp_path / "9709.pdf"), "9709")

        assert info.component_topics["1"] == ["1.1", "1.2", "1.3", "1.4"]
        assert info.component_topics["2"] == ["2.1", "2.2"]
        assert info.component_topics["4"] == ["4.1", "4.2"]
        assert info.component_topics["6"] == ["6.1", "6.2"]
        assert sorted(info.component_topics) == ["1", "2", "3", "4", "5", "6"]

    def test_a_note_mentioning_other_papers_does_not_shift_the_mapping(
        self,
    ) -> None:
        """The component cell is read from its own row, not counted off.

        A footnote under the table naming two more papers is what separates
        the two code paths: reading row heads is unaffected, while pairing
        section order against paper order would see four papers for two
        sections. On a table without such a note they agree, so this is the
        case that pins the row-head path down.
        """
        text = (
            "Content overview\n"
            "Content section     Assessment component   Topics included\n"
            "1 Pure Mathematics 1   Paper 1   1.1 Quadratics\n"
            "2 Pure Mathematics 2   Paper 2   2.1 Algebra\n"
            "Candidates may not combine Paper 4 with Paper 5.\n"
            "Assessment overview\n"
        )
        info = parse_syllabus_text(text, "9709")

        assert info.component_topics == {"1": ["1.1"], "2": ["2.1"]}

    def test_real_shaped_table_is_read_from_the_page_geometry(
        self, tmp_path: Path
    ) -> None:
        """The layout the real 9231 document actually extracts as.

        The text-based branch cannot read this one at all — that is the
        point of the geometry branch, and this is the case that proved it.
        """
        info = parse_syllabus(
            _real_shaped_math_pdf(tmp_path / "9231.pdf"), "9231"
        )

        assert info.topics["1.1"].name == "Roots of polynomial equations"
        # id and name arrived as two fragments on one baseline
        assert info.topics["2.2"].name == "Integration"
        # …and here the name sits *above* its id's baseline: 3.2 keeps the
        # name beside it, 3.3 takes the raised one, which is the pairing the
        # real document needs and the one reading order gets backwards.
        assert info.topics["3.2"].name == (
            "Inference using normal and t-distributions"
        )
        assert info.topics["3.3"].name == "chi2-tests"
        assert info.topics["3.4"].name == "Non-parametric tests"
        # The wrapped section title lives in another column entirely.
        assert "Statistics" not in info.topics["3.1"].name
        # The footer's page number shares the topics column's x range.
        assert info.topics["3.4"].name.strip().endswith("tests")
        assert not any(t.name.strip() == "9" for t in info.topics.values())

    def test_real_shaped_table_ignores_papers_named_after_it(
        self, tmp_path: Path
    ) -> None:
        """Prose below the table names more papers than the table has rows.

        Counting "Paper N" mentions in the flowed text finds 7 for 3 rows;
        only the ones sitting in the component column are components.
        """
        info = parse_syllabus(
            _real_shaped_math_pdf(tmp_path / "9231.pdf"), "9231"
        )

        assert info.component_topics == {
            "1": ["1.1", "1.2", "1.3"],
            "2": ["2.1", "2.2"],
            "3": ["3.1", "3.2", "3.3", "3.4"],
        }

    def test_column_major_extraction_still_maps_papers(
        self, tmp_path: Path
    ) -> None:
        """No row head survives, so sections and papers pair positionally."""
        info = parse_syllabus(
            _math_column_major_pdf(tmp_path / "9709col.pdf"), "9709"
        )

        assert info.topics["2.2"].name == (
            "Logarithmic and exponential functions"
        )
        assert info.component_topics == {
            "1": ["1.1", "1.2"],
            "2": ["2.1", "2.2"],
        }


# ── Science family ────────────────────────────────────────────────


class TestScienceFamily:
    def test_topics_parse_at_flat_granularity_with_categories(
        self, tmp_path: Path
    ) -> None:
        info = parse_syllabus(_science_pdf(tmp_path / "9701.pdf"), "9701")

        assert info.subject_id == "9701"
        # N, not N.M — the flat list's own depth is kept.
        assert all("." not in tid for tid in info.topics)
        assert len(info.topics) == 30
        assert info.topics["3"].name == "Chemical bonding"
        assert info.topics["3"].category == "Physical chemistry"
        assert info.topics["14"].category == "Organic chemistry"
        assert info.topics["9"].name == (
            "The Periodic Table: chemical periodicity"
        )
        # The A Level list restarts its categories after its own heading.
        assert info.topics["27"].category == "Inorganic chemistry"
        assert info.topics["30"].name == "Analytical techniques"

    def test_component_topics_split_as_from_a_level(
        self, tmp_path: Path
    ) -> None:
        info = parse_syllabus(_science_pdf(tmp_path / "9701.pdf"), "9701")

        as_ids = [str(i) for i in range(1, 23)]
        assert info.component_topics["1"] == as_ids
        assert info.component_topics["2"] == as_ids
        # "should study all topics" — the A Level papers get 1..30.
        assert info.component_topics["4"] == [str(i) for i in range(1, 31)]
        # Practical papers state no syllabus content: no mapping at all,
        # which the caller treats the same as "no syllabus".
        assert "3" not in info.component_topics
        assert "5" not in info.component_topics


# ── Shared behaviour ──────────────────────────────────────────────


def test_unrecognised_pdf_raises(tmp_path: Path) -> None:
    path = _lines_pdf(tmp_path / "random.pdf", [[
        "Cambridge International AS & A Level",
        "This document is not a syllabus at all.",
    ]])
    with pytest.raises(SyllabusParseError):
        parse_syllabus(path, "9999")


def test_content_overview_in_the_table_of_contents_is_skipped() -> None:
    """The heading appears twice; only the real section carries topics."""
    text = (
        "Contents\n"
        "Content overview ..... 8\n"
        "Assessment overview ..... 9\n"
        "Content overview\n"
        "AS Level subject content\n"
        "Physical chemistry\n"
        "1 Atoms, molecules and stoichiometry\n"
        "2 Atomic structure\n"
        "Assessment overview\n"
        "Candidates for Cambridge International AS Level should study "
        "topics 1-2.\n"
        "Paper 2 AS Level Structured Questions\n"
        "All questions will be based on the AS Level syllabus content.\n"
    )
    info = parse_syllabus_text(text, "9701")

    assert sorted(info.topics) == ["1", "2"]
    assert info.component_topics["2"] == ["1", "2"]


def test_second_parse_comes_from_the_cache(tmp_path: Path) -> None:
    pdf = _math_pdf(tmp_path / "9709.pdf")
    first = parse_syllabus(pdf, "9709")
    pdf.unlink()

    assert parse_syllabus(pdf, "9709") == first
