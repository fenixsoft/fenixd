"""core.dashboard.data.spec_archive — SPEC 归档/软删除（spec_archive 组）。

refactor-dashboard-data-module D3 分组：本模块承载 SPEC 归档职责域。
软删除、归档、归档检查、state_machine 交互。
"""

import shutil
import sys
import time
from pathlib import Path

# 跨组引用（D4：叶子→中枢，直接导入无环——spec_archive 不被中枢反向 import）
from core.archive_commit import commit_archive_move

# state 组（叶子组已搬移，直接导入无环）
from .state import parse_state

# 删除先停后删的等待总上限（add-freeze-stop-inflight-agents 5.3：admin_actions
# 与 spec_archive 共用同一常量；顶层导入使测试可 patch 覆盖窗口时长）
from .admin_actions import SPEC_DELETE_STOP_WAIT_TOTAL_SECONDS  # noqa: F401


def soft_delete_spec(project_root, spec: str, stop_callback=None) -> dict:
    """软删除 SPEC：STATE.md 移除条目 + spec/changes/<name>/ 移入 archive。

    两步任一失败则尽量回滚以保持两端数据一致（第 1 步移动目录失败时 STATE.md
    尚未改动、天然一致；第 2 步剔除 STATE 失败时尽力把已归档目录移回原位），
    由调用方依据返回码处理：
    - STATE.md 不含该 spec → {found: False}（幂等，不发任何文件操作）
    - 运行中保护：扫描 ``.fenix/runs/*.jsonl`` 顶层（活跃目录），用末行
      非终态判定在跑（终态口径 = ``RUN_TERMINAL_EVENT_TYPES`` 并集，含
      frozen-terminated，不复用 ``classify_run``：superseded 不在终态集合内）。
      归属全等匹配（``run_spec_part(p.stem) == spec``）。
      - 有在跑 + stop_callback 为 None → {running: True}（回退既有 409
        拒绝语义，保持既有单测零改动）。
      - 有在跑 + stop_callback 非 None → 调用停止回调并有界等待终态
        （每 run 宽限 10s + 总上限 SPEC_DELETE_STOP_WAIT_TOTAL_SECONDS）；
        超时 → {ok: False, running: True, pending: [...]}（不改 STATE/
        目录）；全部终止 → 继续正常删除。
    - 正常：remove_spec 原子剔除条目；目录若存在则 shutil.move 到
      spec/archive/<name>-<Unix秒>/；目录缺失仅清状态（幂等）。
    - 目录移动失败（OSError）：返回含 ``error``（``归档移动失败: ...``）的
      失败 dict（不裸抛异常）；STATE.md 尚未改动、目录留在原位。
    - STATE 剔除失败（OSError）：尽力把已归档目录移回 ``spec/changes/<name>``
      并返回含 ``error`` 的失败 dict（不裸抛异常）；回滚亦失败时
      ``archived``/``archive_path`` 保留滞留位置并写入 ``error``。
    - 归档同名冲突（极小概率）：在名字追加毫秒后缀重试，直至成功。

    Returns:
        {"found", "running", "archived": bool, "archive_path": str|null,
         "error": str|null, "pending": list|null, "stopped": int|null}
    """
    from core.agent_runner.liveness import AGENT_TERMINATE_GRACE_SECONDS
    # SPEC_DELETE_STOP_WAIT_TOTAL_SECONDS 已在模块顶层导入（测试可 patch 覆盖）
    from .admin_actions import running_run_ids_for_spec
    proot = Path(project_root)
    # 初始在跑计数（stopped 字段：有在跑 agent 时记录回调前计数，无在跑为 None）
    initial_running_count = 0
    specs = parse_state(proot)
    if spec not in specs:
        return {"found": False}

    # ── 运行中保护：末行非终态判定（add-freeze-stop-inflight-agents 4.1/4.2）──
    # 扫描 .fenix/runs/*.jsonl 顶层（活跃目录），用 run_spec_part 全等归属
    # + 末行非终态判定在跑。末行终态 = RUN_TERMINAL_EVENT_TYPES（含本 SPEC
    # 新增的 frozen-terminated），superseded 不在该集合内（原地重试弃置，
    # 其后还有新 attempt 在跑）——classify_run 误判 superseded 为终态会把
    # 活跃 run 当已终态，让删除在 run 仍可能写盘时移走目录。
    running_ids: list = running_run_ids_for_spec(proot, spec)

    if running_ids:
        if stop_callback is None:
            # 回退既有 409 拒绝语义（保持既有单测零改动）
            return {
                "found": True,
                "running": True,
                "archived": False,
                "archive_path": None,
                "error": "spec 有进行中的运行",
                "pending": None,
                "stopped": None,
            }
        # 有在跑 agent → 经回调请求停止，有界等待终态
        initial_running_count = len(running_ids)
        try:
            stop_callback(running_ids)
        except Exception as e:
            return {
                "found": True,
                "running": True,
                "archived": False,
                "archive_path": None,
                "error": f"停止回调执行失败: {e}",
                "pending": running_ids,
                "stopped": 0,
            }
        # 有界等待：每 AGENT_TERMINATE_GRACE_SECONDS 轮询一次，总上限。
        # 在跑判定每轮复用 running_run_ids_for_spec（code-review item
        # 4b5e9fa50b3a：与初始判定单源同口径，不内联重写末行终态判定；
        # OSError 容错也由该助手内部承担）
        deadline = time.time() + SPEC_DELETE_STOP_WAIT_TOTAL_SECONDS
        while time.time() < deadline:
            still_running: list = running_run_ids_for_spec(proot, spec)
            if not still_running:
                running_ids = []
                break
            running_ids = still_running
            # sleep 前钳制 remaining（code-review item 02f76ca4add6）：上一轮
            # 扫描 runs 目录可能耗时越过 deadline，time.sleep(负值) 抛
            # ValueError 会破坏本函数「以返回 dict 报错、不裸抛异常」契约
            remaining = deadline - time.time()
            if remaining > 0:
                time.sleep(min(AGENT_TERMINATE_GRACE_SECONDS, remaining))
        if running_ids:
            # 超时仍有 run 未终止 → 返回失败，不改 STATE/目录
            return {
                "found": True,
                "running": True,
                "archived": False,
                "archive_path": None,
                "error": f"等待超时仍有 {len(running_ids)} 个 run 未终止",
                "pending": running_ids,
                "stopped": 0,
            }
        # 全部已终止，继续正常删除流程

    from core.state_machine import StateMachine, project_state_logger

    # 跨进程写入者 MUST 注入真实 logger（fix-state-atomicity-and-selfheal-restart
    # 1.3/D2）：dashboard 与 daemon 是不同进程，无 logger 构造会让
    # remove_spec 的「Removed SPEC」留痕静默丢失。
    sm = StateMachine(proot / ".fenix" / "STATE.md", project_state_logger(proot))

    # 1. 先移动目录（若失败，STATE.md 尚未改动，天然一致）
    changes_root = proot / "spec" / "changes"
    spec_dir = changes_root / spec
    # archive 与 changes 平级（spec/archive/），不嵌套在 changes/ 下
    archive_root = proot / "spec" / "archive"
    archived = False
    archive_path = None
    if spec_dir.is_dir():
        archive_root.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
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
        try:
            shutil.move(str(spec_dir), str(dest))
        except OSError as e:
            # 比照 archive_spec（同文件）以返回码告知调用方，不裸抛 OSError：
            # STATE.md 尚未改动、目录留在原位，两端天然一致
            return {
                "found": True,
                "running": False,
                "archived": False,
                "archive_path": None,
                "error": f"归档移动失败: {e}",
                "pending": None,
                "stopped": initial_running_count if initial_running_count else None,
            }
        archived = True
        archive_path = str(dest)

    # 2. 再原子剔除 STATE.md 条目。remove_spec 契约（core/state_machine.py
    # remove_spec docstring）：删除与目录归档是两次独立系统操作，一致性由
    # 调用方负责——此处剔除失败时目录已移入 archive，MUST 尽力移回原位，
    # 否则 spec 永久卡在「STATE 有条目 + 活跃目录不存在」的不一致态
    # （archive_spec 报「活跃目录已不存在」、auto_archive_check 不再纳入，
    # 只能手工修复），并以返回码而非裸异常告知调用方。
    try:
        sm.remove_spec(spec)
    except OSError as e:
        rollback_err = None
        if archived:
            try:
                shutil.move(archive_path, str(spec_dir))
                archived = False
                archive_path = None
            except OSError as re_:
                rollback_err = str(re_)
        error = f"移除 STATE.md 条目失败: {e}"
        if rollback_err is not None:
            error += f"；归档目录回滚失败（滞留于 {archive_path}）: {rollback_err}"
        return {
            "found": True,
            "running": False,
            "archived": archived,
            "archive_path": archive_path,
            "error": error,
            "pending": None,
            "stopped": initial_running_count if initial_running_count else None,
        }
    result = {
        "found": True,
        "running": False,
        "archived": archived,
        "archive_path": archive_path,
        "error": None,
        "pending": None,
        # 有在跑 agent 时登记已停止计数（initial_running_count 在回调前记录，
        # 等待循环把 running_ids 置空后仍可引用）；无在跑时为 None
        "stopped": initial_running_count if initial_running_count else None,
    }
    # 归档自动提交：目录确实移动成功才提交（fail-open，见 core/archive_commit.py）
    if archived:
        cr = commit_archive_move(proot, spec, archive_path)
        result["committed"] = cr["committed"]
        if cr["warning"]:
            result["commit_warning"] = cr["warning"]
    return result


def is_spec_archived(project_root, spec_name: str) -> bool:
    """归档判定：STATE.md 有条目且活跃目录 `spec/changes/<name>/` 不存在。

    D1：归档可见性以活跃目录存在性为准——不检测 archive/ 下具体路径
    形态（删除路径命名 `<name>-<Unix秒>` 不同、手动移动命名不可控），也不写
    STATE.md 标志。三条归档路径（界面 API / CLI skill / 手动 mv）产出相同可见性。
    STATE.md 无该条目（从未创建/已软删除/名字拼错）返回 False 而非 True——
    合取校验防未注册名误判已归档（fix 3505adf6b20e）。
    """
    # 先查目录：未归档 spec 短路返回 False，不额外读 STATE.md（性能敏感路径，
    # /api/specs 对全部 spec 逐个调用）；目录缺席再合取 STATE 条目校验
    return not (Path(project_root) / "spec" / "changes" / spec_name).is_dir() and (
        spec_name in parse_state(project_root)
    )


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
        - 活跃目录缺失（已归档）→ {"ok": False, "found": True, "archived_already": True}
        - 目标已存在 → {"ok": False, "found": True, "conflict": True}（不覆盖）
        - 成功 → {"ok": True, "found": True, "from": 原路径, "to": 目标路径}

        结构化标志（archived_already/conflict）供 HTTP 层按标志选状态码，
        与 error 展示文案无耦合。
    """
    proot = Path(project_root)
    specs = parse_state(proot)
    if spec_name not in specs:
        return {
            "ok": False,
            "found": False,
            "from": None,
            "to": None,
            "error": f"spec not found: {spec_name}",
        }
    status = specs[spec_name].get("status")
    if status not in ("done", "pushed"):
        return {
            "ok": False,
            "found": True,
            "from": None,
            "to": None,
            "error": f"仅终态 spec（done/pushed）可归档，当前状态: {status}",
        }

    change_dir = proot / "spec" / "changes" / spec_name
    if not change_dir.is_dir():
        return {
            "ok": False,
            "found": True,
            "from": None,
            "to": None,
            "archived_already": True,
            "error": f"Spec '{spec_name}' 活跃目录已不存在（可能已归档）",
        }

    from datetime import date

    target = proot / "spec" / "archive" / f"{date.today().isoformat()}-{spec_name}"
    if target.exists():
        return {
            "ok": False,
            "found": True,
            "from": str(change_dir),
            "to": str(target),
            "conflict": True,
            "error": f"归档目标已存在: {target} — 请改名或改日再归档，原目录不会被覆盖",
        }

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        moved = Path(shutil.move(str(change_dir), str(target)))
    except OSError as e:
        return {
            "ok": False,
            "found": True,
            "from": str(change_dir),
            "to": str(target),
            "error": f"归档移动失败: {e}",
        }
    result = {"ok": True, "found": True, "from": str(change_dir), "to": str(moved), "error": None}
    # remove-auto-run-cleanup：run 产物归档的唯一入口 = SPEC 归档。change 目录
    # 移动成功后，把 .fenix/runs/ 顶层属于该 spec 的产物移入 archive/（不删除
    # 任何文件）。与 bin/fenix_archive.py::archive_change 同源同步——本函数是
    # daemon 自动归档（auto_archive_check）与 Dashboard 界面归档
    # （POST /api/spec-archive）共用的入口，此前漏挂此步，SPEC 归档后 run 产物
    # 永久滞留 runs 顶层（实证：138 个已归档 SPEC 中 127 个的产物仍在顶层）。
    # fail-open：runs 归档失败仅在返回 dict 追加告警字段，不阻断 change 归档主流程。
    # D8：经门面延迟解析（tests 以 patch.object(dash_data, "archive_spec_runs") 替换）
    import core.dashboard.data as _facade

    try:
        result["runs_archived"] = _facade.archive_spec_runs(proot / ".fenix" / "runs", spec_name)
    except OSError as e:
        result["runs_archive_warning"] = str(e)
    # 归档自动提交：移动成功立即入库（fail-open，见 core/archive_commit.py）
    cr = commit_archive_move(proot, spec_name, moved)
    result["committed"] = cr["committed"]
    if cr["warning"]:
        result["commit_warning"] = cr["warning"]
    return result


def auto_archive_check(project_root, config: dict, logger=None) -> dict:
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
        return {
            "archived": 0,
            "skipped": 0,
            "target_count": 0,
            "threshold": threshold,
            "total_terminal_unarchived": 0,
        }

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
        return {
            "archived": 0,
            "skipped": 0,
            "target_count": 0,
            "threshold": threshold,
            "total_terminal_unarchived": total,
        }

    # 按 updated 升序（最久完成的先归档）；缺 updated 归队尾（空串最小）。
    # 纯 return 无异常面，try/except 属不可达死代码（code-review item
    # 81f539cc3de8）；updated 经 `or ""` 归一为字符串，排序比较安全。
    def _sort_key(item):
        return item[1].get("updated") or ""

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
