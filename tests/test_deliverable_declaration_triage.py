"""add-deliverable-declaration-triage PR1：晋升 lint 存在性校验回归测试。

覆盖（spec.md「晋升 lint 存在性校验」四个 Scenario + fail-open）：
1. modify 路径不存在被拦（违规消息含路径与「必须存在」语义）
2. new 路径唯一 basename 命中判疑似笔误（消息给出疑似目标路径）
3. 多命中与零命中放行（不拦截，矛盾交由派发处方与守卫终审层兜底）
4. reference 路径不存在被拦（reference 语义即既有引用）
5. lint 自身故障 fail-open + basename 工具排除清单与确定性排序
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.deliverables import (
    _BASENAME_EXCLUDE_DIRS,
    lint_declared,
    match_basename_in_tree,
)


def _mk_tasks_md(spec_dir: Path, yaml_block: str) -> None:
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "tasks.md").write_text(
        "# Tasks\n\n## Deliverables\n\n```yaml\n"
        + yaml_block + "\n```\n\n## 1. x\n\n- [ ] 1.1 do it\n",
        encoding="utf-8",
    )


class _LintFixture(unittest.TestCase):
    """lint_declared 纯函数夹具：临时主树 + 临时 spec 目录。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.pr = Path(self.tmpdir)
        self.spec_dir = self.pr / "spec" / "changes" / "demo"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def write_tree(self, rel_path: str, content: str = "x") -> Path:
        p = self.pr / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p


class TestLintModifyReferenceExistence(_LintFixture):
    """规则 3：modify/reference 路径在主树必须存在。"""

    def test_modify_missing_blocked(self):
        """spec.md Scenario「modify 路径不存在被拦」。"""
        _mk_tasks_md(self.spec_dir,
                     "- path: core/verification.py\n  kind: modify\n")
        violations = lint_declared(self.spec_dir, self.pr)
        self.assertEqual(len(violations), 1)
        self.assertIn("core/verification.py", violations[0])
        self.assertIn("必须存在", violations[0])

    def test_reference_missing_blocked(self):
        """spec.md Scenario「reference 路径不存在被拦」。"""
        _mk_tasks_md(self.spec_dir,
                     "- path: third-party/manifest.json\n  kind: reference\n")
        violations = lint_declared(self.spec_dir, self.pr)
        self.assertEqual(len(violations), 1)
        self.assertIn("third-party/manifest.json", violations[0])
        self.assertIn("必须存在", violations[0])

    def test_modify_reference_existing_pass(self):
        """modify/reference 指向既有文件 → 放行。"""
        self.write_tree("core/data.py")
        self.write_tree("third-party/manifest.json")
        _mk_tasks_md(self.spec_dir,
                     "- path: core/data.py\n  kind: modify\n"
                     "- path: third-party/manifest.json\n  kind: reference\n")
        self.assertEqual(lint_declared(self.spec_dir, self.pr), [])

    def test_mixed_entries_only_missing_reported(self):
        """多条目混合：仅缺者被报，存在者不误报。"""
        self.write_tree("core/true.py")
        _mk_tasks_md(self.spec_dir,
                     "- path: core/true.py\n  kind: modify\n"
                     "- path: core/ghost.py\n  kind: modify\n")
        violations = lint_declared(self.spec_dir, self.pr)
        self.assertEqual(len(violations), 1)
        self.assertIn("core/ghost.py", violations[0])
        self.assertNotIn("core/true.py", violations[0])


class TestLintNewBasenameTriage(_LintFixture):
    """规则 4：new 路径唯一 basename 命中判疑似笔误；零/多命中放行。"""

    def test_new_unique_basename_hit_blocked(self):
        """spec.md Scenario「new 路径唯一 basename 命中判疑似笔误」。"""
        self.write_tree("core/pm_engine/verification.py")
        _mk_tasks_md(self.spec_dir,
                     "- path: core/verification.py\n  kind: new\n")
        violations = lint_declared(self.spec_dir, self.pr)
        self.assertEqual(len(violations), 1)
        self.assertIn("core/verification.py", violations[0])
        self.assertIn("疑似笔误", violations[0])
        self.assertIn("core/pm_engine/verification.py", violations[0])

    def test_new_zero_hit_pass(self):
        """零命中：无同名 basename 文件 → 放行（交由后续层兜底）。"""
        self.write_tree("core/pm_engine/verification.py")
        _mk_tasks_md(self.spec_dir,
                     "- path: core/brand_new_module.py\n  kind: new\n")
        self.assertEqual(lint_declared(self.spec_dir, self.pr), [])

    def test_new_multiple_hits_pass(self):
        """多命中：basename 在仓库命中多个文件 → 放行（语义矛盾交 LLM 层）。"""
        self.write_tree("core/a/verification.py")
        self.write_tree("core/b/verification.py")
        _mk_tasks_md(self.spec_dir,
                     "- path: core/verification.py\n  kind: new\n")
        self.assertEqual(lint_declared(self.spec_dir, self.pr), [])

    def test_new_existing_path_pass(self):
        """new 路径在主树已存在（与规则 3 同检）→ 不拦（design Non-Goal）。"""
        self.write_tree("core/new_mod.py")
        _mk_tasks_md(self.spec_dir,
                     "- path: core/new_mod.py\n  kind: new\n")
        self.assertEqual(lint_declared(self.spec_dir, self.pr), [])


class TestLintFailOpen(_LintFixture):
    """fail-open 保持：lint 自身故障放行，无声明段行为不变。"""

    def test_unreadable_tasks_md_fails_open(self):
        """tasks.md 为目录（read_text 抛 OSError）→ 放行晋升。"""
        tasks = self.spec_dir / "tasks.md"
        tasks.mkdir(parents=True, exist_ok=True)
        self.assertEqual(lint_declared(self.spec_dir, self.pr), [])

    def test_no_deliverables_section_passes(self):
        """无声明段（存量 spec）→ 不拦（start is None 早退路径未触碰）。"""
        self.spec_dir.mkdir(parents=True, exist_ok=True)
        (self.spec_dir / "tasks.md").write_text(
            "# Tasks\n\n## 1. x\n\n- [ ] 1.1 do it\n", encoding="utf-8")
        self.assertEqual(lint_declared(self.spec_dir, self.pr), [])

    def test_missing_tasks_md_passes(self):
        self.assertEqual(
            lint_declared(self.pr / "spec/changes/ghost", self.pr), [])


class TestMatchBasenameInTree(_LintFixture):
    """1.1 工具函数：basename 精确匹配 + 排除清单 + 确定性排序。"""

    def test_basename_exact_match(self):
        self.write_tree("core/pm_engine/verification.py")
        self.write_tree("tests/test_verification.py")
        hits = match_basename_in_tree(self.pr, "core/verification.py")
        self.assertEqual(hits, ["core/pm_engine/verification.py"])

    def test_exclude_dirs_skipped(self):
        """排除清单目录（.git/node_modules/dist/.fenix/__pycache__）不参与命中。"""
        for d in _BASENAME_EXCLUDE_DIRS:
            self.write_tree(f"{d}/verification.py")
        self.write_tree("core/pm_engine/verification.py")
        hits = match_basename_in_tree(self.pr, "core/verification.py")
        self.assertEqual(hits, ["core/pm_engine/verification.py"])

    def test_multiple_hits_deterministic_order(self):
        self.write_tree("core/z/verification.py")
        self.write_tree("core/a/verification.py")
        hits = match_basename_in_tree(self.pr, "core/verification.py")
        self.assertEqual(hits,
                         ["core/a/verification.py", "core/z/verification.py"])

    def test_empty_path_no_hit(self):
        self.assertEqual(match_basename_in_tree(self.pr, ""), [])

    def test_nonexistent_root_returns_empty(self):
        self.assertEqual(
            match_basename_in_tree("/nonexistent_xyz_123", "verification.py"),
            [])


if __name__ == "__main__":
    unittest.main(verbosity=2)