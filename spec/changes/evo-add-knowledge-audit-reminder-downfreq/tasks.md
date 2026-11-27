## Deliverables

```yaml
- path: core/knowledge_audit.py
  kind: modify
- path: tests/test_knowledge_audit_reminder_downfreq.py
  kind: new
```

## 1. 降频判定与状态键

- [ ] 1.1 core/knowledge_audit.py：新增 _escalated_reminder_due(escalated, state, today) 纯函数（escalated 空集 → True 走清理旁路；集与 state.last_escalated_set 不同 → True；同集且距 last_escalated_reminder_date ≥7 天 → True；否则 False），本地日口径沿用 _today()
- [ ] 1.2 core/knowledge_audit.py：run_audit 收尾 upsert 调用点（约 :2245-2253）接入判定——False 时跳过 upsert 不写盘不提交并 log.info 留痕；True 且非空集时行尾追加「（下次重复提醒不早于 YYYY-MM-DD）」并持 _state_write_lock 回读合并更新两状态键
- [ ] 1.3 core/knowledge_audit.py：escalated 清零时旁路降频照常执行纯清理语义摘除残留行，并重置 last_escalated_reminder_date / last_escalated_set 两键防陈旧集误跳过
- [ ] 1.4 core/knowledge_audit.py：_escalated_todo_line 增加可选 next_remind_date 参数（None 不追加尾注，既有文案其余部分逐字节稳定）

## 2. 测试

- [ ] 2.1 tests/test_knowledge_audit_reminder_downfreq.py：覆盖四态——同集 7 天内跳过（upsert 不发生）、集变化立即拍（行含下次提醒尾注）、清零旁路清理、到期恢复拍并刷新状态键
- [ ] 2.2 回归确认既有 knowledge audit 相关测试全绿（tests/ 下 grep knowledge_audit 定位），upsert 既有幂等短路/纯清理语义与 consume_arbitration 消费侧行为不变