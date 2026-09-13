"""Dashboard 建议改进项 API 测试（add-framework-self-evolution 6.7）。

5 个端点（GET items / analysis / draft、POST accept / reject）与配置读写
（用户级往返、非法值 400、项目级写 self_evolution 被拒）的真实 HTTP 验证。

关键隔离：端点读取框架根 ``FRAMEWORK_ROOT``（server.py 模块级）下的
``.fenix/evolution/``——测试把该模块级常量 monkeypatch 到临时框架根，
全部请求都落在隔离目录（接受/拒绝路径含真实 git 操作，同样隔离在临时 repo）。
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import core.dashboard.server as server_mod  # noqa: E402


def _make_framework_root(tmp_path: Path) -> Path:
    """构造自托管框架根（git repo + .fenix/evolution 目录）。"""
    fw = tmp_path / "framework"
    fw.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(fw)], check=True,
                   capture_output=True, timeout=30)
    subprocess.run(["git", "-C", str(fw), "config", "user.email",
                    "test@fenix.local"], check=True, capture_output=True,
                   timeout=30)
    subprocess.run(["git", "-C", str(fw), "config", "user.name", "Fenix Test"],
                   check=True, capture_output=True, timeout=30)
    (fw / "spec").mkdir(parents=True, exist_ok=True)
    (fw / "spec" / "changes").mkdir(parents=True, exist_ok=True)
    (fw / "README.md").write_text("fw", encoding="utf-8")
    subprocess.run(["git", "-C", str(fw), "add", "--", "README.md"],
                   check=True, capture_output=True, timeout=30)
    subprocess.run(["git", "-C", str(fw), "commit", "-m", "init"],
                   check=True, capture_output=True, timeout=30)
    return fw


@pytest.fixture()
def evo_env(monkeypatch, tmp_path):
    """临时框架根 + 条目存储（items.jsonl + 水位），monkeypatch FRAMEWORK_ROOT。"""
    fw = _make_framework_root(tmp_path)
    from core.evolution import (
        upsert_item, advance_watermark, materialize_draft)
    evo = fw / ".fenix" / "evolution"

    def _seed(rec: dict, with_draft=False):
        upsert_item(fw, rec)
        if with_draft and isinstance(rec.get("spec"), dict):
            materialize_draft(rec, fw)
        return rec

    recs = {}
    recs["item-a"] = _seed({
        "id": "item-a", "project": "proj-a", "date_section": "2026-09-12",
        "section": "浪费", "title": "问题 A", "impact": "i", "evidence": "e",
        "analysis": "a", "suggestion": "s",
        "verdict": {"problem_exists": "yes", "suggestion_sound": "yes",
                    "worth_spec": True, "rationale": "证据: t.py:1"},
        "analysis_md": "## 分析A\n结论：应立项。",
        "spec": {"name": "add-evo-a", "capability": "evo-cap",
                 "proposal_md": "# P", "design_md": "# D", "spec_md": "# S",
                 "tasks_md": "## Deliverables\n\n- path: a.txt\n  kind: new\n"},
        "spec_summary": "", "degraded": None,
        "created_at": "2026-09-12T00:00:00Z", "decided_at": None,
        "decided_by": None, "spec_name": None,
        "violations": None, "draft_failed_reason": None,
        "status": "pending",
    }, with_draft=True)
    recs["item-b"] = _seed({
        "id": "item-b", "project": "proj-b", "date_section": "2026-09-13",
        "section": "可改进", "title": "问题 B", "verdict": {"worth_spec": False},
        "analysis_md": "## 分析B\n不需要立项。", "status": "analyzed",
        "created_at": "2026-09-13T00:00:00Z",
        "impact": "", "evidence": "", "analysis": "", "suggestion": "",
        "spec": None, "spec_summary": "", "degraded": None,
        "decided_at": None, "decided_by": None, "spec_name": None,
        "violations": None, "draft_failed_reason": None,
    })
    monkeypatch.setattr(server_mod, "FRAMEWORK_ROOT", fw)
    return {"fw": fw, "evo": evo, "recs": recs}


@pytest.fixture()
def server_fx_with_fw(server_fx, evo_env):
    proot, srv = server_fx
    return proot, srv, evo_env


class TestEvolutionItemsAPI:
    """GET /api/evolution/items — 摘要列表。"""

    def test_list_fields_and_order(self, server_fx_with_fw):
        proot, srv, ev = server_fx_with_fw
        status, data = srv.get("/api/evolution/items")
        assert status == 200
        items = data["items"]
        assert len(items) == 2
        # 按 created_at 倒序：item-b（09-13）在前
        assert items[0]["id"] == "item-b"
        assert items[1]["id"] == "item-a"
        # 字段完整性
        for it in items:
            for key in ("id", "project", "date_section", "section", "title",
                        "status", "has_draft", "spec_name", "created_at"):
                assert key in it
        # 三项判定在 verdict 中
        va = next(i for i in items if i["id"] == "item-a")
        assert va["verdict"]["worth_spec"] is True
        assert va["has_draft"] is True
        vb = next(i for i in items if i["id"] == "item-b")
        assert vb["has_draft"] is False

    def test_list_project_filter(self, server_fx_with_fw):
        proot, srv, ev = server_fx_with_fw
        status, data = srv.get("/api/evolution/items?project=proj-a")
        assert status == 200
        ids = [i["id"] for i in data["items"]]
        assert ids == ["item-a"]

    def test_list_empty_when_missing(self, server_fx_with_fw, monkeypatch):
        proot, srv, ev = server_fx_with_fw
        empty = Path(tempfile.mkdtemp())
        monkeypatch.setattr(server_mod, "FRAMEWORK_ROOT", empty)
        status, data = srv.get("/api/evolution/items")
        assert status == 200
        assert data["items"] == []


class TestEvolutionAnalysisAPI:
    """GET /api/evolution/analysis — 分析结论全文。"""

    def test_returns_analysis_md(self, server_fx_with_fw):
        proot, srv, ev = server_fx_with_fw
        status, data = srv.get("/api/evolution/analysis?item_id=item-a")
        assert status == 200
        assert data["found"] is True
        assert "结论：应立项" in data["content"]

    def test_missing_item_id_400(self, server_fx_with_fw):
        proot, srv, ev = server_fx_with_fw
        status, data = srv.get("/api/evolution/analysis")
        assert status == 400

    def test_unknown_item_404(self, server_fx_with_fw):
        proot, srv, ev = server_fx_with_fw
        status, data = srv.get("/api/evolution/analysis?item_id=nope")
        assert status == 404


class TestEvolutionDraftAPI:
    """GET /api/evolution/draft — 草稿文档读取。"""

    def test_draft_doc_roundtrip(self, server_fx_with_fw):
        proot, srv, ev = server_fx_with_fw
        status, data = srv.get(
            "/api/evolution/draft?item_id=item-a&doc=proposal")
        assert status == 200
        assert data["found"] is True
        assert data["content"] == "# P"

    def test_draft_spec_doc(self, server_fx_with_fw):
        proot, srv, ev = server_fx_with_fw
        status, data = srv.get(
            "/api/evolution/draft?item_id=item-a&doc=spec")
        assert status == 200
        assert data["found"] is True
        assert data["content"] == "# S"

    def test_invalid_doc_400(self, server_fx_with_fw):
        """非法 doc → 400（不读取草稿目录之外的文件）。"""
        proot, srv, ev = server_fx_with_fw
        status, data = srv.get(
            "/api/evolution/draft?item_id=item-a&doc=readme")
        assert status == 400

    def test_unknown_item_404(self, server_fx_with_fw):
        proot, srv, ev = server_fx_with_fw
        status, data = srv.get(
            "/api/evolution/draft?item_id=nope&doc=proposal")
        assert status == 404

    def test_draft_missing_found_false(self, server_fx_with_fw):
        """条目存在但无草稿（analyzed）→ 200 + found:false。"""
        proot, srv, ev = server_fx_with_fw
        status, data = srv.get(
            "/api/evolution/draft?item_id=item-b&doc=proposal")
        assert status == 200
        assert data["found"] is False

    def test_path_param_ignored(self, server_fx_with_fw):
        """任意 path 参数被忽略（读取范围仍由 item_id 推导）。"""
        proot, srv, ev = server_fx_with_fw
        status, data = srv.get(
            "/api/evolution/draft?item_id=item-a&doc=proposal&path=/etc/passwd")
        assert status == 200
        assert data["content"] == "# P"


class TestEvolutionAcceptRejectAPI:
    """POST /api/evolution/accept | /api/evolution/reject。"""

    def test_accept_success(self, server_fx_with_fw):
        proot, srv, ev = server_fx_with_fw
        status, data = srv.post_json(
            "/api/evolution/accept", {"item_id": "item-a"})
        assert status == 200
        assert data["ok"] is True
        assert data["status"] == "accepted"
        assert data["spec_name"] == "evo-add-evo-a"
        # STATE 已注册 drafted
        state = ev["fw"] / ".fenix" / "STATE.md"
        assert state.is_file()
        # 暂存草稿已删除
        assert not (ev["evo"] / "drafts" / "item-a").exists()

    def test_accept_missing_item_id_400(self, server_fx_with_fw):
        proot, srv, ev = server_fx_with_fw
        status, data = srv.post_json("/api/evolution/accept", {})
        assert status == 400

    def test_accept_unknown_item_404(self, server_fx_with_fw):
        proot, srv, ev = server_fx_with_fw
        status, data = srv.post_json(
            "/api/evolution/accept", {"item_id": "nope"})
        assert status == 404

    def test_reject_success(self, server_fx_with_fw):
        proot, srv, ev = server_fx_with_fw
        # 新增一条 pending 且无草稿目录的条目（拒绝无需删文件）
        from core.evolution import upsert_item
        upsert_item(ev["fw"], {
            "id": "item-c", "project": "proj-c", "date_section": "2026-09-14",
            "section": "失误", "title": "问题 C",
            "verdict": {"worth_spec": False}, "status": "pending",
            "analysis_md": "md", "created_at": "2026-09-14T00:00:00Z",
            "impact": "", "evidence": "", "analysis": "", "suggestion": "",
            "spec": None, "spec_summary": "", "degraded": None,
            "decided_at": None, "decided_by": None, "spec_name": None,
            "violations": None, "draft_failed_reason": None,
        })
        status, data = srv.post_json(
            "/api/evolution/reject", {"item_id": "item-c"})
        assert status == 200
        assert data["ok"] is True
        assert data["status"] == "rejected"

    def test_reject_accepted_returns_error(self, server_fx_with_fw):
        proot, srv, ev = server_fx_with_fw
        srv.post_json("/api/evolution/accept", {"item_id": "item-a"})
        status, data = srv.post_json(
            "/api/evolution/reject", {"item_id": "item-a"})
        assert status == 200
        assert data["ok"] is False


class TestEvolutionDeleteAPI:
    """POST /api/evolution/delete —— 硬删条目（任意状态可删）。"""

    def test_delete_removes_record_and_draft(self, server_fx_with_fw):
        proot, srv, ev = server_fx_with_fw
        assert (ev["evo"] / "drafts" / "item-a").exists()
        status, data = srv.post_json(
            "/api/evolution/delete", {"item_id": "item-a"})
        assert status == 200
        assert data["ok"] is True
        # 记录移出 items.jsonl，其它条目不受影响
        _st, listing = srv.get("/api/evolution/items")
        ids = [i["id"] for i in listing["items"]]
        assert "item-a" not in ids
        assert "item-b" in ids
        # 草稿目录一并清理
        assert not (ev["evo"] / "drafts" / "item-a").exists()

    def test_delete_analyzed_item_allowed(self, server_fx_with_fw):
        """不需要立项（analyzed，无草稿）同样可删。"""
        proot, srv, ev = server_fx_with_fw
        status, data = srv.post_json(
            "/api/evolution/delete", {"item_id": "item-b"})
        assert status == 200
        assert data["ok"] is True
        _st, listing = srv.get("/api/evolution/items")
        assert [i["id"] for i in listing["items"]] == ["item-a"]

    def test_delete_missing_item_id_400(self, server_fx_with_fw):
        proot, srv, ev = server_fx_with_fw
        status, data = srv.post_json("/api/evolution/delete", {})
        assert status == 400

    def test_delete_unknown_item_404(self, server_fx_with_fw):
        proot, srv, ev = server_fx_with_fw
        status, data = srv.post_json(
            "/api/evolution/delete", {"item_id": "nope"})
        assert status == 404


class TestEvolutionConfigAPI:
    """self_evolution 配置读写（用户级往返 / 非法值 400 / 项目级拒绝）。"""

    def _user_cfg(self, tmp_path):
        return tmp_path / ".fenix" / "config.yaml"

    def test_user_level_read_write_roundtrip(self, server_fx_with_fw,
                                             monkeypatch, tmp_path):
        proot, srv, ev = server_fx_with_fw
        # 用临时用户级配置目录隔离（避免污染真实 ~/.fenix）
        user_dir = tmp_path / "userhome"
        user_dir.mkdir(parents=True)
        monkeypatch.setattr("core.dashboard.data.USER_CONFIG_PATH",
                            user_dir / "config.yaml")
        # 写
        status, data = srv.post_json(
            "/api/config?scope=user",
            {"self_evolution": {"auto_accept": True, "max_items_per_run": 7}})
        assert status == 200
        assert data.get("saved") is True
        # 读回
        status, data = srv.get("/api/config?scope=user")
        assert status == 200
        assert data["self_evolution"]["auto_accept"] is True
        assert data["self_evolution"]["max_items_per_run"] == 7

    def test_invalid_values_400(self, server_fx_with_fw, monkeypatch,
                                tmp_path):
        proot, srv, ev = server_fx_with_fw
        user_dir = tmp_path / "userhome"
        user_dir.mkdir(parents=True)
        monkeypatch.setattr("core.dashboard.data.USER_CONFIG_PATH",
                            user_dir / "config.yaml")
        # auto_accept 非布尔
        status, data = srv.post_json(
            "/api/config?scope=user",
            {"self_evolution": {"auto_accept": "yes"}})
        assert status == 400
        # max_items_per_run 越界
        status, data = srv.post_json(
            "/api/config?scope=user",
            {"self_evolution": {"max_items_per_run": 201}})
        assert status == 400
        status, data = srv.post_json(
            "/api/config?scope=user",
            {"self_evolution": {"max_items_per_run": 0}})
        assert status == 400
        # 未写盘
        cfg = user_dir / "config.yaml"
        if cfg.exists():
            assert "self_evolution" not in cfg.read_text(encoding="utf-8")

    def test_project_scope_rejected_and_not_written(self, server_fx_with_fw,
                                                    monkeypatch, tmp_path):
        proot, srv, ev = server_fx_with_fw
        # 项目级提交 self_evolution → 400
        status, data = srv.post_json(
            "/api/config?project=proj-a",
            {"self_evolution": {"auto_accept": True}})
        assert status == 400
        assert "user" in (data.get("error") or "").lower() or "全局" in (
            data.get("error") or "")
        # 项目级配置文件未被写入该键
        proj_cfg = proot / ".fenix" / "config.yaml"
        if proj_cfg.exists():
            assert "self_evolution" not in proj_cfg.read_text(encoding="utf-8")