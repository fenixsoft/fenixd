"""
Tests for Dashboard file watcher and SSE functionality.

Split from test_dashboard.py as part of refactor-test-structure.
Updated for dashboard-incremental-watcher: incremental state events,
directory-level signature skip, SummaryIndex file-level diff.
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
        "- updated: 2026-01-02T00:00:00+00:00\n- error: null\n- depends_on: null\n",
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
        index = dash_data.SummaryIndex()
        w = FileWatcher(
            lambda: [{"name": "proj-a", "path": str(proot), "exists": True}], hub,
            summary_index=index,
        )
        return proot, hub, w

    def _atomic_replace_tasks(self, proot, spec_name, new_content):
        """原子替换 tasks.md（模拟 Fenix 写路径：tmp + os.replace 更新父目录 mtime）。

        等长/相近时间片内 os.replace 可能落在同一 stat 粒度内不改目录签名，故
        显式前推 spec 目录 mtime —— 等价于真实时间片间隔下 os.replace 的效果。
        """
        tasks = proot / "openspec" / "changes" / spec_name / "tasks.md"
        tmp = tasks.parent / ".tasks.md.tmp"
        tmp.write_text(new_content, encoding="utf-8")
        os.replace(str(tmp), str(tasks))
        # 等长写入可能未推进目录 mtime：显式前推 1ms，保证目录签名可见变化
        st = tasks.parent.stat()
        os.utime(tasks.parent, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))

    def test_state_change_pushes_incremental_state(self, tmp_path):
        proot, hub, w = self._mk(tmp_path)
        w.scan_once()  # 建立基线
        hub.events.clear()
        state = proot / "STATE.md"
        new_content = state.read_text(encoding="utf-8").replace("- status: testing", "- status: implemented")
        self._atomic_replace_state(proot, new_content)
        w.scan_once()
        state_events = [e for e, _ in hub.events if e["type"] == "state"]
        assert state_events, "STATE.md 变化应广播 state 事件"
        ev = state_events[0]
        assert ev["project"] == "proj-a"
        assert ev["overview"] is None, "增量模式不再下发 overview"
        # myspec 状态变更 → 应在 specs 中
        specs = ev.get("specs", [])
        names = [s["spec"] for s in specs]
        assert "myspec" in names, f"变更的 spec 应出现在增量 specs: {names}"
        # 未变的 spec 不应出现在增量中
        assert len(specs) == 1, f"仅变更 spec 应出现，实际: {len(specs)} 条"

    def _atomic_replace_state(self, proot, new_content):
        """原子替换 STATE.md。"""
        state = proot / "STATE.md"
        tmp = proot / ".STATE.md.tmp"
        tmp.write_text(new_content, encoding="utf-8")
        os.replace(str(tmp), str(state))

    def test_spec_file_change_pushes_detail(self, tmp_path):
        proot, hub, w = self._mk(tmp_path)
        w.scan_once()
        hub.events.clear()
        # 原子替换 tasks.md → 更新 spec 目录 mtime → 目录签名变化 → 检测到
        new_content = (
            "## 1. 阶段一\n\n"
            "- [x] 1.1 任务一\n"
            "- [x] 1.2 任务二\n\n"
            "## 2. 阶段二\n\n"
            "- [ ] 2.1 任务三\n"
        )
        self._atomic_replace_tasks(proot, "myspec", new_content)
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
