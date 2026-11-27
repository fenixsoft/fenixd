## Deliverables

```yaml
- path: core/knowledge_audit.py
  kind: modify
- path: tests/test_knowledge_audit_reminder_decay.py
  kind: new
```

## 1. 降频节拍

- [ ] 1.1 core/knowledge_audit.py：escalated 聚合提醒在持续零仲裁消费超 7 天（与 disputed 注记 stale_days 对齐的常量）后降频为每周一拍——在提醒生成链（_escalated_summary/_escalated_todo_line 到 upsert_todo_line）入口按 knowledge_audit_state.json 新增的最近提醒日期判断，间隔不足 7 天不再改写 todo 聚合行；满 7 天才更新并刷新日期。
- [ ] 1.2 core/knowledge_audit.py：降频期间聚合行文案注明「已降频为每周一拍、欠账仍在」；consume_arbitration 消费任一 escalated 指纹时重置降频态恢复每日节拍；disputed 注记与消费检查点行为不变。

## 2. 测试

- [ ] 2.1 tests/test_knowledge_audit_reminder_decay.py：覆盖四形态——未超龄保持每日一拍；超 7 天未消费降为每周一拍（间隔内 todo 行不被改写）；消费后恢复每日节拍；降频文案注记存在且 disputed 注记不受影响。