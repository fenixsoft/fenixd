# Dashboard 实例生命周期

<!-- knowledge: capability=dashboard-instance-lifecycle rev=7
     sources=spec/archive/2026-09-02-fix-dashboard-duration-and-verify-gate,spec/archive/2026-09-26-fix-dashboard-watchdog-misfire,spec/archive/2026-10-07-fix-dashboard-resident-takeover,spec/knowledge/_inbox/done/memory-distill-ops-runbook.md,spec/changes/add-systemd-hosting,spec/knowledge/_inbox/done/push-restart-unit-absent-tmux-stale-1106.md,spec/knowledge/_inbox/done/provfix-seed-fixture-residue-and-verify-instance-mixed-vintage-500.md -->

dashboard 服务实例的端口独占与接管语义、启动退出纪律与孤儿泄漏防护（claude-watchdog）。

## 规则

- 端口独占：`fenix_dashboard.py --serve` 启动时目标端口被占用，MUST NOT 静默僵挂——检测占用者身份后分支处理：
  - 占用者为 dashboard `--serve` 实例且为**常驻实例**（unit 承载：父进程为 PID 1；tmux 承载：父进程为 tmux server）：MUST NOT 向占用者发送任何信号，常驻实例继续存活并监听；unit 承载实例提示「请用 `systemctl restart fenix-dashboard` 重启生产实例或 `--port` 指定其它端口」，tmux 承载实例提示「请用 `--port` 指定其它端口，或直接复用常驻实例」，均含占用者 PID 后非 0 退出；
  - 占用者为旧的 dashboard `--serve` 实例且**非常驻**（agent 临时自测实例、nohup 遗留实例）：终止旧实例后绑定接管端口；
  - 占用者为其它进程：打印占用进程信息后明确报错退出（退出前不终止任何进程，退出码非 0）。
- 常驻豁免判定两支并列、解析纪律同源（读占用者 `/proc/<pid>/stat` 取 ppid）：`_parent_is_pid1`——ppid 为 1 即 unit 承载（`fenix-dashboard.service` 主进程 PPID 恒为 1），接管它会触发「手工实例接管 → systemd 拉回 → 反向接管」的生产实例闪断循环；`_parent_is_tmux_server`——`/proc/<ppid>/comm` 恰为 `tmux: server`，comm 可读但不匹配时回退父进程 cmdline，仅当 `argv[0]` basename 恰为 `tmux` 或以 `tmux:` 开头方命中。判定时机在占用者身份复核（starttime 锚定防 PID 复用误杀）通过之后、发送信号之前，父进程身份与占用者 pid 同源快照，不引入额外竞态窗口。
- 判定 fail-safe 方向：接管路径读不到占用者父进程身份（/proc 不可用、pid 已退出）按非常驻处理、走既有接管——fail-safe 偏向放行（无 systemd 拉回依托的实例收割后可随时重启重建，不破坏常驻形态）；两判据读取/解析失败返回 False 的纪律一致。
- 端口解析链为 `--port > dashboard.yaml port > config port > 8787`，仅对最终确定的单一端口做占用检测；端口冲突一律报错退出、不自动上探换端口，换端口由调用方自行决定（自动上探会让 URL 写死 8787 的验证流量打到常驻实例而非被测实例）。
- 启动失败的实例 MUST 在 5 秒内退出进程，不保留「已运行但未监听」的僵尸实例。
- claude 生命周期 watchdog（`_start_claude_watchdog`，防 agent 经 CLI nohup 临时自测的实例泄漏）只绑定进程环境带 `CLAUDE_PID` 的非长驻实例：unit 承载实例的进程环境经 EnvironmentFile 会话身份 denylist 剥离 `CLAUDE_PID`，watchdog 无绑定目标、长驻豁免成立；父进程为 tmux server 的实例（`_is_tmux_hosted` 判据）亦不装配，`CLAUDE_PID` 存在与否不影响。
- 判据禁令：MUST NOT 采用「argv 任一项含 `tmux` 子串」（以含 tmux 子串的包装脚本为父进程的 agent 自测实例会被误判常驻、漏掉防泄漏）；MUST NOT 采用「进程自身环境含 `TMUX`」（`TMUX` 会被 agent_runner 透传给 agent 子进程，agent 经 nohup 拉起的实例同样带 `TMUX`）。
- 未命中长驻豁免且进程环境带 `CLAUDE_PID` 的实例（agent 经 CLI nohup 拉起）：装配 watchdog 绑定 `CLAUDE_PID`，目标 claude 进程退出后实例自杀，避免孤儿泄漏。
- 入口双保险：常驻实例的启动入口不含 `CLAUDE_PID`——skill 与人工入口带 `env -u CLAUDE_PID`，unit 承载入口经 EnvironmentFile denylist 剥离（hook 的 `restart-dashboard` 经 `systemctl restart fenix-dashboard` 走 unit 环境生效），与父进程判据互为冗余。
- PDEATHSIG/孤儿拒启两道防线（`_bind_parent_lifecycle`，import 场景防泄漏）独立于本页 watchdog 判据，两者正交。
- 双向验证铁律：验证「分支/worktree 上的行为」打 worktree 自起实例（`python3 bin/fenix_dashboard.py --serve --port 8789`）——:8787 常驻进程内存是启动时刻旧码，吃不到分支改动；验证「dashboard 类 SPEC 交付的主树行为」目标恰是 :8787 常驻实例——静态资源实时读盘，重建 dist 后免重启生效，Python 读侧改动须重启才生效。1900x 端口段是 agent run 的隔离 dev-server，三类实例勿混用。
- 常驻实例重启协议按承载形态双轨：unit 承载走 `systemctl restart fenix-dashboard`，看现场 `journalctl -u fenix-dashboard` 加主树 `.fenix/logs/` 既有日志文件；tmux 托管兜底形态（unit 缺席，session `fenix-dashboard:0`）走 `tmux respawn-window -k -t fenix-dashboard:0`——respawn 沿用窗口原启动命令，`env -u CLAUDE_PID` 双保险与常驻形态一并保留。手工 `--serve` 会被接管豁免拒绝，不能替代任一轨重启。重启验证三件套——curl :8787 得 200、`/proc/<新pid>/environ` 无 CLAUDE_PID、API 读侧新字段有值（Python 读侧生效的直接判据；静态资源侧另核 dist 与源码一致）。
- 读侧字段缺失/恒旧先怀疑陈旧进程：前端正常渲染（dist 实时读盘）而 `/api/specs`、`/api/config` 等读侧字段缺失或恒旧，且同数据在全新进程直跑正常，即运行进程陈旧——`ps -o lstart` 对比主树合入时间钉死；修复走重启而非改 config.yaml 迁就旧视图（Python 读侧不重启恒旧视图）。
- 混代 500 与新端点 404 判读（进程陈旧的路由层签名）：承载实例只保证启动时刻装载的代码代际——代码已新增的端点在旧进程上返回路由层 404（`{"error": "Not Found"}`），新端点须承载进程重启后才上线；进程内模块代际还可不一致（routes 已见新路由而 `dashboard_data` 门面驻旧代、缺新导出符号），对新端点呈 AttributeError 500。判据与陈旧进程同一：同调用在当前代码副本全新进程直跑不复现、`ps -o lstart` 早于相关改动合入时刻——即判承载进程陈旧/混代，按承载形态重启（常驻走双轨重启协议，临时自测/验证实例重启换新代），MUST NOT 据症状改代码补符号或补路由。

## 溯源

- 2026-09-02 fix-dashboard-duration-and-verify-gate（spec/archive/2026-09-02-fix-dashboard-duration-and-verify-gate） — 建立端口独占与启动语义：旧实例接管、异主报错退出、5 秒僵尸退出
- 2026-09-26 fix-dashboard-watchdog-misfire（spec/archive/2026-09-26-fix-dashboard-watchdog-misfire） — watchdog 增加「tmux 承载即显式长驻、不装配」父进程判据（PPID comm 恰等匹配），禁 TMUX 环境变量与 tmux 子串误判路径；skill/agent/hook 入口补 `env -u CLAUDE_PID` 双保险
- 2026-10-07 fix-dashboard-resident-takeover（spec/archive/2026-10-07-fix-dashboard-resident-takeover） — 端口接管增加常驻豁免：tmux 承载占用者拒信号、报错退出（PID+换端口指引）；接管路径补占用者 ppid 判定与读取失败放行的 fail-safe 方向；非 tmux 旧实例接管语义不变
- 2026-11-04 memory-distill-ops-runbook（spec/knowledge/_inbox/done/memory-distill-ops-runbook.md） — 折叠验证与运维操作纪律：双向验证铁律（分支验证打 worktree 自起实例 / 主树交付验证打 :8787 / 1900x 为 run 隔离 dev-server）、tmux 重启协议与孤儿 server 变体、「显示未配置」先疑陈旧进程配方
- 2026-11-04 add-systemd-hosting（spec/changes/add-systemd-hosting） — 端口接管常驻豁免扩至 unit 承载实例（`_parent_is_pid1`，防「接管→systemd 拉回→反向接管」闪断循环）；常驻实例重启协议迁 `systemctl restart fenix-dashboard`（tmux kill-session/new-session 协议与孤儿 server 变体随 tmux 承载退役）；watchdog 长驻豁免经 unit 环境无 `CLAUDE_PID` 成立
- 2026-11-06 push-restart-unit-absent-tmux-stale-1106（spec/knowledge/_inbox/done/push-restart-unit-absent-tmux-stale-1106.md） — 重启协议改写为承载形态双轨（unit 缺席时 tmux 轨 `respawn-window -k` 配方为实测有效路径、验证三件套第三件改 API 读侧新字段有值）；陈旧进程判读一般化（读侧字段缺失/恒旧 + 全新进程对照正常 + `ps -o lstart` 对比合入时间）
- 2026-11-08 provfix-seed-fixture-residue-and-verify-instance-mixed-vintage-500（spec/knowledge/_inbox/done/provfix-seed-fixture-residue-and-verify-instance-mixed-vintage-500.md） — 陈旧进程判读扩到路由层签名：代码新端点在旧进程路由层 404（新端点须重启后上线）、混代「新路由在、门面新导出缺」AttributeError 500，判据仍为当前代码副本全新进程直跑不复现，修法重启承载进程勿改代码
