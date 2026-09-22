"""tests/test_deliverable_drift_align.py — 交付物声明漂移笔误机械对齐测试。

覆盖 evo-deliverable-declaration-drift-align Tasks 3.1/3.2：
- 漂移判定（is_drift_candidate）：主树/分支 HEAD 均缺 + git 历史命中 → 漂移
  特征；历史零命中（孤儿特征）/分支 HEAD 已落地/new 形态 → 非漂移
- 候选定位（_locate_drift_target）：旧路径 basename 去 .py 得包目录 ∩ 分支
  改动集合；唯一候选 / 多候选 fail-open / 零候选 fail-open；含真实拆包形态
  （core/worktree_manager.py / core/pm_engine/dispatch.py）取证
- 对齐执行（_preclassify_drift）：唯一候选机械改写生效声明 + 审计
  （type=relocation + verdict=drift-aligned）+ 解阻（proceed）；零/多候选
  fail-open 回人工；候选不在分支 HEAD 回人工；spec_dir=None（分支来源）走
  凭据登记不改写主树
- 同源草案派发拦截（_check_superseded_convergence / _on_spec_ready /
  _process_queue）：本目录含 SUPERSEDED.md 者被阻断、对侧生效落点正常派发、
  移除 SUPERSEDED.md 后恢复派发
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.admin_store import DisputeAuditStore
from core.deliverables import (
    _git_branch_merge_base,
    _locate_drift_target,
    is_drift_candidate,
)
from core.pm_engine import PMEngine
from core.pm_engine.dispatch import Dispatcher
from core.state_machine import StateMachine
from core.agent_runner import AgentRunResult


def _git(root: Path, *args, check=True):
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result


# ── 纯函数夹具（is_drift_candidate / _locate_drift_target 需真实 git 仓库）──

class _GitDriftRepoFixture(unittest.TestCase):
    """临时 git 仓库夹具（漂移判定需要真实 git 历史 / 分支改动集合）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.pr = Path(self.tmpdir) / "repo"
        self.pr.mkdir(parents=True, exist_ok=True)
        _git(self.pr, "init", "-q")
        _git(self.pr, "config", "user.email", "test@fenix.local")
        _git(self.pr, "config", "user.name", "Fenix Test")
        _git(self.pr, "config", "commit.gpgsign", "false")
        (self.pr / ".gitignore").write_text("dist/\n.history/\n", encoding="utf-8")
        (self.pr / "core").mkdir(parents=True, exist_ok=True)
        (self.pr / "core" / "data.py").write_text("x", encoding="utf-8")
        _git(self.pr, "add", "-A")
        _git(self.pr, "commit", "-q", "-m", "base")
        self.main_branch = _git(
            self.pr, "rev-parse", "--abbrev-ref", "HEAD"
        ).stdout.strip()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def make_drift_branch(self, old_path: str, pkg_file: str,
                          branch: str = "fenix/s1", extra_branch_files=None):
        """构造拆包/改名漂移形态（真实 git 状态）：

        1. 当前分支（主分支）先提交旧单文件 old_path（git 历史命中源）；
        2. 主分支删除旧单文件（主树 HEAD 无该路径——拆包后旧文件不再存在，
           与真实漂移形态一致：主树与实现分支 HEAD 均缺该路径）；
        3. 新建实现分支 branch：包目录落地 pkg_file（拆包改动落在分支改动集合）；
        4. 切回主分支。

        extra_branch_files: 可选 {相对路径: 内容}，随拆包提交一并落分支
        （如 spec 目录 tasks.md，用于分支来源 spec_dir=None 场景）。
        """
        (self.pr / old_path).parent.mkdir(parents=True, exist_ok=True)
        (self.pr / old_path).write_text("legacy", encoding="utf-8")
        _git(self.pr, "add", "-A")
        _git(self.pr, "commit", "-q", "-m", "add legacy single file")
        _git(self.pr, "rm", "-q", "-f", old_path)
        _git(self.pr, "commit", "-q", "-m", "remove legacy single file")
        _git(self.pr, "checkout", "-q", "-b", branch)
        (self.pr / pkg_file).parent.mkdir(parents=True, exist_ok=True)
        (self.pr / pkg_file).write_text("import x\n", encoding="utf-8")
        for rel, content in (extra_branch_files or {}).items():
            p = self.pr / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        _git(self.pr, "add", "-A")
        _git(self.pr, "commit", "-q", "-m", "split into package")
        _git(self.pr, "checkout", "-q", self.main_branch)


# ══════════════════════════════════════════════════════════════════════════════
# TestLocateDriftTarget：候选定位（_locate_drift_target 纯函数）
# ══════════════════════════════════════════════════════════════════════════════

class TestLocateDriftTarget(_GitDriftRepoFixture):
    """候选定位规则：包目录 ∩ 分支改动集合；唯一候选可对齐，零/多候选 fail-open。"""

    def test_unique_candidate_real_unpack_worktree_manager(self):
        """真实拆包形态取证：core/worktree_manager.py → 包内唯一改动 mergeback.py。"""
        self.make_drift_branch(
            "core/worktree_manager.py",
            "core/worktree_manager/mergeback.py",
        )
        mb = _git_branch_merge_base(self.pr, "fenix/s1")
        cands = _locate_drift_target(
            self.pr, "core/worktree_manager.py", "fenix/s1", mb
        )
        self.assertEqual(
            cands, ["core/worktree_manager/mergeback.py"],
            f"真实拆包形态应唯一命中包内改动文件: {cands}",
        )

    def test_unique_candidate_dispatch_py_real_package(self):
        """真实拆包形态取证：core/pm_engine/dispatch.py → dispatch/ 包内唯一改动。"""
        self.make_drift_branch(
            "core/pm_engine/dispatch.py",
            "core/pm_engine/dispatch/queue.py",
        )
        mb = _git_branch_merge_base(self.pr, "fenix/s1")
        cands = _locate_drift_target(
            self.pr, "core/pm_engine/dispatch.py", "fenix/s1", mb
        )
        self.assertEqual(
            cands, ["core/pm_engine/dispatch/queue.py"],
            f"dispatch 拆包唯一改动应命中: {cands}",
        )

    def test_multiple_candidates_fail_open(self):
        """多候选（包目录内分支改动 .py ≥ 2）→ 不唯一，调用方 fail-open 回人工。"""
        self.make_drift_branch(
            "core/pm_engine/dispatch.py",
            "core/pm_engine/dispatch/adjudication.py",
        )
        _git(self.pr, "checkout", "-q", "fenix/s1")
        (self.pr / "core" / "pm_engine" / "dispatch" / "queue.py").write_text(
            "y\n", encoding="utf-8",
        )
        _git(self.pr, "add", "-A")
        _git(self.pr, "commit", "-q", "-m", "second module in package")
        _git(self.pr, "checkout", "-q", self.main_branch)
        mb = _git_branch_merge_base(self.pr, "fenix/s1")
        cands = _locate_drift_target(
            self.pr, "core/pm_engine/dispatch.py", "fenix/s1", mb
        )
        self.assertTrue(
            len(cands) >= 2,
            f"包内两个改动模块应产生多候选: {cands}",
        )

    def test_zero_candidates_fail_open(self):
        """零候选（分支改动集合不含包目录 .py）→ 空列表（fail-open 回人工）。"""
        self.make_drift_branch("core/worker.py", "core/unrelated.py")
        mb = _git_branch_merge_base(self.pr, "fenix/s1")
        cands = _locate_drift_target(
            self.pr, "core/worker.py", "fenix/s1", mb
        )
        self.assertEqual(
            cands, [], "分支改动集合无包目录内 .py → 零候选",
        )

    def test_non_py_path_no_candidates(self):
        """非 .py 声明路径无「拆包为目录」形态 → 零候选。"""
        self.make_drift_branch("core/worker.py", "core/worker/worker.py")
        mb = _git_branch_merge_base(self.pr, "fenix/s1")
        cands = _locate_drift_target(
            self.pr, "core/worker.json", "fenix/s1", mb
        )
        self.assertEqual(cands, [], "非 .py 无拆包形态 → 零候选")


# ══════════════════════════════════════════════════════════════════════════════
# TestIsDriftCandidate：漂移特征判定（1.1）
# ══════════════════════════════════════════════════════════════════════════════

class TestIsDriftCandidate(_GitDriftRepoFixture):
    """漂移特征：主树/分支 HEAD 均缺 + git 历史命中；与孤儿判据互斥。"""

    def test_drift_hit_with_unique_candidate(self):
        """漂移特征命中：主树/分支 HEAD 均缺 + 历史命中 → drift=True 且带候选。"""
        self.make_drift_branch(
            "core/worktree_manager.py",
            "core/worktree_manager/mergeback.py",
        )
        dc = is_drift_candidate(
            {"path": "core/worktree_manager.py", "kind": "modify"},
            self.pr, "fenix/s1",
        )
        self.assertTrue(dc["drift"], f"应判漂移特征: {dc}")
        ev = dc["evidence"]
        self.assertEqual(
            ev["candidates"], ["core/worktree_manager/mergeback.py"],
        )
        self.assertGreaterEqual(ev.get("history_hit", 0), 1, "历史应有命中")

    def test_history_zero_hit_not_drift(self):
        """历史零命中（从未存在过）→ 非漂移（孤儿特征，与孤儿通道互斥）。"""
        dc = is_drift_candidate(
            {"path": "core/never_existed.py", "kind": "modify"},
            self.pr, "fenix/s1",
        )
        self.assertFalse(dc["drift"], "历史零命中 → 非漂移（走孤儿通道）")

    def test_branch_head_has_path_not_drift(self):
        """实现分支 HEAD 已落地该路径 → 非漂移（无缺件，无需对齐）。"""
        # 主树 HEAD 无该路径（stale）但分支 HEAD 有（分支恢复提交）
        (self.pr / "core" / "legacy_v1.py").write_text("v1", encoding="utf-8")
        _git(self.pr, "add", "-A")
        _git(self.pr, "commit", "-q", "-m", "add legacy_v1")
        _git(self.pr, "rm", "-q", "-f", "core/legacy_v1.py")
        _git(self.pr, "commit", "-q", "-m", "del legacy_v1")
        _git(self.pr, "checkout", "-q", "-b", "fenix/landed")
        (self.pr / "core" / "legacy_v1.py").write_text("v1", encoding="utf-8")
        _git(self.pr, "add", "-A")
        _git(self.pr, "commit", "-q", "-m", "restore legacy_v1")
        _git(self.pr, "checkout", "-q", self.main_branch)
        dc = is_drift_candidate(
            {"path": "core/legacy_v1.py", "kind": "modify"},
            self.pr, "fenix/landed",
        )
        self.assertFalse(dc["drift"], "分支 HEAD 已落地 → 非漂移")

    def test_new_kind_not_drift(self):
        """kind: new 不参与漂移判定（无「曾作为文件存在过」的漂移语义）。"""
        self.make_drift_branch(
            "core/worktree_manager.py",
            "core/worktree_manager/mergeback.py",
        )
        dc = is_drift_candidate(
            {"path": "core/worktree_manager.py", "kind": "new"},
            self.pr, "fenix/s1",
        )
        self.assertFalse(dc["drift"], "new 形态恒非漂移")

    def test_no_branch_fail_open(self):
        """分支缺失 → fail-open 非漂移（无法判定分支 HEAD 缺失，不机械改写）。"""
        self.make_drift_branch(
            "core/worktree_manager.py",
            "core/worktree_manager/mergeback.py",
        )
        dc = is_drift_candidate(
            {"path": "core/worktree_manager.py", "kind": "modify"},
            self.pr, None,
        )
        self.assertFalse(dc["drift"], "无分支上下文 → 非漂移（保守）")


# ── 调度器夹具（_preclassify_drift via Dispatcher，含真实 git 仓库）─────────

class _DriftDispatchFixture(unittest.TestCase):
    """真实 git 仓库 + StateMachine + mock runner，驱动 _preclassify_drift。

    与 test_deliverable_orphan_preclassify._OrphanDispatchFixture 同构：
    真实 git 仓库（git log / diff / cat-file 需要）、真实 Dispatcher
    （VAdjudicationMixin MRO 命中）、mock runner + worktree_manager
    （file_exists_on_branch / 守卫 gate 重跑可控）。
    """

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.project_root = self.tmpdir / "repo"
        self.project_root.mkdir(parents=True, exist_ok=True)
        _git(self.project_root, "init", "-q")
        _git(self.project_root, "config", "user.email", "test@fenix.local")
        _git(self.project_root, "config", "user.name", "Fenix Test")
        _git(self.project_root, "config", "commit.gpgsign", "false")
        (self.project_root / ".gitignore").write_text(
            "dist/\n.history/\n", encoding="utf-8",
        )
        (self.project_root / ".fenix").mkdir(exist_ok=True)
        (self.project_root / "core").mkdir(parents=True, exist_ok=True)
        (self.project_root / "core" / "data.py").write_text("x", encoding="utf-8")
        _git(self.project_root, "add", "-A")
        _git(self.project_root, "commit", "-q", "-m", "base")
        self.main_branch = _git(
            self.project_root, "rev-parse", "--abbrev-ref", "HEAD"
        ).stdout.strip()
        self.logger = mock.MagicMock()
        self.sm = StateMachine(
            self.project_root / ".fenix" / "STATE.md", self.logger,
        )
        self.runner = mock.MagicMock()
        self.runner.worktree_manager = mock.MagicMock()
        # 无真实 worktree：_commit_declaration_rewrite 重挂失败 → 回退主树提交路径
        self.runner.worktree_manager.find_worktree_path.return_value = None
        self.runner.worktree_manager.create_worktree_on_branch.return_value = None
        self.config = {}
        self.engine = PMEngine(
            self.sm, self.runner, self.config, self.project_root, self.logger,
        )
        self.dispatcher = Dispatcher(self.engine)
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.transition("s1", "ready")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def make_drift_branch(self, old_path, pkg_file,
                          branch="fenix/s1", extra_branch_files=None):
        """构造拆包漂移分支形态（主树 HEAD 无旧路径 + 历史命中 + 分支改动落点）。"""
        (self.project_root / old_path).parent.mkdir(parents=True, exist_ok=True)
        (self.project_root / old_path).write_text("legacy", encoding="utf-8")
        _git(self.project_root, "add", "-A")
        _git(self.project_root, "commit", "-q", "-m", "add legacy single file")
        _git(self.project_root, "rm", "-q", "-f", old_path)
        _git(self.project_root, "commit", "-q", "-m", "remove legacy single file")
        _git(self.project_root, "checkout", "-q", "-b", branch)
        (self.project_root / pkg_file).parent.mkdir(parents=True, exist_ok=True)
        (self.project_root / pkg_file).write_text("import x\n", encoding="utf-8")
        for rel, content in (extra_branch_files or {}).items():
            p = self.project_root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        _git(self.project_root, "add", "-A")
        _git(self.project_root, "commit", "-q", "-m", "split into package")
        _git(self.project_root, "checkout", "-q", self.main_branch)

    def write_spec_dir(self, yaml_block: str,
                       task_lines: str = "- [ ] 1.1 do it"):
        spec_dir = self.project_root / "spec" / "changes" / "s1"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "tasks.md").write_text(
            "# Tasks\n\n## Deliverables\n\n```yaml\n"
            + yaml_block + "```\n\n## 1. x\n\n" + task_lines + "\n",
            encoding="utf-8",
        )
        return spec_dir

    def make_result(self, branch="fenix/s1", run_id="impl-s1-1-a1"):
        return AgentRunResult(
            run_id, "s1", "implementer",
            success=True, duration_seconds=1.0, branch=branch,
        )

    def _stub_gate_rerun(self, remaining=None):
        """mock 守卫 gate 重跑：remaining 为重跑后的缺件列表（空=全清）。"""
        self.engine._verification._deliverable_gate_missing = mock.MagicMock(
            return_value=remaining or [],
        )

    def _stub_candidate_on_branch(self, present: bool):
        """mock file_exists_on_branch：present=True 时任意候选判定在分支存在。"""
        self.runner.worktree_manager.file_exists_on_branch.return_value = present

    def _read_audit_records(self):
        audit_path = self.project_root / ".fenix" / "dispute_audits.jsonl"
        if not audit_path.exists():
            return []
        with open(audit_path, encoding="utf-8") as f:
            return [json.loads(ln) for ln in f if ln.strip()]


# ══════════════════════════════════════════════════════════════════════════════
# TestPreclassifyDrift：_preclassify_drift 调度器集成（3.1）
# ══════════════════════════════════════════════════════════════════════════════

class TestPreclassifyDrift(_DriftDispatchFixture):
    """漂移机械对齐裁决行为：改写/凭据登记/解阻/审计/fail-open 全链。"""

    def test_drift_unique_align_rewrite_proceed(self):
        """3.1 核心路径：唯一候选 → 改写生效声明 + 审计 + gate 全清 → proceed。"""
        self.make_drift_branch(
            "core/worktree_manager.py",
            "core/worktree_manager/mergeback.py",
        )
        spec_dir = self.write_spec_dir(
            "- path: core/worktree_manager.py\n  kind: modify\n",
        )
        self._stub_candidate_on_branch(True)
        self._stub_gate_rerun(remaining=[])
        result = self.make_result()
        missing = [
            {"path": "core/worktree_manager.py", "kind": "modify", "violation": "missing"}
        ]
        disputed = ["core/worktree_manager.py"]
        outcome = self.dispatcher._preclassify_drift(
            "s1", result, {}, disputed, missing,
        )
        self.assertEqual(
            outcome["action"], "proceed", f"唯一候选机械对齐应放行: {outcome}"
        )
        # 生效声明（主树 spec 目录）声明段已改写为新落点（kind 保持）
        text = (spec_dir / "tasks.md").read_text(encoding="utf-8")
        self.assertIn(
            "path: core/worktree_manager/mergeback.py", text,
            "声明段应被机械改写为新落点",
        )
        self.assertIn("kind: modify", text, "kind 应保持不变")
        self.assertNotIn(
            "- path: core/worktree_manager.py\n", text, "旧单文件路径应被替换",
        )
        # spec 状态已置 implementing（gate 全清分支设定）
        entry = self.sm.read_one("s1")
        self.assertEqual(entry["status"], "implementing")
        self.assertIsNone(entry.get("error"))

    def test_drift_audit_relocation_verdict(self):
        """3.1 审计留痕：type=relocation + verdict=drift-aligned + actual_path。"""
        self.make_drift_branch(
            "core/worktree_manager.py",
            "core/worktree_manager/mergeback.py",
        )
        self.write_spec_dir(
            "- path: core/worktree_manager.py\n  kind: modify\n",
        )
        self._stub_candidate_on_branch(True)
        self._stub_gate_rerun(remaining=[])
        result = self.make_result()
        missing = [
            {"path": "core/worktree_manager.py", "kind": "modify", "violation": "missing"}
        ]
        self.dispatcher._preclassify_drift(
            "s1", result, {}, ["core/worktree_manager.py"], missing,
        )
        records = self._read_audit_records()
        relocs = [
            r for r in records
            if r.get("type") == "relocation"
            and r.get("old_path") == "core/worktree_manager.py"
            and r.get("new_path") == "core/worktree_manager/mergeback.py"
        ]
        self.assertTrue(
            len(relocs) >= 1,
            f"应至少有一条 relocation 审计记录，实际: {records}",
        )
        v0 = relocs[0]["verdicts"][0]
        self.assertEqual(v0["verdict"], "drift-aligned")
        self.assertEqual(v0["element"], "core/worktree_manager.py")
        self.assertEqual(v0["actual_path"], "core/worktree_manager/mergeback.py")
        self.assertIn("drift-aligned", v0.get("reasoning", ""))
        # 候选唯一性证据落册（history_hits / merge_base / candidates）
        self.assertIn("history_hits", relocs[0])
        self.assertIn("merge_base", relocs[0])
        self.assertIn("candidates", relocs[0])
        # before/after diff 非单调（含声明段全文）
        diff = relocs[0].get("diff", {}).get("core/worktree_manager.py", {})
        self.assertIn("before", diff)
        self.assertIn("after", diff)

    def test_drift_rewrite_committed(self):
        """对齐改写后立即提交生效声明（防 merge-back dirty 死锁）。"""
        self.make_drift_branch(
            "core/worktree_manager.py",
            "core/worktree_manager/mergeback.py",
        )
        self.write_spec_dir(
            "- path: core/worktree_manager.py\n  kind: modify\n",
        )
        self._stub_candidate_on_branch(True)
        self._stub_gate_rerun(remaining=[])
        result = self.make_result()
        missing = [
            {"path": "core/worktree_manager.py", "kind": "modify", "violation": "missing"}
        ]
        self.dispatcher._preclassify_drift(
            "s1", result, {}, ["core/worktree_manager.py"], missing,
        )
        proc = _git(
            self.project_root,
            "log", "--oneline", "-1", "--", "spec/changes/s1/tasks.md",
            check=False,
        )
        self.assertEqual(
            proc.returncode, 0, "tasks.md 应已被提交（防 merge-back dirty 死锁）",
        )
        self.assertIn("声明段", proc.stdout, "提交消息应表明声明段改写")
        status = _git(
            self.project_root, "status", "--short", "--",
            "spec/changes/s1/tasks.md", check=False,
        )
        self.assertEqual(status.stdout.strip(), "", "tasks.md 不应残留未提交改动")

    def test_drift_zero_candidates_fallback(self):
        """零候选 → fail-open：声明不改写、维持 blocked 待人工（fallback）。"""
        self.make_drift_branch("core/worker.py", "core/unrelated.py")
        spec_dir = self.write_spec_dir(
            "- path: core/worker.py\n  kind: modify\n",
        )
        self._stub_candidate_on_branch(True)
        result = self.make_result()
        missing = [{"path": "core/worker.py", "kind": "modify", "violation": "missing"}]
        outcome = self.dispatcher._preclassify_drift(
            "s1", result, {}, ["core/worker.py"], missing,
        )
        self.assertEqual(
            outcome["action"], "fallback", "零候选应 fail-open 回人工",
        )
        text = (spec_dir / "tasks.md").read_text(encoding="utf-8")
        self.assertIn("- path: core/worker.py\n", text, "声明不应被改写")

    def test_drift_multiple_candidates_fallback(self):
        """多候选 → fail-open：不机械改写（唯一性前提不满足）。"""
        self.make_drift_branch(
            "core/pm_engine/dispatch.py",
            "core/pm_engine/dispatch/adjudication.py",
        )
        _git(self.project_root, "checkout", "-q", "fenix/s1")
        (self.project_root / "core" / "pm_engine" / "dispatch" / "queue.py").write_text(
            "y\n", encoding="utf-8",
        )
        _git(self.project_root, "add", "-A")
        _git(self.project_root, "commit", "-q", "-m", "second module")
        _git(self.project_root, "checkout", "-q", self.main_branch)
        spec_dir = self.write_spec_dir(
            "- path: core/pm_engine/dispatch.py\n  kind: modify\n",
        )
        self._stub_candidate_on_branch(True)
        result = self.make_result()
        missing = [
            {"path": "core/pm_engine/dispatch.py", "kind": "modify", "violation": "missing"}
        ]
        outcome = self.dispatcher._preclassify_drift(
            "s1", result, {}, ["core/pm_engine/dispatch.py"], missing,
        )
        self.assertEqual(
            outcome["action"], "fallback", "多候选应 fail-open 回人工",
        )
        text = (spec_dir / "tasks.md").read_text(encoding="utf-8")
        self.assertIn("- path: core/pm_engine/dispatch.py\n", text, "声明不应被改写")

    def test_drift_candidate_not_on_branch_fallback(self):
        """候选不在分支 HEAD（mock 判定不存在）→ 回人工（防「改声明≠交付物」）。"""
        self.make_drift_branch(
            "core/worktree_manager.py",
            "core/worktree_manager/mergeback.py",
        )
        spec_dir = self.write_spec_dir(
            "- path: core/worktree_manager.py\n  kind: modify\n",
        )
        self._stub_candidate_on_branch(False)
        result = self.make_result()
        missing = [
            {"path": "core/worktree_manager.py", "kind": "modify", "violation": "missing"}
        ]
        outcome = self.dispatcher._preclassify_drift(
            "s1", result, {}, ["core/worktree_manager.py"], missing,
        )
        self.assertEqual(
            outcome["action"], "fallback",
            "候选不在分支 HEAD 应回人工",
        )
        text = (spec_dir / "tasks.md").read_text(encoding="utf-8")
        self.assertIn("- path: core/worktree_manager.py\n", text, "声明不应被改写")

    def test_drift_spec_dir_none_registers_credential(self):
        """spec_dir=None（分支来源，无落盘位置）→ 凭据登记，MUST NOT 直写主树。"""
        branch_tasks = (
            "# Tasks\n\n## Deliverables\n\n```yaml\n"
            "- path: core/worktree_manager.py\n  kind: modify\n```\n"
            "## 1. x\n- [ ] 1.1 do\n"
        )
        self.make_drift_branch(
            "core/worktree_manager.py",
            "core/worktree_manager/mergeback.py",
            extra_branch_files={
                "spec/changes/s1/tasks.md": branch_tasks,
            },
        )
        # 主树 spec 目录不写 tasks.md（生效声明来源 = 分支版本，spec_dir=None）
        self._stub_candidate_on_branch(True)
        self._stub_gate_rerun(remaining=[])
        result = self.make_result()
        missing = [
            {"path": "core/worktree_manager.py", "kind": "modify", "violation": "missing"}
        ]
        outcome = self.dispatcher._preclassify_drift(
            "s1", result, {}, ["core/worktree_manager.py"], missing,
        )
        self.assertEqual(
            outcome["action"], "proceed",
            f"分支来源凭据登记 + gate 全清 → 放行: {outcome}",
        )
        # 主树无 spec 目录（未直写主树声明）
        main_tasks = self.project_root / "spec" / "changes" / "s1" / "tasks.md"
        self.assertFalse(
            main_tasks.exists(),
            "分支来源 MUST NOT 直写主树声明（无落盘位置走凭据登记）",
        )
        # 审计含 relocation 凭据（old_path 匹配，无 diff 形态）
        records = self._read_audit_records()
        creds = [
            r for r in records
            if r.get("type") == "relocation"
            and r.get("old_path") == "core/worktree_manager.py"
            and r.get("new_path") == "core/worktree_manager/mergeback.py"
        ]
        self.assertTrue(
            len(creds) >= 1, f"应落重定位凭据审计记录: {records}",
        )
        self.assertIn("source", creds[0])

    def test_drift_disputed_missing_entry_fallback(self):
        """声明段无该条目（缺件来自正则回退）→ 无从改写，fallback 回人工。"""
        self.make_drift_branch(
            "core/worktree_manager.py",
            "core/worktree_manager/mergeback.py",
        )
        self.write_spec_dir(
            "- path: core/other.py\n  kind: modify\n",
        )
        self._stub_candidate_on_branch(True)
        result = self.make_result()
        missing = [
            {"path": "core/worktree_manager.py", "kind": "modify", "violation": "missing"}
        ]
        outcome = self.dispatcher._preclassify_drift(
            "s1", result, {}, ["core/worktree_manager.py"], missing,
        )
        self.assertEqual(
            outcome["action"], "fallback",
            "声明段无该条目 → fallback 回人工",
        )

    def test_drift_continue_with_remaining(self):
        """对齐后仍有缺件 → continue（remaining 供调用方续走 blocked/终审）。"""
        self.make_drift_branch(
            "core/worktree_manager.py",
            "core/worktree_manager/mergeback.py",
        )
        self.write_spec_dir(
            "- path: core/worktree_manager.py\n  kind: modify\n",
        )
        self._stub_candidate_on_branch(True)
        # gate 重跑仍报另一项缺件（无异议 → 交 LLM 终审）
        self._stub_gate_rerun(
            remaining=[{"path": "core/still_missing.py", "kind": "new", "violation": "missing"}],
        )
        result = self.make_result()
        missing = [
            {"path": "core/worktree_manager.py", "kind": "modify", "violation": "missing"}
        ]
        outcome = self.dispatcher._preclassify_drift(
            "s1", result, {}, ["core/worktree_manager.py"], missing,
        )
        self.assertEqual(outcome["action"], "continue")
        self.assertEqual(
            outcome["remaining_missing"],
            [{"path": "core/still_missing.py", "kind": "new", "violation": "missing"}],
        )
        self.assertEqual(
            outcome["remaining_disputed"], [],
            "剩余缺件无异议 → 交既有 LLM 终审",
        )


# ══════════════════════════════════════════════════════════════════════════════
# TestSupersededConvergence：派发前同源草案收敛检查（3.2）
# ══════════════════════════════════════════════════════════════════════════════

class TestSupersededConvergence(_DriftDispatchFixture):
    """同源草案派发拦截：本目录含 SUPERSEDED.md 被阻断、生效落点放行、
    移除 SUPERSEDED.md 后恢复；名字归一仅识别平级同名草案不拦截。"""

    def _make_superseded_layout(self):
        """构造同源草案双目录形态：
        - evo-merge-back-wip-overlap-gate/：含 SUPERSEDED.md（收敛源，点名 -575976）
        - evo-merge-back-wip-overlap-gate-575976/：生效落点（无 SUPERSEDED.md）
        """
        changes = self.project_root / "spec" / "changes"
        gate = changes / "evo-merge-back-wip-overlap-gate"
        gate.mkdir(parents=True, exist_ok=True)
        (gate / "SUPERSEDED.md").write_text(
            "# SUPERSEDED — 已收敛\n\n"
            "## 收敛结论\n\n"
            "- **生效实现落点**：`spec/changes/evo-merge-back-wip-overlap-gate-575976/`\n",
            encoding="utf-8",
        )
        (gate / "tasks.md").write_text(
            "# Tasks\n\n## Deliverables\n\n```yaml\n- path: core/x.py\n  kind: new\n```\n"
            "## 1. x\n- [ ] 1.1 do\n",
            encoding="utf-8",
        )
        (gate / "proposal.md").write_text("# P\n", encoding="utf-8")
        live = changes / "evo-merge-back-wip-overlap-gate-575976"
        live.mkdir(parents=True, exist_ok=True)
        (live / "tasks.md").write_text(
            "# Tasks\n\n## Deliverables\n\n```yaml\n- path: core/y.py\n  kind: new\n```\n"
            "## 1. y\n- [ ] 1.1 do\n",
            encoding="utf-8",
        )
        (live / "proposal.md").write_text("# P\n", encoding="utf-8")
        return gate, live

    def test_convergence_source_blocked_effective_target_passes(self):
        """含 SUPERSEDED.md 一侧被拦截；被显式点名的生效落点正常放行。"""
        gate, live = self._make_superseded_layout()
        r1 = self.engine._check_superseded_convergence(
            "evo-merge-back-wip-overlap-gate"
        )
        self.assertTrue(r1["blocked"], "收敛源（含 SUPERSEDED.md）应被拦截")
        self.assertIn("同源草案收敛义务未满足", r1["error"])
        self.assertIn("SUPERSEDED.md", r1["error"])
        r2 = self.engine._check_superseded_convergence(
            "evo-merge-back-wip-overlap-gate-575976"
        )
        self.assertFalse(
            r2["blocked"],
            "被 SUPERSEDED.md 显式点名的生效落点 MUST NOT 被拦截",
        )
        # 名字归一识别平级同名草案（-575976 与 gate 互为 peers）
        self.assertIn("evo-merge-back-wip-overlap-gate", r2["peers"])
        # 显式点名解析：生效落点被收敛源点名
        self.assertIn(
            "evo-merge-back-wip-overlap-gate", r2["named_by"],
            "显式点名（inline code / 路径形态）应被解析",
        )

    def test_remove_superseded_restores_dispatch(self):
        """收敛完成信号：移除 SUPERSEDED.md 后派发恢复（不再拦截）。"""
        gate, live = self._make_superseded_layout()
        r1 = self.engine._check_superseded_convergence(
            "evo-merge-back-wip-overlap-gate"
        )
        self.assertTrue(r1["blocked"])
        (gate / "SUPERSEDED.md").unlink()
        r2 = self.engine._check_superseded_convergence(
            "evo-merge-back-wip-overlap-gate"
        )
        self.assertFalse(
            r2["blocked"], "SUPERSEDED.md 移除后派发恢复",
        )

    def test_on_spec_ready_blocks_superseded(self):
        """_on_spec_ready 派发 implementer 前拦截：置 blocked、不入队。"""
        gate, live = self._make_superseded_layout()
        self.sm.add_spec("evo-merge-back-wip-overlap-gate", {"priority": 5})
        self.sm.transition("evo-merge-back-wip-overlap-gate", "ready")
        self.runner.worktree_manager.has_active_worktree.return_value = False
        with mock.patch.object(
            self.engine._dispatcher, "_enqueue",
            wraps=self.engine._dispatcher._enqueue,
        ) as enqueue_spy:
            self.engine._on_spec_ready("evo-merge-back-wip-overlap-gate")
        entry = self.sm.read_one("evo-merge-back-wip-overlap-gate")
        self.assertEqual(entry["status"], "blocked", "应置 blocked")
        self.assertIn("同源草案收敛义务未满足", entry["error"])
        enqueue_spy.assert_not_called()

    def test_on_spec_ready_effective_target_dispatches(self):
        """_on_spec_ready 对生效落点正常派发（不被归一误拦）。"""
        gate, live = self._make_superseded_layout()
        self.sm.add_spec("evo-merge-back-wip-overlap-gate-575976", {"priority": 5})
        self.sm.transition("evo-merge-back-wip-overlap-gate-575976", "ready")
        self.runner.worktree_manager.has_active_worktree.return_value = False
        with mock.patch.object(
            self.engine._dispatcher, "_enqueue",
            wraps=self.engine._dispatcher._enqueue,
        ) as enqueue_spy:
            self.engine._on_spec_ready("evo-merge-back-wip-overlap-gate-575976")
        entry = self.sm.read_one("evo-merge-back-wip-overlap-gate-575976")
        self.assertEqual(entry["status"], "ready", "生效落点应保持可派发")
        # （add-verify-lane-throughput 1.1：主车道派发成功后附加一次
        # planner-plan 并行出题车道入队；生效落点语义不变，逐一断言两类调用）
        enqueue_spy.assert_any_call(
            "evo-merge-back-wip-overlap-gate-575976", "implementer"
        )
        enqueue_spy.assert_any_call(
            "evo-merge-back-wip-overlap-gate-575976", "planner-plan"
        )
        self.assertEqual(enqueue_spy.call_count, 2)

    def test_process_queue_superseded_entry_removed_blocked(self):
        """_process_queue 候选筛选同口径兜底：旁路入队的收敛源条目被移除+blocked。"""
        gate, live = self._make_superseded_layout()
        self.sm.add_spec("evo-merge-back-wip-overlap-gate", {"priority": 5})
        self.sm.transition("evo-merge-back-wip-overlap-gate", "ready")
        # 旁路直入队列（不经 _on_spec_ready）
        self.dispatcher._enqueue("evo-merge-back-wip-overlap-gate", "implementer")
        self.assertEqual(len(self.dispatcher._run_queue), 1)
        with mock.patch.object(
            self.engine, "_run_agent_worker",
        ) as worker_spy:
            self.dispatcher._process_queue()
        # 条目已被移除（拦截自己 ≠ 阻塞他人），spec 置 blocked
        self.assertEqual(len(self.dispatcher._run_queue), 0, "被拦截条目应出队")
        entry = self.sm.read_one("evo-merge-back-wip-overlap-gate")
        self.assertEqual(entry["status"], "blocked")
        self.assertIn("同源草案收敛义务未满足", entry["error"])
        # _run_agent_worker 未被启动（拦截在派发前）
        worker_spy.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
