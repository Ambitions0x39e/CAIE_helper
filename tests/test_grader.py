# tests/test_grader.py
import json

import pytest

from modules.grader import (
    MarkDetail,
    QuestionResult,
    parse_grading_result,
)


def test_parse_grading_result_valid() -> None:
    raw = json.dumps({
        "question": "Q1",
        "marks": [{"code": "M1", "awarded": True, "reason": "correct method"}],
        "total": 1,
        "max": 7,
        "comment": "Good attempt",
    })
    result = parse_grading_result(raw)
    assert result.question == "Q1"
    assert result.total == 1
    assert result.max == 7
    assert len(result.marks) == 1
    assert result.marks[0].awarded is True


def test_parse_grading_result_strips_code_fences() -> None:
    raw = (
        '```json\n{"question":"Q2","marks":[],"total":0,"max":3,'
        '"comment":"empty"}\n```'
    )
    result = parse_grading_result(raw)
    assert result.question == "Q2"


def test_parse_grading_result_invalid_json() -> None:
    with pytest.raises(ValueError, match="Failed to parse"):
        parse_grading_result("not json at all")


def test_parse_grading_result_missing_fields() -> None:
    with pytest.raises(ValueError, match="Missing fields"):
        parse_grading_result('{"question": "Q1"}')


def test_question_result_model() -> None:
    qr = QuestionResult(
        question="Q1",
        marks=[MarkDetail(code="B1", awarded=True, reason="correct")],
        total=1,
        max=1,
        comment="Perfect",
    )
    assert qr.total == 1
