# Design: merge-back-wip-overlap-gate

## 背景与痛点

merge-back 被主树 WIP 与前修改重叠阻塞（09-15 merge 拒绝，阻塞约 1h），且 pop 冲突丢弃 stash 版已两次致内容丢失（09-14/09-15，见草稿 575976971cb8）。现有 wip_overlap 预检仅采集交集并预警（worktree_manager.py:107-110），无执行级处置。

## 目标

- 重叠时前置阻塞或自动收纳（配置可选）。
- 消除 merge 拒绝与 pop 丢弃两类冲突；任何 stash 版去向可追溯。

## 非目标

- 无重叠/干净主树的正常 merge-back 不动。
- 不引入新的人工找回 UI（git stash 既有路径保持）。

## 方案

1. core/worktree_manager.py：MergeConflictInfo 之外新增 merge-back 前置处置入口（如 `pre_merge_wip_gate`）：计算 wip_overlap 并依配置（block | stash）处置；block → 返回明确失败与告警；stash → 可识别前缀 stash、merge 成功后恢复、冲突保留 stash 版并写 last_stash_entry_fate。
2. merge-back 调用点（worktree_manager 内 merge-back 流程主体）接入该入口，取代「预警后仍 merge」路径；pop 冲突分支删除「静默丢弃 stash 版」行为。
3. 兼容：fix-mergeback-stashpop-silent-loss 的既有 autostash/自愈配置保留为兜底开关（默认新语义生效）。
4. 单测覆盖三种场景 + 恢复/去重。

## 测试策略

- 新文件 tests/test_mergeback_wip_overlap_gate.py：重叠阻塞、重叠收纳并恢复、pop 冲突保留 stash 版、无重叠行为不变四类（git 夹具构造重叠场景）。
- 既有 tests/test_worktree_merge_guard.py、test_worktree_reuse.py 回归。