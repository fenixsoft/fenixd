"""fix 族谱收敛治理（fix-family-convergence-governor / design D4）测试。

覆盖 capability 的全部 Scenario：
- 族谱度量：深度（连续 fix- 前缀层数）/ 宽度（同根未完成兄弟数）
- 四层嵌套请求被拦截：不创建新 SPEC、无新分支、日志记录拦截原因
- 宽度第二兄弟被拦截
- 历史命名不追溯（done/pushed 祖先不计数）
- 拦截产生 family_explosion 信号（severity=major）→ admin store，spec 状态未变
- 人工放行（_family_waiver=true）后单次通行，豁免位用后自动复位
- 未放行持续拦截
- AdminMonitor 摄取 family_explosion 信号唤起 Administrator；放行 → 写豁免位
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.admin_monitor import AdminMonitor
from core.admin_store import AdminStore, SIGNAL
from core.state_machine import StateMachine

# 默认上限（未配置 config 时）：pm.family.max_depth=3 / max_width=2
DEFAULT_MAX_DEPTH = 3
DEFAULT_MAX_WIDTH = 2


def _mk_engine(project_root, logger, config=None):
    from core.pm_engine import PMEngine
    sm = StateMachine(project_root / "STATE.md", logger)
    engine = PMEngine(sm, MagicMock(), config or {}, project_root, logger)
    # 屏蔽 handle_event 的连环副作用（bug_found 由测试直接调用 _do_spec_bug_found）
    engine.handle_event = MagicMock()
    return engine, sm


class TestFixPrefixDepth(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.logger = MagicMock()
        self.engine, self.sm = _mk_engine(Path(self.tmpdir), self.logger)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_depth_counts_consecutive_fix_layers(self):
        self.assertEqual(self.engine._fix_prefix_depth("x"), 0)
        self.assertEqual(self.engine._fix_prefix_depth("fix-x"), 1)
        self.assertEqual(self.engine._fix_prefix_depth("fix-fix-x"), 2)
        self.assertEqual(self.engine._fix_prefix_depth("fix-fix-fix-x"), 3)
        self.assertEqual(self.engine._fix_prefix_depth("fix-fix-fix-fix-x"), 4)

    def test_depth_not_fooled_by_name_containing_fix(self):
        # "my-fix-x" 不以 fix- 开头 → 0；不是连续层
        self.assertEqual(self.engine._fix_prefix_depth("my-fix-x"), 0)
        # add-dashboard-spec-doc-tabs 系（历史真实命名）非 fix- 前缀 → 深度 0
        self.assertEqual(self.engine._fix_prefix_depth("add-dashboard-spec-doc-tabs"), 0)

    def test_strip_all_reveals_root(self):
        self.assertEqual(self.engine._fix_strip_all("fix-fix-x"), "x")
        self.assertEqual(self.engine._fix_strip_all("fix-x"), "x")
        self.assertEqual(self.engine._fix_strip_all("x"), "x")


class TestFamilyWidth(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.logger = MagicMock()
        self.engine, self.sm = _mk_engine(self.project_root, self.logger)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_width_counts_unfinished_same_root(self):
        # 同根 x 的未完成 fix 兄弟：fix-x（ready）、fix-fix-x（bug-found）各算 1
        self.sm.add_spec("x", {"status": "bug-found", "priority": 5})
        self.sm.add_spec("fix-x", {"status": "ready", "priority": 6})
        self.sm.add_spec("fix-fix-x", {"status": "bug-found", "priority": 7})
        self.assertEqual(self.engine._family_width("fix-fix-fix-x"), 2)

    def test_width_excludes_done_and_pushed(self):
        self.sm.add_spec("x", {"status": "bug-found", "priority": 5})
        self.sm.add_spec("fix-x", {"status": "done", "priority": 6})
        self.sm.add_spec("fix-fix-x", {"status": "pushed", "priority": 7})
        # 历史已完成的祖先不追溯计数
        self.assertEqual(self.engine._family_width("fix-fix-fix-x"), 0)

    def test_width_excludes_self(self):
        self.sm.add_spec("fix-x", {"status": "ready", "priority": 6})
        self.assertEqual(self.engine._family_width("fix-x"), 0)

    def test_historical_four_layer_names_evaluated_by_current_value(self):
        """历史已存在的四层命名首次扫描即按现值评估（不追溯惩罚 done 祖先）。"""
        self.sm.add_spec("add-dashboard-spec-doc-tabs", {"status": "done", "priority": 5})
        self.sm.add_spec("fix-add-dashboard-spec-doc-tabs", {"status": "ready", "priority": 6})
        # add-dashboard-spec-doc-tabs 不是 fix- 前缀 → 不在族谱宽度口径内，不追溯
        self.assertEqual(self.engine._family_width("fix-add-dashboard-spec-doc-tabs"), 0)


class FamilyGateFixture:
    """构造族谱越界场景的公共前置。"""

    def __init__(self, engine, sm):
        self.engine = engine
        self.sm = sm


class TestFamilyGateInterception(unittest.TestCase):
    """task 3.1：_do_spec_bug_found 创建前拦截。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.logger = MagicMock()
        # .fenix 目录（信号落盘真实路径）
        (self.project_root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.engine, self.sm = _mk_engine(self.project_root, self.logger)
        self.engine._enqueue = MagicMock()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _signal_records(self):
        store = AdminStore(self.project_root, self.logger)
        return [r for r in store.read_all()
                if r.get("signal_type") == "family_explosion"]

    def test_four_layer_request_intercepted(self):
        """WHEN fix-fix-fix-x 验证失败触发新子代创建请求（将成为第四层）→ 不创建。"""
        self.sm.add_spec("x", {"status": "bug-found", "priority": 5})
        self.sm.add_spec("fix-x", {"status": "done", "priority": 6})
        self.sm.add_spec("fix-fix-x", {"status": "done", "priority": 7})
        self.sm.add_spec("fix-fix-fix-x", {"status": "bug-found", "priority": 8})
        before = set(self.sm.read_all().keys())

        self.engine._do_spec_bug_found("fix-fix-fix-x")

        after = self.sm.read_all()
        # 不创建新 SPEC、无新分支、无 enqueue
        self.assertEqual(set(after.keys()), before, "四层请求必须被拦截，不创建新 SPEC")
        self.engine._enqueue.assert_not_called()
        # 父 SPEC 状态保持 bug-found 不变
        self.assertEqual(after["fix-fix-fix-x"]["status"], "bug-found")
        # 日志记录拦截原因
        self.engine.logger.error.assert_called()
        self.assertIn(
            "族谱", "".join(str(a) for a in self.engine.logger.error.call_args),
        )

    def test_width_second_sibling_intercepted(self):
        """WHEN 某 bug-found SPEC 已存在 2 个未完成子代，再次触发派生 → 中止。"""
        # 同根 x：fix-x（未完成）、fix-fix-x（未完成）→ 再派生第三成员被截
        self.sm.add_spec("x", {"status": "bug-found", "priority": 5})
        self.sm.add_spec("fix-x", {"status": "ready", "priority": 6})
        self.sm.add_spec("fix-fix-x", {"status": "bug-found", "priority": 7})
        before = set(self.sm.read_all().keys())

        self.engine._do_spec_bug_found("fix-fix-x")

        after = self.sm.read_all()
        self.assertEqual(set(after.keys()), before, "宽度第二成员必须被拦截")
        self.engine._enqueue.assert_not_called()
        self.assertEqual(after["fix-fix-x"]["status"], "bug-found")

    def test_width_below_limit_allowed(self):
        """对照：仅 1 个未完成兄弟 → 允许创建第二个。"""
        self.sm.add_spec("x", {"status": "bug-found", "priority": 5})
        self.sm.add_spec("fix-x", {"status": "ready", "priority": 6})

        self.engine._do_spec_bug_found("fix-x")

        after = self.sm.read_all()
        self.assertIn("fix-fix-x", after, "宽度未达上限，应允许再创建一个子 SPEC")
        self.engine._enqueue.assert_called()
        self.assertEqual(after["fix-fix-x"]["status"], "ready")

    def test_four_layer_intercepted_writes_signal(self):
        """拦截产生信号：admin_alerts 新增 family_explosion（severity=major），spec 状态未变。"""
        self.sm.add_spec("x", {"status": "bug-found", "priority": 5})
        self.sm.add_spec("fix-x", {"status": "done", "priority": 6})
        self.sm.add_spec("fix-fix-x", {"status": "done", "priority": 7})
        self.sm.add_spec("fix-fix-fix-x", {"status": "bug-found", "priority": 8})

        self.engine._do_spec_bug_found("fix-fix-fix-x")

        recs = self._signal_records()
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["kind"], SIGNAL)
        self.assertEqual(recs[0]["severity"], "major")
        self.assertEqual(recs[0]["spec"], "fix-fix-fix-x")
        # spec 状态未变
        self.assertEqual(self.sm.read_one("fix-fix-fix-x")["status"], "bug-found")

    def test_width_intercepted_writes_signal(self):
        self.sm.add_spec("x", {"status": "bug-found", "priority": 5})
        self.sm.add_spec("fix-x", {"status": "ready", "priority": 6})
        self.sm.add_spec("fix-fix-x", {"status": "bug-found", "priority": 7})

        self.engine._do_spec_bug_found("fix-fix-x")

        recs = self._signal_records()
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["spec"], "fix-fix-x")
        self.assertEqual(recs[0]["severity"], "major")


class TestFamilyWaiver(unittest.TestCase):
    """task 3.2：人工放行「恰好一次」语义。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.logger = MagicMock()
        (self.project_root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.engine, self.sm = _mk_engine(self.project_root, self.logger)
        self.engine._enqueue = MagicMock()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _build_four_layer_family(self, waiver=None):
        self.sm.add_spec("x", {"status": "bug-found", "priority": 5})
        self.sm.add_spec("fix-x", {"status": "done", "priority": 6})
        self.sm.add_spec("fix-fix-x", {"status": "done", "priority": 7})
        parent = {"status": "bug-found", "priority": 8}
        if waiver is not None:
            parent["_family_waiver"] = waiver
        self.sm.add_spec("fix-fix-fix-x", parent)

    def _signal_count(self):
        store = AdminStore(self.project_root, self.logger)
        return len([r for r in store.read_all()
                    if r.get("signal_type") == "family_explosion"])

    def test_waiver_allows_exactly_one_then_resets(self):
        """WHEN _family_waiver=true（放行一次）→ 下一轮允许创建恰好一个子 SPEC。"""
        self._build_four_layer_family(waiver=True)

        self.engine._do_spec_bug_found("fix-fix-fix-x")

        # 豁免位本次被消费：创建了第四层 fix 子 SPEC
        after = self.sm.read_all()
        self.assertIn("fix-fix-fix-fix-x", after, "豁免应放行一次，创建第四层")
        # 豁免位随即复位为 False
        self.assertNotEqual(self.sm.read_one("fix-fix-fix-x").get("_family_waiver", "true"),
                            "true")
        self.engine._enqueue.assert_called_with("fix-fix-fix-fix-x", "implementer")

    def test_waiver_reset_after_usage_then_reblocked(self):
        """豁免位用后复位：第五层请求（豁免已无）被再次拦截并产生信号。"""
        self._build_four_layer_family(waiver=True)
        self.engine._do_spec_bug_found("fix-fix-fix-x")
        self.assertIn("fix-fix-fix-fix-x", self.sm.read_all())

        # 第四层已完成 → 再次派生请求第五层 → 无豁免 → 拦截 + 信号
        self.sm.update_spec("fix-fix-fix-fix-x", {"status": "done"})
        self.assertEqual(self._signal_count(), 0)
        self.engine._do_spec_bug_found("fix-fix-fix-x")
        self.assertNotIn("fix-fix-fix-fix-fix-x", self.sm.read_all(),
                         "豁免已消费，第五层必须被拦截")
        self.assertEqual(self._signal_count(), 1, "拦截产生 family_explosion 信号")

    def test_waiver_consumed_even_when_below_limit(self):
        """豁免位在平凡创建（未超限）上也会被消耗（放行恰好一次语义）。"""
        self.sm.add_spec("y", {"status": "bug-found", "priority": 5,
                               "_family_waiver": True})
        self.engine._do_spec_bug_found("y")
        # fix-y 创建成功
        self.assertIn("fix-y", self.sm.read_all())
        self.assertNotEqual(self.sm.read_one("y").get("_family_waiver", "true"), "true")

    def test_non_waiver_continuously_intercepted(self):
        """未放行持续拦截：每次越界派生都被拦截，均产生信号。"""
        self._build_four_layer_family()

        self.engine._do_spec_bug_found("fix-fix-fix-x")
        self.assertEqual(self._signal_count(), 1)
        self.assertNotIn("fix-fix-fix-fix-x", self.sm.read_all())

        # 第二次（父仍 bug-found，重复触发）→ 仍拦截
        self.engine._do_spec_bug_found("fix-fix-fix-x")
        self.assertEqual(self._signal_count(), 2, "未放行持续拦截，累计信号")
        self.assertNotIn("fix-fix-fix-fix-x", self.sm.read_all())

    def test_family_waiver_consumed_once_only(self):
        """_consume_family_waiver 幂等：单次消费后返回 False。"""
        self._build_four_layer_family(waiver=True)
        self.assertTrue(self.engine._family_waiver_set("fix-fix-fix-x"))
        self.assertTrue(self.engine._consume_family_waiver("fix-fix-fix-x"))
        self.assertFalse(self.engine._consume_family_waiver("fix-fix-fix-x"))
        self.assertFalse(self.engine._family_waiver_set("fix-fix-fix-x"))


# ── AdminMonitor 摄取 family_explosion 信号 ─────────────────

class _FakeLogger:
    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


class _FakeSM:
    def __init__(self, specs: dict):
        self._specs = specs
        self.updates = []

    def read_all(self):
        return self._specs

    def read_one(self, name):
        return self._specs.get(name)

    def update_spec(self, name, updates):
        self.updates.append((name, updates))
        self._specs.setdefault(name, {})["_family_waiver"] = updates.get("_family_waiver")
        return True

    def hasattr_update(self):
        return hasattr(self, "update_spec")


class _FakeRunner:
    def __init__(self):
        self.calls = []

    def run_administrator(self, signal):
        self.calls.append(signal)
        from core.agent_runner import AdminDisposition
        return AdminDisposition(
            run_id="admin-test-1",
            spec=signal.get("spec"),
            success=True,
            problem=signal.get("description", ""),
            actions_taken="测试处置",
            result="resolved",
            summary="诊断结论：族谱爆炸；处置时间线：评估后放行一次；结果：已放行。",
            family_waiver=True,
        )


class TestFamilyExplosionAdminMonitor(unittest.TestCase):
    """family_explosion 信号被 AdminMonitor 摄取并唤起 Administrator 处置。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.logger = _FakeLogger()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_monitor(self, specs, runner=None, config=None):
        return AdminMonitor(
            config or {"admin": {"enabled": True}},
            _FakeSM(specs),
            self.project_root,
            self.logger,
            store=AdminStore(self.project_root, self.logger),
            agent_runner=runner,
        )

    def _seed_family_signal(self, spec="fix-fix-fix-x"):
        store = AdminStore(self.project_root, self.logger)
        store.append({
            "kind": SIGNAL,
            "signal_type": "family_explosion",
            "spec": spec,
            "severity": "major",
            "description": f"fix 族谱爆炸：'{spec}' 深度超限，自动创建已中止",
            "evidence": "candidate=fix-fix-fix-fix-x; 深度=4",
        })

    def test_signal_picked_up_and_administrator_invoked(self):
        runner = _FakeRunner()
        specs = {
            "fix-fix-fix-x": {"status": "bug-found"},
            "other": {"status": "implementing"},
        }
        mon = self._make_monitor(specs, runner=runner)
        self._seed_family_signal()

        signals = mon.run_once()

        self.assertEqual(len(runner.calls), 1, "Administrator 应被唤起一次")
        self.assertEqual(runner.calls[0]["signal_type"], "family_explosion")
        self.assertEqual(runner.calls[0]["spec"], "fix-fix-fix-x")
        self.assertGreaterEqual(len(signals), 1)

    def test_picked_up_even_without_in_progress_specs(self):
        """族谱拦截后父 SPEC 保持 bug-found（无 in-progress）也不漏传信号。"""
        runner = _FakeRunner()
        mon = self._make_monitor(
            {"fix-fix-fix-x": {"status": "bug-found"}}, runner=runner)
        self._seed_family_signal()

        signals = mon.run_once()

        self.assertEqual(len(runner.calls), 1, "无 in-progress 门控也不漏传")
        self.assertGreaterEqual(len(signals), 1)

    def test_same_record_not_reinvoked_next_tick(self):
        runner = _FakeRunner()
        mon = self._make_monitor(
            {"fix-fix-fix-x": {"status": "bug-found"}}, runner=runner)
        self._seed_family_signal()

        mon.run_once()
        mon.run_once()  # 第二 tick：同记录已 escalated

        self.assertEqual(len(runner.calls), 1, "同记录不反复唤起")

    def test_admin_waiver_sets_family_waiver_on_spec(self):
        runner = _FakeRunner()
        specs = {"fix-fix-fix-x": {"status": "bug-found"}}
        mon = self._make_monitor(specs, runner=runner)
        self._seed_family_signal()

        disp = runner.run_administrator({"signal_type": "family_explosion",
                                         "spec": "fix-fix-fix-x"})
        signal = {"signal_type": "family_explosion", "spec": "fix-fix-fix-x"}
        mon._apply_family_waiver(signal, disp)

        self.assertIn(("fix-fix-fix-x", {"_family_waiver": "true"}), mon.state_machine.updates)

    def test_non_waiver_does_not_set_family_waiver(self):
        specs = {"fix-fix-fix-x": {"status": "bug-found"}}
        mon = self._make_monitor(specs)
        self._seed_family_signal()

        class _NoWaive:
            family_waiver = False
            actions_taken = "检测根因，未放行"
            recommended_action = ""

        mon._apply_family_waiver({"signal_type": "family_explosion",
                                  "spec": "fix-fix-fix-x"}, _NoWaive())

        self.assertEqual(mon.state_machine.updates, [])

    def test_waiver_via_text_token(self):
        """文本动作含放行令牌（_family_waiver/放行/waive）也视为放行。"""
        specs = {"fix-fix-fix-x": {"status": "bug-found"}}
        mon = self._make_monitor(specs)

        class _Disp:
            family_waiver = False
            actions_taken = "经评估放行一次创建"
            recommended_action = ""

        mon._apply_family_waiver({"signal_type": "family_explosion",
                                  "spec": "fix-fix-fix-x"}, _Disp())

        self.assertIn(("fix-fix-fix-x", {"_family_waiver": "true"}),
                      mon.state_machine.updates)

    def test_other_signal_type_ignored(self):
        specs = {"a": {"status": "implementing"}}
        mon = self._make_monitor(specs)

        class _Disp:
            family_waiver = True
            actions_taken = ""
            recommended_action = ""

        mon._apply_family_waiver({"signal_type": "stuck", "spec": "a"}, _Disp())
        self.assertEqual(mon.state_machine.updates, [])


if __name__ == "__main__":
    unittest.main()