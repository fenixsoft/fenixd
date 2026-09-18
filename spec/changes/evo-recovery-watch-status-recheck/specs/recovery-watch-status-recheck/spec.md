# recovery-watch-status-recheck

## ADDED Requirements

### Requirement: 升级前 status 复查

recovery watch 判定 stale 并升级 dispatch_stalled 之前，MUST 二次复查 spec 当前 status：已偏离 ready（blocked / implementing / testing 等非 ready 停滞态）时 MUST 顺延本次判定（保留观察项、推进 due，对齐 evo-recovery-watch-transition-guard 的 transition_defer 顺延范式），MUST NOT 升级 dispatch_stalled；仅当复查确为 ready 且无进展时升级。

#### Scenario: 复查时已 blocked 不升级

- **WHEN** recovery watch 复查到 spec 已是 blocked（或复查后立即写入 blocked）
- **THEN** 顺延本次判定、不升级 dispatch_stalled，避免与 blocked_stuck 通道重复告警

#### Scenario: 复查时已 implementing 不升级

- **WHEN** spec 处于 implementing（正常推进态）且无活跃派发
- **THEN** 顺延本次判定，不升级 dispatch_stalled

#### Scenario: 确为 ready 滞留仍升级

- **WHEN** 复查确认 spec 仍为 ready、无依赖未满足、无过渡窗口、无活跃派发
- **THEN** 维持既有 dispatch_stalled 升级