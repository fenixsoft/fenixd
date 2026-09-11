"""
Tests for SPEC 审批推送（add-spec-approve-push-modal）。

Task 5.1：request_spec_approve_push 全分支 + _check_approve_push_requests 消费逻辑。
Task 5.3：幂等与竞态核对（连续两次 409、spec 已 pushed 后消费无 ERROR）。
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.dashboard import data as dash_data
from conftest import make_project  # noqa: E402
import fenixd as _fenixd_mod
from core.state_machine import StateMachine


# ── FakeLogger / FakeDaemon（复用 test_run_cancel.py 模式） ────────

class FakeLogger:
    def __init__(self):
        self.warnings = []
        self.infos = []
        self.errors = []

    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        self.infos.append(a)

    def warning(self, *a, **k):
        self.warnings.append(a)

    def error(self, *a, **k):
        self.errors.append(a)


class _FakeDaemon(_fenixd_mod.FenixDaemon):
    """FenixDaemon 子类替身：复用真实 _check_approve_push_requests，注入 pm_engine/logger。"""

    def __init__(self, project_root, pm_engine, logger):
        super().__init__()
        self.running = True
        self.pm_engine = pm_engine
        self.logger = logger


# ── 夹具 ─────────────────────────────────────────────────────────

def _make_done_project(tmp_path, spec_name="done-spec"):
    """构造含 done spec 的项目（用于 request_spec_approve_push 测试）。"""
    proot = make_project(tmp_path, name="proj-a", otherspec=False)
    sm = StateMachine(proot / ".fenix" / "STATE.md", None)
    sm.add_spec(spec_name, {"status": "done"})
    return proot, sm


def _make_pushed_project(tmp_path, spec_name="pushed-spec"):
    """构造含 pushed spec 的项目（用于 pushed 幂等拒绝测试）。"""
    proot = make_project(tmp_path, name="proj-a", otherspec=False)
    sm = StateMachine(proot / ".fenix" / "STATE.md", None)
    sm.add_spec(spec_name, {"status": "pushed"})
    return proot, sm


# ── request_spec_approve_push 全分支 ──────────────────────────────

class TestRequestSpecApprovePush:
    """request_spec_approve_push 单元测试：校验→信号写入各分支。"""

    def test_spec_not_found(self, tmp_path):
        """spec 不在 STATE.md → {ok: False, found: False}。"""
        proot, _ = _make_done_project(tmp_path)
        result = dash_data.request_spec_approve_push(proot, "ghost")
        assert result["ok"] is False
        assert result["found"] is False
        assert "not found" in result["error"]

    def test_non_done_ready_rejected(self, tmp_path):
        """status=ready（非 done）→ 403/terminal 拒绝，文案区分 pushed 与其它非 done 状态。"""
        proot = make_project(tmp_path, name="proj-a", otherspec=False)
        sm = StateMachine(proot / ".fenix" / "STATE.md", None)
        sm.add_spec("ready-spec", {"status": "ready"})
        result = dash_data.request_spec_approve_push(proot, "ready-spec")
        assert result["ok"] is False
        assert result["terminal"] is True
        assert "仅 done 状态可审批推送" in result["error"]
        assert "ready" in result["error"]

    def test_pushed_idempotent_rejected(self, tmp_path):
        """status=pushed → terminal 拒绝，文案为「已推送无需审批」。"""
        proot, _ = _make_pushed_project(tmp_path)
        result = dash_data.request_spec_approve_push(proot, "pushed-spec")
        assert result["ok"] is False
        assert result["terminal"] is True
        assert "已推送" in result["error"]

    def test_daemon_down_returns_409(self, tmp_path, monkeypatch):
        """daemon 未运行 → {ok: False, daemon_down: True}，信号文件不写入。"""
        proot, _ = _make_done_project(tmp_path)
        monkeypatch.setattr(dash_data, "_is_running", lambda p: False)
        result = dash_data.request_spec_approve_push(proot, "done-spec")
        assert result["ok"] is False
        assert result["daemon_down"] is True
        assert not (proot / dash_data.APPROVE_PUSH_REQUEST).exists()

    def test_conflict_returns_existing_created(self, tmp_path, monkeypatch):
        """已有未消费信号 → conflict，读既有 created 供返回。"""
        proot, _ = _make_done_project(tmp_path)
        monkeypatch.setattr(dash_data, "_is_running", lambda p: True)
        # 先写一条合法信号
        first_result = dash_data.request_spec_approve_push(proot, "done-spec")
        assert first_result["ok"] is True
        first_created = first_result["created"]
        # 第二次调用 → conflict
        second_result = dash_data.request_spec_approve_push(proot, "done-spec")
        assert second_result["ok"] is False
        assert second_result["conflict"] is True
        assert second_result["created"] == first_created

    def test_success_writes_payload_with_three_keys(self, tmp_path, monkeypatch):
        """校验通过 → 原子写入信号，payload 含 spec/source/created 三键，无 tmp 残留。"""
        proot, _ = _make_done_project(tmp_path)
        monkeypatch.setattr(dash_data, "_is_running", lambda p: True)
        result = dash_data.request_spec_approve_push(proot, "done-spec")
        assert result["ok"] is True
        assert result["found"] is True
        req_path = proot / dash_data.APPROVE_PUSH_REQUEST
        assert req_path.exists()
        payload = json.loads(req_path.read_text(encoding="utf-8"))
        assert payload["spec"] == "done-spec"
        assert payload["source"] == "dashboard"
        assert isinstance(payload["created"], str) and len(payload["created"]) > 10
        # 无 .tmp 残留
        tmp_files = list(proot.glob(".fenix/.approve_push_request.*.tmp"))
        assert not tmp_files


# ── _check_approve_push_requests 消费逻辑 ─────────────────────────

class TestCheckApprovePushRequests:
    """daemon 主循环消费 approve_push_request.json 信号的各分支。"""

    def _write_signal(self, proot, spec="done-spec", source="dashboard"):
        """写入审批推送信号文件。"""
        req_path = proot / ".fenix" / "approve_push_request.json"
        req_path.parent.mkdir(parents=True, exist_ok=True)
        req_path.write_text(json.dumps({
            "spec": spec, "source": source,
            "created": "2026-09-11T00:00:00+00:00",
        }), encoding="utf-8")
        return req_path

    def _pickup(self, monkeypatch, proot, daemon):
        """设置 PROJECT_ROOT 后触发消费。"""
        monkeypatch.setattr(_fenixd_mod, "PROJECT_ROOT", proot)
        daemon._check_approve_push_requests()

    def test_success_consumed_and_approve_push_called(self, tmp_path, monkeypatch):
        """成功消费：调用 pm_engine.approve_push 且信号文件已删。"""
        proot, _ = _make_done_project(tmp_path)
        mock_engine = type("MockEngine", (), {"approve_push": lambda self, spec: True})()
        logger = FakeLogger()
        daemon = _FakeDaemon(proot, mock_engine, logger)
        req = self._write_signal(proot, "done-spec")
        self._pickup(monkeypatch, proot, daemon)
        assert not req.exists()
        assert any("审批推送成功" in str(a) for a in logger.infos)

    def test_approve_push_returns_false_logs_warning(self, tmp_path, monkeypatch):
        """approve_push 返回 False → WARNING 日志，不重试（design D3）。"""
        proot, _ = _make_done_project(tmp_path)
        mock_engine = type("MockEngine", (), {"approve_push": lambda self, spec: False})()
        logger = FakeLogger()
        daemon = _FakeDaemon(proot, mock_engine, logger)
        req = self._write_signal(proot)
        self._pickup(monkeypatch, proot, daemon)
        assert not req.exists()
        assert any("审批推送未成功" in str(a) for a in logger.warnings)

    def test_corrupt_json_deleted_without_exception(self, tmp_path, monkeypatch):
        """损坏 JSON → 删除信号文件，不抛异常，不调 approve_push。"""
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        req = proot / ".fenix" / "approve_push_request.json"
        req.write_text("{ invalid json !!!", encoding="utf-8")
        mock_engine = type("MockEngine", (), {"approve_push": lambda self, spec: True})()
        daemon = _FakeDaemon(proot, mock_engine, FakeLogger())
        self._pickup(monkeypatch, proot, daemon)
        assert not req.exists()

    def test_missing_spec_in_payload_ignored(self, tmp_path, monkeypatch):
        """payload 缺 spec → 删除信号，WARNING 日志，不调 approve_push。"""
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        req = proot / ".fenix" / "approve_push_request.json"
        req.write_text(json.dumps({"source": "dashboard"}), encoding="utf-8")
        mock_engine = type("MockEngine", (), {"approve_push": lambda self, spec: True})()
        logger = FakeLogger()
        daemon = _FakeDaemon(proot, mock_engine, logger)
        self._pickup(monkeypatch, proot, daemon)
        assert not req.exists()
        assert any("缺少 spec" in str(a) for a in logger.warnings)

    def test_pm_engine_none_discards_request(self, tmp_path, monkeypatch):
        """pm_engine 未初始化 → WARNING，丢弃，文件已删。"""
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        req = self._write_signal(proot)
        logger = FakeLogger()
        daemon = _FakeDaemon(proot, None, logger)
        self._pickup(monkeypatch, proot, daemon)
        assert not req.exists()
        assert any("pm_engine 未初始化" in str(a) for a in logger.warnings)

    def test_unlink_failure_skips_and_retries_next_cycle(self, tmp_path, monkeypatch):
        """先读后删失败（被并发消费）→ 本轮跳过，下一轮再试。"""
        proot = _make_done_project(tmp_path)[0]
        mock_engine = type("MockEngine", (), {"approve_push": lambda self, spec: True})()
        logger = FakeLogger()
        daemon = _FakeDaemon(proot, mock_engine, logger)
        req = self._write_signal(proot)
        # 模拟 unlink 失败
        original_unlink = Path.unlink
        call_count = [0]
        def failing_unlink(self_path, *args, **kwargs):
            if "approve_push_request" in str(self_path):
                call_count[0] += 1
                if call_count[0] == 1:
                    raise OSError("simulated concurrent delete")
                return original_unlink(self_path, *args, **kwargs)
            return original_unlink(self_path, *args, **kwargs)
        monkeypatch.setattr(Path, "unlink", failing_unlink)
        # 第一轮：unlink 失败，跳过
        self._pickup(monkeypatch, proot, daemon)
        assert req.exists()
        # 第二轮：unlink 成功，消费
        self._pickup(monkeypatch, proot, daemon)
        assert not req.exists()


# ── Task 5.3：幂等与竞态核对 ─────────────────────────────────────

class TestApprovePushIdempotency:
    """并发/幂等场景：连续两次写入第二次 409；pushed 后消费无 ERROR。"""

    def test_two_requests_without_consumption_second_conflict(self, tmp_path, monkeypatch):
        """连续两次调用（中间不消费）→ 第二次 conflict。"""
        proot, _ = _make_done_project(tmp_path)
        monkeypatch.setattr(dash_data, "_is_running", lambda p: True)
        r1 = dash_data.request_spec_approve_push(proot, "done-spec")
        assert r1["ok"] is True
        r2 = dash_data.request_spec_approve_push(proot, "done-spec")
        assert r2["ok"] is False
        assert r2["conflict"] is True

    def test_approve_push_called_on_pushed_spec_returns_true_no_error(self, tmp_path, monkeypatch):
        """spec 已 pushed 后消费信号 → approve_push 幂等返回 True，不产生 pushed→pushed ERROR。"""
        proot, _ = _make_pushed_project(tmp_path)
        req_path = proot / ".fenix" / "approve_push_request.json"
        req_path.parent.mkdir(parents=True, exist_ok=True)
        req_path.write_text(json.dumps({
            "spec": "pushed-spec", "source": "dashboard",
            "created": "2026-09-11T00:00:00+00:00",
        }), encoding="utf-8")
        # mock pm_engine.approve_push 返回 True（模拟已 pushed 幂等跳过）
        # 注意：经实例属性访问时 self 自动传入，签名须为 (self, spec_name)
        approve_push_called = []
        def fake_approve_push(self, spec_name):
            approve_push_called.append(spec_name)
            return True
        mock_engine = type("MockEngine", (), {"approve_push": fake_approve_push})()
        logger = FakeLogger()
        daemon = _FakeDaemon(proot, mock_engine, logger)
        monkeypatch.setattr(_fenixd_mod, "PROJECT_ROOT", proot)
        daemon._check_approve_push_requests()
        # approve_push 被调用且返回 True（不触发 error 路径）
        assert approve_push_called == ["pushed-spec"]
        assert not req_path.exists()
        assert not logger.errors
