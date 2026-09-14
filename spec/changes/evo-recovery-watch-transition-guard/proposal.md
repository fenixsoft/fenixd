## Why

2026-09-12 21:13:37Z implementer（add-framework-self-evolution a2）成功后，recovery watch 于 21:13:57Z 复查读到过渡态误判 stale，升级 dispatch_stalled（fenixd.log 5584-5597），21:16:11Z 唤起 1 个无效 admin run（1789247771, 9 rounds）；21:14:02Z merge 完成系统即自愈（仅差 5 秒，admin 结案定性『竞态误报』）。根因：recovery watch 通过条件 = 状态 ∈ RECOVERY_PROGRESS_STATUSES（implemented/testing/verified/done/pushed）**或** worktree 存在（core/pm_engine/recovery.py check_recovery_watch），而 implementer 成功后 worktree 先清理（21:13:33Z）再 merge（21:14:02Z）——过渡窗口内两条件皆不成立 → 误判。engine.py 假就绪巡检（BLOCKER CHECK，ready_stall_threshold 20min）同样无过渡窗口豁免。竞态与 spec 无关，可在任何 spec 上复发，每次产生无效 admin run。

**取证订正（评审复核）**：事故当时 daemon 运行的是 c703c707 之前的旧码，其通过条件为「`status != status_at_register` 或已有活跃派发（active_dispatch）」（`git show 1be2d60c:core/pm_engine/recovery.py` 第 127 行 `if status != item.get("status_at_register") or active_dispatch:`；fenixd.log 5596 旧措辞「still stalled in ready」，c703c707 后方改为「not recovered」）——旧码下 status 仍为登记时的 implementing 且 worktree 已清，故同样判 stale；上面写的 `RECOVERY_PROGRESS_STATUSES` 条件是 c703c707 起的现行码。两版条件在过渡窗口下**同样**判 stale（status=implementing 不在集合内、worktree 已清、非 ready 不重派，recovery.py:33/143/153），故缺陷在现行码仍成立，本 SPEC 目标有效。

## What Changes

- recovery watch 与假就绪巡检在判定 stale 前增加『过渡窗口』检查：该 spec 存在待合并分支（worktree_manager pending merge = 归属该 spec 且**有未并入 main 的提交**）或 implementer succeed 痕迹落在缓冲窗口（`pm.recovery.transition_buffer_seconds`，缺省 60 秒）内时，顺延本次判定（保留观察项、推进复查时刻，见 design D2 顺延落点）。**其中假就绪巡检侧为条件性交付**（见下方 Impact 与 design D3 证据门槛）：给不出可复现触发场景时该项整体删去，本 SPEC 只落 recovery watch 侧。
- 或等价：implementer succeed 信号到达时重置/顺延该 spec 的 recovery watch 计时器。
- 无 dashboard UI。新增两个**内部调参项**（沿用既有 `pm.recovery.*` 先例：代码命名默认 + `config.yaml` 可覆盖、无设置界面条目）：`pm.recovery.transition_buffer_seconds`（缺省 60）、`pm.recovery.transition_grace_minutes`（豁免上限）。

## Capabilities

### New Capabilities
- `recovery-watch-transition-guard`: 状态过渡窗口内不误判 stale（pending merge / succeed 缓冲顺延）

### Modified Capabilities
- `post-recovery-patrol`（既有 requirement「每次自动恢复后必须安排闭环复查」的**通过条件**）：该 requirement 现由在飞 SPEC `fix-dispatch-wakeup-gap` 持有 MODIFIED delta（`spec/changes/fix-dispatch-wakeup-gap/specs/post-recovery-patrol/spec.md`；基线见 `spec/archive/2026-09-02-improve-run-lifecycle-governance/specs/post-recovery-patrol/spec.md`），本 SPEC 在它的通过条件上再加**第三条处置**——过渡窗口（归属本 spec 的待合并分支 / succeed 缓冲窗内）既不关闭观察项也不升级 dispatch_stalled，而是**顺延**。对既有语义的影响是**有界收窄**：无活跃派发的 `implementing` 在过渡窗口内不再即时告警（上限 `pm.recovery.transition_grace_minutes`，缺省 5min < 复查间隔 15min）。15min 复查间隔与 dispatch_stalled 兜底本身不变。
- 注：上述 delta 与 `fix-dispatch-wakeup-gap` 的 delta 触及**同一条 requirement**，两者落地顺序会影响归档时的 delta 文本合成；若二者都将落地，后者归档时 MUST 把「顺延」这条处置一并并入该 requirement（本条为披露与协调要求，不在 spec/ 下另立竞争 delta，避免双 delta 冲突）。

## Impact

- **core/pm_engine/recovery.py**：check_recovery_watch 判定前增加 pending-merge / transition 缓冲检查（判据见 design D1/D2）。
- **core/pm_engine/engine.py**：假就绪巡检（BLOCKER CHECK）增加同源豁免（判据落点见 design D3）——**条件性交付**：必要性尚未证实（design D3 证据门槛），给不出可复现触发场景时该项与 Deliverables 中 engine.py 一并删去，本 SPEC 只保留 recovery.py 侧豁免，目标仍成立。
- **core/worktree_manager.py**：暴露『待合并分支』只读查询 `has_pending_merge(spec)`（并暴露未合并提交的年龄，供有界性回落）。判据为「分支按**『完整 spec 名 + 分隔符边界』全等**精确归属（MUST NOT 原样复用 `_spec_from_branch`——它硬编码 `fenix/` 且会剥掉 `verify-` 前缀，须改走 `_wt_name_matches_spec` 同口径的边界守卫并排除验证分支，见 design D1「解析器口径」；禁用 glob 前缀匹配）且 `git rev-list --count main..<branch> > 0`」，**不得**退化为分支存在性检查（design D1：仓库现有 1014 条 `fenix/*` 历史分支，其中 933 条已并入 main、**81 条未并入**（覆盖 48 个 spec 名）——存在性判据会把已合并的历史分支也算作待合并，永久抑制真实 stale 检出）。
- **tests/**：过渡窗口不误报 + 真实 stale 仍报断言 + worktree_manager 查询 / engine 豁免的落点断言。