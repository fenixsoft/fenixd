"""scenario-defect-reroute-stoploss 单元测试（evo-scenario-defect-reroute-stoploss 3.x）。

覆盖 spec 需求 scenario-defect-reroute-stoploss：
  - 改道重入轮（深度≥1，留存轮次匹配）同批失败 → 提前止损升级人工
    （human-escalation-alert scenario_defect_reroute_stoploss），未等
    _SCENARIO_REPAIR_MAX_ROUNDS 耗尽、run_planner 未被调用
  - 有场景被修复 → 覆盖留存后继续既有改道预算通道（仍重派 judge）
  - 纯新增失败场景（无一修复）→ 判同批止损
  - 链首触发（深度 0）+ 陈旧留存失败集相同 → 不误停（照常重派 judge）
  - 留存缺失/损坏/结构不符/轮次不匹配 → 保守放行不误停
  - 既有预算耗尽升级路径回归不破坏（signal 仍为 scenario_defect_reroute_exhausted）
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.pm_engine.verification import (
    VerificationPipeline,
    VerdictReadResult,
    _SCENARIO_REPAIR_MAX_ROUNDS,
)


def _mk_pm(tmpdir, spec="demo-spec"):
    """构造最小 PM 桩：project_root/logger/state_machine/agent_runner/
    _send_human_escalation_alert（与 test_scenario_reroute_gate 同构）。
    """
    pm = SimpleNamespace()
    pm.project_root = Path(tmpdir)
    pm.logger = MagicMock()
    pm.state_machine = SimpleNamespace(
        read_one=lambda s: _STATE.get(s) or {},
        update_spec=lambda s, upd: _STATE.update({s: {**_STATE.get(s, {}), **upd}}),
    )
    pm.agent_runner = SimpleNamespace(
        run_planner=MagicMock(
            return_value=SimpleNamespace(
                success=True, error=None, cancelled=False,
                run_id=f"planner-judge-{spec}-123-a1",
            )
        ),
    )
    pm._read_verdict = MagicMock()
    pm._apply_scenario_freeze = MagicMock(return_value={})
    pm._send_human_escalation_alert = MagicMock()
    return pm


_STATE: dict = {}


def _seed_report(tmpdir, spec, scenarios):
    """写 report.json（改道门判定依据，重跑后当前失败集来源）。"""
    vp = Path(tmpdir) / ".fenix" / "verify-progress" / spec
    vp.mkdir(parents=True, exist_ok=True)
    (vp / "report.json").write_text(
        json.dumps({"spec": spec, "scenarios": scenarios}, ensure_ascii=False),
        encoding="utf-8",
    )


def _seed_stoploss(tmpdir, spec, round_=0, failed_ids=(), *, raw=None):
    """预置跨轮失败集留存；raw 非 None 时原样写入（构造损坏/结构非法场景）。"""
    vp = Path(tmpdir) / ".fenix" / "verify-progress" / spec
    vp.mkdir(parents=True, exist_ok=True)
    path = vp / "scenario_reroute_stoploss.json"
    if raw is not None:
        path.write_text(raw, encoding="utf-8")
    else:
        path.write_text(
            json.dumps(
                {
                    "round": round_,
                    "failed_ids": failed_ids,
                    "written_at": "2026-09-18T00:00:00+00:00",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


def _stoploss_path(tmpdir, spec="demo-spec"):
    return (
        Path(tmpdir)
        / ".fenix"
        / "verify-progress"
        / spec
        / "scenario_reroute_stoploss.json"
    )


def _scenario(sid, status="failed", classification=None):
    sc = {"scenario_id": sid, "status": status}
    if classification is not None:
        sc["classification"] = classification
    return sc


class TestRerouteStoploss(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        _STATE.clear()
        _STATE["demo-spec"] = {"status": "testing"}
        self.pm = _mk_pm(self.tmpdir)
        self.pipe = VerificationPipeline(self.pm)
        # 重入执行在门本身之外（调用方 _run_three_stage_verification 负责）；
        # 单测隔离之，避免牵入完整流水线桩
        self.pipe._run_three_stage_verification = MagicMock()
        self.pipe._read_verdict = MagicMock(
            return_value=VerdictReadResult.success("scenario-repaired"))
        self.pipe._apply_scenario_freeze = MagicMock(return_value={})
        self.judge_result = SimpleNamespace(
            success=True, error=None, run_id="planner-judge-demo-spec-1-a1",
            cancelled=False,
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ── 3.1：改道重入轮同批失败 → 提前止损 ──

    def test_reentry_same_batch_stoploss_escalates(self):
        # 改道重入轮（深度 1）重跑失败集与改道前完全相同（含相等同批）→
        # 提前止损升级人工：未等预算耗尽、不再重派 judge
        _seed_report(self.tmpdir, "demo-spec", [
            _scenario("s1", classification="test-defect"),
            _scenario("s2", classification="flaky"),
        ])
        _seed_stoploss(self.tmpdir, "demo-spec", round_=0, failed_ids=["s1", "s2"])
        handled = self.pipe._scenario_defect_reroute_gate(
            "demo-spec", _repair_depth=1, judge_result=self.judge_result)
        assert handled is True
        self.pm.agent_runner.run_planner.assert_not_called()
        kwargs = self.pm._send_human_escalation_alert.call_args[1]
        assert kwargs["signal_type"] == "scenario_defect_reroute_stoploss"
        assert kwargs["severity"] == "major"
        # 附同批失败证据：failed_ids / 轮次 / classification 分布
        assert "s1" in kwargs["evidence"] and "s2" in kwargs["evidence"]
        assert "轮次" in kwargs["evidence"]
        assert "分类" in kwargs["evidence"] or "classification" in kwargs["evidence"]
        entry = _STATE["demo-spec"]
        assert entry["status"] == "testing"  # spec 保持 testing
        assert "同批" in str(entry.get("error"))

    def test_reentry_same_batch_does_not_touch_impl_budget(self):
        # 止损路径不触碰 impl_run_budget / _repair_depth 语义
        _seed_report(self.tmpdir, "demo-spec", [
            _scenario("s1", classification="test-defect"),
        ])
        _seed_stoploss(self.tmpdir, "demo-spec", round_=0, failed_ids=["s1"])
        self.pipe._scenario_defect_reroute_gate(
            "demo-spec", _repair_depth=1, judge_result=self.judge_result)
        assert "_impl_run_budget_used" not in _STATE["demo-spec"]

    # ── 3.2：有修复继续预算；纯新增止损；缺失/损坏/轮次不匹配放行 ──

    def test_reentry_has_fix_continues_budget_channel(self):
        # 改道重入轮有场景被修复（s2 已不在重跑失败集）→ 覆盖留存后继续
        # 既有预算通道（仍重派 judge），不升级人工
        _seed_report(self.tmpdir, "demo-spec", [
            _scenario("s1", classification="test-defect"),
        ])
        _seed_stoploss(self.tmpdir, "demo-spec", round_=0, failed_ids=["s1", "s2"])
        handled = self.pipe._scenario_defect_reroute_gate(
            "demo-spec", _repair_depth=1, judge_result=self.judge_result)
        assert handled is True
        self.pm.agent_runner.run_planner.assert_called_once_with("demo-spec", "judge")
        self.pm._send_human_escalation_alert.assert_not_called()
        # 留存被覆盖为当前轮（round=1，当前 failed_ids）
        data = json.loads(_stoploss_path(self.tmpdir).read_text(encoding="utf-8"))
        assert data["round"] == 1
        assert data["failed_ids"] == ["s1"]

    def test_reentry_pure_new_failures_stoploss(self):
        # 纯新增失败场景（s1/s2 无一被修复，重跑多出 s3）→ 改道前失败集 ⊆
        # 重跑失败集 → 判同批止损
        _seed_report(self.tmpdir, "demo-spec", [
            _scenario("s1", classification="test-defect"),
            _scenario("s2", classification="flaky"),
            _scenario("s3", classification="test-defect"),
        ])
        _seed_stoploss(self.tmpdir, "demo-spec", round_=0, failed_ids=["s1", "s2"])
        handled = self.pipe._scenario_defect_reroute_gate(
            "demo-spec", _repair_depth=1, judge_result=self.judge_result)
        assert handled is True
        self.pm.agent_runner.run_planner.assert_not_called()
        assert self.pm._send_human_escalation_alert.call_args[1][
            "signal_type"
        ] == "scenario_defect_reroute_stoploss"

    def test_missing_record_passes_fail_open(self):
        # 留存缺失 → 保守放行，照常重派 judge、不误停
        _seed_report(self.tmpdir, "demo-spec", [
            _scenario("s1", classification="test-defect"),
        ])
        handled = self.pipe._scenario_defect_reroute_gate(
            "demo-spec", _repair_depth=1, judge_result=self.judge_result)
        assert handled is True
        self.pm.agent_runner.run_planner.assert_called_once_with("demo-spec", "judge")
        self.pm._send_human_escalation_alert.assert_not_called()
        # 本轮写入当前留存（round=1）
        data = json.loads(_stoploss_path(self.tmpdir).read_text(encoding="utf-8"))
        assert data["round"] == 1
        assert data["failed_ids"] == ["s1"]

    def test_corrupt_record_passes_fail_open(self):
        # 留存损坏（非法 JSON）→ 保守放行不误停
        _seed_report(self.tmpdir, "demo-spec", [
            _scenario("s1", classification="test-defect"),
            _scenario("s2", classification="test-defect"),
        ])
        _seed_stoploss(self.tmpdir, "demo-spec", raw="{not valid json !!")
        handled = self.pipe._scenario_defect_reroute_gate(
            "demo-spec", _repair_depth=1, judge_result=self.judge_result)
        assert handled is True
        self.pm.agent_runner.run_planner.assert_called_once_with("demo-spec", "judge")
        self.pm._send_human_escalation_alert.assert_not_called()

    def test_struct_invalid_record_passes_fail_open(self):
        # 留存结构不符（顶层非 dict / round 非整型 / failed_ids 非 list）→ 放行
        _seed_report(self.tmpdir, "demo-spec", [
            _scenario("s1", classification="test-defect"),
        ])
        _seed_stoploss(
            self.tmpdir, "demo-spec", raw='{"round": "x", "failed_ids": "notalist"}')
        handled = self.pipe._scenario_defect_reroute_gate(
            "demo-spec", _repair_depth=1, judge_result=self.judge_result)
        assert handled is True
        self.pm.agent_runner.run_planner.assert_called_once_with("demo-spec", "judge")
        self.pm._send_human_escalation_alert.assert_not_called()

    def test_empty_failed_ids_record_passes_fail_open(self):
        # 留存 failed_ids 为空 → 视为无留存，保守放行
        _seed_report(self.tmpdir, "demo-spec", [
            _scenario("s1", classification="test-defect"),
        ])
        _seed_stoploss(self.tmpdir, "demo-spec", raw=json.dumps(
            {"round": 0, "failed_ids": [], "written_at": "2026-09-18T00:00:00+00:00"}))
        handled = self.pipe._scenario_defect_reroute_gate(
            "demo-spec", _repair_depth=1, judge_result=self.judge_result)
        assert handled is True
        self.pm.agent_runner.run_planner.assert_called_once_with("demo-spec", "judge")
        self.pm._send_human_escalation_alert.assert_not_called()

    def test_round_mismatch_record_passes_fail_open(self):
        # 留存轮次与 _repair_depth - 1 不匹配（跨链陈旧）→ 放行不误停
        _seed_report(self.tmpdir, "demo-spec", [
            _scenario("s1", classification="test-defect"),
            _scenario("s2", classification="flaky"),
        ])
        _seed_stoploss(self.tmpdir, "demo-spec", round_=5, failed_ids=["s1", "s2"])
        handled = self.pipe._scenario_defect_reroute_gate(
            "demo-spec", _repair_depth=1, judge_result=self.judge_result)
        assert handled is True
        self.pm.agent_runner.run_planner.assert_called_once_with("demo-spec", "judge")
        self.pm._send_human_escalation_alert.assert_not_called()

    # ── 3.3：链首触发 + 陈旧留存失败集相同 → 不误停 ──

    def test_chain_head_stale_record_no_stoploss(self):
        # 全新验证轮（深度 0）门触发读到上一链条遗留留存且失败集相同 →
        # 不做同批判定，写入留存并照常走既有改道通道（MUST NOT 升级人工）
        _seed_report(self.tmpdir, "demo-spec", [
            _scenario("s1", classification="test-defect"),
            _scenario("s2", classification="flaky"),
        ])
        _seed_stoploss(self.tmpdir, "demo-spec", round_=0, failed_ids=["s1", "s2"])
        handled = self.pipe._scenario_defect_reroute_gate(
            "demo-spec", _repair_depth=0, judge_result=self.judge_result)
        assert handled is True
        self.pm.agent_runner.run_planner.assert_called_once_with("demo-spec", "judge")
        self.pm._send_human_escalation_alert.assert_not_called()
        # 链首只写留存（round=0，覆盖陈旧记录）
        data = json.loads(_stoploss_path(self.tmpdir).read_text(encoding="utf-8"))
        assert data["round"] == 0
        assert sorted(data["failed_ids"]) == ["s1", "s2"]

    def test_chain_head_writes_record_with_written_at(self):
        # 链首触发无留存文件 → 写入 {round, failed_ids, written_at}
        _seed_report(self.tmpdir, "demo-spec", [
            _scenario("s1", classification="test-defect"),
        ])
        handled = self.pipe._scenario_defect_reroute_gate(
            "demo-spec", _repair_depth=0, judge_result=self.judge_result)
        assert handled is True
        data = json.loads(_stoploss_path(self.tmpdir).read_text(encoding="utf-8"))
        assert data["round"] == 0
        assert data["failed_ids"] == ["s1"]
        assert "written_at" in data and data["written_at"]

    # ── 3.4：既有预算耗尽升级路径回归 ──

    def test_budget_exhausted_regression(self):
        # 深度达上限（_repair_depth >= MAX）→ 仍走既有 exhausted 升级路径，
        # stoploss 机制不干扰（消息保持「预算耗尽」、信号保持 exhausted）
        _seed_report(self.tmpdir, "demo-spec", [
            _scenario("s1", classification="test-defect"),
        ])
        handled = self.pipe._scenario_defect_reroute_gate(
            "demo-spec", _repair_depth=_SCENARIO_REPAIR_MAX_ROUNDS,
            judge_result=self.judge_result)
        assert handled is True
        self.pm.agent_runner.run_planner.assert_not_called()
        kwargs = self.pm._send_human_escalation_alert.call_args[1]
        assert kwargs["signal_type"] == "scenario_defect_reroute_exhausted"
        entry = _STATE["demo-spec"]
        assert entry["status"] == "testing"
        assert "预算耗尽" in str(entry.get("error"))

    def test_reroute_then_scenario_repaired_reenters_still_works(self):
        # 改道后 judge 申报 scenario-repaired → 重入执行（第 1 次修复）——
        # 既有通道在 stoploss 机制下不受影响（链首只写留存）
        _seed_report(self.tmpdir, "demo-spec", [
            _scenario("s1", classification="test-defect"),
        ])
        handled = self.pipe._scenario_defect_reroute_gate(
            "demo-spec", _repair_depth=0, judge_result=self.judge_result)
        assert handled is True
        self.pipe._run_three_stage_verification.assert_called_once_with(
            "demo-spec", _repair_depth=1)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))