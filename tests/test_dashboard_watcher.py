"""
Tests for Dashboard file watcher and SSE functionality.

Split from test_dashboard.py as part of refactor-test-structure.
Updated for dashboard-incremental-watcher: incremental state events,
directory-level signature skip, SummaryIndex file-level diff.
"""
import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.dashboard import data as dash_data
from core.dashboard.watcher import FileWatcher

# make_project 已收敛至 tests/conftest.py；otherspec=False 对齐本文件原本地变体
# （STATE.md 不含 otherspec 条目），其余内容与 conftest 版逐字节一致。
from conftest import make_project


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
        proot = make_project(tmp_path, otherspec=False)
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
        tasks = proot / "spec" / "changes" / spec_name / "tasks.md"
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
        state = proot / ".fenix" / "STATE.md"
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
        state = proot / ".fenix" / "STATE.md"
        tmp = proot / ".fenix" / ".STATE.md.tmp"
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
