"""
视觉截图稳健性单元测试（fix-visual-baseline-settle / spec: visual-capture-robustness）

覆盖 tasks 1.3 / 2.3：
  - settle 等待：动画进行中→settle 后才截图；超时动画→达上限继续截图不抛
    异常；timeout_ms=0→跳过等待行为与现状一致
  - SSIM 低分自动重拍：首拍噪声重拍恢复（pass + retake_count=1）；重拍耗尽
    仍低分维持原判定（恰重拍 2 次）；首拍通过零重拍零附加开销
  - 重拍证据留痕：视觉结果含 retake_count 与 settle_waited_ms
"""

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
from PIL import Image

from core.verify_engine.browser import wait_animations_settled
from core.verify_engine.visual_diff import VisualDiffer


def _noise(seed: int, size: int = 120) -> np.ndarray:
    """合成高方差 RGB 噪声（通过健全性判定：非 blank / 非 low_contrast）。"""
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(size, size, 3), dtype=np.uint8)


def _near_baseline(baseline: np.ndarray) -> np.ndarray:
    """基线 + 微小噪声：SSIM 接近 1（≈0.99 档，pass）。"""
    rng = np.random.default_rng(99)
    pert = rng.integers(-4, 5, size=baseline.shape).astype(np.int16)
    return np.clip(baseline.astype(np.int16) + pert, 0, 255).astype(np.uint8)


def _write_screenshot(path: Path, pixels) -> None:
    Image.fromarray(pixels, "RGB").save(str(path))


def _make_shot_side_effect(tmpdir: Path, frames):
    """page.screenshot AsyncMock 侧车：按调用次序依次写入 frames 各帧。"""
    state = {"i": 0}

    def _shot(path=None, full_page=False, **kw):
        idx = state["i"]
        _write_screenshot(Path(path), frames[min(idx, len(frames) - 1)])
        state["i"] += 1
        return "ok"

    return AsyncMock(side_effect=_shot)


class TestWaitAnimationsSettled(unittest.TestCase):
    """helper 本身：全部 finished → True；超时/注入异常 → False；0 → 跳过。"""

    async def _run(self, page, timeout_ms):
        return await wait_animations_settled(page, timeout_ms)

    def test_settled_returns_true(self):
        """动画全部静置 → True。"""
        page = MagicMock()
        page.evaluate = AsyncMock(return_value=True)
        self.assertTrue(asyncio.run(self._run(page, 3000)))

    def test_timeout_returns_false(self):
        """达上限仍有未完成动画 → False（继续截图不放大失败）。"""
        page = MagicMock()
        page.evaluate = AsyncMock(return_value=False)
        self.assertFalse(asyncio.run(self._run(page, 3000)))

    def test_injection_failure_degrades_false(self):
        """注入异常（老内核/异常页面）→ 按超时退化返回 False，不抛出。"""
        page = MagicMock()
        page.evaluate = AsyncMock(side_effect=RuntimeError("evaluate failed"))
        self.assertFalse(asyncio.run(self._run(page, 3000)))

    def test_timeout_zero_skips_evaluate(self):
        """timeout_ms=0 → 跳过等待，evaluate 不被调用。"""
        page = MagicMock()
        page.evaluate = AsyncMock(return_value=True)
        self.assertTrue(asyncio.run(self._run(page, 0)))
        page.evaluate.assert_not_called()


class TestSettleBeforeScreenshot(unittest.TestCase):
    """Scenario: 动画静置等待（compare 层）。

    - 动画进行中 → settle 后才截图
    - 超时动画 → 达上限继续截图，compare 不抛异常
    - timeout_ms=0 → 跳过等待，行为与现状一致
    """

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.differ = VisualDiffer("spec_x", self.tmpdir,
                                   config={"verify_engine": {
                                       "visual_settle_timeout_ms": 3000}})

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_settle_before_screenshot(self):
        """动画进行中 → settle 后才截图（截图必须发生在静置之后）。"""
        order = []

        async def _fake_settle(page, timeout_ms):
            order.append("settle")
            await asyncio.sleep(0.02)
            return True

        page = MagicMock()
        shot = _make_shot_side_effect(self.tmpdir, [_noise(5)])

        async def _shot(path=None, full_page=False, **kw):
            order.append("shot")
            return await shot(path, full_page=full_page, **kw)

        page.screenshot = _shot
        with patch("core.verify_engine.visual_diff.wait_animations_settled",
                   new=_fake_settle):
            result = asyncio.run(self.differ.compare(page, "bl", "s1"))
        self.assertEqual(result[0]["status"], "baseline_created")
        self.assertEqual(order, ["settle", "shot"],
                         "settle 必须先于截图执行")
        self.assertGreaterEqual(result[0]["settle_waited_ms"], 0)
        self.assertEqual(result[0]["retake_count"], 0)

    def test_timeout_animation_proceeds_to_screenshot(self):
        """持续超上限的动画 → 达上限仍截图，compare 正常返回不抛异常。"""
        async def _never_settle(page, timeout_ms):
            await asyncio.sleep(0.02)
            return False

        page = MagicMock()
        page.screenshot = _make_shot_side_effect(self.tmpdir, [_noise(1)])
        with patch("core.verify_engine.visual_diff.wait_animations_settled",
                   new=_never_settle):
            result = asyncio.run(self.differ.compare(page, "bl", "s1"))
        self.assertEqual(result[0]["status"], "baseline_created")
        self.assertTrue((self.differ.base_dir / "screenshots" / "s1_current.png").exists())

    def test_timeout_zero_skips_settle(self):
        """timeout_ms=0 → 跳过 settle，行为与现状（无 settle）完全一致。"""
        differ = VisualDiffer("spec_x", self.tmpdir,
                              config={"verify_engine": {
                                  "visual_settle_timeout_ms": 0}})
        page = MagicMock()
        page.screenshot = _make_shot_side_effect(self.tmpdir, [_noise(2)])
        with patch("core.verify_engine.visual_diff.wait_animations_settled"
                   ) as ms:
            result = asyncio.run(differ.compare(page, "bl", "s1"))
        ms.assert_not_called()
        self.assertEqual(result[0]["status"], "baseline_created")
        self.assertEqual(result[0]["settle_waited_ms"], 0)


class TestRetakeOnLowSsim(unittest.TestCase):
    """Scenario: SSIM 低分自动重拍（compare 层，基线已存在）。

    - 首拍噪声重拍恢复 → pass 且 retake_count=1、settle_waited_ms>0
    - 三拍均低分 → diff_detected 且恰重拍 2 次（不重拍第 3 次）
    - 首拍即通过 → 零重拍零附加开销
    """

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        # 预置基线（噪声图，SSIM 对比用）
        baseline = _noise(1)
        bl_dir = self.tmpdir / ".fenix" / "verify-progress" / "spec_x" / "baselines"
        bl_dir.mkdir(parents=True, exist_ok=True)
        self.baseline_path = bl_dir / "bl.png"
        _write_screenshot(self.baseline_path, baseline)
        self.baseline = baseline
        self.differ = VisualDiffer(
            "spec_x", self.tmpdir,
            config={"verify_engine": {
                "visual_settle_timeout_ms": 3000,
                "visual_retake_max": 2}})

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _settle_seq(self, results):
        """按序返回 settle 结果（False=首拍时动画未静置→噪声帧被拍到）。"""
        calls = {"i": 0}

        async def _fake_settle(page, timeout_ms):
            await asyncio.sleep(0.03)
            val = results[min(calls["i"], len(results) - 1)]
            calls["i"] += 1
            return val

        return _fake_settle

    def test_first_noisy_retake_recovers(self):
        """首拍时序噪声（动画未静置帧）→ settle 后重拍恢复：pass + retake=1。"""
        noisy = _noise(2)              # 与基线差异巨大 → diff_detected
        clean = _near_baseline(self.baseline)  # ≈基线 → pass
        page = MagicMock()
        page.screenshot = _make_shot_side_effect(self.tmpdir, [noisy, clean])
        with patch("core.verify_engine.visual_diff.wait_animations_settled",
                   new=self._settle_seq([False, True])):
            result = asyncio.run(self.differ.compare(page, "bl", "s1"))
        r = result[0]
        self.assertEqual(r["status"], "pass")
        self.assertGreaterEqual(r["ssim"], self.differ.SSIM_PASS)
        self.assertEqual(r["retake_count"], 1)
        self.assertGreater(r["settle_waited_ms"], 0,
                           "重拍路径应记录实际 settle 等待时长")

    def test_all_low_retake_exhausted(self):
        """首拍与 2 次重拍均低分 → diff_detected 且恰重拍 2 次（不重拍第 3 次）。"""
        noisy1 = _noise(2)
        noisy2 = _noise(3)
        noisy3 = _noise(4)
        page = MagicMock()
        page.screenshot = _make_shot_side_effect(
            self.tmpdir, [noisy1, noisy2, noisy3])
        with patch("core.verify_engine.visual_diff.wait_animations_settled",
                   new=self._settle_seq([False, False, False])):
            result = asyncio.run(self.differ.compare(page, "bl", "s1"))
        r = result[0]
        self.assertEqual(r["status"], "diff_detected")
        self.assertLess(r["ssim"], self.differ.SSIM_WARN)
        self.assertEqual(r["retake_count"], 2)
        # 截图恰 3 次（首拍 + 2 次重拍）
        self.assertEqual(page.screenshot.call_count, 3)

    def test_first_pass_no_retake(self):
        """首拍即通过（≈0.98）→ 零重拍零附加开销。"""
        clean = _near_baseline(self.baseline)
        page = MagicMock()
        page.screenshot = _make_shot_side_effect(self.tmpdir, [clean])
        with patch("core.verify_engine.visual_diff.wait_animations_settled",
                   new=self._settle_seq([True])):
            result = asyncio.run(self.differ.compare(page, "bl", "s1"))
        r = result[0]
        self.assertEqual(r["status"], "pass")
        self.assertEqual(r["retake_count"], 0)
        self.assertEqual(page.screenshot.call_count, 1)


if __name__ == "__main__":
    unittest.main()