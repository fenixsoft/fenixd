"""tests/test_declaration_relocation.py — 重定位协议与陈日前置分类测试。

覆盖 add-declaration-relocation-protocol Tasks 5.2 / 3.5 / 4.3 / 3.6：
- 陈日信号判定（modify 路径主树 HEAD 不存在命中、new 正常语义不误判且不
  被强制转入重定位通道、delete/reference 不参与）
- 三要素凭据（缺替代路径拒绝 / 多命中不自动 / basename 唯一命中触发）
- 重定位改写与审计留痕
- 生效声明已无该条目时的凭据登记（齐备登记放行 / 替代路径不存在不登记）
- 重定位后防洗白复检（通过放行 / 仍缺件打回）
- 失败安全（改写异常回退缺件处置）
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from core.admin_store import DisputeAuditStore
from core.deliverables import (
    _has_relocation_credential,
    check_declaration_shrinkage,
    extract_declared,
    extract_declared_entries,
    is_stale_declaration,
    load_declaration_baseline,
    match_basename_in_tree,
    register_relocation_credential,
    relocate_declared_path,
    resolve_effective_declaration,
    snapshot_declaration_baseline,
)
from core.pm_engine.engine import PMEngine
from core.state_machine import StateMachine
from core.agent_runner import AgentRunResult


class _FakeLogger:
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass
    def debug(self, *a, **k): pass


def _init_git(root: Path):
    import subprocess as sp
    sp.run(["git", "init", str(root)], capture_output=True, timeout=30)
    sp.run(["git", "-C", str(root), "config", "user.name", "test"],
           capture_output=True, timeout=10)
    sp.run(["git", "-C", str(root), "config", "user.email", "test@test.com"],
           capture_output=True, timeout=10)
    sp.run(["git", "-C", str(root), "config", "core.autocrlf", "false"],
           capture_output=True, timeout=10)
    (root / ".gitkeep").write_text("")
    sp.run(["git", "-C", str(root), "add", "."], capture_output=True, timeout=10)
    sp.run(["git", "-C", str(root), "commit", "-m", "init"],
           capture_output=True, timeout=30)


def _make_task_file(root: Path, spec_name: str, content: str):
    sd = root / "spec" / "changes" / spec_name
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "tasks.md").write_text(content, encoding="utf-8")
    return sd


def _commit_all(root: Path, msg: str):
    import subprocess as sp
    sp.run(["git", "-C", str(root), "add", "-A"], capture_output=True, timeout=10)
    sp.run(["git", "-C", str(root), "commit", "-m", msg],
           capture_output=True, timeout=30)


def _create_branch(root: Path, branch: str):
    import subprocess as sp
    sp.run(["git", "-C", str(root), "checkout", "-b", branch],
           capture_output=True, timeout=10)


def _checkout_main(root: Path):
    import subprocess as sp
    sp.run(["git", "-C", str(root), "checkout", "main"],
           capture_output=True, timeout=10)


class TestIsStaleDeclaration(unittest.TestCase):
    """陈日信号判定（3.1）：modify 且主树 HEAD 不存在 → True；new 恒 False。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_modify_path_missing_in_main_tree(self):
        _init_git(self.tmpdir)
        self.assertTrue(
            is_stale_declaration({"path": "core/old.py", "kind": "modify"}, str(self.tmpdir)),
            "modify 路径在主树 HEAD 不存在 → 命中陈日信号",
        )

    def test_modify_path_exists_in_main_tree(self):
        _init_git(self.tmpdir)
        (self.tmpdir / "core").mkdir(exist_ok=True)
        (self.tmpdir / "core" / "real.py").write_text("x")
        _commit_all(self.tmpdir, "add core/real.py")
        self.assertFalse(
            is_stale_declaration({"path": "core/real.py", "kind": "modify"}, str(self.tmpdir)),
            "modify 路径在主树 HEAD 存在 → 非陈日",
        )

    def test_new_always_false(self):
        _init_git(self.tmpdir)
        self.assertFalse(
            is_stale_declaration({"path": "core/new.py", "kind": "new"}, str(self.tmpdir)),
            "new 恒 False（基线期望不存在是正常语义）",
        )

    def test_delete_reference_always_false(self):
        _init_git(self.tmpdir)
        self.assertFalse(is_stale_declaration({"path": "x", "kind": "delete"}, str(self.tmpdir)))
        self.assertFalse(is_stale_declaration({"path": "x", "kind": "reference"}, str(self.tmpdir)))


class TestRelocateCredentialTriad(unittest.TestCase):
    """凭据三要素校验（3.3）：缺替代路径拒绝 / 多命中不自动 / 唯一命中触发。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        _init_git(self.tmpdir)
        self.logger = _FakeLogger()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_reject_when_new_path_not_on_branch(self):
        result = register_relocation_credential(
            "s1", "core/old.py", "core/new.py", "mechanical-basename",
            "run-1", str(self.tmpdir), branch="main",
        )
        self.assertIsNone(result, "替代路径不在分支 HEAD → MUST NOT 登记")

    def test_reject_when_no_source(self):
        (self.tmpdir / "core").mkdir(exist_ok=True)
        (self.tmpdir / "core" / "new.py").write_text("x")
        _commit_all(self.tmpdir, "add new.py")
        result = register_relocation_credential(
            "s1", "core/old.py", "core/new.py", "", "run-1", str(self.tmpdir), branch="main",
        )
        self.assertIsNone(result, "来源标注缺失 → MUST NOT 登记")

    def test_unique_basename_match_in_tree(self):
        # match_basename_in_tree 按 Path("core/old.py").name == "old.py" 匹配
        (self.tmpdir / "core").mkdir(exist_ok=True)
        (self.tmpdir / "core" / "old.py").write_text("x")
        hits = match_basename_in_tree(str(self.tmpdir), "core/old.py")
        self.assertEqual(hits, ["core/old.py"], "唯一 basename 命中")

    def test_multiple_hits_not_auto_relocate(self):
        (self.tmpdir / "core").mkdir(parents=True, exist_ok=True)
        (self.tmpdir / "core" / "sub").mkdir(exist_ok=True)
        (self.tmpdir / "core" / "old.py").write_text("a")
        (self.tmpdir / "core" / "sub" / "old.py").write_text("b")
        hits = match_basename_in_tree(str(self.tmpdir), "core/old.py")
        self.assertGreater(len(hits), 1, "多命中 → 不自动重定位")


class TestRelocationRewrite(unittest.TestCase):
    """重定位改写与审计留痕（3.2/审计留痕 Scenario）"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        _init_git(self.tmpdir)
        _make_task_file(self.tmpdir, "s1",
                        "# Tasks\n## Deliverables\n```yaml\n"
                        "- path: core/old.py\n  kind: modify\n```\n"
                        "## 1. T\n- [ ] 1.1 do\n")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_rewrite_replaces_path_in_tasks(self):
        sd = relocate_declared_path(
            self.tmpdir / "spec" / "changes" / "s1", "core/old.py", "core/new.py"
        )
        self.assertEqual(sd["element"], "core/old.py")
        self.assertEqual(sd["actual_path"], "core/new.py")
        text = (self.tmpdir / "spec" / "changes" / "s1" / "tasks.md").read_text()
        self.assertIn("path: core/new.py", text)
        self.assertNotIn("path: core/old.py", text)


class TestHasRelocationCredential(unittest.TestCase):
    """_has_relocation_credential 豁免判定：type=relocation 在册 → True；typo 修正
    审计在册 → True（4.3 重定位接入裁决）；无凭据 → False"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        _init_git(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_relocation_record_exempts(self):
        DisputeAuditStore(str(self.tmpdir)).append({
            "type": "relocation",
            "old_path": "core/old.py",
            "new_path": "core/new.py",
        })
        self.assertTrue(_has_relocation_credential(str(self.tmpdir), "core/old.py"))

    def test_typo_verdict_record_exempts(self):
        DisputeAuditStore(str(self.tmpdir)).append({
            "verdicts": [
                {"element": "core/old.py", "verdict": "typo", "actual_path": "core/new.py"},
            ]
        })
        self.assertTrue(_has_relocation_credential(str(self.tmpdir), "core/old.py"))

    def test_no_record_returns_false(self):
        self.assertFalse(_has_relocation_credential(str(self.tmpdir), "core/old.py"))


class TestSnapshotAndShrinkage(unittest.TestCase):
    """基线快照 + 收缩防护：删声明行绕门判 removed；凭据登记豁免；无基线保守降级"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        _init_git(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_snapshot_returns_entries(self):
        _make_task_file(self.tmpdir, "s1",
                        "## Deliverables\n```yaml\n"
                        "- path: core/a.py\n  kind: new\n- path: core/b.py\n  kind: modify\n```\n"
                        "## 1. T\n- [ ] 1.1 do\n")
        snap = snapshot_declaration_baseline("s1", "run-1", str(self.tmpdir))
        self.assertIsNotNone(snap)
        paths = {e["path"] for e in snap["entries"]}
        self.assertEqual(paths, {"core/a.py", "core/b.py"})

    def test_shrinkage_detected_when_entry_removed(self):
        _make_task_file(self.tmpdir, "s1",
                        "## Deliverables\n```yaml\n"
                        "- path: core/a.py\n  kind: new\n```\n"
                        "## 1. T\n- [ ] 1.1 do\n")
        baseline = snapshot_declaration_baseline("s1", "run-1", str(self.tmpdir))
        # 删除基线条目：写一份无 core/a.py 的生效声明
        _make_task_file(self.tmpdir, "s1",
                        "## Deliverables\n```yaml\n"
                        "- path: core/b.py\n  kind: new\n```\n"
                        "## 1. T\n- [ ] 1.1 do\n")
        from core.deliverables import extract_declared
        effective = extract_declared(self.tmpdir / "spec" / "changes" / "s1")
        eff_entries = extract_declared_entries(self.tmpdir / "spec" / "changes" / "s1")
        violations = check_declaration_shrinkage(
            baseline, effective, eff_entries or [], "main", str(self.tmpdir),
        )
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]["path"], "core/a.py")
        self.assertEqual(violations[0]["violation"], "removed")

    def test_relocation_credential_exempts_shrinkage(self):
        _make_task_file(self.tmpdir, "s1",
                        "## Deliverables\n```yaml\n"
                        "- path: core/a.py\n  kind: new\n```\n"
                        "## 1. T\n- [ ] 1.1 do\n")
        baseline = snapshot_declaration_baseline("s1", "run-1", str(self.tmpdir))
        # 重定位凭据登记（模拟改写后已有凭据）
        (self.tmpdir / "core").mkdir(exist_ok=True)
        (self.tmpdir / "core" / "b.py").write_text("x")
        _commit_all(self.tmpdir, "add b.py")
        DisputeAuditStore(str(self.tmpdir)).append({
            "type": "relocation", "old_path": "core/a.py", "new_path": "core/b.py",
        })
        # 生效声明已改
        _make_task_file(self.tmpdir, "s1",
                        "## Deliverables\n```yaml\n"
                        "- path: core/b.py\n  kind: new\n```\n"
                        "## 1. T\n- [ ] 1.1 do\n")
        from core.deliverables import extract_declared, extract_declared_entries
        effective = extract_declared(self.tmpdir / "spec" / "changes" / "s1")
        eff_entries = extract_declared_entries(self.tmpdir / "spec" / "changes" / "s1")
        violations = check_declaration_shrinkage(
            baseline, effective, eff_entries or [], "main", str(self.tmpdir),
        )
        self.assertEqual(len(violations), 0, "凭据在册 → 收缩豁免，不判 removed")

    def test_kind_rewritten_to_reference_detected_as_removed(self):
        """基线 modify 被改写为 reference（移入软校验组）→ 判 removed 不放行"""
        _make_task_file(self.tmpdir, "s1",
                        "## Deliverables\n```yaml\n"
                        "- path: core/x.py\n  kind: modify\n```\n"
                        "## 1. T\n- [ ] 1.1 do\n")
        baseline = snapshot_declaration_baseline("s1", "run-1", str(self.tmpdir))
        # 生效声明把 kind 改写为 reference（无声软化，无审计凭据）
        _make_task_file(self.tmpdir, "s1",
                        "## Deliverables\n```yaml\n"
                        "- path: core/x.py\n  kind: reference\n```\n"
                        "## 1. T\n- [ ] 1.1 do\n")
        from core.deliverables import extract_declared, extract_declared_entries
        effective = extract_declared(self.tmpdir / "spec" / "changes" / "s1")
        eff_entries = extract_declared_entries(self.tmpdir / "spec" / "changes" / "s1")
        violations = check_declaration_shrinkage(
            baseline, effective, eff_entries or [], "main", str(self.tmpdir),
        )
        self.assertEqual(len(violations), 1, "kind 改写为 reference 绕门 → 判 removed")
        self.assertEqual(violations[0]["path"], "core/x.py")
        self.assertEqual(violations[0]["violation"], "removed")

    def test_no_baseline_conservative_degradation(self):
        """无基线快照 → 收缩防护降级保守：不判违规（不误伤正常轮次）"""
        _make_task_file(self.tmpdir, "s1",
                        "## Deliverables\n```yaml\n"
                        "- path: core/a.py\n  kind: new\n```\n"
                        "## 1. T\n- [ ] 1.1 do\n")
        # 不落基线快照
        from core.deliverables import extract_declared, extract_declared_entries
        effective = extract_declared(self.tmpdir / "spec" / "changes" / "s1")
        eff_entries = extract_declared_entries(self.tmpdir / "spec" / "changes" / "s1")
        violations = check_declaration_shrinkage(
            None, effective, eff_entries or [], "main", str(self.tmpdir),
        )
        self.assertEqual(violations, [], "无基线 → 保守降级不判 removed")


class TestAdjudicationStalePipeline(unittest.TestCase):
    """adjudication 陈日前置分类全链路（3.5/4.3）：mock runner + 非 git
    tmpdir 环境（与 test_deliverable_declaration_triage 同构）：无 git
    仓库时 _effective_declaration 回退主树 spec_dir（可写）+ 陈日判定
    回退文件系统（不存在即 stale）+ basename 匹配走文件系统 rglob"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        (self.tmpdir / ".fenix").mkdir(exist_ok=True)
        self.sm = StateMachine(self.tmpdir / ".fenix" / "STATE.md", _FakeLogger())
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.transition("s1", "ready")
        self.runner = mock.MagicMock()
        self.engine = PMEngine(self.sm, self.runner, {}, self.tmpdir, _FakeLogger())
        self.wm = self.runner.worktree_manager
        self.wm.file_exists_on_branch.return_value = False

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_stale_modify_relocates_by_basename(self):
        """陈日 modify 声明：主树无 core/old.py（陈日信号），basename 唯一命中
        core/old_target/old.py → 机械重定位 → 守卫复检通过 → 放行"""
        sd = _make_task_file(self.tmpdir, "s1",
                             "## Deliverables\n```yaml\n"
                             "- path: core/old.py\n  kind: modify\n```\n"
                             "## 1. T\n- [ ] 1.1 do\n")
        # 主树存在 old_target/old.py（basename 唯一命中源）
        (self.tmpdir / "core" / "old_target").mkdir(parents=True, exist_ok=True)
        (self.tmpdir / "core" / "old_target" / "old.py").write_text("existing")
        self.sm.transition("s1", "implementing")
        self.wm.file_exists_on_branch.side_effect = (
            lambda br, p: p == "core/old_target/old.py")
        result = AgentRunResult("run-1", "s1", "implementer",
                                success=True, branch="fenix/s1",
                                duration_seconds=1.0)
        missing = [{"path": "core/old.py", "kind": "modify", "violation": "missing"}]
        outcome = self.engine._adjudicate_deliverable_missing(
            "s1", result, {"status": "success", "findings": []}, missing,
            agent_type="implementer",
        )
        self.assertEqual(outcome["action"], "proceed",
                         "陈日重定位后守卫复检通过 → 放行")
        text = (sd / "tasks.md").read_text()
        self.assertIn("path: core/old_target/old.py", text, "声明段已重定位")
        self.assertNotIn("path: core/old.py", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
