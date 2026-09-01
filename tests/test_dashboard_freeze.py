"""
SPEC 人工冻结/解冻测试（Dashboard「更多」菜单 freeze/unfreeze 的数据层）。

冻结语义（人工冻结处方）：status=blocked + error 以「用户指令冻结：」开头，
admin_monitor 认此模式为有意等待态（免超时误报）；done/pushed 终态不可冻结；
解冻恢复冻结前状态并清空 error。
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def make_frozen_fixture_project(tmp_path: Path, name: str = "proj-a") -> Path:
    """最小可解析项目：仅 STATE.md（冻结测试只依赖 STATE 读写）。"""
    proot = tmp_path / name
    proot.mkdir(parents=True, exist_ok=True)
    (proot / "STATE.md").write_text(
        "# Fenix Project State\n\n## Specs\n\n"
        "### myspec\n- status: testing\n- priority: 2\n"
        "- created: 2026-01-01T00:00:00+00:00\n- updated: 2026-01-02T00:00:00+00:00\n"
        "- error: null\n- depends_on: null\n\n"
        "### donespec\n- status: done\n- priority: 1\n"
        "- created: 2026-01-01T00:00:00+00:00\n- updated: 2026-01-02T00:00:00+00:00\n"
        "- error: null\n- depends_on: null\n",
        encoding="utf-8",
    )
    return proot


class TestSpecFreeze(unittest.TestCase):
    """freeze_spec / unfreeze_spec / is_spec_frozen。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = make_frozen_fixture_project(Path(self.tmpdir))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _entry(self, spec: str) -> dict:
        from core.dashboard.data import parse_state
        return parse_state(self.proot)[spec]

    def test_freeze_sets_blocked_and_error_prefix(self):
        from core.dashboard.data import freeze_spec, is_spec_frozen
        r = freeze_spec(self.proot, "myspec")
        self.assertTrue(r["ok"])
        self.assertTrue(r["frozen"])
        entry = self._entry("myspec")
        self.assertEqual(entry["status"], "blocked")
        self.assertTrue(entry["error"].startswith("用户指令冻结："))
        self.assertIn("testing", entry["error"])  # 记录原状态，供解冻恢复
        self.assertTrue(is_spec_frozen(entry))

    def test_unfreeze_restores_original_status(self):
        from core.dashboard.data import freeze_spec, unfreeze_spec
        freeze_spec(self.proot, "myspec")
        r = unfreeze_spec(self.proot, "myspec")
        self.assertTrue(r["ok"])
        self.assertFalse(r["frozen"])
        entry = self._entry("myspec")
        self.assertEqual(entry["status"], "testing")  # 恢复冻结前状态
        self.assertIsNone(entry["error"])
        from core.dashboard.data import is_spec_frozen
        self.assertFalse(is_spec_frozen(entry))

    def test_freeze_terminal_state_rejected(self):
        from core.dashboard.data import freeze_spec
        r = freeze_spec(self.proot, "donespec")
        self.assertTrue(r["ok"])
        self.assertFalse(r["frozen"])  # 终态拒绝冻结（请求本身成功）
        self.assertEqual(self._entry("donespec")["status"], "done")

    def test_unfreeze_non_frozen_is_noop(self):
        from core.dashboard.data import unfreeze_spec
        r = unfreeze_spec(self.proot, "myspec")
        self.assertTrue(r["ok"])
        self.assertFalse(r["frozen"])
        self.assertEqual(self._entry("myspec")["status"], "testing")

    def test_freeze_unknown_spec_not_found(self):
        from core.dashboard.data import freeze_spec
        r = freeze_spec(self.proot, "nope")
        self.assertFalse(r["ok"])
        self.assertFalse(r["found"])

    def test_freeze_twice_stays_frozen(self):
        from core.dashboard.data import freeze_spec, is_spec_frozen
        freeze_spec(self.proot, "myspec")
        r = freeze_spec(self.proot, "myspec")
        self.assertTrue(r["ok"])
        self.assertTrue(r["frozen"])
        self.assertTrue(is_spec_frozen(self._entry("myspec")))


if __name__ == "__main__":
    unittest.main()
