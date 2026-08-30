from __future__ import annotations

import asyncio
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
                ft.Text(
                    label,
                    size=theme.CAPTION,
                    color=theme.MUTED,
                    style=theme.caption_style(),
                ),
                ft.Text(
                    value,
                    size=24,
                    weight=ft.FontWeight.BOLD,
                    color=color,
                    text_align=ft.TextAlign.CENTER,
                    style=theme.numeric_style(),
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
        ft.Text(
            status,
            size=theme.CAPTION,
            color=theme.ON_FILLED,
            style=theme.caption_style(),
        ),
        bgcolor=theme.SUCCESS if status == "Completed" else theme.WARNING,
        border_radius=12,
        padding=ft.Padding(left=8, right=8, top=2, bottom=2),
    )


def section_title(text: str) -> ft.Text:
    return ft.Text(
        text,
        size=theme.TITLE,
        weight=ft.FontWeight.BOLD,
        style=theme.title_style(),
    )


def success_banner(message: str, details: list[str] | None = None) -> ft.Container:
    controls: list[ft.Control] = [
        ft.Row([
            ft.Icon(ft.CupertinoIcons.CHECKMARK_CIRCLE_FILL, color=theme.SUCCESS),
            ft.Text(message, weight=ft.FontWeight.BOLD),
        ]),
    ]
    for d in details or []:
        controls.append(ft.Text(
            d,
            size=theme.CAPTION,
            color=theme.MUTED,
            style=theme.caption_style(),
        ))
    return ft.Container(
        content=ft.Column(controls),
        bgcolor=theme.SUCCESS_TINT,
        border_radius=theme.CARD_RADIUS,
        border=ft.Border.all(1, theme.HAIRLINE),
        shadow=theme.row_shadow(),
        padding=theme.SPACE_LG,
    )


def error_banner(message: str) -> ft.Container:
    return ft.Container(
        content=ft.Row([
            ft.Icon(ft.CupertinoIcons.XMARK_CIRCLE_FILL, color=theme.DANGER),
            ft.Text(message),
        ]),
        bgcolor=theme.DANGER_TINT,
        border_radius=theme.CARD_RADIUS,
        border=ft.Border.all(1, theme.HAIRLINE),
        shadow=theme.row_shadow(),
        padding=theme.SPACE_LG,
    )


def warning_banner(message: str, details: list[str] | None = None) -> ft.Container:
    controls: list[ft.Control] = [
        ft.Row([
            ft.Icon(ft.CupertinoIcons.EXCLAMATIONMARK_CIRCLE_FILL, color=theme.WARNING),
            ft.Text(message, weight=ft.FontWeight.BOLD),
        ]),
    ]
    for d in details or []:
        controls.append(ft.Text(
            d,
            size=theme.CAPTION,
            color=theme.MUTED,
            style=theme.caption_style(),
        ))
    return ft.Container(
        content=ft.Column(controls),
        bgcolor=theme.WARNING_TINT,
        border_radius=theme.CARD_RADIUS,
        border=ft.Border.all(1, theme.HAIRLINE),
        shadow=theme.row_shadow(),
        padding=theme.SPACE_LG,
    )


#: 颜色槽位收的东西：一个定值，或者一个「问的时候才算」的取值器。
Tint = "ft.ColorValue | Callable[[], ft.ColorValue | None] | None"


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

    也不用 ``ft.SegmentedButton``：它的选中和按下反馈是 Material 的涟漪，跟
    这套 Linear 风 + squircle 的交互态是两套语言。全 app 的分段选择都走这个
    函数，不要再引入前两者。**它只把序号报给 ``on_select``**，值由调用方按
    自己那张表查 —— 见 manage.py 的 ``_VIEWS``。

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


def loading_row(label: str) -> ft.Row:
    return ft.Row(
        [
            ft.ProgressRing(width=20, height=20),
            ft.Text(
                label,
                size=theme.CAPTION,
                color=theme.MUTED,
                style=theme.caption_style(),
            ),
        ],
        spacing=theme.SPACE_SM,
    )


#: 淡出占整段过渡的比例，剩下的归淡入。旧的走得快、新的进得慢 —— 视线是跟着
#: 新内容走的，给它更多时间落位。
_FADE_OUT_SHARE = 0.3


def swap_slot(
    page: ft.Page,
    content: ft.Control,
    duration: int = theme.DURATION_BASE,
) -> tuple[ft.Container, Callable[..., None]]:
    """一块会自己换内容的区域：淡出 → 换掉 → 淡进来。返回 (控件, 换的函数)。

    只淡，不动。要横向推拉（旧的往一侧出、新的从另一侧进）用 push_track ——
    一个容器只有一个 ``offset``，做不出两页各走各的方向。

    **这件事不能交给 ``ft.AnimatedSwitcher``。** 它把新旧两份同时挂进一个
    Stack 里交叉淡开，而那个 Stack 居中对齐、高度取两份里较高的一份 —— 两份
    高度不一样时（换 tab 就是），新内容会先悬在半空，等旧的卸载完再弹回顶部。
    Flet 没有暴露 ``layoutBuilder`` 或 ``alignment``，改不掉。这里同一时刻只
    有一份内容在场，高度是在完全透明的那一刻变的。

    不存在「必须先渲染一帧」的竞态：``animate_opacity`` 补的是「已经画出来的
    那个值」到新值之间的差，而这个容器是**常驻**的，改的是它自己已经画出来的
    值。新建一个控件再改它的属性则不然 —— 那种写法会静默失效，不报错，只是
    不动。
    """
    out_ms = int(duration * _FADE_OUT_SHARE)
    in_ms = duration - out_ms
    slot = ft.Container(
        content,
        animate_opacity=ft.Animation(out_ms, theme.CURVE_OUT),
    )
    #: 淡出还没走完就又点了一次时，只让最后那次算数 —— 否则先发的那次会在
    #: 后发的那次之后落地，屏幕上留下的是用户更早点的那个。
    latest = [0]

    def show(content: ft.Control) -> None:
        token = latest[0] = latest[0] + 1
        slot.animate_opacity = ft.Animation(out_ms, theme.CURVE_OUT)
        slot.opacity = 0
        page.update()

        async def _swap() -> None:
            # 等的是淡出这段动画本身的时长，不是「等一帧」—— 时长是已知的，
            # 睡够了它一定播完了。
            await asyncio.sleep(out_ms / 1000)
            if token != latest[0]:
                return
            slot.content = content
            slot.animate_opacity = ft.Animation(in_ms, theme.CURVE_IN)
            slot.opacity = 1
            page.update()

        page.run_task(_swap)

    return slot, show


def _park(index: int, current: int) -> ft.Offset:
    """一格停在哪，只看它和当前那格的先后：靠前的在左边一格，当前那格在原位，
    靠后的在右边一格。"""
    if index < current:
        return ft.Offset(-1, 0)
    if index > current:
        return ft.Offset(1, 0)
    return ft.Offset(0, 0)


def push_track(
    page: ft.Page,
    panes: int,
    content: ft.Control,
    duration: int = theme.DURATION_BASE,
    *,
    start: int = 0,
    padding: ft.PaddingValue | None = None,
    fill: bool = False,
) -> tuple[ft.Container, Callable[[int, ft.Control], None]]:
    """并排 N 格的推拉轨道：换到第 ``index`` 格，旧的往一侧出去、新的从另一侧
    进来，**两者同向**。返回 (控件, 换的函数)。

    这是 swap_slot 做不到的那一半。一个容器只有一个 ``offset``，新内容进场的
    那一侧必然就是旧内容退场的那一侧 —— 往前走时旧页朝着新页来的方向退，读
    起来是两页对着走。这里每一格是**独立且常驻**的容器，各有各的 offset。

    每格停在哪只看它和当前那格的先后：靠前的在左边一格（-1），当前那格在原位
    （0），靠后的在右边一格（+1）。切换时全体重算，于是退场那格往左走、进场
    那格从右边推过来 —— 同一个方向。落点只在 -1 / 0 / +1 之间取，每格都是从
    **自己上一次画出来的位置**动到新位置，所以不需要任何瞬移，也就没有「必须
    先渲染一帧」的竞态。

    不在场的几格是透明的：三格以上时中间那格会横穿整个视口，不透明就是一道
    闪。

    **外面那层的 ``bgcolor`` 是裁剪的开关，不是装饰，别删。** Flet 把
    ``bgcolor`` / ``border`` / ``border_radius`` 合成一个 ``BoxDecoration``
    交给 Flutter 的 Container，而 Container 只在**有** decoration 时才插那层
    ClipPath —— 三者一个都不设的话，``clip_behavior`` 是一句空话，不报错也不
    裁，滑出去的那一格照样画到左边的导航栏上。取的是页面底色，所以看不出来。

    ``ft.Stack`` 自己的 ``clip_behavior`` 顶不上：Flutter 的 Stack 只在**布局**
    溢出时才裁，而 ``offset`` 是画的时候平移的，布局上每一格都严丝合缝。

    ``padding`` 是页面自己的边距，交给这里而不是在外面套一层：套在外面，裁剪
    边界就退到边距内侧，页面会在离导航栏还有一段的地方凭空出现和消失，中间留
    一条什么都不发生的白边。

    ``start`` 是开局停在第几格。记着上次选了哪个视图的地方要传它 —— 默认从
    第 0 格开局，再 ``show`` 到别处就等于一进页面先推一下。

    ``fill=True`` 让每格撑满轨道的盒子，给**定高**的视口用（下载页那块算出来
    的高度）—— 松约束下格子会缩到内容的固有高度，子页的 expand 和内部滚动就
    不成立了。高度无界的地方（settings 挂在滚动列里）必须留 False，撑满会向
    无穷大要尺寸。
    """
    track: list[ft.Container] = [
        ft.Container(
            content if i == start else ft.Column(),
            padding=padding,
            offset=_park(i, start),
            opacity=1.0 if i == start else 0.0,
            animate_offset=ft.Animation(duration, theme.CURVE_PAGE),
            animate_opacity=ft.Animation(duration, theme.CURVE_PAGE),
        )
        for i in range(panes)
    ]
    current = [start]
    latest = [0]

    def show(index: int, content: ft.Control) -> None:
        track[index].content = content
        if index == current[0]:
            page.update()
            return
        current[0] = index
        token = latest[0] = latest[0] + 1
        for i, pane in enumerate(track):
            pane.offset = _park(i, index)
            pane.opacity = 1.0 if i == index else 0.0
        page.update()

        async def _drop() -> None:
            # 推完把不在场的几格清空：Stack 的高度取最高的一格，留着内容会让
            # 整块一直按最高的那一页撑着。清掉的是格子，不是调用方手里的控件
            # 对象 —— 表单填到一半的状态在调用方那边，挂回来不丢。
            await asyncio.sleep(duration / 1000)
            if token != latest[0]:
                return
            for i, pane in enumerate(track):
                if i != index:
                    pane.content = ft.Column()
            page.update()

        page.run_task(_drop)

    # Stack 收 list[Control]；上面那份保持 list[Container]，改属性时才有类型。
    controls: list[ft.Control] = list(track)
    stack = ft.Stack(
        controls,
        # 顶对齐：两格高度不一样时，矮的那格必须待在顶上。居中对齐正是
        # AnimatedSwitcher 让内容先悬在半空的那个毛病。
        alignment=ft.Alignment.TOP_LEFT,
        fit=ft.StackFit.EXPAND if fill else ft.StackFit.LOOSE,
    )
    return ft.Container(
        stack,
        bgcolor=theme.PAGE_BG,  # 见 docstring：这是裁剪的开关
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
    ), show


#: 骨架条的高度：一行正文的行盒。
_SKELETON_BAR_H = 18
#: 逐行占宽的份数（满格 100）。长短不一才像一段真内容 —— 一摞等长的灰条读起来
#: 是个进度条。``expand`` 只收整数 flex，所以这里是份数不是比例。
_SKELETON_WIDTHS = (96, 82, 94, 70, 88, 76)


def skeleton(rows: int = 6) -> ft.Shimmer:
    """等待态：结果是「一堆形状相似、条数未知的东西」时用这个。

    行数是假的。骨架屏预告的是**形状**，不是数量 —— 给的行数只要够撑起一块
    有份量的轮廓就行，真结果回来时整块被换掉。

    单个结果、或者有明确阶段的长任务不要用它：那些用进度条 + 文字阶段，
    同样的屏幕面积里信息量更大。
    """
    bars: list[ft.Control] = []
    for i in range(rows):
        share = _SKELETON_WIDTHS[i % len(_SKELETON_WIDTHS)]
        bars.append(ft.Row([
            ft.Container(
                height=_SKELETON_BAR_H,
                border_radius=theme.CARD_RADIUS,
                # 底色只定形状 —— Shimmer 是一层 shader mask，画出来的颜色
                # 全部来自 base / highlight。
                bgcolor=theme.HAIRLINE,
                expand=share,
            ),
            # 补满这一行剩下的份数，否则唯一的 flex 子控件会一路撑到头，
            # 每根条都一样长。
            ft.Container(expand=100 - share),
        ], spacing=0))
    return ft.Shimmer(
        content=ft.Column(bars, spacing=theme.SPACE_MD),
        base_color=theme.HAIRLINE,
        highlight_color=theme.SURFACE,
    )
