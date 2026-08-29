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
#: 主操作：下载、查询、批量下载、确认。Tailwind slate-700——冷灰蓝，不用
#: Material 的鲜蓝，跟卡片/边框那套克制的中性色调性一致。
PRIMARY = "#334155"
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

# ── 交互态色档 ────────────────────────────────────────────────────
# 每个语义色配一组 hover / pressed，方向统一：hover 比底色浅，pressed 比底色
# 深。浅=还没落下，深=已经按到底，光照的直觉本身就把两个状态分开了，不必再
# 靠色相。档位是导出的不是挑的——Material 调色板的语义色直接取 _400 / _800，
# PRIMARY 是 Tailwind slate 手写值，取同一梯度的 slate-600 / slate-800。
PRIMARY_HOVER = "#475569"
PRIMARY_PRESSED = "#1E293B"
SUCCESS_HOVER = ft.Colors.GREEN_400
SUCCESS_PRESSED = ft.Colors.GREEN_800
DANGER_HOVER = ft.Colors.RED_400
DANGER_PRESSED = ft.Colors.RED_800
WARNING_HOVER = ft.Colors.ORANGE_400
WARNING_PRESSED = ft.Colors.ORANGE_800
ACCENT_HOVER = ft.Colors.AMBER_400
ACCENT_PRESSED = ft.Colors.AMBER_800
NEUTRAL_HOVER = ft.Colors.GREY_400
NEUTRAL_PRESSED = ft.Colors.GREY_800

#: 底色 → (hover, pressed)。filled_button() 按底色查这张表。表里没有的颜色
#: 三态同色，等于没有交互态——新增一档语义色，要在这里补一行才带得上反馈。
_BUTTON_SHADES: dict[str, tuple[str, str]] = {
    PRIMARY: (PRIMARY_HOVER, PRIMARY_PRESSED),
    SUCCESS: (SUCCESS_HOVER, SUCCESS_PRESSED),
    DANGER: (DANGER_HOVER, DANGER_PRESSED),
    WARNING: (WARNING_HOVER, WARNING_PRESSED),
    ACCENT: (ACCENT_HOVER, ACCENT_PRESSED),
    NEUTRAL: (NEUTRAL_HOVER, NEUTRAL_PRESSED),
}

#: 无底色的可点区域（nav 按钮、分段条、settings 菜单行）悬停时铺的一层底。
#: 与官网的 ``--primary-tint-hover`` 同值——app 和站点是同一套语言。
#:
#: 这一档看着很浅，是因为**底色只扛一半信号，另一半在前景色**：这批区域静息
#: 时前景是 MUTED，悬停时提到 TEXT_PRIMARY，两件事一起发生才读得出来。只让
#: 底色扛就得一路加深到边框色的量级，那时铺出来是一整块死板的色块。
SURFACE_HOVER = "#EEF2F6"
#: 同一批区域被按住时的底，比 SURFACE_HOVER 再深一档（slate-200）。方向跟按钮
#: 的 pressed 一致：按下去总是更深。
SURFACE_PRESSED = "#E2E8F0"

# ── 中性色 ────────────────────────────────────────────────────────
#: 卡片/面板（"白色圆角矩形"）底色。不是纯白——微降一点点，配边框+柔和阴影用。
SURFACE = "#FDFDFC"
#: 窗口/页面背景，RGB 每个通道都比 SURFACE 深 3——用户在试这个量级下卡片是否
#: 更容易被"看出来"，而不必靠边框+阴影单独扛对比。
PAGE_BG = "#F9F9F8"
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
#: Tailwind slate-50——跟 PRIMARY 同一个色系的最浅档。也是选中态的底：官网的
#: ``--primary-tint`` 一个值同时管横幅和导航条的 active，这里照搬。
PRIMARY_TINT = "#F8FAFC"
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


# ── 圆角 ──────────────────────────────────────────────────────────
#: 卡片/面板统一圆角，取代原先 6/8/12 三档并存的写法。按钮走下面独立的
#: SQUIRCLE_RADIUS，两者相差不到 1px，肉眼分不出来——按钮那档是刻意保留的
#: 独立公式，不并进来。
CARD_RADIUS = 10

#: iOS app 图标那套 squircle 的圆角比例（圆角半径 / 边长）。Flet 的
#: RoundedRectangleBorder 只画圆弧角，不是 Apple 那种连续曲率的超椭圆，
#: 这里是用同样的比例去逼近观感，不是真 squircle 曲线。
SQUIRCLE_RADIUS_RATIO = 0.2237
#: Material 3 默认按钮高度（dp），比例换算成像素半径要有个锚点。
_BUTTON_HEIGHT = 40
SQUIRCLE_RADIUS = round(_BUTTON_HEIGHT * SQUIRCLE_RADIUS_RATIO, 2)

# ── 布局 ──────────────────────────────────────────────────────────
#: 左侧 nav 按钮的边长。
NAV_BUTTON_SIZE = 64
#: nav rail 连同它右边那条 1px 分隔线占掉的宽度。``page.width`` 给的是整个
#: 窗口，任何按窗口宽度算版面的地方都得先把这块减掉 —— 少减了，内容区就会
#: 以为自己比实际宽 85px，右边缘溢出。
NAV_CHROME_W = NAV_BUTTON_SIZE + 20 + 1

# ── 间距 scale ────────────────────────────────────────────────────
#: 卡片内部紧凑间隙（比如 metric_card 标签→数值）
SPACE_XS = 4
#: 行间距、图标到文字的间隙
SPACE_SM = 8
#: 卡片内边距、区块间距
SPACE_MD = 12
#: banner 内边距、列表行内边距
SPACE_LG = 16
#: 页面级外边距
SPACE_XL = 20

# ── 字号 scale ────────────────────────────────────────────────────
#: 仅页面标题（每个 tab 一个）。本轮不接线——section_title() 现在的 24 Bold
#: 归 TITLE 还是 SECTION 要看各 tab 调用点，留字面量，是下一轮的事。
TITLE = 24
#: 所有区块/子区块标题
SECTION = 18
#: 需要强调的行/卡片标签，配 ft.FontWeight.W_600 使用
SUBHEAD = 14
#: 默认正文
BODY = 13
#: 提示/次要信息，配 theme.MUTED 颜色使用
CAPTION = 12
#: 比 CAPTION 再小一档，给挤在表格/表单里的辅助文字。
MICRO = 11
# ── 时长 scale ────────────────────────────────────────────────────
#: 交互态：容器的 hover / 选中底色切换。0 = 当帧变色，跟按钮那套 ControlState
#: 色表对齐。这一档是跟着指针走的，任何时长都会被读成延迟而不是过渡，跟下面
#: 几档「引导视线」的用途不是一回事。名字底下是个旋钮：容器的交互态要带补间，
#: 改这一个数就够。
DURATION_INSTANT = 0
#: 结果区三态、banner 进出、列表项
DURATION_FAST = 200
#: tab 切换、settings 子页切换
DURATION_BASE = 320
#: 对话框、大面积材质
DURATION_SLOW = 400

# ── 曲线 ──────────────────────────────────────────────────────────
# 可逆的过渡两个方向必须互为镜像，否则来回走的不是同一条路。
#: 进场：快起慢收
CURVE_IN = ft.AnimationCurve.EASE_OUT_CUBIC
#: 退场：慢起快走
CURVE_OUT = ft.AnimationCurve.EASE_IN_CUBIC
#: 页面级双向切换
CURVE_PAGE = ft.AnimationCurve.EASE_IN_OUT_CUBIC_EMPHASIZED


def filled_button(bgcolor: str = PRIMARY) -> ft.ButtonStyle:
    """实心按钮：彩色底 + 白字 + squircle 圆角。默认主色，传别的语义色改用途。

    三态底色走 ``ControlState`` 色表，切换是瞬时的 —— ``animation_duration``
    对色表无效，所以这里不设时长。按下当帧就变色，正是这一档要的反馈。

    ``overlay_color`` 设成透明是为了关掉 Material 的涟漪：那层灰白盖在
    slate-700 上跟这套克制的中性调性对不上，而且反馈已经由三态色表接管，
    留着就是两套交互态叠在一起。
    """
    hover, pressed = _BUTTON_SHADES.get(bgcolor, (bgcolor, bgcolor))
    return ft.ButtonStyle(
        bgcolor={
            ft.ControlState.DEFAULT: bgcolor,
            ft.ControlState.HOVERED: hover,
            ft.ControlState.PRESSED: pressed,
        },
        color=ON_FILLED,
        overlay_color=ft.Colors.TRANSPARENT,
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


def card_shadow() -> ft.BoxShadow:
    """卡片档阴影（metric_card 尺寸），配边框一起用——不透明度是原先阴影方案的
    一半（12% → 6%），边框已经画出轮廓，阴影只用来补一点厚度感，不用扛全部
    "浮起来"的视觉重量。

    每次返回新对象，理由同 field_label_style()：控件会持有并可能改写自己的
    样式，共享同一个实例会串味。
    """
    return ft.BoxShadow(
        blur_radius=16,
        spread_radius=-2,
        color=ft.Colors.with_opacity(0.06, ft.Colors.BLACK),
        offset=ft.Offset(0, 4),
    )


def row_shadow(*, opacity: float = 0.05) -> ft.BoxShadow:
    """行档阴影（列表行尺寸），比 card_shadow() 更轻。不透明度同样减半
    （10% → 5%）。每次返回新对象，理由同上。

    ``opacity=0`` 给的是几何一样、只是不着色的一层影子，专门用来接
    ``animate`` 的另一端：动画容器只能在**两侧都存在**的属性之间补间，那一侧
    换成 ``None``，影子会在整段淡出期间原样杵着，到最后一帧才消失 —— 看起来
    是结束时闪一下。
    """
    return ft.BoxShadow(
        blur_radius=14,
        spread_radius=-3,
        color=ft.Colors.with_opacity(opacity, ft.Colors.BLACK),
        offset=ft.Offset(0, 2),
    )
