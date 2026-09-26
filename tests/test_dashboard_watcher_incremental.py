"""
Tests for dashboard-incremental-watcher: incremental state broadcasts,
directory-level signature skip, spec add/remove markers, payload size budget.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.dashboard import data as dash_data
from core.dashboard.watcher import FileWatcher


# ── 辅助：构造一个可用的 Fenixd 项目目录 ──────────────────────────────

def make_project(tmp_path: Path, name: str = "proj-a") -> Path:
    proot = tmp_path / name
    (proot / ".fenix" / "logs").mkdir(parents=True, exist_ok=True)
    (proot / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
    (proot / ".fenix" / "verify-progress" / "myspec" / "screenshots").mkdir(parents=True, exist_ok=True)
    (proot / "spec" / "changes" / "myspec" / "specs").mkdir(parents=True, exist_ok=True)
    (proot / "spec" / "changes" / "otherspec" / "specs").mkdir(parents=True, exist_ok=True)

    (proot / ".fenix" / "STATE.md").write_text(
        "# Fenix Project State\n\n## Specs\n\n"
        "### myspec\n- status: testing\n- priority: 2\n- created: 2026-01-01T00:00:00+00:00\n"
        "- updated: 2026-01-02T00:00:00+00:00\n- error: null\n- depends_on: null\n\n"
        "### otherspec\n- status: done\n- priority: 1\n- created: 2026-02-01T00:00:00+00:00\n"
        "- updated: 2026-02-02T00:00:00+00:00\n- error: null\n- depends_on: null\n",
        encoding="utf-8",
    )
    (proot / ".fenix" / "config.yaml").write_text("project:\n  name: fake\n", encoding="utf-8")

    (proot / "spec" / "changes" / "myspec" / "tasks.md").write_text(
        "## 1. 阶段一\n\n"
        "- [x] 1.1 任务一\n"
        "- [ ] 1.2 任务二\n",
        encoding="utf-8",
    )
    (proot / "spec" / "changes" / "otherspec" / "tasks.md").write_text(
        "## 1. 完成\n\n- [x] 1.1 任务一\n", encoding="utf-8",
    )
    return proot


class _FakeHub:
    def __init__(self):
        self.events = []
        self.watched = set()

    def broadcast(self, event, run_id=None):
        self.events.append((event, run_id))

    def is_watched(self, run_id):
        return run_id in self.watched


class TestIncrementalWatcher:
    def _mk(self, tmp_path, name="proj-a"):
        proot = make_project(tmp_path, name)
        hub = _FakeHub()
        index = dash_data.SummaryIndex()
        w = FileWatcher(
            lambda: [{"name": name, "path": str(proot), "exists": True}], hub,
            summary_index=index,
        )
        return proot, hub, w

    @staticmethod
    def _bump_dir_mtime(d: Path):
        """前推目录 mtime 1ms，保证目录签名可见变化（模拟时间片间隔下的 os.replace）。"""
        st = d.stat()
        os.utime(d, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))

    def _atomic_write(self, path: Path, content: str):
        path.write_text(content, encoding="utf-8")
        # 等长/同 tick 内写入可能不推进文件 mtime：显式前推，保证文件级签名可见
        st = path.stat()
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
        self._bump_dir_mtime(path.parent)

    def test_log_append_pushes_small_incremental(self, tmp_path):
        proot, hub, w = self._mk(tmp_path)
        w.scan_once()
        hub.events.clear()
        log = proot / ".fenix" / "logs" / "fenixd-2026.log"
        if not log.exists():
            log.write_text("", encoding="utf-8")
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"timestamp": "2026-01-01T00:00:00Z", "level": "INFO",
                                "component": "pm_engine", "message": "x"}) + "\n")
        w.scan_once()
        state_events = [e for e, _ in hub.events if e["type"] == "state"]
        assert state_events, "日志追加应广播 state 事件"
        ev = state_events[0]
        # 增量：specs/details 为空或仅含受影响 spec；payload < 2KB
        payload = json.dumps(ev, ensure_ascii=False).encode("utf-8")
        assert len(payload) < 2000, f"增量 payload 应 <2KB，实际 {len(payload)}B"
        assert ev["overview"] is None
        assert ev["specs"] == [] or all(isinstance(s, dict) for s in ev["specs"])

    def test_log_append_does_not_resend_unchanged_specs(self, tmp_path):
        """日志追加（无 spec 文件变化）时 specs 应为空，不推全量列表。"""
        proot, hub, w = self._mk(tmp_path)
        w.scan_once()
        hub.events.clear()
        # 基线建立后清空，再手动触发日志追加
        w._last_summaries["proj-a"] = {
            s["name"]: s for s in w.summary_index.get(proot)
        }
        log = proot / ".fenix" / "logs" / "fenixd-2026.log"
        if not log.exists():
            log.write_text("", encoding="utf-8")
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"timestamp": "2026-01-01T00:00:00Z", "message": "y"}) + "\n")
        w.scan_once()
        state_events = [e for e, _ in hub.events if e["type"] == "state"]
        assert state_events
        assert state_events[0]["specs"] == [], "无 spec 文件变化时增量 specs 应为空"

    def test_single_spec_change_pushes_single_entry(self, tmp_path):
        proot, hub, w = self._mk(tmp_path)
        w.scan_once()
        hub.events.clear()
        tasks = proot / "spec" / "changes" / "myspec" / "tasks.md"
        self._atomic_write(tasks, tasks.read_text(encoding="utf-8").replace(
            "- [ ] 1.2", "- [x] 1.2"))
        w.scan_once()
        state_events = [e for e, _ in hub.events if e["type"] == "state"]
        assert state_events
        specs = state_events[0]["specs"]
        # 仅 myspec 一条，且 summary 反映新任务完成数
        assert len(specs) == 1, f"应只推 1 条变更: {specs}"
        assert specs[0]["spec"] == "myspec"
        assert specs[0]["summary"]["task_done"] == 2

    def test_spec_delete_pushes_null_marker(self, tmp_path):
        proot, hub, w = self._mk(tmp_path)
        w.scan_once()
        hub.events.clear()
        # otherspec 目录删除 → changes/ 目录签名变化 → _scan_spec_dirs 返回 removed
        otherspec = proot / "spec" / "changes" / "otherspec"
        import shutil
        shutil.rmtree(str(otherspec))
        self._bump_dir_mtime(proot / "spec" / "changes")
        w.scan_once()
        state_events = [e for e, _ in hub.events if e["type"] == "state"]
        assert state_events
        specs = state_events[0]["specs"]
        null_specs = [s for s in specs if s.get("summary") is None]
        assert any(s["spec"] == "otherspec" for s in null_specs), \
            f"删除的 spec 应推 summary:null 标记: {specs}"

    # 注：原 test_directory_signature_skip_zero_file_stat 已删除——其文件打开计数
    # 断言为恒真（`opens["n"] == 0 or True`），剩余断言（无变化零广播）与
    # test_dashboard_watcher.py::TestFileWatcher::test_no_change_no_broadcast 重复。

    def test_scale_1000_fake_spec_dirs_under_50ms(self, tmp_path):
        """规模基准：1000 个假 spec 目录（含 tasks.md 与空 specs/）一轮 scan <50ms。"""
        proot = make_project(tmp_path, "big")
        # 追加 1000 个假 spec 目录
        for i in range(1000):
            d = proot / "spec" / "changes" / f"fakespec{i:04d}"
            (d / "specs").mkdir(parents=True, exist_ok=True)
            (d / "tasks.md").write_text("## 1. X\n\n- [ ] 1.1 a\n", encoding="utf-8")
        hub = _FakeHub()
        index = dash_data.SummaryIndex()
        w = FileWatcher(
            lambda: [{"name": "big", "path": str(proot), "exists": True}], hub,
            summary_index=index,
        )
        t0 = time.perf_counter()
        w.scan_once()  # 建立基线（含索引构建）
        t1 = time.perf_counter()
        # 命中轮：目录签名全部命中，不做文件级遍历。连扫 5 轮取最优值判定：
        # 单轮墙钟在全量回归高负载下会抖过 50ms（实测 73.1ms 误报），而误退化
        # 成文件级遍历会让每一轮都数倍于阈值，min 口径不放过真回归。
        hit_times = []
        for _ in range(5):
            s = time.perf_counter()
            w.scan_once()
            hit_times.append(time.perf_counter() - s)
        first = t1 - t0
        second = min(hit_times)
        # 首次含 1000 spec 索引构建会比较慢；目录签名命中轮应 <50ms
        assert second < 0.05, \
            f"目录签名命中轮应 <50ms（5 轮最优），实际 {second*1000:.1f}ms"