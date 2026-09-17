# Spec Delta: worktree

## NEW Requirements

### Requirement: merge-back 前主树 WIP 重叠处理不再静默丢弃

merge-back 流程在合并前 MUST 执行主树 WIP 重叠预检（复用 `MergeConflictInfo.wip_overlap`，core/worktree_manager.py:107-110）：
- 重叠非空时，MUST 二选一执行：(a) 前置阻塞——中止合并并输出告警（列出重叠文件、影响分支、处理指引：提交或 stash 后再合）；或 (b) 自动收纳——以可识别前缀 stash 主树 WIP，合并成功自动恢复，pop 冲突时保留 stash 版（人工可找回核对）而非丢弃合并前版本；
- MUST NOT 在重叠时静默走「pop 冲突→自愈丢弃 stash 版」；
- wip_overlap 预检从「只预警」升级为「阻塞或收纳」的执行前置。

**背景（实测依据）**：2026-09-15T18:55:16.385668Z merge 拒绝（tasks.md overwritten，阻塞约 1h 至 03:47 aa30a492；`.fenix/todo.md:107-108`、`.fenix/admin_alerts.json` fp=b31afc216847）；草稿 575976971cb8 记载 09-14/09-15 两次 pop 丢弃。

#### 闸门作用域（MUST，防止「永远阻塞」与「无效收纳」两种失效）

- 既有 autostash 显式排除 `spec/changes`（core/worktree_manager.py:1548-1560 的 `:(exclude)spec/changes`，理由是 SPEC 文件被卷走会让 implementer 空转），而 `_list_dirty_tracked_files`（core/worktree_manager.py:1490-1523）**不排除**该前缀 → 原样复用会同时得到两种失效：收纳策略对 `spec/changes/**` 无效（stash 不含它，merge 仍被 `local changes would be overwritten` 拒绝），阻塞策略则因该前缀**长期脏**（实测主树当前即有 22 个 `spec/changes/**` 脏 tracked 文件）而几乎阻塞每一次 merge-back。
- 闸门判定的重叠集合因此 MUST 与 stash 可覆盖集合一致：`wip_overlap` 中位于 `spec/changes/` 下的路径 MUST 不参与闸门决策（既不计入阻塞、也不计入收纳触发）。
- `spec/changes/**` 的「主树脏 + 分支同改」情形由**既有提交通道**收口，不由本闸门处理：`ensure_spec_committed`（core/worktree_manager.py:420，调用点 core/pm_engine/dispatch.py:716、2517）与 `_commit_softened_declaration`（core/pm_engine/dispatch.py:1933，软化写盘后立即提交）。本 SPEC MUST NOT 为 `spec/changes/**` 引入新的 stash/阻塞语义。

#### 策略默认值（MUST 明示）

- 默认策略 MUST 为**自动收纳（stash）**——与现行 autostash 语义连续、不新增阻塞；**阻塞（block）MUST 仅在显式配置时生效**。
- 理由（regression 约束）：重叠 ≠ 必然冲突（core/worktree_manager.py:2192-2194 既有注释「不同 hunk 可自动合并」），以 block 为默认会把当前可自动完成的合并转为失败，属净回归。

#### 阻塞路径 MUST NOT 落入 merge 熔断

- 阻塞是「前置拦截」，不是「merge 失败」。调度层对 `merge_back_from_branch` 任 `False` 返回一律做指纹熔断记账（core/pm_engine/dispatch.py:1095-1152；`streak >= merge_breaker_threshold`（默认 2）→ `transition(blocked)`），且 `has_semantic_conflict=False` 时连 repair 通道也不进（core/pm_engine/dispatch.py:2947-2949）→ 阻塞策略原样接入会在两次尝试后把 spec 自动冻结为 `blocked`，比现状（人工 1h 内解开）更差。
- 因此阻塞返回 MUST 携带可区分的结构化标记（如 `wip_gate_blocked=True`），调度层 MUST 据此跳过 `_merge_fp`/`_merge_streak` 记账与 ready 降级——先例：预演语义冲突以 `rehearsed=True` 走同一类豁免（core/pm_engine/dispatch.py:1090-1094）。

#### stash 前缀 MUST 与既有巡检隔离

- 闸门收纳/保留条目所用前缀 MUST NOT 包含 `AUTOSTASH_MSG_PREFIX`（core/worktree_manager.py:40）子串：`reclaim_stale_autostash` 以子串匹配栈顶（core/worktree_manager.py:1794 `AUTOSTASH_MSG_PREFIX not in top`）并会 pop 该条目——若复用同前缀，被故意保留待人工找回的闸门条目会被周期巡检（fenixd.py:526-529，每 60s）抢走，去向记录随即失真。

#### 「保留 stash 版」的确定语义（MUST，避免与既有不变量冲突）

- 「保留 stash 版」= **保留 stash 条目**并记录去向（`last_stash_entry_fate`，core/worktree_manager.py:204/1648；admin 告警消费点 core/pm_engine/dispatch.py:1706-1762），**不是**把主树留在 UU 未合并态——后者会令 index 半合并、index.lock 满、后续 git 写操作瘫痪（core/worktree_manager.py:1590-1595 的既有不变量）。
- 条目 MUST NOT 被无条件 drop：现状仅在树级 diff 证明 stash 版已被合并结果**完全取代**时才 drop（`_drop_superseded_stash_entry`，core/worktree_manager.py:1648/1676-1699），其余情形条目保留并打印逐文件找回命令。「删除静默丢弃」应落为「保留**无条件** drop 路径的删除 + 去向可见」，而非删除既有「可证取代才 drop」的正确判定。

#### Scenario: 重叠时前置阻塞

- **WHEN** 主树脏 tracked 文件与分支改动有交集（闸门作用域内的 `wip_overlap` 非空）且配置采取阻塞策略
- **THEN** merge-back 中止，输出告警含重叠文件清单与处理指引，返回带 `wip_gate_blocked` 标记的失败；该失败 MUST NOT 计入 `_merge_fp`/`_merge_streak`，spec MUST NOT 因此被熔断为 `blocked`

#### Scenario: 重叠时自动收纳并恢复

- **WHEN** 闸门作用域内重叠非空且采取默认自动 stash 收纳策略
- **THEN** 可识别前缀 stash 收纳 → 合并 → 成功自动恢复主树 WIP；pop 冲突时保留 stash 条目（仅当树级 diff 证明被合并结果完全取代才 drop）并记录去向（`last_stash_entry_fate`）供人工找回，主树 MUST 不残留 UU 未合并态

#### Scenario: spec/changes 重叠不走闸门

- **WHEN** 重叠仅存在于 `spec/changes/**`（如主树 tasks.md 脏且分支同改）
- **THEN** 闸门不阻塞、不收纳；该情形沿用既有提交通道（`ensure_spec_committed` / `_commit_softened_declaration`）收口

#### Scenario: 无重叠行为不变

- **WHEN** 主树干净或无重叠
- **THEN** 既有 merge-back 行为完全不变：仍走现行 autostash→merge→pop 流程（`ensure_clean_tree` 对脏 tracked 主树照常收纳、成功恢复，core/worktree_manager.py:1545-1575/2197-2206），闸门 MUST NOT 新增任何阻塞或额外 stash