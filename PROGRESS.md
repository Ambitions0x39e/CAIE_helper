# PROGRESS

## 目标／顺序／最大风险

- 目标：设置→关于页加「更新」行，点击查 GitHub latest release，有新版弹确认框，确认后下对应平台包并静默安装。
- 顺序：任务 0 基线核对 → 任务 1 `core/settings.py` + `modules/updater.py` + 单测 → 任务 2 安装触发 → 任务 3 设置页接线。
- 最大风险 1：版本比较写反（`>` 写成 `<`）不会报错也没人发现 → 任务 1 反向验证必做，红→绿都贴。
- 最大风险 2：装错平台包（win 上跑 .pkg）→ `install()` 先校验后缀与 `sys.platform` 匹配才 spawn。
- 最大风险 3：Windows 装的时候 exe 被自己锁着 → spawn 完立刻 `page.window.close()` + `os._exit(0)`。

## 任务进度

### 任务 0 — 基线核对 ✅ 完成
- `uv run pytest -q` → **124 passed, 1 failed**（`test_paper_type.py::test_grader_config_try_load_returns_none_when_missing`，本机 `.env` 有真 GRADER_API_KEY 导致），与任务书实测数字一致。
- `uv run ruff check modules core app_flet` → All checks passed（0 issues）。
- `uv run mypy modules core app_flet` → no issues in 28 source files（0 issues）。
- `curl` GitHub latest release API → 可用免认证，但 `tag_name` 是 **`v1.0.0`**，不是任务书预期的 `v1.1.2` → 记入 BLOCKED.md。JSON 结构与资产命名已确认（`cie-helper-1.0.0-setup.exe` / `.pkg`），单测按任务书要求全部写死假响应，不打网络。

### 任务 1 — modules/updater.py ✅ 完成
- `core/settings.py` 加 `updates_dir` property + `init_dirs()` 里建目录（仿 `pdfs_dir`）。
- 新建 `modules/updater.py`：`AppUpdater.check()/download()/install()`，`_UpdateError` 私有不外泄，Pydantic 结果对象。
- 超时取值说明：任务书同时写了「`timeout=10`」和「同 `downloader.py` 的 `_REQUEST_TIMEOUT`」。两者冲突，采用后者 `(10, 30)`（connect 10s / read 30s）——它点名了唯一真源，且 connect 超时正是 10 秒；安装包有 50–100 MB，read 超时给 30s 才不会把正常下载判成超时。
- 反向验证已做：`>` 改 `<` → `-k version` 2 failed；改回 → 全绿。输出贴在对话里。

### 任务 2 — 触发安装 ✅ 完成
- `install()` 按 `sys.platform` 分派，先校验安装包后缀匹配平台（防装错包）再 spawn。
- Windows：`Popen([exe, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], creationflags=DETACHED_PROCESS|CREATE_NEW_PROCESS_GROUP)`；macOS：`Popen(["open", pkg])`。
- 单测 mock `subprocess.Popen` 精确断言两平台 argv + Windows creationflags，不真 spawn。
- 已批准例外：真跑了一次 `D:\repos\CieHelperWin\dist\cie-helper-1.1.2-setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART` → 退出码 0，无向导弹窗。命令与退出码贴在对话里。

### 任务 3 — 设置页接线 ✅ 完成
- `_build_about_view` 内新增「更新」行（在「反馈」之前），只改这个函数，其余代码未动。
- 非 win32/darwin：直接 `page.launch_url(RELEASES_PAGE_URL)`，不查不报错。
- 查更新走 `page.run_thread`（沿用 `mark.py` 既有模式），期间行显示「检查中…」并禁用点击。
- 有新版 → `ft.AlertDialog` 显版本号 + release notes，「立即更新」下载+安装+退出，「取消」只关。

## 结果

- `uv run pytest -q` → **177 passed, 1 failed**（124 基线 + 53 新增；失败仍是同一个已知的 `test_grader_config_try_load_returns_none_when_missing`，未新增），passed 数 ≥125 ✅
- `uv run ruff check modules core app_flet` → All checks passed，0 issues ✅
- `uv run mypy modules core app_flet` → no issues in 29 source files，0 issues ✅
- `grep -n '"更新"\|"反馈"' app_flet/tabs/settings.py` → 608 / 650，更新在前 ✅
- `uv run flet run --web --port 8550 app_flet/main.py` + `curl` → HTTP **200**，日志 0 处 Traceback / Error ✅
- 额外自证（超出验收要求）：用 stub page 真实构造了一次 `_build_about_view` 返回的 `ft.View` 并遍历控件树，确认「更新」行在「反馈」之前渲染出来——HTTP 200 只能证明 web shell 起来了，证不到这个函数不炸。
- `git diff -U0 app_flet/tabs/settings.py` 两处 hunk 均落在 `_build_about_view` 内，白名单外文件零改动。

## 遗留

- 见 BLOCKED.md：线上最新 release 还是 v1.0.0（< 本地 1.1.2），所以现在点「更新」会正确地提示「已是最新版本」。真正的端到端「查到新版→下载→安装」要等领导发一个版本号高于本地的 release 才能在真机上跑通；代码路径本身由单测 + 真实安装器实测（退出码 0）分别覆盖。
- macOS 分支只到 mock 为止（无 Mac 环境），任务书已说明。
