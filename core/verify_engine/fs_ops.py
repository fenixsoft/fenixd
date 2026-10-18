"""fs_ops.py — verify_engine 原子写盘统一出口（跨模块共用口径）。

mkstemp + fdopen 失败接管 + flush/fsync + ``os.replace`` + 目录 fsync +
异常清理退痕的原子写正文此前在 judge_files._atomic_write_json、
engine._write_progress / _save_report、scenarios.write_scenarios_array、
visual_diff._save_baseline_streaks / _mark_suspicious 六处平行复刻
（code-review items 24106d6108e2 / d1a142dccb99 / 0b7c1aa62ab1），差异仅在
json 缩进、临时文件前后缀与调用方的异常降级策略，任何口径调整（如补目录
项持久化）都需多处同步改写且已有漂移先例（_fsync_dir / 文件 fsync 仅部分
位点具备）。本模块把正文收敛为单一出口；fdopen 失败接管沿用仓库统一口径
（code-review item cbb57806fbfd / 794cfb6f999c）：with 的 close 只在 fdopen
成功后才生效，fdopen 自身抛错时裸 fd 无人关闭——f 为 None 时兜底 os.close。
同 path_safety 的下沉先例：本模块只依赖标准库，不引入反向依赖。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def fsync_dir(path: Path) -> None:
    """fsync 父目录，持久化 rename 的目录项元数据（原 judge_files._fsync_dir）。

    POSIX 语义下 os.replace 落盘数据不等于目录项已持久化，主机掉电后
    可能 tmp 与目标文件一起消失。尽力而为：fsync 目录失败不阻断主流程。
    """
    try:
        dir_fd = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass


def atomic_write_json(
    path: Path,
    payload: Any,
    *,
    tmp_prefix: str,
    tmp_suffix: str = ".json.tmp",
    indent: int | None = 2,
) -> None:
    """mkstemp 原子写盘统一正文：同目录临时文件 + fdopen 失败接管
    （cbb57806fbfd 口径）+ flush/fsync + ``os.replace`` + fsync_dir，
    异常时清理临时文件后原样上抛。

    临时文件前缀/后缀与 json 缩进由调用方传入以保持各处盘上形态不变
    （统一前各位点即此两态）；父目录 mkdir 与异常降级策略（上抛 / 记
    日志降级返回）属调用方语义，由调用方在调用前后落实。
    """
    path = Path(path)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), prefix=tmp_prefix, suffix=tmp_suffix
    )
    try:
        # fdopen 失败路径显式接管（cbb57806fbfd 口径）：with 的 close 只在
        # fdopen 成功后才生效，fdopen 自身抛错时裸 fd 无人关闭——f 为 None
        # 时兜底 os.close。
        f = None
        try:
            f = os.fdopen(fd, "w", encoding="utf-8")
            json.dump(payload, f, ensure_ascii=False, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        finally:
            if f is not None:
                f.close()
            else:
                try:
                    os.close(fd)
                except OSError:
                    pass
        os.replace(tmp_path, path)
        fsync_dir(path.parent)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
