## Deliverables

```yaml
- path: core/worktree_manager.py
  kind: modify
- path: tests/test_mergeback_wip_overlap_gate.py
  kind: new
```

## 1. 落地校验

- [ ] 1.1 core/worktree_manager.py：新增 merge-back 前置 WIP 重叠处置（block | stash 两策略，配置可选），wip_overlap 预检升级为执行级前置
- [ ] 1.2 core/worktree_manager.py：merge-back 主体接入该前置，阻塞策略中止合并并输出重叠文件清单+处理指引；收纳策略用可识别前缀 stash、成功自动恢复、pop 冲突保留 stash 版并记录 last_stash_entry_fate
- [ ] 1.3 core/worktree_manager.py：删除「pop 冲突静默丢弃 stash 版」路径（或降为显式确认后才继续），fix-mergeback-stashpop-silent-loss 既有行为保留为兜底开关

## 2. 测试

- [ ] 2.1 tests/test_mergeback_wip_overlap_gate.py：主树 WIP 与分支改动重叠 + block 策略 → merge-back 中止且告警含文件清单与指引
- [ ] 2.2 tests/test_mergeback_wip_overlap_gate.py：重叠 + stash 策略 → 收纳后合并、成功恢复主树 WIP（断言文件内容还原）
- [ ] 2.3 tests/test_mergeback_wip_overlap_gate.py：pop 冲突 → 保留 stash 版（断言 last_stash_entry_fate/可找回），不静默丢弃
- [ ] 2.4 tests/test_mergeback_wip_overlap_gate.py：无重叠/主树干净 → 既有 merge-back 行为不变（无 stash、无阻塞）
- [ ] 2.5 回归：tests/test_worktree_merge_guard.py、test_worktree_reuse.py、test_worktree_stray_and_identical.py 通过