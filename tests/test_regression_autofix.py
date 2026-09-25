"""test_regression_autofix.py — 回归问题一键自动修复测试（add-regression-auto-fix）

覆盖：
- 1.3 ``convert_regression_snapshot_to_findings``：映射各分支（failure/error/
  long/timeout）、超长 message 截断、snapshot 损坏容错
- 1.3 ``reopen_regression_items``：命中重开 / 不命中 / 非 regression- 前缀不触碰
- 2.3 POST /api/regression/fix：受理写信号、never_run/parse_error 与无异常
  两类拒绝错误码；GET /api/regression/fix-result：读取与缺失兜底
- 3.2 daemon 消费链：消费→入账→triggered=true 全链路、snapshot_missing /
  orchestrator_missing / dispatch_exception 三兜底、already_running 拒绝时
  条目保留、信号消费后不残留

MUST NOT 真跑 agent——编排器经记录型假 executor 投递，runner 用最小替身。
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

import fenixd  # noqa: E402
from core.code_fix import (  # noqa: E402
    convert_regression_snapshot_to_findings,
    regression_findings_fingerprints,
    reopen_regression_items,
)
from core.code_review import read_items, upsert_findings  # noqa: E402

# /tmp 可能被外部清扫进程周期性清空。统一用仓库内 .history/tmp（gitignored）。
_HISTORY_TMP = Path(__file__).resolve().parent.parent / ".history" / "tmp"
_HISTORY_TMP.mkdir(parents=True, exist_ok=True)


def _mkdtemp(prefix: str) -> str:
    return tempfile.mkdtemp(prefix=prefix, dir=str(_HISTORY_TMP))


# ── 快照构造器 ────────────────────────────────────────────────────────


def _snapshot(status="failed", failures=None, long_tests=None, **extra):
    snap = {
        "status": status,
        "cmd": "pytest tests/ -q",
        "output": ".fenix/regression/junit.xml",
        "total": 10, "passed": 8, "failed": 0, "errors": 0, "skipped": 0,
        "failures": failures if failures is not None else [],
        "long_tests": long_tests if long_tests is not None else [],
    }
    snap.update(extra)
    return snap


def _failure(kind="failure", name="tests/test_a.py::test_x", **kw):
    d = {"name": name, "file": "tests/test_a.py", "line": 12, "time": 1.5,
         "kind": kind, "message": "assert 1 == 2"}
    d.update(kw)
    return d


def _long(name="tests/test_slow.py::test_slow", **kw):
    d = {"name": name, "file": "tests/test_slow.py", "line": 3, "time": 42.0}
    d.update(kw)
    return d


# ── 1.3 转换纯函数 ────────────────────────────────────────────────────


class TestConvertRegressionSnapshotToFindings:
    def test_failure_and_error_mapping(self):
        snap = _snapshot(failures=[_failure(kind="failure"), _failure(kind="error")])
        findings = convert_regression_snapshot_to_findings(snap)
        assert len(findings) == 2
        assert [f["category"] for f in findings] == [
            "regression-failure", "regression-error"]
        assert all(f["severity"] == "high" for f in findings)
        assert findings[0]["title"] == "tests/test_a.py::test_x"
        assert findings[0]["file"] == "tests/test_a.py"
        assert findings[0]["line"] == 12
        # description 携带分类、耗时与失败 message
        assert "regression-failure" in findings[0]["description"]
        assert "1.5s" in findings[0]["description"]
        assert "assert 1 == 2" in findings[0]["description"]
        assert findings[0]["suggestion"]

    def test_long_test_mapping(self):
        findings = convert_regression_snapshot_to_findings(
            _snapshot(long_tests=[_long()]))
        assert len(findings) == 1
        f = findings[0]
        assert f["category"] == "regression-long-test"
        assert f["severity"] == "medium"
        assert f["title"] == "tests/test_slow.py::test_slow"
        # description 含 42s 耗时信息
        assert "42s" in f["description"]
        # suggestion 固化文案含「不改变测试通过结果」前提与优化手段
        assert "不改变测试通过结果" in f["suggestion"]
        assert "sleep" in f["suggestion"]

    def test_timeout_mapping(self):
        snap = _snapshot(status="timeout", reason="硬超时 1800s 中止")
        findings = convert_regression_snapshot_to_findings(
            snap, output_excerpt="tail of output")
        assert len(findings) == 1
        f = findings[0]
        assert f["category"] == "regression-timeout"
        assert f["severity"] == "high"
        assert f["file"] == ".fenix/verify.yaml"
        assert f["title"] == "回归整体超时"
        assert "硬超时 1800s 中止" in f["description"]
        assert "tail of output" in f["description"]

    def test_timeout_without_excerpt(self):
        snap = _snapshot(status="timeout", reason="r")
        findings = convert_regression_snapshot_to_findings(snap, output_excerpt="")
        assert len(findings) == 1
        assert "输出摘要" not in findings[0]["description"]

    def test_message_truncated(self):
        snap = _snapshot(failures=[_failure(message="M" * 2000)])
        findings = convert_regression_snapshot_to_findings(snap)
        desc = findings[0]["description"]
        assert len(desc) < 600, "超长 message 截断至 500 字"
        assert "M" * 501 not in desc
        # timeout 的输出摘要同样截断
        snap = _snapshot(status="timeout", reason="r")
        findings = convert_regression_snapshot_to_findings(
            snap, output_excerpt="O" * 2000)
        assert len(findings[0]["description"]) < 700

    def test_corrupt_or_missing_snapshot_tolerated(self):
        assert convert_regression_snapshot_to_findings(None) == []
        assert convert_regression_snapshot_to_findings("junk") == []
        assert convert_regression_snapshot_to_findings({}) == []
        # 字段类型异常不抛（failures 非 list / 条目非 dict）
        assert convert_regression_snapshot_to_findings(
            {"failures": "nope", "long_tests": 3}) == []
        assert convert_regression_snapshot_to_findings(
            {"failures": ["x", 1, None], "long_tests": [2]}) == []

    def test_fingerprints_skip_fileless(self):
        snap = _snapshot(failures=[_failure(), _failure(name="t2", file="")])
        findings = convert_regression_snapshot_to_findings(snap)
        fps = regression_findings_fingerprints(findings)
        assert len(fps) == 1, "无 file 的条目不参与指纹集（与 upsert 硬规则同口径）"


# ── 1.3 复发重开 ──────────────────────────────────────────────────────


class TestReopenRegressionItems:
    def _seed(self, proot: Path, findings):
        upsert_findings(proot, findings, review_id="regression-fix-seed",
                        review_kind="regression_fix")

    def test_reopen_hit_resolved(self):
        proot = Path(_mkdtemp("regfix-"))
        snap = _snapshot(failures=[_failure()])
        findings = convert_regression_snapshot_to_findings(snap)
        self._seed(proot, findings)
        # 模拟已被核销：置 resolved
        items = read_items(proot)
        target = next(iter(items.values()))
        target["status"] = "resolved"
        from core.code_review import write_items

        write_items(proot, items)
        old_first = target["first_seen_at"]

        reopened = reopen_regression_items(
            proot, regression_findings_fingerprints(findings))
        assert reopened == 1
        rec = next(iter(read_items(proot).values()))
        assert rec["status"] == "open"
        assert rec["first_seen_at"] != old_first, "重开刷新 first_seen_at"

    def test_no_hit_stays_resolved(self):
        proot = Path(_mkdtemp("regfix-"))
        snap = _snapshot(failures=[_failure()])
        findings = convert_regression_snapshot_to_findings(snap)
        self._seed(proot, findings)
        items = read_items(proot)
        target = next(iter(items.values()))
        target["status"] = "resolved"
        from core.code_review import write_items

        write_items(proot, items)
        # live 集合不含该指纹 → 不重开
        assert reopen_regression_items(proot, {"deadbeef0000"}) == 0
        assert next(iter(read_items(proot).values()))["status"] == "resolved"

    def test_non_regression_prefix_untouched(self):
        proot = Path(_mkdtemp("regfix-"))
        snap = _snapshot(failures=[_failure()])
        findings = convert_regression_snapshot_to_findings(snap)
        self._seed(proot, findings)
        live_fps = regression_findings_fingerprints(findings)
        items = read_items(proot)
        reg_id = next(iter(items.keys()))
        # 伪造一条 code-review 来源条目：status=resolved 但 fingerprint 恰与
        # live 集合相同（category 非 regression- 前缀）→ MUST NOT 被触碰
        code_review_rec = dict(items[reg_id])
        code_review_rec["item_id"] = "code-review-item-1"
        code_review_rec["category"] = "correctness"
        code_review_rec["status"] = "resolved"
        code_review_rec["fingerprint"] = next(iter(live_fps))
        items["code-review-item-1"] = code_review_rec
        # 回归来源条目自身置 resolved（应被重开）
        items[reg_id]["status"] = "resolved"
        from core.code_review import write_items

        write_items(proot, items)
        assert reopen_regression_items(proot, live_fps) == 1, "仅 regression- 前缀命中"
        after = read_items(proot)
        assert after["code-review-item-1"]["status"] == "resolved", \
            "code-review 来源条目零触碰"
        assert after[reg_id]["status"] == "open"

    def test_open_and_empty_live_noop(self):
        proot = Path(_mkdtemp("regfix-"))
        snap = _snapshot(failures=[_failure()])
        findings = convert_regression_snapshot_to_findings(snap)
        self._seed(proot, findings)
        live_fps = regression_findings_fingerprints(findings)
        # 已是 open：不重复计数
        assert reopen_regression_items(proot, live_fps) == 0
        # 空 live 集合：no-op
        assert reopen_regression_items(proot, set()) == 0


# ── 2.3 触发与回链 API ────────────────────────────────────────────────

from conftest import _TestServer, make_project  # noqa: E402
from core.dashboard.registry import Registry  # noqa: E402


def _registry(tmp_path, proot):
    cfg = tmp_path / "dashboard.yaml"
    reg = Registry(config_path=cfg)
    reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
              "scan_dirs": [str(tmp_path / "scan-empty")]})
    return reg


def _server(tmp_path, proot):
    static = Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static"
    return _TestServer(_registry(tmp_path, proot), static)


def _write_snapshot(proot: Path, snap):
    reg_dir = proot / ".fenix" / "regression"
    reg_dir.mkdir(parents=True, exist_ok=True)
    (reg_dir / "last-run.json").write_text(
        json.dumps(snap, ensure_ascii=False), encoding="utf-8")


class TestRegressionFixAPI:
    def test_accepts_writes_signal(self, tmp_path):
        proot = make_project(tmp_path)
        _write_snapshot(proot, _snapshot(failures=[_failure(), _failure(
            kind="error", name="tests/test_b.py::test_y")]))
        srv = _server(tmp_path, proot)
        try:
            status, body = srv.post_json("/api/regression/fix?project=proj-a", {})
            assert status == 200
            assert body["ok"] is True
            assert body["requested_at"]
            req = proot / ".fenix" / "regression_fix_request.json"
            assert req.is_file()
            payload = json.loads(req.read_text(encoding="utf-8"))
            assert payload["source"] == "regression_fix"
            assert payload["created"] == body["requested_at"]
        finally:
            srv.stop()

    def test_never_run_rejected(self, tmp_path):
        proot = make_project(tmp_path)
        srv = _server(tmp_path, proot)
        try:
            status, body = srv.post_json("/api/regression/fix?project=proj-a", {})
            assert status == 400
            assert body["code"] == "regression_never_run"
            assert not (proot / ".fenix" / "regression_fix_request.json").exists()
        finally:
            srv.stop()

    def test_parse_error_rejected_as_never_run(self, tmp_path):
        proot = make_project(tmp_path)
        _write_snapshot(proot, {})  # 占位：直接写坏 JSON
        (proot / ".fenix" / "regression" / "last-run.json").write_text(
            "not json {", encoding="utf-8")
        srv = _server(tmp_path, proot)
        try:
            status, body = srv.post_json("/api/regression/fix?project=proj-a", {})
            assert status == 400
            # parse_error 快照无 failures 键，不落 no_issues 以免误导
            assert body["code"] == "regression_never_run"
            assert not (proot / ".fenix" / "regression_fix_request.json").exists()
        finally:
            srv.stop()

    def test_no_issues_rejected(self, tmp_path):
        proot = make_project(tmp_path)
        _write_snapshot(proot, _snapshot(status="passed"))
        srv = _server(tmp_path, proot)
        try:
            status, body = srv.post_json("/api/regression/fix?project=proj-a", {})
            assert status == 400
            assert body["code"] == "regression_no_issues"
            assert not (proot / ".fenix" / "regression_fix_request.json").exists()
        finally:
            srv.stop()

    def test_long_only_snapshot_accepted(self, tmp_path):
        """仅长耗时（全绿但慢）同样可触发修复。"""
        proot = make_project(tmp_path)
        _write_snapshot(proot, _snapshot(status="passed", long_tests=[_long()]))
        srv = _server(tmp_path, proot)
        try:
            status, body = srv.post_json("/api/regression/fix?project=proj-a", {})
            assert status == 200
            assert (proot / ".fenix" / "regression_fix_request.json").is_file()
        finally:
            srv.stop()

    def test_unknown_project_404(self, tmp_path):
        proot = make_project(tmp_path)
        srv = _server(tmp_path, proot)
        try:
            status, _ = srv.post_json("/api/regression/fix?project=nope", {})
            assert status == 404
        finally:
            srv.stop()


class TestRegressionFixResultAPI:
    def test_missing_result_none_shape(self, tmp_path):
        proot = make_project(tmp_path)
        srv = _server(tmp_path, proot)
        try:
            status, body = srv.get("/api/regression/fix-result?project=proj-a")
            assert status == 200
            assert body == {"status": "none"}, "结果文件缺失返回缺省态而非 404"
        finally:
            srv.stop()

    def test_result_passthrough(self, tmp_path):
        proot = make_project(tmp_path)
        result = {
            "request_created": "2026-09-25T00:00:00+00:00",
            "triggered": True,
            "reason": "dispatched",
            "message": "已投递",
            "finished_at": "2026-09-25T00:00:01+00:00",
        }
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        (proot / ".fenix" / "regression_fix_request_result.json").write_text(
            json.dumps(result, ensure_ascii=False), encoding="utf-8")
        srv = _server(tmp_path, proot)
        try:
            status, body = srv.get("/api/regression/fix-result?project=proj-a")
            assert status == 200
            assert body == result
        finally:
            srv.stop()

    def test_unknown_project_404(self, tmp_path):
        proot = make_project(tmp_path)
        srv = _server(tmp_path, proot)
        try:
            status, _ = srv.get("/api/regression/fix-result?project=nope")
            assert status == 404
        finally:
            srv.stop()


# ── 3.2 daemon 消费链 ─────────────────────────────────────────────────


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


def _make_project_root(with_verify=True) -> Path:
    proot = Path(_mkdtemp("regfixd-"))
    (proot / ".fenix").mkdir(parents=True, exist_ok=True)
    if with_verify:
        body = (
            "prepare:\n  - run: 'true'\n"
            "serve:\n  kind: static\n  root: site\n"
            "ready:\n  url: /\n  expect: 200\n"
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


def _write_signal(proot: Path, created="2026-09-25T00:00:00+00:00") -> Path:
    req = proot / ".fenix" / "regression_fix_request.json"
    req.parent.mkdir(parents=True, exist_ok=True)
    req.write_text(json.dumps({"source": "regression_fix", "created": created}),
                   encoding="utf-8")
    return req


def _consume(monkeypatch, proot: Path, daemon) -> None:
    monkeypatch.setattr(fenixd, "PROJECT_ROOT", proot)
    daemon._check_regression_fix_requests()


def _read_result(proot: Path) -> dict:
    path = proot / ".fenix" / "regression_fix_request_result.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _orch(proot: Path, runner=None):
    from core.code_fix import CodeFixOrchestrator

    return CodeFixOrchestrator(
        runner, proot,
        config={"admin": {"code_review_fix": {"enabled": True, "batch_size": 20}}},
        logger=None, executor=_RecExecutor())


_CREATED = "2026-09-25T01:02:03+00:00"


class TestRegressionFixConsume:
    def test_full_chain_upserts_and_triggers(self, monkeypatch):
        """消费→转换入账→checkpoint(override)→triggered=true 全链路。"""
        proot = _make_project_root()
        _write_snapshot(proot, _snapshot(
            failures=[_failure(kind="failure")],
            long_tests=[_long()],
        ))
        runner = _FakeRunner()
        runner._code_fix_orchestrator = _orch(proot, runner=runner)
        daemon = _make_daemon(proot, runner)
        _write_signal(proot, _CREATED)
        _consume(monkeypatch, proot, daemon)

        assert not (proot / ".fenix" / "regression_fix_request.json").exists(), \
            "信号消费后 MUST 先读后删"
        res = _read_result(proot)
        assert res["triggered"] is True
        assert res["reason"] == "dispatched"
        assert res["request_created"] == _CREATED, "结果 MUST 回链信号 created"
        assert res["finished_at"]

        items = read_items(proot)
        assert len(items) == 2
        assert {rec["category"] for rec in items.values()} == {
            "regression-failure", "regression-long-test"}
        for rec in items.values():
            assert rec["review_kind"] == "regression_fix"
            assert rec["review_id"] == f"regression-fix-{_CREATED}"
            assert rec["status"] == "open"

    def test_consumer_passes_override_enabled_true(self, monkeypatch):
        """消费端 MUST 以 override_enabled=True 调 checkpoint（手动即临时授权）。"""
        proot = _make_project_root()
        _write_snapshot(proot, _snapshot(failures=[_failure()]))
        spy = _SpyOrch()
        runner = _FakeRunner(orchestrator=spy)
        daemon = _make_daemon(proot, runner)
        _write_signal(proot, _CREATED)
        _consume(monkeypatch, proot, daemon)
        assert spy.calls == [True]

    def test_resolved_item_reopened_on_consume(self, monkeypatch):
        """复发用例（已 resolved 条目再次失败）消费时被重开为 open。"""
        proot = _make_project_root()
        snap = _snapshot(failures=[_failure()])
        findings = convert_regression_snapshot_to_findings(snap)
        upsert_findings(proot, findings, review_id="regression-fix-seed",
                        review_kind="regression_fix")
        items = read_items(proot)
        target = next(iter(items.values()))
        target["status"] = "resolved"
        from core.code_review import write_items

        write_items(proot, items)

        _write_snapshot(proot, snap)
        runner = _FakeRunner(orchestrator=_SpyOrch())
        daemon = _make_daemon(proot, runner)
        _write_signal(proot, _CREATED)
        _consume(monkeypatch, proot, daemon)

        rec = next(iter(read_items(proot).values()))
        assert rec["status"] == "open", "复发条目被重开，链可再次选取修复"
        assert _read_result(proot)["triggered"] is True

    def test_timeout_excerpt_from_output_file(self, monkeypatch):
        """timeout 快照：消费端预读 output 指向文件的尾部 500 字入 description。"""
        proot = _make_project_root()
        reg_dir = proot / ".fenix" / "regression"
        reg_dir.mkdir(parents=True, exist_ok=True)
        out = reg_dir / "junit.xml"
        out.write_text("X" * 100 + "Y" * 500, encoding="utf-8")
        _write_snapshot(proot, _snapshot(status="timeout", reason="硬超时中止"))
        runner = _FakeRunner(orchestrator=_SpyOrch())
        daemon = _make_daemon(proot, runner)
        _write_signal(proot, _CREATED)
        _consume(monkeypatch, proot, daemon)

        items = read_items(proot)
        assert len(items) == 1
        rec = next(iter(items.values()))
        assert rec["category"] == "regression-timeout"
        assert rec["file"] == ".fenix/verify.yaml"
        assert "硬超时中止" in rec["description"]
        assert "Y" * 500 in rec["description"], "尾部 500 字进入输出摘要"
        assert "X" not in rec["description"], "只取尾部，头部内容被截去"

    def test_snapshot_missing_not_silent(self, monkeypatch):
        """快照缺失 → snapshot_missing 结果，不写台账、不调 checkpoint。"""
        proot = _make_project_root()  # 无 last-run.json
        spy = _SpyOrch()
        runner = _FakeRunner(orchestrator=spy)
        daemon = _make_daemon(proot, runner)
        _write_signal(proot, _CREATED)
        _consume(monkeypatch, proot, daemon)

        res = _read_result(proot)
        assert res["triggered"] is False
        assert res["reason"] == "snapshot_missing"
        assert res["request_created"] == _CREATED
        assert spy.calls == [], "快照缺失 MUST NOT 调 checkpoint"
        assert read_items(proot) == {}
        assert not (proot / ".fenix" / "regression_fix_request.json").exists()

    def test_snapshot_corrupt_lands_snapshot_missing(self, monkeypatch):
        proot = _make_project_root()
        reg_dir = proot / ".fenix" / "regression"
        reg_dir.mkdir(parents=True, exist_ok=True)
        (reg_dir / "last-run.json").write_text("{broken", encoding="utf-8")
        runner = _FakeRunner(orchestrator=_SpyOrch())
        daemon = _make_daemon(proot, runner)
        _write_signal(proot, _CREATED)
        _consume(monkeypatch, proot, daemon)
        assert _read_result(proot)["reason"] == "snapshot_missing"

    def test_orchestrator_missing_not_silent(self, monkeypatch):
        """编排器未装配 → orchestrator_missing 结果，不静默丢信号。"""
        proot = _make_project_root()
        _write_snapshot(proot, _snapshot(failures=[_failure()]))
        runner = _FakeRunner(with_attr=False)
        daemon = _make_daemon(proot, runner)
        _write_signal(proot, _CREATED)
        _consume(monkeypatch, proot, daemon)

        res = _read_result(proot)
        assert res["triggered"] is False
        assert res["reason"] == "orchestrator_missing"
        assert res["request_created"] == _CREATED
        assert read_items(proot) == {}, "编排器缺失时 MUST NOT 先入账"
        assert not (proot / ".fenix" / "regression_fix_request.json").exists()

    def test_checkpoint_exception_lands_dispatch_exception(self, monkeypatch):
        """checkpoint 抛异常 → dispatch_exception 结果；已入账条目保留。"""
        proot = _make_project_root()
        _write_snapshot(proot, _snapshot(failures=[_failure()]))
        runner = _FakeRunner(orchestrator=_BoomOrch())
        daemon = _make_daemon(proot, runner)
        _write_signal(proot, _CREATED)
        _consume(monkeypatch, proot, daemon)

        res = _read_result(proot)
        assert res["triggered"] is False
        assert res["reason"] == "dispatch_exception"
        assert res["request_created"] == _CREATED
        assert len(read_items(proot)) == 1, "转换入账成功后异常不回滚台账"

    def test_already_running_keeps_items(self, monkeypatch):
        """checkpoint 以 already_running 拒绝 → 条目保留（在飞链下一批吸收）。"""
        proot = _make_project_root()
        _write_snapshot(proot, _snapshot(failures=[_failure()]))
        runner = _FakeRunner()
        runner._running_agents = {"code-fix-123": object()}
        runner._code_fix_orchestrator = _orch(proot, runner=runner)
        daemon = _make_daemon(proot, runner)
        _write_signal(proot, _CREATED)
        _consume(monkeypatch, proot, daemon)

        res = _read_result(proot)
        assert res["triggered"] is False
        assert res["reason"] == "already_running"
        assert res["request_created"] == _CREATED
        assert len(read_items(proot)) == 1, "拒绝不回滚台账（design D6）"
        assert not (proot / ".fenix" / "regression_fix_request.json").exists()

    def test_signal_not_revived_on_rescan(self, monkeypatch):
        """信号先读后删：二次扫描不重复消费（结果不被覆写）。"""
        proot = _make_project_root()
        _write_snapshot(proot, _snapshot(failures=[_failure()]))
        runner = _FakeRunner(orchestrator=_BoomOrch())
        daemon = _make_daemon(proot, runner)
        _write_signal(proot, _CREATED)
        _consume(monkeypatch, proot, daemon)
        first = _read_result(proot)
        assert first["reason"] == "dispatch_exception"

        # upsert 幂等：二次扫描若误消费会刷新 review_id/时间戳——结果文件
        # 不被覆写即证明未重复消费
        _consume(monkeypatch, proot, daemon)
        assert _read_result(proot) == first

    def test_missing_signal_noop(self, monkeypatch):
        """无信号 → 纯 no-op（不建结果文件、不触碰编排器）。"""
        proot = _make_project_root()
        _write_snapshot(proot, _snapshot(failures=[_failure()]))
        spy = _SpyOrch()
        runner = _FakeRunner(orchestrator=spy)
        daemon = _make_daemon(proot, runner)
        _consume(monkeypatch, proot, daemon)
        assert spy.calls == []
        assert _read_result(proot) == {}
        assert read_items(proot) == {}
