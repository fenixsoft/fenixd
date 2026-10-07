# 实现 run 轮数预算规模推算
<!-- knowledge: capability=impl-run-budget-sizing rev=1 sources=spec/archive/2026-10-08-evo-add-impl-run-budget-sizing -->

实现车道 run 的轮数预算按 spec 规模 sizing：启动期推算建议上限（STATE 可覆写）、扩容判定与事件携带剩余工作量观测、末位扩容可提前收口（缺省关闭）。除缺省关闭的守卫外，活性续期矩阵的 extend/kill 判定语义与 ADR-103 逐位一致。

## 规则

### 启动期生效上限

- 生效序固定为 override > 推算 > base：STATE per-spec 覆写键 `impl_turn_cap_override`（仅接受正整数；bool、非数字字符串、非正整数一律等价无覆写，STATE 缺失或读取异常同样等价无覆写，不放大为 run 故障）优先；否则按规模推算；两者皆缺时等于基础值 `agents.max_turns`。启动日志记录 base / override / effective 三元组。
- 规模推算：`estimate_spec_scale` 规模分（未勾选任务 ×1 + 非引用交付物 ×2）**严格大于** `full_scale_threshold`（缺省 45）时，生效 `max(base, suggested_turn_cap)`（缺省 800）——推算只抬不压，建议值低于 base 时维持 base，规模分等于阈值不抬。推算仅在 `agents.turn_budget_sizing.enabled`（缺省 true）开启时参与；覆写优先级高于推算，不受该开关门控。
- 解析异常保守回退：spec 目录或 tasks.md 缺失、读取或估算失败时回退 base 值，WARNING 留痕，不阻断派发。
- 车道限定：推算抬升、覆写消费与启动进度快照仅对实现车道（implementer / fast-track）生效；dispute-judge / spec-review 等评审与裁决车道维持各自读点的 base 值，不参与推算、也不取进度快照。

### 扩容判定观测面（恒开）

- 轮次上限判定点读取两个观测维度：剩余未勾选任务数——`run_task_track.parse_tasks_md` 单点解析、project_root 主树 tasks.md 口径（与完成度门禁同源，禁止第二套正则），缺失或解析失败记 None 并在 evidence 注明 unavailable；簿记占比——run 累计口径（TaskCreate+TaskUpdate ÷ 全部工具调用），派生自 run_metrics 的 tool_uses 累计直方图，不新增转录扫描。
- extend 与 kill 的 evidence 均拼接 `remaining_tasks=<n>`；`turn_extension` 事件与 run_metrics 记录新增 `remaining_tasks` 字段（附加不替换，既有字段与读侧零改动）。
- 簿记占比 ≥ `bookkeeping_share_threshold`（缺省 0.5）时只写 WARNING 并在 evidence 注记占比值，不得因此单独改变 extend/kill 结论——占比高是低效/打转信号而非失败证据，大 spec 首轮建任务簿记天然偏高。
- 观测面不受 `enabled` 门控：remaining_tasks 观测与簿记占比 WARNING 恒开；评审/裁决车道同样获得观测字段，只是无推算抬升与守卫。

### 末位扩容拆停守卫（kill_early，缺省关闭）

- `kill_early.enabled` 缺省 false；关闭时轮次上限判定与无此机制逐位一致（同输入同输出，新字段只增不改）。
- 开启且仅实现车道生效，以下条件同时成立才提前 kill：本次判定恰为最后一次可用扩容（extension_index 将达 `TURN_EXTENSION_MAX`=2；扩容已封顶时无条件 kill，封顶语义优先于守卫）；剩余未勾选任务数 ≥ `remaining_tasks_threshold`（缺省 10）；run 内勾选进度 ≤ `progress_floor`（缺省 0.1）。进度 = 启动时点快照后新勾选任务数 ÷ 启动时未勾选任务数，分母为 0 视为进度健康不判不济，无启动基线保守跳过。命中时 evidence 注明 early-split 依据与 remaining_tasks。
- 收口复用既有 turn-limit kill + WIP 保全路径，不新增收口实现。

### 配置

- 配置键族 `agents.turn_budget_sizing.{enabled, full_scale_threshold, suggested_turn_cap, bookkeeping_share_threshold, kill_early.{enabled, remaining_tasks_threshold, progress_floor}}`，缺省 true / 45 / 800 / 0.5 / false / 10 / 0.1。归一化单点 `get_turn_budget_sizing_config`（core/fast_track_result.py，非法值逐项回退缺省，与设置界面读侧同源）；推算单点 `suggested_turn_cap_for_scale`；规模与进度解析禁止再造第二套 tasks.md/交付物实现。

## 溯源

- 2026-10-08 evo-add-impl-run-budget-sizing（spec/archive/2026-10-08-evo-add-impl-run-budget-sizing） — 新增本页全部规则：启动期规模推算与覆写生效序（只抬不压）、扩容判定/turn_extension/run_metrics 的剩余工作量与簿记占比观测面（只观测不改判）、末位扩容拆停守卫 kill_early（缺省关闭）
