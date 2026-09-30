"""timeline 域写手格式验读与四处读侧切换 characterization（3.1–3.5）。

add-timelib-consolidation-layer：四处读侧解析统一改走 ``timelib.parse_ts``
（naive 唯一策略=按本地时区解读，design D1）：

- ``core/dashboard/data/timeline.py`` ``_parse_iso_ts``（推翻
  fix-deferred-findings D2 的 naive 补 ``tzinfo=utc``）
- ``core/regression.py`` 守卫解析（原 naive ``astimezone()``，语义不变收拢）
- ``core/dashboard/routes/code_review_routes.py`` ``_parse_iso_utc``
  （原 naive→UTC，翻转）
- ``core/evolution.py`` ``_parse_iso``（原 naive 附本地 tzinfo 再转 UTC，
  语义不变收拢）

3.1 写手格式验读（spec Scenario「timeline 域写手格式验读先于切换」）——
worktree 内无 ``.fenix`` 运行时真实数据，按写手实现构造等价 fixture。该域
时间轴时间戳的全部写手与实际序列化格式：

===========================================  ==============================
写手                                          格式
===========================================  ==============================
admin_store 记录 ``created``                  aware UTC ``+00:00``
  （``datetime.now(timezone.utc).isoformat()``）
runner run 事件 ``timestamp``                  aware UTC ``+00:00``
verify_engine report ``timestamp``             aware UTC ``+00:00``
  （verify_engine/engine.py）
logger 日志行 ts（state 转移 / verify 开始行）  aware UTC ``Z`` 后缀
run started 回退（run_id 内嵌 epoch）           aware UTC ``+00:00``
  （``fromtimestamp(..., tz=timezone.utc)``）
naive（无后缀）                                仅历史遗留/外部人工 marker；
                                               实测多为本地 ``now()``
                                               （含 code_review 剥时区链
                                               产出的 naive 本地）
===========================================  ==============================

验读结论：**该域不存在 naive UTC 写手**——主流写手全部 aware，naive 仅
来自历史/外部人工数据且多为本地墙钟。新旧解析对照差异清单（机器时区
Asia/Shanghai）：

=================================  ================  =================  ======
输入形态                            旧（timeline D2）  新（parse_ts）     差异
=================================  ================  =================  ======
``...Z`` 后缀                       aware UTC         aware UTC          无
``...+00:00``                       aware UTC         aware UTC          无
naive 本地串（真实写手形态）          误读为 UTC         本地 aware         修正：
                                   （展示晚 8h）                       −8h 平移
naive 若真为 UTC 值（无此写手）       正确              误读 +8h          验读确认
                                                                      无此写手，
                                                                      残余仅外部
                                                                      人工按 UTC
                                                                      手写
解析失败 / None / 非字符串            None              None              无
=================================  ================  =================  ======

（regression.py 的旧 naive ``astimezone()`` 与 evolution.py 的旧 naive 附
本地 tzinfo 与新策略语义一致——验读确认无行为差异，仅实现收拢。）
"""

import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core import evolution, regression, timelib
from core.dashboard.data import _parse_iso_ts, _timeline_sort_key, _ts_delta
from core.dashboard.routes import code_review_routes


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


# ── 旧实现参照（验读对照用，与新策略逐条比对）───────────────────────────


def _old_timeline_parse(ts):
    """timeline 旧实现（fix-deferred-findings D2：naive 补 tzinfo=utc）。"""
    try:
        from datetime import datetime as _dt, timezone as _utz

        dt = _dt.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt is not None and dt.tzinfo is None:
            dt = dt.replace(tzinfo=_utz.utc)
        return dt
    except Exception:
        return None


def _old_routes_parse(value):
    """code_review_routes 旧实现（naive→UTC，design D6 字面口径）。"""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith(("Z", "z")):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _old_evolution_parse(value):
    """evolution 旧实现（naive 附本地 tzinfo 再转 UTC）。"""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        local_tz = datetime.now().astimezone().tzinfo
        dt = dt.replace(tzinfo=local_tz)
    return dt.astimezone(timezone.utc)


def _old_regression_parse(raw):
    """regression 旧实现（fromisoformat + naive astimezone()）。"""
    try:
        started = datetime.fromisoformat(str(raw))
        if started.tzinfo is None:
            started = started.astimezone()
        return started
    except (ValueError, TypeError):
        return None


# 四形态验读数据集（覆盖全部已知写手形态）
WRITER_FORMS = {
    "Z 后缀（logger 日志行）": "2026-09-30T02:33:00Z",
    "+00:00（admin_store/runner/verify 写手）": "2026-09-30T02:33:00+00:00",
    "naive 本地（历史/外部人工 marker）": "2026-09-30T10:33:00",
    "纯日期（罕见人工形态）": "2026-09-30",
}


class TestTimelineWriterFormsVerification(unittest.TestCase):
    """3.1 验读：新旧解析对四形态数据集逐条对照（差异清单见模块 docstring）。"""

    def test_aware_forms_identical_old_vs_new(self):
        """aware 形态（该域主流写手）新旧解析完全一致——切换对存量数据零影响。"""
        for label in ("Z 后缀（logger 日志行）", "+00:00（admin_store/runner/verify 写手）"):
            raw = WRITER_FORMS[label]
            self.assertEqual(
                _old_timeline_parse(raw), _parse_iso_ts(raw),
                f"aware 形态出现新旧解析差异（不应有）: {label}")

    def test_naive_form_is_the_single_intentional_diff(self):
        """naive 本地串：旧误读为 UTC（10:33Z），新按本地（=02:33Z）——修正
        −8h 展示平移，是本次唯一有意差异（模块 docstring 差异清单）。"""
        raw = WRITER_FORMS["naive 本地（历史/外部人工 marker）"]
        with TZAsiaShanghai():
            old = _old_timeline_parse(raw)
            new = _parse_iso_ts(raw)
        self.assertEqual(old, datetime(2026, 9, 30, 10, 33, tzinfo=timezone.utc))
        self.assertEqual(
            new, datetime(2026, 9, 30, 2, 33, tzinfo=timezone.utc),
            "naive 应按本地解读（10:33+08:00 = 02:33Z）")
        self.assertEqual((old - new).total_seconds(), 8 * 3600)

    def test_unparseable_forms_return_none_both(self):
        for raw in ("not-a-time", "", None, 12345, "   "):
            self.assertEqual(_old_timeline_parse(raw), _parse_iso_ts(raw), raw)


class TestTimelineParseIsoTs(unittest.TestCase):
    """3.2 timeline 切换 characterization：下游排序/差值行为锁定。"""

    def test_returns_aware_utc_for_z(self):
        dt = _parse_iso_ts("2026-09-15T12:30:45Z")
        self.assertEqual(dt.tzinfo, timezone.utc)
        self.assertEqual((dt.hour, dt.minute), (12, 30))

    def test_naive_interpreted_as_local(self):
        """推翻 D2：naive 补 UTC → 按本地（timelib 唯一策略）。"""
        with TZAsiaShanghai():
            dt = _parse_iso_ts("2026-09-15T12:00:00")
            self.assertEqual(
                timelib.to_storage(dt), "2026-09-15T04:00:00Z")

    def test_sort_key_mixed_naive_and_z_chronological(self):
        """混存 naive（本地写手）与 aware（主流写手）时按真实时刻排序。

        naive 本地 10:33:00 == 02:33:00Z，早于 02:33:30Z 半分钟；旧 D2 口径
        下 naive 读成 10:33Z 会被排到 40 分钟之后（排序失真），新口径修正。
        """
        with TZAsiaShanghai():
            naive_evt = {"time": "2026-09-30T10:33:00", "kind": "state"}
            z_evt = {"time": "2026-09-30T02:33:30Z", "kind": "run"}
            self.assertLess(
                _timeline_sort_key(naive_evt), _timeline_sort_key(z_evt))

    def test_ts_delta_naive_vs_z_uses_real_instant(self):
        with TZAsiaShanghai():
            self.assertEqual(
                _ts_delta("2026-09-30T10:33:00", "2026-09-30T02:33:30Z"), 30.0)

    def test_invalid_still_sorted_last(self):
        """解析失败事件按 datetime.max 排末尾（fix-deferred-findings P0 不回归）。"""
        bad = _timeline_sort_key({"time": "garbage", "kind": "state"})
        ok = _timeline_sort_key({"time": "2026-09-30T02:33:00Z", "kind": "run"})
        self.assertGreater(bad, ok)


class TestRegressionStaleGuard(unittest.TestCase):
    """3.3 regression 守卫切换：stale 判定行为锁定（naive 本地语义不变收拢）。"""

    def _marker(self, tmpdir, started_at, timeout_seconds=1800):
        d = Path(tmpdir) / ".fenix" / "regression"
        d.mkdir(parents=True, exist_ok=True)
        meta = {"started_at": started_at, "timeout_seconds": timeout_seconds}
        (d / ".running").write_text(json.dumps(meta), encoding="utf-8")

    def test_fresh_naive_marker_running(self):
        with TZAsiaShanghai():
            started = timelib.now_local().isoformat()
            with tempfile.TemporaryDirectory() as td:
                self._marker(td, started)
                self.assertTrue(regression.is_regression_running(td))

    def test_stale_naive_marker_not_running(self):
        with TZAsiaShanghai():
            started = (timelib.now_local() - timedelta(hours=2)).isoformat()
            with tempfile.TemporaryDirectory() as td:
                self._marker(td, started, timeout_seconds=1800)
                self.assertFalse(regression.is_regression_running(td))

    def test_stale_aware_z_marker_not_running(self):
        started = (timelib.now_utc() - timedelta(hours=2)).isoformat()
        with tempfile.TemporaryDirectory() as td:
            self._marker(td, started, timeout_seconds=1800)
            self.assertFalse(regression.is_regression_running(td))

    def test_garbage_and_malformed_marker_stale(self):
        with tempfile.TemporaryDirectory() as td:
            self._marker(td, "not-a-time")
            self.assertFalse(regression.is_regression_running(td))
            # 合法 JSON 非对象 → 非 dict 视为 stale（code-review 1e2951cac732 不回归）
            d = Path(td) / ".fenix" / "regression"
            (d / ".running").write_text("null", encoding="utf-8")
            self.assertFalse(regression.is_regression_running(td))

    def test_parse_semantics_identical_old_vs_new(self):
        """新旧解析语义对照：aware/naive/garbage 三类输入结果一致（收拢等价）。"""
        with TZAsiaShanghai():
            now_local = timelib.now_local()
            naive = now_local.replace(tzinfo=None).isoformat()
            aware = now_local.astimezone(timezone.utc).isoformat()
        for raw in (naive, aware, "garbage"):
            old = _old_regression_parse(raw)
            new = timelib.parse_ts(str(raw))
            if old is None:
                self.assertIsNone(new, raw)
            else:
                self.assertEqual(old, new, raw)

    def test_progress_elapsed_seconds_uses_naive_local(self):
        """read_progress 的 elapsed_seconds 对 naive marker 按本地解读（口径一致）。"""
        with TZAsiaShanghai():
            started = (timelib.now_local() - timedelta(seconds=90)).replace(
                tzinfo=None).isoformat()
            with tempfile.TemporaryDirectory() as td:
                self._marker(td, started)
                info = regression.read_progress(td)
        self.assertIsNotNone(info["elapsed_seconds"])
        self.assertGreaterEqual(info["elapsed_seconds"], 60)
        self.assertLess(info["elapsed_seconds"], 600)


class TestCodeReviewRoutesParse(unittest.TestCase):
    """3.4 routes 切换：naive→UTC 翻转为 naive→本地（有意行为变化）。"""

    def test_naive_flipped_from_utc_to_local(self):
        with TZAsiaShanghai():
            self.assertEqual(
                code_review_routes._parse_iso_utc("2026-09-30T10:33:00"),
                datetime(2026, 9, 30, 2, 33, tzinfo=timezone.utc))

    def test_aware_forms_unchanged(self):
        expected = datetime(2026, 9, 30, 2, 33, tzinfo=timezone.utc)
        self.assertEqual(
            code_review_routes._parse_iso_utc("2026-09-30T02:33:00Z"), expected)
        self.assertEqual(
            code_review_routes._parse_iso_utc("2026-09-30T02:33:00+00:00"), expected)

    def test_invalid_returns_none(self):
        self.assertIsNone(code_review_routes._parse_iso_utc("not-a-time"))
        self.assertIsNone(code_review_routes._parse_iso_utc(""))
        self.assertIsNone(code_review_routes._parse_iso_utc(None))
        self.assertIsNone(code_review_routes._parse_iso_utc("   "))

    def test_old_vs_new_single_diff_on_naive(self):
        """新旧对照：仅 naive 形态有差异（翻转点），aware/非法输入一致。"""
        for raw in ("2026-09-30T02:33:00Z", "2026-09-30T02:33:00+00:00",
                    "not-a-time", "", None):
            self.assertEqual(
                _old_routes_parse(raw), code_review_routes._parse_iso_utc(raw), raw)
        with TZAsiaShanghai():
            self.assertNotEqual(
                _old_routes_parse("2026-09-30T10:33:00"),
                code_review_routes._parse_iso_utc("2026-09-30T10:33:00"))


def _old_iso_to_local_dt(iso_str):
    """4.1 收拢前旧实现（code_review/self_review 逐字重复副本）。"""
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


class TestIsoToLocalDtCollapse(unittest.TestCase):
    """4.1 重复副本收拢：既有调用点输入新旧逐项相等（naive 本地 / None）。"""

    def test_equivalent_on_legal_and_illegal_corpus(self):
        """spec Scenario「重复副本删除后行为等价」：Z/+00:00/naive/垃圾串/
        None 新旧返回值逐项相等。"""
        from core import code_review, self_review
        with TZAsiaShanghai():
            corpus = [
                "2026-09-30T10:33:00Z",       # Z 后缀
                "2026-09-30T10:33:00+00:00",  # +00:00
                "2026-09-30T10:33:00",        # naive
                "2026-09-30T10:33:00+08:00",  # 带偏移
                "2026-09-30",                 # 纯日期
                "garbage", "", None,          # 垃圾串 / 空 / None
            ]
            for raw in corpus:
                expected = _old_iso_to_local_dt(raw)
                self.assertEqual(code_review._iso_to_local_dt(raw), expected, raw)
                self.assertEqual(self_review._iso_to_local_dt(raw), expected, raw)

    def test_output_is_naive_local_safe_for_window_compare(self):
        """输出恒为 naive 本地（aware 折算本地后剥时区）——与窗口边界的
        naive ``datetime.now()`` 直接相减不抛 TypeError（MUST NOT 接 aware）。"""
        from core import code_review
        with TZAsiaShanghai():
            dt = code_review._iso_to_local_dt("2026-09-30T02:33:00Z")
            self.assertIsNone(dt.tzinfo)
            self.assertEqual(
                (dt.year, dt.month, dt.day, dt.hour), (2026, 9, 30, 10))
            delta = (datetime.now() - dt).total_seconds()  # naive-naive 可比较
            self.assertLess(delta, 86400)


class TestEvolutionParseIso(unittest.TestCase):
    """3.5 evolution 切换：naive 附本地 tzinfo 语义不变（收拢等价）。"""

    def test_naive_local_to_utc_instant(self):
        with TZAsiaShanghai():
            self.assertEqual(
                evolution._parse_iso("2026-09-30T10:33:00"),
                datetime(2026, 9, 30, 2, 33, tzinfo=timezone.utc))

    def test_aware_forms_normalized_to_utc(self):
        expected = datetime(2026, 9, 30, 2, 33, tzinfo=timezone.utc)
        self.assertEqual(evolution._parse_iso("2026-09-30T02:33:00Z"), expected)
        self.assertEqual(evolution._parse_iso("2026-09-30T10:33:00+08:00"), expected)

    def test_invalid_returns_none(self):
        self.assertIsNone(evolution._parse_iso("garbage"))
        self.assertIsNone(evolution._parse_iso(""))
        self.assertIsNone(evolution._parse_iso(None))
        self.assertIsNone(evolution._parse_iso(123))

    def test_old_vs_new_identical_all_forms(self):
        """收拢等价：四形态+非法输入新旧结果逐项相等。"""
        for raw in list(WRITER_FORMS.values()) + ["garbage", "", None]:
            self.assertEqual(
                _old_evolution_parse(raw), evolution._parse_iso(raw), raw)


if __name__ == "__main__":
    unittest.main()
