"""
admin_monitor_text_rules.py — AdminMonitor 处置文本豁免/回拨的纯文本判定规则。

从 core/admin_monitor.py 抽出的纯函数模块（code-review a132ca295b06）：
family_explosion「放行一次」豁免位（_family_waiver）与 infra 回拨
（reclassify N rounds）的处置文本识别常量与判定逻辑。只做文本 → 布尔/轮次
的纯判定，不落任何状态、不打日志、不依赖 AdminMonitor 实例——副作用
（写豁免位、调 pm_engine 回拨、审计留痕）仍由 AdminMonitor 的
_apply_family_waiver / _apply_infra_reclassification 承载。
"""

import re

# family_explosion 放行文本兜底：仅当处置文本表达「显式放行」语义时才写豁免位。
# 2026-08-28 实证（fix-fix-fix-add-spec-context-menu）：旧的「包含 _family_waiver/
# 放行/waive 令牌即放行」宽松匹配，把处置叙述中否定句里的字面令牌（如
# 「明确不发放 _family_waiver」）误判为放行动作，给未放行的父 SPEC 错误写入
# _family_waiver=true。改为：命中否定短语即不放行；否则须命中赋值型/明确动词型
# 放行模式才写位。
# 2026-08-28 二次实证（fix-fix-fix-improve-failover-model-mapping-ui，admin run
# 1787945929）：否定清单缺「未发放/未放行」等完成时否定，且赋值型模式命中了处置
# 叙述里对【另一族谱】豁免位的提及（「全库唯一的 _family_waiver=true 在另一族谱」
# ——与本困境无关），双重误判给已终态父 SPEC 错误写入 _family_waiver=true。
# 修正：a) 否定清单补完成时/委婉否定；b) 赋值型/动词型模式须与「放行」动词在同句
# 才算放行（单纯提及字段名/他族谱状态不构成放行）。
# code-review 4dd652206902 补修：b) 的分句判定当时只落到赋值型兜底 _WAIVER_ASSIGN_RE，
# 动词型模式（同意放行/放行一次/经评估放行）仍在拼接全文上匹配且无同句限定——
# 处置叙述提及其他族谱/历史放行（「另一族谱已同意放行」「父 SPEC 此前已放行过
# 一次」且不含任何否定短语）会给未放行的本族父 SPEC 误写 _family_waiver=true。
# 现动词型模式同样分句判定，且命中句须含「本次处置」限定（_WAIVER_CURRENT_
# MARKERS 限定词或本 spec 名同现）；否定清单补「不再放行」（非「不放行」的连续
# 子串，此前漏检）「暂不发放」等变体。
# code-review a2644017472b 补修：赋值型兜底（_family_waiver=true 与「放行」同句）
# 未同步收口——「另一族谱已放行（全库唯一的 _family_waiver=true）」这类他族谱
# 叙述 + 字段赋值同句、无任何否定短语的句子仍会绕过限定，给未放行的本次父
# SPEC 误写 _family_waiver=true（与上文两次实证误判同型）。现赋值型兜底复用与
# 动词型相同的「本次处置」同句限定（_WAIVER_CURRENT_MARKERS 或本 spec 名同现）。
_WAIVER_NEGATION_PHRASES = (
    "未放行",
    "不放行",
    "不再放行",
    "拒绝放行",
    "不予放行",
    "不发放",
    "未发放",
    "暂不发放",
    "不启用豁免",
    "未启用豁免",
    "不予豁免",
    "无须放行",
    "无需放行",
    "不必放行",
)
_WAIVER_GRANT_PATTERNS = (
    r"同意放行",
    r"放行一次",
    r"经评估放行",
    r"设置\s*_family_waiver\s*为?\s*true",  # 设置 _family_waiver 为 true
)
# 动词型放行模式命中句的「本次处置」限定词：命中句须含其一（或与本次父 SPEC 名
# 同现）才算本次放行——他族谱/历史放行的叙述提及不构成对本次对象的放行。
_WAIVER_CURRENT_MARKERS = ("本次", "该族", "本族")
# 赋值型 _family_waiver=true 必须与放行动词同句（。！？\n 分句）才算显式放行，
# 防止叙述中对字段名/其他族谱豁免状态的提及被误判为本次处置的放行动作。
_WAIVER_ASSIGN_RE = re.compile(r"_family_waiver['\"]?\s*[=:：]\s*['\"]?true")

# ── infra 回拨文本识别（evo-infra-failure-budget-exempt R3）──────────
# Administrator 处置文本显式声明「回拨 N 轮」（实为 infra 却计入 _verify_fail_rounds
# 的历史轮次减回 + 解冻）。与 _apply_family_waiver 同范式：结构字段
# disp.infra_reclassify_rounds 优先级最高，文本模式兜底。
# 匹配组 (?P<n>\d+) 给出减回轮次。
_RECLASSIFY_GRANT_PATTERNS = (
    r"回拨\s*(?P<n>\d+)\s*轮",
    r"reclassify\s*(?P<n>\d+)\s*(?:infra)?\s*rounds?",
    r"infra\s*回拨\s*(?P<n>\d+)\s*轮",
)
# 否定短语（保守方向：命中即不触发回拨，宁可漏回拨不可误扣 fail_rounds）。
# 「无需/无须/不必回拨」变体与 _WAIVER_NEGATION_PHRASES 的既有修正对称补齐
# （code-review ce4fad2d751e：处置文本「无需回拨 3 轮」曾因否定检查不命中、
# 反被 _RECLASSIFY_GRANT_PATTERNS 的「回拨 N 轮」当成放行，误减 fail_rounds）。
_RECLASSIFY_NEGATION_PHRASES = (
    "不回拨",
    "不应回拨",
    "不能回拨",
    "不予回拨",
    "无需回拨",
    "无须回拨",
    "不必回拨",
    "not reclassify",
    "不适用回拨",
)
# 「本次处置」同句限定词（infra 回拨版）：与 _WAIVER_CURRENT_MARKERS 单源同
# 口径（code-review 666155d105ae）——命中句须含其一（或与本次 spec 名同现）
# 才算本次回拨声明，历史/他 spec 的回拨叙述提及不构成对本次对象的回拨指令。
_RECLASSIFY_CURRENT_MARKERS = _WAIVER_CURRENT_MARKERS


def family_waiver_granted(text: str, spec: str) -> bool:
    """family_explosion 处置文本是否表达「显式放行」语义（纯判定，不落位）。

    判定（沿用既有实证修正，与 ``_apply_family_waiver`` 文本兜底一致）：
      - 命中否定短语即不放行（保守方向：宁可漏放行、不可给未放行的父 SPEC
        错开派生口子）；
      - 否则动词型/赋值型模式按句（。！？\\n）判定，命中句须为本次处置的
        显式放行表述：含「本次/该族」限定词或与本次父 SPEC 名同现——叙述
        提及其他族谱/历史放行（「另一族谱已同意放行」「父 SPEC 此前已放行过
        一次」）且不含否定短语不构成对本次对象的放行（code-review
        4dd652206902）；
      - 赋值型兜底：_family_waiver=true 须与「放行」动词同句，且命中句同样
        须含「本次处置」限定（a2644017472b，与动词型同款口径）才算显式放行。

    Args:
        text: 处置文本拼接（actions_taken/summary/recommended_action）；为
            None/非 str 时按空串处理（无否定短语、无模式命中，保守返回 False）。
        spec: 本次父 SPEC 名（同现限定用）；必须为非空 SPEC 名，为 None/空串/
            非 str 时同现限定不参与判定，仅依赖 _WAIVER_CURRENT_MARKERS 限定词。

    Returns:
        True 表示文本表达本次显式放行。
    """
    # text 防御（与下方 spec 防御 21a00a6ef714 同款口径）：None/非 str 会使
    # in 判定抛 TypeError——按空串处理，否定/放行判定自然落空（返回 False）。
    if not isinstance(text, str):
        text = ""
    negated = any(n in text for n in _WAIVER_NEGATION_PHRASES)
    if negated:
        return False
    # spec 防御（code-review 21a00a6ef714）：None/非 str 会使 in 判定抛
    # TypeError、空串使 `'' in sent` 恒真架空同现限定——非法时回退为仅靠
    # _WAIVER_CURRENT_MARKERS 限定词判定。
    waived = any(
        any(m in sent for m in _WAIVER_CURRENT_MARKERS)
        or (isinstance(spec, str) and spec and spec in sent)
        for sent in re.split(r"[。！？\n]", text)
        if any(re.search(p, sent) for p in _WAIVER_GRANT_PATTERNS)
    )
    if not waived:
        # 赋值型兜底：_family_waiver=true 须与「放行」动词同句才算
        # 显式放行——叙述中对他族谱豁免状态的提及不构成放行。
        # 「本次处置」同句限定（code-review a2644017472b，与动词型路径同款
        # 口径）：命中句须含 _WAIVER_CURRENT_MARKERS 限定词或与本次 spec 名
        # 同现——否则「另一族谱已放行（全库唯一的 _family_waiver=true）」
        # 这类他族谱叙述 + 字段赋值同句、无否定短语的句子会绕过限定，给未
        # 放行的本次父 SPEC 误写豁免位。
        waived = any(
            _WAIVER_ASSIGN_RE.search(sent)
            and "放行" in sent
            and (
                any(m in sent for m in _WAIVER_CURRENT_MARKERS)
                or (isinstance(spec, str) and spec and spec in sent)
            )
            for sent in re.split(r"[。！？\n]", text)
        )
    return waived


def is_reclassify_negated(text: str) -> bool:
    """infra 回拨文本是否命中否定短语（命中即保守不触发回拨）。

    text 为 None/非 str 时按空串处理（无否定短语命中，返回 False）。
    """
    # text 防御（与 family_waiver_granted 同款口径）：None/非 str 会使
    # in 判定抛 TypeError——按空串处理，否定短语判定自然落空（返回 False）。
    if not isinstance(text, str):
        text = ""
    return any(neg in text for neg in _RECLASSIFY_NEGATION_PHRASES)


def infra_reclassify_rounds(text: str, spec: str = "") -> int:
    """infra 回拨文本兜底判定：返回显式声明的减回轮次（0=不触发）。

    匹配「回拨 N 轮」/「reclassify N rounds」等模式，按 _RECLASSIFY_GRANT_
    PATTERNS 数组（模式优先级）顺序取首个 n>0 的命中——非文本出现顺序；
    否定短语命中时保守返回 0（宁可漏回拨不可误扣 fail_rounds）。

    与 family_waiver_granted 同范式（code-review 666155d105ae）：按
    。！？\\n 分句判定，命中句须含「本次」类限定词（_RECLASSIFY_CURRENT_
    MARKERS）或与本次 spec 名同现才算本次回拨声明——处置叙述对历史/其他
    spec 的回拨提及（「此前已回拨 2 轮」「另一族谱已回拨 3 轮」）且不含
    否定短语不构成对本次对象的回拨指令。spec 为 None/空串/非 str 时同现
    限定不参与判定，仅依赖限定词。

    Args:
        text: 处置文本拼接（actions_taken/summary/recommended_action/problem）；
            为 None/非 str 时按空串处理（无否定短语、无模式命中，返回 0）。
        spec: 本次 SPEC 名（同现限定用），防御口径同 family_waiver_granted。
    """
    # text 防御（与 family_waiver_granted 同款口径）：None/非 str 会使下方
    # re.split 抛 TypeError——按空串处理，否定/模式判定自然落空（返回 0）。
    if not isinstance(text, str):
        text = ""
    if is_reclassify_negated(text):
        return 0
    for pattern in _RECLASSIFY_GRANT_PATTERNS:
        for sent in re.split(r"[。！？\n]", text):
            m = re.search(pattern, sent)
            if not m:
                continue
            # 「本次处置」同句限定（与 family_waiver_granted 同款写法）。
            if not (
                any(mk in sent for mk in _RECLASSIFY_CURRENT_MARKERS)
                or (isinstance(spec, str) and spec and spec in sent)
            ):
                continue
            try:
                n = int(m.groupdict().get("n") or 0)
            except (TypeError, ValueError):
                n = 0
            if n > 0:
                return n
    return 0
