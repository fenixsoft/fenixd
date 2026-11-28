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
from datetime import timedelta
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
    monkeypatch.setattr(self_update_mod, "PROGRESS_PATH", udir / "progress.json")
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

    def test_apply_stale_flag_semantics(self, server_fx, update_env):
        # running 且最后活动超龄 → apply_stale=True（UI 提示可重触发）；
        # 新鲜 running / 终态 / 缺时间戳 → False（宁拒不误清）
        from core.self_update import APPLY_LOCK_STALE_S
        from core.timelib import now_utc, to_storage

        _, srv = server_fx
        old = to_storage(now_utc() - timedelta(seconds=APPLY_LOCK_STALE_S + 60))
        fresh = to_storage(now_utc() - timedelta(minutes=5))
        _write_status(update_env, {"apply": {"phase": "running",
                                             "started_at": old}})
        status, body = srv.get("/api/update/status")
        assert status == 200
        assert body["apply_stale"] is True
        _write_status(update_env, {"apply": {"phase": "running",
                                             "started_at": fresh}})
        _, body = srv.get("/api/update/status")
        assert body["apply_stale"] is False
        _write_status(update_env, {"apply": {"phase": "running"}})
        _, body = srv.get("/api/update/status")
        assert body["apply_stale"] is False
        _write_status(update_env, {"apply": {"phase": "failed",
                                             "finished_at": old}})
        _, body = srv.get("/api/update/status")
        assert body["apply_stale"] is False

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


@pytest.fixture()
def mirror_env(monkeypatch, tmp_path):
    """配置写读两端都指到临时文件（落盘单源 config_admin.USER_CONFIG_PATH；
    回读单源 self_update.USER_CONFIG_DIR——生产同为 ~/.fenix/config.yaml）。"""
    cfgdir = tmp_path / "fenix-config"
    cfgdir.mkdir()
    import core.dashboard.data as dash_data
    monkeypatch.setattr(dash_data, "USER_CONFIG_PATH", cfgdir / "config.yaml")
    monkeypatch.setattr(self_update_mod, "USER_CONFIG_DIR", cfgdir)
    return cfgdir


class TestUpdateMirrorRoute:
    """下载源自选两路由（2026-11-28 dashboard 设置页）。

    校验单源 core.self_update.normalize_mirror；落盘单源 config_admin.
    write_update_mirror（与设置页保存同 _CONFIG_WRITE_LOCK）。
    """

    def test_get_defaults_mirror(self, server_fx, mirror_env):
        # 2026-11-28 默认镜像通道：键缺失 → GET 回缺省镜像（ghfast）
        proot, srv = server_fx
        status, body = srv.get("/api/update/mirror")
        assert status == 200
        assert body["mirror"] == self_update_mod.UPDATE_MIRROR_DEFAULT
        assert [p["id"] for p in body["presets"]] == ["official", "ghfast", "ghproxy"]

    def test_post_preset_persists_and_get_roundtrip(self, server_fx, mirror_env):
        proot, srv = server_fx
        status, body = srv.post_json("/api/update/mirror", {
            "mirror": "https://ghfast.top/https://github.com"})
        assert status == 200
        assert body["ok"] is True
        assert body["mirror"] == "https://ghfast.top/https://github.com"
        import yaml
        data = yaml.safe_load(
            (mirror_env / "config.yaml").read_text(encoding="utf-8"))
        assert data["update"]["mirror"] == "https://ghfast.top/https://github.com"
        # 回读走引擎 load_update_config（编排进程同一路径，保存即生效）
        assert self_update_mod.load_update_config().mirror \
            == "https://ghfast.top/https://github.com"
        status, body = srv.get("/api/update/mirror")
        assert status == 200
        assert body["mirror"] == "https://ghfast.top/https://github.com"

    def test_post_custom_tail_and_trailing_slash_normalized(self, server_fx, mirror_env):
        proot, srv = server_fx
        status, body = srv.post_json("/api/update/mirror", {
            "mirror": "https://my-proxy.local:8443/https://github.com/"})
        assert status == 200
        assert body["mirror"] == "https://my-proxy.local:8443/https://github.com"

    def test_post_empty_back_to_official(self, server_fx, mirror_env):
        # 空串持久化为显式键（≠ 键缺失）：引擎 load 读回 ""（官方直连），
        # GET 回 ""（Radio 落在官方）——键缺失才会走缺省镜像通道。
        proot, srv = server_fx
        assert srv.post_json("/api/update/mirror", {
            "mirror": "https://ghfast.top/https://github.com"})[0] == 200
        status, body = srv.post_json("/api/update/mirror", {"mirror": ""})
        assert status == 200
        assert body["mirror"] == ""
        import yaml
        data = yaml.safe_load(
            (mirror_env / "config.yaml").read_text(encoding="utf-8"))
        assert data["update"]["mirror"] == ""
        assert self_update_mod.load_update_config().mirror == ""
        status, body = srv.get("/api/update/mirror")
        assert status == 200
        assert body["mirror"] == ""

    def test_post_invalid_rejected_400_machine_code(self, server_fx, mirror_env):
        proot, srv = server_fx
        for bad in ("http://x.com", "https://u:p@h.com/x", "a b",
                    "https://h.com/a?b=c"):
            status, body = srv.post_json("/api/update/mirror", {"mirror": bad})
            assert status == 400, bad
            assert body.get("code") == "invalid-mirror", bad

    def test_post_non_string_rejected(self, server_fx, mirror_env):
        proot, srv = server_fx
        status, body = srv.post_json("/api/update/mirror", {"mirror": 123})
        assert status == 400
        assert body.get("code") == "invalid-mirror"

    def test_post_missing_body_key_rejected(self, server_fx, mirror_env):
        proot, srv = server_fx
        status, body = srv.post_json("/api/update/mirror", {})
        assert status == 400
        assert body.get("code") == "invalid-mirror"

    def test_post_preserves_other_config_keys(self, server_fx, mirror_env):
        proot, srv = server_fx
        (mirror_env / "config.yaml").write_text(
            "update:\n  interval_hours: 6\nmodel:\n  provider: deepseek\n",
            encoding="utf-8")
        status, body = srv.post_json("/api/update/mirror", {
            "mirror": "https://ghfast.top/https://github.com"})
        assert status == 200
        import yaml
        data = yaml.safe_load(
            (mirror_env / "config.yaml").read_text(encoding="utf-8"))
        assert data["update"]["interval_hours"] == 6
        assert data["model"]["provider"] == "deepseek"

    def test_post_non_mapping_config_refused_400(self, server_fx, mirror_env):
        # 顶层非映射拒改（write_config 同款防线），400 + config-invalid 机器码
        proot, srv = server_fx
        (mirror_env / "config.yaml").write_text("- a\n- b\n", encoding="utf-8")
        status, body = srv.post_json("/api/update/mirror", {
            "mirror": "https://ghfast.top/https://github.com"})
        assert status == 400
        assert body.get("code") == "config-invalid"
        # 原文件未被覆盖
        assert (mirror_env / "config.yaml").read_text(encoding="utf-8") == "- a\n- b\n"


class TestUpdateProgressRoute:
    """GET /api/update/status 的 progress 透出口径：仅 apply 进行中，异常面降级。"""

    def _write(self, udir: Path, name: str, payload: dict) -> None:
        (udir / name).write_text(json.dumps(payload), encoding="utf-8")

    def test_running_phase_exposes_progress(self, server_fx, update_env):
        _, srv = server_fx
        udir = update_env
        self._write(udir, "status.json", {"apply": {"phase": "running"}})
        self._write(udir, "progress.json", {
            "asset": "fenixd-v0.2.2.tar.gz", "stage": "download",
            "downloaded": 5242880, "total": 13510665, "percent": 38.8,
            "attempt": 1, "updated_at": "2026-11-28T06:00:00+00:00"})
        status, body = srv.get("/api/update/status")
        assert status == 200
        assert body["progress"]["asset"] == "fenixd-v0.2.2.tar.gz"
        assert body["progress"]["percent"] == 38.8

    def test_terminal_phase_hides_progress(self, server_fx, update_env):
        _, srv = server_fx
        udir = update_env
        self._write(udir, "status.json", {"apply": {"phase": "failed"}})
        self._write(udir, "progress.json", {"asset": "a.gz", "stage": "download"})
        status, body = srv.get("/api/update/status")
        assert status == 200
        assert body["progress"] is None

    def test_no_progress_file_yields_null(self, server_fx, update_env):
        _, srv = server_fx
        udir = update_env
        self._write(udir, "status.json", {"apply": {"phase": "running"}})
        status, body = srv.get("/api/update/status")
        assert status == 200
        assert body["progress"] is None

    def test_corrupt_progress_file_degrades(self, server_fx, update_env):
        _, srv = server_fx
        udir = update_env
        self._write(udir, "status.json", {"apply": {"phase": "running"}})
        (udir / "progress.json").write_text("{broken", encoding="utf-8")
        status, body = srv.get("/api/update/status")
        assert status == 200
        assert body["progress"] is None

    def test_non_dict_or_assetless_payload_rejected(self, server_fx, update_env):
        _, srv = server_fx
        udir = update_env
        self._write(udir, "status.json", {"apply": {"phase": "running"}})
        self._write(udir, "progress.json", {"stage": "download"})  # 无 asset
        status, body = srv.get("/api/update/status")
        assert status == 200
        assert body["progress"] is None

    def test_never_checked_shape_carries_progress_null(self, server_fx, update_env):
        _, srv = server_fx
        status, body = srv.get("/api/update/status")
        assert status == 200
        assert body["checked"] is False
        assert body["progress"] is None
