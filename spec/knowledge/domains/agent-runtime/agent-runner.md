<!-- knowledge: capability=agent-runner rev=1 sources=spec/archive/2026-09-22-evo-sigterm-source-tracking-cooldown -->

# Agent 进程托管与信号处理

`core/agent_runner` 对 CLI 子进程终结的归属判定与信号死法熔断：信号致死不再一律归为 provider 瞬态。

## 现行规则

- 死法归属闭集：子进程终结按闭集判定——
  - 框架自身终止（cancel 旗标 → `RunCancelledError`；supervision 超时/轮次上限 kill，returncode=-9 且错误文本 `Timeout after …` / `Max turns …`）维持既有语义，不打信号来源标签、不计入信号通道（框架自己强杀不得冷却链路）；
  - daemon 关停（shutting_down 置位 / 产物 interrupted 标记）沿用 `[shutdown-interrupted]` 守卫语义；
  - 其余信号致死（returncode 143 或负信号）归类为带信号来源标签的错误（形如 `[signal-kill: SIGTERM/143]`、`[signal-kill: SIGKILL/-9]`），在 run 错误文本、日志与告警 evidence 中透出来源，不归 `[provider-transient]`。
- 来源只由可实测三源推导：shutting_down 旗标、产物 interrupted 标记、框架自身终止留痕；无判别力时标 `unknown` 并如实携带 returncode，不猜测声称 external-kill。
- 信号死法熔断冷却：信号死法失败（143/-9）计入信号类熔断计数，同 spec 连续达阈值（3）触发该 spec 冷却——冷却期内该 spec 重派被跳过（不无限原地重试），到期自动恢复，涵 admin/impl 处置 run 路由。爆炸半径限于该 spec：不复用、不触发全局瞬断指纹熔断通道（`record_transient_error` / `_transient_break_until`）。与既有秒挂冷却（`_record_instant_fail`）同一事件允许累加，但冷却截止时间取更晚者生效、不相互覆盖。
- 产物硬门失败通道隔离（非内容/非网关质量失败不进全局瞬断指纹）：
  - 任务完成度类（`[task-gate]` 前缀：tasks.md 未勾任务 / completed_tasks 不一致 / partial 申报不一致）不注入 `[provider-transient]` 标签、不就地消耗瞬态退避预算；重试由 gate 降级语义（`TASK_GATE_DEGRADE_THRESHOLD=2`）与 attempt 层重试承担；
  - 结构类（结果文件缺失/为空/非法 JSON/顶层非对象/status 白名单外，无前缀）保留原地退避重试与 `[provider-transient]` 标签，另带结构类归因标签，仅停止全局瞬断指纹记账。

## 溯源

- 2026-09-02 史前复原 — 迁移期已存在的基线：core/agent_runner.py 以非交互式 Claude 会话驱动 agent 执行，run 转录流式落盘供回读取证
- [2026-09-22 evo-sigterm-source-tracking-cooldown](spec/archive/2026-09-22-evo-sigterm-source-tracking-cooldown/) — 固化信号死法三源归属闭集与 signal-kill 标签、同 spec 信号熔断冷却（覆盖处置 run 路由）、产物硬门两类失败与全局瞬断指纹的通道隔离
