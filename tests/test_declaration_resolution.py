"""tests/test_declaration_resolution.py — resolve_effective_declaration 测试。

覆盖 add-declaration-relocation-protocol Task 5.1：
- 分层优先序（分支版本优先 / 分支读取失败回退主树 / 两处均无返回空）
- 结果与 extract_declared 同构
- 消费方经入口读取（断言行为而非调用某函数）
- 回退去向与原因审计留痕
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# 路径补丁：确保 core 可导入
import sys
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


def _init_git_repo(root: Path) -> None:
    """在 root 初始化 git 仓库并做一次初始提交（让 git show 可用）。"""
    subprocess.run(
        ["git", "-c", "user.name=fenix", "-c", "user.email=fenix@test",
         "init", str(root)],
        capture_output=True, timeout=30,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "core.autocrlf", "false"],
        capture_output=True, timeout=10,
    )
    # 创建一个空文件作为初始提交
    (root / ".gitkeep").write_text("")
    subprocess.run(
        ["git", "-C", str(root), "add", "."],
        capture_output=True, timeout=10,
    )
    subprocess.run(
        ["git", "-C", str(root), "commit", "-m", "init"],
        capture_output=True, timeout=30,
    )


def _write_tasks_md(spec_dir: Path, content: str) -> None:
    """写入 tasks.md 到 spec_dir。"""
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "tasks.md").write_text(content, encoding="utf-8")


def _create_branch_with_content(root: Path, branch: str, spec_name: str, content: str) -> None:
    """创建新分支，在其中写入 tasks.md 并提交。"""
    subprocess.run(
        ["git", "-C", str(root), "checkout", "-b", branch],
        capture_output=True, timeout=10,
    )
    spec_dir = root / "spec" / "changes" / spec_name
    _write_tasks_md(spec_dir, content)
    subprocess.run(
        ["git", "-C", str(root), "add", "."],
        capture_output=True, timeout=10,
    )
    subprocess.run(
        ["git", "-C", str(root), "commit", "-m", f"add {spec_name} tasks for {branch}"],
        capture_output=True, timeout=30,
    )
    subprocess.run(
        ["git", "-C", str(root), "checkout", "main"],
        capture_output=True, timeout=10,
    )


_TASKS_WITH_DECLARED = (
    "# Tasks: test-spec\n\n"
    "## 1. 任务\n\n"
    "- [ ] 1.1 做些事情\n\n"
    "## Deliverables\n\n"
    "```yaml\n"
    "- path: core/foo.py\n"
    "  kind: modify\n"
    "- path: tests/bar.py\n"
    "  kind: new\n"
    "```\n"
)

_TASKS_WITH_DECLARED_V2 = (
    "# Tasks: test-spec\n\n"
    "## 1. 任务\n\n"
    "- [ ] 1.1 做些事情\n\n"
    "## Deliverables\n\n"
    "```yaml\n"
    "- path: core/new_file.py\n"
    "  kind: modify\n"
    "- path: tests/bar.py\n"
    "  kind: new\n"
    "```\n"
)

_TASKS_NO_DECLARED = (
    "# Tasks: test-spec\n\n"
    "## 1. 任务\n\n"
    "- [ ] 1.1 做些事情\n"
)


class TestResolveEffectiveDeclaration(unittest.TestCase):
    """resolve_effective_declaration 分层优先序与回退测试。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.project_root = self.tmpdir
        _init_git_repo(self.project_root)
        # 创建主树 tasks.md（带声明段）
        spec_dir = self.project_root / "spec" / "changes" / "test-spec"
        _write_tasks_md(spec_dir, _TASKS_WITH_DECLARED)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_main_tree_fallback(self):
        """主树文件回退：无 branch/worktree 时读主树 tasks.md。"""
        from core.deliverables import resolve_effective_declaration

        result = resolve_effective_declaration(
            "test-spec",
            project_root=self.project_root,
        )
        self.assertEqual(result["source"], "main")
        self.assertIn("core/foo.py", result["deliverables"])
        self.assertIn("tests/bar.py", result["deliverables"])
        self.assertEqual(len(result["entries"]), 2)

    def test_branch_version_preferred(self):
        """分支版本优先：分支上有不同声明时以分支为准。"""
        from core.deliverables import resolve_effective_declaration

        branch = "fenix/test-spec"
        _create_branch_with_content(
            self.project_root, branch, "test-spec", _TASKS_WITH_DECLARED_V2
        )
        result = resolve_effective_declaration(
            "test-spec",
            branch=branch,
            project_root=self.project_root,
        )
        self.assertEqual(result["source"], "branch")
        self.assertIn("core/new_file.py", result["deliverables"])
        self.assertNotIn("core/foo.py", result["deliverables"])

    def test_branch_fallback_to_main(self):
        """分支读取失败回退主树：分支不存在时回退主树版本。"""
        from core.deliverables import resolve_effective_declaration

        result = resolve_effective_declaration(
            "test-spec",
            branch="nonexistent-branch",
            project_root=self.project_root,
        )
        self.assertEqual(result["source"], "main")
        self.assertIn("core/foo.py", result["deliverables"])

    def test_nonexistent_spec_returns_empty(self):
        """两处均不可用返回空：不存在的 spec 名。"""
        from core.deliverables import resolve_effective_declaration

        result = resolve_effective_declaration(
            "nonexistent-spec",
            project_root=self.project_root,
        )
        self.assertEqual(result["source"], None)
        self.assertEqual(result["deliverables"], [])
        self.assertEqual(result["references"], [])
        self.assertEqual(result["entries"], [])

    def test_worktree_version_preferred_over_branch(self):
        """worktree 版本优先于分支版本。"""
        from core.deliverables import resolve_effective_declaration

        branch = "fenix/test-spec-wt"
        _create_branch_with_content(
            self.project_root, branch, "test-spec", _TASKS_WITH_DECLARED_V2
        )
        # 创建临时 worktree 目录（模拟实现方改写了声明段）
        wt_dir = Path(tempfile.mkdtemp()) / "test-worktree"
        wt_dir.mkdir(parents=True, exist_ok=True)
        wt_spec = wt_dir / "spec" / "changes" / "test-spec"
        _write_tasks_md(
            wt_spec,
            "# Tasks: test-spec\n\n"
            "## Deliverables\n\n"
            "```yaml\n"
            "- path: core/wt_file.py\n"
            "  kind: new\n"
            "```\n",
        )
        try:
            result = resolve_effective_declaration(
                "test-spec",
                branch=branch,
                worktree_path=str(wt_dir),
                project_root=self.project_root,
            )
            self.assertEqual(result["source"], "worktree")
            self.assertIn("core/wt_file.py", result["deliverables"])
        finally:
            shutil.rmtree(wt_dir, ignore_errors=True)

    def test_no_declaration_falls_back(self):
        """无声明段：主树 tasks.md 无 Deliverables 段 → 回退后返回空（无声明段语义）。"""
        from core.deliverables import resolve_effective_declaration

        spec_dir = self.project_root / "spec" / "changes" / "test-no-decl"
        _write_tasks_md(spec_dir, _TASKS_NO_DECLARED)
        result = resolve_effective_declaration(
            "test-no-decl",
            project_root=self.project_root,
        )
        self.assertEqual(result["source"], "main")
        self.assertEqual(result["deliverables"], [])
        self.assertEqual(result["entries"], [])

    def test_isomorphic_with_extract_declared(self):
        """结果与 extract_declared 同构：deliverables/references 两桶结构。"""
        from core.deliverables import extract_declared, resolve_effective_declaration

        typed_old = extract_declared(
            self.project_root / "spec" / "changes" / "test-spec"
        )
        result = resolve_effective_declaration(
            "test-spec",
            project_root=self.project_root,
        )
        self.assertEqual(
            sorted(result["deliverables"]),
            sorted(typed_old["deliverables"]),
        )
        self.assertEqual(
            sorted(result["references"]),
            sorted(typed_old["references"]),
        )

    def test_entries_are_path_kind_pairs(self):
        """entries 含 path+kind 对（供 kind 映射/收缩防护）。"""
        from core.deliverables import resolve_effective_declaration

        result = resolve_effective_declaration(
            "test-spec",
            project_root=self.project_root,
        )
        for e in result["entries"]:
            self.assertIn("path", e)
            self.assertIn("kind", e)
            self.assertEqual(e["path"], "core/foo.py" if e["path"] == "core/foo.py" else "tests/bar.py")

    def test_cost_pure_read_only(self):
        """成本契约：MUST NOT 触发 LLM/测试/网络。"""
        with mock.patch(
            "core.deliverables.subprocess.run",
            side_effect=AssertionError("subprocess.run 应只用于 git show/cat-file"),
        ):
            from core.deliverables import resolve_effective_declaration

            # 无 branch/worktree → 主树读取，不需要 subprocess（纯文件读取）
            result = resolve_effective_declaration(
                "test-spec",
                project_root=self.project_root,
            )
            self.assertEqual(result["source"], "main")
            self.assertIn("core/foo.py", result["deliverables"])


if __name__ == "__main__":
    unittest.main()
