"""escalation/recovery/runner ISO 解析内核收拢 characterization（4.2）。

add-timelib-consolidation-layer 4.2：三处同口径事件时间戳解析器的 ISO 内核
统一收拢至 ``timelib.parse_ts``。**有意行为变化**：naive（无时区）输入由
旧实现的显式 naive→UTC 翻转为 naive→本地（timelib 唯一 naive 策略，定调
2026-09-30，design D1）——推翻 escalation「朴素→UTC 与 AdminStore 一致」
与 recovery/runner 的 fc528d7216ed 注释。

4.2 核查留痕（实际数据不含 naive 的证据，按写手代码核验）：

- admin_store 信号/处置记录：``created``/``last_seen``/``handled_at`` 唯一
  时间源 ``_utcnow_iso()`` = ``datetime.now(timezone.utc).isoformat()``
  （admin_store.py:82，写入点 :358/:472/:518/:540/:573）——恒为 aware
  ``+00:00`` 形态，**不含 naive**。
- run 事件 ``timestamp``：runner.py 写侧恒 ``now(timezone.utc).isoformat()``
  （:1436/:1453/:1466/:3492/:3513）——恒为 aware，**不含 naive**。
- naive 仅可能来自人工修补/外部工具文件，且此类写入实测多为本地
  ``now()`` 墙钟（design D1 定调依据）——翻转后按本地解读与其真实时刻
  一致；含 naive 记录的时效判定窗口平移已被设计接受（design Risks 第 4 条）。

epoch 数值分支与 bool 排除保留（``parse_ts`` 不收数值）；aware 输入行为
不变。runner 侧与 ``latency._default_ts_parser`` 的字段等价契约在契约测试
样本（无 naive 形态）上保持成立；naive 形态自本 SPEC 起有意分叉
（latency 留白名单待 SPEC-B 批②迁移）。
"""

import os
import time
import unittest
from datetime import datetime, timezone

from core import timelib
from core.agent_runner import runner as runner_mod
from core.pm_engine import recovery
from core.pm_engine.verification import escalation


class TZAsiaShanghai:
    """进程级临时切到 Asia/Shanghai，结束后恢复原 TZ（house 先例）。"""

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


def _old_iso_epoch(text):
    """旧实现参照（recovery/runner 收拢前：Z 归一 + naive→UTC）。"""
    text = str(text).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


class TestRecoveryParseEventTimestamp(unittest.TestCase):
    """recovery._parse_event_timestamp：数值分支保留 + naive 翻转。"""

    def test_epoch_numeric_passthrough(self):
        self.assertEqual(recovery._parse_event_timestamp(123.0), 123.0)
        self.assertEqual(recovery._parse_event_timestamp(42), 42.0)

    def test_bool_excluded(self):
        """bool 是 int 子类：True/False 不得直通成 epoch 1.0/0.0 假样本。"""
        self.assertIsNone(recovery._parse_event_timestamp(True))
        self.assertIsNone(recovery._parse_event_timestamp(False))

    def test_aware_inputs_unchanged(self):
        expected = datetime(2026, 9, 30, 2, 33, tzinfo=timezone.utc).timestamp()
        self.assertEqual(recovery._parse_event_timestamp("2026-09-30T02:33:00Z"), expected)
        self.assertEqual(recovery._parse_event_timestamp("2026-09-30T02:33:00+00:00"), expected)
        self.assertEqual(
            recovery._parse_event_timestamp("2026-09-30T10:33:00+08:00"), expected)

    def test_naive_flipped_utc_to_local(self):
        """naive→UTC 翻转为 naive→本地：本地 10:33 == 02:33Z（旧实现读成
        10:33Z，差 8h——有意行为变化，模块 docstring 留痕）。"""
        with TZAsiaShanghai():
            expected = datetime(2026, 9, 30, 2, 33, tzinfo=timezone.utc).timestamp()
            self.assertEqual(recovery._parse_event_timestamp("2026-09-30T10:33:00"), expected)
            self.assertEqual(
                recovery._parse_event_timestamp("2026-09-30T10:33:00"),
                recovery._parse_event_timestamp("2026-09-30T02:33:00Z"))
            # 与旧实现的差 = 一个时区偏移
            old = _old_iso_epoch("2026-09-30T10:33:00")
            self.assertEqual(old - expected, 8 * 3600)

    def test_unparseable_returns_none(self):
        for raw in (None, "garbage", "", "   ", "not-a-date"):
            self.assertIsNone(recovery._parse_event_timestamp(raw), raw)


class TestRunnerParseEventTimestamp(unittest.TestCase):
    """runner._parse_event_timestamp：同口径翻转 + 契约样本等价保持。"""

    def _parse(self, ts):
        return runner_mod.AgentRunner._parse_event_timestamp({"timestamp": ts})

    def test_numeric_and_bool_branches(self):
        self.assertEqual(self._parse(123.0), 123.0)
        self.assertIsNone(self._parse(True))
        self.assertIsNone(self._parse(None))
        self.assertIsNone(self._parse({}))

    def test_naive_flipped_utc_to_local(self):
        with TZAsiaShanghai():
            self.assertEqual(
                self._parse("2026-09-30T10:33:00"),
                self._parse("2026-09-30T02:33:00Z"))
            old = _old_iso_epoch("2026-09-30T10:33:00")
            self.assertEqual(old - self._parse("2026-09-30T10:33:00"), 8 * 3600)

    def test_contract_samples_still_equivalent_with_latency(self):
        """契约测试样本（无 naive 形态）与 latency._default_ts_parser 等价
        保持——test_agent_runner_modules_contract 的镜像样本。"""
        from core.agent_runner import latency

        samples = [
            {"timestamp": "2026-09-16T10:00:00Z"},
            {"timestamp": "2026-09-16T10:00:00.123+08:00"},
            {"timestamp": 123.0},
            {"timestamp": 42},
            {"timestamp": True},
            {"timestamp": None},
            {"timestamp": "not-a-date"},
            {},
        ]
        for e in samples:
            self.assertEqual(
                latency._default_ts_parser(e),
                runner_mod.AgentRunner._parse_event_timestamp(e), e)


class _FakeStore:
    def __init__(self, records):
        self._records = records

    def read_all(self):
        return self._records


class _FakePipeline:
    class _Context:
        class logger:
            @staticmethod
            def warning(*args, **kwargs):
                pass

    _context = _Context()


SIGNAL_RECORD = {
    "kind": "signal",
    "signal_type": "inconclusive_loop",
    "spec": "spec-x",
}


class TestEscalationDispositionStaleFlip(unittest.TestCase):
    """escalation._env_exempt_disposition_is_stale：naive 信号 × aware 处置
    的时效判定翻转（nested _parse_ts 收拢 parse_ts 的行为级锁定）。"""

    def _judge(self, signal_created, disposition_created):
        store = _FakeStore([dict(SIGNAL_RECORD, created=signal_created)])
        disposition = {"created": disposition_created}
        return escalation._env_exempt_disposition_is_stale(
            _FakePipeline(), store, "spec-x", disposition)

    def test_naive_signal_local_vs_aware_disposition_is_fresh(self):
        """处置记录（02:34Z）晚于 naive 信号的真实时刻（本地 10:33 == 02:33Z）
        → 新鲜放行（False）。旧 naive→UTC 口径下信号读成 10:33Z → 判陈旧
        （True）——翻转点。"""
        with TZAsiaShanghai():
            self.assertFalse(
                self._judge("2026-09-30T10:33:00", "2026-09-30T02:34:00+00:00"))

    def test_disposition_older_than_signal_is_stale(self):
        """处置早于信号真实时刻 → 陈旧放行（True），fail-closed 语义不回归。"""
        with TZAsiaShanghai():
            self.assertTrue(
                self._judge("2026-09-30T10:33:00", "2026-09-30T02:32:00+00:00"))

    def test_unparseable_disposition_fail_closed(self):
        """处置 created 不可解析 → 按陈旧处置（docstring fail-closed 不回归）。"""
        with TZAsiaShanghai():
            self.assertTrue(
                self._judge("2026-09-30T10:33:00", "garbage"))

    def test_no_signal_records_not_stale(self):
        store = _FakeStore([])
        self.assertFalse(
            escalation._env_exempt_disposition_is_stale(
                _FakePipeline(), store, "spec-x", {"created": "garbage"}))


class TestParseTsCoercionParity(unittest.TestCase):
    """escalation nested _parse_ts 的 ``str(value or "")`` 预处理与 parse_ts
    组合的边界等价（None/空串/数值 → None；naive → 本地）。"""

    def test_boundaries(self):
        with TZAsiaShanghai():
            self.assertIsNone(timelib.parse_ts(str(None or "")))
            self.assertIsNone(timelib.parse_ts(str(0)))
            self.assertEqual(
                timelib.parse_ts(str("2026-09-30T10:33:00")),
                datetime(2026, 9, 30, 2, 33, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
