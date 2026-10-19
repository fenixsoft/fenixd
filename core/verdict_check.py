"""verdict_check.py — 裁决证据分类校验器（add-verdict-evidence-taxonomy）。

设计依据：design.md D1-D5。

裁决链：验证引擎产出 report.json（逐场景 status / assertion_results / screenshots）
→ planner-judge 读取并**增强** report.json（每个非 PASS 场景补 classification 与
evidence，逻辑见 agent_runner.py 的 planner-judge prompt）→ pm_engine 裁决采纳处
消费。

本模块是独立于裁决的纯 Python 校验器（与 scenario-freeze 同型），输入增强后的
report.json，校验：
  - 字段齐全性：每个非 PASS 场景 MUST 含 classification 与 evidence
  - 取值合法性：classification ∈ {product-bug, test-defect, flaky, env}
  - 分类-状态映射：product-bug / test-defect MUST 映射为 failed；flaky / env MAY
    映射为 warning；禁止 product-bug 映射为 warning（D3）
  - 逐断言归因（add-interaction-contract-and-per-assert-triage D3）：每个非 PASS
    场景 MUST 含 assertion_triage 数组，对其每条失败断言单独归类（四分类）并附
    证据；场景级豁免（不记产品 Bug）仅当全部失败断言均非 product-bug 时成立

不合规由调用方（pm_engine 采纳处）走既有裁决重试一次；二次失败 → blocked-env +
告警（与 verify-report-gate 的阻断语义一致）。

向后兼容：report.json 无 classification/evidence 字段（旧格式）时，validate_report
返回 ok=False 且每条非 PASS 场景都标 violation（驱动重试补全），不静默放行。
"""

import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, List, Optional, Set

from core.admin_store import _fsync_parent_dir
from core.fast_track_result import SCENARIO_STATUSES

# 四分类取值（design D1）
VERDICT_CLASSES = ("product-bug", "test-defect", "flaky", "env")

# 非 PASS 状态（这些场景 MUST 带 classification + evidence + assertion_triage）
NON_PASS_STATUSES = ("fail", "failed", "error", "warning")

# classification → 强制状态映射（design D3）
# product-bug / test-defect MUST → failed；flaky / env 允许 warning（不强制）。
FORCE_FAILED_CLASSES = ("product-bug", "test-defect")

# 场景级豁免（warning / 不记产品 Bug）的豁免理由文案（报告豁免清单用）
EXEMPTION_REASON = {
    "test-defect": "测试用例自身缺陷（非产品缺陷）",
    "flaky": "不稳定复现（非产品缺陷）",
    "env": "环境因素（非产品缺陷）",
}

# ── 非驱动视觉状态（fix-visual-baseline-settle D4）──────────────────
# baseline_deferred（基线固化前置条件未满足，本轮不固化不比对）与
# baseline_rejected（健全性判定拒绝固化）属「本轮无法/拒绝对比」语义，与
# env/flaky 同属不构成打回依据：
#   - 引擎侧 determine_scenario_status 已保证此类视觉状态不使场景降档
#     （baseline_deferred 不落 warning/failed，场景按 DOM 断言正常判档）；
#   - 既有豁免通道（_EXEMPT_ALLOWED_CLASSES / is_scenario_exemptible）对其
#     放行——此类场景要么 status=pass 无需分类，要么按 DOM 断言单独归因。
NON_DRIVING_VISUAL_STATUSES = ("baseline_deferred", "baseline_rejected")


# 预留判别单源（当前全仓无生产消费点）：仅 tests/test_visual_baseline_integrity.py
# 引用钉死契约；「judge 不得将非驱动视觉状态计入 bug-found 打回依据」的实际承接点
# 在引擎侧 determine_scenario_status，失败信号侧由 _scenario_has_failure_signal
# 按同源口径独立判定（见其 docstring）。后续消费方接入时以本函数为单源，勿另立口径。
def has_only_non_driving_visual_indicators(scenario: dict) -> bool:
    """场景的失败信号是否仅来自非驱动视觉状态（无 DOM/步骤失败）。

    Returns:
        True 表示：全部 DOM 断言通过、无步骤失败，且 visual_results 中存在
        baseline_deferred/baseline_rejected（不含 diff_detected/warning 类
        驱动视觉结论）——judge 不得将其计入 bug-found 打回依据（同 flaky/env
        待遇）；场景整体 status 应判 pass，无需分类与归因。
    """
    if not isinstance(scenario, dict):
        return False
    for a in scenario.get("assertion_results") or []:
        if isinstance(a, dict) and not a.get("pass", True):
            return False
    for s in scenario.get("step_results") or []:
        if isinstance(s, dict) and not s.get("success", True):
            return False
    visual = scenario.get("visual_results")
    if not isinstance(visual, list) or not visual:
        return False
    for v in visual:
        if not isinstance(v, dict):
            continue
        if v.get("status") in ("diff_detected", "warning"):
            return False  # 存在驱动视觉结论，非「仅非驱动」
    return any(
        isinstance(v, dict) and v.get("status") in NON_DRIVING_VISUAL_STATUSES for v in visual
    )


def _is_non_pass(status: Optional[str]) -> bool:
    if not status:
        return False
    return status in NON_PASS_STATUSES


def _evidence_present(evidence: Any) -> bool:
    """判断 evidence 是否非空（满足「至少一个证据维度」）。

    证据至少含：失败断言列表（failed_assertions 非空）/ 截图路径
    （screenshots 非空）/ 首个失败步骤（first_failed_step 非空字符串）。
    兼容历史字段（assertion_results / assertion 列表）便于旧夹具过渡。
    """
    if not isinstance(evidence, dict):
        return False
    # 失败断言列表：优先 failed_assertions，兼容 assertion_results / assertion。
    # 元素有效性比照 screenshots 口径（code-review item 58726f4b6b33）：至少
    # 一个非空 dict 或非空字符串元素才算证据——[null]/[{}] 等垃圾元素清单
    # 不得满足「至少一个证据维度」，防 judge 凑证据旁路抑制门（与同模块
    # screenshots 逐元素校验 / screenshot_labels·first_frame_ok 严格判定同防伪造口径）
    for key in ("failed_assertions", "assertion_results", "assertion"):
        val = evidence.get(key)
        if not isinstance(val, list):
            continue
        if any(
            (isinstance(item, dict) and item)
            or (isinstance(item, str) and item.strip())
            for item in val
        ):
            return True
    # 截图路径
    shots = evidence.get("screenshots")
    if isinstance(shots, list) and any(isinstance(s, str) and s.strip() for s in shots):
        return True
    # 首个失败步骤（字符串）
    ffs = evidence.get("first_failed_step")
    if isinstance(ffs, str) and ffs.strip():
        return True
    return False


def _evidence_value_present(evidence: Any) -> bool:
    """assertion_triage 条目的 evidence 是否非空（字符串非空白 / dict 非空 /
    list 至少一个有效元素）。"""
    if isinstance(evidence, str):
        return bool(evidence.strip())
    if isinstance(evidence, dict):
        return bool(evidence)
    if isinstance(evidence, list):
        # 元素级校验（code-review item cfe6f177d855）：比照 _evidence_present
        # 对同形清单的口径（item 58726f4b6b33）——至少一个非空 dict 或非空白
        # str 元素才算证据，[null]/[""] 等垃圾元素清单不得满足 triage 条目级
        # evidence 硬门（防 judge 凑证据旁路逐条归因门）。
        return any(
            (isinstance(item, dict) and item)
            or (isinstance(item, str) and item.strip())
            for item in evidence
        )
    return False


def triage_entries(scenario: dict) -> List[dict]:
    """场景的 assertion_triage 数组（缺失/非法时返回空表）。"""
    triage = scenario.get("assertion_triage") if isinstance(scenario, dict) else None
    if not isinstance(triage, list):
        return []
    return [t for t in triage if isinstance(t, dict)]


def _scenario_has_failure_signal(scenario: dict) -> bool:
    """场景是否含断言清单之外的失败信号（失败步骤 / 驱动视觉结论）。

    判定口径与 ``has_only_non_driving_visual_indicators`` 同源：step_results
    任一 success=False，或 visual_results 存在 diff_detected/warning 类驱动
    视觉结论，即视为有失败信号（baseline_deferred/rejected 等非驱动视觉
    状态不构成失败信号）。
    """
    for s in scenario.get("step_results") or []:
        if isinstance(s, dict) and not s.get("success", True):
            return True
    for v in scenario.get("visual_results") or []:
        if isinstance(v, dict) and v.get("status") in ("diff_detected", "warning"):
            return True
    return False


# ── 步骤失败形态的失败清单派生（verdict-step-failure-evidence-derivation D1）──
# 引擎侧「任一步骤原语失败即跳过断言执行」（cli_runner/api_runner/web_runner
# 同语义）使该形态下 assertion_results 必然为空表：judge 若只按「从
# assertion_results 摘未通过断言」申报，首轮漏 triage、重试轮摘出空表，
# fail-closed 驳回-重试死循环（add-knowledge-atlas-maintenance 2026-09-27
# 事故现场）。派生 helper 把失败信号机械映射为缺省 failed_assertions 条目，
# triage 覆盖校验改对派生清单核验——逐条归因仍必须覆盖清单（fail-closed
# 不弱化），只消除空表死循环。

# 派生条目 actual 文本上限（与 agents/planner-judge.md 处方 ≤300 字约束一致）
_DERIVED_ACTUAL_MAX_CHARS = 300

# 通用步骤动作词（引擎失败结果未回传 target/command 时标注仅剩动作词，
# 无法与归因文本对账——覆盖校验对此类标注豁免名称核对，走条数口径）
_GENERIC_STEP_ACTIONS = (
    "run",
    "click",
    "fill",
    "navigate",
    "wait",
    "hover",
    "press",
    "check",
    "request",
    "get",
    "post",
    "put",
    "delete",
)


def _step_failure_label(step: dict, idx: int) -> str:
    """失败步骤的可引用名（action + target/command/url 类回传字段 + 序号前缀）。

    引擎侧步骤失败结果不总回传 target（如 cli 只回传 action="run"），能取到
    专名（选择器/命令/URL/名称）时带上——triage 覆盖校验以步骤名对应归因
    条目（design 风险条目），专名是对账的关键标识。
    """
    parts = []
    action = str(step.get("action") or "").strip()
    if action:
        parts.append(action)
    for key in ("target", "selector", "command", "url", "name"):
        val = step.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(_normalize_whitespace(val))
            break
    label = " ".join(parts)
    prefix = f"步骤{idx}"
    return f"{prefix}({label})" if label else prefix


def _clip_derived_text(text, limit: int = _DERIVED_ACTUAL_MAX_CHARS) -> str:
    """派生条目文本归一化 + 截断（judge 申报处方的 ≤300 字约束同款）。"""
    # 形态归一（code-review item 114e48d39f91）：error/detail 等回传字段可能
    # 为 dict/int 等非串真值（judge 增强时整体改写 report.json 可引入），直接
    # 交给 _normalize_whitespace 的 re.sub 抛 TypeError 会沿 triage_violation
    # → validate_report 调用链外溢，异常被门禁「异常不阻断」降级后整个裁决
    # 证据校验被旁路。str 原样、dict/list 用 json.dumps、其余 str() 归一
    # （与 _step_failure_label 对同类回传字段的 isinstance 防御同口径）。
    if not isinstance(text, str):
        if isinstance(text, (dict, list)):
            try:
                text = json.dumps(text, ensure_ascii=False, sort_keys=True)
            except (TypeError, ValueError):
                text = str(text)
        else:
            # None 才折空串（code-review item 9f451083401c）：0/False 等
            # 假值本身可能是有信息量的错误回传（如退出码），``or`` 兜底会把
            # 原始值吞成空串再误述成「引擎未返回 error 文本」
            text = "" if text is None else str(text)
    clipped = _normalize_whitespace(text)
    if len(clipped) > limit:
        return clipped[:limit] + "…"
    return clipped


def derive_default_failed_assertions(scenario: dict) -> List[dict]:
    """由失败信号派生缺省 failed_assertions 清单（verdict-step-failure-evidence-derivation）。

    条目来源（与 ``_scenario_has_failure_signal`` 同判定口径）：
      - step_results 中 success=False 条目 → ``{"type": "step_error", ...}``
      - visual_results 中 diff_detected/warning 条目 → ``{"type": "screenshot_mismatch", ...}``

    条目形状与 agents/planner-judge.md「步骤失败型场景必填清单（强制）」处方
    的申报形态一致（type/selector/expected/actual），并附 ``step_failure``
    标注——泛指「非引擎断言产物的失败信号派生」而非仅步骤失败型形态：视觉
    比对条目（type=screenshot_mismatch，非步骤失败）同标（code-review item
    0f84f7995d37；下游申报形态按 type 区分，勿按本标注区分）。无失败信号
    返回空表。
    """
    entries: List[dict] = []
    if not isinstance(scenario, dict):
        return entries
    for idx, s in enumerate(scenario.get("step_results") or [], 1):
        if not (isinstance(s, dict) and not s.get("success", True)):
            continue
        # 取值按「None 才折空串」口径逐个回退（item bbd6c288cb56）：or 链会把
        # 0/False 等有信息量的假值回传（如退出码）先吞成空串，使 _clip_derived_text
        # 的 is None 防御在调用侧失效、误述成「引擎未返回 error 文本」。
        error = s.get("error")
        detail = s.get("detail")
        entries.append(
            {
                "type": "step_error",
                "selector": _step_failure_label(s, idx),
                "expected": "步骤成功",
                "actual": _clip_derived_text(
                    error if error is not None else (detail if detail is not None else "")
                )
                or "步骤执行失败（引擎未返回 error 文本）",
                "step_failure": True,
            }
        )
    for v in scenario.get("visual_results") or []:
        if not (isinstance(v, dict) and v.get("status") in ("diff_detected", "warning")):
            continue
        # 形态归一与 error/detail 同口径（_clip_derived_text，item 114e48d39f91）：
        # baseline/name/id 为非串真值时直接进 _normalize_whitespace 的 re.sub
        # 抛 TypeError，沿调用链外溢致裁决证据校验被旁路。
        # 标识符取值同按「None 才折空串」口径逐个回退（item bbd6c288cb56）：
        # id=0 等假值形态是合法且有信息量的标识，不得被 or 链吞掉。
        baseline = v.get("baseline")
        name = v.get("name")
        vid = v.get("id")
        label = _clip_derived_text(
            baseline
            if baseline is not None
            else (name if name is not None else (vid if vid is not None else ""))
        )
        error = v.get("error")
        detail = v.get("detail")
        status = v.get("status")
        entries.append(
            {
                "type": "screenshot_mismatch",
                "selector": f"visual:{label}" if label else "visual:视觉比对",
                "expected": "视觉比对通过",
                "actual": _clip_derived_text(
                    error
                    if error is not None
                    else (
                        detail
                        if detail is not None
                        else (status if status is not None else "")
                    )
                )
                or "驱动视觉结论",
                "step_failure": True,
            }
        )
    return entries


def _has_distinctive_derived_label(entry: dict) -> bool:
    """派生条目标注是否含可对账专名（剥「步骤N(...)」壳后非动作单词）。"""
    label = _normalize_whitespace(entry.get("selector"))
    m = re.match(r"^步骤\d+\((.*)\)$", label)
    inner = (m.group(1) if m else label).strip()
    if not inner:
        return False
    return inner.lower() not in _GENERIC_STEP_ACTIONS


def _derived_label_tokens(entry: dict) -> List[str]:
    """派生条目的可对账文本集合（完整标注 + 剥壳后专名 + 专名子词）。

    「步骤N(click .submit-btn)」形态剥出 ``click .submit-btn`` 与
    ``.submit-btn``——judge 归因文本常只引用步骤动作 + 选择器（不复制序号
    壳），完整标注互不包含时专名子词仍可对账。视觉条目「visual:home.png」
    的 ``visual:`` 前缀是派生器自造的装饰（derive_default_failed_assertions
    添加），judge 归因按 design 风险条目「以名称对应」引用裸视觉名，故剥
    前缀补裸名别名 token——否则裸名归因永不匹配，视觉路径逐条归因硬门
    假阴性。通用动作词不单独入候选（会误命中任意归因文本）。
    """
    label = _normalize_whitespace(entry.get("selector"))
    tokens = [label] if label else []
    m = re.match(r"^步骤\d+\((.*)\)$", label)
    if m:
        inner = m.group(1).strip()
        if inner:
            tokens.append(inner)
            words = inner.split()
            if len(words) > 1:
                tokens.extend(w for w in words[1:] if w.lower() not in _GENERIC_STEP_ACTIONS)
    else:
        vm = re.match(r"^visual:(.+)$", label)
        if vm:
            inner = vm.group(1).strip()
            if inner:
                tokens.append(inner)
    return [t.lower() for t in tokens if t]


# 名称命中的最小信息量门槛（较短方长度）：双向子串匹配下，过短的归因文本
# （如单字符 "s"）即可命中任意含该字符的候选 token，把检测③名称核对退化成
# 纯条数核对。门槛取 4：合法归因文本是引用步骤/视觉专名的句子（tests 钉死
# 的步骤名互含 / 裸选择器 / 裸视觉名 / 完整 visual: 标注形态较短方均 ≥11），
# <4 字符无法标识专名；通用动作词已不入候选（_GENERIC_STEP_ACTIONS），此
# 门槛把同一防误命中口径延到极短子串。
_MIN_NAME_MATCH_CHARS = 4


def _derived_entry_name_matched(entry: dict, triage: List[dict]) -> bool:
    """派生条目是否被某条归因条目按名称对应（任一候选文本互相包含即算）。

    允许以步骤名对应归因条目（design 风险条目：派生条目为步骤级、judge
    归因为断言级，名称对应而非逐字相等是两粒度的对接面）。较短方长度须
    达 _MIN_NAME_MATCH_CHARS，极短归因文本不计入名称命中。
    """
    for token in _derived_label_tokens(entry):
        for t in triage:
            assertion = _normalize_whitespace(t.get("assertion")).lower()
            if (
                assertion
                and min(len(token), len(assertion)) >= _MIN_NAME_MATCH_CHARS
                and (token in assertion or assertion in token)
            ):
                return True
    return False


def _uncovered_derived_entries(derived: List[dict], triage: List[dict]) -> List[dict]:
    """归因未逐条覆盖的派生条目（triage 覆盖校验的核对核心）。

    两级口径（fail-closed 不弱化 + design 风险条目的粒度差兜底）：
      1. 条数核对：归因条数少于派生条数 → 全部派生条目视为未覆盖（与
         检测①②「条数少于失败断言数」同口径）；
      2. 名称对应：条数足够时，含专名标注（步骤 target/命令/URL、视觉名）
         的派生条目 MUST 被某条归因条目按名称提及；仅通用动作词标注（引擎
         未回传 target 时无法对账）豁免名称核对——条数覆盖即逐条归因有落点。
    """
    if len(triage) < len(derived):
        return list(derived)
    return [
        d
        for d in derived
        if _has_distinctive_derived_label(d) and not _derived_entry_name_matched(d, triage)
    ]


def is_expandable_evidence_violation(reason: str) -> bool:
    """判断 judge 违规是否属「可补证据」类型（add-verify-lane-throughput 3.2）。

    可补 = evidence 缺失/截断类（validate_report 产出的 reason 以 "evidence"
    开头，如 "evidence 为空"）——补证后局部重判即可修复；
    不可补 = classification 非法（"classification 缺失或取值非法"）、逐断言
    归因违规（"assertion_triage …"）、report 结构损坏（"report.json 非对象"）
    等，须按真实重裁决记账。

    前缀判定保持与 validate_report reason 词表解耦：词表新增 evidence 类
    reason（如截断）自动纳入可补集，无需改本函数。
    """
    return isinstance(reason, str) and reason.startswith("evidence")


def triage_violation(scenario: dict) -> Optional[str]:
    """逐断言归因合规性检查（add-interaction-contract-and-per-assert-triage D3）。

    非 PASS 场景 MUST 含 assertion_triage，对每条失败断言单独归类（四分类）并附
    非空证据。合规返回 None；不合规返回首个违规原因文案。

    规则：
      - assertion_triage 缺失/为空 → 违规（未逐条归因）
      - 条目缺 assertion 内容 / classification 非法 / evidence 为空 → 违规
      - 条目数少于失败断言数 → 违规（漏条目，整体豁免会吞掉漏归因的断言）
    """
    if not isinstance(scenario, dict):
        return None
    status = scenario.get("status")
    if not _is_non_pass(status):
        return None

    triage = triage_entries(scenario)
    if not triage:
        return "assertion_triage 缺失或为空（failed 场景 MUST 逐条归类失败断言）"

    for i, entry in enumerate(triage, 1):
        assertion = entry.get("assertion")
        if not (isinstance(assertion, str) and assertion.strip()):
            return f"assertion_triage 第 {i} 条缺 assertion 内容"
        if entry.get("classification") not in VERDICT_CLASSES:
            return f"assertion_triage 第 {i} 条 classification 缺失或取值非法"
        if not _evidence_value_present(entry.get("evidence")):
            return f"assertion_triage 第 {i} 条 evidence 为空"

    # 漏条目检测：失败断言数多于归因条数 → 有断言未被单独归类
    failed_count = 0
    ars = scenario.get("assertion_results")
    if isinstance(ars, list):
        failed_count = sum(1 for a in ars if isinstance(a, dict) and not a.get("pass", True))
    if failed_count and len(triage) < failed_count:
        return (
            f"assertion_triage 仅 {len(triage)} 条，少于失败断言数 {failed_count}"
            f"（MUST 逐条归类全部失败断言）"
        )

    # 漏条目检测②（code-review item 4f4c0e8c54aa）：triage 条数少于 judge 自
    # 申报的 evidence.failed_assertions 数 → 同为漏条目。assertion_results
    # 缺失/非列表/空表时上面的 failed_count 恒为 0、检测失效，此路兜住该旁路
    # （清单是 judge 自己申报的，申报了更多失败断言就必须逐条归类）。
    evidence = scenario.get("evidence")
    ev_failed = evidence.get("failed_assertions") if isinstance(evidence, dict) else None
    if isinstance(ev_failed, list) and len(triage) < len(ev_failed):
        return (
            f"assertion_triage 仅 {len(triage)} 条，少于 evidence.failed_assertions "
            f"的 {len(ev_failed)} 条（MUST 逐条归类全部失败断言）"
        )

    # 漏条目检测③（同条目 fail-closed）：引擎断言清单不可作失败基准
    # （assertion_results 缺失/非列表/空表；或非空但失败条目数为 0——
    # code-review item 17d7a090967f：零失败条目使 failed_count=0、检测①
    # 失效且检测②需自申报清单，若不并入本检测，该形态与 status=fail 及失败
    # 步骤/驱动视觉信号自相矛盾却绕过派生覆盖核对，逐条归因硬门退化为
    # 「任意 1 条形状合规的 triage 即放行」；引擎侧「步骤失败即跳过断言」使
    # 该形态不可能自然产出，仅 judge 改写可达）也无自申报失败断言清单，而
    # 场景仍存在失败步骤/驱动视觉结论等失败信号 → 由失败信号派生缺省
    # failed_assertions 清单（verdict-step-failure-evidence-derivation D1），
    # 以派生清单为基准执行 triage 覆盖校验：归因未逐条覆盖派生清单仍判违规
    # 并列出派生条目（fail-closed 不弱化，不给「任意 1 条合规 triage 即放行」
    # 留口）；逐条覆盖 → 合规——空表不再空转驳回，重试轮 judge 有应申报
    # 条目可依。
    # failed_count 仅在 ars 为含失败条目的列表时才 >0，==0 即涵盖缺失/非列表/
    # 空表/零失败条目四种「清单不可作失败基准」形态。
    ars_unusable_as_baseline = failed_count == 0
    if ars_unusable_as_baseline and not (isinstance(ev_failed, list) and ev_failed):
        if _scenario_has_failure_signal(scenario):
            derived = derive_default_failed_assertions(scenario)
            if not derived:
                # 防御兜底：有失败信号却派生不出条目（畸形条目形态）→ 沿用
                # 原清单缺失文案（fail-closed 不放行）
                return (
                    "assertion_results 断言清单缺失或零失败条目，"
                    "无法逐条核验归因完整性（场景仍存在失败信号）："
                    "须在 evidence.failed_assertions 逐条列出失败断言并逐条归类"
                )
            uncovered = _uncovered_derived_entries(derived, triage)
            if uncovered:
                listed = "；".join(f"{d.get('type')}[{d.get('selector')}]" for d in uncovered)
                return (
                    "assertion_results 断言清单缺失或零失败条目（场景存在失败信号），"
                    f"assertion_triage 未逐条覆盖框架派生的失败清单"
                    f"（未覆盖 {len(uncovered)}/{len(derived)} 条：{listed}）："
                    "须在 evidence.failed_assertions 逐条申报上述派生条目"
                    "（步骤失败型场景必填清单）并逐条给出 assertion_triage 归因"
                )
    return None


def has_product_bug_assertion(scenario: dict) -> bool:
    """场景的失败断言中是否存在归类 product-bug 的条目（D3：阻止场景级豁免）。"""
    return any(t.get("classification") == "product-bug" for t in triage_entries(scenario))


def is_scenario_exemptible(scenario: dict) -> bool:
    """场景级豁免（不记产品 Bug）是否成立（D3）。

    仅当该场景全部失败断言均被单独归类为非 product-bug（且逐断言归因合规）时
    成立；含任一 product-bug 断言 → 不得豁免。
    """
    # 非 dict 入参防御（code-review item c2a6dc4cf8a2，与 triage_violation /
    # triage_entries 等同模块公共入口同口径）：scenario.get 直接抛 AttributeError
    if not isinstance(scenario, dict):
        return False
    if not _is_non_pass(scenario.get("status")):
        return False
    if triage_violation(scenario) is not None:
        return False
    return not has_product_bug_assertion(scenario)


def whitewash_violations(scenarios: list, verdict: str,
                         env_exemptions=None, scenario_hashes=None,
                         now=None) -> List[str]:
    """verified 洗白不变量（help-center 0/15 verified 事故的防线）。

    - 0 通过 + 有失败 → 不得 verified（无论失败分类为何——合成报告
      「0/15 通过（全部场景通过）」式的自相矛盾再也不能合法存在）；
    - 任一失败分类为 env → 不得 verified（env 问题须升级 admin 处置，
      不得当作豁免理由放行——「遇到 env 就不测试了」被本检查封死）；
    - 场景表存在非对象条目（损坏场景表）→ 不得 verified（fail-closed，
      零有效场景的损坏报告不得静默放行）；
    - 场景表为空列表（0/0）→ 不得 verified（code-review item ca52c2521b1f：
      与损坏场景表同款 fail-closed——「0/0 场景通过」既非全失败也非 env，
      空报告不得静默过洗白门；escalation 通道对空表先行保守放行、不经此处，
      直调本函数做 verified 防线的调用方由本条把守）；
    - 场景表非列表（结构损坏）→ 不得 verified（code-review item
      c4f79c5c5fe9：与空表/非对象条目同款 fail-closed——escalation 通道
      `report.get("scenarios") or []` 会把非 list 真值原样透传进来，
      损坏输入不得比空表更宽）；
    - exempt（fast-track 申报豁免）既不算通过也不算失败（code-review item
      e3e2a98e2bb5）——否则全 exempt 表会被「0/N 场景通过（全部失败）」误拦
      并按 env 阻塞升级，与申报豁免语义不符；但 env 豁免仍计入 env 通道
      （help-center 事故防线：env 不得借豁免通道放行 verified）。

    evo-fix-env-exemption-gate-conflict-…（1.2）：``env_exemptions`` 传入 spec
    级 STATE 豁免清单（``state_machine.parse_env_exemptions`` 产物，与升级
    握手同源）时，env 失败场景逐项查有效豁免（场景 id+归一化失败签名+场景
    定义 hash+时效，``find_env_exemption`` 同一纯函数），命中则该项不计入
    env 违规——豁免对场景级 env 不再是结构性死信（potplayer 2026-10-05：
    握手认可、本门 43ms 后同因拒绝）。0-pass 不变量与 fail-closed 语义保持：
    豁免只摘除 env 项，「0/N 通过（全部失败）」仍不得 verified；未传豁免
    （None/空）行为与本表其余不变量零变化。

    仅约束 verdict=verified；bug-found 不受限。Returns: 违规说明列表（空=放行）。
    """
    if verdict != "verified":
        return []
    if not isinstance(scenarios, list):
        # 非 list 场景表属结构损坏（code-review item c4f79c5c5fe9）：与空表
        # （ca52c2521b1f）/非 dict 条目同款 fail-closed——escalation 通道
        # `report.get("scenarios") or []` 会把非 list 真值（dict/非空字符串）
        # 原样传入，损坏输入不得比空表更宽
        return ["场景表结构损坏（非列表）不得判 verified"]
    if not scenarios:
        # 空列表 0/0 表（code-review item ca52c2521b1f）：零有效场景不构成
        # 验证通过证据，不得静默放行
        return ["0/0 场景执行（空场景表）不得判 verified"]
    # 豁免查询上下文（1.2）：与升级握手同源——场景定义 hash 表供「场景定义
    # 变更即失效」判定，时钟供 TTL 校验（测试注入）。缺省无 hash 证据（冻结
    # 文件不可得）不判失效，与 env_exemption_active 口径一致。
    from core.state_machine import find_env_exemption, scenario_fail_signature_body

    hashes = scenario_hashes if isinstance(scenario_hashes, dict) else {}
    total = len(scenarios)
    passed = 0
    env_failed: List[str] = []
    has_failed = False
    invalid_idx: List[str] = []
    for idx, sc in enumerate(scenarios, 1):
        if not isinstance(sc, dict):
            # 非 dict 条目属结构损坏：fail-closed 不静默跳过（与
            # validate_fast_track_result「场景 #N 非对象」同口径），否则
            # 全垃圾场景表会绕过本不变量在零有效场景上放行 verified
            invalid_idx.append(f"#{idx}")
            continue
        sid = str(sc.get("scenario_id") or "?")
        # 双词表对齐（item 229075ac0732）：与本模块其余函数同口径——"passed"
        # 亦为通过态（下游 verdict_evidence/pipeline 均按双词表防御），否则
        # 全过报告会被误判 0 通过而错误阻断合法 verified 裁决。
        status = sc.get("status")
        if status in ("pass", "passed"):
            passed += 1
        elif status == "exempt":
            # exempt＝申报豁免（fast-track 合法状态）：既不算通过也不算失败
            # （item e3e2a98e2bb5），不计入 has_failed。但 env 豁免仍须计入
            # env_failed——env 不得当作豁免理由放行 verified（help-center
            # 0/15 事故防线），豁免合法性（非 product-bug）由
            # validate_fast_track_result 的豁免逃逸检查把关。
            if sc.get("classification") == "env":
                _collect_env_failed(
                    sc, sid, env_failed, env_exemptions, hashes, now,
                    find_env_exemption, scenario_fail_signature_body,
                )
        else:
            has_failed = True
            if sc.get("classification") == "env":
                _collect_env_failed(
                    sc, sid, env_failed, env_exemptions, hashes, now,
                    find_env_exemption, scenario_fail_signature_body,
                )
    violations: List[str] = []
    if invalid_idx:
        violations.append(
            f"{len(invalid_idx)}/{total} 场景条目非对象（损坏场景表）不得判 verified: "
            + "、".join(invalid_idx[:8])
        )
    if has_failed and passed == 0:
        violations.append(f"0/{total} 场景通过（全部失败）不得判 verified")
    if env_failed:
        violations.append(
            "env 失败场景不得判 verified（须升级 admin 处置）: " + "、".join(env_failed[:8])
        )
    return violations


def _collect_env_failed(sc: dict, sid: str, env_failed: List[str],
                        env_exemptions, hashes: dict, now,
                        find_exemption, signature_body_fn) -> None:
    """env 失败场景计入违规前的豁免查询（whitewash_violations 内部助手）。

    无豁免上下文（env_exemptions 为空）零行为变化（既有口径原样计入）；
    有上下文时以「场景 id+归一化失败签名+定义 hash+时效」查有效豁免
    （与升级握手共享 find_env_exemption 同一纯函数），命中则该项豁免、
    不计入 env 违规。
    """
    if not env_exemptions:
        env_failed.append(sid)
        return
    hit = find_exemption(
        env_exemptions, sid, signature_body_fn(sc),
        current_hash=str(hashes.get(sid) or ""),
        now=now,
    )
    if hit is None:
        env_failed.append(sid)


def validate_report(report: dict) -> dict:
    """校验增强后的 report.json 分类与证据合规。

    Args:
        report: parse_report / json.loads(report.json) 解析出的 dict。

    Returns:
        {"ok": bool,
         "violations": [{"scenario_id", "status", "reason"}],
         "classified": [scenario_id...]}  # 合规的非 PASS 场景 id 列表
    """
    if not isinstance(report, dict):
        return {
            "ok": False,
            "violations": [
                {"scenario_id": None, "status": None, "reason": "report.json 非对象"},
            ],
            "classified": [],
        }

    scenarios = report.get("scenarios")
    if scenarios is None:
        # 缺 scenarios 键（旧格式 report.json）：无待校验对象，合规不变
        # （不阻塞 verified 路径）
        return {"ok": True, "violations": [], "classified": []}
    if not isinstance(scenarios, list):
        # 非 list 场景表（dict/非空字符串等真值）属结构损坏：与「场景 #N
        # 非对象」同款 fail-closed 记 violation 驱动 judge 重试（code-review
        # item 1575055d3bda），与 whitewash_violations（item c4f79c5c5fe9）
        # 口径一致——损坏输入不得比空表更宽；ok=True 放行会让重试链跳过
        # 证据校验，直到 whitewash 门才升级 admin 而非一次廉价重判
        return {
            "ok": False,
            "violations": [
                {
                    "scenario_id": None,
                    "status": None,
                    "reason": "场景表非列表（结构损坏）",
                }
            ],
            "classified": [],
        }

    violations: List[dict] = []
    classified: List[str] = []
    for idx, sc in enumerate(scenarios, 1):
        if not isinstance(sc, dict):
            # 非 dict 条目属结构损坏：记 violation（fail-closed，不静默放行；
            # 与 validate_fast_track_result「场景 #N 非对象」同口径）
            violations.append(
                {
                    "scenario_id": f"#{idx}",
                    "status": None,
                    "reason": f"场景 #{idx} 非对象",
                }
            )
            continue
        status = sc.get("status")
        if not _is_non_pass(status):
            continue
        sid = sc.get("scenario_id") or sc.get("id") or "?"
        classification = sc.get("classification")
        evidence = sc.get("evidence")

        if classification not in VERDICT_CLASSES:
            violations.append(
                {
                    "scenario_id": sid,
                    "status": status,
                    "reason": "classification 缺失或取值非法",
                }
            )
            continue
        if not _evidence_present(evidence):
            violations.append(
                {
                    "scenario_id": sid,
                    "status": status,
                    "reason": "evidence 为空",
                }
            )
            continue
        # 逐断言归因（add-interaction-contract-and-per-assert-triage D3）：
        # 每个 scenario 至多一条 violation（保持「一场景一违规」语义，便于重试定位）
        triage_reason = triage_violation(sc)
        if triage_reason:
            violations.append(
                {
                    "scenario_id": sid,
                    "status": status,
                    "reason": triage_reason,
                }
            )
            continue
        classified.append(sid)

    return {"ok": len(violations) == 0, "violations": violations, "classified": classified}


def enforce_status_mapping(report: dict) -> dict:
    """按分类-状态映射表强制重写场景 status（design D3）。

    规则：
      - classification ∈ {product-bug, test-defect} 但 status != failed
        → 强制 status=failed，并标记该条目为「已修正」（供报告标注，
        防止 LLM 输出漂移悬置产品缺陷）。
      - 逐断言归因（add-interaction-contract-and-per-assert-triage D3）：
        assertion_triage 中任一断言归类 ∈ {product-bug, test-defect} 但场景
        status != failed → 强制 failed（单条 product-bug 断言阻止场景级豁免）。
      - pass/passed 场景不参与强制改写（code-review item 5f76fe78291f）：
        正常产物 pass 场景不带 triage 与 FORCE_FAILED_CLASSES 分类，残留条目
        与 pass 状态自相矛盾，不据此把通过场景改写为 failed。
      - 其余（flaky / env 允许 warning，或已是 failed）→ 不动。

    返回：
        {"report": <原地增强后的 dict>,
         "corrected": [{"scenario_id", "from_status", "to_status",
                        "classification"}]}  # 被强制改写的条目
    注意：原地修改入参 report（与 verify_report.render 同约定，便于调用方直接
    写回文件）。
    """
    corrected: List[dict] = []
    if not isinstance(report, dict):
        return {"report": report, "corrected": corrected}
    scenarios = report.get("scenarios")
    if not isinstance(scenarios, list):
        return {"report": report, "corrected": corrected}

    for sc in scenarios:
        if not isinstance(sc, dict):
            continue
        classification = sc.get("classification")
        status = sc.get("status")
        # pass 场景不设防会误伤（code-review item 5f76fe78291f）：跨轮增量
        # 归因复用/judge 整体改写留下的 assertion_triage·classification 残留
        # 与 pass 状态自相矛盾，不得据此把通过场景改写为 failed（人为制造
        # 失败、误触发下游 whitewash_violations 的 0-pass 不变量打回）。仅
        # 豁免通过态（"pass"/"passed" 双词表，与 whitewash_violations /
        # tag_cached_attributions 同口径）；exempt 等其余状态维持既有改写——
        # 「单条 product-bug 断言阻止场景级豁免」（D3）不因本条放宽。
        if status in ("pass", "passed"):
            continue
        # 逐断言归因优先：失败断言级 product-bug/test-defect 强制 failed
        offending = None
        for t in triage_entries(sc):
            t_cls = t.get("classification")
            if t_cls in FORCE_FAILED_CLASSES:
                offending = t_cls
                break
        if offending is not None and status != "failed":
            from_status = status
            sc["status"] = "failed"
            sc["status_corrected"] = True
            sc["exempt_blocked_by_assertion"] = True  # 豁免被单断言阻断的留痕
            corrected.append(
                {
                    "scenario_id": sc.get("scenario_id") or sc.get("id") or "?",
                    "from_status": from_status,
                    "to_status": "failed",
                    "classification": offending,
                }
            )
            continue
        if classification in FORCE_FAILED_CLASSES and status != "failed":
            from_status = status
            sc["status"] = "failed"
            sc["status_corrected"] = True  # 报告标注「已修正」
            corrected.append(
                {
                    "scenario_id": sc.get("scenario_id") or sc.get("id") or "?",
                    "from_status": from_status,
                    "to_status": "failed",
                    "classification": classification,
                }
            )
    return {"report": report, "corrected": corrected}


def exempted_assertions(report: dict) -> List[dict]:
    """收集被豁免的失败断言（add-interaction-contract-and-per-assert-triage D4）。

    豁免 = 断言失败但不记产品 Bug：非 PASS 场景的 assertion_triage 中归类为
    test-defect / flaky / env 的条目（product-bug 条目进「真实产品 Bug」，不豁免）。

    Returns:
        [{"scenario_id", "assertion", "classification", "evidence", "reason"}]，
        供报告渲染「断言级豁免清单」。旧报告无 assertion_triage 时返回空表。
    """
    rows: List[dict] = []
    if not isinstance(report, dict):
        return rows
    scenarios = report.get("scenarios")
    if not isinstance(scenarios, list):
        return rows
    for sc in scenarios:
        if not isinstance(sc, dict):
            continue
        sid = str(sc.get("scenario_id") or sc.get("id") or "-")
        for t in triage_entries(sc):
            cls = t.get("classification")
            if cls == "product-bug":
                continue  # 产品缺陷不被豁免
            if cls not in VERDICT_CLASSES:
                continue
            evidence = t.get("evidence")
            if isinstance(evidence, (dict, list)):
                evidence = json.dumps(evidence, ensure_ascii=False)
            rows.append(
                {
                    "scenario_id": sid,
                    "assertion": str(t.get("assertion") or "-"),
                    "classification": cls,
                    "evidence": str(evidence or "-"),
                    "reason": str(t.get("reason") or EXEMPTION_REASON.get(cls, "-")),
                }
            )
    return rows


# ── 归因分级（add-verdict-credibility-gate / spec: verdict-attribution-evidence-gate）──
# 框架侧机械计算归因级别（design D2）：judge 只产出归因文本与证据引用，
# 级别由框架算出（不依赖 judge 自律与多模态能力）。
ATTRIBUTION_LEVEL_EVIDENCE_BACKED = "evidence-backed"
ATTRIBUTION_LEVEL_SPECULATIVE = "speculative"
ATTRIBUTION_LEVEL_PENDING_VISUAL = "pending-visual"
ATTRIBUTION_LEVELS = (
    ATTRIBUTION_LEVEL_EVIDENCE_BACKED,
    ATTRIBUTION_LEVEL_SPECULATIVE,
    ATTRIBUTION_LEVEL_PENDING_VISUAL,
)

# 视觉类断言关键词（用于 pending-visual 判定）
_VISUAL_ASSERTION_KEYWORDS = (
    "render",
    "style",
    "layout",
    "visual",
    "screenshot",
    "css",
    "screenshot_mismatch",
    "pixel",
    "image",
    "visible",
    "display",
    "color",
    "font",
    "border",
    "background",
)


def _scenario_has_substantive_evidence(scenario: dict) -> bool:
    """判断场景是否有「实质性证据」支撑归因（非空 evidence 构成）。

    实质性证据 = 非空截图列表 / 有算法标签 / 有 first_failed_step /
    有 failed_assertions / 有 first_frame_ok=False 结构化字段（异常事实；
    引擎侧只写 False，True 属无信息量默认态，与字段缺失同等处理）。

    evidence 形状防御（code-review item 803f6a23f662）：judge 产出非 dict
    （非空字符串等 truthy 形态）时按空 evidence 处理、保守降级 speculative
    路径，MUST NOT 抛 AttributeError——异常会被 escalation 门禁的
    「异常不阻断」分支吞掉，本应被抑制的 speculative 打回信号就此放行。
    """
    evidence = scenario.get("evidence")
    if not isinstance(evidence, dict):
        evidence = {}
    screenshots = evidence.get("screenshots") or scenario.get("screenshots") or []
    if isinstance(screenshots, list) and any(isinstance(s, str) and s.strip() for s in screenshots):
        return True
    # screenshot_labels 非 dict 按空处理（与 compute_attribution_level 的
    # item 6151f22ae34d 防御同口径：非 dict 真值在此被当「有算法标签」
    # 会把纯推测归因抬升为 evidence-backed，旁路 speculative 抑制门）。
    labels = scenario.get("screenshot_labels") or {}
    if not isinstance(labels, dict):
        labels = {}
    if labels:
        return True
    ffs = evidence.get("first_failed_step")
    if isinstance(ffs, str) and ffs.strip():
        return True
    # first_frame_ok 仅 False（异常事实）计为实质证据：引擎侧（core/verify_engine/
    # browser.py）只写 first_frame_ok=False，从不写 True——True 属无信息量默认态，
    # 与字段缺失同等处理。否则 judge 在 evidence 里伪造 first_frame_ok=true 即凑出
    # has_evidence，经 compute_attribution_level 末段返回 evidence-backed，旁路
    # should_suppress_bug_found 的 speculative 抑制（code-review item b96e297ffdaf）。
    if evidence.get("first_frame_ok") is False:
        return True
    if _scenario_has_failed_assertion_evidence(scenario):
        return True
    return False


def _scenario_has_failed_assertion_evidence(scenario: dict) -> bool:
    """场景是否有失败断言归因（assertion_triage 带非空 evidence）。"""
    triage = scenario.get("assertion_triage") or []
    if not isinstance(triage, list):
        return False
    for t in triage:
        if not isinstance(t, dict):
            continue
        ev = t.get("evidence")
        if isinstance(ev, str) and ev.strip():
            return True
        if isinstance(ev, dict) and ev:
            return True
    return False


def _is_product_bug_classification(classification: str) -> bool:
    """当前仅 product-bug 分类参与 pending-visual 判定（业务约束，
    非泛化的「是否涉及视觉现象」判定：test-defect/flaky/env 等一律 False）。"""
    return classification in ("product-bug",)


def _has_visual_assertions(scenario: dict) -> bool:
    """场景的失败断言是否涉及视觉现象。"""
    triage = scenario.get("assertion_triage") or []
    if isinstance(triage, list):
        for t in triage:
            if not isinstance(t, dict):
                continue
            assertion_text = str(t.get("assertion") or "").lower()
            evidence_text = str(t.get("evidence") or "").lower()
            for kw in _VISUAL_ASSERTION_KEYWORDS:
                if kw in assertion_text or kw in evidence_text:
                    return True
    ars = scenario.get("assertion_results") or []
    if isinstance(ars, list):
        for a in ars:
            if not isinstance(a, dict):
                continue
            if not a.get("pass", True):
                atype = str(a.get("type") or "").lower()
                if any(kw in atype for kw in _VISUAL_ASSERTION_KEYWORDS):
                    return True
    return False


def _flatten_screenshot_labels(labels) -> dict:
    """归一 screenshot_labels 的引擎嵌套形态为扁平标签并集。

    引擎侧（core/verify_engine/web_runner.py）写入场景级
    screenshot_labels 的形态是「{截图路径: 标签dict}」嵌套 dict——
    classify_screenshot 对正常截图也恒含量化指标（pixel_std /
    dominant_color_pct / width / height），仅判定异常时返回空 dict；
    而本模块消费点按扁平标签 dict 取值，嵌套形态下
    blank_screenshot / low_contrast 恒取 None/False，白屏/低对比度
    证据链路（compute_attribution_level 快速通道、
    enforce_blank_screenshot_direction 方向强制改写、
    tag_cached_attributions 纯缓存降级豁免）整体失灵
    （code-review item fdd31d3d542d）。

    规则：值为 dict 的键视为路径键、合并其标签；标量值键视为扁平标签
    原样保留（兼容混合形态）；全部值为标量（已是扁平形态）原样返回。
    非 dict 输入按空 dict 处理（沿用 item 6151f22ae34d / acc304e9e5c4
    的非 dict 防御口径，防 .get 抛 AttributeError 被门禁「异常不阻断」吞掉）。
    """
    if not isinstance(labels, dict):
        return {}
    if not any(isinstance(v, dict) for v in labels.values()):
        return labels
    flat: dict = {}
    for key, value in labels.items():
        if isinstance(value, dict):
            flat.update(value)
        else:
            flat[key] = value
    return flat


def compute_attribution_level(scenario: dict) -> str:
    """框架侧机械计算归因级别（design D2 / Task 2.1）。

    输入：增强后的 scenario dict（含 classification / evidence /
    assertion_triage / screenshot_labels / screenshots）。

    规则（与 judge 模型能力无关，只读证据构成）：
      - evidence-backed：归因引用了结构化证据（失败断言文本、算法标签、
        结构化字段如 first_frame_ok/blank_screenshot）且与证据不矛盾
      - speculative：归因仅为推理链推测（无截图、无算法标签、无结构化字段支撑）
      - pending-visual：归因涉及视觉现象（渲染/样式/布局类断言）但既无截图
        佐证也无算法标签（「截图佐证」指截图与失败断言归因证据共同支撑——
        截图仅在场而 assertion_triage 无非空归因证据时不构成佐证，仍判
        pending-visual，见函数体内规则序注释）

    Returns:
        归因级别字符串（ATTRIBUTION_LEVELS 之一）
    """
    classification = scenario.get("classification")
    if classification == "pass":
        return ATTRIBUTION_LEVEL_EVIDENCE_BACKED  # pass 场景不需要归因
    if classification is None:
        # 四分类未决（如 status=error 且未被归类）的非 PASS 场景不得沿用
        # evidence-backed（code-review item 383452d8eb38）：归因级别须与证据
        # 充分性对齐（docstring 三级定义），未决分类的归因没有结构化证据
        # 兜底，保守落 speculative 下界。影响有界：None 不∈
        # FORCE_FAILED_CLASSES，不构成 should_suppress_bug_found 的打回驱动
        # 场景，本分支只校准 report 标注口径。
        return ATTRIBUTION_LEVEL_SPECULATIVE

    # 归一引擎嵌套形态（{路径: 标签dict}）为扁平标签并集（code-review item
    # fdd31d3d542d）：web_runner 写入按截图路径嵌套，扁平直读使
    # blank_screenshot/low_contrast 恒取 None，白屏/低对比度快速通道恒不
    # 触发；非 dict 按空处理的既有防御（item 6151f22ae34d）已并入助手。
    labels = _flatten_screenshot_labels(scenario.get("screenshot_labels"))
    # 严格 is True 判定（code-review item 94bf2c34ded9），与下方 first_frame_ok
    # 的 is False 同款防伪造纪律：引擎侧（classify_screenshot）只写布尔 True、
    # 缺标签即正常态；若按任意真值判定，judge 改写 report 把标签值伪造成任意
    # 真值（"yes"/1）即可凑出 evidence-backed、旁路 should_suppress_bug_found
    # 的 speculative 抑制门——且归因分级在门禁管线（_run_attribution_gate /
    # _speculative_bug_found_gate）中先于 enforce_blank_screenshot_direction
    # 执行，不存在下游强制改写兜底，防线只能在取值处闭合。
    has_blank = labels.get("blank_screenshot") is True
    has_low_contrast = labels.get("low_contrast") is True
    has_labels = bool(labels)

    # 截图健全性标签是最强证据：白屏/低对比度均有算法标签佐证
    if has_blank or has_low_contrast:
        return ATTRIBUTION_LEVEL_EVIDENCE_BACKED

    # 有真实截图 + 有失败断言归因 → evidence-backed（视觉断言有截图佐证）
    # evidence 非 dict 按空处理（code-review item 803f6a23f662，与
    # _scenario_has_substantive_evidence 同款防御：非 dict 真值 .get 抛
    # AttributeError 会被门禁「异常不阻断」吞掉而旁路归因分级）。
    screenshots = scenario.get("screenshots") or []
    evidence = scenario.get("evidence")
    if not isinstance(evidence, dict):
        evidence = {}
    ev_screenshots = evidence.get("screenshots") or []
    has_real_screenshots = (
        isinstance(screenshots, list) and any(isinstance(s, str) and s.strip() for s in screenshots)
    ) or (
        isinstance(ev_screenshots, list)
        and any(isinstance(s, str) and s.strip() for s in ev_screenshots)
    )

    # 有算法标签 + 有失败断言归因 → evidence-backed
    if has_labels and _scenario_has_failed_assertion_evidence(scenario):
        return ATTRIBUTION_LEVEL_EVIDENCE_BACKED

    if has_real_screenshots and _scenario_has_failed_assertion_evidence(scenario):
        return ATTRIBUTION_LEVEL_EVIDENCE_BACKED

    # 归因涉及视觉现象但无截图/标签佐证 → pending-visual。只有有截图/有标签
    # 两路 evidence-backed 检测排在它之前（有截图时视觉断言可被证据支撑 →
    # evidence-backed）。有意设计（code-review item 78678bf1fa56）：它排在
    # first_failed_step+归因证据的通用 evidence-backed 检测之前——文字级归因
    # 证据不解除视觉类场景的 pending-visual，视觉断言仍待截图佐证
    # （tests/test_verdict_credibility_gate.py s7 钉死该顺序；下游
    # should_suppress_bug_found 对两级别同待遇）。
    # 「无截图佐证」的口径（code-review item a9b84150d10f）：佐证以截图与
    # 归因证据共同支撑为准——截图在场但 assertion_triage 无非空归因证据时，
    # 两路 evidence-backed 检测的合取条件不成立，仍穿透到本分支判
    # pending-visual；截图文件在场本身不构成佐证。
    if _is_product_bug_classification(classification):
        if _has_visual_assertions(scenario):
            return ATTRIBUTION_LEVEL_PENDING_VISUAL

    # 有 first_failed_step + 失败断言归因 → evidence-backed（视觉类场景已在
    # 上方先行判 pending-visual，不会走到这里）
    first_failed_step = evidence.get("first_failed_step") or ""
    if isinstance(first_failed_step, str) and first_failed_step.strip():
        if _scenario_has_failed_assertion_evidence(scenario):
            return ATTRIBUTION_LEVEL_EVIDENCE_BACKED

    # first_frame_ok=False 且分类为 env → evidence-backed（引擎结构化字段佐证）
    first_frame_ok = evidence.get("first_frame_ok")
    if first_frame_ok is False and classification == "env":
        return ATTRIBUTION_LEVEL_EVIDENCE_BACKED

    # 有其他证据但无法支撑分类 → 降级
    has_evidence = _scenario_has_substantive_evidence(scenario)
    if not has_evidence:
        return ATTRIBUTION_LEVEL_SPECULATIVE

    # 有失败断言归因但无截图/标签佐证 → 判断是否涉及视觉
    if _has_visual_assertions(scenario):
        return ATTRIBUTION_LEVEL_PENDING_VISUAL

    # 末端收口合取（code-review item 87289dd96917）：实质证据仅剩在场信号
    # （截图在场/弱标签/非 env 的 first_frame_ok）或纯推理链（含
    # first_failed_step 无佐证归因）而 assertion_triage 无逐条归因证据时，
    # 不得按 evidence-backed 收尾——validate_attribution_levels 与
    # validate_report 是两个独立入口，先打标后校验或只打标时 speculative
    # 抑制门不被在场证据旁路（正常管线 triage 覆盖且带证据不受影响）。
    # 有 first_failed_step 而无失败断言归因的「纯推理链」单独分支曾与此处
    # 等价返回 speculative，已并入本收口（code-review item e8f173ec0962）。
    if not _scenario_has_failed_assertion_evidence(scenario):
        return ATTRIBUTION_LEVEL_SPECULATIVE

    return ATTRIBUTION_LEVEL_EVIDENCE_BACKED


def validate_attribution_levels(report: dict) -> dict:
    """校验并写入 report.json 全部场景的 attribution_level（设计 D2 / Task 2.1）。

    在 report 落盘/打回上下文组装前调用（与 validate_report 同入口位）。
    原地修改每个非 PASS 场景的 attribution_level 字段。

    注：本函数无失败路径——只做归因级别的机械计算与原地写入，不产生
    校验失败信号；``ok`` 恒为 True、``violations`` 恒为空列表，返回结构
    仅为兼容既有调用签名（code-review item 90330728c61a）。真正的失败
    判定由下游 should_suppress_bug_found / check_batch_attribution_dedup
    等函数承担。

    Returns:
        {"ok": bool, "violations": [str, ...]}
    """
    if not isinstance(report, dict):
        return {"ok": True, "violations": []}
    scenarios = report.get("scenarios")
    if not isinstance(scenarios, list):
        return {"ok": True, "violations": []}
    violations = []  # 恒空：仅写入 attribution_level，无校验失败路径
    for sc in scenarios:
        if not isinstance(sc, dict):
            continue
        status = sc.get("status")
        if status in ("pass", "passed"):
            continue
        sc["attribution_level"] = compute_attribution_level(sc)
    return {"ok": True, "violations": violations}


def enforce_blank_screenshot_direction(scenario: dict) -> Optional[str]:
    """白屏方向约束（Task 2.3）：evidence 含 blank_screenshot: true 时归因
    必须引用该标签且限定 env 方向，不得归因于数据层或产品逻辑。

    框架强制改写：classification 不是 env → 改为 env（白屏有算法标签佐证，
    attribution_level 由 compute_attribution_level 判为 evidence-backed）。

    Returns:
        新的 classification（需要改写时）或 None（不需改写）。
    """
    # 归一引擎嵌套形态为扁平标签并集（code-review item fdd31d3d542d，与
    # compute_attribution_level 同款）：嵌套形态下 blank_screenshot 恒取
    # False，白屏方向强制改写恒不命中；非 dict 按空处理的既有防御
    # （item acc304e9e5c4）已并入助手。
    labels = _flatten_screenshot_labels(scenario.get("screenshot_labels"))
    # 严格 is True 判定（code-review item acefd3d40f80），与
    # compute_attribution_level（item 94bf2c34ded9）/ tag_cached_attributions
    # （item a9b61778a7ec）对 blank_screenshot 的消费同款防伪造纪律：引擎侧
    # （classify_screenshot）只写布尔 True、缺标签即正常态；宽松真值判定下
    # judge 改写标签为任意真值（"yes"/1）即可命中本分支被强制改写
    # classification="env"，把 product-bug 归因洗成 env 方向
    # （should_suppress_bug_found 视 env 为非驱动场景不计入打回判定）。
    if labels.get("blank_screenshot") is not True:
        return None
    classification = scenario.get("classification") or ""
    if classification == "env":
        return None
    return "env"


def should_suppress_bug_found(report: dict) -> bool:
    """打回依据全部为 speculative 时抑制 bug-found 打回（Task 2.2）。

    当全部「驱动打回的场景」（classification ∈ product-bug/test-defect，
    即会作为 bug 依据打回 implementer 的场景）的 attribution_level 均为
    speculative（无任何 evidence-backed / pending-visual）时，返回 True——
    应抑制 bug-found 打回：转重验一次或写 error「归因证据不足待人工复核」，
    不得带推测信号打回 implementer。

    非驱动场景（env/flaky/warning 等排除类）不参与判定——它们不构成打回依据。
    """
    if not isinstance(report, dict):
        return False
    scenarios = report.get("scenarios")
    if not isinstance(scenarios, list):
        return False
    driver_count = 0
    for sc in scenarios:
        if not isinstance(sc, dict):
            continue
        status = sc.get("status")
        if status in ("pass", "passed"):
            continue
        classification = sc.get("classification")
        if classification not in FORCE_FAILED_CLASSES:
            continue  # 非驱动场景（env/flaky 等）不参与打回判定
        driver_count += 1
        level = sc.get("attribution_level") or ATTRIBUTION_LEVEL_SPECULATIVE
        if level in (ATTRIBUTION_LEVEL_EVIDENCE_BACKED, ATTRIBUTION_LEVEL_PENDING_VISUAL):
            return False  # 至少一个驱动场景证据充分/待定，不抑制
    # 无驱动场景（全部 env/flaky 或全 PASS）→ 不存在 bug-found 打回依据
    return driver_count > 0


# ── 批量归因查重归一化细分（fix-verdict-dedup-resynthesis D3）──────────
# 16:39 事故解剖：judge 用脚本批量生成归因时 ``error[:120]`` 截断 + 共享模板串
# 使 5 个单根因级联场景完全坍缩——但它们的失败步骤序号/断言清单各异，归因高度
# 相似本是合法形态（前置步骤失败 → 后续场景级联失败），门的「逐字相同=偷懒」
# 假设对它失配。归一化细分：
#   - ``first_failed_step`` 拆「步骤序号 / 描述体」：步骤序号单独进指纹；
#     描述体哈希化（保持熵的同时避免整段原文撑爆指纹与 reason 摘录）；
#   - 步骤序号 / 断言清单任一不同 → 归一化即不同组，凑不满「≥3 同文」而放行
#     （合法级联由归一化拆分兜住；不设组内豁免分支——同组成员在步骤/断言/
#     描述体各分量上必然全等，豁免判定只会得到 False）；
#   - 纯模板偷懒（连步骤引用都逐字复制、断言也相同）→ 仍坍缩同组 → 拒绝。


def _extract_step_number(ffs_text) -> str:
    """从 first_failed_step 提取「步骤N」/「step N」前缀序号（无则空串）。

    归一化指纹细分用：步骤序号是区分「共享根因的合法级联」与「连步骤
    引用都复制的模板偷懒」的关键场景局部数据。
    """
    if not isinstance(ffs_text, str):
        return ""
    m = re.search(r"(?:步骤|step)\s*(\d+)", ffs_text, flags=re.IGNORECASE)
    return m.group(1) if m else ""


# code-review 6c9af9ec3805：跨模块（pm_engine.verification.verdict_evidence 等）复用
# 统一走公开名，模块边界不依赖下划线私有符号；私有名保留给模块内既有调用点。
# 别名直引同一实现，签名与行为随本体，无任何包装差异。
extract_step_number = _extract_step_number


def _first_failed_step_desc(ffs_text) -> str:
    """去除步骤序号前缀后的描述体（归一化空白后哈希进指纹）。"""
    if not isinstance(ffs_text, str):
        return ""
    return re.sub(
        r"^\s*(?:步骤|step)\s*\d+\s*[:：]?\s*",
        "",
        ffs_text,
        flags=re.IGNORECASE,
    ).strip()


def _normalize_whitespace(text) -> str:
    """空白折叠 + strip（归一化比较的统一前置）。"""
    # 形态归一（code-review item 87574a9c6a50）：非串真值（judge 产出字段被
    # 整体改写为 dict/int 等形态）直接进 re.sub 抛 TypeError，沿
    # triage_violation → validate_report 调用链外溢，被门禁「异常不阻断」
    # 降级后裁决证据校验被旁路。与 _clip_derived_text 同款：str 原样、
    # dict/list 用 json.dumps、其余 str()，不再依赖调用序隐式保证；falsy
    # 入参仍按 ``or`` 折空串兜底，字符串路径行为零变化。
    if text and not isinstance(text, str):
        if isinstance(text, (dict, list)):
            try:
                text = json.dumps(text, ensure_ascii=False, sort_keys=True)
            except (TypeError, ValueError):
                text = str(text)
        else:
            text = str(text)
    return re.sub(r"\s+", " ", (text or "")).strip()


def scenario_attribution_summary(sc: dict) -> str:
    """场景归因摘要（judge_attribution.json 条目 attribution 字段）。

    提取 classification + first_failed_step 关键片段 + 首条失败断言 label，
    拼接为 ≤200 字摘要，供逐场景条目落盘与场景级查重判定审计。字段缺失时
    返回空串（调用方按缺归因处理）。
    """
    parts = []
    cls = sc.get("classification")
    if isinstance(cls, str) and cls:
        parts.append(f"classification={cls}")
    evidence = sc.get("evidence")
    if isinstance(evidence, dict):
        ffs = evidence.get("first_failed_step")
        if isinstance(ffs, str) and ffs.strip():
            ffs_short = _normalize_whitespace(ffs)
            if len(ffs_short) > 80:
                ffs_short = ffs_short[:80] + "…"
            parts.append(f"first_failed_step={ffs_short}")
    triage = sc.get("assertion_triage")
    if isinstance(triage, list):
        for t in triage:
            if not isinstance(t, dict):
                continue
            assertion = str(t.get("assertion") or "").strip()
            if assertion:
                assertion_short = _normalize_whitespace(assertion)
                if len(assertion_short) > 60:
                    assertion_short = assertion_short[:60] + "…"
                parts.append(f"assertion={assertion_short}")
                break
    summary = "；".join(parts)
    if len(summary) > 200:
        summary = summary[:200] + "…"
    return summary


def _normalize_attribution(sc: dict) -> str:
    """归一化场景归因文本（strip + 空白折叠 + ffs 描述体哈希化）。

    fix-verdict-dedup-resynthesis 扩展：``first_failed_step`` 拆「步骤序号 /
    描述体」两步——步骤序号单独进指纹，描述体插哈希取前 32 位（保持熵的
    同时避免整段原文撑爆指纹）；断言 triage 的 assertion label 与 evidence
    保持原文进指纹（逐场景本就不同，保留即可区分）。

    返回值恒非空（裸 ``cls=`` 片保底）：无归因文本场景按裸 ``cls=`` 指纹
    参与同文分组而非跳过——级联豁免的锚点只能是框架结构化标记，无归因
    形态不得绕过「≥3 同文照拒」的防套用闸（否则 judge 整体省略归因即可
    逃避批量查重，test_signature_requires_structured_marker_not_text 钉死
    该契约）；违规 reason 对「归因为空」与「归因文本雷同」两种形态分开
    表述（code-review item de702496c0e5 方案②）。
    """
    parts = []
    classification = sc.get("classification") or ""
    parts.append(f"cls={classification}")
    evidence = sc.get("evidence") or {}
    if isinstance(evidence, dict):
        ffs = evidence.get("first_failed_step") or ""
        if isinstance(ffs, str) and ffs.strip():
            step = _extract_step_number(ffs)
            desc = _first_failed_step_desc(ffs)
            desc_digest = hashlib.sha256(_normalize_whitespace(desc).encode("utf-8")).hexdigest()[
                :32
            ]
            parts.append(f"step={step}:desc={desc_digest}")
    triage = sc.get("assertion_triage") or []
    if isinstance(triage, list):
        for t in triage:
            if isinstance(t, dict):
                assertion = str(t.get("assertion") or "").strip()
                cls = str(t.get("classification") or "").strip()
                ev = t.get("evidence")
                if isinstance(ev, str):
                    ev = ev.strip()
                else:
                    # None 才折空串（与 _clip_derived_text 同口径）：0/False
                    # 等假值是有信息量回传（如退出码），不得被 or 吞成空串
                    ev = ("" if ev is None else str(ev)).strip()
                parts.append(f"a={assertion}:c={cls}:e={ev}")
    normalized = " ".join(parts)
    return re.sub(r"\s+", " ", normalized).strip()


# ── 依赖级联同因组豁免（add-attribution-dedup-cascade-exemption 1.1/1.2）──
# 引擎对依赖失败传播场景合成的结构化标记（core/verify_engine/engine.py 写入
# dependency_skipped/skipped_depends_on + 统一跳过文案 + 空步骤/断言）。此类
# 场景的归因本就逐字相同（统一模板 + 空证据，无步骤/断言可细分，D3 归一化
# 拆分结构性不可用），同文不构成模板套用嫌疑——从「归一化逐字同文 ≥3 即拒」
# 判据单列豁免；混合组（含真实 failed 同文）仅对非级联子集计阈值，仍照拒。
# 豁免锚点用引擎结构化标记而非统一文案比对：文案改动不破坏豁免。
ENGINE_CASCADE_SKIP_FLAG = "dependency_skipped"
ENGINE_CASCADE_SKIP_DEPS = "skipped_depends_on"
# 框架合并后的豁免判据键（gate-owned）：仅由 merge_engine_cascade_markers 在
# 查重门前写入/清除。查重豁免判据只认该键——judge 报告自行申报的
# dependency_skipped 同名字段不作为豁免依据（防实现 run 伪标逃逸）。
ENGINE_CASCADE_EXEMPT_KEY = "_engine_dependency_skipped"
# 豁免段 reason 模板（与既有违规 reason 体系区分；留痕可审计豁免是否被滥用）
_ENGINE_CASCADE_EXEMPT_REASON = "同因级联组豁免（{count} 场景，dependency_skipped）"


def is_engine_cascade_scenario(sc: dict) -> bool:
    """判断场景条目是否携带引擎写入的依赖级联跳过结构化签名。

    引擎对依赖失败传播场景写入的完整签名（合成条目三要素）：标记位
    ``dependency_skipped is True`` + 级联来源清单 ``skipped_depends_on`` 非空
    + 合成状态 ``blocked-env``。三者缺一即签名不成立——judge 只申报标记位、
    或对真实 failed 场景伪标（status/执行形状与合成签名矛盾）时均不成立，
    豁免判据不认 judge 自行申报的同名字段。
    """
    if not isinstance(sc, dict):
        return False
    if sc.get(ENGINE_CASCADE_SKIP_FLAG) is not True:
        return False
    deps = sc.get(ENGINE_CASCADE_SKIP_DEPS)
    if not (isinstance(deps, list) and deps):
        return False
    return sc.get("status") == "blocked-env"


def merge_engine_cascade_markers(report) -> list:
    """框架结构化透传（add-attribution-dedup-cascade-exemption 1.0）。

    函数名沿用的「merge」是历史设计措辞，实际语义是**在 report 自身场景条目
    上归一 gate-owned 豁免判据键**（code-review item 629be6a8d312）：引擎在
    执行期已把 dependency_skipped/skipped_depends_on 结构化写入 report 场景
    条目自身，本函数不做任何跨数据源按 scenario_id 的合并/join——只在查重
    门前逐条目检查引擎结构化级联签名并归一到 ``_engine_dependency_skipped``：
    条目携带签名 → 置 True；否则清除该键（防 judge 上一轮写入的伪标/残留键
    经后续轮次洗白）。查重豁免判据只认本函数写入的键——该键在每次查重前被
    本函数全量重算覆写，judge 报告自行申报的 dependency_skipped 同名字段
    （无论写不写 gate-owned 键）都不构成豁免依据，防御在数据流层闭合。

    原地修改 report 场景条目。返回置标的场景 id 列表（留痕用）。
    """
    merged: list = []
    if not isinstance(report, dict):
        return merged
    scenarios = report.get("scenarios")
    if not isinstance(scenarios, list):
        return merged
    for sc in scenarios:
        if not isinstance(sc, dict):
            continue
        if is_engine_cascade_scenario(sc):
            sc[ENGINE_CASCADE_EXEMPT_KEY] = True
            merged.append(str(sc.get("scenario_id") or sc.get("id") or "?"))
        else:
            sc.pop(ENGINE_CASCADE_EXEMPT_KEY, None)
    return merged


def check_batch_attribution_dedup(report: dict) -> dict:
    """报告落盘前批量归因查重（Task 3.2 / D4；fix-verdict-dedup-resynthesis）。

    对全部非 PASS 场景归因归一化（strip + 空白折叠 + ffs 描述体哈希化）：
    ≥3 个场景逐字相同 → 拒绝采纳（返回 violations），要求逐场景归因后重合成。

    归一化细分（fix-verdict-dedup-resynthesis D3）：
    - 步骤序号进指纹——16:39 事故 5 个级联场景因 error[:120] 截断同文而误拒，
      但它们各自失败步骤/断言不同，是单根因级联失败的合法形态；
    - 步骤序号 / 断言清单任一不同 → 归一化即不同组，凑不满「≥3 同文」——
      合法级联由归一化拆分放行；
    - 纯模板偷懒（连步骤引用都逐字复制）→ 仍坍缩同组 → 拒绝。

    依赖级联同因组豁免（add-attribution-dedup-cascade-exemption 1.1）：携带
    引擎结构化透传标记（``merge_engine_cascade_markers`` 写入的 gate-owned
    键）的场景单列豁免，不参与同文分组；豁免信息随返回结构 ``exemptions``
    段留痕（组清单＋原因），与违规 reason 体系区分。

    Returns:
        {"ok": bool, "violations": [{"scenario_ids": [...], "reason": str}],
         "exemptions": [{"scenario_ids": [...], "reason": str}]}
    """
    return _batch_attribution_dedup_common(report, scenario_level=False)


def check_batch_attribution_dedup_scenario(report: dict) -> dict:
    """批量归因查重场景级判定（add-judge-incremental-attribution 2.1 / D2）。

    与 ``check_batch_attribution_dedup`` 同源归一化，但判定粒度
    从整批降为场景：命中重复（≥3 场景归一化后逐字相同）的
    场景归因置 ``requeue``（待回炉），其余非重复场景置 ``accept``（保留
    复用）——**MUST NOT 因子集重复废弃整轮已写盘归因**。依赖级联同因组
    豁免（add-attribution-dedup-cascade-exemption 1.1）同源生效：级联豁免
    场景不参与同文分组、按 accept 保留。

    Returns:
        {"ok": bool, "violations": [{"scenario_ids": [...], "reason": str}],
         "requeue_ids": [str],      # 命中重复、待回炉的场景 id
         "accept_ids": [str],       # 非重复、保留复用的场景 id
         "exemptions": [{"scenario_ids": [...], "reason": str}],
         "counts": {"total": int, "requeue": int, "accept": int}}
    """
    return _batch_attribution_dedup_common(report, scenario_level=True)


def _batch_attribution_dedup_common(report: dict, scenario_level: bool) -> dict:
    """批量归因查重的公共实现（整批 / 场景级两态共享）。

    scenario_level=False → 沿袭整批判定（仅返回 violations，拒绝由调用方
    按整批语义处置）；scenario_level=True → 追加 requeue_ids / accept_ids
    场景级粒度（调用方按设计 D2 驱动子集回炉）。

    退化输入（report 非 dict / scenarios 非列表）的早退分支同样保持与
    docstring 承诺一致的返回形状（场景级补齐空 requeue_ids / accept_ids /
    counts），避免调用方按下标访问时 KeyError。
    """
    extra: dict = {"exemptions": []}
    if scenario_level:
        extra = {
            "requeue_ids": [],
            "accept_ids": [],
            "exemptions": [],
            "counts": {"total": 0, "requeue": 0, "accept": 0},
        }
    if not isinstance(report, dict):
        return {"ok": True, "violations": [], **extra}
    scenarios = report.get("scenarios")
    if not isinstance(scenarios, list):
        return {"ok": True, "violations": [], **extra}

    groups: dict[str, list] = {}
    # 依赖级联同因组豁免（add-attribution-dedup-cascade-exemption 1.1）：
    # 携带框架结构化透传标记（merge_engine_cascade_markers 写入的 gate-owned
    # 键）的场景从「归一化逐字同文 ≥3 即拒」判据单列——引擎统一模板文案 +
    # 空证据使此类场景归因本就逐字相同，同文不构成模板套用嫌疑；且依赖跳过
    # 形态无步骤/断言可细分，D3 归一化拆分豁免对其结构性不可用。豁免判据只
    # 认框架合并的标记键，judge 自行申报的 dependency_skipped 同名字段不经
    # 此分支（签名校验在 merge 侧，status/执行形状矛盾即不置标）。
    cascade_exempt_ids: List[str] = []
    for sc in scenarios:
        if not isinstance(sc, dict):
            continue
        status = sc.get("status")
        if status in ("pass", "passed"):
            continue
        sid = str(sc.get("scenario_id") or sc.get("id") or "?")
        # [fenix-ignore:90c920fc9a9d] status=exempt 仅存在于 fast-track 结果文件
        # （走 validate_fast_track_result 校验，不经查重门）；本函数唯一消费链
        # _run_attribution_gate 只喂引擎 report.json，引擎/judge 均不产 exempt
        # 状态，「≥3 同分类 exempt 场景被误判回炉」前提不可达，无需增设豁免通道
        if sc.get(ENGINE_CASCADE_EXEMPT_KEY) is True:
            cascade_exempt_ids.append(sid)
            continue
        # norm 恒非空（cls 片保底）：无归因文本场景按裸 cls= 指纹参与同文
        # 分组，≥3 同文照拒（item de702496c0e5 方案②，防「整体省略归因」
        # 绕过批量查重）
        groups.setdefault(_normalize_attribution(sc), []).append(sid)

    violations = []
    requeue_ids: List[str] = []
    accept_ids: List[str] = []
    for norm_text, sids in groups.items():
        if len(sids) < 3:
            accept_ids.extend(sids)
            continue
        # 「归因为空」（仅分类相同，归一化后只剩裸 cls= 片）与「归因文本
        # 雷同」两种形态分开表述（item de702496c0e5）：前者并无归因文本可
        # 雷同，违规点是同批 ≥3 场景连归因都未提供，文案失真会误导仲裁
        if all(part.startswith("cls=") for part in norm_text.split(" ")):
            reason = (
                f"{len(sids)} 个场景均无归因文本（仅分类相同），"
                f"疑似批量套用/未做归因：涉及场景 {', '.join(sids)}"
            )
        else:
            reason = (
                f"{len(sids)} 个场景归因文本完全相同"
                f"（归一化后逐字相同），疑似批量套用硬编码归因："
                f"涉及场景 {', '.join(sids)}；"
                f"重复文本=[{norm_text[:200]}]"
            )
        violations.append({"scenario_ids": sids, "reason": reason})
        if scenario_level:
            requeue_ids.extend(sids)

    # 豁免决策留痕（add-attribution-dedup-cascade-exemption 1.2）：豁免=无
    # violations、不触发拒绝收口链，信息随返回结构豁免段（组清单＋原因）
    # 返回，由统一入口 _run_attribution_gate 记 info 日志，与既有违规
    # reason 体系区分，可事后审计豁免是否被滥用。
    exemptions: List[dict] = []
    if cascade_exempt_ids:
        exemptions.append(
            {
                "scenario_ids": cascade_exempt_ids,
                "reason": _ENGINE_CASCADE_EXEMPT_REASON.format(
                    count=len(cascade_exempt_ids)
                ),
            }
        )

    if not scenario_level:
        return {
            "ok": len(violations) == 0,
            "violations": violations,
            "exemptions": exemptions,
        }

    # 场景级：级联豁免场景视作保留（accept 复用，不进回炉）——豁免语义下
    # 其归因无套用嫌疑，MUST NOT 因豁免被回炉重写。
    accept_ids = cascade_exempt_ids + accept_ids
    # 场景级：norm 恒非空、非 pass 场景全部进入分组，accept/requeue 已覆盖
    # 全部参与判定的 id（含级联豁免场景），无需再补齐
    counts = {
        "total": len(accept_ids) + len(requeue_ids),
        "requeue": len(requeue_ids),
        "accept": len(accept_ids),
    }
    return {
        "ok": len(requeue_ids) == 0,
        "violations": violations,
        "requeue_ids": requeue_ids,
        "accept_ids": accept_ids,
        "exemptions": exemptions,
        "counts": counts,
    }


def tag_cached_attributions(report: dict, cache: dict, spec_name: str = "") -> list:
    """跨轮缓存归因打标（Task 3.1 / D3）。

    在 _verify_verdict_evidence 写回 report 前调用：对 verdict_cache 指纹
    命中的场景打 cached_from_previous_round: true + 来源轮次；纯缓存归因
    （无本轮新增 evidence-backed 证据）按 speculative 口径参与门禁。

    原地修改 report 的场景 dict。返回被打标的场景 id 列表。
    """
    if not isinstance(report, dict) or not isinstance(cache, dict):
        return []
    scenarios = report.get("scenarios")
    if not isinstance(scenarios, list):
        return []
    tagged_ids = []
    for sc in scenarios:
        if not isinstance(sc, dict):
            continue
        status = sc.get("status")
        if status in ("pass", "passed"):
            continue
        sid = str(sc.get("scenario_id") or sc.get("id") or "")
        entry = cache.get(sid)
        if not isinstance(entry, dict):
            continue
        fp = entry.get("fingerprint") or ""
        if not fp or fp != scenario_fingerprint(sc):
            continue
        sc["cached_from_previous_round"] = True
        cached_round = entry.get("source_round") or ""
        if cached_round:
            sc["cached_source_round"] = cached_round
        # 纯缓存归因（无本轮新增 evidence-backed 证据）→ 按 speculative 口径
        level = sc.get("attribution_level") or ATTRIBUTION_LEVEL_EVIDENCE_BACKED
        # 归一引擎嵌套形态为扁平标签并集（code-review item fdd31d3d542d，与
        # compute_attribution_level 同款）：嵌套形态下 blank_screenshot/
        # low_contrast 恒取 None，缓存命中场景借白屏/低对比度强标签豁免
        # 纯缓存降级的通道恒不命中；非 dict 按空处理的既有防御
        # （item 6151f22ae34d）已并入助手。
        labels = _flatten_screenshot_labels(sc.get("screenshot_labels"))
        # evidence 非 dict 按空处理（与 _scenario_has_substantive_evidence /
        # compute_attribution_level 的 item 803f6a23f662 防御同口径：非 dict
        # 真值 .get 抛 AttributeError 会被门禁「异常不阻断」吞掉，跨轮缓存
        # 打标与纯缓存归因降级 speculative 整段被跳过）。
        evidence = sc.get("evidence")
        if not isinstance(evidence, dict):
            evidence = {}
        ev_screenshots = evidence.get("screenshots") or []
        has_real_screenshots = isinstance(ev_screenshots, list) and any(
            isinstance(s, str) and s.strip() for s in ev_screenshots
        )
        # 严格 is True 判定（code-review item a9b61778a7ec）：与
        # compute_attribution_level（item 94bf2c34ded9）同款防伪造纪律——
        # 引擎侧只写布尔 True、缺标签即正常态；真值判定下 judge 改写缓存
        # 命中场景的标签为任意真值（"yes"/1）即可跳过纯缓存归因降级
        # speculative，违反 D3「纯缓存归因按 speculative 口径参与门禁」
        has_relevant_labels = (
            labels.get("blank_screenshot") is True
            or labels.get("low_contrast") is True
        )
        # 降级条件（code-review item 492b67e36689）：截图/强标签仅在场而
        # assertion_triage 无非空归因证据时不构成佐证（与 compute_attribution_level
        # item a9b84150d10f 的佐证口径对齐）——否则缓存命中场景（上轮
        # evidence-backed、本轮 evidence.screenshots 非空但 triage 无归因证据）
        # 借在场截图逃逸降级，speculative 抑制门被旁路，违反 D3「纯缓存归因
        # 按 speculative 口径参与门禁」（与 b96e297ffdaf/a9b61778a7ec 防逃逸
        # 纪律一致）。
        if not (
            (has_real_screenshots or has_relevant_labels)
            and _scenario_has_failed_assertion_evidence(sc)
        ):
            # 纯缓存归因 → 降级 speculative（无论原级别：设计 D3
            # 规定纯缓存归因按 speculative 口径参与 2.2 门禁，
            # 防止跨轮缓存归因逃逸推测级抑制）
            if level != ATTRIBUTION_LEVEL_SPECULATIVE:
                sc["attribution_level"] = ATTRIBUTION_LEVEL_SPECULATIVE
                sc["cached_override_level"] = True
        tagged_ids.append(sid)
    return tagged_ids


# ── fast-track 统一结果文件硬校验（add-fast-track-mode / D6）────────────
# 三要素：
#   ① 报告结构完整（场景/结果/判定字段齐全）
#   ② 场景全量执行（设计集与执行集一致，无静默遗漏；豁免走既有豁免规则）
#   ③ 逐场景证据存在性（非 PASS 场景带分类与证据）
# agent 文本宣称不作为通过依据——框架只信可校验的输出（与完整模式 verifier
# 的判定信任模型一致，design D6）。


def _scenario_evidence_ok(sc: dict) -> bool:
    """逐场景证据存在性：非 PASS 场景 MUST 带 classification 与 evidence。

    与 fast_track_result 的 SCENARIO_STATUSES 对齐，并按本模块双词表口径
    补齐 passed/failed（见 _FAST_TRACK_SCENARIO_STATUSES）；非 PASS 集合
    {fail, failed, error, warning} 复用本模块 NON_PASS_STATUSES 判定。
    exempt 场景单独走豁免合法性检查（_exempt_classification_ok），不在此
    要求 evidence（豁免＝不必提交证据）。
    """
    if not isinstance(sc, dict):
        return False
    status = sc.get("status")
    if status not in _FAST_TRACK_SCENARIO_STATUSES:
        return False
    if status in NON_PASS_STATUSES:
        if sc.get("classification") not in VERDICT_CLASSES:
            return False
        return _evidence_present(sc.get("evidence"))
    return True


# 单点定义承诺（fast_track_result docstring）：复用 core.fast_track_result.SCENARIO_STATUSES，
# 避免与解析器两处词表漂移。在此之上补齐 pass/passed 与 fail/failed 双词表
# （item 244fa0af2fba）：本模块 whitewash_violations / validate_attribution_levels
# 与 NON_PASS_STATUSES 均按双词表防御，agent 写出 "passed"/"failed" 时
# 不得被判为非法状态（否则全过报告会被误报「证据缺失」）。
_FAST_TRACK_SCENARIO_STATUSES = tuple(
    dict.fromkeys(SCENARIO_STATUSES + ("passed", "failed"))
)

# 豁免合法性：exempt 场景的分类 MUST 为非 product-bug（豁免逃逸检查，D6）
_EXEMPT_ALLOWED_CLASSES = ("test-defect", "flaky", "env")


def _exempt_classification_ok(sc: dict) -> bool:
    """豁免合法性：status=exempt 的场景分类必须非 product-bug。"""
    if sc.get("status") != "exempt":
        return True
    return sc.get("classification") in _EXEMPT_ALLOWED_CLASSES


def validate_fast_track_result(result: dict, designed_ids: Optional[list] = None) -> dict:
    """确定性校验 fast-track 统一结果文件的三要素（add-fast-track-mode D6）。

    Args:
        result: 解析后的 .fenix-run-result.json dict（含 verification 段）。
        designed_ids: 设计场景 ID 集合（来自 test_scenarios.json，或 fast-track
            结果自带验证段的场景 ID）。None/空时跳过「全量执行」比对（无设计集
            可比对时无法证明静默遗漏，仅做结构与证据校验）。

    Returns:
        {"ok": bool, "violations": [str, ...]}
        - 结构非法（缺 verification / 缺 scenarios / verdict 非法）→ 单条 violation
          （fail-closed，不静默通过）
        - 场景全量执行：每个设计 ID 必须在执行集中出现；缺失 → violation 列出
        - 逐场景证据：每个非 PASS 场景缺分类/证据 → violation 列出
        - 豁免逃逸：status=exempt 且分类 product-bug → violation（视为 bug 未修复）
    """
    violations: list = []
    if not isinstance(result, dict):
        return {"ok": False, "violations": ["fast-track 结果文件非对象"]}
    verification = result.get("verification")
    if not isinstance(verification, dict):
        return {"ok": False, "violations": ["fast-track 结果文件缺 verification 段"]}
    scenarios = verification.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        return {"ok": False, "violations": ["fast-track 结果文件 scenarios 缺失或为空"]}
    verdict = verification.get("verdict")
    if verdict not in ("verified", "bug-found"):
        return {"ok": False, "violations": [f"fast-track 结果文件 verdict 非法: {verdict!r}"]}

    for idx, sc in enumerate(scenarios):
        if not isinstance(sc, dict):
            violations.append(f"场景 #{idx + 1} 非对象")
            continue
        sid = sc.get("scenario_id") or f"#{idx + 1}"
        if sc.get("status") not in _FAST_TRACK_SCENARIO_STATUSES:
            violations.append(
                f"场景 {sid} status 非法: {sc.get('status')!r}"
                f"（合法取值: {'、'.join(_FAST_TRACK_SCENARIO_STATUSES)}）"
            )
        elif not _scenario_evidence_ok(sc):
            violations.append(
                f"场景 {sid} 证据缺失：非 PASS 场景 MUST 带合法 classification 与 evidence"
            )
        if not _exempt_classification_ok(sc):
            violations.append(
                f"场景 {sid} 豁免逃逸：status=exempt 但分类为"
                f" {sc.get('classification')!r}"
                f"（须为 {'、'.join(_EXEMPT_ALLOWED_CLASSES)} 之一；"
                "豁免不得掩盖产品缺陷，视为 bug 未修复）"
            )

    # 场景全量执行：设计集与执行集一致，无静默遗漏
    executed_ids = {
        str(sc.get("scenario_id"))
        for sc in scenarios
        if isinstance(sc, dict) and sc.get("scenario_id")
    }
    if designed_ids:
        missing = [str(d) for d in designed_ids if str(d) and str(d) not in executed_ids]
        if missing:
            violations.append(
                "场景静默遗漏："
                + "、".join(missing)
                + "（设计集存在但执行集缺失，框架校验不通过）。"
                "修复处方（二选一，禁止只改一边）："
                "① 在 .fenix-run-result.json 的 verification.scenarios 中补齐上述"
                "缺失场景条目，scenario_id 必须与 test_scenarios.json 的 id 逐字一致"
                "（执行集允许是设计集超集，可附加单元测试类场景）；"
                "② 若裁决时确属应合并/改名场景，同步重写 test_scenarios.json 使"
                "设计集与执行集一致"
            )

    return {"ok": len(violations) == 0, "violations": violations}


def load_report(project_root, spec_name) -> Optional[dict]:
    """读取 .fenix/verify-progress/<spec>/report.json；不可用返回 None。"""
    path = Path(project_root) / ".fenix" / "verify-progress" / spec_name / "report.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def save_report(project_root, spec_name, report: dict) -> None:
    """原子写回增强后的 report.json（temp + rename，与既有产物写回同约定）。"""
    path = Path(project_root) / ".fenix" / "verify-progress" / spec_name / "report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=".report.", suffix=".json.tmp")
    try:
        # fdopen 失败路径显式接管（对齐 serving_registry._write_unlocked 先例）：
        # with 的 close 只在 fdopen 成功接管后才生效，fdopen 自身抛错时裸 fd
        # 无人关闭——f 为 None 时兜底 os.close。
        f = None
        try:
            f = os.fdopen(fd, "w", encoding="utf-8")
            json.dump(report, f, ensure_ascii=False, indent=2)
            f.flush()
            # fsync 落盘后再 rename：掉电时防止 rename 已生效而内容未写盘，
            # 留下截断的裁决证据文件（与 state_machine/self_review 原子写同口径）
            os.fsync(f.fileno())
        finally:
            if f is not None:
                f.close()
            else:
                try:
                    os.close(fd)
                except OSError:
                    pass
        os.replace(tmp_path, path)
        # rename 生效后刷父目录项，防掉电后裁决证据整体回退为旧内容
        # （复用 admin_store._fsync_parent_dir，内部吞 EINVAL 等目录 fsync
        # 不支持的异常，尽力而为）
        _fsync_parent_dir(path)
    except (OSError, TypeError, ValueError):
        # json.dump 对不可序列化对象抛 TypeError/ValueError，同样须清理半成品
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ── 跨轮裁决缓存（judge 效率治理 2026-09-06）──────────────────────────
# 裁决耗时 ≈ 输出 tokens 量（实测 12 个 judge run 恒定 ~1300-2200 tok/min）。
# 重验轮的失败场景与上轮高度重叠（冻结场景集未变 + 失败复现一致），按断言
# 指纹命中即可沿用上轮结论，judge 免复现——写侧在裁决采纳处（verification
# _persist_verdict_cache），读侧在 judge 派发前（prompt_builder 注入段）。

VERDICT_CACHE_FILENAME = "verdict_cache.json"


def _verdict_cache_path(project_root, spec_name) -> Path:
    return Path(project_root) / ".fenix" / "verify-progress" / spec_name / VERDICT_CACHE_FILENAME


def scenario_fingerprint(scenario: dict) -> str:
    """非 PASS 场景的失败指纹：scenario_id + status + 失败断言/失败步骤稳定 hash。

    取引擎侧原始执行产物（judge 增强前，跨轮稳定），不取
    evidence/assertion_triage（judge 产物，轮间会重写）：
      - ``assertion_results`` 失败条目（type/layer/expected/actual/selector）；
      - ``step_results`` 中 success=False 条目的稳定字段（序号 + action/target
        标注 + error/detail 摘要，与 :func:`derive_default_failed_assertions`
        同源取值）——引擎侧「任一步骤失败即跳过断言执行」使该形态下
        assertion_results 必然为空表，只取失败断言会把指纹退化成
        sid+status 的哈希（失败步骤换了位置、错误文本完全不同指纹仍逐字
        相同），失败内容变化将无法使跨轮缓存失效。
    指纹一致 ⇒ 冻结场景与失败复现均未变，上轮结论可沿用。

    步骤失败字段仅在确有失败步骤时并入载荷：无失败步骤形态的载荷逐字
    不变（既有指纹值向后兼容）；步骤失败形态的指纹由此变化，旧缓存自然
    未命中 → 重裁一轮后写回新指纹（fail-open，不影响正确性）。

    已知局限（code-review item e543120876ae）：载荷不含 ``visual_results``，
    纯视觉差异失败（无失败断言、无失败步骤）场景的指纹退化为 sid+status
    的哈希——视觉基线变化不会使跨轮缓存键失效，上轮结论可被沿用。缓解在
    消费侧而非本函数：tag_cached_attributions 对指纹命中场景打
    cached_from_previous_round 并把纯缓存归因降级 speculative（不得驱动
    bug-found 打回，见 should_suppress_bug_found 的推测抑制门）；pipeline
    侧 PASS 场景复用对出处标注缺失与 fix diff 触碰均 fail-closed。不并入
    视觉摘要（visual_status/算法标签哈希）的取舍：并入会整体翻动既有缓存
    键（全部场景重裁一轮），且逐轮重算的量化指标/截图路径等易变分量可能
    使同内容失败的指纹逐轮漂移、缓存恒不命中，回归风险大于该有界盲区的
    收益。

    异常/缺字段返回空串（调用方按未命中处理，fail-open）。
    """
    try:
        failed = [
            {
                k: a.get(k)
                for k in ("type", "layer", "expected", "actual", "selector")
                if a.get(k) is not None
            }
            for a in (scenario.get("assertion_results") or [])
            if isinstance(a, dict) and not a.get("pass", True)
        ]
        step_failures = []
        for idx, s in enumerate(scenario.get("step_results") or [], 1):
            if not (isinstance(s, dict) and not s.get("success", True)):
                continue
            # 取值按「None 才折空串」口径（与 derive_default_failed_assertions
            # 同源）：or 链会把 0/False 等有信息量的假值回传（如退出码）先吞掉
            error = s.get("error")
            detail = s.get("detail")
            step_failures.append(
                {
                    "label": _step_failure_label(s, idx),
                    "error": _clip_derived_text(
                        error if error is not None else (detail if detail is not None else "")
                    ),
                }
            )
        payload_obj = {
            "sid": scenario.get("scenario_id"),
            "status": scenario.get("status"),
            "failed": failed,
        }
        if step_failures:
            payload_obj["step_failures"] = step_failures
        payload = json.dumps(
            payload_obj,
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    except (TypeError, ValueError, AttributeError):
        return ""


def load_verdict_cache(project_root, spec_name) -> dict:
    """读取跨轮裁决缓存；缺失/损坏返回 {}（fail-open）。"""
    p = _verdict_cache_path(project_root, spec_name)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_verdict_cache(project_root, spec_name, cache: dict) -> None:
    """原子写跨轮裁决缓存（每轮采纳后整体重写，消失/变化的场景自然出清）。

    写失败静默——缓存缺失只导致下轮全量重裁，不影响正确性。

    add-verify-lane-throughput 4.1：写入时自动注入顶层 ``_meta`` 特殊键
    （当前含 ``head_at_write`` = 写入时 git HEAD，修复轮 diff 失效判据的
    基准点）。``_meta`` 非场景条目，读侧消费方按 scenario_id 取条目不会
    误命中。
    """
    p = _verdict_cache_path(project_root, spec_name)
    payload = dict(cache) if isinstance(cache, dict) else {}
    if "_meta" not in payload:
        payload["_meta"] = {"head_at_write": compute_head_at_write(project_root)}
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        # tempfile.mkstemp 唯一临时文件 + os.replace：并发写同缓存时各进程 tmp
        # 互不覆盖，避免固定 .tmp 文件名下另一进程 write_text 轮中截断导致空文件落盘。
        fd, tmp_path = tempfile.mkstemp(dir=str(p.parent), prefix=".verdict_cache.", suffix=".json.tmp")
        try:
            # fdopen 失败路径显式接管（对齐 serving_registry._write_unlocked
            # 先例）：fdopen 自身抛错时裸 fd 无人关闭——f 为 None 时兜底
            # os.close。
            f = None
            try:
                f = os.fdopen(fd, "w", encoding="utf-8")
                json.dump(payload, f, ensure_ascii=False, indent=1)
                f.flush()
                # fsync 落盘后再 rename（与 save_report/state_machine 原子写同口径，
                # 防掉电留下截断缓存）
                os.fsync(f.fileno())
            finally:
                if f is not None:
                    f.close()
                else:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
            os.replace(tmp_path, p)
            # rename 生效后刷父目录项，防掉电后缓存整体回退为旧内容
            # （复用 admin_store._fsync_parent_dir，内部吞目录 fsync 不支持
            # 的异常，尽力而为；缓存侧本就 fail-open，不影响正确性）
            _fsync_parent_dir(p)
        except (OSError, TypeError, ValueError):
            # json.dump 对不可序列化对象抛 TypeError/ValueError，同样须清理
            # .tmp 半成品（code-review item c48f3a21b953，与 save_report 原子写
            # 的异常口径一致）
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except (OSError, TypeError, ValueError):
        # 写失败静默（见 docstring）：缓存缺失只导致下轮全量重裁，不影响正确性
        pass


# ── verdict 缓存键四元组（add-verify-lane-throughput 4.1，design 决策 6）──
# 采信判据 =（场景 id, 场景内容指纹, 被测构建指纹, 验证配置指纹）全等。
# 存疑即 fail-closed：任一分量缺失/不匹配 → 不采信缓存、照跑。


# 场景定义指纹的**白名单键**：只取定义性字段参与指纹。不采用「排除易变键」
# 的黑名单口径——写侧条目来自 report 场景 dict（键名 scenario_id、含执行
# 富集），读侧来自冻结文件 TestScenario.to_dict()（键名 id、归一形状），两侧
# 键集天然不同，黑名单无法归一；白名单（id 与 scenario_id 并收）保证同一
# 场景两侧投影一致。status/evidence/assertion_triage/classification/
# cached_source/attribution_level/assertion_results 等易变键天然不在白名单。
_SCENARIO_DEFINITION_KEYS = (
    "id",
    "scenario_id",
    "name",
    "description",
    "kind",
    "steps",
    "assertions",
    "depends_on",
    "visual_baseline",
    "external_net_errors_ok",
)

# 场景出处标注正则（description 末尾「文件:行号」形态，agents/planner-plan.md
# 出题规范）；文件扩展名覆盖被测应用常见源码/配置类型。
_SCENARIO_SOURCE_FILE_RE = re.compile(
    r"([\w./\\-]+\.(?:py|ts|tsx|js|jsx|mjs|vue|go|java|rb|php|sh|ya?ml|json|html|css|md)):(\d+)"
)

# 被测构建指纹的依赖/构建清单候选（取项目根现存文件集，不存在者跳过）。
_BUILD_MANIFEST_CANDIDATES = (
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "poetry.lock",
    "Pipfile",
    "Pipfile.lock",
    "setup.py",
    "setup.cfg",
    "Cargo.toml",
    "Cargo.lock",
    "go.mod",
    "go.sum",
)

# 嵌套清单递归收集的排除目录与深度上限（code-review item 95c65fc58fce）：
# monorepo/子应用形态（如 core/dashboard/static/package.json）的依赖清单
# 变更也须参与 build_fingerprint；排除依赖树/版本库/虚拟环境/字节码缓存/
# 框架配置目录，深度封顶防大仓全量遍历。
_BUILD_SCAN_PRUNE_DIRS = frozenset(
    {"node_modules", ".git", "venv", ".venv", "__pycache__", ".fenix"}
)
_BUILD_SCAN_MAX_DEPTH = 3  # 项目根下递归扫描的目录层数上限

# 验证配置文件路径（验证配置指纹数据源）。
_VERIFY_CONFIG_RELATIVE_PATH = ".fenix/verify.yaml"


def scenario_definition_fingerprint(scenario: dict) -> str:
    """场景定义内容指纹（缓存键分量②）：定义白名单键投影后稳定 hash。

    与 :func:`scenario_fingerprint`（非 PASS 断言指纹，判定失败复现）互补：
    本指纹判定「场景定义本身是否变化」——定义变 ⇒ 上轮结论作废（失效条件①）。
    白名单口径保证写侧（report 场景 dict）与读侧（TestScenario.to_dict()）
    两侧投影一致；易变键（status/evidence/assertion_triage 等）不在白名单，
    天然不影响指纹。异常/空载荷返回空串（fail-closed，按不可采信处理）。
    """
    try:
        payload = json.dumps(
            {k: scenario.get(k) for k in _SCENARIO_DEFINITION_KEYS},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    except (TypeError, ValueError, AttributeError):
        return ""


def _stable_file_hash(path: Path) -> str:
    """单文件内容 sha256；读取失败返回 ""（该文件视作缺席）。"""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _iter_build_manifest_files(root: Path):
    """递归收集构建清单文件：项目根 + 根下 _BUILD_SCAN_MAX_DEPTH 层目录。

    item 95c65fc58fce：只扫项目根会漏嵌套子应用清单（依赖升级改变被测行为
    而场景定义未变时，四元组缓存键全等、上轮归因结论被沿用）。目录按名排序
    展开（产出顺序确定，消费侧仍排序后哈希）；_BUILD_SCAN_PRUNE_DIRS 剪枝，
    不可读目录/条目静默跳过（与 _stable_file_hash 的 OSError 容错同口径）。
    """
    stack = [(root, 0)]
    while stack:
        cur, depth = stack.pop()
        try:
            children = sorted(cur.iterdir())
        except OSError:
            continue
        for child in children:
            try:
                if child.is_dir():
                    if (
                        depth < _BUILD_SCAN_MAX_DEPTH
                        and child.name not in _BUILD_SCAN_PRUNE_DIRS
                    ):
                        stack.append((child, depth + 1))
                elif child.is_file() and child.name in _BUILD_MANIFEST_CANDIDATES:
                    yield child
            except OSError:
                continue


def compute_build_fingerprint(project_root) -> str:
    """被测构建指纹（缓存键分量③）：依赖/构建清单文件集内容哈希。

    取项目根与受限深度子目录（``_BUILD_MANIFEST_CANDIDATES`` 名单内、排除
    ``_BUILD_SCAN_PRUNE_DIRS``）中现存清单文件的 (相对路径, 内容 hash) 集合
    稳定哈希。**不取 git HEAD**：修复通常不改依赖清单，以文件集为准可避免
    无关提交击穿缓存；「修复 diff 触碰场景出处文件」的文件级失效由 4.2
    消费侧以 head_at_write 基准另行判定，二者正交。

    项目根无任何清单 → 返回 ""（fail-closed：无法刻画被测构建则不采信）。
    根层清单的 parts 字符串（相对路径 == 文件名）与仅扫根层的旧口径逐字
    一致，既有缓存键不受影响；嵌套清单只做增量输入（安全方向：指纹失配
    按「缓存未命中照跑」处理）。
    """
    root = Path(project_root)
    parts = []
    for f in _iter_build_manifest_files(root):
        h = _stable_file_hash(f)
        if h:
            parts.append(f"{f.relative_to(root).as_posix()}:{h}")
    if not parts:
        return ""
    return hashlib.sha256("\n".join(sorted(parts)).encode("utf-8")).hexdigest()[:16]


def compute_verify_config_fingerprint(project_root) -> str:
    """验证配置指纹（缓存键分量④）：``.fenix/verify.yaml`` 内容哈希。

    配置缺失/读取失败 → ""（fail-closed：无法确认验证配置未变则不采信）。
    """
    f = Path(project_root) / _VERIFY_CONFIG_RELATIVE_PATH
    return _stable_file_hash(f)


def compute_head_at_write(project_root) -> str:
    """当前 git HEAD（写侧 ``_meta.head_at_write``）；失败返回 ""（fail-open）。"""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if out.returncode == 0:
            return (out.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def extract_scenario_source_files(description) -> Set[str]:
    """从场景 description 提取出处关联文件集（失效条件②的交集判据数据源）。

    出处标注形态 = ``文件路径:行号``（planner-plan 出题规范）。提取失败/无
    标注 → 空集（消费侧空集 ⇒ 交集必空 ⇒ 该场景按「出处未关联」处理，
    是否采信由调用方 fail-closed 策略决定）。
    """
    if not isinstance(description, str):
        return set()
    files = set()
    for m in _SCENARIO_SOURCE_FILE_RE.finditer(description):
        f = m.group(1)
        while f.startswith("./"):
            f = f[2:]  # 仅剥 ./ 前缀（lstrip 会误伤 ../ 相对段）
        if f:
            files.add(f)
    return files


def verdict_cache_entry_valid(
    entry: Any,
    scenario: dict,
    build_fingerprint: str,
    verify_config_fingerprint: str,
) -> bool:
    """缓存条目四元组采信校验（add-verify-lane-throughput 4.1）。

    全部成立才可采信：
      - 条目为对象且含定义指纹；
      - 被测构建指纹/验证配置指纹非空且与条目记载一致；
      - 场景定义指纹与当前场景一致（定义未变）。

    任一不成立（含分量缺失）→ False（fail-closed：存疑即照跑）。
    """
    if not isinstance(entry, dict):
        return False
    if not build_fingerprint or not verify_config_fingerprint:
        return False
    if entry.get("build_fingerprint") != build_fingerprint:
        return False
    if entry.get("verify_config_fingerprint") != verify_config_fingerprint:
        return False
    if not scenario:
        return False
    dfp = scenario_definition_fingerprint(scenario)
    if not dfp or entry.get("definition_fingerprint") != dfp:
        return False
    return True
