## Context

`core/dashboard/server.py` 的孤儿实例防护有两道防线：

1. `_bind_parent_lifecycle`（2026-09-03 runs 删空事故 V1 防线）：非 DETACH 调用挂
   `PR_SET_PDEATHSIG` + 拒绝 PPID==1 启动，防「调试脚本 import serve() 后孤儿化」。
2. `_start_claude_watchdog`（2026-09-04 第二防线）：DETACH 通道（人的 `--serve`
   长驻入口）检测到 agent 环境（`CLAUDE_PID` 指向存活 claude）时，绑定该 claude
   生命周期——claude 死则实例自杀。引入动机是 agent 用 `nohup ... --serve` 自测后
   实例被 init 收养成为孤儿（8790 泄漏事故）。

第 2 道防线的前提是「带 `CLAUDE_PID` ⇒ 本实例是 agent 临时自测实例」。该前提在
**tmux 承载**下破裂：tmux server 启动时把启动 shell 的完整环境（含 `CLAUDE_PID`）
复制进 pane，于是人工 tmux 常驻的 dashboard 也带上了 `CLAUDE_PID`，被误绑到某个
Claude 会话上。

2026-09-22 08:30 实证：用户会话 `--continue --fork-session` 换了 claude PID
（旧 `624169` → 新 `693542`），常驻 dashboard 的 watchdog 在 ≤5s 内判死并
`os.kill(getpid(), SIGTERM)`，8787 停止监听；同刻 tmux server 与 `fenixd-*` 会话
均存活，排除 tmux server 连坐。

`core/hook_engine.py` 的 `restart-dashboard` hook 早在 2026-09-06 就固化启动命令为
`env -u CLAUDE_PID python3 .../fenix_dashboard.py --serve`（见 hook_engine.py:782），
说明该风险已被识别过，但只落在 hook 一条路径，`skills/fenix-dashboard/SKILL.md` 与
`agents/administrator.md` 两个入口仍用裸 `python3 ... --serve`，判据本身也未修。

## Goals / Non-Goals

**Goals**
- 人工 tmux 常驻的 dashboard MUST NOT 因 `CLAUDE_PID` 会话变动而自杀。
- agent 经 nohup 临时自测的实例 MUST 继续受 watchdog 保护（防 8790 类孤儿泄漏）。
- 修复判据落在代码，而非仅靠各入口记得带 `env -u CLAUDE_PID` 前缀。

**Non-Goals**
- 不改 `_bind_parent_lifecycle` 的 PDEATHSIG/孤儿拒启两道防线。
- 不改 agent 经 CLI 自测的既定语义（仍允许、仍被 watchdog 收口）。
- 不引入新配置键、不改 dashboard API/UI。

## Decisions

### D1：用「父进程是 tmux server」判定显式常驻，而非「自身环境含 TMUX」

实测两种判据的污染情况：

- **自身的 `TMUX` 环境变量**：daemon（pid 702489）由 tmux 下的 supervisor 启动，
  其 `/proc/<pid>/environ` 含 `TMUX=/tmp/tmux-0/default,631314,0`。`agent_runner` 构造
  agent 子进程 env 时用 `os.environ.copy()`（`core/agent_runner/runner.py:3557`），
  **不清洗 `TMUX`**。于是 agent 子进程（实测 pid 703069）带 `TMUX`，它经 Bash 工具
  `nohup` 起的 dashboard 也带 `TMUX` → 该判据会把 **agent 临时自测实例误判为显式常驻**，
  漏掉防泄漏。❌
- **父进程是 tmux server**：实测人工启动的常驻实例（pid 698873）`PPID=631314`，其
  `/proc/631314/comm == "tmux: server"`；agent 起的 claude（pid 703069）`PPID=702489`
  （daemon，`comm==python3`），其 nohup dashboard 的父是 Bash shell（退出后 reparent
  为 1）。**父进程身份不随环境变量继承传播**，判据干净。✅

**Decision**：读 `os.getppid()` 的 `/proc/<ppid>/comm`，值**恰为** `tmux: server`
即判显式常驻，不装配 watchdog；comm 可读但不匹配时才回退 `cmdline`，且仅当 `argv[0]`
的 basename 恰为 `tmux` 或以 `tmux:` 开头才算命中（不用「argv 含 `tmux` 子串」——
agent 自测包装脚本名含 `tmux` 会造成假阳性、漏掉防泄漏）。读取失败（/proc 不可用、非 Linux）回退到
「按非长驻处理」，保持 watchdog 的既有防泄漏（fail-safe 偏向防泄漏，与既有代码在非
Linux 上「仅告警不阻断」的取向一致）。

**备选**：入口全加 `env -u CLAUDE_PID`。缺点是防的是「记得加前缀」，未来新入口仍会漏；
本案作为**双保险**保留（D3），但判据仍是根本修复。

### D2：判据包装为可独立测试的纯函数

新增 `_is_tmux_hosted(ppid: int | None = None) -> bool`，只做「给定 pid，判断其 comm/argv
是否 tmux」一件事，便于 monkeypatch 与单测，不在 `_start_claude_watchdog` 内联 IO。

### D3：入口与文档同步加固（双保险）

- `skills/fenix-dashboard/SKILL.md`：`tmux new-session ... "python3 $DASH --serve"`
  改为 `"env -u CLAUDE_PID python3 $DASH --serve"`。
- `agents/administrator.md`：「常驻启动」命令同样加 `env -u CLAUDE_PID`。
两条与 `hook_engine.py:782` 的既有固化命令对齐，使三条路径一致。

## Risks / Trade-offs

- [非 Linux 或无 /proc 时判据失效] → 回退「按非长驻处理」（仍需 `CLAUDE_PID` 才装配），
  与现状等价，不引入回归；且 dashboard 生产部署即 Linux。
- [tmux 以非常规方式启动（如 `tmux run-shell`、嵌套 tmux）导致父进程非直接 tmux server]
  → `comm` 判据以父进程为准；若父是 shell 而非 tmux，退化为「非长驻」，行为等同修复前，
  不会更糟。真实入口（`tmux new-session -d -s ... "<cmd>"`）父进程即 tmux server。
- [显式常驻实例自身崩溃后无人拉起] → 不在本 change 范围；人工 `--serve` / skill 重启
  即恢复。tmux 常驻语义本就要求人工经 kill-session 收口。

## Migration Plan

1. 改 `core/dashboard/server.py`（`_is_tmux_hosted` + `_start_claude_watchdog` 判据）。
2. 扩充 `tests/test_dashboard_orphan_guard.py`。
3. 改两个入口文档。
4. 生效需重启 dashboard 进程（`tmux kill-session -t fenix-dashboard` 后经 skill 重启）；
   **不影响 daemon**，无需 daemon 重启。回滚即还原上述文件。

## Open Questions

无。
