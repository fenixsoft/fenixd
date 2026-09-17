# Proposal: merge-back-wip-overlap-gate

## Why

merge-back（实现分支合回主树）时主树存在与分支改动重叠的未提交 WIP：现状（fix-mergeback-stashpop-silent-loss 已归档）只做「autostash + WIP 重叠预检（仅产出告警文本）+ pop 冲突自愈（丢弃 stash 版保留合并版）」。后果两类：①merge 拒绝——2026-09-15T18:55:16Z「Merge failed... would be overwritten by merge: spec/changes/refactor-dashboard-data-module/tasks.md」，refactor-dashboard-data-module 合并被阻塞约 1h（03:47 aa30a492 才合并）；②pop 丢弃——09-09 修复后 5 天内复发 2 次（09-14 丢 SuggestedImprovementsPanel.tsx、09-15 00:09 丢 core/admin_store.py，后者含 AdminStore 序列化必要改动）。已核实的代码现状：core/worktree_manager.py:107-110 wip_overlap 预检「只预警不阻断」。

## What Changes

- merge-back 前主树 WIP 重叠预检升级：与分支改动重叠时 MUST 前置阻塞（告警 + 中止合并，附可执行处理指引）或自动 stash 收纳（可识别前缀、合并成功自动恢复、冲突时保留 stash 版供找回），从源头消除 merge 拒绝与 pop 丢弃两类冲突。
- 不再静默走「pop 冲突→自愈丢弃」；仅在显式确认后继续。

## 非目标

- 不改变无重叠/主树干净的正常 merge-back 行为。
- 不替代 git stash 的人工找回流程（仅从源头减少丢弃发生）。