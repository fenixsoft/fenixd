<!-- knowledge: capability=merge-back rev=3 sources=spec/archive/2026-09-22-evo-merge-back-wip-overlap-gate-575976,spec/archive/2026-09-25-evo-merge-back-spec-dir-inflight-guard,spec/archive/2026-09-25-evo-stash-pop-conflict-triage -->

# merge-back 合并回主树

实现分支（`fenix/<spec>-<ts>`）合回主树的主通道：实现成功后以保留历史的方式合并，主树侧的未提交改动与在飞编辑在合并前后受到闸门链与自愈链保护。

## 现行规则

- 闸门顺序不变式：`merge-tree` 预演闸 → WIP 重叠闸门 → spec 目录在飞编辑卫检查 → `ensure_clean_tree` → merge。优先级为语义冲突 → WIP 重叠拦截 → spec 目录在飞编辑顺延 → 放行 merge。
- 无重叠且主树干净的路径：autostash（含 untracked）→ `git merge --no-ff`（保留历史，分支已为主树祖先时幂等跳过）→ 成功后 stash pop 恢复主树 WIP。
- WIP 重叠闸门：重叠集合 = 主树脏 tracked 文件 ∩ 分支触碰文件集，且 MUST 排除 `spec/changes/**`（该前缀由既有 `ensure_spec_committed` / `_commit_softened_declaration` 提交通道收口，不引入新的 stash/阻塞语义）。交集非空的缺省处置为升级人工拦截（不发 merge，人工告警附交集清单；该缺省由 merge-back-precheck 预检确立）；显式 `worktree.mergeback_wip_overlap_policy=auto` 维持自动收纳（收纳 → merge → 成功后恢复主树 WIP）；显式 `block` 并入升级出口；`worktree.merge_precheck_bypass=true` 跳过预检直接 merge。
- 阻塞与顺延不记账：WIP 重叠拦截 MUST NOT 计入 `_merge_fp`/`_merge_streak` 熔断记账，spec MUST NOT 因拦截被自动 `transition("blocked")`；spec 目录顺延同样不计指纹、不递增 `_retry_count`、不消耗实现尝试预算、不触发「新轮次派发清除锚点」。
- spec 目录在飞编辑卫检查：merge 前对 `spec/changes/<spec>/` 整目录（含 specs/**、proposal/design/tasks，spec 名由分支推导）做未提交改动检测，检测只读、不就地提交/还原主树；命中 → merge-back 顺延（携带顺延原因与等待语义，由调度方重排，不判失败）。spec 名解析失败（非 `fenix/<spec>-<ts>` 形态）→ fail-open 放行现行流程，MUST NOT 退化为对整个 `spec/changes/` 的检测。顺延信号沿用 merge-back 返回值结构（新增布尔字段，与 `rehearsed`/`wip_gate_blocked` 同型），保持 `(success, err)` 解包契约。
- 顺延的有界性与解除：解除条件 = 主树侧该 spec 目录被提交（派发前 `ensure_spec_committed`、merge 成功后 `_sync_task_progress` 或人工提交；分支侧提交不构成解除——`git status` 只看主树）。顺延有硬上限：自首次顺延起超过 `mergeback.spec_dir_inflight_grace_minutes`（缺省 30 分钟）或连续 3 轮仍未解除 → 回落「发告警 + 等待人工处置」，MUST NOT 无限顺延；上限 MUST 先于 `agents.impl_run_budget`（缺省 6）耗尽收敛；到期告警对该 spec 可见。非 dispatch 调用方（`_recovery_remerge_pending` / repair re-merge / fast-track 成功路径）MUST NOT 消费 `_repair_awaiting_remerge` 标记，原样保留待下轮再试。
- 失败分类与仅重试合并：可重试失败（主树脏 / spec 在飞编辑 / dispatch 级锁冲突）→ 保留已成功分支与产物，条件满足后仅重试合并，不重派实现整轮。判定按层分离：带 git 退出码文本的（self-heal 兜底后仍被拒的 `would be overwritten by merge` / `would be lost`）用文本匹配且锚定原文片段；不带退出码文本的（spec 目录顺延、dispatch 级锁冲突）用结构化字段/既有信号判据，禁止文本匹配；判不准一律 fail-open 回既有指纹熔断/repair 通道。可重试时 spec 保持 in-flight，记账复用既有事后回退口径（`bump_impl_budget(-1)`），重试点复用既有短程无预算定时器范式且 MUST 经过实现预算闸门（不得绕过 `impl_budget_exhausted`）。不可重试（语义冲突 / 熔断 / 交付物守卫）走既有 repair lane / 熔断 blocked / 冻结转人工；分支清理延迟到重试成功或放弃，放弃（超上限）走既有 repair/熔断/人工通道，MUST NOT 静默丢弃分支。
- stash pop 冲突三态处置（自愈链内，对每个 UU 冲突文件按序尝试）：态 1 三方重试双版本落盘（ours = 已合入 HEAD 版，base = `stash@{0}^1` 版，theirs = `stash@{0}` 版，无冲突写回工作区两侧改动都保留；失败含纯文本同 hunk 冲突不视为异常，直接进态 2）；态 2 路径作用域恢复 commit（逐文件 `git checkout --theirs` 取回 stash 版落工作区，MUST NOT 依赖工作区冲突标记文本，再 `git add` + `git commit --only` 只把本次冲突路径入库，保留 index 其余 staged 条目）；态 3 兜底（态 2 落盘或入库任一步失败时，至少保证 stash 版内容落回工作区并显式登记 disposition）。任一态不得静默丢弃 stash 内容；`last_stash_entry_fate` 结构与 `_drop_superseded_stash_entry` 判据不变。
- stash 前缀隔离：闸门收纳/保留条目所用前缀 MUST NOT 包含 `AUTOSTASH_MSG_PREFIX` 子串——`reclaim_stale_autostash` 以子串匹配栈顶并 pop，复用同前缀会让故意保留待找回的条目被 60s 巡检抢走并沿用丢弃策略。
- 告警通路：`signal_type=mergeback_wip_overlap` 由 dispatch 层在 merge 结果处理的失败/阻塞分支直发 admin store（仅成功路径调用的既有 emit 点不覆盖阻塞路径），MUST 收录进 `admin_monitor` 的 `STORED_SIGNAL_TYPES`（severity=major，附核对指引），`evidence` MUST 先序列化为 `str` 再入 record（dict 穿透会致 Administrator 唤起失败）。
- 可观测性：冲突处置路径写结构化日志（文件清单 / 处置方式（态 1/2/3） / stash sha），dashboard 与自省可见。

## 溯源

- 2026-09-22 evo-merge-back-wip-overlap-gate-575976 — WIP 重叠处置从仅预警升级为执行级闸门（自动收纳/阻塞策略、`spec/changes/**` 排除、闸门不记账）、stash 保留判据与 stash 前缀隔离、`mergeback_wip_overlap` 直发告警通路（其缺省策略后经 merge-back-precheck 改为升级拦截，见该能力页）
- 2026-09-25 evo-merge-back-spec-dir-inflight-guard — 新增 spec 目录在飞编辑卫检查与顺延有界性（30 分钟/3 轮双上限、fail-open 边界）、可重试失败仅重试合并的分类语义与预算记账口径
- 2026-09-25 evo-stash-pop-conflict-triage — stash pop 冲突自愈升级为三态重试（双版本落盘/路径作用域恢复 commit/兜底登记），主树未提交改动不再因自愈静默丢失，处置路径结构化日志可观测
