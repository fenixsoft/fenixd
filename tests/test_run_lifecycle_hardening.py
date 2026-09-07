"""
Tests for run-lifecycle-hardening SPEC.

覆盖四组能力：
1. archive-auto-commit：push 尾部归档收口（残留检测/单 commit/路径限定/失败降级）
2. cli-retry-backoff：秒挂判定与冷却闸门
3. per-agent-timeout-override：run_timeout 按 agent_type 覆盖
4. lifecycle-hygiene：frozen 终止重试链 / STATE 路径唯一 / 预算对账自动校正
"""
import json
import logging
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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
    (proot / ".fenix").mkdir(parents=True, exist_ok=True)
    logger = make_logger()
    sm = StateMachine(proot / ".fenix" / "STATE.md", logger)
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
            "spec/changes/spec-a/tasks.md": "# T\n",
            "spec/changes/spec-a/spec.md": "# S\n",
            "spec/changes/spec-b/spec.md": "# B\n",
            "core/keep.py": "KEEP = 1\n",
        })
        self.engine, self.sm, self.logger = build_engine(self.root)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_detects_archive_move_residue(self):
        # 模拟归档移动：删除 spec-a 目录 + archive 新增
        arch = self.root / "spec" / "archive" / "spec-a-1788451452"
        shutil.move(self.root / "spec" / "changes" / "spec-a", arch)
        has, names = self.engine._archive_move_residue()
        self.assertTrue(has)
        self.assertIn("spec-a", names)

    def test_detects_archive_added_only(self):
        # 仅 archive 新增（未跟踪）→ 也算残留
        arch = self.root / "spec" / "archive" / "new-spec-1788451452"
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
            "spec/changes/spec-a/tasks.md": "# T\n",
            "spec/changes/spec-a/spec.md": "# S\n",
            "core/keep.py": "KEEP = 1\n",
        })
        self.engine, self.sm, self.logger = build_engine(self.root)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_commit_and_push_on_residue(self):
        arch = self.root / "spec" / "archive" / "spec-a-1788451452"
        shutil.move(self.root / "spec" / "changes" / "spec-a", arch)
        # push 用 MagicMock 拦截（不连真实远端）
        self.engine._git_push_ref = MagicMock(return_value=(True, ""))

        self.engine._archive_auto_commit()

        # 产生了一次 push
        self.engine._git_push_ref.assert_called_once_with("main")
        # spec/ 路径干净（删除已提交、archive 已入库）
        status = git(self.root, "status", "--porcelain").stdout.strip()
        spec_lines = [
            ln for ln in status.splitlines()
            if "spec/" in ln
        ]
        self.assertEqual(spec_lines, [])
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
        arch = self.root / "spec" / "archive" / "spec-a-1788451452"
        shutil.move(self.root / "spec" / "changes" / "spec-a", arch)
        (self.root / "core" / "keep.py").write_text("KEEP = 99\n", encoding="utf-8")
        self.engine._git_push_ref = MagicMock(return_value=(True, ""))

        self.engine._archive_auto_commit()

        # commit 只含 spec/ 路径（删除侧 spec/changes/ + 新增侧 spec/archive/）
        files = git(self.root, "show", "--name-only", "--pretty=format:",
                    "HEAD").stdout.splitlines()
        files = [f for f in files if f.strip()]
        self.assertNotEqual(files, [])
        for f in files:
            self.assertTrue(f.startswith("spec/"), f)
        # 源码改动仍留在工作区
        self.assertIn("core/keep.py",
                      git(self.root, "status", "--porcelain").stdout)

    def test_commit_failure_warns_and_continues(self):
        """commit 失败 → WARNING + 不抛异常（spec 终态不受影响）。"""
        arch = self.root / "spec" / "archive" / "spec-a-1788451452"
        shutil.move(self.root / "spec" / "changes" / "spec-a", arch)
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
        arch = self.root / "spec" / "archive" / "spec-a-1788451452"
        shutil.move(self.root / "spec" / "changes" / "spec-a", arch)
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
    runner._daily_run_count = 0
    runner._daily_reset_date = None
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
        self.sm = StateMachine(self.root / ".fenix" / "STATE.md", self.logger)
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


# ══════════════════════════════════════════════════════════════════════
# 3. per-agent-timeout-override
# ══════════════════════════════════════════════════════════════════════

class TestTimeoutOverrideConfig:
    """effective_run_timeout_seconds / judge_timeout_seconds / normalize。"""

    @pytest.fixture(autouse=True)
    def _env(self, tmp_path):
        self.root = tmp_path
        self.logger = make_logger()
        self.base = {"agents": {"run_timeout_seconds": 9000}}

    def _cfg(self, overrides):
        cfg = {"agents": {"run_timeout_seconds": 9000}}
        if overrides:
            cfg["agents"]["timeout_overrides"] = overrides
        return cfg

    def test_override_applies_to_named_type(self):
        from core.config import ConfigLoader
        cfg = self._cfg({"planner-plan": 2700})
        assert ConfigLoader.effective_run_timeout_seconds(cfg, "planner-plan") == 2700
        # 未配置类型回退全局
        assert ConfigLoader.effective_run_timeout_seconds(cfg, "implementer") == 9000
        assert ConfigLoader.effective_run_timeout_seconds(cfg, "verifier") == 9000

    @pytest.mark.parametrize("atype", [
        "implementer", "verifier", "planner-plan", "planner-judge",
        "fast-track", "repair", "administrator",
    ])
    def test_agent_type_coverable(self, atype):
        from core.config import ConfigLoader
        cfg = self._cfg({atype: 3600})
        assert ConfigLoader.effective_run_timeout_seconds(cfg, atype) == 3600, \
            f"{atype} 应可被覆盖"

    def test_global_default_when_no_override(self):
        from core.config import ConfigLoader
        assert ConfigLoader.effective_run_timeout_seconds(self.base, "verifier") == 9000
        # 全局缺失 → 回退 3600
        assert ConfigLoader.effective_run_timeout_seconds({"agents": {}}, "verifier") == 3600.0

    def test_invalid_key_ignored_others_work(self, caplog):
        from core.config import ConfigLoader
        cfg = self._cfg({"unknown-type": 3600, "planner-plan": 2700})
        with caplog.at_level(logging.ERROR, logger="fenixd.config"):
            out = ConfigLoader.normalize_timeout_overrides(cfg)
        assert "unknown-type" not in out
        assert out["planner-plan"] == 2700
        assert any("非法" in r.getMessage() for r in caplog.records)
        # 生效值查询不受非法键影响
        assert ConfigLoader.effective_run_timeout_seconds(cfg, "planner-plan") == 2700
        assert ConfigLoader.effective_run_timeout_seconds(cfg, "implementer") == 9000

    @pytest.mark.parametrize("bad", [100, -5, "2700", 3.5, True],
                             ids=["too-small-int", "negative", "str", "float", "bool"])
    def test_invalid_value_ignored(self, caplog, bad):
        from core.config import ConfigLoader
        cfg = self._cfg({"implementer": bad})
        with caplog.at_level(logging.ERROR, logger="fenixd.config"):
            out = ConfigLoader.normalize_timeout_overrides(cfg)
        assert "implementer" not in out, f"{bad!r} 应被忽略"
        # 原 assertLogs 语义保留：每次非法值必须留 ERROR 日志
        assert any(r.levelno >= logging.ERROR for r in caplog.records)
        assert ConfigLoader.effective_run_timeout_seconds(cfg, "implementer") == 9000

    def test_supervision_judge_under_300_allowed(self):
        from core.config import ConfigLoader
        cfg = self._cfg({"supervision-judge": 240})
        assert ConfigLoader.judge_timeout_seconds(cfg) == 240

    def test_supervision_judge_default(self):
        from core.config import ConfigLoader
        assert ConfigLoader.judge_timeout_seconds(self.base) == 120
        assert ConfigLoader.judge_timeout_seconds({}) == 120

    def test_stuck_threshold_unchanged_by_overrides(self):
        """stuck 阈值派生保持全局默认值语义，不随覆盖变化（design D4）。"""
        from core.config import ConfigLoader
        base = ConfigLoader.effective_stuck_threshold_seconds(self.base)
        cfg = self._cfg({"planner-plan": 2700})
        assert ConfigLoader.effective_stuck_threshold_seconds(cfg) == base

    def test_runner_effective_timeout(self):
        cfg = self._cfg({"planner-plan": 2700})
        runner = make_runner_with_config(self.root, cfg, logger=self.logger)
        assert runner._effective_run_timeout("planner-plan") == 2700
        assert runner._effective_run_timeout("implementer") == 9000


class TestSupervisionAbsoluteMaxFloor:
    """supervision absolute_max 的 floor 派生三分支（2026-09-07 审查并组）。

    合并来源：本文件原 test_absolute_max_floor_rises_with_override /
    test_global_timeout_floor_when_no_override +
    test_run_lifecycle_governance.py 原
    test_absolute_max_raised_to_cover_extension_budget。
    生产语义见 core/agent_runner/liveness.py::_supervision_deadline_action：
    配置值 < run_timeout + 续期总额 时抬到 floor 并 ERROR 留痕。
    """

    @pytest.fixture(autouse=True)
    def _env(self, tmp_path):
        self.root = tmp_path
        (self.root / ".fenix" / "runs").mkdir(parents=True)
        self.logger = make_logger()
        self.run_file = self.root / ".fenix" / "runs" / "impl-spec-1-a1.jsonl"
        self.run_file.write_text('{"type":"init"}\n', encoding="utf-8")

    def _cfg(self, overrides, abs_max):
        cfg = {
            "agents": {
                "run_timeout_seconds": 3600,
                "timeout_supervision": {
                    "enabled": True,
                    "max_extensions": 2,
                    "extension_seconds": 1800,
                    "absolute_max_seconds": abs_max,
                },
            },
        }
        if overrides:
            cfg["agents"]["timeout_overrides"] = overrides
        return cfg

    @pytest.mark.parametrize(
        "overrides, abs_max, started_ago, agent_type, cap_floor, expect_error",
        [
            # 覆盖值 7200 → floor = 7200 + 2*1800 = 10800，配置 9000 被抬升
            ({"planner-plan": 7200}, 9000, 10 ** 9, "planner-plan", 10800, True),
            # 未覆盖类型：floor = 3600 + 2*1800 = 7200 ≤ 9000，不抬升
            ({}, 9000, 10 ** 9, "verifier", 9000, False),
            # 配置偏小（100）抬到 3600 + 2*1800 = 7200：刚启动 60s 不得被截断的
            # 总上限误杀（原 governance 分支）
            (None, 100, 60, None, 7200, True),
        ],
        ids=["override-raises-floor", "global-floor-no-raise", "floor-covers-budget"],
    )
    def test_absolute_max_floor_derivation(self, overrides, abs_max, started_ago,
                                           agent_type, cap_floor, expect_error):
        runner = make_runner_with_config(self.root, self._cfg(overrides, abs_max),
                                         logger=self.logger)
        judge = MagicMock(return_value={"verdict": "advancing", "evidence": "ok"})
        action = runner._supervision_deadline_action(
            self.run_file, "spec", "run-1", started_at=time.time() - started_ago,
            extensions_used=0, agent_type=agent_type, judge=judge)
        if started_ago >= cap_floor:
            # cap 命中：无条件终止，reason 注明派生后的生效值
            assert action["action"] == "kill"
            assert f"absolute_max_seconds cap reached ({cap_floor}s" in action["reason"]
            judge.assert_not_called()
        else:
            # cap 未命中：floor 兜底后不得以截断的总上限误杀短时 run
            assert "absolute_max_seconds" not in action["reason"]
        # ERROR 留痕开关：配置 < floor 时必须留痕，≥ floor 时静默
        err_msgs = [str(c) for c in runner.logger.error.call_args_list]
        assert any("兜底生效" in m for m in err_msgs) is expect_error


class TestTimeoutOverrideSupervision(unittest.TestCase):
    """supervision absolute_max 按生效超时派生抬升 + judge 超时配置化。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        (self.root / ".fenix" / "runs").mkdir(parents=True)
        self.logger = make_logger()
        self.run_file = self.root / ".fenix" / "runs" / "impl-spec-1-a1.jsonl"
        self.run_file.write_text('{"type":"init"}\n', encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _cfg(self, overrides=None, abs_max=9000):
        cfg = {
            "agents": {
                "run_timeout_seconds": 3600,
                "timeout_supervision": {
                    "enabled": True,
                    "max_extensions": 2,
                    "extension_seconds": 1800,
                    "absolute_max_seconds": abs_max,
                },
            },
        }
        if overrides:
            cfg["agents"]["timeout_overrides"] = overrides
        return cfg

    def test_supervision_judge_timeout_reads_config(self):
        cfg = self._cfg({"supervision-judge": 240})
        runner = make_runner_with_config(self.root, cfg, logger=self.logger)
        self.assertEqual(runner._supervision_judge_timeout(), 240)
        judge = MagicMock(return_value={"verdict": "advancing", "evidence": "ok"})
        # 走到 judge 判定需要扩展预算未耗尽且窗口有事件：模拟近 started_at
        action = runner._supervision_deadline_action(
            self.run_file, "spec", "run-1",
            started_at=time.time() - 1000, extensions_used=0,
            agent_type="verifier", judge=judge)
        self.assertEqual(action["action"], "extend")
        judge.assert_called_once()

    def test_judge_liveness_uses_configured_timeout(self):
        """_judge_liveness 的 subprocess timeout 读配置（supervision-judge）。"""
        cfg = self._cfg({"supervision-judge": 240})
        runner = make_runner_with_config(self.root, cfg, logger=self.logger)
        snap = runner._liveness_snapshot(self.run_file, 600)
        with patch("core.agent_runner.liveness.subprocess.run") as sr:
            sr.return_value = MagicMock(
                returncode=0,
                stdout='{"result": "{\\"verdict\\": \\"advancing\\"}"}',
                stderr="",
            )
            runner._judge_liveness(snap, "spec", "run-1")
        kwargs = sr.call_args.kwargs
        self.assertEqual(kwargs.get("timeout"), 240)

    def test_judge_liveness_default_timeout(self):
        cfg = self._cfg({})
        runner = make_runner_with_config(self.root, cfg, logger=self.logger)
        snap = runner._liveness_snapshot(self.run_file, 600)
        with patch("core.agent_runner.liveness.subprocess.run") as sr:
            sr.return_value = MagicMock(
                returncode=0,
                stdout='{"result": "{\\"verdict\\": \\"advancing\\"}"}',
                stderr="",
            )
            runner._judge_liveness(snap, "spec", "run-1")
        self.assertEqual(sr.call_args.kwargs.get("timeout"), 120)


# ══════════════════════════════════════════════════════════════════════
# 4. lifecycle-hygiene（frozen 终止重试链 / 预算对账自动校正）
# ══════════════════════════════════════════════════════════════════════

def write_impl_run_file(proot: Path, run_id: str, terminal: str = "result"):
    """写一条 impl run 产物；终态 result（正常收工）或 error（死亡 run）。"""
    p = proot / ".fenix" / "runs" / f"{run_id}.jsonl"
    with p.open("w", encoding="utf-8") as f:
        f.write('{"type":"init","timestamp":"2026-01-01T00:00:00+00:00"}\n')
        if terminal == "error":
            f.write('{"type":"error","error":"boom"}\n')
        else:
            f.write('{"type":"result","result":"ok"}\n')
    return p


class TestFrozenStopsRetryChain(unittest.TestCase):
    """frozen 终止 attempt 重试链（lifecycle-hygiene 4.1）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        (self.root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = make_logger()
        self.sm = StateMachine(self.root / ".fenix" / "STATE.md", self.logger)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_runner(self, frozen=False):
        self.sm.add_spec("spec-x", {"status": "ready", "priority": 5})
        if frozen:
            self.sm.update_spec("spec-x", {"frozen": True})
        runner = make_runner_with_config(
            self.root, {"agents": {"max_retries": 3}},
            sm=self.sm, logger=self.logger)
        runner.worktree_manager = MagicMock()
        runner.worktree_manager.create.return_value = self.root / "wt"
        # v2 绑定 no-op，避免成功路径触达真实 dev-server
        runner._v2_launch_for_worktree = MagicMock()
        runner._v2_inject_env = MagicMock(return_value={})
        runner._v2_stop_for_worktree = MagicMock()
        return runner

    def test_frozen_terminates_before_any_attempt(self):
        """frozen spec：attempt 1 启动前即终止，不派发任何 claude。"""
        runner = self._make_runner(frozen=True)
        with patch.object(runner, "_run_claude") as rc:
            result = runner.run_implementer("spec-x")
        rc.assert_not_called()  # 不派发 attempt
        self.assertFalse(result.success)
        self.assertIn("frozen", result.error)

    def test_unfrozen_chain_unchanged(self):
        """未冻结链路行为不变：attempt 正常执行。"""
        runner = self._make_runner(frozen=False)
        runs_dir = self.root / ".fenix" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        with patch.object(
            runner, "_run_claude",
            return_value=("ok", 1, "sess-1",
                          {"input_tokens": 0, "output_tokens": 0,
                           "cache_creation_input_tokens": 0,
                           "cache_read_input_tokens": 0, "cost_usd": None}),
        ) as rc:
            result = runner.run_implementer("spec-x")
        rc.assert_called_once()
        self.assertTrue(result.success)

    def test_frozen_mid_chain_terminates(self):
        """attempt 1 进行中被冻结、attempt 2 启动前 → 重试链终止。"""
        runner = self._make_runner(frozen=False)
        runs_dir = self.root / ".fenix" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        attempt = {"n": 0}

        def fake_claude(prompt, cwd, run_id, model_override, env_overrides,
                        resume_session_id=None, max_turns=None, spec_name=None,
                        agent_type=None):
            attempt["n"] += 1
            if attempt["n"] == 1:
                # a1 失败，且运行中该 spec 被人为冻结（模拟运行期冻结）
                self.sm.update_spec("spec-x", {"frozen": True})
                raise RuntimeError("transient failure")
            return ("ok", 1, "sess", {"input_tokens": 0, "output_tokens": 0,
                                      "cache_creation_input_tokens": 0,
                                      "cache_read_input_tokens": 0,
                                      "cost_usd": None})

        runner._run_claude = fake_claude
        with patch.object(runner, "_record_instant_fail",
                          return_value=None) as rif:
            result = runner.run_implementer("spec-x")
        # a1 已执行；a2 启动前被冻结 → 不再第二次调用 _run_claude
        self.assertEqual(attempt["n"], 1)
        self.assertFalse(result.success)
        self.assertIn("frozen", result.error)
        rif.assert_called_once()  # 秒挂计数仍走既有路径


class TestBudgetReconcileCorrect(unittest.TestCase):
    """预算对账自动校正（lifecycle-hygiene 4.3）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        (self.root / ".fenix" / "runs").mkdir(parents=True)
        self.engine, self.sm, self.logger = build_engine(self.root)
        self.sm.add_spec("spec-a", {"status": "ready", "priority": 5})

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _two_normal_runs(self):
        write_impl_run_file(self.root, "impl-spec-a-1788400001-a1", "result")
        write_impl_run_file(self.root, "impl-spec-a-1788400002-a1", "result")

    def test_pure_drift_corrects_4_to_2(self):
        self._two_normal_runs()
        self.sm.update_spec("spec-a", {"_impl_run_budget_used": 4})
        self.engine._reconcile_impl_budget("spec-a")
        entry = self.sm.read_one("spec-a")
        self.assertEqual(int(entry["_impl_run_budget_used"]), 2)
        infos = [str(c) for c in self.logger.info.call_args_list]
        self.assertTrue(any("校正" in m and "4 → 2" in m for m in infos),
                        "应留 INFO 校正日志含前后值")

    def test_death_exemption_no_correction(self):
        self._two_normal_runs()
        # 死亡豁免发生过 → 不改数
        self.sm.update_spec("spec-a", {"_impl_run_budget_used": 4,
                                       "_budget_exempt_runs": 1})
        self.engine._reconcile_impl_budget("spec-a")
        entry = self.sm.read_one("spec-a")
        self.assertEqual(int(entry["_impl_run_budget_used"]), 4)
        warnings = [str(c) for c in self.logger.warning.call_args_list]
        self.assertTrue(any("豁免" in m for m in warnings))

    def test_archived_runs_no_correction(self):
        """runs 产物被归档（保留上限）→ 不改数。"""
        self._two_normal_runs()
        # 另造一条已归档的 impl 产物（archive/ 下）
        arch = self.root / ".fenix" / "runs" / "archive"
        arch.mkdir(parents=True)
        write_impl_run_file(self.root, "impl-spec-a-1788300001-a1", "result")
        (self.root / ".fenix" / "runs" / "impl-spec-a-1788300001-a1.jsonl").rename(
            arch / "impl-spec-a-1788300001-a1.jsonl")
        self.sm.update_spec("spec-a", {"_impl_run_budget_used": 4})
        self.engine._reconcile_impl_budget("spec-a")
        entry = self.sm.read_one("spec-a")
        self.assertEqual(int(entry["_impl_run_budget_used"]), 4)
        warnings = [str(c) for c in self.logger.warning.call_args_list]
        self.assertTrue(any("豁免" in m for m in warnings))

    def test_no_deviation_no_op(self):
        self._two_normal_runs()
        self.sm.update_spec("spec-a", {"_impl_run_budget_used": 2})
        self.engine._reconcile_impl_budget("spec-a")
        entry = self.sm.read_one("spec-a")
        self.assertEqual(int(entry["_impl_run_budget_used"]), 2)


if __name__ == "__main__":
    unittest.main()