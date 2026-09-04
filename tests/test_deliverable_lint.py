"""Deliverables 声明形态 lint 与守卫目录型声明容错测试。

三层防御（remove-auto-run-cleanup 目录声明死锁事故 2026-09-03）：
  A. 守卫侧：file_exists_on_branch 接受 blob 或非空 tree（目录声明可对账）
  C. 晋升 lint：drafted→ready 时拦截目录/占位符声明（fail-open）
（B 为 skills/fenix-new 规则文本，非代码）
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.deliverables import lint_declared
from core.state_machine import StateMachine
from core.worktree_manager import WorktreeManager


def _git(root: Path, *args, check=True):
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result


def _mk_tasks_md(spec_dir: Path, yaml_block: str) -> None:
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "tasks.md").write_text(
        "# Tasks\n\n## Deliverables\n\n```yaml\n"
        + yaml_block + "\n```\n\n## 1. x\n\n- [ ] 1.1 do it\n",
        encoding="utf-8",
    )


class TestLintDeclared(unittest.TestCase):
    """lint_declared：声明形态机械校验（零误拦取向）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.pr = Path(self.tmpdir)
        self.spec_dir = self.pr / "spec" / "changes" / "demo"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_directory_modify_declaration_is_violation(self):
        _mk_tasks_md(self.spec_dir,
                     "- path: core/dashboard/static/dist\n  kind: modify\n")
        dist = self.pr / "core/dashboard/static/dist"
        dist.mkdir(parents=True, exist_ok=True)
        (dist / "index.html").write_text("x", encoding="utf-8")
        violations = lint_declared(self.spec_dir, self.pr)
        self.assertEqual(len(violations), 1)
        self.assertIn("目录", violations[0])
        self.assertIn("dist/index.html", violations[0])  # 处方含锚点示例

    def test_placeholder_declaration_is_violation(self):
        _mk_tasks_md(self.spec_dir,
                     "- path: .fenix/admin_disposition-<run_id>.json\n"
                     "  kind: reference\n")
        violations = lint_declared(self.spec_dir, self.pr)
        self.assertEqual(len(violations), 1)
        self.assertIn("占位符", violations[0])

    def test_clean_file_declarations_pass(self):
        (self.pr / "core").mkdir(parents=True, exist_ok=True)
        (self.pr / "core" / "data.py").write_text("x", encoding="utf-8")
        _mk_tasks_md(self.spec_dir,
                     "- path: core/data.py\n  kind: modify\n"
                     "- path: core/new_thing.py\n  kind: new\n")
        self.assertEqual(lint_declared(self.spec_dir, self.pr), [])

    def test_no_deliverables_section_passes(self):
        spec_dir = self.spec_dir
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "tasks.md").write_text(
            "# Tasks\n\n## 1. x\n\n- [ ] 1.1 do it\n", encoding="utf-8")
        self.assertEqual(lint_declared(spec_dir, self.pr), [])

    def test_missing_tasks_md_passes(self):
        self.assertEqual(
            lint_declared(self.pr / "spec/changes/ghost", self.pr), [])


class TestPromotionLintGate(unittest.TestCase):
    """drafted→ready 晋升拦截：违规保持 drafted 并写 error，修正后放行。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.pr = Path(self.tmpdir)
        from core.pm_engine import PMEngine
        self.logger = MagicMock()
        (self.pr / ".fenix").mkdir(parents=True, exist_ok=True)
        self.sm = StateMachine(self.pr / ".fenix" / "STATE.md", self.logger)
        self.engine = PMEngine(self.sm, MagicMock(), {}, self.pr, self.logger)
        self.engine._on_spec_ready = MagicMock()
        self.spec_dir = self.pr / "spec" / "changes" / "demo"
        self.sm.add_spec("demo", {"priority": 5})

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_violation_blocks_promotion_with_error(self):
        dist = self.pr / "core/dashboard/static/dist"
        dist.mkdir(parents=True, exist_ok=True)
        (dist / "index.html").write_text("x", encoding="utf-8")
        _mk_tasks_md(self.spec_dir,
                     "- path: core/dashboard/static/dist\n  kind: modify\n")

        self.engine._on_spec_drafted("demo")

        entry = self.sm.read_one("demo")
        self.assertEqual(entry["status"], "drafted")  # 不晋升
        self.assertIn("Deliverables 声明 lint 未通过", entry["error"])
        self.engine._on_spec_ready.assert_not_called()

    def test_clean_declaration_promotes(self):
        (self.pr / "core").mkdir(parents=True, exist_ok=True)
        (self.pr / "core" / "data.py").write_text("x", encoding="utf-8")
        _mk_tasks_md(self.spec_dir, "- path: core/data.py\n  kind: modify\n")

        self.engine._on_spec_drafted("demo")

        entry = self.sm.read_one("demo")
        self.assertEqual(entry["status"], "ready")
        self.engine._on_spec_ready.assert_called_once_with("demo")

    def test_lint_crash_fails_open(self):
        # lint 异常（如 tasks.md 不可读）→ 放行晋升，不阻塞流水线
        _mk_tasks_md(self.spec_dir, "- path: core/data.py\n  kind: modify\n")
        with unittest.mock.patch(
                "core.deliverables.lint_declared",
                side_effect=RuntimeError("boom")):
            self.engine._on_spec_drafted("demo")
        entry = self.sm.read_one("demo")
        self.assertEqual(entry["status"], "ready")


class TestFileExistsOnBranchAcceptsTree(unittest.TestCase):
    """A 层：守卫存在性检查接受 blob 或非空 tree（git 不追踪空目录）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir) / "repo"
        self.root.mkdir(parents=True, exist_ok=True)
        _git(self.root, "init", "-q")
        _git(self.root, "config", "user.email", "test@fenix.local")
        _git(self.root, "config", "user.name", "Fenix Test")
        _git(self.root, "config", "commit.gpgsign", "false")
        (self.root / "file.py").write_text("BASE\n", encoding="utf-8")
        dist = self.root / "core" / "dashboard" / "static" / "dist"
        dist.mkdir(parents=True, exist_ok=True)
        (dist / "index.html").write_text("<html></html>\n", encoding="utf-8")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "base")
        self.branch = _git(self.root, "rev-parse", "--abbrev-ref", "HEAD") \
            .stdout.strip()
        base = self.root / ".claude" / "worktrees"
        base.mkdir(parents=True, exist_ok=True)
        self.wm = WorktreeManager(base, self.root, MagicMock())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_file_blob_exists(self):
        self.assertTrue(self.wm.file_exists_on_branch(self.branch, "file.py"))

    def test_directory_tree_exists(self):
        # 目录声明（如 dist/）在分支上存在 → 算落地（本次死锁事故的修复点）
        self.assertTrue(self.wm.file_exists_on_branch(
            self.branch, "core/dashboard/static/dist"))
        self.assertTrue(self.wm.file_exists_on_branch(self.branch, "core"))

    def test_missing_path_rejected(self):
        self.assertFalse(self.wm.file_exists_on_branch(
            self.branch, "core/dashboard/static/dist/nope.js"))
        self.assertFalse(self.wm.file_exists_on_branch(
            self.branch, "ghost/path.py"))
        self.assertFalse(self.wm.file_exists_on_branch("", "file.py"))


if __name__ == "__main__":
    unittest.main()
