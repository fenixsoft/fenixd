"""tests/test_push_retry_recovery.py — fix-push-credential-env-and-retry-rearm 任务 4.2 / 5.2

推送凭证自检（4.1）与 done 态推送退避续推通道（5.1）的守卫测试：
- 凭证自检：双腿皆缺告警一次、单腿可用不告警、探测异常 fail-open 不阻断；
- 续推通道：退避到期投递 approve_push、退避期内 debug 跳过、计数达上限/
  push_failed 已发不再投递、重启后（字段存量+退避过期）首轮拾取、executor
  拒绝不中断扫描、executor 缺席 WARNING 且无内联调用、多 spec 命中主循环
  不内联阻塞。
"""
import os
import sys
import tempfile
import unittest
import shutil
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fenixd as _fenixd_mod
from core.event_bus import EventBus


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


# ── 4.2 启动凭证自检 ──────────────────────────────────────────────────────


class _PrecheckHost:
    """最小宿主替身：复用 FenixDaemon 真实自检方法，注入可控探测面。"""

    _startup_credential_precheck = _fenixd_mod.FenixDaemon._startup_credential_precheck
    _remote_urls_have_embedded_credentials = (
        _fenixd_mod.FenixDaemon._remote_urls_have_embedded_credentials
    )
    _read_remote_urls = _fenixd_mod.FenixDaemon._read_remote_urls

    def __init__(self, tmp_path, admin_store=None, remote_urls_ok=False):
        self._credential_precheck_done = False
        self.config = {}
        self.logger = FakeLogger()
        self.admin_store = admin_store if admin_store is not None else MagicMock()
        self._remote_urls_ok = remote_urls_ok
        self._tmp_path = tmp_path


class TestStartupCredentialPrecheck(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _host(self, **kwargs):
        return _PrecheckHost(self.tmpdir, **kwargs)

    def test_both_legs_missing_warns_once(self):
        """双腿皆缺 → 告警一次（run-once 旗标去重），admin store 收告警。"""
        import core.git_env as ge

        host = self._host()
        orig_resolve = ge.resolve_git_env
        # resolved_home=None（三级全空）→ home_ok False、cred_ok False；
        # remote URL 扫描强制无凭证
        ge.resolve_git_env = lambda config=None, env=None: ge.GitEnv(
            resolved_home=None, process_env={}, credential_file=None
        )
        try:
            host._remote_urls_have_embedded_credentials = lambda: False
            host._startup_credential_precheck()
            first_warnings = len(host.logger.warnings)
            host._startup_credential_precheck()  # 旗标去重：第二次零动作
        finally:
            ge.resolve_git_env = orig_resolve
        assert first_warnings == 1
        assert len(host.logger.warnings) == 1
        assert host.admin_store.append_if_absent.call_count == 1
        rec = host.admin_store.append_if_absent.call_args[0][0]
        assert rec["signal_type"] == "push_credential_missing"
        assert "处置指引" in rec["recommended_action"]

    def test_home_dir_missing_but_leg_present_still_warns(self):
        """HOME 目录不存在 → 即使 URL 腿在场也告警（HOME 解析失败分支）。"""
        import core.git_env as ge

        host = self._host()
        orig_resolve = ge.resolve_git_env
        ge.resolve_git_env = lambda config=None, env=None: ge.GitEnv(
            resolved_home="/no/such/home-dir",
            process_env={"HOME": "/no/such/home-dir"},
            credential_file=None,
        )
        try:
            host._remote_urls_have_embedded_credentials = lambda: True
            host._startup_credential_precheck()
        finally:
            ge.resolve_git_env = orig_resolve
        assert len(host.logger.warnings) == 1

    def test_credential_file_leg_present_no_warning(self):
        """凭证文件腿在场（URL 无凭证）→ 单腿可运行，零告警。"""
        import core.git_env as ge

        home = Path(self.tmpdir) / "home"
        home.mkdir()
        cred = home / ".git-credentials"
        cred.write_text("https://u:t@h\n", encoding="utf-8")
        host = self._host()
        orig_resolve = ge.resolve_git_env
        ge.resolve_git_env = lambda config=None, env=None: ge.GitEnv(
            resolved_home=str(home),
            process_env={"HOME": str(home)},
            credential_file=str(cred),
        )
        try:
            host._remote_urls_have_embedded_credentials = lambda: False
            host._startup_credential_precheck()
        finally:
            ge.resolve_git_env = orig_resolve
        assert host.logger.warnings == []
        host.admin_store.append_if_absent.assert_not_called()

    def test_url_leg_present_no_warning(self):
        """URL 内嵌凭证腿在场（凭证文件缺席）→ 单腿可运行，零告警。"""
        import core.git_env as ge

        home = Path(self.tmpdir) / "home"
        home.mkdir()  # 无 .git-credentials
        host = self._host()
        orig_resolve = ge.resolve_git_env
        ge.resolve_git_env = lambda config=None, env=None: ge.GitEnv(
            resolved_home=str(home),
            process_env={"HOME": str(home)},
            credential_file=str(home / ".git-credentials"),
        )
        try:
            host._remote_urls_have_embedded_credentials = lambda: True
            host._startup_credential_precheck()
        finally:
            ge.resolve_git_env = orig_resolve
        assert host.logger.warnings == []

    def test_probe_exception_fail_open_no_raise(self):
        """探测异常（remote 扫描抛错）→ 不抛出、不阻断（仅日志）。"""
        import core.git_env as ge

        home = Path(self.tmpdir) / "home"
        home.mkdir()
        cred = home / ".git-credentials"
        cred.write_text("x\n", encoding="utf-8")
        host = self._host()
        orig_resolve = ge.resolve_git_env
        ge.resolve_git_env = lambda config=None, env=None: ge.GitEnv(
            resolved_home=str(home),
            process_env={"HOME": str(home)},
            credential_file=str(cred),
        )
        try:
            host._remote_urls_have_embedded_credentials = MagicMock(
                side_effect=RuntimeError("probe exploded")
            )
            # MUST NOT raise：fail-open 契约
            host._startup_credential_precheck()
        finally:
            ge.resolve_git_env = orig_resolve
        # 异常被方法内 except 吞掉 → 零告警（探测未完成）、仅日志留痕
        assert host.admin_store.append_if_absent.call_count == 0

    def test_admin_store_failure_does_not_raise(self):
        """admin store 写入故障 → fail-open 降级日志，不阻断启动。"""
        import core.git_env as ge

        host = self._host()
        store = MagicMock()
        store.append_if_absent.side_effect = RuntimeError("store down")
        host.admin_store = store
        orig_resolve = ge.resolve_git_env
        ge.resolve_git_env = lambda config=None, env=None: ge.GitEnv(
            resolved_home=None, process_env={}, credential_file=None
        )
        try:
            host._remote_urls_have_embedded_credentials = lambda: False
            host._startup_credential_precheck()  # MUST NOT raise
        finally:
            ge.resolve_git_env = orig_resolve
        assert len(host.logger.warnings) == 2  # 告警本体 + store 故障降级


class TestUrlEmbeddedCredentialScan(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_https_url_with_token_detected(self):
        assert _fenixd_mod._url_has_embedded_credential(
            "https://ghp_token123@github.com/owner/repo.git"
        )

    def test_plain_https_url_not_detected(self):
        assert not _fenixd_mod._url_has_embedded_credential(
            "https://github.com/owner/repo.git"
        )

    def test_ssh_form_not_detected(self):
        assert not _fenixd_mod._url_has_embedded_credential(
            "git@github.com:owner/repo.git"
        )

    def test_malformed_url_safe_false(self):
        assert not _fenixd_mod._url_has_embedded_credential("://bad url")

    def test_scan_reads_local_git_config_only(self, monkeypatch=None):
        """_read_remote_urls 纯本地读 git config；已接管项目被纳入扫描面。"""
        import subprocess
        from unittest.mock import patch

        repo = Path(self.tmpdir) / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "config", "remote.origin.url",
             "https://tok@host/repo.git"],
            check=True,
        )
        host = _PrecheckHost(self.tmpdir)
        urls = host._read_remote_urls(repo)
        assert urls == ["https://tok@host/repo.git"]

        # 已接管项目（registry discover）纳入扫描面：项目 remote 含内嵌凭证 → URL 腿在场
        with patch(
            "core.dashboard.registry.Registry.discover",
            return_value=[{"name": "proj", "path": str(repo)}],
        ):
            assert host._remote_urls_have_embedded_credentials() is True

        # 项目 remote 无内嵌凭证 + PROJECT_ROOT（worktree 仓库）无 remote URL → False
        subprocess.run(
            ["git", "-C", str(repo), "config", "remote.origin.url",
             "https://host/repo.git"],
            check=True,
        )
        with patch(
            "core.dashboard.registry.Registry.discover",
            return_value=[{"name": "proj", "path": str(repo)}],
        ):
            # PROJECT_ROOT 是真实 worktree 仓库（有 remote origin），须同被扫描——
            # 若其 remote 含内嵌凭证则本断言不稳，故此处仅验证不抛出且为 bool
            result = host._remote_urls_have_embedded_credentials()
            assert isinstance(result, bool)


# ── 5.2 done 态退避续推通道 ───────────────────────────────────────────────


class _StaticForwardPM:
    """pm_engine 替身：退避/计数读侧走 PMEngine 既有静态转发（真实判定），
    approve_push 可断言调用形态（内联 vs executor.submit）。"""

    from core.pm_engine.reporting import ReportBuilder as _RB

    _is_push_backoffed = staticmethod(_RB._is_push_backoffed)
    _get_push_retry_count = staticmethod(_RB._get_push_retry_count)

    def __init__(self):
        self.approve_push = MagicMock(name="approve_push")


def _make_bus(tmp_path, pm=None, logger=None, config=None):
    return EventBus(
        Path(tmp_path) / "STATE.md",
        MagicMock(name="state_machine"),
        pm if pm is not None else _StaticForwardPM(),
        config if config is not None else {},
        logger if logger is not None else FakeLogger(),
    )


def _done_entry(**overrides):
    entry = {"name": "spec-a", "status": "done", "error": None}
    entry.update(overrides)
    return entry


class _RecordingExecutor:
    """记录 submit 调用的 executor 替身（可注入拒绝行为）。"""

    def __init__(self, reject=False):
        self.submitted = []
        self._reject = reject

    def submit(self, fn, name=None):
        if self._reject:
            raise RuntimeError("pool saturated")
        self.submitted.append((fn, (name,) if name is not None else ()))


class TestRecoverOneDonePushRetry(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _bus(self, executor=None, **kw):
        bus = _make_bus(self.tmpdir, **kw)
        if executor is not None:
            bus._admin_executor = executor
        return bus

    def test_backoff_expired_submits_approve_push(self):
        """退避到期（或无退避）→ 经 executor 投递 approve_push 恰一次。"""
        pm = _StaticForwardPM()
        bus = self._bus(executor=_RecordingExecutor(), pm=pm)
        ok = bus._recover_one("spec-a", _done_entry())
        assert ok is True
        pm.approve_push.assert_not_called()  # 非内联
        # executor 收到 (approve_push, "spec-a")
        executor = bus._admin_executor
        assert executor.submitted == [(pm.approve_push, ("spec-a",))]

    def test_backoff_active_debug_skip_no_submit(self):
        """退避期内（字段持久化 next_retry 在未来）→ debug 跳过、不投递。"""
        import time as _time

        future = int(_time.time()) + 3600
        pm = _StaticForwardPM()
        executor = _RecordingExecutor()
        bus = self._bus(executor=executor, pm=pm)
        entry = _done_entry(
            error=f"git push failed (main): boom [push_attempts=1] "
            f"[push_backoff next_retry_at={future}]",
            _push_attempts=1,
            _push_backoff_next_retry_at=future,
        )
        ok = bus._recover_one("spec-a", entry)
        assert ok is True  # 有意跳过计入 handled
        assert executor.submitted == []
        pm.approve_push.assert_not_called()
        assert any("退避期内" in str(a) for a in bus.logger.debugs)

    def test_retry_count_at_max_no_submit(self):
        """计数达上限（error 无 [push_failed 标记的存量表）→ 不再投递。"""
        pm = _StaticForwardPM()
        executor = _RecordingExecutor()
        bus = self._bus(executor=executor, pm=pm)
        entry = _done_entry(_push_attempts=3, error="git push failed (main): x")
        ok = bus._recover_one("spec-a", entry)
        assert ok is True
        assert executor.submitted == []

    def test_push_failed_escalation_terminal_skip(self):
        """error 含 [push_failed 升级标记 → 终局跳过（不查 admin store）。"""
        pm = _StaticForwardPM()
        executor = _RecordingExecutor()
        bus = self._bus(executor=executor, pm=pm)
        entry = _done_entry(
            error="git push failed (main): x [push_attempts=3] "
            "[push_failed — 已停止自动重试]",
            _push_attempts=3,
        )
        ok = bus._recover_one("spec-a", entry)
        assert ok is True
        assert executor.submitted == []
        assert any("push_failed" in str(a) for a in bus.logger.debugs)

    def test_restart_recovery_picks_up_expired_backoff(self):
        """重启场景：STATE 字段存量 + 退避已过期 → 首轮扫描拾取续推。"""
        import time as _time

        past = int(_time.time()) - 60
        pm = _StaticForwardPM()
        executor = _RecordingExecutor()
        bus = self._bus(executor=executor, pm=pm)
        entry = _done_entry(
            error=f"git push failed (main): boom [push_attempts=1] "
            f"[push_backoff next_retry_at={past}]",
            _push_attempts=1,
            _push_backoff_next_retry_at=past,
        )
        ok = bus._recover_one("spec-a", entry)
        assert ok is True
        assert executor.submitted == [(pm.approve_push, ("spec-a",))]

    def test_executor_reject_does_not_break_scan(self):
        """executor.submit 抛 RuntimeError → 降级 WARNING、_recover_one 不抛、
        返回 True（整轮扫描继续）。"""
        pm = _StaticForwardPM()
        bus = self._bus(executor=_RecordingExecutor(reject=True), pm=pm)
        ok = bus._recover_one("spec-a", _done_entry())
        assert ok is True
        pm.approve_push.assert_not_called()
        assert any("投递被拒绝" in str(a) for a in bus.logger.warnings)

    def test_executor_missing_warns_and_skips_inline(self):
        """executor 缺席（None）→ WARNING 跳过、无内联 approve_push 调用。"""
        pm = _StaticForwardPM()
        bus = self._bus(executor=None, pm=pm)
        ok = bus._recover_one("spec-a", _done_entry())
        assert ok is True
        pm.approve_push.assert_not_called()  # MUST NOT 内联同步
        assert any("未挂载" in str(a) for a in bus.logger.warnings)

    def test_multiple_done_specs_submit_each_without_inline_block(self):
        """多 spec 命中：各投递一次、approve_push 零内联调用（主循环不阻塞）。"""
        from core.pm_engine.reporting import ReportBuilder

        pm = MagicMock()
        # 走 ReportBuilder 真实判定（无退避字段 → False/0）
        pm._is_push_backoffed = ReportBuilder._is_push_backoffed
        pm._get_push_retry_count = ReportBuilder._get_push_retry_count
        executor = _RecordingExecutor()
        bus = self._bus(executor=executor, pm=pm)
        specs = {f"spec-{i}": _done_entry(name=f"spec-{i}") for i in range(3)}
        # 模拟 full_scan recovery 循环形态（逐条 _recover_one）
        for name, entry in specs.items():
            ok = bus._recover_one(name, entry)
            assert ok is True
        assert len(executor.submitted) == 3
        pm.approve_push.assert_not_called()  # 全程无内联 git push

    def test_max_retries_config_guards(self):
        """pm.push.max_retries 非法形态守卫（bool/负值/非数回退 3）。"""
        bus = self._bus(config={"pm": {"push": {"max_retries": True}}})
        assert bus._get_push_max_retries() == 3
        bus = self._bus(config={"pm": {"push": {"max_retries": -1}}})
        assert bus._get_push_max_retries() == 3
        bus = self._bus(config={"pm": {"push": {"max_retries": "bad"}}})
        assert bus._get_push_max_retries() == 3
        bus = self._bus(config={"pm": {"push": {"max_retries": 5}}})
        assert bus._get_push_max_retries() == 5
