# 验证报告：fix-spec-review-blocking-dispatch

> ⚠️ 本报告由框架于 2026-09-19T16:04:39Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-19T23:55:00Z

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 25/33 场景通过，8 失败，0 错误（1 个真实产品 Bug）**

| 指标 | 数量 |
| --- | --- |
| 通过 | 25 |
| 失败 | 8 |
| 错误 | 0 |
| 产品 Bug | 1 |
| 本链增量 Token（输入） | N/A |
| 本链增量 Token（输出） | N/A |


## 真实产品 Bug

### BUG-01（severity=blocking）· -

- 根因：engine.py:3506-3517 is_review_in_flight 内部 with self._queue_lock:（engine.py:3456 property 代理到 dispatcher 同一锁实例）；_process_queue 的两个扫描循环（queue.py:381-384 best_valid_prio、queue.py:470-473 dispatch_idx）在 with self._queue_lock:（queue.py:274）内调用 _should_defer_for_reviewer → queue.py:176 调 is_review_in_flight。threading.Lock 非可重入 → 同线程二次 acquire 永久阻塞。由本 SPEC 提交 c064b991 引入（git log -S is_review_in_flight 确认）
- 证据：
  - tests/test_spec_review_async_dispatch.py::TestReviewEntryDoesNotAffectImplScheduling::test_impl_dispatchable_despite_review_in_queue 死锁超时（3 次复现）；最小复现（真实 PMEngine + 单个 reviewer_run 为空的 implementer 条目）faulthandler 堆栈：engine.py:3516 is_review_in_flight → queue.py:176 _should_defer_for_reviewer → queue.py:382 _process_queue


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| rr01 | spec-review-recovery: approved 收口到 ready | pass | 0/1 | - |
| rr02 | spec-review-recovery: repaired 收口到 ready | pass | 0/1 | - |
| rr03 | spec-review-recovery: rejected 收口到 blocked | pass | 0/1 | - |
| rr04 | spec-review-recovery: 不进入实现调度 | pass | 0/1 | - |
| rr05 | spec-review-recovery: 派发入口不阻塞调用线程 | pass | 0/1 | - |
| rr06 | spec-review-recovery: 收口依赖的 attempt 基准不丢失 | pass | 0/1 | - |
| rr07 | spec-review-recovery: worker 内异常走统一回滚 | pass | 0/1 | - |
| rr08 | spec-review-recovery: 续 attempt 不被自身在飞登记否决 | pass | 0/1 | - |
| rr09 | spec-review-recovery: 未完成状态可被恢复通道重新拾取 | pass | 0/1 | - |
| rr10 | spec-review-recovery: 首次失败后重试 | pass | 0/1 | - |
| rr11 | spec-review-recovery: 达上限转 blocked | pass | 0/1 | - |
| rr12 | spec-review-recovery: 故障不被当作放行 | pass | 0/1 | - |
| rr13 | spec-review-recovery: 重试成功后恢复正轨 | pass | 0/1 | - |
| rr14 | spec-review-recovery: 重试不被在飞锚点阻塞 | pass | 0/1 | - |
| rr15 | spec-review-recovery: 评审不挤压实现派发 | fail | 1/1 | - |
| rr16 | spec-review-recovery: 槽位占满时评审条目仍被扫描 | fail | 1/1 | - |
| rr17 | spec-review-recovery: 评审不被实现挤占 | fail | 1/1 | - |
| rr18 | spec-review-recovery: 评审在飞状态可观测 | pass | 0/1 | - |
| rr19 | spec-review-recovery: 评审并发无上限 | pass | 0/1 | - |
| cg01 | spec-concurrency-governance: 已入队未出队时拒绝重复派发 | pass | 0/1 | - |
| cg02 | spec-concurrency-governance: 入队窗口内不被双重派发判断穿透 | fail | 1/1 | - |
| cg03 | spec-concurrency-governance: 已出队未落锚点时不被队列静默跳过 | fail | 1/1 | - |
| cg04 | spec-concurrency-governance: run 已启动时拒绝重复派发 | pass | 0/1 | - |
| cg05 | spec-concurrency-governance: 锚点已写但 run 未注册的窗口被覆盖 | pass | 0/1 | - |
| cg06 | spec-concurrency-governance: 收口后可再次派发 | pass | 0/1 | - |
| cg07 | spec-concurrency-governance: 入队窗口内判为在飞 | pass | 0/1 | - |
| cg08 | spec-concurrency-governance: 陈旧锚点语义收窄 | pass | 0/1 | - |
| cg09 | spec-concurrency-governance: 在飞判据不因调用方前置条件失效 | pass | 0/1 | - |
| dws01 | daemon-watcher-startup: 启动时派发不阻塞 watcher 启动 | pass | 0/1 | - |
| dws02 | daemon-watcher-startup: 启动期恢复不阻塞主循环 | fail | 1/1 | - |
| dws03 | daemon-watcher-startup: 启动期文件信号消费者可用 | fail | 1/1 | - |
| dws04 | daemon-watcher-startup: 运行期事件处理不被 Agent 阻塞 | fail | 1/1 | - |
| dws05 | daemon-watcher-startup: 基线快照仍先于 watcher 扫描 | pass | 0/1 | - |
