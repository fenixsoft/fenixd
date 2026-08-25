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

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.dashboard import data as dash_data
from core.dashboard.registry import Registry
from core.dashboard.server import DashboardHTTPServer, DashboardHandler, find_free_port


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
        assert bugs, "应从 report + verification-report.md 聚合到 bug"
        assert any(b["source"] == "report" and b["severity"] == "major" for b in bugs)
        assert any(b["source"] == "report-md" for b in bugs)

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
        types = [e["type"] for e in detail["events"]]
        assert types == ["system", "assistant", "result"]

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
    run_file = proot / ".fenix" / "runs" / f"impl-{spec}-{ts}.jsonl"
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


# ── registry.py ───────────────────────────────────────────────────────

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
        # 误检目录：有 STATE.md 但无 .fenix/config.yaml
        (tmp_path / "fake-proj").mkdir()
        (tmp_path / "fake-proj" / "STATE.md").write_text("# state", encoding="utf-8")

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
        assert "fake-proj" not in by_name   # 误检目录被排除

    def test_discover_missing_explicit_flagged(self, tmp_path):
        missing = tmp_path / "gone"
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "gone", "path": str(missing)}], "scan_dirs": []})
        projects = reg.discover()
        assert projects[0]["exists"] is False


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

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture()
def server_fx(tmp_path):
    proot = make_project(tmp_path)
    cfg = tmp_path / "dashboard.yaml"
    reg = Registry(config_path=cfg)
    reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}], "scan_dirs": []})
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
