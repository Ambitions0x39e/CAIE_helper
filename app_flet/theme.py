"""界面用的语义色 + 按钮样式，UI 层唯一该出现颜色常量的地方。

为什么要有这一层：在此之前，颜色本身就是语义 —— 想知道「主操作按钮是什么颜色」
得全仓 grep `ft.Colors.BLUE`，想换主色得改一百多处。现在改一行。

**这里的每个名字都只是别名，值与重构前逐一对应，不改变任何像素。** 真要换配色，
改这个文件里的赋值即可；跨明暗主题的适配也从这里开始。

用法：

    from app_flet import theme

    ft.Text("提示", color=theme.MUTED)
    ft.Button("下载", style=theme.filled_button())
    ft.Button("删除", style=theme.filled_button(theme.DANGER))
"""
from __future__ import annotations

import flet as ft

# ── 语义色 ────────────────────────────────────────────────────────
#: 主操作：下载、查询、批量下载、确认
PRIMARY = ft.Colors.BLUE
#: 成功：完成、已通过、正向指标
SUCCESS = ft.Colors.GREEN
#: 危险 / 失败：删除、报错
DANGER = ft.Colors.RED
#: 警告：需要注意但不致命（未完成、跳过、缺文件）
WARNING = ft.Colors.ORANGE
#: 强调：发送到 GoodNotes 这类次要但要显眼的动作
ACCENT = ft.Colors.AMBER
#: 中性按钮：仅记录这类次要动作
NEUTRAL = ft.Colors.GREY_600
#: 填充色按钮上的文字/图标
ON_FILLED = ft.Colors.WHITE

# ── 中性色 ────────────────────────────────────────────────────────
#: 页面底色
SURFACE = ft.Colors.WHITE
#: 正文文字。主题（main.py 的 text_theme / on_surface）已经把它设成默认色，
#: 所以控件上**不要**再写一遍 —— 只有主题够不着的地方才需要，见
#: field_label_style()。这里留一个名字，是为了主题定义自身也走同一个源头。
TEXT_PRIMARY = ft.Colors.BLACK
#: 辅助文字：说明、提示、次要信息
MUTED = ft.Colors.GREY
#: 分隔线、边框、图表轴线
HAIRLINE = ft.Colors.GREY_300
#: 更淡的网格线
HAIRLINE_FAINT = ft.Colors.GREY_100
#: 输入框边框
FIELD_BORDER = ft.Colors.GREY_400

# ── 浅底色（横幅 / 表头）──────────────────────────────────────────
PRIMARY_TINT = ft.Colors.BLUE_50
DANGER_TINT = ft.Colors.RED_50
SUCCESS_TINT = ft.Colors.GREEN_50
ACCENT_TINT = ft.Colors.AMBER_100
WARNING_TINT = ft.Colors.ORANGE_50
#: 深一档的警告色，用在浅底上的文字/图标
WARNING_STRONG = ft.Colors.ORANGE_800
#: 深色浮层（提示气泡等）
OVERLAY_DARK = ft.Colors.BLUE_GREY_800
#: 深一档的强调色，用在浅底上的图标
ACCENT_STRONG = ft.Colors.AMBER_800

# ── 指标卡配色 ────────────────────────────────────────────────────
#: 统计页 metric_card 的分类色，彼此区分即可，无固定语义
CARD_PURPLE = ft.Colors.PURPLE
CARD_TEAL = ft.Colors.TEAL


#: iOS app 图标那套 squircle 的圆角比例（圆角半径 / 边长）。Flet 的
#: RoundedRectangleBorder 只画圆弧角，不是 Apple 那种连续曲率的超椭圆，
#: 这里是用同样的比例去逼近观感，不是真 squircle 曲线。
SQUIRCLE_RADIUS_RATIO = 0.2237
#: Material 3 默认按钮高度（dp），比例换算成像素半径要有个锚点。
_BUTTON_HEIGHT = 40
SQUIRCLE_RADIUS = round(_BUTTON_HEIGHT * SQUIRCLE_RADIUS_RATIO, 2)


def filled_button(bgcolor: str = PRIMARY) -> ft.ButtonStyle:
    """实心按钮：彩色底 + 白字 + squircle 圆角。默认主色，传别的语义色改用途。"""
    return ft.ButtonStyle(
        bgcolor=bgcolor,
        color=ON_FILLED,
        shape=ft.RoundedRectangleBorder(radius=SQUIRCLE_RADIUS),
    )


def field_label_style() -> ft.TextStyle:
    """输入框 / 下拉框的浮动标签配色。

    这是全 app 唯一还需要手写文字颜色的地方：Flutter 里浮动标签归
    ``InputDecorationTheme`` 管，而 Flet 0.85 的 ``ft.Theme`` 没有暴露那个槽位
    （59 项里没有 input decoration 相关的），``text_theme`` 和
    ``ColorScheme.on_surface`` 都够不着它 —— 实测染色验证过：整套主题染成蓝/红，
    只有这个标签纹丝不动。

    每次返回**新对象**而不是共享一个常量：Flet 控件会持有并可能改写自己的样式，
    共享实例会串味。

    将来做深色模式，这个函数是那批标签唯一要改的地方。
    """
    return ft.TextStyle(color=TEXT_PRIMARY)
