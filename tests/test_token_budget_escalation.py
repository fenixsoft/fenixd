"""add-token-budget-escalation-tiers 单元测试（tasks 4.1-4.4）。

覆盖：
- 4.1：95% major 档触发/幂等/跳变补发；80%/100% 旧行为零回归；不自动冻结；
  _exec_raise_budget 翻倍 + TOKEN_BUDGET_ALERT_FLAGS 全复位（复位后可再触发）
- 4.2：_budget_conserve_state 联合判定；judge spec 级剩余重跑压缩为 1
  （基线锚定，越限冻结文案注明预算近满）；轮内派发上限 2→1 提前停派；
  未近满/未配置零行为变化（常规硬上限 5、轮内 2、文案形态不变）
- 4.3：收敛复验（达阈值切失败∪前置链∪下游子集、merge_subset_report 合并
  注明 token_conserve 模式、空子集/判定未激活回落全量、优先级仲裁让位
  场景修订重验、缺省关闭零行为）
- 4.4：agents.token_conserve_ratio 受管键三面登记（write_config 前置校验
  拒绝非法值不落盘、回显归一、project 来源标注）

注：STATE.md 字段以字符串存储，布尔标志读取时已按类型规整（断言 bool
形态，同 test_cost_observability 口径）。
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent_runner import AgentRunner
from core.agent_runner.token_budget import TOKEN_BUDGET_ALERT_FLAGS
from core.dashboard.data.admin_actions import _exec_raise_budget
from core.dashboard.data.config_admin import (
    read_config,
    read_effective_config,
    write_config,
)
from core.pm_engine.verification import VerificationPipeline
from core.pm_engine.verification.judge_gate import (
    _JUDGE_CONSERVE_REMAINING,
    _JUDGE_CONSERVE_ROUND_MAX_REAL_DISPATCHES,
    _JUDGE_ROUND_MAX_REAL_DISPATCHES,
    _MAX_JUDGE_RERUNS,
    _budget_conserve_state,
    _judge_dispatch_gate,
    _judge_round_escalate,
)
from core.state_machine import StateMachine
from core.verdict_check import load_report, save_report
from tests.helpers import FakeLogger


def make_runner(proot: Path, budget_millions: int = 50) -> AgentRunner:
    runner = AgentRunner.__new__(AgentRunner)
    runner.config = {"agents": {"token_budget_millions": budget_millions}}
    runner.worktree_manager = None
    runner.state_machine = None
    runner.project_root = proot
    runner.logger = FakeLogger()
    runner._running_agents = {}
    return runner


def make_state(proot: Path, spec: str, tokens_in: int = 0) -> StateMachine:
    (proot / ".fenix").mkdir(parents=True, exist_ok=True)
    sm = StateMachine(proot / ".fenix" / "STATE.md", FakeLogger())
    sm.add_spec(spec, {
        "priority": 5,
        "status": "implementing",
        "_tokens_in": tokens_in,
        "_tokens_out": 0,
    })
    return sm


USAGE_1M = {
    "input_tokens": 1_000_000,
    "output_tokens": 0,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0,
    "cost_usd": None,
}


def _token_alerts(proot: Path) -> list:
    from core.admin_store import AdminStore

    return [a for a in AdminStore(proot).read_all()
            if a.get("signal_type") == "token_budget"]


class RecordingNotifier:
    """escalation_notifier stub：记录升级告警 kwargs 供文案断言。"""

    def __init__(self):
        self.calls = []

    def __call__(self, **kw):
        self.calls.append(kw)


def make_pipeline(proot: Path, sm, config_map=None, notifier=None):
    """VerificationPipeline 最小装配（test_judge_efficiency 同款范式）。

    config_reader 消费扁平点号键 dict；notifier 缺省 MagicMock（断言
    never_called 用），需断言文案时传 RecordingNotifier。
    """
    pipeline = VerificationPipeline.__new__(VerificationPipeline)
    cfg = dict(config_map or {})
    ctx = SimpleNamespace(
        project_root=proot,
        logger=MagicMock(),
        state_machine=sm,
        config_reader=lambda key, default=None: cfg.get(key, default),
        escalation_notifier=notifier if notifier is not None else MagicMock(),
    )
    pipeline._pm = ctx
    pipeline._context = ctx
    return pipeline


# ── 4.3 场景集：s1←s2←s4 前置链 + s5←s1；s3 独立 ─────────────────────
def _cli_scenario(sid, deps=None):
    s = {
        "id": sid,
        "description": f"场景 {sid}",
        "kind": "cli",
        "steps": [{"action": "run", "command": ["echo", "hi"]}],
        "assertions": [{"type": "exit_code", "expected": 0}],
    }
    if deps:
        s["depends_on"] = deps
    return s


SCENARIOS = [
    _cli_scenario("s1"),
    _cli_scenario("s2", ["s1"]),
    _cli_scenario("s3"),
    _cli_scenario("s4", ["s2"]),
    _cli_scenario("s5", ["s1"]),
]


def _write_scenarios(proot: Path, spec: str, scenarios=None) -> Path:
    base = proot / ".fenix" / "verify-progress" / spec
    base.mkdir(parents=True, exist_ok=True)
    path = base / "test_scenarios.json"
    path.write_text(
        json.dumps(scenarios if scenarios is not None else SCENARIOS,
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def _write_report(proot: Path, spec: str, fail_ids=(), ts="ts-1"):
    base = proot / ".fenix" / "verify-progress" / spec
    base.mkdir(parents=True, exist_ok=True)
    save_report(proot, spec, {
        "timestamp": ts,
        "scenarios": [
            {"scenario_id": s["id"],
             "status": "fail" if s["id"] in fail_ids else "pass"}
            for s in SCENARIOS
        ],
    })


# ══════════════════════════ 4.1：95% major 档 ══════════════════════════

class TestTokenMajor95:
    def test_constant_set_includes_major_flag(self):
        """TOKEN_BUDGET_ALERT_FLAGS 常量集覆盖三档（raise_budget 复位单源）。"""
        assert TOKEN_BUDGET_ALERT_FLAGS == (
            "_token_warn_80", "_token_major_95", "_token_alert_100",
        )

    def test_major_fires_once_at_95_and_idempotent(self, tmp_path):
        """95% 首越触发 severity=major 告警；幂等标志持久、不重复发射、不冻结。"""
        proot = tmp_path / "proj"
        proot.mkdir()
        # 47M / 50M = 94%：80% 档已置位隔离（本轮只考察 95% 档）
        sm = make_state(proot, "spec-95", tokens_in=47_000_000)
        sm.update_spec("spec-95", {"_token_warn_80": True})
        runner = make_runner(proot)
        runner.state_machine = sm

        runner._token_accountant._accumulate_token_usage("spec-95", USAGE_1M)
        # 48M / 50M = 96% ≥ 95%
        entry = sm.read_one("spec-95")
        assert entry["_token_major_95"] is True
        assert entry["status"] == "implementing"  # 不自动冻结

        alerts = _token_alerts(proot)
        majors = [a for a in alerts if a.get("severity") == "major"]
        assert len(majors) == 1
        assert "近满" in majors[-1]["description"]
        rec = majors[-1].get("recommended_action") or ""
        # recommended_action 三处置选项齐备
        assert "token_conserve_ratio" in rec
        assert "冻结" in rec
        assert "raise_budget" in rec

        # 幂等：再次越线（仍 >=95%）不重复发射
        runner._token_accountant._accumulate_token_usage("spec-95", USAGE_1M)
        majors_after = [a for a in _token_alerts(proot)
                        if a.get("severity") == "major"]
        assert len(majors_after) == 1

    def test_jump_to_100_backfills_major(self, tmp_path):
        """80% 直跳 100% 跨过 95% 档：补发 major（不挂 elif 链不被拦截）。"""
        proot = tmp_path / "proj"
        proot.mkdir()
        sm = make_state(proot, "spec-jump", tokens_in=40_000_000)
        sm.update_spec("spec-jump", {"_token_warn_80": True})
        runner = make_runner(proot)
        runner.state_machine = sm
        # +10.5M → 50.5M = 101%
        runner._token_accountant._accumulate_token_usage("spec-jump", {
            "input_tokens": 10_500_000, "output_tokens": 0,
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            "cost_usd": None,
        })
        entry = sm.read_one("spec-jump")
        assert entry["_token_alert_100"] is True
        assert entry["_token_major_95"] is True
        alerts = _token_alerts(proot)
        assert [a["severity"] for a in alerts].count("major") == 1

    def test_below_95_tiers_unchanged(self, tmp_path):
        """80%-95% 区间：80% 档旧行为不变，95% 档不误触发。"""
        proot = tmp_path / "proj"
        proot.mkdir()
        sm = make_state(proot, "spec-80", tokens_in=38_000_000)
        runner = make_runner(proot)
        runner.state_machine = sm
        # +2.5M → 40.5M = 81%
        runner._token_accountant._accumulate_token_usage("spec-80", {
            "input_tokens": 2_500_000, "output_tokens": 0,
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            "cost_usd": None,
        })
        entry = sm.read_one("spec-80")
        assert entry["_token_warn_80"] is True
        assert not entry.get("_token_major_95")
        assert not entry.get("_token_alert_100")
        assert all(a.get("severity") == "warning" for a in _token_alerts(proot))

    def test_raise_budget_doubles_and_resets_all_flags(self, tmp_path):
        """raise_budget：生效预算翻倍 + 三档幂等标志全复位；复位后 95% 档可再触发。"""
        proot = tmp_path / "proj"
        proot.mkdir()
        spec = "spec-raise"
        sm = make_state(proot, spec, tokens_in=49_000_000)
        sm.update_spec(spec, {flag: True for flag in TOKEN_BUDGET_ALERT_FLAGS})
        # 项目级预算 50（翻倍基数取生效配置）
        write_config(proot, {"agents": {"token_budget_millions": 50}})

        result = _exec_raise_budget(proot, spec)
        assert result.get("ok") is True

        entry = sm.read_one(spec)
        for flag in TOKEN_BUDGET_ALERT_FLAGS:
            assert not entry.get(flag), f"{flag} 未复位"

        cfg = read_config(proot, "project")["agents"]["token_budget_millions"]
        assert float(cfg) == 100.0

        # 复位后预算 100M：爬到 >=95% 新预算 major 档可再次触发（不复位即静默）
        sm.update_spec(spec, {"_tokens_in": 94_000_000})
        runner = make_runner(proot, budget_millions=100)
        runner.state_machine = sm
        runner._token_accountant._accumulate_token_usage(spec, {
            "input_tokens": 1_500_000, "output_tokens": 0,
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            "cost_usd": None,
        })
        # 95.5M / 100M = 95.5%
        assert sm.read_one(spec)["_token_major_95"] is True
        assert [a for a in _token_alerts(proot)
                if a.get("severity") == "major"]


# ══════════════════ 4.2：judge 预算联合压缩 ══════════════════

class TestBudgetConserveState:
    def _state(self, proot, spec, tokens_in):
        sm = make_state(proot, spec, tokens_in=tokens_in)
        return sm

    def test_near_full_when_configured_and_reached(self, tmp_path):
        proot = tmp_path / "proj"
        sm = self._state(proot, "spec-cs", 49_000_000)
        pipeline = make_pipeline(proot, sm, {
            "agents.token_conserve_ratio": 0.95,
            "agents.token_budget_millions": 50,
        })
        state = _budget_conserve_state(pipeline, "spec-cs")
        assert state["enabled"] is True
        assert state["near_full"] is True
        assert state["ratio"] == pytest.approx(0.98)
        assert state["threshold"] == pytest.approx(0.95)

    def test_below_threshold_not_near_full(self, tmp_path):
        proot = tmp_path / "proj"
        sm = self._state(proot, "spec-cs2", 47_000_000)  # 94% < 95%
        pipeline = make_pipeline(proot, sm, {
            "agents.token_conserve_ratio": 0.95,
            "agents.token_budget_millions": 50,
        })
        state = _budget_conserve_state(pipeline, "spec-cs2")
        assert state["enabled"] is True
        assert state["near_full"] is False
        assert state["ratio"] == pytest.approx(0.94)

    @pytest.mark.parametrize("bad_cfg", [
        None,  # 未配置（缺省关闭）
        True,  # bool 拒绝
        "0.95",  # 非数值拒绝
        1.5,  # 越上界
        0,  # 越下界
    ])
    def test_invalid_threshold_disabled(self, tmp_path, bad_cfg):
        proot = tmp_path / "proj"
        sm = self._state(proot, f"spec-bad-{bad_cfg!r}", 49_000_000)
        cfg = {"agents.token_budget_millions": 50}
        if bad_cfg is not None:
            cfg["agents.token_conserve_ratio"] = bad_cfg
        pipeline = make_pipeline(proot, sm, cfg)
        state = _budget_conserve_state(pipeline, f"spec-bad-{bad_cfg!r}")
        assert state["enabled"] is False
        assert state["near_full"] is False

    def test_budget_zero_or_invalid_disabled(self, tmp_path):
        proot = tmp_path / "proj"
        for budget in (0, -1, "x"):
            spec = f"spec-b-{budget!r}"
            sm = self._state(proot, spec, 49_000_000)
            pipeline = make_pipeline(proot, sm, {
                "agents.token_conserve_ratio": 0.95,
                "agents.token_budget_millions": budget,
            })
            state = _budget_conserve_state(pipeline, spec)
            assert state["enabled"] is False
            assert state["near_full"] is False


class TestJudgeConserveCompression:
    def _setup(self, tmp_path, spec, conserve=0.95):
        proot = tmp_path / "proj"
        sm = make_state(proot, spec, tokens_in=49_000_000)
        notifier = RecordingNotifier()
        cfg = {"agents.token_budget_millions": 50}
        if conserve is not None:
            cfg["agents.token_conserve_ratio"] = conserve
        pipeline = make_pipeline(proot, sm, cfg, notifier=notifier)
        return proot, sm, pipeline, notifier

    def test_spec_rerun_allowance_compressed_to_one(self, tmp_path):
        """近满+启用：压缩生效后仅再放行 1 次派发，第 2 次冻结且文案注明预算近满。"""
        proot, sm, pipeline, notifier = self._setup(tmp_path, "spec-cc")
        # 压缩生效时已有 1 次重跑计数 → 基线锚定 1，剩余额度 1
        sm.update_spec("spec-cc", {"_judge_rerun_count": 1})

        # 第 1 次（count=2 ≤ 基线+1）放行
        r1 = _judge_dispatch_gate(pipeline, "spec-cc")
        assert r1 is None
        assert not sm.read_one("spec-cc").get("_judge_cap_frozen")

        # 第 2 次（count=3 > 基线+1）冻结停派
        r2 = _judge_dispatch_gate(pipeline, "spec-cc")
        assert r2 is False
        entry = sm.read_one("spec-cc")
        assert entry["_judge_cap_frozen"] is True
        err = str(entry.get("error") or "")
        assert "预算近满" in err
        assert f"压缩为 {_JUDGE_CONSERVE_REMAINING}" in err
        # 冻结人工升级告警：major + 预算近满文案 + raise_budget 处置提示；
        # description 共享后缀只拼一次（cap_text 已带「已冻结」不再重复追加）
        assert len(notifier.calls) == 1
        freeze_call = notifier.calls[0]
        assert freeze_call["signal_type"] == "judge_rerun_cap"
        assert freeze_call["severity"] == "major"
        assert "预算近满" in freeze_call["description"]
        assert (
            freeze_call["description"].count("已冻结等待人工裁决") == 1
        )
        assert "raise_budget" in freeze_call["recommended_action"]

    def test_round_cap_compressed_and_text_annotated(self, tmp_path):
        """轮内真实派发 1 次即停派升级（上限 2→1），告警注明预算近满。"""
        proot, sm, pipeline, notifier = self._setup(tmp_path, "spec-round")
        _write_report(proot, "spec-round", ts="ts-r1")
        # 同轮已有 1 次真实派发（压缩生效前）；调用点在 testing 阶段
        sm.update_spec("spec-round", {"status": "testing"})
        sm.update_spec("spec-round", {
            "_verify_fail_rounds": 1,
            "_judge_round_id": 1,
            "_judge_round_report_key": "ts-r1",
            "_judge_round_real": 1,
            "_judge_rerun_count": 1,
        })
        r = _judge_dispatch_gate(pipeline, "spec-round")
        assert r is False  # 轮内停派（非冻结）
        entry = sm.read_one("spec-round")
        assert entry["_judge_round_escalated"] is True
        assert not entry.get("_judge_cap_frozen")
        assert entry["status"] == "testing"  # 保持可重试
        assert len(notifier.calls) == 1
        call = notifier.calls[0]
        assert call["signal_type"] == "judge_round_rerun_cap"
        assert "预算近满" in call["description"]
        assert "budget_near_full=True" in call["evidence"]
        assert "token_conserve_ratio" in call["recommended_action"]

    def test_round_cap_default_two_when_not_conserving(self, tmp_path):
        """未近满：轮内 1 次派发后仍放行第 2 次（上限 2 零回归）。"""
        proot, sm, pipeline, notifier = self._setup(tmp_path, "spec-round2",
                                                    conserve=None)
        _write_report(proot, "spec-round2", ts="ts-r2")
        sm.update_spec("spec-round2", {
            "_verify_fail_rounds": 1,
            "_judge_round_id": 1,
            "_judge_round_report_key": "ts-r2",
            "_judge_round_real": 1,
            "_judge_rerun_count": 1,
        })
        r = _judge_dispatch_gate(pipeline, "spec-round2")
        assert r is None  # 轮内第 2 次照常派发
        assert notifier.calls == []
        assert sm.read_one("spec-round2")["_judge_round_real"] == "2"

    def test_legacy_hard_cap_text_unchanged(self, tmp_path):
        """未配置收敛：常规硬上限 5 触顶冻结，文案保持既有形态（无预算近满字样）。"""
        proot, sm, pipeline, notifier = self._setup(tmp_path, "spec-cap",
                                                    conserve=None)
        sm.update_spec("spec-cap", {"_judge_rerun_count": _MAX_JUDGE_RERUNS})
        r = _judge_dispatch_gate(pipeline, "spec-cap")
        assert r is False
        entry = sm.read_one("spec-cap")
        err = str(entry.get("error") or "")
        assert f"{_MAX_JUDGE_RERUNS + 1}/{_MAX_JUDGE_RERUNS} 轮" in err
        assert "预算近满" not in err


# ══════════════════ 4.3：预算近满收敛复验 ══════════════════

# [fenix-ignore:0787dca1e58c] 2026-11-22T03:57Z 回归快照 setup ENOENT 系共享 basetemp 被并发会话中途删除的隔离设施事故（非本文件缺陷），根因已随 687b722c6+64bc07514 修复（pid 唯一根/每用例生命线守卫/共享根不收尾删），本类用例当前树实测全绿
# [fenix-ignore:10e34ad5daa1] 2026-11-22T03:57Z 回归快照 setup ENOENT 系共享 basetemp 被并发会话中途删除的隔离设施事故（非本文件缺陷），根因已随 687b722c6+64bc07514 修复（pid 唯一根/每用例生命线守卫/共享根不收尾删），本类用例当前树实测全绿
# [fenix-ignore:6122cd96d54d] 2026-11-22T03:57Z 回归快照 setup ENOENT 系共享 basetemp 被并发会话中途删除的隔离设施事故（非本文件缺陷），根因已随 687b722c6+64bc07514 修复（pid 唯一根/每用例生命线守卫/共享根不收尾删），本类用例当前树实测全绿
# [fenix-ignore:6fdc25822f23] 2026-11-22T03:57Z 回归快照 setup ENOENT 系共享 basetemp 被并发会话中途删除的隔离设施事故（非本文件缺陷），根因已随 687b722c6+64bc07514 修复（pid 唯一根/每用例生命线守卫/共享根不收尾删），本类用例当前树实测全绿
# [fenix-ignore:b7f27fd5262f] 2026-11-22T03:57Z 回归快照 setup ENOENT 系共享 basetemp 被并发会话中途删除的隔离设施事故（非本文件缺陷），根因已随 687b722c6+64bc07514 修复（pid 唯一根/每用例生命线守卫/共享根不收尾删），本类用例当前树实测全绿
class TestConvergeReverifyDecision:
    """_budget_conserve_decision 判定与仲裁（不产生状态变更）。"""

    def _pipeline(self, tmp_path, spec, fail_ids, conserve=0.95,
                  repair_depth=0, has_frozen=True):
        proot = tmp_path / "proj"
        sm = make_state(proot, spec, tokens_in=49_000_000)
        cfg = {"agents.token_budget_millions": 50}
        if conserve is not None:
            cfg["agents.token_conserve_ratio"] = conserve
        pipeline = make_pipeline(proot, sm, cfg)
        _write_scenarios(proot, spec)
        _write_report(proot, spec, fail_ids=fail_ids)
        return proot, pipeline

    def test_active_subset_union_of_failed_plus_chain(self, tmp_path):
        """s2/s5 失败 → 子集 = {s2,s5} ∪ 前置链 {s1} ∪ 下游 {s4}（按场景序）。"""
        spec = "spec-active"
        proot, pipeline = self._pipeline(tmp_path, spec, fail_ids={"s2", "s5"})
        decision = pipeline._budget_conserve_decision(spec, has_frozen=True)
        assert decision["active"] is True
        assert decision["subset_ids"] == ["s1", "s2", "s4", "s5"]

    def test_inactive_when_not_configured(self, tmp_path):
        spec = "spec-off"
        proot, pipeline = self._pipeline(tmp_path, spec, fail_ids={"s2"},
                                         conserve=None)
        decision = pipeline._budget_conserve_decision(spec, has_frozen=True)
        assert decision["active"] is False
        assert "未配置" in decision["reason"]

    def test_inactive_when_not_near_full(self, tmp_path):
        spec = "spec-low"
        proot, pipeline = self._pipeline(tmp_path, spec, fail_ids={"s2"})
        sm = pipeline._context.state_machine
        sm.update_spec(spec, {"_tokens_in": 10_000_000})  # 20% 远低于阈值
        decision = pipeline._budget_conserve_decision(spec, has_frozen=True)
        assert decision["active"] is False

    def test_first_round_empty_subset_falls_back(self, tmp_path):
        """首轮验证（无冻结集且报告全绿）：空子集守卫回落全量口径。"""
        spec = "spec-fresh"
        proot, pipeline = self._pipeline(tmp_path, spec, fail_ids=set())
        decision = pipeline._budget_conserve_decision(spec, has_frozen=False)
        assert decision["active"] is False
        assert "空" in decision["reason"] or "全量" in decision["reason"]

    def test_repair_round_has_priority_over_converge(self, tmp_path):
        """通道仲裁：场景修订重验（_repair_depth>0）优先，收敛让位。"""
        spec = "spec-arb"
        proot, pipeline = self._pipeline(tmp_path, spec, fail_ids={"s2"})
        decision = pipeline._budget_conserve_decision(
            spec, has_frozen=True, _repair_depth=1)
        assert decision["active"] is False
        assert "修订" in decision["reason"] or "让位" in decision["reason"]


class TestConvergeReverifyExecution:
    """_execute_budget_conserve_round 执行与回落。"""

    def _pipeline_with_stub(self, tmp_path, spec, fail_ids={"s2", "s5"}):
        proot = tmp_path / "proj"
        sm = make_state(proot, spec, tokens_in=49_000_000)
        pipeline = make_pipeline(proot, sm, {
            "agents.token_conserve_ratio": 0.95,
            "agents.token_budget_millions": 50,
        })
        _write_scenarios(proot, spec)
        _write_report(proot, spec, fail_ids=fail_ids)
        calls = []

        def fake_stage2(spec_name, verify_dir, scenarios_path, skip_prune=False):
            calls.append({"path": Path(scenarios_path),
                          "skip_prune": skip_prune})
            if len(calls) == 1:
                # 子集轮：报告只含子集场景
                subset_ids = json.loads(
                    Path(scenarios_path).read_text(encoding="utf-8"))
                rep = {"timestamp": "ts-subset", "scenarios": [
                    {"scenario_id": s["id"], "status": "fail"}
                    for s in subset_ids if s["id"] in fail_ids
                ] + [
                    {"scenario_id": s["id"], "status": "pass"}
                    for s in subset_ids if s["id"] not in fail_ids
                ]}
                return None, rep, True, "ok", False
            # 回落全量轮
            return None, {"timestamp": "ts-full", "scenarios": [
                {"scenario_id": s["id"],
                 "status": "fail" if s["id"] in fail_ids else "pass"}
                for s in SCENARIOS
            ]}, True, "ok", False

        pipeline._execute_stage2 = fake_stage2
        return proot, pipeline, calls

    def _decision(self, pipeline, spec):
        return pipeline._budget_conserve_decision(spec, has_frozen=True)

    def test_subset_round_merges_and_annotates(self, tmp_path):
        spec = "spec-exec"
        proot, pipeline, calls = self._pipeline_with_stub(tmp_path, spec)
        verify_dir = proot / ".fenix" / "verify-progress" / spec
        decision = self._decision(pipeline, spec)

        env_error, report, reachable, note, aborted = (
            pipeline._execute_budget_conserve_round(spec, verify_dir, decision))
        assert env_error is None and aborted is False and reachable is True

        # 子集文件 + skip_prune=True
        assert calls[0]["path"].name == "test_scenarios.token-conserve.json"
        assert calls[0]["skip_prune"] is True
        subset_ids = [s["id"] for s in json.loads(
            calls[0]["path"].read_text(encoding="utf-8"))]
        assert subset_ids == ["s1", "s2", "s4", "s5"]

        # 合并报告：全场景在册（子集外沿用上一轮判定）+ token_conserve 注明模式
        merged = load_report(proot, spec)
        by_id = {sc["scenario_id"]: sc for sc in merged["scenarios"]}
        assert set(by_id) == {"s1", "s2", "s3", "s4", "s5"}
        assert merged["token_conserve"]["mode"] == "converge-reverify"
        assert merged["token_conserve"]["threshold"] == 0.95
        assert "收敛" in merged["token_conserve"]["note"]
        # 子集内用本轮结论，子集外（s3）沿用上一轮 pass
        assert by_id["s2"]["status"] == "fail"
        assert by_id["s3"]["status"] == "pass"

    def test_falls_back_to_full_on_subset_failure(self, tmp_path):
        """子集执行报告残缺 → 回写上一轮报告 + 回落全量口径。"""
        spec = "spec-fb"
        proot, pipeline, calls = self._pipeline_with_stub(tmp_path, spec)

        def broken_stage2(spec_name, verify_dir, scenarios_path,
                          skip_prune=False):
            calls.append({"path": Path(scenarios_path),
                          "skip_prune": skip_prune})
            if len(calls) == 1:
                return None, None, True, "", False  # 报告残缺
            return None, {"timestamp": "ts-full", "scenarios": [
                {"scenario_id": s["id"], "status": "pass"} for s in SCENARIOS
            ]}, True, "ok", False

        pipeline._execute_stage2 = broken_stage2
        verify_dir = proot / ".fenix" / "verify-progress" / spec
        decision = self._decision(pipeline, spec)
        env_error, report, reachable, note, aborted = (
            pipeline._execute_budget_conserve_round(spec, verify_dir, decision))
        # 第二次调用即全量回落（test_scenarios.json 原文件）
        assert calls[1]["path"].name == "test_scenarios.json"
        assert report["timestamp"] == "ts-full"
        # 规范 report.json 已被上一轮全量报告回写（不残留子集残缺态）
        assert load_report(proot, spec)["timestamp"] == "ts-1"

    def test_decision_inactive_stage2_untouched(self, tmp_path):
        """未配置收敛：stage2 派发点不切子集（全量口径零行为）。"""
        spec = "spec-noconserve"
        proot = tmp_path / "proj"
        sm = make_state(proot, spec, tokens_in=10_000_000)
        pipeline = make_pipeline(proot, sm, {"agents.token_budget_millions": 50})
        _write_scenarios(proot, spec)
        _write_report(proot, spec, fail_ids={"s2"})
        decision = pipeline._budget_conserve_decision(spec, has_frozen=True)
        assert decision["active"] is False
        assert decision["subset_ids"] == []


# ══════════════════ 4.4：配置键受管登记 ══════════════════

class TestConfigConserveRatio:
    def test_write_then_read_roundtrip(self, tmp_path):
        """write_config 落盘 + read_config 回显 + project 来源标注。"""
        proot = tmp_path / "proj"
        proot.mkdir()
        result = write_config(proot, {"agents": {"token_conserve_ratio": 0.95}})
        assert result.get("ok") is True

        view = read_config(proot, "project")
        assert view["agents"]["token_conserve_ratio"] == pytest.approx(0.95)
        assert view["sources"]["agents.token_conserve_ratio"] == "project"

    def test_effective_config_echo(self, tmp_path):
        """read_effective_config 回显归一（float 形态）。"""
        proot = tmp_path / "proj"
        proot.mkdir()
        write_config(proot, {"agents": {"token_conserve_ratio": 0.9}})
        eff = read_effective_config(proot)
        assert eff["agents"]["token_conserve_ratio"] == pytest.approx(0.9)

    def test_write_rejects_invalid_values(self, tmp_path):
        """前置校验：非法值拒绝且不落盘。"""
        proot = tmp_path / "proj"
        proot.mkdir()
        write_config(proot, {"agents": {"token_conserve_ratio": 0.95}})
        for bad in (1.5, 0, "0.95", True):
            result = write_config(
                proot, {"agents": {"token_conserve_ratio": bad}})
            assert result.get("ok") is False, f"非法值 {bad!r} 未被拒绝"
            assert "token_conserve_ratio" in str(result.get("error"))
        # 原合法值未被破坏
        assert (read_config(proot, "project")["agents"]
                ["token_conserve_ratio"]) == pytest.approx(0.95)

    def test_default_echo_none_when_absent(self, tmp_path):
        """缺省回显 None（缺省关闭语义）。"""
        proot = tmp_path / "proj"
        proot.mkdir()
        view = read_config(proot, "project")
        assert view["agents"]["token_conserve_ratio"] is None
