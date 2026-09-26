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

- [ ] 1.1 core/agent_runner/maintenance_runs.py：run_evolution 收尾段重排为「先抢救再清理」——新增 _salvage_evolution_out（产物缺失且 .parts 分片非空时按 sorted(glob) 配方合并写回，条目数与待分析条目数不一致时标注缺失数）；run_ok=False 也先读产物，读出可解析契约即按成功落地并落 INFO；删除动作后移且范围扩到 .parts 残片目录
- [ ] 1.2 core/evolution.py：read_contract 把「产物文件不存在」与「JSON 不可解析」拆成两个可判别的 ContractError 文案，告警与日志可直接判别失败面
- [ ] 1.3 agents/evolution.md：分片写入契约改增量合并（每完成一条分片即并入最终产物，替代最后一次性合并），保留结尾全量校验步

## 2. 测试

- [ ] 2.1 tests/test_evolution_product_salvage.py：覆盖四类场景——产物已写但 CLI 非零退出时按成功落地且不删产物、产物缺失但有分片时合并恢复、产物缺失且分片为空时报「产物未写出」并清理残片目录、分片条目数不足时标注缺失数
- [ ] 2.2 覆盖 read_contract 失败文案分级断言，并回归既有 evolution 相关测试确认成功路径行为不变