# -*- coding: utf-8 -*-
"""test_dashboard_prototype_routes.py — /proto/ 原型伺服与批注落盘路由测试。

fenix-prototype 独立 serve_prototype.py 退役后（add-proto-dashboard-serving），
原型静态伺服（GET /proto/<project>/<spec>/<file>）与批注落盘
（POST /api/proto/<project>/<spec>/feedback）由 dashboard 常驻进程承载。
本文件用 conftest._TestServer 直起实例（不依赖 dist 构建产物），覆盖：

- 静态伺服 happy path（index.html / 子目录资产 / 含空格文件名 / 无尾斜杠 301）
- 防穿越（「..」、绝对段 %2F、NUL %00 不 500）
- feedback.json 及其派生名屏蔽、白名单外后缀 404、未注册项目/缺失 spec 404
- 批注 POST 落盘、字段校验 400、损坏隔离 warning、dict 形态结构保留、
  409 拒绝手工整理形态、507 总量上限
- 非 /api/ POST 405 不变量（/proto/ 前缀不豁免）
- prototype_io 纯函数单元（spec_segment_safe / append_feedback 语义）
"""

import json
from pathlib import Path

import pytest

import core.dashboard.prototype_io as prototype_io
from core.dashboard.prototype_io import (
    FeedbackWriteRejected,
    append_feedback,
    spec_segment_safe,
)

from conftest import Registry, _TestServer, make_project

PROTO_INDEX = "<!doctype html><html><body><h1>proto-spec-x</h1></body></html>"


def _make_proto_project(tmp_path: Path) -> tuple[Path, _TestServer]:
    """注册一个 proj-a 项目并在其 .fenix/prototypes/spec-x/ 铺原型资产。"""
    proot = make_project(tmp_path)
    proto = proot / ".fenix" / "prototypes" / "spec-x"
    (proto / "assets").mkdir(parents=True)
    (proto / "index.html").write_text(PROTO_INDEX, encoding="utf-8")
    (proto / "annotator.js").write_text("// annotator stub\n", encoding="utf-8")
    (proto / "assets" / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    (proto / "assets" / "my img.png").write_bytes(b"\x89PNG\r\n\x1a\nfake2")
    (proto / "feedback.json").write_text("[]", encoding="utf-8")
    (proto / "secret.py").write_text("PASSWORD = 'x'\n", encoding="utf-8")
    cfg = tmp_path / "dashboard.yaml"
    reg = Registry(config_path=cfg)
    reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
              "scan_dirs": []})
    return proot, _TestServer(reg, tmp_path)


@pytest.fixture()
def proto_srv(tmp_path):
    proot, srv = _make_proto_project(tmp_path)
    yield proot, srv
    srv.stop()


class TestPrototypeStaticServing:
    """GET /proto/<project>/<spec>/<file> 静态伺服。"""

    def test_index_with_trailing_slash(self, proto_srv):
        _, srv = proto_srv
        status, ctype, body = srv.get("/proto/proj-a/spec-x/", raw=True)
        assert status == 200
        assert "text/html" in ctype
        assert PROTO_INDEX.encode() in body

    def test_index_no_trailing_slash_redirects_301(self, proto_srv):
        # 目录形态无尾斜杠必须 301 补斜杠：原型页相对资源（src="annotator.js"）
        # 以文档 URL 为基解析，否则落到上级目录；query 须原样携带
        _, srv = proto_srv
        status, headers, body = srv.get_ex("/proto/proj-a/spec-x?proto_round=3")
        assert status == 301
        assert headers.get("Location") == "/proto/proj-a/spec-x/?proto_round=3"
        assert body == b""

    def test_nested_dir_no_trailing_slash_redirects(self, proto_srv):
        _, srv = proto_srv
        status, headers, _body = srv.get_ex("/proto/proj-a/spec-x/assets")
        assert status == 301
        assert headers.get("Location") == "/proto/proj-a/spec-x/assets/"

    def test_subdir_asset_png(self, proto_srv):
        _, srv = proto_srv
        status, ctype, body = srv.get("/proto/proj-a/spec-x/assets/logo.png", raw=True)
        assert status == 200
        assert "image/png" in ctype
        assert body.startswith(b"\x89PNG")

    def test_asset_with_space_percent_encoded(self, proto_srv):
        # 含空格文件名在网络上恒为 percent-encoded，不解码则合法资产 404
        _, srv = proto_srv
        status, ctype, _body = srv.get(
            "/proto/proj-a/spec-x/assets/my%20img.png", raw=True)
        assert status == 200
        assert "image/png" in ctype

    def test_missing_file_404(self, proto_srv):
        _, srv = proto_srv
        status, _ctype, _body = srv.get("/proto/proj-a/spec-x/nope.html", raw=True)
        assert status == 404

    def test_missing_spec_dir_404(self, proto_srv):
        _, srv = proto_srv
        status, _ctype, _body = srv.get("/proto/proj-a/spec-z/", raw=True)
        assert status == 404

    def test_unregistered_project_404(self, proto_srv):
        _, srv = proto_srv
        status, _ctype, _body = srv.get("/proto/no-such-proj/spec-x/", raw=True)
        assert status == 404

    def test_whitelist_blocks_source_suffix(self, proto_srv):
        # 白名单外后缀（含手工放入的 .py）不经通道外泄，404 与缺失不可区分
        _, srv = proto_srv
        status, _ctype, _body = srv.get("/proto/proj-a/spec-x/secret.py", raw=True)
        assert status == 404

    def test_feedback_json_blocked(self, proto_srv):
        # 批注回流数据只经 agent 从磁盘读，静态通道屏蔽 feedback.json
        _, srv = proto_srv
        status, _ctype, _body = srv.get(
            "/proto/proj-a/spec-x/feedback.json", raw=True)
        assert status == 403

    def test_feedback_derived_files_blocked(self, proto_srv):
        _, srv = proto_srv
        proto = proto_srv[0] / ".fenix" / "prototypes" / "spec-x"
        (proto / "feedback.json.corrupt-1.bak").write_text("[]", encoding="utf-8")
        (proto / "feedback.json.lock").write_text("", encoding="utf-8")
        for name in ("feedback.json.corrupt-1.bak", "feedback.json.lock"):
            status, _ctype, _body = srv.get(f"/proto/proj-a/spec-x/{name}", raw=True)
            assert status == 403, name

    def test_traversal_dotdot_in_file_part(self, proto_srv):
        _, srv = proto_srv
        status, _ctype, _body = srv.get(
            "/proto/proj-a/spec-x/../../../etc/passwd", raw=True)
        assert status in (403, 404)

    def test_traversal_encoded_dotdot_in_spec(self, proto_srv):
        # spec 段解码还原「..」搬迁攻击：先校验段，再 resolve 包含兜底
        _, srv = proto_srv
        status, _ctype, _body = srv.get(
            "/proto/proj-a/%2e%2e/%2e%2e/.fenix/STATE.md", raw=True)
        assert status in (403, 404)

    def test_traversal_encoded_dotdot_in_file(self, proto_srv):
        _, srv = proto_srv
        status, _ctype, _body = srv.get(
            "/proto/proj-a/spec-x/%2e%2e%2f%2e%2e%2f.fenix%2fSTATE.md", raw=True)
        assert status in (403, 404)

    def test_absolute_segment_in_file(self, proto_srv):
        # 绝对路径段丢弃前缀攻击（%2Ftmp%2F...）：unquote 后拼接会整体换根
        _, srv = proto_srv
        status, _ctype, _body = srv.get(
            "/proto/proj-a/spec-x/%2Ftmp%2Fsecret.py", raw=True)
        assert status in (403, 404)

    def test_nul_byte_no_500(self, proto_srv):
        # %00 解码产物混入 Path 后 .resolve() 抛 ValueError，必须结构化拒绝
        _, srv = proto_srv
        status, _ctype, _body = srv.get(
            "/proto/proj-a/spec-x/index.html%00.png", raw=True)
        assert status in (403, 404)

    def test_proto_prefix_never_falls_back_to_spa(self, proto_srv):
        # /proto/ 分支先于 SPA fallback：未知无扩展名路径不得回前端 index
        _, srv = proto_srv
        status, _ctype, body = srv.get("/proto/proj-a/spec-x/no-such-page", raw=True)
        assert status == 404
        assert b"proto-spec-x" not in body


class TestPrototypeFeedbackPost:
    """POST /api/proto/<project>/<spec>/feedback 批注落盘。"""

    def test_post_writes_feedback(self, proto_srv):
        proot, srv = proto_srv
        status, data = srv.post_json(
            "/api/proto/proj-a/spec-x/feedback",
            {"anchor": "btn-save", "text": "间距太挤", "round": 2},
        )
        assert status == 200
        assert data["ok"] is True
        feedback = json.loads(
            (proot / ".fenix" / "prototypes" / "spec-x" / "feedback.json")
            .read_text(encoding="utf-8"))
        assert feedback == [{"anchor": "btn-save", "text": "间距太挤", "round": 2}]

    def test_missing_anchor_400(self, proto_srv):
        _, srv = proto_srv
        status, _data = srv.post_json(
            "/api/proto/proj-a/spec-x/feedback", {"text": "only text"})
        assert status == 400

    def test_blank_text_400(self, proto_srv):
        _, srv = proto_srv
        status, _data = srv.post_json(
            "/api/proto/proj-a/spec-x/feedback", {"anchor": "a", "text": "   "})
        assert status == 400

    def test_invalid_json_400(self, proto_srv):
        _, srv = proto_srv
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=10)
        conn.request("POST", "/api/proto/proj-a/spec-x/feedback", body=b"{bad",
                     headers={"Content-Type": "application/json",
                              "Content-Length": "4"})
        resp = conn.getresponse()
        resp.read()
        assert resp.status == 400
        conn.close()

    def test_no_body_400(self, proto_srv):
        _, srv = proto_srv
        status, _data = srv.post("/api/proto/proj-a/spec-x/feedback")
        assert status == 400

    def test_unknown_project_404(self, proto_srv):
        _, srv = proto_srv
        status, _data = srv.post_json(
            "/api/proto/no-such-proj/spec-x/feedback",
            {"anchor": "a", "text": "t"})
        assert status == 404

    def test_unknown_spec_404(self, proto_srv):
        _, srv = proto_srv
        status, _data = srv.post_json(
            "/api/proto/proj-a/spec-z/feedback", {"anchor": "a", "text": "t"})
        assert status == 404

    def test_traversal_spec_post_403(self, proto_srv):
        _, srv = proto_srv
        status, _data = srv.post_json(
            "/api/proto/proj-a/%2e%2e/feedback", {"anchor": "a", "text": "t"})
        assert status in (403, 404)

    def test_corrupt_feedback_isolated_with_warning(self, proto_srv):
        # 损坏文件不得静默覆盖：改名隔离 .bak 并随响应 warning 回流
        proot, srv = proto_srv
        fb = proot / ".fenix" / "prototypes" / "spec-x" / "feedback.json"
        fb.write_text("not-json{{{", encoding="utf-8")
        status, data = srv.post_json(
            "/api/proto/proj-a/spec-x/feedback",
            {"anchor": "a", "text": "t", "round": 1})
        assert status == 200
        assert "warning" in data and "隔离" in data["warning"]
        backups = list(fb.parent.glob("feedback.json.corrupt-*.bak"))
        assert len(backups) == 1
        assert "not-json{{{" in backups[0].read_text(encoding="utf-8")
        assert json.loads(fb.read_text(encoding="utf-8")) == [
            {"anchor": "a", "text": "t", "round": 1}]

    def test_dict_form_preserves_round_field(self, proto_srv):
        # annotator.js 本地导出形态 {"feedback": [...], "round": N}：追加后
        # 结构保留，round 等同级字段不丢
        proot, srv = proto_srv
        fb = proot / ".fenix" / "prototypes" / "spec-x" / "feedback.json"
        fb.write_text(json.dumps(
            {"feedback": [{"anchor": "old", "text": "旧批注", "round": 1}],
             "round": 1}), encoding="utf-8")
        status, data = srv.post_json(
            "/api/proto/proj-a/spec-x/feedback",
            {"anchor": "new", "text": "新批注", "round": 2})
        assert status == 200 and data["ok"] is True
        assert "warning" not in data
        doc = json.loads(fb.read_text(encoding="utf-8"))
        assert doc["round"] == 1
        assert [e["anchor"] for e in doc["feedback"]] == ["old", "new"]
        assert doc["feedback"][1]["round"] == 2

    def test_dict_without_feedback_list_409(self, proto_srv):
        # 手工整理形态（dict 但无 feedback 列表）拒绝追加，不整体覆盖
        proot, srv = proto_srv
        fb = proot / ".fenix" / "prototypes" / "spec-x" / "feedback.json"
        fb.write_text(json.dumps({"note": "手工整理"}), encoding="utf-8")
        status, data = srv.post_json(
            "/api/proto/proj-a/spec-x/feedback", {"anchor": "a", "text": "t"})
        assert status == 409
        assert json.loads(fb.read_text(encoding="utf-8")) == {"note": "手工整理"}

    def test_oversize_file_507(self, proto_srv, monkeypatch):
        # 总量上限（8MB，单测缩到 32B）超限拒绝写入
        _, srv = proto_srv
        monkeypatch.setattr(prototype_io, "MAX_FEEDBACK_FILE_BYTES", 32)
        status, _data = srv.post_json(
            "/api/proto/proj-a/spec-x/feedback",
            {"anchor": "a", "text": "t" * 64})
        assert status == 507

    def test_non_api_post_stays_405(self, proto_srv):
        # /proto/ 前缀不豁免「非 /api/ POST 一律 405」不变量
        _, srv = proto_srv
        status, _data = srv.post("/proto/proj-a/spec-x/feedback")
        assert status == 405

    def test_get_feedback_endpoint_not_registered(self, proto_srv):
        # GET 侧未注册该路径：/api/ 前缀 JSON 404，不静默伺服文件
        _, srv = proto_srv
        status, _data = srv.get("/api/proto/proj-a/spec-x/feedback")
        assert status == 404


class TestPrototypeIoUnits:
    """prototype_io 纯函数单元。"""

    def test_spec_segment_safe(self):
        assert spec_segment_safe("spec-x") is True
        assert spec_segment_safe("order_list_v2") is True
        assert spec_segment_safe("") is False
        assert spec_segment_safe(".") is False
        assert spec_segment_safe("..") is False
        assert spec_segment_safe("a/../b") is False
        assert spec_segment_safe("a\\..\\b") is False
        assert spec_segment_safe("/abs") is False
        assert spec_segment_safe("a\x00") is False

    def test_append_feedback_list_form(self, tmp_path):
        target, note = append_feedback(tmp_path, {"anchor": "a", "text": "t"})
        assert note is None
        assert json.loads(target.read_text(encoding="utf-8")) == [
            {"anchor": "a", "text": "t"}]

    def test_append_feedback_creates_missing_file(self, tmp_path):
        # 无既有文件（首个批注）直接建文件，不需要先落地空数组
        target, note = append_feedback(tmp_path, {"anchor": "a", "text": "t"})
        assert note is None and target.is_file()

    def test_append_feedback_rejects_non_dict(self, tmp_path):
        with pytest.raises(FeedbackWriteRejected) as ei:
            append_feedback(tmp_path, "not-a-dict")
        assert ei.value.status == 400
