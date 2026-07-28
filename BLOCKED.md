# BLOCKED

## 1. GitHub latest release 的 `tag_name` 是 `v1.0.0`，不是任务书预期的 `v1.1.2`

任务 0 实测（2026-07-28）：

```
$ curl -s https://api.github.com/repos/Ambitions0x39e/CAIE_helper/releases/latest
tag_name: v1.0.0
body: 'Official public release.\r\n\r\n'
assets:
  cie-helper-1.0.0-setup.exe -> https://github.com/.../v1.0.0/cie-helper-1.0.0-setup.exe
  cie-helper-1.0.0-setup.pkg -> https://github.com/.../v1.0.0/cie-helper-1.0.0-setup.pkg
```

任务书说「领导会在开工前手动发布好 GitHub Release v1.1.2」，实际线上最新还是 v1.0.0 —— 看起来 v1.1.2 的 release 还没发。

- **对本次交付的影响：无阻塞。** API 免认证可用，`tag_name`/`body`/`assets[].browser_download_url` 三个字段和资产命名规律（`-setup.exe` / `-setup.pkg`）都已确认，足够写实现；单测按任务书要求全部用 `monkeypatch` 写死假响应，不打网络。
- **对用户可见行为的影响：** 本地版本 1.1.2 > 线上 1.0.0，所以现在点「更新」会提示「已是最新版本」——这是任务书定义的正确行为（「更旧」→ `update_available=False`），不是 bug。等 v1.1.2 或更高的 release 发出来，自然就能查到更新了。
- **需要领导做的事：** 把 v1.1.2（或下一版）真正发布到 GitHub Releases，并保持资产命名带 `.exe` / `.pkg` 后缀。

## 2. 顺手看到的问题 —— 已在 v1.1.3 修完

原先记在这里的三条（当时属白名单外，未动），领导后来指示修掉，已全部处理，见 commit `b6f1e70`：

- ~~`modules/downloader.py:26` `_build_url()` 的 `return` 后面有一行只含空格的多余行。~~ 已删。
- ~~`tests/test_renderer.py:104` 每次 pytest 收尾都打印 `Task was destroyed but it is pending!`。~~ 已修：`future.cancel()` 只是**排期**取消，收尾在同一批里就 `loop.stop()`，任务永远停在 pending。改为先在 loop 内部把挂住的任务取消并 await 掉再停。产品代码本来就是对的，问题只在测试收尾。
- ~~`test_grader_config_try_load_returns_none_when_missing` 在任何配了真 key 的机器上都会失败。~~ 已修：它断言的前提「未配置」从来没被**造出来**过，直接读了本机 `~/.cie_helper/.env`，所以它测的是环境不是代码。现在测试自己造出未配置环境，并补了反向用例（有 key 时必须返回配置），否则把 `try_load` 改成永远返回 None 也能过。
- 结果：测试套件从 177 通过 / 1 失败 变为 **179 通过 / 0 失败**，警告也消失了。

## 3. 新发现（v1.1.3 打包时看到，未改）

`app.zip` 里打进了几个纯开发用的顶层文件：`release.ps1`、`BLOCKED.md`、`PROGRESS.md`、`CLAUDE.md`、`.gitignore`、`.gitattributes`。

- **不是安全问题**：`release.ps1` 里只有构建逻辑和路径，没有凭证；真正危险的 `.env` 已经在 `exclude` 里，实测确认没打进去。
- **为什么没顺手改**：修法是往 `pyproject.toml` 的 `[tool.flet.app].exclude` 加这几个名字，那是领导的发布配置；而且改了就得重新打包，会让刚出的 `dist/cie-helper-1.1.3-setup.exe` 作废（一次构建约十分钟）。留给领导决定要不要在下一版一起清。
