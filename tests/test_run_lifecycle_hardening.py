"""
Tests for run-lifecycle-hardening SPEC.

覆盖四组能力：
1. archive-auto-commit：push 尾部归档收口（残留检测/单 commit/路径限定/失败降级）
2. cli-retry-backoff：秒挂判定与冷却闸门
3. per-agent-timeout-override：run_timeout 按 agent_type 覆盖
4. lifecycle-hygiene：frozen 终止重试链 / STATE 路径唯一 / 预算对账自动校正
"""
import json
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import StateMachine


def make_logger():
    """MagicMock 日志器（记录级别/消息调用）。"""
    return MagicMock()


def git(repo: Path, *args, check=True):
    """在 repo 内执行 git 命令。"""
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=60,
        check=check,
    )


def init_git_repo(repo: Path, initial_files: dict = None):
    """初始化 git 仓库：配置身份 + 初始提交。

    initial_files: {相对路径: 内容}，在首次提交前写入。
    """
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "fenix-test")
    git(repo, "config", "user.email", "fenix-test@example.com")
    for rel, content in (initial_files or {}).items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    if initial_files:
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "initial")
    return repo


def run_file_lines(proot: Path, run_id: str) -> list:
    """读取 .fenix/runs/<run_id>.jsonl 的解析行。"""
    p = proot / ".fenix" / "runs" / f"{run_id}.jsonl"
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def build_engine(proot: Path, config: dict = None):
    """构造最小 PMEngine（真实 state_machine + MagicMock agent_runner）。"""
    from core.pm_engine import PMEngine
    logger = make_logger()
    sm = StateMachine(proot / "STATE.md", logger)
    engine = PMEngine(sm, MagicMock(), config or {}, proot, logger)
    return engine, sm, logger


# ══════════════════════════════════════════════════════════════════════
# 1. archive-auto-commit
# ══════════════════════════════════════════════════════════════════════

class TestArchiveMoveResidue(unittest.TestCase):
    """_archive_move_residue：识别删除侧 + archive 新增侧，忽略无关改动。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        init_git_repo(self.root, {
            "openspec/changes/spec-a/tasks.md": "# T\n",
            "openspec/changes/spec-a/spec.md": "# S\n",
            "openspec/changes/spec-b/spec.md": "# B\n",
            "core/keep.py": "KEEP = 1\n",
        })
        self.engine, self.sm, self.logger = build_engine(self.root)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_detects_archive_move_residue(self):
        # 模拟归档移动：删除 spec-a 目录 + archive 新增
        arch = self.root / "openspec" / "changes" / "archive" / "spec-a-1788451452"
        shutil.move(self.root / "openspec" / "changes" / "spec-a", arch)
        has, names = self.engine._archive_move_residue()
        self.assertTrue(has)
        self.assertIn("spec-a", names)

    def test_detects_archive_added_only(self):
        # 仅 archive 新增（未跟踪）→ 也算残留
        arch = self.root / "openspec" / "changes" / "archive" / "new-spec-1788451452"
        arch.mkdir(parents=True)
        (arch / "spec.md").write_text("# N", encoding="utf-8")
        has, names = self.engine._archive_move_residue()
        self.assertTrue(has)
        self.assertIn("new-spec", names)

    def test_no_residue_clean_tree(self):
        has, names = self.engine._archive_move_residue()
        self.assertFalse(has)
        self.assertEqual(names, [])

    def test_source_modification_not_residue(self):
        # 仅源码修改 → 非归档残留
        (self.root / "core" / "keep.py").write_text("KEEP = 2\n", encoding="utf-8")
        has, names = self.engine._archive_move_residue()
        self.assertFalse(has)
        self.assertEqual(names, [])


class TestArchiveAutoCommit(unittest.TestCase):
    """_archive_auto_commit：单 commit 收口 / 零动作 / 路径限定 / 失败降级。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        init_git_repo(self.root, {
            "openspec/changes/spec-a/tasks.md": "# T\n",
            "openspec/changes/spec-a/spec.md": "# S\n",
            "core/keep.py": "KEEP = 1\n",
        })
        self.engine, self.sm, self.logger = build_engine(self.root)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_commit_and_push_on_residue(self):
        arch = self.root / "openspec" / "changes" / "archive" / "spec-a-1788451452"
        shutil.move(self.root / "openspec" / "changes" / "spec-a", arch)
        # push 用 MagicMock 拦截（不连真实远端）
        self.engine._git_push_ref = MagicMock(return_value=(True, ""))

        self.engine._archive_auto_commit()

        # 产生了一次 push
        self.engine._git_push_ref.assert_called_once_with("main")
        # openspec/ 路径干净（删除已提交、archive 已入库）
        status = git(self.root, "status", "--porcelain").stdout.strip()
        openspec_lines = [
            ln for ln in status.splitlines()
            if "openspec/" in ln
        ]
        self.assertEqual(openspec_lines, [])
        # 源码修改未被卷入
        self.assertNotIn("core/keep.py", status)
        # commit message 正确
        log = git(self.root, "log", "-1", "--pretty=%s").stdout.strip()
        self.assertTrue(log.startswith("[fenix] archive: spec-a 归档入库"))

    def test_no_residue_no_action(self):
        self.engine._git_push_ref = MagicMock(return_value=(True, ""))
        with patch.object(self.engine, "_git_commit", wraps=self.engine._git_commit) as gc:
            self.engine._archive_auto_commit()
        gc.assert_not_called()
        self.engine._git_push_ref.assert_not_called()
        self.assertEqual(
            git(self.root, "rev-list", "--count", "HEAD").stdout.strip(), "1",
        )

    def test_source_changes_not_included(self):
        # 归档残留 + 源码修改同时存在
        arch = self.root / "openspec" / "changes" / "archive" / "spec-a-1788451452"
        shutil.move(self.root / "openspec" / "changes" / "spec-a", arch)
        (self.root / "core" / "keep.py").write_text("KEEP = 99\n", encoding="utf-8")
        self.engine._git_push_ref = MagicMock(return_value=(True, ""))

        self.engine._archive_auto_commit()

        # commit 只含 openspec/changes 路径
        files = git(self.root, "show", "--name-only", "--pretty=format:",
                    "HEAD").stdout.splitlines()
        files = [f for f in files if f.strip()]
        self.assertNotEqual(files, [])
        for f in files:
            self.assertTrue(f.startswith("openspec/changes/"), f)
        # 源码改动仍留在工作区
        self.assertIn("core/keep.py",
                      git(self.root, "status", "--porcelain").stdout)

    def test_commit_failure_warns_and_continues(self):
        """commit 失败 → WARNING + 不抛异常（spec 终态不受影响）。"""
        arch = self.root / "openspec" / "changes" / "archive" / "spec-a-1788451452"
        shutil.move(self.root / "openspec" / "changes" / "spec-a", arch)
        with patch.object(
            self.engine, "_git_commit", return_value=(False, "hook refused")
        ) as gc, patch.object(
            self.engine, "_git_push_ref", wraps=self.engine._git_push_ref
        ) as gp:
            # 不抛异常
            self.engine._archive_auto_commit()
        gc.assert_called_once()
        # commit 失败 → 不 push
        gp.assert_not_called()
        warnings = [str(c) for c in self.logger.warning.call_args_list]
        self.assertTrue(any("归档收口 commit 失败" in w for w in warnings))

    def test_push_failure_warns(self):
        """commit 成功但 push 失败 → WARNING（残留已本地入库）。"""
        arch = self.root / "openspec" / "changes" / "archive" / "spec-a-1788451452"
        shutil.move(self.root / "openspec" / "changes" / "spec-a", arch)
        self.engine._git_push_ref = MagicMock(
            return_value=(False, "remote rejected"))
        self.engine._archive_auto_commit()
        warnings = [str(c) for c in self.logger.warning.call_args_list]
        self.assertTrue(any("归档收口 push 失败" in w for w in warnings))
        # 即使 push 失败，commit 已完成（残留不重发）
        self.assertEqual(
            git(self.root, "rev-list", "--count", "HEAD").stdout.strip(), "2",
        )

    def test_approve_push_calls_archive_commit(self):
        """approve_push 尾部调用归档收口（main push 成功后）。"""
        self.sm.add_spec("done-spec", {"status": "done", "priority": 5})
        # main push 成功 + 分支尽力（本地分支不存在跳过）→ 归档收口被调用
        self.engine._git_push_ref = MagicMock(return_value=(True, ""))
        self.engine._resolve_push_branch = MagicMock(return_value="fenix/done-spec")
        self.engine._push_branch_best_effort = MagicMock()
        with patch.object(self.engine, "_archive_auto_commit") as aac:
            ok = self.engine.approve_push("done-spec")
        self.assertTrue(ok)
        aac.assert_called_once()
        self.assertEqual(
            (self.sm.read_one("done-spec") or {}).get("status"), "pushed")


# ══════════════════════════════════════════════════════════════════════
# 2. cli-retry-backoff（秒挂判定、冷却闸门、告警、正交性）
# ══════════════════════════════════════════════════════════════════════

def make_runner_with_config(proot, config, sm=None, logger=None):
    """构造最小 AgentRunner（__new__ 绕过 __init__），配置注入 + 秒挂表。"""
    from core.agent_runner import AgentRunner
    runner = AgentRunner.__new__(AgentRunner)
    runner.config = config or {}
    runner.worktree_manager = MagicMock()
    runner.state_machine = sm
    runner.project_root = proot
    runner.logger = logger or make_logger()
    runner._running_agents = {}
    runner._instant_fail = {}
    return runner


class TestInstantFailBackoffCore(unittest.TestCase):
    """runner 侧秒挂分类：计数、冷却、重置、告警。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        (self.root / ".fenix" / "runs").mkdir(parents=True)
        self.logger = make_logger()
        self.runner = make_runner_with_config(self.root, {
            "agents": {"instant_fail_threshold_seconds": 60,
                       "instant_fail_cooldown_after": 3,
                       "instant_fail_cooldown_seconds": 300},
        }, logger=self.logger)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_seconds_under_threshold_counted(self):
        self.runner._record_instant_fail("spec-x", duration_seconds=5)
        self.assertEqual(self.runner._instant_fail_counts("spec-x"), 1)
        self.assertFalse(self.runner.is_instant_fail_cooldown("spec-x"))

    def test_cooldown_triggered_after_threshold(self):
        for _ in range(3):
            self.runner._record_instant_fail("spec-x", duration_seconds=5)
        self.assertTrue(self.runner.is_instant_fail_cooldown("spec-x"))
        self.assertEqual(self.runner._instant_fail_counts("spec-x"), 3)

    def test_success_resets_counter_and_cooldown(self):
        for _ in range(3):
            self.runner._record_instant_fail("spec-x", duration_seconds=5)
        self.assertTrue(self.runner.is_instant_fail_cooldown("spec-x"))
        self.runner._reset_instant_fail("spec-x")
        self.assertEqual(self.runner._instant_fail_counts("spec-x"), 0)
        self.assertFalse(self.runner.is_instant_fail_cooldown("spec-x"))

    def test_survived_failure_resets_counter(self):
        """存活超阈值失败 = 非秒挂：重置连续计数（design D2）。"""
        self.runner._record_instant_fail("spec-x", duration_seconds=5)
        self.runner._record_instant_fail("spec-x", duration_seconds=700)
        self.assertEqual(self.runner._instant_fail_counts("spec-x"), 0)
        self.assertFalse(self.runner.is_instant_fail_cooldown("spec-x"))

    def test_interrupted_run_not_counted(self):
        """框架主动 SIGTERM（产物含 interrupted 标记）不计入秒挂。"""
        run_file = self.root / ".fenix" / "runs" / "impl-spec-x-1-a1.jsonl"
        run_file.write_text(
            '{"type":"interrupted","reason":"daemon shutdown"}\n',
            encoding="utf-8",
        )
        self.runner._record_instant_fail(
            "spec-x", duration_seconds=3, run_file=run_file)
        self.assertEqual(self.runner._instant_fail_counts("spec-x"), 0)

    def test_non_consecutive_resets(self):
        """秒挂 → 成功 → 再秒挂：计数不跨成功累积。"""
        self.runner._record_instant_fail("spec-x", duration_seconds=5)
        self.runner._record_instant_fail("spec-x", duration_seconds=5)
        self.runner._reset_instant_fail("spec-x")
        self.runner._record_instant_fail("spec-x", duration_seconds=5)
        self.assertEqual(self.runner._instant_fail_counts("spec-x"), 1)

    def test_cooldown_expires_auto_recovers(self):
        for _ in range(3):
            self.runner._record_instant_fail("spec-x", duration_seconds=5)
        self.assertTrue(self.runner.is_instant_fail_cooldown("spec-x"))
        # 把 cooldown_until 拨回到过去 → 到期自动恢复并清零
        self.runner._instant_fail["spec-x"]["cooldown_until"] = (
            self.runner._now() - 1)
        self.assertFalse(self.runner.is_instant_fail_cooldown("spec-x"))
        self.assertEqual(self.runner._instant_fail_counts("spec-x"), 0)

    def test_first_cooldown_alerts_once(self):
        for _ in range(3):
            self.runner._record_instant_fail("spec-x", duration_seconds=5)
        # 清空计数再触发第二次冷却 → 15 分钟窗口内有记录 → 不再告警
        self.runner._reset_instant_fail("spec-x")
        for _ in range(3):
            self.runner._record_instant_fail("spec-x", duration_seconds=5)
        store_path = self.root / ".fenix" / "admin_alerts.json"
        self.assertTrue(store_path.exists())
        records = json.loads(store_path.read_text(encoding="utf-8"))
        storms = [r for r in records
                  if r.get("signal_type") == "instant_fail_storm"]
        self.assertEqual(len(storms), 1, "同 spec 15 分钟内只告警一次")
        self.assertEqual(storms[0]["severity"], "major")


class TestInstantFailDispatchGate(unittest.TestCase):
    """派发前冷却闸门：冷却期派发被跳过、不耗预算；到期恢复。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        (self.root / ".fenix").mkdir(parents=True)
        self.logger = make_logger()
        self.sm = StateMachine(self.root / "STATE.md", self.logger)
        self.config = {"agents": {
            "instant_fail_threshold_seconds": 60,
            "instant_fail_cooldown_after": 3,
            "instant_fail_cooldown_seconds": 300,
            "max_concurrent": 2,
        }}
        # 真实 agent_runner（仅秒挂表 + cooldown 判定），其余路径不触达
        self.runner = make_runner_with_config(
            self.root, self.config, sm=self.sm, logger=self.logger)

        from core.pm_engine import PMEngine
        self.engine = PMEngine(
            self.sm, self.runner, self.config, self.root, self.logger)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _cool_spec(self, spec, count=3):
        """让 spec 进入冷却（直接走 runner 秒挂表）。"""
        for _ in range(count):
            self.runner._record_instant_fail(spec, duration_seconds=5)

    def test_cooled_spec_dispatch_skipped(self):
        self._cool_spec("spec-a", 4)
        self.assertTrue(self.engine._instant_fail_cooled("spec-a"))

        self.sm.add_spec("spec-a", {"status": "ready", "priority": 1})
        self.engine._enqueue("spec-a", "implementer")
        # _process_queue 直接调用（不启真实线程）：冷却应跳过 → 队列清空但无派发
        with patch.object(self.runner, "run_implementer") as ri:
            self.engine._process_queue()
            ri.assert_not_called()

        # 条目保持 queued（冷却期跳过不消费），不进入 _run_agent_worker
        self.assertEqual(len(self.engine._run_queue), 1)

    def test_cooled_not_consuming_budget(self):
        self._cool_spec("spec-a")
        self.sm.add_spec("spec-a", {"status": "ready", "priority": 1})
        self.engine._enqueue("spec-a", "implementer")
        with patch.object(self.runner, "run_implementer"):
            self.engine._process_queue()
        entry = self.sm.read_one("spec-a") or {}
        self.assertEqual(int(entry.get("_impl_run_budget_used", 0) or 0), 0)

    def test_recovery_resumes_dispatch(self):
        self._cool_spec("spec-a")
        self.sm.add_spec("spec-a", {"status": "ready", "priority": 1})
        self.engine._enqueue("spec-a", "implementer")
        with patch.object(self.runner, "run_implementer"):
            self.engine._process_queue()
        self.assertEqual(len(self.engine._run_queue), 1)

        # 到期（把 cooldown_until 拨回过去）→ 恢复调度
        self.runner._instant_fail["spec-a"]["cooldown_until"] = (
            self.runner._now() - 1)
        self.assertFalse(self.engine._instant_fail_cooled("spec-a"))
        # 冷却到期后条目在队列中由下一次 _process_queue 正常派发：
        # 条目被 pop（_process_queue 在启线程前即出队），不依赖 daemon 线程完成。
        with patch.object(
            self.engine, "_run_agent_worker", return_value=None):
            self.engine._process_queue()
        self.assertEqual(self.engine._run_queue, [])

    def test_independent_from_provider_circuit(self):
        """秒挂冷却与 provider 熔断互不干扰。"""
        # provider 熔断状态（模拟另一 spec）
        self.runner.provider_circuits = {"p1": {"cooldown_until": 999999999999.0}}
        self.assertFalse(self.engine._instant_fail_cooled("spec-b"))
        # 冷却清空不影响 provider 熔断
        self._cool_spec("spec-b")
        self.assertTrue(self.engine._instant_fail_cooled("spec-b"))
        st = self.runner.provider_circuits["p1"]
        self.assertGreater(st["cooldown_until"], 0.0)


if __name__ == "__main__":
    unittest.main()