"""
裁决 env 豁免握手与 serving dist 新鲜度探针单元测试
（fix-verdict-env-exemption-admin-handshake tasks 4.1-4.3）

覆盖：
  - 级二判据（tasks 4.1）：混合形态（原始 failed>0 且断言级 triage 全部 env、
    场景级 classification 未标 env）命中转 inconclusive；含 product-bug /
    test-defect 断言不命中走 bug-found；flaky 断言混合形态维持既有豁免放行
    不转重验；全批 blocked-env 级一先命中短路（judge 不被调用）；豁免清单
    为空 verified 直通
  - 升级与守卫（tasks 4.2，fix-env-exemption-exit-reachability 1.1 更新为
    首次命中即升级）：级二命中写 SIGNAL + 带 choices 人工告警、停车等待人工、
    不再自动重验；无 admin 放行记录时豁免不得落 verified；放行记录存在后
    豁免生效且报告含处置回链
  - 探针（tasks 4.3，tmp_path 伪造 src/dist mtime）：dist 新鲜直通零重建、
    滞后重建成功后开跑、重建失败错误现场留痕且不静默开跑、worktree 自建
    形态直通
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# 确保 tests 目录在 import 路径（兼容直接执行）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.admin_store import AdminStore, DISPOSITION, ESCALATION, SIGNAL
from core.pm_engine.engine import PMEngine
from core.state_machine import StateMachine
from core.verdict_check import load_report


class _FakeLogger:
    def __init__(self):
        self.messages = []

    def _log(self, level, *args):
        self.messages.append((level,) + tuple(str(a) for a in args))

    def info(self, *args):
        self._log("info", *args)

    def warning(self, *args):
        self._log("warning", *args)

    def error(self, *args):
        self._log("error", *args)

    def debug(self, *args):
        self._log("debug", *args)


def _mk_engine(tmpdir, escalate_attempts=4, max_attempts=3):
    """构造 PMEngine 实例（临时 STATE + 真实 StateMachine + AdminStore）。"""
    project_root = Path(tmpdir)
    (project_root / ".fenix").mkdir(parents=True, exist_ok=True)
    logger = _FakeLogger()
    sm = StateMachine(project_root / ".fenix" / "STATE.md", logger)
    config = {"verify_engine": {
        "inconclusive_escalate_attempts": escalate_attempts,
        "inconclusive_max_attempts": max_attempts,
    }}
    engine = PMEngine(sm, mock.MagicMock(), config, project_root, logger)
    sm.add_spec("s1", {"priority": 5})
    sm.update_spec("s1", {"status": "testing"})
    return engine, sm, logger


def _write_report(tmpdir, spec, report):
    """裁决产物落盘（judge 增强后的 report.json 同位置）。"""
    path = Path(tmpdir) / ".fenix" / "verify-progress" / spec / "report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return path


def _pass_scenarios(n=19):
    return [{"scenario_id": f"pass-{i}", "status": "pass"} for i in range(n)]


def _env_fail_scenario(sid="fail-env-0", n_assertions=1):
    """断言级 triage 全 env、场景级 classification 未标 env 的失败场景。"""
    return {
        "scenario_id": sid,
        "status": "failed",
        "assertion_triage": [
            {
                "assertion": f"text=空态文案 {i}",
                "classification": "env",
                "evidence": "served dist 为中间态构建",
            }
            for i in range(n_assertions)
        ],
    }


def _mixed_env_report(passed=19, failed=2, blocked=1):
    """add-session-composer 事故同形态：19 passed + 2 failed + 1 blocked_env。"""
    scenarios = _pass_scenarios(passed)
    scenarios.extend(
        _env_fail_scenario(sid=f"fail-env-{i}", n_assertions=3) for i in range(failed)
    )
    for i in range(blocked):
        scenarios.append({
            "scenario_id": f"blk-{i}",
            "status": "blocked-env",
            "env_probe_detail": "HTTP 探测失联",
        })
    return {
        "summary": {
            "total": len(scenarios), "passed": passed,
            "warnings": blocked, "failed": failed, "errors": 0,
            "blocked_env": blocked,
        },
        "scenarios": scenarios,
    }


def _dispositions(tmpdir):
    store = AdminStore(Path(tmpdir), _FakeLogger())
    return [r for r in store.read_all() if r.get("kind") == DISPOSITION]


def _signals(tmpdir):
    store = AdminStore(Path(tmpdir), _FakeLogger())
    return [r for r in store.read_all() if r.get("kind") == SIGNAL]


def store_records(tmpdir, kind):
    """按 kind 过滤 admin store 记录（ESCALATION 断言用）。"""
    store = AdminStore(Path(tmpdir), _FakeLogger())
    return [r for r in store.read_all() if r.get("kind") == kind]


# ── tasks 4.1：级二判据 ──────────────────────────────────────────────────


class TestLevel2Criteria(unittest.TestCase):
    """Scenario: 裁决豁免触发重验而非放行 / 级二判据边界。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))

    def test_mixed_form_all_env_assertions_first_hit_parks(self):
        """混合形态（failed>0 且断言级 triage 全 env、场景级未标 env）→ 首次
        命中即升级停车：回 implemented 等人工裁决、tester_run 清空、不重验。"""
        engine, sm, _ = _mk_engine(self.tmpdir)
        report = _mixed_env_report()
        with mock.patch.object(engine, "_enqueue") as enq:
            handled = engine._verification._handle_env_exemption_handshake("s1", report)
        self.assertTrue(handled, "级二命中应由握手处置（不得落 verified）")
        spec = sm.read_one("s1")
        self.assertEqual(spec["status"], "implemented", "应停车 implemented 等待人工")
        self.assertIsNone(spec["tester_run"], "tester_run 应清空")
        self.assertEqual(int(spec["_inconclusive_attempts"]), 1, "首次命中即升级")
        enq.assert_not_called()
        self.assertNotEqual(spec["status"], "verified")

    def test_product_bug_assertion_not_hit(self):
        """含 product-bug 断言不命中——走既有 bug-found，env 部分留豁免记录。"""
        engine, sm, _ = _mk_engine(self.tmpdir)
        report = _mixed_env_report(failed=2, blocked=0)
        report["scenarios"][19]["assertion_triage"] = [
            {"assertion": "按钮无响应", "classification": "product-bug",
             "evidence": "点击后无网络请求"},
        ]
        handled = engine._verification._handle_env_exemption_handshake("s1", report)
        self.assertFalse(handled, "含 product-bug 断言不应命中级二")
        self.assertEqual(sm.read_one("s1")["status"], "testing", "状态不应被改动")

    def test_test_defect_assertion_not_hit(self):
        """含 test-defect 断言不命中（走既有场景缺陷链路）。"""
        engine, sm, _ = _mk_engine(self.tmpdir)
        report = _mixed_env_report(failed=2, blocked=0)
        report["scenarios"][19]["assertion_triage"] = [
            {"assertion": "text=已删除文案", "classification": "test-defect",
             "evidence": "断言与需求文档不符"},
        ]
        handled = engine._verification._handle_env_exemption_handshake("s1", report)
        self.assertFalse(handled, "含 test-defect 断言不应命中级二")

    def test_flaky_assertion_mixed_form_stays_exempt(self):
        """flaky 断言混合形态维持既有豁免放行，不转重验。"""
        engine, sm, _ = _mk_engine(self.tmpdir)
        report = _mixed_env_report(failed=2, blocked=0)
        report["scenarios"][20]["assertion_triage"] = [
            {"assertion": "列表顺序", "classification": "flaky",
             "evidence": "两次复现结果不一致"},
        ]
        handled = engine._verification._handle_env_exemption_handshake("s1", report)
        self.assertFalse(handled, "flaky 归类应维持既有豁免放行")
        self.assertEqual(sm.read_one("s1")["status"], "testing")

    def test_scenario_classification_fallback_hits(self):
        """场景缺 assertion_triage 时回退场景级 classification（env → 命中）。"""
        engine, sm, _ = _mk_engine(self.tmpdir)
        report = {
            "summary": {"total": 2, "passed": 1, "warnings": 0,
                        "failed": 1, "errors": 0, "blocked_env": 0},
            "scenarios": [
                {"scenario_id": "p-1", "status": "pass"},
                {"scenario_id": "f-1", "status": "failed",
                 "classification": "env",
                 "evidence": {"first_failed_step": "navigate /dashboard"}},
            ],
        }
        handled = engine._verification._handle_env_exemption_handshake("s1", report)
        self.assertTrue(handled, "场景级 classification=env 回退判定应命中")

    def test_all_blocked_env_level1_short_circuits_judge(self):
        """全批 blocked-env：级一（阶段 2.6）先命中短路，judge 不被调用。"""
        engine, sm, _ = _mk_engine(self.tmpdir)
        report = _mixed_env_report(passed=0, failed=0, blocked=3)
        report["summary"].update({"warnings": 3})
        with mock.patch.object(engine.agent_runner, "run_planner") as judge, \
                mock.patch.object(engine, "_enqueue") as enq:
            fail_count, judge_result, aborted = engine._verification._run_stage2_gates(
                "s1", report, True, ""
            )
        self.assertTrue(aborted, "级一命中应短路（aborted=True）")
        self.assertIsNone(judge_result, "级一命中不走全绿快道合成")
        judge.assert_not_called()
        enq.assert_any_call("s1", "verifier")
        self.assertEqual(int(sm.read_one("s1")["_inconclusive_attempts"]), 1)

    def test_no_exemption_all_green_passes_through(self):
        """豁免清单为空（全绿）：verified 直通零改动。"""
        engine, sm, _ = _mk_engine(self.tmpdir)
        report = {
            "summary": {"total": 20, "passed": 20, "warnings": 0,
                        "failed": 0, "errors": 0, "blocked_env": 0},
            "scenarios": _pass_scenarios(20),
        }
        handled = engine._verification._handle_env_exemption_handshake("s1", report)
        self.assertFalse(handled, "全绿无豁免对象应零改动直通")
        self.assertEqual(sm.read_one("s1")["status"], "testing")

    def test_missing_report_passes_through(self):
        """无裁决产物（report 缺失）不制造新失败模式，直通。"""
        engine, sm, _ = _mk_engine(self.tmpdir)
        handled = engine._verification._handle_env_exemption_handshake("s1", None)
        self.assertFalse(handled)


# ── tasks 4.2：升级与守卫 ────────────────────────────────────────────────


class TestEscalationAndGuard(unittest.TestCase):
    """Scenario: 连续 env 失联唤起 Administrator / admin 确认后豁免生效。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))

    def test_first_hit_writes_signal_choices_alert_and_parks(self):
        """首次命中即升级：SIGNAL + 带 choices 的人工告警各一条，停车等人工。"""
        engine, sm, _ = _mk_engine(self.tmpdir)
        report = _mixed_env_report()
        handled = engine._verification._handle_env_exemption_handshake("s1", report)
        self.assertTrue(handled)
        sigs = [s for s in _signals(self.tmpdir)
                if s.get("signal_type") == "inconclusive_loop"]
        self.assertEqual(len(sigs), 1, "首次命中即写一条 inconclusive_loop SIGNAL")
        rec = sigs[0]
        self.assertEqual(str(rec.get("spec")), "s1")
        self.assertIn("连续轮数=1", rec.get("evidence") or "")
        self.assertIn("签名摘要=", rec.get("evidence") or "")
        escs = [r for r in store_records(self.tmpdir, ESCALATION)
                if r.get("signal_type") == "inconclusive_loop"]
        self.assertEqual(len(escs), 1, "人工告警恰一条（双通道并存）")
        choice_ids = [c.get("id") for c in escs[0].get("choices") or []]
        self.assertIn("grant_env_exemption", choice_ids, "告警应快照裁决 choices")
        spec = sm.read_one("s1")
        self.assertEqual(spec["status"], "implemented")
        self.assertIn("放行", spec.get("error") or "", "error 现场应含人工放行指引")
        self.assertTrue(
            int(spec.get("_dispatch_backoff_until") or 0) > 0,
            "暂停自动重验应有退避窗",
        )
        self.assertEqual(int(spec["_inconclusive_attempts"]), 1)

    def test_no_release_record_exemption_not_verified(self):
        """无 admin 放行记录：豁免不得落 verified（停车 implemented 等待）。"""
        engine, sm, _ = _mk_engine(self.tmpdir)
        report = _mixed_env_report()
        handled = engine._verification._handle_env_exemption_handshake("s1", report)
        self.assertTrue(handled)
        self.assertEqual(sm.read_one("s1")["status"], "implemented")
        self.assertEqual(_dispositions(self.tmpdir), [], "前置：不应有处置记录")

    def test_release_record_enables_verified_with_backlink(self):
        """放行记录存在：豁免生效放行（返回 False），报告保留处置回链。"""
        engine, sm, _ = _mk_engine(self.tmpdir)
        _write_report(self.tmpdir, "s1", _mixed_env_report())
        store = AdminStore(Path(self.tmpdir), _FakeLogger())
        store.append({
            "kind": DISPOSITION,
            "signal_type": "inconclusive_loop",
            "spec": "s1",
            "severity": "major",
            "description": "连续 4 轮 env 失联",
            "action_taken": "确认事件源在本环境不可达且无补救手段，人工放行",
            "result": "resolved",
        })
        handled = engine._verification._handle_env_exemption_handshake("s1")
        self.assertFalse(handled, "查得放行记录应放行（返回 False 走既有 verified 链）")
        saved = load_report(Path(self.tmpdir), "s1")
        backlink = saved.get("admin_disposition_backlink")
        self.assertIsInstance(backlink, dict, "报告应保留处置回链")
        self.assertEqual(backlink.get("signal_type"), "inconclusive_loop")
        self.assertEqual(backlink.get("result"), "resolved")
        self.assertEqual(sm.read_one("s1")["status"], "testing", "放行轮不改状态")

    def test_non_resolved_disposition_not_release(self):
        """处置未成功（result 非 resolved）不构成放行锚，仍转 inconclusive。"""
        engine, sm, _ = _mk_engine(self.tmpdir)
        store = AdminStore(Path(self.tmpdir), _FakeLogger())
        store.append({
            "kind": DISPOSITION,
            "signal_type": "inconclusive_loop",
            "spec": "s1",
            "result": "failed",
            "description": "处置未成功",
        })
        handled = engine._verification._handle_env_exemption_handshake(
            "s1", _mixed_env_report()
        )
        self.assertTrue(handled, "非 resolved 处置不得放行")
        self.assertEqual(sm.read_one("s1")["status"], "implemented")

    def test_other_spec_disposition_not_release(self):
        """放行锚按 spec 隔离：他 SPEC 的处置记录不放行本 SPEC。"""
        engine, sm, _ = _mk_engine(self.tmpdir)
        store = AdminStore(Path(self.tmpdir), _FakeLogger())
        store.append({
            "kind": DISPOSITION,
            "signal_type": "inconclusive_loop",
            "spec": "other-spec",
            "result": "resolved",
        })
        handled = engine._verification._handle_env_exemption_handshake(
            "s1", _mixed_env_report()
        )
        self.assertTrue(handled, "他 SPEC 的放行记录不得放行本 SPEC")

    def test_parked_spec_keeps_auto_reverify_stopped(self):
        """升级停车后（无放行）：自动重验保持停止——重复命中只重复停车。"""
        engine, sm, _ = _mk_engine(self.tmpdir)
        report = _mixed_env_report()
        engine._verification._handle_env_exemption_handshake("s1", report)
        spec = sm.read_one("s1")
        self.assertEqual(spec["status"], "implemented")
        self.assertEqual(int(spec["_inconclusive_attempts"]), 1)
        self.assertTrue(int(spec.get("_dispatch_backoff_until") or 0) > 0)
        with mock.patch.object(engine, "_enqueue") as enq:
            engine._verification._handle_env_exemption_handshake("s1", report)
        enq.assert_not_called()
        spec = sm.read_one("s1")
        self.assertEqual(spec["status"], "implemented", "重复命中也不落 verified")
        self.assertEqual(int(spec["_inconclusive_attempts"]), 2)


# ── tasks 4.3：serving dist 新鲜度探针 ──────────────────────────────────


class TestDistFreshnessProbe(unittest.TestCase):
    """Scenario: dist 滞后先重建再开跑 / 新鲜零开销直通 / 重建失败不静默开跑。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))
        self.engine, self.sm, _ = _mk_engine(self.tmpdir)
        static_root = Path(self.tmpdir) / "core" / "dashboard" / "static"
        self.src_file = static_root / "src" / "main.tsx"
        self.src_file.parent.mkdir(parents=True, exist_ok=True)
        self.src_file.write_text("console.log(1)")
        self.dist_entry = static_root / "dist" / "index.html"
        self.dist_entry.parent.mkdir(parents=True, exist_ok=True)
        self.dist_entry.write_text("<html>stale</html>")
        self.patcher = mock.patch(
            "core.worktree_manager.dist_conflicts.run_dist_build",
            return_value=True,
        )
        self.run_build = self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_fresh_dist_passthrough_zero_rebuild(self):
        """dist 新鲜（构建晚于 src）：零动作直通，无重建无副作用。"""
        os.utime(self.dist_entry, (3000, 3000))
        os.utime(self.src_file, (2000, 2000))
        err = self.engine._verification._probe_dist_freshness("s1")
        self.assertEqual(err, "", "dist 新鲜应直通")
        self.run_build.assert_not_called()

    def test_stale_dist_rebuild_success_then_run(self):
        """src 较新判滞后：自动重建成功后放行开跑。"""
        os.utime(self.dist_entry, (1000, 1000))
        os.utime(self.src_file, (2000, 2000))
        err = self.engine._verification._probe_dist_freshness("s1")
        self.assertEqual(err, "", "重建成功应放行开跑")
        self.assertEqual(self.run_build.call_count, 1)

    def test_stale_dist_rebuild_failure_leaves_evidence_no_silent_run(self):
        """重建失败：错误现场（构建失败尾部日志）留痕且不静默开跑。"""

        def _fail_build(project_root, static_root, logger, error_detail=None):
            if error_detail is not None:
                error_detail.append("npm ERR! missing script: build")
            return False

        self.run_build.side_effect = _fail_build
        os.utime(self.dist_entry, (1000, 1000))
        os.utime(self.src_file, (2000, 2000))
        err = self.engine._verification._probe_dist_freshness("s1")
        self.assertIn("npm ERR! missing script: build", err, "错误现场应含尾部日志")
        self.assertIn("重建失败", err)

        # 该轮按 blocked-env/inconclusive 路径处置：合成报告交既有级一门禁
        report = self.engine._verification._dist_probe_block_report(
            "s1", [{"id": "sc-1"}, {"id": "sc-2"}], err
        )
        self.assertEqual(report["summary"]["blocked_env"], 2)
        self.assertEqual(report["summary"]["failed"] + report["summary"]["errors"], 0)
        for sc in report["scenarios"]:
            self.assertEqual(sc["status"], "blocked-env")
            self.assertIn("npm ERR!", sc["env_probe_detail"])
        saved = load_report(Path(self.tmpdir), "s1")
        self.assertTrue(saved.get("dist_probe", {}).get("stale"))
        with mock.patch.object(self.engine, "_enqueue"):
            handled = self.engine._verification._handle_env_blocked_inconclusive(
                "s1", report
            )
        self.assertTrue(handled, "合成报告应按 inconclusive 路径处置")
        self.assertEqual(int(self.sm.read_one("s1")["_inconclusive_attempts"]), 1)

    def test_worktree_selfbuilt_form_passthrough(self):
        """worktree 自建形态（prepare 已在本 worktree 构建）：探针直通。"""
        os.utime(self.dist_entry, (1000, 1000))
        os.utime(self.src_file, (2000, 2000))
        self.engine._verification._contract_static_servers = {
            "s1": {"wt_path": str(Path(self.tmpdir) / "wt"), "mode": "static"},
        }
        err = self.engine._verification._probe_dist_freshness("s1")
        self.assertEqual(err, "", "worktree 自建形态应直通")
        self.run_build.assert_not_called()

    def test_no_dashboard_src_passthrough(self):
        """dashboard static src 不存在（非该形态）：探针直通无对象。"""
        shutil.rmtree(Path(self.tmpdir) / "core" / "dashboard" / "static" / "src")
        err = self.engine._verification._probe_dist_freshness("s1")
        self.assertEqual(err, "")
        self.run_build.assert_not_called()

    def test_missing_dist_entry_passthrough(self):
        """served dist 从未构建：交既有 prepare 流程兜底，探针不制造失败。"""
        self.dist_entry.unlink()
        err = self.engine._verification._probe_dist_freshness("s1")
        self.assertEqual(err, "")
        self.run_build.assert_not_called()


if __name__ == "__main__":
    unittest.main()
