"""The tutor's notes — one short Markdown file per syllabus × component.

Rewritten whole after every confirmed grading run, from the profile and the
run's lost marks. Whole, not appended: new evidence has to be able to
overturn an old impression, and an append-only note only ever grows.

The notes are for the student to read. Nothing in the grading path may read
them — a grader that knows "this student keeps losing marks on Equilibria"
marks Equilibria harder (``tests/test_tutor.py`` pins that).
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path

from openai import OpenAI

from core.models import AttemptRecord
from core.settings import GraderConfig, app_settings
from modules.profile import ComponentProfile

#: The note is read at a glance on the syllabus panel; past this it is an essay.
MAX_LINES = 20

_ERROR_LABELS = {
    "concept": "概念",
    "method": "方法",
    "slip": "失误",
    "misread": "审题",
    "wording": "表述",
    "blank": "未作答",
}

_PROMPT = """你是 CIE {subject_id} 的导师，在给学生写一份关于 Paper {component} 的备忘。

## 这个学生 Paper {component} 的数据（{papers} 份卷子，同一份卷重批只算最新一次）
按丢分率从高到低：
{topics}

丢分原因（按丢的分数）：{errors}

## 刚批完的 {paper_id} 的丢分题
{run}

## 你上一次写的备忘
{old_notes}

## 要求
重写整份备忘。直接输出 Markdown 无序列表，不超过 {max_lines} 行，不要标题，不要前言。
- 每一条都要落在上面的数据或评语上：点名 topic，写具体表现，例如
  「Equilibria 7 题丢了 60% 的分，多半是审题：漏看了温度条件」。
  「注意计算」「多做练习」这类对谁都成立的话不要写。
- 只有一两份卷子时，只写这几份卷子能看出来的东西，不要推断长期规律。
- 上一次备忘里被新数据推翻的判断，直接删掉或改写；不要说明改了什么。
- 不要写 LaTeX 或反斜杠，数学符号用 Unicode。"""


def notes_path(subject_id: str, component: str) -> Path:
    return app_settings.base_dir / "tutor" / f"{subject_id}_p{component}.md"


def read_notes(subject_id: str, component: str) -> str | None:
    path = notes_path(subject_id, component)
    return path.read_text(encoding="utf-8") if path.exists() else None


def _label(error_type: str | None) -> str:
    return _ERROR_LABELS.get(error_type or "", "未分类")


def _breakdown(errors: Mapping[str, float]) -> str:
    ranked = sorted(errors.items(), key=lambda kv: -kv[1])
    return "，".join(f"{_label(e)} {lost:g} 分" for e, lost in ranked) or "（未分类）"


def build_prompt(
    profile: ComponentProfile,
    run: Iterable[AttemptRecord],
    comments: Mapping[str, str],
    old_notes: str | None,
    *,
    paper_id: str,
) -> str:
    """The rewrite request. ``run`` is the paper just confirmed; ``comments``
    maps its question ids to the grader's comment on them."""
    topics = "\n".join(
        f"- {t.topic_name or t.topic_id or '未分类'}：{t.questions} 题，"
        f"丢 {t.lost:g}/{t.max_score:g} 分（{t.loss_rate:.0%}），"
        f"原因 {_breakdown(t.errors)}"
        for t in profile.topics
    )
    lost = [a for a in run if a.score < a.max_score]
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
        topics=topics,
        errors=_breakdown(profile.errors),
        paper_id=paper_id,
        run=run_lines,
        old_notes=old_notes.strip() if old_notes else "（还没有）",
        max_lines=MAX_LINES,
    )


def clean_reply(raw: str) -> str:
    """The model's reply as the note: fences stripped, capped at MAX_LINES."""
    text = re.sub(r"^```(?:markdown|md)?\s*|\s*```$", "", raw.strip())
    lines = [line for line in text.splitlines() if line.strip()]
    return "\n".join(lines[:MAX_LINES]) + "\n"


def rewrite_notes(config: GraderConfig, prompt: str) -> str:
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
    return clean_reply(str(response.choices[0].message.content))


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
    note = rewrite_notes(config, prompt)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(note, encoding="utf-8")
    return path
