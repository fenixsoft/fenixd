"""tests/test_admin_direct_exclusive_choice_guard.py — 直派通道人类专属裁决越界拦截。

evo-block-admin-direct-exclusive-choice 2.1/2.2（含 1.4 人工通道零改动断言）：
  1. 执行机器守卫（execute_choice_for_disposition 入口）：7 项人类专属
     choice 全数拒绝（ok=false + skipped=true + error 含「人类拍板面专属」）
     且 execute_adjudication_choice 未被调用、ERROR 留痕；
     is_human_exclusive_choice strip 归一化成员判断；
     非排除项（revise_scenario_reverify）正常放行到执行器。
  2. 人工通道零改动：execute_adjudication_choice（alert-resolve 同一入口）
     对 grant_env_exemption 照常执行成功，STATE `_env_exemptions` 落盘。
  3. 直派消费侧 handoff（admin_monitor._invoke_administrator 全流程）：
     拒绝后 AdminDisposition.handoff_reason 含「人类拍板面专属」、信号
     不回写 handled/resolved（handled=False + result=failed 留痕）、final
     落账 error 文本含守卫文案、STATE `_env_exemptions` 未被写入。

夹具与 test_global_signal_choice_guard 同构收编（_RecordingLogger/_MonitorSM/
_make_monitor/_seed_signal）。
"""
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from core.admin_choice_exec import execute_choice_for_disposition
from core.admin_monitor import AdminMonitor
from core.admin_store import AdminStore, DISPOSITION, SIGNAL
from core.agent_runner.result_gate import AdminDisposition
from core.dashboard.data.adjudication_choices import (
    ADMIN_CHAIN_EXCLUDED_CHOICE_IDS,
    is_human_exclusive_choice,
)
from core.dashboard.data.admin_actions import execute_adjudication_choice


# ── 夹具（与 test_global_signal_choice_guard 同构收编）──────────────────


def _write_state(proot: pathlib.Path, specs: dict) -> None:
    lines = ["# Fenix Project State", "", "## Specs", ""]
    for name, fields in specs.items():
        lines.append(f"### {name}")
        for k, v in fields.items():
            lines.append(f"- {k}: {v}")
        lines.append("")
    (proot / ".fenix" / "STATE.md").write_text("\n".join(lines), encoding="utf-8")


def _state_fields(status, error="null"):
    return {
        "status": status,
        "priority": 2,
        "created": "2026-01-01T00:00:00+00:00",
        "updated": "2026-01-02T00:00:00+00:00",
        "error": error,
        "depends_on": "null",
    }


def _make_proot(tmpdir) -> pathlib.Path:
    proot = pathlib.Path(tmpdir) / "proj-guard"
    (proot / ".fenix").mkdir(parents=True)
    _write_state(proot, {"spec-frozen": _state_fields("blocked", "placeholder")})
    return proot


def _freeze_review_incomplete(proot, spec="spec-frozen"):
    """spec-review-incomplete 冻结形态（真 frozen 停车夹具）。"""
    from core.state_machine import StateMachine, project_state_logger

    sm = StateMachine(proot / ".fenix" / "STATE.md", project_state_logger(proot))
    sm.update_spec(spec, {
        "frozen": True,
        "status": "blocked",
        "error": "spec-review-incomplete: 评审尝试已达上限",
    })


class _RecordingLogger:
    """记录型 logger（守卫 ERROR 留痕断言用）。"""

    def __init__(self):
        self.infos = []
        self.warnings = []
        self.errors = []

    @staticmethod
    def _msg(a):
        return " ".join(str(x) for x in a if not isinstance(x, (dict, list)))

    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        self.infos.append(self._msg(a))

    def warning(self, *a, **k):
        self.warnings.append(self._msg(a))

    def error(self, *a, **k):
        self.errors.append(self._msg(a))


class _MonitorSM:
    """AdminMonitor 测试用最小 StateMachine 替身。"""

    def read_one(self, spec):
        return {"status": "implemented"}


def _make_monitor(proot):
    logger = _RecordingLogger()
    store = AdminStore(proot, logger)
    mon = AdminMonitor(
        {}, _MonitorSM(), proot, logger,
        store=store, agent_runner=mock.MagicMock(),
    )
    return mon, store, logger


def _seed_signal(store, stype, spec=None):
    """写入一条待处置 SIGNAL 记录，返回落地记录（含 id）。"""
    return store.append({
        "kind": SIGNAL,
        "signal_type": stype,
        "spec": spec,
        "severity": "critical",
        "description": "daemon ERROR 指纹 10 分钟窗口复现",
        "evidence": "fp=eb0afd742714; window=10m",
        "recommended_action": "",
    })


class _TempProjCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))


def _forbidden_executor(*a, **k):
    """执行器哨兵：守卫 MUST NOT 触达 execute_adjudication_choice。"""
    raise AssertionError("execute_adjudication_choice 不应被调用（守卫前置拦截）")


# ── 1.1 单源判别助手 ─────────────────────────────────────────────────────


class TestHumanExclusivePredicate(unittest.TestCase):
    """is_human_exclusive_choice：strip 归一化成员判断。"""

    def test_all_excluded_ids_hit(self):
        for cid in ADMIN_CHAIN_EXCLUDED_CHOICE_IDS:
            self.assertTrue(is_human_exclusive_choice(cid), cid)

    def test_strip_normalization(self):
        self.assertTrue(is_human_exclusive_choice(" grant_env_exemption\n"))
        self.assertTrue(is_human_exclusive_choice("abandon  "))

    def test_empty_and_unknown_miss(self):
        self.assertFalse(is_human_exclusive_choice(""))
        self.assertFalse(is_human_exclusive_choice(None))
        self.assertFalse(is_human_exclusive_choice("revise_scenario_reverify"))
        self.assertFalse(is_human_exclusive_choice("retry_review"))


# ── 2.1 执行机器守卫矩阵 ─────────────────────────────────────────────────


class TestExecMachineGuard(_TempProjCase):
    """execute_choice_for_disposition 入口守卫：agent 通道 × 人类专属 choice。"""

    def test_all_excluded_choices_rejected_without_executor(self):
        """7 项人类专属 choice 全数拒绝：ok=false + skipped=true + error 含
        「人类拍板面专属」，执行器零触达，ERROR 留痕。"""
        proot = _make_proot(self.tmpdir)
        for cid in sorted(ADMIN_CHAIN_EXCLUDED_CHOICE_IDS):
            logger = _RecordingLogger()
            disp = AdminDisposition(
                run_id=f"admin-run-{cid}", spec="spec-frozen", success=True,
                result="resolved", summary="越界推荐", choice_id=cid,
            )
            with mock.patch(
                "core.dashboard.data.admin_actions.execute_adjudication_choice",
                side_effect=_forbidden_executor,
            ):
                outcome = execute_choice_for_disposition(
                    str(proot),
                    {"signal_type": "inconclusive_loop", "spec": "spec-frozen"},
                    disp, logger,
                )
            self.assertIsNotNone(outcome, cid)
            self.assertFalse(outcome["ok"], cid)
            self.assertTrue(outcome.get("skipped"), cid)
            self.assertEqual(outcome.get("action"), cid)
            self.assertEqual(outcome.get("steps"), [])
            self.assertIn("人类拍板面专属", outcome.get("error") or "")
            self.assertIn(cid, outcome.get("error") or "")
            self.assertIn("agent 通道拒绝执行", outcome.get("error") or "")
            # ERROR 留痕可检索（与链路径同前缀 grep 命中）
            self.assertTrue(
                any("人类拍板面专属" in e and cid in e for e in logger.errors),
                f"应有守卫 ERROR 留痕: {logger.errors}",
            )

    def test_non_excluded_choice_passes_through_to_executor(self):
        """非排除项（revise_scenario_reverify）带载荷正常放行执行器。"""
        proot = _make_proot(self.tmpdir)
        _freeze_review_incomplete(proot)
        logger = _RecordingLogger()
        captured = {}

        def fake_executor(proot, spec, cid, note="", signal_type=""):
            captured.update({"choice_id": cid, "spec": spec})
            return {"ok": True, "choice_id": cid, "action": cid,
                    "steps": [], "error": None}

        disp = AdminDisposition(
            run_id="admin-run-ok", spec="spec-frozen", success=True,
            result="resolved", summary="场景修订",
            choice_id="revise_scenario_reverify",
            choice_payload=(
                '{"scenarios": [{"id": "s1", "name": "修订后场景", "steps": []}], '
                '"reason": "原场景定义不可行", "fixture_files": []}'
            ),
        )
        with mock.patch(
            "core.dashboard.data.admin_actions.execute_adjudication_choice",
            side_effect=fake_executor,
        ):
            outcome = execute_choice_for_disposition(
                str(proot),
                {"signal_type": "inconclusive_loop", "spec": "spec-frozen"},
                disp, logger,
            )
        self.assertTrue(outcome["ok"], outcome.get("error"))
        self.assertFalse(outcome.get("skipped"))
        self.assertEqual(captured.get("choice_id"), "revise_scenario_reverify")
        self.assertEqual(captured.get("spec"), "spec-frozen")


# ── 1.4 人工通道零改动 ───────────────────────────────────────────────────


class TestHumanChannelUnaffected(_TempProjCase):
    """人工 alert-resolve 入口（execute_adjudication_choice 直调）人类拍板
    放行语义保留：grant_env_exemption 照常执行成功。"""

    def test_human_path_executes_grant_env_exemption(self):
        proot = _make_proot(self.tmpdir)
        _freeze_review_incomplete(proot)
        r = execute_adjudication_choice(
            str(proot), "spec-frozen", "grant_env_exemption",
            note="人工授予 env 豁免：失败确属环境且不可修复",
            signal_type="inconclusive_loop",
        )
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r.get("action"), "grant_env_exemption")
        # 放行记录 + STATE 豁免字段双落盘（豁免生效主源，人工语义完整）
        state_text = (proot / ".fenix" / "STATE.md").read_text(encoding="utf-8")
        self.assertIn("_env_exemptions", state_text)
        store_recs = AdminStore(proot).read_all()
        grants = [x for x in store_recs
                  if x.get("kind") == DISPOSITION
                  and x.get("action_taken") == "grant_env_exemption"]
        self.assertEqual(len(grants), 1)
        self.assertEqual(grants[0].get("result"), "resolved")


# ── 2.1/2.2 直派消费侧 handoff ───────────────────────────────────────────


class TestDirectDispatchHandoff(_TempProjCase):
    """admin_monitor 直派全流程：守卫拒绝 → handoff_reason 留痕 + 信号不闭环
    + final 落账 error 覆盖守卫文案 + STATE `_env_exemptions` 零写入。"""

    def _run_disposition(self, signal, disp, executor_side_effect=_forbidden_executor):
        proot = _make_proot(self.tmpdir)
        mon, store, logger = _make_monitor(proot)
        rec = _seed_signal(store, signal["signal_type"], spec=signal.get("spec"))
        mon.agent_runner.run_administrator = mock.MagicMock(return_value=disp)
        with mock.patch(
            "core.dashboard.data.admin_actions.execute_adjudication_choice",
            side_effect=executor_side_effect,
        ):
            mon._invoke_administrator(signal, rec)
        return proot, store, logger, rec, disp

    def test_grant_env_exemption_rejected_handoff_keeps_signal_pending(self):
        """2026-11-12 事故形态回放：直派 × grant_env_exemption → 拒绝 + handoff。"""
        signal = {
            "signal_type": "daemon_errors", "spec": "spec-frozen",
            "severity": "critical", "description": "daemon ERROR 复现",
        }
        disp = AdminDisposition(
            run_id="admin-run-x1", spec="spec-frozen", success=True,
            result="resolved", summary="建议豁免重验",
            actions_taken="授予 env 豁免", choice_id="grant_env_exemption",
        )
        proot, store, logger, rec, disp = self._run_disposition(signal, disp)
        # 2.2：disposition 记 handoff_reason（链路径同名语义），含守卫文案
        self.assertIn("人类拍板面专属", disp.handoff_reason)
        self.assertIn("grant_env_exemption", disp.handoff_reason)
        # 信号不回写 handled/resolved：留痕但不闭环
        sig = {r["id"]: r for r in store.read_all()}[rec["id"]]
        self.assertFalse(sig.get("handled"), "信号 MUST NOT 被闭环")
        self.assertEqual(sig.get("result"), "failed")
        self.assertEqual(sig.get("action_taken"), "grant_env_exemption")
        # 2.2：final 落账 error 文本含守卫文案（fail-closed 通道天然覆盖，
        # append_admin_final schema 不扩字段）
        disps = [r for r in store.read_all() if r.get("kind") == DISPOSITION]
        finals = [r for r in disps if r.get("admin_run_id") == "admin-run-x1"]
        self.assertEqual(len(finals), 1)
        self.assertIn("人类拍板面专属", finals[0].get("error") or "")
        # 逐动作小步落账不落事件（skipped 形态不落，无 run_id 审计事件）
        steps = [r for r in disps if not r.get("admin_run_id")]
        self.assertEqual(steps, [])
        # 2.2：STATE `_env_exemptions` 未被写入（越界豁免零生效面）
        state_text = (proot / ".fenix" / "STATE.md").read_text(encoding="utf-8")
        self.assertNotIn("_env_exemptions", state_text)
        # ERROR 留痕（守卫 + 直派 handoff 双条可检索）
        self.assertTrue(
            any("人类拍板面专属" in e for e in logger.errors),
            f"应有 ERROR 留痕: {logger.errors}",
        )
        self.assertTrue(
            any("handoff" in e and "grant_env_exemption" in e for e in logger.errors),
            f"应有直派 handoff ERROR 留痕: {logger.errors}",
        )

    def test_abandon_rejected_same_shape(self):
        """abandon（spec 终态裁决）同形态拒绝 + handoff，信号不闭环。"""
        signal = {
            "signal_type": "daemon_errors", "spec": "spec-frozen",
            "severity": "critical", "description": "daemon ERROR 复现",
        }
        disp = AdminDisposition(
            run_id="admin-run-x2", spec="spec-frozen", success=True,
            result="resolved", summary="建议弃单",
            choice_id="abandon",
        )
        proot, store, logger, rec, disp = self._run_disposition(signal, disp)
        self.assertIn("人类拍板面专属", disp.handoff_reason)
        sig = {r["id"]: r for r in store.read_all()}[rec["id"]]
        self.assertFalse(sig.get("handled"))
        self.assertEqual(sig.get("result"), "failed")
        state_text = (proot / ".fenix" / "STATE.md").read_text(encoding="utf-8")
        self.assertNotIn("_env_exemptions", state_text)

    def test_non_excluded_choice_consumption_still_closes(self):
        """对照：非排除项（ack_self_heal）直派消费照常闭环（守卫不误伤）。"""
        signal = {
            "signal_type": "daemon_errors", "spec": None,
            "severity": "critical", "description": "daemon ERROR 复现",
        }
        disp = AdminDisposition(
            run_id="admin-run-x3", spec="global", success=True,
            result="resolved", summary="确认自愈，继续观察",
            actions_taken="瞬时错误已恢复", choice_id="ack_self_heal",
        )

        def ok_executor(*a, **k):
            return {"ok": True, "choice_id": "ack_self_heal",
                    "action": "ack_self_heal", "steps": [], "error": None}

        proot, store, logger, rec, disp = self._run_disposition(
            signal, disp, executor_side_effect=ok_executor,
        )
        sig = {r["id"]: r for r in store.read_all()}[rec["id"]]
        self.assertTrue(sig.get("handled"), "非排除项收口成功应闭环")
        self.assertEqual(sig.get("result"), "resolved")


if __name__ == "__main__":
    unittest.main()
