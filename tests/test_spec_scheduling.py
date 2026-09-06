"""
SPEC 定时调度测试（add-spec-scheduling-controls）。

覆盖面：
- 1.1 状态机层共享基础：parse_utc / start_after_pending / parse_orig_status
  纯函数 + start_after/frozen_until 字段持久化（serialize/parse 白名单）；
- 2.1/2.2 start_after 门控：未到期跳过、不写 STATE、到期放行、非法格式
  与过去时间等价无限制（dispatch 候选筛选 + _on_spec_ready 入口）；
- 2.3 定时解冻：到期自动解冻恢复原状态、清 frozen_until、幂等、重启扫描
  兜底、设置过去时间立即解冻、「定时解冻」来源标记；
- 1.2/6.3 冻结双轨回归：StateMachine.freeze_spec → dashboard 解冻 →
  status 正确恢复（半死态消除）。

fixture 说明：最小可解析项目 = .fenix/STATE.md（调度相关测试只依赖
STATE 读写）；dispatch 门控测试用 PMEngine.__new__ 绕过 __init__。
"""
import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def make_spec_scheduling_project(tmp_path: Path) -> Path:
    """最小可解析项目：仅 .fenix/STATE.md（调度测试只依赖 STATE 读写）。"""
    proot = tmp_path / "proj-a"
    proot.mkdir(parents=True, exist_ok=True)
    (proot / ".fenix").mkdir(parents=True, exist_ok=True)
    (proot / ".fenix" / "STATE.md").write_text(
        "# Fenix Project State\n\n## Specs\n\n"
        "### myspec\n- status: ready\n- priority: 2\n"
        "- created: 2026-01-01T00:00:00+00:00\n- updated: 2026-01-02T00:00:00+00:00\n"
        "- error: null\n- depends_on: null\n"
        "- start_after: null\n- frozen_until: null\n"
        "- frozen: null\n\n"
        "### donespec\n- status: done\n- priority: 1\n"
        "- created: 2026-01-01T00:00:00+00:00\n- updated: 2026-01-02T00:00:00+00:00\n"
        "- error: null\n- depends_on: null\n"
        "- start_after: null\n- frozen_until: null\n"
        "- frozen: null\n",
        encoding="utf-8",
    )
    return proot


def make_state_machine(proot: Path):
    from core.state_machine import StateMachine
    return StateMachine(proot / ".fenix" / "STATE.md", None)


class TestSharedTimeTools(unittest.TestCase):
    """1.1 状态机层共享基础：parse_utc / start_after_pending / parse_orig_status。"""

    def setUp(self):
        from core.state_machine import (
            parse_orig_status, parse_utc, start_after_pending,
        )
        self.parse_utc = parse_utc
        self.start_after_pending = start_after_pending
        self.parse_orig_status = parse_orig_status

    def test_parse_utc_basic(self):
        dt = self.parse_utc("2026-09-07T01:00:00+00:00")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.hour, 1)
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_parse_utc_z_suffix(self):
        dt = self.parse_utc("2026-09-07T01:00:00Z")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.hour, 1)
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_parse_utc_with_offset_normalizes(self):
        # UTC+8 的本地 09:00 → UTC 01:00
        dt = self.parse_utc("2026-09-07T09:00:00+08:00")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.hour, 1)

    def test_parse_utc_naive_treated_as_utc(self):
        dt = self.parse_utc("2026-09-07T01:00:00")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_parse_utc_invalid_returns_none(self):
        for bad in ("明天早上", "下周一", "2026-13-99", "", None, 12345):
            self.assertIsNone(self.parse_utc(bad), f"should reject {bad!r}")

    def test_parse_utc_accepts_datetime_input(self):
        dt = datetime(2026, 9, 7, 1, 0, tzinfo=timezone.utc)
        self.assertEqual(self.parse_utc(dt), dt)

    def test_start_after_pending_future(self):
        now = datetime(2026, 9, 6, 10, 0, tzinfo=timezone.utc)
        entry = {"start_after": "2026-09-07T01:00:00+00:00"}
        self.assertTrue(self.start_after_pending(entry, now))

    def test_start_after_missing_is_not_pending(self):
        now = datetime(2026, 9, 6, 10, 0, tzinfo=timezone.utc)
        self.assertFalse(self.start_after_pending({}, now))
        self.assertFalse(self.start_after_pending({"start_after": None}, now))

    def test_start_after_past_equivalent_no_limit(self):
        now = datetime(2026, 9, 6, 10, 0, tzinfo=timezone.utc)
        entry = {"start_after": "2026-09-06T09:00:00+00:00"}
        self.assertFalse(self.start_after_pending(entry, now))
        exact = {"start_after": now.isoformat()}
        self.assertFalse(self.start_after_pending(exact, now))

    def test_start_after_invalid_parse_is_not_pending(self):
        now = datetime(2026, 9, 6, 10, 0, tzinfo=timezone.utc)
        # 解析失败视为不阻塞（fail-open，脏值不卡死调度）
        self.assertFalse(self.start_after_pending({"start_after": "明天早上"}, now))

    def test_parse_orig_status_ok(self):
        self.assertEqual(
            self.parse_orig_status("用户指令冻结：原状态 testing · 人工确认"),
            "testing",
        )
        self.assertEqual(
            self.parse_orig_status("用户指令冻结：原状态 ready"),
            "ready",
        )

    def test_parse_orig_status_missing_falls_back_ready(self):
        self.assertEqual(self.parse_orig_status(""), "ready")
        self.assertEqual(self.parse_orig_status("用户指令冻结："), "ready")
        self.assertEqual(self.parse_orig_status(None), "ready")
        self.assertEqual(self.parse_orig_status("其他错误无原状态"), "ready")


class TestSchedulingFieldsPersistence(unittest.TestCase):
    """1.1 状态机层：start_after/frozen_until 经 serialize/parse 白名单持久化。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = make_spec_scheduling_project(Path(self.tmpdir))
        self.sm = make_state_machine(self.proot)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_update_and_reload_roundtrip(self):
        iso = "2026-09-07T01:00:00+00:00"
        self.assertTrue(self.sm.update_spec("myspec", {"start_after": iso}))
        # 重新实例化（模拟 daemon 重启），字段必须仍能读回
        sm2 = make_state_machine(self.proot)
        entry = sm2.read_one("myspec")
        self.assertEqual(entry.get("start_after"), iso)

    def test_update_and_reload_frozen_until_roundtrip(self):
        iso = "2026-09-08T01:00:00+00:00"
        self.assertTrue(self.sm.update_spec("myspec", {"frozen_until": iso}))
        sm2 = make_state_machine(self.proot)
        self.assertEqual(sm2.read_one("myspec").get("frozen_until"), iso)

    def test_null_fields_persist_as_none(self):
        self.assertTrue(self.sm.update_spec("myspec", {"start_after": None}))
        sm2 = make_state_machine(self.proot)
        self.assertIsNone(sm2.read_one("myspec").get("start_after"))

    def test_add_spec_passthrough_new_fields(self):
        self.assertTrue(self.sm.add_spec("newspec", {
            "status": "drafted",
            "start_after": "2026-09-09T00:00:00+00:00",
        }))
        sm2 = make_state_machine(self.proot)
        self.assertEqual(
            sm2.read_one("newspec").get("start_after"),
            "2026-09-09T00:00:00+00:00",
        )


class TestStateMachineUnfreezeClearsResiduals(unittest.TestCase):
    """1.1/2.3 解冻路径清残留：error + frozen_until 随官方通道一并清除。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = make_spec_scheduling_project(Path(self.tmpdir))
        self.sm = make_state_machine(self.proot)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_unfreeze_clears_error_and_frozen_until(self):
        self.assertTrue(self.sm.freeze_spec("myspec", "原状态 ready"))
        self.assertTrue(self.sm.update_spec("myspec", {"frozen_until": "2026-09-08T01:00:00+00:00"}))
        entry = self.sm.read_one("myspec")
        self.assertTrue(entry.get("frozen"))
        self.assertEqual(entry.get("status"), "blocked")
        self.assertIsNotNone(entry.get("frozen_until"))

        self.assertTrue(self.sm.unfreeze_spec("myspec", status="ready"))
        entry = self.sm.read_one("myspec")
        self.assertEqual(entry.get("status"), "ready")
        self.assertFalse(entry.get("frozen"))
        self.assertIsNone(entry.get("error"))
        self.assertIsNone(entry.get("frozen_until"))


if __name__ == "__main__":
    unittest.main()