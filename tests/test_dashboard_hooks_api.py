"""
tests/test_dashboard_hooks_api.py — Dashboard hooks API 测试（add-spec-hooks tasks 6.2）。

覆盖：
- 4.1 GET /api/hooks/audit：spec 过滤 / 时间倒序 / limit / 文件不存在空列表 / 项目不存在
- 4.2 POST /api/config hooks 段校验：events 非法 / 空 events / action 非法 /
     webhook 缺 url / shell 缺 command → 400 且不写入
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# _TestServer / server_fx 已收敛至 tests/conftest.py，本文件直接使用 server_fx 夹具


def _write_audit(proot: Path, lines: list):
    """写 .fenix/hook_audit.jsonl。lines 为记录 dict 列表，按序写入。"""
    path = proot / ".fenix" / "hook_audit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in lines) + "\n",
        encoding="utf-8",
    )


class TestHooksAuditGet:
    def test_audit_all_desc(self, server_fx):
        proot, srv = server_fx
        _write_audit(proot, [
            {"ts": "2026-09-06T10:00:00Z", "spec": "s1", "event": "done", "action": "commit",
             "scope": "global", "status": "success", "detail": "ok", "duration_ms": 5},
            {"ts": "2026-09-06T10:01:00Z", "spec": "s2", "event": "blocked", "action": "shell",
             "scope": "spec", "status": "failure", "detail": "bad", "duration_ms": 6},
            {"ts": "2026-09-06T10:02:00Z", "spec": "s1", "event": "blocked", "action": "webhook",
             "scope": "global", "status": "success", "detail": "resp", "duration_ms": 7},
        ])
        st, data = srv.get("/api/hooks/audit?project=proj-a")
        assert st == 200
        assert [r["spec"] for r in data["audit"]] == ["s1", "s2", "s1"]
        assert [r["ts"] for r in data["audit"]] == [
            "2026-09-06T10:02:00Z", "2026-09-06T10:01:00Z", "2026-09-06T10:00:00Z"]

    def test_audit_spec_filter(self, server_fx):
        proot, srv = server_fx
        _write_audit(proot, [
            {"ts": "2026-09-06T10:00:00Z", "spec": "s1", "event": "done", "action": "commit",
             "scope": "global", "status": "success"},
            {"ts": "2026-09-06T10:01:00Z", "spec": "s2", "event": "blocked", "action": "shell",
             "scope": "spec", "status": "failure"},
        ])
        st, data = srv.get("/api/hooks/audit?project=proj-a&spec=s1")
        assert st == 200
        assert len(data["audit"]) == 1
        assert data["audit"][0]["spec"] == "s1"

    def test_audit_limit(self, server_fx):
        proot, srv = server_fx
        _write_audit(proot, [
            {"ts": f"2026-09-06T10:0{i}:00Z", "spec": f"s{i}", "event": "done", "action": "commit",
             "scope": "global", "status": "success"} for i in range(5)
        ])
        st, data = srv.get("/api/hooks/audit?project=proj-a&limit=2")
        assert st == 200
        assert len(data["audit"]) == 2
        assert data["audit"][0]["spec"] == "s4"

    def test_audit_missing_file_empty(self, server_fx):
        _, srv = server_fx
        st, data = srv.get("/api/hooks/audit?project=proj-a")
        assert st == 200
        assert data["audit"] == []

    def test_audit_unknown_project_empty(self, server_fx):
        _, srv = server_fx
        st, data = srv.get("/api/hooks/audit?project=nope")
        assert st == 200
        assert data["audit"] == []

    def test_audit_corrupt_lines_skipped(self, server_fx):
        proot, srv = server_fx
        path = proot / ".fenix" / "hook_audit.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            '{"ts":"2026-09-06T10:00:00Z","spec":"s1","status":"success"}\n'
            "this is not json\n"
            '{"ts":"2026-09-06T10:02:00Z","spec":"s1","status":"success"}\n',
            encoding="utf-8",
        )
        st, data = srv.get("/api/hooks/audit?project=proj-a&spec=s1")
        assert st == 200
        assert len(data["audit"]) == 2


class TestConfigHooksValidation:
    """POST /api/config hooks 校验接线（tasks 4.2）。

    HTTP 侧只留 1 正 1 负两条接线用例（端点确实调用了校验器并落盘/拒绝）；
    校验规则矩阵归 test_hook_engine.py 单元侧（validate_hook_entry /
    validate_hooks_config，写路径经 data.write_config 调用同一函数）。
    """

    def test_valid_hooks_saved(self, server_fx):
        proot, srv = server_fx
        st, data = srv.post_json("/api/config?project=proj-a", {
            "hooks": {"global": [{"id": "h1", "enabled": True, "events": ["done"], "action": "commit"}]},
        })
        assert st == 200, data
        raw = (proot / ".fenix" / "config.yaml").read_text(encoding="utf-8")
        assert "h1" in raw

    def test_invalid_events_400(self, server_fx):
        proot, srv = server_fx
        st, data = srv.post_json("/api/config?project=proj-a", {
            "hooks": {"global": [{"events": ["bogus"], "action": "commit"}]},
        })
        assert st == 400
        assert "hooks" in data["error"]
        raw = (proot / ".fenix" / "config.yaml").read_text(encoding="utf-8")
        assert "bogus" not in raw
