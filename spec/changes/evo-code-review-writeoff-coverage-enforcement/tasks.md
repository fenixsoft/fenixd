## Deliverables

```yaml
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: core/code_review.py
  kind: modify
- path: tests/test_code_review_coverage_gate.py
  kind: new
```

## 1. 覆盖对账执行层

- [ ] 1.1 core/agent_runner/maintenance_runs.py：给全仓审查收尾的 _writeoff_coverage_guard 加执行层——按既有权威口径（分片+主产物，复用 core/code_review.py 的 covered_files）对 manifest scope 计算覆盖，缺口比例超阈值（新常量，缺省 2%）时把该 run 终态从 success 降格记 partial，并经 core/admin_store.py 既有告警写回通道落一条告警，正文含未覆盖文件数、比例与差集摘要；同一 run 只降格一次。
- [ ] 1.2 core/agent_runner/maintenance_runs.py：缺口超阈值时调用 core/code_review.py 既有 pending-writeoff 锚写入（write_pending_writeoff），锚内记本 run id 与未覆盖清单，使 core/admin_monitor.py 既有锚续审扫描自动武装 redispatch 续审；缺口低于阈值保持现行为（WARNING 留痕、success 终态、不落锚）。
- [ ] 1.3 core/code_review.py：补批次派发侧留痕——每个审查批次派出时把批号与计划文件数落一行事件记录（随 manifest 附属事件流或档案事件流），使「批号跳过/计划批次数偏短」形态可与 manifest scope 直接对账（本窗 34 派 vs 362 文件即此形态）。

## 2. 测试

- [ ] 2.1 tests/test_code_review_coverage_gate.py：覆盖三形态——缺口超阈值时终态降格 partial+告警落盘+锚写入且幂等；缺口低于阈值时终态保持 success 且不落锚；批次派发事件行与 manifest 对账能暴露计划偏短。
- [ ] 2.2 回归既有 tests/test_code_review_salvage_writeoff.py 与 tests/test_code_review_night_resume.py，确认锚语义与夜间续跑行为不被破坏。