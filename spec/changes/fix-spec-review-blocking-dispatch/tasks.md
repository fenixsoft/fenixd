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

- [ ] 1.1 在 `DispatchQueue` 新增 `_active_reviews: set`（评审在飞集合，spec 名），与 `_active_runs` / `_active_priorities` 同锁保护；在 `__init__` 初始化并在重入/重置路径保持一致
- [ ] 1.2 提取评审条目合法性判定为独立方法（参照 `_should_defer_for_reviewer` 范式），供 `_process_queue` 的 `best_valid_prio` 扫描与 `dispatch_idx` 扫描两处共用，避免守卫漂移
- [ ] 1.3 `_process_queue` 的 `best_valid_prio` 扫描接入评审判定：`agent_type == "spec-review"` 时状态必须为 `reviewing`，且 `reviewer_run` 为空（锚点已落盘说明已被另一条通道接走），否则 `continue`
- [ ] 1.4 `_process_queue` 的 `dispatch_idx` 扫描以同口径接入同一判定（与 1.3 共用 1.2 的方法）
- [ ] 1.5 出队后按 `agent_type` 分流并发计数：`spec-review` 条目 MUST NOT 执行 `_active_runs += 1`、MUST NOT 写 `_active_priority_counts` / `_active_priorities`，改为 `_active_reviews.add(spec_name)`
- [ ] 1.6 出队后的状态推进分支新增 `spec-review`：不调用 `transition`（状态已由晋升链置为 `reviewing`），仅记录派发日志
- [ ] 1.7 出队后的同步闸门分支（同源草案收敛检查、守卫三、预算闸门、内容完整性闸门）确认对 `spec-review` 不误伤：`spec-review` MUST 跳过 `_check_impl_budget_exhausted` 与 `_check_spec_content_missing`（评审不消耗实现预算）
- [ ] 1.8 `_run_agent_worker` 新增 `agent_type == "spec-review"` 分支：构造 `SpecReviewManager` 并调 `dispatch_review`，捕获异常并交由 `_rollback_failed_dispatch` 收口
- [ ] 1.9 `_run_agent_worker` 的 `finally` 按 `agent_type` 分流释放：`spec-review` 释放 `_active_reviews.discard(spec_name)`，MUST NOT 触碰 `_active_runs` / `_active_priorities`
- [ ] 1.10 出队后所有滚动回滚点（同源草案收敛拦截、预算闸门、内容闸门、守卫三）确认评审条目的回滚路径同样只回滚 `_active_reviews`，不误减 `_active_runs`

## 2. 评审派发改造为入队

- [ ] 2.1 `core/pm_engine/engine.py` 的 `_on_spec_reviewing`：把 `review_manager.dispatch_review(spec_name)` 改为 `self._enqueue(spec_name, "spec-review")`；保留熔断短路、start_after 早退、在飞锚点早退三段前置判定
- [ ] 2.2 `_on_spec_reviewing` 的单飞守卫改为双判据：`spec_name in self._active_reviews`（经 `DispatchQueue` 暴露的只读查询方法）或 STATE 的 `reviewer_run` 非空 → 跳过；移除对 `_review_dispatches` 的依赖
- [ ] 2.3 `core/pm_engine/spec_review.py` 的 `dispatch_review` 保持四步链结构不变（锚点落盘 → 快照 → 执行 → 收口），确认调用方线程已由队列提供，MUST NOT 再被 `_on_spec_reviewing` 直接调用
- [ ] 2.4 `dispatch_review` 入口新增在飞守卫：`spec_name in _active_reviews` 时拒绝（覆盖「条目已出队、run 正在构造」的窗口），与既有 `reviewer_run` 非空拒派构成双判据
- [ ] 2.5 `spec_review.py` 的 content 类失败重试路径（`_handle_review_failure`）：清除 `reviewer_run` 后改为 `self.pm_engine._enqueue(spec_name, "spec-review")` 重新入队，MUST NOT 递归调用 `dispatch_review`
- [ ] 2.6 `spec_review.py` 的 rejected 后自动复评路径（`consume_review_result` 内 `self.dispatch_review(spec_name)` 调用点）：改为 `self.pm_engine._enqueue(spec_name, "spec-review")`，保留 `agent_runner is None` 的 CLI 跳过分支
- [ ] 2.7 `spec_review.py` 的 `re_review` 派发点：同上改为入队，保留 `agent_runner is None` 的 CLI 跳过分支

## 3. 在飞判据补齐入队窗口

- [ ] 3.1 `core/agent_runner/liveness.py` 的 `reviewer_in_flight`：在既有分层判据（进程表 → 流文件 → 陈旧锚点）之前新增前置判据——`spec_name` 出现在 `_active_reviews` 即返回 `(True, "queued")`
- [ ] 3.2 `reviewer_in_flight` 的 `reason` 取值文档更新：新增 `"queued"` 取值与语义说明；确认 `"stale"` 语义收窄为「确无在飞评审」
- [ ] 3.3 确认 `_should_defer_for_reviewer`（`queue.py`）对新增 `"queued"` 取值的处理：`in_flight=True` 走顺延分支，不需要额外改动（写一条测试断言）

## 4. 启动期 full_scan 异步化

- [ ] 4.1 `core/event_bus.py` 的 `full_scan` 拆分：提取 `_snapshot_baseline()`（仅 `_update_known_state`，同步、毫秒级）与扫描主体两段，`full_scan` 保留为「两段顺序执行」的兼容入口（不得改变既有调用方的同步语义）
- [ ] 4.2 `fenixd.py` 的 `start()`：在 `self.event_bus.start()` 之后同步调用 `_snapshot_baseline()`，再把扫描主体提交到后台线程；MUST NOT 让 `start()` 等待扫描主体完成
- [ ] 4.3 `start()` 中后台扫描线程的命名与 `daemon=True` 标记对齐既有线程风格（`fenixd-watcher` / `fenixd-scanner` 同族），异常捕获记日志不中断主循环
- [ ] 4.4 确认 `start()` 的日志顺序：基线快照完成后即打印 `Entering main loop`，MUST NOT 等待扫描完成的日志
- [ ] 4.5 `event_bus` 的 `_periodic_scan_loop` 仍调用同步版 `full_scan`（周期扫描在独立线程内，无须二次异步），确认无回归

## 5. 测试

- [ ] 5.1 新增 `tests/test_spec_review_async_dispatch.py`：断言 `_on_spec_reviewing` 调用后立即返回且队列中出现 `spec-review` 条目（用替身 `agent_runner` 避免真跑 agent）
- [ ] 5.2 同文件：断言评审条目出队后 `_active_runs` 与 `_active_priorities` 均未变化、`_active_reviews` 含该 spec
- [ ] 5.3 同文件：断言 `_run_agent_worker` 的 `finally` 释放 `_active_reviews`（含异常路径）
- [ ] 5.4 同文件：断言双判据单飞——`_active_reviews` 命中时拒绝派发、`reviewer_run` 非空时拒绝派发、两者皆空时放行
- [ ] 5.5 同文件：断言 content 类失败重试经队列重新入队（且入队前 `reviewer_run` 已清空，条目可被候选筛选放行）
- [ ] 5.6 同文件：断言 `reviewer_in_flight` 对 `_active_reviews` 命中返回 `(True, "queued")`
- [ ] 5.7 同文件：断言评审条目存在时，实现条目的可派发性判定不受影响（`min(active_priorities)` 不含评审档）
- [ ] 5.8 新增 `tests/test_startup_full_scan_async.py`：断言 `start()` 在扫描主体未完成时已进入主循环（用替身事件总线阻塞扫描主体，断言主循环 tick 日志先于扫描完成）
- [ ] 5.9 同文件：断言基线快照 `_known_specs` 在扫描主体启动前已建立（存量 SPEC 不被判「新出现」）
- [ ] 5.10 回归确认：既有 `tests/test_spec_review_gate.py` / `tests/test_spec_review_agent.py` / `tests/test_spec_review_artifact_gate.py` / `tests/test_start_after_gate.py` / `tests/test_review_circuit_breaker.py` 全部通过（若有断言依赖「同步阻塞」语义，按新异步语义就地修正并在任务备注中说明）

## 6. 收尾

- [ ] 6.1 全量跑 `tests/` 确认无回归
- [ ] 6.2 在 `core/pm_engine/dispatch/queue.py` 与 `core/pm_engine/engine.py` 的改动处补齐注释，说明「评审不占实现槽位」「双判据单飞」的设计理由（对齐仓内既有的长注释风格）
- [ ] 6.3 更新 `core/agent_runner/liveness.py` 模块文档中 `reviewer_in_flight` 的分层判据说明，纳入 `_active_reviews` 前置判据
