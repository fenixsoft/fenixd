# merge-back 能力规格：spec-dir-inflight-guard

## 概述

merge-back（实现分支合回主树）前与失败后的处置，新增「spec/changes/ 目录在飞编辑卫检查」与「可重试失败仅重试合并」两条语义，杜绝已成功 run 因合流受阻整轮作废。

## 现状与缺口

- merge-back 前：WIP 重叠闸门（auto/block）只处理「tracked 主树改动与分支重叠」，spec/changes/ 下在飞未提交编辑不被识别为顺延信号；Self-heal 检测差异仅告警即中止。
- merge-back 失败后：spec 回置 ready + Retry N/3，等待窗口后重新派发实现整轮（新 run 从头实现），已成功分支与产物不保留复用；实现尝试预算被无产出消耗。
- 取证（2026-09-19 事故，.fenix/logs/fenixd.log 44035-44194）：`git merge --no-ff` 因主树 `spec/changes/evo-transient-storm-alert-context/tasks.md` 有未提交改动被拒（`Your local changes … would be overwritten by merge … Aborting`），成功 run（$8.97）作废，11 分钟后整轮重派（$5.94）。探针实测：既有 merge-tree 预演闸从**提交**计算合并树、无视工作区脏状态（干净仓库中同样脏树下 `merge-tree --write-tree` 返回 0，`git merge` 才报错），故本形态不被预演闸拦截——卫检查与失败分类均为必要新增。

## 规格

### 卫检查（merge-back 前）

- merge-back 前对该 spec 的整个目录 `spec/changes/<spec>/`（**含** `specs/**`、proposal/design/tasks；spec 名由分支推导）做未提交改动检测；检测 MUST 只读，不就地提交/还原主树。
- 命中 → merge-back 顺延（不进入 merge），携带顺延原因与等待语义，由调度方重排，不判失败；顺延不计入 merge 失败指纹（`_merge_fp`/`_merge_streak`）、不递增 `_retry_count`、不消耗实现尝试预算、不触发「新轮次派发清除锚点」。
- 顺序：卫检查置于既有 merge-tree 预演闸与 WIP 重叠闸门**之后**、`ensure_clean_tree` 之前（优先级：语义冲突 → WIP 重叠阻塞 → spec 目录在飞编辑顺延 → 放行 merge）。
- spec 名解析失败（非 `fenix/<spec>-<ts>` 形态）→ 放行现行流程（fail-open），MUST NOT 退化为对整个 `spec/changes/` 的检测。
- 顺延信号的载体 MUST 沿用既有 merge-back 返回值结构（新增布尔字段，与既有 `rehearsed` / `wip_gate_blocked` 同型），保持 `(success, err)` 解包契约。

### 顺延的解除与有界性（MUST）

- 解除条件 = 主树侧该 spec 目录被提交（库内既有提交通道：派发前的 `ensure_spec_committed`、merge 成功后的 `_sync_task_progress`，或人工提交）。分支侧的提交**不构成**解除（`git status` 只看主树）。
- 顺延 MUST 有硬上限：自首次顺延起算，超过固化的顺延窗口（`mergeback.spec_dir_inflight_grace_minutes`，缺省 30 分钟）或连续顺延轮数上限（缺省 3 轮）仍未解除 → 必须回落到既有「发告警 + 等待人工处置」通道，MUST NOT 无限顺延（无上限顺延会把事故中的「整轮重派」换成「永不再处理」，比事故更差）。
- 上限 MUST 先于既有实现预算（`agents.impl_run_budget`，缺省 6）耗尽收敛，避免该单一原因吃光实现预算。
- 到期回落的告警 MUST 对该 spec 可见（既有周期巡检不覆盖「ready 态在飞等待」：`event_bus.recover_orphan_ready` 只扫 ready、`admin_monitor` orphaned_state 只扫 implementing/testing）。
- 顺延信号在非 dispatch 调用方（`_recovery_remerge_pending` / repair re-merge / fast-track 成功路径）MUST NOT 消费 `_repair_awaiting_remerge` 标记，须原样保留待下轮再试。

### 失败分类与重试（merge-back 失败后）

- 分类点位于既有 `rehearsed` / `wip_gate_blocked` 早退**之后**（二者不参与文本分类）。
- 可重试失败（主树脏 / spec 在飞编辑 / 锁冲突）：保留已成功分支与产物，等待条件满足后仅重试合并；等待/重试不消耗实现尝试预算，不重派实现整轮。判定须按层分离——带 git 退出码文本的（self-heal 兜底后仍被拒的 `would be overwritten by merge` / `would be lost`）用文本匹配且锚定原文片段；**不**带退出码文本的（spec 目录在飞编辑顺延、dispatch 级锁冲突）用结构化字段/既有信号判据，禁止文本匹配。判不准一律 fail-open 回既有指纹熔断/repair 通道。
- 可重试时 spec 保持 in-flight（implementing），逐项不动 `_retry_count` / `_merge_fp` / `_merge_streak` / 同因重派指纹；仅当未派生新实现 run 时才不计实现尝试预算，且记账须复用既有事后回退口径（`bump_impl_budget(-1)`），不另造旁路。
- 重试点须复用既有短程无预算定时器范式（`_schedule_instant_fail_recovery` / `_schedule_signal_kill_recovery` / `_schedule_backoff_retry`），且 MUST 经过既有实现预算闸门（不得绕过 `impl_budget_exhausted`）。
- 不可重试（语义冲突 / 熔断 / 交付物守卫）：保持既有 repair lane / 熔断 blocked / 冻结转人工通道。
- 分支清理延迟到重试成功或放弃；放弃（超上限）时 MUST 走既有 repair/熔断/人工通道，MUST NOT 静默丢弃分支。

### 边界

- 不改变 WIP 重叠闸门现有 stash/block 语义。
- 不改变 repair lane 与熔断的既有触发条件。
- 不引入 Dashboard 配置入口：两个上限键沿用既有「代码命名默认 + config.yaml 可覆盖、界面无条目」先例。
- 已知精度边界（记录在案，本 SPEC 不修）：`_spec_from_branch` 按「末段纯数字」切分，spec 名自身以数字段结尾（如 `…-575976`）时解析失真——沿用既有 helper 以与 merge-back 链路保持单源。
