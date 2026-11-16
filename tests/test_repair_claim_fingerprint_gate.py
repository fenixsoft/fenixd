"""修复申报受理指纹门回归测试（judge-repair-claim-gate / design D1-D3）。

覆盖 tasks 4.1 全部分支：

1. 派单侧随单附指纹：bug-found 写点持久化派单指纹 envelope（无基线置
   null 不阻断派发）；code-fix detail 注入（repair_fingerprint/brief）。
2. fix SPEC 完成消费点受理门（engine._on_spec_done fix-* 分支前置）：
   - 指纹未变化拒收：error 含「失败指纹未变化」+双方指纹值、rejected
     记账、父 SPEC 保持 bug-found、不转 implemented、不入队 verifier
     （拒收不穿透守卫）；
   - 指纹变化放行（探针标注主源）；
   - 无基线放行（legacy 链零变化）；
   - 缺探针标注拒收（D1 优先级①②皆缺）；
   - 盘面 post-fix 新鲜轮指纹源分支（report mtime > 派单时刻）。
3. fastlane 子集重验消费点：新鲜轮指纹未变化拒收、变化放行、无新鲜轮
   （env abort）跳过、无基线跳过（路由零变化，仅记账与留痕增量）。
4. 预算口径不变：拒收仅递增观测计数（_judge_repair_claim_rounds /
   _judge_repair_rejected_rounds），不动修复预算耗尽持久字段；既有
   test-defect 通道 _record_repair_claim 调用点不传指纹、零指纹留痕。

测试全部使用 tmp_path 隔离，不触碰现存 verify-progress 数据。
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.pm_engine.verification.repair_claim_gate import (
    REPAIR_DISPATCH_FINGERPRINT_FIELD,
    attach_dispatch_fingerprint,
    collect_failed_fingerprints,
    dispatch_fingerprint_detail,
    envelope_fps,
    evaluate_fingerprint_gate,
    load_dispatch_fingerprint,
    probe_claim_from_result,
)
from core.state_machine import StateMachine
from core.verdict_check import scenario_fingerprint


def _failed_scenario(sid: str, expected: str = "期望文本A") -> dict:
    """非 PASS 场景条目（引擎侧原始执行产物形态，scenario_fingerprint 取数面）。"""
    return {
        "scenario_id": sid,
        "status": "failed",
        "assertion_results": [
            {
                "type": "element_visible",
                "selector": f"#{sid}-result",
                "expected": expected,
                "actual": "实际文本B",
                "pass": False,
            }
        ],
        "step_results": [],
    }


def _write_report(verify_dir: Path, scenarios: list) -> Path:
    verify_dir.mkdir(parents=True, exist_ok=True)
    report_path = verify_dir / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "spec": "demo-spec",
                "summary": {"total": len(scenarios), "passed": 0,
                            "failed": len(scenarios), "warnings": 0},
                "scenarios": scenarios,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return report_path


def _attach_envelope(sm: StateMachine, spec: str, fps: dict) -> None:
    sm.update_spec(
        spec,
        {
            REPAIR_DISPATCH_FINGERPRINT_FIELD: json.dumps(
                {"fps": fps, "at": 1700000000, "run": "judge-r1"},
                ensure_ascii=False, separators=(",", ":"),
            )
        },
    )


class _GateBase(unittest.TestCase):
    """公共夹具：临时项目根 + 真实 PMEngine（派发已 mock）。"""

    PARENT = "demo-spec"
    FIX = "fix-demo-spec"

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()
        from helpers import disable_escalation_chain

        disable_escalation_chain(self.project_root)
        self.sm = StateMachine(
            self.project_root / ".fenix" / "STATE.md", self.logger
        )
        from core.pm_engine import PMEngine

        self.engine = PMEngine(
            self.sm, MagicMock(), {}, self.project_root, self.logger
        )
        # worktree_manager=None：无活跃实现 worktree，结果文件兜底走项目根
        # 真实语义（MagicMock 路径会让 _read_implementer_result 取数失真）
        self.engine.agent_runner.worktree_manager = None
        self.engine._enqueue = MagicMock()
        self.verify_dir = (
            self.project_root / ".fenix" / "verify-progress" / self.PARENT
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_bug_found_parent(self, name: str = PARENT) -> None:
        self.sm.add_spec(name, {"priority": 5})
        for hop in ("ready", "implementing", "implemented", "testing",
                    "bug-found"):
            self.sm.transition(name, hop)

    def _make_fix_done(self, name: str = FIX) -> None:
        self.sm.add_spec(name, {"priority": 6})
        self.sm.update_spec(name, {"status": "done"})

    def _write_probe_snapshot(self, probe: dict, name: str = FIX) -> None:
        snap_dir = (
            self.project_root / ".fenix" / "verify-progress" / name
        )
        snap_dir.mkdir(parents=True, exist_ok=True)
        (snap_dir / "impl-result.json").write_text(
            json.dumps(
                {
                    "status": "success",
                    "spec": name,
                    "verification": {"repair_probe": probe},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def _entry(self, name: str = PARENT):
        return self.sm.read_one(name) or {}


class TestEngineGateFingerprintUnchangedRejected(_GateBase):
    """fix SPEC 完成消费点：指纹未变化 → 拒收（记账 + 留痕 + 不重入）。"""

    def setUp(self):
        super().setUp()
        self._make_bug_found_parent()
        self._make_fix_done()
        sc = _failed_scenario("scn-a")
        _attach_envelope(self.sm, self.PARENT, {"scn-a": scenario_fingerprint(sc)})
        self._write_probe_snapshot(
            {
                "scenario_id": "scn-a",
                "fingerprint": scenario_fingerprint(sc),
                "matches_dispatch": True,
            }
        )

    def test_rejected_with_accounting_and_trace(self):
        rv = self.engine._repair_claim_fingerprint_gate(self.PARENT, self.FIX)
        self.assertTrue(rv, "指纹未变化 MUST 拒收")
        entry = self._entry()
        # 父 SPEC 保持 bug-found（不转 implemented，不重入执行）
        self.assertEqual(entry.get("status"), "bug-found")
        # error 留痕：含「失败指纹未变化」+ 双方指纹值
        error = str(entry.get("error") or "")
        self.assertIn("失败指纹未变化", error)
        self.assertIn("scn-a", error)
        self.assertIn("受理指纹门拒收", error)
        # rejected 记账：申报 +1、拒收 +1、双方指纹留痕
        self.assertEqual(int(entry.get("_judge_repair_claim_rounds") or 0), 1)
        self.assertEqual(
            int(entry.get("_judge_repair_rejected_rounds") or 0), 1
        )
        fp_brief = f"scn-a={scenario_fingerprint(_failed_scenario('scn-a'))[:12]}"
        self.assertEqual(entry.get("_judge_repair_last_dispatch_fp"), fp_brief)
        self.assertEqual(entry.get("_judge_repair_last_fresh_fp"), fp_brief)
        # WARNING 留痕（重派上下文回传载体之一）
        warnings = [
            str(c.args[-1] if c.args else "")
            for c in self.logger.warning.call_args_list
        ]
        self.assertTrue(any("受理指纹门拒收" in w for w in warnings))

    def test_rejection_blocks_parent_reverify_in_spec_done(self):
        """拒收不穿透守卫：_on_spec_done 不转 implemented、不入队 verifier。"""
        self.engine._on_spec_done(self.FIX)
        self.assertEqual(self._entry().get("status"), "bug-found")
        self.engine._enqueue.assert_not_called()


class TestEngineGateFingerprintChangedAccepted(_GateBase):
    """探针指纹已变化 → 照常受理放行（记账 accepted，无拒收痕迹）。"""

    def setUp(self):
        super().setUp()
        self._make_bug_found_parent()
        self._make_fix_done()
        _attach_envelope(self.sm, self.PARENT, {"scn-a": "olddispatchfp001"})
        self._write_probe_snapshot(
            {
                "scenario_id": "scn-a",
                "fingerprint": "newfingerprint02",
                "matches_dispatch": False,
            }
        )

    def test_accepted_without_rejection(self):
        rv = self.engine._repair_claim_fingerprint_gate(self.PARENT, self.FIX)
        self.assertFalse(rv, "指纹已变化 MUST 放行")
        entry = self._entry()
        self.assertEqual(
            int(entry.get("_judge_repair_claim_rounds") or 0), 1
        )
        self.assertEqual(
            int(entry.get("_judge_repair_rejected_rounds") or 0), 0,
            "放行轮不得递增拒收计数",
        )
        self.assertNotIn("失败指纹未变化", str(entry.get("error") or ""))
        # 放行后既有流程继续（_on_spec_done 转 implemented 并入队 verifier）
        self.engine._on_spec_done(self.FIX)
        self.assertEqual(self._entry().get("status"), "implemented")
        self.engine._enqueue.assert_called_once_with(self.PARENT, "verifier")


class TestEngineGateNoBaselineAccepted(_GateBase):
    """无派单基线（首轮修复/legacy 链）→ 放行且零记账（行为零变化锚点）。"""

    def setUp(self):
        super().setUp()
        self._make_bug_found_parent()
        self._make_fix_done()
        self._write_probe_snapshot(
            {"scenario_id": "scn-a", "fingerprint": "whateverfp001",
             "matches_dispatch": False}
        )

    def test_no_envelope_gate_skips(self):
        rv = self.engine._repair_claim_fingerprint_gate(self.PARENT, self.FIX)
        self.assertFalse(rv)
        entry = self._entry()
        self.assertEqual(int(entry.get("_judge_repair_claim_rounds") or 0), 0)
        self.assertNotIn(REPAIR_DISPATCH_FINGERPRINT_FIELD, entry)
        # 既有重验流程零变化
        self.engine._on_spec_done(self.FIX)
        self.assertEqual(self._entry().get("status"), "implemented")


class TestEngineGateMissingProbeRejected(_GateBase):
    """缺探针标注且无新鲜轮 → 按「缺探针标注」拒收（D1 优先级③）。"""

    def setUp(self):
        super().setUp()
        self._make_bug_found_parent()
        self._make_fix_done()
        _attach_envelope(self.sm, self.PARENT, {"scn-a": "dispatchfp00001"})
        # 不写 probe 快照、不写 report.json（②无新鲜轮）

    def test_missing_probe_rejected(self):
        rv = self.engine._repair_claim_fingerprint_gate(self.PARENT, self.FIX)
        self.assertTrue(rv)
        entry = self._entry()
        error = str(entry.get("error") or "")
        self.assertIn("缺探针标注", error)
        self.assertIn("scn-a=dispatchfp00", error, "拒收信息含派单指纹值（brief 截断）")
        self.assertEqual(
            int(entry.get("_judge_repair_rejected_rounds") or 0), 1
        )
        self.assertEqual(entry.get("status"), "bug-found")


class TestEngineGateFreshRoundBranch(_GateBase):
    """盘面 post-fix 新鲜轮指纹源分支（D1 优先级②）。"""

    def setUp(self):
        super().setUp()
        self._make_bug_found_parent()
        self._make_fix_done()
        sc_same = _failed_scenario("scn-a", expected="同签名失败")
        self.fp_same = scenario_fingerprint(sc_same)
        _attach_envelope(self.sm, self.PARENT, {"scn-a": self.fp_same})

    def test_fresh_round_unchanged_rejected(self):
        # 新鲜轮（report mtime 晚于派单 envelope 的 at=1700000000）同签名复现
        _write_report(self.verify_dir, [_failed_scenario("scn-a", expected="同签名失败")])
        rv = self.engine._repair_claim_fingerprint_gate(self.PARENT, self.FIX)
        self.assertTrue(rv, "新鲜轮同指纹 MUST 拒收")
        self.assertIn(
            "失败指纹未变化", str(self._entry().get("error") or "")
        )

    def test_fresh_round_changed_accepted(self):
        # 新鲜轮指纹变化（失败断言内容不同 → 指纹不同）→ 放行
        _write_report(self.verify_dir, [_failed_scenario("scn-a", expected="失败内容已不同")])
        rv = self.engine._repair_claim_fingerprint_gate(self.PARENT, self.FIX)
        self.assertFalse(rv)
        self.assertEqual(
            int(self._entry().get("_judge_repair_rejected_rounds") or 0), 0
        )

    def test_fresh_round_all_pass_accepted(self):
        # 新鲜轮全 pass（fresh_fps 空）→ 场景已转 pass → 放行
        verify_dir = self.verify_dir
        verify_dir.mkdir(parents=True, exist_ok=True)
        (verify_dir / "report.json").write_text(
            json.dumps(
                {"spec": self.PARENT,
                 "summary": {"total": 1, "passed": 1, "failed": 0},
                 "scenarios": [
                     {"scenario_id": "scn-a", "status": "pass",
                      "assertion_results": [], "step_results": []}
                 ]},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        rv = self.engine._repair_claim_fingerprint_gate(self.PARENT, self.FIX)
        self.assertFalse(rv, "场景已转 pass MUST 放行")

    def test_stale_report_not_treated_as_fresh_round(self):
        # report mtime 早于派单时刻（at=1700000000 → 2023-11）＝无新鲜轮 →
        # 走缺探针拒收，不以派单同轮旧报告自证（恒等死锁防护）
        import os

        _write_report(self.verify_dir, [_failed_scenario("scn-a", expected="同签名失败")])
        os.utime(
            self.verify_dir / "report.json", (1690000000, 1690000000)
        )
        rv = self.engine._repair_claim_fingerprint_gate(self.PARENT, self.FIX)
        self.assertTrue(rv)
        self.assertIn("缺探针标注", str(self._entry().get("error") or ""))


class TestFastlaneConsumptionGate(unittest.TestCase):
    """fastlane 子集重验消费点：记账与拒收留痕，路由零变化。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.sm = StateMachine(
            Path(self.tmpdir) / ".fenix" / "STATE.md", MagicMock()
        )
        self.sm.add_spec("demo-spec", {"priority": 5})
        self.sm.transition("demo-spec", "ready")
        self.sm.transition("demo-spec", "implementing")
        self.sm.transition("demo-spec", "implemented")
        self.sm.transition("demo-spec", "testing")
        self.sm.transition("demo-spec", "bug-found")

        from core.pm_engine.verification import VerificationPipeline

        pm = SimpleNamespace()
        pm.project_root = Path(self.tmpdir)
        pm.logger = MagicMock()
        pm.state_machine = self.sm
        pm.agent_runner = MagicMock()
        self.pipe = VerificationPipeline(pm)
        self.record_failure = MagicMock(return_value={"dispatched": False})

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run(self, subset_ids, reverify_ret, prev_report=None):
        with patch(
            "core.pm_engine.verification.fastlane.subset_reverify",
            return_value=reverify_ret,
        ), patch(
            "core.verdict_check.load_report", return_value=prev_report
        ), patch(
            "core.verdict_check.save_report"
        ):
            from core.pm_engine.verification.fastlane import (
                _fastlane_reverify_and_converge,
            )

            return _fastlane_reverify_and_converge(
                self.pipe, "demo-spec",
                run_id="code-fix-fastlane-x", subset_ids=subset_ids,
                record_failure=self.record_failure,
            )

    def _entry(self):
        return self.sm.read_one("demo-spec") or {}

    def test_unchanged_fingerprint_rejected_and_fallback_continues(self):
        sc = _failed_scenario("scn-a")
        _attach_envelope(self.sm, "demo-spec", {"scn-a": scenario_fingerprint(sc)})
        rv = self._run(
            ["scn-a"],
            {"ok": False, "report": {
                "summary": {"total": 1, "passed": 0, "failed": 1, "errors": 0},
                "scenarios": [sc],
            }},
        )
        entry = self._entry()
        self.assertEqual(int(entry.get("_judge_repair_claim_rounds") or 0), 1)
        self.assertEqual(
            int(entry.get("_judge_repair_rejected_rounds") or 0), 1
        )
        self.assertIn("失败指纹未变化", str(entry.get("error") or ""))
        self.assertEqual(entry.get("status"), "bug-found", "spec 保持当前态")
        # 路由零变化：既有回落整轮路径照常执行
        self.record_failure.assert_called_once()
        self.assertIn("子集重验未收敛", str(self.record_failure.call_args[0][0]))

    def test_changed_fingerprint_accepted(self):
        sc_old = _failed_scenario("scn-a", expected="旧失败")
        _attach_envelope(self.sm, "demo-spec", {"scn-a": scenario_fingerprint(sc_old)})
        sc_new = _failed_scenario("scn-a", expected="新失败形态")
        self._run(
            ["scn-a"],
            {"ok": False, "report": {
                "summary": {"total": 1, "passed": 0, "failed": 1, "errors": 0},
                "scenarios": [sc_new],
            }},
        )
        entry = self._entry()
        self.assertEqual(int(entry.get("_judge_repair_claim_rounds") or 0), 1)
        self.assertEqual(
            int(entry.get("_judge_repair_rejected_rounds") or 0), 0
        )
        self.assertNotIn("失败指纹未变化", str(entry.get("error") or ""))

    def test_subset_scope_not_counted_as_progress(self):
        # 子集重验新鲜轮只覆盖子集：子集外场景不在被修面（不得视为已转 pass）
        sc_sub = _failed_scenario("scn-sub")
        sc_out = _failed_scenario("scn-out")
        _attach_envelope(
            self.sm, "demo-spec",
            {"scn-sub": scenario_fingerprint(sc_sub),
             "scn-out": scenario_fingerprint(sc_out)},
        )
        self._run(
            ["scn-sub"],
            {"ok": False, "report": {
                "summary": {"total": 1, "passed": 0, "failed": 1, "errors": 0},
                "scenarios": [sc_sub],
            }},
        )
        self.assertEqual(
            int(self._entry().get("_judge_repair_rejected_rounds") or 0), 1,
            "被修面（子集）内指纹未变化仍 MUST 拒收",
        )

    def test_no_fresh_round_gate_skipped(self):
        # env abort（report=None）＝无新鲜轮可裁决 → 指纹门跳过，零记账
        _attach_envelope(self.sm, "demo-spec", {"scn-a": "somefp000001"})
        self._run(["scn-a"], {"ok": False, "report": None,
                              "reason": "环境错误: xxx"})
        entry = self._entry()
        self.assertEqual(int(entry.get("_judge_repair_claim_rounds") or 0), 0)
        self.assertEqual(
            int(entry.get("_judge_repair_rejected_rounds") or 0), 0
        )
        self.record_failure.assert_called_once()

    def test_no_baseline_gate_skipped(self):
        # 无派单基线（legacy 链）→ 指纹门跳过，行为零变化
        sc = _failed_scenario("scn-a")
        self._run(
            ["scn-a"],
            {"ok": False, "report": {
                "summary": {"total": 1, "passed": 0, "failed": 1, "errors": 0},
                "scenarios": [sc],
            }},
        )
        entry = self._entry()
        self.assertEqual(int(entry.get("_judge_repair_claim_rounds") or 0), 0)
        self.record_failure.assert_called_once()

    def test_converged_accepted(self):
        # 子集重验通过（场景已转 pass）→ 受理放行记账
        sc = _failed_scenario("scn-a")
        _attach_envelope(self.sm, "demo-spec", {"scn-a": scenario_fingerprint(sc)})
        self._run(
            ["scn-a"],
            {"ok": True, "report": {
                "summary": {"total": 1, "passed": 1, "failed": 0, "errors": 0},
                "scenarios": [
                    {"scenario_id": "scn-a", "status": "pass",
                     "assertion_results": [], "step_results": []}
                ],
            }},
        )
        entry = self._entry()
        self.assertEqual(
            int(entry.get("_judge_repair_rejected_rounds") or 0), 0
        )
        # 收敛主链在首个 transition 被拒（stub sm 未推进状态机）时回落，
        # 但受理记账已在收敛判定前落盘
        self.assertEqual(int(entry.get("_judge_repair_claim_rounds") or 0), 1)


class TestDispatchSideAttach(unittest.TestCase):
    """派单侧随单附指纹：envelope 持久化 + 无基线置 null + detail 注入。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.sm = StateMachine(
            Path(self.tmpdir) / ".fenix" / "STATE.md", MagicMock()
        )
        self.sm.add_spec("demo-spec", {"priority": 5})
        from core.pm_engine.verification import VerificationPipeline

        pm = SimpleNamespace()
        pm.project_root = Path(self.tmpdir)
        pm.logger = MagicMock()
        pm.state_machine = self.sm
        pm.agent_runner = MagicMock()
        self.pipe = VerificationPipeline(pm)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _envelope(self):
        raw = (self.sm.read_one("demo-spec") or {}).get(
            REPAIR_DISPATCH_FINGERPRINT_FIELD
        )
        return json.loads(raw) if isinstance(raw, str) else raw

    def test_attach_persists_envelope(self):
        verify_dir = (
            Path(self.tmpdir) / ".fenix" / "verify-progress" / "demo-spec"
        )
        _write_report(verify_dir, [_failed_scenario("scn-a")])
        fps = attach_dispatch_fingerprint(
            self.pipe, "demo-spec", dispatch_run_id="judge-r1"
        )
        self.assertTrue(fps)
        env = self._envelope()
        self.assertEqual(env["fps"], fps)
        self.assertEqual(env["run"], "judge-r1")
        self.assertIn("at", env)

    def test_attach_no_baseline_writes_empty_and_returns_none(self):
        fps = attach_dispatch_fingerprint(self.pipe, "demo-spec")
        self.assertIsNone(fps, "无基线置 null，不阻断派发")
        env = self._envelope()
        self.assertEqual(env["fps"], {})

    def test_attach_failure_clears_stale_envelope(self):
        # 旧轮 envelope 残留 + 本轮报告不可读 → 显式清字段防陈旧基线假拒收
        _attach_envelope(self.sm, "demo-spec", {"scn-a": "stalefp000001"})
        with patch(
            "core.verdict_check.load_report", side_effect=OSError("boom")
        ):
            fps = attach_dispatch_fingerprint(self.pipe, "demo-spec")
        self.assertIsNone(fps)
        self.assertIsNone(self._envelope(), "异常 MUST 清字段")

    def test_detail_injection_null_without_baseline(self):
        detail = dispatch_fingerprint_detail(self.sm, "demo-spec")
        self.assertIsNone(detail["repair_fingerprint"])
        self.assertEqual(detail["repair_fingerprint_brief"], "无基线")

    def test_detail_injection_with_baseline(self):
        _attach_envelope(self.sm, "demo-spec", {"scn-a": "fp123456789abc"})
        detail = dispatch_fingerprint_detail(self.sm, "demo-spec")
        self.assertEqual(detail["repair_fingerprint"], {"scn-a": "fp123456789abc"})
        self.assertIn("scn-a=fp123456789a", detail["repair_fingerprint_brief"])


class TestBudgetSemanticsUnchanged(_GateBase):
    """预算口径不变：拒收只动观测计数；test-defect 通道零指纹留痕。"""

    def test_rejection_does_not_touch_budget_fields(self):
        self._make_bug_found_parent()
        self._make_fix_done()
        sc = _failed_scenario("scn-a")
        _attach_envelope(self.sm, self.PARENT, {"scn-a": scenario_fingerprint(sc)})
        self._write_probe_snapshot(
            {"scenario_id": "scn-a", "fingerprint": scenario_fingerprint(sc),
             "matches_dispatch": True}
        )
        self.engine._repair_claim_fingerprint_gate(self.PARENT, self.FIX)
        entry = self._entry()
        # 修复预算耗尽持久字段与打回轮计数不被本门触碰
        self.assertEqual(
            int(entry.get("_scenario_repair_exhausted_rounds") or 0), 0
        )
        self.assertEqual(int(entry.get("_verify_fail_rounds") or 0), 0)
        self.assertNotIn("_fastlane_fail_streak", entry)

    def test_legacy_call_sites_no_fingerprint_trace(self):
        # 既有 test-defect 通道调用点（不传指纹 kwargs）→ 零指纹留痕（行为零变化）
        self._make_bug_found_parent()
        from core.pm_engine.verification.pipeline import _record_repair_claim
        from types import SimpleNamespace as NS

        target = NS(_context=NS(
            state_machine=self.sm, logger=self.logger,
            project_root=self.project_root,
        ))
        _record_repair_claim(target, self.PARENT, rejected=True)
        entry = self._entry()
        self.assertEqual(int(entry.get("_judge_repair_claim_rounds") or 0), 1)
        self.assertEqual(
            int(entry.get("_judge_repair_rejected_rounds") or 0), 1
        )
        self.assertNotIn("_judge_repair_last_dispatch_fp", entry)
        self.assertNotIn("_judge_repair_last_fresh_fp", entry)

    def test_scenario_repaired_channel_zero_change(self):
        # test-defect 场景修复通道：非 scenario-repaired 状态快速返回 False，
        # 不触发指纹门（既有受理门行为零变化锚点）
        self._make_bug_found_parent()
        from core.pm_engine.verification import VerificationPipeline

        pm = SimpleNamespace()
        pm.project_root = self.project_root
        pm.logger = self.logger
        pm.state_machine = self.sm
        pm.agent_runner = MagicMock()
        pipe = VerificationPipeline(pm)
        pipe._run_three_stage_verification = MagicMock()
        self.assertEqual(
            pipe._handle_scenario_repaired(self.PARENT, "bug-found", 0), False
        )
        self.pipe = pipe


class TestGateHelperEdgeCases(unittest.TestCase):
    """门辅助函数边界（覆盖收集/提取/评定的防御面）。"""

    def test_collect_skips_pass_and_empty_sid(self):
        report = {
            "scenarios": [
                {"scenario_id": "ok-1", "status": "pass",
                 "assertion_results": [], "step_results": []},
                {"status": "failed", "assertion_results": [],
                 "step_results": []},
                _failed_scenario("f-1"),
            ]
        }
        fps = collect_failed_fingerprints(report)
        self.assertEqual(list(fps), ["f-1"])
        # scope 限制（子集重验新鲜轮只覆盖子集）
        fps2 = collect_failed_fingerprints(report, scope={"f-1"})
        self.assertEqual(list(fps2), ["f-1"])

    def test_probe_shape_validation(self):
        self.assertIsNone(probe_claim_from_result({}))
        self.assertIsNone(probe_claim_from_result(
            {"verification": {"repair_probe": "not-a-dict"}}))
        self.assertIsNone(probe_claim_from_result(
            {"verification": {"repair_probe": {"scenario_id": "", "fingerprint": "x"}}}))
        self.assertIsNone(probe_claim_from_result(
            {"verification": {"repair_probe": {"scenario_id": "s", "fingerprint": "  "}}}))

    def test_evaluate_no_overlap_probe_accepts(self):
        verdict, _ = evaluate_fingerprint_gate(
            {"other": "fp"}, {"scn-a": "fp"}, coverage="probe"
        )
        self.assertEqual(verdict, "accept")

    def test_load_envelope_corrupt_returns_none(self):
        sm = MagicMock()
        sm.read_one.return_value = {
            REPAIR_DISPATCH_FINGERPRINT_FIELD: "not-json{"
        }
        self.assertIsNone(load_dispatch_fingerprint(sm, "demo-spec"))
        sm.read_one.return_value = {}
        self.assertIsNone(load_dispatch_fingerprint(sm, "demo-spec"))
        self.assertIsNone(load_dispatch_fingerprint(sm, "missing-spec"))


if __name__ == "__main__":
    unittest.main()
