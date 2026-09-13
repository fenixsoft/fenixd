"""
Tests for StateMachine functionality.

Split from test_core.py as part of refactor-test-structure.
"""
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import StateMachine, StateParser, SpecStatus, VALID_TRANSITIONS, GATE_TRANSITIONS


class TestStateParser(unittest.TestCase):
    """Test STATE.md parsing and serialization."""

    def test_parse_single_spec(self):
        content = """# Fenix Project State
## Specs

### add-login
- status: ready
- priority: 1
- created: 2026-08-10T14:00:00+08:00
- updated: 2026-08-11T09:00:00+08:00
- implementer_run: null
- tester_run: null
- branch: null
- error: null
"""
        result = StateParser._parse_content(content)
        self.assertIn("add-login", result)
        self.assertEqual(result["add-login"]["status"], "ready")
        self.assertEqual(result["add-login"]["priority"], 1)
        self.assertIsNone(result["add-login"]["error"])

    def test_parse_multiple_specs(self):
        content = """## Specs

### spec-a
- status: ready
- priority: 1
- created: 2026-01-01T00:00:00Z
- updated: 2026-01-01T00:00:00Z
- implementer_run: null
- tester_run: null
- branch: null
- error: null

### spec-b
- status: done
- priority: 2
- created: 2026-01-02T00:00:00Z
- updated: 2026-01-02T00:00:00Z
- implementer_run: run-001
- tester_run: run-002
- branch: fenix/spec-b
- error: null
"""
        result = StateParser._parse_content(content)
        self.assertEqual(len(result), 2)
        self.assertEqual(result["spec-a"]["status"], "ready")
        self.assertEqual(result["spec-b"]["status"], "done")
        self.assertEqual(result["spec-b"]["branch"], "fenix/spec-b")

    def test_parse_empty_content(self):
        result = StateParser._parse_content("## Specs\n")
        self.assertEqual(result, {})

    def test_parse_null_values(self):
        content = """### test-spec
- status: ready
- priority: 1
- created: 2026-01-01T00:00:00Z
- updated: 2026-01-01T00:00:00Z
- implementer_run: None
- tester_run: null
- branch: none
- error: null
"""
        result = StateParser._parse_content(content)
        self.assertIsNone(result["test-spec"]["implementer_run"])
        self.assertIsNone(result["test-spec"]["tester_run"])

    def test_serialize_roundtrip(self):
        specs = {
            "test-spec": {
                "status": "ready",
                "priority": 3,
                "created": "2026-01-01T00:00:00Z",
                "updated": "2026-01-01T00:00:00Z",
                "implementer_run": None,
                "tester_run": None,
                "branch": None,
                "error": None,
            }
        }
        serialized = StateParser.serialize(specs)
        parsed = StateParser._parse_content(serialized)
        self.assertIn("test-spec", parsed)
        self.assertEqual(parsed["test-spec"]["status"], "ready")
        self.assertEqual(parsed["test-spec"]["priority"], 3)


class TestStateParserTotalDuration(unittest.TestCase):
    """add-done-duration-persist 1.2：total_duration 序列化白名单往返。"""

    def test_roundtrip_preserves_total_duration(self):
        """含 total_duration 的条目经 serialize/parse 往返后字段值保持。"""
        specs = {
            "spec-with-duration": {
                "status": "done",
                "priority": 1,
                "created": "2026-01-01T00:00:00Z",
                "updated": "2026-01-01T00:00:00Z",
                "implementer_run": None,
                "tester_run": None,
                "branch": None,
                "error": None,
                "depends_on": None,
                "total_duration": 150,
            }
        }
        serialized = StateParser.serialize(specs)
        self.assertIn("- total_duration: 150", serialized)
        parsed = StateParser._parse_content(serialized)
        self.assertIn("spec-with-duration", parsed)
        self.assertEqual(str(parsed["spec-with-duration"]["total_duration"]), "150")

    def test_missing_field_serialized_as_null(self):
        """不含该字段的存量条目序列化为 `- total_duration: null`，与可空字段一致。"""
        specs = {
            "legacy-spec": {
                "status": "pushed",
                "priority": 1,
                "created": "2026-01-01T00:00:00Z",
                "updated": "2026-01-01T00:00:00Z",
            }
        }
        serialized = StateParser.serialize(specs)
        self.assertIn("- total_duration: null", serialized)
        parsed = StateParser._parse_content(serialized)
        self.assertIsNone(parsed["legacy-spec"]["total_duration"])


class TestStateParserHalfWriteDefense(unittest.TestCase):
    """1.1 半写 STATE.md 读取防御——锁定「解析层不得产出字符串条目」契约。

    背景点位：若 read_all 返回值含字符串形态条目，full_scan recovery 循环
    ``entry.get('status')``（core/event_bus.py）即抛 AttributeError、整轮扫描
    中止——故解析层契约被回归破坏时，下游读取端必须有归一防线（下两方法）。
    """

    def test_half_written_state_md_parse_no_crash(self):
        """半身写 STATE.md 不得引发异常；合法条目仍可被正确读取。"""
        content = """# Fenix Project State
## Specs

### valid-spec
- status: ready
- priority: 1
- created: 2026-01-01T00:00:00Z
- updated: 2026-01-01T00:00:00Z
- implementer_run: null
- tester_run: null
- branch: null
- error: null

### half-written-spec
- status: implementing
- priority: 2
- created: 2026-08-27T14:0
### another-valid
"""
        result = StateParser._parse_content(content)
        self.assertIn("valid-spec", result)
        self.assertEqual(result["valid-spec"]["status"], "ready")
        # 半写条目缺 updated/run 字段等，但绝不得以字符串形态进入返回值
        for name, entry in result.items():
            self.assertIsInstance(entry, dict, f"条目 {name} 不得以字符串形态返回")
            self.assertIn("status", entry)

    def test_read_all_normalizes_string_entry(self):
        """1.2 防御契约：read_all 返回值中不得出现非 dict 条目。"""
        sm = StateMachine(Path(tempfile.mkdtemp()) / ".fenix" / "STATE.md", MagicMock())
        # 模拟解析层被回归破坏、混入字符串条目的情形
        sm._raw_override = {
            "good": {"status": "ready", "error": None, "implementer_run": None},
            "bad": "### bad\n- status: ready\n",
            "also_bad": ["not", "a", "dict"],
        }
        original_parse = StateParser.parse

        def _fake_parse(path):
            return sm._raw_override

        try:
            StateParser.parse = staticmethod(_fake_parse)
            result = sm.read_all()
        finally:
            StateParser.parse = staticmethod(original_parse)

        self.assertIn("good", result)
        self.assertIsInstance(result["good"], dict)
        # 字符串与列表形态条目被剔除，不得外泄到下游消费点
        self.assertNotIn("bad", result)
        self.assertNotIn("also_bad", result)
        for name, entry in result.items():
            self.assertIsInstance(entry, dict, f"条目 {name} 不得以非 dict 形态返回")


class TestStateMachine(unittest.TestCase):
    """Test state machine transitions and operations."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_add_spec(self):
        self.assertTrue(self.sm.add_spec("test-spec", {"priority": 1}))
        spec = self.sm.read_one("test-spec")
        self.assertEqual(spec["status"], "drafted")
        self.assertEqual(spec["priority"], 1)

    def test_add_duplicate_spec(self):
        self.sm.add_spec("test-spec", {})
        self.assertFalse(self.sm.add_spec("test-spec", {}))

    def test_valid_transitions(self):
        self.sm.add_spec("test-spec", {"priority": 1})

        # drafted → ready (auto-review)
        self.assertTrue(self.sm.transition("test-spec", "ready"))
        self.assertEqual(self.sm.read_one("test-spec")["status"], "ready")

        # ready → implementing
        self.assertTrue(self.sm.transition("test-spec", "implementing"))

        # implementing → implemented
        self.assertTrue(self.sm.transition("test-spec", "implemented"))

        # implemented → testing
        self.assertTrue(self.sm.transition("test-spec", "testing"))

        # testing → verified
        self.assertTrue(self.sm.transition("test-spec", "verified"))

        # verified → done
        self.assertTrue(self.sm.transition("test-spec", "done"))

        # done → pushed (terminal)
        self.assertTrue(self.sm.transition("test-spec", "pushed"))

    def test_invalid_transition_rejected(self):
        self.sm.add_spec("test-spec", {})
        # drafted → implementing is invalid (must go through ready)
        self.assertFalse(self.sm.transition("test-spec", "implementing"))
        self.assertEqual(self.sm.read_one("test-spec")["status"], "drafted")

    def test_is_valid_transition(self):
        self.assertTrue(self.sm.is_valid_transition("drafted", "ready"))
        self.assertFalse(self.sm.is_valid_transition("drafted", "implementing"))
        self.assertFalse(self.sm.is_valid_transition("pushed", "done"))  # terminal

    def test_get_by_status(self):
        self.sm.add_spec("spec-a", {"priority": 1, "status": "ready"})
        self.sm.add_spec("spec-b", {"priority": 3, "status": "ready"})
        self.sm.add_spec("spec-c", {"priority": 2, "status": "done"})

        ready = self.sm.get_by_status("ready")
        self.assertEqual(len(ready), 2)
        # spec-a has priority 1, should be first
        self.assertEqual(ready[0][0], "spec-a")
        self.assertEqual(ready[1][0], "spec-b")

    def test_get_next_ready(self):
        self.sm.add_spec("low-prio", {"priority": 5, "status": "ready"})
        self.sm.add_spec("high-prio", {"priority": 1, "status": "ready"})

        next_spec = self.sm.get_next_ready()
        self.assertIsNotNone(next_spec)
        self.assertEqual(next_spec[0], "high-prio")

    def test_get_next_ready_empty(self):
        self.assertIsNone(self.sm.get_next_ready())

    def test_recover_interrupted(self):
        """恢复目标按中断态区分：implementing→ready 重实现；testing→implemented 重验证。

        testing 重置 ready 会误派 implementer 从头实现已合并代码并劫持
        branch（2026-09-04 help-center 误派实证：pushed 记录被写成 rogue 分支）。
        """
        self.sm.add_spec("stuck-impl", {"status": "implementing",
                                        "branch": "fenix/impl-branch"})
        self.sm.add_spec("stuck-test", {"status": "testing",
                                        "branch": "fenix/impl-branch",
                                        "tester_run": "planner-plan-x-a1"})
        self.sm.add_spec("normal", {"status": "done"})

        recovered = self.sm.recover_interrupted()
        self.assertEqual(len(recovered), 2)
        self.assertIn("stuck-impl", recovered)
        self.assertIn("stuck-test", recovered)

        # 实现中断 → ready 重派 implementer（branch 清空，原语义）
        impl = self.sm.read_one("stuck-impl")
        self.assertEqual(impl["status"], "ready")
        self.assertIsNone(impl["branch"])
        # 验证中断 → implemented 重派 verifier（branch 保留，清 tester_run）
        test = self.sm.read_one("stuck-test")
        self.assertEqual(test["status"], "implemented")
        self.assertEqual(test["branch"], "fenix/impl-branch",
                         "验证中断不得劫持 branch 字段")
        self.assertIsNone(test["tester_run"])
        # Normal spec unchanged
        self.assertEqual(self.sm.read_one("normal")["status"], "done")

    def test_update_spec(self):
        self.sm.add_spec("test-spec", {})
        self.assertTrue(self.sm.update_spec("test-spec", {"priority": 1, "branch": "fenix/test"}))
        spec = self.sm.read_one("test-spec")
        self.assertEqual(spec["priority"], 1)
        self.assertEqual(spec["branch"], "fenix/test")

    def test_update_nonexistent(self):
        self.assertFalse(self.sm.update_spec("nonexistent", {"status": "ready"}))

    def test_transition_nonexistent(self):
        self.assertFalse(self.sm.transition("nonexistent", "ready"))

    def test_remove_spec(self):
        self.sm.add_spec("to-remove", {"priority": 2})
        self.sm.add_spec("keep", {"priority": 3})
        self.assertTrue(self.sm.remove_spec("to-remove"))
        self.assertIsNone(self.sm.read_one("to-remove"))
        # Other specs must remain intact after atomic rewrite
        self.assertEqual(self.sm.read_one("keep")["priority"], 3)
        # State file no longer contains the removed header
        self.assertNotIn("to-remove", self.state_path.read_text(encoding="utf-8"))

    def test_remove_nonexistent(self):
        # With an existing STATE.md, removing an absent entry leaves the file intact.
        self.sm.add_spec("present", {"priority": 1})
        self.assertFalse(self.sm.remove_spec("does-not-exist"))
        self.assertTrue(self.state_path.exists())
        self.assertEqual(self.sm.read_one("present")["priority"], 1)
        # With no STATE.md at all, the call is still a safe no-op returning False.
        empty_dir = tempfile.mkdtemp()
        fresh_sm = StateMachine(Path(empty_dir) / ".fenix" / "STATE.md", MagicMock())
        self.assertFalse(fresh_sm.remove_spec("absent"))
        self.assertFalse((Path(empty_dir) / ".fenix" / "STATE.md").exists())
        shutil.rmtree(empty_dir, ignore_errors=True)

    def test_priority_sorting_same_priority(self):
        """Same priority uses created time (earlier first)."""
        self.sm.add_spec("later", {"priority": 3, "created": "2026-02-01T00:00:00Z", "status": "ready"})
        self.sm.add_spec("earlier", {"priority": 3, "created": "2026-01-01T00:00:00Z", "status": "ready"})

        ready = self.sm.get_ready_specs()
        self.assertEqual(ready[0][0], "earlier")
        self.assertEqual(ready[1][0], "later")

    def test_bug_found_path(self):
        """Test the bug-found transition path."""
        self.sm.add_spec("buggy", {"priority": 1})
        self.sm.transition("buggy", "ready")
        self.sm.transition("buggy", "implementing")
        self.sm.transition("buggy", "implemented")
        self.sm.transition("buggy", "testing")
        self.sm.transition("buggy", "bug-found")
        self.assertEqual(self.sm.read_one("buggy")["status"], "bug-found")
        # bug-found → implementing (retry)
        self.assertTrue(self.sm.transition("buggy", "implementing"))


class TestSpecStatus(unittest.TestCase):
    """Test status constants and transition definitions."""

    def test_all_statuses_defined(self):
        self.assertEqual(len(SpecStatus.ALL), 11)

    def test_valid_transitions_cover_all_states(self):
        for status in SpecStatus.ALL:
            self.assertIn(status, VALID_TRANSITIONS)

    def test_pushed_is_terminal(self):
        self.assertEqual(VALID_TRANSITIONS["pushed"], [])

    def test_implementing_can_revert(self):
        self.assertIn("ready", VALID_TRANSITIONS["implementing"])


class TestSpecReviewGateStateMachine(unittest.TestCase):
    """add-spec-review-gate 7.1：reviewing 状态、四条新转移边与中断回退。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_reviewing_in_status_enum_and_all(self):
        """REVIEWING 是第 11 个状态且纳入 ALL（枚举总数 11）。"""
        self.assertEqual(SpecStatus.REVIEWING, "reviewing")
        self.assertIn(SpecStatus.REVIEWING, SpecStatus.ALL)
        self.assertEqual(len(SpecStatus.ALL), 11)

    def test_four_new_transition_edges_valid(self):
        """四条新转移边合法：drafted→reviewing、reviewing→ready、
        reviewing→blocked、blocked→reviewing。"""
        self.assertTrue(self.sm.is_valid_transition("drafted", "reviewing"))
        self.assertTrue(self.sm.is_valid_transition("reviewing", "ready"))
        self.assertTrue(self.sm.is_valid_transition("reviewing", "blocked"))
        self.assertTrue(self.sm.is_valid_transition("blocked", "reviewing"))
        # 既有边保留：drafted→ready、blocked→ready
        self.assertTrue(self.sm.is_valid_transition("drafted", "ready"))
        self.assertTrue(self.sm.is_valid_transition("blocked", "ready"))

    def test_illegal_reviewing_edges_rejected(self):
        """非法边拒绝：reviewing 不可直通 implementing/verified，ready 不可
        反向回 reviewing（评审门只在 drafted→ready 之间存在）。"""
        self.assertFalse(self.sm.is_valid_transition("reviewing", "implementing"))
        self.assertFalse(self.sm.is_valid_transition("reviewing", "verified"))
        self.assertFalse(self.sm.is_valid_transition("ready", "reviewing"))
        self.assertFalse(self.sm.is_valid_transition("implementing", "reviewing"))

    def test_gate_transitions_exclude_reviewing(self):
        """GATE_TRANSITIONS（门禁逃生门）MUST NOT 纳入 reviewing——
        人工恢复路径不得走门禁边。"""
        self.assertNotIn("reviewing", GATE_TRANSITIONS)
        # reviewing 的出边仅走 VALID_TRANSITIONS（ready/blocked），
        # 不享有 verified→testing / blocked→testing 的门禁逃生边
        self.assertFalse(self.sm.is_valid_transition("reviewing", "testing"))
        self.assertNotIn("reviewing", VALID_TRANSITIONS["testing"])

    def test_reviewing_interrupted_reverts_to_drafted(self):
        """reviewing 为中断态：recover_interrupted 回退 drafted、清空
        reviewer_run 与 _review_attempts，重走晋升链。"""
        self.sm.add_spec("in-review", {
            "status": "reviewing",
            "reviewer_run": "spec-review-demo-abc123",
            "_review_attempts": 1,
        })
        recovered = self.sm.recover_interrupted()
        self.assertIn("in-review", recovered)
        entry = self.sm.read_one("in-review")
        self.assertEqual(entry["status"], "drafted")
        self.assertIsNone(entry["reviewer_run"])
        self.assertEqual(str(entry["_review_attempts"]), "0")

    def test_reviewing_not_reverted_to_ready(self):
        """reviewing 不得被当作 implementing 回退 ready（评审门在 drafted 链
        上，回退必须回到链首 drafted）。"""
        self.sm.add_spec("in-review", {
            "status": "reviewing",
            "reviewer_run": "spec-review-demo-abc123",
        })
        self.sm.recover_interrupted()
        self.assertEqual(self.sm.read_one("in-review")["status"], "drafted")

    def test_reviewer_run_serialized_in_whitelist(self):
        """reviewer_run 字段纳入序列化白名单：update_spec 写入后可读回。"""
        self.sm.add_spec("demo", {"status": "reviewing"})
        self.assertTrue(self.sm.update_spec("demo", {"reviewer_run": "spec-review-demo-x"}))
        self.assertEqual(self.sm.read_one("demo")["reviewer_run"], "spec-review-demo-x")

    def test_frozen_reviewing_blocked_protected(self):
        """冻结保护对评审状态同样生效：冻结期剥离对 status 的改写（任务 1.3）。"""
        self.sm.add_spec("frozen-review", {"status": "blocked", "frozen": True})
        # 冻结期 update_spec 携带 status 的改写被剥离（status 保持 blocked）
        self.sm.update_spec("frozen-review", {"status": "reviewing"})
        self.assertEqual(self.sm.read_one("frozen-review")["status"], "blocked")


class TestVerifiedTestingEscapeHatch(unittest.TestCase):
    """D7: VERIFIED→TESTING 逃生门（仅门禁自动路径，人工路径仍拒）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        self.sm.add_spec("demo", {"status": "verified",
                                  "implementer_run": "impl-1",
                                  "tester_run": "verify-1"})

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_gate_transition_verified_to_testing_allowed(self):
        """门禁路径：VERIFIED→TESTING 允许。"""
        self.assertTrue(self.sm.transition_gate("demo", "testing"))
        self.assertEqual(self.sm.read_one("demo")["status"], "testing")

    def test_human_transition_verified_to_testing_rejected(self):
        """人工路径：直接调 transition 的 VERIFIED→TESTING 仍被 VALID_TRANSITIONS 拒。"""
        self.assertFalse(self.sm.transition("demo", "testing"))
        self.assertEqual(self.sm.read_one("demo")["status"], "verified")

    def test_gate_transition_preserves_implementer_run(self):
        """回退保留 implementer_run 与断点（仅改 status）。"""
        self.sm.transition_gate("demo", "testing")
        entry = self.sm.read_one("demo")
        self.assertEqual(entry["status"], "testing")
        self.assertEqual(entry["implementer_run"], "impl-1")

    def test_gate_transition_invalid_from_state_rejected(self):
        """非 verified 源态走 transition_gate 回退被拒。"""
        self.sm.update_spec("demo", {"status": "done"})
        self.assertFalse(self.sm.transition_gate("demo", "testing"))
        self.assertEqual(self.sm.read_one("demo")["status"], "done")
