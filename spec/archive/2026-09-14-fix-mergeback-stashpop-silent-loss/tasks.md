## Deliverables

```yaml
- path: core/worktree_manager.py
  kind: modify
- path: core/pm_engine/dispatch.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/dashboard/static/src/pages/activities/index.tsx
  kind: modify
- path: tests/test_worktree_merge_guard.py
  kind: modify
- path: tests/test_pm_engine_dispatch_fixes.py
  kind: modify
```

## 1. 自愈后被取代条目自动 drop

- [x] 1.1 restore_after_merge：pop 前 `rev-parse stash@{0}` 钉住 sha；自愈（UU checkout HEAD + reset）完成后对每个 UU 文件跑 `git diff --quiet <sha> HEAD -- <file>`，全部退出码 0 → 按 reclaim_stale_autostash（4f753ed，worktree_manager.py:1504-1538）同款模式核对 sha 仍在栈顶后 drop 并记 drop sha 日志；任一非 0 → 保留条目，日志含逐文件 `git show <sha>:<file>` 找回命令；sha 不在栈顶 → 放弃 drop 并记录跳过原因
- [x] 1.2 tests/test_worktree_merge_guard.py 新增 3 场景：stash 版被合并取代（同内容）→ 条目 drop；stash 版有独立差异 → 条目保留；pop 后 sha 被新条目顶掉 → 放弃 drop

## 2. merge-back 前 WIP 重叠预检

- [x] 2.1 merge_back_from_branch 在预演闸放行后、ensure_clean_tree 前：提取脏 tracked 文件清单（把 ensure_clean_tree 的 porcelain 脏判定提炼为共享 helper）∩ `git diff --name-only $(git merge-base HEAD <branch>) <branch>`；非空记 WARNING（含重叠清单）并挂 MergeConflictInfo.wip_overlap 新字段；只读不阻断，无重叠/主树干净时行为不变
- [x] 2.2 tests/test_worktree_merge_guard.py 新增 2 场景：脏文件与分支改动相交 → WARNING + wip_overlap 非空；无交集 → 零 WARNING、流程与现状一致

## 3. 冲突告警直发 admin_alerts

- [x] 3.1 admin_monitor.py：STORED_SIGNAL_TYPES 收录 stash_pop_conflict，SIGNAL_SEVERITY 给 major，SIGNAL_RECOMMENDATION 写核对指引（查 stash 栈 + 按 sha 找回）
- [x] 3.2 dispatch.py _report_stash_pop_conflict：conflict_files 非空时经 admin_store.append 直发 signal_type=stash_pop_conflict 告警，description 含 spec 名、冲突文件清单、stash 去向（保留/drop + sha）、逐文件找回命令，并把 merge_info.wip_overlap（若有）并入；spec.error 既有写入保持不变；conflict_files 为空早退不发
- [x] 3.3 activities/index.tsx signalType label 映射加 stash_pop_conflict: '合并冲突改动滞留'
- [x] 3.4 tests/test_pm_engine_dispatch_fixes.py 新增 2 场景：冲突自愈 → admin_alerts 出现 handled=false 的 stash_pop_conflict 记录且 description 含文件清单；pop 成功（无冲突）→ 不产生该记录

## 4. 收尾回归

- [x] 4.1 相关回归全绿：test_worktree_merge_guard、test_reclaim_stale_autostash、test_pm_engine_dispatch_fixes、test_admin
- [x] 4.2 前端自检：activities 页面改动经 npm build 编译通过（dist 不提交，merge 后框架自动重建）
