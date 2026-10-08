"""
state_machine.py — SPEC lifecycle state machine and STATE.md I/O.

Manages the finite state machine for SPECs:
  drafted → [reviewing →] ready → implementing → implemented → testing → verified → done → pushed
                                                       ↘ bug-found → implementing

Handles atomic reads/writes of STATE.md with file locking.
"""

import fcntl
import hashlib
import json
import os
import re
import subprocess
import tempfile
import threading

from core.git_base_branch import resolve_base_branch
from core.timelib import parse_ts
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

# 评审自动冻结专用前缀（evo-fix-spec-review-infra-attribution-bridge 4.1）：
# 评审自动冻结不得自称「用户指令冻结」，按根因取用可区分的评审专用前缀——
# - REVIEW_ATTEMPTS_FREEZE_ERROR_PREFIX：评审器连续失败至尝试上限（结果硬门/
#   写入边界/评审器内容失败等 content 类失败烧尽尝试预算）；
# - REVIEW_REJECTED_FREEZE_ERROR_PREFIX：方案连续被评审否决达 MAX_REJECT_REDO。
# 三条红线：① 调用点保留「原状态 reviewing」子串（parse_orig_status 解冻还原
# 依赖）与 spec-review-incomplete / spec-review-rejected 标记子串；② 前缀不得
# 命中 admin_monitor._INTENTIONAL_PAUSE_MARKERS 三短语、不得以 "frozen:" 开头
# （不挪用有意等待豁免的文本判据——该豁免语义属人工冻结）；③ 冻结仍经
# freeze_for_human「冻结+告警」成对入口。MUST NOT 据此修改 FREEZE_ERROR_PREFIX
# 常量值——freeze_spec 人工冻结路径（本文件）与 parse_orig_status 文档契约
# 依赖「用户指令冻结」前缀的有意豁免语义，动了即人工冻结豁免失效。
REVIEW_ATTEMPTS_FREEZE_ERROR_PREFIX = "评审失败冻结："
REVIEW_REJECTED_FREEZE_ERROR_PREFIX = "评审否决冻结："


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

    SPEC-B 批③：解析内核收拢 timelib.parse_ts（唯一入口）。支持带偏移
    （2026-09-07T01:00:00+00:00）与 'Z' 后缀；字符串与 datetime 对象入参的
    naive 值均按 timelib 唯一 naive 策略解读（本地时区——原「naive 按 UTC」
    第二策略退役；框架写侧恒产出 aware +00:00，存量 aware 数据逐项不变）。
    返回值折算 aware UTC。调度门控与 dashboard 写侧校验共用本函数（design D6
    「时间换算工具后端单点实现」），解析漂移收敛单点。
    """
    if isinstance(value, datetime):
        if not value.tzinfo:
            # naive → 本地 aware（astimezone 的 naive 语义：视作系统本地时区），
            # 对齐 timelib 唯一 naive 策略——原 replace(tzinfo=utc) 是未登记的
            # 第二种 naive 解读，违反 timelib「任何模块 MUST NOT 自行实现第二
            # 种 naive 解读」约定（code-review item 20911e4fdb9d）。
            value = value.astimezone()
        return value.astimezone(timezone.utc)
    dt = parse_ts(value)
    return dt.astimezone(timezone.utc) if dt is not None else None


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
        # 合法性校验：\S+ 贪婪捕获会把无空格分隔的原因一并吞入
        # （「原状态 testing·原因」→「testing·原因」，rstrip 剥不掉中间字符），
        # 非法值落盘后 _admit_entry 会在下个写者 read_all 时丢条目
        # （branch/run 锚点与预算计数一并物理删除）。非法与缺失同口径回退 ready。
        if status in SpecStatus.ALL:
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
# ── per-spec 轮数上限覆写（evo-add-impl-run-budget-sizing 1.2）──────────
# 人工管理属性：null/缺失 = 跟随 agents.max_turns（规模推算照常）；正整数 =
# per-spec 生效轮数上限（override > 推算 > base，design D3）。沿
# impl_run_budget_override 命名与语义先例，与 priority/start_after 同类，
# 须随条目序列化（serialize 显式键表），否则 STATE.md 全量回写时静默丢失。
IMPL_TURN_CAP_OVERRIDE_FIELD = "impl_turn_cap_override"
# ── per-spec 墙钟续期预算覆写（evo-add-impl-wallclock-budget-sizing 1.1）──
# 人工管理属性：null/缺失 = 跟随 agents.impl_wallclock_sizing（规模推算照常）；
# 正整数 = per-spec 生效续期预算 max_extensions（override > 推算 > base，只抬
# 不压，消费点 liveness._supervision_deadline_action）。沿
# impl_turn_cap_override 命名与语义先例，与 priority/start_after 同类，
# 须随条目序列化（serialize 显式键表），否则 STATE.md 全量回写时静默丢失。
IMPL_WALLCLOCK_EXTENSION_OVERRIDE_FIELD = "impl_wallclock_extension_override"

# ── 重启重验预算计数（fix-daemon-lifecycle-races D3）──────────────────
# - _verify_redo_count：daemon 重启恢复路径（testing→implemented 重派 verify）
#   的累计次数，跨重启持久化；与 _verify_fail_rounds（失败→fix 轮数）语义正交，
#   互不读写对方字段。达 agents.verify_redo_budget 阈值即冻结等待人工裁决，
#   堵死「毒 spec 借反复重启无限重验」敞口。
VERIFY_REDO_COUNT_FIELD = "_verify_redo_count"
# 重启重验预算缺省阈值（agents.verify_redo_budget 未配置时沿用本值）
DEFAULT_VERIFY_REDO_BUDGET = 3

# ── 验证/重派周期计数内部字段（code-review item d52ab6f4d442）────────
# 字段名单点定义（pm_engine 与 state_machine 共用，避免两处漂移）：
# - _inconclusive_attempts：inconclusive（含 judge 自述环境暂停）连续轮次计数
# - _redispatch_same_cause_streak：同因重派熔断计数（fix-redispatch-loop-governance）
# - _uniform_fail_attempts：全场景同因失败哨计数（观察窗）
INCONCLUSIVE_ATTEMPTS_FIELD = "_inconclusive_attempts"
REDISPATCH_SAME_CAUSE_STREAK_FIELD = "_redispatch_same_cause_streak"
UNIFORM_FAIL_ATTEMPTS_FIELD = "_uniform_fail_attempts"

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

# 冻结阈值单点定义（与上面字段名同源防漂移）：连续达到该轮数仍 env 阻塞
# → 结构化冻结转人工（判定在 pm_engine.verification 升级通道）。
ENV_BLOCK_FREEZE_THRESHOLD = 2

# ── env 豁免 STATE 结构化字段（evo-fix-env-exemption-gate-conflict-… 1.1/1.4）──
# 豁免以「场景 id + 归一化失败签名」为键持久化到 spec 级 STATE 字段（结构常量
# 单源定义，admin_actions / verdict_check / escalation 共用，防多点漂移）：
#
# - _env_exemptions：豁免清单，值存 JSON 字符串（STATE.md 行内可往返解析，
#   IMPL_DIAGNOSIS_FIELD 同范式），元素形态
#   {"scenario_id", "failure_signature", "scenario_hash", "granted_at",
#    "disposition_id"}（scenario_hash/disposition_id 可空）。
#   升级握手（escalation）与白化门禁（verdict_check）消费同一数据源——
#   「握手认可、门禁拒绝」双门矛盾（potplayer 2026-10-05 事故：豁免只落
#   AdminStore disposition，门禁读不到、43ms 后同因拒绝）由同源消除。
#   切换后 STATE 为唯一生效源：存量 AdminStore disposition 不做数据回填
#   （fail-closed——无 STATE 豁免即无豁免，受影响 spec 重走一次裁决即重建），
#   disposition 自此仅作审计镜像。
# - _scenario_revision_count：场景修订出口（revise_scenario_reverify）已执行
#   次数（生命周期累计，达上限后修订请求转人工冻结）。
# - _scenario_revision_reverify_pending：修订 re-entry 旗标。修订执行器置位；
#   升级停车入口见旗标先于升级消费一次（修订 re-entry 先于升级），verified
#   落定清除。
ENV_EXEMPTIONS_FIELD = "_env_exemptions"
SCENARIO_REVISION_COUNT_FIELD = "_scenario_revision_count"
SCENARIO_REVISION_PENDING_FIELD = "_scenario_revision_reverify_pending"

# 场景修订次数上限（evo-fix-env-exemption-gate-conflict-… 2.1，默认 2）：
# 修订是「重写验证输入」的人工出口，无上限则场景不可行的问题被反复修订
# 掩盖（预算焚烧的温和形态）。达上限后修订请求拒绝并冻结转人工。
# 生命周期累计（跨验证复位保持，_RETRY_COUNTER_RESETS 不清此字段）。
SCENARIO_REVISION_MAX_COUNT = 2

# 豁免时效锚点：granted_at 起超过该小时数即失效（TTL 过期后恢复既有升级/
# 冻结计数语义，冻结兜底保留）。
ENV_EXEMPTION_TTL_HOURS = 72

# 豁免清单条目上限：豁免随 grant 追加、随每次状态写盘整体重写，不设上限则
# 长生命周期 spec 反复裁决时无界增长（REFUNDED_RUN_IDS_MAX_ANCHORS 同款
# 封顶先例）；追加时截断保留最近 N 条。
ENV_EXEMPTION_MAX_ENTRIES = 64


def normalize_env_exemption_signature(text: str) -> str:
    """归一化失败签名：数字→N、去引号、折叠空白（豁免签名匹配口径）。

    与 ``infra_classify._normalize_fail_signature`` 同口径；不能直接 import——
    infra_classify 反向 import 本模块常量（FROZEN_FIELD），会成环。两处口径
    若演进 MUST 同步（此处注释即同步锚点）。
    """
    t = re.sub(r"\d+", "N", str(text or ""))
    t = re.sub(r"['\"`]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def scenario_fail_signature_body(sc: dict) -> str:
    """单场景失败签名体（不含场景 id 前缀；豁免键的签名粒度）。

    口径与 ``escalation._inconclusive_fail_signature`` 的单场景片段一致：
      - blocked-env 场景（从未执行、无失败断言）：签名退化为 ``blocked-env``；
      - 其余非 pass 场景：首失败断言 ``type + 归一化 actual``（failed_assertions
        → assertion_results → assertion 兼容序），仍无则回退
        ``classification|first_failed_step``；
      - pass/passed 场景返回空串（无豁免对象）。
    片段截断 120 字符（与既有签名摘要同口径，防 KB 级错误文本入库）。
    """
    if not isinstance(sc, dict):
        return ""
    status = sc.get("status")
    if status in ("pass", "passed"):
        return ""
    if status == "blocked-env":
        return "blocked-env"
    ev = sc.get("evidence") if isinstance(sc.get("evidence"), dict) else {}
    fa = None
    for key in ("failed_assertions", "assertion_results", "assertion"):
        val = ev.get(key)
        if isinstance(val, list) and val:
            fa = val
            break
    first = fa[0] if fa and isinstance(fa[0], dict) else None
    if first is not None:
        head = str(first.get("type") or "?")
        actual = str(first.get("actual") or "")
    else:
        head = "nosig"
        actual = f"{sc.get('classification') or ''}|{ev.get('first_failed_step') or ''}"
    return f"{head}+{normalize_env_exemption_signature(actual)[:120]}"


def scenario_fail_signature(sc: dict) -> str:
    """单场景完整签名片段 ``<场景id>:<签名体>``（跨轮比较口径，与升级通道一致）。"""
    if not isinstance(sc, dict):
        return ""
    sid = str(sc.get("scenario_id") or sc.get("id") or "?")
    return f"{sid}:{scenario_fail_signature_body(sc)}"


def scenario_definition_hash(scenario_def) -> str:
    """场景定义结构 hash（sort_keys JSON 的 sha256 前 16 位）。

    豁免「场景定义变更即失效」的锚点：grant 时记当前定义 hash，校验时以冻结
    场景文件中的当前定义重算比对——hash 变化即失效（场景被修订）。非 dict
    入参返回空串（无定义可锚）。
    """
    if not isinstance(scenario_def, dict):
        return ""
    try:
        payload = json.dumps(scenario_def, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return ""
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def load_frozen_scenario_hashes(project_root, spec_name: str) -> dict:
    """读冻结场景定义文件算 ``{场景 id: 定义 hash}``（本 SPEC 1.4 失效锚点）。

    豁免记录 grant 时的场景定义 hash；校验时以冻结文件中的当前定义重算比对
    ——hash 变化即「场景定义已修订」，豁免失效。读失败/文件缺失/格式损坏
    一律返回 {}（无变更证据不判失效——grant→reset 重验会删场景文件、重规划
    后才落回，此时豁免凭 id+签名+TTL 生效；env_exemption_active 同口径）。

    单源定义在本层（state_machine），``escalation._load_frozen_scenario_hashes``
    与 ``admin_actions._exec_grant_env_exemption`` 同引：grant 写入与双门校验
    读到的 hash 口径必须逐字节一致，任何一侧私藏副本都会造成「写入 A 校验 B」。
    """
    path = (
        Path(project_root) / ".fenix" / "verify-progress"
        / str(spec_name) / "test_scenarios.json"
    )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    if not isinstance(raw, list):
        return {}
    out: dict = {}
    for item in raw:
        if isinstance(item, dict) and item.get("id"):
            out[str(item["id"])] = scenario_definition_hash(item)
    return out


def parse_env_exemptions(entry) -> list:
    """STATE 条目读豁免清单（fail-closed：任何形状异常返回空清单=无豁免）。

    值为 JSON 字符串（serialize 往返后恒为字符串；进程内直写形态可能是已
    解析的 list，同样接受）。非 list / 元素非 dict / JSON 解析失败一律 []——
    读失败=无豁免，绝不 fail-open 到放行。
    """
    raw = None
    if isinstance(entry, dict):
        raw = entry.get(ENV_EXEMPTIONS_FIELD)
    elif isinstance(entry, (list, tuple)):
        raw = entry  # 直接传清单（进程内形态）
    elif isinstance(entry, str):
        raw = entry
    if raw is None or raw == "":
        return []
    if isinstance(raw, (list, tuple)):
        items = raw
    else:
        try:
            items = json.loads(str(raw))
        except (ValueError, TypeError):
            return []
    if not isinstance(items, list):
        return []
    return [it for it in items if isinstance(it, dict)]


def serialize_env_exemptions(exemptions: list) -> str:
    """豁免清单序列化为 STATE 字段值（JSON 字符串，紧凑分隔符防换行入行）。"""
    return json.dumps(list(exemptions or []), ensure_ascii=False,
                      separators=(",", ":"))


def env_exemption_active(exemption: dict, scenario_id: str, failure_signature: str,
                         current_hash: str = "", now=None) -> bool:
    """单条豁免对（场景 id+签名+可选定义 hash）是否有效（双门共享的纯函数）。

    失效条件（任一命中即无效）：
      - 键不匹配：场景 id 或归一化失败签名不相等（签名空串不匹配，fail-closed）；
      - 场景定义变更：豁免记录的 scenario_hash 与 current_hash **双方均非空且
        不等**（场景被修订即失效）。current_hash 为空（冻结文件缺失/不可读，
        无变更证据）不判失效——否则 grant→reset→重验（reset 会删场景文件、
        重规划）会把合法豁免整体打死；
      - 时效过期：granted_at 起超过 ``ENV_EXEMPTION_TTL_HOURS``（granted_at
        缺失/不可解析按过期，fail-closed）。

    ``now`` 供测试注入时钟；缺省取当前 UTC 时刻。
    """
    if not isinstance(exemption, dict):
        return False
    if str(exemption.get("scenario_id") or "") != str(scenario_id or ""):
        return False
    sig = normalize_env_exemption_signature(failure_signature)
    if not sig or sig != normalize_env_exemption_signature(
        str(exemption.get("failure_signature") or "")
    ):
        return False
    recorded_hash = str(exemption.get("scenario_hash") or "")
    if recorded_hash and current_hash and recorded_hash != str(current_hash):
        return False
    granted_raw = str(exemption.get("granted_at") or "")
    if not granted_raw:
        return False
    # 解析收拢 parse_utc（内核 timelib.parse_ts，唯一入口）：非法/空返回
    # None → 按过期处理（fail-closed，与原 fromisoformat 异常路径同语义）。
    # 写侧（admin_actions.grant）恒产出 aware UTC 串，aware 值折算时刻恒等。
    granted = parse_utc(granted_raw)
    if granted is None:
        return False
    now_dt = now if now is not None else datetime.now(timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)
    return (now_dt - granted).total_seconds() < ENV_EXEMPTION_TTL_HOURS * 3600.0


def find_env_exemption(entry, scenario_id: str, failure_signature: str,
                       current_hash: str = "", now=None):
    """在 STATE 条目的豁免清单中查找（场景 id+签名）命中的有效豁免。

    Returns: 命中的豁免 dict（同场景 id 多条时取最近 granted_at），无命中返回
    None（含清单缺省/读失败=fail-closed 无豁免）。
    """
    best = None
    best_key = ""
    for ex in parse_env_exemptions(entry):
        if not env_exemption_active(ex, scenario_id, failure_signature,
                                    current_hash=current_hash, now=now):
            continue
        key = str(ex.get("granted_at") or "")
        if best is None or key > best_key:
            best, best_key = ex, key
    return best

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
# - _verify_infra_retry_streak：infra-retry 车道专用连续重派计数
#   （evo-verify-infra-retry-lane D2）。**不复用** _verify_infra_rounds 作重试
#   预算：该账被 _escalate_env_blocked 既有挂钩点在每个全价 env 阻塞轮递增，
#   历史 env 轮会吃掉重试预算、使「缺省 2 次」承诺不可达——限次判定只读本
#   专用计数。清零点：验证 PASS（对齐 _verify_fail_rounds 唯一归零点，
#   pipeline._apply_verified 同段）+ unfreeze_spec 清零清单（同一原子写）。
VERIFY_INFRA_RETRY_STREAK_FIELD = "_verify_infra_retry_streak"
INFRA_REFUNDED_RUN_IDS_FIELD = "_infra_refunded_run_ids"
# - _dead_refunded_run_ids：JSON 字符串数组（已退款死亡 run_id）；
#   死亡 run 预算豁免退款幂等锚点——同一死亡 run 的并发豁免判定（如
#   监督者与恢复扫描各判一次）仅首次退款（item cd696b7c0de9，范式同
#   _infra_refunded_run_ids）。
DEAD_REFUNDED_RUN_IDS_FIELD = "_dead_refunded_run_ids"

# 锚点数组保留上限（code-review item 0717428fc4a8）：两个退款幂等锚点数组
# 只在退款时追加、全仓无读方（幂等判断仅在本文件退款路径内线性扫描），
# 不设上限则 daemon 长期运行叠加频繁重派时随豁免次数无界增长，且随每次
# 状态写盘被整体重写。追加时截断保留最近 N 条即可硬性封顶；被剪掉的均为
# 历史 run id，而调用方（_exempt_dead_run_budget / _exempt_infra_run_budget）
# 恒传「刚死亡/刚失败的那次 run id」，旧锚不会被重放，剪枝不影响幂等语义。
REFUNDED_RUN_IDS_MAX_ANCHORS = 256

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

# ── push 退避/重试计数字段（code-review item bbba88d8e6af）──────────
# [push_backoff next_retry_at=<ts>] 与 [push_attempts=N] 两个机器可读标记
# 原先仅寄居 error 文本，Dashboard「清除错误」整段清 error 时连根抹掉——
# 退避期判定（_is_push_backoffed 回 False）与连续重试计数
# （_get_push_retry_count 回 0）同时归零，自动 push 从零重新起算。字段化后
# 双活：写侧（engine._handle_push_failure）专用字段 + error 文本标记同步
# 写入（文本保留展示语义，兼作存量读侧回退）；读侧
# （reporting._is_push_backoffed / _get_push_retry_count）专用字段优先、
# 缺字段回退 error 文本解析（存量 spec 行为不变）。唯一清零点 = push 成功
# （approve_push 落 pushed 时随 error 一并同清）；clear_spec_error 清 error
# 前先摘取文本标记回写字段（过渡期承接），退避与计数不随「清除错误」归零。
# 字段名单点定义（pm_engine 与 dashboard 共用，避免两处漂移）。
PUSH_BACKOFF_NEXT_RETRY_AT_FIELD = "_push_backoff_next_retry_at"
PUSH_ATTEMPTS_FIELD = "_push_attempts"

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

# ── inconclusive 重验轮的 judge 预算隔离（fix-env-exemption-exit-reachability
# D3）────────────────────────────────────────────────────────────────
# 字段名单点定义（pm_engine.verification 与 state_machine 共用，避免漂移）。
# env 豁免握手/inconclusive 升级链进入重验窗口时，judge 派发门按旗标把本次
# 派发分流进独立计数器，MUST NOT 烧 ``_judge_rerun_count`` 生命周期预算——
# 否则「重验等人工」与「judge 硬上限」赛跑，后者总先到顶把人工出口截断
# （2026-10-03 potplayer-base 事故：judge_rerun_cap 冻结 6/5 先于 B7 升级）。
# _in_inconclusive_reverify：旗标。置位点 = inconclusive 处置链（escalation.py
# 级一 ``_handle_env_blocked_inconclusive`` / 级二
# ``_handle_verdict_env_exemption_inconclusive`` / judge 自述形态
# ``_handle_judge_env_declared``：各自重验分支直接置位，升级停车经共用收口
# ``_escalate_inconclusive_parking`` 置位）；清除点 = judge 申报非全 env
# 结论（bug-found / verified 放行 / scenario-repaired 重入决策点，单一助手
# ``_clear_inconclusive_reverify_flag``）、verified 落定、人工 reset_verification。
# _judge_inconclusive_dispatches：重验窗口内 judge 派发的独立计数（上限 =
# verify_engine.inconclusive_max_attempts 配置值），到顶升级停车。
# 两者与 _judge_rerun_count 同生命周期累计语义：**唯一**清零点 = 验证通过
# （verified 落定，verdict_evidence._record_verdict_adoption 既有清零点扩展）
# 与人工 reset_verification 清零清单。
JUDGE_INCONCLUSIVE_DISPATCHES_FIELD = "_judge_inconclusive_dispatches"
IN_INCONCLUSIVE_REVERIFY_FIELD = "_in_inconclusive_reverify"

# 上一轮 inconclusive 失败签名摘要（同 spec 2.2）：级一签名一致提前升级的
# 跨轮比较基准，每轮 inconclusive 处置点回写本轮值；与 _inconclusive_attempts
# 同生命周期（人工 reset_verification 清零清单含本字段——防跨 episode 过期
# 基准误判「环境未变」）。值域为 _inconclusive_fail_signature 产物串，空串 =
# 基准未知（保守走计数上限）。
LAST_INCONCLUSIVE_SIGNATURE_FIELD = "_last_inconclusive_signature"

# ── judge 场景原地修复预算（judge-scenario-repair）──────────────────
# 上限重入轮数单点定义（pm_engine.verification 的 pipeline.py 与 escalation.py
# 共用，避免两处漂移：一侧调参会使改道门与 judge 重入预算对不上）。
# 场景文件自身缺陷（夹具未自建/步骤客观错误/依赖序缺失）由 judge 原地修复
# 后重执行，不再「env 伪失败→原样重验」空转；上限与阶段1 replan_left 对齐。
# 2026-09-18：2 → 3（实证 add-spec-manual-activation：夹具场景第 3 轮才修出
# 正确修复却因预算耗尽无法重入，修复落盘却永不执行）。
_SCENARIO_REPAIR_MAX_ROUNDS = 3


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


def _spec_sort_key(item: Tuple[str, dict]) -> Tuple[int, str]:
    """(priority, created) 排序键：serialize 落盘序与查询序共用同一口径。

    code-review item aa6777dff877：缺失 created 的兜底值此前两处口径相反
    （serialize 兜 ``""`` 排最前、_sort_by_priority 兜 ``"z"`` 排最后），
    同键双兜底漂移。统一兜 ``"z"``——ISO 8601 时间戳以数字开头，ASCII 序
    恒小于 ``"z"``，异常条目排最后；正常数据的既有顺序不受影响。
    """
    return (item[1].get("priority", 999), item[1].get("created", "z"))


# ── 归档清单（add-archive-state-migration D1/D2）─────────────────────

# 已迁出 STATE.md 条目的归档清单，与 STATE.md 同级同生命周期（.fenix/ 内、
# gitignored 运行时目录），格式与 STATE.md 完全相同（### <name> + - key: value）。
ARCHIVE_MANIFEST_FILENAME = "STATE.archive.md"

# 迁出路径白名单（archived_by 溯源字段合法取值）：daemon 自动归档 / Dashboard
# 界面归档 / fenix-archive CLI / daemon 存量回填。
ARCHIVED_BY_PATHS = ("auto", "ui", "cli", "backfill")

# 终态集合：迁出原语只迁终态条目（与 archive_spec/auto_archive_check 的
# done/pushed 口径一致；非终态孤儿条目留人工排查，不做自动迁出）。
TERMINAL_SPEC_STATUSES = (SpecStatus.DONE, SpecStatus.PUSHED)

_ARCHIVE_MANIFEST_HEADER = (
    "# Fenix Archived Spec State\n"
    "# ==========================\n"
    "# 已从 STATE.md 迁出的归档条目（add-archive-state-migration D1）。\n"
    "# 格式与 STATE.md 相同；由迁出原语（StateMachine.evict_spec）维护，请勿手工编辑。\n\n"
)


class StateParser:
    """Parse and serialize STATE.md entries."""

    @staticmethod
    def parse(state_path: Path, logger=None) -> Dict[str, dict]:
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

        # [fenix-ignore:164c26159833] 读失败按空 dict 降级反而有害：写路径是
        # 「锁内 read_all → 改 → 全量回写 STATE.md」，降级空 dict 会诱使下个
        # 写者把全部条目（含 branch/run 锚点与预算计数）整体抹掉；上抛使写者
        # 一并失败、损坏文件得以保全（fail-loud 更安全），且主扫描链路
        # event_bus._run_full_scan_body 已对 read_all 异常捕获降级记 error。
        content = state_path.read_text(encoding="utf-8")
        return StateParser._parse_content(content, logger)

    @staticmethod
    def _admit_entry(name: str, entry: dict, specs: dict, logger) -> None:
        """收编解析出的条目：status 缺失/非法时记 warning 后丢弃。

        code-review item 685210d97ff8：status 缺失或值不在 SpecStatus.ALL 的
        条目此前被过滤点静默丢弃——而 update_spec/add_spec/remove_spec 走
        「锁内 read_all → 改 → _write_all_locked 全量回写」，一次手改 STATE.md
        的 status 拼写错误会让下个写者把该条目（含 branch/implementer_run
        锚点与全部预算计数）从文件整体删除且无痕。此处不改变既有丢弃行为，
        仅把丢弃显性化为 warning；logger=None（脚本/测试直调）时自然静默。
        """
        status = entry.get("status")
        if status in SpecStatus.ALL:
            specs[name] = entry
        elif logger is not None:
            logger.warning(
                "state_machine",
                f"跳过 status 缺失或非法的条目 '{name}': {status!r} —— "
                f"下个写者将把它从 STATE.md 移除",
            )

    @staticmethod
    def _parse_content(content: str, logger=None) -> Dict[str, dict]:
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
                    StateParser._admit_entry(current_name, current_entry, specs, logger)
                elif current_name and logger is not None:
                    # code-review item 4aa82fdfc368：仅标题行、其下没有任何能被
                    # kv 正则解析的字段行（键名大写被正则拒绝/内容全是裸文本等）
                    # 的条目同样会被丢弃——与 _admit_entry（685210d97ff8）同理，
                    # 下个写者按「锁内读全部→改→全量回写」落盘时会把该条目
                    # （含 branch/implementer_run 锚点与全部预算计数）从文件
                    # 整体抹除，此处把丢弃显性化为 warning。
                    logger.warning(
                        "state_machine",
                        f"跳过无可解析字段行的条目 '{current_name}'（仅标题行）—— "
                        f"下个写者将把它从 STATE.md 移除",
                    )
                current_name = _unescape_state_value(header_match.group(1).strip())
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
                elif key == IMPL_TURN_CAP_OVERRIDE_FIELD:
                    # per-spec 轮数上限覆写（evo-add-impl-run-budget-sizing
                    # 1.2）：同 impl_run_budget_override 先例——不转则 STATE.md
                    # 往返后读回字符串 "1200"，消费点正整数判定会误判非法。
                    # 非法值按 null 容错，消费点（runner）再作正整数校验。
                    try:
                        value = int(value)
                    except ValueError:
                        value = None
                elif key == IMPL_WALLCLOCK_EXTENSION_OVERRIDE_FIELD:
                    # per-spec 墙钟续期预算覆写（evo-add-impl-wallclock-budget-
                    # sizing 1.1）：同 impl_turn_cap_override 先例——不转则
                    # STATE.md 往返后读回字符串 "4"，消费点正整数判定会误判
                    # 非法。非法值按 null 容错，消费点（runner）再作正整数校验。
                    try:
                        value = int(value)
                    except ValueError:
                        value = None
                elif key == "_verify_parallel_override":
                    # 降档并行度覆盖（add-verify-parallel-backoff）：契约
                    # int|None（evo-fix-verify-parallel-override-type 2.1）。
                    # 与 impl_run_budget_override 先例同款 int 归一，null 兼容
                    # （None=复位语义，原 null 清单成员迁入本分支）。存量
                    # STATE.md 的 'False' 坏写（布尔归一清单不含本字段，布尔
                    # 值曾整段字符串化落盘）首读即清洗为 None——复位语义，
                    # 读端沿用配置并行度且不再触发解析降档告警；其余不可解析
                    # 形状同样容错为 None（写侧 _apply_updates_entry 已拒布尔/
                    # 字符串，此处仅兜历史残留与锁外内存写）。
                    if value.lower() in ("null", "none", ""):
                        value = None
                    else:
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
                    # fix-env-exemption-exit-reachability D3：inconclusive 重验
                    # 旗标（judge 预算隔离分流判据）——False 不转会被误判为
                    # 恒在重验轮（judge 派发持续分流进独立计数器，生命周期
                    # 账永不累计）。
                    "_in_inconclusive_reverify",
                    # evo-merge-back-spec-dir-inflight-guard D2：merge-only 重试
                    # 顺延标记——False 不转会被误判为恒顺延（_defer_merge_back
                    # 读回字符串 "False" 为 truthy）。
                    "_merge_retry_pending",
                    # evo-add-wip-defer-merge-retry-consumer 1.2：WIP 重叠闸门
                    # 阻断的延迟合回等待标志——False 不转会 STATE.md 往返后
                    # 读回字符串 "False" 为 truthy，周期消费者会把已清账条目
                    # 误判为仍带标志（同 _merge_retry_pending 先例）。
                    "_wip_gate_deferred",
                    # code-review item 7920884822f1：token 预算告警幂等标志——
                    # dashboard raise_budget 复位写 False，不转会 STATE.md
                    # 往返后读回字符串 "False" 为 truthy，复位动作失效、
                    # 预算翻倍后告警仍永久静默（消费侧 token_budget 以
                    # bool(entry.get(...)) 读幂等标志，同 _merge_retry_pending
                    # 先例）。
                    "_token_warn_80",
                    "_token_alert_100",
                    # evo-fix-env-exemption-gate-conflict-… 2.2：场景修订待重验
                    # 旗标——False 不转会读回 "False" 为 truthy，升级停车入口
                    # 会把已消费的修订 re-entry 误判为仍在待重验（无限追加
                    # 重验轮）。
                    SCENARIO_REVISION_PENDING_FIELD,
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
                    # code-review 56f1aefd2823：depends_on 可空——serialize 对
                    # 缺失/None 恒写 null，未登记本表则 STATE.md 往返后读回
                    # 字符串 "null" 而非 None，消费点被迫各自硬编码
                    # == "null" 防御（event_bus._find_dependents、
                    # pm_engine._dependencies_satisfied/_dependencies_pending），
                    # 新消费点漏写即把 "null" 当依赖 spec 名去查并误告警。
                    # serialize 写格式保持不变（仍写 null，兼容既有落盘格式）。
                    "depends_on",
                    "total_duration",
                    START_AFTER_FIELD,
                    FROZEN_UNTIL_FIELD,
                    # _verify_parallel_override 已迁出本清单（上方 int|None 归一
                    # 分支，evo-fix-verify-parallel-override-type 2.1）。
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
                    # 合并熔断指纹（recover_interrupted/remerge 收口四处把
                    # _merge_fp 置 None）——None 经 serialize 写 null、解析回退
                    # None（否则读回 "null" 字符串是 truthy，会被误当真实指纹
                    # 参与比较与 merge_streak 告警文案，与 _redispatch_cause_fp
                    # 同型登记）。
                    "_merge_fp",
                ):
                    if value.lower() in ("null", "none", ""):
                        value = None

                current_entry[key] = value

        # Don't forget the last entry
        if current_name and current_entry:
            StateParser._admit_entry(current_name, current_entry, specs, logger)
        elif current_name and logger is not None:
            # code-review item 4aa82fdfc368：同上，仅标题行的末尾条目丢弃前留痕
            logger.warning(
                "state_machine",
                f"跳过无可解析字段行的条目 '{current_name}'（仅标题行）—— "
                f"下个写者将把它从 STATE.md 移除",
            )

        return specs

    # serialize 固定字段表（顺序即落盘字段序）。成员判定共用 SERIALIZED_FIELD_SET
    # （code-review 94803b70af42）：写侧（_apply_updates_entry 的白名单外键
    # 显性化告警）与读侧口径以此单源，避免第二份漂移白名单。固定表之外的键中
    # 仅下划线前缀内部字段会被 serialize 透传，其余普通命名键在全量回写时
    # 被丢弃——写侧据此显性化（不改变丢弃行为）。
    SERIALIZED_FIELDS = [
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
        IMPL_TURN_CAP_OVERRIDE_FIELD,
        IMPL_WALLCLOCK_EXTENSION_OVERRIDE_FIELD,
        "reviewer_run",
    ]
    SERIALIZED_FIELD_SET = frozenset(SERIALIZED_FIELDS)

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

        # Sort by priority then created time（与查询序共用 _spec_sort_key 同口径，
        # code-review item aa6777dff877）
        sorted_specs = sorted(specs.items(), key=_spec_sort_key)

        for name, entry in sorted_specs:
            # 条目名单行化与字段值同纪律（code-review item dfd3b091fbb0）：
            # 裸换行会让续行脱离条目结构；解析侧 header 经 _unescape_state_value
            # 逆变换，转义后可无损往返。
            lines.append(f"### {_escape_state_value(name)}")
            for key in StateParser.SERIALIZED_FIELDS:
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
        # 归档清单路径（add-archive-state-migration D1）：与 STATE.md 同级
        # （.fenix/STATE.archive.md），迁出原语与清单小节移除共用同一把
        # .STATE.md.lock 串行化两文件的写序。
        self._archive_path = self.state_path.parent / ARCHIVE_MANIFEST_FILENAME
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
        raw = StateParser.parse(self.state_path, self.logger)
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
        content = StateParser.serialize(specs)
        self._atomic_write_text(self.state_path, content)

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

    def _anchor_recheck_locked(self, specs: Dict[str, dict], spec_name: str,
                               snapshot: Optional[dict],
                               anchor_fields) -> tuple:
        """锁内锚点复核共享 helper（code-review 6e8fb8190679）。

        「锁内以最新条目处理 branch/implementer_run 等快照锚点、不一致时经
        ``anchor_recheck`` 带出锁外告警」的 ``_mutate`` 闭包模式此前在
        freeze_spec（锁内取最新值透传）、unfreeze_spec、_recovery_remerge_pending、
        _recovery_preserve_spec（后三处复核锁外快照，失败策略各异：放弃锚点
        回写继续解冻 / 放弃锚点回写保留推进 / 整体放弃本写）四处各持一份实现，
        新增锚点字段或调整比较口径须四处人工同步。本 helper 收敛「取最新条目 +
        锚点字段逐项比较」这一公共口径为单源；差异化的失败策略留在各调用方
        分支。

        Args:
            specs: ``_mutate_locked`` 锁内回调拿到的最新条目表。
            spec_name: 目标条目名。
            snapshot: 锁外快照 entry；None 表示无快照可比（freeze_spec 锁内
                取值形态），matched 恒 True。
            anchor_fields: 参与比较的锚点字段集。

        Returns: ``(fresh, matched)``：fresh 为最新条目（SPEC 缺失时空 dict，
            该缺失形态由调用方据其落「SPEC 并发删除」出口，见
            _recovery_remerge_pending / _recovery_preserve_spec）；matched 为
            锚点字段集内快照与最新值是否全部一致。

        锁语义：MUST 在 ``.STATE.md.lock`` 的锁内被调用（本方法不取锁、不落
        盘、无 I/O，持锁窗口不含日志）。
        """
        fresh = specs.get(spec_name) or {}
        if snapshot is None:
            return fresh, True
        matched = all(
            fresh.get(field) == snapshot.get(field) for field in anchor_fields
        )
        return fresh, matched

    # ── 预算计数原子原语（fix-budget-counting-semantics D2）──────────

    def _bump_counter(self, spec_name: str, field: str, delta: int) -> int:
        """文件锁内原子读改写计数器字段并回读校验。

        消除「读 STATE → 改 → 写回」非原子序列在并发（恢复扫描 × 派发）下
        丢失增量的竞态（interaction-contract 复盘：used=2/4 连续出现两次）。
        锁内完成 读→改→写→回读校验；回读不匹配时重试一次并记审计日志。
        结果下限 0（delta=-1 时不会把计数打成负数）。

        单字段薄封装（code-review 9b32a0d20a16）：本方法与 ``bump_counters``
        的锁内流程逐行同型（读→逐字段钳零改写→落盘→回读校验→不匹配重试
        一次→SPEC-not-found 带出锁外告警），此前各持一份约 50 行实现，回读
        校验口径、重试次数、下限钳零等语义调整须双点同步、漏改一侧即行为
        漂移（同 ``_refund_run_once`` 的收敛理由）。收敛为委托
        ``bump_counters`` 单字段 dict，语义单点维护：返回值取返回 dict 中的
        单值，三个出口（匹配→新值 / SPEC 缺失→0 / 重试后仍不匹配→磁盘值）
        与旧实现逐一等价；verify 不匹配与 SPEC-not-found 两处告警改由
        ``bump_counters`` 输出，触发条件/级别/次数不变，仅字段标签渲染为
        单元素列表（``bump ['<field>'] …``）。

        Returns: 最终生效值；spec 不存在时记 warning 并返回 0。
        """
        return self.bump_counters(spec_name, {field: delta})[field]

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
        missing = False
        for attempt in (1, 2):
            new_values: Dict[str, int] = {}
            with open(lock_path, "w") as lock_f:
                fcntl.flock(lock_f, fcntl.LOCK_EX)
                try:
                    specs = self.read_all()
                    if spec_name not in specs:
                        # 锁内不落日志（持锁窗口不含 I/O），告警带出锁外再记
                        missing = True
                        break
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
        # SPEC-not-found 告警带出锁外再记（锁内不输出日志）
        if missing:
            self.logger.warning(
                "state_machine",
                f"bump {sorted(deltas)} failed: SPEC not found: {spec_name}",
            )
            return {field: 0 for field in deltas}
        # 重试后仍不匹配：返回磁盘实际值（以落盘为准），由调用方审计
        return verify

    def bump_impl_budget(self, spec_name: str, delta: int) -> int:
        """实现尝试预算计数原子增减（``_impl_run_budget_used``）。

        启动计数（delta=+1）与死亡豁免（delta=-1，下限 0）统一走本函数。

        Returns: 递增/回退后的使用次数（跨重启持久化）。
        """
        return self._bump_counter(spec_name, IMPL_RUN_BUDGET_USED_FIELD, delta)

    def set_impl_budget_used_if_unchanged(
        self,
        spec_name: str,
        used_value: int,
        observed_used: int,
        observed_run: str = "",
        check_run: bool = True,
    ) -> bool:
        """预算对账 used 改写的锁内条件写（CAS，code-review item 0cfbe1852825）。

        对账方（``_reconcile_impl_budget``）的守卫读（``implementer_run`` 快照
        + used 起点读）与 used 改写分处多次独立临界区：窗口内并发派发经
        ``bump_impl_budget(+1)`` 落下的启动计数会被陈旧 expected 盲写覆盖
        （丢失更新形态——新 run 计数永久丢失、spec 意外多获预算）。本原语把
        「复核 → 改写」收进单把 ``.STATE.md.lock`` 临界区（与 ``_bump_counter``
        / ``_refund_run_once`` 同范式）：used 与 ``implementer_run`` 均仍等于
        对账侧观测值才写入 ``used_value``——任一已变化（并发派发 bump、退款、
        锚点改写发生过）即不改写返回 False，调用方保守跳过本轮、待下一轮
        对账收敛。仅复核 run 锚不足以挡住 bump：派发的启动计数与锚点改写
        分处两个临界区，bump 先行落地时 run 锚尚未变化，故 used 一并入条件。

        ``check_run=False``（used 上调方向校正专用，item 2fcdfc8f4451）：跳过
        run 锚复核、仅 CAS used——上调的 ``used_value`` 出自 runs 产物计数
        扫描，该路径守卫读未观测 run 锚快照（无值可复核）；并发派发/退款
        的计数改写必先经同一把锁落在 used 上，used 复核已足以挡住覆盖丢失。

        锁内不落日志（持锁窗口不含 I/O），SPEC-not-found 告警带出锁外再记
        （同 ``_refund_run_once`` 约定）。

        Returns: True 表示复核通过且已落盘；False 表示条件失配或 spec 不存在
        （两种情况均未写任何字段）。
        """
        lock_path = self._lockfile
        missing = False
        with open(lock_path, "w") as lock_f:
            fcntl.flock(lock_f, fcntl.LOCK_EX)
            try:
                specs = self.read_all()
                if spec_name not in specs:
                    # 锁内不落日志（持锁窗口不含 I/O），告警带出锁外再记
                    missing = True
                else:
                    entry = specs[spec_name]
                    current_run = str(entry.get("implementer_run") or "")
                    try:
                        current_used = int(
                            entry.get(IMPL_RUN_BUDGET_USED_FIELD, 0) or 0
                        )
                    except (TypeError, ValueError):
                        current_used = 0
                    if current_used != observed_used or (
                        check_run and current_run != observed_run
                    ):
                        return False
                    entry[IMPL_RUN_BUDGET_USED_FIELD] = used_value
                    entry["updated"] = datetime.now(timezone.utc).isoformat()
                    self._write_all_locked(specs)
                    return True
            finally:
                fcntl.flock(lock_f, fcntl.LOCK_UN)
        # SPEC-not-found 告警带出锁外再记（持锁窗口不含 I/O）
        self.logger.warning(
            "state_machine",
            f"set impl budget used (guarded) failed: SPEC not found: {spec_name}",
        )
        return False

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
        return self._refund_run_once(
            spec_name,
            anchor,
            INFRA_REFUNDED_RUN_IDS_FIELD,
            reason_label="refund impl budget",
        )

    def _refund_run_once(
        self, spec_name: str, anchor: str, field: str, reason_label: str
    ) -> tuple:
        """「查锚点 → 退款 → 记锚点」的公共实现（code-review item 160a8d556423）。

        refund_impl_budget_once 与 refund_dead_run_once 此前各持一份约 60 行
        的相同方法体，唯一实质差异是锚点侧车字段与 SPEC-not-found 告警文案；
        收敛为单份后幂等与加锁语义只维护一处，两个公开方法各传自己的锚点
        字段（INFRA_REFUNDED_RUN_IDS_FIELD / DEAD_REFUNDED_RUN_IDS_FIELD）
        成为薄封装。

        追加锚点后截断保留最近 REFUNDED_RUN_IDS_MAX_ANCHORS 条（item
        0717428fc4a8，防数组无界增长；见该常量处安全性论证）。锁内不落日志
        （持锁窗口不含 I/O），SPEC-not-found 告警以 ``reason_label`` 区分来源、
        带出锁外再记。

        Returns: ``(refunded, used)``，语义与两个公开方法 docstring 一致。
        """
        lock_path = self._lockfile
        missing = False
        with open(lock_path, "w") as lock_f:
            fcntl.flock(lock_f, fcntl.LOCK_EX)
            try:
                specs = self.read_all()
                if spec_name not in specs:
                    # 锁内不落日志（持锁窗口不含 I/O，见 _log_update_applied
                    # docstring），SPEC-not-found 告警带出锁外再记
                    missing = True
                else:
                    entry = specs[spec_name]
                    refunded_raw = entry.get(field) or "[]"
                    try:
                        refunded = (
                            json.loads(refunded_raw)
                            if isinstance(refunded_raw, str)
                            else []
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
                        # 截断保留最近 N 条（item 0717428fc4a8）：数组长度不足
                        # 上限时 del 空切片为无操作。锁内不落日志（持锁窗口
                        # 不含 I/O），剪枝静默。
                        del refunded[:-REFUNDED_RUN_IDS_MAX_ANCHORS]
                        entry[field] = json.dumps(refunded, ensure_ascii=False)
                    entry["updated"] = datetime.now(timezone.utc).isoformat()
                    self._write_all_locked(specs)
                    return True, entry[IMPL_RUN_BUDGET_USED_FIELD]
            finally:
                fcntl.flock(lock_f, fcntl.LOCK_UN)
        # SPEC-not-found 告警带出锁外再记（持锁窗口不含 I/O）
        self.logger.warning(
            "state_machine",
            f"{reason_label} failed: SPEC not found: {spec_name}",
        )
        return True, 0

    def refund_dead_run_once(self, spec_name: str, anchor: str) -> tuple:
        """死亡 run 预算豁免的锁内原子「查锚点 → 退款 → 记锚点」（item cd696b7c0de9）。

        旧路径 ``bump_impl_budget(-1)`` 无锚点直接回退：同一死亡 run 的并发
        豁免判定（如监督者与恢复扫描各判一次）都读不到退款痕迹、各自回退
        一次（丢失更新形态，used 重复回退、spec 意外多获预算）。本方法与
        ``refund_impl_budget_once``（infra 退款收敛，item 40f7a931dc4c）同
        范式：把「查豁免锚点 + 回退 + 记锚点」收进单把 ``.STATE.md.lock``
        临界区——锚点已登记 → 幂等跳过不退款；未登记的非空锚点 → 退款并
        追加锚点一次完成。空锚点只退款、不登记，幂等不保证——由调用方
        保证单轮单次（契约见 ``_exempt_dead_run_budget``：无锚点时仍退款）。

        Returns: ``(refunded, used)``
            refunded=False 表示该死亡 run 已退款过（幂等跳过）；used 为退款后
            （或幂等跳过时的当前）used 值。spec 缺失按旧 bump 路径容错：
            记 warning 并返回 (True, 0)，不阻断调用方。
        """
        return self._refund_run_once(
            spec_name,
            anchor,
            DEAD_REFUNDED_RUN_IDS_FIELD,
            reason_label="refund dead run budget",
        )

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
        missing = False
        with open(lock_path, "w") as lock_f:
            fcntl.flock(lock_f, fcntl.LOCK_EX)
            try:
                specs = self.read_all()
                if spec_name not in specs:
                    # 锁内不落日志（持锁窗口不含 I/O，见 _log_update_applied
                    # docstring），SPEC-not-found 告警带出锁外再记
                    missing = True
                else:
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
        # SPEC-not-found 告警带出锁外再记（持锁窗口不含 I/O）
        self.logger.warning(
            "state_machine",
            "reset task_gate_rejections failed: "
            f"SPEC not found: {spec_name}",
        )
        return 0

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

    def bump_verify_infra_retry_streak(self, spec_name: str, delta: int = 1) -> int:
        """infra-retry 专用连续重派计数原子增减（evo-verify-infra-retry-lane D2）。

        与 ``_verify_infra_rounds``（纯观测）严格分离：限次判定只读本计数，
        历史全价 env 轮不污染廉价重试预算。清零点：验证 PASS（pipeline
        _apply_verified 同段）+ unfreeze_spec 清零清单。返回增减后的值。
        """
        return self._bump_counter(spec_name, VERIFY_INFRA_RETRY_STREAK_FIELD, delta)

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
        （调用方须自行核对 ``_stripped`` 才能判知 status 写未生效——只消费
        bool 返回值的既有调用方不受影响）；剥离/拒绝后零字段生效时不落盘
        （code-review c8881a2031f0，与 ``_transition_atomic`` 的 45dc313473ef
        零写入口径对齐），此时连 ``updated`` 时间戳也不刷新。
        """
        applied: dict = {}

        def _mutate(specs):
            found = self._apply_updates_entry(specs, spec_name, updates, applied)
            if found:
                # 零写入（code-review c8881a2031f0，对齐 _transition_atomic 在
                # 45dc313473ef 的既有口径）：applied = local 生效字段 ∪ 留痕键
                # （_stripped / _rejected_verify_parallel_override /
                # _dropped_keys），故「applied 仅含留痕键」⟺「剥离/拒绝后
                # local 为空、零字段生效」——唯一残留副作用只剩
                # _apply_updates_entry 的 updated 时间戳刷新，改返回
                # changed=False 跳过全量落盘（避免仅 updated 变化的 STATE.md
                # 回写与 EventBus 空 diff 噪声）；留痕键伴随有效字段时（如
                # 非法形状 _verify_parallel_override 被拒、其余更新照常应用）
                # local 非空，照常落盘。
                effective = [
                    k for k in applied
                    if k not in ("_stripped", "_rejected_verify_parallel_override",
                                 "_dropped_keys")
                ]
                if not effective:
                    return found, False
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
        - 条目 ``updated`` 时间戳随每次成功应用刷新；
        - 单字段形状守卫（evo-fix-verify-parallel-override-type 2.1a）：非法
          形状（布尔/字符串等非 int|None）的 ``_verify_parallel_override``
          拒绝写入，剥字段留痕（``_rejected_verify_parallel_override``），
          其余更新照常应用。

        ``applied`` 收集本次实际生效的字段（含 ``_stripped`` 剥离留痕），
        供 ``_log_update_applied`` 在锁外输出留痕日志。

        Returns: True 表示条目存在且已应用（调用方据其决定是否落盘）。
        """
        if spec_name not in specs:
            return False
        entry = specs[spec_name]
        local = dict(updates)
        # 单字段形状守卫（evo-fix-verify-parallel-override-type 2.1a）：
        # _verify_parallel_override 契约 int|None（降档并行度 int 或复位
        # null）。布尔或非 int 形状（'False'/'true' 等字符串、float 等）拒绝
        # 写入——不静默序列化进 STATE.md（布尔 False 曾整段字符串化往返、
        # 读端 int() 解析失败降档告警）。仅剥该字段，其余更新照常应用（裁决
        # 复位主体不受牵连）；注意 bool 是 int 子类，先判 bool。拒绝优先于
        # 静默归 None（design 风险项：归一过宽会掩盖真实坏值），留痕经
        # applied 带出锁外，由 _log_update_applied 输出 warning（锁内不落日志）。
        if "_verify_parallel_override" in local:
            _vpo = local["_verify_parallel_override"]
            if not (_vpo is None or (isinstance(_vpo, int) and not isinstance(_vpo, bool))):
                applied["_rejected_verify_parallel_override"] = _vpo
                del local["_verify_parallel_override"]
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
        # code-review 94803b70af42：serialize 只落固定字段表 + 下划线前缀内部
        # 字段两类键，既不在固定表也无下划线前缀的自定义键（如未来写入的
        # note/verified_at 等普通命名键）会在下一次全量回写时被静默丢弃，而
        # 解析端 _parse_content 的 kv 正则却无条件收编——读写口径不对称。此处
        # 不改变丢弃行为，仅把「写了但存不下」显性化（与 _admit_entry 的
        # 显性化策略同款）：收集进 applied 带出锁外，由 _log_update_applied
        # 输出 warning（锁内不落日志，见 _log_update_applied docstring）。
        dropped = sorted(
            k for k in local
            if not k.startswith("_") and k not in StateParser.SERIALIZED_FIELD_SET
        )
        if dropped:
            applied["_dropped_keys"] = dropped
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
        dropped = applied.get("_dropped_keys")
        if dropped:
            # code-review 94803b70af42：serialize 白名单外普通命名键的显性化
            # 告警（收集点在 _apply_updates_entry，此处锁外输出）
            self.logger.warning(
                "state_machine",
                f"SPEC '{spec_name}' 的更新含 serialize 固定字段表外且无下划线"
                f"前缀的键 {dropped}——本次内存写可见，但 STATE.md 全量回写时"
                f"会被静默丢弃（读写口径不对称，仅显性化不改变丢弃行为）",
            )
        if "_rejected_verify_parallel_override" in applied:
            # evo-fix-verify-parallel-override-type 2.1a：非法形状拒绝留痕
            # （收集点在 _apply_updates_entry，此处锁外输出）。值恒非 None
            # （None 是合法形状，不会进 rejected）。
            self.logger.warning(
                "state_machine",
                f"SPEC '{spec_name}' 的更新含非法形状的 _verify_parallel_override="
                f"{applied['_rejected_verify_parallel_override']!r}"
                f"（契约 int|None：降档并行度 int 或复位 null）——已拒绝该字段"
                f"写入，不序列化进 STATE.md；其余更新照常应用",
            )
        self.logger.info(
            "state_machine",
            f"Updated SPEC '{spec_name}'",
            {
                "updates": {
                    k: v for k, v in applied.items()
                    if k not in ("updated", "_stripped", "_dropped_keys",
                                 "_rejected_verify_parallel_override")
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
            # 锚点取最新条目的口径收敛到共享 helper（code-review 6e8fb8190679；
            # 本处为锁内取值形态，无快照可比 → snapshot=None）
            fresh, _matched = self._anchor_recheck_locked(
                specs, spec_name, None, ("branch", "implementer_run", "reviewer_run")
            )
            if fresh.get("status") in INTERRUPTED_STATES:
                for _anchor in ("branch", "implementer_run", "reviewer_run"):
                    if fresh.get(_anchor) is not None:
                        updates[_anchor] = fresh.get(_anchor)
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
            # 防误用：error/status/frozen 三键只应由本方法自身设定——携带
            # error 会用非冻结前缀文案覆盖冻结 error（parse_orig_status 失效）；
            # 携带 status/frozen 会覆盖已置的 blocked/True，且 updates 自带
            # FROZEN_FIELD 使 _apply_updates_entry 的冻结剥离分支不触发，
            # 落盘 frozen=True 而 status≠blocked 的自相矛盾条目。
            safe_extra = {
                k: v
                for k, v in extra_updates.items()
                if k not in ("error", "status", FROZEN_FIELD)
            }
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
        - 判定通过（分支在册 + 相对解析基线有未合并提交 + 载体可用）→ 同一
          原子写保留 branch/implementer_run、置 ``_recovery_resume: True``、
          清 ``_frozen_hold``，status 用解析出的原状态——dispatch 拾取后在
          保留分支上 resume 续做，而非从零新建分支。
        - 判定不通过（无 branch / 零提交 / 载体不可用）→ 清 ``_frozen_hold``、
          不置 ``_recovery_resume``、走普通重派，并 WARNING 留痕降级原因。
        锚点回写在 ``.STATE.md.lock`` 锁内以最新条目复核（与 freeze_spec 同一
        口径）：续做判定依据的锁外快照若已在窗口内被并发改写/清空，则放弃
        branch/implementer_run 回写并 WARNING 留痕，防陈旧锚点复活
        （fenix-fix f5a17d596717）。
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
        resume_anchors: dict = {}
        if resume_branch is not None:
            updates["status"] = resume_status
            # dispatch 层据此识别「解冻续做」路径：在保留分支的 worktree 内
            # resume，而非从零新建分支（与 _recovery_preserve_spec 同源输出）。
            updates["_recovery_resume"] = True
            # 锚点不在此处进 updates（fenix-fix f5a17d596717，与 freeze_spec
            # 的 code-fix d266d19c4860 同一口径）：本方法的锁外 read_one 快照
            # 与落盘之间隔着 _resolve_preserved_branch 的 git 子进程（窗口可达
            # 秒级），期间其他写者（dashboard/admin 处置/恢复链）若已改写或
            # 清空锚点，锁外旧值会在本写中复活。回写载荷是 git 解析出的
            # resume_branch（快照 branch 缺失时来自命名空间枚举），不能改写
            # 成锁内最新值，故收进 _mutate_locked 的锁内回调：以最新条目复核
            # 快照锚点未变才并入（见下方 _mutate），git 子进程保持在锁外。
            resume_anchors = {
                "branch": resume_branch,
                "implementer_run": resume_impl_run,
            }
        updates[FROZEN_HOLD_FIELD] = False
        # 计数清零并入同一原子写，避免解冻后残留计数立即再次触发冻结
        updates[VERIFY_REDO_COUNT_FIELD] = 0
        # add-verdict-credibility-gate / design D6：inconclusive 循环计数同样
        # 随人工解冻清零——人工处置后 blocked-env 轮次从 1 重新计数（与
        # _verify_redo_count 同语义，B6「恢复尊重暂停标记」闭环的人工侧）。
        updates[INCONCLUSIVE_ATTEMPTS_FIELD] = 0
        # add-verify-parallel-backoff / design D2：降档并行度与
        # _inconclusive_attempts 完全同生命周期——人工解冻同轮清 override，
        # 重验从配置并行度重新开始，不留降档残留。
        updates["_verify_parallel_override"] = None
        # add-blocked-reverify-lane D3：env 阻塞轮次随人工解冻清零——人工处置
        # 后 env 轮次从 1 重新计数（与 _verify_redo_count/_inconclusive_attempts
        # 人工解冻清零同款，同一原子写）。其余中间转换（admin 处置复位、daemon
        # 恢复、fix 链）一律不清零，保证「第 2 次阻塞即冻结转人工」可达。
        updates[ENV_BLOCK_ROUNDS_FIELD] = 0
        # evo-verify-infra-retry-lane D2：infra-retry 专用连续重派计数随人工解冻
        # 清零——否则达预算升级冻结→人工解冻后首轮 prepare 失败即立即再升级，
        # 「缺省 2 次廉价重派」预算不可再得（与 ENV_BLOCK_ROUNDS_FIELD 同款
        # 「同一原子写清零」；其余中间转换一律不清零）。
        updates[VERIFY_INFRA_RETRY_STREAK_FIELD] = 0
        # fix-redispatch-loop-governance D3.5：同因重派熔断计数随人工解冻清零——
        # 人工处置后同因重试从零起算（与 VERIFY_REDO_COUNT_FIELD /
        # _inconclusive_attempts / ENV_BLOCK_ROUNDS_FIELD 同款「同一原子写清零」）。
        updates[REDISPATCH_SAME_CAUSE_STREAK_FIELD] = 0
        updates["_redispatch_cause_fp"] = None
        # 全场景同因失败哨计数随人工解冻清零（与上方各验证计数同一原子写）：
        # admin 按推荐动作「拨回 implemented 重验」/解冻人工修复后，同因失败
        # 观察窗从 1 重新起算；否则解冻后首轮同因失败 attempts 即 ≥4 立即
        # 再次 blocked，「连续 3 轮」承诺落空。
        updates[UNIFORM_FAIL_ATTEMPTS_FIELD] = 0
        # fix-recovery-path-blockers D4：场景原地修复预算耗尽轮次随人工解冻
        # 清零——人工解冻是唯一人工裁决出口（对齐 _env_block_rounds 既有语义），
        # 解冻后重新获得「首次耗尽排程重验 → 再次耗尽升级」的完整体验；其余
        # 中间转换（admin 处置复位 / daemon 恢复 / fix 链）一律不清零。
        updates[SCENARIO_REPAIR_EXHAUSTED_FIELD] = 0
        updates["error"] = None
        updates[FROZEN_UNTIL_FIELD] = None
        # update_spec 的单条目写语义在此显式展开（与 freeze_spec 同款：
        # _mutate_locked + _apply_updates_entry + _log_update_applied，无第二份
        # 实现）：锚点复核 MUST 在 .STATE.md.lock 锁内基于最新条目进行，故不能
        # 走 update_spec 的盲写封装。锁内不输出日志（持锁窗口不含 I/O），
        # 复核失败经 anchor_recheck 带出锁外留痕。
        applied: dict = {}
        anchor_recheck: dict = {}

        def _mutate(specs):
            if resume_anchors:
                # 快照锚点复核口径收敛到共享 helper（code-review 6e8fb8190679）；
                # 失败策略（放弃锚点回写、解冻照常推进）留在本调用方分支。
                fresh, matched = self._anchor_recheck_locked(
                    specs, spec_name, entry, ("branch", "implementer_run")
                )
                if matched:
                    updates.update(resume_anchors)
                else:
                    anchor_recheck["snapshot"] = entry
                    anchor_recheck["fresh"] = fresh
            found = self._apply_updates_entry(specs, spec_name, updates, applied)
            return found, found

        if not self._mutate_locked(_mutate):
            self.logger.warning("state_machine", f"SPEC not found: {spec_name}")
            return False
        if anchor_recheck:
            _snap = anchor_recheck["snapshot"]
            _fresh = anchor_recheck["fresh"]
            self.logger.warning(
                "state_machine",
                f"Unfreeze anchor recheck: spec '{spec_name}' 的 branch/"
                f"implementer_run 锚点在续做判定后被并发改写（快照 branch="
                f"{_snap.get('branch')!r}/implementer_run="
                f"{_snap.get('implementer_run')!r} → 最新 branch="
                f"{_fresh.get('branch')!r}/implementer_run="
                f"{_fresh.get('implementer_run')!r}）——放弃锚点回写，"
                f"防陈旧锚点复活",
            )
        self._log_update_applied(spec_name, applied)
        return True

    def add_spec(self, spec_name: str, entry: dict) -> bool:
        """Add a new SPEC entry. Returns False if already exists.

        原子性（D1/D2）：存在性查重与插入在同一把 ``.STATE.md.lock`` 内完成。
        查重与写盘分处锁外时，两个并发 add 会各持「尚无该条目」的快照整体回写，
        后写者把先写者刚注册的 spec 整条抹掉（同源丢失更新）。

        入参 ``entry`` 不会被原地改写：默认字段补齐在内部副本上进行，
        调用方传入的 dict 保持原样。
        """
        added: dict = {}

        def _mutate(specs):
            if spec_name in specs:
                return False, False
            # 先拷贝再补齐默认字段：MUST NOT 原地改写调用方传入的 entry
            # （否则共享 dict 的调用方会在返回后看到隐式注入的键）。
            # 注意副本须换名（闭包内同名重绑定会让 entry 变局部名，RHS 求值
            # 即 UnboundLocalError）。
            new_entry = dict(entry)
            new_entry.setdefault("status", SpecStatus.DRAFTED)
            new_entry.setdefault("priority", 5)
            new_entry.setdefault("created", datetime.now(timezone.utc).isoformat())
            new_entry.setdefault("updated", datetime.now(timezone.utc).isoformat())
            new_entry.setdefault("implementer_run", None)
            new_entry.setdefault("tester_run", None)
            new_entry.setdefault("branch", None)
            new_entry.setdefault("error", None)
            new_entry.setdefault("depends_on", None)
            new_entry.setdefault("reviewer_run", None)
            new_entry.setdefault("_review_attempts", 0)

            specs[spec_name] = new_entry
            added["status"] = new_entry["status"]
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

    # ── 归档清单迁出原语（add-archive-state-migration D2）──────────────

    def _render_archive_entry(self, spec_name: str, entry: dict) -> str:
        """把单个条目渲染为清单小节文本（``### name`` + 字段行，含结尾空行）。"""
        lines = [f"### {_escape_state_value(spec_name)}"]
        for key, val in entry.items():
            if val is None:
                val = "null"
            lines.append(f"- {key}: {_escape_state_value(val)}")
        lines.append("")
        return "\n".join(lines) + "\n"

    def _render_archive_manifest(self, entries: Dict[str, dict]) -> str:
        """把整个清单渲染为完整文件文本（固定头 + 按名排序的小节）。"""
        parts = [_ARCHIVE_MANIFEST_HEADER]
        for name in sorted(entries):
            parts.append(self._render_archive_entry(name, entries[name]))
        return "".join(parts)

    def _atomic_write_text(self, path: Path, content: str):
        """temp 写盘 + fsync + rename 的原子文本替换（原子写机制单点实现，
        _write_all_locked 亦复用本方法落盘 STATE.md）。"""
        parent = path.parent
        tid = threading.get_ident()
        tmp_fd, tmp_path_str = tempfile.mkstemp(
            prefix=f".{path.name}.{os.getpid()}.{tid}.",
            suffix=".tmp",
            dir=str(parent),
        )
        tmp_path = Path(tmp_path_str)
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.rename(str(tmp_path), str(path))
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    def _upsert_archive_entry_locked(self, spec_name: str, entry: dict):
        """清单条目幂等写入（调用方 MUST 已持有 .STATE.md.lock）。

        - 同名小节不存在 → 追加写入（单次 write + fsync；文件缺失时先写固定头）；
        - 同名小节已存在 → 解析既有清单后整体重写覆盖（消除重复小节，
          add-archive-state-migration design D2 幂等语义）。

        写失败（OSError）向上抛出，由 ``evict_spec`` 捕获后保持 STATE.md 不动。
        """
        path = self._archive_path
        if path.exists():
            existing = StateParser.parse(path, self.logger)
            if spec_name in existing:
                existing[spec_name] = entry
                self._atomic_write_text(path, self._render_archive_manifest(existing))
                return
        header = _ARCHIVE_MANIFEST_HEADER if not path.exists() else ""
        with open(path, "a", encoding="utf-8") as f:
            if header:
                f.write(header)
            elif path.stat().st_size > 0:
                # 既有内容未以换行收尾（外部手改）时补分隔，防止小节粘连
                with open(path, "rb") as rf:
                    rf.seek(-1, os.SEEK_END)
                    if rf.read(1) != b"\n":
                        f.write("\n")
            f.write(self._render_archive_entry(spec_name, entry))
            f.flush()
            os.fsync(f.fileno())

    def evict_spec(self, spec_name: str, archived_by: str = "ui") -> dict:
        """把 STATE.md 中该 SPEC 的条目迁出至归档清单 ``.fenix/STATE.archive.md``。

        迁出原语（add-archive-state-migration design D2）：在 ``.STATE.md.lock``
        的 flock 内原子完成「先清单、后活跃」两步——

        1. 锁内 ``read_all`` 重读校验：条目不在 → ``found: False`` 幂等返回
           （已迁出/从未存在，不报错、不改清单）；非终态（非 done/pushed）→
           拒绝迁出；
        2. 先把条目（+ ``archived_at`` UTC ISO 与 ``archived_by``）写入清单
           （同名幂等覆盖，写入含 fsync）；
        3. 再经 ``_write_all_locked`` 重写 STATE.md 移除该条目。

        顺序理由：崩溃/异常窗口只允许出现「清单已有 + 活跃仍有」的双源中间态
        （读侧活跃优先、存量回填下一轮收敛），绝不允许「活跃已删 + 清单没有」
        的丢条目态。清单写入失败（OSError）→ 返回失败且 STATE.md 不动；
        STATE.md 重写失败（OSError）→ 条目留活跃、清单已有副本（无害中间态，
        存量回填收敛）。

        Args:
            spec_name: 要迁出的 SPEC 名。
            archived_by: 迁出路径溯源，取值 ``auto``/``ui``/``cli``/``backfill``
                之一（编程错误直接 ValueError，不落失败 dict）。

        Returns:
            {"found": bool, "ok": bool, "archived_at": str|null,
             "archived_by": str|null, "error": str|null}
        """
        if archived_by not in ARCHIVED_BY_PATHS:
            raise ValueError(
                f"archived_by 仅允许 {ARCHIVED_BY_PATHS}，得到: {archived_by!r}"
            )
        not_found = {
            "found": False,
            "ok": False,
            "archived_at": None,
            "archived_by": None,
            "error": f"spec not in STATE.md (already evicted or unknown): {spec_name}",
        }
        lock_path = self._lockfile
        with open(lock_path, "w") as lock_f:
            fcntl.flock(lock_f, fcntl.LOCK_EX)
            try:
                specs = self.read_all()
                if spec_name not in specs:
                    # 幂等：迁出已迁出/未知 SPEC 不报错、不改清单
                    return not_found
                entry = specs[spec_name]
                status = entry.get("status")
                if status not in TERMINAL_SPEC_STATUSES:
                    return {
                        "found": True,
                        "ok": False,
                        "archived_at": None,
                        "archived_by": None,
                        "error": f"仅终态 spec（done/pushed）可迁出，当前状态: {status}",
                    }
                evicted = dict(entry)
                archived_at = datetime.now(timezone.utc).isoformat()
                evicted["archived_at"] = archived_at
                evicted["archived_by"] = archived_by
                try:
                    self._upsert_archive_entry_locked(spec_name, evicted)
                except OSError as e:
                    # 清单写入失败 → 条目留在 STATE.md（D2 顺序天然保证不丢）
                    self.logger.error(
                        "state_machine",
                        f"归档清单写入失败，条目保留在 STATE.md: {spec_name}: {e}",
                    )
                    return {
                        "found": True,
                        "ok": False,
                        "archived_at": None,
                        "archived_by": None,
                        "error": f"归档清单写入失败: {e}",
                    }
                specs.pop(spec_name)
                try:
                    self._write_all_locked(specs)
                except OSError as e:
                    # STATE.md 重写失败 → 条目留活跃、清单已有副本
                    #（无害双源中间态，存量回填下一轮收敛）
                    self.logger.error(
                        "state_machine",
                        f"STATE.md 重写失败，条目保留待回填收敛: {spec_name}: {e}",
                    )
                    return {
                        "found": True,
                        "ok": False,
                        "archived_at": archived_at,
                        "archived_by": archived_by,
                        "error": f"STATE.md 重写失败（条目保留，待回填收敛）: {e}",
                    }
                self.logger.info(
                    "state_machine",
                    f"Evicted SPEC '{spec_name}' to archive manifest",
                    {"archived_by": archived_by, "archived_at": archived_at},
                )
                return {
                    "found": True,
                    "ok": True,
                    "archived_at": archived_at,
                    "archived_by": archived_by,
                    "error": None,
                }
            finally:
                fcntl.flock(lock_f, fcntl.LOCK_UN)

    def remove_archived_entry(self, spec_name: str) -> bool:
        """从归档清单移除该 SPEC 的小节（软删除专用）。返回是否确有移除。

        在 ``.STATE.md.lock`` 的 flock 内执行（与迁出/回填的清单写入同锁，
        避免并发竞态，add-archive-state-migration design D6）。清单不存在或
        无该小节时返回 False（幂等，不动文件）。
        """
        lock_path = self._lockfile
        with open(lock_path, "w") as lock_f:
            fcntl.flock(lock_f, fcntl.LOCK_EX)
            try:
                path = self._archive_path
                if not path.exists():
                    return False
                entries = StateParser.parse(path, self.logger)
                if spec_name not in entries:
                    return False
                entries.pop(spec_name)
                self._atomic_write_text(path, self._render_archive_manifest(entries))
                self.logger.info(
                    "state_machine",
                    f"Removed archived entry '{spec_name}' from manifest",
                )
                return True
            finally:
                fcntl.flock(lock_f, fcntl.LOCK_UN)

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

    def _finish_transition(self, outcome: dict, result: bool, spec_name: str,
                           new_status: str, *, label: str, verb: str,
                           trigger_run_id: str | None = None,
                           agent_type: str | None = None,
                           channel: str = "auto") -> bool:
        """transition / transition_gate 共用的锁外出口分支（code-review 14e0ba4fccce）。

        ``_transition_atomic`` 返回后的 missing / idempotent / invalid /
        stripped / result 五个出口此前在两个方法里各复制一份约 50 行的判定
        与留痕逻辑，仅查表（由调用方在锁内消费）与日志文案不同——stripped
        假成功消歧（c809d1296efc）等修复须双点同步落笔，单侧修补易漏改另
        一侧造成行为漂移，故收敛于此。文案差异以两个参数带入：

        - ``label``：正文文案中的转换名（``"transition"`` /
          ``"gate transition"``），用于 idempotent / invalid / stripped 行；
          成功行取 ``label.capitalize()`` 前缀（``"Transition"`` /
          ``"Gate transition"``，后者为时间轴正则刻意不命中的前缀，见
          ``transition_gate`` docstring）；
        - ``verb``：missing 行的连字形态（``"transition"`` /
          ``"gate-transition"``，历史文案即连字，逐字保留防断言失配）。

        日志级别 / 通道（``state_machine``）/ 结构化 context /
        ``_log_update_applied`` 留痕写点与各出口返回值在两方法间本就逐字
        一致，此处不引入任何行为变化。
        """
        if outcome.get("missing"):
            self.logger.warning(
                "state_machine", f"Cannot {verb} nonexistent SPEC: {spec_name}"
            )
            return False

        old_status = outcome.get("old_status")

        # 幂等自迁移短路（fix-daemon-lifecycle-races D4）：new_status == old_status
        # 视为幂等自迁移，INFO 降级直接返回 True，不进入转换表（VALID_TRANSITIONS /
        # GATE_TRANSITIONS）拒绝分支。历史 ERROR 噪声（done→pushed 双路径并发必触发
        # 的 pushed→pushed 假告警）由此消噪；真实非法迁移（如 implemented→verified）
        # 仍记 ERROR。依赖返回 False 阻断重复副作用的调用点须改为前置状态判断或
        # 接受幂等覆盖：全库核查见 engine.py:332（done→done 时 total_duration 重算
        # 覆盖为同值，幂等无害）与 dispatch.py:480-503（已有 cur_status !=
        # "implementing" 前置判断的同型防护）。判定在锁内基于最新状态完成，此处
        # 只负责留痕。
        if outcome.get("idempotent"):
            self.logger.info(
                "state_machine",
                f"Idempotent {label}: {spec_name} {old_status} → {new_status} "
                f"(already in state, skipped)",
            )
            return True

        # Validate transition（判定已在锁内完成，此处留痕）
        if outcome.get("invalid"):
            self.logger.error(
                "state_machine",
                f"Invalid {label}: {spec_name} {old_status} → {new_status}",
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
                f"Frozen SPEC '{spec_name}': {label} {old_status} → {new_status} "
                f"stripped — manual freeze intact, status unchanged",
            )
            return False

        if result:
            self.logger.info(
                "state_machine",
                f"{label.capitalize()}: {spec_name} {old_status} → {new_status}",
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
        # 锁外五出口（missing/idempotent/invalid/stripped/result）判定与留痕
        # 收敛于 _finish_transition，与 transition_gate 仅查表与文案不同。
        return self._finish_transition(
            outcome, result, spec_name, new_status,
            label="transition", verb="transition",
            trigger_run_id=trigger_run_id, agent_type=agent_type, channel=channel,
        )

    def is_valid_transition(self, from_status: str, to_status: str) -> bool:
        """Check if a transition is legal."""
        return to_status in VALID_TRANSITIONS.get(from_status, [])

    def transition_gate(self, spec_name: str, new_status: str,
                        *, trigger_run_id: str | None = None,
                        agent_type: str | None = None,
                        channel: str = "auto") -> bool:
        """门禁自动路径专用转换（verifier-judgment-integrity D7 逃生门）。

        仅允许 GATE_TRANSITIONS 中声明的转换（口径以模块常量处注释为准、
        勿在此复述防再漂移：VERIFIED→TESTING、BLOCKED→TESTING），分别
        服务 _on_spec_verified 门禁拦截后的自动回退与 blocked 直达重验。
        人工路径（直接调 transition）受 VALID_TRANSITIONS 约束，这两个
        转换仍被拒，不得绕过。返回 False 表示非门禁允许的转换或 spec 不存在。

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
        # 锁外五出口（missing/idempotent/invalid/stripped/result）判定与留痕
        # 收敛于 _finish_transition，与 transition 仅查表与文案不同。
        return self._finish_transition(
            outcome, result, spec_name, new_status,
            label="gate transition", verb="gate-transition",
            trigger_run_id=trigger_run_id, agent_type=agent_type, channel=channel,
        )

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
        return sorted(specs, key=_spec_sort_key)

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
          preserve（D4）改判定：分支存在且相对解析基线有未合并提交 → 保留
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
                            # 内嵌「原状态 implemented」子串（code-review a2cf023df335）：
                            # dashboard/CLI 解冻按 parse_orig_status 还原目标，缺失
                            # 时回退 ready——testing 冻结的实现已合并，误恢复 ready
                            # 会派 implementer 从头实现并劫持 branch 字段（与下方
                            # testing→implemented 的非超限恢复路径同口径）。
                            error=(
                                f"{FREEZE_ERROR_PREFIX}原状态 implemented · "
                                "重启重验超限，等待人工裁决"
                            ),
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
                    # 保留（实现的身份事实，验证不重做实现）。
                    # code-review 3926b50faeed：SPEC 在恢复窗口内被并发删除时
                    # update_spec 返回 False——不计入 recovered（recovered 口径
                    # 只收「确实恢复了状态」的 spec；spec 在场时返回值恒 True，
                    # 既有行为不变），与下方清空重建路径同型守卫
                    retested = self.update_spec(
                        name,
                        {
                            "status": SpecStatus.IMPLEMENTED,
                            "error": f"Recovered from interrupted state: {status}",
                            "tester_run": None,
                            "_retry_count": 0,
                            "_merge_fp": None,
                            "_merge_streak": 0,
                            REDISPATCH_SAME_CAUSE_STREAK_FIELD: 0,
                            "_redispatch_cause_fp": None,
                        },
                    )
                    if retested:
                        recovered.append(name)
                    continue
                elif status == SpecStatus.REVIEWING:
                    # 评审中断恢复：回退 drafted，清空评审 run 引用与尝试计数，
                    # 使其重新进入晋升链（软化与两道 lint 幂等，分流重新判定）。
                    # 评审者对 SPEC 目录的修补被保留（不还原）。
                    # code-review 3926b50faeed：同 TESTING 分支守卫——SPEC 在
                    # 恢复窗口内被并发删除（update_spec 返回 False）不计入
                    # recovered；spec 在场时返回值恒 True，既有行为不变
                    redrafted = self.update_spec(
                        name,
                        {
                            "status": SpecStatus.DRAFTED,
                            "error": f"Recovered from interrupted state: {status}",
                            "reviewer_run": None,
                            "_review_attempts": 0,
                        },
                    )
                    if redrafted:
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
                cleared = self.update_spec(
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
                        REDISPATCH_SAME_CAUSE_STREAK_FIELD: 0,
                        "_redispatch_cause_fp": None,
                    },
                )
                # code-review 1b4fc51aac73：SPEC 在恢复窗口内被并发删除时
                # update_spec 返回 False——不计入 recovered（recovered 口径
                # 只收「确实恢复了状态」的 spec；spec 在场时返回值恒 True，
                # 既有行为不变）
                if cleared:
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
        - 锚点（branch/implementer_run）回写在 ``.STATE.md.lock`` 锁内以最新
          条目复核（与 freeze_spec 同一口径，code-fix b609ecf63750）：快照
          锚点在 re-merge 的 git 窗口内被并发改写时放弃回写并 WARNING，
          推进本身不回滚（滞留 implementing 会反复重试已合并分支）。
        - 收口副作用（依赖接线，tasks 4.2）：``remerge_callback(spec_name)``
          由 fenixd 注入 PMEngine 侧实现（_clear_dispatch_conflict /
          _sync_task_progress / _reconcile_impl_budget / consume_legacy），
          缺省 None 时行为与旧版逐字节一致。verifier 派发由 boot 的
          event_bus.full_scan() 兜底，不在此复刻 _enqueue_front。

        Returns: True 表示 re-merge 成功并已推进 implemented；False 表示
        re-merge 失败（调用方清除标记后回落保留续做路径，spec 不滞留
        implementing），或 SPEC 已在本方法的 git 窗口内被并发删除
        （code-review 1b4fc51aac73：跳过收口回调与成功日志，不计成功）。
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
            # [fenix-ignore:143b2435ac7b] 非缺陷：2015 行元组解包只给新名字赋值、不重绑 merge_info，其仍是 MergeConflictInfo 对象，getattr 读到真实 spec_dir_inflight（test_state_machine_recovery_remerge_keeps_marker 已覆盖此分支）
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
        # re-merge 成功：推进 implemented，收口字段对齐 repair re-merge 路径。
        # 锚点回写（implementer_run/branch）在 .STATE.md.lock 锁内以最新条目
        # 复核（与 freeze_spec code-fix d266d19c4860 / unfreeze_spec
        # fenix-fix f5a17d596717 同一口径，code-fix b609ecf63750）：上方 entry
        # 是 recover_interrupted 经 get_by_status 取的锁外快照，与本写之间隔着
        # merge_back_from_branch 的 git 子进程（窗口可达秒级），期间
        # dashboard/admin 等其他写者若已改写或清空锚点，快照旧值会在本写中
        # 复活。合并已不可逆，复核不一致时不回滚推进（回滚会让「仅剩合并」的
        # spec 滞留 implementing 反复重试已合并分支），仅放弃快照锚点回写、
        # 保留锁内最新值并 WARNING 留痕。
        updates: dict = {
            "status": SpecStatus.IMPLEMENTED,
            "error": None,
            "_retry_count": 0,
            "_merge_fp": None,
            "_merge_streak": 0,
            REDISPATCH_SAME_CAUSE_STREAK_FIELD: 0,
            "_redispatch_cause_fp": None,
            "_repair_round": 0,
            "_repair_merge_error": None,
            "_repair_awaiting_remerge": False,
        }
        applied: dict = {}
        anchor_recheck: dict = {}

        def _mutate(specs):
            # 快照锚点复核口径收敛到共享 helper（code-review 6e8fb8190679）；
            # 失败策略（放弃锚点回写、推进不回滚）留在本调用方分支。
            fresh, matched = self._anchor_recheck_locked(
                specs, name, entry, ("branch", "implementer_run")
            )
            if not fresh:
                # SPEC 已在 re-merge 的 git 窗口内被并发删除（code-review
                # 1b4fc51aac73）：缺失事实带出锁外，收口出口据此跳过假成功
                anchor_recheck["missing"] = True
            if matched:
                updates["implementer_run"] = entry.get("implementer_run")
                updates["branch"] = branch
            else:
                anchor_recheck["snapshot"] = entry
                anchor_recheck["fresh"] = fresh
            found = self._apply_updates_entry(specs, name, updates, applied)
            return found, found

        if not self._mutate_locked(_mutate):
            if anchor_recheck.get("missing"):
                # SPEC 已被并发删除：不记假成功、不触发收口副作用——此前本
                # 出口只记一条 SPEC not found warning 后无条件执行
                # remerge_callback/consume_legacy 并输出「成功 → implemented」
                # 日志返回 True（缺失 spec 不会被本路径复活、无状态损坏，但
                # 审计日志与下游副作用失真）。返回 False 交调用方按缺失处置。
                self.logger.warning(
                    "state_machine",
                    f"SPEC not found: {name}（恢复期 re-merge 窗口内被并发删除）"
                    f"— 跳过 remerge 收口回调与 consume_legacy，不计成功",
                )
                return False
            self.logger.warning("state_machine", f"SPEC not found: {name}")
            # code-review 90fa33787d14：历史「not found 落入假成功」残留出口——
            # 仅当 _anchor_recheck_locked 判 fresh（specs 有条目）而
            # _apply_updates_entry 判 not found（同一把锁内读同一 specs 字典）
            # 同时成立时可达，实际不可达；显式 return False 与上方 missing 出口
            # 及 docstring「True 表示 re-merge 成功并已推进 implemented」口径
            # 一致，避免不变式被后续改动打破时复活为假成功（跳过收口回调与
            # consume_legacy，不计成功）。
            return False
        elif anchor_recheck:
            _snap = anchor_recheck["snapshot"]
            _fresh = anchor_recheck["fresh"]
            self.logger.warning(
                "state_machine",
                f"Recovery remerge anchor recheck: spec '{name}' 的 branch/"
                f"implementer_run 锚点在恢复期 re-merge 期间被并发改写（快照 "
                f"branch={_snap.get('branch')!r}/implementer_run="
                f"{_snap.get('implementer_run')!r}，最新 branch="
                f"{_fresh.get('branch')!r}/implementer_run="
                f"{_fresh.get('implementer_run')!r}）——放弃快照锚点回写，"
                f"以最新条目为准推进 implemented",
            )
        else:
            self._log_update_applied(name, applied)
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
           只剩分支时命中；候选经「已含基线」优先排序，零提交候选已剔除）。
        第三层命中时走既有 rev-list 非空闸门与 resolve_resume_site 载体处置。

        闸门基线经共享解析器 ``resolve_base_branch`` 取（evo-fix-resume-
        base-branch-portability 2.1）：origin/HEAD → 本地 main → master →
        回退 "main"，不再硬编码 ``main``——非 main 主干仓库（master 主干
        无 remote）此前 rev-list 恒非零退出、必走清空重建。

        Returns: ``(resolved_branch, wt)`` 判定通过（分支可解析、相对解析
        基线有未合并提交、载体可用）；``(branch, None)`` 分支可解析且有未合并
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
            # 候选已按「已含基线」优先排序、零提交候选剔除（D2/tasks 2.5）。
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
            # 分支可解析 + 相对解析基线有未合并提交（rev-list --count > 0）。
            # 基线经共享解析器取（evo-fix-resume-base-branch-portability
            # 2.1）：origin/HEAD → 本地 main → master → 回退 "main"，非
            # main 主干仓库不再恒走清空重建。解析器自身吞异常回退常量、
            # 不抛错；分支不存在时 rev-list 非零退出 → 走现行清空路径。
            base = resolve_base_branch(project_root)
            ahead = subprocess.run(
                ["git", "-C", str(project_root), "rev-list", "--count", f"{base}..{branch}"],
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

        判定：branch 在册、分支可解析、且 rev-list 相对解析基线（共享解析器
        ``resolve_base_branch``）非空（有未合并提交）→ 保留。载体处置经
        worktree_manager 三态
        单源查询（is_available）：在场原地登记（受清理豁免）；缺失在既有分支
        上重建 worktree；不可用降级清空重建并 WARNING。

        锚点回写在 ``.STATE.md.lock`` 锁内以最新条目复核（与 freeze_spec 同一
        口径，code-fix b609ecf63750）：快照锚点在保留判定的 git 窗口内被并发
        改写时放弃本写并 WARNING，返回 False 回落调用方清空重建路径。

        Returns: True 表示已保留并写入恢复续做标记（调用方计入 recovered）；
        False 表示判定未通过、锚点复核不一致（并发改写），或 SPEC 已在本方法
        的 git 窗口内被并发删除（code-review 1b4fc51aac73，不计入 recovered）。
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
        updates: dict = {
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
            REDISPATCH_SAME_CAUSE_STREAK_FIELD: 0,
            "_redispatch_cause_fp": None,
        }
        # 锚点回写（implementer_run/branch）在 .STATE.md.lock 锁内以最新条目
        # 复核（与 freeze_spec code-fix d266d19c4860 / unfreeze_spec
        # fenix-fix f5a17d596717 同一口径，code-fix b609ecf63750）：上方 entry
        # 是 recover_interrupted 经 get_by_status 取的锁外快照，与本写之间隔着
        # _resolve_preserved_branch 的 git 子进程（窗口可达秒级），期间
        # dashboard/admin 等其他写者若已改写或清空锚点，快照旧值会在本写中
        # 复活，续做判定拿到陈旧 run 锚。update_spec 的单条目写语义在此显式
        # 展开（_mutate_locked + _apply_updates_entry + _log_update_applied）：
        # 复核不一致则放弃本写并 WARNING 留痕，返回 False 回落调用方清空重建
        # 路径（该路径只写常量、无快照锚点回写，不会复活陈旧值）。
        applied: dict = {}
        anchor_recheck: dict = {}

        def _mutate(specs):
            # 快照锚点复核口径收敛到共享 helper（code-review 6e8fb8190679）；
            # 失败策略（锚点不一致整体放弃本写）留在本调用方分支。
            fresh, matched = self._anchor_recheck_locked(
                specs, name, entry, ("branch", "implementer_run")
            )
            if not fresh:
                # SPEC 已在保留判定的 git 窗口内被并发删除（code-review
                # 1b4fc51aac73）：缺失事实带出锁外，收口出口据此跳过假成功
                anchor_recheck["missing"] = True
            if matched:
                found = self._apply_updates_entry(specs, name, updates, applied)
            else:
                anchor_recheck["snapshot"] = entry
                anchor_recheck["fresh"] = fresh
                found = False
            return found, found

        if not self._mutate_locked(_mutate):
            if anchor_recheck.get("missing"):
                # SPEC 已被并发删除：不再走下方「SPEC not found → return True」
                # 假成功出口（否则调用方把已删 spec 计入 recovered，与 docstring
                # 「True 表示已保留并写入恢复续做标记」相悖）。返回 False。
                self.logger.warning(
                    "state_machine",
                    f"SPEC not found: {name}（恢复期保留判定窗口内被并发删除）"
                    f"— 不计入 recovered",
                )
                return False
            if anchor_recheck:
                _snap = anchor_recheck["snapshot"]
                _fresh = anchor_recheck["fresh"]
                self.logger.warning(
                    "state_machine",
                    f"Recovery preserve anchor recheck: spec '{name}' 的 "
                    f"branch/implementer_run 锚点在保留判定后被并发改写（快照 "
                    f"branch={_snap.get('branch')!r}/implementer_run="
                    f"{_snap.get('implementer_run')!r}，最新 branch="
                    f"{_fresh.get('branch')!r}/implementer_run="
                    f"{_fresh.get('implementer_run')!r}）——放弃恢复续做回写，"
                    f"回落清空重建路径，以最新条目为准",
                )
                return False
            self.logger.warning("state_machine", f"SPEC not found: {name}")
            # code-review 90fa33787d14：历史「not found → 假成功返回 True」
            # 残留出口——仅当 _anchor_recheck_locked 判 fresh（specs 有条目）
            # 而 _apply_updates_entry 判 not found（同一把锁内读同一 specs
            # 字典）同时成立时可达，实际不可达；显式 return False 与上方
            # missing 出口及 docstring「True 表示已保留并写入恢复续做标记」
            # 口径一致，避免不变式被后续改动打破时复活假成功（误把已删 spec
            # 计入 recovered）。
            return False
        self._log_update_applied(name, applied)
        return True
