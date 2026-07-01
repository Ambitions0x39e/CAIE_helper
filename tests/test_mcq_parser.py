"""Tests for modules.mcq_parser skip-page resolution."""
from __future__ import annotations

from pathlib import Path

from modules.mcq_parser import (
    _extract_paper_id,
    _parse_paper_filename,
    _resolve_skip_pages,
    is_valid_manual_answer,
)


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
