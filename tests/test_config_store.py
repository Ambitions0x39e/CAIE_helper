"""Tests for core.config_store's paper-page-config loader."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.config_store import (
    grading_type_for_paper,
    qp_skip_pages,
)
from core.models import PaperType


def test_qp_skip_pages_raises_on_malformed_json(tmp_path: Path) -> None:
    """Malformed JSON must raise, like ConfigStore.load_all() does for
    syllabus_config.json — not silently fall back to defaults."""
    bad_config = tmp_path / "paper_page_config.json"
    bad_config.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ValueError, match="not valid JSON"):
        qp_skip_pages("9702", "11", config_path=bad_config)


def test_qp_skip_pages_falls_back_to_default_entry(tmp_path: Path) -> None:
    config_path = tmp_path / "paper_page_config.json"
    config_path.write_text(
        json.dumps({"default": {"qp_skip_pages": [0]}}),
        encoding="utf-8",
    )
    assert qp_skip_pages("9999", "1", config_path=config_path) == {0}


def test_qp_skip_pages_uses_component_specific_entry(tmp_path: Path) -> None:
    config_path = tmp_path / "paper_page_config.json"
    config_path.write_text(
        json.dumps({
            "default": {"qp_skip_pages": [0]},
            "9702": {"1": {"qp_skip_pages": [0, 1]}},
        }),
        encoding="utf-8",
    )
    assert qp_skip_pages("9702", "11", config_path=config_path) == {0, 1}


def test_qp_skip_pages_uses_subject_level_default(tmp_path: Path) -> None:
    """A subject's own "_default" entry must win over the top-level default,
    letting components with no component-specific override still inherit
    the subject's convention instead of falling all the way through."""
    config_path = tmp_path / "paper_page_config.json"
    config_path.write_text(
        json.dumps({
            "default": {"qp_skip_pages": [0]},
            "9709": {"_default": {"qp_skip_pages": [0, 1]}},
        }),
        encoding="utf-8",
    )
    assert qp_skip_pages("9709", "61", config_path=config_path) == {0, 1}


@pytest.mark.parametrize(
    ("subject_id", "component", "expected"),
    [
        ("9700", "11", {0, 1}),  # Biology Paper 1 MCQ
        ("9700", "21", {0}),  # Biology Paper 2 structured
        ("9702", "11", {0, 1}),  # Physics Paper 1 MCQ
        ("9702", "31", {0}),  # Physics Paper 3 practical
        ("9709", "11", {0, 1}),  # Math Paper 1 Pure
        ("9709", "61", {0, 1}),  # Math Paper 6 Probability & Stats 2
        ("9231", "11", {0, 1}),  # Further Math Paper 1
        ("9231", "41", {0, 1}),  # Further Math Paper 4
        ("9999", "11", {0}),  # unconfigured subject -> top-level default
    ],
)
def test_real_paper_page_config_resolves_expected_values(
    subject_id: str, component: str, expected: set[int]
) -> None:
    """Pins the real data/paper_page_config.json's resolved values so
    collapsing duplicated boilerplate entries can't silently change them."""
    assert qp_skip_pages(subject_id, component) == expected


# ---------------------------------------------------------------------------
# grading_type_for_paper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("paper_id", "expected"),
    [
        # Chemistry: Paper 1 is the only MCQ; every other component is a
        # structured paper the VL grader handles.
        ("9701_s25_qp_11", PaperType.MCQ),
        ("9701_s25_qp_14", PaperType.MCQ),   # a variant of the same paper
        ("9701_s25_qp_21", PaperType.MATH),
        ("9701_s25_qp_31", PaperType.MATH),
        ("9701_s25_qp_41", PaperType.MATH),
        ("9701_s25_qp_54", PaperType.MATH),
        ("9702_s25_qp_11", PaperType.MCQ),
        ("9709_s25_qp_12", PaperType.MATH),
        ("9709_s25_qp_61", PaperType.MATH),
        ("9231_s25_qp_43", PaperType.MATH),
    ],
)
def test_grading_type_for_real_paper_ids(
    paper_id: str, expected: PaperType
) -> None:
    """Pins the real data/syllabus_config.json: picking the grading path is
    what saves the user from grading a structured paper on the MCQ path,
    which silently yields no topics and no mistake records."""
    assert grading_type_for_paper(paper_id) == expected


@pytest.mark.parametrize(
    "paper_id",
    [
        "9702_s25_qp_41",   # component not recorded (only papers 1-3 are)
        "9700_s25_qp_21",   # subject has no paper_types at all
        "9999_s25_qp_11",   # unknown subject
        "9701_s25_gt",      # not a question paper
        "9701/21/M/J/25",   # the mark scheme's own cover-page id
        "",
    ],
)
def test_grading_type_is_none_when_not_recorded(paper_id: str) -> None:
    """None leaves the Mark tab's radio alone — an unrecorded paper must not
    be guessed at, since guessing wrong is silent."""
    assert grading_type_for_paper(paper_id) is None


def test_grading_type_reads_the_given_config(tmp_path: Path) -> None:
    config_path = tmp_path / "syllabus_config.json"
    config_path.write_text(
        json.dumps([{
            "syllabus_id": "9999",
            "name": "Test",
            "paper_types": [
                {"digit": "1", "name": "MCQ", "grading": "mcq"},
                {"digit": "2", "name": "Structured"},
            ],
        }]),
        encoding="utf-8",
    )

    assert grading_type_for_paper(
        "9999_s25_qp_12", config_path=config_path
    ) == PaperType.MCQ
    # Recorded name but no grading recorded → still None.
    assert grading_type_for_paper(
        "9999_s25_qp_21", config_path=config_path
    ) is None
