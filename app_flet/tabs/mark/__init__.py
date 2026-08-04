"""The Mark tab (AI 批改), split by step.

Was a single ~1,500-line ``app_flet/tabs/mark.py`` closure. The sections now
live in their own modules and share state through
:class:`~app_flet.tabs.mark.context.MarkTabContext`; the UI-agnostic decisions
moved further out still, to :mod:`modules.marking.workflow`, where they have
tests.
"""
from app_flet.tabs.mark.tab import build_mark_tab

__all__ = ["build_mark_tab"]
