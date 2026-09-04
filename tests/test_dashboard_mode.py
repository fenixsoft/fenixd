"""add-fast-track-mode task 7.1：Dashboard data 层 mode 输出测试。"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.dashboard.data import spec_summary, spec_detail
from core.state_machine import StateMachine


def _mk_spec(root, name, mode=None):
    d = root / "openspec" / "changes" / name
    d.mkdir(parents=True, exist_ok=True)
    lines = ["schema: spec-driven", "created: 2026-09-02"]
    if mode:
        lines.append(f"mode: {mode}")
    (d / ".openspec.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (d / "tasks.md").write_text("# Tasks\n\n## 1. x\n\n- [ ] 1.1 do\n", encoding="utf-8")


class TestDashboardMode(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        (self.root / ".fenix").mkdir(parents=True, exist_ok=True)
        (self.root / ".fenix" / "STATE.md").write_text("", encoding="utf-8")
        self.sm = StateMachine(self.root / ".fenix" / "STATE.md", None)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _add(self, name, mode=None):
        _mk_spec(self.root, name, mode)
        self.sm.add_spec(name, {"priority": 5, "status": "ready"})
        return self.sm.read_one(name)

    def test_spec_summary_fast_track(self):
        entry = self._add("ft-spec", mode="fast-track")
        s = spec_summary(self.root, "ft-spec", entry)
        self.assertEqual(s["mode"], "fast-track")

    def test_spec_summary_default_full(self):
        entry = self._add("legacy-spec", mode=None)
        s = spec_summary(self.root, "legacy-spec", entry)
        self.assertEqual(s["mode"], "full")

    def test_spec_summary_explicit_full(self):
        entry = self._add("full-spec", mode="full")
        s = spec_summary(self.root, "full-spec", entry)
        self.assertEqual(s["mode"], "full")

    def test_spec_detail_mode(self):
        entry = self._add("ft-spec", mode="fast-track")
        d = spec_detail(self.root, "ft-spec", entry)
        self.assertEqual(d["mode"], "fast-track")


class TestSpecSummaryDurationPersistence(unittest.TestCase):
    """add-done-duration-persist 3.3：spec_summary 对 STATE.md 固化 total_duration 的读取优先级。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        (self.root / ".fenix").mkdir(parents=True, exist_ok=True)
        (self.root / ".fenix" / "STATE.md").write_text("", encoding="utf-8")
        _mk_spec(self.root, "demo")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_run(self, run_id, start_ts, duration):
        """创建 run 产物并定 mtime，使 duration_seconds = duration。"""
        runs_dir = self.root / ".fenix" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        p = runs_dir / f"{run_id}.jsonl"
        p.write_text("", encoding="utf-8")
        os.utime(p, (start_ts + duration, start_ts + duration))

    def test_done_uses_persisted_value_without_runs(self):
        """① done spec 有字段时返回字段值（run 产物缺失也返回）。"""
        s = spec_summary(self.root, "demo", {"status": "done", "total_duration": "150"})
        self.assertEqual(s["total_duration"], 150)

    def test_done_missing_field_falls_back_to_sum(self):
        """② done spec 缺字段回退求和。"""
        self._make_run("impl-demo-1789000000-a1", 1789000000, 42)
        s = spec_summary(self.root, "demo", {"status": "done"})
        self.assertEqual(s["total_duration"], 42)

    def test_pushed_uses_persisted_value(self):
        """③ pushed spec 有字段时同样直接返回。"""
        s = spec_summary(self.root, "demo", {"status": "pushed", "total_duration": "150"})
        self.assertEqual(s["total_duration"], 150)

    def test_implementing_ignores_persisted_field(self):
        """④ implementing spec 忽略字段，仍走实时求和。"""
        self._make_run("impl-demo-1789000000-a1", 1789000000, 42)
        s = spec_summary(self.root, "demo",
                         {"status": "implementing", "total_duration": "150"})
        self.assertEqual(s["total_duration"], 42)

    def test_dirty_value_falls_back_to_sum(self):
        """⑤ 字段为脏值（非数字）时回退求和不报错。"""
        self._make_run("impl-demo-1789000000-a1", 1789000000, 42)
        s = spec_summary(self.root, "demo", {"status": "done", "total_duration": "abc"})
        self.assertEqual(s["total_duration"], 42)


if __name__ == "__main__":
    unittest.main()
