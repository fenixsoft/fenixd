## Deliverables

```yaml
- path: core/worktree_manager.py
  kind: modify
- path: core/pm_engine/dispatch.py
  kind: modify
- path: tests/test_merge_tree_rehearsal.py
  kind: new
```

## 1. git 层：预演闸

- [x] 1.1 `merge_back_from_branch` 真合并（stash 序列）前执行 `git merge-tree --write-tree <main> <branch>` 只读预演，解析冲突路径清单；零冲突放行现行流程（逐字节不变）
- [x] 1.2 冲突分类复用既有产物前缀判定：全部冲突为产物/ignored-DU → 放行真合并走既有自愈；含语义文件 → 跳过 stash/merge/abort 全序列，返回带 `rehearsed=True` 的结构化 MergeConflictInfo（主树零污染）
- [x] 1.3 git ≥ 2.38 一次性探测（进程内缓存），不支持则预演闸整体跳过并记一次性 WARNING，行为回退现行

## 2. 调度层：语义冲突直通 repair

- [x] 2.1 implementer 与 fast-track 失败分支识别 `rehearsed` 标记：命中则跳过 `_merge_fp`/`_merge_streak` 记账与 ready 降级，直接 `_dispatch_repair_lane`（spec 保持 in-flight）
- [x] 2.2 repair 轮次上限与 fallback 回退语义不变（`_repair_round` 超限回退现行 fallback 重派）；repair 后 re-merge 失败链保持现行 fp 熔断
- [x] 2.3 日志留痕：预演直通 repair 的 spec/冲突路径/分类记 INFO，与 abort 后 repair 路径可区分

## 3. 测试与回归

- [x] 3.1 tests/test_merge_tree_rehearsal.py：覆盖 specs 全部 Scenario（零冲突放行、预演零副作用、语义冲突直通 repair 且无 fp 增量、repair 轮次兜底、产物冲突走自愈、旧版 git 回退）
- [x] 3.2 既有套件回归：test_worktree_merge_guard.py、test_mergeback_repair_lane.py、熔断相关测试全绿（零冲突与产物冲突路径零行为差异）
