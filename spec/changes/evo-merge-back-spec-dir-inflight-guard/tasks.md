# Tasks: merge-back-spec-dir-inflight-guard

## Deliverables

```yaml
- path: core/worktree_manager/mergeback.py
  kind: modify
- path: core/worktree_manager/types.py
  kind: modify      # 顺延信号载体（MergeConflictInfo 新增布尔字段，与 rehearsed/wip_gate_blocked 同型）
- path: core/pm_engine/dispatch/queue.py
  kind: modify
- path: core/state_machine.py
  kind: modify      # 非派发调用方顺延语义（_recovery_remerge_pending 不消费 _repair_awaiting_remerge）
- path: core/pm_engine/dispatch/repair_lane.py
  kind: modify      # 非派发调用方顺延语义（repair re-merge 保留标记）
- path: core/pm_engine/dispatch/fast_track.py
  kind: modify      # 非派发调用方顺延语义（fast-track 成功路径不推进状态）
- path: core/pm_engine/dispatch/rollback.py
  kind: modify      # 顺延超限回落告警（_report_mergeback_spec_dir_inflight_stuck，对齐 _report_mergeback_wip_overlap）
- path: core/admin_monitor.py
  kind: modify      # 信号收录（mergeback_spec_dir_inflight_stuck：STORED_SIGNAL_TYPES + severity）
- path: tests/test_merge_back_spec_dir_guard.py
  kind: new
# 若顺延上限落在非派发调用方（state_machine / repair_lane / fast_track），
# 其改动文件 MUST 补入本清单；仅 dispatch 侧需要时不得无谓改动这三个文件。
```

## 0. 定点与闸门顺序（前置，防顺序回归）

- [x] 0.1 core/worktree_manager/mergeback.py：卫检查插点固化为「`_rehearse_merge_from_branch`（mergeback.py:77）→ `_wip_overlap_gate`（mergeback.py:96）→ **本卫检查** → `ensure_clean_tree`」；断言「主树存在语义冲突且 spec 目录脏」时返回 `rehearsed`（而非顺延），「WIP 重叠且目录脏」时返回 `wip_gate_blocked`（而非顺延）
- [x] 0.2 core/pm_engine/dispatch/queue.py：可重试分类插点固化为「`rehearsed`（queue.py:1306）→ `wip_gate_blocked`（queue.py:1320）→ **本分类** → 指纹熔断记账」；断言 rehearsed / wip_gate_blocked 形态不被本分类接走（不误判为可重试）

## 1. merge-back 前在飞编辑卫检查

- [x] 1.1 core/worktree_manager/types.py：`MergeConflictInfo` 增加顺延字段（如 `spec_dir_inflight: bool = False`），保持 `(success, err)` 解包契约（types.py:11-25）
- [x] 1.2 core/worktree_manager/mergeback.py：merge_back_from_branch 入口对 `spec/changes/<spec>/`（**整个目录，含 specs/**、proposal/design/tasks**）执行 `git status --porcelain -- <rel>` 未提交改动检测（含 untracked），命中即返回顺延信号（reason=spec_dir_inflight），不进入 merge、不 stash、不触碰主树
- [x] 1.3 core/worktree_manager/mergeback.py：spec 名解析复用 `_spec_from_branch`（queries.py:43）；解析失败（返回 None/非 str）→ 放行现行流程（fail-open），断言此时**不**做 `spec/changes/` 全目录检测
- [x] 1.4 core/worktree_manager/mergeback.py：顺延信号携带等待语义（对齐 evo-recovery-watch-status-recheck 的顺延范式），由调度方重排而非判失败
- [x] 1.5 非派发调用方语义：`state_machine._recovery_remerge_pending`（state_machine.py:1284）与 repair re-merge（repair_lane.py:361）遇顺延如实返回 False 但 **MUST NOT** 消费 `_repair_awaiting_remerge` 标记（原样保留待下轮）；fast-track 成功路径（fast_track.py:490）遇顺延不推进状态。三处各留一条断言或显式豁免依据

## 2. merge-back 失败分类与仅重试合并

- [x] 2.1 core/pm_engine/dispatch/queue.py：失败分支区分「可重试（主树脏 / spec 在飞编辑 / 锁冲突）」与「run 真失败」——带 git 退出码文本者锚定原文片段（`would be overwritten by merge` / `would be lost`）；不带文本者用结构化字段（顺延 `spec_dir_inflight`、既有锁冲突信号）判据；判不准 fail-open 回现行指纹熔断
- [x] 2.2 core/pm_engine/dispatch/queue.py：可重试时 spec 保持 implementing、保留 branch/implementer_run，逐项不动 `_retry_count` / `_merge_fp` / `_merge_streak` / `_redispatch_same_cause_streak` / `_redispatch_cause_fp`；**不进入**「新轮次派发清除旧锚点」分支（queue.py:1390+）
- [x] 2.3 core/pm_engine/dispatch/queue.py：重试排程复用既有短程无预算定时器（`_schedule_instant_fail_recovery` / `_schedule_signal_kill_recovery` / `_schedule_backoff_retry`，backoff.py:107-200）；MUST NOT 复用 `_schedule_transient_recovery`（带 transient 熔断/预算语义）
- [x] 2.4 core/pm_engine/dispatch/queue.py：实现尝试预算不计入——仅当未派生新实现 run 时成立；如需回退计数走既有 `bump_impl_budget(-1)` 事后回退口径（budget.py:185-260 的 `_exempt_dead_run_budget` / `_exempt_infra_run_budget` 同型），不另造旁路记账；断言 `_reconcile_impl_budget` 不因本条路径产生偏差告警
- [x] 2.5 core/pm_engine/dispatch/queue.py：顺延/重试**有界**——固化顺延窗口（`mergeback.spec_dir_inflight_grace_minutes`，缺省 30，自首次顺延起算）与顺延轮数上限（缺省 3 轮）；上限先于 `agents.impl_run_budget`（缺省 6）耗尽收敛；超限回落既有「告警 + 等待人工处置」通道（对齐 `_report_mergeback_wip_overlap`），并断言该回落路径对该 spec 可见（周期巡检对 ready 态在飞等待不可见）
- [x] 2.6 core/pm_engine/dispatch/queue.py：重试点 MUST 经过既有实现预算闸门（`_check_impl_budget_exhausted`，budget.py:443），不得绕过 `impl_budget_exhausted` 告警/人工通道
- [x] 2.7 放弃（超上限）时分支清理延迟语义：MUST NOT 静默丢弃分支，走既有 repair/熔断/人工通道

## 3. 测试

- [x] 3.1 tests/test_merge_back_spec_dir_guard.py：`spec/changes/<spec>/` 有未提交改动（含仅 `specs/**` 脏、仅 untracked 文件）时 merge-back 顺延不 merge（构造脏树单测），且主树零污染（无 stash 条目、HEAD 不变）
- [x] 3.2 tests/test_merge_back_spec_dir_guard.py：合并失败分类后可重试路径仅重试合并而非重派实现（实现 run_id 不变断言），且 `_retry_count` / `_merge_fp` / `_merge_streak` 均未变化
- [x] 3.3 tests/test_merge_back_spec_dir_guard.py：顺延**有界**——连续顺延达上限后回落到告警/人工通道（非无限顺延），且失败分支的 `_repair_awaiting_remerge` 标记未被消费
- [x] 3.4 tests/test_merge_back_spec_dir_guard.py：闸门顺序回归——语义冲突形态返回 `rehearsed`、WIP 重叠阻塞形态返回 `wip_gate_blocked`，二者均不被顺延信号或可重试分类接走
- [x] 3.5 tests/test_merge_back_spec_dir_guard.py：spec 名解析失败（非 `fenix/<spec>-<ts>` 分支名）时 fail-open 放行，断言未对 `spec/changes/` 全目录做检测
- [x] 3.6 回归：`tests/test_worktree_merge_guard.py`（WIP 重叠闸门与 self-heal 同族用例，含 `_discard_identical_local_changes`）、`tests/test_worktree_wip_artifact_scope.py`、`tests/test_merge_tree_rehearsal.py`、`tests/test_mergeback_repair_lane.py`、`tests/test_worktree_stray_and_identical.py` 全绿（本变更插点不得改变其既有语义；清单由 `grep -rln "_wip_overlap_gate\|would be overwritten" tests/` 取证得出）
