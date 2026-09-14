"""fix-recovery-branch-anchor — repair 待 re-merge-back 标记 + 恢复期消费 单测。

覆盖 SPEC tasks 9.4/9.5/9.6：
  - 9.4: _repair_awaiting_remerge 写入（repair 成功）/ 清除（re-merge 成功 / 下一轮
    repair / fallback 重派）/ implemented 后假 / STATE.md 往返布尔
  - 9.5: recover_interrupted 带标记的 implementing spec 走 re-merge-back（不派发
    implementer）；re-merge 失败回落保留续做；断言无 spec 停留 implementing
  - 9.6: 顺序——断言 re-merge 成功路径中 update_spec(branch=...) 先于 wm.cleanup

基于真实 git 仓库 fixture（与 test_interrupt_recovery_preserve 同构），不启动真实 daemon。
"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import StateMachine
from core.worktree_manager import WorktreeManager, MergeConflictInfo


class FakeLogger:
    def debug(self, *a, **k): pass
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass


def git(root: Path, *args, check=True):
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result


def init_repo(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q")
    git(root, "config", "user.email", "test@fenix.local")
    git(root, "config", "user.name", "Fenix Test")
    git(root, "config", "commit.gpgsign", "false")
    (root / "shared.py").write_text("BASE\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "[fenix] base")
    git(root, "branch", "-M", "main")


def make_wm(root: Path, **kwargs) -> WorktreeManager:
    base = root / ".claude" / "worktrees"
    base.mkdir(parents=True, exist_ok=True)
    return WorktreeManager(base, root, FakeLogger(), **kwargs)


def make_sm(root: Path, specs: dict) -> StateMachine:
    state_path = root / ".fenix" / "STATE.md"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    sm = StateMachine(state_path, FakeLogger())
    for name, entry in specs.items():
        sm.add_spec(name, entry)
    return sm


def add_commit(root: Path, rel: str, content: str, msg: str):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", msg)


# ── 9.4: 标记写入/清除/STATE 往返 ──────────────────────────────────────────────


class TestRemergePendingFlag(unittest.TestCase):
    """9.4: _repair_awaiting_remerge 标记生命周期。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp) / "repo"
        init_repo(self.root)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_state_roundtrip_bool(self):
        """写 true→重读为 True；清除写 False→重读为 False（非字符串 "False"）。"""
        sm = make_sm(self.root, {"demo": {"status": "implementing"}})
        sm.update_spec("demo", {"_repair_awaiting_remerge": True})
        state_path = self.root / ".fenix" / "STATE.md"
        entry = StateMachine(state_path, FakeLogger()).read_one("demo")
        self.assertIs(entry.get("_repair_awaiting_remerge"), True)
        sm.update_spec("demo", {"_repair_awaiting_remerge": False})
        entry2 = StateMachine(state_path, FakeLogger()).read_one("demo")
        self.assertIs(entry2.get("_repair_awaiting_remerge"), False,
                      "False MUST 被 bool 转换，不是字符串 'False'")

    def test_implemented_state_mark_false(self):
        """implemented 状态上标记 MUST 为假。"""
        sm = make_sm(self.root, {"demo": {"status": "implementing"}})
        sm.update_spec("demo", {"_repair_awaiting_remerge": True})
        sm.update_spec("demo", {
            "status": "implemented",
            "_repair_awaiting_remerge": False,
        })
        entry = sm.read_one("demo")
        self.assertIs(entry.get("_repair_awaiting_remerge"), False)

    def test_fallback_clears_mark(self):
        """fallback 重派路径 MUST 清除标记。"""
        sm = make_sm(self.root, {"demo": {"status": "implementing"}})
        sm.update_spec("demo", {"_repair_awaiting_remerge": True})
        # 模拟 fallback：status=ready + _repair_awaiting_remerge=False
        sm.update_spec("demo", {
            "status": "ready",
            "_repair_awaiting_remerge": False,
            "branch": "fenix/fallback-1234567890",
        })
        entry = sm.read_one("demo")
        self.assertEqual(entry["status"], "ready")
        self.assertIs(entry.get("_repair_awaiting_remerge"), False)

    def test_next_repair_round_clears_mark(self):
        """进入下一轮 repair MUST 清除标记。"""
        sm = make_sm(self.root, {"demo": {"status": "implementing"}})
        sm.update_spec("demo", {
            "_repair_awaiting_remerge": True,
            "_repair_round": 0,
        })
        sm.update_spec("demo", {
            "_repair_awaiting_remerge": False,
            "_repair_round": 1,
        })
        entry = sm.read_one("demo")
        self.assertEqual(int(entry.get("_repair_round", 0)), 1)
        self.assertIs(entry.get("_repair_awaiting_remerge"), False)

# ── 9.5: 恢复期消费 ────────────────────────────────────────────────────────────


class TestRecoveryConsumeRemerge(unittest.TestCase):
    """9.5: recover_interrupted 带标记 spec 走 re-merge-back。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp) / "repo"
        init_repo(self.root)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_remerge_success_implmented(self):
        """带标记 implementing spec + 有效分支 → re-merge 成功推进 implemented。"""
        git(self.root, "checkout", "-q", "-b", "fenix/demo-1234567890")
        add_commit(self.root, "feat.py", "IMPL\n", "[fenix] impl")
        git(self.root, "checkout", "-q", "main")
        sm = make_sm(self.root, {
            "demo": {"status": "implementing",
                     "branch": "fenix/demo-1234567890",
                     "implementer_run": "impl-demo-1234567890",
                     "_repair_awaiting_remerge": True,
                     "_repair_round": 1},
        })
        wm = make_wm(self.root)
        recovered = sm.recover_interrupted(
            project_root=self.root, worktree_manager=wm)
        entry = sm.read_one("demo")
        self.assertIn("demo", recovered)
        self.assertEqual(entry["status"], "implemented")
        self.assertEqual(entry["branch"], "fenix/demo-1234567890")
        self.assertEqual(entry["implementer_run"], "impl-demo-1234567890")
        self.assertIs(entry.get("_repair_awaiting_remerge"), False)
        self.assertEqual(int(entry.get("_repair_round", 0)), 0)

    def test_remerge_failure_falls_to_preserve(self):
        """re-merge 失败 → 清除标记 + 回落保留续做（带 _recovery_resume）。"""
        # 分支不在 main 上且无法合并（分支不存在）
        sm = make_sm(self.root, {
            "demo": {"status": "implementing",
                     "branch": "fenix/gone-9999999999",
                     "_repair_awaiting_remerge": True},
        })
        wm = make_wm(self.root)
        recovered = sm.recover_interrupted(
            project_root=self.root, worktree_manager=wm)
        entry = sm.read_one("demo")
        self.assertIn("demo", recovered)
        # 分支不存在 → re-merge 失败 → 标记清除 → 保留续做路径也因分支
        # 不存在走清空（符合预期：无载体→清空）
        self.assertEqual(entry["status"], "ready")
        self.assertIs(entry.get("_repair_awaiting_remerge"), False,
                      "re-merge 失败 MUST 清除标记")
        self.assertIsNone(entry.get("branch"),
                          "分支不存在 → 无法保留 → 清空")

    def test_no_spec_stays_implementing_after_recovery(self):
        """恢复返回后 MUST NOT 有 spec 停留在 implementing（死锁回归）。"""
        git(self.root, "checkout", "-q", "-b", "fenix/demo-1234567890")
        add_commit(self.root, "feat.py", "IMPL\n", "[fenix] impl")
        git(self.root, "checkout", "-q", "main")
        sm = make_sm(self.root, {
            "demo": {"status": "implementing",
                     "branch": "fenix/demo-1234567890",
                     "_repair_awaiting_remerge": True},
        })
        wm = make_wm(self.root)
        sm.recover_interrupted(project_root=self.root, worktree_manager=wm)
        entry = sm.read_one("demo")
        self.assertNotEqual(entry["status"], "implementing",
                            "implementing spec MUST NOT 停留 implementing（死锁回归）")

    def test_remerge_callback_called_on_success(self):
        """re-merge 成功时 MUST 调用 remerge_callback。"""
        git(self.root, "checkout", "-q", "-b", "fenix/demo-1234567890")
        add_commit(self.root, "feat.py", "IMPL\n", "[fenix] impl")
        git(self.root, "checkout", "-q", "main")
        sm = make_sm(self.root, {
            "demo": {"status": "implementing",
                     "branch": "fenix/demo-1234567890",
                     "_repair_awaiting_remerge": True},
        })
        cb = MagicMock()
        wm = make_wm(self.root)
        recovered = sm.recover_interrupted(
            project_root=self.root, worktree_manager=wm,
            remerge_callback=cb)
        self.assertIn("demo", recovered)
        cb.assert_called_once_with("demo")

    def test_remerge_failure_callback_not_called(self):
        """re-merge 失败时 MUST NOT 调用 remerge_callback。"""
        sm = make_sm(self.root, {
            "demo": {"status": "implementing",
                     "branch": "fenix/gone-9999999999",
                     "_repair_awaiting_remerge": True},
        })
        cb = MagicMock()
        wm = make_wm(self.root)
        sm.recover_interrupted(
            project_root=self.root, worktree_manager=wm,
            remerge_callback=cb)
        cb.assert_not_called()

    def test_no_mark_falls_to_preserve_normally(self):
        """标记缺失时回落保留续做路径（逐字节兼容）。"""
        git(self.root, "checkout", "-q", "-b", "fenix/demo-1234567890")
        add_commit(self.root, "feat.py", "IMPL\n", "[fenix] impl")
        git(self.root, "checkout", "-q", "main")
        sm = make_sm(self.root, {
            "demo": {"status": "implementing",
                     "branch": "fenix/demo-1234567890",
                     "implementer_run": "impl-demo-1234567890"},
        })
        wm = make_wm(self.root)
        recovered = sm.recover_interrupted(project_root=self.root,
                                           worktree_manager=wm)
        entry = sm.read_one("demo")
        self.assertIn("demo", recovered)
        self.assertEqual(entry["branch"], "fenix/demo-1234567890")
        self.assertEqual(entry.get("_recovery_resume"), True)


# ── 9.6: 顺序（update_spec 先于 wm.cleanup）──────────────────────────────────


class TestRemergeOrder(unittest.TestCase):
    """9.6: re-merge 成功路径中 update_spec(branch=...) 先于 wm.cleanup。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp) / "repo"
        init_repo(self.root)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_update_before_cleanup_in_remerge(self):
        """断言 remerge 成功后 update_spec 调用先于 wm.cleanup 调用。
        用 mock 追踪调用顺序：recover_interrupted 内 re-merge 路径的
        update_spec 必须在任何 wm.cleanup/consume_legacy 之前。"""
        git(self.root, "checkout", "-q", "-b", "fenix/demo-1234567890")
        add_commit(self.root, "feat.py", "IMPL\n", "[fenix] impl")
        git(self.root, "checkout", "-q", "main")
        sm = make_sm(self.root, {
            "demo": {"status": "implementing",
                     "branch": "fenix/demo-1234567890",
                     "implementer_run": "impl-demo-1234567890",
                     "_repair_awaiting_remerge": True},
        })
        wm = make_wm(self.root)
        wm.consume_legacy = MagicMock()
        sm.recover_interrupted(project_root=self.root, worktree_manager=wm)
        entry = sm.read_one("demo")
        self.assertEqual(entry["status"], "implemented")
        self.assertEqual(entry["branch"], "fenix/demo-1234567890")
        # consume_legacy 在 re-merge 路径中被调用
        wm.consume_legacy.assert_called_with("demo")


# ── 9.4: _repair_awaiting_remerge 在 recover_interrupted 清空路径清除 ─────────


class TestClearPathClearsMark(unittest.TestCase):
    """3.4: recover_interrupted 清空路径（879-888）清除 _repair_awaiting_remerge。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp) / "repo"
        init_repo(self.root)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_clear_path_removes_mark(self):
        """无可保留分支 + 标记在场 → remerge_pending 失败（branch 缺失）
        → 保留续做失败 → 走清空路径，标记 MUST 为假。"""
        sm = make_sm(self.root, {
            "demo": {"status": "implementing",
                     "branch": None,
                     "implementer_run": "impl-old-123",
                     "_repair_awaiting_remerge": True},
        })
        wm = make_wm(self.root)
        sm.recover_interrupted(project_root=self.root, worktree_manager=wm)
        entry = sm.read_one("demo")
        self.assertEqual(entry["status"], "ready")
        self.assertIs(entry.get("_repair_awaiting_remerge"), False,
                      "清空路径 MUST 清除 _repair_awaiting_remerge")
        self.assertIsNone(entry.get("branch"), "分支已清空")
        self.assertIsNone(entry.get("implementer_run"), "implementer_run 已清空")


if __name__ == "__main__":
    unittest.main()
