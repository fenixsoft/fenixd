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

import json
import logging
import os
import re
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, List

# 模块级 logger（add-declaration-relocation-protocol D1，统一审计留痕入口）。
# 实际绑定在 _LenientLogAdapter 类定义之后设置（见文件下方），此处的中间
# binding 属死赋值（code-review item 98e2c3152572：定义后立即被覆写、中间
# 从未被读），已删除以免同名两处定义造成误导。


class _LenientLogAdapter:
    """轻量 logger 适配层：与 PMEngine.logger 接口一致（tag, msg 两参），
    内部把 tag 拼到消息前缀，恒以零格式参数下发给 stdlib Logger（多参调用
    的 % 插值也在本层完成），避免 stdlib 日志把消息当 format string 解析
    （tag 或消息文本中的字面 % 均会致 TypeError/输出错乱）。

    测试环境不启动 daemon 时 stdlib Logger 的 `warning(tag, msg)` 会触发
    ``"tag" % (msg,)`` → TypeError；生产环境 handler 未连接时不报错。
    """
    def __init__(self, delegate):
        self._delegate = delegate

    def _fmt(self, args):
        if len(args) == 0:
            return "", []
        if len(args) == 1:
            return str(args[0]), []
        msg = f"{args[0]}: {args[1]}"
        rest = args[2:]
        if not rest:
            return msg, []
        # code-review item 5e5c14c19eb9：剩余格式参数由适配层自行插值，恒以
        # 零格式参数下发。若照旧把 rest 交给 delegate 以 msg % args 形态格式
        # 化，拼接后消息文本中的字面 %（如「100% 检查通过」）会被 stdlib
        # logging 当格式符解析（TypeError/输出错乱）——恰是本适配层声称要
        # 规避的形态。插值失败（消息含非法格式形态）降级为 str 拼接，保底不抛。
        try:
            msg = msg % rest
        except (TypeError, ValueError, KeyError):
            msg = f"{msg} | {'; '.join(str(a) for a in rest)}"
        return msg, []

    def info(self, *a, **k):
        msg, args = self._fmt(a)
        self._delegate.info(msg, *args, **k)

    def warning(self, *a, **k):
        msg, args = self._fmt(a)
        self._delegate.warning(msg, *args, **k)

    def error(self, *a, **k):
        msg, args = self._fmt(a)
        self._delegate.error(msg, *args, **k)

    def debug(self, *a, **k):
        msg, args = self._fmt(a)
        self._delegate.debug(msg, *args, **k)


_resolution_logger = _LenientLogAdapter(logging.getLogger("fenixd.deliverables"))

# git show / cat-file 超时（秒）
_GIT_READ_TIMEOUT_SECONDS = 15

# 重定位审计记录类型标识（3.6 凭据登记）
_RELOCATION_AUDIT_TYPE = "relocation"

# 核心交付路径前缀（相对项目根）：实现产物的稳定落点。
_DELIVERABLE_PREFIXES = ("core/", "tests/", ".fenix/", "scripts/")

# 围栏代码块起始/结束（≥3 个 ` 或 ~ 的完整 run，允许跟随语言标识）。捕获完整
# run 而非前三个字符：4+ 反引号围栏只能被不短于它的同字符围栏闭合（CommonMark），
# 只认三字符会让内层 ``` 被误判为闭栏、块边界错位截断（item 575b928f818a）。
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")

# 「路径：」/「路径:」前缀行（中文/英文冒号，前后允许空白与装饰）。
_PATH_LABEL_RE = re.compile(r"^\s*[·•\-*•]?\s*路径\s*[:：]\s*(?P<rest>.+?)\s*$")

# 反引号包裹的单条路径（去除行内其它字符，仅取反引号内 token）。
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")

# 绝对路径 / 通配符 / 目录（以 / 结尾）判定。
_ABSOLUTE_RE = re.compile(r"^/")
_WILDCARD_RE = re.compile(r"[*?]")
_DIRECTORY_RE = re.compile(r"/$")

# ── 语境分类规则表（add-deliverable-extractor-semantics，D1） ───────────────

# 引用语境关键词：出现即视为「既有文件引用」语境（软校验，不参与缺件判定）。
_REFERENCE_KEYWORDS = (
    "实现依据",
    "挂钩点",
    "插入点",
    "真实夹具",
    "上游依赖",
    "现状代码",
    "既有",
    "复用",
    "源自",
    "参考",
)

# 交付语境动词：出现即视为「新建交付物」语境（参与缺件判定）。
_DELIVERABLE_VERBS = ("新增", "新建", "创建", "添加", "交付", "落地", "编写")

# tasks 勾选行：任务清单是交付物声明的第一语义位。宽口径（容忍缩进、*/+ 项目
# 符、大写 X）仅用于语境分类；孤儿判定/任务计数用文件末尾 _TASKS_ITEM_RE 严
# 口径（仅行首 `- [x]`）——两套宽严差异有意、用途不同，勿混用（item
# 6e387df34df1）。
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
    # 去除尾随常见标点（避免从句子里误带出句号/逗号/括号；含全角右闭合
    # 标点，code-review item d633c26ae3ee）
    tok = tok.rstrip(".,;:。，；：)）」』】")
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
            for tok in rest.split():
                # 中文句子通常无空格，切出的 token 会整段尾带全角括注或从句
                # ——在首个全角标点（括注/停顿标点）处截断尾缀，避免伪装成
                # 交付路径（code-review item d633c26ae3ee；rstrip 剥不掉左
                # 括号前挂的括注内容）：「路径：core/api.py（新增）」截在（、
                # 「路径：core/api.py，该文件为新增」截在，。停顿标点截断与
                # _normalize_token 的尾随标点剥离互补——句号/右闭合标点只
                # 挂在 token 尾部由后者剥离，此处负责中缀截断（item
                # ed5bc62b84e9：原字符集只认括注，全角逗号从句无空格可切，
                # 整段伪装成候选路径、守卫误报缺件）
                tok = re.split(r"[（」，、；」』】]", tok, maxsplit=1)[0]
                if tok:
                    cands.append(tok)

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


def _classify_line(line: str, doc_kind: str, in_tasks_header: bool, in_scenario: bool) -> str:
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
    # 去重按 (ctx, path) 分别记账（code-review item f54b4ca2f11a）：旧实现用
    # 单一全局 seen，先出现的语境「赢」并压制另一语境——tasks.md 中同路径的
    # 「实现依据」引用行若先于勾选/新增行出现，该路径**永不进入 deliverables**，
    # 把硬校验交付物静默降级为软审计（正是本模块要防的假成功）。docstring 早已
    # 声明两类「各自去重」，此处对齐语义。
    seen: dict[str, set] = {"deliverables": set(), "references": set()}

    for doc in _iter_spec_documents(root):
        rel = doc.relative_to(root).as_posix() if doc.is_relative_to(root) else doc.name
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
        fence_char = ""  # 当前围栏开栏标记 run（```/~~~~ 等）；空 = 未在围栏内
        in_tasks_header = True  # 第一个 `## ` 标题之前为头部说明段
        in_scenario = False  # 能力 spec 的 Scenario 小节

        for raw_line in text.splitlines():
            # 围栏代码块：整块内所有行均视为显式路径声明，语境在块首按结构性
            # 小节语义重算（item d3391833951c：不沿用块前最近一条已分类行的
            # 关键词语境——「实现依据：`x`」引用行紧邻的围栏路径清单会被整体
            # 降级 references（硬交付物静默软化，假成功方向）；块前无可分类行
            # 时又继承初始档位，tasks 头部说明段围栏块被当硬交付物（误拦方向）。
            # 空行使勾选/关键词规则天然不命中，_classify_line 只剩 Scenario /
            # tasks 头部 / 兜底三条结构规则，与 D1 规则表一致）。
            # 围栏开/关判定先于标题态翻转（code-review item fedc3744144a）：
            # 标题态翻转移入下方非围栏分支——围栏内容里以 # 开头的行（markdown
            # 代码块内 `## Why`、yaml 注释样标题）不参与结构状态机，否则
            # tasks.md 头部说明段围栏块内的 `##` 行会把 in_tasks_header 提前
            # 打为 False，其后围栏块经 _classify_line 落入错误档位，且该状态
            # 在块外持续生效（双向漂移）。围栏分隔行本身不命中任何标题正则，
            # 先判围栏对开/关翻转行为零影响。
            m = _FENCE_RE.match(raw_line)
            if m:
                if not in_fence:
                    # 开栏记完整标记 run，闭栏须同字符且长度不短于开栏
                    # （CommonMark 闭合语义：4+ 反引号围栏不被内层 ```
                    # 错位截断，item 575b928f818a；同字符不互为翻转标记
                    # 对齐 _extract_declared_block，item 820df5cad84b）
                    fence_char = m.group(1)
                    fence_ctx = _classify_line(
                        "", doc_kind, in_tasks_header, in_scenario
                    )
                    in_fence = True
                    continue
                cur = m.group(1)
                if cur[0] == fence_char[0] and len(cur) >= len(fence_char):
                    in_fence = False
                    continue
                # 同字符但更短/异字符的围栏行是块内容而非闭栏（不翻转边界），
                # 落入下方 in_fence 分支按围栏内 token 处理
            if in_fence:
                ctx = fence_ctx
            else:
                if _H2_RE.match(raw_line):
                    in_tasks_header = False
                if _SCENARIO_HEADING_RE.match(raw_line):
                    in_scenario = True
                elif _H2_RE.match(raw_line) or raw_line.startswith("#"):
                    in_scenario = False
                ctx = _classify_line(raw_line, doc_kind, in_tasks_header, in_scenario)

            if in_fence:
                # 代码块内逐 token（按空白/常见分隔符切分）
                tokens = [_normalize_token(t) for t in re.split(r"\s+", raw_line.strip())]
            else:
                tokens = [_normalize_token(t) for t in _candidates_from_line(raw_line)]

            for cand in tokens:
                if not _is_deliverable_path(cand) or cand in seen[ctx]:
                    continue
                seen[ctx].add(cand)
                typed[ctx].append(cand)

    return typed


def extract_declared_entries(spec_dir) -> "list | None":
    """tasks.md ``## Deliverables`` 声明段原始条目（path + kind，保序去重）。

    ``extract_declared`` 与派发处方快照（add-deliverable-declaration-triage
    PR2 2.1）共用的条目级解析：返回过滤后的 ``[{"path": ..., "kind": ...}]``
    列表（kind ∈ new/modify/delete/reference）；无声明段、无有效围栏块、yaml 解析
    失败或全部条目非法 → ``None``。``extract_declared`` 按 kind 归类复用本函数，
    快照按条目级做存在性检查与 basename 匹配（kind 语义不可从归类结果反推）。

    解析逻辑单点在 ``_declared_entries_from_text``（code-review item
    6b203e598e09：本函数读文本后直接委托，消除两份同构拷贝——kind 白名单/过滤
    规则演进漏改一处会导致文件来源与文本来源解析漂移）。
    """
    tasks = Path(spec_dir) / "tasks.md"
    try:
        text = tasks.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    return _declared_entries_from_text(text)


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
    return _typed_from_entries(entries)


# ── 统一声明解析契约（add-declaration-relocation-protocol D1/D3/D4）──────────


def _utcnow_iso() -> str:
    """UTC 时间戳（快照时刻 / 凭据登记 created）。"""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _extract_declared_block(text: str) -> "tuple[List[str] | None, str | None]":
    """抽取 tasks.md 文本 ``## Deliverables`` 段内的 fenced yaml 块行（单点）。

    段边界（``_DECLARED_HEADING_RE`` 定位标题 + ``_H2_RE`` 截断）与围栏块切换
    （``_FENCE_RE``）的唯一实现——条目解析（``_declared_entries_from_text``
    委托链）与 ``lint_declared`` 共用（code-review item aa9e700d8155：原两处各持
    一份扫描拷贝，fence 语法或段边界规则单点演进（如 ``~~~`` 支持、标题别名）会
    解析漂移——lint 放行的块下游解析为 None 静默回退正则猜测，恰是规则 0 要消灭
    的形态）。

    围栏语义（code-review item 8741b4b84c82）：只取节内**首个**围栏作为声明块
    （开栏即记标记字符、同字符才闭栏、闭栏即取完）——节内后续示例/说明性围栏
    不再与声明 yaml 拼接（拼接会让 safe_load 失败静默降级正则猜测，或把示例
    条目误并进声明）；``` 与 ~~~ 不互为翻转标记（CommonMark 同字符闭合语义，
    防声明块内异字符围栏行错位块边界）。

    Args:
        text: tasks.md 全文（None 容错为空文本，沿用既有条目解析的入参语义）。

    Returns:
        ``(block_lines, 诊断)``：无 ``## Deliverables`` 标题 → ``(None, None)``
        （存量 spec，非形态违规）；有标题但段内无 fenced 块 → ``(None, 诊断)``
        （规则 0 违规文案，仅 lint 消费；条目解析按 ``block_lines`` 为 None 静默
        回退正则猜测）；否则 ``(块行列表, None)``。yaml 解析与条目过滤不在本函数
        职责内——lint 需对语法错/非列表产出专属诊断，条目解析对两者静默回退
        ``None``，消费语义不同故不下沉。
    """
    lines = (text or "").splitlines()
    start = None
    for i, line in enumerate(lines):
        if _DECLARED_HEADING_RE.match(line):
            start = i + 1
            break
    if start is None:
        return None, None

    block: List[str] = []
    fence_char = ""  # 当前围栏的开栏标记 run（≥3 个 ` 或 ~）；空串 = 尚未进入围栏
    for line in lines[start:]:
        # 围栏开/关判定先于 _H2_RE 标题截断（fence-first，对齐同文件
        # extract_paths_typed 的同型修复 code-review item fedc3744144a，本次
        # item b2f75d10dde8）：开栏中以 ## 开头的行（yaml 注释、粘贴进来的
        # 小节标题）是块内容而非节边界——标题判定先行会在此提前截断声明块、
        # 块内后续条目被静默丢弃（守卫按缺件对账或收缩防护把仍在的条目误判
        # removed）；未开栏时 ## 行才终止段，闭栏仍只认同字符（「闭栏即取完」
        # 语义不变）。
        m = _FENCE_RE.match(line)
        if m:
            if not fence_char:
                fence_char = m.group(1)  # 开栏：记录完整标记 run
                continue
            cur = m.group(1)
            if cur[0] == fence_char[0] and len(cur) >= len(fence_char):
                break  # 闭栏即取完——声明块只取节内首个围栏，后续围栏不并入
            block.append(line)  # 同字符更短/异字符围栏行是块内容而非闭栏
            continue
        if fence_char:
            block.append(line)
        elif _H2_RE.match(line):
            break
    if not block:
        return None, (
            "Deliverables 声明段存在但未解析出 fenced yaml 块——声明条目必须写在"
            "```yaml 围栏内（每条 `- path: <具体文件>` + `  kind: <new|modify|"
            "delete|reference>` 两行），平铺的 Markdown 列表或缩进子项不会被"
            "下游解析器识别，等同未声明（守卫会回退正则语境猜测）；"
            "请改为 fenced yaml 块后重试晋升"
        )
    return block, None


def _is_filtered_declaration_path(path: str) -> bool:
    """声明路径三类确定性无效形态判定（绝对路径/通配符/尾斜杠目录，单点谓词）。

    ``_declared_entries_from_text`` 对三类形态逐条静默过滤（全部条目被滤空即
    返回 ``None``、守卫回退正则语境猜测）；``lint_declared`` 必须以同一谓词在
    晋升当下拒绝——否则 lint 绿灯与解析器 ``None`` 的落差令声明静默退化为
    语境猜测（code-review item f109a12eefa3：如 ``kind: new, path: scripts/``
    主树目录存在即过存在性检查放行，下游解析器把它滤空、声明机制整体失效）。
    """
    return bool(
        _ABSOLUTE_RE.match(path)
        or _WILDCARD_RE.search(path)
        or _DIRECTORY_RE.search(path)
    )


def _declared_entries_from_text(text: str) -> "list | None":
    """从 tasks.md 文本解析声明段条目（path + kind，保序去重）。

    与 ``extract_declared_entries`` 同构的解析逻辑，但直接吃文本而非文件——
    供统一声明解析入口（``resolve_effective_declaration``）从分支/worktree/主树
    三种来源解析共用。无声明段、无有效围栏块、yaml 解析失败或全部条目非法
    → ``None``（与 ``extract_declared_entries`` 返回语义一致）。

    段边界/围栏块扫描单点复用 ``_extract_declared_block``（``lint_declared``
    同源）；诊断由 lint 消费，本链路对无标题/无块一律静默回退 ``None``（既有
    语义不变）。
    """
    import yaml as _yaml

    block, _ = _extract_declared_block(text)
    if not block:
        return None
    try:
        entries_obj = _yaml.safe_load("\n".join(block))
    except Exception:
        return None
    if not isinstance(entries_obj, list):
        return None

    out: List[dict] = []
    for e in entries_obj:
        if not isinstance(e, dict):
            continue
        path = str(e.get("path") or "").strip()
        kind = str(e.get("kind") or "").strip().lower()
        if not path or kind not in _DECLARED_KINDS:
            continue
        if _is_filtered_declaration_path(path):
            continue
        if any(o["path"] == path for o in out):
            continue
        out.append({"path": path, "kind": kind})
    return out if out else None


def _typed_from_entries(entries) -> dict:
    """按 kind 归类条目为 deliverables/references 两桶（保序去重）。

    与 ``extract_declared`` 的归类逻辑同源：new/modify/delete → deliverables
    （硬校验，delete 为反判）；reference → references（软校验）。
    """
    typed: dict = {"deliverables": [], "references": []}
    for e in entries or []:
        path, kind = e["path"], e["kind"]
        if path in typed["deliverables"] or path in typed["references"]:
            continue
        key = "deliverables" if kind in ("new", "modify", "delete") else "references"
        typed[key].append(path)
    return typed


def _git_show_tasks_text(branch: str, spec_name: str, project_root) -> "str | None":
    """只读 ``git show <branch>:spec/changes/<spec>/tasks.md``（D1 分支来源）。

    fail-safe：非零退出（路径不存在）/超时/异常 → None（分支版本不可用，
    调用方回退下一来源）。纯对象库读取，不触发 LLM / 测试 / 网络。
    """
    try:
        proc = subprocess.run(
            [
                "git",
                "-C",
                str(project_root),
                "show",
                f"{branch}:spec/changes/{spec_name}/tasks.md",
            ],
            capture_output=True,
            text=True,
            timeout=_GIT_READ_TIMEOUT_SECONDS,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        _resolution_logger.warning(
            "deliverables",
            f"resolve_effective_declaration git show 失败（回退下一来源）"
            f"'{spec_name}'@{branch}: {e}",
        )
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def _read_file_text(path) -> "str | None":
    """文件读取（worktree/主树来源），失败返回 None 并留痕。"""
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        _resolution_logger.warning(
            "deliverables",
            f"resolve_effective_declaration 文件读取失败（回退下一来源）{path}: {e}",
        )
        return None


def resolve_effective_declaration(
    spec_name, *, branch=None, worktree_path=None, project_root=None
) -> dict:
    """统一声明解析入口（add-declaration-relocation-protocol D1）。

    所有消费方（收工守卫、裁决流水线、晋升 lint、提示词组装、fast-track 快照、
    重定位）MUST 经本入口取「某 spec 在当下适用的交付物声明集合」——杜绝各消费点
    各自拼接 ``project_root/spec/changes/<spec>/`` 直读主树的错层（事故实证：
    fix-relint-redispatch-legacy 主树声明陈旧致守卫两轮空转）。

    解析优先序（D1）：**worktree 内 tasks.md > ``git show <branch>:...tasks.md``
    > 主树 tasks.md**。分层回退 fail-safe：worktree 文件不存在/读取失败/解析异常
    （无声明段）→ 回退分支版本；分支 git show 非零退出/超时/路径不存在 → 回退主树；
    两处均不可用 → 返回空结果（等价「无声明段」，守卫跳过）。回退去向与原因经
    logger 审计留痕。纯文件/对象库读取，MUST NOT 触发 LLM / 测试 / 网络（成本契约，
    见 ``_git_show_tasks_text`` / ``_read_file_text``）。

    Args:
        spec_name: spec 名（spec/changes/<spec>/）。
        branch: 实现分支名（可选；git show 基线）。
        worktree_path: worktree 根路径（可选；worktree 内文件优先）。
        project_root: 项目根（主树；可选，缺失时主树回退不可用）。

    Returns:
        与 ``extract_declared`` 同构的结果（保序去重），另附来源与条目级信息::

            {
              "deliverables": [...],   # kind ∈ new/modify/delete（硬校验）
              "references": [...],     # kind == reference（软校验）
              "entries": [...],        # 条目级 [{"path", "kind"}]（去重保序）
              "source": "worktree"|"branch"|"main"|None,  # 生效来源（None=均不可用）
              "spec_dir": str|None,    # 生效声明所在目录（改写目标；worktree 优先，
                                       # 分支版本无落盘位置时为 None——改写走
                                       # worktree 挂载提交路径，见 D2）
            }
    """
    # 1) worktree 内文件
    if worktree_path:
        try:
            wt_tasks = Path(worktree_path) / "spec" / "changes" / spec_name / "tasks.md"
        except (OSError, TypeError, ValueError):
            # worktree_path 不可用（非路径形态/非法对象）→ 回退下一来源
            wt_tasks = None
        if wt_tasks is not None and wt_tasks.is_file():
            text = _read_file_text(wt_tasks)
            if text is not None:
                entries = _declared_entries_from_text(text)
                if entries is not None:
                    return {
                        **_typed_from_entries(entries),
                        "entries": entries,
                        "source": "worktree",
                        "spec_dir": str(wt_tasks.parent),
                    }
    # 2) 分支版本（git show，只读对象库）
    if branch and project_root:
        text = _git_show_tasks_text(branch, spec_name, project_root)
        if text is not None:
            entries = _declared_entries_from_text(text)
            if entries is not None:
                return {
                    **_typed_from_entries(entries),
                    "entries": entries,
                    "source": "branch",
                    "spec_dir": None,
                }
    # 3) 主树文件
    if project_root:
        main_spec_dir = Path(project_root) / "spec" / "changes" / spec_name
        main_tasks = main_spec_dir / "tasks.md"
        if main_tasks.is_file():
            text = _read_file_text(main_tasks)
            if text is not None:
                entries = _declared_entries_from_text(text)
                if entries is not None:
                    return {
                        **_typed_from_entries(entries),
                        "entries": entries,
                        "source": "main",
                        "spec_dir": str(main_spec_dir),
                    }
                # 主树文件存在但无声明段：返回空结果 + source 标记（消费方按
                # 「无声明段」语义处理——守卫回退 extract_paths_typed，spec_dir
                # 供回退读取目标定位）。
                return {
                    "deliverables": [],
                    "references": [],
                    "entries": [],
                    "source": "main",
                    "spec_dir": str(main_spec_dir),
                }
    # 4) 两处均不可用 / 均无声明段 → 空结果（消费方按「无声明段」语义处理）
    return {
        "deliverables": [],
        "references": [],
        "entries": [],
        "source": None,
        "spec_dir": None,
    }


def resolve_writeback_target(
    spec_name, *, branch=None, worktree_path=None, project_root=None
) -> dict:
    """声明修正**写回层**判定（fix-relocation-writeback-layer D1，Task 1.1）。

    判据 = **写入层是否等于守卫实际读到的那一层**（``resolve_effective_declaration``
    返回的 ``source``，同源原则）——修正被执行 ⇔ 下一次守卫读取能看到修正：

    - ``source == "worktree"``：``writable=True``，落点 = worktree 内 spec 目录，
      提交根 = 该 worktree（提交落实现分支）；
    - ``source == "main"``：``writable=True``，落点 = **主树** spec 目录、提交根 =
      ``project_root``——前两层均未命中时守卫读取基准**就是主树**，就地写入即同源，
      不构成错层（禁止它会误伤 2026-09-15 merge-back 死锁修复的既有主树就地软化路径）；
    - ``source == "branch"``（``spec_dir is None``，声明只存在于分支对象库、无落盘
      位置）：``writable=False``——**这才是事故态**（写主树、守卫读分支）；
    - ``source is None``（两处均不可用）：``writable=False``。

    Args:
        spec_name: spec 名。
        branch: 实现分支名（可选；解析基准之一）。
        worktree_path: worktree 根路径（可选；最高优先层）。
        project_root: 主树项目根（可选）。

    Returns:
        ``{"writable": bool, "spec_dir": str|None, "source": str|None,
        "commit_root": str|None, "declaration": dict}``。``commit_root`` 为修正落盘后
        提交所应使用的 git 仓库根（worktree 命中 → 该 worktree；main 命中 →
        ``project_root``；不可写 → None）；``declaration`` 为底层解析结果（避免调用方
        二次解析）。
    """
    resolved = resolve_effective_declaration(
        spec_name,
        branch=branch,
        worktree_path=worktree_path,
        project_root=project_root,
    )
    source = resolved.get("source")
    spec_dir = resolved.get("spec_dir")
    # main 命中层的提交根即主树（project_root 缺失时无提交根基可言——但 source
    # == "main" 蕴含主树读取成功，project_root 必然可用）。
    commit_root = None
    if source == "worktree" and spec_dir:
        commit_root = str(worktree_path) if worktree_path else None
    elif source == "main" and spec_dir:
        commit_root = str(project_root) if project_root else None
    writable = bool(
        spec_dir and source in ("worktree", "main") and commit_root
    )
    return {
        "writable": writable,
        "spec_dir": spec_dir if writable else None,
        "source": source,
        "commit_root": commit_root if writable else None,
        "declaration": resolved,
    }


def verify_correction_readback(
    spec_name, corrected_path, *, branch=None, worktree_path=None,
    project_root=None, kind=None,
) -> bool:
    """修正后读取一致性复检（fix-relocation-writeback-layer D3，Task 3.1）。

    以**守卫读取基准**（``resolve_effective_declaration``，优先序 worktree >
    branch > main）复读：被修正的旧路径 ``corrected_path`` 不再以原 ``kind``
    出现在生效声明条目中即视为生效。核心不变量：**修正被执行 ⇔ 下一次守卫读取
    能看到修正**；读回仍是旧路径（写读错层，add-code-review-auto-fix 事故根因）
    → 返回 False，调用方 MUST NOT 判为修正成功。

    Fail-safe 取向：解析来源为 ``None``（两处均不可用）→ 返回 False（无读取基准
    可证修正生效，不静默销账）。

    Args:
        spec_name: spec 名。
        corrected_path: 被修正的旧路径（typo 元素 / 软化条目）。
        kind: 可选；限定「原 kind」比对（None = 任何 kind 命中即算未修正）。
        branch / worktree_path / project_root: 解析上下文（与守卫同参）。

    Returns:
        True 表示旧路径已不在生效声明中（复检通过）；False 表示仍读到旧路径 /
        无读取基准。
    """
    resolved = resolve_effective_declaration(
        spec_name,
        branch=branch,
        worktree_path=worktree_path,
        project_root=project_root,
    )
    if resolved.get("source") is None:
        return False
    for e in resolved.get("entries") or []:
        if not isinstance(e, dict) or e.get("path") != corrected_path:
            continue
        if kind is None or e.get("kind") == kind:
            return False
    return True


def _atomic_write_text(target: Path, content: str) -> None:
    """mkstemp 唯一临时文件 + fsync + ``os.replace`` 原子写（薄委托 fs_utils 收口版）。

    code-review item e42aabcf003a：本模块曾自持一份与 ``core/fs_utils.py``
    收口版双向漂移的私有实现（继承既有权限 + 目录 fsync），收口为薄委托
    ``core.fs_utils.atomic_write_text``（保留函数名以防外部/测试引用），
    mkstemp + fsync + os.replace 纪律（含目录 fsync，item f19b8ef57ce6）
    单点维护于 fs_utils。历史动机留档：临时文件名随机唯一（同 spec 并发写
    不再交错污染，item a8cdbacd2897）、进程中途崩溃/被杀不留下截断的目标
    文件（item 5b69a4a517cd——tasks.md 声明段改写曾用 ``write_text`` 直接
    覆盖，中断即丢声明段、守卫回退正则语境猜测）。

    ``inherit_existing_mode=True``：替换既有文件时继承其权限（item
    80a6ae8b6492——跨用户只读巡检/备份不被 mkstemp 0600 静默收窄）。
    与旧私有版的唯一行为差异：**新**文件从 mkstemp 缺省 0600 放宽为 0644
    （与同一动机一致，避免新落盘产物被调用方「读取失败回退/降级」分支掩盖
    成解析回退）。写失败清理临时文件后原样上抛，由调用方按各自 fail-safe
    语义处置。
    """
    from core.fs_utils import atomic_write_text

    atomic_write_text(target, content, inherit_existing_mode=True)


def snapshot_declaration_baseline(spec_name, run_id, project_root) -> "dict | None":
    """派发时快照主树声明条目到实现 Agent 不可触及的位置（D3）。

    写入 ``.fenix/verify-progress/<spec>/declaration-baseline.json``（原子：
    写临时文件 + ``os.replace``）。快照内容：当前**主树** tasks.md 声明条目
    （path + kind）、快照时刻、触发 run id。该位置在 worktree 之外——实现 Agent
    路径不写入，是收缩防护（D3）的独立参照系。

    写入异常（磁盘/权限）仅 WARNING 不阻塞派发（收缩防护该轮降级保守，见
    ``check_declaration_shrinkage`` 与守卫的降级语义）。

    Args:
        spec_name: spec 名。
        run_id: 触发 run id。
        project_root: 项目根（定位主树 spec 目录与 .fenix/verify-progress）。

    Returns:
        快照 dict（含 entries）；写入失败返回 None。
    """
    root = Path(project_root)
    spec_dir = root / "spec" / "changes" / spec_name
    try:
        entries = extract_declared_entries(spec_dir) or []
    except Exception as e:
        _resolution_logger.warning(
            "deliverables",
            f"基线快照声明解析失败 '{spec_name}'（不落快照，收缩防护该轮降级）: {e}",
        )
        return None
    snap = {
        "spec": spec_name,
        "snapshot_at": _utcnow_iso(),
        "run_id": run_id or "",
        "entries": entries,
    }
    target = root / ".fenix" / "verify-progress" / spec_name / "declaration-baseline.json"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # mkstemp 唯一临时文件 + os.replace 原子落盘（_atomic_write_text，
        # item a8cdbacd2897：固定名 .tmp 在并发快照下内容可能交错污染基线）
        _atomic_write_text(target, json.dumps(snap, ensure_ascii=False, indent=2))
    except OSError as e:
        _resolution_logger.warning(
            "deliverables",
            f"基线快照写入失败 '{spec_name}'（仅 WARNING 不阻塞派发）: {e}",
        )
        return None
    return snap


def load_declaration_baseline(spec_name, project_root) -> "dict | None":
    """读取基线快照（D3 读取侧）；缺失/损坏/读取失败 → None（守卫降级保守）。"""
    target = (
        Path(project_root) / ".fenix" / "verify-progress" / spec_name / "declaration-baseline.json"
    )
    if not target.is_file():
        return None
    try:
        with target.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        _resolution_logger.warning(
            "deliverables",
            f"基线快照读取失败 '{spec_name}'（收缩防护降级保守）: {e}",
        )
        return None
    return data if isinstance(data, dict) else None


def _git_c_env() -> dict:
    """git 子进程环境：合并 ``os.environ`` 并强制 ``LC_ALL=C``。

    消除「路径确定不存在」三态判别对 stderr 英文文案（``does not exist``）的
    本地化依赖（code-review item 77767180a566：LC_MESSAGES/LANG 非英文环境下
    git gettext 输出本地化文案，文案匹配恒失配、确定性不存在被误判为 git
    不可用）。合并而非整体替换，保留调用方的 PATH 等既有环境。
    """
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    return env


# 「确定不存在」stderr 文案容忍集合（小写匹配，code-review item 03edd97d523c）。
# 单点收敛避免对单一措辞的脆弱耦合：当前主形态为
# ``fatal: path 'X' does not exist in 'Y'``，补充等义改写形态，git 小版本
# 改写措辞时「确定性不存在」不整体退化为 None。只收「查询对象缺失」语义的
# 文案；``not a git repository``（非仓库）、``invalid object name``/
# ``unknown revision``（分支或对象名无效）**不**纳入——分支名无效时对象存在性
# 无从谈起，维持归 None 由调用方保守处置，fail-safe 方向不因集合放宽而翻转。
_GIT_OBJECT_ABSENT_STDERR_MARKERS = (
    "does not exist",  # path 'X' does not exist in 'Y'（当前主形态）
    "not found in",  # path 'X' not found in 'Y'（可能改写形态）
    "missing from",  # 'X' missing from tree 'Y'（可能改写形态）
    "no such path",  # no such path 'X' in 'Y'（可能改写形态）
)


def _git_object_exists_on_branch(branch, path, project_root) -> "bool | None":
    """``git cat-file -e <branch>:<path>`` O(1) 探测（纯对象库，零成本）。

    Returns:
        True = 确定存在；False = git 成功执行且确定不存在（退出码非零且
        stderr 命中「确定不存在」文案集合
        ``_GIT_OBJECT_ABSENT_STDERR_MARKERS`` 之一）；None = git 不可用
        （超时/无法执行/非仓库/分支对象名无效）。退出码 128 同时覆盖「路径
        不存在」与「非仓库」，单看 returncode 无法区分（code-review item
        d5da82df85c3），故按 stderr 形态三态判别；无法识别的失败一律归
        不可用（None），由调用方按各自 fail-safe 语义处置。
    """
    try:
        r = subprocess.run(
            ["git", "-C", str(project_root), "cat-file", "-e", f"{branch}:{path}"],
            # stdout 丢弃；stderr 留管道供 128 形态判别（item d5da82df85c3）
            # ——item feccb157c1d5 的全 DEVNULL 免管道优化在「判不存在」须
            # 排除 git 不可用的正确性要求前让位。
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            # LC_ALL=C 固化英文文案，stderr 形态判别不受运行环境本地化影响
            # （item 77767180a566，与 worktree_manager 既有 LC_ALL=C 手法同源）
            env=_git_c_env(),
            timeout=_GIT_READ_TIMEOUT_SECONDS,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if r.returncode == 0:
        return True
    stderr_text = (r.stderr or b"").decode("utf-8", "replace").lower()
    if any(m in stderr_text for m in _GIT_OBJECT_ABSENT_STDERR_MARKERS):
        return False
    return None


def _declared_satisfied_on_branch(path, kind, branch, project_root) -> bool:
    """分支 HEAD 是否已满足声明条目的原 kind 达成要求（D3 收缩判定步骤 2）。

    new/modify → blob/tree 存在；delete → blob/tree 不存在（反判）。
    branch 缺失/git 异常 → False（fail-safe 判未满足 → 可能判 removed；
    保守取向——缺件处置有终审/人工兜底，不静默放行）。
    delete 反判仅在「确定不存在」（exists is False）时算满足：git 不可用
    （探测返回 None）显式判未满足，兑现上一行的保守承诺（item
    d5da82df85c3——旧 ``not exists`` 会把 None 反成「已满足」假成功）。
    """
    if not branch or not path:
        return False
    exists = _git_object_exists_on_branch(branch, path, project_root)
    if kind == "delete":
        return exists is False  # None（git 不可用）→ 判未满足（fail-safe）
    return bool(exists)


def relocation_credential_target(project_root, path) -> "str | None":
    """旧路径在 dispute 审计流中的**替代路径**（fix-relocation-writeback-layer D4，Task 4.1）。

    与 ``_has_relocation_credential`` 同源同形态读 ``.fenix/dispute_audits.jsonl``
    （跨 run 持久），但返回凭据携带的替代路径而非布尔值——守卫据其完成「替代路径
    在实现分支 HEAD 存在」的核销前落地校验（布尔判定不足以完成该校验，防空洞核销）。

    凭据形态（两种，任一命中即取其替代路径）：
    1. ``type == "relocation"`` 且 ``old_path`` 等于该路径 → 取 ``new_path``；
    2. judge ``typo`` 裁决在册（``verdicts`` 中 ``element == path`` 且
       ``verdict == "typo"``）→ 取 ``actual_path``。

    读取失败/缺失/凭据替代路径为空 → None（fail-safe，不误核销）。

    Args:
        project_root: 项目根（审计流读取基准）。
        path: 旧路径。

    Returns:
        替代路径字符串；无凭据或无替代路径时 None。
    """
    try:
        from core.admin_store import DisputeAuditStore

        return _relocation_target_in_records(
            DisputeAuditStore(project_root).read_all(), path
        )
    except Exception:
        return None


def _relocation_target_in_records(records, path) -> "str | None":
    """在已读入的审计记录列表中查旧路径的重定位替代路径（判定核心，无 IO）。

    凭据形态与 ``relocation_credential_target`` 文档一致（两形态任一命中即取其
    替代路径）。单点供两类消费复用：现读现判（``relocation_credential_target``）
    与守卫批量豁免（``check_declaration_shrinkage`` 预读一次审计流后逐路径
    复用——append-only 审计流跨 run 持久增长，N 个基线路径 × 2 判定各自现读
    即 2N 次全量读，code-review item 4d7ef1c7380b），杜绝两条判定路径漂移。

    Args:
        records: ``DisputeAuditStore.read_all()`` 返回的记录列表（或 None）。
        path: 旧路径。

    Returns:
        替代路径字符串；无凭据或无替代路径时 None。
    """
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        if rec.get("type") == _RELOCATION_AUDIT_TYPE and rec.get("old_path") == path:
            target = rec.get("new_path")
            if target:
                return str(target)
        # typo 裁决改写在册：judge 给出 actual_path 的修正即「旧路径 → 替代
        # 路径」的有据改写（审计流已落 diff），收缩防护视同重定位凭据
        for v in rec.get("verdicts") or []:
            if (
                isinstance(v, dict)
                and v.get("element") == path
                and v.get("verdict") == "typo"
                and v.get("actual_path")
            ):
                return str(v["actual_path"])
    return None


def _has_relocation_credential(project_root, path, records=None) -> bool:
    """旧路径在 dispute 审计流是否已有重定位凭据（D3 豁免条款 1）。

    凭据形态见 ``relocation_credential_target``（同源读同一审计流）：
    1. ``type == "relocation"`` 且 ``old_path`` 等于该路径（3.6 凭据登记 /
       3.2-3.4 机械重定位改写随审计流落册）；
    2. judge ``typo`` 裁决在册（``verdicts`` 数组中 ``element == path`` 且
       ``verdict == "typo"`` 且带 ``actual_path``）——typo 改写即声明路径
       修正（旧路径 → actual_path），视同重定位凭据（4.3 重定位接入裁决）。
    两种形态任一命中即豁免。审计流跨 run 持久——上一轮重定位后本轮未
    merge-back，豁免判定仍可命中。读取失败/缺失 → False（fail-safe，不误豁免）。

    实现委托 ``relocation_credential_target``（fix-relocation-writeback-layer
    Task 4.1）：布尔判定与「替代路径可取得」同源，杜绝两条读取路径各自漂移。

    Args:
        project_root: 项目根（审计流读取基准；``records`` 传入时不读）。
        path: 旧路径。
        records: 预读的审计记录列表（``DisputeAuditStore.read_all()`` 结果）。
            传入时跳过审计流读取直接在记录上判定（收缩防护批量豁免单次读
            复用，item 4d7ef1c7380b）；缺省 None 即现读（行为不变）。
    """
    if records is None:
        return relocation_credential_target(project_root, path) is not None
    try:
        return _relocation_target_in_records(records, path) is not None
    except Exception:
        return False


def _has_soften_audit(project_root, path, records=None) -> bool:
    """该路径在审计流是否有合法软化（kind → reference）记录（D3 豁免条款 2）。

    软化形态：DisputeAuditStore 记录的 verdicts 数组中含 element == path 且
    verdict == "reference" 的裁决（法官 reference 软化 / guard-preclassify
    机械软化均落此形态）。读取失败/缺失 → False。

    Args:
        project_root: 项目根（审计流读取基准；``records`` 传入时不读）。
        path: 待判路径。
        records: 预读的审计记录列表（同 ``_has_relocation_credential``，
            item 4d7ef1c7380b 单次读复用）；缺省 None 即现读（行为不变）。
    """
    try:
        if records is None:
            from core.admin_store import DisputeAuditStore

            records = DisputeAuditStore(project_root).read_all()
        for rec in records:
            if not isinstance(rec, dict):
                continue
            for v in rec.get("verdicts") or []:
                if (
                    isinstance(v, dict)
                    and v.get("element") == path
                    and v.get("verdict") == "reference"
                ):
                    return True
    except Exception:
        return False
    return False


def check_declaration_shrinkage(
    baseline, effective, effective_entries, branch, project_root
) -> list:
    """收缩防护判定（D3）：基线路径在生效声明中被「无声剔除」→ removed 违规。

    对基线每条（path, kind）判定（``kind == "reference"`` 的基线条目恒跳过
    ——软校验无硬闸可绕，不参与收缩硬判，item 1f56ff2ff4f2）：
      - 生效声明对基线路径**不再以原有 kind 硬校验**——条目被删除（不在
        effective_entries 中）、或 kind 被改写为 ``reference``（移入软校验组）、
        或改写为其他不满足原有语义的 kind（如 modify → delete / new）；
      - 且该路径在实现分支 HEAD **不满足原有 kind 要求**（modify/new 缺失、
        delete 仍存在）——若分支上已满足原 kind（交付物已落地），剔除的是过时
        声明而非绕门，不判违规；
      - 且无合法豁免：该路径有**重定位凭据**在册（DisputeAuditStore 中
        ``type == "relocation"`` 且 old_path 匹配）或**软化审计**在册（裁决
        reference）→ 不计入违规。
    三者同时成立 → 返回 ``{"path", "kind", "violation": "removed"}``。

    基线不可用（None/缺 entries）→ 返回 []（守卫该轮降级保守，不因缺基线
    误伤正常轮次——审计留痕由守卫负责）。

    Args:
        baseline: ``load_declaration_baseline`` 返回的快照 dict（或 None）。
        effective: 生效声明 typed dict（{"deliverables": [...], "references": [...]}）。
            注（code-review item 8684d6381442）：本函数当前只消费条目级的
            ``effective_entries``（含 kind，可表达 bucket 降级），typed dict
            保留在签名内仅为调用点稳定（branch_guard 已解析出该结构）；
            判定不读它的两个 bucket。如需按 bucket 语义细分，可在此消费。
        effective_entries: 生效声明条目级 [{"path", "kind"}]。
        branch: 实现分支名（分支 HEAD 满足性判定基准）。
        project_root: 项目根（凭据/软化审计读取基准）。

    Returns:
        removed 违规条目列表（保序）；无违规返回 []。
    """
    if not isinstance(baseline, dict):
        return []
    base_entries = baseline.get("entries")
    if not isinstance(base_entries, list) or not base_entries:
        return []
    eff_by_path = {
        e["path"]: e["kind"]
        for e in (effective_entries or [])
        if isinstance(e, dict) and e.get("path")
    }
    violations: list = []
    # 审计流单次全量读入，复用于全部基线路径的豁免判定（重定位凭据 + 软化
    # 审计）：审计 jsonl append-only 跨 run 持久增长，逐路径逐判定各自现读
    # 即 2N 次全量 IO（code-review item 4d7ef1c7380b）。读取失败 → 空列表
    # （fail-safe 与两个判定函数各自的现读失败语义一致：不误豁免）。
    try:
        from core.admin_store import DisputeAuditStore

        audit_records = DisputeAuditStore(project_root).read_all()
    except Exception:
        audit_records = []
    for be in base_entries:
        if not isinstance(be, dict):
            continue
        path = str(be.get("path") or "").strip()
        kind = str(be.get("kind") or "").strip().lower()
        if not path or kind not in _DECLARED_KINDS:
            continue
        # kind=reference 是软校验条目（仅审计留痕）：守卫对 references 缺失只发
        # 「deliverable-reference-missing」软告警、无硬闸可绕，其被剔除/改写属
        # 文档级维护而非「绕门」，不参与收缩硬判（code-review item 1f56ff2ff4f2
        # ——gitignored 运行时路径在分支 HEAD 恒不存在，清理过时 reference 声明
        # 会被误判 removed 走缺件处置）。new/modify/delete 的硬判不削弱。
        if kind == "reference":
            continue
        # 1) 生效声明仍以原 kind 硬校验该路径 → 未剔除
        if eff_by_path.get(path) == kind:
            continue
        # 2) 分支 HEAD 已满足原 kind 要求 → 剔除的是过时声明（交付物已落地）
        if _declared_satisfied_on_branch(path, kind, branch, project_root):
            continue
        # 3) 合法豁免：重定位凭据 / 软化审计在册 → 不计入（审计记录已预读，
        # 见上方单次读入注释）
        if _has_relocation_credential(
            project_root, path, audit_records
        ) or _has_soften_audit(project_root, path, audit_records):
            continue
        violations.append({"path": path, "kind": kind, "violation": "removed"})
    return violations


def is_stale_declaration(entry, project_root) -> bool:
    """陈旧声明确定性信号（D4）：仅 ``kind == "modify"`` 且路径在主树 HEAD 不存在。

    ``new`` 恒 False（基线期望本就是不存在，未落地 new 缺件走既有缺件处置与
    收缩防护，MUST NOT 被强制转入重定位通道）；``delete``/``reference`` 恒 False
    （反判存在性 / 软校验不参与陈旧判定）。零语义推断——只认「主树 HEAD 无该路径」
    这一确定性事实（参考 ``classify_unsatisfiable`` 的排除形态处理）。

    Args:
        entry: 声明条目 dict（含 path/kind）。
        project_root: 项目根（主树基准）。

    Returns:
        命中陈旧信号返回 True；new/delete/reference/缺字段恒 False；仅 git 不可用
        （超时/无法执行/非仓库）时回退文件系统存在性判定。
    """
    if not isinstance(entry, dict):
        return False
    path = str(entry.get("path") or "").strip()
    kind = str(entry.get("kind") or "").strip().lower()
    if kind != "modify" or not path:
        return False
    # 主树 HEAD 存在性：复用 _git_object_exists_on_branch("HEAD", ...) 三态
    # 判别（True/False/None 恰映射「非陈旧/确定性陈旧/回退文件系统」三分支，
    # item 8d2c1a78fe92）。仅 git 不可用（超时/无法执行/非仓库）才回退文件
    # 系统存在性的取向不变（item 0a451454809b）；item d5da82df85c3 的「退出
    # 码 128 须按 stderr 形态区分非仓库与路径不存在」判别单点在助手内。
    exists = _git_object_exists_on_branch("HEAD", path, project_root)
    if exists is not None:
        return exists is False  # True=HEAD 存在→非陈旧；False=HEAD 无该路径→陈旧
    # git 判定不可用（超时/无法执行/非仓库）：回退文件系统存在性（fail-safe）
    try:
        return not (Path(project_root) / path).exists()
    except OSError:
        # 判定不可用且无法证明缺失 → 视为存在（不误判陈旧）
        return False


def relocate_declared_path(effective_spec_dir, old_path, new_path) -> dict:
    """重定位改写（3.2）：生效声明中旧路径确定性替换为替代路径（kind 保持）。

    复用 ``replace_declared_path`` 的文本改写语义（逐行精确替换、同名去重、
    保留注释/顺序、diff 最小）。``effective_spec_dir`` MUST 为**生效声明所在位置**
    （worktree 内 spec 目录优先；其次分支版本落盘位置），MUST NOT 传主树 spec
    目录——改写写生效声明，由 merge-back 携带分支提交对齐主树（D2）。

    改写失败（无声明段 / 无条目匹配 / 并发漂移）上抛，由调用方 fail-safe 处置
    （等价转既有缺件处置，见 3.5）。

    Returns:
        ``replace_declared_path`` 同构：{"element", "actual_path", "before", "after"}。
    """
    return replace_declared_path(effective_spec_dir, old_path, new_path)


def register_relocation_credential(
    spec_name,
    old_path,
    new_path,
    source,
    run_id,
    project_root,
    *,
    branch=None,
    verdict=None,
    evidence=None,
) -> "dict | None":
    """凭据登记（3.6）：生效声明已无该条目时，**不经文本替换**落册重定位凭据。

    当实现方已先行对齐生效声明（旧路径条目已不在声明段，机械文本替换无从执行），
    且凭据三要素齐备（旧路径基线不存在 + 替代路径在实现分支 HEAD 存在 + 来源标注）
    时，以本函数把重定位记录写入 dispute 审计流（``.fenix/dispute_audits.jsonl``，
    经 DisputeAuditStore 跨 run 持久）——供收缩防护豁免匹配
    （``_has_relocation_credential``）。

    替代路径在实现分支 HEAD 不存在（branch 提供时以 git cat-file 判定；branch
    缺失时保守拒绝——无第三方证明替代路径已落地，防「改声明≠交付物」）或来源标注
    缺失 → MUST NOT 登记，返回 None（调用方转既有缺件处置）。git 不可用（超时/
    无法执行/非仓库）存在性未知时同样拒绝，但留痕文案按「确定不存在」与「无法
    校验」区分（item f45e17548a60），不作失真断言。MUST NOT 因「声明段
    无该条目」上抛卡死（本函数不触碰声明段，无该语义的异常面）。写盘失败仅
    WARNING 不抛。

    ``verdict``/``evidence``（可选，evo-deliverable-declaration-drift-align
    1.4）：在册时把裁决/依据一并写入落册记录（``verdicts`` 数组 + ``evidence``
    字段），供裁决溯源（如 verdict=drift-aligned 的机械对齐留痕）；缺省不附加，
    既有调用形态零变化。

    Args:
        spec_name: spec 名。
        old_path: 陈旧旧路径（基线登记路径）。
        new_path: 替代路径（实现分支 HEAD 真实存在）。
        source: 来源标注（如 "relocated" / "judge-actual-path" / "mechanical-basename"）。
        run_id: 触发 run id。
        project_root: 项目根（审计流读写基准）。
        branch: 实现分支名（可选；提供时校验 new_path 在分支 HEAD 存在）。
        verdict: 可选裁决（如 "drift-aligned"）；提供时随记录落 verdicts。
        evidence: 可选判定依据（dict/str）；随记录落册。

    Returns:
        落册的审计记录 dict；未登记（来源缺失/替代路径校验失败/写盘失败）返回 None。
    """
    if not old_path or not new_path or not source:
        return None
    if branch is not None:
        exists = _git_object_exists_on_branch(branch, new_path, project_root)
        if exists is not True:
            # 三态区分（对齐 is_drift_candidate 对同一助手的 None 处置，item
            # 280861e01f22）：False=确定不存在；None=git 不可用（超时/无法执行/
            # 非仓库）存在性未知——留痕文案不作「不存在」的失真断言（item
            # f45e17548a60）。两种情形行为方向一致：拒绝登记、转缺件处置。
            if exists is False:
                reason = f"替代路径 {new_path} 在分支 {branch} HEAD 不存在"
            else:
                reason = (
                    f"git 不可用、无法校验替代路径 {new_path} "
                    f"在分支 {branch} HEAD 是否落地"
                )
            _resolution_logger.warning(
                "deliverables",
                f"重定位凭据登记拒绝 '{spec_name}': {reason}"
                f"（转既有缺件处置）",
            )
            return None
    else:
        # 无分支上下文：保守拒绝（无法证明替代路径已落地）
        _resolution_logger.warning(
            "deliverables",
            f"重定位凭据登记拒绝 '{spec_name}': 无分支上下文无法校验替代路径 "
            f"{new_path}（转既有缺件处置）",
        )
        return None
    # created 不在此处赋值（code-review item c3cc5432891e）：落册记录的
    # created 由 DisputeAuditStore.append 统一以落盘时刻补齐（core/admin_store.py
    # 「created 为审计默认值，不接受入口覆盖」，且在拷贝上改写、不回写本 dict），
    # 入口侧赋值是死代码、双处时间戳语义易漂移
    rec = {
        "spec": spec_name,
        # 仅落契约键 trigger_run_id（code-review item e627ccba5eb3）：D6 记录
        # 契约（core/admin_store.py DisputeAuditStore）只定义 trigger_run_id
        # （实现 run）；无契约地位的 run_id 同值冗余键已删——消费方
        # （_relocation_target_in_records 等）只读 type/old_path/new_path/
        # verdicts，删键无消费面，且防两键后续只改其一时静默分叉。
        "trigger_run_id": run_id or "",
        "type": _RELOCATION_AUDIT_TYPE,
        "old_path": old_path,
        "new_path": new_path,
        "source": source,
    }
    if verdict:
        rec["verdicts"] = [
            {
                "element": old_path,
                "verdict": verdict,
                "actual_path": new_path,
                "reasoning": f"relocate: {source}"
                + (f"; {evidence}" if evidence else ""),
            }
        ]
    if evidence is not None:
        # 独立落册（code-review item a5cdda56e9a5）：与 Args 文档「随记录
        # 落册」对齐——只传 evidence 不传 verdict 时不再被静默丢弃
        rec["evidence"] = evidence
    try:
        from core.admin_store import DisputeAuditStore

        DisputeAuditStore(project_root, _resolution_logger).append(rec)
        return rec
    except Exception as e:
        _resolution_logger.warning(
            "deliverables",
            f"重定位凭据登记写盘失败 '{spec_name}'（非阻塞）: {e}",
        )
        return None


# kind 行匹配模式由 _DECLARED_KINDS 动态构造（code-review item
# 5f0016fa172d）：常量为唯一权威源，白名单扩充/拼写调整时本正则自动跟随，
# 消除双源漂移（否则改写通道把新 kind 条目当「无 kind 行」上抛转人工，与
# 解析层口径不一致）。各 kind 词互不为前缀，交替顺序无关语义，保持常量原序。
_DECLARED_KIND_LINE_RE = re.compile(
    r"^(\s*)kind\s*:\s*(%s)(\s*(#.*)?)$" % "|".join(_DECLARED_KINDS),
    re.IGNORECASE,
)


def _declared_kind_line(lines, path_idx, end):
    """在声明条目 path 行之后定位 kind 行（+1..+2 两行窗口，单点助手）。

    声明格式容忍 path 与 kind 之间隔一行（如注释行），窗口语义即
    soften_declared_kind 的既有搜索窗；soften / remove_declared_entry /
    replace_declared_path 三处文本改写统一走本助手（code-review item
    4fc4ed9e05a9：删除侧只认紧邻一行会在 kind 于 +2 时把孤立 kind 行
    留在段内，声明段 yaml 解析失败、守卫静默回退正则语境猜测）。窗口
    内遇下一条件目的列表项起始行即停（防跨条目误中其 kind 行）。

    kind 值大小写不敏感（code-review item e736d5cf0def）：解析层
    （_declared_entries_from_text / lint_declared）对 kind 做
    ``.strip().lower()`` 后校验，``kind: Modify`` 等非全小写声明能通过
    晋升 lint 并被守卫正常对账——改写通道若只认小写，同字段合法性判定
    即与解析口径不一致，软化/删除/替换通道对大写声明静默退化为人工兜底。
    注意 group(2) 保持原行大小写形态：调用方做 kind 值比较/判定时 MUST
    先 ``.lower()`` 归一（写入新 kind 行时用小写）。

    Returns:
        (kind_idx, kind_match)；窗口内无 kind 行返回 (None, None)。
    """
    for i in range(path_idx + 1, min(end, path_idx + 3)):
        if re.match(r"^\s*-\s", lines[i]):
            break
        m = _DECLARED_KIND_LINE_RE.match(lines[i])
        if m:
            return i, m
    return None, None


def _locate_declared_section(lines):
    """定位 tasks.md 行列表中 ``## Deliverables`` 声明段边界（单点助手）。

    「``_DECLARED_HEADING_RE`` 定位 start（标题行下一行）→ ``_H2_RE`` 扫描
    end（下一个二级标题行，无则 ``len(lines)``）」段边界前导的唯一实现——
    声明段三处文本改写（replace_declared_path / soften_declared_kind /
    remove_declared_entry）共用（code-review item 95d551db0a47：原三处各持
    一份扫描拷贝，段边界规则单点演进（如标题别名）需同步改三处，漏一处即
    出现 lint 放行而某个改写入口上抛的解析漂移），与 _extract_declared_block /
    _declared_kind_line 的单点化取向一致。条目行定位（``_path_line_re`` 等）
    各入口 pattern 与报错语境不同，保留在各入口内不抽象。

    Returns:
        ``(start, end)``；无声明段标题返回 ``None``（调用方按各自语境上抛）。
    """
    start = None
    for i, line in enumerate(lines):
        if _DECLARED_HEADING_RE.match(line):
            start = i + 1
            break
    if start is None:
        return None
    end = len(lines)
    for i in range(start, len(lines)):
        if _H2_RE.match(lines[i]):
            end = i
            break
    return start, end


@contextmanager
def _declaration_write_lock(spec_dir):
    """tasks.md 声明段读改写窗口的进程间互斥（flock，``.fenix/declaration-<spec>.lock``）。

    声明段三处文本改写（replace_declared_path / soften_declared_kind /
    remove_declared_entry）同为「读全文→行级改写→_atomic_write_text 整文件替换」：
    _atomic_write_text 只保证单次写不截断，不串行化读改写窗口——两个进程（daemon
    晋升期 soften 与守卫裁决链 relocation/judge 改写）各读到旧全文后先后
    os.replace，后写者把先写者的条目改写静默回滚（与 knowledge.py
    _register_todo_retry 裸 write_text 并发覆盖同型，code-review 1bb1eacf2463
    最终以 flock+原子写修复）。比照 knowledge_backfill.append_todo_line 的
    _todo_write_lock 先例：LOCK_EX 包住读改写全过程、原子替换保持不变；锁文件
    在项目 ``.fenix/`` 下按 spec 名派生（项目根推导沿用本模块既有惯例
    ``spec_dir.parent.parent.parent``）。三入口互不嵌套调用（adjudication 逐条
    串行 apply、relocate_declared_path 仅薄委托 replace），同进程直接阻塞取锁
    不自锁。锁文件自身无内容语义。

    ``spec_dir`` MUST 为**绝对路径**：相对路径会使 parent.parent.parent 推导
    落到 cwd，锁文件落在当前工作目录 ``.fenix/`` 下、与 daemon 侧不同文件，
    flock 互斥形同虚设（code-review item aa009e1d5f45）——入口直接上抛而非
    静默取错锁（仓内各调用点经 resolve_writeback_target / project_root 拼接
    均为绝对路径，校验不改变既有行为）。
    """
    import fcntl

    spec_path = Path(spec_dir)
    if not spec_path.is_absolute():
        raise ValueError(
            f"_declaration_write_lock 要求 spec_dir 为绝对路径"
            f"（相对路径会使锁目录推导落到 cwd、互斥失效）: {spec_dir}"
        )
    fenix_dir = spec_path.parent.parent.parent / ".fenix"
    fenix_dir.mkdir(parents=True, exist_ok=True)
    fh = open(
        fenix_dir / f"declaration-{Path(spec_dir).name}.lock", "w"
    )  # noqa: SIM115 — 生命周期=with
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


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
    # 读改写窗口进程间互斥（code-review item 90bcfcc0eaf5，先例与语义详见
    # _declaration_write_lock）：LOCK_EX 包住读全文→行级改写→原子替换全过程
    with _declaration_write_lock(spec_dir):
        text = tasks.read_text(encoding="utf-8")
        lines = text.splitlines()
        section = _locate_declared_section(lines)
        if section is None:
            raise ValueError(f"tasks.md 无 Deliverables 声明段（无法修正 {element}）")
        start, end = section

        def _path_line_re(p: str):
            return re.compile(rf"^(\s*-\s*path\s*:\s*){re.escape(p)}(\s*(#.*)?)$")

        elem_idx = None
        for i in range(start, end):
            if _path_line_re(element).match(lines[i]):
                elem_idx = i
                break
        if elem_idx is None:
            raise ValueError(f"声明段无条目匹配 {element}（无法修正）")

        before = "\n".join(lines[start:end])
        # 去重：声明段已存在 actual_path 条目 → 删除 element 条目（path 行 +
        # 窗口内的 kind 行，含中间间隔行），而不是制造两份同名声明
        dup_idx = None
        for i in range(start, end):
            if i != elem_idx and _path_line_re(actual_path).match(lines[i]):
                dup_idx = i
                break
        if dup_idx is not None:
            # 去重契约是「同 kind」才删（docstring）：解析两条目的 kind 行比对，
            # 不一致（含任一条目无 kind 行无法判定）上抛转人工——否则硬交付
            # 条目（new/modify）会被静默删除、只留软审计 reference，硬校验降级
            # 为软校验（code-review item 1a98aed80b98）
            elem_kind_idx, elem_kind_m = _declared_kind_line(lines, elem_idx, end)
            dup_kind_m = _declared_kind_line(lines, dup_idx, end)[1]
            # kind 一致性按 .lower() 归一比较（item e736d5cf0def）：大小写
            # 形态不同的同一 kind（如 Modify / modify）不算不一致
            if (
                elem_kind_m is None
                or dup_kind_m is None
                or elem_kind_m.group(2).lower() != dup_kind_m.group(2).lower()
            ):
                raise ValueError(
                    f"声明段已存在 {actual_path} 但 kind 不一致"
                    f"（element: "
                    f"{elem_kind_m.group(2) if elem_kind_m else '（无 kind 行）'}，"
                    f"existing: "
                    f"{dup_kind_m.group(2) if dup_kind_m else '（无 kind 行）'}）"
                    f"——去重要求同 kind，请人工核对声明段"
                )
            remove_end = elem_kind_idx + 1
            del lines[elem_idx:remove_end]
            # 声明段缩短了 remove_end - elem_idx 行，右端同步收缩：after 仍须是
            # 纯声明段新文（Returns 契约），不得吞进下一节的标题行
            end -= remove_end - elem_idx
        else:
            m = _path_line_re(element).match(lines[elem_idx])
            lines[elem_idx] = f"{m.group(1)}{actual_path}{m.group(2)}"
        after = "\n".join(lines[start:end])

        # mkstemp + os.replace 原子写（_atomic_write_text，item 5b69a4a517cd）：
        # 声明段是守卫对账根，中断截断会令声明段丢失、守卫回退正则语境猜测
        _atomic_write_text(tasks, "\n".join(lines) + "\n")
    return {"element": element, "actual_path": actual_path, "before": before, "after": after}


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
    # 读改写窗口进程间互斥（code-review item 90bcfcc0eaf5，先例与语义详见
    # _declaration_write_lock）：LOCK_EX 包住读全文→行级改写→原子替换全过程
    with _declaration_write_lock(spec_dir):
        text = tasks.read_text(encoding="utf-8")
        lines = text.splitlines()
        section = _locate_declared_section(lines)
        if section is None:
            raise ValueError(f"tasks.md 无 Deliverables 声明段（无法软化 {element}）")
        start, end = section

        path_idx = None
        for i in range(start, end):
            if re.match(rf"^\s*-\s*path\s*:\s*{re.escape(element)}\s*(#.*)?$", lines[i]):
                path_idx = i
                break
        if path_idx is None:
            raise ValueError(f"声明段无条目匹配 {element}（无法软化）")

        before = "\n".join(lines[start:end])
        kind_idx, kind_match = _declared_kind_line(lines, path_idx, end)
        if kind_idx is None or kind_match is None:
            raise ValueError(f"条目 {element} 无 kind 行可软化")
        # kind 值大小写不敏感（item e736d5cf0def）：group(2) 保持原行形态，
        # 判定须 .lower() 归一——否则 kind: Delete 绕过防洗白防线被软化
        if kind_match.group(2).lower() == "delete":
            # 防洗白：delete 的软化在语义上就是错的（降级为仅审计 = 删除要求静默
            # 消失），lint 规则 7-10 已拒绝其不可交付形态；此处防御性拒绝并上抛
            # （调用方等价 unclear 转人工，不静默改写声明段）。
            raise ValueError(
                f"条目 {element} 是 kind: delete——delete 不参与软化（防洗白，"
                f"add-deliverable-delete-kind D4），请人工处置"
            )

        lines[kind_idx] = f"{kind_match.group(1)}kind: reference{kind_match.group(3)}"
        after = "\n".join(lines[start:end])

        # mkstemp + os.replace 原子写（_atomic_write_text，item 5b69a4a517cd）：
        # 声明段是守卫对账根，中断截断会令声明段丢失、守卫回退正则语境猜测
        _atomic_write_text(tasks, "\n".join(lines) + "\n")
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
        # os.walk + 就地剪枝（code-review item 5f9ed67a5538）：旧 rglob 先整树
        # 遍历、再在结果阶段按路径组件过滤 _BASENAME_EXCLUDE_DIRS，.git/
        # node_modules/dist 等大目录仍被深入扫描——本函数被晋升 lint 与派发
        # 处方共用，大型仓库单次判定耗时被无谓放大。改为遍历时剪枝：命中排除
        # 名的目录不再下探（语义与旧「任一组件命中即跳过」等价）；os.walk 缺省
        # 不跟随目录符号链接，与 rglob 的 ``**`` 递归行为一致。is_file 守卫
        # 保留（与旧实现对齐：同名目录/断链 symlink 不计命中）。
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in excluded]
            for fn in filenames:
                if fn != name:
                    continue
                p = Path(dirpath) / fn
                if not p.is_file():
                    continue
                try:
                    rel = p.relative_to(root).as_posix()
                except ValueError:
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
                cwd=str(project_root),
                # 只用 returncode（0=被排除）：输出走 DEVNULL
                # （code-review item feccb157c1d5）。
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            # fail-open 只作用于当前候选：继续判下一个候选（docstring「任一
            # 被排除即 True」契约，item 505afa4a6f26——此处 return False 会让
            # 首候选异常跳过后续候选，多候选场景静默漏判）
            continue
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


def _classify_unsatisfiable_reason(entry, project_root):
    """判定声明条目命中的确定性不可交付信号类别（``classify_unsatisfiable``
    的归因单点，design D1）。

    ``kind ∈ {new, modify}`` 且（``_path_is_gitignored`` 或
    ``_path_is_outside_root`` 命中）→ 返回先命中的信号类别；
    ``reference`` 恒 None（它就是软化终点）；``delete`` 恒 None
    （add-deliverable-delete-kind D4：soften 的语义是降级为仅审计
    reference 软校验，对 delete 即等于删除要求静默消失——复刻本 SPEC
    要消灭的形态，故 delete 的不可交付形态已在 lint 阶段（规则 7-10）
    拒绝，走到软化说明声明本身有问题，应升级人工而非自动降级）；entry 缺
    path/kind、path/kind 非法或判定异常均返回 None（fail-open，交由后续
    lint 照常拒绝兜底）。

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
        命中不可交付模式返回 ``"gitignored"`` / ``"outside-root"``（先命中
        者优先）；其余（含 reference、缺字段、判定不可用、规则 1-4 形态）
        返回 ``None``。
    """
    if not isinstance(entry, dict):
        return None
    path = str(entry.get("path") or "").strip()
    kind = str(entry.get("kind") or "").strip().lower()
    if not path or kind not in _DECLARED_KINDS:
        return None
    if kind not in ("new", "modify"):
        # reference 恒 None（软化终点，无需求再软化）；delete 恒 None
        # （软化即删除要求静默消失，D4 防洗白——见本函数 docstring）
        return None
    # ── 排除规则 1-4 形态（不软化，维持既有拒绝语义）──
    # 规则 1：占位符路径（软化会掩盖声明格式问题）
    if "<" in path or ">" in path:
        return None
    # 规则 2：目录路径（软化为 reference 后 lint 不再拦截，但目录不可交付）
    if kind == "modify":
        # .fenix 归一化已退役（恒等映射），目录判定按字面路径单候选
        pr = Path(project_root)
        if pr.joinpath(path).is_dir():
            return None
    # ── 正向命中判定（.fenix 归一化已退役 → 单候选=原路径）──
    candidates = [path]
    if _path_is_gitignored(project_root, candidates):
        return "gitignored"
    if _path_is_outside_root(project_root, candidates):
        return "outside-root"
    return None


def classify_unsatisfiable(entry, project_root) -> bool:
    """判定声明条目是否命中确定性不可交付模式（design D1）。

    bool 薄包装：判定语义与命中信号类别见 ``_classify_unsatisfiable_reason``
    （单点实现，code-review item 13fbdcae0f25——软化侧复用同一判定的归因
    返回值，不再二次跑 git check-ignore 反推 reason）。本函数保持既有 bool
    返回契约不变（外部调用方与测试均按真值断言）。

    Args:
        entry: 声明条目 dict（含 ``path`` / ``kind``）。
        project_root: 项目根（判定基准）。

    Returns:
        命中不可交付模式返回 True；其余（含 reference、缺字段、判定不可用、
        规则 1-4 形态）返回 False。
    """
    return _classify_unsatisfiable_reason(entry, project_root) is not None


def soften_unsatisfiable_declarations(spec_dir, project_root) -> list:
    """晋升前软化命中不可交付模式的 new/modify 声明（design D1/D2）。

    逐条走 ``_classify_unsatisfiable_reason``（与 ``classify_unsatisfiable``
    同源单点），命中即取其信号类别作 reason 并 ``soften_declared_kind``
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
            # 并留痕，防止未来新增软化路径时无声破防。经 _resolution_logger
            # 而非裸 print（code-review item cece1d891e31）：daemon 下 stdout
            # 通常被重定向/不捕获，防洗白留痕在审计最需要处会丢失。
            _resolution_logger.warning(
                "deliverables",
                f"软化跳过 delete 声明 {path}（防洗白：delete 不参与"
                f"软化，见 add-deliverable-delete-kind D4）",
            )
            continue
        # 判定 + 归因一步到位（code-review item 13fbdcae0f25）：直接消费
        # classify 同源单点的命中信号类别，不再二次跑 git check-ignore
        # 反推 reason（原二次判定在路径同时 gitignored 且仓库外时恒记
        # "gitignored"，outside-root 信号被掩盖，归因失真）。
        reason = _classify_unsatisfiable_reason(e, project_root)
        if reason is None:
            continue
        try:
            soften_declared_kind(spec_dir, path)
        except Exception as exc:
            # 单条改写失败：跳过该条记 warning，交由后续 lint 照常拒绝兜底
            # （经 _resolution_logger，理由同上方 delete 跳过分支）。
            _resolution_logger.warning(
                "deliverables",
                f"软化声明 {path} 失败（跳过，lint 兜底）: {exc}",
            )
            continue
        softened.append(
            {
                "element": path,
                "kind_before": e["kind"],
                "kind_after": "reference",
                "reason": reason,
            }
        )
    return softened


# ── 孤儿声明判定（deliverable-dispute-orphan-preclassify）─────────────────
# 声明残留判定：spec 立项时声明了一条从未被任何任务要求、源码面零引用的
# 交付物（refactor-giant-classes 事故：`tests/test_giant_classes_contract.py`
# 孤儿声明触发守卫缺件 → dispute → blocked 待人工空转 76 分钟）。
# 判定按 kind 分化（design「孤儿判定」节）：引用面 = tracked 文件中除框架
# 记账面（.fenix/**）、声明自身所在 spec 面（spec/changes/<本 spec>/**）、
# 产物面（.history/**、dist/**）以外的部分。负向 pathspec 必须写 `:!` magic
# （`-- 'x/**'` 是**包含**语义，照字面写只在被排除面上搜索、恒零命中 = 一切
# 缺件被误判孤儿，实测防「恒零命中」回归）。


def _git_grep_zero_refs(project_root, path: str, spec_name: str):
    """规则 1：源码面 ``git grep`` 引用扫描（负向 pathspec 排除观测面）。

    ``git grep -n -F <path> -- ':!.fenix/**' ':!spec/changes/<本 spec>/**'
    ':!.history/**' ':!dist/**'``——只扫 tracked 文件（天然排除未跟踪运行时
    产物，如 .fenix/verify-serving 30G），``-F`` 关闭正则避免路径元字符被
    解释。返回值：``{"hit": False, "matches": []}`` = 零命中（规则 1 通过）；
    ``{"hit": True, "matches": [...]}`` = 有引用（非孤儿）；git 不可用/异常
    → ``{"hit": True, "matches": [], "error": ...}`` fail-open（引用面未知，
    不判孤儿——lint 自身故障仍放行，不阻塞流水线）。

    注意 ``git grep`` 退出码：0 = 有匹配、1 = 无匹配、128+ = git 错误
    （非仓库/坏 pathspec）。排除 pathspec 命中不存在路径不报错（实测）。
    """
    spec_pathspec = f"spec/changes/{spec_name}/**"
    try:
        proc = subprocess.run(
            [
                "git", "-C", str(project_root),
                "grep", "-n", "-F", path, "--",
                ":!.fenix/**",
                f":!{spec_pathspec}",
                ":!.history/**",
                ":!dist/**",
            ],
            capture_output=True,
            text=True,
            timeout=_GIT_READ_TIMEOUT_SECONDS,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return {"hit": True, "matches": [], "error": str(e)}
    if proc.returncode == 1:
        # 无匹配 → 零引用（确定性）
        return {"hit": False, "matches": []}
    if proc.returncode != 0:
        # git 错误（非仓库/坏 pathspec）→ fail-open：引用面未知，不判孤儿
        return {
            "hit": True,
            "matches": [],
            "error": proc.stderr.strip() or f"git grep exit={proc.returncode}",
        }
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    return {"hit": True, "matches": lines}


def _git_log_path_history(project_root, path: str):
    """规则 2：路径限定历史（仅 kind: modify）——``git log --all --oneline
    -- <path>``（路径限定 tree diff，非 pickaxe ``-S``——pickaxe 匹配文本
    内容会把记账面「提到」误判为引用，令判定结果随记录行为翻转）。

    命中非空 = 该路径**曾作为文件存在过**（缺失更可能是拆包/改名漂移 →
    走人工，不判孤儿）；零命中 = 从未作为文件存在过 → 进入孤儿判定。
    ``git log -- <path>`` 对从未存在的路径返回空输出 + exit 0（实测），故
    以 stdout 非空为命中判据；git 不可用/异常 → fail-open（不判孤儿）。
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(project_root), "log", "--all", "--oneline", "--", path],
            capture_output=True,
            text=True,
            timeout=_GIT_READ_TIMEOUT_SECONDS,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return {"hit": True, "commits": [], "error": str(e)}
    if proc.returncode != 0:
        # git 错误（非仓库等）→ fail-open：历史未知，不判孤儿
        return {
            "hit": True,
            "commits": [],
            "error": proc.stderr.strip() or f"git log exit={proc.returncode}",
        }
    commits = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    return {"hit": bool(commits), "commits": commits}


def _task_lines_mention(tasks_md_text: str, path: str) -> list:
    """规则 3：任务清单零出现——tasks.md 全部任务行（``- [ ]``/``- [x]``
    开头）文本不含该路径**及其 basename**（末段文件名）。

    任务行是交付需求的第一语义位，判别力最强（正常 spec 首组任务行均逐字
    点名声明路径）。basename 计入的理由（design 实测）：add-architect-agent
    的 ``ArchitectPanel.tsx`` 任务行只写 basename，全路径零命中——只认全路径
    会把非孤儿声明误拦；basename 命中只让判定更保守（回退人工，不误删）。
    事故案的 basename 在其 spec 任务行命中 0 次，放宽后检出能力不减。

    Returns:
        命中的任务行列表（含 basename 命中的行）；零命中返回 []。
    """
    basename = Path(path).name
    hits: list = []
    for line in tasks_md_text.splitlines():
        if not _TASKS_ITEM_RE.match(line):
            continue
        if path in line or (basename and basename in line):
            hits.append(line)
    return hits


def is_orphan_declaration(project_root, spec_name: str, entry: dict, spec_dir=None) -> dict:
    """孤儿声明判定（deliverable-dispute-orphan-preclassify 规则 1/2/3 合成）。

    按声明 kind 分化（判定查询工具与覆盖范围各异，design「孤儿判定」节）：
    - ``kind: new``：规则 1（源码面 git grep 零引用）AND 规则 3（任务清单
      零出现）→ 孤儿。不查历史（新建文件的本义即「主树不存在且历史未出现
      过」，全历史查询对 new 零信息量）；
    - ``kind: modify``：规则 1 AND 规则 2（``git log --all -- <path>`` 路径
      限定历史零命中）AND 规则 3 → 孤儿。历史命中 = 路径曾作为文件存在过，
      缺失更可能是拆包/改名漂移 → 非孤儿（走人工）；
    - ``kind: delete``：**不参与孤儿预分类**（add-deliverable-delete-kind D4
      防洗白：delete 声明一律进人工裁决）→ 恒非孤儿。

    任一规则命中（有引用/历史/任务提及）→ 非孤儿（宁可多走人工，不误删
    真实交付物）。git 不可用/读取异常 → fail-open 非孤儿（lint 自身故障仍
    放行，不阻塞晋升）。

    Args:
        project_root: 项目根（git 命令 cwd 基准，主树）。
        spec_name: spec 名（负向 pathspec 排除面 ``spec/changes/<本 spec>/**``
            的构造基准）。
        entry: 声明条目 dict（含 ``path`` / ``kind``）。
        spec_dir: spec 目录（规则 3 读 tasks.md 用）；缺省回退
            ``<project_root>/spec/changes/<spec_name>``。

    Returns:
        ``{"orphan": bool, "evidence": {...}}``。evidence 携带各规则判定摘要
        （供违规文案/审计 reasoning 引用）：``{"git_grep": ...,
        "git_log": ..., "task_lines": [...]}``。
    """
    path = str((entry or {}).get("path") or "").strip()
    kind = str((entry or {}).get("kind") or "").strip().lower()
    evidence: dict = {"path": path, "kind": kind}
    if not path or kind == "delete":
        # delete 不参与预分类；缺 path 无判定对象 → 非孤儿
        return {"orphan": False, "evidence": evidence}

    # gitignored / 仓库外路径不参与孤儿判定（design「边界」节：运行时产物路径
    # 仍需语义判断，走人工，不预分类）——规则 1 的引用面被负向 pathspec 排除
    # （.fenix/** 等）或路径本身不可能在仓内（仓库外），git grep 恒零命中对
    # 孤儿判定零信息量；且该形态已有 lint 规则 5/6 专属拒绝，孤儿检查不得在
    # 其上报双层违规。
    # .fenix 归一化已退役（恒等映射）→ 单候选=原路径
    candidates = [path]
    if _path_is_gitignored(project_root, candidates) or _path_is_outside_root(
        project_root, candidates
    ):
        evidence["skipped"] = "gitignored-or-outside-root"
        return {"orphan": False, "evidence": evidence}

    # 规则 1：源码面零引用
    grep = _git_grep_zero_refs(project_root, path, spec_name)
    evidence["git_grep"] = grep
    if grep.get("hit") and grep.get("matches"):
        return {"orphan": False, "evidence": evidence}
    if grep.get("error"):
        # git 不可用 → fail-open（引用面未知，不判孤儿）
        return {"orphan": False, "evidence": evidence}

    # 规则 2：历史判据（仅 kind: modify）
    if kind == "modify":
        history = _git_log_path_history(project_root, path)
        evidence["git_log"] = history
        if history.get("hit") or history.get("error"):
            # 历史命中（疑似漂移）或历史不可查（fail-open）→ 非孤儿
            return {"orphan": False, "evidence": evidence}

    # 规则 3：任务清单零出现（全路径与 basename 皆零）
    task_hits: list = []
    tasks_path = Path(spec_dir) if spec_dir is not None else None
    if tasks_path is None:
        tasks_path = Path(project_root) / "spec" / "changes" / spec_name
    tasks_file = tasks_path / "tasks.md"
    try:
        if tasks_file.exists():
            task_hits = _task_lines_mention(tasks_file.read_text(encoding="utf-8"), path)
    except (OSError, UnicodeDecodeError):
        # tasks.md 不可读 → 任务面未知，与 git 故障同向 fail-open 判非孤儿：
        # 未知态按「零出现」推进会误把本应回人工的条目判成孤儿，不保守。
        evidence["skipped"] = "tasks-md-unreadable"
        return {"orphan": False, "evidence": evidence}
    evidence["task_lines"] = task_hits
    if task_hits:
        return {"orphan": False, "evidence": evidence}

    # 全部规则通过 → 孤儿
    evidence["summary"] = (
        f"orphan-preclassify: kind={kind} 路径在主树不存在，源码面 git grep "
        f"零引用（排除 .fenix/spec 自身/.history/dist 观测面），tasks.md 任务行"
        f"对全路径与 basename 均零出现"
    )
    return {"orphan": True, "evidence": evidence}


# ── 漂移笔误机械对齐判定（evo-deliverable-declaration-drift-align D1）─────────
# 与孤儿预分类并列、互斥（孤儿=零历史命中；漂移=历史命中+目标候选存在）：
# 声明路径在主树与实现分支 HEAD 均缺、且 git 历史对该路径有命中（曾作为文件
# 存在过，即拆包/改名漂移特征）→ 进入 _locate_drift_target 候选定位。唯一候选
# 且分支 HEAD 真实存在方机械对齐；零/多候选 fail-open 回人工。纯函数判定层，
# 改写/审计/提交由 adjudication 编排（_preclassify_drift，复用既有原语）。


def _git_branch_merge_base(project_root, branch) -> "str | None":
    """``git merge-base HEAD <branch>`` 计算分支改动集合的 diff 基准。

    拆包/改名漂移的候选定位以「本 spec 的改动落在哪个模块」为判据，只能由
    分支改动集合（merge-base..branch）判定。merge-base 计算失败/异常 → None
    （调用方 fail-open 回人工，不机械改写）。
    """
    if not branch:
        return None
    try:
        proc = subprocess.run(
            ["git", "-C", str(project_root), "merge-base", "HEAD", branch],
            capture_output=True,
            text=True,
            timeout=_GIT_READ_TIMEOUT_SECONDS,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def branch_merge_base(project_root, branch) -> "str | None":
    """``_git_branch_merge_base`` 的公开薄包装（直接委托，行为逐字一致）。

    code-review item 2fe1cd927997：跨模块消费方（dispatch/adjudication）改经
    公开名导入，私有本体仍是本模块内部实现细节——其签名/语义调整不再于模块
    外被静默依赖。既有内部用法与测试对私有名的导入不动。
    """
    return _git_branch_merge_base(project_root, branch)


def _git_branch_changed_files(project_root, branch, merge_base) -> list:
    """``git diff --name-only --diff-filter=AM <merge-base>..<branch>`` 分支改动
    集合（新增/修改文件，design D1 规则 2；既有用法见 mergeback.py:757）。

    拆包/改名漂移场景下分支改动集合内的 .py 文件是「本次实现改动落点」的
    唯一证据——包内文件按名字无法分辨（core/pm_engine/dispatch/ 实测 7 个
    模块），MUST NOT 用全仓 rglob 同名文件兜底。git 异常 → 空列表（调用方
    fail-open 回人工）。
    """
    if not branch or not merge_base:
        return []
    try:
        proc = subprocess.run(
            [
                "git", "-C", str(project_root),
                "diff", "--name-only", "--diff-filter=AM",
                f"{merge_base}..{branch}",
            ],
            capture_output=True,
            text=True,
            timeout=_GIT_READ_TIMEOUT_SECONDS,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    if proc.returncode != 0:
        return []
    files = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    files.sort()
    return files


def _locate_drift_target(project_root, declared_path, branch, merge_base) -> list:
    """全仓定位拆包后候选落点（evo-deliverable-declaration-drift-align D1）。

    规则（确定性，无「同名字符串」之外的语义推断）：
    1. 取旧文件 basename 去 ``.py`` 作为**包目录名**（``worktree_manager.py`` →
       ``worktree_manager/``、``pm_engine/dispatch.py`` → ``pm_engine/dispatch/``）；
    2. 候选 = 该包目录内、且落在本次实现分支改动集合
       （``git diff --name-only --diff-filter=AM <merge-base>..<branch>``）内的
       .py 文件——「本 SPEC 的改动落在哪个模块」只能由分支改动集合判定；
    3. MUST NOT 用 rglob 全仓同名文件兜底（同名冲突会伪造唯一性）。

    Args:
        project_root: 项目根（git 命令 cwd 基准）。
        declared_path: 声明路径（拆包前的旧单文件路径）。
        branch: 实现分支名。
        merge_base: merge-base 提交（``_git_branch_merge_base`` 计算）。

    Returns:
        候选相对路径列表（排序）；零候选 = 无可对齐（fail-open 回人工）。
    """
    name = Path(declared_path or "").name
    if not name.endswith(".py"):
        return []  # 非 .py 无「拆包为目录」的形态（规则 1 前提）
    pkg_dir = name[:-3]  # 去 .py 得包目录名
    parent = str(Path(declared_path).parent)
    if parent in ("", "."):
        pkg_prefix = f"{pkg_dir}/"
    else:
        pkg_prefix = f"{parent}/{pkg_dir}/"
    changed = _git_branch_changed_files(project_root, branch, merge_base)
    candidates = [
        p
        for p in changed
        if p.startswith(pkg_prefix) and p.endswith(".py") and p != declared_path
    ]
    candidates.sort()
    return candidates


def is_drift_candidate(entry, project_root, branch, merge_base=None) -> dict:
    """漂移特征判定（evo-deliverable-declaration-drift-align 1.1）。

    与孤儿预分类并列且互斥（孤儿=零历史命中；漂移=历史命中+目标候选存在）。
    命中漂移特征须同时满足（任一不成立 → 非漂移，fail-open 回既有通道）：
    1. ``kind == modify`` 且主树 HEAD 无该路径（复用 ``is_stale_declaration``
       陈旧信号——new/delete/reference 形态无「曾作为文件存在过」的漂移语义）；
    2. 实现分支 HEAD 也无该路径（分支已落地 → 无缺件，无对齐必要）；
    3. git 历史对该路径有命中（``git log --all -- <path>`` 非空——曾作为文件
       存在过，缺失更可能是拆包/改名漂移，区别于零引用孤儿）。

    条件 3 命中后随 evidence 附候选定位线索（``_locate_drift_target`` 候选
    清单与 merge_base），供调用方直接判唯一性、供审计 reasoning 引用。

    Args:
        entry: 声明条目 dict（含 path/kind）。
        project_root: 项目根（git 命令 cwd 基准，主树）。
        branch: 实现分支名（分支 HEAD 存在性判定基准；缺失时 fail-open 非漂移）。
        merge_base: merge-base 提交（可选；缺省时按需计算一次供候选定位）。

    Returns:
        ``{"drift": bool, "evidence": {...}}``。evidence 含陈旧信号、分支 HEAD
        存在性、git 历史命中摘要、候选定位线索（``candidates``/``merge_base``）。
    """
    path = str((entry or {}).get("path") or "").strip()
    kind = str((entry or {}).get("kind") or "").strip().lower()
    evidence: dict = {"path": path, "kind": kind}
    if not path or kind != "modify":
        return {"drift": False, "evidence": evidence}
    # 条件 1：陈旧信号（modify 且主树 HEAD 无该路径）
    if not is_stale_declaration(entry, project_root):
        return {"drift": False, "evidence": evidence}
    evidence["stale"] = True
    # 条件 2：实现分支 HEAD 无该路径（git cat-file -e）；分支缺失无法判定
    # 分支 HEAD 缺失 → fail-open 非漂移（不机械改写）
    if not branch:
        return {"drift": False, "evidence": evidence}
    exists = _git_object_exists_on_branch(branch, path, project_root)
    if exists is not False:
        # 三态判别（对齐 _declared_satisfied_on_branch 的 None 处置，item
        # 280861e01f22）：True=分支已落地无缺件；None=git 不可用（超时/无法
        # 执行/非仓库）存在性未知——旧真值判断把 None 也当「分支缺路径」
        # 放行，drift=True 与 evidence["branch_missing"] 在 git 不可用环境
        # 下失真，误导人工裁决
        return {"drift": False, "evidence": evidence}
    evidence["branch_missing"] = True
    # 条件 3：git 历史命中（曾作为文件存在过）
    history = _git_log_path_history(project_root, path)
    evidence["git_log"] = history
    if history.get("error"):
        # 历史不可查 → fail-open 非漂移（不机械改写）
        return {"drift": False, "evidence": evidence}
    if not history.get("hit"):
        return {"drift": False, "evidence": evidence}
    evidence["history_hit"] = len(history.get("commits") or [])
    # 候选定位线索（供调用方唯一性判定与审计 reasoning 引用）
    try:
        if merge_base is None:
            merge_base = _git_branch_merge_base(project_root, branch)
        candidates = _locate_drift_target(project_root, path, branch, merge_base)
    except Exception:
        candidates = []
        merge_base = None
    evidence["candidates"] = candidates
    evidence["merge_base"] = merge_base
    return {"drift": True, "evidence": evidence}


def remove_declared_entry(spec_dir, element: str) -> dict:
    """机械删除 tasks.md 声明段条目的 path+kind 两行（孤儿声明删除）。

    逐行精确文本操作（不经 yaml 反序列化再序列化——保留注释/顺序，diff
    最小）：在 ``## Deliverables`` 段内找到 ``path == element`` 的条目，
    删除 path 行 + 搜索窗（+1..+2）内的 kind 行（kind 与 path 间隔的行，
    如注释行，一并移除；其余内容不动）。删除前重读文件、按条目精确删除，
    任何失败上抛（调用方等价 fallback 回退既有路径）。

    Returns:
        {"element", "before": <声明段原文>, "after": <声明段新文>}，
        供审计流落 diff（design「审计」节：diff 记删除声明前后文本）。
    """
    tasks = Path(spec_dir) / "tasks.md"
    # 读改写窗口进程间互斥（code-review item 90bcfcc0eaf5，先例与语义详见
    # _declaration_write_lock）：LOCK_EX 包住读全文→行级改写→原子替换全过程
    with _declaration_write_lock(spec_dir):
        text = tasks.read_text(encoding="utf-8")
        lines = text.splitlines()
        section = _locate_declared_section(lines)
        if section is None:
            raise ValueError(f"tasks.md 无 Deliverables 声明段（无法删除 {element}）")
        start, end = section

        def _path_line_re(p: str):
            return re.compile(rf"^(\s*-\s*path\s*:\s*){re.escape(p)}(\s*(#.*)?)$")

        elem_idx = None
        for i in range(start, end):
            if _path_line_re(element).match(lines[i]):
                elem_idx = i
                break
        if elem_idx is None:
            raise ValueError(f"声明段无条目匹配 {element}（无法删除）")

        before = "\n".join(lines[start:end])
        # kind 行定位走单点助手（+1..+2 两行窗口，容忍 path 与 kind 间隔一行）：
        # 只认紧邻一行会在 kind 于 +2 时把孤立 kind 行留在段内，声明段 yaml
        # 解析失败、守卫静默回退正则语境猜测（code-review item 4fc4ed9e05a9）
        kind_idx, _kind_match = _declared_kind_line(lines, elem_idx, end)
        remove_end = kind_idx + 1 if kind_idx is not None else elem_idx + 1
        del lines[elem_idx:remove_end]
        # 声明段缩短了 remove_end - elem_idx 行，右端同步收缩：after 仍须是
        # 纯声明段新文（Returns 契约），不得吞进下一节的标题行
        end -= remove_end - elem_idx
        after = "\n".join(lines[start:end])

        # mkstemp + os.replace 原子写（_atomic_write_text，item 5b69a4a517cd）：
        # 声明段是守卫对账根，中断截断会令声明段丢失、守卫回退正则语境猜测
        _atomic_write_text(tasks, "\n".join(lines) + "\n")
    return {"element": element, "before": before, "after": after}


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
       部静默放行，只剩任务分组规则报错，失败信息指向不到真问题；条目 path
       命中绝对路径/通配符/尾斜杠目录三类形态同属「声明等于不存在」族——
       下游解析器按 ``_is_filtered_declaration_path`` 静默过滤（f109a12eefa3），lint
       以同一谓词在晋升当下拒绝；
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
       规则 5 的 gitignore 机制覆盖不到仓库外，该声明任何分支不可交付。
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
    11. ``kind: new`` 主树不存在且 basename 零命中时的孤儿声明拦截
        （deliverable-dispute-orphan-preclassify）——任务清单（全路径与
        basename 皆）零出现 + 源码面 git grep 零引用即判声明残留，拒绝
        晋升（规则 4 零命中放行形态的收口，见内层实现）。
    12. 同一 path 在声明段出现多种 kind（abc42cc46260）——解析器
        （``_declared_entries_from_text``）按 path 去重静默保留首条，生效 kind
        取决于书写顺序，自相矛盾的声明在晋升当下拒绝并提示合并/去重。

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
    block, no_block_diag = _extract_declared_block(text)
    if block is None:
        if no_block_diag is None:
            return []  # 无声明段（存量 spec）不在 lint 职责内
        # 规则 0：有标题但段内无 fenced yaml 块（诊断文案单点在 _extract_declared_block）
        return [no_block_diag]
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
    # 规则 12（code-review item abc42cc46260）：声明段同 path 多 kind——
    # _declared_entries_from_text 按 path 去重、静默保留首条，后者被丢弃且
    # 生效 kind 取决于书写顺序（先 reference 后 new 或相反）；自相矛盾的
    # 声明只能靠人读 tasks.md 发现，在晋升当下拒绝并提示合并/去重。
    kinds_by_path: dict = {}
    for e in entries:
        if not isinstance(e, dict):
            continue
        p = str(e.get("path") or "").strip()
        k = str(e.get("kind") or "").strip().lower()
        if p and k in _DECLARED_KINDS:
            kinds_by_path.setdefault(p, set()).add(k)
    for p, kinds in kinds_by_path.items():
        if len(kinds) > 1:
            violations.append(
                f"[{p}] 声明段存在多种 kind（{'/'.join(sorted(kinds))}）——"
                f"同 path 重复声明会被解析器去重、静默保留首条（生效 kind 取决"
                f"于书写顺序），请合并为单一条目或去重后重试晋升"
            )
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
        # 绝对路径/通配符/尾斜杠目录（code-review item f109a12eefa3）：下游
        # _declared_entries_from_text 按 _is_filtered_declaration_path 同一谓词
        # 逐条静默过滤（全部条目被滤空即返回 None，守卫回退正则语境猜测）——
        # lint 放行即「声明等于不存在」，与上方占位符同型，晋升当下拒绝。
        if _is_filtered_declaration_path(path):
            violations.append(
                f"[{path}] 是绝对路径/通配符/尾斜杠目录形态——下游解析器会"
                f"静默过滤该条目（等同未声明，守卫回退正则语境猜测），"
                f"请改为仓库内字面文件路径（尾斜杠目录请去掉尾斜杠并锚定到"
                f"目录下确定性锚点文件，绝对路径请改为相对项目根的路径）"
            )
            continue
        # 目录声明按字面路径判定（.fenix 归一化已退役，恒等映射自然退化）
        candidates = [path]
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
        if kind in ("modify", "new") and _path_is_outside_root(project_root, candidates):
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
                if kind == "reference" and _path_is_outside_root(project_root, candidates):
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
            elif not hits:
                # 规则 11（deliverable-dispute-orphan-preclassify）：孤儿声明
                # 检查——覆盖规则 4 原本放行的「basename 零命中」形态：主树
                # 不存在 + basename 零命中 + 任务清单（全路径与 basename 皆）
                # 零出现 + 源码面 git grep 零引用 → 拦（声明残留，拒绝晋升，
                # 让孤儿声明在立项当下暴露）。basename 多命中沿用规则 4 的
                # fail-open（语义矛盾需 LLM 裁决，lint 只拦确定性形态）。
                # kind: new 不查历史（规则 2 分化结论：全历史查询对其零信息量）。
                oc = is_orphan_declaration(
                    project_root,
                    Path(spec_dir).name,
                    {"path": path, "kind": "new"},
                    spec_dir,
                )
                if oc.get("orphan"):
                    evidence = oc.get("evidence") or {}
                    violations.append(
                        f"[{path}] 是孤儿声明——kind: new 路径在主树不存在，"
                        f"任务清单（tasks.md 全部任务行）对该路径及其 basename "
                        f"均零出现（规则 3 全路径/basename 皆零命中），源码面 "
                        f"git grep 零引用（规则 1，排除 .fenix/spec 自身/"
                        f".history/dist 观测面；判定证据 {evidence}）"
                        f"— 声明残留，请从 Deliverables 段移除或补齐对应任务"
                    )
    return violations


# tasks.md 分组标题正则（task-track D2「同源规则」）：与
# core/dashboard/data.py:parse_tasks 及 bin/fenix_process.py:parse_tasks 的
# 分组正则字面量互指，三处必须保持一致（点号可选双历史格式兼容：
# `## 1. 标题` 与 `## 1 标题`）。漂移由 tests/test_task_track.py 双格式
# Scenario 兜底。
_TASKS_GROUP_RE = re.compile(r"^##\s+\d+\.?\s+(.+)$")

# 任务项正则：与 data.py:parse_tasks / fenix_process.py:parse_tasks 同源。
# 严口径（仅行首 `- [x]`/`- [ ]`）专用于任务行计数与孤儿判定；语境分类用
# 文件头部 _CHECKBOX_RE 宽口径，差异有意、勿混用（item 6e387df34df1）。
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


def lint_tasks_text(text: str, lane: str = "full") -> List[str]:
    """tasks.md 文本可解析性判定 + 产物归属校验（task-track R2 + add-task-artifact-ownership-gate）。

    ``lint_tasks_parseable`` 与 dispatch 收口复检挂点（full/fast-track 车道）
    共用同一判定逻辑，避免两套解析口径漂移。文本形态直接判定：

    - 0 个任务分组（含文件为空/无任务行的情形）→ 违规（既有形态，拦截早于
      run 烧钱）；
    - 分组数 ≥ 1 但任务行总数为 0（2026-09-11 add-impl-terminal-nocommit-gate
      事故形态：sed 把任务行写成 ``^- [x] 1.1 …``，分组完好、任务行全灭）
      → 违规，文案点名损伤特征并给出修正处方；
    - 分组与任务行均正常 → 放行。

    可解析性判定通过后（未提前返回），逐条扫描任务行执行「产物归属」校验
    （add-task-artifact-ownership-gate，design D1 三重合取）：命中已登记验证
    链产物的产出式引用 + 行内无代码文件 + 产出动词 + 执行车道 ∉ 归属车道 →
    判违规。lane 参数由调用侧传入（缺失时由 ``lint_tasks_parseable`` 按
    ``.spec.yaml`` mode 解析，缺省按 ``full`` 保守处理）。

    Args:
        text: tasks.md 文件原文。
        lane: 执行车道——``"fast-track"`` 或 ``"full"``（full 车道执行者为
            implementer）。默认 ``"full"`` 保持向后兼容。

    Returns:
        违规描述清单；空列表 = 通过。
    """
    from core.artifact_ownership import ownership_violations_for_task_line

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

    # ── 可解析性判定通过 → 追加产物归属校验（add-task-artifact-ownership-gate）──
    # 逐条扫描任务行，调用 ownership_violations_for_task_line 进行
    # design D1 三重合取判定；fail-open（单行异常不中断全局扫描）
    ownership_violations: List[str] = []
    for line in text.splitlines():
        if _TASKS_ITEM_RE.match(line):
            try:
                ownership_violations.extend(
                    ownership_violations_for_task_line(line, lane)
                )
            except Exception as exc:  # pragma: no cover - 防御分支
                try:
                    _resolution_logger.warning(
                        "deliverables",
                        "产物归属校验单行异常（fail-open，放行该行）: %s",
                        exc,
                    )
                except Exception:
                    pass
    return ownership_violations


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
    lane = _resolve_lane_for_spec_dir(spec_dir)
    return lint_tasks_text(text, lane)


def _resolve_lane_for_spec_dir(spec_dir) -> str:
    """执行车道判定（add-task-artifact-ownership-gate D3）。

    复用既有 ``core.spec_mode.read_spec_mode``（MUST NOT 自实现第二套
    ``.spec.yaml``/YAML 解析）：``fast-track`` → ``"fast-track"``；
    其余（`mode` 缺失 / 值非法 / 文件不存在 / 解析异常）保守按 ``full``。
    ``read_spec_mode(project_root, spec_name)`` 内部已做读侧容错（缺省 full、
    不抛异常），故本函数仅需归一化调用签名（spec_dir → spec_name + project_root）。

    Args:
        spec_dir: spec 目录（``<project_root>/spec/changes/<spec>/``）。

    Returns:
        ``"fast-track"`` 或 ``"full"``。
    """
    from core.spec_mode import read_spec_mode

    spec_dir = Path(spec_dir)
    try:
        spec_name = spec_dir.name
        project_root = spec_dir.parent.parent.parent
        return read_spec_mode(project_root, spec_name)
    except Exception:
        # 异常保守按 full（与 read_spec_mode 读侧容错语义一致）
        return "full"
