"""
Tests for Dashboard file watcher and SSE functionality.

Split from test_dashboard.py as part of refactor-test-structure.
"""
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.dashboard import data as dash_data
from core.dashboard.registry import Registry
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

    # 事件日志
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
        assert isinstance(ev["specs"], list), "state 事件 specs 应为数组"
        names = {s["name"] for s in ev["specs"]}
        assert names == {"myspec", "otherspec"}
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
        proot, hub, _ = self._mk(tmp_path)
        w = FileWatcher(
            lambda: [{"name": "proj-a", "path": str(proot), "exists": True}],
            hub, interval=0.01, heartbeat=0.02,
        )
        w.scan_once()  # 建立基线
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
