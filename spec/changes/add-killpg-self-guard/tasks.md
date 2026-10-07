# Tasks: add-killpg-self-guard

## Deliverables

```yaml
- path: core/proc_utils.py
  kind: modify
- path: core/regression.py
  kind: modify
- path: core/agent_runner/liveness.py
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: core/adjudication_narrative.py
  kind: modify
- path: core/v2_dev_server.py
  kind: modify
- path: core/knowledge_backfill.py
  kind: modify
- path: core/knowledge.py
  kind: modify
- path: core/worktree_manager/dist_conflicts.py
  kind: modify
- path: core/dashboard/ocr_status.py
  kind: modify
- path: core/dashboard/routes/architecture_routes.py
  kind: modify
- path: core/dashboard/routes/regression_routes.py
  kind: modify
- path: core/dashboard/session_manager.py
  kind: modify
- path: core/serving_registry.py
  kind: modify
- path: core/hook_engine.py
  kind: modify
- path: core/verify_engine/cli_runner.py
  kind: modify
- path: tests/test_codefix_digest_metrics.py
  kind: modify
- path: tests/test_killpg_self_guard.py
  kind: new
```

## 1. M1：守卫助手与高危面

- [x] 1.1 在 `core/proc_utils.py` 新增 `guard_killpg(target_pid, sig, *, caller: str, resolve: bool = False) -> bool`：resolve=True 先 `os.getpgid(target_pid)` 解析 pgid，resolve=False 以 target_pid 为独立成组组长 pgid；解析失败走既有静默语义返回 False；pgid 等于 `os.getpgid(0)`、或 pgid <= 0（非正 pgid：`killpg(0)` 经 `kill(-pgid)` 折算等价调用者自身组广播、负值折算为对任意 pid 误投递，均 MUST 拒绝）时拒绝发出、记 WARNING（含 caller 与 pgid）返回 False；否则 `os.killpg(pgid, sig)` 并把 ProcessLookupError/OSError 吞为返回 False（docstring 写明两种形态判据与两个拒绝分支）
- [x] 1.2 `core/regression.py` `_kill_process_group` 与 `core/proc_utils.py` 内部清场助手的 killpg 最后一跳收口到守卫（SIGTERM→宽限→SIGKILL 序列、探活补刀逐行不动）
- [x] 1.3 修正 `tests/test_codefix_digest_metrics.py` `_FakeProc.pid = 0` 为不可达 pid：对齐 `test_knowledge_backfill.py` 先例的「不可达」意图，但该替身流入组长直传型清场点（maintenance_runs/liveness），先例 `-1` 的不可达性来自 resolve 型 `os.getpgid(-1)` 抛错、在直传型语境不成立，MUST 取正值越界 pid（如 `2**22`，超出 Linux 默认 pid_max=4194304）并含注释说明背景（守卫 pgid<=0 拒绝分支为第二道防线）
- [x] 1.4 新增 `tests/test_killpg_self_guard.py`：替身 pid=0 / 替身 pid=自身 pid 不团灭宿主、直传型 pgid=0 与 pgid=-1 被守卫拒绝且无信号发出、真实独立组（Popen start_new_session）正常清场不变、守卫拒绝留 WARNING、两种入参形态判定一致

## 2. M2：agent_runner 面（组长直传型）

- [x] 2.1 `core/agent_runner/liveness.py` 墙钟击杀路径（os.killpg(proc.pid) 两跳）收口到守卫（resolve=False）
- [x] 2.2 `core/agent_runner/maintenance_runs.py` `_kill_ocr_process_group` 三跳收口到守卫（resolve=False），组长收尸与管道排空调用方语义不变

## 3. M3：其余面收口与全量验证

- [x] 3.1 `core/adjudication_narrative.py`、`core/v2_dev_server.py`（含 507/526 孤儿清扫路径）、`core/knowledge_backfill.py`、`core/knowledge.py`、`core/worktree_manager/dist_conflicts.py`、`core/dashboard/ocr_status.py`、`core/dashboard/routes/architecture_routes.py`、`core/dashboard/routes/regression_routes.py`、`core/dashboard/session_manager.py`、`core/hook_engine.py`（getpgid 内联点改 resolve 型）、`core/serving_registry.py`（解析/孤儿组接管后 pgid 直传型，探活与接管逻辑不动）、`core/verify_engine/cli_runner.py` 各清场击杀跳收口到守卫
- [x] 3.2 在 `tests/test_killpg_self_guard.py` 加 grep 断言：core 下清场击杀语义裸 `os.killpg` 零存在，探活调用点（`killpg(_, 0)`）显式豁免清单核对
- [x] 3.3 全量回归绿（替身怪值仍在仓库其它位置的前提下套件不自杀），若有存量测试依赖裸 killpg 行为同步修正
