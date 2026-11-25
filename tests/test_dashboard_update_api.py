"""Dashboard 更新面三路由测试（add-auto-update 3.1）。

GET /api/update/status（缺文件 never-checked / 有文件回显）、
POST /api/update/check（业务失败 200+error、成功 200+ok）、
POST /api/update/apply（受理 200、并发 409+update-locked 机器码）。
真实 HTTP 验证（server_fx 临时端口），引擎函数经模块属性 monkeypatch 注入。

隔离：update 引擎的 ``STATUS_PATH``/``UPDATE_DIR`` 为 core.self_update 模块
级常量——测试 monkeypatch 到临时目录，全部读写落沙箱，不触真实 ~/.fenix。
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import core.self_update as self_update_mod  # noqa: E402
import core.self_update_apply as apply_mod  # noqa: E402


@pytest.fixture()
def update_env(monkeypatch, tmp_path):
    """状态文件路径 monkeypatch 到临时 update 目录。"""
    udir = tmp_path / "update-state"
    udir.mkdir()
    monkeypatch.setattr(self_update_mod, "UPDATE_DIR", udir)
    monkeypatch.setattr(self_update_mod, "STATUS_PATH", udir / "status.json")
    monkeypatch.setattr(self_update_mod, "AUDITS_PATH", udir / "audits.jsonl")
    monkeypatch.setattr(self_update_mod, "APPLY_LOCK_PATH", udir / "apply.lock")
    return udir


def _write_status(udir: Path, payload: dict) -> None:
    (udir / "status.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class TestUpdateStatusRoute:
    def test_never_checked_shape(self, server_fx, update_env):
        proot, srv = server_fx
        status, body = srv.get("/api/update/status")
        assert status == 200
        assert body["checked"] is False
        assert body["framework"] is None
        assert body["apply"] is None

    def test_existing_status_roundtrip(self, server_fx, update_env):
        proot, srv = server_fx
        _write_status(update_env, {
            "framework": {"form": "artifact", "local_version": "v0.1.7",
                          "remote_version": "v0.1.8", "update_available": True},
            "plugins": {"form": "artifact", "local_version": "v0.1.2",
                        "update_available": False},
            "last_check_at": "2026-11-25T00:00:00Z",
            "apply": {"phase": "idle"},
        })
        status, body = srv.get("/api/update/status")
        assert status == 200
        assert body["checked"] is True
        assert body["framework"]["update_available"] is True
        assert body["plugins"]["local_version"] == "v0.1.2"


class TestUpdateCheckRoute:
    def test_check_success(self, server_fx, update_env, monkeypatch):
        proot, srv = server_fx

        def fake_run_check(source, **kw):
            assert source == "dashboard"
            return {"framework": {"update_available": True}, "last_error": None}

        monkeypatch.setattr(self_update_mod, "run_check", fake_run_check)
        status, body = srv.post("/api/update/check")
        assert status == 200
        assert body["ok"] is True
        assert body["status"]["framework"]["update_available"] is True

    def test_check_business_failure_is_200_with_error(self, server_fx,
                                                      update_env, monkeypatch):
        proot, srv = server_fx
        monkeypatch.setattr(self_update_mod, "run_check", lambda *a, **k: {
            "framework": {}, "plugins": {}, "last_error":
                "查询 fenixsoft/fenixd releases/latest 失败: GitHub API 限流",
        })
        status, body = srv.post("/api/update/check")
        # 业务失败是检查结果而非 HTTP 错误（200 契约），前端按 ok 分支
        assert status == 200
        assert body["ok"] is False
        assert "限流" in body["error"]


class TestUpdateApplyRoute:
    def test_apply_accepted(self, server_fx, update_env, monkeypatch):
        proot, srv = server_fx
        monkeypatch.setattr(apply_mod, "spawn_apply",
                            lambda **kw: {"ok": True, "pid": 4321})
        status, body = srv.post("/api/update/apply")
        assert status == 200
        assert body["ok"] is True
        assert body["pid"] == 4321

    def test_apply_conflict_409_with_machine_code(self, server_fx, update_env,
                                                  monkeypatch):
        proot, srv = server_fx
        monkeypatch.setattr(apply_mod, "spawn_apply", lambda **kw: {
            "ok": False, "conflict": True, "error": "更新编排已在进行中"})
        status, body = srv.get("/api/update/status")  # 前置连接复用预热
        status, body = srv.post("/api/update/apply")
        assert status == 409
        assert body["code"] == "update-locked"

    def test_apply_spawn_failure_500(self, server_fx, update_env, monkeypatch):
        proot, srv = server_fx
        monkeypatch.setattr(apply_mod, "spawn_apply", lambda **kw: {
            "ok": False, "conflict": False, "error": "编排进程拉起失败"})
        status, body = srv.post("/api/update/apply")
        assert status == 500
        assert "error" in body
