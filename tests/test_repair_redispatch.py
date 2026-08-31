"""原地打回修复重派回归测试（调度资格热修 2026-08-29）。

缺陷：打回处置 _enqueue 后 spec 状态为 implementing，而
process_run_queue 的资格检查 status != "ready" 把修复条目永久
静默跳过——修复重派在自动路径上不可达，验证失败后链路停摆。

修复：资格放行 implementing（入队点均在 run 终止后且 _enqueue
按 (spec, type) 去重，无双派风险）。
"""

import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from core.pm_engine import PMEngine


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        self.logger = MagicMock()
        self.engine = PMEngine(
            MagicMock(), MagicMock(), {}, self.root, self.logger
        )
        # 拦截 worker 线程体，避免真实跑 agent
        self.engine._run_agent_worker = MagicMock()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _set_spec(self, status):
        self.engine.state_machine.read_one = MagicMock(
            return_value={"status": status, "priority": 4}
        )

    def test_implementing_repair_entry_dispatches(self):
        """核心回归：implementing 状态的修复条目必须可派发。"""
        self._set_spec("implementing")
        self.engine._dispatcher._run_queue = [(4, "spec-a", "implementer", time.time())]
        self.engine._dispatcher._process_queue()
        self.assertEqual(self.engine._dispatcher._run_queue, [])
        self.engine._run_agent_worker.assert_called_once()

    def test_implementing_dispatch_skips_same_state_transition(self):
        """修复重派时状态已是 implementing，不得触发同态非法转换。"""
        self._set_spec("implementing")
        self.engine._dispatcher._run_queue = [(4, "spec-a", "implementer", time.time())]
        self.engine._dispatcher._process_queue()
        self.engine.state_machine.transition.assert_not_called()

    def test_ready_still_dispatches(self):
        """既有行为回归：ready 实现条目照常派发。"""
        self._set_spec("ready")
        self.engine._dispatcher._run_queue = [(4, "spec-a", "implementer", time.time())]
        self.engine._dispatcher._process_queue()
        self.assertEqual(self.engine._dispatcher._run_queue, [])
        self.engine._run_agent_worker.assert_called_once()
        self.engine.state_machine.transition.assert_called_once_with("spec-a", "implementing")

    def test_testing_entry_still_skipped(self):
        """其余状态（testing 等）不得被放行。"""
        self._set_spec("testing")
        self.engine._dispatcher._run_queue = [(4, "spec-a", "implementer", time.time())]
        self.engine._dispatcher._process_queue()
        self.assertEqual(len(self.engine._dispatcher._run_queue), 1)
        self.engine._run_agent_worker.assert_not_called()


if __name__ == "__main__":
    unittest.main()
