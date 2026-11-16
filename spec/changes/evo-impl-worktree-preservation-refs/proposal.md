# Proposal: impl-worktree-preservation-refs

## Why

worktree 清扫前的实现交付快照从未真正保全过：core/worktree_manager/lifecycle.py:1170 `_snapshot_dirty_worktree` 用 `git stash create`（引用式、不入栈）生成快照 commit，只打 WARNING 日志（:1298-1305 附「recover via: git stash store …」指引），不写任何引用。日志统计「Pre-rmtree snapshot saved」在 2026-11-08~11-10 共 8 次（例行路径），fsck 悬空 commit 中至少 5 个对得上历史快照 SHA——8 次快照无一被人工转正，恢复指引从未成功执行过一次。

后果已逼近兑现：2026-11-10T06:50:38Z 清扫 impl-client-ui-redesign-1794286517 后，run4 全套重实现（9 提交 c3143e5..4306e3f）分支已删、reflog 无锚、零引用可达，仅靠悬空对象与 GC 默认窗口（gc.pruneExpire 未配置，默认 2 周）续命；该 spec 当时正处 impl_budget_exhausted 冻结、三套候选交付待人工裁决，若裁决前发生 gc 即静默折损一套交付。为甄别该风险还额外消耗了一段 arbiter 升级 run（arbiter-client-ui-redesign-1794302874）。

## What Changes

- **快照落真引用（core/worktree_manager/lifecycle.py）**：pre-rmtree 快照从「stash create + 日志指引」改为写入主 gitdir 共享引用 refs/preservation/<run_id>（指向快照 commit），GC 天然可达；指引文案同步更新为引用名。
- **引用生命周期（core/worktree_manager/stale_sweep.py）**：preservation 引用默认保留，仅在 spec 终态（merge-back 决策完成/人工消费）后随清扫删除；终态 impl 分支删除窗口与 preservation 引用对齐。
- **单测**：覆盖快照引用落盘、GC 可达、终态清理、指引文案一致性。

## Capabilities

### impl-delivery-preservation

见 specs/impl-delivery-preservation/spec.md。

## Impact

- core/worktree_manager/lifecycle.py 快照函数与日志文案。
- core/worktree_manager/stale_sweep.py 清扫逻辑增加 preservation 引用处理。
- refs/preservation/* 为新增引用命名空间，不影响既有 refs/stash、refs/heads 行为；不改 fast-track 冻结保全（在途 SPEC 范围）。