# design: merge-back-spec-dir-inflight-guard

## D1 卫检查：spec/changes 在飞编辑检测

- 位置：core/worktree_manager/mergeback.py merge_back_from_branch 入口（_wip_overlap_gate 同级）。
- 实现：git status --porcelain 限定 spec/changes/ 目录检测未提交改动，命中即返回顺延信号（reason=spec_dir_inflight），不触发 merge；调用方（core/pm_engine/dispatch/queue.py）识别后重排等待而非失败。
- 顺延范式对齐 evo-recovery-watch-status-recheck（在飞 SPEC `spec/changes/evo-recovery-watch-status-recheck/`）：等待下一次 recovery/心跳时点重试。**但该先例的「不新增硬超时上限」MUST NOT 照搬**——先例的观察项在顺延期间仍占用每 15min 复查节拍且观察项本身长期在册，本 SPEC 的顺延会**暂停对 spec 的唯一驱动**，故 MUST 设有界上限（见 D1a）。
- **信号置于既有闸门之后（顺序约定）**：`merge_back_from_branch` 在 `_main_tree_lock` 内**先**跑 `_rehearse_merge_from_branch`（mergeback.py:77）与 `_wip_overlap_gate`（mergeback.py:96），本卫检查 MUST 置于二者**之后**、`ensure_clean_tree` **之前**——即「语义冲突（rehearsed）→ WIP 重叠阻塞（wip_gate_blocked）→ spec 目录在飞编辑顺延 → 放行 merge」的固定优先级。三者均为主树零污染早退，顺序不改变各自判定结果，但 MUST 固化以防实现者把顺延信号置于预演闸之前，从而掩盖真实语义冲突（会把「需 repair 的冲突」误报为「等待提交」）。

### D1a 解除条件与有界性（评审补：必须有解除者，否则顺延=无限期停摆）

- **解除者必须点名（MUST）**：顺延等待的解除条件是「主树 spec/changes/<spec>/ 变干净」，而**库内没有任何通道为「已 ready / implementing 的在飞 spec」提交 spec/changes**——`ensure_spec_committed` 只在**派发实现前**调用（queue.py:831、fast_track.py:142），`_sync_task_progress` 只在 **merge 成功后**调用（queue.py:1465）且工作树脏时直接跳过（engine.py:1535-1538）。故 MUST 显式指定解除者，二选一：
  - **(i) 保持既有重排节拍（推荐）**：顺延**不注销** spec 的调度语义——每轮重排仍返回顺延（幂等、零副作用、不计入 `_retry_count` / `_merge_streak` / `_merge_fp`、不递增实现尝试预算、**不进入**「新轮次派发清除旧锚点」分支，queue.py:1390+），由外部提交动作自然解除；**且必须设置上限**（见下条）。
  - **(ii) 自愈提交**：同一 spec 连续顺延达 N 轮（N 固化，缺省 3）后，调用既有 `ensure_spec_committed(spec_name)`（lifecycle.py:331）自动收口该目录——该函数已按 spec 目录做 status/add/commit 全流程。选 (ii) MUST 在 tasks 留依据行，并注意它会把「用户正在编辑的 spec 文档」一并提交（与 fix-merge-back-deadlock 的既有语义一致，可接受）。
- **必须设硬上限（MUST，对齐 evo-recovery-watch-status-recheck 的 `transition_grace_minutes` 有界性）**：顺延窗口固化 `mergeback.spec_dir_inflight_grace_minutes`（命名默认，缺省 **30**），自首次顺延起算；到期仍未解除 → MUST 回落到既有通道（发 admin 告警 + 走既有 `_report_mergeback_wip_overlap` 同型的「等待人工处置」直通），MUST NOT 无限顺延。**理由（事故实证）**：本 SPEC 立项事故中，正是「约 11 分钟后系统重新派发实现整轮」**结束了**停摆；若把该重派换成无上限顺延，则变成「spec 永远不再被处理」——比事故更差（原事故至少收敛）。上限是「不重派」与「不停摆」之间的唯一保障。
- **周期巡检不覆盖此窗口（故不能指望它兜底）**：`admin_monitor` 的 orphaned_state 探测只扫 `implementing`/`testing`（admin_monitor.py:1399-1401），ready 态不在其列；`event_bus.recover_orphan_ready` 只扫 `ready` 态（event_bus.py:491）。顺延中的 spec 若落在 ready 态，两者皆不可见——上限落地后 MUST 由本 SPEC 自己的告警出口可见（见上条）。
- **子目录粒度与卫检查范围（MUST）**：检测范围固定为该 spec 的整个目录 `spec/changes/<spec>/`（**含** `specs/**`、proposal/design/tasks；`git status --porcelain -- spec/changes/<spec>` 天然递归）——**MUST NOT** 只检 `tasks.md`：事故实测脏文件是 tasks.md，但 reviewer 修补的是 proposal/design/specs（同一事故族的 `refactor-dashboard-data-module` 亦为 tasks.md，见 .fenix/logs/fenixd.log:13510 附近），任一同层文件脏都会以同样方式拒绝 merge。
- **spec 名解析口径（MUST）**：MUST 复用 `_spec_from_branch`（queries.py:43），并对其**返回 None / 非 str** 的情形显式豁免（**MUST NOT** 在此情形顺延——`_spec_from_branch` 对非 `fenix/<spec>-<ts>` 形态返回 None，若把 None 塞进路径查询会命中整个 `spec/changes/`，把「人正在改别的 spec」误判为本 spec 受阻）；解析失败 → 放行现行流程（fail-open，主树零新增阻塞）。已知精度边界（本 SPEC 不修，记录在案）：`_spec_from_branch` 按「末段纯数字」切分，spec 名自身以数字段结尾时会误解析（如 `evo-merge-back-wip-overlap-gate-575976`）——该边界为既有 helper 的既有行为，且 `evo-recovery-watch-transition-guard` D1 已对同类解析另立精确口径，本 SPEC 沿用既有 helper 以保持与 merge-back 链路单源。
- **主树 ≠ 分支（MUST NOT 混淆）**：`git status` **无法**说明分支里是否有同名改动（`ensure_spec_committed` 的文档正指出「主树 untracked + 分支同名路径」形态，lifecycle.py:331-336）；故**顺延的解除者不能是"分支侧提交"**——解除只取决于**主树**侧的提交动作（见 D1a 点名）。
- **必须只读（MUST）**：检测 MUST 只读（`git status --porcelain` + 既有 early-return），MUST NOT 为解除该状态而就地 `git add/commit` 或 `checkout` 主树——主树 spec 目录的提交通道是既有 `ensure_spec_committed`（见 D1a）。
- **返回值载体（MUST）**：顺延信号 MUST 走既有 `MergeConflictInfo` 新增布尔字段（如 `spec_dir_inflight=True`）承载，与 `rehearsed` / `wip_gate_blocked` 同型（**MUST NOT** 另造返回类型，否则破坏 `success, err = ...` 解包契约，types.py:11-25）；调用方 MUST 按该字段早退，且**MUST NOT** 计入 `_merge_fp` 指纹。
- **非派发调用方同样受卫检查约束（MUST）**：`merge_back_from_branch` 另有三个非 dispatch 调用方——`state_machine._recovery_remerge_pending`（state_machine.py:1284，daemon 重启恢复）、`repair_lane._run_repair_worker` 的 re-merge（repair_lane.py:361）、`fast_track` 成功路径（fast_track.py:490）。顺延信号在**这些**调用方处的语义 MUST 明确定义：后两者的现状是「merge 失败 → 清 `_repair_awaiting_remerge` 标记 + 回落保留续做」——对顺延形态 MUST NOT 消费该标记（那会让「仅剩合并」的分支退回全新派发），而应**原样保留标记、留待下一轮恢复/重排再试**（等价于「视为尚未尝试合并」）。tasks 须为这三处各留一条断言或显式豁免依据。**取证注**：`_recovery_remerge_pending` 仅在 daemon 重启时触发一次、`fast_track` 在同一轮内失败即返回，故该形态在这两处是**有界短窗**（不自旋）；风险集中在 dispatch 调用方（每轮重排都会再次命中），故有界上限 MUST 落在该处（见 D2）。

## D2 失败分类与仅重试合并

- 位置：core/pm_engine/dispatch/queue.py merge-back 失败分支。
- **分类位置 MUST 在既有早退分支之后**：`merge_back_from_branch` 失败返回值现行按序早退——`rehearsed=True`（预演语义冲突 → `_direct_rehearsed_to_repair`，queue.py:1306-1310）→ `wip_gate_blocked=True`（闸门阻塞 → `_report_mergeback_wip_overlap`，queue.py:1320-1324）→ 指纹熔断/repair/ready 降级。本变更的可重试分类 MUST 插在**这两个早退之后、指纹熔断记账之前**：预演冲突（add-merge-tree-rehearsal D1）与闸门阻塞均**不产生 git 退出码文本**，不进本分类；反之若分类前置，会以「错误文本匹配」把「语义冲突（rehearsed）」或「闸门阻塞」误判为可重试，绕过 repair 通道与既有告警出口——属净回归。
- **rehearsed 的边界说明（复审探针实测）**：预演闸（`_rehearse_merge_from_branch`，mergeback.py:77）以 `git merge-tree --write-tree <branch> HEAD` 只从**提交**计算合并树，**完全无视工作区脏状态**——探针实测（干净临时仓库，主树 `spec/changes/s/tasks.md` 与 `f.txt` 均为已提交文件的未提交修改）：`merge-tree --write-tree` 返回 **0** 且输出 tree oid（不进冲突态），而同一状态下 `git merge --no-ff` 复现事故原文 `error: Your local changes to the following files would be overwritten by merge: f.txt, spec/changes/s/tasks.md … Aborting / Merge with strategy ort failed.`。即：**本 SPEC 治理的形态不会被预演闸提前拦截**（`rehearsed=False` 一路放行到真合并才失败），D1 卫检查与 D2 分类均为必要新增，与 rehearsed 零重叠。该实测亦解释了事故日志为何只有 `Self-heal (identical) aborted` + `Merge failed` 而**没有** rehearsed 分支介入。
- **分类判据须点名匹配面（MUST）**：可重试 = 「主树脏 / spec 在飞编辑 / 锁冲突」，实现 MUST 显式声明匹配的是哪一层文本——
  - **可携带 git 退出码文本**：`_wip_gate_blocked`（既有字段，不重定义）与 mergeback 内 `_merge_back_from_branch_locked` 的 **self-heal 重试后仍失败**路径（mergeback.py:607-720：`_untrack_ignored_local_changes` / `_discard_identical_local_changes` 兜底均未化解时的 `"Your local changes to the following files would be overwritten by merge"` / `"local changes … would be lost"`）。
  - **无法匹配退出码文本（MUST 用结构化字段，禁用文本匹配）**：D1 的 spec 目录在飞编辑顺延（`reason=spec_dir_inflight`，在 merge 之前返回，**无 git 退出码**）与 dispatch 级锁冲突（`_queue_lock` / `main_tree_lock` 获取失败，见 `_clear_dispatch_conflict` 家族）——二者 MUST 分别以 `spec_dir_inflight` 与既有锁冲突信号判据识别；靠「错误文本含 lock」会把任何含该词的真失败误判为可重试（假阴性方向：真实失败被无限重试）。
  - **文本匹配 MUST 锚定 git 原文片段**（`would be overwritten by merge` / `would be lost`），MUST NOT 用宽泛正则（如单独 `overwritten`）；并 MUST 声明该分类为 **fail-open 到既有通道**：判不准 → 走既有指纹熔断/repair/ready 降级（现行行为），而非可重试。
- **可重试处置的记账口径（MUST，逐项点名）**：可重试时 spec 保持 **implementing**（不降级 ready——避免落入「新轮次派发清除旧锚点」，queue.py:1390+），保留 implementer_run 锚点与分支引用，**且逐项不动**：`_retry_count`、`_merge_fp` / `_merge_streak`、`_redispatch_same_cause_streak` / `_redispatch_cause_fp`（后两者由 `_redispatch_cause_fingerprint` 记账，queue.py:1590+）。**不递增的只是一个预算**：实现尝试预算（`_impl_run_budget_used` / `agents.impl_run_budget`），且仅当本条路径确实**未启动新实现 run** 才成立——若为重试点顺带派发了新 run，MUST 正常递增（对照 fix-budget-counting-semantics：计数跟「启动 run」不跟「失败事件」）。
- **重试点与预算耗尽（MUST）**：重试点复用既有**短程无预算定时器**范式——`_schedule_instant_fail_recovery` / `_schedule_signal_kill_recovery` / `_schedule_backoff_retry`（backoff.py:107-200，均只走 `_on_spec_ready`、**不递增** `_retry_count`，见 backoff.py:51）。MUST NOT 复用 `_schedule_transient_recovery`（该通道带 `agents.transient_*` 熔断与预算语义，语义不同）。**预算耗尽 MUST NOT 被本通道绕过**：`_check_impl_budget_exhausted`（budget.py:443）现由派发前的预算闸门评估；重试点重入 `_on_spec_ready` 时该闸门同样生效，故本通道 MUST NOT 在闸门之前抢先重试——实现须确认重试点路径经过同一闸门，否则会绕过 `impl_budget_exhausted` 告警与人工通道。
- **重试上限与本 SPEC 自身预算的关系（MUST，边界约定）**：本通道另有自己的上限——D1 顺延上限（`mergeback.spec_dir_inflight_grace_minutes`，缺省 30min）与「顺延/重试轮数上限」（固化缺省 **3** 轮）；两者 MUST 使本通道**先于**实现预算耗尽收敛（既有缺省 6 次实现预算不得被这一种可重试原因独立吃光），MUST 在 tasks 写明该先收敛依据。
- 分支清理延迟到重试成功或放弃；放弃（超上限）时 MUST 走既有 repair/熔断/人工通道，MUST NOT 静默丢弃分支。

## D3 预算语义

- 实现尝试预算实际配置键为 `agents.impl_run_budget`（缺省 6，budget.py:26 `DEFAULT_IMPL_RUN_BUDGET`；旧文所写 `agents.implement_attempts` 在全库不存在——复查实测：`grep -rn "implement_attempts"` 零命中），上限键 `agents.impl_run_budget_max`（缺省 100）。口径：只对「真正启动实现 run」计一次（`_increment_impl_run_budget_used`）；merge-back 等待与**未派生新 run 的**合并重试不计。
- **既有先例（MUST 对齐，勿新造第三套）**：库内已有两处**事后回退**口径——`_exempt_dead_run_budget`（无收工产物的死亡 run，budget.py:185-205）与 `_exempt_infra_run_budget`（infra 失败，带 `refund_key` 幂等锚点，budget.py:207+），二者均以 `bump_impl_budget(spec_name, -1)` 回退而非「不记」。本 SPEC 的「不计入」MUST 复用该口径（若**未**派生新 run 则根本无须回退；若派生过则按上述幂等回退），MUST NOT 另起一套旁路记账，亦 MUST NOT 以「不写 STATE」代替（会与 `_reconcile_impl_budget` 的对账告警冲突）。

## Non-Goals

- 不修改 WIP 重叠闸门的 stash/block 策略。
- 不改 repair lane / 熔断触发条件。
- 不引入新配置键（顺延窗口复用既有 recovery 周期）。
- 不新增 Dashboard 配置入口：D1a 的顺延上限（`mergeback.spec_dir_inflight_grace_minutes`，缺省 30）与 D2 的顺延/重试轮数上限（缺省 3）沿用既有 `pm.recovery.*` / `worktree.*` 先例——**代码内命名默认 + `.fenix/config.yaml` 可覆盖、`config.template.yaml` 与 Dashboard 设置界面均无条目**。此为有意沿用（同 `evo-recovery-watch-transition-guard` design 的 Non-Goals 表述），若需界面可编辑，另立 SPEC 跟进。