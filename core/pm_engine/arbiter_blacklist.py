"""arbiter_blacklist.py — Arbiter 处置动作黑名单单源（add-arbiter-blacklist-disposition D1）。

处置哲学反转（用户裁定「只有特定场景禁止处理，其他都应当能够救回 SPEC」）的
机械面单源：以「默认可救 + 枚举禁项」替换「白名单 + 判定反例」。本模块同时
承载两类消费方：

- **机械门**（resolved 硬门第一级，``core/pm_engine/arbiter.py`` 消费）：
  对 arbiter 报告的动作面（actions_taken / scenario_fixes / cleanup_paths /
  budget_override）跑机器可判定禁项谓词，命中即拒绝处置、自动降级 escalate。
- **prompt 文案**（``agents/arbiter.md`` 经 prompt_builder/run_arbiter 注入）：
  禁项段与处置哲学反转段文案由本模块渲染函数导出——文案与谓词同源，杜绝
  「prompt 与谓词双源漂移」（judge 写回受理门教训：机械门是唯一防线，prompt
  只引导；提示词约束会被模型漂移突破）。

命名消歧（D1）：本模块是**处置动作面**禁项（对报告动作放行判定），与链级
**触发面**黑名单 ``chain.blacklist``（信号入链过滤 kill switch，
escalation_chain.py 既有机制）不同层、互不冲突。

禁项枚举（spec arbiter-blacklist-disposition「B1–B5 禁项单源配置」）：
- B1 生产账本副作用：对 admin_alerts.json 等生产存储的状态变更（标记已处理、
  裁决消费、批量清理端点族）——consolidate-alerts 事故实锤：E2E 机器人对
  生产账本产生真实副作用（险些批量清剿 12 条生产告警）。
- B2 人工裁决通道代行：消费/关闭 judge_rerun_cap 裁决包、impl_unattainable
  确认等归属人工的裁决物。
- B3 破坏性动作直执：删除/覆写框架自有产物——场景文件经证明器门的成对写
  为唯一白名单例外。
- B4 验证契约放宽：断言期望弱化、场景删除、期望向实际看齐的自证（消费
  scenario_semantics 证明器判定）。
- B5 越界写：直写 STATE.md 本体、他 spec 分支、主树源码。

降级态（D9）：``arbiter_blacklist.enabled=false`` 时谓词全部直通放行、prompt
禁项段停用注入（回滚路径——行为与合入前一致，避免门直通而模型仍自缚保守
偏差）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── 配置单点（D9 降级态开关）─────────────────────────────────────────────

CONFIG_KEY_ENABLED = "arbiter_blacklist.enabled"
DEFAULT_ENABLED = True


def blacklist_enabled(project_root) -> bool:
    """读 ``arbiter_blacklist.enabled``（缺省 True；配置链故障按缺省降级）。

    false = D9 降级态：谓词全部直通放行（resolved 硬门第一级短路）、早期触发
    不发射、prompt 禁项段停用注入——回滚路径行为与合入前一致。
    """
    try:
        from core.config import ConfigLoader

        raw = ConfigLoader.resolve_config(Path(project_root))
        value = ConfigLoader.get(raw, CONFIG_KEY_ENABLED, DEFAULT_ENABLED)
    except Exception:
        return DEFAULT_ENABLED
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "0", "no", "off", "")
    return bool(value)


# ── 禁项枚举（编号/标题/prompt 文案——与谓词同源）─────────────────────────


@dataclass(frozen=True)
class BanItem:
    """单条禁项定义：编号、标题、prompt 禁项段文案。"""

    ban_id: str
    title: str
    prompt_text: str


BAN_ITEMS: tuple = (
    BanItem(
        "B1",
        "生产账本副作用",
        "生产存储写面禁碰：admin_alerts.json 等生产账本的状态变更（标记已"
        "处理、裁决消费、批量清理端点族 POST /api/alerts/clear / "
        "mark_all_handled、告警裁决消费端点执行）一律禁做——账本跨项目共享，"
        "机器人误处置生产告警不可逆。救回方案只读账本取证；需要变更生产"
        "告警状态时只产裁决包。",
    ),
    BanItem(
        "B2",
        "人工裁决通道代行",
        "归属人工的裁决物禁代行：消费或关闭 judge_rerun_cap 裁决包、"
        "impl_unattainable 确认、choice 终审执行等人工裁决通道动作一律禁做"
        "——只产裁决包交人工，不代替人拍板。",
    ),
    BanItem(
        "B3",
        "破坏性动作直执",
        "框架自有产物禁直删直覆：run 转录、verdict、验证报告、评审台账、"
        "场景文件本体（无门删除）等「看起来像框架产出」的文件一律禁删禁"
        "覆写。唯一例外：经证明器门获准的场景修复成对写（_scenarios_full."
        "json + test_scenarios.json 同契约版本戳）；无主坏产物删除走 "
        "cleanup_paths 由框架白名单校验执行。",
    ),
    BanItem(
        "B4",
        "验证契约放宽",
        "验证契约禁放宽：断言期望弱化（exact→宽泛匹配）、场景删除、期望向"
        "实际看齐的自证，凡 scenario_fixes 被证明器判净放宽且无获准正当性码"
        "即禁做——场景修复只允许收紧或中性改写。",
    ),
    BanItem(
        "B5",
        "越界写",
        "越界写面禁碰：直写 .fenix/STATE.md 本体（禁绕过 flock）、他 spec "
        "的分支/worktree/目录、主树源码（core/ agents/ tests/ 等）一律禁写"
        "——修复框架代码走报告 gaps 数组上报，不擅动。",
    ),
)

BAN_BY_ID: Dict[str, BanItem] = {b.ban_id: b for b in BAN_ITEMS}

# ── B1 生产账本副作用谓词素材 ────────────────────────────────────────────
# 批量清理端点族与告警状态写端点（consolidate-alerts 事故形态单源）。
_B1_ENDPOINT_RE = re.compile(
    r"(?:alerts?/clear|mark[_-]?all[_-]?handled|alerts?/[^/\s\"']*/handled"
    r"|alerts?/[^/\s\"']*/resolve|alerts?/[^/\s\"']*/choices?"
    r"|adjudication[_-]?choice|choices?/[^/\s\"']*/execute)",
    re.IGNORECASE,
)
# admin_alerts.json 状态写：文件名与写动词同句共现（只读取证合法，不命中）。
_B1_LEDGER_FILE_RE = re.compile(r"admin_alerts\.json", re.IGNORECASE)
# 写动词含 HTTP 方法动词（POST /api/... 即状态写意图）与 execute/落实——
# 裁决执行端点族（choices/<id>/execute）的动作文本常无中文写动词。
_WRITE_VERB_RE = re.compile(
    r"写|改写|覆写|覆盖|更新|修改|编辑|标记|置为|清空|清剿|删除|落实|"
    r"write|overwrit|updat|modif|edit|mark|clear|wipe|delet|execut|"
    r"\b(?:post|put|patch|delete)s?\b",
    re.IGNORECASE,
)

# ── B2 人工裁决通道代行谓词素材 ──────────────────────────────────────────
_B2_ADJUDICATION_RE = re.compile(
    r"(?:裁决包|adjudication[_-]?(?:choice|package)|judge[_-]?rerun[_-]?cap"
    r"|impl[_-]?unattainable|choice[_-]?id)",
    re.IGNORECASE,
)
_B2_CONSUME_VERB_RE = re.compile(
    r"消费|关闭|执行|代行|落实|终审|确认|拍板|选(?:择)?执行|"
    r"consum|clos|execut|confirm|acknowledge|resolv",
    re.IGNORECASE,
)

# ── B3 破坏性动作直执谓词素材 ────────────────────────────────────────────
# 框架自有产物（禁止无门删除/覆写）；场景文件名在其中——经证明器门获准的
# 成对写（scenario_fixes 申报）是唯一白名单例外，由调用方先摘除再扫。
_B3_ARTIFACT_RE = re.compile(
    r"(?:_scenarios_full\.json|test_scenarios\.json|report\.json|verdict"
    r"|\.jsonl|scenario_static_findings|contract_findings|run[_-]?result"
    r"|_run_harness|arbiter_ledger|escalation_chain_state)",
    re.IGNORECASE,
)
_DESTRUCTIVE_VERB_RE = re.compile(
    r"删除|删掉|清掉|覆写|覆盖|清空|truncate|rm\s|remove|delet|overwrit"
    r"|wipe",
    re.IGNORECASE,
)

# ── B5 越界写谓词素材 ────────────────────────────────────────────────────
# 前导锚边界语义（已知取舍写明）：\b 在汉字与字母之间不成立（Python re 中
# 汉字属 \w），不可用作锚定；ASCII 粘连误命中形态（如 NOTSTATE.md、
# testSTATE.md）由「锚字符须非字母/数字/下划线」继续防住。汉字区与中文/
# 全角标点区显式入锚——报告为中文语境，「覆写STATE.md」「修复core/ 配置」
# 等中文动词/标点与路径紧邻（无空格）书写不漏检（B5 是越界写唯一机械防线，
# 漏检面收敛优先）。
_CJK_BOUND = r"一-鿿　-〿！-～"
_B5_STATE_RE = re.compile(
    rf"(?:^|[\s/\"'`{_CJK_BOUND}])STATE\.md", re.IGNORECASE,
)
_B5_SOURCE_TREE_RE = re.compile(
    rf"(?:^|[\s/\"'`{_CJK_BOUND}])"
    r"((?:core|agents|tests|bin|docs|spec/knowledge)(?:/[\w.\-/]*)?)",
)
# 他 spec 分支/worktree 写面：impl-<spec> worktree 路径携带非本 spec 名。
_B5_WORKTREE_RE = re.compile(
    r"\.claude/worktrees/(?:impl|plan|verify|fasttrack)[-_]([\w.\-]+)",
)
# 本 spec worktree 余段边界：目录名契约 = ``<spec>-<纯数字时间戳>``
# （create() ``f"{prefix}-{spec_name}-{timestamp}"``，ts 恒为
# int(time.time())），故 spec 名之后只允许空段或 ``-<纯数字>``。
_B5_OWN_WORKTREE_SUFFIX_RE = re.compile(r"-\d+")
_REPORT_SPEC_STRIP_RE = re.compile(r"[^A-Za-z0-9._\-]")


def _surface_texts(report: dict) -> List[tuple]:
    """拉平报告动作面文本（surface 名 + 文本）供谓词扫描。

    覆盖 spec 钉死的四类动作面：actions_taken / scenario_fixes（逐条
    file/fix_class/summary/justification 等字符串字段）/ cleanup_paths /
    budget_override——summary/root_cause 等叙述性字段**不**在扫描面（叙述
    引用端点形态不等于执行动作，防「报告里提到事故」误命中）。
    """
    texts: List[tuple] = []
    for i, act in enumerate(report.get("actions_taken") or []):
        if isinstance(act, str) and act:
            texts.append((f"actions_taken[{i}]", act))
    fixes = report.get("scenario_fixes")
    if isinstance(fixes, dict):
        fixes = [fixes]
    for i, fix in enumerate(fixes or []):
        if isinstance(fix, dict):
            for key in ("file", "fix_class", "summary", "justification", "note"):
                v = fix.get(key)
                if isinstance(v, str) and v:
                    texts.append((f"scenario_fixes[{i}].{key}", v))
        elif isinstance(fix, str) and fix:
            texts.append((f"scenario_fixes[{i}]", fix))
    for i, p in enumerate(report.get("cleanup_paths") or []):
        if isinstance(p, str) and p:
            texts.append((f"cleanup_paths[{i}]", p))
    bo = report.get("budget_override")
    if isinstance(bo, str) and bo:
        texts.append(("budget_override", bo))
    return texts


def _hit(ban_id: str, surface: str, detail: str) -> dict:
    return {"ban_id": ban_id, "surface": surface, "detail": detail[:400]}


def _split_declarations(texts: List[tuple]):
    """拆分扫描面：非申报面逐条 (surface, text)；scenario_fixes 申报面按
    **整条**联结（同条申报的 file 字段产物名 + summary 字段破坏动词跨字段
    分布，逐字段共现判定会漏——申报条目是动作的最小语义单元）。

    owner 归属 ``split`` 直接取点前段即等价：四类动作面 surface 中仅
    scenario_fixes 申报条目字段带点（``scenario_fixes[i].file`` 等），其余
    （actions_taken[i] / cleanup_paths[i] / budget_override / 字符串型申报
    scenario_fixes[i]）均不带点，split 原样返回自身。"""
    plain: List[tuple] = []
    decls: Dict[str, List[str]] = {}
    for surface, text in texts:
        owner = surface.split(".", 1)[0]
        if owner.startswith("scenario_fixes"):
            decls.setdefault(owner, []).append(text)
        else:
            plain.append((surface, text))
    return plain, [(k, "；".join(v)) for k, v in decls.items()]


def _scan_b1(texts: List[tuple]) -> List[dict]:
    """B1 生产账本副作用：批量清理端点族/告警状态写端点/账本文件状态写。"""
    hits: List[dict] = []
    plain, decls = _split_declarations(texts)
    for surface, text in plain + decls:
        m = _B1_ENDPOINT_RE.search(text)
        if m and _WRITE_VERB_RE.search(text):
            hits.append(_hit(
                "B1", surface,
                f"生产账本端点动作面命中（{m.group(0)}）：{text[:160]}",
            ))
            continue
        if _B1_LEDGER_FILE_RE.search(text) and _WRITE_VERB_RE.search(text):
            hits.append(_hit(
                "B1", surface,
                f"生产账本文件状态写面命中（admin_alerts.json × 写动词）："
                f"{text[:160]}",
            ))
    return hits


def _scan_b2(texts: List[tuple]) -> List[dict]:
    """B2 人工裁决通道代行：裁决包/裁决物与消费动词共现。"""
    hits: List[dict] = []
    seen: set = set()
    plain, decls = _split_declarations(texts)
    for surface, text in plain + decls:
        if _B2_ADJUDICATION_RE.search(text) and _B2_CONSUME_VERB_RE.search(text):
            key = (surface, text[:120])
            if key in seen:
                continue
            seen.add(key)
            hits.append(_hit(
                "B2", surface,
                f"人工裁决物消费/关闭面命中：{text[:160]}",
            ))
    return hits


# 证明器放行判定（单源；B3 门摘除与 resolved 硬门②同口径）：申报
# prover_verdict 须携带 pass——接受证明器 to_summary() 全文形态
# （「证明器净判定：pass（…）」）或裸 "pass" 词；reject 摘要/缺失不匹配。
PROVER_PASS_RE = re.compile(r"证明器净判定[：:]\s*pass|^pass\b", re.IGNORECASE)


def prover_verdict_pass(verdict_text) -> bool:
    """申报 ``prover_verdict`` 文本是否携带证明器放行判定。"""
    return bool(PROVER_PASS_RE.search(str(verdict_text or "").strip()))


def _gated_scenario_fix_surfaces(report: dict) -> set:
    """经证明器门获准（prover_verdict 携带 pass）的场景修复申报 surface 前缀集。

    B3 的唯一白名单例外：成对写申报须逐条携带 ``prover_verdict`` 放行判定
    （裸 "pass" 词或证明器 to_summary 全文形态）才摘出扫描面——无门/被拒
    申报照常参与 B3 扫描。
    """
    prefixes: set = set()
    fixes = report.get("scenario_fixes")
    if isinstance(fixes, dict):
        fixes = [fixes]
    for i, fix in enumerate(fixes or []):
        if isinstance(fix, dict) and prover_verdict_pass(fix.get("prover_verdict")):
            prefixes.add(f"scenario_fixes[{i}]")
    return prefixes


def _scan_b3(report: dict, texts: List[tuple]) -> List[dict]:
    """B3 破坏性动作直执：框架自有产物删除/覆写（经门成对写摘除后扫描）。"""
    gated = _gated_scenario_fix_surfaces(report)
    hits: List[dict] = []
    seen: set = set()
    plain, decls = _split_declarations(texts)
    for surface, text in plain + decls:
        # surface 归属：scenario_fixes[i] 整条联结面（门按申报条目摘除）；
        # split 取点前段对全部 surface 形态等价（依据见 _split_declarations）
        owner = surface.split(".", 1)[0]
        if owner in gated:
            continue
        if _B3_ARTIFACT_RE.search(text) and _DESTRUCTIVE_VERB_RE.search(text):
            key = (surface, text[:120])
            if key in seen:
                continue
            seen.add(key)
            hits.append(_hit(
                "B3", surface,
                f"框架自有产物破坏性直执面命中：{text[:160]}",
            ))
    return hits


def _scan_b5(report: dict, texts: List[tuple]) -> List[dict]:
    """B5 越界写：STATE.md 本体直写 / 他 spec 分支与 worktree / 主树源码。

    与 B1/B2/B3 同联结口径：scenario_fixes 申报按整条联结扫描（目标路径在
    file 字段、写动词在 summary 字段的跨字段分布不漏检），非申报面逐条。"""
    spec_norm = _REPORT_SPEC_STRIP_RE.sub("", str(report.get("spec") or ""))
    hits: List[dict] = []
    seen: set = set()
    plain, decls = _split_declarations(texts)
    for surface, text in plain + decls:
        if not _WRITE_VERB_RE.search(text):
            continue
        reasons: List[str] = []
        if _B5_STATE_RE.search(text):
            reasons.append("STATE.md 本体直写")
        for m in _B5_SOURCE_TREE_RE.finditer(text):
            # 主树源码树写面（spec/ 目录在飞改动提交是许可 6 合法面，不在词表）
            reasons.append(f"主树源码树写面（{m.group(1)}）")
            break
        for m in _B5_WORKTREE_RE.finditer(text):
            owner = _REPORT_SPEC_STRIP_RE.sub("", m.group(1))
            if spec_norm and owner:
                # 本 spec 判定按目录名契约收紧（双向子串松匹配会让共享前缀
                # 的异名 spec 互相豁免，如 add-arbiter-blacklist 与
                # …-disposition、同族 fix-* 变体）：owner 全等 spec_norm，
                # 或 spec_norm 为 owner 前缀且余段恰为 ``-<纯数字时间戳>``
                # （见 _B5_OWN_WORKTREE_SUFFIX_RE 契约注记），其余形态一律
                # 判他 spec。
                rest = (
                    owner[len(spec_norm):]
                    if owner.startswith(spec_norm) else None
                )
                if rest is None or not (
                    rest == "" or _B5_OWN_WORKTREE_SUFFIX_RE.fullmatch(rest)
                ):
                    reasons.append(f"他 spec worktree 写面（{m.group(1)}）")
                    break
        if reasons:
            key = (surface, text[:120])
            if key in seen:
                continue
            seen.add(key)
            hits.append(_hit("B5", surface, "；".join(reasons) + f"：{text[:160]}"))
    return hits


def scan_report(report: dict, project_root=None) -> List[dict]:
    """黑名单谓词扫描（B1/B2/B3/B5 文本谓词；B4 消费证明器判定另行接线）。

    Args:
        report: arbiter 调查报告 dict（outcome=resolved 时由 resolved 硬门
            调用；escalate 报告不扫描——禁项面约束的是「申报处置」不是
            「申报升级」）。
        project_root: 项目根（缺省 None 不查开关）。传入时读
            ``arbiter_blacklist.enabled``——false（D9 降级态）谓词全部
            直通放行返回空列表（降级态与测试逃生门）。

    Returns:
        命中列表（每条 {ban_id, surface, detail}）；空列表 = 放行。谓词
        异常按单禁项隔离、扫描整体异常按放行降级（不因单谓词故障放大拒判
        面——保守方向是「少拒」：误报拒绝烧人工注意力，漏报放行）。注意
        漏报方向**没有人工兜底**：谓词故障放行时 resolved 照常受理、命中
        被漏检的动作面既不被拒绝也不进入人工复核，兜底仅剩 prompt 禁项
        引导（文案与谓词同源注入）与处置台账留痕的可审计性——本门自身
        不做漏报告警。
    """
    if not isinstance(report, dict):
        return []
    if project_root is not None and not blacklist_enabled(project_root):
        return []
    try:
        texts = _surface_texts(report)
        hits: List[dict] = []
        for scanner in (_scan_b1, _scan_b2):
            try:
                hits.extend(scanner(texts))
            except Exception:  # noqa: BLE001 — 单谓词故障不放大拒判面
                pass
        try:
            hits.extend(_scan_b3(report, texts))
        except Exception:  # noqa: BLE001
            pass
        try:
            hits.extend(_scan_b5(report, texts))
        except Exception:  # noqa: BLE001
            pass
        return hits
    except Exception:  # noqa: BLE001 — 扫描整体故障按放行降级（宁漏报不误报）
        return []


def b4_hit_from_prover(verdict_summary: str) -> Optional[dict]:
    """B4 验证契约放宽：消费证明器判定（拒绝即 B4 命中）。

    Args:
        verdict_summary: 证明器净判定摘要（``scenario_semantics`` 输出的
            human-readable 判定文本；空串/放行态返回 None）。
    """
    if not verdict_summary:
        return None
    return _hit("B4", "scenario_fixes", f"证明器拒绝（净放宽未获准）：{verdict_summary}")


# ── prompt 文案渲染（与谓词同源；D5 保骨架、enabled=false 停用注入）───────

# 回滚态（enabled=false）注入的原文案——与合入前 agents/arbiter.md 的
# 「升级偏向」段与判定反例行逐字一致，兑现「回滚态 prompt 行为与合入前
# 一致」（任务书 1.1）。
_LEGACY_DISPOSITION_SECTION = """## 升级偏向（写死的价值排序：假阴性无害、假阳性危险）
- 拿不准 = 升级。白名单外的一切（产品缺陷终裁、无考古证据的场景集语义取舍、逻辑矛盾、预算政策、任何需要「我认为应该这样设计」的判断）MUST 只产裁决包，MUST NOT 擅动状态。
- 证据不足时不脑补：考古找不到足够证据链（至少两处独立来源互证）就 escalate。
- 处置动作不可逆或影响面超出单 spec 时， escalate。
- 你的产出被消费的形态：`outcome=resolved` 时框架执行解冻/清理收尾并终态化告警；`outcome=escalate` 时裁决包原位挂靠告警推送人类。宁可让人类多看十个裁决包，不可让框架错误地自主改一次状态。

白名单外的判定反例（MUST escalate）：「这个测试应该改断言」「这个设计决策选 A 不选 B」「预算应该调大」「这个产品 bug 应该这样修」。"""

_BLACKLIST_MODE_SECTION_TEMPLATE = """## 处置哲学（黑名单制：默认可救）
处置焦点反转：判定对象由「是否在白名单内」反转为「**是否命中禁项**」。禁项外一律默认可救——场景鲁棒性修复、稳态复跑、稳态态修复等机械可判的救回动作应当做，MUST NOT 以「白名单外」为由放弃可救回的 SPEC；只有命中下方禁项时才 MUST 只产裁决包。

## 禁项判定（B1–B5，机械门与本文案同源；命中即只产裁决包）
{ban_lines}

## 救回工具箱（禁项域内的两类救回工具，产出即救回证据）
- **T1 场景鲁棒性修复**（机械修复类白名单）：选择器向 fixture/种子标记作用域化、expect_network 守卫收紧到记录级路径、等待时序加固、破坏性场景转安全变体（拆除确认点击改机械形态断言）。修复 MUST 走证明器门获准后的场景成对写（`_scenarios_full.json` + `test_scenarios.json` 同契约版本戳），申报进报告 `scenario_fixes`。
- **T2 稳态复跑探针**：对失败面在稳态 checkout/实例上**只读**复跑（MUST NOT 变更任何账本状态），结果落报告 `rescue_evidence` 的 `probe_transient` 证据类；探针复现同一失败时 MUST NOT 申报 resolved——产裁决包附探针产物升级人工。
"""


def render_ban_section() -> str:
    """禁项段文案（B1–B5 逐条渲染，与谓词同源）。"""
    lines = []
    for item in BAN_ITEMS:
        lines.append(f"- **{item.ban_id} {item.title}**：{item.prompt_text}")
    return "\n".join(lines)


def render_mode_sections(project_root) -> Dict[str, str]:
    """按 enabled 渲染 prompt 注入段（prompt_builder / run_arbiter 消费）。

    Returns:
        ``{"mode_section", "writable_surface_note"}``：
        - enabled=True：``mode_section`` = 处置哲学反转段 + 禁项判定段 +
          救回工具箱段；``writable_surface_note`` = 红线 2 修订注记。
        - enabled=False（D9 降级态）：``mode_section`` = 合入前原文案
          （升级偏向段 + 判定反例行逐字）；``writable_surface_note`` =
          空串（回滚态红线 2 与合入前一致）。
    """
    if blacklist_enabled(project_root):
        return {
            "mode_section": _BLACKLIST_MODE_SECTION_TEMPLATE.format(
                ban_lines=render_ban_section(),
            ),
            "writable_surface_note": (
                "；黑名单态唯一扩展可写面：经证明器门获准的场景修复成对写"
                "（`_scenarios_full.json`+`test_scenarios.json` 同契约版本戳）"
            ),
        }
    return {"mode_section": _LEGACY_DISPOSITION_SECTION, "writable_surface_note": ""}
