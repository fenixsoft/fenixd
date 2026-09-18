# Design: recovery-watch-status-recheck

## 背景与目标

refactor-giant-classes（2026-09-17）误报：16:33:58Z recovery watch 在 spec 处于 implementing、且当前无活跃派发
与新鲜运行痕迹时判其 stale，升级 dispatch_stalled，唤起 Administrator run 并最终升级人工（证据与完整时间线见
proposal「Why」，来源 `.fenix/logs/fenixd.log` / `.fenix/admin_alerts.json` / `.fenix/runs/archive/`）。

目标：在**不削弱真实卡死告警**的前提下，让 recovery watch 能识别「框架内部正在推进」（就地重试在途、终态流已归档、
待合并过渡窗口）这一形态，消除该类误报。

## 现状（`core/pm_engine/recovery.py` check_recovery_watch，163-225 行）

- 163-176 行：**过渡窗口豁免**（`_transition_defer_due`，326-394 行）在 `pop` 之前施加；D2(a) 判据用
  `_spec_recent_impl_stream_mtime`（288-324 行）取 `.fenix/runs` **顶层** `impl-<spec>-*.jsonl` 的 mtime，
  经 `run_spec_part` 精确归属；D1 判据用 `has_pending_merge` + `pending_merge_since`，带 grace 有界性。
- 178-179 行：`pop` 观察项并落盘；180-183 行：`read_one` 取 status（**此后到 218 行升级之间不再重读**）。
- 192 行：`status in RECOVERY_PROGRESS_STATUSES`（39 行：implemented/testing/verified/done/pushed）或
  `has_active_worktree` → passed（关闭观察项、不告警）。
- 202 行：status == ready 且无活跃派发 → `_redispatch_stalled_ready` 就地重派。
- 218-223 行：其余（含 blocked / implementing）→ 升级 dispatch_stalled。
- 35-39 行注释：implementing 不在恢复推进集合中为**刻意设计**——「实施中的 spec 由已有活跃派发（worktree 持锁）
  覆盖；无活跃派发的 implementing 属卡死形态，应告警」。该语义被
  `tests/test_run_lifecycle_governance.py::test_defer_registers_watch_no_deadloop` 固化（implementing + 无活跃
  worktree + 无运行痕迹 → `raised == ["s1"]`）。

### 缺口（实测定位）

1. **无「框架内重试在途」判据**：artifact-gate 不一致触发的 in-place retry（16:30:31Z `transient_retry`+`superseded`）
   到重试 run 开始输出（16:34:55Z）之间有约 4.3 分钟间隙，期间 spec 状态/锁/流 mtime 与真卡死形态完全等价
   → 16:33:58Z 误升级。
2. **终态流归档后痕迹不可见**：16:33:38Z 保留清理把 `impl-...-a2.jsonl` 移入 `.fenix/runs/archive/`，而 D2(a) 只
   glob 顶层 → 归档动作本身即抹掉了最后一条活性痕迹。
3. **升级前不重读状态**：180 行读取的 status 一直用到 218 行升级；期间若发生就地派发/闸门检查（202 行路径）而
   状态变更，升级仍按陈旧值执行。
4. **blocked 与 blocked_stuck 双通道重复告警**：blocked 已有 `admin_monitor._detect_blocked_stuck`
   （`core/admin_monitor.py:690`），recovery watch 再升级属重复（本案 16:37Z 该 spec 转 blocked 后即产生
   blocked_stuck 记录，两条通道同时指向同一 spec）。

## 变更

1. **升级前复查（状态 + 正向证据）**——在 218 行升级前重读 `read_one(spec_name)` 与运行痕迹，按下列顺序判定：

   | 复查结果 | 处置 |
   |---|---|
   | `status == "blocked"` | 关闭观察项、**不升级**（交 blocked_stuck 通道）；frozen blocked 同样关闭不告警（对齐 `fix-blocked-freeze-classification` 对 frozen 的 admin_monitor 豁免） |
   | 既有 D1/D2 过渡窗口命中（163-176 行既有判据） | 顺延（保留观察项、有界推进 due） |
   | **框架内重试在途**：最近一次归属该 spec 的 impl 流末事件 ∈ {`transient_retry`, `superseded`} 且 `now - 末事件时间 ≤ inflight_retry_minutes` | 顺延（同上） |
   | 其余（含无正向证据的 implementing / testing 等） | **维持既有升级**（不因 status 非 ready 本身顺延） |
   | 重读失败/异常 | 保守升级（不因本机制漏报真滞留） |

2. **运行痕迹检索口径**：`_spec_recent_impl_stream_mtime` 的检索路径扩展为 `.fenix/runs` 顶层 + `.fenix/runs/archive/`
   （先例：`engine.py:798` `get_runs(..., include_archive=True)`）；归属判定继续用 `run_spec_part`（`-a<n>`/`-r<n>`
   后缀剥离已在 `core/agent_runner/run_files.py` 实现，实测 `run_spec_part("impl-x-1789641481-a2-r1") == "x"`），
   MUST NOT 用裸 glob 命中判定（前缀歧义守卫保持）。新增末事件读取（JSONL 最后一行 `type` 字段）。

3. **blocked 归入「已恢复推进」**：`status == "blocked"`（含 frozen blocked）判 passed——关闭观察项、不告警，
   由 blocked_stuck 通道接管（`RECOVERY_PROGRESS_STATUSES` 或升级路径前置检查等价实现，实现自由）。

4. **有界性（必守）**：新增 `pm.recovery.defer_limit_minutes`（缺省 30），起算点 = 观察项登记时的首个 due 到期时刻
   （`registered_at + followup_check_minutes`，实现可另存 `recheck_deadline` 字段以便重启后续算）；累计顺延超过上限即
   回落既有 stale 判定并升级。新增 `pm.recovery.inflight_retry_minutes`（缺省 5）。不变量：
   `inflight_retry_minutes < defer_limit_minutes`，且 `defer_limit_minutes > followup_check_minutes`；配置违反时按
   `_transition_grace_minutes`（254-286 行）同一钳制范式收敛。

5. **顺延落点**：顺延判定 MUST 落在 178 行 `pop` **之前**（对齐 D2 顺延落点，避免裸 `continue` 丢观察项）；
   若改在 218 行升级路径上顺延，MUST 重新写回 `_recovery_watch[spec_name]`（含 due）并 `_save_recovery_watch()`。

## 边界

- **不改 ready 滞留升级语义**：3fad3350 的 `_dependencies_pending`（`engine.py:2285`，属 `check_blockers` 假就绪巡检，
  不在 recovery watch 路径）与信号文案中性化均保持；
- **不因 status 非 ready 顺延**：这是本设计的关键约束——否则 `test_defer_registers_watch_no_deadloop`
  与 recovery.py:35-39 注释语义同时被破坏（真实卡死在 implementing 上永不告警）；
- 顺延必须**有界**（第 4 条），避免「重试痕迹/活跃态长期存在」把真实卡死洗成健康；
- 二次复查读失败/异常 → 保守升级（不因本机制漏报真滞留）；
- 既有过渡窗口判据全部保持（D2(a) 缓冲 60s、D1 grace 缺省 5min 及其有界回落不变）。

## 回归测试

`tests/test_recovery_watch_status_recheck.py`：

1. **框架内重试在途 → 顺延不升级（复现 2026-09-17 16:33:58 事故）**：流末事件 `transient_retry`/`superseded` 且
   距事件 < `inflight_retry_minutes` → `raised == []`，观察项保留且 due 推进；
2. **同案归档形态**：痕迹文件位于 `.fenix/runs/archive/`（顶层无副本）→ 仍顺延（口径回归，防只查顶层）；
3. **重试窗口超时 → 仍升级**：末事件距 now > `inflight_retry_minutes` → `raised == ["s1"]`；
4. **blocked → 关闭观察项不升级**：`raised == []`、观察项弹出、无 dispatch_stalled 记录（不重复 blocked_stuck）；
5. **无正向证据的 implementing → 仍升级**：无流、无重试痕迹、无待合并 → `raised == ["s1"]`（保持
   `test_defer_registers_watch_no_deadloop` 语义，不得回归）；
6. **确为 ready 滞留 → 仍升级**（回归 3fad3350 语义；就地派发被闸门拦下形态已有既有用例，此处只补最小断言）；
7. **有界性**：顺延累计超过 `defer_limit_minutes` → 回落升级；
8. **二次复查读失败 → 保守升级**。

另需保持既有用例全绿：`tests/test_recovery_watch_transition_guard.py`（全量）、
`tests/test_run_lifecycle_governance.py`（含 `test_defer_registers_watch_no_deadloop`）、`tests/test_pm_recovery.py`。
