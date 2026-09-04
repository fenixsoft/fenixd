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

# 声明段合法 kind：new=本仓库新建文件（硬校验）；modify=修改既有文件（硬校验）；
# reference=运行时写入目标/既有引用（软校验，仅审计，不参与缺件判定）。
_DECLARED_KINDS = ("new", "modify", "reference")


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

    ``spec_dir`` 可为 ``str`` / ``Path``（指向 openspec/changes/<spec>/）。
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

    kind 语义见 ``_DECLARED_KINDS``：new/modify → deliverables（硬校验）；
    reference → references（软校验）。声明段不受 ``_DELIVERABLE_PREFIXES``
    限制（skills/ 等前缀同样可声明为交付物）。

    Returns:
        ``{"deliverables": [...], "references": [...]}``；无声明段、无有效围栏块、
        yaml 解析失败或全部条目非法 → ``None``（守卫回退 ``extract_paths_typed``，
        向后兼容存量 spec）。
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

    typed: dict = {"deliverables": [], "references": []}
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
        if path in typed["deliverables"] or path in typed["references"]:
            continue
        key = "deliverables" if kind in ("new", "modify") else "references"
        typed[key].append(path)
    if not typed["deliverables"] and not typed["references"]:
        return None
    return typed


def extract_paths(spec_dir) -> List[str]:
    """从 SPEC 目录提取声明交付的文件路径清单（去重、保序）。

    兼容包装（add-deliverable-extractor-semantics D2）：等价于
    ``extract_paths_typed`` 的 deliverables 与 references 拼接去重——
    平面列表不再区分语境，语境语义由 typed 版本与守卫调用点承接。
    既有调用方与测试行为不变。

    ``spec_dir`` 可为 ``str`` / ``Path``（指向 openspec/changes/<spec>/）。
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


def lint_declared(spec_dir, project_root) -> List[str]:
    """晋升 lint（drafted → ready）：Deliverables 声明形态机械校验。

    不可满足/失效的声明在撰写当下拦截（spec 停留 drafted + error 提示），
    不再等到收工守卫才暴露——守卫判定发生在一次完整实现 run 之后，声明
    形态错误的代价是一轮 run + 打回循环（remove-auto-run-cleanup 目录声明
    死锁事故 2026-09-03）。

    规则（零误拦取向，只拦确定性无效形态）：
    1. 路径含 ``<``/``>`` 模板占位符——守卫的 ``_is_deliverable_path`` 会静默
       跳过该条目，声明形同虚设（fix-admin-run-blocks-mainloop 同族坑）；
    2. ``kind: modify`` 的路径在主树是目录——目录声明与守卫判定形态不匹配
       （守卫按 blob/tree 校验对象，精确到文件的声明才可对账），处方：改为
       目录下确定性锚点文件（如 ``dist/index.html``）。

    lint 自身故障一律 fail-open（返回空清单放行晋升），不因 lint 阻塞流水线。

    Args:
        spec_dir: SPEC 目录（openspec/changes/<spec>/）。
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
        return []
    try:
        entries = _yaml.safe_load("\n".join(block))
    except Exception:
        return []  # yaml 解析失败由守卫的回退语义处理，lint 不重复报
    if not isinstance(entries, list):
        return []

    violations: List[str] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        path = str(e.get("path") or "").strip()
        kind = str(e.get("kind") or "").strip().lower()
        if not path or kind not in _DECLARED_KINDS:
            continue
        if "<" in path or ">" in path:
            violations.append(
                f"[{path}] 含 <...> 模板占位符——守卫会静默跳过该条目，"
                f"声明形同虚设，请改为具体字面路径"
            )
            continue
        if kind != "modify":
            continue
        # 目录声明按字面路径判定（.fenix 归一化已退役，恒等映射自然退化）
        candidates = [path]
        normalized = normalize_check_path(path)
        if normalized != path:
            candidates.append(normalized)
        is_dir = any((project_root / c).is_dir() for c in candidates)
        if is_dir:
            violations.append(
                f"[{path}] 是目录——目录声明无法精确对账（tree ≠ 具体交付物），"
                f"请改为目录下确定性锚点文件（如 dist/index.html）"
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


def lint_tasks_parseable(spec_dir, project_root) -> List[str]:
    """晋升 lint（drafted → ready）：tasks.md 可解析性校验（task-track R2）。

    tasks.md 不存在 → 返回 ``[]``（不拦：fast-track 前置 spec 允许后补）。
    存在 → 以与下游解析器同源的分组正则（见 ``_TASKS_GROUP_RE`` 注释）解析，
    0 个任务分组（含文件为空/无任务行的情形——无可跟踪任务属撰写缺陷，拦截
    早于 run 烧钱）→ 返回含「tasks.md」字样的违规消息；≥1 分组（含点号可选
    双历史格式）→ 不拦。本函数不读 ``project_root``，仅保持与
    ``lint_declared`` 同构签名（统一调用点形态）。

    Returns:
        违规描述清单；空列表 = 通过。读取类异常直接上抛，由调用方
        （engine）的 fail-open 语义兜底。
    """
    spec_dir = Path(spec_dir)
    tasks = spec_dir / "tasks.md"
    if not tasks.exists():
        return []
    text = tasks.read_text(encoding="utf-8")

    group_count = 0
    for line in text.split("\n"):
        if _TASKS_GROUP_RE.match(line):
            group_count += 1

    if group_count > 0:
        return []
    return [
        "tasks.md 存在但未解析出任务分组——分组标题必须为 `## <编号>. <标题>`"
        "（阿拉伯数字编号，点号可选），如 `## 1. Setup`；"
        "当前格式无法被下游解析器跟踪，请修正后重新晋升"
    ]
