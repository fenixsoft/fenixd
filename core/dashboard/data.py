"""
data.py — 共享数据聚合层（TUI 与 Web Dashboard 共用）。

把 bin/fenix_dashboard.py 中已验证的 STATE.md / tasks.md / 日志 / 验证产物解析
逻辑提取为以 project_root 为参数的纯函数，并为 Web 增加更丰富的聚合视图（验证
进度、逐场景断言、bug 列表、截图列表、运行记录）。

容错约定：所有解析函数对损坏/缺失数据源绝不抛异常——损坏的 JSON 以带
`"error": "corrupt"` 标记的对象返回，缺失则返回空结构，保证聚合请求不 500。
"""

import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

from core.agent_runner import clean_old_runs
from core.fenix_session import is_running as _is_running

# 运行产物文件保留上限（与 agent_runner.RUNS_KEEP 一致）
RUNS_KEEP = 20


# ── Administrator 告警（.fenix/admin_alerts.json） ─────────────────

def get_alerts(project_root) -> list:
    """读取项目全部 Administrator 告警/处置记录（最新在前）。缺失/损坏返回 []。"""
    from core.admin_store import AdminStore
    return AdminStore(project_root).read_all()


def get_unhandled_alerts(project_root) -> list:
    """读取项目未处理的升级告警（最新在前）。"""
    from core.admin_store import AdminStore
    return AdminStore(project_root).unhandled()


def mark_alert_handled(project_root, alert_id: str) -> bool:
    """标记某条升级告警为已处理。返回是否找到并更新。"""
    from core.admin_store import AdminStore
    return AdminStore(project_root).mark_handled(alert_id)


def alerts_summary(project_root) -> dict:
    """项目告警摘要：{unhandled_count, max_severity, latest}。

    max_severity 取未处理告警中最高严重度（critical > major > minor）；
    latest 为最新一条未处理告警。无未处理时三者为空/0。
    """
    unhandled = get_unhandled_alerts(project_root)
    if not unhandled:
        return {"unhandled_count": 0, "max_severity": None, "latest": None}
    sev_rank = {"critical": 3, "major": 2, "minor": 1}
    top = max(unhandled, key=lambda a: sev_rank.get(a.get("severity"), 0))
    return {
        "unhandled_count": len(unhandled),
        "max_severity": top.get("severity"),
        "latest": unhandled[0],
    }


def get_admin_activities(project_root) -> list:
    """返回 Administrator 处置活动记录（运维记录时间线数据源）。

    从 admin_alerts.json 过滤 kind=disposition，按时间倒序；与未处理升级
    escalation 关联（同 admin_run_id）的记录置顶，并标记 handled=False +
    escalation_id（供前端 mark-handled）。旧记录无 summary 时原样返回，
    界面降级显示结构化字段（design D1，向后兼容）。
    """
    from core.admin_store import AdminStore, DISPOSITION, ESCALATION
    records = AdminStore(project_root).read_all()

    # 未处理升级 → 关联 disposition（按 admin_run_id 匹配）
    unhandled_by_run: dict = {}
    for rec in records:
        if (rec.get("kind") == ESCALATION and not rec.get("handled")
                and rec.get("admin_run_id")):
            unhandled_by_run.setdefault(rec["admin_run_id"], rec.get("id"))

    activities = []
    # 按 admin_run_id 归并：pending 是 admin 唤起时的标记记录，同 run 一旦产生
    # 最终 disposition（result != pending）即以最终为准，避免页面出现"永久处置中"。
    best_by_run: dict = {}
    for rec in records:
        if rec.get("kind") != DISPOSITION:
            continue
        rid = rec.get("admin_run_id") or f"run-{id(rec)}"
        status = rec.get("status") or rec.get("result")
        is_pending = status == "pending"
        existing = best_by_run.get(rid)
        if existing is None:
            best_by_run[rid] = (is_pending, rec)
            continue
        # 非 pending 优先于 pending；同为非 pending 取最新
        if is_pending and not existing[0]:
            continue
        if not is_pending and existing[0]:
            best_by_run[rid] = (False, rec)
        elif (rec.get("created") or "") > (existing[1].get("created") or ""):
            best_by_run[rid] = (is_pending, rec)

    for _is_pending, rec in best_by_run.values():
        item = dict(rec)
        esc_id = unhandled_by_run.get(rec.get("admin_run_id"))
        item["handled"] = esc_id is None
        item["escalation_id"] = esc_id
        item["actions_taken"] = rec.get("actions_taken") or rec.get("action_taken") or ""
        item["_pin"] = esc_id is not None
        activities.append(item)

    # 未处理升级关联置顶，组内按时间倒序
    activities.sort(
        key=lambda a: (a["_pin"], a.get("created") or ""), reverse=True)
    for a in activities:
        a.pop("_pin", None)
    return activities


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


def find_implementer_worktree(project_root, spec_name):
    """Find the newest implementer worktree for a SPEC, or None."""
    wt_dir = Path(project_root) / ".claude" / "worktrees"
    if not wt_dir.is_dir():
        return None
    prefix = f"impl-{spec_name}-"
    candidates = []
    for d in wt_dir.iterdir():
        if d.is_dir() and d.name.startswith(prefix):
            try:
                candidates.append((d.stat().st_mtime, d))
            except OSError:
                pass
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


# ── 实时任务完成状态叠加（run 记录 → tasks.md） ───────────────────
#
# 背景：implementer Agent 用 Claude 会话内 TaskCreate/TaskUpdate 工具实时汇报
# 任务完成（见 .fenix/runs/impl-<spec>-*.jsonl 的 assistant tool_use），从不编辑
# tasks.md，导致 Dashboard 任务进度永远 0/N。这里从最新 impl run 产物解析实时
# 完成状态，叠加到 tasks.md 快照上（逐任务并集），使 Dashboard 实时反映进度。
_TASK_ID_RE = re.compile(r"Task\s+#?\s*(\d+\.\d+)")
# _parse_run_task_done 的 memo 缓存：run 文件 O_APPEND 只增，mtime/size 不变即命中。
# 上限 64 项，超出整体清空，防止 append-only 文件每次追加换键导致无界增长。
_RUN_TASK_CACHE: dict = {}


def _find_impl_run_file(project_root, spec_name) -> Path | None:
    """最新一次 impl-<spec>-*.jsonl 运行产物，或 None。

    运行中 STATE.md 的 implementer_run 字段为空，不能用它定位；
    按 mtime 取最新与 worktree 选择（find_implementer_worktree）一致。
    """
    runs_dir = Path(project_root) / ".fenix" / "runs"
    if not runs_dir.is_dir():
        return None
    candidates = []
    try:
        for p in runs_dir.glob(f"impl-{spec_name}-*.jsonl"):
            try:
                candidates.append((p.stat().st_mtime, p))
            except OSError:
                pass
    except OSError:
        return None
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def _parse_run_task_done(run_file: Path) -> dict:
    """解析 impl run 产物的 harness 任务完成状态（容错：任何损坏都不抛异常）。

    TaskCreate 的 input.subject 内嵌 tasks.md id（如 "Task 1.1: ..."）；
    TaskUpdate 的 taskId 为 1 基创建序（tool_result 形如 "Task #1 created ..."）。

    Returns:
        {"done_ids": set[str],   # 已完成且已创建的 tasks.md id（如 {"1.1","2.3"}）
         "created_count": int,    # TaskCreate 次数（flat 回退对齐上限）
         "flat_done": set[int]}   # 已完成任务的创建序下标（0-based，flat 回退用）
    """
    try:
        st = run_file.stat()
        key = (str(run_file), st.st_mtime_ns, st.st_size)
    except OSError:
        return {"done_ids": set(), "created_count": 0, "flat_done": set()}
    cached = _RUN_TASK_CACHE.get(key)
    if cached is not None:
        return cached

    created_ordered: list = []  # 按创建序的 subject 提取 tasks.md id（无 id 记 None）
    completed_idx: set = set()  # TaskUpdate completed 的 taskId - 1
    try:
        with run_file.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict) or entry.get("type") != "assistant":
                    continue
                for c in (entry.get("message") or {}).get("content") or []:
                    if not isinstance(c, dict) or c.get("type") != "tool_use":
                        continue
                    if c.get("name") == "TaskCreate":
                        m = _TASK_ID_RE.search(str((c.get("input") or {}).get("subject") or ""))
                        created_ordered.append(m.group(1) if m else None)
                    elif c.get("name") == "TaskUpdate":
                        inp = c.get("input") or {}
                        try:
                            n = int(str(inp.get("taskId")))  # 兼容 str/int
                        except (TypeError, ValueError):
                            continue
                        if inp.get("status") == "completed":
                            completed_idx.add(n - 1)
    except OSError:
        return {"done_ids": set(), "created_count": 0, "flat_done": set()}

    created_count = len(created_ordered)
    done_ids = set()
    for idx in completed_idx:
        if 0 <= idx < created_count and created_ordered[idx]:
            done_ids.add(created_ordered[idx])
    flat_done = {i for i in completed_idx if 0 <= i < created_count}

    result = {"done_ids": done_ids, "created_count": created_count, "flat_done": flat_done}
    if len(_RUN_TASK_CACHE) > 64:
        _RUN_TASK_CACHE.clear()
    _RUN_TASK_CACHE[key] = result
    return result


# 实时叠加生效的生命周期状态（含实现完成后的验证期）。ready/drafted 不叠加，
# 避免重试过渡期旧 run 的完成数误导。
_LIVE_OVERLAY_STATUSES = {"implementing", "implemented", "testing", "bug-found"}


def _should_overlay(spec_status: str, has_uncompleted: bool) -> bool:
    """是否需要用 run 记录实时完成状态叠加 tasks.md 快照。"""
    if spec_status in _LIVE_OVERLAY_STATUSES:
        return True
    # done/pushed：仅当 tasks.md 仍有未勾选任务时叠加（覆盖实现者从不勾 tasks.md 的现状）
    return spec_status in ("done", "pushed") and has_uncompleted


def parse_tasks(project_root, spec_name, spec_status: str = "", *, live: bool = True) -> list:
    """解析 tasks.md 为分组任务结构：[{title, tasks:[{id,desc,done}], done, total}]。

    For implementing SPECs, reads from the active implementer worktree first.
    live=True 时按 _should_overlay 叠加最新 impl run 的实时完成状态（并集）。
    """
    tasks_path = Path(project_root) / "openspec" / "changes" / spec_name / "tasks.md"
    if spec_status == "implementing":
        wt = find_implementer_worktree(project_root, spec_name)
        if wt:
            wt_tasks = wt / "openspec" / "changes" / spec_name / "tasks.md"
            if wt_tasks.exists():
                tasks_path = wt_tasks
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
    if not groups:
        return groups
    # 实时叠加：最新 impl run 的 TaskUpdate 完成状态与 tasks.md 勾选取并集。
    # 主路径按 tasks.md id 精确对齐；subject 无 id（未来 harness 变体）时回退扁平下标。
    if live and _should_overlay(
        spec_status, any(not t["done"] for g in groups for t in g["tasks"])
    ):
        run_file = _find_impl_run_file(project_root, spec_name)
        if run_file is not None:
            rd = _parse_run_task_done(run_file)
            overlaid = False
            if rd["done_ids"]:
                by_id = {t["id"]: t for g in groups for t in g["tasks"]}
                for tid in rd["done_ids"]:
                    t = by_id.get(tid)
                    if t is not None:
                        t["done"] = True
                        overlaid = True
            elif rd["flat_done"]:
                flat = [t for g in groups for t in g["tasks"]]
                bound = min(rd["created_count"], len(flat))
                for i in rd["flat_done"]:
                    if 0 <= i < bound:
                        flat[i]["done"] = True
                        overlaid = True
            if overlaid:
                # 重算分组计数（前端分组头依赖 g.done / g.total）
                for g in groups:
                    g["done"] = sum(1 for t in g["tasks"] if t["done"])
                    g["total"] = len(g["tasks"])
    return groups


def task_progress(project_root, spec_name, spec_status: str = ""):
    """返回 (done, total)，无任务时为 (0, 0)。"""
    groups = parse_tasks(project_root, spec_name, spec_status)
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


def _fold_summary(summary: dict, key: str, val: str) -> dict:
    """把表格/行内的计数键值折进汇总字典；非计数键忽略。"""
    if val.lower() in ("n/a", "-", "--", "—"):
        return summary
    k = key.lower().replace(" ", "").replace("数", "")
    if k in ("产品bug", "产品", "bug"):
        summary["product_bugs"] = val
    elif k in ("环境问题", "环境"):
        summary["env_issues"] = val
    elif k in ("通过", "passed", "通过数"):
        summary["passed"] = val
    elif k in ("失败", "failed", "失败数"):
        summary["failed"] = val
    elif k in ("错误", "error", "errors", "错误数"):
        summary["errors"] = val
    return summary


def parse_verdict(project_root, spec_name) -> dict:
    """解析 verification-report.md 的验证结论，供 Dashboard 直接展示。

    返回: {"exists", "status", "status_detail", "conclusion", "summary"}
    - status: 结论标题（如 "环境不可达，无法验证" / "❌ 未通过（Bug Found）"）
    - status_detail: **状态:** 行（如 "环境问题 — Dashboard 服务未启动"）
    - conclusion: 结论段落（人类可读，避免用户只看 "0通过, 31失败"）
    - summary: {"passed","failed","errors","product_bugs","env_issues"} 尽力解析
    """
    path = Path(project_root) / "openspec" / "changes" / spec_name / "verification-report.md"
    if not path.exists():
        return {"exists": False, "status": "", "status_detail": "", "conclusion": "", "summary": {}}
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        content = ""

    summary = {"passed": None, "failed": None, "errors": None,
               "product_bugs": None, "env_issues": None}
    status = ""
    status_detail = ""
    conclusion = ""
    conclusion_mode = False

    for raw in content.split("\n"):
        s = raw.strip()
        # 结论标题：## 结论[: 内联] 或 ## 结论摘要
        m = re.match(r"^#{2,4}\s*结论\s*(?:摘要)?\s*[：:]?\s*(.*)$", s)
        if m:
            status = m.group(1).strip() or status
            conclusion_mode = True
            continue
        if conclusion_mode:
            if re.match(r"^#{2,4}\s+", s):
                conclusion_mode = False
            elif s.startswith("**状态"):
                status_detail = re.sub(r"^.*?状态\s*[：:]\s*|\*\*\s*$", "", s).strip()
            elif s and not s.startswith(("|", "---", "-", "**", ">")):
                conclusion += (" " if conclusion else "") + s
        # 备选状态：**验证结果**：❌ 未通过（Bug Found）
        m2 = re.match(r"^\*\*\s*验证结果\s*\*\*\s*[：:]\s*(.+)$", s)
        if m2 and not status:
            status = m2.group(1).strip()
        # 表格行：| 通过 | 0 |
        m3 = re.match(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", s)
        if m3:
            summary = _fold_summary(summary, m3.group(1), m3.group(2).strip())
            continue
        # 行内计数：通过：0
        m4 = re.match(r"^([^|#]{1,12})\s*[：:]\s*([\dN/A\-＋+]+)\s*$", s)
        if m4:
            summary = _fold_summary(summary, m4.group(1), m4.group(2).strip())

    # 兜底：全文搜索计数（处理 "通过：0 | 失败：0 | 错误：10" 行内连写）
    if any(v is None for v in summary.values()):
        for pat, field in [("通过", "passed"), ("失败", "failed"), ("错误", "errors"),
                           (r"产品\s*Bug", "product_bugs"), ("环境问题", "env_issues")]:
            if summary[field] is not None:
                continue
            mm = re.search(r"%s\s*[：:]\s*([\dN/A\-＋+]+)" % pat, content, re.I)
            if mm and mm.group(1).strip().lower() not in ("n/a", "-", "--"):
                summary[field] = mm.group(1).strip()

    return {
        "exists": True,
        "status": status,
        "status_detail": status_detail,
        "conclusion": " ".join(conclusion.split())[:600],
        "summary": summary,
    }


def parse_bugs(project_root, spec_name) -> list:
    """聚合 bug 列表：来自 report.json 的失败/错误场景。

    返回: [{"source": "report", "severity", "scenario_ids", "assertion_type",
            "description", "evidence", "screenshots"}]

    bug 只从结构化的 report.json 提取（每条失败/错误场景 + 失败断言 + 截图）。
    不再从 verification-report.md 逐行正则猜测——Markdown 是人读文档，逐行抓
    「bug/缺陷/失败」关键词会把「环境失败」「被修复缺陷的背景描述」「通过型报告」
    误判为产品缺陷（add-parallelism、fix-worktree-agent-cwd、fix-add-parallelism 等
    均因此产生过大量虚假 bug）。
    """
    bugs = []
    report = parse_report(project_root, spec_name)
    if not report.get("exists") or report.get("error"):
        return bugs
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
        # 截图路径归一化为文件名：report.json 存的是服务器本地绝对路径，
        # 前端需拼 /screenshots/<project>/<spec>/<file>，只取 basename
        screenshots = [os.path.basename(s) for s in sc.get("screenshots", []) if isinstance(s, str) and s.strip()]
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
        # 耗时：run_id 尾部时间戳为起始（int(time.time())），文件 mtime 为终止
        tm = re.search(r"-(\d{9,10})$", run_id)
        start_ts = int(tm.group(1)) if tm else stat.st_mtime
        duration_seconds = max(0, int(stat.st_mtime - start_ts))
        lines = _read_run_lines(p, max_lines=3)
        out.append({
            "run_id": run_id,
            "agent_type": agent_type,
            "spec": spec_part,
            "status": classify_run(lines),
            "duration_seconds": duration_seconds,
            "started": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "file_size": stat.st_size,
        })
    return out


def _read_run_lines(path: Path, max_lines: int = 3) -> list:
    """读取产物文件最后几行 JSON，逐行容错。"""
    out = []
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if size > 4096:
                f.seek(max(0, size - 4096))
            else:
                f.seek(0)
            raw = f.read()
        # 向前扫描到合法 UTF-8 起始字节，避免 seek 落在多字节字符中间
        start = 0
        while start < len(raw) and (raw[start] & 0xC0) == 0x80:
            start += 1
        text = raw[start:].decode("utf-8", errors="replace")
        for line in text.splitlines():
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


def _parse_run_lines(lines) -> list:
    """逐行解析 JSONL 行序列为事件（容错：损坏行降级为 stderr 条目）。"""
    events = []
    for line in lines:
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
    return events


def get_run_events(project_root, run_id: str, tail: int = 300) -> dict:
    """读取单次运行产物流的尾部（前端只展示最近 N 条，全量拉取是浪费）。

    返回: {run_id, exists, status, events, total_events, error}
    events 为最后 tail 条逐行解析结果；status/error 仍由全文件判定
    （终态行 result/error 决定），total_events 为实际总事件数。
    """
    run_file = Path(project_root) / ".fenix" / "runs" / f"{run_id}.jsonl"
    if not run_file.exists():
        return {"run_id": run_id, "exists": False, "status": "missing",
                "events": [], "total_events": 0, "error": None}
    events = []
    error = None
    try:
        with run_file.open("r", encoding="utf-8", errors="replace") as f:
            for entry in _parse_run_lines(f):
                events.append(entry)
                if entry.get("type") == "error":
                    error = entry
    except OSError:
        return {"run_id": run_id, "exists": True, "status": "error",
                "events": [], "total_events": 0, "error": {"error": "unreadable"}}
    return {
        "run_id": run_id,
        "exists": True,
        "status": classify_run(events),
        "events": events[-tail:],
        "total_events": len(events),
        "error": error,
    }


def read_run_events_between(project_root, run_id: str, start_offset: int) -> list:
    """读取运行产物从 start_offset 字节到 EOF 的事件（增量推送用）。

    O_APPEND 只增写：按上次记录的字节偏移读取新增部分，避免整文件重读。
    跨扫描边界被截断的半个 JSON 行会降级为 stderr 条目（_parse_run_lines 容错）。
    """
    run_file = Path(project_root) / ".fenix" / "runs" / f"{run_id}.jsonl"
    try:
        with run_file.open("rb") as f:
            f.seek(start_offset)
            raw = f.read()
    except OSError:
        return []
    text = raw.decode("utf-8", errors="replace")
    return _parse_run_lines(text.splitlines())


def cleanup_runs(project_root) -> int:
    """清理超出保留上限的旧运行产物（跳过活动产物），返回删除数。"""
    runs_dir = Path(project_root) / ".fenix" / "runs"
    return clean_old_runs(runs_dir, keep=RUNS_KEEP)


# ── 聚合视图（供 Web API / 概览 / 详情） ──────────────────────────

def active_run_count(project_root) -> int:
    """统计处于 running / empty（可能正在增长）状态的运行数。"""
    return sum(1 for r in get_runs(project_root) if r["status"] in ("running", "empty"))


# ── daemon 健康检测（D4：TTL memo 避免高频轮询重复 spawn tmux） ──────

_DAEMON_HEALTH_TTL = 5.0   # 秒；结果在 TTL 内复用
_DAEMON_HEALTH_CACHE: dict = {}   # key=规范化项目根, value=(状态, 时间戳)


def daemon_health(project_root) -> str:
    """项目 fenixd daemon 是否在运行，返回 "running"/"stopped"。

    判定复用 core.fenix_session.is_running（唯一 tmux session + 旧版 `fenixd`
    session cwd 匹配）。tmux 不可用、subprocess 异常或均未命中一律 "stopped"，
    不抛异常。带短 TTL memo，避免 overview 每 2s 轮询重复 spawn 子进程。
    """
    key = str(Path(project_root).expanduser().resolve())
    now = time.monotonic()
    cached = _DAEMON_HEALTH_CACHE.get(key)
    if cached is not None and now - cached[1] < _DAEMON_HEALTH_TTL:
        return cached[0]
    try:
        status = "running" if _is_running(key) else "stopped"
    except Exception:
        status = "stopped"
    if len(_DAEMON_HEALTH_CACHE) > 256:
        _DAEMON_HEALTH_CACHE.clear()
    _DAEMON_HEALTH_CACHE[key] = (status, now)
    return status


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
        entry = specs[sname]
        d, t = task_progress(proot, sname, entry.get("status", ""))
        grand_done += d
        grand_total += t
        if entry.get("error") and entry.get("status") not in ("done", "pushed"):
            problems += 1

    runs = get_runs(proot)
    active = sum(1 for r in runs if r["status"] in ("running", "empty"))

    return {
        "name": name,
        "path": str(path),
        "daemon": daemon_health(proot),
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
    done, total = task_progress(project_root, spec_name, entry.get("status", ""))
    vp = parse_verify_progress(project_root, spec_name)
    runs = get_runs(project_root, spec_name)
    return {
        "name": spec_name,
        "status": entry.get("status"),
        "priority": entry.get("priority"),
        "created": entry.get("created"),
        "updated": entry.get("updated"),
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


# ── SPEC 生命周期时间轴 ──────────────────────────────────────────

_LIFECYCLE_ORDER = {"drafted": 0, "ready": 1, "implementing": 2, "bug-found": 2.5,
                    "implemented": 3, "testing": 4, "verified": 5, "done": 6, "pushed": 7}


def _backtrack_reason(frm: str, to: str) -> str:
    """状态回退的规则兜底原因（Agent 记录的 error 优先，见 get_spec_timeline）。"""
    if to == "bug-found":
        return "验证发现 bug，退回修复"
    if frm == "testing" and to in ("implementing", "ready"):
        return "验证失败/中断，回退实现"
    if frm == "implemented" and to in ("implementing", "ready"):
        return "实现未通过，回退重做"
    if frm == "ready" and to == "ready":
        return "实现失败，重试"
    return "状态回退"


def get_spec_timeline(project_root, spec_name: str) -> list:
    """构建 SPEC 生命周期时间轴（按时间排序）。

    数据源：
    - 事件日志（fenixd*.log）中的 `Transition: <spec> from → to` → 状态节点
    - `.fenix/runs/` 运行产物 → 运行节点（可点击展开 LLM 对话）

    每条:
    - 状态: {time, kind:"state", from, to, reason}  （回退节点带 reason）
    - 运行: {time, kind:"run", run_id, agent_type, status}
    """
    logs_dir = Path(project_root) / ".fenix" / "logs"
    events: list[dict] = []
    errors_at: list[tuple] = []   # (timestamp, error) —— Agent 记录的 error，作为回退原因

    if logs_dir.is_dir():
        try:
            log_files = sorted(logs_dir.glob("fenixd*.log"), reverse=True)
        except OSError:
            log_files = []
        for lf in log_files[:2]:
            try:
                content = lf.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            pat = re.compile(r"Transition: " + re.escape(spec_name) + r"\s+([\w-]+)\s*→\s*([\w-]+)")
            for line in content.split("\n"):
                if spec_name not in line:
                    continue
                try:
                    entry = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                msg = entry.get("message", "")
                ts = entry.get("timestamp", "")
                m = pat.search(msg)
                if m:
                    frm, to = m.group(1), m.group(2)
                    reason = ""
                    if _LIFECYCLE_ORDER.get(to, 9) < _LIFECYCLE_ORDER.get(frm, 9):
                        reason = _backtrack_reason(frm, to)
                    events.append({"time": ts, "kind": "state", "from": frm, "to": to, "reason": reason})
                if "Updated SPEC" in msg and spec_name in msg:
                    updates = entry.get("context", {}).get("updates", {}) or {}
                    err = updates.get("error")
                    if err:
                        errors_at.append((ts, str(err)))

    # 运行节点
    for r in get_runs(project_root, spec_name):
        events.append({"time": r["started"], "kind": "run", "run_id": r["run_id"],
                       "agent_type": r["agent_type"], "status": r["status"],
                       "spec": r.get("spec"),
                       "duration_seconds": r.get("duration_seconds")})

    events.sort(key=lambda e: e["time"])

    # 连续的前向状态转换折叠为一次（回退/运行节点打断）
    events = _collapse_timeline(events)

    # 回退节点补充 Agent 记录的 error 作为原因（取时间最近的一条，10 分钟内）
    if errors_at:
        for e in events:
            if e.get("kind") != "state" or not e.get("reason"):
                continue
            deltas = [(d, err) for (ts, err) in errors_at
                      if (d := _ts_delta(ts, e["time"])) is not None]
            if deltas:
                d, err = min(deltas, key=lambda x: x[0])
                if d < 600:   # 10 分钟内匹配到 Agent 记录的 error
                    e["reason"] = err[:120]
    return events


def _collapse_timeline(events: list) -> list:
    """把连续的前向状态转换折叠为一次（from[首] → to[尾]）。

    规则：
    - 连续出现的「前向状态节点」（无 reason）合并为一个节点，展示整体跨度；
      如 drafted→ready / ready→implementing / … → 折叠为 drafted → implementing。
    - 回退节点（带 reason，如 testing→bug-found）与运行节点保持独立，并打断合并。
    """
    out: list[dict] = []
    buf: list[dict] = []   # 待合并的前向状态节点缓冲
    for e in events:
        if e.get("kind") == "state" and not e.get("reason"):
            buf.append(e)
            continue
        # 遇到回退状态 / 运行节点 / 其它 → 先冲刷缓冲，再追加当前事件
        if buf:
            out.append({
                "time": buf[0]["time"], "kind": "state",
                "from": buf[0]["from"], "to": buf[-1]["to"], "reason": "",
            })
            buf = []
        out.append(e)
    if buf:
        out.append({
            "time": buf[0]["time"], "kind": "state",
            "from": buf[0]["from"], "to": buf[-1]["to"], "reason": "",
        })
    return out


def _ts_delta(a: str, b: str):
    """两个 ISO 时间戳的秒级差值（解析失败返回 None）。"""
    try:
        from datetime import datetime as _dt
        ta = _dt.fromisoformat(a.replace("Z", "+00:00"))
        tb = _dt.fromisoformat(b.replace("Z", "+00:00"))
        return abs((ta - tb).total_seconds())
    except Exception:
        return None


def spec_detail(project_root, spec_name: str, entry: dict) -> dict:
    """单个 SPEC 的完整详情（/api/specs/<spec>）。"""
    report = parse_report(project_root, spec_name)
    bugs = parse_bugs(project_root, spec_name)
    scenarios = report.get("scenarios", []) if report.get("exists") and not report.get("error") else []
    # 场景内截图同样归一化为文件名（report.json 存的是服务器本地绝对路径）
    scenarios = [
        {**sc, "screenshots": [os.path.basename(s) for s in sc.get("screenshots", []) if isinstance(s, str) and s.strip()]}
        if isinstance(sc, dict) else sc
        for sc in scenarios
    ]
    screenshots = list_screenshots(project_root, spec_name)
    runs = get_runs(project_root, spec_name)
    verdict = parse_verdict(project_root, spec_name)
    spec_status = entry.get("status", "")
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
        "tasks": parse_tasks(project_root, spec_name, spec_status),
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
        "verdict": verdict,
        "timeline": get_spec_timeline(project_root, spec_name),
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
                "exists": False, "daemon": "stopped", "error": "项目路径不存在",
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


# ── 配置读写（受管键：llm / agents.models / agents.max_concurrent / gates.approve_mode） ──

# Dashboard 管理的配置键子集：写回时只更新这些键，其它键原样保留
_MANAGED_KEYS = ["llm", "agents", "gates"]
# 在 agents 下管理的子键白名单
_AGENTS_MANAGED_SUBKEYS = ["models", "max_concurrent"]

_CONFIG_HEADER_COMMENT = (
    "# Fenix 配置文件\n"
    "# 本文件可通过 Dashboard 或手工编辑修改；修改后需重启 daemon 生效。\n"
    "# 敏感字段（如 apikey）请妥善保管，.fenix/ 目录已 gitignore。\n"
    "\n"
)


def read_config(project_root) -> dict:
    """读取项目 .fenix/config.yaml，返回受管配置段。

    返回: {"llm": {...}, "agents": {"models": {...}, "max_concurrent": int},
            "gates": {"approve_mode": ...}, "raw_exists": bool, "error": str|null}
    容错：文件不存在返回空结构 + raw_exists=False；解析失败返回 error。
    """
    proot = Path(project_root)
    config_path = proot / ".fenix" / "config.yaml"
    result = {
        "llm": {},
        "agents": {"models": {}, "max_concurrent": 2},
        "gates": {"approve_mode": "manual"},
        "raw_exists": False,
        "error": None,
    }
    if not config_path.exists():
        return result
    result["raw_exists"] = True
    try:
        with config_path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError) as e:
        result["error"] = f"配置文件解析失败: {e}"
        return result
    if not isinstance(raw, dict):
        result["error"] = "配置文件顶层不是对象"
        return result

    # 提取受管键（白名单：llm / agents.models / agents.max_concurrent / gates.approve_mode）
    if isinstance(raw.get("llm"), dict):
        result["llm"] = raw["llm"]
    agents_raw = raw.get("agents")
    if isinstance(agents_raw, dict):
        agents_result = {}
        if isinstance(agents_raw.get("models"), dict):
            agents_result["models"] = agents_raw["models"]
        if isinstance(agents_raw.get("max_concurrent"), int):
            agents_result["max_concurrent"] = agents_raw["max_concurrent"]
        if agents_result:
            # 只在结果中有受管键时覆盖默认，避免清空默认值
            for k, v in agents_result.items():
                result["agents"][k] = v
    gates_raw = raw.get("gates")
    if isinstance(gates_raw, dict) and "approve_mode" in gates_raw:
        result["gates"] = {"approve_mode": gates_raw["approve_mode"]}
    return result


def _deep_merge_managed(raw_config: dict, patch: dict) -> dict:
    """把 patch 中的受管键合并到 raw_config，返回新 dict（不修改原对象）。

    合并规则（白名单化）：
    - llm: 整体替换（patch 中存在即替换，不存在则保留原 llm）
    - agents.models: 整体替换（只动 models，其它 agents 子键保留）
    - agents.max_concurrent: 替换（仅 patch 中提供且为正整数时）
    - gates.approve_mode: 只替换 approve_mode 子键
    """
    import copy
    merged = copy.deepcopy(raw_config)

    if "llm" in patch:
        merged["llm"] = copy.deepcopy(patch["llm"])

    if "agents" in patch and isinstance(patch["agents"], dict):
        if not isinstance(merged.get("agents"), dict):
            merged["agents"] = {}
        if "models" in patch["agents"]:
            merged["agents"]["models"] = copy.deepcopy(patch["agents"]["models"])
        if "max_concurrent" in patch["agents"]:
            merged["agents"]["max_concurrent"] = patch["agents"]["max_concurrent"]

    if "gates" in patch and isinstance(patch["gates"], dict):
        if "approve_mode" in patch["gates"]:
            if not isinstance(merged.get("gates"), dict):
                merged["gates"] = {}
            merged["gates"]["approve_mode"] = patch["gates"]["approve_mode"]

    return merged


def write_config(project_root, config_patch: dict) -> dict:
    """把受管配置段写回 .fenix/config.yaml（原子写、保留非受管键）。

    写入前使用 ConfigLoader 做完整校验，校验失败返回错误且不写盘。

    Args:
        project_root: 项目根路径
        config_patch: 含 llm / agents.models / gates.approve_mode 的 patch dict

    Returns: {"ok": bool, "error": str|null}
    """
    from core.config import ConfigLoader

    proot = Path(project_root)
    config_path = proot / ".fenix" / "config.yaml"
    config_dir = config_path.parent

    # 1. 读取现有配置（若不存在则为空 dict，写入时创建）
    raw = {}
    if config_path.exists():
        try:
            with config_path.open("r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
            if isinstance(loaded, dict):
                raw = loaded
        except (yaml.YAMLError, OSError) as e:
            return {"ok": False, "error": f"读取现有配置失败: {e}"}

    # 2. 合并受管键
    merged = _deep_merge_managed(raw, config_patch)

    # 3. 校验受管字段（llm / agents.models / agents.max_concurrent / gates.approve_mode）
    #    不做完整 ConfigLoader 校验，避免缺少 project/schedule 等必填键时无法写入。
    try:
        llm = merged.get("llm") or {}
        if llm:
            ConfigLoader._validate_llm(llm)
        agents = merged.get("agents") or {}
        if "models" in agents and agents["models"]:
            ConfigLoader._validate_agent_models(agents["models"], llm)
        if "max_concurrent" in agents:
            mc = agents["max_concurrent"]
            if not isinstance(mc, int) or mc <= 0:
                raise ValueError(
                    f"agents.max_concurrent must be a positive integer: {mc}"
                )
        gates = merged.get("gates") or {}
        if "approve_mode" in gates and gates["approve_mode"] is not None:
            mode = gates["approve_mode"]
            if mode not in ConfigLoader.VALID_APPROVE_MODES:
                raise ValueError(
                    f"gates.approve_mode must be one of {ConfigLoader.VALID_APPROVE_MODES}: {mode}"
                )
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    # 4. 原子写回（临时文件 + rename）
    config_dir.mkdir(parents=True, exist_ok=True)
    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=str(config_dir), prefix=".config-", suffix=".yaml.tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(_CONFIG_HEADER_COMMENT)
                yaml.safe_dump(merged, f, allow_unicode=True, default_flow_style=False,
                               sort_keys=False)
            os.replace(tmp_path, config_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except OSError as e:
        return {"ok": False, "error": f"写入配置文件失败: {e}"}

    return {"ok": True, "error": None}
