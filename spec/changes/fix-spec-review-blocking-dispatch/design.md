## Context

spec-review 是 daemon 中唯一仍在调用栈上同步执行的 agent run。它的派发收口点 `SpecReviewManager.dispatch_review`（`core/pm_engine/spec_review.py:90`）把「锚点先落盘 → 快照 → **阻塞执行** → 机械收口」四步串在同一个调用栈上，其中第三步是分钟级的 `run_spec_review` → `_run_claude`。

调用方一共四条，分布在三个线程上：

| 入口 | 线程 | 触发时机 |
|---|---|---|
| `start()` → `event_bus.full_scan()` → `_recover_one` → `handle_event("spec_reviewing")` | MainThread | daemon 启动，**主循环之前**（`fenixd.py:491`） |
| `_watch_loop` → `_dispatch_changes` → `handle_event` | fenixd-watcher | STATE.md 变化，2s 轮询 |
| `_periodic_scan_loop` → `full_scan` | fenixd-scanner | 每 30 分钟兜底 |
| `_check_scheduling_kick_requests` → `_on_spec_drafted` | MainThread | 定时拾取到期唤起 |

其中 daemon 启动路径最致命：`full_scan` 在主循环 `while self.running` **之前**同步执行，recovery 一旦捡到待评审 spec，主循环就永远进不去——`_check_admin_invoke_requests` / `_check_cancel_requests` / `_check_approve_push_requests` / `_check_code_review_requests` / `_check_scheduling_kick_requests` 五个消费者一个都不会被执行。

对照 implementer：`_on_spec_ready` → `_enqueue(spec_name, "implementer")` 只往队列塞一条记录就返回，真正的 run 在 `_process_queue` → `threading.Thread(target=_run_agent_worker)` 里跑。**同一条派发链，处理方式相反。**

架构约束（必须在设计里显式处理）：

1. **锚点的双重语义**。`reviewer_run` 在 run 启动前写入（`spec_review.py:170`），所以「非空」同时表示「在飞」和「已落锚点待消费」。`dispatch_review` 与 `_should_defer_for_reviewer` 都依赖它防重派。异步化后，写锚点的线程与收口的线程不同，中间有窗口。
2. **`_review_dispatches` 守卫靠同步阻塞成立**。`engine.py:581` 注释明说：「dispatch_review 同步阻塞（评审 run 分钟级），守卫须覆盖整个阻塞期」。异步后调用方立即返回、`finally` 释放守卫，第二条通道可在锚点写入前挤进来。
3. **`full_scan` 的执行时机不能简单挪走**。`fenixd.py:480` 注释记录 2026-09-07 事故：`event_bus.start()` 必须先于首扫建立 STATE 基线快照，否则全部存量 SPEC 被判「新出现」、pushed 等 hook 事件全量重放，15+ spec 的 commit-push hook 连环触发。
4. **状态机写是文件锁保护的**（`core/state_machine.py:466` `flock`），多线程写 STATE 安全，但「读-判-写」序列不原子。

## Goals / Non-Goals

**Goals:**

- spec-review 的派发不再阻塞任何调用方线程，主循环在启动后 ≤ 数秒内进入 tick。
- 评审 run 与 implementer 走完全相同的执行机制（派发队列 + 独立线程），形状可预测、复用既有调度语义。
- 评审不占 `agents.max_concurrent` 名额、不参与优先级档位比较与队列老化——晋升门不该与实现抢槽位。
- 收口语义（结论机械消费、三类失败分类、重试与冻结、人工恢复入口）零变化。
- 同 spec 的评审并发派发仍被挡住（不因异步化而引入双跑）。

**Non-Goals:**

- **不修 code-review 的产物硬门缺口**。本次立项过程中实测发现 `run_code_review` 全程无产物门调用、out 文件缺失时静默 `success=True`、审计空跑，用户明确要求「单独处理」，不在本 SPEC 范围。
- 不改 admin_monitor 线程里其它同步跑 agent 的点（`run_administrator`、self-review checkpoint）——它们阻塞的是 admin 巡检线程而非主循环，病因与修法不同。
- 不新增配置键、不改 Dashboard 设置页（评审不设并发上限，无需新控件）。
- 不重构 agent_runner 的 `_run_claude` / `_running_agents` 注册机制。

## Decisions

### D1：并入派发队列，而非新建评审 worker 池

**选择**：`_on_spec_reviewing` 改为 `self._enqueue(spec_name, "spec-review")`，`_run_agent_worker` 新增 `spec-review` 分支调 `SpecReviewManager.dispatch_review`。

**理由**：用户明确要求「与 implementer 完全同构」。这直接复用 implementer 验证过多年的机制——队列去重、优先级档、老化降级、`_run_agent_worker` 的异常回滚 `_rollback_failed_dispatch`、`finally` 里的槽位释放与 `_process_queue` 再触发、排水时 `running_run_ids()` 天然可见。

**替代方案**：

- *新建独立 worker 池*（仿 `_admin_executor`）：需新增配置键 + Dashboard 控件，且引入第三套并发生命周期；收益仅是形式上的隔离。
- *复用 `_admin_executor`*：零新配置键，但该池（`admin.workers` 缺省 2）已承载 admin 处置、code-review、evolution 三类分钟级 run，再加分钟级评审会互相饿死。

### D2：评审条目不占 `_active_runs`、不进 `_active_priorities`

**选择**：`_process_queue` 出队后，`spec-review` 条目 SHALL NOT 执行 `self._active_runs += 1`，也 SHALL NOT 写 `_active_priority_counts` / `_active_priorities`。

**理由**：

- `max_concurrent` 的语义是「实现车道槽位」。评审卡住它会让「先审后跑」退化为「审等实现跑完」——三个实现 run 在跑时，新 spec 的评审要排队，而它的 ready 又挡住下一轮实现，形成相互等待。
- `_active_priorities` 参与 `best_valid_prio > min_active` 的宽松优先级判定。评审条目若进档，会以「更重要的活动任务」身份把低优先级的实现条目挡在门外——与它不占槽位的语义矛盾。

**代价**：需要独立的在飞计数（D3）。

**边界**：优先级档比较对评审条目**仍按 `_effective_priority` 计算并参与 target 选择**（即评审也会按优先级排队），只是它不进入活动集合去影响别人。这样评审之间仍有顺序，但不挤压实现。

**槽位闸门的第二处（实证补记，MUST 处理）**：仅「不计入 `_active_runs`」不足以让评审「不因实现槽位占满而等待」——`_process_queue` 在**扫描队列之前**还有一道 `if self._active_runs >= max_concurrent: return`（`core/pm_engine/dispatch/queue.py:233`）。实现车道跑满时该早退使队列里的评审条目**根本不被扫描**，`spec-concurrency-governance` 的 Scenario「评审不挤压实现派发」不可达。故：

- 当队列中存在状态合法的评审条目时，`_process_queue` MUST NOT 因 `_active_runs >= max_concurrent` 提前返回；实现/verifier 条目仍受该闸门约束。
- 该闸门的绕过 MUST 只放行**评审条目本身**，MUST NOT 顺带放行同轮的实现条目（否则 `max_concurrent` 对实现车道失效）。

### D3：新增 `_active_reviews` 集合，作为评审在飞的独立登记

**选择**：`DispatchQueue` 新增 `_active_reviews: set[str]`（spec 名集合），在评审条目出队时 add、在 worker `finally` 释放。

**理由**：

- 观测与幂等：`_process_queue` 在同一轮内可能多次扫到同一 spec 的评审条目（若队列里有多条），需要集合去重。
- `reviewer_in_flight`（`core/agent_runner/liveness.py:448`）当前判据是「`reviewer_run` 非空 且 进程表/流文件说它在跑」。异步化后，从 `_enqueue` 到 `run_spec_review` 首次注册进 `_running_agents` 之间有窗口——期间进程表与流文件都判否，会落到 `stale` 分支，诱导调用方清理锚点。`_active_reviews` 补上这个窗口。

### D4：单飞守卫改为「锚点 + `_active_reviews`」双判据，贯穿在飞期

**选择**：`_on_spec_reviewing` 的守卫改为——`spec_name in self._active_reviews` → 跳过；否则检查 STATE 的 `reviewer_run` 非空 → 跳过；否则 `_enqueue`。

**理由**：现状 `_review_dispatches`（`engine.py:366`）在 `finally` 里 `discard`，异步化后派发即返回、守卫立即释放，窗口敞开。改为：

- `_active_reviews` 覆盖「已入队 / 已出队未收口」；
- `reviewer_run` 非空覆盖「锚点已落盘但 run 尚未注册」；
- 两者都在收口路径（`consume_review_result` / `_handle_review_failure` 清 `reviewer_run`、worker `finally` 释放 `_active_reviews`）清理，与锚点生命周期对齐。

**替代方案**：把 `_review_dispatches` 的 discard 从 `finally` 挪到收口处。否决——它存在 `engine` 实例上，与队列在 `DispatchQueue` 上的职责边界不清；`_active_reviews` 放在队列侧与 `_active_runs` 并列，语义更内聚。

**重入安全性（MUST，实测约束）**：`_run_claude` 的尝试环在同线程内可直接续跑下一 attempt（`core/agent_runner/runner.py:3265`），且评审 run 时长可达分钟级。若 `_active_reviews` 在**整个 worker 生命周期**内保持置位，则同一线程内的续 attempt 在 `dispatch_review` 入口看到自己仍在集合中而被拒——评审收口被自己挡住（本 SPEC 引入的新死锁）。故 MUST 满足：

- 在飞登记 MUST 覆盖窗口 = 「条目出队 → 四步链的锚点（`reviewer_run`）落盘」，即集合的释放时点 MUST NOT 晚于锚点落盘；锚点落盘后由判据 2（`reviewer_run` 非空）接力。
- 单飞判据的生命周期口径 MUST 统一为 `consume_review_result`/`_handle_review_failure` 清锚点 + worker 释放 `_active_reviews`，`tasks.md` 中「出队时置位、收尾时释放」的表述 MUST 与该窗口一致。
- `dispatch_review` 入口的在飞判据 MUST 取 `reviewer_in_flight` 的**在飞结论**（`in_flight == True`），仅当结论为「陈旧锚点」（`reason == "stale"`）时才允许清理锚点后继续派发；MUST NOT 按「锚点是否非空」直接自清——否则与 `_should_defer_for_reviewer` 的 fail-open（判定异常 → `(False, None)`）叠加后可在评审仍在跑时清锚点并放行并发派发。

### D5：`full_scan` 从启动主路径移到后台线程，但基线快照仍在 watcher 之前

**选择**：`fenixd.py:start()` 中：

```
self.event_bus.start()        # 必须最先：建立 STATE 基线快照
self.event_bus.full_scan()    # 改为：后台线程执行，不阻塞主循环
```

具体做法：`full_scan` 拆成两段——`_snapshot_baseline()`（同步，毫秒级，只做 `_update_known_state`）与 `_run_full_scan_body()`（异步）。`start()` 先同步调前者，再提交后者到后台线程，随后立即进入主循环。

**理由**：`start()` 里的注释（`fenixd.py:480`）记录得很清楚——「start() 会建立 STATE 基线快照（_update_known_state），若首扫先行，_known_specs 为空，全部存量 SPEC 被判为『新出现』，pushed 等 hook 事件被全量重放」。直接把 `full_scan` 丢进后台线程会把这个顺序依赖打乱：watcher 先跑一轮 `_dispatch_changes` 时基线还是空的。

**实现口径（MUST，防模块 API 自吞）**：

- `full_scan()` MUST 保留为同步入口（`_snapshot_baseline()` + 扫描主体顺序执行的两段组合），其既有调用方语义逐字不变——`fenixd.py:491` 改为分别调用两段，`event_bus._periodic_scan_loop`（`core/event_bus.py:645`）继续整调用同步版，`start()` **MUST NOT** 调用异步版（否则后台扫描线程永被同步等待吞掉，本次修复静默失效）。
- 异步扫描线程 MUST 携带 `daemon=True` 标记；`EventBus` 需要新增此线程的持有字段并以**同一命名风格**（`fenixd-*` 同族）标记，`stop()` 的收口语义（`self._running = False` + 短 join）SHALL 覆盖它。
- 基线不变量由 `event_bus.start()` 本身保证（`core/event_bus.py:51` 已同步调用 `_update_known_state()`，早于 watcher 线程启动）；`_snapshot_baseline()` 属**显式化该不变量**的冗余加固，任务 4.1/4.2 仍 SHOULD 按计划实施（把隐式依赖变为显式契约），但不得以此为理由改动 `start()` 的同步/异步划分。

**替代方案**：

- *保持 `full_scan` 同步不动*：评审异步化后它已不再被评审阻塞，但 recovery 里还有其它 `handle_event` 同步链（如 `spec_implemented` → `_enqueue`，虽轻量）。**否决理由**：范围最小，但「启动期主循环不响应」这个用户可见症状会残留（recovery 里若有别的耗时分支仍会拖住）。且首扫本身在历史上有 1802s 的长尾记录。
- *完全不调 `full_scan`*：recovery 失效，卡死的 spec 永远不恢复。

### D6：`re_review` / 复评派发点改投队列，去掉 `agent_runner is None` 分支

**选择**：`spec_review.py:393`（rejected 后自动复评）与 `re_review`（`spec_review.py:880`）的 `if self.agent_runner is not None: self.dispatch_review(...)` 改为 `self.pm_engine._enqueue(spec_name, "spec-review")`。

**理由**：

- CLI / Dashboard 侧构造的 `SpecReviewManager` 传 `agent_runner=None`（`bin/fenix_cli.py:95`、`core/dashboard/data/admin_actions.py:342`），因为它们是**跨进程**的——真正的 daemon 在另一个进程里，CLI 只能落状态、等 daemon 的 recovery 拾取。改投队列后这个分支依然要保留（CLI 场景 `pm_engine` 也是 None），但 daemon 侧不再是「直接执行」而是「投队列」。
- 语义收益：re_review 成功后状态已是 `reviewing`，daemon 侧由 in-process 队列接力；CLI 场景由 recovery 的 `reviewing` 分支接力。两条路都通。

### D7：收口语义原地保留，仅挪线程

**选择**：`dispatch_review` 的四步链不改结构，仍由 worker 线程内的同一次调用完成。

**理由**：`consume_review_result` 内部依赖 `attempt_started_at`（本轮 attempt 的启动 epoch）做 mtime 新鲜度校验（`_check_agent_result_artifact` 的 `run_started_at` 参数），这个时间戳在 `dispatch_review` 局部变量里产生，必须与执行在同一调用栈上；拆开会让新鲜度校验失去基准。

**风险**：worker 线程崩溃（非异常而是线程死亡）会导致锚点残留。缓解：由既有 recovery 的 `reviewing` 分支兜底（`_should_defer_for_reviewer` 的 stale 分支会放行并记 WARNING），且 `_active_reviews` 在 `finally` 释放——`finally` 对异常有效，对线程被杀无效（daemon 整体退出时随进程消失，不影响）。

## Risks / Trade-offs

- **[评审 run 崩溃后锚点残留]** → `_handle_review_failure` 与 recovery 的 stale 分支已有清理路径；`_active_reviews` 在 `finally` 释放。**精度约束（实证）**：`_rollback_failed_dispatch`（`core/pm_engine/dispatch/rollback.py:72`）当前只有 `verifier`/`implementer`/`fast-track` 三个分支，`agent_type == "spec-review"` 落入其 `if/elif` 之外，**只记一条 error 日志、不改状态也不重入队**。故 worker 内异常时的收口 MUST 显式区分两层，MUST NOT 把「异常被捕获」当作「状态已收口」：
  - 四步链**内部**异常（`run_spec_review` 抛错等）已在 `dispatch_review` 内由既有 `except` 捕获并走 `_handle_review_failure`（重试/冻结），属正常收口路径，行为与改造前逐字一致；
  - 四步链**之外**的异常（构造 `SpecReviewManager` 失败、快照/日志路径异常等）落到 worker 的 `except`：此时锚点与状态可能均为「未推进」，spec 停在 `reviewing`，MUST 由 `_active_reviews` 释放（`finally`）+ 既有 recovery 的 `reviewing` 分支（`core/event_bus.py:175-198`）重新拾取，恢复延迟上界为 watcher/periodic 扫描周期而非「无界」。任务 1.8 若仍按「复用 `_rollback_failed_dispatch`」实现，MUST 同时为 `spec-review` 补一条分支（清 `reviewer_run` + 保持 `reviewing` + 重新入队），并在任务备注中说明取舍。
- **[异步化后 `_active_reviews` 与实际在飞不一致]**（如 worker 线程被 daemon 排水 SIGTERM 终止）→ `finally` 对 SIGTERM 后正常退出有效；进程被 SIGKILL 时 `_active_reviews` 随内存消失，daemon 重启后由 recovery 的 `reviewing` 分支重新拾取。与 `_active_runs` 的既有容错同构。
- **[`full_scan` 异步后启动窗口内 recovery 未完成，新的 STATE 变更先被 watcher 处理]** → 这是可接受的：recovery 处理的是「上次异常退出遗留的中间态」，watcher 处理的是「新变化」，两者通过 `_known_specs` 基线隔离。首扫期间 watcher 已在跑，但基线的快照已提前建立（D5）。
- **[评审不占槽位后，短时间大量 spec 同时晋升会并发起多个分钟级评审]** → 用户明确接受（「不设上限」）。可观测性由 `_active_reviews` 提供，必要时后续可加配置。
- **[`_process_queue` 的重复扫描逻辑翻倍]** → 现有 `_process_queue` 已经因为「状态闸门」在 best_valid_prio 扫描与 dispatch_idx 扫描两处重复了 26 行守卫（`_should_defer_for_reviewer` 的注释正是在吐槽这点）。新增 spec-review 闸门时会再增加两处重复。**缓解**：把 spec-review 的合法性判定提取为方法（同 `_should_defer_for_reviewer` 范式），两处调用。

## Migration Plan

无需数据迁移。评审条目是内存态队列元素，daemon 重启即重建。

部署顺序：单次代码提交，daemon 重启后生效。回滚即 git revert + 重启 daemon。

存量 `reviewing` 状态的 spec（若有）在 daemon 重启后由 recovery 的 `reviewing` 分支重新入队，无需人工干预。
