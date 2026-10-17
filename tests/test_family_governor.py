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
    (Path(project_root) / ".fenix").mkdir(parents=True, exist_ok=True)
    sm = StateMachine(project_root / ".fenix" / "STATE.md", logger)
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
        self.assertEqual(self.engine._family._fix_prefix_depth("x"), 0)
        self.assertEqual(self.engine._family._fix_prefix_depth("fix-x"), 1)
        self.assertEqual(self.engine._family._fix_prefix_depth("fix-fix-x"), 2)
        self.assertEqual(self.engine._family._fix_prefix_depth("fix-fix-fix-x"), 3)
        self.assertEqual(self.engine._family._fix_prefix_depth("fix-fix-fix-fix-x"), 4)

    def test_depth_not_fooled_by_name_containing_fix(self):
        # "my-fix-x" 不以 fix- 开头 → 0；不是连续层
        self.assertEqual(self.engine._family._fix_prefix_depth("my-fix-x"), 0)
        # add-dashboard-spec-doc-tabs 系（历史真实命名）非 fix- 前缀 → 深度 0
        self.assertEqual(self.engine._family._fix_prefix_depth("add-dashboard-spec-doc-tabs"), 0)

    def test_strip_all_reveals_root(self):
        self.assertEqual(self.engine._family._fix_strip_all("fix-fix-x"), "x")
        self.assertEqual(self.engine._family._fix_strip_all("fix-x"), "x")
        self.assertEqual(self.engine._family._fix_strip_all("x"), "x")


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
        self.assertEqual(self.engine._family._family_width("fix-fix-fix-x"), 2)

    def test_width_excludes_done_and_pushed(self):
        self.sm.add_spec("x", {"status": "bug-found", "priority": 5})
        self.sm.add_spec("fix-x", {"status": "done", "priority": 6})
        self.sm.add_spec("fix-fix-x", {"status": "pushed", "priority": 7})
        # 历史已完成的祖先不追溯计数
        self.assertEqual(self.engine._family._family_width("fix-fix-fix-x"), 0)

    def test_width_excludes_self(self):
        self.sm.add_spec("fix-x", {"status": "ready", "priority": 6})
        self.assertEqual(self.engine._family._family_width("fix-x"), 0)

    def test_historical_four_layer_names_evaluated_by_current_value(self):
        """历史已存在的四层命名首次扫描即按现值评估（不追溯惩罚 done 祖先）。"""
        self.sm.add_spec("add-dashboard-spec-doc-tabs", {"status": "done", "priority": 5})
        self.sm.add_spec("fix-add-dashboard-spec-doc-tabs", {"status": "ready", "priority": 6})
        # add-dashboard-spec-doc-tabs 不是 fix- 前缀 → 不在族谱宽度口径内，不追溯
        self.assertEqual(self.engine._family._family_width("fix-add-dashboard-spec-doc-tabs"), 0)


class FamilyGateFixture:
    """构造族谱越界场景的公共前置。"""

    def __init__(self, engine, sm):
        self.engine = engine
        self.sm = sm


class TestFamilyGateInterception(unittest.TestCase):
    """task 3.1：_do_spec_bug_found 创建前拦截（derive 模式：名称前缀分流退役后，
    族谱收敛治理仅于 admin.bug_repair_mode=derive 时生效）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.logger = MagicMock()
        # .fenix 目录（信号落盘真实路径）
        (self.project_root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.engine, self.sm = _mk_engine(
            self.project_root, self.logger,
            config={"admin": {"bug_repair_mode": "derive"}},
        )
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

        self.engine._family._do_spec_bug_found("fix-fix-fix-x")

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

        self.engine._family._do_spec_bug_found("fix-fix-x")

        after = self.sm.read_all()
        self.assertEqual(set(after.keys()), before, "宽度第二成员必须被拦截")
        self.engine._enqueue.assert_not_called()
        self.assertEqual(after["fix-fix-x"]["status"], "bug-found")

    def test_width_below_limit_allowed(self):
        """对照：仅 1 个未完成兄弟 → 允许创建第二个。"""
        self.sm.add_spec("x", {"status": "bug-found", "priority": 5})
        self.sm.add_spec("fix-x", {"status": "ready", "priority": 6})

        self.engine._family._do_spec_bug_found("fix-x")

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

        self.engine._family._do_spec_bug_found("fix-fix-fix-x")

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

        self.engine._family._do_spec_bug_found("fix-fix-x")

        recs = self._signal_records()
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["spec"], "fix-fix-x")
        self.assertEqual(recs[0]["severity"], "major")


class TestFamilyWaiver(unittest.TestCase):
    """task 3.2：人工放行「恰好一次」语义（derive 模式下族谱治理生效）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.logger = MagicMock()
        (self.project_root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.engine, self.sm = _mk_engine(
            self.project_root, self.logger,
            config={"admin": {"bug_repair_mode": "derive"}},
        )
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

        self.engine._family._do_spec_bug_found("fix-fix-fix-x")

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
        self.engine._family._do_spec_bug_found("fix-fix-fix-x")
        self.assertIn("fix-fix-fix-fix-x", self.sm.read_all())

        # 第四层已完成 → 再次派生请求第五层 → 无豁免 → 拦截 + 信号
        self.sm.update_spec("fix-fix-fix-fix-x", {"status": "done"})
        self.assertEqual(self._signal_count(), 0)
        self.engine._family._do_spec_bug_found("fix-fix-fix-x")
        self.assertNotIn("fix-fix-fix-fix-fix-x", self.sm.read_all(),
                         "豁免已消费，第五层必须被拦截")
        self.assertEqual(self._signal_count(), 1, "拦截产生 family_explosion 信号")

    def test_waiver_consumed_even_when_below_limit(self):
        """豁免位在平凡创建（未超限）上也会被消耗（放行恰好一次语义，仅存量 fix 链）。"""
        self.sm.add_spec("fix-y", {"status": "bug-found", "priority": 5,
                                   "_family_waiver": True})
        self.engine._family._do_spec_bug_found("fix-y")
        # fix-fix-y 创建成功（legacy 路径，fix-y 为 fix-* 父 SPEC）
        self.assertIn("fix-fix-y", self.sm.read_all())
        self.assertNotEqual(self.sm.read_one("fix-y").get("_family_waiver", "true"), "true")

    def test_non_waiver_continuously_intercepted(self):
        """未放行持续拦截：每次越界派生都被拦截，均产生信号。"""
        self._build_four_layer_family()

        self.engine._family._do_spec_bug_found("fix-fix-fix-x")
        self.assertEqual(self._signal_count(), 1)
        self.assertNotIn("fix-fix-fix-fix-x", self.sm.read_all())

        # 第二次（父仍 bug-found，重复触发）→ 仍拦截
        self.engine._family._do_spec_bug_found("fix-fix-fix-x")
        self.assertEqual(self._signal_count(), 2, "未放行持续拦截，累计信号")
        self.assertNotIn("fix-fix-fix-fix-x", self.sm.read_all())

    def test_family_waiver_consumed_once_only(self):
        """_consume_family_waiver 幂等：单次消费后返回 False。"""
        self._build_four_layer_family(waiver=True)
        self.assertTrue(self.sm.read_one("fix-fix-fix-x").get("_family_waiver"))
        self.assertTrue(self.engine._family._consume_family_waiver("fix-fix-fix-x"))
        self.assertFalse(self.engine._family._consume_family_waiver("fix-fix-fix-x"))
        self.assertFalse(self.sm.read_one("fix-fix-fix-x").get("_family_waiver"))


# ── add-bug-repair-mode-config：bug-found 修复方式分流（task 2.3） ──────
# 分流依据由 SPEC 名称前缀（_is_fix_spec）改为 admin.bug_repair_mode 有效值：
# inplace（缺省）对任何 SPEC（含 fix-* 名字）原地打回；derive 派生子 fix 并闭环重验；
# 每次 bug-found 事件实时读取配置（不缓存），切换后下一次即生效。

class TestBugRepairModeSplit(unittest.TestCase):
    """task 2.3：配置驱动的 bug-found 修复方式分流。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.logger = MagicMock()
        (self.project_root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.engine, self.sm = _mk_engine(self.project_root, self.logger)
        self.engine._enqueue = MagicMock()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_buggy_spec(self, name):
        self.sm.add_spec(name, {"priority": 5})
        for s in ("ready", "implementing", "implemented", "testing", "bug-found"):
            self.sm.transition(name, s)

    def _write_tasks(self, name):
        spec_dir = self.project_root / "spec" / "changes" / name
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "tasks.md").write_text("# Tasks\n\n## 1. 实现\n\n- [ ] 1.1 x\n",
                                           encoding="utf-8")

    def test_fix_named_spec_inplace_by_default(self):
        """未配置（缺省 inplace）→ fix-* 名字 SPEC 原地打回，不派生 fix-fix-*。"""
        self._make_buggy_spec("fix-quick-links")
        self._write_tasks("fix-quick-links")
        before = set(self.sm.read_all().keys())

        self.engine._family._do_spec_bug_found("fix-quick-links")

        after = self.sm.read_all()
        self.assertEqual(set(after.keys()), before, "不得派生 fix-fix-* 子 SPEC")
        entry = after["fix-quick-links"]
        self.assertEqual(entry["status"], "implementing")
        self.assertEqual(int(entry.get("_verify_fail_rounds", 0)), 1)
        txt = (self.project_root / "spec" / "changes" / "fix-quick-links" / "tasks.md")\
            .read_text(encoding="utf-8")
        self.assertIn("## 验证修复", txt)
        self.engine._enqueue.assert_called_once_with("fix-quick-links", "implementer")

    def test_derive_for_non_fix_spec_spawns_child_and_closes_loop(self):
        """显式 derive → 非 fix 名字 SPEC 派生子 fix；子完成后闭环重验父。"""
        self.engine.config = {"admin": {"bug_repair_mode": "derive"}}
        self._make_buggy_spec("spec-a")
        self._write_tasks("spec-a")

        self.engine._family._do_spec_bug_found("spec-a")

        child = self.sm.read_one("fix-spec-a")
        self.assertIsNotNone(child, "derive 模式应派生子 fix")
        self.assertEqual(child["status"], "ready")
        # 父保持 bug-found 等待子 fix 完成闭环
        self.assertEqual(self.sm.read_one("spec-a")["status"], "bug-found")

        # 子 fix 完成 → 父 SPEC 自动进入重验（_on_spec_done 闭环保留生效）
        self.sm.update_spec("fix-spec-a", {"status": "done"})
        self.engine._enqueue.reset_mock()
        self.engine._on_spec_done("fix-spec-a")
        self.assertEqual(self.sm.read_one("spec-a")["status"], "implemented")
        self.engine._enqueue.assert_called_once_with("spec-a", "verifier")

    def test_mode_switch_effective_on_next_event(self):
        """模式实时生效：derive → 未配置（inplace）切换后下一次按 inplace 分流。"""
        self.engine.config = {"admin": {"bug_repair_mode": "derive"}}
        self._make_buggy_spec("spec-b")
        self._write_tasks("spec-b")
        self.engine._family._do_spec_bug_found("spec-b")
        self.assertIsNotNone(self.sm.read_one("fix-spec-b"), "derive 首轮派生子 fix")

        # 热切换：原地替换 config（与 fenixd 30s mtime 热更新同语义）
        self.engine.config = {}
        self.sm.update_spec("spec-b", {"status": "bug-found"})
        self.sm.remove_spec("fix-spec-b")
        self.engine._enqueue.reset_mock()
        self.engine._family._do_spec_bug_found("spec-b")

        entry = self.sm.read_one("spec-b")
        self.assertEqual(entry["status"], "implementing")
        self.assertEqual(int(entry.get("_verify_fail_rounds", 0)), 1)
        self.assertIsNone(self.sm.read_one("fix-spec-b"), "切换后不再派生")
        self.engine._enqueue.assert_called_once_with("spec-b", "implementer")


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
            result = "resolved"
            actions_taken = "检测根因，未放行"
            recommended_action = ""

        mon._apply_family_waiver({"signal_type": "family_explosion",
                                  "spec": "fix-fix-fix-x"}, _NoWaive())

        self.assertEqual(mon.state_machine.updates, [])

    def test_waiver_via_text_token(self):
        """文本动作含显式放行动词（放行一次/经评估放行）也视为放行。

        命中句须含「本次处置」限定语境（4dd652206902 收紧：含「本次/该族」
        限定词或与本次父 SPEC 名同现），夹具文本据此带「本次」。
        """
        specs = {"fix-fix-fix-x": {"status": "bug-found"}}
        mon = self._make_monitor(specs)

        class _Disp:
            family_waiver = False
            result = "resolved"
            actions_taken = "本次经评估放行一次创建"
            recommended_action = ""

        mon._apply_family_waiver({"signal_type": "family_explosion",
                                  "spec": "fix-fix-fix-x"}, _Disp())

        self.assertIn(("fix-fix-fix-x", {"_family_waiver": "true"}),
                      mon.state_machine.updates)

    def test_waiver_via_assignment_text(self):
        """文本动作含赋值型放行（_family_waiver=true）视为放行。

        命中句须含「本次处置」限定语境（a2644017472b 收紧，与动词型 4dd652206902
        同款口径：含「本次/该族」限定词或与本次父 SPEC 名同现），夹具文本据此
        带「本次」。
        """
        specs = {"fix-fix-fix-x": {"status": "bug-found"}}
        mon = self._make_monitor(specs)

        class _Disp:
            family_waiver = False
            result = "resolved"
            actions_taken = "确认放行：对本次父 SPEC 设置 _family_waiver=true"
            recommended_action = ""

        mon._apply_family_waiver({"signal_type": "family_explosion",
                                  "spec": "fix-fix-fix-x"}, _Disp())

        self.assertIn(("fix-fix-fix-x", {"_family_waiver": "true"}),
                      mon.state_machine.updates)

    def test_waiver_cross_family_release_with_assignment_same_sentence_does_not_grant(self):
        """他族谱放行叙述与字段赋值同句不构成对本次对象的放行（a2644017472b）。

        赋值型兜底曾只要求 _family_waiver=true 与「放行」二字同句——
        「另一族谱已放行（全库唯一的 _family_waiver=true）」这类无任何否定
        短语的他族谱叙述会绕过限定，给未放行的本次父 SPEC 误写豁免位。
        """
        specs = {"fix-fix-fix-x": {"status": "bug-found"}}
        mon = self._make_monitor(specs)

        class _Disp:
            family_waiver = False
            result = "resolved"
            actions_taken = "另一族谱已放行（全库唯一的 _family_waiver=true）"
            recommended_action = ""

        mon._apply_family_waiver({"signal_type": "family_explosion",
                                  "spec": "fix-fix-fix-x"}, _Disp())

        self.assertNotIn(("fix-fix-fix-x", {"_family_waiver": "true"}),
                         mon.state_machine.updates)

    def test_waiver_mention_in_negative_sentence_does_not_grant(self):
        """仅在否定句中提及豁免位字面令牌不构成放行（2026-08-28 实证回归）。

        处置叙述「明确不发放 _family_waiver」曾被宽松令牌匹配误判为放行动作，
        给未放行的父 SPEC 错误写入 _family_waiver=true。
        """
        specs = {"fix-fix-fix-x": {"status": "bug-found"}}
        mon = self._make_monitor(specs)

        class _Disp:
            family_waiver = False
            result = "resolved"
            actions_taken = ("只读诊断并修复验证基础设施；明确不发放 _family_waiver："
                             "不存在真实产品缺陷，派生第 4 层 fix 只会空转")
            recommended_action = ""

        mon._apply_family_waiver({"signal_type": "family_explosion",
                                  "spec": "fix-fix-fix-x"}, _Disp())

        self.assertNotIn(("fix-fix-fix-x", {"_family_waiver": "true"}),
                         mon.state_machine.updates)

    def test_waiver_mention_without_grant_semantics_does_not_grant(self):
        """叙述性提及（如「将 _family_waiver 复位为 False」）不构成放行。"""
        specs = {"fix-fix-fix-x": {"status": "bug-found"}}
        mon = self._make_monitor(specs)

        class _Disp:
            family_waiver = False
            result = "resolved"
            actions_taken = "复位误置的 _family_waiver 为 False，父 SPEC 维持 ready 重验"
            recommended_action = ""

        mon._apply_family_waiver({"signal_type": "family_explosion",
                                  "spec": "fix-fix-fix-x"}, _Disp())

        self.assertNotIn(("fix-fix-fix-x", {"_family_waiver": "true"}),
                         mon.state_machine.updates)

    def test_waiver_negation_and_cross_family_mention_does_not_grant(self):
        """完成时否定 + 他族谱豁免位提及不构成放行（2026-08-28 二次实证回归）。

        实证（fix-fix-fix-improve-failover-model-mapping-ui，admin run 1787945929）：
        处置文本「确认本族谱未发放 _family_waiver」中的完成时否定不在否定清单，
        且叙述他族谱时提及「全库唯一的 _family_waiver=true 在另一族谱」命中赋值型
        模式，双重误判给已终态父 SPEC 错误写入 _family_waiver=true。
        """
        specs = {"fix-fix-fix-x": {"status": "pushed"}}
        mon = self._make_monitor(specs)

        class _Disp:
            family_waiver = False
            result = "resolved"
            actions_taken = (
                "核对族谱终态：三个成员均为 pushed；"
                "确认本族谱未发放 _family_waiver（上限拦截本身正确）；"
                "全库唯一的 _family_waiver=true 在另一族谱，与本困境无关"
            )
            recommended_action = ""

        mon._apply_family_waiver({"signal_type": "family_explosion",
                                  "spec": "fix-fix-fix-x"}, _Disp())

        self.assertNotIn(("fix-fix-fix-x", {"_family_waiver": "true"}),
                         mon.state_machine.updates)

    def test_terminal_spec_signal_not_reinvoked(self):
        """信号指向的 spec 已终态（pushed）→ 不唤起 Administrator，仅标记 escalated。

        实证（2026-08-28）：陈旧未 escalated 的 family_explosion SIGNAL 记录使
        admin_monitor 在族谱成员全部 pushed 后仍被连续唤起 4 次（每次 admin run
        结束后数十毫秒即唤起下一次）。终态守卫应在摄取阶段直接跳过。
        """
        runner = _FakeRunner()
        mon = self._make_monitor(
            {"fix-fix-fix-x": {"status": "pushed"}}, runner=runner)
        self._seed_family_signal()

        signals = mon.run_once()
        self.assertEqual(len(runner.calls), 0, "终态 spec 不应唤起 Administrator")

        # 记录已标记 escalated：下一 tick 也不重捞
        mon.run_once()
        self.assertEqual(len(runner.calls), 0)

    def test_other_signal_type_ignored(self):
        specs = {"a": {"status": "implementing"}}
        mon = self._make_monitor(specs)

        class _Disp:
            family_waiver = True
            result = "resolved"
            actions_taken = ""
            recommended_action = ""

        mon._apply_family_waiver({"signal_type": "stuck", "spec": "a"}, _Disp())
        self.assertEqual(mon.state_machine.updates, [])


if __name__ == "__main__":
    unittest.main()