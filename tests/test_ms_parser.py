# tests/test_ms_parser.py

from modules.ms_parser import (
    PaperConfig,
    QuestionConfig,
    clean_text,
    normalize_question_id,
)


def test_normalize_question_id_simple() -> None:
    assert normalize_question_id("1") == "Q1"


def test_normalize_question_id_with_part() -> None:
    assert normalize_question_id("2(a)") == "Q2a"


def test_normalize_question_id_strips() -> None:
    assert normalize_question_id("  3  ") == "Q3"


def test_clean_text_removes_garbled() -> None:
    assert "§" not in clean_text("hello§world")


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
