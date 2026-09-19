# Tasks: fix-spec-review-blocking-dispatch

## Deliverables

```yaml
- path: core/pm_engine/dispatch/queue.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: core/pm_engine/spec_review.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: core/agent_runner/liveness.py
  kind: modify
- path: core/event_bus.py
  kind: modify
- path: tests/test_spec_review_async_dispatch.py
  kind: new
- path: tests/test_startup_full_scan_async.py
  kind: new
```

## 1. 派发队列：评审条目支持

- [x] 1.1 在 `DispatchQueue` 新增 `_active_reviews: set`（评审在飞集合，spec 名），与 `_active_runs` / `_active_priorities` 同锁保护；在 `QQQueueMixin.__init__`（`core/pm_engine/dispatch/queue.py:27`）初始化，并在 `PMEngine` 门面的既有 property 透传族（`core/pm_engine/engine.py:3446-3476` 一带）补 `_active_reviews` 的 property/setter/deleter——测试与调用方多以属性路径访问队列态，缺该透传即 AttributeError
- [x] 1.2 提取评审条目合法性判定为独立方法（参照 `_should_defer_for_reviewer` 范式），供 `_process_queue` 的 `best_valid_prio` 扫描与 `dispatch_idx` 扫描两处共用，避免守卫漂移
- [x] 1.3 `_process_queue` 的 `best_valid_prio` 扫描接入评审判定：`agent_type == "spec-review"` 时状态必须为 `reviewing`，且该 spec 无在飞评审（`reviewer_run` 为空）——**判据 MUST 取 `reviewer_in_flight` 的在飞结论（`in_flight == True`）而非「锚点非空即拒」**，否则本 SPEC 新增的「锚点写入在 dispatch_review 内、异常后不再清除」路径（见 design D4 重入安全性）会使该条目被永久静默跳过
- [x] 1.4 `_process_queue` 的 `dispatch_idx` 扫描以同口径接入同一判定（与 1.3 共用 1.2 的方法）
- [x] 1.5 出队后按 `agent_type` 分流并发计数：`spec-review` 条目 MUST NOT 执行 `_active_runs += 1`、MUST NOT 写 `_active_priority_counts` / `_active_priorities`，改为 `_active_reviews.add(spec_name)`；释放时点 MUST NOT 晚于四步链的锚点落盘（见 design D4 重入安全性：worker 内续 attempt 会在 `dispatch_review` 入口重判在飞，集合留着会自我否决）
- [x] 1.5b `_process_queue` 的槽位早退闸门（`core/pm_engine/dispatch/queue.py:233` 的 `if self._active_runs >= max_concurrent: return`）MUST 在「队列中存在状态合法的评审条目」时放行扫描，且该放行 MUST NOT 顺带放行同轮的实现/verifier 条目（design D2 槽位闸门第二处）
- [x] 1.6 出队后的状态推进分支新增 `spec-review`：不调用 `transition`（状态已由晋升链置为 `reviewing`），仅记录派发日志
- [x] 1.7 出队后的同步闸门分支（同源草案收敛检查、守卫三、预算闸门、内容完整性闸门）确认对 `spec-review` 不误伤：`spec-review` MUST 跳过 `_check_impl_budget_exhausted` 与 `_check_spec_content_missing`（评审不消耗实现预算）
- [x] 1.8 `_run_agent_worker` 新增 `agent_type == "spec-review"` 分支：构造 `SpecReviewManager` 并调 `dispatch_review`。异常收口 MUST 区分两层（`_rollback_failed_dispatch` 当前只处理 verifier/implementer/fast-track，`core/pm_engine/dispatch/rollback.py:72-146`）：四步链内部异常已由 `dispatch_review` 自吞并走 `_handle_review_failure`（保持既有语义）；四步链之外的异常 MUST 由本分支显式收口——清 `reviewer_run`、保持 `reviewing`、重新入队（或为 `_rollback_failed_dispatch` 补 `spec-review` 分支），MUST NOT 只记日志了事
- [x] 1.9 `_run_agent_worker` 的 `finally` 按 `agent_type` 分流释放：`spec-review` 释放 `_active_reviews.discard(spec_name)`，MUST NOT 触碰 `_active_runs` / `_active_priorities`
- [x] 1.10 出队后所有滚动回滚点（同源草案收敛拦截、预算闸门、内容闸门、守卫三）确认评审条目的回滚路径同样只回滚 `_active_reviews`，不误减 `_active_runs`
- [x] 1.11 评审条目入队后 MUST 有立即可用的队列处理触发：`_enqueue` 只写队列不派发（`core/pm_engine/dispatch/queue.py:61`），而四个触发通道中 `_watch_loop` 自己调 `_process_queue`、MainThread 经 `handle_event` 尾部的 `_process_queue`（`core/pm_engine/engine.py:432`）触发。故 `_on_spec_reviewing`（及其复评/重试入口）SHOULD 在 `_enqueue` 后补一次 `_process_queue()`，保证「晋升即评审」不被 30 分钟周期扫描兜底（见 tasks 5.11 的同步放行断言）

## 2. 评审派发改造为入队

- [x] 2.1 `core/pm_engine/engine.py` 的 `_on_spec_reviewing`：把 `review_manager.dispatch_review(spec_name)` 改为 `self._enqueue(spec_name, "spec-review")`；保留熔断短路、start_after 早退、在飞锚点早退三段前置判定
- [x] 2.2 `_on_spec_reviewing` 的单飞守卫改为双判据：`spec_name in self._active_reviews`（经 `DispatchQueue` 暴露的只读查询方法）或 STATE 的 `reviewer_run` 非空 → 跳过；移除对 `_review_dispatches` 的依赖
- [x] 2.3 `core/pm_engine/spec_review.py` 的 `dispatch_review` 保持四步链结构不变（锚点落盘 → 快照 → 执行 → 收口），确认调用方线程已由队列提供，MUST NOT 再被 `_on_spec_reviewing` 直接调用
- [x] 2.4 `dispatch_review` 入口在飞守卫改口径：`spec_name` 在 `_active_reviews` 中时拒绝（覆盖「条目已出队、锚点尚未落盘」的窗口）；锚点非空时 MUST 先调 `agent_runner.reviewer_in_flight` 取在飞结论——`in_flight == True` 拒派，仅 `reason == "stale"` 才清锚点后继续（MUST NOT 按「锚点非空」直接自清：`_should_defer_for_reviewer` 的判定异常分支为 fail-open `(False, None)`，直接自清会在评审仍在跑时放行并发派发）。重入保护：同一 worker 线程内的续 attempt 会在锚点落盘后重新进入本入口，此时 `_active_reviews` 必须已释放（见 1.5 与 design D4 重入安全性）
- [x] 2.5 `spec_review.py` 的 content 类失败重试路径（`_handle_review_failure`）：清除 `reviewer_run` 后改为 `self.pm_engine._enqueue(spec_name, "spec-review")` 重新入队，MUST NOT 递归调用 `dispatch_review`
- [x] 2.6 `spec_review.py` 的 rejected 后自动复评路径（`consume_review_result` 内 `self.dispatch_review(spec_name)` 调用点）：改为 `self.pm_engine._enqueue(spec_name, "spec-review")`，保留 `agent_runner is None` 的 CLI 跳过分支
- [x] 2.7 `spec_review.py` 的 `re_review` 派发点：同上改为入队，保留 `agent_runner is None` 的 CLI 跳过分支

## 3. 在飞判据补齐入队窗口

- [x] 3.1 `core/agent_runner/liveness.py` 的 `reviewer_in_flight`：在既有分层判据（进程表 → 流文件 → 陈旧锚点）之前新增前置判据——`spec_name` 出现在 `_active_reviews` 即返回 `(True, "queued")`
- [x] 3.2 `reviewer_in_flight` 的 `reason` 取值文档更新：新增 `"queued"` 取值与语义说明；确认 `"stale"` 语义收窄为「确无在飞评审」
- [x] 3.3 确认 `_should_defer_for_reviewer`（`queue.py:148`）对新增 `"queued"` 取值的处理：`in_flight=True` 走顺延分支，不需要额外改动（写一条测试断言 3.3）
- [x] 3.4 `_should_defer_for_reviewer` 的调用条件 MUST 放宽：其前置 `if reviewer_run:`（`core/pm_engine/dispatch/queue.py:164`）使「锚点尚未落盘、但评审条目已在 `_active_reviews`」的窗口完全绕过在飞判定——正是 3.1 要补的窗口。判据 MUST 改为「`reviewer_run` 非空 **或** 该 spec 在 `_active_reviews` 中」，两处落点（`queue.py:313` / `queue.py:395`）同口径
- [x] 3.5 `engine._on_spec_ready` 的在飞校验同样受 `reviewer_run` 非空前置约束（`core/pm_engine/engine.py:721`），MUST 同口径放宽为「`reviewer_run` 非空 或 `_active_reviews` 命中」——否则实现派发可在评审已入队、锚点未落盘的窗口穿透（与 `spec-concurrency-governance` Requirement 2 的「顺延」语义冲突）
- [x] 3.6 `_should_defer_for_reviewer` 对「`reviewer_run` 为空但 `_active_reviews` 命中」须能取到在飞结论：`reviewer_in_flight(spec_name, reviewer_run)` 的现有签名在锚点为空时**立即返回 `(False, None)`**（`core/agent_runner/liveness.py:471`），MUST 让该前置判据优先于空锚点短路，或改为不依赖锚点的独立查询入口；MUST NOT 保留「空锚点即 `(False, None)`」的顺序使前置判据永远不可达
- [x] 3.7 `_active_reviews` 由 `DispatchQueue` 持有、`reviewer_in_flight` 属 `AgentRunner`/`LivenessSupervisor`，两者无现成引用链（`agent_runner` 不持 `pm_engine`，`fenixd.py:285`）。MUST 显式约定查询通路——推荐在 PMEngine 门面暴露只读方法（仿 `is_review_in_flight(spec_name)`），由 `reviewer_in_flight` 经注入/回引取用；MUST NOT 留待实现者即兴新增跨层引用

## 4. 启动期 full_scan 异步化

- [x] 4.1 `core/event_bus.py` 的 `full_scan` 拆分：提取 `_snapshot_baseline()`（仅 `_update_known_state`，同步、毫秒级）与扫描主体两段。**兼容契约（MUST）**：`full_scan()` 保留为「两段顺序执行」的同步入口，`_periodic_scan_loop`（`core/event_bus.py:645`）继续整调用同步版；`start()` MUST NOT 调用异步版（否则后台扫描被同步等待吞掉，本次修复静默失效）。注意 `event_bus.start()` 本身已同步调用 `_update_known_state()`（`core/event_bus.py:51`），`_snapshot_baseline()` 属显式化该不变量的冗余加固，不是唯一保障
- [x] 4.2 `fenixd.py` 的 `start()`：在 `self.event_bus.start()` 之后同步调用 `_snapshot_baseline()`，再把扫描主体提交到后台线程；MUST NOT 让 `start()` 等待扫描主体完成
- [x] 4.3 `start()` 中后台扫描线程的命名与 `daemon=True` 标记对齐既有线程风格（`fenixd-watcher` / `fenixd-scanner` 同族），异常捕获记日志不中断主循环；线程句柄 MUST 由 `EventBus` 持有，`stop()`（`core/event_bus.py:73`）的收口语义须覆盖它
- [x] 4.4 确认 `start()` 的日志顺序：基线快照完成后即打印 `Entering main loop`，MUST NOT 等待扫描完成的日志
- [x] 4.5 `event_bus` 的 `_periodic_scan_loop` 仍调用同步版 `full_scan`（周期扫描在独立线程内，无须二次异步），确认无回归

## 5. 测试

- [x] 5.1 新增 `tests/test_spec_review_async_dispatch.py`：断言 `_on_spec_reviewing` 调用后立即返回且队列中出现 `spec-review` 条目（用替身 `agent_runner` 避免真跑 agent）
- [x] 5.2 同文件：断言评审条目出队后 `_active_runs` 与 `_active_priorities` 均未变化、`_active_reviews` 含该 spec
- [x] 5.3 同文件：断言 `_run_agent_worker` 的 `finally` 释放 `_active_reviews`（含异常路径）
- [x] 5.4 同文件：断言双判据单飞——`_active_reviews` 命中时拒绝派发、`reviewer_run` 非空时拒绝派发、两者皆空时放行
- [x] 5.5 同文件：断言 content 类失败重试经队列重新入队（且入队前 `reviewer_run` 已清空，条目可被候选筛选放行）
- [x] 5.6 同文件：断言 `reviewer_in_flight` 对 `_active_reviews` 命中返回 `(True, "queued")`
- [x] 5.7 同文件：断言评审条目存在时，实现条目的可派发性判定不受影响（`min(active_priorities)` 不含评审档）
- [x] 5.8 新增 `tests/test_startup_full_scan_async.py`：断言 `start()` 在扫描主体未完成时已进入主循环（用替身事件总线阻塞扫描主体，断言主循环 tick 日志先于扫描完成）
- [x] 5.9 同文件：断言基线快照 `_known_specs` 在扫描主体启动前已建立（存量 SPEC 不被判「新出现」）
- [x] 5.10 回归确认：既有 `tests/test_spec_review_gate.py` / `tests/test_spec_review_agent.py` / `tests/test_spec_review_artifact_gate.py` / `tests/test_start_after_gate.py` / `tests/test_review_circuit_breaker.py` / `tests/test_spec_concurrency_guard.py` 全部通过（若有断言依赖「同步阻塞」语义，按新异步语义就地修正并在任务备注中说明）。**已知需就地修正的两族**：(a) 以真 `PMEngine` + `patch("core.pm_engine.spec_review.SpecReviewManager")` 断言 `dispatch_review` 被调用的用例（如 `tests/test_start_after_gate.py:203-214` 一带）——改造后断言对象改为「队列出现 `spec-review` 条目」；(b) 直接以 `SpecReviewManager` 同步驱动 test 的用例，其 `pm_engine` 多为 `MagicMock()`（`tests/test_spec_review_gate.py:233`、`tests/test_spec_review_artifact_gate.py:288`），改为入队后 `self.pm_engine._enqueue` 变成 MagicMock 记录，断言须同步调整
- [x] 5.11 断言放行即时性：`_on_spec_reviewing` 返回后（不依赖任何周期扫描/兜底计时器）评审条目即已出队且 `_active_reviews` 命中该 spec——钉死 tasks 1.11 的 `_process_queue` 触发约定；若实现改为「只入队不触发」，本用例会红

## 6. 收尾

- [ ] 6.1 全量跑 `tests/` 确认无回归
- [ ] 6.2 在 `core/pm_engine/dispatch/queue.py` 与 `core/pm_engine/engine.py` 的改动处补齐注释，说明「评审不占实现槽位」「双判据单飞」的设计理由（对齐仓内既有的长注释风格）
- [ ] 6.3 更新 `core/agent_runner/liveness.py` 模块文档中 `reviewer_in_flight` 的分层判据说明，纳入 `_active_reviews` 前置判据
