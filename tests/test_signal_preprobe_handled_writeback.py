"""tests/test_signal_preprobe_handled_writeback.py — 信号前置探测与处置终态回写测试。

evo-signal-preprobe-handled-writeback 测试策略：进程内装配 AdminStore +
监视器最小夹具（不唤起真实 Administrator），覆盖 design 声明的四态外加
白名单外行为不变一例：
  1. 探测通过免唤起：handled=true + escalated=true（下一 tick 不重捞）
     + result=resolved 处置留痕
  2. 诉求未满足照常唤起（现有路径不变）
  3. 探测异常 fail-open 照常唤起（R4）
  4. 处置终态回写 handled=true（R5），含 escalate=true 不回写与
     signal_rec=None 跳过两分支
  5. 白名单外信号行为不变（R1）
"""

import pathlib
import shutil
import tempfile
import unittest
from unittest import mock

from core.admin_monitor import PREPROBE_SIGNAL_TYPES, AdminMonitor
from core.admin_store import AdminStore, DISPOSITION, SIGNAL
from core.agent_runner.result_gate import AdminDisposition


class _RecordingLogger:
    """记录型 logger（断言 fail-open 警告内容用，与既有测试同构）。"""

    def __init__(self):
        self.warnings = []
        self.errors = []

    @staticmethod
    def _msg(a):
        return " ".join(str(x) for x in a if not isinstance(x, (dict, list)))

    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        self.warnings.append(self._msg(a))

    def error(self, *a, **k):
        self.errors.append(self._msg(a))


class _MonitorSM:
    """AdminMonitor 测试用最小 StateMachine 替身（非终态，不触发终态守卫）。"""

    def read_one(self, spec):
        return {"status": "implemented"}


def _make_monitor(proot, config=None, logger=None):
    """装配 AdminMonitor 最小夹具：真实 AdminStore + 替身 SM + mock agent_runner。"""
    logger = logger if logger is not None else _RecordingLogger()
    store = AdminStore(proot, logger)
    mon = AdminMonitor(
        config or {},
        _MonitorSM(),
        proot,
        logger,
        store=store,
        agent_runner=mock.MagicMock(),
    )
    return mon, store, logger


def _seed_signal(store, stype, spec="proj", evidence=""):
    """写入一条待摄取 SIGNAL 记录，返回落地记录（含 id）。"""
    return store.append(
        {
            "kind": SIGNAL,
            "signal_type": stype,
            "spec": spec,
            "severity": "major",
            "description": f"请求型信号 {stype}",
            "evidence": evidence or f"项目名={spec}; source=ui-manual",
            "recommended_action": "",
        }
    )


def _make_proj(tmpdir, verify_yaml=None):
    """在临时目录下建最小项目夹具（.fenix/ + 可选 verify.yaml）。"""
    proot = pathlib.Path(tmpdir) / "proj"
    (proot / ".fenix").mkdir(parents=True, exist_ok=True)
    if verify_yaml is not None:
        (proot / ".fenix" / "verify.yaml").write_text(verify_yaml, encoding="utf-8")
    return proot


# 带 regression 段的 verify.yaml（探测通过夹具）
VERIFY_YAML_WITH_REGRESSION = """\
prepare: []
regression:
  cmd: "pytest tests/ -q"
  output: "reports/regression.xml"
"""

# 无 regression 段的 verify.yaml（契约存在但诉求未满足夹具）
VERIFY_YAML_NO_REGRESSION = """\
prepare: []
"""


class _TempProjCase(unittest.TestCase):
    """临时项目夹具基类：每个用例独立 tmpdir，收尾清理。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))


class TestPreprobeSatisfiedNoInvocation(_TempProjCase):
    """Scenario: 探测通过 → handled=true + escalated=true + resolved 留痕，免唤起。"""

    def test_regression_missing_probe_pass_closes_without_invocation(self):
        proot = _make_proj(self.tmpdir, VERIFY_YAML_WITH_REGRESSION)
        mon, store, logger = _make_monitor(proot)
        rec = _seed_signal(store, "verify_regression_missing")
        with mock.patch.object(mon, "_invoke_administrator") as mock_invoke:
            raw = mon._detect_family_explosion()
            # 未唤起 Administrator
            self.assertEqual(mock_invoke.call_count, 0)
        # 未进入摄取信号列表（探测通过即闭环，不作为「已唤起」信号上报）
        self.assertEqual(raw, [])
        # handled=true + escalated=true（escalated 供下一 tick 摄取过滤）
        recs = {r["id"]: r for r in store.read_all()}
        self.assertTrue(recs[rec["id"]].get("handled"))
        self.assertTrue(recs[rec["id"]].get("escalated"))
        # result=resolved 处置留痕，注明探测通过、免唤起
        disps = [r for r in store.read_all() if r.get("kind") == DISPOSITION]
        self.assertEqual(len(disps), 1, f"应恰有 1 条处置留痕: {disps}")
        self.assertEqual(disps[0].get("result"), "resolved")
        self.assertIn("免唤起", disps[0].get("action_taken") or "")
        self.assertIn("探测通过", disps[0].get("action_taken") or "")
        # 不带 admin_run_id（不伪造「在飞 run」）
        self.assertFalse(disps[0].get("admin_run_id"))
        # 下一 tick 不重捞：无新唤起、无重复留痕
        with mock.patch.object(mon, "_invoke_administrator") as mock_invoke:
            self.assertEqual(mon._detect_family_explosion(), [])
            self.assertEqual(mock_invoke.call_count, 0)
        disps2 = [r for r in store.read_all() if r.get("kind") == DISPOSITION]
        self.assertEqual(len(disps2), 1, "下一 tick 不得重复追加留痕")

    def test_contract_missing_probe_pass_closes(self):
        """verify_contract_missing：契约 serve/start 能力已补即免唤起。

        evo-add-scenario-serve-consistency-preflight 2.1 收紧：满足判定从
        「契约可解析」改为「serve 段存在或 commands.start 非占位，且能力可覆盖
        在途场景 kind 需求」——夹具契约须带 serve 段才判满足。
        """
        proot = _make_proj(
            self.tmpdir,
            VERIFY_YAML_WITH_REGRESSION + "serve:\n  kind: static\n  root: dist\n",
        )
        mon, store, _ = _make_monitor(proot)
        rec = _seed_signal(store, "verify_contract_missing")
        with mock.patch.object(mon, "_invoke_administrator") as mock_invoke:
            mon._detect_family_explosion()
            self.assertEqual(mock_invoke.call_count, 0)
        recs = {r["id"]: r for r in store.read_all()}
        self.assertTrue(recs[rec["id"]].get("handled"))

    def test_contract_missing_serveless_still_invokes(self):
        """verify_contract_missing：契约可解析但无 serve 段且 start 占位 → 照常唤起。

        2026-10-10 事故形态（三条在途信号被「可解析即满足」宽松探测错误闭环）
        的回归锁定：能力缺口未补齐不 auto-resolve。
        """
        proot = _make_proj(self.tmpdir, VERIFY_YAML_WITH_REGRESSION)
        mon, store, _ = _make_monitor(proot)
        rec = _seed_signal(store, "verify_contract_missing")
        with mock.patch.object(mon, "_invoke_administrator") as mock_invoke:
            mon._detect_family_explosion()
            self.assertEqual(mock_invoke.call_count, 1, "能力缺口未补应照常唤起")
        recs = {r["id"]: r for r in store.read_all()}
        self.assertFalse(recs[rec["id"]].get("handled"), "不得 pre-probe 闭环")

    def test_artifact_paths_probe_pass_closes(self):
        """build_artifact_paths_missing：产物路径配置非空即免唤起。"""
        proot = _make_proj(self.tmpdir)
        mon, store, _ = _make_monitor(
            proot, config={"worktree": {"build_artifact_paths": ["dist/"]}}
        )
        rec = _seed_signal(store, "build_artifact_paths_missing")
        with mock.patch.object(mon, "_invoke_administrator") as mock_invoke:
            mon._detect_family_explosion()
            self.assertEqual(mock_invoke.call_count, 0)
        recs = {r["id"]: r for r in store.read_all()}
        self.assertTrue(recs[rec["id"]].get("handled"))

    def test_artifact_paths_has_build_artifacts_false_is_adjudicated(self):
        """has_build_artifacts=false（确无产物）亦属已裁决 → 免唤起。"""
        proot = _make_proj(self.tmpdir)
        mon, store, _ = _make_monitor(
            proot, config={"worktree": {"has_build_artifacts": False}}
        )
        rec = _seed_signal(store, "build_artifact_paths_missing")
        with mock.patch.object(mon, "_invoke_administrator") as mock_invoke:
            mon._detect_family_explosion()
            self.assertEqual(mock_invoke.call_count, 0)
        recs = {r["id"]: r for r in store.read_all()}
        self.assertTrue(recs[rec["id"]].get("handled"))


class TestPreprobeUnsatisfiedStillInvokes(_TempProjCase):
    """Scenario: 诉求未满足 → 照常唤起（现有路径不变）。"""

    def test_regression_absent_still_invokes(self):
        """verify.yaml 存在但 regression 段缺失 → 照常唤起。"""
        proot = _make_proj(self.tmpdir, VERIFY_YAML_NO_REGRESSION)
        mon, store, _ = _make_monitor(proot)
        rec = _seed_signal(store, "verify_regression_missing")
        with mock.patch.object(mon, "_invoke_administrator") as mock_invoke:
            raw = mon._detect_family_explosion()
            self.assertEqual(mock_invoke.call_count, 1, "诉求未满足应照常唤起")
        self.assertEqual(len(raw), 1)
        recs = {r["id"]: r for r in store.read_all()}
        self.assertTrue(recs[rec["id"]].get("escalated"), "照常路径应 mark_escalated")
        self.assertFalse(recs[rec["id"]].get("handled"), "未满足不得置 handled")

    def test_verify_yaml_absent_still_invokes(self):
        """契约文件整体缺失 → 照常唤起。"""
        proot = _make_proj(self.tmpdir)
        mon, store, _ = _make_monitor(proot)
        _seed_signal(store, "verify_regression_missing")
        with mock.patch.object(mon, "_invoke_administrator") as mock_invoke:
            mon._detect_family_explosion()
            self.assertEqual(mock_invoke.call_count, 1)

    def test_artifact_paths_unadjudicated_still_invokes(self):
        """config 未裁决（无路径且无 has_build_artifacts=false）→ 照常唤起。"""
        proot = _make_proj(self.tmpdir, VERIFY_YAML_WITH_REGRESSION)
        mon, store, _ = _make_monitor(proot, config={})
        rec = _seed_signal(store, "build_artifact_paths_missing")
        with mock.patch.object(mon, "_invoke_administrator") as mock_invoke:
            mon._detect_family_explosion()
            self.assertEqual(mock_invoke.call_count, 1)
        recs = {r["id"]: r for r in store.read_all()}
        self.assertFalse(recs[rec["id"]].get("handled"))


class TestPreprobeFailOpen(_TempProjCase):
    """Scenario: 探测异常 → fail-open 照常唤起（R4，不静默吞信号）。"""

    def test_probe_exception_falls_open(self):
        proot = _make_proj(self.tmpdir)
        mon, store, logger = _make_monitor(proot)
        rec = _seed_signal(store, "verify_regression_missing")
        with mock.patch.object(
            mon,
            "_preprobe_signal_satisfied",
            side_effect=RuntimeError("probe boom"),
        ):
            with mock.patch.object(mon, "_invoke_administrator") as mock_invoke:
                mon._detect_family_explosion()
                # 探测异常 → 照常唤起
                self.assertEqual(mock_invoke.call_count, 1)
        recs = {r["id"]: r for r in store.read_all()}
        self.assertTrue(
            recs[rec["id"]].get("escalated"), "fail-open 应照常 mark_escalated"
        )
        self.assertFalse(recs[rec["id"]].get("handled"), "探测异常不得置 handled")
        # 留痕：异常路径有 warning 可对账（R6）
        self.assertTrue(
            any("前置探测异常" in w for w in logger.warnings),
            f"应留 fail-open 警告日志: {logger.warnings}",
        )


class TestFinalDispositionWriteback(_TempProjCase):
    """Scenario: 处置 run 落最终 DISPOSITION 后回写信号 handled=true（R5）。"""

    def setUp(self):
        super().setUp()
        self.proot = _make_proj(self.tmpdir)
        self.mon, self.store, self.logger = _make_monitor(self.proot)
        self.rec = _seed_signal(self.store, "verify_regression_missing")
        self.signal = {
            "signal_type": "verify_regression_missing",
            "spec": "proj",
            "severity": "major",
            "description": "请求补写 regression 段",
            "evidence": "项目名=proj",
            "recommended_action": "",
        }

    def _disp(self, result="resolved", escalate=False):
        return AdminDisposition(
            run_id="admin-run-1",
            spec="proj",
            success=not escalate,
            result=result,
            escalate=escalate,
            actions_taken="补写 regression 段",
        )

    def test_final_resolved_writeback_handled(self):
        """非 pending 终态 + escalate=False → 回写 handled=true。"""
        self.mon.agent_runner.run_administrator = mock.MagicMock(
            return_value=self._disp()
        )
        self.mon._invoke_administrator(self.signal, self.rec)
        recs = {r["id"]: r for r in self.store.read_all()}
        self.assertTrue(
            recs[self.rec["id"]].get("handled"),
            "处置终态后应回写信号 handled=true",
        )
        # 终态 DISPOSITION 本身照常落盘
        finals = [
            r
            for r in self.store.read_all()
            if r.get("kind") == DISPOSITION and r.get("result") == "resolved"
        ]
        self.assertEqual(len(finals), 1, "处置结果应照常落盘")

    def test_escalate_true_no_writeback(self):
        """escalate=true（升级人工）不自动回写——人工处置是唯一出路。"""
        self.mon.agent_runner.run_administrator = mock.MagicMock(
            return_value=self._disp(result="failed", escalate=True)
        )
        self.mon._invoke_administrator(self.signal, self.rec)
        recs = {r["id"]: r for r in self.store.read_all()}
        self.assertFalse(
            recs[self.rec["id"]].get("handled"),
            "escalate=true 属升级人工，不得自动回写",
        )

    def test_signal_rec_none_skipped(self):
        """人工显式触发（signal_rec=None）无关联记录 → 跳过回写不抛错。"""
        self.mon.agent_runner.run_administrator = mock.MagicMock(
            return_value=self._disp()
        )
        # 不应抛 AttributeError/KeyError
        self.mon._invoke_administrator(self.signal, None)
        finals = [
            r
            for r in self.store.read_all()
            if r.get("kind") == DISPOSITION and r.get("result") == "resolved"
        ]
        self.assertEqual(len(finals), 1, "处置结果应照常落盘")

    def test_pending_result_no_writeback(self):
        """result=pending（非终态）不回写。"""
        self.mon.agent_runner.run_administrator = mock.MagicMock(
            return_value=self._disp(result="pending")
        )
        self.mon._invoke_administrator(self.signal, self.rec)
        recs = {r["id"]: r for r in self.store.read_all()}
        self.assertFalse(recs[self.rec["id"]].get("handled"))

    def test_writeback_failure_does_not_block_disposition(self):
        """回写异常仅记警告，不阻塞处置结果落盘。"""
        self.mon.agent_runner.run_administrator = mock.MagicMock(
            return_value=self._disp()
        )
        with mock.patch.object(
            self.store, "mark_signal_handled", side_effect=OSError("disk full")
        ):
            # 不应抛出
            self.mon._invoke_administrator(self.signal, self.rec)
        finals = [
            r
            for r in self.store.read_all()
            if r.get("kind") == DISPOSITION and r.get("result") == "resolved"
        ]
        self.assertEqual(len(finals), 1, "处置结果不得因回写失败丢失")
        self.assertTrue(
            any("回写" in w for w in self.logger.warnings),
            f"回写失败应留警告日志: {self.logger.warnings}",
        )


class TestWhitelistBoundary(_TempProjCase):
    """Scenario: 白名单外信号行为完全不变（R1）。"""

    def test_non_whitelisted_type_skips_probe_and_invokes(self):
        """白名单外类型即使诉求事实已满足，也照常唤起、不置 handled。"""
        proot = _make_proj(self.tmpdir, VERIFY_YAML_WITH_REGRESSION)
        mon, store, _ = _make_monitor(proot)
        # verify_uniform_failure 属 STORED_SIGNAL_TYPES 但不在前置探测白名单
        rec = _seed_signal(store, "verify_uniform_failure", spec="s1")
        with mock.patch.object(mon, "_preprobe_signal_satisfied") as mock_probe:
            with mock.patch.object(mon, "_invoke_administrator") as mock_invoke:
                raw = mon._detect_family_explosion()
                self.assertEqual(mock_invoke.call_count, 1, "白名单外应照常唤起")
                # 白名单外不得触发探测
                mock_probe.assert_not_called()
        self.assertEqual(len(raw), 1)
        recs = {r["id"]: r for r in store.read_all()}
        self.assertFalse(recs[rec["id"]].get("handled"))

    def test_whitelist_members(self):
        """白名单恰含 design 收录的三种可探测类型。"""
        self.assertEqual(
            set(PREPROBE_SIGNAL_TYPES),
            {
                "verify_regression_missing",
                "verify_contract_missing",
                "build_artifact_paths_missing",
            },
        )


if __name__ == "__main__":
    unittest.main()
