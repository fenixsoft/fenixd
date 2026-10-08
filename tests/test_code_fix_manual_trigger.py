"""test_code_fix_manual_trigger.py — 手动「立即自动修复」消费链测试
（add-code-fix-manual-trigger task 3.2）

覆盖 daemon 消费函数 ``fenixd._check_code_fix_requests``：
- 开关关闭仍投递（手动即临时授权，override_enabled=True 绕过 enabled 守卫）
- already_running / no_open_items / 回归契约缺失三类拒绝的结果文件内容
- 编排器未装配不静默（orchestrator_missing 结果）
- checkpoint 异常落 dispatch_exception 结果
- 结果文件 ``request_created`` 回链信号 ``created``
- 信号先读后删（异常/损坏不复活、不重复消费）
- 积压旧信号（created 超 1h 阈值）仅消费落 stale_created，不投递（item 6cc24b51f6b9）

MUST NOT 真跑 agent——编排器经记录型假 executor 投递（批 worker 链不在本
文件范围），runner 用最小替身。
"""

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fenixd  # noqa: E402

# /tmp 可能被外部清扫进程周期性清空。统一用仓库内 .history/tmp（gitignored）。
_HISTORY_TMP = Path(__file__).resolve().parent.parent / ".history" / "tmp"
_HISTORY_TMP.mkdir(parents=True, exist_ok=True)


class _FakeLogger:
    def __getattr__(self, name):
        return lambda *a, **k: None


class _RecExecutor:
    """记录 submit 的假线程池（不执行任务——批 worker 链不在本测试范围）。"""

    def __init__(self):
        self.jobs = []

    def submit(self, fn, *args, **kwargs):
        self.jobs.append((fn, args, kwargs))


class _FakeRunner:
    """最小 agent_runner 替身：编排器挂在 ``_code_fix_orchestrator``。"""

    def __init__(self, orchestrator=None, with_attr=True):
        self._running_agents = {}
        self.config = {}
        if with_attr:
            self._code_fix_orchestrator = orchestrator


class _SpyOrch:
    """记录 checkpoint 调用参数的替身（断言 override_enabled=True 传递）。"""

    def __init__(self, result=None):
        self.calls = []
        self._result = result or {"triggered": True, "reason": "dispatched"}

    def checkpoint(self, override_enabled=False):
        self.calls.append(override_enabled)
        return dict(self._result)


class _BoomOrch:
    """checkpoint 必抛异常的替身（消费端 dispatch_exception 兜底路径）。"""

    def checkpoint(self, override_enabled=False):
        raise RuntimeError("boom")


def _mkdtemp(prefix: str) -> str:
    return tempfile.mkdtemp(prefix=prefix, dir=str(_HISTORY_TMP))


def _make_project_root(with_items=True, with_regression=True, with_verify=True) -> Path:
    proot = Path(_mkdtemp("cfixmt-"))
    (proot / ".fenix" / "code-review").mkdir(parents=True, exist_ok=True)
    if with_items:
        item = {"item_id": "a", "status": "open", "file": "core/a.py", "line": 1,
                "severity": "major", "category": "correctness", "title": "t",
                "description": "d", "suggestion": "s", "fingerprint": "fp-a"}
        items_path = proot / ".fenix" / "code-review" / "items.jsonl"
        items_path.write_text(
            json.dumps(item, ensure_ascii=False) + "\n", encoding="utf-8")
    if with_verify:
        body = (
            "prepare:\n  - run: 'true'\n"
            "serve:\n  kind: static\n  root: site\n"
            "ready:\n  url: /\n  expect: 200\n"
        )
        if with_regression:
            body += (
                "regression:\n"
                "  cmd: \"true\"\n"
                "  output: \".fenix/regression/junit.xml\"\n"
            )
        (proot / ".fenix" / "verify.yaml").write_text(body, encoding="utf-8")
    return proot


def _make_daemon(proot: Path, runner) -> fenixd.FenixDaemon:
    """最小 FenixDaemon（__new__ 绕过 __init__），只装配消费路径属性。"""
    daemon = fenixd.FenixDaemon.__new__(fenixd.FenixDaemon)
    daemon.running = True
    daemon.agent_runner = runner
    daemon.logger = _FakeLogger()
    return daemon


def _write_signal(proot: Path, created="2026-09-22T00:00:00+00:00") -> Path:
    req = proot / ".fenix" / "code_fix_request.json"
    req.parent.mkdir(parents=True, exist_ok=True)
    req.write_text(json.dumps({"source": "dashboard", "created": created}),
                   encoding="utf-8")
    return req


def _consume(monkeypatch, proot: Path, daemon) -> None:
    monkeypatch.setattr(fenixd, "PROJECT_ROOT", proot)
    daemon._check_code_fix_requests()


def _read_result(proot: Path) -> dict:
    path = proot / ".fenix" / "code_fix_request_result.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _orch(proot: Path, enabled: bool, runner=None):
    from core.code_fix import CodeFixOrchestrator

    return CodeFixOrchestrator(
        runner, proot,
        config={"admin": {"code_review_fix": {"enabled": enabled, "batch_size": 20}}},
        logger=None, executor=_RecExecutor())


_CREATED = "2026-09-22T01:02:03+00:00"
# item 6cc24b51f6b9：created 超过 1h 阈值的手动信号按陈旧分档（仅消费不投递）。
# 行为类用例改用新鲜 created 以到达原目标路径；固定值 _CREATED 留给 stale 用例。
_FRESH_CREATED = datetime.now(timezone.utc).isoformat()


class TestCodeFixManualTriggerConsume:
    def test_disabled_still_dispatches_with_override(self, monkeypatch):
        """开关关闭 + 手动信号 → 临时授权仍投递（triggered=true）。"""
        proot = _make_project_root()
        runner = _FakeRunner()
        runner._code_fix_orchestrator = _orch(proot, enabled=False, runner=runner)
        daemon = _make_daemon(proot, runner)
        _write_signal(proot, _FRESH_CREATED)
        _consume(monkeypatch, proot, daemon)

        assert not (proot / ".fenix" / "code_fix_request.json").exists(), \
            "信号消费后 MUST 先读后删"
        res = _read_result(proot)
        assert res["triggered"] is True
        assert res["reason"] == "dispatched"
        assert res["request_created"] == _FRESH_CREATED, "结果 MUST 回链信号 created"
        assert res["message"]
        assert res["finished_at"]

    def test_consumer_passes_override_enabled_true(self, monkeypatch):
        """消费端 MUST 以 override_enabled=True 调 checkpoint（临时授权语义成参）。"""
        proot = _make_project_root()
        spy = _SpyOrch()
        runner = _FakeRunner(orchestrator=spy)
        daemon = _make_daemon(proot, runner)
        _write_signal(proot, _FRESH_CREATED)
        _consume(monkeypatch, proot, daemon)
        assert spy.calls == [True]

    def test_already_running_rejected_with_result(self, monkeypatch):
        """已有在途 code-fix 批 → already_running 拒绝 + 结果文件如实反馈。"""
        proot = _make_project_root()
        runner = _FakeRunner()
        runner._running_agents = {"code-fix-123": object()}
        runner._code_fix_orchestrator = _orch(proot, enabled=True, runner=runner)
        daemon = _make_daemon(proot, runner)
        _write_signal(proot, _FRESH_CREATED)
        _consume(monkeypatch, proot, daemon)

        res = _read_result(proot)
        assert res["triggered"] is False
        assert res["reason"] == "already_running"
        assert res["request_created"] == _FRESH_CREATED
        assert "在跑" in res["message"]
        # 拒绝也不得留下死信号
        assert not (proot / ".fenix" / "code_fix_request.json").exists()

    def test_no_open_items_rejected_with_result(self, monkeypatch):
        """台账 open 条目为 0 → no_open_items 拒绝 + 结果文件如实反馈。"""
        proot = _make_project_root(with_items=False)
        runner = _FakeRunner()
        runner._code_fix_orchestrator = _orch(proot, enabled=True, runner=runner)
        daemon = _make_daemon(proot, runner)
        _write_signal(proot, _FRESH_CREATED)
        _consume(monkeypatch, proot, daemon)

        res = _read_result(proot)
        assert res["triggered"] is False
        assert res["reason"] == "no_open_items"
        assert res["request_created"] == _FRESH_CREATED
        assert res["message"]

    def test_regression_contract_missing_rejected_with_result(self, monkeypatch):
        """verify.yaml 契约缺失 → fail-closed 拒绝（不因手动触发放宽）。"""
        proot = _make_project_root(with_verify=False)
        runner = _FakeRunner()
        runner._code_fix_orchestrator = _orch(proot, enabled=True, runner=runner)
        daemon = _make_daemon(proot, runner)
        _write_signal(proot, _FRESH_CREATED)
        _consume(monkeypatch, proot, daemon)

        res = _read_result(proot)
        assert res["triggered"] is False
        assert res["reason"] == "regression_contract_missing"
        assert res["request_created"] == _FRESH_CREATED
        assert res["message"]

    def test_orchestrator_missing_not_silent(self, monkeypatch):
        """编排器未装配 → 落 orchestrator_missing 结果，不静默丢信号。"""
        proot = _make_project_root()
        runner = _FakeRunner(with_attr=False)  # 无 _code_fix_orchestrator 属性
        daemon = _make_daemon(proot, runner)
        _write_signal(proot, _FRESH_CREATED)
        _consume(monkeypatch, proot, daemon)

        res = _read_result(proot)
        assert res["triggered"] is False
        assert res["reason"] == "orchestrator_missing"
        assert res["request_created"] == _FRESH_CREATED
        assert "编排器" in res["message"]
        assert not (proot / ".fenix" / "code_fix_request.json").exists()

    def test_checkpoint_exception_lands_dispatch_exception(self, monkeypatch):
        """checkpoint 抛异常 → dispatch_exception 结果，MUST NOT 静默。"""
        proot = _make_project_root()
        runner = _FakeRunner(orchestrator=_BoomOrch())
        daemon = _make_daemon(proot, runner)
        _write_signal(proot, _FRESH_CREATED)
        _consume(monkeypatch, proot, daemon)

        res = _read_result(proot)
        assert res["triggered"] is False
        assert res["reason"] == "dispatch_exception"
        assert res["request_created"] == _FRESH_CREATED

    def test_signal_read_then_delete_not_revived(self, monkeypatch):
        """信号先读后删：异常不复活，二次扫描不重复消费（结果不被覆写）。"""
        proot = _make_project_root()
        runner = _FakeRunner(orchestrator=_BoomOrch())
        daemon = _make_daemon(proot, runner)
        _write_signal(proot, _FRESH_CREATED)
        _consume(monkeypatch, proot, daemon)
        first = _read_result(proot)
        assert first["reason"] == "dispatch_exception"

        # 二次扫描：信号文件已删 → 不再消费，结果文件不被覆写
        _consume(monkeypatch, proot, daemon)
        assert _read_result(proot) == first

    def test_corrupt_signal_deleted_without_result(self, monkeypatch):
        """损坏 JSON 信号 → 删除防卡死 + 落 invalid_payload 结果不静默。

        item 3ae81f8b6d0b：payload 归因时信号已被消费删除、不会再重试，
        比照 code_review 车道（item 94618d6567ee）落结果文件不静默——
        payload 损坏无 created 可回链（request_created 落空串），前端据
        结果文件如实展示「触发信号内容非法」。
        """
        proot = _make_project_root()
        runner = _FakeRunner(orchestrator=_SpyOrch())
        daemon = _make_daemon(proot, runner)
        req = proot / ".fenix" / "code_fix_request.json"
        req.parent.mkdir(parents=True, exist_ok=True)
        req.write_text("{not-json", encoding="utf-8")
        _consume(monkeypatch, proot, daemon)

        assert not req.exists(), "损坏信号 MUST 删除防每轮卡死"
        res = _read_result(proot)
        assert res["triggered"] is False
        assert res["reason"] == "invalid_payload"
        assert res["request_created"] == "", "payload 损坏无 created 可回链"
        assert res["message"]
        assert res["finished_at"]

    def test_missing_signal_noop(self, monkeypatch):
        """无信号 → 纯 no-op（不建结果文件、不触碰编排器）。"""
        proot = _make_project_root()
        spy = _SpyOrch()
        runner = _FakeRunner(orchestrator=spy)
        daemon = _make_daemon(proot, runner)
        _consume(monkeypatch, proot, daemon)
        assert spy.calls == []
        assert _read_result(proot) == {}

    def test_stale_created_consumed_without_dispatch(self, monkeypatch):
        """积压旧信号（created 超 1h 阈值）→ 仅消费落 stale_created，不投递。

        item 6cc24b51f6b9：手动授权语义锚定点击时刻，daemon 停机积压的旧
        信号重启后不得再执行；消费删除防卡死，结果如实反馈陈旧原因。
        """
        proot = _make_project_root()
        spy = _SpyOrch()
        runner = _FakeRunner(orchestrator=spy)
        daemon = _make_daemon(proot, runner)
        _write_signal(proot, _CREATED)
        _consume(monkeypatch, proot, daemon)

        assert not (proot / ".fenix" / "code_fix_request.json").exists(), \
            "陈旧信号同样 MUST 消费删除，不留死信号"
        res = _read_result(proot)
        assert res["triggered"] is False
        assert res["reason"] == "stale_created"
        assert res["request_created"] == _CREATED
        assert spy.calls == [], "陈旧信号 MUST NOT 投递 checkpoint"
