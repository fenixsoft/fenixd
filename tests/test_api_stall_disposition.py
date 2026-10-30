"""tests/test_api_stall_disposition.py — evo-add-api-stall-disposition-closeout 4.1/4.2

覆盖：
- 4.1 终态 latency 透传：error 终态 run_metrics 的 latency_* 与过程指标一致
  （经 _metrics_latency 公共 helper 透传，task 1.2 链路）；成功终态透传不回归；
  无停滞 run 行为零变化（零样本回退语义不变）；_run_agent 抛出路径收尾
  latency 走零样本且不 NameError（车道层 _stall_latency 预初始化，task 1.1）。
- 4.2 升级信号与受控重派：warning-escalated（latency_max > 升级线）→
  api_round_stall_escalated 信号 1 条且同 run 去重（attempt/重试产物按 base
  run_id 归并）；「warning-escalated 且收尾 error」→ stall 意图登记（jsonl
  幂等标注 + 结果信封上交）/消费侧上限 1 次/与 ratelimit 意图互斥且双条件
  ratelimit 优先（登记侧 gate 顺序）/redispatch_of 指向原 run；「曾停滞但
  正常完成」→ 无信号无意图（design D3 触发条件收窄）。

run_code_review 收尾经最小 runner 替身驱动（对齐 test_code_review_salvage_
writeoff.py 的 _Runner 形态）；admin_monitor 侧经真实 AdminMonitor（store 落
tmp 项目）驱动；_execute_agent 延迟透传经最小 AgentRunner（对齐
test_run_metrics_persistence.py 形态）驱动。
"""

import json
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent_runner import AgentRunner
from core.agent_runner.latency import STALL_ROUND_ESCALATE_SECONDS
from core.agent_runner.maintenance_runs import (
    STALL_REDISPATCH_COOLDOWN_SECONDS,
    STALL_REDISPATCH_MAX,
    _register_stall_redispatch_intent,
    run_code_review,
)
from core.admin_monitor import (
    SIGNAL,
    SIGNAL_RECOMMENDATION,
    SIGNAL_SEVERITY,
    SPEC_LESS_STORED_SIGNAL_TYPES,
    STORED_SIGNAL_TYPES,
    AdminMonitor,
    _api_stall_base_run_id,
    _read_terminal_run_metrics,
)
from core.admin_store import AdminStore
from core.logger import Logger

# 停滞升级样本（warning-escalated：max > STALL_ROUND_ESCALATE_SECONDS=300）
ESCALATED_STATS = {"rounds": 4, "stalls": 2, "max": 420.0}
ZERO_SAMPLE_STATS = {"rounds": 0, "stalls": 0, "max": None}

USAGE_WITH_COST = {
    "input_tokens": 120,
    "output_tokens": 80,
    "cache_creation_input_tokens": 10,
    "cache_read_input_tokens": 20,
    "cost_usd": 0.005,
    "unobserved": False,
}


# ── helpers ──────────────────────────────────────────────────────────────────

def _mk_repo() -> Path:
    root = Path(tempfile.mkdtemp(prefix="stall-closeout-"))
    (root / ".fenix" / "code-review").mkdir(parents=True, exist_ok=True)
    (root / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
    return root


class _RecLogger:
    """记录式 logger（assert 日志文案用）。"""

    def __init__(self):
        self.records = []

    def debug(self, tag, message):
        self.records.append(f"DEBUG {tag} {message}")

    def info(self, tag, message):
        self.records.append(f"INFO {tag} {message}")

    def warning(self, tag, message):
        self.records.append(f"WARNING {tag} {message}")

    def error(self, tag, message):
        self.records.append(f"ERROR {tag} {message}")

    def has(self, text):
        return any(text in m for m in self.records)


class _RecExecutor:
    """同步记录式 executor 替身（jobs 列表存 (fn,)，测试手动驱动）。"""

    def __init__(self):
        self.jobs = []

    def submit(self, fn, *a, **k):
        self.jobs.append((fn, a, k))


def _read_metric_rows(tmp_path: Path, terminal: str | None = None) -> list[dict]:
    """从 fenixd.log 读取 metric_type=run_metrics 结构化行（可按 terminal 过滤）。"""
    log_file = tmp_path / ".fenix" / "logs" / "fenixd.log"
    if not log_file.exists():
        return []
    results = []
    for raw in log_file.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            entry = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        ctx = entry.get("context") or {}
        if ctx.get("metric_type") != "run_metrics":
            continue
        if terminal is not None and ctx.get("terminal") != terminal:
            continue
        results.append(ctx)
    return results


def _make_runner_with_logger(tmp_path: Path, config: dict | None = None):
    """构造带真实 Logger 的最小 AgentRunner（对齐 test_run_metrics_persistence）。"""
    runner = AgentRunner.__new__(AgentRunner)
    runner.config = config or {}
    runner.worktree_manager = None
    runner.state_machine = None
    runner.project_root = tmp_path
    runner.logger = Logger(tmp_path / ".fenix" / "logs", "DEBUG")
    runner._running_agents = {}
    runner._daily_run_count = 0
    runner._provider_circuit._daily_reset_date = None
    runner._provider_circuit._daily_provider_attempts = {}
    runner._provider_circuit._daily_provider_warned = {}
    runner._provider_circuit.provider_circuits = {}
    runner.__dict__["_v2_server_instance"] = MagicMock()
    runner._v2_server._v2_inject_env.return_value = {}
    runner.__dict__["_token_accountant_instance"] = MagicMock()
    runner._build_prompt = lambda *a, **k: "test prompt"
    (tmp_path / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
    return runner


def _write_run_metrics_row(runs_dir: Path, run_id: str, latency_max,
                           agent_type="code-review") -> Path:
    """写一份含终态 run_metrics 行的 run jsonl（2.1 检测数据源形态）。"""
    runs_dir.mkdir(parents=True, exist_ok=True)
    f = runs_dir / f"{run_id}.jsonl"
    rows = [
        {"type": "run_start", "run_id": run_id},
        {"type": "assistant", "message": {"content": []}},
        {"type": "run_metrics", "run_id": run_id, "agent_type": agent_type,
         "terminal": "error", "turns": 40,
         "latency_rounds": 5, "latency_stalls": 2, "latency_max": latency_max},
        {"type": "error", "error": "gateway timeout"},
    ]
    f.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8")
    return f


def _mk_monitor(root: Path, logger=None) -> AdminMonitor:
    """构造真实 AdminMonitor（store 落 tmp 项目，agent_runner=None）。"""
    return AdminMonitor(
        {},
        type("_FakeSM", (), {"read_all": lambda s: {},
                             "read_one": lambda s, n: None})(),
        root,
        logger or _RecLogger(),
        store=AdminStore(root, _RecLogger()),
        agent_runner=None,
    )


def _stall_signals(store: AdminStore) -> list[dict]:
    return [r for r in store.read_records()
            if r.get("kind") == SIGNAL
            and r.get("signal_type") == "api_round_stall_escalated"]


class _CloseoutRunner:
    """run_code_review 收尾链路的最小 runner 替身（对齐 salvage _Runner 形态）。

    die 场景：_run_agent 写完产物后抛出（run_ok=False + claude_error，429
    归因场景）；return_failed 场景：_run_agent 正常返回（携带 stall stats）
    但**不写产物** → 产物硬门拦截（run_ok=False、无 429 归因，stall 场景）；
    success 场景：写产物 + 正常返回（run_ok=True，「曾停滞但正常完成」）。
    """

    def __init__(self, proot, run_id, out_rows=None, mode="return_failed",
                 stats=None, ratelimit_intent=None):
        self.project_root = Path(proot)
        self.logger = _RecLogger()
        self.config = {}
        self._run_id = run_id
        self._out_rows = out_rows or []
        self._mode = mode
        self._stats = stats if stats is not None else ESCALATED_STATS
        self._ratelimit_intent = ratelimit_intent
        self.ratelimit_calls = []

    def _unique_code_review_run_id(self):
        return self._run_id

    def _build_prompt(self, run_id, agent_type, detail=None):
        return "prompt"

    def _get_agent_model_assignment(self, name):
        return None

    def _get_admin_model(self):
        return "test-model"

    def _write_out(self):
        path = self.project_root / ".fenix" / "code-review" / f"out-{self._run_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        content = "".join(
            json.dumps(r, ensure_ascii=False) + "\n" for r in self._out_rows)
        path.write_text(content, encoding="utf-8")

    def _run_agent(self, prompt, root, run_id, model_override, env_overrides,
                   max_turns=None, spec_name=None, agent_type=None,
                   task_progress_snapshot=None):
        if self._mode in ("die", "success"):
            self._write_out()
        if self._mode == "die":
            raise RuntimeError(
                "API Error: Request rejected (429) · rate limit exceeded")
        # return_failed / success：正常返回 5 元组（末位 stall stats）
        return ("output", 3, "session", {}, dict(self._stats))

    def _ratelimit_redispatch_on_terminal(self, run_id, error, provider_name,
                                          spec_name, api_error_status=None,
                                          result_text=""):
        self.ratelimit_calls.append({"run_id": run_id, "error": error})
        return dict(self._ratelimit_intent) if self._ratelimit_intent else None

    def _extract_usage_info(self, x):
        return {}

    def _accumulate_code_review_tokens(self, run_id, usage):
        return None

    def _read_code_review_out(self, project_root, run_id):
        from core.agent_runner import maintenance_runs

        return maintenance_runs._read_code_review_out(self, project_root, run_id)


# ═════════════════════════════════════════════════════════════════════════════
# 4.1 终态 latency 透传
# ═════════════════════════════════════════════════════════════════════════════

class TestMetricsLatencyHelper(unittest.TestCase):
    """_metrics_latency 公共透传 helper（task 1.2 单源）。"""

    def test_dict_passthrough_identity(self):
        stats = {"rounds": 2, "stalls": 1, "max": 350.0}
        from core.agent_runner.runner import _metrics_latency

        self.assertIs(_metrics_latency(stats), stats)

    def test_non_dict_falls_to_none(self):
        from core.agent_runner.runner import _metrics_latency

        self.assertIsNone(_metrics_latency(None))
        self.assertIsNone(_metrics_latency("lag"))
        self.assertIsNone(_metrics_latency([1, 2]))
        self.assertIsNone(_metrics_latency(42))


class TestTerminalLatencyPassthrough(unittest.TestCase):
    """_execute_agent 终态（含非成功终态）run_metrics 行 latency 透传（4.1）。"""

    def _mk_wt_runner(self, tmp_path):
        runner = _make_runner_with_logger(tmp_path, {"agents": {"max_retries": 1}})
        wt = tmp_path / "wt"
        wt.mkdir(parents=True)
        runner.worktree_manager = MagicMock()
        runner.worktree_manager.create.return_value = wt
        runner.worktree_manager.get_branch_name.return_value = "fenix/spec-x"
        runner.worktree_manager.cleanup.return_value = None
        return runner

    def test_error_terminal_latency_matches_process_metrics(self, ):
        """返回但产物硬门拒绝（error 终态）→ 失败行 latency_* 与过程指标一致。

        _run_agent 正常返回携带 escalated stats（rounds=4/stalls=2/max=420），
        spec-review 车道产物缺失触发 AgentArtifactGateError → 原地退避耗尽 →
        attempt 层耗尽 → _exhausted_result 经 _metrics_latency 透传 stats。
        """
        tmp_path = Path(tempfile.mkdtemp(prefix="stall-err-"))
        try:
            runner = self._mk_wt_runner(tmp_path)
            runner._run_agent = lambda *a, **k: (
                "output", 2, "sess-e", dict(USAGE_WITH_COST), dict(ESCALATED_STATS))
            runner.classify_transient_error = lambda *a, **k: False
            with patch("time.sleep", lambda s: None):
                result = runner._execute_agent("spec-x", "spec-review", "run-err1")
            runner.logger.close()

            self.assertFalse(result.success)
            rows = _read_metric_rows(tmp_path, terminal="failure")
            self.assertTrue(rows, "失败收尾应产生 terminal=failure run_metrics 行")
            m = rows[-1]
            self.assertEqual(m["run_id"], "run-err1")
            # latency_* 与过程指标（_run_agent 返回 stats）逐字段一致
            self.assertEqual(m["latency_rounds"], ESCALATED_STATS["rounds"])
            self.assertEqual(m["latency_stalls"], ESCALATED_STATS["stalls"])
            self.assertEqual(m["latency_max"], ESCALATED_STATS["max"])
        finally:
            shutil.rmtree(str(tmp_path), ignore_errors=True)

    def test_success_terminal_passthrough_no_regression(self):
        """成功终态透传不回归：成功行 latency_* 继续反映过程指标。"""
        tmp_path = Path(tempfile.mkdtemp(prefix="stall-ok-"))
        try:
            runner = self._mk_wt_runner(tmp_path)
            runner._run_agent = lambda *a, **k: (
                "output", 3, "sess-ok", dict(USAGE_WITH_COST), dict(ESCALATED_STATS))
            result = runner._execute_agent("spec-x", "verifier", "run-ok1")
            runner.logger.close()

            self.assertTrue(result.success)
            rows = _read_metric_rows(tmp_path, terminal="success")
            self.assertTrue(rows)
            m = rows[-1]
            self.assertEqual(m["latency_rounds"], 4)
            self.assertEqual(m["latency_stalls"], 2)
            self.assertEqual(m["latency_max"], 420.0)
        finally:
            shutil.rmtree(str(tmp_path), ignore_errors=True)

    def test_no_stall_run_zero_sample_unchanged(self):
        """无停滞 run（零样本 stats）→ 行为与既有零样本回退逐字段一致。"""
        tmp_path = Path(tempfile.mkdtemp(prefix="stall-zero-"))
        try:
            runner = self._mk_wt_runner(tmp_path)
            runner._run_agent = lambda *a, **k: (
                "output", 3, "sess-z", dict(USAGE_WITH_COST), dict(ZERO_SAMPLE_STATS))
            result = runner._execute_agent("spec-x", "verifier", "run-zero1")
            runner.logger.close()

            self.assertTrue(result.success)
            rows = _read_metric_rows(tmp_path, terminal="success")
            self.assertTrue(rows)
            m = rows[-1]
            self.assertEqual(m["latency_rounds"], 0)
            self.assertEqual(m["latency_stalls"], 0)
            self.assertIsNone(m["latency_max"])
        finally:
            shutil.rmtree(str(tmp_path), ignore_errors=True)

    def test_raise_path_zero_sample_without_nameerror(self):
        """_run_agent 抛出路径 → 失败行走零样本回退（0/0/None）且不 NameError。"""
        tmp_path = Path(tempfile.mkdtemp(prefix="stall-raise-"))
        try:
            runner = self._mk_wt_runner(tmp_path)
            runner.classify_transient_error = lambda *a, **k: False

            def _boom(*a, **k):
                exc = RuntimeError("claude CLI failed: Exit code: 1")
                exc.stderr_lines = ["error"]
                exc.exit_code = 1
                exc.has_result = False
                raise exc

            runner._run_agent = _boom
            with patch("time.sleep", lambda s: None):
                result = runner._execute_agent("spec-x", "verifier", "run-raise1")
            runner.logger.close()

            self.assertFalse(result.success)
            rows = _read_metric_rows(tmp_path, terminal="failure")
            self.assertTrue(rows)
            m = rows[-1]
            self.assertEqual(m["run_id"], "run-raise1")
            self.assertEqual(m["latency_rounds"], 0)
            self.assertEqual(m["latency_stalls"], 0)
            self.assertIsNone(m["latency_max"])
        finally:
            shutil.rmtree(str(tmp_path), ignore_errors=True)


# ═════════════════════════════════════════════════════════════════════════════
# 4.2a 升级信号检测面（api_round_stall_escalated）
# ═════════════════════════════════════════════════════════════════════════════

class TestStallEscalationSignal(unittest.TestCase):
    """AdminMonitor._check_api_round_stall_escalated（task 2.1）。"""

    def setUp(self):
        self.proot = _mk_repo()

    def tearDown(self):
        shutil.rmtree(str(self.proot), ignore_errors=True)

    def test_signal_type_registered_in_stored_types(self):
        """信号类型进 STORED_SIGNAL_TYPES/SPEC_LESS/severity/recommendation
        登记（未收录则记录落 store 后无人摄取——历史同款落空模式）。"""
        self.assertIn("api_round_stall_escalated", STORED_SIGNAL_TYPES)
        self.assertIn("api_round_stall_escalated", SPEC_LESS_STORED_SIGNAL_TYPES)
        self.assertEqual(SIGNAL_SEVERITY.get("api_round_stall_escalated"), "major")
        self.assertTrue(SIGNAL_RECOMMENDATION.get("api_round_stall_escalated"))

    def test_escalated_run_writes_one_signal_and_dedups(self):
        """升级线以上 → 1 条 major 信号；同 run 复检去重（仍 1 条）。"""
        runs_dir = self.proot / ".fenix" / "runs"
        _write_run_metrics_row(runs_dir, "code-review-x", 420.5)
        mon = _mk_monitor(self.proot)

        mon._check_api_round_stall_escalated()
        signals = _stall_signals(mon.store)
        self.assertEqual(len(signals), 1, "升级 run 应恰落 1 条信号")
        rec = signals[0]
        self.assertEqual(rec["severity"], "major")
        self.assertIsNone(rec["spec"])
        self.assertIn("code-review-x", rec["description"])
        self.assertIn("420", rec["description"])
        self.assertIn("项目名=", rec["evidence"])

        # 同 run 复检：merge 去重（dedup 键 spec=null + base run_id 进 hash 位）
        mon._check_api_round_stall_escalated()
        self.assertEqual(len(_stall_signals(mon.store)), 1, "同 run 至多一条")

    def test_below_threshold_no_signal(self):
        """未到升级线（latency_max ≤ 300）→ 无信号。"""
        _write_run_metrics_row(self.proot / ".fenix" / "runs", "code-review-lo", 120.0)
        mon = _mk_monitor(self.proot)
        mon._check_api_round_stall_escalated()
        self.assertEqual(_stall_signals(mon.store), [])

    def test_zero_sample_row_does_not_trigger(self):
        """dsh 投影 0 样本行（latency_max=None）天然不触发（属 86de1c7071b6）。"""
        _write_run_metrics_row(self.proot / ".fenix" / "runs", "code-review-z", None)
        mon = _mk_monitor(self.proot)
        mon._check_api_round_stall_escalated()
        mon._check_api_round_stall_escalated()
        self.assertEqual(_stall_signals(mon.store), [])

    def test_attempt_retry_files_dedup_by_base_run_id(self):
        """attempt/原地重试产物（-a<n>/-r<n>）各自成文件 → 按 base run_id 归并
        单条信号（dedup 键归一）。"""
        runs_dir = self.proot / ".fenix" / "runs"
        _write_run_metrics_row(runs_dir, "code-review-y-a1", 500.0)
        _write_run_metrics_row(runs_dir, "code-review-y-a1-r2", 610.0)
        mon = _mk_monitor(self.proot)
        mon._check_api_round_stall_escalated()
        signals = _stall_signals(mon.store)
        self.assertEqual(len(signals), 1, "同 run（含全部 attempt/重试产物）至多一条")
        import hashlib

        expected_hash = hashlib.sha1(
            f"api-stall:code-review-y".encode("utf-8")).hexdigest()
        self.assertEqual(signals[0].get("status_hash"), expected_hash)


class TestStallSignalHelpers(unittest.TestCase):
    """模块级 helper 单测（_api_stall_base_run_id / _read_terminal_run_metrics）。"""

    def test_base_run_id_strips_suffixes(self):
        self.assertEqual(_api_stall_base_run_id("code-review-x"), "code-review-x")
        self.assertEqual(_api_stall_base_run_id("code-review-x-a1"), "code-review-x")
        self.assertEqual(
            _api_stall_base_run_id("code-review-x-a1-r2"), "code-review-x")
        self.assertEqual(_api_stall_base_run_id("impl-evo-a-1700000000"), "impl-evo-a-1700000000")

    def test_read_terminal_run_metrics_last_row_wins(self):
        tmp = Path(tempfile.mkdtemp(prefix="stall-read-"))
        try:
            f = tmp / "code-review-m.jsonl"
            rows = [
                {"type": "run_metrics", "run_id": "code-review-m",
                 "latency_max": 100.0, "latency_rounds": 1, "latency_stalls": 0},
                {"type": "assistant", "message": {}},
                {"type": "run_metrics", "run_id": "code-review-m",
                 "latency_max": 480.0, "latency_rounds": 6, "latency_stalls": 3},
            ]
            f.write_text(
                "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            row = _read_terminal_run_metrics(f)
            self.assertEqual(row["latency_max"], 480.0, "取窗口内最近一条")

            # 无 run_metrics 行 → None（调用方不标记 seen）
            g = tmp / "code-review-n.jsonl"
            g.write_text(json.dumps({"type": "assistant"}) + "\n", encoding="utf-8")
            self.assertIsNone(_read_terminal_run_metrics(g))

            # 嵌入式伪命中行（代码/回显）不误判
            h = tmp / "code-review-o.jsonl"
            h.write_text(
                json.dumps({"type": "assistant",
                            "text": '{"type": "run_metrics"}'}) + "\n",
                encoding="utf-8")
            self.assertIsNone(_read_terminal_run_metrics(h))
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)


# ═════════════════════════════════════════════════════════════════════════════
# 4.2b stall 意图登记（车道侧 helper + run_code_review 收尾 gate）
# ═════════════════════════════════════════════════════════════════════════════

class TestStallRedispatchIntent(unittest.TestCase):
    """_register_stall_redispatch_intent（task 2.3 登记侧）。"""

    def setUp(self):
        self.proot = _mk_repo()
        self.run_file = self.proot / ".fenix" / "runs" / "code-review-i1.jsonl"
        self.run_file.write_text(
            json.dumps({"type": "run_start", "run_id": "code-review-i1"}) + "\n",
            encoding="utf-8")
        self.runner = MagicMock()
        self.runner.project_root = self.proot
        self.runner.logger = _RecLogger()

    def tearDown(self):
        shutil.rmtree(str(self.proot), ignore_errors=True)

    def _register(self):
        return _register_stall_redispatch_intent(
            self.runner, run_id="code-review-i1",
            provider_name="inferaiapi.com", latency_max=420.0)

    def test_registers_intent_with_jsonl_marker(self):
        intent = self._register()
        self.assertIsNotNone(intent)
        self.assertEqual(intent["reason"], "api stall escalated")
        self.assertEqual(intent["provider"], "inferaiapi.com")
        self.assertEqual(intent["run_id"], "code-review-i1")
        self.assertEqual(intent["latency_max_seconds"], 420.0)
        self.assertEqual(intent["max_redispatches"], STALL_REDISPATCH_MAX)
        # 冷却到期时刻须在未来（消费侧据此延迟投递），冷却时长 600s 单源
        self.assertEqual(STALL_REDISPATCH_COOLDOWN_SECONDS, 600.0)
        self.assertEqual(STALL_REDISPATCH_MAX, 1)
        self.assertGreater(intent["cooldown_until_epoch"], time.time())
        # run jsonl 标注重派缘由（type=stall_redispatch）
        rows = [json.loads(l) for l in
                self.run_file.read_text(encoding="utf-8").splitlines()]
        markers = [r for r in rows if r.get("type") == "stall_redispatch"]
        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0]["run_id"], "code-review-i1")
        self.assertEqual(markers[0]["cooldown_until_epoch"],
                         intent["cooldown_until_epoch"])

    def test_duplicate_intent_same_run_is_idempotent(self):
        first = self._register()
        self.assertIsNotNone(first)
        second = self._register()
        self.assertIsNone(second, "同 run 已登记 → 不重复登记")
        rows = [json.loads(l) for l in
                self.run_file.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(
            sum(1 for r in rows if r.get("type") == "stall_redispatch"), 1)

    def test_pseudo_hit_row_does_not_fool_idempotency(self):
        """嵌入式伪命中行（代码/回显携带 marker 字面量）不误判「已登记」。"""
        self.run_file.write_text(
            json.dumps({"type": "assistant",
                        "text": '{"type": "stall_redispatch"}'}) + "\n",
            encoding="utf-8")
        self.assertIsNotNone(self._register())


class TestStallIntentCloseoutGate(unittest.TestCase):
    """run_code_review 收尾 gate（「warning-escalated 且收尾 error」才登记，
    与 ratelimit 意图互斥且双条件 ratelimit 优先；task 2.3）。"""

    def setUp(self):
        self.proot = _mk_repo()

    def tearDown(self):
        shutil.rmtree(str(self.proot), ignore_errors=True)

    def test_escalated_error_run_registers_stall_intent(self):
        """停滞升级 + 产物硬门拒绝（收尾 error、无 429 归因）→ stall 意图登记。"""
        runner = _CloseoutRunner(self.proot, "code-review-2000",
                                 mode="return_failed")  # 返回但不写产物
        result = run_code_review(
            runner, ["src/a.py"], review_kind="scheduled",
            window_start=None, scope="full")
        self.assertFalse(result.success)
        self.assertIsNotNone(result.stall_redispatch, "停滞致败应登记 stall 意图")
        self.assertIsNone(result.ratelimit_redispatch, "非 429 失败不应登记 ratelimit")
        intent = result.stall_redispatch
        self.assertEqual(intent["run_id"], "code-review-2000")
        self.assertEqual(intent["latency_max_seconds"], 420.0)
        self.assertTrue(runner.logger.has("Stall redispatch intent registered"))

    def test_double_condition_ratelimit_wins_stall_none(self):
        """双条件（429 归因 + 停滞升级）→ ratelimit 优先，stall 意图 None。"""
        runner = _CloseoutRunner(
            self.proot, "code-review-2001", mode="die",
            ratelimit_intent={"reason": "429 ratelimit", "run_id": "code-review-2001"})
        result = run_code_review(
            runner, ["src/a.py"], review_kind="scheduled",
            window_start=None, scope="full")
        self.assertFalse(result.success)
        self.assertIsNotNone(result.ratelimit_redispatch)
        self.assertIsNone(result.stall_redispatch,
                          "双条件 ratelimit 优先（429 归因明确，停滞归因是假设）")
        self.assertEqual(len(runner.ratelimit_calls), 1)

    def test_normal_429_error_no_stall_intent(self):
        """429 致败但无停滞升级（raise 路径 stall stats 缺失）→ 仅 ratelimit
        意图（互斥 gate 的天然单边）。"""
        runner = _CloseoutRunner(
            self.proot, "code-review-2002", mode="die",
            ratelimit_intent={"reason": "429 ratelimit", "run_id": "code-review-2002"})
        result = run_code_review(
            runner, ["src/a.py"], review_kind="scheduled",
            window_start=None, scope="full")
        self.assertFalse(result.success)
        self.assertIsNotNone(result.ratelimit_redispatch)
        self.assertIsNone(result.stall_redispatch)

    def test_stalled_but_successful_no_intent(self):
        """「曾停滞但正常完成」→ 无意图（design D3：成功的 run 重试是纯浪费）。"""
        out_rows = [{"file": "src/a.py",
                     "findings": [{"category": "correctness", "title": "bug",
                                   "severity": "major", "description": "d",
                                   "suggestion": "s"}]}]
        runner = _CloseoutRunner(self.proot, "code-review-2003",
                                 out_rows=out_rows, mode="success")
        result = run_code_review(
            runner, ["src/a.py"], review_kind="scheduled",
            window_start=None, scope="full")
        self.assertTrue(result.success)
        self.assertIsNone(result.stall_redispatch, "成功 run MUST NOT 登记重派")
        self.assertIsNone(result.ratelimit_redispatch)
        self.assertEqual(runner.ratelimit_calls, [])

    def test_below_threshold_error_no_stall_intent(self):
        """收尾 error 但未到升级线（max ≤ 300）→ 无 stall 意图。"""
        runner = _CloseoutRunner(self.proot, "code-review-2004", mode="return_failed",
                                 stats={"rounds": 2, "stalls": 1, "max": 240.0})
        result = run_code_review(
            runner, ["src/a.py"], review_kind="scheduled",
            window_start=None, scope="full")
        self.assertFalse(result.success)
        self.assertIsNone(result.stall_redispatch)


# ═════════════════════════════════════════════════════════════════════════════
# 4.2c stall 意图消费（admin_monitor 排程上限/互斥 Timer + redispatch_of 链）
# ═════════════════════════════════════════════════════════════════════════════

def _stall_intent(run_id, cooldown_offset=600.0):
    return {
        "reason": "api stall escalated",
        "provider": "inferaiapi.com",
        "run_id": run_id,
        "latency_max_seconds": 420.0,
        "cooldown_until": "2026-01-01T00:00:00+00:00",
        "cooldown_until_epoch": time.time() + cooldown_offset,
        "max_redispatches": 1,
    }


class TestStallRedispatchConsume(unittest.TestCase):
    """_schedule_stall_redispatch / _consume_stall_redispatch（task 2.4）。"""

    def setUp(self):
        self.proot = _mk_repo()
        self.monitor = AdminMonitor(
            {}, type("_FakeSM", (), {"read_all": lambda s: {},
                                     "read_one": lambda s, n: None})(),
            self.proot, _RecLogger(),
            store=AdminStore(self.proot, _RecLogger()),
            agent_runner=MagicMock(),
            code_review_executor=None,
        )
        # 夜间静默窗判定固定不命中（测试不依赖时钟落点）
        self.monitor._code_review_night_window_defer = lambda: None

    def tearDown(self):
        timer = self.monitor._code_review_redispatch_timer
        if timer is not None:
            timer.cancel()
        shutil.rmtree(str(self.proot), ignore_errors=True)

    def test_schedule_stall_cap_one_per_lifetime(self):
        """上限 1 次/monitor 生命周期：第二次登记跳过并记 WARNING。"""
        self.monitor._schedule_stall_redispatch(
            manifest=["a.py"], review_kind="scheduled", window_start=None,
            scope="full", intent=_stall_intent("code-review-r1"))
        self.assertEqual(self.monitor._code_review_stall_redispatches, 1)
        timer1 = self.monitor._code_review_redispatch_timer
        self.assertIsNotNone(timer1)

        self.monitor._schedule_stall_redispatch(
            manifest=["a.py"], review_kind="scheduled", window_start=None,
            scope="full", intent=_stall_intent("code-review-r2"))
        self.assertEqual(self.monitor._code_review_stall_redispatches, 1,
                         "第二次登记不占额（上限 1）")
        self.assertIs(self.monitor._code_review_redispatch_timer, timer1,
                      "重复意图不重复排队（单 Timer 守卫）")
        self.assertTrue(self.monitor.logger.has("已达上限"))

    def test_schedule_rejects_invalid_cooldown(self):
        """cooldown_until_epoch 缺失/非法 → 放弃排程、不占额、不排 Timer。"""
        bad = _stall_intent("code-review-bad")
        bad["cooldown_until_epoch"] = None
        self.monitor._schedule_stall_redispatch(
            manifest=["a.py"], review_kind="scheduled", window_start=None,
            scope="full", intent=bad)
        self.assertEqual(self.monitor._code_review_stall_redispatches, 0)
        self.assertIsNone(self.monitor._code_review_redispatch_timer)
        self.assertTrue(self.monitor.logger.has("无合法"))

    def test_consume_stall_redispatches_with_redispatch_of(self):
        """stall 消费回调 → 以原 manifest 复调并携带 redispatch_of 指向原 run。"""
        self.monitor._consume_stall_redispatch(
            ["a.py", "b.py"], "scheduled", None, "full", "code-review-r1")
        kwargs = self.monitor.agent_runner.run_code_review.call_args.kwargs
        self.assertEqual(kwargs.get("redispatch_of"), "code-review-r1",
                         "redispatch_of 链路指向原 run")
        self.assertEqual(kwargs.get("review_kind"), "scheduled")
        # 消费后单飞复位
        self.assertFalse(self.monitor._code_review_in_flight)

    def test_stall_and_ratelimit_share_single_timer_handle(self):
        """stall 与 ratelimit 排程共用同一 Timer 句柄（同一时刻至多一个待发）。"""
        self.monitor._schedule_stall_redispatch(
            manifest=["a.py"], review_kind="scheduled", window_start=None,
            scope="full", intent=_stall_intent("code-review-s1"))
        stall_timer = self.monitor._code_review_redispatch_timer
        self.assertIsNotNone(stall_timer)
        # 429 侧排程此刻命中「已有待发重派 Timer」守卫
        self.monitor._schedule_ratelimit_redispatch(
            manifest=["a.py"], review_kind="scheduled", window_start=None,
            scope="full", intent=_stall_intent("code-review-s2"))
        self.assertIs(self.monitor._code_review_redispatch_timer, stall_timer)
        self.assertTrue(self.monitor.logger.has("已有待发重派 Timer"))


class TestCheckpointWorkerStallDispatch(unittest.TestCase):
    """周期审查检查点 _worker 按意图种类分派（task 2.4 收尾分发）。"""

    def setUp(self):
        self.proot = _mk_repo()

    def tearDown(self):
        shutil.rmtree(str(self.proot), ignore_errors=True)

    def _drive(self, run_result):
        mon = AdminMonitor(
            {"admin": {"code_review": {
                "enabled": True, "run_at": "00:00", "scope": "full"}}},
            type("_FakeSM", (), {"read_all": lambda s: {},
                                 "read_one": lambda s, n: None})(),
            self.proot, _RecLogger(),
            store=AdminStore(self.proot, _RecLogger()),
            agent_runner=MagicMock(),
            code_review_executor=None,
        )
        mon._code_review_night_window_defer_note = lambda: None
        calls = {"stall": [], "ratelimit": []}
        mon._schedule_stall_redispatch = lambda **kw: calls["stall"].append(kw)
        mon._schedule_ratelimit_redispatch = (
            lambda **kw: calls["ratelimit"].append(kw))
        mon.agent_runner.run_code_review.return_value = run_result
        mon.agent_runner._running_agents = {}
        with patch("core.code_review.read_code_review_state", lambda p: {}), \
                patch("core.code_review.save_code_review_state", lambda p, d: None), \
                patch("core.code_review.collect_manifest",
                      lambda *a, **k: ["a.py", "b.py"]), \
                patch("core.code_review.compute_window",
                      lambda *a, **k: (None, None)):
            mon._run_code_review_checkpoint()
        return calls

    def test_worker_dispatches_stall_intent(self):
        """结果信封携带 stall 意图 → 分派 _schedule_stall_redispatch。"""
        result = MagicMock(
            run_id="code-review-w1", inserted=0, updated=0, resolved=0,
            shards=0, error="artifact gate",
            ratelimit_redispatch=None, stall_redispatch=_stall_intent("code-review-w1"))
        calls = self._drive(result)
        self.assertEqual(len(calls["stall"]), 1)
        self.assertEqual(calls["stall"][0]["intent"]["run_id"], "code-review-w1")
        self.assertEqual(calls["ratelimit"], [])

    def test_worker_ratelimit_intent_wins_over_stall(self):
        """双意图（防御非互斥形态）→ ratelimit 分支优先，stall 不排程。"""
        result = MagicMock(
            run_id="code-review-w2", inserted=0, updated=0, resolved=0,
            shards=0, error="429",
            ratelimit_redispatch=_stall_intent("code-review-w2"),
            stall_redispatch=_stall_intent("code-review-w2"))
        calls = self._drive(result)
        self.assertEqual(len(calls["ratelimit"]), 1)
        self.assertEqual(calls["stall"], [], "双条件 ratelimit 优先")

    def test_worker_without_intent_no_dispatch(self):
        result = MagicMock(
            run_id="code-review-w3", inserted=2, updated=0, resolved=0,
            shards=1, error="",
            ratelimit_redispatch=None, stall_redispatch=None)
        calls = self._drive(result)
        self.assertEqual(calls["stall"], [])
        self.assertEqual(calls["ratelimit"], [])


if __name__ == "__main__":
    unittest.main()
