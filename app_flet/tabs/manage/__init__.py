"""【管理】页：一份数据的三种看法。

总览是聚合（整体构成 + 每个 syllabus 的成绩明细），整理是浏览和操作（Finder
的图标 / 详细信息两种排布），错题是按卷分组的失分明细。三者都只是在读同一批
卷子，拆在三个顶级 tab 里的时候，同一个问题要在三处之间来回跳。

``tab.py`` 负责串起来，一节一个文件 —— 和 ``app_flet/tabs/mark/`` 同一套做法。
行的样式定义在 ``organize.py``，整理和错题共用。
"""
from app_flet.tabs.manage.tab import build_manage_tab

__all__ = ["build_manage_tab"]
