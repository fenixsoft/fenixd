"""
dashboard 模块测试（add-fenix-dashboard 阶段 B/C：dashboard-server + dashboard-ui 数据层）。

覆盖 spec（openspec/changes/add-fenix-dashboard/specs/dashboard-server/spec.md）：
- data.py：STATE.md / tasks.md / 日志 / 验证产物 / 运行记录的容错解析与聚合
- registry.py：配置读写、多项目发现（显式 + 扫描）、注册去重
- server.py：六端点 JSON API、截图防路径穿越、端口上探、仅绑 127.0.0.1
"""

import json
import os
import threading
import time
from pathlib import Path

import pytest
import yaml

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.dashboard import data as dash_data
from core.dashboard.registry import Registry
from core.dashboard.server import DashboardHTTPServer, DashboardHandler, find_free_port
from core.dashboard.watcher import FileWatcher


# ── 辅助：构造一个可用的 Fenixd 项目目录 ──────────────────────────────

def make_project(tmp_path: Path, name: str = "proj-a") -> Path:
    proot = tmp_path / name
    (proot / ".fenix" / "logs").mkdir(parents=True, exist_ok=True)
    (proot / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
    (proot / ".fenix" / "verify-progress" / "myspec" / "screenshots").mkdir(parents=True, exist_ok=True)
    (proot / "openspec" / "changes" / "myspec" / "specs").mkdir(parents=True, exist_ok=True)

    (proot / "STATE.md").write_text(
        "# Fenix Project State\n\n## Specs\n\n"
        "### myspec\n- status: testing\n- priority: 2\n- created: 2026-01-01T00:00:00+00:00\n"
        "- updated: 2026-01-02T00:00:00+00:00\n- error: null\n- depends_on: null\n\n"
        "### otherspec\n- status: done\n- priority: 1\n- created: 2026-02-01T00:00:00+00:00\n"
        "- updated: 2026-02-02T00:00:00+00:00\n- error: null\n- depends_on: null\n",
        encoding="utf-8",
    )

    (proot / ".fenix" / "config.yaml").write_text("project:\n  name: fake\n", encoding="utf-8")

    (proot / "openspec" / "changes" / "myspec" / "tasks.md").write_text(
        "## 1. 阶段一\n\n"
        "- [x] 1.1 任务一\n"
        "- [ ] 1.2 任务二\n\n"
        "## 2. 阶段二\n\n"
        "- [ ] 2.1 任务三\n",
        encoding="utf-8",
    )

    (proot / "openspec" / "changes" / "myspec" / "specs" / "spec.md").write_text(
        "## ADDED Requirements\n\n### Requirement: 功能\n\n"
        "#### Scenario: 场景一\n- **WHEN** x\n- **THEN** y\n\n"
        "#### Scenario: 场景二\n- **WHEN** a\n- **THEN** b\n",
        encoding="utf-8",
    )

    # 验证产物
    (proot / ".fenix" / "verify-progress" / "myspec.json").write_text(
        json.dumps({"total": 3, "done": 1, "current": "场景二"}), encoding="utf-8"
    )
    (proot / ".fenix" / "verify-progress" / "myspec" / "report.json").write_text(
        json.dumps({
            "summary": {"total": 2, "passed": 1, "failed": 1, "warnings": 0, "errors": 0},
            "scenarios": [
                {"scenario_id": "sc-1", "status": "pass", "description": "通过场景",
                 "assertion_results": [{"type": "element_visible", "pass": True}]},
                {"scenario_id": "sc-2", "status": "fail", "description": "失败场景",
                 "assertion_results": [{"type": "text_match", "pass": False,
                                        "message": "期望 '5' 实际 'x'"}],
                 "screenshots": ["fail.png"]},
            ],
        }), encoding="utf-8"
    )
    (proot / ".fenix" / "verify-progress" / "myspec" / "test_scenarios.json").write_text(
        json.dumps([{"id": "sc-1"}, {"id": "sc-2"}]), encoding="utf-8"
    )
    (proot / ".fenix" / "verify-progress" / "myspec" / "screenshots" / "fail.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")

    # 运行记录（一条已完成 + 一条运行中）
    (proot / ".fenix" / "runs" / "impl-myspec-1780000000.jsonl").write_text(
        json.dumps({"type": "system", "subtype": "init"}, ensure_ascii=False) + "\n"
        + json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "开始实现"}]}}, ensure_ascii=False) + "\n"
        + json.dumps({"type": "result", "result": "完成", "num_turns": 5}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (proot / ".fenix" / "runs" / "verify-myspec-1780001000.jsonl").write_text(
        json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "playwright_cli", "input": {"action": "click"}}]}}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # 事件日志（时间戳必须是最近时间，get_recent_events 按分钟窗口过滤）
    from datetime import datetime, timezone
    (proot / ".fenix" / "logs" / "fenixd-2026.log").write_text(
        json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(), "level": "INFO",
                    "component": "pm_engine", "message": "scan"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    (proot / "openspec" / "changes" / "myspec" / "verification-report.md").write_text(
        "# 验证报告\n\n## Bug 汇总\n- 严重缺陷：点击保存按钮无反应\n  根因：事件未绑定\n",
        encoding="utf-8",
    )
    return proot


# ── data.py ───────────────────────────────────────────────────────────

class TestDataParse:
    def test_parse_state(self, tmp_path):
        proot = make_project(tmp_path)
        specs = dash_data.parse_state(proot)
        assert set(specs) == {"myspec", "otherspec"}
        assert specs["myspec"]["status"] == "testing"
        assert specs["myspec"]["priority"] == 2

    def test_parse_tasks_and_progress(self, tmp_path):
        proot = make_project(tmp_path)
        groups = dash_data.parse_tasks(proot, "myspec")
        assert len(groups) == 2
        assert groups[0]["title"].endswith("阶段一")
        assert groups[0]["done"] == 1 and groups[0]["total"] == 2
        done, total = dash_data.task_progress(proot, "myspec")
        assert (done, total) == (1, 3)

    def test_count_scenarios(self, tmp_path):
        proot = make_project(tmp_path)
        assert dash_data.count_scenarios(proot, "myspec") == 2

    def test_get_spec_doc(self, tmp_path):
        proot = make_project(tmp_path)
        doc_path = proot / "openspec" / "changes" / "myspec" / "proposal.md"
        doc_path.write_text("# 背景\n\n- 列表项\n", encoding="utf-8")
        # 存在
        res = dash_data.get_spec_doc(proot, "myspec", "proposal")
        assert res["found"] is True
        assert "背景" in res["content"]
        # 缺失 → found=False，content=""
        res = dash_data.get_spec_doc(proot, "myspec", "design")
        assert res == {"found": False, "content": ""}

    def test_get_spec_doc_invalid(self, tmp_path):
        proot = make_project(tmp_path)
        # doc 白名单外
        with pytest.raises(dash_data.InvalidSpecDoc):
            dash_data.get_spec_doc(proot, "myspec", "readme")
        # spec 非 kebab-case（含大写、含路径穿越片段）
        with pytest.raises(dash_data.InvalidSpecName):
            dash_data.get_spec_doc(proot, "../../etc/passwd", "proposal")
        with pytest.raises(dash_data.InvalidSpecName):
            dash_data.get_spec_doc(proot, "MySpec", "proposal")

    def test_get_recent_events(self, tmp_path):
        proot = make_project(tmp_path)
        events = dash_data.get_recent_events(proot, minutes=10)
        assert len(events) == 1
        assert events[0]["component"] == "pm_engine"

    def test_verify_progress_corrupt_skipped(self, tmp_path):
        proot = make_project(tmp_path)
        (proot / ".fenix" / "verify-progress" / "bad.json").write_text(
            "not json {{{", encoding="utf-8"
        )
        data = dash_data.parse_verify_progress(proot, "bad")
        assert data["error"] == "corrupt"
        assert data["total"] == 0
        # 非对象（list）也应标记损坏而非崩溃
        (proot / ".fenix" / "verify-progress" / "bad.json").write_text(
            "[1,2,3]", encoding="utf-8"
        )
        data = dash_data.parse_verify_progress(proot, "bad")
        assert data["error"] == "corrupt"

    def test_verify_progress_missing(self, tmp_path):
        proot = make_project(tmp_path)
        data = dash_data.parse_verify_progress(proot, "nope")
        assert data["exists"] is False

    def test_parse_report_and_bugs(self, tmp_path):
        proot = make_project(tmp_path)
        report = dash_data.parse_report(proot, "myspec")
        assert report["exists"] and len(report["scenarios"]) == 2

        bugs = dash_data.parse_bugs(proot, "myspec")
        assert bugs, "应从 report.json 聚合到 bug"
        assert all(b["source"] == "report" for b in bugs)
        assert any(b["severity"] == "major" for b in bugs)
        # sc-2 是 fail 场景且 text_match 断言失败 → 计入 bug
        assert any(b["description"] == "失败场景" for b in bugs)
        # bug 携带截图（report.json 中的截图归一化为文件名）
        assert any("fail.png" in b["screenshots"] for b in bugs)

    def test_parse_bugs_no_report_md_from_markdown(self, tmp_path):
        """bug 只来自结构化 report.json，不再从 verification-report.md 逐行抓取。

        回归：parse_bugs 曾把 Markdown 里「环境失败」「无产品 Bug 可确认」「失败
        （环境原因）」「被修复缺陷的背景描述」等行误判为 bug，导致 Dashboard 展示
        大量虚假 bug（add-parallelism、fix-worktree-agent-cwd、fix-add-parallelism
        均曾受影响）。移除 report-md 源后，仅写 Markdown（无 report.json）不产生 bug。
        """
        proot = Path(tmp_path)
        spec_dir = proot / "openspec" / "changes" / "env-spec"
        (spec_dir / "specs").mkdir(parents=True, exist_ok=True)
        # 仅环境误报的 Markdown 报告，无 report.json
        (spec_dir / "verification-report.md").write_text(
            "# 验证报告\n\n"
            "**验证结论**: ❌ **环境失败，无法验证**\n"
            "**总场景数**: 12 | 通过: 0 | 失败: 12\n"
            "**无产品功能 Bug 可确认。** 所有断言失败均由环境问题导致，不构成产品 Bug 证据。\n"
            "- **状态**: ❌ 失败（环境原因）\n"
            "- **判定**: 页面未加载，环境问题\n",
            encoding="utf-8",
        )

        bugs = dash_data.parse_bugs(proot, "env-spec")
        assert bugs == [], f"无 report.json 时不应产生 bug：{bugs}"

    def test_parse_bugs_from_report_json_not_markdown(self, tmp_path):
        """真实缺陷来自 report.json；Markdown 里的缺陷描述不再被当作 bug 源。"""
        proot = Path(tmp_path)
        spec_dir = proot / "openspec" / "changes" / "real-spec"
        (spec_dir / "specs").mkdir(parents=True, exist_ok=True)
        # Markdown 报告写了「严重缺陷」，但无 report.json → 不产生 bug
        (spec_dir / "verification-report.md").write_text(
            "# 验证报告\n\n"
            "## Bug 汇总\n"
            "- 严重缺陷：点击保存按钮无反应\n"
            "  根因：事件未绑定\n",
            encoding="utf-8",
        )
        # 结构化 report.json 含真实 fail 场景 → 产生 bug
        vp = proot / ".fenix" / "verify-progress" / "real-spec"
        vp.mkdir(parents=True, exist_ok=True)
        (vp / "report.json").write_text(json.dumps({
            "summary": {"total": 1, "passed": 0, "failed": 1, "warnings": 0, "errors": 0},
            "scenarios": [
                {"scenario_id": "sc-1", "status": "fail", "description": "保存按钮无反应",
                 "assertion_results": [{"type": "click", "pass": False,
                                         "message": "按钮不可点击"}],
                 "screenshots": [],
                 "step_results": []},
            ],
        }), encoding="utf-8")

        bugs = dash_data.parse_bugs(proot, "real-spec")
        assert all(b["source"] == "report" for b in bugs), bugs
        assert any("保存按钮无反应" in b["description"] for b in bugs), bugs

    def test_list_screenshots(self, tmp_path):
        proot = make_project(tmp_path)
        shots = dash_data.list_screenshots(proot, "myspec")
        assert shots and shots[0]["file"] == "fail.png"

    def test_get_runs_and_run_events(self, tmp_path):
        proot = make_project(tmp_path)
        runs = dash_data.get_runs(proot)
        by_id = {r["run_id"]: r for r in runs}
        assert "impl-myspec-1780000000" in by_id
        assert by_id["impl-myspec-1780000000"]["status"] == "done"
        assert by_id["impl-myspec-1780000000"]["agent_type"] == "implementer"
        assert by_id["verify-myspec-1780001000"]["status"] == "running"

        detail = dash_data.get_run_events(proot, "impl-myspec-1780000000")
        assert detail["status"] == "done"
        assert detail["total_events"] == 3
        types = [e["type"] for e in detail["events"]]
        assert types == ["system", "assistant", "result"]

    def test_get_run_events_tail_truncation(self, tmp_path):
        proot = make_project(tmp_path)
        detail = dash_data.get_run_events(proot, "impl-myspec-1780000000", tail=2)
        assert detail["total_events"] == 3   # 真实总数不受截断影响
        assert [e["type"] for e in detail["events"]] == ["assistant", "result"]

    def test_read_run_events_between(self, tmp_path):
        """增量读取：按字节偏移只读新增部分（弹窗实时推送用）。"""
        proot = make_project(tmp_path)
        run_file = proot / ".fenix" / "runs" / "impl-myspec-1780000000.jsonl"
        offset = run_file.stat().st_size
        with run_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "追加"}]}}) + "\n")
        events = dash_data.read_run_events_between(proot, "impl-myspec-1780000000", offset)
        assert len(events) == 1 and events[0]["type"] == "assistant"

    def test_get_runs_filtered_by_spec(self, tmp_path):
        proot = make_project(tmp_path)
        runs = dash_data.get_runs(proot, "myspec")
        assert all("myspec" in r["run_id"] for r in runs)

    def test_classify_run(self):
        assert dash_data.classify_run([{"type": "result"}]) == "done"
        assert dash_data.classify_run([{"type": "error"}]) == "error"
        assert dash_data.classify_run([{"type": "assistant"}]) == "running"
        assert dash_data.classify_run([]) == "empty"

    def test_cleanup_runs_keeps_latest(self, tmp_path):
        proot = make_project(tmp_path)
        runs_dir = proot / ".fenix" / "runs"
        for i in range(25):
            (runs_dir / f"impl-myspec-{i:010d}.jsonl").write_text(
                json.dumps({"type": "result"}) + "\n", encoding="utf-8"
            )
            time.sleep(0.01)  # 保证 mtime 递增
        removed = dash_data.cleanup_runs(proot)
        assert removed > 0
        remaining = list(runs_dir.glob("*.jsonl"))
        assert len(remaining) <= 20

    def test_project_summary_and_overview(self, tmp_path):
        proot = make_project(tmp_path)
        summary = dash_data.project_summary(proot, "proj-a", str(proot))
        assert summary["spec_count"] == 2
        assert summary["status_counts"]["testing"] == 1
        assert summary["task_done"] == 1 and summary["task_total"] == 3
        assert summary["active_runs"] == 1
        assert summary["problems"] == 0

        overview = dash_data.overview([
            {"name": "proj-a", "path": str(proot), "discovered": False, "exists": True}
        ])
        assert overview["totals"]["spec_count"] == 2
        assert overview["totals"]["active_runs"] == 1
        assert overview["projects"][0]["name"] == "proj-a"


# ── 实时任务进度叠加（run 记录 TaskUpdate → tasks.md） ──────────────────

def _write_flowspec_tasks(proot: Path) -> None:
    """写入 7 个任务的 tasks.md（1.1..3.1），复刻真实 add-flowtoken-run-view 结构。"""
    spec_dir = proot / "openspec" / "changes" / "flowspec"
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "tasks.md").write_text(
        "## 1. 打包接入\n\n"
        "- [ ] 1.1 任务A\n"
        "- [ ] 1.2 任务B\n"
        "- [ ] 1.3 任务C\n"
        "## 2. 弹窗重写\n\n"
        "- [ ] 2.1 任务D\n"
        "- [ ] 2.2 任务E\n"
        "- [ ] 2.3 任务F\n"
        "## 3. 测试\n\n"
        "- [ ] 3.1 任务G\n",
        encoding="utf-8",
    )


def _write_impl_run(proot: Path, spec: str, ts: int, creates, updates) -> Path:
    """写一个含 TaskCreate（subjects）/TaskUpdate（taskId,status）的 impl run 产物。"""
    runs_dir = proot / ".fenix" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_file = runs_dir / f"impl-{spec}-{ts}.jsonl"
    lines = []
    for subj in creates:
        lines.append(json.dumps({
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "name": "TaskCreate",
                 "input": {"subject": subj, "description": "d", "activeForm": "a"}}
            ]},
        }, ensure_ascii=False))
    for tid, status in updates:
        lines.append(json.dumps({
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "name": "TaskUpdate",
                 "input": {"taskId": str(tid), "status": status}}
            ]},
        }, ensure_ascii=False))
    run_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return run_file


class TestTaskLiveOverlay:
    """实时任务进度叠加：implementer 用 TaskUpdate 汇报，Dashboard 从 run 产物解析。"""

    def _mk(self, tmp_path):
        proot = make_project(tmp_path)
        _write_flowspec_tasks(proot)
        return proot

    def _creates7(self):
        return [f"Task {tid}: desc" for tid in ("1.1", "1.2", "1.3", "2.1", "2.2", "2.3", "3.1")]

    def test_parse_tasks_live_overlay_implementing(self, tmp_path):
        proot = self._mk(tmp_path)
        _write_impl_run(proot, "flowspec", 1789000000, self._creates7(),
                        [(i, "completed") for i in range(1, 7)] + [(7, "in_progress")])

        groups = dash_data.parse_tasks(proot, "flowspec", "implementing")
        flat = [t for g in groups for t in g["tasks"]]
        by_id = {t["id"]: t for t in flat}
        assert len(flat) == 7
        assert by_id["1.1"]["done"] is True
        assert by_id["1.3"]["done"] is True
        assert by_id["2.3"]["done"] is True
        assert by_id["3.1"]["done"] is False
        # 分组计数重算（前端分组头依赖 g.done / g.total）
        assert [g["done"] for g in groups] == [3, 3, 0]
        assert [g["total"] for g in groups] == [3, 3, 1]
        assert dash_data.task_progress(proot, "flowspec", "implementing") == (6, 7)

    def test_parse_tasks_live_overlay_id_mismatch(self, tmp_path):
        # 复刻真实缺陷：tasks.md 8 任务（补 3.2），run 建 7、completed 1-6 → 3.2 保持未勾
        proot = self._mk(tmp_path)
        tf = proot / "openspec" / "changes" / "flowspec" / "tasks.md"
        tf.write_text(tf.read_text(encoding="utf-8") + "- [ ] 3.2 任务H\n", encoding="utf-8")
        _write_impl_run(proot, "flowspec", 1789000000, self._creates7(),
                        [(i, "completed") for i in range(1, 7)])

        flat = [t for g in dash_data.parse_tasks(proot, "flowspec", "implementing") for t in g["tasks"]]
        assert len(flat) == 8
        by_id = {t["id"]: t for t in flat}
        assert by_id["3.2"]["done"] is False
        assert sum(1 for t in flat if t["done"]) == 6
        assert dash_data.task_progress(proot, "flowspec", "implementing") == (6, 8)

    def test_parse_tasks_live_overlay_post_implement(self, tmp_path):
        # 防 R1 回跳：实现完成后各生命周期状态仍叠加（tasks.md 仍全未勾选时）
        proot = self._mk(tmp_path)
        _write_impl_run(proot, "flowspec", 1789000000, self._creates7(),
                        [(i, "completed") for i in range(1, 7)])
        for status in ("implemented", "testing", "bug-found", "done", "pushed"):
            assert dash_data.task_progress(proot, "flowspec", status) == (6, 7), status

    def test_parse_tasks_overlay_disabled(self, tmp_path):
        proot = self._mk(tmp_path)
        _write_impl_run(proot, "flowspec", 1789000000, self._creates7(),
                        [(i, "completed") for i in range(1, 7)])
        # live=False / ready / 空状态 → 不叠加
        assert sum(g["done"] for g in dash_data.parse_tasks(proot, "flowspec", "implementing", live=False)) == 0
        assert dash_data.task_progress(proot, "flowspec", "ready") == (0, 7)
        assert dash_data.task_progress(proot, "flowspec", "") == (0, 7)

    def test_parse_tasks_no_run_file_fallback(self, tmp_path):
        proot = self._mk(tmp_path)
        assert dash_data.task_progress(proot, "flowspec", "implementing") == (0, 7)

    def test_parse_run_task_done_corrupt_and_variants(self, tmp_path):
        proot = self._mk(tmp_path)
        run_file = proot / ".fenix" / "runs" / "impl-flowspec-1789000000.jsonl"
        lines = [
            "not json {{{",
            "12345",
            json.dumps({"type": "system", "subtype": "init"}),
            json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "TaskCreate", "input": {"subject": "Task 2.1: x"}}]}}),
            json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "TaskCreate", "input": {"subject": ""}}]}}),
            json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "TaskUpdate", "input": {"taskId": "2", "status": "completed"}}]}}),
            json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "TaskUpdate", "input": {"taskId": 1, "status": "completed"}}]}}),
            json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "TaskUpdate", "input": {"taskId": "abc", "status": "completed"}}]}}),
            json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "TaskUpdate", "input": {"taskId": "99", "status": "completed"}}]}}),
            json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "TaskUpdate", "input": {"taskId": "3", "status": "in_progress"}}]}}),
        ]
        run_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        rd = dash_data._parse_run_task_done(run_file)
        # 2 个 TaskCreate：2.1 有 id、空 subject 无 id；taskId 2/1 completed → done_ids={2.1}，flat_done={0,1}
        assert rd["created_count"] == 2
        assert rd["done_ids"] == {"2.1"}
        assert rd["flat_done"] == {0, 1}

    def test_parse_run_task_done_flat_fallback(self, tmp_path):
        proot = self._mk(tmp_path)
        _write_impl_run(proot, "flowspec", 1789000000,
                        ["Implement A", "Implement B", "Implement C"],
                        [(1, "completed"), (2, "completed")])
        rd = dash_data._parse_run_task_done(proot / ".fenix" / "runs" / "impl-flowspec-1789000000.jsonl")
        assert rd["done_ids"] == set()
        assert rd["flat_done"] == {0, 1}
        # 无 id 时回退扁平下标对齐：前 2 个任务被标记
        assert dash_data.task_progress(proot, "flowspec", "implementing") == (2, 7)

    def test_find_impl_run_file_newest_and_missing(self, tmp_path):
        proot = self._mk(tmp_path)
        old = proot / ".fenix" / "runs" / "impl-flowspec-100.jsonl"
        new = proot / ".fenix" / "runs" / "impl-flowspec-200.jsonl"
        old.write_text("{}\n", encoding="utf-8")
        new.write_text("{}\n", encoding="utf-8")
        os.utime(old, (1000000, 1000000))
        os.utime(new, (2000000, 2000000))
        # 无关前缀不误匹配
        (proot / ".fenix" / "runs" / "impl-other-300.jsonl").write_text("{}\n", encoding="utf-8")
        (proot / ".fenix" / "runs" / "verify-flowspec-400.jsonl").write_text("{}\n", encoding="utf-8")
        assert dash_data._find_impl_run_file(proot, "flowspec") == new
        assert dash_data._find_impl_run_file(proot, "nope") is None

    def test_live_propagates_to_summary(self, tmp_path):
        proot = self._mk(tmp_path)
        # STATE.md 注册 flowspec 为 implementing
        state = proot / "STATE.md"
        state.write_text(state.read_text(encoding="utf-8") +
                         "\n### flowspec\n- status: implementing\n- priority: 5\n- created: 2026-01-01T00:00:00+00:00\n"
                         "- updated: 2026-01-01T00:00:00+00:00\n- error: null\n- depends_on: null\n",
                         encoding="utf-8")
        _write_impl_run(proot, "flowspec", 1789000000, self._creates7(),
                        [(i, "completed") for i in range(1, 7)])

        s = dash_data.spec_summary(proot, "flowspec", {"status": "implementing", "created": "x", "updated": "y"})
        assert s["task_done"] == 6 and s["task_total"] == 7
        p = dash_data.project_summary(proot, "proj-a", str(proot))
        assert p["task_done"] == 6 + 1  # flowspec(6) + myspec(1)
        assert p["task_total"] == 7 + 3


class TestParseRunTaskDoneShared:
    """add-task-progress-sync 1.2：parse_run_task_done 作为 dashboard 与 pm_engine
    共用的公有解析函数——返回正确 done_ids / flat 回退 / 文件缺失损坏返回空集不抛异常。"""

    def test_done_ids_from_subject_and_completed(self, tmp_path):
        proot = tmp_path / "p"
        proot.mkdir()
        run_file = proot / ".fenix" / "runs" / "impl-spec-1789000000.jsonl"
        _write_impl_run(proot, "spec", 1789000000,
                        ["Task 2.1: build", "Task 2.2: test", "Task 2.3: doc"],
                        [(1, "completed"), (2, "completed")])
        rd = dash_data.parse_run_task_done(run_file)
        assert rd["done_ids"] == {"2.1", "2.2"}
        assert rd["created_count"] == 3

    def test_flat_fallback_when_subject_missing_id(self, tmp_path):
        proot = tmp_path / "p"
        proot.mkdir()
        run_file = _write_impl_run(proot, "spec", 1789000000,
                                   ["Implement A", "Implement B", "Implement C"],
                                   [(1, "completed"), (3, "completed")])
        rd = dash_data.parse_run_task_done(run_file)
        # subject 无 id → done_ids 空；但 flat_done 仍按创建序下标记录（供显示回退）
        assert rd["done_ids"] == set()
        assert rd["flat_done"] == {0, 2}

    def test_missing_file_returns_empty(self, tmp_path):
        proot = tmp_path / "p"
        proot.mkdir()
        missing = proot / ".fenix" / "runs" / "impl-spec-1.jsonl"
        rd = dash_data.parse_run_task_done(missing)
        assert rd == {"done_ids": set(), "created_count": 0, "flat_done": set()}

    def test_corrupt_file_returns_empty(self, tmp_path):
        proot = tmp_path / "p"
        proot.mkdir()
        (proot / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
        run_file = proot / ".fenix" / "runs" / "impl-spec-1.jsonl"
        run_file.write_text("{ not valid json {{{ \n 12345 \n", encoding="utf-8")
        rd = dash_data.parse_run_task_done(run_file)
        assert rd == {"done_ids": set(), "created_count": 0, "flat_done": set()}

    def test_public_alias_reference_equals_private(self, tmp_path):
        # data.py 内部调用点（parse_tasks）使用 _parse_run_task_done 别名，须指向同一函数
        assert dash_data._parse_run_task_done is dash_data.parse_run_task_done
        assert dash_data._find_impl_run_file is dash_data.find_impl_run_file

class TestRegistry:
    def test_load_missing_defaults(self, tmp_path):
        reg = Registry(config_path=tmp_path / "none.yaml")
        data = reg.load()
        assert data["port"] == 8787
        assert data["projects"] == [] and data["scan_dirs"] == []

    def test_save_and_load_roundtrip(self, tmp_path):
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 9000, "projects": [{"name": "p", "path": "/x"}], "scan_dirs": ["/d"]})
        data = reg.load()
        assert data["port"] == 9000
        assert data["projects"][0]["path"] == "/x"

    def test_add_project_dedup(self, tmp_path):
        proot = make_project(tmp_path)
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        added, msg = reg.add_project(str(proot))
        assert added
        added2, msg2 = reg.add_project(str(proot))
        assert not added2
        data = reg.load()
        assert len(data["projects"]) == 1

    def test_add_project_requires_state(self, tmp_path):
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        not_a_project = tmp_path / "plain"
        not_a_project.mkdir()
        added, msg = reg.add_project(str(not_a_project))
        assert not added and "STATE.md" in msg

    def test_discover_explicit_and_scan(self, tmp_path):
        proj_a = make_project(tmp_path, "proj-a")
        proj_b = make_project(tmp_path, "proj-b")
        # 仅 STATE.md 的目录：无需 .fenix/config.yaml 也应被发现
        (tmp_path / "lite-proj").mkdir()
        (tmp_path / "lite-proj" / "STATE.md").write_text("# state", encoding="utf-8")
        # 无 STATE.md 的目录仍被排除
        (tmp_path / "plain").mkdir()

        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({
            "port": 8787,
            "projects": [{"name": "proj-a", "path": str(proj_a)}],
            "scan_dirs": [str(tmp_path)],
        })
        projects = reg.discover()
        by_name = {p["name"]: p for p in projects}
        assert "proj-a" in by_name          # 显式
        assert "proj-b" in by_name          # 扫描命中
        assert by_name["proj-b"]["discovered"] is True
        assert "lite-proj" in by_name       # 仅 STATE.md 也被扫描命中
        assert by_name["lite-proj"]["discovered"] is True
        assert "plain" not in by_name       # 无 STATE.md 的目录被排除

    def test_discover_requires_state_only(self, tmp_path):
        # 仅含 STATE.md（无 .fenix/config.yaml）的目录被识别为 Fenixd 项目
        (tmp_path / "lite-proj").mkdir()
        (tmp_path / "lite-proj" / "STATE.md").write_text("# state", encoding="utf-8")
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [], "scan_dirs": [str(tmp_path)]})
        projects = reg.discover()
        names = {p["name"] for p in projects}
        assert "lite-proj" in names

    def test_add_project_without_config_ok(self, tmp_path):
        # add_project 对无 .fenix/config.yaml 的目录（仅 STATE.md）成功
        proot = tmp_path / "lite-proj"
        proot.mkdir()
        (proot / "STATE.md").write_text("# state", encoding="utf-8")
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        added, msg = reg.add_project(str(proot))
        assert added
        assert "已注册项目" in msg

    def test_discover_missing_explicit_flagged(self, tmp_path):
        missing = tmp_path / "gone"
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "gone", "path": str(missing)}], "scan_dirs": []})
        projects = reg.discover()
        assert projects[0]["exists"] is False

    def test_load_includes_ignored_key(self, tmp_path):
        reg = Registry(config_path=tmp_path / "none.yaml")
        data = reg.load()
        assert data["ignored"] == []

    def test_discover_filters_ignored_paths(self, tmp_path):
        proj_a = make_project(tmp_path, "proj-a")
        proj_b = make_project(tmp_path, "proj-b")
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({
            "port": 8787,
            "projects": [
                {"name": "proj-a", "path": str(proj_a)},
                {"name": "proj-b", "path": str(proj_b)},
            ],
            # 空扫描目录：避免默认回退扫描真实主目录 ~，保持测试隔离
            "scan_dirs": [str(tmp_path / "scan-empty")],
        })
        assert len(reg.discover()) == 2
        # 忽略 proj-a 后不应再出现
        reg.add_ignored(str(proj_a))
        names = {p["name"] for p in reg.discover()}
        assert "proj-a" not in names
        assert "proj-b" in names
        # is_ignored 查询
        assert reg.is_ignored(str(proj_a))
        assert not reg.is_ignored(str(proj_b))

    def test_add_ignored_dedup(self, tmp_path):
        proot = make_project(tmp_path)
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        added, msg = reg.add_ignored(str(proot))
        assert added
        added2, msg2 = reg.add_ignored(str(proot))  # 规范化后应判为重复
        assert not added2 and "忽略列表" in msg2
        data = reg.load()
        assert len([x for x in data["ignored"]]) == 1
        # 规范化：尾斜杠等价也应判为同一项
        added3, _ = reg.add_ignored(str(proot) + "/")
        assert not added3


class TestSpecSummaryTotalDuration:
    def test_total_duration_sums_runs(self, tmp_path):
        proot = make_project(tmp_path)
        # make_project 已写入 impl-myspec（duration 由 mtime 推导）+ verify-myspec（运行中）
        # 额外写一条带明确较大时长的 run，确保求和 > 0 且可预期
        import time as _t
        ts = int(_t.time()) - 480
        run_path = proot / ".fenix" / "runs" / f"verify-myspec-{ts}.jsonl"
        run_path.write_text(json.dumps({"type": "result", "result": "ok"}) + "\n", encoding="utf-8")
        # 我们手动写入过去时间，使 duration = now - ts ≈ 480s；再写一条已完成的
        entry = dash_data.parse_state(proot)["myspec"]
        summary = dash_data.spec_summary(proot, "myspec", entry)
        assert summary["total_duration"] >= 0
        # 至少包含 impl + 两条 verify 的运行，全部求和应 > 0
        assert summary["total_duration"] > 0

    def test_total_duration_zero_without_runs(self, tmp_path):
        # 构造一个无运行记录的 spec
        proot = tmp_path / "empty-spec-proj"
        (proot / ".fenix" / "runs").mkdir(parents=True)
        (proot / "STATE.md").write_text(
            "# state\n\n### lone\n- status: ready\n- priority: 1\n", encoding="utf-8"
        )
        entry = dash_data.parse_state(proot)["lone"]
        summary = dash_data.spec_summary(proot, "lone", entry)
        assert summary["total_duration"] == 0


class TestProjectLifecycleAPI:
    """管理端点：start/stop/delete（mock tmux，验证返回、错误路径、SSE 广播）。"""

    def _make_server(self, tmp_path, registry):
        return _TestServer(registry, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")

    def test_start_stop_unknown_project_returns_400(self, tmp_path):
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [], "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = self._make_server(tmp_path, reg)
        try:
            status, body = srv.post("/api/projects/ghost/start")
            assert status == 400 and body["error"]
            status, body = srv.post("/api/projects/ghost/stop")
            assert status == 400 and body["error"]
            status, body = srv.delete("/api/projects/ghost")
            assert status == 400 and body["error"]
        finally:
            srv.stop()

    def test_start_stop_delete_flow_with_mocked_tmux(self, tmp_path, monkeypatch):
        proot = make_project(tmp_path)
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = self._make_server(tmp_path, reg)

        started, stopped, deleted = [], [], []
        monkeypatch.setattr("core.dashboard.server.start_daemon",
                            lambda root: started.append(root) or {"ok": True, "session": "s1", "already": False})
        monkeypatch.setattr("core.dashboard.server.stop_daemon",
                            lambda root: stopped.append(root) or {"ok": True, "session": "s1", "was_running": True})

        try:
            # start
            status, body = srv.post("/api/projects/proj-a/start")
            assert status == 200 and body["ok"] is True
            assert body["session"] == "s1"
            assert str(proot) in started
            # stop
            status, body = srv.post("/api/projects/proj-a/stop")
            assert status == 200 and body["ok"] is True
            assert str(proot) in stopped
            # delete → 软删除：加入 ignored，项目不再被发现
            status, body = srv.delete("/api/projects/proj-a")
            assert status == 200 and body["ok"] is True
            assert reg.is_ignored(str(proot))
            names = {p["name"] for p in reg.discover()}
            assert "proj-a" not in names
        finally:
            srv.stop()

    def test_lifecycle_tmux_error_returns_ok_false_not_500(self, tmp_path, monkeypatch):
        proot = make_project(tmp_path)
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = self._make_server(tmp_path, reg)
        monkeypatch.setattr("core.dashboard.server.start_daemon",
                            lambda root: (_ for _ in ()).throw(RuntimeError("tmux gone")))
        try:
            status, body = srv.post("/api/projects/proj-a/start")
            assert status == 200 and body["ok"] is False and "tmux gone" in body["error"]
        finally:
            srv.stop()


# ── data.py 配置分级（add-hierarchical-config） ─────────────────

def _patch_config_paths(monkeypatch, tmp_path, user_dir_name="user-fenix"):
    """把用户级配置路径重定向到临时目录，返回 (user_config_path, project_root)。"""
    user_dir = tmp_path / user_dir_name
    user_config = user_dir / "config.yaml"
    monkeypatch.setattr(dash_data, "USER_CONFIG_PATH", user_config)
    monkeypatch.setattr("core.config.USER_CONFIG_DIR", user_dir)
    proot = tmp_path / "proj"
    (proot / ".fenix").mkdir(parents=True)
    return user_config, proot


class TestConfigHierarchyData:
    def test_read_config_user_scope_missing(self, tmp_path, monkeypatch):
        user_config, proot = _patch_config_paths(monkeypatch, tmp_path)
        result = dash_data.read_config(proot, scope="user")
        assert result["scope"] == "user"
        assert result["raw_exists"] is False
        assert result["llm"] == {}
        assert result["agents"] == {"models": {}, "max_concurrent": 2, "run_timeout_seconds": 3600}
        assert result["gates"] == {"approve_mode": "manual"}
        assert set(result["sources"].values()) == {"user"}

    def test_read_config_user_scope_values(self, tmp_path, monkeypatch):
        user_config, proot = _patch_config_paths(monkeypatch, tmp_path)
        user_config.parent.mkdir()
        user_config.write_text(yaml.safe_dump({
            "llm": {"providers": [{"name": "volc", "baseurl": "https://a.com",
                                   "apikey": "sk-1", "model": "m1"}]},
            "agents": {"max_concurrent": 4, "max_retries": 3},
            "gates": {"approve_mode": "manual"},
        }), encoding="utf-8")
        result = dash_data.read_config(proot, scope="user")
        assert result["raw_exists"] is True
        assert result["llm"]["providers"][0]["name"] == "volc"
        assert result["agents"]["max_concurrent"] == 4
        assert result["sources"]["agents.max_concurrent"] == "user"
        # 非受管键 max_retries 不应出现在结果里
        assert "max_retries" not in result["agents"]

    def test_write_config_user_scope_creates_file(self, tmp_path, monkeypatch):
        user_config, proot = _patch_config_paths(monkeypatch, tmp_path)
        patch = {
            "llm": {"providers": [{"name": "volc", "baseurl": "https://a.com",
                                   "apikey": "sk-1", "model": "m1"}]},
            "agents": {"max_concurrent": 3},
            "gates": {"approve_mode": "auto"},
        }
        result = dash_data.write_config(proot, patch, scope="user")
        assert result["ok"], result.get("error")
        assert result["scope"] == "user"
        assert result["path"] == str(user_config)
        assert user_config.exists()  # 自动建目录 + 创建文件
        written = yaml.safe_load(user_config.read_text(encoding="utf-8"))
        assert written["agents"]["max_concurrent"] == 3
        assert written["gates"]["approve_mode"] == "auto"

    def test_write_config_user_scope_preserves_non_managed(self, tmp_path, monkeypatch):
        user_config, proot = _patch_config_paths(monkeypatch, tmp_path)
        user_config.parent.mkdir()
        user_config.write_text(yaml.safe_dump({
            "project": {"name": "x", "type": "web"},
            "gates": {"approve_mode": "manual", "require_push_approval": True},
        }), encoding="utf-8")
        result = dash_data.write_config(proot, {"gates": {"approve_mode": "auto"}}, scope="user")
        assert result["ok"], result.get("error")
        written = yaml.safe_load(user_config.read_text(encoding="utf-8"))
        assert written["project"]["name"] == "x"
        assert written["gates"]["approve_mode"] == "auto"
        assert written["gates"]["require_push_approval"] is True

    def test_write_config_validation_rejects_user_scope(self, tmp_path, monkeypatch):
        user_config, proot = _patch_config_paths(monkeypatch, tmp_path)
        bad = {"gates": {"approve_mode": "bogus"}}
        result = dash_data.write_config(proot, bad, scope="user")
        assert not result["ok"]
        assert not user_config.exists()  # 校验失败不写盘

    def test_read_effective_config_merge_and_sources(self, tmp_path, monkeypatch):
        user_config, proot = _patch_config_paths(monkeypatch, tmp_path)
        user_config.parent.mkdir()
        user_config.write_text(yaml.safe_dump({
            "agents": {"max_concurrent": 4},
            "gates": {"approve_mode": "manual"},
        }), encoding="utf-8")
        (proot / ".fenix" / "config.yaml").write_text(yaml.safe_dump({
            "project": {"name": "proj", "type": "web"},
            "agents": {"max_concurrent": 2},
        }), encoding="utf-8")

        result = dash_data.read_effective_config(proot)
        assert result["scope"] == "project"
        assert result["raw_exists"] is True
        # 有效合并值：项目级覆盖 max_concurrent，gates 继承用户级
        assert result["agents"]["max_concurrent"] == 2
        assert result["gates"]["approve_mode"] == "manual"
        # 来源标注
        assert result["sources"]["agents.max_concurrent"] == "project"
        assert result["sources"]["gates.approve_mode"] == "user"

    def test_read_effective_config_project_file_missing(self, tmp_path, monkeypatch):
        user_config, proot = _patch_config_paths(monkeypatch, tmp_path)
        user_config.parent.mkdir()
        user_config.write_text(yaml.safe_dump({
            "agents": {"max_concurrent": 6},
            "gates": {"approve_mode": "auto"},
        }), encoding="utf-8")

        result = dash_data.read_effective_config(proot)
        assert result["raw_exists"] is False
        assert result["agents"]["max_concurrent"] == 6  # 全部继承用户级
        assert set(result["sources"].values()) == {"user"}

    def test_read_effective_config_error_on_invalid_project(self, tmp_path, monkeypatch):
        user_config, proot = _patch_config_paths(monkeypatch, tmp_path)
        (proot / ".fenix" / "config.yaml").write_text(yaml.safe_dump({
            "gates": {"approve_mode": "bogus"},
        }), encoding="utf-8")
        result = dash_data.read_effective_config(proot)
        assert result["error"]  # 校验失败不 500，返回 error 标记
        assert result["sources"]["gates.approve_mode"] == "project"


# ── server.py ─────────────────────────────────────────────────────────

class _TestServer:
    """在临时目录上启动 DashboardHTTPServer，线程后台运行。"""

    def __init__(self, registry: Registry, static_dir: Path):
        self.port = find_free_port(20000)
        self.httpd = DashboardHTTPServer(("127.0.0.1", self.port), registry, static_dir)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def get(self, path: str, raw: bool = False):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("GET", path)
            resp = conn.getresponse()
            body = resp.read()
            if raw:
                return resp.status, resp.getheader("Content-Type"), body
            return resp.status, json.loads(body)
        finally:
            conn.close()

    def _req(self, method: str, path: str):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path)
            resp = conn.getresponse()
            body = resp.read()
            return resp.status, json.loads(body)
        finally:
            conn.close()

    def post(self, path: str):
        return self._req("POST", path)

    def post_json(self, path: str, payload: dict):
        import http.client
        body = json.dumps(payload).encode("utf-8")
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(
                "POST", path, body=body,
                headers={"Content-Type": "application/json",
                         "Content-Length": str(len(body))},
            )
            resp = conn.getresponse()
            data = resp.read()
            return resp.status, json.loads(data)
        finally:
            conn.close()

    def delete(self, path: str):
        return self._req("DELETE", path)

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture()
def server_fx(tmp_path):
    proot = make_project(tmp_path)
    cfg = tmp_path / "dashboard.yaml"
    reg = Registry(config_path=cfg)
    # scan_dirs 指向不存在的目录：避免默认扫描回退到真实主目录 ~，保持测试隔离
    reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
              "scan_dirs": [str(tmp_path / "scan-empty")]})
    srv = _TestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
    yield proot, srv
    srv.stop()


class TestServerAPI:
    def test_index_served(self, server_fx):
        _, srv = server_fx
        status, ctype, body = srv.get("/", raw=True)
        assert status == 200
        assert b"Fenix Dashboard" in body

    def test_api_projects(self, server_fx):
        proot, srv = server_fx
        status, data = srv.get("/api/projects")
        assert status == 200
        assert data["projects"][0]["name"] == "proj-a"
        assert data["projects"][0]["spec_count"] == 2

    def test_api_overview(self, server_fx):
        _, srv = server_fx
        status, data = srv.get("/api/overview")
        assert status == 200
        assert data["totals"]["spec_count"] == 2
        assert data["totals"]["active_runs"] == 1
        assert data["totals"]["status_counts"]["testing"] == 1

    def test_api_specs(self, server_fx):
        _, srv = server_fx
        status, data = srv.get("/api/specs?project=proj-a")
        assert status == 200
        specs = data["specs"]
        names = {s["name"] for s in specs}
        assert "myspec" in names and "otherspec" in names
        # 每个摘要项包含 created / updated
        for s in specs:
            assert "created" in s
            assert "updated" in s
        # 按 created 倒序排列（新在前）：otherspec (2026-02) 在 myspec (2026-01) 前
        spec_names_order = [s["name"] for s in specs]
        assert spec_names_order.index("otherspec") < spec_names_order.index("myspec")

    def test_api_specs_created_missing_last(self, tmp_path):
        """缺失 created 的 SPEC 排在有创建时间条目的末尾。"""
        proot = tmp_path / "proj-nc"
        (proot / "openspec" / "changes" / "old" / "specs").mkdir(parents=True, exist_ok=True)
        (proot / "openspec" / "changes" / "new" / "specs").mkdir(parents=True, exist_ok=True)
        (proot / "openspec" / "changes" / "ancient" / "specs").mkdir(parents=True, exist_ok=True)
        (proot / "STATE.md").write_text(
            "# State\n\n## Specs\n\n"
            "### new\n- status: ready\n- priority: 1\n- created: 2026-03-01T00:00:00+00:00\n"
            "- error: null\n\n"
            "### ancient\n- status: done\n- priority: 9\n"
            "- error: null\n\n"
            "### old\n- status: testing\n- priority: 5\n- created: 2026-01-01T00:00:00+00:00\n"
            "- error: null\n",
            encoding="utf-8",
        )
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-nc", "path": str(proot)}], "scan_dirs": []})
        srv = _TestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
        try:
            status, data = srv.get("/api/specs?project=proj-nc")
            assert status == 200
            names = [s["name"] for s in data["specs"]]
            # 顺序：new（最新） → old（较旧） → ancient（无 created，排最后）
            assert names == ["new", "old", "ancient"]
            # ancient 的 created 为 None
            ancient = next(s for s in data["specs"] if s["name"] == "ancient")
            assert ancient["created"] is None
        finally:
            srv.stop()

    def test_api_spec_detail(self, server_fx):
        _, srv = server_fx
        status, data = srv.get("/api/specs/myspec?project=proj-a")
        assert status == 200
        assert data["status"] == "testing"
        assert len(data["tasks"]) == 2
        assert len(data["scenarios"]) == 2
        assert len(data["bugs"]) >= 1
        assert len(data["screenshots"]) == 1
        assert len(data["runs"]) == 2
        assert data["verify_progress"]["total"] == 3

    def test_api_spec_doc(self, server_fx):
        proot, srv = server_fx
        (proot / "openspec" / "changes" / "myspec" / "proposal.md").write_text(
            "# 背景\n\n- 列表项\n", encoding="utf-8"
        )
        # 读取存在的文档
        status, data = srv.get("/api/spec-doc?project=proj-a&spec=myspec&doc=proposal")
        assert status == 200
        assert data["found"] is True
        assert "背景" in data["content"]
        # 缺失文档 → 200 + found=False
        status, data = srv.get("/api/spec-doc?project=proj-a&spec=myspec&doc=design")
        assert status == 200
        assert data == {"found": False, "content": "", "project": "proj-a", "spec": "myspec", "doc": "design"}
        # 非法 doc → 400
        status, _ = srv.get("/api/spec-doc?project=proj-a&spec=myspec&doc=readme")
        assert status == 400
        # 未知 spec → 404（且不读取 changes 目录外文件）
        status, _ = srv.get("/api/spec-doc?project=proj-a&spec=ghost&doc=proposal")
        assert status == 404
        # 路径穿越 spec → 404，不泄露文件内容
        status, data = srv.get("/api/spec-doc?project=proj-a&spec=../../etc/passwd&doc=proposal")
        assert status == 404
        # 未知项目 → 400
        status, _ = srv.get("/api/spec-doc?project=ghost&spec=myspec&doc=proposal")
        assert status == 400

    def test_api_run(self, server_fx):
        _, srv = server_fx
        status, data = srv.get("/api/runs/impl-myspec-1780000000?project=proj-a")
        assert status == 200
        assert data["status"] == "done"
        assert data["events"][-1]["type"] == "result"

    def test_api_events(self, server_fx):
        _, srv = server_fx
        status, data = srv.get("/api/events?project=proj-a&minutes=10")
        assert status == 200
        assert len(data["events"]) == 1

    def test_unknown_project(self, server_fx):
        _, srv = server_fx
        status, data = srv.get("/api/specs?project=ghost")
        assert status == 200
        assert data["specs"] == []

    def test_screenshot_served(self, server_fx):
        _, srv = server_fx
        status, ctype, body = srv.get("/screenshots/proj-a/myspec/fail.png", raw=True)
        assert status == 200
        assert ctype == "image/png"

    def test_screenshot_path_traversal_blocked(self, server_fx):
        proot, srv = server_fx
        # 越界到项目根 STATE.md
        status, _, _ = srv.get(
            "/screenshots/proj-a/myspec/../../../STATE.md", raw=True
        )
        assert status in (403, 404)
        # 未注册项目
        status, _, _ = srv.get("/screenshots/ghost/myspec/fail.png", raw=True)
        assert status in (403, 404)

    def test_corrupt_progress_does_not_500(self, tmp_path):
        proot = make_project(tmp_path)
        (proot / ".fenix" / "verify-progress" / "myspec.json").write_text(
            "{{{{ corrupted", encoding="utf-8"
        )
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}], "scan_dirs": []})
        srv = _TestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
        try:
            status, data = srv.get("/api/specs/myspec?project=proj-a")
            assert status == 200
            assert data["verify_progress"]["error"] == "corrupt"
            status, data = srv.get("/api/overview")
            assert status == 200
        finally:
            srv.stop()

    def test_binds_localhost_only(self, tmp_path):
        proot = make_project(tmp_path)
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}], "scan_dirs": []})
        srv = _TestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
        try:
            assert srv.httpd.server_address[0] in ("127.0.0.1", "localhost")
        finally:
            srv.stop()

    def test_find_free_port_probes_upward(self):
        occupied = find_free_port(20100)
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", occupied))
            s.listen(1)
            free = find_free_port(occupied)
            assert free != occupied


# ── server.py 配置 API 作用域化（add-hierarchical-config） ──────────

class TestConfigAPI:
    """/api/config GET/POST：无 project = 用户级，带 project = 项目级合并视图。"""

    STATIC_DIR = Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static"

    def _serve(self, tmp_path, monkeypatch, with_user=True):
        user_dir = tmp_path / "user-fenix"
        user_config = user_dir / "config.yaml"
        monkeypatch.setattr(dash_data, "USER_CONFIG_PATH", user_config)
        monkeypatch.setattr("core.config.USER_CONFIG_DIR", user_dir)
        proot = make_project(tmp_path, "proj-a")
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = _TestServer(reg, self.STATIC_DIR)
        return user_config, proot, srv

    def test_config_get_no_project_user_mode(self, tmp_path, monkeypatch):
        user_config, proot, srv = self._serve(tmp_path, monkeypatch)
        try:
            status, data = srv.get("/api/config")
            assert status == 200
            assert data["scope"] == "user"
            assert data["raw_exists"] is False
            assert data["error"] is None          # 不再是 unknown project 错误
            assert data["gates"]["approve_mode"] == "manual"
        finally:
            srv.stop()

    def test_config_get_no_project_returns_user_values(self, tmp_path, monkeypatch):
        user_config, proot, srv = self._serve(tmp_path, monkeypatch)
        user_config.parent.mkdir()
        user_config.write_text(yaml.safe_dump({
            "agents": {"max_concurrent": 4},
            "gates": {"approve_mode": "auto"},
        }), encoding="utf-8")
        try:
            status, data = srv.get("/api/config")
            assert status == 200
            assert data["scope"] == "user"
            assert data["raw_exists"] is True
            assert data["agents"]["max_concurrent"] == 4
            assert data["gates"]["approve_mode"] == "auto"
            assert set(data["sources"].values()) == {"user"}
        finally:
            srv.stop()

    def test_config_get_project_merged_view_with_sources(self, tmp_path, monkeypatch):
        user_config, proot, srv = self._serve(tmp_path, monkeypatch)
        user_config.parent.mkdir()
        user_config.write_text(yaml.safe_dump({
            "agents": {"max_concurrent": 4},
            "gates": {"approve_mode": "manual"},
        }), encoding="utf-8")
        # 项目级只覆盖 max_concurrent
        (proot / ".fenix" / "config.yaml").write_text(yaml.safe_dump({
            "project": {"name": "proj-a", "type": "web"},
            "agents": {"max_concurrent": 2},
        }), encoding="utf-8")
        try:
            status, data = srv.get("/api/config?project=proj-a")
            assert status == 200
            assert data["project"] == "proj-a"
            assert data["scope"] == "project"
            assert data["raw_exists"] is True
            # 有效合并值：项目级覆盖 max_concurrent，gates 继承用户级
            assert data["agents"]["max_concurrent"] == 2
            assert data["gates"]["approve_mode"] == "manual"
            assert data["sources"]["agents.max_concurrent"] == "project"
            assert data["sources"]["gates.approve_mode"] == "user"
        finally:
            srv.stop()

    def test_config_post_no_project_writes_user(self, tmp_path, monkeypatch):
        user_config, proot, srv = self._serve(tmp_path, monkeypatch)
        payload = {
            "llm": {"providers": [{"name": "volc", "baseurl": "https://a.com",
                                   "apikey": "sk-1", "model": "m1"}]},
            "agents": {"models": {}, "max_concurrent": 3},
            "gates": {"approve_mode": "auto"},
        }
        try:
            status, data = srv.post_json("/api/config", payload)
            assert status == 200
            assert data["scope"] == "user"
            assert data["saved"] is True
            assert data["path"] == str(user_config)
            assert user_config.exists()
            written = yaml.safe_load(user_config.read_text(encoding="utf-8"))
            assert written["agents"]["max_concurrent"] == 3
            assert written["gates"]["approve_mode"] == "auto"
        finally:
            srv.stop()

    def test_config_post_project_writes_project(self, tmp_path, monkeypatch):
        user_config, proot, srv = self._serve(tmp_path, monkeypatch)
        proj_cfg = proot / ".fenix" / "config.yaml"
        proj_cfg.write_text(yaml.safe_dump({
            "project": {"name": "proj-a", "type": "web"},
        }), encoding="utf-8")
        payload = {
            "agents": {"models": {}, "max_concurrent": 5},
            "gates": {"approve_mode": "manual"},
        }
        try:
            status, data = srv.post_json("/api/config?project=proj-a", payload)
            assert status == 200
            assert data["scope"] == "project"
            assert data["project"] == "proj-a"
            assert data["saved"] is True
            assert data["path"] == str(proj_cfg)
            written = yaml.safe_load(proj_cfg.read_text(encoding="utf-8"))
            assert written["project"]["name"] == "proj-a"   # 非受管键保留
            assert written["agents"]["max_concurrent"] == 5
            assert written["gates"]["approve_mode"] == "manual"
        finally:
            srv.stop()

    def test_config_post_invalid_payload_rejected(self, tmp_path, monkeypatch):
        user_config, proot, srv = self._serve(tmp_path, monkeypatch)
        try:
            status, data = srv.post_json("/api/config", {"gates": {"approve_mode": "bogus"}})
            assert status == 400
            assert not user_config.exists()  # 校验失败不写盘
        finally:
            srv.stop()


# ── parse_tasks worktree 路径对齐测试（fix-worktree-agent-cwd） ──

class TestParseTasksWorktreeAlignment:
    """parse_tasks 在 implementing 状态读 worktree tasks.md，implemented 后读主树 tasks.md。"""

    def _mk(self, tmp_path):
        proot = make_project(tmp_path)
        # 注册一个新 SPEC wtspec，初始全部未勾选
        spec_dir = proot / "openspec" / "changes" / "wtspec"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "tasks.md").write_text(
            "## 1. 组一\n\n"
            "- [ ] 1.1 任务A\n"
            "- [ ] 1.2 任务B\n",
            encoding="utf-8",
        )
        return proot

    def _mk_worktree(self, proot, spec_name, tasks_content):
        """在 .claude/worktrees/ 下创建一个 impl-<spec>-<ts> 目录模拟 worktree。"""
        wt_dir = proot / ".claude" / "worktrees" / f"impl-{spec_name}-9999999999"
        wt_spec_dir = wt_dir / "openspec" / "changes" / spec_name
        wt_spec_dir.mkdir(parents=True, exist_ok=True)
        (wt_spec_dir / "tasks.md").write_text(tasks_content, encoding="utf-8")
        return wt_dir

    def test_implementing_reads_worktree_tasks(self, tmp_path):
        """implementing 状态应读取 worktree 中的 tasks.md（实现者实时勾选处）。"""
        proot = self._mk(tmp_path)
        # worktree 中 1.1 已勾选，主树中全部未勾
        self._mk_worktree(proot, "wtspec",
            "## 1. 组一\n\n"
            "- [x] 1.1 任务A\n"
            "- [ ] 1.2 任务B\n")

        groups = dash_data.parse_tasks(proot, "wtspec", "implementing", live=False)
        flat = [t for g in groups for t in g["tasks"]]
        by_id = {t["id"]: t for t in flat}
        # 应该读到 worktree 的勾选状态（1.1 done）
        assert by_id["1.1"]["done"] is True
        assert by_id["1.2"]["done"] is False

    def test_implemented_reads_main_tree_tasks(self, tmp_path):
        """implemented 状态应读取主树 tasks.md（merge 已把勾选带回主树）。"""
        proot = self._mk(tmp_path)
        # 主树中 1.1 已勾选（模拟 merge-back 后）
        spec_dir = proot / "openspec" / "changes" / "wtspec"
        (spec_dir / "tasks.md").write_text(
            "## 1. 组一\n\n"
            "- [x] 1.1 任务A\n"
            "- [x] 1.2 任务B\n",
            encoding="utf-8",
        )
        # worktree 中状态不同（模拟 worktree 已清理或内容不同）
        self._mk_worktree(proot, "wtspec",
            "## 1. 组一\n\n"
            "- [x] 1.1 任务A\n"
            "- [ ] 1.2 任务B\n")

        groups = dash_data.parse_tasks(proot, "wtspec", "implemented", live=False)
        flat = [t for g in groups for t in g["tasks"]]
        by_id = {t["id"]: t for t in flat}
        # 应该读到主树的勾选状态（都 done）
        assert by_id["1.1"]["done"] is True
        assert by_id["1.2"]["done"] is True

    def test_testing_reads_main_tree_tasks(self, tmp_path):
        """testing 状态也应读主树 tasks.md（merge-back 后）。"""
        proot = self._mk(tmp_path)
        spec_dir = proot / "openspec" / "changes" / "wtspec"
        (spec_dir / "tasks.md").write_text(
            "## 1. 组一\n\n"
            "- [x] 1.1 任务A\n"
            "- [x] 1.2 任务B\n",
            encoding="utf-8",
        )
        self._mk_worktree(proot, "wtspec",
            "## 1. 组一\n\n"
            "- [ ] 1.1 任务A\n"
            "- [ ] 1.2 任务B\n")

        groups = dash_data.parse_tasks(proot, "wtspec", "testing", live=False)
        done = sum(t["done"] for g in groups for t in g["tasks"])
        assert done == 2  # 主树两个都勾了

    def test_implementing_no_worktree_falls_back_to_main(self, tmp_path):
        """implementing 状态但无 worktree 时，回退读主树 tasks.md。"""
        proot = self._mk(tmp_path)
        # 不创建 worktree
        groups = dash_data.parse_tasks(proot, "wtspec", "implementing", live=False)
        flat = [t for g in groups for t in g["tasks"]]
        # 主树全部未勾 → 0 done
        done = sum(t["done"] for t in flat)
        assert done == 0


# ── FileWatcher（推送数据源监听） ──────────────────────────────────────

class _FakeHub:
    """记录广播事件的替身 hub（不真的推送给浏览器）。"""

    def __init__(self):
        self.events = []      # [(event_dict, run_id)]
        self.watched = set()

    def broadcast(self, event, run_id=None):
        self.events.append((event, run_id))

    def is_watched(self, run_id):
        return run_id in self.watched


class TestFileWatcher:
    def _mk(self, tmp_path):
        proot = make_project(tmp_path)
        hub = _FakeHub()
        w = FileWatcher(
            lambda: [{"name": "proj-a", "path": str(proot), "exists": True}], hub
        )
        return proot, hub, w

    def test_state_change_pushes_overview_specs_and_changed_detail(self, tmp_path):
        proot, hub, w = self._mk(tmp_path)
        w.scan_once()  # 建立基线
        hub.events.clear()
        # STATE.md 中 myspec 状态变化
        state = proot / "STATE.md"
        state.write_text(state.read_text(encoding="utf-8")
                         .replace("- status: testing", "- status: implemented"),
                         encoding="utf-8")
        w.scan_once()
        state_events = [e for e, _ in hub.events if e["type"] == "state"]
        assert state_events, "STATE.md 变化应广播 state 事件"
        ev = state_events[0]
        assert ev["project"] == "proj-a"
        assert ev["overview"]["totals"]["spec_count"] == 2
        names = {s["name"] for s in ev["specs"]["specs"]}
        assert names == {"myspec", "otherspec"}
        # 变化 SPEC 的详情随事件推送，且不含事件流
        assert "myspec" in ev["details"]
        assert "events" not in ev["details"]["myspec"]

    def test_spec_file_change_pushes_detail(self, tmp_path):
        proot, hub, w = self._mk(tmp_path)
        w.scan_once()
        hub.events.clear()
        tasks = proot / "openspec" / "changes" / "myspec" / "tasks.md"
        tasks.write_text(tasks.read_text(encoding="utf-8") + "- [x] 1.2 任务二\n", encoding="utf-8")
        w.scan_once()
        detail_events = [e for e, _ in hub.events if e["type"] == "detail"]
        assert detail_events and detail_events[0]["spec"] == "myspec"
        assert detail_events[0]["data"]["status"] == "testing"

    def test_run_growth_pushes_incremental_events_when_watched(self, tmp_path):
        proot, hub, w = self._mk(tmp_path)
        hub.watched.add("impl-myspec-1780000000")
        w.scan_once()  # 建立 run 基线
        hub.events.clear()
        run_file = proot / ".fenix" / "runs" / "impl-myspec-1780000000.jsonl"
        with run_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "追加"}]}}, ensure_ascii=False) + "\n")
        w.scan_once()
        run_events = [e for e, _ in hub.events if e["type"] == "run_events"]
        assert run_events and run_events[0]["run_id"] == "impl-myspec-1780000000"
        assert len(run_events[0]["events"]) == 1
        assert run_events[0]["events"][0]["type"] == "assistant"
        assert run_events[0].get("reset") is not True

    def test_run_status_transition_pushes_run_meta(self, tmp_path):
        proot, hub, w = self._mk(tmp_path)
        w.scan_once()
        hub.events.clear()
        # 追加 result 行 → 该 run 从 running 变为 done（fixture 的 verify run 是 running）
        run_file = proot / ".fenix" / "runs" / "verify-myspec-1780001000.jsonl"
        with run_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "result", "result": "ok", "num_turns": 1}) + "\n")
        w.scan_once()
        metas = [e for e, _ in hub.events if e["type"] == "run_meta"]
        assert metas and metas[0]["run_id"] == "verify-myspec-1780001000"
        assert metas[0]["status"] == "done"

    def test_no_change_no_broadcast(self, tmp_path):
        proot, hub, w = self._mk(tmp_path)
        w.scan_once()
        hub.events.clear()
        w.scan_once()
        assert hub.events == []

    def test_periodic_heartbeat_broadcasts_refresh(self, tmp_path):
        # daemon 健康状态/新项目发现不产生文件变更，scan_once 感知不到；
        # 需周期性广播 refresh，否则概览徽标不会自动更新（验证发现的真实缺陷）。
        proot, hub, _ = self._mk(tmp_path)
        w = FileWatcher(
            lambda: [{"name": "proj-a", "path": str(proot), "exists": True}],
            hub, interval=0.01, heartbeat=0.02,
        )
        w.scan_once()  # 建立基线（首轮会广播一次 state，之后无变化不再广播）
        hub.events.clear()
        w.start()
        time.sleep(0.15)
        w.stop()
        refreshes = [e for e, _ in hub.events if e["type"] == "refresh"]
        assert refreshes, "周期性心跳应广播 refresh 事件"
        assert not any(e["type"] == "state" for e, _ in hub.events), "无文件变化不应广播 state"

    def test_run_events_not_pushed_when_unwatched(self, tmp_path):
        proot, hub, w = self._mk(tmp_path)
        w.scan_once()  # 无人订阅
        hub.events.clear()
        run_file = proot / ".fenix" / "runs" / "impl-myspec-1780000000.jsonl"
        with run_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "x"}]}}) + "\n")
        w.scan_once()
        assert not any(e["type"] == "run_events" for e, _ in hub.events)


# ── SSE Hub ────────────────────────────────────────────────────────────

class TestSSEHub:
    def test_register_broadcast_unregister(self):
        from core.dashboard.server import SSEHub
        hub = SSEHub()
        conn = hub.register()
        got = []
        hub.broadcast({"type": "refresh"})
        assert conn.id
        assert conn.queue.qsize() == 1
        hub.unregister(conn)
        hub.broadcast({"type": "detail", "spec": "x", "data": {}})
        assert conn.queue.qsize() == 1  # 注销后不再接收


# ── server.py：SSE 流 / tail / watch 端点 ──────────────────────────────

class TestServerPush:
    def test_api_run_tail_truncation(self, server_fx):
        _, srv = server_fx
        status, data = srv.get("/api/runs/impl-myspec-1780000000?project=proj-a&tail=1")
        assert status == 200
        assert data["total_events"] == 3
        assert len(data["events"]) == 1
        assert data["events"][-1]["type"] == "result"

    def test_api_spec_detail_has_no_run_events(self, server_fx):
        _, srv = server_fx
        status, data = srv.get("/api/specs/myspec?project=proj-a")
        assert status == 200
        assert "events" not in data
        for r in data["runs"]:
            assert "events" not in r

    def test_api_run_watch_roundtrip(self, server_fx):
        _, srv = server_fx
        conn = srv.httpd.sse_hub.register()
        cid = conn.id
        run_id = "impl-myspec-1780000000"
        status, data = srv.post(f"/api/runs/{run_id}/watch?project=proj-a&cid={cid}")
        assert status == 200 and data.get("ok")
        assert srv.httpd.sse_hub.is_watched(run_id)
        status, data = srv.delete(f"/api/runs/{run_id}/watch?project=proj-a&cid={cid}")
        assert status == 200
        assert not srv.httpd.sse_hub.is_watched(run_id)

    def test_api_run_watch_missing_cid(self, server_fx):
        _, srv = server_fx
        status, data = srv.post("/api/runs/impl-myspec-1780000000/watch?project=proj-a")
        assert status == 200
        assert data.get("error") == "missing cid"

    def test_sse_stream_hello_and_broadcast(self, server_fx):
        _, srv = server_fx
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
        try:
            conn.request("GET", "/api/stream")
            resp = conn.getresponse()
            assert resp.status == 200
            assert resp.getheader("Content-Type") == "text/event-stream"
            first = resp.read1(65536)
            assert b"hello" in first and b'"cid"' in first
            srv.httpd.sse_hub.broadcast({"type": "refresh", "project": "proj-a"})
            second = resp.read1(65536)
            assert b'"refresh"' in second or b'"type": "refresh"' in second
        finally:
            conn.close()
