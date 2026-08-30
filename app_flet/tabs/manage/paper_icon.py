"""一张卷子的图标：一张纸打底，学科符号压在右下角当角标。

映射按**科目名的关键词**走，不按四位号码 —— 同一个科目在 IGCSE 和 A Level
各有一个号（0620 和 9701 都是化学），而 ``data/syllabus_config.json`` 随时会
加新的号。一条关键词同时覆盖两边，加号码时不用回来改这张表。
"""
from __future__ import annotations

from functools import lru_cache

import flet as ft

from app_flet import theme
from core.config_store import ConfigStore, SyllabusConfigDict

#: 关键词 → 符号。**顺序即优先级**，先命中的算数：Further Mathematics 要落在
#: 求和号上而不是计算器上，所以它排在 Mathematics 前面。
_SUBJECT_ICONS: tuple[tuple[str, ft.IconData], ...] = (
    ("Chemistry", ft.Icons.SCIENCE),
    ("Physics", ft.Icons.BOLT),
    ("Biology", ft.Icons.BIOTECH),
    ("Further Mathematics", ft.Icons.FUNCTIONS),
    ("Mathematics", ft.Icons.CALCULATE),
    ("Computer Science", ft.Icons.TERMINAL),
    ("ICT", ft.Icons.COMPUTER),
    ("Psychology", ft.Icons.PSYCHOLOGY),
    ("Geography", ft.Icons.PUBLIC),
    ("History", ft.Icons.HISTORY_EDU),
    ("Accounting", ft.Icons.ACCOUNT_BALANCE),
    ("Economics", ft.Icons.TRENDING_UP),
    ("Business", ft.Icons.BUSINESS_CENTER),
    ("Physical Education", ft.Icons.SPORTS_SOCCER),
    ("English", ft.Icons.TRANSLATE),
    ("Chinese", ft.Icons.TRANSLATE),
)
#: 认不出的科目落一张写了字的纸 —— 比空白纸更像「一份卷子」。
_FALLBACK = ft.Icons.DESCRIPTION

#: 学科符号占纸面的比例。压在纸中央，所以不能太大 —— 满上去纸就没了。
_GLYPH_RATIO = 0.4


@lru_cache(maxsize=1)
def syllabus_config() -> SyllabusConfigDict:
    """``data/syllabus_config.json`` 的解析结果。手改的 JSON，一个 session 里
    读一次就够 —— 总览的卡片、明细浮层的 Paper 名、这里的学科符号都要它。"""
    return ConfigStore().load_syllabus_config()


def syllabus_names() -> dict[str, str]:
    """四位号码 → 科目全名。"""
    return {
        code: str(entry.get("name", ""))
        for code, entry in syllabus_config().items()
    }


def syllabus_id_of(paper_id: str) -> str:
    return paper_id[:4]


def subject_icon(syllabus_id: str) -> ft.IconData:
    name = syllabus_names().get(syllabus_id, "")
    for keyword, icon in _SUBJECT_ICONS:
        if keyword in name:
            return icon
    return _FALLBACK


def subject_label(syllabus_id: str) -> str:
    name = syllabus_names().get(syllabus_id)
    return f"{syllabus_id} — {name}" if name else syllabus_id


def paper_icon(
    syllabus_id: str,
    size: int,
    *,
    done: bool = False,
) -> ft.Control:
    """一张纸，学科符号压在正中。``done`` 只改符号的颜色，纸面不动 —— 状态是
    这张卷的属性，不是它属于哪一科。"""
    return ft.Stack(
        [
            # 描边版而不是实心版：实心的一整块灰在 PAGE_BG 上是个色块，描边的
            # 才读得出「一张纸」，符号压上去也才有东西可压。
            ft.Icon(
                ft.Icons.INSERT_DRIVE_FILE_OUTLINED,
                size=size,
                color=theme.NEUTRAL,
            ),
            ft.Container(
                ft.Icon(
                    subject_icon(syllabus_id),
                    size=round(size * _GLYPH_RATIO),
                    color=theme.PRIMARY if done else theme.MUTED,
                ),
                width=size,
                height=size,
                alignment=ft.Alignment.CENTER,
            ),
        ],
        width=size,
        height=size,
    )
