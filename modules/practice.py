"""专项练习: every question on chosen topics, across a range of sessions.

The 错题本 can only draw on papers that were graded, because a question's
topic is something the grader decides. Practice draws on papers never done,
so it classifies them itself — one vision call per paper, cached on disk —
and hands the picks to :mod:`modules.question_pdf`.

Nothing here may import ``app_web``.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable, Collection, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Final, NamedTuple

from core.settings import GraderConfig, app_settings
from modules.downloader import QueryResult, query_available
from modules.question_pdf import crops_for_paper

if TYPE_CHECKING:
    from modules.marking.syllabus_parser import SyllabusInfo
    from modules.marking.workflow import Renderer

#: CIE's sessions in calendar order within a year.
SEASONS: Final = "msw"


class Picked(NamedTuple):
    """One question chosen for the practice set — a ``QuestionRef``."""

    paper_id: str
    question_id: str


def _season_index(season: str) -> int:
    # ``in`` on a str is substring matching: "" and "ms" would pass a bare check.
    if len(season) != 1 or season not in SEASONS:
        raise ValueError(f"未知考季: {season!r}")
    return SEASONS.index(season)


def sessions_between(
    start_year: int, start_season: str, end_year: int, end_season: str
) -> list[tuple[str, str]]:
    """Every (year, season) from start to end inclusive, in calendar order."""
    start = start_year * 3 + _season_index(start_season)
    end = end_year * 3 + _season_index(end_season)
    return [(str(i // 3), SEASONS[i % 3]) for i in range(start, end + 1)]


def papers_in_range(
    subject: str,
    component: str,
    sessions: Sequence[tuple[str, str]],
    query: Callable[[str, str, str], QueryResult] = query_available,  # type: ignore[assignment]
) -> tuple[list[str], list[str]]:
    """The QP ids of *component* (``"4"`` → 41, 42, 43 …) in every session.

    A session that fails to list is a warning: the others are still worth
    practising from. A session that lists nothing (a future one, or a March
    session with no such component) contributes nothing, silently.
    """
    ids: list[str] = []
    warnings: list[str] = []
    for year, season in sessions:
        result = query(subject, year, season)
        if not result.success:
            warnings.append(f"{season}{year[-2:]}: {result.error}")
            continue
        ids.extend(sorted(
            e.paper_id for e in result.entries
            if e.kind == "qp" and e.paper_id.split("_")[3].startswith(component)
        ))
    return ids, warnings


def component_topics(info: SyllabusInfo | None, component: str) -> dict[str, str]:
    """Topic id → name for the topics the syllabus maps to *component*."""
    if info is None:
        return {}
    return {
        tid: info.topics[tid].name
        for tid in info.component_topics.get(component, [])
        if tid in info.topics
    }


def select(
    classified: Mapping[str, Mapping[str, Sequence[str]]],
    wanted: Collection[str],
) -> list[Picked]:
    """Every question tagged with any of *wanted*, paper by paper."""
    return [
        Picked(paper_id, question_id)
        for paper_id, questions in classified.items()
        for question_id, topics in questions.items()
        if any(t in wanted for t in topics)
    ]


#: Enough to read a diagram's labels; the crops are already free of answer
#: space, so a 9709 P4 comes to ~2.5k image tokens.
_DPI: Final = 120

_PROMPT: Final = """下面按顺序给出一份 CIE 试卷每道大题的截图。{mapping}

可选 topic（id: 名称）：
{topics}

给每道大题选出它实际考到的 topic。一道题可以考到多个 topic，只选真正考到的。
只输出一个 JSON 对象：键是题号，值是 topic id 列表，例如
{{"Q1": ["4.1"], "Q2": ["4.2", "4.5"]}}"""

_JSON_RE = re.compile(r"\{.*\}", re.S)

type Call = Callable[[GraderConfig, list[bytes], str], str]


def _cache_file(paper_id: str) -> Path:
    return app_settings.topic_cache_dir / f"{paper_id}.json"


def cached_classification(
    paper_id: str, topics: Mapping[str, str]
) -> dict[str, list[str]] | None:
    """The stored classification, if it was made against these same topics.

    The topic list is stored with it: a syllabus re-read that renames or
    adds a topic makes every old answer suspect, so it is a miss.
    """
    try:
        data = json.loads(_cache_file(paper_id).read_text("utf-8"))
    except (OSError, ValueError):
        return None
    if data.get("topics") != dict(topics):
        return None
    questions = data.get("questions")
    return questions if isinstance(questions, dict) else None


def _save(
    paper_id: str, topics: Mapping[str, str], questions: dict[str, list[str]]
) -> None:
    path = _cache_file(paper_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"topics": dict(topics), "questions": questions}
    path.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")


def _bare(question_id: str) -> str:
    return question_id.strip().removeprefix("Q")


def _parse(
    raw: str, question_ids: Sequence[str], topics: Mapping[str, str]
) -> dict[str, list[str]]:
    """The model's JSON, kept to known questions and known topic ids."""
    match = _JSON_RE.search(raw)
    if match is None:
        raise ValueError(f"模型没有返回 JSON: {raw[:80]!r}")
    try:
        data = json.loads(match.group())
    except ValueError as exc:
        raise ValueError(f"模型返回的 JSON 读不了: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"模型返回的不是 JSON 对象: {raw[:80]!r}")
    answers = {_bare(str(k)): v for k, v in data.items()}
    out: dict[str, list[str]] = {}
    for qid in question_ids:
        picked = answers.get(qid, [])
        if isinstance(picked, str):
            picked = [picked]
        out[qid] = [str(t) for t in picked if str(t) in topics]
    return out


def classify_paper(
    paper_id: str,
    qp_path: str,
    topics: Mapping[str, str],
    *,
    config: GraderConfig,
    renderer: Renderer,
    call: Call | None = None,
) -> dict[str, list[str]]:
    """Main question → the topics it examines, for one paper.

    One vision call for the whole paper: every question's crop, in order,
    with the prompt saying which images are which question. Cached per
    paper — see :func:`cached_classification`.
    """
    cached = cached_classification(paper_id, topics)
    if cached is not None:
        return cached

    from modules.marking.page_segmenter import PageClip

    crops, _ = crops_for_paper(paper_id, qp_path)
    pngs: list[bytes] = []
    spans: list[str] = []
    ids: list[str] = []
    for crop in crops:
        images = renderer.render_regions(qp_path, [
            PageClip(page_idx=b.page_idx, y_top=b.y_top, y_bottom=b.y_bottom)
            for b in crop.bands
        ], _DPI)
        if not images:
            continue
        first, last = len(pngs) + 1, len(pngs) + len(images)
        span = f"图 {first}" if first == last else f"图 {first}–{last}"
        spans.append(f"{span} 是 Q{crop.question_id}")
        ids.append(crop.question_id)
        pngs.extend(images)
    if not pngs:
        raise ValueError("定位不到任何一道题")

    prompt = _PROMPT.format(
        mapping="；".join(spans) + "。",
        topics="\n".join(f"{tid}: {name}" for tid, name in topics.items()),
    )
    if call is None:
        from modules.marking.ms_parser import _call_vl

        call = _call_vl
    questions = _parse(call(config, pngs, prompt), ids, topics)
    _save(paper_id, topics, questions)
    return questions
