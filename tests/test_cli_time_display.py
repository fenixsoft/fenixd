"""CLI 展示层时间戳本地化测试。

覆盖:
- bin/fenix_process.py 与 bin/fenix_dashboard.py 的 _local_ts 助手(UTC ISO 串 → 本地时区显示)
- core/logger.py 时间戳格式保持 Z 后缀不变(仅替换弃用的 utcnow,展示层与既有 grep 依赖该格式)
"""

import importlib.util
import json
import logging
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BIN = PROJECT_ROOT / "bin"


def _load_module(name):
    path = BIN / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TZAsiaShanghai:
    """进程级临时切到 Asia/Shanghai,结束后恢复原 TZ。"""

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


class TestLocalTsHelper(unittest.TestCase):
    """_local_ts:UTC ISO 串 → 本地时区格式化。"""

    def setUp(self):
        self.process = _load_module("fenix_process")
        self.dashboard = _load_module("fenix_dashboard")

    def test_utc_z_suffix_converted_to_local(self):
        with TZAsiaShanghai():
            # 10:23:50Z → 本地 +8 → 18:23:50
            self.assertEqual(self.process._local_ts("2026-09-03T10:23:50Z"), "18:23:50")
            self.assertEqual(self.dashboard._local_ts("2026-09-03T10:23:50Z"), "18:23:50")

    def test_utc_offset_format_converted(self):
        """admin_store 风格的 +00:00 后缀同样处理。"""
        with TZAsiaShanghai():
            self.assertEqual(
                self.process._local_ts("2026-09-03T10:23:50+00:00"), "18:23:50")

    def test_dashboard_full_format(self):
        with TZAsiaShanghai():
            out = self.dashboard._local_ts(
                "2026-09-03T10:23:50Z", fmt="%Y-%m-%d %H:%M:%S")
            self.assertEqual(out, "2026-09-03 18:23:50")

    def test_non_utc_offset_input(self):
        """+08:00 输入按其自身时区换算,结果不变。"""
        with TZAsiaShanghai():
            self.assertEqual(
                self.process._local_ts("2026-09-03T18:23:50+08:00"), "18:23:50")

    def test_unparseable_falls_back_to_slice(self):
        # 20 字符不可解析串 → 回退裸切片 [:19]
        self.assertEqual(self.process._local_ts("0123456789abcdefghij"), "0123456789abcdefghi")
        self.assertEqual(self.process._local_ts(""), "")
        self.assertEqual(self.dashboard._local_ts(""), "")


class TestLoggerTimestampFormat(unittest.TestCase):
    """logger 时间戳保持 Z 后缀格式(格式不变,仅换非弃用 API)。"""

    def test_format_preserved_with_z_suffix(self):
        from core.logger import JsonFormatter

        with tempfile.TemporaryDirectory() as tmp:
            # JsonFormatter 不落盘,LogRecord 直接构造即可
            rec = logging.LogRecord("fenixd", logging.INFO, "", 0, "msg", (), None)
            rec.component = "test"
            rec.context = None
            entry = json.loads(JsonFormatter().format(rec))

        ts = entry["timestamp"]
        self.assertTrue(ts.endswith("Z"), f"时间戳应保持 Z 后缀: {ts}")
        # 必须可被展示层解析且为 UTC 零偏移
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        self.assertEqual(dt.utcoffset(), timedelta(0))


if __name__ == "__main__":
    unittest.main()
