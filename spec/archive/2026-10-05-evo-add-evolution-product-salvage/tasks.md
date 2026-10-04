## Deliverables

```yaml
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: core/evolution.py
  kind: modify
- path: agents/evolution.md
  kind: modify
- path: tests/test_evolution_product_salvage.py
  kind: new
```

## 1. 落地校验

- [x] 1.1 core/agent_runner/maintenance_runs.py：run_evolution 收尾段重排为「先抢救再清理」——新增 _salvage_evolution_out（产物缺失**或 JSON 不可解析**且 .parts 分片非空时按 sorted(glob) 配方合并写回）；run_ok=False 也先读产物：恢复出**完整**契约（条目数与 len(pending_entries) 一致或未知）即按成功落地并落 INFO；**部分恢复按失败落地（success=False、缺失数入 error、不触发水位推进**——fenixd worker 在 success 时对全部 ready_projects advance_watermark(snapshot_at)，部分成功推进会永久跳过未分析条目；已落地条目由 ingest_item 幂等去重由下轮补齐）；删除动作后移且范围扩到 .parts 残片目录
- [x] 1.2 core/evolution.py：read_contract 把「产物文件不存在」与「JSON 不可解析」拆成两个可判别的 ContractError 文案，告警与日志可直接判别失败面
- [x] 1.3 agents/evolution.md：分片写入契约改增量合并（每完成一条分片即并入最终产物，替代最后一次性合并），保留结尾全量校验步

## 2. 测试

- [x] 2.1 tests/test_evolution_product_salvage.py：覆盖五类场景——产物已写但 CLI 非零退出时按成功落地且不删产物、产物缺失但有分片时合并恢复、产物缺失且分片为空时报「产物未写出」并清理残片目录、产物存在但 JSON 不可解析且有分片时合并覆盖恢复、分片条目数不足时按失败落地（success=False、标注缺失数）且水位不推进
- [x] 2.2 覆盖 read_contract 失败文案分级断言，并回归既有 evolution 相关测试确认成功路径行为不变