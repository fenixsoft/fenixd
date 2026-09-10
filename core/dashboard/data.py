"""
data.py — 共享数据聚合层（TUI 与 Web Dashboard 共用）。

把 bin/fenix_dashboard.py 中已验证的 STATE.md / tasks.md / 日志 / 验证产物解析
逻辑提取为以 project_root 为参数的纯函数，并为 Web 增加更丰富的聚合视图（验证
进度、逐场景断言、bug 列表、截图列表、运行记录）。

容错约定：所有解析函数对损坏/缺失数据源绝不抛异常——损坏的 JSON 以带
`"error": "corrupt"` 标记的对象返回，缺失则返回空结构，保证聚合请求不 500。
"""

import copy
import json
import os
import re
import shutil
import tempfile
import threading
import time
from collections import deque
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

from core.agent_runner.run_files import run_spec_part
from core.archive_commit import commit_archive_move
from core.fenix_session import is_running as _is_running


# ── Administrator 告警（.fenix/admin_alerts.json） ─────────────────

def get_alerts(project_root) -> list:
    """读取项目全部 Administrator 告警/处置记录（最新在前）。缺失/损坏返回 []。"""
    from core.admin_store import AdminStore
    return AdminStore(project_root).read_all()


def get_unhandled_alerts(project_root) -> list:
    """读取项目未处理的升级告警（最新在前）。"""
    from core.admin_store import AdminStore
    return AdminStore(project_root).unhandled()


def get_resolved_alerts(project_root, limit: int = 50) -> list:
    """读取项目已处理的升级告警（最新在前，add-alert-auto-resolve D5）。

    供管理员视图「已解决」折叠区展示：含 handled_by（区分自动解决/人工处理）、
    resolve_note（解除/处置依据）与 handled_at。仍走 AdminStore.read_all 既有
    读取路径（不绕锁、不改存储格式）。
    """
    from core.admin_store import AdminStore, ESCALATION
    resolved = [
        r for r in AdminStore(project_root).read_all()
        if r.get("kind") == ESCALATION and r.get("handled")
    ]
    return resolved[:limit]


def mark_alert_handled(project_root, alert_id: str) -> bool:
    """标记某条升级告警为已处理。返回是否找到并更新。"""
    from core.admin_store import AdminStore
    return AdminStore(project_root).mark_handled(alert_id)


def mark_all_alerts_handled(project_root) -> int:
    """将项目所有未处理升级告警标记为已处理。返回处理数量。"""
    from core.admin_store import AdminStore
    return AdminStore(project_root).mark_all_handled()


def alerts_summary(project_root) -> dict:
    """项目告警摘要：{unhandled_count, max_severity, latest}。

    max_severity 取未处理告警中最高严重度（critical > major > minor）；
    latest 为最新一条未处理告警。无未处理时三者为空/0。
    """
    unhandled = get_unhandled_alerts(project_root)
    if not unhandled:
        return {"unhandled_count": 0, "max_severity": None, "latest": None}
    sev_rank = {"critical": 3, "major": 2, "minor": 1}
    top = max(unhandled, key=lambda a: sev_rank.get(a.get("severity"), 0))
    return {
        "unhandled_count": len(unhandled),
        "max_severity": top.get("severity"),
        "latest": unhandled[0],
    }


def get_admin_activities(project_root, spec=None) -> list:
    """返回 Administrator 处置活动记录（运维记录时间线数据源）。

    从 admin_alerts.json 过滤 kind=disposition，按时间倒序；与未处理升级
    escalation 关联（同 admin_run_id）的记录置顶，并标记 handled=False +
    escalation_id（供前端 mark-handled）。旧记录无 summary 时原样返回，
    界面降级显示结构化字段（design D1，向后兼容）。

    spec 非空时（add-admin-invoke-dialog）在归并/置顶逻辑完成后按
    `rec.get("spec") == spec` 过滤，仅返回该 SPEC 相关记录（置顶语义先于
    过滤生效，保证未处理升级置顶后仍被正确过滤）。
    """
    from core.admin_store import AdminStore, DISPOSITION, ESCALATION
    records = AdminStore(project_root).read_all()

    # 未处理升级 → 关联 disposition（按 admin_run_id 匹配）
    unhandled_by_run: dict = {}
    for rec in records:
        if (rec.get("kind") == ESCALATION and not rec.get("handled")
                and rec.get("admin_run_id")):
            unhandled_by_run.setdefault(rec["admin_run_id"], rec.get("id"))

    activities = []
    # 按 admin_run_id 归并：pending 是 admin 唤起时的标记记录，同 run 一旦产生
    # 最终 disposition（result != pending）即以最终为准，避免页面出现"永久处置中"。
    best_by_run: dict = {}
    for rec in records:
        if rec.get("kind") != DISPOSITION:
            continue
        rid = rec.get("admin_run_id") or f"run-{id(rec)}"
        status = rec.get("status") or rec.get("result")
        is_pending = status == "pending"
        existing = best_by_run.get(rid)
        if existing is None:
            best_by_run[rid] = (is_pending, rec)
            continue
        # 非 pending 优先于 pending；同为非 pending 取最新
        if is_pending and not existing[0]:
            continue
        if not is_pending and existing[0]:
            best_by_run[rid] = (False, rec)
        elif (rec.get("created") or "") > (existing[1].get("created") or ""):
            best_by_run[rid] = (is_pending, rec)

    for _is_pending, rec in best_by_run.values():
        item = dict(rec)
        esc_id = unhandled_by_run.get(rec.get("admin_run_id"))
        item["handled"] = esc_id is None
        item["escalation_id"] = esc_id
        item["actions_taken"] = rec.get("actions_taken") or rec.get("action_taken") or ""
        item["_pin"] = esc_id is not None
        activities.append(item)

    # 未处理升级关联置顶，组内按时间倒序
    activities.sort(
        key=lambda a: (a["_pin"], a.get("created") or ""), reverse=True)
    for a in activities:
        a.pop("_pin", None)

    # add-admin-invoke-dialog：可选 spec 过滤（置顶语义先行，过滤后生效）
    if spec is not None:
        activities = [a for a in activities if a.get("spec") == spec]

    return activities


# ── 手动唤起 Administrator（add-spec-manual-admin-invoke） ─────────

# daemon 主循环轮询的请求信号文件名（与 fenixd.py 约定一致）
ADMIN_INVOKE_REQUEST = ".fenix/admin_invoke_request.json"


def request_admin_invoke(project_root, spec: str, prompt: str | None = None) -> dict:
    """写入手动唤起 Administrator 的文件信号（.fenix/admin_invoke_request.json）。

    校验 spec 须存在于项目 STATE.md，且当前不存在未消费的请求文件，否则返回
    对应拒绝状态（spec 不存在 → {found: False}；已有进行中 → {conflict: True}）。
    通过校验后原子写入 {spec, source: "manual", created: <ISO>} 返回 {ok: True}。

    prompt：用户在 Dashboard 处置弹窗输入的提示词，非空时写入请求文件，
    daemon 拾取后作为本次处置的任务描述（替代默认文案）传给 Administrator。

    文件信号模式与 restart_request 同构：server 进程不直接起 agent（绕过
    state_machine 与 token 预算），由 daemon 主循环下一轮扫描拾取并唤起。

    Returns:
        {"ok": bool, "found": bool, "conflict": bool,
         "file": str|null, "created": str|null, "error": str|null}
    """
    proot = Path(project_root)
    specs = parse_state(proot)
    if spec not in specs:
        return {"ok": False, "found": False, "conflict": False,
                "file": None, "created": None,
                "error": f"spec not found: {spec}"}

    req_path = proot / ADMIN_INVOKE_REQUEST
    if req_path.exists():
        return {"ok": False, "found": True, "conflict": True,
                "file": str(req_path), "created": None,
                "error": "已有进行中的 Admin 处置"}

    created = datetime.now(timezone.utc).isoformat()
    payload = {"spec": spec, "source": "manual", "created": created}
    if prompt and prompt.strip():
        payload["prompt"] = prompt.strip()
    req_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(req_path.parent), prefix=".admin_invoke_request.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, req_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return {"ok": True, "found": True, "conflict": False,
            "file": str(req_path), "created": created, "error": None}


# ── run 人工取消（add-run-cancel D5 / spec「文件信号跨进程入口」） ─────────

CANCEL_RUN_REQUEST = ".fenix/cancel_run_request.json"


def request_run_cancel(project_root, run_id: str, reason: str = "") -> dict:
    """写入 run 取消的文件信号（.fenix/cancel_run_request.json）。

    原子写（tmp+rename），与 request_admin_invoke 同构：
    - 已存在未消费的请求文件 → 返回冲突（409），不覆盖；
    - run_id 为空 → 返回 {ok: False, missing_run_id: True}；
    - 成功写入 → 返回 {ok: True, created}。

    文件信号模式（D5）：daemon 主循环下一轮（≤2s）扫描拾取并调用
    agent_runner.cancel_run。server 进程不直接调用 cancel_run。

    Returns:
        {"ok": bool, "conflict": bool, "missing_run_id": bool,
         "file": str|null, "created": str|null, "error": str|null}
    """
    if not run_id or not run_id.strip():
        return {"ok": False, "conflict": False, "missing_run_id": True,
                "file": None, "created": None,
                "error": "run_id is required"}

    proot = Path(project_root)
    req_path = proot / CANCEL_RUN_REQUEST

    # 已有未消费请求 → 冲突（409）
    if req_path.exists():
        try:
            existing = json.loads(req_path.read_text(encoding="utf-8"))
            existing_created = existing.get("created") if isinstance(existing, dict) else None
        except (OSError, json.JSONDecodeError):
            existing_created = None
        return {"ok": False, "conflict": True, "missing_run_id": False,
                "file": str(req_path), "created": existing_created,
                "error": "已有进行中的取消请求"}

    created = datetime.now(timezone.utc).isoformat()
    payload = {"run_id": run_id.strip(), "reason": reason or "",
               "source": "dashboard", "created": created}
    req_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(req_path.parent), prefix=".cancel_run_request.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, req_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return {"ok": True, "conflict": False, "missing_run_id": False,
            "file": str(req_path), "created": created, "error": None}


# ── SPEC 人工冻结/解冻（用户指令冻结；admin_monitor 认 blocked+前缀为有意等待态） ──

# 冻结前缀与「原状态 X」解析单点（add-spec-scheduling-controls D4）：冻结/解冻
# 统一走 StateMachine 官方通道（freeze_spec/unfreeze_spec），此处只保留展示用
# 判定常量，文案契约在 state_machine 定义，避免双轨漂移。
from core.state_machine import FREEZE_ERROR_PREFIX, parse_orig_status


def is_spec_frozen(entry: dict) -> bool:
    """判定 SPEC 是否处于人工冻结态：status=blocked 且 error 以冻结前缀开头。"""
    return entry.get("status") == "blocked" and (entry.get("error") or "").startswith(
        FREEZE_ERROR_PREFIX
    )


def freeze_spec(project_root, spec_name: str, reason: str = "") -> dict:
    """人工冻结 SPEC：status→blocked，error 以「用户指令冻结：」开头并记录原状态。

    - done/pushed 终态不可冻结（冻结终态破坏语义），返回 ok=True + frozen=False
    - 写回委托 StateMachine.freeze_spec（add-spec-scheduling-controls D4 收编）：
      结构化 frozen: True 标记 + 原状态并入 reason（``用户指令冻结：原状态 X
      [ · reason]``），daemon 经 STATE.md watcher 感知后停止调度。此前直写
      update_spec 只写 {status, error} 不写 frozen 标记，与 StateMachine 冻结
      双轨并行时产生「解冻后 status 被冻结保护剥离」的半死态，本版本消除。
    """
    specs = parse_state(project_root)
    if spec_name not in specs:
        return {"ok": False, "found": False, "frozen": False,
                "error": f"spec not found: {spec_name}"}
    entry = specs[spec_name]
    if is_spec_frozen(entry):
        return {"ok": True, "found": True, "frozen": True, "error": None}
    if entry.get("status") in ("done", "pushed"):
        return {"ok": True, "found": True, "frozen": False,
                "error": f"终态 spec（{entry.get('status')}）不可冻结"}
    orig = entry.get("status") or "ready"
    note = f"原状态 {orig}" + (f" · {reason}" if reason else "")
    from core.state_machine import StateMachine
    sm = StateMachine(Path(project_root) / ".fenix" / "STATE.md", None)
    sm.freeze_spec(spec_name, reason=note)
    return {"ok": True, "found": True, "frozen": True, "error": None}


def unfreeze_spec(project_root, spec_name: str) -> dict:
    """解冻 SPEC：从冻结 error 中恢复原状态并清空 error；未冻结则为 no-op。

    委托 StateMachine.unfreeze_spec（D4 收编）：status 传解析出的原状态，
    恢复为冻结前状态并清 error/frozen_until。此前直写 update_spec 对带
    frozen 标记的结构化冻结 spec 会被冻结保护剥离 status，残留半死态。
    """
    specs = parse_state(project_root)
    if spec_name not in specs:
        return {"ok": False, "found": False, "frozen": False,
                "error": f"spec not found: {spec_name}"}
    entry = specs[spec_name]
    if not is_spec_frozen(entry):
        return {"ok": True, "found": True, "frozen": False, "error": None}
    orig = parse_orig_status(entry.get("error"))
    from core.state_machine import StateMachine
    sm = StateMachine(Path(project_root) / ".fenix" / "STATE.md", None)
    sm.unfreeze_spec(spec_name, status=orig)
    return {"ok": True, "found": True, "frozen": False, "error": None}


# ── SPEC 人工晋升 drafted → ready（add-draft-promotion-gate D4） ──────

def promote_spec(project_root, spec_name: str) -> dict:
    """人工晋升 drafted SPEC：调用共享晋升函数（软化+lint+判定）。

    - spec 不存在 → {ok: False, found: False, error: ...}
    - spec 非 drafted → {ok: False, found: True, ok: False, reason: ...}
    - lint 违规 → {ok: False, found: True, violations: [...], error: ...}
    - 成功 → {ok: True, found: True, violations: []}
    """
    specs = parse_state(project_root)
    if spec_name not in specs:
        return {"ok": False, "found": False,
                "error": f"spec not found: {spec_name}"}
    from core.pm_engine.promotion import promote_drafted
    from core.state_machine import StateMachine
    from core.logger import Logger
    proot = Path(project_root)
    sm = StateMachine(proot / ".fenix" / "STATE.md", None)
    logger = Logger(proot)
    result = promote_drafted(proot, spec_name, state_machine=sm, logger=logger)
    if result["ok"]:
        # 成功：transition drafted → ready（由 watcher/full_scan 感知派发）
        sm.transition(spec_name, "ready")
        return {"ok": True, "found": True, "violations": []}
    # 失败
    if "reason" in result:
        # 非 drafted 或不存在
        return {"ok": False, "found": True, "reason": result["reason"],
                "error": result["reason"]}
    # lint 违规（STATE error 已由 promote_drafted 写入）
    return {"ok": False, "found": True, "violations": result["violations"],
            "error": f"晋升 lint 未通过：{'; '.join(result['violations'])}"}


# ── SPEC 定时拾取 start_after（add-spec-scheduling-controls D5） ───────

# daemon 主循环轮询的「清空定时拾取即派发」请求信号文件名（与 fenixd.py 约定一致）
SCHEDULING_KICK_REQUEST = ".fenix/scheduling_kick_request.json"


def _write_scheduling_kick_signal(project_root, spec: str) -> dict:
    """写入清空 start_after 后的即时派发唤醒信号（.fenix/scheduling_kick_request.json）。

    原子写（tmp+rename），与 request_admin_invoke 同构；已存在未消费信号时
    不覆盖（返回 conflict），避免把先到的请求顶掉——两个 spec 的唤醒互不冲突，
    daemon 拾取侧按各自 spec 独立派发即可。
    """
    req_path = Path(project_root) / SCHEDULING_KICK_REQUEST
    if req_path.exists():
        return {"ok": False, "conflict": True, "file": str(req_path)}
    payload = {
        "spec": spec,
        "action": "clear-start-after",
        "created": datetime.now(timezone.utc).isoformat(),
    }
    req_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(req_path.parent), prefix=".scheduling_kick_request.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, req_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return {"ok": True, "conflict": False, "file": str(req_path)}


def get_spec_start_after(entry: dict) -> str | None:
    """读取 entry 的 start_after 规范值（ISO8601 UTC 字符串或 None）。

    纯读函数：非法格式/缺失按「无限制」处理（返回 None），供列表倒计时
    展示与前端状态推导用。时间换算/校验单点在后端（design D6）。
    """
    from core.state_machine import parse_utc

    raw = entry.get("start_after") if isinstance(entry, dict) else None
    if raw is None:
        return None
    dt = parse_utc(raw)
    return dt.isoformat() if dt is not None else None


def get_frozen_until(entry: dict) -> str | None:
    """读取 entry 的 frozen_until 规范值（ISO8601 UTC 字符串或 None）。

    与 get_spec_start_after 同构：非法格式视为无定时解冻目标（返回 None）。
    """
    from core.state_machine import parse_utc

    raw = entry.get("frozen_until") if isinstance(entry, dict) else None
    if raw is None:
        return None
    dt = parse_utc(raw)
    return dt.isoformat() if dt is not None else None


def set_spec_start_after(project_root, spec: str, value) -> dict:
    """设置/清除 SPEC 的 start_after（定时拾取时间，ISO8601 UTC 或 null）。

    - spec 不在 STATE.md → {found: False}
    - value 为 None/空串 → 清除定时（start_after 置 null，立即恢复调度）
    - value 非法 ISO8601 → {invalid: True}（拒绝写入，STATE.md 不变）
    - 终态（done/pushed）→ {terminal: True}（拒绝，定时不影响终态语义）
    - 成功 → {ok: True, start_after: <ISO8601 UTC 或 None>}
    写入经 StateMachine.update_spec（flock + 原子 rename，与 daemon 并发写安全）。
    """
    from core.state_machine import StateMachine, parse_utc

    proot = Path(project_root)
    specs = parse_state(proot)
    if spec not in specs:
        return {"ok": False, "found": False, "error": f"spec not found: {spec}"}
    entry = specs[spec]
    if entry.get("status") in ("done", "pushed"):
        return {"ok": False, "found": True, "terminal": True,
                "error": f"终态 spec（{entry.get('status')}）不可设置定时拾取"}
    if value is None or (isinstance(value, str) and not value.strip()):
        normalized = None
    else:
        dt = parse_utc(value)
        if dt is None:
            return {"ok": False, "found": True, "invalid": True,
                    "error": f"start_after 非法 ISO8601: {value!r}"}
        normalized = dt.isoformat()
    sm = StateMachine(proot / ".fenix" / "STATE.md", None)
    sm.update_spec(spec, {"start_after": normalized})
    # 清空即唤醒（2026-09-08 fix-run-cancel-retry-flag-miss 事故路径）：status 恒为
    # ready，event_bus watcher 只盯 status 不发事件、check_scheduling_deadlines 只管
    # 「时间流逝到期」，此前清空后要等 30min 一轮 recovery full_scan 才被捞起。
    # 写文件信号（与 cancel_run_request 同构），daemon 主循环 1s 粒度拾取即派发；
    # 信号冲突（上一信号未消费）不阻塞清空本身，daemon 拾取时对新 spec 一并生效。
    if normalized is None:
        _write_scheduling_kick_signal(proot, spec)
    return {"ok": True, "found": True, "start_after": normalized}


# ── per-spec 实现尝试预算覆盖（add-spec-status-modal-budget D3）──────────────

def set_spec_budget(project_root, spec: str, budget) -> dict:
    """设置/清除 SPEC 的实现尝试预算覆盖（impl_run_budget_override）。

    budget 取值：
    - None：清除覆盖（属性置 null，恢复跟随全局 agents.impl_run_budget）；
    - 1-10 整数：写入 per-spec 覆盖值（API 层已校验 isinstance(int) and not isinstance(bool)）；
    - 其余：{invalid: True}（拒绝写入，STATE.md 不变）。

    校验：
    - spec 不在 STATE.md → {found: False}
    - 终态（done/pushed）→ {terminal: True}（终态修改预算无意义）
    - 非法值 → {invalid: True}
    - 成功 → {ok: True, budget: <1-10 整数或 None>}
    写入经 StateMachine.update_spec（flock + 原子 rename，与 daemon 并发写安全）。

    边界（add-spec-status-modal-budget D3）：本函数只写覆盖属性
    ``impl_run_budget_override``，MUST NOT 触碰 ``_impl_run_budget_used``
    已用计数——已用次数归对账组件 _reconcile_impl_budget 管辖，本能力只改预算上限。
    """
    proot = Path(project_root)
    specs = parse_state(proot)
    if spec not in specs:
        return {"ok": False, "found": False, "budget": None,
                "error": f"spec not found: {spec}"}
    entry = specs[spec]
    if entry.get("status") in ("done", "pushed"):
        return {"ok": False, "found": True, "terminal": True, "budget": None,
                "error": f"终态 spec（{entry.get('status')}）不可设置预算覆盖"}
    # null 清除
    if budget is None:
        from core.state_machine import StateMachine
        sm = StateMachine(proot / ".fenix" / "STATE.md", None)
        sm.update_spec(spec, {"impl_run_budget_override": None})
        return {"ok": True, "found": True, "budget": None}
    # 非法值校验（int，非 bool，1-10）
    if isinstance(budget, bool) or not isinstance(budget, int):
        return {"ok": False, "found": True, "budget": None, "invalid": True,
                "error": "budget must be an integer between 1 and 10 (or null to clear)"}
    if budget < 1 or budget > 10:
        return {"ok": False, "found": True, "budget": None, "invalid": True,
                "error": "budget must be an integer between 1 and 10 (or null to clear)"}
    from core.state_machine import StateMachine
    sm = StateMachine(proot / ".fenix" / "STATE.md", None)
    sm.update_spec(spec, {"impl_run_budget_override": budget})
    return {"ok": True, "found": True, "budget": budget}


# ── 冻结配置 frozen_until（add-spec-scheduling-controls D5） ─────────

def configure_spec_freeze(project_root, spec: str, mode: str, until=None) -> dict:
    """冻结管理配置：永久冻结 ↔ 定时解冻 ↔ 立即解冻。

    - mode=permanent：清 frozen_until（保持冻结态，永久人工解冻）
    - mode=scheduled：写 frozen_until（ISO8601 校验；已过去 → 立即解冻，
      等价到期，不残留字段）
    - mode=unfreeze：立即解冻（复用官方解冻，status 传解析出的原状态）
    - spec 必须处于冻结态（is_spec_frozen），否则拒绝——保证 frozen_until
      只存在于冻结态 spec 上（spec scheduled-spec-unfreeze 字段契约）。
    - 非 scheduled 的 until 参数忽略；非法 mode → {invalid: True}。

    写入经 StateMachine（flock + 原子 rename）：frozen_until 更新不带 status
    键，不触发冻结保护剥离；带 status 的解冻一律走 unfreeze_spec 官方通道。
    """
    from core.state_machine import StateMachine, parse_utc

    proot = Path(project_root)
    specs = parse_state(proot)
    if spec not in specs:
        return {"ok": False, "found": False, "error": f"spec not found: {spec}"}
    entry = specs[spec]
    if not is_spec_frozen(entry):
        return {"ok": False, "found": True,
                "error": "spec 未处于冻结态（冻结管理仅对冻结 spec 生效）"}
    sm = StateMachine(proot / ".fenix" / "STATE.md", None)
    if mode == "unfreeze":
        orig = parse_orig_status(entry.get("error"))
        sm.unfreeze_spec(spec, status=orig)
        return {"ok": True, "found": True, "mode": "unfreeze",
                "unfrozen": True, "frozen_until": None}
    if mode == "permanent":
        sm.update_spec(spec, {"frozen_until": None})
        return {"ok": True, "found": True, "mode": "permanent",
                "frozen_until": None}
    if mode == "scheduled":
        dt = parse_utc(until)
        if dt is None:
            return {"ok": False, "found": True, "invalid": True,
                    "error": f"frozen_until 非法 ISO8601: {until!r}"}
        normalized = dt.isoformat()
        if dt <= datetime.now(timezone.utc):
            # 已过去 → 立即解冻（等价到期，不留待下一轮 tick/扫描）
            orig = parse_orig_status(entry.get("error"))
            sm.unfreeze_spec(spec, status=orig)
            return {"ok": True, "found": True, "mode": "scheduled",
                    "unfrozen": True, "frozen_until": normalized}
        sm.update_spec(spec, {"frozen_until": normalized})
        return {"ok": True, "found": True, "mode": "scheduled",
                "frozen_until": normalized}
    return {"ok": False, "found": True, "invalid": True,
            "error": f"未知冻结模式: {mode!r}"}


# ── SPEC 文档读取（proposal.md / design.md，add-spec-doc-buttons） ──

# kebab-case：小写字母/数字开头，仅含小写字母/数字/连字符（防御路径穿越）
_SPEC_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
# doc 白名单：仅允许读取这些核心设计文档（tasks.md 与 proposal.md 同目录）
_SPEC_DOC_WHITELIST = ("proposal", "design", "tasks", "verification", "scenarios")


def resolve_spec_dir(project_root, spec) -> Path | None:
    """解析 SPEC 目录：活跃优先，归档回退（fix-archived-spec-doc-readback D1）。

    1. spec 不匹配 ``_SPEC_NAME_RE`` → 返回 None（kebab-case 白名单天然排除
       ``..``/``/``，此处校验同时强化 parse_tasks 的健壮性）
    2. ``spec/changes/<spec>`` 为目录 → 返回活跃目录（活跃优先，既有行为不变）
    3. 否则遍历 ``spec/archive/``，目录名匹配日期前缀 + 可选冲突数字后缀
       （``^\\d{4}-\\d{2}-\\d{2}-{re.escape(spec)}(-\\d+)*$``；``re.escape``
       防 spec 名含 ``-`` 引发歧义），命中多个取 ``sorted()[-1]``
       （字典序最大 = 日期最新/后缀最大，与写入端冲突追加序一致）
    4. 无命中 → None
    """
    if not isinstance(spec, str) or not _SPEC_NAME_RE.match(spec):
        return None
    active = Path(project_root) / "spec" / "changes" / spec
    if active.is_dir():
        return active
    archive_root = Path(project_root) / "spec" / "archive"
    if not archive_root.is_dir():
        return None
    pattern = re.compile(r"^\d{4}-\d{2}-\d{2}-" + re.escape(spec) + r"(-\d+)*$")
    matches = [d for d in archive_root.iterdir()
               if d.is_dir() and pattern.match(d.name)]
    if not matches:
        return None
    return sorted(matches)[-1]


class InvalidSpecName(ValueError):
    """spec 名称非法（非 kebab-case 或含路径穿越）。"""


class InvalidSpecDoc(ValueError):
    """doc 参数非法（不在 {proposal, design, tasks} 白名单）。"""


class InvalidPriority(ValueError):
    """优先级非法（非 1-9 整数）。"""


def get_spec_doc(project_root, spec: str, doc: str) -> dict:
    """读取 SPEC 的 proposal.md / design.md / tasks.md 原文。

    Args:
        project_root: 项目根目录
        spec: SPEC 名称（须 kebab-case）
        doc: 文档类型，"proposal" / "design" / "tasks" / "verification"（验证报告）/ "scenarios"（测试场景清单汇总）

    Returns:
        {"found": bool, "content": str}
        - 文件存在：found=True, content=文件原文
        - 文件不存在：found=False, content=""

    Raises:
        InvalidSpecName: spec 非 kebab-case（含可能的路径穿越片段）
        InvalidSpecDoc: doc 不在白名单
    """
    if not isinstance(spec, str) or not _SPEC_NAME_RE.match(spec):
        raise InvalidSpecName(spec)
    if doc not in _SPEC_DOC_WHITELIST:
        raise InvalidSpecDoc(doc)

    spec_dir = resolve_spec_dir(project_root, spec)
    if spec_dir is None:
        # spec 合法但活跃/归档目录均不存在 → 与原有"目录不存在"行为一致
        return {"found": False, "content": ""}
    if doc == "verification":
        # 验证报告：verification-report.md（可能尚未生成 → found=False）
        target = (spec_dir / "verification-report.md").resolve()
    elif doc == "scenarios":
        # 测试场景清单：specs/<capability>/spec.md 的汇总拼接
        return _read_spec_scenarios(spec_dir / "specs")
    else:
        target = (spec_dir / f"{doc}.md").resolve()
    # 防御性校验：解析后必须仍位于该 SPEC 目录内（活跃/归档回退同样生效），
    # 杜绝任何 `..` 拼接越界
    if not target.is_relative_to(spec_dir.resolve()):
        raise InvalidSpecName(spec)
    if not target.is_file():
        return {"found": False, "content": ""}
    try:
        content = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {"found": False, "content": ""}
    return {"found": True, "content": content}


def _read_spec_scenarios(specs_dir: Path) -> dict:
    """汇总 change 的 specs/<capability>/spec.md 为测试场景清单（markdown 拼接）。

    每个 capability 以 `# <capability-name>` 一级标题分隔，场景原文保持不变。
    """
    if not specs_dir.is_dir():
        return {"found": False, "content": ""}
    parts = []
    try:
        for cap_dir in sorted(specs_dir.iterdir()):
            f = cap_dir / "spec.md"
            if cap_dir.is_dir() and f.is_file():
                try:
                    content = f.read_text(encoding="utf-8").strip()
                except (OSError, UnicodeDecodeError):
                    continue
                if content:
                    parts.append(f"# {cap_dir.name}\n\n{content}")
    except OSError:
        pass
    if not parts:
        return {"found": False, "content": ""}
    return {"found": True, "content": "\n\n---\n\n".join(parts)}


def clear_spec_error(project_root, spec: str) -> dict:
    """清除 SPEC 的 error 字段（置空并原子写回 STATE.md）。

    校验 spec 须存在于项目 STATE.md（不存在返回 {found: False}），再实例化
    StateMachine 调用 update_spec(spec, {"error": None})——复用其 flock + 原子
    rename 写回，与 daemon 并发写安全。不影响 status/priority 等其它字段；
    error 已为 null 时仍为成功（幂等）。

    Args:
        project_root: 项目根目录
        spec: SPEC 名称（须 kebab-case，且已在 STATE.md 注册）

    Returns:
        {"found": bool}  — found=True 表示已清除（含本就为空），False 表示 spec 不存在
    """
    proot = Path(project_root)
    specs = parse_state(proot)
    if spec not in specs:
        return {"found": False}
    from core.state_machine import StateMachine
    sm = StateMachine(proot / ".fenix" / "STATE.md")
    sm.update_spec(spec, {"error": None})
    return {"found": True}


def set_spec_priority(project_root, spec: str, priority) -> dict:
    """设置 SPEC 的 priority 字段（1-9，P1 最高）并原子写回 STATE.md。

    校验优先级须为 1-9 整数（含可转 int 的 str，如 "2"）；校验失败抛
    InvalidPriority。spec 须存在于项目 STATE.md，不存在返回 {found: False}。
    成功后复用 StateMachine.update_spec（flock + 原子 rename 写回），
    同时刷新 updated 时间戳，并返回写入后的 priority。

    Returns:
        {"found": bool, "priority": int}  — found=False 表示 spec 不在 STATE.md
    Raises:
        InvalidPriority: priority 不在 1-9 或不可转为整数
    """
    # 1-9 整数校验（兼容可被 int() 消费的字符串）
    try:
        p = int(priority)
    except (TypeError, ValueError):
        raise InvalidPriority(priority)
    if p < 1 or p > 9:
        raise InvalidPriority(priority)

    proot = Path(project_root)
    specs = parse_state(proot)
    if spec not in specs:
        return {"found": False}

    from core.state_machine import StateMachine
    sm = StateMachine(proot / ".fenix" / "STATE.md")
    sm.update_spec(spec, {"priority": p})
    return {"found": True, "priority": p}


def soft_delete_spec(project_root, spec: str) -> dict:
    """软删除 SPEC：STATE.md 移除条目 + spec/changes/<name>/ 移入 archive。

    两步任一失败则尽量回滚以保持两端数据一致，由调用方依据返回码处理：
    - STATE.md 不含该 spec → {found: False}（幂等，不发任何文件操作）
    - 运行中检测：runs 目录该 spec 有 mtime 在最近 120 秒内的运行产物 →
      {running: True, error: "spec 有进行中的运行"}（409 拒绝，不改数据）
    - 正常：remove_spec 原子剔除条目；目录若存在则 shutil.move 到
      spec/archive/<name>-<Unix秒>/；目录缺失仅清状态（幂等）。
    - 归档同名冲突（极小概率）：在名字追加毫秒后缀重试，直至成功。

    Returns:
        {"found", "running", "archived": bool, "archive_path": str|null,
         "error": str|null}
    """
    proot = Path(project_root)
    specs = parse_state(proot)
    if spec not in specs:
        return {"found": False}

    # 运行中保护：runs 目录该 spec 的任意 run 文件 mtime < 120s → 拒绝
    runs_dir = proot / ".fenix" / "runs"
    protect_window = 120
    now = time.time()
    if runs_dir.is_dir():
        try:
            for p in runs_dir.glob(f"*{spec}*.jsonl"):
                try:
                    if now - p.stat().st_mtime < protect_window:
                        return {"found": True, "running": True,
                                "error": "spec 有进行中的运行"}
                except OSError:
                    continue
        except OSError:
            pass

    from core.state_machine import StateMachine
    sm = StateMachine(proot / ".fenix" / "STATE.md")

    # 1. 先移动目录（若失败，STATE.md 尚未改动，天然一致）
    changes_root = proot / "spec" / "changes"
    spec_dir = changes_root / spec
    # archive 与 changes 平级（spec/archive/），不嵌套在 changes/ 下
    archive_root = proot / "spec" / "archive"
    archived = False
    archive_path = None
    if spec_dir.is_dir():
        archive_root.mkdir(parents=True, exist_ok=True)
        ts = int(now)
        base_name = f"{spec}-{ts}"
        dest = archive_root / base_name
        # 同名冲突：追加毫秒后缀重试，避免 shutil.move 覆盖丢失数据
        if dest.exists():
            import datetime as _dt
            ms = _dt.datetime.now().strftime("%f")
            dest = archive_root / f"{base_name}-{ms}"
            # 极端极端情况仍冲突，再用递增序号兜底
            n = 1
            while dest.exists():
                dest = archive_root / f"{base_name}-{ms}-{n}"
                n += 1
        shutil.move(str(spec_dir), str(dest))
        archived = True
        archive_path = str(dest)

    # 2. 再原子剔除 STATE.md 条目
    sm.remove_spec(spec)
    result = {"found": True, "running": False, "archived": archived,
              "archive_path": archive_path, "error": None}
    # 归档自动提交：目录确实移动成功才提交（fail-open，见 core/archive_commit.py）
    if archived:
        cr = commit_archive_move(proot, spec, archive_path)
        result["committed"] = cr["committed"]
        if cr["warning"]:
            result["commit_warning"] = cr["warning"]
    return result


def is_spec_archived(project_root, spec_name: str) -> bool:
    """归档判定：STATE.md 有条目且活跃目录 `spec/changes/<name>/` 不存在。

    D1：归档的**唯一事实来源**是活跃目录存在性——不检测 archive/ 下具体路径
    形态（删除路径命名 `<name>-<Unix秒>` 不同、手动移动命名不可控），也不写
    STATE.md 标志。三条归档路径（界面 API / CLI skill / 手动 mv）产出相同可见性。
    """
    return not (Path(project_root) / "spec" / "changes" / spec_name).is_dir()


def archive_spec(project_root, spec_name: str) -> dict:
    """归档 SPEC：把 `spec/changes/<name>/` 移到 `spec/archive/YYYY-MM-DD-<name>/`。

    与 `bin/fenix_archive.py::archive_change` 相同的移动逻辑与命名规则
    （D2：不 import 脚本，函数级复用核心逻辑）；STATE.md 条目**原样保留**。
    终态校验在 API 层做（仅 done/pushed 可归档），本函数仍做防御性校验，
    供 daemon 自动归档（D4）与手动 API 两条路径复用同一入口。

    Returns:
        {"ok": bool, "found": bool, "from": str|null, "to": str|null, "error": str|null}
        - spec 不在 STATE.md → {"ok": False, "found": False, ...}
        - 非终态 → {"ok": False, "found": True, "error": "仅终态..."}
        - 活跃目录缺失（已归档）→ {"ok": False, "found": True, "error": "已归档"}
        - 目标已存在 → {"ok": False, "found": True, "error": "目标已存在"（不覆盖）}
        - 成功 → {"ok": True, "found": True, "from": 原路径, "to": 目标路径}
    """
    proot = Path(project_root)
    specs = parse_state(proot)
    if spec_name not in specs:
        return {"ok": False, "found": False, "from": None, "to": None,
                "error": f"spec not found: {spec_name}"}
    status = specs[spec_name].get("status")
    if status not in ("done", "pushed"):
        return {"ok": False, "found": True, "from": None, "to": None,
                "error": f"仅终态 spec（done/pushed）可归档，当前状态: {status}"}

    change_dir = proot / "spec" / "changes" / spec_name
    if not change_dir.is_dir():
        return {"ok": False, "found": True, "from": None, "to": None,
                "error": f"Spec '{spec_name}' 活跃目录已不存在（可能已归档）"}

    from datetime import date
    target = (
        proot / "spec" / "archive"
        / f"{date.today().isoformat()}-{spec_name}"
    )
    if target.exists():
        return {"ok": False, "found": True, "from": str(change_dir), "to": str(target),
                "error": f"归档目标已存在: {target} — 请改名或改日再归档，原目录不会被覆盖"}

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        moved = Path(shutil.move(str(change_dir), str(target)))
    except OSError as e:
        return {"ok": False, "found": True, "from": str(change_dir), "to": str(target),
                "error": f"归档移动失败: {e}"}
    result = {"ok": True, "found": True, "from": str(change_dir), "to": str(moved),
              "error": None}
    # 归档自动提交：移动成功立即入库（fail-open，见 core/archive_commit.py）
    cr = commit_archive_move(proot, spec_name, moved)
    result["committed"] = cr["committed"]
    if cr["warning"]:
        result["commit_warning"] = cr["warning"]
    return result


def auto_archive_check(project_root, config: dict,
                       logger=None) -> dict:
    """daemon 周期自动归档检查（D4）：遍历终态未归档 SPEC，超阈值按 updated 升序归档。

    设计 D4/D5：主循环每 300s 调用一次；threshold=0 或缺失时跳过。
    统计完成（done/pushed）且**活跃目录仍存在**（未归档）的 SPEC 数量，
    超过阈值时按 STATE.md `updated` 字段升序逐个归档（最久完成的先），
    直到数量 ≤ 阈值。单条失败（目标已存在等）跳过并记日志，不中断循环。

    Args:
        project_root: 项目根目录
        config: 有效配置 dict（由 ConfigLoader.resolve_config 解析）
        logger: Logger 实例（可选，用于记录归档动作；缺省 print 到 stderr）

    Returns:
        {"archived": int, "skipped": int, "target_count": int,
         "threshold": int, "total_terminal_unarchived": int}
    """
    from core.config import ConfigLoader
    threshold = ConfigLoader.effective_auto_archive_threshold(config)
    if threshold <= 0:
        return {"archived": 0, "skipped": 0, "target_count": 0,
                "threshold": threshold, "total_terminal_unarchived": 0}

    proot = Path(project_root)
    specs = parse_state(proot)
    TERMINAL = ("done", "pushed")

    # 统计终态 + 未归档（活跃目录仍存在）
    candidates = []
    for name, entry in specs.items():
        if entry.get("status") not in TERMINAL:
            continue
        if not (proot / "spec" / "changes" / name).is_dir():
            continue  # 已归档，不计入
        candidates.append((name, entry))

    total = len(candidates)
    if total <= threshold:
        return {"archived": 0, "skipped": 0, "target_count": 0,
                "threshold": threshold, "total_terminal_unarchived": total}

    # 按 updated 升序（最久完成的先归档）
    def _sort_key(item):
        updated = item[1].get("updated") or ""
        try:
            return updated  # ISO8601 字符串排序即时间排序
        except Exception:
            return ""
    candidates.sort(key=_sort_key)

    to_archive = total - threshold
    archived_count = 0
    skipped_count = 0
    for name, _entry in candidates[:to_archive]:
        result = archive_spec(proot, name)
        if result.get("ok"):
            archived_count += 1
            msg = f"自动归档: {name} → {result['to']}"
            if logger is not None:
                try:
                    logger.info("fenixd", msg)
                except Exception:
                    pass
            else:
                import sys
                print(f"[fenixd] {msg}", file=sys.stderr)
        else:
            skipped_count += 1
            msg = f"自动归档跳过 {name}: {result.get('error')}"
            if logger is not None:
                try:
                    logger.warning("fenixd", msg)
                except Exception:
                    pass
            else:
                import sys
                print(f"[fenixd] {msg}", file=sys.stderr)

    return {
        "archived": archived_count,
        "skipped": skipped_count,
        "target_count": threshold,
        "threshold": threshold,
        "total_terminal_unarchived": total,
    }


# ── 基础解析（源自 bin/fenix_dashboard.py，TUI / Web 共用） ────────────

def parse_state(project_root) -> dict:
    """解析项目 STATE.md，返回 {spec_name: {key: value}}。"""
    state_path = Path(project_root) / ".fenix" / "STATE.md"
    if not state_path.exists():
        return {}
    specs = {}
    current_name = None
    current_entry = {}
    try:
        for line in state_path.read_text(encoding="utf-8").split("\n"):
            m = re.match(r"^###\s+(.+)$", line)
            if m:
                if current_name and current_entry and "status" in current_entry:
                    specs[current_name] = current_entry
                current_name = m.group(1).strip()
                current_entry = {}
                continue
            m = re.match(r"^-\s+([a-z_]+):\s*(.*)$", line)
            if m and current_name:
                key = m.group(1)
                val = m.group(2).strip()
                if key == "priority":
                    try:
                        val = int(val)
                    except ValueError:
                        val = 999
                elif key == "impl_run_budget_override":
                    try:
                        val = int(val)
                    except ValueError:
                        val = None
                elif val.lower() in ("null", "none", ""):
                    val = None
                current_entry[key] = val
        if current_name and current_entry and "status" in current_entry:
            specs[current_name] = current_entry
    except (OSError, UnicodeDecodeError):
        pass
    return specs


def find_implementer_worktree(project_root, spec_name):
    """Find the newest implementer worktree for a SPEC, or None."""
    wt_dir = Path(project_root) / ".claude" / "worktrees"
    if not wt_dir.is_dir():
        return None
    prefix = f"impl-{spec_name}-"
    candidates = []
    for d in wt_dir.iterdir():
        if d.is_dir() and d.name.startswith(prefix):
            try:
                candidates.append((d.stat().st_mtime, d))
            except OSError:
                pass
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


# ── 实时任务完成状态叠加（run 记录 → tasks.md） ───────────────────
#
# 背景：implementer Agent 用 Claude 会话内 TaskCreate/TaskUpdate 工具实时汇报
# 任务完成（见 .fenix/runs/impl-<spec>-*.jsonl 的 assistant tool_use），从不编辑
# tasks.md，导致 Dashboard 任务进度永远 0/N。这里从最新 impl run 产物解析实时
# 完成状态，叠加到 tasks.md 快照上（逐任务并集），使 Dashboard 实时反映进度。
_TASK_ID_RE = re.compile(r"Task\s+#?\s*(\d+\.\d+)")
# parse_run_task_done 的 memo 缓存：run 文件 O_APPEND 只增，mtime/size 不变即命中。
# 上限 64 项，超出整体清空，防止 append-only 文件每次追加换键导致无界增长。
_RUN_TASK_CACHE: dict = {}


def find_impl_run_file(project_root, spec_name) -> Path | None:
    """最新一次 impl-<spec>-*.jsonl 运行产物，或 None。

    运行中 STATE.md 的 implementer_run 字段为空，不能用它定位；
    按 mtime 取最新与 worktree 选择（find_implementer_worktree）一致。
    """
    runs_dir = Path(project_root) / ".fenix" / "runs"
    if not runs_dir.is_dir():
        return None
    candidates = []
    try:
        for p in runs_dir.glob(f"impl-{spec_name}-*.jsonl"):
            try:
                candidates.append((p.stat().st_mtime, p))
            except OSError:
                pass
    except OSError:
        return None
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def parse_run_task_done(run_file: Path) -> dict:
    """解析 impl run 产物的 harness 任务完成状态（容错：任何损坏都不抛异常）。

    该函数为 dashboard 实时叠加与 pm_engine 写侧回写共用的解析核心，
    避免两套正则漂移。详见 _parse_run_task_done 历史语义说明。

    TaskCreate 的 input.subject 内嵌 tasks.md id（如 "Task 1.1: ..."）；
    TaskUpdate 的 taskId 为 1 基创建序（tool_result 形如 "Task #1 created ..."）。

    Returns:
        {"done_ids": set[str],   # 已完成且已创建的 tasks.md id（如 {"1.1","2.3"}）
         "created_count": int,    # TaskCreate 次数（flat 回退对齐上限）
         "flat_done": set[int],   # 已完成任务的创建序下标（0-based，flat 回退用）
         "in_progress_ids": list[str]}  # 进行中任务 id（run-progress-current：
                    # 最近一次 TaskUpdate 仍为 in_progress 且未 completed；
                    # subject 无编号时回退 "#创建序"）
    """
    try:
        st = run_file.stat()
        key = (str(run_file), st.st_mtime_ns, st.st_size)
    except OSError:
        return {"done_ids": set(), "created_count": 0, "flat_done": set(),
                "in_progress_ids": []}
    cached = _RUN_TASK_CACHE.get(key)
    if cached is not None:
        return cached

    created_ordered: list = []  # 按创建序的 subject 提取 tasks.md id（无 id 记 None）
    completed_idx: set = set()  # TaskUpdate completed 的 taskId - 1
    last_update_status: dict = {}  # taskId-1 → 最近一次 TaskUpdate status
    try:
        with run_file.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict) or entry.get("type") != "assistant":
                    continue
                for c in (entry.get("message") or {}).get("content") or []:
                    if not isinstance(c, dict) or c.get("type") != "tool_use":
                        continue
                    if c.get("name") == "TaskCreate":
                        m = _TASK_ID_RE.search(str((c.get("input") or {}).get("subject") or ""))
                        created_ordered.append(m.group(1) if m else None)
                    elif c.get("name") == "TaskUpdate":
                        inp = c.get("input") or {}
                        try:
                            n = int(str(inp.get("taskId")))  # 兼容 str/int
                        except (TypeError, ValueError):
                            continue
                        status = inp.get("status")
                        if status:
                            last_update_status[n - 1] = str(status)
                        if status == "completed":
                            completed_idx.add(n - 1)
    except OSError:
        return {"done_ids": set(), "created_count": 0, "flat_done": set(),
                "in_progress_ids": []}

    created_count = len(created_ordered)
    done_ids = set()
    for idx in completed_idx:
        if 0 <= idx < created_count and created_ordered[idx]:
            done_ids.add(created_ordered[idx])
    flat_done = {i for i in completed_idx if 0 <= i < created_count}

    # 进行中任务（run-progress-current）：最近一次 TaskUpdate 仍为 in_progress
    # 且未 completed 的创建序下标 → 展示用 id（subject 无编号时回退 "#创建序"）
    in_progress_idx = {
        idx for idx, s in last_update_status.items()
        if s == "in_progress" and 0 <= idx < created_count
    } - completed_idx
    in_progress_ids = [
        created_ordered[idx] if created_ordered[idx] else f"#{idx + 1}"
        for idx in sorted(in_progress_idx)
    ]

    result = {"done_ids": done_ids, "created_count": created_count, "flat_done": flat_done,
              "in_progress_ids": in_progress_ids}
    if len(_RUN_TASK_CACHE) > 64:
        _RUN_TASK_CACHE.clear()
    _RUN_TASK_CACHE[key] = result
    return result


# 向后兼容别名：旧调用点（tests / 历史引用）仍可用下划线前缀名。
_parse_run_task_done = parse_run_task_done
_find_impl_run_file = find_impl_run_file


# 实时叠加生效的生命周期状态（含实现完成后的验证期）。ready/drafted 不叠加，
# 避免重试过渡期旧 run 的完成数误导。
_LIVE_OVERLAY_STATUSES = {"implementing", "implemented", "testing", "bug-found"}


def _should_overlay(spec_status: str, has_uncompleted: bool) -> bool:
    """是否需要用 run 记录实时完成状态叠加 tasks.md 快照。"""
    if spec_status in _LIVE_OVERLAY_STATUSES:
        return True
    # done/pushed：仅当 tasks.md 仍有未勾选任务时叠加（覆盖实现者从不勾 tasks.md 的现状）
    return spec_status in ("done", "pushed") and has_uncompleted


def parse_tasks(project_root, spec_name, spec_status: str = "", *, live: bool = True) -> list:
    """解析 tasks.md 为分组任务结构：[{title, tasks:[{id,desc,done}], done, total}]。

    For implementing SPECs, reads from the active implementer worktree first.
    live=True 时按 _should_overlay 叠加最新 impl run 的实时完成状态（并集）。
    """
    # 活跃优先、归档回退（fix-archived-spec-doc-readback D3）；归档 SPEC 的
    # tasks.md 从归档目录读取，详情页任务卡片不再空白
    spec_dir = resolve_spec_dir(project_root, spec_name)
    tasks_path = (
        spec_dir or Path(project_root) / "spec" / "changes" / spec_name
    ) / "tasks.md"
    if spec_status == "implementing":
        wt = find_implementer_worktree(project_root, spec_name)
        if wt:
            wt_tasks = wt / "spec" / "changes" / spec_name / "tasks.md"
            if wt_tasks.exists():
                tasks_path = wt_tasks
    if not tasks_path.exists():
        return []
    groups = []
    current_group = None
    try:
        for line in tasks_path.read_text(encoding="utf-8").split("\n"):
            # 分组标题（点号可选双历史格式：`## 1. 标题` / `## 1 标题`）。
            # 与 bin/fenix_process.py:parse_tasks、core/deliverables.py:
            # lint_tasks_parseable 同源正则（task-track D1），三处必须一致。
            m = re.match(r"^##\s+\d+\.?\s+(.+)$", line)
            if m:
                current_group = {"title": m.group(1), "tasks": [], "done": 0, "total": 0}
                groups.append(current_group)
                continue
            m = re.match(r"^- \[(x| )\] (\d+\.\d+) (.+)$", line)
            if m and current_group is not None:
                is_done = m.group(1) == "x"
                current_group["tasks"].append({
                    "done": is_done,
                    "id": m.group(2),
                    "desc": m.group(3).strip(),
                })
                if is_done:
                    current_group["done"] += 1
                current_group["total"] += 1
    except (OSError, UnicodeDecodeError):
        pass
    if not groups:
        return groups
    # 实时叠加：最新 impl run 的 TaskUpdate 完成状态与 tasks.md 勾选取并集。
    # 主路径按 tasks.md id 精确对齐；subject 无 id（未来 harness 变体）时回退扁平下标。
    if live and _should_overlay(
        spec_status, any(not t["done"] for g in groups for t in g["tasks"])
    ):
        run_file = _find_impl_run_file(project_root, spec_name)
        if run_file is not None:
            rd = _parse_run_task_done(run_file)
            overlaid = False
            if rd["done_ids"]:
                by_id = {t["id"]: t for g in groups for t in g["tasks"]}
                for tid in rd["done_ids"]:
                    t = by_id.get(tid)
                    if t is not None:
                        t["done"] = True
                        overlaid = True
            elif rd["flat_done"]:
                flat = [t for g in groups for t in g["tasks"]]
                bound = min(rd["created_count"], len(flat))
                for i in rd["flat_done"]:
                    if 0 <= i < bound:
                        flat[i]["done"] = True
                        overlaid = True
            if overlaid:
                # 重算分组计数（前端分组头依赖 g.done / g.total）
                for g in groups:
                    g["done"] = sum(1 for t in g["tasks"] if t["done"])
                    g["total"] = len(g["tasks"])
    return groups


def task_progress(project_root, spec_name, spec_status: str = ""):
    """返回 (done, total)，无任务时为 (0, 0)。"""
    groups = parse_tasks(project_root, spec_name, spec_status)
    done = sum(g["done"] for g in groups)
    total = sum(g["total"] for g in groups)
    return done, total


def tasks_note(project_root, spec_name, spec_status: str = ""):
    """tasks.md 空解析显式提示（task-track R3）。

    tasks.md 存在但 ``parse_tasks`` 返回空列表 → 返回提示文本（前端据此在
    任务清单 Card 显示 warning 空态，与「无 tasks.md 文件」的 secondary
    空态可区分）；否则返回 ``None``。与 ``tasks`` 字段共用同一次解析语义
    （implementing 状态同样优先读 worktree 内的 tasks.md）。
    """
    spec_dir = resolve_spec_dir(project_root, spec_name)
    tasks_path = (
        spec_dir or Path(project_root) / "spec" / "changes" / spec_name
    ) / "tasks.md"
    if not tasks_path.exists():
        return None
    if parse_tasks(project_root, spec_name, spec_status):
        return None
    return "tasks.md 存在但未解析出任务分组（分组格式不匹配或文件为空）"


def run_task_progress(project_root, spec_name) -> dict:
    """最新 impl run 的 harness 任务完成度（run-progress-observability D3）。

    从最新 impl run 产物用 parse_run_task_done 解析：done = TaskUpdate completed
    的 taskId 去重数（flat_done），total = created_count，current = 进行中任务
    id 列表（in_progress 且未 completed，run-progress-current；run 已终态时
    恒空——终态 run 没有「进行中」，残留状态不得外显）。**不依赖 TaskCreate
    subject 是否内嵌 tasks.md 编号**——这正是它作为 tasks.md 快照失效时兜底
    展示的资本。无 run / 解析失败为 {"done": 0, "total": 0, "current": []}。
    """
    run_file = find_impl_run_file(project_root, spec_name)
    if run_file is None:
        return {"done": 0, "total": 0, "current": []}
    rd = parse_run_task_done(run_file)
    # run-progress-current 终态闸门：终态 run（result/interrupted/cancelled/error）
    # 没有「进行中」任务。current 是实时线索，仅对仍在产事件的 run 有意义；
    # 被杀/清扫补写终态的 run 残留 in_progress 状态不得外显（pushed spec 显示
    # 「进行中 1.2」事故：清扫追加终态行抬高 mtime 使 find_impl_run_file 选中
    # 僵尸文件，残留 in_progress 外显到已推送 SPEC）。
    current = list(rd.get("in_progress_ids") or [])
    if current and classify_run(_read_run_lines(run_file, max_lines=3)) not in ("running", "empty"):
        current = []
    return {
        "done": len(rd.get("flat_done") or set()),
        "total": int(rd.get("created_count") or 0),
        "current": current,
    }


def count_scenarios(project_root, spec_name) -> int:
    """统计 SPEC 各 spec.md 中 Scenario 数量。"""
    specs_dir = Path(project_root) / "spec" / "changes" / spec_name / "specs"
    if not specs_dir.is_dir():
        return 0
    count = 0
    try:
        for sf in specs_dir.rglob("*.md"):
            for line in sf.read_text(encoding="utf-8").split("\n"):
                if re.match(r"^####\s+Scenario:", line):
                    count += 1
    except (OSError, UnicodeDecodeError):
        pass
    return count


def count_generated_scenarios(project_root, spec_name) -> int:
    """统计 planner 已补全的场景数（verification-phase-progress）。

    读 .fenix/verify-progress/<spec>/test_scenarios.json（planner-plan 出题
    产物，分批整体重写）；缺失/损坏/非列表以 0 计——出题进度是纯展示信号，
    任何解析异常都不阻断摘要（fail-open，与 count_scenarios 同风格）。

    口径=「已补全场景数」（steps/assertions 非空才算）：分批落盘强制骨架
    先行（fix-planner-scenarios-batching-hook）后，骨架含全部 id 但无肉，
    若按条数计则骨架落盘瞬间出题条 0→N/N 一次跳；数带肉场景使出题条
    随每 1/3 重写真实爬升。
    """
    pf = (
        Path(project_root)
        / ".fenix"
        / "verify-progress"
        / spec_name
        / "test_scenarios.json"
    )
    if not pf.exists():
        return 0
    try:
        data = json.loads(pf.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return 0
    if isinstance(data, dict):
        data = data.get("scenarios")
    if not isinstance(data, list):
        return 0
    return sum(
        1 for sc in data
        if isinstance(sc, dict) and (sc.get("steps") or sc.get("assertions"))
    )


def spec_generation_progress(project_root, spec_name, entry, vp=None) -> dict | None:
    """出题进度（verification-phase-progress）：场景生成阶段的 N/M 进度。

    场景生成（planner-plan）是验证链主要耗时而后续执行很快——testing 且执行
    进度未产生（verify_total=0）时返回 {"done": 已落盘场景数, "total": spec
    场景目标数}；其余状态 / 执行已开始 / 尚无场景落盘均返回 None。

    total 可为 0（spec 无 `#### Scenario:` 块而出题有多形态扩展），前端对
    total=0 只展示计数不出百分比。done>0 才返回（0 场景无进度可言）。
    """
    if entry.get("status") != "testing":
        return None
    if vp is None:
        vp = parse_verify_progress(project_root, spec_name)
    if vp.get("total", 0):
        return None
    done = count_generated_scenarios(project_root, spec_name)
    if not done:
        return None
    return {"done": done, "total": count_scenarios(project_root, spec_name)}


# ── fenixd 日志块偏移索引（dashboard-log-offset-index D5） ─────

# 每 64KB 一块；查询窗口只读尾部 ≤1MB（16 块），不再全量扫描日志文件。
LOG_INDEX_BLOCK = 64 * 1024
LOG_INDEX_TAIL_WINDOW = 1 * 1024 * 1024
# 进程内重建计数（测试断言用：追加热更新 0 次重建、损坏容错恰好 1 次）。
_LOG_INDEX_REBUILDS = {"count": 0}


def _log_index_path(proot: Path) -> Path:
    """日志块偏移索引路径：.fenix/logs/.idx/fenixd.log.offsets.json。"""
    return proot / ".fenix" / "logs" / ".idx" / "fenixd.log.offsets.json"


def _build_log_block_index(log_path: Path, size: int) -> dict:
    """全量扫描日志一次，构建 {size, offsets}。

    offsets[i] = 第 i 个 64KB 块内首行字节偏移；读取窗口定位到块 i 后从该偏移
    起读即可获得完整行（落在块边界中间的行被包含进下一块起点）。
    """
    offsets = [0]
    try:
        with log_path.open("rb") as f:
            nblocks = size // LOG_INDEX_BLOCK
            for i in range(1, nblocks + 1):
                boundary = i * LOG_INDEX_BLOCK
                if boundary >= size:
                    break
                f.seek(boundary)
                chunk = f.read(LOG_INDEX_BLOCK)
                nl = chunk.find(b"\n")
                if nl == -1:
                    offsets.append(boundary)
                else:
                    offsets.append(boundary + nl + 1)
    except OSError:
        return {"size": size, "offsets": [0]}
    # 保证末尾（不足一块的尾部 / 恰好整块）也有条目指向尾部起始行
    if offsets and offsets[-1] >= size:
        offsets[-1] = max(0, size - 1)
    return {"size": size, "offsets": offsets}


def _write_log_index(proot: Path, idx: dict):
    """索引落盘（.idx/ + 原子 rename），失败静默（查询不阻断）。"""
    idx_path = _log_index_path(proot)
    try:
        idx_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = idx_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")
        os.replace(str(tmp), str(idx_path))
    except OSError:
        pass


def _update_log_block_index(log_path: Path, size: int, idx: dict) -> dict:
    """追加热更新：仅补扫 size 增长的新块，不重建旧块。返回新索引。

    日志只增（O_APPEND / RotatingFileHandler 追加），旧块偏移保持不变；
    size 缩小（轮转/截断）时整体重建。
    """
    old_size = idx.get("size", 0)
    if size < old_size:
        fresh = _build_log_block_index(log_path, size)
        _LOG_INDEX_REBUILDS["count"] += 1
        return fresh
    if size <= old_size:
        return idx
    offsets = list(idx.get("offsets", [0]))
    old_blocks = old_size // LOG_INDEX_BLOCK
    try:
        with log_path.open("rb") as f:
            nblocks = size // LOG_INDEX_BLOCK
            for i in range(old_blocks, nblocks + 1):
                boundary = i * LOG_INDEX_BLOCK
                if boundary >= size:
                    break
                if boundary < old_size:
                    continue  # 旧块已覆盖
                # 新增首块起点恰为旧 size（JSONL 行边界）：直接指到 boundary，
                # 避免 seek-forward 把新增首行整行跳过。
                if boundary == old_size:
                    offsets.append(boundary)
                    continue
                f.seek(boundary)
                chunk = f.read(LOG_INDEX_BLOCK)
                nl = chunk.find(b"\n")
                if nl == -1:
                    offsets.append(boundary)
                else:
                    offsets.append(boundary + nl + 1)
    except OSError:
        return idx
    return {"size": size, "offsets": offsets}


def _load_log_index(proot: Path, log_path: Path) -> dict:
    """读取/重建日志块偏移索引，返回 {"size", "offsets"}。

    缺失或日志文件 size 不匹配（轮转/截断）→ 重建一次（≤1 次全量扫描）并继续；
    匹配则热更新（追加场景 0 次重建）。
    """
    try:
        size = log_path.stat().st_size
    except OSError:
        return {"size": 0, "offsets": [0]}
    idx_path = _log_index_path(proot)
    idx = None
    try:
        if idx_path.exists():
            data = json.loads(idx_path.read_text(encoding="utf-8"))
            if (isinstance(data, dict) and isinstance(data.get("offsets"), list)
                    and isinstance(data.get("size"), int)):
                idx = data
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        idx = None
    if idx is None or idx.get("size", 0) > size:
        # 索引缺失 / 损坏 / 日志被截断（size 缩小）→ 重建一次
        _LOG_INDEX_REBUILDS["count"] += 1
        idx = _build_log_block_index(log_path, size)
        _write_log_index(proot, idx)
        return idx
    # size 相等 → 直接返回；size 增长（append-only）→ 热更新补扫，不重建
    fresh = _update_log_block_index(log_path, size, idx)
    if fresh.get("size") != idx.get("size") or fresh is not idx:
        _write_log_index(proot, fresh)
    return fresh


def _read_log_tail_window(proot: Path, log_path: Path, max_bytes=LOG_INDEX_TAIL_WINDOW) -> bytes:
    """读日志尾部窗口（≤ max_bytes，对齐到块边界保证完整行）。"""
    idx = _load_log_index(proot, log_path)
    size = idx.get("size", 0)
    if size == 0:
        return b""
    offsets = idx.get("offsets", [0]) or [0]
    target = max(0, size - max_bytes)
    bi = min(target // LOG_INDEX_BLOCK, len(offsets) - 1)
    start = offsets[bi] if bi >= 0 else 0
    start = max(0, min(start, size))
    try:
        with log_path.open("rb") as f:
            f.seek(start)
            return f.read(size - start)
    except OSError:
        return b""


def _iter_tail_log_entries(proot: Path, lf: Path, cutoff: str = "") -> list:
    """从日志尾部窗口逐行解析 JSON 条目（跳过非 JSON/空行）。"""
    raw = _read_log_tail_window(proot, lf)
    out = []
    for line in raw.decode("utf-8", errors="replace").split("\n"):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if cutoff and entry.get("timestamp", "") < cutoff:
            continue
        out.append(entry)
    return out


def _norm_utc_iso(ts: str) -> str:
    """时间戳归一为 ...Z 形态（+00:00 → Z），供同格式字典序比较。

    日志时间戳统一 UTC 以 "...Z" 落盘（core/logger.py），STATE.md 的 created 是
    "...+00:00" 形态；同构 ISO 字符串字典序即时间序（微秒位数差异的偏差远小于
    块粒度，不影响定位）。
    """
    return ts.replace("+00:00", "Z")


def _read_log_window_from(proot: Path, log_path: Path, start_ts: str) -> bytes:
    """从时间戳 start_ts 对应位置读到文件尾（块偏移索引二分定位起点）。

    spec 时间轴的读取窗口：尾部 1MB 尾窗对跨窗口存活的长周期 spec 会静默截断
    早期事件（fenixd.log 无轮转持续增长后，早于尾窗的派发/报错/重派全部丢失）。
    改为按 spec created 锚定：日志 append-only 且时间戳单调，二分最后一个
    首行时间戳 < start_ts 的块，从该块读至文件尾（锚点前的残留行由调用方
    spec 名过滤兜底，属无害冗余）。start_ts 为空 → 全文件读取（正确性优先，
    仅低频 REST 详情页触达）；块首行探测失败 → 保守回退全文件。
    """
    idx = _load_log_index(proot, log_path)
    size = idx.get("size", 0)
    offsets = idx.get("offsets", [0]) or [0]
    if size == 0:
        return b""

    def _read(start: int) -> bytes:
        try:
            with log_path.open("rb") as f:
                f.seek(start)
                return f.read(size - start)
        except OSError:
            return b""

    if not start_ts:
        return _read(0)
    target = _norm_utc_iso(start_ts)

    def _first_ts(offset: int) -> "str | None":
        try:
            with log_path.open("rb") as f:
                f.seek(offset)
                chunk = f.read(LOG_INDEX_BLOCK)
            line = chunk.split(b"\n", 1)[0].decode("utf-8", errors="replace")
            return _norm_utc_iso(json.loads(line).get("timestamp", "")) or None
        except (OSError, json.JSONDecodeError, ValueError,
                UnicodeDecodeError, AttributeError):
            return None

    ts0 = _first_ts(offsets[0])
    if ts0 is None or ts0 >= target:
        return _read(0)
    lo, hi = 0, len(offsets) - 1
    # 不变量：块 lo 的首行 ts < target；收敛到满足条件的最大块
    while lo < hi:
        mid = (lo + hi + 1) // 2
        ts_mid = _first_ts(offsets[mid])
        if ts_mid is None:
            return _read(0)
        if ts_mid < target:
            lo = mid
        else:
            hi = mid - 1
    return _read(offsets[lo])


def get_recent_events(project_root, minutes=10, limit=30) -> list:
    """读取最近 N 分钟的 fenixd 结构化日志事件。

    dashboard-log-offset-index D5：只读日志尾部 ≤1MB 窗口（块偏移索引定位），
    不再全量扫描日志文件；窗口外（早于尾部 1MB）的事件按截断语义不追溯。
    """
    logs_dir = Path(project_root) / ".fenix" / "logs"
    if not logs_dir.is_dir():
        return []
    log_files = sorted(logs_dir.glob("fenixd*.log"), reverse=True)
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    events = []
    for lf in log_files[:2]:
        try:
            events.extend(_iter_tail_log_entries(proot=Path(project_root), lf=lf, cutoff=cutoff))
        except (OSError, UnicodeDecodeError):
            continue
    return events[-limit:]


def record_project_event(project_root, component: str, message: str,
                         level: str = "INFO", context: dict | None = None) -> None:
    """向项目事件日志追加一条结构化 JSON 事件（dashboard 操作的活动记录）。

    与 daemon 的 Logger（core/logger.py) 同构：JSON 行写入 `.fenix/logs/fenixd.log`，
    供 `get_recent_events`（活动页）读取展示。服务器进程与 daemon 进程分开部署，
    无法共享 Logger 实例，故按同一文件格式直接追加；daemon 与 dashboard 文件句柄
    O_APPEND 追加互不覆盖（RotatingFileHandler 轮转时按文件名匹配新文件）。
    写日志失败（目录不可写等）静默忽略——活动事件属可观测性增强，不阻断业务操作。

    Args:
        project_root: 项目根目录
        component: 事件组件名（如 dashboard / fenixd）
        message: 事件内容（含 from/to 等归档动作描述）
        level: 日志级别（INFO 默认）
        context: 附加结构化上下文（可选，落为 JSON context 字段）
    """
    logs_dir = Path(project_root) / ".fenix" / "logs"
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "level": level,
            "component": component,
            "message": message,
        }
        if context:
            entry["context"] = context
        with (logs_dir / "fenixd.log").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except (OSError, UnicodeDecodeError):
        pass


# ── 验证产物（容错解析） ──────────────────────────────────────────

def parse_verify_progress(project_root, spec_name) -> dict:
    """解析 .fenix/verify-progress/<spec>.json；损坏/非对象以 error 字段标记。

    进度文件缺失时回退 fast-track 裁决结果文件（fix-verify-progress-fasttrack）：
    调 parse_run_result_scenarios 取 verification.scenarios 合成进度——total=场景数、
    done=含 status 条目数、current=终态文案「验证完成: N通过, M失败, K错误」
    （对齐 verify_engine 终态格式），并标记 source: "run-result" 区分来源
    （进度文件路径返回 source: "file"）。两者皆缺维持 exists: False 空态语义。
    """
    pf = Path(project_root) / ".fenix" / "verify-progress" / f"{spec_name}.json"
    if pf.exists():
        try:
            data = json.loads(pf.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return {"exists": True, "error": "corrupt", "total": 0, "done": 0, "current": ""}
            return {
                "exists": True,
                "total": int(data.get("total", 0) or 0),
                "done": int(data.get("done", 0) or 0),
                "current": data.get("current", "") or "",
                "step": data.get("step"),
                "error": data.get("error"),
                "source": "file",
            }
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            return {"exists": True, "error": "corrupt", "total": 0, "done": 0, "current": ""}
    # 进度文件缺失：fast-track 回退合成（场景为空维持空态，不抛异常）
    scenarios = parse_run_result_scenarios(project_root, spec_name)
    if not scenarios:
        return {"exists": False, "total": 0, "done": 0, "current": ""}
    passed = failed = errors = done = 0
    for sc in scenarios:
        status = sc.get("status")
        if not status:
            continue
        done += 1
        if status == "pass":
            passed += 1
        elif status in ("fail", "failed"):
            failed += 1
        elif status == "error":
            errors += 1
        # warning/exempt 豁免类不入三桶（与裁决链豁免语义一致）
    return {
        "exists": True,
        "total": len(scenarios),
        "done": done,
        "current": f"验证完成: {passed}通过, {failed}失败, {errors}错误",
        "source": "run-result",
    }


def parse_report(project_root, spec_name) -> dict:
    """解析 .fenix/verify-progress/<spec>/report.json（逐场景断言结果）。"""
    rp = Path(project_root) / ".fenix" / "verify-progress" / spec_name / "report.json"
    if not rp.exists():
        return {"exists": False}
    try:
        data = json.loads(rp.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"exists": True, "error": "corrupt"}
        return {"exists": True, **data}
    except (json.JSONDecodeError, OSError, TypeError):
        return {"exists": True, "error": "corrupt"}


def parse_test_scenarios(project_root, spec_name) -> list:
    """读取 .fenix/verify-progress/<spec>/test_scenarios.json（尽力解析）。"""
    sp = Path(project_root) / ".fenix" / "verify-progress" / spec_name / "test_scenarios.json"
    if not sp.exists():
        return []
    try:
        data = json.loads(sp.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, OSError, TypeError):
        return []


def parse_run_result_scenarios(project_root, spec_name) -> list:
    """读取裁决 .fenix-run-result.json 中的场景明细（report.json 缺失/无场景时兜底）。

    合成报告（verify_report.py 兜底）场景下 report.json 可能不存在，而逐场景明细
    只存在于 .fenix-run-result.json（verify-progress 优先，项目根回退且需 spec 匹配）。
    full 模式 tester 结果场景在顶层 ``scenarios``；fast-track 结果（fast_track_result.py
    schema）嵌套在 ``verification.scenarios``——顶层缺失时回退读嵌套键，否则
    fast-track spec 的 Dashboard「场景结果」页签恒空（数据在专属副本里并不缺）。
    返回场景 dict 列表（已归一化截图字段），不可得返回 []。
    """
    candidates = [
        Path(project_root) / ".fenix" / "verify-progress" / spec_name / ".fenix-run-result.json",
        Path(project_root) / ".fenix" / ".fenix-run-result.json",
    ]
    for idx, path in enumerate(candidates):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        # 项目根为共享文件：携带的 spec 与当前 spec 不符时视为其它 spec 残留忽略
        if idx == 1 and isinstance(data.get("spec"), str) and data["spec"] and data["spec"] != spec_name:
            continue
        scenarios = data.get("scenarios")
        if not isinstance(scenarios, list) or not scenarios:
            # fast-track 格式回退：场景嵌套在 verification.scenarios
            ver = data.get("verification")
            scenarios = ver.get("scenarios") if isinstance(ver, dict) else None
        if not isinstance(scenarios, list) or not scenarios:
            continue
        out = []
        for sc in scenarios:
            if not isinstance(sc, dict):
                continue
            norm = dict(sc)
            norm["screenshots"] = [
                os.path.basename(s) for s in sc.get("screenshots", [])
                if isinstance(s, str) and s.strip()
            ]
            out.append(norm)
        # 场景结果缺 kind（契约补 kind 前的存量 run-result）时按 scenario_id
        # 从出题定义 test_scenarios.json 映射补齐；定义同样缺 kind 的旧 spec
        # 维持缺失（前端按缺省 web 渲染）。fail-open：读取异常不影响主数据。
        if any(not sc.get("kind") for sc in out):
            kind_by_id = {}
            try:
                ts_path = (
                    Path(project_root) / ".fenix" / "verify-progress"
                    / spec_name / "test_scenarios.json"
                )
                ts_data = json.loads(ts_path.read_text(encoding="utf-8"))
                ts_scenarios = (
                    ts_data.get("scenarios") if isinstance(ts_data, dict) else ts_data
                )
                if isinstance(ts_scenarios, list):
                    kind_by_id = {
                        str(s.get("id") or s.get("scenario_id")): s.get("kind")
                        for s in ts_scenarios
                        if isinstance(s, dict) and s.get("kind")
                    }
            except (json.JSONDecodeError, OSError, AttributeError):
                kind_by_id = {}
            if kind_by_id:
                for sc in out:
                    if not sc.get("kind"):
                        k = kind_by_id.get(str(sc.get("scenario_id")))
                        if k:
                            sc["kind"] = k
        return out
    return []


def list_screenshots(project_root, spec_name) -> list:
    """列出 .fenix/verify-progress/<spec>/screenshots/ 下的截图文件。"""
    ss_dir = Path(project_root) / ".fenix" / "verify-progress" / spec_name / "screenshots"
    if not ss_dir.is_dir():
        return []
    out = []
    try:
        for p in sorted(ss_dir.iterdir()):
            if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
                out.append({
                    "file": p.name,
                    "size": p.stat().st_size,
                    "mtime": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(),
                })
    except OSError:
        pass
    return out


def _fold_summary(summary: dict, key: str, val: str) -> dict:
    """把表格/行内的计数键值折进汇总字典；非计数键忽略。

    键名先剥离括号别名（如「通过 (PASS)」「产品缺陷 (BUG)」，v3 验证报告方言）
    再匹配；全角/半角括号均支持。
    """
    if val.lower() in ("n/a", "-", "--", "—"):
        return summary
    k = key.lower()
    k = re.sub(r"[（(][^（）)]*[）)]", "", k)
    k = k.replace(" ", "").replace("数", "")
    if k in ("产品bug", "产品", "bug", "产品缺陷", "缺陷"):
        summary["product_bugs"] = val
    elif k in ("环境问题", "环境"):
        summary["env_issues"] = val
    elif k in ("通过", "passed", "通过数"):
        summary["passed"] = val
    elif k in ("失败", "failed", "失败数"):
        summary["failed"] = val
    elif k in ("错误", "error", "errors", "错误数"):
        summary["errors"] = val
    return summary


def _load_run_result(project_root, spec_name) -> dict | None:
    """读取裁决 .fenix-run-result.json（两路候选，不可得返回 None）。

    专属副本（.fenix/verify-progress/<spec>/.fenix-run-result.json）优先；
    项目根 .fenix/.fenix-run-result.json 为共享文件，携带的 spec 与当前 spec
    不符时视为其它 spec 残留忽略。损坏/非对象同样返回 None（fail-closed）。
    """
    candidates = [
        Path(project_root) / ".fenix" / "verify-progress" / spec_name / ".fenix-run-result.json",
        Path(project_root) / ".fenix" / ".fenix-run-result.json",
    ]
    for idx, path in enumerate(candidates):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        if idx == 1 and isinstance(data.get("spec"), str) and data["spec"] and data["spec"] != spec_name:
            continue
        return data
    return None


def _run_result_verdict_and_bugs(data: dict) -> tuple:
    """从 run-result dict 提取（裁决值, bugs 清单）；无合法裁决返回 ("", [])。

    fast-track：裁决嵌套在 verification.verdict、bugs 在 verification.bugs
    （fast_track_result.py 契约）；full 模式：顶层 status 即裁决值、顶层 bugs
    （agents/verifier.md schema）。verdict 非法取值一律 fail-closed 拒收。
    """
    ver = data.get("verification")
    if isinstance(ver, dict) and ver.get("verdict") in ("verified", "bug-found"):
        bugs = ver.get("bugs")
        return ver["verdict"], bugs if isinstance(bugs, list) else []
    if data.get("status") in ("verified", "bug-found"):
        bugs = data.get("bugs")
        return data["status"], bugs if isinstance(bugs, list) else []
    return "", []


def _verdict_from_run_result(project_root, spec_name) -> dict:
    """从 .fenix-run-result.json 的裁决段合成 verdict（verification-report.md 缺失时兜底）。

    fast-track 单 agent 全包不产 verification-report.md，裁决结论只存在于
    .fenix-run-result.json 的 verification 段（fast_track_result.py 契约）；
    full 模式 md 缺失时结果文件顶层 status 也可能是裁决值。缺失/非法一律
    fail-closed 返回 exists: False（维持空态，不伪造结论）。
    """
    data = _load_run_result(project_root, spec_name)
    if data is not None:
        verdict_value, _bugs = _run_result_verdict_and_bugs(data)
        if verdict_value:
            scenarios = data.get("verification", {}).get("scenarios") \
                if isinstance(data.get("verification"), dict) else None
            if not isinstance(scenarios, list):
                scenarios = data.get("scenarios")
            summary = {"passed": 0, "failed": 0, "errors": 0,
                       "product_bugs": len(_bugs), "env_issues": None}
            if isinstance(scenarios, list):
                for sc in scenarios:
                    status = sc.get("status") if isinstance(sc, dict) else None
                    if status == "pass":
                        summary["passed"] += 1
                    elif status in ("fail", "failed"):
                        summary["failed"] += 1
                    elif status == "error":
                        summary["errors"] += 1
                    # warning/exempt 豁免类不入三桶（与裁决链豁免语义一致）
            return {
                "exists": True,
                "status": ("✅ 验证通过（verified）" if verdict_value == "verified"
                           else "❌ 未通过（Bug Found）"),
                "status_detail": f"裁决: {verdict_value}",
                "conclusion": "",
                "summary": summary,
            }
    return {"exists": False, "status": "", "status_detail": "", "conclusion": "", "summary": {}}


def parse_verdict(project_root, spec_name) -> dict:
    """解析 verification-report.md 的验证结论，供 Dashboard 直接展示。

    返回: {"exists", "status", "status_detail", "conclusion", "summary"}
    - status: 结论标题（如 "环境不可达，无法验证" / "❌ 未通过（Bug Found）"）
    - status_detail: **状态:** 行（如 "环境问题 — Dashboard 服务未启动"）
    - conclusion: 结论段落（人类可读，避免用户只看 "0通过, 31失败"）
    - summary: {"passed","failed","errors","product_bugs","env_issues"} 尽力解析

    md 文件缺失时回退 .fenix-run-result.json 的裁决段（_verdict_from_run_result）：
    fast-track 模式不产 verification-report.md，原先 verdict.exists 恒 False，
    列表「验证」列 Popover 与详情页 VerdictPanel 对 fast-track spec 恒隐。
    """
    path = Path(project_root) / "spec" / "changes" / spec_name / "verification-report.md"
    if not path.exists():
        return _verdict_from_run_result(project_root, spec_name)
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        content = ""

    summary = {"passed": None, "failed": None, "errors": None,
               "product_bugs": None, "env_issues": None}
    status = ""
    status_detail = ""
    conclusion = ""
    conclusion_mode = False

    for raw in content.split("\n"):
        s = raw.strip()
        # 结论标题：## 结论[: 内联] / ## 结论摘要 / ## 判定结论[: 内联]
        m = re.match(r"^#{2,4}\s*(?:判定)?结论\s*(?:摘要)?\s*[：:]?\s*(.*)$", s)
        if m:
            status = m.group(1).strip() or status
            conclusion_mode = True
            continue
        if conclusion_mode:
            if re.match(r"^#{2,4}\s+", s):
                conclusion_mode = False
            elif s.startswith("**状态"):
                status_detail = re.sub(r"^.*?状态\s*[：:]\s*|\*\*\s*$", "", s).strip()
            elif s.startswith(("|", "---", "-", "**", ">")):
                pass
            elif s:
                # 行间用 \n 衔接、空行落为段落分隔（\n\n），保住 markdown 段落结构供前端渲染
                conclusion += ("\n" if conclusion else "") + s
            elif conclusion:
                conclusion += "\n"
        # 备选状态：**验证结果**：❌ 未通过（Bug Found）
        m2 = re.match(r"^\*\*\s*验证结果\s*\*\*\s*[：:]\s*(.+)$", s)
        if m2 and not status:
            status = m2.group(1).strip()
        # 表格行：| 通过 | 0 |
        m3 = re.match(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", s)
        if m3:
            summary = _fold_summary(summary, m3.group(1), m3.group(2).strip())
            continue
        # 行内计数：通过：0
        m4 = re.match(r"^([^|#]{1,12})\s*[：:]\s*([\dN/A\-＋+]+)\s*$", s)
        if m4:
            summary = _fold_summary(summary, m4.group(1), m4.group(2).strip())

    # 兜底：全文搜索计数（处理 "通过：0 | 失败：0 | 错误：10" 行内连写）
    if any(v is None for v in summary.values()):
        for pat, field in [("通过", "passed"), ("失败", "failed"), ("错误", "errors"),
                           (r"产品\s*Bug", "product_bugs"), ("环境问题", "env_issues")]:
            if summary[field] is not None:
                continue
            mm = re.search(r"%s\s*[：:]\s*([\dN/A\-＋+]+)" % pat, content, re.I)
            if mm and mm.group(1).strip().lower() not in ("n/a", "-", "--"):
                summary[field] = mm.group(1).strip()

    return {
        "exists": True,
        "status": status,
        "status_detail": status_detail,
        "conclusion": conclusion.strip()[:600],
        "summary": summary,
    }


def parse_bugs(project_root, spec_name) -> list:
    """聚合 bug 列表：来自 report.json 的失败/错误场景。

    返回: [{"source": "report", "severity", "scenario_ids", "assertion_type",
            "description", "evidence", "screenshots"}]

    bug 只从结构化的 report.json 提取（每条失败/错误场景 + 失败断言 + 截图）。
    不再从 verification-report.md 逐行正则猜测——Markdown 是人读文档，逐行抓
    「bug/缺陷/失败」关键词会把「环境失败」「被修复缺陷的背景描述」「通过型报告」
    误判为产品缺陷（add-parallelism、fix-worktree-agent-cwd、fix-add-parallelism 等
    均因此产生过大量虚假 bug）。

    状态枚举对齐写入侧（裁决后失败场景不再消失）：引擎写 "fail"（engine.py
    _determine_scenario_status），裁决链 enforce_status_mapping（verdict_check.py）
    与裁决 Agent 自写报告产 "failed"——两族取值都算失败场景；warning 保持不记
    Bug（合规报告禁止 product-bug 挂 warning，会被强制 failed）。
    分类过滤（add-verdict-evidence-taxonomy）：test-defect/flaky/env 归类 =
    非产品缺陷，不进 Bug 列表（与报告「产品 Bug」计数同语义）；product-bug、
    旧格式无分类（向后兼容）及未知取值（fail-open）照常收录。

    回退（第五读侧缺口）：report.json 缺失/损坏时从 .fenix-run-result.json 的
    bugs 清单收录（fast-track 嵌套 verification.bugs，full 模式 verifier 顶层
    bugs；裁决段由 _run_result_verdict_and_bugs 单点解析）——fast-track 不产
    report.json，原先详情页 Bug 列表对其恒空（source 标记 "run-result"）。
    条目统一携带 scenario/assertion 兼容字段（前端 dashboard.ts 类型为单数
    bug.scenario / bug.assertion，后端原先只给 scenario_ids/assertion_type，
    「关联场景」「断言类型」两行因此从未渲染过）。
    """
    from core.verdict_check import VERDICT_CLASSES
    non_product_classes = tuple(c for c in VERDICT_CLASSES if c != "product-bug")
    bugs = []
    report = parse_report(project_root, spec_name)
    if not report.get("exists") or report.get("error"):
        # report.json 缺失/损坏：run-result bugs 清单回退（fail-closed 无数据返回 []）
        data = _load_run_result(project_root, spec_name)
        if data is None:
            return bugs
        _verdict, rt_bugs = _run_result_verdict_and_bugs(data)
        # severity 归一：fast-track.md 模板是 critical|major|minor，verifier 自由
        # 产出实测漂移为 high|medium|low（agents/verifier.md 步骤 8 未定义条目
        # schema）——读取端统一映射到前端三档色系，未知值原样透传由前端兜底。
        severity_map = {"critical": "critical", "high": "major", "major": "major",
                        "medium": "major", "minor": "minor", "low": "minor"}
        for bug in rt_bugs:
            if not isinstance(bug, dict):
                continue
            ev = bug.get("evidence")
            if isinstance(ev, dict):
                ev = json.dumps(ev, ensure_ascii=False)
            elif not isinstance(ev, str):
                ev = ""
            scenario_ids = bug.get("scenario_ids")
            if not isinstance(scenario_ids, list):
                scenario_ids = []
            assertion_type = bug.get("assertion_type") or ""
            raw_severity = bug.get("severity") or ""
            bugs.append({
                "source": "run-result",
                "severity": severity_map.get(raw_severity, raw_severity) or "major",
                "scenario_ids": scenario_ids,
                "assertion_type": assertion_type,
                "description": bug.get("description") or bug.get("title") or "",
                "evidence": ev or (bug.get("root_cause") or ""),
                "root_cause": bug.get("root_cause") or "",
                "classification": None,
                "status_corrected": False,
                "screenshots": [],
                # verifier 自由 schema 透传（id/title/location），fast-track 无则缺省
                "id": bug.get("id") or "",
                "title": bug.get("title") or "",
                "location": bug.get("location") or "",
                # 前端卡片渲染兼容字段（bug.scenario / bug.assertion）
                "scenario": ", ".join(str(s) for s in scenario_ids),
                "assertion": assertion_type,
            })
        return bugs
    for sc in report.get("scenarios", []):
        if not isinstance(sc, dict):
            continue
        status = sc.get("status")
        if status not in ("fail", "failed", "error"):
            continue
        classification = sc.get("classification")
        if classification in non_product_classes:
            continue
        failed_assertions = [
            a for a in sc.get("assertion_results", [])
            if isinstance(a, dict) and not a.get("pass", True)
        ]
        # 截图路径归一化为文件名：report.json 存的是服务器本地绝对路径，
        # 前端需拼 /screenshots/<project>/<spec>/<file>，只取 basename
        screenshots = [os.path.basename(s) for s in sc.get("screenshots", []) if isinstance(s, str) and s.strip()]
        # 裁决分类与证据（add-verdict-evidence-taxonomy 3.1）：从场景条目摘取；
        # 旧格式 report.json 无 classification/evidence 字段时为空/缺省，向后兼容。
        # 结构化证据优先取场景 evidence 字段（judge 增强产出）；
        # 回退到首个失败断言的 message，保证旧数据仍有证据可见。
        sc_evidence = sc.get("evidence")
        if isinstance(sc_evidence, dict):
            sc_evidence = json.dumps(sc_evidence, ensure_ascii=False)
        elif not isinstance(sc_evidence, str):
            sc_evidence = ""
        for a in failed_assertions or [{}]:
            bugs.append({
                "source": "report",
                "severity": "major" if status in ("fail", "failed") else "critical",
                "scenario_ids": [sc.get("scenario_id", "?")],
                "assertion_type": a.get("type", "step"),
                "description": sc.get("description", "未命名场景"),
                "evidence": (
                    a.get("message") or a.get("detail") or a.get("actual") or ""
                ) or sc_evidence,
                "classification": classification,
                "status_corrected": sc.get("status_corrected", False),
                "screenshots": screenshots,
                "scenario_status": status,
                # 前端卡片渲染兼容字段（bug.scenario / bug.assertion，类型单复数漂移）
                "scenario": str(sc.get("scenario_id", "?")),
                "assertion": a.get("type", "step"),
            })
    return bugs


def parse_filtered_failures(project_root, spec_name) -> list:
    """提取被分类过滤（非 product-bug）的失败/错误场景摘要（fix-verify-verdict-visibility）。

    返回: [{"scenario_id", "classification", "evidence_summary", "screenshots",
            "status_corrected", "status"}]

    与 parse_bugs 互为互补面（同一过滤语义的互补侧）：bugs 收录 product-bug 与
    旧格式无分类（fail-open）；filtered_failures 仅收录 test-defect/flaky/env 分类
    的失败/错误场景——二者过滤条件互斥，不双计。旧格式 report.json 无
    classification 字段 → 不产生条目（fail-open 语义，向后兼容）。

    evidence_summary 回退链（对齐设计 Decision 3）：evidence.first_failed_step
    （裁决 Agent 产出的人类可读理由）→ evidence.failed_assertions 首项 actual →
    空串；缺字段不抛错。
    """
    from core.verdict_check import VERDICT_CLASSES
    non_product_classes = tuple(c for c in VERDICT_CLASSES if c != "product-bug")
    out = []
    report = parse_report(project_root, spec_name)
    if not report.get("exists") or report.get("error"):
        return out
    for sc in report.get("scenarios", []):
        if not isinstance(sc, dict):
            continue
        status = sc.get("status")
        if status not in ("fail", "failed", "error"):
            continue
        classification = sc.get("classification")
        if classification not in non_product_classes:
            continue
        # evidence 摘要：first_failed_step → failed_assertions 首项 actual → 空串
        evidence_summary = ""
        sc_evidence = sc.get("evidence")
        if isinstance(sc_evidence, dict):
            ffs = sc_evidence.get("first_failed_step")
            if isinstance(ffs, str) and ffs.strip():
                evidence_summary = ffs
            else:
                failed_assertions = sc_evidence.get("failed_assertions")
                if isinstance(failed_assertions, list) and failed_assertions:
                    first = failed_assertions[0]
                    if isinstance(first, dict):
                        actual = first.get("actual")
                        if isinstance(actual, str) and actual.strip():
                            evidence_summary = actual
        # 截图路径归一化为文件名（与 parse_bugs 同一口径，前端拼 /screenshots/ 路由）
        screenshots = [os.path.basename(s) for s in sc.get("screenshots", [])
                       if isinstance(s, str) and s.strip()]
        out.append({
            "scenario_id": sc.get("scenario_id", "?"),
            "classification": classification,
            "evidence_summary": evidence_summary,
            "screenshots": screenshots,
            "status_corrected": sc.get("status_corrected", False),
            "status": status,
        })
    return out


# ── 运行记录（.fenix/runs/） ─────────────────────────────────────

# run 终态事件类型 → classify_run 状态映射。写侧唯一权威是
# core.agent_runner.liveness.RUN_TERMINAL_EVENT_TYPES（result=自然完成,
# error=进程异常终止, interrupted=daemon 停机/启动终态补写, cancelled=人工取消），
# 读侧缺类型会把已终结 run 永远判成 running（overview 活跃 Agent 数虚高事故：
# 11 个被杀 run 全部计入活跃，真实活跃仅 1）。测试锁两侧同步。
# fix-retry-orphan-active-runs 追加变体：运行期间原地重试换新 sub_run_id 弃置
# 旧产物文件（写侧补写 superseded 终态），interrupted 补写够不到（daemon 存活
# 期无停机），缺 superseded 映射会把弃置文件永远判成 running——2026-09-10
# 实测 23 活跃仅 2 真实，21 具尸体全数源于该形态。
_RUN_TERMINAL_STATUS_MAP = {
    "result": "done",
    "error": "error",
    "interrupted": "interrupted",
    "cancelled": "cancelled",
    "superseded": "superseded",  # fix-retry-orphan-active-runs：原地重试弃置产物终态
}

# 读侧 mtime 陈旧兜底阈值（fix-retry-orphan-active-runs D2）：末行非终态
# （running/empty）且产物 mtime 停更超过该秒数 → get_runs 判 stale（弃置/断尾，
# 读侧专属状态枚举，非事件类型，不写入任何产物文件）。退避档上限 120s + agent
# 单 turn（长构建/长测试）余量；live run 每 turn 写事件，30 分钟无写入必非在飞。
# 不做配置项（design D2：避免触发「新增配置必须带 Dashboard 界面」约束）。
_RUN_STALE_SECONDS = 1800


def classify_run(lines: list) -> str:
    """根据产物文件行判定运行终态：done / error / interrupted / cancelled /
    superseded / running / empty。

    runner「终态后置」不变量保证任一终态事件即文件最后一行（result/error 在
    收尾 join 后落盘，interrupted 由 daemon 停机/启动清扫追加，cancelled 由
    取消路径最后落盘，superseded 由原地重试弃置前补写），故只看末行即可判定。
    """
    if not lines:
        return "empty"
    last = lines[-1]
    if not isinstance(last, dict):
        return "running"
    return _RUN_TERMINAL_STATUS_MAP.get(last.get("type"), "running")


def _resolve_run_file(project_root, run_id: str) -> Path:
    """定位 run 产物：优先活跃目录，缺失时回读 archive/（add-run-archive）。"""
    proot = Path(project_root)
    live = proot / ".fenix" / "runs" / f"{run_id}.jsonl"
    if live.exists():
        return live
    return proot / ".fenix" / "runs" / "archive" / f"{run_id}.jsonl"


def _first_run_event_ts(path: Path) -> "str | None":
    """run 产物首个带 timestamp 事件的时间（真实启动时刻）。

    run_id 内嵌时间戳是**首次派发**时刻：多 attempt run（-a2+）复用同一
    run_id 基座只加后缀，按 run_id 解析会让所有 attempt 显示同一开始时刻、
    duration 虚增（含前序 attempt 寿命）。真实起点取产物首个带 timestamp 的
    事件：文件头部是无时间戳的 provider_marker/hook/system 事件（实测 10+ 行），
    故扫描前 200 行、命中即停；全部无样本返回 None（调用方回退 run_id 内嵌
    时间戳）。
    """
    try:
        with path.open("rb") as f:
            for _ in range(200):
                raw = f.readline()
                if not raw:
                    break
                line = raw.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = ev.get("timestamp") if isinstance(ev, dict) else None
                if ts and _parse_iso_ts(str(ts)) is not None:
                    return str(ts)
    except OSError:
        return None
    return None


def get_runs(project_root, spec_name: str | None = None,
             include_archive: bool = False) -> list:
    """列出项目的运行记录（.fenix/runs/*.jsonl）。

    spec_name 省略时返回全部；否则仅返回 run_id 包含该 spec 的记录。
    include_archive=True 时并入 runs/archive/ 的归档产物（同 run_id 以活跃
    副本优先），供时间轴/运行历史/耗时统计回看已归档的旧 run。
    每条: {run_id, agent_type, spec, status, started, file_size, events}
    """
    runs_dir = Path(project_root) / ".fenix" / "runs"
    if not runs_dir.is_dir():
        return []
    out = []
    try:
        files = list(runs_dir.glob("*.jsonl"))
        if include_archive:
            archive_dir = runs_dir / "archive"
            if archive_dir.is_dir():
                seen = {p.stem for p in files}
                for p in archive_dir.glob("*.jsonl"):
                    if p.stem not in seen:
                        files.append(p)
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return []
    now = time.time()
    for p in files:
        run_id = p.stem
        if spec_name and spec_name not in run_id:
            continue
        try:
            stat = p.stat()
        except OSError:
            continue
        # 从 run_id 推断 agent 类型与 spec：admin-/impl-/verify-/planner-plan-/planner-judge-
        agent_type = "agent"
        spec_part = run_id
        for prefix, at in (("admin-", "administrator"),
                           ("planner-judge-", "planner-judge"),
                           ("planner-plan-", "planner-plan"),
                           ("planner-", "planner"),
                           ("impl-", "implementer"),
                           ("verify-", "verifier"),
                           ("test-", "tester")):
            if run_id.startswith(prefix):
                agent_type = at
                spec_part = run_id[len(prefix):]
                break
        # 去掉 attempt 段（-a<n>，每个 attempt 追加的后缀），再剥末尾时间戳（-<ts>）。
        # 先剥 -a<n> 再剥时间戳，使 spec_part 不残留时间戳/尝试段。
        spec_part = re.sub(r"-a\d+$", "", spec_part)
        m = re.match(r"^(.*)-\d{9,10}$", spec_part)
        if m:
            spec_part = m.group(1)
        # 耗时：run_id 起始时间戳为 attempt 段前的 10 位 unix 秒（int(time.time())），
        # 文件 mtime 为终止。优先匹配 `-<ts>-a<n>`（含 attempt 后缀的真实格式），
        # 回退 `-<ts>`（旧格式无 attempt 后缀），再无则退化 mtime（现状兜底）。
        tm = re.search(r"-(\d{9,10})-a\d+$", run_id) or re.search(r"-(\d{9,10})$", run_id)
        start_ts = int(tm.group(1)) if tm else stat.st_mtime
        # started 优先取产物首行事件时间戳（真实启动时刻）：run_id 内嵌时间戳
        # 是首次派发时刻，多 attempt run 复用基座会显示同一时刻且 duration 虚增。
        # mtime 仍是结束时间（started 用派发/启动时刻而非结束时刻的语义不变）。
        real_start = _first_run_event_ts(p)
        real_dt = _parse_iso_ts(real_start) if real_start else None
        if real_dt is not None:
            started = real_dt.astimezone(timezone.utc).isoformat()
            duration_seconds = max(0, int(stat.st_mtime - real_dt.timestamp()))
        else:
            # started 用 run_id 解析出的开始时间戳，而非文件 mtime
            # （mtime 是运行 *结束* 时间）。duration_seconds = mtime - start_ts 已真实计算，
            # 若 started 仍取 mtime，则运行列表/时间轴会把每次运行显示为「在结束时刻才开始」，
            # 与真实耗时自相矛盾（耗时列为真实秒数而开始时间却是结束时刻）。
            started = datetime.fromtimestamp(start_ts, tz=timezone.utc).isoformat()
            duration_seconds = max(0, int(stat.st_mtime - start_ts))
        lines = _read_run_lines(p, max_lines=3)
        status = classify_run(lines)
        # fix-retry-orphan-active-runs D3：stale 判定挂在 get_runs 的 status
        # 组装处（classify_run 保持纯函数不注入 mtime）。末行非终态且文件 mtime
        # 停更超过 _RUN_STALE_SECONDS → 判 stale（原地重试弃置尸体 / 进程被杀
        # 无终态断尾），stale 不进 _RUN_TERMINAL_STATUS_MAP（非事件类型）。
        if status in ("running", "empty") and (now - stat.st_mtime) > _RUN_STALE_SECONDS:
            status = "stale"
        out.append({
            "run_id": run_id,
            "agent_type": agent_type,
            "spec": spec_part,
            "status": status,
            "duration_seconds": duration_seconds,
            "started": started,
            "file_size": stat.st_size,
        })
    return out


def _read_run_lines(path: Path, max_lines: int = 3) -> list:
    """读取产物文件最后几行 JSON，逐行容错。

    逐行流式读取（deque 保留尾部），不用末尾字节窗口 seek：result/error
    终结事件行可能超长（result 携带完整结果数据，4KB+），字节窗口会把末行
    从字节中间截断、parse 失败后被包装成伪 stderr 事件排在真实末尾，
    classify_run 因此把已完成 run 误判为 running（overview 活跃 Agent 数
    虚高）。run 产物均为 MB 级以下小文件，全量逐行读开销可忽略。
    """
    tail = deque(maxlen=max_lines)
    try:
        with path.open("rb") as f:
            for raw in f:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    tail.append(json.loads(line))
                except json.JSONDecodeError:
                    tail.append({"type": "stderr", "line": line})
    except OSError:
        pass
    return list(tail)


def _parse_run_lines(lines) -> list:
    """逐行解析 JSONL 行序列为事件（容错：损坏行降级为 stderr 条目）。"""
    events = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            entry = {"type": "stderr", "line": line}
        if not isinstance(entry, dict):
            entry = {"type": "stderr", "line": str(entry)}
        events.append(entry)
    return events


def get_run_events(project_root, run_id: str, tail: int = 300) -> dict:
    """读取单次运行产物流的尾部（前端只展示最近 N 条，全量拉取是浪费）。

    返回: {run_id, exists, status, events, total_events, error}
    events 为最后 tail 条逐行解析结果；status/error 仍由全文件判定
    （终态行 result/error 决定），total_events 为实际总事件数。
    """
    run_file = _resolve_run_file(project_root, run_id)
    if not run_file.exists():
        return {"run_id": run_id, "exists": False, "status": "missing",
                "events": [], "total_events": 0, "error": None}
    events = []
    error = None
    try:
        with run_file.open("r", encoding="utf-8", errors="replace") as f:
            for entry in _parse_run_lines(f):
                events.append(entry)
                if entry.get("type") == "error":
                    error = entry
    except OSError:
        return {"run_id": run_id, "exists": True, "status": "error",
                "events": [], "total_events": 0, "error": {"error": "unreadable"}}
    return {
        "run_id": run_id,
        "exists": True,
        "status": classify_run(events),
        "events": events[-tail:],
        "total_events": len(events),
        "error": error,
    }


def read_run_events_between(project_root, run_id: str, start_offset: int) -> list:
    """读取运行产物从 start_offset 字节到 EOF 的事件（增量推送用）。

    O_APPEND 只增写：按上次记录的字节偏移读取新增部分，避免整文件重读。
    跨扫描边界被截断的半个 JSON 行会降级为 stderr 条目（_parse_run_lines 容错）。
    """
    run_file = Path(project_root) / ".fenix" / "runs" / f"{run_id}.jsonl"
    try:
        with run_file.open("rb") as f:
            f.seek(start_offset)
            raw = f.read()
    except OSError:
        return []
    text = raw.decode("utf-8", errors="replace")
    return _parse_run_lines(text.splitlines())


# ── 聚合视图（供 Web API / 概览 / 详情） ──────────────────────────

def active_run_count(project_root) -> int:
    """统计处于 running / empty（可能正在增长）状态的运行数。"""
    return sum(1 for r in get_runs(project_root) if r["status"] in ("running", "empty"))


# ── daemon 健康检测（D4：TTL memo 避免高频轮询重复 spawn tmux） ──────

_DAEMON_HEALTH_TTL = 5.0   # 秒；结果在 TTL 内复用
_DAEMON_HEALTH_CACHE: dict = {}   # key=规范化项目根, value=(状态, 时间戳)


def daemon_health(project_root) -> str:
    """项目 fenixd daemon 是否在运行，返回 "running"/"stopped"。

    判定复用 core.fenix_session.is_running（进程检测为主：项目根下的
    fenixd.py / fenixd_supervisor.py 进程；/proc 不可用时回退 tmux session）。
    tmux 不可用、subprocess 异常或均未命中一律 "stopped"，
    不抛异常。带短 TTL memo，避免 overview 每 2s 轮询重复 spawn 子进程。
    """
    key = str(Path(project_root).expanduser().resolve())
    now = time.monotonic()
    cached = _DAEMON_HEALTH_CACHE.get(key)
    if cached is not None and now - cached[1] < _DAEMON_HEALTH_TTL:
        return cached[0]
    try:
        status = "running" if _is_running(key) else "stopped"
    except Exception:
        status = "stopped"
    if len(_DAEMON_HEALTH_CACHE) > 256:
        _DAEMON_HEALTH_CACHE.clear()
    _DAEMON_HEALTH_CACHE[key] = (status, now)
    return status


def project_summary(project_root, name: str, path: str) -> dict:
    """单个项目的聚合摘要（/api/projects、/api/overview 共用）。"""
    proot = Path(path)
    specs = parse_state(proot)
    status_counts = {}
    for e in specs.values():
        st = e.get("status", "?") or "?"
        status_counts[st] = status_counts.get(st, 0) + 1

    grand_done = grand_total = 0
    problems = 0
    for sname in specs:
        entry = specs[sname]
        d, t = task_progress(proot, sname, entry.get("status", ""))
        grand_done += d
        grand_total += t
        if entry.get("error") and entry.get("status") not in ("done", "pushed"):
            problems += 1

    runs = get_runs(proot)
    active = sum(1 for r in runs if r["status"] in ("running", "empty"))
    active_by_type = {}
    for r in runs:
        if r["status"] in ("running", "empty"):
            active_by_type[r["agent_type"]] = active_by_type.get(r["agent_type"], 0) + 1

    # 获取项目描述
    effective_config = read_effective_config(proot)
    description = effective_config.get("description", "")

    return {
        "name": name,
        "path": str(path),
        "daemon": daemon_health(proot),
        "spec_count": len(specs),
        "status_counts": status_counts,
        "task_done": grand_done,
        "task_total": grand_total,
        "problems": problems,
        "active_runs": active,
        "active_runs_by_type": active_by_type,
        "scenario_count": sum(count_scenarios(proot, s) for s in specs),
        "updated": (Path(path) / ".fenix" / "STATE.md").stat().st_mtime if (Path(path) / ".fenix" / "STATE.md").exists() else 0,
        "description": description,
    }


def _spec_total_duration(project_root, spec_name: str, entry: dict, runs: list) -> int:
    """SPEC 累计耗时（add-spec-detail-duration：列表 spec_summary / 详情 spec_detail
    共用同一口径，保证两页数值严格一致）。done/pushed 优先读 STATE.md 固化的
    total_duration（done 时刻快照，不随 run 产物清理归零）；其余状态或脏值回退
    实时求和（运行中的 SPEC 耗时应持续增长，固化值仅对终态有意义）。"""
    persisted = None
    if entry.get("status") in ("done", "pushed"):
        raw = entry.get("total_duration")
        if raw is not None:
            try:
                persisted = int(raw)
            except (TypeError, ValueError):
                persisted = None
    if persisted is None:
        # 耗时 = 该 spec 全部运行记录（implementer/verifier/planner/tester 等）的
        # duration_seconds 求和；无任何运行记录时为 0。
        return sum(int(r.get("duration_seconds") or 0) for r in runs)
    return persisted


# ── 全局 impl_run_budget 缓存（add-spec-status-modal-budget D3）──────────────
# budget_effective 需读全局 config agents.impl_run_budget 做 fallback，每次
# spec_summary 调用都 resolve_config 是浪费（O(N) YAML 解析）；以 config 文件
# 签名键缓存一次解析结果，签名不变直返缓存。与 _EFFECTIVE_CONFIG_CACHE 同模式。
_GLOBAL_BUDGET_CACHE: dict = {}
_GLOBAL_BUDGET_CACHE_MAX = 64


def _resolve_global_impl_run_budget(project_root) -> int:
    """读取全局 agents.impl_run_budget 有效值，fallback DEFAULT_IMPL_RUN_BUDGET。

    结果按项目级 config.yaml 签名键缓存（config 变化自动失效），与闸门口径一致：
    ConfigLoader.get 读合并配置 → clamp_impl_run_budget 夹紧 → fallback DEFAULT。
    """
    from core.pm_engine.budget import clamp_impl_run_budget, DEFAULT_IMPL_RUN_BUDGET
    from core.config import ConfigLoader
    proot = Path(project_root)
    cfg_path = proot / ".fenix" / "config.yaml"
    sig = _config_file_sig(cfg_path)
    cache_key = (str(proot.resolve()), sig)
    cached = _GLOBAL_BUDGET_CACHE.get(cache_key)
    if cached is not None:
        return cached
    cfg = ConfigLoader.resolve_config(proot)
    raw = ConfigLoader.get(cfg, "agents.impl_run_budget")
    budget = clamp_impl_run_budget(raw) or DEFAULT_IMPL_RUN_BUDGET
    if len(_GLOBAL_BUDGET_CACHE) > _GLOBAL_BUDGET_CACHE_MAX:
        _GLOBAL_BUDGET_CACHE.clear()
    _GLOBAL_BUDGET_CACHE[cache_key] = budget
    return budget


def spec_summary(project_root, spec_name: str, entry: dict) -> dict:
    """单个 SPEC 的摘要（/api/specs 列表项）。"""
    done, total = task_progress(project_root, spec_name, entry.get("status", ""))
    vp = parse_verify_progress(project_root, spec_name)
    # 含归档：run 产物被清理后列表页耗时统计不缩水
    runs = get_runs(project_root, spec_name, include_archive=True)
    total_duration = _spec_total_duration(project_root, spec_name, entry, runs)
    # add-fast-track-mode（task 7.1）：执行模式（读 .spec.yaml，缺省 full）
    from core.spec_mode import read_spec_mode
    mode = read_spec_mode(project_root, spec_name)
    # add-spec-status-modal-budget D3：per-spec 预算字段
    # 三字段读取与预算闸门同源（clamp_impl_run_budget 单点），前端不重复实现解析。
    from core.pm_engine.budget import clamp_impl_run_budget, IMPL_RUN_BUDGET_OVERRIDE_FIELD, DEFAULT_IMPL_RUN_BUDGET
    budget_override_raw = entry.get(IMPL_RUN_BUDGET_OVERRIDE_FIELD) if entry else None
    budget_override = clamp_impl_run_budget(budget_override_raw)
    try:
        budget_used = int(entry.get("_impl_run_budget_used", 0) or 0) if entry else 0
    except (TypeError, ValueError):
        budget_used = 0
    if budget_override is not None:
        budget_effective = budget_override
    else:
        budget_effective = _resolve_global_impl_run_budget(project_root)
    return {
        "name": spec_name,
        "status": entry.get("status"),
        "archived": is_spec_archived(project_root, spec_name),
        "mode": mode,
        "priority": entry.get("priority"),
        "created": entry.get("created"),
        "updated": entry.get("updated"),
        "error": entry.get("error"),
        # add-spec-scheduling-controls D6：定时拾取（start_after）与定时解冻
        # （frozen_until）规范值（ISO8601 UTC 或 null），前端列表据此渲染
        # 定时 Tag/倒计时与冻结模式。
        "start_after": get_spec_start_after(entry),
        "frozen_until": get_frozen_until(entry),
        # add-task-progress-verify-phase：阶段判定单点在后端——仅 testing 切
        # verify（验证引擎运行中），其余一切状态按 impl；fast-track 经
        # _fast_track_advance_to_verified 瞬时连转 testing→verified 不停留，
        # 天然恒 impl，无需 mode 特判。前端只消费该字段，不重复判定。
        "progress_phase": "verify" if entry.get("status") == "testing" else "impl",
        "verify_current": vp.get("current", ""),
        "task_done": done,
        "task_total": total,
        # run 层实时进度（fix-implementer-task-progress D3）：tasks.md 快照失效
        # （subject 无编号 / agent 不勾 tasks.md）时仍能看到 run 推进。
        "run_progress": run_task_progress(project_root, spec_name),
        "verify_done": vp.get("done", 0),
        "verify_total": vp.get("total", 0),
        "verify_error": vp.get("error"),
        # verification-phase-progress：出题进度（生成阶段 verify_total=0 时有值）
        "generation": spec_generation_progress(project_root, spec_name, entry, vp=vp),
        "scenario_count": count_scenarios(project_root, spec_name),
        "total_duration": total_duration,
        "latest_run": runs[0]["run_id"] if runs else None,
        "latest_run_status": runs[0]["status"] if runs else None,
        # add-spec-status-modal-budget D3：per-spec 预算覆盖三字段
        #（used 容错读；override 非法视为 null；effective 与闸门同源解析）
        "budget_used": budget_used,
        "budget_override": budget_override,
        "budget_effective": budget_effective,
    }


# ── spec 摘要索引（dashboard-spec-summary-index D1） ─────────────

def _stat_sig(path: Path):
    """文件签名 (mtime_ns, size)；缺失/不可 stat 返回 None。"""
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _runs_by_spec_sigs(proot: Path) -> dict:
    """扫描 .fenix/runs（含 archive）一次，按 spec 分组各 run 文件签名。

    返回 {spec_name: {run_path_str: (mtime_ns, size)}}。全目录只 glob 一次，
    避免每 spec 各自 glob 的 O(N²) 放大（add-dashboard-incremental-data D1）。
    """
    runs_dir = proot / ".fenix" / "runs"
    if not runs_dir.is_dir():
        return {}
    out: dict = {}
    try:
        paths = list(runs_dir.glob("*.jsonl"))
        arc = runs_dir / "archive"
        if arc.is_dir():
            paths.extend(arc.glob("*.jsonl"))
    except OSError:
        return out
    for p in paths:
        sig = _stat_sig(p)
        if sig is None:
            continue
        spec_part = run_spec_part(p.stem)
        if not spec_part:
            continue
        out.setdefault(spec_part, {})[str(p)] = sig
    return out


def _spec_dep_sigs(proot: Path, spec_name: str, entry: dict,
                   runs_sigs: dict) -> dict:
    """单个 spec 摘要的依赖文件签名集合（对齐 spec_summary 实际读路径）。

    覆盖 tasks.md（implementing 时含实现 worktree 副本）/ specs/ 目录整体 /
    .spec.yaml / verification-report.md / verify-progress 相关文件 /
    该 spec 的 run 产物（由调用方预扫描 runs_sigs 传入）。宁多勿漏：把
    specs/ 目录整体入签名，依赖文件集合单向全覆盖。
    """
    sigs: dict = {}
    changes = proot / "spec" / "changes" / spec_name

    def add(p: Path):
        sig = _stat_sig(p)
        if sig is not None:
            sigs[str(p)] = sig

    add(changes / "tasks.md")
    if entry and entry.get("status") == "implementing":
        wt = find_implementer_worktree(proot, spec_name)
        if wt is not None:
            add(wt / "spec" / "changes" / spec_name / "tasks.md")
    add(changes / ".spec.yaml")
    add(changes / "verification-report.md")
    specs_dir = changes / "specs"
    if specs_dir.is_dir():
        try:
            for sf in specs_dir.rglob("*.md"):
                add(sf)
        except OSError:
            pass
    add(proot / ".fenix" / "verify-progress" / f"{spec_name}.json")
    vp_dir = proot / ".fenix" / "verify-progress" / spec_name
    add(vp_dir / "report.json")
    add(vp_dir / "test_scenarios.json")
    # add-spec-status-modal-budget D3：budget_effective 依赖全局 config
    #（agents.impl_run_budget 覆盖优先解析的兜底来源），项目级与用户级
    # config.yaml 变化须触发摘要失效（宁多勿漏原则）。
    add(proot / ".fenix" / "config.yaml")
    for p, sig in (runs_sigs.get(spec_name) or {}).items():
        sigs[p] = sig
    return sigs


class SummaryIndex:
    """每项目 spec 摘要内存索引（dashboard-spec-summary-index D1）。

    结构：{proot_key: {spec_name: {"summary": dict, "sigs": {path: (mtime_ns, size)}}}}

    - 惰性构建：首次 get() 触发；watcher 与 server 共享同一实例（单写者 watcher
      线程，读者 HTTP 线程，经 RLock 保护——读多写少场景足够）。
    - 失效策略：每 spec 先比对依赖文件签名，未变直返缓存；变化只重算该 spec。
    - STATE.md 签名变化 → 该项目全量重建（新增/删除 spec 只有 parse_state 全量
      才能发现，触发频率低）。
    - 有界性：摘要 dict 常驻内存（10000 spec ≈ 数十 MB，可接受）；签名只对存在
      路径记录，删除的 spec 目录从索引剔除。
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._idx: dict = {}
        self._state_sigs: dict = {}
        self._state_snapshot: dict = {}

    def get(self, proot, specs: dict | None = None, state_sig=None) -> list:
        """返回该项目的全部 spec_summary 列表（顺序与 specs dict 一致）。

        Args:
            proot: 项目根路径
            specs: parse_state 快照 {spec_name: entry}；省略时复用索引内缓存快照
                （STATE.md 签名未变则直接复用，避免每请求全量解析 STATE.md）。
            state_sig: STATE.md 的 (mtime_ns, size) 签名；变化时触发全量重建
                并重新解析 STATE.md 快照。
        """
        key = str(Path(proot).resolve())
        with self._lock:
            if state_sig is None:
                state_sig = _stat_sig(proot / ".fenix" / "STATE.md")

            # STATE.md 签名变化 → 全量重建索引 + 重新解析快照（新增/删除 spec
            # 只有 parse_state 全量才能发现；触发频率低，仅 STATE.md 变更时）。
            state_changed = state_sig is not None and self._state_sigs.get(key) != state_sig
            if specs is None:
                if not state_changed:
                    specs = self._state_snapshot.get(key)
                if specs is None:
                    specs = parse_state(proot)
                    self._state_snapshot[key] = specs

            idx = self._idx.get(key)
            if idx is None or state_changed:
                idx = {}

            runs_sigs = _runs_by_spec_sigs(proot)
            out = []
            for spec_name, entry in specs.items():
                entry = entry or {}
                cached = idx.get(spec_name)
                sigs = _spec_dep_sigs(proot, spec_name, entry, runs_sigs)
                if cached is not None and cached.get("sigs") == sigs:
                    out.append(cached["summary"])
                    continue
                summary = spec_summary(proot, spec_name, entry)
                idx[spec_name] = {"summary": summary, "sigs": sigs}
                out.append(summary)

            # 清理已删除 spec 的签名条目
            for stale in [s for s in idx if s not in specs]:
                del idx[stale]

            self._idx[key] = idx
            if state_sig is not None:
                self._state_sigs[key] = state_sig
                if specs is not None:
                    self._state_snapshot[key] = specs
            return out


# ── SPEC 生命周期时间轴 ──────────────────────────────────────────

_LIFECYCLE_ORDER = {"drafted": 0, "ready": 1, "implementing": 2, "bug-found": 2.5,
                    "implemented": 3, "testing": 4, "verified": 5, "done": 6, "pushed": 7}


def _backtrack_reason(frm: str, to: str) -> str:
    """状态回退的规则兜底原因（Agent 记录的 error 优先，见 get_spec_timeline）。"""
    if to == "bug-found":
        return "验证发现 bug，退回修复"
    if frm == "testing" and to in ("implementing", "ready"):
        return "验证失败/中断，回退实现"
    if frm == "implemented" and to in ("implementing", "ready"):
        return "实现未通过，回退重做"
    if frm == "ready" and to == "ready":
        return "实现失败，重试"
    return "状态回退"


def _load_billing_config(project_root) -> dict:
    """从 llm.providers[i].billing 收集 per-provider 计价表（improve-provider-billing-config）。

    返回 {provider_name: {"enabled": bool, "prices": [...]}}——仅登记声明了 billing
    子对象且卡片开关开启的 provider（enabled 关闭的卡片不收集：表非空即等价于
    design D2 的「有任一开启卡片才进入计价分支」闸门，未开启卡片由匹配函数
    直接无表项 → None，计费关闭不下发 cost 字段）。读失败/旧形态（顶层
    llm.billing）/异常一律容错返回空表（fail-open 不计价不崩溃）。
    """
    try:
        _llm = read_effective_config(project_root).get("llm") or {}
        providers = _llm.get("providers") or []
    except Exception:
        return {}
    table: dict = {}
    for p in providers:
        if not isinstance(p, dict):
            continue
        name = p.get("name")
        billing = p.get("billing")
        if not isinstance(name, str) or not name or not isinstance(billing, dict):
            continue
        # 形态异常（enabled 非布尔等）容错：跳过该卡片，不计价不崩溃
        if "enabled" in billing and billing["enabled"] is not None \
                and not isinstance(billing["enabled"], bool):
            continue
        if not billing.get("enabled"):
            continue
        prices = billing.get("prices")
        table[name] = {
            "enabled": True,
            "prices": prices if isinstance(prices, list) else [],
        }
    return table


def _run_tail_insights(run_file: Path, tail_bytes: int = 65536,
                       marker_scan_cap: int = 4 << 20) -> dict:
    """读取 run 产物尾部：ClaudeCode 最后一条总结 + 实际驱动的 LLM + usage 四分项 + 终态原因。

    summary 优先取 result 事件的 result 字段（run 最终总结，markdown 文本，
    与 runner.py 提取产物口径一致）；无 result（运行中/中断）时回退最后一条
    assistant 文本。llm 取最后一个 provider_marker 事件（attempt 启动时写入，
    failover 切换产生多个，取最后 = 实际完成 run 的网关）。usage 取 result 事件
    的 usage 字段（add-model-billing-cost-display D2，成本本地计算数据源；
    result 是流终态必在尾窗内，无 result → None）。reason 取终态事件的人类
    可读原因（error 事件的 error 字段 / interrupted、cancelled 事件的 reason
    字段；终态后置不变量保证末行即终态，遍历顺序天然取末行生效），时间轴
    run 节点据此展示失败/中止原因，无终态或成功 run 为空串。只读文件尾部
    tail_bytes 字节避免时间轴加载全量扫描；seek 产生的截断首行直接丢弃。
    marker 可能落在 attempt 大量输出之外（尾窗扫不到），此时按 256KB 块
    向前回扫（上限 marker_scan_cap），仍无则留空。
    """
    try:
        size = run_file.stat().st_size
        with run_file.open("rb") as f:
            if size > tail_bytes:
                f.seek(-tail_bytes, 2)
            data = f.read().decode("utf-8", errors="replace")
    except OSError:
        return {"summary": "", "llm": "", "usage": None, "reason": ""}

    def parse_chunk(raw: str, skip_first: bool) -> tuple:
        lines = raw.split("\n")
        if skip_first:
            lines = lines[1:]
        result_text = last_asst = llm = ""
        usage = None
        reason = ""
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            t = e.get("type")
            if t == "provider_marker":
                m, p = e.get("model"), e.get("provider")
                if m and p:
                    llm = f"{m}@{p}"
            elif t == "result":
                rt = e.get("result")
                if isinstance(rt, str) and rt.strip():
                    result_text = rt.strip()
                u = e.get("usage")
                if isinstance(u, dict) and u:
                    usage = u
            elif t == "assistant":
                c = e.get("content")
                if isinstance(c, str) and c.strip():
                    last_asst = c.strip()
                elif isinstance(c, list):
                    texts = [b.get("text", "") for b in c
                             if isinstance(b, dict) and b.get("type") == "text"]
                    joined = "\n".join(t for t in texts if t.strip())
                    if joined.strip():
                        last_asst = joined.strip()
            elif t in _RUN_TERMINAL_STATUS_MAP and t != "result":
                # 终态原因：error 事件原因在 error 字段，interrupted/cancelled
                # 在 reason 字段；末行终态后处理，天然取末行生效
                reason = str(e.get("error") or e.get("reason") or "").strip()
        return result_text or last_asst, llm, usage, reason

    summary, llm, usage, reason = parse_chunk(data, skip_first=size > tail_bytes)
    if not llm and size > tail_bytes:
        chunk = 262144
        floor = max(0, size - tail_bytes - marker_scan_cap)
        pos = size - tail_bytes
        with run_file.open("rb") as f:
            while pos > floor and not llm:
                start = max(floor, pos - chunk)
                f.seek(start)
                raw = f.read(pos - start).decode("utf-8", errors="replace")
                _, llm, _, _ = parse_chunk(raw, skip_first=start > 0)
                pos = start
    return {"summary": summary, "llm": llm, "usage": usage, "reason": reason}


def compute_run_cost(usage: "dict | None", model_used: str,
                     provider_used: str,
                     billing_table: "dict | None") -> "float | None":
    """按「provider 卡片开关 + 行 model 匹配」计算单 run 成本（design D2）。

    成本 = input/1M×输入价 + output/1M×输出价 + cache_read/1M×缓存读价
         + cache_creation/1M×缓存写价。
    usage 缺失、provider 卡片计费未开启、该卡片无匹配 model 价格行（或价格行
    字段残缺）→ 返回 None（unpriced，展示「成本不可用」，绝不回退网关回传金额）。
    匹配键以 run 产物 provider_marker 的实际网关与模型为准（failover 切换后
    成本归属仍精确）。

    Args:
        usage: run 产物 result 事件 usage 字段（dict 或 None）
        model_used: 实际驱动模型名（provider_marker 的 model）
        provider_used: 实际驱动网关名（provider_marker 的 provider）
        billing_table: per-provider 计价表 {provider_name: {enabled, prices}}
            （_load_billing_config 产物）或 None
    """
    if not isinstance(usage, dict):
        return None
    if not isinstance(billing_table, dict) or not model_used or not provider_used:
        return None
    card = billing_table.get(provider_used)
    if not isinstance(card, dict) or not card.get("enabled"):
        return None
    price_keys = {
        "input": ("input_tokens", "input_per_million"),
        "output": ("output_tokens", "output_per_million"),
        "cache_read": ("cache_read_input_tokens", "cache_read_per_million"),
        "cache_creation": ("cache_creation_input_tokens", "cache_creation_per_million"),
    }
    for row in card.get("prices") or []:
        if not isinstance(row, dict):
            continue
        if row.get("model") != model_used:
            continue
        try:
            total = 0.0
            for _part, (usage_key, price_key) in price_keys.items():
                price = row.get(price_key)
                if price is None:
                    return None
                tokens = int(usage.get(usage_key) or 0)
                total += tokens / 1_000_000.0 * float(price)
            return total
        except (TypeError, ValueError):
            return None
    return None


def _split_llm_marker(llm: str) -> tuple:
    """把 provider_marker 的 `model@provider` 串拆回 (model, provider)。

    无 @ 的残留串视为只有模型名（provider 置空 → 无法匹配价格，判不可计价）。
    """
    if not llm:
        return "", ""
    if "@" in llm:
        model, provider = llm.rsplit("@", 1)
        return model, provider
    return llm, ""


def _admin_events_for_spec(project_root, spec_name: str) -> list:
    """过滤当前 SPEC 关联的 admin 运维事件，输出 kind="admin" 时间轴节点。

    数据源复用 AdminStore.read_all()（既有带锁、容错读，缺失/损坏返回 []）：
    - 过滤：kind in {escalation, disposition} 且 spec 精确匹配目标 SPEC；
      缺 spec 字段（历史脏数据）跳过，不误挂到当前 SPEC。
    - 归并：同 admin_run_id 的 disposition 组内存在非 pending 最终处置时
      （result/status 非 pending），仅保留最新最终处置，避免时间轴出现
      「永久处置中」；无最终处置保留 pending；无 admin_run_id 的记录独立成节点
      （与运维记录页 best_by_run 归并语义一致，不引入置顶/_pin 页面概念）。
    - 输出节点字段：time=created、kind="admin"、record_kind、signal_type、
      severity、description；状态字段 escalation 取 handled、disposition 取 result。
    - 读取异常 fail-open 返回空列表，时间轴照常渲染 state/run 两类节点。
    """
    from core.admin_store import AdminStore, DISPOSITION, ESCALATION
    try:
        records = AdminStore(project_root).read_all()
    except Exception:
        return []
    if not records:
        return []
    spec_records = [
        r for r in records
        if r.get("kind") in (ESCALATION, DISPOSITION)
        and r.get("spec") == spec_name
    ]
    if not spec_records:
        return []

    # 按 admin_run_id 归并 disposition（轻量 best_by_run 语义）：
    # 非 pending 优先于 pending；同为非 pending 取最新；无 admin_run_id 独立。
    best_by_run: dict = {}
    for rec in spec_records:
        if rec.get("kind") != DISPOSITION:
            continue
        rid = rec.get("admin_run_id") or f"run-{id(rec)}"
        status = rec.get("result") or rec.get("status")
        is_pending = status == "pending"
        existing = best_by_run.get(rid)
        if existing is None:
            best_by_run[rid] = (is_pending, rec)
            continue
        if is_pending and not existing[0]:
            continue  # 已有最终处置，pending 被替代
        if not is_pending and existing[0]:
            best_by_run[rid] = (False, rec)
        elif (rec.get("created") or "") > (existing[1].get("created") or ""):
            best_by_run[rid] = (is_pending, rec)

    nodes: list[dict] = []
    for rec in spec_records:
        if rec.get("kind") == DISPOSITION:
            rid = rec.get("admin_run_id") or f"run-{id(rec)}"
            if best_by_run.get(rid, (False, None))[1] is not rec:
                continue  # 该 pending 已被最终处置替代
        node = {
            "time": rec.get("created") or "",
            "kind": "admin",
            "record_kind": rec.get("kind"),
            "signal_type": rec.get("signal_type"),
            "severity": rec.get("severity"),
            "description": rec.get("description") or "",
        }
        if rec.get("kind") == ESCALATION:
            node["handled"] = bool(rec.get("handled"))
        else:
            node["result"] = rec.get("result") or rec.get("status")
        nodes.append(node)
    return nodes


def get_spec_timeline(project_root, spec_name: str, created: str = "") -> list:
    """构建 SPEC 生命周期时间轴（按时间排序）。

    数据源：
    - 事件日志（fenixd*.log）中的 `Transition: <spec> from → to` → 状态节点
    - `.fenix/runs/` 运行产物 → 运行节点（可点击展开 LLM 对话）

    日志读取窗口按 created 锚定（_read_log_window_from）：从 spec 创建时间读到
    文件尾，长周期 spec 的早期事件不再被尾部 1MB 尾窗静默截断；created 缺失
    （存量/归档条目）退化为全文件读取。

    每条:
    - 状态: {time, kind:"state", from, to, reason}  （回退节点带 reason）
    - 运行: {time, kind:"run", run_id, agent_type, status}
    """
    logs_dir = Path(project_root) / ".fenix" / "logs"
    events: list[dict] = []
    errors_at: list[tuple] = []   # (timestamp, error) —— Agent 记录的 error，作为回退原因
    # (timestamp, new_status, err) —— update_spec 直写的 status 变更（打回路径，
    # 无 Transition 行；add-agent-prompt-files 事故：时间轴上看不到打回与原因）
    status_updates: list[tuple] = []
    verify_start_ts = ""   # 最近一轮 verify_engine「开始验证」日志时刻（报告只有完成时刻）

    if logs_dir.is_dir():
        try:
            log_files = sorted(logs_dir.glob("fenixd*.log"), reverse=True)
        except OSError:
            log_files = []
        for lf in log_files:
            try:
                # created 锚定窗口（原尾部 1MB 尾窗对早期事件静默截断）；
                # 锚点早于文件首行 → 整文件，锚点晚于文件尾 → 仅尾块，量均有限
                content = _read_log_window_from(
                    Path(project_root), lf, created).decode(
                    "utf-8", errors="replace"
                )
            except OSError:
                continue
            pat = re.compile(r"Transition: " + re.escape(spec_name) + r"\s+([\w-]+)\s*→\s*([\w-]+)")
            for line in content.split("\n"):
                if spec_name not in line:
                    continue
                try:
                    entry = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                msg = entry.get("message", "")
                ts = entry.get("timestamp", "")
                m = pat.search(msg)
                if m:
                    frm, to = m.group(1), m.group(2)
                    # 方向单源：backward 按生命周期序判定（与打回重建路径
                    # 同式），Transition 回退判定复用为该字段来源
                    backward = _LIFECYCLE_ORDER.get(to, 9) < _LIFECYCLE_ORDER.get(frm, 9)
                    reason = _backtrack_reason(frm, to) if backward else ""
                    events.append({"time": ts, "kind": "state", "from": frm, "to": to,
                                   "reason": reason, "backward": backward})
                # 带引号全匹配（写点唯一于 state_machine.update_spec 的
                # f"Updated SPEC '{spec_name}'"）：子串匹配会让前缀名 spec
                # （如 add-foo）吸收姊妹 spec（add-foo-ui）的状态更新
                if "Updated SPEC" in msg and f"'{spec_name}'" in msg:
                    updates = entry.get("context", {}).get("updates", {}) or {}
                    err = updates.get("error")
                    if err:
                        errors_at.append((ts, str(err)))
                    new_status = updates.get("status")
                    if new_status:
                        status_updates.append(
                            (ts, str(new_status), str(err) if err else ""))
                if "开始验证" in msg and f"'{spec_name}'" in msg:
                    # verify_engine 每轮开跑的唯一一行（多轮验证取最后一轮，
                    # 与每轮覆盖的 report.json 配对）
                    verify_start_ts = ts

    # 运行节点（含归档：旧 spec 的 run 产物被清理后时间轴仍可回看）。
    # improve-provider-billing-config（D2）：计价表非空（有任一声明 billing 的
    # 卡片）时进入计价分支，逐 run 按「实际网关卡片开关 + 行 model 匹配」现算
    # cost_usd（None 不下发）；表空时整条时间轴无成本字段（前端不渲染）。
    billing_table = _load_billing_config(project_root)
    for r in get_runs(project_root, spec_name, include_archive=True):
        insights = _run_tail_insights(_resolve_run_file(project_root, r["run_id"]))
        node = {"time": r["started"], "kind": "run", "run_id": r["run_id"],
                "agent_type": r["agent_type"], "status": r["status"],
                "spec": r.get("spec"),
                "duration_seconds": r.get("duration_seconds"),
                "summary": insights["summary"], "llm": insights["llm"],
                "reason": insights["reason"]}
        if billing_table:
            model, provider = _split_llm_marker(insights["llm"])
            cost = compute_run_cost(insights["usage"], model, provider, billing_table)
            if cost is not None:
                node["cost_usd"] = cost
        events.append(node)

    # ── 验证执行节点：verify_engine 是确定性引擎而非 agent run（不产生
    # runs/*.jsonl），时间轴原本不可见——full 模式 testing→verified 之间无节点
    # 打断折叠，观感是「实现完直接连跳已推送」（fix-provider-transient-backoff
    # 误读事故）。report.json 仅引擎验证写入（fast-track 的 agent 自验不产生），
    # 时间取日志「开始验证」行（引擎开始时刻，报告只有完成时刻）；日志行缺失
    # 退化用报告完成时刻（与 verified 转换同秒，靠 _timeline_sort_key 第三键
    # 精确时间排在 verified 之前）。多轮验证 report 每轮覆盖 → 只留最后一轮。
    report = parse_report(project_root, spec_name)
    if report.get("exists") and not report.get("error"):
        summary = report.get("summary") or {}
        rep_ts = str(report.get("timestamp", "") or "")
        # 时间优先取日志「开始验证」行（引擎开始时刻）；缺失退化报告完成时刻
        v_time = verify_start_ts or rep_ts
        if v_time:
            v_node: dict = {
                "time": v_time, "kind": "verify",
                "total": summary.get("total"),
                "passed": summary.get("passed"),
                "failed": summary.get("failed"),
                "warnings": summary.get("warnings"),
                "errors": summary.get("errors"),
            }
            if verify_start_ts and rep_ts:
                d = _ts_delta(rep_ts, verify_start_ts)
                if d is not None and d >= 0:
                    v_node["duration_seconds"] = int(d)
            if report.get("env_error"):
                v_node["env_error"] = str(report["env_error"])[:200]
            events.append(v_node)

    # ── 打回节点重建：update_spec 直写 status 的变更（无 Transition 行）补建状态节点 ──
    # transition() 成对写的 Updated SPEC 行（与 Transition 节点 Δt<2s 且目标相同）去重跳过；
    # 未匹配的按时间与 Transition 节点合流推演 current status 得 from（窗口截断推不出 → "?"），
    # reason 取同行 error（精确）；无 error 时回退 _backtrack_reason 兜底（允许 errors_at 就近覆盖）。
    trans_states = [e for e in events if e.get("kind") == "state"]
    unmatched: list[tuple] = []
    for ts, new_status, err in status_updates:
        paired = any(
            (d := _ts_delta(t2["time"], ts)) is not None and d < 2
            and t2["to"] == new_status
            for t2 in trans_states
        )
        if not paired:
            unmatched.append((ts, new_status, err))
    if unmatched:
        merged = sorted(
            [(e["time"], 0, "t", e["to"], "") for e in trans_states]
            + [(ts, 1, "u", ns, err) for ts, ns, err in unmatched],
            key=lambda x: (str(x[0]), x[1]),
        )
        current: "str | None" = None
        for ts, _, tag, to, err in merged:
            if tag == "t":
                current = to
                continue
            frm = current if current is not None else "?"
            # 方向按生命周期序判定（与 Transition 路径同式）。前向节点不落
            # 「状态回退」兜底文案：无同行 err 时 reason 置空（可被折叠链
            # 合并，与 Transition 前向节点行为一致）——从结构上消除前向节点
            # 被 errors_at 就近覆写传染的通道；有同行 err 时 reason=err
            # （_precise_reason 保护不被覆写）。回退节点维持现状。
            backward = _LIFECYCLE_ORDER.get(to, 9) < _LIFECYCLE_ORDER.get(frm, 9)
            if backward:
                reason = err[:120] if err else _backtrack_reason(frm, to)
            else:
                reason = err[:120] if err else ""
            events.append({"time": ts, "kind": "state", "from": frm, "to": to,
                           "reason": reason, "backward": backward,
                           "_precise_reason": bool(err)})
            current = to

    # admin 运维事件节点（escalation + disposition）：与 state/run 节点统一
    # 按事件时间排序（admin 在 _timeline_sort_key 中 rank=1，夹在 state/run 间）。
    # 折叠逻辑零改动：admin 节点非 state，天然打断连续前向状态折叠。
    events.extend(_admin_events_for_spec(project_root, spec_name))

    # 排序：解析时间戳 + 同秒内 state 先于 run（_timeline_sort_key 内注释说明根因）
    events.sort(key=_timeline_sort_key)

    # 连续的前向状态转换折叠为一次（回退/运行节点打断）
    events = _collapse_timeline(events)

    # 回退节点补充 Agent 记录的 error 作为原因（取时间最近的一条，10 分钟内）；
    # 打回重建节点（_precise_reason）reason 已是同行精确 error，不覆盖
    if errors_at:
        for e in events:
            if e.get("kind") != "state" or not e.get("reason") or e.get("_precise_reason"):
                continue
            deltas = [(d, err) for (ts, err) in errors_at
                      if (d := _ts_delta(ts, e["time"])) is not None]
            if deltas:
                d, err = min(deltas, key=lambda x: x[0])
                if d < 600:   # 10 分钟内匹配到 Agent 记录的 error
                    e["reason"] = err[:120]
    for e in events:
        e.pop("_precise_reason", None)   # 内部标记不外泄
    return events


def _collapse_timeline(events: list) -> list:
    """把连续的前向状态转换折叠为一次（from[首] → to[尾]）。

    规则：
    - 连续出现的「前向状态节点」（无 reason）合并为一个节点，展示整体跨度；
      如 drafted→ready / ready→implementing / … → 折叠为 drafted → implementing。
      折叠时携带 chain（完整状态序列，首尾与 from/to 一致）：前端展开渲染
      全部中间状态不省略（fast-track 连跳 implemented→testing→verified→
      done→pushed 若只显示一头一尾，会掩盖 testing/verified 等真实途经状态）。
    - 回退节点（带 reason，如 testing→bug-found）与运行节点保持独立，并打断合并。
    """
    out: list[dict] = []
    buf: list[dict] = []   # 待合并的前向状态节点缓冲

    def _flush() -> dict:
        # 折叠缓冲按构造只收前向节点（回退节点带 reason 天然打断），backward=false
        node = {
            "time": buf[0]["time"], "kind": "state",
            "from": buf[0]["from"], "to": buf[-1]["to"], "reason": "",
            "backward": False,
        }
        if len(buf) > 1:
            node["chain"] = [buf[0]["from"]] + [b["to"] for b in buf]
        return node

    for e in events:
        if e.get("kind") == "state" and not e.get("reason"):
            buf.append(e)
            continue
        # 遇到回退状态 / 运行节点 / 其它 → 先冲刷缓冲，再追加当前事件
        if buf:
            out.append(_flush())
            buf = []
        out.append(e)
    if buf:
        out.append(_flush())
    return out


def _parse_iso_ts(ts: str):
    """解析 ISO 时间戳（兼容 Z 后缀与 +00:00），失败返回 None。"""
    try:
        from datetime import datetime as _dt
        return _dt.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def _timeline_sort_key(e: dict):
    """时间轴排序键：(秒截断时间, kind 次序, 精确时间)。

    不能直接对原始字符串排序：日志时间为微秒+Z（…31.212625Z），运行 started
    为秒级+00:00（…31+00:00），同一秒内 '+' < '.' 会把运行节点排到状态转移前。
    也不能只按解析后时间排序：run started 取自 run_id 的 int(time.time()) 秒
    截断，真实启动在该秒内、且必然晚于同秒发生的状态转移（先 transition 后
    spawn，见 pm_engine/dispatch.py），故同秒内 state 恒先于 run。
    admin 运维节点（add-timeline-admin-events）夹在中间：同秒内的真实时序是
    「状态转移（testing→bug-found）→ admin 处置完成 → 触发重派的 run 启动」，
    kind 次序显式映射为 state=0、admin=1、run=2（state/run 相对次序不变）。
    verify（验证执行节点）与 state 同 rank：退化场景（日志「开始验证」行缺失）
    节点取报告完成时刻、与 verified 转换同秒且真实次序在前（报告先落盘），
    须靠第三键精确时间排在 verified 之前；正常场景（引擎开始时刻）独占一秒，
    rank 不参与。
    解析失败的事件按原字符串排在末尾，保持稳定。
    """
    dt = _parse_iso_ts(e.get("time", ""))
    if dt is None:
        from datetime import datetime as _dt, timezone as _tz
        return (_dt.max.replace(tzinfo=_tz), 2, str(e.get("time", "")))
    kind_rank = {"state": 0, "verify": 0, "admin": 1, "run": 2}.get(e.get("kind"), 2)
    return (dt.replace(microsecond=0), kind_rank, dt)


def _ts_delta(a: str, b: str):
    """两个 ISO 时间戳的秒级差值（解析失败返回 None）。"""
    ta = _parse_iso_ts(a)
    tb = _parse_iso_ts(b)
    if ta is None or tb is None:
        return None
    return abs((ta - tb).total_seconds())


def _timeline_with_retry(timeline: list, project_root, entry: dict) -> list:
    """把 spec 当前实现重试轮次附到时间轴最后一个运行节点（retry-display）。

    重派计数是 spec 级状态（STATE.md `_retry_count`），run 产物无逐节点历史
    快照——只在最新 run 节点呈现当前值（>0 时），历史节点不伪造。分母取
    项目 config `agents.max_retries`（缺失/异常回退 3，与 dispatch 取值默认
    一致；read_effective_config 是受管键白名单视图，不含 max_retries）。
    """
    try:
        count = int(entry.get("_retry_count") or 0)
    except (TypeError, ValueError):
        count = 0
    if count <= 0 or not timeline:
        return timeline
    max_r = 3
    try:
        with (Path(project_root) / ".fenix" / "config.yaml").open(
                "r", encoding="utf-8") as f:
            max_r = int(((yaml.safe_load(f) or {}).get("agents") or {})
                        .get("max_retries") or 3)
    except (OSError, yaml.YAMLError, TypeError, ValueError):
        pass
    for e in reversed(timeline):
        if e.get("kind") == "run":
            e["retry_count"] = count
            e["retry_max"] = max_r
            break
    return timeline


def _cost_summary_from_timeline(timeline: list) -> dict:
    """汇总时间轴内可计价 run 的成本（add-model-billing-cost-display D4）。

    Returns: {"computed_usd": float|None, "priced_runs": int, "unpriced_runs": int}
    可计价 run 的成本求和；至少一个可计价 run 时 computed_usd 非 None（否则为
    None = 全部不可计价，界面展示「成本不可用」）。
    """
    total = 0.0
    priced = 0
    unpriced = 0
    for e in timeline:
        if e.get("kind") != "run":
            continue
        cost = e.get("cost_usd")
        if cost is None:
            unpriced += 1
        else:
            priced += 1
            total += cost
    return {
        "computed_usd": total if priced else None,
        "priced_runs": priced,
        "unpriced_runs": unpriced,
    }


def spec_detail(project_root, spec_name: str, entry: dict) -> dict:
    """单个 SPEC 的完整详情（/api/specs/<spec>）。"""
    report = parse_report(project_root, spec_name)
    bugs = parse_bugs(project_root, spec_name)
    scenarios = report.get("scenarios", []) if report.get("exists") and not report.get("error") else []
    # 场景内截图同样归一化为文件名（report.json 存的是服务器本地绝对路径）
    scenarios = [
        {**sc, "screenshots": [os.path.basename(s) for s in sc.get("screenshots", []) if isinstance(s, str) and s.strip()]}
        if isinstance(sc, dict) else sc
        for sc in scenarios
    ]
    # 合成报告（report.json 缺失/无 scenarios）时，从 .fenix-run-result.json 兜底取
    # 逐场景明细，使 Dashboard「场景结果」页签即便在无 report.json 的合成产物下也能
    # 渲染逐场景节点（fix-add-verify-report-gate Bug 2 根因）。
    if not scenarios:
        scenarios = parse_run_result_scenarios(project_root, spec_name)
    screenshots = list_screenshots(project_root, spec_name)
    # 含归档：spec 详情「运行历史」可回看已归档的旧 run
    runs = get_runs(project_root, spec_name, include_archive=True)
    verdict = parse_verdict(project_root, spec_name)
    spec_status = entry.get("status", "")
    # add-fast-track-mode（task 7.1）：执行模式（读 .spec.yaml，缺省 full）
    from core.spec_mode import read_spec_mode
    mode = read_spec_mode(project_root, spec_name)
    # 时间轴（含运行节点 cost_usd；计费开关关闭时 get_spec_timeline 不下发）；
    # created 锚定读取窗口：STATE 条目的 created 使早期事件不被日志尾窗截断
    timeline = _timeline_with_retry(
        get_spec_timeline(project_root, spec_name, entry.get("created") or ""),
        project_root, entry)
    # improve-provider-billing-config（D2）：SPEC 级成本合计——计价表非空
    # （有任一声明 billing 的卡片）时进入计价分支；单 run 计价由匹配函数自行
    # 判定未开启卡片 → None（未开启卡片 run 不计入 priced_runs）。
    cost_summary = None
    billing_table = _load_billing_config(project_root)
    if billing_table:
        cost_summary = _cost_summary_from_timeline(timeline)
    return {
        "name": spec_name,
        "status": entry.get("status"),
        "mode": mode,
        "priority": entry.get("priority"),
        "created": entry.get("created"),
        "updated": entry.get("updated"),
        "error": entry.get("error"),
        "branch": entry.get("branch"),
        "implementer_run": entry.get("implementer_run"),
        "tester_run": entry.get("tester_run"),
        "depends_on": entry.get("depends_on"),
        "tasks": parse_tasks(project_root, spec_name, spec_status),
        "tasks_note": tasks_note(project_root, spec_name, spec_status),
        "run_progress": run_task_progress(project_root, spec_name),
        "verify_progress": parse_verify_progress(project_root, spec_name),
        # verification-phase-progress：出题进度（生成阶段 verify_progress 为空态，
        # 详情页验证进度卡片据此展示「出题 N/M」而非「暂无验证进度」）
        "generation": spec_generation_progress(project_root, spec_name, entry),
        "report": {
            "exists": report.get("exists", False),
            "error": report.get("error"),
            "timestamp": report.get("timestamp"),
            "summary": report.get("summary"),
            # add-planready-artifact-gate D4：降级标注（框架合成报告时从
            # degrade_context.json 注入 report.json 顶层 degrade_annotation），
            # 前端报告区据此条件渲染「⚠️ 降级说明」一行提示；无降级时缺省。
            "degrade_annotation": report.get("degrade_annotation"),
        },
        "scenarios": scenarios,
        "bugs": bugs,
        # fix-verify-verdict-visibility：被分类过滤（非 product-bug）的失败/错误场景摘要，
        # 与 bugs 互补互斥；旧格式 report.json（无 classification）不产生条目
        "filtered_failures": parse_filtered_failures(project_root, spec_name),
        "screenshots": screenshots,
        "runs": runs,
        "verdict": verdict,
        "timeline": timeline,
        # add-spec-detail-duration：详情页「耗时」与列表页「耗时」列同源同口径
        # （runs 已含归档，见 _spec_total_duration）
        "total_duration": _spec_total_duration(project_root, spec_name, entry, runs),
        # add-model-billing-cost-display：SPEC 级成本合计（计费关闭时缺省 None）
        "cost_summary": cost_summary,
        # add-cost-observability（D2）：治理区展示的累计 token 与成本可用性标记。
        # _cost_usd 仅在网关真实回传时存在（不伪造金额，spec「金额展示不伪造」）。
        "token_usage": _token_usage_view(entry),
    }


def _token_usage_view(entry: dict) -> dict:
    """把 STATE 内部 token 字段规整为治理区展示结构（add-cost-observability D2）。

    返回固定结构：
        {
          "tokens_in": int, "tokens_out": int,
          "cache_creation_input_tokens": int | None,  # 分项自 add-cache-hit-display 起累计；历史 spec 无字段→None
          "cache_read_input_tokens": int | None,
          "cost_usd": float | None,    # None = 网关未回传，界面展示「成本不可用」
          "cost_available": bool,       # 成本字段是否可展示
        }
    STATE 持久累计 _tokens_in/_tokens_out/_cost_usd 及缓存分项 _cache_read_tokens/
    _cache_creation_tokens（分项 cache 入 input）；分项为 None 表示该 spec 未记录过
    分项数据（历史条目），前端不显示缓存括号。
    """
    if not isinstance(entry, dict):
        entry = {}
    tokens_in = int(entry.get("_tokens_in", 0) or 0)
    tokens_out = int(entry.get("_tokens_out", 0) or 0)
    # 分项字段：缺失（历史 spec）保持 None，存在则规整为 int（STATE 读出为字符串）
    cache_read = entry.get("_cache_read_tokens")
    cache_creation = entry.get("_cache_creation_tokens")
    cache_read_val = int(cache_read) if cache_read is not None else None
    cache_creation_val = int(cache_creation) if cache_creation is not None else None
    cost = entry.get("_cost_usd")
    if cost is None:
        cost_val = None
        cost_available = False
    else:
        try:
            cost_val = float(cost)
            cost_available = True
        except (TypeError, ValueError):
            cost_val = None
            cost_available = False
    return {
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cache_creation_input_tokens": cache_creation_val,
        "cache_read_input_tokens": cache_read_val,
        "cost_usd": cost_val,
        "cost_available": cost_available,
    }


def _parse_spec_ts(raw) -> "datetime | None":
    """解析 STATE 条目的 updated 时间戳；缺失/非法返回 None。naive 视为本地时间。"""
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
    except (ValueError, TypeError):
        return None
    return ts.astimezone() if ts.tzinfo is None else ts


def _updated_spec_counts(entries: dict, today_start: datetime, week_start: datetime) -> tuple:
    """统计 updated 落在今日（本地自然日）/ 近7天（滚动窗口）的 spec 数。"""
    today = week = 0
    for entry in entries.values():
        ts = _parse_spec_ts(entry.get("updated"))
        if ts is None:
            continue
        if ts >= week_start:
            week += 1
        if ts >= today_start:
            today += 1
    return today, week


def _token_recent_entries(entries: dict, project_name: str) -> list:
    """收集各 spec 的累计 token 消耗（_tokens_in/_tokens_out 为 STATE 持久累计值）。

    跳过无消耗数值（tokens==0）的 spec——消费方展示「最近 20 个有数值的 spec」。
    """
    out = []
    for name, entry in entries.items():
        tokens = int(entry.get("_tokens_in", 0) or 0) + int(entry.get("_tokens_out", 0) or 0)
        if tokens <= 0:
            continue
        out.append({
            "project": project_name,
            "spec": name,
            "tokens": tokens,
            "updated": entry.get("updated") or "",
            "_ts": _parse_spec_ts(entry.get("updated")),
        })
    return out


def overview(registry_projects: list) -> dict:
    """跨项目概览（/api/overview）。registry_projects 为 registry.discover() 结果。"""
    now = datetime.now().astimezone()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)
    projects = []
    totals = {"spec_count": 0, "task_done": 0, "task_total": 0,
              "problems": 0, "active_runs": 0,
              "spec_updated_today": 0, "spec_updated_week": 0,
              "active_runs_by_type": {}}
    status_counts = {}
    token_entries = []
    for p in registry_projects:
        if not p.get("exists"):
            projects.append({
                "name": p["name"], "path": p["path"], "discovered": p.get("discovered", False),
                "exists": False, "daemon": "stopped", "error": "项目路径不存在",
            })
            continue
        s = project_summary(p["path"], p["name"], p["path"])
        s["discovered"] = p.get("discovered", False)
        s["exists"] = True
        projects.append(s)
        totals["spec_count"] += s["spec_count"]
        totals["task_done"] += s["task_done"]
        totals["task_total"] += s["task_total"]
        totals["problems"] += s["problems"]
        totals["active_runs"] += s["active_runs"]
        for at, n in (s.get("active_runs_by_type") or {}).items():
            totals["active_runs_by_type"][at] = totals["active_runs_by_type"].get(at, 0) + n
        entries = parse_state(p["path"])
        t_today, t_week = _updated_spec_counts(entries, today_start, week_start)
        totals["spec_updated_today"] += t_today
        totals["spec_updated_week"] += t_week
        token_entries.extend(_token_recent_entries(entries, p["name"]))
        for st, n in s["status_counts"].items():
            status_counts[st] = status_counts.get(st, 0) + n
    totals["status_counts"] = status_counts
    token_entries.sort(key=lambda e: (e["_ts"].timestamp() if e["_ts"] else 0.0), reverse=True)
    for e in token_entries:
        e.pop("_ts", None)
    return {"projects": projects, "totals": totals,
            "token_usage": {"recent": token_entries[:20]}}


# ── 配置读写（受管键：llm / agents.* / gates.approve_mode / runs / verify.*） ──

# Dashboard 管理的配置键子集：写回时只更新这些键，其它键原样保留
_MANAGED_KEYS = ["llm", "agents", "gates", "runs", "verify", "hooks"]
# 在 agents 下管理的子键白名单
_AGENTS_MANAGED_SUBKEYS = ["models", "max_concurrent", "run_timeout_seconds", "max_turns", "daily_run_limit", "token_budget_millions", "impl_run_budget", "verify_redo_budget"]

# 用户级配置文件路径（与项目级同名 `.fenix/config.yaml`，作用域由所在目录决定）
USER_CONFIG_PATH = Path.home() / ".fenix" / "config.yaml"

# 受管键的来源标注键（前端用于「继承自用户级」badge）
_SOURCE_KEYS = ["llm", "agents.models", "agents.max_concurrent",
                "agents.run_timeout_seconds", "agents.max_turns", "agents.daily_run_limit",
                "agents.token_budget_millions", "agents.impl_run_budget", "agents.verify_redo_budget",
                "gates.approve_mode",
                # add-draft-promotion-gate：草稿晋升模式
                "gates.promote_mode",
                # add-daily-self-review：admin.self_review 三键
                "admin.self_review",
                # add-settings-system-tab：admin.* 受管键（5 键）
                "admin.enabled", "admin.interval_minutes",
                "admin.escalation_cooldown_minutes",
                "admin.merge_breaker_threshold", "admin.shutdown_drain_seconds",
                # add-bug-repair-mode-config：bug-found 修复方式（inplace/derive）
                "admin.bug_repair_mode",
                # 验证契约键（verify.*：静态服务范围 / worktree 依赖供给模式）
                "verify.static_scope", "verify.deps_mode",
                # add-planner-efficiency：planner 生成节流上限
                "verify.planner_max_concurrent",
                # add-spec-hooks：两级 hook 订阅配置（global + specs）
                "hooks",
                # fix-provider-transient-backoff（D6）：瞬断治理五键
                "agents.transient_backoff_schedule",
                "agents.transient_redispatch_delay_seconds",
                "agents.transient_break_threshold",
                "agents.transient_break_window_seconds",
                "agents.transient_break_cooldown_seconds"]

# 受管键的默认回显值（add-daily-self-review；与 ConfigLoader.get_self_review_config
# 保持一致：enabled/read_todo 缺省 false，run_at 缺省 02:00）
_DEFAULT_SELF_REVIEW = {"enabled": False, "run_at": "02:00", "read_todo": False}

_CONFIG_HEADER_COMMENT = (
    "# Fenix 配置文件\n"
    "# 本文件可通过 Dashboard 或手工编辑修改；修改后需重启 daemon 生效。\n"
    "# 敏感字段（如 apikey）请妥善保管，.fenix/ 目录已 gitignore。\n"
    "\n"
)


def _managed_key_sources(raw: dict) -> dict:
    """计算每个受管键的来源层级：在该文件中显式定义 → "project"，否则 "user"。

    "user" 表示该键未在此文件定义，由用户级配置或内置默认值兜底。
    """
    sources = {k: "user" for k in _SOURCE_KEYS}
    if isinstance(raw.get("llm"), dict):
        sources["llm"] = "project"
    agents_raw = raw.get("agents")
    if isinstance(agents_raw, dict):
        if isinstance(agents_raw.get("models"), dict):
            sources["agents.models"] = "project"
        if "max_concurrent" in agents_raw:
            sources["agents.max_concurrent"] = "project"
        if "run_timeout_seconds" in agents_raw:
            sources["agents.run_timeout_seconds"] = "project"
        if "max_turns" in agents_raw:
            sources["agents.max_turns"] = "project"
        if "daily_run_limit" in agents_raw:
            sources["agents.daily_run_limit"] = "project"
        if "token_budget_millions" in agents_raw:
            sources["agents.token_budget_millions"] = "project"
        if "impl_run_budget" in agents_raw:
            sources["agents.impl_run_budget"] = "project"
        if "verify_redo_budget" in agents_raw:
            sources["agents.verify_redo_budget"] = "project"
        # fix-provider-transient-backoff（D6）：瞬断治理五键显式定义 → project
        for _tk in ("transient_backoff_schedule", "transient_redispatch_delay_seconds",
                    "transient_break_threshold", "transient_break_window_seconds",
                    "transient_break_cooldown_seconds"):
            if _tk in agents_raw:
                sources[f"agents.{_tk}"] = "project"
    gates_raw = raw.get("gates")
    if isinstance(gates_raw, dict) and "approve_mode" in gates_raw:
        sources["gates.approve_mode"] = "project"
    # add-draft-promotion-gate：草稿晋升模式显式定义 → project
    if isinstance(gates_raw, dict) and "promote_mode" in gates_raw:
        sources["gates.promote_mode"] = "project"
    verify_src = raw.get("verify")
    if isinstance(verify_src, dict):
        if "static_scope" in verify_src:
            sources["verify.static_scope"] = "project"
        if "deps_mode" in verify_src:
            sources["verify.deps_mode"] = "project"
        if "planner_max_concurrent" in verify_src:
            sources["verify.planner_max_concurrent"] = "project"
    # add-daily-self-review：admin.self_review 段显式定义 → project
    admin_raw = raw.get("admin")
    if isinstance(admin_raw, dict) and isinstance(admin_raw.get("self_review"), dict):
        sources["admin.self_review"] = "project"
    # add-settings-system-tab：admin.* 受管键（5 键）显式定义 → project
    if isinstance(admin_raw, dict):
        for _k in ("enabled", "interval_minutes", "escalation_cooldown_minutes",
                   "merge_breaker_threshold", "shutdown_drain_seconds",
                   "bug_repair_mode"):
            if _k in admin_raw:
                sources[f"admin.{_k}"] = "project"
    # add-spec-hooks：hooks 段显式定义 → project
    if isinstance(raw.get("hooks"), dict):
        sources["hooks"] = "project"
    return sources


# add-settings-system-tab：受管 admin.* 键缺省（与 ConfigLoader.get_admin_config
# 缺省一致：enabled=True / interval_minutes=5 / escalation_cooldown_minutes=60 /
# merge_breaker_threshold 复用 agents.merge_breaker_threshold（缺省 2）/
# shutdown_drain_seconds=1800 / bug_repair_mode=inplace）
_ADMIN_DEFAULTS = {
    "enabled": True,
    "interval_minutes": 5,
    "escalation_cooldown_minutes": 60,
    "shutdown_drain_seconds": 1800,
    "bug_repair_mode": "inplace",
}


def _managed_admin_keys(config: dict) -> dict:
    """受管 admin.* 键提取：6 键 + 缺省填充，不透传未知 admin 键/self_review 子段。

    与 llm/agents 段「缺省填充」形态一致：文件里为合法类型的值才回显，否则用缺省。
    merge_breaker_threshold 缺省沿用 agents.merge_breaker_threshold（未配置则为 2）；
    bug_repair_mode 仅 inplace/derive 回显，非法值回退缺省 inplace（写路径校验
    保证合法值才能落盘）。
    """
    admin = config.get("admin") if isinstance(config, dict) else None
    admin = admin if isinstance(admin, dict) else {}
    breaker = admin.get("merge_breaker_threshold")
    if not isinstance(breaker, int) or isinstance(breaker, bool) or breaker < 1:
        agents = config.get("agents") if isinstance(config, dict) else None
        breaker = agents.get("merge_breaker_threshold") if isinstance(agents, dict) else None
        if not isinstance(breaker, int) or isinstance(breaker, bool) or breaker < 1:
            breaker = 2
    out = {"merge_breaker_threshold": breaker}
    for key, default in _ADMIN_DEFAULTS.items():
        val = admin.get(key, default)
        if key == "enabled":
            out[key] = val if isinstance(val, bool) else default
        elif key == "bug_repair_mode":
            # 字符串枚举：仅 inplace/derive 回显，非法/非字符串回退缺省
            out[key] = val if val in ("inplace", "derive") else default
        else:
            # 数值键：非数值/布尔一律回退缺省（写路径校验保证合法值才能落盘）
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                val = default
            out[key] = val
    return out


def read_config(scope_root, scope: str = "project") -> dict:
    """读取指定作用域文件的受管配置段。

    scope="project"：读 <scope_root>/.fenix/config.yaml（现状）；
    scope="user"：读 ~/.fenix/config.yaml（scope_root 忽略）。

    返回: {"llm": {...}, "agents": {"models": {...}, "max_concurrent": int},
            "gates": {"approve_mode": ...}, "scope": "user"|"project",
            "raw_exists": bool, "sources": {...}, "error": str|null}
    容错：文件不存在返回空结构 + raw_exists=False；解析失败返回 error。
    """
    config_path = USER_CONFIG_PATH if scope == "user" else Path(scope_root) / ".fenix" / "config.yaml"
    result = {
        "llm": {},
        "agents": {"models": {}, "max_concurrent": 2, "run_timeout_seconds": 9000, "max_turns": 400, "daily_run_limit": 50, "token_budget_millions": 50, "impl_run_budget": 4, "verify_redo_budget": 3},
        "gates": {"approve_mode": "manual", "promote_mode": "auto"},
        "runs": {"keep": 50},
        # 验证契约键（static_scope 服务范围 / deps_mode worktree 依赖供给模式）
        "verify": {"static_scope": "main", "deps_mode": "prefer-offline"},
        # add-spec-archive D5：自动归档阈值（0 = 禁用，默认 50）
        "archive": {"auto_threshold": 50},
        # add-daily-self-review：admin.self_review 三键（缺省 false/false/02:00）
        "self_review": dict(_DEFAULT_SELF_REVIEW),
        # add-settings-system-tab：admin.* 受管键（5 键 + 缺省填充）
        "admin": dict(_ADMIN_DEFAULTS, merge_breaker_threshold=2),
        # add-spec-hooks：两级 hook 订阅配置（缺省空订阅，零行为）
        "hooks": {"global": [], "specs": {}},
        "scope": scope,
        "raw_exists": False,
        "sources": _managed_key_sources({}),
        "error": None,
    }
    if scope == "user":
        result["sources"] = {k: "user" for k in _SOURCE_KEYS}
    if not config_path.exists():
        return result
    result["raw_exists"] = True
    try:
        with config_path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError) as e:
        result["error"] = f"配置文件解析失败: {e}"
        return result
    if not isinstance(raw, dict):
        result["error"] = "配置文件顶层不是对象"
        return result

    if scope == "project":
        result["sources"] = _managed_key_sources(raw)

    # 提取受管键（白名单：llm / agents.models / agents.max_concurrent / gates.approve_mode）
    if isinstance(raw.get("llm"), dict):
        result["llm"] = raw["llm"]
    agents_raw = raw.get("agents")
    if isinstance(agents_raw, dict):
        agents_result = {}
        if isinstance(agents_raw.get("models"), dict):
            # improve-failover-model-mapping-ui（D4）：规范化 models 为 Dashboard
            # 回显视图（str/list/对象统一为对象数组 + resolved model）
            from core.config import ConfigLoader as _CL
            llm_providers = raw.get("llm", {}).get("providers") or []
            agents_result["models"] = _CL.normalize_agent_models(
                agents_raw["models"], llm_providers
            )
        if isinstance(agents_raw.get("max_concurrent"), int):
            agents_result["max_concurrent"] = agents_raw["max_concurrent"]
        if isinstance(agents_raw.get("run_timeout_seconds"), int):
            agents_result["run_timeout_seconds"] = agents_raw["run_timeout_seconds"]
        if isinstance(agents_raw.get("max_turns"), int):
            agents_result["max_turns"] = agents_raw["max_turns"]
        if isinstance(agents_raw.get("daily_run_limit"), int):
            agents_result["daily_run_limit"] = agents_raw["daily_run_limit"]
        if isinstance(agents_raw.get("token_budget_millions"), int):
            # add-cost-observability（D5）：预算键回显（此前缺提取，配置值读不回来）
            agents_result["token_budget_millions"] = agents_raw["token_budget_millions"]
        if isinstance(agents_raw.get("impl_run_budget"), int):
            agents_result["impl_run_budget"] = agents_raw["impl_run_budget"]
        if isinstance(agents_raw.get("verify_redo_budget"), int):
            agents_result["verify_redo_budget"] = agents_raw["verify_redo_budget"]
        # fix-provider-transient-backoff（D6）：瞬断治理五键回显到 agents 段
        #（缺省填充，语义与 read_effective_config 的 get_transient_config 一致）
        from core.config import ConfigLoader as _CLT
        _transient = _CLT.get_transient_config(raw)
        for _tk in ("transient_backoff_schedule", "transient_redispatch_delay_seconds",
                    "transient_break_threshold", "transient_break_window_seconds",
                    "transient_break_cooldown_seconds"):
            agents_result[_tk] = _transient[_tk]
        if agents_result:
            # 只在结果中有受管键时覆盖默认，避免清空默认值
            for k, v in agents_result.items():
                result["agents"][k] = v
    gates_raw = raw.get("gates")
    if isinstance(gates_raw, dict) and "approve_mode" in gates_raw:
        result["gates"] = {"approve_mode": gates_raw["approve_mode"]}
    # add-draft-promotion-gate：promote_mode 提取（合法枚举才回显，非法留空由读侧缺省兜底）
    if isinstance(gates_raw, dict) and gates_raw.get("promote_mode") in ("auto", "manual"):
        if "gates" not in result:
            result["gates"] = {}
        result["gates"]["promote_mode"] = gates_raw["promote_mode"]
    verify_raw = raw.get("verify")
    if isinstance(verify_raw, dict):
        if verify_raw.get("static_scope") in ("main", "worktree"):
            result["verify"]["static_scope"] = verify_raw["static_scope"]
        if verify_raw.get("deps_mode") in ("prefer-offline", "hardlink"):
            result["verify"]["deps_mode"] = verify_raw["deps_mode"]
        # add-planner-efficiency（planner-generation-throttle 2.3）：节流上限读回。
        # 与写路径（write_config merge_verify）白名单对称——写了能读回来（BUG-01 修复）。
        pmc = verify_raw.get("planner_max_concurrent")
        if isinstance(pmc, int) and not isinstance(pmc, bool) and pmc >= 0:
            result["verify"]["planner_max_concurrent"] = pmc
    runs_raw = raw.get("runs")
    if isinstance(runs_raw, dict) and isinstance(runs_raw.get("keep"), int) and runs_raw["keep"] >= 1:
        result["runs"] = {"keep": runs_raw["keep"]}
    archive_raw = raw.get("archive")
    if isinstance(archive_raw, dict):
        from core.config import ConfigLoader as _CL
        result["archive"] = {"auto_threshold": _CL.effective_auto_archive_threshold(raw)}
    # add-daily-self-review：admin.self_review 三键（经 ConfigLoader 生效值回显）
    admin_raw = raw.get("admin")
    if isinstance(admin_raw, dict):
        from core.config import ConfigLoader as _CL
        result["self_review"] = _CL.get_self_review_config(raw)
        # add-settings-system-tab：受管 admin 键提取（5 键 + 缺省填充，不透传未知键）
        result["admin"] = _managed_admin_keys(raw)
    # add-spec-hooks：hooks 段原样透传（读回 UI 编辑视图）
    hooks_raw = raw.get("hooks")
    if isinstance(hooks_raw, dict):
        result["hooks"] = hooks_raw
    return result


# 配置解析签名缓存（dashboard-spec-summary-index D4）：
# read_effective_config 按 (用户级 config.yaml 签名, 项目级 config.yaml 签名) 缓存，
# mtime/size 未变不重读文件与 YAML 解析；写路径不维护显式失效（写后 mtime 已变，
# 签名键自然失效，与 _RUN_TASK_CACHE 同模式）。
# 缓存有界：键 ∈ {用户级 config.yaml，项目 config.yaml} × mtime 版本，超出整体清空
# （防配置频繁写入时旧键残留无界增长）。
_EFFECTIVE_CONFIG_CACHE: dict = {}
_EFFECTIVE_CONFIG_CACHE_MAX = 512


def _config_file_sig(path: Path):
    """配置文件签名 (mtime_ns, size)；缺失返回 None。"""
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def read_effective_config(project_root) -> dict:
    """项目模式有效配置视图：受管键取 resolve_config 有效合并值 + sources 标注。

    返回: {"llm": {...}, "agents": {"models": {...}, "max_concurrent": int},
            "gates": {"approve_mode": ...}, "scope": "project", "raw_exists": bool,
            "sources": {...}, "error": str|null, "description": str}
    sources[key] = "project" 当该键在项目级文件显式定义，否则 "user"（继承用户级或默认）。

    配置解析缓存（D4）：以 (用户级 config.yaml, 项目级 config.yaml) 的
    (mtime_ns, size) 为键缓存解析结果；命中直接返回深拷贝，不重读文件。
    """
    from core.config import ConfigLoader

    proot = Path(project_root)
    proj_path = proot / ".fenix" / "config.yaml"

    cache_key = (_config_file_sig(USER_CONFIG_PATH), _config_file_sig(proj_path))
    cached = _EFFECTIVE_CONFIG_CACHE.get(cache_key)
    if cached is not None:
        return copy.deepcopy(cached)

    result = {
        "llm": {},
        "agents": {"models": {}, "max_concurrent": 2, "run_timeout_seconds": 9000, "max_turns": 400, "daily_run_limit": 50, "token_budget_millions": 50, "impl_run_budget": 4, "verify_redo_budget": 3},
        "gates": {"approve_mode": "manual", "promote_mode": "auto"},
        "runs": {"keep": 50},
        # 验证契约键（static_scope 服务范围 / deps_mode worktree 依赖供给模式）
        "verify": {"static_scope": "main", "deps_mode": "prefer-offline"},
        # add-spec-archive D5：自动归档阈值（0 = 禁用，默认 50）
        "archive": {"auto_threshold": 50},
        # add-daily-self-review：admin.self_review 三键（缺省 false/false/02:00）
        "self_review": dict(_DEFAULT_SELF_REVIEW),
        # add-settings-system-tab：admin.* 受管键（5 键 + 缺省填充）
        "admin": dict(_ADMIN_DEFAULTS, merge_breaker_threshold=2),
        # add-spec-hooks：两级 hook 订阅配置（缺省空订阅，零行为）
        "hooks": {"global": [], "specs": {}},
        "scope": "project",
        "raw_exists": proj_path.exists(),
        "sources": _managed_key_sources({}),
        "error": None,
    }

    # 项目级文件显式定义 → sources 标注；解析失败记录 error 不阻断合并视图
    if proj_path.exists():
        try:
            with proj_path.open("r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f) or {}
            if isinstance(loaded, dict):
                result["sources"] = _managed_key_sources(loaded)
            else:
                result["error"] = "配置文件顶层不是对象"
        except (yaml.YAMLError, OSError) as e:
            result["error"] = f"配置文件解析失败: {e}"

    try:
        effective = ConfigLoader.resolve_config(proot)
    except Exception as e:
        result["error"] = f"有效配置解析失败: {e}"
        if len(_EFFECTIVE_CONFIG_CACHE) > _EFFECTIVE_CONFIG_CACHE_MAX:
            _EFFECTIVE_CONFIG_CACHE.clear()
        _EFFECTIVE_CONFIG_CACHE[cache_key] = copy.deepcopy(result)
        return result

    # 提取受管键（有效合并值）
    if isinstance(effective.get("llm"), dict):
        result["llm"] = effective["llm"]
    agents_eff = effective.get("agents")
    if isinstance(agents_eff, dict):
        if isinstance(agents_eff.get("models"), dict):
            # improve-failover-model-mapping-ui（D4）：规范化 models 为 Dashboard
            # 回显视图（str/list/对象统一为对象数组 + resolved model）
            from core.config import ConfigLoader as _CL
            llm_eff = effective.get("llm") or {}
            result["agents"]["models"] = _CL.normalize_agent_models(
                agents_eff["models"], (llm_eff.get("providers") or [])
            )
        if isinstance(agents_eff.get("max_concurrent"), int):
            result["agents"]["max_concurrent"] = agents_eff["max_concurrent"]
        if isinstance(agents_eff.get("run_timeout_seconds"), int):
            result["agents"]["run_timeout_seconds"] = agents_eff["run_timeout_seconds"]
        if isinstance(agents_eff.get("max_turns"), int):
            result["agents"]["max_turns"] = agents_eff["max_turns"]
        if isinstance(agents_eff.get("daily_run_limit"), int):
            result["agents"]["daily_run_limit"] = agents_eff["daily_run_limit"]
        if isinstance(agents_eff.get("token_budget_millions"), int):
            # add-cost-observability（D5）：有效合并视图回显预算键（此前缺提取）
            result["agents"]["token_budget_millions"] = agents_eff["token_budget_millions"]
        if isinstance(agents_eff.get("impl_run_budget"), int):
            result["agents"]["impl_run_budget"] = agents_eff["impl_run_budget"]
        if isinstance(agents_eff.get("verify_redo_budget"), int):
            result["agents"]["verify_redo_budget"] = agents_eff["verify_redo_budget"]
        # fix-provider-transient-backoff（D6）：瞬断治理五键回显到 agents 段
        #（缺省填充，语义与 ConfigLoader.get_transient_config 一致——非法值回退缺省）。
        _transient = ConfigLoader.get_transient_config(effective)
        for _tk in ("transient_backoff_schedule", "transient_redispatch_delay_seconds",
                    "transient_break_threshold", "transient_break_window_seconds",
                    "transient_break_cooldown_seconds"):
            result["agents"][_tk] = _transient[_tk]
    gates_eff = effective.get("gates")
    if isinstance(gates_eff, dict) and "approve_mode" in gates_eff:
        result["gates"] = {"approve_mode": gates_eff["approve_mode"]}
    # add-draft-promotion-gate：草稿晋升模式回显（缺省 auto）
    if isinstance(gates_eff, dict) and "promote_mode" in gates_eff:
        val = gates_eff["promote_mode"]
        if val in ("auto", "manual"):
            if "gates" not in result:
                result["gates"] = {}
            result["gates"]["promote_mode"] = val
    elif "gates" not in result:
        # 缺失时填默认值 auto（对齐 ConfigLoader.get_promote_mode）
        result["gates"] = {"promote_mode": "auto"}
    elif "promote_mode" not in result.get("gates", {}):
        result["gates"]["promote_mode"] = "auto"
    verify_eff = effective.get("verify")
    if isinstance(verify_eff, dict):
        if verify_eff.get("static_scope") in ("main", "worktree"):
            result["verify"]["static_scope"] = verify_eff["static_scope"]
        if verify_eff.get("deps_mode") in ("prefer-offline", "hardlink"):
            result["verify"]["deps_mode"] = verify_eff["deps_mode"]
        # add-planner-efficiency：节流上限有效值回显（与 write_config 白名单对称）
        pmc = verify_eff.get("planner_max_concurrent")
        if isinstance(pmc, int) and not isinstance(pmc, bool) and pmc >= 0:
            result["verify"]["planner_max_concurrent"] = pmc
    runs_eff = effective.get("runs")
    if isinstance(runs_eff, dict) and isinstance(runs_eff.get("keep"), int) and runs_eff["keep"] >= 1:
        result["runs"] = {"keep": runs_eff["keep"]}
    # add-spec-archive D5：经生效助手取值（非法配置回落默认 50，设置页回显一致）
    result["archive"] = {"auto_threshold": ConfigLoader.effective_auto_archive_threshold(effective)}
    # add-daily-self-review：经生效助手取值（run_at 非法值回退 02:00，回显一致）
    result["self_review"] = ConfigLoader.get_self_review_config(effective)
    # add-settings-system-tab：受管 admin 键提取（5 键 + 缺省填充，不透传未知键）
    result["admin"] = _managed_admin_keys(effective)
    # add-spec-hooks：hooks 段有效值透传（读回 UI 编辑视图）
    hooks_eff = effective.get("hooks")
    if isinstance(hooks_eff, dict):
        result["hooks"] = hooks_eff

    # 提取 project.description → 顶层 description（非 str 或缺失 → ""）
    project_eff = effective.get("project")
    if isinstance(project_eff, dict) and isinstance(project_eff.get("description"), str):
        result["description"] = project_eff["description"]
    else:
        result["description"] = ""

    if len(_EFFECTIVE_CONFIG_CACHE) > _EFFECTIVE_CONFIG_CACHE_MAX:
        _EFFECTIVE_CONFIG_CACHE.clear()
    _EFFECTIVE_CONFIG_CACHE[cache_key] = copy.deepcopy(result)
    return result


def _deep_merge_managed(raw_config: dict, patch: dict) -> dict:
    """把 patch 中的受管键合并到 raw_config，返回新 dict（不修改原对象）。

    合并规则（白名单化）：
    - llm: 整体替换（patch 中存在即替换，不存在则保留原 llm）
    - agents.models: 整体替换（只动 models，其它 agents 子键保留）
    - agents.max_concurrent: 替换（仅 patch 中提供且为正整数时）
    - gates.approve_mode: 只替换 approve_mode 子键
    - gates.promote_mode: 只替换 promote_mode 子键
    """
    import copy
    merged = copy.deepcopy(raw_config)

    if "llm" in patch:
        merged["llm"] = copy.deepcopy(patch["llm"])

    if "agents" in patch and isinstance(patch["agents"], dict):
        if not isinstance(merged.get("agents"), dict):
            merged["agents"] = {}
        if "models" in patch["agents"]:
            merged["agents"]["models"] = copy.deepcopy(patch["agents"]["models"])
        if "max_concurrent" in patch["agents"]:
            merged["agents"]["max_concurrent"] = patch["agents"]["max_concurrent"]
        if "run_timeout_seconds" in patch["agents"]:
            merged["agents"]["run_timeout_seconds"] = patch["agents"]["run_timeout_seconds"]
        if "max_turns" in patch["agents"]:
            merged["agents"]["max_turns"] = patch["agents"]["max_turns"]
        if "daily_run_limit" in patch["agents"]:
            merged["agents"]["daily_run_limit"] = patch["agents"]["daily_run_limit"]
        if "token_budget_millions" in patch["agents"]:
            # add-cost-observability（D5）：此前缺合并分支，保存后预算键被静默丢弃
            merged["agents"]["token_budget_millions"] = patch["agents"]["token_budget_millions"]
        if "impl_run_budget" in patch["agents"]:
            merged["agents"]["impl_run_budget"] = patch["agents"]["impl_run_budget"]
        if "verify_redo_budget" in patch["agents"]:
            # fix-daemon-lifecycle-races 验证发现：缺合并分支导致保存被静默丢弃
            merged["agents"]["verify_redo_budget"] = patch["agents"]["verify_redo_budget"]
        # fix-provider-transient-backoff（D6）：瞬断治理五键合并分支（前置校验
        # 已拒绝非法值，此处只应用合法值；缺省透传由 get_transient_config 兜底）。
        for _tk in ("transient_backoff_schedule", "transient_redispatch_delay_seconds",
                    "transient_break_threshold", "transient_break_window_seconds",
                    "transient_break_cooldown_seconds"):
            if _tk in patch["agents"]:
                merged["agents"][_tk] = patch["agents"][_tk]

    if "gates" in patch and isinstance(patch["gates"], dict):
        if "approve_mode" in patch["gates"] or "promote_mode" in patch["gates"]:
            if not isinstance(merged.get("gates"), dict):
                merged["gates"] = {}
        if "approve_mode" in patch["gates"]:
            merged["gates"]["approve_mode"] = patch["gates"]["approve_mode"]
        # add-draft-promotion-gate 验证修复：缺合并分支导致设置页保存的
        # promote_mode 在 merge 阶段被静默丢弃（枚举合法性已由 write_config 前置校验把关）
        if "promote_mode" in patch["gates"]:
            merged["gates"]["promote_mode"] = patch["gates"]["promote_mode"]

    if "runs" in patch and isinstance(patch["runs"], dict):
        keep = patch["runs"].get("keep")
        # 仅接受正整数，非法值静默忽略（保留原配置）
        if isinstance(keep, int) and keep >= 1:
            if not isinstance(merged.get("runs"), dict):
                merged["runs"] = {}
            merged["runs"]["keep"] = keep
    # verify.*：static_scope 服务范围 / deps_mode 依赖供给模式
    # （非法值由 write_config 前置校验拒绝，此处只应用合法值）
    if "verify" in patch and isinstance(patch["verify"], dict):
        if not isinstance(merged.get("verify"), dict):
            merged["verify"] = {}
        for vk in ("static_scope", "deps_mode"):
            if patch["verify"].get(vk) in ("main", "worktree") if vk == "static_scope" \
                    else patch["verify"].get(vk) in ("prefer-offline", "hardlink"):
                merged["verify"][vk] = patch["verify"][vk]
        # add-planner-efficiency（planner-generation-throttle 2.3）：
        # planner 生成节流上限——非负整数（0=不节流），非法值静默忽略。
        pmc = patch["verify"].get("planner_max_concurrent")
        if isinstance(pmc, int) and not isinstance(pmc, bool) and pmc >= 0:
            merged["verify"]["planner_max_concurrent"] = pmc
    # add-spec-archive D5：archive.auto_threshold（非负整数，0=禁用，非法值静默忽略）
    if "archive" in patch and isinstance(patch["archive"], dict):
        at = patch["archive"].get("auto_threshold")
        if isinstance(at, int) and at >= 0:
            if not isinstance(merged.get("archive"), dict):
                merged["archive"] = {}
            merged["archive"]["auto_threshold"] = at
    # add-daily-self-review：admin.self_review 三键（enabled/read_todo 布尔、
    # run_at 合法 HH:MM；非法 run_at 由 write_config 前置校验拒绝，此处只应用合法值）
    if "self_review" in patch and isinstance(patch["self_review"], dict):
        if not isinstance(merged.get("admin"), dict):
            merged["admin"] = {}
        existing_sr = merged["admin"].get("self_review")
        if not isinstance(existing_sr, dict):
            existing_sr = {}
        sr = dict(existing_sr)
        for field in ("enabled", "read_todo"):
            if field in patch["self_review"] and isinstance(patch["self_review"][field], bool):
                sr[field] = patch["self_review"][field]
        run_at = patch["self_review"].get("run_at")
        from core.config import ConfigLoader as _CL
        if _CL.is_valid_hhmm(run_at):
            sr["run_at"] = run_at
        merged["admin"]["self_review"] = sr
    # add-settings-system-tab：admin.* 六键合并。只动 6 个受管键——保留 admin 段内
    # 的 self_review / agent_model / workers 等未知或非受管键（写路径校验保证
    # 进入此处的值合法，self_review 由顶层 patch 分支单独合并）。
    if "admin" in patch and isinstance(patch["admin"], dict):
        if not isinstance(merged.get("admin"), dict):
            merged["admin"] = {}
        for ak in ("enabled", "interval_minutes", "escalation_cooldown_minutes",
                   "merge_breaker_threshold", "shutdown_drain_seconds",
                   "bug_repair_mode"):
            if ak in patch["admin"] and patch["admin"][ak] is not None:
                merged["admin"][ak] = patch["admin"][ak]
    # description 分支：patch 顶层 description（str）写入 merged["project"]["description"]
    if "description" in patch and isinstance(patch["description"], str):
        if not isinstance(merged.get("project"), dict):
            merged["project"] = {}
        merged["project"]["description"] = patch["description"]
    # add-spec-hooks：hooks 段整体替换（patch 中存在即替换，不存在则保留原段）
    if "hooks" in patch:
        merged["hooks"] = copy.deepcopy(patch["hooks"])

    return merged


def write_config(scope_root, config_patch: dict, scope: str = "project") -> dict:
    """把受管配置段写回作用域文件（原子写、保留非受管键）。

    写入前使用 ConfigLoader 做受管字段局部校验，校验失败返回错误且不写盘。

    Args:
        scope_root: 项目根路径（scope="project" 时使用；scope="user" 忽略）
        config_patch: 含 llm / agents.models / gates.approve_mode 的 patch dict
        scope: "user" 写 ~/.fenix/config.yaml（自动建目录）；"project" 写项目文件

    Returns: {"ok": bool, "error": str|null, "scope": "user"|"project", "path": str}
    """
    from core.config import ConfigLoader

    if scope == "user":
        config_path = USER_CONFIG_PATH
    else:
        config_path = Path(scope_root) / ".fenix" / "config.yaml"
    config_dir = config_path.parent
    fail = lambda err: {"ok": False, "error": err, "scope": scope, "path": str(config_path)}

    # 1. 读取现有配置（若不存在则为空 dict，写入时创建）
    raw = {}
    if config_path.exists():
        try:
            with config_path.open("r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
            if isinstance(loaded, dict):
                raw = loaded
        except (yaml.YAMLError, OSError) as e:
            return fail(f"读取现有配置失败: {e}")

    # improve-failover-model-mapping-ui（D4/D5）：前端编辑器状态（规范化的行列表）
    # 序列化为 _validate_agent_models 能消费的 canonical 形态（str / list[str|对象]）。
    # 在合并前序列化，保证校验与写入都使用 canonical 形态；role-level model 空值
    # 不写入，避免空串覆盖配置文件中已有的模型缺省。
    if isinstance(config_patch.get("agents"), dict) and isinstance(config_patch["agents"].get("models"), dict):
        config_patch = dict(config_patch)  # shallow copy, 不改入参
        config_patch["agents"] = dict(config_patch["agents"])
        config_patch["agents"]["models"] = ConfigLoader.serialize_models_patch(
            config_patch["agents"]["models"]
        )

    # add-daily-self-review：前端提交的 self_review patch 后端校验（非法直接拒绝，
    # 不静默忽略——spec「非法输入（如 25:00）被前端与后端双重校验拒绝」）。
    if isinstance(config_patch.get("self_review"), dict):
        sr_patch = config_patch["self_review"]
        for field in ("enabled", "read_todo"):
            if field in sr_patch and sr_patch[field] is not None \
                    and not isinstance(sr_patch[field], bool):
                return fail(
                    f"admin.self_review.{field} must be a boolean: {sr_patch[field]}"
                )
        if "run_at" in sr_patch and sr_patch["run_at"] is not None:
            if not ConfigLoader.is_valid_hhmm(sr_patch["run_at"]):
                return fail(
                    f"admin.self_review.run_at must be HH:MM (00:00-23:59): {sr_patch['run_at']}"
                )

    # verify.* patch 前置校验：非法值直接拒绝，不静默忽略（同 self_review 模式；
    # 只在 merge 层过滤会让 write "成功" 但用户输入被吞）
    if isinstance(config_patch.get("verify"), dict):
        v_patch = config_patch["verify"]
        if "static_scope" in v_patch and v_patch["static_scope"] is not None \
                and v_patch["static_scope"] not in ("main", "worktree"):
            return fail(
                f"verify.static_scope must be one of ['main', 'worktree']: "
                f"{v_patch['static_scope']}"
            )
        if "deps_mode" in v_patch and v_patch["deps_mode"] is not None \
                and v_patch["deps_mode"] not in ("prefer-offline", "hardlink"):
            return fail(
                f"verify.deps_mode must be one of ['prefer-offline', 'hardlink']: "
                f"{v_patch['deps_mode']}"
            )
        # add-planner-efficiency：planner 生成节流上限——非负整数（0=不节流）。
        if "planner_max_concurrent" in v_patch \
                and v_patch["planner_max_concurrent"] is not None:
            pmc = v_patch["planner_max_concurrent"]
            if not isinstance(pmc, int) or isinstance(pmc, bool) or pmc < 0:
                return fail(
                    f"verify.planner_max_concurrent must be a non-negative integer "
                    f"(0=不节流): {pmc!r}"
                )

    # add-settings-system-tab：admin.* 五键前置校验（非法值直接拒绝，不静默忽略——
    # 与 verify/self_review 同模式，前端输入类型错误在后端权威兜底）。
    if isinstance(config_patch.get("admin"), dict):
        adm = config_patch["admin"]
        if "enabled" in adm and adm["enabled"] is not None \
                and not isinstance(adm["enabled"], bool):
            return fail(f"admin.enabled must be a boolean: {adm['enabled']!r}")
        if "interval_minutes" in adm and adm["interval_minutes"] is not None:
            im = adm["interval_minutes"]
            if not isinstance(im, (int, float)) or isinstance(im, bool) or im <= 0:
                return fail(f"admin.interval_minutes must be a positive number: {im!r}")
        if "escalation_cooldown_minutes" in adm \
                and adm["escalation_cooldown_minutes"] is not None:
            ec = adm["escalation_cooldown_minutes"]
            if not isinstance(ec, (int, float)) or isinstance(ec, bool) or ec < 0:
                return fail(
                    f"admin.escalation_cooldown_minutes must be a non-negative number: {ec!r}"
                )
        if "merge_breaker_threshold" in adm \
                and adm["merge_breaker_threshold"] is not None:
            mb = adm["merge_breaker_threshold"]
            if not isinstance(mb, int) or isinstance(mb, bool) or mb < 1:
                return fail(
                    f"admin.merge_breaker_threshold must be a positive integer: {mb!r}"
                )
        if "shutdown_drain_seconds" in adm \
                and adm["shutdown_drain_seconds"] is not None:
            sd = adm["shutdown_drain_seconds"]
            if not isinstance(sd, int) or isinstance(sd, bool) or sd < 0:
                return fail(
                    f"admin.shutdown_drain_seconds must be a non-negative integer: {sd!r}"
                )
        # add-bug-repair-mode-config：bug_repair_mode 枚举校验（inplace/derive，
        # 非法值直接拒绝——前端类型错误在后端权威兜底，与其它 admin 键同模式）。
        if "bug_repair_mode" in adm and adm["bug_repair_mode"] is not None:
            brm = adm["bug_repair_mode"]
            if brm not in ("inplace", "derive"):
                return fail(
                    f"admin.bug_repair_mode must be one of ['inplace', 'derive']: {brm!r}"
                )

    # add-draft-promotion-gate：gates.promote_mode 前置校验（枚举拒绝，对齐 approve_mode）
    if isinstance(config_patch.get("gates"), dict):
        g_patch = config_patch["gates"]
        if "promote_mode" in g_patch and g_patch["promote_mode"] is not None \
                and g_patch["promote_mode"] not in ("auto", "manual"):
            return fail(
                f"gates.promote_mode must be one of ['auto', 'manual']: {g_patch['promote_mode']!r}"
            )

    # add-spec-hooks D7：hooks 段前置校验（非法值直接拒绝 400 且不写入——规则：
    # events 非空且合法、action 合法、webhook 必填 url、shell 必填 command）。
    if isinstance(config_patch.get("hooks"), dict):
        from core.hook_engine import validate_hooks_config
        hooks_err = validate_hooks_config(config_patch)
        if hooks_err:
            return fail(f"hooks 配置非法：{hooks_err}")

    # 2. 合并受管键
    merged = _deep_merge_managed(raw, config_patch)

    # improve-provider-billing-config（D1）：顶层 llm.billing 段移除——即使旧客户端
    # 仍提交旧形态也剥离，保证落盘文件永不含顶层 llm.billing（下次保存自然清除
    # 手工残留的旧键）。
    if isinstance(merged.get("llm"), dict) and "billing" in merged["llm"]:
        merged["llm"].pop("billing", None)

    # 3. 校验受管字段（llm / agents.models / agents.max_concurrent / gates.approve_mode）
    #    不做完整 ConfigLoader 校验，避免缺少 project/schedule 等必填键时无法写入。
    try:
        llm = merged.get("llm") or {}
        if llm:
            ConfigLoader._validate_llm(llm)
        # improve-provider-billing-config（task 2.1）：per-provider billing 校验——
        # 遍历 llm.providers[i].billing（enabled 布尔、prices 行 model 非空、4 项
        # 单价非负数值排除 bool、同一卡片内行 model 不重复）；任一非法拒绝写入并
        # 列出违规项。与 _validate_llm 内 load-time 校验共用 _validate_provider_billing。
        if isinstance(llm, dict):
            _providers = llm.get("providers")
            if _providers is not None:
                if not isinstance(_providers, list):
                    raise ValueError("llm.providers must be a list")
                ConfigLoader._validate_provider_billing(_providers)
        agents = merged.get("agents") or {}
        if "models" in agents and agents["models"]:
            ConfigLoader._validate_agent_models(agents["models"], llm)
            # improve-failover-model-mapping-ui D5：Dashboard 保存时额外要求每行引用的
            # provider 名必须存在于 llm.providers（load-time 校验只打 ERROR 不阻塞，但
            # UI 保存不允许"脏配置"落盘）。
            model_patch = config_patch.get("agents", {}).get("models", {}) if config_patch.get("agents") else {}
            if model_patch:
                provider_names = set()
                provs = (llm or {}).get("providers") or []
                for p in provs:
                    if isinstance(p, dict) and p.get("name"):
                        provider_names.add(p["name"])
                for role, entry in model_patch.items():
                    if not isinstance(entry, dict):
                        continue
                    provider_val = entry.get("provider")
                    bad = []
                    if isinstance(provider_val, str):
                        if provider_val and provider_val not in provider_names:
                            bad.append(provider_val)
                    elif isinstance(provider_val, list):
                        for el in provider_val:
                            n = el.get("provider") if isinstance(el, dict) else el
                            if isinstance(n, str) and n and n not in provider_names:
                                bad.append(n)
                    if bad:
                        raise ValueError(
                            f"agents.models.{role}.provider 引用了不存在的 provider: "
                            + ", ".join(sorted(set(bad)))
                        )
        if "max_concurrent" in agents:
            mc = agents["max_concurrent"]
            if not isinstance(mc, int) or mc <= 0:
                raise ValueError(
                    f"agents.max_concurrent must be a positive integer: {mc}"
                )
        if "run_timeout_seconds" in agents:
            rt = agents["run_timeout_seconds"]
            if not isinstance(rt, int) or rt <= 0:
                raise ValueError(
                    f"agents.run_timeout_seconds must be a positive integer: {rt}"
                )
        if "max_turns" in agents:
            mt = agents["max_turns"]
            if not isinstance(mt, int) or mt <= 0:
                raise ValueError(
                    f"agents.max_turns must be a positive integer: {mt}"
                )
        if "daily_run_limit" in agents:
            drl = agents["daily_run_limit"]
            if not isinstance(drl, int) or drl < 0:
                raise ValueError(
                    f"agents.daily_run_limit must be a non-negative integer: {drl}"
                )
        if "impl_run_budget" in agents:
            irb = agents["impl_run_budget"]
            if not isinstance(irb, int) or irb < 1 or irb > 10:
                raise ValueError(
                    f"agents.impl_run_budget must be an integer in [1, 10]: {irb}"
                )
        if "verify_redo_budget" in agents:
            vrb = agents["verify_redo_budget"]
            if not isinstance(vrb, int) or vrb < 1 or vrb > 10:
                raise ValueError(
                    f"agents.verify_redo_budget must be an integer in [1, 10]: {vrb}"
                )
        # fix-provider-transient-backoff（D6）：瞬断治理四数值键——非负整数校验
        #（非法值直接拒绝 400，与 verify/self_review/admin 同模式，前端类型错误
        # 由后端权威兜底；缺省回显与回退仍走 get_transient_config）。
        for _tk in ("transient_redispatch_delay_seconds",
                    "transient_break_threshold",
                    "transient_break_window_seconds",
                    "transient_break_cooldown_seconds"):
            if _tk in agents and agents[_tk] is not None:
                _tv = agents[_tk]
                if isinstance(_tv, bool) or not isinstance(_tv, (int, float)) or _tv < 0:
                    raise ValueError(
                        f"agents.{_tk} must be a non-negative integer: {_tv!r}"
                    )
        if "transient_backoff_schedule" in agents \
                and agents["transient_backoff_schedule"] is not None:
            _ts = agents["transient_backoff_schedule"]
            if not isinstance(_ts, str):
                raise ValueError(
                    "agents.transient_backoff_schedule must be a comma-separated "
                    f"seconds string: {_ts!r}"
                )
            # 逗号秒序列校验：任一元素非正整数即拒绝（空串=关闭原地退避，允许）
            if _ts.strip():
                for _part in _ts.split(","):
                    _p = _part.strip()
                    if not _p:
                        continue
                    try:
                        _iv = int(_p)
                    except (TypeError, ValueError):
                        raise ValueError(
                            f"agents.transient_backoff_schedule 元素非正整数: {_part!r}"
                        )
                    if _iv <= 0:
                        raise ValueError(
                            f"agents.transient_backoff_schedule 元素非正整数: {_part!r}"
                        )
        gates = merged.get("gates") or {}
        if "approve_mode" in gates and gates["approve_mode"] is not None:
            mode = gates["approve_mode"]
            if mode not in ConfigLoader.VALID_APPROVE_MODES:
                raise ValueError(
                    f"gates.approve_mode must be one of {ConfigLoader.VALID_APPROVE_MODES}: {mode}"
                )
        verify_m = merged.get("verify") or {}
        if "static_scope" in verify_m and verify_m["static_scope"] is not None:
            if verify_m["static_scope"] not in ("main", "worktree"):
                raise ValueError(
                    f"verify.static_scope must be one of ['main', 'worktree']: "
                    f"{verify_m['static_scope']}"
                )
        if "deps_mode" in verify_m and verify_m["deps_mode"] is not None:
            if verify_m["deps_mode"] not in ("prefer-offline", "hardlink"):
                raise ValueError(
                    f"verify.deps_mode must be one of ['prefer-offline', 'hardlink']: "
                    f"{verify_m['deps_mode']}"
                )
        # add-spec-archive D5：archive.auto_threshold 必须为非负整数（0=禁用）
        archive_m = merged.get("archive") or {}
        if "auto_threshold" in archive_m and archive_m["auto_threshold"] is not None:
            at = archive_m["auto_threshold"]
            if not isinstance(at, int) or isinstance(at, bool) or at < 0:
                raise ValueError(
                    f"archive.auto_threshold must be a non-negative integer (0=disabled): {at}"
                )
        # add-daily-self-review：admin.self_review 三键（后端校验，非法输入拒绝 400）
        admin_m = merged.get("admin") or {}
        if isinstance(admin_m, dict) and isinstance(admin_m.get("self_review"), dict):
            sr = admin_m["self_review"]
            for field in ("enabled", "read_todo"):
                if field in sr and sr[field] is not None and not isinstance(sr[field], bool):
                    raise ValueError(
                        f"admin.self_review.{field} must be a boolean: {sr[field]}"
                    )
            if "run_at" in sr and sr["run_at"] is not None:
                from core.config import ConfigLoader as _CL
                if not _CL.is_valid_hhmm(sr["run_at"]):
                    raise ValueError(
                        f"admin.self_review.run_at must be HH:MM (00:00-23:59): {sr['run_at']}"
                    )
        # add-settings-system-tab：admin.* 六键（merged 视图校验；写路径前置校验
        # 已拒绝非法 patch，此处兜底防绕过前置校验的直连调用）
        if "enabled" in admin_m and admin_m["enabled"] is not None \
                and not isinstance(admin_m["enabled"], bool):
            raise ValueError(f"admin.enabled must be a boolean: {admin_m['enabled']!r}")
        if "bug_repair_mode" in admin_m and admin_m["bug_repair_mode"] is not None \
                and admin_m["bug_repair_mode"] not in ("inplace", "derive"):
            raise ValueError(
                f"admin.bug_repair_mode 非法：{admin_m['bug_repair_mode']!r}"
                f"（保存被拒绝，请修正后重试）"
            )
        for _k, _rule in (
            ("interval_minutes", lambda v: isinstance(v, (int, float))
             and not isinstance(v, bool) and v > 0),
            ("escalation_cooldown_minutes", lambda v: isinstance(v, (int, float))
             and not isinstance(v, bool) and v >= 0),
            ("merge_breaker_threshold", lambda v: isinstance(v, int)
             and not isinstance(v, bool) and v >= 1),
            ("shutdown_drain_seconds", lambda v: isinstance(v, int)
             and not isinstance(v, bool) and v >= 0),
        ):
            if _k in admin_m and admin_m[_k] is not None and not _rule(admin_m[_k]):
                raise ValueError(f"admin.{_k} 非法：{admin_m[_k]!r}（保存被拒绝，请修正后重试）")
        # add-spec-hooks D7：merged 视图 hooks 校验（兜底防绕过前置校验的直连调用；
        # 校验规则同前置，但作用于合并后视图，含项目级手工写入的非受管 hooks 段）
        from core.hook_engine import validate_hooks_config as _validate_hooks
        if isinstance(merged.get("hooks"), dict):
            _err = _validate_hooks(merged)
            if _err:
                raise ValueError(f"hooks 配置非法：{_err}")
    except ValueError as e:
        return fail(str(e))

    # 4. 原子写回（临时文件 + rename）
    config_dir.mkdir(parents=True, exist_ok=True)
    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=str(config_dir), prefix=".config-", suffix=".yaml.tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(_CONFIG_HEADER_COMMENT)
                yaml.safe_dump(merged, f, allow_unicode=True, default_flow_style=False,
                               sort_keys=False)
            os.replace(tmp_path, config_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except OSError as e:
        return fail(f"写入配置文件失败: {e}")

    return {"ok": True, "error": None, "scope": scope, "path": str(config_path)}


# ── 同步用户级设置到项目级（设置页项目级作用域「同步用户级设置」按钮） ──

# 页面标识 → 用户级 config.yaml 中被同步的受管键白名单。
# 键集与各设置页签 onSave 提交的 patch 键一一对应（「只覆盖当前页面的设置值」）：
# llm 页取 providers 整段；agents 页只取 models；parallel 页取并发三键 +
# verify.planner_max_concurrent；token 页取预算四键；verify 页取 static_scope/
# deps_mode；approval 页取 gates 两键；misc 页取 archive.auto_threshold；
# system 页取 admin.* 六键 + agents.transient_* 五键。
_SYNC_PAGE_KEYS = {
    "llm": {"llm": ["providers"]},
    "agents": {"agents": ["models"]},
    "parallel": {
        "agents": ["max_concurrent", "max_turns", "run_timeout_seconds"],
        "verify": ["planner_max_concurrent"],
    },
    "token": {
        "agents": ["token_budget_millions", "daily_run_limit",
                   "impl_run_budget", "verify_redo_budget"],
    },
    "verify": {"verify": ["static_scope", "deps_mode"]},
    "approval": {"gates": ["promote_mode", "approve_mode"]},
    "misc": {"archive": ["auto_threshold"]},
    "system": {
        "admin": ["enabled", "interval_minutes", "escalation_cooldown_minutes",
                  "merge_breaker_threshold", "shutdown_drain_seconds",
                  "bug_repair_mode"],
        "agents": ["transient_backoff_schedule", "transient_redispatch_delay_seconds",
                   "transient_break_threshold", "transient_break_window_seconds",
                   "transient_break_cooldown_seconds"],
    },
}


def sync_config_from_user(project_root, page: str) -> dict:
    """把用户级 config.yaml 中 page 页签对应的受管键覆盖写入项目级配置。

    以用户级文件原始值为 patch 源（read_config 的回显含缺省填充，会把用户级
    未显式配置的键也一并覆盖成缺省值），经 write_config 走完整的前置校验 +
    受管键合并 + 原子写盘——非受管键与其它页签的设置值不受影响。

    Args:
        project_root: 项目根路径
        page: 页面标识（_SYNC_PAGE_KEYS 键）

    Returns: {"ok": bool, "error": str|null, "synced": {...}|None, "path": str}
    """
    if page not in _SYNC_PAGE_KEYS:
        return {"ok": False, "error": f"未知页面标识: {page}", "synced": None, "path": None}

    # 读用户级原始文件（raw dict，不做缺省填充）：用户级未显式配置的键不覆盖
    user_raw = {}
    if USER_CONFIG_PATH.exists():
        try:
            with USER_CONFIG_PATH.open("r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
            if isinstance(loaded, dict):
                user_raw = loaded
        except (yaml.YAMLError, OSError) as e:
            return {"ok": False, "error": f"读取用户级配置失败: {e}", "synced": None,
                    "path": str(USER_CONFIG_PATH)}

    section_map = _SYNC_PAGE_KEYS[page]
    patch = {}
    for section, keys in section_map.items():
        sec_raw = user_raw.get(section)
        if not isinstance(sec_raw, dict):
            continue  # 用户级未配置该段：本页无可同步值，跳过（不写空覆盖）
        picked = {k: sec_raw[k] for k in keys if k in sec_raw}
        if picked:
            patch[section] = picked

    if not patch:
        return {"ok": False,
                "error": "用户级配置中该页面没有已设置的值，无可同步内容",
                "synced": None, "path": str(USER_CONFIG_PATH)}

    result = write_config(project_root, patch, scope="project")
    return {"ok": result["ok"], "error": result.get("error"),
            "synced": patch if result["ok"] else None,
            "path": result.get("path")}
