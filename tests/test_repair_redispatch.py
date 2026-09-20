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
        # add-spec-content-integrity-gate（bb9de76c）接入 dispatch 后同层新增的
        # 派发前闸门：本类只验重派资格放行，内容维度按「有内容」放行（c6d5924c
        # 对调度测试替身的同款补桩处方）。漏桩时：empty tmpdir + 恒 ready 替身
        # 触发闸门 → 摘除条目回队首 → 死循环挂起。
        self.engine._check_spec_content_missing = lambda n: False
        # 拦截 worker 线程体，避免真实跑 agent
        self.engine._run_agent_worker = MagicMock()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _set_spec(self, status):
        self.engine.state_machine.read_one = MagicMock(
            return_value={"status": status, "priority": 4}
        )

    def test_dispatch_eligible_status(self):
        """implementing 修复条目可派发（核心回归）；ready 实现条目照常派发。"""
        for status, expect_transition_called in (
                ("implementing", False), ("ready", True)):
            with self.subTest(status=status):
                engine = PMEngine(
                    MagicMock(), MagicMock(), {}, self.root, self.logger
                )
                # 拦截 worker 线程体，避免真实跑 agent
                engine._run_agent_worker = MagicMock()
                # 内容闸门按「有内容」放行（同 _Base.setUp 补桩，规格同注释）
                engine._check_spec_content_missing = lambda n: False
                engine.state_machine.read_one = MagicMock(
                    return_value={"status": status, "priority": 4}
                )
                engine._dispatcher._run_queue = [
                    (4, "spec-a", "implementer", time.time())
                ]
                engine._dispatcher._process_queue()
                self.assertEqual(engine._dispatcher._run_queue, [])
                engine._run_agent_worker.assert_called_once()
                if expect_transition_called:
                    # 派发点以**关键字**传来源上下文（fix-observability-gaps 2.2：
                    # trigger_run_id / agent_type / channel 是时间轴重建该路径的
                    # 唯一通道）；断言 MUST 与之一致——旧写法只给两个位置参数，
                    # 与实际调用形态不符而恒失败（存量缺陷）。
                    engine.state_machine.transition.assert_called_once_with(
                        "spec-a",
                        "implementing",
                        trigger_run_id=None,
                        agent_type="implementer",
                        channel="auto",
                    )

    def test_implementing_dispatch_skips_same_state_transition(self):
        """修复重派时状态已是 implementing，不得触发同态非法转换。"""
        self._set_spec("implementing")
        self.engine._dispatcher._run_queue = [(4, "spec-a", "implementer", time.time())]
        self.engine._dispatcher._process_queue()
        self.engine.state_machine.transition.assert_not_called()

    def test_testing_entry_still_skipped(self):
        """其余状态（testing 等）不得被放行。"""
        self._set_spec("testing")
        self.engine._dispatcher._run_queue = [(4, "spec-a", "implementer", time.time())]
        self.engine._dispatcher._process_queue()
        self.assertEqual(len(self.engine._dispatcher._run_queue), 1)
        self.engine._run_agent_worker.assert_not_called()


if __name__ == "__main__":
    unittest.main()
