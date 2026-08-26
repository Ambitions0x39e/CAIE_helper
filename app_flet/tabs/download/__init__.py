"""下载页，按子标签拆分。

一个子标签一个文件，``tab.py`` 负责串起来 —— 和 ``app_flet/tabs/mark/``
同一套做法。三个子标签之间没有共享的可变状态，所以不需要 mark 那样的
context 对象，各自的常量跟着各自的文件走。
"""
from app_flet.tabs.download.tab import build_download_tab

__all__ = ["build_download_tab"]
