# 可观测缺口治理（指标落盘 / 转换 context / 审计窗口）
<!-- knowledge: capability=observability-gaps rev=1
     sources=spec/archive/2026-09-22-fix-observability-gaps -->

补齐三处结构性观测失真：run 耗时/成本指标落盘、状态转换日志带结构化上下文、审计窗口与日志双写治理。

## 规则

- **run 终止指标结构化落盘**：每次 agent run 进入终态时记录一条结构化指标，至少含 `run_id`、`spec`、`agent_type`、`duration_seconds`、`turns`、token 用量分项（可得时）、`cost_usd`（可得时）、`terminal`（终态类型）、`provider`。成功与失败/超时 run 均落盘；不得仅依赖 run 文件 mtime 推算耗时；查询历史耗时/成本直接读落盘指标，无需事后扫描 run 产物。
- **状态转换日志带结构化 context**：`transition()` / `transition_gate()` 的每次显式状态转换在日志携带结构化 context，至少含触发转换的 `trigger_run_id`（可得时）、`agent_type`（可得时）、`channel`（区分自动调度/人工操作/恢复等来源）。
- **转换范围界定**：幂等短路（old_status == new_status）不产生 `Transition:` 日志行，不在本能力覆盖范围；`update_spec` 直写 status（打回路径、admin 置状态）不经 transition，不产生 `Transition:` 日志行，其上下文由 `Updated SPEC` 日志行的 `context.updates` 承载，时间轴读侧据此重建。
- **时间轴优先消费结构化事件**：dashboard 时间轴优先用状态转换日志的结构化 context 重建转移事件；对无 context 历史日志的 message 正则匹配保留为兜底，不因缺失 context 丢失历史转移。
- **审计保留窗口**：`admin_state_history.json` 对 ready/implementing 状态变化的保留窗口不小于 24 小时（非这两个状态的转换不在本要求范围）；告警历史的保留上限与运维复盘需求相称，并在配置或文档中明确。
- **supervisor 日志不得双写**：记录函数不得同时 print 与写文件到同一路径；日志文件每事件一行。

## 溯源

- [2026-09-22 2026-09-22-fix-observability-gaps](spec/archive/2026-09-22-fix-observability-gaps/) — 新增 run 终止结构化指标落盘、Transition 日志结构化 context 与时间轴结构化消费优先、审计保留窗口下限与 supervisor 双写修正。
