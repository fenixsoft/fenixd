#!/usr/bin/env python3
"""fenix_status — Fenix 状态面板报告（TUI，/fenix-status 数据源）。

与 Dashboard 共用 core/dashboard/data.py 数据层（tui-triage-revamp D1）：
本脚本只做机械拼装事实数据；「需要关注」分诊由执行 skill 的 LLM 依据
信号汇总段现场判断（skills/fenix-status/SKILL.md）。

裁剪契约：活跃 SPEC 逐行列出；done/pushed 终态折叠为统计行（名字不外显）。
信号汇总 = 供 LLM 分诊的原始问题素材，每行自带严重度前缀（🔴/⚠️/ℹ️），
已知等待（冻结/定时）单列、明确不算问题。

用法: python3 fenix_status.py          （经项目内 .fenix/bin/ 软链调用）
"""

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# .absolute()（不跟随软链接）：脚本经项目内 .fenix/bin/ 软链调用时，
# __file__ = <项目根>/.fenix/bin/fenix_status.py，三级 parent 即项目根。
# core 包以 PROJECT_ROOT/.fenix 为根导入——不依赖 CWD，防跨项目误锚。
PROJECT_ROOT = Path(__file__).absolute().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / ".fenix"))

from core.dashboard import data  # noqa: E402

TERMINAL = ("done", "pushed")
STATUS_ICONS = {
    "drafted": "📝",
    "ready": "📌",
    "implementing": "🔨",
    "implemented": "🧪",
    "testing": "🔍",
    "verified": "✅",
    "bug-found": "🐛",
    "blocked": "🧊",
    "done": "🎯",
    "pushed": "🚀",
}
SEV_MARK = {"red": "🔴", "warn": "⚠️", "info": "ℹ️"}
VERIFY_STALL_MINUTES = 30  # 验证进度文件 mtime 停滞阈值（事故校准口径，勿改用 STATE updated）


def _local_ts(iso_str, fmt="%m-%d %H:%M"):
    """UTC ISO → 本地时区显示（日志层全 UTC 写入，展示层转本地）。"""
    try:
        return (
            datetime.fromisoformat(str(iso_str).replace("Z", "+00:00")).astimezone().strftime(fmt)
        )
    except Exception:
        return str(iso_str)[:19]


def _fmt_dur(seconds) -> str:
    try:
        s = int(seconds or 0)
    except (TypeError, ValueError):
        return ""
    if s <= 0:
        return ""
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        return f"{s // 3600}h{(s % 3600) // 60:02d}m"
    return f"{s // 86400}d{(s % 86400) // 3600}h"


def _active_sort_key(item):
    pri = item[1].get("priority")
    try:
        pri = int(pri)
    except (TypeError, ValueError):
        pri = 999
    return (pri, item[0])


def _load_gates(proot):
    """审批/晋升模式（与 Dashboard 设置页同源 read_effective_config）。"""
    try:
        gates = data.read_effective_config(proot).get("gates") or {}
        return (gates.get("approve_mode") or "manual", gates.get("promote_mode") or "auto")
    except Exception:
        return "manual", "auto"


def _collect_signals(proot, entries, active, daemon, approve_mode, promote_mode):
    """信号汇总：供 LLM 分诊的问题素材（已知等待单列，不算问题）。"""
    signals = []  # (level, text)
    waits = []  # 已知等待（有意暂停，非问题）
    now_ts = datetime.now(timezone.utc).timestamp()

    if daemon != "running":
        signals.append(("red", "守护进程已停止 — 运行 /fenix-setup 启动"))

    # 未处理升级告警（已处理的不外显）
    try:
        alerts = data.alerts_summary(proot)
    except Exception:
        alerts = {}
    if alerts.get("unhandled_count"):
        sev = alerts.get("max_severity") or "minor"
        level = "red" if sev == "critical" else ("warn" if sev == "major" else "info")
        latest = alerts.get("latest") or {}
        desc = str(latest.get("description") or "")[:80]
        spec = latest.get("spec")
        loc = f"（{spec}）" if spec else ""
        signals.append(
            (level, f"未处理告警 {alerts['unhandled_count']} 条（最高 {sev}）{loc}：{desc}")
        )

    # 豁免集合：存在活跃 fix-<name> 子 SPEC 时，父 SPEC 的停滞/无修复链不算问题
    active_fix_parents = {
        n[4:]
        for n, e in entries.items()
        if n.startswith("fix-") and e.get("status") not in TERMINAL
    }

    for name, entry in sorted(active.items(), key=_active_sort_key):
        st = entry.get("status", "")
        frozen = data.is_spec_frozen(entry)
        err = entry.get("error")
        # 冻结的 error 是冻结标记本身，不算故障
        if err and not frozen:
            signals.append(("warn", f"{name}（{st}）：{str(err)[:100]}"))
        # 尝试预算（与预算闸门同源字段，spec_summary 单点解析）
        try:
            s = data.spec_summary(proot, name, entry)
        except Exception:
            s = None
        if s:
            used = int(s.get("budget_used") or 0)
            effective = int(s.get("budget_effective") or 0)
            if effective:
                if used >= effective:
                    signals.append(
                        (
                            "warn",
                            f"{name}：尝试预算耗尽（{used}/{effective}）— 需人工介入或调高预算",
                        )
                    )
                elif effective - used == 1:
                    signals.append(("info", f"{name}：尝试预算剩最后 1 次（{used}/{effective}）"))
        # 验证停滞：仅 testing，进度文件 mtime 口径（fix-parent 豁免）
        if st == "testing" and name not in active_fix_parents:
            pf = proot / ".fenix" / "verify-progress" / f"{name}.json"
            if pf.exists():
                try:
                    age_min = (now_ts - pf.stat().st_mtime) / 60
                    if age_min > VERIFY_STALL_MINUTES:
                        signals.append(
                            ("warn", f"{name}：验证停滞 {int(age_min)} 分钟（进度文件未更新）")
                        )
                except OSError:
                    pass
        # bug-found 且无活跃 fix 子 SPEC（fix 自身豁免）
        if st == "bug-found" and not name.startswith("fix-") and name not in active_fix_parents:
            signals.append(
                ("info", f"{name}：bug-found 且无活跃 fix 子 SPEC — 检查修复链是否已创建")
            )
        # 已知等待
        until = data.get_frozen_until(entry)
        if frozen or until:
            tail = f"，定时解冻 { _local_ts(until) }" if until else ""
            waits.append(f"{name}（冻结{tail}）")
        start_after = data.get_spec_start_after(entry)
        if start_after:
            waits.append(f"{name}（start_after { _local_ts(start_after) }）")

    # 待推送 / 待晋升
    done_pending = sum(1 for e in entries.values() if e.get("status") == "done")
    if done_pending:
        if approve_mode == "manual":
            signals.append(("info", f"{done_pending} 个 SPEC 待推送 — 运行 /fenix-approve"))
        else:
            signals.append(
                (
                    "warn",
                    f"{done_pending} 个 SPEC 滞留 done（auto 模式推送可能失败）— 可运行 /fenix-approve 人工兜底",
                )
            )
    drafted = sum(1 for e in entries.values() if e.get("status") == "drafted")
    if drafted and promote_mode == "manual":
        signals.append(("info", f"{drafted} 个草稿待晋升 — 运行 /fenix-ready"))

    if waits:
        signals.append(("info", "已知等待：" + "；".join(waits)))
    return signals


def render_report(project_root) -> str:
    proot = Path(project_root)
    lines = []

    daemon = data.daemon_health(proot)
    entries = data.parse_state(proot)
    active = {n: e for n, e in entries.items() if e.get("status") not in TERMINAL}
    done_cnt = sum(1 for e in entries.values() if e.get("status") == "done")
    pushed_cnt = sum(1 for e in entries.values() if e.get("status") == "pushed")
    approve_mode, promote_mode = _load_gates(proot)

    try:
        runs = data.get_runs(proot)
    except Exception:
        runs = []
    running = [r for r in runs if r["status"] in ("running", "empty")]
    by_type = {}
    for r in running:
        by_type[r["agent_type"]] = by_type.get(r["agent_type"], 0) + 1

    # ── 守护进程 / 告警 / 全景 ──
    daemon_line = "🟢 运行中" if daemon == "running" else "🔴 已停止"
    lines.append(f"守护进程: {daemon_line}")
    try:
        alerts = data.alerts_summary(proot)
        alert_line = (
            f"未处理 {alerts['unhandled_count']} 条"
            + (f"（最高 {alerts['max_severity']}）" if alerts.get("max_severity") else "")
            if alerts.get("unhandled_count")
            else "无"
        )
    except Exception:
        alert_line = "无"
    lines.append(f"告警: {alert_line}")
    run_desc = "，".join(f"{t} {n}" for t, n in by_type.items()) if by_type else "无"
    lines.append(f"活跃运行: {len(running)} 个（{run_desc}）")

    status_counts = {}
    for e in entries.values():
        st = e.get("status", "?") or "?"
        status_counts[st] = status_counts.get(st, 0) + 1
    nonterm_desc = " ".join(
        f"{st} {c}" for st, c in sorted(status_counts.items()) if st not in TERMINAL
    )
    lines.append(
        f"状态统计: 活跃 {len(active)}｜{nonterm_desc}｜终态: 🎯 done {done_cnt} ｜ 🚀 pushed {pushed_cnt}"
    )

    # ── 活跃 SPEC 明细 ──
    lines.append("")
    lines.append(f"-- 活跃 SPEC（{len(active)}）--")
    if not active:
        lines.append("  （无活跃 SPEC）")
    for name, entry in sorted(active.items(), key=_active_sort_key):
        st = entry.get("status", "?")
        icon = STATUS_ICONS.get(st, "❓")
        pri = entry.get("priority", "?")
        try:
            s = data.spec_summary(proot, name, entry)
        except Exception:
            s = None
        seg = [f"{icon} {name}", f"P{pri}", st]
        if s:
            seg.append(f"[{s.get('mode') or 'full'}]")
            if s.get("task_total"):
                seg.append(f"任务 {s.get('task_done')}/{s.get('task_total')}")
            rp = s.get("run_progress") or {}
            if rp.get("total"):
                seg.append(f"run {rp.get('done')}/{rp.get('total')}")
            if s.get("verify_total"):
                seg.append(f"验证 {s.get('verify_done')}/{s.get('verify_total')}")
            elif s.get("generation"):
                g = s["generation"]
                seg.append(f"出题 {g.get('done')}/{g.get('total')}")
            if s.get("budget_effective"):
                seg.append(f"预算 {s.get('budget_used')}/{s.get('budget_effective')}")
            dur = _fmt_dur(s.get("total_duration"))
            if dur:
                seg.append(f"耗时 {dur}")
        line = "  " + "  ".join(seg)
        notes = []
        if data.is_spec_frozen(entry):
            notes.append("🧊 冻结")
        if data.get_spec_start_after(entry):
            notes.append("⏰ 定时")
        err = entry.get("error")
        if err and not data.is_spec_frozen(entry):
            notes.append(f"⚠️ {str(err)[:80]}")
        if notes:
            line += "\n      " + "  ".join(notes)
        lines.append(line)

    # ── 终态折叠 ──
    lines.append("")
    lines.append(f"-- 终态（已折叠）-- 🎯 done {done_cnt} ｜ 🚀 pushed {pushed_cnt}")

    # ── 信号汇总（供 LLM 分诊） ──
    signals = _collect_signals(proot, entries, active, daemon, approve_mode, promote_mode)
    lines.append("")
    lines.append("-- 信号汇总（供分诊；🔴/⚠️=问题，ℹ️=提示，已知等待不算问题）--")
    if signals:
        for level, text in signals:
            lines.append(f"  {SEV_MARK.get(level, 'ℹ️')} {text}")
    else:
        lines.append("  ✅ 无异常信号")

    return "\n".join(lines) + "\n"


def main() -> int:
    sys.stdout.write(render_report(PROJECT_ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
