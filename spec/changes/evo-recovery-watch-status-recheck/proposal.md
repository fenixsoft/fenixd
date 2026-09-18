# Proposal: recovery-watch-status-recheck

## Why

2026-09-17 refactor-giant-classes 误报事故：recovery watch（周期复查异常 spec 是否滞留、滞留则升级 dispatch_stalled 的机制）在 spec 处于 implementing（正常推进态）时复查，将其误判为 stale 升级一条 dispatch_stalled 告警（16:33:58Z），留未处理记录需人工核销。根因：recovery.py 的恢复推进判定集合 RECOVERY_PROGRESS_STATUSES 只含 implemented/testing/verified/done/pushed，**不含 blocked 与 implementing**——非 ready 停滞态（blocked 待裁决、implementing 过渡）被误判为滞留；且升级路径（recovery.py:218-223）在打信号前无二次 status 复查。既有防护均未覆盖此变体：evo-recovery-watch-transition-guard 只覆盖「成功收工过渡窗口」，3fad3350 只覆盖「依赖未满足 ready 假就绪」。

## What Changes

- **升级前 status 复查**：dispatch_stalled 升级前二次复查当前 status——已偏离（blocked/implementing/testing 等非 ready 停滞态）时顺延本次判定（对齐 evo-recovery-watch-transition-guard 的 transition_defer 顺延范式，保留观察项、推进 due），不升级；确为 ready 滞留才升级。
- **恢复推进判定补 blocked/implementing**：把 blocked（待裁决为正常态、有独立 blocked_stuck 通道告警）纳入恢复推进语义，避免 recovery watch 与 blocked 通道重复告警。

## Capabilities

### New Capabilities

- `recovery-watch-status-recheck`: recovery watch 升级前的 status 复查——消除非 ready 停滞态被误判 stale 的竞态误报。