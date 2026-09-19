## Deliverables

```yaml
- path: core/pm_engine/spec_review.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: core/pm_engine/dispatch/queue.py
  kind: modify
- path: core/agent_runner/liveness.py
  kind: modify
- path: tests/test_spec_concurrency_guard.py
  kind: new
```

> `core/agent_runner/liveness.py` 为交付物：`_stream_recent` 只扫 `impl-`/`verify-`
> 前缀（liveness.py:403），`spec-review-`/`repair-` run 判不出在飞——D0 判据 3 需在此扩展
> 前缀集合（或新增等口径入口）。修改该文件后 MUST 复跑 `test_agent_runner*.py` 与
> event_bus 孤儿恢复用例（进程表/流判据语义单源，不得漂移）。

## 0. 判定口径（共享，先落地）

- [x] 0.1 在 `core/agent_runner/liveness.py` 扩展在飞判定前缀覆盖 `spec-review-`/`repair-`
      （或新增等口径入口），与 `_stream_recent` 保持同口径（新鲜 + 末行非终态）
- [x] 0.2 实现共享判定「在飞评审 run」：`reviewer_run` 非空 + 进程表（`running_run_ids()`）
      /流文件分层判定；陈旧锚点（run 已终态）MUST 判为**无在飞评审**并记 WARNING（fail-open，
      防自造死锁）
- [x] 0.3 跳过/顺延路径 MUST NOT 写 `error` 字段（防事件总线自触发反馈环，对齐 engine.py:552-556）；
      审计留痕一律用 `_` 前缀侧车字段（state_machine.py:424 约定）

## 1. 审核收尾回退守卫

- [x] 1.1 `core/pm_engine/spec_review.py:285`（`consume_review_result` 的
      approved/repaired 分支最前，且在结果硬门/边界校验/白名单之后）：重读 spec 当前 status；
      属 implementing/implemented/testing → 不回退，仅 INFO 日志「评审收尾遇在飞实现 run，跳过回退」
- [x] 1.2 跳过分支 MUST 清 `reviewer_run`（+ 复位 `_review_attempts`）、写 `_review_skipped_result`
      审计侧车，并 `return True` 于 `:300` 的 `_on_spec_ready` 调用**之前**（MUST NOT 调用它）
- [x] 1.3 幂等：当前 status 非三类时走既有回退路径（`transition → ready` + 既有 `update_spec`，行为不变）
- [x] 1.4 属性名按本类实际字段 `self.state_machine`（spec_review.py:76）书写；`self._pm` 在本类不存在

## 2. 派发前在飞评审校验（两处同口径）

- [x] 2.1 `core/pm_engine/engine.py:529 _on_spec_ready`：在 `_enqueue`（:628）之前插入 D0 判定；
      命中 → 顺延（不写 STATE/error，INFO 日志附 run_id），且不更新 `_last_dispatch_at`
- [x] 2.2 `core/pm_engine/dispatch/queue.py:209` 与 `:293` 的 `atype in ("implementer","fast-track")`
      分支：同样跳过（`continue`，条目保留不 pop）；覆盖 `family.py:585`/`adjudication.py:1408`/
      `queue.py:870` 等绕过 `_on_spec_ready` 的直入队列路径
- [x] 2.3 重触发保证复核（MUST 保持接线）：评审收尾 `spec_review.py:300` 的
      `_on_spec_ready` 调用为唯一权威推进点；兜底为 event_bus 孤儿 ready 扫描（event_bus.py:427）
      与 `check_scheduling_deadlines`（engine.py:666）；MUST NOT 依赖新增定时器
- [x] 2.4 顺序：判定置于冷却/单飞/worktree 锁/退避/`start_after_pending`/依赖校验之后、`_enqueue` 之前

## 3. 合并收尾 ready 态兜底（三条实现合并路径）

- [x] 3.1 `core/pm_engine/dispatch/queue.py:1199`（implementer 主路径）、
      `repair_lane.py:342`（repair re-merge）、`fast_track.py:583`（fast-track）三处：
      既有 `transition(..., "implemented")` 之前，若 `status == "ready"` → 先
      `transition(spec_name, "implementing", ...)` 补记合法链，再推进 implemented
- [x] 3.2 次级校验：`result.branch` 属本 spec 的 `fenix/` 分支且非 `fenix/verify-` 前缀
      （worktree_manager/lifecycle.py:396-399 同款判定）；判据以「调用点即实现合并收尾」为主，
      MUST NOT 以分支名字面匹配单独充当判据（STATE.implementer_run 是 run-id，非分支名）
- [x] 3.3 兜底 MUST 留 WARNING 日志 + 项目日志审计留痕；MUST NOT 静默吞异常
- [x] 3.4 兜底限定：非实现合并（文档/管理操作）不触发；ready→implemented 直接推进一律禁止
      （保持转移表白名单语义）；兜底后既有收尾（update_spec / enqueue verifier / 任务回写）不变

## 4. 测试

- [x] 4.1 tests/test_spec_concurrency_guard.py：回退守卫（implementing 时不回退、清锚点、
      审计侧车、不调 `_on_spec_ready`）；派发顺延（engine + queue 两落点各一用例）；
      ready 兜底（三落点各一用例、无 Invalid transition ERROR、有 WARNING 留痕）
- [x] 4.2 防死锁回归：陈旧锚点（run 已终态）MUST 放行不误拦；非 `fenix/` 分支不触发兜底
- [ ] 4.3 回归：`test_spec_review_agent.py` / `test_spec_review_gate.py` /
      `test_review_circuit_breaker.py` / `test_state_machine.py` / `test_agent_runner*.py` /
      dispatch 相关套件全绿；`liveness.py` 改动后孤儿恢复用例（event_bus）全绿
