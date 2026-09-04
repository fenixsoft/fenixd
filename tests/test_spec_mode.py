"""add-fast-track-mode task 1.2：.openspec.yaml mode 读取器单测。

覆盖：
1. 显式 fast-track / full 读取
2. 缺省 full：文件缺失 / 无 mode 字段 / 存量 spec 零迁移
3. 非法值回落 full（fail-closed, 不抛异常）
4. 解析失败（损坏 YAML / 非对象顶层）回落 full
"""

import tempfile
import unittest
from pathlib import Path

from core.openspec_mode import (
    DEFAULT_SPEC_MODE,
    read_spec_mode,
    is_fast_track,
)


def _make_spec(root: Path, name: str, yaml_text: str) -> Path:
    d = root / "openspec" / "changes" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / ".openspec.yaml").write_text(yaml_text, encoding="utf-8")
    return d


class TestReadSpecMode(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_reads_fast_track(self):
        _make_spec(self.root, "a", "schema: spec-driven\ncreated: 2026-09-02\nmode: fast-track\n")
        self.assertEqual(read_spec_mode(self.root, "a"), "fast-track")
        self.assertTrue(is_fast_track(self.root, "a"))

    def test_reads_full(self):
        _make_spec(self.root, "b", "schema: spec-driven\ncreated: 2026-09-02\nmode: full\n")
        self.assertEqual(read_spec_mode(self.root, "b"), "full")
        self.assertFalse(is_fast_track(self.root, "b"))

    def test_missing_file_default_full(self):
        self.assertEqual(read_spec_mode(self.root, "ghost"), DEFAULT_SPEC_MODE)
        self.assertFalse(is_fast_track(self.root, "ghost"))

    def test_missing_mode_field_default_full(self):
        # 存量 spec：无 mode 字段 → 缺省 full（零迁移）
        _make_spec(self.root, "c", "schema: spec-driven\ncreated: 2026-09-02\n")
        self.assertEqual(read_spec_mode(self.root, "c"), DEFAULT_SPEC_MODE)

    def test_invalid_mode_default_full(self):
        # 值非法（大小写/拼写/类型错误）→ full
        for bad in ("FAST-TRACK", "fast", "2", "[]", "null"):
            _make_spec(self.root, "d", f"schema: spec-driven\nmode: {bad}\n")
            self.assertEqual(read_spec_mode(self.root, "d"), DEFAULT_SPEC_MODE)

    def test_corrupt_yaml_default_full(self):
        d = self.root / "openspec" / "changes" / "e"
        d.mkdir(parents=True, exist_ok=True)
        (d / ".openspec.yaml").write_text("schema: [unclosed", encoding="utf-8")
        self.assertEqual(read_spec_mode(self.root, "e"), DEFAULT_SPEC_MODE)

    def test_non_object_top_level_default_full(self):
        _make_spec(self.root, "f", "- just\n- a\n- list\n")
        self.assertEqual(read_spec_mode(self.root, "f"), DEFAULT_SPEC_MODE)


if __name__ == "__main__":
    unittest.main()