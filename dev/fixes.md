# 发版前检查清单 — 历史踩坑记录

这份文件记录 code review 中发现并已修复的问题，作为**每次推新版本前的检查清单来源**：
推新版本前过一遍下面的条目，确认没有重新踩同一个坑（尤其是那些没有测试保护、
只能靠人工确认还成立的条目）。

新条目按时间倒序加在最上面。每条格式：**问题** → **修法** → **怎么确认没有回归**。

---

## 2026-07-29 — `_windows_relaunch_script()` 的 settle 延迟

**问题**：装完安装器后立刻启动应用会 exit 0（干净退出，不是崩溃）——原因是
紧接着 225 MB 文件替换完就启动，需要等一下再启动。之前的修法是
`ping -n 6 127.0.0.1 >nul`（约 5 秒），但这个修法本身有两处没处理：

1. 没有测试断言这一行真的存在于生成的 `.cmd` 里，重构时可能被无声删掉。
2. `ping` 依赖本机 ICMP 回环正常工作——部分被组策略/安全软件锁死 ICMP 的
   Windows 环境会让 `ping` 立即失败而不产生等待，delay 直接消失，原来的
   竞态问题会原样重现。

**修法**：
- [modules/updater.py:571](../modules/updater.py#L571) `_windows_relaunch_script()`：
  把延迟机制从 `ping -n 6 127.0.0.1` 换成
  `powershell -NoProfile -NonInteractive -Command "Start-Sleep -Seconds 5"`——
  同样不需要真控制台（这也是当初弃用 `timeout` 的原因），但不依赖网络栈/ICMP。
- [tests/test_updater.py:815](../tests/test_updater.py#L815)
  `test_install_chains_installer_then_relaunch_in_a_detached_cmd`：新增断言
  `"Start-Sleep" in body`，并且顺序必须夹在安装器行和应用启动行之间
  （`body.index(exe) < body.index("Start-Sleep") < body.index(app_exe)`）。

**怎么确认没有回归**：跑 `uv run pytest tests/test_updater.py -q`，
`test_install_chains_installer_then_relaunch_in_a_detached_cmd` 必须通过。
如果以后又要改这段延迟逻辑（比如换回别的等待方式），先改这条测试的断言，
而不是绕开它。

**仍然悬而未决、没有修（人工判断后接受的风险）**：固定 5 秒本身是"睡够时间就
假设文件已解锁"的猜测，不是真正检测安装是否就绪。如果未来在极慢磁盘或
杀毒软件重扫描的机器上又复现"装完立刻退出"，说明 5 秒也不够了，需要考虑
改成重试启动（失败就退避重试）而不是固定睡眠——但目前没有实测数据支持这么做，
先记录在这里，出现新故障报告时回来看这一条。
