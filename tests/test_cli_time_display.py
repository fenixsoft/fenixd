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


class TestManualSentinelDisplay(unittest.TestCase):
    """add-spec-manual-activation 10.6：哨兵 manual 在 CLI 展示层不产生伪时间戳。

    - get_spec_start_after 对 manual 原样返回（MUST，specs/scheduled-spec-pickup）
    - fenix_status：已知等待文案为「待激活，需人工激活」（非 start_after 伪时间戳）；
      状态行备注为「⏸ 待激活」（非「⏰ 定时」——哨兵无目标时间）
    - fenix_process：详情行印「⏸ 待激活（start_after: manual）」，不走 _local_ts
    """

    def _make_min_project(self, tmp_path) -> Path:
        """最小 Fenix 项目：仅 STATE.md + logs（status 报告所需）。"""
        proot = tmp_path / "proj-cli"
        (proot / ".fenix" / "logs").mkdir(parents=True, exist_ok=True)
        (proot / ".fenix" / "STATE.md").write_text(
            "# Fenix Project State\n\n## Specs\n\n"
            "### manualspec\n- status: ready\n- priority: 2\n"
            "- created: 2026-01-01T00:00:00+00:00\n- updated: 2026-01-02T00:00:00+00:00\n"
            "- error: null\n- depends_on: null\n- start_after: manual\n- frozen_until: null\n- frozen: null\n"
            "\n### timedspec\n- status: ready\n- priority: 3\n"
            "- created: 2026-01-01T00:00:00+00:00\n- updated: 2026-01-02T00:00:00+00:00\n"
            "- error: null\n- depends_on: null\n"
            "- start_after: 2026-09-30T01:00:00+00:00\n- frozen_until: null\n- frozen: null\n",
            encoding="utf-8",
        )
        return proot

    def test_get_spec_start_after_returns_manual_sentinel(self):
        from core.dashboard.data import get_spec_start_after
        self.assertEqual(get_spec_start_after({"start_after": "manual"}), "manual")
        self.assertEqual(get_spec_start_after({"start_after": "MANUAL"}), "manual")
        self.assertEqual(get_spec_start_after({}), None)
        # 定时值解析后返回规范化 ISO（原语义不受哨兵分支影响）
        self.assertEqual(
            get_spec_start_after({"start_after": "2026-09-30T01:00:00+00:00"}),
            "2026-09-30T01:00:00+00:00",
        )

    def test_fenix_status_collect_signals_manual_wait_text(self):
        status = _load_module("fenix_status")
        proot = self._make_min_project(
            Path(tempfile.mkdtemp()))
        entries = status.data.parse_state(proot)
        active = {n: e for n, e in entries.items()
                  if e.get("status") not in status.TERMINAL}
        signals = status._collect_signals(
            proot, entries, active=active, daemon="running",
            approve_mode="auto", promote_mode="auto")
        waits = [text for level, text in signals if level == "info" and "已知等待" in text]
        self.assertTrue(waits, "信号汇总应含已知等待行")
        joined = "；".join(waits)
        self.assertIn("manualspec（待激活，需人工激活）", joined, "manual 已知等待文案")
        self.assertNotIn("start_after 手动", joined)
        self.assertNotIn("已知等待：manualspec（start_after", joined)
        # 定时 spec 保持既有形态（不受哨兵分支影响）
        self.assertIn("timedspec（start_after", joined)

    def test_fenix_status_render_report_manual_note(self):
        status = _load_module("fenix_status")
        proot = self._make_min_project(Path(tempfile.mkdtemp()))
        out = status.render_report(proot)
        self.assertIn("⏸ 待激活", out, "状态行备注 MUST 为待激活")
        self.assertIn("manualspec", out)
        # 定时 spec 仍为「⏰ 定时」
        self.assertIn("⏰ 定时", out)

    def test_fenix_process_render_report_manual_no_fake_ts(self):
        process = _load_module("fenix_process")
        proot = self._make_min_project(Path(tempfile.mkdtemp()))
        out = process.render_report(proot, "manualspec")
        self.assertIn("待激活（start_after: manual）", out, "详情行语义待激活")
        self.assertNotIn("⏰ start_after: manual", out, "MUST NOT 走 _local_ts 伪时间戳")
        # 对照：定时 spec 仍走时间戳
        out2 = process.render_report(proot, "timedspec")
        self.assertIn("⏰ start_after:", out2)


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
