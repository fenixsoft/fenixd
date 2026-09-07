"""add-run-cancel 能力测试（对应 spec/changes/add-run-cancel tasks 5.1-5.3）。

覆盖：
- runner 取消原语：cancel_run 返回值/归一化/旗标登记/not_running、_run_claude
  轮询环终止子进程 + cancelled 终态行、_execute_agent 取消路径（无 attempt 2、
  不派发后续 attempt、不计秒挂、cancelled 序列化、不触碰 status）
- dispatch hold-state：implementer 取消后 spec 保持 implementing、
  verifier 取消后 spec 保持 testing
- 文件信号链路：合法请求被消费、损坏 JSON 删除、重复请求冲突、
  API 400/404/409/200 语义
"""

import json
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.agent_runner import (
    AGENT_TERMINATE_GRACE_SECONDS,
    AgentRunner,
    AgentRunResult,
    RunCancelledError,
    append_run_line,
)
from core.agent_runner import runner as runner_module
from core.state_machine import StateMachine
import fenixd as _fenixd_mod


class FakeLogger:
    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


def make_runner(proot: Path) -> AgentRunner:
    """构造最小 AgentRunner 实例（不触发真实 __init__，测试补丁缝对齐）。"""
    runner = AgentRunner.__new__(AgentRunner)
    runner.config = {}
    runner.worktree_manager = None
    runner.state_machine = None
    runner.project_root = proot
    runner.logger = FakeLogger()
    runner._running_agents = {}
    runner._daily_run_count = 0
    runner._daily_reset_date = None
    runner._daily_provider_attempts = {}
    runner._daily_provider_warned = {}
    runner.provider_circuits = {}
    return runner


def spawn_sleep(seconds: float) -> subprocess.Popen:
    """起一个长 sleep 子进程，模拟在跑 agent。"""
    return subprocess.Popen(
        ["python3", "-c", f"import time; time.sleep({seconds})"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def read_run_file(proot: Path, run_id: str) -> list:
    p = proot / ".fenix" / "runs" / f"{run_id}.jsonl"
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


# ════════════════════════════════════════════════════════════════════
# 5.1 runner 取消原语
# ════════════════════════════════════════════════════════════════════


class TestCancelRunPrimitive:
    def test_cancel_active_run_returns_cancel_requested(self, tmp_path):
        proot = tmp_path / "proj"
        proot.mkdir()
        runner = make_runner(proot)
        proc = spawn_sleep(30)
        runner._running_agents["impl-x-123-a1"] = proc
        try:
            result = runner.cancel_run("impl-x-123", reason="测试取消", by="admin")
            assert result["status"] == "cancel_requested"
            assert result["attempts"] == ["impl-x-123-a1"]
            assert result["base_run_id"] == "impl-x-123"
            with runner._cancel_requested_lock:
                assert "impl-x-123" in runner._cancel_requested
        finally:
            proc.kill()
            proc.wait()

    def test_cancel_finished_run_returns_not_running(self, tmp_path):
        proot = tmp_path / "proj"
        proot.mkdir()
        runner = make_runner(proot)
        result = runner.cancel_run("impl-x-123", reason="x")
        assert result["status"] == "not_running"
        with runner._cancel_requested_lock:
            assert "impl-x-123" not in runner._cancel_requested

    @pytest.mark.parametrize("cancel_arg", ["impl-x-123", "impl-x-123-a2"])
    def test_cancel_run_id_base_normalization(self, tmp_path, cancel_arg):
        """基础 run_id 与 -a2 后缀两种调用命中同一旗标（基础归一化）。"""
        proot = tmp_path / "proj"
        proot.mkdir()
        runner = make_runner(proot)
        proc = spawn_sleep(30)
        runner._running_agents["impl-x-123-a2"] = proc
        try:
            result = runner.cancel_run(cancel_arg, reason="r")
            assert result["status"] == "cancel_requested"
            with runner._cancel_requested_lock:
                assert "impl-x-123" in runner._cancel_requested
        finally:
            proc.kill()
            proc.wait()

    def test_cancel_run_does_not_touch_state_machine(self, tmp_path):
        proot = tmp_path / "proj"
        proot.mkdir()
        runner = make_runner(proot)
        sm = MagicMock()
        runner.state_machine = sm
        proc = spawn_sleep(30)
        runner._running_agents["impl-x-123-a1"] = proc
        try:
            runner.cancel_run("impl-x-123")
            # cancel_run 自身不做任何状态转换/写 status
            sm.transition.assert_not_called()
            sm.update_spec.assert_not_called()
        finally:
            proc.kill()
            proc.wait()

    def test_to_dict_contains_cancelled(self, tmp_path):
        r = AgentRunResult("rid", "spec", "implementer", success=False,
                           duration_seconds=1.0, error="cancelled by admin: x",
                           cancelled=True)
        d = r.to_dict()
        assert d["cancelled"] is True
        # 默认 False
        r2 = AgentRunResult("rid", "spec", "implementer", success=True,
                            duration_seconds=1.0)
        assert r2.to_dict()["cancelled"] is False


class TestRunClaudeCancelPolling:
    def test_polling_loop_terminates_process_and_writes_cancelled(self, tmp_path, monkeypatch):
        """活跃子进程被取消：轮询环 SIGTERM，jsonl 末行为 cancelled 终态行。"""
        proot = tmp_path / "proj"
        (proot / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
        runner = make_runner(proot)
        runner.config = {"agents": {"run_timeout_seconds": 3600}}

        # 用长 sleep 替身进程替代 claude CLI
        orig_popen = runner_module.subprocess.Popen

        def fake_popen(cmd, **kw):
            kw.pop("text", None)
            kw.pop("bufsize", None)
            kw.pop("env", None)
            kw.pop("cwd", None)
            return orig_popen(["python3", "-c", "import time; time.sleep(30)"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        monkeypatch.setattr(runner_module.subprocess, "Popen", fake_popen)

        outcome = {}

        def worker():
            try:
                runner._run_claude(
                    "prompt", proot, "impl-x-123-a1",
                    model_override="m", max_turns=50,
                    spec_name="x", agent_type="implementer",
                )
                outcome["result"] = "returned"
            except RunCancelledError as e:
                outcome["result"] = "cancelled"
                outcome["reason"] = e.reason
                outcome["by"] = e.by
            except Exception as e:  # noqa: BLE001
                outcome["result"] = f"err:{e}"

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        # 等待 attempt 进程登记
        deadline = time.time() + 5
        while time.time() < deadline and "impl-x-123-a1" not in runner._running_agents:
            time.sleep(0.05)
        assert "impl-x-123-a1" in runner._running_agents

        result = runner.cancel_run("impl-x-123", reason="测试取消", by="admin")
        assert result["status"] == "cancel_requested"

        t.join(timeout=AGENT_TERMINATE_GRACE_SECONDS + 5)
        assert outcome.get("result") == "cancelled"
        assert outcome.get("reason") == "测试取消"
        assert outcome.get("by") == "admin"

        # 终态行为 cancelled 行，且不含 interrupted/error 终态
        lines = read_run_file(proot, "impl-x-123-a1")
        assert lines[-1]["type"] == "cancelled"
        assert lines[-1]["reason"] == "测试取消"
        assert lines[-1]["by"] == "admin"
        assert not any(l.get("type") in ("interrupted", "error") for l in lines)

        # 旗标被清理（run 收尾防泄漏）
        with runner._cancel_requested_lock:
            assert "impl-x-123" not in runner._cancel_requested
        assert "impl-x-123-a1" not in runner._running_agents


class TestExecuteAgentCancel:
    def _patch_exec_deps(self, runner, proot, run_claude_side_effect):
        """给 runner 装上可跑 _execute_agent 的 worktree_manager / _run_claude mock。"""
        wm = MagicMock()
        wm.create.return_value = proot / "wt"
        runner.worktree_manager = wm
        runner.state_machine = MagicMock()
        runner.state_machine.read_one.return_value = {}
        runner._get_config = lambda key, default=None: {
            "agents.max_retries": 3,
        }.get(key, default)
        runner._run_claude = MagicMock(side_effect=run_claude_side_effect)
        runner._extract_usage_info = lambda r: {}
        runner._accumulate_token_usage = lambda *a, **k: None
        runner._record_verify_progress_tokens = lambda *a, **k: None
        runner._check_daily_limit = lambda: None
        runner._get_agent_model_assignment = lambda at: []
        runner._v2_launch_for_worktree = lambda wt: None
        runner._v2_stop_for_worktree = lambda wt: None
        runner._v2_inject_env = lambda wt: {}
        runner._build_prompt = lambda *a, **k: "prompt"
        runner._resumable_session_id = lambda *a, **k: None
        runner._record_daily_provider_attempt = lambda p: None
        runner._select_chain_candidate = lambda *a, **k: 0
        runner._daily_run_count = 0

    def test_attempt1_cancelled_no_attempt2(self, tmp_path):
        """attempt 1 被取消：返回 cancelled=True，无 -a2 attempt 文件。"""
        proot = tmp_path / "proj"
        proot.mkdir()
        runner = make_runner(proot)
        self._patch_exec_deps(
            runner, proot,
            run_claude_side_effect=lambda *a, **k: (_ for _ in ()).throw(
                RunCancelledError("真测试取消", "admin")),
        )

        r = runner._execute_agent("spec", "implementer", "impl-spec-123")
        assert r.cancelled is True
        assert r.success is False
        assert "cancelled by admin" in r.error
        assert "真测试取消" in r.error
        # 无 -a2 文件
        assert not (proot / ".fenix" / "runs" / "impl-spec-123-a2.jsonl").exists()
        # 收尾清理旗标
        with runner._cancel_requested_lock:
            assert "impl-spec-123" not in runner._cancel_requested

    def test_attempt_gap_flag_prevents_next_attempt(self, tmp_path):
        """attempt 1 正常失败结束、attempt 2 派发前设旗标 → 不再派发。"""
        proot = tmp_path / "proj"
        proot.mkdir()
        runner = make_runner(proot)

        def gap_run_claude(*a, **k):
            # 第一次调用（attempt 1）模拟正常失败，并登记取消旗标
            runner._cancel_requested.add("impl-spec-123")
            raise RuntimeError("普通失败")

        self._patch_exec_deps(runner, proot, gap_run_claude)

        # 跳过 attempt 间 sleep(10)
        import core.agent_runner.runner as _rm
        orig_sleep = _rm.time.sleep

        def fake_sleep(sec):
            pass

        _rm.time.sleep = fake_sleep
        try:
            r = runner._execute_agent("spec", "implementer", "impl-spec-123")
        finally:
            _rm.time.sleep = orig_sleep

        assert r.cancelled is True
        assert r.success is False
        assert "cancelled by admin" in r.error
        # _run_claude 只被调用一次（attempt 1），attempt 2 顶部检查即返回
        assert runner._run_claude.call_count == 1
        assert not (proot / ".fenix" / "runs" / "impl-spec-123-a2.jsonl").exists()

    def test_cancel_does_not_increment_instant_fail(self, tmp_path):
        """取消不增秒挂计数（与框架主动 SIGTERM 同待遇）。"""
        proot = tmp_path / "proj"
        proot.mkdir()
        runner = make_runner(proot)
        self._patch_exec_deps(
            runner, proot,
            run_claude_side_effect=lambda *a, **k: (_ for _ in ()).throw(
                RunCancelledError("cancel", "admin")),
        )
        runner._execute_agent("spec", "implementer", "impl-spec-123")
        assert runner._instant_fail_counts("spec") == 0


# ════════════════════════════════════════════════════════════════════
# 5.2 dispatch hold-state 处置
# ════════════════════════════════════════════════════════════════════


def _make_pm_engine(proot: Path, config=None, agent_runner=None):
    from core.pm_engine import PMEngine
    logger = MagicMock()
    for m in ("info", "warning", "error", "debug"):
        setattr(logger, m, MagicMock())
    ar = agent_runner or MagicMock()
    return PMEngine(MagicMock(), ar, config or {}, proot, logger)


class TestDispatchHoldState:
    def test_implementer_cancelled_holds_state(self, tmp_path):
        """implementing spec 实现 run 被取消：status 保持 implementing、retry 不变、无入队。"""
        from core.pm_engine import PMEngine
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        logger = MagicMock()
        sm = StateMachine(proot / ".fenix" / "STATE.md", logger)
        sm.add_spec("demo", {"priority": 5})
        sm.transition("demo", "ready")
        sm.transition("demo", "implementing")

        ar = MagicMock()
        ar.worktree_manager.find_implementer_worktree.return_value = None
        ar.run_implementer.return_value = AgentRunResult(
            "impl-demo-1", "demo", "implementer",
            success=False, duration_seconds=10.0,
            error="cancelled by admin: 测试取消", cancelled=True,
        )
        engine = PMEngine(sm, ar, {}, proot, logger)
        # _read_implementer_result 读不到文件 → None（走项目根回退）
        engine._read_implementer_result = MagicMock(return_value=None)

        engine._run_agent_worker("demo", "implementer", 5)

        entry = sm.read_one("demo")
        assert entry["status"] == "implementing"
        assert entry.get("_retry_count", 0) == 0
        assert "run 被人工取消" in (entry.get("error") or "")
        # 不入队重派（队列保持空）
        assert engine._run_queue == []

    def test_verifier_cancelled_holds_state(self, tmp_path):
        """testing spec verifier run 被取消：status 保持 testing。"""
        from core.pm_engine import PMEngine
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        logger = MagicMock()
        sm = StateMachine(proot / ".fenix" / "STATE.md", logger)
        sm.add_spec("demo", {"priority": 5})
        for st in ("ready", "implementing", "implemented", "testing"):
            sm.transition("demo", st)

        ar = MagicMock()
        ar.worktree_manager.find_implementer_worktree.return_value = None
        ar.run_verifier.return_value = AgentRunResult(
            "verify-demo-1", "demo", "verifier",
            success=False, duration_seconds=10.0,
            error="cancelled by admin: 测试取消", cancelled=True,
        )
        engine = PMEngine(sm, ar, {"agents": {"use_new_verifier": False}}, proot, logger)

        engine._run_verification_pipeline("demo")

        entry = sm.read_one("demo")
        assert entry["status"] == "testing"
        assert "run 被人工取消" in (entry.get("error") or "")
        assert engine._run_queue == []


# ════════════════════════════════════════════════════════════════════
# 5.3 文件信号链路
# ════════════════════════════════════════════════════════════════════


class TestCancelRequestData:
    def test_request_run_cancel_writes_file(self, tmp_path):
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        from core.dashboard import data as dash_data
        result = dash_data.request_run_cancel(proot, "impl-x-123", "测试")
        assert result["ok"] is True
        assert result["conflict"] is False
        req = proot / ".fenix" / "cancel_run_request.json"
        assert req.is_file()
        payload = json.loads(req.read_text(encoding="utf-8"))
        assert payload["run_id"] == "impl-x-123"
        assert payload["reason"] == "测试"
        assert payload["source"] == "dashboard"
        assert payload["created"]

    def test_duplicate_request_conflict(self, tmp_path):
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        from core.dashboard import data as dash_data
        first = dash_data.request_run_cancel(proot, "impl-x-123", "r1")
        assert first["ok"] is True
        second = dash_data.request_run_cancel(proot, "impl-x-456", "r2")
        assert second["ok"] is False
        assert second["conflict"] is True
        assert second["created"] == first["created"]  # 含既有请求 created

    def test_missing_run_id(self, tmp_path):
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        from core.dashboard import data as dash_data
        result = dash_data.request_run_cancel(proot, "")
        assert result["ok"] is False
        assert result["missing_run_id"] is True


class _FakeDaemon(_fenixd_mod.FenixDaemon):
    """FenixDaemon 子类替身：复用真实 _check_cancel_requests，仅注入所需属性。"""

    def __init__(self, project_root, runner, logger):
        super().__init__()
        self.running = True
        self.agent_runner = runner
        self.logger = logger
        self._project_root = project_root


class TestCancelRequestPickup:
    def _write_request(self, proot, run_id="impl-x-123", reason="r", source="dashboard"):
        req = proot / ".fenix" / "cancel_run_request.json"
        req.parent.mkdir(parents=True, exist_ok=True)
        req.write_text(json.dumps({
            "run_id": run_id, "reason": reason,
            "source": source, "created": "2026-09-04T00:00:00+00:00",
        }), encoding="utf-8")
        return req

    def _pickup(self, monkeypatch, proot, daemon):
        import fenixd as _fenixd_mod
        monkeypatch.setattr(_fenixd_mod, "PROJECT_ROOT", proot)
        daemon._check_cancel_requests()

    def test_legal_request_consumed_and_cancel_run_called(self, tmp_path, monkeypatch):
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        runner = MagicMock()
        daemon = _FakeDaemon(proot, runner, FakeLogger())
        req = self._write_request(proot)
        self._pickup(monkeypatch, proot, daemon)
        # cancel_run 被以 run_id/reason/by=source 调用一次
        assert runner.cancel_run.call_count == 1
        args, kwargs = runner.cancel_run.call_args
        assert args[0] == "impl-x-123"
        assert kwargs.get("reason") == "r"
        assert kwargs.get("by") == "dashboard"
        # 信号文件已删除
        assert not req.exists()

    def test_corrupt_request_deleted_without_exception(self, tmp_path, monkeypatch):
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        req = proot / ".fenix" / "cancel_run_request.json"
        req.write_text("{ not valid json !!!", encoding="utf-8")
        runner = MagicMock()
        daemon = _FakeDaemon(proot, runner, FakeLogger())
        self._pickup(monkeypatch, proot, daemon)
        assert not req.exists()
        runner.cancel_run.assert_not_called()

    def test_missing_run_id_ignored(self, tmp_path, monkeypatch):
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        req = proot / ".fenix" / "cancel_run_request.json"
        req.write_text(json.dumps({"reason": "r"}), encoding="utf-8")
        runner = MagicMock()
        daemon = _FakeDaemon(proot, runner, FakeLogger())
        self._pickup(monkeypatch, proot, daemon)
        assert not req.exists()
        runner.cancel_run.assert_not_called()


# ── API 400/404/409/200 语义（dashboard server）───────────────────

class _TestServer:
    def __init__(self, registry, static_dir):
        from core.dashboard.server import (
            DashboardHTTPServer, find_free_port,
        )
        self.port = find_free_port(21000)
        self.httpd = DashboardHTTPServer(("127.0.0.1", self.port), registry, static_dir)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def post(self, path: str):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("POST", path)
            resp = conn.getresponse()
            body = resp.read()
            try:
                data = json.loads(body)
            except Exception:  # noqa: BLE001
                data = None
            return resp.status, data
        finally:
            conn.close()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture()
def run_cancel_server(tmp_path):
    from core.dashboard.registry import Registry
    proot = tmp_path / "proj"
    (proot / ".fenix").mkdir(parents=True, exist_ok=True)
    (proot / ".fenix" / "STATE.md").write_text(
        "# Fenix Project State\n\n## Specs\n\n"
        "### myspec\n- status: ready\n- priority: 5\n"
        "- created: 2026-01-01T00:00:00+00:00\n"
        "- updated: 2026-01-01T00:00:00+00:00\n- error: null\n",
        encoding="utf-8",
    )
    cfg = tmp_path / "dashboard.yaml"
    reg = Registry(config_path=cfg)
    reg.save({"port": 8787, "projects": [{"name": "proj", "path": str(proot)}],
              "scan_dirs": []})
    srv = _TestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
    yield proot, srv
    srv.stop()


class TestRunCancelAPI:
    def test_api_accepts_valid_request(self, run_cancel_server):
        import urllib.parse
        proot, srv = run_cancel_server
        reason = urllib.parse.quote("测试取消")
        status, data = srv.post(f"/api/run-cancel?project=proj&run_id=impl-x-123&reason={reason}")
        assert status == 200
        assert data["requested"] is True
        req = proot / ".fenix" / "cancel_run_request.json"
        assert req.is_file()
        payload = json.loads(req.read_text(encoding="utf-8"))
        assert payload["run_id"] == "impl-x-123"

    def test_api_missing_run_id_400(self, run_cancel_server):
        _, srv = run_cancel_server
        status, data = srv.post("/api/run-cancel?project=proj")
        assert status == 400

    def test_api_unknown_project_404(self, run_cancel_server):
        _, srv = run_cancel_server
        status, data = srv.post("/api/run-cancel?project=no-such&run_id=impl-x-123")
        assert status == 404

    def test_api_conflict_409(self, run_cancel_server):
        proot, srv = run_cancel_server
        status, _ = srv.post("/api/run-cancel?project=proj&run_id=impl-x-123")
        assert status == 200
        # 第二次请求（已有未消费文件）→ 409
        status2, data2 = srv.post("/api/run-cancel?project=proj&run_id=impl-x-456")
        assert status2 == 409
