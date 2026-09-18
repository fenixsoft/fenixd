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
                        "status", "has_draft", "spec_name", "created_at",
                        "doc_source"):
                assert key in it
        # 三项判定在 verdict 中
        va = next(i for i in items if i["id"] == "item-a")
        assert va["verdict"]["worth_spec"] is True
        assert va["has_draft"] is True
        vb = next(i for i in items if i["id"] == "item-b")
        assert vb["has_draft"] is False

    def test_doc_source_reflects_source(self, server_fx_with_fw):
        """doc_source：有草稿 → draft；无草稿无 spec → null；仅 SPEC → spec。"""
        proot, srv, ev = server_fx_with_fw
        fw = ev["fw"]
        from core.evolution import upsert_item
        # item-a（pending，有草稿）→ draft；item-b（analyzed，无 spec_name）→ null
        status, data = srv.get("/api/evolution/items")
        assert status == 200
        va = next(i for i in data["items"] if i["id"] == "item-a")
        assert va["doc_source"] == "draft"
        vb = next(i for i in data["items"] if i["id"] == "item-b")
        assert vb["doc_source"] is None
        # 已接受条目（草稿已删，spec/changes 就位）→ spec
        upsert_item(fw, {
            "id": "item-spec", "project": "proj-a", "date_section": "2026-09-12",
            "section": "浪费", "title": "已接受",
            "verdict": {"worth_spec": True}, "status": "accepted",
            "analysis_md": "md",
            "spec": {"name": "evo-doc-src", "capability": "cap-src",
                     "proposal_md": "# P", "design_md": "# D", "spec_md": "# S",
                     "tasks_md": "T"},
            "spec_name": "evo-doc-src",
            "created_at": "2026-09-15T00:00:00Z",
            "decided_at": "2026-09-15T01:00:00Z", "decided_by": "manual",
            "impact": "", "evidence": "", "analysis": "", "suggestion": "",
            "spec_summary": "", "degraded": None,
            "violations": None, "draft_failed_reason": None,
        })
        spec_dir = fw / "spec" / "changes" / "evo-doc-src"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "proposal.md").write_text("# P", encoding="utf-8")
        _st, data2 = srv.get("/api/evolution/items")
        vspec = next(i for i in data2["items"] if i["id"] == "item-spec")
        assert vspec["has_draft"] is False
        assert vspec["doc_source"] == "spec"

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


class TestEvolutionDraftSpecFallback:
    """草稿优先、SPEC 位置回退（evo-item-retention-doc-tracking 2.4）。

    覆盖：接受成功后草稿被删但 spec/changes 存在 → 四 doc 均 found:true；
    归档三形态（YYYY-MM-DD-<name> / YYYY-MM-DD-<name>-<n> / <name>-<epoch>）
    均能命中；互为前缀的 spec 名不相混；既无草稿又无 SPEC → found:false。
    """

    def _seed_accepted(self, fw, eid="item-accepted", spec_name="evo-accept-x",
                       capability="cap-x"):
        """构造已接受条目：spec_name 已写、无草稿目录。"""
        from core.evolution import upsert_item
        upsert_item(fw, {
            "id": eid, "project": "proj-a", "date_section": "2026-09-12",
            "section": "浪费", "title": "已接受问题",
            "verdict": {"worth_spec": True}, "status": "accepted",
            "analysis_md": "md",
            "spec": {"name": spec_name, "capability": capability,
                     "proposal_md": "# P", "design_md": "# D", "spec_md": "# S",
                     "tasks_md": "T"},
            "spec_name": spec_name,
            "created_at": "2026-09-12T00:00:00Z",
            "decided_at": "2026-09-12T01:00:00Z", "decided_by": "manual",
            "impact": "", "evidence": "", "analysis": "", "suggestion": "",
            "spec_summary": "", "degraded": None,
            "violations": None, "draft_failed_reason": None,
        })

    def _write_spec_dir(self, fw, spec_dir: Path, capability="cap-x"):
        """在 SPEC 目录落全套文档。"""
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "proposal.md").write_text("# P-active", encoding="utf-8")
        (spec_dir / "design.md").write_text("# D-active", encoding="utf-8")
        (spec_dir / "tasks.md").write_text("T-active", encoding="utf-8")
        (spec_dir / "specs" / capability).mkdir(parents=True, exist_ok=True)
        (spec_dir / "specs" / capability / "spec.md").write_text(
            "# S-active", encoding="utf-8")

    def _assert_four_docs(self, srv, eid, expect_prefix):
        """四个 doc 均 found:true 且内容带 expect 前缀。"""
        for doc in ("proposal", "design", "tasks", "spec"):
            status, data = srv.get(
                f"/api/evolution/draft?item_id={eid}&doc={doc}")
            assert status == 200
            assert data["found"] is True, f"{doc} 应命中 SPEC 位置"
            assert data["content"].startswith(expect_prefix[doc]), doc

    def test_accepted_draft_deleted_reads_from_changes(self, server_fx_with_fw):
        """接受成功后草稿被删但 spec/changes/<name>/ 存在 → 四 doc 取自 SPEC。"""
        proot, srv, ev = server_fx_with_fw
        fw = ev["fw"]
        self._seed_accepted(fw)
        spec_dir = fw / "spec" / "changes" / "evo-accept-x"
        self._write_spec_dir(fw, spec_dir)
        # 条目无草稿目录
        assert not (ev["evo"] / "drafts" / "item-accepted").exists()
        self._assert_four_docs(srv, "item-accepted", {
            "proposal": "# P-active", "design": "# D-active",
            "tasks": "T-active", "spec": "# S-active"})

    def test_archived_standard_date_prefix_form(self, server_fx_with_fw):
        """归档形态 YYYY-MM-DD-<name> 能命中。"""
        proot, srv, ev = server_fx_with_fw
        fw = ev["fw"]
        self._seed_accepted(fw)
        arch = fw / "spec" / "archive" / "2026-09-15-evo-accept-x"
        self._write_spec_dir(fw, arch)
        self._assert_four_docs(srv, "item-accepted", {
            "proposal": "# P-active", "design": "# D-active",
            "tasks": "T-active", "spec": "# S-active"})

    def test_archived_date_prefix_with_conflict_suffix(self, server_fx_with_fw):
        """归档形态 YYYY-MM-DD-<name>-<n>（冲突后缀）能命中。"""
        proot, srv, ev = server_fx_with_fw
        fw = ev["fw"]
        self._seed_accepted(fw)
        arch = fw / "spec" / "archive" / "2026-09-15-evo-accept-x-2"
        self._write_spec_dir(fw, arch)
        self._assert_four_docs(srv, "item-accepted", {
            "proposal": "# P-active", "design": "# D-active",
            "tasks": "T-active", "spec": "# S-active"})

    def test_archived_epoch_suffix_form(self, server_fx_with_fw):
        """归档形态 <name>-<epoch>（非标准/软删除移动形态）能命中。"""
        proot, srv, ev = server_fx_with_fw
        fw = ev["fw"]
        self._seed_accepted(fw)
        arch = fw / "spec" / "archive" / "evo-accept-x-1789359846"
        self._write_spec_dir(fw, arch)
        self._assert_four_docs(srv, "item-accepted", {
            "proposal": "# P-active", "design": "# D-active",
            "tasks": "T-active", "spec": "# S-active"})

    def test_archive_multiple_hits_sorted_last(self, server_fx_with_fw):
        """归一化后全等命中多个 → 取 sorted()[-1]（字典序最大目录）。"""
        proot, srv, ev = server_fx_with_fw
        fw = ev["fw"]
        self._seed_accepted(fw)
        # 两个目录归一化后都等于 evo-accept-x
        a1 = fw / "spec" / "archive" / "2026-09-10-evo-accept-x"
        a2 = fw / "spec" / "archive" / "2026-09-20-evo-accept-x"
        self._write_spec_dir(fw, a1, capability="cap-x")
        (a1 / "proposal.md").write_text("# P-early", encoding="utf-8")
        self._write_spec_dir(fw, a2, capability="cap-x")
        (a2 / "proposal.md").write_text("# P-late", encoding="utf-8")
        # 2026-09-20-evo-accept-x > 2026-09-10-evo-accept-x
        status, data = srv.get(
            "/api/evolution/draft?item_id=item-accepted&doc=proposal")
        assert status == 200
        assert data["found"] is True
        assert data["content"] == "# P-late"

    def test_prefix_spec_name_not_mixed(self, server_fx_with_fw):
        """互为前缀的 spec 名不相混：前缀目录 MUST NOT 命中较长 spec_name。"""
        proot, srv, ev = server_fx_with_fw
        fw = ev["fw"]
        # 长 spec_name：evo-add-fast-track-scale-precheck-4afdbe
        self._seed_accepted(fw, eid="item-long",
                            spec_name="evo-add-fast-track-scale-precheck-4afdbe")
        # 归档只有短名前缀形态（无日期前缀、非数字后缀）
        arch = fw / "spec" / "archive" / "evo-add-fast-track-scale-precheck"
        self._write_spec_dir(fw, arch)
        status, data = srv.get(
            "/api/evolution/draft?item_id=item-long&doc=proposal")
        assert status == 200
        assert data["found"] is False

    def test_short_spec_name_not_mixed_with_long_archive(self, server_fx_with_fw):
        """反向：短 spec_name 不得命中含较长名字的归档目录。"""
        proot, srv, ev = server_fx_with_fw
        fw = ev["fw"]
        self._seed_accepted(fw, eid="item-short",
                            spec_name="evo-add-fast-track-scale-precheck")
        arch = fw / "spec" / "archive" / "evo-add-fast-track-scale-precheck-4afdbe"
        self._write_spec_dir(fw, arch)
        status, data = srv.get(
            "/api/evolution/draft?item_id=item-short&doc=proposal")
        assert status == 200
        assert data["found"] is False

    def test_no_draft_no_spec_found_false(self, server_fx_with_fw):
        """既无草稿又无可解析 SPEC → found:false。"""
        proot, srv, ev = server_fx_with_fw
        fw = ev["fw"]
        # spec_name 合法但目录不存在
        self._seed_accepted(fw, eid="item-none", spec_name="evo-ghost-spec")
        status, data = srv.get(
            "/api/evolution/draft?item_id=item-none&doc=proposal")
        assert status == 200
        assert data["found"] is False

    def test_accept_end_to_end_spec_fallback(self, server_fx_with_fw):
        """端到端：真实接受后（草稿删、spec/changes 落目录）四 doc 可读回。"""
        proot, srv, ev = server_fx_with_fw
        fw = ev["fw"]
        # item-a 已有草稿；接受后草稿被删、spec/changes/evo-add-evo-a 就位
        status, data = srv.post_json(
            "/api/evolution/accept", {"item_id": "item-a"})
        assert status == 200 and data["ok"] is True
        assert data["spec_name"] == "evo-add-evo-a"
        assert not (ev["evo"] / "drafts" / "item-a").exists()
        # 四 doc 从 spec/changes 读回（内容与 seed 中的 spec 内容一致）
        for doc, key in (("proposal", "# P"), ("design", "# D"),
                         ("spec", "# S")):
            _st, d = srv.get(f"/api/evolution/draft?item_id=item-a&doc={doc}")
            assert _st == 200
            assert d["found"] is True, f"{doc} 应经 SPEC 回退读回"
            assert d["content"].startswith(key)
        _st, d = srv.get("/api/evolution/draft?item_id=item-a&doc=tasks")
        assert _st == 200
        assert d["found"] is True
        assert "Deliverables" in d["content"]


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

    def test_accept_with_start_after_schedules_spec(self, server_fx_with_fw):
        """start_after 透传到 STATE：新 SPEC 条目落定时拾取时刻。"""
        proot, srv, ev = server_fx_with_fw
        sa = "2026-09-15T18:00:00+00:00"
        status, data = srv.post_json(
            "/api/evolution/accept", {"item_id": "item-a", "start_after": sa})
        assert status == 200
        assert data["ok"] is True
        from core.state_machine import StateMachine
        sm = StateMachine(ev["fw"] / ".fenix" / "STATE.md", None)
        entry = sm.read_one("evo-add-evo-a")
        assert entry is not None
        assert entry.get("start_after") == sa

    def test_accept_explicit_null_start_after_is_immediate(self, server_fx_with_fw):
        """start_after 显式 null = 立即执行（设置页配了定时也能单条改回立即）。"""
        proot, srv, ev = server_fx_with_fw
        status, data = srv.post_json(
            "/api/evolution/accept", {"item_id": "item-a", "start_after": None})
        assert status == 200
        from core.state_machine import StateMachine
        sm = StateMachine(ev["fw"] / ".fenix" / "STATE.md", None)
        assert sm.read_one("evo-add-evo-a").get("start_after") is None

    @pytest.mark.parametrize("raw", ["manual", "MANUAL", " Manual "])
    def test_accept_manual_sentinel_creates_pending_spec(self, server_fx_with_fw, raw):
        """add-spec-manual-activation 10.4：start_after="manual" 接受成功，
        新建 SPEC 的 STATE entry start_after 为 "manual"（未被 parse_utc 拒绝）。

        大小写容错：端点判等 strip().lower() == "manual"（parametrize 三变体）。
        """
        from core.state_machine import StateMachine
        from core.dashboard.data import get_spec_start_after
        proot, srv, ev = server_fx_with_fw
        status, data = srv.post_json(
            "/api/evolution/accept", {"item_id": "item-a", "start_after": raw})
        assert status == 200, f"应接受哨兵变体: {raw!r}"
        assert data["ok"] is True
        sm = StateMachine(ev["fw"] / ".fenix" / "STATE.md", None)
        entry = sm.read_one("evo-add-evo-a")
        assert entry is not None
        assert entry.get("start_after") == "manual", (
            f"哨兵 {raw!r} 应规范化落入 STATE，实际 {entry.get('start_after')!r}")
        assert get_spec_start_after(entry) == "manual", (
            "读侧必须原样返回哨兵（前端待激活 tag 依赖）")

    def test_accept_invalid_start_after_400(self, server_fx_with_fw):
        """非法 start_after（非 ISO 字符串 / 非字符串）→ 400 且不立项。"""
        proot, srv, ev = server_fx_with_fw
        for bad in ("not-a-date", "2026-13-45T99:99:99Z", 12345, [1], {"a": 1}):
            status, data = srv.post_json(
                "/api/evolution/accept",
                {"item_id": "item-a", "start_after": bad})
            assert status == 400, f"应拒绝: {bad!r}"
        # 未立项：草稿目录仍在、STATE 无条目
        assert (ev["evo"] / "drafts" / "item-a").exists()
        from core.state_machine import StateMachine
        sm = StateMachine(ev["fw"] / ".fenix" / "STATE.md", None)
        assert sm.read_one("evo-add-evo-a") is None

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

    def test_spec_run_at_roundtrip_and_invalid_400(self, server_fx_with_fw,
                                                   monkeypatch, tmp_path):
        """spec_run_at：HH:mm 往返、显式 null 能取消定时、非法值 400。"""
        proot, srv, ev = server_fx_with_fw
        user_dir = tmp_path / "userhome"
        user_dir.mkdir(parents=True)
        monkeypatch.setattr("core.dashboard.data.USER_CONFIG_PATH",
                            user_dir / "config.yaml")
        status, data = srv.post_json(
            "/api/config?scope=user",
            {"self_evolution": {"spec_run_at": "02:00"}})
        assert status == 200
        status, data = srv.get("/api/config?scope=user")
        assert data["self_evolution"]["spec_run_at"] == "02:00"
        # 显式 null 覆盖已有的定时（UI 上「改回立即执行」必须写得掉）
        status, data = srv.post_json(
            "/api/config?scope=user",
            {"self_evolution": {"spec_run_at": None}})
        assert status == 200
        status, data = srv.get("/api/config?scope=user")
        assert data["self_evolution"]["spec_run_at"] is None
        # 非法 HH:mm
        for bad in ("25:00", "2:00", "02:60", "abc", 2, True):
            status, data = srv.post_json(
                "/api/config?scope=user",
                {"self_evolution": {"spec_run_at": bad}})
            assert status == 400, f"应拒绝: {bad!r}"

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

class TestEvolutionClearTodoAPI:
    """POST /api/evolution/clear-todo — 清空所有项目的 .fenix/todo.md。"""

    def test_clears_todo_but_leaves_items(self, server_fx_with_fw):
        proot, srv, ev = server_fx_with_fw
        todo = proot / ".fenix" / "todo.md"
        todo.write_text("## 2026-09-14\n\n### 浪费\n- **问题 A**\n",
                        encoding="utf-8")
        status, data = srv.post_json("/api/evolution/clear-todo", {})
        assert status == 200
        assert data["ok"] is True
        assert data["cleared"] == ["proj-a"]
        assert data["failed"] == []
        # 文件保留但内容为空
        assert todo.is_file()
        assert todo.read_text(encoding="utf-8") == ""
        # 清空范围仅限 todo.md：条目列表（items.jsonl）不受影响
        _, items = srv.get("/api/evolution/items")
        assert len(items["items"]) == 2

    def test_project_without_todo_is_skipped(self, server_fx_with_fw):
        proot, srv, ev = server_fx_with_fw
        assert not (proot / ".fenix" / "todo.md").exists()
        status, data = srv.post_json("/api/evolution/clear-todo", {})
        assert status == 200
        assert data["ok"] is True  # 全跳过亦为 ok（无失败项）
        assert data["cleared"] == []
        assert data["skipped"] == [{"project": "proj-a", "reason": "无 todo.md"}]
        assert data["failed"] == []

    def test_no_project_param_accepted(self, server_fx_with_fw):
        """全局动作：带 project 查询参数不改变行为（端点不接受项目参数）。"""
        proot, srv, ev = server_fx_with_fw
        (proot / ".fenix" / "todo.md").write_text("x\n", encoding="utf-8")
        status, data = srv.post_json("/api/evolution/clear-todo?project=proj-a", {})
        assert status == 200
        assert data["cleared"] == ["proj-a"]
