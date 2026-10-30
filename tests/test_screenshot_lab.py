"""
screenshot_evidence_labeling 单测（spec: screenshot-evidence-labeling）

测试截图健全性算法标签的四种核心 Scenario：
  1. 纯白（纯色）截图 → blank_screenshot: true
  2. 正常内容截图 → 无标签（向后兼容：缺标签=正常）
  3. 低对比度截图 → low_contrast: true
  4. 判定自身异常 → 返回空 dict，不抛出，不阻断主流程

场景感知阈值（evo-visual-low-contrast-gate R1）：
  5. 声明性场景名（含 low-contrast 保留标记）阈值放宽生效
  6. 普通场景与无场景上下文缺省阈值不变
  7. 两调用侧（visual_diff 污染门 / browser.screenshot 标注路径）按场景传参
"""

import asyncio
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
from PIL import Image


def _write_screenshot(path: Path, pixels):
    """写一个合成 PNG 到 path（让 classify_screenshot 可读）。"""
    Image.fromarray(pixels.astype(np.uint8), "RGB").save(str(path))


def _make_page_screenshot(pixels):
    """返回一个 AsyncMock，对 page.screenshot 写入合成 PNG。"""
    def fake_screenshot(path, full_page=False):
        _write_screenshot(Path(path), pixels)
    return AsyncMock(side_effect=fake_screenshot)


def _near_threshold_pixels():
    """合成 pixel_std 落在 (0.08, 0.095) 窗口的画面。

    灰阶 ±38 均匀噪声（77 档离散均匀分布 std≈22.23）→ 跨通道
    pixel_std ≈ 0.087：缺省 0.08 上限判 low_contrast，放宽 0.095
    上限不判——正是历史误判家族（实测天然 std 0.063-0.0941）的
    贴阈值形态。
    """
    rng = np.random.default_rng(11)
    base = np.full((300, 400, 3), 180, dtype=np.uint8)
    noise = rng.integers(-38, 39, size=(300, 400, 3), dtype=np.int16)
    return np.clip(base.astype(np.int16) + noise, 0, 255).astype(np.uint8)


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


class TestScenarioAwareLowContrastUpper(unittest.TestCase):
    """Scenario: 场景感知阈值放宽（evo-visual-low-contrast-gate R1）。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.near_img = self.tmpdir / "near_threshold.png"
        pixels = _near_threshold_pixels()
        Image.fromarray(pixels).save(str(self.near_img))
        from core.verify_engine.screenshot_lab import classify_screenshot
        # 量化键恒在（无论标签判定结果），用于前置守卫
        self.pixel_std = classify_screenshot(str(self.near_img))["pixel_std"]

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_pixel_std_in_relaxed_window(self):
        """前置守卫：测试图 std 落在缺省 0.08 与放宽 0.095 之间的贴阈值窗口。"""
        self.assertGreaterEqual(self.pixel_std, 0.08)
        self.assertLess(self.pixel_std, 0.095)

    def test_default_threshold_not_label_near_band(self):
        """缺省（无场景上下文）0.08 上限：std 在 [0.08, 0.095) 的画面不判
        low_contrast（低对比带为 [0, 0.08)），显式传缺省常量行为一致。"""
        from core.verify_engine.screenshot_lab import (
            LOW_CONTRAST_STD_UPPER,
            classify_screenshot,
        )
        result = classify_screenshot(str(self.near_img))
        self.assertNotIn("low_contrast", result,
                         "缺省 0.08 上限下 std≥0.08 画面不应判 low_contrast")
        result2 = classify_screenshot(
            str(self.near_img), low_contrast_upper=LOW_CONTRAST_STD_UPPER
        )
        self.assertNotIn("low_contrast", result2, "显式缺省上限行为一致")

    def test_relaxed_upper_widens_low_contrast_band(self):
        """放宽上限生效：同一画面在放宽 0.095 上限下判 low_contrast
        （低对比带扩至 [0, 0.095)）——按 SPEC 字面机制断言参数真实生效。"""
        from core.verify_engine.screenshot_lab import (
            LOW_CONTRAST_STD_UPPER_RELAXED,
            classify_screenshot,
        )
        result = classify_screenshot(
            str(self.near_img), low_contrast_upper=LOW_CONTRAST_STD_UPPER_RELAXED
        )
        self.assertIn("low_contrast", result,
                      "放宽上限下 std<0.095 画面判 low_contrast（带扩宽生效）")
        self.assertNotIn("blank_screenshot", result,
                         "放宽只影响 low_contrast 档，不产生 blank 标签")
        self.assertIn("pixel_std", result)

    def test_below_both_thresholds_still_labeled(self):
        """深度低对比（std 远低于两档阈值）在缺省与放宽上限下均判
        low_contrast——放宽不收窄既有判定带。"""
        from core.verify_engine.screenshot_lab import (
            LOW_CONTRAST_STD_UPPER_RELAXED,
            classify_screenshot,
        )
        rng = np.random.default_rng(7)
        base = np.full((300, 400, 3), 180, dtype=np.uint8)
        noise = rng.integers(-5, 6, size=(300, 400, 3), dtype=np.int16)
        arr = np.clip(base.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        deep_img = self.tmpdir / "deep_low_contrast.png"
        Image.fromarray(arr).save(str(deep_img))
        default = classify_screenshot(str(deep_img))
        relaxed = classify_screenshot(
            str(deep_img), low_contrast_upper=LOW_CONTRAST_STD_UPPER_RELAXED
        )
        self.assertTrue(default.get("low_contrast"))
        self.assertTrue(relaxed.get("low_contrast"))

    def test_true_blank_still_blank_under_relaxed(self):
        """真空白（std≈0）在放宽上限下仍是 blank_screenshot（不受放宽影响）。"""
        from core.verify_engine.screenshot_lab import (
            LOW_CONTRAST_STD_UPPER_RELAXED,
            classify_screenshot,
        )
        blank = self.tmpdir / "blank.png"
        Image.fromarray(np.full((100, 100, 3), 255, dtype=np.uint8)).save(str(blank))
        result = classify_screenshot(
            str(blank), low_contrast_upper=LOW_CONTRAST_STD_UPPER_RELAXED
        )
        self.assertTrue(result.get("blank_screenshot"))


class TestScenarioAwareHelper(unittest.TestCase):
    """Scenario: 场景名匹配助手（声明性子串，大小写不敏感）。"""

    def test_declared_names_use_relaxed_upper(self):
        from core.verify_engine.screenshot_lab import (
            LOW_CONTRAST_STD_UPPER_RELAXED,
            is_low_contrast_declared_scenario,
            low_contrast_upper_for_scenario,
        )
        declared = [
            "bigscreen-empty-state",      # empty
            "zero-state",                 # zero-state
            "Zero_State_Placeholder",     # placeholder + 大小写不敏感
            "chart-low-contrast",         # low-contrast 保留标记
            "sc_low_contrast",            # low_contrast 下划线形态
            "EMPTY-STATE",                # 大写
            "table-with-empty-rows",      # 子串命中即可
        ]
        for name in declared:
            self.assertTrue(is_low_contrast_declared_scenario(name))
            self.assertEqual(
                low_contrast_upper_for_scenario(name),
                LOW_CONTRAST_STD_UPPER_RELAXED,
                f"声明性场景名 {name!r} 应用放宽上限",
            )

    def test_undeclared_names_keep_default_upper(self):
        from core.verify_engine.screenshot_lab import (
            LOW_CONTRAST_STD_UPPER,
            is_low_contrast_declared_scenario,
            low_contrast_upper_for_scenario,
        )
        undeclared = [
            "bigscreen-view", "scenario-1", "login-page", "dashboard-main",
            "", "placeholder_check_placeholder".replace("placeholder", "view"),
            None, 123,      # 非 str 上下文按未声明回退缺省
        ]
        for name in undeclared:
            self.assertFalse(
                is_low_contrast_declared_scenario(name),
                f"{name!r} 不应命中声明性子串",
            )
            self.assertEqual(
                low_contrast_upper_for_scenario(name),
                LOW_CONTRAST_STD_UPPER,
                f"非声明场景名 {name!r} 应维持缺省上限",
            )

    def test_zero_state_underscore_not_declared(self):
        """SPEC 字面子串清单只有 zero-state（连字符）与 low_contrast（下划线）：
        zero_state 不在清单内，按缺省处理（字面合规优先）。"""
        from core.verify_engine.screenshot_lab import (
            LOW_CONTRAST_STD_UPPER,
            low_contrast_upper_for_scenario,
        )
        self.assertEqual(low_contrast_upper_for_scenario("zero_state"),
                         LOW_CONTRAST_STD_UPPER)


class TestScenarioAwareCallSites(unittest.TestCase):
    """Scenario: 两调用侧（污染门/标注路径）按场景传参（R1 全覆盖）。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.near_pixels = _near_threshold_pixels()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_pollution_gate_applies_relaxed_upper_to_declared_scenario(self):
        """visual_diff 污染门：声明性场景 id 按场景传放宽上限——std 在
        [0.08, 0.095) 的画面在放宽上限下被判 low_contrast（标签进入拒绝
        结果），而同一画面在缺省 0.08 上限下无标签（见下一条用例），
        以此证明门侧传参随场景切换。"""
        from core.verify_engine.visual_diff import VisualDiffer
        differ = VisualDiffer("spec_x", self.tmpdir)
        page = MagicMock()
        page.screenshot = _make_page_screenshot(self.near_pixels)
        result = asyncio.run(
            differ.compare(page, "bl", "bigscreen-empty-state")
        )
        self.assertEqual(result[0]["status"], "baseline_rejected")
        self.assertTrue(result[0]["screenshot_labels"].get("low_contrast"),
                        "声明性场景走放宽上限（std<0.095 判低对比）")

    def test_pollution_gate_default_threshold_unchanged(self):
        """visual_diff 污染门：普通场景 id 维持缺省 0.08——同一贴阈值画面
        （std≥0.08）不判低对比、照常固化，普通场景行为不变。"""
        from core.verify_engine.visual_diff import VisualDiffer
        differ = VisualDiffer("spec_x", self.tmpdir)
        page = MagicMock()
        page.screenshot = _make_page_screenshot(self.near_pixels)
        result = asyncio.run(differ.compare(page, "bl", "bigscreen-view"))
        self.assertEqual(result[0]["status"], "baseline_created",
                         "普通场景缺省 0.08 行为不变（std≥0.08 无标签）")
        bl = differ.base_dir / "baselines" / "bl.png"
        self.assertTrue(bl.exists())

    def test_screenshot_labeling_applies_scenario_upper(self):
        """browser.screenshot 标注路径：声明性场景名产 low_contrast 标签
        （放宽上限生效），普通场景名同画面无标签（缺省 0.08 不变）。"""
        from core.verify_engine.browser import BrowserManager
        mgr = BrowserManager(project_root=self.tmpdir)
        page = MagicMock()
        page.screenshot = _make_page_screenshot(self.near_pixels)
        out_dir = self.tmpdir / "shots"
        out = asyncio.run(mgr.screenshot(page, "sc-empty-state", out_dir))
        self.assertIn("labels", out)
        self.assertTrue(
            out["labels"].get("low_contrast"),
            f"声明性场景标注侧走放宽上限（pixel_std={out['labels'].get('pixel_std')}）",
        )
        # 同一画面、普通场景名 → 缺省 0.08 不产标签（缺标签=正常态契约不变）
        out2 = asyncio.run(mgr.screenshot(page, "sc-view", out_dir))
        self.assertNotIn("low_contrast", out2["labels"],
                         "普通场景标注侧缺省 0.08 行为不变")


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
