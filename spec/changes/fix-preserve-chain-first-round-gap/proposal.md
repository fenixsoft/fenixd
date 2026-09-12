## Why

2026-09-11 07:51Z 的规划性重启（91 commits/24h 触发热重载）排水超时后 SIGTERM 强杀 `impl-add-blocked-reverify-lane-1789107185-a1`，该 run 本地已跑 128 分钟、0 提交残留，成为当日窗口唯一 failed run，只能从零重派 run2（152 turns）才完成。

关键在于：**为这个场景设计的保全链当时已经在主树里，却整体空跑**。`add-interrupt-recovery-preserve`（`daf4df7d`，09-05 落地）提供了排水期 sidecar 保全（D3）与 orphan 清理保护集（D6），`add-impl-wip-checkpoint`（`ad2fb912`，09-10 落地）提供了 WIP 提交通道——两者都早于事故，但没有一条生效。

根因是两条独立缺陷叠在同一条因果链上：

- **A. `branch` 登记滞后于 run 生命周期。** `branch` 只在 run 完成时写入 STATE（`core/pm_engine/dispatch.py:995`、`:2172`）。首轮在飞的 run 在 STATE 里 `branch` 恒为 `None`，于是：
  - `fenixd.py:1114` `branch = entry.get("branch")` → `''` → `worktree = ''` → 保护集 `seen_wt` 为空 → `cleanup_orphans(protected=∅)` 无差别清理（事故日志 `Preserving interrupted run … branch 'none', ahead=0` 即此）；
  - `core/state_machine.py:868` `_recovery_preserve_spec` 的 `if not branch: return False` 直接放弃保留，转走清空路径（`:854-865` 把 `branch` 重置为 `None`）。
  - 讽刺的是 worktree 路径在创建时**已经**登记在 `worktree_manager._active_worktrees` / `_wt_branches` 里，从未被读取。

- **B. `cleanup_orphans` 无快照留档。** `_snapshot_dirty_worktree`（D4，`add-impl-terminal-nocommit-gate`）全库**唯一调用点**是 `core/worktree_manager.py:638`，且位于 `cleanup()` 的「`git worktree remove` 返回非零 → rmtree 兜底」分支内。`cleanup_orphans()`（`:725`）直接 `git worktree remove --force` + `rmtree`，没有任何留档；即便在 `cleanup()` 内，`--force` 成功路径（`returncode == 0`）同样不触发快照——而 drain 强杀走的正是 `success=False` 带 `--force` 且通常成功的路径。留档通道在最需要它的场景系统性失效。

净效果：**首次实现尝试 + 排水强杀 = 保全链全盲**，工作区被硬删且无快照引用，只能从零重来。

## What Changes

- 新增 **spec → branch/worktree 的 git 事实查询**：保全（`_preserve_interrupted_runs`）与恢复保留判定（`_recovery_preserve_spec`）在 STATE `branch` 缺失时 MUST 回落到该查询反查，不再以 STATE 为唯一依据。查询以 `git worktree list --porcelain` 与 worktree 命名约定为真相（沿用既有 `find_worktree_path` / `is_available` 的「不信任内存表」口径——`_active_worktrees` / `_wt_branches` 是内存表，daemon 重启即失，不足以支撑 boot 路径）。STATE `branch` 保留为完成态记录，语义不变。
- 由此，首轮 run「尚在飞」不再等于「分支不可知」：分支在 worktree 创建时即已成事实，只是此前没有任何读取方去查。
- `cleanup_orphans` 硬删 worktree 前 MUST 接入 `_snapshot_dirty_worktree` 留档通道；`cleanup()` 的 `--force` 成功路径同样补留档，使留档从「失败兜底」变为「删除前置动作」。
- 保护集判定 MUST 在「sidecar 无 worktree 引用」时回落注册表，消除「保全与清理对同一 worktree 处置不一致」的残余窗口。

**非目标**：不改变排水窗口时长（`admin.shutdown_drain_seconds` 缺省仍 1800，0=快速停机）；不改变非计划 SIGTERM 的快速停机语义；不引入「长活 run 自适应延长排水」——延长等待只推迟问题，不解决保全链失明。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `interrupt-recovery-preserve`：终止前保全（Requirement 2）的 branch/worktree 来源从「STATE 单一来源」改为「STATE + worktree 注册表回落」；恢复保留分支续做（Requirement 3）的判定同上；清理协调（Requirement 4）补「硬删前必留档」与「保护集回落注册表」两条约束。

## Impact

- `fenixd.py`：`_preserve_interrupted_runs`（`:1092-1155`）branch/worktree 解析与保护集组装。
- `core/state_machine.py`：`_recovery_preserve_spec`（`:868-930`）保留判定与 `worktree_manager` 注入路径。
- `core/worktree_manager.py`：`cleanup_orphans`（`:725`）、`cleanup`（`:554`）留档接入点、注册表查询接口。
- `core/worktree_manager.py`：新增 spec → worktree/branch 事实查询；`cleanup_orphans`（`:725`）、`cleanup`（`:554`）留档接入点。
- `core/pm_engine/dispatch.py`：预计无需改动（方案显式否决派发期写 STATE branch）；若实现中发现保全入口的 spec 名解析需要对齐，方触及 `:668` 附近的 run_id → spec 解析。
- 测试：`tests/` 下保全/恢复/清理相关用例；新增首发 run 强杀时序回归。

- 风险面：保全与清理是停机关键路径，改动需保证「非计划 SIGTERM 行为零变化」与「零提交分支走现行清空」两条既有 Scenario 逐字节不变。
