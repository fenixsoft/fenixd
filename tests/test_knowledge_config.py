"""knowledge.audit_enabled / knowledge.graph_enabled 解析单测（任务 1.1）。

覆盖：
- 缺省：段缺失 / 键缺失 → 两键默认 True；
- 合法 bool：显式 false / true 原样透传；
- 非法值：非 bool（字符串/整数/None）回退默认 True 并 WARNING 告警；
- 整段非 dict：按空段降级，两键取默认 True 不抛异常；
- 模板登记：config.template.yaml 的 knowledge 段带两行注释模板。
"""

import unittest
from pathlib import Path

from core.config import ConfigLoader

REPO_ROOT = Path(__file__).resolve().parents[1]


class TestKnowledgeConfig(unittest.TestCase):
    def test_missing_section_defaults_true(self):
        cfg = ConfigLoader.get_knowledge_config({})
        self.assertEqual(cfg, {"audit_enabled": True, "graph_enabled": True})

    def test_partial_keys_fill_default(self):
        cfg = ConfigLoader.get_knowledge_config({"knowledge": {"audit_enabled": False}})
        self.assertEqual(cfg, {"audit_enabled": False, "graph_enabled": True})

    def test_valid_bools_passthrough(self):
        cfg = ConfigLoader.get_knowledge_config(
            {"knowledge": {"audit_enabled": False, "graph_enabled": False}}
        )
        self.assertEqual(cfg, {"audit_enabled": False, "graph_enabled": False})

    def test_invalid_values_fallback_true_with_warning(self):
        with self.assertLogs("fenixd.config", level="WARNING") as captured:
            cfg = ConfigLoader.get_knowledge_config(
                {"knowledge": {"audit_enabled": "yes", "graph_enabled": 1}}
            )
        self.assertEqual(cfg, {"audit_enabled": True, "graph_enabled": True})
        joined = "\n".join(captured.output)
        self.assertIn("knowledge.audit_enabled", joined)
        self.assertIn("knowledge.graph_enabled", joined)

    def test_non_dict_section_degrades_to_defaults(self):
        cfg = ConfigLoader.get_knowledge_config({"knowledge": ["audit_enabled"]})
        self.assertEqual(cfg, {"audit_enabled": True, "graph_enabled": True})

    def test_none_value_fallback_default(self):
        with self.assertLogs("fenixd.config", level="WARNING"):
            cfg = ConfigLoader.get_knowledge_config(
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
        # 模板行必须带注释语境（任务 1.1：登记带注释模板行）
        knowledge_idx = text.index("knowledge:")
        self.assertIn("audit 体检", text[knowledge_idx:knowledge_idx + 400])


if __name__ == "__main__":
    unittest.main()
