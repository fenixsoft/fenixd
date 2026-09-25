"""budget.py — ImplBudget：实现尝试总预算（计数/耗尽判定/死亡 run 豁免/豁免循环告警/对账）（refactor-core-packages 阶段 4）。

无状态组件：SPEC 状态全部经门面回引 self._pm.state_machine 落在
STATE.md（design D3 规则 3），本组件不持有实例状态。

"""

from core.state_machine import (
    BUDGET_EXEMPT_ALERTED_FIELD,
    BUDGET_EXEMPT_RUNS_FIELD,
    INFRA_FAILURE_COUNT_FIELD,
    VERIFY_INFRA_ROUNDS_FIELD,
)
from core.agent_runner.run_files import run_spec_part, strip_run_id_suffixes
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
# ── per-spec 预算覆盖属性（add-spec-status-modal-budget D3）──────────
# 人工管理属性（不带下划线前缀，与 priority/start_after 同类；下划线前缀保留给
# 框架私有字段 _impl_run_budget_used 等）。null/缺失 = 跟随全局 agents.impl_run_budget。
IMPL_RUN_BUDGET_OVERRIDE_FIELD = "impl_run_budget_override"

# ── 预算上限键（open-impl-budget-ceiling）──────────────────────────
# 历史上「实现尝试预算」被硬编码夹紧到 [1, 10]（add-spec-status-modal-budget
# D3 界面同口径）。10 的天花板对长链条 spec 过紧：一旦机制摩擦（merge 冲突重试、
# 恢复误派、修复轮）吃掉大部分预算，真修复轮次归零并提前冻结（2026-09-15
# refactor-dashboard-data-module 事故：机制摩擦吞掉 9 次后无法再派修复轮）。
# 现改为可配置上限：``agents.impl_run_budget_max``（缺省 100），per-spec 覆盖值
# 与全局 ``agents.impl_run_budget`` 均按该上限夹紧；上限键自身再受一个硬天花板
# 约束（防极端配置使闸门事实上失效）。
IMPL_RUN_BUDGET_MAX_KEY = "agents.impl_run_budget_max"
IMPL_RUN_BUDGET_MAX_DEFAULT = 100
# 上限键自身的硬天花板：即便把 impl_run_budget_max 配成极大值，也不超过此值。
IMPL_RUN_BUDGET_MAX_CEILING = 1000


def resolve_impl_run_budget_max(raw) -> int:
    """上限键 ``agents.impl_run_budget_max`` 的归一化（正整数，≤ 硬天花板）。

    非正整数（bool/浮点/字符串/None/越界）→ 回退 ``IMPL_RUN_BUDGET_MAX_DEFAULT``；
    超出 ``IMPL_RUN_BUDGET_MAX_CEILING`` → 夹紧到天花板。与 clamp 同族纯函数，
    供闸门 / Dashboard 摘要 / API 校验同源共用。
    """
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        return IMPL_RUN_BUDGET_MAX_DEFAULT
    return min(raw, IMPL_RUN_BUDGET_MAX_CEILING)


def effective_impl_budget_max(config: dict) -> int:
    """从（已 resolve 的）config 字典解析有效上限，供 dashboard 读/写侧共用。

    与闸门 ImplBudget._impl_budget_max 同源（同一 resolve_impl_run_budget_max
    与同一配置键），保证「界面可设范围」与「闸门夹紧范围」永远一致。
    """
    from core.config import ConfigLoader

    raw = ConfigLoader.get(config, IMPL_RUN_BUDGET_MAX_KEY, IMPL_RUN_BUDGET_MAX_DEFAULT)
    return resolve_impl_run_budget_max(raw)


def clamp_impl_run_budget(raw, max_value: int = IMPL_RUN_BUDGET_MAX_DEFAULT) -> int | None:
    """预算值归一化纯函数（模块级导出，闸门与 Dashboard 同源，防口径漂移）。

    - 整数（非 bool）→ 夹紧到 ``[1, max_value]`` 返回（``max_value`` 缺省为上限键
      缺省 ``IMPL_RUN_BUDGET_MAX_DEFAULT``，调用方可传入解析后的有效上限）；
    - None / 非整数（字符串数字、浮点、bool 等）→ 返回 None（调用方回退下一优先级）。

    覆盖值与全局配置共用此函数，保证越界夹紧口径完全一致（design D3 / risk 单点）。
    """
    if raw is None:
        return None
    if not isinstance(raw, int) or isinstance(raw, bool):
        return None
    val = raw
    if val < 1:
        val = 1
    if val > max_value:
        val = max_value
    return val


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

    # ── 实现尝试总预算（add-fail-counter-budget D2/D4 / add-spec-status-modal-budget D3 / open-impl-budget-ceiling）──────────────
    def _impl_budget_max(self) -> int:
        """读取可配置上限 ``agents.impl_run_budget_max``（缺省 100，≤ 硬天花板）。

        上限键缺失/非法 → ``IMPL_RUN_BUDGET_MAX_DEFAULT``；供 override 与全局
        配置的夹紧共用（口径单点，防闸门与 Dashboard 漂移）。
        """
        raw = self._pm._get_config(IMPL_RUN_BUDGET_MAX_KEY, IMPL_RUN_BUDGET_MAX_DEFAULT)
        return resolve_impl_run_budget_max(raw)

    def _impl_run_budget(self, spec_name: str | None = None) -> int:
        """读取实现尝试有效预算，缺省 DEFAULT_IMPL_RUN_BUDGET。

        add-spec-status-modal-budget D3 覆盖优先解析：
        1. spec_name 非空且 STATE 条目 ``impl_run_budget_override`` 存在且可解析为
           整数 → 同口径夹紧 [1, max] 使用（per-spec 覆盖）；
        2. 否则回退全局配置 ``agents.impl_run_budget``（现状逻辑）；
        3. 全局缺失/非法 → DEFAULT_IMPL_RUN_BUDGET。

        范围约束 [1, max]（``agents.impl_run_budget_max``，缺省 100，
        open-impl-budget-ceiling）；配置越界时夹紧到合法区间，避免极端配置使
        闸门失效或永远触发。夹紧逻辑收敛到模块级纯函数 clamp_impl_run_budget
        （与 dashboard 摘要同源，防口径漂移）。
        """
        max_value = self._impl_budget_max()
        if spec_name:
            entry = self._pm.state_machine.read_one(spec_name) or {}
            override = clamp_impl_run_budget(entry.get(IMPL_RUN_BUDGET_OVERRIDE_FIELD), max_value)
            if override is not None:
                return override
        raw = self._pm._get_config("agents.impl_run_budget", DEFAULT_IMPL_RUN_BUDGET)
        return clamp_impl_run_budget(raw, max_value) or DEFAULT_IMPL_RUN_BUDGET

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
            f"实现尝试预算计数 +1: '{spec_name}' used={used}/{self._impl_run_budget(spec_name)}",
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

    def _exempt_dead_run_budget(
        self, spec_name: str, reason: str, run_reason: str | None = None
    ) -> None:
        """死亡 run 豁免：回退本次启动的计数增量 + 侧车递增 + 审计日志。

        fix-budget-counting-semantics D1：run 异常死亡（进程消失/零输出/
        网关链路耗尽，无收工结果产出）时在死亡判定点做补偿回退
        （used -= 1，下限 0），避免故障密集日把预算烧在无效 run 上
        （interaction-contract 复盘：4/4 中 2 次网关死亡 + 2 次守卫误伤，
        真正有产出的 run 反被冻结）。正常失败收工（有收工结果产出）不豁免。

        fix-run-hang-amplification D2：豁免仅适用于基础设施性死亡（daemon
        shutdown/interrupted、网关链路耗尽/provider circuit open）；监督超时/
        被判停滞而杀（不可豁免判据见 ``_is_exemptable_reason``）
        MUST NOT 豁免——它确实消耗了整份预算。

        Args:
            run_reason: 终态 reason 文本（run的 error/reason 字段），供豁免判定
                        关键词检查；None/空时按旧语义豁免。
        """
        if run_reason and not self._is_exemptable_reason(run_reason):
            # 监督超时/被判停滞而杀：不豁免，保持计数
            self._pm.logger.warning(
                "pm_engine",
                f"预算豁免被拒（非基础设施性死亡）: '{spec_name}' reason={reason}, "
                f"run_reason={run_reason[:80] if run_reason else ''}",
            )
            return
        used = self._pm.state_machine.bump_impl_budget(spec_name, -1)
        exempt = self._pm.state_machine.bump_budget_exempt_runs(spec_name)
        self._pm.logger.warning(
            "pm_engine",
            f"预算豁免（死亡 run）: '{spec_name}' used 回退至 "
            f"{used}/{self._impl_run_budget(spec_name)}，_budget_exempt_runs={exempt}，"
            f"reason={reason}",
        )
        if exempt >= self._budget_exempt_alert_threshold():
            self._alert_budget_exempt_loop(spec_name, exempt)

    def _exempt_infra_run_budget(self, spec_name: str, reason: str, refund_key: str = "") -> bool:
        """infra 失败预算事后补偿（evo-infra-failure-budget-exempt R2）。

        与 ``_exempt_dead_run_budget`` 同范式（事后补偿、不做计数时点感知）：
        infra 判定命中时回退本次实现 run 启动时 +1 的 used（下限 0），
        独立写 ``_infra_failure_count``（生命周期累计观测值，不归零）。

        **幂等**（退款一次/轮、避免同一实现 run 重复扣减）：
        幂等锚点 = 实现 run id（``refund_key``）；已退款的 run id 记录在
        ``_infra_refunded_run_ids`` 侧车（JSON 字符串数组，STATE.md ``_``
        前缀自动透传）。同一实现 run 的多次 infra 判定仅首次退款。无锚点
        （空串）时仍退款（调用方保证单轮单次）。

        Returns:
            True 表示本次实际执行了退款（含幂等跳过视为已退款）；
            False 表示异常降级未退款（调用方继续记账不抛穿）。
        """
        try:
            entry0 = self._pm.state_machine.read_one(spec_name) or {}
            anchor = refund_key or str(entry0.get("implementer_run") or "")
            # 「查锚点 + 退款 + 记锚点」收敛为单把文件锁下的原子读改写
            # （item 40f7a931dc4c）：旧三步分持多把锁，同一 run 的并发 infra
            # 判定都读不到锚点、各自退款一次。
            refunded_flag, used = self._pm.state_machine.refund_impl_budget_once(
                spec_name, anchor
            )
            if not refunded_flag:
                # 同一实现 run 已退款——幂等跳过
                self._pm.logger.info(
                    "pm_engine",
                    f"infra 预算退款幂等跳过 '{spec_name}' run={anchor}" f"（该实现 run 已退款）",
                )
                return True
            count = self._pm.state_machine.bump_infra_failure_count(spec_name)
            self._pm.logger.warning(
                "pm_engine",
                f"预算豁免（infra 失败）: '{spec_name}' used 回退至 "
                f"{used}/{self._impl_run_budget(spec_name)}，"
                f"_infra_failure_count={count}，"
                f"run_id={anchor or '(无锚点)'}，reason={reason}",
            )
            return True
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"infra 预算补偿异常跳过 '{spec_name}'（不阻断主流程）: {e}",
            )
            return False

    @staticmethod
    def _is_exemptable_reason(run_reason: str) -> bool:
        """判定 run终态 reason 是否属于基础设施性死亡（可豁免）。

        不可豁免（监督超时/被判停滞而杀）：reason 含
          "extension budget exhausted"（监督超时续期用尽）、"stagnant"（被判停滞）、
          "absolute_max_seconds cap reached"（总墙钟上限，判定先于续期预算用尽）
          或 "run timeout reached"（监督停用时的纯墙钟杀）。
        其他情况视为基础设施性死亡（进程消失/无结果/daemon shutdown/interrupted/
        网关链路耗尽/provider circuit open 等）。
        """
        r = str(run_reason).lower()
        if "extension budget exhausted" in r:
            return False
        if "stagnant" in r:
            return False
        if "absolute_max_seconds cap reached" in r:
            return False
        if "run timeout reached" in r:
            return False
        return True

    def _alert_budget_exempt_loop(self, spec_name: str, exempt: int) -> None:
        """死亡豁免侧车达阈值 → 一次性提醒级告警（幂等标记 ``_exempt_alerted``）。

        只提醒不冻结：豁免不消耗预算，spec 可继续重派；但连续死亡循环
        仍在烧 token，告警唤起人工排查根因。幂等标记防重复告警。
        """
        entry = self._pm.state_machine.read_one(spec_name) or {}
        if entry.get(BUDGET_EXEMPT_ALERTED_FIELD):
            return
        self._pm.state_machine.update_spec(spec_name, {BUDGET_EXEMPT_ALERTED_FIELD: True})
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

        lifecycle-hygiene 4.3：无豁免因素（保留上限/死亡豁免均不适用）的偏差
        = 纯漂移，以 runs 实际计数为准**自动改写 used** 并留 INFO 校正日志
        （含前后值），MUST NOT 保留静默漂移的旧值。
        有豁免因素（runs 产物被归档/保留上限、死亡 run 豁免发生过）时沿用既有
        WARN 不改数——自动改数会破坏豁免语义。
        """
        used = self._impl_run_budget_used(spec_name)
        completed = self._count_normal_completed_impl_runs(spec_name)
        if used == completed:
            return
        # 下调方向先排除在飞 run（item 425736ecfd76）：对账时刻同 spec 恰有
        # 新 run 已派发（启动计数已 +1）而产物尚未落盘时，completed 比 used
        # 少 1 是对账窗口假象，自动下调会把该 run 的计数永久吞掉（run 收工
        # 不再补 +1，预算少计）——保守不改数。
        if completed < used and self._impl_run_unmaterialized(spec_name):
            self._pm.logger.warning(
                "pm_engine",
                f"预算计数对账偏差（在飞实现 run）: '{spec_name}' used={used} vs "
                f"runs 目录正常收工 run 数={completed}"
                f"（implementer_run 产物尚未可见，疑似启动计数已加、产物未落盘，"
                f"不自动改数）",
            )
            return
        if self._budget_reconcile_has_exemption(spec_name):
            self._pm.logger.warning(
                "pm_engine",
                f"预算计数对账偏差: '{spec_name}' used={used} vs "
                f"runs 目录正常收工 run 数={completed}"
                f"（存在豁免因素：runs 产物保留上限/归档 或 死亡 run 豁免，"
                f"不自动改数，供人工核查）",
            )
            return
        # 纯漂移（无豁免因素）：以 runs 实际计数为准改写 used（design D5）
        try:
            self._pm.state_machine.update_spec(spec_name, {IMPL_RUN_BUDGET_USED_FIELD: completed})
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"预算对账校正写回失败 '{spec_name}': {e}",
            )
            return
        self._pm.logger.info(
            "pm_engine",
            f"预算对账自动校正: '{spec_name}' used={used} → {completed}"
            f"（runs 正常收工 run 数，无豁免因素；后续预算闸门按校正值生效）",
        )

    def _impl_run_unmaterialized(self, spec_name: str) -> bool:
        """最近派发的实现 run 产物在 runs 目录不可见（item 425736ecfd76）。

        STATE ``implementer_run`` 指向的产物既不在顶层 runs/ 也不在 archive/
        （按 run_id 前缀匹配，含 attempt/瞬态重试后缀）→ 视为「已派发未落盘」
        的在飞 run。产物已归档/可见时返回 False（归档场景由
        _budget_reconcile_has_exemption 兜底），无锚点返回 False。
        """
        entry = self._pm.state_machine.read_one(spec_name) or {}
        current_run = str(entry.get("implementer_run") or "")
        if not current_run:
            return False
        runs_dir = self._pm.project_root / ".fenix" / "runs"
        for base in (runs_dir, runs_dir / "archive"):
            try:
                if base.is_dir() and any(base.glob(f"{current_run}*.jsonl")):
                    return False
            except OSError:
                return False
        return True

    def _budget_reconcile_has_exemption(self, spec_name: str) -> bool:
        """对账校正的豁免因素判定（lifecycle-hygiene 4.3 / design D5 + R2）。

        任一命中即有豁免因素，不自动改数：
        - 死亡 run 豁免发生过（_budget_exempt_runs > 0）：used 已回退，改数破坏豁免；
        - infra 失败预算退款发生过（_infra_failure_count > 0）：used 已回退
          （evo-infra-failure-budget-exempt R2），改数会把退款冲掉，豁免失效；
        - runs 产物被归档/保留上限（.fenix/runs/archive/ 下存在该 spec 的 impl 产物）：
          顶层计数不完整，改数会把 used 错误压到已归档前的值。
        """
        entry = self._pm.state_machine.read_one(spec_name) or {}
        try:
            exempt = int(entry.get(BUDGET_EXEMPT_RUNS_FIELD, 0) or 0)
        except (TypeError, ValueError):
            exempt = 0
        if exempt > 0:
            return True
        # ── infra 失败预算退款（R2）：有退款则改数会冲掉退款，豁免 ──
        try:
            infra_count = int(entry.get(INFRA_FAILURE_COUNT_FIELD, 0) or 0)
        except (TypeError, ValueError):
            infra_count = 0
        if infra_count > 0:
            return True
        runs_dir = self._pm.project_root / ".fenix" / "runs"
        if runs_dir.is_dir():
            archive_dir = runs_dir / "archive"
            try:
                if archive_dir.is_dir():
                    for p in archive_dir.glob(f"impl-{spec_name}-*.jsonl"):
                        # 精确归属守卫（run 流归属全等匹配，范式见 recovery.py）：
                        # spec 名互为前缀（fix-x vs fix-x-y）时 glob 命中不得直接认定
                        if run_spec_part(p.stem) != spec_name:
                            continue
                        return True
            except OSError:
                pass
        return False

    def _count_normal_completed_impl_runs(self, spec_name: str) -> int:
        """从 .fenix/runs/ 侧车统计本 spec 正常收工的实现 run 数。

        run_id 规则 ``impl-<spec>-<ts>[-a<n>][-r<m>]``（每 attempt/瞬态重试一个
        产物文件，同一 run 的多 attempt/重试视为一个 run，取最新产物）。
        判据：产物末行（终态行）为 error ＝ 死亡 run，不计；
        result 终态 ＝ 正常收工（成功或带收工结果的失败均计入）。
        """
        runs_dir = self._pm.project_root / ".fenix" / "runs"
        if not runs_dir.is_dir():
            return 0
        newest_attempt: dict = {}
        # glob 是惰性生成器，迭代期间的 OSError（权限/IO 抖动）会向上冒泡进
        # 对账主流程（item ba82df251f21）——守卫写法与同文件
        # _impl_run_unmaterialized / _budget_reconcile_has_exemption 对齐：
        # 扫描失败按 0 计并记 WARNING，不阻断调用方主流程。
        try:
            for p in runs_dir.glob(f"impl-{spec_name}-*.jsonl"):
                if run_spec_part(p.stem) != spec_name:
                    continue  # 精确归属守卫（fix-x vs fix-x-y 前缀误命中全部排除）
                # 归并键剥除 attempt/瞬态重试后缀：-a1 与 -a1-r2 同属一个 run
                base = strip_run_id_suffixes(p.stem)
                try:
                    mtime = p.stat().st_mtime
                except OSError:
                    continue
                prev = newest_attempt.get(base)
                if prev is None or mtime > prev[0]:
                    newest_attempt[base] = (mtime, p)
        except OSError as e:
            self._pm.logger.warning(
                "pm_engine",
                f"runs 目录扫描失败 '{spec_name}'（按 0 计）: {e}",
            )
            return 0
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
        spec 置 blocked + 结构化 frozen 标记 + human-escalation-alerts 告警
        （signal_type=impl_budget_exhausted，含 spec、已耗次数、最近失败摘要），
        不再自动重派。返回 True 表示已冻结。

        ``frozen`` 标记不可省（scheduling-showcase 夹具回归）：admin_monitor 的
        blocked_stuck 豁免只看 ``frozen`` 字段 / error 前缀 ``frozen:`` / error 含
        「用户指令」三者，本闸门自有文案一条都不占——缺标记时冻结满
        ``admin.escalation_cooldown_minutes``（默认 60 分钟）即自动召唤一次
        Administrator agent run（夹具实证：admin-c-sched-set-1789106554 309KB，
        09-11 预算耗尽冻结 ~05:02Z → admin 唤起 ~06:13Z）。标记同时使
        StateMachine 的冻结保护剥离自动链路对 status 的改写，等待人工裁决。

        已启动的 run（计数已计入、正在跑）不受此影响，照常跑完 merge——
        本方法只在「即将开启新一轮」时调用。幂等：已是 blocked 时直接返回 True
        不再重复告警。
        """
        budget = self._impl_run_budget(spec_name)
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
        # fix-blocked-freeze-classification 3.1：收敛到 freeze_for_human 单一
        # 入口（frozen + 人工升级告警成对写入），消除「各站点各自记得成对」
        # 的漂移面。error 文案原样保留（长文案，不强制统一前缀）。
        self._pm.state_machine.freeze_for_human(
            spec_name,
            error=(
                f"实现尝试预算耗尽（{used}/{budget}）：已停止自动重派，"
                f"需人工裁决。最近失败：{recent_error}"
            ),
            signal_type="impl_budget_exhausted",
            severity="major",
            description=(f"'{spec_name}' 实现尝试预算耗尽（{used}/{budget}），已冻结等待人工裁决"),
            evidence=(
                f"spec={spec_name}; used={used}; budget={budget}; " f"recent_failure={recent_error}"
            ),
            recommended_action=(
                "检查实现/验证报告定位根因；人工可调大 agents.impl_run_budget 后解冻，"
                "或直接推进状态。人工重置计数器即重新获得自动修复机会"
            ),
            alert_callback=self._pm._send_human_escalation_alert,
        )
        self._pm.logger.error(
            "pm_engine",
            f"实现尝试预算耗尽：'{spec_name}' used={used}/{budget}，冻结为 blocked",
        )
        return True
