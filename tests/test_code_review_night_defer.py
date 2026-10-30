"""test_code_review_night_defer.py — 周期审查跨窗顺延测试
（evo-add-review-night-defer-snapshot-writeoff 2.1 / 4.2）

覆盖 ``admin_monitor._run_code_review_checkpoint`` 单飞判定后新增的跨窗
顺延判定：

- 样本最大值推得预计区间压窗 → reason=night_quiet_window_deferred，且同日
  防重状态未写（save_code_review_state 零调用）、单飞标志已复位、manifest
  未收集（判定先于副作用）；
- 无有效样本回退仅判派发时刻落窗（窗外照常派发、窗内顺延）；
- 预计区间与窗不相交（含恰压线窗起点）→ 照常派发；
- 归档读取异常/损坏行降级不阻断（fail-open）。

估计口径为近 3 轮 duration_s **最大值**（evo-review-night-window-resume-
hardening 1.2：均值改 max——纯均值对时长方差与单调上行趋势系统性滞后）；
可用样本不足 3 时取已有样本最大值。

替身注入形态沿 tests/test_code_review_scope_config.py（fake run_code_review
+ code_review_executor=None 同步执行）；时间注入 patch
``core.admin_monitor.time.localtime``（判定显式走本地时区，与断窗时刻对齐
——spec R6 同源口径）；全部文件落 tempfile 临时目录。
"""

import json
import shutil
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock


def _make_repo() -> Path:
    root = Path(tempfile.mkdtemp(prefix="cr-defer-"))
    (root / ".fenix").mkdir(parents=True, exist_ok=True)
    return root


def _local(h, m, s=0):
    """注入用本地时刻 struct（2026-10-11 周日）。"""
    return time.struct_time((2026, 10, 11, h, m, s, 6, 284, -1))


class MagicMockResult:
    run_id = "code-review-1"
    success = True
    inserted = 0
    updated = 0
    resolved = 0
    error = ""


class _Runner:
    """fake agent_runner：捕获 run_code_review 实参（对齐 scope_config）。"""

    _running_agents = {}

    def __init__(self):
        self.calls = []

    def run_code_review(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        return MagicMockResult()


class _FakeLogger:
    def __init__(self):
        self.records = []

    def info(self, tag, message):
        self.records.append(f"INFO {tag} {message}")

    def warning(self, tag, message):
        self.records.append(f"WARNING {tag} {message}")

    def error(self, tag, message):
        self.records.append(f"ERROR {tag} {message}")


_MULTI_WINDOW = "03:00-03:15,04:15-04:45"


class _MonitorHarness:
    """AdminMonitor + 核心替身注入（compute_window/collect_manifest/状态读写全替身）。"""

    def __init__(self, window=_MULTI_WINDOW):
        from core.admin_monitor import AdminMonitor

        self.repo = _make_repo()
        self.logger = _FakeLogger()
        self.runner = _Runner()
        self.mon = AdminMonitor(
            {
                "admin": {
                    "code_review": {"enabled": True},
                    # run_at="00:00"：守卫对本套件恒放行（沿 scope_config 同款）
                    "self_review": {"enabled": True, "run_at": "00:00"},
                    "code_review_fix": {"night_quiet_window": window},
                }
            },
            None,
            str(self.repo),
            self.logger,
            agent_runner=self.runner,
            code_review_executor=None,
        )
        self._patches = [
            mock.patch("core.code_review.compute_window",
                       return_value=(datetime(2026, 10, 11, 2, 0, 0), "self_review")),
            mock.patch("core.code_review.collect_manifest",
                       return_value=["src/a.py", "src/b.py"]),
            mock.patch("core.code_review.read_code_review_state", return_value={}),
            mock.patch("core.code_review.save_code_review_state"),
        ]
        self.mocks = [p.start() for p in self._patches]

    def dispose(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(str(self.repo), ignore_errors=True)

    def write_archive(self, specs):
        """写归档 code-review run 转录（specs: [(run_id, duration_s 或 None)]）。

        mtime 按specs 序显式递增（os.utime）：读取侧按归档新→旧取最近 3 轮，
        同秒写入的 mtime 平局会使「最近 3 轮」排序不稳，须锚定次序。
        """
        import os

        archive = self.repo / ".fenix" / "runs" / "archive"
        archive.mkdir(parents=True, exist_ok=True)
        for i, (rid, dur) in enumerate(specs):
            line = {"type": "run_metrics", "run_id": rid, "turns": 2}
            if dur is not None:
                line["duration_s"] = dur
            p = archive / f"{rid}.jsonl"
            p.write_text(
                json.dumps(line, ensure_ascii=False) + "\n", encoding="utf-8")
            os.utime(p, (1791000000.0 + i, 1791000000.0 + i))

    def checkpoint_at(self, h, m, s=0):
        """注入派发时刻跑 checkpoint（patch core.admin_monitor.time.localtime）。"""
        with mock.patch("core.admin_monitor.time.localtime",
                        return_value=_local(h, m, s)):
            return self.mon._run_code_review_checkpoint()


class TestPredictedCrossingDefers(unittest.TestCase):
    """样本最大值推得预计区间压窗 → 顺延且零副作用（task 4.2 / 1.2）。"""

    def test_defers_without_side_effects(self):
        # 派发 01:00:30 + 近轮最大时长 7200s → 预计结束 03:00:30 越过窗起点
        # 03:00:00（严格大于＝相交）→ 顺延
        h = _MonitorHarness()
        try:
            h.write_archive([("code-review-1791500000", 7200.0)])
            result = h.checkpoint_at(1, 0, 30)
            self.assertEqual(
                result,
                {"triggered": False, "reason": "night_quiet_window_deferred"})
            # 零副作用：不派发、不收集 manifest、不写同日防重状态
            self.assertEqual(len(h.runner.calls), 0)
            h.mocks[1].assert_not_called()
            h.mocks[3].assert_not_called()
            # 单飞标志已复位（对齐空 manifest 分支口径）
            self.assertFalse(h.mon._code_review_in_flight)
            # 日志含预计区间与下一可派发时刻（相交窗=03:00-03:15）
            joined = "\n".join(h.logger.records)
            self.assertIn("预计区间 01:00-03:00", joined)
            self.assertIn("窗区间 03:00-03:15", joined)
            self.assertIn("下一可派发时刻=", joined)
        finally:
            h.dispose()

    def test_recent_limit_takes_last_three_rounds(self):
        # 样本窗取最近 3 轮最大值：远古超长轮滚出窗口后不再参与估计
        h = _MonitorHarness()
        try:
            h.write_archive([
                ("code-review-1791000000", 10 ** 7),  # 远古超长轮
                ("code-review-1791500000", 60.0),
                ("code-review-1791600000", 60.0),
                ("code-review-1791700000", 60.0),
            ])
            result = h.checkpoint_at(1, 0, 0)
            self.assertEqual(result["reason"], "scheduled",
                             "近 3 轮 max 60s 不跨窗，远古样本不参与")
        finally:
            h.dispose()

    def test_max_not_mean_upward_trend_defers(self):
        # evo-review-night-window-resume-hardening 1.2 / spec Scenario「上行
        # 趋势下拦截穿窗派发」：近 3 轮 10893/12500/5338 秒，01:00 派发——
        # 估计取 max 12500s（均值 9577.2s 会判不相交放行），预计结束 04:28
        # 落入 04:15-04:45 静默窗 → 顺延
        h = _MonitorHarness(window="04:15-04:45")
        try:
            h.write_archive([
                ("code-review-1791500000", 10893.0),
                ("code-review-1791600000", 12500.0),
                ("code-review-1791700000", 5338.0),
            ])
            result = h.checkpoint_at(1, 0, 0)
            self.assertEqual(
                result,
                {"triggered": False, "reason": "night_quiet_window_deferred"},
                "max 估计 12500s 预测穿窗 MUST 顺延，不再以均值 9577s 放行")
            joined = "\n".join(h.logger.records)
            self.assertIn("预计区间 01:00-04:28", joined)
            self.assertIn("窗区间 04:15-04:45", joined)
            self.assertIn("近几轮实测最大时长 12500 秒", joined)
        finally:
            h.dispose()

    def test_partial_samples_take_available_max(self):
        # 可用样本不足 3 时取已有样本最大值：样本 {60, 7200} 均值 3630s
        # 预计结束 02:00:30 不跨窗（均值口径会放行），max 7200s 预计结束
        # 03:00:30 越过 03:00 窗起点 → 顺延
        h = _MonitorHarness()
        try:
            h.write_archive([
                ("code-review-1791500000", 60.0),
                ("code-review-1791600000", 7200.0),
            ])
            result = h.checkpoint_at(1, 0, 30)
            self.assertEqual(
                result,
                {"triggered": False, "reason": "night_quiet_window_deferred"},
                "不足 3 样本取已有样本最大值 7200s，预测跨窗顺延")
            joined = "\n".join(h.logger.records)
            self.assertIn("近几轮实测最大时长 7200 秒", joined)
        finally:
            h.dispose()

    def test_multi_window_crossing_takes_latest_end(self):
        # 预计区间与两窗相交（01:00 + 4h = 05:00 越过两窗起点）：
        # 下一可派发时刻取最晚窗末（仅日志文案）
        h = _MonitorHarness(window="03:00-04:15,04:00-04:45")
        try:
            h.write_archive([("code-review-1791500000", 14400.0)])
            result = h.checkpoint_at(1, 0, 0)
            self.assertEqual(
                result,
                {"triggered": False, "reason": "night_quiet_window_deferred"})
            joined = "\n".join(h.logger.records)
            self.assertIn("窗区间 03:00-04:15, 04:00-04:45", joined)
            self.assertIn("预计区间 01:00-05:00", joined)
        finally:
            h.dispose()


class TestNoSampleFallback(unittest.TestCase):
    """无有效样本回退仅判派发时刻落窗（task 4.2）。"""

    def test_outside_window_dispatches(self):
        # 归档为空（无样本）+ 派发时刻窗外 → 照常派发
        h = _MonitorHarness()
        try:
            result = h.checkpoint_at(1, 0, 30)
            self.assertEqual(
                result,
                {"triggered": True, "ok": True, "reason": "scheduled",
                 "date": result["date"]})
            self.assertEqual(len(h.runner.calls), 1)
            h.mocks[3].assert_called_once()
        finally:
            h.dispose()

    def test_dispatch_time_inside_window_defers(self):
        # 无样本 + 派发时刻本身落窗（04:30 ∈ 04:15-04:45）→ 顺延
        h = _MonitorHarness()
        try:
            result = h.checkpoint_at(4, 30)
            self.assertEqual(
                result,
                {"triggered": False, "reason": "night_quiet_window_deferred"})
            h.mocks[3].assert_not_called()
            self.assertFalse(h.mon._code_review_in_flight)
            joined = "\n".join(h.logger.records)
            self.assertIn("仅判派发时刻落窗", joined)
            self.assertIn("预计区间 04:30（派发时刻）", joined)
        finally:
            h.dispose()

    def test_missing_duration_field_samples_skipped(self):
        # 历史行未记时长（1.2 之前落盘形态）＝无有效样本 → 回退派发时刻判定
        h = _MonitorHarness()
        try:
            h.write_archive([
                ("code-review-1791500000", None),
                ("code-review-1791600000", None),
            ])
            result = h.checkpoint_at(1, 0, 30)
            self.assertEqual(result["reason"], "scheduled",
                             "缺样 MUST NOT 阻塞派发（fail-open）")
        finally:
            h.dispose()


class TestNotCrossingDispatches(unittest.TestCase):
    """预计区间与窗不相交 → 照常派发（task 4.2）。"""

    def test_short_run_dispatches(self):
        # 01:00:30 + 60s = 01:01:30，距窗起点尚远 → 照常派发
        h = _MonitorHarness()
        try:
            h.write_archive([("code-review-1791500000", 60.0)])
            result = h.checkpoint_at(1, 0, 30)
            self.assertEqual(result["reason"], "scheduled")
            self.assertEqual(len(h.runner.calls), 1)
            h.mocks[3].assert_called_once()
        finally:
            h.dispose()

    def test_exact_touch_of_window_start_dispatches(self):
        # 预计结束恰压窗起点（01:00:00 + 7200s = 03:00:00 整）＝不相交
        # （对齐 code-fix 守卫「<= 压线视作不相交」口径）
        h = _MonitorHarness()
        try:
            h.write_archive([("code-review-1791500000", 7200.0)])
            result = h.checkpoint_at(1, 0, 0)
            self.assertEqual(result["reason"], "scheduled",
                             "恰压线窗起点视作不相交，MUST NOT 引入额外延迟")
        finally:
            h.dispose()


class TestArchiveReadDegradation(unittest.TestCase):
    """归档读取异常/损坏降级不阻断（task 4.2）。"""

    def test_corrupt_archive_lines_degrade_to_dispatch_time(self):
        # 归档行损坏（非 JSON/非 run_metrics/负值时长）→ 无有效样本回退
        h = _MonitorHarness()
        try:
            archive = h.repo / ".fenix" / "runs" / "archive"
            archive.mkdir(parents=True, exist_ok=True)
            (archive / "code-review-1791500000.jsonl").write_text(
                "{broken json\n"
                + json.dumps({"type": "result", "run_id": "x"}) + "\n"
                + json.dumps({"type": "run_metrics", "duration_s": -5}) + "\n",
                encoding="utf-8")
            result = h.checkpoint_at(1, 0, 30)
            self.assertEqual(
                result["reason"], "scheduled",
                "损坏归档按无样本回退，窗外派发 MUST NOT 被阻断")
        finally:
            h.dispose()

    def test_sampling_exception_degrades_to_normal_dispatch(self):
        # 取样链路抛异常（目录列举等）→ 判定整体按不顺延处理（fail-open）
        h = _MonitorHarness()
        try:
            h.write_archive([("code-review-1791500000", 7200.0)])
            with mock.patch.object(
                h.mon, "_code_review_archive_duration_mean",
                side_effect=RuntimeError("boom"),
            ):
                result = h.checkpoint_at(1, 0, 30)
            self.assertEqual(
                result["reason"], "scheduled",
                "取样异常 MUST NOT 阻断派发主路径")
        finally:
            h.dispose()


class TestBoolWindowAdminParity(unittest.TestCase):
    """布尔入参下审查顺延守卫路径与告警对等（evo-add-night-window-bool-
    normalization 1.3/3.2）：false 停用零告警（停用态排除）、true fail-open
    + 与 code-fix 车道同款 WARNING（进程级去重，两消费点共享去重集）。"""

    def _harness(self, window):
        """带进程级去重集隔离的 harness（本类用例各自从空集起算）。"""
        import core.admin_monitor as am

        h = _MonitorHarness(window=window)
        patcher = mock.patch.object(
            am, "_NIGHT_QUIET_INVALID_WARNED", set())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(h.dispose)
        return h

    def _illegal_warnings(self, h):
        return [r for r in h.logger.records
                if "WARNING" in r and "夜间静默窗配置非法" in r]

    def test_bool_false_window_dispatches_without_illegal_warning(self):
        """false（YAML 裸 off 的 safe_load 形态）＝显式停用：窗内时刻审查
        照常派发，零非法告警（停用态排除，防与「false＝显式停用」语义冲突
        制造假告警）。"""
        h = self._harness(False)
        result = h.checkpoint_at(4, 30)
        self.assertEqual(
            result, {"triggered": True, "ok": True, "reason": "scheduled",
                     "date": result["date"]},
            "守卫显式停用：窗内派发时刻不顺延")
        self.assertEqual(self._illegal_warnings(h), [])

    def test_bool_true_window_fails_open_with_same_wording_warning(self):
        """true 显式拒判为非法：审查顺延判定 fail-open（不阻断派发）+
        与 code-fix 车道同文案 WARNING（进程级去重，二次 checkpoint 不重发）。"""
        h = self._harness(True)
        result = h.checkpoint_at(4, 30)
        self.assertEqual(
            result, {"triggered": True, "ok": True, "reason": "scheduled",
                     "date": result["date"]},
            "窗值非法按无窗处理，MUST NOT 阻断派发主路径")
        warns = self._illegal_warnings(h)
        self.assertEqual(len(warns), 1)
        self.assertIn("'True'", warns[0])
        self.assertIn("admin 夜间静默窗配置非法", warns[0])
        self.assertIn("off/空串关闭", warns[0], "与 code-fix 车道同文案")
        # 二次 checkpoint：同值进程级去重，不重复告警
        h.checkpoint_at(4, 30)
        self.assertEqual(len(self._illegal_warnings(h)), 1,
                         "进程级去重：同值不重复刷屏")

    def test_two_consumption_points_share_process_dedup(self):
        """审查跨窗顺延与 admin 唤起避让两消费点共享同一去重集：同值合计
        至多一条告警（对等口径：与 code-fix 车道单实例去重形态对齐）。"""
        h = self._harness(True)
        reasons = h.mon._night_dispatch_block_reasons()
        self.assertEqual(
            [r for r in reasons if "夜间静默窗内" in r], [],
            "窗值非法按无窗处理，唤起不避让")
        h.mon._code_review_night_window_defer()
        h.mon._night_dispatch_block_reasons()
        self.assertEqual(
            len(self._illegal_warnings(h)), 1,
            "两消费点共享进程级去重：同值合计至多一条")

    def test_bool_false_no_warning_at_block_reasons_point(self):
        """唤起避让消费点同款停用态排除：false 不避让、零非法告警。"""
        h = self._harness(False)
        with mock.patch("core.admin_monitor.time.localtime",
                        return_value=_local(4, 30)):
            reasons = h.mon._night_dispatch_block_reasons()
        self.assertEqual(reasons, [], "停用态不避让")
        self.assertEqual(self._illegal_warnings(h), [])


if __name__ == "__main__":
    unittest.main()
