# Design: recovery-watch-status-recheck

## 背景与目标

refactor-giant-classes（2026-09-17）误报：spec 处于 implementing（正常推进态）时被 recovery watch 误判 stale，升级 dispatch_stalled（16:33:58Z），留未处理记录需人工核销。目标：升级前二次复查 status，把非 ready 停滞态排除在 dispatch_stalled 之外。

## 现状

core/pm_engine/recovery.py check_recovery_watch 复查路径（175-225 行）：

- 192 行：`status in RECOVERY_PROGRESS_STATUSES`（implemented/testing/verified/done/pushed）或 active_dispatch → passed；
- 202 行：status == ready 且无活跃派发 → 就地重新派发；
- 218-223 行：其余（含 blocked/implementing）→ 升级 dispatch_stalled。

缺口：RECOVERY_PROGRESS_STATUSES 不含 blocked/implementing，非 ready 停滞态直落升级；升级前无二次复查。

## 变更

1. **升级前二次复查**：在 218 行升级前插入 status 复查——`read_one(spec_name)` 重读，若 status 已偏离（blocked/implementing/testing 等非 ready 态）且不满足既有顺延豁免，则对齐 transition_defer 顺延（保留观察项、推进 due，复用 `_transition_defer_due` 范式），不升级；仍 ready → 升级。
2. **恢复推进判定扩展**：把 blocked 纳入「已恢复推进」语义（blocked 有独立 blocked_stuck 通道告警，recovery watch 不重复升级）——`status in (RECOVERY_PROGRESS_STATUSES + ("blocked",))` 判 passed，或升级路径前置检查等价处理。

## 边界

- 仅排除非 ready 停滞态误报，不改 ready 滞留升级语义（3fad3350 的 _dependencies_pending 豁免、文案中性化保持）；
- 顺延复用 guard 的范式（保留观察项推进 due），避免「顺延后仍卡死再升级」无限循环（recovery.py:99-100 既有约束）；
- 二次复查读失败/异常 → 保守升级（不因本机制漏报真滞留）。

## 回归测试

tests/test_recovery_watch_status_recheck.py：

1. 复查时已 blocked → 不升级 dispatch_stalled（复现 2026-09-17 16:33 事故）；
2. 复查时已 implementing → 顺延不升级；
3. 确为 ready 滞留 → 仍升级（回归 3fad3350 语义）；
4. 二次复查读失败 → 保守升级。