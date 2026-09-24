#!/usr/bin/env python3
"""
fenix_session.py — 为 Fenixd 项目计算唯一 tmux session 名并查询运行状态（CLI）。

核心判定逻辑已抽到 core/fenix_session.py（供 dashboard 健康检测共享），
本脚本为薄 CLI 包装，对外契约保持不变：

用法
----
    python3 fenix_session.py name [PROJECT_ROOT]      # 打印 session 名
    python3 fenix_session.py running [PROJECT_ROOT]   # 打印 YES / NO
    python3 fenix_session.py path [PROJECT_ROOT]      # 打印规范化项目根路径

PROJECT_ROOT 省略时取当前目录。
"""

import sys
from pathlib import Path

# 与 bin/fenix_dashboard.py 相同的路径解析：经项目内 .fenix/bin/ 软链接调用时
# 保持 __file__ 不跟随软链接（absolute 而非 resolve），core 位于 ../..（.fenix）；
# 直接以框架 bin/ 调用时 core 位于 ..
_THIS_DIR = Path(__file__).absolute().parent
_FENIX_DIR = _THIS_DIR.parent
if str(_FENIX_DIR) not in sys.path:
    sys.path.insert(0, str(_FENIX_DIR))

from core.fenix_session import is_running, resolve_root, session_name  # noqa: E402


def main() -> int:
    args = sys.argv[1:]
    if len(args) > 2:
        print(__doc__, file=sys.stderr)
        return 2
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
