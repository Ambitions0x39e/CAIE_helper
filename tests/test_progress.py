"""The rank-sum test behind each component's progress line."""

from __future__ import annotations

import random
from itertools import combinations

import pytest

from modules.progress import _exact_lower_tail, _ranks, progress


def test_ties_share_the_average_rank() -> None:
    assert _ranks([3.0, 1.0, 3.0, 2.0]) == [3.5, 1.0, 3.5, 2.0]


def test_five_against_five_matches_the_critical_value_table() -> None:
    # The printed table: for m = n = 5, one-tailed 5%, reject when W <= 19.
    ranks = [float(r) for r in range(1, 11)]
    assert _exact_lower_tail(ranks, 5, 19) <= 0.05
    assert _exact_lower_tail(ranks, 5, 20) > 0.05


def test_the_exact_tail_counts_every_split_including_ties() -> None:
    rng = random.Random(1)
    values = [float(rng.randint(1, 5)) for _ in range(9)]
    ranks = _ranks(values)
    w = sum(ranks[:4])
    brute = [sum(c) <= w for c in combinations(ranks, 4)]
    assert _exact_lower_tail(ranks, 4, w) == pytest.approx(sum(brute) / len(brute))


def test_a_steady_climb_is_progress() -> None:
    result = progress([3.0, 3.1, 3.2, 3.3, 3.4, 3.6, 3.8, 4.0, 4.2, 4.4])
    assert result is not None
    assert (result.early, result.late, result.w) == (5, 5, 15.0)
    assert result.improved


def test_a_flat_run_is_not() -> None:
    result = progress([3.5, 4.0, 3.5, 4.0, 3.5, 4.0, 3.5, 4.0])
    assert result is not None
    assert not result.improved


def test_too_few_papers_are_not_tested() -> None:
    assert progress([3.0, 3.5, 4.0, 4.5, 5.0]) is None


def test_large_samples_use_the_normal_approximation() -> None:
    rising = [i / 10 for i in range(30)]
    result = progress(rising)
    assert result is not None
    assert result.p < 0.001
    assert result.improved
