"""
Unit tests for core.spec_gen — fenix 原生 SPEC 生成器。

Run with: python3 -m pytest tests/test_spec_gen.py -q
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.spec_gen import instructions, new_change, status


class TestNewChange(unittest.TestCase):
    """new_change：创建 / 同名拒绝 / kebab-case 校验。"""

    def test_create_new_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = new_change(root, "add-user-login")
            self.assertTrue(result.is_dir())
            metadata = (root / "openspec" / "changes" / "add-user-login" / ".openspec.yaml").read_text(
                encoding="utf-8"
            )
            self.assertIn("schema: spec-driven", metadata)
            self.assertIn("created:", metadata)
            self.assertEqual(result, root / "openspec" / "changes" / "add-user-login")

    def test_duplicate_change_rejected_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            new_change(root, "add-user-login")
            existing = root / "openspec" / "changes" / "add-user-login" / "proposal.md"
            existing.write_text("sentinel", encoding="utf-8")
            with self.assertRaises(ValueError):
                new_change(root, "add-user-login")
            self.assertTrue(existing.exists())
            self.assertEqual(existing.read_text(encoding="utf-8"), "sentinel")

    def test_non_kebab_name_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ValueError):
                new_change(root, "Add User Login")
            self.assertFalse((root / "openspec" / "changes" / "Add User Login").exists())

    def test_uppercase_name_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                new_change(Path(tmp), "AddUserLogin")

    def test_consecutive_hyphens_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                new_change(Path(tmp), "add--user")

    def test_leading_digit_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                new_change(Path(tmp), "1-add-user")


class TestStatus(unittest.TestCase):
    """status：初始态 / 全完成 / 与 openspec --json 同构。"""

    def _make_change(self, root, name="add-user-login"):
        return new_change(root, name)

    def test_empty_change_initial_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_change(root)
            st = status(root, "add-user-login")
            self.assertEqual(st["changeName"], "add-user-login")
            self.assertEqual(st["schemaName"], "spec-driven")
            self.assertFalse(st["isComplete"])
            self.assertEqual(st["applyRequires"], ["tasks"])

            by_id = {a["id"]: a for a in st["artifacts"]}
            self.assertEqual(by_id["proposal"]["status"], "ready")
            self.assertEqual(by_id["proposal"]["outputPath"], "proposal.md")

            self.assertEqual(by_id["design"]["status"], "blocked")
            self.assertEqual(by_id["design"]["missingDeps"], ["proposal"])
            self.assertEqual(by_id["specs"]["status"], "blocked")
            self.assertEqual(by_id["specs"]["missingDeps"], ["proposal"])
            self.assertEqual(by_id["specs"]["outputPath"], "specs/**/*.md")
            self.assertEqual(by_id["tasks"]["status"], "blocked")
            self.assertEqual(by_id["tasks"]["missingDeps"], ["design", "specs"])

    def test_build_order_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_change(root)
            st = status(root, "add-user-login")
            self.assertEqual(
                [a["id"] for a in st["artifacts"]],
                ["proposal", "design", "specs", "tasks"],
            )

    def test_specs_done_with_any_md_under_specs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            name = "add-user-login"
            change_dir = self._make_change(root, name)
            (change_dir / "proposal.md").write_text("# P", encoding="utf-8")
            (change_dir / "specs" / "cap").mkdir(parents=True)
            (change_dir / "specs" / "cap" / "spec.md").write_text("# S", encoding="utf-8")
            st = status(root, name)
            by_id = {a["id"]: a for a in st["artifacts"]}
            self.assertEqual(by_id["specs"]["status"], "done")
            self.assertEqual(by_id["design"]["status"], "ready")
            self.assertEqual(by_id["tasks"]["status"], "blocked")

    def test_all_complete_apply_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            name = "add-user-login"
            change_dir = self._make_change(root, name)
            (change_dir / "proposal.md").write_text("# P", encoding="utf-8")
            (change_dir / "design.md").write_text("# D", encoding="utf-8")
            (change_dir / "specs" / "cap").mkdir(parents=True)
            (change_dir / "specs" / "cap" / "spec.md").write_text("# S", encoding="utf-8")
            (change_dir / "tasks.md").write_text("# T", encoding="utf-8")
            st = status(root, name)
            self.assertTrue(st["isComplete"])
            self.assertTrue(all(a["status"] == "done" for a in st["artifacts"]))

    def test_missing_change_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                status(Path(tmp), "not-exist")


class TestInstructions(unittest.TestCase):
    """instructions：proposal / tasks 内容与依赖。"""

    def _complete_deps(self, root, name):
        change_dir = root / "openspec" / "changes" / name
        (change_dir / "proposal.md").write_text("# P", encoding="utf-8")
        (change_dir / "design.md").write_text("# D", encoding="utf-8")
        (change_dir / "specs" / "cap").mkdir(parents=True)
        (change_dir / "specs" / "cap" / "spec.md").write_text("# S", encoding="utf-8")

    def test_proposal_instructions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            new_change(root, "add-user-login")
            ins = instructions(root, "proposal", "add-user-login")
            self.assertEqual(ins["changeName"], "add-user-login")
            self.assertEqual(ins["artifactId"], "proposal")
            self.assertEqual(ins["schemaName"], "spec-driven")
            self.assertEqual(ins["outputPath"], "proposal.md")
            self.assertTrue(ins["instruction"])
            self.assertIn("## Why", ins["template"])
            self.assertEqual(ins["dependencies"], [])
            self.assertEqual(ins["unlocks"], ["design", "specs"])
            self.assertTrue(ins["changeDir"].endswith("add-user-login"))

    def test_tasks_instructions_with_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            name = "add-user-login"
            new_change(root, name)
            self._complete_deps(root, name)
            ins = instructions(root, "tasks", name)
            self.assertEqual(ins["outputPath"], "tasks.md")
            self.assertIn("- [ ] 1.1", ins["template"])
            deps = {d["id"]: d for d in ins["dependencies"]}
            self.assertEqual(set(deps.keys()), {"specs", "design"})
            self.assertTrue(deps["specs"]["done"])
            self.assertEqual(deps["specs"]["path"], "specs/**/*.md")
            self.assertTrue(deps["design"]["done"])
            self.assertEqual(deps["design"]["path"], "design.md")

    def test_tasks_instructions_deps_not_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            name = "add-user-login"
            new_change(root, name)
            ins = instructions(root, "tasks", name)
            deps = {d["id"]: d for d in ins["dependencies"]}
            self.assertFalse(deps["specs"]["done"])
            self.assertFalse(deps["design"]["done"])

    def test_unknown_artifact_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            new_change(root, "add-user-login")
            with self.assertRaises(ValueError):
                instructions(root, "bogus", "add-user-login")

    def test_missing_change_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                instructions(Path(tmp), "proposal", "not-exist")


if __name__ == "__main__":
    unittest.main()
