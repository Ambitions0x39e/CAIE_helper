"""科目 / 年份 / 考季 三个下拉框，「按考季查询」和「分数线」共用。

两个子页要选的是同一件事 —— 哪个科目的哪一场考试 —— 所以下拉框只建一次。
从这里拼出卷号，而不是让用户手打 ``9702_s23_gt``，就不会拼错格式。
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import flet as ft

from app_flet import theme
from core.config_store import ConfigStore

#: CIE 的考季代码（卷号里那个字母）与显示名。
_SEASONS: list[tuple[str, str]] = [
    ("m", "March"),
    ("s", "Summer"),
    ("w", "Winter"),
]
#: CIEFrank 能查到的最早年份。
_FIRST_YEAR = 2004


@dataclass(frozen=True)
class SessionPicker:
    """三个下拉框 + 从它们拼出考期/卷号的方法。"""

    syllabus: ft.Dropdown
    year: ft.Dropdown
    season: ft.Dropdown

    def row(self, spacing: int = 12) -> ft.Row:
        return ft.Row([self.syllabus, self.year, self.season], spacing=spacing)

    def is_complete(self) -> bool:
        return bool(self.syllabus.value and self.year.value and self.season.value)

    def session_code(self) -> str:
        """``Winter`` + ``2025`` → ``w25``，即卷号中间那一段。"""
        year = str(self.year.value or "")
        return f"{self.season.value}{year[-2:]}"

    def gt_paper_id(self) -> str:
        """这一场考试的分数线文件名，例如 ``9701_w25_gt``。"""
        return f"{self.syllabus.value}_{self.session_code()}_gt"


def build_session_picker() -> SessionPicker:
    syllabi = sorted(ConfigStore().load_all(), key=lambda s: s.syllabus_id)
    current_year = dt.date.today().year

    return SessionPicker(
        syllabus=ft.Dropdown(
            label="科目",
            label_style=theme.field_label_style(),
            options=[
                ft.dropdown.Option(
                    key=s.syllabus_id, text=f"{s.syllabus_id} — {s.name}",
                )
                for s in syllabi
            ],
            value=syllabi[0].syllabus_id if syllabi else None,
            expand=True,
        ),
        year=ft.Dropdown(
            label="年份",
            label_style=theme.field_label_style(),
            options=[
                ft.dropdown.Option(key=str(y), text=str(y))
                for y in range(current_year, _FIRST_YEAR - 1, -1)
            ],
            value=str(current_year),
            expand=True,
        ),
        season=ft.Dropdown(
            label="考季",
            label_style=theme.field_label_style(),
            options=[
                ft.dropdown.Option(key=code, text=label)
                for code, label in _SEASONS
            ],
            value=_SEASONS[0][0],
            expand=True,
        ),
    )
