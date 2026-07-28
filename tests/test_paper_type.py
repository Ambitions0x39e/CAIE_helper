# tests/test_paper_type.py
from pathlib import Path

import pytest

from core.models import SUBJECT_PAPER_TYPES, PaperType
from core.settings import GraderConfig

_GRADER_ENV_VARS = (
    "GRADER_API_KEY",
    "GRADER_BASE_URL",
    "GRADER_MODEL",
    "GRADER_DPI",
    "GRADER_ENABLE_THINKING",
)


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


def test_grader_config_try_load_returns_none_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """"Missing" has to be arranged, not assumed.

    This used to read whatever ~/.cie_helper/.env happened to hold, so on any
    machine where the developer had actually configured a grader key it failed
    — never because try_load() was broken, only because the precondition was
    false. Point env_file at a path that does not exist and clear the GRADER_*
    variables, and the test finally checks what its name claims.
    """
    monkeypatch.setitem(
        GraderConfig.model_config, "env_file", str(tmp_path / "absent.env"),
    )
    for var in _GRADER_ENV_VARS:
        monkeypatch.delenv(var, raising=False)

    assert GraderConfig.try_load() is None


def test_grader_config_try_load_reads_an_existing_env_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The other half: with a key present, try_load must return a config.

    Without this, the "returns None" test above would still pass if try_load
    were changed to return None unconditionally.
    """
    env_file = tmp_path / ".env"
    env_file.write_text("GRADER_API_KEY=sk-from-env-file\n", encoding="utf-8")
    monkeypatch.setitem(GraderConfig.model_config, "env_file", str(env_file))
    for var in _GRADER_ENV_VARS:
        monkeypatch.delenv(var, raising=False)

    cfg = GraderConfig.try_load()

    assert cfg is not None
    assert cfg.api_key.get_secret_value() == "sk-from-env-file"
