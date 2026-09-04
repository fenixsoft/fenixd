#!/usr/bin/env python3
"""
Fenix Process — 查看指定 SPEC 的详细进展。

用法: python3 fenix_process.py <spec-name>
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# 使用 .absolute()（不跟随软链接）：脚本经项目内 .fenix/bin/ 软链接调用
PROJECT_ROOT = Path(__file__).absolute().parent.parent.parent
STATE_PATH = PROJECT_ROOT / "STATE.md"
CHANGES_DIR = PROJECT_ROOT / "openspec" / "changes"
LOGS_DIR = PROJECT_ROOT / ".fenix" / "logs"
WORKTREES_DIR = PROJECT_ROOT / ".claude" / "worktrees"
VERIFY_PROGRESS_DIR = PROJECT_ROOT / ".fenix" / "verify-progress"

# ── 颜色常量 ────────────────────────────────────────────────────────

GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
RED = "\033[31m"
GRAY = "\033[90m"
BOLD = "\033[1m"
RESET = "\033[0m"

# ── STATE.md 解析 ────────────────────────────────────────────────────

def parse_state():
    """解析 STATE.md 获取 SPEC 状态信息"""
    if not STATE_PATH.exists():
        return {}
    specs = {}
    current_name = None
    current_entry = {}
    for line in STATE_PATH.read_text(encoding="utf-8").split("\n"):
        m = re.match(r"^###\s+(.+)$", line)
        if m:
            if current_name and current_entry and "status" in current_entry:
                specs[current_name] = current_entry
            current_name = m.group(1).strip()
            current_entry = {}
            continue
        m = re.match(r"^-\s+([a-z_]+):\s*(.*)$", line)
        if m and current_name:
            key = m.group(1)
            val = m.group(2).strip()
            if key == "priority":
                try: val = int(val)
                except: val = 999
            elif val.lower() in ("null", "none", ""): val = None
            current_entry[key] = val
    if current_name and current_entry and "status" in current_entry:
        specs[current_name] = current_entry
    return specs


def parse_tasks(spec_name):
    """解析 tasks.md 返回分组任务列表"""
    tasks_path = CHANGES_DIR / spec_name / "tasks.md"
    if not tasks_path.exists():
        return []

    groups = []
    current_group = None

    for line in tasks_path.read_text(encoding="utf-8").split("\n"):
        # 分组标题（点号可选双历史格式：`## 1. 标题` / `## 1 标题`）。
        # 与 core/dashboard/data.py:parse_tasks、core/deliverables.py:
        # lint_tasks_parseable 同源正则（task-track D1），三处必须一致。
        m = re.match(r"^##\s+\d+\.?\s+(.+)$", line)
        if m:
            current_group = {"title": m.group(1), "tasks": []}
            groups.append(current_group)
            continue
        # 任务项
        m = re.match(r"^- \[(x| )\] (\d+\.\d+) (.+)$", line)
        if m and current_group is not None:
            current_group["tasks"].append({
                "done": m.group(1) == "x",
                "id": m.group(2),
                "desc": m.group(3).strip(),
            })

    return groups


# ── 日志解析 ────────────────────────────────────────────────────────

def _local_ts(iso_str, fmt="%H:%M:%S"):
    """UTC ISO 时间戳 → 本地时区格式化;解析失败回退裸切片 [:19]。

    日志层统一写 UTC（core/logger.py），展示层负责转本地时区显示。
    """
    try:
        return datetime.fromisoformat(str(iso_str).replace("Z", "+00:00")).astimezone().strftime(fmt)
    except Exception:
        return str(iso_str)[:19]


def parse_logs(spec_name):
    """从 fenixd 日志中提取指定 SPEC 的事件时间线"""
    log_files = sorted(LOGS_DIR.glob("fenixd*.log"), reverse=True)
    events = []

    for lf in log_files[:3]:  # 只看最近3个日志文件
        try:
            for line in lf.read_text(encoding="utf-8").split("\n"):
                if spec_name not in line:
                    continue
                try:
                    entry = json.loads(line)
                    ts = entry.get("timestamp", "")
                    msg = entry.get("message", "")
                    comp = entry.get("component", "")
                    ctx = entry.get("context", {})
                    if isinstance(ctx, dict):
                        status = ctx.get("status") or ctx.get("new_status", "")
                    else:
                        status = ""
                    events.append({
                        "time": ts,
                        "component": comp,
                        "message": msg,
                        "status": status,
                    })
                except json.JSONDecodeError:
                    continue
        except Exception:
            continue

    return events


# ── Worktree 检查 ────────────────────────────────────────────────────

def check_worktree(spec_name):
    """查找该 SPEC 的活跃 worktree"""
    if not WORKTREES_DIR.exists():
        return None
    for wt in WORKTREES_DIR.iterdir():
        if wt.is_dir() and spec_name.replace("-", "-") in wt.name:
            # 获取最近修改的文件
            recent_files = []
            for f in sorted(wt.rglob("*"), key=lambda x: x.stat().st_mtime if x.exists() else 0, reverse=True):
                if f.is_file() and ".git/" not in str(f) and "node_modules" not in str(f):
                    if any(str(f).endswith(ext) for ext in [".tsx", ".ts", ".css", ".html", ".json", ".py", ".md"]):
                        mtime = datetime.fromtimestamp(f.stat().st_mtime)
                        rel = str(f.relative_to(wt))
                        recent_files.append((rel, mtime))
                if len(recent_files) >= 15:
                    break
            return {"path": str(wt), "files": recent_files}
    return None


# ── 验证进度 ─────────────────────────────────────────────────────────

def parse_verify_progress(spec_name):
    """读取验证进度：进度指针（total/done/current）+ report.json 汇总与场景明细"""
    pointer_path = VERIFY_PROGRESS_DIR / f"{spec_name}.json"
    report_path = VERIFY_PROGRESS_DIR / spec_name / "report.json"

    result = {"pointer": None, "summary": None, "scenarios": [], "timestamp": None}

    # 1. 进度指针（验证进行中实时更新）
    if pointer_path.exists():
        try:
            result["pointer"] = json.loads(pointer_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    # 2. report.json（验证完成后生成的完整报告）
    if report_path.exists():
        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
            result["summary"] = data.get("summary", {})
            result["scenarios"] = data.get("scenarios", [])
            result["timestamp"] = data.get("timestamp")
        except (json.JSONDecodeError, OSError):
            pass

    return result


def show_verify_progress(spec_name):
    """输出验证进度区块（有验证数据时才显示）"""
    vp = parse_verify_progress(spec_name)
    if not vp["pointer"] and not vp["scenarios"]:
        return

    print(f"\n{BOLD}🧪 验证进度（planner 场景）{RESET}")

    # 进度指针
    pointer = vp["pointer"]
    if pointer:
        total = pointer.get("total", 0)
        done = pointer.get("done", 0)
        current = pointer.get("current", "")
        print(f"  进度: {done}/{total} 已完成")
        if current:
            print(f"  {GRAY}{current}{RESET}")

    # 汇总
    summary = vp["summary"]
    if summary:
        passed = summary.get("passed", 0)
        failed = summary.get("failed", 0)
        errors = summary.get("errors", 0)
        warnings = summary.get("warnings", 0)
        print(f"  结果: {GREEN}{passed} 通过{RESET} / {RED}{failed} 失败{RESET}"
              f" / {RED}{errors} 错误{RESET} / {YELLOW}{warnings} 警告{RESET}")

    # 场景明细
    scenarios = vp["scenarios"]
    if scenarios:
        print()
        for s in scenarios:
            sid = s.get("scenario_id", "?")
            desc = s.get("description", "")
            status = s.get("status", "?")
            if status == "pass":
                mark = f"{GREEN}✓{RESET}"
            elif status == "fail":
                mark = f"{RED}✗{RESET}"
            elif status == "error":
                mark = f"{RED}⚠{RESET}"
            else:
                mark = f"{GRAY}·{RESET}"
            line = f"  {mark} {GRAY}{sid}{RESET}"
            if desc:
                line += f" — {desc}"
            if status == "fail":
                # 定位首个失败点：优先断言（更具体），其次步骤
                fail_assert = next((a for a in s.get("assertion_results", []) if not a.get("pass")), None)
                fail_step = next((r for r in s.get("step_results", []) if not r.get("success")), None)
                if fail_assert:
                    label = fail_assert.get("label") or fail_assert.get("type", "?")
                    line += f"  {RED}[断言失败: {label}]{RESET}"
                elif fail_step:
                    detail = fail_step.get("detail") or ""
                    line += f"  {RED}[步骤失败: {fail_step.get('action')} {detail}]{RESET}"
            print(line)


# ── 输出 ─────────────────────────────────────────────────────────────

STATUS_ICONS = {
    "drafted": "📝", "ready": "📌", "implementing": "🔨",
    "implemented": "🧪", "testing": "🔍", "verified": "✅",
    "bug-found": "🐛", "done": "🎯", "pushed": "🚀",
}


def show_progress(spec_name):
    """主函数：输出 SPEC 进展报告"""
    # 1. 基本信息
    specs = parse_state()
    entry = specs.get(spec_name)
    if not entry:
        print(f"{RED}❌ SPEC '{spec_name}' 未找到{RESET}")
        sys.exit(1)

    status = entry.get("status", "?")
    icon = STATUS_ICONS.get(status, "❓")
    priority = entry.get("priority", "?")
    deps = entry.get("depends_on")
    error = entry.get("error")
    impl_run = entry.get("implementer_run")
    test_run = entry.get("tester_run")

    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"  {icon} {BOLD}{spec_name}{RESET}  (P{priority})")
    print(f"  状态: {icon} {GREEN if status in ('done','pushed') else YELLOW}{status}{RESET}")
    if deps and deps != "null":
        print(f"  依赖: {deps}")
    if error:
        print(f"  {RED}⚠️  错误: {error}{RESET}")
    if impl_run:
        print(f"  实现运行: {GRAY}{impl_run}{RESET}")
    if test_run:
        print(f"  测试运行: {GRAY}{test_run}{RESET}")
    print(f"{BOLD}{'='*60}{RESET}")

    # 2. tasks.md 进展
    groups = parse_tasks(spec_name)
    if groups:
        total = sum(len(g["tasks"]) for g in groups)
        done = sum(1 for g in groups for t in g["tasks"] if t["done"])
        pct = int(done / total * 100) if total > 0 else 0
        bar_len = 20
        filled = int(pct / 100 * bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)

        print(f"\n{BOLD}📊 tasks.md 进展 [{bar}] {done}/{total} ({pct}%){RESET}\n")
        for group in groups:
            g_done = sum(1 for t in group["tasks"] if t["done"])
            g_total = len(group["tasks"])
            g_icon = "✅" if g_done == g_total else "🔨"
            print(f"  {g_icon} {group['title']} ({g_done}/{g_total})")
            for task in group["tasks"]:
                mark = f"{GREEN}✓{RESET}" if task["done"] else f"{GRAY}○{RESET}"
                desc = task["desc"]
                if task["done"]:
                    desc = f"{GRAY}{desc}{RESET}"
                print(f"     {mark} {task['id']} {desc}")
    elif (CHANGES_DIR / spec_name / "tasks.md").exists():
        # tasks.md 存在但未解析出任务分组：显式提示，不再静默跳过（task-track R3）
        print(f"\n{YELLOW}⚠ tasks.md 存在但未解析出任务（分组格式不匹配？）{RESET}")

    # 3. fenixd 日志时间线
    events = parse_logs(spec_name)
    if events:
        print(f"\n{BOLD}📋 fenixd 时间线{RESET}\n")
        for ev in events[:20]:
            ts = _local_ts(ev["time"])
            comp_short = {"state_machine": "📦", "pm_engine": "🧠",
                          "agent_runner": "🤖", "event_bus": "📡",
                          "worktree_manager": "🌲"}.get(ev["component"], ev["component"][:4])
            print(f"  {GRAY}{ts}{RESET} {comp_short} {ev['message']}")

    # 4. Worktree 和文件变更
    wt = check_worktree(spec_name)
    if wt:
        print(f"\n{BOLD}🔧 工作区{RESET}")
        print(f"  {GRAY}{wt['path']}{RESET}\n")
        if wt["files"]:
            recent = wt["files"][:10]
            for fpath, mtime in recent:
                ts = mtime.strftime("%H:%M")
                print(f"  {GRAY}{ts}{RESET} {fpath}")

    # 5. 验证进度（planner 场景数 + 通过/失败）
    show_verify_progress(spec_name)

    # 6. 下一步提示
    print(f"\n{BOLD}⏭️  下一步{RESET}")
    next_steps = {
        "drafted": "fenixd 将自动推进 → ready → implementing",
        "ready": "fenixd 等待调度 implementer agent",
        "implementing": "implementer agent 正在工作区修改代码",
        "implemented": "fenixd 将自动调度 verifier agent 进行验证",
        "testing": "verifier agent 正在执行验证测试",
        "verified": "验证通过，fenixd 将自动标记为 done",
        "bug-found": "验证发现 bug，fenixd 将自动创建 fix SPEC",
        "done": "等待推送 — 运行 /fenix-approve",
        "pushed": "✅ 已完成并推送",
    }
    print(f"  {next_steps.get(status, '未知状态')}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python3 fenix_process.py <spec-name>")
        sys.exit(1)
    show_progress(sys.argv[1])
