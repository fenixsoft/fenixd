# Proposal: scenario-defect-reroute-stoploss

## Why

2026-09-16/17 fix-dashboard-read-path-performance 事故：验证阶段 2 个场景被判 test-defect（场景自身缺陷归类），场景缺陷改道门（add-scenario-defect-triage-gate 建立）改道重派 judge 修场景，但改道后重跑仍是同一批失败——改道机制只按次数预算（_SCENARIO_REPAIR_MAX_ROUNDS=2）运行，无「改道无效」中途校验，白白烧掉预算至耗尽才升级人工：5 小时内 3 次耗尽预算（深度 2→1→1），spec 卡 testing 264 分钟越过阈值触发 blocker，下游 fix-robustness-edge-cases 每轮巡检被依赖拒绝。

根因：改道门（core/pm_engine/verification/escalation.py _scenario_defect_reroute_gate）只比较 _repair_depth 与预算上限，改道重派后是否仍同批失败不做对比——「改道修复生效」这一前提无人校验。

## What Changes

- **改道止损判据**：改道重派 judge 后，把重跑失败场景集与改道前失败场景集对比；同批失败（失败集相同或完全包含）时判定「改道无效」，提前止损升级人工，不等 _repair_depth 耗尽；失败集变化（有修复进展）则继续消耗预算。
- **跨轮失败集留存**：改道前失败场景集写入 verify-progress（spec 级状态），供改道重跑后对比。

## Capabilities

### New Capabilities

- `scenario-defect-reroute-stoploss`: 场景缺陷改道的止损判据——改道无效时提前升级人工，避免预算耗尽才升级。