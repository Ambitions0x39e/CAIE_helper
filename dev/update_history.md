# Dev Logs

---

## 2026-07-27 — 设置页改版落地：行式布局 + 新页取代旧页

**改动文件：** `app_flet/tabs/settings.py`（由 `settings_dev.py` 顶替，后者删除）, `app_flet/main.py`（改动已全部撤回）, `.claude/launch.json`, `dev/version_log.md`

### 功能说明

承接同日上一条：`settings_dev.py` 的报错修完后，用户觉得排版「总是差强人意」，给了一张 Claude 设置页截图作为目标 —— **左侧标签、右侧输入，行间细分隔线**。按这个样式重做了整页布局，随后用户确认效果可用，遂用新页面**替换掉老的 `settings.py`**，`settings_dev.py` 与临时的双标签接线一并删除。

### 行式布局：四个原语统一整页

**改动文件：** `app_flet/tabs/settings.py`

抽出四个排版原语，三个子页面 + 主菜单全部改用它们，避免每处各写一套 Row/Column：

| 原语 | 作用 |
|---|---|
| `_section(title)` | 分组标题（对应参考设计里的 Profile / Preferences） |
| `_row(label, control, description=, narrow=)` | 左标签（可带灰色小字说明）+ 右控件，垂直居中 |
| `_divided(*rows)` | 行间插发丝分隔线，**首尾不插** |
| `_actions(*controls)` | 底部操作条，右对齐到控件列 |

- **输入框去掉浮动 label**：行左侧那一列就是标签，框内再写一遍等于同一件事说两遍。`_tf()` 签名改为 `_tf(value, *, password, number, hint)`，`hint_text` 改放示例值（`smtp.gmail.com` / `465` / `sk-…` / `qwen3-vl-flash`），宽度固定 320 使右侧对齐成一条竖线，配 8px 圆角、灰色描边、聚焦转蓝。
- **分组重排**：邮件子页拆成「邮件服务器」（SMTP 四项）+「GoodNotes」（导入地址）；批改子页为「模型凭证」。给 App Password、Import Email、API Key、Model 补了灰色说明小字（如「邮箱服务商生成的应用专用密码，非登录密码」「保存在本地 ~/.cie_helper/.env，不会上传」）。
- **主菜单同语言**：`_menu_row` 去掉白色卡片底色与 `bgcolor`，改为扁平行 + 分隔线列表，图标缩到 20px，与设置行的节奏一致。
- **关于页对齐修复**：原来整列 `horizontal_alignment=CENTER`，会让「反馈」行按内容宽度缩成居中的一小条。改为 `STRETCH`，图标/应用名/版本号各自靠 `Alignment.CENTER` 与 `text_align` 居中，行则正常撑满。

### 窄屏断点（未被要求，但会踩）

**改动文件：** `app_flet/tabs/settings.py`

320px 固定宽输入框 + 左侧标签，在 375px 宽的手机上左右 24px 内边距吃掉后只剩 ~7px 留给标签，会挤爆 —— 而这个 app 是要打 iOS 的。

- 加 `_NARROW_WIDTH = 560` 与 `_is_narrow(page)`；窗口窄于该值时 `_row` 改为**上下堆叠**（标签在上、输入框 `width=None` 占满整行），宽屏才用左右分栏。判定在 build 时读 `page.width`，与 `mark.py` 的 `_responsive_grid` 同一套做法。
- 构造测试两种模式实测：`narrow=False → Row / width=320`，`narrow=True → Column / width=None`。

### 新页面取代旧页面

**改动文件：** `app_flet/tabs/settings.py`, `app_flet/main.py`

- **先做功能对账再删**：旧 `settings.py` 的 8 个字段（SMTP 五项 + Grader 三项）新页面全部覆盖，另多出「关于」页；唯一行为差异是旧版一个「保存」同时写两套凭证，新版各子页各存各的 —— 属改版意图，非遗漏。确认无回退后才替换。
- `settings_dev.py` 内容顶替 `settings.py`，前者删除；模块 docstring 重写（去掉「your main.py」这类改写期的自述口吻，补上行式布局与窄屏断点的说明）。
- `main.py` 的临时接线**全部撤回**：删掉别名导入 `build_settings_tab_dev`、`idx == 5` 分支、以及「设置(Dev)」导航项。撤回后 `git status` 里 `main.py` 已不再显示为修改，与 HEAD 完全一致。
- 全局 grep 确认除 `main.py` 外无其他引用，删除安全。

### 其他

- `.claude/launch.json` 的 flet 启动参数改为 `flet run --web --port 8550 main.py`（原为 `flet run app_flet`），以便用浏览器预览而非弹出桌面窗口。
- `dev/version_log.md` 的 v1.1.2 条目重写：原先按「新旧设置页并存」描述的两条（双标签互相覆盖、开发版顶栏失效）在老页面删除后已不成立，改为面向发布的「设置页改版」「关于页」两条新增 + 排版与保存行为两条行为变更。

### 注意事项

- **UI 效果由用户确认，不是我验证的**：Flet 走 Flutter canvas 渲染，读 DOM 拿不到任何布局信息；而截图工具报「Browser pane is not displayed」—— 预览面板未展开时页面不合成帧，截不到图。本次我这边的验证只到「类型正确 + 原语构造行为正确 + 应用无异常启动」，视觉效果是用户自己跑起来看过说没问题。后续若要我参与调间距/字号，需要先把 Browser 面板打开。
- **`settings_dev.py` 已不存在**：同日上一条日志里提到的该文件是这次改版的中间产物，内容已并入 `settings.py`，勿再按旧路径查找。
- 预览服务已停止；本次未打包（用户要求开发完再打）。

---

## 2026-07-27 — 罗马小题裁剪错位 + 题干归位 + 设置页重写修错（v1.1.1 / v1.1.2）

**改动文件：** `modules/page_segmenter.py`, `tests/test_page_segmenter.py`, `app_flet/tabs/settings_dev.py`, `app_flet/main.py`, `release.ps1`（gitignored）, `dev/version_log.md`, `pyproject.toml`, `packaging/windows/cie-helper.iss`, `uv.lock`

### 功能说明

承接同日上一条：9701 页码识别修好后，用户实跑批改发现**分数仍然全错** —— 截图显示 Q1(a)(ii) 被按 (i) 的答案评分、(iii) 被按 (ii) 的答案评分，是裁剪区整体前移一位。定位并修复了这个错位，随后又修了同一族的字母题干归位问题，以及用户并行在写的设置页重写（`settings_dev.py`）的报错。期间还修了 `release.ps1` 的一处守卫缺陷。全程未打包（用户要求开发完再打）。

### 罗马小题裁剪整体错位（v1.1.1，核心）

**改动文件：** `modules/page_segmenter.py`, `tests/test_page_segmenter.py`

`_accepted_garbled_subsubs` 学习罗马字形集时**只统计单字形 interior**（`len(interior)==1`），也就是只从裸的 `(i)` 里学，因此字形表永远只有 `{i}`：

| 标记 | interior 码点 | 结果 |
|---|---|---|
| `(i)` `(ii)` `(iii)` | `(45,)` `(45,45)` `(45,45,45)` | ✅ 纯 `i` 重复 |
| `(iv)` | `(45, 32)` | ❌ 含 `v`(32)，从未被学到 → 判为噪声丢弃 |

全卷 4 处 `(iv)` 标记被丢。丢标记本身只少一个边界，真正把范围搞乱的是下一步：`_match_boundaries` 里 `len(subsub_bs) == len(romans) - 1` 分支**假定缺的是第一个**（因为首个罗马常与字母标记同行），于是在头部补上 `sub_b`，把后面每个罗马都挤后一位 —— `(a)→Q1(a)(i)`、`(i)→Q1(a)(ii)`、`(ii)→Q1(a)(iii)`。这正是截图里的现象。`(iv)` 反而蒙对，是因为它的范围一路延伸到 `(b)(i)`，把 (iii)(iv) 的作答全裹进去了。

- **修法**：字形表改为「裸单字形（结构上就是 `i`）∪ 全局出现 ≥2 次的字形」，上限 3 个。上限有依据 —— CIE 用到的罗马数字只由 `i`/`v`/`x` 三个字形拼成。噪声字形不重复，仍被拒。
- **实测支撑**：各卷 interior 字母表极小且零噪声（9701 仅 `{45, 32}`，9702 仅 `{38}`），说明「括号对 + 列位置 + 长度」三重约束已把正文滤干净，放宽字形学习是安全的。
- **验证**：9701 的 subsub 边界 35 → 39（正好补回 4 个 `(iv)`），Q1(a) 四个裁剪区起点精确落在各自标记（109.8 / 207.6 / 293.2 / 378.8），逐个渲染出图肉眼核对内容各归各位。

### 字母层题干归位（v1.1.2）

**改动文件：** `modules/page_segmenter.py`, `tests/test_page_segmenter.py`

修完错位后发现同族的次级问题：挂在字母层的题干（如「(b) The shorthand electronic configuration of chromium is [Ar] 3d⁵4s¹」）会落进**上一小题**的裁剪区，轮到 `(b)(i)` 时反而看不到 —— 而这句正是答「补全完整电子排布」的前提。9701 上影响 4 处（Q1(b)(i)、Q2(d)(i)、Q3(c)(i)、Q3(e)(i)）。

- **修法**：`_match_boundaries` 中每个字母的首个罗马（`idx == 0`）改为锚定到字母自己的 SUB 边界，而不是它的罗马标记。与 `389048f`（v0.2.0）修大题题干是同一条规则，只是下沉一层。prepend 分支触发时 `positions[0]` 本就是 `sub_b`，行为自洽。
- **验证**：Q1(a)(iv) 终点 501.1 → 476.6（不再多裹 (b) 的题干），Q1(b)(i) 起点 501.1 → 476.6（拿回题干），两图渲染确认。
- **注意**：这会让**所有卷子**的裁剪范围都略有变化，是本次 blast radius 最大的改动；5 份卷子识别率实测全部不变。

### 设置页重写（settings_dev.py）报错修复

**改动文件：** `app_flet/tabs/settings_dev.py`, `app_flet/main.py`

用户并行在写新版设置页，6 个 mypy 报错里**两个是真 bug 而非类型问题**：

- **`ft.View` 参数位置错误**：flet 0.85.3 的签名是 `View(controls, route, appbar, ...)`。原代码把 route 当第一个位置参数传，又把 `ft.AppBar` 塞进 controls 列表 —— AppBar 会被当普通 body 控件渲染，**根本不成为页面顶栏**，返回按钮和 iOS 滑动返回都失效。改为 `route=` / `appbar=` / `controls=` 具名传参。
- **`ft.padding.symmetric` 不存在**：`ft.padding` 模块只导出 `Padding`/`PaddingValue`/`Number`/`value`，`symmetric` 是 `ft.Padding` 类上的方法。改为 `ft.Padding.symmetric`。
- **类型补齐**：`icon` 由 `str` 改为 `ft.IconData`；`on_click` 补标注为 `Callable[[ft.Event[ft.Container]], None]`，两个 handler 签名同步对齐 —— 这样**不需要 `# type: ignore`**（mark.py / settings.py 里都是靠 ignore 压住的，既然目标是规范化就做到类型正确）。
- **图标恢复**：`_menu_row` 里 `ft.Icon(icon, ...)` 原被注释掉，导致 `icon` 参数完全没用上，而两个调用点都传了真实图标 —— 判断是被那个类型报错逼注释的，类型修好后取消注释。
- **`main.py` 同名导入覆盖**（ruff F811）：`build_settings_tab` 被 `settings` 和 `settings_dev` 两次导入，后者覆盖前者，导致「设置」和 dev 两个标签**都进 dev 版、原设置页无法访问**（SIM114 报的两分支相同正是症状）。给 dev 版加 `as build_settings_tab_dev` 别名，`idx == 5` 改用它；顺带修了 E501 超长行（标签改为「设置(Dev)」）。
- **运行时冒烟**：直接构造 `ft.View(route=..., appbar=..., controls=[...])`、`_menu_row(...)`、`ft.Padding.symmetric(...)` 确认三处 API 真的可用，不只是类型过关。

### release.ps1：同版本重跑打包被守卫拦死

**改动文件：** `release.ps1`（gitignored）

用户跑 `.\release.ps1 1.1.0 -Build` 报「New version equals current version」。原因是之前已单独跑过一次不带 `-Build` 的 bump，版本号早已是 1.1.0，而那道相等检查位于**参数校验段**、在第 4 步打包之前就 `throw` —— 脚本第 3 步本身能优雅处理「changelog stub 已存在」，说明设计上本就预期可重复运行，只是被守卫堵死。

- **修法**：版本相同且带 `-Build` 时视为「已 bump，只需打包」，正常往下走并打印 `Re-packaging X (already bumped)`；版本相同但不带 `-Build` 仍报错（那种情况确实无事可做，更可能是打错版本号），错误信息补上 `- pass -Build to re-package it`。
- **编码注意**：该 `.ps1` 含 13 处中文且带 UTF-8 BOM，编辑后专门校验了 BOM（`efbbbf`）与中文未被破坏 —— 丢 BOM 会让 PS 5.1 按 GBK 解码乱码（见 memory `reference_release_script`）。

### 版本与发布记录

**改动文件：** `dev/version_log.md`, `pyproject.toml`, `packaging/windows/cie-helper.iss`, `uv.lock`

- 补全了 v1.1.0 的 changelog（原为 TODO stub），随后按用户要求把改动拆成两版：**v1.1.1** = 罗马小题裁剪错位；**v1.1.2** = 题干归位 + 设置页两处可用性修复 + 类型/图标。
- 版本号经 `release.ps1` 依次 bump 到 1.1.2（`pyproject.toml` + `cie-helper.iss`），`uv.lock` 随之同步。
- **未打包**：用户明确要求开发完再打，`dist/` 下无任何 1.1.x 产物。三条记录的「对应 commit」均待提交后补。
- 清理了排查期间产生的 4 个 `scratch_*` 临时文件（它们不在 `[tool.flet.app].exclude` 里，否则会被打进 `app.zip`）。

### 注意事项

- **`test_paper_type.py::test_grader_config_try_load_returns_none_when_missing` 仍失败，与本次改动无关**：该测试断言无配置时 `try_load()` 返回 `None`，但实际读到了 `~/.cie_helper/.env` 里的真实凭证。stash 掉全部改动后同样失败，属未隔离环境的既有问题，待单独处理。
- **`(iv)` 之后仍可能欠检测**：若某卷只出现一次 `(iv)` 且无其他含 `v` 的罗马，`v` 字形因不满足「≥2 次」仍会被拒，进而触发那条 prepend 分支造成错位。该分支**至今没有测试覆盖**，其「缺的一定是第一个」假设无法从边界数量本身证伪。若再遇到错位，根治方向是让 `_extract_boundaries` 直接检出与字母标记同行的内联罗马，从源头消除数量不匹配，而不是靠推断补位。
- **验证口径**：全程用 `~/.cie_helper/` 里的真实 9701 卷子实跑，关键裁剪区渲染成 PNG 逐张肉眼核对 —— 单看匹配率（42/42）无法发现错位，因为错位时匹配率同样是满的。

---

## 2026-07-27 — Chemistry 9701 页码识别失效 + 封面元数据提取修复

**改动文件：** `modules/page_segmenter.py`, `modules/ms_parser.py`, `tests/test_page_segmenter.py`, `tests/test_ms_parser.py`

### 功能说明

用户反馈演示时用 chemistry 9701 卷子批改出问题。用本地已下载的 9701_w25 MS + QP 实跑复现，确认是**两个独立于 `70c9299`（max_marks N/A 崩溃修复）的新缺陷**：Step 2 页码自动识别 42 题只中 4 题，以及 MS 封面 `paper_id`/`total_marks` 提取全空。两个都已修复，并顺带处理了会挡住修复效果的陈旧缓存。

### 问题 1：页码自动识别几乎全灭（严重）

**改动文件：** `modules/page_segmenter.py`, `tests/test_page_segmenter.py`

9701 的 42 道小题只自动识别出 4 道（每道大题的第一个小题），其余 38 道要手工填页码，批改流程实际废掉。

根因在 S3（`5522d5d`）引入的那道括号对守卫：`_detect_bracket_pair` 能正确反推出该卷字体的 `(` / `)` 编码，但守卫要求两个码点都 ≥128 才信任，依据是「乱码字体的括号字形总是非 ASCII 高位字节」。**这个假设错了** —— 自定义编码完全可以把括号放在低位字节，9701 就是 `(113, 114)`。正确的编码对被丢弃后 `bracket_pair` 变 `None`，`_accepted_garbled_subs` / `_accepted_garbled_subsubs` 整条乱码识别链路停摆，只剩大题编号能匹配。数学、物理卷凑巧满足 ≥128，所以问题只在化学卷暴露。

- **换判据**：新增 `_is_cid_encoded(pages, skip)`，用「这份文档本身是否 CID 编码」直接回答守卫真正想问的问题（该走乱码链路还是可读链路），取代与之无关的码点大小。实测两类卷分离极干净、中间无模糊地带：9701 92.8% / 9702 72.6–100% / 9231 100%（乱码）对 9700 2.3% / 9618 0.2% / 9231_s23 0%（可读），阈值取 0.5。
- **守卫不能简单删掉**：单纯移除会让可读卷 9700 从 27/27 掉到 22/27（噪声对 `(70,103)` = `'F','g'` 注入幻影 SUB）。这次是**换判据，不是去掉保护**。
- **按跳过后的页面统计**：可读封面页在前、乱码正文在后时不能被封面拉低比例，故只统计分割器实际扫描的页。
- **修正 3 个既有测试 fixture**：`_sub_label` 用高位可读字符（`0xA8`/`0xAA`）假装乱码卷 —— 正是导致本 bug 的错误心智模型，换判据后必然失效。两个 `_extract_boundaries` 测试改用直接构造的**真 CID 编码** `_SegPage`（新增 `_cid` / `_cid_sub_label` / `_page_of` 辅助，括号对刻意取低位的 `(113,114)`）；全流程测试因 FPDF 造不出 CID 编码 PDF，改走可读路径（`_readable_sub_label`）。
- **新增测试**：`TestIsCidEncoded`（乱码/可读/封面不干扰/空文档）、`TestBracketPairTrust`（低位括号对在 CID 卷被接受、可读卷噪声对仍被拒绝）。

### 问题 2：MS 封面元数据提取失败

**改动文件：** `modules/ms_parser.py`, `tests/test_ms_parser.py`

化学卷封面是逐字符断行、且部分字形丢失（9701 全篇 `i` 缺失，`Maximum Mark: 60` 抽出来是一列字符拼成 `MaxmumMark:60`）的文本，`_extract_paper_info` 的正则完全匹配不上，结果 `paper_id=""`、`total_marks=0`，UI 显示成「已解析: (42 题), 0 总分」。

- **抽出纯函数** `_paper_info_from_text(text)`，`_extract_paper_info` 变薄包装，逻辑可单测。
- **原文优先、折叠兜底**：每个字段先按原文匹配，匹配不到才回退到折叠全部空白后的文本。`Maximum` 的正则放宽为 `Max\w{0,6}\s*Mark\s*:?\s*(\d+)` 以吸收丢失字形。**中途返工**：最初无条件折叠空白，结果把 `Maximum Mark: 75` 和下一行的科目代码粘成 `759618`，打坏了 9618/9702 全线满分值；改成原文优先后可读封面根本走不到兜底分支，零回退。
- **实测**：本地 68 份 MS 全部提取正确，9701 现为 `9701/23/O/N/25` / 60 分。

### 顺带：缓存陈旧值就地修复

**改动文件：** `modules/ms_parser.py`, `tests/test_ms_parser.py`

MS 解析结果按「文件名 + 起始页」缓存，与解析器版本无关，修好后本地旧缓存仍带着空 `paper_id`。原计划给缓存键加版本号，但那会强制所有已缓存卷子重跑 VL 解析（真实 API 花费），只为修两个显示字段 —— 不划算。

- 改为新增 `_repair_cover_info`：缓存命中时，若 `paper_id`/`total_marks` 为空则从封面重新提取并回填、写回缓存。这两个字段来自本地文本提取、不花钱，且**只填空值不覆盖已有数据**，题目内容原样保留。
- 缓存不可写时用 `contextlib.suppress` 吞掉，不让写缓存失败连累解析本身。
- MCQ 路径的 `paper_id` 来自文件名，不受影响，故只改 MATH 路径。

### 验证结果

| 卷子 | 改前 | 改后 |
|---|---|---|
| 9701 chemistry | 4/42 | **42/42** |
| 9700 chemistry | 27/27 | 27/27 |
| 9618 | 26/26 | 26/26 |
| 9231_s25 | 21/21 | 21/21 |
| 9702_s25 | 30/30 | 30/30 |

- `uv run pytest`：122 通过（新增 9 个测试）。
- `uv run ruff check`：源码干净（`in_dev/t1.py` 的 import 排序问题为既有）。
- `uv run mypy modules core app_flet`：无问题；剩余 13 个 test 目录报错为既有辅助函数缺类型参数，数量与改动前一致。
- 端到端：沙箱缓存目录里跑完整流程（缓存命中修复 → 分段），42 题全部产出有效 clip。

### 注意事项

- **既有测试失败（非本次引入）**：`tests/test_paper_type.py::test_grader_config_try_load_returns_none_when_missing` 断言无配置时 `try_load()` 返回 `None`，但实际读到了 `~/.cie_helper/.env` 里的真实凭证。stash 掉全部改动后同样失败 —— 该测试没有隔离环境变量，属既有问题，待单独处理。
- **`mypy .` 无法直接运行**：仓库里的 `build/` 目录（flet build 产物）含 `python/Lib/typing.py`，会 shadow 标准库。跑 `uv run mypy modules core app_flet` 指定包名即可。
- **打包后 UI 手测未做**：需 GUI + API 凭证，本次只验证到库层面端到端。

---

## 2026-07-21 — 批改卡死根治（进程内渲染）+ 解析进度条位置修复

**改动文件：** `modules/renderer.py`, `modules/grader.py`, `app_flet/main.py`, `app_flet/tabs/mark.py`, `app_flet/state.py`, `tests/test_renderer.py`, `pyproject.toml`, `uv.lock`

### 功能说明

用户在 9700 生物卷（35.6MB 扫描件）上批改 Q4 全部小题时「卡住、拿不到结果、也无报错」。系统化调试定位：批改逻辑/API/clip 数据全部无辜（headless 复现 27 秒跑通全 Q4），故障在**原生 pdfrx 渲染器经 Python↔Dart RPC 传大 payload 时挂起**——扫描件单页子 PDF 就 4.5MB，`future.result()` 又无超时，于是永久死锁。根治办法是绕开 RPC：桌面改用进程内 pypdfium2 渲染。

- **进程内渲染（根治）**：`modules/renderer.py` 新增 `_try_local_render`，用 pypdfium2 在进程内栅格化 + 裁剪 clip 区域，完全不过 RPC，那份损坏 xref 的 35MB 扫描件也 0.8 秒渲完全部 Q4。`render_regions` 优先走本地路径，pypdfium2 缺失时（iOS）回退原生 pdfrx。同为 PDFium 引擎，输出一致。
- **依赖**：`pyproject.toml` 加 `pypdfium2` + `pillow`，带 `sys_platform != 'ios'` marker——桌面打包含之、`flet build ipa` 排除之，不破坏 iOS 构建。更新了 flet 版本锁定注释里「大 PDF RPC 靠 pypdf 预抽页解决」的过时说法。
- **渲染超时**（防御纵深）：`render_regions` 的原生回退路径给 `future.result()` 加 120s 超时，超时抛中文错误（含子 PDF 大小）而非无限挂起。
- **API 超时**：`modules/grader.py` 的 OpenAI 客户端加超时（普通 120s / 思考模式 300s）+ `max_retries=1`，取代默认约 10 分钟。
- **持久错误横幅**：`app_flet/tabs/mark.py` 批改失败改为在 Step 3 顶部持久红色横幅显示（原来只有几秒自动消失的 snackbar，长时批改容易错过），并 `_log.exception` 记完整堆栈；`AppState` 加 `grading_error` 字段。
- **作用域日志**：`app_flet/main.py` 加 `_setup_logging`，只开 `cie_helper` 命名空间到 INFO，控制台能看到渲染 payload 大小/计时，方便调试卡顿。
- **测试**：`tests/test_renderer.py` 加进程内渲染 happy-path（每 clip 出一张 PNG）与原生回退超时用例（monkeypatch 模拟 iOS 无 pypdfium2）。

### 解析进度条位置修复

**改动文件：** `app_flet/tabs/mark.py`

在最后一步（选题/批改）重新选新 MS 解析时，加载条原本 append 在旧选题界面**下方**、埋在页面底部看不见。改为：解析期间用 `parsing_ref` 标志让 `_rebuild` 收起「已解析预览 + Step 2/3/4 选题」整块，只显示 Step 1 选择器 + 进度条；解析结束（成功或失败）在 `finally` 复位标志并重建。

---

## 2026-07-21 — 分割器乱码卷子题检测修复 + v0.3.0 打包/发布/落地页

**改动文件：** `modules/page_segmenter.py`, `tests/test_page_segmenter.py`, `app_flet/tabs/mark.py`, `app_flet/state.py`, `app_flet/tabs/analytics.py`, `packaging/windows/cie-helper.iss`, `packaging/macos/build-pkg.sh`（新增）, `pyproject.toml`, `README.md`, `.gitattributes`（新增）, `.gitignore`, `site/index.html`（新增）, `release.ps1`（新增，gitignored）

### 分割器：CID 乱码卷子题/子子题检测修复（核心）

**改动文件：** `modules/page_segmenter.py`, `tests/test_page_segmenter.py`, `app_flet/tabs/mark.py`, `app_flet/state.py`

用户在 9702 物理 Paper 2 上「页码大量缺失、压根得不到批改结果」。根因是分割器对 CID 乱码卷的子题检测严重漏检，且 UI 假报成功掩盖了失败。分五步修复（S1–S5），每步独立提交、真实卷卡关验证，数学卷零回退。

- **S1 诚实层**（`3529f11`）：`validate_regions` 不再把无 clips 的 region 算作匹配；`_build_regions` 丢弃退化 region 并记 `reasons`（degenerate / out_of_order）；新增 `SegmentationReport` + `segment_questions_report()`，`segment_questions` 变薄包装保持向后兼容。Mark 标签页据实显示识别数、点名未识别题号、未匹配题的页码框标橙色「待填」。9702 从假报 30/30 变为如实 13/30。
- **S2 假 MAIN 清除**（`e36cdd6`）：`_reconcile_main_numbers` 丢弃无法解码题号的幽灵 MAIN 边界（它会偷走后续 SUB）；边界排序键加入 `_KIND_RANK`（MAIN<SUB<SUBSUB）使同行 `1 (a) (i)` 正确父子化。9702 → 15/30。
- **S3 乱码 SUB 检测**（`5522d5d`）：`_accepted_garbled_subs` 改由 sub_q_x 列驱动，脱离左边距依赖——原逻辑只有与主题号同行的 `(a)` 能被检出，`(b)/(c)` 左边距为空永远漏掉。判据：括号形状用卷子自身编码 + 非正文占据左侧 + 字母字形跨文档复现≥2 次。守卫：括号对两码点须≥128（非 ASCII）才信任，避免可读卷噪声对注入幻影 SUB。9702 → 18/30。
- **S5 乱码罗马子子题检测**（`34306cf`）：`_accepted_garbled_subsubs` 检测 `(i)/(ii)/(iii)`——CID 罗马数字是单字形重复（实测 38='i'）。闭括号按值查找（尾部粘连空格 glyph），内部码点须全属罗马字形集。不解码数值，`_match_boundaries` 按位置配对。加 overdetect 护栏：检出数超过评分标准罗马数时回退到 SUB 锚点，防止错位裁剪。**9702 → 30/30 全匹配**，clip 全部有效、页码单调、无薄裁剪。
- **验证结果**：9702 物理 13→30/30；9231 数学 21/21、9700 生物 27/27 全程零回退。新增 12 个纯数据测试覆盖接受规则与护栏。

### v0.3.0 功能：单请求批改 + 弹性统计布局

**改动文件：** `app_flet/tabs/mark.py`, `app_flet/state.py`, `app_flet/tabs/analytics.py`（commit `f6522d6`）

- **批改请求互斥**：`AppState.grading_in_progress` 锁，数学「开始批改」与 MCQ「检测答案」共用；进行中按钮置灰、重复点击提示，`finally` 复位不卡死。
- **统计页弹性布局**：窗口宽 ≥950px 时表格在左、折线图占满右侧剩余宽度；更窄时折线图全宽在上、表格在下。按实时窗口宽度判定。

### macOS .pkg 打包 + 发布基建

**改动文件：** `packaging/macos/build-pkg.sh`（新增）, `pyproject.toml`, `README.md`, `.gitattributes`（新增）, `release.ps1`（新增）

- **macOS 安装器**：`build-pkg.sh` 用 `pkgbuild` 包装 `flet build macos` 产物，版本号从 pyproject 单一来源读取、自动探测 .app 名。选 .pkg 而非 .dmg：Installer 装入的文件不带 quarantine 标记，安装后可直接打开、免 Gatekeeper 绕过。
- **版本同步**：pyproject 版本升到 0.3.0（与 .iss 对齐）。
- **`.gitattributes`**：强制 `*.sh`/`*.command` 用 LF，防 CRLF 破坏 macOS/Linux 上的 bash。
- **`release.ps1`**（本地 gitignored）：一条命令改 pyproject + .iss + changelog 三处版本号、`-Build` 直接跑 flet build + ISCC 出安装器。注意：含中文的 .ps1 须存 UTF-8 with BOM，否则 PS5.1 按 GBK 解码乱码。

### 落地页

**改动文件：** `site/index.html`（新增）

- 单页落地页（Neumorphism 拟物风格 + Koodo 式留白），首屏 CIE HELPER 字标、点击下载锚点滚动到下载区，提供 macOS/Windows 两个下载按钮指向 GitHub Release 直链，含首次打开的 Gatekeeper/SmartScreen 放行提示、功能介绍与 FAQ。图标以 data URI 内嵌自包含。

### 发布状态

v0.3.0 GitHub Release 已建为**草稿**（含 `cie-helper-0.3.0.pkg` 91MB + 重新编译含分割修复的 `cie-helper-0.3.0-setup.exe` 48MB），待用户确认后手动发布。分割器 S1–S5 共 4 个 commit 尚未推送。

---

## 2026-07-16 — Windows 安装包 + 图标 + 白屏根因修复（flet 版本锁定 0.85.3）

**改动文件：** `pyproject.toml`, `packaging/windows/cie-helper.iss`（新增）, `packaging/windows/app.ico`（新增）, `assets/icon.png`（新增）, `extensions/flet_pdf_render/src/flutter/flet_pdf_render/pubspec.yaml`, `CLAUDE.md`, `uv.lock`

### Windows 安装包（Inno Setup）

- 新增 `packaging/windows/cie-helper.iss`：把 `flet build windows` 的整个输出目录（exe + 全部 DLL + `data/` + `Lib/` + `DLLs/` + `site-packages/`，缺一不可）打成单个向导式 `setup.exe`。产物 `dist/cie-helper-0.1.0-setup.exe`（**48 MB**，源目录 ~203 MB）。
- 关键决策：`PrivilegesRequired=lowest` → **per-user 安装、无 UAC 弹窗**，装到 `%LocalAppData%\Programs`（未签名 app 对普通用户最顺滑）；`AppId` GUID 固定，**跨版本不可改**，否则升级会被当成新软件。
- 编译命令：`"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging/windows/cie-helper.iss`。
- 终端用户**无需预装** Python/Flutter/Dart——三套运行时全部内嵌。未签名 → 首次运行 SmartScreen 蓝框，点"更多信息→仍要运行"即可（2024 年起连 EV 证书也无法秒过，免费出路是 Microsoft Store 或 Azure Artifact Signing ~$10/月）。

### App 图标

- 新增 `assets/icon.png`（1024×1024 石墨灰 #334155 圆角方块 + 白色 "CIE" monogram，Pillow 生成）→ `flet build` 自动嵌入 exe/窗口/任务栏图标；`packaging/windows/app.ico`（多分辨率）→ 安装向导图标（`SetupIconFile`）。

### 打包 app 白屏根因修复（本日核心）

**症状：** 安装/直接运行打包 exe，窗口出现但永久白屏（先闪一下粉色），无任何报错。

**排查（拆掉三层错误假设后钉死）：** 埋点证明 `main(page)` 从未被调用 → 最小 hello-world 同样复现（排除全部业务代码/PdfRenderer/重导入）→ Dart 侧 `--debug` 日志显示 registerClient 已发但 Python 零字节收到 → **载荷交换二分**（借 7/12 构建的扩展 example 的 site-packages 换入即恢复）→ 在 dist-info 目录名里发现真凶。

**根因：** `[project.dependencies]` 的 `flet>=0.85.3` 无上限。`flet build` 打包时**无视 uv.lock**、按此约束全新 pip install → 抓到刚发布的 **flet 0.86.0**（Python 侧）；而 flet-cli 0.85.3 生成的 Flutter 客户端是 **0.85.3** → 两侧线协议不匹配 → session 永远无法注册 → 白屏。dev venv 和 pubspec.lock 都是 0.85.3，常规检查全部"看起来一致"，唯一错位的副本只在 bundle 里。macOS/iOS 能跑纯属时间运气（构建时 0.86.0 尚未发布）。

**修复：** `flet`/`flet-cli`/`flet-desktop` 三件套锁步 pin `>=0.85.3,<0.86`（附详细注释）；重建后验证 session 建立、四 tab UI 全渲染。

### flet 0.86.0 升级尝试 → 放弃（项目定死 0.85.3）

- 用户希望升 0.86（含其上游提的 serious-python 修复），三件套 + 扩展 pubspec（`flet: ^0.85.3` → `">=0.85.3 <0.87.0"`，caret 对 0.x 即 `<0.86` 会在 pub 解析时冲突）齐步升级并实测。
- **0.86.0 在中文（GBK 936）Windows 上双重破损，放弃：** ① `serious_python_windows_plugin.cpp` 含非 GBK 字符 → MSVC `C4819`→`C2220` 编译失败（[flet#6686](https://github.com/flet-dev/flet/issues/6686)，修复 PR 在 review；env `CL=-utf-8` 可绕过——注意 **dash 拼写**，Git Bash 会把 `/utf-8` 路径转换成 `C:/Program Files/Git/utf-8`）；② serious_python 4.3.2 的打包步骤 pip install **永久挂死**（site-packages 0 文件、无网络 I/O；同一条 pip 命令手动跑秒过——疑似子进程 stdout 管道未消费死锁），无 workaround。
- **决策：本项目永久停留 0.85.3**——大 PDF 问题早已在 `modules/renderer.py` 用 pypdf 页预抽取本地解决，0.86 无不可替代价值。pyproject 注释已写明"不要随意升级"；如将来非升不可，flet 三件套 + 扩展 pubspec 四处必须锁步。
- 附带环境收尾：0.86 工具链要求的 Flutter SDK 3.44.4（曾自动装到 `~/flutter/3.44.4`，~2GB）已删除；`D:\flutter`（3.41.7）保持不动，正是 0.85.3 构建所用。

### 其他

- `pyproject.toml` exclude 补入 `packaging`（安装包脚本目录不进 app.zip，下次 build 生效）。
- `CLAUDE.md` 构建小节更新：完整构建命令升级为 `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 CL=-utf-8 uv run flet build windows`；新增 flet 三件套锁步纪律 + 打包 app 白屏调试技巧（exe 加 `--debug` 保留 Dart 日志、直接改 `%APPDATA%\Roaming\<company>\<app>\flet\app\` 免重建迭代）。
- 本条目所有改动**未提交**，由用户决定是否 commit。

---

## 2026-07-15 — 打包体积从 ~900MB/1.2GB 降到 190MB（flet build exclude 修复）

**改动文件：** `pyproject.toml`

### 功能说明

排查 `flet build` 出来的 macOS/Windows app 为何高达 ~1.2GB，定位到根因并修复：**flet 把整个项目工作目录复制进 `app.zip`（`build/<platform>/data/flutter_assets/app/`），且不读 `.gitignore`**，只按 `[tool.flet.app].exclude` 里显式列的**顶层名字**排除。修复前 `app.zip`（未压缩 1287MB / 磁盘 402MB）里塞满了 `.venv`(425MB)、`.claude/worktrees`(539MB)、`.mypy_cache`(181MB)、`.git`、`.codegraph` 和散落的根目录测试 PDF——而真正的代码（`app_flet`/`core`/`modules`）不到 1MB。

- **修复**：把 `[tool.flet.app].exclude` 从 `["extensions", "spikes", "tests", "dev"]` 扩充为完整清单，新增 `.venv`、`.git`、`.claude`、`.mypy_cache`、`.pytest_cache`、`.ruff_cache`、`.codegraph`、`.cursor`、`__pycache__`、`dist`、`in_dev`、`docs` 以及 4 个散落根 PDF 文件名；并加详细注释说明打包机制。跨平台生效，故 macOS 构建同样受益。
- **验证结果（Windows，真实 build）**：`build/windows` **901MB → 190MB**（-79%）；`app.zip` **402MB → 0.3MB**（条目 43327 → 67）；streamlit/pyarrow/altair/pydeck/.venv/.claude/.mypy_cache 全部确认清除。

### 关键结论与注意事项

- **依赖解析路径一直是干净的**：flet 只按 `[project.dependencies]` 把 runtime 依赖**全新装**进 bundle（`SERIOUS_PYTHON_SITE_PACKAGES` → `build/site-packages`），streamlit 从不在其中。streamlit 之所以随 app 分发，纯粹是因为 `.venv/` 目录被整个扫进了 `app.zip`。因此 `uv sync --no-dev` **无法减小体积**——`.venv` 无论装了什么都会被复制，唯一开关是 exclude 清单。
- **剩余 190MB 是地板**：Flutter 引擎 + flet_web/canvaskit + CPython + 合法依赖（pandas/numpy ~55MB、openai、pdfminer、cryptography、pydantic）。若要更小，下一步是去 pandas 改用 stdlib `csv` 重构 `core/storage.py`（约再省 40–55MB），本次未做。
- **安全（已修复）**：本地 repo 根目录的真 `.env`（含真实 SMTP 密码 + API key，git 忽略但磁盘存在，flet 从磁盘打包故进了 `app.zip`）会随分发包泄露。运行时其实**只读** `~/.cie_helper/.env`（`core/settings.py:8` `_ENV_PATH`），打包那份从不被读——纯死文件泄漏、零功能需求。已把 `.env`/`.env.example` 加入 exclude，并重新 build 验证 `.env` 已从 `app.zip` 消失。
- pyproject 改动**未提交**，由用户决定是否 commit。

---

## 2026-07-14 — README 准确性与语言修正 + Phase 2 合并入 main

**改动文件：** `README.md`

### 功能说明

校对用户改写的 README，核对内容与实际代码 / `flet build` 目标后，修正若干事实性错误与英文语法/拼写。本次 session 的代码改动（大 PDF 批改修复、响应式布局收尾）已记录在同日及前一日条目中，此处仅记 README。另：Phase 2（整个 iOS 迁移）已在本次 session 以快进方式合并入 `main`（`abc49c8 → 12001af`），远端 `worktree-phase2b-renderer` 分支与本地 worktree 已清理，PR #7 自动标记 merged。

- **事实性**：uv 安装链接 `uv.run/docs/installation` → 官方 `docs.astral.sh/uv/getting-started/installation/`；`flet build` 目标 `iOS` → 合法值 `ipa`（真机）/ `ios-simulator`（经 `flet build --help` 核实，合法集为 `{macos,linux,windows,web,apk,aab,ipa,ios-simulator}`）；文中的 "config view" 并不存在 → 实际为 **Settings**（设置）对话框。
- **语言/拼写**：`a Image Model` → `an image model`；补冠词（`uses the qwen3-vl-flash model`）；指令语气 `could` → `can`；品牌名 `Goodnote(s)` → `GoodNotes`；`Dashscope by Aliyun` → `DashScope by Alibaba Cloud (Aliyun)`；首句去重（`track...and track`）并补上正文未提及的下载功能；`Install using flet build` → `Build the app with`（`flet build` 是打包而非安装）。

### 注意事项

- README 改动**未提交**，由用户决定是否 commit。

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
