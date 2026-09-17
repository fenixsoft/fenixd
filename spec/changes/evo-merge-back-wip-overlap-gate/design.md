# Design: merge-back-wip-overlap-gate

## 背景与痛点

merge-back 被主树 WIP 与前修改重叠阻塞（09-15 merge 拒绝，阻塞约 1h），且 pop 冲突丢弃 stash 版已两次致内容丢失（09-14/09-15，见草稿 575976971cb8）。现有 wip_overlap 预检仅采集交集并预警（worktree_manager.py:107-110），无执行级处置。

## 目标

- 重叠时前置阻塞或自动收纳（配置可选，默认收纳）。
- 消除闸门作用域内（即 autostash 可覆盖集合，排除 `spec/changes/**`）的 merge 拒绝与 pop 丢弃两类冲突；任何 stash 版去向可追溯。

## 非目标

- 无重叠/干净主树的正常 merge-back 不动。
- 不引入新的人工找回 UI（git stash 既有路径保持）。

## 方案

1. core/worktree_manager.py：MergeConflictInfo 之外新增 merge-back 前置处置入口（如 `pre_merge_wip_gate`）：计算 wip_overlap 并依配置（block | stash）处置；block → 返回带 `wip_gate_blocked=True` 标记的明确失败与告警；stash → 可识别前缀 stash、merge 成功后恢复、冲突保留 stash 条目并写 last_stash_entry_fate。
2. merge-back 调用点（worktree_manager 内 merge-back 流程主体，`merge_back_from_branch` core/worktree_manager.py:2155，锁内、`_detect_wip_overlap` 同点）接入该入口，取代「预警后仍 merge」路径；pop 冲突分支删除「无条件 drop stash 版」的可能路径（现行仅 `_drop_superseded_stash_entry` 证明完全取代时才 drop，core/worktree_manager.py:1648）。
3. 兼容：fix-mergeback-stashpop-silent-loss 的既有 autostash/自愈配置保留为兜底开关（默认新语义生效）。
4. 单测覆盖三种场景 + 恢复/去重。

### 关键约束（防三类失效，详见 specs/worktree/spec.md）

- **闸门作用域**：`_list_dirty_tracked_files`（core/worktree_manager.py:1490-1523）不排除 `spec/changes`，而 `ensure_clean_tree` 的 stash 显式 `:(exclude)spec/changes`（core/worktree_manager.py:1548-1560），且该前缀长期脏（实测主树当前 22 个脏 tracked spec/changes 文件）。故闸门 MUST 排除 `spec/changes/**`：收纳策略对它无效，阻塞策略则几乎阻塞每次 merge-back。该前缀由既有 `ensure_spec_committed`（core/worktree_manager.py:420）/ `_commit_softened_declaration`（core/pm_engine/dispatch.py:1933）收口。
- **默认策略 = stash（收纳）**，block 仅显式配置启用：重叠 ≠ 冲突（core/worktree_manager.py:2192-2194），block 为默认即净回归。
- **阻塞必须豁免熔断**：dispatch 对任 `False` 返回做 `_merge_fp`/`_merge_streak` 记账（core/pm_engine/dispatch.py:1095-1152，阈值 2 → `transition(blocked)`），且 `has_semantic_conflict=False` 不进 repair（dispatch.py:2947-2949）→ 阻塞原样接入会在两次尝试后自动冻结 spec。故新增 dispatch 侧旁路（先例：`rehearsed=True` 豁免，dispatch.py:1090-1094）——**Deliverables 相应增加 core/pm_engine/dispatch.py（modify）**。
- **前缀隔离**：闸门前缀 MUST NOT 含 `AUTOSTASH_MSG_PREFIX`（core/worktree_manager.py:40）子串，否则 `reclaim_stale_autostash`（core/worktree_manager.py:1794 子串匹配 + pop）每 60s 抢走故意保留的条目。
- **「保留 stash 版」= 保留条目 + 记录去向**（`last_stash_entry_fate` core/worktree_manager.py:204/1648 → admin 告警 core/pm_engine/dispatch.py:1706-1762），MUST NOT 把主树留在 UU 态（core/worktree_manager.py:1590-1595 不变量）。
- **无重叠不改行为**：现行 autostash 对任何脏 tracked 主树生效（core/worktree_manager.py:1545-1546），故「无重叠」时 MUST 保持 autostash→merge→pop 现行流程，而非「不做任何 stash」。

## 测试策略

- 新文件 tests/test_mergeback_wip_overlap_gate.py：重叠阻塞、重叠收纳并恢复、pop 冲突保留 stash 条目、无重叠行为不变四类（git 夹具构造重叠场景）。
- 追加用例：闸门阻塞两次后 spec **不**被熔断为 blocked（断言 `_merge_streak` 未累计）；`spec/changes/**` 脏 + 分支同改时闸门不阻塞不收纳（走既有提交通道）。
- 既有 tests/test_worktree_merge_guard.py、test_worktree_reuse.py 回归。