"""The tutor's notes — one short Markdown file per syllabus × component.

Rewritten whole after every confirmed grading run, from the profile and the
run's lost marks. Whole, not appended: new evidence has to be able to
overturn an old impression, and an append-only note only ever grows.

The note's shape is the profile's, laid out by code: a line per topic
(``Vectors 3题 7/16分``) and under it a line per reason it lost marks to
(``失误 4分``). The model only says, in one sentence per reason, what went
wrong — left to write the note itself, it added lines the data never
supported ("畏难情绪", "时间分配不当").

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

from core.models import AttemptRecord
from core.settings import GraderConfig, app_settings
from modules.profile import ComponentProfile, TopicStat

_ERROR_LABELS = {
    "concept": "概念",
    "method": "方法",
    "slip": "失误",
    "misread": "审题",
    "wording": "表述",
}

_PROMPT = """你是 CIE {subject_id} 的导师，在给学生写一份关于 Paper {component} 的备忘\
（{papers} 份卷子，同一份卷重批只算最新一次）。备忘的结构由程序按数据生成，\
你只给每个丢分条目写一句说明。

## 要填的条目（topic · 丢分原因 · 丢了几分）
{slots}

## 刚批完的 {paper_id} 的丢分题
{run}

## 上一次的备忘
{old_notes}

## 要求
只输出一个 JSON 对象，键是上面的条目编号，值是一句话（不超过 40 字）：
这个 topic 在这个原因上具体错在哪，可以点题号，例如 "Q6c 只写 more data，没说自由度"。
- 依据只能是上面的评语和上一次的备忘；找不到具体依据的条目填 ""，不要编。
- 不要揣测心理、态度或时间分配。
- 不要写 LaTeX 或反斜杠，数学符号用 Unicode。"""


def notes_path(subject_id: str, component: str) -> Path:
    return app_settings.base_dir / "tutor" / f"{subject_id}_p{component}.md"


def read_notes(subject_id: str, component: str) -> str | None:
    path = notes_path(subject_id, component)
    return path.read_text(encoding="utf-8") if path.exists() else None


def _label(error_type: str | None) -> str:
    return _ERROR_LABELS.get(error_type or "", "未分类")


def _slots(profile: ComponentProfile) -> list[tuple[TopicStat, str | None, float]]:
    """(topic, reason, marks lost to it) for every reason under every topic,
    most marks first; a topic's losses the grader left unclassified are the
    reason None."""
    slots: list[tuple[TopicStat, str | None, float]] = []
    for t in profile.topics:
        for error, lost in sorted(t.errors.items(), key=lambda kv: -kv[1]):
            slots.append((t, error, lost))
        rest = t.lost - sum(t.errors.values())
        if rest > 0:
            slots.append((t, None, rest))
    return slots


def _topic_name(t: TopicStat) -> str:
    return t.topic_name or t.topic_id or "未分类"


def build_prompt(
    profile: ComponentProfile,
    run: Iterable[AttemptRecord],
    comments: Mapping[str, str],
    old_notes: str | None,
    *,
    paper_id: str,
) -> str:
    """The request for the reasons' descriptions. ``run`` is the paper just
    confirmed; ``comments`` maps its question ids to the grader's comment."""
    slots = "\n".join(
        f"s{i}: {_topic_name(t)} · {_label(e)} · {lost:g} 分"
        for i, (t, e, lost) in enumerate(_slots(profile), 1)
    ) or "（没有丢分）"
    lost = [a for a in run if a.score < a.max_score and a.error_type != "blank"]
    run_lines = "\n".join(
        "- " + " · ".join(filter(None, [
            a.question_id,
            a.topic_name or "未分类",
            _label(a.error_type),
            f"得 {a.score:g}/{a.max_score:g}",
            comments.get(a.question_id, ""),
        ]))
        for a in lost
    ) or "（这份卷子没有丢分）"
    return _PROMPT.format(
        subject_id=profile.subject_id,
        component=profile.component,
        papers=profile.papers,
        slots=slots,
        paper_id=paper_id,
        run=run_lines,
        old_notes=old_notes.strip() if old_notes else "（还没有）",
    )


def parse_reply(raw: str) -> dict[str, str]:
    """The model's ``{"s1": "…"}``; anything unreadable is no descriptions,
    and the note still carries every topic and reason."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v.strip() for k, v in data.items() if isinstance(v, str)}


def render_note(profile: ComponentProfile, said: Mapping[str, str]) -> str:
    """The note: a line per topic, a nested line per reason it lost marks to."""
    slots = _slots(profile)
    lines: list[str] = []
    for t in profile.topics:
        earned = t.max_score - t.lost
        lines.append(f"- {_topic_name(t)} {t.questions}题 {earned:g}/{t.max_score:g}分")
        for i, (owner, error, lost) in enumerate(slots, 1):
            if owner is t:
                why = said.get(f"s{i}", "")
                reason = f"  - {_label(error)} {lost:g}分"
                lines.append(f"{reason}：{why}" if why else reason)
    return "\n".join(lines) + "\n"


def rewrite_notes(config: GraderConfig, prompt: str) -> dict[str, str]:
    client = OpenAI(
        api_key=config.api_key.get_secret_value(),
        base_url=config.base_url,
        timeout=120.0,
        max_retries=1,
    )
    response = client.chat.completions.create(
        model=config.model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        extra_body={"enable_thinking": False},
    )
    return parse_reply(str(response.choices[0].message.content))


def refresh_notes(
    config: GraderConfig,
    run: list[AttemptRecord],
    comments: Mapping[str, str],
    *,
    profile: ComponentProfile,
    paper_id: str,
) -> Path:
    """Rewrite the note for *profile*'s component and return where it went."""
    path = notes_path(profile.subject_id, profile.component)
    prompt = build_prompt(
        profile, run, comments,
        read_notes(profile.subject_id, profile.component),
        paper_id=paper_id,
    )
    note = render_note(profile, rewrite_notes(config, prompt))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(note, encoding="utf-8")
    return path
