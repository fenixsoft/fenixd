## Deliverables

```yaml
- path: core/worktree_manager.py
  kind: modify
- path: core/pm_engine/dispatch.py
  kind: modify
- path: tests/test_mergeback_wip_overlap_gate.py
  kind: new
```

## 1. 落地校验

- [ ] 1.1 core/worktree_manager.py：新增 merge-back 前置 WIP 重叠处置（block | stash 两策略；默认 stash，block 仅显式配置启用），wip_overlap 预检升级为执行级前置；闸门判定的重叠集合 MUST 排除 `spec/changes/**`（与 ensure_clean_tree 的 `:(exclude)spec/changes` 覆盖集合一致），该前缀仍由既有 ensure_spec_committed/_commit_softened_declaration 提交通道收口
- [ ] 1.2 core/worktree_manager.py：merge-back 主体接入该前置，阻塞策略中止合并并输出重叠文件清单+处理指引，返回置 `wip_gate_blocked=True`；收纳策略用可识别前缀（MUST NOT 含 AUTOSTASH_MSG_PREFIX 子串，防 reclaim_stale_autostash 每 60s 抢走保留条目）stash、成功自动恢复、pop 冲突保留 stash 条目并记录 last_stash_entry_fate
- [ ] 1.3 core/worktree_manager.py：删除「pop 冲突无条件丢弃 stash 版」路径，保留既有「树级 diff 证明完全取代才 drop」（_drop_superseded_stash_entry）；主树 MUST NOT 残留 UU 未合并态（沿用既有 checkout 收口不变量）；fix-mergeback-stashpop-silent-loss 既有行为保留为兜底开关
- [ ] 1.4 core/pm_engine/dispatch.py：`wip_gate_blocked` 标记旁路——MUST NOT 计入 `_merge_fp`/`_merge_streak`、MUST NOT 降级 ready/触发 `transition(blocked)`、MUST NOT 进 repair 通道（对照先例 rehearsed 豁免，dispatch.py:1090-1094）

## 2. 测试

- [ ] 2.1 tests/test_mergeback_wip_overlap_gate.py：主树 WIP 与分支改动重叠 + block 策略 → merge-back 中止且告警含文件清单与指引，返回带 `wip_gate_blocked`
- [ ] 2.2 tests/test_mergeback_wip_overlap_gate.py：重叠 + stash 策略 → 收纳后合并、成功恢复主树 WIP（断言文件内容还原）
- [ ] 2.3 tests/test_mergeback_wip_overlap_gate.py：pop 冲突 → 保留 stash 条目（断言 last_stash_entry_fate/可找回），不无条件丢弃、主树无残留 UU
- [ ] 2.4 tests/test_mergeback_wip_overlap_gate.py：无重叠但主树脏 → 沿用现行 autostash→merge→pop 行为不变（照常收纳并恢复、无阻塞）；主树干净 → 无 stash 无阻塞
- [ ] 2.5 tests/test_mergeback_wip_overlap_gate.py：仅在 `spec/changes/**` 重叠（主树 tasks.md 脏 + 分支同改）→ 闸门不阻塞不收纳
- [ ] 2.6 回归：tests/test_worktree_merge_guard.py、test_worktree_reuse.py、test_worktree_stray_and_identical.py 通过；阻塞返回两次后 `_merge_streak` 未累计（不入熔断）