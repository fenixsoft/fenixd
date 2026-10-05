"""
env 豁免握手转人工出口可达性单元测试（fix-env-exemption-exit-reachability tasks 5.1-5.3）

覆盖：
  - 级二首次命中即升级（5.1）：SIGNAL + 带 choices 的人工告警双通道各一条、
    不 enqueue verifier（自动重验停止）、attempts 停 1、退避窗就位
  - grant_env_exemption 执行器（5.1）：DISPOSITION 放行记录落库 + 重置重验
    （计数/旗标/签名基准/退避窗清零）+ 幂等放行闭环（重验后握手查得放行、
    报告带 admin_disposition_backlink 回链）
  - DISPOSITION 写失败 fail-closed（5.1）：store 拒写时不执行重置
  - 级一签名一致提前升级 / 签名变化继续重验 / 基准缺失保守走计数上限 /
    缺省重验上限 2（5.2）
  - judge 预算隔离（5.3）：旗标置位 gate 分流且 _judge_rerun_count 不动、
    独立计数器到顶停车不冻结、旗标未置生命周期账照旧、非 env 结论清旗标
    （单一助手）、verified 落定三字段清零、reset_verification 清新字段
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# 确保 tests 目录在 import 路径（兼容直接执行）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.admin_store import AdminStore, DISPOSITION, ESCALATION, SIGNAL
from core.dashboard.data.admin_actions import (
    execute_adjudication_choice,
    reset_verification,
)
from core.pm_engine.engine import PMEngine
from core.pm_engine.verification.escalation import (
    INCONCLUSIVE_PARKING_ERROR_MARKER,
)
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


def _mk_engine(tmpdir, config=None):
    """构造 PMEngine 实例（临时 STATE + 真实 StateMachine + AdminStore）。

    config 缺省为空 dict——走生产缺省值（inconclusive_max_attempts=2 等），
    显式传入以便隔离考察单一路径。
    """
    project_root = Path(tmpdir)
    (project_root / ".fenix").mkdir(parents=True, exist_ok=True)
    logger = _FakeLogger()
    sm = StateMachine(project_root / ".fenix" / "STATE.md", logger)
    config = dict(config or {})
    engine = PMEngine(sm, mock.MagicMock(), config, project_root, logger)
    sm.add_spec("s1", {"priority": 5})
    sm.update_spec("s1", {"status": "testing"})
    return engine, sm, logger


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
    """judge 已裁决全 env 的混合形态（add-session-composer 事故同形态）。"""
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


def _blocked_env_report(sid="s-x"):
    """级一判据输入：全批 blocked-env（从未执行、无失败断言）。"""
    return {
        "summary": {
            "total": 1, "passed": 0, "warnings": 1,
            "failed": 0, "errors": 0, "blocked_env": 1,
        },
        "scenarios": [
            {"scenario_id": sid, "status": "blocked-env",
             "env_probe_detail": "HTTP 探测失联"},
        ],
    }


def _store_records(tmpdir, kind):
    store = AdminStore(Path(tmpdir), _FakeLogger())
    return [r for r in store.read_all() if r.get("kind") == kind]


def _is_flag_true(entry) -> bool:
    return str(entry.get("_in_inconclusive_reverify") or "").strip().lower() in (
        "true", "1",
    )


# ── 5.1：级二首次命中即升级 / grant 执行器 / fail-closed / 放行回链 ──────────


class TestLevel2FirstHitParking(unittest.TestCase):
    """Scenario: 级二豁免握手首次命中即升级停车（人工出口可达）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))

    def test_first_hit_parks_with_dual_channel_no_reverify(self):
        """首次命中：SIGNAL + 带 choices 的人工告警各一条、不重验、attempts 停 1。"""
        engine, sm, _ = _mk_engine(self.tmpdir)
        report = _mixed_env_report()
        with mock.patch.object(engine, "_enqueue") as enq:
            handled = engine._verification._handle_env_exemption_handshake("s1", report)
        self.assertTrue(handled, "级二命中应由握手处置（不得落 verified）")
        enq.assert_not_called()
        spec = sm.read_one("s1")
        self.assertEqual(spec["status"], "implemented", "停车 implemented 等人工裁决")
        self.assertIsNone(spec["tester_run"], "tester_run 应清空")
        self.assertEqual(int(spec["_inconclusive_attempts"]), 1, "首次命中即升级")
        self.assertTrue(_is_flag_true(spec), "预算隔离旗标应置位")
        self.assertTrue(int(spec.get("_dispatch_backoff_until") or 0) > 0,
                        "退避窗应就位（防 orphaned_state 误报）")
        self.assertIn(INCONCLUSIVE_PARKING_ERROR_MARKER, spec.get("error") or "")
        # 双通道：SIGNAL（Administrator）+ ESCALATION（人工告警带 choices）
        sigs = [r for r in _store_records(self.tmpdir, SIGNAL)
                if r.get("signal_type") == "inconclusive_loop"]
        self.assertEqual(len(sigs), 1, "SIGNAL 通道恰一条（放行查询锚点）")
        self.assertIn("连续轮数=1", sigs[0].get("evidence") or "")
        self.assertIn("签名摘要=", sigs[0].get("evidence") or "")
        escs = [r for r in _store_records(self.tmpdir, ESCALATION)
                if r.get("signal_type") == "inconclusive_loop"]
        self.assertEqual(len(escs), 1, "人工告警通道恰一条")
        choice_ids = [c.get("id") for c in escs[0].get("choices") or []]
        self.assertIn("grant_env_exemption", choice_ids, "告警应快照三选一 choices")
        self.assertIn("manual_fixed_reverify", choice_ids)
        self.assertIn("abandon", choice_ids)

    def test_repeat_hit_repeats_parking_never_reverify(self):
        """升级后重复命中：重复停车（不重验、不落 verified）。"""
        engine, sm, _ = _mk_engine(self.tmpdir)
        report = _mixed_env_report()
        engine._verification._handle_env_exemption_handshake("s1", report)
        with mock.patch.object(engine, "_enqueue") as enq:
            handled = engine._verification._handle_env_exemption_handshake("s1", report)
        self.assertTrue(handled)
        enq.assert_not_called()
        spec = sm.read_one("s1")
        self.assertEqual(spec["status"], "implemented", "不得落 verified")
        self.assertEqual(int(spec["_inconclusive_attempts"]), 2, "只重复停车计数")


def _write_report(tmpdir, spec, report):
    """裁决产物落盘（judge 增强后的 report.json 同位置）。"""
    path = Path(tmpdir) / ".fenix" / "verify-progress" / spec / "report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return path


class TestGrantEnvExemptionExecutor(unittest.TestCase):
    """Scenario: grant_env_exemption 落放行记录 + 重置 + 幂等放行闭环。

    evo-fix-env-exemption-gate-conflict-…（3.2）：豁免生效主源改为 spec 级
    STATE 字段（disposition 为审计镜像）——本组用例同时断言 STATE 字段
    写入/读取镜像一致（``parse_state`` 往返 + ``parse_env_exemptions``）。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))

    def _park(self):
        engine, sm, _ = _mk_engine(self.tmpdir)
        report = _mixed_env_report()
        # 生产时序：停车发生在 judge 裁决 report.json 落盘之后——grant 的
        # STATE 豁免候选从盘上报告读取（场景 id+签名+hash），先落盘再停车
        _write_report(self.tmpdir, "s1", report)
        self.assertTrue(
            engine._verification._handle_env_exemption_handshake("s1", report)
        )
        return engine, sm

    def test_grant_writes_disposition_and_resets(self):
        """grant_env_exemption：DISPOSITION 落库（resolved）+ 计数/旗标/基准清零。"""
        self._park()
        r = execute_adjudication_choice(
            Path(self.tmpdir), "s1", "grant_env_exemption",
            note="失败确属内网依赖不可达", signal_type="inconclusive_loop",
        )
        self.assertTrue(r.get("ok"), f"执行应成功: {r}")
        self.assertTrue(r.get("disposition_id"))
        disps = [d for d in _store_records(self.tmpdir, DISPOSITION)
                 if d.get("spec") == "s1"]
        self.assertEqual(len(disps), 1, "放行记录恰一条")
        rec = disps[0]
        self.assertEqual(rec.get("action_taken"), "grant_env_exemption")
        self.assertEqual(rec.get("result"), "resolved", "resolved 才进放行查询锚点")
        self.assertIn("内网依赖", rec.get("note") or "", "人工审计原文应落库")
        spec = _adjudication_entry(self.tmpdir, "s1")
        self.assertEqual(int(spec.get("_inconclusive_attempts") or 0), 0)
        self.assertFalse(_is_flag_true(spec), "预算隔离旗标应清除")
        self.assertFalse(spec.get("_last_inconclusive_signature"), "签名基准应清")
        self.assertFalse(spec.get("_dispatch_backoff_until"), "退避窗应清")

    def test_grant_writes_state_exemption_field_mirror(self):
        """evo-fix-… 1.1/3.2：grant 写 STATE 豁免字段，读回镜像一致。

        镜像一致性：parse_state 往返后 parse_env_exemptions 读出的条目
        （场景 id / 失败签名 / granted_at / disposition_id 回链）与报告
        场景逐一对应，签名与 ``scenario_fail_signature_body`` 重算同值。
        """
        from core.state_machine import (
            normalize_env_exemption_signature,
            parse_env_exemptions,
            scenario_fail_signature_body,
        )

        report = _mixed_env_report()
        self._park()
        r = execute_adjudication_choice(
            Path(self.tmpdir), "s1", "grant_env_exemption",
            signal_type="inconclusive_loop",
        )
        self.assertTrue(r.get("ok"))
        entry = _adjudication_entry(self.tmpdir, "s1")
        exemptions = parse_env_exemptions(entry)
        self.assertTrue(exemptions, "STATE 豁免字段应已写入且可读回")
        by_sid = {str(e.get("scenario_id")): e for e in exemptions}
        # 报告非 pass 场景全部入豁免（含 blocked-env），pass 场景不入
        expected_sids = {
            str(sc.get("scenario_id")) for sc in report["scenarios"]
            if sc.get("status") not in ("pass", "passed")
        }
        self.assertEqual(set(by_sid), expected_sids)
        for sc in report["scenarios"]:
            sid = str(sc.get("scenario_id") or "")
            if sid not in by_sid:
                continue
            item = by_sid[sid]
            self.assertEqual(
                normalize_env_exemption_signature(item.get("failure_signature") or ""),
                normalize_env_exemption_signature(scenario_fail_signature_body(sc)),
                f"{sid} 落库签名应与场景重算签名同值",
            )
            self.assertTrue(item.get("granted_at"), "时效锚点应落库")
            self.assertEqual(item.get("disposition_id"), r.get("disposition_id"),
                             "豁免应回链 disposition 审计镜像")

    def test_grant_then_reverify_release_with_backlink(self):
        """授予豁免 → 重置重验 → 同结论再命中：握手放行（带回链）不升级。

        evo-fix-… 1.3：放行主通道为 STATE 豁免（anchor=env_exemptions），
        disposition 降为审计镜像——回链 id/action_taken 仍指向 grant 落的
        放行记录。
        """
        engine, sm = self._park()
        r = execute_adjudication_choice(
            Path(self.tmpdir), "s1", "grant_env_exemption",
            signal_type="inconclusive_loop",
        )
        self.assertTrue(r.get("ok"))
        report = _mixed_env_report()
        handled = engine._verification._handle_env_exemption_handshake("s1", report)
        self.assertFalse(handled, "查得有效 STATE 豁免应放行走 verified 链")
        saved = load_report(Path(self.tmpdir), "s1")
        backlink = saved.get("admin_disposition_backlink")
        self.assertIsInstance(backlink, dict, "报告应保留豁免回链")
        self.assertEqual(backlink.get("anchor"), "env_exemptions",
                         "STATE 主放行回链应锚 env_exemptions")
        self.assertEqual(backlink.get("signal_type"), "inconclusive_loop")
        self.assertEqual(backlink.get("result"), "resolved")
        self.assertEqual(backlink.get("id"), r.get("disposition_id"))
        self.assertEqual(backlink.get("action_taken"), "grant_env_exemption")
        self.assertEqual(sm.read_one("s1")["status"], "implemented",
                         "握手只放行不迁移，verified 由调用方推进")

    def test_store_reject_fail_closed_no_reset(self):
        """store 拒写（append 返回 None）：fail-closed 不执行重置。"""
        self._park()
        with mock.patch.object(AdminStore, "append", return_value=None):
            r = execute_adjudication_choice(
                Path(self.tmpdir), "s1", "grant_env_exemption",
                signal_type="inconclusive_loop",
            )
        self.assertFalse(r.get("ok"), "拒写不得报成功")
        self.assertIn("fail-closed", r.get("error") or "")
        self.assertEqual(_store_records(self.tmpdir, DISPOSITION), [],
                         "拒写时不得有放行记录")
        spec = _adjudication_entry(self.tmpdir, "s1")
        self.assertEqual(int(spec.get("_inconclusive_attempts") or 0), 1,
                         "fail-closed 不重置（计数保持）")
        self.assertTrue(_is_flag_true(spec), "fail-closed 不重置（旗标保持）")


def _adjudication_entry(tmpdir, spec):
    """经 admin_actions 同款 parse_state 读条目（验证 STATE.md 落盘往返）。"""
    from core.dashboard.data.state import parse_state

    return parse_state(Path(tmpdir)).get(spec) or {}


# ── 5.2：级一签名一致提前升级 ────────────────────────────────────────────────


class TestLevel1SignatureEscalation(unittest.TestCase):
    """Scenario: 级一 blocked-env 循环的失败签名提前升级与保守缺省。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))

    def test_same_signature_escalates_early(self):
        """同签名第 2 轮（计数未到上限）即升级——环境未变化重验无新信息。"""
        engine, sm, _ = _mk_engine(self.tmpdir, config={"verify_engine": {
            "inconclusive_max_attempts": 5,
            "inconclusive_escalate_attempts": 10,
        }})
        report = _blocked_env_report(sid="s-a")
        handled = engine._verification._handle_env_blocked_inconclusive("s1", report)
        self.assertTrue(handled)
        self.assertEqual([r for r in _store_records(self.tmpdir, SIGNAL)
                          if r.get("signal_type") == "inconclusive_loop"], [],
                         "首轮（基准缺失）不升级")
        self.assertEqual(sm.read_one("s1")["_last_inconclusive_signature"],
                         "s-a:blocked-env|blocked=1", "首轮回写签名基准")
        # 第 2 轮同签名：attempts=2 < max=5，仍提前升级
        handled = engine._verification._handle_env_blocked_inconclusive("s1", report)
        self.assertTrue(handled)
        spec = sm.read_one("s1")
        self.assertEqual(int(spec["_inconclusive_attempts"]), 2)
        self.assertIn("签名与上一轮完全一致", spec.get("error") or "")
        self.assertTrue(int(spec.get("_dispatch_backoff_until") or 0) > 0)
        sigs = [r for r in _store_records(self.tmpdir, SIGNAL)
                if r.get("signal_type") == "inconclusive_loop"]
        self.assertEqual(len(sigs), 1, "签名一致提前升级恰写一条 SIGNAL")

    def test_changed_signature_continues_reverify_until_cap(self):
        """签名变化（环境有变化迹象）继续重验，计数到上限才升级。"""
        engine, sm, _ = _mk_engine(self.tmpdir, config={"verify_engine": {
            "inconclusive_max_attempts": 3,
            "inconclusive_escalate_attempts": 10,
        }})
        for i in range(2):
            engine._verification._handle_env_blocked_inconclusive(
                "s1", _blocked_env_report(sid=f"s-{i}")
            )
        self.assertEqual([r for r in _store_records(self.tmpdir, SIGNAL)
                          if r.get("signal_type") == "inconclusive_loop"], [],
                         "签名变化不提前升级")
        self.assertEqual(int(sm.read_one("s1")["_inconclusive_attempts"]), 2)
        engine._verification._handle_env_blocked_inconclusive(
            "s1", _blocked_env_report(sid="s-final")
        )
        spec = sm.read_one("s1")
        self.assertEqual(int(spec["_inconclusive_attempts"]), 3, "计数到上限升级")
        self.assertIn("已达重验上限", spec.get("error") or "")
        sigs = [r for r in _store_records(self.tmpdir, SIGNAL)
                if r.get("signal_type") == "inconclusive_loop"]
        self.assertEqual(len(sigs), 1)

    def test_default_cap_is_2(self):
        """缺省重验上限 2（2.1：3→2）——首轮重验、次轮升级。"""
        engine, sm, _ = _mk_engine(self.tmpdir)
        engine._verification._handle_env_blocked_inconclusive(
            "s1", _blocked_env_report(sid="s-a")
        )
        self.assertEqual(int(sm.read_one("s1")["_inconclusive_attempts"]), 1,
                         "首轮重验（不升级）")
        self.assertEqual([r for r in _store_records(self.tmpdir, SIGNAL)
                          if r.get("signal_type") == "inconclusive_loop"], [])
        engine._verification._handle_env_blocked_inconclusive(
            "s1", _blocked_env_report(sid="s-b")
        )
        sigs = [r for r in _store_records(self.tmpdir, SIGNAL)
                if r.get("signal_type") == "inconclusive_loop"]
        self.assertEqual(len(sigs), 1, "缺省上限 2：次轮升级")

    def test_failed_assertion_signature_digest_normalized(self):
        """非 blocked-env 失败场景的签名摘要：type + 归一化 actual。"""
        from core.pm_engine.verification.escalation import _inconclusive_fail_signature

        report = {
            "summary": {"total": 2, "passed": 0, "warnings": 0,
                        "failed": 1, "errors": 0, "blocked_env": 1},
            "scenarios": [
                {"scenario_id": "s-f", "status": "failed",
                 "evidence": {"failed_assertions": [
                     {"type": "expect_visible", "actual": "共 12345 条记录"},
                 ]}},
                {"scenario_id": "s-b", "status": "blocked-env"},
            ],
        }
        sig = _inconclusive_fail_signature(None, "s1", report)
        self.assertIn("s-f:expect_visible+", sig)
        self.assertIn("共 N 条记录", sig, "数字应归一化为 N")
        self.assertIn("s-b:blocked-env", sig)
        self.assertTrue(sig.endswith("|blocked=1"), "blocked 计数应附加")
        # 片段排序保证跨轮可比（场景序被重排不影响一致判定）
        self.assertEqual(
            sig, _inconclusive_fail_signature(None, "s1", {
                "summary": report["summary"],
                "scenarios": list(reversed(report["scenarios"])),
            }),
        )


# ── 5.3：judge 预算隔离 ─────────────────────────────────────────────────────


class TestJudgeBudgetIsolation(unittest.TestCase):
    """Scenario: 重验窗口 judge 派发不烧生命周期账，独立计数器到顶停车。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))
        self.engine, self.sm, self.logger = _mk_engine(self.tmpdir, config={
            "verify_engine": {"inconclusive_max_attempts": 2},
        })

    def _entry(self):
        return self.sm.read_one("s1") or {}

    def test_flag_on_gate_uses_independent_counter(self):
        """旗标置位：gate 分流进独立计数器，_judge_rerun_count 不动。"""
        self.sm.update_spec("s1", {"_in_inconclusive_reverify": True})
        gate = self.engine._verification._judge_dispatch_gate
        for expected in (1, 2):
            result = gate("s1")
            self.assertIsNone(result, "未到独立上限且无稳定缓存应放行派发")
            self.assertEqual(int(self._entry().get("_judge_inconclusive_dispatches") or 0),
                             expected)
            self.assertEqual(int(self._entry().get("_judge_rerun_count") or 0), 0,
                             "生命周期账不得被重验轮派发消耗")

    def test_independent_counter_cap_parks_without_freeze(self):
        """独立计数器到顶：停止派发 + 人工告警，不冻结 spec。"""
        self.sm.update_spec("s1", {"_in_inconclusive_reverify": True})
        gate = self.engine._verification._judge_dispatch_gate
        gate("s1")
        gate("s1")
        result = gate("s1")  # count=2 >= cap=2 → 停车
        self.assertIs(result, False, "到顶应停止派发（返回 False 让位）")
        entry = self._entry()
        self.assertEqual(int(entry.get("_judge_inconclusive_dispatches") or 0), 2,
                         "到顶后不再递增")
        self.assertNotEqual(entry.get("status"), "blocked", "不冻结（保持可处置）")
        self.assertFalse(_is_flag_true({"_judge_cap_frozen":
                                        entry.get("_judge_cap_frozen")}),
                         "不得置 judge 硬上限冻结标记")
        escs = [r for r in _store_records(self.tmpdir, ESCALATION)
                if r.get("signal_type") == "inconclusive_loop"]
        self.assertEqual(len(escs), 1, "到顶应发一次人工升级告警")
        # 去重：再次重入不重复告警
        gate("s1")
        escs = [r for r in _store_records(self.tmpdir, ESCALATION)
                if r.get("signal_type") == "inconclusive_loop"]
        self.assertEqual(len(escs), 1, "同 episode 到顶只告警一次")

    def test_flag_off_gate_burns_lifecycle_counter(self):
        """旗标未置：既有语义零变化——gate 照旧烧 _judge_rerun_count。"""
        gate = self.engine._verification._judge_dispatch_gate
        self.assertIsNone(gate("s1"))
        entry = self._entry()
        self.assertEqual(int(entry.get("_judge_rerun_count") or 0), 1)
        self.assertEqual(int(entry.get("_judge_inconclusive_dispatches") or 0), 0,
                         "独立计数器不得被正常轮消耗")

    def test_non_env_conclusion_clears_flag_via_single_helper(self):
        """非全 env 结论路由点经单一助手清旗标（存在才清）。"""
        from core.pm_engine.verification.escalation import (
            _clear_inconclusive_reverify_flag,
        )

        _clear_inconclusive_reverify_flag(self.engine._verification, "s1")
        self.assertFalse(_is_flag_true(self._entry()), "旗标本就为假：无写盘也无异常")
        self.sm.update_spec("s1", {"_in_inconclusive_reverify": True})
        _clear_inconclusive_reverify_flag(self.engine._verification, "s1")
        self.assertFalse(_is_flag_true(self._entry()), "旗标应被清除")

    def test_verified_landing_resets_budget_fields(self):
        """verified 落定清零点：独立计数器归零 + 旗标清除。"""
        self.sm.update_spec("s1", {
            "_in_inconclusive_reverify": True,
            "_judge_inconclusive_dispatches": 2,
            "_judge_rerun_count": 3,
        })
        self.engine._verification._record_verdict_adoption("s1", "verified")
        entry = self._entry()
        self.assertEqual(int(entry.get("_judge_rerun_count") or 0), 0)
        self.assertEqual(int(entry.get("_judge_inconclusive_dispatches") or 0), 0)
        self.assertFalse(_is_flag_true(entry))

    def test_reset_verification_clears_new_fields(self):
        """人工复位清零清单含新字段（计数器/旗标/签名基准/退避窗/告警去重标记）。"""
        from core.pm_engine.verification.escalation import (
            INCONCLUSIVE_PARKING_ERROR_MARKER,
        )

        self.sm.update_spec("s1", {
            "status": "implemented",
            "error": f"连续 2 轮（x）— {INCONCLUSIVE_PARKING_ERROR_MARKER}",
            "_inconclusive_attempts": 2,
            "_in_inconclusive_reverify": True,
            "_judge_inconclusive_dispatches": 1,
            "_last_inconclusive_signature": "s-a:blocked-env|blocked=1",
            "_dispatch_backoff_until": 9999999999,
            "_judge_inconclusive_cap_escalated": True,
        })
        r = reset_verification(Path(self.tmpdir), "s1",
                               signal_type="inconclusive_loop")
        self.assertTrue(r.get("ok"), f"复位应成功: {r}")
        entry = _adjudication_entry(self.tmpdir, "s1")
        self.assertEqual(int(entry.get("_inconclusive_attempts") or 0), 0)
        self.assertEqual(int(entry.get("_judge_inconclusive_dispatches") or 0), 0)
        self.assertFalse(_is_flag_true(entry), "旗标必须清除（防复位后持续分流）")
        self.assertFalse(entry.get("_last_inconclusive_signature"), "过期基准必须清")
        self.assertFalse(entry.get("_dispatch_backoff_until"), "退避窗必须清")
        self.assertFalse(_is_flag_true({"_judge_cap_frozen":
                                        str(entry.get("_judge_inconclusive_cap_escalated"))}),
                         "告警去重标记必须复位（新 episode 可再告警）")


if __name__ == "__main__":
    unittest.main()
