"""
verify_scenarios.py — 验证场景集持久化与受控增量（add-verify-scenario-freeze）。

把「验证场景集（scenario_id 列表）」跨轮稳定下来：

  - 首轮验证裁决产出场景集时，持久化到
    ``.fenix/verify-progress/<spec>/scenarios.json``；已有该文件时 MUST NOT
    无条件覆盖（design D1：走 diff 流程）。
  - 修复轮验证默认复用持久化集；仅当修复段（tasks.md「## 验证修复」）声明了
    新增交付范围时，planner 才允许为**新增范围**追加场景（spec 需求
    ``verify-scenario-freeze``）。
  - planner 产出与持久化集 diff：只增 scenario_id 时合并写回（记录轮次）；
    删减既有场景 MUST 提供理由，无理由的缺场景按 planner 输出不完整处理——
    以持久化集补齐缺失场景后继续（不中断验证）。

确定性与纯 Python（design D3）：planner 无法通过输出文本绕过——diff 校验读取
planner 输出 JSON + scenarios.json + 修复段文本，写回 scenarios.json 只在校验
通过后发生。

scenarios.json 结构（含来源轮次，便于增量审计）::

    {
      "spec": "<spec>",
      "round": <int>,                       # 当前场景集稳定时的验证轮次
      "display_declarations": ["btn-x"],    # 交互契约纯展示声明（add-interaction-contract）
      "scenarios": [
        {"id": "sc-1", "description": "...", "added_in_round": 1,
         "covers": ["dark-Card--link"]},    # 交互契约：场景覆盖的可交互元素
        ...
      ]
    }
"""

import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Optional

# 可传播到 fenixd 已挂载 handler 的结构化日志器（fix-robustness-edge-cases 3.1：
# 收敛旁路裸 getLogger("pm_engine")，保证 WARNING 落入 fenixd.log）
_logger = logging.getLogger("fenixd.verify_scenarios")

# tasks.md 修复段标题正则（与 pm_engine._VERIFY_FIX_SECTION_RE 同源）
_VERIFY_FIX_SECTION_RE = re.compile(r"^## 验证修复\b.*$", re.MULTILINE)

# 修复段中声明「新增交付范围」的匹配：带「新增」字样且非纯修复的条目。
# 设计 D2：仅当修复段声明了新增交付时，planner 才允许为该范围追加场景。
_NEW_DELIVERY_RE = re.compile(
    r"(新增|追加|增加).{0,12}?(交付|范围|功能|场景|支持|能力|特性|页面|模块)",
    re.MULTILINE,
)

# 修复语境短语（bcb05f957b2d）：动词后紧跟「对 … 的修复」＝对既有场景的
# 修复而非新增交付声明；限定同条款内（不含句读/换行）防跨句误排除。
_REPAIR_PHRASE_RE = re.compile(r"对[^，。；\n]{0,60}的修复")


# ── 数据结构 ────────────────────────────────────────────────────────


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _int_or(value, default: int) -> int:
    """字段级 int 兜底（code-review 062e920431bc）：非数字值（int 抛
    ValueError/TypeError）回退 ``default``，防单条坏数值字段把整个冻结集
    加载降级为 None、被 diff 按「无持久化集」全量替换。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class ScenarioEntry:
    """持久化集中的单个场景记录。

    ``covers``：交互契约元数据（add-interaction-contract-and-per-assert-triage
    D2）——本场景覆盖的可交互元素标识列表；旧集无此字段（缺省空表，不追溯）。
    ``kind``：场景 kind（web/cli/api，缺省 web）——可选字段，补齐全集用于
    正确 Runner 执行（multi-kind-report-compat：冻结集补齐/合并携带 kind）。
    """

    __slots__ = ("id", "description", "added_in_round", "covers", "kind")

    def __init__(
        self,
        id: str,
        description: str = "",
        added_in_round: int = 1,
        covers: Optional[list] = None,
        kind: str = "web",
    ):
        self.id = id
        self.description = description
        self.added_in_round = added_in_round
        self.covers = [str(c) for c in (covers or [])]
        self.kind = str(kind or "web")

    def to_dict(self) -> dict:
        d = {"id": self.id, "description": self.description, "added_in_round": self.added_in_round}
        if self.covers:
            d["covers"] = list(self.covers)
        # fix-frozen-scenario-orphan-reservoir D1/D4：kind 恒定写入——写端 schema
        # 门保证每条目均有合法 kind；加载侧对存量缺 kind 条目兜底归类 web
        # 保留在集（b25b28a4ed8a：剔除会把不再整档重写的存量冻结集清成空集）。
        d["kind"] = self.kind
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ScenarioEntry":
        covers = d.get("covers")
        return cls(
            id=d.get("id", ""),
            description=d.get("description", ""),
            added_in_round=_int_or(d.get("added_in_round", 1) or 1, 1),
            covers=covers if isinstance(covers, list) else None,
            kind=d.get("kind", "web"),
        )


class ScenarioSet:
    """验证场景集：spec + 稳定轮次 + 场景列表。

    ``display_declarations``：交互契约纯展示声明登记（元素标识列表，D2 可审计）。
    """

    def __init__(
        self,
        spec: str,
        round_: int = 1,
        scenarios: Optional[list] = None,
        display_declarations: Optional[list] = None,
    ):
        self.spec = spec
        self.round = round_
        self.scenarios: list[ScenarioEntry] = list(scenarios or [])
        self.display_declarations = [str(d) for d in (display_declarations or [])]

    @property
    def ids(self) -> set:
        return {s.id for s in self.scenarios}

    def to_dict(self) -> dict:
        d = {
            "spec": self.spec,
            "round": self.round,
            "updated_at": _now_iso(),
            "scenarios": [s.to_dict() for s in self.scenarios],
        }
        if self.display_declarations:
            d["display_declarations"] = list(self.display_declarations)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ScenarioSet":
        if not isinstance(d, dict):
            return cls(spec="", round=1)
        declared = d.get("display_declarations")
        return cls(
            spec=d.get("spec", ""),
            round_=_int_or(d.get("round", 1) or 1, 1),
            scenarios=[ScenarioEntry.from_dict(s) for s in d.get("scenarios", [])],
            display_declarations=declared if isinstance(declared, list) else None,
        )


# ── 路径与读写 ──────────────────────────────────────────────────────


def scenarios_path_for(project_root, spec_name: str) -> Path:
    """返回 ``.fenix/verify-progress/<spec>/scenarios.json`` 绝对路径。"""
    return Path(project_root) / ".fenix" / "verify-progress" / spec_name / "scenarios.json"


def load_scenario_set(project_root, spec_name: str) -> Optional[ScenarioSet]:
    """读取持久化场景集；文件缺失/损坏返回 None（不抛出）。

    加载净化（fix-frozen-scenario-orphan-reservoir D4，code-review
    b25b28a4ed8a 修正）：非对象条目剔除；缺/非法 ``kind`` 的条目**兜底归类
    web 保留在集中，不再剔除**——剔除会让先于 kind 字段落盘、不再整档重写
    的存量冻结集加载成空集，diff 把 planner 重出场景全按新增处理、修复轮
    被超发拦截后以空集写回（冻结场景集被静默清零）。兜底只影响内存集合，
    不改写 scenarios.json 文件；planner 产出携带合法 kind 时仍由 diff 侧
    刷新为正确值。
    """
    path = scenarios_path_for(project_root, spec_name)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    raw_entries = data.get("scenarios")
    if isinstance(raw_entries, list):
        kept: list = []
        rejected: list[str] = []
        backfilled: list[str] = []
        for item in raw_entries:
            if not isinstance(item, dict):
                rejected.append(f"[{len(kept)}]非对象")
                continue
            if item.get("kind") not in ("web", "cli", "api"):
                # b25b28a4ed8a：缺/非法 kind 兜底归类 web 保留在集（不再剔除，
                # 防存量无 kind 冻结集被清成空集后写回）；不写回文件。
                backfilled.append(str(item.get("id") or "?"))
                item = {**item, "kind": "web"}
            kept.append(item)
        if backfilled:
            _logger.warning(
                "持久化集加载净化：%d 条缺/非法 kind 条目兜底归类 web 保留在集"
                "（scenarios.json 文件不改写，diff 侧合法 kind 仍可刷新）: %s",
                len(backfilled),
                "、".join(backfilled),
            )
        if rejected:
            _logger.warning(
                "持久化集加载净化剔除 %d 条非对象孤儿条目"
                "（scenarios.json 文件不改写，仅内存集合净化）: %s",
                len(rejected),
                "、".join(rejected),
            )
        if backfilled or rejected:
            data = {**data, "scenarios": kept}
    try:
        return ScenarioSet.from_dict(data)
    except (ValueError, TypeError, AttributeError):
        # 数值字段已字段级兜底（_int_or，非数字回退 1，不再到此处）；残剩
        # 损坏形态如 scenarios 为非列表标量（对字符调 .get 抛 AttributeError）：
        # 按「损坏返回 None」契约降级，不向调用方上抛中断验证流程
        return None


def _atomic_write(path: Path, data: dict) -> None:
    """原子写：临时文件写好后 rename 覆盖，避免半写文件（design D1 原子写）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp", prefix=".scenarios-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            f.truncate()
            os.fsync(f.fileno())
        Path(tmp_name).replace(path)
    finally:
        try:
            if Path(tmp_name).exists():
                Path(tmp_name).unlink()
        except OSError:
            pass


# ── 持久化集条目结构校验（fix-frozen-scenario-orphan-reservoir D1/D4）────


def validate_scenario_entries(entry_dicts: list) -> list[str]:
    """持久化集条目（'scenarios.json' 的 dict 列表）结构校验。

    scenarios.json 的 ScenarioEntry 与 test_scenarios.json 的 TestScenario
    形态不同（无 steps/assertions），无法直接复用 ``validate_scenario_dicts``；
    这里对 ScenarioEntry 形态做等价的结构校验——**每条 MUST 有合法 kind**
    （无 kind 无法路由到任何 Runner＝孤儿，储库复活根因）。返回错误清单，
    空列表表示全部合法；本函数不抛异常。
    """
    errors: list[str] = []
    if not isinstance(entry_dicts, list):
        return [f"场景集数据格式错误: 期望数组，实际为 {type(entry_dicts).__name__}"]
    for i, item in enumerate(entry_dicts):
        if not isinstance(item, dict):
            errors.append(f"场景集条目[{i}]解析失败: 期望对象，" f"实际为 {type(item).__name__}")
            continue
        sid = item.get("id") or f"[{i}]"
        kind = item.get("kind")
        if kind not in ("web", "cli", "api"):
            errors.append(
                f"场景集条目 '{sid}' 缺少合法 kind（收到 {kind!r}），"
                f"无法路由到 Runner，属孤儿条目"
            )
    return errors


def save_scenario_set(project_root, scenario_set: ScenarioSet) -> Path:
    """持久化场景集（原子写）。返回写入路径。

    写端 schema 门（fix-frozen-scenario-orphan-reservoir D1/D2）：写回前对
    ScenarioEntry 列表做结构校验，非法条目（如缺 kind 的孤儿）剔除并留痕，
    合法部分照常落盘——不整批拒绝（避免单条坏数据放大成整轮验证无法进行）。
    非 ScenarioEntry 条目按校验失败剔除留痕（2eaebbf39624：原 ``dict(e)``
    伪兜底转换出的裸 dict 无 ``to_dict``、写回阶段必崩，契约外类型不转换）。
    """
    clean_entries: list[ScenarioEntry] = []
    rejected: list[str] = []
    for e in scenario_set.scenarios:
        if not isinstance(e, ScenarioEntry):
            eid = e.get("id") if isinstance(e, dict) else getattr(e, "id", None)
            rejected.append(f"{eid or '?'}（期望 ScenarioEntry，实际为 {type(e).__name__}）")
            continue
        d = {
            "id": e.id,
            "kind": e.kind,
            "description": e.description,
            "added_in_round": e.added_in_round,
        }
        errs = validate_scenario_entries([d])
        if errs:
            rejected.append(f"{d.get('id') or '?'}（{'；'.join(errs)}）")
            continue
        clean_entries.append(e)

    if rejected:
        _logger.warning(
            "场景集写端校验剔除 %d 个非法条目（scenarios.json 不落盘）: %s",
            len(rejected),
            "、".join(rejected),
        )
    scenario_set.scenarios = clean_entries
    path = scenarios_path_for(project_root, scenario_set.spec)
    _atomic_write(path, scenario_set.to_dict())
    return path


# ── 修复段解析（design D2：新增交付范围判定）────────────────────────


def read_verify_fix_section(project_root, spec_name: str) -> Optional[str]:
    """读取 tasks.md 的「## 验证修复」段全文；不存在返回 None。"""
    tasks_path = Path(project_root) / "spec" / "changes" / spec_name / "tasks.md"
    if not tasks_path.exists():
        return None
    try:
        text = tasks_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    m = _VERIFY_FIX_SECTION_RE.search(text)
    if not m:
        return None
    after = text[m.end() :]
    nxt = re.search(r"\n## [^\n]", after)
    end = m.end() + nxt.start() if nxt else len(text)
    return text[m.start() : end]


def declares_new_delivery(fix_section: Optional[str], notes: Optional[list] = None) -> bool:
    """修复段是否声明了「新增交付范围」。

    仅当修复段存在且含「新增/追加/增加 … 交付/范围/功能/能力…」时才允许追加。
    纯修复（无新增范围）返回 False，planner 不得扩容。动词后紧跟
    「对 … 的修复」短语的命中按修复语境排除、不计入新增交付声明
    （bcb05f957b2d：如「追加对场景 X 的修复」），排除时向 ``notes``
    （若提供）追加留痕行供审计。
    """
    if not fix_section:
        return False
    for m in _NEW_DELIVERY_RE.finditer(fix_section):
        if _REPAIR_PHRASE_RE.match(fix_section, m.end(1)):
            if notes is not None:
                line_start = fix_section.rfind("\n", 0, m.start()) + 1
                line_end = fix_section.find("\n", m.end())
                if line_end == -1:
                    line_end = len(fix_section)
                excerpt = fix_section[line_start:line_end].strip()[:60]
                notes.append(
                    f"- 「{excerpt}」命中新增交付词形但属修复语境"
                    f"（对…的修复），该处不计入新增交付声明"
                )
            continue
        return True
    return False


# ── 修复轮判定（design D1）─────────────────────────────────────────


def is_repair_round(project_root, spec_name: str, state: Optional[dict]) -> bool:
    """判定是否为修复轮。

    D1 信号（与原地打回机制同源，不引入新状态）：
      - STATE.md ``_verify_fail_rounds > 0``，或
      - tasks.md 含「## 验证修复」段。
    """
    entry = state or {}
    try:
        fail_rounds = int(entry.get("_verify_fail_rounds", 0) or 0)
    except (TypeError, ValueError):
        fail_rounds = 0
    if fail_rounds > 0:
        return True
    return read_verify_fix_section(project_root, spec_name) is not None


# ── 确定性 diff 校验器（design D3：planner 不可绕过）─────────────────


class DiffResult:
    """planner 产出 vs 持久化集的 diff 结论。

    Attributes:
        ok: 校验是否通过（通过＝可写回；不通过＝以持久化集补齐后继续）。
        scenario_set: 校验后应采用的最终场景集（通过时＝合并结果；
            不通过时＝以持久化集补齐缺失场景后的集）。
        added: 本轮新增的 ScenarioEntry 列表（仅新增范围合法追加）。
        removed: 本轮被移除的 (ScenarioEntry, reason) 列表（有理由删减）。
        unreasoned_missing: 无理由缺失的 ScenarioEntry 列表（被补齐）。
        change_lines: 「本轮场景集变更」小节渲染用的行（人类可读）。
        extended: 是否声明了新增交付范围（允许追加）。
    """

    def __init__(self):
        self.ok = True
        self.scenario_set: Optional[ScenarioSet] = None
        self.added: list[ScenarioEntry] = []
        self.removed: list = []  # (ScenarioEntry, reason)
        self.unreasoned_missing: list[ScenarioEntry] = []
        self.change_lines: list[str] = []
        self.extended = False


def _parse_reasons(planner_scenarios: list) -> dict:
    """从 planner 产出中提取每个场景的「移除理由」。

    planner 可在场景对象上用 ``remove_reason`` 字段声明移除理由（设计 D2：
    删减既有场景 MUST 提供理由）。无该字段视为无理由。
    """
    reasons = {}
    for s in planner_scenarios:
        if not isinstance(s, dict):
            continue
        sid = s.get("id")
        if sid and s.get("remove_reason"):
            reasons[sid] = str(s["remove_reason"])
    return reasons


def _covers_of(scenario: dict) -> list:
    """场景对象的交互契约 ``covers`` 元数据（非列表时缺省空表）。"""
    covers = scenario.get("covers") if isinstance(scenario, dict) else None
    if not isinstance(covers, list):
        return []
    return [str(c) for c in covers if c]


def _kind_of(scenario: dict) -> str:
    """场景对象的 kind（multi-kind-report-compat：冻结条目携带 kind，
    读侧缺失缺省 web，存量冻结文件零迁移）。"""
    kind = scenario.get("kind") if isinstance(scenario, dict) else None
    if kind not in ("web", "cli", "api"):
        return "web"
    return str(kind)


def _legal_kind_of(scenario: dict) -> Optional[str]:
    """场景对象的 kind，仅当为合法值（web/cli/api）时返回；缺失/非法返回
    None（17250417a111：供既有条目保留冻结原值，不缺省改写 web）。"""
    kind = scenario.get("kind") if isinstance(scenario, dict) else None
    if kind not in ("web", "cli", "api"):
        return None
    return str(kind)


def _display_declarations_of(planner_scenarios: list) -> list:
    """planner 产出中登记的纯展示声明（D2：declared-display 登记进元数据）。"""
    from core.interaction_contract import collect_display_declarations

    return collect_display_declarations(planner_scenarios)


def diff_planner_output(
    project_root, spec_name: str, state: Optional[dict], planner_scenarios: list, current_round: int
) -> DiffResult:
    """确定性 diff 校验：planner 产出 vs 持久化集。

    Args:
        project_root: 项目根（用于读取修复段 / 持久化集）。
        spec_name: SPEC 名。
        state: STATE.md 中该 spec 的 entry（含 ``_verify_fail_rounds``）。
        planner_scenarios: planner-plan 产出的场景列表（dict 列表，可含
            ``id`` / ``description`` / ``remove_reason``）。
        current_round: 本轮验证轮次（用于记录 added_in_round）。

    Returns:
        DiffResult：含校验结论与应写回的场景集。
    """
    result = DiffResult()
    persisted = load_scenario_set(project_root, spec_name)
    fix_section = read_verify_fix_section(project_root, spec_name)
    result.extended = declares_new_delivery(fix_section, notes=result.change_lines)
    repair = is_repair_round(project_root, spec_name, state)

    # ── 首轮 / 无持久化集：直接采用 planner 产出，全量写回 ──
    if persisted is None:
        entries = [
            ScenarioEntry(
                id=str(s["id"]),
                description=str(s.get("description", "")),
                added_in_round=current_round,
                covers=_covers_of(s),
                kind=_kind_of(s),
            )
            for s in planner_scenarios
            if isinstance(s, dict) and s.get("id")
        ]
        result.scenario_set = ScenarioSet(
            spec_name,
            current_round,
            entries,
            display_declarations=_display_declarations_of(planner_scenarios),
        )
        result.added = list(entries)
        # append 而非整体重赋值：保留 declares_new_delivery 已写入的
        # 修复语境审计留痕行（与有持久化集分支行为一致）。
        result.change_lines.append(f"- 首轮写入 {len(entries)} 个场景")
        return result

    persisted_ids = persisted.ids
    reasons = _parse_reasons(planner_scenarios)

    # planner 产出的「保留/新增」场景（非移除项）
    planner_ids = set()
    planner_by_id = {}
    for s in planner_scenarios:
        if not isinstance(s, dict) or not s.get("id"):
            continue
        sid = str(s["id"])
        if sid in reasons:
            continue  # 该场景被 planner 显式移除（带理由）
        planner_ids.add(sid)
        planner_by_id[sid] = s

    # 交互契约元数据（D2）：既有条目的 covers 以 planner 本轮产出为准刷新
    # （场景重排后映射可能变化），新增条目直接携带。kind 仅在 planner 产出
    # 携带合法 kind（web/cli/api）时才刷新；缺失/非法保留冻结文件原值
    # （17250417a111：避免 planner 漏给 kind 时 cli/api 冻结条目被无声改写
    # 为 web、下一轮路由到错误 Runner）。仅冻结原值为 cli/api（保留与缺省
    # web 刷新会产生真实分叉、有误路由风险）时记 change_lines 留痕供审计；
    # 原值 web/缺省场景保留即无操作，静默不计变更。
    kept_kind_ids: list[str] = []
    for e in persisted.scenarios:
        s = planner_by_id.get(e.id)
        if s is not None:
            e.covers = _covers_of(s)
            legal = _legal_kind_of(s)
            if legal is not None:
                e.kind = legal
            elif e.kind in ("cli", "api"):
                kept_kind_ids.append(e.id)
    if kept_kind_ids:
        result.change_lines.append(
            f"- {len(kept_kind_ids)} 个既有条目的 kind 保留冻结文件原值"
            f"（planner 产出缺合法 kind）：{'、'.join(kept_kind_ids)}"
        )

    # ── 删减检测：持久化集有、planner 没有 ──
    missing = [e for e in persisted.scenarios if e.id not in planner_ids]
    unreasoned = [e for e in missing if not reasons.get(e.id)]
    reasoned = [(e, reasons[e.id]) for e in missing if reasons.get(e.id)]

    result.removed = reasoned
    result.unreasoned_missing = unreasoned

    # ── 新增检测：planner 有、持久化集没有 ──
    # 默认保留全部既有，但排除有理由移除的场景（scenarios.json 同步移除）。
    removed_ids = {e.id for e, _ in reasoned}
    kept_entries = [e for e in persisted.scenarios if e.id not in removed_ids]
    new_entries = []
    # 按 sid 排序遍历：set 迭代序随 PYTHONHASHSEED 跨进程抖动，违背模块 D3 确定性
    for sid in sorted(planner_ids):
        if sid in persisted_ids:
            continue
        s = planner_by_id[sid]
        new_entries.append(
            ScenarioEntry(
                id=sid,
                description=str(s.get("description", "")),
                added_in_round=current_round,
                covers=_covers_of(s),
                kind=_kind_of(s),
            )
        )

    # ── 受控增量约束（design D2）──
    # 修复轮且未声明新增交付：任何新增均属「超发」，必须拦截（spec：修复轮不扩容）。
    # 非修复轮（首轮之后重新规划）允许新增但需走 diff 记录。
    if new_entries and not result.extended:
        # 合法追加：合并写回（design D2：新增范围允许追加；此处按修复轮判断）。
        # 若修复轮且未声明新增交付，则拦截超发，本批新增被丢弃（仅保留既有集）。
        if repair:
            overcount = len(new_entries)
            new_entries = []
            result.change_lines.append(
                f"- 拦截 planner 超发 {overcount} 个未声明新增范围的场景"
                f"（修复轮不扩容，按 D2 丢弃）"
            )

    final_entries = kept_entries + new_entries
    result.scenario_set = ScenarioSet(
        spec_name,
        current_round,
        final_entries,
        display_declarations=_display_declarations_of(planner_scenarios),
    )
    result.added = new_entries

    # ── 无理由缺场景 → 校验失败，以持久化集补齐后继续（不中断验证）──
    if unreasoned:
        result.ok = False
        result.change_lines.append(
            f"- 无理由缺失 {len(unreasoned)} 个场景，已以持久化集补齐："
            + "、".join(e.id for e in unreasoned)
        )
        # 补齐：final_entries 已含全部既有（kept_entries），无需额外操作；
        # 但 ok=False 标记「本轮验证以持久化集补齐缺失场景后继续」。
    else:
        result.ok = True

    # ── 有理由删减留痕 ──
    for e, reason in reasoned:
        result.change_lines.append(f"- 移除场景 {e.id}（理由：{reason}）")

    # ── 合法新增记录 ──
    for e in new_entries:
        scope = "新增范围" if result.extended else "重新规划"
        result.change_lines.append(f"- 新增场景 {e.id}（{scope}，第 {current_round} 轮）")

    return result


# ── 报告渲染（spec 需求 2.3：本轮场景集变更小节）────────────────────


def render_change_section(diff: DiffResult) -> str:
    """把 diff 结论渲染为验证报告的「本轮场景集变更」小节（Markdown）。"""
    if diff is None:
        return ""
    lines = ["", "## 本轮场景集变更", ""]
    if not diff.change_lines:
        lines.append("场景集与持久化集一致，无变更。")
        lines.append("")
        return "\n".join(lines)
    if diff.scenario_set is not None:
        lines.append(
            f"当前稳定场景集共 {len(diff.scenario_set.scenarios)} 个"
            f"（第 {diff.scenario_set.round} 轮）。"
        )
    lines.append("")
    for cl in diff.change_lines:
        lines.append(cl)
    if not diff.ok:
        lines.append("")
        lines.append(
            "> ⚠️ 本轮 planner 产出缺少既有场景且无理由，已以持久化集补齐后继续验证"
            "（不中断验证）。"
        )
    lines.append("")
    return "\n".join(lines)


def render_first_write_section(scenario_set: ScenarioSet) -> str:
    """首轮写入的「本轮场景集变更」小节渲染。"""
    diff = DiffResult()
    diff.scenario_set = scenario_set
    diff.change_lines = [f"首轮写入 {len(scenario_set.scenarios)} 个场景"]
    return render_change_section(diff)
