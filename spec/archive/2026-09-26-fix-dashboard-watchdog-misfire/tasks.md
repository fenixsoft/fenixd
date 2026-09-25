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

- [x] 1.1 `core/dashboard/server.py` 新增纯函数 `_is_tmux_hosted(ppid=None)`：读 `os.getppid()`（或传入 ppid）对应 `/proc/<ppid>/comm`，值**恰为** `tmux: server` 即返回 True；comm 可读但不匹配时才回退读 `/proc/<ppid>/cmdline`，且**仅当** `argv[0]` 的 basename **恰为** `tmux` 或以 `tmux:` 开头才返回 True（MUST NOT 采用「argv 任一项含 `tmux` 子串」：agent 自测包装脚本作父进程时 argv[0] 形如 `.../tmux_selftest.sh`，子串命中会把 agent 自测实例误判为显式常驻、漏掉防泄漏）；读取失败（非 Linux / /proc 不可用 / 进程已退出）返回 False
- [x] 1.2 `_start_claude_watchdog` 开头增加判据：`if _is_tmux_hosted(): return False`（显式长驻，不装配 watchdog），并在 docstring 说明「tmux 承载=人工常驻，不可用自身 TMUX 环境变量判定（会被 agent_runner 透传污染）」

## 2. 回归测试

- [x] 2.1 `tests/test_dashboard_orphan_guard.py` 新增 `test_is_tmux_hosted_detects_tmux_parent`：monkeypatch 使 `/proc/<pid>/comm` 读取命中 `tmux: server` → `_is_tmux_hosted` 返回 True；非 tmux comm → False；/proc 读取失败 → False
- [x] 2.2 新增 `test_watchdog_skipped_when_tmux_hosted`：DETACH=1 + `CLAUDE_PID`=存活进程 + monkeypatch `_is_tmux_hosted` 返回 True → `_start_claude_watchdog()` 返回 False 且未出现 `claude-watchdog` 线程
- [x] 2.3 新增 `test_watchdog_still_assembled_when_not_tmux_hosted`：DETACH=1 + `CLAUDE_PID`=存活进程 + monkeypatch `_is_tmux_hosted` 返回 False → 仍装配 `claude-watchdog` 线程（既有防泄漏不变）
- [x] 2.4 新增 `test_is_tmux_hosted_ignores_tmux_env`：设置环境变量 `TMUX`（模拟 daemon/agent_runner 透传），对一个真实非 tmux 进程 pid（如 `subprocess.Popen(["sleep", "30"])`，comm 为 `sleep`）调用**未经 monkeypatch 的真实** `_is_tmux_hosted` → 返回 False。MUST NOT 在本例 stub `_is_tmux_hosted`（stub 后断言与 2.3 同义反复，无法证明判据未读 `TMUX`）
- [x] 2.5 运行 `python3 -m pytest tests/test_dashboard_orphan_guard.py -q` 全绿，且既有 12 个用例（`_bind_parent_lifecycle` 相关 5 个 + watchdog 相关 7 个，见 `tests/test_dashboard_orphan_guard.py:41-186`）不回归
- [x] 2.6 既有 `test_watchdog_assembled_for_agent_env`（`tests/test_dashboard_orphan_guard.py:139`）与 `test_bind_parent_lifecycle_detaches_with_watchdog`（同文件 :152）MUST 显式 monkeypatch `_is_tmux_hosted` 返回 False：两例直调真实 `_start_claude_watchdog` / `_bind_parent_lifecycle`，新判据会读进程真实父进程——在 tmux 直接承载 pytest（如 `tmux new-session -d "python3 -m pytest …"`）时会被判为常驻而假失败

## 3. 入口与文档加固

- [x] 3.1 `skills/fenix-dashboard/SKILL.md` 的 tmux 启动命令改为 `tmux new-session -d -s fenix-dashboard "env -u CLAUDE_PID python3 $DASH --serve"`，并在注释说明「防 claude-watchdog 绑会话自杀（与 hook_engine restart-dashboard 固化命令对齐）」
- [x] 3.2 `agents/administrator.md` 的【常驻启动】命令同样加 `env -u CLAUDE_PID` 前缀

## 4. 收尾验证

- [x] 4.1 运行 `python3 -m pytest tests/test_dashboard_orphan_guard.py tests/test_dashboard_mode.py -q` 全绿
- [x] 4.2 新增 `test_is_tmux_hosted_with_real_fixture`（真实 `/proc` 路径覆盖，非纯 monkeypatch）：
  - comm 主判据：`subprocess.Popen(["python3", "-c", "import ctypes,time; ctypes.CDLL('libc.so.6').prctl(15, b'tmux: server', 0, 0, 0); time.sleep(30)"])`，断言 `_is_tmux_hosted(<该 pid>)` 返回 True。**MUST NOT** 用 `bash -c 'exec -a "tmux: server" sleep 30'` 作该用例夹具——实测其 `/proc/<pid>/comm` 仍是 `sleep`（`exec -a` 只改 argv[0]，不改 comm），该夹具覆盖不到本 change 的 comm 主判据
  - argv 回退：`exec -a tmux sleep 30`（argv[0] basename 恰为 `tmux`）→ True；父脚本名含 `tmux` 子串（如 `exec -a /tmp/tmux_selftest.sh sleep 30`）→ False
  - 负例：普通 `sleep` 进程 pid → False
