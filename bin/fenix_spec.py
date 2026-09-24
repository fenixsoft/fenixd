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

    args = parser.parse_args()
    project_root = Path(args.project).expanduser().resolve() if args.project else PROJECT_ROOT
    # 直接以框架 bin/ 路径调用时 PROJECT_ROOT 三级上溯会指到仓库父目录（其下无 spec/），
    # 各命令报错路径随之误导排查：此场景下给错误信息附加推断根与 --project 指引。
    root_hint = (
        ""
        if args.project or (project_root / "spec").exists()
        else f"（默认项目根推断为 {project_root}，其下不存在 spec/ —— 请用 --project 显式指定项目根目录）"
    )

    if args.command == "new":
        try:
            path = new_change(project_root, args.name)
            _emit({"ok": True, "path": str(path), "error": None})
        except ValueError as e:
            _emit({"ok": False, "path": None, "error": str(e) + root_hint}, ok=False)
    elif args.command == "status":
        try:
            _emit(status(project_root, args.change))
        except ValueError as e:
            _emit({"ok": False, "error": str(e) + root_hint}, ok=False)
    elif args.command == "instructions":
        try:
            _emit(instructions(project_root, args.artifact, args.change))
        except ValueError as e:
            _emit({"ok": False, "error": str(e) + root_hint}, ok=False)


if __name__ == "__main__":
    main()
