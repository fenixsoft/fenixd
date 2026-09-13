"""Deliverables 声明形态 lint 与守卫目录型声明容错测试。

三层防御（remove-auto-run-cleanup 目录声明死锁事故 2026-09-03）：
  A. 守卫侧：file_exists_on_branch 接受 blob 或非空 tree（目录声明可对账）
  C. 晋升 lint：drafted→ready 时拦截目录/占位符声明（fail-open）
（B 为 skills/fenix-new 规则文本，非代码）
"""

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
        """合法声明放行：modify/new/reference 三种 kind 各一（无声明段与缺
        tasks.md 的 fail-open 语义见 test_deliverable_declaration_triage 的
        TestLintFailOpen，此处不重复）。"""
        (self.pr / "core").mkdir(parents=True, exist_ok=True)
        (self.pr / "core" / "data.py").write_text("x", encoding="utf-8")
        (self.pr / "third-party").mkdir(parents=True, exist_ok=True)
        (self.pr / "third-party" / "manifest.json").write_text("x",
                                                               encoding="utf-8")
        _mk_tasks_md(self.spec_dir,
                     "- path: core/data.py\n  kind: modify\n"
                     "- path: core/new_thing.py\n  kind: new\n"
                     "- path: third-party/manifest.json\n  kind: reference\n")
        self.assertEqual(lint_declared(self.spec_dir, self.pr), [])


class TestGitignoredDeclaration(unittest.TestCase):
    """规则 5：gitignored 路径不得声明为 modify/new（dist 守卫自伤防复发）。

    reference 不受限（.fenix/config.yaml、dist/index.html 审计留痕先例）；
    否定例外（!.fenix/keep.yaml）与非 git 目录 fail-open 均不拦。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.pr = Path(self.tmpdir) / "repo"
        self.pr.mkdir(parents=True, exist_ok=True)
        _git(self.pr, "init", "-q")
        (self.pr / ".gitignore").write_text(
            "dist/\n.fenix/*\n!.fenix/keep.yaml\n", encoding="utf-8")
        dist = self.pr / "dist"
        dist.mkdir(parents=True, exist_ok=True)
        (dist / "index.html").write_text("x", encoding="utf-8")
        fenix = self.pr / ".fenix"
        fenix.mkdir(parents=True, exist_ok=True)
        (fenix / "keep.yaml").write_text("x", encoding="utf-8")
        self.spec_dir = self.pr / "spec" / "changes" / "demo"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_gitignored_modify_or_new_is_violation(self):
        """modify/new 声明 gitignored 路径均被拦（同型规则，仅差 kind 参数）。"""
        cases = [
            # (kind, path, 处方是否给出 reference 出路提示)
            ("modify", "dist/index.html", True),
            ("new", ".fenix/secret.json", False),
        ]
        for kind, path, expect_reference_hint in cases:
            with self.subTest(kind=kind, path=path):
                _mk_tasks_md(self.spec_dir,
                             f"- path: {path}\n  kind: {kind}\n")
                violations = lint_declared(self.spec_dir, self.pr)
                self.assertEqual(len(violations), 1)
                self.assertIn("gitignore", violations[0])
                if expect_reference_hint:
                    self.assertIn("reference", violations[0])  # 处方给出出路

    def test_reference_gitignored_passes(self):
        # gitignored 运行时产物作 reference 是既有合法模式（审计留痕）
        _mk_tasks_md(self.spec_dir,
                     "- path: dist/index.html\n  kind: reference\n")
        self.assertEqual(lint_declared(self.spec_dir, self.pr), [])

    def test_negated_exception_passes(self):
        # .fenix/* 排除 + !.fenix/keep.yaml 否定 → 未被排除，不拦
        _mk_tasks_md(self.spec_dir, "- path: .fenix/keep.yaml\n  kind: modify\n")
        self.assertEqual(lint_declared(self.spec_dir, self.pr), [])

    def test_non_git_root_fails_open(self):
        # 非 git 目录（check-ignore 128）→ fail-open 放行，不阻塞晋升
        pr = Path(self.tmpdir) / "plain"
        pr.mkdir(parents=True, exist_ok=True)
        (pr / "file.py").write_text("x", encoding="utf-8")
        spec_dir = pr / "spec" / "changes" / "demo"
        _mk_tasks_md(spec_dir, "- path: file.py\n  kind: modify\n")
        self.assertEqual(lint_declared(spec_dir, pr), [])


class TestPromotionLintGate(unittest.TestCase):
    """drafted→ready 晋升拦截：违规保持 drafted 并写 error，修正后放行。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.pr = Path(self.tmpdir)
        from core.pm_engine import PMEngine
        self.logger = MagicMock()
        (self.pr / ".fenix").mkdir(parents=True, exist_ok=True)
        self.sm = StateMachine(self.pr / ".fenix" / "STATE.md", self.logger)
        # 评审门禁隔离（add-spec-review-gate 7.10）：本类验证的是 deliverable
        # lint 门禁（drafted→ready 拦截/放行），传 spec_review_mode: never 使
        # 晋升直通 ready——评审分流语义由 test_spec_review_gate.py 独立覆盖
        self.engine = PMEngine(self.sm, MagicMock(),
                               {"gates": {"spec_review_mode": "never"}},
                               self.pr, self.logger)
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
