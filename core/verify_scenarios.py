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
      "scenarios": [
        {"id": "sc-1", "description": "...", "added_in_round": 1},
        ...
      ]
    }
"""

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Optional

# tasks.md 修复段标题正则（与 pm_engine._VERIFY_FIX_SECTION_RE 同源）
_VERIFY_FIX_SECTION_RE = re.compile(r"^## 验证修复\b.*$", re.MULTILINE)

# 修复段中声明「新增交付范围」的匹配：带「新增」字样且非纯修复的条目。
# 设计 D2：仅当修复段声明了新增交付时，planner 才允许为该范围追加场景。
_NEW_DELIVERY_RE = re.compile(
    r"(新增|追加|增加).{0,12}?(交付|范围|功能|场景|支持|能力|特性|页面|模块)",
    re.MULTILINE,
)


# ── 数据结构 ────────────────────────────────────────────────────────

def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ScenarioEntry:
    """持久化集中的单个场景记录。"""

    __slots__ = ("id", "description", "added_in_round")

    def __init__(self, id: str, description: str = "", added_in_round: int = 1):
        self.id = id
        self.description = description
        self.added_in_round = added_in_round

    def to_dict(self) -> dict:
        d = {"id": self.id, "description": self.description,
             "added_in_round": self.added_in_round}
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ScenarioEntry":
        return cls(
            id=d.get("id", ""),
            description=d.get("description", ""),
            added_in_round=int(d.get("added_in_round", 1) or 1),
        )


class ScenarioSet:
    """验证场景集：spec + 稳定轮次 + 场景列表。"""

    def __init__(self, spec: str, round_: int = 1,
                 scenarios: Optional[list] = None):
        self.spec = spec
        self.round = round_
        self.scenarios: list[ScenarioEntry] = list(scenarios or [])

    @property
    def ids(self) -> set:
        return {s.id for s in self.scenarios}

    def to_dict(self) -> dict:
        return {
            "spec": self.spec,
            "round": self.round,
            "updated_at": _now_iso(),
            "scenarios": [s.to_dict() for s in self.scenarios],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ScenarioSet":
        if not isinstance(d, dict):
            return cls(spec="", round=1)
        return cls(
            spec=d.get("spec", ""),
            round_=int(d.get("round", 1) or 1),
            scenarios=[ScenarioEntry.from_dict(s) for s in d.get("scenarios", [])],
        )


# ── 路径与读写 ──────────────────────────────────────────────────────

def scenarios_path_for(project_root, spec_name: str) -> Path:
    """返回 ``.fenix/verify-progress/<spec>/scenarios.json`` 绝对路径。"""
    return (
        Path(project_root) / ".fenix" / "verify-progress"
        / spec_name / "scenarios.json"
    )


def load_scenario_set(project_root, spec_name: str) -> Optional[ScenarioSet]:
    """读取持久化场景集；文件缺失/损坏返回 None（不抛出）。"""
    path = scenarios_path_for(project_root, spec_name)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return ScenarioSet.from_dict(data)


def _atomic_write(path: Path, data: dict) -> None:
    """原子写：临时文件写好后 rename 覆盖，避免半写文件（design D1 原子写）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), suffix=".tmp", prefix=".scenarios-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            f.truncate()
        Path(tmp_name).replace(path)
    finally:
        try:
            if Path(tmp_name).exists():
                Path(tmp_name).unlink()
        except OSError:
            pass


def save_scenario_set(project_root, scenario_set: ScenarioSet) -> Path:
    """持久化场景集（原子写）。返回写入路径。"""
    path = scenarios_path_for(project_root, scenario_set.spec)
    _atomic_write(path, scenario_set.to_dict())
    return path


# ── 修复段解析（design D2：新增交付范围判定）────────────────────────

def read_verify_fix_section(project_root, spec_name: str) -> Optional[str]:
    """读取 tasks.md 的「## 验证修复」段全文；不存在返回 None。"""
    tasks_path = (
        Path(project_root) / "openspec" / "changes" / spec_name / "tasks.md"
    )
    if not tasks_path.exists():
        return None
    try:
        text = tasks_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    m = _VERIFY_FIX_SECTION_RE.search(text)
    if not m:
        return None
    after = text[m.end():]
    nxt = re.search(r"\n## [^\n]", after)
    end = m.end() + nxt.start() if nxt else len(text)
    return text[m.start():end]


def declares_new_delivery(fix_section: Optional[str]) -> bool:
    """修复段是否声明了「新增交付范围」。

    仅当修复段存在且含「新增/追加/增加 … 交付/范围/功能/能力…」时才允许追加。
    纯修复（无新增范围）返回 False，planner 不得扩容。
    """
    if not fix_section:
        return False
    # 排除「修复」语境：含新增交付关键词即视为声明新范围
    return bool(_NEW_DELIVERY_RE.search(fix_section))


# ── 修复轮判定（design D1）─────────────────────────────────────────

def is_repair_round(project_root, spec_name: str,
                    state: Optional[dict]) -> bool:
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


def diff_planner_output(project_root, spec_name: str, state: Optional[dict],
                        planner_scenarios: list, current_round: int) -> DiffResult:
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
    result.extended = declares_new_delivery(fix_section)
    repair = is_repair_round(project_root, spec_name, state)

    # ── 首轮 / 无持久化集：直接采用 planner 产出，全量写回 ──
    if persisted is None:
        entries = [
            ScenarioEntry(id=str(s["id"]), description=str(s.get("description", "")),
                          added_in_round=current_round)
            for s in planner_scenarios
            if isinstance(s, dict) and s.get("id")
        ]
        result.scenario_set = ScenarioSet(spec_name, current_round, entries)
        result.added = list(entries)
        result.change_lines = [
            f"- 首轮写入 {len(entries)} 个场景",
        ]
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

    # ── 删减检测：持久化集有、planner 没有 ──
    missing = [e for e in persisted.scenarios if e.id not in planner_ids]
    unreasoned = [e for e in missing if not reasons.get(e.id)]
    reasoned = [(e, reasons[e.id]) for e in missing if reasons.get(e.id)]

    result.removed = reasoned
    result.unreasoned_missing = unreasoned

    # ── 新增检测：planner 有、持久化集没有 ──
    # 默认保留全部既有，但排除有理由移除的场景（scenarios.json 同步移除）。
    removed_ids = {e.id for e, _ in reasoned}
    added = [e for e in persisted.scenarios if e.id not in removed_ids]
    new_entries = []
    for sid in planner_ids:
        if sid in persisted_ids:
            continue
        s = planner_by_id[sid]
        new_entries.append(ScenarioEntry(
            id=sid, description=str(s.get("description", "")),
            added_in_round=current_round))

    # ── 受控增量约束（design D2）──
    # 修复轮且未声明新增交付：任何新增均属「超发」，必须拦截（spec：修复轮不扩容）。
    # 非修复轮（首轮之后重新规划）允许新增但需走 diff 记录。
    if new_entries and not result.extended:
        # 合法追加：合并写回（design D2：新增范围允许追加；此处按修复轮判断）。
        # 若修复轮且未声明新增交付，则拦截超发，本批新增被丢弃（仅保留既有集）。
        if repair and not result.extended:
            overcount = len(new_entries)
            new_entries = []
            result.change_lines.append(
                f"- 拦截 planner 超发 {overcount} 个未声明新增范围的场景"
                f"（修复轮不扩容，按 D2 丢弃）"
            )

    final_entries = added + new_entries
    result.scenario_set = ScenarioSet(spec_name, current_round, final_entries)
    result.added = new_entries

    # ── 无理由缺场景 → 校验失败，以持久化集补齐后继续（不中断验证）──
    if unreasoned:
        result.ok = False
        result.change_lines.append(
            f"- 无理由缺失 {len(unreasoned)} 个场景，已以持久化集补齐："
            + "、".join(e.id for e in unreasoned)
        )
        # 补齐：final_entries 已含全部既有（added），无需额外操作；
        # 但 ok=False 标记「本轮验证以持久化集补齐缺失场景后继续」。
    else:
        result.ok = True

    # ── 有理由删减留痕 ──
    for e, reason in reasoned:
        result.change_lines.append(
            f"- 移除场景 {e.id}（理由：{reason}）"
        )

    # ── 合法新增记录 ──
    for e in new_entries:
        scope = "新增范围" if result.extended else "重新规划"
        result.change_lines.append(
            f"- 新增场景 {e.id}（{scope}，第 {current_round} 轮）"
        )

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
