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

# 闭环判定条件枚举（design D2）：保守起步，仅一种。
CONDITION_SPEC_TERMINAL_OR_UNBLOCKED = "spec_terminal_or_unblocked"
# spec.md 场景文本中的同义拼写，作别名兼容（同一判定，不构成新条件）
_CONDITION_ALIAS = "spec_reach_terminal_or_unblocked"

# 存量回填（design D4）：无 trigger 字段的存量告警按 signal_type 推断 condition
BACKFILL_SIGNAL_TYPES = ("verify_fail_escalation", "blocked_stuck")

# 自动闭环标注（design D3）
AUTO_RESOLVE_BY = "auto-resolve"

# signal_type → condition 映射（写入时埋点用）。后续新告警类型按需在此扩展，
# 未列出的类型不写 trigger、永不自动闭环（保守默认）。
_SIGNAL_CONDITIONS = {
    "verify_fail_escalation": CONDITION_SPEC_TERMINAL_OR_UNBLOCKED,
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


def _recognized(condition) -> bool:
    return condition in (CONDITION_SPEC_TERMINAL_OR_UNBLOCKED, _CONDITION_ALIAS)


def _resolve_note_for_condition(spec_name: str, entry: dict,
                                backfill: bool) -> str:
    """spec_terminal_or_unblocked 条件下的解除依据描述（spec.md：含 spec 名与终态说明）。"""
    status = str((entry or {}).get("status") or "")
    if status in TERMINAL_SPEC_STATUSES:
        reason = f"spec {spec_name} 已到达终态 {status}"
    else:
        reason = f"spec {spec_name} 已离开 blocked（当前 {status}）"
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
    if status == "blocked":
        return None  # 条件未解除
    return _resolve_note_for_condition(spec_name, entry, backfill=not has_trigger)


def find_resolvable(alerts: list, specs: dict,
                    backfill: bool = False) -> list:
    """批量判定：返回可闭环条目列表 [{'id', 'spec', 'resolve_note'}]。

    供 AdminStore.auto_resolve 消费（写回在 AdminStore 的排他锁内完成）。
    alerts 全部已闭环 / 无可闭环条目时返回 []（调用方零写回，mtime 不变）。
    """
    results = []
    for alert in alerts or []:
        note = evaluate_alert(alert, specs, backfill=backfill)
        if note is None:
            continue
        results.append({
            "id": alert.get("id"),
            "spec": alert.get("spec"),
            "resolve_note": note,
        })
    return results
