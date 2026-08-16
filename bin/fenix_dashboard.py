#!/usr/bin/env python3
"""
Fenix Dashboard — 实时开发进度控制台仪表盘。

用法: python3 fenix_dashboard.py [--interval N]

数据源:
  - STATE.md           → SPEC 状态机
  - tasks.md            → 任务完成进度
  - fenixd.log          → 实时事件流
  - verify-progress/    → 验证进度
  - ps aux              → 活跃 agent 进程
  - git worktree list   → 活跃工作区
"""

import json
import os
import re
import subprocess
import sys
import time
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 使用 .absolute()（不跟随软链接）：脚本经项目内 .fenix/bin/ 软链接调用
PROJECT_ROOT = Path(__file__).absolute().parent.parent.parent
STATE_PATH = PROJECT_ROOT / "STATE.md"
CHANGES_DIR = PROJECT_ROOT / "openspec" / "changes"
LOGS_DIR = PROJECT_ROOT / ".fenix" / "logs"
PROGRESS_DIR = PROJECT_ROOT / ".fenix" / "verify-progress"
WORKTREES_DIR = PROJECT_ROOT / ".claude" / "worktrees"

# ANSI 颜色
GREEN = "\033[32m"; YELLOW = "\033[33m"; CYAN = "\033[36m"
RED = "\033[31m"; GRAY = "\033[90m"; BLUE = "\033[34m"
MAGENTA = "\033[35m"; WHITE = "\033[97m"
BOLD = "\033[1m"; DIM = "\033[2m"; RESET = "\033[0m"
BG_GREEN = "\033[42m"; BG_RED = "\033[41m"; BG_BLUE = "\033[44m"

STATUS_ICONS = {
    "drafted": "📝", "ready": "📌", "implementing": "🔨",
    "implemented": "🧪", "testing": "🔍", "verified": "✅",
    "bug-found": "🐛", "done": "🎯", "pushed": "🚀",
}
STATUS_COLORS = {
    "implementing": YELLOW, "testing": CYAN, "verified": GREEN,
    "done": GREEN, "pushed": GREEN, "bug-found": RED,
    "drafted": GRAY, "ready": BLUE, "implemented": MAGENTA,
}

# ── 数据解析 ──────────────────────────────────────────────────

def parse_state():
    if not STATE_PATH.exists():
        return {}
    specs = {}
    current_name = None; current_entry = {}
    for line in STATE_PATH.read_text(encoding="utf-8").split("\n"):
        m = re.match(r"^###\s+(.+)$", line)
        if m:
            if current_name and current_entry and "status" in current_entry:
                specs[current_name] = current_entry
            current_name = m.group(1).strip(); current_entry = {}
            continue
        m = re.match(r"^-\s+([a-z_]+):\s*(.*)$", line)
        if m and current_name:
            key = m.group(1); val = m.group(2).strip()
            if key == "priority":
                try: val = int(val)
                except: val = 999
            elif val.lower() in ("null", "none", ""): val = None
            current_entry[key] = val
    if current_name and current_entry and "status" in current_entry:
        specs[current_name] = current_entry
    return specs


def parse_tasks(spec_name):
    tasks_path = CHANGES_DIR / spec_name / "tasks.md"
    if not tasks_path.exists():
        return []
    groups = []; current_group = None
    for line in tasks_path.read_text(encoding="utf-8").split("\n"):
        m = re.match(r"^##\s+\d+\.\s+(.+)$", line)
        if m:
            current_group = {"title": m.group(1), "tasks": [], "done": 0, "total": 0}
            groups.append(current_group); continue
        m = re.match(r"^- \[(x| )\] (\d+\.\d+) (.+)$", line)
        if m and current_group is not None:
            is_done = m.group(1) == "x"
            current_group["tasks"].append({
                "done": is_done, "id": m.group(2), "desc": m.group(3).strip()
            })
            if is_done: current_group["done"] += 1
            current_group["total"] += 1
    return groups


def count_scenarios(spec_name):
    specs_dir = CHANGES_DIR / spec_name / "specs"
    if not specs_dir.exists(): return 0
    count = 0
    try:
        for sf in specs_dir.rglob("*.md"):
            for line in sf.read_text(encoding="utf-8").split("\n"):
                if re.match(r"^####\s+Scenario:", line): count += 1
    except: pass
    return count


def get_recent_events(minutes=5):
    """获取最近 N 分钟的 fenixd 日志事件"""
    log_files = sorted(LOGS_DIR.glob("fenixd*.log"), reverse=True)
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    events = []
    for lf in log_files[:2]:
        try:
            for line in lf.read_text(encoding="utf-8").split("\n"):
                if not line.strip(): continue
                try:
                    entry = json.loads(line)
                    ts = entry.get("timestamp", "")
                    if ts < cutoff: continue
                    events.append(entry)
                except json.JSONDecodeError: continue
        except: continue
    # 取最近 30 条
    return events[-30:]


def get_active_agents():
    """获取活跃的 claude agent 进程"""
    try:
        r = subprocess.run(
            ["ps", "aux"], capture_output=True, text=True, timeout=3
        )
        agents = []
        for line in r.stdout.split("\n"):
            if "claude " not in line or "grep" in line:
                continue
            parts = line.split()
            if len(parts) < 11: continue
            pid = parts[1]
            cpu = parts[2]
            mem = parts[3]
            cmd = " ".join(parts[10:])
            # 提取 agent 角色
            role = "agent"
            if "Implementer" in cmd: role = "🔨 implementer"
            elif "Verifier" in cmd: role = "🔍 verifier"
            elif "Tester" in cmd: role = "🧪 tester"
            # 提取 SPEC 名
            spec = ""
            for part in parts:
                if "impl-" in part or "verify-" in part or "test-" in part:
                    spec = part.split("impl-")[-1].split("verify-")[-1].split("test-")[-1]
                    spec = spec.split("-178")[0]  # 去掉 run id
                    break
            agents.append({"pid": pid, "cpu": cpu, "mem": mem, "role": role, "spec": spec, "cmd": cmd[:200]})
        return agents
    except: return []


def get_worktrees():
    """获取活跃的 git worktree"""
    try:
        r = subprocess.run(["git", "worktree", "list"], capture_output=True, text=True, timeout=3, cwd=PROJECT_ROOT)
        trees = []
        for line in r.stdout.strip().split("\n"):
            parts = line.split()
            if len(parts) >= 1:
                path = parts[0]
                branch = parts[2].strip("[]") if len(parts) >= 3 else ""
                trees.append({"path": path, "branch": branch})
        return trees
    except: return []


def get_verify_progress():
    """获取验证进度"""
    if not PROGRESS_DIR.exists(): return []
    results = []
    for pf in sorted(PROGRESS_DIR.glob("*.json")):
        try:
            data = json.loads(pf.read_text())
            results.append({
                "spec": pf.stem,
                "total": data.get("total", 0),
                "done": data.get("done", 0),
                "current": data.get("current", ""),
            })
        except: pass
    return results


# ── 渲染函数 ──────────────────────────────────────────────────

TERM_WIDTH = 120


def bar(pct, width=20, style="block"):
    """渲染进度条"""
    filled = max(0, min(width, int(pct / 100 * width)))
    if style == "block":
        ch_filled, ch_empty = "█", "░"
    else:
        ch_filled, ch_empty = "▓", "░"
    return f"{GREEN}{ch_filled * filled}{GRAY}{ch_empty * (width - filled)}{RESET}"


def header_line(text):
    """节标题"""
    w = shutil.get_terminal_size((120, 40)).columns
    pad = max(0, w - len(text) - 4)
    return f"\n{BOLD}{BLUE}══ {text} {RESET}{DIM}{'─' * pad}{RESET}\n"


def render_overview(specs, daemon_ok):
    """渲染整体概览"""
    total = len(specs)
    status_counts = {}
    for e in specs.values():
        st = e.get("status", "?")
        status_counts[st] = status_counts.get(st, 0) + 1

    pushed = status_counts.get("pushed", 0)
    done = status_counts.get("done", 0)
    implementing = status_counts.get("implementing", 0)
    testing = status_counts.get("testing", 0)
    verified = status_counts.get("verified", 0)
    has_error = sum(1 for e in specs.values() if e.get("error") and e.get("status") not in ("done", "pushed"))

    # 计算总体实现进度
    grand_total = grand_done = 0
    for name in specs:
        tasks = parse_tasks(name)
        grand_total += sum(g["total"] for g in tasks)
        grand_done += sum(g["done"] for g in tasks)

    # daemon 状态
    d_icon = f"{GREEN}🟢 运行中{RESET}" if daemon_ok else f"{RED}🔴 已停止{RESET}"

    # 活跃 agent 数
    agents = get_active_agents()
    agent_count = len(agents)

    lines = [
        f"  {BOLD}fenixd{RESET}: {d_icon}  │  "
        f"{BOLD}SPECs{RESET}: {total}  │  "
        f"🚀 pushed: {pushed}  🎯 done: {done}  🔨 开发中: {implementing}  🔍 验证中: {testing}  ✅ 已通过: {verified}",
    ]

    # 实现进度
    if grand_total > 0:
        pct = int(grand_done / grand_total * 100)
        lines.append(f"  {BOLD}实现进度{RESET}: {bar(pct, 30)} {grand_done}/{grand_total} ({pct}%)")
    else:
        lines.append(f"  {BOLD}实现进度{RESET}: {GRAY}(无任务数据){RESET}")

    # 活跃进程
    if agent_count > 0:
        agent_line = f"  {BOLD}活跃 Agent{RESET}: {YELLOW}{agent_count}{RESET} 个进程  "
        for a in agents[:5]:
            agent_line += f"[{a['role']} PID:{a['pid']}] "
        lines.append(agent_line)
    else:
        lines.append(f"  {BOLD}活跃 Agent{RESET}: {GRAY}无{RESET}")

    # 错误
    if has_error > 0:
        lines.append(f"  {BOLD}阻塞{RESET}: {RED}🚨 {has_error} 个 SPEC 有错误{RESET}")

    return "\n".join(lines)


def render_active_specs(specs):
    """渲染活跃 SPEC 详情"""
    active = [
        (name, entry) for name, entry in specs.items()
        if entry.get("status") in ("implementing", "testing", "implemented")
    ]
    active.sort(key=lambda x: x[1].get("priority", 999))

    if not active:
        pending = [
            (name, entry) for name, entry in specs.items()
            if entry.get("status") in ("drafted", "ready")
        ]
        if pending:
            return f"  {GRAY}等待调度: {', '.join(n[:20] for n, _ in pending[:3])}{RESET}"
        return f"  {GRAY}无活跃 SPEC — 所有任务已完成{RESET}"

    lines = []
    for name, entry in active[:4]:  # 最多显示 4 个
        status = entry.get("status", "?")
        icon = STATUS_ICONS.get(status, "❓")
        color = STATUS_COLORS.get(status, WHITE)
        error = entry.get("error")
        prio = entry.get("priority", "?")

        # 任务进度
        groups = parse_tasks(name)
        all_tasks = []
        for g in groups:
            all_tasks.extend(g["tasks"])
        task_done = sum(1 for t in all_tasks if t["done"])
        task_total = len(all_tasks)
        task_pct = int(task_done / task_total * 100) if task_total > 0 else 0

        # 找到当前正在做的任务
        current_task = None
        for g in groups:
            for t in g["tasks"]:
                if not t["done"] and current_task is None:
                    current_task = f"{g['title']} → {t['id']} {t['desc'][:40]}"
                    break

        # 行 1: 图标 + 名称 + 状态 + 进度
        name_display = name[:28] + ("…" if len(name) > 28 else "")
        line1 = f"  {icon} {BOLD}{color}{name_display}{RESET}"
        line1 += f"  {color}{status}{RESET}"
        if task_total > 0:
            line1 += f"  {bar(task_pct, 15)} {task_done}/{task_total}"
        else:
            line1 += f"  {GRAY}(无任务){RESET}"
        lines.append(line1)

        # 行 2: 当前任务
        if current_task:
            lines.append(f"     {DIM}⏳ {current_task}{RESET}")
        elif status == "testing":
            # 显示验证进度
            verify = get_verify_progress()
            for v in verify:
                if v["spec"] == name or name in v["spec"]:
                    v_pct = int(v["done"] / v["total"] * 100) if v["total"] > 0 else 0
                    lines.append(f"     {DIM}🔍 验证: {bar(v_pct, 10, 'thin')} {v['done']}/{v['total']} {v['current'][:40]}{RESET}")

        # 行 3: 错误
        if error:
            lines.append(f"     {RED}⚠️  {str(error)[:80]}{RESET}")

        lines.append("")

    return "\n".join(lines)


def render_event_feed(specs):
    """渲染最近事件流"""
    events = get_recent_events(minutes=10)
    if not events:
        return f"  {GRAY}(最近 10 分钟无事件){RESET}"

    active_names = {n for n, e in specs.items() if e.get("status") in ("implementing", "testing")}

    lines = []
    component_icons = {
        "state_machine": "📦", "pm_engine": "🧠", "agent_runner": "🤖",
        "event_bus": "📡", "worktree_manager": "🌲",
    }

    for ev in events[-12:]:
        ts = ev.get("timestamp", "")[:19].replace("T", " ")
        comp = ev.get("component", "")[:15]
        icon = component_icons.get(comp, "  ")
        msg = ev.get("message", "")
        ctx = ev.get("context", {})

        # 高亮活跃 SPEC
        spec_in_msg = ""
        for n in active_names:
            if n in msg: spec_in_msg = n; break

        if spec_in_msg:
            msg_display = msg.replace(spec_in_msg, f"{YELLOW}{spec_in_msg}{RESET}")
        else:
            msg_display = msg[:100]

        lines.append(f"  {DIM}{ts}{RESET} {icon} {msg_display}")

    return "\n".join(lines)


def render_stats_panel(specs):
    """渲染右侧统计面板（简化版）"""
    total = len(specs)
    by_status = {}
    for e in specs.values():
        st = e.get("status", "?")
        by_status[st] = by_status.get(st, 0) + 1

    lines = []
    order = ["implementing", "testing", "implemented", "verified", "done", "pushed", "ready", "drafted", "bug-found"]
    for st in order:
        count = by_status.get(st, 0)
        if count > 0:
            icon = STATUS_ICONS.get(st, "  ")
            lines.append(f"    {icon} {st:14s}: {count}")

    # 场景统计
    total_scenarios = sum(count_scenarios(n) for n in specs)
    if total_scenarios > 0:
        lines.append(f"    📋 场景总数: {total_scenarios}")

    return "\n".join(lines)


def clear_screen():
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


# ── 主循环 ──────────────────────────────────────────────────

def main():
    interval = 3
    if len(sys.argv) >= 3 and sys.argv[1] == "--interval":
        try: interval = int(sys.argv[2])
        except: pass

    print(f"{DIM}Fenix Dashboard — 每 {interval}s 刷新，Ctrl+C 退出{RESET}")
    time.sleep(1)

    try:
        while True:
            clear_screen()

            # 检查 daemon
            daemon_ok = False
            try:
                r = subprocess.run(["tmux", "has-session", "-t", "fenixd"],
                                   capture_output=True, timeout=2)
                daemon_ok = r.returncode == 0
            except: pass

            specs = parse_state()

            # 标题
            now = datetime.now().strftime("%H:%M:%S")
            w = shutil.get_terminal_size((120, 40)).columns
            title = f"  Fenix 开发仪表盘  —  {now}  "
            pad = max(0, w - len(title) - 4)
            print(f"\n{BOLD}{BG_BLUE}{WHITE}{title}{RESET}{DIM}{'─' * pad}{RESET}")

            # 1. 概览
            print(render_overview(specs, daemon_ok))

            # 2. 活跃 SPEC
            print(header_line("活跃 SPEC"))
            print(render_active_specs(specs))

            # 3. 事件流
            print(header_line("事件流 (最近 10 分钟)"))
            print(render_event_feed(specs))

            # 底部状态栏
            total = len(specs)
            pushed = sum(1 for e in specs.values() if e.get("status") == "pushed")
            done = sum(1 for e in specs.values() if e.get("status") == "done")
            active = sum(1 for e in specs.values() if e.get("status") in ("implementing", "testing"))
            pending_push = done  # done status means pending push

            agents = get_active_agents()
            w = shutil.get_terminal_size((120, 40)).columns
            footer = f" SPECs: {total} | 🚀 已推送: {pushed} | 🎯 待推送: {pending_push} | 🔨 活跃: {active} | 🤖 Agent进程: {len(agents)} "
            pad = max(0, w - len(footer) - 2)
            print(f"\n{BG_BLUE}{WHITE}{BOLD}{footer}{RESET}{DIM}{'─' * pad}{RESET}")

            sys.stdout.flush()
            time.sleep(interval)

    except KeyboardInterrupt:
        clear_screen()
        print(f"{GREEN}✅ Fenix Dashboard 已退出{RESET}")


if __name__ == "__main__":
    main()
