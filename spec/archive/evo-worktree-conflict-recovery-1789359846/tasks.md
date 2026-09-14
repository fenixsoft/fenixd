# 任务

## Deliverables

```yaml
- path: core/worktree_manager.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/pm_engine/verification.py
  kind: modify
- path: tests/test_worktree_recovery.py
  kind: new
```

`core/agent_runner/runner.py` 为原因传递链必经环节（`create()` 冲突原因 → `error_msg`；现 `runner.py:2540` 丢弃原因只剩裸串 `Failed to create worktree`），design「改动点」亦列入，漏声明则原因无法到达降级落盘点。降级观测复用既有 `degrade_context.json` 通道，故无 dashboard 交付物。

## 1. worktree 锁记录磁盘化（诊断 sidecar）

- [ ] 1.1 `core/worktree_manager.py`：新增 `.fenix/worktree-locks.json` 读写。约束：
  - 结构 `{run_id, daemon_pid, created_at}`；`daemon_pid` 仅追溯参考，MUST NOT 作存活判据（`create()` 跑在 daemon 进程内，agent 子进程尚未 spawn）。
  - 冲突门 MUST 仍为内存 `_spec_locks`；sidecar MUST NOT 在构造期被加载为拒绝依据（否则 daemon 重启后残留条目把「锁空→create 成功」变成「create 被拒」）。
  - 路径 MUST NOT 选 `.fenix/runs/`（该目录是 run 流命名空间）。
  - 写入/清除 MUST 收敛到单点（`_register_spec_locks`/`_release_spec_locks` 等价辅助），覆盖全部锁变更点：create 失败三处、`cleanup` finally、`keep_for_reuse`、`cleanup_orphans` 全清、`cleanup_stale_worktrees` 重建、`refresh_locks` 释放。
- [ ] 1.2 `core/worktree_manager.py`：`create()` 增 `run_id: str = ""` 形参并入册；`core/agent_runner/runner.py:2538` 调用点传 `attempt_run_id`（缺省值保持既有调用兼容）。

## 2. 锁归属诊断与残留清理重试

- [ ] 2.1 `core/worktree_manager.py`：冲突时按「进程表（主）→ run 流新鲜度 → 锁龄」判定活动/残留；活动返回原因 `parallel-run` 且不重试；残留清理后重试一次。约束：
  - 约束一：残留判定 MUST NOT 单凭 run 流转录缺失——`_latest_stream_mtime` 只 glob `{impl,verify}-<spec>-*.jsonl`，planner/spec-review/admin/evo 流前缀皆不匹配（实测 105/165 条），而 planner 的 worktree 目录仍为 `impl-` 前缀 → 单凭该信号会删掉正在运行的 planner worktree。
  - 约束二：清理 MUST 先 `_snapshot_dirty_worktree` 留档、跳过 `.fenix/interrupted_runs.json` 在册项与 `_active_worktrees` 在册项、走 `git worktree remove --force` + `prune`（MUST NOT rmtree）。
  - 约束三：MUST NOT 在 create 层排重试定时器或写 STATE 退避字段（派发层退避 `dispatch.py:79-132` 职责不变）。
  - 约束四：内存锁在册但 sidecar 无记录时 MUST 判活动（fail-closed）——既有用例 `tests/test_dual_dispatch_and_freeze.py:116-121` 直接向 `_spec_locks` 加锁后断言 `create()` 拒绝，缺省取「无记录=残留」会同时翻红该用例并削弱并发保护。
- [ ] 2.2 `core/worktree_manager.py`：重试失败置原因 `stale-recovery-failed`；非冲突类失败置原因 `env-failure`。

## 3. 降级诊断化（reason 字段，复用既有通道）

- [ ] 3.1 `core/agent_runner/runner.py`：`error_msg`（`:2540`）携带冲突原因（如 `Failed to create worktree (reason=parallel-run)`），使原因随 `AgentRunResult.error` 上传。
- [ ] 3.2 `core/pm_engine/verification.py`：异常驱动降级路径（`:1676` planner-plan 失败、`:2082` planner-judge 失败）在抛错前调用既有 `_write_degrade_context`（`:3452`）落盘 reason；MUST NOT 新建 emit 函数 / dashboard signal 通道。
- [ ] 3.3 锁冲突 MUST NOT 落入死亡 run 预算豁免：核对 `dispatch.py:1108-1128` 判据（`impl_status is None` → `_exempt_dead_run_budget`），使锁冲突短路或带可区分原因（参照 `provider circuit open` 先例 `dispatch.py:1129-1139`：不计 retry、不翻状态）。

## 4. 回归测试（冲突→恢复路径）

- [ ] 4.1 `tests/test_worktree_recovery.py`：残留锁清理重试成功不降级；活动锁（含 `planner-plan`）不重试且原因=`parallel-run`；清理前快照与保护集跳过；sidecar 无记录时 fail-closed；`run_id` 入册。
- [ ] 4.2 既有相关用例不回归：`tests/test_dual_dispatch_and_freeze.py`（`:116-121` 断言 `Worktree already active` + `create()` 拒绝）、`tests/test_run_lifecycle_governance.py`、`tests/test_startup_double_dispatch.py`（均以 tmpdir 作 `project_root` 并断言 `_spec_locks`/派发行为）。sidecar 与判定改动 MUST NOT 改变其判定结果；若某用例确需修改，MUST 同步在 Deliverables 补入该测试文件的 `modify` 声明（未声明的路径不可改）。
