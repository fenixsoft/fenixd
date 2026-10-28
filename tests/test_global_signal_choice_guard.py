"""tests/test_global_signal_choice_guard.py — 全局信号 × 裁决 choice 作用域守卫。

fix-global-signal-choice-execution 3.2：覆盖
  1. 执行器守卫（execute_adjudication_choice）：spec=null 与占位 'global'
     两形态拒绝 retry_review；未注册 signal_type 的 spec_scoped 动作不再
     全表反查兜底放行；非作用域 choice（ack_self_heal/ignore）正常执行；
     注册桶内 retry_review × 真实冻结 spec 对照（守卫不误伤合法路径）。
  2. 消费端守卫与终态回写纠偏（admin_monitor）：全局信号 × spec_scoped
     choice 处置流——choice 跳过留 INFO、信号不回写 handled/resolved、
     告警记录 result=failed + action_taken=动作名、DISPOSITION error 留痕；
     非作用域 choice 成功路径照常闭环留痕；choice 执行失败（非法 id）
     同样不闭环。
  3. mark_signal_handled 留痕契约（admin_store）：handled=False 只留痕不
     闭环、成功闭环带留痕、缺省调用向后兼容（幂等 False / ESCALATION 不匹配）。
"""
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from core.admin_monitor import AdminMonitor
from core.admin_store import AdminStore, DISPOSITION, ESCALATION, SIGNAL
from core.agent_runner.result_gate import AdminDisposition
from core.dashboard.data.admin_actions import (
    _exec_commit_stray_wip,
    execute_adjudication_choice,
)


# ── 夹具（与 test_adjudication_choices 同构收编）─────────────────────────


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
    """spec-review-incomplete 冻结形态（retry_review 的合法前置）。"""
    from core.state_machine import StateMachine, project_state_logger

    sm = StateMachine(proot / ".fenix" / "STATE.md", project_state_logger(proot))
    sm.update_spec(spec, {
        "frozen": True,
        "status": "blocked",
        "error": "spec-review-incomplete: 评审尝试已达上限",
    })


class _RecordingLogger:
    """记录型 logger（消费端跳过 INFO 留痕断言用）。"""

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
    """写入一条全局形态待处置 SIGNAL 记录，返回落地记录（含 id）。"""
    return store.append({
        "kind": SIGNAL,
        "signal_type": stype,
        "spec": spec,
        "severity": "critical",
        "description": "daemon ERROR 指纹 10 分钟窗口复现",
        "evidence": "fp=ce27a93f9dca; window=10m",
        "recommended_action": "",
    })


class _TempProjCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))


# ── 1. 执行器守卫 ────────────────────────────────────────────────────────


class TestExecutorScopeGuard(_TempProjCase):
    """执行器守卫：全局信号拒入 spec_scoped choice（1.2）+ 反查收紧（1.1）。"""

    GLOBAL_SPECS = (None, "", "global")

    def test_global_signal_rejects_retry_review(self):
        """spec=null / 空串 / 占位 'global' × retry_review → 拒绝执行。"""
        for gspec in self.GLOBAL_SPECS:
            r = execute_adjudication_choice(
                str(self.tmpdir), gspec, "retry_review",
                signal_type="spec-review-incomplete",
            )
            self.assertFalse(r["ok"], f"spec={gspec!r} 应拒绝执行")
            self.assertIn("全局信号", r["error"])
            self.assertEqual(r["action"], "retry_review")

    def test_unregistered_signal_type_scoped_choice_no_reverse_lookup(self):
        """未注册 signal_type × spec_scoped 动作 → 不再全表反查兜底放行。"""
        r = execute_adjudication_choice(
            str(self.tmpdir), "spec-a", "retry_review",
            signal_type="daemon_errors",
        )
        self.assertFalse(r["ok"])
        self.assertIn("全表反查", r["error"])
        # 全局形态同断（全局守卫或反查收紧任一拦截）
        r2 = execute_adjudication_choice(
            str(self.tmpdir), "global", "retry_review",
            signal_type="daemon_errors",
        )
        self.assertFalse(r2["ok"])
        self.assertTrue(
            ("全局信号" in r2["error"]) or ("全表反查" in r2["error"]),
            r2["error"],
        )

    def test_nonscoped_choice_executes_for_global_signal(self):
        """非作用域 choice（ack_self_heal/ignore）× 全局信号正常执行（1.3）。"""
        r = execute_adjudication_choice(
            str(self.tmpdir), "global", "ack_self_heal",
            signal_type="daemon_errors",
        )
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["action"], "ack_self_heal")
        r2 = execute_adjudication_choice(
            str(self.tmpdir), None, "ignore", signal_type="token_budget",
        )
        self.assertTrue(r2["ok"], r2.get("error"))

    def test_registered_scoped_choice_with_real_spec_still_executes(self):
        """对照：注册桶内 retry_review × 真实冻结 spec 照常执行（不误伤）。"""
        proot = _make_proot(self.tmpdir)
        _freeze_review_incomplete(proot)
        r = execute_adjudication_choice(
            str(proot), "spec-frozen", "retry_review",
            signal_type="spec-review-incomplete",
        )
        self.assertTrue(r["ok"], r.get("error"))


# ── 1.5 commit_stray_wip 执行路径与守卫（evo-add-commit-stray-wip-choice 3.2）──

# git 仓夹具用仓库内 .history/tmp（gitignored；/tmp 可能被外部清扫，同
# test_maintree_stray_wip_sweep 规避），MUST NOT 改写全局 tempfile.tempdir。
_HISTORY_TMP = pathlib.Path(__file__).resolve().parent.parent / ".history" / "tmp"
_HISTORY_TMP.mkdir(parents=True, exist_ok=True)

_BOUND_SIGNAL_TYPE = "maintree_stray_wip_stale"


def _git(*args, cwd, check=True):
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd), check=check, capture_output=True, text=True,
    )


def _make_wip_repo() -> pathlib.Path:
    """主树仓 + .fenix 状态目录：基线提交后留散件 WIP（a.txt 已改、
    c.txt 为清单外新文件——反例对照，永不被裹挟提交）。仓库本地配置
    提交身份（执行器自起 git 子进程，不经 -c 旗标）。"""
    base = pathlib.Path(tempfile.mkdtemp(prefix="stray-commit-", dir=str(_HISTORY_TMP)))
    repo = base / "proj"
    repo.mkdir(parents=True)
    _git("init", "-q", cwd=repo)
    _git("config", "user.email", "t@t", cwd=repo)
    _git("config", "user.name", "t", cwd=repo)
    (repo / ".gitignore").write_text(".fenix/\n", encoding="utf-8")
    for name in ("a.txt", "b.txt"):
        (repo / name).write_text("base", encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "init", cwd=repo)
    (repo / ".fenix").mkdir()
    (repo / "a.txt").write_text("stray wip", encoding="utf-8")
    (repo / "c.txt").write_text("off-manifest", encoding="utf-8")
    return repo


def _seed_stale_signal(repo, files, signal_type=_BOUND_SIGNAL_TYPE):
    """写入一条带「文件清单(N):」段的散件 WIP SIGNAL 记录（发射点同款 evidence）。"""
    return AdminStore(repo).append({
        "kind": SIGNAL,
        "signal_type": signal_type,
        "spec": None,
        "severity": "major",
        "description": "主树散件 WIP 滞留",
        "evidence": (
            "项目名=proj; first_seen=2026-10-07T00:00:00+00:00; "
            f"文件清单({len(files)}): {', '.join(files) or '无'}; "
            "零触碰注记: 本盘点只读"
        ),
        "recommended_action": "",
    })


def _head(repo) -> str:
    return _git("rev-parse", "HEAD", cwd=repo).stdout.strip()


def _status(repo) -> str:
    return _git("status", "--porcelain", cwd=repo).stdout


class TestCommitStrayWipExecutor(_TempProjCase):
    """commit_stray_wip 执行路径（全局信号放行 / 清单约束 / D4 绑定守卫）。"""

    def test_global_signal_commit_stray_wip_executes_with_hash(self):
        """全局信号（spec=None）× commit_stray_wip 放行；只提交清单内文件，
        处置结果附提交 hash；清单外 c.txt 不被裹挟。"""
        repo = _make_wip_repo()
        _seed_stale_signal(repo, ["a.txt"])
        before_head = _head(repo)
        r = execute_adjudication_choice(
            str(repo), None, "commit_stray_wip", signal_type=_BOUND_SIGNAL_TYPE,
        )
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["action"], "commit_stray_wip")
        self.assertEqual(r["commit_hash"], _head(repo))
        self.assertNotEqual(r["commit_hash"], before_head)
        self.assertEqual(r["committed_files"], ["a.txt"])
        status = _status(repo)
        self.assertNotIn("a.txt", status)
        self.assertIn("c.txt", status)
        # 提交 hash 在 steps 留痕（处置记录附提交 hash 语义）
        self.assertTrue(any(r["commit_hash"] in s for s in r["steps"]))

    def test_manifest_stale_entries_skipped_silently(self):
        """清单中已不在当刻 status 的文件跳过不报错（同指纹一次性告警，清单陈旧）。"""
        repo = _make_wip_repo()
        _seed_stale_signal(repo, ["a.txt", "gone.txt"])
        r = execute_adjudication_choice(
            str(repo), None, "commit_stray_wip", signal_type=_BOUND_SIGNAL_TYPE,
        )
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["committed_files"], ["a.txt"])
        self.assertTrue(any("gone.txt" in s for s in r["steps"]))

    def test_empty_intersection_returns_error_no_empty_commit(self):
        """交集为空返回明确 error，不产生空提交。"""
        repo = _make_wip_repo()
        _seed_stale_signal(repo, ["gone.txt"])
        before_head, before_status = _head(repo), _status(repo)
        r = execute_adjudication_choice(
            str(repo), None, "commit_stray_wip", signal_type=_BOUND_SIGNAL_TYPE,
        )
        self.assertFalse(r["ok"])
        self.assertIn("不产生空提交", r["error"])
        self.assertEqual(_head(repo), before_head)
        self.assertEqual(_status(repo), before_status)

    def test_out_of_manifest_path_rejected_zero_git_write(self):
        """清单外路径拒绝并返回原因，不做任何 git 写。"""
        repo = _make_wip_repo()
        _seed_stale_signal(repo, ["a.txt"])
        before_head, before_status = _head(repo), _status(repo)
        r = _exec_commit_stray_wip(
            str(repo), signal_type=_BOUND_SIGNAL_TYPE, paths=["c.txt"],
        )
        self.assertFalse(r["ok"])
        self.assertIn("清单外", r["error"])
        self.assertEqual(_head(repo), before_head)
        self.assertEqual(_status(repo), before_status)

    def test_signal_type_binding_guard_blocks_all_other_types(self):
        """design D4：resolve_choice 非作用域全表反查通道把本 git 写动作暴露
        给任意未注册信号——执行器校验 signal_type 后才落 git 写，姊妹 info
        信号 maintree_untracked_stray_stale 与未注册信号一律拒绝且零 git 写。"""
        repo = _make_wip_repo()
        _seed_stale_signal(repo, ["a.txt"])
        before_head, before_status = _head(repo), _status(repo)
        for st in ("maintree_untracked_stray_stale", "daemon_errors",
                   "random_unregistered", ""):
            r = execute_adjudication_choice(
                str(repo), None, "commit_stray_wip", signal_type=st,
            )
            self.assertFalse(r["ok"], f"signal_type={st!r} 应拒绝")
            self.assertIn("仅限", r["error"])
        self.assertEqual(_head(repo), before_head)
        self.assertEqual(_status(repo), before_status)

    def test_missing_signal_record_rejected_before_git_write(self):
        """无可解析清单的信号记录：明确 error，不执行 git 写。"""
        repo = _make_wip_repo()
        before_head, before_status = _head(repo), _status(repo)
        r = execute_adjudication_choice(
            str(repo), None, "commit_stray_wip", signal_type=_BOUND_SIGNAL_TYPE,
        )
        self.assertFalse(r["ok"])
        self.assertIn("文件清单", r["error"])
        self.assertEqual(_head(repo), before_head)
        self.assertEqual(_status(repo), before_status)


# ── 2. 消费端守卫与终态回写纠偏 ──────────────────────────────────────────


class TestConsumerGlobalSkipAndWriteback(_TempProjCase):
    """消费端跳过（2.1）与回写纠偏（2.2）：失败/跳过不闭环、留痕落告警记录。"""

    def _run_disposition(self, signal, disp):
        proot = _make_proot(self.tmpdir)
        mon, store, logger = _make_monitor(proot)
        rec = _seed_signal(store, signal["signal_type"], spec=signal.get("spec"))
        mon.agent_runner.run_administrator = mock.MagicMock(return_value=disp)
        mon._invoke_administrator(signal, rec)
        return store, logger, rec

    def test_global_scoped_choice_skip_keeps_signal_unresolved(self):
        """全局信号 × retry_review：跳过留 INFO，信号不回写 resolved/handled。"""
        signal = {
            "signal_type": "daemon_errors", "spec": "global",
            "severity": "critical", "description": "daemon ERROR 复现",
        }
        disp = AdminDisposition(
            run_id="admin-run-g1", spec="global", success=True,
            result="resolved", summary="评审链路可恢复",
            actions_taken="建议重派评审", choice_id="retry_review",
        )
        store, logger, rec = self._run_disposition(signal, disp)
        recs = {r["id"]: r for r in store.read_all()}
        sig = recs[rec["id"]]
        # 信号保留待重审：不置 handled、终态 failed
        self.assertFalse(sig.get("handled"), "信号 MUST NOT 被闭环")
        self.assertEqual(sig.get("result"), "failed")
        self.assertEqual(sig.get("action_taken"), "retry_review")
        # 消费端 INFO 留痕
        self.assertTrue(
            any("跳过执行" in i and "retry_review" in i for i in logger.infos),
            f"应有跳过 INFO 留痕: {logger.infos}",
        )
        # DISPOSITION error 留痕（choice 执行未生效）
        disps = [r for r in store.read_all() if r.get("kind") == DISPOSITION]
        self.assertEqual(len(disps), 1)
        self.assertIn("choice 执行未生效", disps[0].get("error") or "")
        self.assertEqual(disps[0].get("choice_id"), "retry_review")

    def test_global_nonscoped_choice_success_closes_with_trace(self):
        """全局信号 × ack_self_heal 成功：闭环 + action_taken/result 留痕。"""
        signal = {
            "signal_type": "daemon_errors", "spec": "global",
            "severity": "critical", "description": "daemon ERROR 复现",
        }
        disp = AdminDisposition(
            run_id="admin-run-g2", spec="global", success=True,
            result="resolved", summary="确认自愈，继续观察",
            actions_taken="瞬时错误已恢复", choice_id="ack_self_heal",
        )
        store, logger, rec = self._run_disposition(signal, disp)
        sig = {r["id"]: r for r in store.read_all()}[rec["id"]]
        self.assertTrue(sig.get("handled"), "非作用域收口成功应闭环")
        self.assertEqual(sig.get("result"), "resolved")
        self.assertEqual(sig.get("action_taken"), "ack_self_heal")

    def test_choice_execution_failure_keeps_signal_open(self):
        """choice 执行失败（非法 id × 真实 spec 语境）：result=failed 不闭环。"""
        signal = {
            "signal_type": "daemon_errors", "spec": "spec-frozen",
            "severity": "critical", "description": "daemon ERROR 复现",
        }
        disp = AdminDisposition(
            run_id="admin-run-g3", spec="spec-frozen", success=True,
            result="resolved", summary="建议处置",
            actions_taken="动作名不存在", choice_id="nope",
        )
        store, logger, rec = self._run_disposition(signal, disp)
        sig = {r["id"]: r for r in store.read_all()}[rec["id"]]
        self.assertFalse(sig.get("handled"), "执行失败 MUST NOT 闭环")
        self.assertEqual(sig.get("result"), "failed")
        # 逐动作落账（evo-add-admin-orphan-disposition-effect-check 2.1）后
        # 失败形态留两条：主处置记录（带 admin_run_id）+ 逐动作 failed 审计
        # 事件（无 admin_run_id，run 在 final 落账前死亡时已执行事实不丢）。
        # 本用例原断言的「不闭环 + 失败留痕可溯源」语义均不变，仅记录总数
        # 随逐动作事件 +1。
        disps = [r for r in store.read_all() if r.get("kind") == DISPOSITION]
        finals = [r for r in disps if r.get("admin_run_id") == "admin-run-g3"]
        steps = [r for r in disps if not r.get("admin_run_id")]
        self.assertEqual(len(finals), 1)
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].get("result"), "failed")
        self.assertIn("非法 choice_id", finals[0].get("error") or "")
        self.assertIn("非法 choice_id", steps[0].get("error") or "")


# ── 2b. 自动执行通道载荷优先（fix-admin-choice-payload-and-scenario-pairing 4.1）──


class TestChoicePayloadChannel(_TempProjCase):
    """_apply_choice_execution note 来源三分支：
    载荷原文直传执行器 / 缺载荷 skipped 不调执行器 / 非载荷选项 note 仍为
    依据文本截断 200 字（行为不变）。"""

    PAYLOAD = (
        '{"scenarios": [{"id": "s1", "name": "修订后场景", "steps": []}], '
        '"reason": "原场景定义不可行", "fixture_files": []}'
    )

    def _make_mon(self):
        proot = _make_proot(self.tmpdir)
        _freeze_review_incomplete(proot)
        mon, _store, _logger = _make_monitor(proot)
        return mon

    @staticmethod
    def _capture_executor():
        """替换执行器捕获 note（载荷通道断言不真改 spec 状态机）。"""
        captured = {}

        def fake_executor(proot, spec, cid, note="", signal_type=""):
            captured.update({"note": note, "spec": spec, "choice_id": cid})
            return {"ok": True, "choice_id": cid, "action": cid,
                    "steps": [], "error": None}

        return captured, mock.patch(
            "core.dashboard.data.admin_actions.execute_adjudication_choice",
            side_effect=fake_executor,
        )

    def test_payload_reaches_executor_verbatim(self):
        """载荷非空 → note 取 choice_payload 原文整体直传（不经 actions_taken
        拼接或 200 字截断）。"""
        mon = self._make_mon()
        captured, patcher = self._capture_executor()
        long_basis = "依据文本" * 300  # 远超 200 字，证明截断路径未介入
        disp = AdminDisposition(
            run_id="admin-run-p1", spec="spec-frozen", success=True,
            result="resolved", summary="已修订场景集",
            actions_taken=long_basis,
            choice_id="revise_scenario_reverify",
            choice_payload=self.PAYLOAD,
        )
        with patcher:
            outcome = mon._apply_choice_execution(
                {"signal_type": "inconclusive_loop", "spec": "spec-frozen"},
                disp,
            )
        self.assertTrue(outcome["ok"])
        self.assertEqual(captured["note"], self.PAYLOAD)
        self.assertEqual(captured["choice_id"], "revise_scenario_reverify")
        self.assertEqual(captured["spec"], "spec-frozen")

    def test_missing_payload_skips_executor(self):
        """载荷必需选项缺载荷 → not-ok skipped，不调执行器（不留必然失败
        日志），信号保留待重审。"""
        mon = self._make_mon()
        calls = []

        def forbidden_executor(*a, **k):
            calls.append(1)
            return {"ok": True, "steps": [], "error": None}

        disp = AdminDisposition(
            run_id="admin-run-p2", spec="spec-frozen", success=True,
            result="resolved", summary="未携带载荷",
            choice_id="revise_scenario_reverify",
        )
        with mock.patch(
            "core.dashboard.data.admin_actions.execute_adjudication_choice",
            side_effect=forbidden_executor,
        ):
            outcome = mon._apply_choice_execution(
                {"signal_type": "inconclusive_loop", "spec": "spec-frozen"},
                disp,
            )
        self.assertIsNotNone(outcome)
        self.assertFalse(outcome["ok"])
        self.assertTrue(outcome.get("skipped"))
        self.assertIn("choice_payload", outcome.get("error") or "")
        self.assertEqual(outcome.get("action"), "revise_scenario_reverify")
        self.assertEqual(calls, [], "缺载荷 MUST NOT 调执行器")
        # WARNING 留痕（跳过可溯源）
        self.assertTrue(
            any("choice_payload" in w for w in mon.logger.warnings),
            f"应有缺载荷 WARNING 留痕: {mon.logger.warnings}",
        )

    def test_non_payload_option_note_is_basis_text(self):
        """非载荷选项无载荷 → note 维持 actions_taken 截断 200 字现状。"""
        mon = self._make_mon()
        basis_text = "缺口可接受的依据" * 100
        captured, patcher = self._capture_executor()
        disp = AdminDisposition(
            run_id="admin-run-p3", spec="spec-frozen", success=True,
            result="resolved", summary="接受现状推进",
            actions_taken=basis_text,
            choice_id="force_advance",
        )
        with patcher:
            outcome = mon._apply_choice_execution(
                {"signal_type": "impl_budget_exhausted", "spec": "spec-frozen"},
                disp,
            )
        self.assertTrue(outcome["ok"])
        self.assertEqual(captured["note"], basis_text[:200])


# ── 3. mark_signal_handled 留痕契约 ─────────────────────────────────────


class TestMarkSignalHandledTrace(unittest.TestCase):
    """mark_signal_handled 扩展参数：留痕与闭环解耦（2.3）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))
        self.store = AdminStore(self.tmpdir)

    def _sig(self):
        return self.store.append({
            "kind": SIGNAL, "signal_type": "daemon_errors",
            "spec": None, "severity": "critical", "description": "x",
        })

    def test_failure_trace_without_close(self):
        """handled=False 只留痕不闭环：失败路径（result=failed + 动作名）。"""
        sig = self._sig()
        self.assertTrue(self.store.mark_signal_handled(
            sig["id"], action_taken="retry_review", result="failed",
            handled=False,
        ))
        rec = [r for r in self.store.read_all() if r["id"] == sig["id"]][0]
        self.assertFalse(rec.get("handled"), "失败留痕 MUST NOT 置 handled")
        self.assertIsNone(rec.get("handled_at"))
        self.assertEqual(rec.get("action_taken"), "retry_review")
        self.assertEqual(rec.get("result"), "failed")

    def test_success_trace_closes(self):
        """成功路径：闭环 + 留痕一体（result=resolved + 动作名 + handled_at）。"""
        sig = self._sig()
        self.assertTrue(self.store.mark_signal_handled(
            sig["id"], action_taken="ack_self_heal", result="resolved",
        ))
        rec = [r for r in self.store.read_all() if r["id"] == sig["id"]][0]
        self.assertTrue(rec.get("handled"))
        self.assertTrue(rec.get("handled_at"))
        self.assertEqual(rec.get("action_taken"), "ack_self_heal")
        self.assertEqual(rec.get("result"), "resolved")

    def test_default_call_backward_compatible(self):
        """缺省调用（仅 alert_id）：行为与历史一致，不写留痕字段。"""
        sig = self._sig()
        self.assertTrue(self.store.mark_signal_handled(sig["id"]))
        self.assertFalse(self.store.mark_signal_handled(sig["id"]))  # 幂等
        rec = [r for r in self.store.read_all() if r["id"] == sig["id"]][0]
        self.assertTrue(rec.get("handled"))
        self.assertIsNone(rec.get("action_taken"))
        self.assertIsNone(rec.get("result"))

    def test_escalation_kind_not_matched(self):
        """既有语义不放宽：ESCALATION 记录不经本方法闭环。"""
        esc = self.store.append({
            "kind": ESCALATION, "signal_type": "x",
            "spec": "s1", "severity": "major", "description": "y",
        })
        self.assertFalse(self.store.mark_signal_handled(
            esc["id"], action_taken="a", result="resolved",
        ))


if __name__ == "__main__":
    unittest.main()
