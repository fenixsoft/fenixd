"""add-verdict-contract-singularity 同源锚定测试（design D1-D3）。

覆盖任务 1.1 / 1.2 / 1.3 / 2.1 / 2.2：
  1.1 VERDICT_CLASSES / NON_PASS_STATUSES / FORCE_FAILED_CLASSES 取值逐字出现
  1.2 evidence 三维度键名 + assertion_triage 字段在 prompt 结构定义中出现
  1.3 分类定义段合法推荐值不超出 VERDICT_CLASSES（哨兵，防未注册分类值）
  2.1 无害措辞微调 tolerate（绿）+ 常量/文本漂移演练（红，双向覆盖）
  2.2 既有测试无回归（见 tests/test_verdict_evidence_taxonomy.py /
      tests/test_judge_efficiency.py，本套件不触碰它们）
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.verdict_check import (
    VERDICT_CLASSES,
    NON_PASS_STATUSES,
    FORCE_FAILED_CLASSES,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPT_PATH = PROJECT_ROOT / "agents" / "planner-judge.md"

# evidence 结构定义键名（prompt 中 "evidence": {...} 块）
EVIDENCE_KEYS = ("failed_assertions", "screenshots", "first_failed_step")
# assertion_triage 条目字段（prompt 中 "assertion_triage": [...] 块）
ASSERTION_TRIAGE_FIELDS = ("assertion", "classification", "evidence")

# prompt「分类定义」段的节标题（哨兵段边界）
_CLASS_DEF_HEADER = "分类定义（classification 取值限四选一）"


def _read_prompt():
    return PROMPT_PATH.read_text(encoding="utf-8")


def missing_anchored_values(text, values):
    """「取值逐字出现」检查：返回 values 中未在 text 里逐字出现的取值。

    锚定策略（design D1）：只断言取值集合在文本中逐字出现，不做全文/段落
    比对——prompt 是无害可变化的叙述文档，取值不丢即可。
    """
    return [v for v in values if v not in text]


def _assert_anchored(test_case, constant_name, values, text, msg_prefix=""):
    """断言 values 全部逐字出现在 text 中；失败消息携带常量名与缺失取值。"""
    missing = missing_anchored_values(text, values)
    test_case.assertFalse(
        missing,
        f"{msg_prefix}常量 {constant_name}={values} 中取值 {missing} "
        f"未在 agents/planner-judge.md 中逐字出现（文本与校验器常量双源漂移）",
    )


def _extract_classification_definitions(text):
    """提取「分类定义（classification 取值限四选一）」节的合法分类推荐取值。

    从节标题行起逐行扫描：只收集比标题缩进更深的反引号列表项（形如
    "- `值`"），遇到空行跳过，遇到新的同层/更浅层标题行即段界停止——只取
    分类定义段，不把 evidence 字段名等其它 segment 的 bullet 当分类值
    （否则 `failed_assertions` / `screenshots` 等会被误判为未注册分类）。
    """
    header = text.find(_CLASS_DEF_HEADER)
    if header == -1:
        return set()
    line_start = text.rfind("\n", 0, header) + 1
    header_indent = len(text[line_start:header]) - len(text[line_start:header].lstrip())
    values = set()
    for line in text[header:].split("\n")[1:]:
        if not line.strip():
            continue
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if indent <= header_indent:
            break  # 新的同层/更浅层 bullet → 分类定义段结束
        m = re.match(r"-\s*`([a-z0-9][a-z0-9-]*)`", stripped)
        if m:
            values.add(m.group(1))
    return values


class TestVerdictContractSingularity(unittest.TestCase):
    """同源锚定：planner-judge 契约文本与 verdict_check 常量一致。"""

    def setUp(self):
        self.text = _read_prompt()
        self.assertTrue(self.text.strip(), "agents/planner-judge.md 为空或缺失")

    # ── 1.1 常量取值锚定 ────────────────────────────────────────────

    def test_verdict_classes_anchored(self):
        _assert_anchored(self, "VERDICT_CLASSES", VERDICT_CLASSES, self.text)

    def test_non_pass_statuses_anchored(self):
        _assert_anchored(self, "NON_PASS_STATUSES", NON_PASS_STATUSES, self.text)

    def test_force_failed_classes_anchored(self):
        _assert_anchored(self, "FORCE_FAILED_CLASSES", FORCE_FAILED_CLASSES, self.text)

    # ── 1.2 证据结构锚定 ────────────────────────────────────────────

    def test_evidence_keys_in_prompt(self):
        missing = missing_anchored_values(self.text, EVIDENCE_KEYS)
        self.assertFalse(
            missing,
            f"prompt 结构定义缺失 evidence 键名: {missing}（EVIDENCE_KEYS）",
        )

    def test_assertion_triage_fields_in_prompt(self):
        missing = missing_anchored_values(self.text, ASSERTION_TRIAGE_FIELDS)
        self.assertFalse(
            missing,
            f"prompt 结构定义缺失 assertion_triage 字段: {missing}（ASSERTION_TRIAGE_FIELDS）",
        )

    # ── 1.3 哨兵：分类定义段不超出 VERDICT_CLASSES ──────────────────

    def test_classification_definitions_confined(self):
        """分类定义段推荐值不超出 VERDICT_CLASSES（防未注册分类值）。"""
        recommended = _extract_classification_definitions(self.text)
        self.assertTrue(
            recommended,
            "未从「分类定义」段提取到分类推荐值（段结构异常？）",
        )
        illegal = sorted(recommended - set(VERDICT_CLASSES))
        self.assertFalse(
            illegal,
            f"prompt 分类定义段推荐了未注册分类值: {illegal}（VERDICT_CLASSES）",
        )

    # ── 2.1 回归演练：无害措辞 tolerate（绿） ───────────────────────

    def test_harmless_wording_tweak_stays_green(self):
        """无害措辞微调（不动锚定取值）→ 锚定断言仍全绿（tolerate D1）。"""
        tweaked = self.text.replace(
            "分析验证引擎的测试报告", "分析测试引擎的验证报告")
        # 换行/标点等格式变化也不应误伤（取值逐字出现，与格式无关）
        tweaked = tweaked.replace("\n\n", "\n")
        for name, values in (
            ("VERDICT_CLASSES", VERDICT_CLASSES),
            ("NON_PASS_STATUSES", NON_PASS_STATUSES),
            ("FORCE_FAILED_CLASSES", FORCE_FAILED_CLASSES),
        ):
            self.assertEqual(
                missing_anchored_values(tweaked, values), [],
                f"无害措辞被误判漂移: 常量 {name}")
        # 哨兵同样 tolerate 无害变化
        self.assertEqual(
            sorted(_extract_classification_definitions(tweaked) - set(VERDICT_CLASSES)),
            [])

    # ── 2.1 回归演练：漂移报红（双向覆盖） ──────────────────────────

    def test_constant_drift_turns_red(self):
        """verdict_check 常量改动演练：新增取值但 prompt 没跟 → 锚定红。"""
        drifted = VERDICT_CLASSES + ("phantom-bug",)
        self.assertIn(
            "phantom-bug",
            missing_anchored_values(self.text, drifted),
            "常量新增取值未被文本缺位检出（应报红）",
        )

    def test_prompt_text_drift_turns_red(self):
        """prompt 文本改动演练：分类定义段新增未注册分类 → 哨兵红。"""
        after_header = self.text.find("\n", self.text.find(_CLASS_DEF_HEADER))
        injected = (
            self.text[:after_header]
            + "\n  - `phantom-class`：幻觉分类（未注册）\n"
            + self.text[after_header + 1:]
        )
        recommended = _extract_classification_definitions(injected)
        illegal = sorted(recommended - set(VERDICT_CLASSES))
        self.assertIn("phantom-class", illegal, "未注册分类值未被哨兵检出（应报红）")


if __name__ == "__main__":
    unittest.main()