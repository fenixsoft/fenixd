"""tests/test_topology_derivation.py — SPEC 协作拓扑派生表驱动单测。

覆盖 add-spec-topology-bigscreen 任务 1.1–1.6 对应 specs/topology-derivation
的全部 Scenario（正常完整图、impl-ocr 归列、未知前缀兜底、attempt 链 KPI
归并、全不可计价 null、attempt 链重试边、独立重派 handoff、多轮验证逐轮、
fast-track 自动推送终点、人工批准 approve 节点、归档骨架）+ 任务 2.1 端点
（server_fx 起真实 DashboardHandler 的同族寻址与错误契约）。
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conftest import _TestServer  # noqa: E402

from core.dashboard import data as dash_data
from core.dashboard.data.topology import derive_topology, split_attempt, stage_lane_role
from core.dashboard.registry import Registry
from core.proc_utils import find_free_port

# ── 固定时刻（避免真实时钟噪声；全部 ISO 带 tz，与 timelib 解析口径一致） ──
T_CREATED = "2026-03-01T00:00:00+00:00"
T_T1 = "2026-03-01T00:00:01Z"
T_T2 = "2026-03-01T00:00:02Z"
# run_id 内嵌 epoch（9-10 位 unix 秒；started 回退源）
E1 = 1772000000
E2 = 1772000060
E3 = 1772000120
E4 = 1772000180
E5 = 1772000240


def _iso(epoch: int) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def make_proot(tmp_path: Path, spec: str = "demo", status: str = "testing", dirname: str = "proj") -> Path:
    """最小可派生项目：STATE 条目 + 空 logs/runs 目录 + 活跃 spec 目录。"""
    proot = tmp_path / dirname
    (proot / ".fenix" / "logs").mkdir(parents=True)
    (proot / ".fenix" / "runs").mkdir(parents=True)
    (proot / "spec" / "changes" / spec).mkdir(parents=True)
    (proot / ".fenix" / "STATE.md").write_text(
        "# Fenix Project State\n\n## Specs\n\n"
        f"### {spec}\n- status: {status}\n- priority: 1\n"
        f"- created: {T_CREATED}\n- updated: {T_CREATED}\n",
        encoding="utf-8",
    )
    return proot


def write_log(proot: Path, entries: list) -> None:
    """覆写 daemon 日志（结构化 JSON 行；transitions/验证轮次/run_metrics 源）。"""
    (proot / ".fenix" / "logs" / "fenixd.log").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n",
        encoding="utf-8",
    )


def transition(spec: str, frm: str, to: str, ts: str) -> dict:
    return {
        "timestamp": ts,
        "message": f"Transition: {spec} {frm} → {to}",
        "context": {"channel": "auto", "agent_type": "pm-engine"},
    }


def verify_start(spec: str, ts: str) -> dict:
    return {"timestamp": ts, "message": f"SPEC '{spec}' 开始验证 full 模式", "context": {}}


def run_metric(base_run_id: str, duration: float, harness: str = "claude") -> dict:
    return {
        "timestamp": "2026-03-01T01:00:00Z",
        "message": "run metrics",
        "context": {
            "metric_type": "run_metrics",
            "run_id": base_run_id,
            "duration_seconds": duration,
            "harness": harness,
        },
    }


def write_run(proot: Path, run_id: str, last_event: dict, start_ts: str = "") -> None:
    """写 run 产物：start 事件（带 timestamp 作真实起点）+ 终态事件。"""
    events = [{"type": "start", "message": "start"}]
    if start_ts:
        events[0]["timestamp"] = start_ts
    events.append(last_event)
    (proot / ".fenix" / "runs" / f"{run_id}.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n",
        encoding="utf-8",
    )


def derive(proot: Path, spec: str = "demo"):
    entry = dash_data.parse_state(proot).get(spec) or dash_data.parse_archived_state(proot).get(spec)
    return derive_topology(proot, spec, entry)


def nodes_of(data, kind):
    return [n for n in data["nodes"] if n["kind"] == kind]


def run_node(data, run_id):
    hit = [n for n in data["nodes"] if n.get("run_id") == run_id]
    assert len(hit) == 1, f"run node missing: {run_id}"
    return hit[0]


def edge_set(data):
    return {(e["from"], e["to"], e["type"]) for e in data["edges"]}


# ── 纯函数：前缀归并 / 角色归列（任务 1.1 基元） ────────────────────────────


class TestAttemptSplit:
    def test_attempt_chain_suffixes(self):
        base, attempt, transient = split_attempt("impl-demo-1772000000-a2-r1")
        assert base == "impl-demo-1772000000"
        assert attempt == 2
        assert transient == 1

    def test_no_suffix_defaults(self):
        base, attempt, transient = split_attempt("impl-demo-1772000000")
        assert base == "impl-demo-1772000000"
        assert attempt == 1
        assert transient is None


class TestStageLaneRole:
    def test_impl_ocr_review_column(self):
        # Scenario「impl-ocr 归审查列」：stage=审查/修复列，role=代码审查
        assert stage_lane_role("impl-ocr") == ("review", "review", "代码审查")

    def test_seven_stage_mapping(self):
        assert stage_lane_role("spec-review")[0] == "demand"
        assert stage_lane_role("dispute-judge")[0] == "demand"
        assert stage_lane_role("planner")[0] == "plan"
        assert stage_lane_role("planner-plan")[0] == "plan"
        assert stage_lane_role("planner-judge")[0] == "plan"
        assert stage_lane_role("implementer")[0] == "dev"
        assert stage_lane_role("repair")[0] == "review"
        assert stage_lane_role("code-review")[0] == "review"
        assert stage_lane_role("code-fix")[0] == "review"
        assert stage_lane_role("tester")[0] == "test"
        assert stage_lane_role("verifier")[0] == "test"
        assert stage_lane_role("administrator")[0] == "ops"

    def test_unknown_falls_to_dev_unknown(self):
        assert stage_lane_role("agent") == ("dev", "dev", "unknown")
        assert stage_lane_role("never-seen-this") == ("dev", "dev", "unknown")


# ── 任务 1.1 正常 SPEC 派生完整图 ───────────────────────────────────────────


class TestFullGraph:
    def test_full_scenario_nodes_edges_kpis(self, tmp_path):
        # Scenario「正常 SPEC 派生完整图」：创建→评审→规划→开发→审查→验证→pushed
        proot = make_proot(tmp_path, status="pushed")
        write_log(
            proot,
            [
                transition("demo", "drafted", "ready", T_T1),
                transition("demo", "ready", "implementing", T_T2),
                transition("demo", "implemented", "testing", "2026-03-01T00:00:03Z"),
                transition("demo", "testing", "verified", "2026-03-01T00:00:04Z"),
                transition("demo", "verified", "pushed", "2026-03-01T00:00:05Z"),
                run_metric("impl-demo-1772000000", 100.0),
            ],
        )
        write_run(
            proot, f"impl-demo-{E1}", {"type": "result"}, start_ts=_iso(E1)
        )
        data = derive(proot)
        kinds = {n["id"]: n["kind"] for n in data["nodes"]}
        # 用户入口节点、PMEngine 节点、run 节点与交付终点节点齐备
        assert kinds["user"] == "user"
        assert kinds["pm"] == "pm"
        assert kinds[f"run:impl-demo-{E1}"] == "run"
        assert kinds["delivery"] == "delivery"
        # edges 表达派发与交接
        es = edge_set(data)
        assert ("pm", f"run:impl-demo-{E1}", "dispatch") in es
        assert ("user", "pm", "handoff") in es
        assert (f"run:impl-demo-{E1}", "delivery", "handoff") in es
        # kpis 五项指标齐备
        assert set(data["kpis"]) == {
            "total_duration",
            "total_cost_usd",
            "dispatched",
            "completed",
            "retried",
        }
        assert data["status"] == "pushed"
        assert data["archived"] is False
        # pushed 终点时刻取最后一条 pushed 转移
        assert data["nodes"][-1]["time"] == "2026-03-01T00:00:05Z"

    def test_node_payload_fields(self, tmp_path):
        proot = make_proot(tmp_path)
        write_log(proot, [run_metric("impl-demo-1772000000", 100.0, harness="codex")])
        write_run(
            proot,
            f"impl-demo-{E1}",
            {"type": "result", "result": "done"},
            start_ts=_iso(E1),
        )
        data = derive(proot)
        n = run_node(data, f"impl-demo-{E1}")
        assert n["stage"] == "dev"
        assert n["lane"] == "dev"
        assert n["role"] == "开发"
        assert n["status"] == "done"
        assert n["duration_seconds"] == 100.0
        assert n["harness"] == "codex"
        assert n["spec"] == "demo"
        assert "fix" not in n

    def test_fix_family_runs_badged(self, tmp_path):
        # fix 家族子 SPEC run（impl-fix-demo-<ts>）并入父 SPEC 拓扑并带 fix 标记
        proot = make_proot(tmp_path)
        write_log(
            proot,
            [
                run_metric("impl-demo-1772000000", 10.0),
                run_metric("impl-fix-demo-1772000060", 20.0),
            ],
        )
        write_run(proot, f"impl-demo-{E1}", {"type": "result"}, start_ts=_iso(E1))
        write_run(proot, f"impl-fix-demo-{E2}", {"type": "result"}, start_ts=_iso(E2))
        data = derive(proot)
        fix_node = run_node(data, f"impl-fix-demo-{E2}")
        assert fix_node["fix"] is True
        assert fix_node["spec"] == "fix-demo"
        own = run_node(data, f"impl-demo-{E1}")
        assert "fix" not in own

    def test_special_nodes_stages(self, tmp_path):
        proot = make_proot(tmp_path)
        data = derive(proot)
        user = nodes_of(data, "user")[0]
        pm = nodes_of(data, "pm")[0]
        assert user["stage"] == "demand" and user["lane"] == "user"
        assert pm["stage"] == "plan" and pm["lane"] == "pm"
        # 交付终点不单设泳道
        assert nodes_of(data, "delivery")[0]["lane"] is None


# ── 任务 1.1 未知前缀兜底 ──────────────────────────────────────────────────


class TestUnknownPrefix:
    def test_unknown_prefix_node_kept_in_dev(self, tmp_path):
        # Scenario「未知前缀不丢节点」：不带 agent 前缀的裸 run_id
        # （run_spec_part 精确归属本 spec，但前缀不可识别 → role=unknown 落开发列）
        proot = make_proot(tmp_path)
        write_run(proot, f"demo-{E1}", {"type": "result"}, start_ts=_iso(E1))
        data = derive(proot)
        n = run_node(data, f"demo-{E1}")
        assert n["stage"] == "dev"
        assert n["role"] == "unknown"
        assert n["label"] == "未知 Agent"


# ── 任务 1.2 attempt 链归并与 KPI 口径 ─────────────────────────────────────


class TestKpis:
    def test_attempt_chain_merged_count(self, tmp_path):
        # Scenario「同一派发多 attempt 归并计数」：同 base 3 个 attempt 文件
        # → dispatched 计 1、retried 计 1
        proot = make_proot(tmp_path)
        base = f"impl-demo-{E1}"
        write_run(proot, f"{base}-a1", {"type": "superseded"}, start_ts=_iso(E1))
        write_run(proot, f"{base}-a2", {"type": "superseded"}, start_ts=_iso(E1))
        write_run(proot, f"{base}-a3", {"type": "result"}, start_ts=_iso(E1))
        data = derive(proot)
        assert data["kpis"]["dispatched"] == 1
        assert data["kpis"]["retried"] == 1
        assert data["kpis"]["completed"] == 1
        # attempt 链仍逐文件成节点（retry 边连接的载体）
        assert len(nodes_of(data, "run")) == 3

    def test_dispatched_distinct_bases(self, tmp_path):
        proot = make_proot(tmp_path)
        write_run(proot, f"impl-demo-{E1}", {"type": "result"}, start_ts=_iso(E1))
        write_run(proot, f"impl-demo-{E2}", {"type": "result"}, start_ts=_iso(E2))
        write_run(proot, f"verify-demo-{E3}", {"type": "result"}, start_ts=_iso(E3))
        data = derive(proot)
        assert data["kpis"]["dispatched"] == 3
        assert data["kpis"]["completed"] == 3
        assert data["kpis"]["retried"] == 0

    def test_superseded_single_counts_retried(self, tmp_path):
        # attempt=1 但被弃置（superseded/stale）的 run 也计入 retried
        proot = make_proot(tmp_path)
        write_run(proot, f"impl-demo-{E1}", {"type": "superseded"}, start_ts=_iso(E1))
        data = derive(proot)
        assert data["kpis"]["retried"] == 1
        assert data["kpis"]["completed"] == 0

    def test_unpriced_cost_is_null(self, tmp_path):
        # Scenario「全不可计价时成本为 null」：无计价配置 → null 而非 0
        proot = make_proot(tmp_path)
        write_run(proot, f"impl-demo-{E1}", {"type": "result"}, start_ts=_iso(E1))
        data = derive(proot)
        assert data["kpis"]["total_cost_usd"] is None

    def test_total_duration_fallback_sum(self, tmp_path):
        # 非 done/pushed 状态实时求和（与 spec_detail 同口径）；done 状态读固化快照
        proot = make_proot(tmp_path, status="testing")
        write_log(proot, [run_metric("impl-demo-1772000000", 100.0)])
        write_run(proot, f"impl-demo-{E1}", {"type": "result"}, start_ts=_iso(E1))
        assert derive(proot)["kpis"]["total_duration"] == 100

        proot2 = make_proot(tmp_path, spec="demo2", status="done", dirname="proj2")
        (proot2 / ".fenix" / "STATE.md").write_text(
            "# Fenix Project State\n\n## Specs\n\n### demo2\n- status: done\n"
            "- total_duration: 777\n"
            f"- created: {T_CREATED}\n- updated: {T_CREATED}\n",
            encoding="utf-8",
        )
        write_run(proot2, f"impl-demo2-{E1}", {"type": "result"}, start_ts=_iso(E1))
        assert derive(proot2, "demo2")["kpis"]["total_duration"] == 777


# ── 任务 1.3 重试边仅连 attempt 链 ─────────────────────────────────────────


class TestRetryEdges:
    def test_attempt_chain_retry_edge(self, tmp_path):
        # Scenario「attempt 链连重试边」：同 base 两个 attempt 节点为 retry 边
        proot = make_proot(tmp_path)
        base = f"impl-demo-{E1}"
        write_run(proot, f"{base}-a1", {"type": "superseded"}, start_ts=_iso(E1))
        write_run(proot, f"{base}-a2", {"type": "result"}, start_ts=_iso(E1))
        data = derive(proot)
        a1, a2 = f"run:{base}-a1", f"run:{base}-a2"
        assert (a1, a2, "retry") in edge_set(data)

    def test_independent_redispatch_is_handoff(self, tmp_path):
        # Scenario「独立重派不连重试边」：同角色两个不同 base 的 run 串行先后
        # 出现（run1 真实耗时 10s，end ≤ run2.start）→ handoff 边，非 retry。
        # improve-spec-topology-pipeline-view 2.1：handoff 须过单一串行判定，
        # 无耗时数据时 mtime 兜底推算会把两 run 判成时间重叠 → 无边（见
        # TestSerialHandoff.overlapping_redispatch_no_edge）。
        proot = make_proot(tmp_path)
        write_log(
            proot,
            [run_metric(f"impl-demo-{E1}", 10.0), run_metric(f"impl-demo-{E2}", 5.0)],
        )
        write_run(proot, f"impl-demo-{E1}", {"type": "error"}, start_ts=_iso(E1))
        write_run(proot, f"impl-demo-{E2}", {"type": "result"}, start_ts=_iso(E2))
        data = derive(proot)
        es = edge_set(data)
        r1, r2 = f"run:impl-demo-{E1}", f"run:impl-demo-{E2}"
        assert (r1, r2, "handoff") in es
        assert (r1, r2, "retry") not in es


# ── 任务 1.4 多轮验证逐轮呈现 ──────────────────────────────────────────────


class TestVerifyRounds:
    def _two_round_fixture(self, tmp_path):
        proot = make_proot(tmp_path, status="verified")
        (proot / ".fenix" / "verify-progress" / "demo").mkdir(parents=True)
        report_ts = "2026-03-01T02:20:00Z"
        (proot / ".fenix" / "verify-progress" / "demo" / "report.json").write_text(
            json.dumps(
                {
                    "timestamp": report_ts,
                    "summary": {"total": 3, "passed": 2, "failed": 1, "warnings": 0, "errors": 0},
                    "scenarios": [],
                }
            ),
            encoding="utf-8",
        )
        write_log(
            proot,
            [
                verify_start("demo", "2026-03-01T02:00:00Z"),
                verify_start("demo", "2026-03-01T02:10:00Z"),
            ],
        )
        return proot, report_ts

    def test_two_rounds_two_nodes_last_with_stats(self, tmp_path):
        # Scenario「两轮验证出两个节点」：仅末轮含统计字段
        proot, _ = self._two_round_fixture(tmp_path)
        data = derive(proot)
        vnodes = nodes_of(data, "verify")
        assert [n["id"] for n in vnodes] == ["verify:1", "verify:2"]
        first, last = vnodes
        # 历史轮仅时长，无任何统计字段（MUST NOT 伪造）
        assert first["duration_seconds"] == 600
        for k in ("total", "passed", "failed", "warnings", "errors"):
            assert k not in first
        # 末轮与现存 report.json 配对：统计 + 时长（报告完成时刻为终点）
        assert last["total"] == 3
        assert last["passed"] == 2
        assert last["failed"] == 1
        assert last["duration_seconds"] == 600

    def test_report_missing_no_stats(self, tmp_path):
        # report.json 缺失：逐轮节点仅时长，不伪造统计
        proot = make_proot(tmp_path)
        write_log(
            proot,
            [
                verify_start("demo", "2026-03-01T02:00:00Z"),
                verify_start("demo", "2026-03-01T02:10:00Z"),
            ],
        )
        data = derive(proot)
        vnodes = nodes_of(data, "verify")
        assert len(vnodes) == 2
        assert all("total" not in n for n in vnodes)
        assert vnodes[0]["duration_seconds"] == 600

    def test_stale_report_not_paired(self, tmp_path):
        # 报告时刻早于末轮开始（上轮残留/在飞轮次）：末轮不挂统计（不伪造）
        proot = make_proot(tmp_path)
        (proot / ".fenix" / "verify-progress" / "demo").mkdir(parents=True)
        (proot / ".fenix" / "verify-progress" / "demo" / "report.json").write_text(
            json.dumps({"timestamp": "2026-03-01T01:00:00Z", "summary": {"total": 9}}),
            encoding="utf-8",
        )
        write_log(
            proot,
            [
                verify_start("demo", "2026-03-01T02:00:00Z"),
                verify_start("demo", "2026-03-01T02:10:00Z"),
            ],
        )
        data = derive(proot)
        vnodes = nodes_of(data, "verify")
        assert len(vnodes) == 2
        assert all("total" not in n for n in vnodes)


# ── 任务 1.5 交付终点自适应 ────────────────────────────────────────────────


class TestDeliveryEndpoint:
    def test_fasttrack_auto_delivery(self, tmp_path):
        # Scenario「fast-track 不虚构人工批准」：无持久批准留痕 → 自动推送终点
        proot = make_proot(tmp_path, status="pushed")
        write_log(
            proot,
            [
                transition("demo", "done", "pushed", "2026-03-01T00:00:09Z"),
            ],
        )
        data = derive(proot)
        endpoints = nodes_of(data, "approve")
        assert endpoints == []
        delivery = nodes_of(data, "delivery")
        assert len(delivery) == 1
        assert delivery[0]["label"] == "自动推送"
        assert delivery[0]["time"] == "2026-03-01T00:00:09Z"

    def test_persistent_approval_produces_approve_node(self, tmp_path):
        # Scenario「人工批准出 approve 节点」：存在持久批准留痕 → kind=approve
        # 且含批准时间；入边为 approve 型
        proot = make_proot(tmp_path, status="pushed")
        write_run(proot, f"impl-demo-{E1}", {"type": "result"}, start_ts=_iso(E1))
        approve_ts = "2026-03-01T03:00:00Z"
        (proot / "spec" / "changes" / "demo" / "approve-push-record.json").write_text(
            json.dumps({"time": approve_ts}), encoding="utf-8"
        )
        data = derive(proot)
        approves = nodes_of(data, "approve")
        assert len(approves) == 1
        assert approves[0]["time"] == approve_ts
        assert nodes_of(data, "delivery") == []
        assert (f"run:impl-demo-{E1}", "delivery", "approve") in edge_set(data)


# ── 任务 1.6 归档降级骨架 ──────────────────────────────────────────────────


class TestArchivedSkeleton:
    def test_archived_spec_skeleton(self, tmp_path):
        # Scenario「归档 SPEC 返回骨架」：run 产物已随 archive_spec_runs 清理
        # → archived: true、run 节点为空、状态转移与运维事件保留、不报错
        proot = make_proot(tmp_path)
        write_log(
            proot,
            [
                transition("demo", "drafted", "ready", T_T1),
                transition("demo", "verified", "pushed", T_T2),
            ],
        )
        # 归档：活跃目录迁出 + 条目迁入归档清单 + run 产物清理（零 run 文件）
        import shutil

        shutil.rmtree(proot / "spec" / "changes" / "demo")
        (proot / ".fenix" / "STATE.md").write_text(
            "# Fenix Project State\n\n## Specs\n", encoding="utf-8"
        )
        (proot / ".fenix" / "STATE.archive.md").write_text(
            "# Fenix Project State\n\n## Specs\n\n"
            f"### demo\n- status: pushed\n- priority: 1\n- created: {T_CREATED}\n",
            encoding="utf-8",
        )
        data = derive(proot)
        assert data["archived"] is True
        assert data["status"] == "pushed"
        assert nodes_of(data, "run") == []
        # 状态骨架（PMEngine 状态转移）保留
        assert len(data["transitions"]) == 2
        assert data["transitions"][0]["from"] == "drafted"
        # 端点图仍完整：特殊节点与终点在位、不断链
        kinds = [n["kind"] for n in data["nodes"]]
        assert "user" in kinds and "pm" in kinds and "delivery" in kinds
        assert ("pm", "delivery", "handoff") in edge_set(data)

    def test_archived_entry_from_manifest(self, tmp_path):
        proot = make_proot(tmp_path)
        import shutil

        shutil.rmtree(proot / "spec" / "changes" / "demo")
        (proot / ".fenix" / "STATE.archive.md").write_text(
            "# Fenix Project State\n\n## Specs\n\n"
            f"### demo\n- status: done\n- created: {T_CREATED}\n",
            encoding="utf-8",
        )
        data = derive(proot)
        assert data["archived"] is True


# ── improve-spec-topology-pipeline-view 2.3：handoff 单一串行判定 ────────────


class TestSerialHandoff:
    """specs/topology-bigscreen-ui「并行无伪串行边」Requirement。

    画 handoff 边当且仅当 prev.end ≤ cur.start 且 prev.start < cur.start
    （终点缺失取 start）；时间重叠或同刻启动（含双零时长退化）一律跳过。
    """

    def test_same_instant_start_no_handoff_edge(self, tmp_path):
        # Scenario「同刻启动节点间无 handoff 边」：implementer 与 planner-plan
        # 同刻启动（实测样本 2026-10-25T14:32:58Z）→ 派生边中不存在两 run 间
        # 的 handoff 边（双向均无）
        proot = make_proot(tmp_path)
        same_ts = _iso(E1)
        write_run(proot, f"planner-plan-demo-{E1}", {"type": "result"}, start_ts=same_ts)
        write_run(proot, f"impl-demo-{E1}", {"type": "result"}, start_ts=same_ts)
        data = derive(proot)
        es = edge_set(data)
        r1, r2 = f"run:planner-plan-demo-{E1}", f"run:impl-demo-{E1}"
        assert (r1, r2, "handoff") not in es
        assert (r2, r1, "handoff") not in es
        # dispatch 边不受影响（双 run 各自自 pm 派发）
        assert ("pm", r1, "dispatch") in es
        assert ("pm", r2, "dispatch") in es

    def test_overlapping_runs_no_handoff_edge(self, tmp_path):
        # 时间重叠（prev.end > cur.start）一律无边：run1 真实耗时 100s，
        # run2 在 run1.start + 60s 启动 → 重叠 40s → 不画
        proot = make_proot(tmp_path)
        write_log(
            proot,
            [run_metric(f"impl-demo-{E1}", 100.0), run_metric(f"planner-plan-demo-{E2}", 5.0)],
        )
        write_run(proot, f"impl-demo-{E1}", {"type": "result"}, start_ts=_iso(E1))
        write_run(proot, f"planner-plan-demo-{E2}", {"type": "result"}, start_ts=_iso(E2))
        data = derive(proot)
        es = edge_set(data)
        r1, r2 = f"run:impl-demo-{E1}", f"run:planner-plan-demo-{E2}"
        assert (r1, r2, "handoff") not in es

    def test_serial_judge_chain_keeps_handoff(self, tmp_path):
        # Scenario「串行节点保留 handoff 边」：3 轮 planner-judge 依次执行
        # （各 30s，间隔 60s）→ 相邻两轮之间保留 handoff 边
        proot = make_proot(tmp_path)
        epochs = [E1, E2, E3]
        metrics = [run_metric(f"planner-judge-demo-{e}", 30.0) for e in epochs]
        write_log(proot, metrics)
        for e in epochs:
            write_run(proot, f"planner-judge-demo-{e}", {"type": "result"}, start_ts=_iso(e))
        data = derive(proot)
        es = edge_set(data)
        r1, r2, r3 = (f"run:planner-judge-demo-{e}" for e in epochs)
        assert (r1, r2, "handoff") in es
        assert (r2, r3, "handoff") in es

    def test_serial_adjacent_end_equals_start_keeps_handoff(self, tmp_path):
        # 串行贴邻（prev.end == cur.start 且起点严格更早）照画
        proot = make_proot(tmp_path)
        write_log(
            proot,
            [run_metric(f"impl-demo-{E1}", 60.0), run_metric(f"verify-demo-{E2}", 5.0)],
        )
        write_run(proot, f"impl-demo-{E1}", {"type": "result"}, start_ts=_iso(E1))
        write_run(proot, f"verify-demo-{E2}", {"type": "result"}, start_ts=_iso(E2))
        data = derive(proot)
        assert (
            f"run:impl-demo-{E1}",
            f"run:verify-demo-{E2}",
            "handoff",
        ) in edge_set(data)

    def test_attempt_chain_retry_edges_unaffected(self, tmp_path):
        # attempt 链 retry 边不受串行判定影响：同 base 多 attempt 同刻启动，
        # 相邻段仍连 retry 边（非 handoff）
        proot = make_proot(tmp_path)
        base = f"impl-demo-{E1}"
        write_run(proot, f"{base}-a1", {"type": "superseded"}, start_ts=_iso(E1))
        write_run(proot, f"{base}-a2", {"type": "result"}, start_ts=_iso(E1))
        data = derive(proot)
        es = edge_set(data)
        a1, a2 = f"run:{base}-a1", f"run:{base}-a2"
        assert (a1, a2, "retry") in es
        assert (a1, a2, "handoff") not in es

    def test_overlapping_redispatch_no_edge_without_metrics(self, tmp_path):
        # 无耗时数据（run_metrics 缺失）时 mtime 兜底推算耗时远超下一 run
        # 起点 → 按重叠判定无边（不画伪串行边，宁缺勿假）
        proot = make_proot(tmp_path)
        write_run(proot, f"impl-demo-{E1}", {"type": "error"}, start_ts=_iso(E1))
        write_run(proot, f"impl-demo-{E2}", {"type": "result"}, start_ts=_iso(E2))
        data = derive(proot)
        assert (
            f"run:impl-demo-{E1}",
            f"run:impl-demo-{E2}",
            "handoff",
        ) not in edge_set(data)


# ── improve-spec-topology-pipeline-view 2.3：dispatch 归位锚点 ───────────────


class TestDispatchAnchor:
    """派生层为 run 首节点计算可选字段 dispatch_anchor（design D5）。

    started 落在 transitions 相邻转移时刻区间 [t_i, t_{i+1}) → tr:<i+1>；
    无法定位时不下发该字段（前端回退 pm 主节点）；既有 edges 端点不改写。
    """

    def _proot_with_transitions(self, tmp_path, status="testing") -> Path:
        proot = make_proot(tmp_path, status=status)
        write_log(
            proot,
            [
                transition("demo", "drafted", "ready", "2026-03-01T00:01:00Z"),
                transition("demo", "ready", "implementing", "2026-03-01T00:02:00Z"),
                transition("demo", "implementing", "testing", "2026-03-01T00:03:00Z"),
            ],
        )
        return proot

    def test_anchor_for_started_between_transitions(self, tmp_path):
        # started 落在 [t_1, t_2)（第 2、3 条转移之间）→ tr:2
        proot = self._proot_with_transitions(tmp_path)
        write_run(
            proot, f"impl-demo-{E1}", {"type": "result"},
            start_ts="2026-03-01T00:02:30Z",
        )
        data = derive(proot)
        n = run_node(data, f"impl-demo-{E1}")
        assert n["dispatch_anchor"] == "tr:2"
        # 既有 edges 端点不改写（前端按 anchor 归位渲染，泳道不受影响）
        assert ("pm", f"run:impl-demo-{E1}", "dispatch") in edge_set(data)

    def test_anchor_first_interval(self, tmp_path):
        # started 落在 [t_0, t_1) → tr:1
        proot = self._proot_with_transitions(tmp_path)
        write_run(
            proot, f"impl-demo-{E1}", {"type": "result"},
            start_ts="2026-03-01T00:01:30Z",
        )
        assert run_node(derive(proot), f"impl-demo-{E1}")["dispatch_anchor"] == "tr:1"

    def test_anchor_at_transition_time_inclusive_left(self, tmp_path):
        # started 恰为转移时刻（区间左闭）：00:02:00 ∈ [t_1, t_2) → tr:2
        proot = self._proot_with_transitions(tmp_path)
        write_run(
            proot, f"impl-demo-{E1}", {"type": "result"},
            start_ts="2026-03-01T00:02:00Z",
        )
        assert run_node(derive(proot), f"impl-demo-{E1}")["dispatch_anchor"] == "tr:2"

    def test_no_anchor_before_first_transition(self, tmp_path):
        # started 早于首转移：不在任何相邻区间 → 字段不下发
        proot = self._proot_with_transitions(tmp_path)
        write_run(
            proot, f"impl-demo-{E1}", {"type": "result"},
            start_ts="2026-03-01T00:00:30Z",
        )
        assert "dispatch_anchor" not in run_node(derive(proot), f"impl-demo-{E1}")

    def test_no_anchor_at_or_after_last_transition(self, tmp_path):
        # started 恰为末转移时刻 / 之后：无右端点闭区间 → 字段不下发
        proot = self._proot_with_transitions(tmp_path)
        write_run(
            proot, f"impl-demo-{E1}", {"type": "result"},
            start_ts="2026-03-01T00:03:00Z",
        )
        write_run(
            proot, f"verify-demo-{E2}", {"type": "result"},
            start_ts="2026-03-01T00:03:30Z",
        )
        data = derive(proot)
        assert "dispatch_anchor" not in run_node(data, f"impl-demo-{E1}")
        assert "dispatch_anchor" not in run_node(data, f"verify-demo-{E2}")

    def test_no_anchor_without_transitions(self, tmp_path):
        # 无 transitions（日志窗口无转移行）：字段不下发（前端回退 pm 主节点）
        proot = make_proot(tmp_path)
        write_run(proot, f"impl-demo-{E1}", {"type": "result"}, start_ts=_iso(E1))
        data = derive(proot)
        assert data["transitions"] == []
        assert "dispatch_anchor" not in run_node(data, f"impl-demo-{E1}")

    def test_anchor_only_on_first_node_of_base_group(self, tmp_path):
        # 仅 run 首节点（attempt 链 a1）携带 anchor，后续 attempt 节点不携带
        proot = self._proot_with_transitions(tmp_path)
        base = f"impl-demo-{E1}"
        write_run(proot, f"{base}-a1", {"type": "superseded"}, start_ts="2026-03-01T00:02:30Z")
        write_run(proot, f"{base}-a2", {"type": "result"}, start_ts="2026-03-01T00:02:40Z")
        data = derive(proot)
        assert run_node(data, f"{base}-a1")["dispatch_anchor"] == "tr:2"
        assert "dispatch_anchor" not in run_node(data, f"{base}-a2")





@pytest.fixture()
def topo_server_fx(tmp_path):
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


# ── improve-spec-topology-pipeline-view 4.1：端到端派生断言 ──────────────────


class TestEndToEndFieldSample:
    """临时目录 fixture 复刻实测样本形态（add-collab-graph-bigscreen）：

    首行巨型行日志 + spec-review uuid 形态 run_id 产物 + 转移日志行 +
    同刻启动的 impl/planner-plan。断言四个集成结果：spec-review 节点恢复
    （stage=demand）、transitions 非空（巨型行不再吞掉锚定窗口）、不存在
    impl↔planner-plan 伪 handoff 边、run 首节点带 dispatch_anchor。
    """

    def _field_sample_proot(self, tmp_path) -> Path:
        proot = make_proot(tmp_path, status="implementing", dirname="proj-field")
        log = proot / ".fenix" / "logs" / "fenixd.log"
        # 首行 6.6MB 巨型行（admin_monitor 信号形态，时刻早于 SPEC created）
        giant = json.dumps(
            {
                "timestamp": "2026-02-28T10:00:00Z",
                "level": "INFO",
                "component": "admin_monitor",
                "message": "signal",
                "context": {"blob": "x" * (6600 * 1024)},
            },
            ensure_ascii=False,
        )
        # 转移日志行（created 锚点之后，实测 9 条形态抽样为 3 条）
        events = [
            transition("demo", "drafted", "reviewing", "2026-03-01T00:00:05Z"),
            transition("demo", "reviewing", "ready", "2026-03-01T00:00:10Z"),
            transition("demo", "ready", "implementing", "2026-03-01T00:00:15Z"),
        ]
        log.write_text(
            giant + "\n" + "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n",
            encoding="utf-8",
        )
        # spec-review uuid 形态 run_id 产物（spec_review.py 恒插入 6hex 段）
        write_run(
            proot,
            "spec-review-demo-8e869d-1792938300",
            {"type": "result"},
            start_ts="2026-03-01T00:00:20Z",
        )
        # 生成场景 ∥ 开发同刻启动（实测 2026-10-25T14:32:58Z 形态）
        write_run(
            proot, f"planner-plan-demo-{E1}", {"type": "result"},
            start_ts="2026-03-01T00:00:12Z",
        )
        write_run(
            proot, f"impl-demo-{E1}", {"type": "result"},
            start_ts="2026-03-01T00:00:12Z",
        )
        return proot

    def test_field_sample_full_derivation(self, tmp_path):
        proot = self._field_sample_proot(tmp_path)
        data = derive(proot)

        # ① spec-review 节点恢复（uuid 段剥除 → family 全等命中、stage=demand）
        sr = [
            n for n in data["nodes"]
            if n.get("agent_type") == "spec-review" and n["kind"] == "run"
        ]
        assert len(sr) == 1, "spec-review run 节点 MUST NOT 因 uuid 段丢失"
        assert sr[0]["stage"] == "demand"
        assert sr[0]["spec"] == "demo"
        assert sr[0]["run_id"] == "spec-review-demo-8e869d-1792938300"
        # 与其他 run 节点同构（attempt/时长/harness 字段在位）
        assert sr[0]["attempt"] == 1
        assert "duration_seconds" in sr[0]
        assert "harness" in sr[0]

        # ② transitions 非空（首行巨型行不再吞掉 created 锚定窗口）
        assert len(data["transitions"]) == 3
        assert [t["to"] for t in data["transitions"]] == ["reviewing", "ready", "implementing"]

        # ③ 同刻启动的 impl/planner-plan 之间无伪 handoff 边（双向均无）
        es = edge_set(data)
        r_impl, r_plan = f"run:impl-demo-{E1}", f"run:planner-plan-demo-{E1}"
        assert (r_impl, r_plan, "handoff") not in es
        assert (r_plan, r_impl, "handoff") not in es

        # ④ run 首节点带 dispatch_anchor（started 落在 [t_1, t_2) → tr:2）
        assert run_node(data, f"impl-demo-{E1}")["dispatch_anchor"] == "tr:2"
        assert run_node(data, f"planner-plan-demo-{E1}")["dispatch_anchor"] == "tr:2"
        # spec-review run started 晚于末转移 → 无归位区间 → 字段不下发
        assert "dispatch_anchor" not in sr[0]
        # 既有 edges 端点不改写：dispatch 边仍自 pm 出发
        assert ("pm", r_impl, "dispatch") in es
        assert ("pm", "run:spec-review-demo-8e869d-1792938300", "dispatch") in es


# ── 任务 2.1 只读端点（真实 DashboardHandler） ─────────────────────────────


class TestTopologyEndpoint:
    def test_endpoint_returns_topology(self, topo_server_fx):
        proot, srv = topo_server_fx
        write_run(proot, f"impl-myspec-{E1}", {"type": "result"}, start_ts=_iso(E1))
        status, data = srv.get("/api/specs/myspec/topology?project=proj-a")
        assert status == 200
        assert "error" not in data
        assert data["spec"] == "myspec"
        assert data["project"] == "proj-a"
        assert set(data["kpis"]) == {
            "total_duration",
            "total_cost_usd",
            "dispatched",
            "completed",
            "retried",
        }
        assert any(n["kind"] == "user" for n in data["nodes"])
        assert any(n["kind"] == "pm" for n in data["nodes"])
        assert any(n["kind"] == "delivery" for n in data["nodes"])
        # make_project 预置 impl-myspec-1780000000 / verify-myspec-1780001000 两个
        # base + 本用例新写 1 个 → dispatched = 3（attempt 归并按 base 计数）
        assert data["kpis"]["dispatched"] == 3

    def test_endpoint_archived_spec(self, topo_server_fx):
        # 归档 SPEC 可调用（读侧不区分数据获取路径），返回骨架不报错。
        # 归档语义 = 活跃目录迁出 + 条目迁清单 + run 产物随 archive_spec_runs 清理
        proot, srv = topo_server_fx
        import shutil

        shutil.rmtree(proot / "spec" / "changes" / "myspec")
        for p in (proot / ".fenix" / "runs").glob("*.jsonl"):
            p.unlink()
        (proot / ".fenix" / "STATE.archive.md").write_text(
            "# Fenix Project State\n\n## Specs\n\n"
            "### myspec\n- status: done\n- created: 2026-01-01T00:00:00+00:00\n",
            encoding="utf-8",
        )
        status, data = srv.get("/api/specs/myspec/topology?project=proj-a")
        assert status == 200
        assert data["archived"] is True
        assert [n for n in data["nodes"] if n["kind"] == "run"] == []

    def test_endpoint_unknown_spec_compat_contract(self, topo_server_fx):
        # 与 detail 同族兼容契约：未知 spec 维持 200 + {"error": ...}
        _, srv = topo_server_fx
        status, data = srv.get("/api/specs/no-such-spec/topology?project=proj-a")
        assert status == 200
        assert "error" in data

    def test_endpoint_etag_roundtrip(self, topo_server_fx):
        # 条目第 4 位签名生效：同源数据二连请求，200 → 304
        proot, srv = topo_server_fx
        path = "/api/specs/myspec/topology?project=proj-a"
        status, headers, body = srv.get_ex(path)
        assert status == 200
        etag = headers.get("ETag")
        assert etag
        status2, headers2, body2 = srv.get_ex(path, headers={"If-None-Match": etag})
        assert status2 == 304
        assert body2 == b""
        # 数据源变化（新 run 产物）翻转签名 → 200 新图
        write_run(proot, f"impl-myspec-{E1}", {"type": "result"}, start_ts=_iso(E1))
        status3, _, _ = srv.get_ex(path, headers={"If-None-Match": etag})
        assert status3 == 200
