"""add-knowledge-atlas + add-knowledge-atlas-maintenance：knowledge 配置段解析单测。

合并后 ``knowledge`` 段三键共存（enabled 蒸馏总开关 + audit_enabled/graph_enabled
维护车道），两组解析器各归其主：

- ConfigLoader.get_knowledge_config（add-knowledge-atlas task 1.1）：
  enabled 缺省 true / 显式 true / 显式 false / 非法值回退 true 并告警；
  _validate 软校验：knowledge.enabled 非法值不阻塞加载（与 archive.auto_threshold
  同型——记 ERROR 回落缺省，不 raise）；
  config.template.yaml 登记 knowledge 段（模板与解析不脱钩）；
  设置页受管键登记（config_admin 回显 / 合并 / 校验三处 + 来源清单）。
- ConfigLoader.get_knowledge_lane_config（add-knowledge-atlas-maintenance 1.1）：
  audit_enabled / graph_enabled 缺省 True / 合法 bool 透传 / 非法值回退 True 并
  WARNING 告警 / 整段非 dict 按空段降级；模板登记两键带注释。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import ConfigLoader

REPO_ROOT = Path(__file__).resolve().parents[1]


def _valid_cfg() -> dict:
    """最小合法配置底座（与 test_config._valid_cfg 同构）。"""
    return {
        "project": {"name": "test", "type": "web"},
        "schedule": {"poll_interval_minutes": 30},
        "agents": {"max_concurrent": 2, "max_retries": 3, "max_turns": 50},
        "worktree": {
            "base_dir": ".claude/worktrees",
            "implement_branch_prefix": "fenix",
            "verify_branch_prefix": "fenix/verify",
        },
        "gates": {"require_push_approval": True},
        "commands": {"test": "", "build": "", "start": ""},
        "logging": {"dir": ".fenix/logs", "level": "INFO"},
    }


class TestGetKnowledgeConfig(unittest.TestCase):
    def test_missing_section_defaults_true(self):
        self.assertEqual(
            ConfigLoader.get_knowledge_config({}),
            {"enabled": True},
        )

    def test_section_without_enabled_defaults_true(self):
        self.assertEqual(
            ConfigLoader.get_knowledge_config({"knowledge": {}}),
            {"enabled": True},
        )

    def test_explicit_true(self):
        self.assertEqual(
            ConfigLoader.get_knowledge_config({"knowledge": {"enabled": True}}),
            {"enabled": True},
        )

    def test_explicit_false(self):
        self.assertEqual(
            ConfigLoader.get_knowledge_config({"knowledge": {"enabled": False}}),
            {"enabled": False},
        )

    def test_invalid_value_falls_back_true_with_warning(self):
        with self.assertLogs("fenixd.config", level="ERROR") as ctx:
            got = ConfigLoader.get_knowledge_config({"knowledge": {"enabled": "yes"}})
        self.assertEqual(got, {"enabled": True})
        joined = "\n".join(ctx.output)
        self.assertIn("knowledge.enabled", joined)


class TestValidateKnowledgeSoft(unittest.TestCase):
    def _assert_loads(self, cfg):
        # load 严格路径：非法 knowledge.enabled 不 raise（软校验）
        return ConfigLoader._validate(cfg, require_project=True)

    def test_invalid_enabled_does_not_block_load(self):
        cfg = _valid_cfg()
        cfg["knowledge"] = {"enabled": "on"}
        try:
            self._assert_loads(cfg)
        except ValueError as e:
            self.fail(f"knowledge.enabled 非法值不应阻塞加载: {e}")

    def test_bool_enabled_passes(self):
        cfg = _valid_cfg()
        cfg["knowledge"] = {"enabled": False}
        self._assert_loads(cfg)

    def test_non_dict_section_degrades(self):
        cfg = _valid_cfg()
        cfg["knowledge"] = 3
        try:
            self._assert_loads(cfg)
        except ValueError as e:
            self.fail(f"knowledge 段非 dict 应按空段降级而非 raise: {e}")


class TestKnowledgeTemplateRegistered(unittest.TestCase):
    def test_template_yaml_has_knowledge_section(self):
        tpl = REPO_ROOT / ".fenix" / "config.template.yaml"
        try:
            import yaml

            data = yaml.safe_load(tpl.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            self.fail(f"config.template.yaml 解析失败: {e}")
        self.assertIsInstance(data, dict)
        self.assertIn("knowledge", data)
        # 合并后单节三键共存（重复顶层 knowledge: 会被 YAML 后节覆盖静默丢键）
        self.assertIs(data["knowledge"]["enabled"], True)
        self.assertIs(data["knowledge"]["audit_enabled"], True)
        self.assertIs(data["knowledge"]["graph_enabled"], True)


class TestKnowledgeLaneConfig(unittest.TestCase):
    """knowledge.audit_enabled / knowledge.graph_enabled 解析（maintenance 1.1）。"""

    def test_missing_section_defaults_true(self):
        cfg = ConfigLoader.get_knowledge_lane_config({})
        self.assertEqual(cfg, {"audit_enabled": True, "graph_enabled": True})

    def test_partial_keys_fill_default(self):
        cfg = ConfigLoader.get_knowledge_lane_config(
            {"knowledge": {"audit_enabled": False}}
        )
        self.assertEqual(cfg, {"audit_enabled": False, "graph_enabled": True})

    def test_valid_bools_passthrough(self):
        cfg = ConfigLoader.get_knowledge_lane_config(
            {"knowledge": {"audit_enabled": False, "graph_enabled": False}}
        )
        self.assertEqual(cfg, {"audit_enabled": False, "graph_enabled": False})

    def test_invalid_values_fallback_true_with_warning(self):
        with self.assertLogs("fenixd.config", level="WARNING") as captured:
            cfg = ConfigLoader.get_knowledge_lane_config(
                {"knowledge": {"audit_enabled": "yes", "graph_enabled": 1}}
            )
        self.assertEqual(cfg, {"audit_enabled": True, "graph_enabled": True})
        joined = "\n".join(captured.output)
        self.assertIn("knowledge.audit_enabled", joined)
        self.assertIn("knowledge.graph_enabled", joined)

    def test_non_dict_section_degrades_to_defaults(self):
        cfg = ConfigLoader.get_knowledge_lane_config({"knowledge": ["audit_enabled"]})
        self.assertEqual(cfg, {"audit_enabled": True, "graph_enabled": True})

    def test_none_value_fallback_default(self):
        with self.assertLogs("fenixd.config", level="WARNING"):
            cfg = ConfigLoader.get_knowledge_lane_config(
                {"knowledge": {"audit_enabled": None}}
            )
        self.assertEqual(cfg, {"audit_enabled": True, "graph_enabled": True})

    def test_template_registers_both_keys(self):
        text = (REPO_ROOT / ".fenix" / "config.template.yaml").read_text(
            encoding="utf-8"
        )
        self.assertIn("knowledge:", text)
        self.assertIn("audit_enabled: true", text)
        self.assertIn("graph_enabled: true", text)
        # 模板行必须带注释语境（task 1.1：登记带注释模板行）
        knowledge_idx = text.index("knowledge:")
        self.assertIn("audit 体检", text[knowledge_idx:knowledge_idx + 400])


class TestKnowledgeManagedKeys(unittest.TestCase):
    """设置页受管键三处登记（读回显 / 深合并 / 写校验）。

    合并后 knowledge 段三键（enabled + audit_enabled + graph_enabled）同段回显、
    同型合并、同口径校验——任何一键缺分支都会被静默丢弃（历史同坑）。
    """

    def test_default_echo_view_has_knowledge(self):
        from core.dashboard.data import config_admin

        view = config_admin._default_echo_view("user")
        self.assertEqual(
            view["knowledge"],
            {"enabled": True, "audit_enabled": True, "graph_enabled": True},
        )

    def test_read_config_echoes_enabled_from_raw(self):
        import tempfile

        from core.dashboard.data import config_admin

        with tempfile.TemporaryDirectory() as td:
            cfg_dir = Path(td) / ".fenix"
            cfg_dir.mkdir()
            (cfg_dir / "config.yaml").write_text(
                "knowledge:\n  enabled: false\n", encoding="utf-8"
            )
            view = config_admin.read_config(td, scope="project")
        self.assertEqual(
            view["knowledge"],
            {"enabled": False, "audit_enabled": True, "graph_enabled": True},
        )

    def test_deep_merge_applies_enabled(self):
        from core.dashboard.data.config_admin import _deep_merge_managed

        merged = _deep_merge_managed({"knowledge": {"enabled": True}}, {"knowledge": {"enabled": False}})
        self.assertEqual(merged["knowledge"]["enabled"], False)
        # 未提供 knowledge patch 时原段保留
        merged2 = _deep_merge_managed({"knowledge": {"enabled": False}}, {})
        self.assertEqual(merged2["knowledge"]["enabled"], False)

    def test_deep_merge_applies_lane_keys(self):
        from core.dashboard.data.config_admin import _deep_merge_managed

        merged = _deep_merge_managed(
            {"knowledge": {"audit_enabled": True, "graph_enabled": True}},
            {"knowledge": {"audit_enabled": False}},
        )
        self.assertEqual(merged["knowledge"]["audit_enabled"], False)
        self.assertEqual(merged["knowledge"]["graph_enabled"], True)

    def test_write_config_rejects_non_bool_enabled(self):
        import tempfile

        from core.dashboard.data import config_admin

        with tempfile.TemporaryDirectory() as td:
            result = config_admin.write_config(td, {"knowledge": {"enabled": "yes"}}, scope="project")
        self.assertFalse(result["ok"])
        self.assertIn("boolean", result["error"])

    def test_write_config_rejects_non_bool_lane_key(self):
        import tempfile

        from core.dashboard.data import config_admin

        with tempfile.TemporaryDirectory() as td:
            result = config_admin.write_config(
                td, {"knowledge": {"audit_enabled": "yes"}}, scope="project"
            )
        self.assertFalse(result["ok"])
        self.assertIn("boolean", result["error"])
        self.assertIn("audit_enabled", result["error"])

    def test_write_config_accepts_bool_enabled(self):
        import tempfile

        import yaml

        from core.dashboard.data import config_admin

        with tempfile.TemporaryDirectory() as td:
            (Path(td) / ".fenix").mkdir(parents=True)
            result = config_admin.write_config(td, {"knowledge": {"enabled": False}}, scope="project")
            self.assertTrue(result["ok"])
            on_disk = yaml.safe_load((Path(td) / ".fenix" / "config.yaml").read_text(encoding="utf-8"))
        self.assertEqual(on_disk["knowledge"]["enabled"], False)

    def test_write_config_accepts_bool_lane_keys(self):
        import tempfile

        import yaml

        from core.dashboard.data import config_admin

        with tempfile.TemporaryDirectory() as td:
            (Path(td) / ".fenix").mkdir(parents=True)
            result = config_admin.write_config(
                td,
                {"knowledge": {"audit_enabled": False, "graph_enabled": False}},
                scope="project",
            )
            self.assertTrue(result["ok"])
            on_disk = yaml.safe_load(
                (Path(td) / ".fenix" / "config.yaml").read_text(encoding="utf-8")
            )
        self.assertEqual(on_disk["knowledge"]["audit_enabled"], False)
        self.assertEqual(on_disk["knowledge"]["graph_enabled"], False)

    def test_knowledge_keys_in_source_keys(self):
        from core.dashboard.data.config_admin import _SOURCE_KEYS

        self.assertIn("knowledge.enabled", _SOURCE_KEYS)
        self.assertIn("knowledge.audit_enabled", _SOURCE_KEYS)
        self.assertIn("knowledge.graph_enabled", _SOURCE_KEYS)


if __name__ == "__main__":
    unittest.main()
