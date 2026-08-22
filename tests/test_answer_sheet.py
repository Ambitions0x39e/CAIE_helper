"""Tests for ``modules.marking.answer_sheet`` — the 错题本's answer export.

The sheet is typeset by hand into base-14 PDF fonts, so the things that can
break are: the font split (Greek has to land in Symbol, everything else in
Helvetica), the notation rewrite, the wrapping arithmetic, and the promise
that nothing here ever parses a mark scheme. Each gets its own layer.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pypdf import PdfReader

from core.models import MistakeRecord
from modules.marking.answer_sheet import (
    _ASCII_MATHS,
    _TEXT_W,
    atoms,
    build_answer_sheet,
    line_height,
    ms_paths_by_paper,
    wrap,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

_TS = datetime.datetime(2026, 8, 22, 12, 0, 0)
_PAPER = "9231_s25_qp_11"


def _record(question_id: str, score: float = 1.0) -> MistakeRecord:
    return MistakeRecord(
        paper_id=_PAPER,
        question_id=question_id,
        topic_id=None,
        topic_name=None,
        score=score,
        max_score=4.0,
        comment="",
        timestamp=_TS,
    )


@pytest.fixture
def ms_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point the mark-scheme cache at a temp dir and fill it."""
    from core.settings import app_settings

    cache = tmp_path / "ms"
    cache.mkdir()
    monkeypatch.setattr(
        type(app_settings), "ms_cache_dir",
        property(lambda _self: cache),
    )
    (cache / "9231_s25_ms_11.sp4.json").write_text(json.dumps({
        "paper_id": "9231/11/M/J/25",
        "total_marks": 75,
        "questions": {
            "Q1a": {"max_marks": 3, "mark_scheme": "B1: 9r^2 - 21r + 10"},
            "Q1b": {"max_marks": 4, "mark_scheme": "M1: Σ(r=1 to n) = -1/6"},
            "Q2a": {"max_marks": 2, "mark_scheme": "A1: cos θ - sin θ = 0"},
        },
    }), "utf-8")
    yield cache


def _text(data: bytes, tmp_path: Path) -> str:
    out = tmp_path / "sheet.pdf"
    out.write_bytes(data)
    return "\n".join(page.extract_text() for page in PdfReader(str(out)).pages)


# ── Maths layout ──────────────────────────────────────────────────


def _shape(text: str, size: float = 10.0) -> list[tuple[str, float, float]]:
    """(character, size, rise) for each laid-out atom."""
    return [
        (atom.char, round(atom.size, 2), round(atom.rise, 2))
        for atom in atoms(text, size)
    ]


class TestAtoms:
    def test_a_caret_raises_the_next_character_instead_of_printing(
        self,
    ) -> None:
        """"θ^2" is theta squared. Printed flat it says "theta caret two",
        which is what made these sheets painful to read."""
        assert _shape("x^2") == [("x", 10.0, 0.0), ("2", 7.2, 4.2)]

    def test_an_underscore_lowers_it(self) -> None:
        assert _shape("u_n") == [("u", 10.0, 0.0), ("n", 7.2, -2.0)]

    def test_a_bracketed_group_loses_its_brackets(self) -> None:
        """"e^(¼θ)" means e to the ¼θ; once the ¼θ is actually raised the
        brackets say nothing."""
        assert [char for char, _, _ in _shape("e^(ab)")] == ["e", "a", "b"]

    def test_a_bare_number_is_taken_whole(self) -> None:
        """"10^12", not ten to the one followed by a two."""
        assert [rise for _, _, rise in _shape("10^12")] == [0, 0, 4.2, 4.2]

    def test_a_signed_exponent_keeps_its_sign_up_there(self) -> None:
        assert [char for char, _, _ in _shape("e^-3")] == ["e", "-", "3"]

    def test_a_greek_letter_rides_along_with_its_coefficient(self) -> None:
        """The limit in "∫_0^2π" is 2π, not 2 with a stray π after it."""
        raised = [char for char, _, rise in _shape("∫_0^2π") if rise > 0]

        assert raised == ["2", "π"]

    def test_only_one_letter_follows_a_caret(self) -> None:
        """No run rule for letters: "e^ax" is e-to-the-a times x as often as
        not, and the measured mark schemes never write a letter run."""
        assert [rise for _, _, rise in _shape("e^ax")] == [0, 4.2, 0]

    def test_nesting_shrinks_but_not_past_the_floor(self) -> None:
        sizes = {size for _, size, _ in _shape("a^(b^(c^(d^e)))")}

        assert min(sizes) >= 10.0 * 0.5

    def test_unicode_superscripts_are_set_raised_not_rewritten(self) -> None:
        """"x²" is already a raised two; it should look like one rather than
        turn into "x^2"."""
        assert _shape("x²") == [("x", 10.0, 0.0), ("2", 7.2, 4.2)]

    def test_a_run_of_unicode_subscripts_stays_together(self) -> None:
        """"u₂ₙ" is u sub 2n — both characters down, no separator."""
        assert _shape("u₂ₙ") == [
            ("u", 10.0, 0.0), ("2", 7.2, -2.0), ("n", 7.2, -2.0),
        ]

    def test_punctuation_is_still_rewritten(self) -> None:
        assert [char for char, _, _ in _shape("−3")] == ["-", "3"]

    def test_every_rewrite_lands_in_a_character_the_font_can_draw(
        self,
    ) -> None:
        """The sheet is set in base-14 fonts encoded as Latin-1, so a
        rewrite that produces anything else silently becomes "?"."""
        for source, target in _ASCII_MATHS.items():
            target.encode("latin-1")   # raises if it cannot be drawn
            assert source != target


    def test_a_heading_is_not_read_as_maths(self) -> None:
        """A paper id is "9231_s25_qp_11". Read as maths it comes out as
        9231 with a subscript s, then 25, then a subscript q — which is
        exactly how the first interleaved export printed it."""
        laid = atoms("9231_s25_qp_11", 10.0, math=False)

        assert "".join(a.char for a in laid) == "9231_s25_qp_11"
        assert all(a.rise == 0.0 for a in laid)


class TestLineHeight:
    def test_a_line_with_scripts_is_given_more_room(self) -> None:
        """Or the raised characters collide with the line above."""
        plain = wrap("plain text", 9.5, False, _TEXT_W)[0]
        scripted = wrap("x^2 and u_n", 9.5, False, _TEXT_W)[0]

        assert line_height(scripted, 9.5) > line_height(plain, 9.5)


# ── Wrapping ──────────────────────────────────────────────────────


class TestWrap:
    def test_a_long_line_is_broken_into_several(self) -> None:
        lines = wrap("word " * 200, 9.5, False, _TEXT_W)

        assert len(lines) > 1

    def test_every_line_fits_the_column(self) -> None:
        lines = wrap("word " * 200, 9.5, False, _TEXT_W)

        assert all(
            sum(run.width for run in line) <= _TEXT_W for line in lines
        )

    def test_newlines_in_the_mark_scheme_start_new_lines(self) -> None:
        """Mark schemes are written one mark point per line and that
        structure is the whole readability of them."""
        lines = wrap("B1: one\nM1: two\nA1: three", 9.5, False, _TEXT_W)

        assert len(lines) == 3

    def test_a_word_wider_than_the_column_is_not_broken(self) -> None:
        """Hyphenating "3n^3-6n^2+n" would change what it says."""
        lines = wrap("x" * 400, 9.5, False, _TEXT_W)

        assert len(lines) == 1


# ── The whole sheet ───────────────────────────────────────────────


class TestBuildAnswerSheet:
    def test_the_answers_are_in_the_pdf(
        self, ms_cache: Path, tmp_path: Path
    ) -> None:
        data, warnings = build_answer_sheet(
            [_record("Q1b")], {_PAPER: "9231_s25_ms_11.pdf"}
        )

        assert warnings == []
        text = _text(data, tmp_path)
        assert "9r2 - 21r + 10" in text     # Q1a, its 2 now raised
        assert "-1/6" in text                     # Q1b, the one asked for

    def test_a_whole_main_question_comes_along(
        self, ms_cache: Path, tmp_path: Path
    ) -> None:
        """A sub-question read without its siblings usually makes no
        sense, so Q1a rides along with Q1b — and Q2 stays out."""
        data, _ = build_answer_sheet(
            [_record("Q1b")], {_PAPER: "9231_s25_ms_11.pdf"}
        )

        text = _text(data, tmp_path)
        assert "Q1a" in text
        assert "Q2a" not in text

    def test_the_first_attempt_score_is_not_on_the_sheet(
        self, ms_cache: Path, tmp_path: Path
    ) -> None:
        """This is the answer to redo against; the old marks belong in the
        错题本, not on it."""
        data, _ = build_answer_sheet(
            [_record("Q1b", score=1.0)], {_PAPER: "9231_s25_ms_11.pdf"}
        )

        assert "scored" not in _text(data, tmp_path)

    def test_the_exponent_really_is_raised_in_the_output(
        self, ms_cache: Path, tmp_path: Path
    ) -> None:
        """End to end, not just in the layout: text extraction reads "9r2"
        either way, so the proof has to be the Ts operator in the content
        stream — that is what sets a character above the baseline."""
        import re

        data, _ = build_answer_sheet(
            [_record("Q1a")], {_PAPER: "9231_s25_ms_11.pdf"}
        )
        out = tmp_path / "sheet.pdf"
        out.write_bytes(data)
        stream = PdfReader(str(out)).pages[0].get_contents().get_data()

        rises = [
            float(m) for m in
            re.findall(rb"(-?[\d.]+) Ts", stream)
        ]
        assert any(rise > 0 for rise in rises)

    def test_greek_survives_the_round_trip(
        self, ms_cache: Path, tmp_path: Path
    ) -> None:
        """The proof that the Symbol font is wired up: extraction reads the
        glyph back as θ, which it cannot do if the byte went out in
        Helvetica."""
        data, _ = build_answer_sheet(
            [_record("Q2a")], {_PAPER: "9231_s25_ms_11.pdf"}
        )

        assert "θ" in _text(data, tmp_path)

    def test_an_unparsed_paper_is_named_not_parsed(
        self, ms_cache: Path
    ) -> None:
        """Never a silent re-parse: that one costs money and minutes."""
        with pytest.raises(ValueError, match="没有可导出"):
            build_answer_sheet(
                [_record("Q1b")], {_PAPER: "9709_s25_ms_12.pdf"}
            )

    def test_a_question_the_parse_does_not_cover_is_reported(
        self, ms_cache: Path
    ) -> None:
        _, warnings = build_answer_sheet(
            [_record("Q1b"), _record("Q9a")],
            {_PAPER: "9231_s25_ms_11.pdf"},
        )

        assert any("Q9" in w for w in warnings)


def test_ms_paths_by_paper_splits_parsed_from_unparsed(
    ms_cache: Path,
) -> None:
    """So the UI can say what will be missing before the file dialog
    opens, rather than after."""
    found, missing = ms_paths_by_paper(
        [_record("Q1b"), MistakeRecord(
            paper_id="9709_s25_qp_12", question_id="Q1",
            topic_id=None, topic_name=None, score=0.0, max_score=3.0,
            comment="", timestamp=_TS,
        )],
        {_PAPER: "9231_s25_ms_11.pdf", "9709_s25_qp_12": "9709_s25_ms_12.pdf"},
    )

    assert list(found) == [_PAPER]
    assert missing == ["9709_s25_qp_12"]
