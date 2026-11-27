## Deliverables

```yaml
- path: core/knowledge_audit.py
  kind: modify
- path: tests/test_knowledge_audit_reminder_decay.py
  kind: new
```

## 1. 降频节拍

- [ ] 1.1 core/knowledge_audit.py：新增 `_escalated_reminder_due(escalated, state, today)` 纯函数——集合变化旁路；escalated 空集应拍；降频态 = 最长龄期 > `cfg["escalated_stale_days"]` 且（无 `last_escalated_consumed_date` 或距今 > stale_days）；降频态下距 `last_escalated_reminded_date` ≥ stale_days 才应拍。`stale_days` 取 config 单源，不新增本文件 7 常量（:88-94 纪律）。
- [ ] 1.2 core/knowledge_audit.py：run_audit 收尾 upsert 调用点（:2396-2416）前置判定——不应拍时不调用 upsert（不写盘不提交，log.info 留痕下次提醒日），MUST NOT 用空串返回跳过（空串=纯清理会删聚合行）；应拍时 `_escalated_todo_line(escalated, decayed=...)` 附降频注记；仅 upsert 实际写盘（True）后持 `_state_write_lock`（:188）回读合并刷新 `last_escalated_reminded_date` / `last_escalated_fingerprint_set`；fail-open OSError 不刷新日期。
- [ ] 1.3 core/knowledge_audit.py：escalated 空集旁路降频照常纯清理并复位三键；`consume_arbitration`（:700）仅 consumed 非空时追加记账（`last_escalated_consumed_date=today`、清除 `last_escalated_reminded_date`、更新指纹集），consumed 为空零写；消费判定/台账删除/注记摘除行为不变。
- [ ] 1.4 core/knowledge_audit.py：`_escalated_todo_line` 增加可选 `decayed=False` 参数，True 时行尾追加「（已降频为每周一拍、欠账仍在）」，其余文案逐字节不变。

## 2. 测试

- [ ] 2.1 tests/test_knowledge_audit_reminder_decay.py：覆盖六形态——未超龄每日拍；超龄零消费降频（间隔内 upsert 不调用且聚合行保持原样）；降频期间新增 escalated 当日应拍；消费后恢复每日拍、stale_days 后重新降频；全部消费纯清理并复位键；状态键缺失/损坏与 upsert 失败均不抑制提醒且不刷新日期。
- [ ] 2.2 回归确认既有 knowledge audit 相关测试全绿（tests/test_knowledge_audit.py、tests/test_knowledge_audit_escalation_governance.py、tests/test_knowledge_backfill.py），upsert 幂等/纯清理语义与 consume_arbitration 消费侧行为不变。
