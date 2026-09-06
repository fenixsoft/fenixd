"""add-deliverable-declaration-triage PR1：晋升 lint 存在性校验回归测试。

覆盖（spec.md「晋升 lint 存在性校验」四个 Scenario + fail-open）：
1. modify 路径不存在被拦（违规消息含路径与「必须存在」语义）
2. new 路径唯一 basename 命中判疑似笔误（消息给出疑似目标路径）
3. 多命中与零命中放行（不拦截，矛盾交由派发处方与守卫终审层兜底）
4. reference 路径不存在被拦（reference 语义即既有引用）
5. lint 自身故障 fail-open + basename 工具排除清单与确定性排序

PR2（spec.md「派发前声明现实处方注入」三个 Scenario）：
6. 疑似笔误候选随任务书注入（提示词含候选与 deliverable-dispute 登记约定）
7. 无声明段不注入（prompt 与现状逐字节一致）
8. 干跑异常不阻塞派发（快照为 None，派发照常）
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent_runner import AgentRunner
from core.deliverables import (
    _BASENAME_EXCLUDE_DIRS,
    extract_declared,
    extract_declared_entries,
    lint_declared,
    match_basename_in_tree,
)
from core.state_machine import StateMachine


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


class _FakeLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass

    def debug(self, *a, **k):
        pass


# ── PR2 派发前声明现实处方注入 ─────────────────────────────────────────────

class TestDeclaredRealityInjection(unittest.TestCase):
    """prompt_builder 声明现实快照注入：候选注入/无声明段跳过/干跑异常放行。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.project_root = self.tmpdir
        (self.project_root / ".fenix").mkdir(exist_ok=True)
        self.logger = _FakeLogger()
        self.sm = StateMachine(self.project_root / ".fenix" / "STATE.md",
                               self.logger)
        self.wm = mock.MagicMock()
        self.wm.get_legacy.return_value = None  # 无遗产：legacy 段零注入
        self.runner = AgentRunner.__new__(AgentRunner)
        self.runner.logger = self.logger
        self.runner.state_machine = self.sm
        self.runner.project_root = self.project_root
        self.runner.worktree_manager = self.wm

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def write_spec(self, name, tasks_text):
        spec_dir = self.project_root / "spec" / "changes" / name
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "tasks.md").write_text(tasks_text, encoding="utf-8")
        return spec_dir

    def write_tree(self, rel_path: str, content: str = "x") -> Path:
        p = self.project_root / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def build_prompt(self, spec_name="s1") -> str:
        return self.runner._prompt_builder._build_prompt(spec_name, "implementer")

    def test_suspected_typo_candidate_injected(self):
        """spec.md Scenario「疑似笔误候选随任务书注入」。"""
        self.write_tree("core/pm_engine/verification.py")
        self.write_spec("s1",
            "# Tasks\n\n## Deliverables\n\n```yaml\n"
            "- path: core/verification.py\n  kind: new\n```\n"
            "## 1. 分组\n\n- [ ] 1.1 新建 `core/verification.py`\n")
        prompt = self.build_prompt()
        self.assertIn("声明清单 × 仓库现实", prompt)
        self.assertIn("core/verification.py", prompt)
        self.assertIn("core/pm_engine/verification.py", prompt)
        self.assertIn("deliverable-dispute", prompt)
        self.assertIn("不得静默改变交付落点", prompt)

    def test_existing_modify_marked_as_target(self):
        """存在的 modify 路径标注为修改目标（快照存在性=true）。"""
        self.write_tree("core/data.py")
        self.write_spec("s1",
            "# Tasks\n\n## Deliverables\n\n```yaml\n"
            "- path: core/data.py\n  kind: modify\n```\n"
            "## 1. 分组\n\n- [ ] 1.1 扩展 `core/data.py`\n")
        prompt = self.build_prompt()
        self.assertIn("声明清单 × 仓库现实", prompt)
        self.assertIn("core/data.py", prompt)
        self.assertIn("主树存在", prompt)
        self.assertNotIn("疑似声明笔误", prompt)

    def test_no_declared_section_no_injection(self):
        """spec.md Scenario「无声明段不注入」：prompt 与现状逐字节一致。"""
        self.write_spec("s1", "# Tasks\n\n- [ ] 1.1 写 `core/foo.py`\n")
        prompt = self.build_prompt()
        # 注入段的独有标题/文案不得出现（模板自带 deliverable-dispute 约定不计）
        self.assertNotIn("声明清单 × 仓库现实", prompt)
        self.assertNotIn("疑似声明笔误", prompt)
        self.assertNotIn("不得静默改变交付落点", prompt)

    def test_dry_run_exception_does_not_block_dispatch(self):
        """spec.md Scenario「干跑异常不阻塞派发」：spec 目录缺失 → 快照 None。"""
        # ghost spec 目录不存在：_build_prompt 不抛、无注入，派发照常
        prompt = self.runner._prompt_builder._build_prompt("ghost", "implementer")
        self.assertNotIn("声明清单 × 仓库现实", prompt)

    def test_snapshot_read_failure_returns_none(self):
        """spec 目录读取失败（tasks.md 为目录）→ 快照 None，注入跳过。"""
        spec_dir = self.project_root / "spec" / "changes" / "s1"
        (spec_dir / "tasks.md").mkdir(parents=True, exist_ok=True)
        self.assertIsNone(
            self.runner._prompt_builder._declared_reality_snapshot("s1"))
        prompt = self.build_prompt()
        self.assertNotIn("声明清单 × 仓库现实", prompt)


# ── extract_declared_entries（处方快照条目级解析） ─────────────────────────

class TestExtractDeclaredEntries(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.spec_dir = self.tmpdir / "spec"
        self.spec_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def write_tasks(self, text):
        (self.spec_dir / "tasks.md").write_text(text, encoding="utf-8")

    def test_entries_preserve_kind_per_item(self):
        """条目级 path+kind 保序返回；reference 条目不丢失。"""
        self.write_tasks(
            "# Tasks\n\n## Deliverables\n\n```yaml\n"
            "- path: core/data.py\n  kind: modify\n"
            "- path: core/new_mod.py\n  kind: new\n"
            "- path: .fenix/config.yaml\n  kind: reference\n```\n"
        )
        entries = extract_declared_entries(self.spec_dir)
        self.assertEqual(entries, [
            {"path": "core/data.py", "kind": "modify"},
            {"path": "core/new_mod.py", "kind": "new"},
            {"path": ".fenix/config.yaml", "kind": "reference"},
        ])

    def test_extract_declared_consistent_with_entries(self):
        """extract_declared 归类与 entries 解析一致（复用同源）。"""
        self.write_tasks(
            "# Tasks\n\n## Deliverables\n\n```yaml\n"
            "- path: core/data.py\n  kind: modify\n"
            "- path: .fenix/config.yaml\n  kind: reference\n```\n"
        )
        entries = extract_declared_entries(self.spec_dir)
        typed = extract_declared(self.spec_dir)
        self.assertEqual(
            [e["path"] for e in entries if e["kind"] in ("new", "modify")],
            typed["deliverables"])
        self.assertEqual(
            [e["path"] for e in entries if e["kind"] == "reference"],
            typed["references"])

    def test_absent_section_returns_none(self):
        self.write_tasks("# Tasks\n\n- [ ] 1.1 写 `core/foo.py`\n")
        self.assertIsNone(extract_declared_entries(self.spec_dir))


if __name__ == "__main__":
    unittest.main(verbosity=2)