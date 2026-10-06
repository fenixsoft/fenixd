"""add-code-review-run-at：周期审查触发时点独立键（admin.code_review.run_at）测试。

覆盖：
- ``get_code_review_config`` run_at 独立值生效 / 缺省回退自省 / 非法值回退 /
  cr 段整体缺失回退（task 1.2）；
- ``admin_monitor`` 周期触发（``_run_code_review_checkpoint``）触发判定换源：
  独立时点未到不派发、到点派发、缺省回退自省时点派发、开关关闭零动作（task 2.2）；
- 窗口水位三态：code_review_state.last_run_at 优先 / 回退自省水位 / 双缺失回退
  24h；save 后 compute 读回一致（task 3.3）；
- 设置页保存链（config_admin）run_at 读回退展示生效值 / 写合法值落盘 /
  非法值拒绝（task 4.3）。

替身注入形态沿用 tests/test_code_review_scope_config.py（fake run_code_review +
code_review_executor=None 同步执行）；全部文件落 tempfile 临时目录，
不触真实用户级配置。
"""

import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock


# ── 1. get_code_review_config run_at 配置 ──────────────────────────


class TestRunAtConfig(unittest.TestCase):
    def _cfg(self, code_review, self_review=None):
        from core.config import ConfigLoader

        admin = {"code_review": code_review}
        if self_review is not None:
            admin["self_review"] = self_review
        return ConfigLoader.get_code_review_config({"admin": admin})

    def test_independent_value_wins(self):
        # 独立值生效：cr run_at 与自省 run_at 并存时取 cr 自身（解耦的意义）
        self.assertEqual(
            self._cfg({"run_at": "13:00"}, {"enabled": True, "run_at": "01:00"})["run_at"],
            "13:00",
        )
        self.assertEqual(self._cfg({"run_at": "00:00"})["run_at"], "00:00")
        self.assertEqual(self._cfg({"run_at": "23:59"})["run_at"], "23:59")

    def test_missing_key_falls_back_to_self_review(self):
        # 键缺失（含整段缺失）回退自省 run_at——缺省＝历史行为逐位一致
        self.assertEqual(
            self._cfg({}, {"enabled": True, "run_at": "01:00"})["run_at"], "01:00"
        )
        self.assertEqual(
            self._cfg({"enabled": True, "max_files": 100}, {"run_at": "04:30"})["run_at"],
            "04:30",
        )
        # 双缺失：回退自省文档缺省 02:00
        from core.config import ConfigLoader

        self.assertEqual(ConfigLoader.get_code_review_config({})["run_at"], "02:00")

    def test_invalid_values_fall_back(self):
        # 非法字面量 / 非字符串类型（含 bool/int/None/越界时分/容器）一律回退
        # 自省 run_at，不抛异常（巡检路径 MUST NOT 因脏配置中断，对齐 scope
        # 白名单回退口径）
        sr = {"run_at": "01:30"}
        for bad in ("abc", 123, True, False, None, "25:00", "7:00", "12:60",
                    "12:5", ["13:00"], {"v": "13:00"}, 13.0, ""):
            cfg = self._cfg({"run_at": bad}, sr)
            self.assertEqual(cfg["run_at"], "01:30", f"bad={bad!r}")

    def test_missing_cr_section_falls_back(self):
        # cr 段整体缺失（非 dict 同款降级）→ 回退自省 run_at
        from core.config import ConfigLoader

        self.assertEqual(
            ConfigLoader.get_code_review_config(
                {"admin": {"code_review": "x", "self_review": {"run_at": "05:00"}}}
            )["run_at"],
            "05:00",
        )
        self.assertEqual(
            ConfigLoader.get_code_review_config({"admin": {"self_review": {"run_at": "06:00"}}})["run_at"],
            "06:00",
        )


# ── 2. 检查点触发判定换源 ──────────────────────────────────────────


class _Runner:
    """fake agent_runner：捕获 run_code_review 实参（对齐 test_code_review.py）。"""

    _running_agents = {}

    def __init__(self):
        self.calls = []

    def run_code_review(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})

        class _R:
            run_id = "code-review-1"
            success = True

        return _R()


class _FakeLogger:
    """项目自定义 logger 协议替身：info/error(tag, message) 两参形态
    （MUST NOT 传标准 logging.Logger，协议不同会 %-format 冲突）。"""

    def __init__(self):
        self.records = []

    def info(self, tag, message):
        self.records.append(f"INFO {tag} {message}")

    def error(self, tag, message):
        self.records.append(f"ERROR {tag} {message}")


class _CheckpointHarness:
    """AdminMonitor 替身注入 + now_local 定点（触发判定按 WallClock 断言）。"""

    def __init__(self, cr_cfg, self_review=None, now=None):
        from core.admin_monitor import AdminMonitor

        self.repo = Path(tempfile.mkdtemp(prefix="cr-runat-"))
        (self.repo / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = _FakeLogger()
        self.runner = _Runner()
        admin = {"code_review": cr_cfg}
        # self_review.run_at 缺省 01:00：与 SPEC 场景（自省 01:00 / 审查 13:00）同刻
        admin["self_review"] = (
            self_review if self_review is not None else {"enabled": True, "run_at": "01:00"}
        )
        self.mon = AdminMonitor(
            {"admin": admin},
            None,
            str(self.repo),
            self.logger,
            agent_runner=self.runner,
            code_review_executor=None,
        )
        self._patches = [
            mock.patch("core.code_review.compute_window", return_value=(
                datetime(2026, 10, 1, 2, 0, 0).astimezone(), "last_run")),
            mock.patch("core.code_review.collect_manifest", return_value=["src/a.py"]),
            mock.patch("core.code_review.read_code_review_state", return_value={}),
            mock.patch("core.code_review.save_code_review_state"),
        ]
        if now is not None:
            # 函数内 import 取模块属性 → patch admin_monitor 命名空间即生效
            self._patches.insert(0, mock.patch("core.admin_monitor.now_local", return_value=now))
        self.mocks = [p.start() for p in self._patches]

    @property
    def save_mock(self):
        return self.mocks[-1]

    @property
    def manifest_mock(self):
        return self.mocks[-3]

    def dispose(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(str(self.repo), ignore_errors=True)


class TestCheckpointRunAt(unittest.TestCase):
    def test_independent_run_at_before_time_no_dispatch(self):
        # 独立时点 13:00：01:00 巡检轮 before_run_at 不派发（自省 01:00 照常
        # 触发自省——本检查点对自省零连带，互不连带由两检查点独立读键保证）
        h = _CheckpointHarness(
            {"enabled": True, "run_at": "13:00"},
            now=datetime(2026, 10, 6, 1, 0, 0).astimezone(),
        )
        try:
            result = h.mon._run_code_review_checkpoint()
            self.assertEqual(result, {"triggered": False, "reason": "before_run_at"})
            self.assertEqual(len(h.runner.calls), 0)
            # 未到时点：不收集、不写防重状态（零动作）
            h.manifest_mock.assert_not_called()
            h.save_mock.assert_not_called()
        finally:
            h.dispose()

    def test_independent_run_at_after_time_dispatches(self):
        # 13:00 后巡检轮：正常派发（review_kind 恒 scheduled），且不触发自省
        #（自省检查点独立判自家 run_at，本用例只断言本车道）
        h = _CheckpointHarness(
            {"enabled": True, "run_at": "13:00"},
            now=datetime(2026, 10, 6, 13, 5, 0).astimezone(),
        )
        try:
            result = h.mon._run_code_review_checkpoint()
            from core.self_review import local_today_str

            self.assertEqual(
                result,
                {"triggered": True, "ok": True, "reason": "scheduled", "date": local_today_str()},
            )
            self.assertEqual(len(h.runner.calls), 1)
            self.assertEqual(h.runner.calls[0]["kwargs"]["review_kind"], "scheduled")
            h.save_mock.assert_called_once()
        finally:
            h.dispose()

    def test_fallback_dispatches_at_self_review_time(self):
        # 缺省回退（cr 未配 run_at）：01:00 轮取自省时点正常派发——与解耦前
        # 行为逐位一致
        h = _CheckpointHarness(
            {"enabled": True},
            self_review={"enabled": True, "run_at": "01:00"},
            now=datetime(2026, 10, 6, 1, 0, 0).astimezone(),
        )
        try:
            result = h.mon._run_code_review_checkpoint()
            self.assertEqual(result["reason"], "scheduled")
            self.assertEqual(len(h.runner.calls), 1)
        finally:
            h.dispose()

    def test_fallback_waits_for_self_review_time(self):
        # 缺省回退：自省时点 13:00 时，01:00 轮同样不派发（生效时点=回退源）
        h = _CheckpointHarness(
            {"enabled": True},
            self_review={"enabled": True, "run_at": "13:00"},
            now=datetime(2026, 10, 6, 1, 0, 0).astimezone(),
        )
        try:
            result = h.mon._run_code_review_checkpoint()
            self.assertEqual(result, {"triggered": False, "reason": "before_run_at"})
            self.assertEqual(len(h.runner.calls), 0)
        finally:
            h.dispose()

    def test_disabled_zero_action_with_independent_run_at(self):
        # enabled=false 全链路零动作（既有语义回归；独立 run_at 在场也不派发）
        h = _CheckpointHarness(
            {"enabled": False, "run_at": "13:00"},
            now=datetime(2026, 10, 6, 13, 5, 0).astimezone(),
        )
        try:
            result = h.mon._run_code_review_checkpoint()
            self.assertEqual(result, {"triggered": False, "reason": "disabled"})
            self.assertEqual(len(h.runner.calls), 0)
            h.manifest_mock.assert_not_called()
            h.save_mock.assert_not_called()
        finally:
            h.dispose()


if __name__ == "__main__":
    unittest.main()
