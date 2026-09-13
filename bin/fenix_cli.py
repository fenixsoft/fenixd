#!/usr/bin/env python3
"""
fenix_cli.py — Fenix CLI 工具集（add-draft-promotion-gate D6）。

提供人工操作子命令（promote、review 等），与 Dashboard API 共享同一晋升语义。
不挂载 fenixd.py（误执行会拉起 daemon），独立入口。

用法:
    python3 bin/fenix_cli.py promote <spec> [--project <path>]
    python3 bin/fenix_cli.py review <spec> [--project <path>]
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
            print("✗ 晋升 lint 未通过：", file=sys.stderr)
            for v in result["violations"]:
                print(f"  - {v}", file=sys.stderr)
        else:
            print("✗ 晋升失败", file=sys.stderr)
        sys.exit(1)


def cmd_review(args):
    """重新评审 blocked SPEC（评审相关 blocked → reviewing）。"""
    from core.state_machine import StateMachine, FROZEN_FIELD
    from core.logger import Logger

    proot = _resolve_project_root(args.project)
    sm = StateMachine(proot / ".fenix" / "STATE.md", None)
    logger = Logger(proot)

    entry = sm.read_one(args.spec)
    if not entry:
        print(f"✗ SPEC「{args.spec}」不存在于 STATE.md", file=sys.stderr)
        sys.exit(1)

    # 沿用 SpecReviewManager.re_review 的开放条件校验
    from core.pm_engine.spec_review import SpecReviewManager
    review_manager = SpecReviewManager(proot, sm, None, None, {}, logger)
    ok, msg = review_manager.re_review(args.spec)
    if ok:
        print(f"✓ SPEC「{args.spec}」已重新进入评审（reviewing），等待评审 run")
        sys.exit(0)
    else:
        print(f"✗ 重新评审被拒绝：{msg}", file=sys.stderr)
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

    p_review = subparsers.add_parser(
        "review",
        help="重新评审 blocked SPEC（评审相关 blocked → reviewing）",
    )
    p_review.add_argument("spec", help="要重新评审的 SPEC 名称")
    p_review.add_argument(
        "--project", "-p",
        default=None,
        help="项目根目录（默认当前目录，挂在 review 子解析器下）",
    )

    args = parser.parse_args()

    if args.command == "promote":
        cmd_promote(args)
    elif args.command == "review":
        cmd_review(args)
    else:
        print(f"未知命令：{args.command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()