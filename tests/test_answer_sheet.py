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
    _SYMBOL_BYTE,
    _TEXT_W,
    build_answer_sheet,
    ms_paths_by_paper,
    normalise,
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


# ── Notation ──────────────────────────────────────────────────────


class TestNormalise:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("x²", "x^2"),
            ("x²y³", "x^2y^3"),
            ("u₂ₙ", "u_(2n)"),
            ("a₁₀", "a_(10)"),
            ("10⁻³", "10^(-3)"),
            ("−3", "-3"),
            ("don’t", "don't"),
            ("• first", "-  first"),
        ],
    )
    def test_notation_becomes_the_ascii_the_rest_already_uses(
        self, raw: str, expected: str
    ) -> None:
        assert normalise(raw) == expected

    def test_greek_is_left_alone(self) -> None:
        """It is not rewritten because Symbol can draw it — see the font
        split. Spelling it "theta" would be a worse sheet."""
        assert normalise("cos θ") == "cos θ"


# ── The font split ────────────────────────────────────────────────


class TestFontSplit:
    def _runs(self, text: str) -> list[tuple[bool, str]]:
        lines = wrap(text, 10.0, False, _TEXT_W)
        return [(run.symbol, run.text) for run in lines[0]]

    def test_greek_goes_to_symbol_and_the_rest_to_helvetica(self) -> None:
        runs = self._runs("cos θ")

        assert [symbol for symbol, _ in runs] == [False, True]
        assert runs[0][1] == "cos "
        # Symbol puts theta where Helvetica puts "q".
        assert runs[1][1] == chr(_SYMBOL_BYTE["θ"])

    def test_neighbouring_characters_of_one_font_become_one_run(self) -> None:
        """One Tj per run, so this is what keeps the content stream from
        being one operator per character."""
        assert len(self._runs("hello")) == 1

    def test_a_character_no_font_has_is_visible_rather_than_dropped(
        self,
    ) -> None:
        """A silently dropped operator changes what an answer says."""
        runs = self._runs("答案")

        assert runs == [(False, "??")]


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
        assert "9r^2 - 21r + 10" in text          # Q1a, for context
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

    def test_the_score_marks_the_parts_marks_were_lost_on(
        self, ms_cache: Path, tmp_path: Path
    ) -> None:
        data, _ = build_answer_sheet(
            [_record("Q1b", score=1.0)], {_PAPER: "9231_s25_ms_11.pdf"}
        )

        text = _text(data, tmp_path)
        assert "scored 1/4" in text

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
