#!/usr/bin/env python3
"""fenix_detect_artifacts.py — 构建产物路径纯本地探测脚本。

用法:
    python3 bin/fenix_detect_artifacts.py [项目根目录]
    python3 bin/fenix_detect_artifacts.py --write [项目根目录]

    项目根目录缺省为当前目录。

模式:
    默认（无 --write）：探测并输出候选产物路径 JSON，不修改任何文件。
    --write：探测结果写入项目主树的 .fenix/config.yaml（幂等，不覆盖已显式配置的项目）。

探测信息源（按代码实际执行顺序，各源独立探测、候选取并集，无短路）：
    1. Fenix 框架项目：core/dashboard/static/dist/ 存在且非空时自动包含
    2. package.json 的 scripts.build / scripts.dist / scripts.release / scripts.bundle：
       仅记入 sources 供展示，不产生候选路径、不参与 has_build_artifacts 判定
    3. pyproject.toml（含 [build-system] 或 [tool.poetry]）→ 检查根级 dist/、_build/
    4. 项目目录结构：根级 dist/、build/、out/ 目录（独立信息源，仅项目根级，
       不递归子级；Python 项目不列 build/；dist/ 已由 pyproject 分支归因时不重复记源）
    5. 根级产物文件：release-*.zip、*.tar.gz 等命名的产物文件（写入具体文件名）

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
import tempfile
from pathlib import Path

# 框架根（定位 core/），仿 bin/fenix_cli.py：标准调用 `python3 bin/fenix_detect_artifacts.py`
# 时 sys.path[0] 是 bin/，cwd 不入 path，不加此项则 write_config_if_unresolved 里
# validate_build_artifact_paths 的 import 恒 ImportError 被静默跳过，写入前校验沦为死代码
FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FRAMEWORK_ROOT))

# package.json 构建脚本键白名单（code-review item 0c0caf5199e6）：判存在与列
# 键名共用同一元组（单一事实源），避免两处字面量须同步演进、漏改一处漂移
_BUILD_SCRIPT_KEYS = ("build", "dist", "release", "bundle")


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
            build_script_keys = [k for k in scripts if k in _BUILD_SCRIPT_KEYS]
            if build_script_keys:
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
            # 段头判定（code-review item 85ae09234ddc）：逐行 strip 后以 startswith
            # 匹配段头，替代全文子串包含——注释/字符串值里提到这些字样的行不再
            # 被误判为 Python 项目在册（误判仅影响 dist/_build 归因文案，仍须收紧）。
            # poetry 子段前缀匹配（code-review item 0e2a77bd5fb2）：poetry 2.x
            # 支持 PEP 621 后主段可省略，仅声明 [tool.poetry.dependencies] 等
            # 子段的 pyproject.toml 同属 Python 项目，"[tool.poetry" 前缀一并覆盖。
            if any(
                row.strip().startswith(("[build-system]", "[tool.poetry"))
                for row in content.splitlines()
            ):
                # Python 项目的常见产物目录。site-packages/ 不列为候选：根级出现
                # site-packages/ 多为手工摆放的第三方包或 venv 残留而非构建产物，
                # 而下游 ArtifactPathMatcher 会把命中路径当产物走 merge 自愈/重建
                # 通道，误列会把语义改动产物化；build/ 同样不列：目录名太通用
                # （易误报任意同名目录），不作 Python 项目产物候选
                for d in ["dist", "_build"]:
                    try:
                        candidate = project_root / d
                        if candidate.is_dir() and any(candidate.iterdir()):
                            paths_found.add(f"{d}/")
                            sources.append(f"pyproject.toml 存在 + {d}/ 目录非空")
                    except OSError:
                        # 该目录不可读时只跳过本目录，不连带其余候选
                        # （code-review item 74ac90941c60）
                        pass
        except OSError:
            pass

    # ── 4. 根级 dist/ build/ out/ 目录（独立信息源，不依赖 package.json 存在）──
    # 无 package.json/pyproject.toml 的项目（Go/Rust 等）同样探测根级构建目录；
    # build/ 目录名太通用（易误报任意同名目录），Python 项目（pyproject.toml
    # 在册）不作产物候选，与 pyproject 分支的排除语义一致
    has_pyproject = pyproject.is_file()
    # 逐目录收窄 try（code-review item 74ac90941c60）：循环级 except 会让单个
    # 目录不可读（权限/挂载异常）连带跳过其余候选目录，与「单源粒度跳过，
    # 不阻塞探测」的语义不符
    for d in ["dist", "build", "out"]:
        if d == "build" and has_pyproject:
            continue
        try:
            candidate = project_root / d
            if candidate.is_dir() and any(candidate.iterdir()):
                if f"{d}/" in paths_found:
                    continue  # dist/ 已由 pyproject 分支归因，不重复记源
                paths_found.add(f"{d}/")
                sources.append(f"{d}/ 目录存在且非空")
        except OSError:
            pass  # 该目录不可读（权限/挂载异常）时只跳过本目录，不阻塞探测

    # ── 5. 根级产物文件（release-*.zip 等命名 → 写入具体文件名）──────────────
    try:
        # 一次性物化枚举（code-review item 74ac90941c60）：iterdir 是惰性生成器，
        # 中途失败会丢弃剩余文件；物化后枚举失败按该信息源整段跳过（单源
        # 粒度），逐文件判定不再处于 try 内
        root_entries = list(project_root.iterdir())
    except OSError:
        root_entries = []  # 根目录不可读（权限/挂载异常）时跳过该信息源，不阻塞探测
    for f in root_entries:
        if f.is_file():
            name = f.name
            # zip 与 tar.gz 同边界语义（code-review item b3927c8887e3）：原先
            # zip 仅认 release- 前缀、tar.gz 允许词根任意位置带边界，形如
            # foo-release-1.0.zip 不命中而同名 .tar.gz 命中，口径不对称
            if name.endswith((".zip", ".tar.gz")):
                if (
                    name.startswith("release-")
                    or (
                        # dist/build/release 同须边界语义：tag 前是行首或 -/_，
                        # tag 后紧跟 -/_/数字/v数字；纯子串会误命中 distribution、
                        # redistribute、buildkit-docs 等普通词
                        re.search(r"(?:^|[-_])(?:release|build|dist)(?:[-_]|\d|v\d)", name)
                        # "v" 须带版本语义且与上方分支同边界：v 前是行首或 -/_
                        # （如 v1.2.3 / project-v2.0.tar.gz）；无边界 v\d 子串会误命中
                        # srv12-logs、conv2-data、env5-backup 等普通文件名
                        or re.search(r"(?:^|[-_])v\d", name)
                    )
                ):
                    paths_found.add(name)  # 具体文件名（如 release-1.0.zip），非通配
                    sources.append(f"根级通配产物: {name}")

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
        # errors="replace" 同 detect 路径 package.json 分支：非 UTF-8 编码（如 GBK）
        # 的 config.yaml 解码不抛 UnicodeDecodeError（ValueError 族不在下方 except 内）
        content = cfg_path.read_text(encoding="utf-8", errors="replace")
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
        if stripped == "worktree:" and not line.startswith((" ", "\t")):
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
    config.yaml 无法解析（YAMLError/OSError）、顶层非映射或 worktree 段非映射
    （标量/列表）时中止写入，绝不以空配置起步全量重写，以免静默清空用户其余配置。

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
    def _atomic_replace_text(path: Path, text: str) -> None:
        # 临时文件 + os.replace 原子替换（对齐 core/dashboard/registry.py 保存路径
        # 先例）：原地写 config.yaml 在进程中途崩溃/磁盘满/与并发写者交错时会留下
        # 半截文件，daemon/ConfigLoader 随后整份解析失败；mkstemp 在同目录取进程
        # 唯一临时名，fsync 落盘后 os.replace 原子替换，OSError 上抛由调用点落
        # {"wrote": False, "reason": ...} 错误契约
        fd, tmp_str = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
        )
        try:
            try:
                f = open(fd, "w", encoding="utf-8")
            except OSError:
                # open 失败不会接管 fd：不显式关闭则描述符泄漏——finally 只负责
                # unlink 临时文件。close 自身再失败（fd 已坏）不吞掉原始异常。
                try:
                    os.close(fd)
                except OSError:
                    pass
                raise
            with f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_str, str(path))
        finally:
            tmp_path = Path(tmp_str)
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    try:
        import yaml  # PyYAML（fenix-setup 步骤 1 已确保安装）

        try:
            # errors="replace"：非 UTF-8 编码的 config.yaml 在读取层解码不抛
            # UnicodeDecodeError（ValueError 族不在下方 except 内）；但被替换成
            # U+FFFD 的文本往往仍能被 safe_load 成功解析，照常 yaml.dump 全量
            # 重写会把篡改后的字符串持久化，故解析前先检测 U+FFFD，存在即与
            # 「无法解析即中止写入」同口径中止，防静默破坏用户其余配置值
            with open(cfg_path, "r", encoding="utf-8", errors="replace") as f:
                raw_text = f.read()
            if "\ufffd" in raw_text:
                return {
                    "wrote": False,
                    "reason": (
                        "config.yaml 含非 UTF-8 字节（读取时已被替换为 U+FFFD），"
                        "中止写入以免静默篡改既有配置"
                    ),
                }
            config = yaml.safe_load(raw_text) or {}
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
        worktree = config.get("worktree")
        if worktree is not None and not isinstance(worktree, dict):
            # worktree 段为标量/列表（如 worktree: disabled）：以空 dict 顶替会在
            # 下方 yaml.dump 全量重写中静默吞掉原值，与顶层非映射同口径中止写入，
            # 提示人工处置而非覆盖
            return {
                "wrote": False,
                "reason": (
                    f"worktree 段为 {type(worktree).__name__} 而非映射，"
                    "中止写入以免清空既有配置"
                ),
            }
        if not isinstance(worktree, dict):
            # 键不在册或显式 null：null 亦视为未裁决（worktree_config_view 同
            # 口径），以空映射起步落两键
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
            _atomic_replace_text(
                cfg_path,
                yaml.dump(config, allow_unicode=True, default_flow_style=False, sort_keys=False),
            )
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
            # errors="replace" 同 _read_existing_config：非 UTF-8 编码不抛
            # UnicodeDecodeError（ValueError 族不在下方 except 内）
            old_lines = cfg_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as e:
            # 读取失败即中止写入：以空列表起步组装新内容会把用户既有配置整份
            # 清成仅含 worktree 两键，与 PyYAML 路径「无法解析即中止写入」对齐
            return {
                "wrote": False,
                "reason": f"config.yaml 无法读取，中止写入以免清空既有配置: {e}",
            }

    # 宽松复查（code-review item 7e3785b68cba）：段头识别（_read_existing_config 与
    # 下方 wt_start 定位）都只认裸 worktree: 行，段头带行尾注释（worktree:  # c）或
    # 内联映射（worktree: {has_build_artifacts: false}）时两处均失配 → 早退不触发，
    # 会走「无 worktree 段」分支在文件尾追加第二个 worktree: 段，YAML 重复键后者胜出，
    # 用户显式布尔裁决被探测结果静默覆盖。有 PyYAML 时 safe_load 后的在册复查兜住
    # 这两种形态；无 PyYAML 走到此处没有任何权威复查，故写盘前对旧文本做一次宽松
    # 扫描：任一非注释行含 has_build_artifacts: 键且值为显式布尔（别名集与
    # _read_existing_config 同口径）即中止写入——宁可漏写，不覆盖人工设置。
    for row in old_lines:
        s = row.strip()
        if not s or s.startswith("#"):
            continue
        # 中止条件二（code-review item 96139bacfa21）：顶格 worktree: 后跟非空
        # 内容（内联映射 worktree: {base_dir: /x}、标量 worktree: disabled、
        # 段头行尾注释 worktree:  # c）时段头定位同样失配，会落入「无 worktree
        # 段」分支在文件尾追加第二个 worktree: 段，YAML 重复顶层键后者胜出，
        # 用户原段 base_dir 等兄弟键被静默丢弃——宁可漏写，中止写入交人工处置
        if (
            not row.startswith((" ", "\t"))
            and s.startswith("worktree:")
            and s != "worktree:"
        ):
            return {
                "wrote": False,
                "reason": "worktree 段形态无法安全解析（内联映射/标量/段头行尾注释），请人工处置",
            }
        _, sep, val = s.partition("has_build_artifacts:")
        if not sep:
            continue
        # 截到首个分隔符：兼容内联映射（worktree: {has_build_artifacts: false, ...}）
        # 与行尾注释（has_build_artifacts: false  # c）；带引号的值非 YAML 布尔，
        # 与 PyYAML 路径的 isinstance(bool) 同口径不视为已裁决
        val = re.split(r"[,}\[#]", val, maxsplit=1)[0].strip()
        if val.lower() in ("true", "1", "yes", "on", "false", "0", "no", "off"):
            return {"wrote": False, "reason": "has_build_artifacts 已显式配置，跳过"}

    def _is_block_item(s: str) -> bool:
        return s == "-" or s.startswith("- ")

    # 既有缩进探测（code-review item 458df4aabd1d）：has_line/paths_line 若按
    # 固定 2 空格缩进落进 4 空格（或其他深度）缩进的既有 worktree 段，原位替换
    # 与段内追加都会产出段内缩进混排的 YAML，daemon/ConfigLoader 的 safe_load
    # 随即抛缩进错误、config.yaml 整体不可读；从旧段首个段内键行探测既有缩进
    # 宽度并以同宽生成两行。无既有段或段内无可参照键行时用 2 空格（与 yaml.dump
    # 默认缩进一致，新段整体自洽，与他段缩进不同在 YAML 中合法）。
    def _detect_indent() -> str:
        for k, row in enumerate(old_lines):
            stripped = row.strip()
            if stripped == "worktree:" and not row.startswith((" ", "\t")):
                for sub in old_lines[k + 1 :]:
                    s2 = sub.strip()
                    if not s2 or s2.startswith("#") or _is_block_item(s2):
                        continue  # 空行/注释/块式列表值行不作缩进参照
                    if not sub.startswith((" ", "\t")):
                        break  # 顶格非块项 = 段已结束，段内无键行可参照
                    if sub.startswith("\t"):
                        break  # tab 缩进非合法 YAML，无从同宽，回退默认
                    return sub[: len(sub) - len(sub.lstrip(" "))]
                break
        return "  "

    indent = _detect_indent()
    has_line = f"{indent}has_build_artifacts: {str(detection['has_build_artifacts']).lower()}"
    paths = detection["build_artifact_paths"]
    paths_line = f"{indent}build_artifact_paths: {json.dumps(paths, ensure_ascii=False)}"

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
        _atomic_replace_text(cfg_path, text)
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
    try:
        # 路径解析收口进 try（与 fenix_archive.py/fenix_spec.py 同场景防护对齐）：
        # expanduser 解析不出家目录抛 RuntimeError、含空字节路径在构造阶段抛
        # ValueError，裸抛会绕过下方「目录不存在」分支的 JSON 错误载荷与
        # sys.exit(1)，进程以 traceback 收场、退出码不符 docstring 契约
        project_root = Path(args.project_root).expanduser().resolve()
    except (ValueError, OSError, RuntimeError) as e:
        print(json.dumps({"error": f"项目根目录无法解析: {e}", "status": "error"}))
        sys.exit(1)
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
