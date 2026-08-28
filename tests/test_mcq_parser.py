"""Tests for modules.marking.mcq_parser skip-page resolution."""
from __future__ import annotations

from pathlib import Path

import pytest
from fpdf import FPDF

from modules.marking.mcq_parser import (
    _extract_paper_id,
    _parse_paper_filename,
    _resolve_skip_pages,
    is_valid_manual_answer,
    parse_mcq_mark_scheme,
)

ANSWER_CYCLE = "BDAC"


def test_parse_paper_filename_matches_qp() -> None:
    assert _parse_paper_filename("9702_s25_qp_11") == ("9702", "s", "25", "11")


def test_parse_paper_filename_matches_ms() -> None:
    assert _parse_paper_filename("9702_s25_ms_11") == ("9702", "s", "25", "11")


def test_parse_paper_filename_returns_none_when_unparseable() -> None:
    assert _parse_paper_filename("tmpAbC123xyz") is None


def test_extract_paper_id_formats_session() -> None:
    assert _extract_paper_id(Path("9702_s25_ms_11.pdf")) == "9702/11/M/J/25"


def test_extract_paper_id_falls_back_to_stem_when_unparseable() -> None:
    assert _extract_paper_id(Path("tmpAbC123xyz.pdf")) == "tmpAbC123xyz"


def test_is_valid_manual_answer_rejects_empty_string() -> None:
    """`"" in "ABCD"` is True in Python (substring semantics) — an untouched
    text_input defaulting to "" must not be accepted as a valid answer."""
    assert is_valid_manual_answer("") is False


def test_is_valid_manual_answer_accepts_valid_letters() -> None:
    assert all(is_valid_manual_answer(letter) for letter in "ABCD")


def test_is_valid_manual_answer_rejects_other_input() -> None:
    assert is_valid_manual_answer("E") is False
    assert is_valid_manual_answer("AB") is False


def test_resolve_skip_pages_uses_subject_specific_config() -> None:
    """A parseable '<subject>_<season><year>_qp_<component>' stem looks up
    the real per-subject config (9702 Paper 1x skips cover + data sheet)."""
    assert _resolve_skip_pages("9702_s25_qp_11") == {0, 1}


def test_resolve_skip_pages_falls_back_to_json_default_when_unparseable() -> None:
    """An unparseable stem (e.g. a random tempfile name) must fall back to
    paper_page_config.json's own "default" entry — not a second, separately
    hardcoded value that could silently disagree with it."""
    assert _resolve_skip_pages("tmpAbC123xyz") == {0}


# ── mark-scheme table parsing ─────────────────────────────────


def _make_ms_pdf(
    rows: list[tuple[str, str]],
    *,
    with_marks_column: bool = True,
    rows_per_page: int = 28,
) -> bytes:
    """Build a synthetic MCQ mark scheme laid out like the real CIE PDFs.

    Each column is drawn top-to-bottom in full before the next one starts,
    which is what makes pdfminer emit the table column-major — the layout
    that broke the old adjacent-lines parser.
    """
    pdf = FPDF(unit="pt", format=(595, 842))
    pdf.set_auto_page_break(auto=False)
    for start in range(0, len(rows), rows_per_page):
        chunk = rows[start : start + rows_per_page]
        pdf.add_page()
        pdf.set_font("Helvetica", size=10.8)
        pdf.text(80, 120, "Question")
        pdf.text(294, 120, "Answer")
        pdf.text(500, 120, "Marks")
        for col_x, values in (
            (99, [q for q, _ in chunk]),
            (137, [a for _, a in chunk]),
            *([(505, ["1"] * len(chunk))] if with_marks_column else []),
        ):
            for i, value in enumerate(values):
                pdf.text(col_x, 150 + i * 23, value)
    return bytes(pdf.output())


def _write_ms(tmp_path: Path, name: str, pdf_bytes: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(pdf_bytes)
    return path


def test_parse_mcq_mark_scheme_reads_column_major_table(tmp_path: Path) -> None:
    """CIE MCQ mark schemes emit each table column as one run of text, so the
    question numbers all arrive before any answer letter. Rows must be
    reconstructed from geometry, not from line adjacency."""
    answers = [ANSWER_CYCLE[i % 4] for i in range(40)]
    rows = [(str(i + 1), answers[i]) for i in range(40)]
    path = _write_ms(tmp_path, "9702_s25_ms_14.pdf", _make_ms_pdf(rows))

    config = parse_mcq_mark_scheme(path)

    assert len(config.questions) == 40
    assert config.total_marks == 40
    assert [q.mark_scheme for q in config.questions.values()] == answers


def test_parse_mcq_mark_scheme_ignores_marks_column(tmp_path: Path) -> None:
    """The Marks column is a third run of bare digits ("1" per row); it must
    not be mistaken for question numbers."""
    rows = [(str(i + 1), "C") for i in range(30)]
    path = _write_ms(tmp_path, "9702_s25_ms_11.pdf", _make_ms_pdf(rows))

    config = parse_mcq_mark_scheme(path)

    assert list(config.questions) == [f"Q{i + 1}" for i in range(30)]


def test_parse_mcq_mark_scheme_rejects_gappy_table(tmp_path: Path) -> None:
    """A table missing rows means the layout was misread — a partial answer
    key silently marks the student wrong, so refuse it."""
    rows = [(str(i + 1), "A") for i in range(10) if i != 4]
    path = _write_ms(tmp_path, "9702_s25_ms_11.pdf", _make_ms_pdf(rows))

    with pytest.raises(ValueError, match="5"):
        parse_mcq_mark_scheme(path)


def test_parse_mcq_mark_scheme_raises_when_no_table(tmp_path: Path) -> None:
    pdf = FPDF(unit="pt", format=(595, 842))
    pdf.add_page()
    pdf.set_font("Helvetica", size=10.8)
    pdf.text(80, 120, "This mark scheme is published as an aid to teachers.")
    path = _write_ms(tmp_path, "9702_s25_ms_21.pdf", bytes(pdf.output()))

    with pytest.raises(ValueError, match="No MCQ answers"):
        parse_mcq_mark_scheme(path)
