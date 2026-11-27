## Deliverables

```yaml
- path: core/evolution.py
  kind: modify
- path: tests/test_evolution_prune.py
  kind: modify
- path: spec/knowledge/domains/self-evolution/self-evolution.md
  kind: modify
```

## 1. 保留集 pending 配额豁免

- [ ] 1.1 core/evolution.py：在 prune_items 保留集构建处（keep_ids 并集，约 2810 行附近）追加 pending 配额集——status=='pending' 的条目按 created_at 倒序额外保留前 ITEM_RETENTION_PENDING_MIN 名并入 keep_ids；新常量与 ITEM_RETENTION_DAYS/ITEM_RETENTION_MIN 同处定义（约 149-150 行附近），缺省 20；超配额最老 pending 仍按常规策略淘汰，保持队列有界
- [ ] 1.2 core/evolution.py：清理日志行补 pending 维度——「自进化条目保留清理：total/kept/deleted」日志追加删除的 pending 条数（deleted_pending），使 pending 保全效果可审计
- [ ] 1.3 spec/knowledge/domains/self-evolution/self-evolution.md：同步保留策略口径——将「清理一刀切全状态」描述修订为「常规条目按 7 天∪前 100 名，pending 条目另有 created_at 倒序配额保护」，注明该口径修订取代 2026-09-19-evo-item-retention-doc-tracking design.md 的显式用户决策及其前提失效原因（人工接受闸门停滞导致 pending 被挤出保留集）

## 2. 测试

- [ ] 2.1 tests/test_evolution_prune.py：覆盖 pending 配额豁免——构造超配额 pending 台账（analyzed 超 7 天且超前 100 名、pending 25 条）断言 pending 至少保留 created_at 最新的 20 条、超配额最老 pending 被删、analyzed 淘汰行为不变；覆盖 pending 少于配额时全部保留；覆盖清理日志含正确的 deleted_pending 计数