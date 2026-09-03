"""budget.py — ImplBudget：实现尝试总预算（计数/耗尽判定/死亡 run 豁免/豁免循环告警/对账）（refactor-core-packages 阶段 4）。

无状态组件：SPEC 状态全部经门面回引 self._pm.state_machine 落在
STATE.md（design D3 规则 3），本组件不持有实例状态。

"""

from core.state_machine import BUDGET_EXEMPT_ALERTED_FIELD, BUDGET_EXEMPT_RUNS_FIELD
from pathlib import Path
import json
import re


# ── 实现尝试总预算缺省值（add-fail-counter-budget D2/D3）──────────
# 每 spec 跨修复周期的实现 run 启动次数上限（含首次实现与每轮修复重派、
# 含单次派发的重试 attempt）；达到预算 → blocked + 人工裁决。
# 该缺省经 config 键 ``agents.impl_run_budget`` 覆盖（该键带 Dashboard 界面）。
# 4→6（add-v3-spec-quick-switch 2026-09-02）：4 次预算中 merge 冲突重试、恢复
# 误派等机制摩擦可吞掉全部预算，真 bug 修复轮次为 0；上调留出摩擦余量。
DEFAULT_IMPL_RUN_BUDGET = 6
# 持久化字段名：当前 spec 已累计启动的实现 run 次数。
IMPL_RUN_BUDGET_USED_FIELD = "_impl_run_budget_used"
# ── 死亡 run 豁免（fix-budget-counting-semantics D1）──────────────
# _budget_exempt_runs 侧车达到该值时发一次性提醒级告警（不冻结）：
# 豁免本身不占预算，但极端「死亡循环」仍烧 token——告警兜底人工介入。
# 可经 pm.budget_exempt_alert_threshold 覆盖（模块常量缺省，不进 Dashboard）。
BUDGET_EXEMPT_ALERT_THRESHOLD = 6


class ImplBudget:
    """实现尝试总预算组件（门面 PMEngine 的组合组件）。"""

    def __init__(self, pm):
        self._pm = pm  # 门面回引（design D3 规则 3：组件 → 门面 单向）

    # ── 实现尝试总预算（add-fail-counter-budget D2/D4）──────────────
    def _impl_run_budget(self) -> int:
        """读取实现尝试预算（agents.impl_run_budget），缺省 DEFAULT_IMPL_RUN_BUDGET。

        范围约束 1-10（D3 界面校验同口径）；配置越界时夹紧到合法区间，避免
        极端配置使闸门失效或永远触发。
        """
        try:
            raw = self._pm._get_config("agents.impl_run_budget", DEFAULT_IMPL_RUN_BUDGET)
            val = int(raw) if raw is not None else DEFAULT_IMPL_RUN_BUDGET
        except (TypeError, ValueError):
            val = DEFAULT_IMPL_RUN_BUDGET
        if val < 1:
            val = 1
        if val > 10:
            val = 10
        return val


    def _increment_impl_run_budget_used(self, spec_name: str) -> int:
        """实现 run 启动时递增并持久化 ``_impl_run_budget_used``。

        返回递增后的使用次数。跨重启有效（直接写 STATE.md）。
        fix-budget-counting-semantics D2：读改写收敛到
        state_machine.bump_impl_budget（文件锁内读改写 + 回读校验），
        消除恢复扫描并发派发时的增量丢失（used=2/4 连现事故）。
        """
        used = self._pm.state_machine.bump_impl_budget(spec_name, 1)
        self._pm.logger.info(
            "pm_engine",
            f"实现尝试预算计数 +1: '{spec_name}' used={used}/{self._impl_run_budget()}",
        )
        return used


    def _budget_exempt_alert_threshold(self) -> int:
        """死亡豁免侧车告警阈值（pm.budget_exempt_alert_threshold，缺省 6）。"""
        try:
            val = int(
                self._pm._get_config(
                    "pm.budget_exempt_alert_threshold", BUDGET_EXEMPT_ALERT_THRESHOLD
                )
                or BUDGET_EXEMPT_ALERT_THRESHOLD
            )
        except (TypeError, ValueError):
            val = BUDGET_EXEMPT_ALERT_THRESHOLD
        return max(1, val)


    def _exempt_dead_run_budget(self, spec_name: str, reason: str) -> None:
        """死亡 run 豁免：回退本次启动的计数增量 + 侧车递增 + 审计日志。

        fix-budget-counting-semantics D1：run 异常死亡（进程消失/零输出/
        网关链路耗尽，无收工结果产出）时在死亡判定点做补偿回退
        （used -= 1，下限 0），避免故障密集日把预算烧在无效 run 上
        （interaction-contract 复盘：4/4 中 2 次网关死亡 + 2 次守卫误伤，
        真正有产出的 run 反被冻结）。正常失败收工（有收工结果产出）不豁免。
        """
        used = self._pm.state_machine.bump_impl_budget(spec_name, -1)
        exempt = self._pm.state_machine.bump_budget_exempt_runs(spec_name)
        self._pm.logger.warning(
            "pm_engine",
            f"预算豁免（死亡 run）: '{spec_name}' used 回退至 "
            f"{used}/{self._impl_run_budget()}，_budget_exempt_runs={exempt}，"
            f"reason={reason}",
        )
        if exempt >= self._budget_exempt_alert_threshold():
            self._alert_budget_exempt_loop(spec_name, exempt)


    def _alert_budget_exempt_loop(self, spec_name: str, exempt: int) -> None:
        """死亡豁免侧车达阈值 → 一次性提醒级告警（幂等标记 ``_exempt_alerted``）。

        只提醒不冻结：豁免不消耗预算，spec 可继续重派；但连续死亡循环
        仍在烧 token，告警唤起人工排查根因。幂等标记防重复告警。
        """
        entry = self._pm.state_machine.read_one(spec_name) or {}
        if entry.get(BUDGET_EXEMPT_ALERTED_FIELD):
            return
        self._pm.state_machine.update_spec(
            spec_name, {BUDGET_EXEMPT_ALERTED_FIELD: True}
        )
        threshold = self._budget_exempt_alert_threshold()
        self._pm._send_human_escalation_alert(
            spec_name=spec_name,
            signal_type="impl_budget_exempt_loop",
            severity="minor",
            description=(
                f"'{spec_name}' 实现 run 已异常死亡 {exempt} 次并被预算豁免回退，"
                f"疑似网关/环境故障循环（spec 未冻结，可继续重派）"
            ),
            evidence=(
                f"spec={spec_name}; budget_exempt_runs={exempt}; "
                f"threshold={threshold}; used={self._impl_run_budget_used(spec_name)}"
            ),
            recommended_action=(
                "检查 provider 网关健康度与最近死亡 run 产物（.fenix/runs/ 中 "
                "error 终态的 impl-*.jsonl）；排除基础设施故障后人工清理 "
                "_budget_exempt_runs 侧车即可解除告警条件"
            ),
        )


    def _reconcile_impl_budget(self, spec_name: str) -> None:
        """merge 成功/守卫放行后回读 used 与正常收工 run 数比对。

        偏差记 WARNING 供人工发现；不自动改数（对账复杂化收益低）。
        已知固有偏差源：provider 链耗尽的 run 不落产物——偏差日志需结合
        这些因素人工判读。
        """
        used = self._impl_run_budget_used(spec_name)
        completed = self._count_normal_completed_impl_runs(spec_name)
        if used != completed:
            self._pm.logger.warning(
                "pm_engine",
                f"预算计数对账偏差: '{spec_name}' used={used} vs "
                f"runs 目录正常收工 run 数={completed}"
                f"（runs 产物有保留上限/链耗尽 run 不落产物，供人工核查，不自动改数）",
            )


    def _count_normal_completed_impl_runs(self, spec_name: str) -> int:
        """从 .fenix/runs/ 侧车统计本 spec 正常收工的实现 run 数。

        run_id 规则 ``impl-<spec>-<ts>[-a<n>]``（每 attempt 一个产物文件，
        同一 run 的多 attempt 视为一个 run，取最新 attempt 产物）。
        判据：产物末行（终态行）为 error ＝ 死亡 run，不计；
        result 终态 ＝ 正常收工（成功或带收工结果的失败均计入）。
        """
        runs_dir = self._pm.project_root / ".fenix" / "runs"
        if not runs_dir.is_dir():
            return 0
        newest_attempt: dict = {}
        for p in runs_dir.glob(f"impl-{spec_name}-*.jsonl"):
            base = re.sub(r"-a\d+$", "", p.stem)
            try:
                mtime = p.stat().st_mtime
            except OSError:
                continue
            prev = newest_attempt.get(base)
            if prev is None or mtime > prev[0]:
                newest_attempt[base] = (mtime, p)
        count = 0
        for _mtime, path in newest_attempt.values():
            if not self._run_file_died(path):
                count += 1
        return count


    @staticmethod
    def _run_file_died(path: Path) -> bool:
        """实现 run 产物是否以 error 终态行收尾（死亡 run 判据，容错解析）。"""
        last = None
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(entry, dict):
                        last = entry
        except OSError:
            return True
        return isinstance(last, dict) and last.get("type") == "error"


    def _impl_run_budget_used(self, spec_name: str) -> int:
        entry = self._pm.state_machine.read_one(spec_name) or {}
        try:
            return int(entry.get(IMPL_RUN_BUDGET_USED_FIELD, 0) or 0)
        except (TypeError, ValueError):
            return 0


    def _check_impl_budget_exhausted(self, spec_name: str) -> bool:
        """派发新一轮实现器前校验预算。

        已累计使用 ``_impl_run_budget_used >= agents.impl_run_budget`` 时触发闸门：
        spec 置 blocked + human-escalation-alerts 告警（signal_type=impl_budget_exhausted，
        含 spec、已耗次数、最近失败摘要），不再自动重派。返回 True 表示已冻结。

        已启动的 run（计数已计入、正在跑）不受此影响，照常跑完 merge——
        本方法只在「即将开启新一轮」时调用。幂等：已是 blocked 时直接返回 True
        不再重复告警。
        """
        budget = self._impl_run_budget()
        used = self._impl_run_budget_used(spec_name)
        if used < budget:
            return False

        entry = self._pm.state_machine.read_one(spec_name) or {}
        if entry.get("status") == "blocked":
            # 已冻结（可能由其它闸门触发）：不重复告警，但仍阻止重派
            return True

        # 最近失败摘要：优先取 error，回退 tester_run/implementer_run 上下文
        recent_error = (entry.get("error") or "").strip()
        if not recent_error:
            recent_error = (
                f"最近实现 run={entry.get('implementer_run') or '未知'}，"
                f"验证 run={entry.get('tester_run') or '未知'}"
            )
        self._pm.state_machine.update_spec(spec_name, {
            "status": "blocked",
            "error": (
                f"实现尝试预算耗尽（{used}/{budget}）：已停止自动重派，"
                f"需人工裁决。最近失败：{recent_error}"
            ),
        })
        self._pm.logger.error(
            "pm_engine",
            f"实现尝试预算耗尽：'{spec_name}' used={used}/{budget}，冻结为 blocked",
        )
        self._pm._send_human_escalation_alert(
            spec_name=spec_name,
            signal_type="impl_budget_exhausted",
            severity="major",
            description=(
                f"'{spec_name}' 实现尝试预算耗尽（{used}/{budget}），已冻结等待人工裁决"
            ),
            evidence=(
                f"spec={spec_name}; used={used}; budget={budget}; "
                f"recent_failure={recent_error}"
            ),
            recommended_action=(
                "检查实现/验证报告定位根因；人工可调大 agents.impl_run_budget 后解冻，"
                "或直接推进状态。人工重置计数器即重新获得自动修复机会"
            ),
        )
        return True
