"""Tests for modules.marking.workflow.

This logic used to be nested inside app_flet/tabs/mark.py's build_mark_tab
closure, where it could not be reached without a running Flet page — these
are the first tests it has ever had.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from core.models import PaperType
from modules.marking import workflow
from modules.marking.grader import MarkDetail, QuestionResult
from modules.marking.ms_parser import PaperConfig, QuestionConfig
from modules.marking.page_segmenter import PageClip, QuestionRegion
from modules.marking.workflow import (
    ScoreSummary,
    collect_page_assignments,
    grade_paper,
    merge_mcq_answers,
    parse_page_spec,
    regions_to_page_map,
    summarise_scores,
)

# ── Page specs ────────────────────────────────────────────────────

class TestParsePageSpec:
    @pytest.mark.parametrize(
        ("spec", "expected"),
        [
            ("2", [2]),
            ("2,3", [2, 3]),
            (" 2 , 3 ", [2, 3]),
            ("2,,3", [2, 3]),
            ("10,1", [10, 1]),  # order is the user's, not sorted
        ],
    )
    def test_valid(self, spec: str, expected: list[int]) -> None:
        assert parse_page_spec(spec) == expected

    @pytest.mark.parametrize("spec", ["", "   ", ",", " , "])
    def test_blank_is_none(self, spec: str) -> None:
        assert parse_page_spec(spec) is None

    @pytest.mark.parametrize("spec", ["abc", "2,x", "2.5", "2-3"])
    def test_malformed_is_none(self, spec: str) -> None:
        # None, not a partial list: a half-parsed "2,x" would silently grade
        # the wrong pages.
        assert parse_page_spec(spec) is None


class TestCollectPageAssignments:
    def test_skips_blank_and_malformed(self) -> None:
        assert collect_page_assignments({
            "Q1": "2",
            "Q2": "",
            "Q3": "4,5",
            "Q4": "oops",
        }) == {"Q1": [2], "Q3": [4, 5]}

    def test_empty_input(self) -> None:
        assert collect_page_assignments({}) == {}


# ── Regions → page map ────────────────────────────────────────────

def _clip(page_idx: int) -> PageClip:
    return PageClip(page_idx=page_idx, y_top=0.0, y_bottom=100.0)


class TestRegionsToPageMap:
    def test_pages_are_one_based_and_deduped(self) -> None:
        regions = [
            QuestionRegion(
                question_id="Q1",
                clips=[_clip(1), _clip(1), _clip(2)],
            ),
        ]
        pages, clips = regions_to_page_map(regions)
        assert pages == {"Q1": "2,3"}
        assert len(clips["Q1"]) == 3

    def test_clipless_region_is_skipped_entirely(self) -> None:
        # A phantom "" entry would count as a detected question and hide the
        # real shortfall from the user.
        regions = [
            QuestionRegion(question_id="Q1", clips=[_clip(0)]),
            QuestionRegion(question_id="Q2", clips=[]),
        ]
        pages, clips = regions_to_page_map(regions)
        assert pages == {"Q1": "1"}
        assert "Q2" not in pages
        assert "Q2" not in clips


# ── MCQ merge ─────────────────────────────────────────────────────

class TestMergeMcqAnswers:
    def test_manual_overrides_detected(self) -> None:
        assert merge_mcq_answers({"Q1": "A"}, {"Q1": "B"}) == {"Q1": "B"}

    def test_manual_fills_gaps(self) -> None:
        assert merge_mcq_answers({"Q1": "A"}, {"Q2": "C"}) == {
            "Q1": "A", "Q2": "C",
        }

    def test_invalid_manual_is_ignored(self) -> None:
        merged = merge_mcq_answers({"Q1": "A"}, {"Q1": "", "Q2": "9"})
        assert merged == {"Q1": "A"}

    def test_detected_is_not_mutated(self) -> None:
        detected = {"Q1": "A"}
        merge_mcq_answers(detected, {"Q2": "B"})
        assert detected == {"Q1": "A"}


# ── Score summary ─────────────────────────────────────────────────

def _result(qid: str, total: int, max_marks: int) -> QuestionResult:
    return QuestionResult(
        question=qid,
        marks=[MarkDetail(code="M1", awarded=True, reason="ok")],
        total=total,
        max=max_marks,
    )


class TestSummariseScores:
    def test_sums_without_overrides(self) -> None:
        totals = summarise_scores([_result("Q1", 3, 5), _result("Q2", 4, 4)])
        assert totals.score == 7
        assert totals.max_score == 9

    def test_override_wins_per_question(self) -> None:
        totals = summarise_scores(
            [_result("Q1", 3, 5), _result("Q2", 4, 4)],
            {"Q1": 5},
        )
        assert totals.score == 9

    def test_percentage(self) -> None:
        assert summarise_scores([_result("Q1", 3, 4)]).percentage == 75.0

    def test_zero_max_does_not_divide_by_zero(self) -> None:
        assert ScoreSummary(score=0, max_score=0).percentage == 0.0

    def test_empty_run(self) -> None:
        totals = summarise_scores([])
        assert (totals.score, totals.max_score, totals.percentage) == (
            0, 0, 0.0,
        )


# ── Grading run ───────────────────────────────────────────────────

@dataclass
class _FakeConfig:
    """Stands in for GraderConfig — grade_paper only reads ``dpi``."""

    dpi: int = 200


class _FakeRenderer:
    """Records which render path each question took."""

    def __init__(self) -> None:
        self.region_calls: list[str] = []
        self.page_calls: list[list[int]] = []

    def render_regions(
        self, source: bytes, clips: list[PageClip], dpi: int = 200,
    ) -> list[bytes]:
        self.region_calls.append(f"{len(clips)} clips")
        return [b"png"]

    def render_pages(
        self, source: bytes, page_numbers: list[int], dpi: int = 200,
    ) -> list[bytes]:
        self.page_calls.append(list(page_numbers))
        return [b"png"]


def _paper_config(*qids: str) -> PaperConfig:
    return PaperConfig(
        paper_id="9709_s24_qp_12",
        total_marks=5 * len(qids),
        questions={
            qid: QuestionConfig(mark_scheme=f"scheme {qid}", max_marks=5)
            for qid in qids
        },
    )


@pytest.fixture
def _stub_grader(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace the LLM call; returns the list of graded question ids."""
    graded: list[str] = []

    def _fake_grade(*, question_id: str, **_kw: object) -> str:
        graded.append(question_id)
        return (
            f'{{"question": "{question_id}", "marks": [], '
            f'"total": 3, "max": 5}}'
        )

    monkeypatch.setattr(workflow, "grade_question", _fake_grade)
    return graded


class TestGradePaper:
    def _run(
        self,
        renderer: _FakeRenderer,
        clips: dict[str, list[PageClip]],
        qids: tuple[str, ...] = ("Q1", "Q2"),
    ) -> workflow.GradeOutcome:
        return grade_paper(
            config=_FakeConfig(),  # type: ignore[arg-type]
            paper_config=_paper_config(*qids),
            paper_type=PaperType.MATH,
            pdf_bytes=b"%PDF",
            question_ids=list(qids),
            assignments={q: [1] for q in qids},
            clips=clips,
            renderer=renderer,
        )

    def test_prefers_clips_over_whole_pages(
        self, _stub_grader: list[str],
    ) -> None:
        renderer = _FakeRenderer()
        # Q1 has segmentation clips, Q2 does not.
        outcome = self._run(renderer, {"Q1": [_clip(0), _clip(1)]})

        assert outcome.ok
        assert len(outcome.results) == 2
        assert renderer.region_calls == ["2 clips"]
        assert renderer.page_calls == [[1]]

    def test_progress_reports_each_question_then_completion(
        self, _stub_grader: list[str],
    ) -> None:
        seen: list[tuple[int, int, str]] = []
        grade_paper(
            config=_FakeConfig(),  # type: ignore[arg-type]
            paper_config=_paper_config("Q1", "Q2"),
            paper_type=PaperType.MATH,
            pdf_bytes=b"%PDF",
            question_ids=["Q1", "Q2"],
            assignments={"Q1": [1], "Q2": [2]},
            clips={},
            renderer=_FakeRenderer(),
            on_progress=lambda d, t, q: seen.append((d, t, q)),
        )
        assert seen == [(0, 2, "Q1"), (1, 2, "Q2"), (2, 2, "")]

    def test_failure_keeps_earlier_results_and_names_the_question(
        self, _stub_grader: list[str],
    ) -> None:
        class _Boom(_FakeRenderer):
            def render_pages(
                self, source: bytes, page_numbers: list[int], dpi: int = 200,
            ) -> list[bytes]:
                if len(self.page_calls) == 1:
                    raise RuntimeError("render stalled")
                return super().render_pages(source, page_numbers, dpi)

        outcome = self._run(_Boom(), {}, ("Q1", "Q2", "Q3"))

        assert not outcome.ok
        assert outcome.failed_question == "Q2"
        assert outcome.error is not None
        assert "render stalled" in outcome.error
        # Q1 was already graded — that work is not thrown away.
        assert [r.question for r in outcome.results] == ["Q1"]

    def test_empty_question_list_is_a_clean_no_op(
        self, _stub_grader: list[str],
    ) -> None:
        outcome = grade_paper(
            config=_FakeConfig(),  # type: ignore[arg-type]
            paper_config=_paper_config(),
            paper_type=PaperType.MATH,
            pdf_bytes=b"%PDF",
            question_ids=[],
            assignments={},
            clips={},
            renderer=_FakeRenderer(),
        )
        assert outcome.ok
        assert outcome.results == []
