"""四条打回路径遗产登记一致性测试（fix-relint-redispatch-legacy 2.3/2.4）。

以「遗产在册 + ``_take_reusable_worktree`` 可认领」为可观测判据（design D4），
逐条断言适用打回路径（交付物守卫缺件打回、tasks.md relint 违规打回）登记了
**可认领**的分支遗产——不断言「调用了某函数」，使实现重构不破坏断言语义。

2.4 继承链端到端：relint 打回后，下一次 ``worktree_manager.create(spec,
"implementer")`` 经 ``_take_reusable_worktree`` 认领**同一分支**（MUST NOT
新建 worktree、MUST NOT 从 main 起新分支），继承首轮已提交成果。

夹具形态：真实 git 仓库 + 真实 WorktreeManager + 真实 PMEngine（同
test_transient_backoff.py 的 reuse 认领测试同构），首轮 run 提交实现 → 成功
收工清理（worktree 物理删除、分支留存）→ 触达打回路径 → 断言遗产可认领。
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.state_machine import StateMachine
from core.worktree_manager import WorktreeManager

RELINT_VIOLATION = (
    "tasks.md 存在任务分组（2 个），但未解析出任何任务行——任务行必须为 "
    "`- [ ] <编号>. <任务>` / `- [x] <编号>. <任务>` 行首形态"
)


def _init_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email",
                    "test@fenix.local"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name",
                    "Fenix Test"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "commit.gpgsign",
                    "false"], check=True)
    (root / "base.py").write_text("BASE\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m",
                    "[fenix] base"], check=True)
    subprocess.run(["git", "-C", str(root), "branch", "-M", "main"], check=True)
    (root / ".claude" / "worktrees").mkdir(parents=True, exist_ok=True)


def _commit_in_wt(wt: Path, fname: str, content: str, msg: str) -> None:
    full = wt / fname
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")
    subprocess.run(["git", "-C", str(wt), "add", fname], check=True)
    subprocess.run(["git", "-C", str(wt), "commit", "-q", "-m", msg], check=True)


class _SuccessionBase(unittest.TestCase):
    """真实 git 仓库 + 真实 WorktreeManager + 真实 PMEngine 的共用夹具。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        (self.tmpdir / ".fenix").mkdir(exist_ok=True)
        self.logger = MagicMock()
        _init_repo(self.tmpdir)
        self.sm = StateMachine(self.tmpdir / ".fenix" / "STATE.md", self.logger)
        from core.pm_engine import PMEngine
        self.engine = PMEngine(self.sm, MagicMock(), {}, self.tmpdir, self.logger)
        self.wm = WorktreeManager(
            self.tmpdir / ".claude" / "worktrees", self.tmpdir, self.logger)
        self.engine.agent_runner.worktree_manager = self.wm
        self.dispatcher = self.engine._dispatcher
        self.dispatcher._enqueue_front = MagicMock()
        self.sm.add_spec("demo", {"priority": 5})
        self.sm.transition("demo", "implementing")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _round_one_committed_branch(self) -> str:
        """第一轮原型：create worktree → 提交实现 → 成功收工清理（仅分支留存）。

        与 full 车道「run 成功收工后 worktree 已被 cleanup(success=True) 物理
        清理、仅分支留存完整已提交成果」的形态一致。
        """
        wt = self.wm.create("demo", "implementer")
        self.assertIsNotNone(wt)
        branch = self.wm.get_branch_name(wt)
        self.assertIsNotNone(branch)
        _commit_in_wt(wt, "core/real.py", "REAL\n", "[fenix] demo: 首轮实现")
        self.wm.cleanup(wt, success=True)
        self.assertEqual(self.wm.find_worktree_path(branch), None,
                         "成功收工后 worktree 应已物理清理")
        return branch

    def _assert_claimable_branch_legacy(self, branch: str) -> Path:
        """design D4 可观测判据：遗产在册 + _take_reusable_worktree 可认领。"""
        rec = self.wm.get_legacy("demo")
        self.assertIsNotNone(rec, "适用打回路径应登记分支遗产")
        self.assertEqual(rec["path"], "", "full 车道成功收工后应为仅分支模式")
        self.assertEqual(rec["branch"], branch)
        self.assertTrue(self.wm._legacy["demo"]["reuse"],
                        "仅分支遗产须置 reuse 才可被 _take_reusable_worktree 认领")
        taken = self.wm._take_reusable_worktree("demo")
        self.assertIsNotNone(taken, "遗产在册且应可被 _take_reusable_worktree 认领")
        wt2, claimed_branch = taken
        self.assertEqual(claimed_branch, branch, "认领应落在同一分支")
        self.assertTrue((wt2 / "core" / "real.py").exists(),
                        "认领的载体应继承首轮已提交成果")
        return wt2


class TestRedispatchPathsRegisterClaimableLegacy(_SuccessionBase):
    """Task 2.3 — 适用打回路径一致登记可认领的分支遗产（防同类缺口再现）。

    逐条断言（非「调用了某函数」）：打回处置后遗产在册、reuse 为真、
    ``_take_reusable_worktree`` 能在既有分支上重建载体认领。
    """

    def test_deliverable_gate_missing_path(self):
        """交付物守卫缺件打回（既有路径）：遗产在册且可认领。"""
        branch = self._round_one_committed_branch()
        result = SimpleNamespace(branch=branch, run_id="impl-1", success=True)
        self.dispatcher._redispatch_for_missing("demo", result, [
            {"path": "core/real.py", "kind": "new", "violation": "missing"},
        ])
        self._assert_claimable_branch_legacy(branch)
        entry = self.sm.read_one("demo")
        self.assertEqual(entry["status"], "ready")
        self.assertEqual(int(entry["_retry_count"]), 1)

    def test_relint_path(self):
        """tasks.md relint 违规打回（本变更补齐）：遗产在册且可认领。"""
        branch = self._round_one_committed_branch()
        self.dispatcher._redispatch_tasks_relint(
            "demo", [RELINT_VIOLATION], run_id="impl-1", branch=branch)
        self._assert_claimable_branch_legacy(branch)
        entry = self.sm.read_one("demo")
        self.assertEqual(entry["status"], "ready")
        self.assertIn("tasks.md 收口复检违规", entry["error"])


class TestSuccessionChainCreateClaimsSameBranch(_SuccessionBase):
    """Task 2.4 — 继承链端到端：create 认领同一分支，不从 main 起新分支。"""

    def test_create_inherits_same_branch_after_relint(self):
        """relint 打回 → 下一轮 create 经 _take_reusable_worktree 认领同一分支。

        断言：认领后的分支名 == 首轮分支（MUST NOT 新建 worktree、MUST NOT
        从 main 起新分支），首轮已提交成果在继承载体中，认领后遗产摘出。
        """
        branch = self._round_one_committed_branch()
        self.dispatcher._redispatch_tasks_relint(
            "demo", [RELINT_VIOLATION], run_id="impl-1", branch=branch)

        wt2 = self.wm.create("demo", "implementer")
        self.assertIsNotNone(wt2)
        claimed = self.wm.get_branch_name(wt2)
        self.assertEqual(claimed, branch,
                         "MUST 认领同一分支，不得从 main 起新分支")
        self.assertIn(branch, subprocess.run(
            ["git", "-C", str(self.tmpdir), "branch", "--list", "fenix/*"],
            capture_output=True, text=True).stdout,
            "首轮分支应仍存在（未因重派被清除）")
        self.assertTrue((wt2 / "core" / "real.py").exists(),
                        "首轮已提交成果应在继承载体中")
        self.assertIsNone(self.wm.get_legacy("demo"),
                          "认领后遗产应从 _legacy 摘出（转 _active_reuse）")
        # 继承载体确实落在首轮分支上（git 事实复核）
        head_branch = subprocess.run(
            ["git", "-C", str(wt2), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True).stdout.strip()
        self.assertEqual(head_branch, branch)

    def test_deliverable_gate_chain_claims_same_branch(self):
        """交付物守卫缺件打回 → 下一轮 create 同样认领同一分支（一致性）。"""
        branch = self._round_one_committed_branch()
        result = SimpleNamespace(branch=branch, run_id="impl-1", success=True)
        self.dispatcher._redispatch_for_missing("demo", result, [
            {"path": "core/real.py", "kind": "new", "violation": "missing"},
        ])
        wt2 = self.wm.create("demo", "implementer")
        self.assertIsNotNone(wt2)
        self.assertEqual(self.wm.get_branch_name(wt2), branch)


if __name__ == "__main__":
    unittest.main(verbosity=2)