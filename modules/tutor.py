"""The tutor's notes — where a student keeps going wrong in one component.

Two files per syllabus × component under ``~/.cie_helper/tutor/``:

- ``<subject>_p<N>.json`` — the ledger. Every lost question is filed under a
  mistake pattern of its topic ("结论没结合题目语境"), each pattern listing
  the papers and questions it turned up in.
- ``<subject>_p<N>.md`` — the note the student reads, laid out by code from
  the ledger: a line per topic (``Vectors 3题 7/16分``) and under it the
  patterns seen in two papers or more. A mistake made once is on file but
  not in the note until it happens again.

The ledger is iterated, not rewritten: after each confirmed paper the model
only files that paper's lost questions — into a pattern already on file, or
a new one — and code does all the counting. Re-grading a paper takes its
old filings back out first. With no ledger yet, every paper already graded
is filed, oldest first.

The notes are for the student to read. Nothing in the grading path may read
them — a grader that knows "this student keeps losing marks on Equilibria"
marks Equilibria harder (``tests/test_tutor.py`` pins that).
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path

from openai import OpenAI
from pydantic import BaseModel

from core.models import AttemptRecord
from core.settings import GraderConfig, app_settings
from modules.profile import ComponentProfile, component_profile, component_rows

_ERROR_LABELS = {
    "concept": "概念",
    "method": "方法",
    "slip": "失误",
    "misread": "审题",
    "wording": "表述",
}

_PROMPT = """你是 CIE {subject_id} Paper {component} 的导师，在整理这个学生反复犯的错。

## 已记录的错误模式（按 topic）
{patterns}

## 这份卷子 {paper_id} 的丢分题
{lost}

## 要求
把每道丢分题归到它犯的那种错上。只输出一个 JSON 对象，键是题号，值二选一：
- 已有模式的编号（例如 "p3"），只能选这道题所在 topic 下的；未分类的题可以选
  任何 topic 下的。错法一样就归进去，具体数字、
  小问、题型不同都不影响。
- 一句新的模式描述（不超过 20 字）：已有模式里没有同一种错时才新建。
  写成以后在别的题上还会再犯的那一类错，例如「假设检验结论写法不规范」
  「H1 方向写反」「漏写单位」；不要把这道题的细节写进去，
  例如不要写「Q6a 常数项算错」。这份卷子里几道题犯同一种新错，
  就给它们写一字不差的同一句描述。
依据只能是评语；不要揣测心理、态度或时间分配。不要写 LaTeX 或反斜杠。"""


class Pattern(BaseModel):
    id: str
    topic_id: str | None
    topic_name: str | None = None
    text: str
    #: (paper_id, question_id) of every question filed under it.
    hits: list[tuple[str, str]] = []

    @property
    def papers(self) -> int:
        return len({paper for paper, _ in self.hits})


class Ledger(BaseModel):
    patterns: list[Pattern] = []


def notes_path(subject_id: str, component: str) -> Path:
    return app_settings.base_dir / "tutor" / f"{subject_id}_p{component}.md"


def ledger_path(subject_id: str, component: str) -> Path:
    return notes_path(subject_id, component).with_suffix(".json")


def read_notes(subject_id: str, component: str) -> str | None:
    path = notes_path(subject_id, component)
    return path.read_text(encoding="utf-8") if path.exists() else None


def _label(error_type: str | None) -> str:
    return _ERROR_LABELS.get(error_type or "", "未分类")


def _short(paper_id: str) -> str:
    """``9231_s23_qp_43`` → ``s23_43``."""
    parts = paper_id.split("_")
    return f"{parts[1]}_{parts[3]}" if len(parts) == 4 else paper_id


def lost_questions(rows: Iterable[AttemptRecord]) -> list[AttemptRecord]:
    """The questions worth filing: marks lost, and an answer to judge.
    A blank says nothing about how the student goes wrong."""
    return [r for r in rows if r.score < r.max_score and r.error_type != "blank"]


def build_prompt(
    ledger: Ledger,
    lost: list[AttemptRecord],
    comments: Mapping[tuple[str, str], str],
    *,
    subject_id: str,
    component: str,
    paper_id: str,
) -> str:
    """The request to file *lost* — one paper's questions. The patterns of
    the topics those questions are in are offered, and every topic's when
    one of them is untagged: the grader not placing it doesn't make it a
    different mistake (s23 Q5b and s25 Q5b, one tagged and one not, were
    the same PGF expansion slip)."""
    offered = {r.topic_id for r in lost}
    if None in offered:
        offered |= {p.topic_id for p in ledger.patterns}
    names = {p.topic_id: p.topic_name for p in ledger.patterns}
    names |= {r.topic_id: r.topic_name for r in lost}
    blocks = []
    for topic_id in sorted(offered, key=lambda t: names.get(t) or t or "未分类"):
        name = names.get(topic_id) or topic_id or "未分类"
        on_file = [p for p in ledger.patterns if p.topic_id == topic_id]
        lines = [
            f"{p.id}: {p.text}（{'、'.join(f'{_short(a)} {q}' for a, q in p.hits)}）"
            for p in on_file
        ] or ["（还没有）"]
        blocks.append(f"【{name}】\n" + "\n".join(lines))
    lost_lines = "\n".join(
        "- " + " · ".join(filter(None, [
            r.question_id,
            r.topic_name or "未分类",
            _label(r.error_type),
            f"得 {r.score:g}/{r.max_score:g}",
            comments.get((r.paper_id, r.question_id), ""),
        ]))
        for r in lost
    )
    return _PROMPT.format(
        subject_id=subject_id,
        component=component,
        patterns="\n\n".join(blocks),
        paper_id=paper_id,
        lost=lost_lines,
    )


def parse_reply(raw: str) -> dict[str, str]:
    """The model's ``{"Q6a": "p3", "Q6b": "新的错法"}``; unreadable is empty."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v.strip() for k, v in data.items() if isinstance(v, str) and v.strip()}


_PATTERN_ID_RE = re.compile(r"p\d+")


def file_paper(
    ledger: Ledger, paper_id: str, lost: list[AttemptRecord], reply: Mapping[str, str],
) -> Ledger:
    """*ledger* with *paper_id*'s filings replaced by those in *reply*.

    A tagged question joins only its own topic's patterns — the model was
    shown no others for it; an untagged one may join any. A question the
    reply leaves out stays unfiled.
    """
    patterns = [
        p.model_copy(update={"hits": [h for h in p.hits if h[0] != paper_id]})
        for p in ledger.patterns
    ]
    next_id = 1 + max((int(p.id[1:]) for p in patterns), default=0)
    for r in lost:
        said = reply.get(r.question_id)
        if not said:
            continue
        hit = (paper_id, r.question_id)
        if _PATTERN_ID_RE.fullmatch(said):
            offered = (
                p for p in patterns if r.topic_id is None or p.topic_id == r.topic_id
            )
            match = next((p for p in offered if p.id == said), None)
            if match is not None:
                match.hits.append(hit)
            continue
        # Several questions of this paper given one new description are one
        # pattern, not several that each happened once.
        same = next(
            (p for p in patterns if p.topic_id == r.topic_id and p.text == said), None,
        )
        if same is not None:
            same.hits.append(hit)
            continue
        patterns.append(
            Pattern(
                id=f"p{next_id}", topic_id=r.topic_id, topic_name=r.topic_name,
                text=said, hits=[hit],
            ),
        )
        next_id += 1
    return Ledger(patterns=[p for p in patterns if p.hits])


def render_note(profile: ComponentProfile, ledger: Ledger) -> str:
    """A line per topic, and under it the patterns seen in two papers or
    more, the most papers first."""
    lines: list[str] = []
    for t in profile.topics:
        earned = t.max_score - t.lost
        name = t.topic_name or t.topic_id or "未分类"
        lines.append(f"- {name} {t.questions}题 {earned:g}/{t.max_score:g}分")
        recurring = sorted(
            (p for p in ledger.patterns if p.topic_id == t.topic_id and p.papers >= 2),
            key=lambda p: (-p.papers, -len(p.hits)),
        )
        for p in recurring:
            where = "、".join(f"{_short(a)} {q}" for a, q in p.hits)
            lines.append(f"  - {p.text} ×{len(p.hits)}（{where}）")
    return "\n".join(lines) + "\n"


def _ask(config: GraderConfig, prompt: str) -> dict[str, str]:
    client = OpenAI(
        api_key=config.api_key.get_secret_value(),
        base_url=config.base_url,
        timeout=120.0,
        max_retries=1,
    )
    response = client.chat.completions.create(
        model=config.model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        extra_body={"enable_thinking": False},
    )
    return parse_reply(str(response.choices[0].message.content))


def refresh_notes(
    config: GraderConfig,
    records: Iterable[AttemptRecord],
    comments: Mapping[tuple[str, str], str],
    *,
    subject_id: str,
    component: str,
    paper_id: str,
) -> Path | None:
    """File *paper_id* into the component's ledger and rewrite its note.

    ``records`` is every attempt row, ``comments`` every grader comment by
    (paper, question). Returns the note's path, or None when the component
    has nothing graded.
    """
    profile = component_profile(records, subject_id, component)
    if profile is None:
        return None
    rows = component_rows(records, subject_id, component)
    path = ledger_path(subject_id, component)
    if path.exists():
        ledger = Ledger.model_validate_json(path.read_text(encoding="utf-8"))
        papers = [paper_id]
    else:
        ledger = Ledger()
        # Oldest first; dict keeps each paper at its first appearance.
        papers = list(dict.fromkeys(
            r.paper_id for r in sorted(rows, key=lambda r: r.timestamp)
        ))

    for paper in papers:
        lost = lost_questions(r for r in rows if r.paper_id == paper)
        reply = _ask(config, build_prompt(
            ledger, lost, comments,
            subject_id=subject_id, component=component, paper_id=paper,
        )) if lost else {}
        ledger = file_paper(ledger, paper, lost, reply)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ledger.model_dump_json(indent=2), encoding="utf-8")
    note = notes_path(subject_id, component)
    note.write_text(render_note(profile, ledger), encoding="utf-8")
    return note
