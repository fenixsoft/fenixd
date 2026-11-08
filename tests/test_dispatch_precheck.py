"""tests/test_dispatch_precheck.py — add-dispatch-precheck-true-fallback 任务 2.5

覆盖 spec 三 Requirement 全部 Scenario：
1. 派发前置 harness 可达性自检：CLI 不在 PATH → 短路返回带归因标记的失败
   （不进重试、不建 worktree、零 subprocess）；CLI 可达 → 零噪音放行；
   daemon 启动自检发现不可达 → 一条升级告警（进程内 run-once 去重）。
2. 归因与豁免：错误证据带 ``[harness-cli-unavailable]`` 标记；带标记的
   秒挂不计入 instant-fail-storm，带标记的终态 run 不计入 repeated-failures。
3. PATH 缺陷自愈闭环：基线目录在盘但不在 PATH → 幂等追加 systemd.env +
   写 restart_request 请求重启生效；binary 全盘皆无 → 不盲写 env。
"""
import json
import time
from pathlib import Path

import pytest

import fenixd
from core.agent_runner.harness import (
    HARNESS_CLI_UNAVAILABLE_MARKER,
    HARNESS_EXECUTABLE_NAMES,
    VALID_HARNESS_VALUES,
    precheck_harness_executable,
)
from core.agent_runner.harness.dsh_adapter import HarnessHealthError
from core.agent_runner.runner import AgentRunner
from core.admin_monitor import AdminMonitor


class _StubLogger:
    """双参（channel, message）形态的最小 logger 存根。"""

    def __init__(self):
        self.records = []

    def _record(self, level, channel, message):
        self.records.append((level, channel, message))

    def debug(self, channel, message):
        self._record("debug", channel, message)

    def info(self, channel, message):
        self._record("info", channel, message)

    def warning(self, channel, message):
        self._record("warning", channel, message)

    def error(self, channel, message):
        self._record("error", channel, message)

    def messages(self, level=None):
        return [r[2] for r in self.records if level is None or r[0] == level]


class _StubStore:
    """append_if_absent 内存存根：与 AdminStore 同形（谓词为真才落一条）。"""

    def __init__(self):
        self.entries = []

    def append_if_absent(self, entry, is_inflight):
        if any(is_inflight(e) for e in self.entries):
            return None
        self.entries.append(dict(entry))
        return entry


class _StubAdapter:
    """记录 spawn / check_health 调用的适配器存根。"""

    def __init__(self, name="claude", health_error=None):
        self.name = name
        self.spawn_calls = []
        self.health_calls = []
        self._health_error = health_error

    def build_spawn_spec(self, request):
        self.spawn_calls.append(request)
        return {"cmd": [self.name], "cwd": str(Path.cwd())}

    def check_health(self):
        self.health_calls.append(True)
        if self._health_error is not None:
            raise self._health_error
        return {"ok": True}


def _make_runner(config=None):
    runner = AgentRunner.__new__(AgentRunner)
    runner.logger = _StubLogger()
    runner.config = config or {}
    return runner


def _make_daemon(tmp_path, harness="claude"):
    daemon = fenixd.FenixDaemon.__new__(fenixd.FenixDaemon)
    daemon._harness_precheck_done = False
    daemon.config = {"agent.harness": harness}
    daemon.logger = _StubLogger()
    daemon.admin_store = _StubStore()
    return daemon


# ---------------------------------------------------------------------------
# 2.2 派发前置可达性自检：短路 + 归因
# ---------------------------------------------------------------------------


class TestDispatchPrecheckShortCircuit:
    def test_missing_cli_short_circuits_with_marker(self, monkeypatch):
        """claude 不在 PATH：_execute_agent 零开销短路，错误带标记与指引。"""
        runner = _make_runner()
        adapter = _StubAdapter(name="claude")
        monkeypatch.setattr(
            "core.agent_runner.runner.resolve_adapter_from_config",
            lambda config: adapter,
        )
        monkeypatch.setattr("core.agent_runner.harness.shutil.which", lambda name: None)
        monkeypatch.setenv("PATH", "/usr/bin:/bin")

        result = runner._execute_agent("spec-a", "implementer", "impl-spec-a-1000000000")

        assert result.success is False
        assert result.error is not None
        assert HARNESS_CLI_UNAVAILABLE_MARKER in result.error
        assert "claude" in result.error
        assert "检查 PATH" in result.error
        # 短路：未进入 attempt 循环（无 spawn / 健康检查 subprocess）
        assert adapter.spawn_calls == []
        assert adapter.health_calls == []
        assert result.duration_seconds == 0.0
        # 拦截本身有一条 WARNING 留痕
        assert any("可达性自检" in m for m in runner.logger.messages("warning"))

    def test_reachable_cli_passes_through_zero_noise(self, monkeypatch):
        """CLI 可达：前置自检放行且零告警，流程继续到健康检查。"""
        runner = _make_runner()
        adapter = _StubAdapter(
            name="claude",
            health_error=HarnessHealthError("health probe boom"),
        )
        monkeypatch.setattr(
            "core.agent_runner.runner.resolve_adapter_from_config",
            lambda config: adapter,
        )
        monkeypatch.setattr(
            "core.agent_runner.harness.shutil.which", lambda name: "/usr/bin/claude"
        )

        result = runner._execute_agent("spec-a", "implementer", "impl-spec-a-1000000000")

        # 前置自检放行：流程到达健康检查并被其错误归因（无前置标记）
        assert adapter.health_calls == [True]
        assert result.success is False
        assert HARNESS_CLI_UNAVAILABLE_MARKER not in (result.error or "")
        assert "health probe boom" in (result.error or "")
        assert not any("可达性自检" in m for m in runner.logger.messages("warning"))

    def test_precheck_unit_message_shape(self, monkeypatch):
        """precheck_harness_executable：不可达 → 带标记/可执行名/PATH 摘要的消息。"""
        monkeypatch.setattr("core.agent_runner.harness.shutil.which", lambda name: None)
        monkeypatch.setenv("PATH", "/usr/bin:/bin")
        message = precheck_harness_executable("claude")
        assert message is not None
        assert message.startswith(HARNESS_CLI_UNAVAILABLE_MARKER)
        assert "claude" in message
        assert "/usr/bin:/bin" in message
        assert "检查 PATH" in message

    def test_precheck_unit_reachable_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            "core.agent_runner.harness.shutil.which", lambda name: "/usr/bin/dsh"
        )
        assert precheck_harness_executable("dsh") is None

    def test_executable_names_single_source(self):
        """spawn 面名字表与 harness 白名单一一对应（单源派生）。"""
        assert HARNESS_EXECUTABLE_NAMES == {name: name for name in VALID_HARNESS_VALUES}


# ---------------------------------------------------------------------------
# 2.2 daemon 启动自检：一条告警 + run-once 去重
# ---------------------------------------------------------------------------


class TestStartupPrecheckAlert:
    def _patch_env(self, monkeypatch, tmp_path):
        monkeypatch.setattr(fenixd, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(
            "core.systemd_hosting.PATH_BASELINE_DIRS", (str(tmp_path / "toolbin"),)
        )
        monkeypatch.setattr("core.agent_runner.harness.shutil.which", lambda name: None)
        monkeypatch.setenv("PATH", "/usr/bin:/bin")

    def test_unreachable_emits_single_deduped_alert(self, monkeypatch, tmp_path):
        """启动自检不可达：恰好一条 ESCALATION 告警，含安装指引；再调不重复。"""
        daemon = _make_daemon(tmp_path)
        self._patch_env(monkeypatch, tmp_path)
        # binary 全盘皆无、无 systemd.env：纯告警形态
        (tmp_path / "toolbin").mkdir()

        daemon._startup_harness_precheck()
        assert len(daemon.admin_store.entries) == 1
        entry = daemon.admin_store.entries[0]
        assert entry["signal_type"] == "harness_cli_unavailable"
        assert entry["severity"] == "major"
        assert "安装" in entry["recommended_action"]
        assert "executable=claude" in entry["evidence"]
        assert "binary_found_in=全基线目录均未找到" in entry["evidence"]
        assert "self_heal=未触发" in entry["evidence"]
        assert daemon.logger.messages("warning")

        # run-once 去重：同进程二次调用零追加
        daemon._startup_harness_precheck()
        assert len(daemon.admin_store.entries) == 1

    def test_reachable_startup_is_silent(self, monkeypatch, tmp_path):
        """可达：零告警零噪音，run-once 旗标置位。"""
        daemon = _make_daemon(tmp_path)
        monkeypatch.setattr(fenixd, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(
            "core.systemd_hosting.PATH_BASELINE_DIRS", (str(tmp_path / "toolbin"),)
        )
        monkeypatch.setattr(
            "core.agent_runner.harness.shutil.which",
            lambda name: str(tmp_path / "toolbin" / name),
        )
        (tmp_path / "toolbin").mkdir()
        (tmp_path / "toolbin" / "claude").write_text("#!/bin/sh\n", encoding="utf-8")

        daemon._startup_harness_precheck()
        assert daemon.admin_store.entries == []
        assert daemon.logger.messages("warning") == []
        assert daemon._harness_precheck_done is True


# ---------------------------------------------------------------------------
# 2.4 PATH 缺陷自愈：幂等追加 + restart_request / 不盲写
# ---------------------------------------------------------------------------


class TestStartupSelfHeal:
    def _setup_healable(self, monkeypatch, tmp_path):
        """binary 在基线目录、systemd.env 在盘、PATH 缺该目录的可自愈环境。"""
        toolbin = tmp_path / "toolbin"
        toolbin.mkdir()
        (toolbin / "claude").write_text("#!/bin/sh\n", encoding="utf-8")
        fenix_dir = tmp_path / ".fenix"
        fenix_dir.mkdir()
        env_file = fenix_dir / "systemd.env"
        env_file.write_text("FOO=1\nPATH=/usr/bin:/bin\n", encoding="utf-8")
        monkeypatch.setattr(fenixd, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(
            "core.systemd_hosting.PATH_BASELINE_DIRS", (str(toolbin),)
        )
        monkeypatch.setattr("core.agent_runner.harness.shutil.which", lambda name: None)
        monkeypatch.setenv("PATH", "/usr/bin:/bin")
        return env_file

    def test_selfheal_appends_env_and_requests_restart(self, monkeypatch, tmp_path):
        env_file = self._setup_healable(monkeypatch, tmp_path)
        daemon = _make_daemon(tmp_path)

        daemon._startup_harness_precheck()

        # 幂等追加：目录以尾部形式并入，其余键保留
        text = env_file.read_text(encoding="utf-8")
        assert f"/usr/bin:/bin:{tmp_path / 'toolbin'}" in text
        assert "FOO=1" in text
        assert text.count(str(tmp_path / "toolbin")) == 1
        # 重启请求落位且形态完整
        request = json.loads(
            (tmp_path / ".fenix" / "restart_request").read_text(encoding="utf-8")
        )
        assert request["origin"] == "harness-path-selfheal"
        assert request["reason"]
        assert request["date"]
        # 告警形态：已自愈 + 重启待生效
        entry = daemon.admin_store.entries[0]
        assert f"binary_found_in={tmp_path / 'toolbin'}" in entry["evidence"]
        assert "self_heal=已追加" in entry["evidence"]
        assert "重启" in entry["recommended_action"]

    def test_selfheal_is_idempotent_across_restarts(self, monkeypatch, tmp_path):
        """第二次自愈（模拟重启后新进程）：env 不重复追加、不重复请求重启。"""
        env_file = self._setup_healable(monkeypatch, tmp_path)
        _make_daemon(tmp_path)._startup_harness_precheck()
        first_text = env_file.read_text(encoding="utf-8")
        request_path = tmp_path / ".fenix" / "restart_request"
        first_request = request_path.read_text(encoding="utf-8")

        # 新 daemon 实例 = 重启后的新进程（run-once 旗标复位）
        _make_daemon(tmp_path)._startup_harness_precheck()

        assert env_file.read_text(encoding="utf-8") == first_text
        assert request_path.read_text(encoding="utf-8") == first_request

    def test_binary_nowhere_no_blind_env_write(self, monkeypatch, tmp_path):
        """binary 全盘皆无：不写 env、不请求重启，告警给安装指引（盲写门）。"""
        toolbin = tmp_path / "toolbin"
        toolbin.mkdir()
        monkeypatch.setattr(fenixd, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(
            "core.systemd_hosting.PATH_BASELINE_DIRS", (str(toolbin),)
        )
        monkeypatch.setattr("core.agent_runner.harness.shutil.which", lambda name: None)
        monkeypatch.setenv("PATH", "/usr/bin:/bin")
        daemon = _make_daemon(tmp_path)

        daemon._startup_harness_precheck()

        assert not (tmp_path / ".fenix" / "systemd.env").exists()
        assert not (tmp_path / ".fenix" / "restart_request").exists()
        entry = daemon.admin_store.entries[0]
        assert "安装" in entry["recommended_action"]


# ---------------------------------------------------------------------------
# 2.3 豁免面：带标记失败不计入秒挂风暴 / 重复失败计数
# ---------------------------------------------------------------------------


class TestEscalationExemption:
    def test_instant_fail_skips_marker_error(self):
        """带标记秒挂：不计入 instant-fail 计数（守卫先于计数）。"""
        runner = AgentRunner.__new__(AgentRunner)
        runner.logger = _StubLogger()
        runner._record_instant_fail(
            "spec-a",
            0.1,
            run_file=None,
            error=f"{HARNESS_CLI_UNAVAILABLE_MARKER} claude 不在 PATH",
        )
        assert "_instant_fail_state" not in runner.__dict__

    def test_instant_fail_counts_plain_error(self):
        """对照组：普通秒挂照常计数（豁免只对带标记的错误生效）。"""
        runner = AgentRunner.__new__(AgentRunner)
        runner.logger = _StubLogger()
        runner.config = {}
        runner._record_instant_fail(
            "spec-a", 0.1, run_file=None, error="boom: health check failed"
        )
        assert "spec-a" in runner._instant_fail

    @staticmethod
    def _write_terminal_run(runs_dir: Path, run_id: str, error: str) -> Path:
        runs_dir.mkdir(parents=True, exist_ok=True)
        run_file = runs_dir / f"{run_id}.jsonl"
        run_file.write_text(
            json.dumps({"type": "error", "error": error}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return run_file

    def test_repeated_failures_skip_marker_runs(self, monkeypatch, tmp_path):
        """带标记终态 run 不计入 repeated-failures；普通失败照常成信号。"""
        import core.admin_monitor as admin_monitor_module

        monkeypatch.setattr(admin_monitor_module, "REPEAT_FAILURE_THRESHOLD", 1)
        monitor = AdminMonitor.__new__(AdminMonitor)
        monitor.project_root = tmp_path
        runs_dir = tmp_path / ".fenix" / "runs"

        marker_error = f"{HARNESS_CLI_UNAVAILABLE_MARKER} claude 不在 PATH"
        self._write_terminal_run(runs_dir, "impl-spec-a-1000000000", marker_error)
        assert monitor._detect_repeated_failures(now=time.time()) == []

        self._write_terminal_run(runs_dir, "impl-spec-b-1000000000", "boom")
        signals = monitor._detect_repeated_failures(now=time.time())
        assert len(signals) == 1
        assert signals[0]["spec"] == "spec-b"
