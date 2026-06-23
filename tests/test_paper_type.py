# tests/test_paper_type.py
from core.models import SUBJECT_PAPER_TYPES, PaperType
from core.settings import GraderConfig


def test_paper_type_enum() -> None:
    assert PaperType.MATH.value == "math"


def test_subject_mapping() -> None:
    assert SUBJECT_PAPER_TYPES["9709"] == PaperType.MATH
    assert SUBJECT_PAPER_TYPES["9231"] == PaperType.MATH


def test_subject_mapping_unknown_returns_none() -> None:
    assert SUBJECT_PAPER_TYPES.get("9999") is None


def test_grader_config_defaults() -> None:
    cfg = GraderConfig(api_key="test-key")
    assert cfg.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert cfg.model == "qwen3-vl-flash"
    assert cfg.api_key.get_secret_value() == "test-key"


def test_grader_config_try_load_returns_none_when_missing() -> None:
    assert GraderConfig.try_load() is None
