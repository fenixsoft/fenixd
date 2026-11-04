#!/usr/bin/env python3
"""
fenix_session.py — 查询 Fenixd 项目运行状态（CLI）。

核心判定逻辑在 core/fenix_session.py（供 dashboard 健康检测共享），本脚本为
薄 CLI 包装。tmux 会话名体系已随 systemd 承载退役（add-systemd-hosting）：
原 `name` 子命令（打印 tmux session 名，且曾为默认子命令）改为拒绝并指引——
daemon 承载现为 systemd unit ``fenixd-<项目名>.service``，unit 名与启停协议
见 `python3 fenix_session.py unit [PROJECT_ROOT]` 与 /fenix-setup 配方。

用法
----
    python3 fenix_session.py running [PROJECT_ROOT]   # 打印 YES / NO
    python3 fenix_session.py path [PROJECT_ROOT]      # 打印规范化项目根路径
    python3 fenix_session.py unit [PROJECT_ROOT]      # 打印 systemd unit 名

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

from core.fenix_session import is_running, resolve_root  # noqa: E402
from core.systemd_hosting import unit_name_for  # noqa: E402


def main() -> int:
    args = sys.argv[1:]
    if len(args) > 2:
        print(__doc__, file=sys.stderr)
        return 2
    cmd = args[0] if args else None
    root = args[1] if len(args) > 1 else None

    if cmd in (None, "name"):
        # tmux 会话名体系退役（add-systemd-hosting）：`name` 子命令与「无参数
        # 缺省打 session 名」旧行为一并拒绝——脚本若仍按旧默认消费输出，拿到
        # 的必须不是看似合法的会话名（退出码非 0，调用方可见失败）。
        print(
            "tmux 会话名体系已退役（daemon 承载已迁移 systemd unit）。\n"
            f"本项目 unit 名：{unit_name_for(resolve_root(root))}\n"
            "  启动：见 /fenix-setup 配方（start_daemon → systemctl enable --now）\n"
            "  看现场：journalctl -u <unit> + .fenix/logs/supervisor.log",
            file=sys.stderr,
        )
        return 2
    if cmd == "running":
        print("YES" if is_running(root) else "NO")
    elif cmd == "path":
        print(resolve_root(root))
    elif cmd == "unit":
        print(unit_name_for(resolve_root(root)))
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
