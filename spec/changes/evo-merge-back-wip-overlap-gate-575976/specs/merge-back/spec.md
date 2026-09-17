# merge-back Capability Spec

## 变更点

- `worktree_manager` merge-back 前：WIP 重叠检测命中（主树脏 tracked 与分支改动路径重叠）时，不再直接进入 stash→merge→pop；改为阻塞并告警（或自动将重叠改动收纳为新 stash 条目并标记待回收），重叠被人工确认/收纳后方继续。
- `restore_after_merge` 自愈路径保留，但「丢弃 stash 版」必须是显式决策的结果，杜绝无提示静默丢弃。
- dispatch 层告警文案升级：含重叠文件清单、`git stash show` 找回命令、处置指引，且升级路径不再依赖可能崩坏的序列化字段（evidence 一律先序列化为 str）。

## 判定语义

- 主树脏 tracked 与分支改动无重叠 → 行为不变（当前路径）。
- 有重叠且未确认 → merge-back 阻塞，产出 major 告警，等待人工确认或自动收纳。
- 有重叠且已收纳/人工确认 → 继续 merge-back，合并结果优先，重叠改动进 stash 并留待回收。