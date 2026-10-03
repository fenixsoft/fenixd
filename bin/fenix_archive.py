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


def ensure_framework_path() -> None:
    """把 FRAMEWORK_ROOT 注入 sys.path（幂等），供各处延迟导入 core/ 复用。

    core 从框架根导入：自举仓库下即 project_root，第三方项目下跟随
    .fenix 软链接定位安装位置。
    """
    if str(FRAMEWORK_ROOT) not in sys.path:
        sys.path.insert(0, str(FRAMEWORK_ROOT))


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
        # 造成归档层级漂移。原位空闲则移回原位并报错（不覆盖既有目录）；
        # 原位若已被并发者重建为同名目录则放弃回滚直接报错。不用 os.rename
        # 替代是因为归档可能跨设备（rename 会 EXDEV 失败）。
        if change_dir.is_dir():
            # 此时再移回原位会被 shutil.move 嵌套进 change_dir/<name> 内部
            # （层级二次漂移），报错须带上 moved 实际路径供排障者直接定位。
            raise ValueError(
                f"Archive target already exists: {target} — 原位 {change_dir} "
                f"已被并发重建，误移内容保留在 {moved}，请手工核对处置"
            )
        try:
            shutil.move(str(moved), str(change_dir))
        except OSError as e:
            # 回滚移回原位自身失败（原位被占、跨设备复制中断等）时内容仍滞留
            # 在 target/<name> 嵌套层级，报错须带上 moved 实际路径供排障者
            # 直接定位，与上方并发重建分支的处置口径对齐；转 ValueError 走
            # main 统一 JSON 错误载荷（OSError 裸抛只显示 errno 文案）。
            raise ValueError(
                f"Archive rollback failed: {e} — 回滚移回原位失败，"
                f"误移内容保留在 {moved}，请手工核对处置"
            ) from e
        # 二次 TOCTOU：回滚 move 前 is_dir 检查与移动之间原位若被并发者重建
        # 为同名目录，shutil.move 会把内容静默嵌套移入该目录内部（moved 派生
        # 路径 change_dir/moved.name）而不抛异常，统一报错文案找不到内容；
        # 报错须带上实际落点，与上方并发重建/回滚失败分支的处置口径对齐。
        nested = change_dir / moved.name
        if nested.exists():
            raise ValueError(
                f"Archive target already exists: {target} — 回滚时原位 {change_dir} "
                f"已被并发重建，误移内容嵌套保留在 {nested}，请手工核对处置"
            )
        raise ValueError(
            f"Archive target already exists: {target} — 请改名或改日再归档，原目录不会被覆盖"
        )
    result = {"from": str(change_dir), "to": str(moved)}

    # 归档成功即迁出 STATE.md 条目（add-archive-state-migration 2.3/D3）：
    # 目录已移入 archive/ 后，把该 change 的 STATE.md 条目迁出至归档清单
    # .fenix/STATE.archive.md（archived_by=cli）。STATE 无条目（手工创建目录等）
    # 输出说明性字段不报错；迁出异常 fail-open 为告警字段，不回滚目录移动、
    # 不改变归档成功语义（与下方 commit_archive_move 同风格）。core 从框架根
    # 导入（对齐上方 runs 归档的 FRAMEWORK_ROOT 先例）。
    ensure_framework_path()
    state_md = Path(project_root) / ".fenix" / "STATE.md"
    if not state_md.exists():
        result["state_evicted"] = False
        result["state_evict_note"] = "项目无 STATE.md，无条目可迁出"
    else:
        try:
            from core.state_machine import StateMachine, project_state_logger

            sm = StateMachine(state_md, project_state_logger(project_root))
            ev = sm.evict_spec(name, archived_by="cli")
            result["state_evicted"] = bool(ev.get("ok"))
            if ev.get("found") is False:
                result["state_evict_note"] = (
                    "STATE.md 无该 change 条目（从未注册或已迁出）"
                )
            elif not ev.get("ok"):
                result["evict_warning"] = ev.get("error")
        except Exception as e:  # fail-open：move 已成功，迁出失败只降级为告警
            result["state_evicted"] = False
            result["evict_warning"] = str(e)

    # remove-auto-run-cleanup：run 产物归档的唯一入口 = SPEC 归档。
    # change 目录移动成功后，清理 .fenix/runs/ 中属于该 spec 的产物
    # （fix-run-cleanup-attach-spec-archive D1：顶层与 archive/ 归档副本
    # 一并删除，产物生命周期绑定 SPEC 生命周期）。fail-open（design D4）：
    # 清理失败仅在返回 dict 追加告警字段，不阻断 change 归档主流程。
    # core 从框架根导入（对齐 fenix_spec.py FRAMEWORK_ROOT 先例）：自举仓库
    # 下即 project_root，第三方项目下跟随 .fenix 软链接定位安装位置。
    ensure_framework_path()
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

    try:
        # 路径解析同样收口进 try：expanduser 解析不出家目录抛 RuntimeError、
        # 含空字节路径在构造/resolve 阶段抛 ValueError，裸抛会绕过下方统一
        # JSON 错误载荷、破坏「stdout 恒输出 JSON」契约。
        project_root = Path(args.project).expanduser().resolve() if args.project else PROJECT_ROOT
        if args.project is None and PROJECT_ROOT_FALLBACK:
            # 提示走 stderr，避免破坏下游对 stdout JSON 的解析
            print(f"fenix_archive: 项目根回退到框架根: {project_root}", file=sys.stderr)

        result = archive_change(project_root, args.name)
        payload = {"ok": True, "from": result["from"], "to": result["to"], "error": None}
        for key in (
            "state_evicted",
            "state_evict_note",
            "evict_warning",
            "runs_archived",
            "runs_archive_warning",
            "committed",
            "commit_warning",
        ):
            if key in result:
                payload[key] = result[key]
    except (ValueError, OSError, RuntimeError) as e:
        # OSError：shutil.move 因权限/只读盘等失败，或 is_dir() 检查与移动之间
        # 目录被并发移走的竞态；RuntimeError：--project expanduser 解析不出家
        # 目录——与 ValueError 同走统一 JSON 错误载荷。
        payload = {"ok": False, "from": None, "to": None, "error": str(e)}

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not payload["ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
