# tests/test_ms_parser.py

import json

from modules.ms_parser import (
    PaperConfig,
    QuestionConfig,
    _merge_questions,
    _parse_image_ms_response,
    normalize_question_id,
)

# ── normalize_question_id ─────────────────────────────────────


def test_normalize_question_id_simple() -> None:
    assert normalize_question_id("1") == "Q1"


def test_normalize_question_id_with_part() -> None:
    assert normalize_question_id("2(a)") == "Q2a"


def test_normalize_question_id_strips() -> None:
    assert normalize_question_id("  3  ") == "Q3"


# ── Models ────────────────────────────────────────────────────


def test_question_config_model() -> None:
    qc = QuestionConfig(max_marks=7, mark_scheme="B1: correct answer")
    assert qc.max_marks == 7
    assert "B1" in qc.mark_scheme


def test_paper_config_model() -> None:
    pc = PaperConfig(
        paper_id="9231/41/O/N/22",
        total_marks=50,
        questions={"Q1": QuestionConfig(max_marks=7, mark_scheme="test")},
    )
    assert pc.total_marks == 50
    assert "Q1" in pc.questions


# ── _merge_questions ──────────────────────────────────────────


def test_merge_questions_no_overlap() -> None:
    base = {"Q1": QuestionConfig(max_marks=3, mark_scheme="M1: method")}
    new = {"Q2": QuestionConfig(max_marks=5, mark_scheme="B1: answer")}
    merged = _merge_questions(base, new)
    assert set(merged.keys()) == {"Q1", "Q2"}
    assert merged["Q1"].mark_scheme == "M1: method"
    assert merged["Q2"].mark_scheme == "B1: answer"


def test_merge_questions_with_overlap() -> None:
    base = {"Q1": QuestionConfig(max_marks=3, mark_scheme="M1: first part")}
    new = {"Q1": QuestionConfig(max_marks=5, mark_scheme="A1: second part")}
    merged = _merge_questions(base, new)
    assert merged["Q1"].max_marks == 5
    assert "M1: first part" in merged["Q1"].mark_scheme
    assert "A1: second part" in merged["Q1"].mark_scheme


# ── _parse_image_ms_response ─────────────────────────────────


def test_parse_image_ms_response_valid() -> None:
    raw = json.dumps({
        "questions": [
            {"id": "1(a)", "max_marks": 3, "mark_scheme": "B1: x = 2"},
            {"id": "2", "max_marks": 5, "mark_scheme": "M1: integrate"},
        ]
    })
    result = _parse_image_ms_response(raw)
    assert "Q1a" in result
    assert "Q2" in result
    assert result["Q1a"].max_marks == 3
    assert result["Q2"].mark_scheme == "M1: integrate"


def test_parse_image_ms_response_with_fences() -> None:
    inner = json.dumps(
        {"questions": [{"id": "3", "max_marks": 2, "mark_scheme": "B1: y"}]}
    )
    raw = f"```json\n{inner}\n```"
    result = _parse_image_ms_response(raw)
    assert "Q3" in result
    assert result["Q3"].max_marks == 2


def test_parse_image_ms_response_empty() -> None:
    raw = json.dumps({"questions": []})
    result = _parse_image_ms_response(raw)
    assert result == {}
