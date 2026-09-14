"""交付物路径提取（add-implementer-deliverable-gate，D2）。

纯函数模块：从 SPEC 的 tasks.md / proposal.md / specs/*.md 文本中提取
实现 agent 显式声明的交付文件路径清单，供收工守卫做存在性校验。

提取规则（保守，避免误杀）：
- 仅识别显式路径形态：反引号包裹（`` `path` ``）、围栏代码块（``` 内）、
  「路径：」/「路径:」前缀行；
- 路径必须匹配核心交付前缀之一：`` core/ ``、`` tests/ ``、`` .fenix/ ``、
  `` scripts/ ``；
- 排除以 `` / `` 开头的绝对路径、含通配符（`` * `` `` ? ``）的条目、以 `` / ``
  结尾的目录条目、含模板占位符（`` < `` `` > ``，如 ``<run_id>``）的条目；
- 输出去重、保序（首次出现顺序）的路径列表；无任何可提取路径返回空列表
  （守卫据此跳过，向后兼容）。

语境分类（add-deliverable-extractor-semantics，D1）：
``extract_paths_typed`` 把候选路径分为两类：

- ``deliverables``：新建交付物，参与守卫缺件判定。tasks.md 勾选行
  （``- [ ]``/``- [x]``）与含「新增/创建/添加」等动词的行；
- ``references``：既有文件引用，不参与缺件判定（守卫仅审计留痕）。
  tasks.md 头部说明段（第一个 ``## `` 标题之前，如「实现依据」段）、
  含「实现依据/挂钩点/插入点/真实夹具/上游依赖」等关键词的行、
  proposal.md 的叙述性段落、能力 spec 文档（specs/*.md，其 Scenario
  中的路径是示例而非交付声明——本变更自身即曾因场景示例
  ``.fenix/x``/``core/foo.py`` 被误判缺件）。

声明段（``extract_declared``，tasks.md ``## Deliverables`` 段）按 kind 归类为
同一两桶结构：``new``/``modify``/``delete`` 归 ``deliverables``（硬校验——
``delete`` 为反判：合并后必须不存在）；``reference`` 归 ``references``
（软校验）。两桶语义在声明段与正则提取两条路径上保持一致。

无法判定时保守归 ``deliverables``（宁误拦不漏放——误拦有 3 次封顶 +
引用软校验兜底，漏放则假成功）；proposal.md 例外：仅「交付/新增」
语境归 deliverables，叙述性段落归 references（proposal 是叙事文档，
新增动词才是交付声明的信号）。

``normalize_check_path`` 曾做 ``.fenix/`` 前缀归一化（正式化热修 4461231，
前提是 ``.fenix`` 为自引用符号链接）。该设计已废弃（状态文件迁入 .fenix/，
提交 932a078）：``.fenix`` 现为实体目录、``.fenix/x`` 可按树查找，声明路径
一律按字面校验，本函数保留签名退化为恒等映射（迁移后历史声明的
``.fenix/x`` 恰指字面文件；若保留改写，根路径同名文件会把缺件误判为存在）。

无外部依赖、无 LLM / 测试 / 网络调用，单测可直接 fixture 真实文档。
"""

from __future__ import annotations

import os
import re
import subprocess
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

# ── 语境分类规则表（add-deliverable-extractor-semantics，D1） ───────────────

# 引用语境关键词：出现即视为「既有文件引用」语境（软校验，不参与缺件判定）。
_REFERENCE_KEYWORDS = (
    "实现依据", "挂钩点", "插入点", "真实夹具", "上游依赖",
    "现状代码", "既有", "复用", "源自", "参考",
)

# 交付语境动词：出现即视为「新建交付物」语境（参与缺件判定）。
_DELIVERABLE_VERBS = ("新增", "新建", "创建", "添加", "交付", "落地", "编写")

# tasks 勾选行：任务清单是交付物声明的第一语义位。
_CHECKBOX_RE = re.compile(r"^\s*[-*+]?\s*\[[ xX]\]")

# tasks.md 头部说明段边界：第一个 `## ` 二级标题（D1）。
_H2_RE = re.compile(r"^##\s")

# 能力 spec 文档的 Scenario 小节：场景中的路径是示例而非交付声明。
_SCENARIO_HEADING_RE = re.compile(r"^#{1,6}\s+.*Scenario", re.IGNORECASE)

# `## Deliverables` 显式声明段标题（planner 交付契约，守卫机械对账优先于正则提取）。
_DECLARED_HEADING_RE = re.compile(r"^##\s+Deliverables\s*$", re.IGNORECASE)

# basename 模糊匹配排除目录（D1，add-deliverable-declaration-triage）：产物/
# 依赖/状态目录不参与「疑似笔误」判定——node_modules/dist 的包内同名文件会在
# 不同 spec 语境反复误命中，.fenix/git 是框架自身状态而非交付落点。
_BASENAME_EXCLUDE_DIRS = (".git", "node_modules", "dist", ".fenix", "__pycache__")

# 声明段合法 kind：new=本仓库新建文件（硬校验）；modify=修改既有文件（硬校验）；
# delete=让该路径在合并后不存在（仅限入库文件，守卫反判存在性）；
# reference=运行时写入目标/既有引用（软校验，仅审计，不参与缺件判定）。
_DECLARED_KINDS = ("new", "modify", "delete", "reference")


def _is_deliverable_path(token: str) -> bool:
    """判断单个 token 是否为可校验的核心交付路径。"""
    tok = token.strip()
    if not tok:
        return False
    # 排除模板占位符（如 `.fenix/admin_disposition-<run_id>.json`）：<...> 是
    # 模式描述而非字面路径，永远无法按名落地，误判会令守卫永远缺件
    # （fix-admin-run-blocks-mainloop 事故 2026-09-01）。
    if "<" in tok or ">" in tok:
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


def normalize_check_path(p: str) -> str:
    """路径归一化（已退役为恒等映射，签名保留兼容既有调用方）。

    历史语义（正式化热修 4461231）：``.fenix`` 曾是指向项目根的自引用
    符号链接，``.fenix/x`` 语义等价根路径 ``x``，故做前缀归一化。该设计
    已废弃（状态文件迁入 .fenix/，提交 932a078）：``.fenix`` 现为实体
    目录，``.fenix/x`` 即字面路径、可按树查找——归一化若保留，根路径
    存在同名文件时会把 ``.fenix/x`` 缺件误判为存在（假放行）。

    Returns:
        原样返回（仅做首尾空白裁剪）。
    """
    return (p or "").strip()


def _classify_line(line: str, doc_kind: str, in_tasks_header: bool,
                   in_scenario: bool) -> str:
    """对单行做语境分类，返回 ``"deliverables"`` 或 ``"references"``。

    优先级（D1 规则表）：
    1. 能力 spec 文档的 Scenario 小节 → 引用（场景路径是示例）
    2. tasks 勾选行 → 交付物
    3. 引用语境关键词行 → 引用
    4. 交付语境动词行 → 交付物
    5. tasks.md 头部说明段（第一个 ``## `` 之前）→ 引用
    6. 无法判定 → 保守兜底：tasks 归交付物（宁误拦不漏放）；
       proposal / 能力 spec 正文归引用（叙事文档，无交付动词即非声明）
    """
    if doc_kind == "specs" and in_scenario:
        return "references"
    if _CHECKBOX_RE.match(line):
        return "deliverables"
    if any(k in line for k in _REFERENCE_KEYWORDS):
        return "references"
    if any(k in line for k in _DELIVERABLE_VERBS):
        return "deliverables"
    if doc_kind == "tasks" and in_tasks_header:
        return "references"
    return "deliverables" if doc_kind == "tasks" else "references"


def extract_paths_typed(spec_dir) -> dict:
    """从 SPEC 目录提取路径，按语境分为交付物与引用两类（D1/D2）。

    ``spec_dir`` 可为 ``str`` / ``Path``（指向 spec/changes/<spec>/）。
    仅读取 tasks.md / proposal.md / specs/*.md。

    Returns:
        ``{"deliverables": [...], "references": [...]}``——各自去重、保序；
        两类均为空表示守卫应跳过。``deliverables`` 参与守卫缺件判定；
        ``references`` 由守卫做软校验（缺失仅审计留痕，不阻断）。
    """
    root = Path(spec_dir)
    typed: dict = {"deliverables": [], "references": []}
    seen: set[str] = set()

    for doc in _iter_spec_documents(root):
        rel = doc.relative_to(root).as_posix() if doc.is_relative_to(root) \
            else doc.name
        if rel == "tasks.md":
            doc_kind = "tasks"
        elif rel == "proposal.md":
            doc_kind = "proposal"
        else:
            doc_kind = "specs"

        try:
            text = doc.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        in_fence = False
        in_tasks_header = True   # 第一个 `## ` 标题之前为头部说明段
        in_scenario = False      # 能力 spec 的 Scenario 小节
        line_ctx = "references" if doc_kind != "tasks" else "deliverables"

        for raw_line in text.splitlines():
            if _H2_RE.match(raw_line):
                in_tasks_header = False
            if _SCENARIO_HEADING_RE.match(raw_line):
                in_scenario = True
            elif _H2_RE.match(raw_line) or raw_line.startswith("#"):
                in_scenario = False

            # 围栏代码块：整块内所有行均视为显式路径声明，沿用块前语境
            if _FENCE_RE.match(raw_line):
                in_fence = not in_fence
                continue
            if in_fence:
                ctx = line_ctx
            else:
                ctx = _classify_line(raw_line, doc_kind, in_tasks_header,
                                     in_scenario)
                line_ctx = ctx

            if in_fence:
                # 代码块内逐 token（按空白/常见分隔符切分）
                tokens = [
                    _normalize_token(t)
                    for t in re.split(r"\s+", raw_line.strip())
                ]
            else:
                tokens = [_normalize_token(t)
                          for t in _candidates_from_line(raw_line)]

            for cand in tokens:
                if not _is_deliverable_path(cand) or cand in seen:
                    continue
                seen.add(cand)
                typed[ctx].append(cand)

    return typed


def extract_declared_entries(spec_dir) -> "list | None":
    """tasks.md ``## Deliverables`` 声明段原始条目（path + kind，保序）。

    ``extract_declared`` 与派发处方快照（add-deliverable-declaration-triage
    PR2 2.1）共用的条目级解析：返回过滤后的 ``[{"path": ..., "kind": ...}]``
    列表（kind ∈ new/modify/delete/reference）；无声明段、无有效围栏块、yaml 解析
    失败或全部条目非法 → ``None``。``extract_declared`` 按 kind 归类复用本函数，
    快照按条目级做存在性检查与 basename 匹配（kind 语义不可从归类结果反推）。
    """
    import yaml as _yaml

    tasks = Path(spec_dir) / "tasks.md"
    try:
        text = tasks.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if _DECLARED_HEADING_RE.match(line):
            start = i + 1
            break
    if start is None:
        return None

    block: List[str] = []
    in_fence = False
    for line in lines[start:]:
        if _H2_RE.match(line):
            break
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            block.append(line)
    if not block:
        return None
    try:
        entries = _yaml.safe_load("\n".join(block))
    except Exception:
        return None
    if not isinstance(entries, list):
        return None

    out: List[dict] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        path = str(e.get("path") or "").strip()
        kind = str(e.get("kind") or "").strip().lower()
        if not path or kind not in _DECLARED_KINDS:
            continue
        if (_ABSOLUTE_RE.match(path) or _WILDCARD_RE.search(path)
                or _DIRECTORY_RE.search(path)):
            continue
        out.append({"path": path, "kind": kind})
    return out if out else None


def extract_declared(spec_dir) -> "dict | None":
    """tasks.md 的 ``## Deliverables`` 显式声明段（planner 交付契约）。

    语义：planner 在 tasks.md 中用 fenced yaml 显式声明交付清单与语境类别，守卫
    做机械对账，不再做正则语境猜测（语境分类曾致三次误判事故：Scenario 示例、
    ``<run_id>`` 占位符、勾选行内的运行时写入目标 ``.fenix/config.yaml``）。

    格式（tasks.md 内）::

        ## Deliverables

        ```yaml
        - path: core/dashboard/data.py
          kind: modify
        - path: .fenix/config.yaml
          kind: reference   # 运行时写入目标，非本仓库交付物
        ```

    kind 语义见 ``_DECLARED_KINDS``：new/modify/delete → deliverables（硬校验，
    delete 为反判——合并后必须不存在）；reference → references（软校验）。声明段
    不受 ``_DELIVERABLE_PREFIXES`` 限制（skills/ 等前缀同样可声明为交付物）。

    Returns:
        ``{"deliverables": [...], "references": [...]}``；无声明段、无有效围栏块、
        yaml 解析失败或全部条目非法 → ``None``（守卫回退 ``extract_paths_typed``，
        向后兼容存量 spec）。
    """
    entries = extract_declared_entries(spec_dir)
    if not entries:
        return None
    typed: dict = {"deliverables": [], "references": []}
    for e in entries:
        path, kind = e["path"], e["kind"]
        if path in typed["deliverables"] or path in typed["references"]:
            continue
        key = "deliverables" if kind in ("new", "modify", "delete") else "references"
        typed[key].append(path)
    if not typed["deliverables"] and not typed["references"]:
        return None
    return typed


def replace_declared_path(spec_dir, element: str, actual_path: str) -> dict:
    """机械替换 tasks.md 声明段条目的 path（add-deliverable-declaration-triage D4）。

    在 tasks.md ``## Deliverables`` 段内找到 ``path == element`` 的条目并确定
    性替换其 path 为 ``actual_path``；若声明段内已存在同名 actual_path 条目
    （同 kind）则删除 element 条目（去重）。逐行精确文本操作（不经 yaml 反序列
    化再序列化——保留注释/顺序，diff 最小）。修正前重读文件、按条目精确替换，
    任何失败上抛（调用方等价 ``unclear`` 转人工，design D4/D6）。

    Returns:
        {"element", "actual_path", "before": <声明段原文>, "after": <声明段新文>}，
        供审计流落 diff（4.5）。
    """
    tasks = Path(spec_dir) / "tasks.md"
    text = tasks.read_text(encoding="utf-8")
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if _DECLARED_HEADING_RE.match(line):
            start = i + 1
            break
    if start is None:
        raise ValueError(f"tasks.md 无 Deliverables 声明段（无法修正 {element}）")
    end = len(lines)
    for i in range(start, len(lines)):
        if _H2_RE.match(lines[i]):
            end = i
            break

    def _path_line_re(p: str):
        return re.compile(
            rf"^(\s*-\s*path\s*:\s*){re.escape(p)}(\s*(#.*)?)$"
        )

    elem_idx = None
    for i in range(start, end):
        if _path_line_re(element).match(lines[i]):
            elem_idx = i
            break
    if elem_idx is None:
        raise ValueError(f"声明段无条目匹配 {element}（无法修正）")

    before = "\n".join(lines[start:end])
    # 去重：声明段已存在 actual_path 条目 → 删除 element 条目（path 行 + 紧随
    # 的 kind 行），而不是制造两份同名声明
    dup_idx = None
    for i in range(start, end):
        if i != elem_idx and _path_line_re(actual_path).match(lines[i]):
            dup_idx = i
            break
    if dup_idx is not None:
        remove_end = elem_idx + 1
        if remove_end < len(lines) and re.match(r"^\s+kind\s*:", lines[remove_end]):
            remove_end += 1
        del lines[elem_idx:remove_end]
    else:
        m = _path_line_re(element).match(lines[elem_idx])
        lines[elem_idx] = f"{m.group(1)}{actual_path}{m.group(2)}"
    after = "\n".join(lines[start:end])

    tasks.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"element": element, "actual_path": actual_path,
            "before": before, "after": after}


def soften_declared_kind(spec_dir, element: str) -> dict:
    """将 tasks.md 声明段条目的 kind 改为 reference（D4：reference 软化）。

    确定性文本替换：``kind: new/modify → kind: reference``，该路径移入 references
    软校验（不再参与守卫缺件判定）。条目不存在/无 kind 行/改写失败上抛（调用方
    等价 ``unclear`` 转人工）。

    ``kind: delete`` 条目拒绝软化（add-deliverable-delete-kind D4 防御性防线）：
    软化 = 把「该删」降级为「仅审计」，删除要求静默消失——lint 规则 7-10 已在
    晋升期拒绝 delete 的不可交付形态，走到软化说明声明有问题，应升级人工而非
    自动降级。命中 delete 上抛（调用方等价 ``unclear`` 转人工，不静默改写）。

    Returns:
        {"element", "before": <声明段原文>, "after": <声明段新文>}。
    """
    tasks = Path(spec_dir) / "tasks.md"
    text = tasks.read_text(encoding="utf-8")
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if _DECLARED_HEADING_RE.match(line):
            start = i + 1
            break
    if start is None:
        raise ValueError(f"tasks.md 无 Deliverables 声明段（无法软化 {element}）")
    end = len(lines)
    for i in range(start, len(lines)):
        if _H2_RE.match(lines[i]):
            end = i
            break

    path_idx = None
    for i in range(start, end):
        if re.match(rf"^\s*-\s*path\s*:\s*{re.escape(element)}\s*(#.*)?$",
                    lines[i]):
            path_idx = i
            break
    if path_idx is None:
        raise ValueError(f"声明段无条目匹配 {element}（无法软化）")

    before = "\n".join(lines[start:end])
    kind_idx = None
    kind_match = None
    for i in range(path_idx + 1, min(end, path_idx + 3)):
        m = re.match(
            r"^(\s*)kind\s*:\s*(new|modify|delete|reference)(\s*(#.*)?)$",
            lines[i],
        )
        if m:
            kind_idx = i
            kind_match = m
            break
    if kind_idx is None or kind_match is None:
        raise ValueError(f"条目 {element} 无 kind 行可软化")
    if kind_match.group(2) == "delete":
        # 防洗白：delete 的软化在语义上就是错的（降级为仅审计 = 删除要求静默
        # 消失），lint 规则 7-10 已拒绝其不可交付形态；此处防御性拒绝并上抛
        # （调用方等价 unclear 转人工，不静默改写声明段）。
        raise ValueError(
            f"条目 {element} 是 kind: delete——delete 不参与软化（防洗白，"
            f"add-deliverable-delete-kind D4），请人工处置")

    lines[kind_idx] = f"{kind_match.group(1)}kind: reference{kind_match.group(3)}"
    after = "\n".join(lines[start:end])

    tasks.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"element": element, "before": before, "after": after}


def extract_paths(spec_dir) -> List[str]:
    """从 SPEC 目录提取声明交付的文件路径清单（去重、保序）。

    兼容包装（add-deliverable-extractor-semantics D2）：等价于
    ``extract_paths_typed`` 的 deliverables 与 references 拼接去重——
    平面列表不再区分语境，语境语义由 typed 版本与守卫调用点承接。
    既有调用方与测试行为不变。

    ``spec_dir`` 可为 ``str`` / ``Path``（指向 spec/changes/<spec>/）。
    仅读取 tasks.md / proposal.md / specs/*.md；无任何可提取路径时返回空列表。

    Returns:
        相对项目根的去重路径列表；为空列表表示守卫应跳过。
    """
    typed = extract_paths_typed(spec_dir)
    ordered: List[str] = []
    for path in typed["deliverables"] + typed["references"]:
        if path not in ordered:
            ordered.append(path)
    return ordered


def match_basename_in_tree(project_root, path: str) -> List[str]:
    """主树 basename 精确匹配（add-deliverable-declaration-triage D1）。

    以 ``Path(path).name`` 对主树文件做 basename 精确匹配（rglob），排除
    ``_BASENAME_EXCLUDE_DIRS``（``.git``/``node_modules``/``dist``/
    ``.fenix``/``__pycache__``）目录内的命中；返回相对项目根的命中路径列表，
    确定性排序（字符串升序）。不引入编辑距离/模糊串匹配（D1：basename 内
    笔误如 ``verifcation.py`` 由 judge 层兜底，lint 层保持零误拦取向）。

    ``new`` 声明路径在主树不存在时调用（晋升 lint 规则 4 与派发处方干跑共用），
    命中唯一即判疑似笔误候选；零或多命中放行（交由后续层兜底）。

    Args:
        project_root: 项目根（主树基准）。
        path: 声明路径（以其余 ``Path(path).name`` 为匹配键）。

    Returns:
        命中相对路径列表（排序）；无命中或遍历异常返回空列表（fail-open）。
    """
    root = Path(project_root)
    name = Path(path or "").name
    if not name:
        return []
    excluded = set(_BASENAME_EXCLUDE_DIRS)
    hits: List[str] = []
    try:
        for p in root.rglob(name):
            if not p.is_file():
                continue
            try:
                rel = p.relative_to(root).as_posix()
            except ValueError:
                continue
            if set(rel.split("/")) & excluded:
                continue
            hits.append(rel)
    except OSError:
        return []
    hits.sort()
    return hits


def _path_is_gitignored(project_root, candidates: List[str]) -> bool:
    """任一 candidate 被 .gitignore 排除返回 True（规则 5 判定核心）。

    用 ``git check-ignore -q`` 而非自写 gitignore 解析：嵌套 .gitignore 与
    否定规则（``.fenix/*`` + ``!.fenix/verify.yaml``）语义复杂，check-ignore
    原生正确。returncode 0=被排除；1=未排除；其余（非仓库等 git 错误）与
    subprocess 异常一律 fail-open 视为未排除（不因环境缺 git 阻塞晋升）。

    Args:
        project_root: 项目根（check-ignore 的 cwd，须为 git 仓库内）。
        candidates: 待判定路径（字面 + 归一化）。

    Returns:
        任一路径被排除返回 True；未被排除或判定不可用返回 False。
    """
    for cand in candidates:
        try:
            r = subprocess.run(
                ["git", "-c", "core.fsmonitor=", "check-ignore", "-q", "--", cand],
                cwd=str(project_root), capture_output=True, timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        if r.returncode == 0:
            return True
        # >=2 = git 自身错误（非仓库等）：fail-open 视为未排除，继续下一候选
    return False


def _path_is_outside_root(project_root, candidates) -> bool:
    """任一 candidate 解析后不在 project_root 内返回 True（规则 6 判定核心）。

    判定顺序（design D1）：``os.path.expanduser``（``~``/``~user`` 展开）；相对
    路径先拼接到 project_root 下（声明段路径相对项目根而非 cwd）；``resolve``
    （``..`` 越界在此归一）；与 resolve 后的 project_root 做前缀判定
    （``os.path.commonpath``，``..`` 段已消解）。非仓库外（含仓库内相对路径）
    → False；解析异常 fail-open 返回 False（不因判定故障阻塞晋升）。

    ``reference`` 不受本函数约束（它就是非交付物语义，仓库外引用合法放行）。

    Args:
        project_root: 项目根（前缀判定基准，resolve 后使用）。
        candidates: 待判定路径（字面 + 归一化候选）。

    Returns:
        任一路径解析后不在根内返回 True；全部在根内或判定不可用返回 False。
    """
    root = Path(project_root).resolve()
    for cand in candidates:
        try:
            p = Path(os.path.expanduser(str(cand)))
            p = p if p.is_absolute() else (root / p)
            resolved = p.resolve()
            common = os.path.commonpath([str(root), str(resolved)])
            if common != str(root):
                return True
        except (OSError, ValueError, TypeError):
            # fail-open：判定故障（非法路径/平台差异）视为在根内，不阻塞晋升
            continue
    return False


def classify_unsatisfiable(entry, project_root) -> bool:
    """判定声明条目是否命中确定性不可交付模式（design D1）。

    ``kind ∈ {new, modify}`` 且（``_path_is_gitignored`` 或
    ``_path_is_outside_root`` 命中）→ True。``reference`` 恒 False（它就是软化
    终点）；``delete`` 恒 False（add-deliverable-delete-kind D4：soften 的语义
    是降级为仅审计 reference 软校验，对 delete 即等于删除要求静默消失——复刻
    本 SPEC 要消灭的形态，故 delete 的不可交付形态已在 lint 阶段（规则 7-10）
    拒绝，走到软化说明声明本身有问题，应升级人工而非自动降级）；entry 缺
    path/kind、path/kind 非法或判定异常均返回 False（fail-open，交由后续 lint
    照常拒绝兜底）。

    排除规则 1-4 形态（design D1：这四种不软化，维持既有拒绝语义——需 path
    修正非 kind 修正）：
    - 占位符（``<``/``>``）路径：规则 1，软化会掩盖声明格式问题；
    - 目录路径（``kind: modify`` + 主树存在且为目录）：规则 2，软化后 lint
      不再拦截但语义仍不可交付；

    零语义推断：只认 gitignored（check-ignore 原生判定）与仓库外（路径解析）
    两个确定性信号。

    Args:
        entry: 声明条目 dict（含 ``path`` / ``kind``）。
        project_root: 项目根（判定基准）。

    Returns:
        命中不可交付模式返回 True；其余（含 reference、缺字段、判定不可用、
        规则 1-4 形态）返回 False。
    """
    if not isinstance(entry, dict):
        return False
    path = str(entry.get("path") or "").strip()
    kind = str(entry.get("kind") or "").strip().lower()
    if not path or kind not in _DECLARED_KINDS:
        return False
    if kind not in ("new", "modify"):
        # reference 恒 False（软化终点，无需求再软化）；delete 恒 False
        # （软化即删除要求静默消失，D4 防洗白——见本函数 docstring）
        return False
    # ── 排除规则 1-4 形态（不软化，维持既有拒绝语义）──
    # 规则 1：占位符路径（软化会掩盖声明格式问题）
    if "<" in path or ">" in path:
        return False
    # 规则 2：目录路径（软化为 reference 后 lint 不再拦截，但目录不可交付）
    if kind == "modify":
        candidates_dir = [path]
        normalized_dir = normalize_check_path(path)
        if normalized_dir != path:
            candidates_dir.append(normalized_dir)
        pr = Path(project_root)
        if any(pr.joinpath(c).is_dir() for c in candidates_dir):
            return False
    # ── 正向命中判定 ──
    candidates = [path]
    normalized = normalize_check_path(path)
    if normalized != path:
        candidates.append(normalized)
    if _path_is_gitignored(project_root, candidates):
        return True
    return _path_is_outside_root(project_root, candidates)


def soften_unsatisfiable_declarations(spec_dir, project_root) -> list:
    """晋升前软化命中不可交付模式的 new/modify 声明（design D1/D2）。

    逐条 ``classify_unsatisfiable``，命中即 ``soften_declared_kind``
    （kind → reference 确定性文本改写）；单条改写异常（并发改写/格式漂移）
    跳过该条记 warning 不中断（fail-safe，交由后续 lint 拒绝兜底）。
    ``kind: delete`` 条目显式跳过（add-deliverable-delete-kind D4 防御性防线：
    即使上游 classify 已拦，软化入口也须拒绝把「该删」降级为「仅审计」——
    否则 lint 规则 7-10 之外的未来软化路径会静默复刻原缺口；审计 warning
    留痕说明跳过原因）。
    无声明段（``extract_declared_entries`` 返回 None）早退返回 []。

    Returns:
        软化记录 ``[{element, kind_before, kind_after, reason}]``（保序）；
        ``reason`` 区分 ``"gitignored"`` 与 ``"outside-root"``，供审计
        reasoning 构造；无命中返回 []。
    """
    entries = extract_declared_entries(spec_dir)
    if not entries:
        return []
    softened: list = []
    for e in entries:
        path = e["path"]
        if e.get("kind") == "delete":
            # 防洗白：delete 的软化在语义上就是错的（降级为仅审计 = 删除要求
            # 静默消失），lint 规则 7-10 已拒绝其不可交付形态；此处防御性跳过
            # 并留痕，防止未来新增软化路径时无声破防。
            print(f"WARNING: 软化跳过 delete 声明 {path}（防洗白：delete 不参与"
                  f"软化，见 add-deliverable-delete-kind D4）")
            continue
        if not classify_unsatisfiable(e, project_root):
            continue
        # 判定 reason（供审计 reasoning 区分 gitignored / outside-root）
        reason = "gitignored"
        try:
            # 归一化候选与 classify 同源
            candidates = [path]
            normalized = normalize_check_path(path)
            if normalized != path:
                candidates.append(normalized)
            if not _path_is_gitignored(project_root, candidates):
                reason = "outside-root"
        except Exception:
            reason = "outside-root"  # 判定异常保守取 outside-root
        try:
            soften_declared_kind(spec_dir, path)
        except Exception as exc:
            # 单条改写失败：跳过该条记 warning，交由后续 lint 照常拒绝兜底
            print(f"WARNING: 软化声明 {path} 失败（跳过，lint 兜底）: {exc}")
            continue
        softened.append({
            "element": path,
            "kind_before": e["kind"],
            "kind_after": "reference",
            "reason": reason,
        })
    return softened


def lint_declared(spec_dir, project_root) -> List[str]:
    """晋升 lint（drafted → ready）：Deliverables 声明形态机械校验。

    不可满足/失效的声明在撰写当下拦截（spec 停留 drafted + error 提示），
    不再等到收工守卫才暴露——守卫判定发生在一次完整实现 run 之后，声明
    形态错误的代价是一轮 run + 打回循环（remove-auto-run-cleanup 目录声明
    死锁事故 2026-09-03）。

    规则（零误拦取向，只拦确定性无效形态）：
    0. 声明段形态本身不可解析（2026-09-14 自进化草稿格式事故）：
       ``## Deliverables`` 标题存在但段内无 fenced yaml 块 / yaml 语法错 /
       顶层非列表 / 条目缺 path / kind 非法值——五种形态下声明等于不存在，
       下游 ``extract_declared_entries`` 一律返回 ``None`` 并静默回退守卫的
       正则语境猜测（声明机制要消灭的正是这套猜测），故必须在此拦下。无
       ``## Deliverables`` 标题的存量 spec 仍返回空清单（不在 lint 职责内）。
       事故原形：自进化草稿把 Deliverables 写成平铺 Markdown 列表 + 缩进
       path/kind 子项、kind 用 ``feature``/``test``/``chore`` 自造词，lint 全
       部静默放行，只剩任务分组规则报错，失败信息指向不到真问题；
    1. 路径含 ``<``/``>`` 模板占位符——守卫的 ``_is_deliverable_path`` 会静默
       跳过该条目，声明形同虚设（fix-admin-run-blocks-mainloop 同族坑）；
    2. ``kind: modify`` 的路径在主树是目录——目录声明与守卫判定形态不匹配
       （守卫按 blob/tree 校验对象，精确到文件的声明才可对账），处方：改为
       目录下确定性锚点文件（如 ``dist/index.html``）；
    3. ``kind: modify``/``kind: reference`` 的路径在主树不存在（存在性硬校验，
       add-deliverable-declaration-triage D1）——modify 语义即修改既有文件、
       reference 语义即既有引用，不存在即声明有错，停留 drafted 附 error；
    4. ``kind: new`` 的路径在主树不存在时做 basename 模糊匹配（规则 3 同型
       形态错误），仓库内唯一命中即判疑似笔误拒绝晋升，违规消息直接给出疑似
       目标路径；零命中或多命中放行（fail-open 取向，交由派发处方与守卫终审
       层兜底——语义矛盾（多 basename 命中/basename 内笔误/语境等价）原理上
       需要 LLM 裁决，lint 只拦确定性唯一命中）。
    5. ``kind: modify``/``kind: new`` 的路径被 .gitignore 排除——modify 语义
       即修改已入库文件、new 语义即产出提交入库，gitignored 文件两者均不可
       满足，守卫的 git 对账在任何分支必报缺件（add-spec-hooks dist/index.html
       守卫自伤事故 2026-09-06 同型）。``kind: reference`` 不受限：gitignored
       运行时产物/配置作 reference（仅审计留痕、不参与守卫硬校验）是既有
       合法模式（.fenix/config.yaml、dist/index.html 先例）。
    6. 仓库外路径（add-declaration-premechanize D3）——``kind: modify``/``kind:
       new`` 的路径解析后（``~`` 展开、``..`` 越界、绝对路径归一）不在项目根内，
       规则 5 的 gitignore 机制覆盖不到仓库外，该声明任何分支不可交付。```
       ``kind: reference`` 不受限：仓库外引用（``~/.claude/settings.json`` 等）
       本就是非交付物语义，合法放行。
    7. ``kind: delete`` 的路径被 .gitignore 排除（add-deliverable-delete-kind
       D1）——delete 语义即「合并后该路径不存在」，仅限入库文件；gitignored
       路径不属于任何分支，守卫反判（分支 HEAD 存在即违规）恒判通过 → 静默
       空跑（add-stale-code-selfheal 事故同型），必须在立项当下拒绝；处方：
       gitignored 运行时文件的删除不进 Deliverables 段，由人工在主树执行。
    8. ``kind: delete`` 的路径在主树不存在——delete 语义即删除既有入库文件，
       主树不存在即无可删（声明 vs 现实的确定性矛盾，零误拦），应核对声明
       路径（新建文件请用 kind: new）。
    9. ``kind: delete`` 的路径在主树是目录——delete 是文件删除语义，目录删除
       无法按 blob 对账（守卫按文件存在性校验），应改为目录下确定性锚点文件
       或从声明中移除。
    10. ``kind: delete`` 的路径在仓库外——delete 要求删除仓库内已入库文件，
        仓库外路径超出守卫 git 对账范围（规则 7 同型：守卫反判无从成立），
        任何分支不可交付，应改为仓库内路径。

    lint 自身故障一律 fail-open（返回空清单放行晋升），不因 lint 阻塞流水线。
    规则 0 的形态违规属「内容确定性无效」而非 lint 故障，照常返回违规。

    Args:
        spec_dir: SPEC 目录（spec/changes/<spec>/）。
        project_root: 项目根（主树路径存在性判定基准）。

    Returns:
        违规描述清单；空列表 = 通过。
    """
    import yaml as _yaml

    spec_dir = Path(spec_dir)
    project_root = Path(project_root)
    tasks = spec_dir / "tasks.md"
    try:
        text = tasks.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if _DECLARED_HEADING_RE.match(line):
            start = i + 1
            break
    if start is None:
        return []  # 无声明段（存量 spec）不在 lint 职责内

    block: List[str] = []
    in_fence = False
    for line in lines[start:]:
        if _H2_RE.match(line):
            break
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            block.append(line)
    if not block:
        return [
            "Deliverables 声明段存在但未解析出 fenced yaml 块——声明条目必须写在"
            "```yaml 围栏内（每条 `- path: <具体文件>` + `  kind: <new|modify|"
            "delete|reference>` 两行），平铺的 Markdown 列表或缩进子项不会被"
            "下游解析器识别，等同未声明（守卫会回退正则语境猜测）；"
            "请改为 fenced yaml 块后重试晋升"
        ]
    try:
        entries = _yaml.safe_load("\n".join(block))
    except Exception as e:
        return [
            f"Deliverables 声明段 yaml 语法错误（{e}）——声明条目必须能被 "
            f"yaml.safe_load 解析为列表，当前解析失败等同未声明；"
            f"请修正该 fenced yaml 块语法后重试晋升"
        ]
    if not isinstance(entries, list):
        return [
            f"Deliverables 声明段顶层必须是列表——当前 yaml 解析为 "
            f"{type(entries).__name__}，声明条目须为 `- path: ...` 序列；"
            f"请修正后重试晋升"
        ]

    violations: List[str] = []
    for e in entries:
        if not isinstance(e, dict):
            violations.append(
                f"Deliverables 声明条目必须是映射——当前为 "
                f"{type(e).__name__}（{e!r}），条目形态为 "
                f"`- path: <具体文件>` + `  kind: <kind>`；"
                f"该条目等同未声明，请修正后重试晋升"
            )
            continue
        path = str(e.get("path") or "").strip()
        kind = str(e.get("kind") or "").strip().lower()
        if not path:
            violations.append(
                f"Deliverables 声明条目缺 path——条目 {e!r} 无法对账，"
                f"请补 path（具体文件路径）后重试晋升"
            )
            continue
        if kind not in _DECLARED_KINDS:
            violations.append(
                f"[{path}] kind 非法: {kind or '（缺 kind）'}——合法值仅 "
                f"{'/'.join(_DECLARED_KINDS)}（语义：new 产出入库 / modify 改"
                f"既有入库文件 / delete 删除既有入库文件 / reference 既有引用"
                f"仅审计留痕）；自造词（feature/test/chore 等）等同未声明，"
                f"请改写为合法 kind 后重试晋升"
            )
            continue
        if "<" in path or ">" in path:
            violations.append(
                f"[{path}] 含 <...> 模板占位符——守卫会静默跳过该条目，"
                f"声明形同虚设，请改为具体字面路径"
            )
            continue
        # 目录声明按字面路径判定（.fenix 归一化已退役，恒等映射自然退化）
        candidates = [path]
        normalized = normalize_check_path(path)
        if normalized != path:
            candidates.append(normalized)
        # 规则 5（gitignored 不可满足声明，add-spec-hooks dist 守卫自伤防复发
        # 2026-09-06）：modify/new 语义均以「文件可入 git」为前提，被 .gitignore
        # 排除即任何分支不可满足。不 continue：目录/存在性校验相互独立，可叠加。
        if kind in ("modify", "new") and _path_is_gitignored(project_root, candidates):
            violations.append(
                f"[{path}] 被 .gitignore 排除——{kind} 声明要求文件"
                f"{'已入库可修改' if kind == 'modify' else '产出可提交入库'}，"
                f"gitignored 文件在守卫 git 对账下任何分支不可满足"
                f"（add-spec-hooks dist 守卫自伤同型）；请改为 kind: reference"
                f"（仅审计留痕，不参与守卫硬校验）或从声明中移除"
            )
        # 规则 6（add-declaration-premechanize D3）：仓库外路径。规则 5 的
        # gitignore 机制覆盖不到仓库外（~/x.md、../outside.md 等展开/越界后
        # 不在项目根内）；kind: new/modify 语义均以文件在仓库内为前提，仓库外
        # 路径任何分支不可交付。reference 放行（reference 本就是非交付物语义，
        # 仓库外引用合法）。与规则 5 并列共存、相互独立，可叠加违规。
        if kind in ("modify", "new") and _path_is_outside_root(
                project_root, candidates):
            violations.append(
                f"[{path}] 是仓库外路径——{kind} 声明要求文件在仓库内"
                f"（{'修改既有仓库文件' if kind == 'modify' else '产出入库'}），"
                f"仓库外路径不可作为 {kind} 交付物，应声明 reference"
                f"或改为仓库内路径"
            )
        if kind == "modify":
            is_dir = any((project_root / c).is_dir() for c in candidates)
            if is_dir:
                violations.append(
                    f"[{path}] 是目录——目录声明无法精确对账（tree ≠ 具体交付物），"
                    f"请改为目录下确定性锚点文件（如 dist/index.html）"
                )
                # 目录本身在主树存在：不落入下方存在性校验（避免重复违规）
                continue
        # 规则 3（add-deliverable-declaration-triage D1）：modify/reference
        # 路径在主树必须存在。reference 语义即既有引用，modify 语义即修改既有
        # 文件——不存在即声明有错（声明 vs 现实的确定性矛盾，零误拦）。
        # 例外：仓库外 reference 放行（design D3：reference 本就是非交付物语义，
        # ~/x.md/.claude/settings.json 等仓库外引用合法，软化后转 reference
        # 不应被存在性校验拦截）。
        if kind in ("modify", "reference"):
            if not any((project_root / c).exists() for c in candidates):
                # reference 仓库外放行（design D3）
                if kind == "reference" and _path_is_outside_root(
                        project_root, candidates):
                    continue
                violations.append(
                    f"[{path}] 在主树不存在——{kind} 声明路径必须在主树存在"
                    f"（必须存在，指向既有文件），请核对声明路径"
                    f"（新建文件请用 kind: new）"
                )
            continue
        # 规则 7-10（add-deliverable-delete-kind D1）：kind: delete 四类拒绝。
        # delete 语义即「合并后该路径不存在」，仅限入库文件，守卫反判存在性
        # （分支 HEAD 仍有该 blob 即 undeleted）。守卫判定基准是实现分支 blob，
        # gitignored 路径不属于任何分支 → 反判恒通过 → 静默空跑（add-stale-code-
        # selfheal 事故同型），故以下四类确定性不可交付形态在立项当下拒绝：
        #  7  gitignored 排除（不可入 git，删除无法落库）——处方明示运行时文件
        #     删除不进 Deliverables 段、由人工在主树执行；
        #  8  主树不存在（无可删，声明 vs 现实确定性矛盾）；
        #  9  是目录（删除语义针对具体文件，tree 无法按 blob 反判）；
        #  10 仓库外（超出守卫 git 对账范围，反判无从成立）。
        if kind == "delete":
            # 规则 7：gitignored——与规则 5 并列共存、相互独立，可叠加违规
            if _path_is_gitignored(project_root, candidates):
                violations.append(
                    f"[{path}] 被 .gitignore 排除——delete 声明要求删除已入库"
                    f"文件，gitignored 路径不属于任何分支，守卫反判恒通过即"
                    f"静默空跑（add-stale-code-selfheal 事故同型）；运行时文件"
                    f"的删除不进 Deliverables 段，由人工在主树执行"
                )
            # 规则 10：仓库外——与规则 7 并列共存、相互独立，可叠加违规
            if _path_is_outside_root(project_root, candidates):
                violations.append(
                    f"[{path}] 是仓库外路径——delete 声明要求删除仓库内已入库"
                    f"文件，仓库外路径超出守卫 git 对账范围（反判无从成立），"
                    f"请改为仓库内路径或从声明中移除"
                )
            # 规则 9：目录——目录删除无法按 blob 反判，先于存在性判定
            is_dir = any((project_root / c).is_dir() for c in candidates)
            if is_dir:
                violations.append(
                    f"[{path}] 是目录——delete 是文件删除语义（tree 无法按 "
                    f"blob 反判存在），请改为目录下确定性锚点文件"
                    f"（如 dist/index.html）或从声明中移除"
                )
                # 目录在主树存在：不落入下方存在性校验（避免重复违规）
                continue
            # 规则 8：主树不存在（无可删）——零误拦确定性矛盾
            if not any((project_root / c).exists() for c in candidates):
                violations.append(
                    f"[{path}] 在主树不存在——无可删（delete 声明路径必须在"
                    f"主树存在，指向既有入库文件），请核对声明路径"
                    f"（新建文件请用 kind: new）"
                )
            continue
        # 规则 4（D1）：new 路径主树不存在时做 basename 模糊匹配，仓库内唯一
        # 命中即判疑似笔误拒绝晋升；零命中或多命中放行（语义矛盾交由后续层）。
        if kind == "new":
            if any((project_root / c).exists() for c in candidates):
                continue
            hits = match_basename_in_tree(project_root, path)
            if len(hits) == 1:
                violations.append(
                    f"[{path}] 在主树不存在，疑似笔误——仓库内唯一 basename "
                    f"命中 [{hits[0]}]，请修正声明路径或改 kind"
                )
    return violations


# tasks.md 分组标题正则（task-track D2「同源规则」）：与
# core/dashboard/data.py:parse_tasks 及 bin/fenix_process.py:parse_tasks 的
# 分组正则字面量互指，三处必须保持一致（点号可选双历史格式兼容：
# `## 1. 标题` 与 `## 1 标题`）。漂移由 tests/test_task_track.py 双格式
# Scenario 兜底。
_TASKS_GROUP_RE = re.compile(r"^##\s+\d+\.?\s+(.+)$")

# 任务项正则：与 data.py:parse_tasks / fenix_process.py:parse_tasks 同源。
_TASKS_ITEM_RE = re.compile(r"^- \[(x| )\]")


def _tasks_parse_counts(text: str) -> tuple:
    """tasks.md 文本解析计数纯函数（task-track D2「同源规则」复用点）。

    Args:
        text: tasks.md 全文。

    Returns:
        (分组数, 任务行数) 二元组。分组按 ``_TASKS_GROUP_RE`` 匹配；
        任务行按 ``_TASKS_ITEM_RE``（checkbox 前缀）计数——只要求
        checkbox、不要求任务 id，与 data.py 口径相比偏宽松：本门禁的
        目的是「下游能否展示出任务」，checkbox 存在即可读出任务。
    """
    group_count = 0
    item_count = 0
    for line in text.split("\n"):
        if _TASKS_GROUP_RE.match(line):
            group_count += 1
        if _TASKS_ITEM_RE.match(line):
            item_count += 1
    return group_count, item_count


def lint_tasks_text(text: str) -> List[str]:
    """tasks.md 文本可解析性判定（task-track R2 同源规则，收口复检共用）。

    ``lint_tasks_parseable`` 与 dispatch 收口复检挂点（full/fast-track 车道）
    共用同一判定逻辑，避免两套解析口径漂移。文本形态直接判定：

    - 0 个任务分组（含文件为空/无任务行的情形）→ 违规（既有形态，拦截早于
      run 烧钱）；
    - 分组数 ≥ 1 但任务行总数为 0（2026-09-11 add-impl-terminal-nocommit-gate
      事故形态：sed 把任务行写成 ``^- [x] 1.1 …``，分组完好、任务行全灭）
      → 违规，文案点名损伤特征并给出修正处方；
    - 分组与任务行均正常 → 放行。

    Returns:
        违规描述清单；空列表 = 通过。
    """
    group_count, item_count = _tasks_parse_counts(text)

    if group_count == 0:
        return [
            "tasks.md 存在但未解析出任务分组——分组标题必须为 `## <编号>. <标题>`"
            "（阿拉伯数字编号，点号可选），如 `## 1. Setup`；"
            "当前格式无法被下游解析器跟踪，请修正后重新晋升"
        ]
    if item_count == 0:
        return [
            "tasks.md 存在任务分组（"
            f"{group_count} 个），但未解析出任何任务行——任务行必须为 "
            "`- [ ] <编号>. <任务>` / `- [x] <编号>. <任务>` 行首形态"
            "（行首仅 `-` 空格 `[`，不得有多余字符）；若任务行以 `^-` 开头"
            "（如 `^- [x] 1.1 …`）即 sed 转义损伤特征，请改用编辑器直接勾选："
            "把 `^- [` 改回 `- [ ` 并恢复 `[x]`/`[ ]`，否则下游无法跟踪任务"
        ]
    return []


def lint_tasks_parseable(spec_dir, project_root) -> List[str]:
    """晋升 lint（drafted → ready）：tasks.md 可解析性校验（task-track R2）。

    tasks.md 不存在 → 返回 ``[]``（不拦：fast-track 前置 spec 允许后补）。
    存在 → 交由 ``lint_tasks_text`` 判定（与收口复检挂点同源同口径）。
    本函数不读 ``project_root``，仅保持与 ``lint_declared`` 同构签名
    （统一调用点形态）。

    Returns:
        违规描述清单；空列表 = 通过。读取类异常直接上抛，由调用方
        （engine）的 fail-open 语义兜底。
    """
    spec_dir = Path(spec_dir)
    tasks = spec_dir / "tasks.md"
    if not tasks.exists():
        return []
    text = tasks.read_text(encoding="utf-8")
    return lint_tasks_text(text)
