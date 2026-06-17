# tests/test_paper_type.py
from core.models import PaperType, SUBJECT_PAPER_TYPES
from core.settings import GraderConfig


def test_paper_type_enum():
    assert PaperType.MATH.value == "math"


def test_subject_mapping():
    assert SUBJECT_PAPER_TYPES["9709"] == PaperType.MATH
    assert SUBJECT_PAPER_TYPES["9231"] == PaperType.MATH


def test_subject_mapping_unknown_returns_none():
    assert SUBJECT_PAPER_TYPES.get("9999") is None


def test_grader_config_defaults():
    cfg = GraderConfig(api_key="test-key")
    assert cfg.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert cfg.model == "qwen3-vl-flash"
    assert cfg.api_key.get_secret_value() == "test-key"


def test_grader_config_try_load_returns_none_when_missing():
    assert GraderConfig.try_load() is None
