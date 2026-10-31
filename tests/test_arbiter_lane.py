"""add-arbiter-lane 6.1：触发面 / dedup / 单飞 / 死人开关 / 显式 status 解冻测试。

覆盖 tasks 1.1 / 1.2 / 1.3 / 2.3 / 4.1（run 段）/ 5.1 判定面：
- 触发面五态：机器冻结触发（freeze_for_human 咽喉入队）、人工冻结不触发
  （freeze_spec 零接触）、定时冻结不触发（frozen_until 路径零接触）、
  condition 排除（token 预算 / spec_integrity / queue 异常类）；
- 同签名 dedup（双咽喉各报一次只派发一次 + alert 补绑）与同签名复发直接升级；
- 单飞：全局队列串行、排队登记失败显式报错（RuntimeError 不吞）；
- 死人开关三路径：连败达阈值 / 墙钟超限 / token 超限 → 半成品包升级台账；
- 显式 status 解冻断言：报告带合法 status_after → unfreeze_spec(spec,
  status=<显式值>)；缺显式 status → 解冻不执行留冻结待人工。

worker 为 daemon 线程：确定性等待以 queue.unfinished_tasks 轮询（有界），
不做无界 sleep。测试全程不触网、不真调网关。
"""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.pm_engine.arbiter import (
    ARBITER_EXCLUDED_SIGNAL_TYPES,
    ArbiterLane,
    arbiter_failure_signature,
    arbiter_report_path,
    ledger_entry_complete,
    load_arbiter_ledger,
    reset_lane,
)


# ── 夹具助手 ────────────────────────────────────────────

class FakeLogger:
    def __init__(self):
        self.records = []

    def info(self, component, message, context=None):
        self.records.append(("info", component, message))

    def warning(self, component, message, context=None):
        self.records.append(("warning", component, message))

    def error(self, component, message, context=None):
        self.records.append(("error", component, message))


class FakeRunner:
    """调查 run 门面替身：_run_agent 按脚本写报告/抛异常。"""

    def __init__(self, project_root, script=None, pinned_model="glm-5.3-flash"):
        self.project_root = Path(project_root)
        self.script = script or {}
        self.pinned_model = pinned_model
        self.observed_models = []
        self.run_agent_calls = []
        self._run_harness = {}
        self.shutting_down = False

    def _build_prompt(self, spec, agent_type, detail=None):
        return f"prompt[{agent_type}/{spec}]"

    def _get_agent_model_assignment(self, agent_type):
        return None  # 无分配 → 钉死模型链

    def _get_config(self, key, default=None):
        return default

    def _run_was_interrupted(self, run_file):
        return False

    def _record_signal_kill_or_label(self, spec, error, exit_code,
                                     framework_terminate=False):
        return error

    def _run_agent(self, prompt, project_root, run_id, model_override,
                   env_overrides, max_turns=300, spec_name=None, agent_type=None):
        self.run_agent_calls.append(run_id)
        self.observed_models.append(model_override)
        action = self.script.get("run")
        if action == "raise":
            raise RuntimeError("gateway stall")
        report = action or {}
        path = arbiter_report_path(self.project_root, run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        usage = self.script.get("usage") or {
            "input_tokens": 100, "output_tokens": 50,
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
        }
        return ("", 1, None, usage, None)


class FakeStateMachine:
    def __init__(self, entries=None):
        self.entries = dict(entries or {})
        self.unfreeze_calls = []
        self.added_specs = []

    def read_all(self):
        return dict(self.entries)

    def unfreeze_spec(self, spec_name, status=None, project_root=None,
                      worktree_manager=None):
        self.unfreeze_calls.append((spec_name, status))
        entry = dict(self.entries.get(spec_name) or {})
        entry["frozen"] = False
        if status:
            entry["status"] = status
        self.entries[spec_name] = entry
        return True

    def add_spec(self, spec_name, entry):
        if spec_name in self.entries:
            return False
        self.entries[spec_name] = dict(entry)
        self.added_specs.append(spec_name)
        return True


def make_lane(tmp_path, config=None, runner=None, sm=None):
    lane = ArbiterLane(tmp_path, FakeLogger())
    lane.set_runner(runner or FakeRunner(tmp_path))
    lane.set_state_machine(sm or FakeStateMachine())
    if config is not None:
        lane.config = lambda: {
            "enabled": config.get("enabled", True),
            "budget_wallclock_s": config.get("budget_wallclock_s", 1800),
            "budget_tokens": config.get("budget_tokens", 1000000),
            "max_consecutive_failures": config.get(
                "max_consecutive_failures", 2),
        }
    return lane


def drain(lane, timeout_s=15.0):
    """确定性等待 worker 清空队列（有界轮询，不无界 sleep）。

    15s 预算：宿主机高载（并行前端构建等）下 5s 会假超时——drain 返回
    False 后续台账断言提前执行即红（load-flake 实测）；worker 处理本身
    毫秒级，15s 仅 absorb 调度饥饿。
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if lane._queue.unfinished_tasks == 0 and not lane._active:
            return True
        time.sleep(0.01)
    return False


@pytest.fixture(autouse=True)
def _lane_cleanup():
    yield
    reset_lane()


# ── 触发面五态 ──────────────────────────────────────────

class TestTriggerSurface:
    def test_machine_freeze_triggers_lane(self, tmp_path):
        """机器冻结（freeze_for_human 咽喉）→ Arbiter 入队（enabled）。"""
        from core import state_machine as sm_mod
        from core.state_machine import StateMachine

        state = tmp_path / ".fenix" / "STATE.md"
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text("# Fenix Project State\n## Specs\n", encoding="utf-8")
        sm = StateMachine(state, MagicMock())
        sm.add_spec("spec-a", {"status": "testing"})

        lane = make_lane(tmp_path)
        submitted = []

        def hook(**kw):
            submitted.append(kw)
            lane.submit_trigger(
                spec=str(kw.get("spec_name")),
                signal_type=str(kw.get("signal_type")),
                source="freeze_for_human",
            )

        sm_mod.set_arbiter_freeze_hook(hook)
        try:
            alerts = []
            ok = sm.freeze_for_human(
                "spec-a",
                error="验证连续失败",
                signal_type="verify_fail_escalation",
                severity="major",
                description="d",
                evidence="e",
                recommended_action="r",
                alert_callback=lambda **kw: alerts.append(kw),
            )
            assert ok is True
        finally:
            sm_mod.set_arbiter_freeze_hook(None)
        # 咽喉先告警后派发：alert 回调与 Arbiter 派发各一次
        assert alerts and alerts[0]["spec_name"] == "spec-a"
        assert submitted and submitted[0]["spec_name"] == "spec-a"
        # worker 可能已秒消费（qsize 竞态）：以 run 实际发生为准
        assert drain(lane)
        assert len(lane._resolve_runner().run_agent_calls) == 1

    def test_manual_freeze_never_calls_hook(self, tmp_path):
        """人工冻结（freeze_spec）零接触：咽喉回调不被调用。"""
        from core.state_machine import StateMachine

        state = tmp_path / ".fenix" / "STATE.md"
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text("# Fenix Project State\n## Specs\n", encoding="utf-8")
        sm = StateMachine(state, MagicMock())
        sm.add_spec("spec-a", {"status": "ready"})
        calls = []
        sm_mod_hook = lambda **kw: calls.append(kw)
        sm_mod = __import__("core.state_machine", fromlist=["x"])
        sm_mod.set_arbiter_freeze_hook(sm_mod_hook)
        try:
            ok = sm.freeze_spec("spec-a", "用户指令冻结：测试")
            assert ok is True
            assert calls == [], "freeze_spec（人工冻结）MUST NOT 触发 Arbiter 咽喉"
            entry = sm.read_one("spec-a")
            assert entry.get("frozen") is True
        finally:
            sm_mod.set_arbiter_freeze_hook(None)

    def test_frozen_until_scheduled_freeze_never_calls_hook(self, tmp_path):
        """定时冻结（frozen_until）零接触：调度自愈路径不经咽喉。"""
        from core.state_machine import StateMachine

        state = tmp_path / ".fenix" / "STATE.md"
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text("# Fenix Project State\n## Specs\n", encoding="utf-8")
        sm = StateMachine(state, MagicMock())
        sm.add_spec("spec-a", {"status": "ready"})
        calls = []
        sm_mod = __import__("core.state_machine", fromlist=["x"])
        sm_mod.set_arbiter_freeze_hook(lambda **kw: calls.append(kw))
        try:
            # frozen_until 定时冻结走 update_spec 直写字段（mark_frozen_hold /
            # frozen_until 调度器路径），不经 freeze_for_human 咽喉
            ok = sm.update_spec("spec-a", {"frozen": True, "frozen_until": "2030-01-01T00:00:00Z"})
            assert ok is True
            assert calls == [], "frozen_until 定时冻结 MUST NOT 触发 Arbiter 咽喉"
        finally:
            sm_mod.set_arbiter_freeze_hook(None)

    def test_excluded_signal_types(self):
        """condition 排除表：token 预算 / spec_integrity / queue 异常类不进。"""
        lane = ArbiterLane(Path("/tmp"), None)
        for sig in (
            "impl_budget_exhausted",      # token 预算
            "impl_budget_exempt_loop",
            "spec_content_missing",       # spec_integrity
            "spec_delivered_no_content",
            "redispatch_loop_detected",   # queue 异常
        ):
            assert sig in ARBITER_EXCLUDED_SIGNAL_TYPES
            assert lane.in_trigger_surface(sig) is False
        assert lane.in_trigger_surface("verify_fail_escalation") is True

    def test_disabled_lane_returns_disabled(self, tmp_path):
        """enabled=false：submit 返回 disabled，零写入零派发。"""
        lane = make_lane(tmp_path, config={"enabled": False})
        assert lane.submit_trigger(spec="spec-a", signal_type="verify_fail_escalation") == "disabled"
        assert lane._queue.qsize() == 0
        assert load_arbiter_ledger(tmp_path) == []


# ── dedup / 复发 ────────────────────────────────────────

class TestDedupAndRecurrence:
    def test_double_throat_single_dispatch_with_alert_bind(self, tmp_path):
        """双咽喉同签名：首个 queued、第二个 deduped 且 alert 补绑。"""
        lane = make_lane(tmp_path)
        out1 = lane.submit_trigger(spec="spec-a", signal_type="verify_fail_escalation",
                           alert_id=None)
        assert out1 == "queued"
        out2 = lane.submit_for_alert(
            None, {"spec": "spec-a", "signal_type": "verify_fail_escalation"},
            "alert-1",
        )
        assert out2 == "deduped"
        assert drain(lane)
        # alert-1 经补绑进入触发，处置升级路径有挂靠目标（台账/告警以
        # _process_trigger 结果为准，这里只断言补绑生效不抛）

    def test_recurrence_escalates_without_run(self, tmp_path):
        """同签名处置成功后复发：不再派发，直接产裁决包升级（design D6）。"""
        report = {"outcome": "resolved", "summary": "s", "root_cause": "r",
                  "scene_snapshot": "snap", "forensic_timeline": [],
                  "actions_taken": ["a"], "evidence_refs": ["e"],
                  "status_after": "ready"}
        runner = FakeRunner(tmp_path, script={"run": report})
        sm = FakeStateMachine()
        lane = make_lane(tmp_path, runner=runner, sm=sm)
        # 第一轮：自主处置成功（sig 进 _dispositioned）
        lane.submit_trigger(spec="spec-a", signal_type="verify_fail_escalation")
        assert drain(lane)
        first_runs = len(runner.run_agent_calls)
        assert first_runs >= 1
        # 同根因复发（新触发、同签名）：不再自主处置，直接升级
        out = lane.submit_for_alert(
            None, {"spec": "spec-a", "signal_type": "verify_fail_escalation",
                   "description": "再次冻结"},
            "alert-2",
        )
        assert out == "recurrence-escalated"
        assert len(runner.run_agent_calls) == first_runs, "复发 MUST NOT 再派发 run"
        kinds = [rec["kind"] for rec in load_arbiter_ledger(tmp_path)]
        assert "recurrence-escalation" in kinds


# ── 单飞 ────────────────────────────────────────────────

class TestSingleFlight:
    def test_queue_full_raises_explicitly(self, tmp_path):
        """排队登记失败（队列满）显式报错，不吞 conflict 报假成功。"""
        lane = make_lane(tmp_path)
        # 不启动 worker（monkeypatch _ensure_worker 为 no-op）填满队列
        lane._ensure_worker = lambda: None
        outcomes = []
        for i in range(8):  # ARBITER_QUEUE_MAX
            outcomes.append(
                lane.submit_trigger(spec=f"spec-{i}", signal_type="verify_fail_escalation")
            )
        assert all(o == "queued" for o in outcomes)
        with pytest.raises(RuntimeError, match="队列已满"):
            lane.submit_trigger(spec="spec-overflow", signal_type="verify_fail_escalation")

    def test_worker_consumes_serially(self, tmp_path):
        """worker 串行消费：多触发依次处理，全部终态后 _active 清空。"""
        runner = FakeRunner(tmp_path, script={"run": {"outcome": "resolved",
                                                      "summary": "s",
                                                      "root_cause": "r",
                                                      "scene_snapshot": "snap",
                                                      "forensic_timeline": [],
                                                      "actions_taken": ["a1"],
                                                      "evidence_refs": ["e1"],
                                                      "status_after": "ready"}})
        sm = FakeStateMachine({"spec-a": {"status": "blocked", "frozen": True}})
        lane = make_lane(tmp_path, runner=runner, sm=sm)
        lane.submit_trigger(spec="spec-a", signal_type="verify_fail_escalation")
        assert drain(lane)
        assert len(runner.run_agent_calls) == 1
        assert lane._active == set()


# ── 死人开关三路径 ──────────────────────────────────────

class TestDeadManSwitch:
    def _escalation_targets(self, tmp_path, lane):
        """断言台账含 dead-man 且告警升级路径被调用（经 ledger 检查）。"""
        kinds = [rec["kind"] for rec in load_arbiter_ledger(tmp_path)]
        assert "dead-man" in kinds
        return kinds

    def test_consecutive_failures_trigger_deadman(self, tmp_path):
        """连败 2 次（缺省阈值）→ dead-man 升级。"""
        runner = FakeRunner(tmp_path, script={"run": "raise"})
        lane = make_lane(tmp_path, runner=runner)
        lane.submit_trigger(spec="spec-a", signal_type="verify_fail_escalation",
                    alert_id="alert-1")
        assert drain(lane)
        lane.submit_trigger(spec="spec-a", signal_type="verify_fail_escalation",
                    alert_id="alert-1")
        assert drain(lane)
        self._escalation_targets(tmp_path, lane)
        # 第三次同签名：复发语义（不派发）——_dispatched 已含
        out = lane.submit_trigger(spec="spec-a", signal_type="verify_fail_escalation")
        assert out == "recurrence-escalated"

    def test_single_failure_retries_without_deadman(self, tmp_path):
        """单次失败留重试余量：不升级、台账 kind=failed。"""
        runner = FakeRunner(tmp_path, script={"run": "raise"})
        lane = make_lane(tmp_path, runner=runner)
        lane.submit_trigger(spec="spec-b", signal_type="verify_fail_escalation")
        assert drain(lane)
        kinds = [rec["kind"] for rec in load_arbiter_ledger(tmp_path)]
        assert "failed" in kinds
        assert "dead-man" not in kinds

    def test_wallclock_budget_exhaustion_upgrades(self, tmp_path):
        """墙钟超限（elapsed_s > budget_wallclock_s）→ 半成品包升级。"""
        report = {"outcome": "resolved", "summary": "s", "root_cause": "r",
                  "scene_snapshot": "snap", "forensic_timeline": [],
                  "actions_taken": ["a"], "evidence_refs": ["e"],
                  "status_after": "ready"}
        runner = FakeRunner(tmp_path, script={"run": report})
        lane = make_lane(tmp_path, runner=runner,
                         config={"budget_wallclock_s": 1})
        # 注入超墙钟 elapsed_s（模拟 run 超时路径——真实链路由
        # _effective_run_timeout 封顶后超时抛出，此处直击预算记账判定）
        orig = lane._run_investigation

        def fake_investigation(trigger):
            result = orig(trigger)
            result["budget"]["elapsed_s"] = 9999.0
            result["budget"]["wallclock_exhausted"] = True
            # 超墙钟时 run 已被框架终止 → 无报告按失败信封
            result["ok"] = False
            result["error"] = "wallclock budget exceeded"
            result["report"] = {}
            return result

        lane._run_investigation = fake_investigation
        lane.submit_trigger(spec="spec-c", signal_type="verify_fail_escalation")
        assert drain(lane)
        self._escalation_targets(tmp_path, lane)

    def test_token_budget_exhaustion_upgrades(self, tmp_path):
        """token 超限且 run 失败 → 停止自主尝试、半成品包升级（不重试烧预算）。

        语义：token 预算是事后记账（usage 四键累计）；run 正常完成且报告合法
        时处置照常成立（超限入台账审计），超限升级发生在 run 失败路径——
        与死人开关同槽位判定，防止超限后继续重试烧预算。
        """
        runner = FakeRunner(tmp_path, script={"run": "raise"})
        lane = make_lane(tmp_path, runner=runner, config={"budget_tokens": 1000})
        orig = lane._run_investigation

        def fake_investigation(trigger):
            result = orig(trigger)
            result["budget"]["tokens_used"] = 2_000_000
            result["budget"]["tokens_exhausted"] = True
            result["ok"] = False
            result["error"] = "token budget exceeded mid-run"
            result["report"] = {}
            return result

        lane._run_investigation = fake_investigation
        lane.submit_trigger(spec="spec-d", signal_type="verify_fail_escalation")
        assert drain(lane)
        self._escalation_targets(tmp_path, lane)
        recs = load_arbiter_ledger(tmp_path)
        dm = [r for r in recs if r["kind"] == "dead-man"]
        assert dm and "预算耗尽" in dm[-1]["action_or_upgrade"]

    def test_over_budget_valid_disposition_still_stands(self, tmp_path):
        """超预算但报告合法的 run：处置成立，超限只入台账审计。"""
        report = {"outcome": "resolved", "summary": "s", "root_cause": "r",
                  "scene_snapshot": "snap", "forensic_timeline": [],
                  "actions_taken": ["a"], "evidence_refs": ["e"],
                  "status_after": "ready"}
        runner = FakeRunner(
            tmp_path,
            script={"run": report,
                    "usage": {"input_tokens": 2_000_000, "output_tokens": 0,
                              "cache_creation_input_tokens": 0,
                              "cache_read_input_tokens": 0}},
        )
        sm = FakeStateMachine({"spec-e": {"status": "blocked", "frozen": True}})
        lane = make_lane(tmp_path, runner=runner, sm=sm,
                         config={"budget_tokens": 1000})
        lane.submit_trigger(spec="spec-e", signal_type="verify_fail_escalation")
        assert drain(lane)
        recs = load_arbiter_ledger(tmp_path)
        kinds = [r["kind"] for r in recs]
        assert "disposition" in kinds
        assert "dead-man" not in kinds
        disp = [r for r in recs if r["kind"] == "disposition"][-1]
        assert disp["budget"]["tokens_exhausted"] is True


# ── 显式 status 解冻 ────────────────────────────────────

class TestExplicitStatusUnfreeze:
    REPORT = {"outcome": "resolved", "summary": "s", "root_cause": "r",
              "scene_snapshot": "snap", "forensic_timeline": [],
              "actions_taken": ["a"], "evidence_refs": ["e"]}

    def test_unfreeze_with_explicit_status(self, tmp_path):
        """合法显式 status_after → unfreeze_spec(spec, status=<显式值>)。"""
        runner = FakeRunner(tmp_path, script={"run": {**self.REPORT,
                                                      "status_after": "testing"}})
        sm = FakeStateMachine({"spec-a": {"status": "blocked", "frozen": True}})
        lane = make_lane(tmp_path, runner=runner, sm=sm)
        lane.submit_trigger(spec="spec-a", signal_type="verify_fail_escalation")
        assert drain(lane)
        assert sm.unfreeze_calls == [("spec-a", "testing")]

    def test_missing_status_does_not_unfreeze(self, tmp_path):
        """缺显式 status → 解冻不执行，留冻结待人工（拒绝 parse 兜底）。"""
        runner = FakeRunner(tmp_path, script={"run": dict(self.REPORT)})
        sm = FakeStateMachine({"spec-a": {"status": "blocked", "frozen": True}})
        lane = make_lane(tmp_path, runner=runner, sm=sm)
        lane.submit_trigger(spec="spec-a", signal_type="verify_fail_escalation")
        assert drain(lane)
        assert sm.unfreeze_calls == []
        kinds = [rec["kind"] for rec in load_arbiter_ledger(tmp_path)]
        assert "disposition" in kinds

    def test_unfrozen_spec_untouched(self, tmp_path):
        """未冻结 spec：resolved 报告不解冻（零接触）。"""
        runner = FakeRunner(tmp_path, script={"run": {**self.REPORT,
                                                      "status_after": "ready"}})
        sm = FakeStateMachine({"spec-a": {"status": "ready"}})
        lane = make_lane(tmp_path, runner=runner, sm=sm)
        lane.submit_trigger(spec="spec-a", signal_type="verify_fail_escalation")
        assert drain(lane)
        assert sm.unfreeze_calls == []

    def test_pinned_model_when_no_assignment(self, tmp_path):
        """无 model 分配 → 钉死 glm-5.3-flash（不回落默认网关模型）。"""
        runner = FakeRunner(tmp_path, script={"run": dict(self.REPORT)})
        lane = make_lane(tmp_path, runner=runner)
        lane.submit_trigger(spec="spec-a", signal_type="verify_fail_escalation")
        assert drain(lane)
        assert runner.observed_models == ["glm-5.3-flash"]


# ── 消费预演（2.3，全新进程 import 链 + 咽喉注册自检）────

class TestConsumptionRehearsal:
    def test_fresh_process_import_chain_and_throat_registration(self, tmp_path):
        """全新进程：import 链 + 车道表/门面/咽喉/契约面自检断言全绿。"""
        import subprocess
        import sys

        code = f"""
import json, sys
sys.path.insert(0, {json.dumps(str(Path(__file__).resolve().parents[1]))})
import core.agent_runner.runner  # 门面链
import core.agent_runner.maintenance_runs as mr
import core.pm_engine.arbiter as arb
import core.adjudication_narrative as adj
import core.state_machine as sm
import core.admin_store as admin_store
import core.config as config_mod
from core.agent_runner.run_files import RUN_ID_AGENT_PREFIXES
assert ("arbiter-", "arbiter") in RUN_ID_AGENT_PREFIXES
assert hasattr(mr, "run_arbiter")
assert hasattr(sm, "set_arbiter_freeze_hook") and sm.get_arbiter_freeze_hook() is None
assert "arbiter" in __import__("core.agent_runner.prompt_builder", fromlist=["AGENT_PROMPT_FILES"]).AGENT_PROMPT_FILES
assert hasattr(admin_store.AdminStore, "arbiter_resolve")
assert hasattr(admin_store.AdminStore, "arbiter_upgrade")
assert hasattr(adj, "narrative_yielded_to_arbiter")
cfg = config_mod.ConfigLoader.get_arbiter_config({{}})
assert cfg == {{"enabled": True, "budget_wallclock_s": 1800, "budget_tokens": 1000000, "max_consecutive_failures": 2}}, cfg
req = json.load(open({json.dumps(str(Path(__file__).resolve().parents[1] / "restart_request"))}))
assert {{"reason", "origin", "date"}} <= set(req)
assert mr.ARBITER_REPORT_OUTCOMES == ("resolved", "escalate")
print("REHEARSAL-OK")
"""
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                              text=True, timeout=120)
        assert proc.returncode == 0, proc.stderr
        assert "REHEARSAL-OK" in proc.stdout


# ── 台账五段完整性（4.2 判定面）─────────────────────────

class TestLedgerSegments:
    def test_ledger_entry_complete(self):
        base = {
            "scene_snapshot": "snap",
            "forensic_timeline": [{"at": "t", "event": "e"}],
            "root_cause": "r",
            "action_or_upgrade": "a",
            "evidence_refs": ["x"],
        }
        assert ledger_entry_complete(base)
        for key in base:
            broken = dict(base)
            broken[key] = None
            assert not ledger_entry_complete(broken)
            broken[key] = "" if isinstance(base[key], str) else []
            assert not ledger_entry_complete(broken)

    def test_ledger_written_with_five_segments(self, tmp_path):
        runner = FakeRunner(tmp_path, script={"run": {
            "outcome": "resolved", "summary": "s", "root_cause": "root!",
            "scene_snapshot": "snap!", "forensic_timeline": [],
            "actions_taken": ["a1"], "evidence_refs": ["ref1"],
            "status_after": "ready"}})
        lane = make_lane(tmp_path, runner=runner)
        lane.submit_trigger(spec="spec-a", signal_type="verify_fail_escalation")
        assert drain(lane)
        recs = load_arbiter_ledger(tmp_path)
        assert recs and ledger_entry_complete(recs[-1])
