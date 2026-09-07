"""验证执行阶段进度写点粒度测试（fix-verify-progress-granularity）。

根因（2026-09-07 fix-mobile-breakpoint-hook-tables 实测）：验证进度条 0→100%
一次跳变——
  1. 引擎开始执行场景前不写 (0, N) 起点进度：从出题落盘完成到首批 gather
     完成之间进度文件不存在，dashboard 无执行进度可显；
  2. 进度写点是批次级（asyncio.gather 整批完成后才写）：场景普遍无依赖时
     单批占满全部场景，中间态只存活数秒。
本组测试钉住两个写点：执行起点 (0, N) 与逐场景完成即写。
"""

import asyncio
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.verify_engine import runner as runner_module
from core.verify_engine.engine import VerifyEngine
from core.verify_engine.scenarios import (
    TestScenario as Scenario,  # 别名防 pytest 把数据类当测试类收集
    validate_scenario,
)


def _cli_scenario(sid: str) -> dict:
    return {
        "id": sid,
        "kind": "cli",
        "steps": [{"action": "run", "command": "true"}],
        "assertions": [],
    }


class _ProgressObservingRunner(runner_module.VerifyRunner):
    """测试专用 cli 假 Runner：execute 时快照进度文件内容。"""

    kind = "cli"

    def validate(self, scenario):
        return validate_scenario(scenario)

    async def setup(self):
        pass

    async def teardown(self):
        pass

    async def probe_env(self, candidates):
        return {"healthy": True, "detail": "cli 无降级探针"}

    async def execute(self, scenario):
        snap = None
        if self._progress_path.exists():
            try:
                snap = json.loads(self._progress_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                snap = None
        self.observations.append((scenario.id, snap))
        if scenario.id == "c1":
            self.gate.set()
        else:
            await asyncio.wait_for(self.gate.wait(), timeout=5)
        return {
            "scenario_id": scenario.id,
            "description": scenario.description,
            "status": "pass",
            "step_results": [],
            "assertion_results": [],
            "visual_results": [],
            "screenshots": [],
        }


class TestExecutionProgressGranularity(unittest.TestCase):
    """引擎执行阶段进度写点：起点 (0, N) + 逐场景完成即写。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / ".fenix").mkdir(parents=True, exist_ok=True)
        self.progress_path = (
            self.tmp / ".fenix" / "verify-progress" / "spec-a.json"
        )

    def _engine_with(self, runner: _ProgressObservingRunner) -> VerifyEngine:
        engine = VerifyEngine("spec-a", self.tmp, mock.MagicMock(), {})
        engine._runners["cli"] = runner
        return engine

    def _run_two_scenarios(self):
        """c1 先执行（快照起点进度），完成后 c2 执行（快照逐场景进度）。"""
        runner = _ProgressObservingRunner("spec-a", self.tmp, mock.MagicMock(), {})
        runner.observations = []
        runner.gate = asyncio.Event()
        runner.__class__._progress_path = self.progress_path
        engine = self._engine_with(runner)
        scenarios = [Scenario.from_dict(_cli_scenario("c1")),
                     Scenario.from_dict(_cli_scenario("c2"))]
        report = asyncio.run(engine.run(scenarios))
        return report, runner.observations

    def test_execution_start_writes_zero_progress_before_first_scenario(self):
        """首个场景开跑前进度文件必须已是 (0, N) 起点（旧实现不写→文件不存在）。"""
        _report, observations = self._run_two_scenarios()
        first_id, first_snap = observations[0]
        self.assertEqual(first_id, "c1")
        self.assertIsNotNone(
            first_snap,
            "引擎开始执行首个场景时进度文件尚不存在——"
            "缺少执行起点 (0, N) 写点（0→100% 跳变根因 1）")
        self.assertEqual(first_snap.get("total"), 2)
        self.assertEqual(first_snap.get("done"), 0)

    def test_per_scenario_progress_visible_to_sibling_scenario(self):
        """c1 完成后、c2 仍在执行时，进度文件必须已反映 done=1
        （旧实现批次级写点：c2 开跑时文件不存在）。"""
        _report, observations = self._run_two_scenarios()
        second_id, second_snap = observations[1]
        self.assertEqual(second_id, "c2")
        self.assertIsNotNone(
            second_snap,
            "c1 已完成但进度文件未更新——缺少逐场景完成写点"
            "（0→100% 跳变根因 2：进度只在整批 gather 后写）")
        self.assertGreaterEqual(second_snap.get("done", 0), 1)
        self.assertEqual(second_snap.get("total"), 2)

    def test_final_progress_completed_state(self):
        """run 结束后进度文件为 (N, N) 完成态（既有行为回归守卫）。"""
        _report, _observations = self._run_two_scenarios()
        data = json.loads(self.progress_path.read_text(encoding="utf-8"))
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["done"], 2)
        self.assertTrue(data["current"].startswith("验证完成"))


if __name__ == "__main__":
    unittest.main()
