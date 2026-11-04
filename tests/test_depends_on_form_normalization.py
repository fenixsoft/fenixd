"""
Tests for SPEC 级 depends_on 形态归一（state_machine 单源）。

覆盖 2026-11-03 add-knowledge-inbox-pipeline 派发卡死事故：depends_on 以
YAML 列表形态（``['A']``）落盘后，读回原始字符串，PMEngine 的
``str(deps).split(",")`` 解析口径把单元素列表 str() 成带引号方括号的脏名
``['A']``（无逗号可拆，整串当一个依赖名）→ 查无此 SPEC → fail-closed
永判「依赖未满足」，依赖方转 pushed 后依赖方 SPEC 仍永不派发。

修复形态归一单源在 ``core.state_machine._normalize_depends_on``：
读侧（``_parse_content``）+ 写侧（``add_spec`` / ``_apply_updates_entry``）
共用，内存态恒为规范逗号分隔字符串，serialize 落盘自动自愈历史列表形态。
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import StateMachine, StateParser, _normalize_depends_on


class TestNormalizeDependsOnHelper(unittest.TestCase):
    """归一助手单测：各形态入参 → 规范逗号分隔字符串。"""

    def test_none_and_null_literals(self):
        self.assertIsNone(_normalize_depends_on(None))
        self.assertIsNone(_normalize_depends_on("null"))
        self.assertIsNone(_normalize_depends_on("none"))
        self.assertIsNone(_normalize_depends_on(""))
        self.assertIsNone(_normalize_depends_on("Null"))

    def test_canonical_string_passthrough(self):
        self.assertEqual(_normalize_depends_on("A"), "A")
        self.assertEqual(_normalize_depends_on("A,B"), "A,B")
        # 外层空白 strip，元素内空格保留（消费点 split 后自行 strip 元素）
        self.assertEqual(_normalize_depends_on(" A , B "), "A , B")

    def test_list_value_normalized(self):
        self.assertEqual(_normalize_depends_on(["A"]), "A")
        self.assertEqual(_normalize_depends_on(["A", "B"]), "A,B")
        self.assertEqual(_normalize_depends_on(("A",)), "A")
        self.assertIsNone(_normalize_depends_on([]))
        self.assertIsNone(_normalize_depends_on(["", "  "]))

    def test_list_literal_string_normalized(self):
        # 事故形态：STATE.md 原始行读回的字符串化列表
        self.assertEqual(_normalize_depends_on("['A']"), "A")
        self.assertEqual(_normalize_depends_on("['A', 'B']"), "A,B")
        self.assertEqual(_normalize_depends_on('["A","B"]'), "A,B")

    def test_unparseable_literal_kept_as_is(self):
        # 拆不动的坏值原样保留（外层 strip，不吞数据），消费侧维持既有
        # fail-closed 口径
        self.assertEqual(_normalize_depends_on("['A', "), "['A',")


class TestParserReadSideNormalization(unittest.TestCase):
    """读侧：STATE.md 中的列表形态行解析为规范逗号串。"""

    def test_parse_list_form_single(self):
        content = (
            "## Specs\n\n### A\n- status: ready\n- depends_on: ['B']\n"
        )
        entry = StateParser._parse_content(content)["A"]
        self.assertEqual(entry["depends_on"], "B")

    def test_parse_list_form_multi(self):
        content = (
            "## Specs\n\n### A\n- status: ready\n- depends_on: ['B', 'C']\n"
        )
        entry = StateParser._parse_content(content)["A"]
        self.assertEqual(entry["depends_on"], "B,C")

    def test_parse_null_literal_unchanged(self):
        # 迁移守卫：可空清单迁出后 null 语义不得回归（56f1aefd2823 契约）
        content = "## Specs\n\n### A\n- status: ready\n- depends_on: null\n"
        entry = StateParser._parse_content(content)["A"]
        self.assertIsNone(entry["depends_on"])

    def test_parse_canonical_unchanged(self):
        content = "## Specs\n\n### A\n- status: ready\n- depends_on: B,C\n"
        entry = StateParser._parse_content(content)["A"]
        self.assertEqual(entry["depends_on"], "B,C")


class TestWriteSideNormalization(unittest.TestCase):
    """写侧：add_spec / update_spec 传入列表形态落盘为规范串。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.state_path.parent.mkdir(parents=True)
        self.sm = StateMachine(self.state_path, MagicMock())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_add_spec_list_form(self):
        self.sm.add_spec("A", {"status": "ready", "depends_on": ["B"]})
        entry = self.sm.read_one("A")
        self.assertEqual(entry["depends_on"], "B")
        self.assertIn("- depends_on: B", self.state_path.read_text())

    def test_add_spec_list_multi_form(self):
        self.sm.add_spec("A", {"status": "ready", "depends_on": ["B", "C"]})
        self.assertEqual(self.sm.read_one("A")["depends_on"], "B,C")
        self.assertIn("- depends_on: B,C", self.state_path.read_text())

    def test_update_spec_list_form(self):
        self.sm.add_spec("A", {"status": "ready", "depends_on": "B"})
        self.sm.update_spec("A", {"depends_on": ["C", "D"]})
        self.assertEqual(self.sm.read_one("A")["depends_on"], "C,D")
        self.assertIn("- depends_on: C,D", self.state_path.read_text())

    def test_history_list_form_selfheals_on_rewrite(self):
        # 历史 STATE.md 已落的列表形态：任一次写侧全量回写即自愈为规范串
        self.state_path.write_text(
            "## Specs\n\n### A\n- status: ready\n"
            "- depends_on: ['B']\n- priority: 5\n"
        )
        self.sm.update_spec("A", {"priority": 6})
        self.assertIn("- depends_on: B", self.state_path.read_text())
        self.assertNotIn("['B']", self.state_path.read_text())


class TestDependencySatisfiedEndToEnd(unittest.TestCase):
    """端到端回归：列表形态 depends_on 不再卡死派发门（事故本体）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir()
        self.logger = MagicMock()
        self.state_path = self.project_root / ".fenix" / "STATE.md"
        self.sm = StateMachine(self.state_path, self.logger)
        from core.pm_engine import PMEngine
        self.engine = PMEngine(self.sm, MagicMock(), {}, self.project_root,
                               self.logger)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_list_form_dep_satisfied_when_dep_pushed(self):
        # 复现事故形态：B 已 pushed，A 的 depends_on 以列表形态登记——
        # 修复前 _dependencies_satisfied 解析出脏名 ['B'] 查无此 SPEC 恒 False
        self.sm.add_spec("A", {"status": "ready", "depends_on": ["B"]})
        self.sm.add_spec("B", {"status": "pushed"})
        self.assertTrue(self.engine._dependencies_satisfied("A"))

    def test_canonical_dep_blocked_when_dep_implementing(self):
        # 对照组：规范形态下依赖未到接受态仍正确 fail-closed
        self.sm.add_spec("A", {"status": "ready", "depends_on": "B"})
        self.sm.add_spec("B", {"status": "implementing"})
        self.assertFalse(self.engine._dependencies_satisfied("A"))


if __name__ == "__main__":
    unittest.main()
