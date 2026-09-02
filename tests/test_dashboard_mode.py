"""add-fast-track-mode task 7.1：Dashboard data 层 mode 输出测试。"""

import json
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
        (self.root / "STATE.md").write_text("", encoding="utf-8")
        self.sm = StateMachine(self.root / "STATE.md", None)

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


if __name__ == "__main__":
    unittest.main()