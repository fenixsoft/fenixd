"""add-adjudication-auto-exec 4.2：外部 →testing 跃迁即时派发测试。

覆盖（specs/testing-dispatch-liveness/spec.md）：
- watch 通道 diff 到「既有 SPEC blocked→testing 跃迁」→ 立即经
  _recover_testing 触发 verifier 派发（不等 30 分钟 full_scan 兜底）；
- 无驱动判定/在飞互斥命中（有驱动 testing）→ 不重复派发；
- 稳态 testing（无跃迁）与「新出现即 testing」不触发即时派发
  （后者沿用 full_scan 节奏，防基线重建窗口派发风暴）；
- 即时派发失败 → 不上抛、无状态损坏（快照照常推进），恢复出口
  （full_scan 兜底网）照常可用。
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import StateMachine  # noqa: E402


def _write_state(state_path: Path, specs: dict) -> None:
    lines = ["# Fenix Project State", "", "## Specs", ""]
    for name, fields in specs.items():
        lines.append(f"### {name}")
        for k, v in fields.items():
            lines.append(f"- {k}: {v}")
        lines.append("")
    state_path.write_text("\n".join(lines), encoding="utf-8")


class TestTestingTransitionImmediateDispatch(unittest.TestCase):
    """watch 通道 →testing 跃迁即时派发（add-adjudication-auto-exec 4.1）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        from core.event_bus import EventBus

        self.pm = MagicMock()
        self.pm.project_root = self.tmpdir
        self.bus = EventBus(self.state_path, self.sm, self.pm, {}, self.logger)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _baseline_blocked(self, name="spec-a"):
        _write_state(self.state_path, {
            name: {
                "status": "blocked",
                "priority": 2,
                "error": "judge_rerun_cap: judge 重跑达上限",
                "depends_on": "null",
            },
        })
        self.bus._update_known_state()

    def _dispatch_with_guards(self, inflight=False):
        with patch("core.admin_monitor._pgrep_live_worktree",
                   return_value=False):
            with patch.object(self.bus, "_admin_inflight_guard",
                              return_value=inflight):
                self.bus._dispatch_changes(self.sm.read_all())

    def test_blocked_to_testing_dispatches_immediately(self):
        """dashboard/裁决外写解冻 blocked→testing → 锁外即时 verifier 派发。"""
        self._baseline_blocked("spec-a")
        assert self.sm.update_spec("spec-a", {"status": "testing"})
        self._dispatch_with_guards(inflight=False)
        self.pm.handle_event.assert_called_once()
        args = self.pm.handle_event.call_args[0]
        self.assertEqual(args[0], "spec_implemented")
        self.assertEqual(args[1], "spec-a")
        self.assertEqual(args[2].get("status"), "testing")
        info_calls = [str(c) for c in self.logger.info.call_args_list]
        self.assertTrue(
            any("re-triggering verify for undriven testing 'spec-a'" in c
                for c in info_calls),
            f"应复用 _recover_testing 恢复出口留痕: {info_calls}",
        )

    def test_driven_testing_inflight_admin_skips(self):
        """无驱动判定/在飞互斥命中（admin 处置在飞）→ 不派发、状态原样。"""
        self._baseline_blocked("spec-b")
        assert self.sm.update_spec("spec-b", {"status": "testing"})
        self._dispatch_with_guards(inflight=True)
        self.pm.handle_event.assert_not_called()
        # 状态不被即时通道触碰
        entry = self.sm.read_all().get("spec-b")
        self.assertEqual(entry.get("status"), "testing")

    def test_steady_testing_without_transition_no_redispatch(self):
        """稳态 testing（基线即 testing、无跃迁）→ 即时通道不派发
        （稳态恢复仍由 full_scan 的 _recover_one 例行承担）。"""
        _write_state(self.state_path, {
            "spec-c": {"status": "testing", "priority": 2,
                       "depends_on": "null"},
        })
        self.bus._update_known_state()
        self._dispatch_with_guards(inflight=False)
        self.pm.handle_event.assert_not_called()

    def test_new_appearance_at_testing_not_immediate(self):
        """新出现即 testing（基线后新增 SPEC）→ 不即时派发（防基线重建
        窗口全量派发风暴；沿用 full_scan _recover_one 兜底节奏）。"""
        self.bus._update_known_state()  # 空基线
        _write_state(self.state_path, {
            "spec-d": {"status": "testing", "priority": 2,
                       "depends_on": "null"},
        })
        self._dispatch_with_guards(inflight=False)
        self.pm.handle_event.assert_not_called()

    def test_dispatch_failure_isolated_and_fallback_intact(self):
        """即时派发失败：不上抛、快照照常推进（无状态损坏），恢复出口
        （full_scan 兜底网语义）仍可成功补派发。"""
        self._baseline_blocked("spec-e")
        assert self.sm.update_spec("spec-e", {"status": "testing"})
        with patch("core.admin_monitor._pgrep_live_worktree",
                   return_value=False):
            with patch.object(self.bus, "_admin_inflight_guard",
                              return_value=False):
                with patch.object(self.bus, "_recover_testing",
                                  side_effect=RuntimeError("引擎忙")):
                    # 不上抛（fail-open，watch 线程存活）
                    self.bus._dispatch_changes(self.sm.read_all())
        # 快照已推进：下一轮同状态无重复跃迁（无重复 run 残留的通道级前提）
        self.assertEqual(self.bus._known_specs.get("spec-e"), "testing")
        # 兜底网可用：full_scan 同款恢复出口随后成功补派发
        entry = self.sm.read_all()["spec-e"]
        with patch("core.admin_monitor._pgrep_live_worktree",
                   return_value=False):
            with patch.object(self.bus, "_admin_inflight_guard",
                              return_value=False):
                self.bus._recover_testing("spec-e", entry)
        self.pm.handle_event.assert_called_once_with(
            "spec_implemented", "spec-e", entry,
        )


if __name__ == "__main__":
    unittest.main()
