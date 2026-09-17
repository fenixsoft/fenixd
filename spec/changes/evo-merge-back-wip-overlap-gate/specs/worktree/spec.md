# Spec Delta: worktree

## NEW Requirements

### Requirement: merge-back 前主树 WIP 重叠处理不再静默丢弃

merge-back 流程在合并前 MUST 执行主树 WIP 重叠预检（复用 `MergeConflictInfo.wip_overlap`，core/worktree_manager.py:107-110）：
- 重叠非空时，MUST 二选一执行：(a) 前置阻塞——中止合并并输出告警（列出重叠文件、影响分支、处理指引：提交或 stash 后再合）；或 (b) 自动收纳——以可识别前缀（复用 AUTOSTASH_MSG_PREFIX=「fenix: pre-dispatch autostash」同族）stash 主树 WIP，合并成功自动恢复，pop 冲突时保留 stash 版（人工可找回核对）而非丢弃合并前版本；
- MUST NOT 在重叠时静默走「pop 冲突→自愈丢弃 stash 版」；
- wip_overlap 预检从「只预警」升级为「阻塞或收纳」的执行前置。

**背景（实测依据）**：2026-09-15T18:55:16.385668Z merge 拒绝（tasks.md overwritten，阻塞约 1h 至 03:47 aa30a492）；草稿 575976971cb8 记载 09-14/09-15 两次 pop 丢弃。

#### Scenario: 重叠时前置阻塞

- **WHEN** 主树脏 tracked 文件与分支改动有交集（wip_overlap 非空）且配置采取阻塞策略
- **THEN** merge-back 中止，输出告警含重叠文件清单与处理指引，返回失败（可重试）而非合并失败后裸 ERROR

#### Scenario: 重叠时自动收纳并恢复

- **WHEN** 重叠非空且配置采取自动 stash 收纳策略
- **THEN** 可识别前缀 stash 收纳 → 合并 → 成功自动恢复主树 WIP；pop 冲突时保留 stash 版并记录去向（last_stash_entry_fate）供人工找回

#### Scenario: 无重叠行为不变

- **WHEN** 主树干净或无重叠
- **THEN** 既有 merge-back 行为完全不变（不做任何 stash/阻塞）