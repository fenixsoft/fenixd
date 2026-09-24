# recovery-watch-status-recheck

## ADDED Requirements

### Requirement: 升级前状态与运行痕迹复查

recovery watch 判 stale 并升级 dispatch_stalled 之前，MUST 重读该 spec 的当前 status 与运行痕迹，并**仅**在命中
正向证据时不予升级：

- `status == "blocked"`（含 frozen）→ MUST 关闭观察项且 MUST NOT 升级 dispatch_stalled（blocked 由独立
  `blocked_stuck` 通道告警，`core/admin_monitor.py:690`）；
- 既有过渡窗口判据（evo-recovery-watch-transition-guard D2(a) 流缓冲 / D1 待合并 grace）命中 → MUST 顺延本次
  判定（保留观察项、有界推进 due）；
- **框架内重试在途**：该 spec 最近一次归属其自身的 impl 流末事件为 `transient_retry` 或 `superseded`
  （`core/agent_runner/runner.py:2368/2384/2503/2518` 的原地退避重试留痕）且距该事件不超过
  `pm.recovery.inflight_retry_minutes`（缺省 5）→ MUST 顺延本次判定；

其余情形（含**无正向证据**的 implementing / testing 等非 ready 停滞态、确为 ready 且派发未成立）MUST 维持既有
dispatch_stalled 升级——MUST NOT 仅因 status 非 ready 而顺延（否则无活跃派发的真实卡死形态永不告警，
`core/pm_engine/recovery.py:35-39` 刻意设计语义被破坏）。

运行痕迹归属 MUST 以 `run_spec_part` 精确解析（覆盖 `-a<n>`/`-r<n>` 后缀），且 MUST 同时检索 `.fenix/runs` 顶层与
`.fenix/runs/archive/`（终态 run 会在告警前被保留清理归档——2026-09-17 16:33:38 归档、16:33:58 误报）。

#### Scenario: 框架内重试在途不升级（2026-09-17 误报复现）

- **WHEN** 复查时该 spec 已无活跃派发、无新鲜流 mtime，但最近一次归属其自身的 impl 流末事件为
  `transient_retry`/`superseded` 且距该事件不超过 `inflight_retry_minutes`
- **THEN** 顺延本次判定（保留观察项、推进 due），不升级 dispatch_stalled

#### Scenario: 重试痕迹在归档目录仍算证据

- **WHEN** 该 spec 的终态 impl 流已被保留清理移入 `.fenix/runs/archive/`（`.fenix/runs` 顶层无同名副本），
  末事件仍为 `transient_retry`/`superseded` 且未超窗口
- **THEN** 仍判为「框架内重试在途」并顺延，不因顶层无副本而升级

#### Scenario: 复查时已 blocked 不升级

- **WHEN** 复查到 spec 已是 blocked（或复查读取时已写入 blocked）
- **THEN** 关闭观察项、不升级 dispatch_stalled，避免与 blocked_stuck 通道重复告警

#### Scenario: 无正向证据的 implementing 仍升级

- **WHEN** spec 处于 implementing 且无活跃派发、无归属自身的运行痕迹（无流 / 末事件非重试标记 / 已超窗口）、
  无待合并过渡窗口
- **THEN** 维持既有 dispatch_stalled 升级（对齐 `tests/test_run_lifecycle_governance.py::test_defer_registers_watch_no_deadloop`）

#### Scenario: 确为 ready 滞留仍升级

- **WHEN** 复查确认 spec 仍为 ready、无依赖未满足、无过渡窗口、无活跃派发、就地重派发未成立
- **THEN** 维持既有 dispatch_stalled 升级（回归 3fad3350 语义）

### Requirement: 顺延有界性与保守失败

顺延 MUST 有界：自观察项首个 due 到期时刻（`registered_at + followup_check_minutes`）起累计顺延 MUST NOT 超过
`pm.recovery.defer_limit_minutes`（缺省 30），超限 MUST 回落既有 stale 判定并升级——MUST NOT 以「一直有重试痕迹 /
长期活跃态」把真实卡死洗成健康。配置不变量：`inflight_retry_minutes < defer_limit_minutes` 且
`defer_limit_minutes > followup_check_minutes`，违反时按 `_transition_grace_minutes`
（`core/pm_engine/recovery.py:254-286`）同一钳制范式收敛。

顺延判定 MUST 落在 `_recovery_watch.pop`（`recovery.py:178`）**之前**；若在升级路径上顺延，MUST 将观察项（含推进后的
due）写回 `_recovery_watch` 并调用 `_save_recovery_watch()`，MUST NOT 只改局部变量或不落盘。

重读 status / 运行痕迹失败或抛异常时 MUST 保守升级（不因本机制漏报真滞留）。

#### Scenario: 顺延累计超限回落升级

- **WHEN** 同一观察项的累计顺延已达 `defer_limit_minutes`，复查时仍命中重试痕迹/过渡窗口
- **THEN** 不再顺延，回落既有 stale 判定并升级 dispatch_stalled

#### Scenario: 二次复查读失败保守升级

- **WHEN** 升级前重读 status 或运行痕迹抛出异常/返回不可用结果
- **THEN** 按保守方向执行既有 dispatch_stalled 升级，不静默关闭观察项

#### Scenario: 顺延不丢观察项

- **WHEN** 本次判定命中任一正向证据而顺延
- **THEN** 观察项仍在 `_recovery_watch` 中且已持久化到 `.fenix/recovery_watch.json`（due 已推进），
  MUST NOT 静默丢弃或关闭观察项
