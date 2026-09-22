## Why

Dashboard 的孤儿实例防护（claude-watchdog，2026-09-04 为堵 agent nohup 自测泄漏而引入）
绑定的是环境变量 `CLAUDE_PID`。但经 tmux 常驻启动时，**tmux server 会把启动 shell 的
`CLAUDE_PID` 当普通环境变量继承进 pane**，使一个本应长期存活、跨 shell 存在的服务
被贴上「跟随某个 Claude 会话」的死亡开关：该 claude 会话一旦续接/分叉/退出，新
`claude` 进程换 PID，watchdog 在 ≤5s 内判定「目标已死」→ `os.kill(getpid(), SIGTERM)`
自杀。

2026-09-22 08:30 实证：`/root/fenixd` 的常驻 dashboard（pid 698873 之前的实例）在
用户会话 `--continue --fork-session` 后约 5 秒内静默退出，8787 停止监听；同一时刻
tmux server 与 `fenixd-*` 会话均存活，排除 tmux server 连坐。恢复手段是启动命令加
`env -u CLAUDE_PID`（人工绕过），但根本判据未修，任何未带该前缀的入口都会复现。

## What Changes

- **`core/dashboard/server.py`**：`_start_claude_watchdog` 增加「显式长驻」判据——
  当 dashboard 进程的**父进程是 tmux server**（读取 `PPID` 的 `/proc/<ppid>/comm`，
  判为 `tmux: server`，或 argv 含 `tmux`）时，判定为 tmux 承载的显式长驻入口，
  **不装配** claude-watchdog，`CLAUDE_PID` 存在与否不影响。纯 agent 自测（经 CLI
  nohup 直接拉起、父进程非 tmux）行为不变，仍装配 watchdog 绑定 claude 生命周期防泄漏。

  判据选择说明：**不用**「自身环境变量含 `TMUX`」作为判据——实测 daemon 由 tmux 下的
  supervisor 启动，其 `TMUX` 环境变量会被 `agent_runner`（`os.environ.copy()` 不清洗）
  透传给 agent 子进程，agent 再经 Bash 工具 nohup 起的 dashboard 同样带 `TMUX`，会把
  agent 临时自测实例**误判**为显式常驻、漏掉防泄漏。父进程是否为 tmux 无此继承污染：
  tmux 直接 spawn 命令时 dashboard 的 PPID 即 tmux server，而 agent nohup 实例的父是
  Bash shell（退出后 reparent 为 1）。
- **入口与文档加固**（双保险，判据之外）：
  - `skills/fenix-dashboard/SKILL.md` 的 tmux 启动命令补 `env -u CLAUDE_PID`；
  - `agents/administrator.md` 的「常驻启动」命令补 `env -u CLAUDE_PID`。
  与 `core/hook_engine.py` 中 `restart-dashboard` hook 已固化的 `env -u CLAUDE_PID`
  命令对齐（该 hook 早已识别此风险，但未回灌到 skill/agent 入口）。
- 回归测试：新增「tmux 承载不装配 watchdog」「非 tmux + CLAUDE_PID 仍装配」两类用例。

不动：`_bind_parent_lifecycle` 的 PDEATHSIG/孤儿拒启两道防线（那是 import 场景的
防泄漏，与本节问题正交）保持原样。

## Capabilities

### New Capabilities
<!-- 无新能力 -->

### Modified Capabilities

- `dashboard-instance-lifecycle`: 增加「显式长驻（tmux 承载）实例 MUST NOT 装配
  claude 生命周期 watchdog」的启动语义要求，明确孤儿防护只针对 agent 临时自测实例，
  不得误伤人工常驻实例。

## Impact

- 代码：`core/dashboard/server.py`（`_start_claude_watchdog` / `_bind_parent_lifecycle`）。
- 文档/入口：`skills/fenix-dashboard/SKILL.md`、`agents/administrator.md`。
- 测试：`tests/test_dashboard_orphan_guard.py`（扩充）。
- 无数据迁移、无 API 变更、无配置新增。生效需重启 dashboard 进程（不影响 daemon）。
