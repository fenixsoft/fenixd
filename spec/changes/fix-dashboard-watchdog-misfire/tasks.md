## Deliverables

```yaml
- path: core/dashboard/server.py
  kind: modify
- path: tests/test_dashboard_orphan_guard.py
  kind: modify
- path: skills/fenix-dashboard/SKILL.md
  kind: modify
- path: agents/administrator.md
  kind: modify
```

## 1. 核心判据修复

- [ ] 1.1 `core/dashboard/server.py` 新增纯函数 `_is_tmux_hosted(ppid=None)`：读 `os.getppid()`（或传入 ppid）对应 `/proc/<ppid>/comm`，值为 `tmux: server` 或读取 `/proc/<ppid>/cmdline` 的 argv 含 `tmux` 即返回 True；读取失败（非 Linux / /proc 不可用 / 进程已退出）返回 False
- [ ] 1.2 `_start_claude_watchdog` 开头增加判据：`if _is_tmux_hosted(): return False`（显式长驻，不装配 watchdog），并在 docstring 说明「tmux 承载=人工常驻，不可用自身 TMUX 环境变量判定（会被 agent_runner 透传污染）」

## 2. 回归测试

- [ ] 2.1 `tests/test_dashboard_orphan_guard.py` 新增 `test_is_tmux_hosted_detects_tmux_parent`：monkeypatch 使 `/proc/<pid>/comm` 读取命中 `tmux: server` → `_is_tmux_hosted` 返回 True；非 tmux comm → False；/proc 读取失败 → False
- [ ] 2.2 新增 `test_watchdog_skipped_when_tmux_hosted`：DETACH=1 + `CLAUDE_PID`=存活进程 + monkeypatch `_is_tmux_hosted` 返回 True → `_start_claude_watchdog()` 返回 False 且未出现 `claude-watchdog` 线程
- [ ] 2.3 新增 `test_watchdog_still_assembled_when_not_tmux_hosted`：DETACH=1 + `CLAUDE_PID`=存活进程 + monkeypatch `_is_tmux_hosted` 返回 False → 仍装配 `claude-watchdog` 线程（既有防泄漏不变）
- [ ] 2.4 新增 `test_watchdog_ignores_tmux_env_without_tmux_parent`：设置环境变量 `TMUX` 但 monkeypatch `_is_tmux_hosted` 返回 False → 仍装配 watchdog（父进程判据不受 TMUX 继承污染）
- [ ] 2.5 运行 `python3 -m pytest tests/test_dashboard_orphan_guard.py -q` 全绿，且既有 4 个孤儿守卫用例不回归

## 3. 入口与文档加固

- [ ] 3.1 `skills/fenix-dashboard/SKILL.md` 的 tmux 启动命令改为 `tmux new-session -d -s fenix-dashboard "env -u CLAUDE_PID python3 $DASH --serve"`，并在注释说明「防 claude-watchdog 绑会话自杀（与 hook_engine restart-dashboard 固化命令对齐）」
- [ ] 3.2 `agents/administrator.md` 的【常驻启动】命令同样加 `env -u CLAUDE_PID` 前缀

## 4. 收尾验证

- [ ] 4.1 运行 `python3 -m pytest tests/test_dashboard_orphan_guard.py tests/test_dashboard_mode.py -q` 全绿
- [ ] 4.2 新增 `test_is_tmux_hosted_with_real_fixture`：用 `subprocess` 起一个名为 `tmux: server` 的假进程（如 `bash -c 'exec -a "tmux: server" sleep 30'`）作为父进程参照，断言 `_is_tmux_hosted(<该 pid>)` 在真实 `/proc` 读取下返回 True；普通 `sleep` 进程 pid → False（真实 /proc 路径覆盖，非纯 monkeypatch）
