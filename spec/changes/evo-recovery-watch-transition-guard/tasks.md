# 任务

## Deliverables

```yaml
- path: core/pm_engine/recovery.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
  # 条件性交付：1.3 证据门槛未过则连同本项一并删去（不影响本 SPEC 目标）
- path: core/worktree_manager.py
  kind: modify
- path: tests/test_recovery_watch_transition_guard.py
  kind: new
# 既有 recovery-watch 用例（判据 (b) 取 STATE.updated 时会被误豁免转红，见 design D2「既有测试回归」；取 (a) 时亦须复核不改动）
- path: tests/test_run_lifecycle_governance.py
  kind: modify
- path: tests/test_pm_recovery.py
  kind: modify
```

## 1. 过渡窗口豁免

- [ ] 1.1 core/pm_engine/recovery.py check_recovery_watch：判定 stale 前检查待合并信号 `has_pending_merge(spec)`，为真则顺延本次判定（design D1；判据 = 实现分支未并入 main 的提交，非分支存在性）。**落点约束（design D2「顺延落点」）**：观察项在判定前已被弹出（recovery.py:130-131 `pop` + `_save_recovery_watch`），故豁免检查 MUST 施加于 `pop` 之前并顺延 `due`，或在 `pop` 之后原地重登记（保留 `registered_at`/`reason`、刷新 `due`）；MUST NOT 以裸 `continue` 静默丢弃观察项（丢弃 = 真实卡死从此无人告警），MUST NOT 以「视为已恢复」关闭观察项。**顺延推进量（design D2「顺延推进量」）**：`due` 推进量 MUST 固化（缺省 `pm.recovery.transition_buffer_seconds` = 60s，daemon 主循环每 60s 调用 `check_recovery_watch`，fenixd.py:483-486），且推进后的 `due` MUST NOT 晚于 grace 截止（起点 + `transition_grace_minutes`）；重登记路径不得沿用 `followup_check_minutes`（15min）默认推进量而越界。**调用点严格判定（design D2「mock 替身回归」，评审就地修补）**：`has_pending_merge` 经 `self._pm.agent_runner.worktree_manager` 调用（recovery.py:139 同路径），而既有夹具该属性为 `MagicMock`（tests/test_run_lifecycle_governance.py:210、tests/test_pm_recovery.py:197；实测 `bool(MagicMock()) is True`）——调用点 MUST 用严格判定（布尔 `is True` / 时间戳 `isinstance(ts, (int, float))`），MUST NOT 依赖裸真值或 `is not None`（先例 engine.py:1961 `return result is True`）；否则既有 recovery-watch 用例会被替身真值误豁免而转红（受影响集合见 3.4）

- [ ] 1.2 core/pm_engine/recovery.py check_recovery_watch：判定 stale 前补齐第二道缓冲判据（design D2）——取既有可观测源之一：(a) 该 spec 的 `.fenix/runs/impl-<spec>-*.jsonl` mtime 落在窗口内，或 (b) STATE `updated` 落在窗口内（事故实证：21:13:37.3 成功收工的 usage 累加刷新了 STATE.updated，21:13:57 复查时仍在 60s 窗内）。窗口秒数固化为命名默认 `pm.recovery.transition_buffer_seconds`（缺省 60）。**约束一**：状态里不存在「implementer succeed 时间戳」字段（`branch`/`implementer_run` 仅 merge 成功后写，dispatch.py:1042-1045），不得据此实现；若改走事件式「succeed 信号到达即重置计时器」，须先把成功处置段所在文件补入 Deliverables 再实施。**约束二（单位）**：复用 (a) 时注意 `engine._spec_has_recent_run_activity(spec_name, window_minutes)`（engine.py:1956）以**分钟**为入参，须显式换算 `transition_buffer_seconds / 60`，并以测试钉住窗口边界。**约束三（判据选择必须显式 + 归属精确，评审就地修补）**：MUST 在实现说明中显式声明取 (a) 还是 (b)，并处理其既有测试后果（design D2「既有测试回归」）——(b) 取 STATE.updated 会使 `RecoveryWatchFixture.watch_due()`（tests/test_run_lifecycle_governance.py:342-350，只回拨 `due` 不回拨 `updated`）下的 4 条既有用例（:447/:467/:508、tests/test_pm_recovery.py:227）被误豁免转红，取 (b) 则 MUST 同步更新这 4 例（如把 `updated` 一并置窗外）并留依据行；取 (a) 则 MUST NOT 原样调用 `_spec_has_recent_run_activity`——其 glob `f"{prefix}-{spec_name}-*.jsonl"`（engine.py:1963）对 spec 名互为前缀会误命中他 spec 的运行流（spec `a-b` 命中 `impl-a-b-c-<ts>.jsonl`），MUST 改走 `impl-<spec>-<ts>` 末段纯数字时间戳 + 前段全等的边界守卫（口径同 `_wt_name_matches_spec`）

- [ ] 1.3 core/pm_engine/engine.py 假就绪巡检（BLOCKER CHECK）：**先过证据门槛（design D3 证据门槛）——未过则本任务整体作废，engine.py 连同 Deliverables 中该项一并删去，本 SPEC 只保留 recovery.py 侧豁免**。门槛：MUST 给出可复现触发场景，点名豁免施加的判据（ready 滞留巡检 engine.py:2176-2208 与/或 implementing/testing 卡死检查 engine.py:2143）、命中状态与该判据阈值，并说明事故窗口（status=implementing、`updated` 为秒级）如何越过阈值。门槛未过的依据：implementing/testing 卡死阈值 = run_timeout + 600s（默认 9000+600=9600s≈**160min**，`core/config.py:1116-1133` `effective_stuck_threshold_seconds` 经 engine.py:2081 派生），ready 滞留阈值缺省 20min（engine.py:1947-1953）——两条在秒级窗口均不可能触发；且 ready 滞留 blocker 的既有处置正是 `_signal_dispatch_stalled`（engine.py:2234-2242），无据抑制即削弱真实 stale 告警。门槛通过时口径：两条判据共用同一 `has_pending_merge` / 缓冲窗口豁免（与 1.1/2.1 同源）

- [ ] 1.4 有界性：`has_pending_merge` 豁免在**年龄**（design D1 年龄来源：该分支未并入 main 的最新 committer date，`git log -1 --format=%ct main..<branch>`）超过 `pm.recovery.transition_grace_minutes` 仍未合并时，回落既有 stale 判定，避免分支永挂导致真实 stale 永不告警（design D1 有界性）。**缺省固化为 5 分钟**（MUST NOT 留待实现者取值——原「与 1.2 缓冲同量级」在单位上自相矛盾：1.2 缓冲是秒/60，误读成 60 分钟则行为差 60×）。**不变量**：grace MUST < `pm.recovery.followup_check_minutes`（缺省 15，1.2 未改动该复查间隔），使回落在下一次复查即可观测。**年龄起点（design D1「年龄起点不得早于过渡窗口」）**：MUST 取 `max(分支未并入 main 的最新提交时间, 该 spec 成功收工痕迹时间)`，不得只取提交时间——事故实证末次提交 21:09:54Z / succeed 21:13:37Z（间隙 243s），仅取提交时间时 grace=300s 的有效覆盖只剩 57s（< 60s 缓冲网），对耗时 >60s 的合并早已过期；无近期痕迹的孤儿分支仍以提交时间起算（有界性不降）。上限必须生效的实证：仓库现存 **81 条**未并入 main 的 `fenix/*` 分支（覆盖 48 个 spec 名）

## 2. 支撑

- [ ] 2.1 core/worktree_manager.py：新增只读查询 `has_pending_merge(spec) -> bool`（并暴露未合并提交的**年龄**，供 1.4 回落；即 `pending_merge_since(spec)` 或等价签名——仅 `-> bool` 无法表达有界性）。**归属判据 MUST 精确，禁止 glob 前缀匹配**（design D1 归属精确性）：事实源用 `git for-each-ref refs/heads/<prefix>/` 拉窄候选（prefix MUST 与分支创建/解析端同源——见 2.2「前缀来源」，**MUST NOT 单独凭配置值取前缀**），但分支→spec 的归属 MUST 按「完整 spec 名 + 分隔符边界」**全等比较**确定，MUST NOT 以 `refs/heads/<prefix>/<spec>-*` 或 `startswith("<spec>-")` 定归属。**解析器口径（评审就地修补）**：归属 MUST NOT 原样复用 `_spec_from_branch`——它硬编码 `startswith("fenix/")`（worktree_manager.py:1383）且剥掉 `verify-` 前缀（会把 `<prefix>/verify-<spec>-<ts>` 验证分支也算作本 spec 的实现分支，与 fix-recovery-branch-anchor-without-worktree 的候选口径「验证分支 MUST NOT 进入候选清单」冲突）；MUST 采用与既有守卫同口径的解析——分支名去 `<prefix>/` 后按最后一个 `-` 分段、末段 MUST 为纯数字、其前段与该 spec 名**全等**（口径同 `_wt_name_matches_spec`（worktree_manager.py:3201-3217）与 `engine.py:1870-1873`），并 MUST 排除 `<prefix>/verify-<spec>-*`——与既有约定一致（`find_worktree_by_spec` docstring，worktree_manager.py:3115-3135「禁止子串包含：spec 名互为前缀如 fix-x 与 fix-x-y 不误匹配」）。实锤：`git for-each-ref 'refs/heads/fenix/evo-add-fast-track-scale-precheck-*'` 命中 5 条分支，其中 `...-4afdbe-<ts>`（2 条）属**另一 spec**；前缀判据会把甲 spec 的未合并分支算到乙 spec 头上，反向抑制真实 stale 检出。候选归属确认后判据为 `git rev-list --count main..<branch> > 0`；MUST NOT 退化为 `branch_exists` 式存在性检查（design D1 反例：仓库现有 1014 条 `fenix/*` 分支，其中 81 条未并入 main）。（原草稿误写 core/agent_runner/worktree_manager.py，该目录下无此文件，已订正）

- [ ] 2.2 去重（两处，design D4）：(i) 若 fix-recovery-branch-anchor-without-worktree 的 git 分支命名空间枚举能力（其 2.1 `find_branches_by_spec`）已落地，复用其 `for-each-ref` 事实源而非另造一套枚举；该 SPEC 的 2.1/6.2 亦以 `<prefix>/<spec>-*` 作命名空间口径，两者 MUST 共用本 SPEC 2.1 的「完整 spec 名 + 分隔符边界」全等归属判据（该 SPEC 亦已要求候选按此全等过滤，口径一致），并以「未并入 main 的提交」这一唯一判据口径对齐。(ii) **既有同判据实现 MUST 复用/对齐而非再造第三份**（design D4 末段）：`core/pm_engine/verification.py:2553-2585` 的 `_branch_commit_count`（`git rev-list --count main..<branch>`）与 `_implementation_branch_has_commits`（`> 0`，自述「单一来源」）、`core/state_machine.py:919-937`（恢复保留路径内联同一判据）。本 SPEC 新增的能力是 **spec → 候选分支的精确解析**（「完整 spec 名 + 分隔符边界」全等，见 2.1；MUST NOT 原样复用 `_spec_from_branch`），不属重复实现；实现说明 MUST 写清复用了哪一处、为何不能直接调用。`main` 作基分支硬编码与既有实现一致（state_machine.py:925、runner.py:1928、verification.py:2567），不引入新配置。**前缀来源（design D1「前缀来源」）**：枚举前缀 MUST 与分支**创建端**同源——分支创建硬编码 `fenix/`（worktree_manager.py:223/226），`_spec_from_branch` 解析亦硬编码 `fenix/`（worktree_manager.py:1383），`worktree.implement_branch_prefix` 现仅 `engine._resolve_push_branch`（engine.py:1860）读取；故 MUST NOT 仅凭配置值取前缀（非 `fenix` 时枚举空命名空间、豁免静默失效）。**配置获取途径（评审就地修补）**：`WorktreeManager` 构造签名为 `(base_dir, project_root, logger, process_scanner=None)`（worktree_manager.py:134）且全文件无配置取值调用（对照 `engine.py:1860` 经 `self._get_config` 读同名键）；若最终选择读配置取前缀，实现 MUST 显式落地获取途径（构造注入或按 `project_root` 就地读取）并保持既有构造调用点（fenixd.py:228 及各测试）兼容，读取失败降级缺省前缀而非抛错

## 3. 测试

- [ ] 3.1 tests/test_recovery_watch_transition_guard.py：过渡窗口复查不误报 dispatch_stalled（成功-合并窗口场景）

- [ ] 3.2 真实 stale 仍升级 dispatch_stalled（回归断言）；含守卫用例「分支存在但已并入 main（`rev-list --count == 0`）不算待合并，仍报 stale」

- [ ] 3.3 支撑与落点断言：`has_pending_merge` 三态（未合并=真 / 已合并=假 / 无分支=假）；**前缀歧义守卫用例**——仅存在 `<spec>-<其它后缀>` 的未合并分支时（如 spec `a-b` 与分支 `fenix/a-b-c-<ts>`，形如现存的 `evo-add-fast-track-scale-precheck` 与 `...-4afdbe`），spec `a-b` MUST 返回假并仍报 stale；**顺延在册断言**（1.1）——顺延后观察项仍在 `.fenix/recovery_watch.json` 且 `due` 已推进（防裸 `continue` 静默关闭），并断言推进量符合固化值且不超过 grace 截止；**有界性断言**（1.4）——年龄超过 grace 时回落告警，且年龄起点取 `max(提交时间, 收工痕迹时间)`（用例：末次提交早于 succeed 达 243s 时仍在 grace 内豁免）；1.3 若未作废，则断言所选 engine 判据的豁免落点，并对偶断言「待合并信号为假时仍报 blocker」

- [ ] 3.4 既有用例回归收口（design D2「既有测试回归」，评审就地修补）：按 1.2 显式声明的判据选择，复核并（必要时）更新 `tests/test_run_lifecycle_governance.py`（:447 `test_watch_fails_when_still_fake_ready`、:467 `test_watch_registered_implementing_rolled_back_to_ready_redispatches`、:508 `test_watch_inplace_dispatch_blocked_by_budget_signals`）与 `tests/test_pm_recovery.py`（:227 `test_recovery_patrol_redispatches_regressed_ready`）——取 (b) 时这 4 例的夹具 `updated` 为 now、会被缓冲判据误豁免，MUST 把它们一并置于窗外（复用夹具 `_stale()`）或按新语义改写断言；MUST NOT 以删断言/放宽断言方式「修绿」。取 (a) 时 MUST 跑一遍确认这 4 例不改仍绿。**并覆盖 mock 替身回归（design D2「mock 替身回归」，评审就地修补）**：受影响集合不止上述 4 条——`test_defer_registers_watch_no_deadloop`（tests/test_run_lifecycle_governance.py:393，断言 :410 `raised == ["s1"]`）与 `test_watch_passes_when_spec_left_ready`（:430，断言观察项已关闭）同样经 `worktree_manager` 替身，若新查询以裸真值/`is not None` 判定会被误豁免；实现后 MUST 跑这 6 条确认全绿（MUST NOT 仅跑前 4 条）
