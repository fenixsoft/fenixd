"""派发队列老化（dispatch-queue-aging / design D3）的单元与调度回归测试。

覆盖 capability 的全部 Scenario：
- P6 条目获得窗口（P4/P5 持续占用下等待老化的 P6 获得派发机会）
- 未达阈值行为完全不变（aging.enabled=false 或缺省时 zero effect）
- 持久运行的 P4 不会被降级（活动集合记 base 原值）
- 同级顺序稳定（effective 相等按入队先后派发）
- 老化解界：floor_levels 封顶、daemon 重启重建队列从零计时（内存态）
"""

import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.pm_engine import PMEngine


def aging_config(**overrides):
    cfg = {
        "enabled": True,
        "initial_wait_minutes": 30,
        "step_down_minutes": 15,
        "floor_levels": 4,
    }
    cfg.update(overrides)
    return {"pm": {"dispatch": {"aging": cfg}}}


class TestAgingBonus(unittest.TestCase):
    """_aging_bonus / _effective_priority 纯函数。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.logger = MagicMock()
        self.engine = PMEngine(
            MagicMock(), MagicMock(), {}, self.project_root, self.logger
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_disabled_by_default_returns_zero(self):
        # 缺省 config 全空 → enabled=false，恒 0 → effective == base（向后兼容）
        self.assertEqual(self.engine._aging_bonus(time.time() - 10_000, time.time()), 0)
        self.assertEqual(self.engine._effective_priority(6, time.time() - 10_000, time.time()), 6)

    def test_below_initial_wait_no_aging(self):
        self.engine.config = aging_config()  # initial_wait=30min
        now = time.time()
        t0 = now - 29 * 60  # 未到 30 分钟
        self.assertEqual(self.engine._aging_bonus(t0, now), 0)
        self.assertEqual(self.engine._effective_priority(6, t0, now), 6)

    def test_one_step_down_after_initial_wait(self):
        self.engine.config = aging_config()  # initial 30min, step 15min
        now = time.time()
        t0 = now - 30 * 60 - 900 - 1  # initial + 整整一档 → 第 1 阶
        self.assertEqual(self.engine._aging_bonus(t0, now), 1)
        self.assertEqual(self.engine._effective_priority(6, t0, now), 5)

    def test_floor_levels_cap(self):
        self.engine.config = aging_config(floor_levels=4)
        now = time.time()
        t0 = now - 60 * 60 * 24 * 7  # 等待一整周 → 理应远超 floor
        self.assertEqual(self.engine._aging_bonus(t0, now), 4)
        self.assertEqual(self.engine._effective_priority(6, t0, now), 2)  # P6 最低到 P2

    def test_effective_never_negative(self):
        self.engine.config = aging_config(floor_levels=10)
        now = time.time()
        t0 = now - 10 * 60 * 60  # 等待 10 小时（远超 floor 对应的 2.5h）
        self.assertEqual(self.engine._aging_bonus(t0, now), 10)
        self.assertEqual(self.engine._effective_priority(6, t0, now), 0)  # 不为负


class TestQueueAgingScheduler(unittest.TestCase):
    """_process_queue 在老化开启时的调度行为。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.logger = MagicMock()
        self.logger.info = MagicMock()
        self.logger.warning = MagicMock()
        self.logger.error = MagicMock()
        self.logger.debug = MagicMock()

        self.sm = MagicMock()
        self.agent_runner = MagicMock()
        self.config = {"agents": {"max_concurrent": 2}}
        self.engine = PMEngine(
            self.sm, self.agent_runner, self.config,
            self.project_root, self.logger,
        )

        # 拦截 worker 线程启动，仅记录派发条目
        self.dispatched = []  # [(priority, spec_name, agent_type)]
        self._orig_thread_start = threading.Thread.start

        def fake_start(thread_self):
            if not thread_self.name.startswith("fenix-"):
                self._orig_thread_start(thread_self)
                return
            _, agent_type, spec_name = thread_self.name.split("-", 2)
            priority = thread_self._args[2]
            self.dispatched.append((priority, spec_name, agent_type))

        threading.Thread.start = fake_start

    def tearDown(self):
        threading.Thread.start = self._orig_thread_start
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _set_specs(self, specs):
        def read_one(name):
            return specs.get(name)

        self.sm.read_one = MagicMock(side_effect=read_one)
        self.sm.transition = MagicMock(return_value=True)

    def _enqueue_at(self, spec_name, agent_type, priority, age_seconds):
        """手工构造带过去入队时间戳的队列条目（测试老化路径）。"""
        entry = (priority, spec_name, agent_type, time.time() - age_seconds)
        with self.engine._dispatcher._queue_lock:
            self.engine._dispatcher._run_queue.append(entry)

    def test_starved_p6_gets_window_under_constant_p4(self):
        """P6 条目获得窗口：P4 持续运行，等待老化的 P6 在下一 tick 获得派发机会。

        aging 开启（initial 0 / step 1min）：P6 等待 3 分钟 → bonus=3 →
        effective=P3 ≤ min_active(P4) → 通过放宽规则派发。
        """
        self._set_specs({
            "spec-p6": {"status": "ready", "priority": 6},
        })
        self.config = {
            "agents": {"max_concurrent": 2},
            "pm": {"dispatch": {"aging": {
                "enabled": True, "initial_wait_minutes": 0,
                "step_down_minutes": 1, "floor_levels": 10,
            }}},
        }
        self.engine.config = self.config

        # P4 正在运行
        with self.engine._dispatcher._queue_lock:
            self.engine._dispatcher._active_runs = 1
            self.engine._dispatcher._active_priorities.add(4)

        # P6 已等待 3 分钟（未老化时会被 P4 永久压制）
        self._enqueue_at("spec-p6", "implementer", 6, age_seconds=180)

        self.engine._dispatcher._process_queue()

        self.assertEqual(len(self.dispatched), 1)
        self.assertEqual(self.dispatched[0][1], "spec-p6", "老化的 P6 应获得派发窗口")

    def test_control_p6_starved_without_aging(self):
        """对照：aging 关闭时 P6 被 P4 压制，不得派发（行为与现状一致）。"""
        self._set_specs({
            "spec-p6": {"status": "ready", "priority": 6},
        })
        with self.engine._dispatcher._queue_lock:
            self.engine._dispatcher._active_runs = 1
            self.engine._dispatcher._active_priorities.add(4)

        self._enqueue_at("spec-p6", "implementer", 6, age_seconds=180)

        self.engine._dispatcher._process_queue()

        self.assertEqual(self.dispatched, [], "未达阈值/未开启时行为必须完全不变")

    def test_active_set_records_base_priority_not_effective(self):
        """持久运行的条目不会被降级：派发老化的 P6 后 _active_priorities 记原值 P6。

        因此紧随其后的 P7 在 P6 运行期间仍然被挡——活动任务语义不因老化改变。
        """
        self._set_specs({
            "spec-p6": {"status": "ready", "priority": 6},
            "spec-p7": {"status": "ready", "priority": 7},
        })
        self.config = {
            "agents": {"max_concurrent": 2},
            "pm": {"dispatch": {"aging": {
                "enabled": True, "initial_wait_minutes": 0,
                "step_down_minutes": 1, "floor_levels": 10,
            }}},
        }
        self.engine.config = self.config

        # P6 等待 3 分钟 → effective P3；P7 新入队
        self._enqueue_at("spec-p6", "implementer", 6, age_seconds=180)
        with self.engine._dispatcher._queue_lock:
            # P4 在跑，防止一次性并发派发两个
            self.engine._dispatcher._active_runs = 1
            self.engine._dispatcher._active_priorities.add(4)

        self.engine._dispatcher._process_queue()

        self.assertEqual([d[1] for d in self.dispatched], ["spec-p6"])
        # 活动集合记 base 原值 P6（而非 effective P3）
        with self.engine._dispatcher._queue_lock:
            self.assertIn(6, self.engine._dispatcher._active_priorities)
            self.assertNotIn(3, self.engine._dispatcher._active_priorities)

        # P6 仍在运行：P7 即使新入队也因 min_active=4 <7 被挡（无第二并发）
        self._enqueue_at("spec-p7", "implementer", 7, age_seconds=1)
        with self.engine._dispatcher._queue_lock:
            self.engine._dispatcher._active_runs = 2  # 占满并行度
        before = len(self.dispatched)
        self.engine._dispatcher._process_queue()
        self.assertEqual(len(self.dispatched), before, "并行度已满，不派发")

    def test_same_effective_fcfs_order_stable(self):
        """同级顺序稳定：两个同为 P6、等效值相同的条目按入队先后派发。"""
        self._set_specs({
            "spec-a": {"status": "ready", "priority": 6},
            "spec-b": {"status": "ready", "priority": 6},
        })
        self.config = {
            "agents": {"max_concurrent": 2},
            "pm": {"dispatch": {"aging": {
                "enabled": True, "initial_wait_minutes": 0,
                "step_down_minutes": 1, "floor_levels": 10,
            }}},
        }
        self.engine.config = self.config

        # 同一老化阶梯内（同一步级，effective 相同）：
        # A 先入队 90 秒、B 后入队 60 秒 → bonus 均为 1 → effective 均 P5
        self._enqueue_at("spec-a", "implementer", 6, age_seconds=90)
        self._enqueue_at("spec-b", "implementer", 6, age_seconds=60)

        self.engine._dispatcher._process_queue()

        self.assertEqual([d[1] for d in self.dispatched], ["spec-a", "spec-b"],
                         "同级条目派发顺序必须遵循入队先后，不被老化扰动")

    def test_enqueue_records_timestamp_for_zerotimer_restart(self):
        """enqueued_at 在入队时写入（内存态）：daemon 重启重建队列后从零计时。

        此处断言 _enqueue 产生的条目携带接近当前时刻的 enqueued_at —— 若 daemon
        重启，新队列条目必然新近入队，等待计数归零（spec 要求「从零计时」）。
        """
        with self.engine._dispatcher._queue_lock:
            self.engine._dispatcher._run_queue.clear()
        self.engine._dispatcher._enqueue("spec-x", "implementer")
        with self.engine._dispatcher._queue_lock:
            entry = self.engine._dispatcher._run_queue[0]
        self.assertEqual(len(entry), 4)
        self.assertAlmostEqual(entry[3], time.time(), delta=5)


if __name__ == "__main__":
    unittest.main()