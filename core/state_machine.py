"""
state_machine.py — SPEC lifecycle state machine and STATE.md I/O.

Manages the finite state machine for SPECs:
  drafted → [reviewing →] ready → implementing → implemented → testing → verified → done → pushed
                                                       ↘ bug-found → implementing

Handles atomic reads/writes of STATE.md with file locking.
"""

import fcntl
import json
import os
import re
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── State definitions ──────────────────────────────────────────────


class SpecStatus:
    DRAFTED = "drafted"
    READY = "ready"
    IMPLEMENTING = "implementing"
    IMPLEMENTED = "implemented"
    TESTING = "testing"
    VERIFIED = "verified"
    BUG_FOUND = "bug-found"
    BLOCKED = "blocked"
    DONE = "done"
    PUSHED = "pushed"
    REVIEWING = "reviewing"

    ALL = [
        DRAFTED,
        READY,
        IMPLEMENTING,
        IMPLEMENTED,
        TESTING,
        VERIFIED,
        BUG_FOUND,
        BLOCKED,
        DONE,
        PUSHED,
        REVIEWING,
    ]


# 人工冻结标记（fix-restart-dual-dispatch S4）：结构化字段替代 error 文本契约。
# 此前 admin 巡检豁免靠 error 文本匹配（frozen: 前缀/「用户指令」子串），文案
# 漂移即失效（「人工冻结（…）」实测绕过豁免 → admin 每 15 分钟空探一次烧 token）。
# 冻结 = update_spec 写 {"frozen": True, "status": BLOCKED, "error": 前缀+原因}；
# 冻结期间所有自动链路对 status 的改写在 update_spec 内被剥离（82 个调用点
# 一次性收口），诊断字段（error/_retry_count 等）照写不丢上下文。
FROZEN_FIELD = "frozen"
FREEZE_ERROR_PREFIX = "用户指令冻结："


# ── SPEC 定时调度（add-spec-scheduling-controls D1）────────────────────
# 单一事实源 = STATE.md entry 字段：start_after（定时拾取）与 frozen_until
# （冻结定时解冻）均为可空 ISO8601 UTC，缺省 null（=无限制/永久冻结）。
# 序列化/解析在此声明（见 StateParser），保证 update_spec 透传的两字段真正
# 落盘——design 的「任意键透传」在 serialize 白名单下并不成立，字段须显式登记。
START_AFTER_FIELD = "start_after"
FROZEN_UNTIL_FIELD = "frozen_until"

# 手工激活哨兵（add-spec-manual-activation D1）：start_after 取值域的第三态。
# 值为 "manual" 时表示「永不到期，须人工激活后方可被调度器拾取」——与定时值
# （ISO8601 UTC）互斥，与 null（无限制）语义相反。哨兵是合法值而非脏值，
# 必须由 start_after_pending 显式分派（见该函数注释），勿下沉到 parse_utc
# （parse_utc 只认时间戳，哨兵不是时间）。
START_AFTER_MANUAL = "manual"


def parse_utc(value) -> Optional[datetime]:
    """ISO8601 UTC 解析（容错）。非法/空/None 返回 None，绝不抛异常。

    支持带偏移（2026-09-07T01:00:00+00:00）与 'Z' 后缀；naive 时间按 UTC
    解释。调度门控与 dashboard 写侧校验共用本函数（design D6「时间换算
    工具后端单点实现」），解析漂移收敛单点。
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except (ValueError, TypeError):
            return None
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def start_after_pending(entry: dict, now: Optional[datetime] = None) -> bool:
    """start_after 定时拾取门控：晚于当前时刻返回 True（未到期，应跳过派发）。

    语义（spec scheduled-spec-pickup）：
    - 字段缺失/null/非法格式一律视为不阻塞（解析失败 fail-open，脏值不卡死
      调度——与 ``_dispatch_backoffed`` 容错同型）。
    - 哨兵值 ``"manual"``（手工激活）显式判定为永远阻塞（语义与 fail-open 相反），
      必须在 parse_utc 之前分派——哨兵是合法值而非脏值，若下沉到 parse_utc 则
      被 fail-open 吞掉导致未激活 SPEC 被误派发（本次最核心的风险点）。
    - 早于/等于 now 的值等价 null（不阻塞拾取）。
    """
    value = (entry or {}).get(START_AFTER_FIELD)
    if value is None:
        return False

    # D1 哨兵判定：合法值且语义与 fail-open 相反（永远 pending），必须在此分派。
    # 大小写不敏感 + strip 容错人工手改 STATE.md。
    if isinstance(value, str) and value.strip().lower() == START_AFTER_MANUAL:
        return True  # 永不到期，等价「永远 pending」

    when = parse_utc(value)
    if when is None:
        return False
    if now is None:
        now = datetime.now(timezone.utc)
    return when > now


def start_after_blocks_promotion(entry: dict, config=None) -> bool:
    """组合谓词：start_after 未到期且 scope 为 full 时阻塞晋升/评审入口。

    仅用于**晋升/评审**入口（_on_spec_drafted、_on_spec_reviewing、
    _recover_one drafted/reviewing 分支）；**实现派发口** MUST 继续直接调
    ``start_after_pending``（无条件语义）。

    ``config=None`` 等价 ``dispatch``（不阻塞），与存量调用点零改动的兜底一致。
    异常不在此处吞——fail-open 由四处调用点既有的 try/except + warning 原样承担
    （design D3）。
    """
    from core.config import ConfigLoader
    return start_after_pending(entry) and ConfigLoader.get_start_after_scope(config) == "full"


def parse_orig_status(error) -> str:
    """从冻结 error 中解析「原状态 X」（人工冻结文本契约的共享读函数）。

    匹配格式：``用户指令冻结：原状态 testing · <reason>``（freeze_spec 写入）。
    缺失/非法时回退 ``ready``（迁移期存量 spec 无原状态记录的安全兜底）。
    """
    m = re.search(r"原状态\s+(\S+)", str(error or ""))
    if m:
        status = m.group(1).strip().rstrip("·，,。")
        if status:
            return status
    return SpecStatus.READY


# Valid state transitions: from → [to, ...]
VALID_TRANSITIONS: Dict[str, List[str]] = {
    SpecStatus.DRAFTED: [SpecStatus.READY, SpecStatus.REVIEWING],
    SpecStatus.READY: [SpecStatus.IMPLEMENTING],
    SpecStatus.IMPLEMENTING: [
        SpecStatus.IMPLEMENTED,
        SpecStatus.READY,
        SpecStatus.BLOCKED,
    ],  # ready=retry, blocked=熔断
    SpecStatus.IMPLEMENTED: [SpecStatus.TESTING],
    SpecStatus.TESTING: [SpecStatus.VERIFIED, SpecStatus.BUG_FOUND],
    SpecStatus.BUG_FOUND: [
        SpecStatus.IMPLEMENTING,
        SpecStatus.IMPLEMENTED,
    ],  # implemented=fix 完成后重新验证
    SpecStatus.REVIEWING: [SpecStatus.READY, SpecStatus.BLOCKED],
    SpecStatus.BLOCKED: [SpecStatus.READY, SpecStatus.REVIEWING],  # 人工确认后恢复 / 重新评审
    SpecStatus.VERIFIED: [SpecStatus.DONE],
    SpecStatus.DONE: [SpecStatus.PUSHED],
    SpecStatus.PUSHED: [],  # terminal state
}

# 门禁自动路径额外允许的「逃生门」转换（verifier-judgment-integrity D7 + add-blocked-reverify-lane）：
# - VERIFIED→TESTING：由 _on_spec_verified 门禁拦截触发的自动回退调用，保留断点。
# - BLOCKED→TESTING：env 阻塞冻结的 spec 在实现分支已合并时，由 admin 处置收尾
#   框架自动调用（transition_gate + 守卫），跳过全量重实现直达重验。
# 人工路径（直接调 transition）仍受 VALID_TRANSITIONS 约束被拒，不得绕过。
GATE_TRANSITIONS: Dict[str, List[str]] = {
    SpecStatus.VERIFIED: [SpecStatus.TESTING],
    SpecStatus.BLOCKED: [SpecStatus.TESTING],
}

# States that are considered "interrupted" on daemon restart (revert to ready)
INTERRUPTED_STATES = {SpecStatus.IMPLEMENTING, SpecStatus.TESTING, SpecStatus.REVIEWING}

# ── 实现尝试预算计数（fix-budget-counting-semantics D2）──────────────
# 字段名单点定义（pm_engine 与 state_machine 共用，避免两处漂移）：
# - _impl_run_budget_used：当前 spec 已累计启动的实现 run 次数
# - _budget_exempt_runs：死亡 run 豁免侧车计数（豁免不占预算，仅审计/告警）
# - _exempt_alerted：豁免阈值告警幂等标记（一次性，防重复告警）
IMPL_RUN_BUDGET_USED_FIELD = "_impl_run_budget_used"
BUDGET_EXEMPT_RUNS_FIELD = "_budget_exempt_runs"
BUDGET_EXEMPT_ALERTED_FIELD = "_exempt_alerted"
# - _budget_manual_reset_baseline：人工预算重置基线（continue_auto_fix 清零
#   used 时同批写入的清零前 used 值）。对账组件 _reconcile_impl_budget 见该
#   字段即把目标口径改为 max(0, 正常收工 run 数 − 基线)：历史 run 数不再冲掉
#   人工清零（否则对账把 used 改写回历史 run 数，人工重置在一个周期内被静默
#   回滚、预算闸门随即再冻结）；基线之后新产生的 run 消耗照常累计，闸门再次
#   耗尽仍生效。缺失（无人工重置）时对账口径与历史完全一致。
BUDGET_MANUAL_RESET_BASELINE_FIELD = "_budget_manual_reset_baseline"
# ── per-spec 预算覆盖属性（add-spec-status-modal-budget D3）────────────
# 人工管理属性：null/缺失 = 跟随全局 agents.impl_run_budget；正整数 = per-spec
# 有效预算（上限由 agents.impl_run_budget_max 决定，open-impl-budget-ceiling）。
# 与 priority/start_after 同类，须随条目序列化（serialize 显式键表）。
IMPL_RUN_BUDGET_OVERRIDE_FIELD = "impl_run_budget_override"

# ── 重启重验预算计数（fix-daemon-lifecycle-races D3）──────────────────
# - _verify_redo_count：daemon 重启恢复路径（testing→implemented 重派 verify）
#   的累计次数，跨重启持久化；与 _verify_fail_rounds（失败→fix 轮数）语义正交，
#   互不读写对方字段。达 agents.verify_redo_budget 阈值即冻结等待人工裁决，
#   堵死「毒 spec 借反复重启无限重验」敞口。
VERIFY_REDO_COUNT_FIELD = "_verify_redo_count"
# 重启重验预算缺省阈值（agents.verify_redo_budget 未配置时沿用本值）
DEFAULT_VERIFY_REDO_BUDGET = 3

# ── 冻结终止保持标记（add-freeze-stop-inflight-agents D3）──────────────
# _frozen_hold：spec 被冻结终止（run 因 frozen 被强杀、现场已 WIP 保全）后
# 的独立保持标记，与 _cancelled_hold 并列且互不读写：
# - _cancelled_hold：人工取消 run → 有意等待态，唯一出路是显式复位；恢复链路跳过。
# - _frozen_hold：冻结终止 → 现场已保全，出路是 unfreeze（清 frozen + 清
#   _frozen_hold + 置 _recovery_resume 续做）；恢复链路不因它跳过（冻结期间
#   由 frozen 字段挡住一切派发，_frozen_hold 只是续做依据）。
# 冻结终止路径 MUST 先清 _cancelled_hold（避免解冻后恢复链路按取消保持跳过）。
FROZEN_HOLD_FIELD = "_frozen_hold"

# ── env 阻塞轮次生命周期计数（add-blocked-reverify-lane D3）──────────
# 字段名单点定义（pm_engine 与 state_machine 共用，避免两处漂移）：
# _env_block_rounds：spec 生命周期内累计的 env 阻塞轮数（跨 admin 处置复位/
# daemon 恢复/fix 链等中间转换不清零）。唯一清零点=验证通过（verified 落定，
# 与 _verify_fail_rounds 的 PASS 唯一归零点同语义）与人工 unfreeze_spec。
# 冻结阈值（rounds >= 2）判定在 pm_engine.verification 升级通道。
ENV_BLOCK_ROUNDS_FIELD = "_env_block_rounds"

# ── 基础设施失败预算豁免侧车（evo-infra-failure-budget-exempt R2/R3）──
# 字段名单点定义（pm_engine 与 state_machine 共用，避免两处漂移）：
#
# - _infra_failure_count：生命周期累计的 infra 失败次数（观测值，不归零，
#   与 _budget_exempt_runs 同范式）。用于对账豁免判定与 dashboard 可观测。
#
# - _verify_infra_rounds：本轮验证周期内 infra 失败轮次（纯观测，
#   **不参与** MAX_VERIFY_FAIL_ROUNDS 冻结判定；与 _verify_fail_rounds
#   同生命周期，验证 PASS 唯一归零点清零）。
#
# - _infra_refunded_run_ids：JSON 字符串数组（已退款验证 run_id）；
#   infra 预算退款幂等锚点，避免同一验证轮重复扣减（退款一次/轮）。
INFRA_FAILURE_COUNT_FIELD = "_infra_failure_count"
VERIFY_INFRA_ROUNDS_FIELD = "_verify_infra_rounds"
INFRA_REFUNDED_RUN_IDS_FIELD = "_infra_refunded_run_ids"

# ── 任务完成度类产物硬门跨轮拒绝计数（2026-09-16 改进①「只卡第一次」）──
# _impl_gate_task_rejections：实现 run 的产物硬门以 [task-gate] 前缀（未勾任务
# / completed_tasks 不一致 / TaskUpdate 交叉核对 / partial 申报不一致）拒绝的
# 累计次数，跨 dispatch 持久化。达阈值后 runner 降级为警告放行，避免实现者已
# 诚实说明「确实无法满足」时被同一门无限拒回原地重试（a2/a3 × 3 重试死循环）。
# 门禁干净通过或全新派发时清零。结构类失败不计数。
TASK_GATE_REJECTIONS_FIELD = "_impl_gate_task_rejections"

# ── spec 级结构化诊断（fix-run-hang-amplification 2.3）──────────────
# _impl_diagnosis：run 终结时写入的结构化诊断摘要（终态类型 + 归因 +
# 已定性结论 + 已提交进度），重派 attempt 经 PromptBuilder 注入（诊断继承）。
# 值存 JSON 字符串（STATE.md 行内可往返解析，避免裸 dict 序列化后语义漂移）。
# 序列化：`_` 前缀字段由 serialize 自动透传（含本字段），解析端按字符串读回，
# 无需类型转换登记——此处定义常量作为单一事实源供写侧/注入侧共用。
IMPL_DIAGNOSIS_FIELD = "_impl_diagnosis"

# ── 场景原地修复预算耗尽轮次（fix-recovery-path-blockers D4）──────────
# 字段名单点定义（pm_engine 与 state_machine 共用，避免两处漂移）：
# _scenario_repair_exhausted_rounds：spec 生命周期内「场景原地修复预算耗尽」
# 的跨轮持久计数（0=尚未给过重验日程；>=1=已给过一次重验仍不收敛）。与
# _judge_rerun_count 同生命周期累计语义：**唯一**清零点 = 验证通过
# （verified 落定，_record_verdict_adoption 内既有 verified 分支）与人工
# unfreeze_spec（对齐 _env_block_rounds 既有语义——人工解冻是唯一人工裁决
# 出口）。MUST NOT 在 admin 处置复位 / daemon 恢复 / 中间转换清零——否则
# 「毒 spec 借每次 admin 复位重置计数 → 无限循环」敞口复开。
SCENARIO_REPAIR_EXHAUSTED_FIELD = "_scenario_repair_exhausted_rounds"


# ── STATE.md Parser ─────────────────────────────────────────────────


def _escape_state_value(val) -> str:
    """字段值单行化：换行转义为字面量 ``\\n``（反斜杠先转义保证可往返）。

    STATE.md 是行式格式，值内裸换行会让续行脱离条目结构（解析侧静默丢弃
    或被误解析成伪造字段）。异常文本（git/subprocess 报错等）常含多行，
    写入端统一消毒，解析端经 ``_unescape_state_value`` 逆变换往返。
    """
    s = str(val)
    s = s.replace("\\", "\\\\")
    s = s.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\r")
    return s


_UNESCAPE_STATE_VALUE_RE = re.compile(r"\\\\|\\n|\\r")


def _unescape_state_value(val: str) -> str:
    """``_escape_state_value`` 的逆变换（单趟左到右扫描，正确处理 ``\\\\n``）。"""
    return _UNESCAPE_STATE_VALUE_RE.sub(
        lambda m: {"\\n": "\n", "\\r": "\r", "\\\\": "\\"}[m.group(0)], val
    )


class StateParser:
    """Parse and serialize STATE.md entries."""

    @staticmethod
    def parse(state_path: Path) -> Dict[str, dict]:
        """
        Parse STATE.md and return {spec_name: entry_dict}.

        Expected entry format:
        ### <spec-name>
        - status: <value>
        - priority: <integer>
        - created: <ISO 8601>
        - updated: <ISO 8601>
        - implementer_run: <run-id or null>
        - tester_run: <run-id or null>
        - branch: <branch-name or null>
        - error: <error-message or null>
        """
        if not state_path.exists():
            return {}

        content = state_path.read_text(encoding="utf-8")
        return StateParser._parse_content(content)

    @staticmethod
    def _parse_content(content: str) -> Dict[str, dict]:
        """Parse content string into spec entries."""
        specs = {}
        current_name = None
        current_entry = {}

        in_comment = False
        for line in content.split("\n"):
            # 跳过 HTML 注释块：块状态机跟踪，进入 <!-- 后跳过直到 --> 的
            # 全部行（注释内的字段行不再被 kv 正则误并入前一条目）；同行
            # 闭合的 <!-- xxx --> 只跳过本行；未闭合注释块（有 <!-- 无 -->）
            # 到文件末尾均视为注释。普通字段值行恰以 --> 结尾（如
            # note: a --> b）不再被整体丢弃。
            if in_comment:
                if "-->" in line:
                    in_comment = False
                continue
            if line.strip().startswith("<!--"):
                if "-->" not in line:
                    in_comment = True
                continue

            # Match ### <spec-name>
            header_match = re.match(r"^###\s+(.+)$", line)
            if header_match:
                if current_name and current_entry:
                    if "status" in current_entry:
                        # Only accept entries with valid status values
                        if current_entry["status"] in SpecStatus.ALL:
                            specs[current_name] = current_entry
                current_name = header_match.group(1).strip()
                current_entry = {}
                continue

            # Match - key: value（键名允许小写字母/下划线/数字，支持 _token_warn_80
            # 等带数字的内部字段；原有键名均不含数字，放宽不影响既有解析）
            kv_match = re.match(r"^-\s+([a-z_][a-z0-9_]*):\s*(.*)$", line)
            if kv_match and current_name:
                key = kv_match.group(1)
                value = _unescape_state_value(kv_match.group(2).strip())

                # Type coercion
                if key in ("priority",):
                    try:
                        value = int(value)
                    except ValueError:
                        value = 999
                elif key == IMPL_RUN_BUDGET_OVERRIDE_FIELD:
                    # per-spec 预算覆盖：整数值显式转换（写入端恒 int 或 null；
                    # 非法值按 null 容错，闸门读侧以 clamp 兜底）
                    try:
                        value = int(value)
                    except ValueError:
                        value = None
                elif key in (
                    FROZEN_FIELD,
                    "_recovery_resume",
                    "_cancelled_hold",
                    FROZEN_HOLD_FIELD,  # add-freeze-stop-inflight-agents D3
                    "_repair_awaiting_remerge",
                    "_judge_cap_frozen",
                    # evo-merge-back-spec-dir-inflight-guard D2：merge-only 重试
                    # 顺延标记——False 不转会被误判为恒顺延（_defer_merge_back
                    # 读回字符串 "False" 为 truthy）。
                    "_merge_retry_pending",
                    # evo-add-wip-defer-merge-retry-consumer 1.2：WIP 重叠闸门
                    # 阻断的延迟合回等待标志——False 不转会 STATE.md 往返后
                    # 读回字符串 "False" 为 truthy，周期消费者会把已清账条目
                    # 误判为仍带标志（同 _merge_retry_pending 先例）。
                    "_wip_gate_deferred",
                ):
                    # 布尔字段显式转换：字符串 "False" 也是 truthy，不转会把
                    # 解冻后的 spec 永久误判为冻结（fix-restart-dual-dispatch S4）；
                    # _recovery_resume（interrupt-recovery-preserve）同型处理。
                    # _cancelled_hold（fix-cancel-holdstate-recovery D1）：取消保持
                    # 标记随 STATE.md 往返，False 不转会被误判为保持态。
                    # _frozen_hold（add-freeze-stop-inflight-agents D3）：冻结终止
                    # 保持标记与 _cancelled_hold 并列，False 不转会把解冻后无冻结终止
                    # 的 spec 永久误判为冻结保持态（解冻后续做判定失效）。
                    # _repair_awaiting_remerge（fix-recovery-branch-anchor D3）：
                    # 「待 re-merge-back」标记，False 不转会被误判为恒待合并。
                    # _judge_cap_frozen（judge-rerun-stability R1）：judge 重跑
                    # hard cap 冻结标记，False 不转会被误判为恒冻结。
                    value = value.lower() in ("true", "1", "yes")
                elif key in (
                    "implementer_run",
                    "tester_run",
                    "branch",
                    "error",
                    "total_duration",
                    START_AFTER_FIELD,
                    FROZEN_UNTIL_FIELD,
                    "_verify_parallel_override",
                    "reviewer_run",
                    "_repair_base_tip",
                    "_repair_merge_error",
                    # evo-merge-back-spec-dir-inflight-guard D2：顺延窗口起点
                    # （epoch 秒）可空——None 经 serialize 写 null、解析回退 None，
                    # 否则 "null" 字符串被 float() 吃掉整条顺延记账。
                    "_merge_retry_first_at",
                    # 同因重派熔断（fix-redispatch-loop-governance D3.2）：归因指纹
                    # 可空字段——None 经 serialize 写 null、解析回退 None（否则
                    # 「null」字符串会被 prev_fp == fp 比较吞掉，跨重启熔断失效）。
                    "_redispatch_cause_fp",
                ):
                    if value.lower() in ("null", "none", ""):
                        value = None

                current_entry[key] = value

        # Don't forget the last entry
        if current_name and current_entry and "status" in current_entry:
            if current_entry["status"] in SpecStatus.ALL:
                specs[current_name] = current_entry

        return specs

    @staticmethod
    def serialize(specs: Dict[str, dict]) -> str:
        """Serialize spec entries back into STATE.md format."""
        lines = [
            "# Fenix Project State",
            "# ====================",
            "# Auto-generated by fenixd. Records all SPECs and their current status.",
            f"# Last updated: {datetime.now(timezone.utc).isoformat()}",
            "",
            "## Specs",
            "",
        ]

        # Sort by priority then created time
        sorted_specs = sorted(
            specs.items(),
            key=lambda item: (
                item[1].get("priority", 999),
                item[1].get("created", ""),
            ),
        )

        for name, entry in sorted_specs:
            lines.append(f"### {name}")
            for key in [
                "status",
                "priority",
                "created",
                "updated",
                "implementer_run",
                "tester_run",
                "branch",
                "error",
                "depends_on",
                "total_duration",
                FROZEN_FIELD,
                START_AFTER_FIELD,
                FROZEN_UNTIL_FIELD,
                IMPL_RUN_BUDGET_OVERRIDE_FIELD,
                "reviewer_run",
            ]:
                val = entry.get(key, "null")
                if val is None:
                    val = "null"
                lines.append(f"- {key}: {_escape_state_value(val)}")
            # 追加内部状态字段（_ 前缀，如 _retry_count/_merge_fp/_merge_streak），
            # 使其跨 daemon 重启持久化（fix-fenix-token-waste：熔断计数依赖它）
            for key, val in entry.items():
                if key.startswith("_"):
                    if val is None:
                        val = "null"
                    lines.append(f"- {key}: {_escape_state_value(val)}")
            lines.append("")

        return "\n".join(lines)


# ── State Machine ───────────────────────────────────────────────────


class _NullLogger:
    """静默日志器：logger 为 None 时兜底，避免各方法无条件调用 self.logger 崩溃。

    适用于脚本直接构造 StateMachine（如 spec 流程）且不需要日志的场景。
    凡**会写 STATE.md 的生产构造点** MUST NOT 落到本兜底（会形成无日志的静默
    写入路径）——dashboard 侧的跨进程写入者经 ``project_state_logger`` 注入
    真实 logger（fix-state-atomicity-and-selfheal-restart D2/1.3）。
    """

    def debug(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


# ── 跨进程写入者的真实日志器（fix-state-atomicity-and-selfheal-restart 1.3）──

_STATE_LOGGER_CACHE: Dict[str, object] = {}
_STATE_LOGGER_CACHE_LOCK = threading.Lock()


def project_state_logger(project_root):
    """构造（并按项目根复用）指向 ``<project_root>/.fenix/logs`` 的真实日志器。

    ``StateMachine.__init__`` 在 ``logger=None`` 时兜底 ``_NullLogger``，使写入
    完全静默。dashboard 是**独立进程**的 STATE.md 写入者，此前三处构造点均以无
    logger 形态构造（design D2），正是 2026-09-21「``updated`` 已变但
    fenixd.log 无 "Updated SPEC" 记录」的成因。本 helper 让这些构造点注入与
    daemon 同源的 ``core.logger.Logger``（JSON 行落
    ``.fenix/logs/fenixd.log``，即 dashboard 的日志观测通道）。

    按项目根缓存实例：``core.logger.Logger.__init__`` 会重绑全局 "fenixd" 根
    日志器的 handler，重复构造会关掉前一实例的 handler；缓存后每个项目只构造
    一次（多项目部署下不再互相踩 handler）。

    Args:
        project_root: 目标项目根（STATE.md 所在 ``.fenix/`` 的父目录）。

    Returns: 具备 ``debug/info/warning/error(component, message, context=None)``
        接口的日志器实例。
    """
    key = str(Path(project_root).resolve())
    with _STATE_LOGGER_CACHE_LOCK:
        cached = _STATE_LOGGER_CACHE.get(key)
    if cached is not None:
        return cached
    from core.logger import Logger  # 延迟 import：仅跨进程写入点需要

    built = Logger(Path(project_root) / ".fenix" / "logs")
    with _STATE_LOGGER_CACHE_LOCK:
        # 并发构造同项目：先到者生效，二者语义等价（同路径同格式）
        return _STATE_LOGGER_CACHE.setdefault(key, built)


class StateMachine:
    """
    Manages the lifecycle state machine for all SPECs.
    Provides atomic read/write access to STATE.md.
    """

    def __init__(self, state_path: Path, logger=None):
        self.state_path = Path(state_path)
        # logger 允许为 None（脚本场景）：兜底为静默日志器，保证 add_spec/transition 等
        # 方法内无条件 self.logger.* 调用不崩溃
        self.logger = logger if logger is not None else _NullLogger()
        # 跨进程写锁单源（code-review item 59f2136ef670）：全部加锁点统一引用
        # 本属性。旧实现误指向 STATE.md.lock（从未被使用），真实加锁文件是
        # .STATE.md.lock——两套路径并存会诱导后续维护者据 _lockfile 协调而锁形
        # 同虚设。
        self._lockfile = self.state_path.parent / ".STATE.md.lock"
        # 状态文件与 .STATE.md.lock 均在 state_path.parent 下打开；状态文件迁入
        # .fenix/ 后父目录不再恒存在（项目根），构造时确保之（新项目首写路径）
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Read / Write ───────────────────────────────────────────────

    def read_all(self) -> Dict[str, dict]:
        """Read all SPEC entries from STATE.md.

        防御层（fix-dispatch-orphan D3）：解析结果必须被规范化为
        ``{name: dict}``。若解析产物混入非 dict 条目（并发撕裂写入、
        外部工具改写 STATE.md、或未来解析路径回归），跳过该条目并记
        warning，绝不使其进入返回值——否则下游 ``entry.get("status")``
        会抛 ``AttributeError``/``TypeError``（事故家族
        ``string indices must be integers``），整轮 full_scan 静默中止。
        """
        raw = StateParser.parse(self.state_path)
        return self._normalize_entries(raw)

    def _normalize_entries(self, raw: Dict[str, dict]) -> Dict[str, dict]:
        """过滤非 dict 条目，保证返回值的每个条目都是 dict。

        不修改合法条目的任何字段，仅把非法条目（字符串/列表/None 等）
        剔除并记日志。返回新 dict，不改动入参。
        """
        normalized: Dict[str, dict] = {}
        for name, entry in raw.items():
            if isinstance(entry, dict):
                normalized[name] = entry
                continue
            # 非法条目：不得进入返回值，记 warning（self.logger 由 __init__
            # 兜底保证非 None，logger=None 的脚本场景自然静默）。
            self.logger.warning(
                "state_machine",
                f"跳过非法条目 '{name}'：期望 dict，实际为 "
                f"{type(entry).__name__}，已忽略以防扫描崩溃",
            )
        return normalized

    def read_one(self, spec_name: str) -> Optional[dict]:
        """Read a single SPEC entry."""
        all_specs = self.read_all()
        return all_specs.get(spec_name)

    def write_all(self, specs: Dict[str, dict]):
        """Atomically write all SPEC entries to STATE.md with file locking.

        Thread-safe: each call uses a unique temp file (pid + tid + counter),
        and the final STATE.md write is serialized by flock on a lock file.
        """
        # Serialize the final rename via flock on a dedicated lock file.
        # 注意：调用方若已持有该锁（如 _bump_counter），必须走 _write_all_locked，
        # 否则同进程二次 flock 会自阻塞死锁。
        lock_path = self._lockfile
        with open(lock_path, "w") as lock_f:
            fcntl.flock(lock_f, fcntl.LOCK_EX)
            try:
                self._write_all_locked(specs)
            finally:
                fcntl.flock(lock_f, fcntl.LOCK_UN)

    def _write_all_locked(self, specs: Dict[str, dict]):
        """write_all 的锁内实现（temp 写盘 + rename），不加锁。

        供已持有 .STATE.md.lock 的调用方（_bump_counter）复用；write_all 是
        本方法 + flock 的组合。flock 按打开文件描述符生效，同进程对同一文件
        的第二个 fd 再 flock 会阻塞，故锁内不得再走 write_all。
        """
        import threading

        content = StateParser.serialize(specs)
        parent = self.state_path.parent

        # Use per-thread unique temp name to avoid threads clobbering each other
        tid = threading.get_ident()
        tmp_fd, tmp_path_str = tempfile.mkstemp(
            prefix=f".STATE.md.{os.getpid()}.{tid}.",
            suffix=".tmp",
            dir=str(parent),
        )
        tmp_path = Path(tmp_path_str)
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.rename(str(tmp_path), str(self.state_path))
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    # ── 锁内原子读改写范式（fix-state-atomicity-and-selfheal-restart D1）──

    def _mutate_locked(self, mutate):
        """在 ``.STATE.md.lock`` 的 ``flock(LOCK_EX)`` 内执行「读 → 改 → 写」。

        ``mutate(specs)`` 在持锁期间被调用，MUST 返回 ``(result, changed)``；
        ``changed`` 为真时经 ``_write_all_locked`` 落盘，否则只读不写。

        收紧的正是丢失更新窗口：改动前 ``update_spec`` / ``add_spec`` /
        ``remove_spec`` 的 ``read_all()`` 与 ``write_all()`` 分处锁外锁内，
        并发写者（daemon 多 worker 线程 + dashboard 独立进程）各自持陈旧快照
        整体回写，后写者覆盖先写者（2026-09-21 事故：评审 run 写入的
        ``reviewer_run`` 被更早快照覆盖回 ``null``，评审结果永不消费）。收进
        同一把锁后读到的永远是上一写入者提交后的最新态——与 ``_bump_counter``
        同范式（该路径已在 fix-budget-counting-semantics D2 验证）。

        锁内 MUST 只调 ``_write_all_locked``：``write_all`` 会对同一文件再取
        一次 flock，同进程二次 flock 自阻塞（见 ``_write_all_locked`` 注释）。

        Returns: ``mutate`` 返回的 ``result``（类型由调用方约定）。
        """
        lock_path = self._lockfile
        with open(lock_path, "w") as lock_f:
            fcntl.flock(lock_f, fcntl.LOCK_EX)
            try:
                specs = self.read_all()
                result, changed = mutate(specs)
                if changed:
                    self._write_all_locked(specs)
                return result
            finally:
                fcntl.flock(lock_f, fcntl.LOCK_UN)

    # ── 预算计数原子原语（fix-budget-counting-semantics D2）──────────

    def _bump_counter(self, spec_name: str, field: str, delta: int) -> int:
        """文件锁内原子读改写计数器字段并回读校验。

        消除「读 STATE → 改 → 写回」非原子序列在并发（恢复扫描 × 派发）下
        丢失增量的竞态（interaction-contract 复盘：used=2/4 连续出现两次）。
        锁内完成 读→改→写→回读校验；回读不匹配时重试一次并记审计日志。
        结果下限 0（delta=-1 时不会把计数打成负数）。

        Returns: 最终生效值；spec 不存在时记 warning 并返回 0。
        """
        lock_path = self._lockfile
        verify = 0
        for attempt in (1, 2):
            with open(lock_path, "w") as lock_f:
                fcntl.flock(lock_f, fcntl.LOCK_EX)
                try:
                    specs = self.read_all()
                    if spec_name not in specs:
                        self.logger.warning(
                            "state_machine",
                            f"bump {field} failed: SPEC not found: {spec_name}",
                        )
                        return 0
                    try:
                        current = int(specs[spec_name].get(field, 0) or 0)
                    except (TypeError, ValueError):
                        current = 0
                    new_value = max(0, current + delta)
                    specs[spec_name][field] = new_value
                    specs[spec_name]["updated"] = datetime.now(timezone.utc).isoformat()
                    self._write_all_locked(specs)
                    # 回读校验：确认增量真正落盘（防并发写覆盖丢增量）
                    verify = int((self.read_all().get(spec_name) or {}).get(field, 0) or 0)
                finally:
                    fcntl.flock(lock_f, fcntl.LOCK_UN)
            if verify == new_value:
                return new_value
            self.logger.warning(
                "state_machine",
                f"bump {field} verify mismatch for '{spec_name}' "
                f"(attempt {attempt}): wrote {new_value}, read back {verify} — "
                f"并发写覆盖，已重试",
            )
        # 重试后仍不匹配：返回磁盘实际值（以落盘为准），由调用方审计
        return verify

    def bump_counters(self, spec_name: str, deltas: Dict[str, int]) -> Dict[str, int]:
        """多字段计数器锁内原子读改写（``_bump_counter`` 的多字段版）。

        同一临界区内同时递增多个计数器字段——分次单字段 bump 会在两次加锁
        之间暴露窗口（他写者夹在中间写入，读者看到半新态）；fastlane 失败
        记账须同点同时递增 ``_fastlane_fail_streak`` 与 ``_verify_fail_rounds``
        （与整轮失败同账），走本原语保持计数路径单一范式。
        与 ``_bump_counter`` 同范式：锁内 读→改→写→回读校验，不匹配重试一次；
        各字段结果下限 0（负 delta 不会把计数打成负数）。

        Returns: ``{field: 最终生效值}``；spec 不存在时记 warning 并返回全 0。
        """
        lock_path = self._lockfile
        verify: Dict[str, int] = {field: 0 for field in deltas}
        for attempt in (1, 2):
            new_values: Dict[str, int] = {}
            with open(lock_path, "w") as lock_f:
                fcntl.flock(lock_f, fcntl.LOCK_EX)
                try:
                    specs = self.read_all()
                    if spec_name not in specs:
                        self.logger.warning(
                            "state_machine",
                            f"bump {sorted(deltas)} failed: SPEC not found: {spec_name}",
                        )
                        return {field: 0 for field in deltas}
                    entry = specs[spec_name]
                    for field, delta in deltas.items():
                        try:
                            current = int(entry.get(field, 0) or 0)
                        except (TypeError, ValueError):
                            current = 0
                        new_values[field] = max(0, current + delta)
                        entry[field] = new_values[field]
                    entry["updated"] = datetime.now(timezone.utc).isoformat()
                    self._write_all_locked(specs)
                    # 回读校验：确认增量真正落盘（防并发写覆盖丢增量）
                    verify = {
                        field: int((self.read_all().get(spec_name) or {}).get(field, 0) or 0)
                        for field in deltas
                    }
                finally:
                    fcntl.flock(lock_f, fcntl.LOCK_UN)
            if verify == new_values:
                return new_values
            self.logger.warning(
                "state_machine",
                f"bump {sorted(deltas)} verify mismatch for '{spec_name}' "
                f"(attempt {attempt}): wrote {new_values}, read back {verify} — "
                f"并发写覆盖，已重试",
            )
        # 重试后仍不匹配：返回磁盘实际值（以落盘为准），由调用方审计
        return verify

    def bump_impl_budget(self, spec_name: str, delta: int) -> int:
        """实现尝试预算计数原子增减（``_impl_run_budget_used``）。

        启动计数（delta=+1）与死亡豁免（delta=-1，下限 0）统一走本函数。

        Returns: 递增/回退后的使用次数（跨重启持久化）。
        """
        return self._bump_counter(spec_name, IMPL_RUN_BUDGET_USED_FIELD, delta)

    def refund_impl_budget_once(self, spec_name: str, anchor: str) -> tuple:
        """infra 预算退款的锁内原子「查锚点 → 退款 → 记锚点」（item 40f7a931dc4c）。

        旧路径 ``read_one`` 查锚 → ``bump_impl_budget(-1)`` → ``update_spec``
        记锚三步分持多把锁：同一 run 的并发 infra 判定都读不到锚点、各自
        退款一次（丢失更新形态）。本方法把三步收进单把 ``.STATE.md.lock``
        临界区（与 _bump_counter 同范式）：锚点已登记 → 幂等跳过不退款；
        未登记的非空锚点 → 退款并追加锚点一次完成。空锚点只退款、不登记，
        幂等不保证——由调用方保证单轮单次（契约见
        ``_exempt_infra_run_budget``：无锚点时仍退款）。

        Returns: ``(refunded, used)``
            refunded=False 表示该 run 已退款过（幂等跳过）；used 为退款后
            （或幂等跳过时的当前）used 值。spec 缺失按旧 bump 路径容错：
            记 warning 并返回 (True, 0)，不阻断调用方。
        """
        lock_path = self._lockfile
        with open(lock_path, "w") as lock_f:
            fcntl.flock(lock_f, fcntl.LOCK_EX)
            try:
                specs = self.read_all()
                if spec_name not in specs:
                    self.logger.warning(
                        "state_machine",
                        f"refund impl budget failed: SPEC not found: {spec_name}",
                    )
                    return True, 0
                entry = specs[spec_name]
                refunded_raw = entry.get(INFRA_REFUNDED_RUN_IDS_FIELD) or "[]"
                try:
                    refunded = (
                        json.loads(refunded_raw) if isinstance(refunded_raw, str) else []
                    )
                except (json.JSONDecodeError, TypeError, ValueError):
                    refunded = []
                if not isinstance(refunded, list):
                    refunded = []
                try:
                    used = int(entry.get(IMPL_RUN_BUDGET_USED_FIELD, 0) or 0)
                except (TypeError, ValueError):
                    used = 0
                if anchor and anchor in refunded:
                    return False, used
                entry[IMPL_RUN_BUDGET_USED_FIELD] = max(0, used - 1)
                if anchor:
                    refunded.append(anchor)
                    entry[INFRA_REFUNDED_RUN_IDS_FIELD] = json.dumps(
                        refunded, ensure_ascii=False
                    )
                entry["updated"] = datetime.now(timezone.utc).isoformat()
                self._write_all_locked(specs)
                return True, entry[IMPL_RUN_BUDGET_USED_FIELD]
            finally:
                fcntl.flock(lock_f, fcntl.LOCK_UN)

    def bump_task_gate_rejections(self, spec_name: str, delta: int = 1) -> int:
        """任务完成度类产物硬门拒绝计数原子增减（``_impl_gate_task_rejections``）。

        改进①「只卡第一次」：每次 [task-gate] 类失败 +1，达阈值后 runner 降级
        放行；门禁干净通过或全新派发时经 ``reset_task_gate_rejections`` 清零。

        Returns: 增减后的累计值（跨重启持久化）。
        """
        return self._bump_counter(spec_name, TASK_GATE_REJECTIONS_FIELD, delta)

    def reset_task_gate_rejections(self, spec_name: str) -> int:
        """任务完成度类产物硬门拒绝计数原子归零（code-review item c08bc3db202d）。

        「读当前值 → 置 0」在同一文件锁临界区内完成。调用方不得再走
        ``read_one → bump_task_gate_rejections(delta=-cur)`` 两段式：读与写
        分持两把锁，其间并发 bump 会被 -cur 补偿吞掉（或留下过时正值）——
        正是 ``_bump_counter`` 注释声称已修复的丢失更新形态。

        Returns: 归零前的计数值（0 = 本就干净；spec 不存在记 warning 返回 0）。
        """
        lock_path = self._lockfile
        with open(lock_path, "w") as lock_f:
            fcntl.flock(lock_f, fcntl.LOCK_EX)
            try:
                specs = self.read_all()
                if spec_name not in specs:
                    self.logger.warning(
                        "state_machine",
                        "reset task_gate_rejections failed: "
                        f"SPEC not found: {spec_name}",
                    )
                    return 0
                try:
                    current = int(
                        specs[spec_name].get(TASK_GATE_REJECTIONS_FIELD, 0) or 0
                    )
                except (TypeError, ValueError):
                    current = 0
                if current != 0:
                    specs[spec_name][TASK_GATE_REJECTIONS_FIELD] = 0
                    specs[spec_name]["updated"] = datetime.now(timezone.utc).isoformat()
                    self._write_all_locked(specs)
                return current
            finally:
                fcntl.flock(lock_f, fcntl.LOCK_UN)

    def bump_budget_exempt_runs(self, spec_name: str) -> int:
        """死亡豁免侧车计数原子递增（``_budget_exempt_runs``）。

        Returns: 递增后的豁免次数。
        """
        return self._bump_counter(spec_name, BUDGET_EXEMPT_RUNS_FIELD, 1)

    def bump_infra_failure_count(self, spec_name: str) -> int:
        """infra 失败累计观测值原子递增（``_infra_failure_count``）。

        生命周期累计、不归零（与 _budget_exempt_runs 同范式）；仅由
        infra 判定记账路径调用。返回递增后的累计值。
        """
        return self._bump_counter(spec_name, INFRA_FAILURE_COUNT_FIELD, 1)

    def bump_verify_infra_rounds(self, spec_name: str, delta: int = 1) -> int:
        """infra 失败轮次原子增减（``_verify_infra_rounds``）。

        纯观测计数（不参与 MAX_VERIFY_FAIL_ROUNDS 冻结判定）；与
        _verify_fail_rounds 同生命周期——验证 PASS 经 update_spec 与
        _verify_fail_rounds 同点清零（唯一归零点）。返回增减后的值。
        """
        return self._bump_counter(spec_name, VERIFY_INFRA_ROUNDS_FIELD, delta)

    def bump_verify_redo_count(self, spec_name: str, delta: int = 1) -> int:
        """重启重验计数原子增减（``_verify_redo_count``）。

        仅由 daemon 重启恢复路径（recover_interrupted 的 testing→implemented
        分支）递增调用；运行期中断/重试不经过此路径，计数天然只反映「重启恢复
        重验」次数（fix-daemon-lifecycle-races D3）。

        Returns: 增减后的累计值（跨重启持久化）。
        """
        return self._bump_counter(spec_name, VERIFY_REDO_COUNT_FIELD, delta)

    def update_spec(self, spec_name: str, updates: dict,
                    *, applied_out: Optional[dict] = None) -> bool:
        """Update a single SPEC's fields atomically. Returns True if updated.

        原子性（fix-state-atomicity-and-selfheal-restart D1）：读 STATE.md →
        内存改目标字段 → 持久化的三段全部收进 ``.STATE.md.lock`` 的 flock 内。
        并发的 update_spec（daemon 多 worker 线程 + dashboard 独立进程）不再
        各持陈旧快照互相覆盖——任一已提交写入的字段改动 MUST NOT 丢失。
        冻结剥离判定同样在锁内基于**最新**条目进行（锁外快照会把「刚被冻结」
        误判为「未冻结」而漏剥离自动 status 写）。

        单条目应用逻辑提取为 ``_apply_updates_entry``（锁内 mutate 复用体），
        留痕日志提取为 ``_log_update_applied``——原子转换路径
        （``_transition_atomic``）共用同一份写语义，避免冻结剥离/取消保持
        解锁规则出现第二份实现。

        ``applied_out``（code-review b7a0f425b6bb）：可选收集 dict，写成功后
        回填本次实际生效字段（含 ``_stripped`` 剥离留痕，语义同
        ``_apply_updates_entry.applied``）。冻结剥离时本函数仍返回 True
        （写本身成功），调用方须自行核对 ``_stripped`` 才能判知 status 写
        未生效——只消费 bool 返回值的既有调用方不受影响。
        """
        applied: dict = {}

        def _mutate(specs):
            found = self._apply_updates_entry(specs, spec_name, updates, applied)
            return found, found

        if not self._mutate_locked(_mutate):
            self.logger.warning("state_machine", f"SPEC not found: {spec_name}")
            return False
        self._log_update_applied(spec_name, applied)
        if applied_out is not None:
            applied_out.clear()
            applied_out.update(applied)
        return True

    def _apply_updates_entry(self, specs: Dict[str, dict], spec_name: str,
                             updates: dict, applied: dict) -> bool:
        """update_spec 的锁内单条目应用逻辑（原子转换路径复用同一份写语义）。

        语义（自 update_spec._mutate 原样提取，MUST NOT 在别处重写第二份）：
        - spec 不存在 → False；
        - 人工冻结保护（fix-restart-dual-dispatch S4）：frozen spec 的自动
          status 改写一律剥离——dispatch Retry/恢复路径实测会把人工冻结覆盖
          回 ready。更新自带 frozen 键视为冻结/解冻操作本身，原样放行；
        - 取消保持解锁（fix-cancel-holdstate-recovery D4）：显式携带 status 的
          更新（admin 处置复位、面板重派、unfreeze 等复位路径）即人工裁决，
          顺带清除取消保持标记；仅 error 等隐式 updates 不清；
        - implementing→ready WIP 标志清除（code-fix 6a2031777cc3）：状态由
          implementing 落 ready 时顺带清 ``_wip_gate_deferred``——admin 处置
          复位与人工 ready 重派不得携带陈旧等待标志进入下一轮派发（显式
          携带该标志的更新视为知情写，原样放行）；
        - 条目 ``updated`` 时间戳随每次成功应用刷新。

        ``applied`` 收集本次实际生效的字段（含 ``_stripped`` 剥离留痕），
        供 ``_log_update_applied`` 在锁外输出留痕日志。

        Returns: True 表示条目存在且已应用（调用方据其决定是否落盘）。
        """
        if spec_name not in specs:
            return False
        entry = specs[spec_name]
        local = dict(updates)
        if entry.get(FROZEN_FIELD) and FROZEN_FIELD not in local and "status" in local:
            applied["_stripped"] = local.pop("status")
        if "status" in local:
            local["_cancelled_hold"] = False
            # implementing→ready 中央清除（code-fix 6a2031777cc3）：admin 处置
            # 复位（orphaned_state 降级过期）与人工 ready 重派都经本单点落
            # ready——稳态下不再经过 boot 复位写点，陈旧 _wip_gate_deferred
            # 会随重派带进下一轮 implementing，周期消费者会在在飞实现 run
            # 收尾前 merge-only 合回半成品分支（正是 boot 复位写点要防的
            # 竞态），故随迁移顺带清标志（内存写，失败不存在、不阻断迁移）。
            if (
                local["status"] == SpecStatus.READY
                and entry.get("status") == SpecStatus.IMPLEMENTING
                and "_wip_gate_deferred" not in local
            ):
                # _merge_retry_count/_merge_retry_first_at 与非 wip 的
                # spec_dir_inflight 顺延链共用一套计数（混账已知、接受），
                # 此时刻无法区分归属，只清 wip 标志本身。
                local["_wip_gate_deferred"] = False
        specs[spec_name].update(local)
        specs[spec_name]["updated"] = datetime.now(timezone.utc).isoformat()
        applied.update(local)
        return True

    def _log_update_applied(self, spec_name: str, applied: dict) -> None:
        """update_spec / 原子转换路径共用的锁外留痕日志（「写入必留痕」）。

        MUST 在原子写成功后调用：锁内日志会让持锁窗口包含 I/O，故留痕在
        落盘之后输出（update_spec 既有约定）。含 frozen 剥离 warning 与
        「Updated SPEC」info（含 spec 名与本次所改字段键，``updated`` /
        ``_stripped`` 内部键不入日志）。
        """
        if "_stripped" in applied:
            self.logger.warning(
                "state_machine",
                f"Frozen SPEC '{spec_name}': status update "
                f"'{applied['_stripped']}' stripped — manual freeze intact, "
                f"unfreeze via unfreeze_spec() to resume",
            )
        self.logger.info(
            "state_machine",
            f"Updated SPEC '{spec_name}'",
            {
                "updates": {
                    k: v for k, v in applied.items() if k not in ("updated", "_stripped")
                }
            },
        )

    def freeze_spec(self, spec_name: str, reason: str = "") -> bool:
        """人工冻结 spec（fix-restart-dual-dispatch S4 的统一入口）。

        写入 blocked + 结构化 frozen 标记 + 规范前缀 error。error 保留「用户指令」
        子串，与既有文本契约豁免（admin_monitor）双保险兼容。冻结期间自动链路
        （重派/恢复/Retry/admin 唤起）全部失效，唯一出路是 unfreeze_spec。

        add-freeze-stop-inflight-agents 2.2（保真锚点）：冻结时若该 spec 当前
        status 在 INTERRUPTED_STATES（implementing/testing/reviewing），把
        branch / implementer_run / reviewer_run 现值一并写入同一次锁内原子写
        ——MUST NOT 因冻结清空这些锚点，否则在飞 attempt 被冻结终止后（轮询环
        冻结检查）解冻续做判定（_frozen_hold + 保留分支）因锚点已失只能降级为
        从零重派。当前 freeze_spec 只写 {status, frozen, error}、本身不清锚点，
        但必须显式带值透传：一旦将来有清理路径把 branch 置空，mark_frozen_hold
        （MUST NOT 清锚点）也会拿着空锚点、续做判定必然降级。
        """
        error = f"{FREEZE_ERROR_PREFIX}{reason}" if reason else FREEZE_ERROR_PREFIX.rstrip("：:")
        updates: dict = {
            "status": SpecStatus.BLOCKED,
            FROZEN_FIELD: True,
            "error": error,
        }
        # 锚点快照在 .STATE.md.lock 锁内基于最新条目取值（code-fix
        # d266d19c4860）：锁外 read_one 快照与落盘之间存在竞态窗口——其他写者
        # （如恢复清空重建路径）若已把锚点清为 None，锁外旧值会在本写中复活，
        # 解冻续做判定据此拿到陈旧锚点。收进 _mutate_locked 的锁内回调后与
        # update_spec 的原子读改写范式对齐；单条目写语义（冻结剥离/取消保持/
        # updated 刷新）复用 _apply_updates_entry，无第二份实现。
        applied: dict = {}

        def _mutate(specs):
            entry = specs.get(spec_name) or {}
            if entry.get("status") in INTERRUPTED_STATES:
                for _anchor in ("branch", "implementer_run", "reviewer_run"):
                    if entry.get(_anchor) is not None:
                        updates[_anchor] = entry.get(_anchor)
            found = self._apply_updates_entry(specs, spec_name, updates, applied)
            return found, found

        if not self._mutate_locked(_mutate):
            self.logger.warning("state_machine", f"SPEC not found: {spec_name}")
            return False
        self._log_update_applied(spec_name, applied)
        return True

    def freeze_for_human(
        self,
        spec_name: str,
        *,
        error: str,
        signal_type: str,
        severity: str,
        description: str,
        evidence: str,
        recommended_action: str,
        alert_callback=None,
        extra_updates: Optional[dict] = None,
    ) -> bool:
        """「冻结转人工」单一入口（fix-blocked-freeze-classification D2）。

        blocked 二分类契约的机械化写入口：一次调用完成 ``status=blocked`` +
        ``frozen=True`` + 各站点保留的 error 文案（显式传入，不强制统一前缀，
        评审路径须内嵌「原状态 <冻结前状态>」子串供 parse_orig_status 解析
        解冻目标），**并且**经注入的告警回调发送人工升级告警——frozen 与 alert
        成对、不可分离，从结构上消除「打了 frozen 标记但无人被通知」的静默冻结
        （历史事故：:849 重启重验超限曾只有 frozen 无告警）。

        alert 发送者以回调注入（最小依赖倒置）：StateMachine 不持有 pm_engine
        引用，发送由调用方传入可调用（生产传 ``pm_engine._send_human_escalation_alert``；
        None 仅允许单测场景——静默冻结时必须记 ERROR 审计日志，MUST NOT 无痕）。

        Args:
            error: frozen spec 的 error 文案（各站点既有文案原样传入；评审路径
                须内嵌「原状态 <冻结前状态>」子串，供 parse_orig_status 解析
                解冻目标——评审 frozen spec 解冻后恢复 reviewing → daemon 自动
                重派评审）。
            extra_updates: 并入同一原子写的额外字段（如评审收口的 reviewer_run
                /_review_attempts 清理），MUST NOT 携带 error 键（会覆盖冻结 error）。
            alert_callback: 人工升级告警发送回调（接受 spec_name/signal_type/
                severity/description/evidence/recommended_action 关键字参数）。
                生产接线点：recover_interrupted 的 human_alert_callback、
                spec_review/budget/spec_integrity 的 pm_engine
                ._send_human_escalation_alert。None 仅允许单测场景。

        Returns: True 表示状态已更新。
        """
        updates: dict = {
            "status": SpecStatus.BLOCKED,
            FROZEN_FIELD: True,
            "error": error,
        }
        if extra_updates:
            # 防误用：extra_updates 不得覆盖冻结 error（评审收口若传入 error
            # 键会用非冻结前缀文案覆盖冻结 error → parse_orig_status 失效）
            safe_extra = {k: v for k, v in extra_updates.items() if k != "error"}
            updates.update(safe_extra)
        ok = self.update_spec(spec_name, updates)
        if alert_callback is None:
            # 无告警回调=静默冻结：必须有审计痕迹（None 仅允许单测；生产
            # 通过 fenixd._build_human_alert_callback / pm_engine
            # ._send_human_escalation_alert 注入非 None 回调，缺省
            # 回调使 helper 退回静默冻结违反「冻结必告警」不变式）
            self.logger.error(
                "state_machine",
                f"FREEZE WITHOUT ALERT: '{spec_name}' frozen for human "
                f"(signal_type={signal_type}) but no alert_callback supplied — "
                f"静默冻结（仅单测允许，生产 MUST 提供非 None 回调）",
            )
            return ok
        try:
            alert_callback(
                spec_name=spec_name,
                signal_type=signal_type,
                severity=severity,
                description=description,
                evidence=evidence,
                recommended_action=recommended_action,
            )
        except Exception as e:
            # 告警失败不得回滚冻结本身（冻结状态已落盘）——记录审计后
            # 静默继续（与既有人工升级告警写入的 try/except 容错一致）
            self.logger.warning(
                "state_machine",
                f"冻结人工升级告警发送失败 '{spec_name}'（signal_type="
                f"{signal_type}，非阻塞）: {e}",
            )
        return ok

    def mark_frozen_hold(self, spec_name: str, error: str = "") -> bool:
        """冻结终止的独立保持标记写入（add-freeze-stop-inflight-agents D3）。

        调用方：dispatch 侧的 frozen_terminated=True 结果收口（queue /
        fast_track / repair_lane / verification，与既有 cancelled 分支并列）。

        单次原子写 ``{_frozen_hold: True, _cancelled_hold: False, error}``：
        - MUST NOT 改 status（保持 blocked——冻结期间由 frozen 字段挡住一切派发）；
        - MUST NOT 清 branch / implementer_run（解冻续做判定依据）；
        - MUST 清 _cancelled_hold（与取消保持**互不读写**：冻结终止路径先清
          后者，避免解冻后恢复链路按取消保持跳过）。
        形态约束（tests/test_cancel_holdstate_recovery.py 静态守卫）：MUST 写
        ``_frozen_hold: True`` 并**清** ``_cancelled_hold`` 为 False，而非两字段
        同写 True——全库取消保持写点字面命中恰为 6 处（守卫要求），
        新增该字面即红灯。
        """
        return self.update_spec(
            spec_name,
            {
                FROZEN_HOLD_FIELD: True,
                "_cancelled_hold": False,
                "error": error or (FROZEN_HOLD_FIELD + " flagged"),
            },
        )

    def unfreeze_spec(self, spec_name: str, status: str = None,
                      project_root=None, worktree_manager=None) -> bool:
        """解除人工冻结。status 给定时同时恢复到该状态（绕过冻结保护）。

        解冻即人工裁决完成——重启重验计数一并清零（fix-daemon-lifecycle-races
        D3），使人工放行后的重验预算重新从零起算。error 与 frozen_until
        （定时解冻目标，add-spec-scheduling-controls D3）随解冻一并清除，
        保证恢复后 spec 回到「无 error、无冻结残留」的干净可调度态。

        add-freeze-stop-inflight-agents D4/2.5（续做接线）：若该 spec 带
        ``_frozen_hold: True``（曾被冻结终止、现场已保全）且 project_root /
        worktree_manager 均传入，走 ``_resolve_preserved_branch`` 共享判定
        （与 _recovery_preserve_spec 同源、零漂移）：
        - 判定通过（分支在册 + 相对 main 有未合并提交 + 载体可用）→ 同一
          原子写保留 branch/implementer_run、置 ``_recovery_resume: True``、
          清 ``_frozen_hold``，status 用解析出的原状态——dispatch 拾取后在
          保留分支上 resume 续做，而非从零新建分支。
        - 判定不通过（无 branch / 零提交 / 载体不可用）→ 清 ``_frozen_hold``、
          不置 ``_recovery_resume``、走普通重派，并 WARNING 留痕降级原因。
        ``_frozen_hold`` 缺失（从未被冻结终止）时行为与改动前逐位一致。
        """
        entry = self.read_one(spec_name) or {}
        frozen_hold = bool(entry.get(FROZEN_HOLD_FIELD))
        # 续做解析先行：判定通过时覆盖 status/branch/implementer_run 的
        # 解冻目标（同一原子写），未命中时保持普通解冻清理集。
        resume_status = None  # 仅续做判定通过时设为解析出的目标状态
        resume_branch = None
        resume_impl_run = None
        # fix-relocation-writeback-layer D6（Task 7.1）：保留判定 MUST NOT 以
        # 「调用方是否显式传上下文」为前置条件。实测（2026-09-22，add-code-
        # review-auto-fix）：裸 ``unfreeze_spec(name, status=…)``（人工操作/
        # 定时解冻/scheduled）会整段跳过续做解析，``_frozen_hold`` 随解冻被清 →
        # 下一轮 ``find_branches_by_spec`` 不再枚举保留分支 → dispatch 落
        # 「新轮次派发清除旧锚点」从 main 新建分支（6 提交/48 勾选的实现被弃）。
        # 未显式传入时自解析：STATE.md 位于 ``<project_root>/.fenix/STATE.md``，
        # worktree_manager 以 Dashboard 解冻（admin_actions）同参形态自构造。
        # 判据分支不可达（自解析失败）才降级，且 MUST 落 WARNING——绝无静默。
        if frozen_hold and (project_root is None or worktree_manager is None):
            _auto_root = None
            try:
                _auto_root = self.state_path.parent.parent
                if project_root is None:
                    project_root = _auto_root
                if worktree_manager is None:
                    from core.worktree_manager import WorktreeManager

                    worktree_manager = WorktreeManager(
                        base_dir=_auto_root / ".fenix",
                        project_root=_auto_root,
                        logger=None,
                    )
            except Exception as _e:
                self.logger.warning(
                    "state_machine",
                    f"Unfreeze resume degrade: spec '{spec_name}' 带 _frozen_hold "
                    f"但续做上下文自解析失败（project_root={_auto_root}: {_e}）"
                    f"——保留判定不可达，清标记走普通重派（从零）",
                )
        if frozen_hold and project_root is not None and worktree_manager is not None:
            _resolved_branch, _wt = self._resolve_preserved_branch(
                spec_name, entry, project_root, worktree_manager,
                context="Unfreeze resume",
            )
            if _wt is not None:
                resume_status = _resolved_branch and (
                    status or SpecStatus.READY)
                resume_branch = _resolved_branch
                resume_impl_run = entry.get("implementer_run")
                self.logger.warning(
                    "state_machine",
                    f"Unfreeze resume: spec '{spec_name}' 冻结终止现场已保全，"
                    f"在保留分支 '{resume_branch}' 上续做（_recovery_resume），"
                    f"worktree={_wt}",
                )
            elif _resolved_branch is not None:
                # Task 7.2：分支命名空间枚举命中但载体三态暂不可用（worktree
                # 被实现 run 占用等）——MUST NOT 因载体缺失整体丢弃分支锚点：
                # 仍记录续做分支 + _recovery_resume，dispatch 拾取后按既有
                # resolve_resume_site 三态自行重建/重试载体（载体是续做的执行
                # 细节，锚点丢失才是不可逆损失——worktree 清理后锚点不再被
                # 枚举，实现成果被弃从零重做）。
                resume_status = status or SpecStatus.READY
                resume_branch = _resolved_branch
                resume_impl_run = entry.get("implementer_run")
                self.logger.warning(
                    "state_machine",
                    f"Unfreeze resume: spec '{spec_name}' 保留分支 "
                    f"'{_resolved_branch}' 命中但载体暂不可用——仍记录续做分支"
                    f"锚点（branch + _recovery_resume），由 dispatch 续做路径"
                    f"按 resolve_resume_site 三态重建载体",
                )
            else:
                self.logger.warning(
                    "state_machine",
                    f"Unfreeze resume degrade: spec '{spec_name}' 带 _frozen_hold "
                    f"但保留判定未通过（分支缺失/零提交/载体不可用）——清标记走 "
                    f"普通重派（从零）",
                )
        elif frozen_hold:
            # Task 7.1：自解析后判据分支仍不可达（project_root/worktree_manager
            # 均不可得）——显式告警降级，杜绝静默丢弃保留分支锚点。
            self.logger.warning(
                "state_machine",
                f"Unfreeze resume degrade: spec '{spec_name}' 带 _frozen_hold "
                f"但续做上下文不可得（project_root/worktree_manager 均不可用）"
                f"——保留判定不可达，清标记走普通重派（从零）",
            )
        updates: dict = {FROZEN_FIELD: False}
        if status is not None and resume_status is None and not (frozen_hold and resume_branch):
            updates["status"] = status
        if resume_branch is not None:
            updates["status"] = resume_status
            updates["branch"] = resume_branch
            updates["implementer_run"] = resume_impl_run
            # dispatch 层据此识别「解冻续做」路径：在保留分支的 worktree 内
            # resume，而非从零新建分支（与 _recovery_preserve_spec 同源输出）。
            updates["_recovery_resume"] = True
        updates[FROZEN_HOLD_FIELD] = False
        # 计数清零并入同一原子写，避免解冻后残留计数立即再次触发冻结
        updates[VERIFY_REDO_COUNT_FIELD] = 0
        # add-verdict-credibility-gate / design D6：inconclusive 循环计数同样
        # 随人工解冻清零——人工处置后 blocked-env 轮次从 1 重新计数（与
        # _verify_redo_count 同语义，B6「恢复尊重暂停标记」闭环的人工侧）。
        updates["_inconclusive_attempts"] = 0
        # add-verify-parallel-backoff / design D2：降档并行度与
        # _inconclusive_attempts 完全同生命周期——人工解冻同轮清 override，
        # 重验从配置并行度重新开始，不留降档残留。
        updates["_verify_parallel_override"] = None
        # add-blocked-reverify-lane D3：env 阻塞轮次随人工解冻清零——人工处置
        # 后 env 轮次从 1 重新计数（与 _verify_redo_count/_inconclusive_attempts
        # 人工解冻清零同款，同一原子写）。其余中间转换（admin 处置复位、daemon
        # 恢复、fix 链）一律不清零，保证「第 2 次阻塞即冻结转人工」可达。
        updates[ENV_BLOCK_ROUNDS_FIELD] = 0
        # fix-redispatch-loop-governance D3.5：同因重派熔断计数随人工解冻清零——
        # 人工处置后同因重试从零起算（与 VERIFY_REDO_COUNT_FIELD /
        # _inconclusive_attempts / ENV_BLOCK_ROUNDS_FIELD 同款「同一原子写清零」）。
        updates["_redispatch_same_cause_streak"] = 0
        updates["_redispatch_cause_fp"] = None
        # 全场景同因失败哨计数随人工解冻清零（与上方各验证计数同一原子写）：
        # admin 按推荐动作「拨回 implemented 重验」/解冻人工修复后，同因失败
        # 观察窗从 1 重新起算；否则解冻后首轮同因失败 attempts 即 ≥4 立即
        # 再次 blocked，「连续 3 轮」承诺落空。
        updates["_uniform_fail_attempts"] = 0
        # fix-recovery-path-blockers D4：场景原地修复预算耗尽轮次随人工解冻
        # 清零——人工解冻是唯一人工裁决出口（对齐 _env_block_rounds 既有语义），
        # 解冻后重新获得「首次耗尽排程重验 → 再次耗尽升级」的完整体验；其余
        # 中间转换（admin 处置复位 / daemon 恢复 / fix 链）一律不清零。
        updates[SCENARIO_REPAIR_EXHAUSTED_FIELD] = 0
        updates["error"] = None
        updates[FROZEN_UNTIL_FIELD] = None
        return self.update_spec(spec_name, updates)

    def add_spec(self, spec_name: str, entry: dict) -> bool:
        """Add a new SPEC entry. Returns False if already exists.

        原子性（D1/D2）：存在性查重与插入在同一把 ``.STATE.md.lock`` 内完成。
        查重与写盘分处锁外时，两个并发 add 会各持「尚无该条目」的快照整体回写，
        后写者把先写者刚注册的 spec 整条抹掉（同源丢失更新）。
        """
        added: dict = {}

        def _mutate(specs):
            if spec_name in specs:
                return False, False
            entry.setdefault("status", SpecStatus.DRAFTED)
            entry.setdefault("priority", 5)
            entry.setdefault("created", datetime.now(timezone.utc).isoformat())
            entry.setdefault("updated", datetime.now(timezone.utc).isoformat())
            entry.setdefault("implementer_run", None)
            entry.setdefault("tester_run", None)
            entry.setdefault("branch", None)
            entry.setdefault("error", None)
            entry.setdefault("depends_on", None)
            entry.setdefault("reviewer_run", None)
            entry.setdefault("_review_attempts", 0)

            specs[spec_name] = entry
            added["status"] = entry["status"]
            return True, True

        if not self._mutate_locked(_mutate):
            self.logger.warning("state_machine", f"SPEC already exists: {spec_name}")
            return False
        self.logger.info(
            "state_machine", f"Added SPEC '{spec_name}'", {"status": added["status"]}
        )
        return True

    def remove_spec(self, spec_name: str) -> bool:
        """Remove a SPEC entry atomically. Returns True if removed, False if absent.

        唯一不变式：读取-剔除-写回在 ``.STATE.md.lock`` 的 flock 内完成，故并发
        写者 MUST NOT 以陈旧快照整体回写而复活该条目（锁外快照的旧实现做不到
        这一点——design D2 已指出原 docstring 的该声明与实现不符）。

        **注意**：本方法只保证 STATE.md 自身的一致性。删除与目录归档
        （spec/changes → spec/archive）是两次独立系统操作，二者的一致性由调用方
        负责（add-spec-priority-and-delete-api 的既有契约）。
        """
        def _mutate(specs):
            if spec_name not in specs:
                return False, False
            specs.pop(spec_name)
            return True, True

        if not self._mutate_locked(_mutate):
            self.logger.warning(
                "state_machine", f"Cannot remove nonexistent SPEC: {spec_name}"
            )
            return False
        self.logger.info("state_machine", f"Removed SPEC '{spec_name}'")
        return True

    # ── State Transitions ──────────────────────────────────────────

    def _transition_atomic(self, spec_name: str, new_status: str,
                           table: Dict[str, List[str]], outcome: dict) -> bool:
        """transition / transition_gate 共用的锁内原子转换路径。

        校验与落盘收进同一把 ``.STATE.md.lock`` 的 flock：mutate 回调内基于
        **最新** entry 重查 old_status、重跑幂等短路与 ``table`` 判定
        （``VALID_TRANSITIONS`` / ``GATE_TRANSITIONS`` 由调用方传入——门禁
        规则单点定义于模块常量，此处只做查表，不复制第二份规则），校验失败
        不改动 entry、不落盘。旧实现锁外 ``read_one`` 快照校验 + ``update_spec``
        锁内盲写三段非原子：并发写者（daemon 多 worker 线程 + dashboard 独立
        进程）在快照与落盘之间先行推进状态后，本路径仍按陈旧 old_status 通过
        校验并覆盖写（如 verified→testing 无门禁回退），该丢失转换窗口由此消除
        （与 ``_mutate_locked`` 修复的丢失更新窗口同型）。

        ``outcome`` 把锁内判定结果带出给调用方锁外记日志（持锁窗口不含 I/O，
        同 ``_log_update_applied`` 的既有约定）：
        - ``missing``：spec 不存在；
        - ``old_status``：锁内读到的当前状态（供日志文案）；
        - ``idempotent``：old==new 幂等短路（返回 True 且不落盘）；
        - ``invalid``：``table`` 判定拒绝（返回 False 且不落盘）；
        - ``applied``：成功应用后的字段快照（供 ``_log_update_applied`` 留痕）；
        - ``stripped``：frozen spec 的 status 写被剥离（code-review c809d1296efc，
          值为被剥离的 status）——状态实际未变，transition/transition_gate
          据此返回 False，调用方不再把假成功当真转换继续推进。

        Returns: True 表示幂等短路或成功落盘；False 表示不存在、非法转换或
        冻结剥离（status 未实际生效）。
        """
        def _mutate(specs):
            entry = specs.get(spec_name)
            if entry is None:
                outcome["missing"] = True
                return False, False
            old_status = entry.get("status", SpecStatus.DRAFTED)
            outcome["old_status"] = old_status
            # 幂等自迁移短路（fix-daemon-lifecycle-races D4）：锁内基于最新
            # 状态判定，并发写者先行推进后此处看到的是推进后的真实状态。
            if new_status == old_status:
                outcome["idempotent"] = True
                return True, False
            if new_status not in table.get(old_status, []):
                outcome["invalid"] = True
                return False, False
            applied: dict = {}
            applied_ok = self._apply_updates_entry(
                specs, spec_name, {"status": new_status}, applied
            )
            if "_stripped" in applied:
                # 冻结剥离带出（code-review c809d1296efc）：_apply_updates_entry
                # 对 frozen spec 剥离 status 后仍返回 True（update_spec 路径要
                # 靠它落盘 error 等其余字段），但本路径 updates 仅含 status，
                # 剥离即零字段生效——状态实际未变。outcome 带出 stripped 供
                # transition/transition_gate 返回 False，调用方不再把假成功
                # 当真转换继续推进（_stripped WARNING 之外的可编程判别通道）。
                outcome["stripped"] = applied["_stripped"]
                # 零写入（code-review 45dc313473ef）：本路径 updates 仅含 status，
                # 剥离后唯一「生效」副作用只剩 _apply_updates_entry 的 updated
                # 时间戳刷新——返回 (True, True) 会为这次语义上的未转换做一次
                # 全量落盘（EventBus 校验和变化 → 空 diff 噪声），与 docstring
                # 「冻结剥离不落盘」口径不符。改返回 (False, False)：状态未变
                # 不落盘。transition/transition_gate 在 stripped 分支先行返回
                # False、不消费 applied 快照，调用方语义不变。
                return False, False
            if applied_ok:
                outcome["applied"] = applied
            return applied_ok, applied_ok

        return self._mutate_locked(_mutate)

    def transition(self, spec_name: str, new_status: str,
                   *, trigger_run_id: str | None = None,
                   agent_type: str | None = None,
                   channel: str = "auto") -> bool:
        """Transition a SPEC to a new status. Validates the transition is legal.

        fix-observability-gaps 2.1：结构化 context 以**可选关键字参数**扩展
        （既有调用点零改动）：trigger_run_id（触发转换的 run）、agent_type
        （触发方 agent 类型）、channel（来源：auto=自动调度 /
        manual=人工操作 / recovery=恢复/解冻）。仅真实状态变化的转换（非
        幂等短路、非非法拒绝）携带 context；幂等短路（old==new）不改变状态，
        按 spec「每次状态转换 MUST 携带结构化 context」口径不视为状态转换，
        不补 context（2.1a 显式排除，见日志行）。

        原子性：幂等短路 / VALID_TRANSITIONS 校验与落盘收进同一把文件锁、
        基于锁内最新 entry 判定（``_transition_atomic``），并发下不再有
        「按陈旧快照校验通过后覆盖写」的无门禁回退窗口。
        """
        outcome: dict = {}
        result = self._transition_atomic(spec_name, new_status, VALID_TRANSITIONS, outcome)
        if outcome.get("missing"):
            self.logger.warning("state_machine", f"Cannot transition nonexistent SPEC: {spec_name}")
            return False

        old_status = outcome.get("old_status")

        # 幂等自迁移短路（fix-daemon-lifecycle-races D4）：new_status == old_status
        # 视为幂等自迁移，INFO 降级直接返回 True，不进入 VALID_TRANSITIONS 拒绝
        # 分支。历史 ERROR 噪声（done→pushed 双路径并发必触发的 pushed→pushed
        # 假告警）由此消噪；真实非法迁移（如 implemented→verified）仍记 ERROR。
        # 依赖返回 False 阻断重复副作用的调用点须改为前置状态判断或接受幂等覆盖：
        # 全库核查见 engine.py:332（done→done 时 total_duration 重算覆盖为同值，
        # 幂等无害）与 dispatch.py:480-503（已有 cur_status != "implementing"
        # 前置判断的同型防护）。判定在锁内基于最新状态完成，此处只负责留痕。
        if outcome.get("idempotent"):
            self.logger.info(
                "state_machine",
                f"Idempotent transition: {spec_name} {old_status} → {new_status} "
                f"(already in state, skipped)",
            )
            return True

        # Validate transition（判定已在锁内完成，此处留痕）
        if outcome.get("invalid"):
            self.logger.error(
                "state_machine",
                f"Invalid transition: {spec_name} {old_status} → {new_status}",
            )
            return False

        # 冻结剥离假成功消歧（code-review c809d1296efc）：frozen spec 的 status
        # 写在锁内被剥离、状态实际未变，此前照常走 result=True 分支输出
        # 「Transition」并返回 True，依赖返回值判断推进结果的自动链路会误以为
        # 状态已到位。改为显式 warning + 返回 False——冻结期间自动链路失效
        # 本就是冻结语义（唯一出路 unfreeze_spec），False 让调用方诚实感知。
        if outcome.get("stripped") is not None:
            self.logger.warning(
                "state_machine",
                f"Frozen SPEC '{spec_name}': transition {old_status} → {new_status} "
                f"stripped — manual freeze intact, status unchanged",
            )
            return False

        if result:
            self.logger.info(
                "state_machine",
                f"Transition: {spec_name} {old_status} → {new_status}",
                # fix-observability-gaps 2.1：结构化 context（trigger_run_id /
                # agent_type / channel），供 dashboard 时间轴读侧优先消费；
                # 断路器在落盘成功后返回 True，日志先行
                {
                    "trigger_run_id": trigger_run_id,
                    "agent_type": agent_type,
                    "channel": channel,
                },
            )
            self._log_update_applied(spec_name, outcome.get("applied", {}))
        return result

    def is_valid_transition(self, from_status: str, to_status: str) -> bool:
        """Check if a transition is legal."""
        return to_status in VALID_TRANSITIONS.get(from_status, [])

    def transition_gate(self, spec_name: str, new_status: str,
                        *, trigger_run_id: str | None = None,
                        agent_type: str | None = None,
                        channel: str = "auto") -> bool:
        """门禁自动路径专用转换（verifier-judgment-integrity D7 逃生门）。

        仅允许 GATE_TRANSITIONS 中声明的转换（当前：VERIFIED→TESTING），
        用于 _on_spec_verified 门禁拦截后的自动回退。人工路径（直接调
        transition）受 VALID_TRANSITIONS 约束，VERIFIED→TESTING 仍被拒，
        不得绕过。返回 False 表示非门禁允许的转换或 spec 不存在。

        fix-observability-gaps 2.1：与 transition() 相同——可选关键字参数
        trigger_run_id / agent_type / channel，日志前缀 `Gate transition: `
        同样携带结构化 context（该前缀不被时间轴正则命中，context 是
        时间轴重建该路径的唯一通道，必须带）。

        原子性：幂等短路 / GATE_TRANSITIONS 校验与落盘收进同一把文件锁、
        基于锁内最新 entry 判定（``_transition_atomic``，与 transition()
        共用同一原子机制，仅查表不同），并发下不再有「按陈旧快照校验通过
        后覆盖写」的窗口。
        """
        outcome: dict = {}
        result = self._transition_atomic(spec_name, new_status, GATE_TRANSITIONS, outcome)
        if outcome.get("missing"):
            self.logger.warning(
                "state_machine", f"Cannot gate-transition nonexistent SPEC: {spec_name}"
            )
            return False

        old_status = outcome.get("old_status")

        # 幂等自迁移短路（fix-daemon-lifecycle-races D4）：同 transition() 语义，
        # old==new 视为幂等，INFO 直接返回 True，不进 GATE_TRANSITIONS 拒绝分支。
        # 判定在锁内基于最新状态完成，此处只负责留痕。
        if outcome.get("idempotent"):
            self.logger.info(
                "state_machine",
                f"Idempotent gate transition: {spec_name} {old_status} → {new_status} "
                f"(already in state, skipped)",
            )
            return True

        if outcome.get("invalid"):
            self.logger.error(
                "state_machine",
                f"Invalid gate transition: {spec_name} {old_status} → {new_status}",
            )
            return False

        # 冻结剥离假成功消歧（code-review c809d1296efc）：同 transition()——
        # frozen spec 的 status 写被剥离、状态实际未变，返回 False 而非假成功。
        if outcome.get("stripped") is not None:
            self.logger.warning(
                "state_machine",
                f"Frozen SPEC '{spec_name}': gate transition {old_status} → {new_status} "
                f"stripped — manual freeze intact, status unchanged",
            )
            return False

        if result:
            self.logger.info(
                "state_machine",
                f"Gate transition: {spec_name} {old_status} → {new_status}",
                {
                    "trigger_run_id": trigger_run_id,
                    "agent_type": agent_type,
                    "channel": channel,
                },
            )
            self._log_update_applied(spec_name, outcome.get("applied", {}))
        return result

    # ── Query ──────────────────────────────────────────────────────

    def get_by_status(self, status: str) -> List[Tuple[str, dict]]:
        """Get all SPECs with the given status, sorted by priority."""
        all_specs = self.read_all()
        matching = [
            (name, entry) for name, entry in all_specs.items() if entry.get("status") == status
        ]
        return self._sort_by_priority(matching)

    def get_ready_specs(self) -> List[Tuple[str, dict]]:
        """Get all ready SPECs sorted by priority."""
        return self.get_by_status(SpecStatus.READY)

    def get_next_ready(self) -> Optional[Tuple[str, dict]]:
        """Get the highest-priority ready SPEC."""
        ready = self.get_ready_specs()
        return ready[0] if ready else None

    def get_pending_verification(self) -> List[Tuple[str, dict]]:
        """Get all SPECs awaiting verification, sorted by priority."""
        return self.get_by_status(SpecStatus.IMPLEMENTED)

    def _sort_by_priority(self, specs: List[Tuple[str, dict]]) -> List[Tuple[str, dict]]:
        """Sort by priority (lower = higher priority), then by created time."""
        return sorted(
            specs,
            key=lambda item: (
                item[1].get("priority", 999),
                item[1].get("created", "z"),
            ),
        )

    # ── Recovery ───────────────────────────────────────────────────

    def recover_interrupted(
        self,
        project_root=None,
        worktree_manager=None,
        verify_redo_budget: int = DEFAULT_VERIFY_REDO_BUDGET,
        remerge_callback=None,
        human_alert_callback=None,
    ) -> List[str]:
        """
        On daemon restart, revert any SPECs stuck in interrupted states.
        Uses update_spec directly (bypasses transition validation for recovery).
        Returns list of recovered SPEC names.

        恢复目标按中断态区分（2026-09-04 help-center 误派实证）：
        - implementing（实现中断）→ ready 重派 implementer。interrupt-recovery-
          preserve（D4）改判定：分支存在且相对 main 有未合并提交 → 保留
          branch/implementer_run + ``_recovery_resume`` 标记，按 resume 续做
          （dispatch 层在保留分支上续做而非从零重派）；仅零提交/分支缺失才走
          现行清空路径（逐字节兼容）。project_root/worktree_manager 缺省时行为
          与旧版完全一致（脚本/测试场景零变化）。
        - implementing + ``_repair_awaiting_remerge``（fix-recovery-branch-anchor
          D3/D4）：实现分支已含 main 的合并与冲突解决、仅剩重新合并进主树 →
          直接 re-merge-back 完成合并（不经由 event_bus 排队，避免 ready 窗口
          被 full_scan 误派 implementer）；成功推进 implemented；失败清除标记
          后回落既有保留续做路径。恢复期主树无其他在飞 run（fenixd 调用点
          在 cleanup_stale_worktrees 与 full_scan 之前），是最干净的执行时机。
        - testing（验证中断）→ implemented 重派 verifier——实现已合并/落分支，
          重置 ready 会误派 implementer 从头实现已合并代码并劫持 branch 字段
          （pushed 记录被写成 rogue 分支）；配合场景冻结复用，重验代价极小。
          fix-daemon-lifecycle-races（D3）：恢复重验递增 ``_verify_redo_count``
          并持久化，累计达 ``verify_redo_budget`` 阈值即经 freeze_for_human
          「冻结 + 告警」成对入口（fix-blocked-freeze-classification D4）转为
          blocked 等待人工裁决——修复此前「打了 frozen 却不告警」的静默冻结
          缺陷；本启动不再派发 verifier——毒 spec 无法借反复重启无限重验。
          signal_type=verify_redo_exhausted，severity=major，逐 SPEC 触发
          不聚合丢失。

        Args:
            project_root: 项目根（interrupt-recovery-preserve 保留判定用）。
            worktree_manager: worktree 三态单源查询器（保留续做用）。
            verify_redo_budget: 重启重验预算阈值（agents.verify_redo_budget
                配置值，缺省 DEFAULT_VERIFY_REDO_BUDGET=3）。
            remerge_callback: 恢复期 re-merge-back 成功后的收口回调
                （``callable(spec_name) -> None``），由 fenixd 注入 PMEngine
                侧副作用实现（_clear_dispatch_conflict/_sync_task_progress/
                _reconcile_impl_budget/consume_legacy 等）。缺省 None 时
                行为与旧版逐字节一致（脚本/测试场景零变化）。
            human_alert_callback: 恢复期冻结人工升级告警回调（fix-blocked-
                freeze-classification D4/1.2 接线）。``callable(
                spec_name, signal_type, severity, description, evidence,
                recommended_action) -> None``，由 fenixd 注入
                PMEngine._send_human_escalation_alert 实现。缺省 None 时
                冻结退回静默——helper 内打审计 ERROR（违反「冻结必告警」不变式，
                仅允许单测；生产接线 MUST 非 None）。
        """
        recovered = []
        for status in INTERRUPTED_STATES:
            specs = self.get_by_status(status)
            for name, entry in specs:
                # ── 取消保持跳过（fix-cancel-holdstate-recovery D3）──
                # 被人工取消的 hold spec（_cancelled_hold=True）是有意等待态：
                # 重启恢复不复位、不重派、不递增重启重验计数——人工「随根因
                # 修复一并重派」的决策不被恢复链路静默覆盖。status/error/run
                # 字段原样保留，唯一出路是显式复位（update_spec 携带 status）。
                if entry.get("_cancelled_hold"):
                    self.logger.info(
                        "state_machine",
                        f"跳过重启恢复：人工取消保持 '{name}'",
                    )
                    continue
                self.logger.warning(
                    "state_machine",
                    f"Recovering interrupted SPEC: {name} (was {status})",
                )
                if status == SpecStatus.TESTING:
                    # 重启恢复重验计数（fix-daemon-lifecycle-races D3）：递增并
                    # 持久化（_bump_counter 文件锁内原子读写）。仅此恢复路径递增
                    # ——运行期中断/重派不经过 recover_interrupted，天然不计数。
                    redo_count = self.bump_verify_redo_count(name, 1)
                    if redo_count >= max(1, int(verify_redo_budget or 0)):
                        # 超限冻结：blocked + frozen + 规范 error 前缀，本次启动
                        # 不再重派 verifier（冻结期间自动链路的 status 改写被
                        # update_spec 剥离），唯一出路是人工 unfreeze_spec。
                        # fix-blocked-freeze-classification D4：改走 freeze_for_human
                        # 「冻结 + 告警」成对入口——恢复路径首次补齐人工升级告警
                        # （逐 SPEC 触发不聚合；signal_type=verify_redo_exhausted），
                        # 反复重启仍无法收敛的毒 spec 必须有人被告知。
                        self.freeze_for_human(
                            name,
                            error=f"{FREEZE_ERROR_PREFIX}重启重验超限，等待人工裁决",
                            signal_type="verify_redo_exhausted",
                            severity="major",
                            description=(
                                f"'{name}' 重启重验计数达预算上限 "
                                f"({redo_count}/{verify_redo_budget})，已冻结"
                                f"等待人工裁决"
                            ),
                            evidence=(
                                f"spec={name}; verify_redo_count={redo_count}; "
                                f"verify_redo_budget={verify_redo_budget}"
                            ),
                            recommended_action=(
                                "人工排查反复重启仍无法收敛的根因（验证环境/依赖/"
                                "测试挂起）；处置后 unfreeze_spec 解冻（自动清零重启"
                                "重验计数）重验"
                            ),
                            alert_callback=human_alert_callback,
                        )
                        self.logger.error(
                            "state_machine",
                            f"SPEC '{name}' 重启重验已达预算上限 "
                            f"({redo_count}/{verify_redo_budget}) — 冻结为 "
                            f"blocked 等待人工裁决（unfreeze_spec 可解冻并清零计数）",
                        )
                        recovered.append(name)
                        continue
                    # 清 tester_run 让验证流水线全新重入；branch/implementer_run
                    # 保留（实现的身份事实，验证不重做实现）
                    self.update_spec(
                        name,
                        {
                            "status": SpecStatus.IMPLEMENTED,
                            "error": f"Recovered from interrupted state: {status}",
                            "tester_run": None,
                            "_retry_count": 0,
                            "_merge_fp": None,
                            "_merge_streak": 0,
                            "_redispatch_same_cause_streak": 0,
                            "_redispatch_cause_fp": None,
                        },
                    )
                    recovered.append(name)
                    continue
                elif status == SpecStatus.REVIEWING:
                    # 评审中断恢复：回退 drafted，清空评审 run 引用与尝试计数，
                    # 使其重新进入晋升链（软化与两道 lint 幂等，分流重新判定）。
                    # 评审者对 SPEC 目录的修补被保留（不还原）。
                    self.update_spec(
                        name,
                        {
                            "status": SpecStatus.DRAFTED,
                            "error": f"Recovered from interrupted state: {status}",
                            "reviewer_run": None,
                            "_review_attempts": 0,
                        },
                    )
                    recovered.append(name)
                    continue
                # ── 待 re-merge-back 标记消费（fix-recovery-branch-anchor D3/D4）──
                # repair 成功待合并的 implementing spec（_repair_awaiting_remerge
                # =True）：直接 re-merge-back 完成合并、推进 implemented，
                # 不派发 implementer（tasks 4.1）。失败已清除标记，回落下方
                # 保留续做路径（tasks 4.3，spec 不滞留 implementing）。
                if entry.get("_repair_awaiting_remerge"):
                    remerged = self._recovery_remerge_pending(
                        name, entry, project_root, worktree_manager, remerge_callback
                    )
                    if remerged:
                        recovered.append(name)
                        continue
                # ── 中断恢复保留续做（interrupt-recovery-preserve D4）──
                # 有提交分支 → 保留 branch/implementer_run 并按 resume 续做；
                # 三态载体处置（在场/重建/降级）经 worktree_manager 单源查询
                # （is_available）。零提交/分支缺失/载体不可用 → 现行清空路径。
                preserved = self._recovery_preserve_spec(
                    name, entry, project_root, worktree_manager
                )
                if preserved:
                    recovered.append(name)
                    continue
                # 锚点不可得强制留痕（fix-recovery-branch-anchor E/7.2）：
                # 清空重建路径在写出清空状态时打 WARNING——三处锚点（STATE
                # branch / 在册 worktree / 分支命名空间枚举）均不可得时，
                # 权限内无任何可保留载体，本次恢复将清空重派（零留痕的静默
                # 早退正是本 SPEC 事故环 4 的根因之一）。
                self.logger.warning(
                    "state_machine",
                    f"Recovery clear-and-rebuild '{name}': 三处锚点均不可得 "
                    f"（STATE.branch 缺失、在册 worktree 无命中、分支命名空间"
                    f"枚举无候选）——清空状态走全新派发（零提交/分支缺失"
                    f"形态，任务书既有豁免）",
                )
                # 清空陈旧的 run 字段，否则 full_scan 的恢复派发会因
                # implementer_run 非空而跳过重新调度（fix-fenix-token-waste）
                self.update_spec(
                    name,
                    {
                        "status": SpecStatus.READY,
                        "error": f"Recovered from interrupted state: {status}",
                        "implementer_run": None,
                        "tester_run": None,
                        "branch": None,
                        # 一并清除待 re-merge 标记（fix-recovery-branch-anchor 3.4）：
                        # 清空重建路径不得残留标记，避免污染下一轮
                        "_repair_awaiting_remerge": False,
                        # WIP 等待标志复位（evo-add-wip-defer-merge-retry-consumer
                        # 1.2）：清空重建走全新派发，不得残留标志，避免周期消费者
                        # 在无分支锚点的全新条目上空转重试。
                        "_wip_gate_deferred": False,
                        "_retry_count": 0,
                        "_merge_fp": None,
                        "_merge_streak": 0,
                        "_redispatch_same_cause_streak": 0,
                        "_redispatch_cause_fp": None,
                    },
                )
                recovered.append(name)
        return recovered

    def _recovery_remerge_pending(
        self,
        name: str,
        entry: dict,
        project_root=None,
        worktree_manager=None,
        remerge_callback=None,
    ) -> bool:
        """恢复期 re-merge-back（fix-recovery-branch-anchor D4）。

        带 ``_repair_awaiting_remerge`` 标记的 implementing spec：实现分支已含
        main 的合并与冲突解决，仅剩重新合并进主树。直接调用既有
        ``merge_back_from_branch`` 完成合并并推进 implemented，不派发
        implementer、不经由 event_bus 排队（避免 ready 窗口被 full_scan
        误派）。

        成功收口字段与副作用对齐 repair re-merge 成功路径
        （dispatch.py:_run_repair_worker remerge_ok 分支）：
        - ``update_spec``：status=implemented、error=None、保留
          branch/implementer_run、_merge_fp/_merge_streak/_repair_round/
          _repair_merge_error 清零、_repair_awaiting_remerge=False；
        - 收口副作用（依赖接线，tasks 4.2）：``remerge_callback(spec_name)``
          由 fenixd 注入 PMEngine 侧实现（_clear_dispatch_conflict /
          _sync_task_progress / _reconcile_impl_budget / consume_legacy），
          缺省 None 时行为与旧版逐字节一致。verifier 派发由 boot 的
          event_bus.full_scan() 兜底，不在此复刻 _enqueue_front。

        Returns: True 表示 re-merge 成功并已推进 implemented；False 表示
        re-merge 失败（调用方清除标记后回落保留续做路径，spec 不滞留
        implementing）。
        """
        branch = entry.get("branch")
        if not branch:
            self.logger.warning(
                "state_machine",
                f"待 re-merge 标记但 branch 缺失 '{name}' — 清除标记回落保留续做",
            )
            return False
        if project_root is None or worktree_manager is None:
            return False
        try:
            merge_info = worktree_manager.merge_back_from_branch(branch)
            remerge_ok, remerge_error = merge_info
        except Exception as e:
            self.logger.warning(
                "state_machine",
                f"恢复期 re-merge-back 异常 '{name}'（branch '{branch}'）: {e}",
            )
            return False
        if not remerge_ok:
            # ── spec 目录在飞编辑顺延（evo-merge-back-spec-dir-inflight-guard
            # D1/D1a）── 恢复期 re-merge-back 被卫检查顺延（spec_dir_inflight=True）：
            # 主树 spec 目录有未提交改动，**MUST NOT** 消费 _repair_awaiting_remerge
            # 标记——原样保留待下一轮恢复/重排再试（等价于「视为尚未尝试合并」）。
            # 若清除标记会让「仅剩合并」的分支退回 ready 全新派发，白废已完成的实现。
            # 顺延的有界上限由 dispatch 调用方（D2）承载；此处是 daemon 重启单次的
            # 有界短窗（不自旋），由下一次重启/人工提交解除。
            if getattr(merge_info, "spec_dir_inflight", False):
                self.logger.warning(
                    "state_machine",
                    f"恢复期 re-merge-back 顺延 '{name}'（branch '{branch}'）: "
                    f"{remerge_error} — spec 目录在飞编辑，保留待 re-merge 标记"
                    f"待下一轮再试",
                )
                return False
            # re-merge 失败：清除标记后回落既有保留续做路径（tasks 4.3）——
            # 保留 branch/implementer_run + _recovery_resume，spec 落 ready，
            # 由下一轮 run 的正常 merge-back 经 _should_enter_repair 进入
            # 既有 repair/熔断通道。MUST NOT 静默清空该 spec 状态。
            self.update_spec(name, {"_repair_awaiting_remerge": False})
            self.logger.warning(
                "state_machine",
                f"恢复期 re-merge-back 失败 '{name}'（branch '{branch}'）: "
                f"{remerge_error} — 清除待 re-merge 标记，回落保留续做",
            )
            return False
        # re-merge 成功：推进 implemented，收口字段对齐 repair re-merge 路径
        self.update_spec(
            name,
            {
                "status": SpecStatus.IMPLEMENTED,
                "error": None,
                "implementer_run": entry.get("implementer_run"),
                "branch": branch,
                "_retry_count": 0,
                "_merge_fp": None,
                "_merge_streak": 0,
                "_redispatch_same_cause_streak": 0,
                "_redispatch_cause_fp": None,
                "_repair_round": 0,
                "_repair_merge_error": None,
                "_repair_awaiting_remerge": False,
            },
        )
        # 收口副作用回调（PMEngine 侧注入；tasks 4.2 依赖接线）
        if remerge_callback is not None:
            try:
                remerge_callback(name)
            except Exception as e:
                self.logger.warning(
                    "state_machine",
                    f"恢复期 re-merge 收口回调失败 '{name}'（非阻塞）: {e}",
                )
        # consume_legacy 属 worktree_manager 既有形参，不在此列（tasks 4.2）
        try:
            if worktree_manager is not None:
                worktree_manager.consume_legacy(name)
        except Exception as e:
            self.logger.warning(
                "state_machine",
                f"恢复期 re-merge consume_legacy 失败 '{name}'（非阻塞）: {e}",
            )
        self.logger.info(
            "state_machine",
            f"恢复期 re-merge-back 成功 '{name}'（branch '{branch}'）→ implemented",
        )
        return True

    def _resolve_preserved_branch(
        self, name: str, entry: dict, project_root=None, worktree_manager=None,
        *, context: str = "Recovery preserve",
    ) -> tuple:
        """共享保留判定主体（add-freeze-stop-inflight-agents 2.4）。

        从 _recovery_preserve_spec 提取、供其与 unfreeze_spec 续做接线共用——
        MUST NOT 保留第二份平行副本（前缀表/解析口径漂移已有事故先例：
        评审前缀表漂移、-r<n> 剥除口径漂移）。三层分支解析（fix-recovery-
        branch-anchor D2）+ rev-list 非空闸门 + resolve_resume_site 载体三态：

        1. STATE.branch；
        2. ``find_worktree_by_spec``（在册 worktree 事实查询）；
        3. ``find_branches_by_spec``（git 分支命名空间枚举，worktree 已清
           只剩分支时命中；候选经「已含 main」优先排序，零提交候选已剔除）。
        第三层命中时走既有 rev-list 非空闸门与 resolve_resume_site 载体处置。

        Returns: ``(resolved_branch, wt)`` 判定通过（分支可解析、相对 main
        有未合并提交、载体可用）；``(branch, None)`` 分支可解析且有未合并
        提交但载体三态暂不可用（Task 7.2：锚点不丢，交调用方重建载体）；
        ``(None, None)`` 判定不通过（锚点不可得/分支缺失/零提交）。
        """
        if project_root is None or worktree_manager is None:
            return None, None
        branch = entry.get("branch")
        ns_candidates: list = []
        if not branch and worktree_manager is not None:
            # 首轮在飞 run（STATE branch 未写，run 未到终态即被强杀）→ 回落
            # worktree_manager 的 spec → worktree 事实查询（git 真相，不依赖
            # 重启即失的内存表），反查该 spec 在册 worktree 归属分支。
            resolved = worktree_manager.find_worktree_by_spec(name)
            if resolved is not None:
                branch = resolved[1]
                self.logger.warning(
                    "state_machine",
                    f"{context}: STATE branch 缺失，经 git 事实查询回落 "
                    f"spec '{name}' 在册 worktree → branch '{branch}'",
                )
        if not branch and worktree_manager is not None:
            # 第三层：git 分支命名空间枚举（worktree 已清只剩分支的窗口）。
            # 候选已按「已含 main」优先排序、零提交候选剔除（D2/tasks 2.5）。
            ns_candidates = worktree_manager.find_branches_by_spec(name)
            if ns_candidates:
                best = ns_candidates[0]
                branch = best["branch"]
                cand_names = [c["branch"] for c in ns_candidates]
                self.logger.warning(
                    "state_machine",
                    f"{context}: STATE 与在册 worktree 双缺失，"
                    f"经分支命名空间枚举回落 spec '{name}' → 选中 "
                    f"branch '{branch}'（候选: {cand_names}）",
                )
        if not branch:
            # 锚点不可得早退：强制留痕（tasks 7.1）
            self.logger.warning(
                "state_machine",
                f"{context}: spec '{name}' 三处锚点均不可得——"
                f"STATE.branch 缺失、在册 worktree 无命中、"
                f"分支命名空间枚举："
                f"{'无候选' if not ns_candidates else [c['branch'] for c in ns_candidates]}",
            )
            return None, None
        try:
            # 分支可解析 + 相对 main 有未合并提交（rev-list --count > 0）。
            # 分支不存在时 rev-list 非零退出 → 走现行清空路径。
            ahead = subprocess.run(
                ["git", "-C", str(project_root), "rev-list", "--count", f"main..{branch}"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if ahead.returncode != 0:
                return None, None
            try:
                ahead_commits = int(ahead.stdout.strip() or "0")
            except ValueError:
                return None, None
            if ahead_commits <= 0:
                return None, None
        except (subprocess.TimeoutExpired, OSError):
            return None, None
        # 三态载体处置：在场原地 / 缺失重建 / 不可用降级
        wt, resolved_branch = worktree_manager.resolve_resume_site(name, branch)
        if wt is None:
            # fix-relocation-writeback-layer Task 7.2：载体三态暂不可用
            # （worktree 被实现 run 占用/重建失败）MUST NOT 连带丢弃已解析的
            # 分支锚点——返回 ``(branch, None)`` 让 unfreeze 续做接线仍记录
            # 续做分支 + _recovery_resume，由 dispatch 按三态重建载体。
            # 兼容性：_recovery_preserve_spec 以 ``wt is None`` 判定不通过，
            # 行为不变；unfreeze_spec 据第二元是否为 None 分流。
            self.logger.warning(
                "state_machine",
                f"{context} unavailable for '{name}': branch '{branch}' "
                f"无可用载体（三态判定失败）——保留分支锚点交 dispatch 重建",
            )
            return branch, None
        return resolved_branch, wt

    def _recovery_preserve_spec(
        self, name: str, entry: dict, project_root=None, worktree_manager=None
    ) -> bool:
        """实现中断的恢复保留判定与三态载体处置（interrupt-recovery-preserve D4/D5）。

        判定主体已提取为 ``_resolve_preserved_branch``（add-freeze-stop-
        inflight-agents 2.4 共享单点，本方法与其零漂移），此处仅负责判定通过
        后的更新集写入。

        判定：branch 在册、分支可解析、且 ``git rev-parse main..branch`` 非空
        （相对 main 有未合并提交）→ 保留。载体处置经 worktree_manager 三态
        单源查询（is_available）：在场原地登记（受清理豁免）；缺失在既有分支
        上重建 worktree；不可用降级清空重建并 WARNING。

        Returns: True 表示已保留并写入恢复续做标记（调用方计入 recovered）。
        """
        if project_root is None or worktree_manager is None:
            return False
        resolved_branch, wt = self._resolve_preserved_branch(
            name, entry, project_root, worktree_manager)
        if wt is None:
            return False
        self.logger.warning(
            "state_machine",
            f"Recovering interrupted SPEC '{name}' with preserved branch "
            f"'{resolved_branch}' (ahead of main) — resume continuation, "
            f"worktree={wt}",
        )
        self.update_spec(
            name,
            {
                "status": SpecStatus.READY,
                "error": f"Recovered from interrupted state: implementing "
                f"(resume preserved branch)",
                "implementer_run": entry.get("implementer_run"),
                "tester_run": None,
                "branch": resolved_branch,
                # dispatch 层据此识别「恢复续做」路径：在保留分支的 worktree 内
                # resume（claude --resume + 继承注记），而非从零新建分支。
                "_recovery_resume": True,
                # WIP 等待标志复位（evo-add-wip-defer-merge-retry-consumer 1.2，
                # 清除写点之一）：保留续做落 ready 后恢复 run 在飞期间，陈旧
                # 标志会让周期消费者把半成品分支过早 merge 进主树、并与在飞
                # run 收尾竞态。不变式「implementing + _wip_gate_deferred ⇒
                # 无在飞实现 run」由 boot 复位写点 + implementing→ready 中央
                # 清除（_apply_updates_entry 单点，封住 admin 处置复位/人工
                # ready 重派的稳态绕行）+ 消费者扫描兜底清理共同保证——boot
                # 复位 MUST 清标志。
                "_wip_gate_deferred": False,
                "_retry_count": 0,
                "_merge_fp": None,
                "_merge_streak": 0,
                "_redispatch_same_cause_streak": 0,
                "_redispatch_cause_fp": None,
            },
        )
        return True
