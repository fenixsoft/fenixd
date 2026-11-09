# Proposal：fast-track 冻结实现分支现场保全

## 问题

fast-track 车道重试耗尽冻结转人工时，实现分支（可能携带全部已验证实现提交）未被现场保全：分支与 worktree 被无快照清理，`_frozen_hold` 不置位、STATE `branch` 锚点为空——unfreeze 的续做通道（`_frozen_hold → _resolve_preserved_branch → _recovery_resume`）因此不可用，解冻后 dispatch 只能从零新建分支，已完成的实现被整体丢弃。

## 证据（2026-11-09 cloud-phone single-app-realdevice-retest 实证）

| 环节 | 事实 | 锚点 |
|---|---|---|
| 冻结入口 | fast-track 重试耗尽两处直接调 `freeze_for_human`，该入口只写 status/frozen/error/告警，**无任何 worktree/分支保全逻辑** | `core/pm_engine/dispatch/fast_track.py:1079`、`core/pm_engine/dispatch/fast_track.py:2168`；`core/state_machine.py:2291`（freeze_for_human） |
| 保全机制存在但未覆盖此路径 | `mark_frozen_hold` 在 frozen-terminated、验证管线、repair_lane、queue、spec_review 等路径均有调用，唯独 fast-track 重试耗尽路径没有 | `core/pm_engine/dispatch/fast_track.py:280`、`core/pm_engine/verification/pipeline.py:2948`、`core/pm_engine/dispatch/repair_lane.py:665`、`core/pm_engine/dispatch/queue.py:2744`、`core/pm_engine/spec_review.py:634` |
| 快照机制存在但未触发 | worktree 清理端的 pre-rmtree snapshot 正常工作（m3/p2p/m0 均有快照提交），single-app 的分支被删时无快照产生 | `core/worktree_manager/lifecycle.py:1283`；分支删除段 `core/worktree_manager/lifecycle.py:839-1012`（implementer 失败应走 register_legacy 遗产保留） |
| 清理嫌疑路径 | 重试期间 worktree 由 `_keep_fast_track_worktree` 保留（worktree-reuse），冻结后某条清理路径（stale sweep / 遗产清理 / 冻结收尾）无快照删除了分支+worktree——具体删除者待实现期定位 | `core/pm_engine/dispatch/fast_track.py:693`（_keep_fast_track_worktree）、`core/worktree_manager/stale_sweep.py` |
| 后果 | 悬空对象被 `git gc` 回收即全丢；抢救需人工 fsck + 手工补 STATE 锚点 | unfreeze 续做判定 `core/state_machine.py` `_resolve_preserved_branch`（三层解析 + rev-list 非空闸门 + resolve_resume_site 载体三态） |

## 目标

1. **不变量**：fast-track 冻结转人工时，凡实现分支相对解析基线存在未合并提交，MUST 在冻结同一原子窗口内完成现场保全——pre-rmtree snapshot（或等效快照提交）+ 分支保留 + `_frozen_hold: True` + STATE `branch` 锚点回写。
2. 冻结后任何清理路径（stale sweep、遗产清理、worktree GC）MUST NOT 删除处于 `_frozen_hold`/已保全状态的实现分支与 worktree。
3. 冻结→解冻→续做全链可回归验证：unfreeze_spec 在该场景 MUST 命中 `_resolve_preserved_branch` 续做通道（`_recovery_resume: True`、分支/实现 run 锚点保留），而非从零重派。

## 非目标

- 不改动 unfreeze/续做通道本身（`_resolve_preserved_branch` 及三层解析已验证可用，本次事故中人工补齐锚点后即走通）。
- 不改动 freeze_for_human 的告警/blocked 分类契约（fix-blocked-freeze-classification D2）。
- 不涉及 full 车道、verifier 车道的既有保全语义（它们已有 mark_frozen_hold 调用）。

## 成功标准

- 回归测试复现 single-app 形态：fast-track partial ×N → 重试耗尽冻结 → 断言分支存在、含实现提交、`_frozen_hold: True`、STATE `branch` 非空、存在快照；随后 unfreeze 断言 `_recovery_resume: True` 且续做分支正确。
- 清理路径守护测试：对 `_frozen_hold` spec 的分支/worktree 执行 sweep/GC 入口，断言不删。
- 云端实证复验：修复合入后，任一 fast-track 重试耗尽冻结的 spec 面板与 STATE 均呈现保全现场。
