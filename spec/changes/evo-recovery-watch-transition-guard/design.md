# 设计：recovery watch 过渡窗口豁免

## Context

2026-09-12 21:13:33Z（worktree 清理）→ 21:13:37Z（implementer succeed）→ 21:14:02Z（merge 完成）窗口内，recovery watch 于 21:13:57Z 复查：状态不在 RECOVERY_PROGRESS_STATUSES、worktree 已清理（active_dispatch=False）→ 误判 stale → dispatch_stalled → 无效 admin run（1789247771，9 rounds）。

**取证订正**（评审复核）：事故当时 daemon 运行的是 c703c707 之前的旧码（通过条件为 `status != status_at_register` 或已有活跃派发，见 `git show 1be2d60c:core/pm_engine/recovery.py` 第 127 行；fenixd.log 5596 的旧措辞「still stalled in ready」，该措辞已由 c703c707 改为「not recovered」）——旧码下 status 仍为登记时的 implementing 且 worktree 已清，故同样判 stale。但现行码（recovery.py:33 `RECOVERY_PROGRESS_STATUSES`、:143 通过条件、:153 仅 `status == "ready"` 才就地重派）在同一窗口下**同样判 stale**——status=implementing 既不在集合内、worktree 又已清、且非 ready 故不重派。故该缺陷在现行码上仍成立，本 SPEC 目标有效。

## Goals / Non-Goals

- **Goals**：过渡窗口内不产生 dispatch_stalled 误报；真实 stale 检测能力不降。
- **Non-Goals**：不缩短/改动 15min 复查间隔语义；不改 dispatch_stalled 兜底（真实 stale 仍升级）；不引入新的状态字段；**不新增 Dashboard 配置入口**——D1/D2 的两个调参项（`pm.recovery.transition_grace_minutes`、`pm.recovery.transition_buffer_seconds`）沿用既有 `pm.recovery.*` 先例（`followup_check_minutes`/`signal_cooldown_minutes`/`ready_stall_threshold_minutes`：代码命名默认 + `.fenix/config.yaml` 可覆盖，`.fenix/config.template.yaml` 与 Dashboard 设置界面均无条目）。此为**有意**沿用先例而非遗漏；若用户要求这两个键可在界面编辑，另立 SPEC 跟进。

## Decisions

### D1：待合并信号以「未并入 main 的提交」为准，禁止以分支存在与否判定

**选择**：worktree_manager 侧新增只读查询（建议名 `has_pending_merge(spec)`；返回值 MUST 同时携带「未合并提交的年龄」或另设 `pending_merge_since(spec)`——仅 `-> bool` 无法表达下面的有界性），判定标准为：

> 枚举 `refs/heads/<prefix>/*`（prefix 与分支创建/解析端同源，见下「前缀来源」），候选分支按**精确归属**解析——「完整 spec 名 + 分隔符边界」全等（分支名去 `<prefix>/` 后按最后一个 `-` 分段、末段为纯数字、其前段与该 spec 名全等；口径同 `_wt_name_matches_spec`（worktree_manager.py:3201-3217）与 `engine.py:1870-1873`）——确认属于该 spec 且**非验证分支**（`<prefix>/verify-<spec>-*` MUST NOT 进入候选），且 `git rev-list --count main..<branch> > 0`（该分支有未并入 main 的提交）。

**归属精确性（评审新增，必须遵守）**：MUST NOT 以 glob `refs/heads/<prefix>/<spec>-*` 直接匹配。实测 `git for-each-ref 'refs/heads/fenix/evo-add-fast-track-scale-precheck-*'` 命中 5 条分支，其中 `fenix/evo-add-fast-track-scale-precheck-4afdbe-<ts>`（2 条）属**另一 spec** `evo-add-fast-track-scale-precheck-4afdbe`（其 STATE.md 条目同在册）——前缀匹配会把别的 spec 的未合并提交算到本 spec 头上，制造本 SPEC 要消除的误判（方向相反：这一次是抑制真实 stale 检出）。

**前缀来源（评审新增，必须遵守）**：候选枚举所用前缀 MUST 与分支**创建端**同源。实测：分支创建硬编码 `fenix/`（worktree_manager.py:223/226），`_spec_from_branch` 解析亦硬编码 `startswith("fenix/")`（worktree_manager.py:1383），而 `worktree.implement_branch_prefix` 现仅被 `engine._resolve_push_branch` 读取（engine.py:1860）——故 `has_pending_merge` MUST NOT 仅凭配置值取前缀（非 `fenix` 配置下会枚举空命名空间、豁免静默失效）；实现取其一时 MUST 同源对齐（读取配置即须先使创建端同源，或沿用 `fenix/`）。

**解析器口径（评审新增，必须遵守）**：归属解析 MUST NOT 原样复用 `_spec_from_branch`——它硬编码 `startswith("fenix/")` 且会剥掉 `verify-` 前缀（worktree_manager.py:1386-1387），会把验证分支 `fenix/verify-<spec>-<ts>` 也误算作本 spec 的实现分支；MUST 走「末段纯数字时间戳 + 其前段与该 spec 名全等」的边界守卫（口径同 `_wt_name_matches_spec`），并显式排除 `<prefix>/verify-<spec>-*`（与 fix-recovery-branch-anchor-without-worktree 的候选口径一致）。若最终选择读配置取前缀，`WorktreeManager` 无配置取值途径（构造签名见 worktree_manager.py:134），实现 MUST 显式落地获取途径（构造注入 / 就地读取）并保持既有构造调用点兼容，读取失败降级缺省前缀。

**理由 / 反例（评审新增，必须遵守）**：实现成功路径**保留**分支（worktree_manager.py:560 文档「If True, retain the branch」；删除分支只在 `not success` 分支，worktree_manager.py:648-653），且 `merge_back_from_branch`（worktree_manager.py:1899+）**不删除**已合并分支。仓库现有 **1014 个** `fenix/*` 历史分支即为佐证。因此：

- 「存在 `fenix/<spec>-*` 分支」**MUST NOT** 作为待合并判据——几乎每个做过实现的 spec 恒为真，dispatch_stalled 将被**永久抑制**，直接违反 Goals「真实 stale 检测能力不降」与 spec.md Scenario「真实 stale 仍被报出」。
- 「未并入 main 的提交」判据在 merge 完成后 `count=0`，自然失效，是忠实的过渡信号。
- worktree_manager 的 `has_active_worktree`（基于内存 `_spec_locks` + 进程存活扫描，worktree_manager.py:781+）**不能**直接照搬：成功收工时 `cleanup` 已 `_wt_branches.pop` + `_active_worktrees.discard`（worktree_manager.py:655-656）并在 finally 段释放 `_spec_locks`（worktree_manager.py:660-677），过渡窗口内 agent 进程已退出、该内存态无记录。故 D1 的真相源必须是 git 分支事实（rev-list），不是 worktree_manager 内存登记。

**有界性（评审新增，必须遵守）**：该豁免 MUST 有上限——自「年龄来源」（下段：该分支未并入 main 的最新 committer date）起算，超过 `pm.recovery.transition_grace_minutes` 仍未合并时，回落既有 stale 判定，避免「分支永挂 → 永不告警」把真实卡死洗成健康。

**grace 缺省固化（评审新增，必须遵守）**：`pm.recovery.transition_grace_minutes` 缺省 **5 分钟**，实现时固化，MUST NOT 留待实现者取值。原「缺省与 D2 缓冲同量级」在**单位上自相矛盾**——D2 缓冲是秒（60），「同量级」可被读成 1 分钟或 60 分钟，行为差 60×，有界性无法验收。**不变量**：grace MUST < 复查间隔 `pm.recovery.followup_check_minutes`（缺省 15），使「回落」在下一次复查即可观测。上限必须生效的实证：仓库现存 **81 条**未并入 main 的 `fenix/*` 分支（覆盖 **48 个** spec 名），无上限时这些 spec 的真实 stale 会被永久洗为健康。

**年龄来源（评审新增，必须遵守）**：有界性要求「距该分支产生未合并提交已多久」，而 D1 判据只给出提交**计数**——任务 MUST 点名年龄载体，取该分支未并入 main 的**最新 committer date**（`git log -1 --format=%ct main..<branch>`）为默认口径，接口随之暴露该时间戳（见上「仅 `-> bool` 无法表达有界性」）。不得让实现者临时决定起点语义（分支创建时间 / 首次未合并时间 / 提交时间三者语义不同，会得出不同的回落时机）。

**年龄起点不得早于过渡窗口（评审新增，必须遵守）**：起点若只取「最新未合并提交时间」，会在实现者末次提交早于 succeed 时被**预先消耗**——事故实证：分支末次提交 21:09:54Z、succeed 21:13:37Z（间隙 **243s**），而 grace=300s，故 21:13:57Z 复查（提交年龄 243s）时 pending-merge 网的**有效覆盖仅剩 57s**，短于 60s 缓冲网；对耗时 >60s 的合并（主树锁竞争 / 冲突修复通道）该网在复查到达前即已过期。故年龄起点 MUST 取 `max(该分支未并入 main 的最新提交时间, 该 spec 成功收工痕迹时间)`（后者即 D2 的 (a)/(b) 来源时间戳），使上限度量的是「过渡开始后的豁免时长」而非「提交的陈腐度」；无近期收工痕迹的孤儿分支（仓库存量 48 个 spec 的旧分支）仍以提交时间起算，有界性不降。

### D2：缓冲窗口的「succeed 时间戳」取既有可观测源，不依赖新字段

**现状事实（评审新增）**：STATE 无「implementer succeed 时间戳」持久字段——`branch` / `implementer_run` 只在 merge-back **成功之后**才写（dispatch.py:1042-1045），过渡窗口内恒为 null（与 `fix-recovery-branch-anchor-without-worktree` 的取证一致：`spec/changes/fix-recovery-branch-anchor-without-worktree/proposal.md` Change A 首条）。

**选择**：兜底判据 MUST 取既有可观测源之一，二选一即可：

- (a) 该 spec 的 impl run 流文件 `.fenix/runs/impl-<spec>-*.jsonl` 的 mtime 落在缓冲窗口内（与 `engine._spec_has_recent_run_activity` 同源代理判据，engine.py:1956-1976）；或
- (b) STATE `updated` 落在缓冲窗口内（成功收工的 usage 累加会刷新它，state_machine.py:562）。

**缓冲秒数固化（评审新增）**：实现时 MUST 固化为命名默认 `pm.recovery.transition_buffer_seconds`，缺省 **60**——覆盖实测的 21:13:33→21:14:02（29s）窗口并留余量。不得留待实现者临时决定（原 design 仅称「设计固化秒数」而未给值，spec.md 亦只写「设计固化秒数」）。

**单位换算（评审新增，必须遵守）**：复用 (a) 时注意既有代理判据以**分钟**为入参（`engine._spec_has_recent_run_activity(spec_name, window_minutes)`，engine.py:1956），而本 SPEC 固化的缓冲值是**秒**（60）。直接以 60 作 `window_minutes` 会把 1 分钟窗口放大成 60 分钟窗口；MUST 显式换算（`transition_buffer_seconds / 60`），并在测试中断言该换算（可允许的窗口边界）。

**判据 (a) 归属须精确（评审新增，必须遵守）**：MUST NOT 原样调用 `engine._spec_has_recent_run_activity` 的 `runs_dir.glob(f"{prefix}-{spec_name}-*.jsonl")`（engine.py:1963）——该 glob 对 spec 名互为前缀会误命中**他 spec** 的运行流（spec `a-b` 命中 `impl-a-b-c-<ts>.jsonl`），凭空制造「近期活动」→ 豁免真 stale，与 D1「归属精确性」同源反向。复用事实源（`.fenix/runs/` 下 impl 流）时 MUST 走 `impl-<spec>-<ts>` 的「末段纯数字时间戳 + 前段与 spec 名全等」边界守卫（口径同 `_wt_name_matches_spec`）。

**既有测试回归（评审新增，必须遵守）**：判据 (b)（STATE `updated`）会**必然命中**既有 recovery-watch 用例的夹具——`RecoveryWatchFixture.watch_due()`（tests/test_run_lifecycle_governance.py:342-350）**只回拨 `due`、不回拨 `updated`**，而 `make_ready_spec`（:222-225）/`sm.update_spec` 刚写入 `updated`（=now），故 `test_watch_fails_when_still_fake_ready`（:447）、`test_watch_registered_implementing_rolled_back_to_ready_redispatches`（:467）、`test_watch_inplace_dispatch_blocked_by_budget_signals`（:508）、`test_recovery_patrol_redispatches_regressed_ready`（tests/test_pm_recovery.py:227）这 4 条断言 `dispatch_stalled`/就地派发的用例会被误豁免而**转红**（夹具 `project_root` 为 pytest tmpdir，非 git 仓库 → 待合并信号恒假，缓冲判据成唯一变量）。故实现 MUST 二选一并显式声明：(i) 判据取 **(a)**（tmpdir 无 run 流 → 不误命中，既有 4 例保持绿）；或 (ii) 取 **(b)** 时 MUST 同步更新上述用例（如在其内复用夹具 `_stale()` 把 `updated` 一并置于缓冲窗外）并为该选择在 tasks.md 留一行依据。**两文件（tests/test_run_lifecycle_governance.py、tests/test_pm_recovery.py）MUST 补入 tasks.md Deliverables**——不论取哪支，二者至少其一会被动到，漏列即交付物集合不封闭。

**mock 替身回归（评审新增，必须遵守）**：待合并信号的调用路径是 `self._pm.agent_runner.worktree_manager.<query>`（与既有 `has_active_worktree` 同路径，recovery.py:139），而既有 recovery-watch 夹具的 `worktree_manager` 为 `MagicMock`（tests/test_run_lifecycle_governance.py:210、tests/test_pm_recovery.py:197）。实测量得 `bool(MagicMock()) is True`、`MagicMock() is not None is True`（仅 `is True` 为假），故**调用点 MUST 对返回值做严格判定**——布尔查询用 `is True`、时间戳查询用 `isinstance(ts, (int, float))`，MUST NOT 依赖裸真值或 `is not None`。先例：engine.py:1961 `return result is True`（存活探针）与用例 `test_probe_non_bool_return_treated_as_absent`（tests/test_run_lifecycle_governance.py:384「探针返回非布尔（如未配置的测试替身）→ 保守按无存活」）。**否则取判据 (a) 时（tmpdir 非 git 仓库 → 待合并信号本应为假）这些用例仍会因替身真值被误豁免而转红**——上文「取 (a) 时既有 4 例保持绿」的结论因此不成立；`pending_merge_since` 若以 `is not None` 守护同样中招（MagicMock 非 None）。受影响集合**大于**已列 4 条：除 :447/:467/:508 与 tests/test_pm_recovery.py:227 外，至少还含 `test_defer_registers_watch_no_deadloop`（tests/test_run_lifecycle_governance.py:393，断言 :410 `raised == ["s1"]`）与 `test_watch_passes_when_spec_left_ready`（:430，断言观察项已关闭）——实现后 MUST 跑这 6 条确认全绿。

**顺延落点（评审新增，必须遵守）**：`check_recovery_watch` 在判定前就已把观察项弹出（recovery.py:130-131 `_recovery_watch.pop` + `_save_recovery_watch`）——「跳过本次判定」若实现为裸 `continue`，观察项被静默丢弃、永不复查，真实卡死从此无人告警（正是本 SPEC 要防的反面）。故顺延 MUST 二者之一：(i) 豁免检查施加于 `pop` **之前**（并顺带把 `due` 后移，避免每轮重复进入）；(ii) 在 `pop` 之后按原 `registered_at`/`reason` 重登记并刷新 `due`。**唯一口径为「顺延（保留观察项）」**，不得以「视为已恢复」关闭观察项——过渡窗口内 spec 并未推进，关闭即等于放弃后续复查。

**顺延推进量（评审新增，必须遵守）**：顺延 MUST 固化 `due` 推进量（缺省取 `pm.recovery.transition_buffer_seconds`，60s），且推进后的 `due` MUST NOT 晚于待合并信号的 grace 截止（起点 + `transition_grace_minutes`）——否则有界性回落的告警会被推后到更晚的复查，甚至越过下一次复查才可观测。走 (ii) 重登记路径时同样 MUST 覆盖 `followup_check_minutes`（15min）的默认推进量，不得因重登记把 `due` 推到 grace 截止之后。

**事件式可选路径**：若采用「implementer succeed 信号到达时重置该 spec 计时器」的事件式实现，写入点在成功处置段（dispatch.py 的 implementer 成功分支 ~1020-1083）或 runner.py:3077-3082，须把该文件补入 tasks.md Deliverables；否则一律走上面的惰性求值路径，保持交付物集合封闭。

### D3：engine.py 假就绪巡检的豁免目标须点名判据

**现状事实（评审新增）**：现行 ready 滞留巡检只在 `status == "ready"` 分支内评估（engine.py:2176-2208，阈值 `ready_stall_threshold_minutes` 缺省 20min）；事故窗口 status=implementing，该巡检**不会**触发。与之相邻、真正可能看到该窗口的是 engine.py:2143 的 `status in ("implementing", "testing")` 卡死检查（另一阈值）。

**选择**：任务 MUST 点名豁免施加于**哪条判据**——ready 滞留巡检、implementing/testing 卡死检查、或二者；并给出可复现的触发场景。否则「同源豁免」无落点、无法定验收。

**证据门槛（评审新增，必须遵守）**：本 SPEC 的 engine.py 侧豁免**必要性尚未被证实**，而施加面是既有安全网，故实现 MUST 先过门槛再动手：先给出可复现触发场景（指名判据、命中状态与阈值，并说明事故窗口如何越过阈值）。**给不出则 MUST 删去 engine.py 侧改动**（`core/pm_engine/engine.py` 连同 tasks.md Deliverables 中该项一并删去），本 SPEC 只保留 recovery.py 侧豁免——不得为「对称」而改安全网。门槛未过的依据：按现行阈值两条判据在事故窗口（status=implementing、`updated` 为秒级）均不可能触发——implementing/testing 卡死阈值 = run_timeout + 600s（默认 9000+600=9600s≈**160min**，`core/config.py:1116-1133` `effective_stuck_threshold_seconds` 经 engine.py:2081 派生），ready 滞留阈值缺省 20min（engine.py:1947-1953）；且 ready 滞留 blocker 的既有处置**正是** `_signal_dispatch_stalled`（engine.py:2234-2242），无据抑制它等于削弱真实 stale 告警。默认口径（门槛通过时）：两条判据在判定 blocker 前共用同一 `has_pending_merge` / 缓冲窗口豁免。

### D4：与 fix-recovery-branch-anchor-without-worktree 的去重

两者都在解决「已实现、未合并」这一窗口不可识别的问题：本 SPEC 从**消费侧**（recovery watch / 假就绪巡检判 stale 前豁免）补判据，`fix-recovery-branch-anchor-without-worktree` 从**登记侧**（终态成功即落 `branch`/`implementer_run`、分支命名空间回落）补锚点。实现时 MUST 复用它新增的 git 分支命名空间枚举能力（若已落地），不得各造一套分支枚举；若两者并行落地，以「未并入 main 的提交」这一唯一判据口径对齐（见 `[[fix-recovery-branch-anchor-without-worktree]]`）。

**既有同判据实现（评审新增，必须遵守）**：`rev-list --count main..<branch>` 在库中已有两处实现，新查询 MUST 复用其口径而非再造第三份——`core/pm_engine/verification.py:2553-2585`（`_branch_commit_count` / `_implementation_branch_has_commits`，自述「单一来源」）与 `core/state_machine.py:919-937`（恢复保留路径内联）。二者的差别只在「入参是 run result 还是 branch 名」，本 SPEC 新增的能力是 **spec → 候选分支的精确解析**（「完整 spec 名 + 分隔符边界」全等，见 D1），不属于重复实现；实现说明 MUST 写清复用了哪一处、为何不能直接调用。
