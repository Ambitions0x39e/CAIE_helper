from __future__ import annotations

from collections.abc import Callable, Sequence

import flet as ft

from app_flet import theme


def data_table(
    columns: list[ft.DataColumn],
    rows: list[ft.DataRow],
    *,
    show_checkbox_column: bool = False,
    on_select_all: Callable[..., None] | None = None,
    row_height: float | None = None,
    compact: bool = False,
) -> ft.Row:
    """全 app 统一的表格样式，宽度铺满窗口。

    管理页和分数线页各自写过一份 DataTable，边框、圆角、表头底色不一致；
    收成一处，改一次两处都跟着变。

    **返回的是包了一层 Row 的表格**，不是裸的 DataTable：``expand`` 是沿父容器
    的主轴生效的，而这两处表格都放在 Column 里 —— 在 Column 里 expand 会往
    **竖**向撑，横向依旧只有内容宽度。套一层 Row 之后主轴才是横向，expand
    才等于「占满窗口宽度」（同 request.py 里 ``expand=True`` 的下拉框）。

    也不要再往外面套 ``Row(scroll=AUTO)``：横向滚动的行宽度无界，expand 撑不出
    约束，表格会缩回内容宽度。

    ``row_height`` 只给单元格里放了控件（下拉框、按钮）的表用 —— 默认行高按纯
    文本算，塞进一个下拉框会被裁掉。不传就沿用 Flet 的默认，既有调用方不受影响。

    ``compact=True`` 收紧行高、列距，并补上竖分隔线：给单元格只有一两个字符的
    密集表格用（批改页的 MCQ 答题卡，一屏要放 40 题），列一多就必须有竖线才对得
    上题号。两个都传时 ``row_height`` 说了算 —— 它是调用方给出的确切数值，
    compact 那档只是默认值。默认那档是给管理页那种整行文字的表格用的，不要动。
    """
    compact_min, compact_max = (30, 34) if compact else (None, None)
    return ft.Row([
        ft.DataTable(
            columns=columns,
            rows=rows,
            show_checkbox_column=show_checkbox_column,
            on_select_all=on_select_all,
            data_row_min_height=row_height if row_height else compact_min,
            data_row_max_height=row_height if row_height else compact_max,
            expand=True,
            border=ft.Border.all(1, theme.HAIRLINE),
            border_radius=theme.CARD_RADIUS,
            heading_row_color=theme.PRIMARY_TINT,
            heading_row_height=32 if compact else None,
            column_spacing=8 if compact else None,
            horizontal_margin=10 if compact else None,
            vertical_lines=(
                ft.BorderSide(1, theme.HAIRLINE_FAINT) if compact else None
            ),
        )
    ])


def metric_card(label: str, value: str, color: str) -> ft.Container:
    # No fixed height — it auto-sizes to the content so a wide value (e.g.
    # "123/150", "100.0%") wraps within the card instead of overflowing the
    # old fixed 110x85 box. Width is comfortable for a 7-char value at size 24.
    return ft.Container(
        ft.Column(
            [
                ft.Text(label, size=theme.CAPTION, color=theme.MUTED),
                ft.Text(
                    value,
                    size=24,
                    weight=ft.FontWeight.BOLD,
                    color=color,
                    text_align=ft.TextAlign.CENTER,
                ),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=theme.SPACE_XS,
        ),
        width=132,
        bgcolor=theme.SURFACE,
        border_radius=theme.CARD_RADIUS,
        border=ft.Border.all(1, theme.HAIRLINE),
        shadow=theme.card_shadow(),
        padding=theme.SPACE_MD,
        alignment=ft.Alignment(0, 0),
    )


def status_badge(status: str) -> ft.Container:
    return ft.Container(
        ft.Text(status, size=12, color=theme.ON_FILLED),
        bgcolor=theme.SUCCESS if status == "Completed" else theme.WARNING,
        border_radius=12,
        padding=ft.Padding(left=8, right=8, top=2, bottom=2),
    )


def section_title(text: str) -> ft.Text:
    return ft.Text(
        text,
        size=theme.TITLE,
        weight=ft.FontWeight.BOLD,
    )


def _banner(
    message: str,
    details: list[str] | None,
    *,
    icon: ft.IconValue,
    icon_color: str,
    bgcolor: str,
    bold: bool,
) -> ft.Container:
    controls: list[ft.Control] = [
        ft.Row([
            ft.Icon(icon, color=icon_color),
            ft.Text(
                message,
                weight=ft.FontWeight.BOLD if bold else None,
            ),
        ]),
    ]
    controls.extend(
        ft.Text(d, size=theme.CAPTION, color=theme.MUTED) for d in details or []
    )
    return ft.Container(
        content=ft.Column(controls),
        bgcolor=bgcolor,
        border_radius=theme.CARD_RADIUS,
        border=ft.Border.all(1, theme.HAIRLINE),
        shadow=theme.row_shadow(),
        padding=theme.SPACE_LG,
    )


def success_banner(message: str, details: list[str] | None = None) -> ft.Container:
    return _banner(
        message, details,
        icon=ft.CupertinoIcons.CHECKMARK_CIRCLE_FILL,
        icon_color=theme.SUCCESS,
        bgcolor=theme.SUCCESS_TINT,
        bold=True,
    )


def error_banner(message: str) -> ft.Container:
    return _banner(
        message, None,
        icon=ft.CupertinoIcons.XMARK_CIRCLE_FILL,
        icon_color=theme.DANGER,
        bgcolor=theme.DANGER_TINT,
        bold=False,
    )


def warning_banner(message: str, details: list[str] | None = None) -> ft.Container:
    return _banner(
        message, details,
        icon=ft.CupertinoIcons.EXCLAMATIONMARK_CIRCLE_FILL,
        icon_color=theme.WARNING,
        bgcolor=theme.WARNING_TINT,
        bold=True,
    )


def _tint(source: ft.ColorValue | Callable[[], ft.ColorValue | None] | None) -> (
    ft.ColorValue | None
):
    return source() if callable(source) else source


def hoverable(
    inner: ft.Container,
    *,
    hover_bgcolor: ft.ColorValue | Callable[[], ft.ColorValue | None] = (
        theme.SURFACE_HOVER
    ),
    rest_bgcolor: Callable[[], ft.ColorValue | None] | None = None,
    tinted: Sequence[ft.Icon | ft.Text] = (),
    hover_color: ft.ColorValue | Callable[[], ft.ColorValue | None] = (
        theme.TEXT_PRIMARY
    ),
    rest_color: Callable[[], ft.ColorValue | None] | None = None,
) -> ft.GestureDetector:
    """给一个可点的 Container 接上悬停态，返回包在外面的 GestureDetector。

    **必须包 GestureDetector，不能用 ``ft.Container`` 自带的悬停回调槽位。**
    那个槽位的事件确实会触发（计数器会跳，``e.data`` 是 ``"true"`` /
    ``"false"``），但在回调里改任何属性都不渲染。六种写法逐一试过并排除：
    构造时传 handler、构造后赋值、配 ``ink=True`` + ``on_click``、handler
    挂外层只改子控件、用 ``ctl.update()`` 代替 ``page.update()`` —— 全部
    无效。只有 ``GestureDetector`` 的 ``on_enter`` / ``on_exit`` 有效。
    这条会**静默失效**：不报错、不崩溃、代码看着完全合理，只是没有效果，
    所以 hover 的代价统一收在这个函数里，调用方不要自己写。

    ``tinted`` 里的图标/文字跟着底色一起变：静息 MUTED、悬停 TEXT_PRIMARY。
    两件事必须一起做 —— ``SURFACE_HOVER`` 只有 PAGE_BG 上一点点的对比，单靠
    底色读不出来；要让底色独自扛，就得加深到边框色的量级，铺出来是一整块
    死板的色块。前景一起动，浅底才够用。

    四个颜色槽位都收**取值器**，不只是值：要涂成什么，得在事件发生那一刻
    现问。nav 按钮的静息色随选中状态变，而「悬停着点进去」正好会在指针还在
    里面的时候换掉选中状态 —— 进入时快照一次，移开时就会把刚点亮的选中态
    擦掉。同一个理由也用在悬停侧：分段条里已选中的那一段不该被悬停涂灰，
    ``hover_bgcolor`` 传个取值器就能让它悬停时保持原样。``rest_*`` 不传则
    各自沿用构造时的颜色，适合静息色恒定的行。
    """
    bg_snapshot: ft.ColorValue | None = inner.bgcolor
    color_snapshots: list[ft.ColorValue | None] = [c.color for c in tinted]

    def _resting_bg() -> ft.ColorValue | None:
        return bg_snapshot if rest_bgcolor is None else rest_bgcolor()

    def _paint(hovered: bool) -> None:
        inner.bgcolor = _tint(hover_bgcolor) if hovered else _resting_bg()
        for i, ctl in enumerate(tinted):
            if hovered:
                ctl.color = _tint(hover_color)
            elif rest_color is None:
                ctl.color = color_snapshots[i]
            else:
                ctl.color = rest_color()
        inner.update()

    def _enter(_: ft.HoverEvent[ft.GestureDetector]) -> None:
        _paint(True)

    def _exit(_: ft.HoverEvent[ft.GestureDetector]) -> None:
        _paint(False)

    return ft.GestureDetector(
        inner,
        mouse_cursor=ft.MouseCursor.CLICK,
        on_enter=_enter,
        on_exit=_exit,
    )


#: 胶囊圆角。Flutter 画 RRect 时会把超出半高的圆角按比例缩到刚好贴合，所以
#: 给一个足够大的数就等于「两端是半圆」，不必跟着高度算。
PILL_RADIUS = 999
#: segmented_strip 渲染出来的外框高度。调用方给内容区算高度时按这个减 ——
#: 让它自己长会让高度成为一个只能靠眼睛量的数。
SEGMENTED_STRIP_H = 40
#: 外框内壁到滑块的留白，滑块靠这个才是「浮在里面」而不是贴着边。
_TRACK_INSET = 3
#: 滑块高度 = 外框 - 上下边框各 1 - 上下留白各 _TRACK_INSET。
_SEGMENT_H = SEGMENTED_STRIP_H - 2 - _TRACK_INSET * 2
#: 分隔线高度：比一行文字略高，两端留白，不顶到胶囊内壁。
_SPLIT_H = 16


def segmented_strip(
    labels: Sequence[str],
    on_select: Callable[[int], None],
    *,
    selected: int = 0,
) -> ft.Container:
    """站点导航条那种分段选择器：选中的一段铺 ``PRIMARY_TINT``，其余透明。

    用它而不用 ``ft.TabBar``：TabBar 的选中态只能是一条下划线。它的
    ``indicator`` 槽位只收 ``UnderlineTabIndicator``，而 ``overlay_color``
    走的是 InkWell 的状态机 —— Flutter 的 TabBar 不把 ``selected`` 交给
    InkWell，所以「选中态铺底」这个状态在那条路上根本不存在。

    形制是一整颗胶囊：外框一圈发丝边 + 最浅的 tint 底，里面每段之间一道竖直
    分隔线，选中的那段浮起来成一块白色的滑块（``SURFACE`` + ``row_shadow()``，
    与 nav 选中态同一套语言）。分隔线在紧挨滑块的两侧收起 —— 滑块自己的边界
    已经把那里分开了，再画一道就是两条线叠在一起。

    选中往**浅**里走（浮起），悬停往**深**里走（压下），两个方向相反，所以
    「指在上面」和「已经选中」不会看混。

    这一条自己管自己的选中状态：点哪一段就自己重画哪一段，再把序号交给
    ``on_select``。**画完不刷屏** —— 调用方接着要换内容，两件事合成一次
    ``page.update()`` 才是一个来回。
    """
    cells: list[ft.Container] = []
    texts: list[ft.Text] = []
    #: splits[i] 夹在 cells[i] 和 cells[i+1] 之间。
    splits: list[ft.Container] = []
    current = [selected]

    def _paint() -> None:
        for i, cell in enumerate(cells):
            active = i == current[0]
            cell.bgcolor = theme.SURFACE if active else None
            cell.shadow = (
                theme.row_shadow() if active else theme.row_shadow(opacity=0)
            )
            texts[i].color = theme.PRIMARY if active else theme.MUTED
            texts[i].weight = (
                ft.FontWeight.W_600 if active else ft.FontWeight.NORMAL
            )
        for i, split in enumerate(splits):
            split.visible = current[0] not in (i, i + 1)

    def _make_click(i: int) -> Callable[[ft.Event[ft.Container]], None]:
        def _click(_: ft.Event[ft.Container]) -> None:
            current[0] = i
            _paint()
            on_select(i)
        return _click

    def _rest_bg(i: int) -> Callable[[], ft.ColorValue | None]:
        return lambda: theme.SURFACE if i == current[0] else None

    def _hover_bg(i: int) -> Callable[[], ft.ColorValue | None]:
        # 已选中的那段悬停时保持原样：滑块被涂灰会让它看起来反而没被选中。
        return lambda: (
            theme.SURFACE if i == current[0] else theme.SURFACE_HOVER
        )

    def _rest_color(i: int) -> Callable[[], ft.ColorValue | None]:
        return lambda: theme.PRIMARY if i == current[0] else theme.MUTED

    def _hover_color(i: int) -> Callable[[], ft.ColorValue | None]:
        return lambda: (
            theme.PRIMARY if i == current[0] else theme.TEXT_PRIMARY
        )

    track: list[ft.Control] = []
    for i, label in enumerate(labels):
        if i:
            split = ft.Container(
                width=1, height=_SPLIT_H, bgcolor=theme.HAIRLINE,
            )
            splits.append(split)
            track.append(split)
        text = ft.Text(label, size=theme.BODY, no_wrap=True)
        cell = ft.Container(
            text,
            height=_SEGMENT_H,
            padding=ft.Padding.symmetric(horizontal=theme.SPACE_MD),
            alignment=ft.Alignment.CENTER,
            border_radius=PILL_RADIUS,
            animate=ft.Animation(theme.DURATION_INSTANT, theme.CURVE_IN),
            on_click=_make_click(i),
        )
        cells.append(cell)
        texts.append(text)
        track.append(hoverable(
            cell,
            tinted=[text],
            hover_bgcolor=_hover_bg(i),
            rest_bgcolor=_rest_bg(i),
            hover_color=_hover_color(i),
            rest_color=_rest_color(i),
        ))
    _paint()

    return ft.Container(
        ft.Row(
            track,
            spacing=theme.SPACE_XS,
            tight=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        height=SEGMENTED_STRIP_H,
        padding=ft.Padding.symmetric(horizontal=_TRACK_INSET),
        # 没有 alignment 是有意的：Container 一旦带 alignment，在有界约束下就会
        # 撑满父容器，Row 的 tight 拦不住 —— 胶囊会横铺整页。竖直居中由 Row 的
        # vertical_alignment 负责，不需要在这一层再对齐一次。
        bgcolor=theme.PRIMARY_TINT,
        border=ft.Border.all(1, theme.HAIRLINE),
        border_radius=PILL_RADIUS,
    )
