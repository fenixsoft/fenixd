"""tests/test_command_center_aggregation.py — 指挥中心聚合层表驱动单测。

覆盖 add-command-center specs/command-center-aggregation 全部 Scenario：

- 任务 1.3：四指标混合派生（含出窗归档不计、跨源去重）、分母零 null、
  花名册卡 + 未登记 lane「其他」分区、working/idle 状态、edges 两次请求恒等；
- 任务 2.5：五列归组 + running 附加 + 项目筛选回显、台账排序 + trigger=null、
  收件箱只含未决带快照条目且 choices 与快照逐字段一致 + 排序；
- 任务 2.4：五端点注册（server_fx 起真实 DashboardHandler）与错误契约。

聚合入口签名沿用 aggregate_*(registry_projects, project=None) 注入模式，
``now`` 关键字参数冻结当前时刻（2026-10-25T12:00:00Z）使归档日期前缀
``2026-10-24`` 落窗（fixture 产物 mtime 同步用 os.utime 钉进窗口）。
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conftest import _TestServer  # noqa: E402

from core.dashboard.data import command_center as cc  # noqa: E402
from core.dashboard.registry import Registry  # noqa: E402

# ── 冻结时刻（7×24h UTC 滚动窗锚点）：2026-10-25T12:00:00Z ────────────────
NOW = int(datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc).timestamp())
WIN_START = NOW - 7 * 86400  # 2026-10-18T12:00Z
T_CREATED = "2026-03-01T00:00:00+00:00"

BASE_USAGE = {
    "input_tokens": 1_000_000,
    "output_tokens": 0,
    "cache_read_input_tokens": 0,
    "cache_creation_input_tokens": 0,
}

# ── fixture 构造助手 ──────────────────────────────────────────────────────


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


@pytest.fixture(autouse=True)
def _isolated_user_config(tmp_path, monkeypatch):
    """用户级配置隔离：read_effective_config/计价不受宿主 ~/.fenix 污染。"""
    user_dir = tmp_path / "user-config"
    user_dir.mkdir()
    monkeypatch.setattr("core.config.USER_CONFIG_DIR", user_dir)
    import core.dashboard.data as dd

    monkeypatch.setattr(dd, "USER_CONFIG_PATH", user_dir / "config.yaml")


def make_proj(tmp_path: Path, name: str, specs: dict | None = None) -> Path:
    """最小可聚合项目：logs/runs 目录 + 活跃 spec 目录 + STATE 条目。"""
    proot = tmp_path / name
    (proot / ".fenix" / "logs").mkdir(parents=True)
    (proot / ".fenix" / "runs").mkdir(parents=True)
    for spec in (specs or {}):
        (proot / "spec" / "changes" / spec).mkdir(parents=True, exist_ok=True)
    body = "# Fenix Project State\n\n## Specs\n"
    for spec, status in (specs or {}).items():
        body += (
            f"\n### {spec}\n- status: {status}\n- priority: 1\n"
            f"- created: {T_CREATED}\n- updated: {T_CREATED}\n"
        )
    (proot / ".fenix" / "STATE.md").write_text(body, encoding="utf-8")
    return proot


def write_run_file(proot: Path, stem: str, events: list, mtime_epoch: int | None) -> Path:
    """写 run 产物；mtime_epoch 非空时用 os.utime 钉 mtime（窗口 mtime 粗筛
    入窗的前提）。在飞 run 传 None 保留真实新 mtime——stale 兜底
    （_RUN_STALE_SECONDS=1800）按**真实墙钟**判停更，钉在冻结时间线上的
    mtime 会被判 stale 而失去在飞语义。"""
    path = proot / ".fenix" / "runs" / f"{stem}.jsonl"
    path.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n",
        encoding="utf-8",
    )
    if mtime_epoch is not None:
        os.utime(path, (mtime_epoch, mtime_epoch))
    return path


def priced_run(
    proot: Path,
    stem: str,
    outcome: str,
    start_epoch: int,
    usage: dict | None = BASE_USAGE,
) -> Path:
    """写一条带 provider_marker + result.usage 的 run（成本口径 1.0/条）。"""
    events = [
        {"type": "start", "message": "start", "timestamp": _iso(start_epoch)},
        {"type": "provider_marker", "model": "m-1", "provider": "prov-a"},
    ]
    if outcome == "done":
        events.append({"type": "result", "result": "ok", "usage": usage})
    elif outcome == "error":
        events.append({"type": "error", "error": "boom"})
    else:  # 在飞（progress 非终态 → classify_run 判 running）
        events.append({"type": "progress"})
        # 在飞产物 mtime 必须新鲜（见 write_run_file docstring）
        return write_run_file(proot, stem, events, mtime_epoch=None)
    return write_run_file(proot, stem, events, mtime_epoch=start_epoch + 60)


def enable_billing(proot: Path) -> None:
    """写项目级 config.yaml：prov-a 计价卡片（input 1.0/M → 1M tokens=$1.0）。"""
    (proot / ".fenix" / "config.yaml").write_text(
        "llm:\n"
        "  providers:\n"
        "    - name: prov-a\n"
        "      baseurl: https://prov-a.invalid/v1\n"
        "      apikey: k-test\n"
        "      model: m-1\n"
        "      billing:\n"
        "        enabled: true\n"
        "        prices:\n"
        "          - model: m-1\n"
        "            input_per_million: 1.0\n"
        "            output_per_million: 1.0\n"
        "            cache_read_per_million: 0.0\n"
        "            cache_creation_per_million: 0.0\n",
        encoding="utf-8",
    )


def write_alerts(proot: Path, records: list) -> None:
    (proot / ".fenix" / "admin_alerts.json").write_text(
        json.dumps(records, ensure_ascii=False), encoding="utf-8"
    )


def projects_of(*proots: Path) -> list:
    return [
        {"name": p.name, "path": str(p), "exists": True} for p in proots
    ]


# ── KPI 四指标（任务 1.3 Scenario 1/2） ───────────────────────────────────


class TestKpiAggregation:
    def test_kpi_mixed_derivation(self, tmp_path):
        """四指标在混合 fixture 上正确派生（出窗归档不计、跨源去重、网关配置态）。"""
        proot = make_proj(tmp_path, "proj-a", specs={"y": "pushed"})
        (proot / "spec" / "archive" / "2026-10-24-x").mkdir(parents=True)
        (proot / "spec" / "archive" / "2026-09-01-old").mkdir(parents=True)
        enable_billing(proot)
        # 8 done（计价 1.25/条，result.usage 为成本口径唯一来源）+ 2 error
        # （error 无 result.usage → 不计价不贡献）→ 成本合计 10.0
        done_usage = {
            "input_tokens": 1_250_000, "output_tokens": 0,
            "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
        }
        for i in range(8):
            priced_run(proot, f"impl-alpha-{WIN_START + 3600 + i}", "done",
                       WIN_START + 3600 + i, usage=done_usage)
        for i in range(2):
            priced_run(proot, f"impl-alpha-{WIN_START + 5000 + i}", "error",
                       WIN_START + 5000 + i, usage=None)
        write_alerts(
            proot,
            [
                {  # 人工处置（窗内 handled_at）→ 计数
                    "id": "e1", "kind": "escalation", "severity": "major",
                    "created": _iso(NOW - 200), "handled": True,
                    "handled_at": _iso(NOW - 100),
                },
                {
                    "id": "e2", "kind": "escalation", "severity": "minor",
                    "created": _iso(NOW - 300), "handled": True,
                    "handled_at": _iso(NOW - 150),
                },
                {  # auto-self-heal 收口 SIGNAL → get_resolved_alerts 口径内、
                    # kind 剔除后不计人工介入
                    "id": "s1", "kind": "signal", "severity": "minor",
                    "created": _iso(NOW - 300), "handled": True,
                    "handled_by": "auto-self-heal", "handled_at": _iso(NOW - 100),
                },
                {  # 出窗人工处置 → 不计
                    "id": "e3", "kind": "escalation", "severity": "minor",
                    "created": _iso(NOW - 40 * 86400), "handled": True,
                    "handled_at": _iso(NOW - 40 * 86400),
                },
            ],
        )

        data = cc.aggregate_kpi(projects_of(proot), now=NOW)
        assert data["project"] is None
        assert data["projects"] == ["proj-a"]
        # 归档 1（2026-10-24-x；2026-09-01-old 出窗不计）+ pushed 1（y），
        # 跨两源按 SPEC 名去重后无重名
        assert data["delivered_specs_7d"] == 2
        assert data["run_success_rate_7d"] == 0.8  # 8 done / (8+2)
        assert data["human_intervention_rate_7d"] == 0.2  # 2 / 10 终态
        assert data["cost_per_spec_7d"] == pytest.approx(10.0 / 2)
        # 网关为配置态派生（fixture 计价卡片四要素齐备）；全程零网络探测
        assert data["gateway_health"] == {"configured": True, "providers": 1}

    def test_kpi_zero_denominators_null(self, tmp_path):
        """窗内无终态 run（空项目）：三比率 null、delivered=0。"""
        proot = make_proj(tmp_path, "proj-empty", specs={})
        data = cc.aggregate_kpi(projects_of(proot), now=NOW)
        assert data["delivered_specs_7d"] == 0
        assert data["human_intervention_rate_7d"] is None
        assert data["run_success_rate_7d"] is None
        assert data["cost_per_spec_7d"] is None

    def test_kpi_project_scoped(self, tmp_path):
        """project 筛选只聚合同名项目，projects 回显全集。"""
        pa = make_proj(tmp_path, "proj-a", specs={})
        pb = make_proj(tmp_path, "proj-b", specs={})
        enable_billing(pa)
        priced_run(pa, "impl-alpha-1", "done", WIN_START + 100)
        data = cc.aggregate_kpi(projects_of(pa, pb), project="proj-a", now=NOW)
        assert data["project"] == "proj-a"
        assert data["projects"] == ["proj-a", "proj-b"]
        assert data["run_success_rate_7d"] == 1.0


# ── 组织网格（任务 1.3 Scenario 3/4） ─────────────────────────────────────


class TestOrgAggregation:
    def build_observed(self, tmp_path):
        """implementer 观测：今日 2 run、7d 成功率 0.75、成本 1.2、14 日活动
        非全零、有在飞 run；另有花名册外 lane（verify- 前缀 → verifier）。"""
        proot = make_proj(tmp_path, "proj-b", specs={"demo": "implementing"})
        enable_billing(proot)
        # 今日（UTC 日界 00:00Z 后）：1 done（计价 1.2）+ 1 在飞
        priced_run(proot, f"impl-demo-{NOW - 3600}", "done", NOW - 3600, usage={
            "input_tokens": 1_200_000, "output_tokens": 0,
            "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
        })
        priced_run(proot, f"impl-demo-{NOW - 600}", "progress", NOW - 600, usage=None)
        # 昨日（仍在 7 日窗内）：2 done + 1 error → 7 日终态 4、成功 3（0.75）
        priced_run(proot, f"impl-demo-{NOW - 90000}", "done", NOW - 90000, usage=None)
        priced_run(proot, f"impl-demo-{NOW - 91800}", "done", NOW - 91800, usage=None)
        priced_run(proot, f"impl-demo-{NOW - 93600}", "error", NOW - 93600, usage=None)
        # verifier（2026-10-28 重划后为交付线编制内 lane）
        priced_run(proot, f"verify-demo-{NOW - 4000}", "done", NOW - 4000, usage=None)
        # 观测 lane 归并（LANE_ALIASES）：dispute-judge→judge、repair→code-fix
        priced_run(proot, f"dispute-judge-demo-{NOW - 3000}", "done", NOW - 3000, usage=None)
        priced_run(proot, f"repair-demo-{NOW - 2500}", "done", NOW - 2500, usage=None)
        # 花名册外观测 lane（未知前缀 → 泛型 "agent"，落「其他」分区）
        priced_run(proot, f"mystery-demo-{NOW - 3500}", "done", NOW - 3500, usage=None)
        return proot

    def card_of(self, data, lane):
        hit = [c for z in data["zones"] for c in z["cards"] if c["lane"] == lane]
        assert len(hit) == 1, f"lane card missing: {lane}"
        return hit[0]

    def zone_of(self, data, zone):
        hit = [z for z in data["zones"] if z["zone"] == zone]
        assert len(hit) == 1, f"zone missing: {zone}"
        return hit[0]

    def test_roster_cards_merge_with_observed(self, tmp_path):
        """花名册卡与观测数据合并：零 run 车道出卡、working/idle、未登记 lane 落「其他」。"""
        proot = self.build_observed(tmp_path)
        data = cc.aggregate_org(projects_of(proot), now=NOW)
        # 全部花名册车道出卡（编制内岗位可见）
        all_lanes = [c["lane"] for z in data["zones"] for c in z["cards"]]
        for lanes in cc.ROSTER.values():
            for lane in lanes:
                assert lane in all_lanes
        # planner 零 run：idle、计数为 0
        planner = self.card_of(data, "planner")
        assert planner["status"] == "idle"
        assert planner["runs"] == 0
        assert planner["success_rate"] is None  # 今日 0 需求 → denom 0 → 「—」
        assert planner["cost"] == 0.0  # 固定 $0.00（真实零显示，非「—」）
        assert planner["activity_14d"] == [0] * 14
        assert planner["attributable"] is None
        assert planner["zone"] == "需求线"
        # implementer 卡与观测一致
        impl = self.card_of(data, "implementer")
        assert impl["status"] == "working"
        assert impl["zone"] == "交付线"
        # 默认窗口 today：今日 2 run（1 done + 1 在飞）→ 成功率 1.0
        assert impl["runs"] == 2
        assert impl["success_rate"] == 1.0
        assert impl["cost"] == pytest.approx(1.2)
        assert len(impl["activity_14d"]) == 14
        assert any(impl["activity_14d"])  # 14 日活动非全零
        assert impl["last_activity_ts"]
        # 在飞 run 归属：最近在飞（impl-demo-5）→ {project, spec}
        assert impl["attributable"] == {"project": "proj-b", "spec": "demo"}
        # 在飞归属列表（2026-10-29 多 spec 并行）：今日在飞 1 条，带 run_id
        assert impl["attributables"] == [
            {"project": "proj-b", "spec": "demo", "run_id": f"impl-demo-{NOW - 600}"}
        ]
        # 观测 lane 归并：dispute-judge 计入 judge、repair 计入 code-fix
        assert self.card_of(data, "judge")["runs"] == 1
        assert self.card_of(data, "code-fix")["runs"] == 1
        # verifier（2026-10-28 重划后编制内）落「交付线」
        assert self.card_of(data, "verifier")["zone"] == "交付线"
        assert self.card_of(data, "planner-plan")["zone"] == "设计线"
        assert self.card_of(data, "evolution")["zone"] == "运营线"
        assert self.card_of(data, "self-review")["zone"] == "质量线"
        # 花名册外观测 lane（泛型 agent）落「其他」分区
        other = self.zone_of(data, "其他")
        assert [c["lane"] for c in other["cards"]] == ["agent"]
        # 分区固定序：花名册五区在前，「其他」殿后
        assert [z["zone"] for z in data["zones"]] == [
            "需求线", "设计线", "交付线", "质量线", "运营线", "其他",
        ]
        # 产品团队汇总卡（2026-10-28 追加）：今日 run = implementer 2 +
        # verifier 1 + agent 1；成本仅 implementer 计价 1.2；需求数量随窗——
        # demo 创建于 2026-03-01（T_CREATED），不在今日窗
        assert data["summary"]["spec_count"] == 0
        assert data["summary"]["runs_total"] == 6
        assert data["summary"]["cost_total"] == pytest.approx(1.2)
        # 运行时长（秒）：无 run_metrics 指标的 fixture 走 mtime 回退——终态
        # run 产物 mtime=started+60 → 各 60s（在飞 run 走真实墙钟，只设下界）
        assert data["summary"]["duration_total"] >= 300.0
        assert data["window"] == "today"

    def test_attributables_multi_spec_order_and_dedup(self, tmp_path):
        """在飞归属列表（2026-10-29 多 spec 并行滚动显示）：started 降序、
        同 (project, spec) 去重取最新（重试场景）、spec/started/run_id 缺失
        剔除；attributable 兼容字段取最新一条且形态不变（无 run_id 键）。"""
        proot = make_proj(tmp_path, "proj-m")
        # 同 spec 两条在飞（瞬态重试场景）：取最新一条
        priced_run(proot, f"impl-alpha-{NOW - 900}", "progress", NOW - 900, usage=None)
        priced_run(proot, f"impl-alpha-{NOW - 100}", "progress", NOW - 100, usage=None)
        # 另一 spec 在飞（更晚 start，应排最前）
        priced_run(proot, f"impl-beta-{NOW - 50}", "progress", NOW - 50, usage=None)
        data = cc.aggregate_org(projects_of(proot), now=NOW)
        impl = self.card_of(data, "implementer")
        assert [a["spec"] for a in impl["attributables"]] == ["beta", "alpha"]
        assert impl["attributables"][0]["run_id"] == f"impl-beta-{NOW - 50}"
        assert impl["attributables"][1]["run_id"] == f"impl-alpha-{NOW - 100}"
        assert impl["attributable"] == {"project": "proj-m", "spec": "beta"}

    def test_org_windows(self, tmp_path):
        """时间窗（2026-10-28）：7d 窗并入昨日终态；all=未归档全部（不限
        时间、剔除已归档 SPEC 名下 run）；需求数量随窗（按 created）；
        14 日 sparkline 恒为 14 日口径不随窗变。"""
        proot = self.build_observed(tmp_path)
        # 归档 SPEC 清单 + 其名下一条 run（all 窗应剔除）
        (proot / ".fenix" / "STATE.archive.md").write_text(
            "# Fenix Archive State\n\n## Specs\n"
            "\n### arch-demo\n- status: pushed\n- priority: 1\n"
            f"- created: {T_CREATED}\n- updated: {T_CREATED}\n",
            encoding="utf-8",
        )
        priced_run(proot, f"impl-arch-demo-{NOW - 5000}", "done", NOW - 5000, usage=None)
        kw = dict(now=NOW)
        d7 = cc.aggregate_org(projects_of(proot), window="7d", **kw)
        impl7 = self.card_of(d7, "implementer")
        # 7d：今日 2 + 昨日 3 → 5 run、成功率 3/4（昨日 1 error 计入）
        assert impl7["runs"] == 5
        assert impl7["success_rate"] == 0.75
        assert impl7["cost"] == pytest.approx(1.2)
        assert d7["summary"]["runs_total"] == 9  # impl 5 + verifier 1 + agent 1 + 归并 2
        assert d7["summary"]["spec_count"] == 0  # demo 创建于 3 月，不在 7 日窗
        assert self.card_of(d7, "planner")["runs"] == 0  # planner 派生=窗口内需求数
        assert d7["window"] == "7d"
        dall = cc.aggregate_org(projects_of(proot), window="all", **kw)
        # all=未归档全部：arch-demo（归档 SPEC）名下 run 被剔除 → impl 仍 5；
        # 需求数量计全量活跃 SPEC（demo 1 个，arch-demo 已归档不计）
        assert self.card_of(dall, "implementer")["runs"] == 5
        # planner 派生：全量窗 1 个活跃需求 → 1 次「需求规划」，成功率固定
        # 100%、成本固定 $0
        planner_all = self.card_of(dall, "planner")
        assert planner_all["runs"] == 1
        assert planner_all["success_rate"] == 1.0
        assert planner_all["cost"] == 0.0
        assert dall["summary"]["runs_total"] == 10  # 上行 9 + planner 派生 1
        # 时长合计为数值（全量窗 ≥ 7d 窗口径）
        assert dall["summary"]["duration_total"] >= d7["summary"]["duration_total"]
        assert dall["summary"]["spec_count"] == 1
        assert dall["window"] == "all"
        # sparkline 不随窗变（两个窗口下同一 14 日口径）
        assert (
            self.card_of(d7, "implementer")["activity_14d"]
            == self.card_of(dall, "implementer")["activity_14d"]
        )

    def test_edges_static_constant(self, tmp_path):
        """任意两次请求 edges 完全一致且等于模块常量（4 条边）。"""
        proot = make_proj(tmp_path, "proj-b", specs={})
        first = cc.aggregate_org(projects_of(proot), now=NOW)
        second = cc.aggregate_org(projects_of(proot), now=NOW)
        assert first["edges"] == second["edges"]
        assert first["edges"] == [dict(e) for e in cc.EDGES]
        assert len(first["edges"]) == 4
        # 响应副本改写不污染常量（冻结结构）
        first["edges"][0]["from"] = "tampered"
        assert cc.EDGES[0]["from"] == "planner"


# ── 交付流水线（任务 2.5） ────────────────────────────────────────────────


class TestPipelineAggregation:
    def build(self, tmp_path):
        pa = make_proj(tmp_path, "proj-a", specs={
            "d1": "drafted", "i1": "implementing", "i2": "blocked", "i3": "implementing",
        })
        pb = make_proj(tmp_path, "proj-b", specs={"t1": "testing", "p1": "pushed"})
        # i1 有在飞 run（impl- 前缀 + 10 位 epoch 后缀 → run_spec_part=i1）
        priced_run(pa, f"impl-i1-{NOW - 300}", "progress", NOW - 300, usage=None)
        return pa, pb

    def col(self, data, key):
        hit = [c for c in data["columns"] if c["key"] == key]
        assert len(hit) == 1
        return hit[0]

    def test_five_columns_running_and_blocked(self, tmp_path):
        pa, pb = self.build(tmp_path)
        data = cc.aggregate_pipeline(projects_of(pa, pb))
        assert [c["key"] for c in data["columns"]] == [
            "drafted", "ready", "implementing", "verifying", "pushed",
        ]
        counts = {c["key"]: len(c["cards"]) for c in data["columns"]}
        assert counts == {"drafted": 1, "ready": 0, "implementing": 3,
                          "verifying": 1, "pushed": 1}
        impl_cards = {c["spec"]: c for c in self.col(data, "implementing")["cards"]}
        # 在飞卡附 running（lane + 开始时间）
        assert impl_cards["i1"]["running"]["lane"] == "implementer"
        assert impl_cards["i1"]["running"]["started_at"] == _iso(NOW - 300)
        # blocked 卡保留原生 status（侧挂归在制列）
        assert impl_cards["i2"]["status"] == "blocked"
        assert "running" not in impl_cards["i2"]
        assert impl_cards["i3"]["status"] == "implementing"
        # 每卡携带 project + 原生 status
        pushed = self.col(data, "pushed")["cards"]
        assert pushed == [{"project": "proj-b", "spec": "p1", "status": "pushed"}]

    def test_pipeline_project_filter_echo(self, tmp_path):
        pa, pb = self.build(tmp_path)
        data = cc.aggregate_pipeline(projects_of(pa, pb), project="proj-a")
        specs = [c["spec"] for c in data["columns"] for c2 in [c] for c in c2["cards"]]
        assert set(specs) == {"d1", "i1", "i2", "i3"}
        assert data["project"] == "proj-a"
        # projects 回显仍为全集（筛选下拉数据源）
        assert data["projects"] == ["proj-a", "proj-b"]


# ── 执行台账（任务 2.5） ──────────────────────────────────────────────────


class TestLedgerAggregation:
    def test_rows_ordering_and_null_trigger(self, tmp_path):
        pa = make_proj(tmp_path, "proj-a", specs={"s": "implementing"})
        pb = make_proj(tmp_path, "proj-b", specs={"s": "implementing"})
        enable_billing(pa)
        T1, T2, T3, T4 = NOW - 4000, NOW - 3000, NOW - 1000, NOW - 2000
        priced_run(pa, f"impl-s-{T1}", "done", T1)   # T1
        priced_run(pa, f"impl-s-{T2}", "done", T2)   # T2（计价 1.0）
        priced_run(pa, f"impl-s-{T3}", "error", T3)  # T3（error 无 usage 不计价）
        priced_run(pb, f"impl-s-{T4}", "done", T4)   # T4（T1<T4<T3，项目未计价）
        data = cc.aggregate_ledger(projects_of(pa, pb))
        rows = data["rows"]
        assert len(rows) == 4
        # 跨项目按开始时间倒序：T3、T4、T2、T1
        assert [(r["project"], r["started_at"]) for r in rows] == [
            ("proj-a", _iso(T3)), ("proj-b", _iso(T4)),
            ("proj-a", _iso(T2)), ("proj-a", _iso(T1)),
        ]
        for r in rows:
            assert set(r) == {
                "project", "spec", "lane", "outcome", "duration",
                "tokens", "cost", "started_at", "trigger",
            }
            assert r["lane"] == "implementer"
            assert r["outcome"] in ("done", "error")
            # trigger 既有数据缺口：null 不硬造
            assert r["trigger"] is None
        # 计价 run 行带成本/tokens（既有成本口径）；error 行与未计价项目行为 None
        assert rows[0]["cost"] is None  # T3 = error run，无 result.usage
        assert rows[2]["cost"] == pytest.approx(1.0)  # T2 = done + 计价
        assert rows[2]["tokens"] == 1_000_000
        assert rows[1]["cost"] is None  # proj-b 未配计价卡片

    def test_rows_cap_50(self, tmp_path):
        pa = make_proj(tmp_path, "proj-a", specs={"s": "implementing"})
        for i in range(55):
            priced_run(pa, f"impl-s-{i}", "done", NOW - 6000 + i, usage=None)
        data = cc.aggregate_ledger(projects_of(pa))
        assert len(data["rows"]) == 50
        starts = [r["started_at"] for r in data["rows"]]
        assert starts == sorted(starts, reverse=True)
        # 倒序截断保留最近 50 条（最早的 5 条出榜）
        assert data["rows"][0]["started_at"] == _iso(NOW - 6000 + 54)


# ── 裁决收件箱（任务 2.5） ────────────────────────────────────────────────

_CHOICES_A1 = [
    {"id": "retry", "label": "重试", "desc": "重跑验证", "action": "reset_verification"},
    {"id": "abandon", "label": "撤销丢弃", "desc": "软删除归档",
     "action": "abandon", "destructive": True},
    {"id": "ack", "label": "确认观察", "desc": "留痕关闭", "action": "ack_self_heal"},
]
_CHOICES_A2 = [
    {"id": "force_advance", "label": "接受现状推进", "desc": "豁免推进",
     "action": "force_advance"},
]


class TestInboxAggregation:
    def build(self, tmp_path):
        pa = make_proj(tmp_path, "proj-a", specs={"x": "blocked"})
        pb = make_proj(tmp_path, "proj-b", specs={"y": "implementing"})
        write_alerts(pa, [
            {  # 高严重度带 3 选项快照的未决告警
                "id": "al-1", "kind": "escalation", "severity": "critical",
                "created": _iso(NOW - 500), "spec": "x", "run_id": "impl-x-1",
                "signal_type": "sig-a", "handled": False, "choices": _CHOICES_A1,
            },
            {  # 已终态告警 → 不进收件箱
                "id": "al-3", "kind": "escalation", "severity": "critical",
                "created": _iso(NOW - 400), "spec": "x", "handled": True,
                "handled_at": _iso(NOW - 300), "choices": _CHOICES_A1,
            },
            {  # 无 choices 快照的知情类告警 → 不进收件箱
                "id": "al-4", "kind": "signal", "severity": "minor",
                "created": _iso(NOW - 200), "handled": False,
            },
        ])
        write_alerts(pb, [
            {  # 低严重度带选项快照的未决告警
                "id": "al-2", "kind": "escalation", "severity": "major",
                "created": _iso(NOW - 100), "spec": "y",
                "signal_type": "sig-b", "handled": False, "choices": _CHOICES_A2,
            },
        ])
        return pa, pb

    def test_pending_cards_sorted_and_snapshot_exact(self, tmp_path):
        pa, pb = self.build(tmp_path)
        data = cc.aggregate_inbox(projects_of(pa, pb))
        cards = data["cards"]
        # 仅含前两条（未终态且带 choices 快照）；高严重度在前
        assert [c["id"] for c in cards] == ["al-1", "al-2"]
        assert cards[0]["severity"] == "critical"
        # choices 与告警记录内快照逐字段一致（只读快照，不回读注册表）
        assert cards[0]["choices"] == _CHOICES_A1
        assert cards[1]["choices"] == _CHOICES_A2
        # 溯源字段齐全
        assert cards[0]["project"] == "proj-a"
        assert cards[0]["spec"] == "x"
        assert cards[0]["signal_type"] == "sig-a"
        assert cards[0]["created_at"] == _iso(NOW - 500)
        # 纯装配：响应不携带任何执行动作端点引用
        for c in cards:
            assert not any("endpoint" in k or "action_url" in k for k in c)
        # projects 回显全集
        assert data["projects"] == ["proj-a", "proj-b"]

    def test_inbox_project_filter(self, tmp_path):
        pa, pb = self.build(tmp_path)
        data = cc.aggregate_inbox(projects_of(pa, pb), project="proj-b")
        assert [c["id"] for c in data["cards"]] == ["al-2"]
        assert data["project"] == "proj-b"


# ── 端点注册（任务 2.4：真实 DashboardHTTPServer 分派链） ─────────────────


@pytest.fixture()
def cc_server_fx(tmp_path):
    proot = make_proj(tmp_path, "proj-a", specs={"d1": "drafted", "i1": "implementing"})
    enable_billing(proot)
    priced_run(proot, f"impl-i1-{NOW - 300}", "progress", NOW - 300, usage=None)
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


class TestCommandCenterEndpoints:
    def test_five_endpoints_registered(self, cc_server_fx):
        proot, srv = cc_server_fx
        for path in (
            "/api/command-center/kpi",
            "/api/command-center/org",
            "/api/command-center/pipeline",
            "/api/command-center/ledger",
            "/api/command-center/inbox",
        ):
            status, data = srv.get(path)
            assert status == 200, path
            assert "error" not in data, (path, data)
            assert data["projects"] == ["proj-a"]

    def test_endpoint_shapes(self, cc_server_fx):
        _, srv = cc_server_fx
        _, kpi = srv.get("/api/command-center/kpi")
        assert set(kpi) >= {
            "delivered_specs_7d", "human_intervention_rate_7d",
            "run_success_rate_7d", "cost_per_spec_7d", "gateway_health",
        }
        _, org = srv.get("/api/command-center/org")
        assert len(org["edges"]) == 4
        _, pipeline = srv.get("/api/command-center/pipeline")
        assert len(pipeline["columns"]) == 5
        _, ledger = srv.get("/api/command-center/ledger")
        assert ledger["rows"][0]["trigger"] is None
        _, inbox = srv.get("/api/command-center/inbox")
        assert inbox["cards"] == []

    def test_endpoint_project_filter_and_unknown_compat(self, cc_server_fx):
        _, srv = cc_server_fx
        status, data = srv.get("/api/command-center/pipeline?project=proj-a")
        assert status == 200
        assert data["project"] == "proj-a"
        assert data["projects"] == ["proj-a"]
        # 未知项目维持 200 + {"error": ...}（与 collab-graph 同族兼容契约）
        for path in (
            "/api/command-center/kpi",
            "/api/command-center/org",
            "/api/command-center/pipeline",
            "/api/command-center/ledger",
            "/api/command-center/inbox",
        ):
            status, data = srv.get(f"{path}?project=no-such")
            assert status == 200, path
            assert "error" in data, path

    def test_aggregate_methods_are_readonly(self, cc_server_fx):
        """五端点只读、无副作用：重复调用结果一致。"""
        proot, srv = cc_server_fx
        priced_run(proot, f"impl-i1-{NOW - 100}", "done", NOW - 100)
        for path in (
            "/api/command-center/kpi",
            "/api/command-center/org",
            "/api/command-center/pipeline",
            "/api/command-center/ledger",
            "/api/command-center/inbox",
        ):
            _, first = srv.get(path)
            _, second = srv.get(path)
            assert first == second, path
