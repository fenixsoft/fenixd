# ADR-103：轮次上限活性续期矩阵，强杀收口接 WIP 保全

date: 2026-09-17
status: accepted

## Context

turn-limit（Max turns reached）强杀是三不管死法：未提交现场不保全、健康推进被无差别腰斩（实证第 378 轮仍在正常勾选任务）、消耗按零记账。超时路径已有「extend 有据、封顶有限、每次留痕」的封闭续期矩阵先例；WIP 检查点已有排水 / 瞬断退避两个锚点，共用「可证明静默窗口」前提。

## Decision

- turn-limit 命中不再无条件 kill：按封闭矩阵判定——run 表现真实推进活性（判定窗口内分支有新提交，**或**有新 tool_result 事件流量，任一即活性）且续期未封顶 → 按固定步长（max_turns 的 25%）extend 上限量，以 `turn_extension` 事件落 run 文件留痕（含序号 / 步长 / 证据摘要 / 新上限）；无活性或封顶才 kill。与超时矩阵同构但计数相互独立、事件 type 分流，读侧零改动。
- 强杀收口点接 WIP 保全（新锚点）：调用点钉在「proc 终止 + 读线程 join 后」——可证明 agent 不再写盘的静默窗口，与既有锚点同前提；kill 前提交被否决（agent 尚在写盘，会提交半写文件）。turn-limit 与 timeout 两条强杀路径共用同一收口方法。
- 强杀路径消耗记账区分「unobserved」与「zero」：usage 不可观测时打 unobserved 标识，日志不得写「counted as 0」；STATE 累计保持不伪造原则——无可展示的真实数字就不展示，不新增展示字段。

## Consequences

- 健康长任务不再被腰斩；无活性 run 一次续期都拿不到。最坏墙钟增幅有界（步长 25% × 封顶 2 次，仅对真活性 run 发生）。
- WIP 保全窗口族扩展到强杀收口；锚点产生的 `fenix(wip):` 提交由 merge-back 前既有塌缩机制清理，零新增塌缩逻辑。
- 活性判定引入的 git 子进程调用只在触发判定时执行，不进常规轮询周期。

## 补充注记（evo-add-impl-run-budget-sizing，2026-10-03）

本 SPEC 是对 ADR-103 的**补充而非修订**：除下述缺省关闭的守卫外，续期矩阵的 extend/kill 语义与本 ADR 的 Decision 逐位一致。

- **观测面新增字段（不参与判定语义）**：`turn_extension` 事件新增 `remaining_tasks`（判定时点 main 树 tasks.md 剩余未勾选任务数，缺失记 `unavailable`/None——附加不替换，既有字段与读侧零改动）；`run_metrics` 事件同键新增 `remaining_tasks`（run 收尾时点快照）与整 run 累计簿记占比观测（`tool_uses` 直方图中 TaskCreate+TaskUpdate 占全部工具调用比，≥ 阈值仅在轮次上限判定点 WARNING + evidence 注记，不改 extend/kill 结论）。
- **STATE 新增 per-spec 覆写键 `impl_turn_cap_override`**（正整数）：run 启动点生效轮数上限的覆写入口，优先级高于按 spec 规模分（`estimate_spec_scale`）的 `suggested_turn_cap_for_scale` 推算（enabled 且规模分严格大于 `full_scale_threshold` 时抬到 max(base, suggested)，只抬不压）；仅实现车道（implementer / fast-track）参与推算与覆写。
- **kill_early 末位扩容拆停守卫（缺省关闭，仅实现车道）**：`agents.turn_budget_sizing.kill_early.enabled` 为 true、且本次判定恰为最后一次可用扩容（extension_index+1 == TURN_EXTENSION_MAX）、且剩余未勾选任务数 ≥ `remaining_tasks_threshold`、且 run 期间勾选进度 ≤ `progress_floor`（启动点快照后新勾 ÷ 启动时未勾；分母 0 或无基线不判）四条件全满足时，提前返回 kill 并复用既有 turn-limit kill 收口（含 WIP 保全锚点），不新增收口实现——相当于把本 ADR「末位续期」中 renewal unlikely to finish remaining work 的那一段，从「有活性即续」收窄为可配置的提前止损；enabled 为 false（含缺省）时对任意输入的结论与引入前逐位一致。
