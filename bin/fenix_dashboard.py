#!/usr/bin/env python3
"""
Fenix Dashboard — 统一入口（Web / TUI / 项目注册）。

用法:
  python3 fenix_dashboard.py --serve [--port N]     # 启动 Web Dashboard（默认，跨项目）
  python3 fenix_dashboard.py --tui [--interval N]   # 终端仪表盘（原 TUI，保留）
  python3 fenix_dashboard.py --add-project <path>   # 注册项目到监控列表
  python3 fenix_dashboard.py --remove-project <path>  # 从监控列表移除已注册项目
  python3 fenix_dashboard.py --list-projects        # 列出已注册项目

数据源:
  - STATE.md            → SPEC 状态机
  - tasks.md            → 任务完成进度
  - .fenix/logs/*.log   → 实时事件流
  - .fenix/verify-progress/ → 验证进度 / 报告 / 截图
  - .fenix/runs/*.jsonl → Agent 运行产物流（实时 LLM 对话 / 工具调用）
  - ~/.config/fenixd/dashboard.yaml → 多项目监控配置

路径解析（兼容两种调用）:
  - 经项目内 .fenix/bin/ 软链接调用 → 项目根 = ../../..，core 在 ../.. (.fenix)
  - 直接以框架 bin/ 调用             → 项目根 = ..，core 在 ..
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# 使用 .absolute()（不跟随软链接）：脚本经项目内 .fenix/bin/ 软链接调用
_THIS_DIR = Path(__file__).absolute().parent
_FENIX_DIR = _THIS_DIR.parent
PROJECT_ROOT = _FENIX_DIR.parent if _FENIX_DIR.name == ".fenix" else _FENIX_DIR
if str(_FENIX_DIR) not in sys.path:
    sys.path.insert(0, str(_FENIX_DIR))

from core.dashboard import data as dash_data           # noqa: E402
from core.dashboard.registry import Registry, DEFAULT_PORT  # noqa: E402
from core.dashboard.server import serve, STATIC_DIR   # noqa: E402

STATE_PATH = PROJECT_ROOT / "STATE.md"
LOGS_DIR = PROJECT_ROOT / ".fenix" / "logs"
PROGRESS_DIR = PROJECT_ROOT / ".fenix" / "verify-progress"

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


# ── 项目注册子命令 ──────────────────────────────────────────────

def cmd_add_project(path: str) -> int:
    reg = Registry()
    target = str(Path(path).expanduser().absolute())
    added, msg = reg.add_project(target)
    print(msg)
    return 0 if added else 1


def cmd_remove_project(path: str) -> int:
    reg = Registry()
    target = str(Path(path).expanduser().absolute())
    removed, msg = reg.remove_project(target)
    print(msg)
    return 0 if removed else 1


def cmd_list_projects() -> int:
    reg = Registry()
    projects = reg.list_projects()
    if not projects:
        print("（尚未注册任何项目）")
        return 0
    print("已注册监控项目：")
    for p in projects:
        print(f"  - {p['name']}: {p['path']}")
    return 0


# ── TUI 渲染（原终端仪表盘，保留） ───────────────────────────────

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
    """获取验证进度（复用共享解析，损坏条目跳过）"""
    if not PROGRESS_DIR.exists(): return []
    results = []
    for pf in sorted(PROGRESS_DIR.glob("*.json")):
        data = dash_data.parse_verify_progress(PROJECT_ROOT, pf.stem)
        results.append({
            "spec": pf.stem,
            "total": data.get("total", 0),
            "done": data.get("done", 0),
            "current": data.get("current", ""),
        })
    return results


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
        d, t = dash_data.task_progress(PROJECT_ROOT, name)
        grand_total += t
        grand_done += d

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
        groups = dash_data.parse_tasks(PROJECT_ROOT, name)
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


def _local_ts(iso_str, fmt="%H:%M:%S"):
    """UTC ISO 时间戳 → 本地时区格式化;解析失败回退裸切片 [:19]。

    日志层统一写 UTC（core/logger.py），展示层负责转本地时区显示。
    """
    try:
        return datetime.fromisoformat(str(iso_str).replace("Z", "+00:00")).astimezone().strftime(fmt)
    except Exception:
        return str(iso_str)[:19]


def render_event_feed(specs):
    """渲染最近事件流"""
    events = dash_data.get_recent_events(PROJECT_ROOT, minutes=10)
    if not events:
        return f"  {GRAY}(最近 10 分钟无事件){RESET}"

    active_names = {n for n, e in specs.items() if e.get("status") in ("implementing", "testing")}

    lines = []
    component_icons = {
        "state_machine": "📦", "pm_engine": "🧠", "agent_runner": "🤖",
        "event_bus": "📡", "worktree_manager": "🌲",
    }

    for ev in events[-12:]:
        # 成功路径已带空格分隔;失败回退路径的 "T" 由 replace 归一
        ts = _local_ts(ev.get("timestamp", ""), fmt="%Y-%m-%d %H:%M:%S").replace("T", " ")
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
    total_scenarios = sum(dash_data.count_scenarios(PROJECT_ROOT, n) for n in specs)
    if total_scenarios > 0:
        lines.append(f"    📋 场景总数: {total_scenarios}")

    return "\n".join(lines)


def clear_screen():
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def check_daemon():
    """检查当前项目 daemon 是否运行（唯一 session 名，见 bin/fenix_session.py）"""
    try:
        helper = _THIS_DIR / "fenix_session.py"
        r = subprocess.run(
            ["python3", str(helper), "running", str(PROJECT_ROOT)],
            capture_output=True, timeout=2,
        )
        return r.stdout.strip() == "YES"
    except Exception:
        return False


def run_tui(interval=3):
    """终端仪表盘主循环（原 TUI，保留）"""
    print(f"{DIM}Fenix Dashboard — 每 {interval}s 刷新，Ctrl+C 退出{RESET}")
    time.sleep(1)

    try:
        while True:
            clear_screen()
            daemon_ok = check_daemon()
            specs = dash_data.parse_state(PROJECT_ROOT)

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


# ── Web 模式 ────────────────────────────────────────────────────

def run_serve(port_override=None):
    """启动 Web Dashboard（跨项目）。端口优先级：--port > 用户配置(registry) > 项目 dashboard.port > 8787。

    CLI 是人的显式长驻入口：设 FENIX_DASHBOARD_DETACH=1 豁免 serve() 的
    父子生命周期绑定（PDEATHSIG/孤儿拒启）——本实例不随启动 shell 退出而终止；
    直接 import serve() 的脚本/交互会话无此豁免，脚本退出即被内核回收
    （孤儿实例防护，2026-09-03 runs 删空事故 V1 防线）。
    """
    os.environ["FENIX_DASHBOARD_DETACH"] = "1"
    reg = Registry()
    cfg = reg.load()
    port = port_override or cfg.get("port")
    if not port_override and port in (None, DEFAULT_PORT):
        # 用户未显式指定端口 → 回退项目级 .fenix/config.yaml 的可选 dashboard.port
        # （config.template.yaml 已含模板字段；跨项目场景下用户级配置优先级最高）
        try:
            from core.config import ConfigLoader
            pconf = ConfigLoader.load(PROJECT_ROOT / ".fenix" / "config.yaml")
            pport = ConfigLoader.get(pconf, "dashboard.port", None)
            if pport is not None:
                port = int(pport)
        except Exception:
            pass
    try:
        port = int(port) if port is not None else DEFAULT_PORT
    except (TypeError, ValueError):
        port = DEFAULT_PORT
    serve(reg, port=port)


# ── 入口 ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Fenix Dashboard — Web / TUI / 项目注册",
    )
    parser.add_argument("--serve", action="store_true",
                        help="启动 Web Dashboard（默认，跨项目监控）")
    parser.add_argument("--tui", action="store_true",
                        help="启动终端仪表盘（原 TUI）")
    parser.add_argument("--add-project", metavar="PATH",
                        help="注册项目到监控列表（按路径去重）")
    parser.add_argument("--remove-project", metavar="PATH",
                        help="从监控列表移除已注册项目（未注册时不报错）")
    parser.add_argument("--list-projects", action="store_true",
                        help="列出已注册监控项目")
    parser.add_argument("--port", type=int,
                        help="Web 端口（默认取配置，或 8787；被占用时按端口接管语义处理）")
    parser.add_argument("--interval", type=int, default=3,
                        help="TUI 刷新间隔（秒）")
    args = parser.parse_args()

    if args.add_project:
        sys.exit(cmd_add_project(args.add_project))
    if args.remove_project:
        sys.exit(cmd_remove_project(args.remove_project))
    if args.list_projects:
        sys.exit(cmd_list_projects())
    if args.tui:
        run_tui(args.interval)
    else:
        # 默认 Web 模式（--serve）
        run_serve(args.port)


if __name__ == "__main__":
    main()
