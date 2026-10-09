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

from pydantic import BaseModel, Field, model_validator

from core.settings import GraderConfig, app_settings
from modules.downloader import QueryResult, query_available
from modules.question_pdf import build_export, crops_for_paper

if TYPE_CHECKING:
    from core.storage import CSVStore
    from modules.downloader import PaperDownloader
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
    if not isinstance(data, dict):
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


def _as_q(question_id: str) -> str:
    """``"3"``, ``"Q3"`` and ``" q3 "`` are the same question: ``"Q3"``."""
    return "Q" + question_id.strip().upper().removeprefix("Q")


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
    answers = {_as_q(str(k)): v for k, v in data.items()}
    if not any(qid in answers for qid in question_ids):
        # ``{}`` and keys like "Question 1" would otherwise read as "no
        # question examines any topic" and be cached as such.
        raise ValueError(f"模型的回答里没有任何一道题: {raw[:80]!r}")
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
        spans.append(f"{span} 是 {crop.question_id}")
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


type Progress = Callable[[str, int, int, str], None]


class PracticeRequest(BaseModel):
    """What the 练习 tab asks for."""

    subject: str
    #: The component's first digit: "4" covers 41, 42, 43 …
    component: str = Field(pattern=r"^\d$")
    from_year: int
    from_season: str
    to_year: int
    to_season: str
    topic_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _range_runs_forward(self) -> PracticeRequest:
        start = (self.from_year, _season_index(self.from_season))
        end = (self.to_year, _season_index(self.to_season))
        if start > end:
            raise ValueError("起始考季晚于结束考季")
        return self


def _on_disk(
    paper_ids: Sequence[str],
    store: CSVStore,
    downloader: PaperDownloader,
    on_progress: Progress,
    warnings: list[str],
) -> dict[str, tuple[str, str]]:
    """paper_id → (qp_path, ms_path), downloading whatever is missing."""
    from modules.downloader import DownloadRequest

    known = {r.paper_id: r for r in store.load_all()}
    paths: dict[str, tuple[str, str]] = {}
    missing = [
        pid for pid in paper_ids
        if pid not in known or not Path(known[pid].qp_path).is_file()
    ]
    for done, pid in enumerate(missing, 1):
        on_progress("下载", done, len(missing), pid)
        result = downloader.download(DownloadRequest(paper_id=pid))
        if not result.success or not result.qp_path:
            # A paper the store already has cannot be added again, so a stale
            # record's re-download reports failure with the file back on disk.
            if pid in known and Path(known[pid].qp_path).is_file():
                continue
            warnings.append(f"{pid}: 下载失败（{result.error}）")
            continue
        paths[pid] = (result.qp_path, result.ms_path or "")
    for pid in paper_ids:
        if pid in known and pid not in paths and Path(known[pid].qp_path).is_file():
            paths[pid] = (known[pid].qp_path, known[pid].ms_path)
    return {pid: paths[pid] for pid in paper_ids if pid in paths}


def _parse_answers(
    paper_ids: Sequence[str],
    ms_path_of: Mapping[str, str],
    config: GraderConfig,
    renderer: Renderer,
    on_progress: Progress,
) -> list[str]:
    """Parse the mark schemes the export will need and has no parse of.

    Returns warnings. A paper whose grading path is unknown cannot be parsed,
    and MCQ parses are never cached, so neither gets an answer page —
    ``build_export`` names the questions that lack one.
    """
    from modules.marking.ms_parser import cached_mark_scheme, parse_mark_scheme
    from modules.marking.syllabus_parser import resolve_grading_type

    todo = [
        pid for pid in paper_ids
        if ms_path_of.get(pid) and cached_mark_scheme(ms_path_of[pid]) is None
    ]
    warnings: list[str] = []
    for done, pid in enumerate(todo, 1):
        on_progress("答案", done, len(todo), pid)
        paper_type = resolve_grading_type(pid)
        if paper_type is None:
            warnings.append(f"{pid}: 不知道这份卷的批改类型，没有解析 mark scheme")
            continue
        try:
            parse_mark_scheme(
                ms_path_of[pid], paper_type=paper_type,
                grader_config=config, renderer=renderer,
            )
        except Exception as exc:  # noqa: BLE001 — one paper's answers, not the set
            warnings.append(f"{pid}: mark scheme 解析失败（{exc}）")
    return warnings


def build_practice(
    request: PracticeRequest,
    topics: Mapping[str, str],
    *,
    store: CSVStore,
    downloader: PaperDownloader,
    config: GraderConfig,
    renderer: Renderer,
    on_progress: Progress,
    query: Callable[[str, str, str], QueryResult] = query_available,  # type: ignore[assignment]
) -> tuple[bytes, int, list[str]]:
    """The whole practice set: (PDF, number of questions, warnings).

    Every failure short of "nothing at all" is a warning, the way the
    错题本 export reports a paper it could not use.

    Raises:
        ValueError: no question in range examines any of the chosen topics,
            or nothing could be exported.
    """
    sessions = sessions_between(
        request.from_year, request.from_season, request.to_year, request.to_season,
    )
    paper_ids, warnings = papers_in_range(
        request.subject, request.component, sessions, query=query,
    )
    paths = _on_disk(paper_ids, store, downloader, on_progress, warnings)

    classified: dict[str, dict[str, list[str]]] = {}
    for done, (pid, (qp_path, _)) in enumerate(paths.items(), 1):
        on_progress("分类", done, len(paths), pid)
        try:
            classified[pid] = classify_paper(
                pid, qp_path, topics, config=config, renderer=renderer,
            )
        except Exception as exc:  # noqa: BLE001 — one paper, not the set
            warnings.append(f"{pid}: 分类失败（{exc}）")

    picks = select(classified, set(request.topic_ids))
    if not picks:
        raise ValueError("这个范围里没有考到所选 topic 的题")

    chosen = list(dict.fromkeys(p.paper_id for p in picks))
    ms_path_of = {pid: paths[pid][1] for pid in chosen}
    warnings += _parse_answers(chosen, ms_path_of, config, renderer, on_progress)

    data, export_warnings = build_export(
        picks, {pid: paths[pid][0] for pid in chosen}, ms_path_of,
    )
    return data, len(picks), warnings + export_warnings
