"""Tests for core.config_store's paper-page-config loader."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.config_store import PaperPageConfig, get_paper_page_config


def test_paper_page_config_is_a_pydantic_model() -> None:
    """PaperPageConfig must validate like the rest of the config models in
    this module (SyllabusConfig, PaperTypeConfig), not be a bare dataclass
    that skips validation."""
    with pytest.raises(ValidationError):
        PaperPageConfig(qp_skip_pages="not-a-set")  # type: ignore[arg-type]


def test_get_paper_page_config_raises_on_malformed_json(tmp_path: Path) -> None:
    """Malformed JSON must raise, like ConfigStore.load_all() does for
    syllabus_config.json — not silently fall back to defaults."""
    bad_config = tmp_path / "paper_page_config.json"
    bad_config.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ValueError, match="not valid JSON"):
        get_paper_page_config("9702", "11", config_path=bad_config)


def test_get_paper_page_config_falls_back_to_default_entry(tmp_path: Path) -> None:
    config_path = tmp_path / "paper_page_config.json"
    config_path.write_text(
        json.dumps({"default": {"qp_skip_pages": [0], "ms_start_page": 6}}),
        encoding="utf-8",
    )
    cfg = get_paper_page_config("9999", "1", config_path=config_path)
    assert cfg.qp_skip_pages == {0}
    assert cfg.ms_start_page == 6


def test_get_paper_page_config_uses_component_specific_entry(tmp_path: Path) -> None:
    config_path = tmp_path / "paper_page_config.json"
    config_path.write_text(
        json.dumps({
            "default": {"qp_skip_pages": [0], "ms_start_page": 6},
            "9702": {"1": {"qp_skip_pages": [0, 1], "ms_start_page": 2}},
        }),
        encoding="utf-8",
    )
    cfg = get_paper_page_config("9702", "11", config_path=config_path)
    assert cfg.qp_skip_pages == {0, 1}
    assert cfg.ms_start_page == 2


def test_get_paper_page_config_uses_subject_level_default(tmp_path: Path) -> None:
    """A subject's own "_default" entry must win over the top-level default,
    letting components with no component-specific override still inherit
    the subject's convention instead of falling all the way through."""
    config_path = tmp_path / "paper_page_config.json"
    config_path.write_text(
        json.dumps({
            "default": {"qp_skip_pages": [0], "ms_start_page": 6},
            "9709": {"_default": {"qp_skip_pages": [0, 1], "ms_start_page": 6}},
        }),
        encoding="utf-8",
    )
    cfg = get_paper_page_config("9709", "61", config_path=config_path)
    assert cfg.qp_skip_pages == {0, 1}
    assert cfg.ms_start_page == 6


@pytest.mark.parametrize(
    ("subject_id", "component", "expected_skip", "expected_ms_start"),
    [
        ("9700", "11", {0, 1}, 2),  # Biology Paper 1 MCQ
        ("9700", "21", {0}, 6),  # Biology Paper 2 structured
        ("9702", "11", {0, 1}, 2),  # Physics Paper 1 MCQ
        ("9702", "31", {0}, 6),  # Physics Paper 3 practical
        ("9709", "11", {0, 1}, 6),  # Math Paper 1 Pure
        ("9709", "61", {0, 1}, 6),  # Math Paper 6 Probability & Stats 2
        ("9231", "11", {0, 1}, 2),  # Further Math Paper 1
        ("9231", "41", {0, 1}, 2),  # Further Math Paper 4
        ("9999", "11", {0}, 6),  # unconfigured subject -> top-level default
    ],
)
def test_real_paper_page_config_resolves_expected_values(
    subject_id: str, component: str, expected_skip: set[int], expected_ms_start: int
) -> None:
    """Pins the real data/paper_page_config.json's resolved values so
    collapsing duplicated boilerplate entries can't silently change them."""
    cfg = get_paper_page_config(subject_id, component)
    assert cfg.qp_skip_pages == expected_skip
    assert cfg.ms_start_page == expected_ms_start
