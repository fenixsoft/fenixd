"""core.dashboard.data.collab_graph — 跨项目角色级协作图谱聚合。

add-collab-graph-bigscreen：对 dashboard 托管全部项目的全部 SPEC 逐个调用
``topology.derive_topology``（单 SPEC 拓扑派生单点）并在其结果上聚合出
**角色级**协作图谱——角色为节点（固定 8 泳道角色集）、跨角色交接为边、
次数为边权、成本/时长/run 计数/在飞计数为节点权重，外加全局 KPI 与下钻
明细（recent_runs）。角色归列与 attempt 归并**零第二套实现**：全部语义
（``_ROLE_TABLE`` 归列、attempt/瞬态重试后缀归并、用户/PMEngine 特殊节点）
复用 topology.py 派生产物，本模块只做「节点/边 → 泳道角色」的投影聚合。

本模块纯只读：不写任何文件、不改归档链路。已归档 SPEC（``STATE.archive.md``
清单条目，run 产物已随 ``archive_spec_runs`` 清理）计入 KPI 计数与
``archived_excluded``，但**跳过 ``derive_topology`` 调用**——归档 SPEC 无
run 数据可聚合，零产物读取开销（specs「归档 SPEC 口径」Requirement）。
"""

from pathlib import Path

from core import timelib

# 角色固定集 = 单 SPEC 拓扑八泳道（topology.LANES 单源，含用户/PMEngine
# 特殊节点）：specs「跨项目角色图谱聚合端点」的角色粒度 MUST 与单 SPEC
# 泳道角色口径同源。
from .topology import LANES, LANE_LABELS, derive_topology
from .state import parse_archived_state, parse_state

# 在飞 run 状态（与单 SPEC 大屏在飞口径一致：classify_run 的非终态读侧
# 枚举——running=末行非终态事件、empty=零事件产物）。
IN_FLIGHT_STATUSES = ("running", "empty")

# 下钻明细条数上限（specs：返回条数上限留实现裁量）。节点/边各自独立
# 截断，按时间降序保留最近 N 条。
RECENT_RUNS_CAP = 10


def _new_role(lane: str) -> dict:
    """角色节点骨架（固定 8 泳道全量下发——零交接的角色也入图，前端固定
    就位布局需要完整角色集）。cost_usd 与单 SPEC 拓扑 total_cost_usd 同
    语义：全部 run 不可计价时为 None（不渲染 $0.00 伪装可计价）。"""
    return {
        "id": lane,
        "role": lane,
        "label": LANE_LABELS[lane],
        "cost_usd": None,
        "duration_seconds": 0,
        "run_count": 0,
        "running": 0,
        "in_flight": False,
        "recent_runs": [],
    }


def _recent_key(entry: dict):
    """recent_runs 排序键：解析时间降序用（最新在前），解析失败排末尾。"""
    dt = timelib.parse_ts(str(entry.get("time") or ""))
    if dt is None:
        from datetime import datetime as _dt, timezone as _tz

        return (1, _dt.max.replace(tzinfo=_tz.utc))
    return (0, dt)


def _push_recent(bucket: list, entry: dict) -> None:
    """追加一条下钻明细并保留时间最新的 RECENT_RUNS_CAP 条（降序）。"""
    bucket.append(entry)
    bucket.sort(key=_recent_key, reverse=True)
    del bucket[RECENT_RUNS_CAP:]


def _merge_topology(topo: dict, project_name: str, roles: dict, edges: dict, state: dict) -> None:
    """把单 SPEC 拓扑派生结果投影聚合进角色级图谱（就地修改）。

    投影口径：
    - 节点：``lane`` 非空的节点落对应角色；``kind=="run"`` 计入权重与明细
      （verify 轮次是验证动作非 agent run，不进 run 计数/成本/时长，但其
      占位仍参与边投影——见下）；delivery/approve 终点（lane=None）不进
      角色图；
    - 边：拓扑边两端节点 lane 均非空且不同 → 跨角色交接边，weight +1，
      明细取**目标节点**（交接的接收方 run）的项目/SPEC/时间/状态。
    """
    spec_name = str(topo.get("spec") or "")
    if any(
        n.get("kind") == "run" and n.get("status") in IN_FLIGHT_STATUSES
        for n in topo.get("nodes", [])
    ):
        state["running_specs"].add(spec_name)

    node_by_id = {n["id"]: n for n in topo.get("nodes", []) if isinstance(n, dict)}

    for n in topo.get("nodes", []):
        if not isinstance(n, dict):
            continue
        lane = n.get("lane")
        if lane is None:
            continue  # delivery/approve 终点不进角色图
        role = roles.get(lane)
        if role is None:
            continue  # LANES 之外的 lane 值防御性丢弃（LANES 单源下不可达）
        if n.get("kind") != "run":
            continue
        role["run_count"] += 1
        d = n.get("duration_seconds")
        if isinstance(d, (int, float)) and d > 0:
            role["duration_seconds"] += int(d)
        c = n.get("cost_usd")
        if isinstance(c, (int, float)):
            role["cost_usd"] = (role["cost_usd"] or 0.0) + float(c)
        if n.get("status") in IN_FLIGHT_STATUSES:
            role["running"] += 1
            role["in_flight"] = True
        _push_recent(
            role["recent_runs"],
            {
                "project": project_name,
                "spec": str(n.get("spec") or spec_name),
                "time": str(n.get("time") or ""),
                "status": str(n.get("status") or ""),
            },
        )

    for e in topo.get("edges", []):
        src = node_by_id.get(e.get("from"))
        dst = node_by_id.get(e.get("to"))
        if not isinstance(src, dict) or not isinstance(dst, dict):
            continue
        sl = src.get("lane")
        dl = dst.get("lane")
        if sl is None or dl is None or sl == dl:
            continue  # 同角色内转移（dispatch 同泳道/retry attempt 链）不产生跨角色边
        key = (sl, dl)
        edge = edges.get(key)
        if edge is None:
            edge = {"from": sl, "to": dl, "weight": 0, "recent_runs": []}
            edges[key] = edge
        edge["weight"] += 1
        _push_recent(
            edge["recent_runs"],
            {
                "project": project_name,
                "spec": str(dst.get("spec") or spec_name),
                "time": str(dst.get("time") or ""),
                "status": str(dst.get("status") or ""),
            },
        )


def aggregate_collab_graph(registry_projects, project=None) -> dict:
    """跨项目角色级协作图谱聚合（``GET /api/overview/collab-graph`` 数据源）。

    Args:
        registry_projects: registry 项目清单（``server.projects()`` 结果，
            与 ``summary.overview(registry_projects)`` 同一注入模式——数据层
            不持有 registry 引用）。
        project: 可选项目名，收窄聚合范围到单项目（specs「项目筛选收窄」）。

    Returns::

        {
          "project": <name | None>,          # 回显筛选参数
          "projects": [...],                 # 可聚合项目名全集（筛选器数据源）
          "roles": [8 角色节点],
          "edges": [{from, to, weight, recent_runs}],
          "kpis": {spec_count, active_spec_count, archived_excluded,
                   running_specs, running_runs, total_runs,
                   total_cost_usd, total_handoffs},
          "archived_excluded": <N>,          # 顶层口径计数（前端注记）
        }

    归档口径：归档清单（``STATE.archive.md``）条目计入 spec_count 与
    archived_excluded、**不触发** ``derive_topology``（零 run 产物读取）；
    活跃 STATE 条目逐个派生聚合（若活跃条目实际已归档——目录迁出而条目
    未迁清单的过渡态——按派生结果 archived 归入归档口径）。
    """
    roles = {lane: _new_role(lane) for lane in LANES}
    edges: dict = {}
    spec_count = 0
    active_count = 0
    archived_excluded = 0
    project_names: list = []
    running_specs: set = set()
    state = {"running_specs": running_specs}

    for p in registry_projects or []:
        name = p.get("name")
        if not name:
            continue
        if project is not None and name != project:
            continue
        if not p.get("exists"):
            continue  # 未就绪项目零贡献（同 _aggregatable_projects 的 exists 口径）
        project_names.append(name)
        proot = Path(p["path"])
        active = parse_state(proot)
        archived = parse_archived_state(proot)
        # 归档清单条目：计 KPI 不进图、零 derive 调用（run 产物已清理，
        # specs「归档项目零开销跳过」Scenario）。与活跃 STATE 重叠的条目
        # 不重复计数（活跃侧派生结果仲裁归档口径）。
        for spec_name in sorted(set(archived) - set(active)):
            spec_count += 1
            archived_excluded += 1
        for spec_name in sorted(active):
            spec_count += 1
            topo = derive_topology(proot, spec_name, active[spec_name])
            if topo.get("archived"):
                # 目录已迁出（条目残留活跃清单的过渡态）：派生结果无 run
                # 数据可聚合，按归档口径计 KPI
                archived_excluded += 1
                continue
            active_count += 1
            _merge_topology(topo, name, roles, edges, state)

    # 边序：按泳道固定序（LANES 下标）排序，响应形态确定（两次请求顺序一致）
    lane_index = {lane: i for i, lane in enumerate(LANES)}
    edge_list = sorted(
        edges.values(),
        key=lambda e: (lane_index.get(e["from"], 99), lane_index.get(e["to"], 99)),
    )

    total_runs = sum(r["run_count"] for r in roles.values())
    priced = [r["cost_usd"] for r in roles.values() if r["cost_usd"] is not None]
    kpis = {
        "spec_count": spec_count,
        "active_spec_count": active_count,
        "archived_excluded": archived_excluded,
        "running_specs": len(running_specs),
        "running_runs": sum(r["running"] for r in roles.values()),
        "total_runs": total_runs,
        "total_cost_usd": sum(priced) if priced else None,
        "total_handoffs": sum(e["weight"] for e in edge_list),
    }

    return {
        "project": project,
        "projects": project_names,
        "roles": [roles[lane] for lane in LANES],
        "edges": edge_list,
        "kpis": kpis,
        "archived_excluded": archived_excluded,
    }
