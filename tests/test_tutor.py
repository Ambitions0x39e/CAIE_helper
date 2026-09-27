"""Tests for ``modules.tutor`` — the note's shape, the prompt its
descriptions are asked for with, and that grading never sees the note."""
from __future__ import annotations

import datetime
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from core.models import AttemptRecord
from core.settings import GraderConfig, app_settings
from modules import tutor
from modules.profile import ComponentProfile, component_profile

_TS = datetime.datetime(2026, 9, 24, 10, 0)


def _run() -> list[AttemptRecord]:
    """Paper 1 of 9231: Vectors lost to a slip, a method error and one mark
    nobody classified; Matrices full; Polar coordinates left blank."""
    return [
        AttemptRecord(
            paper_id="9231_s25_qp_11", question_id=q, topic_id=t,
            topic_name=n, error_type=e,  # type: ignore[arg-type]
            score=s, max_score=m, timestamp=_TS,
        )
        for q, t, n, e, s, m in [
            ("Q6a", "1.6", "Vectors", "slip", 1.0, 5.0),
            ("Q6c", "1.6", "Vectors", "method", 2.0, 7.0),
            ("Q6b", "1.6", "Vectors", None, 3.0, 4.0),
            ("Q4a", "1.4", "Matrices", None, 2.0, 2.0),
            ("Q5b", "1.5", "Polar coordinates", "blank", 0.0, 6.0),
        ]
    ]


def _profile() -> ComponentProfile:
    profile = component_profile(_run(), "9231", "1")
    assert profile is not None
    return profile


def test_the_note_is_a_line_per_topic_and_one_per_reason() -> None:
    note = tutor.render_note(_profile(), {"s1": "Q6c 把向量当标量代入距离公式"})

    assert note == (
        "- Vectors 3题 6/16分\n"
        "  - 方法 5分：Q6c 把向量当标量代入距离公式\n"
        "  - 失误 4分\n"
        "  - 未分类 1分\n"
        "- Matrices 1题 2/2分\n"
    )


def test_an_unanswered_question_is_not_in_the_note() -> None:
    """Left blank, a question says nothing about its topic: Polar
    coordinates neither gets a line nor reaches the model."""
    prompt = tutor.build_prompt(
        _profile(), _run(), {}, None, paper_id="9231_s25_qp_11",
    )

    assert "Polar" not in tutor.render_note(_profile(), {})
    assert "Polar" not in prompt and "Q5b" not in prompt


def test_the_prompt_numbers_the_reasons_and_carries_the_runs_comments() -> None:
    prompt = tutor.build_prompt(
        _profile(), _run(), {"Q6c": "混淆向量与标量"}, None,
        paper_id="9231_s25_qp_11",
    )

    assert "s1: Vectors · 方法 · 5 分" in prompt
    assert "s3: Vectors · 未分类 · 1 分" in prompt
    assert "- Q6c · Vectors · 方法 · 得 2/7 · 混淆向量与标量" in prompt
    assert "Q4a" not in prompt  # full marks is not a lost mark
    assert "（还没有）" in prompt


def test_the_prompt_hands_back_the_old_note() -> None:
    prompt = tutor.build_prompt(
        _profile(), _run(), {}, "- Vectors 老是漏单位\n", paper_id="9231_s25_qp_11",
    )
    assert "- Vectors 老是漏单位" in prompt


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('```json\n{"s1": " 算错 ", "s2": 3}\n```', {"s1": "算错"}),
        ("不是 JSON", {}),
        ('["s1"]', {}),
    ],
)
def test_the_reply_is_read_leniently(raw: str, expected: dict[str, str]) -> None:
    assert tutor.parse_reply(raw) == expected


def test_refresh_replaces_the_note_on_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_settings, "base_dir", tmp_path)
    sent: list[str] = []

    def _create(**kw: Any) -> Any:
        sent.append(kw["messages"][0]["content"])
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps({"s2": "Q6a 点积算错"})),
        )])

    monkeypatch.setattr(tutor, "OpenAI", lambda **_: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=_create)),
    ))
    tutor.notes_path("9231", "1").parent.mkdir(parents=True)
    tutor.notes_path("9231", "1").write_text("- 旧的判断\n", encoding="utf-8")

    tutor.refresh_notes(
        GraderConfig(api_key="k"), _run(), {}, profile=_profile(),
        paper_id="9231_s25_qp_11",
    )

    assert "- 旧的判断" in sent[0]
    assert "  - 失误 4分：Q6a 点积算错\n" in (tutor.read_notes("9231", "1") or "")


def test_the_grading_path_cannot_reach_the_notes() -> None:
    """Blind grading: nothing the grader imports may import the profile or
    the notes, so no prompt it builds can carry them."""
    code = (
        "import sys; import modules.marking.workflow; "
        "leaked = [m for m in ('modules.tutor', 'modules.profile') "
        "if m in sys.modules]; assert not leaked, leaked"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
