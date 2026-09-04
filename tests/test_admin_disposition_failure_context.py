"""admin-disposition-failure-context 测试（fix-admin-disposition-empty-shell tasks 4.1）。

CLI 失败 → final 记录含 error / 兜底 recommended_action / description 非空；
成功记录不受影响；WARNING 日志在 _run_claude 异常时被调用。
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.admin_store import AdminStore, DISPOSITION
from core.admin_monitor import AdminMonitor
from core.agent_runner import AdminDisposition
from core.agent_runner.runner import AgentRunner, admin_disposition_path


# ── 辅助 ────────────────────────────────────────────────


def utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


def iso_ago(minutes: float) -> str:
    return datetime.fromtimestamp(time.time() - minutes * 60, tz=timezone.utc).isoformat()


class FakeLogger:
    def __init__(self):
        self.warnings = []
        self.errors = []

    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def warning(self, component: str, message: str, context=None):
        self.warnings.append({"component": component, "message": message, "context": context})

    def error(self, component: str, message: str, context=None):
        self.errors.append({"component": component, "message": message, "context": context})


class FakeSM:
    def __init__(self, specs: dict):
        self._specs = specs

    def read_all(self):
        return self._specs


class FailingRunner:
    """模拟 CLI 失败——run_administrator 返回 failed disposition。"""

    def __init__(self, error_text="claude CLI failed: Exit code: 143"):
        self.error_text = error_text
        self.calls = []

    def run_administrator(self, signal):
        self.calls.append(signal)
        return AdminDisposition(
            run_id=f"admin-{signal.get('spec')}-test-1",
            spec=signal.get("spec"),
            success=False,
            problem="",
            actions_taken="",
            result="failed",
            escalate=False,
            recommended_action="",
            summary="",
            error=self.error_text,
        )


class SuccessRunner:
    """模拟成功——run_administrator 返回 resolved disposition。"""

    def __init__(self):
        self.calls = []

    def run_administrator(self, signal):
        self.calls.append(signal)
        return AdminDisposition(
            run_id=f"admin-{signal.get('spec')}-test-1",
            spec=signal.get("spec"),
            success=True,
            problem="已诊断",
            actions_taken="重置状态",
            result="resolved",
            escalate=False,
            recommended_action="建议人工检查日志",
            summary="诊断结论：问题已解决。",
            error="",
        )


def make_signal(spec="spec-a", signal_type="stuck"):
    return {
        "signal_type": signal_type,
        "spec": spec,
        "severity": "major",
        "description": "卡滞 2 小时无进展",
        "evidence": "旧记录未更新",
        "recommended_action": "检查 spec-a 的 agent 进程是否存活",
    }


def make_monitor(tmp_path, specs, config=None, runner=None):
    proot = tmp_path / "proj"
    proot.mkdir(parents=True, exist_ok=True)
    logger = FakeLogger()
    mon = AdminMonitor(
        config or {},
        FakeSM(specs),
        proot,
        logger,
        store=AdminStore(proot, logger),
        agent_runner=runner,
    )
    return proot, mon, logger


# ── 核心断言 ─────────────────────────────────────────────


class TestFailedDispositionFailureContext:
    """CLI 失败 → final 记录含 error / 兜底 recommended_action / description 非空。"""

    def test_failed_record_carries_error(self, tmp_path):
        runner = FailingRunner("claude CLI failed: Exit code: 143")
        proot, mon, _ = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(120)},
        }, runner=runner)
        mon._invoke_administrator(make_signal(), None)
        recs = mon.store.read_all()
        disp = next(r for r in recs if r["kind"] == DISPOSITION)
        assert disp["result"] == "failed"
        assert disp["error"] == "claude CLI failed: Exit code: 143"
        assert disp["description"]  # description 非空

    def test_failed_record_recommended_action_fallback(self, tmp_path):
        runner = FailingRunner()
        proot, mon, _ = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(120)},
        }, runner=runner)
        signal = make_signal()
        mon._invoke_administrator(signal, None)
        recs = mon.store.read_all()
        disp = next(r for r in recs if r["kind"] == DISPOSITION)
        # recommended_action 应回退到信号值（disp.recommended_action 为空）
        assert disp["recommended_action"] == signal["recommended_action"]

    def test_failed_record_summary_allows_empty(self, tmp_path):
        runner = FailingRunner()
        proot, mon, _ = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(120)},
        }, runner=runner)
        mon._invoke_administrator(make_signal(), None)
        recs = mon.store.read_all()
        disp = next(r for r in recs if r["kind"] == DISPOSITION)
        assert disp["summary"] == ""  # summary 允许为空
        assert disp["error"]          # error 必须非空


class TestSuccessfulDispositionUnaffected:
    """成功记录不受影响：无 error 键或空串；recommended_action 取 disp 值。"""

    def test_successful_record_error_empty(self, tmp_path):
        runner = SuccessRunner()
        proot, mon, _ = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(120)},
        }, runner=runner)
        mon._invoke_administrator(make_signal(), None)
        recs = mon.store.read_all()
        disp = next(r for r in recs if r["kind"] == DISPOSITION)
        assert disp["result"] == "resolved"
        assert disp["error"] == ""

    def test_successful_record_recommended_action_not_fallback(self, tmp_path):
        runner = SuccessRunner()
        proot, mon, _ = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(120)},
        }, runner=runner)
        signal = make_signal()
        mon._invoke_administrator(signal, None)
        recs = mon.store.read_all()
        disp = next(r for r in recs if r["kind"] == DISPOSITION)
        # recommended_action 取 disp 值，不回退到 signal
        assert disp["recommended_action"] == "建议人工检查日志"

    def test_successful_record_preserves_all_fields(self, tmp_path):
        runner = SuccessRunner()
        proot, mon, _ = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(120)},
        }, runner=runner)
        mon._invoke_administrator(make_signal(), None)
        recs = mon.store.read_all()
        disp = next(r for r in recs if r["kind"] == DISPOSITION)
        assert disp["result"] == "resolved"
        assert disp["summary"] == "诊断结论：问题已解决。"
        assert disp["description"] == "已诊断"
        assert disp["error"] == ""


# ── run_administrator WARNING 日志 ──────────────────────


class TestRunAdministratorWarningLog:
    """_run_claude 异常路径产生 WARNING 日志（fix-admin-disposition-empty-shell）。"""

    def _make_runner(self, proot, logger):
        runner = AgentRunner.__new__(AgentRunner)
        runner.project_root = proot
        runner._get_config = lambda key, default=None: default
        runner._get_admin_model = lambda: "claude-sonnet-5"
        runner._get_agent_model_assignment = lambda agent_type: None
        runner._prompt_builder._build_prompt = lambda *a, **k: "prompt"

        def failing_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                               max_turns, spec_name=None, agent_type=None):
            raise RuntimeError("claude CLI failed: Exit code: 143")

        runner._run_claude = failing_run_claude
        runner.logger = logger
        return runner

    def test_warning_log_contains_run_id_and_error(self, tmp_path):
        logger = FakeLogger()
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        runner = self._make_runner(proot, logger)
        disp = runner.run_administrator(make_signal())

        # WARNING 日志被调用
        assert len(logger.warnings) >= 1
        warn = logger.warnings[0]
        assert warn["component"] == "agent_runner"
        assert disp.run_id in warn["message"]  # run_id 包含在内
        assert "Exit code: 143" in warn["message"]  # 异常文本包含在内

    def test_warning_log_context_has_run_id(self, tmp_path):
        logger = FakeLogger()
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        runner = self._make_runner(proot, logger)
        disp = runner.run_administrator(make_signal())

        warn = logger.warnings[0]
        assert warn["context"]["run_id"] == disp.run_id
        assert "Exit code: 143" in warn["context"]["error"]

    def test_failed_disposition_error_field_set(self, tmp_path):
        logger = FakeLogger()
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        runner = self._make_runner(proot, logger)
        disp = runner.run_administrator(make_signal())
        assert disp.success is False
        assert "Exit code: 143" in disp.error
        assert disp.result == "failed"
