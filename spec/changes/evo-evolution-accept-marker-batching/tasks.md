## Deliverables

```yaml
- path: core/evolution.py
  kind: modify
- path: tests/test_evolution_todo_marker_commit.py
  kind: modify
```

## 1. 接受循环批末合并提交

- [ ] 1.1 core/evolution.py：accept_item（:1526，回写点 :1793 write_todo_marker 缺省 commit=True）加 defer_commit 开关形参（缺省不变，dashboard 手动单条路径 core/dashboard/routes/evolution_routes.py:137 保持即时提交）；auto_accept_pending（:2108，循环体 :2125-2149）改为逐条 defer、批末对本项目调一次 commit_todo_marker 合并提交（_commit_todo_marker :932 传条目 id 明细消息后缀）。

## 2. 测试

- [ ] 2.1 tests/test_evolution_todo_marker_commit.py：照 test_ingest_pending_batch_defers_commit 模板补「auto_accept 批次（≥2 条）恰一枚提交且消息含条目 id 明细」回归；补「dashboard 手动单条接受仍即时提交」不回归用例。