"""evo-verifier-result-single-source：implementer 残留污染回归测试（Task 3.1/3.2）。

模拟 add-web-ui 误判链红灯场景：主树共享 .fenix/.fenix-run-result.json 被
implementer 残留 status=success 污染（role=implementer 或缺 role，且 run_id
不匹配 -\\d{10,}-a\\d+$ ——旧代码 _verifier_result_is_stale 的 run_id fail-open
会把残留误判为已读裁决、落入 blocked 分支）时，legacy 与 planner（三阶段）
两路径均不得将其当验证裁决，走 stale/foreign 护栏 re-dispatch。

Task 3.2 补机械锚点：断言 legacy 与 planner 两处裁决读取确实调用统一入口
_read_verdict（防「测试预先全绿、改动实为空跑」的零变更洗白）。
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.pm_engine import PMEngine
from core.pm_engine.verification import VerdictReadResult
from core.state_machine import StateMachine


# ── 红灯场景夹具 ──────────────────────────────────────────────────────────────
# run_id 不匹配 -\d{10,}-a\d+$（无 -a<attempt> 后缀）→ 旧 _verifier_result_is_stale
# fail-open，残留 status=success 会被采信判 blocked（本 SPEC 修复此行为）。

IMPL_RESIDUAL_ROLE = {
    "run_id": "impl-demo-spec-1750000000",
    "spec": "demo-spec",
    "status": "success",
    "role": "implementer",
    "summary": "impl ok",
}
IMPL_RESIDUAL_NO_ROLE = {
    "run_id": "impl-demo-spec-1750000000",
    "spec": "demo-spec",
    "status": "success",
    "summary": "impl ok",
}
VALID_VERIFIER_RESULT = {
    "run_id": "verify-demo-spec-1750000000-a1",
    "spec": "demo-spec",
    "role": "verifier",
    "status": "bug-found",
    "bugs": [],
}
ALL_GREEN_FAST_PATH_RESULT = {
    "status": "verified",
    "mechanical": True,
    "spec": "demo-spec",
    "bugs": [],
}


class _ContaminationBase:
    """污染回归测试共用基础设施（spec 进入 testing、冻结场景就绪）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        self.engine = PMEngine(
            self.sm, MagicMock(), {}, Path(self.tmpdir), self.logger,
        )
        self.engine._enqueue = MagicMock()
        self.engine._on_spec_verified = MagicMock()
        self.engine._on_spec_bug_found = MagicMock()
        self.engine._send_human_escalation_alert = MagicMock()
        self.sm.add_spec("demo-spec", {"priority": 5})
        for s in ("ready", "implementing", "implemented", "testing"):
            self.sm.transition("demo-spec", s)
        # 冻结场景（跳过阶段1 出题，直接阶段2/3）
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
        # spec.md + scenarios.json（spec 戳所需：verified 放行门判据）
        self.specs_dir = (
            Path(self.tmpdir) / "spec" / "changes" / "demo-spec" / "specs"
        )
        (self.specs_dir / "cap-a").mkdir(parents=True, exist_ok=True)
        (self.specs_dir / "cap-a" / "spec.md").write_text(
            "# Spec A\nInitial spec content.", encoding="utf-8")
        (self.verify_dir / "scenarios.json").write_text(
            json.dumps({
                "spec": "demo-spec", "round": 1,
                "scenarios": [{"id": "scn-a", "kind": "cli",
                               "description": "场景A", "added_in_round": 1}],
            }, ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @property
    def shared_path(self):
        return Path(self.tmpdir) / ".fenix" / ".fenix-run-result.json"

    def _write_shared(self, payload: dict) -> None:
        self.shared_path.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def _read_shared(self) -> dict | None:
        if not self.shared_path.exists():
            return None
        try:
            return json.loads(self.shared_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None


# ═══════════════════════════════════════════════════════════════════════════════
# 1. _read_verdict 入口单测
# ═══════════════════════════════════════════════════════════════════════════════

class TestReadVerdictEntry(_ContaminationBase, unittest.TestCase):
    """统一入口 _read_verdict：verify-progress 优先 + 主树共享 role/spec 戳。"""

    def test_primary_preferred_over_shared(self):
        """verify-progress/<spec>/ 存在 → 直接采信（per-spec 隔离），忽略共享文件。"""
        (self.verify_dir / ".fenix-run-result.json").write_text(
            json.dumps({"status": "bug-found", "bugs": []}), encoding="utf-8")
        self._write_shared(IMPL_RESIDUAL_ROLE)  # 共享有残留但不读
        res = self.engine._read_verdict("demo-spec")
        self.assertTrue(res.ok)
        self.assertEqual(res.status, "bug-found")

    def test_missing_both_files_unreadable(self):
        """两个文件都不存在 → missing（fail-closed）。"""
        res = self.engine._read_verdict("demo-spec")
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "missing")

    def test_shared_implementer_role_rejected(self):
        """主树共享 role=implementer → foreign-role（不采信为裁决）。"""
        self._write_shared(IMPL_RESIDUAL_ROLE)
        res = self.engine._read_verdict("demo-spec")
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "foreign-role")
        self.assertIn("role='implementer'", res.detail)

    def test_shared_missing_role_rejected(self):
        """主树共享缺 role（旧格式遗留）→ foreign-role。"""
        self._write_shared(IMPL_RESIDUAL_NO_ROLE)
        res = self.engine._read_verdict("demo-spec")
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "foreign-role")

    def test_shared_verifier_role_accepted(self):
        """主树共享 role=verifier + spec 匹配 + 白名单 status → ok。"""
        self._write_shared(VALID_VERIFIER_RESULT)
        res = self.engine._read_verdict("demo-spec")
        self.assertTrue(res.ok)
        self.assertEqual(res.status, "bug-found")

    def test_shared_foreign_spec_rejected(self):
        """主树共享 spec 戳与当前不符 → foreign-stamp。"""
        self._write_shared({
            "run_id": "verify-other-1750000000-a1",
            "spec": "other-spec",
            "role": "verifier",
            "status": "bug-found",
        })
        res = self.engine._read_verdict("demo-spec")
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "foreign-stamp")
        self.assertIn("other-spec", res.detail)

    def test_shared_invalid_json_parse_failure(self):
        """主树共享非法 JSON → parse。"""
        self.shared_path.write_text("not json {{{", encoding="utf-8")
        res = self.engine._read_verdict("demo-spec")
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "parse")

    def test_shared_unknown_status_after_role_gate(self):
        """role=verifier + status 白名单外 → unknown-status（role 已先行放行）。"""
        self._write_shared({
            "run_id": "verify-demo-spec-1750000000-a1",
            "spec": "demo-spec",
            "role": "verifier",
            "status": "success",
        })
        res = self.engine._read_verdict("demo-spec")
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "unknown-status")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. legacy 路径集成测试
# ═══════════════════════════════════════════════════════════════════════════════

class TestLegacyContamination(_ContaminationBase, unittest.TestCase):
    """legacy 路径：implementer 残留不得当裁决，走 stale/foreign 护栏 re-dispatch。"""

    def _run_legacy(self, verifier_run_id="verify-demo-spec-1750000000"):
        """run_id 不匹配 -\d{10,}-a\d+$（无 -a 后缀）→ 旧 fail-open 红灯场景。"""
        self.engine._ensure_verification_report = MagicMock(return_value=None)
        self.engine._env_whitewash_gate = MagicMock(return_value=True)
        self.engine._check_verification_gate = MagicMock(return_value=None)
        self.engine._speculative_bug_found_gate = MagicMock(return_value=False)
        self.engine.agent_runner.run_verifier = MagicMock(
            return_value=SimpleNamespace(
                success=True, error=None, run_id=verifier_run_id))
        self.engine._run_legacy_verification("demo-spec")

    def test_implementer_role_residual_redispatches(self):
        """role=implementer 残留（run_id 不可解析）→ 不 blocked、re-dispatch。"""
        self._write_shared(IMPL_RESIDUAL_ROLE)
        self._run_legacy()
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(entry["status"], "implemented")
        self.assertIn("replayed", entry.get("error", ""))
        self.assertIsNone(entry.get("tester_run"))
        self.engine._on_spec_verified.assert_not_called()
        self.engine._on_spec_bug_found.assert_not_called()
        self.engine._send_human_escalation_alert.assert_not_called()

    def test_missing_role_residual_redispatches(self):
        """旧格式（缺 role）残留 → 同样 re-dispatch 不 blocked。"""
        self._write_shared(IMPL_RESIDUAL_NO_ROLE)
        self._run_legacy()
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(entry["status"], "implemented")
        self.assertIn("replayed", entry.get("error", ""))

    def test_legacy_valid_verifier_still_works(self):
        """role=verifier 的合法裁决照常消费（bug-found 不回归）。"""
        self._write_shared(VALID_VERIFIER_RESULT)
        self._run_legacy()
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(entry["status"], "bug-found")
        self.engine._on_spec_bug_found.assert_called_once_with(
            "demo-spec", failure_class="product", run_id=ANY)

    def test_verified_gate_protects_against_redispatch(self):
        """已 verified + 共享残留 → 放行门拒绝 re-dispatch（不覆盖 verified）。"""
        # 预置 verdict stability（已 verified，spec 戳匹配当前）
        from core.verify_report import (
            VERDICT_STABILITY_FILENAME, compute_spec_stamp,
        )
        stamp = compute_spec_stamp(Path(self.tmpdir), "demo-spec")
        (self.verify_dir / VERDICT_STABILITY_FILENAME).write_text(
            json.dumps({
                "spec": "demo-spec",
                "stamp": stamp,
                "rounds": [
                    {"status": "verified", "failed_ids": [], "at": "2026-09-14"},
                ],
                "updated_at": "2026-09-14T00:00:00Z",
            }, ensure_ascii=False),
            encoding="utf-8")
        self._write_shared(IMPL_RESIDUAL_ROLE)
        self._run_legacy()
        # verified 放行门阻止 re-dispatch：status 保持 testing
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(entry["status"], "testing")
        self.engine._on_spec_verified.assert_not_called()
        self.engine._on_spec_bug_found.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# 3. 三阶段路径集成测试
# ═══════════════════════════════════════════════════════════════════════════════

class _ThreeStageBase(_ContaminationBase):
    """三阶段验证路径共用 mock 基础设施。"""

    def setUp(self):
        super().setUp()
        self.engine._task_completion_blocker = MagicMock(return_value=None)
        self.engine._apply_scenario_freeze = MagicMock(return_value={})
        self.engine._apply_interaction_contract = MagicMock(return_value=None)
        self.engine._verify_verdict_evidence = MagicMock(return_value={
            "ok": True, "cause": "pass", "violations": [], "dispatch_error": "",
        })
        self.engine._update_warning_streaks = MagicMock(return_value=[])
        self.engine._ensure_app_reachable = MagicMock(return_value=(True, False, ""))
        self.engine.agent_runner.run_planner = MagicMock(
            return_value=SimpleNamespace(
                success=True, error=None,
                run_id="planner-judge-demo-spec-1-a1",
            ))

    def _make_fake_verify_engine(self, all_pass=True):
        """构造假 VerifyEngine（返回全绿/全红）。"""
        class FakeEngine:
            def __init__(self, spec_name, project_root, logger=None,
                         config=None, scenario_root=None):
                pass
            async def run(self, scenarios):
                total = 2 if all_pass else 2
                passed = total if all_pass else 0
                failed = 0 if all_pass else total
                return {
                    "spec": "demo-spec",
                    "summary": {
                        "total": total, "passed": passed, "failed": failed,
                        "warnings": 0, "errors": 0,
                    },
                    "scenarios": [],
                }
        return FakeEngine

    def _run_three_stage(self, fake_engine_cls=None, **kwargs):
        cls = fake_engine_cls or self._make_fake_verify_engine()
        with patch("importlib.reload", lambda m: m), \
                patch("core.verify_engine.VerifyEngine", cls):
            self.engine._run_three_stage_verification("demo-spec", **kwargs)


class TestThreeStageContamination(_ThreeStageBase, unittest.TestCase):
    """三阶段路径：implementer 残留不采信，judge 重写后 fresh verdict 被采纳。"""

    def test_residual_not_read_when_primary_fresh(self):
        """primary 存在且合法 → shared 残留被忽略（primary 优先）。"""
        # 写合法 primary
        (self.verify_dir / ".fenix-run-result.json").write_text(
            json.dumps(ALL_GREEN_FAST_PATH_RESULT), encoding="utf-8")
        # 同时写共享残留（不应被读取）
        self._write_shared(IMPL_RESIDUAL_ROLE)
        self._run_three_stage()
        entry = self.sm.read_one("demo-spec")
        self.assertIn(entry["status"], ("verified", "done"))
        self.engine._on_spec_verified.assert_called()

    def test_residual_retriggers_judge_when_primary_missing(self):
        """primary 缺失 + shared 有残留 → 重写 judge → fresh verdict 被采纳。"""
        calls = {"n": 0}

        def fake_run_planner(spec_name, mode):
            if mode == "plan":
                return SimpleNamespace(
                    success=True, error=None,
                    run_id="planner-plan-demo-spec-1-a1")
            # judge 模式：首次不写 primary（模拟 judge 失败落盘），第二次写
            calls["n"] += 1
            if calls["n"] >= 2:
                primary = self.verify_dir / ".fenix-run-result.json"
                primary.write_text(
                    json.dumps(ALL_GREEN_FAST_PATH_RESULT),
                    encoding="utf-8")
            return SimpleNamespace(
                success=True, error=None,
                run_id="planner-judge-demo-spec-1-a1")

        self.engine.agent_runner.run_planner = MagicMock(
            side_effect=fake_run_planner)
        self._write_shared(IMPL_RESIDUAL_ROLE)  # shared 有残留，primary 缺
        self._run_three_stage()
        entry = self.sm.read_one("demo-spec")
        # 重写 judge 后采纳 fresh verdict（verified），不被残留干扰
        self.assertIn(entry["status"], ("verified", "done"))
        self.engine._on_spec_verified.assert_called()
        self.engine._on_spec_bug_found.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 机械锚点测试（Task 3.2）——防零变更洗白
# ═══════════════════════════════════════════════════════════════════════════════

class TestMechanicalAnchors(_ThreeStageBase, unittest.TestCase):
    """断言 legacy 与 planner 两路径确实调用统一入口 _read_verdict。"""

    def test_legacy_path_calls_read_verdict(self):
        """legacy 路径裁决读取必须走 _read_verdict（防空跑）。"""
        self._write_shared(IMPL_RESIDUAL_ROLE)
        self.engine._ensure_verification_report = MagicMock(return_value=None)
        self.engine._env_whitewash_gate = MagicMock(return_value=True)
        self.engine._check_verification_gate = MagicMock(return_value=None)
        self.engine._speculative_bug_found_gate = MagicMock(return_value=False)
        self.engine.agent_runner.run_verifier = MagicMock(
            return_value=SimpleNamespace(
                success=True, error=None, run_id="verify-demo-spec-1750000000"))
        with patch.object(self.engine, "_read_verdict",
                          wraps=self.engine._read_verdict) as mock_rd:
            self.engine._run_legacy_verification("demo-spec")
            mock_rd.assert_called_once_with("demo-spec")

    def test_three_stage_path_calls_read_verdict(self):
        """三阶段路径裁决读取必须走 _read_verdict（防空跑）。"""
        # primary 已存在：残留不相关，只验证入口被调用
        (self.verify_dir / ".fenix-run-result.json").write_text(
            json.dumps(ALL_GREEN_FAST_PATH_RESULT), encoding="utf-8")
        with patch.object(self.engine, "_read_verdict",
                          wraps=self.engine._read_verdict) as mock_rd:
            with patch("importlib.reload", lambda m: m), \
                    patch("core.verify_engine.VerifyEngine",
                          self._make_fake_verify_engine()):
                self.engine._run_three_stage_verification("demo-spec")
            mock_rd.assert_called()


# ═══════════════════════════════════════════════════════════════════════════════
# 5. 写入侧 R2：拷回 role/spec 戳注入（Task 2.1）
# ═══════════════════════════════════════════════════════════════════════════════

def _usage_ok() -> dict:
    return {"input_tokens": 1, "output_tokens": 2,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0, "cost_usd": None}


class TestCopybackRoleInjection:
    """主树共享写路径：_execute_agent 拷回时按 agent_type 注入 role 与 spec 戳。"""

    def _make_runner(self, tmp_path, agent_type: str):
        from core.agent_runner import AgentRunner
        from tests.helpers import FakeLogger

        runner = AgentRunner.__new__(AgentRunner)
        runner.config = {
            "llm": {"providers": [
                {"name": "inferaiapi.com", "baseurl": "https://a.com",
                 "apikey": "k1"},
            ]},
            "agents": {
                "models": {
                    agent_type: {"provider": "inferaiapi.com", "model": "m1"},
                },
                "max_retries": 1,
                "transient_backoff_schedule": "1",
            },
        }
        runner.worktree_manager = MagicMock()
        runner.state_machine = None
        runner.project_root = tmp_path
        runner.logger = MagicMock()
        runner._running_agents = {}
        runner._daily_run_count = 0
        runner._daily_reset_date = None
        runner._daily_provider_attempts = {}
        runner._daily_provider_warned = {}
        runner.provider_circuits = {}
        runner.__dict__["_v2_server_instance"] = MagicMock()
        runner._v2_server._v2_inject_env.return_value = {}
        runner.__dict__["_token_accountant_instance"] = MagicMock()
        runner._build_prompt = lambda *a, **k: "test prompt"
        (tmp_path / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
        return runner

    def _run_agent(self, tmp_path, agent_type, payload) -> dict:
        runner = self._make_runner(tmp_path, agent_type)
        wt = tmp_path / "wt"
        wt.mkdir(parents=True)
        runner.worktree_manager.create.return_value = wt
        runner.worktree_manager.get_branch_name.return_value = "fenix/spec-x"
        runner.worktree_manager.cleanup.return_value = None
        (wt / ".fenix-run-result.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        runner._run_claude = MagicMock(
            return_value=("done", 1, "sess-cb", _usage_ok()))
        result = runner._execute_agent("spec-x", agent_type, "run-cb1")
        assert result.success is True, result.error
        root_result = tmp_path / ".fenix" / ".fenix-run-result.json"
        return json.loads(root_result.read_text(encoding="utf-8"))

    def test_verifier_copyback_injects_role(self, tmp_path):
        """verifier 拷回 → role=verifier（裁决读侧唯一采信角色）。"""
        data = self._run_agent(
            tmp_path, "verifier", {"status": "bug-found", "bugs": []})
        assert data["role"] == "verifier"
        assert data["spec"] == "spec-x"
        assert data["status"] == "bug-found"

    def test_planner_judge_copyback_injects_judge_role(self, tmp_path):
        """planner-judge 拷回 → role=judge（裁决主为 per-spec primary，共享仅备份）。"""
        runner = self._make_runner(tmp_path, "planner-judge")
        wt = tmp_path / "wt"
        wt.mkdir(parents=True)
        runner.worktree_manager.create.return_value = wt
        runner.worktree_manager.get_branch_name.return_value = "fenix/spec-x"
        runner.worktree_manager.cleanup.return_value = None
        # planner-judge 产物硬门：verify-progress/.fenix-run-result.json 必须可解析
        wt_vp = wt / ".fenix" / "verify-progress" / "spec-x"
        wt_vp.mkdir(parents=True, exist_ok=True)
        (wt_vp / ".fenix-run-result.json").write_text(
            json.dumps({"status": "verified", "bugs": []}, ensure_ascii=False),
            encoding="utf-8")
        (wt / ".fenix-run-result.json").write_text(
            json.dumps({"status": "verified", "bugs": []}, ensure_ascii=False),
            encoding="utf-8")
        runner._run_claude = MagicMock(
            return_value=("done", 1, "sess-cb", _usage_ok()))
        result = runner._execute_agent("spec-x", "planner-judge", "run-cb2")
        assert result.success is True, result.error
        data = json.loads(
            (tmp_path / ".fenix" / ".fenix-run-result.json").read_text(
                encoding="utf-8"))
        assert data["role"] == "judge"
        assert data["spec"] == "spec-x"

    def test_planner_plan_copyback_injects_planner_role(self, tmp_path):
        """planner-plan 拷回 → role=planner。"""
        runner = self._make_runner(tmp_path, "planner-plan")
        wt = tmp_path / "wt"
        wt.mkdir(parents=True)
        runner.worktree_manager.create.return_value = wt
        runner.worktree_manager.get_branch_name.return_value = "fenix/spec-x"
        runner.worktree_manager.cleanup.return_value = None
        # planner-plan 双产物硬门：test_scenarios.json + .fenix-run-result.json
        wt_vp = wt / ".fenix" / "verify-progress" / "spec-x"
        wt_vp.mkdir(parents=True, exist_ok=True)
        (wt_vp / "test_scenarios.json").write_text(
            json.dumps([{"id": "s1", "description": "d",
                         "steps": [], "assertions": []}], ensure_ascii=False),
            encoding="utf-8")
        (wt_vp / ".fenix-run-result.json").write_text(
            json.dumps({"status": "plan-ready"}, ensure_ascii=False),
            encoding="utf-8")
        (wt / ".fenix-run-result.json").write_text(
            json.dumps({"status": "plan-ready", "summary": "scenarios generated"},
                       ensure_ascii=False), encoding="utf-8")
        runner._run_claude = MagicMock(
            return_value=("done", 1, "sess-cb", _usage_ok()))
        result = runner._execute_agent("spec-x", "planner-plan", "run-cb3")
        assert result.success is True, result.error
        data = json.loads(
            (tmp_path / ".fenix" / ".fenix-run-result.json").read_text(
                encoding="utf-8"))
        assert data["role"] == "planner"
        assert data["spec"] == "spec-x"

    def test_implementer_copyback_injects_role(self, tmp_path):
        """implementer 拷回 → role=implementer（裁决读侧将丢弃其残留）。"""
        runner = self._make_runner(tmp_path, "implementer")
        wt = tmp_path / "wt"
        wt.mkdir(parents=True)
        runner.worktree_manager.create.return_value = wt
        runner.worktree_manager.get_branch_name.return_value = "fenix/spec-x"
        runner.worktree_manager.cleanup.return_value = None
        # implementer 产物硬门依赖 tasks.md 完成度判据
        spec_dir = wt / "spec" / "changes" / "spec-x"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "tasks.md").write_text(
            "## 1. 阶段\n\n- [x] 1.1 任务\n", encoding="utf-8")
        (wt / ".fenix-run-result.json").write_text(
            json.dumps({"status": "success", "completed_tasks": ["1.1"],
                        "summary": "impl ok"}, ensure_ascii=False),
            encoding="utf-8")
        runner._run_claude = MagicMock(
            return_value=("done", 1, "sess-cb", _usage_ok()))
        result = runner._execute_agent("spec-x", "implementer", "run-cb5")
        assert result.success is True, result.error
        data = json.loads(
            (tmp_path / ".fenix" / ".fenix-run-result.json").read_text(
                encoding="utf-8"))
        assert data["role"] == "implementer"
        assert data["spec"] == "spec-x"
        assert data["status"] == "success"

    def test_invalid_json_copyback_keeps_raw_bytes(self, tmp_path):
        """非法 JSON → 维持原始字节拷回（读侧按 parse 归因，不注入破坏字节）。"""
        runner = self._make_runner(tmp_path, "verifier")
        wt = tmp_path / "wt"
        wt.mkdir(parents=True)
        runner.worktree_manager.create.return_value = wt
        runner.worktree_manager.get_branch_name.return_value = "fenix/spec-x"
        runner.worktree_manager.cleanup.return_value = None
        # 裸换行非法 JSON（add-verify-contract-autodraft 事故签名）
        (wt / ".fenix-run-result.json").write_text(
            '{"status": "bug-found", "summary": "line1\nline2"}',
            encoding="utf-8")
        runner._run_claude = MagicMock(
            return_value=("done", 1, "sess-cb", _usage_ok()))
        result = runner._execute_agent("spec-x", "verifier", "run-cb4")
        assert result.success is True  # verifier 无产物硬门
        raw = (tmp_path / ".fenix" / ".fenix-run-result.json").read_text(
            encoding="utf-8")
        assert '"summary": "line1\nline2"' in raw  # 原始字节保留
        assert '"role"' not in raw  # 非法 JSON 不注入
