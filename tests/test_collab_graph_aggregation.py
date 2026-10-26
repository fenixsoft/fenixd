"""tests/test_collab_graph_aggregation.py — 跨项目角色图谱聚合表驱动单测。

覆盖 add-collab-graph-bigscreen 任务 1.1–1.3 对应 specs/collab-graph-aggregation
的全部 Scenario（多项目聚合边权重求和、项目筛选收窄、跨项目在飞计数、归档
只进 KPI、归档项目零开销跳过、空项目不报错、下钻明细随聚合返回）+ 任务 2.1
端点（server_fx 起真实 DashboardHandler 的路由注册/错误契约/ETag）。

聚合语义单源复用 topology.derive_topology，本文件沿用
test_topology_derivation.py 的产物构造助手（run_id 前缀/STATE 形态同款）。
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conftest import _TestServer  # noqa: E402

from core.dashboard.data import collab_graph as cg
from core.dashboard.data.collab_graph import aggregate_collab_graph
from core.dashboard.registry import Registry
from core.proc_utils import find_free_port

# ── 固定时刻（ISO 带 tz，与 timelib 解析口径一致） ──
T_CREATED = "2026-03-01T00:00:00+00:00"
E1 = 1772000000
E2 = 1772000060
E3 = 1772000120
E4 = 1772000180
E5 = 1772000240
E6 = 1772000300


def _iso(epoch: int) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def make_proot(
    tmp_path: Path,
    dirname: str = "proj",
    specs: dict | None = None,
) -> Path:
    """最小可聚合项目：logs/runs 目录 + 活跃 spec 目录 + STATE 条目。

    specs: {spec_name: status}，缺省 {"demo": "testing"}；空 dict = 零 SPEC
    项目（任务 1.3 空项目边界）。
    """
    proot = tmp_path / dirname
    (proot / ".fenix" / "logs").mkdir(parents=True)
    (proot / ".fenix" / "runs").mkdir(parents=True)
    for spec, status in (specs if specs is not None else {"demo": "testing"}).items():
        (proot / "spec" / "changes" / spec).mkdir(parents=True, exist_ok=True)
    body = "# Fenix Project State\n\n## Specs\n"
    for spec, status in (specs if specs is not None else {"demo": "testing"}).items():
        body += (
            f"\n### {spec}\n- status: {status}\n- priority: 1\n"
            f"- created: {T_CREATED}\n- updated: {T_CREATED}\n"
        )
    (proot / ".fenix" / "STATE.md").write_text(body, encoding="utf-8")
    return proot


def write_archive_manifest(proot: Path, specs: list) -> None:
    """写归档清单（STATE.archive.md；条目已迁出活跃 STATE 的居所）。"""
    body = "# Fenix Project State\n\n## Specs\n"
    for spec in specs:
        body += f"\n### {spec}\n- status: done\n- created: {T_CREATED}\n"
    (proot / ".fenix" / "STATE.archive.md").write_text(body, encoding="utf-8")


def write_run(proot: Path, run_id: str, last_event: dict, start_ts: str = "") -> None:
    """写 run 产物：start 事件（带 timestamp 作真实起点）+ 终态事件。

    终态 run 产物 mtime 回拨到 start+30s：读侧 duration_seconds 无 run_metrics
    指标行时兜底为 mtime − started（真实形态假设 mtime ≈ 运行结束），夹具默认
    mtime=写入时刻（现在）会与事件时间轴（2026-02）自相矛盾，伪 8 个月时长令
    handoff 单一串行判定（prev.end ≤ cur.start，improve-spec-topology-pipeline-view
    2.1）把相距 60s 的串行链误判重叠、plan→dev/dev→review 边全灭。在飞 run
    不回拨——(now − mtime) > _RUN_STALE_SECONDS 会被读侧改判 stale，翻转在飞
    计数。
    """
    events = [{"type": "start", "message": "start"}]
    if start_ts:
        events[0]["timestamp"] = start_ts
    events.append(last_event)
    path = proot / ".fenix" / "runs" / f"{run_id}.jsonl"
    path.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n",
        encoding="utf-8",
    )
    if start_ts and last_event.get("type") != "progress":
        start_epoch = datetime.fromisoformat(start_ts).timestamp()
        os.utime(path, (start_epoch + 30, start_epoch + 30))


def write_handoff_chain(proot: Path, spec: str, running: bool = False) -> list:
    """写一条「规划→开发→审查」交接链（planner→impl→impl-ocr 三个 run）。

    running=True 时全部 run 无终态事件（classify_run 判 running，在飞）。
    返回写入的 run_id 列表（时间升序）。
    """
    run_ids = [f"planner-{spec}-{E1}", f"impl-{spec}-{E2}", f"impl-ocr-{spec}-{E3}"]
    for i, rid in enumerate(run_ids):
        last = {"type": "progress"} if running else {"type": "result"}
        write_run(proot, rid, last, start_ts=_iso(E1 + i * 60))
    return run_ids


def role_of(data, lane: str) -> dict:
    hit = [r for r in data["roles"] if r["id"] == lane]
    assert len(hit) == 1, f"role node missing: {lane}"
    return hit[0]


def edge_of(data, frm: str, to: str) -> dict:
    hit = [e for e in data["edges"] if e["from"] == frm and e["to"] == to]
    assert len(hit) == 1, f"edge missing: {frm}->{to}"
    return hit[0]


# ══ 任务 1.1：全局聚合出角色图 ═══════════════════════════════════════════


class TestAggregationScenarios:
    def test_multi_project_edge_weight_sum(self, tmp_path):
        """Scenario「全局聚合出角色图」：两项目各经历规划→开发→审查交接，
        「规划→开发」「开发→审查」边 weight 为两项目相应交接次数之和，角色
        节点固定为 8 个。"""
        pa = make_proot(tmp_path, "proj-a", {"spec-a": "testing"})
        pb = make_proot(tmp_path, "proj-b", {"spec-b": "testing"})
        write_handoff_chain(pa, "spec-a")
        write_handoff_chain(pb, "spec-b")
        data = aggregate_collab_graph(
            [
                {"name": "proj-a", "path": str(pa), "exists": True},
                {"name": "proj-b", "path": str(pb), "exists": True},
            ]
        )
        # 角色节点固定 8 个（topology.LANES 同源全集，零交接角色也在）
        assert [r["id"] for r in data["roles"]] == list(cg.LANES)
        assert len(data["roles"]) == 8
        # 跨项目边权重求和（跨角色 handoff + PMEngine 逐 run dispatch 均入边）
        assert edge_of(data, "plan", "dev")["weight"] == 2
        assert edge_of(data, "dev", "review")["weight"] == 2
        # 每项目各贡献一次 user→pm（SPEC 创建固定交接）与逐 run dispatch
        assert edge_of(data, "user", "pm")["weight"] == 2
        assert edge_of(data, "pm", "plan")["weight"] == 2
        assert edge_of(data, "pm", "dev")["weight"] == 2
        assert edge_of(data, "pm", "review")["weight"] == 2
        assert data["kpis"]["total_handoffs"] == 12
        assert data["kpis"]["spec_count"] == 2
        assert data["kpis"]["active_spec_count"] == 2
        assert data["archived_excluded"] == 0
        # 节点权重：run 计数聚合（每项目 规划/开发/审查 各 1）
        assert role_of(data, "plan")["run_count"] == 2
        assert role_of(data, "dev")["run_count"] == 2
        assert role_of(data, "review")["run_count"] == 2
        assert data["kpis"]["total_runs"] == 6
        # 归列与 attempt 归并零第二套实现：项目归属明细来自 topology 派生
        assert data["projects"] == ["proj-a", "proj-b"]

    def test_recent_runs_embedded(self, tmp_path):
        """Scenario「下钻明细随聚合返回」：开发角色节点的 recent_runs 含该
        run 明细（项目名/SPEC 名/时间/状态），对应交接边的明细列表同样携带。"""
        pa = make_proot(tmp_path, "proj-a", {"spec-a": "testing"})
        write_handoff_chain(pa, "spec-a")
        data = aggregate_collab_graph([{"name": "proj-a", "path": str(pa), "exists": True}])
        dev = role_of(data, "dev")
        assert [e["project"] for e in dev["recent_runs"]] == ["proj-a"]
        entry = dev["recent_runs"][0]
        assert entry["spec"] == "spec-a"
        assert entry["time"] == _iso(E2)
        assert entry["status"] == "done"
        edge = edge_of(data, "plan", "dev")
        assert len(edge["recent_runs"]) == 1
        assert edge["recent_runs"][0]["project"] == "proj-a"
        assert edge["recent_runs"][0]["status"] == "done"
        # 审查侧边明细取接收方 run（impl-ocr）
        assert edge_of(data, "dev", "review").get("recent_runs") == [
            {
                "project": "proj-a",
                "spec": "spec-a",
                "time": _iso(E3),
                "status": "done",
            }
        ]

    def test_recent_runs_capped_and_sorted(self, tmp_path):
        """明细条数上限（实现裁量 RECENT_RUNS_CAP）+ 时间降序。"""
        pa = make_proot(tmp_path, "proj-a", {"spec-a": "testing"})
        # 同角色写入 CAP+2 个 run（时间递增）
        for i in range(cg.RECENT_RUNS_CAP + 2):
            write_run(pa, f"impl-spec-a-{E1 + i * 60}", {"type": "result"}, start_ts=_iso(E1 + i * 60))
        data = aggregate_collab_graph([{"name": "proj-a", "path": str(pa), "exists": True}])
        dev = role_of(data, "dev")
        assert len(dev["recent_runs"]) == cg.RECENT_RUNS_CAP
        times = [e["time"] for e in dev["recent_runs"]]
        assert times == sorted(times, reverse=True)
        # 保留的是最近 CAP 条（最旧两条被截断）
        assert times[0] == _iso(E1 + (cg.RECENT_RUNS_CAP + 1) * 60)

    def test_recent_runs_unparseable_time_sorted_last(self):
        """排序契约：time 解析失败（含缺失）的明细在降序列表排**末尾**，
        不反超可解析条目，优先被 RECENT_RUNS_CAP 截断而非挤掉正常条目。"""
        bucket: list = []
        for entry in ({"time": _iso(E1)}, {"time": "not-a-ts"}, {}, {"time": _iso(E3)}):
            cg._push_recent(bucket, entry)
        assert [e.get("time") for e in bucket] == [_iso(E3), _iso(E1), "not-a-ts", None]
        # 失败条目垫底 → 先被条数上限截断，可解析条目的名额不受挤占
        full: list = []
        for i in range(cg.RECENT_RUNS_CAP):
            cg._push_recent(full, {"time": _iso(E1 + i * 60)})
        cg._push_recent(full, {"time": "not-a-ts"})
        assert len(full) == cg.RECENT_RUNS_CAP
        assert all(e["time"] != "not-a-ts" for e in full)
        assert full[0]["time"] == _iso(E1 + (cg.RECENT_RUNS_CAP - 1) * 60)


# ══ 任务 1.1：节点权重与在飞语义 ═════════════════════════════════════════


class TestInFlightScenario:
    def test_cross_project_running_count(self, tmp_path):
        """Scenario「跨项目在飞聚合」：项目 A 开发 1 个 run 在飞、项目 B 开发
        2 个 run 在飞 → 开发节点 running 计数为 3 且标记在飞。"""
        pa = make_proot(tmp_path, "proj-a", {"spec-a": "testing"})
        pb = make_proot(tmp_path, "proj-b", {"spec-b": "testing", "spec-b2": "testing"})
        write_run(pa, f"impl-spec-a-{E1}", {"type": "progress"}, start_ts=_iso(E1))
        write_run(pb, f"impl-spec-b-{E1}", {"type": "progress"}, start_ts=_iso(E1))
        write_run(pb, f"impl-spec-b2-{E2}", {"type": "progress"}, start_ts=_iso(E2))
        data = aggregate_collab_graph(
            [
                {"name": "proj-a", "path": str(pa), "exists": True},
                {"name": "proj-b", "path": str(pb), "exists": True},
            ]
        )
        dev = role_of(data, "dev")
        assert dev["running"] == 3
        assert dev["in_flight"] is True
        assert data["kpis"]["running_runs"] == 3
        # 在飞 SPEC 计数：spec-a / spec-b / spec-b2 均存在活在飞 run
        assert data["kpis"]["running_specs"] == 3
        # 未受影响的角色保持零在飞
        assert role_of(data, "test")["in_flight"] is False


# ══ 任务 1.2：归档 SPEC 口径 ═════════════════════════════════════════════


class TestArchivedScenario:
    def test_archived_specs_kpi_only(self, tmp_path):
        """Scenario「归档 SPEC 只进 KPI 不进图」：5 个已归档 + 3 个活跃 →
        spec_count=8、archived_excluded=5，图谱边与权重仅来自活跃 SPEC。"""
        pa = make_proot(
            tmp_path,
            "proj-a",
            {f"live-{i}": "testing" for i in range(3)},
        )
        for i in range(3):
            write_handoff_chain(pa, f"live-{i}")
        write_archive_manifest(pa, [f"arch-{i}" for i in range(5)])
        data = aggregate_collab_graph([{"name": "proj-a", "path": str(pa), "exists": True}])
        assert data["kpis"]["spec_count"] == 8
        assert data["kpis"]["active_spec_count"] == 3
        assert data["kpis"]["archived_excluded"] == 5
        assert data["archived_excluded"] == 5
        # 边与权重仅来自活跃 SPEC（每个 live spec：user→pm + pm→3 run dispatch
        # + plan→dev + dev→review = 6 条交接）
        assert edge_of(data, "plan", "dev")["weight"] == 3
        assert data["kpis"]["total_handoffs"] == 18
        # 归档 SPEC 不出现在任何下钻明细（零产物聚合）
        for r in data["roles"]:
            assert all(not e["spec"].startswith("arch-") for e in r["recent_runs"])

    def test_archived_manifest_specs_zero_derive(self, tmp_path, monkeypatch):
        """Scenario「归档项目零开销跳过」：全部 SPEC 已归档的项目不触发任何
        derive 调用（run 产物零读取），仅计入 KPI。"""
        calls: list = []

        def _spy(proot, spec, entry=None):
            calls.append(spec)
            raise AssertionError(f"archived spec must not derive: {spec}")

        pa = make_proot(tmp_path, "proj-a", {})  # 活跃零 SPEC
        write_archive_manifest(pa, ["done-1", "done-2"])
        # runs 目录残留产物（归档清理遗漏的防御性形态）：聚合也 MUST NOT 读取
        write_run(pa, f"impl-done-1-{E1}", {"type": "result"}, start_ts=_iso(E1))
        monkeypatch.setattr(cg, "derive_topology", _spy)
        data = aggregate_collab_graph([{"name": "proj-a", "path": str(pa), "exists": True}])
        assert calls == []
        assert data["kpis"]["spec_count"] == 2
        assert data["kpis"]["archived_excluded"] == 2
        assert data["edges"] == []
        assert data["kpis"]["total_runs"] == 0


# ══ 任务 1.3：边界鲁棒 ═══════════════════════════════════════════════════


class TestBoundaryScenarios:
    def test_empty_project_no_error(self, tmp_path):
        """Scenario「空项目不报错」：从未跑过任何 SPEC 的新项目正常返回，
        贡献零边零权重。"""
        pa = make_proot(tmp_path, "proj-a", {})
        data = aggregate_collab_graph([{"name": "proj-a", "path": str(pa), "exists": True}])
        assert data["kpis"]["spec_count"] == 0
        assert data["edges"] == []
        assert data["kpis"]["total_runs"] == 0
        assert len(data["roles"]) == 8
        assert data["kpis"]["total_cost_usd"] is None

    def test_project_filter_narrows(self, tmp_path):
        """Scenario「项目筛选收窄」：project=<name> 时聚合仅含该项目。"""
        pa = make_proot(tmp_path, "proj-a", {"spec-a": "testing"})
        pb = make_proot(tmp_path, "proj-b", {"spec-b": "testing"})
        write_handoff_chain(pa, "spec-a")
        write_handoff_chain(pb, "spec-b")
        projects = [
            {"name": "proj-a", "path": str(pa), "exists": True},
            {"name": "proj-b", "path": str(pb), "exists": True},
        ]
        data = aggregate_collab_graph(projects, project="proj-a")
        assert edge_of(data, "plan", "dev")["weight"] == 1
        assert data["kpis"]["spec_count"] == 1
        assert data["project"] == "proj-a"
        assert data["projects"] == ["proj-a"]
        # 全量视图不受影响
        full = aggregate_collab_graph(projects)
        assert edge_of(full, "plan", "dev")["weight"] == 2

    def test_nonexistent_and_fixture_projects_skipped(self, tmp_path):
        """不存在项目零贡献；项目集合回显仍含 exists=False 的名字由调用方
        口径决定——本函数按 exists 过滤（与 _aggregatable_projects 对齐）。"""
        pa = make_proot(tmp_path, "proj-a", {"spec-a": "testing"})
        write_handoff_chain(pa, "spec-a")
        data = aggregate_collab_graph(
            [
                {"name": "proj-a", "path": str(pa), "exists": True},
                {"name": "ghost", "path": str(tmp_path / "ghost"), "exists": False},
            ]
        )
        assert data["kpis"]["spec_count"] == 1
        assert "ghost" not in data["projects"]

    def test_unpriced_cost_is_null(self, tmp_path):
        """全部 run 不可计价（tmp 项目无计价表）→ 节点/全局成本为 null
        （与单 SPEC 拓扑 total_cost_usd 同语义，不伪装 $0.00）。"""
        pa = make_proot(tmp_path, "proj-a", {"spec-a": "testing"})
        write_handoff_chain(pa, "spec-a")
        data = aggregate_collab_graph([{"name": "proj-a", "path": str(pa), "exists": True}])
        assert role_of(data, "dev")["cost_usd"] is None
        assert data["kpis"]["total_cost_usd"] is None


# ══ 任务 2.1：只读端点（真实 DashboardHandler） ══════════════════════════


@pytest.fixture()
def graph_server_fx(tmp_path):
    """server_fx 同款：registry + 真实 DashboardHandler 的临时 HTTP 实例。"""
    from conftest import make_project

    proot = make_project(tmp_path)
    cfg = tmp_path / "dashboard.yaml"
    reg = Registry(config_path=cfg)
    reg.save(
        {
            "port": 8787,
            "projects": [{"name": "proj-a", "path": str(proot)}],
            "scan_dirs": [str(tmp_path / "scan-empty")],
        }
    )
    srv = _TestServer(
        reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static"
    )
    yield proot, srv
    srv.stop()


class TestCollabGraphEndpoint:
    def test_endpoint_aggregates_roles(self, graph_server_fx):
        proot, srv = graph_server_fx
        write_run(proot, f"impl-myspec-{E4}", {"type": "progress"}, start_ts=_iso(E4))
        status, data = srv.get("/api/overview/collab-graph")
        assert status == 200
        assert "error" not in data
        assert [r["id"] for r in data["roles"]] == list(cg.LANES)
        assert data["project"] is None
        assert data["projects"] == ["proj-a"]
        dev = role_of(data, "dev")
        assert dev["running"] == 1
        assert dev["in_flight"] is True
        assert any(
            e["project"] == "proj-a" and e["spec"] == "myspec" for e in dev["recent_runs"]
        )
        assert data["kpis"]["spec_count"] >= 1

    def test_endpoint_project_filter(self, graph_server_fx):
        proot, srv = graph_server_fx
        # make_project 预置 impl-myspec（dev 泳道）；补写 planner run 后
        # 形成 规划→开发 交接链
        write_run(proot, f"planner-myspec-{E4}", {"type": "result"}, start_ts=_iso(E4))
        status, data = srv.get("/api/overview/collab-graph?project=proj-a")
        assert status == 200
        assert data["project"] == "proj-a"
        assert edge_of(data, "pm", "plan")["weight"] == 1
        assert edge_of(data, "plan", "dev")["weight"] == 1

    def test_endpoint_unknown_project_compat_contract(self, graph_server_fx):
        """与 detail/alerts 同族兼容契约：未知项目维持 200 + {"error": ...}。"""
        _, srv = graph_server_fx
        status, data = srv.get("/api/overview/collab-graph?project=no-such")
        assert status == 200
        assert "error" in data

    def test_endpoint_etag_roundtrip(self, graph_server_fx):
        """条件请求：同源数据二连请求 200 → 304；新 run 产物翻转签名 → 200。"""
        proot, srv = graph_server_fx
        path = "/api/overview/collab-graph"
        status, headers, _ = srv.get_ex(path)
        assert status == 200
        etag = headers.get("ETag")
        assert etag
        status2, _, body2 = srv.get_ex(path, headers={"If-None-Match": etag})
        assert status2 == 304
        assert body2 == b""
        write_run(proot, f"impl-myspec-{E5}", {"type": "result"}, start_ts=_iso(E5))
        status3, _, _ = srv.get_ex(path, headers={"If-None-Match": etag})
        assert status3 == 200

    def test_aggregate_method_is_readonly(self, graph_server_fx):
        """端点只读、无副作用：重复调用结果一致（不写任何运行时状态）。"""
        proot, srv = graph_server_fx
        write_run(proot, f"impl-myspec-{E6}", {"type": "result"}, start_ts=_iso(E6))
        _, first = srv.get("/api/overview/collab-graph")
        _, second = srv.get("/api/overview/collab-graph")
        assert first == second
