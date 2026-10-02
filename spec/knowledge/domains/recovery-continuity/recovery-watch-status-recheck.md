<!-- knowledge: capability=recovery-watch-status-recheck rev=1 sources=spec/archive/2026-09-24-evo-recovery-watch-status-recheck -->

# 恢复监视升级前复查

recovery watch 判 stale 并升级 dispatch_stalled 之前重读 spec 当前状态与运行痕迹，仅在命中正向证据时顺延或关闭，其余一律维持升级。

## 现行规则

- 升级前复查：判 stale 并升级 dispatch_stalled 之前，重读该 spec 的当前 status 与运行痕迹，仅在命中正向证据时不予升级：
  - `status == "blocked"`（含 frozen）→ 关闭观察项且不升级（blocked 由独立 `blocked_stuck` 通道告警，避免重复告警）；
  - 既有过渡窗口判据（transition-guard 的流缓冲 / 待合并 grace）命中 → 顺延本次判定（保留观察项、有界推进 due）；
  - 框架内重试在途：该 spec 最近一次归属其自身的 impl 流末事件为 `transient_retry` 或 `superseded`（原地退避重试留痕）且距该事件不超过 `pm.recovery.inflight_retry_minutes`（缺省 5）→ 顺延本次判定。
- 其余情形（含无正向证据的 implementing/testing 等非 ready 停滞态、确为 ready 且派发未成立）维持既有 dispatch_stalled 升级——不得仅因 status 非 ready 而顺延，否则无活跃派发的真实卡死永不告警。
- 运行痕迹归属以 `run_spec_part` 精确解析（覆盖 `-a<n>`/`-r<n>` 后缀），并同时检索 `.fenix/runs` 顶层与 `.fenix/runs/archive/`——终态 run 会在告警前被保留清理归档，顶层无同名副本时归档目录内的重试痕迹仍算证据。
- 顺延有界：自观察项首个 due 到期时刻（`registered_at + followup_check_minutes`）起累计顺延不超过 `pm.recovery.defer_limit_minutes`（缺省 30），超限回落既有 stale 判定并升级——不得以「一直有重试痕迹/长期活跃态」把真实卡死洗成健康。配置不变量：`inflight_retry_minutes < defer_limit_minutes` 且 `defer_limit_minutes > followup_check_minutes`，违反时按 `_transition_grace_minutes` 同一钳制范式收敛。
- 顺延实现约束：顺延判定落在 `_recovery_watch.pop` 之前；在升级路径上顺延时，把观察项（含推进后的 due）写回 `_recovery_watch` 并调用 `_save_recovery_watch()` 持久化到 `.fenix/recovery_watch.json`，不得只改局部变量、不落盘、静默丢弃或关闭观察项。
- 保守失败：重读 status / 运行痕迹失败或抛异常时保守升级（按既有 dispatch_stalled），不因本机制漏报真滞留。

## 溯源

- 2026-09-24 evo-recovery-watch-status-recheck（spec/archive/2026-09-24-evo-recovery-watch-status-recheck） — 新增升级前状态与运行痕迹复查（blocked 关闭、过渡与重试在途顺延）与顺延有界性、保守失败
