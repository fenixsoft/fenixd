"""
视觉基线完整性单元测试（fix-visual-baseline-settle / spec: visual-baseline-integrity）

覆盖 tasks 3.5 / 4.3：
  - 基线固化门：步骤失败场景首轮 → baseline_deferred 且不固化；下轮干净 →
    正常固化；DOM 全过 + baseline_deferred → 场景非 failed 且 judge 不计打回
  - 存量污染基线侦测：三连 diff_detected + DOM 全过 → 第 3 轮告警 + 标记；
    中途恢复 → 清零无告警；一轮 DOM 真失败 → 该轮不累计不告警；
    跨重启计数延续；baseline_deferred 轮计数保持
"""

import asyncio
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
from PIL import Image

from core.admin_store import AdminStore
from core.verify_engine.runner import determine_scenario_status
from core.verify_engine.visual_diff import VisualDiffer
from core.verdict_check import has_only_non_driving_visual_indicators

SUSPICIOUS_SIGNAL = "visual_baseline_suspicious"


def _noise(seed: int, size: int = 120) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(size, size, 3), dtype=np.uint8)


def _near_baseline(baseline: np.ndarray) -> np.ndarray:
    rng = np.random.default_rng(99)
    pert = rng.integers(-4, 5, size=baseline.shape).astype(np.int16)
    return np.clip(baseline.astype(np.int16) + pert, 0, 255).astype(np.uint8)


def _write_screenshot(path: Path, pixels) -> None:
    Image.fromarray(pixels, "RGB").save(str(path))


def _shot_side_effect(frames):
    """page.screenshot AsyncMock 侧车：按调用次序依次写入 frames 各帧。"""
    state = {"i": 0}

    def _shot(path=None, full_page=False, **kw):
        _write_screenshot(Path(path), frames[min(state["i"], len(frames) - 1)])
        state["i"] += 1
        return "ok"

    return AsyncMock(side_effect=_shot)


def _passed_context() -> dict:
    return {"steps_failed": False, "step_results": [{"success": True}],
            "assertion_results": [{"pass": True}]}


def _failed_context() -> dict:
    return {"steps_failed": False, "step_results": [{"success": True}],
            "assertion_results": [{"pass": False, "layer": 2}]}


class _BaseCase(unittest.TestCase):
    """共享夹具：tmpdir + differ（settle 直接通过，避免真实浏览器）。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.base_dir = (
            self.tmpdir / ".fenix" / "verify-progress" / "spec_x")
        self.differ = VisualDiffer(
            "spec_x", self.tmpdir,
            config={"verify_engine": {
                "visual_settle_timeout_ms": 3000,
                "visual_retake_max": 2}})

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _settle_true(self):
        async def _fake_settle(page, timeout_ms):
            return True

        return patch(
            "core.verify_engine.visual_diff.wait_animations_settled",
            new=_fake_settle)

    def _make_page(self, frames):
        page = MagicMock()
        page.screenshot = _shot_side_effect(frames)
        return page


class TestBaselineCreationGate(_BaseCase):
    """Scenario: 基线固化前置条件（步骤+断言全过才固化）。"""

    def test_step_failure_defers_baseline(self):
        """步骤失败场景首轮 → baseline_deferred 且不固化。"""
        page = self._make_page([_noise(1)])
        with self._settle_true():
            result = asyncio.run(self.differ.compare(
                page, "bl", "s1",
                scenario_context={"steps_failed": True,
                                  "step_results": [{"success": False}],
                                  "assertion_results": []}))
        r = result[0]
        self.assertEqual(r["status"], "baseline_deferred")
        self.assertFalse(r["pass"])
        self.assertIn("前置条件", r["note"])
        bl = self.differ.base_dir / "baselines" / "bl.png"
        self.assertFalse(bl.exists(), "失败场景首轮不得固化基线")

    def test_assertion_failure_defers_baseline(self):
        """断言失败场景首轮 → baseline_deferred（健全性判定仍在前）。"""
        page = self._make_page([_noise(2)])
        with self._settle_true():
            result = asyncio.run(self.differ.compare(
                page, "bl", "s1", scenario_context=_failed_context()))
        self.assertEqual(result[0]["status"], "baseline_deferred")
        self.assertFalse(
            (self.differ.base_dir / "baselines" / "bl.png").exists())

    def test_clean_next_round_creates_baseline(self):
        """下轮干净执行 → 正常固化（顺延不丢）。"""
        # 第一轮：步骤失败 → deferred
        page1 = self._make_page([_noise(1)])
        with self._settle_true():
            r1 = asyncio.run(self.differ.compare(
                page1, "bl", "s1",
                scenario_context={"steps_failed": True,
                                  "step_results": [{"success": False}],
                                  "assertion_results": []}))
        self.assertEqual(r1[0]["status"], "baseline_deferred")
        # 第二轮：干净 → created
        page2 = self._make_page([_noise(3)])
        with self._settle_true():
            r2 = asyncio.run(self.differ.compare(
                page2, "bl", "s1", scenario_context=_passed_context()))
        self.assertEqual(r2[0]["status"], "baseline_created")
        self.assertTrue(
            (self.differ.base_dir / "baselines" / "bl.png").exists())

    def test_baseline_deferred_not_scenario_failed(self):
        """DOM 全过 + baseline_deferred → 场景 status 非 failed（pass）。"""
        status = determine_scenario_status(
            [{"action": "navigate", "success": True}],
            [{"pass": True, "layer": 2}],
            [{"status": "baseline_deferred", "pass": False}],
        )
        self.assertEqual(status, "pass")

    def test_baseline_deferred_not_driving_for_judge(self):
        """baseline_deferred 归入非驱动场景：judge 不计打回依据。"""
        scenario = {
            "scenario_id": "s1",
            "status": "pass",
            "step_results": [{"success": True}],
            "assertion_results": [{"pass": True}],
            "visual_results": [{"status": "baseline_deferred", "pass": False}],
        }
        self.assertTrue(has_only_non_driving_visual_indicators(scenario))
        # 含 diff_detected 驱动视觉结论 → 非「仅非驱动」
        scenario["visual_results"] = [{"status": "diff_detected", "pass": False}]
        self.assertFalse(has_only_non_driving_visual_indicators(scenario))
        # 有 DOM 失败 → 非「仅非驱动」（真实缺陷按 DOM 归因）
        scenario["visual_results"] = [
            {"status": "baseline_deferred", "pass": False}]
        scenario["assertion_results"] = [{"pass": False, "layer": 2}]
        self.assertFalse(has_only_non_driving_visual_indicators(scenario))


class TestPollutedBaselineDetection(_BaseCase):
    """Scenario: 存量污染基线侦测与告警（连续计数持久化）。"""

    def _seed_baseline(self):
        bl_dir = self.differ.base_dir / "baselines"
        bl_dir.mkdir(parents=True, exist_ok=True)
        _write_screenshot(bl_dir / "bl.png", _noise(10))

    def _run_round(self, frame, context) -> dict:
        page = self._make_page([frame])
        with self._settle_true():
            result = asyncio.run(self.differ.compare(
                page, "bl", "scn-a", scenario_context=context))
        return result[0]

    def _streaks(self) -> dict:
        path = self.differ.base_dir / "baseline_streaks.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _alerts(self):
        store = AdminStore(self.tmpdir)
        return [e for e in store.read_all()
                if e.get("signal_type") == SUSPICIOUS_SIGNAL]

    def test_three_streak_triggers_suspicious(self):
        """三连 diff_detected + DOM 全过 → 第 3 轮告警 + 标记文件。"""
        self._seed_baseline()
        low = _noise(20)  # 与基线差异巨大 → diff_detected
        self._run_round(low, _passed_context())
        self._run_round(low, _passed_context())
        r3 = self._run_round(low, _passed_context())
        self.assertEqual(r3["status"], "diff_detected")
        # 第 3 轮后：计数=3、suspicious 标记 + 告警
        entry = self._streaks().get("scn-a", {})
        self.assertEqual(entry.get("count"), 3)
        self.assertTrue(entry.get("suspicious"))
        marker = self.differ.base_dir / "baselines" / "bl.suspicious"
        self.assertTrue(marker.exists(), "基线旁应有 .suspicious 标记文件")
        alerts = self._alerts()
        self.assertEqual(len(alerts), 1)
        self.assertIn("scn-a", alerts[0]["description"])
        self.assertIn("bl.png", alerts[0]["evidence"])
        # 再跑一轮不重复告警（只标记一次，不刷屏）
        self._run_round(low, _passed_context())
        self.assertEqual(len(self._alerts()), 1)
        # 基线文件未被自动覆盖/删除
        self.assertTrue((self.differ.base_dir / "baselines" / "bl.png").exists())

    def test_recovery_resets_and_clears_marker(self):
        """连续 2 轮 diff_detected 后 SSIM 恢复 → 清零、无告警、撤标记。"""
        self._seed_baseline()
        low = _noise(20)
        self._run_round(low, _passed_context())
        self._run_round(low, _passed_context())
        entry = self._streaks().get("scn-a", {})
        self.assertEqual(entry.get("count"), 2)
        # 第 3 轮恢复 pass（settle+重拍后画面≈基线）
        clean = _near_baseline(np.asarray(
            Image.open(self.differ.base_dir / "baselines" / "bl.png")))
        r3 = self._run_round(clean, _passed_context())
        self.assertEqual(r3["status"], "pass")
        self.assertEqual(self._streaks().get("scn-a", {}).get("count"), 0)
        self.assertFalse(self._streaks().get("scn-a", {}).get("suspicious"))
        self.assertFalse(
            (self.differ.base_dir / "baselines" / "bl.suspicious").exists())
        self.assertEqual(self._alerts(), [])

    def test_dom_failure_round_not_counted(self):
        """一轮 DOM 真失败 → 该轮不累计、不告警（真实缺陷不伪装成污染）。"""
        self._seed_baseline()
        low = _noise(20)
        self._run_round(low, _passed_context())      # count=1
        self._run_round(low, _passed_context())      # count=2
        r3 = self._run_round(low, _failed_context())  # DOM 失败 → 清零
        self.assertEqual(r3["status"], "diff_detected")
        self.assertEqual(self._streaks().get("scn-a", {}).get("count"), 0)
        self.assertEqual(self._alerts(), [])

    def test_count_persists_across_restart(self):
        """跨重启计数延续：新 VisualDiffer 实例读同文件继续累计。"""
        self._seed_baseline()
        low = _noise(20)
        self._run_round(low, _passed_context())
        self.assertEqual(self._streaks().get("scn-a", {}).get("count"), 1)
        # 「daemon 重启」：新实例指向同一 spec 目录
        differ2 = VisualDiffer("spec_x", self.tmpdir)
        page2 = self._make_page([low])
        with self._settle_true():
            r2 = asyncio.run(differ2.compare(
                page2, "bl", "scn-a", scenario_context=_passed_context()))
        self.assertEqual(r2[0]["status"], "diff_detected")
        self.assertEqual(self._streaks().get("scn-a", {}).get("count"), 2)

    def test_baseline_deferred_round_keeps_count(self):
        """baseline_deferred 轮不累计也不清零（计数保持）。"""
        self._seed_baseline()
        low = _noise(20)
        self._run_round(low, _passed_context())  # count=1
        self.assertEqual(self._streaks().get("scn-a", {}).get("count"), 1)
        # 人工删除污染基线（重建交人工确认的必然前置）→ 下轮步骤失败 →
        # baseline_deferred，计数保持 1 不变
        (self.differ.base_dir / "baselines" / "bl.png").unlink()
        page2 = self._make_page([_noise(30)])
        with self._settle_true():
            r2 = asyncio.run(self.differ.compare(
                page2, "bl", "scn-a",
                scenario_context={"steps_failed": True,
                                  "step_results": [{"success": False}],
                                  "assertion_results": []}))
        self.assertEqual(r2[0]["status"], "baseline_deferred")
        self.assertEqual(self._streaks().get("scn-a", {}).get("count"), 1)


if __name__ == "__main__":
    unittest.main()