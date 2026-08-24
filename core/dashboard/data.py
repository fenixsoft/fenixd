"""
data.py — 共享数据聚合层（TUI 与 Web Dashboard 共用）。

把 bin/fenix_dashboard.py 中已验证的 STATE.md / tasks.md / 日志 / 验证产物解析
逻辑提取为以 project_root 为参数的纯函数，并为 Web 增加更丰富的聚合视图（验证
进度、逐场景断言、bug 列表、截图列表、运行记录）。

容错约定：所有解析函数对损坏/缺失数据源绝不抛异常——损坏的 JSON 以带
`"error": "corrupt"` 标记的对象返回，缺失则返回空结构，保证聚合请求不 500。
"""

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

from core.agent_runner import clean_old_runs

# 运行产物文件保留上限（与 agent_runner.RUNS_KEEP 一致）
RUNS_KEEP = 20


# ── 基础解析（源自 bin/fenix_dashboard.py，TUI / Web 共用） ────────────

def parse_state(project_root) -> dict:
    """解析项目 STATE.md，返回 {spec_name: {key: value}}。"""
    state_path = Path(project_root) / "STATE.md"
    if not state_path.exists():
        return {}
    specs = {}
    current_name = None
    current_entry = {}
    try:
        for line in state_path.read_text(encoding="utf-8").split("\n"):
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
                    try:
                        val = int(val)
                    except ValueError:
                        val = 999
                elif val.lower() in ("null", "none", ""):
                    val = None
                current_entry[key] = val
        if current_name and current_entry and "status" in current_entry:
            specs[current_name] = current_entry
    except (OSError, UnicodeDecodeError):
        pass
    return specs


def parse_tasks(project_root, spec_name) -> list:
    """解析 tasks.md 为分组任务结构：[{title, tasks:[{id,desc,done}], done, total}]。"""
    tasks_path = Path(project_root) / "openspec" / "changes" / spec_name / "tasks.md"
    if not tasks_path.exists():
        return []
    groups = []
    current_group = None
    try:
        for line in tasks_path.read_text(encoding="utf-8").split("\n"):
            m = re.match(r"^##\s+\d+\.\s+(.+)$", line)
            if m:
                current_group = {"title": m.group(1), "tasks": [], "done": 0, "total": 0}
                groups.append(current_group)
                continue
            m = re.match(r"^- \[(x| )\] (\d+\.\d+) (.+)$", line)
            if m and current_group is not None:
                is_done = m.group(1) == "x"
                current_group["tasks"].append({
                    "done": is_done,
                    "id": m.group(2),
                    "desc": m.group(3).strip(),
                })
                if is_done:
                    current_group["done"] += 1
                current_group["total"] += 1
    except (OSError, UnicodeDecodeError):
        pass
    return groups


def task_progress(project_root, spec_name):
    """返回 (done, total)，无任务时为 (0, 0)。"""
    groups = parse_tasks(project_root, spec_name)
    done = sum(g["done"] for g in groups)
    total = sum(g["total"] for g in groups)
    return done, total


def count_scenarios(project_root, spec_name) -> int:
    """统计 SPEC 各 spec.md 中 Scenario 数量。"""
    specs_dir = Path(project_root) / "openspec" / "changes" / spec_name / "specs"
    if not specs_dir.is_dir():
        return 0
    count = 0
    try:
        for sf in specs_dir.rglob("*.md"):
            for line in sf.read_text(encoding="utf-8").split("\n"):
                if re.match(r"^####\s+Scenario:", line):
                    count += 1
    except (OSError, UnicodeDecodeError):
        pass
    return count


def get_recent_events(project_root, minutes=10, limit=30) -> list:
    """读取最近 N 分钟的 fenixd 结构化日志事件。"""
    logs_dir = Path(project_root) / ".fenix" / "logs"
    if not logs_dir.is_dir():
        return []
    log_files = sorted(logs_dir.glob("fenixd*.log"), reverse=True)
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    events = []
    for lf in log_files[:2]:
        try:
            for line in lf.read_text(encoding="utf-8").split("\n"):
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = entry.get("timestamp", "")
                if ts < cutoff:
                    continue
                events.append(entry)
        except (OSError, UnicodeDecodeError):
            continue
    return events[-limit:]


# ── 验证产物（容错解析） ──────────────────────────────────────────

def parse_verify_progress(project_root, spec_name) -> dict:
    """解析 .fenix/verify-progress/<spec>.json；损坏/非对象以 error 字段标记。"""
    pf = Path(project_root) / ".fenix" / "verify-progress" / f"{spec_name}.json"
    if not pf.exists():
        return {"exists": False, "total": 0, "done": 0, "current": ""}
    try:
        data = json.loads(pf.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"exists": True, "error": "corrupt", "total": 0, "done": 0, "current": ""}
        return {
            "exists": True,
            "total": int(data.get("total", 0) or 0),
            "done": int(data.get("done", 0) or 0),
            "current": data.get("current", "") or "",
            "step": data.get("step"),
            "error": data.get("error"),
        }
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return {"exists": True, "error": "corrupt", "total": 0, "done": 0, "current": ""}


def parse_report(project_root, spec_name) -> dict:
    """解析 .fenix/verify-progress/<spec>/report.json（逐场景断言结果）。"""
    rp = Path(project_root) / ".fenix" / "verify-progress" / spec_name / "report.json"
    if not rp.exists():
        return {"exists": False}
    try:
        data = json.loads(rp.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"exists": True, "error": "corrupt"}
        return {"exists": True, **data}
    except (json.JSONDecodeError, OSError, TypeError):
        return {"exists": True, "error": "corrupt"}


def parse_test_scenarios(project_root, spec_name) -> list:
    """读取 .fenix/verify-progress/<spec>/test_scenarios.json（尽力解析）。"""
    sp = Path(project_root) / ".fenix" / "verify-progress" / spec_name / "test_scenarios.json"
    if not sp.exists():
        return []
    try:
        data = json.loads(sp.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, OSError, TypeError):
        return []


def list_screenshots(project_root, spec_name) -> list:
    """列出 .fenix/verify-progress/<spec>/screenshots/ 下的截图文件。"""
    ss_dir = Path(project_root) / ".fenix" / "verify-progress" / spec_name / "screenshots"
    if not ss_dir.is_dir():
        return []
    out = []
    try:
        for p in sorted(ss_dir.iterdir()):
            if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
                out.append({
                    "file": p.name,
                    "size": p.stat().st_size,
                    "mtime": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(),
                })
    except OSError:
        pass
    return out


def parse_bugs(project_root, spec_name) -> list:
    """聚合 bug 列表：失败/错误场景（report.json）+ verification-report.md 尽力解析。

    返回: [{"source": "report"|"report-md", "severity", "scenario_ids", "assertion_type",
            "description", "evidence", "screenshots"}]
    """
    bugs = []
    report = parse_report(project_root, spec_name)
    if report.get("exists") and not report.get("error"):
        for sc in report.get("scenarios", []):
            if not isinstance(sc, dict):
                continue
            status = sc.get("status")
            if status not in ("fail", "error"):
                continue
            failed_assertions = [
                a for a in sc.get("assertion_results", [])
                if isinstance(a, dict) and not a.get("pass", True)
            ]
            screenshots = [s for s in sc.get("screenshots", []) if isinstance(s, str)]
            for a in failed_assertions or [{}]:
                bugs.append({
                    "source": "report",
                    "severity": "major" if status == "fail" else "critical",
                    "scenario_ids": [sc.get("scenario_id", "?")],
                    "assertion_type": a.get("type", "step"),
                    "description": sc.get("description", "未命名场景"),
                    "evidence": a.get("message") or a.get("detail") or a.get("actual") or "",
                    "screenshots": screenshots,
                    "scenario_status": status,
                })

    # verification-report.md 尽力解析（宽松：抓取 bug 相关行）
    report_md = Path(project_root) / "openspec" / "changes" / spec_name / "verification-report.md"
    if report_md.exists():
        try:
            content = report_md.read_text(encoding="utf-8")
            lines = content.split("\n")
            current = None
            for i, line in enumerate(lines):
                stripped = line.strip()
                if not stripped:
                    continue
                if re.match(r"^(#{2,4})\s+", line):
                    current = re.sub(r"^#+\s*", "", stripped)
                    continue
                if re.search(r"(bug|Bug|BUG|缺陷|问题|失败|根因)", stripped) and not stripped.startswith(("#", "- [")):
                    severity = "major"
                    if any(k in stripped.lower() for k in ("critical", "严重", "致命", "阻断")):
                        severity = "critical"
                    elif any(k in stripped.lower() for k in ("minor", "轻微", "低")):
                        severity = "minor"
                    bugs.append({
                        "source": "report-md",
                        "severity": severity,
                        "scenario_ids": [],
                        "assertion_type": "",
                        "description": stripped[:200],
                        "evidence": (lines[i + 1].strip()[:200] if i + 1 < len(lines) else ""),
                        "screenshots": [],
                        "section": current,
                    })
        except (OSError, UnicodeDecodeError):
            pass
    return bugs


# ── 运行记录（.fenix/runs/） ─────────────────────────────────────

def classify_run(lines: list) -> str:
    """根据产物文件行判定运行终态：done / error / running / empty。"""
    if not lines:
        return "empty"
    last = lines[-1]
    if not isinstance(last, dict):
        return "running"
    t = last.get("type")
    if t == "result":
        return "done"
    if t == "error":
        return "error"
    return "running"


def get_runs(project_root, spec_name: str | None = None) -> list:
    """列出项目的运行记录（.fenix/runs/*.jsonl）。

    spec_name 省略时返回全部；否则仅返回 run_id 包含该 spec 的记录。
    每条: {run_id, agent_type, spec, status, started, file_size, events}
    """
    runs_dir = Path(project_root) / ".fenix" / "runs"
    if not runs_dir.is_dir():
        return []
    out = []
    try:
        files = sorted(runs_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return []
    for p in files:
        run_id = p.stem
        if spec_name and spec_name not in run_id:
            continue
        try:
            stat = p.stat()
        except OSError:
            continue
        # 从 run_id 推断 agent 类型与 spec：impl-/verify-/planner-plan-/planner-judge-
        agent_type = "agent"
        spec_part = run_id
        for prefix, at in (("planner-judge-", "planner-judge"),
                           ("planner-plan-", "planner-plan"),
                           ("planner-", "planner"),
                           ("impl-", "implementer"),
                           ("verify-", "verifier"),
                           ("test-", "tester")):
            if run_id.startswith(prefix):
                agent_type = at
                spec_part = run_id[len(prefix):]
                break
        # 去掉末尾时间戳（-<ts>）
        m = re.match(r"^(.*)-\d{9,10}$", spec_part)
        if m:
            spec_part = m.group(1)
        lines = _read_run_lines(p, max_lines=3)
        out.append({
            "run_id": run_id,
            "agent_type": agent_type,
            "spec": spec_part,
            "status": classify_run(lines),
            "started": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "file_size": stat.st_size,
        })
    return out


def _read_run_lines(path: Path, max_lines: int = 3) -> list:
    """读取产物文件最后几行 JSON，逐行容错。"""
    out = []
    try:
        with path.open("r", encoding="utf-8") as f:
            # 只读末尾几行判断终态：若文件较小直接读完
            f.seek(0, 2)
            size = f.tell()
            if size > 4096:
                f.seek(max(0, size - 4096))
            else:
                f.seek(0)
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    out.append({"type": "stderr", "line": line})
                if len(out) > max_lines:
                    out.pop(0)
    except OSError:
        pass
    return out


def get_run_events(project_root, run_id: str) -> dict:
    """读取单次运行的完整产物流。

    返回: {run_id, exists, status, events, error}
    events 为逐行解析结果；终态行（result/error）同时以字段暴露。
    """
    run_file = Path(project_root) / ".fenix" / "runs" / f"{run_id}.jsonl"
    if not run_file.exists():
        return {"run_id": run_id, "exists": False, "status": "missing",
                "events": [], "error": None}
    events = []
    error = None
    try:
        with run_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    entry = {"type": "stderr", "line": line}
                if not isinstance(entry, dict):
                    entry = {"type": "stderr", "line": str(entry)}
                events.append(entry)
                if entry.get("type") == "error":
                    error = entry
    except OSError:
        return {"run_id": run_id, "exists": True, "status": "error",
                "events": [], "error": {"error": "unreadable"}}
    return {
        "run_id": run_id,
        "exists": True,
        "status": classify_run(events),
        "events": events,
        "error": error,
    }


def cleanup_runs(project_root) -> int:
    """清理超出保留上限的旧运行产物（跳过活动产物），返回删除数。"""
    runs_dir = Path(project_root) / ".fenix" / "runs"
    return clean_old_runs(runs_dir, keep=RUNS_KEEP)


# ── 聚合视图（供 Web API / 概览 / 详情） ──────────────────────────

def active_run_count(project_root) -> int:
    """统计处于 running / empty（可能正在增长）状态的运行数。"""
    return sum(1 for r in get_runs(project_root) if r["status"] in ("running", "empty"))


def project_summary(project_root, name: str, path: str) -> dict:
    """单个项目的聚合摘要（/api/projects、/api/overview 共用）。"""
    proot = Path(path)
    cleanup_runs(proot)
    specs = parse_state(proot)
    status_counts = {}
    for e in specs.values():
        st = e.get("status", "?") or "?"
        status_counts[st] = status_counts.get(st, 0) + 1

    grand_done = grand_total = 0
    problems = 0
    for sname in specs:
        d, t = task_progress(proot, sname)
        grand_done += d
        grand_total += t
        entry = specs[sname]
        if entry.get("error") and entry.get("status") not in ("done", "pushed"):
            problems += 1

    runs = get_runs(proot)
    active = sum(1 for r in runs if r["status"] in ("running", "empty"))

    return {
        "name": name,
        "path": str(path),
        "spec_count": len(specs),
        "status_counts": status_counts,
        "task_done": grand_done,
        "task_total": grand_total,
        "problems": problems,
        "active_runs": active,
        "scenario_count": sum(count_scenarios(proot, s) for s in specs),
        "updated": (Path(path) / "STATE.md").stat().st_mtime if (Path(path) / "STATE.md").exists() else 0,
    }


def spec_summary(project_root, spec_name: str, entry: dict) -> dict:
    """单个 SPEC 的摘要（/api/specs 列表项）。"""
    done, total = task_progress(project_root, spec_name)
    vp = parse_verify_progress(project_root, spec_name)
    runs = get_runs(project_root, spec_name)
    return {
        "name": spec_name,
        "status": entry.get("status"),
        "priority": entry.get("priority"),
        "error": entry.get("error"),
        "task_done": done,
        "task_total": total,
        "verify_done": vp.get("done", 0),
        "verify_total": vp.get("total", 0),
        "verify_error": vp.get("error"),
        "scenario_count": count_scenarios(project_root, spec_name),
        "latest_run": runs[0]["run_id"] if runs else None,
        "latest_run_status": runs[0]["status"] if runs else None,
    }


def spec_detail(project_root, spec_name: str, entry: dict) -> dict:
    """单个 SPEC 的完整详情（/api/specs/<spec>）。"""
    report = parse_report(project_root, spec_name)
    bugs = parse_bugs(project_root, spec_name)
    scenarios = report.get("scenarios", []) if report.get("exists") and not report.get("error") else []
    screenshots = list_screenshots(project_root, spec_name)
    runs = get_runs(project_root, spec_name)
    return {
        "name": spec_name,
        "status": entry.get("status"),
        "priority": entry.get("priority"),
        "created": entry.get("created"),
        "updated": entry.get("updated"),
        "error": entry.get("error"),
        "branch": entry.get("branch"),
        "implementer_run": entry.get("implementer_run"),
        "tester_run": entry.get("tester_run"),
        "depends_on": entry.get("depends_on"),
        "tasks": parse_tasks(project_root, spec_name),
        "verify_progress": parse_verify_progress(project_root, spec_name),
        "report": {
            "exists": report.get("exists", False),
            "error": report.get("error"),
            "timestamp": report.get("timestamp"),
            "summary": report.get("summary"),
        },
        "scenarios": scenarios,
        "bugs": bugs,
        "screenshots": screenshots,
        "runs": runs,
    }


def overview(registry_projects: list) -> dict:
    """跨项目概览（/api/overview）。registry_projects 为 registry.discover() 结果。"""
    projects = []
    totals = {"spec_count": 0, "task_done": 0, "task_total": 0,
              "problems": 0, "active_runs": 0}
    status_counts = {}
    for p in registry_projects:
        if not p.get("exists"):
            projects.append({
                "name": p["name"], "path": p["path"], "discovered": p.get("discovered", False),
                "exists": False, "error": "项目路径不存在",
            })
            continue
        s = project_summary(p["path"], p["name"], p["path"])
        s["discovered"] = p.get("discovered", False)
        s["exists"] = True
        projects.append(s)
        totals["spec_count"] += s["spec_count"]
        totals["task_done"] += s["task_done"]
        totals["task_total"] += s["task_total"]
        totals["problems"] += s["problems"]
        totals["active_runs"] += s["active_runs"]
        for st, n in s["status_counts"].items():
            status_counts[st] = status_counts.get(st, 0) + n
    totals["status_counts"] = status_counts
    return {"projects": projects, "totals": totals}
