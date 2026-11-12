"""scenario_semantics.py — 场景修复语义保持证明器（add-arbiter-blacklist-disposition 2.1）。

Arbiter 救回工具箱 T1（场景鲁棒性修复）的机械门：对修复前后的场景集做
**确定性 diff 三分类**（tighten/relax/neutral），净放宽且未获准正当性码即拒绝。
拒绝 LLM 复核方案（design D2）：机械门必须可复现、可测试、防模型漂移——
不可复现即不可守卫。

判定规则表（spec arbiter-blacklist-disposition「B4 验证契约放宽」机械判别）：

- 期望语义比较：exact/contains → regex = relax（除非该断言附正当性码）；
  exact → contains = relax；contains → exact、regex → exact/contains = tighten；
  regex → regex 以**固定样本语料覆盖面**为代理判定收窄/扩大/改写。
- 删除断言 / 删除场景 = relax（正当性码可豁免——机械闭合不区分豁免语义，
  语义把关由 prompt 禁项段与人工兜底承载）。
- 选择器作用域化（骨架包含旧骨架的锚定范围收紧）、等待时序调整、文案注记
  （引号字面变体）、端口/宿主重绑定 = neutral。
- 断言语义定位字段（json_path/selector/url）变更 = 断言换靶（旧检查点删除
  + 新落点按旧期望）= relax；仅 timeout 等真形态字段变更 = neutral。
- expect_network 守卫差异在成对步骤上一律三分类（含 click/send 等
  非 http_request 步骤）：新增 / 模式包含收紧 = tighten；改写 / 删除 =
  relax（守卫放松即确认面收窄）。
- 场景级编排字段 depends_on：依赖收窄 = relax（前置断言链不再执行，间接
  回归面收窄）；其余场景级标量字段变化维持注记/编排豁免。
- 新增破坏性形态步骤（R1/R3 判定与移除面 carve-out 同源）= relax——B1
  合规化豁免只覆盖移除面，新增面对生产账本的副作用不得绕过证明器。
- 正当性码白名单闭合：``global-counter-nondeterministic``（全局聚合量由
  全部项目实时账本决定，形态断言是唯一稳定语义——知识锚
  ``spec/knowledge/domains/verify-pipeline/scenario-env-coupling.md``）。
- B1 合规化 carve-out：场景 diff 仅由「移除 R1 位置点击改状态 / R3 批量
  破坏确认形态步骤」构成且无新增生产端点 → 整体中性（合规化修复不是
  放宽——把机器人对生产账本的副作用面拆掉正是黑名单制的方向）。

已知边界（宁误拒不误放）：regex 语料代理对不可比覆盖面按 relax 保守拒；
选择器骨架不含旧骨架的重写（如改 testid）按 relax 拒——误拒由 resolved
硬门降级留痕 + 人工兜底承接（design D3 风险登记：多一次人工不损可用性）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# ── 成对落盘契约锚点（与 judge 受理门 judge-repair-scenario-writeback-gate
#    同构：备份与主文件经同一写端归一化盖戳，先备份后主文件）───────────────

from core.verify_engine.scenarios import (  # noqa: F401 — 锚点再导出
    CONTRACT_VERSION_FIELD,
    CURRENT_CONTRACT_VERSION,
    SCHEMA_VERSION,
    prepare_scenarios_for_write,
)

# 成对写顺序（judge 受理门同构）：先 `_scenarios_full.json` 备份、后
# `test_scenarios.json` 主文件——撕裂窗口只允许「备份新主文件旧」方向
# 存在半拍（受理采纳成对落盘时同轮落定）。
PAIR_WRITE_BACKUP_FILE = "_scenarios_full.json"
PAIR_WRITE_MAIN_FILE = "test_scenarios.json"
PAIR_WRITE_ORDER = (PAIR_WRITE_BACKUP_FILE, PAIR_WRITE_MAIN_FILE)


def assert_pair_write_contract(backup_payload, main_payload) -> List[str]:
    """成对落盘一致性校验（写前预检 / 撕裂对检测，纯函数）。

    两份 payload 均应为 ``prepare_scenarios_for_write`` 形态（场景条目
    list）。逐场景 id 对账：双方都存在时 ``schema_version`` 与
    ``contract_version`` 戳必须一致；单侧缺失/形状非法记违例。

    Returns:
        违例描述列表（空 = 一致，可落盘）。
    """
    violations: List[str] = []

    def _index(payload) -> Dict[str, dict]:
        items = payload
        if isinstance(payload, dict):
            items = payload.get("scenarios") or []
        out: Dict[str, dict] = {}
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    out[item["id"]] = item
        return out

    backup_map = _index(backup_payload)
    main_map = _index(main_payload)
    for sid in sorted(set(backup_map) | set(main_map)):
        b = backup_map.get(sid)
        m = main_map.get(sid)
        if b is None or m is None:
            violations.append(f"场景'{sid}'成对单侧缺失（备份={b is not None}，"
                              f"主文件={m is not None}）——撕裂对")
            continue
        for key in ("schema_version", CONTRACT_VERSION_FIELD):
            if b.get(key) != m.get(key):
                violations.append(
                    f"场景'{sid}'契约戳不一致：{key} 备份={b.get(key)!r} "
                    f"主文件={m.get(key)!r}",
                )
    return violations


# ── 正当性码白名单（闭合；码 → 知识锚）─────────────────────────────────

JUSTIFICATION_CODE_ANCHORS: Dict[str, str] = {
    "global-counter-nondeterministic": (
        "spec/knowledge/domains/verify-pipeline/scenario-env-coupling.md"
    ),
}


def _is_justified(scenario_id: str, target: Optional[str],
                  justifications) -> Optional[str]:
    """该 (scenario, target) 是否被白名单正当性码覆盖；命中返回码。"""
    for j in justifications or []:
        if not isinstance(j, dict):
            continue
        code = str(j.get("code") or "")
        if code not in JUSTIFICATION_CODE_ANCHORS:
            continue
        if str(j.get("scenario_id") or "") != scenario_id:
            continue
        j_target = j.get("target")
        if j_target in (None, "") or (target is not None
                                      and str(j_target) == target):
            return code
    return None


# ── 判定结果 ─────────────────────────────────────────────────────────────

TIGHTEN = "tighten"
RELAX = "relax"
NEUTRAL = "neutral"


@dataclass(frozen=True)
class ProverVerdict:
    """证明器净判定（逐条摘要 + 汇总出口）。"""

    outcome: str  # "pass" | "reject"
    entries: Tuple[dict, ...] = field(default_factory=tuple)
    unjustified: Tuple[dict, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        return self.outcome == "pass"

    def to_summary(self) -> str:
        """逐条判定摘要（供报告 ``scenario_fixes`` 字段留痕）。"""
        lines = [f"证明器净判定：{self.outcome}"
                 f"（{len(self.entries)} 条 diff，未获准放宽 "
                 f"{len(self.unjustified)} 条）"]
        for e in self.entries:
            lines.append(
                f"- [{e.get('classification')}] {e.get('scenario_id')}"
                f"{('.' + e['target']) if e.get('target') else ''}："
                f"{e.get('note')}",
            )
        return "\n".join(lines)

    def reject_summary(self) -> str:
        """拒绝态净判定摘要；放行态返回空串（B4 消费口径）。"""
        if self.passed:
            return ""
        lines = [f"证明器拒绝：{len(self.unjustified)} 条未获准放宽"]
        for e in self.unjustified:
            lines.append(
                f"- {e.get('scenario_id')}"
                f"{('.' + e['target']) if e.get('target') else ''}："
                f"{e.get('note')}",
            )
        return "\n".join(lines)


# ── 语料代理（regex 覆盖面比较的固定样本；确定性优先于完备性）────────────

_REGEX_CORPUS: Tuple[str, ...] = (
    "", "0", "1", "3", "12", "123", "1234", "-1", "3.5", "0.00", "99+",
    "abc", "ABC", "ok", "N/A", "中文测试", " ", "  x  ", "x", "#",
    "2026-11-12", "T08:00:00", "a-b_c", "ERROR", "done 3 items",
)


def _compare_regex(old_pattern: str, new_pattern: str) -> Tuple[str, str]:
    """regex→regex 的覆盖面代理三分类（语料子集关系，确定性）。"""
    try:
        old_re = re.compile(old_pattern)
    except re.error:
        return NEUTRAL, "旧正则非法（执行期必败），改动视为修复性改写"
    try:
        new_re = re.compile(new_pattern)
    except re.error:
        return NEUTRAL, "新正则非法（执行期必败，非放宽形态）"
    m_old = {s for s in _REGEX_CORPUS if old_re.search(s)}
    m_new = {s for s in _REGEX_CORPUS if new_re.search(s)}
    if m_old < m_new:
        return RELAX, f"regex 覆盖面扩大（语料代理：{sorted(m_new - m_old)} 新入集）"
    if m_new < m_old:
        return TIGHTEN, "regex 覆盖面收窄（语料代理）"
    if m_old == m_new:
        return NEUTRAL, "regex 覆盖面等价（语料代理），视为文案级改写"
    return RELAX, "regex 覆盖面不可比（语料代理），按保守放宽拒"


_QUOTED_RE = re.compile(r"(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')")


def _selector_skeleton(selector: str) -> str:
    """剥引号字面量后的选择器骨架（文案字面变体与作用域收紧判别基础）。"""
    return _QUOTED_RE.sub("()", selector or "")


def _compare_selector(old_sel: str, new_sel: str) -> Tuple[str, str]:
    """选择器三分类：骨架等价=文案变体 neutral；骨架包含=作用域收紧
    neutral；否则 relax（重写未经证明收紧——宁误拒人工兜底）。"""
    old_sk, new_sk = _selector_skeleton(old_sel), _selector_skeleton(new_sel)
    if old_sk == new_sk:
        return NEUTRAL, "选择器仅文案字面变体（骨架等价）"
    if old_sk and old_sk in new_sk:
        return NEUTRAL, "选择器作用域化收紧（锚定范围收窄）"
    return RELAX, "选择器重写未经证明收紧（骨架不含旧骨架）"


# ── 破坏性形态识别（R1/R3 carve-out 与新增生产端点判定素材）─────────────

_POSITIONAL_CLICK_RE = re.compile(
    r":nth-|>>|\.first\b|\.last\b|\bfirst\b|\blast\b|row\s*[=:\-]?\s*\d"
    r"|第\s*\d+\s*行",
    re.IGNORECASE,
)
_BATCH_DESTRUCTIVE_RE = re.compile(
    r"mark[_-]?all[_-]?handled|alerts?/clear|"
    r"alerts?/[^/\s\"']*/(?:resolve|handled)",
    re.IGNORECASE,
)
_PRODUCTION_ENDPOINT_RE = re.compile(
    r"alerts?/[^/\s\"']*|adjudication[_-]?choices?|"
    r"choices?/[^/\s\"']*/execute|mark[_-]?all[_-]?handled",
    re.IGNORECASE,
)
_WRITE_METHODS = {"post", "put", "patch", "delete"}
_GUARD_STEP_ACTIONS = {"wait", "mock_api", "seed"}
_NOTE_ONLY_KEYS = {"note", "desc", "description", "help", "comment"}
_EXPECT_KEYS = {"expected", "mode"}
# 语义定位键：携带「检查点打在哪」语义的断言定位字段——其变更等价断言
# 换靶（旧检查点删除 + 新检查点按旧期望落点），按 relax 判（与「断言
# 删除 = relax」同一判定哲学）；timeout 等真形态字段变更才 neutral。
_SEMANTIC_LOCATOR_KEYS = ("json_path", "selector", "url")


def _step_text(step: dict) -> str:
    parts = [step.get("target"), step.get("url"), step.get("value"),
             step.get("command")]
    stdin = step.get("stdin")
    if isinstance(stdin, list):
        parts.extend(stdin)
    elif isinstance(stdin, str):
        parts.append(stdin)
    net = step.get("expect_network")
    if isinstance(net, dict):
        parts.append(net.get("url_pattern"))
    elif isinstance(net, list):
        parts.extend(n.get("url_pattern") for n in net
                     if isinstance(n, dict))
    return " ".join(str(p) for p in parts if isinstance(p, str))


def _is_destructive_form_step(step: dict) -> bool:
    """R1 位置点击改状态 / R3 批量破坏确认形态步骤（carve-out 判定）。"""
    if not isinstance(step, dict):
        return False
    action = str(step.get("action") or "")
    target = str(step.get("target") or "")
    text = _step_text(step)
    if action == "click" and target and _POSITIONAL_CLICK_RE.search(target):
        return True
    if _BATCH_DESTRUCTIVE_RE.search(text):
        return True
    return False


def _step_endpoints(step: dict) -> set:
    return set(_PRODUCTION_ENDPOINT_RE.findall(_step_text(step)))


def _scenario_endpoints(sc: dict) -> set:
    out: set = set()
    for step in (sc or {}).get("steps") or []:
        if isinstance(step, dict):
            out |= _step_endpoints(step)
    return out


def _scenario_dep_set(sc: dict) -> set:
    """场景 depends_on 依赖 id 集（非 list 形态视为空——容错不猜）。"""
    deps = (sc or {}).get("depends_on")
    if not isinstance(deps, list):
        return set()
    return {str(d) for d in deps if d}


# ── 断言比较 ─────────────────────────────────────────────────────────────

def _compare_assertion(old: dict, new: dict) -> Tuple[str, str]:
    """成对断言三分类（期望语义 / 选择器 / 注记边界）。"""
    if old == new:
        return NEUTRAL, "断言未变"
    old_notes = {k: v for k, v in old.items() if k in _NOTE_ONLY_KEYS}
    new_notes = {k: v for k, v in new.items() if k in _NOTE_ONLY_KEYS}
    core_old = {k: v for k, v in old.items() if k not in _NOTE_ONLY_KEYS}
    core_new = {k: v for k, v in new.items() if k not in _NOTE_ONLY_KEYS}
    if core_old == core_new:
        return NEUTRAL, "仅文案注记变更"

    has_expected = "expected" in core_old or "expected" in core_new
    if has_expected:
        old_exp, new_exp = old.get("expected"), new.get("expected")
        old_mode = str(old.get("mode") or "exact")
        new_mode = str(new.get("mode") or "exact")
        if old_exp != new_exp and old_mode == new_mode \
                and old_mode in ("exact", "contains"):
            return RELAX, f"期望值漂移（{old_mode}：{old_exp!r}→{new_exp!r}）"
        if old_mode == new_mode and old_mode == "regex" \
                and old_exp != new_exp:
            return _compare_regex(str(old_exp), str(new_exp))
        if old_mode != new_mode:
            if old_mode in ("exact", "contains") and new_mode == "regex":
                return RELAX, f"期望匹配放宽（{old_mode}→regex）"
            if old_mode == "exact" and new_mode == "contains":
                return RELAX, "期望匹配放宽（exact→contains）"
            if old_mode == "contains" and new_mode == "exact":
                return TIGHTEN, "期望匹配收紧（contains→exact）"
            if old_mode == "regex" and new_mode in ("exact", "contains"):
                return TIGHTEN, f"期望匹配收紧（regex→{new_mode}）"
        if old_exp == new_exp and old_mode == new_mode:
            # 期望与模式均未变时，core 差异若落在语义定位字段即为换靶
            # 形态（含把检查点挪到恰好通过的路径、期望向实际看齐的自证
            # 变体，隐含旧检查点删除），按 relax；仅 timeout 等真形态
            # 字段变更才 neutral。
            moved_locators = [k for k in _SEMANTIC_LOCATOR_KEYS
                              if old.get(k) != new.get(k)]
            if moved_locators:
                return RELAX, (
                    f"断言语义定位字段变更（{'/'.join(moved_locators)}）"
                    "——断言换靶，回归面收窄")
            return NEUTRAL, "期望语义未变（仅形态字段变更）"
        return RELAX, f"期望语义变更未归入已知收紧形态（{old_mode}:{old_exp!r}→{new_mode}:{new_exp!r}）"

    if "selector" in core_old and "selector" in core_new:
        return _compare_selector(str(core_old["selector"]),
                                 str(core_new["selector"]))

    return RELAX, "断言语义字段变更未归入已知中性形态"


# ── 步骤比较 ─────────────────────────────────────────────────────────────

def _classify_added_step(step: dict) -> Tuple[str, str]:
    # B1 对称化：破坏性形态新增一律 relax——移除面的合规化 carve-out
    # 不给新增面豁免，机器人对生产账本的副作用面不得从新增步骤绕过
    # 证明器（判定与 _is_destructive_form_step 同源）。
    if _is_destructive_form_step(step):
        return RELAX, "新增破坏性形态步骤（R1 位置点击改状态/R3 批量破坏确认）"
    action = str(step.get("action") or "")
    if action in _GUARD_STEP_ACTIONS or step.get("expect_network"):
        return TIGHTEN, "新增守卫/时序步骤"
    if action == "http_request":
        method = str(step.get("method") or "GET").lower()
        if method in _WRITE_METHODS:
            return RELAX, "新增生产写端点请求（非只读方法）"
        return NEUTRAL, "新增只读探查请求"
    return NEUTRAL, "新增步骤（覆盖面扩展）"


def _compare_expect_network(old: dict, new: dict) -> Optional[Tuple[str, str]]:
    """expect_network 守卫三分类（http_request 与普通成对步骤共用口径）：
    新增 / 模式包含收紧 = tighten；改写 / 删除 = relax；未变返回 None。"""
    old_net = old.get("expect_network")
    new_net = new.get("expect_network")
    if old_net == new_net:
        return None
    old_p = _step_text({"expect_network": old_net}) if old_net else ""
    new_p = _step_text({"expect_network": new_net}) if new_net else ""
    if not old_p:
        return TIGHTEN, "新增 expect_network 守卫"
    if old_p in new_p:
        return TIGHTEN, "expect_network 守卫收紧（模式包含旧模式）"
    return RELAX, "expect_network 守卫改写未经证明收紧"


def _compare_step(old: dict, new: dict) -> Tuple[str, str]:
    """成对步骤三分类（等待时序 / 端点重绑定 / 选择器 / 守卫收紧）。"""
    if old == new:
        return NEUTRAL, "步骤未变"
    action = str(new.get("action") or old.get("action") or "")
    if action == "wait":
        return NEUTRAL, "等待时序调整"
    if action == "navigate":
        old_url, new_url = str(old.get("value") or ""), str(new.get("value") or "")
        if old_url == new_url:
            return NEUTRAL, "导航未变"
        # hash 路由（umi 挂根 #/xxx）是 SPA 的唯一路由段——路径对账保留
        # fragment，只剥 query；仅宿主/端口重绑定视为中性。
        old_path = old_url.split("://", 1)[-1].split("/", 1)[-1].split("?", 1)[0]
        new_path = new_url.split("://", 1)[-1].split("/", 1)[-1].split("?", 1)[0]
        if old_path == new_path:
            return NEUTRAL, "URL 仅宿主/端口重绑定（路径等价）"
        return RELAX, "导航目标路径变更未经证明收紧"
    if action == "http_request":
        old_m = str(old.get("method") or "GET").lower()
        new_m = str(new.get("method") or "GET").lower()
        if old_m != new_m:
            return RELAX, f"请求方法变更（{old_m.upper()}→{new_m.upper()}）"
        old_url, new_url = str(old.get("url") or ""), str(new.get("url") or "")
        old_path = old_url.split("://", 1)[-1]
        new_path = new_url.split("://", 1)[-1]
        if old_path.split("/", 1)[-1].split("?", 1)[0] \
                == new_path.split("/", 1)[-1].split("?", 1)[0]:
            guard = _compare_expect_network(old, new)
            if guard is not None:
                return guard
            return NEUTRAL, "请求仅宿主/端口重绑定（路径等价）"
        return RELAX, "请求端点路径变更未经证明收紧"
    if "target" in old or "target" in new:
        if old.get("target") != new.get("target"):
            return _compare_selector(str(old.get("target") or ""),
                                     str(new.get("target") or ""))
        # 目标未变不豁免守卫差异：守卫删除/改写即确认面收窄，与
        # http_request 分支同口径三分类
        guard = _compare_expect_network(old, new)
        if guard is not None:
            return guard
        return NEUTRAL, "步骤目标未变（仅附属字段调整）"
    if action == "run":
        if old.get("command") != new.get("command"):
            return RELAX, "探针命令变更未经证明收紧"
        return NEUTRAL, "探针脚本内部改写（command 未变）"
    return NEUTRAL, "步骤附属字段调整"


def _greedy_align(old_items: List[dict], new_items: List[dict],
                  key: str) -> Tuple[List[Tuple[int, int]], List[int], List[int]]:
    """按 key 值保序贪心配对；未配对的下标各自剩余（删/增）。"""
    pairs: List[Tuple[int, int]] = []
    used_new: set = set()
    for i, old in enumerate(old_items):
        want = str(old.get(key) or "") if isinstance(old, dict) else ""
        for j in range(len(new_items)):
            if j in used_new:
                continue
            new = new_items[j]
            got = str(new.get(key) or "") if isinstance(new, dict) else ""
            if want and got == want:
                pairs.append((i, j))
                used_new.add(j)
                break
    old_paired = {i for i, _ in pairs}
    return (pairs,
            [i for i in range(len(old_items)) if i not in old_paired],
            [j for j in range(len(new_items)) if j not in used_new])


def _diff_scenario(old_sc: dict, new_sc: dict,
                   justifications: list) -> List[dict]:
    """单场景 diff → 判定条目（含 B1 合规化 carve-out 整体归并）。"""
    sid = str(new_sc.get("id") or old_sc.get("id") or "?")
    entries: List[dict] = []

    def _add(target: Optional[str], classification: str, note: str,
             detail: str = "") -> None:
        entries.append({
            "scenario_id": sid,
            "target": target,
            "classification": classification,
            "note": note,
            "detail": detail,
        })

    # 场景级字段：kind 重定义 = relax；depends_on 依赖收窄 = relax（前置
    # 断言链不再执行，间接回归面收窄）；其余标量字段变化视为注记/编排
    if str(old_sc.get("kind") or "") != str(new_sc.get("kind") or ""):
        _add(None, RELAX,
             f"场景 kind 重定义（{old_sc.get('kind')}→{new_sc.get('kind')}）")
    removed_deps = sorted(_scenario_dep_set(old_sc)
                          - _scenario_dep_set(new_sc))
    if removed_deps:
        _add(None, RELAX,
             "depends_on 前置依赖收窄（移除：" + "、".join(removed_deps)
             + "）——前置断言链不再执行，间接回归面收窄")

    old_assertions = [a for a in old_sc.get("assertions") or []
                      if isinstance(a, dict)]
    new_assertions = [a for a in new_sc.get("assertions") or []
                      if isinstance(a, dict)]
    pairs, old_left, new_left = _greedy_align(old_assertions,
                                              new_assertions, "type")
    for i, j in pairs:
        cls, note = _compare_assertion(old_assertions[i], new_assertions[j])
        if cls == RELAX:
            code = (str(new_assertions[j].get("justification_code") or "")
                    or _is_justified(sid, f"assertions[{i}]", justifications))
            if code:
                _add(f"assertions[{i}]", NEUTRAL,
                     f"放宽获准（正当性码 {code}）")
                continue
        _add(f"assertions[{i}]", cls, note)
    for i in old_left:
        code = _is_justified(sid, f"assertions[{i}]", justifications)
        if code:
            _add(f"assertions[{i}]", NEUTRAL,
                 f"断言删除获准（正当性码 {code}）")
        else:
            _add(f"assertions[{i}]", RELAX, "断言删除（回归面收窄）")
    for j in new_left:
        _add(None, TIGHTEN, f"新增断言（assertions[{j}]）")

    old_steps = [s for s in old_sc.get("steps") or [] if isinstance(s, dict)]
    new_steps = [s for s in new_sc.get("steps") or [] if isinstance(s, dict)]
    spairs, s_old_left, s_new_left = _greedy_align(old_steps, new_steps,
                                                   "action")
    removed_destructive_only = True
    for i in s_old_left:
        if _is_destructive_form_step(old_steps[i]):
            # carve-out 候选：先记 relax，场景级合规化成立时整体归并为中性
            _add(f"steps[{i}]", RELAX,
                 "移除破坏性形态步骤（R1 位置点击改状态/R3 批量破坏确认）")
        else:
            removed_destructive_only = False
            code = _is_justified(sid, f"steps[{i}]", justifications)
            if code:
                _add(f"steps[{i}]", NEUTRAL,
                     f"步骤删除获准（正当性码 {code}）")
            else:
                _add(f"steps[{i}]", RELAX, "步骤删除")
    for j in s_new_left:
        cls, note = _classify_added_step(new_steps[j])
        _add(None, cls, note)
    for i, j in spairs:
        cls, note = _compare_step(old_steps[i], new_steps[j])
        if cls == RELAX:
            code = (str(new_steps[j].get("justification_code") or "")
                    or _is_justified(sid, f"steps[{i}]", justifications))
            if code:
                _add(f"steps[{i}]", NEUTRAL,
                     f"放宽获准（正当性码 {code}）")
                continue
        _add(f"steps[{i}]", cls, note)

    # B1 合规化 carve-out（design D2）：diff 仅由破坏性形态步骤移除构成、
    # 无新增生产端点、无未获准断言放宽 → 整体中性（合规化 ≠ 放宽）。
    removals = [e for e in entries
                if e["target"] and str(e["target"]).startswith("steps[")
                and e["classification"] == RELAX
                and "破坏性形态步骤" in e["note"]]
    removal_ids = {id(e) for e in removals}
    other_relaxes = [e for e in entries if e["classification"] == RELAX
                     and id(e) not in removal_ids]
    new_endpoints = _scenario_endpoints(new_sc)
    old_endpoints = _scenario_endpoints(old_sc)
    if (removals and not other_relaxes and removed_destructive_only
            and new_endpoints <= old_endpoints):
        for e in removals:
            e["classification"] = NEUTRAL
            e["note"] += "（B1 合规化 carve-out：无新增生产端点，整体中性）"
        entries.append({
            "scenario_id": sid, "target": None, "classification": NEUTRAL,
            "note": "B1 合规化 carve-out 成立：破坏性形态步骤移除且无新增"
                    "生产端点，场景整体中性",
            "detail": "",
        })
    return entries


# ── 入口 ─────────────────────────────────────────────────────────────────

def _scenario_list(scenarios) -> List[dict]:
    if isinstance(scenarios, dict):
        scenarios = scenarios.get("scenarios") or []
    if not isinstance(scenarios, list):
        return []
    return [s for s in scenarios if isinstance(s, dict)]


def prove_scenario_fix(old_scenarios, new_scenarios,
                       justifications=None) -> ProverVerdict:
    """语义保持证明（纯函数，确定性三分类）。

    Args:
        old_scenarios: 修复前场景集（list 或 ``{"scenarios": [...]}`` 包装）。
        new_scenarios: 修复后场景集（同形态）。
        justifications: 正当性申报列表，每条
            ``{"scenario_id", "code", "target"?}``——``code`` 须在
            ``JUSTIFICATION_CODE_ANCHORS`` 白名单内；``target`` 缺省豁免
            该场景全部条目。断言/步骤也可内联
            ``justification_code`` 键（双通道等价）。

    Returns:
        ProverVerdict：``outcome="pass"`` 当且仅当无未获准 relax。
    """
    old_list = _scenario_list(old_scenarios)
    new_list = _scenario_list(new_scenarios)
    old_map = {str(s.get("id") or ""): s for s in old_list}
    new_map = {str(s.get("id") or ""): s for s in new_list}
    entries: List[dict] = []
    for sid in sorted(set(old_map) - set(new_map)):
        code = _is_justified(sid, None, justifications)
        if code:
            entries.append({
                "scenario_id": sid, "target": None,
                "classification": NEUTRAL,
                "note": f"场景删除获准（正当性码 {code}）", "detail": "",
            })
        else:
            entries.append({
                "scenario_id": sid, "target": None,
                "classification": RELAX,
                "note": "场景删除（回归面收窄）", "detail": "",
            })
    for sid in sorted(set(new_map) - set(old_map)):
        entries.append({
            "scenario_id": sid, "target": None,
            "classification": TIGHTEN, "note": "新增场景（覆盖面扩展）",
            "detail": "",
        })
    for sid in sorted(set(old_map) & set(new_map)):
        entries.extend(_diff_scenario(old_map[sid], new_map[sid],
                                      justifications))
    unjustified = tuple(e for e in entries if e["classification"] == RELAX)
    outcome = "pass" if not unjustified else "reject"
    return ProverVerdict(
        outcome=outcome,
        entries=tuple(entries),
        unjustified=unjustified,
    )


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print("用法：python3 -m core.verify_engine.scenario_semantics "
              "<old.json> <new.json>", file=sys.stderr)
        raise SystemExit(2)
    import json
    from pathlib import Path

    with open(sys.argv[1], encoding="utf-8") as f:
        old = json.load(f)
    with open(sys.argv[2], encoding="utf-8") as f:
        new = json.load(f)
    verdict = prove_scenario_fix(old, new)
    print(verdict.to_summary())
    raise SystemExit(0 if verdict.passed else 1)
