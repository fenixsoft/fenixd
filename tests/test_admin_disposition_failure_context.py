"""admin-disposition-failure-context 测试（fix-admin-disposition-empty-shell tasks 4.1）。

CLI 失败 → final 记录含 error / 兜底 recommended_action / description 非空；
成功记录不受影响；WARNING 日志在 _run_agent 异常时被调用。
"""
import pytest

from core.admin_store import AdminStore, DISPOSITION
from core.admin_monitor import AdminMonitor
from core.agent_runner import AdminDisposition
from core.agent_runner.runner import AgentRunner, admin_disposition_path
from tests.helpers import iso_ago


# ── 辅助 ────────────────────────────────────────────────


class FakeLogger:
    def __init__(self):
        self.warnings = []
        self.errors = []

    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def warning(self, component: str, message: str, context=None):
        self.warnings.append({"component": component, "message": message, "context": context})

    def error(self, component: str, message: str, context=None):
        self.errors.append({"component": component, "message": message, "context": context})


class FakeSM:
    def __init__(self, specs: dict):
        self._specs = specs

    def read_all(self):
        return self._specs


class FailingRunner:
    """模拟 CLI 失败——run_administrator 返回 failed disposition。"""

    def __init__(self, error_text="claude CLI failed: Exit code: 143"):
        self.error_text = error_text
        self.calls = []

    def run_administrator(self, signal):
        self.calls.append(signal)
        return AdminDisposition(
            run_id=f"admin-{signal.get('spec')}-test-1",
            spec=signal.get("spec"),
            success=False,
            problem="",
            actions_taken="",
            result="failed",
            escalate=False,
            recommended_action="",
            summary="",
            error=self.error_text,
        )


class SuccessRunner:
    """模拟成功——run_administrator 返回 resolved disposition。"""

    def __init__(self):
        self.calls = []

    def run_administrator(self, signal):
        self.calls.append(signal)
        return AdminDisposition(
            run_id=f"admin-{signal.get('spec')}-test-1",
            spec=signal.get("spec"),
            success=True,
            problem="已诊断",
            actions_taken="重置状态",
            result="resolved",
            escalate=False,
            recommended_action="建议人工检查日志",
            summary="诊断结论：问题已解决。",
            error="",
        )


def make_signal(spec="spec-a", signal_type="stuck"):
    return {
        "signal_type": signal_type,
        "spec": spec,
        "severity": "major",
        "description": "卡滞 2 小时无进展",
        "evidence": "旧记录未更新",
        "recommended_action": "检查 spec-a 的 agent 进程是否存活",
    }


def make_monitor(tmp_path, specs, config=None, runner=None):
    proot = tmp_path / "proj"
    proot.mkdir(parents=True, exist_ok=True)
    logger = FakeLogger()
    mon = AdminMonitor(
        config or {},
        FakeSM(specs),
        proot,
        logger,
        store=AdminStore(proot, logger),
        agent_runner=runner,
    )
    return proot, mon, logger


# ── 核心断言 ─────────────────────────────────────────────


class TestFailedDispositionFailureContext:
    """CLI 失败 → final 记录含 error / 兜底 recommended_action / description 非空。"""

    def test_failed_record_carries_error(self, tmp_path):
        runner = FailingRunner("claude CLI failed: Exit code: 143")
        proot, mon, _ = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(120)},
        }, runner=runner)
        mon._invoke_administrator(make_signal(), None)
        recs = mon.store.read_all()
        disp = next(r for r in recs if r["kind"] == DISPOSITION)
        assert disp["result"] == "failed"
        assert disp["error"] == "claude CLI failed: Exit code: 143"
        assert disp["description"]  # description 非空

    def test_failed_record_recommended_action_fallback(self, tmp_path):
        runner = FailingRunner()
        proot, mon, _ = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(120)},
        }, runner=runner)
        signal = make_signal()
        mon._invoke_administrator(signal, None)
        recs = mon.store.read_all()
        disp = next(r for r in recs if r["kind"] == DISPOSITION)
        # recommended_action 应回退到信号值（disp.recommended_action 为空）
        assert disp["recommended_action"] == signal["recommended_action"]

    def test_failed_record_summary_allows_empty(self, tmp_path):
        runner = FailingRunner()
        proot, mon, _ = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(120)},
        }, runner=runner)
        mon._invoke_administrator(make_signal(), None)
        recs = mon.store.read_all()
        disp = next(r for r in recs if r["kind"] == DISPOSITION)
        assert disp["summary"] == ""  # summary 允许为空
        assert disp["error"]          # error 必须非空


class TestSuccessfulDispositionUnaffected:
    """成功记录不受影响：无 error 键或空串；recommended_action 取 disp 值。

    （原 test_successful_record_error_empty 与 preserves_all_fields 断言完全
    子集重叠——result/error 两键后者均已覆盖——审查后并入删除。）
    """

    def test_successful_record_recommended_action_not_fallback(self, tmp_path):
        runner = SuccessRunner()
        proot, mon, _ = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(120)},
        }, runner=runner)
        signal = make_signal()
        mon._invoke_administrator(signal, None)
        recs = mon.store.read_all()
        disp = next(r for r in recs if r["kind"] == DISPOSITION)
        # recommended_action 取 disp 值，不回退到 signal
        assert disp["recommended_action"] == "建议人工检查日志"

    def test_successful_record_preserves_all_fields(self, tmp_path):
        runner = SuccessRunner()
        proot, mon, _ = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(120)},
        }, runner=runner)
        mon._invoke_administrator(make_signal(), None)
        recs = mon.store.read_all()
        disp = next(r for r in recs if r["kind"] == DISPOSITION)
        assert disp["result"] == "resolved"
        assert disp["summary"] == "诊断结论：问题已解决。"
        assert disp["description"] == "已诊断"
        assert disp["error"] == ""


# ── run_administrator WARNING 日志 ──────────────────────


class TestRunAdministratorWarningLog:
    """_run_agent 异常路径产生 WARNING 日志（fix-admin-disposition-empty-shell）。

    （原 test_warning_log_contains_run_id_and_error 与 test_warning_log_context_has_run_id
    同一 fixture 同一调用路径，仅分别断言 message / context 两个键——审查后合并；
    test_failed_disposition_error_field_set 的三断言由
    TestFailedDispositionFailureContext.test_failed_record_carries_error（记录层）
    与 test_admin.py::test_run_administrator_failure_falls_back（disp 层）覆盖，删除。）
    """

    def test_warning_log_carries_run_id_and_error(self, tmp_path):
        logger = FakeLogger()
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        runner = AgentRunner.__new__(AgentRunner)
        runner.project_root = proot
        runner._get_config = lambda key, default=None: default
        runner._get_admin_model = lambda: "claude-sonnet-5"
        runner._get_agent_model_assignment = lambda agent_type: None
        runner._prompt_builder._build_prompt = lambda *a, **k: "prompt"

        def failing_run_agent(prompt, cwd, run_id, model_override, env_overrides,
                               max_turns, spec_name=None, agent_type=None):
            raise RuntimeError("claude CLI failed: Exit code: 143")

        runner._run_agent = failing_run_agent
        runner.logger = logger

        disp = runner.run_administrator(make_signal())

        # WARNING 日志被调用，message 含 run_id 与异常文本
        assert len(logger.warnings) >= 1
        warn = logger.warnings[0]
        assert warn["component"] == "agent_runner"
        assert disp.run_id in warn["message"]
        assert "Exit code: 143" in warn["message"]
        # context 结构化字段同样携带 run_id 与异常文本
        assert warn["context"]["run_id"] == disp.run_id
        assert "Exit code: 143" in warn["context"]["error"]


# ── run_administrator 收尾富指标行（admin 车道品牌投影写侧补链） ──────────


class RecordingLogger(FakeLogger):
    """FakeLogger 基础上记录 info 调用（收尾 run_metrics 行断言用）。"""

    def __init__(self):
        super().__init__()
        self.infos = []

    def info(self, component, message, context=None):
        self.infos.append(
            {"component": component, "message": message, "context": context})


class TestRunAdministratorLaneMetrics:
    """admin 车道收尾写 harness 富指标行（品牌投影数据源补链）。

    run_administrator 此前从不写带 agent_type/harness 的终态富指标行——
    run_metrics 索引里只有 projection/context 两条注记行，品牌投影读侧取不
    到 harness（admin dsh run 恒回退 Claude 品牌）；且 _run_agent spawn 装配
    写入的 _run_harness 登记无收尾咽喉消费，随 daemon 无界增长。
    """

    def _make_runner(self, tmp_path, logger, run_agent):
        proot = tmp_path / "proj"
        (proot / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
        runner = AgentRunner.__new__(AgentRunner)
        runner.project_root = proot
        runner._get_config = lambda key, default=None: default
        runner._get_admin_model = lambda: "claude-sonnet-5"
        runner._get_agent_model_assignment = lambda agent_type: None
        runner._prompt_builder._build_prompt = lambda *a, **k: "prompt"
        runner._run_agent = run_agent
        runner.logger = logger
        runner._run_harness = {}
        return runner

    @staticmethod
    def _terminal_metrics(logger):
        return [
            e for e in logger.infos
            if isinstance(e["context"], dict)
            and e["context"].get("metric_type") == "run_metrics"
            and e["context"].get("terminal")
        ]

    def test_success_path_emits_harness_and_pops_registration(self, tmp_path):
        logger = RecordingLogger()
        holder = {}

        def success_run_agent(prompt, cwd, run_id, model_override,
                              env_overrides, max_turns,
                              spec_name=None, agent_type=None):
            # 模拟 _run_agent spawn 装配的品牌登记（runner.py 一次性车道同款）
            holder["runner"]._run_harness[run_id] = "dsh"
            # 按 prompt 契约写合法处置文件（result 枚举内 → 硬门放行）
            admin_disposition_path(holder["runner"].project_root, run_id).write_text(
                '{"result": "resolved", "summary": "ok"}', encoding="utf-8")
            return ("output", 7, None, {"input_tokens": 100, "output_tokens": 20},
                    {"rounds": 7, "stalls": 0, "max": 0.5})

        runner = self._make_runner(tmp_path, logger, success_run_agent)
        holder["runner"] = runner

        disp = runner.run_administrator(make_signal())

        assert disp.success is True
        metrics = self._terminal_metrics(logger)
        assert len(metrics) == 1
        ctx = metrics[0]["context"]
        assert ctx["run_id"] == disp.run_id
        assert ctx["agent_type"] == "administrator"
        assert ctx["harness"] == "dsh"
        assert ctx["terminal"] == "success"
        assert ctx["turns"] == 7
        assert ctx["input_tokens"] == 100
        # 登记随收尾消费摘除（无界增长缺口闭合）
        assert runner._run_harness == {}

    def test_agent_failure_path_emits_error_terminal_and_pops(self, tmp_path):
        logger = RecordingLogger()
        holder = {}

        def failing_run_agent(prompt, cwd, run_id, model_override,
                              env_overrides, max_turns,
                              spec_name=None, agent_type=None):
            holder["runner"]._run_harness[run_id] = "dsh"
            raise RuntimeError("claude CLI failed: Exit code: 143")

        runner = self._make_runner(tmp_path, logger, failing_run_agent)
        holder["runner"] = runner

        disp = runner.run_administrator(make_signal())

        assert disp.success is False
        metrics = self._terminal_metrics(logger)
        assert len(metrics) == 1
        ctx = metrics[0]["context"]
        assert ctx["run_id"] == disp.run_id
        assert ctx["harness"] == "dsh"
        assert ctx["terminal"] == "error"
        # 抛出路径 turns 预置 0（不 NameError、零样本入账）
        assert ctx["turns"] == 0
        assert runner._run_harness == {}
