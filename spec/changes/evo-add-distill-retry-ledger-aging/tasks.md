## Deliverables

```yaml
- path: core/knowledge.py
  kind: modify
- path: tests/test_distill_retry_ledger_aging.py
  kind: new
```

## 1. 龄期展示与超期升级

- [ ] 1.1 core/knowledge.py：check_retry_ledger_age 发射信号时在 description/evidence 附欠账条目登记时刻、当前龄期与对应归档 spec 名
- [ ] 1.2 core/knowledge.py：欠账龄期超过 72 小时未处置时信号升级为 major/ESCALATION（按 admin_store 既有常量择一），24 小时内维持 warning

## 2. 持久化节流

- [ ] 2.1 core/knowledge.py：将进程内当日幂等标记替换为经 AdminStore 的持久节流窗口（复用 latest_signal 判窗或 append_if_absent），窗口跨 daemon 重启有效
- [ ] 2.2 core/knowledge.py：龄期跨过升级门槛的首次发射穿透节流窗口立即发出

## 3. 测试

- [ ] 3.1 tests/test_distill_retry_ledger_aging.py：覆盖龄期字段正确性、72 小时升级边界、节流窗口跨 daemon 重启语义、升级首射穿透节流
