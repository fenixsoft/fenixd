# Dashboard 实例生命周期

<!-- knowledge: capability=dashboard-instance-lifecycle rev=2
     sources=spec/archive/2026-09-02-fix-dashboard-duration-and-verify-gate,spec/archive/2026-09-26-fix-dashboard-watchdog-misfire -->

dashboard 服务实例的端口独占、启动退出纪律与孤儿泄漏防护（claude-watchdog）。

## 规则

- 端口独占：`fenix_dashboard.py --serve` 启动时目标端口被占用，MUST NOT 静默僵挂——检测占用者：若为旧的 dashboard `--serve` 实例（命令行匹配 `bin/fenix_dashboard.py` 且含 `--serve`），先终止旧实例再绑定接管；若为其它进程，打印占用进程信息后明确报错退出（退出前不终止任何进程，退出码非 0）。
- 同一时刻至多一个 dashboard 实例监听生产端口；端口取值沿用 `--port > dashboard.yaml port > config port > 8787` 解析链，仅对最终确定的单一端口做占用检测。
- 启动失败的实例 MUST 在 5 秒内退出进程，不保留「已运行但未监听」的僵尸实例。
- claude 生命周期 watchdog（`_start_claude_watchdog`，防 agent 经 CLI nohup 临时自测的实例泄漏）只绑定非显式长驻实例。「显式长驻」判据为父进程是 tmux server：读 `/proc/<ppid>/comm` 恰为 `tmux: server`；comm 可读但不匹配时回退父进程 cmdline，仅当 `argv[0]` 的 basename 恰为 `tmux` 或以 `tmux:` 开头方可判为常驻。命中即不装配 watchdog，`CLAUDE_PID` 存在与否不影响——tmux 承载即视为人工可经 `tmux kill-session` 收口的常驻服务。
- 判据禁令：MUST NOT 采用「argv 任一项含 `tmux` 子串」（以含 tmux 子串的包装脚本为父进程的 agent 自测实例会被误判常驻、漏掉防泄漏）；MUST NOT 采用「进程自身环境含 `TMUX`」（daemon 由 tmux 下 supervisor 启动，`TMUX` 会被 agent_runner 透传给 agent 子进程，agent 经 nohup 拉起的实例同样带 `TMUX`）。
- 未命中长驻判据的实例（agent 经 CLI nohup 拉起、父进程非 tmux）行为不变：装配 watchdog 绑定 `CLAUDE_PID`，目标 claude 进程退出后实例自杀，避免孤儿泄漏。
- 入口双保险：skill、administrator 常驻启动命令与 hook_engine 的 `restart-dashboard` hook 统一带 `env -u CLAUDE_PID`，与父进程判据互为冗余。
- PDEATHSIG/孤儿拒启两道防线（`_bind_parent_lifecycle`，import 场景防泄漏）保持原样，与本页 watchdog 判据正交。

## 溯源

- [2026-09-02 2026-09-02-fix-dashboard-duration-and-verify-gate](spec/archive/2026-09-02-fix-dashboard-duration-and-verify-gate/) — 建立端口独占与启动语义：旧实例接管、异主报错退出、5 秒僵尸退出
- [2026-09-26 2026-09-26-fix-dashboard-watchdog-misfire](spec/archive/2026-09-26-fix-dashboard-watchdog-misfire/) — watchdog 增加「tmux 承载即显式长驻、不装配」父进程判据（PPID comm 恰等匹配），禁 TMUX 环境变量与 tmux 子串误判路径；skill/agent/hook 入口补 `env -u CLAUDE_PID` 双保险
