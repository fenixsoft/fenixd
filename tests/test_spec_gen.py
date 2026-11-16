"""
Unit tests for core.spec_gen — fenix 原生 SPEC 生成器。

Run with: python3 -m pytest tests/test_spec_gen.py -q
"""

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.spec_gen import instructions, new_change, status

# bin/ 下的独立脚本（fenix_archive.py）以模块方式导入以复用归档逻辑
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
from fenix_archive import archive_change


class TestNewChange(unittest.TestCase):
    """new_change：创建 / 同名拒绝 / kebab-case 校验。"""

    def test_create_new_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = new_change(root, "add-user-login")
            self.assertTrue(result.is_dir())
            metadata = (root / "spec" / "changes" / "add-user-login" / ".spec.yaml").read_text(
                encoding="utf-8"
            )
            self.assertIn("schema: spec-driven", metadata)
            self.assertIn("created:", metadata)
            self.assertEqual(result, root / "spec" / "changes" / "add-user-login")

    def test_duplicate_change_rejected_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            new_change(root, "add-user-login")
            existing = root / "spec" / "changes" / "add-user-login" / "proposal.md"
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
            self.assertFalse((root / "spec" / "changes" / "Add User Login").exists())

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


class TestNewChangeSchemaPrecheck(unittest.TestCase):
    """A1r：new 写盘前 load_schema 前置校验（制品缺件干净失败）。

    v0.1.1 Windows 部署实录：codeload tarball 不含 schemas/，new 落盘
    半成品目录后 status/instructions 才以裸 FileNotFoundError 暴露。
    """

    def _missing_schema_dir(self, tmp):
        # 指向不存在的 vendored schema 目录（制品缺件形态）
        return Path(tmp) / "vendored-missing" / "schemas" / "spec-driven"

    def test_missing_schema_raises_value_error_with_repair_hint(self):
        import unittest.mock as mock

        from core import spec_gen

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(
                    spec_gen, "SCHEMA_DIR", self._missing_schema_dir(tmp)):
                with self.assertRaises(ValueError) as ctx:
                    new_change(Path(tmp) / "proj", "add-user-login")
        msg = str(ctx.exception)
        self.assertIn("制品缺件", msg)
        self.assertIn("install.md §3A", msg)
        self.assertIn("v0.1.2", msg)

    def test_missing_schema_zero_disk_writes(self):
        # 干净失败：ValueError 前零落盘，无半成品 spec/changes 目录残留
        import unittest.mock as mock

        from core import spec_gen

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "proj"
            with mock.patch.object(
                    spec_gen, "SCHEMA_DIR", self._missing_schema_dir(tmp)):
                with self.assertRaises(ValueError):
                    new_change(root, "add-user-login")
            self.assertFalse((root / "spec").exists())

    def test_cli_new_missing_schema_exit_nonzero(self):
        # CLI 面：bin/fenix_spec.py new 捕获 ValueError → JSON error + exit 1
        import contextlib
        import io
        import json
        import sys
        import unittest.mock as mock

        from core import spec_gen

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
        import fenix_spec

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "spec").mkdir()
            buf = io.StringIO()
            with mock.patch.object(
                    spec_gen, "SCHEMA_DIR", self._missing_schema_dir(tmp)), \
                mock.patch.object(
                    sys, "argv",
                    ["fenix_spec.py", "new", "add-user-login",
                     "--project", str(root)]), \
                contextlib.redirect_stdout(buf):
                with self.assertRaises(SystemExit) as ctx:
                    fenix_spec.main()
            self.assertEqual(ctx.exception.code, 1)
            payload = json.loads(buf.getvalue())
            self.assertFalse(payload["ok"])
            self.assertIn("制品缺件", payload["error"])
            self.assertIn("§3A", payload["error"])
            # 零落盘
            self.assertFalse(
                (root / "spec" / "changes" / "add-user-login").exists())


class TestStatus(unittest.TestCase):
    """status：初始态 / 全完成 / 与 spec status --json 同构。"""

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
        change_dir = root / "spec" / "changes" / name
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


class TestArchive(unittest.TestCase):
    """archive_change：移动成功 / 日期冲突报错不覆盖 / 不存在报错。"""

    def test_archive_moves_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            name = "add-user-login"
            change_dir = new_change(root, name)
            (change_dir / "tasks.md").write_text("# T", encoding="utf-8")

            result = archive_change(root, name)

            self.assertTrue(result["from"].endswith(f"spec/changes/{name}"))
            expected_to = root / "spec" / "archive" / f"{date.today().isoformat()}-{name}"
            self.assertEqual(result["to"], str(expected_to))
            self.assertTrue(expected_to.is_dir())
            self.assertFalse(change_dir.exists())
            self.assertTrue((expected_to / "tasks.md").exists())
            self.assertTrue((expected_to / ".spec.yaml").exists())

    def test_archive_date_conflict_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            name = "add-user-login"
            change_dir = new_change(root, name)
            sentinel = change_dir / "sentinel.txt"
            sentinel.write_text("keep", encoding="utf-8")

            # 预置同名目标（模拟同一天重复归档）
            target = root / "spec" / "archive" / f"{date.today().isoformat()}-{name}"
            target.mkdir(parents=True)
            (target / "existing.txt").write_text("old", encoding="utf-8")

            with self.assertRaises(ValueError):
                archive_change(root, name)

            # 原目录未被移动或覆盖
            self.assertTrue(change_dir.is_dir())
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
            self.assertTrue((target / "existing.txt").exists())

    def test_archive_missing_change_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ValueError):
                archive_change(root, "not-exist")


if __name__ == "__main__":
    unittest.main()
