# Tasks: recovery-watch-status-recheck

## Deliverables

```yaml
- path: core/pm_engine/recovery.py
  kind: modify
- path: tests/test_recovery_watch_status_recheck.py
  kind: new
```

> 既有用例 MUST 保持全绿（不新增 deliverable 改动）：`tests/test_recovery_watch_transition_guard.py`（全量）、
> `tests/test_run_lifecycle_governance.py`（含 `test_defer_registers_watch_no_deadloop`）、`tests/test_pm_recovery.py`。

## 1. 升级前状态与运行痕迹复查

- [ ] 1.1 core/pm_engine/recovery.py：升级前（218 行）重读 `read_one(spec_name)` 与运行痕迹，仅按正向证据免于升级；
      异常/读失败一律走保守升级（不静默关闭观察项）
- [ ] 1.2 `status == "blocked"`（含 frozen）→ 关闭观察项、不升级 dispatch_stalled（blocked 由
      admin_monitor._detect_blocked_stuck 通道接管，不重复告警）
- [ ] 1.3 运行痕迹检索口径扩展：`.fenix/runs` 顶层 + `.fenix/runs/archive/`（终态流会在告警前被保留清理归档，
      2026-09-17 16:33:38 归档 → 16:33:58 误报）；归属继续用 `run_spec_part` 精确比对（含 `-a<n>`/`-r<n>` 后缀），
      禁止裸 glob 命中判定
- [ ] 1.4 新增「框架内重试在途」判据：最近一次归属该 spec 的 impl 流末事件 ∈ {`transient_retry`, `superseded`}
      且 `now - 末事件时间 ≤ pm.recovery.inflight_retry_minutes`（缺省 5）→ 顺延（保留观察项、推进 due），不升级
- [ ] 1.5 **MUST NOT** 仅因 status 非 ready 而顺延：无正向证据的 implementing/testing 等停滞态维持既有升级
      （保持 recovery.py:35-39 注释语义与 test_defer_registers_watch_no_deadloop 的「到期即信号」不变量）
- [ ] 1.6 顺延落点在 `_recovery_watch.pop`（178 行）之前生效；若在升级路径上顺延，MUST 写回观察项（含 due）并
      `_save_recovery_watch()`，不得只改局部变量
- [ ] 1.7 有界性：新增 `pm.recovery.defer_limit_minutes`（缺省 30），起算点 = 观察项首个 due 到期时刻
      （`registered_at + followup_check_minutes`，可另存 `recheck_deadline` 字段以跨重启续算）；累计顺延超限即回落
      既有 stale 判定并升级；配置不变量 `inflight_retry_minutes < defer_limit_minutes`、
      `defer_limit_minutes > followup_check_minutes`，违反时按 `_transition_grace_minutes` 同一钳制范式收敛
- [ ] 1.8 既有过渡窗口判据（D2(a) 缓冲 60s / D1 grace 缺省 5min 及其有界回落）与 ready 滞留就地重派发路径保持不变

## 2. 测试

- [ ] 2.1 tests/test_recovery_watch_status_recheck.py：框架内重试在途（末事件 `transient_retry`/`superseded` 且
      未超窗口）→ 顺延不升级（复现 2026-09-17 16:33:58 事故）
- [ ] 2.2 归档形态：痕迹仅在 `.fenix/runs/archive/` 且顶层无副本 → 仍顺延（防只查顶层的口径回归）
- [ ] 2.3 重试窗口超时（末事件距 now > `inflight_retry_minutes`）→ 仍升级 dispatch_stalled
- [ ] 2.4 复查时已 blocked → 关闭观察项、不升级、无 dispatch_stalled 记录
- [ ] 2.5 复查时无正向证据的 implementing → 仍升级（对齐既有 `test_defer_registers_watch_no_deadloop` 语义）
- [ ] 2.6 确为 ready 滞留（就地重派发被闸门拦下）→ 仍升级（回归 3fad3350 语义）
- [ ] 2.7 顺延累计超过 `defer_limit_minutes` → 回落升级（有界性）
- [ ] 2.8 升级前重读 status/运行痕迹抛异常 → 保守升级
- [ ] 2.9 回归运行：`tests/test_recovery_watch_transition_guard.py`、`tests/test_run_lifecycle_governance.py`、
      `tests/test_pm_recovery.py` 全绿（顺延不丢观察项、mock 替身严格判定等既有断言不回归）
