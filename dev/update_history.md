# Dev Logs

---

## 2026-07-14 — 大 PDF 批改修复 + 批改流程响应式布局收尾

**改动文件：** `modules/renderer.py`, `tests/test_renderer.py`, `pyproject.toml`, `uv.lock`, `app_flet/tabs/mark.py`, `app_flet/tabs/analytics.py`, `app_flet/tabs/manage.py`, `app_flet/components/widgets.py`

### 大 PDF 批改失败根因 + 修复(核心)

**症状:** iPad 上用一份真实 9700 GoodNotes 答卷(34MB、21 页高清扫描图)批改,点"开始批改"后有进度条但**出不来结果**。

**逐层排除(在真实文件上):** 分割 27/27、嵌套题号 `Q1(a)(i)`、评分标准数据、批改 API 调用、结果解析、PDFium 渲染(0.26s/页)——**全部正常**。唯一挂的是渲染 RPC 传输。

**根因:** `NativeRenderer.render_regions` 在批改循环里**每道题都把整份 34MB PDF 经 Flet Python↔Dart RPC 传一遍**;34MB 的 msgpack 负载(×题数、120s 超时)撑爆传输 → 渲染协程失败 → 批改循环抛异常 → 被 `批改失败` 吞掉 → `grading_results` 为空 → Step 4 不显示。9231 答卷小,从没碰到。

**修复(即 Phase 3 当初 defer 的"页预抽取"优化——大 PDF 测试既然挂了就补上):** 新增 `modules/renderer.py` `_extract_pages(pdf, pages)`,用纯 Python **pypdf**(iOS 安全,新增 runtime 依赖)只抽出这道题 clip 涉及的那几页、重映射页码,再发给 Dart。每题 RPC 负载 **34MB → 2.6–4.6MB**;抽出页渲染与原页**逐字节相同**;`render_pages` 因委托给 `render_regions` 一并受益;空 clip 短路返回 `[]`。新增 2 个单测。**已真机验证:34MB 答卷现在能正常出批改结果。**

### 响应式布局收尾(手机/iPad 窄屏 overflow)

- **Mark Step 2 页码输入 / Step 3 题目勾选**:`ResponsiveRow` 的断点在 iPad 上塌成一列且重叠 → 换成 `_responsive_grid()`,按 `page.width` 实时算列数并切成定宽 `ft.Row`(手机 ~2–3 列、iPad ~4–8 列)。
- **Step 4 批改结果**:① `metric_card`(总分/百分比/题数)原本死写 `110×85` 配 size-28 数值,`123/150`/`100.0%` 塞不下 → 宽度 132、去掉固定高度自适应、size-24 居中换行;② 每题对错理由 / 评语的 `Text` 在 `Row` 里没 `expand`,长中文横向溢出 → 加 `expand=True` + 顶部对齐,自动折行。
- **Analytics / Manage**(前次已并入 part 2,此处并列记录):趋势图按屏宽 + 横向滚动、SegmentedButton 横向滚动、Manage 卡片分数并入可伸缩左列。

### 注意事项

- `page.width` 在建 tab 时读一次;旋转设备不会实时重排,需切走再切回。若要实时,加 `page.on_resized` 回调。
- pypdf 读 GoodNotes 的畸形 xref 会打 warning,已在 `_extract_pages` 里把 `pypdf` logger 降到 ERROR。
- 遗留:`ruff check .` / `mypy .` 各 1 个错,均在 `extensions/.../examples/.../main.py`(dev 示例,早于本次),app 代码树干净。

---

## 2026-07-13 — Phase 2 part 2：全应用切换到原生 pdfrx 渲染、彻底移除 pdfplumber，iOS 端到端跑通

**改动文件：** `modules/renderer.py`（新增）, `tests/test_renderer.py`（新增）, `modules/pdf_renderer.py`（删除）, `modules/grader.py`, `modules/mcq_parser.py`, `modules/ms_parser.py`, `app_flet/main.py`, `app_flet/state.py`, `app_flet/tabs/mark.py`, `app_flet/tabs/analytics.py`, `app_flet/tabs/manage.py`, `pyproject.toml`, `uv.lock`

### 功能说明

承接 part 1（2A 解耦 + 2B.1 扩展）：把 app 的**全部渲染路径**接到原生 pdfrx 扩展上，删掉最后一个 pdfplumber 使用者，让整个 `app_flet` import 图彻底无 pdfplumber。至此 iOS 迁移的三大阻塞（画图 kaleido、分割 pdfplumber、渲染 pdfplumber）全部清除，`flet build ios-simulator` 打包成功且在模拟器上把「解析评分标准 → 分割答卷 → 渲染 → AI 批改 → 记录分数」完整流程跑通，**功能在 iOS 上全部可行**。

### 2B.2 — 渲染抽象层 `modules/renderer.py`

- **纯函数**（app 无关、单测覆盖）：`to_pdf_bytes(source)` 归一化 path/bytes；`page_count(source)`、`full_page_clips(source)` 经 pdfminer 读页数与页尺寸（iOS 安全，不碰 pdfplumber）。
- **`NativeRenderer(service, loop)`**：把扩展里 async 的 `PdfRenderer` 服务桥接到**同步、后台线程**的批改循环——`asyncio.run_coroutine_threadsafe(coro, loop).result()`，loop 取自 `page.session.connection.loop`。提供 `render_regions(source, clips, dpi)` 和 `render_pages(source, page_numbers, dpi)`。

### 2B.3 — 全应用切到原生渲染，删除 pdfplumber

- **`app_flet/main.py` / `state.py`**：创建一个 `PdfRenderer()` 服务挂到 `page.services`，存到 `state.pdf_renderer`，全 app 复用。
- **`mark.py`**：`_do_parse`/`_do_segment`/`_do_grade` 改用 `NativeRenderer`；页数用 `page_count`（pdfminer），分割用已迁好的 `segment_questions`（pdfminer），渲染用 native。
- **`ms_parser.py` / `mcq_parser.py`**：这两处原本各自开 pdfplumber 渲染，改成接收 `NativeRenderer`；MCQ 文本提取也走 pdfminer。
- **`grader.py`**：删除已死的 pdfplumber 渲染函数。
- **删除 `modules/pdf_renderer.py`**（pdfplumber 版渲染器整文件移除）。
- **`pyproject.toml`**：`flet[all]`→`flet`（`[all]` 会拖进 flet-cli→watchdog，无 iOS wheel）；pdfplumber/streamlit 降级到 `legacy` extra 与 dev group（仅本地跑旧 Streamlit app / 全量测试用）；runtime 依赖加 `pdfminer.six` 与本地扩展 `flet-pdf-render`。**app_flet import 图现已无 pdfplumber**（mypy/ruff/测试全绿）。

### 2B.4 — iOS 打包解阻 + 响应式 UI 修复

- **`[tool.flet.app] exclude = ["extensions", "spikes", "tests", "dev"]`**：`flet build` 只排顶层 `build/`，而扩展示例残留的 `build/` 里有自嵌套 `.pod/dist_macos/...` 超长路径，打包拷贝时 `errno 63 File name too long`。扩展的 Python 来自已安装依赖、Dart 来自已安装包的 bundled data，源码树无需进包，故整目录排除是安全的。
- **响应式修复（`analytics.py`/`mark.py`/`manage.py`）**：手机窄屏下三个 tab 的定宽横向布局触发 RenderFlex overflow。趋势图 Canvas 从死写 600px 改为按 `page.width` 计算并夹在 280..600、外套横向滚动；per-paper-type 的 SegmentedButton 横向滚动；Mark 的 Step 2 页码输入 / Step 3 题目勾选从死写「每行 5 个」改 `wrap=True` 自适应；Manage 列表卡片把分数文本挪进可伸缩的左列，右侧只留定宽按钮，杜绝溢出。

### 注意事项

- 桥接用的 event loop 必须是 flet page 的 loop（`page.session.connection.loop`），批改在 `page.run_thread` 的后台线程里跑，用 `run_coroutine_threadsafe` 回到该 loop 才能调到 async 的扩展服务。
- `tests/test_paper_type.py::test_grader_config_try_load_returns_none_when_missing` 在本机因 `~/.cie_helper/.env` 有真实凭证而失败，属环境相关、与本次改动无关。

---

## 2026-07-12 — Phase 2 part 1：modules 解耦（2A）+ pdfrx 原生渲染 Flet 扩展（2B.1）

**改动文件：** `modules/__init__.py`, `tests/test_modules_import.py`（新增）, `extensions/flet_pdf_render/`（新增整个扩展）

### 功能说明

延续 iOS 迁移：Phase 1 已把题目分割从 pdfplumber 迁到 pdfminer.six，Phase 2 要把**渲染**也迁离 pdfplumber（`pypdfium2` 无 iOS wheel），改用 Flet 自定义 Dart 扩展 + pdfrx（PDFium/PDFKit 原生）。本次完成两块:让 `modules` 能在无 streamlit/pdfplumber 环境下 import(2A)，以及写出并端到端验证了 pdfrx 渲染扩展(2B.1)。尚未接入 app（2B.2/2B.3/2B.4 待做）。

### 2A — 解耦 `modules/__init__.py`

- **`modules/__init__.py`**：原来 eager import 了所有子模块（含 Streamlit 版 `visualizer`、pdfplumber 版 `pdf_renderer`），导致 `import modules.page_segmenter` 就会拖进 streamlit + pdfplumber，iOS 上直接崩、且 streamlit 变 optional 后 pytest 收集就报错。改为**不做任何 eager re-export**（全仓库无人用 `from modules import X`，直接 import 子模块即可）。
- **`tests/test_modules_import.py`**（新增）：子进程 import guard，断言 `import modules.page_segmenter`/`modules.grader` 不会把 streamlit 拉进 `sys.modules`。

### 2B.1 — pdfrx 原生渲染 Flet 扩展（`extensions/flet_pdf_render/`）

- **Python 侧**：`PdfRenderer(ft.Service)` + `RenderClip`，`render_regions(pdf: bytes, clips, dpi) -> list[bytes]`，经 `_invoke_method("render_regions", …)` 把 PDF 字节和裁剪矩形传给 Dart，拿回每个区域的 PNG 字节。
- **Dart 侧**：`PdfRendererService(FletService)`，`PdfDocument.openData(bytes)` 打开，`page.render(x,y,width,height,fullWidth,fullHeight)` 渲染每个全宽竖直切片（点→像素按 `dpi/72`，top-origin），`PdfImage.createImage() → toByteData(png)` 转 PNG，返回 `List<Uint8List>`。`Extension.createService` 按控件类型 `"PdfRenderer"` 注册。pubspec 加 `pdfrx: ^2.4.4`。
- **端到端验证（Windows 桌面）**：对真实 9702 物理卷渲染，整页切片 `y=0..792pt @150dpi → 1275×1650px`、裁剪 `y=60..300pt → 1275×500px`，点→像素映射精确、渲染内容清晰正确。

### 注意事项：Chinese Windows 上 `flet build windows` 三个坑

1. **路径过长**：worktree 路径太深会触发 `C1083`/`FTK1011`（FileTracker 非长路径感知，junction 也没用因为工具会解析回真实路径）。需从**短的真实路径**构建（如 `robocopy` 到 `C:\pdfext` 再 build）。
2. **UTF-8**：flet 日志打 emoji（✅🥳），GBK 控制台编码报 `UnicodeEncodeError`，表现为误导性的 "app.zip was not created"。需 `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`。
3. **exe 占用**：重建时旧 exe 还在跑会锁 `libcrypto-3.dll` → `PermissionError`，需先 `taskkill /F /IM <app>.exe`。

**改动文件：** `app_flet/tabs/analytics.py`, `pyproject.toml`, `uv.lock`

### 功能说明

为 iOS 打包扫清最大阻塞点：`kaleido` 内嵌无头 Chromium 做 PNG 导出，在 iOS 沙盒环境下无法运行。将 Analytics tab 的成绩趋势图从 plotly → kaleido → PNG → base64 → `ft.Image` 的渲染链路，改为用 `flet.canvas`（`Points`/`PointMode.POLYGON` 画线、`Circle` 画点、`Text` 画坐标轴标签）原生绘制，完全去掉 `plotly`/`kaleido` 依赖。

- 确认当前 flet 版本（0.85.3，新架构）没有内置图表控件（旧版的 `ft.LineChart` 已不存在），但 `flet.canvas` 是核心控件自带，无需额外依赖
- `pyproject.toml`/`uv.lock` 中移除 `plotly`、`kaleido`
- `pandas` 保留（`core/storage.py` 的 CSV 存取仍依赖），仅替换图表渲染部分

## 2026-07-06 — Windows 构建修复 + .env 路径迁移 + Cupertino 白色文字全局修复

**改动文件：** `main.py`, `core/settings.py`, `app_flet/main.py`, `app_flet/tabs/mark.py`, `app_flet/tabs/download.py`, `app_flet/components/dialogs.py`

### 功能说明

修复 `flet build windows` 构建后 exe 闪退问题，将 `.env` 从项目根目录迁移到 `~/.cie_helper/.env` 以支持打包后和 iOS 环境，并全面修复 iOS Cupertino 模式下控件文字不可见的问题。

### 1. Windows 构建入口修复（`main.py`）

- 根目录 `main.py` 原为占位符（仅 `print("Hello")`），`flet build` 打包后 exe 启动即退出无 UI
- 改为 `import flet as ft; from app_flet.main import main; ft.app(main)` 正确调用 Flet 入口
- 构建后的 `cie-helper.exe` 现在能正常显示完整界面

### 2. `.env` 路径迁移（`core/settings.py`）

- `_ENV_PATH` 从 `Path(".env")`（相对路径）改为 `Path.home() / ".cie_helper" / ".env"`
- `MailConfig` 和 `GraderConfig` 的 `env_file` 配置同步更新为新路径
- 解决了打包后 exe 因 cwd 不确定而找不到 `.env` 的问题
- iOS 上 `Path.home()` 指向 app 沙箱 Documents 目录，天然兼容
- 已将现有 `.env` 复制到 `~/.cie_helper/.env`

### 3. Cupertino 白色文字全局修复（`app_flet/main.py`, 多个 UI 文件）

- `page.adaptive` 从 `True` 改为 `False`，iOS 上也使用 Material 控件，避免 Cupertino 控件忽略 `label_style` 等 Material 属性
- 在 `page.theme` 中添加 `ColorScheme(on_surface=BLACK)` 和完整的 `TextTheme` 样式覆盖
- 所有 `ft.Dropdown` 和 `ft.TextField` 补充 `label_style=ft.TextStyle(color=ft.Colors.BLACK)`，覆盖文件：
  - `app_flet/tabs/mark.py`：科目/试卷 Dropdown、起始页/页码分配/调分/MCQ 手动输入 TextField
  - `app_flet/tabs/download.py`：Paper ID TextField
  - `app_flet/components/dialogs.py`：提交分数 Dropdown + TextField、设置页全部 TextField

---

## 2026-07-05 — Flet Mark tab (Math+MCQ) 完成 + Analytics 性能重构 + 分割/排序 bug 修复

**改动文件：** `app_flet/main.py`, `app_flet/state.py`, `app_flet/tabs/mark.py`, `app_flet/tabs/analytics.py`, `modules/ms_parser.py`, `modules/page_segmenter.py`, `.claude/launch.json`（新增）；删除遗留原型 `app_flet.py`

### 功能说明

继续 Streamlit→Flet 迁移的 Phase 4/5：完成 Mark tab 的 Math 结构化批改与 MCQ 批改两条完整流程，重构 Analytics tab 解决卡顿，并修复了批改流程中暴露出的两个 shared module（`page_segmenter.py`/`ms_parser.py`）级别的正确性 bug。

### 1. Mark tab — Math 结构化批改（`app_flet/tabs/mark.py`）

- Step 1：评分标准来源选择（已下载试卷 / 上传 PDF）+ 科目代码下拉 + 试卷下拉（按 paper_id 排序）+ 题型选择 + AI 解析（带批次进度条）
- Step 2：上传答卷 PDF → 后台线程自动分割题目（`segment_questions`）→ 每题页码文本框（自动填充检测结果，可手动改）+ 删除题目按钮
- Step 3：思考模式开关 + 题目复选框（"全选"/"全不选"）+ 后台线程逐题 AI 批改（裁剪题目区域优先，退回整页渲染）+ 进度条
- Step 4：批改结果展开卡片（每个 marking point 对错图标 + 理由）+ 调分输入框 + 确认并写回 CSV

### 2. Mark tab — MCQ 批改（`app_flet/tabs/mark.py` `_build_mcq_flow`）

- 上传标注过的 QP → 通过 Vision API 检测学生作答（`detect_student_answers`）
- 未检测到的题目提供手动下拉修正
- 即时计分（无需 AI），确认后写回 CSV

### 3. Analytics tab 性能重构（`app_flet/tabs/analytics.py`）

此前每次打开统计页会为所有科目 × 所有 Paper Type 组合同时渲染 Plotly 折线图（每张图 kaleido 冷启动 ~2 秒）且全部展开，导致打开页面卡顿数十秒，且后续任何操作都会排在这个同步渲染后面（表现为"点设置一分钟后才弹出"）。

- 科目区块默认折叠（`expanded=False`），只在**首次展开时**才构建该科目内容（含图表），避免打开 tab 时全量渲染
- 同一科目内新增 Paper Type 切换板（`SegmentedButton`），一次只渲染当前选中类型的图表+表格，不再把所有 Paper Type 堆叠展示
- 折线图标题暂时禁用（用户要求，减少视觉噪音）

### 4. 修复：`_build_syllabus_section` 挂载前访问 `.page` 崩溃

`ExpansionTile` 内容在挂载前（`build_analytics_tab` 首次同步构建阶段）就调用 `type_content.page` 判断是否需要 `page.update()`——Flet 的 `Control.page` 属性在控件未挂载时直接抛 `RuntimeError`。该异常被 Flet 的事件分发器静默捕获并显示为阻塞性错误浮层，表现为"切换到统计/管理/批改后无法再切换其他 tab"。改为只在用户触发的 `on_change`/`on_expand` 回调里调用 `page.update()`，初次构建不再调用。

### 5. 修复：`app_flet.py` 遗留原型覆盖包目录

仓库根目录残留了拆包前的单文件原型 `app_flet.py`（491 行，只有 Download tab demo）。`flet run app_flet` 在文件与同名目录都存在时优先解析成 `.py` 文件，导致所有测试实际跑的是这个过时原型而非 `app_flet/` 包，白测了好几轮。定位后删除该文件（未纳入版本控制，可安全删除）。

### 6. 修复：`modules/page_segmenter.py` 裁剪区域为零面积崩溃

用户的真实答卷跑批改时崩溃：`ValueError: Bounding box (0, 217.0, 612, 217.0) has an area of zero`。根因是 `_build_regions()` 只对跨页裁剪片段做了最小高度校验，同页裁剪片段完全没有下限——当两个相邻题目边界检测到同一 Y 坐标时（常见于嵌套子题只按字母级边界匹配、罗马数字子子题共享同一坐标的情况），会生成零高度矩形，crop 时抛异常。

- 同页分支补上与跨页分支一致的 `_MIN_CLIP_HEIGHT` 校验，退化片段直接跳过（不再崩溃，题目会退回整页渲染兜底）
- 顺带补上了罗马数字子子题（`(i)`/`(ii)`/`(iii)`）的独立边界检测（新增 `_BoundaryKind.SUBSUB`），让嵌套子题裁剪更精确，`_MIN_CLIP_HEIGHT` 相应从 50pt 收紧到 20pt 以适配更细粒度的裁剪

### 7. 修复：`modules/ms_parser.py` 题目排序混合记法导致乱序

VL 模型提取的题号记法不统一（有的被 `normalize_question_id` 规整成 `"Q2a"`，有的因不匹配正则原样保留成 `"Q2(b)(i)"`），原排序 key 对主序号相同的题目直接按字符串比较，导致 `"("`（ASCII 40）排在字母前面，"Q2(b)(i)" 排到了 "Q2a" 前面。新增 `_question_sort_key()` 提取 `(主序号, 子字母, 罗马数字序号)` 三元组排序，与记法风格无关。已用该 key 就地重新排序了两个既有的 mark scheme 缓存文件（`~/.cie_helper/.cache/ms/*.json`），无需重新调 AI 解析。

### 8. Mark tab UI 细节修复

- Checkbox 固定宽度导致短标签文字被拉伸放大、长短不一——改为把宽度约束放在外层 `Container` 上，`Checkbox` 本体不再被强制拉伸
- "全不选"点击后下一次 rebuild 会被"若列表为空则自动填充全部"的兜底逻辑重新填满，导致无法真正取消全选——改为一次性 `seeded` 标记，只在首次构建时兜底填充一次
- 新增"全选"/"全不选"按钮
- Step 2 页码输入框布局从 3 列改为与 Step 3 复选框一致的 5 列每行

### 验证结果

- `ruff check .` / `mypy`：涉及文件全部通过
- `pytest`：69/71 passed，2 个既存失败（`test_main_with_subs` 排序断言与本次改动无关、`GraderConfig try_load` 因本机 `.env` 已配置真实 key 触发，均非本次改动引入）

---

## 2026-07-02 — fitz→pdfplumber 迁移 + Mark tab 性能修复 + 评分 prompt 优化

**改动文件：** `app.py`, `core/settings.py`, `modules/grader.py`, `modules/mcq_parser.py`, `modules/ms_parser.py`, `modules/page_segmenter.py`, `modules/pdf_renderer.py`, `pyproject.toml`, `tests/test_page_segmenter.py`, `uv.lock`

### 功能说明

为 iOS 移植做准备，将所有 PyMuPDF (`fitz`) 调用替换为 pdfplumber 等价写法。迁移过程中发现并修复了两个 pdfplumber 特有的行为差异导致的回归 bug，新增 mark scheme 缓存功能，修复 Mark tab 严重卡顿问题，并优化 AI 评分 prompt 解决输出冗长和自我矛盾问题。

### 1. fitz→pdfplumber 全量迁移

- **`modules/page_segmenter.py`**：最复杂的迁移。pdfplumber 渲染 CID 字体为 `(cid:N)` 字符串，所有 `len(text)` / `ord(text[0])` 判断全部失效。新增 `_parse_codepoints()` helper 做 CID-aware 解析，`_build_char_mapping`、`_decode_question_num`、`_extract_boundaries`、`_detect_bracket_pair` 全部改为使用 codepoint list
- **`modules/grader.py`**：手写检测从 `page.get_drawings()` 迁移到 `page.curves` + `page.lines`。发现 pdfplumber 的 `page.curves` 不含 PDF annotation layer 的 ink strokes（Apple Pencil/stylus 批注），新增 `page.annots` InkList 检测作为第一优先级 heuristic
- **`modules/pdf_renderer.py`**：`page.get_pixmap()` → `page.to_image().original` (PIL) + BytesIO 导出 PNG。修复 `_page_to_png` 参数类型从 `PDF` 到 `Page`
- **`modules/mcq_parser.py`**、**`modules/ms_parser.py`**：import 修改为 `from pdfplumber.pdf import PDF`（pdfplumber 的 `PDF` 未在 `__all__` 导出，直接 import 会触发 mypy `name-defined` 错误）
- **`app.py`**：`fitz.open` → `pdfplumber.open`，`len(doc)` → `len(pdf.pages)`
- **`pyproject.toml`**：移除 `pymupdf` 依赖，新增 `fpdf2`（dev dependency，测试用），pdfplumber 加入 mypy ignore list
- **`tests/test_page_segmenter.py`**：合成 PDF 从 `fitz.open()` + `insert_text()` 改为 `fpdf2` 生成；修复 `test_cross_page_region` 的 `end_y` 阈值（60→200，低于 `_MIN_CLIP_HEIGHT=50` 导致测试失败）

### 2. Mark scheme 缓存

- **`modules/ms_parser.py`**：新增 `_cache_path_for()` / `_load_cached()` / `_save_cache()` 三个函数，parse 过的 mark scheme 以 `PaperConfig.model_dump_json()` 缓存到 `~/.cie_helper/.cache/ms/<stem>.json`，下次 parse 直接读缓存
- **`core/settings.py`**：`AppSettings` 新增 `ms_cache_dir` property + `init_dirs` 创建缓存目录

### 3. Mark tab 性能修复

- **`app.py`**：`pdfplumber.open()` + `detect_handwriting_pages()` + `segment_questions()` 原先在每次 Streamlit rerun 时都会重新执行（用户每按一个键都触发），导致严重卡顿。将三者合并到 `auto_pages_done` guard 内，结果缓存到 `st.session_state`，后续 rerun 直接读缓存。上传新 PDF 时清除缓存

### 4. AI 评分 prompt 优化

- **`modules/grader.py`**：`_MATH_GRADING_PROMPT` 新增"关键约束"部分：
  - `reason` 字段限制为一句话（≤40 字），禁止写推理过程，附正确/错误示范
  - `total` 必须等于 `awarded=true` 的数量之和，禁止 reason 说"应给分"但 `awarded=false` 的矛盾
  - 要求"先做决定再填 JSON，不要在 reason 中犹豫或自我质疑"

### 验证结果

- `ruff check .`：通过
- `pytest`：71/71 passed（1 个既存失败因 `.env` API key 不属于本次改动）
- mypy：pdfplumber 相关 migration-specific 错误已解决

---

## 2026-07-01 — Code review 发现的 10 个问题修复（TDD）

**改动文件：** `app.py`, `core/config_store.py`, `core/settings.py`（净 diff 为空，见下）, `data/paper_page_config.json`, `modules/__init__.py`, `modules/mcq_parser.py`, `modules/page_segmenter.py`, `tests/test_page_segmenter.py`；新增 `tests/test_settings.py`, `tests/test_mcq_parser.py`, `tests/test_config_store.py`

### 功能说明

对 MCQ support 分支 + VL mark scheme 分支（本地已合并未 push）做了一次多角度 code review（8 个 finder agent 覆盖正确性、重复代码、简化、效率、设计深度、CLAUDE.md 规范等角度），产出 10 条确认发现，记录于 `dev/regular-review/2026-07-01-review.md`。随后按 TDD（先写失败测试、确认失败原因、再写最小修复代码）逐条修复，全部验证通过。

### 1. 正确性 Bug

- **`core/settings.py`**：`sender_email` 之前被加了 `example@gmail.com` 假默认值，绕过了 `MailConfig.try_load()` 判断"是否已配置邮箱"的机制。移除默认值恢复必填校验（此改动使该文件净 diff 归零，相当于撤销了一处此前存在于工作区的未提交回归）。
- **`modules/mcq_parser.py` + `app.py`**：MCQ 页面跳过配置（`paper_page_config.json`）此前完全不生效——查找逻辑基于文件名正则匹配，但实际传入的是 `tempfile.NamedTemporaryFile` 生成的随机路径，永远匹配不上。新增 `detect_student_answers(..., source_filename=...)` 参数，`app.py` 上传时把原始文件名存入 `st.session_state["mcq_qp_filename"]` 并传入，同时删除了从未被调用方使用的 `skip_pages` 参数。
- **`modules/page_segmenter.py`**：单字符边界（Q1–Q9）判定原先"先尝试 MAIN 解码、解码成功就直接判定为主题号"，但解码用的 char_map 是从页脚数字独立构建的，可能与 SUB 括号标记的字节巧合碰撞。改为先检查 SUB 括号配对，找不到再退回 MAIN 解码。
- **`modules/page_segmenter.py`**：页码识别的纵向阈值 `bbox[1] < 60` 侵入了正文起始区（`top_margin=45`），可能污染 char_map。收紧到 `< 50`，用两个测试分别钉住"仍需兼容页头 y≈46 的试卷"和"y≈55 的正文不应被误判为页码"。
- **`modules/mcq_parser.py` + `app.py`**：手动补录答案时 `if val in "ABCD"` 对空字符串成立（Python 子串语义），导致未填写的题目在渲染时就被标记为"已作答"。新增 `is_valid_manual_answer()` 用集合成员判断替代。

### 2. 冗余逻辑清理

- **`core/config_store.py`**：`PaperPageConfig` 原本是裸 `@dataclass`，JSON 解析失败时静默吞掉异常，与同文件里 `ConfigStore`（Pydantic + 抛错）的模式不一致。改为 `pydantic.BaseModel`，解析失败时抛 `ValueError`；`get_paper_page_config()` 新增 `config_path` 参数便于测试注入。
- **`modules/mcq_parser.py`**：`_extract_paper_id()` 和原 `detect_student_answers()` 内部各自维护一份文件名解析正则。提取出共用的 `_parse_paper_filename()`，两处复用。
- **`data/paper_page_config.json`**：9709/9231 等科目下多个 component 条目内容完全重复（约 24 处）。新增科目级 `_default` 字段作为该科目所有 component 的默认值，只在真正有差异时才单独列出（如各科目的 Paper 1 MCQ）。用参数化回归测试钉住了所有科目的实际解析结果，确认结构调整前后行为完全一致。
- **`app.py`**：删除了 MCQ 分支下从未被使用的 `start_page = 1` 死赋值。

### 验证结果

- `pytest`：70 passed（新增约 28 个测试用例），2 个与本次改动无关的既存失败保持不变
- `ruff check .`：43 个错误（改动前基线 44 个）
- `mypy .`：40 个错误（改动前基线 51 个）
- `ruff format --check .`：全仓库历史遗留的格式不合规，本次未处理（超出任务范围）

---

## 2026-06-29 — MCQ 试卷页面配置与 QP 检测修复（mcq-support 分支）

**改动文件：** `data/paper_page_config.json`（新建）, `core/config_store.py`, `core/__init__.py`, `modules/mcq_parser.py`, `modules/page_segmenter.py`

### 功能说明

新增 `data/paper_page_config.json`，按 subject ID + component 前缀（component 首位数字）配置每类试卷的 QP 跳过页数和 MS 内容起始页，替代原来在代码里硬编码的 `skip_pages={0,1}`。同时修复了 MCQ QP 检测在特殊情况下（如用户上传的临时试卷）完全失效的问题。

### 1. 新建 `data/paper_page_config.json`

- 覆盖 9700/9701/9702/9696（理科 MCQ）、9709/9231（数学）共 6 个 subject
- 每条按 component prefix 细分（如 9702 Paper 1x 和 Paper 2x 配置不同）：
  - Paper 1 MCQ：`qp_skip_pages: [0, 1]`（封面 + 数据页），`ms_start_page: 2`
  - Paper 2/3/4 结构题：`qp_skip_pages: [0]`，`ms_start_page: 6`
  - 数学各 paper：`qp_skip_pages: [0, 1]`，`ms_start_page: 6`
- 包含 `default` 回退条目（skip=[0], ms_start=6）

### 2. `core/config_store.py` — 新增页面配置 loader

- 新增 `PaperPageConfig` dataclass（`qp_skip_pages: set[int]`, `ms_start_page: int`）
- 新增 `get_paper_page_config(subject_id, component)` 函数：按 subject + component 首位字符查找 JSON，找不到则回退 default
- `core/__init__.py` 同步导出 `PaperPageConfig`、`get_paper_page_config`

### 3. `modules/mcq_parser.py` — 接入配置 + 修复 QP 检测失效

- `detect_student_answers()` 中 `skip_pages=None` 时，自动从 QP 文件名解析 subject/component，调用 `get_paper_page_config()` 获取实际 skip 集合，替代原硬编码 `{0, 1}`
- 将 `_build_page_batches()` 简化为纯按页批次（直接返回每个非跳过页的 index），**移除 `segment_questions` 依赖**：MCQ 每题独立成小方框，VL 一次读整页即可识别多题，无需题目级切割
- 修复了只有 3 页的临时卷子（封面+数据+1 题页）完全检测不到的问题

### 4. `modules/page_segmenter.py` — 修复 CID 字体单字符边界检测

- `_build_char_mapping()` 中页码检测 y 阈值从 `< 40` 放宽至 `< 60`，兼容页头在 y≈46 的试卷
- `_extract_boundaries()` MAIN 边界检测从仅处理 `len==2` 改为 `len in (1, 2)`：单位数题号（Q1–Q9）的 CID 编码为单字节，之前被误判为 sub-question 或完全忽略

---

## 2026-06-25 — MS 解析全面迁移至 VL 模型（all_vl 分支）

**改动文件：** `modules/ms_parser.py`, `modules/pdf_renderer.py`（新建）, `modules/grader.py`, `modules/__init__.py`, `app.py`, `tests/test_ms_parser.py`

### 功能说明

将 mark scheme 解析从 PyMuPDF table 提取全面迁移至 VL（Vision Language）模型。之前的流程需要两步（先 table 提取，再对图片页单独调 VL），现在统一为单步 VL 解析：所有 MS 页面渲染为图片 → 分 batch 发送至 Qwen-VL → 解析 JSON 返回结构化题目配置。

### 1. 新建共享渲染模块 `modules/pdf_renderer.py`

- 提取 `render_pdf_pages(doc, page_numbers, dpi)` 作为共享函数，MS parser 和 grader 都调用它
- 新增 `render_pages_from_path(pdf_path, start_page, dpi)` 便捷函数，直接从文件路径渲染
- `grader.py` 的 `render_pages()` 改为调用共享函数的 thin wrapper

### 2. 重写 `modules/ms_parser.py`

- **删除所有 table 解析代码**：`_parse_math_ms()`、`_parse_table_rows()`、`_group_questions()`、garbled font 解码（`decode_shifted_text`、`SHIFTED_CHAR_MAP` 等）、`detect_image_pages()`、`extract_ms_from_images()`
- **新增 `_call_vl()`**：封装 VL API 调用（OpenAI-compatible client）
- **新增 `_merge_questions()`**：合并跨 batch 边界的同一题目（append mark_scheme text + max(max_marks)）
- **新增 `_parse_all_vl()`**：核心函数，渲染所有页面 → 按 batch_size=2 分批 → 逐批调 VL → 合并结果
- **更新 `parse_mark_scheme()` 签名**：新增 `grader_config` 必填参数和 `on_progress` 回调
- 保留 `_extract_paper_info()` 用 PyMuPDF 文本提取 paper_id 和 total_marks（封面页始终可读，无需浪费 VL token）
- 增强 `_parse_image_ms_response()` 的 JSON 解析鲁棒性（fallback 到查找首尾 `{}` 括号）

### 3. 简化 `app.py` Mark tab UI

- 移除 `import re`（不再需要）、`detect_image_pages`、`extract_ms_from_images` 导入
- "Parse Mark Scheme" 按钮改为单步 VL 解析，带 `st.progress()` 显示 batch 进度
- 删除 "Extract from image pages" 按钮及其整个 UI block（~60 行）
- 清理相关 session state：`ms_image_pages`、`ms_pdf_path`

### 4. 测试更新

- 删除 `test_clean_text_removes_garbled`（函数已删除）
- 新增 5 个测试：`_merge_questions` 无重叠/有重叠、`_parse_image_ms_response` 正常/带 fence/空结果

---

## 2026-06-24 — Mark tab UI 改进 + 图片页 MS 提取 + bug 修复

**改动文件：** `app.py`, `modules/ms_parser.py`, `modules/page_segmenter.py`, `pyproject.toml`, `dev/update_history.md`

### 功能说明

对 Mark tab 做了三项 UI 改进，修复了两个 mark scheme 解析 bug，并新增了基于 VL 模型的图片页 mark scheme 提取功能。

### 1. Syllabus code 筛选器

- 选卷时先选 Syllabus code（如 `9231`、`9709`），再从该科目下的试卷列表中选择
- 试卷列表按 paper_id 升序排列
- Syllabus code 和 Select paper 两个 selectbox 并排显示（`st.columns([1, 3])`）

### 2. 题目删除按钮

- 每个题目的页码输入框右侧新增 `✕` 按钮，可手动移除异常题目
- 删除状态存入 `st.session_state["deleted_questions"]`，重新 parse mark scheme 时自动重置

### 3. 分数修改功能

- 批改结果 expander **右侧**（外部）新增 `Adjust` number_input，可手动覆盖 AI 给分
- 布局使用 `st.columns([5, 1])` 将 expander 和 adjust 并排
- 修改后实时更新 expander 标题、顶部 metrics、最终提交分数

### 4. Bug 修复

| Bug | 根因 | 修复方式 |
|-----|------|----------|
| Q1、Q6 缺失 | MS PDF 中这些页面是纯嵌入 PNG，`find_tables()` 无法提取 | 新增 VL 模型提取（见下） |
| Q2a/Q2c 页面范围多出 P5/P6 | `_build_regions` 跨页时生成了极小的尾部 clip（<20pt，只是 header/margin） | `page_segmenter.py` 加 `_MIN_CLIP_HEIGHT = 50` 阈值，跳过过小 clip |

### 5. VL 图片页 Mark Scheme 提取（核心新功能）

- **`ms_parser.py:detect_image_pages()`**：自动检测 MS PDF 中无 table、无 text、有 image 的纯图片页
- **`ms_parser.py:extract_ms_from_images()`**：将图片页渲染为 PNG（200 dpi），通过 OpenAI-compatible API 发送给 Qwen-VL，提取题号、分值、marking points，返回 `dict[str, QuestionConfig]`
- **`ms_parser.py:_parse_image_ms_response()`**：解析 VL 响应 JSON，通过 `normalize_question_id()` 标准化题号
- **Prompt 优化**：明确要求 VL 模型 transcribe 实际数学表达式（行列式展开、代入过程等），禁止输出 "method..."、"criterion..." 等泛泛描述
- **UI 集成**：parse 后自动检测图片页并显示 warning，用户点击按钮即可通过 AI 提取并合并到题目列表

### 6. 其他

- `pyproject.toml`：移除了与 PyMuPDF 冲突的 `fitz>=0.0.1.dev2` 依赖
- worktree `image-ms-detection` 分支已合并到 main

---

## 2026-06-21 — 试卷题目自动分割与题号解码

**改动文件：** `modules/page_segmenter.py`, `tests/test_page_segmenter.py`

### 功能说明

为 Mark tab 实现了自动检测 CIE 试卷 PDF 中的题目/子题边界功能。通过分析 PDF 文本 span 坐标自动识别题号位置，替代手动输入页码。本次 session 重点解决了**题号偏移问题**：当 mark scheme 与试卷的子题数量不一致时，后续所有题目位置发生错位。

### 字符映射反推（核心新功能）

- **`_build_char_mapping(doc)`**：扫描每页顶部的页码 span，利用"第 N 页的页码应该是 N+1"的已知信息，反推出 garbled 字体（AllAndNone）的 byte→digit 映射表
- **`_decode_question_num(text, mapping)`**：用映射表将 MAIN boundary 的乱码字节解码为实际题号数字（1, 2, 3, ...）
- **`_is_ascii_digit_str()`**：替代 Python 内置 `str.isdigit()`，避免 Unicode 上标数字（如 `³` = `chr(0xb3)`）的误判

### 分组匹配重写

- **`_group_boundaries()`**：以 MAIN boundary 为锚点，将后续 SUB 归入同一组
- **`_group_qids()`**：按题号前缀（"4a","4b" → 第 4 组）将 mark scheme 的 question_id 分组
- **`_match_boundaries()` 重写**：改为按**解码出的题号数字**查找对应 boundary 组（`b_by_num` dict），而非按位置顺序。无映射时自动降级为位置匹配
- **`_Boundary` 模型**：新增 `question_num: int | None` 字段

### 多格式兼容（前次 session 遗留 + 本次修复）

- 支持 garbled 编码（AllAndNone 字体，自定义 CIDFont）和 readable 编码（TimesNewRoman/Arial）两种 CIE PDF 格式
- `_detect_bracket_pair()` 自动检测子题括号编码（不同卷子使用不同 byte pair）
- 已验证通过的卷子：`9231_s25_qp_11`, `9231_s25_qp_13`, `9231_s25_qp_44`, `9231_s24_qp_13`

### 注意事项

- 字符映射依赖 PDF 页码与题号使用同一套字体编码（所有已测试的 CIE 卷子均满足此条件）
- 合成测试 PDF 无页码 span → `_build_char_mapping` 返回 `None` → 自动降级为位置匹配
- 23 个单元测试全部通过

---

## 2026-06-11 — Analytics 每 paper type 标题与统计信息合并显示

**改动文件：** `modules/visualizer.py`, `tests/test_visualizer_metrics.py`

### 功能说明

将 Analytics tab 中每个 paper type 标签页的统计指标（Attempts、Average、Best）从独立行合并进标题行，并移除了 "— Trend" 后缀。指标以 HTML `<small>` 灰色字体内联展示，与上方 syllabus 级别的 `st.metric()` 卡片形成清晰的视觉层级。

- **`_render_trend_chart`**：移除 "— Trend" 后缀；`show_metrics=True` 时将 Attempts / Average / Best 内联渲染到标题同一行（`st.markdown` + `unsafe_allow_html`），`show_metrics=False` 时仅输出纯标题
- **`_render_paper_type_metrics`**：整个方法删除，逻辑已内联进 `_render_trend_chart`
- **`test_visualizer_metrics.py`**：更新测试，从测试已删除的 `_render_paper_type_metrics` 改为测试 `_render_trend_chart(show_metrics=True)` 的合并输出，并断言 "Trend" 字样不出现在标题中

---

## 2026-06-01 — Score 输入框增加 session_state 草稿缓存

**改动文件：** `app.py`

### 功能说明

在 `submit_score_dialog` 的两个 `number_input` 上加入了 per-paper 的 `key`（`draft_raw_{paper_id}` / `draft_total_{paper_id}`），利用 Streamlit `session_state` 的持久化机制缓存未提交的输入值。用户输入分数后关闭对话框再重新打开，数字不会丢失，直到成功提交后 paper 从 Pending 列表移走，draft key 自然失效。

- **`submit_score_dialog`**：`number_input` 加 `key=f"draft_raw_{selected_id}"` 和 `key=f"draft_total_{selected_id}"`，其余逻辑不变

---

## 2026-05-23 — 合并 manage-refactor 分支，修复 Streamlit 弃用警告

**改动文件：** `app.py`, `core/settings.py`, `data/syllabus_config.json`

### 功能说明

将 `feature/manage-refactor` 分支合并回 `main`，包含 syllabus 配置更新、UI 默认值调整和 SMTP 字段可选化，并修复了 Streamlit 的 `use_container_width` 弃用警告。合并后删除了本地和远端的 feature 分支。

- **syllabus_config**：新增 9231、9618 的 paper type 配置，移除已废弃的 9608 条目
- **Hide completed 默认值**：List 视图的"Hide completed"toggle 默认改为 `True`，减少已完成卷子的干扰
- **SMTP 字段可选化**：`MailConfig` 中 `smtp_server` 和 `sender_app_password` 改为 `str | None` / `SecretStr | None`，未配置邮件的用户启动时不再报错
- **Streamlit 弃用修复**：`app.py` 中两处 `use_container_width=True` 替换为 `width="stretch"`（涉及 `st.button` 和 `st.dataframe`）

---
