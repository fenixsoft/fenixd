## Deliverables

```yaml
- path: core/knowledge_audit.py
  kind: modify
- path: tests/test_knowledge_audit_reminder_downfreq.py
  kind: new
- path: tests/test_knowledge_audit_escalation_governance.py
  kind: modify
- path: spec/knowledge/domains/knowledge-atlas/knowledge-audit.md
  kind: modify
```

## 1. 降频判定与状态键

- [x] 1.1 core/knowledge_audit.py：新增 _escalated_reminder_due(escalated, state, today) 纯函数（escalated 空集 → True 走清理旁路；集与 state.last_escalated_set 不同 → True；同集且距 last_escalated_reminder_date ≥7 天 → True；否则 False），本地日口径沿用 _today()
- [x] 1.2 core/knowledge_audit.py：run_audit 收尾 upsert 调用点（约 :2407-2414）接入判定——False 时跳过 upsert 不写盘不提交并 log.info 留痕（跳过前只读校验聚合行仍在 todo.md，缺失则强制拍）；True 且非空集时行尾追加「（下次重复提醒不早于 YYYY-MM-DD）」，且仅在 upsert 实际写盘成功（返回 True）后持 _state_write_lock 回读合并更新两状态键，异常/解码失败不更新、下一轮重拍
- [x] 1.3 core/knowledge_audit.py：escalated 清零时旁路降频照常执行纯清理语义摘除残留行，并持锁回读合并重置 last_escalated_reminder_date / last_escalated_set 两键防陈旧集误跳过
- [x] 1.4 core/knowledge_audit.py：_escalated_todo_line 增加可选 next_remind_date 参数（None 不追加尾注，既有文案其余部分逐字节稳定）
- [x] 1.5 core/knowledge_audit.py：降频判定 fail-open——状态键缺失/非法/晚于 today、last_escalated_set 非列表、集合未排序一律按应拍处理不抛异常；日期差经 core.timelib.parse_ts 按自然日计算

## 2. 测试

- [x] 2.1 tests/test_knowledge_audit_reminder_downfreq.py：覆盖四态——同集 7 天内跳过（upsert 不发生）、集变化立即拍（行含下次提醒尾注）、清零旁路清理、到期恢复拍并刷新状态键
- [x] 2.2 回归确认既有 knowledge audit 相关测试全绿（tests/ 下 grep knowledge_audit 定位），upsert 既有幂等短路/纯清理语义与 consume_arbitration 消费侧行为不变
- [x] 2.3 tests/test_knowledge_audit_reminder_downfreq.py：补 fail-open 与写失败用例——状态键损坏/未来日期/集合形状不符→应拍；upsert 抛 OSError 或 strict 解码失败→状态键不刷新；聚合行被外部删除→强制拍重建
- [x] 2.4 tests/test_knowledge_audit_escalation_governance.py：适配 test_todo_aggregated_row_upsert_replaces_not_appends——第二次 run 前把状态键回拨 ≥7 天（或清空）模拟到期后仍断言「最长龄期 9 天」，并断言同日第二次 run 零写盘
- [x] 2.5 spec/knowledge/domains/knowledge-atlas/knowledge-audit.md：同步「升级聚合与唯一人工入口」条为 7 天降频语义（两状态键、集变化立即拍、清理旁路、下次提醒尾注），更新页首 rev 与溯源段

## 3. 编排去重

- [x] 3.1 实施前核对 spec/changes/evo-knowledge-audit-reminder-frequency-decay：该在途草稿与本 SPEC 目标重叠但判据/状态键不同，两线 MUST NOT 同时改同一调用点。若其已落地，则在其基线上合并（保留本 SPEC 的 7 天窗口判据，删除重复状态键与重复测试文件）；若并行未落地，由编排层择一后实施