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

## 2. 顺手看到、没有改的问题

- `modules/downloader.py:26` `_build_url()` 的 `return` 后面有一行只含空格的多余行（无害，属白名单外，未动）。
- `tests/test_renderer.py:104` 每次 pytest 收尾都打印 `Task was destroyed but it is pending!`（asyncio 任务没被 await 干净）。不影响结果，属白名单外，未动。
- `tests/test_paper_type.py::test_grader_config_try_load_returns_none_when_missing` 在任何配了真 `GRADER_API_KEY` 的机器上都会失败——该测试假设本机没有凭证。任务书说明是已知失败、不用修，原样保留。
