"""fix-spec-review-blocking-dispatch 异步初扫回归测试（tasks 5.8/5.9）。

覆盖：
- 5.8: start() 在扫描主体未完成时已进入主循环（替身阻塞扫描主体，断言主
  循环 tick 日志先于扫描完成）。
- 5.9: 基线快照 _known_specs 在扫描主体启动前已建立（存量 SPEC 不被判
  为「新出现」并重放 hook 事件）。
"""

import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import StateMachine
from core.event_bus import EventBus


class TestStartupScanAsync(unittest.TestCase):
    """tasks 5.8/5.9: full_scan 异步化后启动期行为。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        (self.tmpdir / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = self.tmpdir / ".fenix" / "STATE.md"
        self.sm = StateMachine(self.state_path, MagicMock())
        self.logger = MagicMock()
        self.pm = MagicMock()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _bus(self, hook_dispatcher=None):
        return EventBus(self.state_path, self.sm, self.pm, {}, self.logger,
                        hook_dispatcher=hook_dispatcher)

    def test_baseline_snapshot_established_before_scan(self):
        """5.9: 基线快照 _known_specs 在 start() 时已建立（_update_known_state
        同步完成），不依赖后台扫描线程。

        语义验证：先 add 一个存量 spec，然后 start()（调 _update_known_state），
        _known_specs 应立即反映该 spec；此后在后台扫描线程完成前，_dispatch_changes
        不会把存量 spec 当「新出现」重放事件。
        """
        bus = self._bus()
        # 添加存量 spec
        self.sm.add_spec("existing", {"status": "done"})
        # start() 内调 _update_known_state → _known_specs 应包含 existing
        bus.start()
        try:
            # 快照已建立：存量 spec 不被 _dispatch_changes 当新事件
            captured = []
            def dispatcher(spec, old, new, entry):
                captured.append((spec, old, new))
            bus.hook_dispatcher = dispatcher
            bus._dispatch_changes(self.sm.read_all())
            self.assertEqual(captured, [], "存量 spec 不得被重放为新事件")
        finally:
            bus.stop()

    def test_start_initial_scan_runs_async(self):
        """5.8: start_initial_scan 启动后台线程执行 _run_full_scan_body，
        立即返回（不阻塞调用方）。

        验证：用阻塞桩替换 _run_full_scan_body，确认 start_initial_scan
        立即返回且后台线程确实启动（_initial_scan_thread.is_alive）。

        竞态消解（上一轮全量回归偶发失败根因）：原桩只 set 事件就同步跑完
        扫描主体，微小 tmpdir + MagicMock 下整轮扫描毫秒级完成——后台线程若
        在主线程断言 is_alive() 前被调度并跑完，断言即假失败。改为「入桩确认
        + 事件放行」：stub_entered 证明线程已启动并进入扫描主体，release 桩
        保证断言时线程必然仍存活。
        """
        bus = self._bus()
        # 存量 spec
        self.sm.add_spec("s1", {"status": "ready"})
        bus.start()
        stub_entered = threading.Event()
        release = threading.Event()

        def slow_scan():
            stub_entered.set()
            # 阻塞桩：等主线程完成「立即返回 + 线程存活」断言后放行
            release.wait(timeout=5)
            bus._run_full_scan_body_original()

        # 保存原方法，替换为带信号的版本
        bus._run_full_scan_body_original = bus._run_full_scan_body
        bus._run_full_scan_body = slow_scan

        try:
            bus.start_initial_scan()
            # start_initial_scan 立即返回（不阻塞调用方）
            self.assertIsNotNone(bus._initial_scan_thread)
            # 后台线程确实启动并已进入扫描主体（而非同步执行——同步路径下
            # start_initial_scan 会被 release.wait 卡住，线程句柄为 None）
            self.assertTrue(stub_entered.wait(timeout=5),
                            "后台扫描线程应已进入扫描主体")
            self.assertTrue(bus._initial_scan_thread.is_alive(),
                            "后台扫描线程应在运行中")
        finally:
            # 放行后台线程再收口，避免 stop() 等待阻塞桩超时
            release.set()
            bus.stop()

    def test_known_specs_snapshot_prevents_false_new_events(self):
        """5.9: start() 后在后台扫描完成前，_dispatch_changes 不把存量 SPEC
        判为「新出现」重放 hook 事件——验证 _update_known_state 在 start() 内
        同步建立基线快照。
        """
        bus = self._bus()
        # 构造存量 spec
        self.sm.add_spec("existing", {"status": "ready"})
        self.sm.add_spec("another", {"status": "done"})
        # start() 建立快照
        bus.start()
        try:
            # 快照已建立（同步）
            self.assertIn("existing", bus._known_specs)
            self.assertIn("another", bus._known_specs)
            self.assertEqual(bus._known_specs["existing"], "ready")
            # 新增一个 spec：此时 _dispatch_changes 只会报新增
            self.sm.add_spec("new_one", {"status": "drafted"})
            events = []
            def on_event(spec, old, new, entry):
                events.append((spec, old, new))
            bus.hook_dispatcher = on_event
            bus._dispatch_changes(self.sm.read_all())
            # 只有 new_one 是「新出现」（old_status=None）
            new_events = [e for e in events if e[0] == "new_one"]
            self.assertEqual(len(new_events), 1)
            # existing/another 不产生事件
            other_events = [e for e in events if e[0] in ("existing", "another")]
            self.assertEqual(len(other_events), 0, "存量 spec 不应产生事件")
        finally:
            bus.stop()


if __name__ == "__main__":
    unittest.main()
