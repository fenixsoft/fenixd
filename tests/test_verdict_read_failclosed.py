"""fix-verdict-read-failclosed：读侧 fail-closed 全矩阵测试（Task 2.5）。

验证三态结构化读取（VerdictReadResult）在三阶段裁决采纳处的 retry-then-block
行为，以及 legacy 路径的 fail-closed 阻断。核心保证：不可读裁决（缺失/非法 JSON/
白名单外 status）在任何路径都不得晋级 verified。

复刻事故签名：Invalid control character at: line 25 column 402（summary
字符串内裸换行致非法 JSON）——对应日志 09:13:32 Failed to read verifier result。
"""

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.pm_engine import PMEngine
from core.pm_engine.verification import VerdictReadResult
from core.state_machine import StateMachine


CORRUPT_RESULT = '{"status": "bug-found", "summary": "line1\\nline2"}'
# 裸换行（复刻 add-verify-contract-autodraft 事故签名，JSON 非法）
CORRUPT_NEWLINE_RESULT = '{"status": "bug-found", "summary": "line1\nline2"}'
# 非法 status（verdict 语义错位，如 verifier 写入非白名单 status）
UNKNOWN_STATUS_RESULT = (
    '{"status": "success", "summary": "impl ok", "role": "verifier"}')


class _FailClosedTestBase(unittest.TestCase):
    """三阶段 fail-closed 测试共用基础设施。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        self.engine = PMEngine(
            self.sm, MagicMock(), {}, Path(self.tmpdir), self.logger,
        )

        # ── spec 进入 testing（直接）──
        self.sm.add_spec("demo-spec", {"priority": 5})
        for s in ("ready", "implementing", "implemented", "testing"):
            self.sm.transition("demo-spec", s)

        # ── 基础 mock ──
        self.engine._enqueue = MagicMock()
        self.engine._on_spec_verified = MagicMock()
        self.engine._on_spec_bug_found = MagicMock()
        self.engine._task_completion_blocker = MagicMock(return_value=None)
        self.engine._ensure_verification_report = MagicMock(return_value=None)
        self.engine._env_whitewash_gate = MagicMock(return_value=True)
        self.engine._check_verification_gate = MagicMock(return_value=None)
        self.engine._apply_scenario_freeze = MagicMock(return_value={})
        self.engine._apply_interaction_contract = MagicMock(return_value=None)
        self.engine._verify_verdict_evidence = MagicMock(return_value={
            "ok": True, "cause": "pass", "violations": [], "dispatch_error": "",
        })
        self.engine._update_warning_streaks = MagicMock(return_value=[])
        self.engine._ensure_app_reachable = MagicMock(return_value=(True, False, ""))
        self.engine._send_human_escalation_alert = MagicMock()

        # ── planner-plan 始终成功（不关注 plan 成本）──
        self.engine.agent_runner.run_planner = MagicMock(
            return_value=SimpleNamespace(
                success=True, error=None,
                run_id="planner-judge-demo-spec-1-a1",
            )
        )

        # ── 冻结场景集（跳过阶段1 出题，直接阶段2/3）──
        self.verify_dir = (
            Path(self.tmpdir) / ".fenix" / "verify-progress" / "demo-spec"
        )
        self.verify_dir.mkdir(parents=True, exist_ok=True)
        (self.verify_dir / "test_scenarios.json").write_text(
            json.dumps([{
                "id": "scn-a", "description": "场景A",
                "steps": [
                    {"action": "navigate", "value": "http://localhost:8787/"},
                    {"action": "wait", "target": ".x", "description": "等待"},
                ],
                "assertions": [
                    {"type": "element_visible", "selector": ".x", "label": "可见"},
                ],
            }], ensure_ascii=False),
            encoding="utf-8")

        self._alert_calls: list = []
        self.engine._send_human_escalation_alert.side_effect = self._capture_alert

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _capture_alert(self, **kwargs):
        self._alert_calls.append(kwargs)

    def _make_fake_engine(self):
        class FakeEngine:
            def __init__(self, spec_name, project_root, logger=None,
                         config=None, scenario_root=None):
                pass
            async def run(self, scenarios):
                return {
                    "spec": "demo-spec",
                    "summary": {
                        "total": 2, "passed": 1, "failed": 1,
                        "warnings": 0, "errors": 0,
                    },
                    "scenarios": [],
                }
        return FakeEngine

    def _run_three_stage(self, fake_engine_cls=None):
        cls = fake_engine_cls or self._make_fake_engine()
        with patch("importlib.reload", lambda m: m), \
                patch("core.verify_engine.VerifyEngine", cls):
            self.engine._run_three_stage_verification("demo-spec")


class TestThreeStageRetryThenBlock(_FailClosedTestBase):
    """三阶段读侧：unreadable → 重派 judge 一次 → 二次仍坏 → blocked + 告警。"""

    def test_corrupt_json_retry_then_block(self):
        """裸换行非法 JSON（事故签名）→ 重试 → 仍坏 → blocked + 告警。"""
        self.engine._read_verdict = MagicMock(side_effect=[
            # 阶段1 已冻结复用跳过，不读 plan；下方为阶段3 reads：
            VerdictReadResult.failure(
                "parse",
                "Invalid control character at: line 25 column 402"),
            VerdictReadResult.failure(
                "parse",
                "Invalid control character at: line 25 column 402"),
        ])
        self._run_three_stage()
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(entry["status"], "blocked")
        self.assertIn("不可读", entry.get("error", ""))
        self.assertIn("Invalid control character", entry.get("error", ""))
        # 重派 judge 一次
        judge_calls = [
            c for c in self.engine.agent_runner.run_planner.call_args_list
            if c[0][1] == "judge"
        ]
        self.assertGreaterEqual(len(judge_calls), 2)
        # 告警断言
        self.assertEqual(len(self._alert_calls), 1)
        alert = self._alert_calls[0]
        self.assertEqual(alert["signal_type"], "verdict_result_unreadable")
        self.assertEqual(alert["severity"], "critical")
        self.assertIn("Invalid control character", alert["evidence"])
        # 不晋级 verified，不派生 fix
        self.engine._on_spec_verified.assert_not_called()
        self.engine._on_spec_bug_found.assert_not_called()

    def test_unknown_status_retry_then_block(self):
        """status='success' 白名单外 → 重试 → 仍坏 → blocked。"""
        self.engine._read_verdict = MagicMock(side_effect=[
            VerdictReadResult.failure("unknown-status", "status='success'"),
            VerdictReadResult.failure("unknown-status", "status='success'"),
        ])
        self._run_three_stage()
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(entry["status"], "blocked")
        self.assertIn("'success'", entry.get("error", ""))
        self.engine._on_spec_verified.assert_not_called()

    def test_retry_then_success_fix_chain(self):
        """首次 unreadable → 重试后合法 bug-found → 正常走 fix 链。"""
        self.engine._read_verdict = MagicMock(side_effect=[
            VerdictReadResult.failure("parse", "bad json"),
            VerdictReadResult.success("bug-found"),
        ])
        self._run_three_stage()
        entry = self.sm.read_one("demo-spec")
        self.assertIn(entry["status"], ("bug-found", "implemented"))
        self.engine._on_spec_bug_found.assert_called_once_with("demo-spec")
        self.engine._on_spec_verified.assert_not_called()


class TestThreeStageValidRoutes(_FailClosedTestBase):
    """三阶段合法裁决路由不回归。"""

    def test_verified_route(self):
        """合法 verified → verified → done。"""
        self.engine._read_verdict = MagicMock(
            return_value=VerdictReadResult.success("verified"))
        self._run_three_stage()
        entry = self.sm.read_one("demo-spec")
        self.assertIn(entry["status"], ("verified", "done"))
        self.engine._on_spec_verified.assert_called_once()

    def test_scenario_repaired_route(self):
        """合法 scenario-repaired → 冻结记账 + 重入，随后 verified 收敛。"""
        self.engine._read_verdict = MagicMock(
            side_effect=[
                VerdictReadResult.success("scenario-repaired"),
                VerdictReadResult.success("verified"),
            ])
        self._run_three_stage()
        # 修复轮冻结记账恰一次
        self.assertEqual(self.engine._apply_scenario_freeze.call_count, 1)
        entry = self.sm.read_one("demo-spec")
        self.assertIn(entry["status"], ("verified", "done"))

    def test_all_green_fast_path_verified(self):
        """全绿快道机械写回 → 读侧 ok → verified 不回归。"""
        # 不 mock _read_verdict（setUp 未 mock）— 让真实读取走文件路径
        # 阶段1 冻结复用跳过 planner-plan 读；阶段3 由 _all_green_fast_path
        # 机械写入 primary → _read_verdict 真实读取 → verified。

        class AllGreenEngine:
            def __init__(self, spec_name, project_root, logger=None,
                         config=None, scenario_root=None):
                pass
            async def run(self, scenarios):
                return {
                    "spec": "demo-spec",
                    "summary": {
                        "total": 2, "passed": 2, "failed": 0,
                        "warnings": 0, "errors": 0,
                    },
                    "scenarios": [],
                }
        self._run_three_stage(AllGreenEngine)
        entry = self.sm.read_one("demo-spec")
        self.assertIn(entry["status"], ("verified", "done"))
        self.engine._on_spec_verified.assert_called_once()
        # 机械写回的产物存在于主树
        result_path = (
            self.verify_dir / ".fenix-run-result.json"
        )
        self.assertTrue(result_path.is_file())
        with open(result_path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data.get("status"), "verified")
        self.assertTrue(data.get("mechanical"))


class TestLegacyReadFailClosed(unittest.TestCase):
    """legacy 路径：结果不可读 → blocked + 告警，不晋级 verified。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        self.engine = PMEngine(
            self.sm, MagicMock(), {}, Path(self.tmpdir), self.logger,
        )
        self.sm.add_spec("demo-spec", {"priority": 5})
        for s in ("ready", "implementing", "implemented", "testing"):
            self.sm.transition("demo-spec", s)

        self.engine._enqueue = MagicMock()
        self.engine._on_spec_verified = MagicMock()
        self.engine._on_spec_bug_found = MagicMock()
        self.engine._task_completion_blocker = MagicMock(return_value=None)
        self.engine._env_whitewash_gate = MagicMock(return_value=True)
        self.engine._ensure_verification_report = MagicMock(return_value=None)
        self.engine._check_verification_gate = MagicMock(return_value=None)
        self.engine._send_human_escalation_alert = MagicMock()
        self.engine.agent_runner.run_verifier = MagicMock(
            return_value=SimpleNamespace(
                success=True, error=None,
                run_id="verify-demo-spec-1-a1",
            )
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run_legacy(self):
        self.engine._run_legacy_verification("demo-spec")

    def test_corrupt_result_file_blocks(self):
        """legacy 裸换行非法 JSON → blocked + verdict_result_unreadable 告警。"""
        run_result_path = Path(self.tmpdir) / ".fenix" / ".fenix-run-result.json"
        run_result_path.write_text(
            CORRUPT_NEWLINE_RESULT, encoding="utf-8")
        self._run_legacy()
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(entry["status"], "blocked")
        self.assertIn("不可读", entry.get("error", ""))
        self.assertIn("parse", entry.get("error", ""))
        self.engine._send_human_escalation_alert.assert_called_once()
        alert_kwargs = (
            self.engine._send_human_escalation_alert.call_args[1])
        self.assertEqual(alert_kwargs["signal_type"], "verdict_result_unreadable")
        self.assertEqual(alert_kwargs["severity"], "critical")
        self.engine._on_spec_verified.assert_not_called()

    def test_unknown_status_own_spec_blocks(self):
        """legacy status='success' 属当前 spec → 白名单外 blocked（非 stale re-dispatch）。"""
        run_result_path = Path(self.tmpdir) / ".fenix" / ".fenix-run-result.json"
        run_result_path.write_text(
            UNKNOWN_STATUS_RESULT, encoding="utf-8")
        self._run_legacy()
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(entry["status"], "blocked")
        self.assertIn("'success'", entry.get("error", ""))
        self.engine._on_spec_verified.assert_not_called()

    def test_missing_result_file_blocks(self):
        """legacy 结果文件缺失 → blocked（fail-closed，非 stale re-dispatch）。"""
        self._run_legacy()
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(entry["status"], "blocked")
        self.assertIn("不可读", entry.get("error", ""))
        self.engine._send_human_escalation_alert.assert_called_once()

    def test_valid_bug_found_still_works(self):
        """legacy 合法 bug-found（role=verifier）→ 正常流转 bug-found，不回归。"""
        run_result_path = Path(self.tmpdir) / ".fenix" / ".fenix-run-result.json"
        run_result_path.write_text(
            json.dumps({"spec": "demo-spec", "status": "bug-found",
                         "bugs": [], "role": "verifier"}),
            encoding="utf-8")
        self._run_legacy()
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(entry["status"], "bug-found")
        self.engine._send_human_escalation_alert.assert_not_called()
