"""evo-add-host-change-governance 宿主系统级变更治理测试。

覆盖 tasks.md 3.1 四个场景族：
- 击杀类终止（无 run-result）时读 worktree 根登记文件派发回滚义务告警
  （登记文件是唯一权威载体——击杀时拷回与 run-result 均不发生）
- 失败终态告警派发与去重（append_if_absent 去重键=spec+变更对象路径）
- 成功终态仅留痕不告警 / 无登记文件零告警
- run-result host_changes 汇总字段警告级校验 fail-open 语义（缺失不拒绝结果）
另覆盖登记拷回留痕（result-bearing run → 主树 .fenix/host_changes/<spec>.json）。
"""

import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.admin_store import (
    ESCALATION,
    HOST_CHANGE_ROLLBACK_SIGNAL_TYPE,
    AdminStore,
)
from core.agent_runner import result_gate
from core.agent_runner.result_gate import (
    HOST_CHANGES_REGISTRY_NAME,
    _check_host_changes_summary_soft,
    parse_host_changes_registry,
)
from core.agent_runner.runner import AgentRunner, _AttemptState

SPEC = "demo"

REGISTRY_ENTRY = {
    "object_path": "/lib/modules/6.8.0/updates/dkms/v4l2loopback.ko",
    "version": "0.12.7 (e27cd86-dirty)",
    "backup": "/var/backups/v4l2loopback-0.12.7.ko",
    "rollback": "cp 备份回原路径 && depmod -a && modprobe v4l2loopback",
}


class RecLogger:
    """记录型 logger（断言 WARNING/INFO 留痕）。"""

    def __init__(self):
        self.infos = []
        self.warnings = []
        self.errors = []

    def debug(self, *a, **k):
        pass

    def info(self, component, message, context=None):
        self.infos.append({"component": component, "message": message})

    def warning(self, component, message, context=None):
        self.warnings.append({"component": component, "message": message})

    def error(self, component, message, context=None):
        self.errors.append({"component": component, "message": message})


def make_runner(proot: Path, logger=None) -> AgentRunner:
    """最小 AgentRunner 实例（tests/helpers.make_runner 先例，绕过真实 __init__）。"""
    runner = AgentRunner.__new__(AgentRunner)
    runner.config = {}
    runner.worktree_manager = None
    runner.state_machine = None
    runner.project_root = proot
    runner.logger = logger or RecLogger()
    runner._running_agents = {}
    return runner


class GovBase:
    """公共夹具：tmp 项目根 + worktree 目录 + 最小 runner。"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir) / "proj"
        self.proot.mkdir()
        (self.proot / ".fenix").mkdir()
        self.wt = Path(self.tmpdir) / "wt"
        self.wt.mkdir()
        self.logger = RecLogger()
        self.runner = make_runner(self.proot, self.logger)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def write_registry(self, entries=None, wt=None):
        p = (wt or self.wt) / HOST_CHANGES_REGISTRY_NAME
        p.write_text(
            json.dumps([REGISTRY_ENTRY] if entries is None else entries,
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return p

    def escalations(self):
        """主树 admin_alerts.json 中的回滚义务 escalation 记录列表。"""
        path = self.proot / ".fenix" / "admin_alerts.json"
        if not path.is_file():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return [
            r for r in data
            if r.get("kind") == ESCALATION
            and r.get("signal_type") == HOST_CHANGE_ROLLBACK_SIGNAL_TYPE
        ]


class TestKilledTerminalDispatch(GovBase):
    """击杀类终止（无 run-result）：终态记录点读 worktree 根登记派发告警。"""

    def test_killed_without_result_dispatches_alert_from_registry(self):
        # 无 .fenix-run-result.json（击杀类终止的特征），登记文件是唯一权威载体
        assert not (self.wt / ".fenix-run-result.json").exists()
        self.write_registry()
        self.runner._dispatch_host_change_rollback_on_failure(
            SPEC, "run-1", self.wt)
        alerts = self.escalations()
        assert len(alerts) == 1
        rec = alerts[0]
        assert rec["spec"] == SPEC
        assert rec["severity"] == "major"
        assert REGISTRY_ENTRY["object_path"] in rec["evidence"]
        assert REGISTRY_ENTRY["rollback"] in rec["recommended_action"]
        assert rec["host_change_paths"] == [REGISTRY_ENTRY["object_path"]]
        # 处置闭环端点可达（复用既有告警生命周期）
        assert AdminStore(self.proot).mark_handled(rec["id"]) is True

    def test_killed_without_registry_zero_alerts(self):
        # 无登记文件：零告警、零新增开销（admin_alerts.json 不因空派发创建）
        self.runner._dispatch_host_change_rollback_on_failure(
            SPEC, "run-1", self.wt)
        assert self.escalations() == []
        assert not (self.proot / ".fenix" / "admin_alerts.json").exists()

    def test_none_worktree_path_zero_alerts(self):
        # worktree 路径不可得（预检早夭等）：零告警不抛
        self.runner._dispatch_host_change_rollback_on_failure(
            SPEC, "run-1", None)
        assert self.escalations() == []

    def test_dispatch_channel_failure_fail_open(self):
        # 告警通道故障 fail-open：只 WARNING，不向终态路径抛异常
        self.write_registry()

        class Boom:
            def __init__(self, *a, **k):
                pass

            def dispatch_host_change_rollback_alert(self, *a, **k):
                raise RuntimeError("store broken")

        import core.admin_store as admin_store

        original = admin_store.AdminStore
        try:
            admin_store.AdminStore = Boom
            self.runner._dispatch_host_change_rollback_on_failure(
                SPEC, "run-1", self.wt)  # MUST NOT raise
        finally:
            admin_store.AdminStore = original
        assert self.escalations() == []
        assert any("fail-open" in w["message"] for w in self.logger.warnings)


class TestFailureTerminalDispatchAndDedup(GovBase):
    """失败终态派发与去重；终态记录点先于 worktree 清理。"""

    def _finalize_terminal(self, wt=None, attempt=1, max_retries=1,
                           agent_type="implementer"):
        """走 _finalize_failure_keep 终态分支（attempt >= max_retries）。"""
        wt = wt or self.wt
        cleaned = []
        self.runner.worktree_manager = SimpleNamespace(
            cleanup=lambda p, success: (cleaned.append((p, success)),
                                        shutil.rmtree(p, ignore_errors=True)),
            keep_for_reuse=lambda *a, **k: None,
        )
        self.runner.__dict__["_v2_server_instance"] = SimpleNamespace(
            _v2_stop_for_worktree=lambda p: None)
        st = _AttemptState(wt_path=wt)
        handed_off = set()
        should_break = self.runner._finalize_failure_keep(
            spec_name=SPEC, agent_type=agent_type, attempt=attempt,
            attempt_run_id="run-1", max_retries=max_retries, start_time=0.0,
            turns=3, usage_info={}, provider_name=None, model=None,
            error="claude CLI failed: Exit code: 137 (killed)",
            cancelled_flag=False, shutdown_interrupted=False,
            st=st, handed_off=handed_off,
        )
        return should_break, cleaned, st, handed_off

    def test_terminal_failure_dispatches_alert_before_cleanup(self):
        self.write_registry()
        should_break, cleaned, st, handed_off = self._finalize_terminal()
        # 终态失败且登记非空 → 告警派发（registry 内容进 evidence）
        alerts = self.escalations()
        assert len(alerts) == 1
        assert REGISTRY_ENTRY["object_path"] in alerts[0]["evidence"]
        # 派发先于 worktree 清理：cleanup 已执行（目录被删），告警仍含登记内容
        assert cleaned and cleaned[0][1] is False
        assert not self.wt.exists(), "cleanup 模拟真实删除"
        # implementer 终态失败非 break 通道（attempt 预算自然耗尽）
        assert should_break is False
        assert st.kept_wt_path is None

    def test_retry_wait_does_not_dispatch(self, monkeypatch):
        # attempt 间重试等待（非终态）：不派发、worktree 保留
        monkeypatch.setattr(
            __import__("core.agent_runner.runner", fromlist=["time"]).time,
            "sleep", lambda s: None)
        self.write_registry()
        should_break, cleaned, st, _ = self._finalize_terminal(
            attempt=0, max_retries=3)
        assert should_break is False
        assert cleaned == []
        assert self.escalations() == []
        assert self.wt.exists(), "重试等待保留 worktree"

    def test_dedup_same_spec_and_object_path(self):
        self.write_registry()
        self.runner._dispatch_host_change_rollback_on_failure(
            SPEC, "run-1", self.wt)
        # 同 spec 同对象路径的未处理告警在途：二次失败终态不重复派发
        self.runner._dispatch_host_change_rollback_on_failure(
            SPEC, "run-2", self.wt)
        assert len(self.escalations()) == 1
        # 新对象路径 → 落新条（去重键=spec+变更对象路径，非 spec 单值）
        self.write_registry(
            [{"object_path": "/usr/lib/modules/x.ko", "version": "1"}])
        self.runner._dispatch_host_change_rollback_on_failure(
            SPEC, "run-3", self.wt)
        assert len(self.escalations()) == 2
        # 既有告警闭环（人工已处理）→ 同路径复现再落新条（生命周期复用）
        AdminStore(self.proot).mark_handled(self.escalations()[0]["id"])
        self.write_registry()
        self.runner._dispatch_host_change_rollback_on_failure(
            SPEC, "run-4", self.wt)
        assert len(self.escalations()) == 3

    def test_terminal_failure_empty_registry_zero_alerts(self):
        self.write_registry(entries=[])
        self._finalize_terminal()
        assert self.escalations() == []

    def test_terminal_failure_invalid_registry_fail_open(self):
        # 登记文件非法 JSON：解析失败降级「无有效登记」，终态收口不抛
        (self.wt / HOST_CHANGES_REGISTRY_NAME).write_text(
            "{not-json", encoding="utf-8")
        should_break, cleaned, _, _ = self._finalize_terminal()
        assert self.escalations() == []
        assert cleaned, "终态收口不被登记解析问题阻断"


class TestSuccessTerminalTraceOnly(GovBase):
    """成功终态仅留痕不告警；无登记文件零动作。"""

    def _finalize_success(self):
        from core.agent_runner.result_gate import AgentRunResult

        cleaned = []
        self.runner.__dict__["_provider_circuit_instance"] = SimpleNamespace(
            provider_circuits={})
        self.runner.worktree_manager = SimpleNamespace(
            cleanup=lambda p, success: (cleaned.append((p, success)),
                                        shutil.rmtree(p, ignore_errors=True)),
            keep_for_reuse=lambda *a, **k: None,
            get_branch_name=lambda p: "fenix/demo-impl",
        )
        self.runner.__dict__["_v2_server_instance"] = SimpleNamespace(
            _v2_stop_for_worktree=lambda p: None)
        self.runner._git_status_porcelain = lambda p: []
        self.runner._should_keep_worktree_for_partial = lambda s, p: False
        self.runner._daily_count_lock = threading.Lock()
        self.runner._daily_run_count = 0
        self.runner._reset_instant_fail = lambda s: None
        self.runner._reset_signal_kill = lambda s: None
        self.runner._accumulate_token_usage = lambda *a, **k: None
        self.runner._record_verify_progress_tokens = lambda *a, **k: None
        self.runner._log_run_metrics = lambda *a, **k: None
        self.runner._cancel_clear = lambda r: None
        result = self.runner._finalize_success(
            spec_name=SPEC, agent_type="implementer", run_id="run",
            attempt_run_id="run-a1", attempt=1, start_time=0.0, turns=5,
            usage_info={}, provider_name=None, model=None,
            wt_path=self.wt, output="ok", sub_run_id="run-a1",
            branch="fenix/demo-impl", handed_off=set(),
        )
        assert isinstance(result, AgentRunResult)
        return cleaned

    def test_success_with_registry_traces_without_alert(self):
        self.write_registry()
        cleaned = self._finalize_success()
        # 仅留痕（INFO），零告警
        assert self.escalations() == []
        assert any("留痕" in i["message"] and "不告警" in i["message"]
                   for i in self.logger.infos)
        assert REGISTRY_ENTRY["object_path"] in "\n".join(
            i["message"] for i in self.logger.infos)
        # 留痕读取先于清理（cleanup 已删目录仍留痕成功）
        assert cleaned and cleaned[0][1] is True
        assert not self.wt.exists()

    def test_success_without_registry_zero_alerts(self):
        cleaned = self._finalize_success()
        assert self.escalations() == []
        assert not any("宿主变更登记" in i["message"]
                       for i in self.logger.infos)
        assert cleaned


class TestHostChangesSummarySoftCheck:
    """run-result host_changes 汇总字段警告级校验 fail-open 语义。"""

    @pytest.fixture()
    def env(self, tmp_path):
        wt = tmp_path / "wt"
        wt.mkdir()
        result_path = wt / ".fenix-run-result.json"
        registry = wt / HOST_CHANGES_REGISTRY_NAME
        return SimpleNamespace(wt=wt, result_path=result_path,
                               registry=registry)

    def _capwarn(self, caplog):
        return [r for r in caplog.records
                if r.levelno >= 30 and "host_changes" in r.getMessage()]

    def test_missing_field_fail_open(self, env, caplog):
        # 字段缺失：零拦截零告警（fail-open 语义锚点）
        caplog.set_level("WARNING", logger=result_gate._logger.name)
        _check_host_changes_summary_soft(
            None, SPEC, {"status": "success"}, env.result_path, env.wt)
        assert self._capwarn(caplog) == []

    def test_non_dict_result_fail_open(self, env, caplog):
        caplog.set_level("WARNING", logger=result_gate._logger.name)
        _check_host_changes_summary_soft(
            None, SPEC, None, env.result_path, env.wt)
        assert self._capwarn(caplog) == []

    def test_malformed_summary_warns_but_never_rejects(self, env, caplog):
        # 形态非法（非数组 / 元素缺对象路径）：WARNING 放行，恒返回 None
        caplog.set_level("WARNING", logger=result_gate._logger.name)
        for bad in ("not-a-list", [{"version": "1"}], [{"object_path": " "}]):
            data = {"status": "success", "host_changes": bad}
            assert _check_host_changes_summary_soft(
                None, SPEC, data, env.result_path, env.wt) is None
        assert len(self._capwarn(caplog)) >= 3

    def test_summary_registry_mismatch_warns(self, env, caplog):
        env.registry.write_text(
            json.dumps([REGISTRY_ENTRY], ensure_ascii=False), encoding="utf-8")
        data = {"status": "success",
                "host_changes": [{"object_path": "/other/path.ko"}]}
        caplog.set_level("WARNING", logger=result_gate._logger.name)
        assert _check_host_changes_summary_soft(
            None, SPEC, data, env.result_path, env.wt) is None
        warns = self._capwarn(caplog)
        assert any("不一致" in r.getMessage() for r in warns)

    def test_consistent_summary_no_warning(self, env, caplog):
        env.registry.write_text(
            json.dumps([REGISTRY_ENTRY], ensure_ascii=False), encoding="utf-8")
        data = {"status": "success",
                "host_changes": [{"object_path": REGISTRY_ENTRY["object_path"],
                                  "version": "0.12.7", "backup": "/b",
                                  "rollback": "cp back"}]}
        caplog.set_level("WARNING", logger=result_gate._logger.name)
        assert _check_host_changes_summary_soft(
            None, SPEC, data, env.result_path, env.wt) is None
        assert self._capwarn(caplog) == []

    def test_registry_missing_no_warning(self, env, caplog):
        # 汇总在场但登记缺位：权威载体缺位无从对账 → 放行
        data = {"status": "success", "host_changes": [dict(REGISTRY_ENTRY)]}
        caplog.set_level("WARNING", logger=result_gate._logger.name)
        assert _check_host_changes_summary_soft(
            None, SPEC, data, env.result_path, env.wt) is None
        assert self._capwarn(caplog) == []

    def test_soft_check_internal_error_fail_open(self, env, caplog):
        # 软检查自身故障 fail-open：不向门禁路径抛异常
        env.registry.write_text("{}", encoding="utf-8")
        data = {"status": "success", "host_changes": [dict(REGISTRY_ENTRY)]}
        original = result_gate.parse_host_changes_registry
        try:
            result_gate.parse_host_changes_registry = (
                lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
            assert _check_host_changes_summary_soft(
                None, SPEC, data, env.result_path, env.wt) is None
        finally:
            result_gate.parse_host_changes_registry = original
        # 恒不 raise 即通过


class TestRegistryParsing:
    """登记文件解析单点（runner 终态路径与软校验共引）。"""

    def test_missing_file_returns_none(self, tmp_path):
        assert parse_host_changes_registry(tmp_path / "nope.json") is None

    def test_invalid_json_returns_none(self, tmp_path):
        p = tmp_path / HOST_CHANGES_REGISTRY_NAME
        p.write_text("{broken", encoding="utf-8")
        assert parse_host_changes_registry(p) is None

    def test_non_list_returns_none(self, tmp_path):
        p = tmp_path / HOST_CHANGES_REGISTRY_NAME
        p.write_text('{"object_path": "/x"}', encoding="utf-8")
        assert parse_host_changes_registry(p) is None

    def test_empty_list_is_valid_value(self, tmp_path):
        p = tmp_path / HOST_CHANGES_REGISTRY_NAME
        p.write_text("[]", encoding="utf-8")
        assert parse_host_changes_registry(p) == []

    def test_wrapped_changes_form_tolerated(self, tmp_path):
        p = tmp_path / HOST_CHANGES_REGISTRY_NAME
        p.write_text(
            json.dumps({"changes": [REGISTRY_ENTRY]}, ensure_ascii=False),
            encoding="utf-8")
        assert parse_host_changes_registry(p) == [REGISTRY_ENTRY]

    def test_object_path_alias(self):
        assert result_gate.host_change_object_path(
            {"path": "/x"}) == "/x"
        assert result_gate.host_change_object_path("junk") == ""


class TestCopyback(GovBase):
    """登记拷回留痕（result-bearing run → 主树 .fenix/host_changes/<spec>.json）。"""

    def test_copyback_writes_main_tree_trace(self):
        self.write_registry()
        self.runner._copyback_host_changes(SPEC, self.wt)
        dst = self.proot / ".fenix" / "host_changes" / f"{SPEC}.json"
        assert dst.is_file()
        assert json.loads(dst.read_text(encoding="utf-8")) == [REGISTRY_ENTRY]

    def test_copyback_noop_without_registry(self):
        self.runner._copyback_host_changes(SPEC, self.wt)
        assert not (self.proot / ".fenix" / "host_changes").exists()

    def test_copyback_mtime_guard_keeps_newer_main_tree(self):
        # 主树较新（mtime 更晚）→ worktree 陈旧副本不回灌
        import os

        dst = self.proot / ".fenix" / "host_changes" / f"{SPEC}.json"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(json.dumps([{"object_path": "/newer"}]),
                       encoding="utf-8")
        old = self.tmpdir + "/old"
        os.mkdir(old)
        reg = self.write_registry(wt=Path(old))
        past = os.stat(dst).st_mtime - 100
        os.utime(reg, (past, past))
        self.runner._copyback_host_changes(SPEC, Path(old))
        assert json.loads(dst.read_text(encoding="utf-8")) == [
            {"object_path": "/newer"}]
