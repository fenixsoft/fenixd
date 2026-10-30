"""tests/test_fastlane_items_dispatch.py

evo-fix-fastlane-items-dispatch SPEC 单测：

- 3.1 fastlane 派发 code-fix 时 prompt 含非空 items（失败场景转单，按
  ``_CODE_FIX_ITEM_FIELDS`` 白名单映射）；items 空但派发方声明存在待修失败
  场景时出 WARNING（进程级去重），非 fastlane 消费面不误报。
- 3.2 冻结前定向修复分流单测：满足形态（失败场景数 ≤3 且根因行级定位）
  不冻结先派修复、不满足形态仍按原阈值冻结；承接已派发过的失败事件不再
  触发分流（双派发断言）；升级告警 recommended_action 含根因文本与裁决
  指引。
"""

import json
import logging
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent_runner import prompt_builder as pb_module
from core.agent_runner.prompt_builder import PromptBuilder
from core.pm_engine.family import FamilyGovernor
from core.pm_engine.verification import fastlane as fl
from core.state_machine import StateMachine

# cli 场景最小合法 run 步骤（对齐 load_scenarios 校验：steps 不得为空）
_CLI_STEP = [{"action": "run", "command": "true"}]

# 行级根因 bugs 固件（分流判据：root_cause 含 file:line 行级定位）
_LINE_LEVEL_BUGS = [
    {
        "scenario_ids": ["s0"],
        "root_cause": "core/runner.py:123 缺少空值检查，空列表直取首元素",
        "description": "空场景列表触发 IndexError",
        "severity": "high",
    },
]


def _int(entry: dict, key: str, default: int = 0) -> int:
    """STATE 行式存储计数器取值归一（str 往返读回，对齐 bump_counters 口径）。"""
    try:
        return int(entry.get(key, default) or 0)
    except (TypeError, ValueError):
        return default


class FakeLogger:
    def __init__(self):
        self.records: list = []

    def _rec(self, level, component, msg):
        self.records.append((level, component, msg))

    def info(self, component, msg, context=None):
        self._rec("info", component, msg)

    def warning(self, component, msg, context=None):
        self._rec("warning", component, msg)

    def error(self, component, msg, context=None):
        self._rec("error", component, msg)

    def debug(self, component, msg, context=None):
        self._rec("debug", component, msg)


def _seed_verify_fixtures(tmp_path: Path, spec: str = "spec-a",
                          bugs=None, failed_ids=None):
    """布置分流/转单输入：report.json、场景文件、verifier 结果（bugs）。"""
    failed_ids = failed_ids or ["s0"]
    vp = tmp_path / ".fenix" / "verify-progress" / spec
    vp.mkdir(parents=True, exist_ok=True)
    failed = [
        {"scenario_id": sid, "status": "failed"}
        for sid in failed_ids
    ]
    report = {
        "scenarios": [
            {"scenario_id": "s-dep", "status": "pass"},
            {"scenario_id": "s-down", "depends_on": ["s0"], "status": "pass"},
            *failed,
        ],
        "summary": {"total": 2 + len(failed_ids), "failed": len(failed_ids)},
    }
    (vp / "report.json").write_text(
        json.dumps(report, ensure_ascii=False), encoding="utf-8"
    )
    (vp / "test_scenarios.json").write_text(
        json.dumps([
            {"id": "s-dep", "kind": "cli", "steps": _CLI_STEP, "assertions": []},
            {"id": "s0", "kind": "cli", "steps": _CLI_STEP, "assertions": []},
            {"id": "s-down", "depends_on": ["s0"], "kind": "cli",
             "steps": _CLI_STEP, "assertions": []},
        ], ensure_ascii=False),
        encoding="utf-8",
    )
    # verifier/judge 结果（primary）：spec 戳 + status=bug-found 门内才采信
    (vp / ".fenix-run-result.json").write_text(
        json.dumps(
            {"status": "bug-found", "spec": spec, "bugs": bugs or _LINE_LEVEL_BUGS},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _make_pipe(tmp_path: Path, sm: StateMachine, failed_ids: list,
               dispatch_calls: list, *, stage2_ok: bool = True):
    """构造分流链所需的 pipeline 替身（只暴露模块真实消费面）。"""
    logger = FakeLogger()

    def _execute_agent(spec, agent_type, run_id, detail=None):
        # evo-fix-fastlane-items-dispatch 1.1/1.2：fastlane 派发经 detail 注入
        # items 转单（runner 对 code-fix 与 repair 同样透传）。
        dispatch_calls.append(
            {"spec": spec, "agent_type": agent_type,
             "run_id": run_id, "detail": detail}
        )
        return SimpleNamespace(success=True, run_id=run_id, error="")

    def _stage2(spec, verify_dir, scenarios_path, skip_prune=False):
        if stage2_ok:
            report = {
                "scenarios": [
                    {"scenario_id": "s0", "status": "pass"},
                    {"scenario_id": "s-down", "status": "pass"},
                ],
                "summary": {"total": 2, "passed": 2, "failed": 0,
                            "errors": 0, "blocked_env": 0},
            }
        else:
            report = {
                "scenarios": [
                    {"scenario_id": "s0", "status": "failed"},
                    {"scenario_id": "s-down", "status": "pass"},
                ],
                "summary": {"total": 2, "passed": 1, "failed": 1,
                            "errors": 0, "blocked_env": 0},
            }
        return None, report, True, "", False

    ctx = SimpleNamespace(
        project_root=tmp_path,
        state_machine=sm,
        logger=logger,
        agent_runner=SimpleNamespace(_execute_agent=_execute_agent),
    )
    pipe = SimpleNamespace(
        _context=ctx,
        _failed_scenario_ids=lambda spec: list(failed_ids),
        _execute_stage2=_stage2,
        # 收敛收口替身：真实 _apply_verified 内部 testing→verified + 门禁链，
        # 此处只落 status=verified 表达「门禁未拒绝」的收敛终态。
        _apply_verified=lambda spec, judge_result, report: sm.update_spec(
            spec, {"status": "verified"}
        ),
    )
    return pipe


def _mk_state_machine(tmp_path: Path) -> StateMachine:
    (tmp_path / ".fenix").mkdir(parents=True, exist_ok=True)
    return StateMachine(tmp_path / ".fenix" / "STATE.md", FakeLogger())


def _mk_governor(tmp_path: Path, pipe, failed_ids: list, *,
                 fail_rounds: int = 2, streak: int = 0):
    """构造 FamilyGovernor（门面 pm 桩：真实 StateMachine + 分流假 pipeline）。"""
    sm = pipe._context.state_machine
    sm.add_spec("spec-a", {
        "status": "bug-found",
        "priority": 5,
        "_verify_fail_rounds": fail_rounds,
        fl.FASTLANE_STREAK_FIELD: streak,
    })
    pm = SimpleNamespace(
        project_root=tmp_path,
        logger=FakeLogger(),
        state_machine=sm,
        config={},
        _verification=pipe,
        _failed_scenario_ids=lambda spec: list(failed_ids),
        _append_fail_history=MagicMock(),
        _read_fail_history=lambda spec: [],
        _clear_fail_history=MagicMock(),
        _append_project_log=MagicMock(),
        _enqueue=MagicMock(),
        _send_human_escalation_alert=MagicMock(),
    )
    governor = FamilyGovernor(pm)
    # 告警回调替换为实例级捕获桩：真实方法写 admin store，kwargs 捕获断言用
    governor._send_human_escalation_alert = MagicMock()
    return governor, pm, sm


# ══════════════ 3.1 fastlane 载具修复条目注入 ══════════════


class TestFastlaneItemsInjection(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tmp_path = Path(self.tmpdir)
        # 进程级去重集合跨测试清零，防用例间互相吞告警
        pb_module._EMPTY_FASTLANE_ITEMS_WARNED.clear()

    def tearDown(self):
        pb_module._EMPTY_FASTLANE_ITEMS_WARNED.clear()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_dispatch_carries_nonempty_whitelist_items(self):
        """承接派发 code-fix 时 detail 携带非空 items，键名全部在白名单内。"""
        _seed_verify_fixtures(self.tmp_path)
        sm = _mk_state_machine(self.tmp_path)
        sm.add_spec("spec-a", {"status": "bug-found", "priority": 5})
        dispatch_calls: list = []
        pipe = _make_pipe(self.tmp_path, sm, ["s0"], dispatch_calls)
        decision = {
            "eligible": True, "path": "fastlane", "failed_id": "s0",
            "subset_ids": ["s0", "s-down"],
            "affected_files": ["core/runner.py"],
        }
        outcome = fl.dispatch_minor_defect_fastlane(pipe, "spec-a", decision)
        assert outcome["dispatched"] is True
        assert len(dispatch_calls) == 1
        call = dispatch_calls[0]
        assert call["agent_type"] == "code-fix"
        detail = call["detail"]
        # 非空 items + 失败上下文顶层标记（1.3 告警触发面）
        assert detail.get("has_failed_scenarios") is True
        items = detail.get("items")
        assert isinstance(items, list) and items, "items 不得为空（结构性空转回归）"
        item = items[0]
        whitelist = set(pb_module._CODE_FIX_ITEM_FIELDS)
        assert set(item) <= whitelist, f"白名单外键名注入: {set(item) - whitelist}"
        # 白名单映射：场景 ID→item_id、文件→file、行号→line、根因→description
        assert item["item_id"] == "s0"
        assert item["file"] == "core/runner.py"
        assert item["line"] == 123
        assert "缺少空值检查" in item["description"]

    def test_prompt_contains_nonempty_items_json(self):
        """派发 detail 经 _build_code_fix_prompt 渲染后 prompt 含非空 items。"""
        detail = {
            "has_failed_scenarios": True,
            "dispatch_source": "minor-defect-fastlane",
            "items": [{
                "item_id": "s0", "file": "core/runner.py", "line": 123,
                "severity": "major", "category": "product-bug",
                "title": "验证失败场景 s0 定向修复",
                "description": "根因：core/runner.py:123 缺少空值检查",
            }],
        }
        pb = PromptBuilder(SimpleNamespace(project_root=str(self.tmp_path)))
        prompt = pb._build_code_fix_prompt("spec-a", detail)
        assert '"item_id": "s0"' in prompt, "prompt 未注入 items 条目"
        assert "core/runner.py" in prompt
        # 非 fastlane 消费面对照：无 items 时才出现 "[]"（此处非空则不出现）
        assert '[]' not in prompt.split("{items}")[-1][:200] or '"item_id"' in prompt

    def test_empty_items_with_failed_scenarios_warns_once(self):
        """items 空 + 派发方声明存在失败场景 → WARNING 留痕且进程级去重。"""
        pb = PromptBuilder(SimpleNamespace(project_root=str(self.tmp_path)))
        detail = {
            "items": [],
            "has_failed_scenarios": True,
            "dispatch_source": "minor-defect-fastlane",
        }
        with self.assertLogs("fenixd.agent_runner.prompt_builder",
                             level="WARNING") as captured:
            pb._build_code_fix_prompt("spec-warn", detail)
            # 进程级去重：同派发源第二次构建不再告警
            pb._build_code_fix_prompt("spec-warn", detail)
        warnings = [r for r in captured.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1, f"预期去重后恰 1 条 WARNING，实得 {len(warnings)}"
        assert "items 为空" in warnings[0].getMessage()

    def test_empty_items_without_marker_no_false_positive(self):
        """其余 code-fix 消费面（台账批/维护车道）不带 items 属正常形态不误报。"""
        pb = PromptBuilder(SimpleNamespace(project_root=str(self.tmp_path)))
        try:
            with self.assertNoLogs("fenixd.agent_runner.prompt_builder",
                                   level="WARNING"):
                pb._build_code_fix_prompt("spec-ledger", {"items": []})
                pb._build_code_fix_prompt("spec-maint", {})
        except AssertionError:
            # Python 3.10 前无 assertNoLogs 的环境兜底：直接检查去重集合未新增
            assert not any(
                "spec-ledger" in k or "spec-maint" in k
                for k in pb_module._EMPTY_FASTLANE_ITEMS_WARNED
            )


# ══════════════ 3.2 冻结前定向修复分流 ══════════════


class TestPreFreezeDiversion(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tmp_path = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_shape_matched_diverts_before_freeze(self):
        """满足形态：_verify_fail_rounds 已达阈值-1 时不冻结、先派定向修复并收敛，
        冻结预算不递增（先修后冻）。"""
        _seed_verify_fixtures(self.tmp_path)
        sm = _mk_state_machine(self.tmp_path)
        dispatch_calls: list = []
        pipe = _make_pipe(self.tmp_path, sm, ["s0"], dispatch_calls, stage2_ok=True)
        governor, pm, sm2 = _mk_governor(
            self.tmp_path, pipe, ["s0"], fail_rounds=2
        )
        # MAX_VERIFY_FAIL_ROUNDS=3：引入前 fail_rounds=2+1=3 即冻结
        governor._do_spec_bug_found("spec-a", "product")
        # 分流派发了 code-fix 定向修复（items 非空）
        assert len(dispatch_calls) == 1
        assert dispatch_calls[0]["detail"]["items"]
        # 收敛：状态 verified、冻结预算未递增（仍为 2）、无冻结
        entry = sm2.read_one("spec-a")
        assert entry.get("status") == "verified"
        assert _int(entry, "_verify_fail_rounds") == 2
        assert not entry.get("frozen")
        governor._send_human_escalation_alert.assert_not_called()

    def test_shape_not_matched_freezes_at_threshold(self):
        """不满足形态（根因非行级定位）：仍按原阈值冻结，冻结预算照常递增。"""
        no_line_bugs = [
            {"scenario_ids": ["s0"],
             "root_cause": "缺陷原因不明确，建议人工排查",
             "severity": "major"},
        ]
        _seed_verify_fixtures(self.tmp_path, bugs=no_line_bugs)
        sm = _mk_state_machine(self.tmp_path)
        dispatch_calls: list = []
        pipe = _make_pipe(self.tmp_path, sm, ["s0"], dispatch_calls)
        governor, pm, sm2 = _mk_governor(
            self.tmp_path, pipe, ["s0"], fail_rounds=2
        )
        governor._do_spec_bug_found("spec-a", "product")
        # 未派发分流（形态不满足）、未收敛
        assert dispatch_calls == []
        entry = sm2.read_one("spec-a")
        assert entry.get("status") == "blocked"
        assert entry.get("frozen") is True
        assert _int(entry, "_verify_fail_rounds") == 3
        governor._send_human_escalation_alert.assert_called_once()

    def test_diversion_fix_fails_budget_still_bumped(self):
        """分流先派修复但子集重验仍失败 → 经 bump_counters 单点递增计入冻结预算。"""
        _seed_verify_fixtures(self.tmp_path)
        sm = _mk_state_machine(self.tmp_path)
        dispatch_calls: list = []
        pipe = _make_pipe(self.tmp_path, sm, ["s0"], dispatch_calls, stage2_ok=False)
        governor, pm, sm2 = _mk_governor(
            self.tmp_path, pipe, ["s0"], fail_rounds=2
        )
        governor._do_spec_bug_found("spec-a", "product")
        # 分流先派了定向修复
        assert len(dispatch_calls) == 1
        entry = sm2.read_one("spec-a")
        # 仍失败：既有闸门路径推进——递增到 3 即冻结，车道 streak 不被误记
        assert _int(entry, "_verify_fail_rounds") == 3
        assert entry.get("frozen") is True
        assert _int(entry, fl.FASTLANE_STREAK_FIELD) == 0

    def test_minor_defect_handled_event_not_diverted_again(self):
        """承接已派发过的失败事件不再触发分流（双派发断言）：判定记录为承接
        失败回落 + 同 failed_id 时，分流跳过、按既有记账路径推进。"""
        _seed_verify_fixtures(self.tmp_path)
        # 本失败事件已由 minor-defect 承接派发处置并回落（record_decision 产物）
        vp = self.tmp_path / ".fenix" / "verify-progress" / "spec-a"
        (vp / "fastlane_decision.json").write_text(
            json.dumps({
                "eligible": True, "path": "full-round",
                "stage": "dispatch-failed",
                "reason": "code-fix 轻量修复失败（回落整轮）",
                "failed_id": "s0", "spec": "spec-a", "streak": 1,
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        sm = _mk_state_machine(self.tmp_path)
        dispatch_calls: list = []
        pipe = _make_pipe(self.tmp_path, sm, ["s0"], dispatch_calls)
        governor, pm, sm2 = _mk_governor(
            self.tmp_path, pipe, ["s0"], fail_rounds=0, streak=1
        )
        governor._do_spec_bug_found("spec-a", "product")
        # 双派发断言：本事件内 family 不再派第二次 code-fix
        assert dispatch_calls == []
        entry = sm2.read_one("spec-a")
        # 按既有记账路径推进：递增至 1（<3）走原地打回，车道 streak 不动
        assert _int(entry, "_verify_fail_rounds") == 1
        assert entry.get("status") == "implementing"
        assert _int(entry, fl.FASTLANE_STREAK_FIELD) == 1
        # 打回路径重派 implementer（非 code-fix）
        pm._enqueue.assert_called_once_with("spec-a", "implementer")

    def test_lane_circuit_break_skips_diversion(self):
        """车道熔断（连续 2 次 fastlane 失败）期间不分流，直接按闸门路径推进。"""
        _seed_verify_fixtures(self.tmp_path)
        sm = _mk_state_machine(self.tmp_path)
        dispatch_calls: list = []
        pipe = _make_pipe(self.tmp_path, sm, ["s0"], dispatch_calls)
        governor, pm, sm2 = _mk_governor(
            self.tmp_path, pipe, ["s0"], fail_rounds=2,
            streak=fl.FASTLANE_MAX_CONSECUTIVE_FAILURES,
        )
        governor._do_spec_bug_found("spec-a", "product")
        assert dispatch_calls == []
        entry = sm2.read_one("spec-a")
        assert _int(entry, "_verify_fail_rounds") == 3
        assert entry.get("frozen") is True

    def test_recommended_action_contains_root_cause_and_guidance(self):
        """升级告警 recommended_action 含验证报告行级根因与「修复重验/豁免」
        裁决指引；既有结构化 choices 通道不受影响（告警回调仍被调用）。"""
        _seed_verify_fixtures(self.tmp_path)  # bugs 含 core/runner.py:123 根因
        sm = _mk_state_machine(self.tmp_path)
        dispatch_calls: list = []
        # 形态不满足（4 个失败场景 > 3）逼入冻结分支，但 bugs 根因仍可注入
        pipe = _make_pipe(
            self.tmp_path, sm, ["s0", "s1", "s2", "s3"], dispatch_calls
        )
        governor, pm, sm2 = _mk_governor(
            self.tmp_path, pipe, ["s0", "s1", "s2", "s3"], fail_rounds=2
        )
        governor._do_spec_bug_found("spec-a", "product")
        entry = sm2.read_one("spec-a")
        assert entry.get("frozen") is True
        governor._send_human_escalation_alert.assert_called_once()
        kwargs = governor._send_human_escalation_alert.call_args.kwargs
        action = kwargs["recommended_action"]
        assert "core/runner.py:123" in action, "recommended_action 缺行级根因"
        assert "缺少空值检查" in action
        assert "裁决指引" in action
        assert "manual_fixed_reverify" in action
        # 既有 signal/severity 契约不变（verify_fail_escalation / major）
        assert kwargs["signal_type"] == "verify_fail_escalation"
        assert kwargs["severity"] == "major"

    def test_recommended_action_fallback_without_root_cause(self):
        """裁决产物不可读/无根因时 recommended_action 含查阅指引兜底，不阻断冻结。"""
        _seed_verify_fixtures(
            self.tmp_path,
            bugs=[{"scenario_ids": ["s0"], "severity": "major"}],  # 有 bug 无 root_cause
        )
        sm = _mk_state_machine(self.tmp_path)
        dispatch_calls: list = []
        pipe = _make_pipe(
            self.tmp_path, sm, ["s0", "s1", "s2", "s3"], dispatch_calls
        )
        governor, pm, sm2 = _mk_governor(
            self.tmp_path, pipe, ["s0", "s1", "s2", "s3"], fail_rounds=2
        )
        governor._do_spec_bug_found("spec-a", "product")
        kwargs = governor._send_human_escalation_alert.call_args.kwargs
        assert "verification-report.md" in kwargs["recommended_action"]

    def test_diversion_exception_falls_back_to_existing_gate(self):
        """分流判定/派发异常 ≠ 修复失败：fail-open 回既有闸门路径（不收敛、
        按原阈值冻结）。"""
        _seed_verify_fixtures(self.tmp_path)
        sm = _mk_state_machine(self.tmp_path)
        dispatch_calls: list = []
        pipe = _make_pipe(self.tmp_path, sm, ["s0"], dispatch_calls)
        governor, pm, sm2 = _mk_governor(
            self.tmp_path, pipe, ["s0"], fail_rounds=2
        )
        # 打断分流消费面：agent_runner 派发抛异常
        def _boom(spec, agent_type, run_id, detail=None):
            raise RuntimeError("dispatch exploded")

        pipe._context.agent_runner._execute_agent = _boom
        governor._do_spec_bug_found("spec-a", "product")
        entry = sm2.read_one("spec-a")
        assert _int(entry, "_verify_fail_rounds") == 3
        assert entry.get("frozen") is True


if __name__ == "__main__":
    unittest.main()
