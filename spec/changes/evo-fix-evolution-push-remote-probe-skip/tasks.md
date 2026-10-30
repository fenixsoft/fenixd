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

- [ ] 2.1 core/evolution.py（仅本车道；self_review 每日至多一次 push 不聚合）：按项目根维护进程内 push 连续失败计数（自最近一次成功起累计、成功清零）与当日已告警标记，首败发含仓路径与计数（及 stderr 尾部）的一条聚合 WARNING，后续失败仅递增计数并降级记 DEBUG、不记常规 WARNING；当日已告警标记跨日重置（计数不清零）

## 3. 测试

- [ ] 3.1 tests/test_evolution_push_remote_probe.py：零 remote 仓回写，两车道（evolution `_commit_todo_marker` 与 self_review `_commit_todo`）各验证——push 被跳过（无 push 子进程调用）、DEBUG 日志含仓路径、无 WARNING、commit 仍产生；self_review 车道以注入 logger／调用记录取证，不依赖 fenixd.log 中央 sink（兄弟仓场景该车道在中央 sink 静默，见 MERGE-NOTES 验证纪律）
- [ ] 3.2 tests/test_evolution_push_remote_probe.py：同仓连续两次 push 失败——全程仅一条 WARNING（首败聚合，文案含仓路径与连续失败计数），第二次失败仅递增计数且降级 DEBUG、无新 WARNING
- [ ] 3.3 tests/test_evolution_push_remote_probe.py：有 remote 但单次 push 失败——记常规 WARNING 且文案含仓路径与 stderr 尾部（task 1.3 的验收）