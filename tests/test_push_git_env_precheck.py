"""evo-add-push-git-env-precheck 测试：推送 git 环境预检短路 + 续推双门。

覆盖（对应 tasks.md）：
- 1.1/1.2：无 remote / 无目标分支的 N/A 短路、push=N/A 持久留痕（专用字段，
  不走 error）、不进退避、best-effort 与归档收口 info 降级；
- 2.1/2.2：续推通道审批门（manual+零记账拦截 / manual+有记账放行 / auto
  不受影响）与 N/A 持久字段终局跳过（跨重启幂等、零重投递）；
- 3.1：推送目标分支配置优先、缺省按仓库当前分支探测（去 main 硬编码）；
- 3.2：pm.push.retry_backoff_seconds 缺键 DEBUG 静默 / 形式非法 WARNING /
  元素级非法 WARNING 回退的分级回归锁定（元素级留痕系 code-review item
  ddb8b7643aba 后的现行契约：行为回退不变、补排障指向）。

git 交互用真实临时仓（含本地 bare remote），预检走真实 git 探测——mock 掉
被测预检＝后端契约零覆盖，故仅对推送收口外围（归档/蒸馏/项目日志）打桩。
"""

import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.event_bus import EventBus
from core.pm_engine.reporting import ReportBuilder
from core.state_machine import (
    PUSH_ATTEMPTS_FIELD,
    PUSH_BACKOFF_NEXT_RETRY_AT_FIELD,
    PUSH_NA_FIELD,
    PUSH_NA_REASON_FIELD,
    StateMachine,
)

PUSH_NA_PREFIX = "[push_na:"


def git(repo: Path, *args) -> subprocess.CompletedProcess:
    res = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    assert res.returncode == 0, f"git {args} failed: {res.stderr}"
    return res


def init_git_repo(repo: Path, initial_files: dict = None) -> str:
    """初始化 git 仓库（配置身份 + 初始提交），返回当前分支名。"""
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
    return git(repo, "symbolic-ref", "--short", "HEAD").stdout.strip()


def make_bare_remote(base: Path) -> Path:
    """建本地 bare remote 并返回其路径（预检放行的最小真实远端）。"""
    bare = base / "origin.git"
    git(base, "init", "-q", "--bare", str(bare))
    return bare


class FakeLogger:
    def __init__(self):
        self.debugs = []
        self.infos = []
        self.warnings = []
        self.errors = []

    def debug(self, *a, **k):
        self.debugs.append(a)

    def info(self, *a, **k):
        self.infos.append(a)

    def warning(self, *a, **k):
        self.warnings.append(a)

    def error(self, *a, **k):
        self.errors.append(a)


def build_engine(proot: Path, config: dict = None):
    """构造最小 PMEngine（真实 state_machine + MagicMock agent_runner）。"""
    from core.pm_engine import PMEngine

    (proot / ".fenix").mkdir(parents=True, exist_ok=True)
    logger = FakeLogger()
    sm = StateMachine(proot / ".fenix" / "STATE.md", logger)
    engine = PMEngine(sm, MagicMock(), config or {}, proot, logger)
    return engine, sm, logger


class _RecordingExecutor:
    def __init__(self, reject=False):
        self.submitted = []
        self._reject = reject

    def submit(self, fn, name=None):
        if self._reject:
            raise RuntimeError("pool saturated")
        self.submitted.append((fn, (name,) if name is not None else ()))


class _StaticForwardPM:
    """pm_engine 替身：退避/计数读侧走 ReportBuilder 真实判定（不 mock 判定）。"""

    _is_push_backoffed = staticmethod(ReportBuilder._is_push_backoffed)
    _get_push_retry_count = staticmethod(ReportBuilder._get_push_retry_count)

    def __init__(self):
        self.approve_push = MagicMock(name="approve_push")


def _make_bus(tmp_path, pm=None, logger=None, config=None, executor=None):
    bus = EventBus(
        Path(tmp_path) / "STATE.md",
        MagicMock(name="state_machine"),
        pm if pm is not None else _StaticForwardPM(),
        config if config is not None else {},
        logger if logger is not None else FakeLogger(),
    )
    if executor is not None:
        bus._admin_executor = executor
    return bus


def _done_entry(**overrides):
    entry = {"name": "spec-a", "status": "done", "error": None}
    entry.update(overrides)
    return entry


# ════════════════════════════════════════════════════════════════════
# 1.1 _git_push_ref 环境预检（真实 git 探测）
# ════════════════════════════════════════════════════════════════════


class TestGitPushEnvPrecheck(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.engine, self.sm, self.logger = build_engine(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_no_remote_short_circuit_without_push_subprocess(self):
        """无 remote 仓：_git_push_ref 返回 N/A 标记，push 子进程零执行。"""
        branch = init_git_repo(self.tmpdir, {"README.md": "x\n"})
        pushed = []

        orig_run = subprocess.run

        def counting_run(cmd, **kwargs):
            if "push" in [str(a) for a in cmd]:
                pushed.append(cmd)
            return orig_run(cmd, **kwargs)

        with patch("subprocess.run", side_effect=counting_run):
            ok, err = self.engine._git_push_ref(branch)
        self.assertFalse(ok)
        self.assertIn(PUSH_NA_PREFIX + "no-remote", err)
        self.assertEqual(pushed, [], "无 remote 时 MUST NOT 执行 git push 子进程")

    def test_remote_present_but_target_branch_missing(self):
        """有 remote 无目标分支：返回 no-ref 标记，不执行 push。"""
        init_git_repo(self.tmpdir, {"README.md": "x\n"})
        git(self.tmpdir, "remote", "add", "origin", str(make_bare_remote(self.tmpdir)))
        ok, err = self.engine._git_push_ref("nonexistent-branch")
        self.assertFalse(ok)
        self.assertIn(PUSH_NA_PREFIX + "no-ref", err)
        self.assertIn("nonexistent-branch", err)

    def test_env_ok_push_succeeds_against_bare_remote(self):
        """remote 与目标分支俱在：预检放行，push 真实执行成功。"""
        branch = init_git_repo(self.tmpdir, {"README.md": "x\n"})
        git(self.tmpdir, "remote", "add", "origin", str(make_bare_remote(self.tmpdir)))
        ok, err = self.engine._git_push_ref(branch)
        self.assertTrue(ok, err)
        self.assertEqual(err, "")
        # 远端引用确实落定（真实推送，非 mock 放行）
        ls = git(self.tmpdir, "ls-remote", "origin", f"refs/heads/{branch}")
        self.assertIn(branch, ls.stdout)

    def test_probe_exception_fail_closed_as_no_remote(self):
        """探测异常保守按缺失处理（fail-closed），不裸推。"""
        init_git_repo(self.tmpdir, {"README.md": "x\n"})
        with patch(
            "core.pm_engine.engine.subprocess.run",
            side_effect=RuntimeError("git binary gone"),
        ):
            ok, err = self.engine._git_push_ref("main")
        self.assertFalse(ok)
        self.assertIn(PUSH_NA_PREFIX + "no-remote", err)

    def test_marker_classifier(self):
        """_is_push_na_marker 按 [push_na: 前缀分流（调用方单点）。"""
        self.assertTrue(self.engine._is_push_na_marker("[push_na:no-remote] x"))
        self.assertTrue(self.engine._is_push_na_marker("[push_na:no-ref] y"))
        self.assertFalse(self.engine._is_push_na_marker("git push failed: boom"))
        self.assertFalse(self.engine._is_push_na_marker(""))
        self.assertFalse(self.engine._is_push_na_marker(None))


# ════════════════════════════════════════════════════════════════════
# 1.2 approve_push N/A 短路与持久留痕
# ════════════════════════════════════════════════════════════════════


class TestApprovePushNaShortCircuit(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        # 真实 git 仓、无 remote（预检与 N/A 短路走真实探测链路）
        init_git_repo(self.tmpdir, {"README.md": "x\n"})
        self.engine, self.sm, self.logger = build_engine(self.tmpdir)
        # 隔离外围链路（预检与 git push 走真实探测）
        self.engine._resolve_push_branch = MagicMock(return_value="fenix/spec-a")
        self.engine._push_branch_best_effort = MagicMock()
        self.engine._archive_auto_commit = MagicMock()
        self.engine._append_project_log = MagicMock()
        self.engine._signal_push_failed = MagicMock()
        self.sm.add_spec("spec-a", {"status": "done", "branch": "fenix/spec-a"})

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_na_short_circuit_persists_dedicated_fields(self):
        """无 remote：approve_push 返回 False；N/A 落专用字段；error/退避/升级全零。"""
        ok = self.engine.approve_push("spec-a", distill=lambda p, n: None)
        self.assertFalse(ok)
        entry = self.sm.read_one("spec-a")
        self.assertEqual(entry[PUSH_NA_FIELD], "N/A")
        self.assertIn(PUSH_NA_PREFIX + "no-remote", entry[PUSH_NA_REASON_FIELD])
        # 不走 error 字段、不进退避记账、不升级 push_failed
        self.assertIsNone(entry.get("error"))
        self.assertIsNone(entry.get(PUSH_ATTEMPTS_FIELD))
        self.assertIsNone(entry.get(PUSH_BACKOFF_NEXT_RETRY_AT_FIELD))
        self.engine._signal_push_failed.assert_not_called()

    def test_na_repeat_idempotent_same_values(self):
        """重复进入（人工重推）：N/A 结果稳定可重复，字段值不漂移。"""
        self.engine.approve_push("spec-a", distill=lambda p, n: None)
        first = self.sm.read_one("spec-a")
        self.engine.approve_push("spec-a", distill=lambda p, n: None)
        second = self.sm.read_one("spec-a")
        self.assertEqual(first[PUSH_NA_FIELD], second[PUSH_NA_FIELD])
        self.assertEqual(first[PUSH_NA_REASON_FIELD], second[PUSH_NA_REASON_FIELD])
        self.assertEqual(second["status"], "done", "N/A 短路不得转移状态")

    def test_push_success_clears_na_fields(self):
        """配置 remote 后重推成功：N/A 字段随 push 成功同清（唯一清零点）。"""
        self.engine.approve_push("spec-a", distill=lambda p, n: None)
        self.assertEqual(self.sm.read_one("spec-a")[PUSH_NA_FIELD], "N/A")
        # 环境修复：挂本地 bare remote（当前分支可推）
        branch = git(self.tmpdir, "symbolic-ref", "--short", "HEAD").stdout.strip()
        git(self.tmpdir, "remote", "add", "origin", str(make_bare_remote(self.tmpdir)))
        ok = self.engine.approve_push("spec-a", distill=lambda p, n: None)
        self.assertTrue(ok)
        entry = self.sm.read_one("spec-a")
        self.assertEqual(entry["status"], "pushed")
        self.assertIsNone(entry.get(PUSH_NA_FIELD))
        self.assertIsNone(entry.get(PUSH_NA_REASON_FIELD))

    def test_best_effort_na_degrades_to_info(self):
        """best-effort 遇 N/A 标记：info 级跳过，不 WARNING。"""
        del self.engine._push_branch_best_effort  # 恢复真实方法（setUp 打桩外围）
        self.engine._local_branch_sha = MagicMock(return_value="a" * 40)
        self.engine._remote_branch_sha = MagicMock(return_value=None)
        self.engine._git_push_ref = MagicMock(
            return_value=(False, PUSH_NA_PREFIX + "no-ref] 目标分支不存在")
        )
        self.engine._push_branch_best_effort("spec-a", "fenix/spec-a")
        self.assertTrue(any("N/A skipped" in str(a) for a in self.logger.infos))
        self.assertEqual(self.logger.warnings, [])

    def test_archive_closeout_na_degrades_to_info(self):
        """归档收口 push 遇 N/A 标记：info 留痕短路，不 WARNING 刷屏。"""
        del self.engine._archive_auto_commit  # 恢复真实方法（setUp 打桩外围）
        self.engine._git_commit = MagicMock(return_value=(True, ""))
        self.engine._archive_move_residue = MagicMock(
            return_value=(True, ["spec-a"], ["spec/archive/spec-a-1"])
        )
        self.engine._git_push_ref = MagicMock(
            return_value=(False, PUSH_NA_PREFIX + "no-remote] 仓库未配置任何 git remote")
        )
        self.engine._archive_auto_commit()
        self.assertTrue(any("归档收口 push N/A" in str(a) for a in self.logger.infos))
        self.assertEqual(self.logger.warnings, [])


# ════════════════════════════════════════════════════════════════════
# 2.1/2.2 续推通道双门（审批门 + N/A 终局门）
# ════════════════════════════════════════════════════════════════════


class TestRecoverDonePushRetryGates(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_manual_zero_accounting_not_dispatched(self):
        """manual（含缺省回退）+ 零记账（未经人工批准）→ 不自动补投推送。"""
        executor = _RecordingExecutor()
        bus = _make_bus(self.tmpdir, executor=executor)
        ok = bus._recover_one("spec-a", _done_entry())
        self.assertTrue(ok)  # 有意跳过计入 handled
        self.assertEqual(executor.submitted, [])
        self.assertTrue(
            any("不自动补投" in str(a) for a in bus.logger.debugs)
        )

    def test_manual_with_attempts_accounting_dispatched(self):
        """manual + push_attempts 记账（人工已批准推送的退避重试）→ 放行续推。"""
        executor = _RecordingExecutor()
        bus = _make_bus(self.tmpdir, executor=executor)
        ok = bus._recover_one("spec-a", _done_entry(_push_attempts=1))
        self.assertTrue(ok)
        self.assertEqual(len(executor.submitted), 1)

    def test_manual_with_expired_backoff_field_dispatched(self):
        """manual + 退避字段（已过期）即算记账 → 放行（双源记账判定）。"""
        past = int(time.time()) - 60
        executor = _RecordingExecutor()
        bus = _make_bus(self.tmpdir, executor=executor)
        ok = bus._recover_one(
            "spec-a", _done_entry(_push_backoff_next_retry_at=past)
        )
        self.assertTrue(ok)
        self.assertEqual(len(executor.submitted), 1)

    def test_auto_mode_zero_accounting_dispatched(self):
        """显式配置 auto：零记账 spec 照常投递（既有行为不变）。"""
        executor = _RecordingExecutor()
        bus = _make_bus(
            self.tmpdir,
            config={"gates": {"approve_mode": "auto"}},
            executor=executor,
        )
        ok = bus._recover_one("spec-a", _done_entry())
        self.assertTrue(ok)
        self.assertEqual(len(executor.submitted), 1)

    def test_na_field_terminal_skip_even_auto(self):
        """N/A 持久字段 → 终局跳过（auto 模式也不投递），不推进重试计数。"""
        executor = _RecordingExecutor()
        bus = _make_bus(
            self.tmpdir,
            config={"gates": {"approve_mode": "auto"}},
            executor=executor,
        )
        entry = _done_entry(_push_na="N/A", _push_na_reason="[push_na:no-remote] x")
        ok = bus._recover_one("spec-a", entry)
        self.assertTrue(ok)
        self.assertEqual(executor.submitted, [])
        self.assertEqual(entry.get(PUSH_ATTEMPTS_FIELD), None)

    def test_na_skip_survives_restart_roundtrip(self):
        """跨重启幂等：N/A 字段经 STATE 落盘/读回后仍终局跳过（零重投递）。"""
        proot = self.tmpdir
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        logger = FakeLogger()
        sm = StateMachine(proot / ".fenix" / "STATE.md", logger)
        sm.add_spec("spec-a", {"status": "done"})
        sm.update_spec(
            "spec-a",
            {PUSH_NA_FIELD: "N/A", PUSH_NA_REASON_FIELD: "[push_na:no-remote] x"},
        )
        # 模拟 daemon 重启：全新 StateMachine 实例读同一 STATE.md
        sm2 = StateMachine(proot / ".fenix" / "STATE.md", logger)
        entry = sm2.read_one("spec-a")
        self.assertEqual(entry[PUSH_NA_FIELD], "N/A")
        executor = _RecordingExecutor()
        bus = _make_bus(proot, executor=executor)
        ok = bus._recover_one("spec-a", entry)
        self.assertTrue(ok)
        self.assertEqual(executor.submitted, [])
        self.assertTrue(any("N/A 终局" in str(a) for a in bus.logger.debugs))


# ════════════════════════════════════════════════════════════════════
# 3.1 推送目标分支解析（配置优先 / 缺省探测 / approve_push 与归档收口覆盖）
# ════════════════════════════════════════════════════════════════════


class TestPushTargetBranchResolution(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.branch = init_git_repo(self.tmpdir, {"README.md": "x\n"})
        git(self.tmpdir, "remote", "add", "origin", str(make_bare_remote(self.tmpdir)))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_config_branch_takes_priority(self):
        """pm.push.target_branch 显式配置优先于仓库探测。"""
        engine, _, _ = build_engine(
            self.tmpdir, config={"pm": {"push": {"target_branch": "release"}}}
        )
        self.assertEqual(engine._resolve_push_target_branch(), "release")

    def test_defaults_to_repo_current_branch(self):
        """未配置：按仓库当前分支探测（本仓默认分支，非硬编码 main）。"""
        engine, _, _ = build_engine(self.tmpdir)
        self.assertEqual(engine._resolve_push_target_branch(), self.branch)

    def test_falls_back_to_main_when_symbolic_ref_fails(self):
        """探测失败（detached HEAD 等异常形态）保守回退 main。"""
        engine, _, _ = build_engine(self.tmpdir)
        with patch(
            "core.pm_engine.engine.subprocess.run",
            side_effect=subprocess.CalledProcessError(128, "git"),
        ):
            self.assertEqual(engine._resolve_push_target_branch(), "main")

    def test_approve_push_pushes_resolved_branch(self):
        """approve_push 主推走解析分支（非 main 硬编码）。"""
        git(self.tmpdir, "checkout", "-q", "-b", "dev")
        engine, sm, logger = build_engine(self.tmpdir)
        sm.add_spec("spec-a", {"status": "done"})
        engine._resolve_push_branch = MagicMock(return_value="fenix/spec-a")
        engine._push_branch_best_effort = MagicMock()
        engine._archive_auto_commit = MagicMock()
        engine._append_project_log = MagicMock()
        engine._git_push_ref = MagicMock(return_value=(True, ""))
        # tip 前进断言（wrapup-push-branch-guard 1.2）基线打桩：推送前基线
        # 查询失败（None）→ 按「基线不可知→远端 tip 与本地 HEAD 复核」契约
        # 确认推送生效（远端 tip == 本地分支 SHA；597a7f776 契约，替身对齐）。
        engine._remote_branch_sha = MagicMock(side_effect=[None, "f" * 40])
        engine._local_branch_sha = MagicMock(return_value="f" * 40)
        self.assertTrue(engine.approve_push("spec-a", distill=lambda p, n: None))
        engine._git_push_ref.assert_called_once_with("dev")

    def test_archive_closeout_pushes_resolved_branch(self):
        """归档收口 push 走解析分支（两处裸推同覆盖）。"""
        git(self.tmpdir, "checkout", "-q", "-b", "dev")
        engine, sm, logger = build_engine(self.tmpdir)
        engine._archive_move_residue = MagicMock(
            return_value=(True, ["spec-a"], ["spec/archive/spec-a-1"])
        )
        engine._git_commit = MagicMock(return_value=(True, ""))
        engine._git_push_ref = MagicMock(return_value=(True, ""))
        engine._archive_auto_commit()
        engine._git_push_ref.assert_called_once_with("dev")


# ════════════════════════════════════════════════════════════════════
# 3.2 退避配置分级回归锁定（既有行为，无实现改动）
# ════════════════════════════════════════════════════════════════════


class TestBackoffConfigGrading(unittest.TestCase):
    """pm.push.retry_backoff_seconds：缺键→DEBUG 静默、形式非法→WARNING、
    元素级非法→WARNING 回退（分级已在 _handle_push_failure 实现，此处锁定
    防回归；元素级留痕口径见 ddb8b7643aba，与同类脏配置分支对齐）。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.engine, self.sm, self.logger = build_engine(self.tmpdir)
        self.sm.add_spec("spec-a", {"status": "done"})
        self.engine.state_machine.update_spec = MagicMock()
        self.engine._signal_push_failed = MagicMock()
        self.spec = self.sm.read_one("spec-a")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _trigger(self, config):
        self.engine.config = config
        self.engine._handle_push_failure("spec-a", self.spec, "boom", "main")

    def test_missing_key_silent_debug_with_default(self):
        """键未配置：DEBUG 静默回退默认退避（无 WARNING 噪音）。"""
        self._trigger({})
        self.assertTrue(any("未配置" in str(a) for a in self.logger.debugs))
        graded = [w for w in self.logger.warnings if "retry_backoff_seconds" in str(w)]
        self.assertEqual(graded, [])

    def test_malformed_form_warns(self):
        """键存在但非 list / 长度不足：WARNING 回退默认。"""
        for bad in ("bad", [300], 42):
            self.logger.warnings.clear()
            self.logger.debugs.clear()
            self._trigger({"pm": {"push": {"retry_backoff_seconds": bad}}})
            graded = [
                w for w in self.logger.warnings if "retry_backoff_seconds" in str(w)
            ]
            self.assertEqual(len(graded), 1, f"形态非法 {bad!r} 应恰一次 WARNING")
            self.assertIn("非 list 或长度不足", str(graded[0]))

    def test_negative_zero_bool_elements_warn(self):
        """负值/零值/布尔元素：WARNING 回退默认。"""
        for bad in ([300, -5], [0, 900], [True, 900]):
            self.logger.warnings.clear()
            self._trigger({"pm": {"push": {"retry_backoff_seconds": bad}}})
            graded = [
                w for w in self.logger.warnings if "retry_backoff_seconds" in str(w)
            ]
            self.assertEqual(len(graded), 1, f"非法元素 {bad!r} 应恰一次 WARNING")
            self.assertIn("负值/零值/布尔", str(graded[0]))

    def test_element_level_illegal_silent_fallback(self):
        """元素级非法（int 转换失败）：恰一次 WARNING 留痕 + 回退默认值。

        方法名保留历史口径；分级契约已由 ddb8b7643aba 演进为「非法值必
        留痕」——行为回退不变、补排障指向，与形式非法/负值/零值/布尔
        分支同款 WARNING（断言过时回正，fix_scope=test）。
        """
        self._trigger({"pm": {"push": {"retry_backoff_seconds": [300, "abc"]}}})
        graded = [w for w in self.logger.warnings if "retry_backoff_seconds" in str(w)]
        self.assertEqual(len(graded), 1, "元素级非法应恰一次 WARNING 留痕")
        self.assertIn("含非数值元素", str(graded[0]))
        # 回退默认 300：退避记账按默认 delay 落盘
        update_kwargs = self.engine.state_machine.update_spec.call_args
        fields = update_kwargs[0][1]
        self.assertEqual(fields[PUSH_ATTEMPTS_FIELD], 1)
        import time as _time

        self.assertGreaterEqual(
            fields[PUSH_BACKOFF_NEXT_RETRY_AT_FIELD], int(_time.time()) + 295
        )


if __name__ == "__main__":
    unittest.main()
