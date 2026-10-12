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

import sys
from datetime import datetime, timezone
from pathlib import Path

# .absolute()（不跟随软链接）：兼容两种调用（与 fenix_dashboard.py 同一判定）——
# 经项目内 .fenix/bin/ 软链调用 → _FENIX_DIR = <项目根>/.fenix，PROJECT_ROOT = 项目根；
# 直接以框架 bin/ 调用   → _FENIX_DIR = 仓库根，PROJECT_ROOT = 仓库根。
# core 包随 _FENIX_DIR 导入——不依赖 CWD，防跨项目误锚。
_THIS_DIR = Path(__file__).absolute().parent
_FENIX_DIR = _THIS_DIR.parent
PROJECT_ROOT = _FENIX_DIR.parent if _FENIX_DIR.name == ".fenix" else _FENIX_DIR
if str(_FENIX_DIR) not in sys.path:
    sys.path.insert(0, str(_FENIX_DIR))

from core.dashboard import data  # noqa: E402
from core.timelib import parse_ts  # noqa: E402
# 展示层助手单点在 core.tui_format（code-review item 50a1202e3e91：此前本脚本
# 的 _fmt_dur 小时段补零输出 2h05m，与 fenix_process 的 2h5m 口径漂移）
from core.tui_format import fmt_dur as _fmt_dur, local_ts  # noqa: E402

TERMINAL = ("done", "pushed")
STATUS_ICONS = {
    "drafted": "📝",
    "ready": "📌",
    "implementing": "🔨",
    "implemented": "🧪",
    "testing": "🔍",
    "verified": "✅",
    "reviewing": "⚖️",
    "bug-found": "🐛",
    "blocked": "🧊",
    "done": "🎯",
    "pushed": "🚀",
}
SEV_MARK = {"red": "🔴", "warn": "⚠️", "info": "ℹ️"}
VERIFY_STALL_MINUTES = 30  # 验证停滞阈值：进度文件 mtime 停滞 / 缺失超时共用（事故校准口径；mtime 口径勿改用 STATE updated）


def _local_ts(iso_str, fmt="%m-%d %H:%M"):
    """UTC ISO → 本地时区显示（实现单点 core.tui_format.local_ts；本面板默认带日期）。"""
    return local_ts(iso_str, fmt)


def _active_sort_key(item):
    pri = item[1].get("priority")
    try:
        pri = int(pri)
    except (TypeError, ValueError):
        pri = 999
    return (pri, item[0])


def _fix_root(name):
    """剥全部连续 `fix-` 前缀得家族根名（对齐 family.py _fix_strip_all 口径）。"""
    while name.startswith("fix-"):
        name = name[4:]
    return name


def _load_gates(proot):
    """审批/晋升模式（与 Dashboard 设置页同源 read_effective_config）。"""
    try:
        gates = data.read_effective_config(proot).get("gates") or {}
        return (gates.get("approve_mode") or "manual", gates.get("promote_mode") or "auto")
    except Exception:
        return "manual", "auto"


def _collect_signals(
    proot, entries, active, daemon, approve_mode, promote_mode, alerts=None, summaries=None
):
    """信号汇总：供 LLM 分诊的问题素材（已知等待单列，不算问题）。"""
    signals = []  # (level, text)
    waits = []  # 已知等待（有意暂停，非问题）
    now_ts = datetime.now(timezone.utc).timestamp()

    if daemon != "running":
        signals.append(("red", "守护进程已停止 — 运行 /fenix-setup 启动"))

    # 未处理升级告警（已处理的不外显）。alerts 由调用方（render_report）取一次
    # 传入复用——同一份报告顶部告警行与信号汇总共用同一快照，避免重复 IO，
    # 两处数字也不因扫描间隙的告警变化而互相矛盾；直调方未传时现场取。
    if alerts is None:
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

    # 豁免集合：存在活跃 fix-<name> 子 SPEC 时，父 SPEC 的停滞/无修复链不算问题。
    # 根名剥全部连续 `fix-` 前缀（对齐 family.py _fix_strip_all / engine.py
    # _on_spec_done 候选循环口径）：嵌套修复链（fix-fix-<spec>）激活时父 SPEC
    # 豁免不失效；裸 "fix-" 剥空后不进集合。
    active_fix_parents = set()
    for n, e in entries.items():
        if not n.startswith("fix-") or e.get("status") in TERMINAL:
            continue
        root = _fix_root(n)
        if root:
            active_fix_parents.add(root)

    for name, entry in sorted(active.items(), key=_active_sort_key):
        st = entry.get("status", "")
        frozen = data.is_spec_frozen(entry)
        err = entry.get("error")
        # 冻结的 error 是冻结标记本身，不算故障
        if err and not frozen:
            signals.append(("warn", f"{name}（{st}）：{str(err)[:100]}"))
        # 尝试预算（与预算闸门同源字段，spec_summary 单点解析）。summaries 由
        # 调用方（render_report）取一次传入复用——与 alerts 的快照共享同一模式：
        # 同一批活跃 SPEC 的明细行与信号汇总共用同一份 summary（内部多文件
        # IO），避免 IO 翻倍、也避免两次扫描间隙数据变化使两处口径不一致；
        # 直调方未传时现场取。
        if summaries is None:
            try:
                s = data.spec_summary(proot, name, entry)
            except Exception:
                s = None
        else:
            s = summaries.get(name)
        if s:
            try:
                used = int(s.get("budget_used") or 0)
                effective = int(s.get("budget_effective") or 0)
            except (TypeError, ValueError):
                # 预算字段被人工直写成非数字时不中断报告，取中性缺省 0
                # （effective 为 0 时该信号自然跳过；与 fenix_process.py 同口径）
                used = effective = 0
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
            else:
                # 进度文件缺失（verifier 进入 testing 后从未写出：启动即崩、
                # 写入路径异常等）时 mtime 口径失效，停滞检测不得因此完全
                # 沉默——补独立信号。时长锚点用 STATE updated（进入 testing
                # 前后的最近一次状态变更），仅作「进入 testing 已多久」的
                # 锚点，不替代上方已校准的 mtime 停滞口径；daemon 侧
                # orphaned_state/stuck 只扫「无活动 run + 无存活子进程」，
                # verifier 存活但不写进度时两边都沉默，故此处必须补位。
                try:
                    updated = entry.get("updated")
                    if updated:
                        # SPEC-B 批⑤：解析收拢 parse_ts（唯一入口，失败 None
                        # 同路跳过该 entry 信号——原 except pass）。naive 语义
                        # 随全框架唯一策略翻转（原显式补 UTC→现按本地解读）；
                        # STATE updated 写侧恒 aware，翻转仅影响历史手写数据
                        # （findings 申报）。
                        dt = parse_ts(str(updated))
                        if dt is not None:
                            anchor = dt.timestamp()
                            age_min = (now_ts - anchor) / 60
                            if age_min > VERIFY_STALL_MINUTES:
                                signals.append(
                                    (
                                        "warn",
                                        f"{name}：testing 但无进度文件 {int(age_min)} 分钟（verifier 未写出验证进度）",
                                    )
                                )
                except (TypeError, ValueError):
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
            # add-spec-manual-activation D8/5.3：哨兵 manual 是「永不到期、待人工
            # 激活」——MUST NOT 走 _local_ts（非 ISO 走 except 回退 str[:19]，
            # 会输出 `start_after manual` 的伪时间戳）。
            if start_after == "manual":
                waits.append(f"{name}（待激活，需人工激活）")
            else:
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
        alerts = {}
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
    summaries = {}  # 取一次快照：明细行渲染与 _collect_signals 共用（见其 summaries 注释）
    for name, entry in sorted(active.items(), key=_active_sort_key):
        st = entry.get("status", "?")
        icon = STATUS_ICONS.get(st, "❓")
        # 与 _active_sort_key 同口径：priority 为 null/非法时折叠为 "?"，避免渲染出 PNone
        try:
            pri = int(entry.get("priority"))
        except (TypeError, ValueError):
            pri = "?"
        try:
            s = data.spec_summary(proot, name, entry)
        except Exception:
            s = None
        summaries[name] = s
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
        sa = data.get_spec_start_after(entry)
        if sa:
            # add-spec-manual-activation 5.3：哨兵 manual 无目标时间，
            # 「⏰ 定时」为事实错误，改印「⏸ 待激活」
            if sa == "manual":
                notes.append("⏸ 待激活")
            else:
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
    signals = _collect_signals(
        proot, entries, active, daemon, approve_mode, promote_mode, alerts, summaries
    )
    lines.append("")
    lines.append("-- 信号汇总（供分诊；🔴/⚠️=问题，ℹ️=提示，已知等待不算问题）--")
    if signals:
        for level, text in signals:
            lines.append(f"  {SEV_MARK.get(level, 'ℹ️')} {text}")
    else:
        lines.append("  ✅ 无异常信号")

    return "\n".join(lines) + "\n"


def main() -> int:
    # 兜底对齐 fenix_cli.main 的统一错误口径：render_report 内 get_runs/
    # alerts_summary/spec_summary 均已 try/except 降级，唯独入口 parse_state
    # 未包裹——STATE.md 并发改写瞬间的解析异常、权限/编码类 OSError 裸抛会以
    # traceback 收场，/fenix-status 报告整体不可用且无可读错误。统一转
    # stderr（附异常类型名）+ exit 1，报告失败也给出可读错误。
    try:
        report = render_report(PROJECT_ROOT)
    except Exception as e:
        print(f"✗ 报告生成失败：{type(e).__name__}: {e}", file=sys.stderr)
        return 1
    sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
