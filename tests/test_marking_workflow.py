"""Tests for modules.marking.workflow.

The module takes explicit arguments and imports nothing from the UI layer,
which is what lets the whole grading flow be driven from here with stubs.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

import pytest

from core.models import PaperType
from modules.marking import workflow
from modules.marking.grader import MarkDetail, QuestionResult
from modules.marking.ms_parser import PaperConfig, QuestionConfig
from modules.marking.page_segmenter import PageClip, QuestionRegion
from modules.marking.syllabus_parser import SyllabusInfo, SyllabusTopic
from modules.marking.workflow import (
    ScoreSummary,
    collect_page_assignments,
    component_paper_number,
    grade_paper,
    merge_mcq_answers,
    parse_page_spec,
    regions_to_page_map,
    summarise_scores,
    topics_for_paper,
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
        self,
        source: str | bytes | Path,
        clips: list[PageClip],
        dpi: int = 200,
    ) -> list[bytes]:
        self.region_calls.append(f"{len(clips)} clips")
        return [b"png"]

    def render_pages(
        self,
        source: str | bytes | Path,
        page_numbers: list[int],
        dpi: int = 200,
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
        on_progress: object = None,
    ) -> workflow.GradeOutcome:
        return grade_paper(
            config=_FakeConfig(),  # type: ignore[arg-type]
            paper_config=_paper_config(*qids),
            paper_type=PaperType.MATH,
            pdf_source=b"%PDF",
            # Distinct page per question so a renderer can single one out by
            # the page number it was asked to render.
            question_ids=list(qids),
            assignments={q: [i + 1] for i, q in enumerate(qids)},
            clips=clips,
            renderer=renderer,
            on_progress=on_progress,  # type: ignore[arg-type]
        )

    def test_prefers_clips_over_whole_pages(
        self, _stub_grader: list[str],
    ) -> None:
        renderer = _FakeRenderer()
        # Q1 has segmentation clips, Q2 does not (assignments give it page 2).
        outcome = self._run(renderer, {"Q1": [_clip(0), _clip(1)]})

        assert outcome.ok
        assert len(outcome.results) == 2
        assert renderer.region_calls == ["2 clips"]
        assert renderer.page_calls == [[2]]

    def test_grades_questions_concurrently(
        self, _stub_grader: list[str],
    ) -> None:
        """Three renders must be in flight at once, not one after another.

        Each render blocks on a 3-party barrier before returning. A
        sequential implementation only ever has one render in flight, so the
        barrier never fills and every question times out; this only passes
        when grade_paper genuinely runs the three concurrently.
        """
        barrier = threading.Barrier(3, timeout=2)

        class _BarrierRenderer(_FakeRenderer):
            def render_pages(
                self,
        source: str | bytes | Path,
        page_numbers: list[int],
        dpi: int = 200,
            ) -> list[bytes]:
                barrier.wait()
                return super().render_pages(source, page_numbers, dpi)

        outcome = self._run(_BarrierRenderer(), {}, ("Q1", "Q2", "Q3"))

        assert outcome.ok
        assert len(outcome.results) == 3

    def test_one_failure_does_not_stop_the_others(
        self, _stub_grader: list[str],
    ) -> None:
        class _FailsOnPageTwo(_FakeRenderer):
            def render_pages(
                self,
        source: str | bytes | Path,
        page_numbers: list[int],
        dpi: int = 200,
            ) -> list[bytes]:
                if page_numbers == [2]:
                    raise RuntimeError("render stalled")
                return super().render_pages(source, page_numbers, dpi)

        outcome = self._run(_FailsOnPageTwo(), {}, ("Q1", "Q2", "Q3"))

        assert not outcome.ok
        assert outcome.failures == [
            workflow.QuestionFailure(question="Q2", error="render stalled"),
        ]
        # Q1 and Q3 still got graded, in original order, despite Q2 failing.
        assert [r.question for r in outcome.results] == ["Q1", "Q3"]

    def test_multiple_failures_are_all_collected(
        self, _stub_grader: list[str],
    ) -> None:
        class _AlwaysFails(_FakeRenderer):
            def render_pages(
                self,
        source: str | bytes | Path,
        page_numbers: list[int],
        dpi: int = 200,
            ) -> list[bytes]:
                raise RuntimeError(f"boom {page_numbers}")

        outcome = self._run(_AlwaysFails(), {}, ("Q1", "Q2"))

        assert not outcome.ok
        assert {f.question for f in outcome.failures} == {"Q1", "Q2"}
        assert outcome.results == []

    def test_progress_reports_each_completion_then_a_final_call(
        self, _stub_grader: list[str],
    ) -> None:
        seen: list[tuple[int, int, str]] = []
        lock = threading.Lock()

        def _cb(done: int, total: int, qid: str) -> None:
            with lock:
                seen.append((done, total, qid))

        outcome = self._run(_FakeRenderer(), {}, ("Q1", "Q2"), on_progress=_cb)

        assert outcome.ok
        # Two per-question completions (order not guaranteed under
        # concurrency) plus one final "fully done" call.
        assert len(seen) == 3
        assert seen[-1] == (2, 2, "")
        per_question = seen[:-1]
        assert {qid for _, _, qid in per_question} == {"Q1", "Q2"}
        assert sorted(done for done, _, _ in per_question) == [1, 2]
        assert all(total == 2 for _, total, _ in per_question)

    def test_empty_question_list_is_a_clean_no_op(
        self, _stub_grader: list[str],
    ) -> None:
        seen: list[tuple[int, int, str]] = []
        outcome = grade_paper(
            config=_FakeConfig(),  # type: ignore[arg-type]
            paper_config=_paper_config(),
            paper_type=PaperType.MATH,
            pdf_source=b"%PDF",
            question_ids=[],
            assignments={},
            clips={},
            renderer=_FakeRenderer(),
            on_progress=lambda d, t, q: seen.append((d, t, q)),
        )
        assert outcome.ok
        assert outcome.results == []
        assert seen == [(0, 0, "")]


# ── Syllabus topics ───────────────────────────────────────────────

def _syllabus() -> SyllabusInfo:
    """A 9709-shaped syllabus: paper 1 → section 1, paper 4 → section 4."""
    names = {
        "1.1": "Quadratics",
        "1.2": "Functions",
        "4.1": "Forces and equilibrium",
    }
    return SyllabusInfo(
        subject_id="9709",
        topics={
            tid: SyllabusTopic(topic_id=tid, name=name)
            for tid, name in names.items()
        },
        component_topics={"1": ["1.1", "1.2"], "4": ["4.1"]},
    )


class TestComponentPaperNumber:
    @pytest.mark.parametrize(
        ("paper_id", "expected"),
        [
            ("9709_s25_qp_12", "1"),
            ("9701_s25_qp_21", "2"),
            ("9709_w24_qp_43", "4"),
        ],
    )
    def test_first_digit_of_the_component(
        self, paper_id: str, expected: str
    ) -> None:
        assert component_paper_number(paper_id) == expected

    @pytest.mark.parametrize(
        "paper_id", ["9709/12/M/J/25", "9709_s25_gt", "", "nonsense"]
    )
    def test_shapes_that_are_not_a_downloaded_id(self, paper_id: str) -> None:
        assert component_paper_number(paper_id) is None


class TestTopicsForPaper:
    def test_named_topics_for_the_papers_component(self) -> None:
        assert topics_for_paper(_syllabus(), "9709_s25_qp_12") == {
            "1.1": "Quadratics",
            "1.2": "Functions",
        }

    @pytest.mark.parametrize(
        ("info", "paper_id"),
        [
            (None, "9709_s25_qp_12"),          # no syllabus uploaded
            (_syllabus(), None),               # MS was uploaded, not downloaded
            (_syllabus(), "9709/12/M/J/25"),   # cover-page id, not a file id
            (_syllabus(), "9709_s25_qp_31"),   # component the syllabus omits
        ],
    )
    def test_every_unresolvable_case_is_none_not_empty(
        self, info: SyllabusInfo | None, paper_id: str | None
    ) -> None:
        """None, so the prompt drops the section; {} would render a heading."""
        assert topics_for_paper(info, paper_id) is None


@pytest.fixture
def _grader_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    """Record every keyword ``grade_paper`` passes to ``grade_question``."""
    calls: list[dict[str, object]] = []

    def _fake_grade(**kwargs: object) -> str:
        calls.append(kwargs)
        return (
            f'{{"question": "{kwargs["question_id"]}", "marks": [], '
            f'"total": 3, "max": 5, "topic": "1.1"}}'
        )

    monkeypatch.setattr(workflow, "grade_question", _fake_grade)
    return calls


class TestGradePaperTopicPlumbing:
    """What reaches ``grade_question``, not what comes back from it.

    Asserting on the returned ``QuestionResult.topic`` would pass just as
    well if ``grade_paper`` never forwarded anything, since the stubbed reply
    carries a topic of its own.
    """

    def _run(
        self,
        calls_fixture: list[dict[str, object]],
        **kwargs: object,
    ) -> workflow.GradeOutcome:
        return grade_paper(
            config=_FakeConfig(),  # type: ignore[arg-type]
            paper_config=_paper_config("Q1", "Q2"),
            paper_type=PaperType.MATH,
            pdf_source=b"%PDF",
            question_ids=["Q1", "Q2"],
            assignments={"Q1": [1], "Q2": [2]},
            clips={},
            renderer=_FakeRenderer(),
            **kwargs,  # type: ignore[arg-type]
        )

    def test_every_question_is_graded_against_its_papers_topics(
        self, _grader_calls: list[dict[str, object]],
    ) -> None:
        self._run(
            _grader_calls,
            syllabus_info=_syllabus(),
            paper_id="9709_s25_qp_12",
        )

        assert len(_grader_calls) == 2
        assert [c["question_id"] for c in _grader_calls] == ["Q1", "Q2"]
        for call in _grader_calls:
            assert call["topic_list"] == {
                "1.1": "Quadratics",
                "1.2": "Functions",
            }

    def test_another_component_gets_that_components_topics(
        self, _grader_calls: list[dict[str, object]],
    ) -> None:
        """Not a fixed list: paper 4 must get section 4, not section 1."""
        self._run(
            _grader_calls,
            syllabus_info=_syllabus(),
            paper_id="9709_s25_qp_43",
        )

        for call in _grader_calls:
            assert call["topic_list"] == {"4.1": "Forces and equilibrium"}

    def test_without_a_syllabus_nothing_is_passed(
        self, _grader_calls: list[dict[str, object]],
    ) -> None:
        self._run(_grader_calls, paper_id="9709_s25_qp_12")

        assert _grader_calls
        for call in _grader_calls:
            assert call["topic_list"] is None

    def test_an_uploaded_mark_scheme_has_no_paper_id_and_no_topics(
        self, _grader_calls: list[dict[str, object]],
    ) -> None:
        self._run(_grader_calls, syllabus_info=_syllabus())

        assert _grader_calls
        for call in _grader_calls:
            assert call["topic_list"] is None

    def test_the_topic_the_model_returns_reaches_the_result(
        self, _grader_calls: list[dict[str, object]],
    ) -> None:
        outcome = self._run(
            _grader_calls,
            syllabus_info=_syllabus(),
            paper_id="9709_s25_qp_12",
        )

        assert [r.topic for r in outcome.results] == ["1.1", "1.1"]
