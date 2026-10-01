"""knowledge 盖戳时间源 characterization（本地时区盖戳迁移后口径）。

历史演进：add-timelib-consolidation-layer 4.3 曾把两个同逻辑盖戳时间源收拢
到 ``timelib.now_utc()``（UTC 盖戳）；其后「知识真相源盖戳迁移本地时区」
（用户定调 2026-09-30：真相源面向人类读者，用本地时区展示）把盖戳值迁为
本地墙钟（timelib 原语 ``now_local()``），盖戳行尾追加时区后缀，蒸馏动态段
自称「当前本地时间」。4.3 的旧 UTC 口径断言随迁移一并改写为本文件。

盖戳行格式（既有 ``_STAMP_LINE_RE``）：
``> 最后更新：YYYY-MM-DD HH:MM UTC+8``（index 与 _domain 通用，时区后缀兼容
任意时区机器；表格单元格为同格式去时区后缀）。
"""

import re
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from core import knowledge, knowledge_backfill, timelib

_STAMP_LINE_RE = knowledge._STAMP_LINE_RE


def _expect_tz_suffix() -> str:
    """当前本地时区的展示后缀（``UTC+8`` / ``UTC-5`` / ``UTC+5:30``）。"""
    off = timelib.now_local().utcoffset() or timedelta(0)
    total_min = round(off.total_seconds() / 60)
    sign = "+" if total_min >= 0 else "-"
    hours, minutes = divmod(abs(total_min), 60)
    return f"UTC{sign}{hours}" + (f":{minutes:02d}" if minutes else "")


class TestKnowledgeStampTimeSource(unittest.TestCase):
    """两个同逻辑盖戳时间源：格式一致、取值=timelib.now_local()（本地墙钟）。"""

    # [fenix-ignore:e998d2c91a61] 回归失败不复现：旧 UTC 用例 test_backfill_now_utc_format_and_value 已随基线提交 bfb98d61（盖戳迁移本地时区）改写为本用例（_now_utc→_now_local_parts），当前实测通过
    def test_backfill_now_local_parts_format_and_value(self):
        stamp, tz = knowledge_backfill._now_local_parts()
        self.assertRegex(stamp, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
        # 与 timelib.now_local() 同源（分钟粒度，跨分钟边界容差 ±2）
        delta = (
            datetime.strptime(stamp, "%Y-%m-%d %H:%M")
            - timelib.now_local().replace(tzinfo=None, second=0, microsecond=0)
        )
        self.assertLessEqual(abs(delta.total_seconds()), 120)
        # 时区后缀=真实本地偏移（非 UTC 裸后缀；本地墙钟 + 本地偏移）
        self.assertEqual(tz, _expect_tz_suffix())

    def test_local_now_stamp_same_contract(self):
        """knowledge.local_now_stamp 与回填侧同契约（格式与后缀口径一致）。"""
        stamp, tz = knowledge.local_now_stamp()
        self.assertRegex(stamp, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
        self.assertEqual(tz, _expect_tz_suffix())

    # [fenix-ignore:5accb32b8071] 回归失败不复现：动态段时间源已随 bfb98d61 迁移为本地时区并实际注入（「当前本地时间：…（时区 …）」），断言同步改写，当前实测通过
    def test_distill_prompt_dynamic_segment_stamp(self):
        """蒸馏提示词动态段「当前本地时间」走同一时间源、格式不变。"""
        text = knowledge.build_distill_prompt(Path(".").resolve(), ["demo-archive"])
        m = re.search(
            r"当前本地时间：(\d{4}-\d{2}-\d{2} \d{2}:\d{2})"
            r"（时区 (UTC[+-]\d{1,2}(?::\d{2})?)）",
            text,
        )
        self.assertIsNotNone(m, "动态段时间戳缺失或格式漂移")
        stamp, tz = m.group(1), m.group(2)
        self.assertEqual(tz, _expect_tz_suffix())
        # 动态段给出的盖戳行写法能通过盖戳行校验（三处联动的端到端证据）
        self.assertIsNotNone(_STAMP_LINE_RE.match(f"> 最后更新：{stamp} {tz}"))
        # 与回填盖戳同一分钟级时间源（跨分钟边界容差 ±2）
        backfill_stamp = knowledge_backfill._now_local_parts()[0]
        delta = (
            datetime.strptime(stamp, "%Y-%m-%d %H:%M")
            - datetime.strptime(backfill_stamp, "%Y-%m-%d %H:%M")
        )
        self.assertLessEqual(
            abs(delta.total_seconds()), 120,
            "蒸馏动态段与回填盖戳应为同一分钟级时间源")

    # [fenix-ignore:02a719b85876] 回归失败不复现：时间源已随 bfb98d61 迁移为 local_now_stamp（knowledge_backfill._now_utc 不复存在），盖戳行校验链不变，当前实测通过
    def test_stamp_line_regex_still_validates_output(self):
        """时间源产出能通过盖戳行校验（格式不变的端到端证据）。"""
        stamp, tz = knowledge.local_now_stamp()
        line = f"> 最后更新：{stamp} {tz}"
        self.assertIsNotNone(_STAMP_LINE_RE.match(line))

    # [fenix-ignore:138e43f830cc] 回归失败不复现：同 02a719b85876 根因，bfb98d61 盖戳迁移已在基线完成，表格单元格断言不变式保留，当前实测通过
    def test_table_cell_format_unchanged(self):
        """表格单元格为同格式去时区后缀（knowledge.py 模块注释约定）。"""
        stamp, _tz = knowledge.local_now_stamp()
        self.assertIsNotNone(knowledge._STAMP_CELL_RE.match(stamp))


if __name__ == "__main__":
    unittest.main()
