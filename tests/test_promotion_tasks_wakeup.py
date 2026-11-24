"""evo-promotion-lint-wakeup 回归测试。

覆盖（tasks 2.3 / 3.2）：
- 2.3a: lint 修复落盘后 tasks.md checksum 变化 → 秒级重评晋升（真实晋升链，
  auto 模式下 drafted → ready）。
- 2.3b: lint 仍败重写同值 error → 联合去重（error 值 + checksum）抑制重复
  触发与重复日志。
- 2.3c: promote_mode=manual → 唤醒派发出口被引擎既有 manual 闸口短路，不晋升。
- 2.3d: 非 tasks.md lint error 的 drafted spec → 不入唤醒名单，tasks.md 变化
  不触发任何事件。
- 3.2: dashboard clear_spec_error 清空成功显式留痕（含 spec 名与清空来源）。

event_bus 装配参照 tests/test_startup_full_scan_async.py（StateMachine +
pm_engine 替身 + _update_known_state 建基线，避免 _dispatch_changes 把存量
spec 判「新出现」重放 spec_drafted 事件污染 call 计数）。
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.event_bus import EventBus
from core.pm_engine.promotion import TASKS_LINT_MSG_PREFIX
from core.state_machine import StateMachine


_BROKEN_TASKS_V1 = (
    "# Tasks\n\n## 阶段一\n\n- [ ] 实现 A\n- [ ] 实现 B\n"
)
_BROKEN_TASKS_V2 = (
    "# Tasks\n\n## 阶段一\n\n- [ ] 实现 A\n- [ ] 实现 B\n- [ ] 实现 C\n"
)
_FIXED_TASKS = (
    "# Tasks\n\n## Deliverables\n\n```yaml\n"
    "- path: core/data.py\n  kind: modify\n```\n\n"
    "## 1. 阶段一\n\n- [ ] 1.1 do it\n"
)
# 单源（code-review item 96cf07eec4a5）：与 EventBus 消费常量同源于
# promotion.py 唯一生成点。2.3a 经真实晋升链断言 STATE error 命中本常量
# （assertIn 至 entry["error"]），即生成点→消费点的契约锚。
_TASKS_LINT_ERR_PHRASE = TASKS_LINT_MSG_PREFIX


class _WakeTestBase(unittest.TestCase):
    """公共夹具：tmp 项目根 + drafted spec + lint 拒绝的 tasks.md。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.pr = self.tmpdir / "proj"
        (self.pr / ".fenix").mkdir(parents=True, exist_ok=True)
        (self.pr / "core").mkdir(parents=True, exist_ok=True)
        (self.pr / "core" / "data.py").write_text("x", encoding="utf-8")
        self.state_path = self.pr / ".fenix" / "STATE.md"
        self.spec_dir = self.pr / "spec" / "changes" / "demo"
        self.spec_dir.mkdir(parents=True, exist_ok=True)
        # title 晋升门夹具（非 title 违规）
        (self.spec_dir / ".spec.yaml").write_text(
            "title: 测试中文标题\n", encoding="utf-8")
        (self.spec_dir / "tasks.md").write_text(
            _BROKEN_TASKS_V1, encoding="utf-8")
        self.sm = StateMachine(self.state_path, MagicMock())
        self.logger = MagicMock()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _bus(self, pm, config=None):
        bus = EventBus(self.state_path, self.sm, pm, config or {}, self.logger)
        # 基线快照同步建立（同 start()）：此后 _dispatch_changes 不把存量
        # spec 判「新出现」重放事件
        bus._update_known_state()
        return bus


class TestTasksMdWakeup(_WakeTestBase):
    """tasks.md 变化即时唤醒（2.3 四类用例）。"""

    def test_fixed_tasks_md_triggers_second_level_repromote(self):
        """2.3a：lint 修复落盘 → checksum 变化 → 真实晋升链秒级重评（→ready）。"""
        from core.pm_engine import PMEngine

        config = {"gates": {"promote_mode": "auto", "spec_review_mode": "never"}}
        engine = PMEngine(self.sm, MagicMock(), config, self.pr, self.logger)
        engine._on_spec_ready = MagicMock()
        self.sm.add_spec("demo", {"priority": 5})
        # 真实晋升链产出 lint 拒绝态（ drafted + tasks lint error）
        engine._on_spec_drafted("demo")
        entry = self.sm.read_one("demo")
        self.assertEqual(entry["status"], "drafted")
        self.assertIn(_TASKS_LINT_ERR_PHRASE, entry["error"])

        bus = self._bus(engine, config)
        bus._dispatch_changes(self.sm.read_all())
        self.assertIn("demo", bus._tasks_wake_list)

        # 首见巡检只登记不触发（当前文件内容正是 error 成因）
        bus._check_tasks_wakeup()
        entry = self.sm.read_one("demo")
        self.assertEqual(entry["status"], "drafted")
        engine._on_spec_ready.assert_not_called()

        # 修复落盘 → 下一个健康 tick（_check_tasks_wakeup）→ 秒级重评晋升
        (self.spec_dir / "tasks.md").write_text(_FIXED_TASKS, encoding="utf-8")
        bus._check_tasks_wakeup()

        entry = self.sm.read_one("demo")
        self.assertEqual(entry["status"], "ready", "修复落盘后应经唤醒出口重评晋升")
        engine._on_spec_ready.assert_called_once_with("demo")

    def test_same_value_error_after_failed_lint_is_suppressed(self):
        """2.3b：lint 仍败重写同值 error → 同值抑制（不重复触发/重复日志）。"""
        pm = MagicMock()
        pm.project_root = self.pr
        # 双违规拼接串（Deliverables 段居首 + tasks 段）：验证子串匹配口径
        joined_err = (
            "Deliverables 声明 lint 未通过：目录声明违规；"
            f"{_TASKS_LINT_ERR_PHRASE}：tasks.md 存在但未解析出任务分组"
        )
        self.sm.add_spec("demo", {"status": "drafted", "error": joined_err})

        bus = self._bus(pm)
        bus._dispatch_changes(self.sm.read_all())
        self.assertEqual(set(bus._tasks_wake_list), {"demo"})

        # 首见：登记不触发
        bus._check_tasks_wakeup()
        pm.handle_event.assert_not_called()

        # 用户改了文件但仍是坏形态 → checksum 变化 → 触发一次重评
        (self.spec_dir / "tasks.md").write_text(_BROKEN_TASKS_V2,
                                                encoding="utf-8")
        bus._check_tasks_wakeup()
        pm.handle_event.assert_called_once()
        args = pm.handle_event.call_args[0]
        self.assertEqual(args[0], "spec_drafted")
        self.assertEqual(args[1], "demo")

        # lint 仍败：STATE error 重写为同值（真实链路为 promotion 直写）→
        # STATE checksum 变化刷新名单，但 tasks.md checksum 未变 → 抑制
        err_same = self.sm.read_one("demo")["error"]
        self.sm.update_spec("demo", {"error": err_same})
        bus._dispatch_changes(self.sm.read_all())
        n_info_before = len(self.logger.info.call_args_list)
        bus._check_tasks_wakeup()
        pm.handle_event.assert_called_once()
        # 无重复唤醒日志（触发日志只此一条）
        self.assertEqual(
            [c for c in self.logger.info.call_args_list[n_info_before:]
             if "re-triggering promote wakeup" in str(c)],
            [],
        )

    def test_manual_promote_mode_not_woken(self):
        """2.3c：promote_mode=manual → 唤醒出口被引擎既有 manual 闸口短路。"""
        from core.pm_engine import PMEngine

        config = {"gates": {"promote_mode": "manual", "spec_review_mode": "never"}}
        engine = PMEngine(self.sm, MagicMock(), config, self.pr, self.logger)
        engine._on_spec_ready = MagicMock()
        # auto 期遗留的 lint 拒绝态（manual 闸口在 lint 之前，不再重写 error，
        # 此处直接种子 STATE 复现该现场）
        err_before = (
            f"{_TASKS_LINT_ERR_PHRASE}：tasks.md 存在但未解析出任务分组"
        )
        self.sm.add_spec("demo", {"status": "drafted", "error": err_before})

        bus = self._bus(engine, config)
        bus._dispatch_changes(self.sm.read_all())
        self.assertIn("demo", bus._tasks_wake_list)
        bus._check_tasks_wakeup()  # 首见登记

        # 修复落盘 → 唤醒派发 → manual 闸口短路：停留 drafted、error 原样保留
        (self.spec_dir / "tasks.md").write_text(_FIXED_TASKS, encoding="utf-8")
        bus._check_tasks_wakeup()

        entry = self.sm.read_one("demo")
        self.assertEqual(entry["status"], "drafted", "manual 模式不得被唤醒晋升")
        self.assertEqual(entry["error"], err_before, "manual 闸口先于 lint，error 不变")
        engine._on_spec_ready.assert_not_called()

    def test_non_lint_error_drafted_spec_unaffected(self):
        """2.3d：非 tasks.md lint error 的 drafted spec → 不入名单、零触发。"""
        pm = MagicMock()
        pm.project_root = self.pr
        self.sm.add_spec("a", {"status": "drafted",
                               "error": "验证环境阻塞：playwright 不可用"})
        self.sm.add_spec("b", {"status": "drafted"})  # 无 error
        self.sm.add_spec("c", {"status": "ready",
                               "error": f"{_TASKS_LINT_ERR_PHRASE}：残留"})  # 非 drafted

        bus = self._bus(pm)
        bus._dispatch_changes(self.sm.read_all())
        self.assertEqual(bus._tasks_wake_list, {})

        # tasks.md 怎么变都不触发
        (self.spec_dir / "tasks.md").write_text(_FIXED_TASKS, encoding="utf-8")
        bus._check_tasks_wakeup()
        pm.handle_event.assert_not_called()


class TestClearSpecErrorAuditLog(unittest.TestCase):
    """3.2：clear_spec_error 清空成功显式留痕（spec 名 + 清空来源）。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.pr = self.tmpdir / "proj"
        (self.pr / ".fenix").mkdir(parents=True, exist_ok=True)
        self.sm = StateMachine(self.pr / ".fenix" / "STATE.md", MagicMock())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_clear_success_writes_audit_line(self):
        from core.dashboard.data.admin_actions import clear_spec_error

        self.sm.add_spec("demo", {
            "status": "ready",
            "error": "tasks.md 可解析性 lint 未通过：tasks.md 存在但未解析出任务分组",
        })
        result = clear_spec_error(self.pr, "demo")
        self.assertEqual(result, {"ok": True, "found": True})
        entry = self.sm.read_one("demo")
        self.assertIsNone(entry["error"], "STATE 写语义不变：error 照常清空")

        # 留痕行落共享 sink（项目 .fenix/logs/fenixd.log，与 daemon 同源）
        log_text = (self.pr / ".fenix" / "logs" / "fenixd.log").read_text(
            encoding="utf-8")
        self.assertIn("clear_spec_error", log_text)
        self.assertIn("demo", log_text)
        self.assertIn("清空来源=dashboard", log_text)


if __name__ == "__main__":
    unittest.main()
