"""
视觉基线防污染单元测试（add-verdict-credibility-gate / spec: attribution-freshness-governance）

覆盖 tasks 4.1-4.3：
  - 白屏截图拒绝固化（baseline_rejected + screenshot_labels）
  - 正常截图照常固化（baseline_created）
  - baseline_rejected 在 visual_results 可追溯 → determine_scenario_status → warning
"""

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import numpy as np
from PIL import Image

from core.verify_engine.visual_diff import VisualDiffer
from core.verify_engine.runner import determine_scenario_status


def _write_screenshot(path: Path, pixels):
    """写一个合成 PNG 到 path（让 classify_screenshot 可读）。"""
    img = Image.fromarray(pixels.astype(np.uint8), "RGB")
    img.save(str(path))


def _make_page_screenshot(ckpt_dir: Path, pixels):
    """返回一个 AsyncMock，对 page.screenshot 写入合成 PNG。"""
    def fake_screenshot(path, full_page=False):
        _write_screenshot(Path(path), pixels)
    return AsyncMock(side_effect=fake_screenshot)


class TestVisualBaselineAntiPollution(unittest.TestCase):
    """Scenario: 白屏/低对比度不得固化为基线。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.spec_dir = self.tmpdir / "spec_x"
        self.differ = VisualDiffer("spec_x", self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_white_baseline_rejected(self):
        """白屏截图 → baseline_rejected + blank_screenshot 标签。"""
        white = np.full((100, 100, 3), 255, dtype=np.uint8)
        page = MagicMock()
        page.screenshot = _make_page_screenshot(self.tmpdir, white)
        result = asyncio.run(self.differ.compare(page, "baseline_v1", "sc1"))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["status"], "baseline_rejected")
        self.assertFalse(result[0]["pass"])
        self.assertIn("拒绝固化", result[0]["note"])
        labels = result[0].get("screenshot_labels", {})
        self.assertTrue(labels.get("blank_screenshot"),
                       "blank_screenshot 标签应在返回结果中")
        # 基线文件不应被创建
        bl = self.differ.base_dir / "baselines" / "baseline_v1.png"
        self.assertFalse(bl.exists(), "白屏截图基线文件不应被创建")

    def test_normal_baseline_created(self):
        """正常截图 → baseline_created，基线文件存在。"""
        rng = np.random.default_rng(42)
        normal = rng.integers(0, 256, size=(100, 100, 3), dtype=np.uint8)
        page = MagicMock()
        page.screenshot = _make_page_screenshot(self.tmpdir, normal)
        result = asyncio.run(self.differ.compare(page, "baseline_v1", "sc1"))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["status"], "baseline_created")
        self.assertTrue(result[0]["pass"])
        bl = self.differ.base_dir / "baselines" / "baseline_v1.png"
        self.assertTrue(bl.exists(), "正常截图基线文件应被创建")

    def test_baseline_rejected_next_round_normal_creates(self):
        """首次白屏被拒，下一轮正常截图可成功建立基线。"""
        # 第一轮：白屏
        white = np.full((100, 100, 3), 255, dtype=np.uint8)
        page = MagicMock()
        page.screenshot = _make_page_screenshot(self.tmpdir, white)
        result1 = asyncio.run(self.differ.compare(page, "bl", "s1"))
        self.assertEqual(result1[0]["status"], "baseline_rejected")
        # 第二轮：正常截图
        rng = np.random.default_rng(7)
        normal = rng.integers(0, 256, size=(100, 100, 3), dtype=np.uint8)
        page2 = MagicMock()
        page2.screenshot = _make_page_screenshot(self.tmpdir, normal)
        result2 = asyncio.run(self.differ.compare(page2, "bl", "s1"))
        self.assertEqual(result2[0]["status"], "baseline_created")


class TestDetermineScenarioStatusBaselineRejected(unittest.TestCase):
    """Scenario: baseline_rejected 在 determine_scenario_status 中映射 warning。"""

    def test_baseline_rejected_yields_warning(self):
        """baseline_rejected → warning（环境存疑，不产生像素比对结论）。"""
        step_results = [{"action": "navigate", "success": True}]
        assertion_results = [{"pass": True, "layer": 2}]
        visual_results = [{"status": "baseline_rejected", "pass": False}]
        status = determine_scenario_status(step_results, assertion_results,
                                           visual_results)
        self.assertEqual(status, "warning")

    def test_baseline_created_pass_not_warning(self):
        """baseline_created + pass 不应触发 warning。"""
        step_results = [{"action": "navigate", "success": True}]
        assertion_results = [{"pass": True, "layer": 2}]
        visual_results = [{"status": "baseline_created", "pass": True}]
        status = determine_scenario_status(step_results, assertion_results,
                                           visual_results)
        self.assertEqual(status, "pass")

    def test_diff_detected_yields_warning(self):
        """diff_detected → warning（既有一致性）。"""
        step_results = [{"action": "navigate", "success": True}]
        assertion_results = [{"pass": True, "layer": 2}]
        visual_results = [{"status": "diff_detected", "pass": False}]
        status = determine_scenario_status(step_results, assertion_results,
                                           visual_results)
        self.assertEqual(status, "warning")

    def test_empty_visual_results_pass(self):
        """无视觉结果 + 其他通过 → pass。"""
        status = determine_scenario_status(
            [{"action": "navigate", "success": True}],
            [{"pass": True, "layer": 2}],
            [],
        )
        self.assertEqual(status, "pass")


if __name__ == "__main__":
    unittest.main()
