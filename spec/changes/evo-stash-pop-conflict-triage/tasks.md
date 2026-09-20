# Tasks: stash-pop-conflict-triage

## Deliverables

```yaml
- path: core/worktree_manager/stash_guard.py
  kind: modify
- path: tests/test_stash_pop_conflict_triage.py
  kind: new
```

## 1. stash pop 冲突三态重试

- [ ] 1.1 core/worktree_manager/stash_guard.py：pop 冲突时首选将 stash 版并入 merge 后工作区（不同 hunk 自动合并，真正冲突才留标记），不直接丢弃
- [ ] 1.2 core/worktree_manager/stash_guard.py：merge 不可行时自动创建恢复 commit 留审计（stash 版内容 + 冲突标记），登记 disposition
- [ ] 1.3 core/worktree_manager/stash_guard.py：两者均不可行才保留冲突文件并登记 disposition，绝不静默丢弃；stash 条目保留与 stash_pop_conflict 信号行为保持
- [ ] 1.4 core/worktree_manager/stash_guard.py：冲突处置路径写结构化日志（文件清单/处置方式/stash sha），供 stash_pop_conflict 信号 evidence 携带

## 2. 测试

- [ ] 2.1 tests/test_stash_pop_conflict_triage.py：pop 冲突时 stash 版内容不丢失（构造冲突场景断言文件内容落回工作区）
- [ ] 2.2 tests/test_stash_pop_conflict_triage.py：兜底路径（merge 与恢复 commit 均不可行）仍登记 disposition 且不留静默丢弃