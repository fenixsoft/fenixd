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
import re
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.pm_engine.arbiter import (
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
                signal_type="verify_env_blocked",
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

    def test_excluded_signal_types(self, tmp_path):
        """黑名单 kill switch：chain.blacklist 内 signal 不进链不进 Arbiter。

        触发面反转（add-escalation-chain-admin-arbiter 3.3）：旧「白名单+排除
        表」被 chain.blacklist 取代（初始为空——升级边默认自动化处置）；名单
        内信号直达人工队列。读取失败按空名单 fail-open（放行方向）。
        """
        (tmp_path / ".fenix").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".fenix" / "config.yaml").write_text(
            "arbiter:\n  enabled: true\n"
            "chain:\n  blacklist: [impl_budget_exhausted, spec_content_missing]\n",
            encoding="utf-8")
        lane = ArbiterLane(tmp_path, None)
        for sig in ("impl_budget_exhausted", "spec_content_missing"):
            assert lane.in_trigger_surface(sig) is False, sig
        # 名单外默认在触发面——含旧排除表词汇（反转后可进链自动化处置）
        assert lane.in_trigger_surface("verify_env_blocked") is True
        assert lane.in_trigger_surface("redispatch_loop_detected") is True

    def test_production_signal_vocabulary_in_surface(self):
        """触发面白名单 MUST 覆盖全部生产冻结/升级信号词汇（2026-11-01 两段修复）。

        词汇分裂实证：verify_fail_escalation=family.py 冻结路径；verify_env_
        blocked=pipeline 争议/环境阻塞路径——任一单点锚定都是部分词汇（第一段
        修错方向、第二段补齐后又漏 spec-review 族=fix-planner 冻结未被接走）。
        唯一可靠口径=freeze_for_human 全调用点机械枚举 ∪ 事件/回扫旁路名，
        见 test_trigger_surface_covers_all_freeze_throat_signal_types 机械守卫。
        """
        lane = ArbiterLane(Path("/tmp"), None)
        for sig in (
            # freeze_for_human 九族（机械枚举在案）
            "verify_fail_escalation",     # family.py 冻结路径
            "verify_env_blocked",         # pipeline 争议/环境阻塞（evo-refine 实证）
            "spec-review-incomplete",     # spec_review 评审不完整（fix-planner 实证）
            "spec-review-rejected",       # spec_review 方案连续否决
            "judge_rerun_cap",            # judge 重跑上限（计数复位配方族）
            "verify_uniform_failure",     # 全场景同因失败
            "verifier_infra_death",       # 验证基础设施死亡
            # 事件/回扫旁路名（非 freeze_for_human 直发）
            "verdict_result_unreadable",  # pipeline 裁决缺失 fail-closed
            "blocked_stuck",              # admin_monitor blocked 超阈值
            "manual-intervention",        # Administrator 处置请求
        ):
            assert lane.in_trigger_surface(sig) is True, sig

    def test_trigger_surface_covers_all_freeze_throat_signal_types(self):
        """机械守卫：freeze_for_human 全调用点 signal_type 必须落在触发面。

        防词汇漂移复发——新增冻结族未进触发面时本测试红。扫描 core/ 全源
        （跳过 def 定义行），signal_type 字面量经触发面判定核对（黑名单制：
        非黑名单即入，缺省空黑名单下全部放行）。
        """
        import glob
        lane = ArbiterLane(Path("/tmp"), None)
        found = set()
        for fp in glob.glob("core/**/*.py", recursive=True):
            src = open(fp, encoding="utf-8").read()
            for m in re.finditer(r"freeze_for_human\(", src):
                if src[max(0, m.start() - 4):m.start()].rstrip().endswith("def"):
                    continue  # 定义行
                seg = src[m.end():m.end() + 500]
                sm = re.search(r'signal_type\s*=\s*["\']?([A-Za-z][\w-]*)', seg)
                if sm:
                    found.add(sm.group(1))
        assert found, "机械枚举扫描零命中——扫描器本身坏了"
        for sig in sorted(found):
            assert lane.in_trigger_surface(sig), (
                f"冻结族 '{sig}' 未进触发面（黑名单制：非黑名单即入，"
                "词汇漂移复发）"
            )

    def test_disabled_lane_returns_disabled(self, tmp_path):
        """enabled=false：submit 返回 disabled，零写入零派发。"""
        lane = make_lane(tmp_path, config={"enabled": False})
        assert lane.submit_trigger(spec="spec-a", signal_type="verify_env_blocked") == "disabled"
        assert lane._queue.qsize() == 0
        assert load_arbiter_ledger(tmp_path) == []


# ── dedup / 复发 ────────────────────────────────────────

class TestDedupAndRecurrence:
    def test_double_throat_single_dispatch_with_alert_bind(self, tmp_path):
        """双咽喉同签名：首个 queued、第二个 deduped 且 alert 补绑。"""
        lane = make_lane(tmp_path)
        out1 = lane.submit_trigger(spec="spec-a", signal_type="verify_env_blocked",
                           alert_id=None)
        assert out1 == "queued"
        out2 = lane.submit_for_alert(
            None, {"spec": "spec-a", "signal_type": "verify_env_blocked"},
            "alert-1",
        )
        assert out2 == "deduped"
        assert drain(lane)
        # alert-1 经补绑进入触发，处置升级路径有挂靠目标（台账/告警以
        # _process_trigger 结果为准，这里只断言补绑生效不抛）

    def test_recurrence_escalates_without_run(self, tmp_path):
        """同签名拍板配额耗尽后复发：不再派发，直接产裁决包升级（D6 配额制）。

        旧「同签名仅一次」单发纪律被配额制取代（add-escalation-chain-
        admin-arbiter 3.3）：拍板 arbiter_rulings 次内复现正常重派（配额内
        自愈），耗尽后第 rulings+1 次复现强制上升。此处 cap=1：首拍即耗尽。
        """
        (tmp_path / ".fenix").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".fenix" / "config.yaml").write_text(
            "arbiter:\n  enabled: true\nchain:\n  arbiter_rulings: 1\n",
            encoding="utf-8")
        report = {"outcome": "resolved", "summary": "s", "root_cause": "r",
                  "scene_snapshot": "snap", "forensic_timeline": [],
                  "actions_taken": ["a"], "evidence_refs": ["e"],
                  "status_after": "ready"}
        runner = FakeRunner(tmp_path, script={"run": report})
        sm = FakeStateMachine()
        lane = make_lane(tmp_path, runner=runner, sm=sm)
        # 第一轮：自主处置成功（拍板计数 1/1 落 chain 状态文件）
        lane.submit_trigger(spec="spec-a", signal_type="verify_env_blocked")
        assert drain(lane)
        first_runs = len(runner.run_agent_calls)
        assert first_runs >= 1
        # 同根因复发（新触发、同签名）：配额耗尽，不再自主处置，直接升级
        out = lane.submit_for_alert(
            None, {"spec": "spec-a", "signal_type": "verify_env_blocked",
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
                lane.submit_trigger(spec=f"spec-{i}", signal_type="verify_env_blocked")
            )
        assert all(o == "queued" for o in outcomes)
        with pytest.raises(RuntimeError, match="队列已满"):
            lane.submit_trigger(spec="spec-overflow", signal_type="verify_env_blocked")

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
        lane.submit_trigger(spec="spec-a", signal_type="verify_env_blocked")
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
        lane.submit_trigger(spec="spec-a", signal_type="verify_env_blocked",
                    alert_id="alert-1")
        assert drain(lane)
        lane.submit_trigger(spec="spec-a", signal_type="verify_env_blocked",
                    alert_id="alert-1")
        assert drain(lane)
        self._escalation_targets(tmp_path, lane)
        # 第三次同签名：复发语义（不派发）——_dispatched 已含
        out = lane.submit_trigger(spec="spec-a", signal_type="verify_env_blocked")
        assert out == "recurrence-escalated"

    def test_single_failure_retries_without_deadman(self, tmp_path):
        """单次失败留重试余量：不升级、台账 kind=failed。"""
        runner = FakeRunner(tmp_path, script={"run": "raise"})
        lane = make_lane(tmp_path, runner=runner)
        lane.submit_trigger(spec="spec-b", signal_type="verify_env_blocked")
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
        lane.submit_trigger(spec="spec-c", signal_type="verify_env_blocked")
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
        lane.submit_trigger(spec="spec-d", signal_type="verify_env_blocked")
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
        lane.submit_trigger(spec="spec-e", signal_type="verify_env_blocked")
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
        lane.submit_trigger(spec="spec-a", signal_type="verify_env_blocked")
        assert drain(lane)
        assert sm.unfreeze_calls == [("spec-a", "testing")]

    def test_missing_status_does_not_unfreeze(self, tmp_path):
        """缺显式 status → 解冻不执行，留冻结待人工（拒绝 parse 兜底）。"""
        runner = FakeRunner(tmp_path, script={"run": dict(self.REPORT)})
        sm = FakeStateMachine({"spec-a": {"status": "blocked", "frozen": True}})
        lane = make_lane(tmp_path, runner=runner, sm=sm)
        lane.submit_trigger(spec="spec-a", signal_type="verify_env_blocked")
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
        lane.submit_trigger(spec="spec-a", signal_type="verify_env_blocked")
        assert drain(lane)
        assert sm.unfreeze_calls == []

    def test_pinned_model_when_no_assignment(self, tmp_path):
        """无 model 分配 → 钉死 glm-5.3-flash（不回落默认网关模型）。"""
        runner = FakeRunner(tmp_path, script={"run": dict(self.REPORT)})
        lane = make_lane(tmp_path, runner=runner)
        lane.submit_trigger(spec="spec-a", signal_type="verify_env_blocked")
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
# restart_request 为运行时瞬时产物（supervisor 消费即删除）——不进常驻断言
# （2026-11-01：曾断言根路径文件存在，消费后永久失败=时间炸弹）
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
        lane.submit_trigger(spec="spec-a", signal_type="verify_env_blocked")
        assert drain(lane)
        recs = load_arbiter_ledger(tmp_path)
        assert recs and ledger_entry_complete(recs[-1])


# ── 禁立项红线与 gaps→todo 路由（add-arbiter-gap-todo-routing）─────────

_GAP_REPORT_BASE = {
    "outcome": "resolved", "summary": "s", "root_cause": "r",
    "scene_snapshot": "snap", "forensic_timeline": [],
    "actions_taken": ["a"], "evidence_refs": ["e"], "status_after": "ready",
}

# 立项通道退役后的立项类台账 kind（MUST NOT 再出现）
_FILING_KINDS = {"spec-proposed", "proposal-dedup", "proposal-throttled"}


def _gap_topic_report(gaps):
    report = dict(_GAP_REPORT_BASE)
    report["gaps"] = gaps
    return report


class TestFilingRetirement:
    """退役断言（tasks 3.1）：立项写点不存在；调查完结零 drafted SPEC。"""

    def test_retired_symbols_absent(self, tmp_path):
        """立项方法/物化/节流常量在模块与 lane 实例上均不存在（防回潮）。"""
        import core.pm_engine.arbiter as arb_mod

        for sym in ("_apply_proposals", "_materialize_proposal",
                    "PROPOSAL_MAX_PER_RUN", "PROPOSAL_WEEKLY_QUOTA"):
            assert not hasattr(arb_mod, sym), f"退役符号仍在模块上: {sym}"
        lane = make_lane(tmp_path)
        for sym in ("_apply_proposals", "_materialize_proposal"):
            assert not hasattr(lane, sym), f"退役方法仍在 lane 上: {sym}"

    def test_resolved_report_never_drafts_spec(self, tmp_path):
        """带 gaps 的 resolved 报告全链完结后：无 add_spec、无 spec/changes
        目录物化、台账无立项类 kind——todo.md 是框架缺口唯一出口。"""
        runner = FakeRunner(tmp_path, script={"run": _gap_topic_report([
            {"topic": "registry-gap-probe", "evidence": "e",
             "impact": "i", "candidates": "c"},
        ])})
        sm = FakeStateMachine({"spec-a": {"status": "blocked", "frozen": True}})
        lane = make_lane(tmp_path, runner=runner, sm=sm)
        lane.submit_trigger(spec="spec-a", signal_type="verify_env_blocked")
        assert drain(lane)
        assert sm.added_specs == [], "调查完结 MUST NOT 立项（无 add_spec）"
        assert sm.unfreeze_calls == [("spec-a", "ready")]  # 白名单解冻不受扰
        changes_dir = tmp_path / "spec" / "changes"
        assert not changes_dir.exists() or not any(changes_dir.iterdir()), \
            "立项目录物化 MUST NOT 发生"
        kinds = {rec["kind"] for rec in load_arbiter_ledger(tmp_path)}
        assert not _FILING_KINDS & kinds
        assert "gap-noted" in kinds            # 缺口经 todo 路由留痕
        assert (tmp_path / ".fenix" / "todo.md").exists()

    def test_gaps_absent_report_zero_filing(self, tmp_path):
        """gaps 缺席的报告：台账无立项类 kind、无 todo 落盘（零动作）。"""
        runner = FakeRunner(tmp_path, script={"run": dict(_GAP_REPORT_BASE)})
        lane = make_lane(tmp_path, runner=runner)
        lane.submit_trigger(spec="spec-a", signal_type="verify_env_blocked")
        assert drain(lane)
        kinds = {rec["kind"] for rec in load_arbiter_ledger(tmp_path)}
        assert not _FILING_KINDS & kinds
        assert "gap-noted" not in kinds
        assert not (tmp_path / ".fenix" / "todo.md").exists()


class TestGapTodoRouting:
    """路由断言（tasks 3.2）：gaps 逐条落 todo.md；同主题去重；台账
    gap-noted 三形态（记入/去重跳过/旧字段容错）。"""

    @staticmethod
    def _trigger():
        return {"spec": "spec-a", "signature": "sig-a", "run_id": "r1",
                "enqueued_at": "", "source": "test",
                "signal_type": "verify_env_blocked"}

    def test_gap_lands_with_contract(self, tmp_path):
        """单条 gap：结构契约条目落「可改进」小节（来源前缀/run_id/四字段）。"""
        lane = make_lane(tmp_path)
        lane._apply_gaps(self._trigger(), _gap_topic_report([
            {"topic": "adjudication-registry-gap",
             "evidence": "注册表缺 X 项",
             "impact": "升级链断链",
             "candidates": "补注册表单源"},
        ]))
        todo = (tmp_path / ".fenix" / "todo.md").read_text(encoding="utf-8")
        assert "### 可改进" in todo                     # 自进化消费面小节
        assert "- **[arbiter:sig-a] adjudication-registry-gap**" in todo
        assert "run_id=r1" in todo                      # 正文带触发 run_id
        for label in ("影响：", "证据：", "调查评估：", "建议："):
            assert label in todo, f"四字段标签缺失: {label}"
        assert "补注册表单源" in todo                    # 候选方向入建议段
        recs = load_arbiter_ledger(tmp_path)
        assert [r["kind"] for r in recs] == ["gap-noted"]
        assert "adjudication-registry-gap" in recs[-1]["action_or_upgrade"]

    def test_same_topic_dedup_skips_and_ledgers(self, tmp_path):
        """同主题去重命中跳过：todo 单条目；台账记入+跳过两条 gap-noted。"""
        lane = make_lane(tmp_path)
        lane._apply_gaps(self._trigger(), _gap_topic_report([
            {"topic": "registry-gap", "evidence": "e1", "impact": "i1",
             "candidates": "c1"}]))
        lane._apply_gaps(self._trigger(), _gap_topic_report([
            {"topic": "registry-gap followup", "evidence": "e2",
             "impact": "i2", "candidates": "c2"}]))
        todo = (tmp_path / ".fenix" / "todo.md").read_text(encoding="utf-8")
        assert todo.count("- **[arbiter:sig-a]") == 1   # 第二条被去重
        recs = load_arbiter_ledger(tmp_path)
        assert [r["kind"] for r in recs] == ["gap-noted", "gap-noted"]
        assert "已存在" in recs[-1]["action_or_upgrade"]  # 跳过条附指引

    def test_legacy_proposals_field_tolerated(self, tmp_path):
        """切换窗旧 proposals 字段：WARNING 台账 gap-noted 后丢弃，不落 todo。"""
        lane = make_lane(tmp_path)
        legacy = dict(_GAP_REPORT_BASE)
        legacy["proposals"] = [{"topic": "old-prompt-topic", "rationale": "r"}]
        lane._apply_gaps(self._trigger(), legacy)       # MUST NOT 抛异常
        assert not (tmp_path / ".fenix" / "todo.md").exists()
        recs = load_arbiter_ledger(tmp_path)
        assert [r["kind"] for r in recs] == ["gap-noted"]
        assert "proposals" in recs[-1]["action_or_upgrade"]
        warnings = [rec for rec in lane.logger.records if rec[0] == "warning"]
        assert any("proposals" in rec[2] for rec in warnings)

    def test_empty_or_missing_gaps_zero_action(self, tmp_path):
        """gaps 缺席/空数组/非列表：零动作零台账。"""
        lane = make_lane(tmp_path)
        for gaps in (None, [], "not-a-list"):
            report = dict(_GAP_REPORT_BASE)
            if gaps is not None:
                report["gaps"] = gaps
            lane._apply_gaps(self._trigger(), report)
        assert not (tmp_path / ".fenix" / "todo.md").exists()
        assert load_arbiter_ledger(tmp_path) == []

    def test_lock_mutex_under_concurrency(self, tmp_path):
        """锁互斥：并发多线程记入不同 topic，条目全落且无撕裂。

        topic 取彼此零共享 token 的单词——D3 关键词包含去重按设计生效，
        共享 token 的并发入参会被判同主题跳过（那是去重断言的职责，不是
        锁断言的职责）。
        """
        import threading

        lane = make_lane(tmp_path)
        topics = ["zeta", "kappa", "sigma", "delta", "omega", "lambda",
                  "theta", "rho"]
        threads = [
            threading.Thread(
                target=lane._apply_gaps,
                args=(self._trigger(),
                      _gap_topic_report([{"topic": t, "evidence": "e",
                                          "impact": "i", "candidates": "c"}])))
            for t in topics
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        todo = (tmp_path / ".fenix" / "todo.md").read_text(encoding="utf-8")
        for t in topics:
            assert f"[arbiter:sig-a] {t}" in todo, f"并发记入丢条: {t}"
        recs = load_arbiter_ledger(tmp_path)
        assert len([r for r in recs if r["kind"] == "gap-noted"]) == 8


class TestGapPromptConsumerConsistency:
    """tasks 3.3：prompt 报告 schema（gaps）与消费端解析一致性；白名单
    处置动作回归不受扰。"""

    PROMPT_PATH = Path(__file__).resolve().parents[1] / "agents" / "arbiter.md"

    def test_prompt_gaps_schema_parseable_by_consumer(self, tmp_path):
        """prompt 声明的 gaps 四粒度键构造样例 → 消费端可解析落 todo。"""
        tpl = self.PROMPT_PATH.read_text(encoding="utf-8")
        assert '"gaps"' in tpl                          # schema 字段在位
        for key in ("topic", "evidence", "impact", "candidates"):
            assert key in tpl, f"prompt gaps 粒度键缺失: {key}"
        lane = make_lane(tmp_path)
        lane._apply_gaps(
            {"spec": "spec-a", "signature": "sig-abc12345", "run_id": "r9",
             "enqueued_at": "", "source": "test",
             "signal_type": "verify_env_blocked"},
            _gap_topic_report([{
                "topic": "prompt-schema-roundtrip",
                "evidence": "arbiter.md 报告契约段",
                "impact": "消费端解析面",
                "candidates": "契约对齐测试",
            }]))
        todo = (tmp_path / ".fenix" / "todo.md").read_text(encoding="utf-8")
        assert "- **[arbiter:sig-abc1] prompt-schema-roundtrip**" in todo
        assert "arbiter.md 报告契约段" in todo

    def test_whitelist_unfreeze_regression_with_gaps(self, tmp_path):
        """解冻白名单动作与 gaps 路由同报告不互扰（行为与落地前一致）。"""
        runner = FakeRunner(tmp_path, script={"run": _gap_topic_report([
            {"topic": "coexists-with-unfreeze", "evidence": "e",
             "impact": "i", "candidates": "c"}])})
        sm = FakeStateMachine({"spec-a": {"status": "blocked", "frozen": True}})
        lane = make_lane(tmp_path, runner=runner, sm=sm)
        lane.submit_trigger(spec="spec-a", signal_type="verify_env_blocked")
        assert drain(lane)
        assert sm.unfreeze_calls == [("spec-a", "ready")]   # 解冻照常
        todo = (tmp_path / ".fenix" / "todo.md").read_text(encoding="utf-8")
        assert "coexists-with-unfreeze" in todo             # 路由照常
        kinds = {r["kind"] for r in load_arbiter_ledger(tmp_path)}
        assert {"disposition", "gap-noted"} <= kinds
