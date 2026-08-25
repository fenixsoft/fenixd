#!/usr/bin/env python3
"""
fenix_session.py — 为 Fenixd 项目计算唯一 tmux session 名并查询运行状态。

背景
----
早期框架用固定 tmux session 名 `fenixd`，同一台机器只能同时运行一个
fenixd daemon。本工具按「项目根路径」派生确定性、唯一的 session 名
（fenixd-<目录名>-<路径哈希6位>），使多个 Fenixd 项目可并行开发，
互不干扰（日志、STATE.md、config.yaml 本就按项目隔离，唯一冲突点
就是 session 名）。

用法
----
    python3 fenix_session.py name [PROJECT_ROOT]      # 打印 session 名
    python3 fenix_session.py running [PROJECT_ROOT]   # 打印 YES / NO
    python3 fenix_session.py path [PROJECT_ROOT]      # 打印规范化项目根路径

PROJECT_ROOT 省略时取当前目录。

兼容性
------
`running` 同时识别旧版固定名 `fenixd`：若该 session 存在且其工作目录
（pane_current_path）解析后等于目标项目根，则视为「该项目 daemon 正在
运行」。这样升级后既有项目（如 fenix-desktop）的旧 daemon 仍被正确
识别，避免重复启动；新项目则使用派生出的唯一 session 名。
"""

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

LEGACY_SESSION = "fenixd"


def resolve_root(root: str | None = None) -> Path:
    """规范化项目根路径（展开 ~ 与软链接）。"""
    return Path(root or os.getcwd()).expanduser().resolve()


def session_name(root: str | None = None) -> str:
    """按项目根路径派生唯一 session 名。

    同一项目经不同入口（技能 / 状态栏 / 仪表盘）计算得到的结果一致；
    不同项目（即使目录同名）因哈希不同而唯一。
    """
    proot = resolve_root(root)
    digest = hashlib.md5(str(proot).encode()).hexdigest()[:6]
    base = re.sub(r"[^A-Za-z0-9_.-]+", "-", proot.name).strip("-.") or "project"
    return f"fenixd-{base}-{digest}"


def _legacy_session_matches(root: Path) -> bool:
    """旧版固定 session `fenixd` 是否属于该项目（按其 cwd 判断）。"""
    try:
        r = subprocess.run(
            ["tmux", "list-panes", "-t", LEGACY_SESSION, "-F", "#{pane_current_path}"],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return False
    if r.returncode != 0:
        return False
    for line in r.stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            if Path(line).expanduser().resolve() == root:
                return True
        except Exception:
            continue
    return False


def is_running(root: str | None = None) -> bool:
    """该项目是否有 daemon 在运行（唯一名 + 旧版兼容）。"""
    proot = resolve_root(root)
    try:
        r = subprocess.run(
            ["tmux", "has-session", "-t", session_name(proot)],
            capture_output=True,
            timeout=2,
        )
        if r.returncode == 0:
            return True
    except Exception:
        pass
    return _legacy_session_matches(proot)


def main() -> int:
    args = sys.argv[1:]
    cmd = args[0] if args else "name"
    root = args[1] if len(args) > 1 else None

    if cmd == "name":
        print(session_name(root))
    elif cmd == "running":
        print("YES" if is_running(root) else "NO")
    elif cmd == "path":
        print(resolve_root(root))
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
