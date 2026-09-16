"""judge-rerun-stability 单元测试（Task 4.1）。

验证核心行为：
  1. verified 落盘后（verdict_stability.json 记录 verified round）即使共享
     .fenix-run-result.json 被 implementer 残留 status=success 污染，
     verified 一次性放行门仍拒绝降级为 blocked/bug-found。
  2. judge 两轮 verdict 一致（spec 戳/report.json mtime 未变）时不产生第三轮
     judge run（稳定性复用路径，连续两轮一致即停）。
"""

import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.pm_engine import PMEngine
from core.state_machine import StateMachine
from core.verify_report import (
    compute_spec_stamp, record_verdict_round, read_verdict_stability,
    VERDICT_STABILITY_FILENAME,
)


class _VerifiedGateBase(unittest.TestCase):
    """verified 一次性放行门测试基础设施。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = self.project_root / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        self.engine = PMEngine(
            self.sm, MagicMock(), {}, self.project_root, self.logger,
        )
        # ── spec 进入 testing ──
        self.sm.add_spec("my-spec", {"priority": 5})
        for s in ("ready", "implementing", "implemented", "testing"):
            self.sm.transition("my-spec", s)
        # ── verify-progress 基础结构 ──
        self.vp = self.project_root / ".fenix" / "verify-progress" / "my-spec"
        self.vp.mkdir(parents=True, exist_ok=True)
        # ── spec.md + scenarios.json（spec 戳需要）──
        self.specs_dir = (
            self.project_root / "spec" / "changes" / "my-spec" / "specs"
        )
        (self.specs_dir / "cap-a").mkdir(parents=True, exist_ok=True)
        (self.specs_dir / "cap-a" / "spec.md").write_text(
            "# Spec A\nInitial spec content.", encoding="utf-8")
        (self.vp / "scenarios.json").write_text(
            json.dumps({
                "spec": "my-spec", "round": 1,
                "scenarios": [{"id": "s1", "kind": "cli",
                               "description": "场景1", "added_in_round": 1}],
            }, ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _seed_verdict_stable_verified(self):
        """写入 verdict_stability.json：最新轮次为 verified，spec 戳匹配当前。"""
        stamp = compute_spec_stamp(self.project_root, "my-spec")
        report_mtime = 123456789
        data = {
            "stamp": stamp,
            "report_mtime_ns": report_mtime,
            "rounds": [
                {"status": "bug-found", "failed_ids": ["s1"], "at": "2026-09-01"},
                {"status": "verified", "failed_ids": [], "at": "2026-09-02"},
            ],
            "updated_at": "2026-09-02T00:00:00Z",
        }
        (self.vp / VERDICT_STABILITY_FILENAME).write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    def _seed_shared_file_status_success(self):
        """主树共享 .fenix-run-result.json 被 implementer 残留 status=success 污染。"""
        shared = self.project_root / ".fenix" / ".fenix-run-result.json"
        shared.write_text(
            json.dumps({"spec": "my-spec", "status": "success",
                         "summary": "impl done"}, ensure_ascii=False),
            encoding="utf-8")


class TestVerifiedGateWithPollutedSharedFile(_VerifiedGateBase):
    """Task 4.1 场景一：verified 落盘后，共享文件被 status=success 污染，
    verified 门仍拒绝降级。"""

    def test_verified_gate_refuses_bug_found_when_shared_polluted(self):
        """共享 .fenix-run-result.json 污染 status=success 后，
        verified 门拒绝 bug-found 降级（legacy 路径不触发 transition）。"""
        # ── seed：verified 已落盘 ──
        self._seed_verdict_stable_verified()
        self._seed_shared_file_status_success()

        # ── act：调用 verified 门 ──
        ref = self.engine._verification
        refused = ref._verified_gate_refuses("my-spec", "bug-found")
        self.assertTrue(refused,
                        "共享文件 status=success 不影响 verified 门判断，"
                        "应拒绝 bug-found 降级")

    def test_verified_gate_refuses_blocked_when_shared_polluted(self):
        """共享 .fenix-run-result.json 污染 status=success 后，
        verified 门拒绝 blocked 降级。"""
        self._seed_verdict_stable_verified()
        self._seed_shared_file_status_success()

        ref = self.engine._verification
        refused = ref._verified_gate_refuses("my-spec", "blocked")
        self.assertTrue(refused,
                        "共享文件 status=success 不影响 verified 门判断，"
                        "应拒绝 blocked 降级")

    def test_verified_gate_inactive_when_stamp_changed(self):
        """场景集变更（spec 戳变化）→ verified 门失效，允许降级。"""
        self._seed_verdict_stable_verified()
        # ── 修改 scenarios.json 使 spec 戳变化 ──
        (self.vp / "scenarios.json").write_text(
            json.dumps({
                "spec": "my-spec", "round": 2,
                "scenarios": [
                    {"id": "s1", "kind": "cli",
                     "description": "场景1", "added_in_round": 1},
                    {"id": "s2", "kind": "cli",
                     "description": "新增场景", "added_in_round": 2},
                ],
            }, ensure_ascii=False), encoding="utf-8")

        ref = self.engine._verification
        refused = ref._verified_gate_refuses("my-spec", "bug-found")
        self.assertFalse(refused,
                         "场景集变更后 verified 门应失效，允许降级")

    def test_verified_gate_inactive_when_no_stability_data(self):
        """无 verdict_stability.json → verified 门不生效，正常流程。"""
        ref = self.engine._verification
        refused = ref._verified_gate_refuses("my-spec", "bug-found")
        self.assertFalse(refused,
                         "无 verdict_stability 数据时 verified 门不生效")


class TestLegacyUnknownStatusNotOverridingVerified(_VerifiedGateBase):
    """Task 2.1 集成测试：verified 落盘后 legacy unknown-status 不得改判。

    真实驱动 ``_run_legacy_verification``：主树共享 .fenix-run-result.json 被
    implementer 残留 status=success 污染（unknown-status 白名单外）时，verified
    放行门必须拒绝改判 blocked——spec 保持 testing 不降级。
    """

    def _run_legacy(self):
        from types import SimpleNamespace as _NS
        self.engine._on_spec_verified = MagicMock()
        self.engine._on_spec_bug_found = MagicMock()
        self.engine._verification._ensure_verification_report = MagicMock(return_value=None)
        self.engine._verification._env_whitewash_gate = MagicMock(return_value=True)
        self.engine.agent_runner.run_verifier = MagicMock(
            return_value=_NS(success=True, error=None,
                             run_id="verify-my-spec-1-a1"))
        # 主树共享结果文件被 implementer 残留 status=success 污染
        shared = self.project_root / ".fenix" / ".fenix-run-result.json"
        shared.write_text(
            json.dumps({"spec": "my-spec", "status": "success",
                         "summary": "impl ok"}, ensure_ascii=False),
            encoding="utf-8")
        # 使共享文件 mtime 新鲜（非 stale）：不触发 re-dispatch 分支
        import os
        now = time.time()
        os.utime(str(shared), (now, now))
        self.engine._run_legacy_verification("my-spec")

    def test_legacy_unknown_status_not_blocked_after_verified(self):
        """verified 落盘 + 共享文件被 success 污染 → legacy 不得改判 blocked。"""
        self._seed_verdict_stable_verified()
        self._run_legacy()
        entry = self.sm.read_one("my-spec")
        # 不降级：不得 blocked/bug-found；保持 testing（verified 结论不被推翻）
        self.assertEqual(entry["status"], "testing",
                         "verified 放行门应拒绝 legacy 将 verified 改判为 blocked")
        self.engine._on_spec_bug_found.assert_not_called()
        self.engine._on_spec_verified.assert_not_called()


class TestVerdictStabilityTwoRoundConsistency(_VerifiedGateBase):
    """Task 4.1 场景二：judge 两轮一致不产生第三轮。"""

    def test_two_identical_rounds_trigger_stability_reuse(self):
        """连续两轮 verdict 一致且 spec 戳/report.json mtime 未变 →
        is_verdict_stable 返回 True（第三轮将复用）。"""
        stamp = compute_spec_stamp(self.project_root, "my-spec")
        # ── 写入两轮一致的 verdict ──
        data = {
            "stamp": stamp,
            "report_mtime_ns": 999999,
            "rounds": [
                {"status": "bug-found", "failed_ids": ["s1"], "at": "2026-09-01"},
                {"status": "bug-found", "failed_ids": ["s1"], "at": "2026-09-02"},
            ],
            "updated_at": "2026-09-02T00:00:00Z",
        }
        (self.vp / VERDICT_STABILITY_FILENAME).write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        # ── report.json 使用相同 mtime（复用场景：无新 tester 运行）──
        (self.vp / "report.json").write_text(
            json.dumps({"summary": {"passed": 1, "total": 1},
                         "scenarios": [{"scenario_id": "s1", "status": "pass"}]},
                        ensure_ascii=False), encoding="utf-8")
        # 手动设置 mtime 与记录一致
        import os
        os.utime(str(self.vp / "report.json"),
                 ns=(data["report_mtime_ns"], data["report_mtime_ns"]))

        from core.verify_report import is_verdict_stable
        self.assertTrue(
            is_verdict_stable(self.project_root, "my-spec"),
            "两轮一致 + stamp/mtime 未变 → is_verdict_stable 应返回 True")

    def test_different_rounds_not_stable(self):
        """两轮 verdict 不一致 → is_verdict_stable 返回 False。"""
        stamp = compute_spec_stamp(self.project_root, "my-spec")
        data = {
            "stamp": stamp,
            "report_mtime_ns": 888888,
            "rounds": [
                {"status": "bug-found", "failed_ids": ["s1"], "at": "2026-09-01"},
                {"status": "verified", "failed_ids": [], "at": "2026-09-02"},
            ],
            "updated_at": "2026-09-02T00:00:00Z",
        }
        (self.vp / VERDICT_STABILITY_FILENAME).write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        (self.vp / "report.json").write_text(
            json.dumps({"summary": {"passed": 1, "total": 1}}, ensure_ascii=False),
            encoding="utf-8")
        import os
        os.utime(str(self.vp / "report.json"),
                 ns=(data["report_mtime_ns"], data["report_mtime_ns"]))

        from core.verify_report import is_verdict_stable
        self.assertFalse(
            is_verdict_stable(self.project_root, "my-spec"),
            "两轮 verdict 不一致 → is_verdict_stable 应返回 False")

    def test_single_round_not_stable(self):
        """只有一轮 verdict → is_verdict_stable 返回 False。"""
        stamp = compute_spec_stamp(self.project_root, "my-spec")
        data = {
            "stamp": stamp,
            "report_mtime_ns": 777777,
            "rounds": [
                {"status": "bug-found", "failed_ids": ["s1"], "at": "2026-09-01"},
            ],
            "updated_at": "2026-09-01T00:00:00Z",
        }
        (self.vp / VERDICT_STABILITY_FILENAME).write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        (self.vp / "report.json").write_text(
            json.dumps({"summary": {"passed": 1, "total": 1}}, ensure_ascii=False),
            encoding="utf-8")
        import os
        os.utime(str(self.vp / "report.json"),
                 ns=(data["report_mtime_ns"], data["report_mtime_ns"]))

        from core.verify_report import is_verdict_stable
        self.assertFalse(
            is_verdict_stable(self.project_root, "my-spec"),
            "单轮 verdict → is_verdict_stable 应返回 False")

    def test_record_verdict_round_appends_and_caps_at_two(self):
        """record_verdict_round 追加轮次并保留最近两轮。"""
        from core.verify_report import record_verdict_round
        record_verdict_round(
            self.project_root, "my-spec", "bug-found", ["s1"])
        record_verdict_round(
            self.project_root, "my-spec", "bug-found", ["s1"])

        data = read_verdict_stability(self.project_root, "my-spec")
        self.assertIsNotNone(data)
        self.assertEqual(len(data["rounds"]), 2)
        self.assertEqual(data["rounds"][0]["status"], "bug-found")
        self.assertEqual(data["rounds"][1]["status"], "bug-found")

    def test_judge_dispatch_gate_returns_reuse_when_stable(self):
        """_judge_dispatch_gate 在 verdict 稳定时返回 AgentRunResult（复用）。"""
        from core.verify_report import record_verdict_round
        stamp = compute_spec_stamp(self.project_root, "my-spec")
        # ── 先写两轮一致 verdict + 保持 report.json mtime 不变 ──
        record_verdict_round(
            self.project_root, "my-spec", "bug-found", ["s1"],
            stamp=stamp, report_mtime=111111)
        record_verdict_round(
            self.project_root, "my-spec", "bug-found", ["s1"],
            stamp=stamp, report_mtime=111111)
        (self.vp / "report.json").write_text(
            json.dumps({"summary": {"passed": 1, "total": 1}}, ensure_ascii=False),
            encoding="utf-8")
        import os
        os.utime(str(self.vp / "report.json"), ns=(111111, 111111))

        ref = self.engine._verification
        result = ref._judge_dispatch_gate("my-spec")
        self.assertIsNotNone(result,
                             "稳定时应返回合成复用结果")
        self.assertTrue(result.success)
        self.assertEqual(result.run_id, "verdict-stable-reuse")

    def test_hard_cap_freezes_on_count_exceeded(self):
        """judge_rerun_count 超上限（5）→ blocked + alert。"""
        from core.pm_engine.verification import _MAX_JUDGE_RERUNS
        ref = self.engine._verification
        # ── 手动灌入超过上限的 _judge_rerun_count ──
        self.sm.update_spec("my-spec", {
            "_judge_rerun_count": _MAX_JUDGE_RERUNS + 1,
        })
        # 上限检查在 is_verdict_stable 之前：count > 上限即冻结并 return False
        result = ref._judge_dispatch_gate("my-spec")
        self.assertFalse(result,
                         "硬上限时应返回 False（调用方 return），而非复用结果")
        entry = self.sm.read_one("my-spec")
        self.assertEqual(entry.get("status"), "blocked")
        self.assertTrue(entry.get("_judge_cap_frozen"),
                        "hard cap 后应设置 _judge_cap_frozen=True")


if __name__ == "__main__":
    unittest.main()
