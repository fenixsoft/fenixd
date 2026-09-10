"""
screenshot_evidence_labeling 单测（spec: screenshot-evidence-labeling）

测试截图健全性算法标签的四种核心 Scenario：
  1. 纯白（纯色）截图 → blank_screenshot: true
  2. 正常内容截图 → 无标签（向后兼容：缺标签=正常）
  3. 低对比度截图 → low_contrast: true
  4. 判定自身异常 → 返回空 dict，不抛出，不阻断主流程
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image


class TestClassifyScreenshotBlank(unittest.TestCase):
    """Scenario: 纯白（或纯色）截图产出 blank_screenshot 标签。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.blank_img = self.tmpdir / "blank_white.png"
        # 纯白图：255×255 RGB = 全白像素
        img = Image.new("RGB", (255, 255), (255, 255, 255))
        img.save(str(self.blank_img))

        self.pure_black_img = self.tmpdir / "blank_black.png"
        img = Image.new("RGB", (100, 100), (0, 0, 0))
        img.save(str(self.pure_black_img))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_blank_white_output_has_blank_screenshot_label(self):
        from core.verify_engine.screenshot_lab import classify_screenshot
        result = classify_screenshot(str(self.blank_img))
        self.assertTrue(result.get("blank_screenshot"))
        self.assertIn("pixel_std", result)
        self.assertIn("dominant_color_pct", result)
        self.assertIn("width", result)
        self.assertIn("height", result)
        self.assertLess(result["pixel_std"], 0.012,
                        "像素 std 应低于纯色阈值")
        self.assertGreater(result["dominant_color_pct"], 0.99,
                           "主色占比应 >99%")

    def test_blank_black_output_has_blank_screenshot_label(self):
        from core.verify_engine.screenshot_lab import classify_screenshot
        result = classify_screenshot(str(self.pure_black_img))
        self.assertTrue(result.get("blank_screenshot"))
        self.assertLess(result["pixel_std"], 0.012)

    def test_width_height_match_input(self):
        from core.verify_engine.screenshot_lab import classify_screenshot
        result = classify_screenshot(str(self.blank_img))
        self.assertEqual(result["width"], 255)
        self.assertEqual(result["height"], 255)


class TestClassifyScreenshotNormal(unittest.TestCase):
    """Scenario: 正常截图不产生标签。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.normal_img = self.tmpdir / "normal.png"
        # 正常图：有丰富颜色分布
        rng = np.random.default_rng(42)
        arr = rng.integers(0, 256, size=(300, 400, 3), dtype=np.uint8)
        Image.fromarray(arr).save(str(self.normal_img))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_normal_screenshot_no_labels(self):
        from core.verify_engine.screenshot_lab import classify_screenshot
        result = classify_screenshot(str(self.normal_img))
        self.assertFalse(result.get("blank_screenshot", False))
        self.assertFalse(result.get("low_contrast", False))
        self.assertIn("pixel_std", result)
        self.assertGreater(result["pixel_std"], 0.1,
                           "正常随机图的 std 应远高于纯色阈值")


class TestClassifyScreenshotLowContrast(unittest.TestCase):
    """Scenario: 低对比度截图产出 low_contrast 标签。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.low_contrast_img = self.tmpdir / "low_contrast.png"
        # 低对比度图：灰度在小范围内波动，std 在 0.0118~0.08 之间
        rng = np.random.default_rng(7)
        base = np.full((300, 400, 3), 180, dtype=np.uint8)
        noise = rng.integers(-5, 6, size=(300, 400, 3), dtype=np.int16)
        arr = np.clip(base.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        Image.fromarray(arr).save(str(self.low_contrast_img))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_low_contrast_has_label(self):
        from core.verify_engine.screenshot_lab import classify_screenshot
        result = classify_screenshot(str(self.low_contrast_img))
        # 应不是 blank（std > blank_std_threshold）
        self.assertFalse(result.get("blank_screenshot", False),
                         "低对比度不应误判为 blank")
        # 应是 low_contrast
        self.assertTrue(result.get("low_contrast"),
                        f"pixel_std={result.get('pixel_std')}，应在 low_contrast 范围")


class TestClassifyScreenshotExceptionSafety(unittest.TestCase):
    """Scenario: 判定失败不阻断截图主流程。"""

    def test_nonexistent_file_returns_empty_dict(self):
        from core.verify_engine.screenshot_lab import classify_screenshot
        # 不存在的文件 → 异常被捕获，返回空 dict
        result = classify_screenshot("/nonexistent/path/void.png")
        self.assertEqual(result, {})

    def test_invalid_image_returns_empty_dict(self):
        """损坏/非图像文件 → 异常被捕获，返回空 dict。"""
        from core.verify_engine.screenshot_lab import classify_screenshot
        self.tmpdir = Path(tempfile.mkdtemp())
        try:
            bad = self.tmpdir / "bad.txt"
            bad.write_text("not an image", encoding="utf-8")
            result = classify_screenshot(str(bad))
            self.assertEqual(result, {})
        finally:
            shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_exception_does_not_raise(self):
        """异常绝不向上抛出（B1 规约：截图主流程不受健全性判定影响）。"""
        from core.verify_engine.screenshot_lab import classify_screenshot
        # 不应抛出
        result = classify_screenshot("/no/valid/path")
        self.assertIsInstance(result, dict)


if __name__ == "__main__":
    unittest.main()
