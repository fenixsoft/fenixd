## Why

2026-09-18 `add-spec-manual-activation` 事故暴露恢复路径的两个闭环缺陷——它们不改变任何产品行为，却让「本可自愈」的 spec 每轮必然唤起一次 Administrator（每次 ~$2、~75 分钟），且把两次「预算耗尽」错误地定性为终局：

1. **处置者被当成驱动证据（缺口 A）**：`admin-<spec>-<ts>.jsonl` 经 `AdminMonitor._spec_from_run_id` 归到被处置的 spec（`admin-` 在 `RUN_ID_AGENT_PREFIXES` 内），而 `_has_recent_spec_run` 对该 spec 的**任意前缀** run 文件判活跃。于是 Administrator 处置某 spec 的**全过程**中，该 spec 永远满足「有近期写活动」→ `spec_is_undriven` 条件 ① 恒假 → `event_bus._recover_testing` 与 `admin_monitor` 孤儿探测双双跳过它。实测：spec 因预算耗尽停在 testing（10:21），10:41 成 orphaned_state 信号唤起 admin，admin 跑了 75 分钟（233 轮），期间 STATE 停在 testing/error=null/tester_run=null、**任何恢复路径都不动它**——不是没人管，是判定说「有人管」。

2. **预算耗尽无重验日程（缺口 B）**：`core/pm_engine/verification/pipeline.py` 的 `scenario-repaired` 预算耗尽分支（`_handle_scenario_repaired` 内 `_repair_depth >= _SCENARIO_REPAIR_MAX_ROUNDS`）只写 error「保持 testing 等待下一轮重验」并 return——**没有任何「下一轮」日程**：既不写 `_dispatch_backoff_until`、也不排定时器、也不入派发队列。testing 态的唯一驱动是 `event_bus._recover_testing`，它只在 30 分钟的 full_scan 里跑；15 分钟的 orphaned_state 阈值天然先到，于是**每一轮预算耗尽都必然成一条 orphaned_state 信号**（本 spec 与 `fix-verify-serving-disk-reclaim` 反复成条的同一根因族）。当日更重的叠加：那轮 full_scan 被**阻塞式派发**占住（py-spy 实证 scanner 线程栈停在 `_run_claude` → `run_spec_review` → `_on_spec_reviewing` → `full_scan`），recovery 整轮回调延迟。

两者的共同后果：**一个「修复已落盘、只差重验」的 spec，被两次误判拖成 75 分钟人工等待**。缺口 A 使处置期间无法自愈；缺口 B 使处置结束后仍无确定性重验时刻。

## What Changes

- **缺口 A — admin run 不再计入驱动证据**：`_has_recent_spec_run`（及其 `AdminMonitor._has_recent_progress` 同源实现）跳过 `admin-` 前缀的 run 文件——Administrator 的处置活动**不是**被处置 spec 的验证驱动证据。判定口径改为「该 spec 是否存在非 admin 前缀的近期 run 文件」。
- **缺口 A — 补并发守卫**：`event_bus._recover_testing` 与 `admin_monitor` 孤儿复位派 verifier 前，检查该 spec 是否存在**在飞或待派发的 Administrator run**（复用 `AdminMonitor._has_active_admin_run_for`）；有则跳过本次重验派发——避免「admin 正在写 STATE/修场景文件」与「verifier 同时读同一批产物」的竞态（admin 处置常写 `test_scenarios.json` 与 spec 状态）。
- **缺口 B — 预算耗尽给出显式重验日程**：`_handle_scenario_repaired` 预算耗尽时不再只写 error 干等：
  - **首次耗尽**（新增跨轮持久计数 `_scenario_repair_exhausted_rounds == 0`）→ 写显式重验日程（排程定时器 + `_dispatch_backoff_until` 兜底，见 design D3），保持 testing 并留痕；**不升级人工**。
  - **再次耗尽**（计数 `>= 1`，即已给过一次重验仍不收敛）→ 走既有升级通道（`escalation_notifier`，signal_type 复用既有场景缺陷族），保持 testing，等待人工裁决。
  - 新增计数与 `_judge_rerun_count` 同生命周期：`verified` 落定与人工 `unfreeze_spec` 两处清零（防止「毒 spec 借重验日程无限循环」）。
- **成本与可观测**：两条缺口修复后，「预算耗尽 → 重验」不再必然产生 orphaned_state 信号与 Administrator run；首次耗尽路径只消耗一次排程与一轮验证。

## Capabilities

### New Capabilities

- `recovery-path-liveness`: 恢复路径的活性判定与推进日程——（a）Administrator 处置活动不得被误判为被处置 spec 的驱动证据，且派发 verifier 前必须与该 spec 的在飞 admin run 互斥；（b）场景原地修复预算耗尽必须落一个显式、可观测的重验日程，连续耗尽才升级人工。

### Modified Capabilities

<!-- 无：本 SPEC 只新增判定与日程，不修改既有能力的 Requirement 语义（既有 orphaned_state / scenario-repaired 通道行为在「非 admin 处置 / 首次耗尽」样例下逐字节不变）。 -->

## Impact

- **改动点**：
  - `core/admin_monitor.py` — `_has_recent_spec_run`（模块级）与 `AdminMonitor._has_recent_progress`（两处同源实现）加 `admin-` 前缀排除；孤儿复位路径复用 `_has_active_admin_run_for` 作并发守卫。
  - `core/event_bus.py` — `_recover_testing` 补 admin 并发守卫（派发前查在飞 admin run）。
  - `core/pm_engine/verification/pipeline.py` — `_handle_scenario_repaired` 预算耗尽分支改为「首次排程 / 再次升级」两态；新增计数读写。
  - `core/pm_engine/verification/escalation.py` — 若重验日程排程器落在此处（design 定），同步常量与调用。
  - `core/state_machine.py` — 新增 `_scenario_repair_exhausted_rounds` 字段名常量（与既有 `_judge_rerun_count` 同族）与 `verified` / `unfreeze_spec` 清零点。
- **行为影响**：预算耗尽的 spec 首次进入显式重验日程（更快、可观测）；admin 处置期间的 spec 恢复判定回归「真无驱动」语义；不改变非 admin 处置路径与正常验证链任何样例。
- **不涉及**：不改变 `_SCENARIO_REPAIR_MAX_ROUNDS` 的数值语义（本轮该值已由既有提交改为 3，属独立变更）；不修改前端；不引入新配置键（日程时长若需可配置，走既有 `agents.*` 命名，见 design）。

## Non-Goals

- **不修「扫描线程被阻塞式派发占住」**：py-spy 实证的 `full_scan` 同步等 run 问题（导致 30 分钟周期实际退化为「30 分钟 + 最长 run 时长」）是独立缺口，本 SPEC 不覆盖——见 design Risks 登记。
- **不减少升级人工的次数本身**：仅消除「必然升级」的两次误判；真收敛失败仍需人工裁决。
- **不改 `evo-scenario-defect-reroute-stoploss` 的作用面**：该 SPEC 处理「改道无效仍烧改道预算」，与本 SPEC 的「预算耗尽无日程」相邻但不同（不同判据、不同分支）。
