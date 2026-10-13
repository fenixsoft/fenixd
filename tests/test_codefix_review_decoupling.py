"""test_codefix_review_decoupling.py — code-fix 车道与周期审查 run 调度解耦回归
（decouple-codefix-review-lanes 4.1-4.4）

覆盖四场景：
- 4.1 审查 run 在飞（模拟无产出）+ 台账有 open 条目 → code-fix 照常建树派批
  推进，无派批空窗（派发判据不含「审查在飞」）；
- 4.2 defer 批合回成功 → 链自驱动推进下一批（批收尾 defer=consumed 自驱动
  `_resubmit` ∪ 延迟台账合回核销后同一 checkpoint 继续选批投递）；
- 4.3 审查 run stall 看门狗：双判据（产物 mtime × 进程树 CPU）同时无进展达
  阈值 → cancel + 既有急救落账 + 告警；任一判据有进展 → 重置不触发；
- 4.4 审查正常收尾 inserted>0 → 两路激活语义不变（inserted==0 不激活、
  cancel 抢救落账不激活的红线一并钉住）。

MUST NOT 真跑 agent——复用 tests/test_code_fix.py 的 fake runner / 临时目录
脚手架与 tests/test_code_review.py 的 run_code_review fake runner 形态。
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from test_code_fix import (  # noqa: E402
    _CapturingExecutor,
    _FakeRunner,
    _FakeWM,
    _make_project_root,
    _wip_blocked_info,
    _write_items,
    _write_verify_yaml,
    _item,
)

_HISTORY_TMP = _TESTS_DIR.parent / ".history" / "tmp"
_HISTORY_TMP.mkdir(parents=True, exist_ok=True)

# batch_size=1：两条 open 拆两批，才能断言「批间自驱动推进无空窗」
_CFG_B1 = {"admin": {"code_review_fix": {"enabled": True, "batch_size": 1}}}


def _mkdtemp(prefix: str) -> str:
    return tempfile.mkdtemp(prefix=prefix, dir=str(_HISTORY_TMP))


_RUN_ID = "code-review-1799000000"


def _write_review_inflight(proot: Path, run_id: str = _RUN_ID, n_files: int = 2):
    """构造「审查 run 在飞」磁盘现场（read_progress running=True 的判据集）。

    - manifest-<run_id>.json：total 权威来源（files 非空）；
    - .fenix/runs/<run_id>.jsonl：末行非终态 + mtime 新鲜（running 判据）；
    - out-<run_id>.jsonl：进度产物（看门狗 mtime 判据的观测对象）。
    """
    crdir = proot / ".fenix" / "code-review"
    crdir.mkdir(parents=True, exist_ok=True)
    (crdir / f"manifest-{run_id}.json").write_text(json.dumps({
        "run_id": run_id, "scope": "window", "review_kind": "scheduled",
        "requested_at": "2026-09-24T06:17:08+00:00",
        "files": [f"core/f{i}.py" for i in range(n_files)],
    }), encoding="utf-8")
    out = crdir / f"out-{run_id}.jsonl"
    out.write_text(
        json.dumps({"file": "core/f0.py", "findings": []}) + "\n", encoding="utf-8")
    runs = proot / ".fenix" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / f"{run_id}.jsonl").write_text(
        json.dumps({"type": "system", "subtype": "init"}) + "\n", encoding="utf-8")
    return out


def _mark_run_terminal(proot: Path, run_id: str = _RUN_ID):
    """run 文件追加 cancelled 终态行（read_progress running=false 判据）。"""
    rf = proot / ".fenix" / "runs" / f"{run_id}.jsonl"
    with rf.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "cancelled"}) + "\n")


def _read_items_status(proot: Path) -> dict:
    from core.code_review import read_items

    return {k: v.get("status") for k, v in read_items(proot).items()}


class TestDispatchDecoupledFromReviewInflight(unittest.TestCase):
    """4.1/2.2：审查在飞期间 code-fix 照常建树派批推进（解耦）。"""

    def test_review_inflight_does_not_gate_dispatch(self):
        from core.code_fix import CodeFixOrchestrator
        from core.code_review import read_progress

        proot = _make_project_root()
        _write_review_inflight(proot)
        # 夹具自证：审查 run 确实在飞（read_progress running 判据成立）
        self.assertTrue(read_progress(proot)["running"])

        _write_items(proot, {"a": _item("a"), "b": _item("b")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot)
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_B1, logger=None)

        # 同步链（executor=None）：一次 checkpoint 建树派批并自驱动跑完两批
        res = orch.checkpoint()
        self.assertTrue(res["triggered"],
                        "审查在飞 MUST NOT 否决/等待 code-fix 派批")
        self.assertEqual(len(runner.fix_calls), 2, "两批连投，无派批空窗")
        self.assertEqual(len(runner.worktree_manager.create_calls), 2,
                         "每批均真实建树")
        self.assertEqual(_read_items_status(proot),
                         {"a": "resolved", "b": "resolved"})
        # 审查在飞现场不被 code-fix 触碰
        self.assertTrue(read_progress(proot)["running"])

    def test_review_inflight_with_stalled_progress_still_dispatches(self):
        """审查产物 mtime 停滞（模拟无产出）也不构成派批否决条件。"""
        import time

        from core.code_fix import CodeFixOrchestrator

        proot = _make_project_root()
        out = _write_review_inflight(proot)
        stale = time.time() - 3600
        os.utime(out, (stale, stale))  # 产物 1 小时无更新（无产出形态）

        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot)
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_B1, logger=None)
        self.assertTrue(orch.checkpoint()["triggered"])
        self.assertEqual(len(runner.fix_calls), 1)
        self.assertEqual(_read_items_status(proot), {"a": "resolved"})


class TestDeferMergeBackSelfDrives(unittest.TestCase):
    """4.2：defer 批合回成功 → 链自驱动推进下一批（等价 success 收尾）。"""

    def _arm_block_once(self, wm, overlap):
        """伪 merge_back：首次返回 wip_gate_blocked=True，此后放行（主树转净）。"""
        real_merge = wm.merge_back
        state = {"n": 0}

        def flaky(wt_path):
            state["n"] += 1
            wm.merge_calls.append(str(wt_path))
            if state["n"] == 1:
                return _wip_blocked_info(overlap)
            return real_merge(wt_path)

        wm.merge_back = flaky

    def test_defer_batch_merge_back_success_advances_chain(self):
        from core.code_fix import (CodeFixOrchestrator, load_deferred_batches,
                                   read_progress)

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a"), "b": _item("b")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot)
        runner.worktree_manager = _FakeWM("git", enforce_lock=True)
        self._arm_block_once(runner.worktree_manager, ["src/a.py"])
        executor = _CapturingExecutor()
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_B1, logger=None,
                                   executor=executor)

        self.assertTrue(orch.checkpoint()["triggered"])
        # 批 a worker：合回被 WIP 挡住 → defer（consumed）→ 自驱动 _resubmit
        executor.run_one()
        self.assertEqual(len(load_deferred_batches(proot)), 1, "批 a 已入延迟台账")
        # 无外部激活（审查收尾/扫描均未发生）：队列里的 checkpoint 作业即自驱动
        executor.run_one()  # resubmit 的 checkpoint：延迟批合回成功 + 投递批 b
        executor.run_one()  # 批 b worker：success 收尾 → 再 resubmit
        executor.run_one()  # 收尾 checkpoint：无 open 条目收敛

        self.assertEqual(executor.jobs, [], "链自驱动收敛，无残留作业")
        self.assertEqual(_read_items_status(proot),
                         {"a": "resolved", "b": "resolved"},
                         "defer 批合回成功核销 + 链推进下一批核销")
        self.assertEqual(load_deferred_batches(proot), [], "延迟台账清空")
        self.assertEqual(len(runner.fix_calls), 2, "两批均真实派 run，无空窗")
        prog = read_progress(proot)
        self.assertFalse(prog["running"])
        self.assertEqual(prog["phase"], "idle")

    def test_deferred_retry_success_dispatches_next_batch_same_checkpoint(self):
        """延迟台账合回核销后，同一 checkpoint 继续选批投递（不等下一次节拍）。"""
        from core.code_fix import CodeFixOrchestrator, record_deferred_batch

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a"), "b": _item("b")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot)
        runner.worktree_manager = _FakeWM("git", enforce_lock=True)
        # 预置延迟台账：批 a 的保留现场（worktree 在册，merge_back 恒成功）。
        # tip_sha 必须是 worktree HEAD 真值——_deferred_entry_alive 以它对账
        # 判活，假值会让条目被判死移出台账（D5 再认领判据）。
        wt = runner.worktree_manager.create(spec_name="code-review-fix",
                                            agent_type="code-fix")
        head = subprocess.run(
            ["git", "-C", str(wt), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True).stdout.strip()
        branch = subprocess.run(
            ["git", "-C", str(wt), "rev-parse", "--abbrev-ref", "HEAD"],
            check=True, capture_output=True, text=True).stdout.strip()
        record_deferred_batch(proot, ["a"], ["a"], Path(wt),
                              branch=branch, tip_sha=head,
                              last_overlap=["src/a.py"])
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_B1, logger=None)

        # 单次 checkpoint（同步链）：_process_deferred_merges 核销批 a 后
        # 继续投递批 b——不等下一次 full scan / 审查收尾激活
        self.assertTrue(orch.checkpoint()["triggered"])
        self.assertEqual(_read_items_status(proot),
                         {"a": "resolved", "b": "resolved"})
        self.assertEqual(len(runner.fix_calls), 1, "批 b 在同一 checkpoint 投递")


class _SilentLogger:
    """吞掉全部日志调用的假 logger（AdminMonitor 构造依赖）。"""

    def __getattr__(self, name):
        return lambda *a, **k: None


class _FakeStateMachine:
    def read_all(self):
        return {}


class _FakeAdminAgentRunner:
    """看门狗 fake agent_runner：进程表 + cancel_run 记录。"""

    def __init__(self, run_id, pid=4321):
        self._running_agents = {run_id: types.SimpleNamespace(pid=pid)}
        self.cancel_calls = []

    def cancel_run(self, run_id, reason="", by="admin"):
        self.cancel_calls.append((run_id, reason, by))
        return {"status": "cancel_requested", "attempts": [run_id],
                "base_run_id": run_id}


class TestReviewStallWatchdog(unittest.TestCase):
    """4.3：审查 run stall 看门狗双判据触发 / 误杀防护。"""

    def setUp(self):
        import core.admin_monitor as am

        from core.agent_runner import maintenance_runs as mr
        from core.admin_store import AdminStore

        self._am = am
        self._mr = mr
        self._real_time = am.time
        self.clock = {"now": 1_000_000.0}
        am.time = types.SimpleNamespace(time=lambda: self.clock["now"])
        self.proot = Path(_mkdtemp("review-watchdog-"))
        self.run_id = _RUN_ID
        self.out = _write_review_inflight(self.proot, self.run_id)
        self.cpu = {"v": 10.0}
        self._real_cpu_fn = mr.agent_process_cpu_seconds
        mr.agent_process_cpu_seconds = lambda proc: self.cpu["v"]

        self.runner = _FakeAdminAgentRunner(self.run_id)
        self.mon = am.AdminMonitor(
            config={"admin": {"review_stall_minutes": 30}},
            state_machine=_FakeStateMachine(),
            project_root=self.proot,
            logger=_SilentLogger(),
            store=AdminStore(self.proot, None),
            agent_runner=self.runner,
        )

    def tearDown(self):
        self._am.time = self._real_time
        self._mr.agent_process_cpu_seconds = self._real_cpu_fn
        shutil.rmtree(str(self.proot), ignore_errors=True)

    def _advance(self, minutes, touch_mtime=False, cpu=None):
        self.clock["now"] += minutes * 60
        if touch_mtime:
            os.utime(self.out, (self.clock["now"], self.clock["now"]))
        if cpu is not None:
            self.cpu["v"] = cpu
        return self.mon._check_review_run_watchdog()

    def _alerts(self, signal_type):
        from core.admin_store import AdminStore

        return [r for r in AdminStore(self.proot, None).read_all()
                if r.get("signal_type") == signal_type]

    def test_double_criterion_stall_triggers_cancel_alert(self):
        """双判据同时无进展达阈值 → 取消 + 告警留痕（急救落账由收尾路径接手）。"""
        first = self.mon._check_review_run_watchdog()
        self.assertEqual(first["reason"], "baseline")
        res = self._advance(31)
        self.assertTrue(res["triggered"])
        self.assertEqual(res["threshold_minutes"], 30)
        # cancel_run 经既有原语登记（by=review_stall_watchdog 留痕可判别）
        self.assertEqual(len(self.runner.cancel_calls), 1)
        rid, reason, by = self.runner.cancel_calls[0]
        self.assertEqual(rid, self.run_id)
        self.assertEqual(by, "review_stall_watchdog")
        self.assertIn("review_stall_watchdog", reason)
        # 告警留痕：ESCALATION + 去重键，evidence 携带双判据冻结值
        alerts = self._alerts("review_stall_watchdog")
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["kind"], "escalation")
        self.assertEqual(alerts[0]["dedup_key"],
                         f"review-stall-watchdog-{self.run_id}")
        self.assertIn("cpu_seconds=10.0", alerts[0]["evidence"])
        self.assertIn("mtime=", alerts[0]["evidence"])
        # 取消完成后 run 落终态：再次巡检短路 not_running，不重复取消
        _mark_run_terminal(self.proot, self.run_id)
        again = self.mon._check_review_run_watchdog()
        self.assertEqual(again["reason"], "not_running")
        self.assertEqual(len(self.runner.cancel_calls), 1)

    def test_alert_dedup_single_record_per_run(self):
        self.mon._check_review_run_watchdog()
        self._advance(31)
        # 恢复在飞现场模拟重复巡检：再触发也不得重复落告警
        self.runner.cancel_calls.clear()
        self.mon._review_stall_state[self.run_id] = {
            "mtime": self.out.stat().st_mtime, "cpu": self.cpu["v"],
            "since": self.clock["now"] - 3600}
        self.mon._check_review_run_watchdog()
        self.assertEqual(len(self._alerts("review_stall_watchdog")), 1,
                         "单 run 至多一条（append_if_absent 去重）")

    def test_cpu_progress_resets_timer(self):
        """CPU 判据有进展 → 重置计时，不触发。"""
        self.mon._check_review_run_watchdog()
        res = self._advance(31, cpu=42.5)
        self.assertFalse(res["triggered"])
        self.assertEqual(res["reason"], "baseline", "任一判据有进展即整体重置")
        self.assertEqual(self.runner.cancel_calls, [])
        # 重置后再停滞满阈值才触发（计时不从旧基线累计）
        res2 = self._advance(31)
        self.assertTrue(res2["triggered"])

    def test_mtime_progress_resets_timer(self):
        """产物 mtime 有进展 → 重置计时，不触发。"""
        self.mon._check_review_run_watchdog()
        res = self._advance(31, touch_mtime=True)
        self.assertFalse(res["triggered"])
        self.assertEqual(res["reason"], "baseline")
        self.assertEqual(self.runner.cancel_calls, [])

    def test_below_threshold_does_not_trigger(self):
        self.mon._check_review_run_watchdog()
        res = self._advance(10)
        self.assertFalse(res["triggered"])
        self.assertEqual(res["reason"], "below_threshold")
        self.assertEqual(self.runner.cancel_calls, [])
        self.assertEqual(self._alerts("review_stall_watchdog"), [])

    def test_cpu_unavailable_fails_open(self):
        """进程句柄缺失（CPU 判据不可用）→ fail-open 不触发。"""
        self.runner._running_agents.clear()
        self.mon._check_review_run_watchdog()
        res = self._advance(120)
        self.assertFalse(res["triggered"])
        self.assertEqual(res["reason"], "cpu_unavailable")
        self.assertEqual(self.runner.cancel_calls, [])

    def test_threshold_config_key_respected(self):
        """admin.review_stall_minutes 生效（缺省 30 之外可调）。"""
        from core.admin_store import AdminStore

        mon = self._am.AdminMonitor(
            config={"admin": {"review_stall_minutes": 5}},
            state_machine=_FakeStateMachine(),
            project_root=self.proot,
            logger=_SilentLogger(),
            store=AdminStore(self.proot, None),
            agent_runner=self.runner,
        )
        mon._check_review_run_watchdog()
        self.clock["now"] += 6 * 60
        res = mon._check_review_run_watchdog()
        self.assertTrue(res["triggered"])
        self.assertEqual(res["threshold_minutes"], 5)

    def test_not_running_clears_state(self):
        """run 离开在飞（终态/缺失）→ 短路并清理看门狗状态。"""
        self.mon._check_review_run_watchdog()
        self.assertIn(self.run_id, self.mon._review_stall_state,
                      "baseline 巡检已建状态")
        (self.proot / ".fenix" / "runs" / f"{self.run_id}.jsonl").unlink()
        # 末行判据依赖 run 文件：缺失即 running=false
        res = self.mon._check_review_run_watchdog()
        self.assertEqual(res["reason"], "not_running")
        self.assertEqual(self.mon._review_stall_state, {})


class _OrchRecorder:
    """记录 checkpoint 调用的 code-fix 编排器替身。"""

    def __init__(self):
        self.calls = []

    def checkpoint(self):
        self.calls.append(True)
        return {"triggered": False, "reason": "recorded"}


class TestReviewCompletionActivationPreserved(unittest.TestCase):
    """4.4：审查正常收尾 inserted>0 → 链激活语义不变（两路激活之一）。"""

    def setUp(self):
        self.proot = Path(_mkdtemp("cr-activate-"))
        self.crdir = self.proot / ".fenix" / "code-review"
        self.crdir.mkdir(parents=True)
        self.run_id = _RUN_ID

    def tearDown(self):
        shutil.rmtree(str(self.proot), ignore_errors=True)

    def _fake_runner(self, boom=False):
        from core.agent_runner import maintenance_runs as mr

        runner = type("R", (), {})()
        runner.project_root = self.proot
        runner.logger = None
        runner._unique_code_review_run_id = lambda: self.run_id
        runner._build_prompt = lambda *a, **k: "PROMPT"
        runner._get_agent_model_assignment = lambda *a, **k: None
        runner._get_admin_model = lambda: "test-model"
        runner._extract_usage_info = lambda *a, **k: {}
        runner._accumulate_code_review_tokens = lambda *a, **k: None
        runner._read_code_review_out = lambda project_root, rid: (
            mr._read_code_review_out(runner, project_root, rid))
        if boom:
            def _cancel(*a, **k):
                from core.agent_runner.result_gate import RunCancelledError

                raise RunCancelledError(
                    reason="审查 run 双判据停滞（阈值 30 分钟）",
                    by="review_stall_watchdog")

            runner._run_agent = _cancel
        else:
            runner._run_agent = lambda *a, **k: ("OUT", 3, "sess", {})
        return runner

    def _write_out(self, findings):
        (self.crdir / f"out-{self.run_id}.jsonl").write_text(
            json.dumps({"file": "core/a.py", "findings": findings}) + "\n",
            encoding="utf-8")

    @staticmethod
    def _finding():
        return {"line": 3, "severity": "major", "category": "correctness",
                "title": "解耦回归发现。", "description": "d", "suggestion": "s",
                "evidence": "core/a.py:3"}

    def _run(self, runner):
        from core.agent_runner import maintenance_runs as mr

        return mr.run_code_review(runner, ["core/a.py"], "scheduled")

    def test_success_with_inserted_activates_chain(self):
        """正常收尾 inserted>0 → checkpoint 恰触发一次（既有语义逐字保留）。"""
        orch = _OrchRecorder()
        runner = self._fake_runner()
        runner._code_fix_orchestrator = orch
        self._write_out([self._finding()])
        result = self._run(runner)
        self.assertTrue(result.success)
        self.assertEqual(result.inserted, 1)
        self.assertEqual(orch.calls, [True], "inserted>0 激活一次")

    def test_success_without_inserted_does_not_activate(self):
        """inserted==0（无新 open 条目）→ 不激活（语义不变：仅 inserted>0）。"""
        orch = _OrchRecorder()
        runner = self._fake_runner()
        runner._code_fix_orchestrator = orch
        self._write_out([])
        result = self._run(runner)
        self.assertTrue(result.success)
        self.assertEqual(result.inserted, 0)
        self.assertEqual(orch.calls, [])

    def test_cancelled_salvage_ledgers_but_does_not_activate(self):
        """看门狗取消收场：既有急救落账入账，MUST NOT 激活修复链（红线不变）。"""
        orch = _OrchRecorder()
        runner = self._fake_runner(boom=True)
        runner._code_fix_orchestrator = orch
        self._write_out([self._finding()])
        result = self._run(runner)
        self.assertFalse(result.success)
        self.assertIn("review_stall_watchdog", result.error)
        self.assertEqual(result.inserted, 1, "cancel 后既有抢救路径产物入账")
        items = [
            json.loads(x)
            for x in (self.crdir / "items.jsonl").read_text(encoding="utf-8")
            .splitlines() if x.strip()
        ]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["status"], "open")
        self.assertEqual(orch.calls, [], "残跑产物不激活修复链（既有红线）")


if __name__ == "__main__":
    unittest.main()
