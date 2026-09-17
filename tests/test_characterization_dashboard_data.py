"""
Characterization tests for core.dashboard.data uncovered functions.

Task 1.2 of refactor-dashboard-data-module SPEC.
新增测试文件，不改现有测试文件。覆盖搬移前行为快照。
Task 1.2b: D8 两处 patch 语义锁定测试。
"""
import json
import os
import shutil
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestPatchSemanticsIsRunning(unittest.TestCase):
    """D8 锁定 1：patch("core.dashboard.data._is_running") 必须影响 daemon_health。

    搬移后 daemon_health 迁入 summary.py，但调用点必须经门面延迟解析
    （_facade._is_running），否则此测试在重构后失败——即锁定生效性而非假通过。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_patch_is_running_true_yields_running(self):
        from core.dashboard.data import daemon_health
        with patch("core.dashboard.data._is_running", return_value=True):
            self.assertEqual(daemon_health(self.tmpdir), "running")

    def test_patch_is_running_false_yields_stopped(self):
        from core.dashboard.data import daemon_health
        with patch("core.dashboard.data._is_running", return_value=False):
            self.assertEqual(daemon_health(self.tmpdir), "stopped")

    def test_patch_side_effect_counts_calls(self):
        """TTL 缓存内复用：patch 生效且只被调用一次。"""
        from core.dashboard.data import daemon_health
        calls = {"n": 0}

        def fake(root):
            calls["n"] += 1
            return True

        with patch("core.dashboard.data._is_running", side_effect=fake):
            self.assertEqual(daemon_health(self.tmpdir), "running")
            self.assertEqual(daemon_health(self.tmpdir), "running")
        self.assertEqual(calls["n"], 1)


class TestPatchSemanticsUserConfigPath(unittest.TestCase):
    """D8 锁定 2：patch("core.dashboard.data.USER_CONFIG_PATH") 必须影响配置读取。

    搬移后 read_config/read_effective_config 迁入 config_admin.py，但函数体内
    必须经门面读取 USER_CONFIG_PATH，否则 patch 静默失效、测试读真实
    ~/.fenix/config.yaml 出现环境敏感假失败。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_patch_user_config_path_redirects_read_effective_config(self):
        """read_effective_config 合并被 patch 的用户配置（而非真实 ~/.fenix/config.yaml）。"""
        from core.dashboard.data import read_effective_config
        # USER_CONFIG_DIR 指向 tmpdir，config.yaml 位于其中 → 与既有测试隔离形态一致
        user_path = Path(self.tmpdir) / "config.yaml"
        user_path.write_text("llm:\n  provider: patched-provider\n", encoding="utf-8")
        with patch("core.dashboard.data.USER_CONFIG_PATH", user_path), \
             patch("core.config.USER_CONFIG_DIR", Path(self.tmpdir)):
            result = read_effective_config(self.tmpdir)
            self.assertEqual(result["llm"]["provider"], "patched-provider")

    def test_patch_user_config_path_redirects_write_config_user_scope(self):
        """write_config(scope="user") 写入被 patch 的路径而非真实 ~/.fenix/config.yaml。"""
        from core.dashboard.data import write_config
        user_path = Path(self.tmpdir) / "user-fenix" / "config.yaml"
        with patch("core.dashboard.data.USER_CONFIG_PATH", user_path), \
             patch("core.config.USER_CONFIG_DIR", Path(self.tmpdir) / "user-fenix"):
            result = write_config(
                self.tmpdir, {"llm": {"provider": "patched-provider"}}, scope="user")
            self.assertTrue(result["ok"])
            self.assertEqual(result["scope"], "user")
            self.assertEqual(Path(result["path"]), user_path)
        self.assertTrue(user_path.exists())
        content = user_path.read_text(encoding="utf-8")
        self.assertIn("patched-provider", content)


class TestPureFunctions(unittest.TestCase):
    """锁定纯函数/无副作用函数的行为。"""

    # ── _should_overlay ──

    def test_overlay_live_statuses_return_true(self):
        from core.dashboard.data import _should_overlay
        for s in ("implementing", "implemented", "testing", "bug-found"):
            self.assertTrue(_should_overlay(s, False))
            self.assertTrue(_should_overlay(s, True))

    def test_overlay_done_pushed_no_uncompleted_returns_false(self):
        from core.dashboard.data import _should_overlay
        self.assertFalse(_should_overlay("done", False))
        self.assertFalse(_should_overlay("pushed", False))

    def test_overlay_done_pushed_with_uncompleted_returns_true(self):
        from core.dashboard.data import _should_overlay
        self.assertTrue(_should_overlay("done", True))
        self.assertTrue(_should_overlay("pushed", True))

    def test_overlay_other_statuses_returns_false(self):
        from core.dashboard.data import _should_overlay
        for s in ("drafted", "reviewing", "ready", "error", ""):
            self.assertFalse(_should_overlay(s, False))
            self.assertFalse(_should_overlay(s, True))

    # ── _norm_utc_iso ──

    def test_norm_utc_iso_converts_plus0000(self):
        from core.dashboard.data import _norm_utc_iso
        self.assertEqual(_norm_utc_iso("2026-09-15T10:00:00+00:00"), "2026-09-15T10:00:00Z")

    def test_norm_utc_iso_preserves_z(self):
        from core.dashboard.data import _norm_utc_iso
        self.assertEqual(_norm_utc_iso("2026-09-15T10:00:00Z"), "2026-09-15T10:00:00Z")

    def test_norm_utc_iso_no_change_without_suffix(self):
        from core.dashboard.data import _norm_utc_iso
        self.assertEqual(_norm_utc_iso("2026-09-15T10:00:00"), "2026-09-15T10:00:00")

    # ── _parse_iso_ts ──

    def test_parse_iso_ts_z_suffix(self):
        from core.dashboard.data import _parse_iso_ts
        dt = _parse_iso_ts("2026-09-15T12:30:45.123456Z")
        self.assertIsInstance(dt, datetime)
        self.assertEqual(dt.tzinfo, timezone.utc)
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 9)
        self.assertEqual(dt.hour, 12)

    def test_parse_iso_ts_plus0000_suffix(self):
        from core.dashboard.data import _parse_iso_ts
        dt = _parse_iso_ts("2026-09-15T12:30:45+00:00")
        self.assertIsInstance(dt, datetime)
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_parse_iso_ts_invalid_returns_none(self):
        from core.dashboard.data import _parse_iso_ts
        self.assertIsNone(_parse_iso_ts("not-a-timestamp"))
        self.assertIsNone(_parse_iso_ts(""))
        self.assertIsNone(_parse_iso_ts(None))
        self.assertIsNone(_parse_iso_ts(12345))

    def test_parse_iso_ts_naive_interpreted_as_utc(self):
        """fix-deferred-findings D2：无时区后缀（naive）结果补 tzinfo=utc。

        与项目「全链时间戳 UTC」约定一致（有意行为变化）：naive 输入不再
        返回 naive datetime（否则与 aware 的 datetime.max 比较会抛 TypeError）。
        """
        from core.dashboard.data import _parse_iso_ts
        dt = _parse_iso_ts("2026-09-15T12:00:00")
        self.assertIsInstance(dt, datetime)
        self.assertEqual(dt.tzinfo, timezone.utc)
        self.assertEqual(dt.hour, 12)
        # 补 tzinfo 后可与 aware 时间戳直接比较（不再抛 TypeError）
        aware = _parse_iso_ts("2026-09-15T12:00:01Z")
        self.assertLess(dt, aware)

    def test_run_meta_cached_naive_start_interpreted_as_utc(self):
        """fix-deferred-findings D2 下游消费点：runs.py::_run_meta_cached 对
        无时区后缀的 run 首事件戳按 UTC 解释。

        naive 输入经 _parse_iso_ts 补 tzinfo=utc 后：`started` 为 UTC 解释结果，
        `duration_seconds` 与 mtime - started 自洽（若按本地时区 CST=UTC+8 解释，
        duration 会凭空多出本地偏移）。
        """
        from core.dashboard.data.runs import _run_meta_cached

        tmpdir = tempfile.mkdtemp()
        try:
            runs_dir = Path(tmpdir) / ".fenix" / "runs"
            runs_dir.mkdir(parents=True)
            run_file = runs_dir / "impl-spec-x-1750000000-a1.jsonl"
            # 首事件戳无时区后缀（naive）
            run_file.write_text(
                json.dumps({"type": "started", "timestamp": "2026-09-15T12:00:00"}) + "\n",
                encoding="utf-8",
            )
            # mtime = 2026-09-15T12:00:30Z（started 后 30 秒）
            mtime = datetime(2026, 9, 15, 12, 0, 30, tzinfo=timezone.utc).timestamp()
            os.utime(run_file, (mtime, mtime))
            stat = run_file.stat()
            meta = _run_meta_cached(run_file, stat, time.time(), project_root=Path(tmpdir))
            # started 按 UTC 解释（本地时区解释会得到 04:00:00+00:00）
            self.assertEqual(meta["started"], "2026-09-15T12:00:00+00:00")
            # duration = mtime - started = 30s（自洽）
            self.assertEqual(meta["duration_seconds"], 30)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # ── _ts_delta ──

    def test_ts_delta_normal(self):
        from core.dashboard.data import _ts_delta
        a = "2026-09-15T12:00:00Z"
        b = "2026-09-15T12:00:10Z"
        self.assertEqual(_ts_delta(a, b), 10.0)
        self.assertEqual(_ts_delta(b, a), 10.0)

    def test_ts_delta_invalid_returns_none(self):
        from core.dashboard.data import _ts_delta
        self.assertIsNone(_ts_delta("bad", "2026-09-15T12:00:00Z"))
        self.assertIsNone(_ts_delta("2026-09-15T12:00:00Z", "bad"))

    # ── _timeline_sort_key ──

    def test_timeline_sort_key_state_before_run_same_second(self):
        from core.dashboard.data import _timeline_sort_key
        ts = "2026-09-15T12:00:00Z"
        state_event = {"time": ts, "kind": "state"}
        run_event = {"time": ts, "kind": "run"}
        self.assertLess(_timeline_sort_key(state_event), _timeline_sort_key(run_event))

    def test_timeline_sort_key_admin_between_state_and_run(self):
        from core.dashboard.data import _timeline_sort_key
        ts = "2026-09-15T12:00:00Z"
        state_event = {"time": ts, "kind": "state"}
        admin_event = {"time": ts, "kind": "admin"}
        run_event = {"time": ts, "kind": "run"}
        self.assertLess(_timeline_sort_key(state_event), _timeline_sort_key(admin_event))
        self.assertLess(_timeline_sort_key(admin_event), _timeline_sort_key(run_event))

    def test_timeline_sort_key_invalid_time_sorts_later(self):
        """无效时间戳分支（findings.md BUG-1 / fix-deferred-findings P0）：修复后
        无效事件返回 (datetime.max, 2, 原字符串) 排在末尾，不再抛 TypeError。"""
        from core.dashboard.data import _timeline_sort_key
        bad_event = {"time": "invalid", "kind": "state"}
        good_event = {"time": "2026-09-15T12:00:00Z", "kind": "run"}
        bad_key = _timeline_sort_key(bad_event)
        good_key = _timeline_sort_key(good_event)
        # 无效事件排在合法事件之后
        self.assertGreater(bad_key, good_key)
        # kind rank=2（run 类兜底值）确保末位
        self.assertEqual(bad_key[1], 2)

    # ── _parse_run_lines ──

    def test_parse_run_lines_normal(self):
        from core.dashboard.data import _parse_run_lines
        lines = ['{"type":"started","ts":1}', '{"type":"ended"}']
        events = _parse_run_lines(lines)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["type"], "started")
        self.assertEqual(events[1]["type"], "ended")

    def test_parse_run_lines_blank_lines_skipped(self):
        from core.dashboard.data import _parse_run_lines
        events = _parse_run_lines(['{"type":"a"}', '', '  ', '{"type":"b"}'])
        self.assertEqual(len(events), 2)

    def test_parse_run_lines_corrupt_line_becomes_stderr(self):
        from core.dashboard.data import _parse_run_lines
        events = _parse_run_lines(["{invalid json"])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "stderr")
        self.assertIn("invalid", events[0]["line"])

    def test_parse_run_lines_non_dict_becomes_stderr(self):
        from core.dashboard.data import _parse_run_lines
        events = _parse_run_lines(['"just a string"'])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "stderr")

    # ── _degraded_project ──

    def test_degraded_project_structure(self):
        from core.dashboard.data import _degraded_project
        p = {"name": "my-proj", "path": "/tmp/my-proj", "discovered": True}
        result = _degraded_project(p, "perm denied")
        self.assertEqual(result["name"], "my-proj")
        self.assertEqual(result["path"], "/tmp/my-proj")
        self.assertTrue(result["exists"])
        self.assertEqual(result["error"], "perm denied")
        self.assertEqual(result["daemon"], "stopped")
        self.assertEqual(result["hosting"], "stopped")

    def test_degraded_project_fallback_name(self):
        from core.dashboard.data import _degraded_project
        p = {"path": "/tmp/x"}
        result = _degraded_project(p, "err")
        self.assertEqual(result["name"], "x")

    # ── _backtrack_reason ──

    def test_backtrack_reason_known_transitions(self):
        from core.dashboard.data import _backtrack_reason
        self.assertEqual(_backtrack_reason("testing", "implementing"),
                         "验证失败/中断，回退实现")
        self.assertEqual(_backtrack_reason("implemented", "implementing"),
                         "实现未通过，回退重做")
        self.assertEqual(_backtrack_reason("anything", "bug-found"),
                         "验证发现 bug，退回修复")
        self.assertEqual(_backtrack_reason("ready", "ready"),
                         "实现失败，重试")
        self.assertEqual(_backtrack_reason("drafted", "drafted"),
                         "状态回退")

    # ── get_spec_start_after / get_frozen_until ──

    def test_get_spec_start_after_missing(self):
        from core.dashboard.data import get_spec_start_after
        self.assertIsNone(get_spec_start_after({}))
        self.assertIsNone(get_spec_start_after({"start_after": None}))
        self.assertIsNone(get_spec_start_after(None))

    def test_get_frozen_until_missing(self):
        from core.dashboard.data import get_frozen_until
        self.assertIsNone(get_frozen_until({}))
        self.assertIsNone(get_frozen_until({"frozen_until": None}))

    # ── _token_usage_view ──

    def test_token_usage_view_normal(self):
        from core.dashboard.data import _token_usage_view
        entry = {"_tokens_in": 1000, "_tokens_out": 200, "_cost_usd": 0.05}
        result = _token_usage_view(entry)
        self.assertEqual(result["tokens_in"], 1000)
        self.assertEqual(result["tokens_out"], 200)
        self.assertEqual(result["cost_usd"], 0.05)
        self.assertTrue(result["cost_available"])

    def test_token_usage_view_missing_keys(self):
        from core.dashboard.data import _token_usage_view
        result = _token_usage_view({})
        self.assertIsInstance(result, dict)

    # ── _parse_spec_ts ──

    def test_parse_spec_ts_valid(self):
        from core.dashboard.data import _parse_spec_ts
        dt = _parse_spec_ts("2026-09-15T12:30:45")
        self.assertIsInstance(dt, datetime)

    def test_parse_spec_ts_invalid(self):
        from core.dashboard.data import _parse_spec_ts
        self.assertIsNone(_parse_spec_ts("nope"))
        self.assertIsNone(_parse_spec_ts(None))
        self.assertIsNone(_parse_spec_ts(""))


class TestAdminAlertsGroup(unittest.TestCase):
    """admin_alerts 组 characterization tests。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_alerts(self, records):
        path = Path(self.tmpdir) / ".fenix" / "admin_alerts.json"
        path.write_text(json.dumps(records), encoding="utf-8")

    def test_get_alerts_returns_list(self):
        from core.dashboard.data import get_alerts
        self.assertEqual(get_alerts(self.tmpdir), [])
        self._write_alerts([{"id": "a1", "kind": "signal"}])
        result = get_alerts(self.tmpdir)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)

    def test_get_unhandled_alerts_filters_handled(self):
        from core.dashboard.data import get_unhandled_alerts
        self._write_alerts([
            {"id": "e1", "kind": "escalation", "handled": False, "severity": "critical"},
            {"id": "e2", "kind": "escalation", "handled": True},
        ])
        result = get_unhandled_alerts(self.tmpdir)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "e1")

    def test_mark_all_alerts_handled(self):
        from core.dashboard.data import mark_all_alerts_handled
        self._write_alerts([
            {"id": "e1", "kind": "escalation", "handled": False},
            {"id": "e2", "kind": "escalation", "handled": False},
        ])
        count = mark_all_alerts_handled(self.tmpdir)
        self.assertEqual(count, 2)
        from core.dashboard.data import get_unhandled_alerts
        self.assertEqual(get_unhandled_alerts(self.tmpdir), [])


class TestSpecArchiveGroup(unittest.TestCase):
    """spec_archive 组 characterization tests。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.spec_dir = Path(self.tmpdir) / "spec" / "changes" / "test-spec"
        self.spec_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_is_spec_archived_when_no_archive_dir(self):
        from core.dashboard.data import is_spec_archived
        self.assertFalse(is_spec_archived(self.tmpdir, "test-spec"))


class TestConfigFunctions(unittest.TestCase):
    """config_admin 组纯函数 characterization tests。"""

    def test_config_file_sig_returns_tuple_for_existing(self):
        from core.dashboard.data import _config_file_sig
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"test")
            path = Path(f.name)
        try:
            sig = _config_file_sig(path)
            self.assertIsInstance(sig, tuple)
            self.assertEqual(len(sig), 2)
            self.assertIsInstance(sig[0], int)
            self.assertEqual(sig[1], 4)
        finally:
            path.unlink()

    def test_config_file_sig_returns_none_for_missing(self):
        from core.dashboard.data import _config_file_sig
        self.assertIsNone(_config_file_sig(Path("/nonexistent/config.yaml")))

    def test_managed_key_sources_defaults(self):
        from core.dashboard.data import _managed_key_sources
        result = _managed_key_sources({})
        self.assertIsInstance(result, dict)
        self.assertIn("llm", result)
        self.assertEqual(result["llm"], "user")

    def test_managed_key_sources_project(self):
        from core.dashboard.data import _managed_key_sources
        result = _managed_key_sources({"llm": {"provider": "openai"}})
        self.assertEqual(result["llm"], "project")

    def test_managed_admin_keys_defaults(self):
        """_managed_admin_keys 返回 admin 段内容（非包裹键）。"""
        from core.dashboard.data import _managed_admin_keys
        result = _managed_admin_keys({})
        self.assertIsInstance(result, dict)
        self.assertIn("merge_breaker_threshold", result)
        self.assertIn("bug_repair_mode", result)
        self.assertEqual(result["bug_repair_mode"], "inplace")


class TestLogIndexPureHelpers(unittest.TestCase):
    """log_index 纯辅助函数 characterization tests。"""

    def test_build_log_block_index_empty_file(self):
        from core.dashboard.data import _build_log_block_index
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = Path(f.name)
        try:
            idx = _build_log_block_index(path, 0)
            self.assertEqual(idx["size"], 0)
            self.assertEqual(idx["offsets"], [0])
        finally:
            path.unlink()

    def test_build_log_block_index_small_file(self):
        from core.dashboard.data import _build_log_block_index, LOG_INDEX_BLOCK
        content = b"line1\nline2\nline3\n"
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(content)
            path = Path(f.name)
        try:
            idx = _build_log_block_index(path, len(content))
            self.assertEqual(idx["size"], len(content))
            self.assertIsInstance(idx["offsets"], list)
            self.assertGreater(len(idx["offsets"]), 0)
        finally:
            path.unlink()

    def test_log_index_path(self):
        from core.dashboard.data import _log_index_path
        result = _log_index_path(Path("/tmp/proj"))
        self.assertTrue(str(result).endswith("fenixd.log.offsets.json"))
        self.assertIn(".idx", str(result))


class TestTasksGroupHelpers(unittest.TestCase):
    """tasks 组辅助函数 characterization tests。"""

    def test_task_progress_no_tasks_returns_zero(self):
        """spec 不存在时 task_progress 返回 (0, 0)。"""
        from core.dashboard.data import task_progress
        done, total = task_progress("/nonexistent/project", "nonexistent-spec")
        self.assertEqual((done, total), (0, 0))


if __name__ == "__main__":
    unittest.main()
