"""
add-settings-system-tab：设置页系统页签配置契约测试。

三组用例：
1. read_config admin 段回显（含缺省填充、不透传未知键、merge_breaker 回退 agents）
2. write_config admin 段非法值拒绝（enabled/interval_minutes/escalation_cooldown_minutes/
   merge_breaker_threshold/shutdown_drain_seconds）与合法值落盘回环
3. 既有段（llm/agents/gates/verify）零回归
"""
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml


class TestSystemAdminReadBack(unittest.TestCase):
    """read_config admin 段回显（白名单 + 缺省填充）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config_dir = Path(self.tmpdir) / ".fenix"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.config_dir / "config.yaml"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_raw(self, raw: dict):
        with self.config_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(raw, f, allow_unicode=True, sort_keys=False)

    def test_read_config_admin_defaults_filled(self):
        """缺省填充：无 admin 段时返回各键缺省值（含 bug_repair_mode=inplace）。"""
        from core.dashboard.data import read_config

        echoed = read_config(self.tmpdir)
        self.assertEqual(
            echoed["admin"],
            {
                "enabled": True,
                "interval_minutes": 5,
                "escalation_cooldown_minutes": 60,
                "merge_breaker_threshold": 2,
                "shutdown_drain_seconds": 1800,
                "bug_repair_mode": "inplace",
                # evo-stuck-signal-hygiene D4：stuck 处置后静默期默认 120 分钟
                "stuck_silence_minutes": 120,
            },
        )
        # 缺省来源标注为 user（未在本文件定义）
        self.assertEqual(echoed["sources"]["admin.enabled"], "user")

    def test_read_config_admin_echoes_written_values(self):
        """写回后回显一致（保存→回显闭环读路径）。"""
        from core.dashboard.data import read_config, write_config

        result = write_config(
            self.tmpdir,
            {
                "admin": {
                    "enabled": False,
                    "interval_minutes": 3,
                    "escalation_cooldown_minutes": 10,
                    "merge_breaker_threshold": 4,
                    "shutdown_drain_seconds": 300,
                }
            },
        )
        self.assertTrue(result["ok"], result.get("error"))
        echoed = read_config(self.tmpdir)
        self.assertEqual(echoed["admin"]["enabled"], False)
        self.assertEqual(echoed["admin"]["interval_minutes"], 3)
        self.assertEqual(echoed["admin"]["escalation_cooldown_minutes"], 10)
        self.assertEqual(echoed["admin"]["merge_breaker_threshold"], 4)
        self.assertEqual(echoed["admin"]["shutdown_drain_seconds"], 300)
        self.assertEqual(echoed["sources"]["admin.shutdown_drain_seconds"], "project")

    def test_read_config_merge_breaker_falls_back_to_agents(self):
        """merge_breaker_threshold 缺省沿用 agents 同名键（admin 未配置时）。"""
        from core.dashboard.data import read_config

        self._write_raw({"admin": {"shutdown_drain_seconds": 0},
                         "agents": {"merge_breaker_threshold": 5}})
        echoed = read_config(self.tmpdir)
        self.assertEqual(echoed["admin"]["merge_breaker_threshold"], 5)
        # admin 键显式配置时优先
        self._write_raw({"admin": {"merge_breaker_threshold": 7}})
        echoed = read_config(self.tmpdir)
        self.assertEqual(echoed["admin"]["merge_breaker_threshold"], 7)

    def test_read_config_does_not_leak_unknown_admin_keys(self):
        """不透传未知 admin 键、不纳入 self_review 子段。"""
        from core.dashboard.data import read_config

        self._write_raw({
            "admin": {
                "enabled": True,
                "unknown_key": 42,
                "workers": 2,
                "agent_model": "claude-sonnet-5",
                "self_review": {"enabled": True, "run_at": "02:00", "read_todo": False},
            }
        })
        echoed = read_config(self.tmpdir)
        self.assertEqual(
            set(echoed["admin"].keys()),
            {"enabled", "interval_minutes", "escalation_cooldown_minutes",
             "merge_breaker_threshold", "shutdown_drain_seconds", "bug_repair_mode",
             "stuck_silence_minutes"},
        )
        self.assertNotIn("self_review", echoed["admin"])


class TestSystemAdminWriteValidation(unittest.TestCase):
    """write_config admin 段校验：非法值拒绝保存、合法值落盘。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config_dir = Path(self.tmpdir) / ".fenix"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.config_dir / "config.yaml"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _assert_rejected(self, patch: dict, keyword: str):
        from core.dashboard.data import read_config, write_config
        before = read_config(self.tmpdir)
        result = write_config(self.tmpdir, patch)
        self.assertFalse(result["ok"], f"应当拒绝：{patch}")
        self.assertIn(keyword, result["error"])
        # 配置文件不被写入（回显不变）
        after = read_config(self.tmpdir)
        self.assertEqual(after["admin"], before["admin"])

    def test_admin_enabled_must_be_boolean(self):
        self._assert_rejected({"admin": {"enabled": "yes"}}, "enabled")

    def test_admin_interval_minutes_positive(self):
        """interval_minutes 填 -1 或 abc 拒绝保存并提示「须为正数」类明确错误。"""
        self._assert_rejected({"admin": {"interval_minutes": -1}}, "interval_minutes")
        self._assert_rejected({"admin": {"interval_minutes": "abc"}}, "interval_minutes")
        self._assert_rejected({"admin": {"interval_minutes": 0}}, "interval_minutes")

    def test_admin_escalation_cooldown_non_negative(self):
        self._assert_rejected({"admin": {"escalation_cooldown_minutes": -5}},
                              "escalation_cooldown_minutes")
        # 0 合法
        from core.dashboard.data import write_config
        ok = write_config(self.tmpdir, {"admin": {"escalation_cooldown_minutes": 0}})
        self.assertTrue(ok["ok"], ok.get("error"))

    def test_admin_merge_breaker_positive_integer(self):
        self._assert_rejected({"admin": {"merge_breaker_threshold": 0}},
                              "merge_breaker_threshold")
        self._assert_rejected({"admin": {"merge_breaker_threshold": 1.5}},
                              "merge_breaker_threshold")

    def test_admin_shutdown_drain_non_negative_integer(self):
        self._assert_rejected({"admin": {"shutdown_drain_seconds": -1}},
                              "shutdown_drain_seconds")
        self._assert_rejected({"admin": {"shutdown_drain_seconds": 1.5}},
                              "shutdown_drain_seconds")
        # 0（快速停机）合法
        from core.dashboard.data import write_config
        ok = write_config(self.tmpdir, {"admin": {"shutdown_drain_seconds": 0}})
        self.assertTrue(ok["ok"], ok.get("error"))

    def test_admin_valid_write_persists_and_keeps_unmanaged_keys(self):
        """合法值落盘：写入 .fenix/config.yaml 且保留非受管 admin 键。"""
        from core.dashboard.data import write_config

        result = write_config(self.tmpdir, {
            "admin": {"shutdown_drain_seconds": 300},
            "self_review": {"enabled": True},
        })
        self.assertTrue(result["ok"], result.get("error"))
        with self.config_path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        self.assertEqual(raw["admin"]["shutdown_drain_seconds"], 300)
        # 非受管 admin 键（agent_model）保留，不被合并分支抹掉
        self._write_with_agent_model()
        result = write_config(self.tmpdir, {"admin": {"interval_minutes": 3}})
        self.assertTrue(result["ok"], result.get("error"))
        with self.config_path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        self.assertEqual(raw["admin"]["agent_model"], "claude-sonnet-5")
        self.assertEqual(raw["admin"]["interval_minutes"], 3)

    def _write_with_agent_model(self):
        raw = {"admin": {"agent_model": "claude-sonnet-5"}}
        with self.config_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(raw, f, allow_unicode=True, sort_keys=False)


class TestSystemAdminExistingSectionsNoRegression(unittest.TestCase):
    """admin 段扩展后既有段（llm/agents/gates/verify）零回归。

    self_review 缺省三元组回显由 test_daily_self_review.py 的
    TestDashboardSelfReview 承担（跨文件二留一，此处不再重复断言）。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config_dir = Path(self.tmpdir) / ".fenix"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.config_dir / "config.yaml"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_existing_sections_structure_unchanged(self):
        """read_config 既有段返回结构逐字段不变（llm/agents/gates/verify）。"""
        from core.dashboard.data import read_config

        echoed = read_config(self.tmpdir)
        # llm 空对象
        self.assertEqual(echoed["llm"], {})
        # agents 含全部受管键 + 默认值
        for k in ("models", "max_concurrent", "run_timeout_seconds", "max_turns",
                  "daily_run_limit", "token_budget_millions", "impl_run_budget"):
            self.assertIn(k, echoed["agents"], k)
        self.assertEqual(echoed["agents"]["max_concurrent"], 2)
        # gates / verify（add-draft-promotion-gate：读侧缺省填充 promote_mode=auto；
        # add-spec-review-gate 补 spec_review_mode=auto；
        # add-start-after-scope-config 补 start_after_scope=dispatch）
        self.assertEqual(echoed["gates"],
                         {"approve_mode": "manual", "promote_mode": "auto",
                          "spec_review_mode": "auto", "start_after_scope": "dispatch"})
        self.assertEqual(echoed["verify"],
                         {"static_scope": "main", "deps_mode": "hardlink",
                          "serving_reclaim": {"enabled": True},
                          # add-impl-code-review-tuning：三运行参数恒回显缺省
                          # （add-impl-ocr-parallel-lane：并发缺省 2→4）
                          "impl_code_review_timeout_sec": 600,
                          "impl_code_review_concurrency": 4,
                          "impl_code_review_effort": "low",
                          # add-impl-ocr-parallel-lane：join 双档模式恒回显缺省
                          "impl_code_review_mode": "gate",
                          # fix-agent-lane-efficiency D3：上下文经济性告警阈值
                          "context_cost_per_turn_threshold": 200000})

    def test_roundtrip_verify_and_self_review_after_admin_write(self):
        """写入 admin 段后，verify/self_review 写读仍正常（互不干扰）。"""
        from core.dashboard.data import read_config, write_config

        write_config(self.tmpdir, {"verify": {"static_scope": "worktree",
                                              "deps_mode": "hardlink"}})
        write_config(self.tmpdir, {"admin": {"shutdown_drain_seconds": 300}})
        write_config(self.tmpdir, {"self_review": {"enabled": True}})
        echoed = read_config(self.tmpdir)
        self.assertEqual(echoed["verify"],
                         {"static_scope": "worktree", "deps_mode": "hardlink",
                          "serving_reclaim": {"enabled": True},
                          # add-impl-code-review-tuning：三运行参数恒回显缺省
                          # （add-impl-ocr-parallel-lane：并发缺省 2→4、补 mode 键）
                          "impl_code_review_timeout_sec": 600,
                          "impl_code_review_concurrency": 4,
                          "impl_code_review_effort": "low",
                          "impl_code_review_mode": "gate",
                          "context_cost_per_turn_threshold": 200000})
        self.assertEqual(echoed["self_review"]["enabled"], True)
        self.assertEqual(echoed["admin"]["shutdown_drain_seconds"], 300)


class TestBugRepairModeConfig(unittest.TestCase):
    """add-bug-repair-mode-config：bug_repair_mode 设置读取/持久化契约。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config_dir = Path(self.tmpdir) / ".fenix"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.config_dir / "config.yaml"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_raw(self, raw: dict):
        with self.config_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(raw, f, allow_unicode=True, sort_keys=False)

    def test_unconfigured_defaults_to_inplace(self):
        """未配置 → 读取链路返回缺省 inplace。"""
        from core.dashboard.data import read_config

        echoed = read_config(self.tmpdir)
        self.assertEqual(echoed["admin"]["bug_repair_mode"], "inplace")
        self.assertEqual(echoed["sources"]["admin.bug_repair_mode"], "user")

    def test_derive_write_persists_and_reads_back(self):
        """配置 derive → 写入落盘、读取链路返回 derive 且来源标注 project。"""
        from core.dashboard.data import read_config, write_config

        result = write_config(self.tmpdir, {"admin": {"bug_repair_mode": "derive"}})
        self.assertTrue(result["ok"], result.get("error"))
        with self.config_path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        self.assertEqual(raw["admin"]["bug_repair_mode"], "derive")

        echoed = read_config(self.tmpdir)
        self.assertEqual(echoed["admin"]["bug_repair_mode"], "derive")
        self.assertEqual(echoed["sources"]["admin.bug_repair_mode"], "project")

    def test_illegal_value_rejected_and_not_persisted(self):
        """非法取值（如 always）拒绝保存，配置文件不变（回显仍缺省 inplace）。"""
        from core.dashboard.data import read_config, write_config

        before = read_config(self.tmpdir)
        result = write_config(self.tmpdir, {"admin": {"bug_repair_mode": "always"}})
        self.assertFalse(result["ok"])
        self.assertIn("bug_repair_mode", result["error"])
        after = read_config(self.tmpdir)
        self.assertEqual(after["admin"], before["admin"])

    def test_raw_derive_file_reads_back_without_write(self):
        """手工写入 derive → read_config 直接回显 derive（读侧白名单对称）。"""
        from core.dashboard.data import read_config

        self._write_raw({"admin": {"bug_repair_mode": "derive"}})
        echoed = read_config(self.tmpdir)
        self.assertEqual(echoed["admin"]["bug_repair_mode"], "derive")
        # 其余受管键仍为缺省填充，不透传未知键
        self.assertEqual(echoed["admin"]["enabled"], True)


class TestImplCodeReviewConfig(unittest.TestCase):
    """add-impl-code-review-gate 任务 7.6：verify.impl_code_review 读写契约。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config_dir = Path(self.tmpdir) / ".fenix"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.config_dir / "config.yaml"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_raw(self, raw: dict):
        with self.config_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(raw, f, allow_unicode=True, sort_keys=False)

    def test_write_then_read_back_true(self):
        """写入 true → 落盘、读回为 True、来源标注 project。"""
        from core.dashboard.data import read_config, write_config

        result = write_config(
            self.tmpdir, {"verify": {"impl_code_review": True}})
        self.assertTrue(result["ok"], result.get("error"))
        with self.config_path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        self.assertTrue(raw["verify"]["impl_code_review"])

        echoed = read_config(self.tmpdir)
        self.assertTrue(echoed["verify"]["impl_code_review"])
        self.assertEqual(echoed["sources"]["verify.impl_code_review"], "project")

    def test_write_false_persists_false(self):
        """写入 false → 落盘为 false（而非删键），读回为 False。"""
        from core.dashboard.data import read_config, write_config

        write_config(self.tmpdir, {"verify": {"impl_code_review": True}})
        result = write_config(self.tmpdir, {"verify": {"impl_code_review": False}})
        self.assertTrue(result["ok"], result.get("error"))
        with self.config_path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        self.assertIs(raw["verify"]["impl_code_review"], False)
        echoed = read_config(self.tmpdir)
        self.assertIs(echoed["verify"]["impl_code_review"], False)
        self.assertEqual(echoed["sources"]["verify.impl_code_review"], "project")

    def test_illegal_value_rejected_and_not_persisted(self):
        """非 bool 值（如 "yes" / 1 / 空串）拒绝保存，配置文件不变。"""
        from core.dashboard.data import read_config, write_config

        for bad in ("yes", 1, 0, "", None if False else "x"):
            before = read_config(self.tmpdir)
            result = write_config(self.tmpdir, {"verify": {"impl_code_review": bad}})
            self.assertFalse(result["ok"], f"应当拒绝: {bad!r}")
            self.assertIn("impl_code_review", result["error"])
            after = read_config(self.tmpdir)
            self.assertEqual(after["verify"], before["verify"])

    def test_default_not_echoed_and_no_source(self):
        """缺省（未配置）时读回 MUST NOT 含 impl_code_review 键（防破坏既有
        严格相等断言 tests/test_system_settings_config.py:229）；来源标注
        随 _SOURCE_KEYS 登记存在，缺省为继承自用户级（user）。"""
        from core.dashboard.data import read_config

        echoed = read_config(self.tmpdir)
        self.assertNotIn("impl_code_review", echoed["verify"])
        # _SOURCE_KEYS 登记后 sources 键存在，缺省为 user（继承用户级）
        self.assertEqual(echoed["sources"]["verify.impl_code_review"], "user")

    def test_strict_bool_readback(self):
        """读侧严格 bool：配置文件中该键为 1 / "yes" 等非 bool 时不回显。"""
        from core.dashboard.data import read_config

        self._write_raw({"verify": {"impl_code_review": 1,
                                    "static_scope": "main",
                                    "deps_mode": "hardlink"}})
        echoed = read_config(self.tmpdir)
        self.assertNotIn("impl_code_review", echoed["verify"])

    def test_config_loader_reader_reads_merged(self):
        """ConfigLoader.get_impl_code_review_enabled 读取合并后的 verify 节。"""
        from core.config import ConfigLoader

        self.assertTrue(
            ConfigLoader.get_impl_code_review_enabled(
                {"verify": {"impl_code_review": True}}))
        self.assertFalse(
            ConfigLoader.get_impl_code_review_enabled(
                {"verify": {"impl_code_review": False}}))
        self.assertFalse(ConfigLoader.get_impl_code_review_enabled({}))
        self.assertFalse(ConfigLoader.get_impl_code_review_enabled(
            {"verify": {"static_scope": "main"}}))
        self.assertFalse(ConfigLoader.get_impl_code_review_enabled(
            {"verify": {"impl_code_review": 1}}))

    def test_effective_config_echoes(self):
        """read_effective_config 在项目级显式配置时同样回显该键。"""
        from core.dashboard.data import read_effective_config, write_config

        write_config(self.tmpdir, {"verify": {"impl_code_review": True}})
        eff = read_effective_config(self.tmpdir)
        self.assertTrue(eff["verify"]["impl_code_review"])


if __name__ == "__main__":
    unittest.main()
