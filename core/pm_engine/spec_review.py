"""spec_review.py — SPEC 方案评审门禁的核心逻辑。

实现评审 run 的派发、结果消费、写入边界校验、故障重试与人工恢复入口。
"""

import hashlib
import json
import logging
import re
import subprocess
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

from core.state_machine import (
    SpecStatus,
    FROZEN_FIELD,
    FREEZE_ERROR_PREFIX,
)
from core.agent_runner.runner import AgentRunner
from core.agent_runner.prompt_builder import (
    spec_review_result_path,
    spec_review_result_status_whitelist,
)

_logger = logging.getLogger("fenixd.pm_engine.spec_review")

# 评审尝试上限（首次 + 最多 2 次重试，常量名自解释）
MAX_REVIEW_ATTEMPTS = 3

# 评审否决自动复评上限（2026-09-15 评审误判事故）：`blocking` 由 LLM 自分类，
# 存在把「文档内部矛盾/遗漏」误判为「方向不成立」的残差。首次 rejected 不直接
# 冻结转人工，而是回 reviewing 自动复评；连续达该次数仍 rejected 才认定方向
# 确不成立、冻结转人工。取 2 = 「初次否决 + 1 次复评确认」。
MAX_REJECT_REDO = 2

# 审核收尾回退守卫（evo-spec-concurrency-flight-guard D1）：评审收口
# （approved/repaired → 回退 ready）前重读 spec 当前 status，属这三类说明存在
# 在飞实现 run 或在实现后段（implementer 已派发/合并已推进）——跳过回退，
# 仅清 reviewer_run 锚点 + 落 `_review_skipped_result` 审计侧车。
IN_FLIGHT_IMPL_STATES = ("implementing", "implemented", "testing")

# 写入边界校验：SPEC 目录相对路径前缀
SPEC_CHANGES_PREFIX = "spec/changes/"

# ── infra 失败指纹（evo-run-failure-classification-circuitbreaker D1）──────
# 评审 API 批量失败（403 网关拒绝 / 402 余额不足 / 429 限流 / quota/budget 耗尽 /
# rate limit / provider 侧熔断信号 / CLI 进程级崩溃）同属 infra——链路级问题，
# 非 spec 内容问题。指纹匹配大小写不敏感；"Exit code: 1" 不得一律判 infra
# （评审器内容失败同样 exit 1），仅当退出码非 0/1（进程级崩溃）才归 infra。
_INFRA_FINGERPRINTS = (
    "403",
    "402",
    "429",
    "quota",
    "budget",
    "余额",
    "insufficient balance",
    "rate limit",
    "provider circuit open",
    "provider chain exhausted",
    "model_chain_preflight_failed",
)
# CLI 进程级崩溃：error 含 "Exit code: <N>" 且 N 非 0/1
_CLI_EXIT_CODE_RE = re.compile(r"Exit code:\s*(-?\d+)")


class SpecReviewManager:
    """评审管理器：负责评审 run 的派发、结果消费、边界校验、重试与恢复。"""

    def __init__(
        self,
        project_root: Path,
        state_machine,
        agent_runner: AgentRunner,
        pm_engine,
        config: dict,
        logger=None,
    ):
        self.project_root = project_root
        self.state_machine = state_machine
        self.agent_runner = agent_runner
        self.pm_engine = pm_engine
        self.config = config
        self.logger = logger or _logger

    # ── 评审派发 ────────────────────────────────────────────────

    def dispatch_review(self, spec_name: str) -> bool:
        """为指定 SPEC 派发一次评审 run，并在其收工后机械收口。

        本方法是评审的**唯一派发收口点**，「锚点落盘 → 快照 → 阻塞执行 → 消费结果」
        四步全在此闭合（评审门禁接线修复）：

        - **锚点（``reviewer_run``）在 run 启动之前写入**。``run_spec_review`` 为同步
          阻塞（分钟级）；若沿用「run 收工后才写锚点」的旧序，阻塞期间第二条派发通道
          （event_bus 轮询与 ``_on_spec_drafted`` 直调各一）读到锚点为空会再派一次，
          两个评审 Agent 并发改写同一 SPEC 目录（并发写者事故）。
        - **run 收工后立即 ``consume_review_result`` 收口**（approved/repaired → ready、
          rejected → blocked）。此前该消费点在全部生产路径上零调用——评审结果写盘后
          无人读，SPEC 永久停在 reviewing，随 daemon 重启被反复重派。

        Returns: True 表示评审 run 已执行收工；False 表示被拒或 run 执行失败。
        """
        # 链路级熔断短路（evo-run-failure-classification-circuitbreaker D2）：
        # spec-review 链路熔断窗口内直接返回不派发；冷却到期自动恢复重试。
        breaker = getattr(self.pm_engine, "infra_breaker", None)
        if breaker is not None:
            cond = breaker.condition("spec-review")
            if cond == "broken":
                remaining = breaker.cooldown_remaining("spec-review")
                self.logger.info(
                    "spec_review", f"评审派发熔断短路: {spec_name}，冷却剩余 {remaining}s"
                )
                return False
            if cond == "recovered":
                # 冷却到期自动恢复：落恢复 SIGNAL 记录（D3）
                self.pm_engine._emit_infra_breaker_event(
                    "recovered", spec_name, "", breaker.get_state("spec-review")
                )
        # 防重派（fix-spec-review-blocking-dispatch 2.4 改口径）：
        # ① ``_active_reviews`` 命中 → 拒绝：覆盖「条目已出队、锚点尚未落盘」
        #    的窗口。异步化后本入口只由 worker（``_run_spec_review_worker``）
        #    调用——worker 在调用前已释放本次登记（释放时点 ≤ 锚点落盘，
        #    design D4 重入安全性），故本判据主要防御其它并发直调通道。
        # ② 锚点非空 → MUST 经 ``reviewer_in_flight`` 取**在飞结论**：
        #    ``in_flight == True`` 拒派；仅 ``reason == "stale"``（陈旧锚点，
        #    run 已终态）才清锚点后继续。MUST NOT 按「锚点非空」直接自清——
        #    ``_should_defer_for_reviewer`` 的判定异常分支为 fail-open
        #    ``(False, None)``，直接自清会在评审仍在跑时放行并发派发。
        #    判定异常 fail-closed 拒派（记 WARNING，recovery 兜底）——评审
        #    自身派发宁可不发，与实现派发侧的 fail-open 取相反保守方向。
        # 重入保护：content 失败重试入队（``_handle_review_failure`` 清锚点后
        # 重新入队 → 新 worker）进入本入口时 ``_active_reviews`` 已被
        # ``_run_spec_review_worker`` 释放、锚点已被收口路径清除——两者皆空
        # 放行，评审不被自己挡住（spec-review-recovery spec Scenario「续
        # attempt 不被自身在飞登记否决」）。
        pm_engine = self.pm_engine
        if pm_engine is not None and pm_engine.is_review_in_flight(spec_name):
            self.logger.info("spec_review", f"评审条目已在飞（队列/未收口）: {spec_name}")
            return False
        entry = self.state_machine.read_one(spec_name)
        if not entry:
            self.logger.warning("spec_review", f"SPEC 不存在: {spec_name}")
            return False
        reviewer_run = entry.get("reviewer_run")
        if reviewer_run:
            try:
                in_flight, reason = self.agent_runner.reviewer_in_flight(
                    spec_name, reviewer_run
                )
            except Exception as e:
                # 判定异常 fail-closed 拒派（不自行清锚点）
                self.logger.warning(
                    "spec_review",
                    f"在飞评审判定异常 '{spec_name}'（fail-closed 拒派）: {e}",
                )
                return False
            if in_flight:
                self.logger.info("spec_review", f"已有在飞评审 run: {spec_name}")
                return False
            if reason == "stale":
                self.logger.warning(
                    "spec_review",
                    f"陈旧评审锚点（run 已终态）清理后继续派发: "
                    f"{spec_name} run={reviewer_run}",
                )
                self.state_machine.update_spec(spec_name, {"reviewer_run": None})
        # 检查评审尝试次数
        try:
            attempts = int(entry.get("_review_attempts", 0) or 0)
        except (TypeError, ValueError):
            attempts = 0
        if attempts >= MAX_REVIEW_ATTEMPTS:
            # 耗尽即转冻结转人工（fix-blocked-freeze-classification 2.2）：
            # 改走 freeze_for_human「冻结 + 告警」成对入口——admin 对
            # 「评审器连续失败」无杠杆（模型链/配置问题）；冻结后
            # admin_monitor 的 blocked_stuck 豁免生效。
            error_msg = (
                f"{FREEZE_ERROR_PREFIX}原状态 reviewing · "
                f"spec-review-incomplete: 评审尝试已达上限"
                f"（{MAX_REVIEW_ATTEMPTS}）"
            )
            self.state_machine.freeze_for_human(
                spec_name,
                error=error_msg,
                signal_type="spec-review-incomplete",
                severity="major",
                description=(
                    f"'{spec_name}' 评审尝试已达上限（{MAX_REVIEW_ATTEMPTS}），"
                    "评审器连续失败，需人工排查（模型链/配置问题）"
                ),
                evidence=(
                    f"spec={spec_name}; run_id={entry.get('reviewer_run') or '无'}; "
                    f"attempts={MAX_REVIEW_ATTEMPTS}"
                ),
                recommended_action=(
                    "人工排查评审链路（模型链/配置/结果硬门）；排查后经 "
                    "dashboard/CLI 解冻——解冻恢复原状态 reviewing，daemon "
                    "自动重派评审；或直接撤销该 spec"
                ),
                alert_callback=self.pm_engine._send_human_escalation_alert,
                extra_updates={"reviewer_run": None, "_review_attempts": 0},
            )
            return False

        # ① 锚点先落盘：预生成 run_id，保证 STATE 里的 reviewer_run 与实际 run 一致
        run_id = f"spec-review-{spec_name}-{int(time.time())}"
        self.state_machine.update_spec(spec_name, {"reviewer_run": run_id})

        # ② 派发前快照（写入边界校验的基线）
        snapshot = self._take_snapshot(spec_name)
        snapshot_dir = self.project_root / ".fenix" / "spec-review" / spec_name
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = snapshot_dir / "snapshot.json"
        try:
            snapshot_path.write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            self.logger.warning("spec_review", f"快照保存失败: {spec_name}: {e}")

        # ③ 阻塞执行评审 run（正常收工或异常后返回）
        attempt_started_at = time.time()
        result = None  # 异常路径下不绑定（修复验证轮 BUG：UnboundLocalError）
        try:
            result = self.agent_runner.run_spec_review(spec_name, run_id=run_id)
            run_ok = bool(getattr(result, "success", False))
            run_err = getattr(result, "error", None)
        except Exception as e:  # noqa: BLE001 — 派发异常须收口锚点，不得留残余
            run_ok, run_err = False, str(e)
        if not run_ok:
            self.logger.error("spec_review", f"评审 run 执行失败: {spec_name}: {run_err}")

            # ③0 add-freeze-stop-inflight-agents 3.5：冻结终止在失败分类之前拦截——
            # 评审 run 因 spec 冻结被终止（frozen_terminated=True）：写
            # _frozen_hold 标记、保持 reviewing、不重派、不递增 _review_attempts、
            # 不触发熔断。MUST NOT 走 _classify_run_failure 的 content/infra
            # 分支（_INFRA_FINGERPRINTS 含裸 "503"，评审 run 的 503 重试会被
            # 误判 infra 而递增计数/熔断）。
            # 判定用 `is True` 严格等值（修复验证轮 BUG）：MagicMock 等替身
            # 在属性访问时自动生成 truthy 子对象，`if getattr(...)` 裸布尔会把
            # 非冻结的替身结果误判为冻结终止、跳过重试递增——生产结果
            # AgentRunResult.frozen_terminated 为显式 bool，严格等值判定不受影响。
            if result is not None and getattr(result, "frozen_terminated", False) is True:
                rev_err = getattr(result, "error", None) or run_err or ""
                frozen_err = (
                    f"评审 run 因 spec 冻结被终止（进度已保全，解冻后续做）"
                    f"{': ' + rev_err if rev_err else ''}"
                )
                self.state_machine.mark_frozen_hold(spec_name, frozen_err)
                self.logger.warning(
                    "spec_review",
                    f"评审 run 因 spec 冻结被终止 — hold-state '{spec_name}'"
                    f"（保持 reviewing，不重派）: {frozen_err}",
                )
                return False

            # ① 结果捞回（run 失败时尝试从转录代写落盘，避免白烧重试）
            salvage = getattr(self.agent_runner, "_salvage_spec_review_result", None)
            if callable(salvage):
                try:
                    salvage(spec_name, run_id)
                except Exception as e:  # noqa: BLE001 — 捞回失败不得阻断判定
                    self.logger.warning("spec_review", f"结果捞回异常: {spec_name}: {e}")

            # ② 产物优先判定（D1）：产物已合法落盘 → 按产物消费，exit code 失败仅
            #    降级 warning 日志留痕，不递增 _review_attempts、不重派
            artifact_ok, artifact_data = self._artifact_landed_valid(
                spec_name, run_started_at=attempt_started_at
            )
            if artifact_ok:
                self.logger.warning(
                    "spec_review",
                    f"评审 run exit code 失败但产物已落盘，优先按产物消费"
                    f"（exit code={run_err}）: {spec_name}",
                )
                self.consume_review_result(spec_name, run_started_at=attempt_started_at)
                return True

            # ③ 产物不合法 → 走既有重试语义（attempt 递增）
            self._handle_review_failure(spec_name, f"评审 run 执行失败: {run_err}")
            return False
        self.logger.info("spec_review", f"评审 run 已收工: {spec_name} run_id={run_id}")

        # ③b 结果捞回（2026-09-15 事故修复）：评审 run 正常收工但从未调用 Write，
        # 把结果 JSON 当正文 fenced 代码块吐出。此处从转录代写落盘，避免整轮白烧
        # 重试。抽不出/已存在时不动作，交下方硬门按既有语义处理。
        salvage = getattr(self.agent_runner, "_salvage_spec_review_result", None)
        if callable(salvage):
            try:
                salvage(spec_name, run_id)
            except Exception as e:  # noqa: BLE001 — 捞回失败不得阻断收口
                self.logger.warning("spec_review", f"结果捞回异常: {spec_name}: {e}")

        # ④ 机械收口：结果缺失/越界由 _handle_review_failure 重试（保持既有语义）
        self.consume_review_result(spec_name, run_started_at=attempt_started_at)
        return True

    # ── 评审结果消费 ────────────────────────────────────────────

    def consume_review_result(self, spec_name: str, run_started_at: float | None = None) -> bool:
        """消费评审结果：校验结果硬门与写入边界，按 status 机械收口。

        Args:
            run_started_at: 本轮 attempt 的启动 epoch 秒（供结果文件 mtime 新鲜度
                校验，防上轮残留合法文件替本轮放行——fix-verdict-read-failclosed
                D2 同款）。None 时跳过新鲜度校验（直调/测试兼容）。

        Returns: True 表示消费成功（状态已变更），False 表示消费失败（需重试）。
        """
        entry = self.state_machine.read_one(spec_name)
        if not entry:
            return False
        run_id = entry.get("reviewer_run")
        if not run_id:
            return False

        # 结果硬门校验（复用 _check_agent_result_artifact，spec-review 分支
        # 2026-09-15 已真接线：缺失/空/非白名单 status/陈旧 mtime 均由此拦截）
        err = self.agent_runner._check_agent_result_artifact(
            spec_name, "spec-review", run_started_at=run_started_at
        )
        if err is not None:
            self.logger.warning("spec_review", f"结果硬门校验失败: {spec_name}: {err}")
            self._handle_review_failure(spec_name, err)
            return False

        # 读取结果文件
        result_path = spec_review_result_path(self.project_root, spec_name)
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            self.logger.warning("spec_review", f"结果文件读取失败: {spec_name}: {e}")
            self._handle_review_failure(spec_name, f"结果文件读取失败: {e}")
            return False

        # 写入边界校验。MUST NOT 再走 artifact 分类（code-review item 4b9f59b8717f）：
        # 边界错误（approved 带 repairs / repaired 无 repairs / repairs 路径非法）
        # 的产物在 `_artifact_landed_valid` 眼里是**合法**的（它只看文件可解析 +
        # status 白名单 + mtime + 快照一致性，不看 repairs 与 status 的一致性），
        # 故旧实现会判 artifact → 再次 consume_review_result → 再次命中同一（未被
        # 修正的）边界错误 → 无限递归，最终 RecursionError 被 worker 捕获后重新入队
        # 退化为活锁。显式 forbade_artifact + 透传 run_started_at（旧实现顺带跳过
        # mtime 新鲜度校验）。
        boundary_err = self._check_write_boundary(spec_name, data)
        if boundary_err:
            self.logger.warning("spec_review", f"写入边界校验失败: {spec_name}: {boundary_err}")
            self._handle_review_failure(
                spec_name, boundary_err, allow_artifact=False, run_started_at=run_started_at
            )
            return False

        # 按 status 机械收口
        status = data.get("status")
        if status not in spec_review_result_status_whitelist:
            self.logger.warning("spec_review", f"未知 status: {status}")
            self._handle_review_failure(spec_name, f"未知 status: {status}")
            return False

        if status in ("approved", "repaired"):
            # ── 审核收尾回退守卫（evo-spec-concurrency-flight-guard D1）──
            # 评审 run 收尾时，实现 run 可能已在飞（implementer 已派发 →
            # implementing；或已合并 → implemented/testing）。此刻把状态回退到
            # ready 会：① 产生「ready 态残留」→ 后续 merge 收尾 ready→implemented
            # 非法转移 ERROR（16:29:24Z 事故实证）；② ready 残留把同一 spec 拉进
            # 重复派发面。故本分支最前重读 spec 当前 status——属在飞实现状态则
            # 跳过回退，仅清 reviewer_run 锚点 + 落审计侧车。
            current = self.state_machine.read_one(spec_name) or {}
            cur = current.get("status")
            if cur in IN_FLIGHT_IMPL_STATES:
                self.logger.info(
                    "spec_review",
                    f"评审收尾遇在飞实现 run（status={cur}），跳过回退: {spec_name}",
                )
                # 清锚点（否则 reviewer_run 永久残留，与 D2 派发前校验合流后
                # 阻塞后续派发——本 SPEC 自造死锁）；审计侧车留痕本轮评审结论
                # 未被状态机消费（不写 error 字段，防事件总线自触发反馈环，D0）。
                self.state_machine.update_spec(
                    spec_name,
                    {
                        "reviewer_run": None,
                        "_review_attempts": 0,
                        "_review_skipped_result": f"{status}@result-path={result_path}",
                    },
                )
                # 早于下方 :300 的 _on_spec_ready 调用返回（MUST NOT 调用它：
                # 此刻无待派发实现 run，且若调用会被 D2 判定为在飞评审而顺延，
                # 语义重复）。
                return True
            # 转 ready 并触发实现调度（fix-observability-gaps 2.2：自动来源标注）
            self.state_machine.transition(
                spec_name, "ready",
                trigger_run_id=run_id, agent_type="spec-review", channel="auto",
            )
            self.state_machine.update_spec(
                spec_name,
                {
                    "reviewer_run": None,
                    "_review_attempts": 0,
                    # 通过即清零否决计数（含自动复评后通过）：下一次评审从零起算
                    "_review_rejections": 0,
                    "error": None,
                },
            )
            # 触发实现调度
            self.pm_engine._on_spec_ready(spec_name)
            self.logger.info("spec_review", f"评审通过: {spec_name} status={status}")
            return True
        elif status == "rejected":
            # 评审否决 → 冻结转人工（fix-blocked-freeze-classification D3）：
            # admin 对「方案被否」无操作杠杆（2026-09-14 事故：17 分钟 admin
            # run 结论「无需介入」把原样 spec 弹回 reviewing → 下轮评审再次否决，
            # 整轮纯烧 token），故不打裸 blocked 而是 frozen=True + 人工升级
            # 告警，使 admin_monitor 的 blocked_stuck 豁免生效。
            #
            # 有界自动复评（2026-09-15 评审误判事故）：`blocking` 由 LLM 自分类，
            # 存在把「文档内部矛盾/遗漏」误判为「方向不成立」的残差（实证：
            # refactor-agent-runner-module 一轮 rejected→人工修补→复评 repaired）。
            # 故首次 rejected MUST NOT 立刻冻结转人工——改回 reviewing 并重派一次
            # 复评（带上一轮 blocking 摘要），把误判自愈在体系内；连续
            # MAX_REJECT_REDO 次（含首次）仍 rejected 才认定方向确不成立，冻结转人工。
            # 计数存 `_review_rejections`（`_` 前缀随 STATE 往返持久化）；任何一次
            # approved/repaired 收口即清零（见上一分支的 update_spec）。
            findings = data.get("findings") or []
            # findings 元素类型校验（code-review item 29ed238af688）：findings 由
            # LLM 产出，元素非 dict 时旧实现 f.get(...) 抛 AttributeError 逃出
            # consume_review_result，绕过失败分类/重试与冻结路径。非 dict 元素
            # 直接忽略（不进 blocking 摘要）。
            if not isinstance(findings, list):
                findings = []
            blocking = [
                f
                for f in findings
                if isinstance(f, dict) and f.get("severity") == "blocking"
            ]
            blocked_summary = (
                "; ".join(f.get("detail", "") for f in blocking) if blocking else "无详情"
            )

            entry_now = self.state_machine.read_one(spec_name) or {}
            try:
                rejections = int(entry_now.get("_review_rejections", 0) or 0)
            except (TypeError, ValueError):
                rejections = 0
            rejections += 1

            if rejections < MAX_REJECT_REDO:
                # 未达上限：不冻结，回 reviewing 触发复评
                self.state_machine.update_spec(
                    spec_name,
                    {
                        "reviewer_run": None,
                        "_review_attempts": 0,
                        "_review_rejections": rejections,
                        "error": (f"spec-review-rejected: {blocked_summary}"),
                    },
                )
                self.state_machine.transition(
                    spec_name, "reviewing",
                    trigger_run_id=run_id, agent_type="spec-review", channel="auto",
                )
                self.logger.warning(
                    "spec_review",
                    f"评审否决（第 {rejections}/{MAX_REJECT_REDO} 次）→ 自动复评"
                    f"（未冻结，避免误判转人工）: {spec_name}；"
                    f"blocking: {blocked_summary[:200]}",
                )
                # 复评派发（fix-spec-review-blocking-dispatch 2.6）：rejected 后
                # 自动复评改为入队 spec-review 由队列接力（不再递归直调
                # dispatch_review——收口线程内递归调用会与在飞判据互相否决）。
                # agent_runner 为 None 的 CLI 场景跳过，由 daemon recovery 的
                # reviewing 分支拾取。上轮 blocking 摘要已写入 error，经
                # _prev_error_section 注入复评 prompt（复评者据此区分
                # 「前提证伪」与「文档不一致」）。
                if self.agent_runner is not None and self.pm_engine is not None:
                    self.pm_engine._enqueue(spec_name, "spec-review")
                return True

            # 达上限：方向确不成立，冻结转人工（原语义）
            error_msg = (
                f"{FREEZE_ERROR_PREFIX}原状态 reviewing · "
                f"spec-review-rejected: {blocked_summary}"
            )
            self.state_machine.freeze_for_human(
                spec_name,
                error=error_msg,
                signal_type="spec-review-rejected",
                severity="major",
                description=(
                    f"'{spec_name}' 方案连续 {rejections} 次被评审否决"
                    f"（已自动复评 {rejections - 1} 次仍不成立），需人工修订方案"
                    f"或撤销（blocking findings: {blocked_summary}; "
                    f"评审 run={run_id}）"
                ),
                evidence=(
                    f"spec={spec_name}; run_id={run_id}; "
                    f"rejections={rejections}; findings={blocked_summary}"
                ),
                recommended_action=(
                    "人工修订 spec 方案（proposal.md/design.md）后经 dashboard/"
                    "CLI 解冻——解冻恢复原状态 reviewing，daemon 自动重派评审；"
                    "或直接撤销该 spec"
                ),
                alert_callback=self.pm_engine._send_human_escalation_alert,
                extra_updates={
                    "reviewer_run": None,
                    "_review_attempts": 0,
                    "_review_rejections": 0,
                },
            )
            self.logger.info(
                "spec_review",
                f"评审否决（第 {rejections}/{MAX_REJECT_REDO} 次，达上限）"
                f"已冻结转人工: {spec_name}",
            )
            return True
        else:
            # 理论上不会到这里
            self._handle_review_failure(spec_name, f"未知 status: {status}")
            return False

    # ── 写入边界校验 ────────────────────────────────────────────

    def _take_snapshot(self, spec_name: str) -> dict:
        """派发前对 SPEC 目录与工作区脏文件记录快照。

        返回快照 dict，包含：
        - spec_files: {相对路径: 内容哈希}——SPEC 目录完整性硬门依据（删除即越界）
        - dirty_files: {相对路径: 内容哈希}（仅 git status --porcelain 列出的脏文件）
          ——仅供 `_verify_snapshot` 记 WARNING 留痕与「新增文件」去重，不作硬门
        """
        spec_dir = self.project_root / "spec" / "changes" / spec_name
        snapshot = {"spec_files": {}, "dirty_files": {}}
        if not spec_dir.is_dir():
            return snapshot
        # 记录 SPEC 目录内所有文件的内容哈希
        for file in spec_dir.rglob("*"):
            if file.is_file():
                rel = str(file.relative_to(self.project_root))
                try:
                    content = file.read_bytes()
                    h = hashlib.md5(content).hexdigest()
                    snapshot["spec_files"][rel] = h
                except OSError:
                    pass
        # 记录工作区脏文件的内容哈希
        try:
            result = subprocess.run(
                ["git", "-C", str(self.project_root), "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if line.startswith("??") or line.startswith(" M") or line.startswith("M "):
                        # 简化处理：取文件路径（去掉状态前缀）
                        parts = line.split()
                        if len(parts) >= 2:
                            path = parts[1]
                            # 忽略 SPEC 目录内的文件（已经单独记录）
                            if path.startswith(SPEC_CHANGES_PREFIX):
                                continue
                            full = self.project_root / path
                            if full.is_file():
                                try:
                                    content = full.read_bytes()
                                    h = hashlib.md5(content).hexdigest()
                                    snapshot["dirty_files"][path] = h
                                except OSError:
                                    pass
        except (subprocess.SubprocessError, OSError):
            pass
        return snapshot

    def _verify_snapshot(self, spec_name: str, snapshot: dict) -> Optional[str]:
        """收工后比对快照，检出越界写入。

        Returns: None 表示通过，否则返回错误信息。

        **只对可归因信号开硬门**（该变动有且仅有「评审者越界」一种解释）：

        - SPEC 目录内文件被删除——评审者只被授权就地修补，删除必为越界。

        工作区扫描（既存脏文件被改动、SPEC 目录外新增未跟踪文件）**不作为硬门**：
        评审 run 同步阻塞数分钟且 cwd = 主树，期间任何并发写者（人工编辑、其他
        会话、其他 run）触碰主树都会命中，两者都无法与评审者越界区分。2026-09-14
        evo-item-retention-doc-tracking 因此连丢三份评审结果（约 $25）并空转至尝试
        耗尽。现改为记 WARNING 留痕、放行——评审者的真实写入边界由 repairs 路径
        合法性（`_check_write_boundary` 步骤 1）与结果契约共同钉死。
        """
        spec_dir = self.project_root / "spec" / "changes" / spec_name
        if not spec_dir.is_dir():
            return f"SPEC 目录不存在: {spec_dir}"

        # 检查 SPEC 目录内文件哈希是否变化
        for rel, old_hash in snapshot.get("spec_files", {}).items():
            full = self.project_root / rel
            if not full.exists():
                return f"SPEC 目录内文件被删除: {rel}"
            try:
                content = full.read_bytes()
                new_hash = hashlib.md5(content).hexdigest()
                if new_hash != old_hash:
                    # 文件被修改，这是允许的（repaired 状态）
                    pass
            except OSError:
                return f"无法读取文件: {rel}"

        # 工作区脏文件变动：非归因，仅留痕
        changed_dirty = []
        for rel, old_hash in snapshot.get("dirty_files", {}).items():
            full = self.project_root / rel
            if not full.exists():
                continue  # 文件被删除，可能不是评审者所为
            try:
                content = full.read_bytes()
                new_hash = hashlib.md5(content).hexdigest()
                if new_hash != old_hash:
                    changed_dirty.append(rel)
            except OSError:
                pass
        if changed_dirty:
            self.logger.warning(
                "spec_review",
                f"评审期间工作区脏文件被改动（非归因，放行）: {spec_name}: "
                f"{', '.join(sorted(changed_dirty))}",
            )

        # SPEC 目录外新增未跟踪文件：非归因（并发写者新建文件同样命中），仅留痕
        added_untracked = []
        try:
            result = subprocess.run(
                ["git", "-C", str(self.project_root), "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if line.startswith("??"):
                        parts = line.split()
                        if len(parts) >= 2:
                            path = parts[1]
                            if not path.startswith(SPEC_CHANGES_PREFIX):
                                # 检查是否在快照中已存在
                                if path not in snapshot.get("dirty_files", {}):
                                    added_untracked.append(path)
        except (subprocess.SubprocessError, OSError):
            pass
        if added_untracked:
            self.logger.warning(
                "spec_review",
                f"评审期间 SPEC 目录外新增未跟踪文件（非归因，放行）: {spec_name}: "
                f"{', '.join(sorted(added_untracked))}",
            )

        return None

    def _check_write_boundary(self, spec_name: str, review_data: dict) -> Optional[str]:
        """校验评审 run 的写入边界：repairs 路径合法性、SPEC 目录完整性、status 与改动一致。

        工作区扫描（脏文件变动 / 目录外新增文件）只留痕不拦截——非归因信号，
        见 `_verify_snapshot`。

        Returns: None 表示通过，否则返回错误信息。
        """
        spec_dir = self.project_root / "spec" / "changes" / spec_name
        if not spec_dir.is_dir():
            return f"SPEC 目录不存在: {spec_dir}"

        # 1. repairs 路径合法性（解析后归属校验，code-review item bdec829dca96）
        # 评审结果 JSON 由 LLM 产出（不可信输入），此处是写入边界的唯一硬门。
        # 旧实现只做字符串前缀 startswith("spec/changes/")：`spec/changes/../foo.txt`
        # 未归一化即可穿过，且 `/` 形态的绝对/跨 spec 路径只要文件存在也能通过。
        # 改为 Path 解析 + 归属校验：归一化后唯一合法落点必须是**本 spec** 目录
        # （spec/changes/<spec_name>/）内的文件。
        spec_root = (self.project_root / "spec" / "changes").resolve()
        allowed_dir = (spec_root / spec_name).resolve()
        repairs = review_data.get("repairs") or []
        # repairs 元素类型校验（code-review item 29ed238af688）：repairs 由 LLM
        # 产出，可能非列表/元素非 dict；旧实现 repair.get(...) 会抛 AttributeError
        # 逃出 consume_review_result，绕过本文件的失败分类/重试与冻结路径。
        # 非法形态按「非法产物」直接判失败（fail-closed），不进 repairs 校验循环。
        if not isinstance(repairs, list):
            return f"repairs 非列表（非法产物）: {type(repairs).__name__}"
        for repair in repairs:
            if not isinstance(repair, dict):
                return f"repairs 元素非对象（非法产物）: {repair!r}"
            path = repair.get("path", "")
            if not isinstance(path, str) or not path:
                return f"repairs 路径越界: {path!r}"
            candidate = Path(path)
            if candidate.is_absolute():
                return f"repairs 路径越界（绝对路径）: {path}"
            resolved = (self.project_root / candidate).resolve()
            # 归一化后必须落在本 spec 目录内（startswith 于父目录且不等于父目录本身）
            if resolved != allowed_dir and allowed_dir not in resolved.parents:
                return f"repairs 路径越界（须落在 {spec_name}/ 内）: {path}"
            if not resolved.exists():
                return f"repairs 路径不存在: {path}"

        # 2. 快照比对（需要从临时文件加载派发前快照）
        snapshot_path = self.project_root / ".fenix" / "spec-review" / spec_name / "snapshot.json"
        if snapshot_path.exists():
            try:
                snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
                snapshot_err = self._verify_snapshot(spec_name, snapshot)
                if snapshot_err:
                    return snapshot_err
            except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
                # 读取失败不再静默放行（code-review item 5d38e8dd6478 / 6a3f77476d0f）：
                # 快照是 SPEC 目录完整性硬门（删除检测）的唯一依据，缺失/损坏时
                # 旧实现 pass 静默放行、且无日志——越界删除将无人发现。Non-UTF8
                # 内容抛 UnicodeDecodeError（非 OSError 子类）此前还会直接逃出本方法。
                # 记 WARNING 明确降级（保留既有放行语义，但使降级可观测）。
                _logger.warning(
                    "spec_review: 快照读取失败 '%s'（%s，跳过目录完整性比对，"
                    "删除检测降级）: %s",
                    spec_name,
                    type(e).__name__,
                    e,
                )

        # 3. status 与改动一致性
        status = review_data.get("status")
        if status == "approved" and repairs:
            return "approved 状态伴随文件改动"
        if status == "repaired" and not repairs:
            return "repaired 状态无修补清单"
        # rejected 必须无修补清单：既判「前提/方向不成立」又改了文档属自相矛盾。
        # 判据依据（2026-09-15 评审误判事故）：能落在 SPEC 目录内修复的问题
        # 一律属 repairable（agent prompt 的「severity 判定标准」已固化该口径）；
        # 若评审确实改了文档使方案成立，正确结论是 repaired 而非 rejected。
        if status == "rejected" and repairs:
            return "rejected 状态伴随文件改动"

        return None

    # ── 故障重试 ────────────────────────────────────────────────

    def _artifact_landed_valid(
        self, spec_name: str, run_started_at: float | None = None
    ) -> Tuple[bool, Optional[dict]]:
        """校验评审 run 产物是否已合法落盘（任务 1.1）。

        判定「合法」的条件：
        1. 结果文件存在、非空、可解析为 JSON 对象
        2. status ∈ {approved, repaired}
        3. mtime ≥ 锚点写入时刻（防上轮残留合法文件替本轮放行）
        4. 快照 spec 一致性校验通过（复用 _verify_snapshot）

        Returns:
            (True, data) 如果产物合法，data 为解析后的结果对象。
            (False, None) 如果产物不合法。

        设计依据（D1 产物优先判定）：run 成败由 CLI exit code 一票判定时，
        产物是否已合法落盘不作为判败前置条件——「产物已具备却被退出码一票否决」。
        本方法在 run 失败时前置校验，合法产物优先消费，exit code 失败仅降级
        为 warning 日志并留痕。

        锚点 = 解析 entry.reviewer_run 内嵌 epoch 时间戳（dispatch_review
        步骤①写入 run_id 的时刻，run_id 形如 ``spec-review-<spec>-<ts>``），
        与 consume 内跳过的新鲜度校验语义同向。
        """
        result_path = spec_review_result_path(self.project_root, spec_name)

        # 锚点解析：reviewer_run 内嵌 epoch 时间戳（run_id 尾部段）
        anchor_ts = run_started_at
        try:
            entry = self.state_machine.read_one(spec_name) or {}
            run_id = entry.get("reviewer_run") or ""
            if run_id:
                tail = str(run_id).rsplit("-", 1)[-1]
                if tail.isdigit():
                    anchor_ts = float(tail)
        except (TypeError, ValueError):
            pass

        try:
            if not result_path.is_file():
                return (False, None)
            if result_path.stat().st_size == 0:
                return (False, None)

            # mtime 新鲜度校验：mtime 早于锚点（宽限 1s 吸收 fs 写入滞后）
            if anchor_ts is not None:
                mtime = result_path.stat().st_mtime
                if mtime < anchor_ts - 1.0:
                    return (False, None)

            # JSON 解析
            try:
                data = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return (False, None)

            if not isinstance(data, dict):
                return (False, None)

            # status 白名单校验（仅 approved/repaired 视为合法产物）
            status = data.get("status")
            if status not in ("approved", "repaired"):
                return (False, None)

            # 快照 spec 一致性校验（复用 _verify_snapshot）
            snapshot_path = (
                self.project_root / ".fenix" / "spec-review" / spec_name / "snapshot.json"
            )
            if snapshot_path.exists():
                try:
                    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
                    snapshot_err = self._verify_snapshot(spec_name, snapshot)
                    if snapshot_err:
                        return (False, None)
                except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
                    # 与 _check_write_boundary 同款：读取失败记 WARNING 而非静默
                    # 放行（code-review item 5d38e8dd6478——本文件的同款快照加载
                    # 代码需一并修正）。
                    self.logger.warning(
                        "spec_review",
                        f"产物判定快照读取失败 '{spec_name}'（跳过一致性校验）: "
                        f"{type(e).__name__}: {e}",
                    )

            return (True, data)

        except (OSError, AttributeError):
            return (False, None)

    def _classify_run_failure(self, reason: str | None, spec_name: str | None = None) -> str:
        """三类失败分类（evo-run-failure-classification-circuitbreaker D1）。

        扩展 evo-run-failure-artifact-first 的同名 `_classify_run_failure`（沿用同名，
        勿另开 `_classify_failure`）为三分 "artifact" | "infra" | "content"：

        - artifact：产物已落盘合法（调用 `_artifact_landed_valid`）；优先级最高；
        - infra：指纹匹配（403/402/429/quota/budget/余额/insufficient balance/
          rate limit / 既有 provider 熔断信号 "provider circuit open" /
          "provider chain exhausted"——runner.py:2458/2473，供侧熔断同属 infra）
          或 CLI 进程级崩溃（error 含 "Exit code: N" 且 N 非 0/1——"Exit code: 1"
          不得一律判 infra，评审器内容失败同样 exit 1）；或 probe 标记
          model_chain_preflight_failed；
        - content：其余（含空白轮次）。

        Args:
            reason: run 失败原因文本（可为 None）。
            spec_name: 可选；给出时前置校验产物是否已合法落盘，命中则判 artifact。

        Returns: "artifact" | "infra" | "content"。
        """
        # artifact 分支优先级最高：产物已落盘合法 → 判别失败，直接消费不重试。
        if spec_name:
            try:
                landed = self._artifact_landed_valid(spec_name)
            except (AttributeError, TypeError, ValueError):
                landed = False
            # _artifact_landed_valid 返回 (bool, data) 元组；兼容测试替身返回裸 bool。
            artifact_ok = landed[0] if isinstance(landed, tuple) else bool(landed)
            if artifact_ok:
                return "artifact"
        low = (reason or "").lower()
        for fp in _INFRA_FINGERPRINTS:
            if fp in low:
                return "infra"
        # CLI 进程级崩溃：exit code 非 0/1（0 正常 / 1 内容失败）
        m = _CLI_EXIT_CODE_RE.search(reason or "")
        if m:
            try:
                code = int(m.group(1))
            except ValueError:
                code = None
            if code not in (None, 0, 1):
                return "infra"
        return "content"

    def _handle_review_failure(
        self, spec_name: str, reason: str, *, allow_artifact: bool = True,
        run_started_at: float | None = None,
    ):
        """处理评审失败：按失败分类落点（D1/D2）。

        ``allow_artifact=False``（写入边界类失败调用）：禁止 artifact 分类回流
        ——否则 consume → 边界错误 → _handle_review_failure → artifact →
        consume 无限递归（code-review item 4b9f59b8717f）。``run_started_at``
        透传给回流消费，保持 mtime 新鲜度校验。

        - artifact：产物已落盘合法 → 直接消费（不重试，run-failure-artifact-first
          承接；`_artifact_landed_valid` 缺失时回退 content）；
        - infra：熔断计数 + 升级告警；清 reviewer_run、**不递增 _review_attempts**
          （熔断前与冷却期均不计入——infra 属链路级问题而非 spec 内容问题；若递增，
          第 3 次 infra 会同时触 MAX_REVIEW_ATTEMPTS=3 freeze 破坏「冷却后自动
          恢复」；若不清锚点，冷却到期后 dispatch_review 见 reviewer_run 非空拒派
          （spec_review.py:67-69），spec 永久卡 reviewing）；
        - content：维持既有重试语义（递增 _review_attempts，达上限转冻结转人工）。

        error 保留 ``spec-review-incomplete:`` 前缀不变（复用 re_review 的
        startswith 契约）。
        """
        failure_type = self._classify_run_failure(
            reason, spec_name if allow_artifact else None
        )

        if failure_type == "artifact":
            # 判别失败：产物已落盘合法 → 直接消费收口，不重试。
            self.logger.info("spec_review", f"判别失败（产物已落盘）→ 直接消费: {spec_name}")
            # 仅在确有 run_started_at 时才透传该关键字——保持既有调用形态
            # （run_started_at=None 与「不传」语义等价：均跳过 mtime 新鲜度校验），
            # 避免为无意义的 None 改变调用签名（既有测试以位置参数断言）。
            if run_started_at is not None:
                self.consume_review_result(spec_name, run_started_at=run_started_at)
            else:
                self.consume_review_result(spec_name)
            return

        if failure_type == "infra":
            # infra 失败：熔断计数 + 升级告警（触发熔断时恰好落一条 critical）。
            breaker = getattr(self.pm_engine, "infra_breaker", None)
            if breaker is not None:
                triggered = breaker.record_failure("spec-review")
                if triggered:
                    self.pm_engine._emit_infra_breaker_event(
                        "triggered", spec_name, reason, breaker.get_state("spec-review")
                    )
            # 清 reviewer_run、不递增 _review_attempts（保持原值）
            self.state_machine.update_spec(
                spec_name,
                {
                    "reviewer_run": None,
                    "error": f"spec-review-incomplete: infra failure: {reason}",
                },
            )
            self.logger.warning(
                "spec_review", f"评审 infra 失败（熔断计数，不递增尝试）: {spec_name}: {reason}"
            )
            return

        # ── content 分支：重试改为入队（fix-spec-review-blocking-dispatch 2.5）──
        # 原：保持 reviewing + 清 reviewer_run → 由 `dispatch_review` 返回后
        # 调用方重试。改造后：清 reviewer_run → 入队 spec-review → 由队列接力
        # 在独立 worker 线程重试。重试入队前 MUST 已清除 reviewer_run（否则队列
        # 候选筛选判「reviewer_run 非空 + in_flight=True」→ 拒派；任务 2.5 约束）。
        # 本方法在 dispatch_review 栈内执行，worker 的 finally 会兜底调
        # `_process_queue`，所以不需要额外触发。CLI 场景 pm_engine=None 保持原语义
        # （记日志，由 daemon recovery 拾取）。
        entry = self.state_machine.read_one(spec_name)
        if not entry:
            return
        try:
            attempts = int(entry.get("_review_attempts", 0) or 0)
        except (TypeError, ValueError):
            attempts = 0
        if attempts < MAX_REVIEW_ATTEMPTS:
            # 重试：保持 reviewing 状态，清除 reviewer_run + 入队
            self.state_machine.update_spec(
                spec_name,
                {
                    "reviewer_run": None,
                    "_review_attempts": attempts + 1,
                    "error": f"spec-review-incomplete: {reason}",
                },
            )
            self.logger.info("spec_review", f"评审失败重试: {spec_name} attempt={attempts+1}")
            if self.pm_engine is not None:
                self.pm_engine._enqueue(spec_name, "spec-review")
        else:
            # 达上限转冻结转人工（fix-blocked-freeze-classification 2.2）：
            # admin 对「评审器连续失败」无操作杠杆（模型链/配置问题），
            # 改走 freeze_for_human「冻结 + 告警」成对入口，使 admin_monitor
            # 的 blocked_stuck 豁免生效。
            r_id = entry.get("reviewer_run")
            error_msg = (
                f"{FREEZE_ERROR_PREFIX}原状态 reviewing · " f"spec-review-incomplete: {reason}"
            )
            self.state_machine.freeze_for_human(
                spec_name,
                error=error_msg,
                signal_type="spec-review-incomplete",
                severity="major",
                description=(
                    f"'{spec_name}' 评审器连续失败（模型链/配置问题）至"
                    f"尝试上限（{MAX_REVIEW_ATTEMPTS}），需人工排查"
                ),
                evidence=(f"spec={spec_name}; run_id={r_id or '无'}; reason={reason}"),
                recommended_action=(
                    "人工排查评审链路根因（模型链/配置/结果硬门/写入边界）；"
                    "排查后经 dashboard/CLI 解冻——解冻恢复原状态 reviewing，"
                    "daemon 自动重派评审；或直接撤销该 spec"
                ),
                alert_callback=self.pm_engine._send_human_escalation_alert,
                extra_updates={"reviewer_run": None, "_review_attempts": 0},
            )
            self.logger.warning("spec_review", f"评审失败达上限: {spec_name}")

    # ── 人工恢复入口 ────────────────────────────────────────────

    def re_review(self, spec_name: str) -> Tuple[bool, str]:
        """重新评审入口：对符合开放条件的 blocked SPEC 执行 blocked → reviewing。

        Returns: (success, message)
        """
        entry = self.state_machine.read_one(spec_name)
        if not entry:
            return False, "SPEC 不存在"
        if entry.get("status") != SpecStatus.BLOCKED:
            return False, "SPEC 状态不是 blocked"
        if entry.get(FROZEN_FIELD):
            return False, "SPEC 已冻结"
        error = entry.get("error") or ""
        if not (
            error.startswith("spec-review-rejected:") or error.startswith("spec-review-incomplete:")
        ):
            return False, "SPEC 未因评审进入 blocked"

        # 执行 blocked → reviewing（fix-observability-gaps 2.2：人工重评来源）
        success = self.state_machine.transition(
            spec_name, "reviewing",
            trigger_run_id=entry.get("reviewer_run") or None,
            agent_type="spec-review", channel="manual",
        )
        if not success:
            return False, "状态转移失败"

        # 派发新评审（fix-spec-review-blocking-dispatch 2.7：改投队列）——
        # agent_runner 为 None 的 CLI 场景跳过派发，由 daemon full_scan
        # recovery 的 reviewing 分支拾取。in-process（daemon 侧）场景：
        # 入队 spec-review 由队列接力在 worker 线程派发，re_review 立即返回。
        if self.agent_runner is not None and self.pm_engine is not None:
            self.pm_engine._enqueue(spec_name, "spec-review")

        return True, "重新评审已触发"

    def responsible_release(self, spec_name: str) -> Tuple[bool, str]:
        """担责放行入口：对 blocked SPEC 执行 blocked → ready（人工裁决）。

        Returns: (success, message)
        """
        entry = self.state_machine.read_one(spec_name)
        if not entry:
            return False, "SPEC 不存在"
        if entry.get("status") != SpecStatus.BLOCKED:
            return False, "SPEC 状态不是 blocked"

        # 执行 blocked → ready（fix-observability-gaps 2.2：人工担责放行来源）
        success = self.state_machine.transition(
            spec_name, "ready",
            trigger_run_id=entry.get("reviewer_run") or None,
            agent_type="spec-review", channel="manual",
        )
        if not success:
            return False, "状态转移失败"

        # 清除评审相关字段
        self.state_machine.update_spec(
            spec_name,
            {
                "reviewer_run": None,
                "_review_attempts": 0,
                "error": None,
            },
        )
        # 触发实现调度（pm_engine None 守卫，code-review item 5ee4abf84768）：
        # CLI（bin/fenix_cli.py: cmd_review）与 Dashboard
        # （core/dashboard/data/admin_actions.re_review_spec）均以
        # SpecReviewManager(proot, sm, None, None, {}, logger) 构造——与 re_review
        # 的 `if self.agent_runner is not None and self.pm_engine is not None` 同款
        # 守卫缺失时，blocked→ready 已提交成功后会在本行抛 AttributeError，调用方
        # 拿不到结果而状态已变更。此处按 None 跳过派发（状态已在 ready，由 daemon
        # full_scan recovery 兜底拾取）。
        if self.pm_engine is not None:
            self.pm_engine._on_spec_ready(spec_name)
        return True, "担责放行已触发"
