#!/usr/bin/env python3
"""fenix_detect_artifacts.py — 构建产物路径纯本地探测脚本。

用法:
    python3 bin/fenix_detect_artifacts.py [项目根目录]
    python3 bin/fenix_detect_artifacts.py --write [项目根目录]

    项目根目录缺省为当前目录。

模式:
    默认（无 --write）：探测并输出候选产物路径 JSON，不修改任何文件。
    --write：探测结果写入项目主树的 .fenix/config.yaml（幂等，不覆盖已显式配置的项目）。

探测信息源（按优先级）：
    1. package.json 的 scripts.build / scripts.dist / scripts.release / scripts.bundle
    2. pyproject.toml 的 [build-system]（poetry setuptools 等 → 检查 dist/）
    3. 项目目录结构：根级 dist/、build/、out/ 目录（独立信息源，仅项目根级，
       不递归子级；Python 项目不列 build/）、release-*.zip 等命名的产物文件（写入具体文件名）
    4. Fenix 框架项目（core/dashboard/static/dist/ 存在时自动包含）

输出（JSON）：
    {
      "has_build_artifacts": true,
      "build_artifact_paths": ["dist/", "release-1.0.zip"],
      "sources": ["package.json scripts.build", "dist/ 存在"],
      "status": "success"
    }

    无候选时：has_build_artifacts=false，build_artifact_paths=[]

退出码:
    0 — 成功（探测完成，无论有无候选）
    1 — 参数错误或项目根目录不存在

示例:
    # 探测当前项目候选路径
    python3 bin/fenix_detect_artifacts.py

    # 探测并将结果写入 .fenix/config.yaml（幂等）
    python3 bin/fenix_detect_artifacts.py --write /path/to/project
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

# 框架根（定位 core/），仿 bin/fenix_cli.py：标准调用 `python3 bin/fenix_detect_artifacts.py`
# 时 sys.path[0] 是 bin/，cwd 不入 path，不加此项则 write_config_if_unresolved 里
# validate_build_artifact_paths 的 import 恒 ImportError 被静默跳过，写入前校验沦为死代码
FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FRAMEWORK_ROOT))


def detect_build_artifacts(project_root: Path) -> dict:
    """纯本地探测项目构建产物路径（无网络、无子进程）。

    Returns: {"has_build_artifacts": bool, "build_artifact_paths": list[str],
              "sources": list[str], "status": str}
    失败/信息不足时返回空候选（has=false），MUST NOT 抛异常。
    """
    result = {
        "has_build_artifacts": False,
        "build_artifact_paths": [],
        "sources": [],
        "status": "success",
    }
    paths_found = set()
    sources = []

    # ── 1. Fenix 框架项目（core/dashboard/static/dist/）────────────────────
    fenix_dist = project_root / "core" / "dashboard" / "static" / "dist"
    if fenix_dist.is_dir():
        # 目录存在且非空即视为框架产物目录（不校验 index.html / hash JS 等产物特征）
        try:
            if any(fenix_dist.iterdir()):
                paths_found.add("core/dashboard/static/dist/")
                sources.append("core/dashboard/static/dist/ 存在且非空")
        except OSError:
            pass  # dist 目录不可读（权限/挂载异常）时跳过该信息源，不阻塞探测

    # ── 2. package.json scripts ──────────────────────────────────────────────
    pkg_json = project_root / "package.json"
    if pkg_json.is_file():
        try:
            # errors="replace"：非 UTF-8 编码（如 GBK）的 package.json 解码不抛
            # UnicodeDecodeError（ValueError 族不在下方 except 内），守住 MUST NOT 抛异常契约
            pkg = json.loads(pkg_json.read_text(encoding="utf-8", errors="replace"))
            # 顶层是合法 JSON 但非对象（[]/字符串/null 等）时 pkg.get 抛 AttributeError，
            # 不在下方 except 内；非 dict 归一为 {} 按无 scripts 处理（与下方 scripts 防御同口径）
            if not isinstance(pkg, dict):
                pkg = {}
            # "scripts" 键存在但为 null 时 get 的默认值不生效，须归一为 dict；
            # 非 dict（数字/字符串等）同样防住，避免迭代抛 TypeError 违反 MUST NOT 抛异常约定
            scripts = pkg.get("scripts") or {}
            if not isinstance(scripts, dict):
                scripts = {}
            has_build_script = any(
                key in ("build", "dist", "release", "bundle")
                for key in scripts
            )
            if has_build_script:
                build_script_keys = [
                    k for k in scripts if k in ("build", "dist", "release", "bundle")
                ]
                sources.append(
                    "package.json scripts: " + ", ".join(build_script_keys)
                )
        except (json.JSONDecodeError, OSError):
            pass  # 损坏的 package.json 不阻塞

    # ── 3. pyproject.toml（Python 项目）──────────────────────────────────────
    pyproject = project_root / "pyproject.toml"
    if pyproject.is_file():
        try:
            # errors="replace" 同 package.json 分支：非 UTF-8 编码不抛 UnicodeDecodeError
            content = pyproject.read_text(encoding="utf-8", errors="replace")
            if "[build-system]" in content or "[tool.poetry]" in content:
                # Python 项目的常见产物目录。site-packages/ 不列为候选：根级出现
                # site-packages/ 多为手工摆放的第三方包或 venv 残留而非构建产物，
                # 而下游 ArtifactPathMatcher 会把命中路径当产物走 merge 自愈/重建
                # 通道，误列会把语义改动产物化；build/ 同样不列：目录名太通用
                # （易误报任意同名目录），不作 Python 项目产物候选
                for d in ["dist", "_build"]:
                    candidate = project_root / d
                    if candidate.is_dir() and any(candidate.iterdir()):
                        paths_found.add(f"{d}/")
                        sources.append(f"pyproject.toml 存在 + {d}/ 目录非空")
        except OSError:
            pass

    # ── 4. 根级 dist/ build/ out/ 目录（独立信息源，不依赖 package.json 存在）──
    # 无 package.json/pyproject.toml 的项目（Go/Rust 等）同样探测根级构建目录；
    # build/ 目录名太通用（易误报任意同名目录），Python 项目（pyproject.toml
    # 在册）不作产物候选，与 pyproject 分支的排除语义一致
    has_pyproject = pyproject.is_file()
    try:
        for d in ["dist", "build", "out"]:
            if d == "build" and has_pyproject:
                continue
            candidate = project_root / d
            if candidate.is_dir() and any(candidate.iterdir()):
                if f"{d}/" in paths_found:
                    continue  # dist/ 已由 pyproject 分支归因，不重复记源
                paths_found.add(f"{d}/")
                sources.append(f"{d}/ 目录存在且非空")
    except OSError:
        pass  # 目录不可读（权限/挂载异常）时跳过该信息源，不阻塞探测

    # ── 5. 根级产物文件（release-*.zip 等命名 → 写入具体文件名）──────────────
    try:
        for f in project_root.iterdir():
            if f.is_file():
                name = f.name
                if (
                    name.startswith("release-")
                    and name.endswith(".zip")
                ) or (
                    name.endswith(".tar.gz")
                    and (
                        any(
                            tag in name
                            for tag in ("release", "build", "dist")
                        )
                        # "v" 须带版本语义（如 v1.2.3 / project-v2.0.tar.gz）：
                        # 裸字母 v 子串会误命中 level-data、novel 等任意含 v 的文件名
                        or re.search(r"v\d", name)
                    )
                ):
                    paths_found.add(name)  # 具体文件名（如 release-1.0.zip），非通配
                    sources.append(f"根级通配产物: {name}")
    except OSError:
        pass

    # ── 汇总 ─────────────────────────────────────────────────────────────────
    # 目录前缀保留 / 尾缀，文件为具体文件名（不生成通配模式）
    final_paths = sorted(paths_found)
    if final_paths:
        result["has_build_artifacts"] = True
        result["build_artifact_paths"] = final_paths
    result["sources"] = sources
    return result


def _read_existing_config(project_root: Path) -> dict | None:
    """读取 .fenix/config.yaml 中 worktree 段（YAML 简单解析，不依赖 yaml 库）。"""
    cfg_path = project_root / ".fenix" / "config.yaml"
    if not cfg_path.is_file():
        return None
    try:
        content = cfg_path.read_text(encoding="utf-8")
    except OSError:
        return None
    # 简单 YAML 解析：找到 worktree: 段并提取 has_build_artifacts / build_artifact_paths
    in_worktree = False
    result = {}
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # 段标题检测
        if stripped == "worktree:" and not line.startswith(" "):
            in_worktree = True
            continue
        if in_worktree:
            if not line.startswith(" ") and not line.startswith("\t"):
                in_worktree = False
                continue
            s = stripped
            if s.startswith("has_build_artifacts:"):
                val = s.split(":", 1)[1].strip()
                # 三态契约（与 worktree_config_view 同口径）：空值/null 表示「未裁决」，
                # MUST NOT 落键——write_config_if_unresolved 以键在册判「已显式配置」，
                # 误落键会把未裁决项目静默排除在自动探测写入之外；仅显式布尔裁决落键
                if val.lower() in ("true", "1", "yes", "on"):  # on 是 YAML 1.1 的 true 别名，与 false 集合的 off 对称
                    result["has_build_artifacts"] = True
                elif val.lower() in ("false", "0", "no", "off"):
                    result["has_build_artifacts"] = False
            elif s.startswith("build_artifact_paths:"):
                val = s.split(":", 1)[1].strip()
                if val.startswith("["):
                    # 内联列表 [a, b, c]
                    import ast
                    try:
                        result["build_artifact_paths"] = ast.literal_eval(val)
                    except (ValueError, SyntaxError):
                        result["build_artifact_paths"] = None
                else:
                    # 块式列表不在本行，无法简单解析；仅凭 has_build_artifacts 在册即视为已裁决
                    result["build_artifact_paths"] = None
    return result if result else None


def write_config_if_unresolved(project_root: Path, detection: dict) -> dict:
    """将探测结果写入 .fenix/config.yaml（幂等，不覆盖已显式配置的项目）。

    仅 when worktree.has_build_artifacts 未显式布尔裁决（未裁决；空值/null 亦视为
    未裁决）才写入；已裁决项目跳过（MUST NOT 覆盖人工设置）。YAML 缺失时退化到
    定向文本更新（仅改写/追加 worktree 段两键，其余行原样保留），不抛异常——
    写入失败返回 {"wrote": False, "reason": <原因>}。

    注意：有 PyYAML 时走 yaml.dump 全量重写，config.yaml 原有注释与排版会全部
    丢失（PyYAML 不保留注释）；仅无 yaml 的退化文本路径逐行保留原文件。
    config.yaml 无法解析（YAMLError/OSError）或顶层非映射时中止写入，绝不以空
    配置起步全量重写，以免静默清空用户其余配置。

    Returns: {"wrote": bool, "reason": str}
    """
    cfg_path = project_root / ".fenix" / "config.yaml"
    if cfg_path.is_file():
        existing = _read_existing_config(project_root)
        if existing and "has_build_artifacts" in existing:
            return {"wrote": False, "reason": "has_build_artifacts 已显式配置，跳过"}

    try:
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        # docstring 承诺本函数不抛异常（写入失败返回 {"wrote": False, ...}）：
        # .fenix 被同名普通文件占用/父目录不可写时 mkdir 的 OSError 也须落契约，
        # 否则按 stdout JSON 消费的上游拿到的是 traceback 而非错误载荷
        return {"wrote": False, "reason": f"无法创建配置目录: {e}"}
    # 写入前经 validate_build_artifact_paths 同口径校验（task 7.1：与 Dashboard
    # write_config 同一判定权威——非法项拒绝而非静默丢弃，防探测误判误写）
    try:
        from core.worktree_manager.artifact_paths import validate_build_artifact_paths

        err = validate_build_artifact_paths(list(detection["build_artifact_paths"]))
        if err:
            return {"wrote": False, "reason": f"候选路径校验未通过: {err}"}
    except ImportError:
        pass  # 独立脚本环境（无 core 包）时跳过校验，仅作参考
    try:
        import yaml  # PyYAML（fenix-setup 步骤 1 已确保安装）

        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
        except FileNotFoundError:
            config = {}  # 文件尚不存在，空配置起步不损失任何内容
        except (OSError, yaml.YAMLError) as e:
            # 读取失败/语法错误：以空 dict 全量重写会清掉用户其余配置，中止写入
            # （与退化文本路径「其余行原样保留」语义对齐）
            return {
                "wrote": False,
                "reason": f"config.yaml 无法解析，中止写入以免清空既有配置: {e}",
            }
        if not isinstance(config, dict):
            # 顶层非映射（列表/标量）：yaml.dump 全量重写会改写整个文档结构，中止
            return {
                "wrote": False,
                "reason": (
                    f"config.yaml 顶层为 {type(config).__name__} 而非映射，"
                    "中止写入以免清空既有配置"
                ),
            }
        worktree = config.setdefault("worktree", {})
        if not isinstance(worktree, dict):
            worktree = {}
        # 仅显式布尔算已裁决（worktree_config_view 同口径）；null/非法值=未裁决，照常写入
        if isinstance(worktree.get("has_build_artifacts"), bool):
            return {"wrote": False, "reason": "has_build_artifacts 已显式配置，跳过"}
        worktree["has_build_artifacts"] = bool(detection["has_build_artifacts"])
        worktree["build_artifact_paths"] = list(detection["build_artifact_paths"])
        config["worktree"] = worktree
        # yaml.dump 全量重写：PyYAML 不保留注释，原文件注释/排版在此全部丢失
        # （保留注释需保守文本插入，风险更高，此处如实告知而非伪装成无损合并）
        try:
            with open(cfg_path, "w", encoding="utf-8") as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        except OSError as e:
            # 与退化文本路径错误契约对齐（docstring 承诺写入失败返回
            # {"wrote": False, "reason": ...}）：只读文件系统/磁盘满/权限不足时
            # 异常上抛会让按 stdout JSON 消费的上游拿到 traceback 而非错误载荷
            return {"wrote": False, "reason": f"写入失败: {e}"}
        return {"wrote": True, "reason": "探测结果已写入（YAML 全量重写，原注释丢失）"}
    except ImportError:
        pass  # 无 yaml → 退化定向文本更新

    # ── 退化路径：无 PyYAML → 定向行内更新（仅改写/追加 worktree 段两键）──
    # 旧实现的整段剔除会把 base_dir 等段内兄弟键一并删掉，与 PyYAML 路径的
    # 全量重写语义漂移；此处两键已存在则原位替换，不在册则段内追加，其余行原样保留
    old_lines = []
    if cfg_path.is_file():
        try:
            old_lines = cfg_path.read_text(encoding="utf-8").splitlines()
        except OSError as e:
            # 读取失败即中止写入：以空列表起步组装新内容会把用户既有配置整份
            # 清成仅含 worktree 两键，与 PyYAML 路径「无法解析即中止写入」对齐
            return {
                "wrote": False,
                "reason": f"config.yaml 无法读取，中止写入以免清空既有配置: {e}",
            }

    def _is_block_item(s: str) -> bool:
        return s == "-" or s.startswith("- ")

    has_line = f"  has_build_artifacts: {str(detection['has_build_artifacts']).lower()}"
    paths = detection["build_artifact_paths"]
    paths_line = f"  build_artifact_paths: {json.dumps(paths, ensure_ascii=False)}"

    # 定位旧 worktree: 段区间 [wt_start, wt_end)。段尾检测须放过顶格块式列表项：
    # yaml.dump 的列表子行落在键的缩进层级（可顶格 `- x`），仍属段内不能截断
    wt_start = None
    wt_end = len(old_lines)
    for i, line in enumerate(old_lines):
        stripped = line.strip()
        if stripped == "worktree:" and not line.startswith((" ", "\t")):
            wt_start = i
            break
    if wt_start is not None:
        for j in range(wt_start + 1, len(old_lines)):
            line = old_lines[j]
            stripped = line.strip()
            if stripped and not line.startswith((" ", "\t")) and not _is_block_item(stripped):
                wt_end = j
                break

    if wt_start is None:
        # 无 worktree 段：文件尾追加新段，其余行原样保留
        new_lines = list(old_lines)
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        new_lines.append("worktree:")
        new_lines.append(has_line)
        new_lines.append(paths_line)
    else:
        new_lines = old_lines[: wt_start + 1]
        i = wt_start + 1
        wrote_has = wrote_paths = False
        while i < wt_end:
            line = old_lines[i]
            stripped = line.strip()
            if stripped.startswith("has_build_artifacts:"):
                new_lines.append(has_line)  # 原位替换（旧 null 空值行同此更新）
                wrote_has = True
                i += 1
            elif stripped.startswith("build_artifact_paths:"):
                new_lines.append(paths_line)  # 原位替换
                wrote_paths = True
                i += 1
                # 吞掉旧键的块式列表值行（yaml.dump 默认块式），否则残留悬空
                # `- x` 会破坏 YAML；确属值块的空行/注释一并清掉，值块后缀的
                # 空行/注释（下一个兄弟键的前导）原样保留
                pending = []
                while i < wt_end:
                    s = old_lines[i].strip()
                    if _is_block_item(s):
                        pending.clear()
                        i += 1
                    elif not s or s.startswith("#"):
                        pending.append(old_lines[i])
                        i += 1
                    else:
                        break
                new_lines.extend(pending)
            else:
                new_lines.append(line)  # base_dir 等兄弟键及注释原样保留
                i += 1
        if not wrote_has:
            new_lines.append(has_line)
        if not wrote_paths:
            new_lines.append(paths_line)
        new_lines.extend(old_lines[wt_end:])

    text = "\n".join(new_lines)
    if text and not text.endswith("\n"):
        text += "\n"
    try:
        cfg_path.write_text(text, encoding="utf-8")
        return {"wrote": True, "reason": "探测结果已写入（文本定向更新退化路径）"}
    except OSError as e:
        return {"wrote": False, "reason": f"写入失败: {e}"}


def main():
    parser = argparse.ArgumentParser(
        description="纯本地探测项目构建产物路径"
    )
    parser.add_argument(
        "project_root",
        nargs="?",
        default=".",
        help="项目根目录（默认：当前目录）",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="探测结果写入 .fenix/config.yaml（幂等，不覆盖已配置）",
    )
    args = parser.parse_args()

    # expanduser：shell 引号包裹传入的 ~ 开头路径按字面落盘会误报「项目根目录不存在」，
    # 与 fenix_dashboard.py cmd_add_project 的用户输入路径解析口径对齐
    project_root = Path(args.project_root).expanduser().resolve()
    if not project_root.is_dir():
        print(json.dumps({"error": f"项目根目录不存在: {project_root}", "status": "error"}))
        sys.exit(1)

    detection = detect_build_artifacts(project_root)

    if args.write:
        write_result = write_config_if_unresolved(project_root, detection)
        detection["write"] = write_result

    print(json.dumps(detection, ensure_ascii=False, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
