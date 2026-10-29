#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""栈画像侦察（fenix-prototype · 任务 1.1）。

对目标工程做只读侦察，产出「栈画像 JSON」供原型生成 prompt 注入：

- 依赖清单识别组件库与版本（package.json 的 dependencies / devDependencies）；
- 主题 / 设计 token 提取（CSS 自定义属性、antd ConfigProvider theme tokens、
  tailwind 配置、DESIGN.md 摘录）；
- 画像判定：v1 实现 React+antd 画像；识别不出受支持栈时返回 ``unknown``
  并给出降级标记（纯 HTML/CSS 仿样、显式「视觉参照、无约束力」）。

零第三方依赖（python 标准库），对目标工程零写入、不要求工程可构建。
画像接口留扩展位：新栈在 ``PROFILE_PROBES`` 注册一个 probe 即可，
判定主流程与其余输出 schema 不变。

用法::

    python3 stack_profile.py --project <工程目录> [--output <path>] [--pretty]

退出码：0 = 侦察成功（含 unknown 降级画像，属正常产物）；2 = 用法/目录错误。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCHEMA_VERSION = "fenix-prototype/stack-profile@1"

# 扫描排除目录：永不进入（vendor/构建产物/运行时目录与本能力无关）
SKIP_DIRS = {
    "node_modules", "dist", "build", ".git", ".fenix", ".history",
    ".claude", "coverage", ".pytest_cache", "__pycache__", "vendor",
    "third_party", "thirdparty",
}

# 各类别扫描的文件上限（侦察是尽力而为，不为全仓遍历烧时间）
MAX_FILES_PER_CATEGORY = 400

# 主题相关文件扩展名
STYLE_EXTS = {".css", ".less", ".scss"}
CODE_EXTS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}


# ---------------------------------------------------------------------------
# 依赖清单识别
# ---------------------------------------------------------------------------

def find_manifest(project: Path) -> Path | None:
    """定位依赖清单。v1 支持 package.json；留扩展位（go.mod / requirements.txt 等）。"""
    candidate = project / "package.json"
    if candidate.is_file():
        return candidate
    return None


def read_dependencies(manifest: Path) -> dict[str, str]:
    """读 package.json 的 dependencies + devDependencies 合并表（name -> version range）。"""
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    deps: dict[str, str] = {}
    for key in ("dependencies", "devDependencies"):
        block = data.get(key)
        if isinstance(block, dict):
            for name, version in block.items():
                if isinstance(name, str) and isinstance(version, str):
                    deps.setdefault(name, version)
    return deps


# ---------------------------------------------------------------------------
# 栈判定（probe 注册表 = 扩展位）
# ---------------------------------------------------------------------------

class StackProbe:
    """单个栈的判定探针。新栈支持：子类化并注册进 ``PROFILE_PROBES``。"""

    name: str = ""

    def detect(self, deps: dict[str, str]) -> dict | None:
        """命中返回画像要素 dict，未命中返回 None。"""
        raise NotImplementedError


class ReactAntdProbe(StackProbe):
    """v1：React + antd 浏览器组件栈（本仓 dashboard 吃狗粮实证）。"""

    name = "react-antd"

    def detect(self, deps: dict[str, str]) -> dict | None:
        if "react" not in deps or "antd" not in deps:
            return None
        react_version = deps["react"]
        confidence = "high" if "react-dom" in deps else "low"
        framework = {"name": "react", "version": react_version}
        if "react-dom" in deps:
            framework["dom_version"] = deps["react-dom"]
        return {
            "profile": self.name,
            "framework": framework,
            "component_library": {"name": "antd", "version": deps["antd"]},
            "confidence": confidence,
        }


#: 探针注册表（顺序即优先级）。扩展新栈在此追加，不改判定主流程。
PROFILE_PROBES: list[StackProbe] = [ReactAntdProbe()]


# ---------------------------------------------------------------------------
# 主题 / 设计 token 提取
# ---------------------------------------------------------------------------

def _iter_source_files(project: Path, exts: set[str], limit: int = MAX_FILES_PER_CATEGORY):
    """受控遍历：跳过 SKIP_DIRS 与超出上限后的剩余文件（顺序稳定）。"""
    count = 0
    for path in sorted(project.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(project).parts):
            continue
        if path.suffix.lower() not in exts:
            continue
        count += 1
        if count > limit:
            break
        yield path


#: 只提取「视觉约束相关」的 CSS 自定义属性（前缀命中即收，防 token 表爆炸）
_INTERESTING_CUSTOM_PROP = re.compile(
    r"--([a-z0-9-]*(?:primary|accent|background|foreground|radius|font|muted|border|"
    r"card|popover|secondary|destructive|ring|input|chart|sidebar)[a-z0-9-]*)\s*:\s*([^;]+);",
    re.IGNORECASE,
)

# antd ConfigProvider theme tokens：``token: { colorPrimary: '#xxx', ... }``
_ANTD_TOKEN_BLOCK = re.compile(r"token\s*:\s*\{([^{}]*)\}", re.DOTALL)
_ANTD_TOKEN_KEY = re.compile(r"(color[A-Za-z]+|borderRadius[A-Za-z]*|fontSize[A-Za-z]*|fontFamily)\s*:\s*['\"]?([^,'\"}\n]+)")


def extract_css_custom_props(project: Path) -> tuple[dict[str, str], list[str]]:
    """提取 :root 级 CSS 自定义属性（less/scss/css 同口径），返回 (tokens, sources)。"""
    tokens: dict[str, str] = {}
    sources: list[str] = []
    for path in _iter_source_files(project, STYLE_EXTS):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        found = {f"--{name.strip().lower()}": value.strip()
                 for name, value in _INTERESTING_CUSTOM_PROP.findall(text)}
        if found:
            # 先扫到的文件优先（sorted 遍历保证确定性）；不覆盖已有键
            for key, value in found.items():
                tokens.setdefault(key, value)
            rel = path.relative_to(project).as_posix()
            if rel not in sources:
                sources.append(rel)
    return tokens, sources


def extract_antd_tokens(project: Path) -> tuple[dict[str, str], list[str]]:
    """提取代码里 antd ConfigProvider 的 theme.token 配置，返回 (tokens, sources)。"""
    tokens: dict[str, str] = {}
    sources: list[str] = []
    for path in _iter_source_files(project, CODE_EXTS):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "token" not in text:
            continue
        found: dict[str, str] = {}
        for block in _ANTD_TOKEN_BLOCK.findall(text):
            for key, value in _ANTD_TOKEN_KEY.findall(block):
                found.setdefault(key, value.strip())
        if found:
            for key, value in found.items():
                tokens.setdefault(key, value)
            rel = path.relative_to(project).as_posix()
            if rel not in sources:
                sources.append(rel)
    return tokens, sources


_DESIGN_DOC_CANDIDATES = ("DESIGN.md", "docs/DESIGN.md", "doc/DESIGN.md")
_DESIGN_KEYWORD = re.compile(
    r"颜色|色彩|配色|字体|字号|间距|圆角|布局|color|colour|font|spacing|radius|layout",
    re.IGNORECASE,
)


def extract_design_doc(project: Path) -> dict | None:
    """提取 DESIGN.md 摘录（标题 + 含视觉关键词的行，封顶 40 行）。"""
    for rel in _DESIGN_DOC_CANDIDATES:
        path = project / rel
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        extract: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#") or _DESIGN_KEYWORD.search(stripped):
                extract.append(stripped)
            if len(extract) >= 40:
                break
        return {"path": rel, "extract": extract}
    return None


# ---------------------------------------------------------------------------
# 画像组装
# ---------------------------------------------------------------------------

def build_profile(project: Path) -> dict:
    """组装栈画像 JSON（识别失败返回 unknown + 降级标记，不抛错）。"""
    warnings: list[str] = []
    manifest = find_manifest(project)

    if manifest is None:
        return _unknown_profile(
            project,
            [f"未找到依赖清单 package.json：{project}"],
        )

    deps = read_dependencies(manifest)
    if not deps:
        return _unknown_profile(project, ["依赖清单存在但未能解析出任何依赖项"])

    detected: dict | None = None
    for probe in PROFILE_PROBES:
        detected = probe.detect(deps)
        if detected is not None:
            break

    if detected is None:
        return _unknown_profile(
            project,
            ["依赖清单未识别出受支持的浏览器组件库（v1 支持 React+antd）"],
        )

    css_tokens, css_sources = extract_css_custom_props(project)
    antd_tokens, antd_sources = extract_antd_tokens(project)
    design_doc = extract_design_doc(project)

    profile = {
        "schema": SCHEMA_VERSION,
        "profile": detected["profile"],
        "detected": True,
        "confidence": detected["confidence"],
        "framework": detected["framework"],
        "component_library": detected["component_library"],
        "theme": {
            "css_custom_props": css_tokens,
            "antd_tokens": antd_tokens,
            "sources": css_sources + antd_sources,
        },
        "design_doc": design_doc,
        "samples": _sample_pages(project),
        "generation": {
            "mode": "real-components",
            "binding": "binding",
            "annotation": None,
        },
        "degradation": None,
        "warnings": warnings,
    }
    if detected["confidence"] == "low":
        warnings.append("检测到 react + antd 但未发现 react-dom，渲染入口需生成时确认")
    return profile


def _unknown_profile(project: Path, reasons: list[str]) -> dict:
    """unknown 画像：显式降级为纯 HTML/CSS 仿样并标注无约束力。"""
    return {
        "schema": SCHEMA_VERSION,
        "profile": "unknown",
        "detected": False,
        "confidence": "none",
        "framework": None,
        "component_library": None,
        "theme": {"css_custom_props": {}, "antd_tokens": {}, "sources": []},
        "design_doc": extract_design_doc(project),
        "samples": _sample_pages(project),
        "generation": {
            "mode": "plain-html",
            "binding": "none",
            "annotation": "视觉参照、无约束力",
        },
        "degradation": {
            "level": "plain-html",
            "reasons": reasons,
        },
        "warnings": list(reasons),
    }


#: 现有页面样例（供生成 prompt 参考既有布局惯例），封顶 8 个
_SAMPLE_PATTERNS = ("src/pages/", "src/views/", "src/routes/", "app/", "pages/")


def _sample_pages(project: Path) -> list[str]:
    samples: list[str] = []
    for path in _iter_source_files(project, CODE_EXTS, limit=MAX_FILES_PER_CATEGORY):
        rel = path.relative_to(project).as_posix()
        if any(pat in rel for pat in _SAMPLE_PATTERNS):
            samples.append(rel)
            if len(samples) >= 8:
                break
    return samples


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="fenix-prototype 栈画像侦察")
    parser.add_argument("--project", default=".", help="目标工程根目录（默认当前目录）")
    parser.add_argument("--output", default=None, help="画像 JSON 落盘路径（默认打印 stdout）")
    parser.add_argument("--pretty", action="store_true", help="缩进美化输出")
    args = parser.parse_args(argv)

    project = Path(args.project)
    if not project.is_dir():
        print(json.dumps({"ok": False, "error": f"工程目录不存在：{args.project}"},
                         ensure_ascii=False), file=sys.stderr)
        return 2

    profile = build_profile(project)
    text = json.dumps(profile, ensure_ascii=False, indent=2 if args.pretty else None)
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
