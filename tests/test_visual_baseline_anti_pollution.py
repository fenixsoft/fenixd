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
from unittest.mock import AsyncMock, MagicMock, patch

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


def _make_page_screenshot_sequence(pixels_seq):
    """返回 (AsyncMock, 调用状态)：每次 page.screenshot 依序写 pixels_seq[i]，
    超出序列后复写最后一帧（模拟画面恒定）。"""
    state = {"call": 0}

    def fake_screenshot(path, full_page=False):
        idx = min(state["call"], len(pixels_seq) - 1)
        _write_screenshot(Path(path), pixels_seq[idx])
        state["call"] += 1

    return AsyncMock(side_effect=fake_screenshot), state


def _read_png(path: Path) -> np.ndarray:
    with Image.open(str(path)) as im:
        return np.array(im.convert("RGB"))


def _low_contrast_pixels():
    """合成深度低对比画面（std≈0.011 < 缺省 0.08，正常场景 id 必判低对比）。"""
    rng = np.random.default_rng(7)
    base = np.full((100, 100, 3), 180, dtype=np.uint8)
    noise = rng.integers(-5, 6, size=(100, 100, 3), dtype=np.int16)
    return np.clip(base.astype(np.int16) + noise, 0, 255).astype(np.uint8)


def _normal_pixels():
    """合成正常画面（std 远高于阈值，无任何健全性标签）。"""
    rng = np.random.default_rng(123)
    return rng.integers(0, 256, size=(100, 100, 3), dtype=np.uint8)


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


class TestGateConvergenceRecheck(unittest.TestCase):
    """门内收敛复核与证据落盘（evo-visual-low-contrast-gate R2/R3）。

    污染门命中先做一次延时重截复测：收敛（复测通过）先回写 current_path
    再按正常流程固化/放行；仍污染才 baseline_rejected（每场景每轮至多一次
    重截）；命中分支首截与复测件均落盘 .fenix/verify-evidence/<spec>/。
    """

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.differ = VisualDiffer("spec_x", self.tmpdir)
        self.evidence_dir = (
            self.tmpdir / ".fenix" / "verify-evidence" / "spec_x"
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _evidence_names(self):
        return sorted(p.name for p in self.evidence_dir.glob("*.png"))

    def test_recheck_converged_creates_baseline_from_retake_frame(self):
        """低对比首截 → 门内重截复测收敛 → 放行固化，基线内容=复测件。"""
        first = _low_contrast_pixels()
        retake = _normal_pixels()
        page = MagicMock()
        page.screenshot, state = _make_page_screenshot_sequence([first, retake])
        result = asyncio.run(self.differ.compare(page, "bl", "s1"))
        self.assertEqual(result[0]["status"], "baseline_created",
                         f"复测收敛应放行: {result[0]}")
        self.assertTrue(result[0]["pass"])
        # 回写断言：固化基线内容 = 复测件（非污染首图）
        baseline_path = self.differ.base_dir / "baselines" / "bl.png"
        self.assertTrue(baseline_path.exists())
        np.testing.assert_array_equal(
            _read_png(baseline_path), retake,
            "固化基线必须是回写后的复测件内容",
        )
        # 标准证据路径 current_path 同步回写为复测件
        current_path = self.differ.base_dir / "screenshots" / "s1_current.png"
        np.testing.assert_array_equal(_read_png(current_path), retake)
        # 工作副本不留盘（轮次命名文件已清理）
        retake_work = self.differ.base_dir / "screenshots" / "s1_current_r1.png"
        self.assertFalse(retake_work.exists(), "复测件工作副本不应残留")
        # 重截恰好发生一次（首截 + 一次复测）
        self.assertEqual(page.screenshot.await_count, 2)
        # R3：首截与复测件均落证据目录，复测件带 r{n} 后缀
        names = self._evidence_names()
        self.assertEqual(len(names), 2, f"证据目录应有首截+复测件两份: {names}")
        self.assertTrue(all(n.startswith("s1_polluted_") for n in names),
                        f"证据命名应含场景名: {names}")
        r1 = [n for n in names if n.endswith("_r1.png")]
        self.assertEqual(len(r1), 1, f"复测件应恰一份且带 r1 后缀: {names}")

    def test_recheck_still_polluted_rejected_with_single_retake(self):
        """复测仍污染才 baseline_rejected；重截至多一次（防死循环）。"""
        white = np.full((100, 100, 3), 255, dtype=np.uint8)
        page = MagicMock()
        page.screenshot, state = _make_page_screenshot_sequence([white, white])
        result = asyncio.run(self.differ.compare(page, "bl", "s1"))
        self.assertEqual(result[0]["status"], "baseline_rejected")
        self.assertIn("拒绝固化", result[0]["note"])
        self.assertIn("复测", result[0]["note"], "拒绝说明应留复测痕迹")
        labels = result[0].get("screenshot_labels", {})
        self.assertTrue(labels.get("blank_screenshot"))
        # 重截至多一次：首截 + 一次复测 = 恰 2 次截图，无第 3 次
        self.assertEqual(page.screenshot.await_count, 2,
                         "每场景每轮至多一次门内重截")
        # 基线不固化；首截不被复测件覆写（复测件未收敛不回写）
        self.assertFalse(
            (self.differ.base_dir / "baselines" / "bl.png").exists()
        )
        current_path = self.differ.base_dir / "screenshots" / "s1_current.png"
        np.testing.assert_array_equal(
            _read_png(current_path), white, "未收敛时首截保持标准路径内容",
        )
        # R3：首截与复测件均落证据目录（复测件 r1）
        names = self._evidence_names()
        self.assertEqual(len(names), 2, f"首截+复测件均落盘: {names}")
        self.assertEqual(
            len([n for n in names if n.endswith("_r1.png")]), 1,
            f"复测件带 r1 后缀: {names}",
        )
        # 工作副本不留盘
        self.assertFalse(
            (self.differ.base_dir / "screenshots" / "s1_current_r1.png").exists()
        )

    def test_recheck_failure_falls_closed_to_first_frame(self):
        """复测自身失败（页面崩溃等）不掩盖污染判定：按首截污染拒绝。"""
        white = np.full((100, 100, 3), 255, dtype=np.uint8)
        calls = {"n": 0}

        async def screenshot_then_crash(path, full_page=False):
            if calls["n"] == 0:
                _write_screenshot(Path(path), white)
            else:
                raise RuntimeError("page crashed")
            calls["n"] += 1

        page = MagicMock()
        page.screenshot = AsyncMock(side_effect=screenshot_then_crash)
        result = asyncio.run(self.differ.compare(page, "bl", "s1"))
        self.assertEqual(result[0]["status"], "baseline_rejected",
                         "复测失败应按首截污染拒绝（fail-closed）")
        labels = result[0].get("screenshot_labels", {})
        self.assertTrue(labels.get("blank_screenshot"))
        self.assertFalse(
            (self.differ.base_dir / "baselines" / "bl.png").exists()
        )

    def test_evidence_dump_failure_does_not_block_gate(self):
        """证据落盘失败只记 warning，不阻断污染门判定。"""
        white = np.full((100, 100, 3), 255, dtype=np.uint8)
        page = MagicMock()
        page.screenshot, state = _make_page_screenshot_sequence([white, white])
        with patch("core.verify_engine.visual_diff.shutil.copy",
                   side_effect=OSError("disk full")):
            result = asyncio.run(self.differ.compare(page, "bl", "s1"))
        self.assertEqual(result[0]["status"], "baseline_rejected",
                         "证据落盘失败不阻断门判定")

    def test_recheck_not_triggered_when_first_frame_clean(self):
        """首截干净（无污染）不触发门内重截：单次截图直接走正常门序。"""
        normal = _normal_pixels()
        page = MagicMock()
        page.screenshot, state = _make_page_screenshot_sequence([normal])
        result = asyncio.run(self.differ.compare(page, "bl", "s1"))
        self.assertEqual(result[0]["status"], "baseline_created")
        self.assertEqual(page.screenshot.await_count, 1,
                         "干净首截不应触发重截")
        self.assertEqual(self._evidence_names(), [], "无污染不落证据")


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
