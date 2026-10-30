## Deliverables

```yaml
- path: core/code_fix.py
  kind: modify
- path: tests/test_code_fix.py
  kind: modify
- path: tests/test_codefix_failure_registration_closeout.py
  kind: new
```

## 1. 登记核销回路

- [x] 1.1 core/code_fix.py：fix-failed.json 失败记录增结构化核销字段（consumed_at/consumed_note/open_remaining，缺键视为未核销）；核销判定=对台账逐 id 对账、被跳过条目全部终态（resolved/ignored）即置核销；挂钩两处——批收尾/合回核销点（mark_ignored/mark_resolved 及延迟批合回）后即时检查、新链启动既有簿记块周期兜底；台账读取失败按空集 fail-open 不阻断主流程；核销写沿用 fix-failed.json flock 惯例（锁内不重入，告警/todo 写锁外）
- [x] 1.2 core/code_fix.py：核销时按记录内 branch/tip_sha/item_ids 匹配未收口的 code_fix_retry_budget_exhausted 告警并经 AdminStore.mark_signal_handled 收口（action_taken 附终态分布）；部分终态只更新 open_remaining 不收口；重复核销幂等
- [x] 1.3 core/code_fix.py：release_failed_batch 增结构化留痕——内部无条件追加一行到 .fenix/code-review/fix-failed-release.jsonl（释放记录数+item_ids 摘要，OSError 容错同 _append_todo_entry 口径），logger（可选）传入时另写一行 daemon 日志；todo.md 消费侧持同锁重写式核销或整块移除（按块体「被跳过的条目集合」行的 item_ids 定位本记录登记块、裸标题残骸按标题兜底，MUST NOT 波及他批登记块），不依赖原位追加注记，OSError 容错与 _append_todo_entry 同口径

## 2. 测试

- [x] 2.1 tests/test_codefix_failure_registration_closeout.py：覆盖全终态→核销+告警收口+todo 重写一次完成、部分终态→保留 open_remaining 不收口、重复核销幂等、release 留痕断言、台账读取失败 fail-open
- [x] 2.2 tests/test_code_fix.py：补登记写入/核销改写与 evolution 写者的锁竞争回归用例