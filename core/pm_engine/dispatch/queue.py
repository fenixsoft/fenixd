"""queue.py — Q 队列核心/worker（refactor-giant-classes D1/D3/D5）。

原为 Dispatcher 的 8 个方法（含 `__init__` 与 742 行 `_run_agent_worker`
枢纽，`core/pm_engine/dispatch/_legacy.py`），原样搬移为 mixin。
宿主实例化时按 MRO 命中本 mixin 的 `__init__`，实例属性初始化语义不变。

`_run_agent_worker` 扇出到 B/F/P/V 各组的协作全部经宿主实例
`self.<method>`（搬移后仍是同一类的方法，只是文件不同）。

D3 patch 缝隙：本组使用 `time` 模块（入队时刻/老化计时），经模块顶部
导入即可——测试 ``patch.object(_dispatch_mod.time, "time", _tick)``
修改的是 time 模块对象（即 `core.pm_engine.dispatch.time`）的 `time`
属性，全进程共享，patch 依旧生效。
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Dict

from core.archive_commit import (
    ArchiveResidueScan,
    assess_archive_residue_selfheal,
    scan_archive_residue,
)
from core.state_machine import (
    TASK_GATE_REJECTIONS_FIELD,
    start_after_blocks_promotion,
    start_after_pending,
)
from core.agent_runner.provider_circuit import MODEL_CHAIN_UNAVAILABLE_MARKER
from core.pm_engine.dispatch.repair_lane import _merge_breaker_threshold

# ── WIP 延迟合回预算（evo-add-wip-defer-merge-retry-consumer 2.1/2.3）────────
# 等待窗口（分钟，自首阻时刻起算）与自动 merge-only 重试轮数上限，对齐
# code-fix defer D6 范式（90 分钟/6 次）。模块常量、**不新增配置键**（规避
# dashboard UI 联动义务，MAX_REPAIR_ROUNDS_PER_FAILURE 先例）。超任一上限即
# 停止自动重试、降级人工处置告警；orphaned_state 探测的豁免判据
# （admin_monitor 2.3）从本模块导入同一常量，保证「豁免失效」与「停止重试」
# 单一口径。
WIP_DEFER_WINDOW_MINUTES = 90.0
WIP_DEFER_MAX_ROUNDS = 6


def agent_worker_thread_name(spec_name: str, agent_type: str) -> str:
    """agent worker 线程命名的**单点**（evo-inprocess-verify-activity-signal 1.1）。

    形如 ``fenix-{agent_type}-{spec_name}``（本文件 _process_queue 的 Thread
    构造处）。抽函数而非两处硬编码字面量：admin_monitor 的 in-process 验证
    活性探测（``inprocess_verify_active`` 线程臂）按 ``threading.enumerate()``
    匹配同名活线程，判定读侧与命名写侧必须同一来源，防止命名漂移使探测
    静默失效。
    """
    return f"fenix-{agent_type}-{spec_name}"


class QQQueueMixin:
    """Q 队列核心/worker（design D1 表 B Q 组）。"""

    def __init__(self, pm):
        self._pm = pm  # 门面回引（design D3 规则 3：组件 → 门面 单向）

        # 队列与并发状态（design D3 规则 1：_queue_lock 与被保护的
        # _run_queue/_active_runs/_active_priorities 整体同迁，单锁语义不变）。
        # fix-spec-review-blocking-dispatch BUG-01：is_review_in_flight 内部
        # with self._queue_lock:（engine.py:3516）与 _process_queue 的外层
        # with self._queue_lock:（queue.py:274）同线程嵌套，threading.Lock
        # 非可重入 → 永久阻塞。改为 RLock 使同线程可重入，不影响既有语义。
        self._queue_lock = threading.RLock()
        self._active_runs = 0
        # 评审在飞集合（fix-spec-review-blocking-dispatch D3）：spec 名集合，
        # 评审条目独立登记、不占 _active_runs/_active_priorities（评审是晋升
        # 前置门，占实现槽位会把「先审后跑」退化为「审等实现跑完」）。生命周期
        # 与设计 D4 重入安全性对齐：出队时置位、worker 调 dispatch_review 前
        # 释放（MUST NOT 晚于锚点 reviewer_run 落盘），锚点落盘后由 reviewer_run
        # 判据接力；finally 幂等兜底释放（异常路径也释放）。
        self._active_reviews: set = set()
        # 评审 worker 过渡在飞集合（code-review item e3d1d53906cb）：spec 名
        # 集合，覆盖「_active_reviews 已释放、四步链锚点 reviewer_run 尚未落盘」
        # 的过渡窗口——该窗口内 reviewer_in_flight 判「无在飞评审」，外部通道
        # （admin re_review / rejected 复评）为同一 spec 新入队的评审条目会被
        # 放行，产生同 spec 两个并发 dispatch_review。worker 释放 _active_reviews
        # 的同一锁段内置位、收尾 finally 幂等释放；判据消费点仅
        # _review_entry_ready。MUST NOT 并入 _active_reviews：dispatch_review
        # 入口防重派判据（is_review_in_flight）与 D4 重入安全性共用该集合，
        # 过渡登记并入会让重试接力的新 worker 被本 worker 的登记挡住。
        self._reviews_dispatching: set = set()
        # 并行出题在飞集合（add-verify-lane-throughput 2.1）：spec 名集合，
        # planner-plan 并行条目独立登记、不占 _active_runs/_active_priorities
        # （出题与实现并行，占实现槽位会抵消并行收益）。生命周期对齐评审条目：
        # 出队时置位、worker 收尾 finally 幂等释放（异常路径也释放）。
        # 在飞数即豁免上限计量（_PARALLEL_PLAN_INFLIGHT_CAP），与
        # agents.max_concurrent 解耦（调大实现并发不放大豁免上限）。
        self._active_parallel_plans: set = set()
        # verify 车道同 spec 单飞在飞集合（evo-add-verify-dispatch-single-flight
        # 1.1）：spec 名集合，键=spec_name。verifier 条目占实现槽位（_active_runs，
        # 出队分流 else 分支照常递增），本集合只做同 spec 防双路验证的守卫判据，
        # 不参与槽位计量。生命周期对齐 _active_reviews：入队去重（_enqueue/
        # _enqueue_front 扩展为「未派发队列∪在飞」双查）＋出队分流锁内置位
        # （与 pop 同 _queue_lock 锁段，MUST NOT 延后到线程启动的「派发成功」点
        # ——neutralize-pack 事故第一路入队到派发仅约 13ms，登记晚于出队则
        # 「已出队未登记」窗口内第二路入队双查落空）＋worker finally 幂等摘除
        # （异常路径也摘除）。
        self._active_verifies: set = set()
        # Pending (priority, spec_name, agent_type, enqueued_at) tuples。
        # enqueued_at 为入队时刻 time.time()，仅供内存态老化计时（design D3）：
        # 不持久化，daemon 重启重建队列即视为等待清零。
        self._run_queue = []
        self._active_priorities = set()  # 当前活动 priority 集合（宽松优先级下可含多个档）
        self._active_priority_counts: Dict[int, int] = {}  # priority → 活动 run 数
        # 派发锁冲突退避定时器（_schedule_backoff_retry 维护，死定时器惰性清理）。
        self._backoff_timers: list = []
        # 秒挂冷却恢复定时器（cli-retry-backoff 2.2）：{spec_name}，幂等排程防重复。
        # 冷却到期由定时器重入 _on_spec_ready，不依赖 30 分钟全量扫描兜底。
        self._instant_fail_timers: set = set()
        # 信号死法冷却恢复定时器（evo-sigterm-source-tracking-cooldown）：
        # {spec_name}，幂等排程防重复。与 _instant_fail_timers 独立——两条冷却
        # 通道各自排程恢复，互不覆盖冷却截止（取更晚者生效）。
        self._signal_kill_timers: set = set()
        # fix-provider-transient-backoff（D4）：transient 恢复排程定时器：{spec_name}。
        # 瞬断终态触发后按 `transient_redispatch_delay_seconds`（缺省 600s）延迟重入
        # _on_spec_ready，同 instant_fail_timers 同款幂等去重。
        self._transient_timers: set = set()
        # 评审 content 失败重派短退避定时器判重集合（evo-fix-spec-review-
        # infra-attribution-bridge 3.1）：{spec_name}，幂等排程防重复定时器。
        # 由 SpecReviewManager._enqueue_review_retry 经 _schedule_recovery_timer
        # 排程（集合挂门面存续——SpecReviewManager 每次派发重建，实例级集合
        # 判不住跨派发重复）；到期回调重入队评审条目并重扫队列。
        self._review_content_backoff_timers: set = set()
        # add-impl-ocr-parallel-lane（任务 4.1/4.2）：ocr 审查车道在飞登记
        # {spec_name: True} + 专锁。单飞去重判据（join 侧幂等触发与 merge-back
        # 时点启动共用）；车道线程完成回调经同锁摘除登记。
        self._ocr_lane_lock = threading.Lock()
        self._ocr_lane_inflight: Dict[str, bool] = {}
        # WIP 等待超限降级告警去重集合：{spec_name}，daemon 生命周期内每条目
        # 至多告警一次（_report_wip_defer_stuck_once 的幂等去重判据；daemon 主
        # 循环复查与重试失败 Timer 两条触发路径共用，故 __init__ 统一初始化，
        # 避免两线程各自惰性建集合）。
        self._wip_defer_degrade_notified: set = set()
        # spec 目录在飞编辑顺延超限降级告警去重集合：{spec_name}，daemon
        # 生命周期内每条目至多告警一次（code-review item 820ca0230859，
        # _defer_merge_back 超限分支的幂等去重判据；与 _wip_defer_degrade_notified
        # 同款范式——merge-only 重试 Timer 链与实现 run 失败链双路并发时，
        # 防超限后重复发 major 告警）。
        self._spec_dir_inflight_stuck_notified: set = set()
        # 归档残留自愈单次尝试记账（evo-mergeback-archive-residue-selfheal 1.1）：
        # {spec_name}，daemon 生命周期内每条目至多自动尝试一次（对齐
        # _spec_dir_inflight_stuck_notified 范式；重启后至多再试一次），避免
        # 与归档自身重试互相踩踏。
        self._archive_residue_selfheal_attempted: set = set()
        # 自愈重放在飞守卫：{spec_name}，重放体（_retry_merge_back_only）失败链
        # 会再入 _defer_merge_back 熔断分支，重入帧据此直接返回——告警与熔断
        # 收口由外层自愈帧统一处置（防嵌套告警/递归）。
        self._archive_selfheal_active: set = set()
        # spec_dir_inflight 顺延周期消费者接手记账（本 SPEC 1.3）：{spec_name}，
        # 每条目接手重试至多一次，失败维持既有熔断告警与人工通道，不无限节拍
        # 重试。
        self._inflight_defer_recheck_attempted: set = set()

    # ── 验证车道槽位豁免（add-verify-lane-throughput 2.1）──────────────────
    # 槽位豁免车道全集：spec-review（既有先例，fix-spec-review-blocking-dispatch）
    # + planner-plan（本 SPEC 新增的并行出题条目）。planner-judge 维持验证管线内
    # 同步派发（随 verifier 条目 worker 执行、不过派发队列），本期不建独立队列
    # 条目；若后续 judge 独立成队列条目，沿用同模式豁免与上限（design D4）。
    _SLOT_EXEMPT_LANE_TYPES = ("spec-review", "planner-plan")
    # 并行 planner-plan 独立在飞上限（design D4）：同时最多 1 个并行出题 run，
    # 防出题分片（低优先级任务 5.1）挤占网关。独立常量、不走 agents.max_concurrent
    # ——调大实现并发不放大豁免上限（spec Scenario: 实现并发上调不放大豁免）。
    _PARALLEL_PLAN_INFLIGHT_CAP = 1
    # 评审车道在飞上限（evo-fix-spec-review-infra-attribution-bridge 2.1）：
    # 批量晋升的评审条目并发无上限（_SLOT_EXEMPT_LANE_TYPES 豁免实现槽位），
    # 短窗口批量晋升即并发风暴（实证：8 个 spec 4.58 秒内同时派评审撞账户级
    # 429）。达上限时候选评审条目保留队列不 pop（条目不丢，下轮补位）。
    # 可配 review.max_inflight（缺省 3；非法/非正值回退缺省），独立常量、
    # 不走 agents.max_concurrent——同 _PARALLEL_PLAN_INFLIGHT_CAP 范式，
    # 调大实现并发不放大评审豁免上限。
    _REVIEW_INFLIGHT_CAP = 3
    _REVIEW_INFLIGHT_CAP_CONFIG_KEY = "review.max_inflight"
    # 并行出题条目可派发的 spec 状态集：ready（触发时刻）/ implementing /
    # implemented（impl 先完成、出题仍在排队的追平窗口）。drafted/blocked（含
    # 冻结——freeze_spec 置 blocked）等回退态一律不可派发（任务 1.2：回退即停）。
    _PARALLEL_PLAN_DISPATCHABLE_STATUS = ("ready", "implementing", "implemented")

    def _parallel_plan_cap_reached(self) -> bool:
        """并行 planner-plan 豁免上限判定（在飞 ≥1 即达上限）。"""
        return len(self._active_parallel_plans) >= self._PARALLEL_PLAN_INFLIGHT_CAP

    def _review_inflight_cap(self) -> int:
        """评审车道在飞上限（evo-fix-spec-review-infra-attribution-bridge 2.1）。

        配置键 ``review.max_inflight``，缺省 ``_REVIEW_INFLIGHT_CAP``（3）。
        配置容错（同 agents.max_concurrent 读取点口径）：字符串/None/非法值
        不中断候选扫描——int() 失败或非正值回退缺省。
        """
        try:
            val = int(
                self._pm._get_config(
                    self._REVIEW_INFLIGHT_CAP_CONFIG_KEY, self._REVIEW_INFLIGHT_CAP
                )
            )
        except (TypeError, ValueError):
            return self._REVIEW_INFLIGHT_CAP
        if val <= 0:
            return self._REVIEW_INFLIGHT_CAP
        return val

    def _review_inflight_count(self) -> int:
        """评审车道当前占用数（evo-fix-spec-review-infra-attribution-bridge 2.1）。

        计量集 = ``_active_reviews``（已出队、锚点未落盘）∪
        ``_reviews_dispatching``（worker 已释放前者、dispatch_review 未收工——
        真正的在飞评审 run 都在这段窗口内）。两集合按生命周期互斥（worker 在
        同一锁段内释放前者、置位后者），并集即「已占用评审车道」的完整计数；
        成员读不加锁（对齐 engine.is_review_in_flight 的裸读先例）。
        """
        return len(self._active_reviews) + len(self._reviews_dispatching)

    def _parallel_plan_entry_ready(self, spec: dict) -> bool:
        """并行出题条目候选可派发判定（对齐 _review_entry_ready 单一落点范式）。

        供 ``_process_queue`` 的 best_valid_prio 扫描与 dispatch_idx 扫描两处
        共用：状态合法（_PARALLEL_PLAN_DISPATCHABLE_STATUS）且豁免上限未满。
        状态非法（打回 drafted / 冻结 blocked / spec 已删除）→ False（条目
        滞留队列不再派发，半成品产物由消费侧校验兜底，任务 1.2）。

        签名不含 ``sname``（与 ``_review_entry_ready`` 的唯一差异）：本判定
        无需按 spec 查在飞评审——豁免上限是全局集合计数，spec 名仅调用方
        扫描上下文自持（code-review item fe5e723fcfb3：形参不落即删，不留
        未读参数）。
        """
        if (spec or {}).get("status") not in self._PARALLEL_PLAN_DISPATCHABLE_STATUS:
            return False
        return not self._parallel_plan_cap_reached()

    def _get_spec_priority(self, spec_name: str) -> int:
        """读取 SPEC 的 priority，缺省为 5。"""
        spec = self._pm.state_machine.read_one(spec_name)
        if spec and isinstance(spec.get("priority"), int):
            return spec["priority"]
        return 5

    def _rollback_dispatch_slot(self, base_prio, entry_to_dispatch=None):
        """回滚一次已 pop 的派发占用（可选重新入队 + 释放槽位计数）。

        调用方 MUST 持有 ``_queue_lock``。统一各闸门（预算耗尽 / 内容缺失 /
        同源收敛 / 守卫三）触发的记账（code-review item 25e5ba1febfc：旧实现
        六处复制同一段逻辑、微差易漂移），并统一「仅当该档计数归零才移出
        ``_active_priorities``」的口径——修复 code-review item 5eab0a6c324d：
        旧预算/内容闸门无条件 ``discard(base_prio)``，在同档仍有活动 run
        （cnt > 0）时会移除一个仍活跃的档位，破坏
        「priority ∈ _active_priorities ⟺ _active_priority_counts[priority] > 0」
        不变量，使宽松优先级闸门 ``min(self._active_priorities)`` 取值错误。
        """
        if entry_to_dispatch is not None:
            self._run_queue.insert(0, entry_to_dispatch)
        self._active_runs -= 1
        cnt = self._active_priority_counts.get(base_prio, 0) - 1
        if cnt <= 0:
            self._active_priority_counts.pop(base_prio, None)
            self._active_priorities.discard(base_prio)
        else:
            self._active_priority_counts[base_prio] = cnt

    def _enqueue(self, spec_name: str, agent_type: str):
        """Add a run request to the queue (thread-safe).

        条目结构：(priority, spec_name, agent_type, enqueued_at)。
        priority 从 STATE.md 读取（缺省 5）；enqueued_at = time.time() 供
        派发队列老化计时（design D3，内存态、不持久化）。
        """
        priority = self._pm._get_spec_priority(spec_name)
        entry = (priority, spec_name, agent_type, time.time())
        with self._queue_lock:
            # verify 单飞守卫（evo-add-verify-dispatch-single-flight 1.1）：同 spec
            # 已有在飞验证 run → 拒绝＋结构化留痕，不排队（design 决策 2：拒绝优于
            # 排队——「在飞即排队」需引入延迟派发语义，而在飞 run 收工自有终态
            # 收口，重复条目只会派出第二个并发验证；对齐
            # fix-admin-cross-type-duplicate-dispatch 先例）。
            if agent_type == "verifier" and spec_name in self._active_verifies:
                self._pm.logger.warning(
                    "pm_engine",
                    f"verify 单飞守卫：'{spec_name}' 已有在飞验证，拒绝重复入队"
                    f" ({agent_type})",
                    {"spec": spec_name, "agent_type": agent_type,
                     "guard": "verify_single_flight", "path": "enqueue"},
                )
                return
            # 去重：忽略 priority 差异，只看 (spec, agent)
            if not any(e[1] == spec_name and e[2] == agent_type for e in self._run_queue):
                self._run_queue.append(entry)
                self._pm.logger.debug(
                    "pm_engine", f"Queued: {spec_name} ({agent_type}, P{priority})"
                )

    def _remove_queued_entry(self, spec_name: str, agent_type: str) -> bool:
        """按 (spec, agent_type) 摘除队列条目（线程安全）。

        供车道停止路径消费（add-verify-lane-throughput 1.2：spec 状态回退时
        摘除在队并行出题条目）。返回是否实际摘除。
        """
        with self._queue_lock:
            before = len(self._run_queue)
            self._run_queue = [
                e for e in self._run_queue
                if not (e[1] == spec_name and e[2] == agent_type)
            ]
            return len(self._run_queue) < before

    def _enqueue_front(self, spec_name: str, agent_type: str):
        """Insert a run request at the front of its priority bucket (thread-safe).

        在优先级调度下，「队首」语义改为同档优先：verifier 与 implementer
        属于同一 SPEC、同一 priority，插入后落回同一档且保持档内 FCFS。
        """
        priority = self._pm._get_spec_priority(spec_name)
        entry = (priority, spec_name, agent_type, time.time())
        with self._queue_lock:
            # verify 单飞守卫（evo-add-verify-dispatch-single-flight 1.1）：同 spec
            # 已有在飞验证 → 拒绝＋结构化留痕（repair 链成功/异常尾段
            # _enqueue_front 与 admin 复位直通道均汇聚本入口，命中即不插队不排队）。
            if agent_type == "verifier" and spec_name in self._active_verifies:
                self._pm.logger.warning(
                    "pm_engine",
                    f"verify 单飞守卫：'{spec_name}' 已有在飞验证，拒绝队首重入队"
                    f" ({agent_type})",
                    {"spec": spec_name, "agent_type": agent_type,
                     "guard": "verify_single_flight", "path": "enqueue_front"},
                )
                return
            # Remove existing duplicate (ignoring priority)
            self._run_queue = [
                e for e in self._run_queue if not (e[1] == spec_name and e[2] == agent_type)
            ]
            # 插入到同优先级档的最前面（保持同一档内的顺序）
            insert_idx = 0
            for i, e in enumerate(self._run_queue):
                if e[0] == priority:
                    insert_idx = i
                    break
                if e[0] > priority:
                    insert_idx = i
                    break
                insert_idx = i + 1
            self._run_queue.insert(insert_idx, entry)
            self._pm.logger.debug(
                "pm_engine", f"Queued at front of P{priority}: {spec_name} ({agent_type})"
            )

    def _aging_bonus(self, enqueued_at: float, now: float) -> int:
        """队列等待老化收益：条目等待越久，参与比较的优先级档越高。

        方向说明：本项目 priority 数值越小代表越重要、越早派发。放宽规则为
        「任务 X 可派发当且仅当 min(active_priorities) >= X」——因此等待条目的
        *比较档位* 必须随等待降低（effective = base - bonus）才能在 P4/P5 家族
        持续占用下给 P6 打开派发窗口（spec Scenario: P6 条目获得窗口）。设计
        文档中的字面 `base + …` 公式与自身 Scenario 相悖（只会让 P6 更晚派发），
        本实现以行为需求为准：effective = max(0, base - bonus)。

        config: pm.dispatch.aging.
            enabled (默认 false) —— 关闭时恒返回 0，行为与现状完全一致；
            initial_wait_minutes (默认 30) —— 等待不足此值不老化的零窗口；
            step_down_minutes (默认 15) —— 每满一档老化时间降一级比较；
            floor_levels (默认 4) —— 单条目等效降级总量上限（P6 最低可比至 P2，
              仍天然低于新到的 P1，高优家族先占）。
        """
        from core.config import ConfigLoader

        cfg = self._pm.config or {}
        a = dict(ConfigLoader.get(cfg, "pm.dispatch.aging", {}) or {})
        enabled = a.get("enabled", False)
        if not enabled:
            return 0
        # 注意：不能用 `or 默认值` 取参 —— 配置 0（initial_wait/step_down）合法且常见，
        # 0 为假值会被误替换为默认值。
        iw = a.get("initial_wait_minutes")
        sw = a.get("step_down_minutes")
        fl = a.get("floor_levels")
        try:
            initial_wait = max(0.0, float(iw if iw is not None else 30)) * 60.0
            step_down = max(0.0, float(sw if sw is not None else 15)) * 60.0
            floor_levels = max(0, int(fl if fl is not None else 4))
        except (TypeError, ValueError):
            # 畸形配置（如非数值字符串）只降级回缺省值，不炸派发循环
            #（口径对齐 _merge_retry_* 读取器）。
            initial_wait = 30 * 60.0
            step_down = 15 * 60.0
            floor_levels = 4
        elapsed = max(0.0, now - (enqueued_at or now))
        if step_down <= 0 or elapsed < initial_wait:
            return 0
        steps = int((elapsed - initial_wait) // step_down)
        return min(floor_levels, max(0, steps))

    def _effective_priority(self, base: int, enqueued_at: float, now: float) -> int:
        """条目参与优先级判定时的有效档位（activity 追踪仍用 base，活动任务不老化）。"""
        return max(0, base - self._pm._aging_bonus(enqueued_at, now))

    def _should_defer_for_reviewer(self, spec: dict, sname: str) -> bool:
        """派发前在飞评审校验（evo-spec-concurrency-flight-guard D2）**单一落点**。

        `_process_queue` 的候选筛选（best_valid_prio 扫描）与档位对齐（dispatch_idx
        扫描）两处需同口径顺延（覆盖 family.py:585 / adjudication.py:1408 /
        queue.py:870 等绕过 `_on_spec_ready` 的直入队列路径）。提取为本方法避免
        两处 26 行重复守卫漂移：日志文案 / fail-open 策略 / stale 处理只在此改一处。

        - ``spec``：``state_machine.read_one(sname)`` 结果；``reviewer_run`` 为空
          **且**该 spec 不在 ``_active_reviews`` 中 → 无在飞评审（放行）。
          （fix-spec-review-blocking-dispatch 3.4：前置条件由「reviewer_run 非空」
          放宽为「reviewer_run 非空 或 _active_reviews 命中」——「锚点尚未落盘、
          但评审条目已在 _active_reviews」的窗口必须进入在飞判定，正是
          reviewer_in_flight 新增 ``"queued"`` 前置判据要覆盖的窗口。）
        - ``reviewer_in_flight`` 分层判定：进程表 → 流文件 → ``_active_reviews``
          前置判据（"queued"）→ 陈旧锚点 fail-open。
        - 判定异常 fail-open（D0 第 5 条，对齐 engine 落点容错）。
        - 返回 True = 应顺延（调用方 MUST ``continue``：条目保留队列、不 pop、
          不消耗 attempt，待 review 收尾后由既有重触发通道重判）。
        """
        reviewer_run = spec.get("reviewer_run")
        if reviewer_run or self._pm.is_review_in_flight(sname):
            try:
                in_flight, reason = self._pm.agent_runner.reviewer_in_flight(
                    sname, reviewer_run
                )
            except Exception as e:
                # 判定异常 fail-open（D0 第 5 条）
                self._pm.logger.warning(
                    "pm_engine",
                    f"在飞评审判定异常 '{sname}'（fail-open 放行）: {e}",
                )
                in_flight, reason = False, None
            if in_flight:
                self._pm.logger.info(
                    "pm_engine",
                    f"在飞评审 run，派发顺延: {sname} run={reviewer_run}",
                )
                return True
            if reason == "stale":
                self._pm.logger.warning(
                    "pm_engine",
                    f"陈旧评审锚点（run 已终态）按无在飞评审放行; "
                    f"待既有恢复路径清理: {sname} run={reviewer_run}",
                )
        return False

    def _review_entry_ready(self, spec: dict, sname: str) -> bool:
        """评审条目候选可派发判定（fix-spec-review-blocking-dispatch 1.2）。

        供 ``_process_queue`` 的 best_valid_prio 扫描与 dispatch_idx 扫描两处
        共用（对齐 ``_should_defer_for_reviewer`` 的单一落点范式，避免守卫
        漂移）：

        - 状态 MUST 为 ``reviewing``（晋升链已置位，派发处不再 transition）；
        - 无在飞评审才可派发：经 ``reviewer_in_flight`` 取**在飞结论**
          （``in_flight`` 为 False 才放行）。判据 MUST NOT 按「锚点非空即拒」
          ——本 SPEC 新增的「锚点写入在 dispatch_review 内、异常后不再清除」
          路径会让锚点残留的条目被永久静默跳过（design D4 重入安全性）。
          ``_active_reviews`` 前置判据（``"queued"``）同样经 reviewer_in_flight
          命中：空锚点 + 已出队未收口 → 判在飞 → 本条目不派发。
        - worker 过渡在飞判据（code-review item e3d1d53906cb）：``_active_reviews``
          已被 worker 释放（MUST NOT 晚于锚点落盘，design D4）、锚点尚未落盘的
          过渡窗口内，reviewer_in_flight 会判「无在飞评审」；``_reviews_dispatching``
          命中（同 spec 评审 worker 已出队未收工）→ 判在飞顺延，堵住同 spec
          第二条评审条目在窗口内被并发派发的窗口。重试接力条目不受影响：
          worker 收尾先摘登记、``_run_agent_worker`` finally 的 ``_process_queue``
          再重扫派发。
        - 判定异常 fail-open 放行（保守不阻塞候选扫描，与其它候选闸门一致）。
        """
        if spec.get("status") != "reviewing":
            return False
        # 评审在飞上限（evo-fix-spec-review-infra-attribution-bridge 2.1）：达
        # 上限时候选条目保留队列不 pop（条目不丢，下轮 worker finally 重扫补位
        # ——同 :558「在飞即跳过候选、条目保留」先例）。置最前（status 校验后）：
        # 廉价集合计数短路，超载时不做后续 reviewer_in_flight 进程表/流文件探测。
        # INFO 留痕（生产日志全库 0 条 DEBUG，闸门静默不可见曾是事故复盘要点）。
        if self._review_inflight_count() >= self._review_inflight_cap():
            self._pm.logger.info(
                "pm_engine",
                f"评审在飞达上限（{self._review_inflight_count()} ≥ "
                f"{self._review_inflight_cap()}），派发顺延（条目保留队列）: {sname}",
            )
            return False
        # 过渡在飞判据（code-review item e3d1d53906cb）：见 docstring。成员读
        # 不加锁（对齐 engine.is_review_in_flight 对 _active_reviews 的裸读先例）。
        if sname in self._reviews_dispatching:
            self._pm.logger.debug(
                "pm_engine",
                f"评审 worker 过渡在飞（已出队未收口），派发顺延: {sname}",
            )
            return False
        try:
            in_flight, _reason = self._pm.agent_runner.reviewer_in_flight(
                sname, spec.get("reviewer_run")
            )
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"评审条目在飞判定异常 '{sname}'（fail-open 放行）: {e}",
            )
            return True
        return not in_flight

    def _start_after_blocks_entry(self, spec: dict, sname: str, atype: str) -> bool:
        """队列 start_after 门控（按 agent_type 分流）**单一落点**。

        `_process_queue` 的 best_valid_prio 扫描与 dispatch_idx 扫描两处须同口径
        顺延，提取为本方法避免两处重复守卫漂移（对齐 ``_review_entry_ready`` /
        ``_should_defer_for_reviewer`` 的单一落点范式）。

        **分流依据（2026-09-21 事故）**：队列在
        ``fix-spec-review-blocking-dispatch``（评审派发异步化）之后**同时承载
        ``spec-review`` 条目**，不再是纯实现派发口。旧实现两处均裸调无条件谓词
        ``start_after_pending(spec)``，对评审条目也开火——``start_after=manual``
        的 SPEC 其评审条目**入队后永久滞留**（无日志、无派发、无评审 run），
        dispatch 档（缺省）被静默抬高成 full 档行为，与
        ``add-start-after-scope-config`` 的「dispatch 档下 reviewing SPEC 照常
        派发评审」契约矛盾。

        - **实现车道**（implementer / fast-track / verifier / repair 等）：保持
          无条件 ``start_after_pending``——「到点才实现」是 start_after 的无条件
          本职语义，与 scope 取值无关（scope 只控制「是否提前晋升/评审」）。
        - **``spec-review`` 条目**：改经 scope 感知的 ``start_after_blocks_promotion``
          ——与 ``_on_spec_reviewing`` 入口守卫同谓词、同 config 口径（dispatch
          档放行、full 档拦截），杜绝入口放行 / 队列二次拦截的口径分裂。
        - 判定异常 fail-open 放行（不阻塞候选扫描，与其它候选闸门一致）。
        """
        if atype != "spec-review":
            return start_after_pending(spec)
        try:
            return start_after_blocks_promotion(spec, getattr(self._pm, "config", None))
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"start_after 门控判定异常 '{sname}'（fail-open 放行）: {e}",
            )
            return False

    def _queue_entry_ready(self, spec: dict, sname: str, atype: str) -> bool:
        """队列条目状态守卫与闸门链候选判定**单一落点**。

        供 ``_process_queue`` 的 best_valid_prio 扫描与 dispatch_idx 扫描两处
        共用（对齐 ``_review_entry_ready`` / ``_parallel_plan_entry_ready`` /
        ``_start_after_blocks_entry`` 的单一落点范式；code-review item
        409a6ced70ce：两处约 80 行守卫链手工同步已发生日志漂移——秒挂冷却
        命中第一处记 debug、第二处静默跳过，提取后统一日志口径）。判定顺序
        与提取前两处扫描逐字一致，对合法条目的判定结果不变：

        - 车道分流状态合法性：并行出题（``_parallel_plan_entry_ready``）、
          评审（``_review_entry_ready``）、implementer/fast-track（ready/
          implementing）、verifier（implemented/testing）；
        - 派发退避（``_dispatch_backoffed``）；
        - start_after 门控（``_start_after_blocks_entry``，debug 留痕）；
        - 秒挂冷却（仅 implementer/fast-track，debug 留痕并排程到期
          恢复）/ 信号死法冷却（全部 agent 类型，同款）——两处扫描经本落点
          统一记 debug（判定不变，仅日志口径统一）；
        - 在飞评审校验（``_should_defer_for_reviewer``，仅实现车道，置于
          退避/start_after/冷却之后避免无谓进程表判定）。

        返回 False = 本轮不可派发（条目保留队列待重判）；调用方 MUST
        ``continue``。
        """
        status = spec.get("status")
        if atype == "planner-plan":
            # 并行出题条目候选判定（2.1）：状态合法且豁免上限未满。
            if not self._parallel_plan_entry_ready(spec):
                return False
        elif atype == "spec-review":
            # 评审条目候选判定（1.2/1.3/1.4）：状态必须 reviewing 且无在飞评审。
            if not self._review_entry_ready(spec, sname):
                return False
        elif atype == "implementer" and status not in ("ready", "implementing"):
            # implementing 允许派发 = 原地打回的修复重派（热修 2026-08-29）：
            # 打回处置 _enqueue 时状态为 implementing，旧条件 status != "ready"
            # 导致修复条目被永久静默跳过、链路停摆。入队点均在 run 终止后
            # （打回处理器/零变更重试）且 _enqueue 按 (spec,type) 去重，无双派。
            return False
        if atype == "fast-track" and status not in ("ready", "implementing"):
            # fast-track：ready 正常派发；implementing 允许 = 失败打回后的修复重派
            # （入队点均在 run 终止后，与 implementer 同语义，无双派）。
            return False
        if atype == "verifier" and status not in ("implemented", "testing"):
            # testing 允许派发 = 重验车道出口（fix-robustness-edge-cases
            # 孤儿信号根因）：无驱动 testing 的三条恢复车道
            # （event_bus._recover_testing / admin_monitor 孤儿复位 /
            # env 阻塞复位直通道）都按重验语义入队 verifier，而 spec
            # 已在 testing——旧守卫 status != "implemented" 让条目永久
            # 滞留队列（无日志、无派发），testing 只能等 stuck 阈值兜底。
            # 派发处 transition(testing) 为幂等自迁移，语义不变。
            return False
        if self._pm._dispatch_backoffed(spec):
            return False
        # add-spec-scheduling-controls D2：start_after 未到期静默跳过
        # （不写 error 不翻状态，对齐退避门控的防自触发设计）；到期后由
        # 60s 定时唤起 / full_scan 兜底恢复调度。
        # 分流落点见 _start_after_blocks_entry：实现车道无条件，
        # spec-review 条目走 scope 感知谓词（dispatch 档放行）。
        if self._start_after_blocks_entry(spec, sname, atype):
            self._pm.logger.debug(
                "pm_engine",
                f"start_after 未到期，跳过 {atype} 派发 '{sname}'（定时拾取）",
            )
            return False
        # cli-retry-backoff 2.2：秒挂冷却期内跳过 implementer/fast-track
        # 派发（不耗预算、不起进程），并排程到期自动恢复。
        # （code-review item 634bc08048e4：原列表含 "repair"，但 repair run 由
        # repair_lane._dispatch_repair_lane 自起线程执行、不经队列（其冷却在
        # repair_lane 内直查 _instant_fail_cooled），全仓无 "repair" 入队路径
        # ——删除该口径分裂，防误入队条目经闸门放行后被 worker 静默吞掉。）
        if atype in (
            "implementer",
            "fast-track",
        ) and self._pm._instant_fail_cooled(sname):
            self._pm.logger.debug(
                "pm_engine",
                f"秒挂冷却中，跳过 {atype} 派发 '{sname}'",
            )
            self._schedule_instant_fail_recovery(sname, lock_held=True)
            return False
        # evo-sigterm-source-tracking-cooldown：信号死法冷却期内跳过
        # 该 spec 的**全部** agent 类型重派（含 admin/impl 处置 run
        # 路由；不耗预算、不起进程），并排程到期自动恢复。与秒挂冷却
        # 并存：两条通道各自独立，取更晚的冷却截止生效。
        if self._pm._signal_kill_cooled(sname):
            self._pm.logger.debug(
                "pm_engine",
                f"信号死法冷却中，跳过 {atype} 派发 '{sname}'",
            )
            self._schedule_signal_kill_recovery(sname, lock_held=True)
            return False
        # 派发前在飞评审校验（evo-spec-concurrency-flight-guard D2）：
        # 存在在飞 spec-review run 时跳过候选（条目保留队列、不 pop、
        # 不消耗 attempt），待 review 收尾重判。本落点覆盖 family.py:585 /
        # adjudication.py:1408 / queue.py:870 等绕过 `_on_spec_ready` 的
        # 直入队列路径（与 engine 落点同口径）。陈旧锚点（run 已终态）判为
        # 无在飞评审放行并记 WARNING（D0）。位置：置于退避/start_after/
        # 冷却闸门之后、派发判定之前（D2 任务 2.4：避免在无谓路径上做
        # 进程表判定）。
        if atype in ("implementer", "fast-track") and self._should_defer_for_reviewer(
            spec, sname
        ):
            return False
        return True

    def _process_queue(self):
        """Process the run queue — relaxed-priority parallel scheduling.

        调度规则（宽松优先级并行，fix-fenix-token-waste 后按用户要求调整）：
        - 任务 X 可派发当且仅当没有比 X 更重要的活动任务
          （即 min(active_priorities) >= X）：有 P6 在跑时 P5 可并发、P7 不行。
        - 同一档内多个任务可并行至 max_concurrent；不同档可并发（只要满足上述规则）。
        - 不抢占：已在运行的任务不会被新到的高优先级中断。
        - 每轮派发队列中最高优先级的合法就绪条目。
        - 槽满豁免边界（fix-spec-review-blocking-dispatch 1.5b / add-verify-
          lane-throughput 2.1，code-review item 64394b92e9ef）：槽位占满时
          评审 / 并行出题豁免车道照常扫描派发（不占实现槽位、并发无上限），
          但该豁免只作用于槽位闸门；宽松优先级闸门（上方第一条）对所有车道
          统一生效——豁免车道条目在存在数值更小的活动任务（更高优）时同样
          顺延，不因槽满豁免而例外。

        队列老化（dispatch-queue-aging / design D3）：比较用 effective 档位
        （base - 等待老化收益）；派发后活动集合 _active_priorities 记 base 原值
        —— 活动任务不参与老化降级（spec Scenario: 持久运行的 P4 不会被降级）；
        同级（effective 相等）条目保持「先入队先派发」的队首顺序（先入队者
        老化收益 ≥ 后入队者，队首扫描天然保持同级 FCFS，spec Scenario: 同级
        顺序稳定）。老化仅内存态 —— enqueued_at 随进程存活，daemon 重启重建
        队列即从零计时。
        """
        # 优雅关闭期间不再派发（fix-admin-self-heal）
        if self._pm.shutting_down:
            self._pm.logger.debug("pm_engine", "Shutting down — dispatch paused")
            return
        # fix-provider-transient-backoff D4 + evo-fix-transient-break-unseal-backoff
        # 1.2：首道闸按 冻结 > post-unseal hold > 探针观察窗 > 错峰放行 态序扩展
        # 消费（短路顺序即优先级；冻结期重触发则 hold 作废重计——gate 查询先查
        # 冻结即天然满足）。与 instant_fail_cooled 同构：各态到期自动恢复；在飞
        # run 不受影响。队列里已有条目被闸门挡下时以 INFO 留痕（2026-09-22 事故：
        # 解冻后的 spec_ready 已入队，但熔断闸门只在 debug 级留痕、生产日志全库
        # 0 条 DEBUG——「ready 却 4 分钟不派发」在日志里完全不可见）。积压条目的
        # 最终放出由解封节奏定时器链主动唤醒兜底（ProviderCircuit._schedule_
        # unseal_wake → _process_queue 首道闸查询即推进态机）。
        gate = self._pm._transient_unseal_gate()
        if gate == "frozen":
            with self._queue_lock:
                held = len(self._run_queue)
            if held:
                self._pm.logger.info(
                    "pm_engine",
                    f"Global transient break active — {held} queued dispatch(es) "
                    f"held (fix-provider-transient-backoff D4)",
                )
            else:
                self._pm.logger.debug(
                    "pm_engine",
                    "Global transient break active — dispatch paused "
                    "(fix-provider-transient-backoff D4)",
                )
            return
        # 错峰开放拍空队收口（code-review item 31578b1e77d8）：下方收口判据
        # 只覆盖 release-wait（当拍未到节拍）；当拍已开放（gate == "release"）
        # 时积压若已在窗口内清空（如条目被守卫回滚/移除而未经 admit），队列
        # 恒空、gate 恒为 release——下方 `not self._run_queue` 兜底收口在槽满
        # 提前返回路径不可达，唤醒链会以 0.5s 间隔空转直至硬过期（horizon
        # ≥600s ≈ 1200 次空跑 _process_queue）。队列空即退出错峰态终止链条；
        # held 非空不收口——条目仍落到下方常态派发路径按节拍准入
        # （admit_unseal_dispatch 控拍），错峰语义不变。
        if gate == "release":
            with self._queue_lock:
                held = len(self._run_queue)
            if not held:
                self._pm._transient_unseal_note_drained()
                return
        if gate in ("hold", "observe", "release-wait"):
            with self._queue_lock:
                held = len(self._run_queue)
            if gate == "release-wait" and not held:
                # 错峰积压已放完：退出错峰态，后续派发恢复常态节奏
                self._pm._transient_unseal_note_drained()
            elif held:
                self._pm.logger.info(
                    "pm_engine",
                    f"Transient unseal {gate} active — {held} queued dispatch(es) "
                    f"held (evo-fix-transient-break-unseal-backoff)",
                )
            else:
                self._pm.logger.debug(
                    "pm_engine",
                    f"Transient unseal {gate} active — dispatch paused "
                    f"(evo-fix-transient-break-unseal-backoff)",
                )
            return
        # 并发缺省值 2→5（add-pipeline-throughput-governance D1）：全历史耗时
        # 显示实现排队 893h（37.1%）为最大时间池，缺省 2 的槽位串行是主因之一。
        # 显式配置优先级不变——.fenix/config.yaml 写了 agents.max_concurrent
        # 即按配置值生效，代码缺省只对无配置部署生效；full-suite.lock 主机级
        # 回归锁（等待上限 600s、超时 skip）保证多 run 回归互斥语义不变。
        # 配置侧 int() 归一（code-review item db57ee959a49，与
        # agents.merge_breaker_threshold / agents.max_retries 读取点同款）：
        # 字符串配置裸用于下方槽位比较（持锁临界区内）抛 TypeError，沿
        # worker finally / 定时器线程的 _process_queue 调用链逃逸，派发整体
        # 停摆；非法值回退缺省，max(1, ...) 收下限。
        try:
            cfg_max_concurrent = self._pm._get_config("agents.max_concurrent", 5)
            max_concurrent = (
                5 if cfg_max_concurrent is None else int(cfg_max_concurrent)
            )
        except (TypeError, ValueError):
            max_concurrent = 5
        max_concurrent = max(max_concurrent, 1)

        # 本轮调用内已被守卫三抑制的条目（spec, agent_type）。
        # 被抑制条目保持 queued（后到抑制），但绝不能阻塞其后的条目派发
        # —— 否则队首一个被抑制条目就会让整条队列停摆（2026-08-28 实证：
        # 双 ready 同根兄弟互相判对方 actionable，P6/P7 全线无法派发）。
        suppressed = set()

        while True:
            entry_to_dispatch = None

            with self._queue_lock:
                now = time.time()
                # 槽位闸门（fix-spec-review-blocking-dispatch 1.5b / design D2
                # 第二处）：实现车道槽位占满时不得无条件提前返回——队列中可能
                # 存在评审条目，评审是晋升前置门、不占实现槽位（评审并发无上限），
                # 必须照常被扫描并派发。放行只针对评审条目本身：下方扫描循环在
                # slots_full 时对非评审条目 continue，故实现条目不因该放行而被
                # 派发（``max_concurrent`` 对实现车道仍生效）。
                slots_full = self._active_runs >= max_concurrent
                # code-review item 806ba20de85f：同轮判据缓存 (sname, atype) →
                # (spec, ready)。best_valid_prio 扫描与 dispatch_idx 扫描在同一
                # 锁持有窗口内连续执行，过滤条件一致、队列与 suppressed 均不变
                # （_queue_entry_ready 链上仅幂等恢复定时器排程与日志，无队列
                # mutation），第二轮直接复用首轮判定，消除同轮对同一批 spec 的
                # 重复 read_one 读盘与闸门链（含 reviewer_in_flight 进程表/流
                # 文件探测）。缓存每轮 while 重建，不跨轮。
                # code-review item eb63419bbfd6：槽满豁免车道存在性判定
                # （has_review/has_parallel_plan）并入同一轮扫描由缓存推导——
                # 旧实现单独预扫描对同批评审/出题条目重复 read_one 与闸门链
                # 判定，队列越大持锁 I/O 临界区越长，放大 dashboard 只读路径
                # 在 _queue_lock 上的等待（与 806ba20de85f 同型关切）。
                scan_verdicts = {}
                best_valid_prio = None
                has_review = False
                has_parallel_plan = False
                for entry in self._run_queue:
                    prio, sname, atype, enqueued_at = entry
                    if (sname, atype) in suppressed:
                        continue
                    # 槽位占满时实现车道条目不参与候选（评审/并行出题条目放行，
                    # 1.5b + add-verify-lane-throughput 2.1）
                    if slots_full and atype not in self._SLOT_EXEMPT_LANE_TYPES:
                        continue
                    eff = self._pm._effective_priority(prio, enqueued_at, now)
                    spec = self._pm.state_machine.read_one(sname)
                    if not spec:
                        scan_verdicts[(sname, atype)] = (None, False)
                        continue
                    # 状态守卫与退避/start_after/双冷却/在飞评审闸门链：单一
                    # 落点 _queue_entry_ready（对齐 _review_entry_ready 单一
                    # 落点范式，code-review item 409a6ced70ce），两处扫描不再
                    # 各自复制守卫链。
                    ready = self._queue_entry_ready(spec, sname, atype)
                    scan_verdicts[(sname, atype)] = (spec, ready)
                    if not ready:
                        continue
                    # 槽满豁免车道存在性（评审 + 并行出题，2.1；旧独立预扫描
                    # 判定并入此处，eb63419bbfd6）：就绪的评审/出题条目照常
                    # 放行派发，实现条目照旧滞留。
                    if atype == "spec-review":
                        has_review = True
                    elif atype == "planner-plan":
                        has_parallel_plan = True
                    if best_valid_prio is None or eff < best_valid_prio:
                        best_valid_prio = eff
                if slots_full and not (has_review or has_parallel_plan):
                    return
                if not self._run_queue:
                    # 队列已空：若错峰放行态仍在（积压已放完），通知退出错峰态
                    # （evo-fix-transient-break-unseal-backoff 1.2；非错峰态零操作）
                    self._pm._transient_unseal_note_drained()
                    return
                if best_valid_prio is None:
                    return  # 无就绪条目

                # 确定当前应派发的目标档位（宽松优先级）：
                # 任务 X 可派发当且仅当没有比 X 更重要的活动任务
                # （即 min(active) >= X；有 P6 在跑时 P5 可并发、P7 不行）。
                # 无活动任务时派发就绪条目中最高优先级档。
                if self._active_priorities:
                    min_active = min(self._active_priorities)
                    if best_valid_prio > min_active:
                        # 队列中最优就绪任务比活动任务更低优先（数值更大）：
                        # 被更高优先的活动任务挡住，本轮不派发
                        return
                target_prio = best_valid_prio

                # 从队列头部开始找第一个 effective == target 且状态合法的条目。
                # 队首即同档最老条目（enqueued_at 单调不减）：同级 FCFS 不被老化扰动。
                dispatch_idx = None
                for i, entry in enumerate(self._run_queue):
                    prio, sname, atype, enqueued_at = entry
                    if (sname, atype) in suppressed:
                        continue
                    # 槽位占满时实现车道条目不可派发（评审/并行出题条目放行，
                    # 1.5b + add-verify-lane-throughput 2.1）
                    if slots_full and atype not in self._SLOT_EXEMPT_LANE_TYPES:
                        continue
                    if self._pm._effective_priority(prio, enqueued_at, now) != target_prio:
                        continue
                    # 状态守卫与闸门链：复用 best_valid_prio 扫描的同轮判定
                    # 缓存（code-review item 806ba20de85f；判定口径仍同一
                    # 单一落点 _queue_entry_ready，code-review item
                    # 409a6ced70ce）。两扫描过滤条件一致，走到这里的条目必在
                    # 首轮缓存中，判定结果与原重复判定等价。
                    spec, ready = scan_verdicts[(sname, atype)]
                    if not spec or not ready:
                        continue
                    dispatch_idx = i
                    break

                if dispatch_idx is None:
                    # 目标档位无就绪条目（可能有但状态不合法），本轮不派发
                    return

                # evo-fix-transient-break-unseal-backoff 1.2：解封节奏单条准入
                # （探针观察窗仅首条=探针准入；错峰放行按 stagger 节拍每拍一条）。
                # 锁内、pop 前消费——准入失败即整轮返回，绝不在同一拍连环 pop
                # （MUST NOT 同拍全量放出）。fail-open：engine 门面异常放行。
                if not self._pm._transient_unseal_admit():
                    return
                entry_to_dispatch = self._run_queue.pop(dispatch_idx)
                # 先解包条目（agent_type 供下游分流，priority 供 finally 释放）。
                # 必须在锁内完成——解锁后 _run_queue 可被其他线程修改，
                # 但 entry_to_dispatch 已 pop，变量局部安全。
                priority, spec_name, agent_type, my_enqueued_at = entry_to_dispatch
                # 统一绑定 base_prio（活动追踪记 base 原值：活动任务不老化，
                # spec Scenario: 持久运行的 P4 不会被降级，min_active 语义不变）。
                # 与 priority 同值；出锁段闸门异常兜底按 agent_type 分流回滚，
                # 豁免车道（spec-review/planner-plan）不使用该值
                # （code-review item 76330e41877d：原仅 else 分支绑定，异常兜底
                # 无条件引用对豁免车道存在 NameError 风险）。
                base_prio = priority
                # verify 单飞出队分流命中标记（锁内置位，出锁段留痕后丢弃条目）。
                verify_flight_rejected = False
                if agent_type == "spec-review":
                    # 评审条目不占实现车道槽位（design D2）：MUST NOT 增减
                    # _active_runs、MUST NOT 写 _active_priority_counts /
                    # _active_priorities（否则以「更重要的活动任务」身份挤压
                    # 实现派发）；独立登记 _active_reviews 供同 spec 防重派与
                    # 可观测。释放时点见 _run_spec_review_worker（MUST NOT 晚于
                    # 四步链锚点 reviewer_run 落盘，design D4 重入安全性）。
                    self._active_reviews.add(spec_name)
                    active_count = self._active_runs
                elif agent_type == "planner-plan":
                    # 并行出题条目不占实现车道槽位（add-verify-lane-throughput
                    # 2.1，spec Scenario「在飞期间不计入实现槽位计数」）：登记
                    # _active_parallel_plans 供豁免上限计量与防重派，MUST NOT
                    # 增减 _active_runs/_active_priorities。释放点见 worker
                    # finally 幂等兜底。
                    self._active_parallel_plans.add(spec_name)
                    active_count = self._active_runs
                else:
                    # verify 单飞出队分流守卫（evo-add-verify-dispatch-single-flight
                    # 1.1）：锁内原子「查在飞→命中即拒绝留痕并丢弃条目→未命中即
                    # 登记」。查/登记与 pop 同 _queue_lock 锁段完成——登记延后到
                    # 线程启动的「派发成功」点（历史 :930-937 形态）会在「已出队
                    # 未登记」窗口放进第二路（入队双查与出队查双双落空）。
                    # 命中路径：条目已 pop 即丢弃（不重新入队，拒绝优于排队）；
                    # 槽位从未递增（递增在本分支下方才发生），故只退还本拍准入
                    # （recredit），MUST NOT 调 _rollback_dispatch_slot（那会把
                    # _active_runs 减成负数）。
                    if agent_type == "verifier" and spec_name in self._active_verifies:
                        self._pm._transient_unseal_recredit()
                        verify_flight_rejected = True
                        active_count = self._active_runs
                    else:
                        if agent_type == "verifier":
                            self._active_verifies.add(spec_name)
                        self._active_runs += 1
                        self._active_priority_counts[base_prio] = (
                            self._active_priority_counts.get(base_prio, 0) + 1
                        )
                        self._active_priorities.add(base_prio)
                        active_count = self._active_runs

            if verify_flight_rejected:
                # verify 单飞出队分流命中（evo-add-verify-dispatch-single-flight
                # 1.1）：结构化留痕（对齐下方「Dispatching」打印点口径）后丢弃
                # 条目继续扫描后队（拦截自己 ≠ 阻塞他人，条目不入队无热旋）。
                self._pm.logger.warning(
                    "pm_engine",
                    f"verify 单飞守卫：'{spec_name}' 已有在飞验证，拒绝重复派发"
                    f"并丢弃条目",
                    {"spec": spec_name, "agent_type": agent_type,
                     "guard": "verify_single_flight", "path": "dequeue",
                     "active_runs": active_count},
                )
                continue

            # ── 派发前同源草案收敛检查（evo-deliverable-declaration-drift-align
            # D3，同口径兜底）──
            # _on_spec_ready 只覆盖 4 条主入口；定时重派与恢复车道直入队列的条目
            # （该文件 :604 注释点名的旁路）不经它，故在此候选筛选处以同口径等价
            # 过谓词：本 spec 目录自身含 SUPERSEDED.md（已被取代）→ 移除队列条目、
            # 置 blocked（error=同源草案收敛义务未满足，附 SUPERSEDED.md 路径），
            # 继续扫描后队（拦截自己 ≠ 阻塞他人）。被 SUPERSEDED.md 显式点名为
            # 生效落点的一侧（自身无 SUPERSEDED.md）MUST NOT 被拦截。检查异常
            # fail-open：不因检查故障阻塞派发（与其它派发前闸门 fail-open 一致）。
            # 1.7/1.10：本闸门以 agent_type ∈ (implementer, fast-track) 为入口
            # ，spec-review 天然不进入，无需额外排除。
            # ── 出锁段闸门异常兜底（code-review item 8343d5e56846）──────
            # 条目 pop 后槽位已在锁内递增（_active_runs/_active_priority_counts），
            # 出锁后的收敛拦截写盘 / 守卫三 / 预算 / 内容闸门 / transition 各段
            # 此前无异常保护：任一 STATE 写盘或判定抛异常会跳过全部回滚点，该
            # 条目占用的并发槽位永久泄漏（max_concurrent 逐次侵蚀 → 派发停摆），
            # 异常还会沿 _process_queue 传播进调用方（worker finally / 定时器
            # 线程）。统一在此兜底：异常路径退还准入 + 回滚槽位（条目重新入队）、
            # 本调用 suppressed 抑制防同条目热旋；正常路径行为与成功时序不变，
            # 各分支既有清理逻辑不动。
            try:
                if agent_type in ("implementer", "fast-track"):
                    try:
                        convergence = self._pm._check_superseded_convergence(spec_name)
                    except Exception as e:
                        convergence = {"blocked": False, "error": None}
                        self._pm.logger.warning(
                            "pm_engine",
                            f"同源草案收敛检查异常 '{spec_name}'（fail-open 放行）: {e}",
                        )
                    if convergence.get("blocked"):
                        self._pm.state_machine.update_spec(
                            spec_name,
                            {
                                "status": "blocked",
                                "tester_run": None,
                                "error": convergence.get("error") or "同源草案收敛义务未满足",
                            },
                        )
                        self._pm.logger.error(
                            "pm_engine",
                            f"同源草案收敛义务拦截派发 '{spec_name}'（含 SUPERSEDED.md，"
                            f"{convergence.get('superseded_path')}）— 已 blocked，"
                            f"收敛后恢复；移除队列条目继续扫描",
                        )
                        with self._queue_lock:
                            # 收敛拦截：移除条目（不重新入队）、释放槽位
                            # 准入已消费即零 run 启动，MUST 退还（item d2e6133109ff）。
                            self._pm._transient_unseal_recredit()
                            self._rollback_dispatch_slot(base_prio)
                        continue

                # ── 守卫三：派发互斥（fix-repair-lane-dedup / design 守卫三，legacy）──
                # 仅存量 fix-* SPEC 可达（非 fix 父 SPEC 现已走原地打回，不进入此分支）。
                # fix spec 实现器派发前检查同根兄弟是否存在活跃修复活动；
                # 存在则回滚 entry 到队列、跳过本轮派发（先到先得，后到抑制）。
                # 被抑制条目记入 suppressed 后继续扫描后队：抑制自己 ≠ 阻塞他人。
                if agent_type == "implementer" and self._pm._is_fix_spec(spec_name):
                    carrier = self._pm._sibling_repair_active(spec_name, my_enqueued_at=my_enqueued_at)
                    if carrier:
                        # 回滚：把已 pop 的 entry 放回队列
                        with self._queue_lock:
                            # 准入已消费即零 run 启动，MUST 退还（item d2e6133109ff）。
                            self._pm._transient_unseal_recredit()
                            self._rollback_dispatch_slot(base_prio, entry_to_dispatch)
                        self._pm.logger.info(
                            "pm_engine",
                            f"守卫三：'{spec_name}' 同根兄弟 '{carrier}' 存在活跃修复"
                            f"——跳过本轮派发，保持 ready",
                        )
                        suppressed.add((spec_name, agent_type))
                        continue

                # Update state to in-progress
                if agent_type == "implementer":
                    # add-fail-counter-budget D2：派发前预算闸门。
                    # 已启动（_run_agent_worker 内已自增计数）的 run 不受此处影响，
                    # 仍会跑完 merge；本闸门只在「即将开启新一轮」时校验，避免无限重派。
                    # 闸门触发 → 不派发、状态置 blocked + 人工裁决告警，并回滚队列占用。
                    # 1.7：spec-review 不经本闸门（评审不消耗实现预算）；1.10：回滚
                    # 点只对 implementer 可达，不会误减评审的 _active_reviews。
                    if self._pm._check_impl_budget_exhausted(spec_name):
                        with self._queue_lock:
                            # 准入已在本拍 pop 前消费（code-review item
                            # d2e6133109ff）：条目回滚即零 run 启动，MUST 退还
                            # （探针名额/错峰节拍），否则空烧至观察窗空过/硬过期。
                            self._pm._transient_unseal_recredit()
                            self._rollback_dispatch_slot(base_prio, entry_to_dispatch)
                        continue
                    # add-spec-content-integrity-gate：派发前内容完整性闸门。
                    # 空 spec 目录（无 proposal/design/tasks/specs）冻结派发，
                    # 不烧预算；与预算闸门同层并列，复用回滚范式。
                    if self._pm._check_spec_content_missing(spec_name):
                        with self._queue_lock:
                            # 准入已在本拍 pop 前消费（code-review item
                            # d2e6133109ff）：条目回滚即零 run 启动，MUST 退还
                            # （探针名额/错峰节拍），否则空烧至观察窗空过/硬过期。
                            self._pm._transient_unseal_recredit()
                            self._rollback_dispatch_slot(base_prio, entry_to_dispatch)
                        # 命中即本调用抑制该条目重选（守卫三同款，抑制自己 ≠
                        # 阻塞他人）。「已交付未落盘」形态不冻结 spec（仍 ready），
                        # 无抑制时同一调用内 pop→命中→回滚入队→再 pop 无限热旋，
                        # 调用方线程挂死（code-review item ff79ebdb12d6）。
                        suppressed.add((spec_name, agent_type))
                        continue
                    # 修复重派时状态已是 implementing（同态转换非法），跳过 transition
                    cur_status = (self._pm.state_machine.read_one(spec_name) or {}).get("status")
                    if cur_status != "implementing":
                        # fix-observability-gaps 2.2：自动派发来源（run 尚未派发，
                        # trigger_run_id 暂无，派发完成后由收口路径写 run context）
                        self._pm.state_machine.transition(
                            spec_name, "implementing",
                            trigger_run_id=None, agent_type="implementer", channel="auto",
                        )
                elif agent_type == "fast-track":
                    # fast-track：与 implementer 同语义，派发即进入 implementing；
                    # 失败打回重派时状态已是 implementing，跳过同态转换。
                    if self._pm._check_impl_budget_exhausted(spec_name):
                        with self._queue_lock:
                            # 准入已在本拍 pop 前消费（code-review item
                            # d2e6133109ff）：条目回滚即零 run 启动，MUST 退还
                            # （探针名额/错峰节拍），否则空烧至观察窗空过/硬过期。
                            self._pm._transient_unseal_recredit()
                            self._rollback_dispatch_slot(base_prio, entry_to_dispatch)
                        continue
                    # add-spec-content-integrity-gate：内容完整性闸门（fast-track 分支，
                    # 与 implementer 同层并列；空 spec 冻结派发，不烧预算）。
                    if self._pm._check_spec_content_missing(spec_name):
                        with self._queue_lock:
                            # 准入已在本拍 pop 前消费（code-review item
                            # d2e6133109ff）：条目回滚即零 run 启动，MUST 退还
                            # （探针名额/错峰节拍），否则空烧至观察窗空过/硬过期。
                            self._pm._transient_unseal_recredit()
                            self._rollback_dispatch_slot(base_prio, entry_to_dispatch)
                        # 命中即本调用抑制该条目重选（守卫三同款，抑制自己 ≠
                        # 阻塞他人）。「已交付未落盘」形态不冻结 spec（仍 ready），
                        # 无抑制时同一调用内 pop→命中→回滚入队→再 pop 无限热旋，
                        # 调用方线程挂死（code-review item ff79ebdb12d6）。
                        suppressed.add((spec_name, agent_type))
                        continue
                    cur_status = (self._pm.state_machine.read_one(spec_name) or {}).get("status")
                    if cur_status != "implementing":
                        # fix-observability-gaps 2.2：fast-track 自动派发来源
                        self._pm.state_machine.transition(
                            spec_name, "implementing",
                            trigger_run_id=None, agent_type="fast-track", channel="auto",
                        )
                elif agent_type == "verifier":
                    # fix-observability-gaps 2.2：verifier 自动派发来源
                    self._pm.state_machine.transition(
                        spec_name, "testing",
                        trigger_run_id=None, agent_type="verifier", channel="auto",
                    )
                elif agent_type == "planner-plan":
                    # 并行出题条目不迁移 spec 状态（add-verify-lane-throughput 1.1）：
                    # 出题与实现并行在飞，spec 状态机由实现车道驱动；此处零状态写。
                    # 预算/内容完整性闸门同 spec-review 逻辑不适用（出题不消耗实现
                    # 预算，无实现内容可校验）。
                    pass
                elif agent_type == "spec-review":
                    # 评审条目状态推进（fix-spec-review-blocking-dispatch 1.6）：
                    # 不调用 transition——状态已由晋升链（promote_drafted 的
                    # reviewing 分支 / rejected 复评 / re_review）置为 reviewing，
                    # 派发处只登记在飞集合（上面出队分流已 add）并记录派发日志
                    # （下方统一日志）。预算闸门/内容完整性闸门/同源草案收敛/
                    # 守卫三均以 agent_type ∈ (implementer, fast-track) 为入口，
                    # 评审条目不进入这些同步闸门及其回滚点（1.7/1.10：评审不消耗
                    # 实现预算，无实现内容可校验），也就不会误减 _active_runs。
                    pass
            except Exception as e:
                # 记账必然闭合：先退还准入再回滚槽位（条目重新入队待下轮重派），
                # suppressed 抑制本调用内重试（抑制自己 ≠ 阻塞他人，守卫三同款）。
                # 按 agent_type 分流（code-review item 76330e41877d）：实现车道
                # （implementer/fast-track/verifier，锁内已递增 _active_runs /
                # 档位计数）回滚槽位记账；豁免车道（spec-review/planner-plan）
                # 从不递增 _active_runs，调 _rollback_dispatch_slot 会把
                # _active_runs 反向减成负数，只退还准入并摘除各自在飞登记。
                with self._queue_lock:
                    self._pm._transient_unseal_recredit()
                    if agent_type in ("implementer", "fast-track", "verifier"):
                        if agent_type == "verifier":
                            # verify 单飞在飞摘除（evo-add-verify-dispatch-single-
                            # flight 1.1）：闸门异常/线程启动失败路径与前置登记
                            # 严格互逆（对齐 _active_reviews 分流回滚处置）。
                            self._active_verifies.discard(spec_name)
                        self._rollback_dispatch_slot(base_prio, entry_to_dispatch)
                    elif agent_type == "spec-review":
                        self._active_reviews.discard(spec_name)
                    elif agent_type == "planner-plan":
                        self._active_parallel_plans.discard(spec_name)
                suppressed.add((spec_name, agent_type))
                self._pm.logger.warning(
                    "pm_engine",
                    f"派发闸门处理异常 '{spec_name}' ({agent_type}) — 已回滚槽位"
                    f"记账并保留条目: {e}",
                )
                continue

            self._pm.logger.info(
                "pm_engine",
                f"Dispatching {agent_type} for '{spec_name}' (P{priority})",
                {"active_runs": active_count},
            )

            # code-review item 186ea8df1cb1：条目 pop、槽位/在飞登记与准入消费
            # 均已在锁内完成，而释放只在线程体 finally——Thread 构造/start 失败
            # （如环境性 RuntimeError can't start new thread）时 finally 永不执行：
            # 实现车道槽位只增不减、max_concurrent 逐次侵蚀至派发停摆（出锁段
            # 闸门异常兜底注释描述的同型故障），评审/出题车道在飞登记残留使
            # reviewer_in_flight / 豁免上限判据恒真、该 spec 条目被永久顺延。
            # 对齐 repair_lane._dispatch_repair_lane（code-review item
            # 94d6ad914d0b）与本文件 _start_impl_ocr_lane（b52d9c1760b6）的守卫
            # 形态：捕获失败、锁内退还准入并按 agent_type 分流回滚（与出锁段
            # 异常兜底同一分流口径，回滚与前置登记严格互逆），suppressed 抑制
            # 本调用内重选防热旋，条目重新入队待下轮重派。
            try:
                t = threading.Thread(
                    target=self._pm._run_agent_worker,
                    args=(spec_name, agent_type, priority),
                    daemon=True,
                    name=agent_worker_thread_name(spec_name, agent_type),
                )
                t.start()
            except Exception as e:  # noqa: BLE001 — 环境性启动失败按「未派发」处置
                with self._queue_lock:
                    self._pm._transient_unseal_recredit()
                    if agent_type in ("implementer", "fast-track", "verifier"):
                        if agent_type == "verifier":
                            # verify 单飞在飞摘除（evo-add-verify-dispatch-single-
                            # flight 1.1）：闸门异常/线程启动失败路径与前置登记
                            # 严格互逆（对齐 _active_reviews 分流回滚处置）。
                            self._active_verifies.discard(spec_name)
                        self._rollback_dispatch_slot(base_prio, entry_to_dispatch)
                    elif agent_type == "spec-review":
                        self._active_reviews.discard(spec_name)
                    elif agent_type == "planner-plan":
                        self._active_parallel_plans.discard(spec_name)
                suppressed.add((spec_name, agent_type))
                self._pm.logger.warning(
                    "pm_engine",
                    f"worker 线程启动失败 '{spec_name}' ({agent_type}) — 已回滚"
                    f"槽位记账并保留条目: {type(e).__name__}: {e}",
                )
                continue

    def _run_agent_worker(self, spec_name: str, agent_type: str, priority: int):
        """Worker thread body: run the agent and handle result.

        finally 按 agent_type 分流释放（详见 finally 内分流注释）：实现车道减
        _active_runs 并按档位摘除 _active_priorities；spec-review /
        planner-plan 车道从不递增 _active_runs，仅摘除各自在飞登记
        （_active_reviews / _active_parallel_plans）。各车道均重新触发队列
        处理，异常路径同样释放。
        priority 参数仅实现车道用于 finally 中从 _active_priorities 移除对应档位。
        """
        try:
            if agent_type == "spec-review":
                # ── spec-review 分支（fix-spec-review-blocking-dispatch 1.8）──
                # 评审 run 与 implementer 同构：在独立 worker 线程执行，调用方
                # （_on_spec_reviewing）入队后立即返回。四步链（锚点落盘 → 快照
                # → 执行 → 机械收口）保留在 dispatch_review 内，与本线程同一调用
                # 栈闭合（收口依赖本轮 attempt 的 run_started_at 做结果新鲜度
                # 校验，design D7）。异常收口分两层（design 风险段）：
                #   ① 四步链内部异常已由 dispatch_review 内 except 自吞并走
                #      _handle_review_failure（重试/冻结），行为与改造前逐字一致；
                #   ② 四步链之外异常（构造失败/快照路径异常）落本分支 except：
                #      清 reviewer_run、保持 reviewing、重新入队（spec-review-
                #      recovery spec Scenario「worker 内异常走统一回滚」），
                #      MUST NOT 只记日志了事。
                self._run_spec_review_worker(spec_name)

            elif agent_type == "fast-track":
                # ── fast-track 单 run 全包：实现 → 场景设计 → 验证 → 判定 ──
                # 预算与 worktree 语义与 implementer 一致（impl- run_id/分支前缀），
                # 结果处理走 _run_fast_track_worker（守卫 + 硬校验 + 状态推进）。
                # ── 派发前规模预检（add-fast-track-scale-precheck）──────────
                # 大任务面 spec（tasks.md 任务条数/交付物面超阈）不再按统一档
                # 派发：full 档降级完整模式（implementer 车道），higher 档写入
                # 规模档位标记供 runner 超时监督提高 extension 上限。预检失败
                # 保守低档放行（design D2，不阻断派发）。总开关
                # agents.scale_precheck.enabled 关闭时预检返回 "disabled"，
                # 两档动作均不执行（回到预检上线前行为）。
                scale, tier = self._fast_track_scale_precheck(spec_name)
                if tier == "full":
                    # 降级完整模式：改写 .spec.yaml mode → full + 状态回滚 ready
                    # + 重新入队 implementer；本次不启动 fast-track run、不递增预算。
                    # （fix-fasttrack-recovery-resume D4）此处早退于续做判定**之前**，
                    # MUST NOT 新增任何锚点写入/清除动作——branch/implementer_run 与
                    # _recovery_resume 标记原样留给随后的 implementer 派发消费（其
                    # 分支本就会正确消费续做标记）。
                    self._downgrade_fast_track_scale(spec_name, scale)
                    return
                # higher 档写标记；其余档位仅在**存量标记存在**时清除——否则
                # 「改版后重算降档」或「开关关闭」时旧 higher 标记会继续抬高
                # extension 上限（liveness 只按标记值判定，不重算规模）。无标记
                # 的常态路径不写键，避免 STATE.md 堆积无意义的 null 行。
                try:
                    _prev_tier = (
                        self._pm.state_machine.read_one(spec_name) or {}
                    ).get("_fast_track_scale_tier")
                    if tier == "higher":
                        self._pm.state_machine.update_spec(
                            spec_name, {"_fast_track_scale_tier": "higher"}
                        )
                    elif _prev_tier:
                        self._pm.state_machine.update_spec(
                            spec_name, {"_fast_track_scale_tier": None}
                        )
                except Exception as e:
                    self._pm.logger.warning(
                        "pm_engine",
                        f"fast-track 规模档位标记写入失败 '{spec_name}'（非阻塞）: {e}",
                    )
                self._pm._increment_impl_run_budget_used(spec_name)
                # ── 中断恢复保留续做（interrupt-recovery-preserve D4/D5）──
                # 本段与下方 implementer 分支的 _recovery_resume 消费序列**同源**
                # （interrupt-recovery-preserve D4/D5 / fix-recovery-branch-anchor D1）；
                # 两处结构改动 MUST 同步（见 implementer 分支的反向引用注释）。
                # recovery 保留的 spec（_recovery_resume 标记 + 保留分支）：在既有
                # 分支的 worktree 内 resume 续做（claude --resume 断点续跑），
                # 而非从零新建分支。载体三态经 wm.resolve_resume_site
                # （is_available 单源）解析：在场原地 / 缺失重建 / 不可用降级
                # 为普通全新派发。标记一次性消费：派发后清空，防后续 full_scan
                # 反复尝试续做。清锚点 MUST 在续做判定**之后**、仅 resume_wt
                # is None 时执行（续做命中时旧锚点正是本轮要使用的保留分支）。
                # [fenix-ignore:25c99379be14] 重复已由「MUST 同步」注释钉住、recovery 形参差异为 fast-track D6 有意设计；清锚点半段两处分支数量（单条件合并一次更新 vs 三段独立条件更新）、异常路径（try/except 吞异常 vs 不捕获向上传播）与字段集（implementer 独有 task-gate 计数清零）均不同，lane 参数无法在行为逐条等价前提下确定性表达，提取风险大于收益。
                wm = self._pm.agent_runner.worktree_manager
                resume_wt = None
                dispatch_entry = self._pm.state_machine.read_one(spec_name) or {}
                resume_branch = (
                    dispatch_entry.get("branch") if dispatch_entry.get("_recovery_resume") else None
                )
                if resume_branch:
                    site = wm.resolve_resume_site(spec_name, resume_branch)
                    if site[0] is not None:
                        resume_wt = site[0]
                    else:
                        self._pm.logger.warning(
                            "pm_engine",
                            f"Resume site unavailable for '{spec_name}' "
                            f"(branch '{resume_branch}') — degrade to fresh dispatch",
                        )
                if dispatch_entry.get("_recovery_resume"):
                    self._pm.state_machine.update_spec(spec_name, {"_recovery_resume": None})
                if resume_wt is not None:
                    self._pm.logger.info(
                        "pm_engine",
                        f"Resume dispatch for '{spec_name}' on preserved branch "
                        f"'{resume_branch}' (worktree {resume_wt})",
                    )
                    # 继承痕迹登记（prompt 注入恢复续做说明，interrupt-recovery-preserve
                    # 2.3 / fix-fasttrack-recovery-resume 3.2c）。recovery=True 携带
                    # 恢复来源标记——_active_reuse 同时被 _take_reusable_worktree /
                    # 跨 attempt 复用写入，无来源判据会把「曾因 daemon 重启被中断」
                    # 的错误归因注入每次普通重派轮（design D6）。
                    try:
                        wm.mark_reused(spec_name, resume_wt, resume_branch or "", recovery=True)
                    except Exception as e:
                        self._pm.logger.warning(
                            "pm_engine",
                            f"mark_reused for resume '{spec_name}' failed（非阻塞）: {e}",
                        )
                # ── 新轮次派发前清除旧锚点（fix-recovery-branch-anchor D1）──
                # 仅**未命中续做**（resume_wt is None：无标记 / 载体解析降级 /
                # 零提交）的全新派发才清除。fast-track 车道同 implementer 语义：
                # spec 可能经 repair lane（_run_repair_worker 为 fast-track spec
                # 同样写 branch/标记）或 fallback 留下陈旧 branch/implementer_run，
                # 新一轮在飞期间不得被恢复链当作可保留锚点。注意：续做命中时
                # MUST NOT 执行本段——不清除正是 state_machine 保全的可续做锚点
                # 能存活到派发当刻的前提（fix-fasttrack-recovery-resume 事故实证，
                # 2026-09-18：无条件清除使恢复保全的分支被就地抹除）。陈旧
                # _repair_awaiting_remerge 续做命中时保持原值交由后续流程处置。
                # _fast_track_scale_tier 不属「本轮锚点」，写入保持原位不动。
                if resume_wt is None:
                    try:
                        if (
                            dispatch_entry.get("branch")
                            or dispatch_entry.get("implementer_run")
                            or dispatch_entry.get("_repair_awaiting_remerge")
                        ):
                            self._pm.state_machine.update_spec(
                                spec_name,
                                {
                                    "branch": None,
                                    "implementer_run": None,
                                    "_repair_awaiting_remerge": False,
                                },
                            )
                            self._pm.logger.info(
                                "pm_engine",
                                f"新轮次派发清除旧锚点 '{spec_name}': "
                                f"branch={dispatch_entry.get('branch')}, "
                                f"implementer_run={dispatch_entry.get('implementer_run')}",
                            )
                    except Exception as e:
                        self._pm.logger.warning(
                            "pm_engine",
                            f"fast-track 新轮次清除旧锚点失败 '{spec_name}'" f"（非阻塞）: {e}",
                        )
                self._run_fast_track_worker(spec_name, pre_wt_path=resume_wt)

            elif agent_type == "implementer":
                # add-fail-counter-budget D2：实现 run 启动即递增预算计数并持久化
                # （跨重启有效）。已启动的 run 即使随后触发预算闸门也会照常跑完 merge
                # （沉没成本不浪费），闸门只阻止「新一轮」自动重派。
                self._pm._increment_impl_run_budget_used(spec_name)
                wm = self._pm.agent_runner.worktree_manager
                # 派发前把 spec 目录提交进主树（fix-merge-back-deadlock 根因修复）：
                # 消除「spec 在主树 untracked + 分支 commit 同名路径」导致的 merge-back 冲突。
                wm.ensure_spec_committed(spec_name)
                # ── 中断恢复保留续做（interrupt-recovery-preserve D4/D5）──
                # recovery 保留的 spec（_recovery_resume 标记 + 保留分支）：在既有
                # 分支的 worktree 内 resume 续做（claude --resume 断点续跑），
                # 而非从零新建分支。载体三态经 wm.resolve_resume_site
                # （is_available 单源）解析：在场原地 / 缺失重建 / 不可用降级
                # 为普通全新派发。标记一次性消费：派发后清空，防后续 full_scan
                # 反复尝试续做。
                # （fix-fasttrack-recovery-resume 1.4 反向引用）本段消费序列与
                # 上方 fast-track 分支的续做判定段同源——两处结构改动 MUST 同步，
                # 见 fast-track 分支的对照注释。
                resume_wt = None
                dispatch_entry = self._pm.state_machine.read_one(spec_name) or {}
                resume_branch = (
                    dispatch_entry.get("branch") if dispatch_entry.get("_recovery_resume") else None
                )
                if resume_branch:
                    site = wm.resolve_resume_site(spec_name, resume_branch)
                    if site[0] is not None:
                        resume_wt = site[0]
                    else:
                        self._pm.logger.warning(
                            "pm_engine",
                            f"Resume site unavailable for '{spec_name}' "
                            f"(branch '{resume_branch}') — degrade to fresh dispatch",
                        )
                if dispatch_entry.get("_recovery_resume"):
                    self._pm.state_machine.update_spec(spec_name, {"_recovery_resume": None})
                if resume_wt is not None:
                    self._pm.logger.info(
                        "pm_engine",
                        f"Resume dispatch for '{spec_name}' on preserved branch "
                        f"'{resume_branch}' (worktree {resume_wt})",
                    )
                    # 继承痕迹登记（prompt 注入恢复续做说明，interrupt-recovery-preserve
                    # 2.3 / fix-fasttrack-recovery-resume 3.2c）。recovery=True 携带
                    # 恢复来源标记，与 fast-track 分支同源段对齐——_active_reuse
                    # 同时被 _take_reusable_worktree / 跨 attempt 复用写入，无来源
                    # 判据会把「曾因 daemon 重启被中断」的错误归因注入每次普通重派轮
                    # （design D6）。
                    try:
                        wm.mark_reused(spec_name, resume_wt, resume_branch or "", recovery=True)
                    except Exception as e:
                        self._pm.logger.warning(
                            "pm_engine",
                            f"mark_reused for resume '{spec_name}' failed（非阻塞）: {e}",
                        )
                # ── 新轮次派发前清除上一轮锚点（fix-recovery-branch-anchor D1）──
                # 非 _recovery_resume 续做的全新派发：旧的 branch/implementer_run
                # 锚点来自上一轮已放弃的 run，若不清除，_recovery_preserve_spec
                # 第一层（STATE.branch）会在下一轮在飞期间压过本轮载体，导致
                # daemon 重启时保留并续做陈旧分支、整轮丢弃当前在飞成果。
                if resume_wt is None:
                    old_branch = dispatch_entry.get("branch")
                    old_impl_run = dispatch_entry.get("implementer_run")
                    if old_branch or old_impl_run:
                        self._pm.state_machine.update_spec(
                            spec_name, {"branch": None, "implementer_run": None}
                        )
                        self._pm.logger.info(
                            "pm_engine",
                            f"新轮次派发清除旧锚点 '{spec_name}': "
                            f"branch={old_branch}, "
                            f"implementer_run={old_impl_run}",
                        )
                    # 陈旧「待 re-merge」标记同步失效（fix-recovery-branch-anchor
                    # D3）：上一轮失败链若曾写 _repair_awaiting_remerge，新一轮
                    # 在飞期间重启不得对尚未完工的新分支执行 re-merge。
                    if dispatch_entry.get("_repair_awaiting_remerge"):
                        self._pm.state_machine.update_spec(
                            spec_name, {"_repair_awaiting_remerge": False}
                        )
                    # 全新派发清零 task-gate 拒绝计数（改进①）：只卡第一次的计数
                    # 只应反映「同一轮被连续拒回」；全新 implementing 轮次（含
                    # 上轮已降级放行后的再派发）从零开始，避免陈旧计数误降级。
                    # （TASK_GATE_REJECTIONS_FIELD 已模块顶部导入，删除此处的
                    # 冗余函数内 import——code-review item 3218887178b8/35c865a3a00f）
                    prev_gate_rejections = self._parse_int_field(
                        dispatch_entry, TASK_GATE_REJECTIONS_FIELD, 0
                    )
                    if prev_gate_rejections > 0:
                        self._pm.state_machine.update_spec(
                            spec_name, {TASK_GATE_REJECTIONS_FIELD: 0}
                        )
                # ── 派发时落可信基线快照（add-declaration-relocation-protocol D3）──
                # 把当前**主树**声明集合快照到 .fenix/verify-progress/<spec>/
                # declaration-baseline.json（worktree 之外，实现 Agent 路径不写入），
                # 作为收工守卫收缩防护（check_declaration_shrinkage）的独立参照系。
                # 写入异常仅 WARNING 不阻塞派发（该轮收缩防护降级保守，见 2.4）。
                try:
                    from core.deliverables import snapshot_declaration_baseline

                    snapshot_declaration_baseline(
                        spec_name,
                        f"dispatch-{int(time.time())}",
                        self._pm.project_root,
                    )
                except Exception as e:
                    self._pm.logger.warning(
                        "pm_engine",
                        f"基线快照落盘失败 '{spec_name}'（仅 WARNING 不阻塞派发）: {e}",
                    )
                # 主树 stash 已收拢进 merge_back_from_branch 的 guard 原子段
                # （fix-autostash-orphans）：锁内 stash→merge→pop，不再依赖
                # 派发前 stash + 成功路径 pop 的长窗口配对（曾致 7 次改动滞留 stash）。
                result = self._pm.agent_runner.run_implementer(spec_name, pre_wt_path=resume_wt)
                # Read .fenix-run-result.json (worktree first, project root fallback)
                # to determine true status — file is more authoritative than
                # process exit code for semantic success/error.
                impl_result = self._pm._read_implementer_result(spec_name)
                impl_status = None
                impl_error = None
                if impl_result:
                    impl_status = impl_result.get("status")
                    if impl_status == "error":
                        impl_error = impl_result.get("error") or result.error
                    elif impl_status == "partial":
                        # fix-impl-tasks-completion-gate D6：partial 是「诚实申报未完成」
                        # 的合法终态——is_success 为假、MUST NOT 进入 implemented。
                        # 失败归因 MUST 非空且由 unfinished 清单与缺口 id 构成，MUST NOT
                        # 沿用为 None 的 result.error（成功进程 error=None，沿用会产出
                        # 「失败但无归因」的空壳处置，违背 admin 处置非空壳约定）。
                        # 归因文案同时是重派 prompt 的缺口注入来源。
                        impl_error = self._pm._partial_attribution(spec_name, impl_result, result)
                    elif impl_status != "success":
                        impl_error = result.error
                is_success = result.success and (impl_status is None or impl_status == "success")
                # ── 诚实退出收敛（unattainable，2026-09-16 改进② 补齐收敛路径）──
                # 实现者以 partial 收工且**缺口全部 ⊆ unattainable 申报**时，不该
                # 判失败重派：剩余任务客观上不可由 agent 完成（人工运维门控——需
                # 用户亲手重启 daemon / 审批 / 外部资源），重派 N 轮只会重复同一
                # 终局。修正前该豁免只接在 verified→done 门（engine._task_completion_
                # blocker），partial 在收敛路径一律 is_success=False → 无限重派烧预算
                # （2026-09-16 fix-dashboard-read-path-performance 实测：3 轮原地重试 +
                # 多次全新重派，$4.4，spec 在 implementing 悬置 43 分钟直至 admin 唤起）。
                # 部分未申报的缺口仍按失败处置（防 partial 洗白），走既有重试通道。
                honest_exit_gap: list = []
                if impl_status == "partial":
                    honest_exit_gap = self._honest_exit_gap(self._pm, spec_name, impl_result)
                if result.success and impl_status == "partial" and honest_exit_gap:
                    # 诚实退出收敛：不按失败重派，转正常成功收口（后续通用
                    # is_success 路径会写 impl-result 快照、过交付物/relint 门、
                    # merge-back 并 enqueue verifier）。人工待办告警与
                    # engine._task_completion_blocker 的诚实退出分支同文案，
                    # 使 /fenix-approve 环节可见「哪些任务交给了人工」。
                    self._pm.logger.warning(
                        "pm_engine",
                        f"诚实退出收敛 '{spec_name}'：partial 缺口全部 ⊆ unattainable "
                        f"申报 {honest_exit_gap} —— 不重派，按成功收口转验证",
                    )
                    impl_error = None
                    is_success = True
                    try:
                        self._pm._note_unattainable_todos(
                            spec_name, impl_result, honest_exit_gap)
                    except Exception as e:  # noqa: BLE001 — 非阻塞
                        self._pm.logger.debug(
                            "pm_engine",
                            f"unattainable 待办告警写入失败（不阻断收敛）: {e}",
                        )
                final_error = impl_error or result.error

                # ── 结构化诊断写入（fix-run-hang-amplification 2.3）──
                # run 终结时把终态类型 + 归因 + 已定性结论 + 已提交进度写入
                # spec 级 _impl_diagnosis 字段，供重派 attempt 继承（不再从零
                # 重复探测同一阻塞）。任何异常不阻塞主流程（诊断是附加物）。
                try:
                    self._record_impl_diagnosis(spec_name, result, impl_result, final_error)
                except Exception as e:
                    self._pm.logger.warning(
                        "pm_engine",
                        f"记录实现诊断失败 '{spec_name}'（非阻塞）: {e}",
                    )

                # ── 零变更成功哨（2026-08-28）─────────────────────────
                # 实现器宣称成功但分支零新提交且全程零 Edit/Write 工具调用
                # ＝ 疑似输出截断/空转（CLI 把截断包装成 result/success + exit 0，
                # is_error 三闸失明）。不合并、不推进状态，按失败重派；
                # 连续 3 次零变更 → blocked 交人工。
                if is_success and self._pm._implementer_zero_change(spec_name, result):
                    # ── 验证确认型 no-op 放行（2026-09-11 add-web-ui 事故原地修）──
                    # admin 把 env-blocked spec 复位 ready 而实现分支已 merge 进
                    # main 时，agent 验证确认「全部绿、无需改动」报成功是唯一正确
                    # 行为，被本哨误判空转 → 重派第二轮重蹈覆辙（$1.42 + 重建
                    # $1.30）。哨兵触发后先跑交付物守卫：交付物齐备 = 合法确认
                    # 完成，走正常成功收口（implemented → verifier）；
                    # 缺件仍按空转重派。守卫方法内自带无声明 spec 跳过。
                    # （分支零提交时 rev-list main..branch == 0 ⟺ 分支已并入 main，
                    # 无需另查 merge-base。）
                    if not self._pm._deliverable_gate_missing(spec_name, result):
                        self._pm.logger.warning(
                            "pm_engine",
                            f"零变更哨·确认型 no-op '{spec_name}' — 交付物齐备且分支"
                            f"零提交（已并入 main），走成功收口（不重派）"
                            f"run={result.run_id}",
                        )
                        # fix-observability-gaps 2.2：零变更哨成功收口，run context 可标注
                        # 收口前 ready 态兜底（code-review item 78ceeef7f56c）：与
                        # _finalize_merge_success 同口径（evo-spec-concurrency-
                        # flight-guard D3）——run 在飞期间评审收尾竞态把 status 回退
                        # 为 ready 时，先补记合法转移 ready→implementing 再推进
                        # implemented；否则 ready→implemented 被拒后仍会写
                        # implementer_run 并入队 verifier（status=ready 不满足
                        # (implemented, testing) 永不派发）。
                        self._pm._merge_ready_fallback(
                            spec_name,
                            result.run_id,
                            "implementer",
                            getattr(result, "branch", None),
                        )
                        self._pm.state_machine.transition(
                            spec_name, "implemented",
                            trigger_run_id=result.run_id,
                            agent_type="implementer", channel="auto",
                        )
                        self._pm.state_machine.update_spec(
                            spec_name,
                            {
                                "implementer_run": result.run_id,
                                "error": None,
                                "_zero_change_attempts": 0,
                            },
                        )
                        # （code-review item 85495e15ab27）确认型 no-op 分支同样落
                        # impl-result 快照（与 fast_track.py 确认型 no-op 同分支对齐）：
                        # 本分支 transition implemented 后直接入队 verifier，不经下方
                        # 通用成功路径的快照写点——快照缺失时 verified→done 门禁
                        # _task_completion_blocker 规则 3 在「共享结果文件已被其它
                        # spec 成功覆盖 + tasks.md 有未勾数字任务 + implementer_run
                        # 在场」组合下 fail-closed 误拦，spec 滞留 verified 需人工
                        # 解锁。写失败仅 WARNING 不阻塞（fail-open，与通用路径同口径）。
                        if impl_result is not None:
                            try:
                                self._pm._write_impl_result_snapshot(
                                    spec_name, impl_result
                                )
                            except Exception as e:
                                self._pm.logger.warning(
                                    "pm_engine",
                                    f"确认型 no-op impl-result 快照写入失败 "
                                    f"'{spec_name}'（非阻塞）: {e}",
                                )
                        self._enqueue_front(spec_name, "verifier")
                        return
                    spec_entry = self._pm.state_machine.read_one(spec_name) or {}
                    # _zero_change_attempts 锁内原子递增（code-review item
                    # 8eb2f7b9e6ad）：取写后值参与 attempts >= 3 判定与 error 文案，
                    # 下方 update_spec / freeze_for_human 不再并写该字段（对齐
                    # _retry_count 同型站点收口形态，防并发写回互相覆盖丢增量）
                    # ——原两段式「读 → 算 +1 → 绝对写回」读与写分处两次 STATE 锁
                    # 临界区，与 merge-only 重试定时器/WIP 周期消费者并发进入同一
                    # spec 时可丢一次递增，「连续 3 次零变更」冻结转人工晚一轮触发。
                    attempts = self._pm.state_machine.bump_counters(
                        spec_name, {"_zero_change_attempts": 1}
                    ).get("_zero_change_attempts", 0)
                    # fix-zero-change-blindspot：区分「真空转」与「有工作未提交」。
                    # cleanup 前取证的 worktree_dirty 非空 = agent 确实动过文件
                    # （如用 Bash 写文件而非 Edit/Write），只是没 commit——不是空转，
                    # 重派文案须指导 commit，避免把真实工作当空转误报。
                    dirty = list(getattr(result, "worktree_dirty", None) or [])
                    if dirty:
                        err_note = (
                            f"实现器报成功但分支零提交，worktree 有 "
                            f"{len(dirty)} 个未提交修改（清单见日志）——不是空转；"
                            f"重派时务必用 git commit 提交改动后再报完成"
                        )
                        self._pm.logger.warning(
                            "pm_engine",
                            f"零变更哨·未提交工作 '{spec_name}': {dirty[:10]}",
                        )
                    else:
                        err_note = (
                            "实现器零变更报成功（疑似输出截断/空转）— " "不合并不推进，重派实现"
                        )
                    updates: dict = {
                        "status": "ready",
                        "error": err_note + f"（第 {attempts} 次）",
                        # _zero_change_attempts 已由上方 bump_counters 原子递增落盘，
                        # 不再并写（防并发写回互相覆盖丢增量）
                    }
                    if attempts >= 3:
                        # fix-blocked-freeze-classification 3.1 同型收敛（code-review
                        # item 912ea4592630）：连续失败交人工收敛到 freeze_for_human
                        # 单一入口（frozen + 人工升级告警成对写入），与本文件同因
                        # 熔断 / 重试耗尽分支及 repair_lane._fallback_after_repair
                        # 同口径——原裸 status=blocked 既无 frozen 标记也无成对
                        # 告警，admin_monitor 的 blocked_stuck 豁免判据一条不占，
                        # 冷却期满会被按 stuck 自动召唤 admin run。error 内嵌
                        # 「原状态 X」供 parse_orig_status 解冻还原。
                        orig_status = spec_entry.get("status") or "implementing"
                        self._pm.state_machine.freeze_for_human(
                            spec_name,
                            error=(
                                f"原状态 {orig_status} · 实现器连续 {attempts} 次"
                                f"零变更报成功 — 已冻结转人工，需人工检查任务书/"
                                f"上下文/网关稳定性"
                            ),
                            signal_type="redispatch_loop_detected",
                            severity="major",
                            description=(
                                f"'{spec_name}' 连续 {attempts} 次零变更报成功"
                                f"（疑似输出截断/空转），自动重派终止——已冻结"
                                f"转人工处置"
                            ),
                            evidence=(
                                f"spec={spec_name}; zero_change_attempts={attempts}; "
                                f"run={result.run_id}"
                            ),
                            recommended_action=(
                                "检查任务书/上下文/网关稳定性；处置后解冻"
                                "（unfreeze_spec 自动清零计数）可重新获得自动"
                                "修复机会"
                            ),
                            alert_callback=self._pm._send_human_escalation_alert,
                            extra_updates={
                                # _zero_change_attempts 已由上方 bump_counters 原子
                                # 递增落盘，不再并写（防并发写回互相覆盖丢增量）
                                "tester_run": None,
                            },
                        )
                    else:
                        self._pm.state_machine.update_spec(spec_name, updates)
                    self._pm.logger.error(
                        "pm_engine",
                        f"零变更成功哨触发 '{spec_name}'（第 {attempts} 次）— "
                        f"run={result.run_id}",
                    )
                    if attempts < 3:
                        self._enqueue_front(spec_name, "implementer")
                    return

                # ── 交付物存在性守卫（add-implementer-deliverable-gate，D1/D3）──
                # 实现器宣称成功，但 SPEC 声明的核心交付物可能未真正落地
                # （v2-config-page 事故：agent 报成功但 config.json 未创建，0/11 验证全败）。
                # 在 merge 之前做纯文件系统存在性校验（校验基准为实现分支提交，
                # worktree 已在 run_implementer 内清理，仅分支留存），缺件则不合并、
                # 不推进状态，按失败重派并带精准缺件清单；连续 3 次封顶 → blocked 升级告警。
                if is_success:
                    missing = self._pm._deliverable_gate_missing(spec_name, result)
                    if missing:
                        # ── dispute 裁决通道（add-project-description 事故治理）──
                        # 实现 run 对缺件提出 deliverable-dispute 异议时不自动重派
                        # （误判场景重派必然同因失败，纯烧钱），blocked 交人工裁决。
                        # 质疑不得自动放行（防 agent 绕守卫），必须第三方裁决。
                        disputed = self._pm._disputed_deliverables(impl_result, missing)
                        # 机械预分类是否已全清放行（proceed）——True 时下方
                        # 短路 LLM 终审（code-review item 98b789430350）。
                        preclassified_proceed = False
                        if disputed:
                            # ── 争议分支漂移笔误机械对齐（evo-deliverable-declaration-drift-align）──
                            # 实现 run 已对缺件提出 deliverable-dispute 异议时，先试
                            # 漂移机械对齐（design D1/D2）：声明路径在主树与分支 HEAD
                            # 均缺 + git 历史命中（拆包/改名漂移特征）→ _locate_drift_target
                            # 候选定位，分支改动集合内包目录唯一候选且分支 HEAD 真实
                            # 存在 → 机械改写生效声明 + 审计 + 提交 + 守卫重跑全清 →
                            # 放行 merge（不 blocked）；零/多候选或任一环节异常 → fail-open
                            # 回退既有 blocked 待人工通道（与 _preclassify_stale 互斥：
                            # 异议形态不进入 _adjudicate_deliverable_missing，stale 通道
                            # 不可达——本轮三次 blocked 事故正落在这一段）。
                            drift_result = self._pm._preclassify_drift(
                                spec_name, result, impl_result, disputed, missing
                            )
                            if drift_result.get("action") == "fallback":
                                # 漂移通道 fail-open → 走既有孤儿预分类（deliverable-
                                # dispute-orphan-preclassify）：按 kind 分化的孤儿判定
                                # （声明残留：任务清单零出现 + 源码面 git grep 零引用）
                                # → 机械删除声明 + 审计 + 重跑守卫对账，spec 不 blocked；
                                # 非孤儿 → 维持 blocked 待人工。两类预分类按「历史命中
                                # 与否」天然分流（孤儿=零历史命中，漂移=历史命中），
                                # 同一轮同一 spec 只会被一条通道改写声明。
                                orphan_result = self._pm._preclassify_orphan(
                                    spec_name, result, impl_result, disputed, missing
                                )
                            else:
                                # proceed / continue → 复用孤儿通道同构的后续处理
                                orphan_result = drift_result
                            if orphan_result.get("action") == "proceed":
                                # 机械对齐/删除后守卫重跑全清 → 放行 merge（不 blocked）
                                self._pm.logger.warning(
                                    "pm_engine",
                                    f"交付物守卫缺件争议机械预分类全清 '{spec_name}' — "
                                    f"声明已机械处置，放行 merge run={result.run_id}",
                                )
                                # code-review item 98b789430350：预分类 proceed 即
                                # 守卫重跑全清、声明已机械处置（预分类器已置
                                # implementing/error=None），契约是「放行 merge
                                # （不 blocked）/不派 judge run」——须短路下方 LLM
                                # 终审：继续派 dispute-judge 会让 spec 先被置
                                # blocked「LLM 终审进行中」再白烧一轮 judge run，
                                # 与放行日志自相矛盾（adjudication.py 对 proceed
                                # 均立即 return 短路）。此处不直接 return：后续
                                # relint 复检/impl-result 快照/merge 收尾仍须照常
                                # 执行，仅跳过终审调用。
                                preclassified_proceed = True
                            elif orphan_result.get("action") == "continue":
                                # 仍有缺件 → 以重跑后的 remaining 续走既有后续（design
                                # 续走契约第 4 点）：剩余项仍带 dispute 异议 → blocked 待
                                # 人工；无异议项 → 交下方既有 _adjudicate_deliverable_missing
                                # LLM 终审，不得因「已判过一批」就整段跳过。
                                still_disputed = orphan_result.get(
                                    "remaining_disputed", []
                                )
                                if still_disputed:
                                    disp_q = "、".join(still_disputed)
                                    updates: dict = {
                                        "status": "blocked",
                                        "tester_run": None,
                                        "error": (
                                            f"交付物守卫缺件 [{disp_q}]，但实现 run 对其"
                                            f"提出 deliverable-dispute 异议（依据见该 run"
                                            f"的 .fenix-run-result.json findings 与旧分支"
                                            f"成果）— 已 blocked 待人工裁决，不自动重派"
                                        ),
                                    }
                                    self._pm.state_machine.update_spec(spec_name, updates)
                                    self._pm.logger.error(
                                        "pm_engine",
                                        f"交付物守卫缺件异议 '{spec_name}'（{disp_q}）— "
                                        f"blocked 待裁决，不重派 run={result.run_id}",
                                    )
                                    return
                                # 剩余缺件均无异议 → 落入下方既有 LLM 终审通道
                                missing = orphan_result.get(
                                    "remaining_missing", missing
                                )
                            else:
                                # fallback（无孤儿可删 / 判定/删除/提交/重跑异常）→
                                # 全量回退既有 blocked 待人工路径（fail-open）
                                disp_q = "、".join(disputed)
                                updates: dict = {
                                    "status": "blocked",
                                    "tester_run": None,
                                    "error": (
                                        f"交付物守卫缺件 [{disp_q}]，但实现 run 对其提出 "
                                        f"deliverable-dispute 异议（依据见该 run 的 "
                                        f".fenix-run-result.json findings 与旧分支成果）"
                                        f"— 已 blocked 待人工裁决，不自动重派"
                                    ),
                                }
                                self._pm.state_machine.update_spec(spec_name, updates)
                                self._pm.logger.error(
                                    "pm_engine",
                                    f"交付物守卫缺件异议 '{spec_name}'（{disp_q}）— "
                                    f"blocked 待裁决，不重派 run={result.run_id}",
                                )
                                return
                        # ── 缺件 LLM 终审与裁决机械执行（add-deliverable-declaration-triage）──
                        # 判缺件后不再直接打回/重派：先派 dispute-judge- run 语义终审
                        # （机械规则拦不住的声明 vs 现实矛盾由 LLM 裁决）。终审期间
                        # spec 置 blocked（error 含 run id 与「LLM 终审进行中」）阻断
                        # 轮询重派竞态（D5）。裁决机械执行（D4）：
                        #   typo → tasks.md 声明 path 修正 → 重跑守卫对账（4.4 防洗白）
                        #            → 通过则放行 merge；
                        #   reference → 声明软化（转软校验）；
                        #   missing → 既有打回/重派路径（带精准缺件清单）；
                        #   unclear → 既有 deliverable-dispute blocked 人工裁决话术。
                        if not preclassified_proceed:
                            # 机械预分类 proceed（守卫重跑全清放行）短路终审
                            # （code-review item 98b789430350）：不再派 judge
                            # run，直接续走下方 merge 收尾；其余形态照常派
                            # 单轮 dispute-judge run 消费裁决。
                            adjudication = self._pm._adjudicate_deliverable_missing(
                                spec_name, result, impl_result, missing
                            )
                            if adjudication.get("action") != "proceed":
                                return

                # ── tasks.md 收口复检门禁（add-tasksmd-relint-gate）──────────────
                # 2026-09-11 add-impl-terminal-nocommit-gate 事故：implementer 用 sed
                # 勾选 tasks.md 把任务行写成 `^- [x] 1.1 …`，分组完好任务行全灭，晋升
                # lint（立项期跑一次）穿透、收口期零校验 → dashboard 任务清单空白。
                # 此处为 merge 前事后复检：以实现分支 HEAD 的 tasks.md 为基准（merge 前
                # 主树版本 = 立项旧版本，读分支才反映中途编辑），违规 → 不合并不推进，
                # 走失败重派 + error 写违规明细与修正处方。读取失败/异常 → fail-open。
                if is_success:
                    try:
                        relint = self._pm._tasks_md_relint_from_branch(
                            spec_name, getattr(result, "branch", None)
                        )
                    except Exception as e:
                        self._pm.logger.warning(
                            "pm_engine",
                            f"tasks.md relint 执行异常（fail-open）'{spec_name}': {e}",
                        )
                        relint = []
                    if relint:
                        self._redispatch_tasks_relint(
                            spec_name,
                            relint,
                            run_id=getattr(result, "run_id", "") or "",
                            # fix-relint-redispatch-legacy 1.3：full 车道此处持有
                            # result（用于上方 _tasks_md_relint_from_branch），把分支
                            # 线索传入处置函数以登记仅分支遗产（branch 为空则跳过）。
                            branch=getattr(result, "branch", None),
                        )
                        return

                if is_success:
                    # ── impl-result per-spec 快照（fix-verified-gate-evidence-race D1）──
                    # implementer 成功即把已解析的结果 dict 原样原子快照到
                    # .fenix/verify-progress/<spec>/impl-result.json，供 verified→done
                    # 门禁 _task_completion_blocker 读取——门禁证据不再依赖跨 spec
                    # 共享文件 .fenix/.fenix-run-result.json（2026-09-07 事故：共享文件
                    # 被其它 spec 成功覆盖 → 门禁「无法证伪即放行」静默放行带未勾任务的
                    # spec）。快照写失败仅 WARNING 不阻塞（fail-open，门禁 fail-closed
                    # 兜底）；重派后新成功原子覆盖旧快照（幂等）。
                    # fast-track 车道同语义，写点在 _run_fast_track_flow 的 merge
                    # 成功收口处（2026-09-10 add-planready-artifact-gate 实证 fast-track
                    # 滞留 verified 同样存在跨 spec 覆盖窗口）。
                    if impl_result is not None:
                        try:
                            self._pm._write_impl_result_snapshot(spec_name, impl_result)
                        except Exception as e:
                            self._pm.logger.warning(
                                "pm_engine",
                                f"impl-result 快照写入失败 '{spec_name}'（非阻塞）: {e}",
                            )
                        # 消费后清理共享结果文件（D4，fast-track 车道同语义写点在
                        # _run_fast_track_flow）：本次采信消费 + 快照落盘之后删除
                        # 主树共享文件，仅当 stamp 严格匹配本 spec 时删除。删除失败
                        # 仅 WARNING 不阻塞（fail-open，残留由 stamp 严格校验兜底）。
                        self._pm._cleanup_shared_result_file(spec_name)
                    # 计数对账（fix-budget-counting-semantics D3）：守卫放行/merge
                    # 收工后回读 used 与正常收工 run 数比对，偏差记 WARNING。
                    self._pm._reconcile_impl_budget(spec_name)
                    # ── 锚点提前落盘（fix-recovery-branch-anchor D1）─────────
                    # implementer run 终态成功后、merge 预演与 merge-back 之前，
                    # 把 branch/implementer_run 写入 STATE——使恢复链在「已实现未合并」
                    # 窗口内可命中本轮分支，避免 daemon 重启后清空重写。
                    # 写入点定序在全部 merge 前置闸门之后（零变更哨/交付物守卫/
                    # tasks.md 收口复检），确保只有真正通过所有闸门的成功 run 才
                    # 留下锚点；早退路径（status: ready/blocked）进入下一轮全新
                    # 派发，不残留本轮锚点。
                    # ── 锚点清除见 _run_agent_worker 入口（tasks 1.5）──────
                    if result.branch:
                        # add-impl-ocr-parallel-lane（任务 4.1）：ocr join 指纹的
                        # base 分量在本点捕获（全部 merge 前置闸门之后、merge-back
                        # 之前）——merge 后 merge-base(main, branch) 恒为 branch
                        # head（空 diff），base MUST 在 merge 前取。随锚点同批
                        # 持久化，重启窗口内恢复链仍可按当前指纹重跑车道。
                        # 捕获失败置 None（车道启动时回退 merge-base 语义，见
                        # _start_impl_ocr_lane 调用点）。
                        _ocr_base = None
                        if self._impl_ocr_enabled():
                            _ocr_base = self._git_merge_base_main(result.branch)
                        try:
                            self._pm.state_machine.update_spec(
                                spec_name,
                                {
                                    "branch": result.branch,
                                    "implementer_run": result.run_id,
                                    "_ocr_base_commit": _ocr_base,
                                },
                            )
                            self._pm.logger.info(
                                "pm_engine",
                                f"锚点已提前落盘 '{spec_name}': "
                                f"branch={result.branch}, "
                                f"implementer_run={result.run_id}",
                            )
                        except Exception as e:
                            self._pm.logger.warning(
                                "pm_engine",
                                f"锚点写入失败 '{spec_name}'（非阻塞）: {e}",
                            )
                    # Merge worktree branch back into main tree before advancing state.
                    # worktree 已被 agent_runner 清理，但分支仍保留（success 路径不删分支），
                    # 所以用分支名直接 merge。
                    if impl_status != "partial" and not result.branch:
                        # （code-review item e45c71cbcd2c）防御「success 蕴含 branch
                        # 非空」契约：runner 成功路径的分支名取自
                        # worktree_manager.get_branch_name（Optional[str]——daemon
                        # 重启后内存映射重建缺项等场景可返回 None）。branch 为空时
                        # 下方 merge_ok 默认 True 且 if result.branch: 跳过合并，将经
                        # _finalize_merge_success(branch=None) 伪推进 implemented 并
                        # 入队 verifier——实现成果未合入 main 且 worktree 已被清理；
                        # 三个下游检查点对该形态全部放行（_implementer_zero_change
                        # 对 branch 空直接返回 False 不判定、_deliverable_gate_missing
                        # 对 branch 空保守放行、relint fail-open），成果静默丢失。
                        # 对齐 fast-track 车道同款守卫（item 69fe26c88579）：直接判
                        # 失败走重派，禁止无 branch 的伪合并收口——无真实 merge 失败
                        # 可归因，不经 fingerprint/breaker/repair 记账，也不触同因
                        # 重派 streak（作用域边界同通用失败分支 3.3b 约定）；
                        # worktree 已被 runner 清理，无可保留现场。
                        # 豁免 impl_status == "partial"（诚实退出收敛，定向重试轮
                        # 回归修复）：run-result 自报 partial + 缺口全部 ⊆
                        # unattainable 时上方已按成功收口，该契约形态本就允许
                        # branch 缺失（「run 已收工、worktree 已清理」下收尾只推进
                        # 状态并入队 verifier，无合并动作——
                        # test_honest_exit_convergence 钉住，fix-dashboard-read-path-
                        # performance 实测事故的收敛出口）。守卫只盯伪 success
                        # （自报 success / 无结果文件），不拦自报 partial 的合法缺支。
                        contract_err = (
                            "merge skipped（success 但 branch 为空，违反「success "
                            "蕴含 branch 非空」契约）：实现成果未经合并，按 merge "
                            "失败重派"
                        )
                        try:
                            # 配置侧 int() 归一（与通用失败分支同款）：字符串配置
                            # 裸用于比较抛 TypeError 中断重派处置，非法值回退缺省。
                            cfg_max_r = self._pm._get_config("agents.max_retries", 3)
                            max_r = 3 if cfg_max_r is None else int(cfg_max_r)
                        except (TypeError, ValueError):
                            max_r = 3
                        max_r = max(max_r, 1)
                        # _retry_count 锁内原子递增（写后值不再并入 update_spec，
                        # 对齐 _handle_merge_back_real_failure 防并发写回丢增量）。
                        # 本出口重派同样受 agents.max_retries 封顶（对齐 fast-track
                        # item a7395837fcbb）：持续性「success 但 branch 为空」若只
                        # 递增重派会无限烧实现 run 预算——达阈冻结转人工，不再自动
                        # 重派。
                        retries = self._pm.state_machine.bump_counters(
                            spec_name, {"_retry_count": 1}
                        ).get("_retry_count", 0)
                        if retries >= max_r:
                            spec_entry = (
                                self._pm.state_machine.read_one(spec_name) or {}
                            )
                            fp = self._pm._redispatch_cause_fingerprint(contract_err)
                            orig_status = spec_entry.get("status") or "implementing"
                            self._pm.state_machine.freeze_for_human(
                                spec_name,
                                error=(
                                    f"原状态 {orig_status} · 重试耗尽"
                                    f"（{max_r}/{max_r} 轮，指纹 {fp}）：{contract_err}"
                                ),
                                signal_type="redispatch_loop_detected",
                                severity="major",
                                description=(
                                    f"'{spec_name}' 契约违反（success 但 branch 为空）"
                                    f"连续重试 {max_r} 轮已达上限（max_retries），"
                                    f"自动重试终止——已冻结转人工处置"
                                ),
                                evidence=(
                                    f"spec={spec_name}; retries={retries}; "
                                    f"max_retries={max_r}; fp={fp}; "
                                    f"final_error={contract_err}"
                                ),
                                recommended_action=(
                                    "检查 runner 成功但分支名缺失的根因；处置后解冻"
                                    "（unfreeze_spec 自动清零计数）可重新获得自动"
                                    "修复机会"
                                ),
                                alert_callback=self._pm._send_human_escalation_alert,
                            )
                            self._pm.logger.error(
                                "pm_engine",
                                f"All retries exhausted for '{spec_name}' — "
                                f"冻结转人工，不再重派（{retries}/{max_r}，fp={fp}）",
                            )
                        else:
                            self._pm.state_machine.update_spec(
                                spec_name,
                                {
                                    "status": "ready",
                                    "error": contract_err,
                                },
                            )
                            self._enqueue_front(spec_name, "implementer")
                            self._pm.logger.error(
                                "pm_engine",
                                f"merge-back skipped for '{spec_name}': "
                                f"{contract_err}",
                            )
                        return
                    merge_ok = True
                    merge_error = ""
                    merge_info = None
                    conflict_files = []
                    if result.branch:
                        merge_info = wm.merge_back_from_branch(result.branch)
                        merge_ok, merge_error = merge_info  # 兼容 (bool, str) 解包
                        # guard 段内 pop 冲突自愈丢弃的用户改动清单（admin 告警用）
                        conflict_files = list(wm.last_stash_pop_conflicts)

                    if not merge_ok:
                        # ── 预演语义冲突直通 repair（add-merge-tree-rehearsal D2）──
                        # merge-tree 预演在主树零污染点检出语义冲突（rehearsed=True）：
                        # 未发生真合并，熔断语义上「merge 失败」并不成立——不经
                        # _merge_fp/_merge_streak 记账、不做 ready 降级，spec 保持
                        # in-flight 直接派 repair agent 在实现分支内把 main 合入解决。
                        # 轮次上限（_repair_round）超限时回退现行 fallback 重派兜底。
                        if getattr(merge_info, "rehearsed", False):
                            self._direct_rehearsed_to_repair(
                                spec_name, merge_info, result.branch, merge_error
                            )
                            return
                        # ── WIP 重叠闸门阻塞旁路（evo-merge-back-wip-overlap-gate D3）──
                        # 阻塞是「前置拦截」而非「merge 失败」：主树未被
                        # stash/merge/pop 触碰（worktree_manager 在闸门命中且策略为
                        # block 时直接返回 wip_gate_blocked=True，主树零污染），
                        # 原样走熔断记账会把同一指纹连续累计到阈值冻结 spec
                        # （比现状更差）。对照 rehearsed=True 同类豁免：不经
                        # _merge_fp/_merge_streak 记账、不做 ready 降级、不进
                        # repair 通道，spec 保持 in-flight，仅直发告警等待人工
                        # 处置主树 WIP（提交或 stash 重叠改动后重新放行）。
                        if getattr(merge_info, "wip_gate_blocked", False):
                            self._report_mergeback_wip_overlap(
                                spec_name, merge_info, result.branch, merge_error
                            )
                            return
                        # ── 可重试 merge-back 失败分类（evo-merge-back-spec-dir-inflight-guard D2）──
                        # 插点（task 0.2 固化）：rehearsed（上方早退）→
                        # wip_gate_blocked（上方早退）→ **本分类** → 指纹熔断记账。
                        # 可重试（主树脏 / spec 目录在飞编辑 / 锁冲突）时保留已成功
                        # 分支与产物、仅重试合并（不重派实现 run）；判不准 fail-open
                        # 回既有指纹熔断通道（D2 假阴性方向：真实失败被无限重试）。
                        if self._handle_retryable_mergeback_failure(
                            spec_name, merge_info, merge_error, result.branch
                        ):
                            return
                        # merge 失败：指纹熔断（fix-fenix-token-waste）。
                        # 同一错误指纹连续失败 ≥ 阈值 → spec 进入 blocked 停止自动重试，
                        # 避免「根因不消除 → 全量重跑 → 再败」的无限烧钱循环。
                        # （实现体提取为 _handle_merge_back_real_failure，供 merge-only
                        # 重试点复用同一判定基准——evo-merge-back-spec-dir-inflight-guard D2）
                        self._handle_merge_back_real_failure(
                            spec_name, merge_info, merge_error, result.branch
                        )
                    else:
                        # stash 恢复已在 merge_back_from_branch 的 guard 段内完成
                        # （fix-autostash-orphans），此处只推进状态。
                        # （实现体提取为 _finalize_merge_success，供 merge-only
                        # 重试点复用同一收口逻辑——evo-merge-back-spec-dir-inflight-guard D2）
                        self._finalize_merge_success(
                            spec_name,
                            result.run_id,
                            getattr(result, "branch", None) or None,
                            merge_info,
                            conflict_files,
                        )
                else:
                    # ── 冻结终止 hold-state（add-freeze-stop-inflight-agents 3.1）──
                    # 被冻结终止的 run（frozen_terminated=True）：独立保持分支，
                    # 在 cancelled 分支之前判定（spec 级高于 run 级）。只写
                    # _frozen_hold 标记 + error、不翻转 status（保持 blocked）、
                    # 不动 _retry_count/_merge_fp/_merge_streak、不入队重派、
                    # 不豁免预算（区别于死亡 run 豁免）。解冻后经 _frozen_hold
                    # + 保留分支续做。
                    # 判定用 `is True`（修复验证轮 BUG：MagicMock 替身自动
                    # 生成 truthy 属性，裸布尔会误判；生产结果为显式 bool）。
                    if getattr(result, "frozen_terminated", False) is True:
                        ft_err = getattr(result, "error", None) or final_error or ""
                        frozen_err = (
                            f"run 因 spec 冻结被终止（进度已保全，解冻后续做）"
                            f"{': ' + ft_err if ft_err else ''}"
                        )
                        self._pm.logger.warning(
                            "pm_engine",
                            f"run 因 spec 冻结被终止 '{spec_name}' — "
                            f"_frozen_hold，不重试/不重派: {frozen_err}",
                        )
                        self._pm.state_machine.mark_frozen_hold(
                            spec_name, frozen_err)
                        return
                    # ── 人工取消 hold-state（add-run-cancel D4）──────
                    # 被取消的 run（cancelled=True）：只更新 error 字段（含
                    # 「run 被人工取消」与 reason），不翻转 status、不动
                    # _retry_count/_merge_fp/_merge_streak、不入队重派。
                    # 后续重排完全交给既有机制（stuck 检测/恢复扫描）或
                    # 管理员人工操作（freeze 等）。判定口径与上方
                    # frozen_terminated 一致用 `is True`（防 MagicMock 替身
                    # 自动生成 truthy 属性误判）。
                    if getattr(result, "cancelled", False) is True:
                        cancelled_err = (
                            f"run 被人工取消：{final_error}" if final_error else "run 被人工取消"
                        )
                        self._pm.logger.warning(
                            "pm_engine",
                            f"run 被人工取消 '{spec_name}' — hold-state，"
                            f"不重试/不重派: {cancelled_err}",
                        )
                        self._pm.state_machine.update_spec(
                            spec_name,
                            {
                                "error": cancelled_err,
                                # 取消保持持久标记（fix-cancel-holdstate-recovery D1）：
                                # 随 STATE.md 存活，重启恢复/监测链路据此跳过该 spec。
                                "_cancelled_hold": True,
                            },
                        )
                        return
                    # ── 死亡 run 豁免（fix-budget-counting-semantics D1）──────
                    # 无收工结果产出（.fenix-run-result.json 缺失）＝ run 异常
                    # 死亡（进程消失/零输出/网关链路耗尽）：回退本次启动的计数。
                    # 有收工结果的正常失败（impl_status=error）不豁免——既有
                    # 「正常失败仍计数」语义不变。
                    # fix-run-hang-amplification D2：run_reason 传入豁免判据，
                    # 监督超时/被判停滞而杀（extension budget exhausted / stagnant）
                    # 不豁免——确实消耗了整份预算。
                    if impl_status is None:
                        # 隔离（code-review item 6c566aab43e8，与 rollback.py
                        # _rollback_failed_dispatch 同名调用点同款）：豁免是
                        # **尽力而为的记账**（写状态文件，锁/IO 可能失败），若它
                        # 自己抛异常，控制流会直接跳到外层 except 转
                        # _rollback_failed_dispatch，下方 provider 熔断保持原状 /
                        # [provider-transient] 延迟重派 / 模型链不可用 / 同因熔断
                        # 与重试计数四段终态分类全部被跳过（_retry_count 不递增、
                        # transient 不排程），失败被降格为通用回滚。故必须独立
                        # try/except，豁免失败仅 WARNING、按未生效继续走失败分类链。
                        # exempt_applied 标记：审计日志须携带豁免是否实际生效，
                        # 否则记账失败时对账会把未生效的豁免当作已豁免。
                        exempt_applied = False
                        try:
                            self._pm._exempt_dead_run_budget(
                                spec_name,
                                f"no run-result file (error={str(final_error)[:80]})",
                                run_reason=str(final_error) if final_error else None,
                            )
                            exempt_applied = True
                        except Exception as exempt_exc:  # noqa: BLE001 —— 记账失败不阻塞失败分类
                            self._pm.logger.warning(
                                "pm_engine",
                                f"budget exempt failed for '{spec_name}'（按未豁免"
                                f"继续失败分类）: {type(exempt_exc).__name__}: "
                                f"{exempt_exc}",
                            )
                        # 审计日志：可审计豁免判定（spec、终态、原因、是否豁免）
                        self._pm.logger.info(
                            "pm_engine",
                            f"budget_exempt_audit: spec={spec_name}, "
                            f"impl_status=None, exempt_applied={exempt_applied}, "
                            f"final_error={str(final_error)[:120]}, "
                            f"run_reason={str(final_error)[:80] if final_error else ''}",
                        )
                    # ── provider 熔断拦截（fix-stashpop-deadlock：provider-fault-fuse） ──
                    # MUST 同步（code-review item 0caca76e37b1）：本 implementer
                    # 失败处置链以下四段「终态错误分类→处置动作」（provider 熔断
                    # "provider circuit open" 保持原状 / [provider-transient]
                    # 延迟重派 / MODEL_CHAIN_UNAVAILABLE_MARKER 保持原状 / else
                    # 重试计数与 max_r 封顶冻结转人工）与
                    # fast_track.py `_handle_fast_track_failure` 的同名四段逐段
                    # 同构、手工双维护，fast-track 侧历史上曾多次缺失、事后补齐
                    # 对齐。任一车道新增/修改终态失败分支时 MUST 同步该方法对应
                    # 段，禁止只改一处；对照定位用方法名/分支语义，勿写裸行号。
                    # 熔断期派发失败（error 含 "provider circuit open"）属「provider 故障」，
                    # 不是 spec 自身问题：不计入 _retry_count / _merge_streak、不翻转状态机、
                    # 不创建新 worktree/autostash（design D5）。spec 保持 implementing 原状，
                    # 由冷却结束后的既有轮询/事件机制自然重排；持续过久由 admin_monitor
                    # 按 stuck 规则唤起人工（充值/换模型）。
                    if final_error and "provider circuit open" in final_error:
                        self._pm.logger.warning(
                            "pm_engine",
                            f"Provider circuit open for '{spec_name}' — holding state, "
                            f"no retry/state flip: {final_error}",
                        )
                        # 写入 error 供 dashboard/admin 可见，但不翻转状态、不增 retry
                        self._pm.state_machine.update_spec(
                            spec_name,
                            {
                                "error": final_error,
                            },
                        )
                    elif final_error and "[provider-transient]" in final_error:
                        # fix-provider-transient-backoff（D4）：transient 终态——不走
                        # _retry_count 递增/清零路径，改排程等待后重派（复用
                        # instant_fail_recovery 定时器模式，`transient_redispatch_delay_seconds`
                        # 缺省 600s）。死亡 run 预算豁免行为保持不变。
                        self._pm.logger.warning(
                            "pm_engine",
                            f"Provider transient for '{spec_name}' — scheduling "
                            f"delayed redispatch, no retry/state flip: {final_error}",
                        )
                        # 写入 error 供 dashboard 可见，但不翻转状态
                        self._pm.state_machine.update_spec(
                            spec_name,
                            {
                                "error": final_error,
                            },
                        )
                        self._schedule_transient_recovery(spec_name)
                    elif final_error and MODEL_CHAIN_UNAVAILABLE_MARKER in final_error:
                        # add-impl-selfcheck-model-probe（2.2）：链尾拒模型 →
                        # 全链模型不可用终态。同因重派必然撞同一拒模型链（确定性
                        # 失败，非瞬态），不排程、不增 retry、不翻转状态机；spec
                        # 原状保持，error 落盘供 dashboard/admin 可见。摘除拒模型
                        # 条目后恢复属人工运维（docs/help/12-faq.md）。
                        self._pm.logger.warning(
                            "pm_engine",
                            f"Model chain unavailable for '{spec_name}' — holding "
                            f"state, no redispatch/retry/state flip: {final_error}",
                        )
                        self._pm.state_machine.update_spec(
                            spec_name,
                            {
                                "error": final_error,
                            },
                        )
                    else:
                        # Retry or mark error
                        # code-review item f8c5c67e7eb4：run 在飞期间 spec 可能
                        # 被删——read_one 返回 None 时下方 spec_entry.get /
                        # _parse_int_field 抛 AttributeError，整条失败处置链
                        # 被外层异常兜底接管（同因熔断/重试耗尽逻辑被跳过）。
                        # 与零变更哨 spec_entry 及 _handle_merge_back_real_failure
                        # 的 read_one or {} 站点对齐（对照定位用方法名/分支语义，
                        # 勿写裸行号——本文件自定约定）。
                        spec_entry = self._pm.state_machine.read_one(spec_name) or {}
                        # _retry_count 锁内原子递增（code-review item
                        # e0da51239a8d）：取写后值参与 retries >= max_r 判定与
                        # error 文案，else 分支 update_spec 不再并写该字段（对齐
                        # 契约违反分支与本文件 _handle_merge_back_real_failure
                        # 同型收口，防并发写回互相覆盖丢增量）——原两段式
                        # 「读 → 算 +1 → 绝对写回」读与写分处两次 STATE 锁临界
                        # 区，并发交错丢一次递增，max_retries 封顶与重试耗尽冻结
                        # 晚一轮触发。冻结分支不写该字段的既有语义不变。
                        retries = self._pm.state_machine.bump_counters(
                            spec_name, {"_retry_count": 1}
                        ).get("_retry_count", 0)
                        try:
                            # 配置侧 int() 归一（code-review item 84d793a3ac41，
                            # 与 adjudication.py 同款）：字符串配置裸用于比较抛
                            # TypeError 中断失败重派处置，非法值回退缺省。
                            cfg_max_r = self._pm._get_config("agents.max_retries", 3)
                            max_r = 3 if cfg_max_r is None else int(cfg_max_r)
                        except Exception:
                            max_r = 3
                        max_r = max(max_r, 1)
                        # ── 同因重派熔断（fix-redispatch-loop-governance D3/3.3/3.4）──
                        # 现状（事故实证）：retries >= max_r 时清零 _retry_count 后
                        # 照样 _enqueue——「All retries exhausted」只是日志，无限热派。
                        # 本变更让该分支真正终止自动重试：
                        #   1. 同因熔断：对失败归因做归一化指纹（剔除 run_id/时间戳/
                        #      worktree 路径等易变段），连续同指纹达
                        #      agents.max_same_cause_redispatches（缺省 3）阈值 →
                        #      冻结转人工（freeze_for_human），MUST NOT 再 _enqueue；
                        #      指纹变化即重置 streak 为 1。
                        #   2. 重试耗尽：retries 达 max_r → 同样冻结终止（协同 3.3，
                        #      「达上限即冻结」），不再清零重派。
                        # 作用域边界（3.3b）：本 streak 只在**本通用失败重派分支**
                        # 记账——merge 指纹熔断（_merge_fp/_merge_streak）、provider
                        # transient 排程、锁冲突退避、交付物守卫/relint 的
                        # _retry_count 封顶四条通道的失败 MUST NOT 增减它。
                        fp = self._pm._redispatch_cause_fingerprint(final_error)
                        prev_fp = spec_entry.get("_redispatch_cause_fp")
                        prev_streak = self._parse_int_field(
                            spec_entry, "_redispatch_same_cause_streak", 0
                        )
                        streak = prev_streak + 1 if prev_fp == fp else 1
                        from core.config import ConfigLoader as _CL_breaker

                        breaker_threshold = _CL_breaker.get_max_same_cause_redispatches(
                            self._pm.config
                        )
                        orig_status = (spec_entry or {}).get("status") or "implementing"
                        if streak >= breaker_threshold:
                            # 同因熔断：冻结转人工（error 内嵌「原状态 X」供
                            # parse_orig_status 解冻还原 + 含指纹/轮数供人工审计）
                            self._pm.state_machine.freeze_for_human(
                                spec_name,
                                error=(
                                    f"原状态 {orig_status} · 同因重派循环（指纹 "
                                    f"{fp}，连续同因 {streak} 轮，累计重派 {retries} "
                                    f"轮，阈值 {breaker_threshold}）：{final_error}"
                                ),
                                signal_type="redispatch_loop_detected",
                                severity="major",
                                description=(
                                    f"'{spec_name}' 连续 {streak} 轮以同一归因"
                                    f"（指纹 {fp}）判失败重派，达熔断阈值——已冻结"
                                    f"转人工处置，不再自动重派"
                                ),
                                evidence=(
                                    f"spec={spec_name}; fp={fp}; streak={streak}; "
                                    f"retries={retries}; max_retries={max_r}; "
                                    f"final_error={final_error}"
                                ),
                                recommended_action=(
                                    "检查失败根因（缺口/环境/网关）；处置后解冻"
                                    "（unfreeze_spec 自动清零同因计数）可重新获得"
                                    "自动修复机会"
                                ),
                                alert_callback=self._pm._send_human_escalation_alert,
                                # 冻结瞬间持久化最终同因计数（供冻结态审计 /
                                # 解冻前可读；解冻时统一清零）
                                extra_updates={
                                    "_redispatch_cause_fp": fp,
                                    "_redispatch_same_cause_streak": streak,
                                },
                            )
                            self._pm.logger.error(
                                "pm_engine",
                                f"同因重派熔断 '{spec_name}'（fp={fp}，streak="
                                f"{streak}，retries={retries}/{max_r}）— "
                                f"冻结转人工，不再重派",
                            )
                        elif retries >= max_r:
                            # 重试耗尽（3.4）：真正终止自动重试（原清零+重派空转）。
                            self._pm.state_machine.freeze_for_human(
                                spec_name,
                                error=(
                                    f"原状态 {orig_status} · 重试耗尽"
                                    f"（{max_r}/{max_r} 轮，指纹 {fp}）：{final_error}"
                                ),
                                signal_type="redispatch_loop_detected",
                                severity="major",
                                description=(
                                    f"'{spec_name}' 连续失败重试 {max_r} 轮已达上限"
                                    f"（max_retries），自动重试终止——已冻结转人工"
                                    f"处置"
                                ),
                                evidence=(
                                    f"spec={spec_name}; retries={retries}; "
                                    f"max_retries={max_r}; fp={fp}; "
                                    f"final_error={final_error}"
                                ),
                                recommended_action=(
                                    "检查失败根因；处置后解冻（unfreeze_spec 自动"
                                    f"清零计数）可重新获得自动修复机会"
                                ),
                                alert_callback=self._pm._send_human_escalation_alert,
                            )
                            self._pm.logger.error(
                                "pm_engine",
                                f"All retries exhausted for '{spec_name}' — "
                                f"冻结转人工，不再重派（{retries}/{max_r}，fp={fp}）",
                            )
                        else:
                            self._pm.state_machine.update_spec(
                                spec_name,
                                {
                                    "status": "ready",
                                    "error": final_error,
                                    # _retry_count 已由上方 bump_counters 原子递增
                                    # 落盘，此处不再并写（防并发写回互相覆盖丢增量）
                                    "_redispatch_cause_fp": fp,
                                    "_redispatch_same_cause_streak": streak,
                                },
                            )
                            self._pm.logger.warning(
                                "pm_engine",
                                f"Retry {retries}/{max_r} for '{spec_name}'"
                                f"（同因 streak {streak}）",
                            )

            elif agent_type == "verifier":
                self._pm._run_verification_pipeline(spec_name)

            elif agent_type == "planner-plan":
                # ── 并行出题车道（add-verify-lane-throughput 1.1/2.1）──
                # 出题 run 与实现车道独立在飞：run 失败走既有 planner 失败路径
                # （transient 重试/升级，由 _run_parallel_plan_lane 内部处置），
                # 异常吞并留痕，MUST NOT 影响实现车道派发与状态机。半成品场景集
                # 的不采信由消费侧（pipeline 并行产物校验）兜底（任务 1.2/1.3）。
                try:
                    self._pm._run_parallel_plan_lane(spec_name)
                except Exception as e:  # pragma: no cover - 防御性兜底
                    self._pm.logger.warning(
                        "pm_engine",
                        f"并行出题车道异常 '{spec_name}'（不影响实现车道）: {e}",
                    )

            else:
                # ── 未识别 agent_type 兜底（code-review item 634bc08048e4）──
                # 旧 if/elif 链无兜底：误入队条目（拼写变体/未来新增车道）会正常
                # pop、出锁段递增 _active_runs/_active_priority_counts 占用并发
                # 槽位，本链匹配不到任何分支后直接走 finally 释放——零动作、零
                # 日志，spec 滞留原状态且无痕迹可查。此处仅 ERROR 留痕，MUST NOT
                # 调 _rollback_failed_dispatch：该方法对未识别 agent_type 无对应
                # 分支（rollback.py 末段 else 仅 WARNING 留痕、无任何状态动作），
                # 而 finally 的 else 兜底已释放本条目占用的槽位，再调回滚只会叠加
                # 一层「已回滚」的误导语义；spec 滞留由既有 recovery/stuck 兜底
                # 通道拾取（本条日志即对账锚点）。
                self._pm.logger.error(
                    "pm_engine",
                    f"未识别的 agent_type={agent_type!r}，worker 无对应车道分支，"
                    f"条目已出队但不做任何派发：spec='{spec_name}' (P{priority})",
                )

        except Exception as e:
            self._pm.logger.error("pm_engine", f"Agent run exception: {e}")
            # 派发/执行异常必须回滚滞留中间态的 spec（fix: 伪 bug 卡死根因）。
            # 此前只记日志：日限额耗尽等异常使 run 从未启动，spec 却已滞留在
            # implementing/testing，无 run 痕迹、永久卡死。
            self._pm._rollback_failed_dispatch(spec_name, agent_type, e)
        finally:
            # Release the concurrency slot and try to dispatch more work
            with self._queue_lock:
                if agent_type == "spec-review":
                    # 评审条目释放（fix-spec-review-blocking-dispatch 1.9）：
                    # 释放 _active_reviews，不触碰 _active_runs/_active_priorities
                    # （评审条目从未递增它们）。幂等 discard：worker 的
                    # _run_spec_review_worker 已在调用 dispatch_review 前释放
                    # （释放时点 ≤ 锚点落盘，design D4 重入安全性），finally
                    # 再执行一次兜底（覆盖异常路径）。异常路径不触发重排队列
                    # ——_rollback_failed_dispatch 不含 spec-review 分支时
                    # 由 recovery 的 reviewing 分支兜底拾取（spec-review-recovery
                    # spec Scenario「未完成状态可被恢复通道重新拾取」）。
                    self._active_reviews.discard(spec_name)
                elif agent_type == "planner-plan":
                    # 并行出题条目释放（add-verify-lane-throughput 2.1）：仅摘除
                    # 在飞登记（豁免上限计量恢复），不触碰 _active_runs/
                    # _active_priorities（条目从未递增它们）。
                    self._active_parallel_plans.discard(spec_name)
                else:
                    if agent_type == "verifier":
                        # verify 单飞在飞摘除（evo-add-verify-dispatch-single-flight
                        # 1.1）：worker 收工（成功或异常路径经 finally 兜底）即
                        # 放行同 spec 后续合法重验（spec Scenario「在飞结束后
                        # 放行」）。
                        self._active_verifies.discard(spec_name)
                    self._active_runs -= 1
                    # 宽松优先级：按优先级计数释放，仅当该档最后一个 run 结束才移除该档，
                    # 避免多档并发时把仍活动的档位误移除（fix：多档并发）
                    cnt = self._active_priority_counts.get(priority, 0) - 1
                    if cnt <= 0:
                        self._active_priority_counts.pop(priority, None)
                        self._active_priorities.discard(priority)
                    else:
                        self._active_priority_counts[priority] = cnt
            self._pm._process_queue()

    # ── merge-back 可重试分类与仅重试合并（evo-merge-back-spec-dir-inflight-guard D2）──
    # 插点：_run_agent_worker 的 merge 失败分支，位于 rehearsed / wip_gate_blocked
    # 早退之后、指纹熔断记账之前（task 0.2 固化）。D2 判据按层分离：
    #   带 git 退出码文本（self-heal 兜底后仍被拒的原文片段）→ 文本匹配；
    #   不带退出码文本（spec 目录在飞编辑顺延 / dispatch 级锁冲突）→ 结构化字段；
    #   判不准 fail-open 回既有指纹熔断/repair/ready 通道。

    _RETRYABLE_MERGE_ERROR_FRAGMENTS = ("would be overwritten by merge", "would be lost")

    def _retryable_merge_error_text(self, merge_error: str) -> bool:
        """merge 错误文本是否命中「主树脏」可重试形态（D2 文本匹配判据）。

        只锚定 git 原文片段（``would be overwritten by merge`` / ``would be lost``），
        MUST NOT 用宽泛正则（如单独 ``overwritten``）——判不准 fail-open 回既有
        指纹熔断（D2 假阴性方向：真实失败被无限重试）。
        """
        err = merge_error or ""
        return any(frag in err for frag in self._RETRYABLE_MERGE_ERROR_FRAGMENTS)

    def _dispatch_lock_conflict_pending(self, spec_name: str) -> bool:
        """既有 dispatch 级锁冲突信号判据（D2）：``_dispatch_backoff_until`` 未到期。

        锁冲突（``_queue_lock`` / ``main_tree_lock`` 获取失败，见
        ``_clear_dispatch_conflict`` 家族）与 spec 目录顺延一样**不带 git 退出码
        文本**——MUST 用既有结构化字段判据识别，禁止文本匹配（靠「错误文本含
        lock」会把任何含该词的真失败误判为可重试）。merge-back 失败时刻该信号
        理论上不成立（run 已启动说明派发锁已取得），本判据为防御性识别；判不准
        fail-open 回既有指纹熔断。
        """
        entry = self._pm.state_machine.read_one(spec_name) or {}
        until = entry.get("_dispatch_backoff_until")
        if not until:
            return False
        try:
            return float(until) > time.time()
        except (TypeError, ValueError):
            return False

    def _handle_retryable_mergeback_failure(
        self, spec_name: str, merge_info, merge_error: str, branch: str
    ) -> bool:
        """merge-back 失败可重试分类（D2 判据入口）。

        可重试 = 主树脏 / spec 目录在飞编辑 / 锁冲突。命中时保留已成功分支与产物、
        仅重试合并（不重派实现 run）：spec 保持 implementing、保留 branch/
        implementer_run 锚点，逐项不动 ``_retry_count`` / ``_merge_fp`` /
        ``_merge_streak`` / 同因重派指纹，不进入「新轮次派发清除旧锚点」分支，
        不递增实现尝试预算（未派生新 run）。

        Returns: True = 已按可重试处置（调用方早退）；False = 判不准/非可重试，
        调用方继续既有指纹熔断/repair/ready 通道（fail-open）。
        """
        if getattr(merge_info, "spec_dir_inflight", False):
            self._defer_merge_back(spec_name, merge_info, branch, merge_error)
            return True
        if self._retryable_merge_error_text(merge_error):
            self._defer_merge_back(spec_name, merge_info, branch, merge_error)
            return True
        if self._dispatch_lock_conflict_pending(spec_name):
            self._defer_merge_back(spec_name, merge_info, branch, merge_error)
            return True
        return False

    @staticmethod
    def _parse_int_field(entry: dict, key: str, default: int = 0) -> int:
        """状态条目整型记账字段容错解析（单一落点，code-review item 43cfde173067）。

        ``_retry_count`` / ``_merge_streak`` / ``_zero_change_attempts`` /
        ``_ocr_fix_rounds`` 等字段的 try-int-except-(TypeError, ValueError)
        解析块此前在文件内重复多处，统一改引本工具（与
        ``_parse_defer_accounting`` 确立的单一落点方向同口径）：字段缺失 /
        None / 空值 / 非数值脏值一律回退 0，后续调整容错规则只改此处。

        Args:
            entry: 状态条目（调用方自行 read_one，缺条目传 ``{}``）。
            key: 记账字段名。
            default: 字段缺失时的缺省值（现存调用点均为 0）。

        Returns: 解析后的 int；脏值/类型不符回退 0，不抛异常。
        """
        try:
            return int(entry.get(key, default) or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _parse_defer_accounting(entry: dict, now: float) -> tuple[int, float]:
        """顺延/WIP 等待共用记账字段的解析与缺省回填（单一落点）。

        code-review item ba3eca240b83：``_merge_retry_count`` /
        ``_merge_retry_first_at`` 是 spec_dir_inflight 顺延与 WIP 等待两条
        通道共用、rollback.py 按同口径读写的共享记账，解析规则收敛到此处，
        三处消费方（``_defer_merge_back`` / ``_recheck_one_wip_deferred`` /
        ``_record_wip_defer_retry_failure``）不再各自复制。统一口径：
        count 缺失/非法 → 0；first_at 缺失/非法 → now（首次阻塞时刻=本次，
        与 rollback.py 写侧缺省回填 ``int(time.time())`` 同口径）。

        Args:
            entry: 状态条目（调用方自行 read_one，缺条目传 ``{}``）。
            now: 调用方已取的当前时刻（沿用同一时间基准，保证窗口计算
                与记账写入不因二次取时漂移）。

        Returns: (count, first_f)——first_f 已保证为 float（缺省回填 now）。
        """
        count = QQQueueMixin._parse_int_field(entry, "_merge_retry_count", 0)
        first_at = entry.get("_merge_retry_first_at")
        try:
            first_f = float(first_at) if first_at else now
        except (TypeError, ValueError):
            first_f = now
        return count, first_f

    def _defer_merge_back(self, spec_name: str, merge_info, branch: str, merge_error: str) -> None:
        """可重试 merge-back 失败：顺延等待，仅重试合并（D1a/D2）。

        语义（逐项点名，MUST）：spec 保持 **implementing**（不降级 ready，避免
        落入「新轮次派发清除旧锚点」）；保留 branch/implementer_run 锚点；逐项
        不动 ``_retry_count`` / ``_merge_fp`` / ``_merge_streak`` /
        ``_redispatch_same_cause_streak`` / ``_redispatch_cause_fp``；**不进入**
        「新轮次派发清除旧锚点」分支；不递增实现尝试预算（未派生新 run，D3）。

        有界性（D1a/D2，MUST）：顺延窗口固化
        ``mergeback.spec_dir_inflight_grace_minutes``（缺省 30，自首次顺延起算）
        与连续顺延轮数 ``mergeback.spec_dir_inflight_max_rounds``（缺省 3），任一
        超限 → 回落「告警 + 等待人工处置」通道
        （``_report_mergeback_spec_dir_inflight_stuck``），MUST NOT 无限顺延；
        上限 MUST 先于 ``agents.impl_run_budget``（缺省 6）耗尽收敛（D2 边界约定）。

        自愈（evo-mergeback-archive-residue-selfheal 1.1）：熔断出口前先做归档
        残留只读自愈评估（_assess_archive_residue_selfheal）——命中「同 spec 两侧
        成对且全落 spec/ 两类路径」时补提交归档收尾并立即重放 merge-back，成功
        则正常收尾（零 admin 会话）；未命中/失败走原路径熔断，告警 evidence 增补
        自愈评估摘要。
        """
        entry = self._pm.state_machine.read_one(spec_name) or {}
        now = time.time()
        # first_at 非计数字段，沿用单一落点解析值（首阻缺省=now，自首次顺延
        # 起算窗口）；count 改走锁内原子递增（bump_counters 返回写后值，
        # code-review item 92e18d381825）：原先「read_one 读 → 算 +1 →
        # update_spec 写回」两段式，merge-only 重试定时器链与实现 worker 失败
        # 链并发进入同一 spec 时各持相同旧值写回、丢一次递增、
        # spec_dir_inflight_max_rounds 上限与窗口降级晚触发（同型修复见
        # _record_wip_defer_retry_failure / _handle_merge_back_real_failure）。
        _, first_f = self._parse_defer_accounting(entry, now)
        count = self._pm.state_machine.bump_counters(
            spec_name, {"_merge_retry_count": 1}
        ).get("_merge_retry_count", 0)
        try:
            self._pm.state_machine.update_spec(
                spec_name,
                {
                    "_merge_retry_pending": True,
                    # _merge_retry_count 已由上方 bump_counters 原子递增落盘，
                    # 此处不再并写（防并发写回互相覆盖丢增量）
                    "_merge_retry_first_at": int(first_f),
                    "error": (
                        f"merge-back 顺延等待 spec 目录提交动作解除"
                        f"（{count} 轮，首轮 {int(first_f)}）: {merge_error}"
                    ),
                },
            )
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"顺延记账写入失败 '{spec_name}'（非阻塞）: {e}",
            )
        if self._inflight_defer_over_limit(count, first_f, now):
            # 归档残留只读自愈评估（evo-mergeback-archive-residue-selfheal 1.1，
            # 熔断出口前接入）：脏文件特征命中「归档残留」（同 spec 两侧成对且
            # 全落 spec/ 两类路径）时由框架代为补提交归档收尾并立即重放
            # merge-back，成功则正常收尾（零 admin 会话）；未命中/失败走原路径
            # 熔断（告警 evidence 增补自愈评估摘要）。
            if spec_name in self._archive_selfheal_active:
                # 自愈重放在飞的重入帧：重放体（_retry_merge_back_only）失败链
                # 会再入本分支——不评估、不告警、不再排 Timer，收口由外层自愈帧
                # 统一处置（防嵌套告警与递归）。
                return
            replay_merged, selfheal_evidence = self._assess_archive_residue_selfheal(
                spec_name, merge_info, branch, merge_error,
            )
            if replay_merged:
                # 自动收尾 + 重放成功：_finalize_merge_success 已清顺延记账并
                # 推进 implemented，不熔断、不发 stuck 告警。
                return
            # 超限降级告警去重（code-review item 820ca0230859，与 WIP 车道
            # _report_wip_defer_stuck_once 同款）：daemon 生命周期内每条目至多
            # 一次（防周期节拍刷屏）——merge-only 重试 Timer 链与实现 run 失败链
            # 双路并发时，超限后每个迟到 Timer 各触发一次重试-顺延-再报告，
            # 不去重会重复发多条 major 告警。记账（bump/update_spec）不受去重
            # 影响，仅告警幂等。
            if spec_name not in self._spec_dir_inflight_stuck_notified:
                self._spec_dir_inflight_stuck_notified.add(spec_name)
                self._report_mergeback_spec_dir_inflight_stuck(
                    spec_name, merge_info, branch, merge_error, count, int(first_f),
                    selfheal_evidence=selfheal_evidence,
                )
            return
        self._schedule_merge_retry(spec_name, self._merge_retry_delay_seconds())

    def _inflight_defer_over_limit(self, count: int, first_f: float, now: float) -> bool:
        """spec_dir_inflight 顺延熔断阈值判式（单一落点）。

        窗口（``mergeback.spec_dir_inflight_grace_minutes``，自首阻起算）或连续
        顺延轮数（``mergeback.spec_dir_inflight_max_rounds``）任一超限即熔断。
        _defer_merge_back 熔断出口与周期消费者 _recheck_inflight_deferred_merges
        （本 SPEC 1.3）共用本判式——两处 MUST 保持同一口径（周期消费者只接手
        已超阈值条目，防与存活 Timer 链同拍双驱动）。
        """
        window_exceeded = (now - first_f) / 60.0 >= self._merge_retry_grace_minutes()
        return window_exceeded or count >= self._merge_retry_max_rounds()

    def _assess_archive_residue_selfheal(
        self, spec_name: str, merge_info, branch: str, merge_error: str,
    ) -> tuple:
        """归档残留只读自愈评估（evo-mergeback-archive-residue-selfheal 1.1）。

        熔断出口前调用：脏文件特征命中「归档残留」（共享辅助宽信号 + 同 spec
        两侧成对校验，见 ``core.archive_commit.assess_archive_residue_selfheal``）
        时由框架代为补提交归档收尾并立即重放既有 merge-back 路径。

        - 补提交 add 限定为共享辅助返回的**精确残留路径清单**（对齐
          _archive_auto_commit 的逐路径收窄，禁止退回 ``git add -- spec`` 双前缀
          通配——会把其它 spec 在途草案卷进提交）；提交消息沿用归档收尾形态并
          含目标 spec 名；
        - 补提交前重查工作区（本评估内的扫描即新鲜状态）：残留已被归档自身
          收口完成提交则跳过补提交直接重放 merge；
        - 补提交只 commit 不 push：由重放成功的 merge-back push 携带入库，
          重放失败与 _archive_auto_commit 同语义留待后续 push，不单独加推；
        - 单条至多自动尝试一次（``_archive_residue_selfheal_attempted`` 进程内
          集合记账，daemon 生命周期语义，重启后至多再试一次）；
        - 全程写日志与证据留痕（判据命中与否、补提交 hash、重放结果）。

        Returns: (replay_merged: bool, evidence: str)——replay_merged=True 表示
        自动收尾+重放成功（调用方直接正常收尾）；evidence 为自愈评估摘要，
        供熔断告警 evidence 增补。
        """
        if spec_name in self._archive_residue_selfheal_attempted:
            return False, "自愈已尝试（单条至多一次），本轮不再评估"
        self._archive_residue_selfheal_attempted.add(spec_name)
        scan = scan_archive_residue(self._pm.project_root)
        if scan.error:
            reason = f"评估失败（git status 探测失败）: {scan.error}"
            self._pm.logger.warning("pm_engine", f"归档残留自愈评估 '{spec_name}': {reason}")
            return False, reason
        authorized, reason = assess_archive_residue_selfheal(scan)
        # 观测（本 SPEC 需求 6）：每次自愈评估（命中/未命中）落一条可检索日志
        self._pm.logger.info(
            "pm_engine",
            f"归档残留自愈评估 '{spec_name}': 判据{'命中' if authorized else '未命中'}"
            f"（{reason}）；残留路径 {len(scan.residue_paths)} 条、"
            f"类外脏文件 {len(scan.non_spec_dirty)} 个",
        )
        if not authorized:
            return False, f"判据未命中: {reason}"
        self._archive_selfheal_active.add(spec_name)
        try:
            commit_hash = ""
            if scan.found:
                ok, err, commit_hash = self._heal_commit_archive_residue(scan)
                if not ok:
                    reason = f"判据命中、补提交失败: {err}"
                    self._pm.logger.warning(
                        "pm_engine",
                        f"归档残留自愈 '{spec_name}': {reason}（走原路径熔断等人工）",
                    )
                    return False, reason
                self._pm.logger.info(
                    "pm_engine",
                    f"归档残留自愈 '{spec_name}': 补提交成功 {commit_hash or '(hash 读取失败)'}"
                    f"（{scan.residue_paths}），立即重放 merge-back",
                )
            # else：重查时残留已被归档自身收口完成提交（主树干净）——跳过补提交
            # 直接重放 merge，避免与归档自身收口并发重复提交。
            merged = self._retry_merge_back_only(spec_name)
            if merged:
                self._pm.logger.info(
                    "pm_engine",
                    f"归档残留自愈 '{spec_name}': 重放合并成功，正常收尾"
                    f"（补提交 {commit_hash or '无需，收口已在场'} 由 merge push 携带入库）",
                )
                return True, (
                    f"判据命中，补提交 {commit_hash or '无需（收口已在场）'}"
                    f"后重放合并成功"
                )
            reason = (
                f"判据命中，补提交 {commit_hash or '无需（收口已在场）'}"
                f"后重放合并未成功（提交留待后续 push，与归档收口同语义）"
            )
            self._pm.logger.warning(
                "pm_engine",
                f"归档残留自愈 '{spec_name}': {reason}",
            )
            return False, reason
        finally:
            self._archive_selfheal_active.discard(spec_name)

    def _heal_commit_archive_residue(self, scan: ArchiveResidueScan) -> tuple:
        """补提交归档收尾（只 commit 不 push）。Returns (ok, err, commit_hash)。

        add/commit 限定**精确残留路径清单**（scan.residue_paths，共享辅助已收窄
        到 changes 删除侧 + archive 新增侧，绝不卷入 spec/ 下其它在途草案）；
        残留路径为空（理论不可达，authorized 蕴含 found）时回退 catalog 级
        ``spec`` pathspec 兜底，对齐 _archive_auto_commit。

        add 与 commit 的 pathspec 不同：已 staged 的归档移动呈 ``R`` rename 行，
        旧侧路径已不在工作区也不在索引，``git add`` 对零匹配 pathspec 会 fatal
        退出（git 实证）——add 清单按「工作区存在或索引可匹配」过滤；commit 的
        pathspec 未命中只是过滤器不致命，保留全量清单以完整收录 rename 两侧
        （只带新侧会把旧侧删除留在索引、收口不完整，git 实证）。commit 失败
        best-effort reset 本次 pathspec，不留半状态索引。
        """
        paths = scan.residue_paths or ["spec"]
        root = str(self._pm.project_root)
        label = "、".join(scan.spec_names) if scan.spec_names else "spec"
        commit_msg = f"[fenix] archive: {label} 归档入库"
        addable = [
            p for p in paths
            if (self._pm.project_root / p).exists() or self._path_in_index(p)
        ]
        try:
            if addable:
                add = subprocess.run(
                    ["git", "add", "--"] + addable,
                    cwd=root,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if add.returncode != 0:
                    return False, add.stderr.strip() or f"git add exit {add.returncode}", ""
            commit = subprocess.run(
                ["git", "commit", "-m", commit_msg, "--"] + paths,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if commit.returncode != 0:
                try:
                    subprocess.run(
                        ["git", "reset", "--"] + paths,
                        cwd=root, capture_output=True, text=True, timeout=30,
                    )
                except Exception:  # noqa: BLE001 — best-effort 清理
                    pass
                return (
                    False,
                    commit.stderr.strip() or f"git commit exit {commit.returncode}",
                    "",
                )
        except subprocess.TimeoutExpired:
            return False, "git commit timed out", ""
        except Exception as e:  # noqa: BLE001 — 环境性异常按补提交失败处置
            return False, str(e), ""
        # pathspec 锚定读哈希（同 archive_commit.commit_archive_move 口径：
        # 不用 rev-parse HEAD，防 commit→读取窗口内并发提交记到别人头上）
        commit_hash = ""
        try:
            rev = subprocess.run(
                ["git", "log", "-1", "--format=%H", "--"] + paths,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if rev.returncode == 0:
                commit_hash = rev.stdout.strip()
        except Exception:  # noqa: BLE001 — 哈希读取失败不影响提交本体已落库
            pass
        return True, "", commit_hash

    def _path_in_index(self, rel_path: str) -> bool:
        """pathspec 是否有索引条目（add 清单过滤：已 staged rename 的旧侧无条目）。

        探测失败保守返回 True（把路径留在 add 清单里尝试）——add 对零匹配
        pathspec 的 fatal 会按补提交失败安全落回熔断，不放大。
        """
        try:
            ls = subprocess.run(
                ["git", "ls-files", "--", rel_path],
                cwd=str(self._pm.project_root),
                capture_output=True,
                text=True,
                timeout=30,
            )
            return ls.returncode == 0 and bool(ls.stdout.strip())
        except Exception:  # noqa: BLE001
            return True

    def _merge_retry_grace_minutes(self) -> float:
        """顺延窗口（分钟）：``mergeback.spec_dir_inflight_grace_minutes``，缺省 30。"""
        try:
            return max(
                0.0,
                float(
                    self._pm._get_config("mergeback.spec_dir_inflight_grace_minutes", 30)
                ),
            )
        except (TypeError, ValueError):
            return 30.0

    def _merge_retry_max_rounds(self) -> int:
        """顺延/重试轮数上限：``mergeback.spec_dir_inflight_max_rounds``，缺省 3。"""
        try:
            return max(
                1,
                int(self._pm._get_config("mergeback.spec_dir_inflight_max_rounds", 3)),
            )
        except (TypeError, ValueError):
            return 3

    def _merge_retry_delay_seconds(self) -> float:
        """重试节拍（秒）：``mergeback.spec_dir_inflight_retry_delay_seconds``，缺省 60。"""
        try:
            return max(
                5.0,
                float(self._pm._get_config("mergeback.spec_dir_inflight_retry_delay_seconds", 60)),
            )
        except (TypeError, ValueError):
            return 60.0

    def _schedule_merge_retry(self, spec_name: str, delay: float) -> None:
        """merge-only 重试排程（D2/task 2.3）：短程无预算定时器范式。

        与 ``_schedule_backoff_retry``（backoff.py:107）同构：``threading.Timer``
        到期回调 ``_on_merge_retry``（仅重试合并、不重派实现 run），定时器登记进
        ``_backoff_timers`` 惰性清理。不递增 ``_retry_count``、不递增实现尝试预算
        （未派生新 run）。MUST NOT 复用 ``_schedule_transient_recovery``（该通道带
        ``agents.transient_*`` 熔断与预算语义，语义不同）。
        """
        timer = threading.Timer(
            max(0.5, float(delay)),
            self._on_merge_retry,
            args=(spec_name,),
        )
        timer.daemon = True
        with self._queue_lock:
            self._backoff_timers = [t for t in getattr(self, "_backoff_timers", []) if t.is_alive()]
            self._backoff_timers.append(timer)
        # （code-review item 53c202982773）start 守卫：裸 timer.start() 的启动异常
        # （如环境性 RuntimeError can't start new thread）会沿 _defer_merge_back →
        # _handle_retryable_mergeback_failure → worker 外层 except 转
        # _rollback_failed_dispatch，把一次「仅顺延重试合并」放大成整轮回滚；且
        # _merge_retry_pending 已登记而该通道唯一的自动重试驱动（merge-only
        # Timer）未排成——_recheck_wip_deferred_merges 只扫 _wip_gate_deferred，
        # spec 将悬置 implementing 直至外部巡检。对齐本文件 worker 线程启动守卫
        # 范式（_process_queue 的 Thread.start 同款）：捕获失败、保持登记与定时器
        # 状态一致（摘除死条目 + 清 _merge_retry_pending），再降级走显式重试体——
        # 同步调用 _on_merge_retry 复用既有状态守卫/预算闸门/有界顺延（最坏再排程
        # 一次，_merge_retry_count 递增使顺延受窗口/轮数上限与 stuck 告警兜底），
        # 异常不回灌调用方放大成 run 回滚。
        try:
            timer.start()
        except Exception as e:  # noqa: BLE001 — 环境性启动失败按「未排成」处置
            with self._queue_lock:
                self._backoff_timers = [
                    t for t in self._backoff_timers if t is not timer
                ]
            try:
                self._pm.state_machine.update_spec(
                    spec_name, {"_merge_retry_pending": False},
                )
            except Exception as we:
                self._pm.logger.warning(
                    "pm_engine",
                    f"merge 重试排程失败清账写入 '{spec_name}'（非阻塞）: {we}",
                )
            self._pm.logger.warning(
                "pm_engine",
                f"merge-only 重试定时器启动失败 '{spec_name}' — 已摘除死定时器并清"
                f"_merge_retry_pending，改走显式重试: {type(e).__name__}: {e}",
            )
            try:
                self._on_merge_retry(spec_name)
            except Exception as re_err:  # noqa: BLE001 — 重试体异常不回灌调用方
                self._pm.logger.error(
                    "pm_engine",
                    f"merge 显式重试异常 '{spec_name}': "
                    f"{type(re_err).__name__}: {re_err}",
                )
            return
        self._pm.logger.info(
            "pm_engine",
            f"merge-only 重试已排程 '{spec_name}'（{int(max(0.5, float(delay)))}s，"
            f"不重派实现 run、不计实现预算）",
        )

    def _on_merge_retry(self, spec_name: str) -> None:
        """merge 重试定时器到期回调（D2）：仅重试合并，不重派实现 run。

        与 backoff 家族回调（``_on_instant_fail_recovery`` 等）同构：收尾触发
        ``_process_queue`` 释放并发槽语义。
        """
        self._pm.logger.info(
            "pm_engine",
            f"merge 重试定时器到期 '{spec_name}' — 仅重试合并（不重派实现 run）",
        )
        try:
            self._retry_merge_back_only(spec_name)
        finally:
            self._pm._process_queue()

    def _retry_merge_back_only(self, spec_name: str) -> bool:
        """merge-only 重试体（D2/task 2.4/2.6）：重试合并而非重派实现。

        预算耗尽 MUST NOT 被本通道绕过（task 2.6）：先经 ``_check_impl_budget_exhausted``
        （budget.py:443，与派发前预算闸门同一判据）——耗尽时该闸门自行置 blocked +
        写 ``impl_budget_exhausted`` 告警（人工通道），本通道不再尝试合并。本路径
        未派生新实现 run（D3）：**不递增** 实现尝试预算，也**不需要** ``bump_impl_budget(-1)``
        事后回退（无计数可退；``_reconcile_impl_budget`` 以 runs 实际计数对账，
        本条路径不产生新 run 产物，不构成偏差）。

        Returns: True = 真正执行了 merge-only 合回（走到 ``_finalize_merge_success``
        收口）；False = 本次未执行合并（状态守卫跳过/无分支锚点/预算闸门/合并失败
        各通道）——调用方据此闸门告警闭环：守卫 2.1a 跳过时条目可能是人工已推进
        implemented，不得把人工动作记成「自动合回成功」。
        """
        wm = self._pm.agent_runner.worktree_manager
        entry = self._pm.state_machine.read_one(spec_name) or {}
        # ── 状态守卫（evo-add-wip-defer-merge-retry-consumer 2.1a，两层守卫
        # 的第一层）── status 非 implementing 即跳过并清账后返回：人工/admin
        # 已把条目推进（如 orphaned_state 处置复位 ready、验证链推进
        # testing/implemented）后，迟到的 merge-only 重试不得再动它（重复合并
        # /非法状态转移）。守卫只看 status、不看 _wip_gate_deferred：既有
        # spec_dir_inflight 顺延定时器链的条目仅带 _merge_retry_pending 不带
        # 新标志，既有测试亦不带标志直调，MUST 继续可用。
        if (entry.get("status") or "") != "implementing":
            try:
                self._pm.state_machine.update_spec(
                    spec_name,
                    {
                        "_merge_retry_pending": False,
                        "_merge_retry_count": 0,
                        "_merge_retry_first_at": None,
                        "_wip_gate_deferred": False,
                    },
                )
            except Exception as e:
                self._pm.logger.warning(
                    "pm_engine",
                    f"merge 重试跳过清账失败 '{spec_name}'（非阻塞）: {e}",
                )
            self._pm.logger.info(
                "pm_engine",
                f"merge 重试 '{spec_name}' 跳过：status="
                f"{entry.get('status') or '无'} 非 implementing"
                f"（条目已被人工/admin 推进，不重复合并），顺延/等待记账已清账",
            )
            return False
        branch = entry.get("branch")
        if not branch:
            self._pm.logger.error(
                "pm_engine",
                f"merge 重试 '{spec_name}' 无分支锚点 — 无法仅重试合并，"
                f"保持 implementing 等待人工处置（既有告警/巡检可见）",
            )
            return False
        # 预算闸门（D2/task 2.6）：同派发前闸门，阻塞则不再尝试（闸门自身置 blocked+告警）
        if self._pm._check_impl_budget_exhausted(spec_name):
            self._pm.logger.warning(
                "pm_engine",
                f"merge 重试 '{spec_name}' 触发实现预算闸门 — 已 blocked/告警，"
                f"不再重试合并（D2 不绕过 impl_budget_exhausted）",
            )
            return False
        try:
            merge_info = wm.merge_back_from_branch(branch)
            merge_ok, merge_error = merge_info
        except Exception as e:
            self._pm.logger.error(
                "pm_engine",
                f"merge 重试异常 '{spec_name}'（branch '{branch}'）: {e}",
            )
            return False
        if merge_ok:
            # 合并成功：清顺延记账（_finalize_merge_success 内收口）并推进 implemented
            self._finalize_merge_success(
                spec_name,
                entry.get("implementer_run"),
                branch,
                merge_info,
                list(getattr(wm, "last_stash_pop_conflicts", []) or []),
            )
            return True
        # ── WIP 等待标志在场且失败仍为 wip 阻断形态
        # （evo-add-wip-defer-merge-retry-consumer 2.1b）── 交回等待记账
        # （计数 +1、超限降级），MUST NOT 落入既有可重试分类/指纹熔断：主路径
        # 对 wip_gate_blocked 有同型旁路先例（wip 阻断是「前置拦截」而非
        # 「merge 失败」，熔断会把「等待人工清 WIP」误记成 merge 连败而冻结
        # spec）。真内容冲突（非 wip 形态）不在此列——按设计走既有失败路径，
        # 不尝试自动解决内容冲突。
        if (
            entry.get("_wip_gate_deferred")
            and getattr(merge_info, "wip_gate_blocked", False)
        ):
            self._record_wip_defer_retry_failure(
                spec_name, merge_info, merge_error, branch
            )
            return False
        # 带标志条目落**非 wip** 失败（真内容冲突等）：等待到此结束——先清
        # 标志再走既有失败路径。MUST 先清：既有路径会把条目降级 ready/重派
        # 新实现 run，陈旧标志会让周期消费者在恢复 run 在飞期间触发
        # merge-only 重试（把半成品分支过早合入主树，与在飞 run 收尾竞态——
        # 与 boot 复位写点同一不变式）。
        if entry.get("_wip_gate_deferred"):
            try:
                self._pm.state_machine.update_spec(
                    spec_name, {"_wip_gate_deferred": False},
                )
            except Exception as e:
                self._pm.logger.warning(
                    "pm_engine",
                    f"WIP 等待标志清除失败 '{spec_name}'（非阻塞）: {e}",
                )
        # 再次顺延（有界，自首轮起算）或真失败（fail-open 回既有通道）
        if self._handle_retryable_mergeback_failure(spec_name, merge_info, merge_error, branch):
            return False
        self._handle_merge_back_real_failure(
            spec_name, merge_info, merge_error, branch
        )
        return False

    # ── WIP 延迟合回周期消费者（evo-add-wip-defer-merge-retry-consumer 2.1）──

    @staticmethod
    def _wip_defer_over_limit(count: int, first_f: float, now: float) -> bool:
        """WIP 等待是否超限：窗口（自首阻起算 ≥90 分钟）或轮数（≥6 次）任一命中。

        admin_monitor 豁免判据（2.3）用同一常量的反向谓词（计数<6 且窗口
        <90 分钟），两处 MUST 保持同一口径——超限即「降级人工 + 豁免自动失效」。
        """
        window_exceeded = (now - first_f) / 60.0 >= WIP_DEFER_WINDOW_MINUTES
        return window_exceeded or count >= WIP_DEFER_MAX_ROUNDS

    def _recheck_wip_deferred_merges(self) -> None:
        """周期复查带 WIP 等待标志的 spec（主循环 120 秒节拍调用，2.1/2.2）。

        筛选（两层守卫的第二层）：只对 ``_wip_gate_deferred`` 为真的条目动作；
        ``status=implementing`` 才进入重试，非 implementing 的带标志条目
        （人工/admin 已推进或复位）不重试，但清掉陈旧标志（复位写点不经
        side-car 字段，否则标志存活到重派的新 run、在飞期间误触发合并）。
        逐条 merge-only 重试：重叠文件已干净（人工已提交/
        stash 主树 WIP）即成功走 ``_finalize_merge_success``（implemented
        推进 + 标志清账）并显式闭环 ``mergeback_wip_overlap`` 告警；失败仍为
        wip 阻断则计数 +1（``_retry_merge_back_only`` 内 2.1b 分支），超限
        降级人工处置告警并停止自动重试。

        主树串行化说明：merge-only 体对主树的全部触达（预演闸/WIP 闸/
        stash→merge→pop）都在 ``merge_back_from_branch`` 的 ``_main_tree_lock``
        内（mergeback.py:73），与本方法调用方（daemon 主循环单线程）共同保证
        逐条顺序执行——与人工 merge 并发时由锁串行，人工先行则状态守卫跳过。

        任何异常都不中断扫描（其余条目继续）。
        """
        try:
            specs = self._pm.state_machine.read_all() or {}
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine", f"WIP 等待复查扫描失败（本轮跳过，非阻塞）: {e}",
            )
            return
        for name, entry in specs.items():
            if not entry.get("_wip_gate_deferred"):
                continue
            if (entry.get("status") or "") != "implementing":
                # 安全不变式兜底：标志生命周期不变式是「implementing+带标志 ⇒
                # 无在飞实现 run」，但手动/panel 重派与 admin 处置复位经
                # update_spec/transition 写 ready 不触达 side-car 字段（boot
                # 复位写点正因如此才需要显式清）。运行期见到非 implementing 的
                # 带标志条目即陈旧标志，同守卫 2.1a 的受保护、非阻塞更新清账
                # 后跳过——否则标志存活进重派的新 run（ready→implementing
                # 写点不清标志），下一拍 implementing+带标志即触发 merge-only
                # 重试，把半成品分支过早合入主树、与在飞 run 收尾竞态。
                # 无标志的 spec_dir_inflight _merge_retry_pending 链路已在
                # 上方筛掉，不经此清账。
                try:
                    self._pm.state_machine.update_spec(
                        name,
                        {
                            "_merge_retry_pending": False,
                            "_merge_retry_count": 0,
                            "_merge_retry_first_at": None,
                            "_wip_gate_deferred": False,
                        },
                    )
                except Exception as e:
                    self._pm.logger.warning(
                        "pm_engine",
                        f"WIP 等待标志陈旧清账失败 '{name}'（非阻塞）: {e}",
                    )
                self._pm.logger.info(
                    "pm_engine",
                    f"WIP 等待复查 '{name}' 跳过：status="
                    f"{entry.get('status') or '无'} 非 implementing"
                    f"（人工/admin 已推进，不重复合并），陈旧标志已清账",
                )
                continue
            try:
                self._recheck_one_wip_deferred(name, entry)
            except Exception as e:
                self._pm.logger.warning(
                    "pm_engine", f"WIP 等待复查异常 '{name}'（非阻塞）: {e}",
                )

    def _recheck_one_wip_deferred(self, spec_name: str, entry: dict) -> None:
        """单条带标志条目的周期复查（2.1）：超限先降级，未超限才重试。"""
        now = time.time()
        count, first_f = self._parse_defer_accounting(entry, now)
        # 超限（窗口 ≥90 分钟或轮数 ≥6）：停止自动重试，降级人工处置告警
        # （现场标志保留供人工与取证；orphaned_state 豁免随之自动失效）。
        if self._wip_defer_over_limit(count, first_f, now):
            self._report_wip_defer_stuck_once(
                spec_name, count, int(first_f),
            )
            return
        self._pm.logger.info(
            "pm_engine",
            f"WIP 等待复查 '{spec_name}'（第 {count + 1} 次自动 merge-only 重试，"
            f"首阻 {int(first_f)}）",
        )
        before_status = entry.get("status")
        merged = self._retry_merge_back_only(spec_name)
        after = self._pm.state_machine.read_one(spec_name) or {}
        if (
            merged
            and before_status == "implementing"
            and (after.get("status") or "") == "implemented"
        ):
            # 自动合回成功：显式闭环 mergeback_wip_overlap 告警
            # （stuck-signal-hygiene 处置记录范式，result=resolved）。以
            # merged 为闸：守卫 2.1a 跳过（人工已推进 implemented）时本次
            # 并未合回，不得把人工动作记成「自动合回，无需人工处置」。
            self._resolve_wip_overlap_alert(spec_name)

    def _report_wip_defer_stuck_once(
        self, spec_name: str, count: int, first_at: int,
    ) -> None:
        """超限降级告警（daemon 生命周期内每条目至多一次，防周期节拍刷屏）。"""
        if spec_name in self._wip_defer_degrade_notified:
            return
        self._wip_defer_degrade_notified.add(spec_name)
        self._report_mergeback_wip_defer_stuck(spec_name, count, first_at)

    def _record_wip_defer_retry_failure(
        self, spec_name: str, merge_info, merge_error: str, branch: str,
    ) -> None:
        """WIP 等待条目重试仍被阻断：计数 +1（首阻时刻沿用），超限降级。"""
        entry = self._pm.state_machine.read_one(spec_name) or {}
        now = time.time()
        # first_at 非计数字段，沿用单一落点解析值；count 改走锁内原子递增
        # （bump_counters 返回写后值，code-review item 6c89067c172a）：原先
        # 「read_one 读 → 算 +1 → update_spec 写回」两段式，与主路径顺延
        # 记账、rollback.py 写点并发时丢递增、超限降级晚触发（同型修复见
        # repair_lane._fallback_after_repair）。
        _, first_f = self._parse_defer_accounting(entry, now)
        count = self._pm.state_machine.bump_counters(
            spec_name, {"_merge_retry_count": 1}
        ).get("_merge_retry_count", 0)
        overlap = list(getattr(merge_info, "wip_overlap", []) or [])
        try:
            self._pm.state_machine.update_spec(
                spec_name,
                {
                    # 标志保持 True（仍在等待），error 叠加最新轮次供取证
                    "_wip_gate_deferred": True,
                    # _merge_retry_count 已由上方 bump_counters 原子递增落盘，
                    # 此处不再并写（防并发写回互相覆盖丢增量）
                    "_merge_retry_first_at": int(first_f),
                    "error": (
                        f"mergeback wip overlap deferred "
                        f"(retry {count}/{WIP_DEFER_MAX_ROUNDS}, "
                        f"first_blocked={int(first_f)}): files={overlap} "
                        f"{str(merge_error)[:160]}"
                    ),
                },
            )
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"WIP 等待记账写入失败 '{spec_name}'（非阻塞）: {e}",
            )
        self._pm.logger.info(
            "pm_engine",
            f"WIP 等待重试仍被阻断 '{spec_name}'（{count}/{WIP_DEFER_MAX_ROUNDS} 轮，"
            f"首阻 {int(first_f)}）—— 主树 WIP 未清理，继续等待",
        )
        if self._wip_defer_over_limit(count, first_f, now):
            self._report_wip_defer_stuck_once(spec_name, count, int(first_f))

    def _resolve_wip_overlap_alert(self, spec_name: str) -> None:
        """显式闭环 mergeback_wip_overlap 告警（2.1）。

        沿用 stuck-signal-hygiene 处置记录范式：AdminStore 写 kind=disposition、
        ``result=resolved`` 处置记录（infra_classify.py 审计留痕先例）——自动
        合回成功即闭环，Administrator 不再被该信号召唤。任何异常不阻塞收口。
        """
        try:
            from core.admin_store import AdminStore, DISPOSITION

            store = AdminStore(self._pm.project_root, self._pm.logger)
            store.append(
                {
                    "kind": DISPOSITION,
                    "signal_type": "mergeback_wip_overlap",
                    "spec": spec_name,
                    "severity": "major",
                    "description": (
                        f"SPEC '{spec_name}' 主树 WIP 重叠已解除：周期消费者 "
                        f"merge-only 重试成功，spec 推进 implemented，"
                        f"mergeback_wip_overlap 告警闭环（自动合回，无需人工处置）"
                    ),
                    "action_taken": (
                        "等待期内主树重叠改动已被清理（提交/stash），"
                        "自动 merge-only 重试成功并走 _finalize_merge_success 收口"
                    ),
                    "result": "resolved",
                    "recommended_action": "",
                    "summary": f"wip defer auto-merge resolved: {spec_name}",
                    "admin_run_id": f"wip-defer-consumer:{spec_name}",
                }
            )
            self._pm.logger.info(
                "pm_engine",
                f"mergeback_wip_overlap 告警已闭环（result=resolved）: '{spec_name}'",
            )
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"mergeback_wip_overlap 告警闭环失败 '{spec_name}'（非阻塞）: {e}",
            )

    def _handle_merge_back_real_failure(
        self, spec_name: str, merge_info, merge_error: str, branch: str
    ) -> None:
        """merge-back 真失败：指纹熔断记账 + repair/ready 降级（D2 fail-open 通道）。

        从 ``_run_agent_worker`` 提取（task 0.2 插点之后、非可重试形态的唯一出口），
        供实现 run 失败分支与 merge-only 重试点复用同一判定基准。rehearsed /
        wip_gate_blocked / 可重试形态均已在调用方早退，本方法只处理真失败。
        """
        spec_entry = self._pm.state_machine.read_one(spec_name) or {}
        fp = self._pm._merge_fingerprint(merge_error)
        prev_fp = spec_entry.get("_merge_fp")
        final_error = f"Merge-back failed (fp={fp}): {merge_error}"
        # _merge_streak 走锁内原子递增（bump_counters 返回写后值参与阈值判定，
        # 仿 repair_lane._fallback_after_repair 对 _retry_count 的同型修复，
        # code-review item 6c89067c172a）：原先「read_one 读 → 算 +1 → 并进
        # update_spec 写回」读与写分处两次 STATE 锁临界区，merge-only 重试
        # 定时器、WIP 周期消费者与 worker 失败链并发进入同一 spec 时各持相同
        # 旧值写回、丢一次递增，同指纹熔断晚一轮触发、多烧一整轮实现 run。
        # 指纹切换属重置语义（绝对写 1，无丢增量面），不 bump、随后续
        # update_spec 落盘（streak_bumped=True 时各分支不再并写该字段）。
        if prev_fp == fp:
            streak = self._pm.state_machine.bump_counters(
                spec_name, {"_merge_streak": 1}
            ).get("_merge_streak", 0)
            streak_bumped = True
        else:
            streak = 1
            streak_bumped = False

        # 状态回写保护（fix-startup-double-dispatch）：
        # merge-back 失败回写 ready 前，检查 spec 当前状态——若已在
        # testing/implemented 且存在活跃 tester run，不降级 ready，
        # 只记录冲突并待验证结束后统一处置（避免覆写在飞验证态）。
        current_status = (spec_entry or {}).get("status", "")
        active_tester = (spec_entry or {}).get("tester_run")
        if current_status in ("testing", "implemented") and active_tester:
            self._pm.logger.warning(
                "pm_engine",
                f"Merge-back failed for '{spec_name}' but spec is in "
                f"'{current_status}' with active tester run {active_tester} "
                f"— not downgrading to ready, conflict logged",
            )
            # 记录冲突但不降级状态，保持 testing/implemented。
            # streak 已由 bump_counters 原子递增落盘时不再并入 update_spec
            # （防并发写回互相覆盖丢增量），仅指纹切换重置路径补绝对写。
            conflict_updates: dict = {"error": final_error, "_merge_fp": fp}
            if not streak_bumped:
                conflict_updates["_merge_streak"] = streak
            self._pm.state_machine.update_spec(spec_name, conflict_updates)
            return

        # 配置侧归一经 repair_lane._merge_breaker_threshold 单一落点
        # （code-review item bba1be087ad5 收敛三处同型复制：原 31e28743fe1c
        # 防御语义不变——字符串/null 配置不裸用于比较、None 判空而非 or
        # 兜底、非法回退 2、下限收敛 1——归一规则调整只改读取器一处）。
        breaker_threshold = _merge_breaker_threshold(self._pm)
        if streak >= breaker_threshold:
            # 熔断触发：blocked 后 repair 通道一并停止
            # （spec-merge-circuit-breaker：repair 不绕过熔断）。
            # fix-observability-gaps 2.2：merge 熔断 blocked（自动降级路径）
            self._pm.state_machine.transition(
                spec_name, "blocked",
                trigger_run_id=None, agent_type="implementer", channel="auto",
            )
            # _retry_count: 0 是重置语义（绝对写，无丢增量面）；streak 已
            # bump 时不再并写（同上，防覆盖丢增量）。
            breaker_updates: dict = {
                "error": final_error,
                "_merge_fp": fp,
                "_retry_count": 0,
            }
            if not streak_bumped:
                breaker_updates["_merge_streak"] = streak
            self._pm.state_machine.update_spec(spec_name, breaker_updates)
            self._pm.logger.error(
                "pm_engine",
                f"Circuit breaker tripped for '{spec_name}' (fp={fp}) — spec blocked",
            )
        elif self._pm._should_enter_repair(
            spec_name, merge_info, streak, breaker_threshold
        ):
            # ── repair 通道（add-merge-back-repair-lane）──
            # 语义冲突失败且熔断未触发：派 repair agent 原地修复
            # （把 main 合入分支解决冲突），而非 abort 后全新重派。
            self._pm._dispatch_repair_lane(
                spec_name,
                merge_info,
                branch,
                fp=fp,
                streak=streak,
            )
        else:
            # _retry_count 同型收口：锁内原子递增，写后值不再并入 update_spec
            # （对齐 repair_lane._fallback_after_repair 的注释先例）。
            retries = self._pm.state_machine.bump_counters(
                spec_name, {"_retry_count": 1}
            ).get("_retry_count", 0)
            ready_updates: dict = {
                "status": "ready",
                "error": final_error,
                "_merge_fp": fp,
            }
            if not streak_bumped:
                ready_updates["_merge_streak"] = streak
            self._pm.state_machine.update_spec(spec_name, ready_updates)
            # 本分支重试不受 agents.max_retries 约束，仅由 _merge_streak
            # 同指纹熔断兜底——日志只报 streak/阈值，避免误导。
            self._pm.logger.warning(
                "pm_engine",
                f"Merge-back retry for '{spec_name}' "
                f"(streak {streak}/{breaker_threshold})",
            )

    # ── spec_dir_inflight 顺延周期消费者（evo-mergeback-archive-residue-selfheal 1.3）──

    def _recheck_inflight_deferred_merges(self) -> None:
        """周期复查 spec_dir_inflight 顺延条目（主循环 120 秒节拍调用，1.3）。

        背景：超熔断阈值后 _defer_merge_back 提前 return 不再排 Timer，Timer 链
        中断（含进程重启）后此类条目（``_merge_retry_pending`` 残留）无人接手，
        只能烧 admin 会话等人工。本消费者仿 _recheck_wip_deferred_merges 范式
        兜底接手。

        筛选（防双驱动，MUST）：
        - 只认**无** ``_wip_gate_deferred`` 标志的条目——带标志条目由 WIP 等待
          周期消费者（_recheck_wip_deferred_merges）接手，两车道互不越界；
        - 只接手**已超熔断阈值**（_inflight_defer_over_limit，与 _defer_merge_back
          熔断出口同判式）且仍 ``_merge_retry_pending`` 的条目——未超阈值条目由
          60 秒 merge-only Timer 链驱动（_defer_merge_back 尾部排程），消费者
          跳过，否则与存活 Timer 链同拍双驱动重试同一分支，git index.lock 竞争
          的失败会被 bump_counters 误计入顺延轮数提前熔断；
        - status 非 implementing 的条目跳过（人工/admin 已推进，不重复合并）。

        接手动作：merge-only 重试一次（_retry_merge_back_only）。重试失败链会
        再入 _defer_merge_back：超阈值分支先做归档残留自愈评估（Timer 链缺失
        场景下自愈由此间接生效），未命中/失败则重发 stuck 告警（去重幂等）——
        即「重试或按既有通道维持熔断降级」。接手重试每条目至多一次
        （_inflight_defer_recheck_attempted 记账），失败维持既有熔断告警与人工
        通道，不无限节拍重试。

        任何异常都不中断扫描（其余条目继续）。
        """
        try:
            specs = self._pm.state_machine.read_all() or {}
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"spec_dir_inflight 顺延复查扫描失败（本轮跳过，非阻塞）: {e}",
            )
            return
        now = time.time()
        for name, entry in specs.items():
            try:
                if entry.get("_wip_gate_deferred"):
                    # WIP 等待车道由 _recheck_wip_deferred_merges 接手，不越界
                    continue
                if not entry.get("_merge_retry_pending"):
                    continue
                if (entry.get("status") or "") != "implementing":
                    continue  # 人工/admin 已推进，不重复合并（守卫 2.1a 同款）
                count, first_f = self._parse_defer_accounting(entry, now)
                if not self._inflight_defer_over_limit(count, first_f, now):
                    # 未超阈值：60 秒 merge-only Timer 链驱动，跳过防双驱动
                    continue
                if name in self._inflight_defer_recheck_attempted:
                    continue  # 接手重试每条目至多一次
                self._inflight_defer_recheck_attempted.add(name)
                self._pm.logger.info(
                    "pm_engine",
                    f"spec_dir_inflight 顺延复查 '{name}'：已超熔断阈值且无 Timer 驱动"
                    f"（{count} 轮，首阻 {int(first_f)}）—— 接手 merge-only 重试"
                    f"（每条目至多一次）",
                )
                self._retry_merge_back_only(name)
            except Exception as e:
                self._pm.logger.warning(
                    "pm_engine",
                    f"spec_dir_inflight 顺延复查异常 '{name}'（非阻塞）: {e}",
                )

    def _finalize_merge_success(
        self, spec_name: str, run_id, branch: str, merge_info, conflict_files: list
    ) -> None:
        """merge-back 成功收口（从 ``_run_agent_worker`` 提取，供主路径与重试点复用）。

        与提取前逐字节同语义：合并收尾 ready 态兜底 → implemented 转移 → 字段清账
        （error/_retry_count/_merge_fp/_merge_streak/锁冲突计数/顺延记账）→
        pop 冲突告警 → 任务进度回写 → consume_legacy → verifier 入队。
        """
        # fix-observability-gaps 2.2：implementer merge 成功收口
        # 合并收尾 ready 态兜底（evo-spec-concurrency-flight-guard
        # D3）：status=ready（评审收尾竞态回退残留）时先补记合法转移
        # ready→implementing，再推进 implemented——消除 ready→
        # implemented 非法转移 ERROR 与 83 分钟状态矛盾。
        self._pm._merge_ready_fallback(
            spec_name,
            run_id,
            "implementer",
            branch,
        )
        self._pm.state_machine.transition(
            spec_name, "implemented",
            trigger_run_id=run_id,
            agent_type="implementer", channel="auto",
        )
        self._pm.state_machine.update_spec(
            spec_name,
            {
                "implementer_run": run_id,
                # 记录真实实现分支（带时间戳后缀）：push 时按此分支推送，
                # 否则回退 fenix/<spec> 不存在导致 auto-push 全部失败。
                "branch": branch,
                "error": None,
                "_retry_count": 0,
                "_merge_fp": None,
                "_merge_streak": 0,
                # 零变更哨「连续 3 次」计数清账（与 fast_track.py 成功收口、
                # queue.py 确认型 no-op 分支同款，code-review item b12df5687a55）：
                # 普通实现成功收口不清零会使非连续零变更累计进哨位，
                # 同 spec 后续轮次首次零变更即按 3/3 熔断。
                "_zero_change_attempts": 0,
                # 派发成功即清零锁冲突计数（improve-run-lifecycle-governance D5）
                **self._pm._clear_dispatch_conflict(spec_name),
                # 顺延记账清账（evo-merge-back-spec-dir-inflight-guard D2）：
                # merge 成功即解除顺延态，防陈旧计数污染下一轮
                "_merge_retry_pending": False,
                "_merge_retry_count": 0,
                "_merge_retry_first_at": None,
                # WIP 等待标志清账（evo-add-wip-defer-merge-retry-consumer
                # 1.2）：merge 成功即解除等待态（三条清除写点之一）。
                "_wip_gate_deferred": False,
            },
        )
        # pop 冲突自愈后：被丢弃的 stash 改动文件清单写入 error 字段，
        # 触发 admin 告警（stash 条目保留、可 git stash show 找回，
        # 不阻塞 merge-back 与状态推进）。须放在上面 update_spec(error=None)
        # 之后，避免被清空。见 fix-stashpop-deadlock。
        if conflict_files:
            self._pm._report_stash_pop_conflict(
                spec_name, conflict_files, merge_info=merge_info
            )
        # 写侧确定性回写：把已完成的任务勾选同步进主树 tasks.md
        # （add-task-progress-sync）。任何异常都不阻塞 run 终态主流程。
        try:
            self._pm._sync_task_progress(spec_name)
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"任务进度回写未成功 '{spec_name}'（非阻塞）: {e}",
            )
        # 恢复重派遗产回收（add-recovery-legacy-check 1.3）：后继 run 成功
        # merge 后，该 spec 的遗产已被收编/不再需要，consume_legacy 触发回收。
        # worktree 物理回收在 run_implementer 的 cleanup（成功路径保留分支、
        # 由 merge 前已清理）完成后由既有路径处理；此处仅清内存态遗产登记，
        # 使清扫器不再对其豁免。
        try:
            self._pm.agent_runner.worktree_manager.consume_legacy(spec_name)
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"consume_legacy 失败 '{spec_name}'（非阻塞）: {e}",
            )
        # Immediately queue verifier at FRONT so it runs next
        self._enqueue_front(spec_name, "verifier")
        self._pm.logger.info(
            "pm_engine", f"Implement done, verifier queued for '{spec_name}'"
        )
        # add-impl-ocr-parallel-lane（任务 4.1）：merge-back 成功且 tester 派发的
        # 同一时点启动 ocr 审查车道——与 verifier 车道并行，join 于 testing 出口
        # （_ocr_join_gate）。指纹取 merge 前 _run_agent_worker 持久化的锚点
        # （_ocr_base_commit，写点在调用方 merge 准备段）+ 分支 head；任何异常
        # 都不阻塞 merge 收尾主流程（车道缺席时 join 门禁会幂等补启，见 4.2）。
        try:
            fp = self._ocr_current_fingerprint(spec_name)
            if fp is not None:
                self._start_impl_ocr_lane(spec_name, fp)
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"ocr 车道启动失败 '{spec_name}'（非阻塞，join 门禁兜底补启）: "
                f"{type(e).__name__}: {e}",
            )

    # ── impl ocr 审查车道接线与 testing 出口 join（add-impl-ocr-parallel-lane
    #    任务 4.1-4.6）───────────────────────────────────────────────────────

    def _impl_ocr_enabled(self) -> bool:
        """车道总开关（verify.impl_code_review）。关闭时 join 门禁零校验放行。"""
        from core.config import ConfigLoader

        return ConfigLoader.get_impl_code_review_enabled(self._pm.config)

    def _git_merge_base_main(self, branch: str) -> str | None:
        """``git merge-base main <branch>``（merge 前捕获 ocr 指纹 base 分量）。

        失败（非 git 仓库/分支不存在/超时）返回 None——调用方以分支 head 兜底
        （空 diff → 0 findings 优雅降级，design D4）。
        """
        try:
            r = subprocess.run(
                ["git", "-C", str(self._pm.project_root), "merge-base", "main", branch],
                capture_output=True, text=True, timeout=15,
            )
            if r.returncode == 0:
                return r.stdout.strip() or None
        except Exception:  # noqa: BLE001
            pass
        return None

    def _git_rev_parse(self, ref: str) -> str | None:
        """``git rev-parse <ref>``（车道指纹 head 分量）。失败返回 None。"""
        try:
            r = subprocess.run(
                ["git", "-C", str(self._pm.project_root), "rev-parse", ref],
                capture_output=True, text=True, timeout=15,
            )
            if r.returncode == 0:
                return r.stdout.strip() or None
        except Exception:  # noqa: BLE001
            pass
        return None

    def _ocr_current_fingerprint(self, spec_name: str) -> dict | None:
        """join 读侧权威指纹 ``(branch, merge_base, head_commit)``（任务 4.3）。

        base 分量取 spec entry 持久化的 ``_ocr_base_commit``（merge 前锚点捕获），
        缺失时以 head 兜底（与车道写侧 `base or head` 回退同构，两侧相等才视为
        新鲜）。分支不可得返回 None（无审查对象）。
        """
        entry = self._pm.state_machine.read_one(spec_name) or {}
        branch = entry.get("branch")
        if not branch:
            return None
        head = self._git_rev_parse(branch)
        if not head:
            return None
        base = entry.get("_ocr_base_commit") or head
        return {"branch": branch, "merge_base": base, "head_commit": head}

    def _read_ocr_artifact(self, spec_name: str) -> dict | None:
        """读主树车道产物 ``.fenix/verify-progress/<spec>/code-review.json``。

        缺失/损坏/非对象 → None（join 按「产物缺失」分支处理）。
        """
        path = (
            Path(self._pm.project_root)
            / ".fenix" / "verify-progress" / spec_name / "code-review.json"
        )
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def _ocr_lane_running(self, spec_name: str) -> bool:
        """车道单飞判据：在飞登记表命中即 True。"""
        with self._ocr_lane_lock:
            return bool(self._ocr_lane_inflight.get(spec_name))

    def ocr_lane_busy(self, spec_name: str | None = None) -> bool:
        """在飞 impl-ocr 车道公开判定（fix-fasttrack-implemented-deadstate 2.1/D3）。

        - 带参：按该 spec 判 ``_ocr_lane_inflight``（engine 恢复三条件③用
          ——重入前确认本 spec 无在飞车道，不与在飞收尾竞态）；
        - 无参：任一在飞即 busy（fenixd ``_is_idle`` 第五维用）；
        - 内部异常按 busy 处理（宁紧勿松：车道在飞期间自愈重启会 SIGTERM
          杀掉在飞车道 run，与 ``_is_idle`` 既有异常策略一致）。

        公开方法封装——调用方（engine / fenixd）MUST NOT 跨层直读
        ``_ocr_lane_inflight`` 私有字典。
        """
        try:
            if spec_name is None:
                with self._ocr_lane_lock:
                    return bool(self._ocr_lane_inflight)
            # 单 spec 分支委托 _ocr_lane_running（同锁同语义，code-review item
            # de22e0ca08c4）——锁不可重入，MUST NOT 持锁内再调（会死锁）。
            return self._ocr_lane_running(spec_name)
        except Exception:  # noqa: BLE001 — 判定异常按 busy 处理（宁紧勿松）
            return True

    def _start_impl_ocr_lane(self, spec_name: str, fingerprint: dict) -> str | None:
        """幂等启动 ocr 审查车道线程（任务 4.1/4.2）。

        在飞单飞去重（返回 None）；线程体跑 ``runner.run_impl_ocr``（维护型
        run 形态：不占 spec 预算、不走 _execute_agent），完成回调
        ``_on_impl_ocr_lane_finished`` 唤醒 join 重评。返回启动的标记串
        （"started"）或 None（未启动：开关关/已在飞/分支不可得/线程创建
        失败——失败时已在锁内回滚在飞登记）。

        Args:
            fingerprint: ``_ocr_current_fingerprint`` 产物（branch/merge_base/
                head_commit）。base 缺失时以 head 兜底（空 diff 优雅降级）。
        """
        if not self._impl_ocr_enabled():
            return None
        branch = fingerprint.get("branch")
        head = fingerprint.get("head_commit")
        if not branch or not head:
            return None
        base = fingerprint.get("merge_base") or head
        with self._ocr_lane_lock:
            if self._ocr_lane_inflight.get(spec_name):
                return None
            self._ocr_lane_inflight[spec_name] = True

        def _run() -> None:
            run_id = spec_name
            try:
                artifact = self._pm.agent_runner.run_impl_ocr(
                    spec_name=spec_name,
                    branch=branch,
                    base_commit=base,
                    head_commit=head,
                )
                if isinstance(artifact, dict) and artifact.get("run_id"):
                    run_id = str(artifact["run_id"])
            except Exception as e:  # noqa: BLE001 — 车道线程异常由产物缺失分支兜底
                self._pm.logger.warning(
                    "pm_engine",
                    f"ocr 车道线程异常 '{spec_name}'（非阻塞）: "
                    f"{type(e).__name__}: {e}",
                )
            finally:
                with self._ocr_lane_lock:
                    self._ocr_lane_inflight.pop(spec_name, None)
                try:
                    self._on_impl_ocr_lane_finished(spec_name, run_id)
                except Exception as e:  # noqa: BLE001 — 回调异常不影响主流程
                    self._pm.logger.warning(
                        "pm_engine",
                        f"ocr 车道完成回调异常 '{spec_name}'（非阻塞）: "
                        f"{type(e).__name__}: {e}",
                    )

        # code-review item b52d9c1760b6：在飞登记已在锁内写入，而摘除只在线程体
        # finally——Thread 构造/start（锁外）失败（如 RuntimeError can't start
        # new thread）时 finally 永不执行，登记即泄漏：_ocr_join_await_lane 据此
        # 判「车道在飞」走 defer，完成回调却永不触发，spec 永久停等 testing。
        # 故此处须捕获失败、锁内回滚登记后返回 None，让 join 的 fail-open 放行
        # 分支生效（第二调用点 merge 收尾 fire-and-forget 同样受益）。
        try:
            threading.Thread(
                target=_run, name=f"impl-ocr-lane-{spec_name}", daemon=True
            ).start()
        except Exception as e:  # noqa: BLE001 — 环境性启动失败按「未启动」处置
            with self._ocr_lane_lock:
                self._ocr_lane_inflight.pop(spec_name, None)
            self._pm.logger.warning(
                "pm_engine",
                f"ocr 车道线程启动失败 '{spec_name}'（已回滚在飞登记，"
                f"fail-open）: {type(e).__name__}: {e}",
            )
            return None
        # ocr 审查 finding#5 第二道防线：新车道启动即旧修复义务作废——打回轮
        # directive 在重派实现 prompt 构建时已被消费（注入先于 merge），此处
        # 清除防 pass 出口未覆盖的残留形态（冻结/人工接管的打回轮后再实现）。
        self._ocr_clear_findings_directive(spec_name)
        self._pm.logger.info(
            "pm_engine",
            f"ocr 车道已启动 '{spec_name}': {branch} "
            f"{str(base)[:8]}..{str(head)[:8]}",
        )
        return "started"

    def _ocr_clear_findings_directive(self, spec_name: str) -> None:
        """清除修复轮 directive 文件（ocr 审查 finding#5：义务消费即失效）。

        接线两道防线：join 放行（pass 出口）= 修复义务消费完毕；新车道启动 =
        旧义务作废（防 pass 后残留 directive 被同 spec 后续无关实现轮——
        verified 后 bug-found 打回、verifier 修复、人工返工——的 prompt_builder
        误读误注入）。文件缺失幂等静默；删除失败仅 WARNING（下次启动/放行重试）。
        """
        path = (
            Path(self._pm.project_root)
            / ".fenix" / "verify-progress" / spec_name
            / "ocr_findings_directive.json"
        )
        try:
            path.unlink()
        except FileNotFoundError:
            return
        except OSError as e:
            self._pm.logger.warning(
                "pm_engine",
                f"ocr findings directive 清理失败 '{spec_name}'（非阻塞）: {e}",
            )
            return
        self._pm.logger.info(
            "pm_engine", f"ocr findings directive 已清除 '{spec_name}'"
        )

    def _ocr_join_pending_fields(self, origin: str) -> dict:
        """停等-唤醒 pending 标量字段（STATE 字典字段不回传，一律标量）。"""
        return {"_ocr_join_wait": 1, "_ocr_join_agent": origin}

    @staticmethod
    def _ocr_join_pending_cleared() -> dict:
        """pending 字段清账形态（join 出口三支共用）。"""
        return {"_ocr_join_wait": None, "_ocr_join_agent": None}

    def _ocr_join_clear_pending(self, spec_name: str) -> None:
        """清 pending 停等标记（放行/裁决完成时调用；失败静默）。"""
        try:
            self._pm.state_machine.update_spec(
                spec_name, self._ocr_join_pending_cleared()
            )
        except Exception:  # noqa: BLE001
            pass

    def _ocr_join_await_lane(self, spec_name: str, origin: str, fingerprint: dict,
                             reason: str) -> str:
        """停等分支：落 pending 标量 + 幂等触发车道 + 返回 defer（任务 4.2）。

        车道启动失败且不在飞 → MUST NOT 无限停等：fail-open 放行 + WARNING
        留痕（对齐 unavailable 的环境降级语义）。
        """
        # pending 先落盘、后触发车道（code-review item 19de3c05e9f2）：车道
        # 线程体及其完成回调都晚于 Thread.start，而 start 又晚于标记写入——
        # 自启车道无论多快完成，回调读 pending 必然晚于写入，不存在「回调于
        # 标记落盘前空转、此后再无唤醒、spec 带停等标记永久滞留 testing」
        # 窗口（该窗口只能靠外部 stuck/orphan 巡检兜底）。pending 落盘包
        # try/except（与 _ocr_join_clear_pending 同款惯例）：写失败不得打断
        # _ocr_join_gate 的 pass/defer/reject 返回契约，且此路径 MUST NOT
        # 返回 defer——pending 缺席时唤醒回调幂等空转，故 fail-open 放行
        # （对齐下方车道缺席降级语义）；此时车道尚未启动，不产生空转回调。
        try:
            self._pm.state_machine.update_spec(
                spec_name, self._ocr_join_pending_fields(origin)
            )
        except Exception as e:  # noqa: BLE001
            self._pm.logger.warning(
                "pm_engine",
                f"ocr join pending 标记写入失败 '{spec_name}'（fail-open 放行）: "
                f"{type(e).__name__}: {e}",
            )
            return "pass"
        started = None
        try:
            started = self._start_impl_ocr_lane(spec_name, fingerprint)
        except Exception as e:  # noqa: BLE001
            self._pm.logger.warning(
                "pm_engine",
                f"ocr 车道幂等触发失败 '{spec_name}': {type(e).__name__}: {e}",
            )
        # 未自启时锁内复核在飞（code-review item dd27b3a77576）：覆盖幂等触发
        # 的既有车道恰在「在飞判定」与「pending 落盘」之间完成的形态——其回调
        # 读到缺席标记即幂等空转，此后再无唤醒。复核不在飞即按 fail-open 语义
        # 清标记放行；见在飞则回调必然晚于标记写入读到（pop 未发生 ⇒ 读在写
        # 后），defer 停等安全。自启路径（started="started"）由上方先写后启
        # 的顺序保证回调必见标记（19de3c05e9f2），无需复核。
        if started is None and not self._ocr_lane_running(spec_name):
            self._pm.logger.warning(
                "pm_engine",
                f"ocr join 停等放弃 '{spec_name}'（车道未启动且不在飞，"
                f"fail-open 放行）: {reason}",
            )
            self._ocr_join_clear_pending(spec_name)
            self._ocr_clear_findings_directive(spec_name)
            return "pass"
        self._pm.logger.info(
            "pm_engine",
            f"ocr join 停等 '{spec_name}'（{reason}）——spec 停留 testing，"
            f"车道完成回调唤醒重评",
        )
        return "defer"

    def _ocr_join_reject(self, spec_name: str, entry: dict, actionable: list,
                         rounds: int, artifact: dict) -> str:
        """gate 档打回（任务 4.4）：testing → bug-found → 修复轮重派。

        与验证失败既有打回同通道（零新状态）：transition bug-found →
        error 注明 ocr findings → ``_ocr_fix_rounds`` 递增持久化 → 写修复轮
        directive（任务 5.1 join 侧写点）→ ``_on_spec_bug_found`` 原地打回重派。
        """
        sm = self._pm.state_machine
        lane_run_id = str(artifact.get("run_id") or "")
        sm.transition(
            spec_name, "bug-found",
            trigger_run_id=entry.get("tester_run") or None,
            agent_type="planner-judge", channel="auto",
        )
        sm.update_spec(
            spec_name,
            {
                "error": (
                    f"ocr 收尾审查发现 {len(actionable)} 条未裁决 findings"
                    f"（gate 档打回，修复轮 {rounds + 1}/1）"
                ),
                # _ocr_fix_rounds 绝对写回而非 bump_counters 原子递增（code-review
                # item 99ba2e45e362）：修复轮上限硬编码为 1（gate 侧 rounds < 1 即
                # 打回、directive max_rounds=1、>=1 转台账放行），两路并发各持同一
                # 旧值写回最多丢一次递增，影响被「>=1 即终止」封顶。前提钉死：若
                # 放宽修复轮上限，MUST 先改用 bump_counters 锁内原子递增取写后值
                # （对齐 _retry_count/_merge_streak 同型站点），防丢增量。
                "_ocr_fix_rounds": rounds + 1,
                **self._ocr_join_pending_cleared(),
            },
        )
        self._write_ocr_findings_directive(spec_name, actionable, rounds + 1)
        self._pm.logger.warning(
            "pm_engine",
            f"ocr join gate 打回 '{spec_name}': {len(actionable)} 条 findings，"
            f"修复轮 {rounds + 1}/1（lane run {lane_run_id}）",
        )
        self._pm._on_spec_bug_found(
            spec_name, failure_class="product", run_id=lane_run_id
        )
        return "reject"

    def _write_ocr_findings_directive(self, spec_name: str, findings: list,
                                      round_no: int) -> None:
        """写修复轮 directive 文件（任务 5.1 join 侧写点，prompt_builder 读）。

        原子替换；写失败仅 WARNING（修复轮注入缺席时实现者按无义务轮处理，
        gate 轮次上限仍兜底防死循环）。
        """
        path = (
            Path(self._pm.project_root)
            / ".fenix" / "verify-progress" / spec_name
            / "ocr_findings_directive.json"
        )
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # 原子落盘对齐 infra_breaker.py 写入范式（code-review item
            # c208b7542b6e）：同目录 mkstemp 生成唯一 tmp 名（join gate 多入口
            # 并发生成同一 spec 的 directive 时不再共用固定 tmp 路径，消除交错写
            # 把半截内容 replace 进正式文件的窗口）+ fsync（掉电/崩溃不留截断
            # 内容被下轮实现 prompt 误读）+ os.replace 原子替换。
            fd, tmp_str = tempfile.mkstemp(
                prefix=f".{path.name}.",
                suffix=".tmp",
                dir=str(path.parent),
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(
                        json.dumps(
                            {
                                "spec": spec_name,
                                "round": round_no,
                                "max_rounds": 1,
                                "findings": findings,
                            },
                            ensure_ascii=False,
                            indent=2,
                        )
                    )
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_str, str(path))
            finally:
                if os.path.exists(tmp_str):
                    try:
                        os.unlink(tmp_str)
                    except OSError:
                        pass
        except OSError as e:
            self._pm.logger.warning(
                "pm_engine",
                f"ocr findings directive 写入失败 '{spec_name}'（非阻塞）: {e}",
            )

    def _ocr_transfer_findings_to_ledger(self, spec_name: str, findings: list,
                                         lane_run_id: str, why: str) -> None:
        """findings 转 code-review 台账（任务 4.5/4.6，status=open）。

        台账条目词表仅 open/resolved/ignored（无 deferred，业务语义 deferred
        以 open + 描述注记承载）；spec_name 归属本 spec（spec_map 按同源指纹
        函数现算）；finding 附处置 reason（拼入 description）。落账异常仅
        WARNING——转台账是放行路径的观测增强，不阻塞 join。
        """
        try:
            from core.code_review import fingerprint as cr_fingerprint, upsert_findings

            mapped = []
            spec_map = {}
            for f in findings:
                if not isinstance(f, dict):
                    continue
                file_ = str(f.get("path") or "")
                content = str(f.get("content") or "").strip()
                if not file_:
                    continue
                category = str(f.get("category") or "general")
                title = content[:120] or "ocr finding"
                reason = str(f.get("reason") or "").strip()
                desc = content
                if reason:
                    desc = f"{content}\n\n[impl-ocr 处置注记] {reason}"
                mapped.append(
                    {
                        "file": file_,
                        "line": f.get("start_line") or 1,
                        "severity": str(f.get("severity") or "info"),
                        "category": category,
                        "title": title,
                        "description": desc,
                        "suggestion": str(f.get("suggestion") or ""),
                    }
                )
                spec_map[cr_fingerprint(file_, category, title)] = spec_name
            if not mapped:
                return
            stats = upsert_findings(
                self._pm.project_root,
                mapped,
                review_id=lane_run_id or f"impl-ocr-{spec_name}",
                review_kind="impl-ocr",
                spec_map=spec_map,
            )
            self._pm.logger.info(
                "pm_engine",
                f"ocr findings 转台账 '{spec_name}'（{why}）: "
                f"inserted={stats.get('inserted', 0)} "
                f"updated={stats.get('updated', 0)}",
            )
        except Exception as e:  # noqa: BLE001
            self._pm.logger.warning(
                "pm_engine",
                f"ocr findings 转台账失败 '{spec_name}'（非阻塞）: "
                f"{type(e).__name__}: {e}",
            )

    def _ocr_join_gate(self, spec_name: str, origin: str) -> str:
        """testing 出口 ocr join 门禁（任务 4.2-4.6 的机械裁决单点）。

        由 ``pipeline._apply_verified``（verified transition 前）与
        ``fast_track._fast_track_advance_to_verified``（testing 转移后）调用。

        Returns:
            - ``"pass"``：放行，调用方继续 verified 推进；
            - ``"defer"``：车道未就绪——已落 pending 停等标记/已幂等触发车道，
              调用方 MUST 停止推进（spec 停留 testing，tester 不重派）；
            - ``"reject"``：gate 档打回已在本方法内完成（bug-found + 修复轮
              重派），调用方直接返回。
        """
        from core.config import ConfigLoader

        if not self._impl_ocr_enabled():
            # 与其余 pass 出口对齐：停等标记残留会误导车道回调与巡检判别
            self._ocr_join_clear_pending(spec_name)
            self._ocr_clear_findings_directive(spec_name)
            return "pass"
        fingerprint = self._ocr_current_fingerprint(spec_name)
        if fingerprint is None:
            # 无实现分支/分支 ref 不可得：无审查对象，放行留痕
            self._pm.logger.warning(
                "pm_engine",
                f"ocr join 放行 '{spec_name}'（分支指纹不可得，无审查对象）",
            )
            self._ocr_join_clear_pending(spec_name)
            self._ocr_clear_findings_directive(spec_name)
            return "pass"
        artifact = self._read_ocr_artifact(spec_name)
        status = artifact.get("status") if isinstance(artifact, dict) else None

        if status == "unavailable":
            # 任务 4.6：unavailable 两档均放行 + WARNING 审计留痕
            self._pm.logger.warning(
                "pm_engine",
                f"ocr 车道产物 unavailable，join 放行 '{spec_name}': "
                f"{str(artifact.get('reason') or '')[:200]}",
            )
            self._ocr_join_clear_pending(spec_name)
            self._ocr_clear_findings_directive(spec_name)
            return "pass"

        if status == "completed":
            fp = artifact.get("fingerprint") or {}
            if (
                fp.get("branch"),
                fp.get("merge_base"),
                fp.get("head_commit"),
            ) != (
                fingerprint["branch"],
                fingerprint["merge_base"],
                fingerprint["head_commit"],
            ):
                # 任务 4.3：指纹 stale fail-closed——不采信不放行，触发按当前
                # 指纹重跑（在跑单飞去重），spec 停等。
                return self._ocr_join_await_lane(
                    spec_name, origin, fingerprint,
                    reason="产物指纹不新鲜（stale fail-closed），按当前指纹重跑",
                )
            findings = artifact.get("findings")
            if not isinstance(findings, list):
                findings = []
            actionable = [
                f for f in findings
                if isinstance(f, dict) and f.get("disposition") != "rejected"
            ]
            self._ocr_join_clear_pending(spec_name)
            if not actionable:
                self._ocr_clear_findings_directive(spec_name)
                return "pass"  # 双绿放行
            mode = ConfigLoader.get_impl_code_review_mode(self._pm.config)
            lane_run_id = str(artifact.get("run_id") or "")
            if mode == "advisory":
                # 任务 4.6：advisory 恒写台账后放行，永不打回
                self._ocr_transfer_findings_to_ledger(
                    spec_name, actionable, lane_run_id, "advisory 档放行"
                )
                self._ocr_clear_findings_directive(spec_name)
                return "pass"
            entry = self._pm.state_machine.read_one(spec_name) or {}
            rounds = self._parse_int_field(entry, "_ocr_fix_rounds", 0)
            if rounds < 1:
                return self._ocr_join_reject(
                    spec_name, entry, actionable, rounds, artifact
                )
            # 任务 4.5：修复轮上限（_ocr_fix_rounds >= 1）仍出现的 findings
            # 全部转台账（status=open、spec 归属本 spec），join 放行防死循环。
            self._ocr_transfer_findings_to_ledger(
                spec_name, actionable, lane_run_id,
                f"修复轮上限（{rounds}）后仍出现，转台账放行",
            )
            self._ocr_clear_findings_directive(spec_name)
            return "pass"

        # 产物缺失/损坏（车道未运行或未完成）→ 幂等触发 + 停等（任务 4.2，
        # 覆盖 daemon 重启恢复经重派路径再派 verifier、无 merge-back 事件的形态）
        return self._ocr_join_await_lane(
            spec_name, origin, fingerprint, reason="产物缺失或车道未完成"
        )

    def _on_impl_ocr_lane_finished(self, spec_name: str, run_id: str) -> None:
        """车道完成回调（任务 4.1/4.2 唤醒侧）：重评 join 并应用 deferred 推进。

        仅当 spec 停留在 testing 且 pending 停等标记在场时动作；其余形态
        （tester 未完成/规格已迁移/旧回调）幂等空转。
        """
        sm = self._pm.state_machine
        entry = sm.read_one(spec_name) or {}
        if not entry.get("_ocr_join_wait"):
            return  # tester 未完成或无停等义务——tester 出口时 join 门禁即时裁决
        if entry.get("status") != "testing":
            return  # spec 已迁移（冻结/人工接管等）——不再唤醒推进
        origin = entry.get("_ocr_join_agent") or "planner-judge"
        self._pm.logger.info(
            "pm_engine",
            f"ocr 车道完成唤醒 join 重评 '{spec_name}'（origin={origin}，"
            f"lane run {run_id}）",
        )
        decision = self._ocr_join_gate(spec_name, origin)
        if decision == "pass":
            self._resume_verified_after_ocr(spec_name, origin)
        # "reject"：打回已在 gate 内完成；"defer"：gate 幂等重触发新车道后继续停等

    def _resume_verified_after_ocr(self, spec_name: str, origin: str) -> None:
        """停等唤醒后的 verified 推进续做（任务 4.2）。

        - pipeline 起源（origin=planner-judge）：重载验证报告后重入
          ``_apply_verified``——门禁（进度核对/报告闸/洗白门）幂等重跑，通过后
          完成 testing → verified；
        - fast-track 起源：重入 ``_fast_track_advance_to_verified``——
          implemented→testing 已发生，同状态转移幂等保证安全。
        """
        from types import SimpleNamespace

        entry = self._pm.state_machine.read_one(spec_name) or {}
        tester_run = entry.get("tester_run") or "ocr-join-resume"
        try:
            if origin == "fast-track":
                self._fast_track_advance_to_verified(
                    spec_name, SimpleNamespace(run_id=tester_run)
                )
                return
            report = None
            try:
                from core.verify_report import _load_report_json

                report = _load_report_json(self._pm.project_root, spec_name)
            except Exception:  # noqa: BLE001 — 报告重载失败按空失败集记录
                report = None
            # 经门面单跳调用（design D3 规则 3，code-review item 525fd816c134）：
            # 不再穿透 self._pm._verification._apply_verified 私有链——pipeline
            # 私有方法重命名时只在门面注册表一处断链，而非 ocr 每次停等唤醒即
            # AttributeError 被下方 except 吞成 WARNING、spec 滞留 testing。
            self._pm._apply_verified(
                spec_name, SimpleNamespace(run_id=tester_run), report
            )
        except Exception as e:  # noqa: BLE001 — 续做失败不崩溃，留下次唤醒/扫描兜底
            self._pm.logger.warning(
                "pm_engine",
                f"ocr join 续做 verified 失败 '{spec_name}'（非阻塞）: "
                f"{type(e).__name__}: {e}",
            )

    def _run_spec_review_worker(self, spec_name: str):
        """评审 run worker 线程体（fix-spec-review-blocking-dispatch 1.8）。

        - 四步链（锚点落盘 → 快照 → 执行 → 机械收口）保留在
          ``SpecReviewManager.dispatch_review`` 内、在本线程调用栈闭合；
        - 在飞登记释放时点 MUST NOT 晚于锚点落盘（design D4 重入安全性）：
          构造完成后、调用 ``dispatch_review`` 之前先释放 ``_active_reviews``
          的本次登记（幂等 discard），锚点落盘后由 ``reviewer_run`` 判据接力
          ——否则同一 worker 线程内的续 attempt 重入 ``dispatch_review`` 入口
          见自己仍在集合中而被拒，评审收口被自己挡住；
        - 同一锁段内在 ``_reviews_dispatching`` 置位过渡在飞登记（code-review
          item e3d1d53906cb）：释放后、锚点落盘前的过渡窗口对外仍判在飞
          （判据消费点 ``_review_entry_ready``），堵住同 spec 第二条评审条目
          并发派发窗口；收尾 finally 幂等释放，重试接力不被延迟；
        - 四步链**内部**异常已由 ``dispatch_review`` 自吞并走
          ``_handle_review_failure``（重试/冻结），不会传播到这里；
        - 四步链**之外**异常（构造 SpecReviewManager 失败、快照/日志路径异常
          等）：此时 spec 可能停在 reviewing 且 reviewer_run 未被推进，MUST
          显式收口——清 ``reviewer_run``、保持 ``reviewing``、重新入队
          （spec-review-recovery spec Scenario「worker 内异常走统一回滚」），
          MUST NOT 只记日志了事（``_rollback_failed_dispatch`` 不含
          spec-review 分支，直接复用等同于只记日志）。
        """
        # 构造在释放前：构造失败时登记仍保留，由上层 finally 兜底释放。
        from core.pm_engine.spec_review import SpecReviewManager

        review_manager = SpecReviewManager(
            self._pm.project_root,
            self._pm.state_machine,
            self._pm.agent_runner,
            self._pm,
            self._pm.config,
            self._pm.logger,
        )
        # 释放时点：不晚于四步链锚点 reviewer_run 落盘
        with self._queue_lock:
            # 过渡登记与释放同一锁段完成（code-review item e3d1d53906cb）：
            # _active_reviews 释放后、锚点落盘前的窗口内由 _reviews_dispatching
            # 接力在飞判定（判据见 _review_entry_ready），防同 spec 第二条
            # 评审条目在窗口内被并发派发；收尾 finally 幂等释放。
            self._reviews_dispatching.add(spec_name)
            self._active_reviews.discard(spec_name)
        try:
            review_manager.dispatch_review(spec_name)
        except Exception as e:
            self._pm.logger.error(
                "pm_engine", f"评审 worker 异常（四步链外）: {spec_name}: {e}"
            )
            try:
                # 显式收口：清锚点、保持 reviewing、重新入队由队列接力
                # （recovery 的 reviewing 分支作为最终兜底拾取）。
                self._pm.state_machine.update_spec(
                    spec_name,
                    {
                        "reviewer_run": None,
                        "error": f"spec-review-incomplete: worker 异常: {e}",
                    },
                )
                entry = self._pm.state_machine.read_one(spec_name) or {}
                if entry.get("status") == "reviewing":
                    self._pm._enqueue(spec_name, "spec-review")
            except Exception as e2:
                self._pm.logger.error(
                    "pm_engine",
                    f"评审 worker 异常收口失败（交 recovery 兜底）: {spec_name}: {e2}",
                )
        finally:
            # 过渡在飞登记释放（幂等，code-review item e3d1d53906cb）：worker
            # 收工即摘除，重试入队的接力条目由 _run_agent_worker finally 的
            # _process_queue 在摘除后重扫派发，重试接力不被本登记延迟
            # （D4 重入安全性不受影响——dispatch_review 入口防重派判据仍只查
            # _active_reviews）。
            with self._queue_lock:
                self._reviews_dispatching.discard(spec_name)
