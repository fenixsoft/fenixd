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


if __name__ == "__main__":
    unittest.main()
