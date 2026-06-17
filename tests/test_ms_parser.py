# tests/test_ms_parser.py
import pytest
from core.models import PaperType
from modules.ms_parser import (
    QuestionConfig,
    PaperConfig,
    clean_text,
    normalize_question_id,
)


def test_normalize_question_id_simple():
    assert normalize_question_id("1") == "Q1"


def test_normalize_question_id_with_part():
    assert normalize_question_id("2(a)") == "Q2a"


def test_normalize_question_id_strips():
    assert normalize_question_id("  3  ") == "Q3"


def test_clean_text_removes_garbled():
    assert "§" not in clean_text("hello§world")


def test_question_config_model():
    qc = QuestionConfig(max_marks=7, mark_scheme="B1: correct answer")
    assert qc.max_marks == 7
    assert "B1" in qc.mark_scheme


def test_paper_config_model():
    pc = PaperConfig(
        paper_id="9231/41/O/N/22",
        total_marks=50,
        questions={"Q1": QuestionConfig(max_marks=7, mark_scheme="test")},
    )
    assert pc.total_marks == 50
    assert "Q1" in pc.questions
