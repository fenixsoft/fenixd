# Design: fix-judge-budget-counters-alignment

## Context

两套预算的现状：
- **场景修复预算**：`_SCENARIO_REPAIR_MAX_ROUNDS = 3`（`core/state_machine.py:700-707` 单点定义，注释明言由 `pm_engine.verification` 的 pipeline.py 与 escalation.py 共用消费）。耗尽处置在 `escalation.py:2693` `_escalate_scenario_repair_exhausted`（首耗尽排程重验；`_scenario_repair_exhausted_rounds >= 1` 再耗尽转人工）。预算按 episode 生效——排程重验新 episode 的 judge 仍可修复（round 4 实证修了 8 个场景并申报 scenario-repaired）。
- **重跑硬上限**：`_judge_rerun_count`（judge_gate.py:632）**生命周期累计**，`> 5` 即 `_judge_hard_cap_freeze` 冻结（add-command-center 6/5 冻结实证）。

两套预算的累计口径不同（episode vs 生命周期）、互不知情：修复机制自认预算内，冻结却由生命周期计数触发。另实证「耗尽状态持久性」存疑：round 3 已排程「不再重入」，daemon 重启后 round 4 照样修复——耗尽闸门要么在内存、要么被恢复路径清除，须以 STATE 持久字段为准。

## Goals / Non-Goals

**Goals:**
- 修复预算耗尽后修复通道持久关闭（跨重启），「不再重入」承诺兑现
- 硬上限冻结告警携带修复历史，人工裁决不需要再翻日志

**Non-Goals:**
- 不改 `_SCENARIO_REPAIR_MAX_ROUNDS` 数值与 per-episode 修复预算本身（人工解冻重获预算的既有语义保留）
- 不改重跑硬上限生命周期语义与上限值（清零出口由 fix-unfreeze-judge-counter-reset 补齐）
- 不动 verdict 稳定性复用与轮内停派两级节流

## Decisions

- **D1 修复通道门挂在 scenario-repaired 受理点**：pipeline.py 的 scenario-repaired 申报受理处（改写场景文件前）检查 `_scenario_repair_exhausted_rounds >= 1`：命中则拒收申报（场景文件不改写、不触发重执行重入），judge 裁决产物照常落盘（test-defect 记录在案），WARNING 留痕「修复预算已耗尽，转纯归因」。选受理点而非 judge prompt——prompt 层约束会被模型漂移突破，机械门 fail-closed。
  **拒收出口契约**：受理门命中时 MUST 提前退出裁决采纳尾段（`_handle_scenario_repaired`
  返回 True，比照空集拒绝先例 pipeline.py:1915-1936：error 留痕、spec 保持 testing），
  MUST NOT 返回 False——调用方平铺尾段（pipeline.py:3621-3662）依赖「scenario-repaired
  已由专门分支消费」前提（:3630-3632 注释），拒收若返回 False 会穿透 plan-ready/bug-found
  守卫落到 `_apply_verified`（:3662），未重执行即假收敛为 verified，正是本 SPEC 要堵的
  「洗白」类故障。
- **D2 耗尽状态即 STATE 持久字段本身**：`_scenario_repair_exhausted_rounds` 已持久化于 STATE（state_machine.py:631-640 既有语义），门只读该字段即天然跨重启；若实证发现某路径（daemon 恢复/admin 复位）会误清该字段，属该路径的清零集缺陷，就地修正并在任务中回归（该字段唯一清零点 = verified + 人工解冻：实现点为 verdict_evidence.py:1383-1394 verified 分支与 state_machine.py:2448 unfreeze_spec，tests/test_pm_verification.py:763-793 已回归既有口径）。
- **D3 纯归因模式不新增状态字段**：无修复模式 = 「耗尽字段 >= 1 且非刚解冻」的推导态，不落新旗标（避免双旗标漂移）；解冻清零后门自然放行（D2）。本条禁列仅指**模式推导旗标**；D4 告警取数所需的生命周期修复申报计数留痕（申报轮数、耗尽后拒收轮数）属预算口径字段，与 `_judge_rerun_count` 同族（清零点同为 verified + 人工解冻），在 state_machine.py 单点定义，不在禁列。
- **D4 告警上下文取数**：`_judge_hard_cap_freeze` 的 evidence 拼入 `_scenario_repair_exhausted_rounds` 当前值 + 生命周期修复申报计数与耗尽后拒收轮数（D3 预算口径字段，受理门写点维护）+ judge 修复申报的最近摘要（取自 judge 裁决产物/judge_files，场景 id 级别截断）——三项均有具名 STATE/产物来源，MUST NOT 依赖日志回捞，recommended_action 分叉：耗尽 → 「剩余 test-defect 走人工修复或归因豁免」；未耗尽 → 既有「检查反复重跑根因」。

## Risks / Trade-offs

- **修复质量下降**：耗尽后真有可修复的场景缺陷也只能记录不修——这是预算语义的代价面；人工解冻即可重开通道，且「修了但永不执行」（round 3 排程重验前修复落盘却撞重启作废）的浪费形态被一并堵住。
- **受理点拒收导致 judge 轮「白跑」观感**：judge 仍产出有效归因（product-bug/env 定性与 test-defect 记录），非空转；重跑计数增长由硬上限兜底（SPEC 1 保证解冻可重置）。
