"""add-impl-selfcheck-model-probe 单测（tasks 1.3 / 2.3 / 2.5 / 3.3 / 3.4）。

覆盖：
- 1.3 自检 CLI（``python3 -m core.agent_runner.result_gate --selfcheck``）：
  字符串数组 dispositions 被拦（明细含条目序号）、修复后 0 退出、合法文件
  零副作用、自检与 daemon 硬门同源判定一致；
- 2.3 模板链卫生：模板不含 ``maomaoai + deepseek-v4.1-flash`` 组合条目、
  含拒模型警示注释、YAML 仍可解析；
- 2.5 拒模型 failover：首选拒立即切链不重派、全链拒收场归因且派发器
  不同因重派、其余错误路径（5xx/超时/404 配额）回归不变；
- 3.3 零打回：full-suite 项缺失或 pending 不新增任何打回/失败终态；
- 3.4 回归双跑合并：写侧指纹 stamp、框架侧产物优先（结论不一致取产物）、
  指纹陈旧/存量无指纹回退自查值、双源皆无 pending、缺项零打回。
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent_runner import AgentRunner
from core.agent_runner import result_gate as rg
from core.agent_runner.provider_circuit import (
    MODEL_CHAIN_UNAVAILABLE_MARKER,
    ProviderCircuit,
)
from core.dashboard.data import parse_quality_gates
from core.dashboard.data.quality_gates import (
    _deliverable_guard_status,
    _full_suite_status,
    _run_gate_status,
)
from core.regression import current_repo_fingerprint, read_result, write_result
from tests.helpers import make_runner

REPO_ROOT = Path(__file__).resolve().parent.parent


# ── 公共夹具 ──────────────────────────────────────────────────────────

SPEC = "demo-spec"


def _mk_project(tmp_path: Path) -> Path:
    """最小 worktree 形态：spec/changes/<spec>/tasks.md（两条已勾选）。"""
    d = tmp_path / "spec" / "changes" / SPEC
    d.mkdir(parents=True, exist_ok=True)
    (d / "tasks.md").write_text(
        "# Tasks\n\n- [x] 1.1 first\n- [x] 1.2 second\n", encoding="utf-8")
    return tmp_path


def _valid_result(**extra) -> dict:
    data = {
        "status": "success",
        "spec": SPEC,
        "summary": "ok",
        "completed_tasks": ["1.1", "1.2"],
    }
    data.update(extra)
    return data


def _write_result_file(wt: Path, data: dict) -> Path:
    p = wt / ".fenix-run-result.json"
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def _mk_git_repo(tmp_path: Path) -> Path:
    """tmp git 仓库（指纹采集需要 HEAD/main 可解析）。"""
    root = tmp_path / "repo"
    root.mkdir()
    def git(*a):
        subprocess.run(["git", "-C", str(root), *a],
                       capture_output=True, check=True)
    git("init", "-q", "-b", "main", ".")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    (root / "f.txt").write_text("x", encoding="utf-8")
    git("add", ".")
    git("commit", "-qm", "init")
    return root


# ── 1.3 自检 CLI ──────────────────────────────────────────────────────


class TestSelfcheckCLI:
    """1.3：result_gate __main__ 自检 CLI 行为契约。"""

    def test_string_array_dispositions_rejected_with_index(self, tmp_path, capsys):
        """字符串数组 dispositions 被拦，违规明细含条目序号。"""
        wt = _mk_project(tmp_path)
        p = _write_result_file(wt, _valid_result(
            code_review={"dispositions": ["fixed", "fixed"]}))
        assert rg.main(["--selfcheck", str(p)]) == 1
        err = capsys.readouterr().err
        assert "dispositions[0]" in err
        assert "selfcheck FAIL" in err

    def test_object_dispositions_exit_zero(self, tmp_path, capsys):
        """修复为对象数组（含 reason 规则）后退出码 0。"""
        wt = _mk_project(tmp_path)
        p = _write_result_file(wt, _valid_result(code_review={"dispositions": [
            {"disposition": "fixed"},
            {"disposition": "deferred", "reason": "非空理由"},
        ]}))
        assert rg.main(["--selfcheck", str(p)]) == 0
        out = capsys.readouterr()
        assert "selfcheck PASS" in out.out
        assert out.err == ""

    def test_valid_file_zero_side_effects(self, tmp_path):
        """合法文件自检通过且对目标文件零副作用（字节级不变）。"""
        wt = _mk_project(tmp_path)
        p = _write_result_file(wt, _valid_result())
        before = p.read_bytes()
        assert rg.main(["--selfcheck", str(p)]) == 0
        assert p.read_bytes() == before

    def test_usage_errors_exit_two(self, tmp_path, capsys):
        """参数缺失/文件不存在 → 用法输出 + 非零码 2。"""
        assert rg.main([]) == 2
        assert rg.main(["--selfcheck", ""]) == 2
        assert rg.main(["--selfcheck",
                        str(tmp_path / "no-such-file.json")]) == 2
        assert "用法" in capsys.readouterr().err

    def test_same_source_as_daemon_gate(self, tmp_path, capsys):
        """自检与 daemon 硬门同源：CLI 违规明细 == 生产校验体返回值。"""
        wt = _mk_project(tmp_path)
        # completed_tasks 与 tasks.md 勾选集合不一致 → 任务完成度类失败
        p = _write_result_file(wt, _valid_result(completed_tasks=["1.1"]))
        shim = rg._SelfcheckShim(wt)
        gate_err = rg._check_impl_result_artifact(shim, SPEC, None, wt)
        assert gate_err is not None
        assert rg.main(["--selfcheck", str(p)]) == 1
        err = capsys.readouterr().err
        # CLI 逐字透出同一校验体的同一违规串（非复制逻辑的证据）
        assert gate_err in err


# ── 2.3 模板链卫生 ────────────────────────────────────────────────────


class TestConfigTemplateHygiene:
    """2.3：config.template.yaml 链卫生断言。"""

    def test_template_has_no_rejected_model_combo(self):
        """模板不含 maomaoai + deepseek-v4.1-flash 组合条目（评审实核固化）。"""
        text = (REPO_ROOT / ".fenix" / "config.template.yaml").read_text(
            encoding="utf-8")
        assert not ("maomaoai" in text and "deepseek-v4.1-flash" in text)

    def test_template_has_rejected_model_warning_comment(self):
        """models 注释示例处含拒模型警示注释与运维文档指引。"""
        text = (REPO_ROOT / ".fenix" / "config.template.yaml").read_text(
            encoding="utf-8")
        assert "拒模型" in text
        assert "13-model-chain-ops.md" in text

    def test_template_still_parses_as_yaml(self):
        import yaml
        data = yaml.safe_load(
            (REPO_ROOT / ".fenix" / "config.template.yaml").read_text(
                encoding="utf-8"))
        assert isinstance(data, dict)


# ── 2.5 拒模型 failover（runner 级）───────────────────────────────────

_CFG2 = {
    "llm": {"providers": [
        {"name": "pA", "baseurl": "https://a", "apikey": "k", "model": "m-bad"},
        {"name": "pB", "baseurl": "https://b", "apikey": "k", "model": "m-good"},
    ]},
    "agents": {"models": {"implementer": {"provider": ["pA", "pB"]}}},
}
_CFG1 = {
    "llm": {"providers": [
        {"name": "pA", "baseurl": "https://a", "apikey": "k", "model": "m-bad"},
    ]},
    "agents": {"models": {"implementer": {"provider": ["pA"]}}},
}


def _patch_exec(runner, tmp_path, calls, fail_models):
    """装 worktree/硬门/_run_claude 桩；fail_models 中的 model 抛对应错误。"""
    from unittest.mock import MagicMock as _MM
    wm = _MM()
    wm.create.return_value = tmp_path / "wt"
    runner.worktree_manager = wm
    runner._check_agent_result_artifact = _MM(return_value=None)

    def fake_run_claude(*a, **k):
        model = a[3] if len(a) > 3 else k.get("model_override")
        calls.append(model)
        exc = fail_models.get(model)
        if exc is not None:
            raise RuntimeError(exc)
        return ("ok", 1, "sess-1", {"input_tokens": 0, "output_tokens": 0,
                                    "cache_creation_input_tokens": 0,
                                    "cache_read_input_tokens": 0,
                                    "cost_usd": None})
    runner._run_claude = fake_run_claude


class TestUnrecognizedFailover:
    """2.5：拒模型链上 failover 与归因。"""

    def test_first_provider_rejected_switches_chain(self, tmp_path, monkeypatch):
        """首选拒 → 记 WARNING、沿链前进到次选成功；不整轮重派（单 run 内完成）。"""
        monkeypatch.setattr("time.sleep", lambda _s: None)
        runner = make_runner(tmp_path, _CFG2)
        calls = []
        _patch_exec(runner, tmp_path, calls, {
            "m-bad": "API error: HTTP 404 unrecognized_model m-bad"})
        res = runner.run_implementer(SPEC)
        assert res.success is True
        assert calls == ["m-bad", "m-good"]
        assert MODEL_CHAIN_UNAVAILABLE_MARKER not in (res.error or "")

    def test_full_chain_rejected_attributed_and_holds(self, tmp_path, monkeypatch):
        """全链（链尾）拒 → 归因含全链模型不可用语义；不再对必败链起进程。"""
        monkeypatch.setattr("time.sleep", lambda _s: None)
        runner = make_runner(tmp_path, _CFG1)
        calls = []
        _patch_exec(runner, tmp_path, calls, {
            "m-bad": "API error: HTTP 404 unrecognized_model m-bad"})
        res = runner.run_implementer(SPEC)
        assert res.success is False
        assert MODEL_CHAIN_UNAVAILABLE_MARKER in res.error
        assert "unrecognized_model" in res.error
        assert "pA" in res.error and "m-bad" in res.error
        assert calls == ["m-bad"]

    def test_5xx_still_switches_without_unrecognized_semantics(
            self, tmp_path, monkeypatch):
        """5xx 回归不变：走既有切换路径，归因不带全链不可用标记。"""
        monkeypatch.setattr("time.sleep", lambda _s: None)
        runner = make_runner(tmp_path, _CFG2)
        calls = []
        _patch_exec(runner, tmp_path, calls, {
            "m-bad": "HTTP 500 bad gateway"})
        res = runner.run_implementer(SPEC)
        assert res.success is True
        assert calls == ["m-bad", "m-good"]
        assert MODEL_CHAIN_UNAVAILABLE_MARKER not in (res.error or "")

    def test_quota_404_keeps_circuit_path_not_switch(self, tmp_path, monkeypatch):
        """404 配额类（无拒模型字样）回归不变：不切链、走既有熔断计数。"""
        monkeypatch.setattr("time.sleep", lambda _s: None)
        runner = make_runner(tmp_path, _CFG2)
        calls = []
        _patch_exec(runner, tmp_path, calls, {
            "m-bad": "API error: HTTP 404 quota exceeded"})
        res = runner.run_implementer(SPEC)
        assert res.success is False
        # 未切链：次选从未被尝试；无全链不可用归因（非拒模型语义）
        assert calls == ["m-bad"] * len(calls)
        assert "m-good" not in calls
        assert MODEL_CHAIN_UNAVAILABLE_MARKER not in (res.error or "")

    def test_timeout_and_conn_errors_still_transient(self):
        """超时/连接类回归不变：瞬断判定通道照常命中。"""
        assert ProviderCircuit.classify_transient_error(
            ["connection reset by peer"], 1, False) is True
        assert ProviderCircuit.classify_transient_error(
            ["API error: 504 gateway timeout"], 1, False) is True

    def test_classify_unrecognized_negative_cases(self):
        """拒模型判定负例：5xx/403 配额/空文本 MUST NOT 命中。"""
        assert AgentRunner.classify_unrecognized_model_error("HTTP 500") is False
        assert AgentRunner.classify_unrecognized_model_error(
            "API Error: 403 quota exceeded") is False
        assert AgentRunner.classify_unrecognized_model_error("") is False
        # 真子集关系：命中拒模型必命中切换类
        assert AgentRunner.classify_switch_error(
            "API error: HTTP 404 unrecognized_model x") is True
        assert AgentRunner.classify_switch_error(
            "Failed to authenticate. API Error: 403 No active subscription") is False


# ── 2.5 派发器不重派守卫 ──────────────────────────────────────────────


def _mk_engine(root: Path):
    """隔离 PMEngine（与 test_redispatch_loop_governance._make_engine 同范式）。"""
    from core.pm_engine import PMEngine
    from core.state_machine import StateMachine

    (root / ".fenix").mkdir(parents=True, exist_ok=True)
    logger = MagicMock()
    sm = StateMachine(root / ".fenix" / "STATE.md", logger)
    engine = PMEngine(sm, MagicMock(), {}, root, logger)
    engine._enqueue = MagicMock()
    engine._dispatcher._enqueue = MagicMock()
    engine._dispatcher._enqueue_front = MagicMock()
    engine._process_queue = MagicMock()
    engine._reconcile_impl_budget = MagicMock()
    engine._schedule_transient_recovery = MagicMock()
    # _schedule_transient_recovery 的实现体在 dispatcher mixin 上（dispatch 侧
    # 自有方法），快车道瞬断排程经 `self._schedule_transient_recovery` 解析到此
    engine._dispatcher._schedule_transient_recovery = MagicMock()
    return sm, engine


def _mk_inflight_spec(sm, root: Path, name: str = SPEC):
    d = root / "spec" / "changes" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "tasks.md").write_text("# Tasks\n\n- [ ] 1.1 do it\n", encoding="utf-8")
    sm.add_spec(name, {"priority": 5})
    sm.transition(name, "ready")
    sm.transition(name, "implementing")


_MARKER_ERROR = (
    f"{MODEL_CHAIN_UNAVAILABLE_MARKER} 全链模型不可用：provider 'pA' 拒绝模型 "
    f"'m-bad'（unrecognized_model，链尾无更多候选；本 run 已有 1 个链上候选被拒）"
)


class TestDispatcherNoRedispatch:
    """2.2/2.5：派发器对 [model-chain-unavailable] 归因不同因重派。"""

    def test_full_lane_holds_without_retry_or_redispatch(self, tmp_path):
        """full 车道：状态不翻转、retry 不递增、不入队重派，error 落盘。"""
        sm, engine = _mk_engine(tmp_path)
        _mk_inflight_spec(sm, tmp_path)
        engine._read_implementer_result = MagicMock(return_value=None)
        engine.agent_runner.run_implementer = MagicMock(return_value=SimpleNamespace(
            success=False, error=_MARKER_ERROR,
            run_id="impl-demo-spec-1-a1", branch=None, duration_seconds=1.0))
        engine.agent_runner.worktree_manager.find_implementer_worktree = (
            MagicMock(return_value=None))

        engine._run_agent_worker(SPEC, "implementer", 5)

        entry = sm.read_one(SPEC)
        assert entry.get("status") == "implementing"
        assert MODEL_CHAIN_UNAVAILABLE_MARKER in str(entry.get("error") or "")
        assert int(entry.get("_retry_count", 0) or 0) == 0
        engine._enqueue.assert_not_called()
        engine._dispatcher._schedule_transient_recovery.assert_not_called()

    def test_fast_track_lane_holds_without_retry_or_redispatch(self, tmp_path):
        """fast-track 车道对等：不重派、不增 retry、不排程瞬断恢复。"""
        sm, engine = _mk_engine(tmp_path)
        _mk_inflight_spec(sm, tmp_path)
        engine._read_implementer_result = MagicMock(return_value=None)

        engine._dispatcher._handle_fast_track_failure(SPEC, None, _MARKER_ERROR)

        entry = sm.read_one(SPEC)
        assert entry.get("status") == "implementing"
        assert MODEL_CHAIN_UNAVAILABLE_MARKER in str(entry.get("error") or "")
        assert int(entry.get("_retry_count", 0) or 0) == 0
        engine._schedule_transient_recovery.assert_not_called()
        engine._enqueue.assert_not_called()

    def test_fast_track_transient_still_schedules_recovery(self, tmp_path):
        """对照：瞬断归因照常排程延迟重派（守卫仅收窄拒模型归因）。"""
        sm, engine = _mk_engine(tmp_path)
        _mk_inflight_spec(sm, tmp_path)
        engine._read_implementer_result = MagicMock(return_value=None)

        engine._dispatcher._handle_fast_track_failure(
            SPEC, None, "[provider-transient] connection reset")

        engine._dispatcher._schedule_transient_recovery.assert_called_once_with(SPEC)


# ── 3.3 缺项零打回 ────────────────────────────────────────────────────


class TestFullSuiteZeroRejection:
    """3.3：full-suite 缺失或 pending 不新增任何打回/失败终态。"""

    def test_missing_key_is_pending_not_unknown(self):
        """键未写入（渐进落盘中间态）→ pending；源缺失永不产生 unknown。"""
        assert _run_gate_status(None, "full-suite", source_ok=True) == ("pending", "")

    def test_missing_and_pending_render_pending_in_synthesis(self, tmp_path):
        """quality-gates.json 可读但 full-suite 键缺（3.1 常态）→ pending；
        文件整体缺失 → unknown 既有语义（键名全集与状态枚举零变化）。"""
        out = parse_quality_gates(tmp_path, SPEC, entry={}, runs=[])
        item = next(it for it in out["items"] if it["id"] == "full-suite")
        assert item["status"] == "unknown"
        # 文件在场、键缺 → pending（零打回核心断言）
        vp = tmp_path / ".fenix" / "verify-progress" / SPEC
        vp.mkdir(parents=True, exist_ok=True)
        (vp / "quality-gates.json").write_text(json.dumps({
            "gates": {"frontend-build": {"status": "skipped",
                                         "reason": "无前端产物"}},
            "updated_at": "2026-09-22T00:00:00+00:00",
        }, ensure_ascii=False), encoding="utf-8")
        out2 = parse_quality_gates(tmp_path, SPEC, entry={}, runs=[])
        item2 = next(it for it in out2["items"] if it["id"] == "full-suite")
        assert item2["status"] == "pending"

    def test_deliverable_guard_ignores_full_suite(self):
        """交付物守卫不读 full-suite：implemented 态恒 passed，不受缺项影响。"""
        assert _deliverable_guard_status({"status": "implemented"})[0] == "passed"

    def test_soft_check_accepts_missing_and_pending_fullsuite(
            self, tmp_path, caplog):
        """result_gate 宽松对账：full-suite 键缺失/pending 均零拦截零告警。"""
        runner = make_runner(tmp_path)
        vp = tmp_path / ".fenix" / "verify-progress" / SPEC
        vp.mkdir(parents=True, exist_ok=True)
        # 仅 frontend-build 在场（full-suite 按 3.1 默认不写）
        (vp / "quality-gates.json").write_text(json.dumps({
            "gates": {"frontend-build": {"status": "skipped",
                                         "reason": "无前端产物"}},
            "updated_at": "2026-09-22T00:00:00+00:00",
        }, ensure_ascii=False), encoding="utf-8")
        assert rg._check_quality_gates_soft(runner, SPEC, tmp_path) is None
        assert not [r for r in caplog.records if r.levelname == "WARNING"]
        # full-suite 显式 pending 同样零告警
        (vp / "quality-gates.json").write_text(json.dumps({
            "gates": {"full-suite": {"status": "pending"}},
            "updated_at": "2026-09-22T00:00:00+00:00",
        }, ensure_ascii=False), encoding="utf-8")
        assert rg._check_quality_gates_soft(runner, SPEC, tmp_path) is None

    def test_selfcheck_passes_without_fullsuite_key(self, tmp_path):
        """自检 CLI：结果文件/quality-gates.json 均无 full-suite 键 → 0 退出。"""
        wt = _mk_project(tmp_path)
        vp = wt / ".fenix" / "verify-progress" / SPEC
        vp.mkdir(parents=True, exist_ok=True)
        (vp / "quality-gates.json").write_text(json.dumps({
            "gates": {"frontend-build": {"status": "skipped",
                                         "reason": "无前端产物"}},
            "updated_at": "2026-09-22T00:00:00+00:00",
        }, ensure_ascii=False), encoding="utf-8")
        p = _write_result_file(wt, _valid_result())
        assert rg.main(["--selfcheck", str(p)]) == 0


# ── 3.4 回归双跑合并 ──────────────────────────────────────────────────


class TestRegressionDualRunMerge:
    """3.4：框架侧回归产物指纹 stamp 与 full-suite 读侧双源优先级。"""

    def _mk_gates_file(self, root: Path, status: str) -> Path:
        vp = root / ".fenix" / "verify-progress" / SPEC
        vp.mkdir(parents=True, exist_ok=True)
        p = vp / "quality-gates.json"
        p.write_text(json.dumps({
            "gates": {"full-suite": {"status": status,
                                     "detail": "run 内自查值"}},
            "updated_at": "2026-09-22T00:00:00+00:00",
        }, ensure_ascii=False), encoding="utf-8")
        return p

    def _item(self, out: dict) -> dict:
        return next(it for it in out["items"] if it["id"] == "full-suite")

    def test_write_result_stamps_fingerprint(self, tmp_path):
        """写侧：write_result stamp 三元组指纹；不改写调用方 dict。"""
        root = _mk_git_repo(tmp_path)
        payload = {"status": "passed", "passed": 1, "failed": 0}
        write_result(root, payload)
        snap = read_result(root)
        assert snap["repo_fingerprint"] == current_repo_fingerprint(root)
        # 调用方 dict 未被改写
        assert "repo_fingerprint" not in payload

    def test_write_result_fail_open_without_git(self, tmp_path):
        """非 git 目录：指纹采集失败 fail-open——快照照常落盘、仅缺指纹字段。"""
        root = tmp_path / "plain"
        root.mkdir()
        write_result(root, {"status": "passed"})
        assert read_result(root)["status"] == "passed"
        assert "repo_fingerprint" not in read_result(root)

    def test_product_priority_on_conflict(self, tmp_path):
        """框架侧产物与 run 自查结论不一致 → 取产物（failed 压过自查 passed）。"""
        root = _mk_git_repo(tmp_path)
        self._mk_gates_file(root, "passed")
        write_result(root, {"status": "failed", "passed": 90, "failed": 10})
        out = parse_quality_gates(root, SPEC, entry={}, runs=[])
        item = self._item(out)
        assert item["status"] == "failed"
        assert "last-run.json" in item["detail"]

    def test_stale_fingerprint_falls_back_to_selfcheck(self, tmp_path):
        """HEAD 前进 → 指纹陈旧按不可见 → 回落 run 自查值。"""
        root = _mk_git_repo(tmp_path)
        self._mk_gates_file(root, "passed")
        write_result(root, {"status": "failed"})
        (root / "g.txt").write_text("y", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True,
                       capture_output=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "second"],
                       check=True, capture_output=True)
        item = self._item(parse_quality_gates(root, SPEC, entry={}, runs=[]))
        assert item["status"] == "passed"

    def test_legacy_snapshot_without_fingerprint_falls_back(self, tmp_path):
        """存量快照无指纹字段 → 不可见 → 回落自查值；自查键也缺 → pending。"""
        root = _mk_git_repo(tmp_path)
        self._mk_gates_file(root, "skipped")
        (root / ".fenix" / "regression").mkdir(parents=True, exist_ok=True)
        (root / ".fenix" / "regression" / "last-run.json").write_text(
            json.dumps({"status": "passed"}), encoding="utf-8")
        item = self._item(parse_quality_gates(root, SPEC, entry={}, runs=[]))
        assert item["status"] == "skipped"
        # 自查键亦缺（文件可读但无 full-suite）→ pending（缺项零打回）
        vp = root / ".fenix" / "verify-progress" / SPEC
        (vp / "quality-gates.json").write_text(json.dumps({
            "gates": {"frontend-build": {"status": "skipped",
                                         "reason": "无前端产物"}},
            "updated_at": "2026-09-22T00:00:00+00:00",
        }, ensure_ascii=False), encoding="utf-8")
        item2 = self._item(parse_quality_gates(root, SPEC, entry={}, runs=[]))
        assert item2["status"] == "pending"

    def test_both_sources_missing_pending(self, tmp_path):
        """双源皆无：文件可读键缺 → pending；直连单门合成同判。"""
        root = _mk_git_repo(tmp_path)
        vp = root / ".fenix" / "verify-progress" / SPEC
        vp.mkdir(parents=True, exist_ok=True)
        (vp / "quality-gates.json").write_text(json.dumps({
            "gates": {}, "updated_at": "2026-09-22T00:00:00+00:00",
        }, ensure_ascii=False), encoding="utf-8")
        item = self._item(parse_quality_gates(root, SPEC, entry={}, runs=[]))
        assert item["status"] == "pending"
        # 直连单门合成同判
        assert _full_suite_status(root, None, source_ok=True) == ("pending", "")

    def test_status_mapping_timeout_skipped_running(self, tmp_path):
        """产物状态映射：timeout→failed、skipped→skipped（附 reason）、
        running→running；映射外（parse_error）→ 本源异常回落。"""
        root = _mk_git_repo(tmp_path)
        vp = root / ".fenix" / "verify-progress" / SPEC
        vp.mkdir(parents=True, exist_ok=True)
        # 文件可读但无 full-suite 键：回落语义 = pending
        (vp / "quality-gates.json").write_text(json.dumps({
            "gates": {"frontend-build": {"status": "skipped",
                                         "reason": "无前端产物"}},
            "updated_at": "2026-09-22T00:00:00+00:00",
        }, ensure_ascii=False), encoding="utf-8")
        write_result(root, {"status": "timeout"})
        assert self._item(
            parse_quality_gates(root, SPEC, entry={}, runs=[]))["status"] == "failed"
        write_result(root, {"status": "skipped",
                            "reason": "full_suite_lock_not_acquired"})
        item = self._item(parse_quality_gates(root, SPEC, entry={}, runs=[]))
        assert item["status"] == "skipped"
        assert "full_suite_lock_not_acquired" in item["detail"]
        write_result(root, {"status": "parse_error", "reason": "xml broken"})
        assert self._item(
            parse_quality_gates(root, SPEC, entry={}, runs=[]))["status"] == "pending"


class TestAssertionEmptyStringSentinel:
    """验证修复轮 BUG-01：Assertion.expected 的「未设置」哨兵是 None 而非空串。

    空串是 json_path 等断言的合法期望值（如「quality_gates.items[0].detail
    为空串」）；曾以 ``str = ""`` 兼作哨兵，to_dict 按 ``!= ""`` 丢键，合法
    空串期望经 from_dict→to_dict 往返后被丢、运行时按 None 比较——合法断言
    确定性误判失败，且路径缺失时 None==None 误判通过。
    """

    def test_empty_string_expected_survives_roundtrip(self):
        """expected="" 是合法期望：from_dict→to_dict 往返保留键（丢键回归）。"""
        from core.verify_engine.scenarios import Assertion
        a = Assertion.from_dict(
            {"type": "json_path", "path": "quality_gates.items[0].detail",
             "expected": ""})
        assert a.expected == ""
        assert a.to_dict()["expected"] == ""

    def test_unset_expected_omitted_in_to_dict(self):
        """未设置 expected：属性为 None、to_dict 不输出该键（哨兵语义不变）。"""
        from core.verify_engine.scenarios import Assertion
        a = Assertion(type="element_visible", selector=".x")
        assert a.expected is None
        assert "expected" not in a.to_dict()

    def test_json_path_empty_expected_exact_semantics(self):
        """执行体级双向防线：actual="" vs expected="" 判过；
        路径缺失 actual=None vs expected="" 判败（None==None 误判通过防线）。"""
        import asyncio

        from core.verify_engine.api_assertions import ApiAssertionRunner
        runner = ApiAssertionRunner.__new__(ApiAssertionRunner)

        hit = asyncio.run(runner._assert_json_path(
            {"json": {"quality_gates": {"items": [{"detail": ""}]}}},
            {"type": "json_path", "path": "quality_gates.items[0].detail",
             "expected": ""}))
        assert hit["pass"] is True
        assert hit["expected"] == ""

        miss = asyncio.run(runner._assert_json_path(
            {"json": {"other": 1}},
            {"type": "json_path", "path": "quality_gates.items[0].detail",
             "expected": ""}))
        assert miss["pass"] is False
