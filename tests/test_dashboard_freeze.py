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
    """最小可解析项目：仅 .fenix/STATE.md（冻结测试只依赖 STATE 读写）。"""
    proot = tmp_path / name
    proot.mkdir(parents=True, exist_ok=True)
    (proot / ".fenix").mkdir(parents=True, exist_ok=True)
    (proot / ".fenix" / "STATE.md").write_text(
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


def make_auto_frozen_fixture_project(tmp_path: Path) -> Path:
    """自动冻结夹具：frozen: True + 自有文案（无「用户指令冻结：」前缀）。

    形态与真实写入端一致——内容闸门/预算闸门/env 阻塞冻结都是
    ``update_spec({status: blocked, frozen: True, error: <自有文案>})``。
    另含一条 ``frozen: False`` 的普通 blocked，覆盖 STATE.md 文本「False」
    被当成真值的字符串陷阱。
    """
    proot = tmp_path / "proj-auto"
    (proot / ".fenix").mkdir(parents=True, exist_ok=True)
    (proot / ".fenix" / "STATE.md").write_text(
        "# Fenix Project State\n\n## Specs\n\n"
        "### auto-frozen\n- status: blocked\n- priority: 5\n"
        "- created: 2026-01-01T00:00:00+00:00\n- updated: 2026-01-02T00:00:00+00:00\n"
        "- error: \"实现尝试预算耗尽（6/6）：已停止自动重派，需人工裁决\"\n"
        "- frozen: True\n- depends_on: null\n\n"
        "### plain-blocked\n- status: blocked\n- priority: 5\n"
        "- created: 2026-01-01T00:00:00+00:00\n- updated: 2026-01-02T00:00:00+00:00\n"
        "- error: \"熔断：连续失败\"\n"
        "- frozen: False\n- depends_on: null\n",
        encoding="utf-8",
    )
    return proot


class TestStructuredFreezeRecognition(unittest.TestCase):
    """自动冻结（内容闸门/预算闸门/env 阻塞）的结构化 frozen 标记识别。

    回归：``is_spec_frozen`` 与弹窗 ``isFrozen`` 此前只认 error 文本前缀，
    而自动冻结一律写自有文案（且 env 阻塞旧文案是「用户指令冻结（」全角括号、
    与常量根本不匹配）→ 自动冻结的 spec 在 UI 上既不显示冻结态也没有解冻按钮，
    ``/api/spec-unfreeze`` 与 ``/api/spec-freeze-config`` 一律判「未处于冻结态」。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = make_auto_frozen_fixture_project(Path(self.tmpdir))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _entry(self, spec: str) -> dict:
        from core.dashboard.data import parse_state
        return parse_state(self.proot)[spec]

    def test_frozen_field_recognized_without_text_prefix(self):
        from core.dashboard.data import is_spec_frozen
        self.assertTrue(
            is_spec_frozen(self._entry("auto-frozen")),
            "结构化 frozen: True + 自有文案（无文本前缀）同样算冻结态",
        )

    def test_frozen_false_string_not_treated_as_frozen(self):
        """STATE.md 的 ``frozen: False`` 是字符串 'False'——真值判定会误判。"""
        from core.dashboard.data import is_spec_frozen
        entry = self._entry("plain-blocked")
        self.assertIs(entry.get("frozen"), False,
                      "parse_state 须把 frozen 归一到真布尔，否则 'False' 恒真")
        self.assertFalse(is_spec_frozen(entry))

    def test_unfreeze_works_on_structured_freeze(self):
        """返回值 ``frozen`` 是解冻后态（恒 False）；真实解冻以 STATE 落盘判定。"""
        from core.dashboard.data import is_spec_frozen, unfreeze_spec
        r = unfreeze_spec(self.proot, "auto-frozen")
        self.assertTrue(r["ok"])
        entry = self._entry("auto-frozen")
        self.assertFalse(
            is_spec_frozen(entry),
            "结构化冻结须走真实解冻路径——no-op 会残留 blocked + frozen: True",
        )
        self.assertEqual(entry["status"], "ready")
        self.assertIsNone(entry["error"])

    def test_freeze_config_unfreeze_works_on_structured_freeze(self):
        from core.dashboard.data import configure_spec_freeze
        r = configure_spec_freeze(self.proot, "auto-frozen", "unfreeze")
        self.assertTrue(r["ok"])
        self.assertTrue(r.get("unfrozen"))

    def test_spec_summary_exposes_frozen_flag(self):
        from core.dashboard.data import spec_summary
        self.assertIs(spec_summary(self.proot, "auto-frozen",
                                   self._entry("auto-frozen"))["frozen"], True)
        self.assertIs(spec_summary(self.proot, "plain-blocked",
                                   self._entry("plain-blocked"))["frozen"], False)


if __name__ == "__main__":
    unittest.main()
