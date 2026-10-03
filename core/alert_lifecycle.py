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

本模块不读写文件、不依赖锁——写回由 AdminStore.auto_resolve 在排他锁内完成
（design D6）。
"""

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


def _resolve_note_for_condition(spec_name: str, entry: dict, backfill: bool) -> str:
    """spec_terminal_or_unblocked 条件下的解除依据描述（spec.md：含 spec 名与终态说明）。"""
    status = str((entry or {}).get("status") or "")
    if status in TERMINAL_SPEC_STATUSES:
        reason = f"spec {spec_name} 已到达终态 {status}"
    else:
        # 中性表述：此分支对从未 blocked 的 spec（如 ready/in_progress）同样
        # 命中，不宜断言「已离开 blocked」；空/缺失 status 兜底显示 unknown。
        reason = f"spec {spec_name} 当前状态 {status or 'unknown'}，已非 blocked（视为解除）"
    return f"存量回填：{reason}" if backfill else reason


def evaluate_alert(alert: dict, specs: dict, backfill: bool = False):
    """判定单条告警的触发条件是否已解除。

    specs 为当轮扫描读取的 STATE.md 状态表（name → entry）；判定所需的
    spec 状态以此为准，不额外读文件（design D3）。

    返回 resolve_note 字符串表示可闭环；返回 None 表示保持原状。保持原状
    的情形（保守默认）：
      - 非 escalation 告警 / 已 handled（人工记录不可覆盖）
      - 无 spec 字段，或 spec 在状态表中不存在（无法关联 spec）
      - trigger.condition 未识别（存量回填模式下 signal_type 不在
        BACKFILL_SIGNAL_TYPES 中同理）
      - 关联 spec 仍处于 blocked（条件未解除）
    """
    specs = specs if isinstance(specs, dict) else {}  # 非 dict（如 STATE.md 扫描失败传 None）按空表处理
    if not isinstance(alert, dict):
        return None
    if alert.get("kind") != "escalation":
        return None
    if alert.get("handled"):
        return None  # 人工/既有处理记录不可覆盖
    spec_name = alert.get("spec")
    if not spec_name:
        return None  # 无 spec 字段：无法关联，保持原状

    trigger = alert.get("trigger")
    has_trigger = isinstance(trigger, dict) and trigger
    if has_trigger:
        condition = trigger.get("condition")
        if not _recognized(condition):
            return None  # 未识别 condition：永不自动闭环
    else:
        # 存量回填（design D4）：无 trigger 字段 → 按 signal_type 推断
        if not backfill:
            return None
        if alert.get("signal_type") not in BACKFILL_SIGNAL_TYPES:
            return None

    entry = specs.get(spec_name)
    if not isinstance(entry, dict):
        return None  # spec 不在状态表中：无法判定，保持原状
    status = str(entry.get("status") or "")
    if has_trigger and trigger.get("condition") == CONDITION_SPEC_DELIVERED_ADJUDICATED:
        # 独立条件（alert-noise-governance 1.4）：仅终态自动闭环，非终态
        # （含 ready/blocked）一律保持原状——信号产生时 SPEC 停在 ready 待
        # 裁决，提前闭环会让告警离开人工待处理队列。「补 tasks.md 归档凭据」
        # 裁决路径的收口为人工 handled（本判定只读状态表、不读目录，MUST
        # NOT 承诺纯 status 判定无法达成的「补内容即自动闭环」）。
        if status not in DELIVERED_ADJUDICATED_TERMINAL_STATUSES:
            return None
        return (
            f"spec {spec_name} 已到达终态 {status}，"
            f"spec_delivered_no_content 人工裁决完成（终态收口）"
        )
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
