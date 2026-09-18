# Proposal: recovery-watch-status-recheck

## Why

2026-09-17 16:33:58Z refactor-giant-classes 误报事故（admin store 信号 id `24ae002d605c`，evidence：
`spec still implementing with no active dispatch after followup window, in-place redispatch not established`）：
recovery watch 判该 spec stale 并升级 dispatch_stalled，唤起 Administrator run
`admin-refactor-giant-classes-1789663092`；该 run 随后因 daemon 关闭中断、被 AdminMonitor 升级人工
（17:55:28Z escalation `16ba51c52562`），留下未处理记录需人工核销。

实测时间线（`.fenix/logs/fenixd.log` / `.fenix/admin_alerts.json` / `.fenix/runs/archive/`）：

- 16:08:04Z 观察项登记（`auto-recovery deferred (live child present)`），复查窗口 15 分钟；
- 16:23:53Z–16:32:58Z 连续 10 次 `Recovery watch deferred ... (transition window active)`——期间 impl run
  `impl-refactor-giant-classes-1789641481-a2` 在跑，既有过渡窗口豁免（evo-recovery-watch-transition-guard
  D2(a) 流 mtime / D1 待合并）**正常工作**；
- 16:30:31Z 该 run 终止：流末事件 `transient_retry` + `superseded`（artifact-gate 不一致 → in-place retry
  1/3 已排程，`core/agent_runner/runner.py:2368/2384`）；16:33:38Z 终态流被保留清理移入 `.fenix/runs/archive/`；
- 16:33:58Z 顺延判据全部落空（流已不在顶层 runs 目录、待合并 grace 到期）→ 升级 dispatch_stalled；
- 而框架内重试 run `impl-refactor-giant-classes-1789641481-a2-r1` 在 16:34:55Z（误报 56 秒后）即开始输出，
  16:37:29Z `implementer succeeded`。

**真因**：顺延判据只认「状态 + worktree 锁 + **顶层** runs 目录的近期流 mtime + 待合并 grace」，缺少
「**框架内重试在途**」这一正向证据，也未覆盖「终态流已归档仍算痕迹」的检索口径——重试间隙内该 spec 与
真卡死形态观测等价，故误报。

既有防护均未覆盖此变体：evo-recovery-watch-transition-guard 只覆盖「成功收工过渡窗口」（流仍在顶层、60s
缓冲内）；3fad3350 只覆盖 `check_blockers` 假就绪巡检的「依赖未满足 ready 假就绪」
（`engine.py:2285 _dependencies_pending`，不在 recovery watch 路径上）。

> **评审修正（2026-09-18，据实测证据）**：本 SPEC 初稿把根因归为「`RECOVERY_PROGRESS_STATUSES` 不含
> blocked/implementing」。实测证伪：观察期内既有顺延机制已连续 10 次正确抑制告警，误报发生在顺延判据落空的
> **重试间隙**，不是状态集合成员问题；且 `core/pm_engine/recovery.py:35-39` 明确记载 implementing 不在集合中
> 是刻意设计（「无活跃派发的 implementing 属卡死形态，应告警」）。若把非 ready 态一律排除在升级之外，会破坏
> D6/3.1 的「到期即信号」不变量（`tests/test_run_lifecycle_governance.py::test_defer_registers_watch_no_deadloop`
> 已固化该语义：implementing + 无活跃派发 + 无运行痕迹 → 必须升级）。故本方案改为**补充正向证据判据 + 有界顺延**，
> 不改为「非 ready 一律顺延」。

## What Changes

- **升级前复查（状态 + 运行痕迹）**：判定 stale 与升级之间 MUST 重读当前状态与运行痕迹；命中任一**正向证据**
  → 不升级：
  - `status == "blocked"` → 关闭观察项、不告警（blocked 有独立 `blocked_stuck` 通道，`core/admin_monitor.py:690`，
    recovery watch 不重复升级）；
  - 既有过渡窗口判据（D2(a) 流缓冲 / D1 待合并 grace）命中 → 按 transition_defer 范式顺延（保留观察项、有界推进 due）；
  - **框架内重试在途**：该 spec 最近一次归属其自身的 impl 流末事件为 `transient_retry` / `superseded`（runner 原地
    退避重试留痕，`runner.py:2368/2384/2503/2518`）且距该事件不超过 `pm.recovery.inflight_retry_minutes`（缺省 5）
    → 顺延；**无正向证据的非 ready 停滞态 MUST 维持既有升级**（真实卡死仍可见）。
- **归属与归档检索口径**：运行痕迹 MUST 以 `run_spec_part` 精确归属（覆盖 `-a<n>`/`-r<n>` 后缀），且 MUST 同时
  检索 `.fenix/runs` 顶层与 `.fenix/runs/archive/`（终态流会在告警前被保留清理归档——2026-09-17 16:33:38 归档、
  16:33:58 误报，只查顶层即漏判；归档含检先例见 `engine.py:798` `get_runs(..., include_archive=True)`）。
- **有界性**：顺延 MUST 有界——自观察项首个 due 到期时刻起累计顺延不得超过 `pm.recovery.defer_limit_minutes`
  （缺省 30），超限回落既有 stale 判定并升级，避免「一直有重试痕迹/一直 blocked」把真实卡死洗成健康。
- **顺延落点**：顺延判定 MUST 在 `_recovery_watch.pop` **之前**生效；若实现选择在 pop 之后升级路径上顺延，
  MUST 把观察项写回并 `_save_recovery_watch()`（不得只改局部变量）。

## Capabilities

### New Capabilities

- `recovery-watch-status-recheck`: recovery watch 升级前的状态/运行痕迹复查与有界顺延——消除「框架内重试间隙 +
  终态流已归档」形态的 stale 误报，同时保持无正向证据的非 ready 停滞态照常升级。
