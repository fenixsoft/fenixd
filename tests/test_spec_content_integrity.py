"""add-spec-content-integrity-gate 能力测试。

覆盖 spec 全部 Scenario（spec.md 三 Requirement）：
- 判定函数各形态：不存在/空目录/只有无关文件/有 tasks/有 proposal/只有 specs
  子目录/读目录 IO 异常保守放行
- 闸门命中冻结：blocked + spec_content_missing 告警 + 不启动 run + 回滚队列
- 含实质内容正常派发：校验通过进入 implementing
- 已冻结幂等：已是 blocked 不重复告警但仍拒绝重派
- 告警生命周期闭环：spec_content_missing 已注册到 _SIGNAL_CONDITIONS
  （spec 补内容解冻后自动 resolve）
- 冻结须带结构化 frozen 标记（scheduling-showcase 夹具回归）：缺标记时
  admin_monitor 的 blocked_stuck 豁免三条件全不命中 → 冻结后每 60 分钟自动
  召唤一次 Administrator agent run（实测 run 产物 309KB/348KB，纯 token 浪费）
"""

import json
import logging
import shutil
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.admin_monitor import AdminMonitor
from core.admin_store import AdminStore, ESCALATION
from core.alert_lifecycle import (
    _SIGNAL_CONDITIONS,
    CONDITION_SPEC_DELIVERED_ADJUDICATED,
    CONDITION_SPEC_TERMINAL_OR_UNBLOCKED,
    evaluate_alert,
)
from core.state_machine import StateMachine
from core.pm_engine.spec_integrity import (
    GHOST_ENTRY_FRESHNESS_MINUTES,
    GHOST_RECLAIM_LEDGER_FILENAME,
    GHOST_RECLAIM_LEDGER_KIND,
    GHOST_RECLAIM_SIGNAL_TYPE,
    git_path_has_commits,
    ghost_reclaim_ledger_path,
    spec_has_content,
    SpecIntegrityGate,
)


def _mk_engine(project_root, logger, config=None):
    from core.pm_engine import PMEngine
    from helpers import disable_escalation_chain

    disable_escalation_chain(project_root)
    sm = StateMachine(project_root / ".fenix" / "STATE.md", logger)
    engine = PMEngine(sm, MagicMock(), config or {}, project_root, logger)
    engine.handle_event = MagicMock()
    return engine, sm


def _mk_spec_dir(project_root: Path, name: str, files: list) -> Path:
    """构造 spec/changes/<name>/ 目录并按 files 清单创建内容文件。"""
    d = project_root / "spec" / "changes" / name
    d.mkdir(parents=True, exist_ok=True)
    for f in files:
        p = d / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# placeholder\n", encoding="utf-8")
    return d


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()
        self.engine, self.sm = _mk_engine(self.project_root, self.logger)
        self.engine._enqueue = MagicMock()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _alerts(self, signal_type: str, spec: str) -> list:
        return [a for a in AdminStore(self.project_root, self.logger).read_all()
                if a.get("signal_type") == signal_type and a.get("spec") == spec]


class TestSpecHasContent(unittest.TestCase):
    """1.1：spec_has_content 各形态"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_dir_not_exist_returns_false(self):
        self.assertFalse(spec_has_content(self.project_root, "no-such-spec"))

    def test_empty_dir_returns_false(self):
        _mk_spec_dir(self.project_root, "empty-spec", [])
        self.assertFalse(spec_has_content(self.project_root, "empty-spec"))

    def test_unrelated_files_only_returns_false(self):
        _mk_spec_dir(self.project_root, "noise-spec", [".DS_Store", "run.log"])
        self.assertFalse(spec_has_content(self.project_root, "noise-spec"))

    def test_has_tasks_md_returns_true(self):
        _mk_spec_dir(self.project_root, "ok-spec", ["tasks.md"])
        self.assertTrue(spec_has_content(self.project_root, "ok-spec"))

    def test_has_proposal_md_returns_true(self):
        _mk_spec_dir(self.project_root, "draft-spec", ["proposal.md"])
        self.assertTrue(spec_has_content(self.project_root, "draft-spec"))

    def test_has_design_md_returns_true(self):
        _mk_spec_dir(self.project_root, "design-only-spec", ["design.md"])
        self.assertTrue(spec_has_content(self.project_root, "design-only-spec"))

    def test_only_specs_subdir_md_returns_true(self):
        _mk_spec_dir(self.project_root, "specs-only-spec",
                     ["specs/some-cap/spec.md"])
        self.assertTrue(spec_has_content(self.project_root, "specs-only-spec"))

    def test_specs_subdir_no_md_returns_false(self):
        # specs/ 存在但无 *.md（只有无关文件）→ 空判定
        _mk_spec_dir(self.project_root, "specs-noise-spec", ["specs/note.txt"])
        self.assertFalse(spec_has_content(self.project_root, "specs-noise-spec"))

    def test_specs_nested_md_returns_true(self):
        # specs/ 多级嵌套 *.md（rglob **）兜底
        _mk_spec_dir(self.project_root, "nested-spec",
                     ["specs/a/b/c/spec.md"])
        self.assertTrue(spec_has_content(self.project_root, "nested-spec"))

    def test_io_error_conservative_pass(self):
        _mk_spec_dir(self.project_root, "perm-spec", ["tasks.md"])
        with patch("core.pm_engine.spec_integrity.Path.is_dir",
                   side_effect=PermissionError("denied")):
            # IO 异常保守放行（True），不误伤
            self.assertTrue(spec_has_content(self.project_root, "perm-spec"))


class TestGateFreeze(_Base):
    """2.1：闸门命中冻结处置"""

    def test_gate_hit_blocks_and_alerts_not_start_run(self):
        _mk_spec_dir(self.project_root, "empty-spec", [])
        self.sm.add_spec("empty-spec", {"priority": 5})
        self.sm.transition("empty-spec", "ready")

        self.assertTrue(self.engine._check_spec_content_missing("empty-spec"))

        entry = self.sm.read_one("empty-spec")
        self.assertEqual(entry["status"], "blocked")
        self.assertIn("SPEC 内容缺失", entry["error"])
        self.assertIn("empty-spec", entry["error"])
        alerts = self._alerts("spec_content_missing", "empty-spec")
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["kind"], ESCALATION)
        self.assertEqual(alerts[0]["severity"], "major")
        self.assertIn("empty-spec", alerts[0]["description"])

    def test_gate_pass_does_not_block(self):
        _mk_spec_dir(self.project_root, "ok-spec", ["tasks.md"])
        self.sm.add_spec("ok-spec", {"priority": 5})
        self.sm.transition("ok-spec", "ready")

        self.assertFalse(self.engine._check_spec_content_missing("ok-spec"))
        self.assertEqual(self.sm.read_one("ok-spec")["status"], "ready")
        self.assertEqual(len(self._alerts("spec_content_missing", "ok-spec")), 0)

    def test_already_blocked_idempotent_no_duplicate_alert(self):
        _mk_spec_dir(self.project_root, "empty-spec", [])
        self.sm.add_spec("empty-spec", {"priority": 5})
        self.sm.transition("empty-spec", "ready")
        self.engine._check_spec_content_missing("empty-spec")
        self.assertEqual(len(self._alerts("spec_content_missing", "empty-spec")), 1)

        # 再次评估（已是 blocked）：幂等 True，不重复告警
        self.assertTrue(self.engine._check_spec_content_missing("empty-spec"))
        self.assertEqual(
            len(self._alerts("spec_content_missing", "empty-spec")), 1)

    def test_gate_hit_then_content_added_passes(self):
        # 补内容后闸门放行（spec 解冻由恢复巡检处理，此处只验判定）
        d = _mk_spec_dir(self.project_root, "empty-spec", [])
        self.assertTrue(self.engine._spec_integrity.check_spec_content_missing("empty-spec"))
        (d / "tasks.md").write_text("# Tasks\n", encoding="utf-8")
        self.assertFalse(self.engine._spec_integrity.check_spec_content_missing("empty-spec"))


class TestGateFreezeFrozenFlag(_Base):
    """2.2：闸门冻结须带结构化 frozen 标记（scheduling-showcase 夹具回归）。

    回归背景：闸门此前只写 {status: blocked, error: SPEC 内容缺失…}，而
    admin_monitor._detect_blocked_stuck 的豁免三条件（frozen 字段 / error 前缀
    'frozen:' / error 含「用户指令」）无一命中 —— 冻结满 60 分钟（默认
    escalation_cooldown_minutes）即自动召唤一次 Administrator agent run。
    夹具实证：.fenix/runs/admin-c-sched-set-1789106554.jsonl 309KB、
    admin-c-sched-clear-1789199472.jsonl 348KB 两次纯浪费唤起。

    同层先例：env 阻塞冻结（verification.py）同样写 frozen: True + 自有文案。
    """

    def _freeze_via_gate(self, name="empty-spec") -> dict:
        _mk_spec_dir(self.project_root, name, [])
        self.sm.add_spec(name, {"priority": 5})
        self.sm.transition(name, "ready")
        self.assertTrue(self.engine._check_spec_content_missing(name))
        return self.sm.read_one(name)

    def test_gate_hit_sets_frozen_flag(self):
        """闸门命中写结构化 frozen 标记（否则 admin 豁免不生效）。"""
        entry = self._freeze_via_gate()
        self.assertIs(entry.get("frozen"), True,
                      "闸门冻结必须写 frozen: True —— 否则 admin_monitor 的 "
                      "blocked_stuck 豁免三条件全不命中，每 60 分钟空探一次")
        self.assertEqual(entry["status"], "blocked")
        self.assertIn("SPEC 内容缺失", entry["error"])

    def test_gate_frozen_spec_exempt_from_blocked_stuck(self):
        """端到端意图：闸门冻结的 entry 超阈值也不再产生 blocked_stuck 信号。"""
        entry = dict(self._freeze_via_gate())
        # 回拨 updated 至阈值外（阈值 = max(cooldown, 15) 分钟）
        entry["updated"] = (
            datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()

        mon = AdminMonitor.__new__(AdminMonitor)
        mon.admin_cfg = {"escalation_cooldown_minutes": 15}
        mon.logger = MagicMock()

        signals = mon._detect_blocked_stuck({"empty-spec": entry}, time.time())
        self.assertEqual(
            [s for s in signals if s["spec"] == "empty-spec"], [],
            "闸门冻结的 spec 不得触发 blocked_stuck（自动召唤 Administrator 的根因）",
        )

    def test_gate_freeze_strips_automatic_status_rewrite(self):
        """冻结保护生效：自动链路对 status 的改写被剥离，冻结态不被掀翻。"""
        self._freeze_via_gate()
        self.sm.update_spec("empty-spec", {"status": "ready"})
        entry = self.sm.read_one("empty-spec")
        self.assertEqual(entry["status"], "blocked")
        self.assertIs(entry.get("frozen"), True)

    def test_unfreeze_restores_ready(self):
        """人工解冻是唯一出路：frozen 清空、状态复位 ready（告警闭环通道）。

        status 由调用方给出（与真实调用点同形：dashboard/engine 走
        ``parse_orig_status``，无「原状态」记录时回退 ready —— 与 env 阻塞
        冻结同款，故闸门 error 无需另立「原状态」文本契约）。
        """
        self._freeze_via_gate()
        self.sm.unfreeze_spec("empty-spec", status="ready")
        entry = self.sm.read_one("empty-spec")
        self.assertFalse(entry.get("frozen"))
        self.assertEqual(entry["status"], "ready")
        self.assertIsNone(entry["error"])


class TestDispatchGate(unittest.TestCase):
    """2.3/2.4：派发前闸门接入（implementer / fast-track 双分支）"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()
        self.engine, self.sm = _mk_engine(self.project_root, self.logger)
        # 注意：不用 mock _enqueue，使用真实入队以触发 _process_queue

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _enqueue_and_process(self, spec_name: str, agent_type: str):
        self.engine._enqueue(spec_name, agent_type)
        self.engine._process_queue()

    def _alerts(self, signal_type: str, spec: str) -> list:
        return [a for a in AdminStore(self.project_root, self.logger).read_all()
                if a.get("signal_type") == signal_type and a.get("spec") == spec]

    def test_implementer_empty_spec_not_dispatched(self):
        _mk_spec_dir(self.project_root, "empty-spec", [])
        self.sm.add_spec("empty-spec", {"priority": 5})
        self.sm.transition("empty-spec", "ready")
        # 打桩：断言 run 绝不启动
        self.engine._run_agent_worker = MagicMock()

        self._enqueue_and_process("empty-spec", "implementer")

        self.engine._run_agent_worker.assert_not_called()
        entry = self.sm.read_one("empty-spec")
        self.assertEqual(entry["status"], "blocked")
        self.assertEqual(len(self._alerts("spec_content_missing", "empty-spec")), 1)

    def test_implementer_content_spec_dispatched(self):
        _mk_spec_dir(self.project_root, "ok-spec", ["tasks.md"])
        self.sm.add_spec("ok-spec", {"priority": 5})
        self.sm.transition("ok-spec", "ready")
        # 后续 worker 内部会启动线程调用真实逻辑；打桩以同步断言
        self.engine._run_agent_worker = MagicMock()

        self._enqueue_and_process("ok-spec", "implementer")

        self.engine._run_agent_worker.assert_called_once()
        self.assertEqual(self.sm.read_one("ok-spec")["status"], "implementing")

    def test_fast_track_empty_spec_not_dispatched(self):
        _mk_spec_dir(self.project_root, "empty-spec", [])
        self.sm.add_spec("empty-spec", {"priority": 5})
        self.sm.transition("empty-spec", "ready")
        self.engine._run_agent_worker = MagicMock()

        self._enqueue_and_process("empty-spec", "fast-track")

        self.engine._run_agent_worker.assert_not_called()
        self.assertEqual(self.sm.read_one("empty-spec")["status"], "blocked")
        self.assertEqual(len(self._alerts("spec_content_missing", "empty-spec")), 1)

    def test_fast_track_content_spec_dispatched(self):
        _mk_spec_dir(self.project_root, "ok-spec", ["proposal.md"])
        self.sm.add_spec("ok-spec", {"priority": 5})
        self.sm.transition("ok-spec", "ready")
        self.engine._run_agent_worker = MagicMock()

        self._enqueue_and_process("ok-spec", "fast-track")

        self.engine._run_agent_worker.assert_called_once()
        self.assertEqual(self.sm.read_one("ok-spec")["status"], "implementing")

    def test_missing_spec_never_touches_budget(self):
        # 空 spec 被内容闸门拦截，预算计数不被消耗（零 run 启动）
        _mk_spec_dir(self.project_root, "empty-spec", [])
        self.sm.add_spec("empty-spec", {"priority": 5})
        self.sm.transition("empty-spec", "ready")
        self.engine._run_agent_worker = MagicMock()

        self._enqueue_and_process("empty-spec", "implementer")

        used = self.engine._impl_run_budget_used("empty-spec")
        self.assertEqual(used, 0)


class TestAlertLifecycleClosedLoop(unittest.TestCase):
    """3.1：spec_content_missing 接入告警生命周期闭环"""

    def test_signal_condition_registered(self):
        self.assertEqual(
            _SIGNAL_CONDITIONS.get("spec_content_missing"),
            CONDITION_SPEC_TERMINAL_OR_UNBLOCKED,
        )

    def test_trigger_attached_on_alert(self):
        import tempfile
        import shutil
        tmpdir = tempfile.mkdtemp()
        try:
            project_root = Path(tmpdir)
            (project_root / ".fenix").mkdir(parents=True, exist_ok=True)
            logger = MagicMock()
            engine, sm = _mk_engine(project_root, logger)
            _mk_spec_dir(project_root, "empty-spec", [])
            sm.add_spec("empty-spec", {"priority": 5})
            sm.transition("empty-spec", "ready")
            engine._check_spec_content_missing("empty-spec")

            alerts = [a for a in AdminStore(project_root, logger).read_all()
                      if a.get("signal_type") == "spec_content_missing"]
            self.assertEqual(len(alerts), 1)
            trigger = alerts[0].get("trigger")
            self.assertIsNotNone(trigger)
            self.assertEqual(trigger["condition"], CONDITION_SPEC_TERMINAL_OR_UNBLOCKED)
            self.assertEqual(trigger["spec"], "empty-spec")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════
# alert-noise-governance：闸门源头分类（1.1/1.2/1.3）、生命周期闭环（1.4）
# 与 frozen 重放断链（2.1/2.2/2.3）
# ═══════════════════════════════════════════════════════════════════


class TestTerminalExemption(_Base):
    """alert-noise-governance 1.1：终态（done/archived）spec 豁免内容闸门。

    背景（c-sched-set 实证）：已交付 spec（实现已合并、验证 25/25 通过）被
    外部 STATE 重置打回后，闸门按「空 spec」冻结并挂 major 告警——处置方向
    与事实相反。
    """

    def _terminal_spec(self, name, status, files):
        _mk_spec_dir(self.project_root, name, files)
        self.sm.add_spec(name, {"priority": 5})
        self.sm.update_spec(name, {"status": status})
        return name

    def test_done_empty_dir_not_frozen_no_alert(self):
        """done 态空目录：闸门放行（不冻结、不告警），状态保持 done。"""
        self._terminal_spec("done-spec", "done", [])
        self.assertFalse(self.engine._check_spec_content_missing("done-spec"))
        entry = self.sm.read_one("done-spec")
        self.assertEqual(entry["status"], "done")
        self.assertFalse(entry.get("frozen"))
        self.assertEqual(self._alerts("spec_content_missing", "done-spec"), [])
        self.assertEqual(
            self._alerts("spec_delivered_no_content", "done-spec"), [])

    def test_archived_also_exempt(self):
        """archived 拼写同享豁免（spec.md 场景语言；状态机当前不产出该值，
        STATE 序列化会丢弃之——此处直接以条目形态驱动闸门分类判定）。"""
        _mk_spec_dir(self.project_root, "arch-spec", [])
        gate = self.engine._spec_integrity
        with patch.object(self.sm, "read_one",
                          return_value={"status": "archived"}):
            self.assertFalse(gate.check_spec_content_missing("arch-spec"))
        self.assertEqual(self._alerts("spec_content_missing", "arch-spec"), [])

    def test_terminal_exemption_does_not_touch_blocked_idempotent(self):
        """终态豁免与既有 blocked 幂等短路并列：blocked 语义不受影响。"""
        self._terminal_spec("blk-spec", "blocked", [])
        self.assertTrue(self.engine._check_spec_content_missing("blk-spec"))


class TestDeliveredNoContent(_Base):
    """alert-noise-governance 1.2：仅存 verification-report.md 的独立分类。"""

    def _delivered_ready_spec(self, name="delivered-spec"):
        _mk_spec_dir(self.project_root, name, ["verification-report.md"])
        self.sm.add_spec(name, {"priority": 5})
        self.sm.transition(name, "ready")
        return name

    def test_report_only_dir_produces_delivered_signal_not_frozen(self):
        name = self._delivered_ready_spec()
        self.assertTrue(self.engine._check_spec_content_missing(name))
        entry = self.sm.read_one(name)
        # 不冻结：状态不被改写为 blocked+frozen（人工裁决上下文保留在 ready）
        self.assertEqual(entry["status"], "ready")
        self.assertFalse(entry.get("frozen"))
        alerts = self._alerts("spec_delivered_no_content", name)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["severity"], "major")
        self.assertIn("二选一裁决", alerts[0]["recommended_action"])
        self.assertIn("spec_delivered_adjudicated", alerts[0]["recommended_action"])

    def test_repeat_hit_no_duplicate_alert(self):
        """幂等短路：重复命中不追加告警（恢复精触发 60s 一轮，防告警风暴）。"""
        name = self._delivered_ready_spec()
        self.assertTrue(self.engine._check_spec_content_missing(name))
        self.assertTrue(self.engine._check_spec_content_missing(name))
        self.assertTrue(self.engine._check_spec_content_missing(name))
        self.assertEqual(len(self._alerts("spec_delivered_no_content", name)), 1)

    def test_dispatch_still_blocked(self):
        """派发拦截语义不变：分类分支仍返回 True，不派出实现 run。"""
        name = self._delivered_ready_spec()
        self.sm.update_spec(name, {"status": "ready"})
        self.engine._run_agent_worker = MagicMock()
        self.engine._enqueue(name, "implementer")
        self.engine._process_queue()
        self.engine._run_agent_worker.assert_not_called()
        self.assertEqual(self.sm.read_one(name)["status"], "ready")

    def test_no_report_still_freezes_semantics_regression(self):
        """无验证报告仍走既有冻结路径（语义回归）。"""
        name = "empty-spec"
        _mk_spec_dir(self.project_root, name, [])
        self.sm.add_spec(name, {"priority": 5})
        self.sm.transition(name, "ready")
        self.assertTrue(self.engine._check_spec_content_missing(name))
        entry = self.sm.read_one(name)
        self.assertEqual(entry["status"], "blocked")
        self.assertIs(entry.get("frozen"), True)
        self.assertEqual(len(self._alerts("spec_content_missing", name)), 1)
        self.assertEqual(
            self._alerts("spec_delivered_no_content", name), [])

    def test_spec_has_content_ignores_verification_report(self):
        """1.3：verification-report.md 不进认可名单（防盲目重实现，09-12 实证）。"""
        _mk_spec_dir(self.project_root, "report-only", ["verification-report.md"])
        self.assertFalse(spec_has_content(self.project_root, "report-only"))
        # 报告 + 无关文件同样不算内容
        _mk_spec_dir(self.project_root, "report-noise",
                     ["verification-report.md", "run.log"])
        self.assertFalse(spec_has_content(self.project_root, "report-noise"))
        # 报告 + 任一认可文件仍算有内容（判据本身不动）
        _mk_spec_dir(self.project_root, "report-tasks",
                     ["verification-report.md", "tasks.md"])
        self.assertTrue(spec_has_content(self.project_root, "report-tasks"))


class TestDeliveredNoContentLifecycle(unittest.TestCase):
    """alert-noise-governance 1.4：spec_delivered_no_content 接入生命周期闭环。"""

    def test_signal_condition_registered(self):
        self.assertEqual(
            _SIGNAL_CONDITIONS.get("spec_delivered_no_content"),
            CONDITION_SPEC_DELIVERED_ADJUDICATED,
        )

    def test_trigger_attached_via_unified_entry(self):
        """经统一告警入口写入时 trigger 自动推导为 spec_delivered_adjudicated。"""
        import tempfile
        import shutil
        tmpdir = tempfile.mkdtemp()
        try:
            project_root = Path(tmpdir)
            (project_root / ".fenix").mkdir(parents=True, exist_ok=True)
            logger = MagicMock()
            engine, sm = _mk_engine(project_root, logger)
            _mk_spec_dir(project_root, "dlv-spec", ["verification-report.md"])
            sm.add_spec("dlv-spec", {"priority": 5})
            sm.transition("dlv-spec", "ready")
            engine._check_spec_content_missing("dlv-spec")

            alerts = [a for a in AdminStore(project_root, logger).read_all()
                      if a.get("signal_type") == "spec_delivered_no_content"]
            self.assertEqual(len(alerts), 1)
            trigger = alerts[0].get("trigger")
            self.assertIsNotNone(trigger)
            self.assertEqual(trigger["condition"], CONDITION_SPEC_DELIVERED_ADJUDICATED)
            self.assertEqual(trigger["spec"], "dlv-spec")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def _alert(self, spec="dlv-spec"):
        return {
            "kind": "escalation",
            "signal_type": "spec_delivered_no_content",
            "spec": spec,
            "trigger": {
                "type": "spec_delivered_no_content",
                "spec": spec,
                "condition": CONDITION_SPEC_DELIVERED_ADJUDICATED,
            },
        }

    def test_pending_adjudication_alert_stays_visible(self):
        """待裁决期间（ready/blocked）auto_resolve 不闭环，人工队列持续可见。"""
        for status in ("ready", "blocked", "implemented", "testing"):
            specs = {"dlv-spec": {"status": status}}
            self.assertIsNone(evaluate_alert(self._alert(), specs),
                              f"status={status} 非终态不得自动闭环")

    def test_terminal_adjudication_auto_resolves(self):
        """人工置终态后由 spec_delivered_adjudicated 条件自动闭环。"""
        for status in ("done", "pushed", "archived"):
            specs = {"dlv-spec": {"status": status}}
            note = evaluate_alert(self._alert(), specs)
            self.assertIsNotNone(note, f"status={status} 终态应自动闭环")
            self.assertIn("dlv-spec", note)

    def test_handled_path_stays_human_closed(self):
        """「补 tasks.md 归档凭据」路径：handled 记录不可被 auto 覆盖。"""
        alert = self._alert()
        alert["handled"] = True
        specs = {"dlv-spec": {"status": "done"}}
        self.assertIsNone(evaluate_alert(alert, specs))

    def test_condition_registered_constant(self):
        self.assertEqual(CONDITION_SPEC_DELIVERED_ADJUDICATED,
                         "spec_delivered_adjudicated")


class TestFrozenReplayGuards(unittest.TestCase):
    """alert-noise-governance 2.1/2.2/2.3：冻结 spec 不被恢复/派发链重放。

    背景（2026-09-22 实证）：外部回置把冻结 spec 的 status 打回 ready 后，
    恢复与派发链均不复核 frozen，同日重放 9 轮「就绪→派发→拦截→冻结」，
    全天 18 条闸门 ERROR。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = self.project_root / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        self.runner = MagicMock()
        self.runner.worktree_manager = MagicMock()
        self.runner.worktree_manager.has_active_worktree.return_value = False
        self.runner.has_live_attempt.return_value = False
        from core.pm_engine import PMEngine
        from core.event_bus import EventBus
        self.engine = PMEngine(self.sm, self.runner, {}, self.project_root, self.logger)
        self.engine._process_queue = MagicMock()  # 防止 worker 线程异步副作用
        self.bus = EventBus(self.state_path, self.sm, self.engine, {}, self.logger)
        self.store = AdminStore(self.project_root, self.logger)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _frozen_reset_spec(self, name="frozen-spec"):
        """写入「外部部分回置」形态：status=ready + frozen=True + error 非空。"""
        self.sm.add_spec(
            name, {"status": "ready", "error": "dispatch stalled", "frozen": True}
        )

    def _escalations(self):
        return [a for a in self.store.read_all() if a.get("kind") == ESCALATION]

    # ── 2.1：孤儿恢复 frozen 复核 ────────────────────────────────

    def test_frozen_orphan_recovery_skips_without_state_write(self):
        self._frozen_reset_spec()
        with patch.object(self.engine, "handle_event") as mock_handle:
            self.bus.recover_orphan_ready()
        mock_handle.assert_not_called()
        entry = self.sm.read_one("frozen-spec")
        # 零 STATE 写入：error 不被清、frozen/status 保持原样
        self.assertEqual(entry["error"], "dispatch stalled")
        self.assertIs(entry.get("frozen"), True)
        self.assertEqual(entry["status"], "ready")
        # INFO 留痕（含 spec 名与原因）
        info_texts = " ".join(
            str(c.args[1] if len(c.args) > 1 else c.args[0])
            for c in self.logger.info.call_args_list
        )
        self.assertIn("frozen-spec", info_texts)
        self.assertIn("frozen", info_texts.lower())

    def test_non_frozen_orphan_recovery_unchanged(self):
        """2.3 语义回归：非冻结孤儿 ready 恢复行为不变（清 error + 重派）。"""
        self.sm.add_spec("orphan-spec", {"status": "ready", "error": "stalled"})
        with patch.object(self.engine, "handle_event") as mock_handle:
            self.bus.recover_orphan_ready()
        mock_handle.assert_called_once()
        entry = self.sm.read_one("orphan-spec")
        self.assertIsNone(entry.get("error"))

    # ── 2.2：派发链 frozen 复核 ──────────────────────────────────

    def test_frozen_replay_dispatch_skipped_no_gate_error(self):
        """重启回放经 _on_spec_ready 跳过派发，不再产生闸门 ERROR。"""
        self._frozen_reset_spec()
        self.engine._enqueue = MagicMock()
        self.engine._on_spec_ready("frozen-spec")
        self.engine._enqueue.assert_not_called()
        entry = self.sm.read_one("frozen-spec")
        self.assertEqual(entry["status"], "ready")
        self.assertIs(entry.get("frozen"), True)
        # 闸门未运行 → 零升级告警（不再重放「派发→拦截→冻结」）
        self.assertEqual(self._escalations(), [])

    def test_non_frozen_dispatch_unchanged(self):
        """2.3 语义回归：非冻结 ready spec 派发守卫链行为不变（正常入队）。

        add-verify-lane-throughput 1.1 起 _on_spec_ready 成功入队 implementer
        后默认触发并行出题（verify.parallel_planning 缺省开启），对无场景集的
        ready spec 追加一条 planner-plan 条目；本守卫的核心语义是实现车道恰好
        入队一次，故按角色过滤断言（planner-plan 契约由
        test_verify_lane_throughput 专项覆盖）。
        """
        _mk_spec_dir(self.project_root, "ready-spec", ["tasks.md"])
        self.sm.add_spec("ready-spec", {"status": "ready"})
        self.engine._enqueue = MagicMock()
        self.engine._on_spec_ready("ready-spec")
        impl_calls = [
            c.args for c in self.engine._enqueue.call_args_list
            if c.args == ("ready-spec", "implementer")
        ]
        self.assertEqual(impl_calls, [("ready-spec", "implementer")])


# ═══════════════════════════════════════════════════════════════════
# fix-legacy-ghost-spec-entry-reclaim：幽灵指纹判定与结构性清退
# （design D2 三条件 AND / D3 清退动作与留痕 / D4 挂点与配置）
# ═══════════════════════════════════════════════════════════════════


class _GhostBase(_Base):
    """幽灵清退测试基座：真实 git 仓库 + created 回拨 + 台账/告警读取。"""

    def setUp(self):
        super().setUp()
        self._git_init()

    def _git_init(self):
        """项目根初始化为含一次初始提交的真实 git 仓库（历史探测走真实 git）。"""
        import os
        import subprocess

        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        }

        def git(*args):
            subprocess.run(
                ["git", "-C", str(self.project_root), *args],
                check=True,
                capture_output=True,
                env=env,
            )

        git("init", "-q")
        git("config", "user.email", "t@example.com")
        git("config", "user.name", "t")
        (self.project_root / "README.md").write_text("x\n", encoding="utf-8")
        git("add", "README.md")
        git("commit", "-q", "-m", "init")

    def _backdate(self, name: str, minutes: float):
        created = (datetime.now(timezone.utc) - timedelta(minutes=minutes))
        self.sm.update_spec(name, {"created": created.isoformat()})

    def _mk_entry(self, name: str, minutes=60, extra=None):
        """注册条目并回拨 created（默认 60 分钟前，过新鲜度窗）。"""
        fields = {"priority": 5}
        if minutes is not None:
            fields["created"] = (
                datetime.now(timezone.utc) - timedelta(minutes=minutes)
            ).isoformat()
        if extra:
            fields.update(extra)
        self.sm.add_spec(name, fields)
        return name

    def _ledger_entries(self) -> list:
        path = ghost_reclaim_ledger_path(self.project_root)
        if not path.is_file():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").split("\n"):
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out

    def _ghost_alerts(self) -> list:
        return [
            a for a in AdminStore(self.project_root, self.logger).read_all()
            if a.get("signal_type") == GHOST_RECLAIM_SIGNAL_TYPE
        ]


class TestGhostFingerprintTruthTable(_GhostBase):
    """3.1：指纹真值表——三条件各自翻转即不命中；全中即命中；
    blocked+frozen 全中亦命中（冻结不豁免）。"""

    def test_freshness_window_constant_is_30(self):
        # task 1.2：新鲜度窗模块常量（30 分钟）
        self.assertEqual(GHOST_ENTRY_FRESHNESS_MINUTES, 30)

    def test_all_three_conditions_hit(self):
        self._mk_entry("ghost-spec")
        verdict = self.engine._spec_integrity.detect_ghost_entries()
        self.assertEqual([h["spec"] for h in verdict["hits"]], ["ghost-spec"])
        self.assertEqual(verdict["skipped"], [])
        hit = verdict["hits"][0]
        # 每项含三项指纹证据
        self.assertIn("created", hit)
        self.assertIn("dir_evidence", hit)
        self.assertIn("git_evidence", hit)
        self.assertIn("零提交", hit["git_evidence"])
        self.assertGreaterEqual(hit["age_minutes"], 30)

    def test_content_condition_flip_not_hit(self):
        # 条件 1 翻转：物化过 proposal.md（7f7ee45e2 范式）→ 不命中
        self._mk_entry("content-spec")
        _mk_spec_dir(self.project_root, "content-spec", ["proposal.md"])
        verdict = self.engine._spec_integrity.detect_ghost_entries()
        self.assertEqual(
            [h["spec"] for h in verdict["hits"] if h["spec"] == "content-spec"],
            [],
        )

    def test_git_history_condition_flip_not_hit(self):
        # 条件 2 翻转：曾立项提交过、目录后被误删 → git 历史仍在 → 不命中
        name = "committed-spec"
        d = _mk_spec_dir(self.project_root, name, ["proposal.md"])
        import os
        import subprocess
        subprocess.run(
            ["git", "-C", str(self.project_root), "add", f"spec/changes/{name}"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(self.project_root), "commit", "-q", "-m", name],
            check=True,
            capture_output=True,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "t",
                "GIT_AUTHOR_EMAIL": "t@example.com",
                "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@example.com",
            },
        )
        shutil.rmtree(d)  # 模拟目录被误删（历史仍在）
        self._mk_entry(name)
        self.assertFalse(spec_has_content(self.project_root, name))
        self.assertTrue(git_path_has_commits(self.project_root, name))
        verdict = self.engine._spec_integrity.detect_ghost_entries()
        self.assertEqual(
            [h["spec"] for h in verdict["hits"] if h["spec"] == name], []
        )

    def test_freshness_condition_flip_not_hit(self):
        # 条件 3 翻转：新注册条目（< 30 分钟）→ 不命中
        self._mk_entry("fresh-spec", minutes=None)  # created=now
        verdict = self.engine._spec_integrity.detect_ghost_entries()
        self.assertEqual(
            [h["spec"] for h in verdict["hits"] if h["spec"] == "fresh-spec"],
            [],
        )

    def test_missing_created_conservative_not_hit(self):
        # created 缺失/非法（判龄失败）保守不清退
        self.sm.add_spec("no-ts-spec", {"priority": 5, "created": ""})
        verdict = self.engine._spec_integrity.detect_ghost_entries()
        self.assertEqual(
            [h["spec"] for h in verdict["hits"] if h["spec"] == "no-ts-spec"],
            [],
        )

    def test_pushed_terminal_exempt(self):
        # 终态豁免（design D2 字面：pushed 豁免）
        self._mk_entry("pushed-spec", extra={"status": "pushed"})
        verdict = self.engine._spec_integrity.detect_ghost_entries()
        self.assertEqual(
            [h["spec"] for h in verdict["hits"] if h["spec"] == "pushed-spec"],
            [],
        )

    def test_blocked_frozen_hit_frozen_not_exempt(self):
        # 冻结不豁免（design D3）：孪生条目形态 blocked+frozen 全中即命中
        self._mk_entry(
            "frozen-ghost", extra={"status": "blocked", "frozen": True}
        )
        verdict = self.engine._spec_integrity.detect_ghost_entries()
        hits = [h for h in verdict["hits"] if h["spec"] == "frozen-ghost"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["status"], "blocked")


class TestGhostExemptions(_GhostBase):
    """3.2：新鲜度豁免、非法名跳过、物化 proposal 条目不命中。"""

    def test_fresh_entry_not_reclaimed(self):
        # < 30 分钟不清退，留待下一轮对账
        self._mk_entry("fresh-ghost", minutes=None)
        result = self.engine.reclaim_ghost_entries()
        self.assertEqual(result["reclaimed"], [])
        self.assertIsNotNone(self.sm.read_one("fresh-ghost"))
        self.assertEqual(self._ledger_entries(), [])

    def test_materialized_proposal_entry_not_hit(self):
        # arbiter 7f7ee45e2 范式：最小成文 proposal.md 即有内容，不命中不清退
        self._mk_entry("materialized-spec")
        _mk_spec_dir(self.project_root, "materialized-spec", ["proposal.md"])
        result = self.engine.reclaim_ghost_entries()
        self.assertEqual(result["reclaimed"], [])
        self.assertIsNotNone(self.sm.read_one("materialized-spec"))
        self.assertEqual(self._ghost_alerts(), [])

    def test_unsafe_name_skipped_not_reclaimed(self):
        # 非法路径成分名：不进命中清单、另入跳过清单待告警、绝不清退
        entry = {
            "status": "ready",
            "created": (
                datetime.now(timezone.utc) - timedelta(hours=2)
            ).isoformat(),
        }
        with patch.object(
            self.sm, "read_all", return_value={"../evil": entry}
        ):
            verdict = self.engine._spec_integrity.detect_ghost_entries()
        self.assertEqual(verdict["hits"], [])
        self.assertEqual(verdict["skipped"], ["../evil"])

        with patch.object(
            self.sm, "read_all", return_value={"../evil": entry}
        ):
            result = self.engine.reclaim_ghost_entries()
        self.assertEqual(result["reclaimed"], [])
        self.assertEqual(result["skipped"], ["../evil"])
        # 保守跳过仍要告警待人工（spec Requirement 2）
        alerts = self._ghost_alerts()
        self.assertEqual(len(alerts), 1)
        self.assertIn("../evil", alerts[0]["description"])

    def test_normal_entries_silent_zero_noise(self):
        # 有内容/新鲜的正常条目零命中零副作用零日志噪音
        self._mk_entry("normal-spec")
        _mk_spec_dir(self.project_root, "normal-spec", ["tasks.md"])
        result = self.engine.reclaim_ghost_entries()
        self.assertEqual(result["reclaimed"], [])
        self.assertEqual(result["skipped"], [])
        self.assertFalse(result["alerted"])
        self.assertEqual(self._ghost_alerts(), [])
        self.assertEqual(self._ledger_entries(), [])


class TestGhostReclaimActions(_GhostBase):
    """3.3：清退断言——remove_spec 被调、条目消失、台账 kind 与证据、
    聚合告警单条含全清单。"""

    def test_reclaim_removes_entry_and_writes_ledger(self):
        self._mk_entry("ghost-spec")
        with patch.object(
            self.sm, "remove_spec", wraps=self.sm.remove_spec
        ) as mock_rm:
            result = self.engine.reclaim_ghost_entries()
        mock_rm.assert_called_once_with("ghost-spec")
        # STATE 条目消失
        self.assertIsNone(self.sm.read_one("ghost-spec"))
        self.assertEqual(
            [h["spec"] for h in result["reclaimed"]], ["ghost-spec"]
        )
        # 台账 kind 与三项证据字段
        ledger = self._ledger_entries()
        self.assertEqual(len(ledger), 1)
        rec = ledger[0]
        self.assertEqual(rec["kind"], GHOST_RECLAIM_LEDGER_KIND)
        self.assertEqual(rec["spec"], "ghost-spec")
        self.assertEqual(rec["status_at_reclaim"], "drafted")
        ev = rec["evidence"]
        self.assertIn("created", ev)
        self.assertIn("age_minutes", ev)
        self.assertIn("dir_probe", ev)
        self.assertIn("git_log", ev)
        self.assertIn("零提交", ev["git_log"])

    def test_aggregate_alert_single_contains_full_list(self):
        # 一轮至多一条聚合告警，列出全部清退条目与证据
        self._mk_entry("ghost-a")
        self._mk_entry("ghost-b")
        result = self.engine.reclaim_ghost_entries()
        self.assertEqual(len(result["reclaimed"]), 2)
        alerts = self._ghost_alerts()
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["kind"], ESCALATION)
        self.assertEqual(alerts[0]["severity"], "major")
        self.assertIn("ghost-a", alerts[0]["description"])
        self.assertIn("ghost-b", alerts[0]["description"])
        # 证据随告警可审计
        self.assertIn("零提交", alerts[0]["evidence"])
        self.assertIn(GHOST_RECLAIM_LEDGER_FILENAME, alerts[0]["evidence"])

    def test_check_blockers_hook_reclaims_ghost(self):
        # 2.1 挂点：check_blockers（full_scan 咽喉）先清退再扫描
        self._mk_entry("ghost-spec")
        self.engine.check_blockers()
        self.assertIsNone(self.sm.read_one("ghost-spec"))
        self.assertEqual(len(self._ledger_entries()), 1)

    def test_check_blockers_zero_hit_no_state_change(self):
        # 幂等：正常条目零副作用
        self._mk_entry("normal-spec")
        _mk_spec_dir(self.project_root, "normal-spec", ["tasks.md"])
        self.engine.check_blockers()
        self.assertEqual(self.sm.read_one("normal-spec")["status"], "drafted")
        self.assertEqual(self._ledger_entries(), [])
        self.assertEqual(self._ghost_alerts(), [])


class TestGhostIdempotentAndConfig(_GhostBase):
    """3.4：幂等重放（第二轮零清退、告警不重复）；开关 off 全跳过。"""

    def test_second_round_zero_reclaim_no_duplicate_alert(self):
        self._mk_entry("ghost-spec")
        first = self.engine.reclaim_ghost_entries()
        self.assertEqual(len(first["reclaimed"]), 1)
        second = self.engine.reclaim_ghost_entries()
        self.assertEqual(second["reclaimed"], [])
        self.assertFalse(second["alerted"])
        self.assertEqual(len(self._ghost_alerts()), 1)
        self.assertEqual(len(self._ledger_entries()), 1)
        self.assertIsNone(self.sm.read_one("ghost-spec"))

    def test_config_off_skips_everything(self):
        from core.pm_engine import PMEngine
        cfg_engine = PMEngine(
            self.sm,
            MagicMock(),
            {"gates": {"ghost_entry_reclaim": False}},
            self.project_root,
            self.logger,
        )
        self._mk_entry("ghost-spec")
        result = cfg_engine.reclaim_ghost_entries()
        self.assertFalse(result["enabled"])
        self.assertEqual(result["reclaimed"], [])
        # 零副作用：条目仍在、无台账、无告警
        self.assertIsNotNone(self.sm.read_one("ghost-spec"))
        self.assertEqual(self._ledger_entries(), [])
        self.assertEqual(self._ghost_alerts(), [])
        # check_blockers 挂点同样被开关短路
        cfg_engine.check_blockers()
        self.assertIsNotNone(self.sm.read_one("ghost-spec"))


if __name__ == "__main__":
    unittest.main()