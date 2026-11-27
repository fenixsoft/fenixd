## Deliverables

```yaml
- path: core/evolution.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: tests/test_evolution_prune.py
  kind: modify
- path: spec/knowledge/domains/self-evolution/self-evolution.md
  kind: modify
```

## 1. 保留集 pending 配额豁免

- [ ] 1.1 core/evolution.py：在 prune_items 保留集构建处（keep_ids 并集，约 2810 行附近）追加 pending 配额集——status=='pending' 的条目按 created_at 倒序额外保留前 ITEM_RETENTION_PENDING_MIN 名并入 keep_ids；新常量与 ITEM_RETENTION_DAYS/ITEM_RETENTION_MIN 同处定义（约 149-150 行附近），缺省 20；超配额最老 pending 仍按常规策略淘汰，保持队列有界
- [ ] 1.2 清理留痕补 pending 维度——core/evolution.py prune_items 返回 dict 新增 deleted_pending 键（本次删除成功条目中 status=='pending' 的条数，与 deleted 同口径循环内累加）；fenixd.py 调用方日志行（约 6276-6280 行 f-string 拼装处）追加「pending W」段，以 .get("deleted_pending", 0) 容错读取；日志发射条件维持既有「deleted>0 or failed>0」，不新增零删除日志，使 pending 保全效果可审计
- [ ] 1.3 spec/knowledge/domains/self-evolution/self-evolution.md：同步保留策略口径——「条目保留与自动清理」能力段（第 31 行附近，现行文字为「仅保留 7 天 ∪ 倒序前 100 条并集，其余硬删」，未提状态维度，页内并无「一刀切全状态」原句）修订为「常规条目按 7 天∪前 100 名，pending 条目另有 created_at 倒序配额保护（前 ITEM_RETENTION_PENDING_MIN 名）」，并在溯源段追加本 SPEC 条目，注明该口径修订取代 2026-09-19-evo-item-retention-doc-tracking design.md 的显式用户决策及其前提失效原因（人工接受闸门停滞导致 pending 被挤出保留集）

## 2. 测试

- [ ] 2.1 tests/test_evolution_prune.py：覆盖 pending 配额豁免——构造超配额 pending 台账（analyzed 超 7 天且超前 100 名、pending 25 条且均超 7 天窗口并在前 100 名之外，使配额成为唯一保留来源）断言 pending 至少保留 created_at 最新的 20 条、超配额最老 pending 被删、analyzed 淘汰行为不变；覆盖 pending 少于配额时全部保留；覆盖 prune_items 返回值含正确的 deleted_pending 计数（含零删除时为 0 的形态）；既有 test_old_pending_deleted 夹具（100 条 recent pending + 5 条超龄 pending）在新语义下语义不变仍应通过，无须改动