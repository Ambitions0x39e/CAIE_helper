"""Tests for core.gt_parser's pdfminer-based table reconstruction.

The parser used to lean on pdfplumber's ``extract_tables()``. It now rebuilds
tables from the ruling lines CIE actually draws, so these synthesise ruled
PDFs and check the grid comes back with the right cells — in particular the
two failure modes the port had to fix:

* two tables on one page, whose column positions must not be pooled
  (that sliced "250" into "25" + "0"), and
* multi-line cells, whose glyphs must not interleave
  ("Combination of / components" → "Ccoommbpinoanteionnt so f").
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fpdf import FPDF

from core.gt_parser import (
    GradeThreshold,
    GTParser,
    _cid_to_char,
    _decode,
    _extract_tables,
)

_GRADES = ["A*", "A", "B", "C", "D", "E"]


def _ruled_pdf(
    path: Path,
    tables: list[tuple[float, list[list[str]], list[float]]],
) -> Path:
    """Draw ruled tables. Each entry is (top_y, rows, column x-positions)."""
    pdf = FPDF(unit="pt", format=(612, 792))
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()
    pdf.set_font("Helvetica", size=8)
    # Tall enough for the 3-line header cell to fit inside its own row band —
    # otherwise its last line spills into the row below and corrupts it.
    row_h = 36.0
    line_h = 9.0

    for top, rows, xs in tables:
        height = row_h * len(rows)
        # Column separators (full height) and row separators (full width).
        for x in xs:
            pdf.rect(x, top, 0.7, height, style="F")
        for i in range(len(rows) + 1):
            pdf.rect(xs[0], top + i * row_h, xs[-1] - xs[0], 0.7, style="F")
        for r, row in enumerate(rows):
            for c, cell in enumerate(row):
                for ln, part in enumerate(cell.split("\n")):
                    pdf.text(
                        xs[c] + 2,
                        top + r * row_h + 9 + ln * line_h,
                        part,
                    )

    pdf.output(str(path))
    return path


def _options_rows() -> list[list[str]]:
    return [
        ["Option", "Maximum\nmark after\nweighting",
         "Combination of\ncomponents", *_GRADES],
        ["AC", "250", "14, 24, 34, 44", "226", "203", "167", "142", "117", "92"],
        ["AX", "250", "11, 21, 31, 41", "210", "175", "140", "117", "94", "71"],
    ]


_COLS = [60.0, 110.0, 175.0, 265.0, 300.0, 335.0, 370.0, 405.0, 440.0, 475.0]


class TestCidDecoding:
    """The PDFs carry no character map, so glyph ids are decoded by rule.

    CIE embeds Arial as an Identity-H subset with the font's own cmap
    stripped, leaving pdfminer to emit "(cid:N)". Those N are standard
    Macintosh TrueType glyph ids, whose entries 3..97 are printable ASCII.
    """

    @pytest.mark.parametrize(
        ("gid", "char"),
        [
            (3, " "), (15, ","), (16, "-"), (19, "0"), (20, "1"),
            (22, "3"), (28, "9"), (29, ":"), (36, "A"), (49, "N"),
            (61, "Z"), (68, "a"), (97, "~"),
        ],
    )
    def test_standard_glyph_ids(self, gid: int, char: str) -> None:
        assert _cid_to_char(gid) == char

    def test_unknown_id_yields_nothing(self) -> None:
        assert _cid_to_char(0) == ""
        assert _cid_to_char(9999) == ""

    def test_decode_resolves_escapes_in_place(self) -> None:
        # "103" — the digit that the old hand-built table dropped, turning
        # this threshold into "10".
        assert _decode("(cid:20)(cid:19)(cid:22)") == "103"
        assert _decode("A(cid:15) B") == "A, B"

    def test_decode_handles_empty(self) -> None:
        assert _decode(None) == ""
        assert _decode("") == ""


class TestThresholdSanity:
    def _threshold(self, **thresholds: int) -> GradeThreshold:
        return GradeThreshold(
            option="AX", max_weighted=250,
            components=["11"], thresholds=thresholds,
        )

    def test_accepts_a_descending_row(self) -> None:
        row = self._threshold(**{"A*": 226, "A": 203, "B": 167})
        assert row.thresholds["A"] == 203

    def test_rejects_an_inverted_row(self) -> None:
        # D below E is what a dropped digit looks like (103 -> 10).
        with pytest.raises(ValueError, match="is below"):
            self._threshold(**{"C": 127, "D": 10, "E": 80})

    def test_allows_ties(self) -> None:
        row = self._threshold(**{"B": 150, "C": 150})
        assert row.thresholds["C"] == 150

    def test_rejects_a_threshold_above_the_maximum(self) -> None:
        with pytest.raises(ValueError, match="above the paper maximum"):
            self._threshold(**{"A*": 260})


class TestExtractTables:
    def test_reads_a_simple_ruled_table(self, tmp_path: Path) -> None:
        pdf = _ruled_pdf(
            tmp_path / "one.pdf", [(600.0, _options_rows(), _COLS)],
        )
        grids = _extract_tables(pdf)
        assert len(grids) == 1

        grid = grids[0]
        assert grid[0][0] == "Option"
        assert grid[1][0] == "AC"
        # The whole number, not a fragment — this is the "250" → "25"+"0" bug.
        assert grid[1][1] == "250"
        assert grid[1][2] == "14, 24, 34, 44"
        assert grid[1][3:] == ["226", "203", "167", "142", "117", "92"]

    def test_multi_line_cell_keeps_its_lines_in_order(
        self, tmp_path: Path,
    ) -> None:
        pdf = _ruled_pdf(
            tmp_path / "wrap.pdf", [(600.0, _options_rows(), _COLS)],
        )
        header = _extract_tables(pdf)[0][0]
        # Sorting purely left-to-right would interleave the two printed lines.
        assert header[2] == "Combination of\ncomponents"
        assert header[1] == "Maximum\nmark after\nweighting"

    def test_two_tables_on_one_page_keep_separate_columns(
        self, tmp_path: Path,
    ) -> None:
        # Second table's columns sit between the first's — pooling the two
        # sets of verticals would chop the first table's cells apart.
        other_cols = [80.0, 150.0, 240.0, 320.0]
        other = [["H1", "H2", "H3"], ["v1", "v2", "v3"]]
        pdf = _ruled_pdf(
            tmp_path / "two.pdf",
            [(400.0, _options_rows(), _COLS), (620.0, other, other_cols)],
        )
        grids = _extract_tables(pdf)
        assert len(grids) == 2

        by_width = {len(g[0]): g for g in grids}
        assert by_width[9][1][1] == "250"      # options table intact
        assert by_width[3][1] == ["v1", "v2", "v3"]


class TestGTParser:
    def test_parses_options_into_thresholds(self, tmp_path: Path) -> None:
        pdf = _ruled_pdf(
            tmp_path / "9701_s25_gt.pdf",
            [(400.0, _options_rows(), _COLS)],
        )
        doc = GTParser().parse(pdf, "s25")

        assert doc.syllabus_id == "9701"
        assert doc.session == "s25"
        assert doc.option_codes == ["AC", "AX"]

        ac = doc.get_option("AC")
        assert ac is not None
        assert ac.max_weighted == 250
        assert ac.components == ["14", "24", "34", "44"]
        assert ac.thresholds == {
            "A*": 226, "A": 203, "B": 167, "C": 142, "D": 117, "E": 92,
        }

    def test_grade_for_score_walks_down_from_the_top(
        self, tmp_path: Path,
    ) -> None:
        pdf = _ruled_pdf(
            tmp_path / "9701_s25_gt.pdf",
            [(400.0, _options_rows(), _COLS)],
        )
        ac = GTParser().parse(pdf, "s25").get_option("AC")
        assert ac is not None
        assert ac.grade_for_score(230) == "A*"
        assert ac.grade_for_score(226) == "A*"   # exactly on the boundary
        assert ac.grade_for_score(225) == "A"
        assert ac.grade_for_score(92) == "E"
        assert ac.grade_for_score(91) == "U"

    def test_rejects_a_row_whose_thresholds_invert(
        self, tmp_path: Path,
    ) -> None:
        # D below E is the fingerprint of a dropped digit (103 read as 10);
        # the row is skipped rather than reported as a real boundary.
        rows = _options_rows()
        rows.append(
            ["BAD", "250", "11, 21", "226", "203", "167", "142", "10", "92"],
        )
        pdf = _ruled_pdf(tmp_path / "9701_s25_gt.pdf", [(400.0, rows, _COLS)])
        assert GTParser().parse(pdf, "s25").option_codes == ["AC", "AX"]

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            GTParser().parse(tmp_path / "nope.pdf", "s25")

    def test_pdf_without_an_options_table_is_rejected(
        self, tmp_path: Path,
    ) -> None:
        pdf = _ruled_pdf(
            tmp_path / "9701_s25_gt.pdf",
            [(600.0, [["H1", "H2"], ["a", "b"]], [60.0, 150.0, 240.0])],
        )
        with pytest.raises(ValueError, match="No option rows found"):
            GTParser().parse(pdf, "s25")
