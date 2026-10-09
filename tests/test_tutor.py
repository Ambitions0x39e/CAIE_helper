"""Tests for ``modules.tutor`` — filing lost questions into the ledger,
the note laid out from it, and that grading never sees either."""
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
from modules.profile import component_profile
from modules.tutor import Ledger, Pattern

_S23 = "9231_s23_qp_43"
_S25 = "9231_s25_qp_44"


def _row(
    paper: str, q: str, topic: str | None, name: str | None, error: str | None,
    score: float, max_score: float, day: int = 1,
) -> AttemptRecord:
    return AttemptRecord(
        paper_id=paper, question_id=q, topic_id=topic, topic_name=name,
        error_type=error,  # type: ignore[arg-type]
        score=score, max_score=max_score,
        timestamp=datetime.datetime(2026, 9, day, 10, 0),
    )


def _records() -> list[AttemptRecord]:
    """Two Paper 4 papers. Q3a and Q2a are the same Wilcoxon slip; Q6b is
    a one-off; Q1 is full; Q3 was left blank."""
    return [
        _row(_S23, "Q1", "4.1", "Continuous random variables", None, 3, 3, day=1),
        _row(_S23, "Q3a", "4.4", "Non-parametric tests", "slip", 5, 7, day=1),
        _row(_S23, "Q6b", "4.3", "χ²-tests", "concept", 1, 2, day=1),
        _row(_S25, "Q2a", "4.4", "Non-parametric tests", "slip", 3, 6, day=2),
        _row(_S25, "Q3", "4.3", "χ²-tests", "blank", 0, 7, day=2),
    ]


def _ledger() -> Ledger:
    return Ledger(patterns=[
        Pattern(id="p1", topic_id="4.4", text="Wilcoxon T 取错",
                hits=[(_S23, "Q3a"), (_S25, "Q2a")]),
        Pattern(id="p2", topic_id="4.3", text="结论与计算矛盾", hits=[(_S23, "Q6b")]),
    ])


def test_the_note_shows_only_what_recurs_across_papers() -> None:
    profile = component_profile(_records(), "9231", "4")
    assert profile is not None

    assert tutor.render_note(profile, _ledger()) == (
        "- χ²-tests 1题 1/2分\n"
        "- Non-parametric tests 2题 8/13分\n"
        "  - Wilcoxon T 取错 ×2（s23_43 Q3a、s25_44 Q2a）\n"
        "- Continuous random variables 1题 3/3分\n"
    )


def test_two_questions_of_one_paper_are_not_a_recurring_mistake() -> None:
    profile = component_profile(_records(), "9231", "4")
    assert profile is not None
    ledger = Ledger(patterns=[Pattern(
        id="p1", topic_id="4.4", text="Wilcoxon T 取错",
        hits=[(_S23, "Q3a"), (_S23, "Q3b")],
    )])

    assert "Wilcoxon" not in tutor.render_note(profile, ledger)


def test_filing_joins_a_pattern_or_opens_one_within_the_topic() -> None:
    lost = tutor.lost_questions(r for r in _records() if r.paper_id == _S25)
    start = Ledger(patterns=[
        Pattern(id="p1", topic_id="4.4", text="Wilcoxon T 取错", hits=[(_S23, "Q3a")]),
        Pattern(id="p2", topic_id="4.3", text="结论与计算矛盾", hits=[(_S23, "Q6b")]),
    ])

    joined = tutor.file_paper(start, _S25, lost, {"Q2a": "p1"})
    assert joined.patterns[0].hits == [(_S23, "Q3a"), (_S25, "Q2a")]

    # p2 is χ²'s: offered only Non-parametric patterns, the model cannot
    # have meant it, so the question stays unfiled rather than misfiled.
    stray = tutor.file_paper(start, _S25, lost, {"Q2a": "p2"})
    assert [p.hits for p in stray.patterns] == [[(_S23, "Q3a")], [(_S23, "Q6b")]]

    opened = tutor.file_paper(start, _S25, lost, {"Q2a": "秩和算错"})
    assert opened.patterns[-1] == Pattern(
        id="p3", topic_id="4.4", topic_name="Non-parametric tests",
        text="秩和算错", hits=[(_S25, "Q2a")],
    )


def test_an_untagged_question_can_join_any_topics_pattern() -> None:
    """s25 Q5b, which the grader left untagged, is the PGF slip s23 Q5b
    made under Probability generating functions."""
    ledger = Ledger(patterns=[Pattern(
        id="p1", topic_id="4.5", topic_name="Probability generating functions",
        text="展开合并同类项算错", hits=[(_S23, "Q5b")],
    )])
    lost = [_row(_S25, "Q5b", None, None, "slip", 2, 3)]

    prompt = tutor.build_prompt(
        ledger, lost, {}, subject_id="9231", component="4", paper_id=_S25,
    )
    filed = tutor.file_paper(ledger, _S25, lost, {"Q5b": "p1"})

    assert "【Probability generating functions】\np1: 展开合并同类项算错" in prompt
    assert filed.patterns[0].hits == [(_S23, "Q5b"), (_S25, "Q5b")]


def test_one_new_description_given_twice_is_one_pattern() -> None:
    lost = [
        _row(_S25, "Q1", None, None, "wording", 2, 4),
        _row(_S25, "Q6b", None, None, "concept", 7, 8),
    ]

    ledger = tutor.file_paper(
        Ledger(), _S25, lost, {"Q1": "结论写法不规范", "Q6b": "结论写法不规范"},
    )

    assert [(p.text, p.hits) for p in ledger.patterns] == [
        ("结论写法不规范", [(_S25, "Q1"), (_S25, "Q6b")]),
    ]


def test_refiling_a_paper_replaces_its_old_filings() -> None:
    """A re-grade: S25's Q2a moves to a new pattern, and p1, left with S23
    alone, no longer recurs."""
    lost = tutor.lost_questions(r for r in _records() if r.paper_id == _S25)

    ledger = tutor.file_paper(_ledger(), _S25, lost, {"Q2a": "秩和算错"})

    assert ledger.patterns[0].hits == [(_S23, "Q3a")]
    assert ledger.patterns[-1].hits == [(_S25, "Q2a")]


def test_a_pattern_left_with_no_questions_is_dropped() -> None:
    ledger = Ledger(patterns=[
        Pattern(id="p1", topic_id="4.4", text="只在 S25", hits=[(_S25, "Q2a")]),
    ])
    assert tutor.file_paper(ledger, _S25, [], {}).patterns == []


def test_the_prompt_offers_the_topics_patterns_and_the_comments() -> None:
    lost = tutor.lost_questions(r for r in _records() if r.paper_id == _S25)

    prompt = tutor.build_prompt(
        _ledger(), lost, {(_S25, "Q2a"): "T 取了较大的秩和"},
        subject_id="9231", component="4", paper_id=_S25,
    )

    assert (
        "【Non-parametric tests】\np1: Wilcoxon T 取错（s23_43 Q3a、s25_44 Q2a）"
    ) in prompt
    assert "- Q2a · Non-parametric tests · 失误 · 得 3/6 · T 取了较大的秩和" in prompt
    assert "结论与计算矛盾" not in prompt  # χ² has no lost question to file here
    assert "Q3 " not in prompt  # blank: nothing to say how the student goes wrong


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('```json\n{"Q1": " p3 ", "Q2": 3, "Q3": ""}\n```', {"Q1": "p3"}),
        ("不是 JSON", {}),
        ('["p1"]', {}),
    ],
)
def test_the_reply_is_read_leniently(raw: str, expected: dict[str, str]) -> None:
    assert tutor.parse_reply(raw) == expected


def _fake_model(
    monkeypatch: pytest.MonkeyPatch, replies: list[dict[str, str]],
) -> list[str]:
    sent: list[str] = []
    queue = iter(replies)

    def _create(**kw: Any) -> Any:
        sent.append(kw["messages"][0]["content"])
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(next(queue))),
        )])

    monkeypatch.setattr(tutor, "OpenAI", lambda **_: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=_create)),
    ))
    return sent


def test_with_no_ledger_every_graded_paper_is_filed_oldest_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_settings, "base_dir", tmp_path)
    sent = _fake_model(monkeypatch, [
        {"Q3a": "Wilcoxon T 取错", "Q6b": "结论与计算矛盾"},
        {"Q2a": "p1"},
    ])

    tutor.refresh_notes(
        GraderConfig(api_key="k"), _records(), {},
        subject_id="9231", component="4", questions=[(_S25, "Q2a")],
    )

    assert [_S23 in s for s in sent] == [True, False]
    assert "  - Wilcoxon T 取错 ×2（s23_43 Q3a、s25_44 Q2a）\n" in (
        tutor.read_notes("9231", "4") or ""
    )


def test_with_a_ledger_only_the_confirmed_paper_is_filed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_settings, "base_dir", tmp_path)
    path = tutor.ledger_path("9231", "4")
    path.parent.mkdir(parents=True)
    path.write_text(_ledger().model_dump_json(), encoding="utf-8")
    sent = _fake_model(monkeypatch, [{"Q2a": "p1"}])

    tutor.refresh_notes(
        GraderConfig(api_key="k"), _records(), {},
        subject_id="9231", component="4", questions=[(_S25, "Q2a")],
    )

    assert len(sent) == 1
    saved = Ledger.model_validate_json(path.read_text(encoding="utf-8"))
    assert saved.patterns[0].hits == [(_S23, "Q3a"), (_S25, "Q2a")]


def test_refiling_one_question_leaves_its_papers_others_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A redone S23 Q6b: only it is sent and refiled; S23 Q3a keeps p1."""
    monkeypatch.setattr(app_settings, "base_dir", tmp_path)
    path = tutor.ledger_path("9231", "4")
    path.parent.mkdir(parents=True)
    path.write_text(_ledger().model_dump_json(), encoding="utf-8")
    sent = _fake_model(monkeypatch, [{"Q6b": "符号写反"}])

    tutor.refresh_notes(
        GraderConfig(api_key="k"), _records(), {},
        subject_id="9231", component="4", questions=[(_S23, "Q6b")],
    )

    assert len(sent) == 1
    assert "- Q6b" in sent[0]
    assert "- Q3a" not in sent[0]
    saved = Ledger.model_validate_json(path.read_text(encoding="utf-8"))
    assert [(p.text, p.hits) for p in saved.patterns] == [
        ("Wilcoxon T 取错", [(_S23, "Q3a"), (_S25, "Q2a")]),
        ("符号写反", [(_S23, "Q6b")]),
    ]


def test_the_grading_path_cannot_reach_the_notes() -> None:
    """Blind grading: nothing the grader imports may import the profile or
    the notes, so no prompt it builds can carry them."""
    code = (
        "import sys; import modules.marking.workflow, modules.marking.sheet; "
        "leaked = [m for m in ('modules.tutor', 'modules.profile') "
        "if m in sys.modules]; assert not leaked, leaked"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
