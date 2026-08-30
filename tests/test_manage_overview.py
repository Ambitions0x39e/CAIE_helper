"""Tests for the 管理 tab's two pieces of real logic.

Both are silent when wrong: a饼图 whose slices don't add up still draws a full
ring (the last arc just overshoots), and a subject that falls through to the
fallback icon still shows *an* icon. Neither shows up in a screenshot.
"""
from __future__ import annotations

import datetime

import flet as ft
import pytest

from app_flet.tabs.manage.overview import _tally
from app_flet.tabs.manage.paper_icon import subject_icon
from core.models import PaperRecord

_NOW = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)


def _done(paper_id: str, raw: float, total: float) -> PaperRecord:
    return PaperRecord(
        paper_id=paper_id, status="Completed",
        score_raw=raw, score_total=total, timestamp=_NOW,
    )


def _pending(paper_id: str) -> PaperRecord:
    return PaperRecord(paper_id=paper_id, status="Pending")


class TestTally:
    """每张卷各占一份，三块必须正好拼成总数。"""

    def test_slices_sum_to_total(self) -> None:
        records = [
            _done("9702_s24_qp_11", 40, 50),
            _done("9709_s24_qp_12", 30, 60),
            _pending("9701_s24_qp_21"),
        ]
        tally = _tally(records)
        assert tally.total == 3
        assert tally.earned + tally.lost + tally.pending == pytest.approx(3)

    def test_earned_is_the_score_rate_not_the_paper_count(self) -> None:
        # 一张 80%、一张 50% → 1.3 份绿，0.7 份红。按卷数算的话会是 2 和 0。
        tally = _tally([
            _done("9702_s24_qp_11", 40, 50),
            _done("9709_s24_qp_12", 30, 60),
        ])
        assert tally.earned == pytest.approx(1.3)
        assert tally.lost == pytest.approx(0.7)

    def test_pending_papers_have_no_marks_to_split(self) -> None:
        # Pending 的记录在 data.csv 里没有满分，所以它整份都是灰的。
        tally = _tally([_pending("9702_s24_qp_11")])
        assert (tally.earned, tally.lost, tally.pending) == (0.0, 0.0, 1)

    def test_empty_store(self) -> None:
        tally = _tally([])
        assert (tally.total, tally.earned, tally.lost, tally.pending) == (
            0, 0.0, 0.0, 0,
        )


class TestSubjectIcon:
    """关键词表是有序的，长的那条得排在短的前面。"""

    def test_further_maths_does_not_fall_into_maths(self) -> None:
        assert subject_icon("9231") != subject_icon("9709")

    def test_same_subject_at_both_levels_shares_an_icon(self) -> None:
        # 0620 和 9701 都是化学 —— 按科目名匹配才有这个性质，按号码没有。
        assert subject_icon("0620") == subject_icon("9701")

    def test_unknown_syllabus_falls_back(self) -> None:
        assert subject_icon("0000") == ft.Icons.DESCRIPTION
