# fix-spec-review-blocking-dispatch

## Why

**spec-review 的派发是全库唯一仍在调用栈上同步执行的 agent run**，它把 daemon 主循环连同全部文件信号消费者一起钉死数分钟到数十分钟。

2026-09-19 实证（本次立项的直接触发）：19:14 之前 daemon 重启，`start()` 在进入主循环**之前**同步调用 `event_bus.full_scan()`（`fenixd.py:491`），recovery 的 `reviewing` 分支捡起刚晋升的 `add-impl-code-review-tuning`，经 `handle_event` → `_on_spec_reviewing` → `dispatch_review` → `run_spec_review` → `_run_claude` 一路同步阻塞（`core/pm_engine/spec_review.py:188`）。结果：

- daemon 从 18:46:46 起 27 分钟没有打印过 `Entering main loop`（日志实测），主循环一次都没转过；
- 用户在 Dashboard 点「全仓库审查」，端点返回「已受理」并写入 `.fenix/code_review_request.json`，**进度条出现几十秒后消失**——因为消费者 `_check_code_review_requests` 在主循环里，从未被调用；
- 同一队列上排着的 `cancel_run`、`approve_push`、`admin_invoke`、`scheduling_kick` 五个文件信号消费者全部一起停摆。

同类记录：`fix-admin-run-blocks-mainloop`（2026-09-08 归档）修的是同一种病的 administrator 变体——「处置期间整个主循环停摆，实测拾取延迟最高 231 秒」，修法是把 admin run 挪进后台 worker 池。**但 spec-review 这条链没被一起改**，同病只治了一个入口。

排除项（取证已做）：非 OOM、非系统重启、非死锁——py-spy 显示主线程在 `_run_claude` 中正常推进，是纯粹的同步等待。

## What Changes

**把 spec-review 的派发并入既有派发队列，与 implementer 完全同构；评审不占用 `agents.max_concurrent` 名额。**

- **并入派发队列**：`_on_spec_reviewing` 不再直接调 `dispatch_review`，改为 `_enqueue(spec_name, "spec-review")`，与 `_on_spec_ready` → `_enqueue(spec_name, agent_type)` 完全同形。评审 run 由 `_run_agent_worker` 在独立 `threading.Thread` 中执行（`core/pm_engine/dispatch/queue.py:575`），调用方立即返回。
- **不占并发槽位**：`agents.max_concurrent`（当前 3）是**实现车道的槽位**（implementer / fast-track / verifier / repair 共用）。评审是晋升前置门，占用实现槽位会把「先审后跑」退化成「审等实现跑完」。评审条目 SHALL NOT 增减 `_active_runs`，也 SHALL NOT 进入 `_active_priorities` —— 因而不参与宽松优先级档位比较、不挤压实现派发、不参与队列老化降级。评审自身的在飞计数 SHALL 独立登记（`_active_reviews`），用于同 spec 防重派与可观测性，**不设并发上限**（用户决策：评审次数天然稀疏，每个 spec 晋升时一次）。
- **收口语义原地不变**：「锚点先落盘 → 快照 → 执行 → 机械收口」四步链完整保留在 `dispatch_review` 内，只是从调用方线程搬到 worker 线程。approved/repaired → ready、rejected → blocked/复评、artifact/infra/content 三类失败分类、熔断短路、`_review_attempts` 递增与达上限冻结转人工——全部保持现有语义。
- **单飞守卫改为贯穿在飞期**：现守卫 `_review_dispatches`（`engine.py:366`）靠「同步阻塞整个流程」才成立——异步后调用方立即返回、守卫随即释放。改为以 state 的 `_active_reviews` 集合 + STATE 的 `reviewer_run` 锚点双判据贯穿评审 run 的整个生命周期。
- **`full_scan` 移出启动主路径**：`start()` 中的同步 `full_scan()` 改为异步执行——首扫仍必须先于主循环（否则 watcher 起来后全量 SPEC 会被判「新出现」并重放 hook 事件，2026-09-07 事故），但执行挪到后台线程，主循环不再等它。事件基线快照（`_update_known_state`）的建立时点必须早于 watcher 启动，此约束 SHALL 保持。

**失败与关闭语义**（异步化必须补齐的两处）：

- worker 内的同步执行异常 → 既有的 `_rollback_failed_dispatch` 收口（与其它 agent_type 同路径），MUST NOT 静默吞掉。
- daemon 关闭排水：评审 run 经 `_run_claude` 注册进 `_running_agents`，`drain_wait` / `running_run_ids` 天然可见，排水语义与其它 run 一致，无需额外改造。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `spec-review-recovery`：评审 run 的执行模型从「调用方线程同步阻塞」改为「派发队列后台线程异步执行」；收口语义（结论机械消费、失败重试与标记、人工恢复入口）全部保持不变。新增「评审不占用实现并发槽位」的调度约束。
- `spec-concurrency-governance`：新增评审任务的在飞判定与同 spec 防重派口径——评审派发以 `_active_reviews` 独立登记，不受 `agents.max_concurrent` 与优先级档位约束。
- `daemon-watcher-startup`（或 `full-scan-resilience`）：`full_scan` 的执行位置从「启动主路径同步」改为「异步后台」，主循环不再阻塞等待首扫完成；基线快照先于 watcher 的既有约束保持不变。

## Impact

- `core/pm_engine/engine.py`：`_on_spec_reviewing`（改投队列）、`_review_dispatches` 单飞守卫（改在飞期语义）
- `core/pm_engine/spec_review.py`：`dispatch_review`（保持四步链，去掉对调用栈的依赖）、`re_review` / 复评派发点（改投队列）、`_handle_review_failure`（重试路径改由队列接力）
- `core/pm_engine/dispatch/queue.py`：`_process_queue` 候选筛选（新增 spec-review 状态闸门、免 `max_concurrent` 与优先级约束）、`_run_agent_worker`（新增 spec-review 分支）、`_active_reviews` 计数与释放
- `fenixd.py`：`start()` 中 `full_scan` 异步化；主循环各 `_check_*` 消费者随之恢复响应（不改代码，是本次修复的直接收益）
- 既有守卫复用：`_should_defer_for_reviewer`（`queue.py:149`）语义不变——它防的是「实现派发撞上在飞评审」，与本次「评审派发不再阻塞」正交
