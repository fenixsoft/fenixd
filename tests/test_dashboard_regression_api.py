"""test-dashboard-regression-api — 回归 Dashboard 后端测试（task 4.4 + 3.6）。

覆盖：
- GET  /api/regression/result：有效快照 / never_run / parse_error 不 500 / 未知项目 404
- POST /api/regression/run：受理 / 未配置 400 / 未托管 409 / 已有在跑 409
- admin.regression 配置受管键：_SOURCE_KEYS 登记 / 缺省回显 / 写读回环 / 非法值拒绝
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from conftest import _TestServer, make_project  # noqa: E402
from core.dashboard.registry import Registry


def _registry(tmp_path, proot):
    cfg = tmp_path / "dashboard.yaml"
    reg = Registry(config_path=cfg)
    reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
              "scan_dirs": [str(tmp_path / "scan-empty")]})
    return reg


def _server(tmp_path, proot):
    static = Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static"
    return _TestServer(_registry(tmp_path, proot), static)


def _write_verify_yaml(proot: Path, regression_block: str = ""):
    body = (
        "prepare:\n"
        "  - run: touch built.txt\n"
        "serve:\n"
        "  kind: static\n"
        "  root: site\n"
        "ready:\n"
        "  url: /\n"
        "  expect: 200\n"
    )
    if regression_block:
        body += regression_block
    (proot / ".fenix" / "verify.yaml").write_text(body, encoding="utf-8")


REGRESSION_VALID = (
    "regression:\n"
    "  cmd: \"pytest --junit-xml=.fenix/regression/junit.xml\"\n"
    "  output: \".fenix/regression/junit.xml\"\n"
)


class TestRegressionResultAPI:
    """GET /api/regression/result 三态 + 404。"""

    def test_never_run(self, tmp_path):
        proot = make_project(tmp_path)
        srv = _server(tmp_path, proot)
        try:
            status, body = srv.get("/api/regression/result?project=proj-a")
            assert status == 200
            assert body["status"] == "never_run"
        finally:
            srv.stop()

    def test_valid_snapshot(self, tmp_path):
        proot = make_project(tmp_path)
        (proot / ".fenix" / "regression").mkdir(parents=True, exist_ok=True)
        (proot / ".fenix" / "regression" / "last-run.json").write_text(
            json.dumps({"status": "passed", "total": 5, "passed": 5, "failed": 0,
                        "errors": 0, "skipped": 0, "failures": [], "long_tests": []}),
            encoding="utf-8",
        )
        srv = _server(tmp_path, proot)
        try:
            status, body = srv.get("/api/regression/result?project=proj-a")
            assert status == 200
            assert body["status"] == "passed"
            assert body["total"] == 5
        finally:
            srv.stop()

    def test_parse_error_not_500(self, tmp_path):
        proot = make_project(tmp_path)
        (proot / ".fenix" / "regression").mkdir(parents=True, exist_ok=True)
        (proot / ".fenix" / "regression" / "last-run.json").write_text(
            "not json {", encoding="utf-8"
        )
        srv = _server(tmp_path, proot)
        try:
            status, body = srv.get("/api/regression/result?project=proj-a")
            assert status == 200
            assert body["status"] == "parse_error"
            assert body["reason"]
        finally:
            srv.stop()

    def test_unknown_project_404(self, tmp_path):
        proot = make_project(tmp_path)
        srv = _server(tmp_path, proot)
        try:
            status, body = srv.get("/api/regression/result?project=nope")
            assert status == 404
        finally:
            srv.stop()


class TestRegressionRunAPI:
    """POST /api/regression/run 受理与守卫。"""

    def test_accepts_writes_signal(self, tmp_path, monkeypatch):
        proot = make_project(tmp_path)
        _write_verify_yaml(proot, REGRESSION_VALID)
        # 模拟 daemon managed 态
        import core.fenix_session

        monkeypatch.setattr(core.fenix_session, "hosting_state", lambda p: "managed")
        srv = _server(tmp_path, proot)
        try:
            status, body = srv.post_json("/api/regression/run?project=proj-a", {})
            assert status == 200
            assert body["ok"] is True
            assert body["requested_at"]
            # 信号文件已写入
            assert (proot / ".fenix" / "regression_request.json").is_file()
        finally:
            srv.stop()

    def test_not_configured_400(self, tmp_path, monkeypatch):
        proot = make_project(tmp_path)
        _write_verify_yaml(proot)  # 无 regression 段
        import core.fenix_session

        monkeypatch.setattr(core.fenix_session, "hosting_state", lambda p: "managed")
        srv = _server(tmp_path, proot)
        try:
            status, body = srv.post_json("/api/regression/run?project=proj-a", {})
            assert status == 400
            assert "未配置全量回归" in body["error"]
            # MUST NOT 派发空跑：无信号文件
            assert not (proot / ".fenix" / "regression_request.json").exists()
        finally:
            srv.stop()

    def test_unmanaged_409(self, tmp_path, monkeypatch):
        proot = make_project(tmp_path)
        _write_verify_yaml(proot, REGRESSION_VALID)
        import core.fenix_session

        monkeypatch.setattr(core.fenix_session, "hosting_state", lambda p: "unmanaged")
        srv = _server(tmp_path, proot)
        try:
            status, body = srv.post_json("/api/regression/run?project=proj-a", {})
            assert status == 409
            # MUST NOT 写入会永久滞留的信号
            assert not (proot / ".fenix" / "regression_request.json").exists()
        finally:
            srv.stop()

    def test_unknown_project_404(self, tmp_path):
        proot = make_project(tmp_path)
        srv = _server(tmp_path, proot)
        try:
            status, body = srv.post_json("/api/regression/run?project=nope", {})
            assert status == 404
        finally:
            srv.stop()


class TestRegressionConfigAdmin:
    """admin.regression 受管键：登记 / sources / 回显 / 写读 / 非法拒绝（task 3.5/3.6）。"""

    def test_source_keys_registered(self):
        from core.dashboard.data import _SOURCE_KEYS

        assert "admin.regression" in _SOURCE_KEYS

    def test_default_echo(self, tmp_path):
        from core.dashboard.data import read_config, read_effective_config

        rc = read_config(tmp_path)
        assert rc["regression"]["enabled"] is False
        assert rc["sources"]["admin.regression"] == "user"

        eff = read_effective_config(tmp_path)
        assert eff["regression"]["enabled"] is False

    def test_write_read_roundtrip(self, tmp_path):
        """enabled=true 写入后读回；admin 段合并路径生效（task 3.5）。"""
        from core.dashboard.data import read_config, write_config

        proot = Path(tmp_path)
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        r = write_config(proot, {"regression": {"enabled": True}})
        assert r.get("error") is None, r
        rc = read_config(proot)
        assert rc["regression"]["enabled"] is True
        assert rc["sources"]["admin.regression"] == "project"

    def test_invalid_value_rejected(self, tmp_path):
        """enabled 非 bool → 拒绝不落盘（task 3.5 前置校验）。"""
        from core.dashboard.data import write_config

        proot = Path(tmp_path)
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        r = write_config(proot, {"regression": {"enabled": "yes"}})
        assert r.get("error") is not None
        assert "boolean" in r["error"]

    def test_switch_absent_when_not_configured(self, tmp_path):
        """键缺失 → 回显关闭（缺省 false，不因键缺失报错或默认开启）。"""
        from core.dashboard.data import read_config

        rc = read_config(tmp_path)
        assert rc["regression"]["enabled"] is False


class TestRegressionRunningMarker:
    """运行中 marker 判定（POST 409 守卫的判据，task 4.2/5.6）。"""

    def test_marker_roundtrip(self, tmp_path):
        from core.regression import (
            clear_running,
            is_regression_running,
            mark_running,
        )

        proot = Path(tmp_path)
        clear_running(proot)
        assert is_regression_running(proot) is False
        mark_running(proot, timeout_seconds=1800)
        assert is_regression_running(proot) is True
        clear_running(proot)
        assert is_regression_running(proot) is False
