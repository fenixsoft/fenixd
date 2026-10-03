"""budget.py — ImplBudget：实现尝试总预算（计数/耗尽判定/死亡 run 豁免/豁免循环告警/对账）（refactor-core-packages 阶段 4）。

无状态组件：SPEC 状态全部经门面回引 self._pm.state_machine 落在
STATE.md（design D3 规则 3），本组件不持有实例状态。

"""

from core.state_machine import (
    BUDGET_EXEMPT_ALERTED_FIELD,
    BUDGET_EXEMPT_RUNS_FIELD,
    BUDGET_MANUAL_RESET_BASELINE_FIELD,
    INFRA_FAILURE_COUNT_FIELD,
)
from core.agent_runner.run_files import run_spec_part, strip_run_id_suffixes
from pathlib import Path
import io
import json

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

# run 产物终态判定的尾部扫描窗口（item 66e369185609）：终态行只会在文件尾部，
# _run_file_died 默认只读该窗口、从后向前找末条有效 dict 行，产物大/修复周期
# 累积时不再每次对账全量重读；窗口盖不住（末条有效行在窗口之外、超长行被
# 窗口起点截断）时回退全量读，判定结果与全量逐行读完全一致。
RUN_FILE_TAIL_SCAN_BYTES = 262144


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
        code-review 0b7fddb94aad：闸门判定（``_check_impl_budget_exhausted``
        的 used < budget 读）与本次启动计数递增分处两个临界区，恢复扫描与
        派发队列两条过闸通道在窗口内可各读旧 used 各自过闸，递增后 used 可
        越过有效预算一轮。此处对递增结果复核兜底（budget 与闸门同源读法）：
        越限即 WARNING 并补触发既有冻结闸门（幂等：已 blocked 不重复告警；
        刚启动的 run 照常跑完，闸门只阻止「新一轮」自动重派）。
        """
        used = self._pm.state_machine.bump_impl_budget(spec_name, 1)
        budget = self._impl_run_budget(spec_name)
        if used > budget:
            self._pm.logger.warning(
                "pm_engine",
                f"实现尝试预算越过上限（并发派发过闸复核）: '{spec_name}' "
                f"used={used}/{budget}，补触发冻结闸门",
            )
            self._check_impl_budget_exhausted(spec_name)
        self._pm.logger.info(
            "pm_engine",
            f"实现尝试预算计数 +1: '{spec_name}' used={used}/{budget}",
        )
        return used

    def _budget_exempt_alert_threshold(self) -> int:
        """死亡豁免侧车告警阈值（pm.budget_exempt_alert_threshold，缺省 6）。"""
        try:
            # 显式判 None（code-review item 431b18465020，与 engine.py
            # _handle_push_failure 的 95c429d664e3 同款）：`or` 会把合法的 0
            # （首次死亡豁免即告警，由下方 max(1, val) 夹紧下限）吞成默认 6，
            # 仅缺省时才回退默认值。
            raw = self._pm._get_config(
                "pm.budget_exempt_alert_threshold", BUDGET_EXEMPT_ALERT_THRESHOLD
            )
            val = BUDGET_EXEMPT_ALERT_THRESHOLD if raw is None else int(raw)
        except (TypeError, ValueError):
            val = BUDGET_EXEMPT_ALERT_THRESHOLD
        return max(1, val)

    def _exempt_dead_run_budget(
        self,
        spec_name: str,
        reason: str,
        run_reason: str | None = None,
        run_id: str = "",
    ) -> str:
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

        **幂等**（item cd696b7c0de9）：退款动作收敛为
        ``refund_dead_run_once`` 单把文件锁内的原子「查锚点 → 退款 →
        记锚点」（与 infra 路径 item 40f7a931dc4c 同范式）——同一死亡 run
        的并发豁免判定（如监督者与恢复扫描各判一次）仅首次退款，杜绝 used
        重复回退放大预算。幂等锚点 = 本次死亡 run id（``run_id``；缺省回退
        STATE ``implementer_run``——四个调用点（engine auto-recovery、
        dispatch/queue、dispatch/fast_track、dispatch/rollback）判定死亡时
        该字段仍指向刚死亡的 run（清 run 字段均发生在豁免之后），与
        ``_exempt_infra_run_budget`` 的锚点回退同范式）。无锚点时仍退款、
        不登记（幂等不保证，由调用方保证单轮单次）。

        **容错**（item 3b6448c3a22b）：记账段整体包裹 try/except（与
        ``_exempt_infra_run_budget``「不阻断主流程」同姿态）——read_one /
        refund_dead_run_once / bump_budget_exempt_runs 均读写状态文件（可抛
        OSError），STATE.md 瞬态 IO 异常记 WARNING 返回、不抛穿，豁免失败
        不得中止调用方的 run 死亡处置（requeue/error 落盘与审计日志）。

        Args:
            run_reason: 终态 reason 文本（run的 error/reason 字段），供豁免判定
                        关键词检查；None/空时按旧语义豁免。
            run_id: 本次死亡 run 的 id（幂等退款锚点；空串回退 STATE
                    ``implementer_run``）。

        Returns:
            豁免结果指纹（code-review item 963d40154301）：``"applied"`` 豁免
            实际生效（退款 + 侧车递增完成）；``"refused"`` run_reason 未过
            ``_is_exemptable_reason`` 被拒；``"idempotent_skip"`` 该死亡 run
            已退款（幂等跳过）；``"failed"`` 记账段异常降级（容错不抛穿）。
            三条未生效路径原为静默 return、调用方 except 判不出，现以返回值
            区分，供调用方审计标记（budget_exempt_audit）按实际生效口径落盘。
        """
        if run_reason and not self._is_exemptable_reason(run_reason):
            # 监督超时/被判停滞而杀：不豁免，保持计数
            self._pm.logger.warning(
                "pm_engine",
                f"预算豁免被拒（非基础设施性死亡）: '{spec_name}' reason={reason}, "
                f"run_reason={run_reason[:80] if run_reason else ''}",
            )
            return "refused"
        # 容错（item 3b6448c3a22b）：记账失败记 WARNING 返回、不抛穿（姿态与
        # _exempt_infra_run_budget 同，理由见 docstring「容错」段）。
        try:
            entry0 = self._pm.state_machine.read_one(spec_name) or {}
            anchor = run_id or str(entry0.get("implementer_run") or "")
            refunded_flag, used = self._pm.state_machine.refund_dead_run_once(
                spec_name, anchor
            )
            if not refunded_flag:
                # 同一死亡 run 已退款——幂等跳过（不重复回退 used、不递增豁免侧车）
                self._pm.logger.info(
                    "pm_engine",
                    f"死亡 run 预算豁免幂等跳过 '{spec_name}' run={anchor}（该 run 已退款）",
                )
                return "idempotent_skip"
            exempt = self._pm.state_machine.bump_budget_exempt_runs(spec_name)
            self._pm.logger.warning(
                "pm_engine",
                f"预算豁免（死亡 run）: '{spec_name}' used 回退至 "
                f"{used}/{self._impl_run_budget(spec_name)}，_budget_exempt_runs={exempt}，"
                f"run_id={anchor or '(无锚点)'}，reason={reason}",
            )
            if exempt >= self._budget_exempt_alert_threshold():
                self._alert_budget_exempt_loop(spec_name, exempt)
            return "applied"
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"死亡 run 预算豁免异常跳过 '{spec_name}'（不阻断主流程）: {e}",
            )
            return "failed"

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
        # 幂等标记翻转收敛为 state_machine 锁内原子 test-and-set（bump_counters
        # 读改写同把文件锁）：auto-recovery 与派发失败两条线程并发豁免都读到
        # 未标记时，仅 bump 结果 == 1 的赢家发告警，其余跳过（防重复告警）。
        alerted = self._pm.state_machine.bump_counters(
            spec_name, {BUDGET_EXEMPT_ALERTED_FIELD: 1}
        )[BUDGET_EXEMPT_ALERTED_FIELD]
        if alerted > 1:
            return
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

        人工重置基线（item 043e9fdd3ac7）：STATE 带
        ``_budget_manual_reset_baseline``（continue_auto_fix 清零 used 时同批
        写入的清零前值）时，对账目标改为 ``max(0, 正常收工 run 数 − 基线)``——
        历史 run 数不再冲掉人工清零（否则对账把 used 改写回历史 run 数，人工
        重置在一个周期内被静默回滚）；基线之后新产生的 run 消耗照常累计，
        预算闸门再次耗尽仍生效。多次人工重置后基线与 completed 绝对计数
        脱钩的口径错位由纯漂移分支的「重锚」自愈（expected > used 时把基线
        重锚为 completed − used，不改写 used）。豁免判定守卫（不改数分支）
        保持在基线改写之前、优先级不变。无该字段时对账口径与历史完全一致。
        """
        used = self._impl_run_budget_used(spec_name)
        completed = self._count_normal_completed_impl_runs(spec_name)
        # 扫描失败（计数不可用）≠ 权威 0：0 会被当成真实对账值把 used 改写
        # 清零（已耗尽的 spec 意外重获全部预算），故记 WARN 跳过本轮对账不改数。
        if completed is None:
            self._pm.logger.warning(
                "pm_engine",
                f"预算计数对账跳过: '{spec_name}' used={used}"
                f"（runs 目录扫描失败，无权威计数，本轮不改数）",
            )
            return
        # 人工重置基线：有锚点时对账目标 = 基线之后的新增正常收工 run 数。
        baseline = self._budget_manual_reset_baseline(spec_name)
        if baseline is None:
            expected = completed
            target_basis = f"runs 目录正常收工 run 数={completed}"
        else:
            expected = max(0, completed - baseline)
            target_basis = (
                f"runs 正常收工 run 数 {completed} − 人工重置基线 {baseline}={expected}"
            )
        if used == expected:
            return
        # 下调方向先排除在飞 run（item 425736ecfd76）：对账时刻同 spec 恰有
        # 新 run 已派发（启动计数已 +1）而产物尚未落盘时，completed 比 used
        # 少 1 是对账窗口假象，自动下调会把该 run 的计数永久吞掉（run 收工
        # 不再补 +1，预算少计）——保守不改数。
        # 守卫读观测到的 implementer_run 快照同步留作 CAS 锚（item
        # 0cfbe1852825）：守卫读与下方 used 改写非同一临界区，下调改写须
        # 锁内复核该快照未变才落盘。
        observed_run = ""
        if expected < used:
            unmaterialized, observed_run = self._impl_run_unmaterialized(spec_name)
            if unmaterialized:
                self._pm.logger.warning(
                    "pm_engine",
                    f"预算计数对账偏差（在飞实现 run）: '{spec_name}' used={used} vs "
                    f"{target_basis}"
                    f"（implementer_run 产物尚未可见，疑似启动计数已加、产物未落盘，"
                    f"不自动改数）",
                )
                return
        exemption = self._budget_reconcile_has_exemption(spec_name)
        if exemption is None:
            # 豁免因素不可知（item efb5917745cb 归档扫描失败 / item
            # c903cac4ac2e 豁免侧车字段损坏）：与上方 completed is None 同
            # 口径——本轮不改数（按无豁免继续会走纯漂移分支把 used 改写为
            # 更小值，已归档 run 的消耗/豁免退款被抹掉）。
            self._pm.logger.warning(
                "pm_engine",
                f"预算计数对账跳过: '{spec_name}' used={used}"
                f"（豁免因素不可知：归档目录扫描失败或豁免侧车字段损坏，"
                f"本轮不改数）",
            )
            return
        if exemption:
            self._pm.logger.warning(
                "pm_engine",
                f"预算计数对账偏差: '{spec_name}' used={used} vs "
                f"{target_basis}"
                f"（存在豁免因素：runs 产物保留上限/归档 或 死亡 run 豁免，"
                f"不自动改数，供人工核查）",
            )
            return
        # 人工重置基线的口径自愈（item 043e9fdd3ac7）：基线写入的是清零前
        # used（彼时的增量消耗），而 completed 是历史全量绝对计数；spec 经
        # 第二次及以后 continue_auto_fix 重置后（彼时 used==增量 ≠ completed
        # 全量），completed − 基线会把更早周期的历史 run 数幽灵式计回，
        # expected 虚高于 used——若按它上调改写 used 会再次回滚人工重置。
        # 「expected > used」即该口径错位的签名（正常收工的 run 必然 used 与
        # completed 同涨，二者只会在基线错位/used 异常丢失时脱钩）：把基线
        # 重锚为 completed − used（=重置时刻 completed 的快照），expected 随即
        # 归位为重置后新增；used 保持不变，留 INFO 留痕。
        if baseline is not None and expected > used:
            reanchored = max(0, completed - used)
            try:
                self._pm.state_machine.update_spec(
                    spec_name, {BUDGET_MANUAL_RESET_BASELINE_FIELD: reanchored}
                )
            except Exception as e:
                self._pm.logger.warning(
                    "pm_engine",
                    f"预算重置基线重锚写回失败 '{spec_name}': {e}",
                )
                return
            self._pm.logger.info(
                "pm_engine",
                f"预算重置基线重锚: '{spec_name}' baseline={baseline} → {reanchored}"
                f"（人工重置后基线口径错位自愈，used={used} 保持不变，"
                f"对账目标归位为重置后新增）",
            )
            return
        # 纯漂移（无豁免因素）：以 runs 实际计数为准改写 used（design D5）。
        # 下调方向改写经锁内条件写收敛（item 0cfbe1852825）：守卫读与写之间
        # 的窗口内，并发派发经 bump_impl_budget 完成 +1（启动计数与锚点改写
        # 分处两个临界区，run 锚未必先行变化）——仅复核 run 锚挡不住，故锁内
        # 同时复核 used 与 implementer_run 均未变化才落盘；任一已变即保守
        # 跳过本轮（与上方在飞守卫同口径），待下一轮对账收敛，启动计数不丢。
        # 上调方向同样收敛为锁内条件写（item 2fcdfc8f4451）：仅复核 used 未变
        # （check_run=False）——expected 出自 runs 计数扫描，run 锚不在该路径
        # 守卫读内、无快照可复核；并发派发的启动计数必先经 bump 改写 used，
        # used 复核已足以挡住覆盖丢失，已变即保守跳过本轮、待下一轮对账
        # 按新值收敛，启动计数不丢。
        try:
            if expected < used:
                corrected = self._pm.state_machine.set_impl_budget_used_if_unchanged(
                    spec_name, expected, used, observed_run
                )
                if not corrected:
                    self._pm.logger.warning(
                        "pm_engine",
                        f"预算对账自动校正跳过: '{spec_name}' used={used} → {expected}"
                        f"（对账窗口内 used/implementer_run 已被并发改写，"
                        f"疑似新派发启动计数已加，保守不改数）",
                    )
                    return
            else:
                corrected = self._pm.state_machine.set_impl_budget_used_if_unchanged(
                    spec_name, expected, used, check_run=False
                )
                if not corrected:
                    self._pm.logger.warning(
                        "pm_engine",
                        f"预算对账自动校正跳过: '{spec_name}' used={used} → {expected}"
                        f"（对账窗口内 used 已被并发改写，疑似新派发启动计数已加，"
                        f"保守不改数，待下一轮对账收敛）",
                    )
                    return
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"预算对账校正写回失败 '{spec_name}': {e}",
            )
            return
        if baseline is None:
            # 无人工基线：留痕文案与引入基线机制前逐字一致
            self._pm.logger.info(
                "pm_engine",
                f"预算对账自动校正: '{spec_name}' used={used} → {expected}"
                f"（runs 正常收工 run 数，无豁免因素；后续预算闸门按校正值生效）",
            )
        else:
            self._pm.logger.info(
                "pm_engine",
                f"预算对账自动校正: '{spec_name}' used={used} → {expected}"
                f"（{target_basis}，无豁免因素；后续预算闸门按校正值生效）",
            )

    def _budget_manual_reset_baseline(self, spec_name: str) -> int | None:
        """人工预算重置基线（``_budget_manual_reset_baseline``，无锚点返回 None）。

        continue_auto_fix 清零 used 时写入的清零前 used 值（item 043e9fdd3ac7）；
        对账据此把目标口径改为 ``max(0, 正常收工 run 数 − 基线)``，使历史
        run 数不再冲掉人工清零。字段缺失/空/非法 → None（对账沿用历史全量
        口径，行为与引入前完全一致）。
        """
        entry = self._pm.state_machine.read_one(spec_name) or {}
        raw = entry.get(BUDGET_MANUAL_RESET_BASELINE_FIELD)
        if raw is None or raw == "":
            return None
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return None

    def _impl_run_unmaterialized(self, spec_name: str) -> tuple[bool, str]:
        """最近派发的实现 run 产物在 runs 目录不可见（item 425736ecfd76）。

        STATE ``implementer_run`` 指向的产物既不在顶层 runs/ 也不在 archive/
        （按 run_id 前缀匹配，含 attempt/瞬态重试后缀）→ 视为「已派发未落盘」
        的在飞 run。产物已归档/可见时返回 False（归档场景由
        _budget_reconcile_has_exemption 兜底），无锚点返回 False。

        Returns: ``(unmaterialized, observed_run)``——``observed_run`` 为本次
        守卫读观测到的 ``implementer_run`` 快照（含空串），供调用方
        （_reconcile_impl_budget）作为锁内条件写（CAS）的复核锚（item
        0cfbe1852825）：锚与判定必须出自同一次读，分次读会放大而非消除窗口。
        """
        entry = self._pm.state_machine.read_one(spec_name) or {}
        current_run = str(entry.get("implementer_run") or "")
        if not current_run:
            return False, current_run
        runs_dir = self._pm.project_root / ".fenix" / "runs"
        for base in (runs_dir, runs_dir / "archive"):
            try:
                if base.is_dir() and any(base.glob(f"{current_run}*.jsonl")):
                    return False, current_run
            except OSError:
                # 扫描失败 ≠ 产物已可见（item dbcbc1495dc2）：按 False 处理会
                # 绕过 _reconcile_impl_budget 的在飞 run 守卫，纯漂移分支把
                # used 下调改写、在飞 run 的启动计数被永久吞掉——与同文件
                # _count_normal_completed_impl_runs 的保守口径（失败＝不可知、
                # 跳过本轮对账不改数）对齐，返回 True 视为未落盘、本轮不下调。
                return True, current_run
        return True, current_run

    def _budget_reconcile_has_exemption(self, spec_name: str) -> bool | None:
        """对账校正的豁免因素判定（lifecycle-hygiene 4.3 / design D5 + R2）。

        任一命中即有豁免因素，不自动改数：
        - 死亡 run 豁免发生过（_budget_exempt_runs > 0）：used 已回退，改数破坏豁免；
        - infra 失败预算退款发生过（_infra_failure_count > 0）：used 已回退
          （evo-infra-failure-budget-exempt R2），改数会把退款冲掉，豁免失效；
        - runs 产物被归档/保留上限（.fenix/runs/archive/ 下存在该 spec 的 impl 产物）：
          顶层计数不完整，改数会把 used 错误压到已归档前的值。

        返回 None（不可知）：豁免侧车字段损坏（``_budget_exempt_runs`` /
        ``_infra_failure_count`` 非整数字符串等，item c903cac4ac2e）或 archive
        归档目录扫描失败（OSError，item efb5917745cb）——豁免因素**不可知** ≠
        无豁免，与同文件 _count_normal_completed_impl_runs（扫描失败返回 None
        跳过对账）/ _impl_run_unmaterialized（扫描失败按未落盘保守处理）的
        「扫描失败＝不可知、本轮不改数」口径对齐：字段损坏按 0 兜底会把「有
        豁免」误判为「无豁免」，纯漂移分支把 used 改写为更小值，死亡豁免/
        infra 退款语义被静默冲掉、spec 意外重获预算。调用方
        （_reconcile_impl_budget）据此与 completed is None 同样跳过本轮对账
        不改数。
        """
        entry = self._pm.state_machine.read_one(spec_name) or {}
        try:
            exempt = int(entry.get(BUDGET_EXEMPT_RUNS_FIELD, 0) or 0)
        except (TypeError, ValueError):
            # 侧车字段损坏＝豁免因素不可知 ≠ 无豁免（item c903cac4ac2e）：
            # 按 0 兜底会走纯漂移分支改写 used，冲掉死亡豁免退款。与下方
            # archive 扫描失败（OSError → None）三态口径对齐，返回 None 跳过
            # 本轮对账；WARNING 留痕便于定位写坏来源。
            self._pm.logger.warning(
                "pm_engine",
                f"预算豁免侧车字段损坏 '{spec_name}'（{BUDGET_EXEMPT_RUNS_FIELD}"
                f" 非法，豁免因素不可知，本轮对账不改数）: "
                f"{entry.get(BUDGET_EXEMPT_RUNS_FIELD)!r}",
            )
            return None
        if exempt > 0:
            return True
        # ── infra 失败预算退款（R2）：有退款则改数会冲掉退款，豁免 ──
        try:
            infra_count = int(entry.get(INFRA_FAILURE_COUNT_FIELD, 0) or 0)
        except (TypeError, ValueError):
            # 同上（item c903cac4ac2e）：infra 侧车字段损坏＝不可知，返回 None
            # 跳过本轮对账，不按「无豁免」处理。
            self._pm.logger.warning(
                "pm_engine",
                f"预算豁免侧车字段损坏 '{spec_name}'（{INFRA_FAILURE_COUNT_FIELD}"
                f" 非法，豁免因素不可知，本轮对账不改数）: "
                f"{entry.get(INFRA_FAILURE_COUNT_FIELD)!r}",
            )
            return None
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
                # 归档扫描失败＝豁免因素不可知（item efb5917745cb，三态口径见
                # docstring）：返回 None，调用方跳过本轮对账不改数。
                return None
        return False

    def _count_normal_completed_impl_runs(self, spec_name: str) -> int | None:
        """从 .fenix/runs/ 侧车统计本 spec 正常收工的实现 run 数。

        run_id 规则 ``impl-<spec>-<ts>[-a<n>][-r<m>]``（每 attempt/瞬态重试一个
        产物文件，同一 run 的多 attempt/重试视为一个 run，取最新产物）。
        判据：产物末行（终态行）为 error ＝ 死亡 run，不计；
        凡末行非 error 一律计入正常收工——含 result 终态（成功或带收工
        结果的失败）、gate-blocked 等中间态收尾，以及空文件/进程中断流
        （无有效末行时同样按收工计入）。
        runs 目录缺失 ＝ 权威 0；扫描失败（IO/权限）返回 None——对账方
        （_reconcile_impl_budget）以本计数为权威改写 used，喂 0 会把预算
        瞬态清零，故失败必须与「真实 0」区分。单文件读取失败
        （_run_file_died 返回 None，item bb880517c83c）与单文件 stat 失败
        （mtime 不可得）同样整体降级 None。
        """
        runs_dir = self._pm.project_root / ".fenix" / "runs"
        if not runs_dir.is_dir():
            return 0
        newest_attempt: dict = {}
        # glob 是惰性生成器，迭代期间的 OSError（权限/IO 抖动）会向上冒泡进
        # 对账主流程（item ba82df251f21）——守卫写法与同文件
        # _impl_run_unmaterialized / _budget_reconcile_has_exemption 对齐：
        # 扫描失败返回 None（非 0），调用方据此跳过本轮对账不改数。
        try:
            for p in runs_dir.glob(f"impl-{spec_name}-*.jsonl"):
                if run_spec_part(p.stem) != spec_name:
                    continue  # 精确归属守卫（fix-x vs fix-x-y 前缀误命中全部排除）
                # 归并键剥除 attempt/瞬态重试后缀：-a1 与 -a1-r2 同属一个 run
                base = strip_run_id_suffixes(p.stem)
                try:
                    mtime = p.stat().st_mtime
                except OSError as e:
                    # 单文件 stat 失败（权限/IO 抖动、文件在 glob 与 stat 之间
                    # 被归档移动）＝该 run 收工与否不可知 ≠ 不存在——按 continue
                    # 剔除会让该 run 从 newest_attempt 归并中消失、completed
                    # 少计，无豁免因素时纯漂移分支把 used 改写成更小值，真实
                    # 消耗被抹掉。与上方目录扫描失败（item ba82df251f21）/下方
                    # 单文件读取失败（item bb880517c83c）口径对齐：整体降级
                    # None，调用方（_reconcile_impl_budget）跳过本轮对账不改数。
                    self._pm.logger.warning(
                        "pm_engine",
                        f"run 产物 stat 失败 '{spec_name}'（计数不可用）: {e}",
                    )
                    return None
                prev = newest_attempt.get(base)
                if prev is None or mtime > prev[0]:
                    newest_attempt[base] = (mtime, p)
        except OSError as e:
            self._pm.logger.warning(
                "pm_engine",
                f"runs 目录扫描失败 '{spec_name}'（计数不可用）: {e}",
            )
            return None
        count = 0
        for _mtime, path in newest_attempt.values():
            died = self._run_file_died(path)
            if died is None:
                # 单文件读取失败（item bb880517c83c）：收工与否不可知 ≠ 死亡——
                # 旧口径按死亡剔除会把 completed 压低，无豁免因素时纯漂移分支
                # 把 used 改写成更小值，真实消耗被抹掉、spec 意外多获预算。
                # 与上方目录扫描失败口径对齐：整体降级 None，调用方
                # （_reconcile_impl_budget）跳过本轮对账不改数。
                self._pm.logger.warning(
                    "pm_engine",
                    f"run 产物读取失败 '{spec_name}'（计数不可用）: {path.name}",
                )
                return None
            if not died:
                count += 1
        return count

    @staticmethod
    def _run_file_died(path: Path) -> bool | None:
        """实现 run 产物是否以 error 终态行收尾（死亡 run 判据，容错解析）。

        返回 None（不可知）：产物存在但读取失败（OSError，权限/IO 抖动、
        文件在 glob 与 open 之间被归档移动，item bb880517c83c）——与同文件
        目录扫描失败的保守口径对齐（不可知 ≠ 死亡），调用方据此整体降级
        跳过本轮对账；「确认 error 终态死亡」仍返回 True。

        终态判定只取决于「末条有效 dict 行」（item 66e369185609）：默认只读
        文件尾部窗口、从后向前找第一条有效 dict 行，产物大/修复周期累积时
        不再每次对账全量重读；窗口内不存在有效 dict 行（末条有效行在窗口
        之外、超长行被窗口起点截断）时回退全量读，判定与全量逐行读完全
        一致（空文件/末行未收尾半行/非法 JSON 行跳过等边界口径不变）。
        """

        def _last_valid_entry(lines: list) -> dict | None:
            # 与全量逐行读同口径：strip 后空行/非法 JSON/非 dict 跳过，
            # 从后向前第一条有效 dict 即全量读口径的末条有效 dict。
            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict):
                    return entry
            return None

        start = 0
        try:
            with path.open("rb") as f:
                f.seek(0, io.SEEK_END)
                size = f.tell()
                start = max(0, size - RUN_FILE_TAIL_SCAN_BYTES)
                if start > 0:
                    # 多读窗口起点前 1 字节判定首片段是否行首对齐：前一字节
                    # 非 \n 说明窗口起点落在行中间，首片段为残行须丢弃（残行
                    # 恰为末条有效行时由下方全量回退兜底；多字节 UTF-8 字符
                    # 不含 0x0A，行首对齐即字符对齐）。
                    f.seek(start - 1)
                    chunk = f.read(size - start + 1)
                else:
                    f.seek(0)
                    chunk = f.read()
        except OSError:
            return None
        # 文本模式逐行读的 universal newlines 口径（\n、\r\n、\r 同作行界）
        lines = (
            chunk.decode("utf-8", errors="replace")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
            .split("\n")
        )
        if start > 0 and chunk[:1] != b"\n":
            lines = lines[1:]
        last = _last_valid_entry(lines)
        if last is None and start > 0:
            # 尾部窗口内无有效 dict 行：末条有效行可能在窗口之外——回退
            # 全量读，判定与全量逐行读完全一致。
            try:
                with path.open("r", encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except OSError:
                return None
            last = _last_valid_entry(
                text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
            )
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
        # （str() 归一，code-review item 6292a4f1d3f6：STATE 坏条目 error 为
        # 非字符串真值时裸 .strip() 抛 AttributeError 穿透预算闸门）
        recent_error = str(entry.get("error") or "").strip()
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
