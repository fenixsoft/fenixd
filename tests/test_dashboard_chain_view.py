"""Dashboard 处置链视图（add-escalation-chain-admin-arbiter 5.2）。

两层覆盖：
1. 数据层 ``chain_overview`` 单读聚合（tests 直调）：四视图派生（在办/
   配额水位/上升件/人工队列）、spec=null 主体键归组投影、fail-open 空态、
   缺省 cap 回落与 exhausted 判定；
2. API 层 ``GET /api/chain``（conftest server_fx 真起 server）：?project
   单项目与缺省跨项目聚合（逐条注入 project、summary 累加）、未知项目
   200+error 有意契约、零写动作（视图端点无 POST 侧效应）。
"""

import json
import sys
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from conftest import make_project  # noqa: E402

from core.admin_store import ESCALATION, AdminStore  # noqa: E402
from core.dashboard.data import chain_overview  # noqa: E402
from core.pm_engine.escalation_chain import ChainQuotaStore  # noqa: E402


def _seed_quota(proot, sig, attempts=0, rulings=0):
    store = ChainQuotaStore(proot)
    for _ in range(attempts):
        store.count_admin_attempt(sig)
    for _ in range(rulings):
        store.count_arbiter_ruling(sig)
    return store


def _seed_escalation(proot, spec=None, chain_sig=None, handled=False) -> str:
    store = AdminStore(proot)
    entry = {
        "kind": ESCALATION,
        "signal_type": "verify_env_blocked",
        "spec": spec,
        "severity": "major",
        "description": "链上升件描述",
        "evidence": "e",
        "recommended_action": "r",
    }
    if chain_sig:
        entry["chain"] = {"signature": chain_sig, "chain_id": "chain-1"}
    rec = store.append(entry)
    if handled:
        store.mark_handled(rec["id"])
    return rec["id"]


class TestChainOverviewDataLayer:
    """chain_overview 单读聚合四视图。"""

    @pytest.fixture()
    def proot(self, tmp_path):
        p = tmp_path / "proj"
        p.mkdir()
        (p / ".fenix").mkdir(parents=True)
        return p

    def test_empty_state_fail_open(self, proot):
        """状态文件缺失：全空态派生、零报错（观测面 fail-open）。"""
        view = chain_overview(proot)
        assert view["summary"] == {
            "in_flight": 0,
            "signatures": 0,
            "quota_exhausted": 0,
            "escalations": 0,
            "queue": 0,
        }
        assert view["in_flight"] == [] and view["signatures"] == []
        assert view["escalations"] == [] and view["queue"] == []

    def test_four_sections_derived(self, proot):
        """在办/配额/上升件/队列四视图派生与 exhausted 判定。"""
        _seed_quota(proot, "spec-a::verify_env_blocked", attempts=2, rulings=2)
        _seed_quota(proot, "spec-b::verify_env_blocked", attempts=1)
        ChainQuotaStore(proot).mark_in_flight(
            "chain-1", "spec-a::verify_env_blocked", "spec-a", "arbiter"
        )
        _seed_escalation(proot, spec="spec-a", chain_sig="spec-a::verify_env_blocked")
        _seed_escalation(
            proot, spec="spec-a", chain_sig="spec-a::verify_env_blocked", handled=True
        )
        _seed_escalation(proot, spec="spec-nochain")  # 无链关联键不入视图

        view = chain_overview(proot)
        assert view["summary"] == {
            "in_flight": 1,
            "signatures": 2,
            "quota_exhausted": 1,
            "escalations": 2,
            "queue": 1,
        }
        assert view["in_flight"][0]["phase"] == "arbiter"
        assert view["in_flight"][0]["chain_id"] == "chain-1"
        quads = {s["signature"]: s for s in view["signatures"]}
        assert quads["spec-a::verify_env_blocked"]["exhausted"] is True
        assert quads["spec-a::verify_env_blocked"]["admin_cap"] == 2
        assert quads["spec-a::verify_env_blocked"]["arbiter_cap"] == 2
        assert quads["spec-b::verify_env_blocked"]["exhausted"] is False
        # 上升件含已收口（close_cause 保留），queue 仅未收口子集
        assert len(view["escalations"]) == 2
        assert len(view["queue"]) == 1
        assert all(not r.get("handled") for r in view["queue"])

    def test_project_config_caps_reflected(self, proot):
        """项目级配置 cap 即时生效（quota_config 同源热更新）。"""
        cfg = proot / ".fenix" / "config.yaml"
        cfg.write_text(
            "chain:\n  admin_attempts: 3\n  arbiter_rulings: 1\n", encoding="utf-8"
        )
        _seed_quota(proot, "spec-a::gate", attempts=3, rulings=1)
        view = chain_overview(proot)
        sig = view["signatures"][0]
        assert sig["admin_cap"] == 3 and sig["arbiter_cap"] == 1
        assert sig["exhausted"] is True

    def test_subject_key_grouping_projection(self, proot):
        """spec=null 主体键归组：null:/global: 签名投影 subject/granularity。"""
        _seed_quota(proot, "null:检测器-1::verify_env_blocked", attempts=1)
        _seed_quota(proot, "global::verify_env_blocked", attempts=1)
        ChainQuotaStore(proot).record_recurrence("spec-a::gate")  # 零计数条目（仅 last_seen）
        view = chain_overview(proot)
        quads = {s["signature"]: s for s in view["signatures"]}
        subj = quads["null:检测器-1::verify_env_blocked"]
        assert subj["granularity"] == "subject" and subj["subject"] == "检测器-1"
        assert subj["spec"] == ""
        typ = quads["global::verify_env_blocked"]
        assert typ["granularity"] == "type" and typ["subject"] == ""
        spc = quads["spec-a::gate"]
        assert spc["granularity"] == "spec" and spc["spec"] == "spec-a"

    def test_corrupt_state_file_fail_open(self, proot):
        """状态文件损坏：空态派生不抛（load_chain_state 兜底贯通）。"""
        state_file = proot / ".fenix" / "escalation_chain_state.json"
        state_file.write_text("{broken json", encoding="utf-8")
        view = chain_overview(proot)
        assert view["summary"]["signatures"] == 0
        assert view["signatures"] == []


class TestChainApi:
    """GET /api/chain 路由（server_fx 真起 server）。"""

    def test_single_project_view(self, server_fx):
        proot, srv = server_fx
        _seed_quota(proot, "spec-a::verify_env_blocked", attempts=2)
        _seed_escalation(proot, spec="spec-a", chain_sig="spec-a::verify_env_blocked")
        status, body = srv.get("/api/chain?project=proj-a")
        assert status == 200
        assert body.get("error") is None
        assert body["project"] == "proj-a"
        assert body["summary"]["signatures"] == 1
        assert body["summary"]["escalations"] == 1
        assert body["signatures"][0]["signature"] == "spec-a::verify_env_blocked"
        assert body["escalations"][0]["chain"]["signature"] == "spec-a::verify_env_blocked"

    def test_aggregate_default_injects_project(self, tmp_path):
        """缺省跨项目聚合：逐条注入 project、summary 累加（fixture 项目跳过）。"""
        from core.dashboard.registry import Registry
        from conftest import _TestServer
        from core.proc_utils import find_free_port

        proot_a = tmp_path / "proj-a"
        proot_b = tmp_path / "proj-b"
        for p in (proot_a, proot_b):
            p.mkdir()
            (p / ".fenix").mkdir(parents=True)
        _seed_quota(proot_a, "spec-a::gate", attempts=1)
        _seed_quota(proot_b, "spec-b::gate", attempts=1, rulings=1)
        _seed_escalation(proot_a, spec="spec-a", chain_sig="spec-a::gate")
        _seed_escalation(proot_b, spec="spec-b", chain_sig="spec-b::gate", handled=True)

        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({
            "port": 8787,
            "projects": [
                {"name": "proj-a", "path": str(proot_a)},
                {"name": "proj-b", "path": str(proot_b)},
            ],
            "scan_dirs": [str(tmp_path / "scan-empty")],
        })
        srv = _TestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
        try:
            status, body = srv.get("/api/chain")
            assert status == 200
            assert body["total"] == {
                "in_flight": 0,
                "signatures": 2,
                "quota_exhausted": 0,
                "escalations": 2,
                "queue": 1,
            }
            assert {p["name"] for p in body["projects"]} == {"proj-a", "proj-b"}
            assert {r["project"] for r in body["signatures"]} == {"proj-a", "proj-b"}
            assert {r["project"] for r in body["escalations"]} == {"proj-a", "proj-b"}
            # queue 与 escalations 同源子集（未收口）
            assert len(body["queue"]) == 1
            assert body["queue"][0]["project"] == "proj-a"
            # created 倒序（跨项目合并后排序）
            created = [r.get("created") or "" for r in body["escalations"]]
            assert created == sorted(created, reverse=True)
        finally:
            srv.stop()

    def test_unknown_project_200_error_body(self, server_fx):
        """未知项目：有意 200+error 契约（同 _api_alerts，body.error 判错）。"""
        _, srv = server_fx
        status, body = srv.get("/api/chain?project=no-such")
        assert status == 200
        assert body == {"error": "project not found"}

    def test_read_only_no_post_route(self, server_fx):
        """零写动作：POST /api/chain 不落任何链侧写路径（404 派发）。"""
        proot, srv = server_fx
        _seed_quota(proot, "spec-a::gate", attempts=1)
        status, _body = srv.post("/api/chain")
        assert status == 404
        # 状态文件计数未被扰动
        assert ChainQuotaStore(proot).admin_attempts("spec-a::gate") == 1


class TestChainConfigChannel:
    """5.3 设置页链配置写回通道（write_config 白名单合并 + read 回显）。"""

    @pytest.fixture()
    def proot(self, tmp_path):
        p = tmp_path / "proj"
        p.mkdir()
        (p / ".fenix").mkdir(parents=True)
        return p

    def test_write_and_read_roundtrip(self, proot):
        from core.dashboard.data.config_admin import read_config, write_config

        out = write_config(
            str(proot),
            {
                "chain": {
                    "admin_attempts": 3,
                    "arbiter_rulings": 4,
                    "reset_window_days": 14,
                    "blacklist": ["verify_env_blocked", "spec_content_missing"],
                }
            },
        )
        assert out["ok"] is True, out
        view = read_config(str(proot))
        assert view["chain"]["admin_attempts"] == 3
        assert view["chain"]["arbiter_rulings"] == 4
        assert view["chain"]["reset_window_days"] == 14
        assert view["chain"]["blacklist"] == ["spec_content_missing", "verify_env_blocked"]
        # 落盘 yaml 直读复核（get_chain_config 归一链路贯通）
        import yaml

        raw = yaml.safe_load((proot / ".fenix" / "config.yaml").read_text(encoding="utf-8"))
        assert raw["chain"]["admin_attempts"] == 3
        # 生效值回显（read_effective_config 同段）
        from core.dashboard.data.config_admin import read_effective_config

        eff = read_effective_config(str(proot))
        assert eff["chain"]["arbiter_rulings"] == 4
        # 项目级 sources 标注（设置页徽标）
        assert eff["sources"].get("chain.admin_attempts") == "project"
        assert eff["sources"].get("chain.blacklist") == "project"

    def test_write_invalid_values_rejected(self, proot):
        """非法值 400 语义拒绝不落盘（D7 契约：bool/非正数/黑名单非字符串项）。"""
        from core.dashboard.data.config_admin import write_config

        for bad in (
            {"chain": {"admin_attempts": True}},
            {"chain": {"arbiter_rulings": 0}},
            {"chain": {"reset_window_days": -1}},
            {"chain": {"blacklist": "verify_env_blocked"}},
            {"chain": {"blacklist": ["ok-signal", ""]}},
            {"chain": "not-a-dict"},
        ):
            out = write_config(str(proot), bad)
            assert out["ok"] is False, f"{bad} 应被拒绝"
        # 全部拒绝后零落盘（前置校验在原子写之前）
        assert not (proot / ".fenix" / "config.yaml").exists()

    def test_empty_blacklist_write_through(self, proot):
        """空黑名单是有意显式值（清空 kill switch）：穿透落盘非「未提交」。"""
        from core.dashboard.data.config_admin import read_config, write_config

        assert write_config(
            str(proot), {"chain": {"blacklist": ["verify_env_blocked"]}}
        )["ok"] is True
        assert write_config(str(proot), {"chain": {"blacklist": []}})["ok"] is True
        import yaml

        raw = yaml.safe_load((proot / ".fenix" / "config.yaml").read_text(encoding="utf-8"))
        assert raw["chain"]["blacklist"] == []
        assert read_config(str(proot))["chain"]["blacklist"] == []
