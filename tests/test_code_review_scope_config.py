"""add-code-review-scope-config：周期审查范围配置（admin.code_review.scope）测试。

覆盖：
- ``get_code_review_config`` scope 缺省 / 合法两档 / 非法值回退；
- ``admin_monitor`` 周期触发（``_run_code_review_checkpoint``）在 scope=window
  与 full 两档下 ``collect_manifest`` / ``run_code_review`` 实参断言
  （review_kind 恒 scheduled；full 档 window_start=None）；
- full 档 manifest 空走既有 no_files 路径且日志带 scope 标注（task 2.2）；
- 守卫（enabled 关闭 / run_at 未到 / 同自然日防重）两档行为一致。

替身注入形态沿用 tests/test_code_review.py（fake run_code_review +
code_review_executor=None 同步执行）；全部文件落 tempfile 临时目录，
不触真实用户级配置。
"""

import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock


def _make_repo() -> Path:
    root = Path(tempfile.mkdtemp(prefix="cr-scope-"))
    (root / ".fenix").mkdir(parents=True, exist_ok=True)
    return root


class MagicMockResult:
    run_id = "code-review-1"
    success = True
    inserted = 0
    updated = 0
    resolved = 0
    error = ""


class _Runner:
    """fake agent_runner：捕获 run_code_review 实参（对齐 test_code_review.py）。"""

    _running_agents = {}

    def __init__(self):
        self.calls = []

    def run_code_review(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        return MagicMockResult()


class _FakeLogger:
    """项目自定义 logger 协议替身：info/error(tag, message) 两参形态。

    MUST NOT 传标准 logging.Logger——其 info(msg, *args) 会把 tag 当格式串
    做 %-formatting，触发 TypeError（协议不同）。
    """

    def __init__(self):
        self.records = []

    def info(self, tag, message):
        self.records.append(f"INFO {tag} {message}")

    def error(self, tag, message):
        self.records.append(f"ERROR {tag} {message}")


class _MonitorHarness:
    """AdminMonitor + 核心替身注入（compute_window/collect_manifest/状态读写全替身）。"""

    def __init__(self, cr_cfg, window_start=None):
        from core.admin_monitor import AdminMonitor

        self.repo = _make_repo()
        self.logger = _FakeLogger()
        self.runner = _Runner()
        self.window_start = window_start or datetime(2026, 9, 22, 2, 0, 0)
        self.mon = AdminMonitor(
            # self_review.run_at="00:00"：避开缺省 02:00 与真实时钟的竞态
            # （run_at 守卫对本套件恒放行，守卫本身由 TestCheckpointGuardsBothScopes 覆盖）
            {"admin": {"code_review": cr_cfg, "self_review": {"enabled": True, "run_at": "00:00"}}},
            None,
            str(self.repo),
            self.logger,
            agent_runner=self.runner,
            code_review_executor=None,
        )
        # 函数内 import 取模块属性 → patch 源模块即生效
        self._patches = [
            mock.patch("core.code_review.compute_window", return_value=(self.window_start, "self_review")),
            mock.patch("core.code_review.collect_manifest", return_value=["src/a.py", "src/b.py"]),
            mock.patch("core.code_review.read_code_review_state", return_value={}),
            mock.patch("core.code_review.save_code_review_state"),
        ]
        self.mocks = [p.start() for p in self._patches]

    def dispose(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(str(self.repo), ignore_errors=True)


# ── 1. get_code_review_config scope 配置 ───────────────────────────


class TestScopeConfig(unittest.TestCase):
    def _cfg(self, code_review):
        from core.config import ConfigLoader

        return ConfigLoader.get_code_review_config({"admin": {"code_review": code_review}})

    def test_missing_scope_defaults_to_window(self):
        # 键缺失（含整段缺失）回显 window —— 历史行为向后兼容
        self.assertEqual(self._cfg({})["scope"], "window")
        self.assertEqual(self._cfg({"enabled": True, "max_files": 100})["scope"], "window")
        self.assertEqual(self._cfg({})["enabled"], False)
        self.assertEqual(self._cfg({})["max_files"], 500)

    def test_legal_values(self):
        self.assertEqual(self._cfg({"scope": "window"})["scope"], "window")
        self.assertEqual(self._cfg({"scope": "full"})["scope"], "full")

    def test_invalid_values_fallback_to_window(self):
        # 非法字面量 / 非字符串类型（含 bool/int/None/容器）一律回退 window，
        # 不抛异常（巡检路径 MUST NOT 因脏配置中断）
        for bad in ("today", "FULL", "full ", "全库", 123, 0, True, False, None, ["full"], {"v": "full"}, 1.5):
            cfg = self._cfg({"scope": bad})
            self.assertEqual(cfg["scope"], "window", f"bad={bad!r}")

    def test_non_dict_section_falls_back(self):
        from core.config import ConfigLoader

        cfg = ConfigLoader.get_code_review_config({"admin": {"code_review": "full"}})
        self.assertEqual(cfg["scope"], "window")


class TestDashboardWriteChainScope(unittest.TestCase):
    """设置页保存链（config_admin）的 scope 写入/校验/回显。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="cr-scope-cfg-"))
        (self.tmpdir / ".fenix").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(str(self.tmpdir), ignore_errors=True)

    def test_write_scope_full_persists_and_echoes(self):
        from core.dashboard.data import write_config, read_config

        result = write_config(
            self.tmpdir, {"code_review": {"enabled": True, "scope": "full", "max_files": 200}}
        )
        self.assertTrue(result["ok"], result)
        echoed = read_config(self.tmpdir)
        self.assertEqual(echoed["code_review"]["scope"], "full")
        self.assertEqual(echoed["code_review"]["enabled"], True)
        # 落盘 yaml 实文件含 scope（write 链不得丢键）
        import yaml

        raw = yaml.safe_load((self.tmpdir / ".fenix" / "config.yaml").read_text())
        self.assertEqual(raw["admin"]["code_review"]["scope"], "full")

    def test_write_invalid_scope_rejected_no_partial_write(self):
        from core.dashboard.data import write_config, read_config

        result = write_config(self.tmpdir, {"code_review": {"scope": "today"}})
        self.assertFalse(result["ok"])
        self.assertIn("scope", result.get("error", ""))
        # 拒绝不半写：config.yaml 不产生 code_review 段
        echoed = read_config(self.tmpdir)
        self.assertEqual(echoed["code_review"]["scope"], "window")

    def test_user_scope_default_echo_includes_window(self):
        from core.dashboard.data import read_config

        echoed = read_config(self.tmpdir)
        self.assertEqual(
            echoed["code_review"],
            {
                "enabled": False,
                "max_files": 500,
                "scope": "window",
                "stall_alert_minutes": 15,
            },
        )


# ── 2. 周期触发两档实参断言 ─────────────────────────────────────────


class TestCheckpointScopeDispatch(unittest.TestCase):
    def test_window_scope_dispatch_args(self):
        # scope=window（缺省）：与改动前逐字节一致——窗口收集 + window_start 同源
        h = _MonitorHarness({"enabled": True})
        try:
            result = h.mon._run_code_review_checkpoint()
            from core.self_review import local_today_str

            self.assertEqual(
                result,
                {"triggered": True, "ok": True, "reason": "scheduled", "date": local_today_str()},
            )
            # collect_manifest：window 档实参
            h.mocks[1].assert_called_once_with(h.repo, scope="window", window_start=h.window_start)
            # run_code_review：review_kind 恒 scheduled，window_start 同源
            self.assertEqual(len(h.runner.calls), 1)
            call = h.runner.calls[0]
            self.assertEqual(call["args"], (["src/a.py", "src/b.py"],))
            self.assertEqual(
                call["kwargs"],
                {"review_kind": "scheduled", "window_start": h.window_start, "scope": "window"},
            )
        finally:
            h.dispose()

    def test_full_scope_dispatch_args(self):
        # scope=full：全仓收集（window_start=None），run_code_review scope="full"、
        # window_start=None，review_kind 保持 scheduled（审计口径不变）
        h = _MonitorHarness({"enabled": True, "scope": "full"})
        try:
            result = h.mon._run_code_review_checkpoint()
            self.assertEqual(result["reason"], "scheduled")
            h.mocks[1].assert_called_once_with(h.repo, scope="full", window_start=None)
            self.assertEqual(len(h.runner.calls), 1)
            call = h.runner.calls[0]
            self.assertEqual(
                call["kwargs"],
                {"review_kind": "scheduled", "window_start": None, "scope": "full"},
            )
        finally:
            h.dispose()

    def test_full_scope_empty_manifest_no_files_path(self):
        # task 2.2：full 档 manifest 空（异常态）→ 既有 no_files 路径记录并跳过，
        # 不派发 run；防重状态照写；日志文案带 scope 标注
        h = _MonitorHarness({"enabled": True, "scope": "full"})
        try:
            h.mocks[1].return_value = []
            result = h.mon._run_code_review_checkpoint()
            self.assertEqual(result["reason"], "no_files")
            self.assertEqual(len(h.runner.calls), 0)
            h.mocks[2].assert_called_once()
            h.mocks[3].assert_called_once()
            joined = "\n".join(h.logger.records)
            self.assertIn("scope=full", joined)
        finally:
            h.dispose()


# ── 3. 守卫两档行为一致 ─────────────────────────────────────────────


class TestCheckpointGuardsBothScopes(unittest.TestCase):
    def test_disabled_zero_action_both_scopes(self):
        for scope in ("window", "full"):
            cr = {"enabled": False} if scope == "window" else {"enabled": False, "scope": "full"}
            h = _MonitorHarness(cr)
            try:
                result = h.mon._run_code_review_checkpoint()
                self.assertEqual(result, {"triggered": False, "reason": "disabled"}, f"scope={scope}")
                self.assertEqual(len(h.runner.calls), 0, f"scope={scope}")
                # 零动作：不写任何 code-review 产物
                h.mocks[3].assert_not_called()
            finally:
                h.dispose()

    def test_before_run_at_both_scopes(self):
        # run_at 未到（23:59）不触发——两档守卫同源
        for cr in ({"enabled": True}, {"enabled": True, "scope": "full"}):
            h = _MonitorHarness({**cr, "_sr_run_at": "23:59"})
            try:
                h.mon.config = {
                    "admin": {
                        "code_review": cr,
                        "self_review": {"enabled": True, "run_at": "23:59"},
                    }
                }
                result = h.mon._run_code_review_checkpoint()
                self.assertEqual(result, {"triggered": False, "reason": "before_run_at"}, f"cr={cr}")
                self.assertEqual(len(h.runner.calls), 0)
            finally:
                h.dispose()

    def test_already_ran_today_both_scopes(self):
        # 同自然日防重：预写今日状态 → 跳过（不派发、不覆盖状态）。
        # today 必须动态取（与 local_today_str() 同源），硬编码日期跨日即腐坏
        #（实测 2026-09-23 写死后 09-24 起恒假失败）
        from core.self_review import local_today_str

        today = local_today_str()
        for cr in ({"enabled": True}, {"enabled": True, "scope": "full"}):
            h = _MonitorHarness(cr)
            try:
                h.mocks[2].return_value = {"last_run_date": today}
                result = h.mon._run_code_review_checkpoint()
                self.assertEqual(result, {"triggered": False, "reason": "already_ran_today"}, f"cr={cr}")
                self.assertEqual(len(h.runner.calls), 0)
                h.mocks[3].assert_not_called()
            finally:
                h.dispose()


if __name__ == "__main__":
    unittest.main()
