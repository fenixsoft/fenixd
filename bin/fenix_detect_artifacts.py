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
    1. package.json 的 scripts.build / scripts.dist / scripts.release
       + 根级/子级 dist/、build/、out/ 目录存在性
    2. pyproject.toml 的 [build-system]（poetry setuptools 等 → 检查 dist/）
    3. 项目目录结构：根级 dist/、build/、target/、out/、release-*.zip 通配
    4. Fenix 框架项目（core/dashboard/static/dist/ 存在时自动包含）

输出（JSON）：
    {
      "has_build_artifacts": true,
      "build_artifact_paths": ["dist/", "release-*.zip"],
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
import sys
from pathlib import Path


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
        # 检查是否有构建产物特征（index.html / hash JS 文件）
        if any(fenix_dist.iterdir()):
            paths_found.add("core/dashboard/static/")
            sources.append("core/dashboard/static/dist/ 存在且非空")

    # ── 2. package.json scripts + dist/build 目录 ────────────────────────────
    pkg_json = project_root / "package.json"
    if pkg_json.is_file():
        try:
            pkg = json.loads(pkg_json.read_text(encoding="utf-8"))
            scripts = pkg.get("scripts", {})
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
            # 根级 dist/ build/ out/ 检测
            for d in ["dist", "build", "out"]:
                candidate = project_root / d
                if candidate.is_dir() and any(candidate.iterdir()):
                    paths_found.add(f"{d}/")
                    sources.append(f"{d}/ 目录存在且非空")
        except (json.JSONDecodeError, OSError):
            pass  # 损坏的 package.json 不阻塞

    # ── 3. pyproject.toml（Python 项目）──────────────────────────────────────
    pyproject = project_root / "pyproject.toml"
    if pyproject.is_file():
        try:
            content = pyproject.read_text(encoding="utf-8")
            if "[build-system]" in content or "[tool.poetry]" in content:
                # Python 项目的常见产物目录
                for d in ["dist", "build", "_build", "site-packages"]:
                    candidate = project_root / d
                    if candidate.is_dir() and any(candidate.iterdir()):
                        if d == "dist":
                            paths_found.add("dist/")
                            sources.append(f"pyproject.toml 存在 + {d}/ 目录非空")
                        elif d not in ("build",):  # build 太通用，仅在有 pyproject 时添加
                            paths_found.add(f"{d}/")
                            sources.append(f"pyproject.toml 存在 + {d}/ 目录非空")
        except OSError:
            pass

    # ── 4. 根级通配产物（release-*.zip 等）────────────────────────────────────
    try:
        for f in project_root.iterdir():
            if f.is_file():
                name = f.name
                if (
                    name.startswith("release-")
                    and name.endswith(".zip")
                ) or (
                    name.endswith(".tar.gz")
                    and any(
                        tag in name
                        for tag in ("release", "build", "dist", "v")
                    )
                ):
                    if "*" not in name:  # glob 通配不含 / 只匹配根级
                        paths_found.add(name)  # 如 release-*.zip → 通配
                        sources.append(f"根级通配产物: {name}")
    except OSError:
        pass

    # ── 汇总 ─────────────────────────────────────────────────────────────────
    # 对通配文件名添加 * 模式（目录前缀保留 /）
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
                result["has_build_artifacts"] = val.lower() in ("true", "1", "yes")
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
                    result["build_artifact_paths"] = None  # 未在本行定义
    return result if result else None


def write_config_if_unresolved(project_root: Path, detection: dict) -> dict:
    """将探测结果写入 .fenix/config.yaml（幂等，不覆盖已显式配置的项目）。

    仅 when worktree.has_build_artifacts 未显式存在（未裁决）才写入；已裁决项目
    跳过（MUST NOT 覆盖人工设置）。YAML 缺失时退化到最小文本追加（保留其余行），
    不抛异常——写入失败返回 {"wrote": False, "reason": <原因>}。

    Returns: {"wrote": bool, "reason": str}
    """
    cfg_path = project_root / ".fenix" / "config.yaml"
    if cfg_path.is_file():
        existing = _read_existing_config(project_root)
        if existing and "has_build_artifacts" in existing:
            return {"wrote": False, "reason": "has_build_artifacts 已显式配置，跳过"}

    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import yaml  # PyYAML（fenix-setup 步骤 1 已确保安装）

        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError, FileNotFoundError):
            config = {}
        if not isinstance(config, dict):
            config = {}
        worktree = config.setdefault("worktree", {})
        if not isinstance(worktree, dict):
            worktree = {}
        if "has_build_artifacts" in worktree:
            return {"wrote": False, "reason": "has_build_artifacts 已显式配置，跳过"}
        worktree["has_build_artifacts"] = bool(detection["has_build_artifacts"])
        worktree["build_artifact_paths"] = list(detection["build_artifact_paths"])
        config["worktree"] = worktree
        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        return {"wrote": True, "reason": "探测结果已写入（YAML 合并）"}
    except ImportError:
        pass  # 无 yaml → 退化最小文本追加

    # ── 退化路径：无 PyYAML → 最小文本追加（保留原行）──────────────────────
    old_lines = []
    if cfg_path.is_file():
        try:
            old_lines = cfg_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            pass
    # 剔除旧 worktree 段（避免重复键）
    new_lines = []
    in_worktree = False
    for line in old_lines:
        stripped = line.strip()
        if stripped == "worktree:" and not line.startswith(" "):
            in_worktree = True
            continue
        if in_worktree:
            if not line.startswith(" ") and not line.startswith("\t") and stripped:
                in_worktree = False
            else:
                continue
        new_lines.append(line)
    new_lines.append("")
    new_lines.append("worktree:")
    new_lines.append(f"  has_build_artifacts: {str(detection['has_build_artifacts']).lower()}")
    paths = detection["build_artifact_paths"]
    new_lines.append(f"  build_artifact_paths: {json.dumps(paths, ensure_ascii=False)}")
    new_lines.append("")
    try:
        cfg_path.write_text("\n".join(new_lines), encoding="utf-8")
        return {"wrote": True, "reason": "探测结果已写入（文本追加退化路径）"}
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

    project_root = Path(args.project_root).resolve()
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
