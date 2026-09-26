#!/usr/bin/env python3
"""
fenix_archive.py — 将已完成的 change 归档到 spec/archive/YYYY-MM-DD-<name>。

用法（项目根目录下经 .fenix 软链接调用）:
    python3 .fenix/bin/fenix_archive.py <name>
"""

import argparse
import json
import re
import shutil
import sys
from datetime import date
from pathlib import Path

# 项目根（经 .fenix/bin/ 软链接调用时 = 项目目录）
PROJECT_ROOT = Path(__file__).absolute().parent.parent.parent
# 框架根（.resolve() 跟随 .fenix 软链接，定位真实安装位置）：core/ 所在目录
FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent
# 直接以 bin/ 路径调用时上面的三级上溯会落到仓库外目录：校验 spec/ 缺失则
# 回退到框架根（自举仓库下与项目根重合，同为 .resolve() 口径），
# 此时 main() 会向 stderr 提示实际使用的根。
PROJECT_ROOT_FALLBACK = not (PROJECT_ROOT / "spec").is_dir()
if PROJECT_ROOT_FALLBACK:
    PROJECT_ROOT = FRAMEWORK_ROOT

# change 名称安全白名单：仅字母/数字/点/下划线/连字符（不含路径分隔符），
# 防止 name 携带 `../` 或绝对路径成分越出 spec/changes/ 目录。
_SAFE_NAME_RE = re.compile(r"[A-Za-z0-9._-]+")


def archive_change(project_root: Path, name: str) -> dict:
    """将 `spec/changes/<name>/` 移动到 `spec/archive/YYYY-MM-DD-<name>`。

    Returns:
        dict: {"from": 原路径, "to": 目标路径}

    Raises:
        ValueError: name 含非法字符，或 change 不存在，或目标归档路径已存在（不覆盖）。
    """
    if not _SAFE_NAME_RE.fullmatch(name) or name in (".", ".."):
        raise ValueError(
            f"Illegal change name: {name} — 名称仅允许字母、数字、点、下划线、连字符，"
            "且不能为 '.' 或 '..'"
        )

    change_dir = project_root / "spec" / "changes" / name
    if not change_dir.is_dir():
        raise ValueError(f"Change '{name}' not found at {change_dir}")

    target = project_root / "spec" / "archive" / f"{date.today().isoformat()}-{name}"
    # [fenix-ignore:4d8934ef8959] target 被并发创建为普通文件时不会静默覆盖：源 change_dir 必为目录，rename(目录, 已存在文件) 报 ENOTDIR，shutil.move 的 copytree 回退再抛 FileExistsError（OSError 族，main 已统一捕获），move 不会返回 moved == target，change_dir 与既有文件均原样保留
    if target.exists():
        raise ValueError(
            f"Archive target already exists: {target} — 请改名或改日再归档，原目录不会被覆盖"
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    moved = Path(shutil.move(str(change_dir), str(target)))
    if moved != target:
        # TOCTOU：exists 检查与 move 之间 target 若被并发创建为目录，
        # shutil.move 会把 change 目录嵌套移入 target 内部（target/<name>）
        # 造成归档层级漂移。移回原位并报错（不覆盖既有目录）；不用 os.rename
        # 替代是因为归档可能跨设备（rename 会 EXDEV 失败）。
        shutil.move(str(moved), str(change_dir))
        raise ValueError(
            f"Archive target already exists: {target} — 请改名或改日再归档，原目录不会被覆盖"
        )
    result = {"from": str(change_dir), "to": str(moved)}

    # remove-auto-run-cleanup：run 产物归档的唯一入口 = SPEC 归档。
    # change 目录移动成功后，把 .fenix/runs/ 顶层属于该 spec 的产物移入
    # archive/（不删除任何文件）。fail-open（design D4）：runs 归档失败
    # 仅在返回 dict 追加告警字段，不阻断 change 归档主流程。
    # core 从框架根导入（对齐 fenix_spec.py FRAMEWORK_ROOT 先例）：自举仓库
    # 下即 project_root，第三方项目下跟随 .fenix 软链接定位安装位置。
    if str(FRAMEWORK_ROOT) not in sys.path:
        sys.path.insert(0, str(FRAMEWORK_ROOT))
    try:
        from core.agent_runner.run_files import archive_spec_runs

        result["runs_archived"] = archive_spec_runs(project_root / ".fenix" / "runs", name)
    except Exception as e:  # fail-open：move 已成功，任意异常只降级为告警不改变整体结果
        result["runs_archive_warning"] = str(e)

    # 归档自动提交：移动成功立即入库（fail-open，见 core/archive_commit.py）
    try:
        from core.archive_commit import commit_archive_move

        cr = commit_archive_move(project_root, name, moved)
        result["committed"] = cr["committed"]
        if cr.get("warning"):
            result["commit_warning"] = cr["warning"]
    except Exception as e:  # fail-open：move 已成功，提交失败只降级为告警
        result["committed"] = False
        result["commit_warning"] = str(e)
    return result


def main():
    parser = argparse.ArgumentParser(description="归档 change 到 spec/archive/")
    parser.add_argument("name", help="要归档的 change 名称")
    parser.add_argument(
        "--project",
        default=None,
        help="项目根目录（默认由脚本位置推断，经 .fenix/bin/ 调用时即项目目录）",
    )
    args = parser.parse_args()

    project_root = Path(args.project).expanduser().resolve() if args.project else PROJECT_ROOT
    if args.project is None and PROJECT_ROOT_FALLBACK:
        # 提示走 stderr，避免破坏下游对 stdout JSON 的解析
        print(f"fenix_archive: 项目根回退到框架根: {project_root}", file=sys.stderr)

    try:
        result = archive_change(project_root, args.name)
        payload = {"ok": True, "from": result["from"], "to": result["to"], "error": None}
        for key in ("runs_archived", "runs_archive_warning", "committed", "commit_warning"):
            if key in result:
                payload[key] = result[key]
    except (ValueError, OSError) as e:
        # OSError：shutil.move 因权限/只读盘等失败，或 is_dir() 检查与移动之间
        # 目录被并发移走的竞态——与 ValueError 同走统一 JSON 错误载荷。
        payload = {"ok": False, "from": None, "to": None, "error": str(e)}

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not payload["ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
