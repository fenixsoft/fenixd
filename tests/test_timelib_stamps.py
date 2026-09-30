"""knowledge 盖戳时间源收拢 characterization（add-timelib-consolidation-layer 4.3）。

4.3：knowledge 真相源盖戳的两个同逻辑时间源副本统一改走
``timelib.now_utc()``，输出格式与取值口径**逐字不变**。

_声明对账留痕（deliverable-dispute）_：SPEC 任务 4.3 与 spec Scenario 写的
``knowledge.local_now_stamp`` / ``knowledge_backfill._now_local_parts`` 与
``("2026-09-30 10:33", "UTC+8")`` / ``> 最后更新：… UTC+8`` 在仓库（含全部
git 历史）中从未存在；实际是 UTC 盖戳（``_STAMP_LINE_RE`` 锁
``UTC`` 后缀，蒸馏提示词动态段亦自称「当前 UTC 时间」）。「输出格式逐字
不变」约束优先于任务文本的 ``now_local()`` 字面——用 ``now_local()`` 会把
本地墙钟盖进「UTC」标签（值平移 8h 且语义错误）。本地化盖戳若需推进应另
行走 SPEC（改 ``_STAMP_LINE_RE``/表格单元格/提示词模板三处联动）。

盖戳行格式（既有 ``_STAMP_LINE_RE``）：
``> 最后更新：YYYY-MM-DD HH:MM UTC``（index 与 _domain 通用，表格单元格为
同格式去 UTC 后缀）。
"""

import re
import unittest
from datetime import datetime, timezone
from pathlib import Path

from core import knowledge, knowledge_backfill, timelib

_STAMP_LINE_RE = knowledge._STAMP_LINE_RE


class TestKnowledgeStampTimeSource(unittest.TestCase):
    """两个同逻辑盖戳时间源：格式逐字不变、取值=timelib.now_utc()。"""

    def test_backfill_now_utc_format_and_value(self):
        got = knowledge_backfill._now_utc()
        self.assertRegex(got, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
        # 与 timelib.now_utc() 同源（分钟粒度，跨分钟边界容差 ±2）
        delta = (
            datetime.strptime(got, "%Y-%m-%d %H:%M")
            - timelib.now_utc().replace(tzinfo=None, second=0, microsecond=0)
        )
        self.assertLessEqual(abs(delta.total_seconds()), 120)
        # 取值是 UTC 墙钟：与 aware UTC 的本地差零（本地 +8 时差不出现在值里）
        with self.subTest("utc-not-local"):
            now_aware = timelib.now_utc()
            self.assertEqual(
                knowledge_backfill._now_utc(),
                now_aware.strftime("%Y-%m-%d %H:%M"),
            )

    def test_distill_prompt_dynamic_segment_stamp(self):
        """蒸馏提示词动态段「当前 UTC 时间」走同一时间源、格式不变。"""
        text = knowledge.build_distill_prompt(Path(".").resolve(), ["demo-archive"])
        m = re.search(r"当前 UTC 时间：(\d{4}-\d{2}-\d{2} \d{2}:\d{2})", text)
        self.assertIsNotNone(m, "动态段时间戳缺失或格式漂移")
        self.assertEqual(
            m.group(1), knowledge_backfill._now_utc(),
            "蒸馏动态段与回填盖戳应为同一分钟级时间源")

    def test_stamp_line_regex_still_validates_output(self):
        """时间源产出能通过盖戳行校验（格式逐字不变的端到端证据）。"""
        stamp = knowledge_backfill._now_utc()
        line = f"> 最后更新：{stamp} UTC"
        m = _STAMP_LINE_RE.match(line)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), stamp)

    def test_table_cell_format_unchanged(self):
        """表格单元格为同格式去 UTC 后缀（knowledge.py 模块注释约定）。"""
        stamp = knowledge_backfill._now_utc()
        self.assertIsNotNone(knowledge._STAMP_CELL_RE.match(stamp))


if __name__ == "__main__":
    unittest.main()
