"""
data.py — 共享数据聚合层（TUI 与 Web Dashboard 共用）。

把 bin/fenix_dashboard.py 中已验证的 STATE.md / tasks.md / 日志 / 验证产物解析
逻辑提取为以 project_root 为参数的纯函数，并为 Web 增加更丰富的聚合视图（验证
进度、逐场景断言、bug 列表、截图列表、运行记录）。

容错约定：所有解析函数对损坏/缺失数据源绝不抛异常——损坏的 JSON 以带
`"error": "corrupt"` 标记的对象返回，缺失则返回空结构，保证聚合请求不 500。
"""

import json
import os
import re
import shutil
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

from core.agent_runner import clean_old_runs
from core.fenix_session import is_running as _is_running

# 运行产物文件保留上限（与 agent_runner.RUNS_KEEP 一致）
RUNS_KEEP = 50


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


# ── SPEC 人工冻结/解冻（用户指令冻结；admin_monitor 认 blocked+前缀为有意等待态） ──

FREEZE_ERROR_PREFIX = "用户指令冻结："


def is_spec_frozen(entry: dict) -> bool:
    """判定 SPEC 是否处于人工冻结态：status=blocked 且 error 以冻结前缀开头。"""
    return entry.get("status") == "blocked" and (entry.get("error") or "").startswith(
        FREEZE_ERROR_PREFIX
    )


def freeze_spec(project_root, spec_name: str, reason: str = "") -> dict:
    """人工冻结 SPEC：status→blocked，error 以「用户指令冻结：」开头并记录原状态。

    - done/pushed 终态不可冻结（冻结终态破坏语义），返回 ok=True + frozen=False
    - 写回经 StateMachine（带文件锁）；daemon 经 STATE.md watcher 感知后停止调度
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
    note = f"{FREEZE_ERROR_PREFIX}原状态 {orig}" + (f" · {reason}" if reason else "")
    from core.state_machine import StateMachine
    sm = StateMachine(Path(project_root) / "STATE.md", None)
    sm.update_spec(spec_name, {"status": "blocked", "error": note})
    return {"ok": True, "found": True, "frozen": True, "error": None}


def unfreeze_spec(project_root, spec_name: str) -> dict:
    """解冻 SPEC：从冻结 error 中恢复原状态并清空 error；未冻结则为 no-op。"""
    specs = parse_state(project_root)
    if spec_name not in specs:
        return {"ok": False, "found": False, "frozen": False,
                "error": f"spec not found: {spec_name}"}
    entry = specs[spec_name]
    if not is_spec_frozen(entry):
        return {"ok": True, "found": True, "frozen": False, "error": None}
    m = re.search(r"原状态\s+(\S+)", entry.get("error") or "")
    orig = m.group(1) if m else "ready"
    from core.state_machine import StateMachine
    sm = StateMachine(Path(project_root) / "STATE.md", None)
    sm.update_spec(spec_name, {"status": orig, "error": None})
    return {"ok": True, "found": True, "frozen": False, "error": None}


# ── SPEC 文档读取（proposal.md / design.md，add-spec-doc-buttons） ──

# kebab-case：小写字母/数字开头，仅含小写字母/数字/连字符（防御路径穿越）
_SPEC_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
# doc 白名单：仅允许读取这些核心设计文档（tasks.md 与 proposal.md 同目录）
_SPEC_DOC_WHITELIST = ("proposal", "design", "tasks", "verification", "scenarios")


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

    changes_root = Path(project_root) / "openspec" / "changes"
    if doc == "verification":
        # 验证报告：verification-report.md（可能尚未生成 → found=False）
        target = (changes_root / spec / "verification-report.md").resolve()
    elif doc == "scenarios":
        # 测试场景清单：specs/<capability>/spec.md 的汇总拼接
        return _read_spec_scenarios(changes_root / spec / "specs")
    else:
        target = (changes_root / spec / f"{doc}.md").resolve()
    # 防御性校验：解析后必须仍位于 changes 目录内，杜绝任何 `..` 拼接越界
    if not target.is_relative_to(changes_root.resolve()):
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
    sm = StateMachine(proot / "STATE.md")
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
    sm = StateMachine(proot / "STATE.md")
    sm.update_spec(spec, {"priority": p})
    return {"found": True, "priority": p}


def soft_delete_spec(project_root, spec: str) -> dict:
    """软删除 SPEC：STATE.md 移除条目 + openspec/changes/<name>/ 移入 archive。

    两步任一失败则尽量回滚以保持两端数据一致，由调用方依据返回码处理：
    - STATE.md 不含该 spec → {found: False}（幂等，不发任何文件操作）
    - 运行中检测：runs 目录该 spec 有 mtime 在最近 120 秒内的运行产物 →
      {running: True, error: "spec 有进行中的运行"}（409 拒绝，不改数据）
    - 正常：remove_spec 原子剔除条目；目录若存在则 shutil.move 到
      openspec/changes/archive/<name>-<Unix秒>/；目录缺失仅清状态（幂等）。
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
    sm = StateMachine(proot / "STATE.md")

    # 1. 先移动目录（若失败，STATE.md 尚未改动，天然一致）
    changes_root = proot / "openspec" / "changes"
    spec_dir = changes_root / spec
    archive_root = changes_root / "archive"
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
    return {"found": True, "running": False, "archived": archived,
            "archive_path": archive_path, "error": None}


def is_spec_archived(project_root, spec_name: str) -> bool:
    """归档判定：STATE.md 有条目且活跃目录 `openspec/changes/<name>/` 不存在。

    D1：归档的**唯一事实来源**是活跃目录存在性——不检测 archive/ 下具体路径
    形态（删除路径命名 `<name>-<Unix秒>` 不同、手动移动命名不可控），也不写
    STATE.md 标志。三条归档路径（界面 API / CLI skill / 手动 mv）产出相同可见性。
    """
    return not (Path(project_root) / "openspec" / "changes" / spec_name).is_dir()


def archive_spec(project_root, spec_name: str) -> dict:
    """归档 SPEC：把 `openspec/changes/<name>/` 移到 `archive/YYYY-MM-DD-<name>/`。

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

    change_dir = proot / "openspec" / "changes" / spec_name
    if not change_dir.is_dir():
        return {"ok": False, "found": True, "from": None, "to": None,
                "error": f"Spec '{spec_name}' 活跃目录已不存在（可能已归档）"}

    from datetime import date
    target = (
        proot / "openspec" / "changes" / "archive"
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
    return {"ok": True, "found": True, "from": str(change_dir), "to": str(moved),
            "error": None}


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
        if not (proot / "openspec" / "changes" / name).is_dir():
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
    state_path = Path(project_root) / "STATE.md"
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
         "flat_done": set[int]}   # 已完成任务的创建序下标（0-based，flat 回退用）
    """
    try:
        st = run_file.stat()
        key = (str(run_file), st.st_mtime_ns, st.st_size)
    except OSError:
        return {"done_ids": set(), "created_count": 0, "flat_done": set()}
    cached = _RUN_TASK_CACHE.get(key)
    if cached is not None:
        return cached

    created_ordered: list = []  # 按创建序的 subject 提取 tasks.md id（无 id 记 None）
    completed_idx: set = set()  # TaskUpdate completed 的 taskId - 1
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
                        if inp.get("status") == "completed":
                            completed_idx.add(n - 1)
    except OSError:
        return {"done_ids": set(), "created_count": 0, "flat_done": set()}

    created_count = len(created_ordered)
    done_ids = set()
    for idx in completed_idx:
        if 0 <= idx < created_count and created_ordered[idx]:
            done_ids.add(created_ordered[idx])
    flat_done = {i for i in completed_idx if 0 <= i < created_count}

    result = {"done_ids": done_ids, "created_count": created_count, "flat_done": flat_done}
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
    tasks_path = Path(project_root) / "openspec" / "changes" / spec_name / "tasks.md"
    if spec_status == "implementing":
        wt = find_implementer_worktree(project_root, spec_name)
        if wt:
            wt_tasks = wt / "openspec" / "changes" / spec_name / "tasks.md"
            if wt_tasks.exists():
                tasks_path = wt_tasks
    if not tasks_path.exists():
        return []
    groups = []
    current_group = None
    try:
        for line in tasks_path.read_text(encoding="utf-8").split("\n"):
            m = re.match(r"^##\s+\d+\.\s+(.+)$", line)
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


def count_scenarios(project_root, spec_name) -> int:
    """统计 SPEC 各 spec.md 中 Scenario 数量。"""
    specs_dir = Path(project_root) / "openspec" / "changes" / spec_name / "specs"
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


def get_recent_events(project_root, minutes=10, limit=30) -> list:
    """读取最近 N 分钟的 fenixd 结构化日志事件。"""
    logs_dir = Path(project_root) / ".fenix" / "logs"
    if not logs_dir.is_dir():
        return []
    log_files = sorted(logs_dir.glob("fenixd*.log"), reverse=True)
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    events = []
    for lf in log_files[:2]:
        try:
            for line in lf.read_text(encoding="utf-8").split("\n"):
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = entry.get("timestamp", "")
                if ts < cutoff:
                    continue
                events.append(entry)
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
    """解析 .fenix/verify-progress/<spec>.json；损坏/非对象以 error 字段标记。"""
    pf = Path(project_root) / ".fenix" / "verify-progress" / f"{spec_name}.json"
    if not pf.exists():
        return {"exists": False, "total": 0, "done": 0, "current": ""}
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
        }
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return {"exists": True, "error": "corrupt", "total": 0, "done": 0, "current": ""}


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
    返回场景 dict 列表（已归一化截图字段），不可得返回 []。
    """
    candidates = [
        Path(project_root) / ".fenix" / "verify-progress" / spec_name / ".fenix-run-result.json",
        Path(project_root) / ".fenix-run-result.json",
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


def parse_verdict(project_root, spec_name) -> dict:
    """解析 verification-report.md 的验证结论，供 Dashboard 直接展示。

    返回: {"exists", "status", "status_detail", "conclusion", "summary"}
    - status: 结论标题（如 "环境不可达，无法验证" / "❌ 未通过（Bug Found）"）
    - status_detail: **状态:** 行（如 "环境问题 — Dashboard 服务未启动"）
    - conclusion: 结论段落（人类可读，避免用户只看 "0通过, 31失败"）
    - summary: {"passed","failed","errors","product_bugs","env_issues"} 尽力解析
    """
    path = Path(project_root) / "openspec" / "changes" / spec_name / "verification-report.md"
    if not path.exists():
        return {"exists": False, "status": "", "status_detail": "", "conclusion": "", "summary": {}}
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
    """
    bugs = []
    report = parse_report(project_root, spec_name)
    if not report.get("exists") or report.get("error"):
        return bugs
    for sc in report.get("scenarios", []):
        if not isinstance(sc, dict):
            continue
        status = sc.get("status")
        if status not in ("fail", "error"):
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
        classification = sc.get("classification")
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
                "severity": "major" if status == "fail" else "critical",
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
            })
    return bugs


# ── 运行记录（.fenix/runs/） ─────────────────────────────────────

def classify_run(lines: list) -> str:
    """根据产物文件行判定运行终态：done / error / running / empty。"""
    if not lines:
        return "empty"
    last = lines[-1]
    if not isinstance(last, dict):
        return "running"
    t = last.get("type")
    if t == "result":
        return "done"
    if t == "error":
        return "error"
    return "running"


def _resolve_run_file(project_root, run_id: str) -> Path:
    """定位 run 产物：优先活跃目录，缺失时回读 archive/（add-run-archive）。"""
    proot = Path(project_root)
    live = proot / ".fenix" / "runs" / f"{run_id}.jsonl"
    if live.exists():
        return live
    return proot / ".fenix" / "runs" / "archive" / f"{run_id}.jsonl"


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
        duration_seconds = max(0, int(stat.st_mtime - start_ts))
        lines = _read_run_lines(p, max_lines=3)
        out.append({
            "run_id": run_id,
            "agent_type": agent_type,
            "spec": spec_part,
            "status": classify_run(lines),
            "duration_seconds": duration_seconds,
            # started 用 run_id 解析出的真实开始时间戳（start_ts），而非文件 mtime
            # （mtime 是运行 *结束* 时间）。duration_seconds = mtime - start_ts 已真实计算，
            # 若 started 仍取 mtime，则运行列表/时间轴会把每次运行显示为「在结束时刻才开始」，
            # 与真实耗时自相矛盾（耗时列为真实秒数而开始时间却是结束时刻）。
            "started": datetime.fromtimestamp(start_ts, tz=timezone.utc).isoformat(),
            "file_size": stat.st_size,
        })
    return out


def _read_run_lines(path: Path, max_lines: int = 3) -> list:
    """读取产物文件最后几行 JSON，逐行容错。"""
    out = []
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if size > 4096:
                f.seek(max(0, size - 4096))
            else:
                f.seek(0)
            raw = f.read()
        # 向前扫描到合法 UTF-8 起始字节，避免 seek 落在多字节字符中间
        start = 0
        while start < len(raw) and (raw[start] & 0xC0) == 0x80:
            start += 1
        text = raw[start:].decode("utf-8", errors="replace")
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                out.append({"type": "stderr", "line": line})
            if len(out) > max_lines:
                out.pop(0)
    except OSError:
        pass
    return out


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


def cleanup_runs(project_root) -> int:
    """归档超出保留上限的旧运行产物（跳过活动产物），返回归档数。

    额外保护：STATE.md 中任一 spec 的 implementer_run / tester_run 引用的 run
    文件永久保留——它们是历史 spec 时间轴的数据源，不能因保留上限被淘汰
    （否则 spec 详情页的时间轴、任务进度随即消失）。

    保留上限取 runs.keep（用户级/项目级合并有效值，默认 RUNS_KEEP=50），
    可在 Dashboard 设置页「其他」分类调整；超限产物移入 runs/archive/ 而非
    删除（add-run-archive：时间轴/运行记录回读归档）。
    """
    from core.config import ConfigLoader

    runs_dir = Path(project_root) / ".fenix" / "runs"
    protected = set()
    for entry in parse_state(project_root).values():
        for key in ("implementer_run", "tester_run"):
            rid = entry.get(key)
            if rid:
                protected.add(str(rid))
    keep = RUNS_KEEP
    try:
        effective = ConfigLoader.resolve_config(project_root)
        configured = ConfigLoader.get(effective, "runs.keep", RUNS_KEEP)
        if isinstance(configured, int) and configured >= 1:
            keep = configured
    except Exception:
        pass
    return clean_old_runs(runs_dir, keep=keep, active_ids=protected)


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
    cleanup_runs(proot)
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
        "updated": (Path(path) / "STATE.md").stat().st_mtime if (Path(path) / "STATE.md").exists() else 0,
        "description": description,
    }


def spec_summary(project_root, spec_name: str, entry: dict) -> dict:
    """单个 SPEC 的摘要（/api/specs 列表项）。"""
    done, total = task_progress(project_root, spec_name, entry.get("status", ""))
    vp = parse_verify_progress(project_root, spec_name)
    # 含归档：run 产物被清理后列表页耗时统计不缩水
    runs = get_runs(project_root, spec_name, include_archive=True)
    # add-done-duration-persist（D4）：done/pushed 的 SPEC 优先读 STATE.md 固化的
    # total_duration（done 时刻快照，不随 run 产物清理归零）；parse_state 返回
    # 字符串，须 int 容错转换，脏值/缺失回退实时求和。非完成状态忽略字段，
    # 运行中的 SPEC 耗时应持续增长，冻结值仅对终态有意义（D5）。
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
        total_duration = sum(int(r.get("duration_seconds") or 0) for r in runs)
    else:
        total_duration = persisted
    # add-fast-track-mode（task 7.1）：执行模式（读 .openspec.yaml，缺省 full）
    from core.openspec_mode import read_spec_mode
    mode = read_spec_mode(project_root, spec_name)
    return {
        "name": spec_name,
        "status": entry.get("status"),
        "archived": is_spec_archived(project_root, spec_name),
        "mode": mode,
        "priority": entry.get("priority"),
        "created": entry.get("created"),
        "updated": entry.get("updated"),
        "error": entry.get("error"),
        "task_done": done,
        "task_total": total,
        "verify_done": vp.get("done", 0),
        "verify_total": vp.get("total", 0),
        "verify_error": vp.get("error"),
        "scenario_count": count_scenarios(project_root, spec_name),
        "total_duration": total_duration,
        "latest_run": runs[0]["run_id"] if runs else None,
        "latest_run_status": runs[0]["status"] if runs else None,
    }


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


def _run_tail_insights(run_file: Path, tail_bytes: int = 65536,
                       marker_scan_cap: int = 4 << 20) -> dict:
    """读取 run 产物尾部：ClaudeCode 最后一条总结 + 实际驱动的 LLM。

    summary 优先取 result 事件的 result 字段（run 最终总结，markdown 文本，
    与 runner.py 提取产物口径一致）；无 result（运行中/中断）时回退最后一条
    assistant 文本。llm 取最后一个 provider_marker 事件（attempt 启动时写入，
    failover 切换产生多个，取最后 = 实际完成 run 的网关）。只读文件尾部
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
        return {"summary": "", "llm": ""}

    def parse_chunk(raw: str, skip_first: bool) -> tuple[str, str]:
        lines = raw.split("\n")
        if skip_first:
            lines = lines[1:]
        result_text = last_asst = llm = ""
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
        return result_text or last_asst, llm

    summary, llm = parse_chunk(data, skip_first=size > tail_bytes)
    if not llm and size > tail_bytes:
        chunk = 262144
        floor = max(0, size - tail_bytes - marker_scan_cap)
        pos = size - tail_bytes
        with run_file.open("rb") as f:
            while pos > floor and not llm:
                start = max(floor, pos - chunk)
                f.seek(start)
                raw = f.read(pos - start).decode("utf-8", errors="replace")
                _, llm = parse_chunk(raw, skip_first=start > 0)
                pos = start
    return {"summary": summary, "llm": llm}


def get_spec_timeline(project_root, spec_name: str) -> list:
    """构建 SPEC 生命周期时间轴（按时间排序）。

    数据源：
    - 事件日志（fenixd*.log）中的 `Transition: <spec> from → to` → 状态节点
    - `.fenix/runs/` 运行产物 → 运行节点（可点击展开 LLM 对话）

    每条:
    - 状态: {time, kind:"state", from, to, reason}  （回退节点带 reason）
    - 运行: {time, kind:"run", run_id, agent_type, status}
    """
    logs_dir = Path(project_root) / ".fenix" / "logs"
    events: list[dict] = []
    errors_at: list[tuple] = []   # (timestamp, error) —— Agent 记录的 error，作为回退原因

    if logs_dir.is_dir():
        try:
            log_files = sorted(logs_dir.glob("fenixd*.log"), reverse=True)
        except OSError:
            log_files = []
        for lf in log_files[:2]:
            try:
                content = lf.read_text(encoding="utf-8", errors="replace")
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
                    reason = ""
                    if _LIFECYCLE_ORDER.get(to, 9) < _LIFECYCLE_ORDER.get(frm, 9):
                        reason = _backtrack_reason(frm, to)
                    events.append({"time": ts, "kind": "state", "from": frm, "to": to, "reason": reason})
                if "Updated SPEC" in msg and spec_name in msg:
                    updates = entry.get("context", {}).get("updates", {}) or {}
                    err = updates.get("error")
                    if err:
                        errors_at.append((ts, str(err)))

    # 运行节点（含归档：旧 spec 的 run 产物被清理后时间轴仍可回看）
    for r in get_runs(project_root, spec_name, include_archive=True):
        insights = _run_tail_insights(_resolve_run_file(project_root, r["run_id"]))
        events.append({"time": r["started"], "kind": "run", "run_id": r["run_id"],
                       "agent_type": r["agent_type"], "status": r["status"],
                       "spec": r.get("spec"),
                       "duration_seconds": r.get("duration_seconds"),
                       "summary": insights["summary"], "llm": insights["llm"]})

    # 排序：解析时间戳 + 同秒内 state 先于 run（_timeline_sort_key 内注释说明根因）
    events.sort(key=_timeline_sort_key)

    # 连续的前向状态转换折叠为一次（回退/运行节点打断）
    events = _collapse_timeline(events)

    # 回退节点补充 Agent 记录的 error 作为原因（取时间最近的一条，10 分钟内）
    if errors_at:
        for e in events:
            if e.get("kind") != "state" or not e.get("reason"):
                continue
            deltas = [(d, err) for (ts, err) in errors_at
                      if (d := _ts_delta(ts, e["time"])) is not None]
            if deltas:
                d, err = min(deltas, key=lambda x: x[0])
                if d < 600:   # 10 分钟内匹配到 Agent 记录的 error
                    e["reason"] = err[:120]
    return events


def _collapse_timeline(events: list) -> list:
    """把连续的前向状态转换折叠为一次（from[首] → to[尾]）。

    规则：
    - 连续出现的「前向状态节点」（无 reason）合并为一个节点，展示整体跨度；
      如 drafted→ready / ready→implementing / … → 折叠为 drafted → implementing。
    - 回退节点（带 reason，如 testing→bug-found）与运行节点保持独立，并打断合并。
    """
    out: list[dict] = []
    buf: list[dict] = []   # 待合并的前向状态节点缓冲
    for e in events:
        if e.get("kind") == "state" and not e.get("reason"):
            buf.append(e)
            continue
        # 遇到回退状态 / 运行节点 / 其它 → 先冲刷缓冲，再追加当前事件
        if buf:
            out.append({
                "time": buf[0]["time"], "kind": "state",
                "from": buf[0]["from"], "to": buf[-1]["to"], "reason": "",
            })
            buf = []
        out.append(e)
    if buf:
        out.append({
            "time": buf[0]["time"], "kind": "state",
            "from": buf[0]["from"], "to": buf[-1]["to"], "reason": "",
        })
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
    解析失败的事件按原字符串排在末尾，保持稳定。
    """
    dt = _parse_iso_ts(e.get("time", ""))
    if dt is None:
        from datetime import datetime as _dt, timezone as _tz
        return (_dt.max.replace(tzinfo=_tz), 2, str(e.get("time", "")))
    kind_rank = 0 if e.get("kind") == "state" else 1
    return (dt.replace(microsecond=0), kind_rank, dt)


def _ts_delta(a: str, b: str):
    """两个 ISO 时间戳的秒级差值（解析失败返回 None）。"""
    ta = _parse_iso_ts(a)
    tb = _parse_iso_ts(b)
    if ta is None or tb is None:
        return None
    return abs((ta - tb).total_seconds())


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
    # add-fast-track-mode（task 7.1）：执行模式（读 .openspec.yaml，缺省 full）
    from core.openspec_mode import read_spec_mode
    mode = read_spec_mode(project_root, spec_name)
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
        "verify_progress": parse_verify_progress(project_root, spec_name),
        "report": {
            "exists": report.get("exists", False),
            "error": report.get("error"),
            "timestamp": report.get("timestamp"),
            "summary": report.get("summary"),
        },
        "scenarios": scenarios,
        "bugs": bugs,
        "screenshots": screenshots,
        "runs": runs,
        "verdict": verdict,
        "timeline": get_spec_timeline(project_root, spec_name),
        # add-cost-observability（D2）：治理区展示的累计 token 与成本可用性标记。
        # _cost_usd 仅在网关真实回传时存在（不伪造金额，spec「金额展示不伪造」）。
        "token_usage": _token_usage_view(entry),
    }


def _token_usage_view(entry: dict) -> dict:
    """把 STATE 内部 token 字段规整为治理区展示结构（add-cost-observability D2）。

    返回固定结构：
        {
          "tokens_in": int, "tokens_out": int,
          "cache_creation_input_tokens": int | None,  # STATE 仅存累计，分项未记录→None
          "cache_read_input_tokens": int | None,
          "cost_usd": float | None,    # None = 网关未回传，界面展示「成本不可用」
          "cost_available": bool,       # 成本字段是否可展示
        }
    STATE 仅持久累计 _tokens_in/_tokens_out/_cost_usd（分项 cache 入 input），
    故分项在详情 tooltip 中以「已计入 input」说明，值为 None 表示无可分项数据。
    """
    if not isinstance(entry, dict):
        entry = {}
    tokens_in = int(entry.get("_tokens_in", 0) or 0)
    tokens_out = int(entry.get("_tokens_out", 0) or 0)
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
        "cache_creation_input_tokens": None,
        "cache_read_input_tokens": None,
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


# ── 配置读写（受管键：llm / agents.models / agents.max_concurrent / agents.run_timeout_seconds / gates.approve_mode） ──

# Dashboard 管理的配置键子集：写回时只更新这些键，其它键原样保留
_MANAGED_KEYS = ["llm", "agents", "gates", "runs"]
# 在 agents 下管理的子键白名单
_AGENTS_MANAGED_SUBKEYS = ["models", "max_concurrent", "run_timeout_seconds", "max_turns", "daily_run_limit", "token_budget_millions", "impl_run_budget"]

# 用户级配置文件路径（与项目级同名 `.fenix/config.yaml`，作用域由所在目录决定）
USER_CONFIG_PATH = Path.home() / ".fenix" / "config.yaml"

# 受管键的来源标注键（前端用于「继承自用户级」badge）
_SOURCE_KEYS = ["llm", "agents.models", "agents.max_concurrent",
                "agents.run_timeout_seconds", "agents.max_turns", "agents.daily_run_limit",
                "agents.token_budget_millions", "agents.impl_run_budget", "gates.approve_mode",
                "runs.keep"]

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
    gates_raw = raw.get("gates")
    if isinstance(gates_raw, dict) and "approve_mode" in gates_raw:
        sources["gates.approve_mode"] = "project"
    runs_raw = raw.get("runs")
    if isinstance(runs_raw, dict) and "keep" in runs_raw:
        sources["runs.keep"] = "project"
    return sources


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
        "agents": {"models": {}, "max_concurrent": 2, "run_timeout_seconds": 3600, "max_turns": 300, "daily_run_limit": 50, "token_budget_millions": 50, "impl_run_budget": 4},
        "gates": {"approve_mode": "manual"},
        "runs": {"keep": 50},
        # add-spec-archive D5：自动归档阈值（0 = 禁用，默认 50）
        "archive": {"auto_threshold": 50},
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
        if agents_result:
            # 只在结果中有受管键时覆盖默认，避免清空默认值
            for k, v in agents_result.items():
                result["agents"][k] = v
    gates_raw = raw.get("gates")
    if isinstance(gates_raw, dict) and "approve_mode" in gates_raw:
        result["gates"] = {"approve_mode": gates_raw["approve_mode"]}
    runs_raw = raw.get("runs")
    if isinstance(runs_raw, dict) and isinstance(runs_raw.get("keep"), int) and runs_raw["keep"] >= 1:
        result["runs"] = {"keep": runs_raw["keep"]}
    archive_raw = raw.get("archive")
    if isinstance(archive_raw, dict):
        from core.config import ConfigLoader as _CL
        result["archive"] = {"auto_threshold": _CL.effective_auto_archive_threshold(raw)}
    return result


def read_effective_config(project_root) -> dict:
    """项目模式有效配置视图：受管键取 resolve_config 有效合并值 + sources 标注。

    返回: {"llm": {...}, "agents": {"models": {...}, "max_concurrent": int},
            "gates": {"approve_mode": ...}, "scope": "project", "raw_exists": bool,
            "sources": {...}, "error": str|null, "description": str}
    sources[key] = "project" 当该键在项目级文件显式定义，否则 "user"（继承用户级或默认）。
    """
    from core.config import ConfigLoader

    proot = Path(project_root)
    proj_path = proot / ".fenix" / "config.yaml"

    result = {
        "llm": {},
        "agents": {"models": {}, "max_concurrent": 2, "run_timeout_seconds": 3600, "max_turns": 300, "daily_run_limit": 50, "token_budget_millions": 50, "impl_run_budget": 4},
        "gates": {"approve_mode": "manual"},
        "runs": {"keep": 50},
        # add-spec-archive D5：自动归档阈值（0 = 禁用，默认 50）
        "archive": {"auto_threshold": 50},
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
    gates_eff = effective.get("gates")
    if isinstance(gates_eff, dict) and "approve_mode" in gates_eff:
        result["gates"] = {"approve_mode": gates_eff["approve_mode"]}
    runs_eff = effective.get("runs")
    if isinstance(runs_eff, dict) and isinstance(runs_eff.get("keep"), int) and runs_eff["keep"] >= 1:
        result["runs"] = {"keep": runs_eff["keep"]}
    # add-spec-archive D5：经生效助手取值（非法配置回落默认 50，设置页回显一致）
    result["archive"] = {"auto_threshold": ConfigLoader.effective_auto_archive_threshold(effective)}

    # 提取 project.description → 顶层 description（非 str 或缺失 → ""）
    project_eff = effective.get("project")
    if isinstance(project_eff, dict) and isinstance(project_eff.get("description"), str):
        result["description"] = project_eff["description"]
    else:
        result["description"] = ""

    return result


def _deep_merge_managed(raw_config: dict, patch: dict) -> dict:
    """把 patch 中的受管键合并到 raw_config，返回新 dict（不修改原对象）。

    合并规则（白名单化）：
    - llm: 整体替换（patch 中存在即替换，不存在则保留原 llm）
    - agents.models: 整体替换（只动 models，其它 agents 子键保留）
    - agents.max_concurrent: 替换（仅 patch 中提供且为正整数时）
    - gates.approve_mode: 只替换 approve_mode 子键
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

    if "gates" in patch and isinstance(patch["gates"], dict):
        if "approve_mode" in patch["gates"]:
            if not isinstance(merged.get("gates"), dict):
                merged["gates"] = {}
            merged["gates"]["approve_mode"] = patch["gates"]["approve_mode"]

    if "runs" in patch and isinstance(patch["runs"], dict):
        keep = patch["runs"].get("keep")
        # 仅接受正整数，非法值静默忽略（保留原配置）
        if isinstance(keep, int) and keep >= 1:
            if not isinstance(merged.get("runs"), dict):
                merged["runs"] = {}
            merged["runs"]["keep"] = keep
    # add-spec-archive D5：archive.auto_threshold（非负整数，0=禁用，非法值静默忽略）
    if "archive" in patch and isinstance(patch["archive"], dict):
        at = patch["archive"].get("auto_threshold")
        if isinstance(at, int) and at >= 0:
            if not isinstance(merged.get("archive"), dict):
                merged["archive"] = {}
            merged["archive"]["auto_threshold"] = at
    # description 分支：patch 顶层 description（str）写入 merged["project"]["description"]
    if "description" in patch and isinstance(patch["description"], str):
        if not isinstance(merged.get("project"), dict):
            merged["project"] = {}
        merged["project"]["description"] = patch["description"]

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

    # 2. 合并受管键
    merged = _deep_merge_managed(raw, config_patch)

    # 3. 校验受管字段（llm / agents.models / agents.max_concurrent / gates.approve_mode）
    #    不做完整 ConfigLoader 校验，避免缺少 project/schedule 等必填键时无法写入。
    try:
        llm = merged.get("llm") or {}
        if llm:
            ConfigLoader._validate_llm(llm)
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
        gates = merged.get("gates") or {}
        if "approve_mode" in gates and gates["approve_mode"] is not None:
            mode = gates["approve_mode"]
            if mode not in ConfigLoader.VALID_APPROVE_MODES:
                raise ValueError(
                    f"gates.approve_mode must be one of {ConfigLoader.VALID_APPROVE_MODES}: {mode}"
                )
        # add-spec-archive D5：archive.auto_threshold 必须为非负整数（0=禁用）
        archive_m = merged.get("archive") or {}
        if "auto_threshold" in archive_m and archive_m["auto_threshold"] is not None:
            at = archive_m["auto_threshold"]
            if not isinstance(at, int) or isinstance(at, bool) or at < 0:
                raise ValueError(
                    f"archive.auto_threshold must be a non-negative integer (0=disabled): {at}"
                )
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
