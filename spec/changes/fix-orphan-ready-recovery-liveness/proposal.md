## Why

2026-09-17 03:26Z 实测到一条**恢复静默失效**链路：daemon 主动停机（SIGTERM）时杀掉的在飞 run，会在重启后的首轮恢复扫描里被**误判为「仍有存活子进程」**，导致该 SPEC 的孤儿 ready 恢复被跳过；随后 30 分钟内无人再触发恢复，SPEC 空等整整一个扫描周期。

事故时间线（`.fenix/logs/fenixd.log` 逐条取证）：

| 时刻 (UTC) | 事件 |
|---|---|
| 03:26:26 | daemon 关停，向在飞 run `impl-fix-observability-gaps-1789605764-a1-r1` 发 SIGTERM |
| 03:26:27 | runner 收口，向该 run 流文件补写终态行 `{"type":"error","exit_code":143}`；STATE 落 `ready`、`_retry_count=1`、预算回退 `used 0/6` |
| 03:26:35 | daemon 重启，启动终态补写扫描**不改动**该文件（末行已是终态） |
| 03:26:40 | 首轮 `full_scan()` → `_recover_ready()` → 判「live child present」，**恢复被静默跳过** |
| 03:56:40 | 下一次恢复机会（`schedule.poll_interval_minutes` 周期扫描）——实际由 03:52:55 的一次自愈重启提前触发 |

两处独立缺陷叠加成这次静默失效：

**缺陷一：把「刚死的 run 的流文件」当成「活着的子进程」。**
`liveness.has_live_attempt()` 的存活判据是「pgrep 命中进程 → 否则回退『该 SPEC 任一 run 流文件 mtime < `LIVE_ATTEMPT_STREAM_WINDOW_SECONDS`（120s）』」。pgrep 未命中后，回退判据只看 mtime 窗口、**从不读末行**。而框架主动 SIGTERM 的死法恰恰会留下一行**终态**：

- 03:26:27 的 `error` 行由 runner 收口路径写入（`append_run_error`）；
- 该文件的 mtime 距 03:26:40 的首轮扫描仅 **13 秒**，远在 120s 窗口内。

于是「流文件新鲜」被等价成「进程还活着」——一条已经**明确宣告终结**的 run 反过来把恢复挡住了 30 分钟。判据把「有写活动」当成了「有生命」。

**缺陷二：孤儿 ready 的恢复只挂在 30 分钟的全量扫描上。**
`_recover_ready()` 唯一的调用方是 `full_scan()`，而 `full_scan()` 只有三个触发源：daemon 启动、`.fenix/STATE.md` 变化、每 `schedule.poll_interval_minutes`（缺省 30）的周期扫描。其中「STATE.md 变化」经 `_dispatch_changes()` 派发**只针对 status 发生变化的 SPEC**——“一直停在 ready”的孤儿不会产生任何变化，因此**没有任何事件源能唤醒它**。这类 SPEC 的恢复延迟被硬编码为「最坏一个扫描周期」。

对照既有能力声明，两处都属实现偏离而非设计取舍：`recovery-state-consistency` 声明「无存活子进程时恢复照常执行」，`full-scan-resilience` 声明「带 error 的孤儿 ready 获得重新派发」——本次实证的形态下两条都未生效。

## What Changes

- **存活判据区分「有写活动」与「有生命」（修改既有能力 `recovery-state-consistency`）**：`has_live_attempt()` 的流新鲜度回退路径 MUST 先排除**末行已成终态**的流文件——末行是 `result`/`error`/`interrupted`/`cancelled` 之一即代表该 run 已明确终结，不得再作为「存活」依据。判据的终态口径 MUST 与框架既有单源（`core/agent_runner/liveness.RUN_TERMINAL_EVENT_TYPES`）复用，不得另立集合。
  - 边界（MUST 显式保持）：`superseded` **不属于** run 终结——它是原地重试弃置旧产物的标记，run 在新 sub_run_id 文件继续（`fix-retry-orphan-active-runs`）。把 superseded 也算作「死」会在 artifact-gate 原地重试的退避窗口内误判，造成双派发。故终态集合取 `RUN_TERMINAL_EVENT_TYPES` 四类，**不含** superseded。
- **孤儿 ready 恢复改由短周期精触发（修改既有能力 `full-scan-resilience`）**：在 daemon 主循环既有的 60 秒计时段中，新增一次「孤儿 ready 恢复」精触发——逐条扫描 `ready` 态 SPEC，对确无驱动的条目走**与既有 full_scan 恢复完全同源**的处理路径（含 `start_after` 未到期 / `_cancelled_hold` / 存活子进程三道门 + `_on_spec_ready` 的全部派发闸门），使恢复延迟从「最坏一个扫描周期（30 分钟）」降到「最坏一个精触发周期（60 秒）」。
  - MUST NOT 缩短 `schedule.poll_interval_minutes`（30 分钟周期扫描仍为兜底，语义不变）；
  - MUST NOT 放宽任何派发闸门——精触发只是把既有判据跑得更勤，不是新判据；
  - MUST 有界：同一 SPEC 的重复恢复尝试按最小间隔节流，避免「被闸门拦下 → 回 ready → 60 秒后又试」的空转环（`add-spec-status-modal-budget` 每小时重验 9 轮同型事故）；稳态（error 已为空且无存活子进程）MUST 零 STATE 写入，避免「写 error → 触发 spec_ready 事件」的自激。

## Capabilities

### New Capabilities

（无——本次不引入新能力，只收紧既有能力的判据与触发时机。）

### Modified Capabilities

- `recovery-state-consistency`: 「卡死自动恢复前必须核验无存活子进程」这条 Requirement 的存活判据被收紧——流新鲜度回退路径 MUST 排除末行已为终态的流文件（该 run 已终结，不得计为存活）。现状是该门禁在「daemon 主动停机杀掉刚写的 run」这一形态下**假阳性**，把恢复挡在门外。
- `full-scan-resilience`: 「孤儿 ready 白名单恢复」这条 Requirement 的**触发时机**被补齐——孤儿 ready 的恢复不再只依赖 30 分钟的全量扫描，新增 60 秒粒度的精触发；白名单判据本身（存活子进程 / `start_after` / `_cancelled_hold`）不变，`full_scan` 仍为兜底。

## Impact

- 代码：
  - `core/agent_runner/liveness.py` — `has_live_attempt()` / `_stream_recent()` 的流新鲜度回退增加「末行终态即非存活」判定；新增尾部终态判定助手（与既有 `_file_has_terminal_event` 并列，共用 `RUN_TERMINAL_EVENT_TYPES` 单源）
  - `core/event_bus.py` — 新增 ready 恢复的精触发入口（复用既有 `_recover_ready`、`_ready_has_live_child`、`start_after_pending`、`_cancelled_hold` 判定，不新增判据）；稳态零 STATE 写入
  - `fenixd.py` — 主循环既有 60 秒计时段挂载精触发入口（对齐 `check_recovery_watch` / `check_scheduling_deadlines` 的挂载方式，不新建线程）
- 行为：
  - 被误判为「live child present」的孤儿 ready 恢复**即刻生效**（不再被刚死的 run 挡住）
  - 孤儿 ready 的恢复延迟从「最坏 30 分钟」降到「最坏 60 秒」
  - `full_scan` 触发源、`schedule.poll_interval_minutes` 默认值、优先级/并发/预算闸门、状态机合法转移表均不变
- 不改动：`admin_monitor` 的 `orphaned_state` 信号（覆盖 implementing/testing，已由 5 分钟监视周期覆盖）、`post-recovery-patrol` 的闭环复查语义（`recovery_watch` 仍为 15 分钟）、`runs` 归档保留策略。
- 测试：`tests/test_run_lifecycle_governance.py`（`has_live_attempt` 末行终态用例）、`tests/test_event_bus.py`（精触发用例与稳态零写入用例）、`tests/test_daemon_lifecycle_races.py`（终态口径单源防漂移，对齐既有漂移测试模式）。
