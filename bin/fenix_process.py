#!/usr/bin/env python3
"""fenix_process — SPEC 详情报告（TUI，/fenix-process 数据源）。

与 Dashboard 共用 core/dashboard/data.py 数据层（tui-triage-revamp D1）：
主数据源 = data.spec_detail()（/api/specs/<name> 同一份组装），外加
spec_summary 的预算三字段与 worktree 检查。「需要关注」分诊由执行 skill
的 LLM 依据报告内容现场判断（skills/fenix-process/SKILL.md）。

用法: python3 fenix_process.py <spec-name>
"""

import os
import re
import sys
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
# normalize_depends_on 走公开名（code-review item b4b0573cd357：顶层导入 core
# 私有名，core 侧重命名即整份报告 import 期崩溃）；展示层助手单点在
# core.tui_format（_local_ts 默认 fmt 契约由 test_cli_time_display 钉死）。
from core.dashboard.data.summary import normalize_depends_on  # noqa: E402
from core.tui_format import fmt_dur as _fmt_dur, local_ts as _local_ts  # noqa: E402
from core.timelib import from_epoch  # noqa: E402

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
RUN_ICONS = {
    "administrator": "🛡️",
    "planner": "📋",
    "planner-plan": "📋",
    "planner-judge": "⚖️",
    "implementer": "🔨",
    "verifier": "🔍",
    "tester": "🧪",
    "agent": "🤖",
}
RUN_STATUS_DESC = {
    "done": "完成",
    "running": "运行中",
    "empty": "空跑",
    "error": "出错",
    "interrupted": "被打断",
    "cancelled": "已取消",
}
NEXT_STEPS = {
    "drafted": "等待晋升（promote_mode=manual 时运行 /fenix-ready）",
    "ready": "等待调度 implementer agent",
    "implementing": "implementer agent 正在工作区修改代码",
    "implemented": "等待调度 verifier agent 进行验证",
    "testing": "verifier agent 正在执行验证测试",
    "verified": "验证通过，等待标记 done",
    "reviewing": "等待方案评审 run",
    "bug-found": "等待修复（admin 自动创建 fix SPEC，或人工处置）",
    "blocked": "已冻结/阻塞 — 确认冻结原因或 /fenix-dashboard 解冻",
    "done": "等待推送 — 运行 /fenix-approve",
    "pushed": "✅ 已完成并推送",
}


def _fmt_tokens(n) -> str:
    try:
        n = int(n or 0)
    except (TypeError, ValueError):
        return "0"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def _render_tasks(tasks):
    """tasks.md 分组明细：未完成项全显，已完成项保留 id。"""
    lines = []
    total = sum(len(g.get("tasks", [])) for g in tasks)
    done = sum(1 for g in tasks for t in g.get("tasks", []) if t.get("done"))
    if not total:
        return lines
    lines.append(f"tasks.md 进展: {done}/{total}")
    for g in tasks:
        g_tasks = g.get("tasks", [])
        g_done = sum(1 for t in g_tasks if t.get("done"))
        g_total = len(g_tasks)
        mark = "✅" if g_done == g_total and g_total else "🔨"
        lines.append(f"  {mark} {g.get('title', '?')}（{g_done}/{g_total}）")
        for t in g_tasks:
            if t.get("done"):
                # 已完成任务只留 id：TUI 关注未完成的肉，完成明细是噪音
                lines.append(f"    ✓ {t.get('id', '?')}")
            else:
                lines.append(f"    ○ {t.get('id', '?')} {t.get('desc', '')}")
    return lines


def _render_verdict(detail):
    """验证结论 + 产品 Bug + 非产品失败计数。"""
    lines = []
    verdict = detail.get("verdict") or {}
    bugs = detail.get("bugs") or []
    filtered = detail.get("filtered_failures") or []
    has_verdict = verdict.get("exists")
    if has_verdict:
        lines.append(f"结论: {verdict.get('status') or '(空)'}")
        if verdict.get("status_detail"):
            lines.append(f"状态说明: {verdict['status_detail']}")
        summary = verdict.get("summary") or {}

        def _cnt(key):
            v = summary.get(key)
            return v if v is not None else "-"

        lines.append(
            f"计数: 通过 {_cnt('passed')} / 失败 {_cnt('failed')} / 错误 {_cnt('errors')}"
            f" ｜ 产品 Bug {_cnt('product_bugs')} ｜ 环境问题 {_cnt('env_issues')}"
        )
        if verdict.get("conclusion"):
            lines.append(f"结论段: {verdict['conclusion'][:200]}")
    if bugs:
        lines.append("产品 Bug:")
        for b in bugs:
            sev = b.get("severity") or "?"
            sc = b.get("scenario") or ",".join(str(s) for s in (b.get("scenario_ids") or []))
            desc = str(b.get("description") or b.get("title") or "")[:100]
            lines.append(f"  🐛 [{sev}] {sc} {desc}")
    if filtered:
        lines.append(f"非产品失败（test-defect/env/flaky，已过滤）: {len(filtered)} 条")
    # 场景截图数（验证证据）
    shots = detail.get("screenshots") or []
    if shots:
        lines.append(f"截图: {len(shots)} 张（.fenix/screenshots/{detail.get('name')}/）")
    return lines


def _render_runs(runs):
    """运行历史（含归档，最新在前）：attempt 链一目了然。"""
    lines = []
    for r in runs[:10]:
        icon = RUN_ICONS.get(r.get("agent_type"), "🤖")
        rid = r.get("run_id", "?")
        status = RUN_STATUS_DESC.get(r.get("status"), r.get("status") or "?")
        dur = _fmt_dur(r.get("duration_seconds"))
        started = _local_ts(r.get("started"), "%m-%d %H:%M")
        tail = f"  耗时 {dur}" if dur else ""
        lines.append(f"  {icon} {rid}  {status}  {started}{tail}")
    return lines


def _render_timeline(timeline):
    """时间轴精华：最近 15 个节点（状态转换带方向，打回带原因）。"""
    lines = []
    for ev in timeline[-15:]:
        ts = _local_ts(ev.get("time"), "%m-%d %H:%M")
        if ev.get("kind") == "state":
            arrow = "↩️" if ev.get("backward") else "→"
            reason = f"（{ev['reason']}）" if ev.get("reason") else ""
            lines.append(f"  {ts} 📦 {ev.get('from')} {arrow} {ev.get('to')}{reason}")
        else:
            icon = RUN_ICONS.get(ev.get("agent_type"), "🤖")
            status = RUN_STATUS_DESC.get(ev.get("status"), ev.get("status") or "")
            rid = str(ev.get("run_id") or "")
            if not rid and not status:
                continue  # 空 run 节点（无 run_id 无状态）是数据噪音，不渲染
            lines.append(f"  {ts} {icon} {rid} {status}".rstrip())
    return lines


def _wt_dir_matches_spec(wt_name: str, spec_name: str) -> bool:
    """worktree 目录名精确对应 spec（``{impl,verify,repair}-<spec>-<ts>``）。

    解析命名得完整 spec 名再精确比较（分隔符边界锚定，禁止子串包含——
    spec 名互为前缀如 auth 与 auth2 不误命中），与 worktree_manager
    ``_wt_name_matches_spec`` 同口径；非本框架命名返回 False。
    """
    if not wt_name or not spec_name:
        return False
    for prefix in ("impl", "verify", "repair"):
        if wt_name.startswith(f"{prefix}-"):
            rest = wt_name[len(prefix) + 1 :]
            parts = rest.rsplit("-", 1)
            if len(parts) == 2 and parts[0] and parts[1].isdigit():
                return parts[0] == spec_name
            return False
    return False


def _check_worktree(proot, spec_name):
    """活跃 worktree 与最近修改文件（保留原脚本行为）。"""
    wt_root = proot / ".claude" / "worktrees"
    # is_dir 而非 exists（code-review item a077e9aad426）：路径若为普通文件
    # （异常环境残留），exists() 为真但 iterdir() 抛 NotADirectoryError 令整份
    # 报告崩溃；is_dir 一并覆盖，与不存在同口径返回 None 降级。
    if not wt_root.is_dir():
        return None
    # 目录存在但不可读（权限/挂载异常）时 iterdir() 抛 PermissionError，
    # 沿 render_report 传到 main（只捕 ValueError）令整份报告裸栈崩溃；
    # 与下方 _mtime/os.walk 的 OSError 防御同口径，异常即降级返回 None。
    try:
        matches = [
            wt
            for wt in wt_root.iterdir()
            if wt.is_dir() and _wt_dir_matches_spec(wt.name, spec_name)
        ]
    except OSError:
        return None
    if not matches:
        return None

    def _mtime(p):
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0

    # 多匹配确定性选择（code-review item cbb7096a760e）：iterdir 顺序依文件
    # 系统而定，impl-<spec>-ts 与 verify-<spec>-ts 等多个 worktree 并存是合法
    # 状态，命中首个即返回会让同一 spec 的报告在两次执行间漂移；改为全量
    # 收集后按目录 mtime 新者优先、目录名字典序兜底——与 worktree_manager
    # find_implementer_worktree 的「最新优先」口径一致。
    matches.sort(key=lambda wt: (-_mtime(wt), wt.name))
    wt = matches[0]
    recent = []
    try:
        # os.walk 现场剪枝（code-review item 50836a87ed56）：rglob 先
        # 物化全树并对每个条目（含 .git/node_modules 全部文件）stat，
        # 依赖重的仓库报告卡顿；剪枝后仅对候选扩展名文件 stat。
        candidates = []
        for dirpath, dirnames, filenames in os.walk(wt):
            dirnames[:] = [
                d for d in dirnames if d not in (".git", "node_modules")
            ]
            for fn in filenames:
                if Path(fn).suffix in (
                    ".tsx", ".ts", ".css", ".html", ".json", ".py", ".md",
                ):
                    p = Path(dirpath) / fn
                    try:
                        candidates.append((p.stat().st_mtime, p))
                    except OSError:
                        continue
        candidates.sort(key=lambda x: x[0], reverse=True)
        recent = [(str(p.relative_to(wt)), mt) for mt, p in candidates[:10]]
    except OSError:
        pass
    return {"path": str(wt), "files": recent}


def render_report(project_root, spec_name: str) -> str:
    proot = Path(project_root)
    entries = data.parse_state(proot)
    entry = entries.get(spec_name)
    if not entry:
        # code-review item 9ec5f36af2a0：渲染函数不做输入校验副作用，
        # SPEC 缺失抛 ValueError，打印与退出由 main 决定。
        raise ValueError(f"SPEC '{spec_name}' 未找到（/fenix-status 查看全部 SPEC 名称）")

    lines = []

    # ── 头部 ──
    # 与 fenix_status.render_report（.get("status") or "?"）同口径：parse_state
    # 把 `- status:` 空值折叠为 None，.get 默认值只在键缺失时生效，None 会把
    # 头部渲染出字面量 None 并令 NEXT_STEPS.get(None) 落「未知状态」。
    status = entry.get("status") or "?"
    icon = STATUS_ICONS.get(status, "❓")
    try:
        summary = data.spec_summary(proot, spec_name, entry)
    except Exception:
        summary = {}
    # code-review item 76bb34e3d31f：spec_detail 组装链更长（runs/timeline/
    # verify_progress 等），任一子解析抛异常会让整份报告不可用；与 summary
    # 同口径降级为空详情（下游全部 .get() or 默认，空 dict 可安全兜底）。
    detail_err = None
    try:
        detail = data.spec_detail(proot, spec_name, entry)
    except Exception as exc:
        detail = {}
        detail_err = exc
    mode = (summary or {}).get("mode") or detail.get("mode") or "full"

    # 与 fenix_status.render_report 同口径：STATE.md 序列化对空优先级写 null，
    # .get 默认值只在键缺失时生效，null 会渲染出 PNone，故 int 折叠为 "?"
    try:
        pri = int(entry.get("priority"))
    except (TypeError, ValueError):
        pri = "?"
    lines.append(f"{icon} {spec_name}  P{pri}  {status}  [{mode}]")
    if detail_err is not None:
        lines.append(f"  ⚠ 详情组装失败: {detail_err}")
    head_notes = []
    # 依赖列与 Dashboard 列表侧同一归一化单点对齐：STATE.md 序列化对空依赖
    # 恒写 ``- depends_on: null``，解析回来是字面量字符串 "null"（真值），
    # 裸真值判定会给无依赖 SPEC 渲染「依赖: null」的误导行。
    deps = normalize_depends_on(entry.get("depends_on"))
    if deps:
        head_notes.append(f"依赖: {deps}")
    if entry.get("branch"):
        head_notes.append(f"分支: {entry['branch']}")
    for label, key in (("创建", "created"), ("更新", "updated")):
        if entry.get(key):
            head_notes.append(f"{label} {_local_ts(entry[key], '%m-%d %H:%M')}")
    if head_notes:
        lines.append("  " + "  ｜  ".join(head_notes))
    runs_ref = []
    if entry.get("implementer_run"):
        runs_ref.append(f"impl {entry['implementer_run']}")
    if entry.get("tester_run"):
        runs_ref.append(f"test {entry['tester_run']}")
    if runs_ref:
        lines.append("  " + "  ｜  ".join(runs_ref))
    frozen = data.is_spec_frozen(entry)
    err = entry.get("error")
    if err and not frozen:
        lines.append(f"  ⚠️ 错误: {err}")
    until = data.get_frozen_until(entry)
    if frozen or until:
        tail = f"，定时解冻 {_local_ts(until, '%m-%d %H:%M')}" if until else ""
        lines.append(f"  🧊 冻结{tail}")
    start_after = data.get_spec_start_after(entry)
    if start_after:
        # add-spec-manual-activation 5.4：哨兵 Manual 无目标时间，MUST NOT
        # 走 _local_ts（非 ISO 走 except 回退 str[:19]，输出伪时间戳）
        if start_after == "manual":
            lines.append("  ⏸ 待激活（start_after: manual）")
        else:
            lines.append(f"  ⏰ start_after: {_local_ts(start_after, '%m-%d %H:%M')}")

    # ── 进度 ──
    lines.append("")
    lines.append("-- 进度 --")
    lines.extend(_render_tasks(detail.get("tasks") or []))
    tasks_note = detail.get("tasks_note")
    if tasks_note:
        lines.append(f"  ⚠ {tasks_note}")
    rp = detail.get("run_progress") or {}
    if rp.get("total"):
        cur = f"（进行中 {','.join(rp.get('current') or [])}）" if rp.get("current") else ""
        lines.append(f"run 层实时: {rp.get('done')}/{rp.get('total')}{cur}")
    vp = detail.get("verify_progress") or {}
    if vp.get("total"):
        cur = f"  当前: {vp.get('current')}" if vp.get("current") else ""
        lines.append(f"验证: {vp.get('done')}/{vp.get('total')}{cur}")
    gen = detail.get("generation")
    if gen:
        lines.append(f"出题: {gen.get('done')}/{gen.get('total')}（场景生成中）")
    if not detail.get("tasks") and not vp.get("total") and not rp.get("total") and not gen:
        lines.append("  （无进度数据）")
    dur = _fmt_dur(detail.get("total_duration"))
    if dur:
        lines.append(f"累计耗时: {dur}")

    # ── 预算 ──
    if summary:
        try:
            effective = int(summary.get("budget_effective") or 0)
            used = int(summary.get("budget_used") or 0)
        except (TypeError, ValueError):
            # 预算字段被人工直写成非数字时不中断报告，取中性缺省 0
            effective = used = 0
        override = summary.get("budget_override")
        if effective:
            tag = f"（override {override}）" if override else ""
            if used >= effective:
                lines.append(f"尝试预算: {used}/{effective}{tag} ⚠️ 已耗尽 — 需人工介入或调高预算")
            else:
                lines.append(f"尝试预算: {used}/{effective}{tag} 剩余 {effective - used} 次")

    # ── 验证结论 ──
    verdict_block = _render_verdict(detail)
    if verdict_block:
        lines.append("")
        lines.append("-- 验证结论 --")
        lines.extend(verdict_block)

    # ── 运行历史 ──
    runs = detail.get("runs") or []
    if runs:
        lines.append("")
        lines.append(f"-- 运行历史（最近 {min(10, len(runs))}/{len(runs)}）--")
        lines.extend(_render_runs(runs))

    # ── 成本 ──
    token_usage = detail.get("token_usage") or {}
    cost_summary = detail.get("cost_summary")
    if token_usage.get("tokens_in") or token_usage.get("tokens_out") or cost_summary:
        lines.append("")
        lines.append("-- 成本 --")
        lines.append(
            f"tokens: 输入 {_fmt_tokens(token_usage.get('tokens_in'))}"
            f" / 输出 {_fmt_tokens(token_usage.get('tokens_out'))}"
        )
        cost_usd = token_usage.get("cost_usd")
        if token_usage.get("cost_available") and isinstance(cost_usd, (int, float)):
            lines.append(f"累计成本: ${cost_usd:.2f}")
        elif cost_summary:
            total_cost = cost_summary.get("computed_usd")
            if total_cost is not None:
                lines.append(f"时间轴计费成本: ${float(total_cost):.2f}")
            else:
                lines.append("成本: 不可用（计费开启但无可计价 run）")
        else:
            lines.append("成本: 不可用（网关未回传计费）")

    # ── 时间轴 ──
    timeline = detail.get("timeline") or []
    if timeline:
        lines.append("")
        lines.append(f"-- 时间轴（最近 {min(15, len(timeline))} 节点）--")
        lines.extend(_render_timeline(timeline))

    # ── 工作区 ──
    wt = _check_worktree(proot, spec_name)
    if wt:
        lines.append("")
        lines.append("-- 工作区 --")
        lines.append(f"  {wt['path']}")
        for rel, mtime in wt["files"][:10]:
            # SPEC-B 批⑤收拢：from_epoch（aware UTC）→ 本地渲染，与原
            # 零参 fromtimestamp（本地语义）同一墙钟输出
            ts = from_epoch(mtime).astimezone().strftime("%H:%M")
            lines.append(f"  {ts} {rel}")

    # ── 下一步 ──
    lines.append("")
    lines.append("-- 下一步 --")
    lines.append(f"  {NEXT_STEPS.get(status, '未知状态')}")

    return "\n".join(lines) + "\n"


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python3 fenix_process.py <spec-name>")
        return 1
    try:
        report = render_report(PROJECT_ROOT, sys.argv[1])
    except ValueError as exc:
        print(f"❌ {exc}")
        return 1
    except Exception as exc:
        # code-review item 7715ccc47799：render_report 入口的 parse_state
        # 未包裹，STATE.md 并发改写瞬间、权限/编码类 OSError 等非 ValueError
        # 异常会从 main 裸抛 traceback。SPEC 缺失仍走上方 ValueError 专门
        # 分支，其余环境级异常对齐 fenix_cli/fenix_status 兜底口径：
        # stderr（附异常类型名）+ exit 1。
        print(f"✗ 报告生成失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
