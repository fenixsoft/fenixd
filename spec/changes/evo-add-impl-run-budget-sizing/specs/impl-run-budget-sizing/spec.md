# spec: impl-run-budget-sizing

## ADDED Requirements

### Requirement: 实现车道启动时按规模推算轮数上限

实现 run（implementer / fast-track 及一切消费 `agents.max_turns` 的工作车道）启动时，生效轮数上限按序确定：STATE 中该 spec 的 `impl_turn_cap_override`（正整数）优先；否则按 `estimate_spec_scale` 规模分推算——规模分大于 `agents.turn_budget_sizing.full_scale_threshold`（缺省 45）时生效 `agents.turn_budget_sizing.suggested_turn_cap`（缺省 800）与基础值中的较大者，否则等于基础值。规模解析异常（tasks.md 缺失/IO 失败）保守回退基础值，不阻断派发，WARNING 留痕。启动日志记录 base / override / 生效值三元组。

#### Scenario: 大规模 spec 启动获得更高轮数上限

- **WHEN** `agents.max_turns` 为 400，`agents.turn_budget_sizing.enabled` 为 true，spec 的 estimate_spec_scale 规模分为 118（大于缺省阈值 45）
- **THEN** 该 run 生效轮数上限为 800，启动日志含 `base=400 override=None effective=800`

#### Scenario: 小规模 spec 行为不变

- **WHEN** spec 规模分 ≤ full_scale_threshold
- **THEN** 生效轮数上限等于 `agents.max_turns` 原值，日志记 `effective` 与 base 相等

#### Scenario: spec 级覆写优先于规模推算

- **WHEN** STATE 中 `impl_turn_cap_override` 为 1200 且规模分大于阈值
- **THEN** 生效轮数上限为 1200，日志记 `override=1200`

#### Scenario: 规模解析异常保守回退

- **WHEN** spec 目录或 tasks.md 读取失败
- **THEN** 生效轮数上限等于 `agents.max_turns`，写 WARNING，派发不被阻断

### Requirement: 扩容判定与事件携带剩余工作量

`_turn_limit_action` 判定时读取剩余未勾选任务数（core/run_task_track.parse_tasks_md，project_root 口径；缺失或解析失败记 None 并在证据中注明 unavailable）与簿记占比（run 文件尾窗内 TaskCreate+TaskUpdate 占全部工具调用比）。extend 与 kill 的 evidence 拼接 `remaining_tasks=<n>`；`turn_extension` 事件与 run_metrics 新增 `remaining_tasks` 字段。簿记占比 ≥ `agents.turn_budget_sizing.bookkeeping_share_threshold`（缺省 0.5）时写 WARNING 并在 evidence 注记，但 MUST NOT 因此单独改变 extend/kill 结论。剩余工作量字段只增观测面，不改变既有活性矩阵的判定语义。

#### Scenario: 扩容事件记录剩余任务数

- **WHEN** 判定为 extend 且 tasks.md 解析得剩余未勾选任务 20 条
- **THEN** 落盘的 turn_extension 事件含 `remaining_tasks: 20`，evidence 含 `remaining_tasks=20`

#### Scenario: tasks.md 不可得时不误判

- **WHEN** 判定时 tasks.md 缺失
- **THEN** 事件 `remaining_tasks` 为 null，evidence 注明 unavailable，extend/kill 结论与无该字段时一致

#### Scenario: 簿记占比异常只留痕不改判

- **WHEN** 尾窗内 TaskCreate+TaskUpdate 占工具调用比 ≥ 0.5 且分支活性成立
- **THEN** 写 WARNING 与 evidence 注记，判定仍为 extend

### Requirement: 末位扩容拆停守卫缺省关闭且开启时保守判定

`agents.turn_budget_sizing.kill_early.enabled` 缺省 false。关闭时 `_turn_limit_action` 决策与现状逐位一致（同输入同输出，新字段只增不改）。开启时，仅当到达最后一次可用扩容（extension_index 将等于 TURN_EXTENSION_MAX）且剩余未勾选任务数 ≥ `kill_early.remaining_tasks_threshold`（缺省 10）且本次 run 期间任务勾选进度占比 ≤ `kill_early.progress_floor`（缺省 0.1）时，判 kill 并在 evidence 注明 early-split 依据；收口必须复用既有 turn-limit kill + WIP 保全路径，不新增收口实现。

#### Scenario: 缺省关闭时零行为变化

- **WHEN** kill_early.enabled 为 false（含缺省）
- **THEN** 相同输入下 extend/kill 结论与引入本机制前逐位一致

#### Scenario: 开启且续期不济时提前收口

- **WHEN** kill_early.enabled 为 true，第 2 次扩容判定点剩余任务 25 条、run 期间勾选进度 0.05
- **THEN** 判定 kill，evidence 含 early-split 与 remaining_tasks，run 经既有 WIP 保全收口

#### Scenario: 开启但进度健康时不提前收口

- **WHEN** kill_early.enabled 为 true，末次扩容判定点剩余任务 25 条但勾选进度 0.6
- **THEN** 判定仍为 extend（对齐 ADR-103「不腰斩健康推进 run」不变量）