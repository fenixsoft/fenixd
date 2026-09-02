"""run_files.py — .fenix/runs/ 运行产物写入与清理（refactor-core-packages 阶段 2）。

模块级函数组件：append_run_line / append_run_error / clean_old_runs。
门面 runner.py 转导这些名字，`from core.agent_runner import clean_old_runs`
等外部 import 路径保持不变（spec core-package-structure「外部 API 零变化」）。
"""

from pathlib import Path
import json

# .fenix/runs/ 保留的最近运行产物数量上限（默认 50，见 D1 / spec agent-run-artifacts；
# 超出部分归档至 runs/archive/ 而非删除，见 add-run-archive）
RUNS_KEEP = 50


def append_run_line(run_file: Path, entry: dict) -> None:
    """向运行产物文件追加一行 JSON 并立即 flush，保证运行期间 Dashboard 可读。

    每行独立 open("a") + flush，两个读线程并发写入时依赖 O_APPEND 的原子性，
    避免长行被交错切碎。
    """
    with run_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        f.flush()


def append_run_error(run_file: Path, error: str, exit_code: int) -> None:
    """异常/超时/kill 终止时向产物文件追加 error 终态行。"""
    append_run_line(run_file, {"type": "error", "error": error, "exit_code": exit_code})


def clean_old_runs(runs_dir: Path, keep: int = RUNS_KEEP, active_ids=None) -> int:
    """归档 .fenix/runs/ 中超出保留上限的最旧产物，跳过受保护的产物。

    超限产物移入 runs_dir/archive/（add-run-archive：保留历史供 Dashboard
    时间轴/运行记录回看），不再直接删除。同 run_id 的归档副本已存在时仅
    删除活跃副本（内容同源，以归档为准）。

    Args:
        runs_dir: .fenix/runs/ 目录。
        keep: 保留的最近产物数量（可配置，见 data.cleanup_runs 的 runs.keep）。
        active_ids: 不归档的 run_id 集合——既含仍在增长的活动产物，也含
            STATE.md 引用的历史产物（implementer_run/tester_run，清理时由
            data.cleanup_runs 传入），被引用的 run 是 spec 时间轴数据源。

    Returns: 归档（含去重删除）的文件数。
    """
    if not runs_dir.is_dir():
        return 0
    active_ids = set(active_ids or ())
    try:
        candidates = [
            p for p in runs_dir.glob("*.jsonl")
            if p.stem not in active_ids
        ]
    except OSError:
        return 0
    # 按最近修改时间排序，旧的在前
    candidates.sort(key=lambda p: p.stat().st_mtime)
    removed = 0
    archive_dir = runs_dir / "archive"
    while len(candidates) > keep:
        victim = candidates.pop(0)
        try:
            archive_dir.mkdir(parents=True, exist_ok=True)
            dest = archive_dir / victim.name
            if dest.exists():
                victim.unlink()
            else:
                victim.replace(dest)
            removed += 1
        except OSError:
            continue
    return removed
