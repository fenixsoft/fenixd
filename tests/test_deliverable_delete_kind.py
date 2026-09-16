"""add-deliverable-delete-kind 单元测试：声明扩展、守卫反判、防洗白三处。

覆盖 tasks.md 7.1-7.4：

7.1 lint_declared 对 delete 的四类拒绝与合法 delete 放行；extract_declared
    归类（delete 进 deliverables、非法 kind 忽略、同路径保留首见）。
7.2 守卫反判——delete 条目在分支 HEAD 仍存在 → undeleted；已不存在 → 无违规；
    与 missing 混合时逐条返回且 kind/violation 一一对应。
7.3 防洗白三处——classify_unsatisfiable / soften_* 不改写 delete；
    守卫预分类不软化 delete；judge 对 delete 给出 reference 时被机械改写
    为 unclear。
7.4 派发前处方对 delete 的两种形态（主树存在 → 删除目标确认；
    主树不存在 → 无可删 + 候选）。
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.deliverables import (
    classify_unsatisfiable,
    extract_declared,
    extract_declared_entries,
    lint_declared,
    soften_declared_kind,
    soften_unsatisfiable_declarations,
)
from core.agent_runner import AgentRunner, AgentRunResult
from core.pm_engine import PMEngine
from core.state_machine import StateMachine


# ── helpers ──────────────────────────────────────────────────────────────────

def _mk_tasks_md(spec_dir: Path, yaml_block: str) -> None:
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "tasks.md").write_text(
        "# Tasks\n\n## Deliverables\n\n```yaml\n"
        + yaml_block + "\n```\n\n## 1. x\n\n- [ ] 1.1 do it\n",
        encoding="utf-8",
    )


# ── 7.1 lint_declared 对 delete 的拒绝与放行 ──────────────────────────────────

class TestLintDeleteRejects(unittest.TestCase):
    """7.1 lint_declared：delete 四类拒绝（gitignored / 不存在 / 目录 / 仓库外）+ 合法放行。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.pr = Path(self.tmpdir)
        self.spec_dir = self.pr / "spec" / "changes" / "demo"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_file(self, rel: str, content: str = "x") -> Path:
        p = self.pr / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    # ── gitignored（规则 7）──

    def test_gitignored_delete_blocked(self):
        """gitignored 路径声明 delete → 违规（处方明示运行时文件删除不进交付物）。"""
        git_pr = self.pr / "repo"
        git_pr.mkdir(parents=True)
        import subprocess
        subprocess.run(["git", "-C", str(git_pr), "init", "-q"], check=True)
        (git_pr / ".gitignore").write_text("dist/\n", encoding="utf-8")
        dist = git_pr / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("x", encoding="utf-8")
        _mk_tasks_md(git_pr / "spec" / "changes" / "demo",
                     "- path: dist/index.html\n  kind: delete\n")
        violations = lint_declared(git_pr / "spec" / "changes" / "demo", git_pr)
        self.assertEqual(len(violations), 1)
        self.assertIn("gitignore", violations[0])
        self.assertIn("delete", violations[0])
        self.assertIn("不进 Deliverables 段", violations[0])

    # ── 主树不存在（规则 8）──

    def test_nonexistent_delete_blocked(self):
        """主树不存在 → 无可删，违规。"""
        _mk_tasks_md(self.spec_dir,
                     "- path: core/ghost.py\n  kind: delete\n")
        violations = lint_declared(self.spec_dir, self.pr)
        self.assertEqual(len(violations), 1)
        self.assertIn("在主树不存在", violations[0])
        self.assertIn("无可删", violations[0])

    # ── 目录（规则 9）──

    def test_directory_delete_blocked(self):
        """目录声明 delete → 违规（删除语义针对文件）。"""
        d = self.pr / "core" / "dist"
        d.mkdir(parents=True)
        (d / "index.html").write_text("x", encoding="utf-8")
        _mk_tasks_md(self.spec_dir,
                     "- path: core/dist\n  kind: delete\n")
        violations = lint_declared(self.spec_dir, self.pr)
        self.assertEqual(len(violations), 1)
        self.assertIn("目录", violations[0])

    # ── 仓库外（规则 10）──

    def test_outside_root_delete_blocked(self):
        """仓库外路径声明 delete → 违规。"""
        _mk_tasks_md(self.spec_dir,
                     "- path: ../outside.py\n  kind: delete\n")
        violations = lint_declared(self.spec_dir, self.pr)
        self.assertTrue(any("仓库外" in v and "delete" in v for v in violations))

    # ── 合法 delete 放行 ──

    def test_valid_delete_passes(self):
        """已入库文件声明 delete → 放行。"""
        self._write_file("core/obsolete.py")
        _mk_tasks_md(self.spec_dir,
                     "- path: core/obsolete.py\n  kind: delete\n")
        self.assertEqual(lint_declared(self.spec_dir, self.pr), [])


# ── 7.1 extract_declared 归类 ───────────────────────────────────────────────

class TestExtractDeclaredDelete(unittest.TestCase):
    """7.1 extract_declared：delete 归 deliverables；非法 kind 忽略；同路径首见。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.pr = Path(self.tmpdir)
        self.spec_dir = self.pr / "spec" / "changes" / "demo"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_delete_goes_to_deliverables(self):
        """delete 条目归 deliverables 桶。"""
        _mk_tasks_md(self.spec_dir,
                     "- path: core/a.py\n  kind: delete\n")
        typed = extract_declared(self.spec_dir)
        self.assertIn("core/a.py", typed["deliverables"])
        self.assertNotIn("core/a.py", typed["references"])

    def test_illegal_kind_ignored(self):
        """非法 kind（如 manual）条目被忽略。"""
        _mk_tasks_md(self.spec_dir,
                     "- path: core/a.py\n  kind: manual\n")
        typed = extract_declared(self.spec_dir)
        self.assertIsNone(typed)

    def test_same_path_first_seen_wins(self):
        """同路径首次出现的 kind 保留（首见去重）。"""
        _mk_tasks_md(self.spec_dir,
                     "- path: core/a.py\n  kind: modify\n"
                     "- path: core/a.py\n  kind: delete\n")
        typed = extract_declared(self.spec_dir)
        self.assertIn("core/a.py", typed["deliverables"])

    def test_entries_preserve_delete_kind(self):
        """extract_declared_entries：delete 条目 kind 保留。"""
        _mk_tasks_md(self.spec_dir,
                     "- path: core/old.py\n  kind: delete\n")
        entries = extract_declared_entries(self.spec_dir)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["kind"], "delete")


# ── 7.2 守卫反判 ────────────────────────────────────────────────────────────

class _GateFixture(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.project_root = self.tmpdir
        (self.project_root / ".fenix").mkdir(exist_ok=True)
        self.logger = mock.MagicMock()
        self.sm = StateMachine(self.project_root / ".fenix" / "STATE.md",
                               self.logger)
        self.runner = mock.MagicMock()
        self.runner.worktree_manager = mock.MagicMock()
        self.config = {}
        self.engine = PMEngine(self.sm, self.runner, self.config,
                               self.project_root, self.logger)
        self.wm = self.runner.worktree_manager

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def make_ready_spec(self, name="s1"):
        self.sm.add_spec(name, {"priority": 5})
        self.sm.transition(name, "ready")

    def make_result(self, branch="fenix/s1", run_id="run-1"):
        return AgentRunResult(run_id, "s1", "implementer",
                              success=True, duration_seconds=1.0, branch=branch)

    def write_spec_dir(self, name, tasks_text):
        spec_dir = self.project_root / "spec" / "changes" / name
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "tasks.md").write_text(tasks_text, encoding="utf-8")
        return spec_dir


class TestGateDeleteUndeleted(_GateFixture):
    """7.2 守卫反判：delete 条目在分支仍存在 → undeleted；已不存在 → 无违规。"""

    def test_delete_still_exists_undeleted(self):
        """delete 条目在分支 HEAD 仍存在 → undeleted 违规。"""
        self.make_ready_spec("s1")
        self.write_spec_dir("s1",
            "## Deliverables\n\n```yaml\n"
            "- path: core/obsolete.py\n  kind: delete\n```\n\n"
            "## 1. x\n\n- [ ] 1.1 删除 `core/obsolete.py`\n")
        self.wm.file_exists_on_branch.return_value = True
        violations = self.engine._deliverable_gate_missing("s1", self.make_result())
        self.assertEqual(len(violations), 1)
        v = violations[0]
        self.assertEqual(v["path"], "core/obsolete.py")
        self.assertEqual(v["kind"], "delete")
        self.assertEqual(v["violation"], "undeleted")

    def test_delete_not_exists_no_violation(self):
        """delete 条目已不存在 → 无违规。"""
        self.make_ready_spec("s1")
        self.write_spec_dir("s1",
            "## Deliverables\n\n```yaml\n"
            "- path: core/old.py\n  kind: delete\n```\n\n"
            "## 1. x\n\n- [ ] 1.1 删除\n")
        self.wm.file_exists_on_branch.return_value = False
        violations = self.engine._deliverable_gate_missing("s1", self.make_result())
        self.assertEqual(violations, [])

    def test_mixed_delete_and_missing(self):
        """delete + new 混合：逐条返回且 kind/violation 一一对应。"""
        self.make_ready_spec("s1")
        self.write_spec_dir("s1",
            "## Deliverables\n\n```yaml\n"
            "- path: core/old.py\n  kind: delete\n"
            "- path: core/new.py\n  kind: new\n```\n\n"
            "## 1. x\n\n- [ ] 1.1 x\n")
        # old.py 仍在分支（undeleted），new.py 不存在（missing）
        self.wm.file_exists_on_branch.side_effect = lambda b, p: (p == "core/old.py")
        violations = self.engine._deliverable_gate_missing("s1", self.make_result())
        by_path = {v["path"]: v for v in violations}
        self.assertEqual(by_path["core/old.py"]["kind"], "delete")
        self.assertEqual(by_path["core/old.py"]["violation"], "undeleted")
        self.assertEqual(by_path["core/new.py"]["kind"], "new")
        self.assertEqual(by_path["core/new.py"]["violation"], "missing")


# ── 7.3 防洗白三处 ──────────────────────────────────────────────────────────

class TestAntiWhitewashDelete(unittest.TestCase):
    """7.3 classify_unsatisfiable / soften 不改写 delete；预分类不软化；judge reference 被拒。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.project_root = self.tmpdir
        (self.project_root / ".fenix").mkdir(exist_ok=True)
        self.logger = mock.MagicMock()
        self.sm = StateMachine(self.project_root / ".fenix" / "STATE.md",
                               self.logger)
        self.runner = mock.MagicMock()
        self.runner.worktree_manager = mock.MagicMock()
        self.config = {}
        self.engine = PMEngine(self.sm, self.runner, self.config,
                               self.project_root, self.logger)
        self.spec_dir = self.project_root / "spec" / "changes" / "s1"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_spec(self, yaml_block: str):
        self.spec_dir.mkdir(parents=True, exist_ok=True)
        (self.spec_dir / "tasks.md").write_text(
            "# Tasks\n\n## Deliverables\n\n```yaml\n"
            + yaml_block + "\n```\n\n## 1. x\n\n- [ ] 1.1 do it\n",
            encoding="utf-8",
        )

    # 7.3-a：classify_unsatisfiable 恒返回 False（delete 不参与软化）

    def test_classify_unsatisfiable_delete_always_false(self):
        """classify_unsatisfiable 对 delete 条目恒返回 False。"""
        # 即使路径被 gitignore，delete 也不进软化
        entry = {"path": "dist/index.html", "kind": "delete"}
        self.assertFalse(classify_unsatisfiable(entry, self.project_root))
        # 路径在仓库外同理
        entry2 = {"path": "../../outside.py", "kind": "delete"}
        self.assertFalse(classify_unsatisfiable(entry2, self.project_root))

    # 7.3-b：soften_declared_kind 拒绝 delete 条目（上抛）

    def test_soften_declared_kind_rejects_delete(self):
        """soften_declared_kind 对 delete 条目上抛（不改写声明段）。"""
        self._write_spec(
            "- path: core/old.py\n  kind: delete\n")
        with self.assertRaises(ValueError) as cm:
            soften_declared_kind(self.spec_dir, "core/old.py")
        self.assertIn("delete", str(cm.exception))
        # 声明段未被改写
        text = (self.spec_dir / "tasks.md").read_text(encoding="utf-8")
        self.assertIn("kind: delete", text)

    # 7.3-c：soften_unsatisfiable_declarations 跳过 delete 条目

    def test_soften_unsatisfiable_skips_delete(self):
        """soften_unsatisfiable_declarations 跳过 delete 条目，不加入软化记录。"""
        import subprocess
        git_pr = self.project_root / "repo"
        git_pr.mkdir()
        subprocess.run(["git", "-C", str(git_pr), "init", "-q"], check=True)
        (git_pr / ".gitignore").write_text("dist/\n", encoding="utf-8")
        (git_pr / "dist").mkdir()
        (git_pr / "dist" / "index.html").write_text("x", encoding="utf-8")
        (git_pr / "core").mkdir()
        (git_pr / "core" / "data.py").write_text("x", encoding="utf-8")
        _mk_tasks_md_text = (
            "## Deliverables\n\n```yaml\n"
            "- path: dist/index.html\n  kind: delete\n"
            "- path: core/data.py\n  kind: modify\n```\n\n"
            "## 1. x\n\n- [ ] 1.1 do it\n"
        )
        sd = git_pr / "spec" / "changes" / "demo"
        sd.mkdir(parents=True)
        (sd / "tasks.md").write_text(_mk_tasks_md_text, encoding="utf-8")
        result = soften_unsatisfiable_declarations(sd, git_pr)
        # delete 被跳过，modify/dist 被软化（但 dist 也是 delete——等等，
        # dist/index.html 是 delete kind，不进软化；没有可软化条目 → result 空）
        # 由于条目都是 delete，result 应为空
        self.assertEqual(result, [])

    # 7.3-d：预分类不软化 delete（_preclassify_missing 逻辑，通过 guard 重跑验证）

    def test_preclassify_skips_delete(self):
        """_preclassify_missing 不软化 delete 条目，delete 保留在 remaining 进入后继流程。"""
        import subprocess
        subprocess.run(["git", "-C", str(self.project_root), "init", "-q"], check=True)
        # gitignored 的 modify 条目可软化（deterministic 非空 → continue）；
        # delete 条目 MUST NOT 被软化，保留在 remaining 进入 judge
        (self.project_root / ".gitignore").write_text("dist/\n", encoding="utf-8")
        (self.project_root / "dist").mkdir()
        (self.project_root / "dist" / "index.html").write_text("x", encoding="utf-8")
        (self.project_root / "core").mkdir()
        (self.project_root / "core" / "old.py").write_text("x", encoding="utf-8")
        self._write_spec(
            "- path: core/old.py\n  kind: delete\n"
            "- path: dist/index.html\n  kind: modify\n")
        result = mock.MagicMock()
        result.branch = "fenix/s1"
        # 缺件：delete 条目（undeleted）+ gitignored modify 条目
        missing = [
            {"path": "core/old.py", "kind": "delete", "violation": "undeleted"},
            {"path": "dist/index.html", "kind": "modify", "violation": "missing"},
        ]
        # 守卫重跑：软化 dist 后 delete 条目仍在（未删除）→ 仍有剩余
        self.engine._verification._deliverable_gate_missing = mock.MagicMock(return_value=[
            {"path": "core/old.py", "kind": "delete", "violation": "undeleted"},
        ])
        outcome = self.engine._dispatcher._preclassify_missing("s1", result, missing)
        self.assertEqual(outcome["action"], "continue")
        # delete 条目保留在 remaining（未被软化进 deterministic）
        self.assertIn("core/old.py", outcome["remaining"])
        # 声明段未被改写（delete 条目原样保留）
        text = (self.spec_dir / "tasks.md").read_text(encoding="utf-8")
        self.assertIn("core/old.py\n  kind: delete", text)
        self.assertNotIn("core/old.py\n  kind: reference", text)


# ── 7.4 派发前处方 delete 两种形态 ──────────────────────────────────────────

class TestRealitySnapshotDelete(unittest.TestCase):
    """7.4 派发前处方对 delete 的两种形态：主树存在/不存在。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.project_root = self.tmpdir
        (self.project_root / ".fenix").mkdir(exist_ok=True)
        self.logger = mock.MagicMock()
        self.sm = StateMachine(self.project_root / ".fenix" / "STATE.md",
                               self.logger)
        self.wm = mock.MagicMock()
        self.wm.get_legacy.return_value = None
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

    def test_delete_exists_target_confirmed(self):
        """主树存在 → 「删除目标确认」。"""
        (self.project_root / "core").mkdir()
        (self.project_root / "core" / "old.py").write_text("x", encoding="utf-8")
        self.write_spec("s1",
            "## Deliverables\n\n```yaml\n"
            "- path: core/old.py\n  kind: delete\n```\n\n"
            "## 1. x\n\n- [ ] 1.1 do it\n")
        section = self.runner._prompt_builder._declared_reality_section("s1")
        self.assertIn("删除目标确认", section)
        self.assertNotIn("修改目标确认", section)

    def test_delete_nonexistent_suspected_typo_with_candidates(self):
        """主树不存在 → 「无可删，疑似声明笔误」+ basename 候选。"""
        # 声明 core/old.py（主树不存在该路径），但 scripts/old.py 存在 →
        # basename 候选命中 old.py（疑似笔误）
        (self.project_root / "scripts").mkdir()
        (self.project_root / "scripts" / "old.py").write_text("x", encoding="utf-8")
        self.write_spec("s1",
            "## Deliverables\n\n```yaml\n"
            "- path: core/old.py\n  kind: delete\n```\n\n"
            "## 1. x\n\n- [ ] 1.1 do it\n")
        section = self.runner._prompt_builder._declared_reality_section("s1")
        self.assertIn("无可删", section)
        self.assertIn("疑似声明笔误", section)
        self.assertIn("scripts/old.py", section)  # basename 候选


# ── 7.3 第三处防洗白：judge 对 delete 给 reference 被改写为 unclear ──────────

class TestJudgeDeleteReferenceRejected(unittest.TestCase):
    """judge 对 kind: delete 条目裁决 reference → 机械改写为 unclear，不软化声明段。"""

    def setUp(self):
        import json
        self.json = json
        self.tmpdir = Path(tempfile.mkdtemp())
        self.project_root = self.tmpdir
        (self.project_root / ".fenix").mkdir(exist_ok=True)
        self.logger = mock.MagicMock()
        self.sm = StateMachine(self.project_root / ".fenix" / "STATE.md",
                               self.logger)
        self.runner = mock.MagicMock()
        self.runner.worktree_manager = mock.MagicMock()
        self.config = {}
        self.engine = PMEngine(self.sm, self.runner, self.config,
                               self.project_root, self.logger)
        self.wm = self.runner.worktree_manager
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.transition("s1", "ready")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def write_spec_dir(self, tasks_text):
        spec_dir = self.project_root / "spec" / "changes" / "s1"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "tasks.md").write_text(tasks_text, encoding="utf-8")
        return spec_dir

    def make_result(self, branch="fenix/s1", run_id="impl-s1-1-a1"):
        return AgentRunResult(run_id, "s1", "implementer",
                              success=True, duration_seconds=1.0, branch=branch)

    def write_judge_result(self, verdicts, status="success"):
        vp = self.project_root / ".fenix" / "verify-progress" / "s1"
        vp.mkdir(parents=True, exist_ok=True)
        (vp / "dispute_judge_result.json").write_text(
            self.json.dumps({"status": status, "verdicts": verdicts},
                            ensure_ascii=False),
            encoding="utf-8",
        )

    def stub_judge_run(self):
        def fake_run(spec_name, judge_input, run_id=None):
            return AgentRunResult(run_id or "dispute-judge-s1-1", "s1",
                                  "dispute-judge", success=True,
                                  duration_seconds=1.0)

        self.runner.run_dispute_judge = fake_run

    def test_judge_reference_on_delete_rewritten_to_unclear(self):
        """judge 对 delete 条目裁决 reference → 改写为 unclear 转人工，声明段不改写。"""
        tasks = (
            "# Tasks\n\n## Deliverables\n\n```yaml\n"
            "- path: core/old.py\n  kind: delete\n```\n"
            "## 1. 分组\n\n- [ ] 1.1 删除 `core/old.py`\n"
        )
        self.write_spec_dir(tasks)
        # judge 错误地裁决 reference（该路径应被删除，不应被软化为引用）
        self.write_judge_result([
            {"element": "core/old.py", "verdict": "reference",
             "reasoning": "误判为运行时文件", "confidence": "high"},
        ])
        self.stub_judge_run()
        # delete 条目仍在分支（未删除）→ undeleted
        self.wm.file_exists_on_branch.side_effect = (
            lambda branch, path: path == "core/old.py")

        outcome = self.engine._adjudicate_deliverable_missing(
            "s1", self.make_result(), None, [
                {"path": "core/old.py", "kind": "delete",
                 "violation": "undeleted"}])

        # reference 被拒 → unclear 转人工（blocked），不软化声明段
        self.assertEqual(outcome["action"], "handled")
        entry = self.sm.read_one("s1")
        self.assertEqual(entry["status"], "blocked")
        self.assertIn("LLM 终审裁决 unclear", entry["error"])
        # 声明段未被改写（仍是 kind: delete，未被软化为 reference）
        tasks_text = (self.project_root / "spec" / "changes" / "s1"
                      / "tasks.md").read_text(encoding="utf-8")
        self.assertIn("kind: delete", tasks_text)
        self.assertNotIn("kind: reference", tasks_text)
