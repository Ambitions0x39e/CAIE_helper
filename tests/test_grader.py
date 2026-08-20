# tests/test_grader.py
import json
from types import SimpleNamespace
from typing import Any

import pytest

from core.settings import GraderConfig
from modules.marking import grader
from modules.marking.grader import (
    MarkDetail,
    QuestionResult,
    grade_question,
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


# ── Topic tagging ─────────────────────────────────────────────────
#
# ``grade_question`` builds the prompt, so the only way to see whether the
# topic section is really in it (or really absent) is to capture what would
# have been sent. Only the OpenAI client is replaced — prompt assembly, the
# code under test, runs for real.

_CANNED_REPLY = '{"question": "Q1", "marks": [], "total": 0, "max": 5}'
_TOPIC_HEADING = "## 该 Paper 覆盖的 Topic 列表:"


@pytest.fixture
def sent_prompts(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Capture the text part of every message ``grade_question`` sends."""
    prompts: list[str] = []

    def _create(**kwargs: Any) -> Any:
        for part in kwargs["messages"][0]["content"]:
            if part.get("type") == "text":
                prompts.append(part["text"])
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=_CANNED_REPLY))]
        )

    class _FakeClient:
        def __init__(self, **_kw: Any) -> None:
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=_create)
            )

    monkeypatch.setattr(grader, "OpenAI", _FakeClient)
    return prompts


def _grade(topic_list: dict[str, str] | None) -> None:
    grade_question(
        config=GraderConfig(api_key="test-key"),
        images=[b"png"],
        question_id="Q1",
        mark_scheme="B1 for the right answer",
        max_marks=5,
        topic_list=topic_list,
    )


def test_prompt_omits_the_topic_section_without_a_syllabus(
    sent_prompts: list[str],
) -> None:
    """No topic list → no heading, no list, no "topic" field instruction."""
    _grade(None)

    prompt = sent_prompts[0]
    assert _TOPIC_HEADING not in prompt
    assert "topic" not in prompt
    # The rest of the prompt is untouched by the change.
    assert "B1 for the right answer" in prompt


def test_prompt_lists_the_topics_it_was_given(
    sent_prompts: list[str],
) -> None:
    _grade({"1.2": "Functions", "1.6": "Series"})

    prompt = sent_prompts[0]
    assert _TOPIC_HEADING in prompt
    assert "1.2: Functions" in prompt
    assert "1.6: Series" in prompt
    assert '"topic"' in prompt


def test_an_empty_topic_list_is_treated_as_no_syllabus(
    sent_prompts: list[str],
) -> None:
    """``{}`` must not produce a heading over an empty list."""
    _grade({})

    assert _TOPIC_HEADING not in sent_prompts[0]


def test_parse_grading_result_repairs_latex_backslashes() -> None:
    """The model writes LaTeX in `reason`; `\\S` is not a JSON escape.

    Verbatim from a real failing response — the question had been graded
    correctly and was reported as a failure purely on the encoding.
    """
    raw = (
        '{"question": "Q2b", '
        '"marks": [{"code": "M1", "awarded": true, '
        r'"reason": "正确使用了展开公式 $\Sigma y^2 = (\Sigma y)^2 - 2\Sigma xy$"}], '
        '"total": 2, "max": 2, "comment": "准确应用了韦达定理"}'
    )

    result = parse_grading_result(raw)

    assert result.total == 2
    assert result.marks[0].awarded is True
    # The text survives with its backslashes, rather than being dropped.
    assert r"\Sigma y^2" in result.marks[0].reason


def test_parse_grading_result_leaves_a_valid_response_alone() -> None:
    """Valid JSON parses on the first try — the repair never runs."""
    raw = json.dumps({
        "question": "Q1",
        "marks": [{
            "code": "B1", "awarded": True,
            "reason": 'path C:\\temp, quote ", newline\nhere',
        }],
        "total": 1, "max": 1,
    })

    result = parse_grading_result(raw)

    assert result.marks[0].reason == 'path C:\\temp, quote ", newline\nhere'


def test_parse_grading_result_repairs_only_the_invalid_escapes() -> None:
    """One reason carrying both a valid escape and an invalid one.

    This is what separates a correct repair from the naive "double every
    backslash" pass: the latter turns the already-correct ``\\\\`` into
    ``\\\\\\\\``, so the path comes back with two backslashes instead of one.
    A response that is *only* malformed cannot tell the two apart, because a
    fully valid response never reaches the repair at all.
    """
    raw = (
        '{"question": "Q1", '
        '"marks": [{"code": "M1", "awarded": true, '
        r'"reason": "路径 C:\\temp 与公式 $\Sigma y$"}], '
        '"total": 1, "max": 1}'
    )

    result = parse_grading_result(raw)

    assert result.marks[0].reason == "路径 C:\\temp 与公式 $\\Sigma y$"


def test_parse_grading_result_still_rejects_real_garbage() -> None:
    """Repairing escapes must not turn "unparseable" into "silently wrong"."""
    with pytest.raises(ValueError, match="Failed to parse"):
        parse_grading_result('{"question": "Q1", "marks": [,,,}')


def test_prompt_forbids_latex(sent_prompts: list[str]) -> None:
    """Belt and braces: the repair is the net, this is the instruction."""
    _grade(None)

    assert "不要在任何字段里写 LaTeX 或反斜杠" in sent_prompts[0]


def test_parse_grading_result_reads_the_topic_field() -> None:
    raw = json.dumps({
        "question": "Q1",
        "marks": [],
        "total": 2,
        "max": 5,
        "topic": "1.2",
    })

    assert parse_grading_result(raw).topic == "1.2"


def test_parse_grading_result_topic_defaults_to_none() -> None:
    raw = json.dumps({"question": "Q1", "marks": [], "total": 2, "max": 5})

    assert parse_grading_result(raw).topic is None


def test_parse_grading_result_accepts_a_null_topic() -> None:
    """The prompt tells the model to answer null when it cannot place it."""
    raw = json.dumps({
        "question": "Q1", "marks": [], "total": 2, "max": 5, "topic": None,
    })

    assert parse_grading_result(raw).topic is None


def test_parse_grading_result_coerces_a_numeric_topic() -> None:
    """A science topic id is a bare number; JSON may carry it as one."""
    raw = json.dumps({
        "question": "Q1", "marks": [], "total": 2, "max": 5, "topic": 7,
    })

    assert parse_grading_result(raw).topic == "7"
