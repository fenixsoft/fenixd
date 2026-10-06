# Dashboard 实例生命周期

<!-- knowledge: capability=dashboard-instance-lifecycle rev=3
     sources=spec/archive/2026-09-02-fix-dashboard-duration-and-verify-gate,spec/archive/2026-09-26-fix-dashboard-watchdog-misfire,spec/archive/2026-10-07-fix-dashboard-resident-takeover -->

dashboard 服务实例的端口独占与接管语义、启动退出纪律与孤儿泄漏防护（claude-watchdog）。

## 规则

- 端口独占：`fenix_dashboard.py --serve` 启动时目标端口被占用，MUST NOT 静默僵挂——检测占用者身份后分支处理：
  - 占用者为旧的 dashboard `--serve` 实例（命令行匹配 `bin/fenix_dashboard.py` 且含 `--serve`）且**非 tmux 承载**（agent 临时自测实例、nohup 遗留实例）：终止旧实例后绑定接管端口；
  - 占用者为 dashboard `--serve` 实例且为 **tmux 承载的常驻实例**：MUST NOT 向占用者发送任何信号，常驻实例继续存活并监听；新实例打印含占用者 PID、tmux 常驻说明与「请用 `--port` 指定其它端口，或直接复用常驻实例」指引的错误后非 0 退出；
  - 占用者为其它进程：打印占用进程信息后明确报错退出（退出前不终止任何进程，退出码非 0）。
- tmux 承载判定与 watchdog 长驻判据同源（`_is_tmux_hosted`）：接管路径经 `_parent_is_tmux_server` 读占用者 `/proc/<pid>/stat` 取 ppid，再按父进程判据——`/proc/<ppid>/comm` 恰为 `tmux: server`；comm 可读但不匹配时回退父进程 cmdline，仅当 `argv[0]` basename 恰为 `tmux` 或以 `tmux:` 开头方命中。判定时机在占用者身份复核（starttime 锚定防 PID 复用误杀）通过之后、发送信号之前，父进程身份与占用者 pid 同源快照，不引入额外竞态窗口。
- 判定 fail-safe 方向：接管路径读不到占用者父进程身份（占用者已成孤儿、ppid 变 1 等）按非 tmux 承载处理、走既有接管——孤儿实例已无可依托的 tmux 会话，接管收割不破坏任何常驻形态；与 `_is_tmux_hosted` 读取失败返回 False 的纪律一致。
- 端口解析链为 `--port > dashboard.yaml port > config port > 8787`，仅对最终确定的单一端口做占用检测；端口冲突一律报错退出、不自动上探换端口，换端口由调用方自行决定（自动上探会让 URL 写死 8787 的验证流量打到常驻实例而非被测实例）。
- 启动失败的实例 MUST 在 5 秒内退出进程，不保留「已运行但未监听」的僵尸实例。
- claude 生命周期 watchdog（`_start_claude_watchdog`，防 agent 经 CLI nohup 临时自测的实例泄漏）只绑定非显式长驻实例。「显式长驻」判据为父进程是 tmux server（同上判据），命中即不装配 watchdog，`CLAUDE_PID` 存在与否不影响——tmux 承载即视为人工可经 `tmux kill-session` 收口的常驻服务。
- 判据禁令：MUST NOT 采用「argv 任一项含 `tmux` 子串」（以含 tmux 子串的包装脚本为父进程的 agent 自测实例会被误判常驻、漏掉防泄漏）；MUST NOT 采用「进程自身环境含 `TMUX`」（daemon 由 tmux 下 supervisor 启动，`TMUX` 会被 agent_runner 透传给 agent 子进程，agent 经 nohup 拉起的实例同样带 `TMUX`）。
- 未命中长驻判据的实例（agent 经 CLI nohup 拉起、父进程非 tmux）：装配 watchdog 绑定 `CLAUDE_PID`，目标 claude 进程退出后实例自杀，避免孤儿泄漏。
- 入口双保险：skill、administrator 常驻启动命令与 hook_engine 的 `restart-dashboard` hook 统一带 `env -u CLAUDE_PID`，与父进程判据互为冗余。
- PDEATHSIG/孤儿拒启两道防线（`_bind_parent_lifecycle`，import 场景防泄漏）独立于本页 watchdog 判据，两者正交。

## 溯源

- 2026-09-02 fix-dashboard-duration-and-verify-gate（spec/archive/2026-09-02-fix-dashboard-duration-and-verify-gate） — 建立端口独占与启动语义：旧实例接管、异主报错退出、5 秒僵尸退出
- 2026-09-26 fix-dashboard-watchdog-misfire（spec/archive/2026-09-26-fix-dashboard-watchdog-misfire） — watchdog 增加「tmux 承载即显式长驻、不装配」父进程判据（PPID comm 恰等匹配），禁 TMUX 环境变量与 tmux 子串误判路径；skill/agent/hook 入口补 `env -u CLAUDE_PID` 双保险
- 2026-10-07 fix-dashboard-resident-takeover（spec/archive/2026-10-07-fix-dashboard-resident-takeover） — 端口接管增加常驻豁免：tmux 承载占用者拒信号、报错退出（PID+换端口指引）；接管路径补占用者 ppid 判定与读取失败放行的 fail-safe 方向；非 tmux 旧实例接管语义不变
