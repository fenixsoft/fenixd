## ADDED Requirements

### Requirement: 处置活动不得计入被处置 SPEC 的驱动证据

`_has_recent_spec_run`（`core/admin_monitor.py` 模块级）与 `AdminMonitor._has_recent_progress`（同源实现）判定「某 SPEC 是否有近期写活动」时，MUST 排除 `admin-` 前缀的 run 文件——Administrator 的处置 run 是**处置者**的活动，不是被处置 SPEC 的验证/实现驱动证据。判定口径 MUST 为「该 SPEC 是否存在**非 admin 前缀**的、写活动在宽限窗内的 run 文件」。

`spec_is_undriven` 与 `event_bus._recover_testing` 的条件 ① MUST 相应回归「真无驱动」语义：仅有 admin run 活动时，该 SPEC MUST 判为无驱动（不再被处置者的 run 文件挡住）。

#### Scenario: 仅有 admin run 活动时判为无驱动

- **WHEN** 某 SPEC 处于 testing，其 `.fenix/runs/` 下只有 `admin-<spec>-<ts>.jsonl` 的 mtime 在宽限窗内，且无存活 agent 子进程、无待派发条目
- **THEN** `spec_is_undriven(project_root, spec, entry)` MUST 返回 `True`
- **AND** `_has_recent_spec_run(project_root, spec, now, grace)` MUST 返回 `False`

#### Scenario: 非 admin 前缀 run 活动仍判为有驱动

- **WHEN** 该 SPEC 同时存在 mtime 在窗内的 `impl-<spec>-<ts>.jsonl`（或 `verify-` / `repair-` 等非 admin 前缀）
- **THEN** `_has_recent_spec_run` MUST 返回 `True`
- **AND** `spec_is_undriven` MUST 返回 `False`

#### Scenario: admin run 过期后不影响判定

- **WHEN** 该 SPEC 的 admin run 文件 mtime 已超出宽限窗，且无其他前缀 run 活动
- **THEN** 判定结果与「无任何 run 文件」逐位一致（`_has_recent_spec_run` 返回 `False`）

### Requirement: verifier 重验派发与在飞 Administrator run 互斥

`event_bus._recover_testing` 与 `admin_monitor` 孤儿复位路径派发 verifier（`handle_event("spec_implemented", ...)`）前，MUST 检查该 SPEC 是否存在在飞或待派发的 Administrator run；存在时 MUST 跳过本次重验派发并记日志，MUST NOT 起 verifier run。

判定 MUST 覆盖该 SPEC 的**任意** signal_type：新增 `AdminMonitor._has_active_admin_run_for_spec(spec)`，复用既有 `_has_active_admin_run_for` 的 by_run 归并口径（某 `admin_run_id` 组 `has_pending` 且无终结兄弟记录）但**去掉** signal_type 过滤——按 `(spec, signal_type)` 精确匹配会漏 `verify_env_blocked` / `manual-intervention` / `stuck` 等非 orphaned_state 处置。既有带 signal_type 的版本语义不变、调用点保持不动。

同一在飞判定 MUST 同时用于**抑制重复唤起 Administrator**：`AdminMonitor._handle_signal` 在唤起前（`_invoke_administrator` 之前）检查该 SPEC 是否存在在飞 admin run，存在则跳过本次唤起并记 INFO/WARNING（信号仍按既有沉淀/节流语义落 store）。依据：`_has_active_admin_run_for` 当前**仅**在 `_recover_orphaned_dispositions` 内使用（`core/admin_monitor.py:1819`），唤起路径无任何在飞去重；而 D1 生效后，处置中的 SPEC 会在 escalation 冷却窗（缺省 60 分钟）过期后重新成条，无本守卫即产生与在飞处置**并行**的第二个 Administrator run。

判定 MUST 采用 fail-open：admin 在飞判定本身异常时按「无在飞 admin」放行（与既有恢复路径容错语义一致），异常须记 WARNING。

#### Scenario: admin 处置在飞时跳过重验派发

- **WHEN** 某 testing SPEC 被判为无驱动（缺口 A 修复后），但同 SPEC 任一 signal_type 名下有 `has_pending` 且无终结兄弟记录的在飞 admin run（含 `orphaned_state` / `verify_env_blocked` / `manual-intervention` / `stuck`）
- **THEN** 恢复路径 MUST NOT 派发 verifier
- **AND** MUST 记 INFO/WARNING 日志说明「admin 处置在飞，跳过重验派发」

#### Scenario: admin 处置在飞时抑制重复唤起

- **WHEN** 某 SPEC 已有在飞 admin run，且该 SPEC 的新信号通过了既有节流判定（冷却窗已过期）
- **THEN** `_handle_signal` MUST NOT 唤起第二个 Administrator run
- **AND** MUST 记 INFO/WARNING 日志说明「已有在飞处置，跳过重复唤起」
- **AND** 该信号仍按既有沉淀/节流语义落 store（不丢痕）

#### Scenario: admin 判定异常时 fail-open 放行

- **WHEN** admin 在飞判定抛出异常（如 store 不可读）
- **THEN** 恢复路径 MUST 记 WARNING 并继续派发 verifier（不因守卫故障阻断恢复）

#### Scenario: 无在飞 admin 时正常派发

- **WHEN** 该 SPEC 被判无驱动且无在飞 admin run
- **THEN** 恢复路径 MUST 照既有语义派发 verifier（`spec_implemented` → 入队）

### Requirement: 场景原地修复预算耗尽必须有显式重验日程

`_handle_scenario_repaired` 的预算耗尽分支（`_repair_depth >= _SCENARIO_REPAIR_MAX_ROUNDS`）MUST NOT 只写 error 后静默干等。判定 MUST 按跨轮持久计数 `_scenario_repair_exhausted_rounds` 分两态处置：

- **首次耗尽**（计数为 0）→ MUST 落一个**显式、可观测的重验日程**（排程定时重入 + `_dispatch_backoff_until` 兜底，见 design D3），SPEC 保持 testing，计数递增为 1，MUST NOT 升级人工、MUST NOT 原地重入。
- **再次耗尽**（计数 `>= 1`）→ MUST 走既有升级通道呼叫人工（保持 testing），MUST NOT 再排程。

判定「是否首次耗尽」MUST 在**写 error 文案之前**完成：既有实现先以同一文案覆盖 error（`core/pm_engine/verification/pipeline.py:988-995`），若不先读计数并把首次态文案与再次态文案分开写，首次排程的「下次重验时刻」会立即被既有「等待下一轮重验」文案覆盖，本 Requirement 的**可观测**目标（Design D5）落空。

排程 MUST 幂等：同一 SPEC 在同一耗尽态下重复进入本分支 MUST NOT 排多个重验定时器（设计取 `_dispatch_backoff_until` 已生效即视为已排程，或等价的 per-spec 判重集合）。

排程到期 MUST 触发一次重验（等价 `_recover_testing` 的 `spec_implemented` 语义），且该次重验 MUST 重新获得完整的 `_SCENARIO_REPAIR_MAX_ROUNDS` 修复预算。排程回调与 `_dispatch_backoff_until` 到期后的周期兜底（`_recover_testing`）**两者皆可能触发**，实现 MUST 依赖既有 `_enqueue` 按 `(spec, agent_type)` 去重与 `_process_queue` 的 `_dispatch_backoffed` 门（`core/pm_engine/dispatch/queue.py:228/312`）保证只起一次 verifier run——MUST NOT 依赖「两者只触发其一」这一不成立的前提。

`_scenario_repair_exhausted_rounds` MUST 与 `_judge_rerun_count` 同生命周期：仅在 `verified` 落定与人工 `unfreeze_spec` 两处清零；MUST NOT 在其他中间转换（含 admin 处置复位）清零。

#### Scenario: 首次预算耗尽排程一次重验

- **WHEN** judge 申报 `scenario-repaired` 而 `_repair_depth >= _SCENARIO_REPAIR_MAX_ROUNDS`，且 `_scenario_repair_exhausted_rounds` 为 0
- **THEN** SPEC MUST 保持 testing，error MUST 说明「已排程重验」（含可读的下次重验时刻）
- **AND** `_scenario_repair_exhausted_rounds` MUST 递增为 1
- **AND** MUST 存在已生效的重验日程（定时器 + `_dispatch_backoff_until`）
- **AND** MUST NOT 调用 `escalation_notifier`

#### Scenario: 再次耗尽升级人工

- **WHEN** 同 SPEC 再次进入预算耗尽分支，且 `_scenario_repair_exhausted_rounds >= 1`
- **THEN** SPEC MUST 保持 testing
- **AND** MUST 调用 `escalation_notifier` 升级人工（signal_type 属既有场景缺陷族）
- **AND** MUST NOT 再新增重验日程

#### Scenario: 重验轮重新获得完整修复预算

- **WHEN** 首次耗尽排程的重验被触发、进入新一轮三阶段验证
- **THEN** 该轮的 `_repair_depth` MUST 从 0 起算，即可再次获得 `_SCENARIO_REPAIR_MAX_ROUNDS` 次修复机会

#### Scenario: verified 落定清零耗尽计数

- **WHEN** 该 SPEC 验证通过（`status == "verified"`）
- **THEN** `_scenario_repair_exhausted_rounds` MUST 被清零

#### Scenario: 人工解冻清零耗尽计数

- **WHEN** 人工调用 `unfreeze_spec`
- **THEN** `_scenario_repair_exhausted_rounds` MUST 被清零

#### Scenario: admin 处置复位不清零耗尽计数

- **WHEN** admin 处置收尾走复位直通道（`transition_gate(testing)`）或孤儿复位
- **THEN** `_scenario_repair_exhausted_rounds` MUST 保持原值（生命周期累计语义）
