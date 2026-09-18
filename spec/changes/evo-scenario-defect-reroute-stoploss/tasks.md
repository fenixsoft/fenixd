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

- [ ] 1.1 core/pm_engine/verification/escalation.py：_scenario_defect_reroute_gate 改道重派后新增失败集对比——同批失败（失败集相同或改道前 ⊆ 重跑集）即调用 _escalate_scenario_defect_reroute 提前止损
- [ ] 1.2 新增 human-escalation-alert 信号 scenario_defect_reroute_stoploss（升级人工，附同批失败证据）

## 2. 跨轮失败集留存

- [ ] 2.1 改道门触发时把失败场景 id 列表写入 .fenix/verify-progress/<spec>/scenario_reroute_stoploss.json（含轮次）
- [ ] 2.2 改道重跑后读取对比；文件缺失/损坏 → 保守放行继续既有预算通道

## 3. 测试

- [ ] 3.1 tests/test_scenario_reroute_stoploss.py：同批失败 → 提前止损升级人工（未等预算耗尽）
- [ ] 3.2 失败集变化 → 继续预算通道；文件缺失 → 放行不误停
- [ ] 3.3 既有预算耗尽升级路径回归不破坏