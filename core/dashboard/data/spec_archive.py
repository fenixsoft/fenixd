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
                        return {"found": True, "running": True, "error": "spec 有进行中的运行"}
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
    result = {
        "found": True,
        "running": False,
        "archived": archived,
        "archive_path": archive_path,
        "error": None,
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
