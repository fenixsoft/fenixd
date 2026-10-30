## Deliverables

```yaml
- path: core/evolution.py
  kind: modify
- path: core/self_review.py
  kind: modify
- path: tests/test_evolution_push_remote_probe.py
  kind: new
```

## 1. push 前探测跳过

- [ ] 1.1 core/evolution.py：todo 回写 push（现 1106-1122 行一带）前探测 git remote，无 remote 记 DEBUG（含项目根路径）并跳过 push，commit 语义不变
- [ ] 1.2 core/self_review.py：_commit_todo（现 2689 行一带）接入同一探测逻辑（抽共用小函数），两车道行为一致
- [ ] 1.3 core/evolution.py 与 core/self_review.py：push 失败 WARNING 文案统一补项目根路径

## 2. 恒失败聚合告警

- [ ] 2.1 core/evolution.py：按项目根维护 push 连续失败计数与当日已告警标记，首败发含仓路径与计数的聚合告警，后续失败仅递增计数、跨日重置

## 3. 测试

- [ ] 3.1 tests/test_evolution_push_remote_probe.py：零 remote 仓回写——push 被跳过、DEBUG 日志含仓路径、无 WARNING、commit 仍产生
- [ ] 3.2 tests/test_evolution_push_remote_probe.py：同仓连续两次 push 失败——仅一条聚合告警且文案含仓路径与连续失败计数