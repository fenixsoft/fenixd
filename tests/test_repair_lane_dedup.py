"""fix-repair-lane-dedup 三级去重守卫测试。

覆盖 capability spec 的全部 Scenario：
- 守卫一：reset 路径同根子 fix 存在时抑制重实现
- 守卫二：spawn 路径在重实现在飞时跳过派生
- 守卫三：派发级同根互斥
- 零行为差异回退保证
"""

import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import StateMachine


def _mk_engine(project_root, logger, config=None):
    """复用 test_family_governor 的引擎构建模式。"""
    from core.pm_engine import PMEngine
    (project_root / ".fenix").mkdir(parents=True, exist_ok=True)
    sm = StateMachine(project_root / ".fenix" / "STATE.md", logger)
    engine = PMEngine(sm, MagicMock(), config or {}, project_root, logger)
    engine.handle_event = MagicMock()
    return engine, sm


# ═══════════════════════════════════════════════════════════════════
# Task 1.1: _same_root_siblings / _sibling_repair_active
# ═══════════════════════════════════════════════════════════════════

class TestSameRootSiblings(unittest.TestCase):
    """_same_root_siblings 返回同根非终态兄弟列表（排除自身）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.logger = MagicMock()
        self.engine, self.sm = _mk_engine(self.project_root, self.logger)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_non_fix_spec_returns_empty(self):
        """非 fix spec 无兄弟。"""
        self.assertEqual(self.engine._family._same_root_siblings("my-spec"), [])

    def test_same_root_siblings_excludes_self(self):
        """返回列表不含自身。"""
        self.sm.add_spec("fix-x", {"status": "ready"})
        self.sm.add_spec("fix-fix-x", {"status": "ready"})
        siblings = self.engine._family._same_root_siblings("fix-x")
        self.assertIn("fix-fix-x", siblings)
        self.assertNotIn("fix-x", siblings)

    def test_excludes_terminal_siblings(self):
        """终态兄弟不计入。"""
        self.sm.add_spec("fix-x", {"status": "ready"})
        self.sm.add_spec("fix-fix-x", {"status": "done"})
        siblings = self.engine._family._same_root_siblings("fix-x")
        self.assertEqual(siblings, [])

    def test_includes_non_terminal_siblings(self):
        """非终态兄弟均计入（implementing / testing / ready / bug-found / blocked）。"""
        self.sm.add_spec("fix-x", {"status": "ready"})
        self.sm.add_spec("fix-fix-x", {"status": "implementing"})
        self.sm.add_spec("fix-fix-fix-x", {"status": "testing"})
        siblings = self.engine._family._same_root_siblings("fix-x")
        self.assertIn("fix-fix-x", siblings)
        self.assertIn("fix-fix-fix-x", siblings)

    def test_different_root_not_included(self):
        """不同根的 fix spec 不计入。"""
        self.sm.add_spec("fix-x", {"status": "ready"})
        self.sm.add_spec("fix-y", {"status": "ready"})
        siblings = self.engine._family._same_root_siblings("fix-x")
        self.assertNotIn("fix-y", siblings)


class TestSiblingRepairActive(unittest.TestCase):
    """_sibling_repair_active 判定同根兄弟是否存在 actionable 修复活动。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.logger = MagicMock()
        self.engine, self.sm = _mk_engine(self.project_root, self.logger)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_implementing_sibling_is_active(self):
        """implementing 状态的兄弟视为 actionable。"""
        self.sm.add_spec("fix-x", {"status": "ready"})
        self.sm.add_spec("fix-fix-x", {"status": "implementing"})
        carrier = self.engine._family._sibling_repair_active("fix-x")
        self.assertEqual(carrier, "fix-fix-x")

    def test_ready_sibling_with_queue_entry_is_active(self):
        """ready 且队列含实现器条目的兄弟视为 actionable。"""
        self.sm.add_spec("fix-x", {"status": "ready"})
        self.sm.add_spec("fix-fix-x", {"status": "ready"})
        # 手动入队
        self.engine._dispatcher._enqueue("fix-fix-x", "implementer")
        carrier = self.engine._family._sibling_repair_active("fix-x")
        self.assertEqual(carrier, "fix-fix-x")

    def test_ready_sibling_without_queue_not_active(self):
        """ready 但无队列条目、无存活 agent 的兄弟不视为 actionable（防僵死 ready）。"""
        self.sm.add_spec("fix-x", {"status": "ready"})
        self.sm.add_spec("fix-fix-x", {"status": "ready"})
        # 不入队，且存活探测显式关闭（MagicMock 默认 truthy 会误判活跃）
        with patch.object(self.engine, "_sibling_has_live_agent", return_value=False):
            carrier = self.engine._family._sibling_repair_active("fix-x")
        self.assertEqual(carrier, "")

    def test_no_siblings_returns_empty(self):
        """无兄弟时返回空串。"""
        self.sm.add_spec("fix-x", {"status": "ready"})
        carrier = self.engine._family._sibling_repair_active("fix-x")
        self.assertEqual(carrier, "")


# ═══════════════════════════════════════════════════════════════════
# Task 1.2: _is_fix_spec / _has_non_terminal_child_fix
# ═══════════════════════════════════════════════════════════════════

class TestIsFixSpec(unittest.TestCase):
    """_is_fix_spec 判定 fix- 前缀。"""

    def test_fix_spec(self):
        from core.pm_engine import PMEngine
        self.assertTrue(PMEngine._is_fix_spec("fix-x"))
        self.assertTrue(PMEngine._is_fix_spec("fix-fix-x"))

    def test_non_fix_spec(self):
        from core.pm_engine import PMEngine
        self.assertFalse(PMEngine._is_fix_spec("my-spec"))
        self.assertFalse(PMEngine._is_fix_spec("x-fix"))
        self.assertFalse(PMEngine._is_fix_spec(""))
        self.assertFalse(PMEngine._is_fix_spec(None))


class TestHasNonTerminalChildFix(unittest.TestCase):
    """_has_non_terminal_child_fix 判定同根子 fix 是否存在非终态。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.logger = MagicMock()
        self.engine, self.sm = _mk_engine(self.project_root, self.logger)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_no_child_fix_returns_empty(self):
        """无子 fix 时返回空串。"""
        self.sm.add_spec("fix-x", {"status": "ready"})
        self.assertEqual(self.engine._family._has_non_terminal_child_fix("fix-x"), "")

    def test_terminal_child_returns_empty(self):
        """子 fix 已终态时返回空串（解封）。"""
        self.sm.add_spec("fix-x", {"status": "bug-found"})
        self.sm.add_spec("fix-fix-x", {"status": "done"})
        self.assertEqual(self.engine._family._has_non_terminal_child_fix("fix-x"), "")

    def test_non_terminal_child_returns_name(self):
        """非终态子 fix 存在时返回其名称。"""
        self.sm.add_spec("fix-x", {"status": "bug-found"})
        self.sm.add_spec("fix-fix-x", {"status": "ready"})
        self.assertEqual(self.engine._family._has_non_terminal_child_fix("fix-x"), "fix-fix-x")

    def test_deeper_non_terminal_child(self):
        """更深层非终态子 fix 优先返回。"""
        self.sm.add_spec("fix-x", {"status": "bug-found"})
        self.sm.add_spec("fix-fix-x", {"status": "done"})
        self.sm.add_spec("fix-fix-fix-x", {"status": "implementing"})
        self.assertEqual(self.engine._family._has_non_terminal_child_fix("fix-x"), "fix-fix-fix-x")


# ═══════════════════════════════════════════════════════════════════
# Task 2.1: 守卫一 — _do_spec_bug_found reset 抑制
# ═══════════════════════════════════════════════════════════════════

class TestGuardOneResetSuppression(unittest.TestCase):
    """守卫一：fix spec 有非终态子 fix 时抑制 reset，保持 bug-found。

    add-bug-repair-mode-config：守卫一在 derive 模式（admin.bug_repair_mode=derive）
    下生效；inplace（缺省）下 fix-* 名字 SPEC 同样原地打回、不派生。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.logger = MagicMock()
        self.engine, self.sm = _mk_engine(
            self.project_root, self.logger,
            config={"admin": {"bug_repair_mode": "derive"}},
        )
        self.engine._enqueue = MagicMock()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_suppresses_reset_when_child_fix_active(self):
        """Scenario: 有非终态子 fix 时重置被抑制。"""
        # fix-fix-x 已存在且非终态
        self.sm.add_spec("fix-x", {"status": "bug-found"})
        self.sm.add_spec("fix-fix-x", {"status": "ready"})
        # 重触发 fix-x 的 bug-found → 应被抑制
        self.engine._family._do_spec_bug_found("fix-x")
        # fix-x 保持 bug-found，不被重置为 ready
        entry = self.sm.read_one("fix-x")
        self.assertEqual(entry["status"], "bug-found")
        self.assertIn("子 fix", entry.get("error", ""))

    def test_no_suppression_when_child_terminal(self):
        """Scenario: 子终态后解封——守卫不生效，照常派发新修复。

        fix-x 仍处 bug-found（守卫只抑制 reset，不重置父态）；
        因子 fix-fix-x 已 done，_resolve_fix_spec_name 递归生成更深一层
        fix-fix-fix-x 作为本轮新修复承载方。
        """
        self.sm.add_spec("fix-x", {"status": "bug-found"})
        self.sm.add_spec("fix-fix-x", {"status": "done"})
        self.engine._family._do_spec_bug_found("fix-x")
        # 守卫一不生效（子已终态）→ 派生新的更深层 fix 承载方
        new_child = self.sm.read_one("fix-fix-fix-x")
        self.assertIsNotNone(new_child)
        self.assertEqual(new_child["status"], "ready")
        # 父保持 bug-found（reset 抑制守卫只拦重实现，不触及父态）
        self.assertEqual(self.sm.read_one("fix-x")["status"], "bug-found")


# ═══════════════════════════════════════════════════════════════════
# Task 2.2: 守卫二 — judge spawn 抑制
# ═══════════════════════════════════════════════════════════════════

class TestGuardTwoSpawnSuppression(unittest.TestCase):
    """守卫二：fix spec ready/implementing 时跳过派生子 fix。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.logger = MagicMock()
        self.engine, self.sm = _mk_engine(self.project_root, self.logger)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_no_suppression_when_not_fix_spec(self):
        """非 fix spec 不触发守卫二。"""
        self.sm.add_spec("my-spec", {"status": "testing"})
        self.assertFalse(self.engine._family._is_fix_spec("my-spec"))


# ═══════════════════════════════════════════════════════════════════
# Task 2.3: 守卫三 — 派发级同根互斥
# ═══════════════════════════════════════════════════════════════════

class TestGuardThreeDispatchMutex(unittest.TestCase):
    """守卫三：同根兄弟存在活跃修复时跳过派发。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.logger = MagicMock()
        self.engine, self.sm = _mk_engine(self.project_root, self.logger)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_dispatch_only_when_no_active_sibling(self):
        """同根无活跃兄弟时正常派发。"""
        self.sm.add_spec("fix-x", {"status": "ready"})
        self.sm.add_spec("fix-fix-x", {"status": "done"})
        carrier = self.engine._family._sibling_repair_active("fix-x")
        self.assertEqual(carrier, "")


# ═══════════════════════════════════════════════════════════════════
# 守卫三死锁修复：先到先得裁决 + 被抑制条目不阻塞后队
# （2026-08-28 队列头死锁实证：双 ready 同根兄弟互相判对方 actionable，
#   守卫三 pop→insert 回队首→return，队首之后全部条目无法派发）
# ═══════════════════════════════════════════════════════════════════

class TestSiblingRepairActiveFcfs(unittest.TestCase):
    """守卫三先到先得裁决：批量入队现场由先入队者承载，后到者自我抑制。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.logger = MagicMock()
        self.engine, self.sm = _mk_engine(self.project_root, self.logger)
        # 入队时刻来自 time.time()；真实调度下两次 _enqueue 可能落在同一
        # mtime 粒度内，导致先到先得裁决不稳定。注入确定性递增时钟替代
        # 测试内 time.sleep(0.01) 分隔（sleep 既是慢又是 flaky 源）。
        import core.pm_engine.dispatch as _dispatch_mod
        clock = {"t": 1_000_000.0}
        def _tick():
            clock["t"] += 1.0
            return clock["t"]
        self._clock_patch = patch.object(
            _dispatch_mod.time, "time", _tick)
        self._clock_patch.start()

    def tearDown(self):
        self._clock_patch.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _entry_ts(self, spec_name):
        """取队列中该 spec 实现器条目的入队时刻。"""
        entry = next(
            e for e in self.engine._dispatcher._run_queue
            if e[1] == spec_name and e[2] == "implementer"
        )
        return entry[3]

    def test_older_sibling_entry_carries(self):
        """兄弟条目先入队 → 兄弟承载，我方被抑制（先到先得）。"""
        self.sm.add_spec("fix-x", {"status": "ready"})
        self.sm.add_spec("fix-fix-x", {"status": "ready"})
        self.engine._dispatcher._enqueue("fix-fix-x", "implementer")
        self.engine._dispatcher._enqueue("fix-x", "implementer")
        carrier = self.engine._sibling_repair_active(
            "fix-x", my_enqueued_at=self._entry_ts("fix-x")
        )
        self.assertEqual(carrier, "fix-fix-x")

    def test_newer_sibling_entry_does_not_block_me(self):
        """我方条目先入队 → 由我承载；兄弟仅凭更新条目不计 actionable。"""
        self.sm.add_spec("fix-x", {"status": "ready"})
        self.sm.add_spec("fix-fix-x", {"status": "ready"})
        self.engine._dispatcher._enqueue("fix-x", "implementer")
        self.engine._dispatcher._enqueue("fix-fix-x", "implementer")
        with patch.object(self.engine, "_sibling_has_live_agent", return_value=False):
            carrier = self.engine._sibling_repair_active(
                "fix-x", my_enqueued_at=self._entry_ts("fix-x")
            )
        self.assertEqual(carrier, "")

    def test_none_keeps_legacy_judgment(self):
        """非派发路径（my_enqueued_at=None）保持原判：兄弟 ready+条目即 actionable。"""
        self.sm.add_spec("fix-x", {"status": "ready"})
        self.sm.add_spec("fix-fix-x", {"status": "ready"})
        self.engine._dispatcher._enqueue("fix-fix-x", "implementer")
        self.engine._dispatcher._enqueue("fix-x", "implementer")
        carrier = self.engine._family._sibling_repair_active("fix-x")
        self.assertEqual(carrier, "fix-fix-x")


class TestGuardThreeNoQueueHeadBlocking(unittest.TestCase):
    """守卫三被抑制条目不得阻塞其后条目（队列头死锁回归测试）。"""

    def setUp(self):
        import threading as _threading

        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.logger = MagicMock()
        self.sm = MagicMock()
        self.agent_runner = MagicMock()
        self.config = {"agents": {"max_concurrent": 2}}
        self.engine = PMEngine(
            self.sm, self.agent_runner, self.config,
            self.project_root, self.logger,
        )
        # add-spec-content-integrity-gate（bb9de76c）接入 dispatch 后同层新增的
        # 派发前闸门：本类只验守卫三/队首不阻塞，内容维度按「有内容」放行
        # （c6d5924c 对调度测试替身的同款补桩处方）。漏桩时：empty tmpdir +
        # 恒 ready 替身触发闸门 → 摘除条目回队首 → 死循环挂起。
        self.engine._check_spec_content_missing = lambda n: False
        self._threading = _threading
        self.dispatched = []
        self._orig_thread_start = _threading.Thread.start

        def fake_start(thread_self):
            if not thread_self.name.startswith("fenix-"):
                self._orig_thread_start(thread_self)
                return
            self.dispatched.append(thread_self.name)

        _threading.Thread.start = fake_start

    def tearDown(self):
        self._threading.Thread.start = self._orig_thread_start
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_suppressed_head_does_not_block_following_entry(self):
        """队首 fix spec 被守卫三抑制时，其后的合法条目仍应派发。"""
        specs = {
            "fix-head": {"status": "ready", "priority": 6},
            "spec-next": {"status": "ready", "priority": 6},
        }
        self.sm.read_one = MagicMock(side_effect=lambda n: specs.get(n))
        self.sm.transition = MagicMock(return_value=True)
        # fix-head 同根兄弟存在活跃修复 → 守卫三抑制
        with patch.object(
            self.engine, "_sibling_repair_active", return_value="fix-head-fix"
        ):
            self.engine._enqueue("fix-head", "implementer")
            self.engine._enqueue("spec-next", "implementer")
            self.engine._process_queue()

        names = [n.split("-", 2)[2] for n in self.dispatched]
        # fix-head 被抑制不派发，spec-next 不被队首拖死
        self.assertNotIn("fix-head", names)
        self.assertIn("spec-next", names)
        # fix-head 保持 queued（后到抑制，不丢条目）
        queued_specs = [e[1] for e in self.engine._dispatcher._run_queue]
        self.assertIn("fix-head", queued_specs)

    def test_fcfs_sibling_pair_resolves_by_enqueue_order(self):
        """双 ready 同根兄弟批量入队：先入队者派发，后入队者被抑制且不阻塞后队。"""
        specs = {
            "fix-a": {"status": "ready", "priority": 6},
            "fix-fix-a": {"status": "ready", "priority": 7},
            "spec-b": {"status": "ready", "priority": 6},
        }
        self.sm.read_one = MagicMock(side_effect=lambda n: specs.get(n))
        self.sm.transition = MagicMock(return_value=True)
        # 不 mock _sibling_repair_active：真实判定路径（含先到先得裁决）
        self.engine._enqueue("fix-a", "implementer")       # 先入队（P6 载体）
        self.engine._enqueue("fix-fix-a", "implementer")   # 后入队
        self.engine._enqueue("spec-b", "implementer")
        self.engine._process_queue()

        names = [n.split("-", 2)[2] for n in self.dispatched]
        self.assertIn("fix-a", names)          # 先到者胜出
        self.assertNotIn("fix-fix-a", names)   # 后到者抑制
        self.assertIn("spec-b", names)         # 后队不被拖死


# ═══════════════════════════════════════════════════════════════════
# 零行为差异回退保证
# ═══════════════════════════════════════════════════════════════════

class TestZeroBehaviorDiffFallback(unittest.TestCase):
    """守卫在无子无在飞的正常路径不生效。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.logger = MagicMock()
        self.engine, self.sm = _mk_engine(self.project_root, self.logger)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_normal_spec_unaffected(self):
        """Scenario: 非 fix 父 SPEC 走原地打回（add-inplace-bug-repair）。"""
        self.sm.add_spec("my-spec", {"status": "bug-found"})
        # 正常 bug-found（非 fix 父）：原地打回，不派生 fix-my-spec
        self.engine._family._do_spec_bug_found("my-spec")
        fix_entry = self.sm.read_one("fix-my-spec")
        self.assertIsNone(fix_entry)
        # 父 SPEC 重置为 implementing 并递增计数器
        parent = self.sm.read_one("my-spec")
        self.assertEqual(parent["status"], "implementing")
        self.assertEqual(int(parent.get("_verify_fail_rounds", 0)), 1)

    def test_fix_spec_no_child_unaffected(self):
        """fix spec 无子时重置行为不变（derive 模式下派生闭环生效）。"""
        # 独立引擎：显式 derive，fix-* 名字 SPEC 无子 → 递归派生 fix-fix-x
        engine, sm = _mk_engine(
            self.project_root, self.logger,
            config={"admin": {"bug_repair_mode": "derive"}},
        )
        engine._enqueue = MagicMock()
        sm.add_spec("fix-x", {"status": "bug-found"})
        engine._family._do_spec_bug_found("fix-x")
        # 无子 → 守卫一不生效；_resolve_fix_spec_name 递归生成 fix-fix-x 作为新承载方
        new_child = sm.read_one("fix-fix-x")
        self.assertIsNotNone(new_child)
        self.assertEqual(new_child["status"], "ready")
        # 父保持 bug-found（reset 抑制守卫只拦重实现，不重置父态）
        self.assertEqual(sm.read_one("fix-x")["status"], "bug-found")

    def test_sibling_repair_active_empty_for_non_fix(self):
        """非 fix spec 同根兄弟无活跃修复。"""
        self.assertEqual(self.engine._sibling_repair_active("my-spec"), "")


if __name__ == "__main__":
    unittest.main()
