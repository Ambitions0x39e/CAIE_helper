"""Tests for ``modules.tutor`` — the prompt the note is rewritten from, what is
kept of the reply, and that grading never sees the note."""
from __future__ import annotations

import datetime
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from core.models import AttemptRecord
from core.settings import GraderConfig, app_settings
from modules import tutor
from modules.profile import component_profile

_TS = datetime.datetime(2026, 9, 24, 10, 0)


def _run() -> list[AttemptRecord]:
    return [
        AttemptRecord(
            paper_id="9701_s25_qp_22", question_id=q, topic_id="7",
            topic_name="Equilibria", error_type=e,  # type: ignore[arg-type]
            score=s, max_score=4.0, timestamp=_TS,
        )
        for q, s, e in [("1", 4.0, None), ("2", 1.0, "misread")]
    ]


def _prompt(old_notes: str | None = None) -> str:
    run = _run()
    profile = component_profile(run, "9701", "2")
    assert profile is not None
    return tutor.build_prompt(
        profile, run, {"2": "漏看了温度条件"}, old_notes, paper_id="9701_s25_qp_22",
    )


def test_the_prompt_carries_the_profile_and_the_runs_lost_marks() -> None:
    prompt = _prompt()

    assert "Equilibria：2 题，丢 3/8 分（38%），原因 审题 3 分" in prompt
    assert "- 2 · Equilibria · 审题 · 得 1/4 · 漏看了温度条件" in prompt
    assert "- 1 ·" not in prompt  # full marks is not a lost mark
    assert "（还没有）" in prompt


def test_the_prompt_hands_back_the_old_note_to_be_rewritten() -> None:
    assert "- Energetics 老是漏单位" in _prompt("- Energetics 老是漏单位\n")


def test_the_reply_loses_its_fences_and_is_capped() -> None:
    raw = "```markdown\n" + "\n".join(f"- 第 {i} 条" for i in range(30)) + "\n```"

    note = tutor.clean_reply(raw)

    assert note.splitlines()[0] == "- 第 0 条"
    assert len(note.splitlines()) == tutor.MAX_LINES


def test_refresh_replaces_the_note_on_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_settings, "base_dir", tmp_path)
    sent: list[str] = []

    def _create(**kw: Any) -> Any:
        sent.append(kw["messages"][0]["content"])
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content="- Equilibria 审题丢分"),
        )])

    monkeypatch.setattr(tutor, "OpenAI", lambda **_: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=_create)),
    ))
    tutor.notes_path("9701", "2").parent.mkdir(parents=True)
    tutor.notes_path("9701", "2").write_text("- 旧的判断\n", encoding="utf-8")
    run = _run()
    profile = component_profile(run, "9701", "2")
    assert profile is not None

    tutor.refresh_notes(
        GraderConfig(api_key="k"), run, {}, profile=profile, paper_id="9701_s25_qp_22",
    )

    assert "- 旧的判断" in sent[0]
    assert tutor.read_notes("9701", "2") == "- Equilibria 审题丢分\n"


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


def _unfinished_run() -> list[AttemptRecord]:
    return [
        AttemptRecord(
            paper_id="9231_s25_qp_44", question_id=q, topic_id=t,
            topic_name=n, error_type=e,  # type: ignore[arg-type]
            score=s, max_score=m, timestamp=_TS,
        )
        for q, t, n, e, s, m in [
            ("Q2a", "4.4", "Non-parametric tests", "slip", 3.0, 6.0),
            ("Q2b", "4.4", "Non-parametric tests", "blank", 0.0, 1.0),
            ("Q3", "4.3", "χ²-tests", "blank", 0.0, 7.0),
        ]
    ]


def test_unanswered_questions_never_reach_the_model() -> None:
    """Handed "7 marks left blank", the model wrote about avoidance and time
    management; an unfinished paper says nothing about the topics skipped."""
    run = _unfinished_run()
    profile = component_profile(run, "9231", "4")
    assert profile is not None

    prompt = tutor.build_prompt(profile, run, {}, None, paper_id="9231_s25_qp_44")

    assert "Non-parametric tests：1 题，丢 3/6 分" in prompt
    assert "χ²-tests" not in prompt
    assert "Q2b" not in prompt and "Q3" not in prompt
    assert profile.papers == 1


def test_unanswered_questions_are_listed_by_code() -> None:
    assert tutor.unfinished_line(_unfinished_run()) == "- 【BP/未完成】Q2b、Q3"
    assert tutor.unfinished_line(_run()) is None


def test_the_unfinished_line_is_written_by_code_under_the_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The last note's unfinished line does not go back to the model either."""
    monkeypatch.setattr(app_settings, "base_dir", tmp_path)
    sent: list[str] = []
    reply = "\n".join(f"- 第 {i} 条" for i in range(30))

    def _create(**kw: Any) -> Any:
        sent.append(kw["messages"][0]["content"])
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=reply),
        )])

    monkeypatch.setattr(tutor, "OpenAI", lambda **_: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=_create)),
    ))
    tutor.notes_path("9231", "4").parent.mkdir(parents=True)
    tutor.notes_path("9231", "4").write_text(
        "- Wilcoxon 取 T 出错\n- 【BP/未完成】Q5\n", encoding="utf-8",
    )
    run = _unfinished_run()
    profile = component_profile(run, "9231", "4")
    assert profile is not None

    path = tutor.refresh_notes(
        GraderConfig(api_key="k"), run, {}, profile=profile, paper_id="9231_s25_qp_44",
    )

    assert "- Wilcoxon 取 T 出错" in sent[0]
    assert "BP" not in sent[0]
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == tutor.MAX_LINES
    assert lines[-1] == "- 【BP/未完成】Q2b、Q3"
