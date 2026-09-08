#!/usr/bin/env python3
"""
fenix_cli.py — Fenix CLI 工具集（add-draft-promotion-gate D6）。

提供人工操作子命令（promote 等），与 Dashboard API 共享同一晋升语义。
不挂载 fenixd.py（误执行会拉起 daemon），独立入口。

用法:
    python3 bin/fenix_cli.py promote <spec> [--project <path>]
"""

import argparse
import sys
from pathlib import Path

# 框架根（定位 core/）
FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FRAMEWORK_ROOT))


def _resolve_project_root(args_project: str | None) -> Path:
    """解析项目根路径：--project 或当前目录。"""
    if args_project:
        proot = Path(args_project).resolve()
    else:
        proot = Path.cwd()
    if not (proot / ".fenix" / "STATE.md").exists():
        print(f"错误：{proot} 不是 Fenix 项目目录（缺少 .fenix/STATE.md）",
              file=sys.stderr)
        sys.exit(1)
    return proot


def cmd_promote(args):
    """晋升 drafted SPEC → ready。"""
    from core.pm_engine.promotion import promote_drafted
    from core.state_machine import StateMachine
    from core.logger import Logger

    proot = _resolve_project_root(args.project)
    sm = StateMachine(proot / ".fenix" / "STATE.md", None)
    logger = Logger(proot)

    result = promote_drafted(proot, args.spec, state_machine=sm, logger=logger)
    if result["ok"]:
        # transition drafted → ready（由 watcher/full_scan 感知派发）
        sm.transition(args.spec, "ready")
        print(f"✓ SPEC「{args.spec}」已晋升 ready，等待调度")
        sys.exit(0)
    else:
        if "reason" in result:
            print(f"✗ 晋升被拒绝：{result['reason']}", file=sys.stderr)
        elif "violations" in result and result["violations"]:
            print(f"✗ 晋升 lint 未通过：", file=sys.stderr)
            for v in result["violations"]:
                print(f"  - {v}", file=sys.stderr)
        else:
            print(f"✗ 晋升失败", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Fenix CLI 工具集（人工操作子命令）",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_promote = subparsers.add_parser(
        "promote",
        help="晋升 drafted SPEC → ready（软化+lint+transition）",
    )
    p_promote.add_argument("spec", help="要晋升的 SPEC 名称")
    p_promote.add_argument(
        "--project", "-p",
        default=None,
        help="项目根目录（默认当前目录）",
    )

    args = parser.parse_args()

    if args.command == "promote":
        cmd_promote(args)
    else:
        print(f"未知命令：{args.command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
