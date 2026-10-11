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
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

# 冻结前缀与「原状态 X」解析单点（add-spec-scheduling-controls D4）
from core.state_machine import (
    FREEZE_ERROR_PREFIX,
    parse_orig_status,
    START_AFTER_MANUAL,
    BUDGET_MANUAL_RESET_BASELINE_FIELD,
    # env 豁免 STATE 字段与纯函数单源（evo-fix-env-exemption-gate-conflict-…
    # 1.1/1.4：豁免写入、签名推导、场景定义 hash 与校验同源共用）
    ENV_EXEMPTIONS_FIELD,
    ENV_EXEMPTION_MAX_ENTRIES,
    SCENARIO_REVISION_COUNT_FIELD,
    SCENARIO_REVISION_MAX_COUNT,
    SCENARIO_REVISION_PENDING_FIELD,
    parse_env_exemptions,
    scenario_definition_hash,
    scenario_fail_signature_body,
    serialize_env_exemptions,
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
# admin_actions 委托它写目录形态的唤醒信号；validate_scheduling_kick_spec
# 复用为 reset_verification 删除路径的 spec 形态白名单（code-review item
# a1e09f8181cd，与 kick 写入路径同防线）。
from core.signals import (  # noqa: F401
    ADMIN_INVOKE_REQUEST,
    SCHEDULING_KICK_DIR,
    request_admin_invoke,
    validate_scheduling_kick_spec,
    write_scheduling_kick,
)

CANCEL_RUN_REQUEST = ".fenix/cancel_run_request.json"

# 裁决动词的失败留痕通道（code-review item 7e377b667b7b）：旧的
# `except Exception: pass` 把调度唤醒信号/幂等标记复位失败静默吞掉——
# 丢 kick 会让 deferred start_after 滞留无迹，丢标记复位会让预算告警被
# token_budget 幂等门永久静默。统一 WARNING 留痕 + 步骤后缀如实回显。
logger = logging.getLogger("fenixd.dashboard.admin_actions")


def _atomic_write_request(req_path: Path, payload: dict, tmp_prefix: str) -> tuple:
    """原子写请求信号文件并回读校验写入归属（code-review item 2e9c8ab94e5d）。

    调用方先 ``req_path.exists()`` 判冲突、再 mkstemp+os.replace 写入，两步
    之间无锁；dashboard HTTP 服务多线程下，并发双请求可同时通过存在性
    检查，后写者 os.replace 静默覆盖先写者且两侧均返回 ok，先写请求丢失
    无迹。本辅助给 payload 附加唯一 ``write_id``（uuid4 hex；created 为
    isoformat 微秒级但同进程双请求理论上仍可能重复，不用作归属判据），
    replace 后立即回读文件比对：write_id ≠ 本次值即被并发后写者覆盖。

    消费方（fenixd ``_consume_request_file`` 及各 ``_check_*``）按宽松
    ``payload.get`` 解析，新增字段无害。单请求路径行为完全不变：回读即
    本次值（或回读失败无法证伪归属时按本次胜出，不因回读抖动引入假冲突）。

    Args:
        req_path: 信号文件目标路径
        payload: 待写入的 JSON payload（原地追加 write_id）
        tmp_prefix: 临时文件前缀（保持各调用点既有命名）

    Returns:
        (won, created) — won=True 本次写入胜出；created 为回读到的文件
        当前 created（胜出时即本次值，败给并发后写者时为对方值，供冲突
        返回对齐既有「读既有 created」语义）。
    """
    req_path.parent.mkdir(parents=True, exist_ok=True)
    payload["write_id"] = uuid.uuid4().hex
    fd, tmp_path = tempfile.mkstemp(dir=str(req_path.parent), prefix=tmp_prefix, suffix=".tmp")
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
    try:
        current = json.loads(req_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        # 回读失败（如信号已被 daemon 瞬时消费 / 瞬时 IO 错误）：无法证伪
        # 归属，按本次写入胜出处理
        return True, payload["created"]
    if not (isinstance(current, dict) and current.get("write_id") == payload["write_id"]):
        return False, current.get("created") if isinstance(current, dict) else None
    return True, payload["created"]


def _request_signal_with_guards(
    proot: Path,
    req_path: Path,
    payload: dict,
    tmp_prefix: str,
    extra_fields: dict,
    unmanaged_error: str,
    conflict_error: str,
) -> dict:
    """request_* 信号函数共用的托管态校验 + 冲突检查 + 原子写 + 返回形状。

    抽取 request_run_cancel / request_spec_delete / request_spec_approve_push
    三处逐字重复段（code-review item 75cb80eb1783）：_hosting_state
    try/except → unmanaged/daemon_down 两组拒绝形状 → ``req_path.exists()``
    冲突检查（读既有 created）→ _atomic_write_request → won=False 冲突返回
    → 成功返回。三函数差异只剩文案（unmanaged_error/conflict_error）与差异
    字段（extra_fields：run_cancel 的 missing_run_id、approve_push 的
    found+terminal，spec_delete 无），新增字段或调整形状只改本处
    （历史上 2e9c8ab94e5d 即需三处各修一遍的教训）。
    """
    # 消费方判据：信号唯一消费方是 daemon 主循环，unmanaged（进程在跑但无
    # supervisor）或 stopped 时信号无人消费——静默滞留既让用户误以为请求
    # 已受理，又让后续请求持续 409，前置拦截不写信号。
    # _hosting_state 已在模块顶层导入（测试可 patch 该绑定）
    try:
        state = _hosting_state(proot)
    except Exception:
        state = "stopped"
    if state == "unmanaged":
        return {**extra_fields, "ok": False, "conflict": False,
                "unmanaged": True, "daemon_down": False,
                "file": None, "created": None, "error": unmanaged_error}
    if state != "managed":
        return {**extra_fields, "ok": False, "conflict": False,
                "unmanaged": False, "daemon_down": True,
                "file": None, "created": None,
                "error": "daemon 未运行，请先启动 daemon"}

    # 已有未消费请求 → 冲突（409），读既有 created 供返回
    if req_path.exists():
        try:
            existing = json.loads(req_path.read_text(encoding="utf-8"))
            existing_created = (
                existing.get("created") if isinstance(existing, dict) else None
            )
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            existing_created = None
        return {**extra_fields, "ok": False, "conflict": True,
                "unmanaged": False, "daemon_down": False,
                "file": str(req_path), "created": existing_created,
                "error": conflict_error}

    won, current_created = _atomic_write_request(
        req_path, payload, tmp_prefix=tmp_prefix
    )
    if not won:
        # 并发后写者覆盖了本次信号（TOCTOU 回读校验，item 2e9c8ab94e5d）：
        # 先写请求将丢失无迹，按既有冲突语义返回
        return {**extra_fields, "ok": False, "conflict": True,
                "unmanaged": False, "daemon_down": False,
                "file": str(req_path), "created": current_created,
                "error": conflict_error}
    return {**extra_fields, "ok": True, "conflict": False,
            "unmanaged": False, "daemon_down": False,
            "file": str(req_path), "created": payload["created"],
            "error": None}


def request_run_cancel(project_root, run_id: str, reason: str = "") -> dict:
    """写入 run 取消的文件信号（.fenix/cancel_run_request.json）。

    原子写（tmp+rename），与 request_admin_invoke 同构：
    - daemon 未受 supervisor 托管（hosting_state != "managed"）→ 信号无人
      消费会静默滞留并锁死后续取消请求，前置拦截（对齐
      request_spec_delete / request_spec_approve_push 契约）；
    - 已存在未消费的请求文件 → 返回冲突（409），不覆盖；
    - run_id 为空 → 返回 {ok: False, missing_run_id: True}；
    - 成功写入 → 返回 {ok: True, created}。

    文件信号模式（D5）：daemon 主循环下一轮（≤2s）扫描拾取并调用
    agent_runner.cancel_run。server 进程不直接调用 cancel_run。

    Returns:
        {"ok": bool, "conflict": bool, "missing_run_id": bool,
         "unmanaged": bool, "daemon_down": bool,
         "file": str|null, "created": str|null, "error": str|null}
    """
    if not run_id or not run_id.strip():
        return {
            "ok": False,
            "conflict": False,
            "missing_run_id": True,
            "unmanaged": False,
            "daemon_down": False,
            "file": None,
            "created": None,
            "error": "run_id is required",
        }

    proot = Path(project_root)
    created = datetime.now(timezone.utc).isoformat()
    payload = {
        "run_id": run_id.strip(),
        "reason": reason or "",
        "source": "dashboard",
        "created": created,
    }
    # 托管态校验 + 冲突检查 + 原子写 + 返回形状统一走
    # _request_signal_with_guards（与 request_spec_delete /
    # request_spec_approve_push 同一实现点，差异仅文案与差异字段）
    return _request_signal_with_guards(
        proot,
        proot / CANCEL_RUN_REQUEST,
        payload,
        tmp_prefix=".cancel_run_request.",
        extra_fields={"missing_run_id": False},
        unmanaged_error=(
            "本项目 daemon 未受 supervisor 托管，取消信号不会被消费。"
            "经 Dashboard 项目页「安装托管」或 /fenix-setup 恢复"
            "supervisor 托管后重试"
        ),
        conflict_error="已有进行中的取消请求",
    )


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
                        # type 非 str（合法 JSON 的数组/对象值，手工编辑/
                        # 异常写入）不可哈希，视为无终态行，保持保守
                        # 「在跑」语义——否则 frozenset 成员测试抛 TypeError
                        # 穿透调用链致 500
                        if (
                            isinstance(entry, dict)
                            and isinstance(entry.get("type"), str)
                            and entry.get("type")
                        ):
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
    created = datetime.now(timezone.utc).isoformat()
    payload = {
        "spec": spec,
        "source": "dashboard",
        "created": created,
        "stopping": int(stopping or 0),
    }
    # 托管态校验 + 冲突检查 + 原子写 + 返回形状统一走
    # _request_signal_with_guards（同 request_run_cancel /
    # request_spec_approve_push 实现点）
    return _request_signal_with_guards(
        proot,
        proot / SPEC_DELETE_REQUEST,
        payload,
        tmp_prefix=".spec_delete_request.",
        extra_fields={},
        unmanaged_error=(
            "本项目 daemon 未受 supervisor 托管，删除信号不会被消费。"
            "经 Dashboard 项目页「安装托管」或 /fenix-setup 恢复"
            "supervisor 托管后重试"
        ),
        conflict_error="已有进行中的删除请求",
    )


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

    sm = _sm(project_root)
    if not sm.freeze_spec(spec_name, reason=note):
        # 与 reset_verification 同口径（写入必留痕）：spec 在前置校验后被并发
        # 软删除/写入被拒时冻结未落盘，WARNING 留痕并如实返回失败形状。
        logger.warning(
            "freeze_spec 冻结失败：spec 已并发删除或写入被拒，冻结未落盘（spec=%s）",
            spec_name,
        )
        return {"ok": False, "found": True, "frozen": False,
                "error": "spec 已并发删除或写入被拒，裁决未落盘"}
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
    sm = _sm(project_root)
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
    if not sm.unfreeze_spec(spec_name, status=orig,
                            project_root=Path(project_root),
                            worktree_manager=_wt_mgr):
        # 与 reset_verification 同口径（写入必留痕）：spec 在前置校验后被并发
        # 软删除/写入被拒时解冻未落盘，WARNING 留痕并如实返回失败形状。
        logger.warning(
            "unfreeze_spec 解冻失败：spec 已并发删除或写入被拒，解冻未落盘（spec=%s）",
            spec_name,
        )
        return {"ok": False, "found": True, "frozen": True,
                "error": "spec 已并发删除或写入被拒，裁决未落盘"}
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
    from core.pm_engine.verification import reclassify_infra_rounds as _recl

    specs = parse_state(project_root)
    if spec_name not in specs:
        return {"ok": False, "found": False, "error": f"spec not found: {spec_name}"}
    if not str(audit_reason or "").strip():
        return {"ok": False, "found": True, "error": "audit_reason 必填（审计留痕要求）"}
    sm = _sm(project_root)
    if isinstance(n, (bool, float)):
        # 布尔是 int 子类、浮点会被 int() 静默截断，均须显式排除（与
        # set_spec_budget 的 isinstance(budget, bool) 拒绝同口径）：否则 JSON body
        # 传 n=true 会被静默当 1 轮回拨，n=1.5 也会被静默截断为 1 执行（实际生效
        # 轮次与用户请求不一致且无任何提示）。
        return {"ok": False, "found": True, "error": "invalid n（回拨轮次参数无效）"}
    try:
        n_val = int(n)
    except (TypeError, ValueError) as e:
        # 不外泄裸异常文本（code-review item e584a2ede367）：客户端收固定
        # 文案，异常细节经服务端日志留痕（对齐 run_routes/spec_routes 脱敏）
        logger.warning(
            "reclassify_infra_rounds invalid n（n=%r）: %s: %s",
            n, type(e).__name__, e,
        )
        return {"ok": False, "found": True, "error": "invalid n（回拨轮次参数无效）"}
    try:
        result = _recl(
            project_root,
            sm,
            None,
            spec_name,
            n_val,
            str(audit_reason),
            actor=actor,
        )
    except (TypeError, ValueError) as e:
        # 同上（code-review item e584a2ede367）：固定文案 + 服务端日志留痕
        logger.warning(
            "reclassify_infra_rounds 内部失败（非 n 参数问题，spec=%s）: %s: %s",
            spec_name, type(e).__name__, e,
        )
        return {
            "ok": False,
            "found": True,
            "error": "reclassify_infra_rounds 内部失败（非 n 参数问题）",
        }
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
    - 转移被拒（promote_drafted 后 spec 被并发改写/软删除/转移非法）→
      {ok: False, found: True, error: ...}（spec 实际停留 drafted）
    - 成功 → {ok: True, found: True, violations: []}
    """
    specs = parse_state(project_root)
    if spec_name not in specs:
        return {"ok": False, "found": False, "error": f"spec not found: {spec_name}"}
    from core.pm_engine.promotion import promote_drafted
    from core.logger import Logger
    from core.config import ConfigLoader

    proot = Path(project_root)
    sm = _sm(proot)
    # audit_logger 专名与模块级 std logging logger 区分（code-review item
    # 4e77fe1344f6）：同名遮蔽会让后续 logger.warning(...) 误用 Logger 实例
    audit_logger = Logger(proot)
    # 解析项目有效配置传给 promote_drafted，使评审分流判定与 daemon 同源
    # （add-spec-review-gate 3.4/3.5：不传 config 无法评估跳过白名单，恒直通 ready）
    config = ConfigLoader.resolve_config(proot)
    result = promote_drafted(proot, spec_name, state_machine=sm, logger=audit_logger, config=config)
    if result["ok"]:
        # 依分流结论转移：命中跳过白名单 → ready；否则 → reviewing 待方案评审。
        # 与 _on_spec_drafted 收尾语义一致，MUST NOT 硬编码 ready（全通道覆盖）。
        next_status = result.get("next_status", "ready")
        # fix-observability-gaps 2.2：dashboard 人工晋升来源（channel=manual）
        # 转移结果如实回报（与 reset_verification 同口径）：promote_drafted 与
        # transition 之间存在并发窗口（STATE 被并发改写/软删除/转移非法），
        # 转移未落盘时 spec 实际停留在 drafted，不得向调用方宣称晋升成功。
        if not sm.transition(
            spec_name, next_status,
            trigger_run_id=None, agent_type=None, channel="manual",
        ):
            logger.warning(
                "promote_spec 转移未生效：→%s 转换被拒或未落盘，"
                "spec 仍滞留 drafted（spec=%s）",
                next_status, spec_name,
            )
            return {"ok": False, "found": True, "violations": [],
                    "next_status": next_status,
                    "error": (f"转移未生效：→{next_status} 转换被拒或未落盘，"
                              "spec 仍滞留 drafted")}
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
    from core.logger import Logger

    proot = Path(project_root)
    sm = _sm(proot)
    audit_logger = Logger(proot)
    result = _reflow(proot, spec_name, state_machine=sm, logger=audit_logger, source="api")
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
    from core.logger import Logger

    proot = Path(project_root)
    sm = _sm(proot)
    audit_logger = Logger(proot)
    # agent_runner=None：跳过同步派发，由 daemon 全扫 recovery 的 reviewing
    # 分支拾取派发（与 CLI cmd_review 同构）；Dashboard 侧请求发往常驻 daemon
    # 管理的进程，状态先落盘、派发由既有调度链接力。
    review_manager = SpecReviewManager(proot, sm, None, None, {}, audit_logger)
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
    - 写入失败（前置校验后 spec 被并发软删除/写入被拒）→
      ``{ok: False, found: True, reason/error: ...}``（WARNING 留痕，STATE 零变更）
    """
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
            "reason": "该 SPEC 并非待激活态（start_after 非 manual）",
        }
    # 命中 → 清 start_after + 唤醒信号；写入结果如实回报（D3），
    # CLI 与 Dashboard 依 ok 分支文案，不再无条件宣称「立即恢复调度」
    sm = _sm(proot)
    if not sm.update_spec(spec, {"start_after": None}):
        # 与 reset_verification 同口径（写入必留痕）：spec 在前置校验后被并发
        # 软删除/写入被拒时变更未落盘，WARNING 留痕并如实返回失败形状，不再
        # 无条件宣称「已激活」（路由/CLI 均按 ok 分流，reason 供拒绝文案位复用）。
        logger.warning(
            "activate_spec 激活失败：spec 已并发删除或写入被拒，变更未落盘（spec=%s）",
            spec,
        )
        return {"ok": False, "found": True,
                "reason": "spec 已并发删除或写入被拒，激活未落盘",
                "error": "spec 已并发删除或写入被拒，激活未落盘"}
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
    - 命中但写入失败（前置校验后 spec 被并发软删除/写入被拒）→
      ``{ok: False, found: True, error}``（WARNING 留痕，不写 kick）
    """
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
    sm = _sm(proot)
    resolved_branch, _wt = sm._resolve_preserved_branch(
        spec, entry, proot, wm, context="Cancel-hold resume")
    if resolved_branch is not None:
        # 命中 → 保留分支续做（收口字段集与 state_machine _recovery_preserve_spec
        # 续做先例同集：tester_run 清空防误读为在飞验证锚点，_merge_*/重派
        # 计数归零防陈旧计数触发误熔断/误告警）。
        updates = {
            "status": "ready",
            "error": f"Recovered from cancelled hold (resume preserved branch)：原状态 {status}",
            "_recovery_resume": True,
            "tester_run": None,
            "_retry_count": 0,
            "_merge_fp": None,
            "_merge_streak": 0,
            "_redispatch_same_cause_streak": 0,
            "_redispatch_cause_fp": None,
        }
        # 锚点不进 updates（fenix-fix dbc51407f377，与 unfreeze_spec 的
        # f5a17d596717 同一口径）：上方 parse_state 快照与落盘之间隔着
        # _resolve_preserved_branch 的 git 子进程（窗口可达秒级），期间并发
        # 写者若已改写/清空锚点，锁外旧值会在本写中复活，派发侧据此误判
        # 在飞实现锚点。branch 载荷是 git 解析值（快照 branch 缺失时来自
        # 命名空间枚举），不能改写成锁内最新值，故收进 _mutate_locked 的
        # 锁内回调：以最新条目复核快照锚点未变才并入（unfreeze_spec 同款
        # 展开：单条目写语义复用 _apply_updates_entry，无第二份实现），
        # git 子进程保持在锁外。
        resume_anchors = {
            "branch": resolved_branch,
            "implementer_run": entry.get("implementer_run"),
        }
        applied: dict = {}
        anchor_recheck: dict = {}

        def _mutate(specs):
            fresh = specs.get(spec) or {}
            if (
                fresh.get("branch") == entry.get("branch")
                and fresh.get("implementer_run") == entry.get("implementer_run")
            ):
                updates.update(resume_anchors)
            else:
                anchor_recheck["snapshot"] = entry
                anchor_recheck["fresh"] = fresh
            found = sm._apply_updates_entry(specs, spec, updates, applied)
            return found, found

        if not sm._mutate_locked(_mutate):
            # 写入必留痕 + 如实返回失败形状（对齐本函数降级分支与
            # activate_spec/reset_verification 同口径）：spec 在前置校验后
            # 被并发软删除/写入被拒时恢复未落盘，不再沿用旧 update_spec 盲写
            # 契约宣称成功——不写 kick、不置 degraded。
            sm.logger.warning("state_machine", f"SPEC not found: {spec}")
            logger.warning(
                "resume_cancelled_spec 恢复失败：spec 已并发删除或写入被拒，"
                "恢复未落盘（spec=%s）",
                spec,
            )
            return {
                "ok": False,
                "found": True,
                "error": "spec 已并发删除或写入被拒，恢复未落盘",
            }
        sm._log_update_applied(spec, applied)
        if anchor_recheck:
            _snap = anchor_recheck["snapshot"]
            _fresh = anchor_recheck["fresh"]
            sm.logger.warning(
                "state_machine",
                f"Cancel-hold anchor recheck: spec '{spec}' 的 branch/"
                f"implementer_run 锚点在续做判定后被并发改写（快照 branch="
                f"{_snap.get('branch')!r}/implementer_run="
                f"{_snap.get('implementer_run')!r} → 最新 branch="
                f"{_fresh.get('branch')!r}/implementer_run="
                f"{_fresh.get('implementer_run')!r}）——放弃锚点回写，"
                f"防陈旧锚点复活",
            )
        result = {"ok": True, "found": True, "spec": spec, "degraded": False}
    else:
        # 降级：共享判定已实际运行且给出「不可保留」结论 → 普通全新重派。
        # _resolve_preserved_branch 各失败层内已有 WARNING 留痕；此处写降级集
        # （不置 _recovery_resume），携带 status 即自动清保持标记。
        if not sm.update_spec(spec, {
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
        }):
            # 与 activate_spec 同口径（写入必留痕）：parse_state 快照与落盘之间
            # spec 被并发软删除/写入被拒时恢复未落盘，WARNING 留痕并如实返回
            # 失败形状（对齐命中分支，不再宣称 degraded 成功）。
            logger.warning(
                "resume_cancelled_spec 恢复失败：spec 已并发删除或写入被拒，"
                "恢复未落盘（spec=%s）",
                spec,
            )
            return {
                "ok": False,
                "found": True,
                "error": "spec 已并发删除或写入被拒，恢复未落盘",
            }
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
    - 写入失败（前置校验后 spec 被并发软删除/写入被拒）→
      {ok: False, found: True, error: ...}（WARNING 留痕，STATE 零变更）
    写入经 StateMachine.update_spec（flock + 原子 rename，与 daemon 并发写安全）。
    """
    from core.state_machine import parse_utc

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
    sm = _sm(proot)
    if not sm.update_spec(spec, {"start_after": normalized}):
        # 与 reset_verification 同口径（写入必留痕）：spec 在前置校验后被并发
        # 软删除/写入被拒时变更未落盘，WARNING 留痕并如实返回失败形状，不再
        # 无条件宣称「已设置」（路由侧按 ok 分流 409）。
        logger.warning(
            "set_spec_start_after 写入失败：spec 已并发删除或写入被拒，"
            "变更未落盘（spec=%s）",
            spec,
        )
        return {"ok": False, "found": True,
                "error": "spec 已并发删除或写入被拒，变更未落盘"}
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
    - 写入失败（前置校验后 spec 被并发软删除/写入被拒）→
      {ok: False, found: True, error: ...}（WARNING 留痕，STATE 零变更）
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
        sm = _sm(proot)
        if not sm.update_spec(spec, {"impl_run_budget_override": None}):
            # 与 reset_verification 同口径（写入必留痕）：spec 在前置校验后被
            # 并发软删除/写入被拒时清除未落盘，WARNING 留痕并如实返回失败形状
            # （路由侧按 ok 分流 409）。
            logger.warning(
                "set_spec_budget 清除失败：spec 已并发删除或写入被拒，"
                "变更未落盘（spec=%s）",
                spec,
            )
            return {"ok": False, "found": True, "budget": None,
                    "error": "spec 已并发删除或写入被拒，变更未落盘"}
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
    sm = _sm(proot)
    if not sm.update_spec(spec, {"impl_run_budget_override": budget}):
        # 与 reset_verification 同口径（写入必留痕）：spec 在前置校验后被并发
        # 软删除/写入被拒时写入未落盘，WARNING 留痕并如实返回失败形状
        # （路由侧按 ok 分流 409）。
        logger.warning(
            "set_spec_budget 写入失败：spec 已并发删除或写入被拒，变更未落盘（spec=%s）",
            spec,
        )
        return {"ok": False, "found": True, "budget": None,
                "error": "spec 已并发删除或写入被拒，变更未落盘"}
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
    - 写入失败（前置校验后 spec 被并发软删除/写入被拒）→
      {ok: False, found: True, error: ...}（WARNING 留痕，STATE 零变更）。

    写入经 StateMachine（flock + 原子 rename）：frozen_until 更新不带 status
    键，不触发冻结保护剥离；带 status 的解冻一律走 unfreeze_spec 官方通道。
    """
    from core.state_machine import parse_utc

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
    sm = _sm(proot)
    if mode == "unfreeze":
        orig = parse_orig_status(entry.get("error"))
        # 与 unfreeze_spec 同口径（写入必留痕）：spec 在前置校验后被并发软删除/
        # 写入被拒时解冻未落盘，WARNING 留痕并如实返回失败形状（路由按 ok 分流）。
        if not sm.unfreeze_spec(spec, status=orig):
            logger.warning(
                "configure_spec_freeze 解冻失败：spec 已并发删除或写入被拒，"
                "解冻未落盘（spec=%s）",
                spec,
            )
            return {"ok": False, "found": True,
                    "error": "spec 已并发删除或写入被拒，裁决未落盘"}
        return {
            "ok": True,
            "found": True,
            "mode": "unfreeze",
            "unfrozen": True,
            "frozen_until": None,
        }
    if mode == "permanent":
        # 同上（写入必留痕）：写入被拒时如实返回失败形状。
        if not sm.update_spec(spec, {"frozen_until": None}):
            logger.warning(
                "configure_spec_freeze 写入失败：spec 已并发删除或写入被拒，"
                "变更未落盘（spec=%s）",
                spec,
            )
            return {"ok": False, "found": True,
                    "error": "spec 已并发删除或写入被拒，变更未落盘"}
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
            # 与 unfreeze_spec 同口径（写入必留痕）：并发软删除/写入被拒时
            # 解冻未落盘，WARNING 留痕并如实返回失败形状（路由按 ok 分流）。
            if not sm.unfreeze_spec(spec, status=orig):
                logger.warning(
                    "configure_spec_freeze 解冻失败：spec 已并发删除或写入被拒，"
                    "解冻未落盘（spec=%s）",
                    spec,
                )
                return {"ok": False, "found": True,
                        "error": "spec 已并发删除或写入被拒，裁决未落盘"}
            return {
                "ok": True,
                "found": True,
                "mode": "scheduled",
                "unfrozen": True,
                "frozen_until": normalized,
            }
        if not sm.update_spec(spec, {"frozen_until": normalized}):
            # 同上（写入必留痕）：写入被拒时如实返回失败形状。
            logger.warning(
                "configure_spec_freeze 写入失败：spec 已并发删除或写入被拒，"
                "变更未落盘（spec=%s）",
                spec,
            )
            return {"ok": False, "found": True,
                    "error": "spec 已并发删除或写入被拒，变更未落盘"}
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
    # stopped 维持既有 daemon_down 文案、managed 放行。托管态校验 + 冲突
    # 检查 + 原子写 + 返回形状统一走 _request_signal_with_guards（同
    # request_run_cancel / request_spec_delete 实现点）；found/terminal 已
    # 定值随 extra_fields 透传。
    created = datetime.now(timezone.utc).isoformat()
    payload = {"spec": spec, "source": "dashboard", "created": created}
    return _request_signal_with_guards(
        proot,
        proot / APPROVE_PUSH_REQUEST,
        payload,
        tmp_prefix=".approve_push_request.",
        extra_fields={"found": True, "terminal": False},
        unmanaged_error=(
            "本项目 daemon 未受 supervisor 托管，审批推送信号"
            "不会被消费。经 Dashboard 项目页「安装托管」或 "
            "/fenix-setup 恢复 supervisor 托管后重试"
        ),
        conflict_error="已有进行中的审批推送请求",
    )


def clear_spec_error(project_root, spec: str) -> dict:
    """清除 SPEC 的 error 字段（置空并原子写回 STATE.md）。

    校验 spec 须存在于项目 STATE.md（不存在返回 {found: False}），再实例化
    StateMachine 调用 update_spec(spec, {"error": None})——复用其 flock + 原子
    rename 写回，与 daemon 并发写安全。不影响 status/priority 等其它字段；
    error 已为 null 时仍为成功（幂等）。

    冻结态守卫（code-review item babdab6b010b）：is_spec_frozen 对存量 spec
    保留「status=blocked 且 error 以冻结前缀开头」的文本回退判据，对这类
    spec 无条件清 error 会把冻结原因一并抹掉——冻结状态静默消失并被正常
    调度捞起。故冻结态一律拒绝（不抛异常），解冻须走 unfreeze_spec 官方
    通道（对齐 configure_spec_freeze「冻结管理仅对冻结 spec 生效」的反向
    守卫与 {ok: False, error: 原因} 拒绝形状）。

    豁免标记守卫（code-review item 582624e4c92a）：admin_monitor 的
    blocked_stuck 豁免除 frozen 字段与「用户指令冻结：」前缀外，还认 error
    前缀 ``frozen:`` 与「用户指令」子串两种存量文本标记（人工冻结/暂停的
    历史文案，词形漂移不一）。blocked 态清空 error 会连带抹掉这些标记、
    使豁免失效——有意等待态 spec 满冷却阈值即被反复误报唤起 admin（真实
    事故：清除错误整段抹掉 error 连带冻结标记 → 15 分钟循环误报；清除
    error ≠ 要求重派）。故 blocked 态 error 携带任一豁免标记时同样拒绝；
    判据须与 admin_monitor._detect_blocked_stuck 保持同步，勿单侧增删。

    退避标记摘取（code-review item bbba88d8e6af）：done 态 spec 的 error
    携带 push 退避/重试计数的机器可读标记（``[push_backoff next_retry_at=…]``
    与 ``[push_attempts=N]``）。整段清空会把退避期与连续重试计数一并归零
    （engine 自动 push 从零重新起算）。故清空前先摘取这两个标记回写专用
    字段（``_push_backoff_next_retry_at`` / ``_push_attempts``，读侧字段
    优先的过渡期承接）；error 无标记时不写键，不影响普通错误清除。

    Args:
        project_root: 项目根目录
        spec: SPEC 名称（须 kebab-case，且已在 STATE.md 注册）

    Returns:
        {"ok": True, "found": True}  — 已清除（含本就为空）
        {"found": False}             — spec 不存在
        {"ok": False, "found": True, "frozen": True, "error": 原因}
                                     — 冻结态/豁免标记拒绝
        {"ok": False, "found": True, "error": 原因}
                                     — 写入失败（前置校验后并发软删除/写入被拒，
                                       WARNING 留痕，STATE 零变更）
    """
    proot = Path(project_root)
    specs = parse_state(proot)
    if spec not in specs:
        return {"found": False}
    if is_spec_frozen(specs[spec]):
        return {
            "ok": False,
            "found": True,
            "frozen": True,
            "error": "SPEC 处于冻结态，清除错误会连带解除冻结；请先经解冻（unfreeze）官方通道恢复",
        }
    entry = specs[spec]
    err_text = str(entry.get("error") or "")
    if entry.get("status") == "blocked" and (
        err_text.startswith("frozen:") or "用户指令" in err_text
    ):
        return {
            "ok": False,
            "found": True,
            "frozen": True,
            "error": "SPEC 的 error 携带冻结/用户指令标记（admin 巡检 blocked_stuck 豁免的依据），清除会使豁免失效并引发循环误报；请先经官方通道处置或人工修正 STATE.md",
        }
    from core.pm_engine.reporting import (
        extract_push_attempts_marker,
        extract_push_backoff_marker,
    )
    from core.state_machine import (
        PUSH_ATTEMPTS_FIELD,
        PUSH_BACKOFF_NEXT_RETRY_AT_FIELD,
    )

    # 退避标记摘取回写（code-review item bbba88d8e6af）：机器可读标记寄居
    # error 文本，整段清空会把 push 退避期与连续重试计数一并归零。清空前
    # 先摘取文本标记回写专用字段；标记不在时不写键——保留字段既有值，
    # 普通错误清除不误伤退避状态。
    updates = {"error": None}
    backoff_until = extract_push_backoff_marker(err_text)
    if backoff_until is not None:
        updates[PUSH_BACKOFF_NEXT_RETRY_AT_FIELD] = backoff_until
    push_attempts = extract_push_attempts_marker(err_text)
    if push_attempts is not None:
        updates[PUSH_ATTEMPTS_FIELD] = push_attempts

    sm = _sm(proot)
    if not sm.update_spec(spec, updates):
        # 与 reset_verification 同口径（写入必留痕）：spec 在前置校验后被并发
        # 软删除/写入被拒时清除未落盘，WARNING 留痕并如实返回失败形状
        # （路由侧按 ok 分流 409），不再无条件宣称「已清除」。
        logger.warning(
            "clear_spec_error 清除失败：spec 已并发删除或写入被拒，清除未落盘（spec=%s）",
            spec,
        )
        return {"ok": False, "found": True,
                "error": "spec 已并发删除或写入被拒，清除未落盘"}
    return {"ok": True, "found": True}


# set_spec_priority 的校验异常（code-review item 3b904e164982：唯一 raise 点
# 在本模块，异常定义随抛出者走，不再寄居 spec_docs；routes 侧仍经门面
# dashboard_data.InvalidPriority 捕获映射 400，导入路径不变）
class InvalidPriority(ValueError):
    """优先级非法（非 1-9 整数）。"""


def set_spec_priority(project_root, spec: str, priority) -> dict:
    """设置 SPEC 的 priority 字段（1-9，P1 最高）并原子写回 STATE.md。

    校验优先级须为 1-9 整数（含可转 int 的 str，如 "2"）；校验失败抛
    InvalidPriority。spec 须存在于项目 STATE.md，不存在返回 {found: False}。
    成功后复用 StateMachine.update_spec（flock + 原子 rename 写回），
    同时刷新 updated 时间戳，并返回写入后的 priority。

    Returns:
        {"found": bool, "priority": int}  — found=False 表示 spec 不在 STATE.md
        写入失败（前置校验后并发软删除/写入被拒）→
        {"found": True, "ok": False, "priority": None, "error": ...}
        （WARNING 留痕，STATE 零变更；路由侧按 ok 分流 409）
    Raises:
        InvalidPriority: priority 不在 1-9 或不可转为整数
    """
    # 1-9 整数校验（兼容可被 int() 消费的字符串）；bool/浮点直接拒绝，
    # 对齐 set_spec_budget 的校验口径——bool 是 int 子类、int() 会静默截断浮点
    if isinstance(priority, bool) or not isinstance(priority, (int, str)):
        raise InvalidPriority(priority)
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

    sm = _sm(proot)
    if not sm.update_spec(spec, {"priority": p}):
        # 与 reset_verification 同口径（写入必留痕）：spec 在前置校验后被并发
        # 软删除/写入被拒时写入未落盘，WARNING 留痕并如实返回失败形状
        # （路由侧按 ok 分流 409），不再无条件宣称已写入。
        logger.warning(
            "set_spec_priority 写入失败：spec 已并发删除或写入被拒，写入未落盘（spec=%s）",
            spec,
        )
        return {"found": True, "ok": False, "priority": None,
                "error": "spec 已并发删除或写入被拒，写入未落盘"}
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
    # fix-env-exemption-exit-reachability 4.5：env 豁免握手/inconclusive 升级
    # 停车族的一键处置可达性硬前提——grant_env_exemption / manual_fixed_
    # reverify 经 alert-resolve 以 signal_type=inconclusive_loop 调本动词，
    # 不放行则在前置校验即被拒，选项集接线形同虚设。
    "inconclusive_loop",
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
# judge/verify 失败轮不在其清零面）。布尔标记清 False（_judge_cap_frozen 等
# 在 parse 布尔归一清单内，读回真 False）。_verify_parallel_override 清
# None——其契约是 int|None（降档并行度 int 写点 escalation、复位点一律
# None，unfreeze_spec 先例亦写 None），布尔归一清单不含该字段：写 False
# 会 STATE.md 往返字符串化、读端 int() 解析失败降档告警
# （evo-fix-verify-parallel-override-type 1.1 纠偏；state_machine 写侧另有
# 单字段形状守卫拒绝布尔/字符串写入）。生命周期累计字段
# （_tokens_*、_cost_usd）与实现预算 _impl_run_budget_used 不在此——后者仅
# continue_auto_fix 语义清零，reset_verification 不重发实现预算。
_RETRY_COUNTER_RESETS = {
    "_judge_rerun_count": 0,
    "_judge_cap_frozen": False,
    "_verify_fail_rounds": 0,
    "_verify_redo_count": 0,
    "_verify_parallel_override": None,
    "_inconclusive_attempts": 0,
    "_env_block_rounds": 0,
    "_redispatch_same_cause_streak": 0,
    "_redispatch_cause_fp": None,
    # fix-env-exemption-exit-reachability 3.4：inconclusive 重验预算隔离双
    # 字段（独立计数器 + 旗标，design D3）与 _judge_rerun_count 同生命周期，
    # 人工复位一并清零/清除（防旗标滞留使复位后正常轮 judge 派发持续分流）。
    "_judge_inconclusive_dispatches": 0,
    "_in_inconclusive_reverify": False,
    # 同 spec 2.2：级一签名比较基准——跨 episode 过期基准会把重置后的首轮
    # 误判「环境未变」提前升级，复位必须清（首轮按基准未知保守走计数上限）。
    "_last_inconclusive_signature": None,
    # 同 spec 1.1：级二停车退避窗——清 error 后残留会拖延重置后首派
    # （spec_is_undriven 条件③ 在退避窗内恒真，探测器静默）。
    "_dispatch_backoff_until": None,
    # 同字段 3.3：独立计数器到顶升级告警的去重标记——复位后新 episode
    # 再到顶应能再次告警。
    "_judge_inconclusive_cap_escalated": False,
    # evo-fix-env-exemption-gate-conflict-… 2.2：场景修订待重验旗标——复位
    # 视为验证链输入整体重置，滞留旗标会让复位后首次升级被误判为修订
    # re-entry 追加重验轮。修订次数计数（_scenario_revision_count）**不清**：
    # 生命周期累计语义（修订上限跨复位保持，防借复位刷修订预算）。
    SCENARIO_REVISION_PENDING_FIELD: False,
}

# force_advance 允许的目标状态（design D4：校验目标可达性，不开放任意跳转）
_FORCE_ADVANCE_TARGETS = ("done", "verified")


def _sm(project_root):
    """本模块动作函数共用的 StateMachine 构造（flock + 原子写，与 daemon 并发安全）。

    原 _adjudication_sm 只收编裁决动词，构造口径（路径/日志器）改动时仍须
    逐点扫齐其余动作函数的内联构造，故扩展为通用助手并更名；旧名保留作
    兼容别名。
    """
    from core.state_machine import StateMachine, project_state_logger

    return StateMachine(
        Path(project_root) / ".fenix" / "STATE.md",
        project_state_logger(project_root),
    )


# 兼容别名：既有裁决动词调用点与外部引用仍可用旧名
_adjudication_sm = _sm


def _is_inconclusive_parking_form(entry: dict) -> bool:
    """spec 条目是否为 env 豁免握手 inconclusive 升级停车形态（4.5 前置门扩展）。

    停车形态（fix-env-exemption-exit-reachability D5）：status=implemented +
    ``_inconclusive_attempts``>0 + error 命中 inconclusive 停车文案特征
    （与 escalation 写侧共用同一常量防漂移）。三条件缺一不可——裸
    implemented 不放行（重置验证不适用于任意实现中 spec），计数为 0 说明
    不在 inconclusive episode 内。
    """
    from core.pm_engine.verification.escalation import (
        INCONCLUSIVE_PARKING_ERROR_MARKER,
    )

    if str(entry.get("status") or "") != "implemented":
        return False
    try:
        if int(entry.get("_inconclusive_attempts", 0) or 0) <= 0:
            return False
    except (TypeError, ValueError):
        return False
    return INCONCLUSIVE_PARKING_ERROR_MARKER in str(entry.get("error") or "")


def reset_verification(project_root, spec: str, note: str = "", signal_type: str = "") -> dict:
    """裁决动词：人工裁定验证链输入已失真，重置验证重跑（add-human-adjudication-choices 3.1）。

    执行序列：前置校验（spec 形态白名单/冻结/blocked 且属验证链信号）→ 删该
    spec 的场景与验证进度运行时文件（精确 spec 名拼路径，禁通配）并失效
    spec 戳匹配的项目根共享 run-result → 清 judge 重跑与验证
    失败轮计数并剥冻结清 error（保持 blocked）→ 按
    ``resolve_env_blocked_reset_path`` 推进（分支已合并走 BLOCKED→TESTING
    门禁直通道重验，否则 BLOCKED→READY 回实现并写调度唤醒信号）→ 返回执行
    步骤明细。生命周期累计字段（tokens/cost 审计）不清零。

    Returns:
        {"ok": bool, "found": bool, "steps": [str], "target_status": str|null,
         "error": str|null}
    """
    proot = Path(project_root)
    # 形态白名单前置（code-review item a1e09f8181cd）：spec 名直接拼
    # verify-progress 删除路径，仅靠「须在 STATE.md 注册」一道门禁不足——
    # 手改塞入含路径分隔符/「..」的名字可越出目录。复用 kebab-case 权威
    # 正则白名单（与 kick 写入路径 validate_scheduling_kick_spec 同防线），
    # 不合规形态直接拒绝；合规律名字不可能注册进 STATE.md，故按既有
    # not-found 形状返回。
    spec_shape_error = validate_scheduling_kick_spec(spec)
    if spec_shape_error:
        return {"ok": False, "found": False, "steps": [], "target_status": None,
                "error": spec_shape_error}
    specs = parse_state(proot)
    if spec not in specs:
        return {"ok": False, "found": False, "steps": [], "target_status": None,
                "error": f"spec not found: {spec}"}
    entry = specs[spec]
    parking_form = _is_inconclusive_parking_form(entry)
    if not (is_spec_frozen(entry) or entry.get("status") == "blocked" or parking_form):
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
        # 用户指令冻结默认拒绝（code-review item 659874157d55）：freeze_spec
        # 把人工 reason 并入冻结 error（「用户指令冻结：原状态 X · <reason>」），
        # 自定义 reason 含「重派/验证/预算/env」等通用词即命中下方 marker 子串
        # 判别，人工冻结被静默解除并删验证进度。人工冻结走 unfreeze/裁决动词
        # 处置；自动冻结（闸门/env 阻塞/judge·verify 链）写自有文案不携带本
        # 前缀（见 is_spec_frozen 注），合法验证链冻结不受影响——结构化
        # signal_type 路径同样不经过本判定。
        if error_text.startswith(FREEZE_ERROR_PREFIX):
            return {
                "ok": False, "found": True, "steps": [], "target_status": None,
                "error": "用户指令冻结不属验证链信号（人工冻结走解冻/裁决处置），重置验证被拒绝",
            }
        if not any(m in error_text for m in _VERIFY_CHAIN_ERROR_MARKERS):
            return {
                "ok": False, "found": True, "steps": [], "target_status": None,
                "error": "冻结原因不属验证链信号（error 文本无验证链特征），重置验证被拒绝",
            }

    steps: list = []
    # 2. 删该 spec 自己的场景/进度文件（路径按 spec 名精确构造，无 glob）
    vp_dir = proot / ".fenix" / "verify-progress" / spec
    deleted_any = False
    for fname in _VERIFY_PROGRESS_RUNTIME_FILES:
        fpath = vp_dir / fname
        if fpath.is_file():
            try:
                fpath.unlink()
                deleted_any = True
                steps.append(f"已删除 {fpath.relative_to(proot)}")
            except OSError as e:
                # 不外泄裸异常文本（code-review item e584a2ede367）：OSError
                # 可携带内部路径/errno，细节降级经服务端日志留痕
                logger.warning(
                    "reset_verification 删除验证进度文件失败（spec=%s file=%s）: %s: %s",
                    spec, fname, type(e).__name__, e,
                )
                return {"ok": False, "found": True, "steps": steps,
                        "target_status": None,
                        "error": f"删除验证进度文件失败 {fname}"}

    # 2b. 失效共享 run-result（code-review item 13304b99fea3）：读侧
    # _load_run_result（artifacts.py）的第二候选是项目根共享
    # .fenix/.fenix-run-result.json，spec 戳匹配即采纳——专属副本删除后，
    # 上一轮残留的共享结果仍会经 parse_verdict/parse_bugs/
    # parse_run_result_scenarios 兜底通道复活旧裁决/场景/bug 清单。仅当共享
    # 文件显式携带本 spec 戳才删除；损坏/缺失/他 spec 残留一律不动（不误伤
    # 其它 spec，待下一个任意 spec 的 run 覆盖或其自身 reset 处置）。
    shared_run_result = proot / ".fenix" / ".fenix-run-result.json"
    if shared_run_result.is_file():
        try:
            shared_data = json.loads(shared_run_result.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            shared_data = None
        if isinstance(shared_data, dict) and shared_data.get("spec") == spec:
            try:
                shared_run_result.unlink()
                deleted_any = True
                steps.append(f"已删除 {shared_run_result.relative_to(proot)}")
            except OSError as e:
                # 同上：OSError 细节降级，经服务端日志留痕
                logger.warning(
                    "reset_verification 删除共享 run-result 失败（spec=%s）: %s: %s",
                    spec, type(e).__name__, e,
                )
                return {"ok": False, "found": True, "steps": steps,
                        "target_status": None,
                        "error": "删除共享 run-result 文件失败"}
    if not deleted_any:
        steps.append("无场景/进度文件可删（verify-progress 目录不存在或已清）")

    # 3+4a. 清计数 + 剥冻结 + 清 error（自带 frozen 键走 update_spec 显式豁免，
    # status 保持 blocked 供复位路径判定）
    sm = _sm(proot)
    updates = {"frozen": False, "error": None, "frozen_until": None}
    updates.update(_RETRY_COUNTER_RESETS)
    if not sm.update_spec(spec, updates):
        # 与 resume_cancelled_spec 同口径（写入必留痕）：spec 在前置校验后被
        # 并发软删除/写入被拒时计数清理未落盘，steps 如实陈述并提前返回失败
        # 形状，不再走后续 transition（对缺失 spec 行为未定义）。
        logger.warning(
            "reset_verification 清计数失败：spec 已并发删除，计数清理未落盘（spec=%s）",
            spec,
        )
        steps.append("spec 已并发删除，计数清理未落盘")
        return {"ok": False, "found": True, "steps": steps,
                "target_status": None,
                "error": "spec 已并发删除，计数清理未落盘"}
    steps.append("已清零 judge 重跑/验证失败轮等重试计数并解除冻结（保持 blocked）")

    # 4b. 复位路径判定（基于清除后的干净 entry）
    from core.pm_engine.verification.branch_guard import resolve_env_blocked_reset_path

    entry2 = parse_state(proot).get(spec) or {}
    reset_error = None
    if entry2.get("status") != "blocked":
        steps.append(f"spec 已不在 blocked（当前 {entry2.get('status')}），无需复位转换")
        target = entry2.get("status")
    else:
        path = resolve_env_blocked_reset_path(entry2, proot)
        if path == "testing":
            # 复位转换结果如实回报（code-review item 5f650e3b6404）：快照与
            # transition 之间 spec 被并发改写或门禁拒绝时返回 False，此时 error
            # 已被上一步清空、spec 仍滞留 blocked——不得宣称已复位到 testing。
            if not sm.transition_gate(spec, "testing", channel="manual"):
                reset_error = "复位转换未生效：BLOCKED→TESTING 门禁转换被拒或未落盘"
            else:
                target = "testing"
                steps.append("实现分支已合并：BLOCKED→TESTING 门禁直通道重验")
        else:
            if not sm.transition(spec, "ready", channel="manual"):
                reset_error = "复位转换未生效：BLOCKED→READY 转换被拒或未落盘"
            else:
                target = "ready"
                kicked = _kick_step_suffix(proot, spec)
                steps.append("实现分支未合并或缺 branch：BLOCKED→READY 回实现通道" + kicked)
    if reset_error:
        # 与上方 update_spec 同口径（写入必留痕）：WARNING 留痕 + 失败形状，
        # target_status 如实报 None（spec 实际仍滞留 blocked 且 error 已清空）。
        logger.warning(
            "reset_verification %s，spec 仍滞留 blocked（spec=%s）", reset_error, spec,
        )
        steps.append(reset_error + "，spec 仍滞留 blocked")
    if note:
        steps.append(f"裁决依据：{note}")
    if reset_error:
        return {"ok": False, "found": True, "steps": steps,
                "target_status": None, "error": reset_error}
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
    sm = _sm(proot)
    if not sm.update_spec(spec, {"frozen": False, "status": target_status, "error": None}):
        # 与 reset_verification 同口径（写入必留痕）：spec 在前置校验后被并发
        # 软删除/写入被拒时推进未落盘，WARNING 留痕并如实返回失败，
        # 不再拼「Transition」步骤伪装成功（对缺失 spec 行为未定义）。
        logger.warning(
            "force_advance 推进失败：spec 已并发删除或写入被拒，裁决未落盘（spec=%s）",
            spec,
        )
        return {"ok": False, "found": True, "steps": [], "from_status": None,
                "status": None,
                "error": "spec 已并发删除或写入被拒，裁决未落盘"}
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
    sm = _sm(proot)
    if not sm.update_spec(spec, {
        "frozen": False, "status": "ready", "error": None,
        "reviewer_run": None, "_review_attempts": 0,
    }):
        # 与 reset_verification 同口径（写入必留痕）：spec 在前置校验后被并发
        # 软删除/写入被拒时跳过评审未落盘，WARNING 留痕并如实返回失败，
        # 不再拼「Transition」步骤伪装成功（对缺失 spec 行为未定义）。
        logger.warning(
            "skip_review_gate 跳过评审门失败：spec 已并发删除或写入被拒，"
            "裁决未落盘（spec=%s）",
            spec,
        )
        return {"ok": False, "found": True, "steps": [], "status": None,
                "error": "spec 已并发删除或写入被拒，裁决未落盘"}
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
    sm = _sm(proot)
    if not sm.update_spec(spec, {
        "frozen": False, "status": "reviewing", "error": None,
        "reviewer_run": None, "_review_attempts": 0,
    }):
        # 与 reset_verification 同口径（写入必留痕）：spec 在前置校验后被并发
        # 软删除/写入被拒时解冻未落盘，WARNING 留痕并如实返回失败，
        # 不再拼「Transition」步骤伪装成功（对缺失 spec 行为未定义）。
        logger.warning(
            "_exec_review_unfreeze 解冻失败：spec 已并发删除或写入被拒，"
            "裁决未落盘（spec=%s）",
            spec,
        )
        return {"ok": False, "steps": [],
                "error": "spec 已并发删除或写入被拒，裁决未落盘"}
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
    sm = _sm(proot)
    updates = {"frozen": False, "error": None, "frozen_until": None}
    updates.update(_RETRY_COUNTER_RESETS)
    # 人工重置基线（code-review item 043e9fdd3ac7）：只清零不写可被对账识别
    # 的锚点时，对账组件 _reconcile_impl_budget 的不变量（used == runs 正常
    # 收工 run 数）会在下一轮实现 run 收工对账时把 used 改写回历史 run 数——
    # 人工重置在一个周期内被静默回滚，预算闸门随即再次冻结，本动作承诺的
    # 「重新获得完整自动修复预算」不成立（预算耗尽的常见成因是多次正常收工
    # 失败，此类 spec 无任何豁免标记、对账必然自动改数）。清零前取当前 used
    # 作基线同批落盘，对账口径变为 max(0, run 数 − 基线)：历史 run 数不再
    # 回滚清零，重置后新产生的 run 消耗照常累计，闸门再次耗尽仍生效
    # （多次人工重置后基线与 completed 全量计数的口径错位，由对账组件
    # _reconcile_impl_budget 的重锚自愈兜底，见 budget.py）。
    try:
        prev_used = int(entry.get("_impl_run_budget_used", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        prev_used = 0
    updates[BUDGET_MANUAL_RESET_BASELINE_FIELD] = max(0, prev_used)
    updates["_impl_run_budget_used"] = 0
    if not sm.update_spec(spec, updates):
        # 与 reset_verification 同口径（写入必留痕）：spec 在前置校验后被并发
        # 软删除/写入被拒时清计数未落盘，WARNING 留痕并如实返回失败，
        # 不再继续 transition（对缺失 spec 行为未定义）伪装成功。
        logger.warning(
            "continue_auto_fix 清计数失败：spec 已并发删除或写入被拒，"
            "裁决未落盘（spec=%s）",
            spec,
        )
        return {"ok": False, "steps": [],
                "error": "spec 已并发删除或写入被拒，裁决未落盘"}
    if not sm.transition(spec, "ready", channel="manual"):
        # 复位转换结果如实回报（code-review item 5f650e3b6404）：快照与
        # transition 之间 spec 被并发改写或转换被拒时未生效，error 已被上一步
        # 清空、spec 仍滞留 blocked——不得宣称「BLOCKED→READY 回实现通道」。
        logger.warning(
            "continue_auto_fix 复位转换未生效：BLOCKED→READY 被拒或未落盘，"
            "spec 仍滞留 blocked（spec=%s）",
            spec,
        )
        return {"ok": False, "steps": [],
                "error": "复位转换未生效：BLOCKED→READY 转换被拒或未落盘"}
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
    from .config_admin import write_config

    proot = Path(project_root)
    current_val = 50.0
    try:
        # 翻倍基数取**生效**预算（code-review item 3de34b86c99e）：项目级
        # read_config 回显只对真 int 生效（_echo_agents_int_keys 过滤）且不含
        # 用户级继承——预算只配在用户级（如生效 80M）或项目级为 float（如 0.5）
        # 时读到 None 会误回缺省 50，「翻倍」语义失真且项目级显式值从此覆盖
        # 用户级。改经 ConfigLoader.resolve_config 取用户级+项目级深合并后的
        # 原始值（int/float 均参与运算，bool 排除），与预算检查器
        # （token_budget._get_config 生效值口径）一致。
        from core.config import ConfigLoader

        effective = ConfigLoader.resolve_config(proot)
        raw = (effective.get("agents") or {}).get("token_budget_millions")
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            current_val = float(raw)
    except Exception:  # noqa: BLE001 — 读侧任何异常按缺省 50 兜底（宁缺毋 500）
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
        sm = _sm(proot)
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
    """declare_no_artifacts：原子写 worktree.has_build_artifacts=false 结案。

    写路径复用 write_config 受管通道（受管合并、mkstemp 唯一临时文件、
    文件头与错误口径统一），与 _exec_raise_budget 同范式。
    """
    from .config_admin import write_config

    proot = Path(project_root)
    r = write_config(proot, {"worktree": {"has_build_artifacts": False}}, scope="project")
    if not r.get("ok"):
        return {"ok": False, "steps": [], "error": f"写配置失败: {r.get('error')}"}
    steps = ["worktree.has_build_artifacts=false 已写入 .fenix/config.yaml"
             "（原子写，声明本项目无构建产物，结案）"]
    if note:
        steps.append(f"裁决依据：{note}")
    return {"ok": True, "steps": steps, "error": None}


# ── env 归因证据门（evo-fix-env-exemption-gate-conflict-… 2.3）──
# 媒体管线词汇：归因文本出现任一即视为「声称帧管线类失败」，须同时给出
# 送帧侧与解码侧两段证据引用才维持 env 结论。
ENV_ATTR_MEDIA_VOCAB = (
    "帧", "frame", "feed", "解码", "decode", "编码", "encode",
    "相机", "camera", "视频", "video", "推流", "采样", "sample", "md5",
)
# 送帧侧证据引用词形（提送/推流/喂帧链路实测记录）
ENV_ATTR_FRAME_FEED_MARKERS = (
    "送帧", "推帧", "喂帧", "提送", "推流", "已送", "send_frame",
    "push_frame", "frame pushed", "frames sent", "frame_count",
)
# 解码侧证据引用词形（解码输出/解出帧/软硬解记录）
ENV_ATTR_DECODE_MARKERS = (
    "解码", "decode", "软解", "硬解", "解出", "yuv", "nv12", "rgb",
)


def env_attribution_evidence_gate(classification, evidence_text) -> str:
    """env 归因结论的证据门（纯函数，级二判定调用；2.3）。

    规则（fail-closed 只对 env 结论收紧，不做任何放行放宽）：
      - classification != "env"：原样返回（非 env 归因与本门无关）；
      - evidence_text 不含任何媒体管线词汇：原样返回——普通 env 归因
        （端口失联、依赖缺失、served dist 为中间态构建等）不受此门约束，
        既有裁决车道零行为变化；
      - 含媒体词汇但**不同时具备**送帧侧与解码侧证据引用：降级返回
        "inconclusive"——声称帧管线类失败却只给一句现象描述的归因不可
        采信（2026-10-05 potplayer：归因一句「解码失败」，既无送帧计数
        也无解码输出记录，级二据此整轮放行豁免属证据不足放行）。

    Returns: "env"（维持）/ "inconclusive"（降级）。
    """
    cls = str(classification or "")
    if cls != "env":
        return cls
    text = str(evidence_text or "")
    if not any(word in text for word in ENV_ATTR_MEDIA_VOCAB):
        return cls  # 非媒体词汇 env 归因不受此门约束
    has_feed = any(m in text for m in ENV_ATTR_FRAME_FEED_MARKERS)
    has_decode = any(m in text for m in ENV_ATTR_DECODE_MARKERS)
    if has_feed and has_decode:
        return "env"
    return "inconclusive"


def _env_exemption_candidates(project_root, spec: str, disposition_id) -> list:
    """从验证报告非 pass 场景构建豁免候选清单（evo-fix-… 1.1）。

    每条豁免键 = 场景 id + 归一化失败签名（``scenario_fail_signature_body``
    与升级/门禁同口径）+ 场景定义 hash（``load_frozen_scenario_hashes`` 当前
    冻结定义，单源在 state_machine）+ 时效锚点 granted_at。disposition 落
    审计镜像（disposition_id 回链）。

    report.json 缺位/无场景时返回 []（不臆造豁免对象——下游双门读空清单
    fail-closed，放行退回 disposition 存量通道，行为与历史版本一致）。
    """
    from core.state_machine import (
        load_frozen_scenario_hashes,
        scenario_fail_signature_body,
    )
    from core.verdict_check import load_report

    report = load_report(project_root, spec) or {}
    scenarios = report.get("scenarios") or []
    if not scenarios:
        return []
    hashes = load_frozen_scenario_hashes(project_root, spec)
    granted_at = datetime.now(timezone.utc).isoformat()
    out: list = []
    for sc in scenarios:
        if not isinstance(sc, dict):
            continue
        # pass/paired 之外全部入豁免候选：含 fail/error/warning 与 blocked-env
        # （judge 裁决「全部失败归 env」时 blocked-env 场景从未执行、无失败
        # 断言，签名退化为 blocked-env——同样是豁免对象；NON_PASS_STATUSES
        # 不含 blocked-env，不能用之作过滤，会整类漏授）。
        if sc.get("status") in ("pass", "passed"):
            continue
        sid = str(sc.get("scenario_id") or sc.get("id") or "").strip()
        if not sid:
            continue
        out.append({
            "scenario_id": sid,
            "failure_signature": scenario_fail_signature_body(sc),
            "scenario_hash": hashes.get(sid, ""),
            "granted_at": granted_at,
            "disposition_id": str(disposition_id or ""),
            "source": "grant_env_exemption",
        })
    return out


def _write_env_exemptions_state(project_root, spec: str, disposition_id) -> str:
    """把豁免清单写入 spec 级 STATE 字段（evo-fix-… 1.1 豁免生效主源）。

    与既有 STATE 豁免按（场景 id, 失败签名）合并——同键刷新 granted_at/hash/
    disposition_id（重授予即续期），异键追加；总量超 ``ENV_EXEMPTION_MAX_
    ENTRIES`` 按 granted_at 保新截旧。写入经 ``update_spec``（flock 原子），
    返回空串=成功、非空=错误文本（调用方 fail-closed 不执行重置）。
    """
    from core.state_machine import (
        ENV_EXEMPTION_MAX_ENTRIES,
        parse_env_exemptions,
        serialize_env_exemptions,
    )

    try:
        additions = _env_exemption_candidates(project_root, spec, disposition_id)
        sm = _sm(project_root)
        entry = sm.read_one(spec)
        if entry is None:
            return f"spec '{spec}' 不存在，无法写 STATE 豁免字段（fail-closed）"
        merged: dict = {}
        for item in parse_env_exemptions(entry):
            key = (str(item.get("scenario_id") or ""),
                   str(item.get("failure_signature") or ""))
            merged[key] = item
        for item in additions:
            key = (str(item.get("scenario_id") or ""),
                   str(item.get("failure_signature") or ""))
            merged[key] = item  # 同键刷新（重授予=续期），异键追加
        exemptions = sorted(
            merged.values(),
            key=lambda it: str(it.get("granted_at") or ""),
        )
        if len(exemptions) > ENV_EXEMPTION_MAX_ENTRIES:
            exemptions = exemptions[-ENV_EXEMPTION_MAX_ENTRIES:]
        ok = sm.update_spec(spec, {
            ENV_EXEMPTIONS_FIELD: serialize_env_exemptions(exemptions),
        })
        if not ok:
            return "STATE 豁免字段写入未生效（update_spec 拒绝，fail-closed）"
        return ""
    except Exception as e:
        logger.warning(
            "grant_env_exemption 写 STATE 豁免字段失败（spec=%s）: %s: %s",
            spec, type(e).__name__, e,
        )
        return "STATE 豁免字段写入失败（fail-closed，不执行重置）"


def _exec_grant_env_exemption(project_root, spec: str, note: str = "") -> dict:
    """grant_env_exemption：人工授予 env 豁免（fix-env-exemption-exit-reachability 4.2）。

    执行序列（fail-closed）：
      1. 经 AdminStore 写 kind=DISPOSITION 放行记录（signal_type=inconclusive_loop、
         result 显式 env 豁免放行语义、note 落人工审计文本）——幂等锚点对齐
         既有 disposition 形态（``latest_resolved_disposition`` 按
         spec+signal_type+result∈{resolved, partially-resolved} 取最近一条）；
      2. 写 spec 级 STATE 豁免字段（evo-fix-env-exemption-gate-conflict-… 1.1，
         场景 id+归一化失败签名+定义 hash+时效锚点）——豁免**生效主源**，
         升级握手与 verified 洗白门禁同源消费；disposition 自此为审计镜像
         （存量放行查询通道保留作回退）；
      3. 调 ``reset_verification`` 复用既有清计数/清验证进度路径（signal_type
         显式传入走 VERIFY_CHAIN_SIGNAL_TYPES 精确判别）。

    DISPOSITION 或 STATE 写失败**不执行重置**（fail-closed）：握手/门禁查不
    到有效豁免会把重验后的全 env 轮再次拦截回升级停车——「重置了却没放行」
    正是 2026-10-03 死循环与 2026-10-05 双门矛盾的复发形态。放行 → 重置 →
    重验 → STATE 豁免命中放行 → 合法 verified（报告带回链）。

    Returns:
        {"ok": bool, "steps": [str], "target_status": str|null, "error": str|null,
         "disposition_id": str|null}
    """
    from core.admin_store import AdminStore, DISPOSITION

    proot = Path(project_root)
    store = AdminStore(proot, logger)
    audit_note = note or "人工授予 env 豁免：失败确属环境且不可修复，放行重验"
    try:
        rec = store.append({
            "kind": DISPOSITION,
            "signal_type": "inconclusive_loop",
            "spec": spec,
            "severity": "major",
            "description": (
                f"人工授予 env 豁免（'{spec}' judge 已裁决全部失败归 env、"
                f"豁免握手拦截 verified）"
            ),
            "action_taken": "grant_env_exemption",
            # result 显式 env 豁免放行语义：resolved 进 latest_resolved_
            # disposition 放行查询锚点（非 resolved 不构成放行，握手不认）。
            "result": "resolved",
            "note": audit_note,
        })
    except Exception as e:
        # 不外泄裸异常文本（code-review item e584a2ede367 同口径）
        logger.warning(
            "grant_env_exemption 写放行记录失败（spec=%s）: %s: %s",
            spec, type(e).__name__, e,
        )
        return {"ok": False, "steps": [], "target_status": None,
                "disposition_id": None,
                "error": "env 豁免放行记录写入失败（fail-closed，不执行重置）"}
    if rec is None:
        # store 拒写（文件损坏留底被下限保护等，append 契约返回 None）：
        # 记录未落盘，按 fail-closed 处置（item 2570ca39177a 先例）
        return {"ok": False, "steps": [], "target_status": None,
                "disposition_id": None,
                "error": "env 豁免放行记录未落盘（store 拒写，fail-closed 不执行重置）"}
    steps = [f"已落 env 豁免放行记录（id={rec.get('id')}，result=resolved，"
             f"豁免下轮 verified 合法生效带回链）"]
    # ── evo-fix-env-exemption-gate-conflict-… 1.1：STATE 豁免字段写入 ──
    # 豁免生效主源改 spec 级 STATE 字段（场景 id+失败签名+定义 hash+时效），
    # 升级握手与 verified 洗白门禁同源消费——disposition 降为审计镜像。
    # STATE 写失败不执行重置（fail-closed）：「重置了却没豁免」会让重验后
    # 的全 env 轮被门禁重新拦截，正是本 SPEC 要消除的矛盾形态。
    state_err = _write_env_exemptions_state(
        project_root, spec, disposition_id=rec.get("id"),
    )
    if state_err:
        return {"ok": False, "steps": steps, "target_status": None,
                "disposition_id": rec.get("id"), "error": state_err}
    steps.append("已写 spec 级 STATE 豁免字段（场景 id+失败签名+定义 hash+时效，"
                 "握手与洗白门禁同源消费）")
    r = reset_verification(
        project_root, spec,
        note=f"授予 env 豁免后重置重验：{audit_note}" if note else "授予 env 豁免后重置重验",
        signal_type="inconclusive_loop",
    )
    steps.extend(r.get("steps") or [])
    merged = {
        "ok": bool(r.get("ok")),
        "steps": steps,
        "target_status": r.get("target_status"),
        "disposition_id": rec.get("id"),
        "error": r.get("error"),
    }
    if not r.get("ok") and not merged["error"]:
        merged["error"] = "放行记录已落库，但验证重置未成功"
    return merged


def _exec_revise_scenario_reverify(project_root, spec: str, note: str = "") -> dict:
    """revise_scenario_reverify：场景修订重验出口（evo-fix-… 2.1）。

    场景不可行/夹具缺供给时的人工修订通道：改写场景定义与夹具供给层文件
    （仅白名单路径）后重置重验。执行序列（任一步失败即停，不留半改状态）：

      1. 解析载荷：note 为 JSON
         ``{"scenarios": [...], "reason": "...",
            "fixture_files": [{"path": "...", "content": "..."}]}``，
         scenarios 必填（修订后的完整场景集，整体替换而非增量）；
      2. 修订预算前置：``_scenario_revision_count >= SCENARIO_REVISION_MAX_
         COUNT``（默认 2）→ 拒绝执行并 ``freeze_spec`` 转人工冻结——修订
         出口耗尽，继续修订只是把「场景设计不可行」往预算里藏；
      3. 夹具路径白名单（``validate_scenario_revision_paths``）：绝对路径/
         穿越/产品代码路径拒绝；
      4. 场景结构预校验（``validate_scenario_dicts``）：非法场景不入盘；
      5. 落盘：夹具文件按 project_root 锚定写入；场景集经
         ``prepare_scenarios_for_write`` 盖版本戳后**成对同覆盖**
         ``test_scenarios.json`` 与 ``_scenarios_full.json``（防对账回填旧
         定义，fix-frozen-scenario-shell-truncation 同款成对纪律）。
         逐文件写前快照，任一步失败按快照回滚本轮已写文件（不留半改状态
         与成对撕裂对，code-review item 97da350709f7）；
      6. STATE：修订计数 +1、置 ``_scenario_revision_reverify_pending``
         （修订 re-entry 先于升级——下轮再失败时升级停车入口见旗标追加
         一次重验而非直接升级）、清 env 阻塞/inconclusive 停车字段
         （_RETRY_COUNTER_RESETS，含 ``_env_block_rounds`` 与退避窗）；
      7. 解冻 + implemented→testing 门禁转换 + 写调度唤醒信号重派 verifier。

    Returns:
        {"ok": bool, "steps": [str], "error": str|null, "frozen_manual": bool}
    """
    from .adjudication_choices import validate_scenario_revision_paths
    from core.pm_engine.verification.scenario_gate import atomic_write_text
    from core.verify_engine.scenarios import (
        prepare_scenarios_for_write,
        validate_scenario_dicts,
    )

    proot = Path(project_root)
    steps: list = []
    # 1. 载荷解析（note 传 JSON；裸文本视为缺载荷拒绝——修订 MUST 以结构化
    # 场景集为输入，凭一句「改一下」执行会让修订内容无据可查）
    payload = None
    try:
        payload = json.loads(note) if note and note.strip() else None
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = None
    if not isinstance(payload, dict):
        return {"ok": False, "steps": [], "error": (
            "revise_scenario_reverify 需要 JSON 载荷：{\"scenarios\": [...], "
            "\"reason\": \"...\", \"fixture_files\": [{\"path\", \"content\"}]}"
        ), "frozen_manual": False}
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        return {"ok": False, "steps": [],
                "error": "载荷 scenarios 缺失或为空（修订须给出完整场景集）",
                "frozen_manual": False}
    fixture_files = payload.get("fixture_files") or []
    if not isinstance(fixture_files, list):
        return {"ok": False, "steps": [], "error": "载荷 fixture_files 须为数组",
                "frozen_manual": False}
    # 非 dict 项须整体拒绝：夹具白名单步骤会静默跳过非 dict 项，而写盘循环对
    # 所有 item 调 .get——非 dict 项混入时会在前面的夹具已落盘后才抛
    # AttributeError，留下半改状态（违背「任一步失败即停，不留半改状态」）。
    if not all(isinstance(f, dict) for f in fixture_files):
        return {"ok": False, "steps": [],
                "error": "载荷 fixture_files 每项须为对象（{\"path\", \"content\"}）",
                "frozen_manual": False}

    # 2. 修订预算前置（超限转人工冻结）
    specs = parse_state(proot)
    if spec not in specs:
        return {"ok": False, "steps": [], "error": f"spec not found: {spec}",
                "frozen_manual": False}
    entry = specs[spec]
    try:
        revision_count = int(entry.get(SCENARIO_REVISION_COUNT_FIELD) or 0)
    except (TypeError, ValueError):
        revision_count = 0
    if revision_count >= SCENARIO_REVISION_MAX_COUNT:
        fr = freeze_spec(
            proot, spec,
            reason=(f"场景修订次数达上限（{SCENARIO_REVISION_MAX_COUNT}）："
                    "修订出口耗尽转人工——场景设计不可行须人工重审验证方案"),
        )
        steps.append(
            f"修订次数已达上限（{revision_count}/{SCENARIO_REVISION_MAX_COUNT}），"
            f"拒绝修订并冻结转人工（frozen={fr.get('frozen')}）"
        )
        return {"ok": False, "steps": steps,
                "error": (f"场景修订次数达上限（{SCENARIO_REVISION_MAX_COUNT}），"
                          "已冻结转人工"), "frozen_manual": True}

    # 3. 夹具路径白名单（先校验全部路径再动盘——任一非法即整体拒绝）
    fixture_paths = [str(f.get("path") or "") for f in fixture_files
                     if isinstance(f, dict)]
    whitelist_error = validate_scenario_revision_paths(proot, fixture_paths)
    if whitelist_error:
        return {"ok": False, "steps": steps, "error": whitelist_error,
                "frozen_manual": False}

    # 4. 场景结构预校验（validate_scenario_dicts 返回逐条错误清单）
    errors = validate_scenario_dicts(scenarios)
    if errors:
        return {"ok": False, "steps": steps,
                "error": "场景定义校验失败：" + "；".join(errors[:3]),
                "frozen_manual": False}

    # 5. 落盘公共骨架（写前快照 + 失败回滚，item 97da350709f7）：docstring
    # 承诺「任一步失败即停，不留半改状态」——夹具与场景成对文件写入前逐
    # 文件快照，任一步失败按快照回滚本轮已写文件（仿 _exec_untrack_stray_wip
    # 的 gi_backup/_abort 骨架），不留半改夹具与「新一个旧一个」成对撕裂对。
    written: list = []  # 本轮已落盘 (Path, 写前 bytes|None)，失败按此回滚

    def _rollback_written() -> int:
        n = len(written)
        for path, snap in reversed(written):
            try:
                if snap is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(snap)
            except OSError as e:
                # 回滚尽力而为：失败仅留痕，不掩盖原始失败原因
                logger.warning(
                    "revise_scenario_reverify 回滚 %s 失败: %s: %s",
                    path, type(e).__name__, e,
                )
        written.clear()
        return n

    # 5a. 夹具文件落盘（project_root 锚定；路径已过白名单）
    for item in fixture_files:
        rel = str(item.get("path") or "").strip()
        target = proot / rel
        try:
            snap = target.read_bytes() if target.exists() else None
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(target, str(item.get("content") or ""))
            written.append((target, snap))
            steps.append(f"已写夹具文件 {rel}")
        except OSError as e:
            logger.warning(
                "revise_scenario_reverify 写夹具文件失败（spec=%s path=%s）: %s: %s",
                spec, rel, type(e).__name__, e,
            )
            rolled = _rollback_written()
            if rolled:
                steps.append(f"夹具写入失败，已回滚本轮已写文件（{rolled} 个）")
            return {"ok": False, "steps": steps,
                    "error": f"夹具文件写入失败：{rel}", "frozen_manual": False}

    # 5b. 场景集成对落盘（同覆盖 test_scenarios.json 与 _scenarios_full.json）。
    # 两次独立原子写按「先 _scenarios_full 后 test_scenarios」固定顺序（对账
    # 回填以 test_scenarios.json 为权威源，后写使中断撕裂对收敛回旧一致态而
    # 非触发既有回填缺陷）；第二次写失败时按快照回滚成对两文件。
    versioned = prepare_scenarios_for_write(scenarios)
    vp_dir = proot / ".fenix" / "verify-progress" / spec
    try:
        vp_dir.mkdir(parents=True, exist_ok=True)
        body = json.dumps(versioned, ensure_ascii=False, indent=2)
        for pair_path in (vp_dir / "_scenarios_full.json",
                          vp_dir / "test_scenarios.json"):
            snap = pair_path.read_bytes() if pair_path.exists() else None
            atomic_write_text(pair_path, body)
            written.append((pair_path, snap))
    except (OSError, TypeError, ValueError) as e:
        logger.warning(
            "revise_scenario_reverify 场景落盘失败（spec=%s）: %s: %s",
            spec, type(e).__name__, e,
        )
        rolled = _rollback_written()
        if rolled:
            steps.append(f"场景落盘失败，已回滚本轮已写文件（{rolled} 个，"
                         "含成对定义文件，不留撕裂对）")
        return {"ok": False, "steps": steps,
                "error": "修订场景集落盘失败（成对定义文件写入异常）",
                "frozen_manual": False}
    steps.append(f"已修订场景集（{len(versioned)} 条，成对覆盖 "
                 "test_scenarios.json 与 _scenarios_full.json）")

    # 6+7. STATE：计数 +1、置 re-entry 旗标、清停车字段、解冻、testing、唤醒
    sm = _sm(proot)
    updates = dict(_RETRY_COUNTER_RESETS)
    updates.update({
        SCENARIO_REVISION_COUNT_FIELD: revision_count + 1,
        # 旗标在 _RETRY_COUNTER_RESETS 里被清 False，此处覆盖置位——顺序敏感
        SCENARIO_REVISION_PENDING_FIELD: True,
        "frozen": False,
        "error": None,
    })
    if not sm.update_spec(spec, updates):
        return {"ok": False, "steps": steps,
                "error": "修订 STATE 写入未生效（update_spec 拒绝）",
                "frozen_manual": False}
    steps.append(f"已记修订次数（{revision_count + 1}"
                 f"/{SCENARIO_REVISION_MAX_COUNT}）并置修订重验旗标")
    old_status = entry.get("status")
    if old_status == "testing":
        steps.append("spec 已在 testing，无需状态转换")
    elif old_status == "implemented":
        if not sm.transition(spec, "testing", channel="manual"):
            return {"ok": False, "steps": steps,
                    "error": "修订后状态转换未生效（IMPLEMENTED→TESTING 被拒）",
                    "frozen_manual": False}
        steps.append("IMPLEMENTED→TESTING 门禁转换（channel=manual）")
    else:
        # 冻结/blocked 等形态经显式豁免通道直改（force_advance 同款：updates
        # 自带 frozen 键过冻结剥离守卫），留 Transition 痕
        if not sm.update_spec(spec, {"status": "testing"}):
            return {"ok": False, "steps": steps,
                    "error": f"状态 {old_status} → testing 直改未生效",
                    "frozen_manual": False}
        sm.logger.info(
            "state_machine",
            f"Transition: {spec} {old_status} → testing",
            {"channel": "manual", "note": "场景修订重验出口（revise_scenario_reverify）"},
        )
        steps.append(f"{old_status} → testing 显式豁免通道（修订重验）")
    steps.append("重派 verifier 重验" + _kick_step_suffix(proot, spec))
    if payload.get("reason"):
        steps.append(f"修订依据：{payload.get('reason')}")
    return {"ok": True, "steps": steps, "error": None, "frozen_manual": False}


# ── 主树散件 WIP 提交（evo-add-commit-stray-wip-choice 2.1）──────────────

# signal_type 绑定守卫单源（design D4）：commit_stray_wip 是 admin_actions
# 首个对主树执行 git 写的执行器（现存执行器只动 spec 状态机/配置），而
# resolve_choice 对未注册信号存在「非 spec_scoped 动作全表反查放行」通道
# （adjudication_choices.resolve_choice 解析序 2）——注册为非作用域动作后，
# 任意未注册 signal_type（含姊妹 info 信号 maintree_untracked_stray_stale）
# 都能解析到它。执行器 MUST 校验 signal_type 与本常量全等，其余一律拒绝
# （零 git 写），把 git 写暴露面收口到 maintree_stray_wip_stale。
COMMIT_STRAY_WIP_SIGNAL_TYPE = "maintree_stray_wip_stale"


def parse_stray_wip_manifest(evidence) -> list:
    """从信号记录 evidence 解析「文件清单(N):」段（stray_wip 内嵌 prose）。

    stray_wip._write_alert 把清单以 ``文件清单(N): a, b;`` 形态内嵌进 evidence
    文本（无结构化字段），本函数按段解析：返回清单内相对路径列表（保序
    去重）；无清单段 / 清单为「无」→ 空列表。只做段级文本解析，不做路径
    合法性裁决（合法性由调用方以「清单 ∩ 当刻 git status」求交保证）。
    """
    m = re.search(r"文件清单\(\d+\):\s*([^;]+)", str(evidence or ""))
    if not m:
        return []
    raw = m.group(1).strip()
    if not raw or raw == "无":
        return []
    out: list = []
    for item in raw.split(","):
        p = item.strip()
        if p and p not in out:
            out.append(p)
    return out


def _git_out(project_root, *args: str) -> str:
    """在 project_root 跑 git 命令，返回 stdout；非零退出抛 RuntimeError。

    固化解码口径 + 超时（code-review item f4c753f87e84）：text=True 缺省按
    随 locale 的默认编码解码，消费面含 ``status --porcelain -z`` /
    ``ls-files -z``（-z 对非 ASCII 路径原样输出字节），非 UTF-8 locale 下
    抛 UnicodeDecodeError——pipeline._fix_diff_files 同形态实测事故，修法
    对齐其 code-review item de067b5e1d70（encoding="utf-8"+errors="replace"）；
    无 timeout 时索引锁被占/hook 挂起会无限阻塞调用线程（alert-resolve/
    admin 处置端点所在线程），取 30s（与 _path_already_ignored 同口径），
    超时抛 RuntimeError 由各调用方既有 except 分支兜底。
    """
    try:
        r = subprocess.run(
            ["git", "-C", str(project_root), *args],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"git 命令超时（30s）: {' '.join(args[:2])}") from e
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[:300])
    return r.stdout


def _git_status_paths(project_root) -> set:
    """当刻 ``git status --porcelain -z`` 涉及路径集（-z 免引号；含 rename 双侧）。"""
    tokens = _git_out(project_root, "status", "--porcelain", "-z").split("\0")
    paths: set = set()
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        i += 1
        # porcelain v1 行形态 ``XY <path>``（XY 两状态字符 + 空格）；rename/
        # copy 的 orig path 跟随在独立 NUL 字段（无 XY 前缀），显式消费。
        if len(tok) >= 4 and tok[2] == " ":
            paths.add(tok[3:])
            if tok[0] in ("R", "C") and i < len(tokens):
                paths.add(tokens[i])
                i += 1
    return paths


def _latest_stray_wip_manifest(project_root, signal_type: str) -> list:
    """store 内最新一条含可解析清单的 signal_type SIGNAL 记录 → 文件清单。

    strays 执行器（commit/untrack）共用的清单单源：read_all 倒序返回，取
    最新可解析记录；无匹配记录 / store 不可读 → 空列表（调用方按「无清单
    不执行 git 写」处置）。
    """
    from core.admin_store import SIGNAL, AdminStore

    try:
        records = AdminStore(Path(project_root), logger=None).read_all()
    except Exception:
        return []
    for rec in records:
        if (rec.get("kind") != SIGNAL
                or rec.get("signal_type") != signal_type):
            continue
        manifest = parse_stray_wip_manifest(rec.get("evidence"))
        if manifest:
            return manifest
    return []


def _exec_commit_stray_wip(project_root, note: str = "", signal_type: str = "",
                           paths=None) -> dict:
    """commit_stray_wip：提交主树信号清单内的散件 WIP（全局信号专用）。

    约束（design D2/D4）：
    - signal_type 绑定守卫：仅 maintree_stray_wip_stale 可触达（其余信号类型
      ——含未注册信号与姊妹信号 maintree_untracked_stray_stale——一律拒绝，
      零 git 写）；
    - 文件来源 MUST 限信号记录 evidence 的「文件清单(N):」段与当刻
      ``git status --porcelain`` 的交集，拒任意路径；清单中已不在当刻 status
      的文件跳过不报错（同指纹一次性告警，清单会陈旧）；交集内未跟踪条目
      不随本动作提交（pathspec 提交对未跟踪文件必 fatal），提示走
      untrack_stray_wip；交集为空返回明确 error、不产生空提交；
    - 非 destructive（提交可回溯），无需确认门；成功结果附提交 hash。

    paths 仅供程序化调用方显式收窄提交范围（MUST 为清单子集，清单外路径
    拒绝，零 git 写）；缺省从 store 内最新一条含可解析清单的
    maintree_stray_wip_stale SIGNAL 记录解析（同指纹一次性告警语义下在途
    记录至多一条；execute_adjudication_choice 契约不携带告警 id，故按记录
    自取）。提交经 pathspec 形态（``git commit -- <paths>``）：只落清单内
    路径的工作区内容，不裹挟索引中其它暂存改动。
    """
    from core.admin_store import SIGNAL, AdminStore

    # D4 绑定守卫：在任何 git 读/写之前 fail-closed。
    sig = str(signal_type or "").strip()
    if sig != COMMIT_STRAY_WIP_SIGNAL_TYPE:
        return {
            "ok": False, "steps": [],
            "error": (f"signal_type '{sig or '缺失'}' 不可执行 commit_stray_wip"
                      f"（仅限 {COMMIT_STRAY_WIP_SIGNAL_TYPE}；git 写暴露面"
                      f"收口到本信号，design D4）"),
        }

    proot = Path(project_root)
    # 清单单源：信号记录 evidence 清单段（拒任意路径）。
    manifest = _latest_stray_wip_manifest(proot, COMMIT_STRAY_WIP_SIGNAL_TYPE)
    if not manifest:
        return {
            "ok": False, "steps": [],
            "error": ("未找到含可解析文件清单的 maintree_stray_wip_stale 信号"
                      "记录（清单解析自记录 evidence「文件清单(N):」段），"
                      "不执行 git 写"),
        }

    # 显式 paths 白名单校验：清单外路径拒绝（零 git 写）。
    if paths is not None:
        requested = [str(p).strip() for p in paths if str(p).strip()]
        outside = [p for p in requested if p not in manifest]
        if outside:
            return {
                "ok": False, "steps": [],
                "error": ("拒绝清单外路径（文件来源 MUST 限信号记录清单，"
                          f"design D2）：{', '.join(outside)}；"
                          f"信号清单({len(manifest)}): {', '.join(manifest)}"),
            }
        candidates = requested
    else:
        candidates = list(manifest)

    # 与当刻 git status 求交：清单中已不在当刻 status 的文件跳过不报错。
    try:
        dirty = _git_status_paths(proot)
    except RuntimeError as e:
        return {"ok": False, "steps": [], "error": f"读取 git status 失败: {e}"}
    to_commit = [p for p in candidates if p in dirty]
    skipped = [p for p in candidates if p not in dirty]
    if not to_commit:
        return {
            "ok": False, "steps": [],
            "error": ("信号清单内文件已全部不在当刻工作区改动中（同指纹一次性"
                      "告警，清单陈旧），不产生空提交；"
                      f"清单({len(manifest)}): {', '.join(manifest)}"),
        }

    # 未跟踪分流（code-review item 48fc7cf0837c）：porcelain 交集自然混入
    # 未跟踪（??）条目，而 ``git commit -- <path>`` 对未跟踪文件报 fatal
    # 「pathspec did not match any file(s) known to git」，任一未跟踪项即
    # 整批提交放弃。tracked/未跟踪两态分流：只提交 tracked 子集；未跟踪
    # 散件按分工走 untrack_stray_wip（出库+ignore 根治，对已脱离索引条目
    # 幂等跳过），此处提示不报错。
    try:
        indexed = {p for p in _git_out(proot, "ls-files", "-z").split("\0") if p}
    except RuntimeError as e:
        return {"ok": False, "steps": [], "error": f"读取 git 索引失败: {e}"}
    untracked = [p for p in to_commit if p not in indexed]
    to_commit = [p for p in to_commit if p in indexed]
    if not to_commit:
        return {
            "ok": False, "steps": [],
            "error": ("信号清单∩当刻改动内文件均未被 git 跟踪（未跟踪散件按"
                      "分工应走 untrack_stray_wip），不产生提交；"
                      f"清单({len(manifest)}): {', '.join(manifest)}"),
        }

    try:
        msg = (f"[fenix] admin: 提交主树散件 WIP"
               f"（{COMMIT_STRAY_WIP_SIGNAL_TYPE} 信号清单内 "
               f"{len(to_commit)} 文件）")
        if note:
            msg += f"\n\n裁决依据：{note}"
        _git_out(proot, "commit", "-m", msg, "--", *to_commit)
        # pathspec 锚定读哈希（code-review item 7fe327348b37，同
        # archive_commit.commit_archive_move / queue.py 既有口径：不用
        # rev-parse HEAD，防 commit→读取窗口内并发提交记到别人头上，审计
        # 追溯失真）。
        commit_hash = _git_out(
            proot, "log", "-1", "--format=%H", "--", *to_commit,
        ).strip()
    except RuntimeError as e:
        return {"ok": False, "steps": [], "error": f"git 提交失败: {e}"}
    steps = [
        f"提交主树散件 WIP {len(to_commit)} 个文件（信号清单∩当刻改动）："
        f"{', '.join(to_commit)}",
        f"提交 hash: {commit_hash}",
    ]
    if skipped:
        steps.append(
            f"清单内已不在当刻改动、跳过 {len(skipped)} 个：{', '.join(skipped)}"
        )
    if untracked:
        steps.append(
            f"清单内未跟踪散件 {len(untracked)} 个不随本动作提交"
            f"（pathspec 提交仅限 tracked；走 untrack_stray_wip 根治）："
            f"{', '.join(untracked)}"
        )
    if note:
        steps.append(f"裁决依据：{note}")
    return {
        "ok": True, "steps": steps, "error": None,
        "commit_hash": commit_hash,
        "committed_files": to_commit,
    }


# ── 主树复发型散件根治 untrack（evo-recurring-stray-remediation 1.2）──────

# signal_type 绑定守卫单源：与 commit_stray_wip 同一信号（design D4 同款
# 收口逻辑——resolve_choice 非作用域全表反查通道对本动作同样可达，执行器
# MUST 校验 signal_type 后才落 git 写）。
UNTRACK_STRAY_WIP_SIGNAL_TYPE = COMMIT_STRAY_WIP_SIGNAL_TYPE


def _path_already_ignored(proot, path: str) -> bool:
    """path 是否已被既有 ignore 规则覆盖（check-ignore --no-index 口径）。

    tracked 文件的普通 check-ignore 恒为非忽略（误报，stash_guard 同款教训），
    ``--no-index`` 只按 ignore 规则判定。git 不可用/超时按「未忽略」处理
    （保守追加，去重由字面行比对兜底）。
    """
    try:
        r = subprocess.run(
            ["git", "-C", str(proot), "check-ignore", "--no-index", "-q", "--", path],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return r.returncode == 0


def _append_gitignore_entries(proot, paths) -> list:
    """把 paths 逐条追加进 .gitignore（去重），返回实际新增条目列表。

    去重双重口径：条目字面行已在 .gitignore → 不重复写（幂等重入不增行）；
    ``check-ignore --no-index`` 判定已被既有规则覆盖（如通配 ``*.log``）→
    追加亦冗余，不写。.gitignore 不存在则新建。
    """
    gi = Path(proot) / ".gitignore"
    existing = gi.read_text(encoding="utf-8", errors="replace") if gi.exists() else ""
    have_lines = {ln.strip() for ln in existing.splitlines()}
    appended: list = []
    for p in paths:
        if p in have_lines or _path_already_ignored(proot, p):
            continue
        appended.append(p)
        have_lines.add(p)
    if appended:
        sep = "" if (not existing or existing.endswith("\n")) else "\n"
        # 原子写回（code-review item c971a8de0638）：裸 write_text 非原子，
        # 进程中断/磁盘满可留下截断的 .gitignore（仓库忽略规则整体丢失面）
        # ——gi_backup 只覆盖 _abort 显式回滚路径，不覆盖写半程中断。改走
        # scenario_gate.atomic_write_text（tmp+replace，模块内其余文件写入
        # 同款）。
        from core.pm_engine.verification.scenario_gate import atomic_write_text

        atomic_write_text(gi, existing + sep + "\n".join(appended) + "\n")
    return appended


def _exec_untrack_stray_wip(project_root, note: str = "", signal_type: str = "",
                            paths=None) -> dict:
    """untrack_stray_wip：主树复发型散件当场根治（git rm --cached + .gitignore）。

    对告警指认文件清单执行出库 + ignore 规则追加 + 独立提交（design D4：
    untrack 与 .gitignore 追加原子成一批独立提交，不与处置中其他改动混合，
    可整体 revert 回滚）。约束：

    - signal_type 绑定守卫（design D4，同 _exec_commit_stray_wip）：仅
      maintree_stray_wip_stale 可触达，其余一律拒绝、零 git 写；
    - 文件来源 MUST 限信号记录 evidence「文件清单(N):」段（拒任意路径）；
      与当刻 git status 与索引求交——已不在 status 的跳过（清单陈旧）；仍在
      status 但已脱离索引的视为已根治过，跳过不报错（幂等重入）；可执行
      集合为空返回明确 error、不产生空提交；
    - 复用 stash_guard staged 子集守卫/回滚骨架：rm 循环 → staged 子集守卫
      （口径与 ``_untrack_index_paths`` 一致，额外放行 .gitignore——根治
      提交的另一半；staged 名单同源反转义）→ 裸 commit；回滚段复用
      ``G6StashGuardMixin._reset_index_paths``（经 _UntrackGuardProbe 最小
      宿主），追加的 .gitignore 一并还原（暂存态 reset + 文件内容恢复），
      任何中止分支不残留半程改动。不打开 stash_guard「check-ignore 全须
      忽略」前置门（design D1）。不能用 ``commit -- <paths>`` 限定：路径已
      被 rm --cached 移出 index，pathspec 解析必 fatal（stash_guard 同款
      教训），故裸 commit + staged 子集守卫。

    paths 仅供程序化调用方显式收窄作用面（MUST 为清单子集，清单外拒绝，
    零 git 写）；缺省取 store 内最新一条含可解析清单的 maintree_stray_wip_stale
    SIGNAL 记录（execute_adjudication_choice 契约不携带告警 id，同
    commit 执行器按记录自取）。结果记录 untrack 文件清单（untracked_files）、
    .gitignore 实际新增条目（gitignore_appended）与提交号（commit_hash）。
    """
    # D4 绑定守卫：在任何 git 读/写之前 fail-closed。
    sig = str(signal_type or "").strip()
    if sig != UNTRACK_STRAY_WIP_SIGNAL_TYPE:
        return {
            "ok": False, "steps": [],
            "error": (f"signal_type '{sig or '缺失'}' 不可执行 untrack_stray_wip"
                      f"（仅限 {UNTRACK_STRAY_WIP_SIGNAL_TYPE}；git 写暴露面"
                      f"收口到本信号，design D4）"),
        }

    proot = Path(project_root)
    # 清单单源：信号记录 evidence 清单段（拒任意路径）。
    manifest = _latest_stray_wip_manifest(proot, UNTRACK_STRAY_WIP_SIGNAL_TYPE)
    if not manifest:
        return {
            "ok": False, "steps": [],
            "error": ("未找到含可解析文件清单的 maintree_stray_wip_stale 信号"
                      "记录（清单解析自记录 evidence「文件清单(N):」段），"
                      "不执行 git 写"),
        }

    # 显式 paths 白名单校验：清单外路径拒绝（零 git 写）。
    if paths is not None:
        requested = [str(p).strip() for p in paths if str(p).strip()]
        outside = [p for p in requested if p not in manifest]
        if outside:
            return {
                "ok": False, "steps": [],
                "error": ("拒绝清单外路径（文件来源 MUST 限信号记录清单，"
                          f"design D2）：{', '.join(outside)}；"
                          f"信号清单({len(manifest)}): {', '.join(manifest)}"),
            }
        candidates = requested
    else:
        candidates = list(manifest)

    # 与当刻 git status / 索引求交：三态分流。
    try:
        dirty = _git_status_paths(proot)
        indexed = {p for p in _git_out(proot, "ls-files", "-z").split("\0") if p}
    except RuntimeError as e:
        return {"ok": False, "steps": [], "error": f"读取 git 状态失败: {e}"}
    to_untrack = [p for p in candidates if p in dirty and p in indexed]
    skipped_stale = [p for p in candidates if p not in dirty]
    already_untracked = [p for p in candidates if p in dirty and p not in indexed]
    if not to_untrack:
        return {
            "ok": False, "steps": [],
            "error": ("信号清单内文件均已不在 git 索引（已根治过或已删除），"
                      f"无需重复执行 untrack；清单({len(manifest)}): "
                      f"{', '.join(manifest)}"),
        }

    gi_path = proot / ".gitignore"
    gi_backup = gi_path.read_bytes() if gi_path.exists() else None

    # 复用 stash_guard 回滚子函数的最小宿主（code_fix._main_tree_dirty_files
    # 的 ``_Probe(G6StashGuardMixin)`` 先例：完整 WorktreeManager 装配是死重；
    # 函数级 import 规避装载环）。不打开 stash_guard「check-ignore 全须忽略」
    # 前置门（design D1：目标生成物文件本就不被 ignore，独立执行器作用面
    # 限告警指认清单，误伤面最小）。
    from core.worktree_manager.stash_guard import G6StashGuardMixin
    from core.worktree_manager.mergeback import _unquote_git_path

    class _StashGuardTagLogger:
        """标准 logging → stash_guard ``(tag, msg)`` 双参口径适配。

        stash_guard 自愈骨架以 ``self.logger.warning("worktree_manager", msg)``
        双参口径写日志（Fenix 项目 logger 形态）；本模块 logger 是标准
        logging，直传会把 msg 当 % 参数——适配器折回单参格式化。
        """

        def __init__(self, base):
            self._base = base

        def warning(self, tag, msg):
            self._base.warning("%s: %s", tag, msg)

    class _UntrackGuardProbe(G6StashGuardMixin):
        """仅承载 project_root/logger 的守卫探针壳（回滚子函数宿主）。"""

        def __init__(self, pr, base_logger):
            self.project_root = Path(pr)
            self.logger = _StashGuardTagLogger(base_logger)

    probe = _UntrackGuardProbe(proot, logger)
    processed: list = []   # 已成功 rm --cached 的路径（中止按此回滚索引态）
    appended: list = []    # 已写入 .gitignore 的条目（中止一并还原）

    def _abort(reason: str) -> dict:
        rollback = list(processed)
        if appended:
            rollback.append(".gitignore")
        # 回滚段复用 stash_guard 骨架（_reset_index_paths：只重置索引不动
        # 工作区；尽力而为，失败仅记 warning 不掩盖原始原因）。
        probe._reset_index_paths(rollback)
        if appended:
            if gi_backup is None:
                gi_path.unlink(missing_ok=True)
            else:
                # 原子写回（code-review item 55aaffc3e33b，与
                # _append_gitignore_entries / _append_gitignore_and_commit
                # 走 atomic_write_text 同口径）：裸 write_bytes 非原子，
                # 还原时刻恰逢进程被杀/磁盘满会留下截断的 .gitignore
                # （仓库忽略规则整体丢失面）。
                from core.pm_engine.verification.scenario_gate import atomic_write_text

                atomic_write_text(
                    gi_path, gi_backup.decode("utf-8", errors="replace"),
                )
        return {"ok": False, "steps": [],
                "error": f"untrack 根治中止已回滚（主树状态已还原）: {reason}"}

    try:
        for path in to_untrack:
            _git_out(proot, "rm", "-f", "--cached", "--", path)
            processed.append(path)
        appended = _append_gitignore_entries(proot, to_untrack)
        if appended:
            _git_out(proot, "add", "--", ".gitignore")
        # staged 子集守卫（stash_guard._untrack_index_paths 同口径）：裸
        # commit 会把索引里其它 staged 条目连带入库，校验暂存集 ⊆ 本次
        # untrack 路径 ∪ {.gitignore}，越界先回滚再放弃。名单反转义：diff
        # --cached 对非 ASCII 路径默认输出 C-quoted 转义形。
        staged_out = _git_out(proot, "diff", "--cached", "--name-only", "HEAD")
        staged_set = {_unquote_git_path(ln) for ln in staged_out.splitlines()}
        allowed = set(to_untrack) | ({".gitignore"} if appended else set())
        if not staged_set <= allowed:
            return _abort(
                "索引存在本次作用面之外的暂存条目: "
                f"{sorted(staged_set - allowed)}"
            )
        msg = (f"[fenix] admin: 根治主树复发型散件"
               f"（untrack_stray_wip 出库 {len(to_untrack)} 文件）")
        if note:
            msg += f"\n\n裁决依据：{note}"
        _git_out(proot, "commit", "-m", msg)
        # pathspec 锚定读哈希（code-review item 7fe327348b37，同
        # _exec_commit_stray_wip / archive_commit.commit_archive_move 口径）：
        # 提交本体因 rm --cached 后 pathspec 解析必 fatal 而只能裸 commit
        # （stash_guard 同款教训），读哈希按被出库路径锚定，同样防
        # commit→读取窗口内并发提交记到别人头上。
        commit_hash = _git_out(
            proot, "log", "-1", "--format=%H", "--", *to_untrack,
        ).strip()
    except (subprocess.TimeoutExpired, OSError) as e:
        return _abort(f"git 执行异常: {e}")
    except RuntimeError as e:
        return _abort(str(e))

    steps = [
        f"untrack 出库 {len(to_untrack)} 个文件（信号清单∩当刻改动∩索引）："
        f"{', '.join(to_untrack)}",
    ]
    if appended:
        steps.append(f".gitignore 追加 {len(appended)} 条（去重后实际新增）: "
                     f"{', '.join(appended)}")
    else:
        steps.append(".gitignore 无需追加（既有规则已覆盖或条目已存在）")
    steps.append(f"提交 hash: {commit_hash}")
    if skipped_stale:
        steps.append(
            f"清单内已不在当刻改动、跳过 {len(skipped_stale)} 个: "
            f"{', '.join(skipped_stale)}"
        )
    if already_untracked:
        steps.append(
            f"清单内已脱离索引（已根治过）、跳过 {len(already_untracked)} 个: "
            f"{', '.join(already_untracked)}"
        )
    if note:
        steps.append(f"裁决依据：{note}")
    return {
        "ok": True, "steps": steps, "error": None,
        "commit_hash": commit_hash,
        "untracked_files": to_untrack,
        "gitignore_appended": appended,
    }


# ── 主树 untracked 散件认领（evo-stray-untracked-escalation 3.1）──────────

# signal_type 绑定白名单单源（design D4 同款收口逻辑）：认领执行器是主树
# git 写/文件删除的暴露面，白名单仅收录升级信号——姊妹 info 信号
# （maintree_untracked_stray_stale）与 tracked 桶信号（maintree_stray_wip_stale
# 等）一律拒绝、零 git 写零文件触碰。evidence 清单段解析复用
# parse_stray_wip_manifest（升级信号 evidence 与 info 前身同段级格式，仅指
# 解析器复用，不将 info 信号放行为执行目标）。
UNTRACKED_CLAIM_SIGNAL_TYPES = ("maintree_untracked_stray_escalated",)

# 显式归档登记目录（相对 project_root）：归档裁决把清单内散件移入该目录的
# UTC 时间戳子目录（保留清单内相对路径结构），并把登记目录本身追加进
# .gitignore——归档是「已认领存放」语义，登记目录 MUST NOT 计入后续
# untracked 盘点（无忽略规则的项目否则会把归档产物再当散件告警，裁决自我
# 循环）；.gitignore 追加以 pathspec 独立提交落地（可整体 revert）。
UNTRACKED_STRAY_ARCHIVE_DIR = ".fenix/stray-archive"


def _claim_untracked_manifest(project_root, signal_type: str, paths=None) -> dict:
    """认领执行器共用前置：绑定守卫 → 清单单源 → 显式 paths 白名单校验。

    binding 守卫在任何 git 读/写之前 fail-closed（spec「tracked 信号拒绝零
    git 写」验收口径）；manifest 解析只读 AdminStore（零 git 零文件触碰）。
    paths 仅供程序化调用方显式收窄作用面（MUST 为清单子集，清单外拒绝），
    语义对齐 commit/untrack 执行器同款 D2 约束。

    Returns: {"manifest": [...], "candidates": [...], "error": str}
    error 非空时调用方原样返回失败结果（零 git 写、零文件触碰）。
    """
    sig = str(signal_type or "").strip()
    if sig not in UNTRACKED_CLAIM_SIGNAL_TYPES:
        return {
            "manifest": [], "candidates": [],
            "error": (f"signal_type '{sig or '缺失'}' 不可执行 untracked 散件"
                      f"认领（白名单仅限 {', '.join(UNTRACKED_CLAIM_SIGNAL_TYPES)}；"
                      "tracked 桶与 info 信号零 git 写零文件触碰，design D4）"),
        }
    proot = Path(project_root)
    manifest = _latest_stray_wip_manifest(proot, UNTRACKED_CLAIM_SIGNAL_TYPES[0])
    if not manifest:
        return {
            "manifest": [], "candidates": [],
            "error": ("未找到含可解析文件清单的 maintree_untracked_stray_escalated "
                      "信号记录（清单解析自记录 evidence「文件清单(N):」段），"
                      "不执行认领写"),
        }
    if paths is not None:
        requested = [str(p).strip() for p in paths if str(p).strip()]
        outside = [p for p in requested if p not in manifest]
        if outside:
            return {
                "manifest": [], "candidates": [],
                "error": ("拒绝清单外路径（文件来源 MUST 限信号记录清单，"
                          f"design D2）：{', '.join(outside)}；"
                          f"信号清单({len(manifest)}): {', '.join(manifest)}"),
            }
        candidates = requested
    else:
        candidates = list(manifest)
    return {"manifest": manifest, "candidates": candidates, "error": ""}


def _append_gitignore_and_commit(proot, entries, header: str) -> dict:
    """追加 .gitignore 并以 pathspec 独立提交落地（认领裁决共用）。

    pathspec 形态（``git commit -- .gitignore``，commit_stray_wip 同款）：
    只落 .gitignore 的工作区内容，不裹挟索引中其它暂存改动——认领裁决
    MUST NOT 制造「索引被裹挟」的新散件。.gitignore 尚未入库时先 add 再
    pathspec 提交（新文件须在索引内 pathspec 才可解析）。提交失败时尽力
    还原追加行（不残留半程改动；还原失败保留现状不掩盖原始原因）。

    Returns: {"appended": [...], "commit_hash": str, "error": str}
    """
    appended = _append_gitignore_entries(proot, entries)
    if not appended:
        return {"appended": [], "commit_hash": "", "error": ""}
    # .gitignore 入库态快照（code-review item 8db336608775）：新文件场景 add
    # 已把 .gitignore 暂存，失败还原分支除回滚工作区内容外还须撤销暂存，
    # 否则残留 staged 半程改动。ls-files 失败时入库态未知，按「已跟踪」保守
    # 处理（不补 reset——git 已异常，再补写只会放大）。
    gitignore_untracked = False
    try:
        tracked = {p for p in _git_out(proot, "ls-files", "-z").split("\0") if p}
        gitignore_untracked = ".gitignore" not in tracked
        if gitignore_untracked:
            _git_out(proot, "add", "--", ".gitignore")
        msg = f"[fenix] admin: {header}（{len(appended)} 条）"
        _git_out(proot, "commit", "-m", msg, "--", ".gitignore")
        # pathspec 锚定读哈希（code-review item 7fe327348b37，同
        # _exec_commit_stray_wip / archive_commit.commit_archive_move 口径：
        # 不用 rev-parse HEAD，防 commit→读取窗口内并发提交记到别人头上）。
        commit_hash = _git_out(
            proot, "log", "-1", "--format=%H", "--", ".gitignore",
        ).strip()
    except RuntimeError as e:
        restore_note = ""
        try:
            gi = proot / ".gitignore"
            kept = [
                ln for ln in
                gi.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
                if ln.strip() not in set(appended)
            ]
            # 原子写回（code-review item 8db336608775，与
            # _append_gitignore_entries 走 atomic_write_text 同口径）：裸
            # write_text 非原子，还原时刻恰逢进程被杀/磁盘满会留下截断的
            # .gitignore（仓库忽略规则整体丢失面）。
            from core.pm_engine.verification.scenario_gate import atomic_write_text

            atomic_write_text(gi, "".join(kept))
        except OSError:
            restore_note = "；.gitignore 还原写回失败（保留现状）"
        if gitignore_untracked:
            try:
                _git_out(proot, "reset", "-q", "--", ".gitignore")
            except RuntimeError as reset_err:
                restore_note += f"；撤销 .gitignore 暂存失败: {reset_err}"
        return {"appended": [], "commit_hash": "",
                "error": (f".gitignore 追加提交失败（已尽力还原追加行"
                          f"{restore_note}）: {e}")}
    return {"appended": appended, "commit_hash": commit_hash, "error": ""}


def _stray_manifest_path_escapes(proot, paths) -> list:
    """清单路径「相对且不越出项目根」纵深校验，返回不合规条目（空=全部合法）。

    清单解析自告警 evidence 文本段（parse_stray_wip_manifest 只做段级文本
    解析，不做路径合法性裁决），绝对路径条目会使 ``proot / p`` 整体替换基准
    路径、含 ``..`` 条目可指向项目根之外（code-review item a2e84e9e166c）。
    同模块先例防线：夹具写入走 validate_scenario_revision_paths 白名单、
    spec 名拼路径走 kebab-case 正则；散件路径散布全仓、不在任何目录白名单
    内，故只取其绝对路径/穿越规则做同型校验，白名单目录约束不适用。
    """
    base = os.path.realpath(os.path.abspath(str(proot)))
    bad: list = []
    for raw in paths or []:
        p = str(raw or "").strip()
        if not p or p.startswith("~") or os.path.isabs(p) or ":" in p.split("/")[0]:
            bad.append(p)
            continue
        norm = os.path.normpath(p)
        if norm == "." or norm.startswith(".."):
            bad.append(p)
            continue
        # realpath 前缀断言：解析后必须仍落在项目根之内（顺带挡住中间目录为
        # 指向项目外符号链接的形态）。
        anchored = os.path.realpath(os.path.join(base, norm))
        if anchored != base and not anchored.startswith(base + os.sep):
            bad.append(p)
    return bad


def _exec_archive_untracked_stray(project_root, note: str = "", signal_type: str = "",
                                  paths=None) -> dict:
    """archive_untracked_stray：显式归档——清单内散件移入登记目录（全局信号专用）。

    约束（design D4 同款收口）：
    - signal_type 绑定白名单（UNTRACKED_CLAIM_SIGNAL_TYPES）：仅
      maintree_untracked_stray_escalated 可触达，tracked 桶与 info 信号一律
      拒绝，零 git 写零文件触碰；
    - 文件来源 MUST 限信号记录 evidence「文件清单(N):」段（拒任意路径）；
    - 归档落点 .fenix/stray-archive/<UTC时间戳>/（保留相对路径结构）；登记
      目录先追加 .gitignore 并独立提交（幂等，重入去重），再逐文件移动——
      已移动文件不回拉（移动是逐文件原子操作，留在登记目录属已认领态），
      失败如实上报、重试续移剩余文件；
    - 清单内已不在磁盘的文件跳过不报错（同指纹一次性告警，清单会陈旧）；
      可归档集合为空返回明确 error。移动前 ls-files 复核 untracked 身份
      （code-review item 6715a1facae4，同 commit/untrack 执行器）并对清单
      条目做相对路径/越界校验（code-review item a2e84e9e166c）：已变
      tracked 与绝对路径/穿越条目一并跳过（tracked 文件移动＝git 可见删改）。
    """
    pre = _claim_untracked_manifest(project_root, signal_type, paths)
    if pre["error"]:
        return {"ok": False, "steps": [], "error": pre["error"]}
    proot = Path(project_root)
    # 路径纵深校验（code-review item a2e84e9e166c，_stray_manifest_path_escapes
    # 同型防线）：不合规条目剔除、不阻断其余合规条目。
    escapes = _stray_manifest_path_escapes(proot, pre["candidates"])
    compliant = [p for p in pre["candidates"] if p not in escapes]
    # 三态分流（code-review item f7c915465d1d，与 delete 执行器的显式非普通
    # 文件分支对齐）：在盘但非普通文件（目录等）单列跳过原因，不落入「已不
    # 在磁盘」口径——条目实际在盘，只是不满足普通文件归档条件。
    existing, skipped, not_plain = [], [], []
    for p in compliant:
        f = proot / p
        if not f.exists():
            skipped.append(p)
        elif not f.is_file():
            not_plain.append(p)
        else:
            existing.append(p)
    # tracked 复核防线（code-review item 6715a1facae4，同 commit/untrack 执行器
    # 的 ls-files 求交）：清单+磁盘存在不代表仍 untracked——同指纹一次性告警的
    # 清单会陈旧，文件可能在告警后已被 commit_stray_wip 等途径提交跟踪（同一
    # 信号下并排裁决动作的先后组合）；对 tracked 路径执行移动会制造 git 可见
    # 的删改，违背「零 git 写、只动 untracked」契约。
    try:
        indexed = {p for p in _git_out(proot, "ls-files", "-z").split("\0") if p}
    except RuntimeError as e:
        return {"ok": False, "steps": [], "error": f"读取 git 索引失败: {e}"}
    newly_tracked = [p for p in existing if p in indexed]
    existing = [p for p in existing if p not in indexed]
    if not existing:
        err = ("信号清单内文件均已不在磁盘（同指纹一次性告警，清单陈旧），"
               f"无可归档文件；清单({len(pre['manifest'])}): "
               f"{', '.join(pre['manifest'])}")
        if newly_tracked:
            err += f"；其中 {len(newly_tracked)} 个已变 tracked（不执行归档移动）"
        if not_plain:
            err += f"；其中 {len(not_plain)} 个在盘但非普通文件（跳过不触碰）"
        if escapes:
            err += f"；其中 {len(escapes)} 条路径不合规已剔除"
        return {"ok": False, "steps": [], "error": err}
    gi = _append_gitignore_and_commit(
        proot, [f"{UNTRACKED_STRAY_ARCHIVE_DIR}/"], "登记 untracked 散件归档目录",
    )
    if gi["error"]:
        return {"ok": False, "steps": [], "error": gi["error"]}
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    dest_root = proot / UNTRACKED_STRAY_ARCHIVE_DIR / stamp
    moved, failed = [], ""
    try:
        for p in existing:
            dest = dest_root / p
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(proot / p), str(dest))
            moved.append(p)
    except OSError as e:
        failed = f"归档移动失败（已移动 {len(moved)} 个留在登记目录，重试续移）: {e}"
    steps = []
    if gi["appended"]:
        steps.append(
            f"登记目录 {UNTRACKED_STRAY_ARCHIVE_DIR}/ 追加 ignore 并独立提交"
            f"（{gi['commit_hash'][:12]}）"
        )
    else:
        steps.append(f"登记目录 {UNTRACKED_STRAY_ARCHIVE_DIR}/ 已在 ignore 规则内，无需追加")
    steps.append(
        f"归档 {len(moved)} 个 untracked 散件至 {UNTRACKED_STRAY_ARCHIVE_DIR}/{stamp}/"
        f"（保留相对路径）: {', '.join(moved)}"
    )
    if skipped:
        steps.append(f"清单内已不在磁盘、跳过 {len(skipped)} 个: {', '.join(skipped)}")
    if not_plain:
        steps.append(
            f"清单内在盘但非普通文件（目录等）、跳过不触碰 {len(not_plain)} 个"
            f"（不执行归档移动）: {', '.join(not_plain)}"
        )
    if newly_tracked:
        steps.append(
            f"清单内已变 tracked、跳过 {len(newly_tracked)} 个（告警后已被提交"
            f"跟踪，不执行归档移动）: {', '.join(newly_tracked)}"
        )
    if escapes:
        steps.append(
            f"清单内 {len(escapes)} 条路径不合规（绝对路径/越出项目根），"
            f"跳过不触碰: {', '.join(escapes)}"
        )
    if note:
        steps.append(f"裁决依据：{note}")
    if failed:
        steps.append(failed)
        return {"ok": False, "steps": steps, "error": failed}
    return {
        "ok": True, "steps": steps, "error": None,
        "archived_files": moved,
        "archive_dir": f"{UNTRACKED_STRAY_ARCHIVE_DIR}/{stamp}",
        "gitignore_appended": gi["appended"],
        "commit_hash": gi["commit_hash"],
    }


def _exec_ignore_untracked_stray(project_root, note: str = "", signal_type: str = "",
                                 paths=None) -> dict:
    """ignore_untracked_stray：清单内 untracked 路径追加 .gitignore（去重）。

    约束同认领族（白名单守卫/清单单源/pathspec 独立提交）。去重双重口径
    复用 _append_gitignore_entries：条目字面行已存在或既有规则（含通配）
    已覆盖的不重复写。清单内路径无须仍在磁盘（ignore 规则对路径生效）。
    """
    pre = _claim_untracked_manifest(project_root, signal_type, paths)
    if pre["error"]:
        return {"ok": False, "steps": [], "error": pre["error"]}
    proot = Path(project_root)
    gi = _append_gitignore_and_commit(
        proot, pre["candidates"], "追加 untracked 散件 ignore 规则",
    )
    if gi["error"]:
        return {"ok": False, "steps": [], "error": gi["error"]}
    steps = []
    if gi["appended"]:
        steps.append(
            f".gitignore 追加 {len(gi['appended'])} 条（去重后实际新增）: "
            f"{', '.join(gi['appended'])}"
        )
        steps.append(f"独立提交 hash: {gi['commit_hash']}")
    else:
        steps.append(".gitignore 无需追加（既有规则已覆盖或条目已存在）")
    if note:
        steps.append(f"裁决依据：{note}")
    return {
        "ok": True, "steps": steps, "error": None,
        "gitignore_appended": gi["appended"],
        "commit_hash": gi["commit_hash"],
    }


def _exec_delete_untracked_stray(project_root, note: str = "", signal_type: str = "",
                                 paths=None) -> dict:
    """delete_untracked_stray：删除清单内 untracked 散件文件（destructive）。

    约束同认领族。只删普通文件（is_file 门，防御性收口——目录与特殊文件
    拒绝，不 rmtree）；已不在磁盘的跳过不报错，全不存在时明确 error。
    删除前 ls-files 复核 untracked 身份（code-review item 6715a1facae4，同
    archive 执行器）并对清单条目做相对路径/越界校验（code-review item
    a2e84e9e166c）：已变 tracked 与绝对路径/穿越条目跳过不删。零 git 写
    （untracked 文件删除不经 git，ls-files 为只读复核；ignore/登记需求走
    其它两裁决），空目录残留不进 git status、无再告警面，不顺手清理
    （零额外触碰）。
    """
    pre = _claim_untracked_manifest(project_root, signal_type, paths)
    if pre["error"]:
        return {"ok": False, "steps": [], "error": pre["error"]}
    proot = Path(project_root)
    # 路径纵深校验（code-review item a2e84e9e166c，同 archive 执行器）：
    # 不合规条目剔除、不阻断其余合规条目。
    escapes = _stray_manifest_path_escapes(proot, pre["candidates"])
    compliant = [p for p in pre["candidates"] if p not in escapes]
    targets, skipped = [], []
    for p in compliant:
        f = proot / p
        if not f.exists():
            skipped.append(p)
        elif not f.is_file():
            return {
                "ok": False, "steps": [],
                "error": f"拒绝删除非普通文件（防御性收口，仅文件删除）: {p}",
            }
        else:
            targets.append(p)
    # tracked 复核防线（code-review item 6715a1facae4，同 commit/untrack/
    # archive 执行器的 ls-files 求交）：告警后已被提交跟踪的路径不再删除，
    # 否则会把 tracked 文件的工作区副本直接 unlink 制造 git 可见删改。
    try:
        indexed = {p for p in _git_out(proot, "ls-files", "-z").split("\0") if p}
    except RuntimeError as e:
        return {"ok": False, "steps": [], "error": f"读取 git 索引失败: {e}"}
    newly_tracked = [p for p in targets if p in indexed]
    targets = [p for p in targets if p not in indexed]
    if not targets:
        err = ("信号清单内文件均已不在磁盘（同指纹一次性告警，清单陈旧），"
               f"无可删除文件；清单({len(pre['manifest'])}): "
               f"{', '.join(pre['manifest'])}")
        if newly_tracked:
            err += f"；其中 {len(newly_tracked)} 个已变 tracked（不执行删除）"
        if escapes:
            err += f"；其中 {len(escapes)} 条路径不合规已剔除"
        return {"ok": False, "steps": [], "error": err}
    deleted, failed = [], ""
    try:
        for p in targets:
            (proot / p).unlink()
            deleted.append(p)
    except OSError as e:
        # 部分删除如实回传（code-review item a527df01d2de，与 archive 执行器
        # 「已移动 N 个、重试续移」的部分进度口径对齐）：本轮已删清单并入
        # steps，不留对操作者不可见的半程删除状态。
        failed = f"删除失败（已删除 {len(deleted)} 个，重试续删剩余）: {e}"
    steps = [f"删除 {len(deleted)} 个 untracked 散件文件: {', '.join(deleted)}"]
    if skipped:
        steps.append(f"清单内已不在磁盘、跳过 {len(skipped)} 个: {', '.join(skipped)}")
    if newly_tracked:
        steps.append(
            f"清单内已变 tracked、跳过 {len(newly_tracked)} 个（告警后已被提交"
            f"跟踪，不执行删除）: {', '.join(newly_tracked)}"
        )
    if escapes:
        steps.append(
            f"清单内 {len(escapes)} 条路径不合规（绝对路径/越出项目根），"
            f"跳过不触碰: {', '.join(escapes)}"
        )
    if note:
        steps.append(f"裁决依据：{note}")
    if failed:
        steps.append(failed)
        return {"ok": False, "steps": steps, "error": failed}
    return {
        "ok": True, "steps": steps, "error": None,
        "deleted_files": deleted,
    }


def execute_adjudication_choice(project_root, spec: str, choice_id: str,
                                note: str = "", signal_type: str = "") -> dict:
    """choice_id → 后端动作统一映射执行器（add-human-adjudication-choices 4.1/4.2）。

    alert-resolve 端点与 Administrator 处置记录消费共用本执行器：同一动作
    映射、同一留痕格式，自动处置与人工下拉处置收敛为同一裁决空间（D1）。
    action 判定：signal_type 注册表内精确匹配优先；缺 signal_type 上下文时
    按 choice_id 全表反查（同一 id 在各信号下 action 语义一致；spec_scoped
    动作不再兜底放行，fix-global-signal-choice-execution 1.1）。
    作用域守卫（fix-global-signal-choice-execution 1.2）：spec 为空或占位
    'global' 的全局信号拒绝执行 spec_scoped choice；非作用域 choice 不受限。

    本函数只执行动作，不做告警 handled 标记与 disposition 留痕——由调用方
    （端点 / admin 消费路径）按各自通道收口。

    Returns:
        {"ok": bool, "choice_id": str, "action": str, "steps": [str],
         "error": str|null, ...动作附加字段}
    """
    from .adjudication_choices import is_global_spec, resolve_choice

    if not choice_id or not str(choice_id).strip():
        return {"ok": False, "choice_id": choice_id or "", "action": None,
                "steps": [], "error": "choice_id is required"}
    choice_id = str(choice_id).strip()
    sig = str(signal_type or "")
    # choice 解析收敛注册表单源（fix-global-signal-choice-execution 1.1）：
    # 桶内精确匹配 / 未注册信号全表反查（spec_scoped 动作不再兜底放行）同序
    # 同源，执行器与消费端守卫共用一套解析（resolve_choice）。
    choice, reason = resolve_choice(choice_id, sig)
    if choice is None:
        if reason == "not-in-bucket":
            # signal_type 已注册：choice 必须落在该信号选项集内（alert-resolve
            # 契约「按 alert 的 signal_type 校验 choice_id 合法」），不做跨信号放行
            return {"ok": False, "choice_id": choice_id, "action": None,
                    "steps": [],
                    "error": (f"非法 choice_id '{choice_id}'"
                              f"（不在信号 '{sig}' 的选项集内）")}
        if reason == "scoped-no-reverse":
            # 未注册 signal_type × spec 作用域动作：不再经全表反查兜底放行
            # （1.1 收紧）——历史上放行会在执行期才于 parse_state 处报错
            return {"ok": False, "choice_id": choice_id, "action": None,
                    "steps": [],
                    "error": (f"choice_id '{choice_id}' 为 spec 作用域动作，"
                              f"信号 '{sig}' 未注册裁决选项集，"
                              f"不经跨信号全表反查兜底放行")}
        return {"ok": False, "choice_id": choice_id, "action": None, "steps": [],
                "error": f"非法 choice_id '{choice_id}'（注册表无此选项）"}
    action = choice.get("action")
    # 全局信号作用域守卫（fix-global-signal-choice-execution 1.2）：spec 为空
    # 或占位 'global' 的信号无具体 spec 可操作，MUST NOT 执行 spec 作用域动作
    # （2026-10-02 ce27a93f9dca：全局指纹告警选 retry_review，执行器 parse_state
    # 报 spec not found 且同秒信号已被误记 handled）。非作用域 choice 不受影响。
    if choice.get("spec_scoped", True) and is_global_spec(spec):
        return {"ok": False, "choice_id": choice_id, "action": action,
                "steps": [],
                "error": (f"全局信号（spec={spec!r}）不可执行 spec 作用域动作 "
                          f"'{action}'（无 spec 可操作，信号保留待重审）")}

    try:
        if action == "reset_verification":
            r = reset_verification(project_root, spec, note=note, signal_type=signal_type)
        elif action == "grant_env_exemption":
            # fix-env-exemption-exit-reachability 4.2：授予 env 豁免（DISPOSITION
            # 放行 + 重置重验）
            r = _exec_grant_env_exemption(project_root, spec, note)
        elif action == "revise_scenario_reverify":
            # evo-fix-env-exemption-gate-conflict-… 2.1：场景修订重验出口
            # （白名单路径修订场景定义/夹具供给层 + 置 re-entry 旗标重验）
            r = _exec_revise_scenario_reverify(project_root, spec, note)
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
        elif action == "ack_self_heal":
            # fix-global-signal-choice-execution 1.3：全局信号的非作用域收口
            # （确认自愈/继续观察）——仅留痕关断，不触碰任何 spec 状态机
            r = {"ok": True,
                 "steps": ["确认自愈/继续观察：仅留痕并关闭本条信号，不改动"
                           "任何 spec 状态"],
                 "error": None}
        elif action == "open_config":
            r = {"ok": True,
                 "steps": ["确认信号：请到 Dashboard 配置表单填写 "
                           "worktree.has_build_artifacts / build_artifact_paths"
                           "（本动作仅确认，不代填配置）"],
                 "error": None}
        elif action == "commit_stray_wip":
            # evo-add-commit-stray-wip-choice 2.1：提交主树散件 WIP（全局信号
            # 唯一 git 写动作；signal_type 绑定守卫在执行器内 fail-closed，
            # design D4——resolve_choice 非作用域全表反查通道对未注册信号
            # 可达本动作，执行器收口后任意其它 signal_type 零 git 写）。
            r = _exec_commit_stray_wip(project_root, note, signal_type)
        elif action == "untrack_stray_wip":
            # evo-recurring-stray-remediation 1.2：复发型主树散件当场根治
            # （第二个主树 git 写动作；signal_type 绑定守卫同款在执行器内
            # fail-closed，design D4 收口逻辑一致）。
            r = _exec_untrack_stray_wip(project_root, note, signal_type)
        elif action == "archive_untracked_stray":
            # evo-stray-untracked-escalation 3.1：untracked 散件显式归档
            # （主树文件移动 + 登记目录 ignore；signal_type 绑定白名单在
            # 执行器内 fail-closed，design D4 收口逻辑一致——tracked 桶与
            # info 信号零 git 写零文件触碰）。
            r = _exec_archive_untracked_stray(project_root, note, signal_type)
        elif action == "ignore_untracked_stray":
            # evo-stray-untracked-escalation 3.1：untracked 路径追加 .gitignore
            # （去重 + pathspec 独立提交；绑定白名单同款收口）。
            r = _exec_ignore_untracked_stray(project_root, note, signal_type)
        elif action == "delete_untracked_stray":
            # evo-stray-untracked-escalation 3.1：untracked 散件文件删除
            # （destructive，仅普通文件；绑定白名单同款收口，零 git 写）。
            r = _exec_delete_untracked_stray(project_root, note, signal_type)
        else:
            r = {"ok": False, "steps": [],
                 "error": f"注册表 action '{action}' 无执行器映射"}
    except Exception as e:
        # 不外泄裸异常文本（code-review item e584a2ede367）：执行器异常细节
        # 经服务端日志留痕，客户端（alert-resolve 端点）收固定文案
        logger.warning(
            "裁决动作执行异常（choice_id=%s action=%s spec=%s）: %s: %s",
            choice_id, action, spec, type(e).__name__, e,
        )
        return {"ok": False, "choice_id": choice_id, "action": action,
                "steps": [], "error": "动作执行异常"}
    if not isinstance(r, dict):
        r = {"ok": False, "steps": [], "error": "执行器返回非结构化结果"}
    r = dict(r)
    r.setdefault("steps", [])
    r["choice_id"] = choice_id
    r["action"] = action
    if not r.get("ok") and not r.get("error"):
        r["error"] = "动作未成功执行"
    return r
