#!/usr/bin/env python3
"""
fenix_cli.py — Fenix CLI 工具集（add-draft-promotion-gate D6）。

提供人工操作子命令（promote、review 等），与 Dashboard API 共享同一晋升语义。
不挂载 fenixd.py（误执行会拉起 daemon），独立入口。

用法:
    python3 bin/fenix_cli.py promote <spec> [--project <path>]
    python3 bin/fenix_cli.py review <spec> [--project <path>]
    python3 bin/fenix_cli.py reflow <spec> [--project <path>]
    python3 bin/fenix_cli.py activate <spec> [--project <path>]
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
        # 对齐 fenix_archive/fenix_dashboard 口径：先展开 ~ 前缀再解析，
        # 避免 ~/x 被误判为非 Fenix 项目目录且报错指向不存在的字面路径
        proot = Path(args_project).expanduser().resolve()
    else:
        proot = Path.cwd()
    if not (proot / ".fenix" / "STATE.md").exists():
        print(f"错误：{proot} 不是 Fenix 项目目录（缺少 .fenix/STATE.md）", file=sys.stderr)
        sys.exit(1)
    return proot


def cmd_promote(args):
    """晋升 drafted SPEC → ready / reviewing（按评审判定分流）。"""
    from core.pm_engine.promotion import promote_drafted
    from core.state_machine import StateMachine, project_state_logger
    from core.config import ConfigLoader

    proot = _resolve_project_root(args.project)
    # 复用按项目根缓存的 state logger：本就指向 .fenix/logs/fenixd.log 且与
    # STATE 写入同源；另构造 Logger 会摘除其 handler 并把留痕散落 <proot>/fenixd.log
    logger = project_state_logger(proot)
    sm = StateMachine(proot / ".fenix" / "STATE.md", logger)

    # 解析项目有效配置（用户级 + 项目级深合并），使评审分流判定与 daemon
    # 同源——不传 config 时 promote_drafted 无法评估跳过白名单，恒直通 ready。
    config = ConfigLoader.resolve_config(proot)

    result = promote_drafted(proot, args.spec, state_machine=sm, logger=logger, config=config)
    if result.get("ok"):
        # 依 promote_drafted 的分流结论执行转移（add-spec-review-gate 3.4）：
        # 命中跳过白名单 → ready；否则 → reviewing 待方案评审。与 _on_spec_drafted
        # 收尾语义一致，MUST NOT 硬编码 ready（否则 CLI 通道绕过评审门禁）。
        # 缺失分流结论 = 契约破坏，显式报错退出而非静默回退 ready——回退恰好
        # 复现本注释要防的绕过路径（code-review item 4103a14bb72e）。
        next_status = result.get("next_status")
        if not next_status:
            print(
                "✗ 晋升失败：promote_drafted 返回缺少 next_status 分流结论（契约破坏），"
                "MUST NOT 回退 ready 绕过评审门禁，请人工核查",
                file=sys.stderr,
            )
            sys.exit(1)
        # fix-observability-gaps 2.2：CLI 人工晋升来源（channel=manual）
        # transition 返回 False（spec 缺失或并发下状态已变，promote_drafted
        # 校验与 transition 落盘之间存在 TOCTOU）时如实报错退出，MUST NOT
        # 无条件宣称晋升成功误导人工操作者。
        if not sm.transition(
            args.spec, next_status,
            trigger_run_id=None, agent_type=None, channel="manual",
        ):
            print(
                "✗ 状态转移被拒（可能已被并发转移），请核查 STATE.md 当前状态",
                file=sys.stderr,
            )
            sys.exit(1)
        if next_status == "reviewing":
            print(f"✓ SPEC「{args.spec}」已晋升 reviewing（待方案评审），等待评审 run")
        else:
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
    from core.state_machine import StateMachine, project_state_logger

    proot = _resolve_project_root(args.project)
    # 同 cmd_promote：复用缓存 state logger（.fenix/logs），勿另构造 Logger 摘其 handler
    logger = project_state_logger(proot)
    sm = StateMachine(proot / ".fenix" / "STATE.md", logger)

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


def cmd_activate(args):
    """激活待激活 SPEC（start_after manual → null，立即进入调度）。

    判定与执行收敛到 core/dashboard/data/admin_actions.activate_spec 单一
    实现点（add-spec-manual-activation D6）——CLI 与 Dashboard API 共用同一
    幂等语义（非待激活拒绝、终态拒绝、found 404），MUST NOT 在 CLI 侧复写。

    信号写入结果如实回报（fix-scheduling-kick-single-slot D3/2.5）：start_after
    已成功置 null（exit 0），但即时唤醒信号写出失败时不宣称「立即进入调度」，
    改为提示将由下次扫描派发——CLI 是与 Dashboard 并列的第二个「动作方」。
    """
    from core.dashboard.data.admin_actions import activate_spec

    proot = _resolve_project_root(args.project)
    result = activate_spec(proot, args.spec)
    if result.get("ok"):
        kick = result.get("scheduling_kick")
        if kick and not kick.get("ok"):
            print(
                f"✓ SPEC「{args.spec}」已激活（start_after manual → null），"
                f"但即时唤醒信号写入失败，将由下次扫描（缺省 ≤30 分钟）派发"
            )
        else:
            print(f"✓ SPEC「{args.spec}」已激活，立即进入调度（start_after manual → null）")
        sys.exit(0)
    else:
        if not result.get("found"):
            reason = f"SPEC「{args.spec}」不存在于 STATE.md"
        elif result.get("terminal"):
            reason = f"终态 SPEC「{args.spec}」不可激活"
        else:
            reason = result.get("reason") or "未知原因"
        print(f"✗ 激活被拒绝：{reason}", file=sys.stderr)
        sys.exit(1)


def cmd_reflow(args):
    """task-gap 滞留 verified SPEC 的人工回炉（verified → ready）。

    判定与执行收敛到 core/pm_engine/task_reflow.reflow_spec 单一实现点
    （fix-impl-tasks-completion-gate D8）——CLI 与 Dashboard API 共用同一开放
    条件、同一执行语义、同一日志留痕，MUST NOT 在 CLI 侧复写一套判定逻辑
    （add-spec-review-gate 的 CLI 绕过评审分流教训）。
    """
    from core.pm_engine.task_reflow import reflow_spec
    from core.state_machine import StateMachine, project_state_logger

    proot = _resolve_project_root(args.project)
    # 同 cmd_promote：复用缓存 state logger（.fenix/logs），勿另构造 Logger 摘其 handler
    logger = project_state_logger(proot)
    sm = StateMachine(proot / ".fenix" / "STATE.md", logger)

    result = reflow_spec(proot, args.spec, state_machine=sm, logger=logger, source="cli")
    if result.get("ok"):
        gap = result.get("gap_tasks") or []
        gap_note = f"（缺口 {len(gap)} 项）" if gap else ""
        print(
            f"✓ SPEC「{args.spec}」已回炉复位为 ready{gap_note}，"
            f"daemon 将重新派发实现者承接剩余任务"
        )
        sys.exit(0)
    else:
        print(f"✗ 回炉被拒绝：{result.get('reason') or '未知原因'}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Fenix CLI 工具集（人工操作子命令）",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_promote = subparsers.add_parser(
        "promote",
        help="晋升 drafted SPEC → ready/reviewing（按评审判定分流，软化+lint+transition）",
    )
    p_promote.add_argument("spec", help="要晋升的 SPEC 名称")
    p_promote.add_argument(
        "--project",
        "-p",
        default=None,
        help="项目根目录（默认当前目录）",
    )

    p_review = subparsers.add_parser(
        "review",
        help="重新评审 blocked SPEC（评审相关 blocked → reviewing）",
    )
    p_review.add_argument("spec", help="要重新评审的 SPEC 名称")
    p_review.add_argument(
        "--project",
        "-p",
        default=None,
        help="项目根目录（默认当前目录，挂在 review 子解析器下）",
    )

    p_reflow = subparsers.add_parser(
        "reflow",
        help="task-gap 滞留 verified SPEC 人工回炉（verified → ready，重派实现者）",
    )
    p_reflow.add_argument("spec", help="要回炉的 SPEC 名称")
    p_reflow.add_argument(
        "--project",
        "-p",
        default=None,
        help="项目根目录（默认当前目录）",
    )

    p_activate = subparsers.add_parser(
        "activate",
        help="激活待激活 SPEC（start_after manual → null，立即进入调度）",
    )
    p_activate.add_argument("spec", help="要激活的 SPEC 名称")
    p_activate.add_argument(
        "--project",
        "-p",
        default=None,
        help="项目根目录（默认当前目录）",
    )

    args = parser.parse_args()

    if args.command == "promote":
        cmd_promote(args)
    elif args.command == "review":
        cmd_review(args)
    elif args.command == "reflow":
        cmd_reflow(args)
    elif args.command == "activate":
        cmd_activate(args)
    # 未知命令分支不存在：subparsers required=True 使 parse_args 对非法/缺失
    # 命令直接报错退出（code-review item 76318b16fefc），此处四分支已穷尽。


if __name__ == "__main__":
    main()
