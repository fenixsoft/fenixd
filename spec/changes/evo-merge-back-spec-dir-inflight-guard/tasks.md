# Tasks: merge-back-spec-dir-inflight-guard

## Deliverables

```yaml
- path: core/worktree_manager/mergeback.py
  kind: modify
- path: core/pm_engine/dispatch/queue.py
  kind: modify
- path: tests/test_merge_back_spec_dir_guard.py
  kind: new
```

## 1. merge-back 前在飞编辑卫检查

- [ ] 1.1 core/worktree_manager/mergeback.py：merge_back_from_branch 入口对 spec/changes/<spec>/（spec 名由分支推导，复用 _spec_from_branch）执行 git status 未提交改动检测，命中即返回顺延信号（reason=spec_dir_inflight），不进入 merge
- [ ] 1.2 core/worktree_manager/mergeback.py：顺延信号携带等待语义（对齐 evo-recovery-watch-status-recheck 范式），由调度方重排而非判失败

## 2. merge-back 失败分类与仅重试合并

- [ ] 2.1 core/pm_engine/dispatch/queue.py：merge-back 失败分支区分「可重试（主树脏/spec 在飞编辑/锁冲突）」与「run 真失败」——可重试时保留已成功分支与产物、等待主树干净后仅重试合并
- [ ] 2.2 core/pm_engine/dispatch/queue.py：可重试等待/重试不消耗实现尝试预算（used count）、不重派实现整轮；合并重试耗尽后仍失败再走既有熔断/repair 通道

## 3. 测试

- [ ] 3.1 tests/test_merge_back_spec_dir_guard.py：spec/changes 有未提交改动时 merge-back 顺延不 merge（构造脏树单测）
- [ ] 3.2 tests/test_merge_back_spec_dir_guard.py：合并失败分类后可重试路径仅重试合并而非重派实现（实现 run_id 不变断言）