"""runs.keep 配置项取消后的 config_admin 契约测试（fix-run-cleanup-attach-spec-archive 3.2）。

覆盖：
- 配置补丁含 runs 键被忽略：不落盘、不回显
- 其余受管键正常应用与回显
- 回显结果不含 runs 键（存量死键也不透传）
- 非 dict 值的 runs 补丁同样被忽略，不报 400
- 存量死键 runs.keep 非法值（如 keep: true）不阻塞其他受管键写入
"""
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml


class TestRunsKeyRemoved(unittest.TestCase):
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

    def _read_raw(self) -> dict:
        with self.config_path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def test_patch_with_runs_key_ignored(self):
        """runs 补丁被忽略：不落盘、不回显，同补丁其余受管键正常应用。"""
        from core.dashboard.data import read_config, write_config

        result = write_config(
            self.tmpdir,
            {
                "runs": {"keep": 120},
                "gates": {"approve_mode": "auto"},
            },
        )
        self.assertTrue(result["ok"], result.get("error"))
        raw = self._read_raw()
        self.assertNotIn("runs", raw, "runs 键不得落盘")
        self.assertEqual(raw["gates"]["approve_mode"], "auto")
        echoed = read_config(self.tmpdir)
        self.assertNotIn("runs", echoed, "runs 键不得回显")

    def test_echo_omits_existing_runs_dead_key(self):
        """存量文件里的 runs 段回显时不透传（读侧无消费点）。"""
        from core.dashboard.data import read_config

        self._write_raw({"runs": {"keep": 30}})
        echoed = read_config(self.tmpdir)
        self.assertNotIn("runs", echoed)

    def test_non_dict_runs_patch_not_rejected(self):
        """非 dict 值的 runs 补丁同样被忽略，不报 400（键已退出受管清单）。"""
        from core.dashboard.data import write_config

        for bad in ("garbage", 123, True, None):
            result = write_config(self.tmpdir, {"runs": bad})
            self.assertTrue(result["ok"], f"runs={bad!r} 不应被拒绝: {result.get('error')}")

    def test_legacy_invalid_keep_does_not_block_other_keys(self):
        """存量死键 runs.keep 非法值（keep: true）不阻塞其他受管键写入。"""
        from core.dashboard.data import read_config, write_config

        self._write_raw({"runs": {"keep": True}})
        result = write_config(
            self.tmpdir,
            {
                "gates": {"approve_mode": "auto"},
                "verify": {"static_scope": "worktree"},
            },
        )
        self.assertTrue(result["ok"], f"存量死键不得阻塞写入: {result.get('error')}")
        raw = self._read_raw()
        self.assertEqual(raw["gates"]["approve_mode"], "auto")
        self.assertEqual(raw["verify"]["static_scope"], "worktree")
        self.assertEqual(raw["runs"]["keep"], True, "死键保持原样（无迁移要求）")
        echoed = read_config(self.tmpdir)
        self.assertNotIn("runs", echoed)

    def test_managed_keys_contract_anchor_excludes_runs(self):
        """_MANAGED_KEYS 契约锚点不含 runs（防回潮）。"""
        from core.dashboard.data.config_admin import _MANAGED_KEYS

        self.assertNotIn("runs", _MANAGED_KEYS)


if __name__ == "__main__":
    unittest.main()
