"""core.dashboard.data.admin_actions — Administrator/SPEC 写操作（admin_actions 组）。

refactor-dashboard-data-module D3 分组：本模块承载 admin 写操作职责域。
请求信号（admin invoke / run cancel / scheduling kick / approve push）、
冻结/解冻、晋升/回拨/重新评审、定时拾取、预算覆盖。
"""

import json
import os
import re
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

# 冻结前缀与「原状态 X」解析单点（add-spec-scheduling-controls D4）
from core.state_machine import (
    FREEZE_ERROR_PREFIX,
    FROZEN_FIELD,
    parse_orig_status,
    INFRA_FAILURE_COUNT_FIELD,
    VERIFY_INFRA_ROUNDS_FIELD,
    START_AFTER_MANUAL,
)

# 跨组引用（D4：叶子→中枢，直接导入无环）
from .state import parse_state

# fix-deferred-findings CYC-1：request_admin_invoke 与 ADMIN_INVOKE_REQUEST
# 已迁入中性模块 core.signals（pm_engine 侧消费点不再反向 import
# dashboard.data），此处 re-export 保住既有门面导入路径。
# fix-scheduling-kick-single-slot：write_scheduling_kick 亦在 core.signals，
# admin_actions 委托它写目录形态的唤醒信号。
from core.signals import (  # noqa: F401
    ADMIN_INVOKE_REQUEST,
    SCHEDULING_KICK_DIR,
    request_admin_invoke,
    write_scheduling_kick,
)

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
        return {
            "ok": False,
            "conflict": False,
            "missing_run_id": True,
            "file": None,
            "created": None,
            "error": "run_id is required",
        }

    proot = Path(project_root)
    req_path = proot / CANCEL_RUN_REQUEST

    # 已有未消费请求 → 冲突（409）
    if req_path.exists():
        try:
            existing = json.loads(req_path.read_text(encoding="utf-8"))
            existing_created = existing.get("created") if isinstance(existing, dict) else None
        except (OSError, json.JSONDecodeError):
            existing_created = None
        return {
            "ok": False,
            "conflict": True,
            "missing_run_id": False,
            "file": str(req_path),
            "created": existing_created,
            "error": "已有进行中的取消请求",
        }

    created = datetime.now(timezone.utc).isoformat()
    payload = {
        "run_id": run_id.strip(),
        "reason": reason or "",
        "source": "dashboard",
        "created": created,
    }
    req_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(req_path.parent), prefix=".cancel_run_request.", suffix=".tmp"
    )
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
    return {
        "ok": True,
        "conflict": False,
        "missing_run_id": False,
        "file": str(req_path),
        "created": created,
        "error": None,
    }


def is_spec_frozen(entry: dict) -> bool:
    """判定 SPEC 是否处于冻结态。

    结构化 ``frozen`` 字段优先（state_machine 侧已声明「结构化字段替代 error
    文本契约」）；文本前缀仅作存量兼容回退。自动冻结（内容完整性闸门 /
    预算闸门 / env 阻塞）一律写自有文案而非「用户指令冻结：」，只认文本会让
    它们在 dashboard 里既不显示冻结态也走不了解冻入口。
    """
    if entry.get("status") != "blocked":
        return False
    if entry.get("frozen") is True:
        return True
    return (entry.get("error") or "").startswith(FREEZE_ERROR_PREFIX)


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
        return {
            "ok": False,
            "found": False,
            "frozen": False,
            "error": f"spec not found: {spec_name}",
        }
    entry = specs[spec_name]
    if is_spec_frozen(entry):
        return {"ok": True, "found": True, "frozen": True, "error": None}
    if entry.get("status") in ("done", "pushed"):
        return {
            "ok": True,
            "found": True,
            "frozen": False,
            "error": f"终态 spec（{entry.get('status')}）不可冻结",
        }
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
        return {
            "ok": False,
            "found": False,
            "frozen": False,
            "error": f"spec not found: {spec_name}",
        }
    entry = specs[spec_name]
    if not is_spec_frozen(entry):
        return {"ok": True, "found": True, "frozen": False, "error": None}
    orig = parse_orig_status(entry.get("error"))
    from core.state_machine import StateMachine

    sm = StateMachine(Path(project_root) / ".fenix" / "STATE.md", None)
    sm.unfreeze_spec(spec_name, status=orig)
    return {"ok": True, "found": True, "frozen": False, "error": None}


def reclassify_infra_rounds(
    project_root, spec_name: str, n: int, audit_reason: str, actor: str = "dashboard"
) -> dict:
    """admin/dashboard 手动回拨 infra 误计入轮次（_verify_fail_rounds 减回 + 解冻）。

    委托 verification.reclassify_infra_rounds 核心实现（原子改写
    ``_verify_fail_rounds = max(0, current - n)`` + 解冻 + admin_store
    DISPOSITION 审计留痕，按 reclassify_key 幂等去重——重复回拨不二次扣减）。

    Args:
        project_root: 主树根目录。
        spec_name: 目标 spec。
        n: 减回轮次（>0）。
        audit_reason: 人工审核原因文本（审计留痕必须携带）。
        actor: 发起者标识（dashboard / cli）。

    Returns:
        dict：{ok, fail_rounds, status, applied, error?}。
        spec 不存在 → {ok: False, found: False, error}.
    """
    from core.state_machine import StateMachine
    from core.pm_engine.verification import reclassify_infra_rounds as _recl

    specs = parse_state(project_root)
    if spec_name not in specs:
        return {"ok": False, "found": False, "error": f"spec not found: {spec_name}"}
    if not str(audit_reason or "").strip():
        return {"ok": False, "found": True, "error": "audit_reason 必填（审计留痕要求）"}
    sm = StateMachine(Path(project_root) / ".fenix" / "STATE.md", None)
    try:
        result = _recl(
            project_root,
            sm,
            None,
            spec_name,
            int(n),
            str(audit_reason),
            actor=actor,
        )
    except (TypeError, ValueError) as e:
        return {"ok": False, "found": True, "error": f"invalid n: {e}"}
    return {
        "ok": result.get("ok", False),
        "found": True,
        "fail_rounds": result.get("fail_rounds", 0),
        "status": result.get("status", ""),
        "applied": result.get("applied", 0),
        "error": result.get("reason"),
    }


def promote_spec(project_root, spec_name: str) -> dict:
    """人工晋升 drafted SPEC：调用共享晋升函数（软化+lint+判定）。

    - spec 不存在 → {ok: False, found: False, error: ...}
    - spec 非 drafted → {ok: False, found: True, ok: False, reason: ...}
    - lint 违规 → {ok: False, found: True, violations: [...], error: ...}
    - 成功 → {ok: True, found: True, violations: []}
    """
    specs = parse_state(project_root)
    if spec_name not in specs:
        return {"ok": False, "found": False, "error": f"spec not found: {spec_name}"}
    from core.pm_engine.promotion import promote_drafted
    from core.state_machine import StateMachine
    from core.logger import Logger
    from core.config import ConfigLoader

    proot = Path(project_root)
    sm = StateMachine(proot / ".fenix" / "STATE.md", None)
    logger = Logger(proot)
    # 解析项目有效配置传给 promote_drafted，使评审分流判定与 daemon 同源
    # （add-spec-review-gate 3.4/3.5：不传 config 无法评估跳过白名单，恒直通 ready）
    config = ConfigLoader.resolve_config(proot)
    result = promote_drafted(proot, spec_name, state_machine=sm, logger=logger, config=config)
    if result["ok"]:
        # 依分流结论转移：命中跳过白名单 → ready；否则 → reviewing 待方案评审。
        # 与 _on_spec_drafted 收尾语义一致，MUST NOT 硬编码 ready（全通道覆盖）。
        next_status = result.get("next_status", "ready")
        # fix-observability-gaps 2.2：dashboard 人工晋升来源（channel=manual）
        sm.transition(
            spec_name, next_status,
            trigger_run_id=None, agent_type=None, channel="manual",
        )
        return {"ok": True, "found": True, "violations": [], "next_status": next_status}
    # 失败
    if "reason" in result:
        # 非 drafted 或不存在
        return {"ok": False, "found": True, "reason": result["reason"], "error": result["reason"]}
    # lint 违规（STATE error 已由 promote_drafted 写入）
    return {
        "ok": False,
        "found": True,
        "violations": result["violations"],
        "error": f"晋升 lint 未通过：{'; '.join(result['violations'])}",
    }


def reflow_spec(project_root, spec_name: str) -> dict:
    """task-gap 滞留 verified SPEC 的人工回炉（fix-impl-tasks-completion-gate P1′/D8）。

    判定与执行收敛到 core/pm_engine/task_reflow.reflow_spec 单一实现点——
    本包装只做 StateMachine/Logger 装配与结果归一化（与 promote_spec 同型，
    Dashboard 路由与 CLI reflow 子命令共用，MUST NOT 在两侧复写判定逻辑）。

    - spec 不存在 → {ok: False, found: False, reason: ...}
    - 不满足开放条件（非 verified / error 非 task-gap 前缀 / 冻结态 / 幂等重复）
      → {ok: False, found: True, reason: <明确拒绝原因>}
    - 成功 → {ok: True, found: True, spec, status: "ready"}
    """
    specs = parse_state(project_root)
    if spec_name not in specs:
        return {"ok": False, "found": False, "reason": f"spec not found: {spec_name}"}
    from core.pm_engine.task_reflow import reflow_spec as _reflow
    from core.state_machine import StateMachine
    from core.logger import Logger

    proot = Path(project_root)
    sm = StateMachine(proot / ".fenix" / "STATE.md", None)
    logger = Logger(proot)
    result = _reflow(proot, spec_name, state_machine=sm, logger=logger, source="api")
    result.setdefault("found", True)
    return result


def re_review_spec(project_root, spec_name: str) -> dict:
    """重新评审 blocked SPEC：复核开放条件后执行 blocked → reviewing 并派发新评审。

    条件校验复用 core/pm_engine/spec_review.py:SpecReviewManager.re_review
    （状态 MUST 为 blocked、error MUST 为 spec-review-* 前缀、MUST NOT 冻结）；
    不符合条件 STATE 零变更。
    - spec 不存在 → {"ok": False, "found": False, "error": ...}（路由 → 404）
    - 不符合开放条件 / 转移失败 / 派发失败 → {"ok": False, "found": True,
      "error": 明确原因}（路由非 200）
    - 成功 → {"ok": True, "found": True, "error": None}
    """
    specs = parse_state(project_root)
    if spec_name not in specs:
        return {"ok": False, "found": False, "error": f"spec not found: {spec_name}"}
    from core.pm_engine.spec_review import SpecReviewManager
    from core.state_machine import StateMachine
    from core.logger import Logger

    proot = Path(project_root)
    sm = StateMachine(proot / ".fenix" / "STATE.md", None)
    logger = Logger(proot)
    # agent_runner=None：跳过同步派发，由 daemon 全扫 recovery 的 reviewing
    # 分支拾取派发（与 CLI cmd_review 同构）；Dashboard 侧请求发往常驻 daemon
    # 管理的进程，状态先落盘、派发由既有调度链接力。
    review_manager = SpecReviewManager(proot, sm, None, None, {}, logger)
    ok, msg = review_manager.re_review(spec_name)
    if ok:
        return {"ok": True, "found": True, "error": None}
    return {"ok": False, "found": True, "error": msg}


SCHEDULING_KICK_REQUEST = ".fenix/scheduling_kick_request.json"


def _write_scheduling_kick_signal(project_root, spec: str) -> dict:
    """写入清空 start_after 后的即时派发唤醒信号（每 SPEC 一文件目录形态）。

    fix-scheduling-kick-single-slot：委托 core.signals.write_scheduling_kick，
    载体由单文件单槽位演进为每 SPEC 一个文件
    （.fenix/scheduling_kick/<spec>.json）。多槽位下不存在跨 SPEC 冲突，
    conflict 恒为 False；写入失败如实上报。

    保留与旧调用方兼容的 {"ok", "conflict", "file", "error"} 返回形状
    （error 字段供 D3 诚实回报链路透传写入失败原因）。
    """
    kick_result = write_scheduling_kick(project_root, spec)
    return {
        "ok": kick_result["ok"],
        "conflict": False,  # 多槽位下不再存在跨 SPEC 冲突
        "file": kick_result["file"],
        "error": kick_result.get("error"),
    }


def activate_spec(project_root, spec: str) -> dict:
    """激活待激活 SPEC：把 start_after 从 manual 置为 null 并即时唤醒派发。

    复用既有 ``_write_scheduling_kick_signal``（action='clear-start-after'），
    daemon 主循环 1s 粒度消费信号并唤起 ``_on_spec_ready``——激活动作与定时清空
    共享同一条唤醒通路（add-spec-manual-activation D4）。

    幂等语义：
    - spec 不在 STATE.md → ``{ok: False, found: False, error: ...}``
    - 终态（done/pushed）→ ``{ok: False, found: True, terminal: True, error: ...}``
    - 当前 start_after 非 manual → ``{ok: False, found: True,
      reason: "该 SPEC 并非待激活态（start_after 非 manual）"}``
      （STATE 零变更——幂等拒绝，不误清定时值）
    - 命中 → update_spec 清 start_after + 写 kick 信号
      → ``{ok: True, found: True, spec, start_after: None}``
    """
    from core.state_machine import StateMachine

    proot = Path(project_root)
    specs = parse_state(proot)
    if spec not in specs:
        return {"ok": False, "found": False, "error": f"spec not found: {spec}"}
    entry = specs[spec]
    status = entry.get("status")
    if status in ("done", "pushed"):
        return {
            "ok": False,
            "found": True,
            "terminal": True,
            "error": f"终态 spec（{status}）不可激活",
        }
    # 校验当前 start_after 是否为哨兵 manual（大小写不敏感 + strip 容错）
    raw_sa = entry.get("start_after") if isinstance(entry, dict) else None
    if not (isinstance(raw_sa, str) and raw_sa.strip().lower() == START_AFTER_MANUAL):
        return {
            "ok": False,
            "found": True,
            "reason": f"该 SPEC 并非待激活态（start_after 非 manual）",
        }
    # 命中 → 清 start_after + 唤醒信号；写入结果如实回报（D3），
    # CLI 与 Dashboard 依 ok 分支文案，不再无条件宣称「立即恢复调度」
    sm = StateMachine(proot / ".fenix" / "STATE.md", None)
    sm.update_spec(spec, {"start_after": None})
    kick_result = _write_scheduling_kick_signal(proot, spec)
    return {
        "ok": True,
        "found": True,
        "spec": spec,
        "start_after": None,
        "scheduling_kick": {"ok": kick_result["ok"], "error": kick_result.get("error")},
    }


def get_spec_start_after(entry: dict) -> str | None:
    """读取 entry 的 start_after 规范值（ISO8601 UTC 字符串 / 哨兵 "manual" / None）。

    纯读函数：非法格式/缺失按「无限制」处理（返回 None），供列表倒计时
    展示与前端状态推导用。时间换算/校验单点在后端（design D6）。
    - 哨兵 ``"manual"``（手工激活，add-spec-manual-activation D1）原样返回
      （在 parse_utc 之前判定——哨兵不是时间，parse_utc 会返回 None 被折叠）；
      大小写不敏感 + strip 容错人工手改 STATE.md。
    """
    from core.state_machine import parse_utc

    raw = entry.get("start_after") if isinstance(entry, dict) else None
    if raw is None:
        return None
    # 哨兵优先判定：合法值且语义特殊（手工激活），MUST NOT 折叠回 None
    if isinstance(raw, str) and raw.strip().lower() == START_AFTER_MANUAL:
        return START_AFTER_MANUAL
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
    """设置/清除 SPEC 的 start_after（定时拾取时间 / 手工激活哨兵）。

    取值三态（add-spec-manual-activation D4/D5）：
    - value 为 None/空串 → 清除定时（start_after 置 null，立即恢复调度）
    - value（字符串）``strip().lower() == "manual"`` → 设为待激活
      （写哨兵字符串，跳过 parse_utc 校验；**不**写 kick 信号——这是「设为
      等待」而非「恢复调度」，激活动作见 ``activate_spec``）
    - value 为合法 ISO8601 → 定时（原语义）
    - value 非法 → {invalid: True}（拒绝写入，STATE.md 不变）
    - 终态（done/pushed）→ {terminal: True}（拒绝，定时不影响终态语义）
    - 成功 → {ok: True, start_after: <ISO8601 UTC 或 None 或 "manual">}
    写入经 StateMachine.update_spec（flock + 原子 rename，与 daemon 并发写安全）。
    """
    from core.state_machine import StateMachine, parse_utc

    proot = Path(project_root)
    specs = parse_state(proot)
    if spec not in specs:
        return {"ok": False, "found": False, "error": f"spec not found: {spec}"}
    entry = specs[spec]
    if entry.get("status") in ("done", "pushed"):
        return {
            "ok": False,
            "found": True,
            "terminal": True,
            "error": f"终态 spec（{entry.get('status')}）不可设置定时拾取",
        }
    if value is None or (isinstance(value, str) and not value.strip()):
        normalized = None
    elif isinstance(value, str) and value.strip().lower() == START_AFTER_MANUAL:
        # 哨兵分支：大小写不敏感 + strip 容错；跳过 parse_utc（哨兵不是时间）。
        # 不写 kick 信号——设为待激活是「暂停调度」，不是「恢复调度」。
        normalized = START_AFTER_MANUAL
    else:
        dt = parse_utc(value)
        if dt is None:
            return {
                "ok": False,
                "found": True,
                "invalid": True,
                "error": f"start_after 非法 ISO8601: {value!r}",
            }
        normalized = dt.isoformat()
    sm = StateMachine(proot / ".fenix" / "STATE.md", None)
    sm.update_spec(spec, {"start_after": normalized})
    # 清空即唤醒（2026-09-08 fix-run-cancel-retry-flag-miss 事故路径）：status 恒为
    # ready，event_bus watcher 只盯 status 不发事件、check_scheduling_deadlines 只管
    # 「时间流逝到期」，此前清空后要等 30min 一轮 recovery full_scan 才被捞起。
    # 写文件信号（与 cancel_run_request 同构），daemon 主循环 1s 粒度拾取即派发。
    # 信号写入结果如实回报（fix-scheduling-kick-single-slot D3）：成功时前端宣称
    # 「立即恢复调度」，失败时告知将由下次扫描派发。
    scheduling_kick = None
    if normalized is None:
        kick_result = _write_scheduling_kick_signal(proot, spec)
        scheduling_kick = {"ok": kick_result["ok"], "error": kick_result.get("error")}
    return {"ok": True, "found": True, "start_after": normalized, "scheduling_kick": scheduling_kick}


def set_spec_budget(project_root, spec: str, budget) -> dict:
    """设置/清除 SPEC 的实现尝试预算覆盖（impl_run_budget_override）。

    budget 取值：
    - None：清除覆盖（属性置 null，恢复跟随全局 agents.impl_run_budget）；
    - 1 至 agents.impl_run_budget_max（缺省 100）的整数：写入 per-spec 覆盖值；
    - 其余：{invalid: True}（拒绝写入，STATE.md 不变）。

    校验：
    - spec 不在 STATE.md → {found: False}
    - 终态（done/pushed）→ {terminal: True}（终态修改预算无意义）
    - 非法值 → {invalid: True}
    - 成功 → {ok: True, budget: <整数或 None>}
    写入经 StateMachine.update_spec（flock + 原子 rename，与 daemon 并发写安全）。

    边界（add-spec-status-modal-budget D3）：本函数只写覆盖属性
    ``impl_run_budget_override``，MUST NOT 触碰 ``_impl_run_budget_used``
    已用计数——已用次数归对账组件 _reconcile_impl_budget 管辖，本能力只改预算上限。
    """
    proot = Path(project_root)
    specs = parse_state(proot)
    if spec not in specs:
        return {"ok": False, "found": False, "budget": None, "error": f"spec not found: {spec}"}
    entry = specs[spec]
    if entry.get("status") in ("done", "pushed"):
        return {
            "ok": False,
            "found": True,
            "terminal": True,
            "budget": None,
            "error": f"终态 spec（{entry.get('status')}）不可设置预算覆盖",
        }
    # null 清除
    if budget is None:
        from core.state_machine import StateMachine

        sm = StateMachine(proot / ".fenix" / "STATE.md", None)
        sm.update_spec(spec, {"impl_run_budget_override": None})
        return {"ok": True, "found": True, "budget": None}
    # 非法值校验（int，非 bool，[1, 有效上限]）
    # open-impl-budget-ceiling：上限 = agents.impl_run_budget_max（缺省 100），
    # 与闸门/Dashboard 摘要同源解析，保证「界面可设范围」与「闸门夹紧范围」一致。
    from core.pm_engine.budget import (
        resolve_impl_run_budget_max,
        IMPL_RUN_BUDGET_MAX_KEY,
        IMPL_RUN_BUDGET_MAX_DEFAULT,
    )
    from core.config import ConfigLoader

    budget_max = resolve_impl_run_budget_max(
        ConfigLoader.get(
            ConfigLoader.resolve_config(proot), IMPL_RUN_BUDGET_MAX_KEY, IMPL_RUN_BUDGET_MAX_DEFAULT
        )
    )
    if isinstance(budget, bool) or not isinstance(budget, int):
        return {
            "ok": False,
            "found": True,
            "budget": None,
            "invalid": True,
            "error": f"budget must be an integer between 1 and {budget_max} (or null to clear)",
        }
    if budget < 1 or budget > budget_max:
        return {
            "ok": False,
            "found": True,
            "budget": None,
            "invalid": True,
            "error": f"budget must be an integer between 1 and {budget_max} (or null to clear)",
        }
    from core.state_machine import StateMachine

    sm = StateMachine(proot / ".fenix" / "STATE.md", None)
    sm.update_spec(spec, {"impl_run_budget_override": budget})
    return {"ok": True, "found": True, "budget": budget}


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
        return {
            "ok": False,
            "found": True,
            "error": "spec 未处于冻结态（冻结管理仅对冻结 spec 生效）",
        }
    sm = StateMachine(proot / ".fenix" / "STATE.md", None)
    if mode == "unfreeze":
        orig = parse_orig_status(entry.get("error"))
        sm.unfreeze_spec(spec, status=orig)
        return {
            "ok": True,
            "found": True,
            "mode": "unfreeze",
            "unfrozen": True,
            "frozen_until": None,
        }
    if mode == "permanent":
        sm.update_spec(spec, {"frozen_until": None})
        return {"ok": True, "found": True, "mode": "permanent", "frozen_until": None}
    if mode == "scheduled":
        dt = parse_utc(until)
        if dt is None:
            return {
                "ok": False,
                "found": True,
                "invalid": True,
                "error": f"frozen_until 非法 ISO8601: {until!r}",
            }
        normalized = dt.isoformat()
        if dt <= datetime.now(timezone.utc):
            # 已过去 → 立即解冻（等价到期，不留待下一轮 tick/扫描）
            orig = parse_orig_status(entry.get("error"))
            sm.unfreeze_spec(spec, status=orig)
            return {
                "ok": True,
                "found": True,
                "mode": "scheduled",
                "unfrozen": True,
                "frozen_until": normalized,
            }
        sm.update_spec(spec, {"frozen_until": normalized})
        return {"ok": True, "found": True, "mode": "scheduled", "frozen_until": normalized}
    return {"ok": False, "found": True, "invalid": True, "error": f"未知冻结模式: {mode!r}"}


APPROVE_PUSH_REQUEST = ".fenix/approve_push_request.json"


def request_spec_approve_push(project_root, spec: str) -> dict:
    """写入 SPEC 审批推送的文件信号（.fenix/approve_push_request.json）。

    校验链（全部通过才写信号）：
    - spec 不在项目 STATE.md → {ok: False, found: False}
    - status 非 done → {ok: False, terminal: True}（error 区分 pushed 幂等
      文案与其它非 done 状态文案）
    - daemon 未受 supervisor 托管（`core.fenix_session.hosting_state(proot)`
      非 "managed"）→ {ok: False, daemon_down: True}（stopped）或
      {ok: False, unmanaged: True}（进程在跑但无 supervisor）——信号无人
      消费会静默滞留，比明确报错更糟（design D2 + fix-supervisor-hosting-chain
      D8），前置拦截
    - 已存在未消费信号 → {ok: False, conflict: True}（对齐 request_run_cancel
      冲突语义，读既有 created 供返回）
    通过校验后原子写（tmp+rename + fsync，与 request_admin_invoke 同构）
    {"spec": spec, "source": "dashboard", "created": <ISO8601 UTC>}。

    消费方判据（fix-supervisor-hosting-chain D8）：从「daemon 进程存活」
    升级为「受 supervisor 托管的活跃 daemon」（hosting_state == "managed"）
    ——进程在跑但无 supervisor（unmanaged）时文件信号无人消费，会永久滞留
    并锁死该项目后续全部审批推送；此时 MUST NOT 写信号，返回带
    unmanaged: True 的失败结果。

    本函数只写信号、不触碰 STATE.md——状态推进（done → pushed）由 daemon
    侧 `pm_engine.approve_push` 的 `transition(pushed)` 完成；退避/失败由
    既有 `_handle_push_failure` 链路接管（推送失败写回退避标记或升级
    push_failed 信号），本函数不新增任何推送语义。

    Returns:
        {"ok": bool, "found": bool, "terminal": bool, "daemon_down": bool,
         "unmanaged": bool, "conflict": bool, "file": str|null,
         "created": str|null, "error": str|null}
    """
    proot = Path(project_root)
    specs = parse_state(proot)
    if spec not in specs:
        return {
            "ok": False,
            "found": False,
            "terminal": False,
            "daemon_down": False,
            "unmanaged": False,
            "conflict": False,
            "file": None,
            "created": None,
            "error": f"spec not found: {spec}",
        }

    entry = specs[spec]
    status = entry.get("status")
    if status != "done":
        if status == "pushed":
            # 幂等拒绝：已推送终态，无需审批（与 approve_push 幂等跳过同语义）
            msg = "SPEC 已推送（pushed），无需审批"
        else:
            msg = f"仅 done 状态可审批推送（当前 {status}）"
        return {
            "ok": False,
            "found": True,
            "terminal": True,
            "daemon_down": False,
            "unmanaged": False,
            "conflict": False,
            "file": None,
            "created": None,
            "error": msg,
        }

    # 消费方判据（D8）：托管态为准——unmanaged 拒绝（信号无人消费）、
    # stopped 维持既有 daemon_down 文案、managed 放行。
    from core.fenix_session import hosting_state as _hosting_state

    try:
        state = _hosting_state(proot)
    except Exception:
        state = "stopped"  # 判定异常按未运行兜底，宁拒勿假放行
    if state == "unmanaged":
        return {
            "ok": False,
            "found": True,
            "terminal": False,
            "daemon_down": False,
            "unmanaged": True,
            "conflict": False,
            "file": None,
            "created": None,
            "error": (
                "本项目 daemon 未受 supervisor 托管，审批推送信号"
                "不会被消费。经 Dashboard 项目页「安装托管」或 "
                "/fenix-setup 恢复 supervisor 托管后重试"
            ),
        }
    if state != "managed":
        # stopped（或判定异常兜底）：维持既有 daemon_down 文案逐字不变
        return {
            "ok": False,
            "found": True,
            "terminal": False,
            "daemon_down": True,
            "unmanaged": False,
            "conflict": False,
            "file": None,
            "created": None,
            "error": "daemon 未运行，请先启动 daemon",
        }

    req_path = proot / APPROVE_PUSH_REQUEST
    if req_path.exists():
        # 读既有 created 供返回（对齐 request_run_cancel 冲突语义）
        existing_created = None
        try:
            existing = json.loads(req_path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                existing_created = existing.get("created")
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            pass
        return {
            "ok": False,
            "found": True,
            "terminal": False,
            "daemon_down": False,
            "unmanaged": False,
            "conflict": True,
            "file": str(req_path),
            "created": existing_created,
            "error": "已有进行中的审批推送请求",
        }

    created = datetime.now(timezone.utc).isoformat()
    payload = {"spec": spec, "source": "dashboard", "created": created}
    req_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(req_path.parent), prefix=".approve_push_request.", suffix=".tmp"
    )
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
    return {
        "ok": True,
        "found": True,
        "terminal": False,
        "daemon_down": False,
        "unmanaged": False,
        "conflict": False,
        "file": str(req_path),
        "created": created,
        "error": None,
    }


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
