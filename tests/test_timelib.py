"""timelib 单元测试（add-timelib-consolidation-layer 1.2）。

覆盖 spec/timelib-consolidation 全部 Scenario：
- now_utc 返回 aware UTC（tzinfo/utcoffset 断言）
- to_storage 输出 Z 后缀，本地输入折算同一 UTC 时刻
- fmt_display 按本地时区输出（UTC 02:33 → 本地 10:33，Asia/Shanghai）
- parse_ts：naive→本地（唯一策略）、Z 与 +00:00 等价、纯日期串、
  非法串/None/空串/非字符串返回 None 不抛异常

时区敏感断言用 TZAsiaShanghai 固定进程时区（同 test_cli_time_display
先例），机器真实时区不影响结果。
"""

import os
import time
import unittest
from datetime import datetime, timedelta, timezone

from core import timelib


class TZAsiaShanghai:
    """进程级临时切到 Asia/Shanghai，结束后恢复原 TZ（test_cli_time_display 先例）。"""

    def __enter__(self):
        self._old = os.environ.get("TZ")
        os.environ["TZ"] = "Asia/Shanghai"
        time.tzset()

    def __exit__(self, *exc):
        if self._old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self._old
        time.tzset()


class TestNowUtc(unittest.TestCase):
    """Scenario: now_utc 返回 aware UTC。"""

    def test_tzinfo_is_utc_and_offset_zero(self):
        dt = timelib.now_utc()
        self.assertEqual(dt.tzinfo, timezone.utc)
        self.assertEqual(dt.utcoffset().total_seconds(), 0)

    def test_close_to_datetime_now_utc(self):
        delta = abs(
            (timelib.now_utc() - datetime.now(timezone.utc)).total_seconds()
        )
        self.assertLess(delta, 5)


class TestNowLocal(unittest.TestCase):
    def test_returns_aware_local(self):
        with TZAsiaShanghai():
            dt = timelib.now_local()
            self.assertIsNotNone(dt.tzinfo)
            self.assertEqual(dt.utcoffset().total_seconds(), 8 * 3600)


class TestToStorage(unittest.TestCase):
    """Scenario: to_storage 输出 Z 后缀（本地输入折算同一 UTC 时刻）。"""

    def test_aware_utc_gets_z_suffix(self):
        dt = datetime(2026, 9, 30, 2, 33, 0, tzinfo=timezone.utc)
        self.assertEqual(timelib.to_storage(dt), "2026-09-30T02:33:00Z")

    def test_aware_local_converted_to_utc_z(self):
        # 本地 2026-09-30 10:33 +08:00 → UTC 02:33
        plus8 = timezone(timedelta(hours=8))
        dt = datetime(2026, 9, 30, 10, 33, 0, tzinfo=plus8)
        self.assertEqual(timelib.to_storage(dt), "2026-09-30T02:33:00Z")

    def test_naive_interpreted_as_local(self):
        with TZAsiaShanghai():
            self.assertEqual(
                timelib.to_storage(datetime(2026, 9, 30, 10, 33, 0)),
                "2026-09-30T02:33:00Z",
            )

    def test_microseconds_preserved(self):
        dt = datetime(2026, 9, 30, 2, 33, 0, 123456, tzinfo=timezone.utc)
        self.assertEqual(timelib.to_storage(dt), "2026-09-30T02:33:00.123456Z")

    def test_roundtrip_with_parse_ts(self):
        dt = timelib.now_utc()
        self.assertEqual(timelib.parse_ts(timelib.to_storage(dt)), dt)


class TestFmtDisplay(unittest.TestCase):
    """Scenario: fmt_display 按本地时区输出（机器时区 Asia/Shanghai）。"""

    def test_utc_z_string_to_local(self):
        with TZAsiaShanghai():
            self.assertEqual(
                timelib.fmt_display("2026-09-30T02:33:00Z"),
                "2026-09-30 10:33:00",
            )

    def test_datetime_input(self):
        with TZAsiaShanghai():
            dt = datetime(2026, 9, 30, 2, 33, 0, tzinfo=timezone.utc)
            self.assertEqual(timelib.fmt_display(dt), "2026-09-30 10:33:00")

    def test_custom_format(self):
        with TZAsiaShanghai():
            self.assertEqual(
                timelib.fmt_display("2026-09-30T02:33:00Z", "%H:%M"),
                "10:33",
            )

    def test_naive_datetime_treated_as_local_wall_clock(self):
        with TZAsiaShanghai():
            self.assertEqual(
                timelib.fmt_display(datetime(2026, 9, 30, 10, 33, 0)),
                "2026-09-30 10:33:00",
            )

    def test_invalid_returns_empty(self):
        self.assertEqual(timelib.fmt_display("not-a-time"), "")
        self.assertEqual(timelib.fmt_display(None), "")
        self.assertEqual(timelib.fmt_display(12345), "")


class TestParseTs(unittest.TestCase):
    """Scenario 组：naive→本地 / Z 与 +00:00 等价 / 纯日期 / 非法返回 None。"""

    def test_naive_interpreted_as_local(self):
        """Scenario: naive 输入按本地解读（Asia/Shanghai → UTC 02:33Z）。"""
        with TZAsiaShanghai():
            dt = timelib.parse_ts("2026-09-30T10:33:00")
            self.assertEqual(dt.utcoffset().total_seconds(), 8 * 3600)
            self.assertEqual(
                timelib.to_storage(dt), "2026-09-30T02:33:00Z"
            )

    def test_z_and_plus0000_equivalent(self):
        """Scenario: Z 后缀与 +00:00 等价（不叠加时区偏移）。"""
        a = timelib.parse_ts("2026-09-30T02:33:00Z")
        b = timelib.parse_ts("2026-09-30T02:33:00+00:00")
        self.assertEqual(a, b)
        self.assertEqual(a.tzinfo, timezone.utc)

    def test_lowercase_z_suffix(self):
        self.assertEqual(
            timelib.parse_ts("2026-09-30T02:33:00z"),
            timelib.parse_ts("2026-09-30T02:33:00+00:00"),
        )

    def test_non_utc_offset_preserved(self):
        dt = timelib.parse_ts("2026-09-30T10:33:00+08:00")
        self.assertEqual(
            timelib.to_storage(dt), "2026-09-30T02:33:00Z"
        )

    def test_pure_date_string_local_midnight(self):
        with TZAsiaShanghai():
            dt = timelib.parse_ts("2026-09-30")
            self.assertEqual(dt.hour, 0)
            self.assertEqual(dt.utcoffset().total_seconds(), 8 * 3600)

    def test_invalid_inputs_return_none(self):
        """Scenario: 非法输入返回 None 不抛异常。"""
        self.assertIsNone(timelib.parse_ts("not-a-time"))
        self.assertIsNone(timelib.parse_ts(None))
        self.assertIsNone(timelib.parse_ts(""))
        self.assertIsNone(timelib.parse_ts("   "))
        self.assertIsNone(timelib.parse_ts(12345))
        self.assertIsNone(timelib.parse_ts(datetime(2026, 9, 30)))

    def test_whitespace_tolerated(self):
        self.assertEqual(
            timelib.parse_ts("  2026-09-30T02:33:00Z  "),
            timelib.parse_ts("2026-09-30T02:33:00Z"),
        )


class TestFromEpoch(unittest.TestCase):
    def test_returns_aware_utc(self):
        dt = timelib.from_epoch(0.0)
        self.assertEqual(dt.tzinfo, timezone.utc)
        self.assertEqual(dt.year, 1970)

    def test_matches_datetime_utc_construct(self):
        ts = datetime(2026, 9, 30, 2, 33, 0, tzinfo=timezone.utc).timestamp()
        self.assertEqual(timelib.from_epoch(ts), datetime(2026, 9, 30, 2, 33, 0, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
