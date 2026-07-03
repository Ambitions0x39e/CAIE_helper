# Dev Logs

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
