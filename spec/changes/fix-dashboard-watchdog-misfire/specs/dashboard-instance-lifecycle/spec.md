## MODIFIED Requirements

### Requirement: dashboard 端口独占与启动语义

`fenix_dashboard.py --serve` 启动时若目标端口已被占用，MUST NOT 静默僵挂：需检测端口占用者，若为旧的 `fenix_dashboard.py --serve` 实例（命令行匹配 `bin/fenix_dashboard.py` 且含 `--serve`），MUST 先终止旧实例再绑定接管端口；若占用者为其它进程（非 dashboard 实例），MUST 明确报错退出并提示占用信息。同一时刻 MUST 至多一个 dashboard 实例监听生产端口（端口号来自 `--port > dashboard.yaml port > config port > 默认 8787` 的现有解析链）。

任何情况下启动失败的实例 MUST 在 5 秒内退出进程，不得保留「已运行但未监听」的僵尸实例堆积。

claude 生命周期 watchdog（`_start_claude_watchdog`，防 agent 经 CLI nohup 临时自测的实例泄漏）MUST 只绑定**非显式长驻**的实例。判定「显式长驻」的判据为：dashboard 进程的**父进程是 tmux server**（`/proc/<ppid>/comm` 为 `tmux: server`，或父进程 argv 含 `tmux`）。命中该判据时 MUST NOT 装配 watchdog，`CLAUDE_PID` 环境变量是否存在均不影响——tmux 承载即视为人工可经 `tmux kill-session` 收口的常驻服务。未命中的实例（含 agent 经 nohup 拉起、父进程非 tmux 者）行为不变，仍按现有逻辑装配 watchdog。

判据 MUST NOT 采用「进程自身环境变量含 `TMUX`」：daemon 由 tmux 下的 supervisor 启动，其 `TMUX` 变量会被 `agent_runner` 透传给 agent 子进程，agent 经 Bash 工具 nohup 起的 dashboard 亦带 `TMUX`，会把 agent 临时自测实例误判为显式常驻、漏掉防泄漏；父进程判据无此继承污染。

#### Scenario: 旧 dashboard 实例占用端口时接管

- **WHEN** 端口 8787 已被 13:26 启动的旧 `fenix_dashboard.py --serve --port 8787` 实例占用，此时启动新的 `fenix_dashboard.py --serve --port 8787`
- **THEN** 新实例检测到占用者为 dashboard 旧实例，终止旧进程并成功绑定 8787；`curl :8787/api/specs` 返回最新代码字段（如 `total_duration`）

#### Scenario: 非 dashboard 进程占用端口时报错退出

- **WHEN** 端口 8787 被无关进程（如 nginx、其它服务）占用
- **THEN** 新实例打印包含占用进程信息的错误后退出，退出前不终止任何进程，状态码非 0

#### Scenario: 端口解析链保持现有语义

- **WHEN** 未传 `--port` 且 `dashboard.yaml` 与 config 均指定了端口
- **THEN** 采用的端口序仍为 `--port > dashboard.yaml port > config port > 8787`（仅对最终确定的单一端口做上述占用检测）

#### Scenario: tmux 承载的常驻实例不装配 watchdog

- **WHEN** 经 `tmux new-session -d -s fenix-dashboard "python3 .../fenix_dashboard.py --serve"` 启动的实例，其父进程为 tmux server，且其环境继承了 `CLAUDE_PID`（指向某个 claude 会话）
- **THEN** `_start_claude_watchdog` 判定为显式长驻，MUST NOT 装配 `claude-watchdog` 线程；该 `CLAUDE_PID` 会话日后续接/分叉/退出时，dashboard 进程 MUST 继续存活并继续监听端口

#### Scenario: agent 无 tmux 的自测实例仍受 watchdog 保护

- **WHEN** agent 经 CLI（`nohup python3 .../fenix_dashboard.py --serve`）拉起实例，父进程非 tmux（Bash shell 退出后 reparent），环境含指向存活 claude 进程的 `CLAUDE_PID`
- **THEN** 仍装配 `claude-watchdog` 线程；该 claude 进程退出后，实例 MUST 自杀以避免孤儿泄漏（既有行为不变）

#### Scenario: 父进程判据不受 TMUX 环境变量继承污染

- **WHEN** 实例自身环境含 `TMUX` 变量（沿袭自 tmux 下启动的 daemon 透传）但父进程并非 tmux server
- **THEN** MUST NOT 仅凭 `TMUX` 变量判定为显式长驻，仍按非长驻处理（是否装配 watchdog 取决于 `CLAUDE_PID`）
