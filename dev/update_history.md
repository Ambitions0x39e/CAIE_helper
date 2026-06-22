# Dev Logs

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
