# 设计 — worktree-conflict-recovery

## 现状取证（改动前基线）
- 冲突门是**内存集合**：`WorktreeManager._spec_locks`（`core/worktree_manager.py:140`）在 `create()` 内 check-then-add 原子持有（同文件 `:190-199`），失败/收工释放。daemon 重启后内存锁为空，`create()` 按新时间戳分支新建，**不会冲突**。
- 既有锁治理已在别处实现「活动 vs 残留」：`has_active_worktree`（`:781-825`）以进程表 + run 流新鲜度 + 锁龄三信号回收陈锁——`_spec_process_alive`（`:1196-1216`，pgrep `worktrees/{impl,verify}-<spec>-` + `_is_claude_process` 确认）、`_latest_stream_mtime`（`:1241-1262`）、`_lock_young`（`:1181-1194`，窗口 `STALE_LOCK_IDLE_SECONDS=120`，`:29`）。`refresh_locks`（`:829-864`）仅在 daemon 启动时调用（`fenixd.py:372`）。
- 派发层已有锁冲突退避与升级：`core/pm_engine/dispatch.py:79-132`（`pm.dispatch_backoff_schedule` 缺省 30/120/600s，不消耗 retry，序列耗尽发 `dispatch_stalled`），触发点 `core/pm_engine/engine.py:316-337`；其中先以 `has_live_attempt`（`core/agent_runner/runner.py:4824`）甄别「活 run 持锁」并静默跳过。
- 降级观测通道已存在：`verification.py:1706` → `_write_degrade_context`（`:3452-3492`，落 `.fenix/verify-progress/<spec>/degrade_context.json`）→ `core/verify_report.py:143-153`/`:648-672` 注入 → `core/dashboard/data.py:3669`。
- 删除 worktree 的安全约定：任何删除路径 MUST 先 `_snapshot_dirty_worktree`（`:677`，约定见 `:734-737`，调用见 `:755`）；`cleanup_orphans(protected=...)`（`:724-751`）跳过保全集（保全集由 `recover_interrupted` 于 `fenixd.py:376-384` 先于 `cleanup_stale_worktrees` 登记）。

## 活跃记录扩展（诊断用 sidecar）
- 路径固定为 `.fenix/worktree-locks.json`。MUST NOT 写 `.fenix/runs/`——该目录是 run 流命名空间（`_latest_stream_mtime` 按 `{impl,verify}-<spec>-*.jsonl` glob），混入非流文件会污染流扫描。
- 结构：`{"<spec>:<agent_type>": {"run_id": str, "daemon_pid": int, "created_at": float}}`。
- **权威源不变**：冲突判定 MUST 仍以内存 `_spec_locks` 为准（`:190-199`）；sidecar 只作诊断读取，MUST NOT 在构造期被加载为拒绝依据——否则 daemon 重启后残留条目会把今日「锁空 → create 成功」变成「create 被拒」。
- `daemon_pid` 仅作追溯参考，MUST NOT 用作存活判据：`create()` 运行在 daemon 进程内（`os.getpid()` 即 daemon pid，同文件 `:1296` 的用法），agent 子进程在 `create()` 返回之后才 spawn（`core/agent_runner/runner.py:2538` 之后进入 attempt 子循环）。以 daemon pid 判存活会让「pid 不存在」分支在 daemon 存活期内永不成立。
- `run_id` 由调用方传入：`create(self, spec_name, agent_type)`（`:178`）现无 run_id 形参，需扩展签名并由 `runner.py` 以 `attempt_run_id` 传入（缺省空串，保持既有调用兼容）。
- 写入/清除 MUST 收敛到锁登记辅助方法（`_register_spec_locks` `:1162-1171`、`_release_spec_locks` `:1173-1179`），MUST NOT 散点直改集合；否则任一路径漏清即留幽灵条目。锁的全部变更点：create 失败 `:260-262`/`:296-298`/`:301-303`、`cleanup` finally `:660-675`、`keep_for_reuse` `:1004-1007`、`cleanup_orphans` 全清 `:776-779`、`cleanup_stale_worktrees` 重建 `:1857`、`refresh_locks` 释放 `:856`。

## 残留判定（复用既有信号，不自造 pid 判据）
判定顺序（`create()` 冲突分支内）：

1. **进程表**：`_spec_process_alive(spec)`（`:1196`）为真 → 活动 run（`reason=parallel-run`），不重试、不清理。与派发层「活 run 持锁静默跳过」同口径（`core/pm_engine/engine.py:316-332`）。
2. **run 流新鲜度**：`_latest_stream_mtime(spec)`（`:1241`）在 `STALE_LOCK_IDLE_SECONDS` 内 → 活动，不清理。
   - **前缀盲区（必须显式处理）**：该 helper 只 glob `{impl,verify}-<spec>-*.jsonl`，而 `planner-plan`/`planner-judge`/`spec-review`/`admin`/`evo` 流前缀均不匹配（实测 `.fenix/runs/`：`planner-plan-` 32、`planner-judge-` 29、`spec-review-` 21、`admin-` 18、`evo-` 5 条 = 105/165 条），而 planner 的 **worktree 目录**仍用 `impl-` 前缀（`create()` `:222-231`）。因此「run 转录缺失」对 planner 恒真，MUST NOT 单凭它判残留——否则会删掉正在跑 planner 的 worktree。判定 MUST 以判据 1 的进程表信号为主。
3. **锁龄**：`_lock_young(spec)`（`:1181`）为真 → 处于 create 构建窗口，保留不清理。
4. **记录缺失的缺省方向**：内存锁在册但 sidecar 无记录（历史锁、手工加锁、测试直改集合）→ MUST 判**活动**（fail-closed），MUST NOT 判残留。既有用例 `tests/test_dual_dispatch_and_freeze.py:116-121` 正是直接向 `_spec_locks` 加锁后断言 `create()` 拒绝；缺省若取「无记录=残留」会同时翻红该用例并削弱并发保护。
5. 三条皆否且 sidecar 有记录 → 残留（`reason=stale`）。

## 恢复流程
- `create()` 冲突（`lock_key in self._spec_locks`）时：
  1. 按上节判定锁归属；
  2. 活动 → 记 `reason=parallel-run` 并在返回上下文带出「锁活跃」事实，按现有语义失败返回（**不重试、不清理**）；
  3. 残留 → 按「清理安全约束」清理该锁对应的 worktree 后释放该锁，**重试一次** create；
  4. 重试失败 → 降级，`reason=stale-recovery-failed`。
- 环境性失败（非冲突类：git 命令失败/超时等）→ `reason=env-failure`，不进入清理重试。

## 清理安全约束（与既有删除约定对齐）
残留清理 MUST：
- 先 `_snapshot_dirty_worktree`（`:677`；约定 `:734-737`、既有调用 `:755`）留档，MUST NOT 只把留档挂在 rmtree 兜底分支；
- 跳过保护集：`.fenix/interrupted_runs.json` 在册项与 `_active_worktrees` 在册项（口径同 `cleanup_orphans(protected=...)` `:724-751`，及并发 SPEC `fix-recovery-branch-anchor-without-worktree` 的「清理协调」不变量：任何删除 worktree 目录的路径 MUST 先留档、MUST 跳过保全引用）；
- 清理由 `git worktree remove --force` + `git worktree prune` 完成；失败仅 WARNING，MUST NOT rmtree 目录树（避免绕过 git 记账）。

## 降级诊断化（复用既有通道，不新建）
- 原因经既有通道落盘：`_write_degrade_context(spec, reason, run_id, duration_seconds)`（`:3452`）→ `.fenix/verify-progress/<spec>/degrade_context.json` → `verify_report` 注入 → Dashboard（`core/dashboard/data.py:3669`）。MUST NOT 新建 emit 函数 / dashboard signal 通道（同一事实两个来源必然漂移）。
- 覆盖缺口：异常驱动的降级路径（`verification.py:1676` planner-plan 失败、`:2082` planner-judge 失败）目前不写 degrade 上下文；MUST 在抛错前落盘 `reason`，使 `core/pm_engine/engine.py:1297-1314` 的兜底降级可读。
- `reason` 取值集合：`parallel-run` | `stale-recovery-failed` | `env-failure`。
- 原因传递链：`worktree_manager.create()` 冲突原因 → `runner.py` 的 `error_msg`（当前 `:2540` 丢弃原因、只剩裸串 `Failed to create worktree`）→ `AgentRunResult.error` → planner 抛错 → 降级落盘。

## 与既有机制的关系（职责边界）
- **派发层退避**（`dispatch.py:79-132`，implementer 派发入口 `engine.py:316-337`）：本 SPEC 不改、不介入。create 层只做「识别 + 一次性清理重试」，MUST NOT 在 create 层排定重试定时器、MUST NOT 写 STATE 状态或退避字段——否则与派发退避形成双重重试链。重试配额语义归属派发层。
- **`has_active_worktree`/`refresh_locks` 的陈锁回收**：保留。本 SPEC 的残留清理只把「同一 daemon 生命周期内、孤儿持锁」这一窄窗口的恢复提前到 create 冲突点（`refresh_locks` 仅在 daemon 启动时跑），不替换既有回收路径。
- **预算归因**：锁冲突 MUST NOT 落进死亡 run 豁免（`dispatch.py:1108-1128`：判据 `impl_status is None` → `_exempt_dead_run_budget`，`:2519-2521`）。参照 `provider circuit open` 先例（`dispatch.py:1129-1139`：不计 retry、不翻状态）为锁冲突提供同类处置，或至少提供可区分的原因字段供豁免判据排除。

## 改动点
- `core/worktree_manager.py`：sidecar 读写（收敛到锁辅助方法）+ 残留判定 + 清理重试。
- `core/agent_runner/runner.py`：create 传 `run_id`；`error_msg`（`:2540`）携带冲突原因。
- `core/pm_engine/verification.py`：异常驱动降级路径落盘 degrade 原因（`:1676`/`:2082`）。
- `tests/test_worktree_recovery.py`（新增）：判定 + 清理重试 + 原因传递单测。

**路径口径**：本仓库 `.fenix/core` 是指向主树 `core/` 的符号链接（`ls -la .fenix/` 可见），故改动点一律以仓库相对路径 `core/...` 书写。MUST NOT 按 `.fenix/core/...` 定位实现文件——worktree 内 `.fenix/` 不含该符号链接，按该路径改会落到主树。
