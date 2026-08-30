"""交付物路径提取（add-implementer-deliverable-gate，D2）。

纯函数模块：从 SPEC 的 tasks.md / proposal.md / specs/*.md 文本中提取
实现 agent 显式声明的交付文件路径清单，供收工守卫做存在性校验。

提取规则（保守，避免误杀）：
- 仅识别显式路径形态：反引号包裹（`` `path` ``）、围栏代码块（``` 内）、
  「路径：」/「路径:」前缀行；
- 路径必须匹配核心交付前缀之一：`` core/ ``、`` tests/ ``、`` .fenix/ ``、
  `` scripts/ ``；
- 排除以 `` / `` 开头的绝对路径、含通配符（`` * `` `` ? ``）的条目、以 `` / ``
  结尾的目录条目；
- 输出去重、保序（首次出现顺序）的路径列表；无任何可提取路径返回空列表
  （守卫据此跳过，向后兼容）。

无外部依赖、无 LLM / 测试 / 网络调用，单测可直接 fixture 真实文档。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List

# 核心交付路径前缀（相对项目根）：实现产物的稳定落点。
_DELIVERABLE_PREFIXES = ("core/", "tests/", ".fenix/", "scripts/")

# 围栏代码块起始/结束（``` 或 ~~~，允许跟随语言标识）。
_FENCE_RE = re.compile(r"^\s*(```|~~~)")

# 「路径：」/「路径:」前缀行（中文/英文冒号，前后允许空白与装饰）。
_PATH_LABEL_RE = re.compile(
    r"^\s*[·•\-*•]?\s*路径\s*[:：]\s*(?P<rest>.+?)\s*$"
)

# 反引号包裹的单条路径（去除行内其它字符，仅取反引号内 token）。
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")

# 绝对路径 / 通配符 / 目录（以 / 结尾）判定。
_ABSOLUTE_RE = re.compile(r"^/")
_WILDCARD_RE = re.compile(r"[*?]")
_DIRECTORY_RE = re.compile(r"/$")


def _is_deliverable_path(token: str) -> bool:
    """判断单个 token 是否为可校验的核心交付路径。"""
    tok = token.strip()
    if not tok:
        return False
    # 排除绝对路径
    if _ABSOLUTE_RE.match(tok):
        return False
    # 排除含通配符的条目
    if _WILDCARD_RE.search(tok):
        return False
    # 排除目录条目（以 / 结尾）
    if _DIRECTORY_RE.search(tok):
        return False
    # 必须以核心交付前缀开头
    return tok.startswith(_DELIVERABLE_PREFIXES)


def _normalize_token(token: str) -> str:
    """规整候选 token：去尾随标点、去引号、去前导空白。"""
    tok = token.strip()
    # 去首尾成对引号
    if len(tok) >= 2 and tok[0] in "\"'`" and tok[-1] == tok[0]:
        tok = tok[1:-1]
    # 去除尾随常见标点（避免从句子里误带出句号/逗号/括号）
    tok = tok.rstrip(".,;:。，；：)")
    return tok


def _candidates_from_line(line: str) -> List[str]:
    """从单行提取所有候选路径 token（反引号 + 路径前缀行）。"""
    cands: List[str] = []

    # 1) 反引号包裹 token
    for m in _INLINE_CODE_RE.finditer(line):
        cands.append(m.group(1))

    # 2) 「路径：」前缀行 —— 整行剩余部分可能含空格分隔的多个路径
    label = _PATH_LABEL_RE.match(line)
    if label:
        rest = label.group("rest")
        # 优先取反引号 token；否则按空白切分（支持「路径: a/b c/d」写法）
        inner = _INLINE_CODE_RE.findall(rest)
        if inner:
            cands.extend(inner)
        else:
            cands.extend(rest.split())

    return cands


def _iter_spec_documents(spec_dir: Path) -> Iterable[Path]:
    """yielding SPEC 文档（tasks.md / proposal.md / specs/*.md）。"""
    for name in ("tasks.md", "proposal.md"):
        p = spec_dir / name
        if p.is_file():
            yield p
    specs_dir = spec_dir / "specs"
    if specs_dir.is_dir():
        for f in sorted(specs_dir.rglob("*.md")):
            if f.is_file():
                yield f


def extract_paths(spec_dir) -> List[str]:
    """从 SPEC 目录提取声明交付的文件路径清单（去重、保序）。

    ``spec_dir`` 可为 ``str`` / ``Path``（指向 openspec/changes/<spec>/）。
    仅读取 tasks.md / proposal.md / specs/*.md；无任何可提取路径时返回空列表。

    Returns:
        相对项目根的去重路径列表；为空列表表示守卫应跳过。
    """
    root = Path(spec_dir)
    seen: set[str] = set()
    ordered: List[str] = []

    for doc in _iter_spec_documents(root):
        try:
            text = doc.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        in_fence = False
        for raw_line in text.splitlines():
            # 围栏代码块：整块内所有行均视为显式路径声明
            if _FENCE_RE.match(raw_line):
                in_fence = not in_fence
                continue
            if in_fence:
                # 代码块内逐 token（按空白/常见分隔符切分）
                for tok in re.split(r"\s+", raw_line.strip()):
                    cand = _normalize_token(tok)
                    if _is_deliverable_path(cand) and cand not in seen:
                        seen.add(cand)
                        ordered.append(cand)
                continue

            # 行内（反引号 / 路径前缀行）
            for tok in _candidates_from_line(raw_line):
                cand = _normalize_token(tok)
                if _is_deliverable_path(cand) and cand not in seen:
                    seen.add(cand)
                    ordered.append(cand)

    return ordered
