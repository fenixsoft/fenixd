"""core.dashboard.data.admin_actions — Administrator/SPEC 写操作（admin_actions 组）。

refactor-dashboard-data-module D3 分组：本模块承载 admin 写操作职责域。
请求信号（admin invoke / run cancel / scheduling kick / approve push）、
冻结/解冻、晋升/回拨/重新评审、定时拾取、预算覆盖。
"""

import json
import logging
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
from .state import normalize_bool_flag, parse_state

# run 归属全等匹配（add-freeze-stop-inflight-agents 4.4：running_run_ids_for_spec
# 与 daemon 消费方共用——run_spec_part 已剥 agent 前缀与 -a<n>/-r<n>/时间戳）
from core.agent_runner.run_files import run_spec_part

# 托管态判定（add-freeze-stop-inflight-agents 4.3/5.1：request_spec_delete 前置
# 校验 daemon 未托管时信号无人消费——模块顶层导入使单测可 patch 该绑定）
from core.fenix_session import hosting_state as _hosting_state

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

# 裁决动词的失败留痕通道（code-review item 7e377b667b7b）：旧的
# `except Exception: pass` 把调度唤醒信号/幂等标记复位失败静默吞掉——
# 丢 kick 会让 deferred start_after 滞留无迹，丢标记复位会让预算告警被
# token_budget 幂等门永久静默。统一 WARNING 留痕 + 步骤后缀如实回显。
logger = logging.getLogger("fenixd.dashboard.admin_actions")


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
    文本契约」），且为**独立判据**——任意 status 下 ``frozen=True`` 即冻结。
    验证 BUG-01（add-human-adjudication-choices）：原实现首行
    ``status != 'blocked'`` 提前返回，reviewing+frozen 的评审器失败冻结
    （SPEC 语义形态：冻结起源态 reviewing 经「原状态 reviewing」内嵌保留）
    被误判为未冻结，skip_review_gate 在 CLI/API/Web 三条消费通道全被拒。
    文本前缀仅作存量兼容回退。自动冻结（内容完整性闸门 / 预算闸门 / env
    阻塞）一律写自有文案而非「用户指令冻结：」，只认文本会让它们在
    dashboard 里既不显示冻结态也走不了解冻入口。
    """
    if entry.get("frozen") is True:
        return True
    if entry.get("status") != "blocked":
        return False
    return (entry.get("error") or "").startswith(FREEZE_ERROR_PREFIX)


SPEC_DELETE_REQUEST = ".fenix/spec_delete_request.json"
# 删除先停后删的等待总上限（task 5.3：daemon 消费侧与数据层共用常量；
# 每 run 宽限沿用 liveness.AGENT_TERMINATE_GRACE_SECONDS=10s，总窗口
# 足够覆盖该 spec 全部在跑 run 的 terminate→grace→kill 序列）
SPEC_DELETE_STOP_WAIT_TOTAL_SECONDS = 60


def running_run_ids_for_spec(project_root, spec: str) -> list:
    """枚举某 spec 名下仍在跑的 run_id 列表（add-freeze-stop-inflight-agents 4.4）。

    扫描 ``.fenix/runs/*.jsonl`` 顶层（活跃目录）——``_resolve_run_file`` 的
    archive 回读口径不适用于「在跑」判定（已归档 run 不可能在跑）。归属用
    ``run_spec_part(p.stem) == spec`` 全等（复用 run_files 已剥前后缀）；
    在跑判定 = 末行**非**终态。终态口径 MUST 用写侧权威集合并集：
    ``liveness.RUN_TERMINAL_EVENT_TYPES``（result/interrupted/error/cancelled/
    frozen-terminated）——MUST NOT 复用 ``classify_run``：其读侧映射含
    ``superseded``，而 superseded 不在终态集合内（原地重试弃置事件，其后
    还有新 attempt 在跑），复用会把活跃 run 误判为已终态、让删除在 run 仍
    可能写盘时移走 spec 目录（违反「等待超时不删除」硬约束）。

    Returns: 仍在跑的 run 产物 stem 列表（含 -a<n>/-r<n> 后缀，供调用方
    精确终止/展示）。
    """
    from core.agent_runner.liveness import RUN_TERMINAL_EVENT_TYPES

    runs_dir = Path(project_root) / ".fenix" / "runs"
    running: list = []
    if not runs_dir.is_dir():
        return running
    try:
        for p in runs_dir.glob("*.jsonl"):
            if run_spec_part(p.stem) != spec:
                continue
            # 末行终态判定（逐行扫描取末行，损坏 JSON 行跳过——与
            # liveness._file_has_terminal_event 同口径；文件不可读视为在跑，
            # 宁可保守不删）
            last_type = None
            try:
                with p.open("r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                        except (json.JSONDecodeError, ValueError):
                            continue
                        if isinstance(entry, dict) and entry.get("type"):
                            last_type = entry.get("type")
            except OSError:
                last_type = None
            if last_type not in RUN_TERMINAL_EVENT_TYPES:
                running.append(p.stem)
    except OSError:
        pass
    return running


def request_spec_delete(project_root, spec: str, stopping: int = 0) -> dict:
    """写入 SPEC 删除请求的文件信号（.fenix/spec_delete_request.json）。

    异步受理契约（add-freeze-stop-inflight-agents D5/4.3）：该 spec 有在跑
    agent 时，dashboard 侧不阻塞等待终止——写信号立即返回受理结果，由
    daemon 主循环消费（停 agent → 有界等待终态 → soft_delete_spec）。原子写
    tmp+rename+fsync（与 request_run_cancel 同构）。

    前置校验（对齐 request_spec_approve_push 契约）：
    - daemon 未受 supervisor 托管（hosting_state != "managed"）→ 信号无人
      消费，返回 unmanaged/daemon_down 拒绝；
    - 已存在未消费信号 → conflict 409（对齐 request_run_cancel 语义）。

    Args:
        stopping: 待停止的在跑 agent 计数（API 侧经 running_run_ids_for_spec
            预先计数，写进信号供 daemon 日志/审计）。

    Returns:
        {"ok", "conflict", "unmanaged", "daemon_down", "file", "created",
         "error"}
    """
    proot = Path(project_root)
    # _hosting_state 已在模块顶层导入（测试可 patch 该绑定）

    try:
        state = _hosting_state(proot)
    except Exception:
        state = "stopped"
    if state == "unmanaged":
        return {
            "ok": False,
            "conflict": False,
            "unmanaged": True,
            "daemon_down": False,
            "file": None,
            "created": None,
            "error": (
                "本项目 daemon 未受 supervisor 托管，删除信号不会被消费。"
                "经 Dashboard 项目页「安装托管」或 /fenix-setup 恢复"
                "supervisor 托管后重试"
            ),
        }
    if state != "managed":
        return {
            "ok": False,
            "conflict": False,
            "unmanaged": False,
            "daemon_down": True,
            "file": None,
            "created": None,
            "error": "daemon 未运行，请先启动 daemon",
        }

    req_path = proot / SPEC_DELETE_REQUEST
    if req_path.exists():
        existing_created = None
        try:
            existing = json.loads(req_path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                existing_created = existing.get("created")
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            pass
        return {
            "ok": False,
            "conflict": True,
            "unmanaged": False,
            "daemon_down": False,
            "file": str(req_path),
            "created": existing_created,
            "error": "已有进行中的删除请求",
        }

    created = datetime.now(timezone.utc).isoformat()
    payload = {
        "spec": spec,
        "source": "dashboard",
        "created": created,
        "stopping": int(stopping or 0),
    }
    req_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(req_path.parent), prefix=".spec_delete_request.", suffix=".tmp"
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
        "unmanaged": False,
        "daemon_down": False,
        "file": str(req_path),
        "created": created,
        "error": None,
    }


def freeze_spec(project_root, spec_name: str, reason: str = "") -> dict:
    """人工冻结 SPEC：status→blocked，error 以「用户指令冻结：」开头并记录原状态。

    - done/pushed 终态不可冻结（冻结终态破坏语义），返回 ok=True + frozen=False
    - 写回委托 StateMachine.freeze_spec（add-spec-scheduling-controls D4 收编）：
      结构化 frozen: True 标记 + 原状态并入 reason（``用户指令冻结：原状态 X
      [ · reason]``），daemon 经 STATE.md watcher 感知后停止调度。此前直写
      update_spec 只写 {status, error} 不写 frozen 标记，与 StateMachine 冻结
      双轨并行时产生「解冻后 status 被冻结保护剥离」的半死态，本版本消除。

    add-freeze-stop-inflight-agents 6.x 验证修复（BUG-01）：冻结成功时统计
    并返回 ``stopped_agents``（冻结时刻在跑 agent 计数），供前端展示
    「已停止 N 个在跑 agent，进度已留存，解冻后可续做」。冻结写入本身为
    非阻塞 STATE 更新，计数基于冻结写入前的 run 文件快照；在冻结写入与
    runner 轮询环感知之间的短暂窗口内，仍有 run 文件非终态但已不可见
    对新 freeze_spec 调用的影响极小（daemon 下一轮 watcher 触发）。
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
    # 冻结前统计在跑 agent 数（proposal Impact「freeze_spec 返回值扩展
    # （stopped_agents 计数）」；验证 BUG-01 修复点）——冻结 STATE 写入
    # 后 runner 轮询环感知到 frozen 终止，计数为终止窗口前的快照值。
    running = running_run_ids_for_spec(project_root, spec_name)
    from core.state_machine import StateMachine, project_state_logger

    sm = StateMachine(Path(project_root) / ".fenix" / "STATE.md", project_state_logger(project_root))
    sm.freeze_spec(spec_name, reason=note)
    return {"ok": True, "found": True, "frozen": True, "error": None, "stopped_agents": len(running)}


def unfreeze_spec(project_root, spec_name: str) -> dict:
    """解冻 SPEC：从冻结 error 中恢复原状态并清空 error；未冻结则为 no-op。

    委托 StateMachine.unfreeze_spec（D4 收编）：status 传解析出的原状态，
    恢复为冻结前状态并清 error/frozen_until。此前直写 update_spec 对带
    frozen 标记的结构化冻结 spec 会被冻结保护剥离 status，残留半死态。

    add-freeze-stop-inflight-agents 2.6：传入 project_root 与就地构造的
    WorktreeManager（dashboard 独立进程，此前零处 import）；构造失败或
    工作目录异常时降级为 None（跳过续做判定，与脚本/测试场景同语义）——
    MUST NOT 因构造失败使解冻本身失败。
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
    from core.state_machine import StateMachine, project_state_logger
    sm = StateMachine(Path(project_root) / ".fenix" / "STATE.md", project_state_logger(project_root))
    _wt_mgr = None
    try:
        from core.worktree_manager import WorktreeManager
        _wt_mgr = WorktreeManager(
            base_dir=Path(project_root) / ".fenix",
            project_root=Path(project_root),
            logger=None,
        )
    except Exception:
        pass
    sm.unfreeze_spec(spec_name, status=orig,
                     project_root=Path(project_root),
                     worktree_manager=_wt_mgr)
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
    from core.state_machine import StateMachine, project_state_logger
    from core.pm_engine.verification import reclassify_infra_rounds as _recl

    specs = parse_state(project_root)
    if spec_name not in specs:
        return {"ok": False, "found": False, "error": f"spec not found: {spec_name}"}
    if not str(audit_reason or "").strip():
        return {"ok": False, "found": True, "error": "audit_reason 必填（审计留痕要求）"}
    sm = StateMachine(Path(project_root) / ".fenix" / "STATE.md", project_state_logger(project_root))
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
    from core.state_machine import StateMachine, project_state_logger
    from core.logger import Logger
    from core.config import ConfigLoader

    proot = Path(project_root)
    sm = StateMachine(proot / ".fenix" / "STATE.md", project_state_logger(proot))
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
    from core.state_machine import StateMachine, project_state_logger
    from core.logger import Logger

    proot = Path(project_root)
    sm = StateMachine(proot / ".fenix" / "STATE.md", project_state_logger(proot))
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
    from core.state_machine import StateMachine, project_state_logger
    from core.logger import Logger

    proot = Path(project_root)
    sm = StateMachine(proot / ".fenix" / "STATE.md", project_state_logger(proot))
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


def _kick_step_suffix(project_root, spec: str) -> str:
    """裁决动词写调度唤醒信号并返回步骤后缀（code-review item 7e377b667b7b）。

    失败不再静默（新动词旧实现 `except Exception: pass`）：丢 kick 会让
    spec 的 deferred ``start_after`` 滞留不清且无迹可查。WARNING 留痕 + 步骤
    后缀如实报告（经 alert-resolve/处置回显透出），供人工补清 start_after。
    """
    try:
        kick = _write_scheduling_kick_signal(project_root, spec)
        if kick.get("ok"):
            return "，已写调度唤醒信号"
        reason = kick.get("error") or "写入被拒"
        logger.warning("scheduling kick 写入失败 spec=%s: %s", spec, reason)
        return f"（调度唤醒信号写入失败：{reason}；如带 start_after 延迟将不会被清除）"
    except Exception as e:
        logger.warning("scheduling kick 写入异常 spec=%s: %s", spec, e)
        return "（调度唤醒信号写入异常；如带 start_after 延迟将不会被清除）"


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
    from core.state_machine import StateMachine, project_state_logger

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
    sm = StateMachine(proot / ".fenix" / "STATE.md", project_state_logger(proot))
    sm.update_spec(spec, {"start_after": None})
    kick_result = _write_scheduling_kick_signal(proot, spec)
    return {
        "ok": True,
        "found": True,
        "spec": spec,
        "start_after": None,
        "scheduling_kick": {"ok": kick_result["ok"], "error": kick_result.get("error")},
    }


def _hold_state_true(v) -> bool:
    """取消保持标记归一化读值（add-cancelled-spec-resume-action D1）。

    单点委托 core.dashboard.data.state.normalize_bool_flag（与 parse_state
    对 frozen/_cancelled_hold 归一化口径逐字一致）。
    """
    return normalize_bool_flag(v)


def resume_cancelled_spec(project_root, spec: str) -> dict:
    """恢复取消保持态 SPEC：复位 ready 并按保留分支续做（add-cancelled-spec-resume-action）。

    取消保持态（``_cancelled_hold: true``，fix-cancel-holdstate-recovery）是
    「有意等待」：全部自动恢复链路对其显式跳过，唯一出路是显式复位。本动作
    是该状态的界面出口，语义与冻结终止的「解冻续做」（unfreeze_spec +
    ``_frozen_hold``）对齐：

    - 命中：调 ``StateMachine._resolve_preserved_branch``（context=
      "Cancel-hold resume"）解析保留分支，通过则单次原子写续做集
      （收口字段集与 ``state_machine.py`` ``_recovery_preserve_spec`` 续做
      先例同集），携带 status 即由 update_spec 自动清 ``_cancelled_hold``
      （既有 D4 语义），后写 scheduling_kick 即时唤醒派发；
    - 降级：共享判定**真正运行过**且不通过（三层锚点均不可得 / 分支零提交 /
      载体不可用）→ WARNING 留痕 + 原子写降级集（branch/implementer_run
      清空、不置 ``_recovery_resume``），返回 ``degraded: true`` + 原因；
    - fail-closed：WorktreeManager 构造失败（保留判定根本未运行）MUST 拒绝
      且 STATE 零变更——该情形下「无可保留分支」没有依据，降级清锚点会把
      仍可续做的保留分支从 STATE 脱钩（正是本动作要消除的事故面）。

    拒绝语义（对齐 freeze-config 家族幂等拒绝）：
    - spec 不存在 → ``{ok: False, found: False, error}``
    - 终态（done/pushed）→ ``{ok: False, terminal: True, error}``（路由 403）
    - 冻结态（结构化 frozen 或文本前缀）→ ``{ok: False, reason}``（须先解冻，
      禁止绕过）
    - ``_cancelled_hold`` 非 true → ``{ok: False, reason}``（幂等拒绝，
      STATE 零变更）
    """
    from core.state_machine import StateMachine, project_state_logger

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
            "error": f"终态 spec（{status}）不可恢复",
        }
    if is_spec_frozen(entry):
        return {
            "ok": False,
            "found": True,
            "reason": "冻结 SPEC 须先解冻，禁止绕过冻结直接恢复（unfreeze_spec 后再恢复）",
        }
    if not _hold_state_true(entry.get("_cancelled_hold")):
        return {
            "ok": False,
            "found": True,
            "reason": f"该 SPEC 并非取消保持态（_cancelled_hold 非 true，status={status}）",
        }
    # 就地构造 WorktreeManager（dashboard 独立进程，与 unfreeze_spec 先例同型）。
    # 构造失败 → fail-closed 拒绝（保留判定未运行，禁止降级清锚点）。
    try:
        from core.worktree_manager import WorktreeManager
        wm = WorktreeManager(
            base_dir=proot / ".fenix",
            project_root=proot,
            logger=None,
        )
    except Exception:
        wm = None
    if wm is None:
        return {
            "ok": False,
            "found": True,
            "reason": "worktree 管理器不可用，无法判定保留分支",
        }
    sm = StateMachine(proot / ".fenix" / "STATE.md", project_state_logger(proot))
    resolved_branch, _wt = sm._resolve_preserved_branch(
        spec, entry, proot, wm, context="Cancel-hold resume")
    if resolved_branch is not None:
        # 命中 → 保留分支续做（收口字段集与 state_machine _recovery_preserve_spec
        # 续做先例同集：tester_run 清空防误读为在飞验证锚点，_merge_*/重派
        # 计数归零防陈旧计数触发误熔断/误告警）。
        sm.update_spec(spec, {
            "status": "ready",
            "error": f"Recovered from cancelled hold (resume preserved branch)：原状态 {status}",
            "branch": resolved_branch,
            "implementer_run": entry.get("implementer_run"),
            "_recovery_resume": True,
            "tester_run": None,
            "_retry_count": 0,
            "_merge_fp": None,
            "_merge_streak": 0,
            "_redispatch_same_cause_streak": 0,
            "_redispatch_cause_fp": None,
        })
        result = {"ok": True, "found": True, "spec": spec, "degraded": False}
    else:
        # 降级：共享判定已实际运行且给出「不可保留」结论 → 普通全新重派。
        # _resolve_preserved_branch 各失败层内已有 WARNING 留痕；此处写降级集
        # （不置 _recovery_resume），携带 status 即自动清保持标记。
        sm.update_spec(spec, {
            "status": "ready",
            "error": "Recovered from cancelled hold (no preserved branch — fresh dispatch)"
                     f"：原状态 {status}",
            "branch": None,
            "implementer_run": None,
            # 降级同为人工裁决出口，陈旧计数无条件清零（与 unfreeze_spec 命中/
            # 降级两路径同款，state_machine.py 人工处置清零先例）：取消收尾刻意
            # 保留的 _retry_count/_merge_*/重派计数若残留，全新重派首几轮即可
            # 误触发同因熔断/合并告警——正是命中分支注释点名的同一事故面。
            "_retry_count": 0,
            "_merge_fp": None,
            "_merge_streak": 0,
            "_redispatch_same_cause_streak": 0,
            "_redispatch_cause_fp": None,
        })
        result = {
            "ok": True,
            "found": True,
            "spec": spec,
            "degraded": True,
            "reason": "无可保留分支（STATE.branch 缺失 / 分支相对 main 零提交 / 载体不可用），降级全新重派",
        }
    # 即时唤醒派发（与 activate_spec 同一通路）；写入失败如实回传 warning，
    # STATE 已变更不回滚（语义对齐 spec-activate 的 D3 诚实回报）。
    kick_result = _write_scheduling_kick_signal(proot, spec)
    if not kick_result["ok"]:
        result["warning"] = (
            "已复位 ready，但即时唤醒信号写入失败，将由下次扫描"
            "（缺省 ≤30 分钟，即 schedule.poll_interval_minutes）派发"
        )
    return result


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
    from core.state_machine import StateMachine, parse_utc, project_state_logger

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
    sm = StateMachine(proot / ".fenix" / "STATE.md", project_state_logger(proot))
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
        from core.state_machine import StateMachine, project_state_logger

        sm = StateMachine(proot / ".fenix" / "STATE.md", project_state_logger(proot))
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
    from core.state_machine import StateMachine, project_state_logger

    sm = StateMachine(proot / ".fenix" / "STATE.md", project_state_logger(proot))
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
    from core.state_machine import StateMachine, parse_utc, project_state_logger

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
    sm = StateMachine(proot / ".fenix" / "STATE.md", project_state_logger(proot))
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
    from core.state_machine import StateMachine, project_state_logger

    sm = StateMachine(proot / ".fenix" / "STATE.md", project_state_logger(proot))
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

    from core.state_machine import StateMachine, project_state_logger

    sm = StateMachine(proot / ".fenix" / "STATE.md", project_state_logger(proot))
    sm.update_spec(spec, {"priority": p})
    return {"found": True, "priority": p}


# ── 裁决动词（add-human-adjudication-choices 3.x）────────────────────────
# 语义：人工对桶 2 冻结信号的裁决收敛为注册表选择题（D1），本节提供选项
# ``action`` 映射的后端动词；alert-resolve 端点与 Administrator 处置消费
# 共用 :func:`execute_adjudication_choice` 单一映射执行器。

# 验证链信号（reset_verification 适用域）：signal_type 显式传入时按此精确
# 判别；无 signal_type 上下文（直接动词调用）时回退 error 文本关键词判别。
VERIFY_CHAIN_SIGNAL_TYPES = frozenset({
    "impl_budget_exhausted",
    "judge_rerun_cap",
    "verify_fail_escalation",
    "redispatch_loop_detected",
})
_VERIFY_CHAIN_ERROR_MARKERS = (
    "judge", "验证", "重派", "预算", "verify", "inconclusive", "env",
)

# 非验证链冻结 reason 排除表（code-review item 0d6dd05975ba）：token_budget 的
# freeze_stop_loss 裁决写「用户指令冻结：token 预算止损（人工裁决）」，reason
# 含「预算」——上面的单 marker 子串判别会把它误划进验证链，对验证链之外的
# spec 删验证进度文件并清零计数。命中 marker 前先按本表显式排除（逐案补充
# 已知非验证链用户指令 reason；排除优先于命中）。
_NON_VERIFY_CHAIN_FREEZE_REASONS = ("token 预算止损",)

# 冻结场景与验证进度运行时文件（reset_verification 删除清单：按 spec 名
# 精确拼路径，禁通配；tokens.json 为生命周期成本审计侧车，保留不清）。
_VERIFY_PROGRESS_RUNTIME_FILES = (
    "test_scenarios.json",
    "_scenarios_full.json",
    "report.json",
    ".fenix-run-result.json",
    "degrade_context.json",
)

# 重置/继续修复时清零的重试计数器（unfreeze_spec 自动清零集的超集补充：
# judge/verify 失败轮不在其清零面）。布尔标记清 False——与 unfreeze_spec 清
# _verify_parallel_override 同款先例：STATE.md 是文本表，落盘规范形即
# `False` 字面量，生产读者经 StateMachine.parse 的布尔归一清单
# （_judge_cap_frozen/_verify_parallel_override 在列，state_machine.py）读回
# 真 False；计数清 0 后消费端 int(...or 0) 语义不变。生命周期累计字段
# （_tokens_*、_cost_usd）与实现预算 _impl_run_budget_used 不在此——后者仅
# continue_auto_fix 语义清零，reset_verification 不重发实现预算。
_RETRY_COUNTER_RESETS = {
    "_judge_rerun_count": 0,
    "_judge_cap_frozen": False,
    "_verify_fail_rounds": 0,
    "_verify_redo_count": 0,
    "_verify_parallel_override": False,
    "_inconclusive_attempts": 0,
    "_env_block_rounds": 0,
    "_redispatch_same_cause_streak": 0,
    "_redispatch_cause_fp": None,
}

# force_advance 允许的目标状态（design D4：校验目标可达性，不开放任意跳转）
_FORCE_ADVANCE_TARGETS = ("done", "verified")


def _adjudication_sm(project_root):
    """裁决动词共用的 StateMachine 构造（flock + 原子写，与 daemon 并发安全）。"""
    from core.state_machine import StateMachine, project_state_logger

    return StateMachine(
        Path(project_root) / ".fenix" / "STATE.md",
        project_state_logger(project_root),
    )


def reset_verification(project_root, spec: str, note: str = "", signal_type: str = "") -> dict:
    """裁决动词：人工裁定验证链输入已失真，重置验证重跑（add-human-adjudication-choices 3.1）。

    执行序列：前置校验（冻结/blocked 且属验证链信号）→ 删该 spec 的场景与
    验证进度运行时文件（精确 spec 名拼路径，禁通配）→ 清 judge 重跑与验证
    失败轮计数并剥冻结清 error（保持 blocked）→ 按
    ``resolve_env_blocked_reset_path`` 推进（分支已合并走 BLOCKED→TESTING
    门禁直通道重验，否则 BLOCKED→READY 回实现并写调度唤醒信号）→ 返回执行
    步骤明细。生命周期累计字段（tokens/cost 审计）不清零。

    Returns:
        {"ok": bool, "found": bool, "steps": [str], "target_status": str|null,
         "error": str|null}
    """
    proot = Path(project_root)
    specs = parse_state(proot)
    if spec not in specs:
        return {"ok": False, "found": False, "steps": [], "target_status": None,
                "error": f"spec not found: {spec}"}
    entry = specs[spec]
    if not (is_spec_frozen(entry) or entry.get("status") == "blocked"):
        return {
            "ok": False, "found": True, "steps": [], "target_status": None,
            "error": (f"spec 未处于冻结/blocked 态（当前 {entry.get('status')}），"
                      "重置验证仅对验证链冻结/blocked 开放"),
        }
    if signal_type:
        if signal_type not in VERIFY_CHAIN_SIGNAL_TYPES:
            return {
                "ok": False, "found": True, "steps": [], "target_status": None,
                "error": (f"signal_type '{signal_type}' 不属验证链信号，"
                          "重置验证被拒绝"),
            }
    else:
        error_text = str(entry.get("error") or "")
        # 显式排除先行（code-review item 0d6dd05975ba）：成本止损类用户指令
        # 冻结的 reason 含「预算」，不排除会被 marker 子串误放行
        if any(r in error_text for r in _NON_VERIFY_CHAIN_FREEZE_REASONS):
            return {
                "ok": False, "found": True, "steps": [], "target_status": None,
                "error": "冻结原因属用户指令成本止损（非验证链信号），重置验证被拒绝",
            }
        if not any(m in error_text for m in _VERIFY_CHAIN_ERROR_MARKERS):
            return {
                "ok": False, "found": True, "steps": [], "target_status": None,
                "error": "冻结原因不属验证链信号（error 文本无验证链特征），重置验证被拒绝",
            }

    steps: list = []
    # 2. 删该 spec 自己的场景/进度文件（路径按 spec 名精确构造，无 glob）
    vp_dir = proot / ".fenix" / "verify-progress" / spec
    for fname in _VERIFY_PROGRESS_RUNTIME_FILES:
        fpath = vp_dir / fname
        if fpath.is_file():
            try:
                fpath.unlink()
                steps.append(f"已删除 {fpath.relative_to(proot)}")
            except OSError as e:
                return {"ok": False, "found": True, "steps": steps,
                        "target_status": None,
                        "error": f"删除验证进度文件失败 {fname}: {e}"}
    if not any(s.startswith("已删除") for s in steps):
        steps.append("无场景/进度文件可删（verify-progress 目录不存在或已清）")

    # 3+4a. 清计数 + 剥冻结 + 清 error（自带 frozen 键走 update_spec 显式豁免，
    # status 保持 blocked 供复位路径判定）
    sm = _adjudication_sm(proot)
    updates = {"frozen": False, "error": None, "frozen_until": None}
    updates.update(_RETRY_COUNTER_RESETS)
    sm.update_spec(spec, updates)
    steps.append("已清零 judge 重跑/验证失败轮等重试计数并解除冻结（保持 blocked）")

    # 4b. 复位路径判定（基于清除后的干净 entry）
    from core.pm_engine.verification.branch_guard import resolve_env_blocked_reset_path

    entry2 = parse_state(proot).get(spec) or {}
    if entry2.get("status") != "blocked":
        steps.append(f"spec 已不在 blocked（当前 {entry2.get('status')}），无需复位转换")
        target = entry2.get("status")
    else:
        path = resolve_env_blocked_reset_path(entry2, proot)
        if path == "testing":
            sm.transition_gate(spec, "testing", channel="manual")
            target = "testing"
            steps.append("实现分支已合并：BLOCKED→TESTING 门禁直通道重验")
        else:
            sm.transition(spec, "ready", channel="manual")
            target = "ready"
            kicked = _kick_step_suffix(proot, spec)
            steps.append("实现分支未合并或缺 branch：BLOCKED→READY 回实现通道" + kicked)
    if note:
        steps.append(f"裁决依据：{note}")
    return {"ok": True, "found": True, "steps": steps, "target_status": target, "error": None}


def force_advance(project_root, spec: str, target_status: str = "done", note: str = "") -> dict:
    """裁决动词：人工裁定接受现状，豁免剩余缺口推进（add-human-adjudication-choices 3.2）。

    前置校验（冻结/blocked）→ 经 ``update_spec`` 显式豁免通道（updates 同时
    携 ``frozen=False`` 与 ``status``，冻结剥离守卫对自带 frozen 键的更新原样
    放行）推进到 target_status 并清 error。``blocked→done`` 不在
    VALID_TRANSITIONS，不走 transition；MUST NOT 直写 STATE.md。留痕以
    channel=manual 的 Transition 日志标注「人工豁免推进」与 note 原文，
    可追溯「人工豁免而非自然达成」。不触碰实现分支内容或主树工作区文件。

    Returns:
        {"ok": bool, "found": bool, "steps": [str], "from_status": str|null,
         "status": str|null, "error": str|null}
    """
    proot = Path(project_root)
    specs = parse_state(proot)
    if spec not in specs:
        return {"ok": False, "found": False, "steps": [], "from_status": None,
                "status": None, "error": f"spec not found: {spec}"}
    entry = specs[spec]
    if not (is_spec_frozen(entry) or entry.get("status") == "blocked"):
        return {
            "ok": False, "found": True, "steps": [], "from_status": None,
            "status": None,
            "error": (f"spec 未处于冻结/blocked 态（当前 {entry.get('status')}），"
                      "人工豁免推进仅对冻结/blocked 开放"),
        }
    if target_status not in _FORCE_ADVANCE_TARGETS:
        return {
            "ok": False, "found": True, "steps": [], "from_status": None,
            "status": None,
            "error": (f"不支持的目标状态 '{target_status}'"
                      f"（允许：{'/'.join(_FORCE_ADVANCE_TARGETS)}）"),
        }
    old_status = entry.get("status")
    sm = _adjudication_sm(proot)
    sm.update_spec(spec, {"frozen": False, "status": target_status, "error": None})
    basis = "人工豁免推进" + (f"：{note}" if note else "")
    sm.logger.info(
        "state_machine",
        f"Transition: {spec} {old_status} → {target_status}",
        {"channel": "manual", "note": basis},
    )
    steps = [
        f"冻结解除 + error 清空（显式豁免通道：{old_status} → {target_status}，"
        "不走 VALID_TRANSITIONS）",
        f"留痕：{basis}",
    ]
    return {"ok": True, "found": True, "steps": steps, "from_status": old_status,
            "status": target_status, "error": None}


def skip_review_gate(project_root, spec: str, note: str = "") -> dict:
    """裁决动词：评审器持续基础设施失败时人工授权跳过评审门（3.3）。

    前置校验仅对 ``spec-review-incomplete``（评审器自身失败）冻结开放；
    评审否决（``spec-review-rejected``，方向不成立）类冻结 MUST 拒绝——
    方向不成立时「跳过评审」语义不成立。执行：显式豁免通道解除冻结并从
    blocked 直推 ready（reviewing→ready 本属合法边），清评审器重试计数，
    写调度唤醒信号；留痕标注「人工授权跳过评审」与 note。

    Returns:
        {"ok": bool, "found": bool, "steps": [str], "status": str|null,
         "error": str|null}
    """
    proot = Path(project_root)
    specs = parse_state(proot)
    if spec not in specs:
        return {"ok": False, "found": False, "steps": [], "status": None,
                "error": f"spec not found: {spec}"}
    entry = specs[spec]
    error_text = str(entry.get("error") or "")
    if not is_spec_frozen(entry):
        return {
            "ok": False, "found": True, "steps": [], "status": None,
            "error": (f"spec 未处于冻结态（当前 {entry.get('status')}），"
                      "跳过评审门仅对评审器失败冻结开放"),
        }
    if "spec-review-rejected" in error_text:
        return {
            "ok": False, "found": True, "steps": [], "status": None,
            "error": ("评审否决（方向不成立）类冻结不支持跳过评审门，"
                      "处置请走 revise_reproposal / force_advance / abandon"),
        }
    if "spec-review-incomplete" not in error_text:
        return {
            "ok": False, "found": True, "steps": [], "status": None,
            "error": "非评审器失败冻结（error 无 spec-review-incomplete 特征），跳过评审门被拒绝",
        }
    sm = _adjudication_sm(proot)
    sm.update_spec(spec, {
        "frozen": False, "status": "ready", "error": None,
        "reviewer_run": None, "_review_attempts": 0,
    })
    basis = "人工授权跳过评审" + (f"：{note}" if note else "")
    sm.logger.info(
        "state_machine",
        f"Transition: {spec} blocked → ready",
        {"channel": "manual", "note": basis},
    )
    kicked = _kick_step_suffix(proot, spec)
    steps = [
        "冻结解除 + 评审器重试计数清零（reviewer_run/_review_attempts）",
        "blocked → ready 直推（跳过评审门），进入正常实现调度" + kicked,
        f"留痕：{basis}",
    ]
    return {"ok": True, "found": True, "steps": steps, "status": "ready", "error": None}


# ── choice_id → 动作映射执行器（alert-resolve 端点与 Administrator 消费共用）──

def _exec_review_unfreeze(project_root, spec: str, note: str, marker: str, label: str) -> dict:
    """评审族共用解冻回 reviewing：revise_reproposal / retry_review 的公共体。"""
    proot = Path(project_root)
    specs = parse_state(proot)
    if spec not in specs:
        return {"ok": False, "steps": [], "error": f"spec not found: {spec}"}
    entry = specs[spec]
    # 状态前置（code-review item 3628279ba8e6）：与 reset_verification /
    # force_advance / _exec_continue_auto_fix（frozen/blocked）和
    # skip_review_gate（frozen）同门——非冻结/blocked 态一律拒绝，防只改了
    # status、error 残留评审族标记的在途 spec 被陈旧/重放裁决拽回 reviewing
    # 并清零其评审计数、丢弃当前在途状态
    if not (is_spec_frozen(entry) or entry.get("status") == "blocked"):
        return {"ok": False, "steps": [],
                "error": (f"spec 未处于冻结/blocked 态（当前 {entry.get('status')}），"
                          f"{label}被拒绝")}
    if marker not in str(entry.get("error") or ""):
        return {"ok": False, "steps": [],
                "error": f"该冻结非 {marker} 类，{label}被拒绝"}
    sm = _adjudication_sm(proot)
    sm.update_spec(spec, {
        "frozen": False, "status": "reviewing", "error": None,
        "reviewer_run": None, "_review_attempts": 0,
    })
    sm.logger.info(
        "state_machine",
        f"Transition: {spec} blocked → reviewing",
        {"channel": "manual", "note": f"{label}（人工裁决）"},
    )
    kicked = _kick_step_suffix(proot, spec)
    steps = [
        f"冻结解除 + 评审计数清零，回 reviewing {label}" + kicked,
    ]
    if note:
        steps.append(f"裁决依据：{note}")
    return {"ok": True, "steps": steps, "status": "reviewing", "error": None}


def _exec_abandon(project_root, spec: str, note: str = "") -> dict:
    """abandon：软删除归档（撤销并丢弃该 spec 的工作，留处置痕）。"""
    from .spec_archive import soft_delete_spec

    r = soft_delete_spec(project_root, spec)
    if r.get("found") and not r.get("running") and not r.get("error"):
        steps = ["STATE.md 条目已移除"
                 + (f"，spec 目录归档至 {r.get('archive_path')}" if r.get("archived")
                    else "（spec 目录不存在，仅清状态）")]
        if note:
            steps.append(f"裁决依据：{note}")
        return {"ok": True, "steps": steps, "archived": r.get("archived"),
                "archive_path": r.get("archive_path"), "error": None}
    if r.get("running"):
        return {"ok": False, "steps": [],
                "error": (f"spec 仍有在跑 agent（pending: {r.get('pending')}），"
                          "撤销丢弃被拒绝；请先停止在跑 agent")}
    return {"ok": False, "steps": [],
            "error": r.get("error") or (None if r.get("found") else f"spec not found: {spec}")
            or "软删除失败"}


def _exec_continue_auto_fix(project_root, spec: str, note: str = "") -> dict:
    """continue_auto_fix：解冻 + 清全部重试计数（含实现预算）→ ready 继续自动修复。

    对各验证链信号按注册表语义是「重置对应预算/轮次」，此处统一清全部
    重试计数器——超集无害（均为可重试预算类字段），避免 per-signal 分支漂移。
    """
    proot = Path(project_root)
    specs = parse_state(proot)
    if spec not in specs:
        return {"ok": False, "steps": [], "error": f"spec not found: {spec}"}
    entry = specs[spec]
    if not (is_spec_frozen(entry) or entry.get("status") == "blocked"):
        return {"ok": False, "steps": [],
                "error": (f"spec 未处于冻结/blocked 态（当前 {entry.get('status')}），"
                          "继续自动修复被拒绝")}
    sm = _adjudication_sm(proot)
    updates = {"frozen": False, "error": None, "frozen_until": None}
    updates.update(_RETRY_COUNTER_RESETS)
    updates["_impl_run_budget_used"] = 0
    sm.update_spec(spec, updates)
    sm.transition(spec, "ready", channel="manual")
    kicked = _kick_step_suffix(proot, spec)
    steps = [
        "解冻并清零实现预算与验证链重试计数（重新获得完整自动修复预算）",
        "BLOCKED→READY 回实现通道" + kicked,
    ]
    if note:
        steps.append(f"裁决依据：{note}")
    return {"ok": True, "steps": steps, "status": "ready", "error": None}


def _exec_raise_budget(project_root, spec: str) -> dict:
    """raise_budget：agents.token_budget_millions 翻倍 + 复位告警幂等标记。"""
    from .config_admin import read_config, write_config

    proot = Path(project_root)
    current_val = 50.0
    try:
        agents_cfg = (read_config(proot) or {}).get("agents") or {}
        raw = agents_cfg.get("token_budget_millions")
        if raw is not None:
            current_val = float(raw)
    except (TypeError, ValueError):
        pass
    if current_val <= 0:
        # 0=关闭语义无法翻倍，回缺省基线翻倍（与 _check_token_budget 缺省一致）
        current_val = 50.0
    new_val = current_val * 2
    new_val_i = int(new_val) if float(new_val).is_integer() else new_val
    r = write_config(proot, {"agents": {"token_budget_millions": new_val_i}}, scope="project")
    if not r.get("ok"):
        return {"ok": False, "steps": [], "error": f"写入预算配置失败: {r.get('error')}"}
    steps = [f"agents.token_budget_millions {current_val:g}M → {new_val:g}M"
             "（写入 .fenix/config.yaml）"]
    # 幂等标记复位失败不再静默成功（code-review item 7e377b667b7b）：update_spec
    # False（spec 不在 STATE.md/写入被拒）或异常曾被 `except: pass` 吞掉且仍追加
    # 成功步骤——token_budget.py 的幂等门（`ratio >= 1.0 and not alert_flag`）会让
    # 下次预算耗尽不再告警，裁决看似闭环、spec 实则静音。预算翻倍此时已生效且
    # 不可安全回退（回退会让重试再翻倍），故保持 ok:True，但 WARNING 留痕 +
    # 步骤警告如实透出，提示人工核查。
    try:
        sm = _adjudication_sm(proot)
        if sm.update_spec(spec, {"_token_warn_80": False, "_token_alert_100": False}):
            steps.append("已复位 _token_warn_80/_token_alert_100 告警幂等标记")
        else:
            logger.warning(
                "raise_budget 告警幂等标记复位失败 spec=%s（update_spec False）", spec
            )
            steps.append("警告：告警幂等标记复位失败（spec 未找到或写入被拒），"
                         "预算 80%/100% 告警可能保持静默，请人工核查")
    except Exception as e:
        logger.warning("raise_budget 告警幂等标记复位异常 spec=%s: %s", spec, e)
        steps.append("警告：告警幂等标记复位异常，预算 80%/100% 告警可能保持静默，"
                     "请人工核查")
    return {"ok": True, "steps": steps, "error": None}


def _exec_declare_no_artifacts(project_root, spec: str, note: str = "") -> dict:
    """declare_no_artifacts：原子写 worktree.has_build_artifacts=false 结案。"""
    import yaml as _yaml

    proot = Path(project_root)
    config_path = proot / ".fenix" / "config.yaml"
    raw = {}
    if config_path.is_file():
        try:
            loaded = _yaml.safe_load(config_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                raw = loaded
        except (_yaml.YAMLError, OSError) as e:
            return {"ok": False, "steps": [], "error": f"读取现有配置失败: {e}"}
    wt = raw.get("worktree")
    if not isinstance(wt, dict):
        wt = {}
    wt["has_build_artifacts"] = False
    raw["worktree"] = wt
    config_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = config_path.with_suffix(config_path.suffix + ".tmp")
    try:
        tmp_path.write_text(
            _yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        os.replace(tmp_path, config_path)
    except OSError as e:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        return {"ok": False, "steps": [], "error": f"写配置失败: {e}"}
    steps = ["worktree.has_build_artifacts=false 已写入 .fenix/config.yaml"
             "（原子写，声明本项目无构建产物，结案）"]
    if note:
        steps.append(f"裁决依据：{note}")
    return {"ok": True, "steps": steps, "error": None}


def execute_adjudication_choice(project_root, spec: str, choice_id: str,
                                note: str = "", signal_type: str = "") -> dict:
    """choice_id → 后端动作统一映射执行器（add-human-adjudication-choices 4.1/4.2）。

    alert-resolve 端点与 Administrator 处置记录消费共用本执行器：同一动作
    映射、同一留痕格式，自动处置与人工下拉处置收敛为同一裁决空间（D1）。
    action 判定：signal_type 注册表内精确匹配优先；缺 signal_type 上下文时
    按 choice_id 全表反查（同一 id 在各信号下 action 语义一致）。

    本函数只执行动作，不做告警 handled 标记与 disposition 留痕——由调用方
    （端点 / admin 消费路径）按各自通道收口。

    Returns:
        {"ok": bool, "choice_id": str, "action": str, "steps": [str],
         "error": str|null, ...动作附加字段}
    """
    from .adjudication_choices import ADJUDICATION_CHOICES

    if not choice_id or not str(choice_id).strip():
        return {"ok": False, "choice_id": choice_id or "", "action": None,
                "steps": [], "error": "choice_id is required"}
    choice_id = str(choice_id).strip()
    sig = str(signal_type or "")
    action = None
    for c in ADJUDICATION_CHOICES.get(sig, ()):
        if c.get("id") == choice_id:
            action = c.get("action")
            break
    if action is None and sig in ADJUDICATION_CHOICES:
        # signal_type 已注册：choice 必须落在该信号选项集内（alert-resolve
        # 契约「按 alert 的 signal_type 校验 choice_id 合法」），不做跨信号放行
        return {"ok": False, "choice_id": choice_id, "action": None, "steps": [],
                "error": (f"非法 choice_id '{choice_id}'"
                          f"（不在信号 '{sig}' 的选项集内）")}
    if action is None:
        # signal_type 缺失/未注册（直接调用 / Administrator 自由处置带建议 id）：
        # 按 id 全表反查（同一 id 在各信号下 action 语义一致）
        for sig_choices in ADJUDICATION_CHOICES.values():
            for c in sig_choices:
                if c.get("id") == choice_id:
                    action = c.get("action")
                    break
            if action:
                break
    if action is None:
        return {"ok": False, "choice_id": choice_id, "action": None, "steps": [],
                "error": f"非法 choice_id '{choice_id}'（注册表无此选项）"}

    try:
        if action == "reset_verification":
            r = reset_verification(project_root, spec, note=note, signal_type=signal_type)
        elif action == "force_advance":
            r = force_advance(project_root, spec, target_status="done", note=note)
        elif action == "skip_review_gate":
            r = skip_review_gate(project_root, spec, note=note)
        elif action == "abandon":
            r = _exec_abandon(project_root, spec, note)
        elif action == "continue_auto_fix":
            r = _exec_continue_auto_fix(project_root, spec, note)
        elif action == "revise_reproposal":
            r = _exec_review_unfreeze(project_root, spec, note,
                                      "spec-review-rejected", "修订重评")
        elif action == "retry_review":
            r = _exec_review_unfreeze(project_root, spec, note,
                                      "spec-review-incomplete", "重派评审")
        elif action == "freeze_stop_loss":
            r = freeze_spec(project_root, spec, reason=note or "token 预算止损（人工裁决）")
            if r.get("ok") and not r.get("frozen") and r.get("error"):
                r = {"ok": False, "steps": [], "error": r.get("error")}
        elif action == "raise_budget":
            r = _exec_raise_budget(project_root, spec)
        elif action == "declare_no_artifacts":
            r = _exec_declare_no_artifacts(project_root, spec, note)
        elif action == "ignore":
            r = {"ok": True, "steps": ["知情确认：仅关闭本条告警，不改动 spec 状态"],
                 "error": None}
        elif action == "open_config":
            r = {"ok": True,
                 "steps": ["确认信号：请到 Dashboard 配置表单填写 "
                           "worktree.has_build_artifacts / build_artifact_paths"
                           "（本动作仅确认，不代填配置）"],
                 "error": None}
        else:
            r = {"ok": False, "steps": [],
                 "error": f"注册表 action '{action}' 无执行器映射"}
    except Exception as e:
        return {"ok": False, "choice_id": choice_id, "action": action,
                "steps": [], "error": f"动作执行异常: {e}"}
    if not isinstance(r, dict):
        r = {"ok": False, "steps": [], "error": "执行器返回非结构化结果"}
    r = dict(r)
    r.setdefault("steps", [])
    r["choice_id"] = choice_id
    r["action"] = action
    if not r.get("ok") and not r.get("error"):
        r["error"] = "动作未成功执行"
    return r
