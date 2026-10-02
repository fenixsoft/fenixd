## Deliverables

```yaml
- path: core/knowledge_audit.py
  kind: modify
- path: core/knowledge_backfill.py
  kind: modify
- path: tests/test_knowledge_audit_escalation_governance.py
  kind: new
```

## 1. 语义车道解冻与聚合

- [ ] 1.1 core/knowledge_audit.py：escalated 条目不再计入 MAX_SEMANTIC_RUNS 转写预算（组装 semantic_all 时排除或 skip 补还槽位），报告留痕移至循环外统一渲染
- [ ] 1.2 core/knowledge_audit.py：体检报告 _render_report 把 escalated 明细折叠为单条汇总（条数 + 自 first_seen 起算的最长龄期）
- [ ] 1.3 core/knowledge_backfill.py：新增同前缀 upsert 辅助（匹配固定前缀整行替换）；core/knowledge_audit.py 升级登记改为单条聚合行（N 条待仲裁 + 最长龄期 + 指向仲裁清单路径），首跑替换清理历史逐条行

## 2. 超龄注记与仲裁清单

- [ ] 2.1 core/knowledge_audit.py：新增 ESCALATED_STALE_DAYS 常量（knowledge.escalated_stale_days 可覆盖）；escalated 超龄时对涉事页顶部写 disputed 注记（不含 knowledge: 前缀、不引用 archive 路径、写前查 150 行硬顶），走既有 [fenix] knowledge 提交路径自提交
- [ ] 2.2 core/knowledge_audit.py：escalated-skip 分支消费 .fenix/knowledge_audit_arbitration.json——命中指纹且 decision 合法即 _record_verdict、删台账条目、同步摘除注记；非法 decision/未知指纹跳过留痕

## 3. 测试

- [ ] 3.1 tests/test_knowledge_audit_escalation_governance.py：escalated 占槽豁免（10 条 escalated 在册时新候选仍被转写）、报告聚合行形态
- [ ] 3.2 tests/test_knowledge_audit_escalation_governance.py：聚合 todo 行 upsert（龄期变化替换不追加）、注记写入与摘除、注记不劫持 knowledge: marker 解析
- [ ] 3.3 tests/test_knowledge_audit_escalation_governance.py：仲裁清单消费闭环（合法 decision 删条目恢复复核）、脏输入防御（未知指纹/非法 decision 跳过留痕）