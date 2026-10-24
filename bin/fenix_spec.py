#!/usr/bin/env python3
"""
fenix_spec.py — fenix 原生 SPEC 生成 CLI。

提供 `new change` / `status --change --json` /
`instructions <artifact> --change --json` 三个命令，全部输出 JSON，
供 fenix-new skill 调用。无需安装 npm 依赖。

用法（项目根目录下经 .fenix 软链接调用）:
    python3 .fenix/bin/fenix_spec.py new <name>
    python3 .fenix/bin/fenix_spec.py status --change <name>
    python3 .fenix/bin/fenix_spec.py instructions <artifact-id> --change <name>
"""

import argparse
import json
import sys
from pathlib import Path

# 框架根（.resolve() 跟随 .fenix 软链接，定位真实安装位置）：schemas/ 与 core/ 所在目录
FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent
if str(FRAMEWORK_ROOT) not in sys.path:
    sys.path.insert(0, str(FRAMEWORK_ROOT))

# 项目根（经 .fenix/bin/ 软链接调用时 = 项目目录）
PROJECT_ROOT = Path(__file__).absolute().parent.parent.parent

from core.spec_gen import instructions, new_change, status  # noqa: E402


def _emit(payload: dict, ok: bool = True):
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not ok:
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="fenix 原生 SPEC 生成 CLI（JSON 输出）")
    parser.add_argument(
        "--project",
        default=None,
        help="项目根目录（默认由脚本位置推断，经 .fenix/bin/ 调用时即项目目录）",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_new = subparsers.add_parser("new", help="创建 change 脚手架")
    p_new.add_argument("name", help="kebab-case change 名称")

    p_status = subparsers.add_parser("status", help="查看 change 的 artifact 完成状态")
    p_status.add_argument("--change", required=True, help="change 名称")

    p_ins = subparsers.add_parser("instructions", help="获取指定 artifact 的生成指引")
    p_ins.add_argument("artifact", help="artifact id（proposal / specs / design / tasks）")
    p_ins.add_argument("--change", required=True, help="change 名称")

    # --project 同时挂在各子 parser 上，使其置于子命令之前或之后均可；
    # 子 parser 侧用 SUPPRESS 默认值，避免未传参时以 None 覆盖顶层已解析值。
    for _sub in (p_new, p_status, p_ins):
        _sub.add_argument(
            "--project",
            default=argparse.SUPPRESS,
            help="项目根目录（等价于顶层 --project，子命令前后位置均可）",
        )

    args = parser.parse_args()
    try:
        # 路径解析收口进 try（与 fenix_archive.py 同场景防护对齐）：expanduser
        # 解析不出家目录抛 RuntimeError、含空字节路径在构造/resolve 阶段抛
        # ValueError，裸抛会绕过 _run 的统一 JSON 兜底，进程以 traceback 收场。
        project_root = Path(args.project).expanduser().resolve() if args.project else PROJECT_ROOT
    except (ValueError, OSError, RuntimeError) as e:
        # 错误基座与 _run 各命令分支同形（new 带 path 键），下游按命令解析不缺字段
        error_base = {"ok": False, "path": None} if args.command == "new" else {"ok": False}
        _emit({**error_base, "error": str(e)}, ok=False)
        return
    # 直接以框架 bin/ 路径调用时 PROJECT_ROOT 三级上溯会指到仓库父目录（其下无 spec/）。
    # new 是创建性命令，会在错误根下 mkdir 出错位脚手架（fenix_archive.py 对同场景
    # 是检测 spec/ 缺失即回退框架根），故在 new 分支内前置拒绝而非仅附报错提示；
    # 其余只读命令维持报错路径附加推断根与 --project 指引（root_hint）。
    root_hint = (
        ""
        if args.project or (project_root / "spec").exists()
        else f"（默认项目根推断为 {project_root}，其下不存在 spec/ —— 请用 --project 显式指定项目根目录）"
    )

    def _run(payload_fn, error_base):
        # 三个命令分支共用：调用抛 ValueError/OSError 时统一转 {ok: False, error: ...} 输出；
        # 其余异常类型（如 schema.yaml 损坏抛 yaml.YAMLError）兜底转同类载荷（附异常类型名），
        # 保证 stdout 恒有 JSON，消费方不会拿到空输出而无法区分命令失败与输出损坏。
        try:
            _emit(payload_fn())
        except (ValueError, OSError) as e:
            _emit({**error_base, "error": str(e) + root_hint}, ok=False)
        except Exception as e:
            _emit({**error_base, "error": f"{type(e).__name__}: {e}"}, ok=False)

    if args.command == "new":
        # 与 fenix_archive.py 的 spec/ 缺失防线对齐：new 未经 .fenix 软链接且未显式
        # 传 --project 时推断根可能指到仓库父目录，new_change 的 mkdir(parents=True)
        # 会成功在错误根下创建 spec/changes/<name>，故此处直接拒绝执行。
        if not args.project and not (project_root / "spec").exists():
            _emit(
                {
                    "ok": False,
                    "path": None,
                    "error": (
                        f"项目根推断为 {project_root}，其下不存在 spec/ —— "
                        "疑似直接以框架 bin/ 路径调用，拒绝创建错位脚手架；"
                        "请用 --project 显式指定项目根目录"
                    ),
                },
                ok=False,
            )
            return
        _run(
            lambda: {"ok": True, "path": str(new_change(project_root, args.name)), "error": None},
            {"ok": False, "path": None},
        )
    elif args.command == "status":
        _run(lambda: status(project_root, args.change), {"ok": False})
    elif args.command == "instructions":
        _run(lambda: instructions(project_root, args.artifact, args.change), {"ok": False})


if __name__ == "__main__":
    main()
