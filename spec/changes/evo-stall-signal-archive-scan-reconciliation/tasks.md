## Deliverables

```yaml
- path: core/admin_monitor.py
  kind: modify
- path: tests/test_lane_stall_accounting.py
  kind: modify
- path: spec/knowledge/domains/cost-observability/api-stall-observability.md
  kind: modify
```

## 1. 扫描面归档盲区修复与对账自证

- [ ] 1.1 core/admin_monitor.py：扩展车道日预算信号面（_evaluate_lane_stall_daily_signals）与单轮停滞升级信号面（_check_api_round_stall_escalated）共用的 run 档案扫描源——从顶层 glob（约 4459-4461 行）扩展为「顶层 + archive/」双源，使终态 run 被 runs 保留清理移入归档后仍可入账；归档源按当日 UTC 日桶过滤控制扫描量
- [ ] 1.2 core/admin_monitor.py：对账自证——每巡检轮将终态 run_metrics 停滞行合计（含当日 archive 内终态 run）与内存累计器 _lane_stall_daily 对账，差额超 60 秒补发 lane_stall_daily_budget 信号留痕且 evidence 注明对账来源；补发走既有信号落账通道，不新增 kind
- [ ] 1.3 core/admin_monitor.py：三来源（顶层/归档/对账补发）共用既有 run 级去重集合，同一 run 停滞行只入账一次；success 终态豁免、阈值与 UTC 日桶语义不变
- [ ] 1.4 spec/knowledge/domains/cost-observability/api-stall-observability.md：补记「终态秒级归档 vs 巡检节拍」竞态盲区（历史落账最险仅早归档 4 秒、2026-11-25 窗首例漏报与 api_round_stall_escalated 面零落账实证）与扫描面双源、对账自证机制

## 2. 测试

- [ ] 2.1 tests/test_lane_stall_accounting.py：覆盖终态即归档场景——构造停滞 run 档案直接落入 archive/（顶层无文件）断言车道日累计入账且越线时信号落账；覆盖「落盘后立即归档」场景下一巡检轮仍入账
- [ ] 2.2 tests/test_lane_stall_accounting.py：覆盖对账自证——构造累计器与档案合计差额超 60 秒场景断言补发信号且 evidence 含对账来源注记；覆盖三来源去重——同一 run 档案经顶层、归档、对账补发只入账一次；覆盖 success 终态豁免与阈值语义无回归