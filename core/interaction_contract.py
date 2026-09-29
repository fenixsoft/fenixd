"""interaction_contract.py — 交互契约显式化校验器（add-interaction-contract-and-per-assert-triage D1/D2）。

背景（v2-overview-page 事故，2026-08-30）：首页项目卡片渲染成可点击外观
（amis 卡片默认 link 样式）却从未实现跳转——spec 没写这个需求、场景集因此没测。
本模块把「视觉上可交互的元素」纳入显式契约：页面类 SPEC 的场景集 MUST 覆盖每个
渲染为可交互形态的元素，或在该元素定义处声明「纯展示、不可交互」；二者皆无的
场景集被判覆盖不完整，要求 planner 补齐。

设计要点（design.md D1/D2）：
  - 候选识别采用**声明式**：扫描 SPEC 文本中 button-group/button/cards 循环/
    href 与 link 字样 className 等模式（首版清单，见 ``INTERACTIVE_KEYWORDS``，
    可迭代扩展）；不做渲染树自动探测（成本高误报多，靠场景覆盖要求兜底）。
  - 场景-元素映射由 planner 记入场景元数据（``covers`` 字段），纯展示声明记
    ``declared_display``；校验器 diff 候选集与场景集。
  - 纯展示声明双通道：SPEC 元素定义处（命中行）的「纯展示 / 不可交互」标注，
    或 planner 产出场景对象上的 ``declared_display`` 列表。
  - 覆盖判定三通道：场景 ``covers`` 显式登记 → 候选标识原文/归一化形式出现在
    场景文本（steps/assertions/description）→ 主语义关键词别名匹配（如
    ``dark-Card--link`` ↔ 场景描述「卡片」）。
  - 旧场景集（无元数据）不追溯（design D2）：持久化集为遗留集时跳过强制，
    仅新验证轮生效。

确定性与纯 Python：输入 SPEC 文本 + planner 产出 JSON，无 LLM 参与，planner
无法通过输出文本绕过（与 scenario-freeze / verdict-check 同型）。
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── 声明式候选识别模式（design D1 首版清单，可迭代）──────────────────

# 可交互语义关键词（token 命中任一即候选）
INTERACTIVE_KEYWORDS = ("button", "btn", "card", "link", "href", "clickable")

# 主题前缀（amis/cxd/antd 主题类名前缀，归一化时剥离）
THEME_PREFIXES = ("dark-", "cxd-", "light-", "amis-", "ant-")

# cards 渲染循环模式（design D1：cards 循环）
_CARDS_LOOP_RE = re.compile(
    r"(卡片|cards).{0,24}?(循环|渲染|map\(|forEach|each|列表|遍历)|"
    r"(循环|渲染|map\(|forEach|遍历).{0,24}?(卡片|cards)",
    re.IGNORECASE,
)

# href / link 字段模式（design D1：href/link 字样）
_HREF_FIELD_RE = re.compile(r"[\"']?(href|link)[\"']?\s*[:=]", re.IGNORECASE)

# token 形态：字母开头，含字母/数字/连字符/下划线
_TOKEN_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9_-]+\b")

# 纯展示声明标记（SPEC 元素定义处 / planner declared_display）
DISPLAY_DECL_RE = re.compile(r"纯展示|不可交互|declared-display|display-only")

# 主语义关键词的别名（覆盖判定的宽松通道：场景描述用中文表述同一元素）
KEYWORD_ALIASES: Dict[str, tuple] = {
    "card": ("卡片", "card"),
    "button": ("按钮", "button"),
    "btn": ("按钮", "button"),
    "link": ("链接", "跳转", "link"),
    "href": ("链接", "跳转", "href"),
    "clickable": ("可点击", "点击"),
}


# ── 数据结构 ────────────────────────────────────────────────────────


class InteractiveCandidate:
    """SPEC 文本中识别出的单个可交互候选元素。"""

    __slots__ = ("key", "raw", "source", "line", "snippet", "declared_display")

    def __init__(
        self,
        key: str,
        raw: str,
        source: str,
        line: int,
        snippet: str,
        declared_display: bool = False,
    ):
        self.key = key  # 归一化标识（主题前缀已剥离）
        self.raw = raw  # 原始 token
        self.source = source  # 来源文件（相对路径）
        self.line = line  # 1-based 行号
        self.snippet = snippet  # 命中行片段（截断）
        self.declared_display = declared_display  # 定义处已声明纯展示

    def to_dict(self) -> dict:
        return {
            "id": self.key,
            "raw": self.raw,
            "source": self.source,
            "line": self.line,
            "snippet": self.snippet,
            "declared_display": self.declared_display,
        }


class ContractResult:
    """交互契约覆盖校验结论。

    Attributes:
        ok: 候选集是否全部被覆盖或声明纯展示。
        candidates: 全部候选（InteractiveCandidate）。
        uncovered: 既无场景覆盖又无纯展示声明的候选 key 列表。
        covered: (候选 key, 覆盖它的场景 id 列表) 列表。
        declared: 纯展示声明的候选 key 列表（SPEC 标注或 planner 登记）。
        skipped: 是否因遗留场景集跳过强制（design D2：旧集不追溯）。
        change_lines: 人类可读的校验留痕行。
    """

    def __init__(self):
        self.ok = True
        self.candidates: List[InteractiveCandidate] = []
        self.uncovered: List[str] = []
        self.covered: List[tuple] = []
        self.declared: List[str] = []
        self.skipped = False
        self.change_lines: List[str] = []

    @property
    def has_candidates(self) -> bool:
        return bool(self.candidates)


# ── 归一化与识别 ────────────────────────────────────────────────────


def normalize_token(token: str) -> str:
    """归一化元素标识：小写、剥离主题前缀、折叠分隔符。"""
    t = (token or "").strip().lower()
    changed = True
    while changed:
        changed = False
        for prefix in THEME_PREFIXES:
            if t.startswith(prefix):
                t = t[len(prefix) :]
                changed = True
    t = re.sub(r"--+", "-", t)
    return t.strip("-_")


def _bare_keyword(token_lower: str) -> Optional[str]:
    """裸关键词识别（含简单复数形式：cards → card）。"""
    if token_lower in INTERACTIVE_KEYWORDS:
        return token_lower
    if token_lower.endswith("s") and token_lower[:-1] in INTERACTIVE_KEYWORDS:
        return token_lower[:-1]
    return None


def _primary_keyword(key: str) -> Optional[str]:
    """候选标识的主语义关键词（首个命中关键词的部分，含复数形式）。"""
    for part in key.split("-"):
        kw = _bare_keyword(part)
        if kw:
            return kw
    return None


def _has_display_decl(lines: List[str], idx: int) -> bool:
    """候选命中行自身是否含纯展示声明（声明与元素同行，避免跨元素误挂）。"""
    return bool(DISPLAY_DECL_RE.search(lines[idx]))


def extract_candidates(text: str, source: str = "") -> List[InteractiveCandidate]:
    """从 SPEC 文本提取可交互候选元素（声明式首版模式，design D1）。

    模式：
      1. 带分隔符且含交互关键词的 token（如 ``dark-Card--link``、``submit-btn``、
         ``button-group``）；
      2. 无分隔符裸关键词 token（button/cards/href/link 等），直接视为候选，
         不做元素定义语境判定（首版曾要求所在行含语境标记如类名/字段/组件/
         循环/渲染等，该门槛已被有意移除：中文 SPEC 中的英文 token 几乎均为
         组件/字段标识，加门槛徒增漏报面）；
      3. cards 渲染循环（卡片/cards 与循环/渲染/map 同行）；
      4. href/link 字段（``"href":`` / ``link=``）。

    按归一化 key 去重，保留首次出现位置。
    """
    if not text:
        return []
    lines = text.splitlines()
    found: Dict[str, InteractiveCandidate] = {}
    order: List[str] = []

    def _register(raw: str, idx: int):
        key = normalize_token(raw)
        if not key:
            return
        if key in found:
            # 同一文档内同元素多处出现：任一处声明纯展示即视为已声明
            # （与 collect_spec_candidates 的跨文档合并语义一致）
            if _has_display_decl(lines, idx):
                found[key].declared_display = True
            return
        # 分段精确匹配而非子串包含：discard（含 card）、hyperlink（含 link）
        # 这类嵌入式子串不应被误判为可交互候选
        if not any(_bare_keyword(part) for part in re.split(r"[-_]", key)):
            return
        snippet = lines[idx].strip()
        if len(snippet) > 120:
            snippet = snippet[:117] + "..."
        found[key] = InteractiveCandidate(
            key=key,
            raw=raw,
            source=source,
            line=idx + 1,
            snippet=snippet,
            declared_display=_has_display_decl(lines, idx),
        )
        order.append(key)

    for idx, line in enumerate(lines):
        # 模式 1/2：token 扫描
        for tok in _TOKEN_RE.findall(line):
            low_tok = tok.lower()
            has_sep = "-" in tok or "_" in tok
            if has_sep:
                _register(tok, idx)
            elif _bare_keyword(low_tok):
                # 裸关键词（button/cards/href/link 等）：中文 SPEC 中的英文 token
                # 几乎均为组件/字段标识，直接视为候选
                _register(tok, idx)

        # 模式 3：cards 渲染循环
        if _CARDS_LOOP_RE.search(line):
            _register("cards", idx)

        # 模式 4：href/link 字段
        m = _HREF_FIELD_RE.search(line)
        if m:
            _register(m.group(1).lower(), idx)

    # 去重：SPEC 已识别出具体卡片 token（dark-Card--link 等）时，泛化 "cards"
    # 候选与它是同一元素族，不再单列
    if "cards" in found and any(k != "cards" and _primary_keyword(k) == "card" for k in found):
        del found["cards"]
        order.remove("cards")

    return [found[k] for k in order]


def collect_spec_candidates(project_root, spec_name: str) -> List[InteractiveCandidate]:
    """收集 SPEC 全部文档（proposal/design/tasks/specs）中的可交互候选。

    读取失败/文档缺失时返回空列表（不抛出）。
    """
    base = Path(project_root) / "spec" / "changes" / spec_name
    paths: List[Path] = []
    for name in ("proposal.md", "design.md", "tasks.md"):
        p = base / name
        if p.exists():
            paths.append(p)
    specs_dir = base / "specs"
    if specs_dir.is_dir():
        for p in sorted(specs_dir.rglob("*.md")):
            paths.append(p)

    found: Dict[str, InteractiveCandidate] = {}
    order: List[str] = []
    for p in paths:
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        try:
            rel = str(p.relative_to(project_root))
        except ValueError:
            rel = str(p)
        for cand in extract_candidates(text, source=rel):
            if cand.key in found:
                # 同一元素多处出现：任一处声明纯展示即视为已声明
                if cand.declared_display:
                    found[cand.key].declared_display = True
                continue
            found[cand.key] = cand
            order.append(cand.key)
    return [found[k] for k in order]


# ── 场景侧：覆盖与声明 ──────────────────────────────────────────────


def scenario_text_blob(scenario: Any) -> str:
    """把场景对象的可检索文本拼为单一小写串（id/description/covers/steps/assertions）。"""
    if not isinstance(scenario, dict):
        return ""
    parts: List[str] = []
    for key in ("id", "description"):
        val = scenario.get(key)
        if isinstance(val, str):
            parts.append(val)
    covers = scenario.get("covers")
    if isinstance(covers, list):
        parts.extend(str(c) for c in covers)
    declared = scenario.get("declared_display")
    if isinstance(declared, list):
        parts.extend(str(c) for c in declared)
    for group in ("steps", "assertions"):
        items = scenario.get(group)
        if isinstance(items, list):
            for it in items:
                if isinstance(it, dict):
                    for key in (
                        "target",
                        "selector",
                        "label",
                        "expected",
                        "actual",
                        "message",
                        "description",
                        "value",
                    ):
                        val = it.get(key)
                        if isinstance(val, str):
                            parts.append(val)
                elif isinstance(it, str):
                    parts.append(it)
    return " ".join(parts).lower()


def _covers_list(scenario: Any) -> List[str]:
    covers = scenario.get("covers") if isinstance(scenario, dict) else None
    if not isinstance(covers, list):
        return []
    return [normalize_token(str(c)) for c in covers if c]


def scenario_cover_channel(scenario: Any, candidate: InteractiveCandidate) -> int:
    """场景覆盖候选所用的通道号（0=未覆盖，1/2/3 见模块 docstring 三通道）。"""
    blob = scenario_text_blob(scenario)
    if not blob:
        return 0
    # 通道 1：planner 显式登记 covers
    covers = _covers_list(scenario)
    if candidate.key in covers or normalize_token(candidate.raw) in covers:
        return 1
    # 通道 2：候选标识（原文/归一化）作为独立 token 出现在场景文本。
    # 边界排除字母/数字而非裸子串：card 不得命中 discard、link 不得命中
    # hyperlink 这类嵌入式假覆盖；连字符/下划线是词内连接符（dark-card--link、
    # btn_submit 对 card/btn 的引用仍算命中，不误杀既有合法覆盖）。
    for term in dict.fromkeys((candidate.raw.lower(), candidate.key)):
        if term and re.search(
            r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", blob
        ):
            return 2
    # 通道 3：主语义关键词别名（中文表述同一元素）
    primary = _primary_keyword(candidate.key)
    if primary:
        for alias in KEYWORD_ALIASES.get(primary, ()):
            if alias in blob:
                return 3
    return 0


def scenario_covers(scenario: Any, candidate: InteractiveCandidate) -> bool:
    """场景是否覆盖该候选（三通道，见模块 docstring）。"""
    return scenario_cover_channel(scenario, candidate) != 0


def collect_display_declarations(planner_scenarios: Any) -> List[str]:
    """收集 planner 产出中登记的纯展示声明（场景对象 ``declared_display``）。"""
    declared: List[str] = []
    for s in planner_scenarios or []:
        if not isinstance(s, dict):
            continue
        items = s.get("declared_display")
        if isinstance(items, list):
            for it in items:
                key = normalize_token(str(it))
                if key and key not in declared:
                    declared.append(key)
    return declared


# ── 遗留集判定（design D2：旧场景集不追溯）─────────────────────────


def is_legacy_scenario_set(scenario_set: Any) -> bool:
    """持久化场景集是否为「无契约元数据」的遗留集。

    存在且所有条目均无 ``covers`` 元数据、且集级无纯展示声明 → 遗留集，
    跳过强制（仅新验证轮生效）。
    """
    if scenario_set is None:
        return False
    entries = getattr(scenario_set, "scenarios", None)
    if not entries:
        return False
    if any(getattr(e, "covers", None) for e in entries):
        return False
    declared = getattr(scenario_set, "display_declarations", None)
    if declared:
        return False
    return True


# ── 校验入口（pm_engine 场景执行前调用）────────────────────────────


def validate_interaction_coverage(
    project_root, spec_name: str, planner_scenarios: Any, persisted_set: Any = None
) -> ContractResult:
    """校验场景集对可交互候选的覆盖（design D1/D2）。

    Args:
        project_root: 项目根（读取 SPEC 文档）。
        spec_name: SPEC 名。
        planner_scenarios: planner 产出场景列表（dict 列表）。
        persisted_set: 持久化场景集（ScenarioSet）——遗留集时跳过强制（D2）。

    Returns:
        ContractResult：ok=False 表示覆盖不完整（调用方要求 planner 补齐）。
    """
    result = ContractResult()
    result.candidates = collect_spec_candidates(project_root, spec_name)
    if not result.has_candidates:
        result.ok = True
        result.change_lines.append("- 未检出可交互候选元素，交互契约无强制项")
        return result

    if persisted_set is not None and is_legacy_scenario_set(persisted_set):
        # design D2：旧场景集（无元数据）不追溯，仅新验证轮生效
        result.skipped = True
        result.ok = True
        result.change_lines.append(
            f"- 持久化场景集为无契约元数据的遗留集（{len(result.candidates)} 个"
            f"候选不追溯），本轮跳过交互契约强制"
        )
        return result

    declared = set(collect_display_declarations(planner_scenarios))
    scenarios = [s for s in (planner_scenarios or []) if isinstance(s, dict)]

    for cand in result.candidates:
        if cand.declared_display or cand.key in declared:
            result.declared.append(cand.key)
            result.change_lines.append(
                f"- 元素 {cand.key}（{cand.source}:{cand.line}）声明纯展示，" f"豁免交互场景"
            )
            continue
        covering = []
        for s in scenarios:
            ch = scenario_cover_channel(s, cand)
            if ch:
                covering.append((str(s.get("id") or "?"), ch))
        if covering:
            ids = [cid for cid, _ in covering]
            result.covered.append((cand.key, ids))
            line = f"- 元素 {cand.key} 由场景 {'、'.join(ids)} 覆盖"
            # code-review 9394c470cf26：通道三为裸子串别名匹配（场景文本任意
            # 位置出现「点击/卡片」等中文词即命中），属有意的宽松通道；仅靠
            # 它判覆盖时在留痕行标注弱证据供人工复核（不改变放行结果）。
            if all(ch == 3 for _, ch in covering):
                line += "（弱证据：仅靠关键词别名命中，无 covers 登记或元素标识原文）"
            result.change_lines.append(line)
        else:
            result.uncovered.append(cand.key)
            result.change_lines.append(
                f"- ⚠️ 元素 {cand.key}（{cand.source}:{cand.line}）既无交互场景"
                f"覆盖也无纯展示声明"
            )

    result.ok = not result.uncovered
    return result


# ── 反馈渲染（复用场景验收退回 plan 的反馈机制）────────────────────


def build_replan_feedback(result: ContractResult) -> str:
    """把覆盖不完整结论渲染为 REPLAN_FEEDBACK 文本（要求 planner 补齐）。"""
    lines = [
        "## 交互契约覆盖不完整（add-interaction-contract-and-per-assert-triage）",
        "",
        "以下可交互元素既无交互场景覆盖也无纯展示声明，必须补齐后重新输出全部场景：",
        "",
    ]
    for key in result.uncovered:
        cand = next((c for c in result.candidates if c.key == key), None)
        if cand is not None:
            lines.append(
                f"- `{cand.raw}`（{cand.source}:{cand.line}）：补一个覆盖该元素"
                f"交互行为的场景（点击/操作后的可观察结果断言，并在场景对象上"
                f'用 "covers": ["{cand.raw}"] 登记）；或确认其纯展示——在场景'
                f'对象上用 "declared_display": ["{cand.raw}"] 声明'
            )
        else:
            lines.append(f"- `{key}`：补交互场景或声明纯展示")
    lines.append("")
    lines.append("注意：修复轮不得扩容场景面时，用 `declared_display` 声明纯展示即可合规。")
    return "\n".join(lines)


def load_planner_scenarios(scenarios_path: Path) -> Optional[list]:
    """读取 test_scenarios.json 的场景列表；不可用返回 None（不抛出）。"""
    if not scenarios_path.exists():
        return None
    try:
        data = json.loads(scenarios_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, list):
        return None
    return data
