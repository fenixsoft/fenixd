# Tasks: scenario-defect-reroute-stoploss

## Deliverables

```yaml
- path: core/pm_engine/verification/escalation.py
  kind: modify
- path: core/pm_engine/verification/pipeline.py
  kind: modify
- path: tests/test_scenario_reroute_stoploss.py
  kind: new
```

## 1. 止损判据

- [x] 1.1 core/pm_engine/verification/escalation.py：_scenario_defect_reroute_gate 门入口读留存，满足链内作用域（`_repair_depth >= 1` 且留存轮次 = `_repair_depth - 1`）且改道前失败集 ⊆ 重跑失败集 → 调 _escalate_scenario_defect_reroute 提前止损（不再重派 judge、不消耗剩余预算）；有场景被修复 → 覆盖留存后走既有通道
- [x] 1.2 新增 human-escalation-alert 信号 scenario_defect_reroute_stoploss（severity major，升级人工，附同批失败证据：failed_ids / 轮次 / classification 分布）
- [x] 1.3 链首触发（`_repair_depth == 0`）只写留存不判定（防上一链条陈旧留存误停，MUST NOT 在此轮升级）

## 2. 跨轮失败集留存

- [x] 2.1 门入口（重派 judge 前）把 `{"round": <_repair_depth>, "failed_ids": <dist["failed_ids"]>, "written_at": <iso8601>}` 写入 `.fenix/verify-progress/<spec>/scenario_reroute_stoploss.json`（含轮次）；写失败仅告警不阻断改道
- [x] 2.2 门入口读取对比；文件缺失/损坏/结构不符/轮次不匹配 → 保守放行继续既有预算通道
- [x] 2.3 读取点 MUST 是改道重入轮的门触发入口（重跑已产新 report.json）；MUST NOT 在同一次门调用内重派前读（读到的是改道前旧产物，必判同批 = 假止损）

## 3. 测试

- [x] 3.1 tests/test_scenario_reroute_stoploss.py：改道重入轮同批失败 → 提前止损升级人工（未等预算耗尽、run_planner 未被调用）
- [x] 3.2 改道重入轮有场景修复 → 继续预算通道；纯新增场景（无一修复）→ 判同批止损；文件缺失/损坏/轮次不匹配 → 放行不误停
- [x] 3.3 链首触发（深度 0）+ 陈旧留存失败集相同 → 不误停（照常重派 judge）
- [x] 3.4 既有预算耗尽升级路径回归不破坏；tests/test_scenario_reroute_gate.py 全量回归通过
