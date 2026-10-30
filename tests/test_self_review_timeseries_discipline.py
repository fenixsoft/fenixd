"""自省时序聚合断言回源纪律契约测试（evo-self-review-timeseries-assertion-backsource）。

守护 agents/self-review.md「含调查评估」清单中两类纪律条款同时在场：
- 「归因证据边界」（既有条款，evo-self-review-evidence-bound-attribution 落地）；
- 「时序聚合断言回源」（本 spec 新增条款）。

模板是纯文本、无类型保护：后续模板改写静默删除任一条款时，本测试失败
阻止回退。关键词 MUST 按模板原文逐字取自条款标题（MUST NOT 用「证据边界
归因」等语序变体或缩略「时序聚合回源」，防关键词与模板不一致造成误报/漏报）。

对应 spec specs/self-review-timeseries-discipline/spec.md：
- Requirement「条款落位与契约守护」/ Scenario「模板含两类纪律条款」：
  两类条款同时存在、同区并列；
- Scenario「契约测试拦截静默丢失」：删除任一条款 → 本文件用例失败。
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "agents" / "self-review.md"

# 逐字标题关键词（逐字取自 agents/self-review.md「含调查评估」清单条款标题）。
TITLE_ATTRIBUTION = "归因证据边界"      # 既有第 3 项（粗体标题）
TITLE_TIMESERIES = "时序聚合断言回源"   # 新增第 4 项（粗体标题）
TITLE_ORGANIZE = "组织顺序"            # 顺延后的第 5 项


def _template_text() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def _investigation_segment(text: str) -> str:
    """提取「含调查评估」清单段（该 bullet 起至下一个顶层 bullet/标题行止）。

    「含调查评估」是条目质量标准下的一个顶层 bullet，其编号子项
    （1. 核实 / 2. 评估 / 3. 归因证据边界 / 4. 时序聚合断言回源 / 5. 组织顺序）
    为缩进续行；两类纪律条款 MUST 同区并列于此段内。
    """
    lines = text.splitlines()
    start = next(
        (i for i, ln in enumerate(lines) if "含调查评估" in ln), None)
    assert start is not None, "模板缺「含调查评估」清单段"
    end = start + 1
    while end < len(lines):
        ln = lines[end]
        if (ln.startswith("- **") or ln.startswith("### ")
                or ln.startswith("## ")):
            break
        end += 1
    return "\n".join(lines[start:end])


class TestBothDisciplineTitlesPresent:
    """Scenario: 模板含两类纪律条款——逐字标题子串同时存在。"""

    def test_attribution_title_present(self):
        """既有「归因证据边界」条款在场（防本 spec 改写静默挤掉）。"""
        text = _template_text()
        assert TITLE_ATTRIBUTION in text, (
            "agents/self-review.md 丢失既有「归因证据边界」条款标题")

    def test_timeseries_title_present(self):
        """新增「时序聚合断言回源」条款在场（本 spec 核心交付）。"""
        text = _template_text()
        assert TITLE_TIMESERIES in text, (
            "agents/self-review.md 缺「时序聚合断言回源」条款标题")

    def test_titles_are_bold_clause_heads(self):
        """两标题均以粗体条款头形态在场（**标题**：），非顺带提及。"""
        text = _template_text()
        assert f"**{TITLE_ATTRIBUTION}**" in text
        assert f"**{TITLE_TIMESERIES}**" in text


class TestSameRegionPlacement:
    """Scenario: 模板含两类纪律条款——两类条款同区并列于「含调查评估」清单。"""

    def test_both_in_investigation_segment(self):
        segment = _investigation_segment(_template_text())
        assert TITLE_ATTRIBUTION in segment
        assert TITLE_TIMESERIES in segment

    def test_timeseries_after_attribution_then_organize_last(self):
        """新条款插在归因条款之后、组织顺序之前（编号顺延不换位）。"""
        segment = _investigation_segment(_template_text())
        pos_attr = segment.index(f"**{TITLE_ATTRIBUTION}**")
        pos_time = segment.index(f"**{TITLE_TIMESERIES}**")
        pos_org = segment.index(TITLE_ORGANIZE)
        assert pos_attr < pos_time < pos_org, (
            "「含调查评估」清单顺序应为 归因证据边界 → 时序聚合断言回源 → 组织顺序")

    def test_checklist_numbering_contiguous(self):
        """编号子项 1..N 连续无跳号/重号（防插入后编号冲突静默腐烂）。"""
        segment = _investigation_segment(_template_text())
        numbers = [
            int(m.group(1))
            for m in re.finditer(r"(?m)^\s+(\d+)\. ", segment)
        ]
        assert numbers, "「含调查评估」清单段无编号子项"
        assert numbers == list(range(1, len(numbers) + 1)), (
            f"编号子项应自 1 起连续，实际 {numbers}")


class TestTimeseriesClauseSemantics:
    """新增条款覆盖 spec 三个行为 requirement 的关键语义串（同句在场）。"""

    def test_clause_covers_backsource_scope_and_fallback(self):
        text = _template_text()
        pos = text.index(f"**{TITLE_TIMESERIES}**")
        clause = text[pos:text.find("\n  5.", pos)]
        # 回源触发面：连续/上行/回落/钉值/下界/合计类断言逐项回源。
        for kw in ("连续", "上行", "回落", "钉值", "下界", "合计", "回源"):
            assert kw in clause, f"时序条款缺回源触发面关键词: {kw}"
        # 回源对象：当晚原始汇总行（run_metrics/延迟汇总行）或档案重算。
        assert "原始汇总行" in clause and "run_metrics" in clause
        assert "档案重算" in clause
        # 断言句同附每晚原始数字与口径（整晚总量 vs 单车道分量）。
        assert "每晚原始数字与口径" in clause and "单车道分量" in clause
        # 转引前轮条目数字必须重新回源。
        assert "转引" in clause and "重新回源" in clause
        # 无法回源时降级定性或标注未核实。
        assert "未核实" in clause
