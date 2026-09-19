"""Characterization tests for _run_three_stage_verification / _execute_agent_inner。

锁定两个超长函数在当前代码上的可观测行为——状态推进序列、
写出的产物内容、返回结构、异常类型与消息——作为拆分前后等价性
基线（design D0 / tasks 1.2）。

只记录可观测行为，不写实现逻辑断言——重构时保证这些行为不变。
"""

import asyncio
import json
import shutil
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core.pm_engine.verification import VerificationPipeline
from core.state_machine import StateMachine
from core.agent_runner.runner import AgentRunResult


# ═══════════════════════════════════════════════════════════════════════════════
# 夹具
# ═══════════════════════════════════════════════════════════════════════════════

class _FakeLogger:
    def debug(self, *a, **k): pass
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass


def _make_pm(project_root):
    """构造满足 VerificationPipeline 依赖的最小 PMEngine mock。"""
    state_path = project_root / ".fenix" / "STATE.md"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    logger = _FakeLogger()
    sm = StateMachine(state_path, logger)
    pm = MagicMock()
    pm.project_root = project_root
    pm.logger = logger
    pm.state_machine = sm
    pm.agent_runner = MagicMock()
    pm.agent_runner.run_planner = MagicMock(
        return_value=SimpleNamespace(
            success=True, error=None,
            run_id="planner-plan-char-spec-1-a1",
        ))
    pm.agent_runner.ensure_planner_route_map = MagicMock()
    pm._get_config = MagicMock(return_value=3)
    pm._enqueue = MagicMock()
    return pm, sm, logger


def _base_pipeline_setup(spec="char-spec"):
    tmpdir = tempfile.mkdtemp()
    root = Path(tmpdir)
    (root / ".fenix").mkdir(parents=True, exist_ok=True)
    (root / "spec" / "changes" / spec / "specs" / "cap-a").mkdir(
        parents=True, exist_ok=True)
    (root / "spec" / "changes" / spec / "specs" / "cap-a" / "spec.md"
    ).write_text("# Spec\nInitial.", encoding="utf-8")
    pm, sm, logger = _make_pm(root)
    sm.add_spec(spec, {"priority": 5})
    for s in ("ready", "implementing", "implemented", "testing"):
        sm.transition(spec, s)
    vp = root / ".fenix" / "verify-progress" / spec
    vp.mkdir(parents=True, exist_ok=True)
    (vp / "scenarios.json").write_text(
        json.dumps({
            "spec": spec, "round": 1,
            "scenarios": [
                {"id": "s1", "kind": "cli",
                 "description": "场景1", "added_in_round": 1}
            ],
        }, ensure_ascii=False), encoding="utf-8")
    return tmpdir, root, pm, sm, logger, vp


# ═══════════════════════════════════════════════════════════════════════════════
# _run_three_stage_verification characterization
# ═══════════════════════════════════════════════════════════════════════════════

class TestThreeStageVerificationChar:
    """锁定 _run_three_stage_verification 关键可观测行为。"""

    # ── 状态推进序列 ─────────────────────────────────────────────────────

    def test_entry_status_not_testing_discards_result(self):
        """入口 status 非 testing → 直接 return（无状态变更、无异常）。"""
        tmpdir, root, pm, sm, lg, vp = _base_pipeline_setup()
        try:
            sm.update_spec("char-spec", {"status": "implemented"})
            pipe = VerificationPipeline(pm)
            pipe._run_three_stage_verification("char-spec")
            # spec 保持 implemented，未被修改
            assert sm.read_one("char-spec")["status"] == "implemented"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_planner_failure_raises_runtime_error(self):
        """planner 失败（非取消/非 circuit）→ raise RuntimeError（既有行为：
        异常触发外层 legacy 降级，spec 状态不变）。"""
        tmpdir, root, pm, sm, lg, vp = _base_pipeline_setup()
        try:
            pm.agent_runner.run_planner = MagicMock(
                return_value=SimpleNamespace(
                    success=False, error="planner crashed",
                    cancelled=False, run_id="planner-plan-xxx"))
            pipe = VerificationPipeline(pm)
            with patch("importlib.reload", lambda m: m), \
                    pytest.raises(RuntimeError, match="Planner plan 失败"):
                pipe._run_three_stage_verification("char-spec")
            entry = sm.read_one("char-spec")
            assert entry["status"] == "testing"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_frozen_corrupt_escalates_and_returns(self):
        """冻结场景文件损坏 → _escalate_env_blocked 升级 + return（不抛异常、
        状态保持 testing，spec 不流转）。"""
        tmpdir, root, pm, sm, lg, vp = _base_pipeline_setup()
        try:
            pipe = VerificationPipeline(pm)
            pipe._escalate_env_blocked = MagicMock()
            # 写不可解析的冻结文件（JSON 语法错 → corrupt → env_blocked；
            # 自 evo-frozen-scenario-contract-versioning 起 _load_frozen_or_escalate
            # 直接读原始 JSON 路由契约迁移，不再经 _load_frozen_scenarios 验收）
            (vp / "test_scenarios.json").write_text("{not-json", encoding="utf-8")
            with patch("importlib.reload", lambda m: m):
                result = pipe._run_three_stage_verification("char-spec")
            assert result is None
            pipe._escalate_env_blocked.assert_called_once()
            entry = sm.read_one("char-spec")
            assert entry["status"] == "testing"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # ── 写出的产物 ─────────────────────────────────────────────────────

    def test_verify_progress_dir_exists(self):
        """函数运行时 verify_dir 必须存在（B1 创建），corrupt 冻结路径后仍存在。"""
        tmpdir, root, pm, sm, lg, vp = _base_pipeline_setup()
        try:
            pipe = VerificationPipeline(pm)
            pipe._escalate_env_blocked = MagicMock()
            (vp / "test_scenarios.json").write_text("{not-json", encoding="utf-8")
            with patch("importlib.reload", lambda m: m):
                pipe._run_three_stage_verification("char-spec")
            assert vp.exists()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_planner_cancelled_writes_hold_state(self):
        """planner 被取消 → spec 写入 error + _cancelled_hold=True（不流转 bug-found）。"""
        tmpdir, root, pm, sm, lg, vp = _base_pipeline_setup()
        try:
            pm.agent_runner.run_planner = MagicMock(
                return_value=SimpleNamespace(
                    success=False, error="timeout",
                    cancelled=True, run_id="r"))
            pipe = VerificationPipeline(pm)
            with patch("importlib.reload", lambda m: m):
                pipe._run_three_stage_verification("char-spec")
            entry = sm.read_one("char-spec")
            assert entry["status"] == "testing"
            assert entry.get("_cancelled_hold") is True
            assert "取消" in entry.get("error", "") or "cancel" in entry.get("error", "").lower()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # ── 异常类型 ─────────────────────────────────────────────────────────

    def test_import_error_in_reload_does_not_crash(self):
        """importlib.reload 内部异常 → WARNING 记录，函数不崩溃（fail-open）。"""
        tmpdir, root, pm, sm, lg, vp = _base_pipeline_setup()
        try:
            pipe = VerificationPipeline(pm)
            pipe._escalate_env_blocked = MagicMock()
            (vp / "test_scenarios.json").write_text("{not-json", encoding="utf-8")
            def _explode(m):
                raise RuntimeError("reload failed")
            with patch("importlib.reload", _explode), \
                 patch("importlib.import_module", lambda m: None):
                pipe._run_three_stage_verification("char-spec")
            # reload 异常被 per-module try/except 吞掉（fail-open），函数继续执行
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # ── 返回结构 ─────────────────────────────────────────────────────────

    def test_returns_none_on_entry_guard(self):
        """入口 status != testing → return None（void 函数）。"""
        tmpdir, root, pm, sm, lg, vp = _base_pipeline_setup()
        try:
            sm.update_spec("char-spec", {"status": "done"})
            pipe = VerificationPipeline(pm)
            result = pipe._run_three_stage_verification("char-spec")
            assert result is None
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════════
# _execute_agent_inner characterization
# ═══════════════════════════════════════════════════════════════════════════════

class TestExecuteAgentInnerChar:
    """锁定 _execute_agent_inner 关键可观测行为。"""

    def _make_runner(self, project_root):
        from core.agent_runner import AgentRunner
        runner = AgentRunner.__new__(AgentRunner)
        runner.config = {
            "agents.max_retries": 3,
            "agents.max_turns": 300,
            "agents.transient_backoff_schedule": "1,2",
        }
        runner.worktree_manager = MagicMock()
        runner.state_machine = MagicMock()
        runner.project_root = project_root
        runner.logger = _FakeLogger()
        runner._running_agents = {}
        runner._daily_run_count = 0
        # _provider_circuit 为惰性属性：通过 _provider_circuit_instance 注入 mock
        pc = MagicMock()
        pc.provider_circuits = {}
        pc._daily_provider_attempts = {}
        pc._daily_provider_warned = {}
        runner.__dict__["_provider_circuit_instance"] = pc
        runner._cancel_requested = set()
        runner._cancel_meta = {}
        runner.shutting_down = False
        runner._last_model_used = None
        runner._instant_fail = {}
        return runner

    def test_frozen_spec_returns_failure(self):
        """frozen spec → 返回失败 AgentRunResult，error 含 FROZEN 指示。"""
        tmpdir = tempfile.mkdtemp()
        root = Path(tmpdir)
        (root / ".fenix").mkdir(parents=True, exist_ok=True)
        try:
            runner = self._make_runner(root)
            runner._spec_is_frozen = MagicMock(return_value=True)
            runner._log_run_metrics = MagicMock()
            runner._extract_usage_info = MagicMock(return_value={})
            result = runner._execute_agent_inner(
                "frozen-spec", "implementer", "run-1")
            assert isinstance(result, AgentRunResult)
            assert result.success is False
            assert result.spec_name == "frozen-spec"
            assert "frozen" in (result.error or "").lower()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_cancel_flag_returns_failure_with_cancelled(self):
        """cancel flag 命中 → 返回失败结果，cancelled=True。"""
        tmpdir = tempfile.mkdtemp()
        root = Path(tmpdir)
        (root / ".fenix").mkdir(parents=True, exist_ok=True)
        try:
            runner = self._make_runner(root)
            runner._spec_is_frozen = MagicMock(return_value=False)
            runner._cancel_is_requested = MagicMock(return_value=True)
            runner._cancel_meta = {"run-1": {"reason": "user abort"}}
            runner._cancel_clear = MagicMock()
            runner._log_run_metrics = MagicMock()
            runner._extract_usage_info = MagicMock(return_value={})
            result = runner._execute_agent_inner(
                "spec-x", "implementer", "run-1")
            assert isinstance(result, AgentRunResult)
            assert result.success is False
            assert result.cancelled is True
            assert "user abort" in (result.error or "")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_chain_exhausted_returns_failure(self):
        """provider 链耗尽 → 返回失败结果，chain_exhausted=True。"""
        tmpdir = tempfile.mkdtemp()
        root = Path(tmpdir)
        (root / ".fenix").mkdir(parents=True, exist_ok=True)
        try:
            runner = self._make_runner(root)
            runner._spec_is_frozen = MagicMock(return_value=False)
            runner._cancel_is_requested = MagicMock(return_value=False)
            runner._check_daily_limit = MagicMock()
            runner._get_agent_model_assignment = MagicMock(return_value=[
                ({"name": "prov1", "baseurl": "x", "apikey": "y"}, "model1")
            ])
            runner._select_chain_candidate = MagicMock(return_value=-1)
            runner._log_run_metrics = MagicMock()
            runner._extract_usage_info = MagicMock(return_value={})
            runner.is_circuit_open = MagicMock(return_value=False)
            result = runner._execute_agent_inner(
                "spec-x", "implementer", "run-1")
            assert isinstance(result, AgentRunResult)
            assert result.success is False
            assert getattr(result, 'chain_exhausted', False) is True
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_return_is_agent_run_result(self):
        """所有早退路径返回类型 MUST 为 AgentRunResult。"""
        tmpdir = tempfile.mkdtemp()
        root = Path(tmpdir)
        (root / ".fenix").mkdir(parents=True, exist_ok=True)
        try:
            runner = self._make_runner(root)
            runner._spec_is_frozen = MagicMock(return_value=True)
            runner._log_run_metrics = MagicMock()
            runner._extract_usage_info = MagicMock(return_value={})
            result = runner._execute_agent_inner(
                "s", "implementer", "r")
            assert type(result).__name__ == "AgentRunResult"
            d = result.to_dict()
            assert "run_id" in d
            assert "spec_name" in d
            assert "success" in d
            assert "error" in d
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_usage_info_default_zero_on_early_exit(self):
        """早夭分支（frozen/cancel）→ usage_info 为默认值（_extract_usage_info 返回值）。"""
        tmpdir = tempfile.mkdtemp()
        root = Path(tmpdir)
        (root / ".fenix").mkdir(parents=True, exist_ok=True)
        try:
            runner = self._make_runner(root)
            runner._spec_is_frozen = MagicMock(return_value=True)
            runner._log_run_metrics = MagicMock()
            default_usage = {"input_tokens": 0, "output_tokens": 0}
            runner._extract_usage_info = MagicMock(return_value=default_usage)
            runner._execute_agent_inner("s", "implementer", "r")
            runner._log_run_metrics.assert_called_once()
            call_kw = runner._log_run_metrics.call_args
            assert call_kw[1].get("usage_info") == default_usage or \
                   (len(call_kw[0]) > 4)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_run_id_used_in_frozen_return(self):
        """frozen 早退 → AgentRunResult.run_id 使用基础 run_id（既有行为：
        冻结终止不派生 attempt_run_id）。"""
        tmpdir = tempfile.mkdtemp()
        root = Path(tmpdir)
        (root / ".fenix").mkdir(parents=True, exist_ok=True)
        try:
            runner = self._make_runner(root)
            runner._spec_is_frozen = MagicMock(return_value=True)
            runner._log_run_metrics = MagicMock()
            runner._extract_usage_info = MagicMock(return_value={})
            result = runner._execute_agent_inner(
                "s", "implementer", "base-run-id")
            assert result.run_id == "base-run-id"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
