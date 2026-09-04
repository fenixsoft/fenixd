#!/usr/bin/env python3
"""
Fenix status line for Claude Code.
Shows: daemon health | progress bar | active SPEC.task | blocker/warning alerts.
"""

import os
import re
import subprocess
from pathlib import Path

def _find_project_root() -> Path:
    """从当前目录向上查找含 STATE.md 或 .fenix 的项目根。

    statusline 是全局 hook（配置在 ~/.claude/settings.json），
    Claude Code 以项目根为 cwd 运行它；若不在项目内则回退到 cwd。
    """
    cwd = Path.cwd()
    for p in [cwd, *cwd.parents]:
        if (p / ".fenix" / "STATE.md").exists() or (p / ".fenix").exists():
            return p
    return cwd


PROJECT_ROOT = _find_project_root()
STATE_PATH = PROJECT_ROOT / ".fenix" / "STATE.md"
CHANGES_DIR = PROJECT_ROOT / "spec" / "changes"

# ── Daemon check ──────────────────────────────────────────────────

def check_fenixd() -> str:
    """检测本项目 daemon 是否运行（唯一 session 名，见 bin/fenix_session.py）。"""
    try:
        helper = Path(__file__).resolve().parent / "fenix_session.py"
        r = subprocess.run(
            ["python3", str(helper), "running", str(PROJECT_ROOT)],
            capture_output=True, timeout=2,
        )
        return "🟢" if r.stdout.strip() == "YES" else "🔴"
    except Exception:
        return "⚪"


# ── STATE.md parser ───────────────────────────────────────────────

def parse_state() -> dict:
    """Parse STATE.md, return {spec_name: {status, priority, error, ...}}."""
    if not STATE_PATH.exists():
        return {}

    specs = {}
    current_name = None
    current_entry = {}

    try:
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
                elif val.lower() in ("null", "none", ""):
                    val = None
                current_entry[key] = val

        if current_name and current_entry and "status" in current_entry:
            specs[current_name] = current_entry
    except Exception:
        pass

    return specs


# ── worktree helpers ──────────────────────────────────────────────

WORKTREES_DIR = PROJECT_ROOT / ".claude" / "worktrees"

def find_implementer_worktree(spec_name: str) -> Path | None:
    """Find the newest implementer worktree for a SPEC, or None."""
    if not WORKTREES_DIR.is_dir():
        return None
    prefix = f"impl-{spec_name}-"
    candidates = []
    for d in WORKTREES_DIR.iterdir():
        if d.is_dir() and d.name.startswith(prefix):
            try:
                candidates.append((d.stat().st_mtime, d))
            except OSError:
                pass
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


# ── tasks.md parser ───────────────────────────────────────────────

def parse_tasks(spec_name: str, status: str = "") -> dict:
    """Parse tasks.md for a SPEC, return {total, done, current_task}.

    For implementing SPECs, reads from the active implementer worktree first,
    falling back to the main repository.
    """
    tasks_path = CHANGES_DIR / spec_name / "tasks.md"
    if status == "implementing":
        wt = find_implementer_worktree(spec_name)
        if wt:
            wt_tasks = wt / "spec" / "changes" / spec_name / "tasks.md"
            if wt_tasks.exists():
                tasks_path = wt_tasks
    if not tasks_path.exists():
        return {"total": 0, "done": 0, "current_task": None}

    total = 0
    done = 0
    first_undone = None

    try:
        for line in tasks_path.read_text(encoding="utf-8").split("\n"):
            m = re.match(r"^- \[(x| )\] (\d+\.\d+) (.+)$", line)
            if m:
                total += 1
                is_done = m.group(1) == "x"
                task_id = m.group(2)
                task_desc = m.group(3).strip()

                if is_done:
                    done += 1
                elif first_undone is None:
                    first_undone = f"{task_id} {task_desc[:20]}"
    except Exception:
        pass

    return {"total": total, "done": done, "current_task": first_undone}


def count_scenarios(spec_name: str) -> int:
    """Count total #### Scenario: blocks across all spec.md files for a SPEC."""
    specs_dir = CHANGES_DIR / spec_name / "specs"
    if not specs_dir.exists():
        return 0

    count = 0
    try:
        for spec_file in specs_dir.rglob("*.md"):
            for line in spec_file.read_text(encoding="utf-8").split("\n"):
                if re.match(r"^####\s+Scenario:", line):
                    count += 1
    except Exception:
        pass
    return count


# ── Alert detection ───────────────────────────────────────────────

def detect_alerts(specs: dict) -> list:
    """Detect blockers, errors, and human-intervention-needed conditions."""
    critical = []   # 🔴 must-show
    warnings = []   # 🟡 nice-to-show

    for name, entry in specs.items():
        status = entry.get("status", "")
        error = entry.get("error")

        # 🔴 Critical: stuck in implementing/testing WITH error
        if status in ("implementing", "testing") and error:
            err_short = str(error)[:30]
            critical.append(("🔴", f"{name[:12]}:{err_short}"))

        # 🔴 Critical: done but has error (shouldn't happen, indicates bug)
        if status == "ready" and error:
            err_short = str(error)[:30]
            critical.append(("🟡", f"{name[:12]}:{err_short}"))

    # Only show dependency blocks if no critical issues
    if not critical:
        for name, entry in specs.items():
            deps = entry.get("depends_on")
            if deps and deps != "null":
                for dep in str(deps).split(","):
                    dep = dep.strip()
                    if dep:
                        dep_entry = specs.get(dep, {})
                        dep_status = dep_entry.get("status", "")
                        # Only flag if dependency is stuck (not actively progressing)
                        if dep_status not in ("done", "pushed", "implementing", "testing"):
                            warnings.append(("⏸️", f"{name[:10]}→{dep[:10]}"))

    result = critical + warnings
    return result[:2]  # Max 2 alerts


# ── Main ──────────────────────────────────────────────────────────

def main():
    daemon = check_fenixd()
    specs = parse_state()

    if not specs:
        print(f"{daemon} Fenix  no SPECs")
        return

    # Aggregate tasks + scenarios across all SPECs
    grand_total = 0
    grand_done = 0
    scenario_total = 0
    scenario_done = 0
    active_icon = None
    active_name = None
    active_prio = 999
    active_task = None

    for name, entry in specs.items():
        status = entry.get("status", "")
        tasks = parse_tasks(name, status)
        grand_total += tasks["total"]
        grand_done += tasks["done"]

        # Scenario counts for verification progress
        sc = count_scenarios(name)
        scenario_total += sc
        status = entry.get("status", "")
        if status in ("verified", "done", "pushed"):
            scenario_done += sc

        prio = entry.get("priority", 999)

        if status == "implementing" and prio < active_prio:
            active_prio = prio
            active_icon = "🔨"
            active_name = name
            active_task = tasks["current_task"]
        elif status == "testing":
            t_prio = prio + 0.5
            if active_name is None or (active_icon != "🔨" and t_prio < active_prio):
                active_prio = t_prio
                active_icon = "🔍"
                active_name = name
                active_task = tasks["current_task"]

    # Implementation progress bar (10 segments)
    if grand_total > 0:
        pct = grand_done / grand_total
        filled = int(pct * 10)
        bar = "▓" * filled + "░" * (10 - filled)
        impl_progress = f"[{bar}] {grand_done}/{grand_total}"
    else:
        impl_progress = "[-/-]"

    # Verification progress — prefer incremental progress files over binary per-SPEC
    verify_done = verify_total = 0
    progress_dir = PROJECT_ROOT / ".fenix" / "verify-progress"
    if progress_dir.exists():
        in_verify_specs = {name for name, e in specs.items() if e.get("status") == "testing"}
        for pf in progress_dir.glob("*.json"):
            try:
                import json as jmod
                data = jmod.loads(pf.read_text())
                verify_total += data.get("total", 0)
                verify_done += data.get("done", 0)
            except Exception:
                pass

    # Merge with binary done: count scenarios for verified SPECs
    for name, entry in specs.items():
        if entry.get("status") in ("verified", "done", "pushed"):
            sc = count_scenarios(name)
            verify_done += sc
            verify_total += sc

    # Ensure we have at least the scenario-based totals
    if verify_total == 0:
        verify_total = scenario_total
        verify_done = scenario_done

    total_specs = len(specs)
    verified = sum(1 for e in specs.values() if e.get("status") in ("verified", "done", "pushed"))
    in_verify = sum(1 for e in specs.values() if e.get("status") == "testing")

    if total_specs > 0 and grand_done >= grand_total:
        # All implementation done — show verification progress with scenario granularity
        if verify_total > 0:
            v_pct = verify_done / verify_total
            v_filled = int(v_pct * 10)
            v_bar = "▓" * v_filled + "░" * (10 - v_filled)
            progress = f"🔍 [{v_bar}] {verify_done}/{verify_total}"
        else:
            progress = f"🔍 {verified}/{total_specs}"
    elif verified > 0 or in_verify > 0:
        # Mixed phase — show impl progress + verification count
        progress = f"{impl_progress}  ✅ {verified}/{total_specs}"
    else:
        progress = impl_progress

    # Build status line
    parts = [f"{daemon} Fenix {progress}"]

    # Active SPEC and task (compact)
    if active_name:
        short = active_name[:15] + ("…" if len(active_name) > 15 else "")
        if active_task:
            parts.append(f"{active_icon} {short}:{active_task}")
        else:
            parts.append(f"{active_icon} {short}")

    # Done count — only SPECs awaiting push (done, not yet pushed)
    pending_push = sum(1 for e in specs.values() if e.get("status") == "done")
    if pending_push > 0:
        parts.append(f"🚀 {pending_push}")

    # Pushed count — completed and pushed
    pushed = sum(1 for e in specs.values() if e.get("status") == "pushed")
    if pushed > 0:
        parts.append(f"📤 {pushed}")

    # Error/blocker count summary
    error_count = sum(1 for e in specs.values()
                      if e.get("error") and e.get("status") not in ("done", "pushed"))
    if error_count > 0:
        parts.append(f"🚨 {error_count}")

    # Alerts (only show if no error count, to keep it compact)
    if error_count == 0:
        alerts = detect_alerts(specs)
        for icon, msg in alerts:
            parts.append(f"{icon} {msg[:25]}")

    print("  ".join(parts))


if __name__ == "__main__":
    main()
