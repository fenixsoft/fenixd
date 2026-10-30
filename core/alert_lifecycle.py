"""
alert_lifecycle.py — 告警生命周期闭环（add-alert-auto-resolve）。

升级告警（kind=escalation）产生后与底层 spec 状态脱钩：spec 恢复、验证通过、
到达终态都不会回写告警，管理员视图被历史噪音淹没。本模块提供纯函数判定：

  输入（告警列表、spec 状态表）→ 输出（可闭环条目及 resolve_note）

闭环语义（design D2/D3）：
  - 触发条件以告警条目的结构化 ``trigger`` 字段为准（写入时埋点，见
    pm_engine._send_human_escalation_alert）；``condition`` 枚举保守起步，
    未识别的 condition 永不自动闭环。
  - 首发仅一种 condition：``spec_terminal_or_unblocked``——关联 spec 状态
    到达终态（pushed/done）或离开 blocked 即视为解除。
  - ``handled=True`` 的条目一律跳过（人工处理记录不可覆盖）。
  - 无 ``trigger`` 字段的存量告警按 signal_type ∈ {verify_fail_escalation,
    blocked_stuck} + spec 字段存在推断为同一 condition（存量回填，design D4），
    resolve_note 注明「存量回填」。
  - evo-add-signal-subject-terminal-close：spec 附着条件族的 kind=signal
    记录（blocked_stuck 等）同样走上述主体终态判定——盘点 pending 过滤与
    auto_resolve 写回的 kind 门同步打开（design D2：按条件族白名单而非全部
    kind=signal，防「主体终态但仍需人工关注的信号」被误收口）；签名安静族
    （SELF_HEAL_SIGNAL_TYPES）仍按签名安静判定，语义不变。

自愈闭环语义（add-alert-self-heal-marking，infra_transient_self_healed 条件）：
  - 覆盖族注册表 ``SELF_HEAL_SIGNAL_TYPES``（daemon_errors / run_infra_failure /
    self-evolution）——基础设施瞬态族「底层故障自愈型」告警按**签名安静判定**
    收口：条目（或收敛升级的底层信号）最近复现时刻距当前时刻 ≥ 安静窗口
    （默认 1440 分钟）即视为已自愈。
  - 判定输入（告警列表、当前时刻）全部由调用方注入（``now`` / ``records``
    参数）；未注入 ``now``（既有调用方）不启用自愈判定，既有路径零变化。
  - 收敛升级（spec-less escalation 带 ``admin_run_id``）取双源锚点（D2）：
    ``admin_run_id`` 名下 disposition ＋ 同 signal_type 未收口 signal——
    MUST NOT 只锚 disposition created，否则底层风暴仍在复现时会被提前收口。
  - inconclusive_loop（env 豁免握手族）刻意不在注册表，永不自愈闭环；
    spec 附着族命中既有条件枚举时不做自愈判定（不双重判定）。

本模块不读写文件、不依赖锁——写回由 AdminStore.auto_resolve /
AdminStore.auto_self_heal 在排他锁内完成（design D6 / D3）。
"""

import math

from .timelib import from_epoch, parse_ts, to_storage

# spec 终态（与 admin_monitor._TERMINAL_SPEC_STATUSES 同口径）
TERMINAL_SPEC_STATUSES = ("done", "pushed")

# spec_delivered_adjudicated 条件的闭环终态口径（alert-noise-governance 1.4）：
# 与 TERMINAL_SPEC_STATUSES 同口径，另纳入 spec.md 场景文本的 archived 拼写
# （状态机当前不产出该值，向前兼容）。
DELIVERED_ADJUDICATED_TERMINAL_STATUSES = TERMINAL_SPEC_STATUSES + ("archived",)

# 闭环判定条件枚举（design D2）：保守起步，仅一种。
CONDITION_SPEC_TERMINAL_OR_UNBLOCKED = "spec_terminal_or_unblocked"
# spec.md 场景文本中的同义拼写，作别名兼容（同一判定，不构成新条件）
_CONDITION_ALIAS = "spec_reach_terminal_or_unblocked"
# spec_delivered_no_content 的独立裁决闭环条件（alert-noise-governance 1.4）：
# 仅当关联 SPEC 到达终态才自动闭环。MUST NOT 复用 spec_terminal_or_unblocked
# ——该条件在 evaluate_alert 仅以 blocked 为未解除出口，对非 blocked spec 一
# 律判「已解除」，而本信号产生时 SPEC 恰恰停在 ready 等待人工裁决，复用会被
# 下一轮 auto_resolve 立即闭环、告警离开人工待处理队列、人工无从看见。
CONDITION_SPEC_DELIVERED_ADJUDICATED = "spec_delivered_adjudicated"

# 存量回填（design D4）：无 trigger 字段的存量告警按 signal_type 推断 condition
BACKFILL_SIGNAL_TYPES = ("verify_fail_escalation", "blocked_stuck")

# ── 基础设施瞬态告警自愈闭环（add-alert-self-heal-marking）────────────────

# 自愈闭环条件（specs/alert-lifecycle ADDED）：签名安静判定
CONDITION_INFRA_TRANSIENT_SELF_HEALED = "infra_transient_self_healed"

# 覆盖族注册表（design D2）：基础设施瞬态族「底层故障自愈型」信号——
#   daemon_errors        fenixd 日志指纹风暴（admin_monitor._detect_daemon_errors）
#   run_infra_failure    spec-review 链路 infra 熔断（pm_engine 熔断告警）
#   self-evolution       evo 分析 run 失败（fenixd._evolution_warn 写入点实际常量）
# 收敛升级（「处置终态未收口」）signal_type 复制底层类型（daemon_errors 等），
# 已在注册表内，经 admin_run_id 双源锚点规则覆盖。
# 注册表外 signal_type 永不自愈闭环（保守缺省不变）；inconclusive_loop（env
# 豁免握手族）刻意不在册——其出口是人工裁决（与 _SIGNAL_CONDITIONS 处注释
# 同口径），无论安静多久都不自动收口。
SELF_HEAL_SIGNAL_TYPES = ("daemon_errors", "run_infra_failure", "self-evolution")

# 默认安静窗口（design D4）：1440 分钟盖过跨日同刻复发节律（实证指纹以
# ≈24h 间隔复发一次）——「最后一次复发后一整个复发周期无复现」才收口，
# 避免收口后立即重开。可配 admin.self_heal_quiet_minutes（脏值回退本缺省）。
DEFAULT_SELF_HEAL_QUIET_MINUTES = 1440

# 自愈写回独立标识（design D3）：并列既有 AUTO_RESOLVE_BY，不复用不改其语义
AUTO_SELF_HEAL_BY = "auto-self-heal"

# 自动闭环标注（design D3）
AUTO_RESOLVE_BY = "auto-resolve"

# signal_type → condition 映射（写入时埋点用）。后续新告警类型按需在此扩展，
# 未列出的类型不写 trigger、永不自动闭环（保守默认）。
# verify_fail_escalation / blocked_stuck 均属 spec_terminal_or_unblocked 类
# （design D2）：前者由 pm_engine 升级闸门产生，后者经 admin_monitor 升级人工
# 产生——两条写入管道都经 attach_trigger 统一埋点。
# spec_content_missing（add-spec-content-integrity-gate D4）：派发前内容完整性
# 闸门命中产生；spec 补内容解冻离开 blocked（或到达终态）即自动闭环。
# spec_delivered_no_content（alert-noise-governance 1.4）：内容闸门「已交付
# 未落盘」分类产生（spec_integrity.SPEC_DELIVERED_NO_CONTENT_SIGNAL），独立
# 条件 spec_delivered_adjudicated——仅终态闭环（信号产生时 SPEC 停在 ready
# 待裁决，见条件常量处注释）；「补 tasks.md 归档凭据」裁决路径的告警收口为
# 人工 handled（本模块只读状态表不读目录，不承诺「补内容即自动闭环」）。
# inconclusive_loop（fix-env-exemption-exit-reachability 4.3）：env 豁免握手
# 停车族刻意不接入本枚举——其出口是人工裁决（授予豁免/修环境重置/放弃，
# adjudication_choices 注册表），任何一种都不可由状态表字段自动判定达成
# （「已豁免」是 DISPOSITION 台账事实而非状态迁移），按保守缺省不写 trigger、
# 永不自动闭环；闭环一律走人工处置后的 alert-resolve handled 收口。
_SIGNAL_CONDITIONS = {
    "verify_fail_escalation": CONDITION_SPEC_TERMINAL_OR_UNBLOCKED,
    "blocked_stuck": CONDITION_SPEC_TERMINAL_OR_UNBLOCKED,
    "spec_content_missing": CONDITION_SPEC_TERMINAL_OR_UNBLOCKED,
    "spec_delivered_no_content": CONDITION_SPEC_DELIVERED_ADJUDICATED,
    # 自愈族（add-alert-self-heal-marking 1.2）：登记进枚举使既有
    # attach_trigger 写入点自动埋点（daemon_errors 升级、run_infra_failure
    # 熔断、self-evolution）。该 condition 在既有 _recognized 集合之外——
    # 既有 spec 附着判定路径不会误消费它，evaluate_alert 内由自愈分支承接
    # （spec 附着族命中既有条件枚举时不双重判定）。
    "daemon_errors": CONDITION_INFRA_TRANSIENT_SELF_HEALED,
    "run_infra_failure": CONDITION_INFRA_TRANSIENT_SELF_HEALED,
    "self-evolution": CONDITION_INFRA_TRANSIENT_SELF_HEALED,
    # instant_fail_storm（evo-instant-fail-storm-alert-closeout 1.1）：秒挂
    # 风暴升级告警接入终态收口，条件与 spec_delivered_no_content 同族
    # （spec_delivered_adjudicated）——terminal-only：仅 pushed/done/archived
    # 才 resolved。MUST NOT 挂 spec_terminal_or_unblocked：该条件对非
    # blocked spec 一律判「已解除」（evaluate_alert 仅以 blocked 为未解除
    # 出口），而本信号产生时 SPEC 正处秒挂冷却期（非终态在途），挂上去会被
    # 下一轮 auto_resolve 立即闭环、冷却告警失效，「秒挂风暴升级」失去存在
    # 意义。冷却到期自动恢复不依赖本告警收口（is_instant_fail_cooldown
    # 独立判定），告警只承载人工关注面。
    "instant_fail_storm": CONDITION_SPEC_DELIVERED_ADJUDICATED,
}


def build_trigger(signal_type: str, spec_name) -> dict:
    """构造结构化触发条件描述（design D2）。

    返回 {"type", "spec", "condition"}；signal_type 未接入闭环枚举时返回
    None（调用方不写 trigger 字段，该告警保持人工闭环语义）。
    """
    condition = _SIGNAL_CONDITIONS.get(signal_type)
    if condition is None:
        return None
    return {
        "type": signal_type,
        "spec": spec_name,
        "condition": condition,
    }


def attach_trigger(entry: dict) -> dict:
    """按条目的 signal_type/spec 就地补全 trigger 字段（写入时埋点）。

    signal_type 未接入闭环枚举（或条目已带 trigger）时原样返回，供
    pm_engine / admin_monitor 各告警写入点统一复用。
    """
    if isinstance(entry, dict) and not entry.get("trigger"):
        trigger = build_trigger(entry.get("signal_type"), entry.get("spec"))
        if trigger:
            entry["trigger"] = trigger
    return entry


def _recognized(condition) -> bool:
    return condition in (
        CONDITION_SPEC_TERMINAL_OR_UNBLOCKED,
        _CONDITION_ALIAS,
        CONDITION_SPEC_DELIVERED_ADJUDICATED,
    )


def is_spec_attached_signal(alert: dict, backfill: bool = False) -> bool:
    """kind=signal 记录是否属 spec 附着条件族（evo-add-signal-subject-terminal-close D2）。

    口径与 escalation 判定端同一：trigger 条件已识别（_recognized），或
    （存量回填模式）无 trigger 且 signal_type ∈ BACKFILL_SIGNAL_TYPES。
    其余 kind=signal（签名安静自愈族、未登记族）不属本族——终态判定门不放行，
    仍归自愈通道或人工闭环。供 evaluate_alert kind 门与盘点通道 pending 过滤
    共用，防两侧口径漂移。
    """
    if not isinstance(alert, dict) or alert.get("kind") != "signal":
        return False
    trigger = alert.get("trigger")
    if isinstance(trigger, dict) and trigger and _recognized(trigger.get("condition")):
        return True
    return bool(
        backfill and not trigger and alert.get("signal_type") in BACKFILL_SIGNAL_TYPES
    )


# ── 自愈判定助手（add-alert-self-heal-marking 1.1）────────────────────────


def _entry_epoch(entry: dict, allow_last_seen: bool = True):
    """条目最近复现时刻 → epoch 秒；``last_seen`` 缺失回落 ``created``。

    signal 族复现时刷新 last_seen（merge_signal 既有行为）；escalation /
    disposition 不参与合并，实际回落 created。均缺失/非法/解析失败返回
    None（调用方按无锚点处理，保守不闭环）。
    """
    if not isinstance(entry, dict):
        return None
    raw = entry.get("last_seen") if allow_last_seen else None
    if not raw:
        raw = entry.get("created")
    if not isinstance(raw, str):
        return None
    dt = parse_ts(raw)
    return dt.timestamp() if dt is not None else None


def _self_heal_anchor(alert: dict, records) -> "float | None":
    """自愈判定的安静锚点 = 全部候选复现时刻的最新值（epoch 秒）。

    默认锚点：条目自身 ``last_seen`` 回落 ``created``（D1——安静证据取条目
    自身时间戳，不读日志）。

    收敛升级形态（kind=escalation 且带 ``admin_run_id``）取 D2 双源锚点：
      ① ``admin_run_id`` 名下 disposition 条目（处置记录不带 last_seen，
        回落 created）；
      ② 同 signal_type 的未收口 signal 条目——signal 记录不携带
        admin_run_id，按 signal_type＋spec 同域匹配（收敛升级 spec 为空，
        匹配 spec 同为空的 daemon 级信号）。
    锚点取全部候选（含条目自身）的最新时刻：MUST NOT 只锚 disposition
    created，否则底层风暴仍在复现（signal last_seen 持续刷新）时 escalation
    会被提前收口，违背 D4 的复发节律覆盖。
    """
    candidates = [_entry_epoch(alert)]
    rid = alert.get("admin_run_id")
    if rid and alert.get("kind") == "escalation":
        alert_spec = alert.get("spec")
        for rec in records or []:
            if not isinstance(rec, dict):
                continue
            rec_kind = rec.get("kind")
            if rec_kind == "disposition":
                if rec.get("admin_run_id") == rid:
                    candidates.append(_entry_epoch(rec, allow_last_seen=False))
            elif rec_kind == "signal":
                if rec.get("handled"):
                    continue  # 已收口信号不构成复现证据
                if rec.get("signal_type") != alert.get("signal_type"):
                    continue
                rec_spec = rec.get("spec")
                if alert_spec:
                    if rec_spec != alert_spec:
                        continue
                elif rec_spec:
                    continue  # spec 空匹配：per-spec 信号不归收敛升级锚定
                candidates.append(_entry_epoch(rec))
    valid = [c for c in candidates if c is not None]
    return max(valid) if valid else None


def _evaluate_self_heal(
    alert: dict, now, records, quiet_minutes: int, backfill: bool
):
    """infra_transient_self_healed 条件判定：签名安静 ≥ 窗口 → 自愈 note。

    返回「已自愈：…」resolve_note（附安静时长与最近复现时刻；存量回填在
    尾注注明，保持「已自愈：」前缀字面）；窗口内复现 / 无时间锚点返回
    None（保守不闭环）；脏窗口值回退 DEFAULT_SELF_HEAL_QUIET_MINUTES
    （与模块常量注释同口径）。
    """
    if isinstance(quiet_minutes, bool) or not isinstance(quiet_minutes, int):
        quiet_minutes = DEFAULT_SELF_HEAL_QUIET_MINUTES
    if quiet_minutes <= 0:
        quiet_minutes = DEFAULT_SELF_HEAL_QUIET_MINUTES
    anchor = _self_heal_anchor(alert, records)
    if anchor is None:
        return None  # 无可用时间锚点：无法判定，保持原状
    try:
        now_epoch = float(now)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(now_epoch):
        return None  # NaN/inf：无法判定，保守不闭环
    elapsed = now_epoch - anchor
    if elapsed < quiet_minutes * 60:
        return None  # 窗口内仍复现：保持待处理
    note = (
        f"已自愈：{alert.get('signal_type')} 签名已安静 "
        f"{int(elapsed // 60)} 分钟（≥ 窗口 {quiet_minutes} 分钟），"
        f"最近复现 {to_storage(from_epoch(anchor))}"
    )
    if backfill:
        note += "（存量回填）"
    return note


def _resolve_note_for_condition(spec_name: str, entry: dict, backfill: bool) -> str:
    """spec_terminal_or_unblocked 条件下的解除依据描述（spec.md：含 spec 名与终态说明）。

    evo-add-signal-subject-terminal-close 1.1：解除依据附主体终态/解除时刻，
    供审计回查（blocked_stuck 信号「主体已恢复仍虚报升级」事故的根因之一是
    收口记录无时刻可对账）。数据源为 specs 状态表 entry 的 ``updated`` 字段
    ——最后状态变更时刻，非精确终态时间戳；字段缺失时保持既有表述（不硬造
    时刻）。终态/非终态两分支的中性表述语义均不动。
    """
    entry = entry or {}
    status = str(entry.get("status") or "")
    if status in TERMINAL_SPEC_STATUSES:
        reason = f"spec {spec_name} 已到达终态 {status}"
    else:
        # 中性表述：此分支对从未 blocked 的 spec（如 ready/in_progress）同样
        # 命中，不宜断言「已离开 blocked」；空/缺失 status 兜底显示 unknown。
        reason = f"spec {spec_name} 当前状态 {status or 'unknown'}，已非 blocked（视为解除）"
    updated = str(entry.get("updated") or "")
    if updated:
        reason += f"（状态变更时刻 {updated}）"
    return f"存量回填：{reason}" if backfill else reason


def evaluate_alert(
    alert: dict,
    specs: dict,
    backfill: bool = False,
    now=None,
    records=None,
    quiet_minutes: int = DEFAULT_SELF_HEAL_QUIET_MINUTES,
):
    """判定单条告警的触发条件是否已解除。

    specs 为当轮扫描读取的 STATE.md 状态表（name → entry）；判定所需的
    spec 状态以此为准，不额外读文件（design D3）。

    自愈判定（add-alert-self-heal-marking）仅在调用方显式注入 ``now``
    （epoch 秒）时启用；``records`` 为全量告警记录（收敛升级双源锚点需
    关联 disposition 与 signal 条目），``quiet_minutes`` 为安静窗口（脏值
    回退默认 1440）。既有调用方（不传 now）行为零变化。

    返回 resolve_note 字符串表示可闭环；返回 None 表示保持原状。保持原状
    的情形（保守默认）：
      - 已 handled（人工记录不可覆盖）
      - 非 escalation 且非 spec 附着族的 kind=signal（spec 附着族随主体终态
        收口，evo-add-signal-subject-terminal-close；自愈族另收，需注入 now）
      - 无 spec 字段，或 spec 在状态表中不存在（无法关联 spec）
      - trigger.condition 未识别（存量回填模式下 signal_type 不在
        BACKFILL_SIGNAL_TYPES 中同理）
      - 关联 spec 仍处于 blocked（条件未解除）
      - 自愈族：signal_type 未注册 / 形态不符 / 窗口内仍复现 / 无时间锚点
    """
    specs = specs if isinstance(specs, dict) else {}  # 非 dict（如 STATE.md 扫描失败传 None）按空表处理
    if not isinstance(alert, dict):
        return None
    if alert.get("handled"):
        return None  # 人工/既有处理记录不可覆盖
    kind = alert.get("kind")
    signal_type = alert.get("signal_type")
    trigger = alert.get("trigger")
    has_trigger = isinstance(trigger, dict) and trigger
    condition = trigger.get("condition") if has_trigger else None

    # ── 自愈分支（add-alert-self-heal-marking 1.2）────────────────────
    # 以 signal_type 注册表为门：注册表外类型（含 inconclusive_loop env
    # 握手族）永不自愈。spec 附着族命中既有条件枚举（trigger 已识别）→
    # 既有条件判定，不双重判定（specs/alert-lifecycle 排除项）。
    # 自愈注册表与回填注册表 BACKFILL_SIGNAL_TYPES 互斥（无交集），故
    # 此处不存在「无 trigger 按回填推断」的既有条件路径。
    if (
        now is not None
        and kind in ("escalation", "signal")
        and signal_type in SELF_HEAL_SIGNAL_TYPES
    ):
        existing_applies = has_trigger and _recognized(condition)
        if not existing_applies:
            return _evaluate_self_heal(
                alert,
                now=now,
                records=records,
                quiet_minutes=quiet_minutes,
                backfill=not has_trigger,
            )

    # kind 门（evo-add-signal-subject-terminal-close 1.1）：escalation 一律走
    # 既有路径；kind=signal 仅当属 spec 附着条件族（trigger 条件已识别，或
    # 回填模式按 signal_type ∈ BACKFILL_SIGNAL_TYPES 推断）才放行，与
    # escalation 复用同一终态判定（下方 blocked 拦截与中性表述均不动）；
    # 签名安静族与其余未登记 signal 形态不在此列，语义不动。
    if kind != "escalation" and not is_spec_attached_signal(alert, backfill):
        return None
    spec_name = alert.get("spec")
    if not spec_name:
        return None  # 无 spec 字段：无法关联，保持原状

    if has_trigger:
        if not _recognized(condition):
            return None  # 未识别 condition：永不自动闭环
    else:
        # 存量回填（design D4）：无 trigger 字段 → 按 signal_type 推断
        if not backfill:
            return None
        if signal_type not in BACKFILL_SIGNAL_TYPES:
            return None

    entry = specs.get(spec_name)
    if not isinstance(entry, dict):
        return None  # spec 不在状态表中：无法判定，保持原状
    status = str(entry.get("status") or "")
    if has_trigger and trigger.get("condition") == CONDITION_SPEC_DELIVERED_ADJUDICATED:
        # 独立条件（alert-noise-governance 1.4 登记 spec_delivered_no_content；
        # evo-instant-fail-storm-alert-closeout 1.1 扩展至 instant_fail_storm）：
        # 仅终态自动闭环，非终态（含 ready/blocked）一律保持原状——信号产生
        # 时 SPEC 停在待裁决/冷却等在途状态，提前闭环会让告警离开人工待处理
        # 队列。「补 tasks.md 归档凭据」裁决路径的告警收口为人工 handled
        # （本判定只读状态表、不读目录，MUST NOT 承诺纯 status 判定无法达成
        # 的「补内容即自动闭环」）。
        if status not in DELIVERED_ADJUDICATED_TERMINAL_STATUSES:
            return None
        # 与 _resolve_note_for_condition 同一审计口径（evo-add-signal-subject-
        # terminal-close 1.1）：终态收口备注附状态变更时刻（updated 缺失时
        # 保持既有表述，不硬造时刻）。文案按 signal_type 中性泛化（不写死
        # 单类型），同条件族新信号接入注册表后自动复用。
        reason = (
            f"spec {spec_name} 已到达终态 {status}，"
            f"{signal_type or '关联信号'} 裁决完成（终态收口）"
        )
        updated = str(entry.get("updated") or "")
        if updated:
            reason += f"（状态变更时刻 {updated}）"
        return reason
    if status == "blocked":
        return None  # 条件未解除
    return _resolve_note_for_condition(spec_name, entry, backfill=not has_trigger)


def find_resolvable(alerts: list, specs: dict, backfill: bool = False) -> list:
    """批量判定：返回可闭环条目列表 [{'id', 'spec', 'resolve_note'}]。

    供 AdminStore.auto_resolve 消费（写回在 AdminStore 的排他锁内完成）。
    alerts 全部已闭环 / 无可闭环条目时返回 []（调用方零写回，mtime 不变）。
    """
    results = []
    for alert in alerts or []:
        note = evaluate_alert(alert, specs, backfill=backfill)
        if note is None:
            continue
        results.append(
            {
                "id": alert.get("id"),
                "spec": alert.get("spec"),
                "resolve_note": note,
            }
        )
    return results


def find_self_healable(
    records: list, now, quiet_minutes: int = DEFAULT_SELF_HEAL_QUIET_MINUTES
) -> list:
    """批量自愈判定：返回可自愈收口条目 [{'id', 'spec', 'resolve_note'}]。

    供 AdminStore.auto_self_heal 消费（写回在其排他锁内完成）。``records``
    为全量告警记录（signal / escalation / disposition——收敛升级双源锚点
    需要关联信号与处置条目）；``now`` 为当前时刻（epoch 秒），判定输入全部
    由调用方注入（纯函数，不读时钟）。

    仅产出自愈族结果（既有 spec 附着条件族仍由 find_resolvable 承接，两
    通道互斥不重复）。无可自愈条目返回 []（调用方零写回，mtime 不变）。
    """
    results = []
    for alert in records or []:
        if not isinstance(alert, dict):
            continue
        if alert.get("handled"):
            continue
        if alert.get("kind") not in ("escalation", "signal"):
            continue
        if alert.get("signal_type") not in SELF_HEAL_SIGNAL_TYPES:
            continue
        trigger = alert.get("trigger")
        if isinstance(trigger, dict) and trigger and _recognized(trigger.get("condition")):
            continue  # 既有条件在册：归 find_resolvable 通道，不双重判定
        note = _evaluate_self_heal(
            alert,
            now=now,
            records=records,
            quiet_minutes=quiet_minutes,
            backfill=not (isinstance(trigger, dict) and trigger),
        )
        if note is None:
            continue
        results.append(
            {
                "id": alert.get("id"),
                "spec": alert.get("spec"),
                "resolve_note": note,
            }
        )
    return results
