# Design: spec-concurrency-flight-guard

## D0: 判定口径总则（三处守卫共用）

「在飞评审 run」= `STATE.reviewer_run` 非空 **且** 该 run 尚在飞。判据分层（进程表为真相，
流文件兜底，陈旧锚点 fail-open）：

1. `entry.reviewer_run` 为空 → 无在飞评审（`reviewer_run` 在 run 启动前落盘，见
   `core/pm_engine/spec_review.py:150-152`，故非空 ⟺ 在飞或结果待消费）。
2. `agent_runner.running_run_ids()`（`core/agent_runner/runner.py:4328`，进程表为真相，
   评审 run 经 `_run_claude` 在 `runner.py:3380` 注册）含 `reviewer_run` → 在飞。
3. 否则看该 run 流文件是否「新鲜且末行非终态」（与
   `core/agent_runner/liveness.py:384 _stream_recent` 同口径）。
   ⚠️ **既有 `_stream_recent` 只扫 `impl-`/`verify-` 前缀**（`liveness.py:403`），
   `spec-review-` / `repair-` run 一律判不出在飞——本 SPEC 的判定 MUST 覆盖这两类前缀
   （扩展该处或另写等口径判定，二者择一但 MUST NOT 依赖扩展后的行为以外的第二套漂移实现）。
4. 2、3 皆否 → **陈旧锚点**（run 已终态但结果未消费/历史残留）：MUST NOT 顺延派发，
   按「无在飞评审」放行并记 WARNING，交由既有恢复路径清理锚点。
5. 判定过程异常 → fail-open 放行（不新增死锁面；对齐 `engine.py:470-478` 既有门控容错）。

兜底：顺延/跳过路径 MUST NOT 写 `error` 字段（写 error 会经事件总线自触发 `spec_ready`，
形成反馈环——`engine.py:552-556` 已有同款约束）；审计留痕一律用 `_` 前缀侧车字段
（`state_machine.py:424` 约定 `_` 前缀字段随 STATE 往返持久化）。

## D1: 审核收尾回退守卫（spec_review.py）

落点：`core/pm_engine/spec_review.py:285`，即 `consume_review_result` 内
`if status in ("approved", "repaired"):` 分支的**最前面**——MUST 位于结果硬门
（:253）、结果文件读取（:265）、写入边界校验（:276）、status 白名单（:281）**之后**，
既有 `transition(..., "ready")`（:285）之前。

```python
# consume_review_result 内，approved/repaired 分支最前
IN_FLIGHT_STATES = ("implementing", "implemented", "testing")
current = self.state_machine.read_one(spec_name) or {}   # 注意：本类属性名为 state_machine（:76），非 _pm
cur = current.get("status")
if cur in IN_FLIGHT_STATES:
    self.logger.info(
        "spec_review",
        f"评审收尾遇在飞实现 run（status={cur}），跳过回退: {spec_name}",
    )
    # 清锚点（否则 reviewer_run 永久残留，与 D2 判定合流后阻塞后续派发）
    self.state_machine.update_spec(spec_name, {
        "reviewer_run": None,
        "_review_attempts": 0,
        # 审计侧车：本轮评审结论未被消费（不写 error，见 D0 兜底）
        "_review_skipped_result": f"{status}@result-path={result_path}",
    })
    return True   # ⚠️ 此处 return 早于 :300 的 self.pm_engine._on_spec_ready(...)
# 否则维持既有回退（implementing→ready / reviewing→ready）与既有 update_spec（:291-298）
```

约束：

- **MUST NOT 调用 `self.pm_engine._on_spec_ready(spec_name)`**：此刻 status 已是
  implementing/implemented/testing，无待派发实现 run；且 :300 的调用被本分支跳过是
  有意的（若调用，将被 D2 判定为在飞评审而顺延，语义重复）。
- **MUST 清 `reviewer_run`**：`_on_spec_ready` 的 D2 判定以 `reviewer_run` 非空为第一
  判据，残留锚点 + 后续 merge 失败回退 ready 会让派发永久顺延（本 SPEC 自造死锁）。
- 幂等：`cur` 非三类状态时走既有回退路径，行为逐字不变。
- 日志级别 INFO（不是 ERROR）；`_review_skipped_result` 供 dashboard/人工审计，不参与门控。
- 陈旧锚点 WARNING 由 D0 第 4 条给出，本分支不重复判存活（避免两处判定漂移）。

## D2: 派发前在飞评审校验（engine.py + dispatch/queue.py，两处必须同口径）

覆盖面 **MUST 为两处**（与 `start_after_pending` 同款双落点，权威依据见
`core/pm_engine/engine.py:598-608` 的「派发入口全覆盖核对结论」，以及
`spec/changes/fix-start-after-premature-pickup/specs/*/spec.md` 的
「门控 MUST 包含以下全部入口，MUST NOT 只覆盖 ready 派发口」）：

1. `core/pm_engine/engine.py:529 _on_spec_ready`：在依赖校验（:620 附近）之后、
   `self._enqueue(spec_name, agent_type)`（:628）之前插入 D0 判定；
   命中 → `return`（不写 STATE、不写 error），日志
   `INFO "在飞评审 run，派发顺延: {spec_name} run={reviewer_run}"`，并**保留**
   `_last_dispatch_at` 不更新（顺延不计冷却起点）。
2. `core/pm_engine/dispatch/queue.py:209`（`best_valid_prio` 候选筛选）与 `:293`
   （实际派发筛选）的 `atype in ("implementer", "fast-track")` 分支：命中 D0 判定 →
   `continue`（条目**保留在队列**，不 pop、不消耗 attempt），日志同上。
   理由：`family.py:585`、`adjudication.py:1408`、`queue.py:870` 等直入队列路径
   绕过 `_on_spec_ready`；只补 ① 会留下与本次事故同型的旁路（fix-start-after-premature-pickup
   的 5.2 登记已实证「绕过通道会让门控失效」）。

**重触发保证（MUST 明文保留，实现时不得破坏）**：评审收尾的既有出口
`spec_review.py:300 self.pm_engine._on_spec_ready(spec_name)` 覆盖 approved/repaired
收口（含 D1 未跳过的正常分支）与 `responsible_release`（:881）；rejected 分支回 reviewing
不产生待派发实现 run。故顺延条目必然被「评审收尾 → `_on_spec_ready`」重判一次。
兜底通道：`event_bus` 的孤儿 ready 短周期扫描（`core/event_bus.py:427`）与
`check_scheduling_deadlines`（`engine.py:666`）。**MUST NOT** 依赖新增定时器。

顺延与既有守卫的相对顺序：置于冷却窗（:538）、派发单飞（:549）、
`has_active_worktree`/`has_live_attempt`（:565-583）、退避（:588）、`start_after_pending`
（:609）、依赖校验之后，`_enqueue` 之前——避免在无谓路径上做进程表判定。

## D3: 合并收尾 ready 态兜底（三条实现合并收尾路径）

**判据 MUST 取「调用点即证据」**：兜底只由**实现 run 合并收尾**的三条路径调用，
MUST NOT 以分支名字面匹配单独充当判据（`STATE.implementer_run` 是 run-id 如
`impl-<spec>-<ts>-a1`，不是分支名；分支锚点是 `STATE.branch`）。三条落点：

| 路径 | 落点 | agent |
| --- | --- | --- |
| implementer 主路径 | `core/pm_engine/dispatch/queue.py:1199-1204` | implementer |
| repair 链 re-merge | `core/pm_engine/dispatch/repair_lane.py:342-347` | repair |
| fast-track 单 run | `core/pm_engine/dispatch/fast_track.py:583-588` | fast-track |

```python
# 既有 transition(spec_name, "implemented", ...) 之前
current = self._pm.state_machine.read_one(spec_name) or {}
if current.get("status") == "ready":
    # 竞态回退兜底：先补记合法链 ready→implementing，再推进 implemented
    self._pm.state_machine.transition(
        spec_name, "implementing",
        trigger_run_id=<本路径既有 run_id>, agent_type=<本路径既有 agent_type>,
        channel="auto",
    )
    self._pm.logger.warning(
        "pm_engine",
        f"ready 态合并兜底：补记 implementing（评审收尾竞态回退残留）"
        f"'{spec_name}' run=<run_id> branch=<branch>",
    )
    # MUST 追加项目日志/事件（可审计），MUST NOT 静默吞掉异常
self._pm.state_machine.transition(spec_name, "implemented", ...)  # 既有调用不变
```

约束：

- 次级校验（防御性，不是唯一判据）：`result.branch` 属本 spec 的 `fenix/` 分支且
  **非** `fenix/verify-` 前缀（`core/worktree_manager/lifecycle.py:396-399` 同款判定）；
  不满足 → 不兜底，维持既有转移（ready→implemented 仍被拒 = 真实异常暴露）。
- **MUST NOT** 由文档/管理操作合并（archive、人工 merge-back 通道）触发。
- 兜底 MUST 留审计痕迹（WARNING 日志 + 项目日志），**MUST NOT** 把异常彻底静音：
  本兜底是对「评审收尾竞态回退」的补偿，不是对非法转移的通用放行。
- 补偿后 `implemented` 的既有收尾（`update_spec(implementer_run/branch/...)`、
  `_enqueue_front(verifier)`、`_sync_task_progress`）保持原样；`transition` 产生的
  中间 `implementing` 是瞬时态（下一个调用即离开），`_on_spec_implemented` 与
  `_enqueue_front(verifier)` 由 `_enqueue` 的 `(spec, type)` 去重保证不双派。

## D4: 测试策略

tests/test_spec_concurrency_guard.py：

- 回退守卫：mock spec_review 收口遇 implementing → 断言不回退、仅 INFO 日志、
  `reviewer_run` 已清、`_review_skipped_result` 落盘、未调用 `_on_spec_ready`；
  幂等：status=ready/reviewing 时行为与既有用例逐字一致。
- 派发校验：mock 在飞 reviewer（`running_run_ids()` 含 `reviewer_run`）→ 断言
  `_on_spec_ready` 不派发，且 queue 候选筛选同口径跳过（两处落点各一用例）；
  陈旧锚点（run 已终态）→ 断言放行不误拦（防死锁回归）。
- ready 兜底：三条落点各一用例（ready + 实现分支 → 先补记 implementing 再 implemented，
  无 Invalid transition ERROR，有 WARNING 留痕）；非 `fenix/` 分支不触发兜底。
- 回归：既有 `test_spec_review_agent.py` / `test_spec_review_gate.py` /
  `test_review_circuit_breaker.py` / `test_state_machine.py` / dispatch 相关套件全绿；
  `_stream_recent`/`has_live_attempt` 若被扩展，`test_agent_runner*.py` 与
  `event_bus` 孤儿恢复用例须全绿（进程表与流判据语义不得漂移）。
