"""test_drain_inflight_run_protection.py — evo-drain-inflight-run-protection 测试集（tasks 4.1）

覆盖（spec 五组验收场景）：
①  排水窗扩容一致性门：shutdown=0 未同调告警留痕不阻断、协调配置不告警、
   planned 有效窗在 shutdown≤0 回退（310−10=300）下仍 ≥300；
②  code-review prompt 批边界旗标自检段：detail 携带 checkpoint_flag_path 注入
   （含路径与置位退出语义），未携带不注入；
③  writeoff 锚即时续审周期扫描：锚缺席零动作、enabled 闸、绕同日闸（gate
   已布防仍派发且不读状态）、剃余派发（redispatch_of/reason）、剩余为零不派、
   空清单不派、夜窗顺延零副作用、单飞闸（in_flight 标志与 _running_agents
   前缀探测）、同步收尾复位单飞；
④  续审运行注记 reason=writeoff_resume；缺省（429/stall 重派路径不传）保持
   "429 ratelimit" 字面；
⑤  旗标响应退出路径落锚：success + 部分覆盖 + 旗标在册 + 非重派 → 写锚
   reason=restart_checkpoint；全覆盖解锁 → 清锚不写；重派 run → 链根锚不覆写。

run_code_review 链路经最小 runner 替身驱动（_run_agent 写真实 out 产物，
聚合/落账/核销/锚链路全走生产代码，沿 test_code_review_salvage_writeoff 同款）。
"""

import importlib.util
import json
import logging
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from core.agent_runner.run_files import restart_checkpoint_flag_path
from core.code_review import (
    read_pending_writeoff,
    write_pending_writeoff,
)
from core.config import ConfigLoader


# ── 公共小件 ───────────────────────────────────────────────────────────


def _make_repo(prefix="cr-drain-"):
    root = Path(tempfile.mkdtemp(prefix=prefix))
    (root / ".fenix" / "code-review").mkdir(parents=True, exist_ok=True)
    (root / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
    return root


class _FakeLogger:
    def __init__(self):
        self.records = []

    def info(self, tag, message):
        self.records.append(f"INFO {tag} {message}")

    def warning(self, tag, message):
        self.records.append(f"WARNING {tag} {message}")

    def error(self, tag, message):
        self.records.append(f"ERROR {tag} {message}")


def _finding(category="correctness", title="bug", file_key=None, severity="major"):
    f = {
        "category": category,
        "title": title,
        "severity": severity,
        "description": f"desc {title}",
        "suggestion": f"fix {title}",
    }
    if file_key:
        f["file"] = file_key
    return f


class _ScriptedRunner:
    """AdminMonitor 侧 runner 替身：记录 run_code_review 调用并按剧本返回。"""

    def __init__(self, outcomes=None):
        self._running_agents = {}
        self._outcomes = list(outcomes or [])
        self.calls = []

    def run_code_review(self, manifest, review_kind="scheduled", window_start=None,
                        scope="window", **k):
        self.calls.append({
            "manifest": list(manifest), "kind": review_kind,
            "scope": scope, "window_start": window_start,
            "redispatch_of": k.get("redispatch_of"),
            "redispatch_reason": k.get("redispatch_reason"),
        })
        if self._outcomes:
            return self._outcomes.pop(0)
        return SimpleNamespace(
            run_id="code-review-x", success=True, inserted=0, updated=0,
            resolved=0, shards=0, error=None, ratelimit_redispatch=None,
            stall_redispatch=None, fail_face=None)


def _seed_flag(proot, run_id):
    """写重启 checkpoint 旗标（在册=置位；空 dict 视作未置位故写非空载荷）。"""
    p = restart_checkpoint_flag_path(proot, run_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"planned_restart": True}, ensure_ascii=False),
                 encoding="utf-8")
    return p


# ── ① 排水窗扩容一致性门 ───────────────────────────────────────────────


def _base_cfg(**admin_extra):
    admin = {"shutdown_drain_seconds": 0}
    admin.update(admin_extra)
    return {
        "project": {"name": "t", "type": "cli"},
        "schedule": {},
        "agents": {},
        "admin": admin,
        "worktree": {},
        "gates": {},
        "commands": {},
        "logging": {},
    }


class TestDrainWindowConsistencyGate(unittest.TestCase):
    """config 一致性告警（task 1.1）与 supervisor 回退联动（task 1.2）。"""

    def test_shutdown_zero_uncoordinated_warns_but_validates(self):
        """shutdown=0 且未同调 run_drain：告警留痕（恰等边界同样示警）、不阻断。"""
        with self.assertLogs("fenixd.config", level="WARNING") as ctx:
            ConfigLoader._validate(_base_cfg())
        joined = "\n".join(ctx.output)
        self.assertIn("排水窗被夹短", joined)
        self.assertIn("不阻断启动", joined)
        # effective = min(300, 310−10) = 300 == 申报 → 恰等边界第二析取支命中
        # （shutdown≤0 且 cap≤declared）。

    def test_coordinated_shutdown_no_warning(self):
        """shutdown=430（+120 margin → cap 540 ≥ 300）：有效窗不被夹短，不告警。"""
        with self.assertNoLogs("fenixd.config", level="WARNING"):
            ConfigLoader._validate(_base_cfg(shutdown_drain_seconds=430))

    def test_planned_effective_window_at_least_300_with_shutdown_zero(self):
        """shutdown=0 回退联动：planned 有效窗 = min(300, 310−10) = 300 ≥ 300。"""
        cfg = _base_cfg()
        value = ConfigLoader.get_run_drain_max_seconds(cfg, planned=True)
        self.assertGreaterEqual(value, 300.0)
        self.assertLessEqual(value, 300.0)  # 恰为 300（cap 300 夹等）

    def test_supervisor_sigkill_wait_planned_310_stop_60(self):
        """supervisor 双侧同源：planned restart 回退 310；stop/收编路径保持 60。"""
        tmp = Path(tempfile.mkdtemp(prefix="sup-drain-"))
        try:
            fenix = tmp / ".fenix"
            fenix.mkdir(parents=True)
            (fenix / "config.yaml").write_text(
                "admin:\n  shutdown_drain_seconds: 0\n", encoding="utf-8")
            sup_path = (Path(__file__).resolve().parent.parent
                        / "bin" / "fenixd_supervisor.py")
            spec = importlib.util.spec_from_file_location(
                "fenixd_supervisor_drain", sup_path)
            sup = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(sup)
            sup.FENIX_DIR = fenix
            sup.PROJECT_ROOT = tmp
            self.assertEqual(sup._sigkill_wait_seconds(planned_restart=True), 310)
            self.assertEqual(sup._sigkill_wait_seconds(), 60)
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)


# ── ② prompt 批边界旗标自检段 ──────────────────────────────────────────


class TestCheckpointFlagPromptInjection(unittest.TestCase):
    """detail 携带 checkpoint_flag_path → 注入自检段（task 2.1）。"""

    RUN_ID = "code-review-1791000000"

    def _build(self, detail):
        from core.agent_runner.prompt_builder import PromptBuilder

        proot = Path(tempfile.mkdtemp(prefix="cr-flag-prompt-"))
        try:
            pb = PromptBuilder(SimpleNamespace(project_root=str(proot)))
            return pb._build_code_review_prompt(self.RUN_ID, detail), proot
        finally:
            shutil.rmtree(str(proot), ignore_errors=True)

    def test_flag_path_detail_injects_selfcheck_section(self):
        prompt, _ = self._build({
            "manifest": ["core/a.py"],
            "review_window": "（全仓）",
            "out_path": "/tmp/out-x.jsonl",
            "checkpoint_flag_path": str(Path("/p/.fenix/runs") / f"{self.RUN_ID}.checkpoint.json"),
        })
        self.assertIn("## 重启排水批边界自检（drain-inflight-run-protection）", prompt)
        self.assertIn(f"{self.RUN_ID}.checkpoint.json", prompt)  # 路径已注入具体值
        self.assertIn("MUST NOT 开启新批", prompt)  # 置位语义：单批收尾退出
        self.assertIn("不视为失败", prompt)  # 提前退出语义
        self.assertIn("writeoff 锚即时续审", prompt)  # 剩余接管链路告知

    def test_no_flag_detail_no_section(self):
        prompt, _ = self._build({
            "manifest": ["core/a.py"],
            "review_window": "（全仓）",
            "out_path": "/tmp/out-x.jsonl",
        })
        self.assertNotIn("重启排水批边界自检", prompt)


# ── ③ writeoff 锚即时续审周期扫描 ──────────────────────────────────────


class _ScanHarness:
    """AdminMonitor + 核心替身注入（collect_manifest/状态读写/剃余来源全替身）。

    read_pending_writeoff 不替身：锚经真实 write_pending_writeoff 落盘、
    真实读回（锚在册性是本扫描唯一触发条件，走生产读侧）。
    """

    def __init__(self, enabled=True, scope="window", night_window=None,
                 covered=None, manifest=None, anchor_run=None):
        from core.admin_monitor import AdminMonitor

        self.repo = _make_repo()
        self.logger = _FakeLogger()
        self.runner = _ScriptedRunner()
        cr = {"enabled": enabled, "run_at": "00:00", "scope": scope}
        cfg = {
            "admin": {
                "code_review": cr,
                "self_review": {"enabled": True, "run_at": "00:00"},
            }
        }
        if night_window:
            cfg["admin"]["code_review_fix"] = {"night_quiet_window": night_window}
        self.mon = AdminMonitor(
            cfg, None, str(self.repo), self.logger,
            agent_runner=self.runner, code_review_executor=None,
        )
        if anchor_run:
            write_pending_writeoff(self.repo, {
                "run_id": anchor_run, "inserted": 3, "updated": 1,
                "at": "2026-11-16T00:00:00+00:00"})
        self._patches = [
            mock.patch("core.code_review.compute_window",
                       return_value=(
                           SimpleNamespace(isoformat=lambda: "2026-11-16T02:00:00"),
                           "self_review")),
            mock.patch("core.code_review.collect_manifest",
                       return_value=list(manifest if manifest is not None
                                         else ["src/a.py", "src/b.py"])),
            mock.patch("core.code_review.read_code_review_state", return_value={}),
            mock.patch("core.code_review.save_code_review_state"),
            mock.patch("core.code_review.cumulative_covered_files",
                       return_value=set(covered or set())),
        ]
        self.mocks = [p.start() for p in self._patches]

    def dispose(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(str(self.repo), ignore_errors=True)


class TestWriteoffAnchorResumeScan(unittest.TestCase):
    """锚驱动续审扫描门序与剃余派发（task 3.1）。"""

    ANCHOR = "code-review-900"

    def _run_scan(self, h):
        return h.mon._run_writeoff_anchor_resume_checkpoint()

    def test_no_anchor_is_noop(self):
        h = _ScanHarness()
        try:
            res = self._run_scan(h)
            self.assertEqual(res, {"triggered": False, "reason": "no_anchor"})
            h.mocks[1].assert_not_called()  # 未收集清单
            self.assertEqual(len(h.runner.calls), 0)  # 未派发
        finally:
            h.dispose()

    def test_disabled_zero_action_even_with_anchor(self):
        h = _ScanHarness(enabled=False, anchor_run=self.ANCHOR)
        try:
            res = self._run_scan(h)
            self.assertEqual(res, {"triggered": False, "reason": "disabled"})
            h.mocks[1].assert_not_called()
            self.assertEqual(len(h.runner.calls), 0)
        finally:
            h.dispose()

    def test_bypasses_same_day_gate_and_dispatches_remaining(self):
        """同日闸已布防（真实状态文件记当日）+ 锚在册 → 绕闸派发剃余清单。

        证明链：gate 状态真实落盘 → 扫描不读状态（mock 未被消费）→ 仍派发，
        manifest 为「本轮收集 − 锚链累计覆盖」的剩余，redispatch_of 指回锚。
        """
        from core.code_review import save_code_review_state as real_save
        from core.self_review import local_today_str

        h = _ScanHarness(covered={"src/a.py"}, anchor_run=self.ANCHOR)
        try:
            # 布防同日闸：真实写当日状态（每日检查点将拒绝）
            real_save(h.repo, local_today_str())
            res = self._run_scan(h)
            self.assertTrue(res.get("triggered"))
            self.assertTrue(res.get("ok"))
            self.assertEqual(res.get("reason"), "writeoff_resume_dispatched")
            self.assertEqual(res.get("resume_of"), self.ANCHOR)
            self.assertEqual(res.get("remaining"), 1)
            self.assertEqual(len(h.runner.calls), 1)
            call = h.runner.calls[0]
            self.assertEqual(call["manifest"], ["src/b.py"])  # 剃余后剩余
            self.assertEqual(call["redispatch_of"], self.ANCHOR)
            self.assertEqual(call["redispatch_reason"], "writeoff_resume")
            self.assertEqual(call["scope"], "window")
            # 投递前写防重（续审轮即当日一轮）
            h.mocks[3].assert_called_once()
            # 同步收尾（executor=None）后单飞标志复位
            self.assertFalse(h.mon._code_review_in_flight)
        finally:
            h.dispose()

    def test_all_covered_no_dispatch_and_no_gate_write(self):
        """锚链已全覆盖：不派发、不写同日状态（未派发不占用当日轮语义）。"""
        h = _ScanHarness(covered={"src/a.py", "src/b.py"}, anchor_run=self.ANCHOR)
        try:
            res = self._run_scan(h)
            self.assertFalse(res.get("triggered"))
            self.assertEqual(res.get("reason"), "writeoff_resume_no_remaining")
            self.assertEqual(len(h.runner.calls), 0)
            h.mocks[3].assert_not_called()
            self.assertFalse(h.mon._code_review_in_flight)
        finally:
            h.dispose()

    def test_empty_collect_no_dispatch(self):
        """收集清单为空：不派发、锚保持（不触碰核销红线）。"""
        h = _ScanHarness(manifest=[], anchor_run=self.ANCHOR)
        try:
            res = self._run_scan(h)
            self.assertFalse(res.get("triggered"))
            self.assertEqual(res.get("reason"), "no_files")
            self.assertEqual(len(h.runner.calls), 0)
            h.mocks[3].assert_not_called()
        finally:
            h.dispose()

    def test_night_window_defers_without_side_effects(self):
        """全日静默窗：顺延不派、不写同日防重（调用方契约）、锚保持。"""
        h = _ScanHarness(night_window="00:00-23:59", anchor_run=self.ANCHOR)
        try:
            res = self._run_scan(h)
            self.assertFalse(res.get("triggered"))
            self.assertEqual(res.get("reason"), "night_quiet_window_deferred")
            self.assertEqual(len(h.runner.calls), 0)
            h.mocks[1].assert_not_called()
            h.mocks[3].assert_not_called()
            self.assertFalse(h.mon._code_review_in_flight)
        finally:
            h.dispose()

    def test_in_flight_flag_blocks(self):
        """单飞闸（同锁同标志）：标志置位即不派、不复位他人标志。"""
        h = _ScanHarness(anchor_run=self.ANCHOR)
        try:
            h.mon._code_review_in_flight = True
            res = self._run_scan(h)
            self.assertEqual(res, {"triggered": False, "reason": "already_running"})
            self.assertEqual(len(h.runner.calls), 0)
            self.assertTrue(h.mon._code_review_in_flight)  # 他人标志不动
        finally:
            h.dispose()

    def test_running_agent_prefix_blocks(self):
        """单飞闸（外部 run 探测）：code-review- 前缀在飞 run 即不派。"""
        h = _ScanHarness(anchor_run=self.ANCHOR)
        try:
            h.runner._running_agents = {"code-review-777": object()}
            res = self._run_scan(h)
            self.assertEqual(res, {"triggered": False, "reason": "already_running_agent"})
            self.assertEqual(len(h.runner.calls), 0)
            self.assertFalse(h.mon._code_review_in_flight)  # 未置位即误置
        finally:
            h.dispose()

    def test_scope_full_passes_full_collection(self):
        """scope=full：collect_manifest 走全仓档，run window_start=None。"""
        h = _ScanHarness(scope="full", covered=set(), anchor_run=self.ANCHOR)
        try:
            res = self._run_scan(h)
            self.assertTrue(res.get("triggered"))
            _, kwargs = h.mocks[1].call_args
            self.assertEqual(kwargs.get("scope"), "full")
            self.assertEqual(h.runner.calls[0]["scope"], "full")
            self.assertIsNone(h.runner.calls[0]["window_start"])
        finally:
            h.dispose()


# ── ④ 续审运行注记 reason ──────────────────────────────────────────────


class _ProdPathRunner:
    """最小 runner 替身（沿 salvage 测试同款）：out 产物真实落盘。

    success_runs：轮次剧本 [(out_rows, die_after_write)]，按 _run_agent 消费。
    """

    def __init__(self, proot, run_id, out_rows=None, die=False):
        self.project_root = Path(proot)
        self.logger = _FakeLogger()
        self.config = {}
        self._run_id = run_id
        self._out_rows = out_rows or []
        self._die = die

    def _unique_code_review_run_id(self):
        return self._run_id

    def _build_prompt(self, run_id, agent_type, detail=None):
        self.last_detail = detail
        return "prompt"

    def _get_agent_model_assignment(self, name):
        return None

    def _get_admin_model(self):
        return "test-model"

    def _write_out(self):
        path = self.project_root / ".fenix" / "code-review" / f"out-{self._run_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in self._out_rows),
            encoding="utf-8")

    def _run_agent(self, prompt, root, run_id, model_override, env_overrides,
                   max_turns=None, spec_name=None, agent_type=None):
        self._write_out()
        if self._die:
            raise RuntimeError("Exit code: 1 (gateway 429)")
        return ("output", 3, "session", {}, None)

    def _extract_usage_info(self, x):
        return {}

    def _accumulate_code_review_tokens(self, run_id, usage):
        return None

    def _read_code_review_out(self, project_root, run_id):
        from core.agent_runner import maintenance_runs

        return maintenance_runs._read_code_review_out(self, project_root, run_id)


def _redispatch_note(proot, run_id):
    """读 run jsonl 中的 ratelimit_redispatch 注记行（无则 None）。"""
    p = Path(proot) / ".fenix" / "runs" / f"{run_id}.jsonl"
    if not p.is_file():
        return None
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("type") == "ratelimit_redispatch":
            return rec
    return None


class TestResumeNoteReason(unittest.TestCase):
    """重派注记 reason 参数化（task 3.2）：锚续审 writeoff_resume，缺省不变。"""

    def setUp(self):
        self.proot = _make_repo()

    def tearDown(self):
        shutil.rmtree(str(self.proot), ignore_errors=True)

    def test_writeoff_resume_reason_recorded(self):
        from core.agent_runner.maintenance_runs import run_code_review

        runner = _ProdPathRunner(
            self.proot, "code-review-901",
            out_rows=[{"file": "src/a.py", "findings": [_finding(title="x")]}])
        run_code_review(
            runner, ["src/a.py"], review_kind="scheduled", window_start=None,
            scope="full", redispatch_of=self.ANCHOR_RUN,
            redispatch_reason="writeoff_resume")
        note = _redispatch_note(self.proot, "code-review-901")
        self.assertIsNotNone(note)
        self.assertEqual(note["redispatch_of"], self.ANCHOR_RUN)
        self.assertEqual(note["reason"], "writeoff_resume")

    def test_default_reason_stays_429_ratelimit(self):
        """缺省（429/stall/empty 消费路径不传 reason）：字面保持 "429 ratelimit"。"""
        from core.agent_runner.maintenance_runs import run_code_review

        runner = _ProdPathRunner(
            self.proot, "code-review-902",
            out_rows=[{"file": "src/a.py", "findings": [_finding(title="y")]}])
        run_code_review(
            runner, ["src/a.py"], review_kind="scheduled", window_start=None,
            scope="full", redispatch_of="code-review-800")
        note = _redispatch_note(self.proot, "code-review-902")
        self.assertIsNotNone(note)
        self.assertEqual(note["reason"], "429 ratelimit")

    ANCHOR_RUN = "code-review-900"


# ── ⑤ 旗标响应退出路径落锚 ─────────────────────────────────────────────


class TestFlagResponseAnchorWrite(unittest.TestCase):
    """success 收场 + 旗标在册 + 部分覆盖 → 落锚；全覆盖清锚；重派不覆写链根。"""

    def setUp(self):
        self.proot = _make_repo()

    def tearDown(self):
        shutil.rmtree(str(self.proot), ignore_errors=True)

    def _run(self, run_id, manifest, out_files, *, flag=False,
             redispatch_of=None):
        from core.agent_runner.maintenance_runs import run_code_review

        rows = [{"file": f, "findings": [_finding(title=f"t-{f}"),
                                          _finding(title=f"s-{f}", category="style")]}
                for f in out_files]
        runner = _ProdPathRunner(self.proot, run_id, out_rows=rows)
        if flag:
            _seed_flag(self.proot, run_id)
        return run_code_review(
            runner, manifest, review_kind="scheduled", window_start=None,
            scope="full", redispatch_of=redispatch_of)

    def test_flag_partial_coverage_success_writes_anchor(self):
        """旗标在册 + 部分覆盖 + 非重派：写锚 reason=restart_checkpoint（优先）。

        覆盖缺口 1/2=50% > 2% → 终态降格 partial；同一收尾至多写一次锚，
        旗标锚优先，不得被 coverage_gap 锚覆写。
        """
        result = self._run(
            "code-review-910", ["src/a.py", "src/b.py"], ["src/a.py"], flag=True)
        self.assertFalse(result.success)
        self.assertTrue(getattr(result, "coverage_partial", False))
        anchor = read_pending_writeoff(self.proot)
        self.assertEqual(anchor.get("run_id"), "code-review-910")
        self.assertEqual(anchor.get("inserted"), 2)  # src/a.py 两条 finding
        self.assertEqual(anchor.get("updated"), 0)
        self.assertEqual(anchor.get("reason"), "restart_checkpoint",
                         "旗标锚优先，覆盖缺口锚不得覆写")
        self.assertTrue(anchor.get("at"))

    def test_flag_absent_partial_coverage_writes_coverage_gap_anchor(self):
        """旗标未置位但覆盖缺口超阈值：落 coverage_gap 锚（武装锚续审）。"""
        result = self._run(
            "code-review-911", ["src/a.py", "src/b.py"], ["src/a.py"], flag=False)
        self.assertFalse(result.success)
        self.assertTrue(getattr(result, "coverage_partial", False))
        anchor = read_pending_writeoff(self.proot)
        self.assertEqual(anchor.get("run_id"), "code-review-911")
        self.assertEqual(anchor.get("reason"), "coverage_gap")
        self.assertEqual(anchor.get("attempts"), 1)

    def test_flag_full_coverage_clears_preexisting_anchor(self):
        """全覆盖解锁：清既有锚（核销解锁分支走完），不写旗标锚。"""
        write_pending_writeoff(self.proot, {
            "run_id": "code-review-prior", "inserted": 1, "updated": 0,
            "at": "2026-11-15T00:00:00+00:00"})
        result = self._run(
            "code-review-912", ["src/a.py"], ["src/a.py"], flag=True)
        self.assertTrue(result.success)
        self.assertEqual(read_pending_writeoff(self.proot), {},
                         "覆盖完整 → 锚清除（旗标不落新锚）")

    def test_redispatch_run_never_overwrites_chain_root_anchor(self):
        """重派 run 收尾（即便旗标在册）：链根锚不覆写（防剃余丢根覆盖）。"""
        write_pending_writeoff(self.proot, {
            "run_id": "code-review-900", "inserted": 5, "updated": 2,
            "at": "2026-11-16T00:00:00+00:00"})
        result = self._run(
            "code-review-913", ["src/b.py"], ["src/b.py"], flag=True,
            redispatch_of="code-review-900")
        self.assertTrue(result.success)
        anchor = read_pending_writeoff(self.proot)
        self.assertEqual(anchor.get("run_id"), "code-review-900",
                         "锚仍指链根原 run，未被重派 run 覆写")
        self.assertEqual(anchor.get("inserted"), 5)


if __name__ == "__main__":
    unittest.main()
