"""Has one component got better? A Wilcoxon rank-sum test on its trend.

The papers, oldest first, are split into an earlier and a later half, and the
test asks whether the later half sits higher on the grade scale
(``modules.grade_lines.position``) — the score against each paper's own
boundaries, so a run of easy papers does not pass for progress.

H0: both halves come from one distribution. H1: the later half is higher.
One-tailed, at 5%. Pure: numbers in, numbers out.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from statistics import median

from pydantic import BaseModel

#: The fewest papers tested. 3 against 3 is the smallest split whose most
#: extreme ordering still reaches 5% (1 in 20).
MIN_PAPERS = 6
SIGNIFICANCE = 0.05
#: Up to this many papers in the earlier half the p-value is exact; above
#: it, the normal approximation the syllabus uses for samples over 10.
_EXACT_UP_TO = 10


class Progress(BaseModel):
    early: int
    late: int
    early_median: float
    late_median: float
    #: Rank sum of the earlier half; small when the later papers rank higher.
    w: float
    #: One-tailed: the chance of a W this small with no progress.
    p: float
    improved: bool


def _ranks(values: Sequence[float]) -> list[float]:
    """1-based ranks, ties sharing the average of the ranks they span."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def _exact_lower_tail(ranks: Sequence[float], m: int, w: float) -> float:
    """P(rank sum of m ranks drawn from *ranks* <= w), counting every subset.

    Ranks are doubled so a tie's half-rank is an integer; ``ways[k][s]`` is
    the number of k-subsets summing to s.
    """
    doubled = [round(r * 2) for r in ranks]
    ways: list[dict[int, int]] = [{0: 1}] + [{} for _ in range(m)]
    for r in doubled:
        for k in range(m, 0, -1):
            for s, n in ways[k - 1].items():
                ways[k][s + r] = ways[k].get(s + r, 0) + n
    limit = round(w * 2)
    hits = sum(n for s, n in ways[m].items() if s <= limit)
    return hits / math.comb(len(ranks), m)


def _normal_lower_tail(m: int, n: int, w: float) -> float:
    """ponytail: no tie correction to the variance; ties only make this
    slightly conservative."""
    mean = m * (m + n + 1) / 2
    sd = math.sqrt(m * n * (m + n + 1) / 12)
    z = (w + 0.5 - mean) / sd
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def progress(positions: Sequence[float]) -> Progress | None:
    """*positions* oldest first; None below :data:`MIN_PAPERS`."""
    if len(positions) < MIN_PAPERS:
        return None
    m = len(positions) // 2
    early, late = positions[:m], positions[m:]
    ranks = _ranks(positions)
    w = sum(ranks[:m])
    p = (
        _exact_lower_tail(ranks, m, w)
        if m <= _EXACT_UP_TO
        else _normal_lower_tail(m, len(late), w)
    )
    return Progress(
        early=m,
        late=len(late),
        early_median=median(early),
        late_median=median(late),
        w=w,
        p=p,
        improved=p < SIGNIFICANCE,
    )
