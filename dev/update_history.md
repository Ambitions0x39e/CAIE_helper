# Dev Logs

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
