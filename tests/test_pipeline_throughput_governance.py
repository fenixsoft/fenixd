"""tests/test_pipeline_throughput_governance.py

add-pipeline-throughput-governance SPEC 单测：并发槽位上调（1.3）、merge 前置
预检（2.4）、重启排水保护（3.3）、bug-found 小缺陷 fastlane（4.3）、spec-review
打回理由结构化（5.3）。
"""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.config import ConfigLoader
from core.pm_engine.spec_review import (
    normalize_rejection_class,
    rejection_class_stats,
)


# ── 基建：git 仓库初始化与分支播种（对齐 test_worktree_merge_guard 风格）────


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        timeout=60,
    )


def init_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    (root / "README.md").write_text("base\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    return root


class FakeLogger:
    def __init__(self):
        self.records: list = []

    def _rec(self, level, component, msg):
        self.records.append((level, component, msg))

    def info(self, component, msg, context=None):
        self._rec("info", component, msg)

    def warning(self, component, msg, context=None):
        self._rec("warning", component, msg)

    def error(self, component, msg, context=None):
        self._rec("error", component, msg)

    def debug(self, component, msg, context=None):
        self._rec("debug", component, msg)


# ══════════════════════ 1. 并发槽位上调（任务 1.3）═════════════════════════


class TestDispatchConcurrencyTuning:
    def test_default_is_5_without_explicit_config(self):
        """无显式配置时代码缺省 5：派发队列读取缺省值与配置读取面一致。"""
        import inspect

        from core.pm_engine.dispatch import queue as queue_mod

        src = inspect.getsource(queue_mod)
        assert '_get_config("agents.max_concurrent", 5)' in src, (
            "queue.py 的 agents.max_concurrent 代码缺省值应为 5"
        )
        # 配置读取面：未配置键返回给定缺省（显式配置优先级链路的底层语义）
        assert ConfigLoader.get({}, "agents.max_concurrent", 5) == 5

    def test_explicit_config_wins_over_default(self):
        """显式配置任意值（如 3）时按配置值生效。"""
        config = {"agents": {"max_concurrent": 3}}
        assert ConfigLoader.get(config, "agents.max_concurrent", 5) == 3

    def test_template_recommends_5(self):
        """.fenix/config.template.yaml 推荐值同步为 5 且附资源前提注释。"""
        repo_root = Path(__file__).resolve().parents[1]
        template = (repo_root / ".fenix" / "config.template.yaml").read_text(
            encoding="utf-8"
        )
        assert "max_concurrent: 5" in template
        for keyword in ("worktree 磁盘", "网关并发", "full-suite.lock"):
            assert keyword in template, f"模板缺资源前提注释: {keyword}"

    def test_full_suite_lock_wait_cap_unchanged(self):
        """full-suite.lock 主机级回归锁互斥与 600s 等待上限语义不变。"""
        from core import regression

        assert regression._LOCK_WAIT_TIMEOUT_SECONDS == 600
        assert regression._LOCK_FILE_REL == ".fenix/full-suite.lock"


# ══════════════════════ 2. merge 前置预检（任务 2.4）═════════════════════════


class TestMergeBackPrecheck:
    """merge-back 发起前交集预检（复用既有 _detect_wip_overlap 判定）。"""

    def _seed_overlap_repo(self, root: Path) -> str:
        """core/a.py 基线 + 分支改同路径；返回基线 sha。"""
        (root / "core").mkdir()
        (root / "core" / "a.py").write_text("BASE-A\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "seed core/a.py")
        base_sha = git(root, "rev-parse", "HEAD").stdout.strip()
        git(root, "checkout", "-q", "-b", "fenix/impl")
        (root / "core" / "a.py").write_text("BASE-A\nBRANCH-A\n", encoding="utf-8")
        git(root, "commit", "-q", "-am", "branch edit")
        git(root, "checkout", "-q", "main")
        return base_sha

    def _make_wm(self, root: Path, **kwargs):
        from core.worktree_manager import WorktreeManager

        return WorktreeManager(
            root / ".claude" / "worktrees", root, FakeLogger(), **kwargs
        )

    def test_wip_overlap_blocks_merge_and_escalates(self, tmp_path):
        """缺省（escalate）：交集非空 → 不发起 merge、wip_gate_blocked=True、
        spec 侧产物（分支与主树 WIP）完好。"""
        from core.worktree_manager.types import MergeConflictInfo

        root = init_repo(tmp_path / "repo")
        base_sha = self._seed_overlap_repo(root)
        # 主树 WIP 与分支触碰路径重叠
        (root / "core" / "a.py").write_text("BASE-A\nWIP-A\n", encoding="utf-8")

        wm = self._make_wm(root)  # 缺省策略 = escalate（本 SPEC 策略变更）
        info = wm.merge_back_from_branch("fenix/impl")
        success, err = info
        assert not success, f"交集非空缺省应拦截: {err}"
        assert info.wip_gate_blocked is True
        assert isinstance(info, MergeConflictInfo)
        # 主树零污染：HEAD 不动、无 stash、WIP 原样
        assert git(root, "rev-parse", "HEAD").stdout.strip() == base_sha
        assert not git(root, "stash", "list").stdout.strip()
        assert (root / "core" / "a.py").read_text(encoding="utf-8") == "BASE-A\nWIP-A\n"

    def test_escalation_message_contains_overlap_list(self, tmp_path):
        """升级拦截出口内容含交集清单与两侧来源（主树 WIP × 分支改动）。"""
        root = init_repo(tmp_path / "repo")
        self._seed_overlap_repo(root)
        (root / "core" / "a.py").write_text("BASE-A\nWIP-A\n", encoding="utf-8")

        wm = self._make_wm(root)
        info = wm.merge_back_from_branch("fenix/impl")
        assert info.wip_overlap == ["core/a.py"]
        assert "core/a.py" in info.error, f"告警应含交集清单: {info.error}"
        assert "fenix/impl" in info.error, "告警应含分支（一侧来源）"
        assert "merge_precheck_bypass" in info.error, "告警应含逃生门指引"

    def test_no_overlap_merges_directly(self, tmp_path):
        """无交集（主树 WIP 路径分支未触碰）→ 预检直通，正常 merge。"""
        root = init_repo(tmp_path / "repo")
        self._seed_overlap_repo(root)
        # 主树 WIP 只动分支未触碰的文件
        (root / "README.md").write_text("base\nlocal-wip\n", encoding="utf-8")

        wm = self._make_wm(root)
        info = wm.merge_back_from_branch("fenix/impl")
        success, err = info
        assert success, f"无交集应直通: {err}"
        assert info.wip_gate_blocked is False
        assert "BRANCH-A" in git(root, "show", "HEAD:core/a.py").stdout

    def test_bypass_skips_precheck(self, tmp_path):
        """merge_precheck_bypass=true：重叠在场也直接 merge（可自动合并的
        不同 hunk），与未引入预检能力前一致。"""
        root = init_repo(tmp_path / "repo")
        self._seed_overlap_repo(root)
        # 同路径不同 hunk（分支尾加行、WIP 头加行）→ git 可自动合并
        (root / "core" / "a.py").write_text("WIP-FIRST\nBASE-A\n", encoding="utf-8")

        wm = self._make_wm(root, merge_precheck_bypass=True)
        info = wm.merge_back_from_branch("fenix/impl")
        success, err = info
        assert success, f"逃生门应跳过预检直接 merge: {err}"
        assert info.wip_gate_blocked is False

    def test_policy_resolution_block_merges_into_escalate(self):
        """策略解析：缺省 None→escalate、显式 block→escalate（并入升级出口）、
        显式 auto 保留收纳语义（读侧兼容）。"""
        from core.worktree_manager import WorktreeManager

        def policy_for(value):
            wm = WorktreeManager.__new__(WorktreeManager)
            wm._mergeback_wip_overlap_policy = value
            return WorktreeManager._wip_gate_policy(wm)

        assert policy_for(None) == "escalate"
        assert policy_for("block") == "escalate"
        assert policy_for("auto") == "auto"

    def test_explicit_auto_policy_keeps_stash_semantics(self, tmp_path):
        """显式 auto：重叠收纳 stash→merge→恢复（旧缺省行为保留）。"""
        root = init_repo(tmp_path / "repo")
        self._seed_overlap_repo(root)
        (root / "core" / "a.py").write_text("WIP-FIRST\nBASE-A\n", encoding="utf-8")

        wm = self._make_wm(root, mergeback_wip_overlap_policy="auto")
        info = wm.merge_back_from_branch("fenix/impl")
        success, err = info
        assert success, f"显式 auto 收纳应完成 merge: {err}"
        assert info.wip_gate_blocked is False


# ══════════════════════ 3. 重启排水保护（任务 3.3）═════════════════════════


class TestGracefulRestartDrain:
    def test_default_drain_window_is_60_not_1800(self):
        """缺省窗口 60s：缺省组合下重启无 1800s 级空等。"""
        assert ConfigLoader.get_run_drain_max_seconds({}) == 60.0

    def test_explicit_drain_window_enlarged_takes_effect(self):
        """显式调大（600s）且未超 shutdown 缺省 1800 → 按 600 生效。"""
        config = {"agents": {"run_drain_max_seconds": 600}}
        assert ConfigLoader.get_run_drain_max_seconds(config) == 600.0

    def test_drain_window_clamped_by_shutdown_drain(self):
        """MUST ≤ shutdown_drain_seconds：旁路组合按 min 夹紧（含 0 快速停机联动）。"""
        assert ConfigLoader.get_run_drain_max_seconds(
            {"agents": {"run_drain_max_seconds": 600},
             "admin": {"shutdown_drain_seconds": 300}}
        ) == 300.0
        assert ConfigLoader.get_run_drain_max_seconds(
            {"admin": {"shutdown_drain_seconds": 0}}
        ) == 0.0


class TestPlannedRestartDrainExemption:
    """规划性重启豁免 shutdown=0 夹紧（planned-restart-drain 3.2）。

    planned=True：豁免 admin.shutdown_drain_seconds 快速停机联动，窗口取
    min(run_drain 原值, supervisor SIGKILL 等待 − 终止收口安全余量 10s)；
    shutdown≤0 时 SIGKILL 等待回退 60s（bin/fenixd_supervisor.py
    _sigkill_wait_seconds），上界 = 50s。
    """

    def test_planned_exempt_from_shutdown_zero_clamp(self):
        """planned 在场：shutdown=0 不再清零，窗口 = run_drain 原值受上界 50s。"""
        config = {"agents": {"run_drain_max_seconds": 60},
                  "admin": {"shutdown_drain_seconds": 0}}
        assert ConfigLoader.get_run_drain_max_seconds(config, planned=True) == 50.0

    def test_planned_window_capped_by_supervisor_sigkill_wait(self):
        """planned：窗口仍受 supervisor SIGKILL 等待上界约束（60−10=50）。"""
        config = {"agents": {"run_drain_max_seconds": 600},
                  "admin": {"shutdown_drain_seconds": 0}}
        assert ConfigLoader.get_run_drain_max_seconds(config, planned=True) == 50.0

    def test_planned_shutdown_positive_upper_bound_not_binding(self):
        """planned：shutdown>0 时 SIGKILL 等待 = shutdown+120，上界不束紧。"""
        config = {"agents": {"run_drain_max_seconds": 600},
                  "admin": {"shutdown_drain_seconds": 1800}}
        assert ConfigLoader.get_run_drain_max_seconds(config, planned=True) == 600.0

    def test_planned_zero_run_drain_stays_zero(self):
        """planned：run_drain 显式 0（车道禁用排水）仍为 0，WARNING 留痕路径。"""
        config = {"agents": {"run_drain_max_seconds": 0},
                  "admin": {"shutdown_drain_seconds": 0}}
        assert ConfigLoader.get_run_drain_max_seconds(config, planned=True) == 0.0

    def test_non_planned_clamp_unchanged(self):
        """非规划性关停现行 min 夹紧逐字节不变（含 shutdown=0 联动清零）。"""
        config = {"agents": {"run_drain_max_seconds": 60},
                  "admin": {"shutdown_drain_seconds": 0}}
        assert ConfigLoader.get_run_drain_max_seconds(config) == 0.0
        assert ConfigLoader.get_run_drain_max_seconds(config, planned=False) == 0.0

    def test_validate_rejects_both_explicit_violation(self):
        """两者均显式且 run_drain > shutdown → 配置加载拒绝。"""
        with pytest.raises(ValueError, match="run_drain_max_seconds"):
            ConfigLoader._validate(
                {
                    "project": {"name": "t", "type": "cli"},
                    "schedule": {},
                    "agents": {"run_drain_max_seconds": 600},
                    "admin": {"shutdown_drain_seconds": 300},
                    "worktree": {},
                    "gates": {},
                    "commands": {},
                    "logging": {},
                }
            )

    def test_fenixd_restart_drain_uses_run_drain_config(self):
        """daemon restart 排水窗口走 agents.run_drain_max_seconds 单源。"""
        import inspect

        import fenixd

        src = inspect.getsource(fenixd.FenixDaemon)
        assert "def _run_drain_max_seconds" in src
        assert "get_run_drain_max_seconds" in src

    def test_broadcast_checkpoint_writes_flags_for_running_runs(self, tmp_path):
        """广播对每个在飞 run 写一次 checkpoint 旗标（写即返回、不阻塞）。"""
        from core.agent_runner.runner import AgentRunner

        runner = AgentRunner.__new__(AgentRunner)
        runner.project_root = tmp_path
        runner.logger = FakeLogger()
        done_proc = SimpleNamespace(poll=lambda: 0)      # 已收尾
        live_proc = SimpleNamespace(poll=lambda: None)   # 在飞
        runner._running_agents = {
            "impl-live-1": live_proc,
            "impl-done-2": done_proc,
        }
        dispatched = runner.broadcast_restart_checkpoint(reason="unit-test")
        assert dispatched == ["impl-live-1"]
        flag = tmp_path / ".fenix" / "runs" / "impl-live-1.checkpoint.json"
        assert flag.exists(), "在飞 run 应收到 checkpoint 旗标"
        payload = json.loads(flag.read_text(encoding="utf-8"))
        assert payload["action"] == "checkpoint"
        assert payload["reason"] == "unit-test"
        assert not (tmp_path / ".fenix" / "runs" / "impl-done-2.checkpoint.json").exists()

    def test_broadcast_zero_side_effect_without_running_runs(self, tmp_path):
        """广播零副作用：无在飞 run 时返回空清单、不建多余文件。"""
        from core.agent_runner.runner import AgentRunner

        runner = AgentRunner.__new__(AgentRunner)
        runner.project_root = tmp_path
        runner.logger = FakeLogger()
        runner._running_agents = {}
        assert runner.broadcast_restart_checkpoint() == []
        # 不识别信号的 run（无响应语义）：drain_wait 等待语义不受旗标影响
        runner._running_agents = {"impl-x": SimpleNamespace(poll=lambda: None)}
        import time as _time

        start = _time.time()
        remaining = runner.drain_wait(timeout=0.05)
        assert remaining == ["impl-x"]
        assert _time.time() - start < 5, "排水窗口语义不被广播改变"

    def test_drain_window_short_window_finishes_normally(self, tmp_path):
        """窗口内收尾的 run 正常终态：drain_wait 返回空（正常合并判定前提）。"""
        from core.agent_runner.runner import AgentRunner

        runner = AgentRunner.__new__(AgentRunner)
        runner.project_root = tmp_path
        runner.logger = FakeLogger()
        state = {"poll": None}

        def _poll():
            return state["poll"]

        runner._running_agents = {"impl-finish": SimpleNamespace(poll=_poll)}
        # 模拟窗口内自然收尾：首查存活、其后立刻退出
        calls = {"n": 0}

        def running_ids():
            calls["n"] += 1
            if calls["n"] == 1:
                return ["impl-finish"]
            return []

        runner.running_run_ids = running_ids
        assert runner.drain_wait(timeout=5) == []


# ══════════════════════ 4. bug-found 小缺陷 fastlane（任务 4.3）═════════════


def _make_pipeline(tmp_path: Path, failed_ids: list, state: dict | None = None):
    """构造 fastlane 模块所需的 pipeline 替身（只暴露模块真实消费面）。"""
    from core.pm_engine.verification import fastlane as fl

    logger = FakeLogger()
    state = state if state is not None else {}

    def _bump_counters(spec, deltas):
        # 对齐 StateMachine.bump_counters 契约：各字段下限 0，返回最终生效值
        for field, delta in deltas.items():
            state[field] = max(0, state.get(field, 0) + delta)
        return {field: state[field] for field in deltas}

    ctx = SimpleNamespace(
        project_root=tmp_path,
        state_machine=SimpleNamespace(
            read_one=lambda spec: dict(state),
            update_spec=lambda spec, fields: state.update(fields),
            bump_counters=_bump_counters,
            # fastlane 收敛链（bug-found→implemented→testing）现显式调
            # transition（code-review item 51e7dea98b19），桩恒返回 True
            # 保持既有收敛测试语义。
            transition=lambda *args, **kwargs: True,
        ),
        logger=logger,
        agent_runner=SimpleNamespace(
            _execute_agent=lambda spec, agent_type, run_id: SimpleNamespace(
                success=True, run_id=run_id, error=""
            ),
        ),
    )
    pipe = SimpleNamespace(
        _context=ctx,
        _failed_scenario_ids=lambda spec: list(failed_ids),
        _execute_stage2=lambda spec, verify_dir, scenarios_path, skip_prune=False: (
            None,
            {"scenarios": [
                {"scenario_id": "s0", "status": "pass"},
                {"scenario_id": "s-down", "status": "pass"},
            ], "summary": {"total": 2, "passed": 2, "failed": 0, "errors": 0}},
            True,
            "",
            False,
        ),
        _apply_verified_results=[],
        _apply_verified=lambda spec, judge_result, report: (
            pipe._apply_verified_results.append((spec, judge_result, report))
        ),
    )
    return pipe, fl, logger


class TestMinorDefectFastlane:
    def _seed_fastlane_fixtures(self, tmp_path: Path, failed_count: int = 1):
        """布置三条件判定输入：report、judge_attribution、场景文件、结果文件。"""
        vp = tmp_path / ".fenix" / "verify-progress" / "spec-a"
        vp.mkdir(parents=True, exist_ok=True)
        failed = [
            {"scenario_id": f"s{i}", "status": "failed",
             "attribution": "product-bug: fix core/runner.py"}
            for i in range(failed_count)
        ]
        report = {
            "scenarios": [
                {"scenario_id": "s-dep", "status": "pass"},
                {"scenario_id": "s-down", "depends_on": ["s0"], "status": "pass"},
                *failed,
            ],
            "summary": {"total": 2 + failed_count, "failed": failed_count},
        }
        # 场景文件权威键是 id（TestScenario 契约），须经 load_scenarios 校验
        (vp / "test_scenarios.json").write_text(
            json.dumps([
                {"id": "s-dep", "kind": "cli", "steps": [], "assertions": []},
                {"id": "s0", "kind": "cli", "steps": [], "assertions": []},
                {"id": "s-down", "depends_on": ["s0"], "kind": "cli",
                 "steps": [], "assertions": []},
            ], ensure_ascii=False),
            encoding="utf-8",
        )
        # 条件②：单场景失败 → judge 归因影响面 1 文件（≤3）
        (vp / "judge_attribution.json").write_text(
            json.dumps([{"id": "s0", "attribution": "缺陷在 core/runner.py 与 tests/x.py"}]),
            encoding="utf-8",
        )
        # 条件③：实现结果文件无 dispute/adjudication 条目
        (tmp_path / ".fenix" / ".fenix-run-result.json").write_text(
            json.dumps({"status": "success", "findings": []}), encoding="utf-8"
        )
        # 上一轮完整报告（load_report 读取面）：收敛合并时未实跑场景沿用
        (vp / "report.json").write_text(
            json.dumps({"scenarios": [
                {"scenario_id": "s-dep", "status": "pass"},
                {"scenario_id": "s0", "status": "failed"},
                {"scenario_id": "s-down", "status": "failed"},
            ]}, ensure_ascii=False),
            encoding="utf-8",
        )
        return report

    def test_three_conditions_met_eligible_fastlane(self, tmp_path):
        """三条件全过 → eligible=True、path=fastlane、子集含失败场景+前置+下游。"""
        self._seed_fastlane_fixtures(tmp_path, failed_count=1)
        pipe, fl, _ = _make_pipeline(tmp_path, failed_ids=["s0"])
        decision = fl.evaluate_fastlane(pipe, "spec-a")
        assert decision["eligible"] is True
        assert decision["path"] == "fastlane"
        assert decision["failed_id"] == "s0"
        # 子集 = 失败 s0 ∪ 前置（无）∪ 下游 s-down
        assert set(decision["subset_ids"]) == {"s0", "s-down"}

    def test_multi_failure_falls_back_full_round(self, tmp_path):
        """多场景失败 → 条件①不满足 → 回落整轮 fix SPEC 路径。"""
        self._seed_fastlane_fixtures(tmp_path, failed_count=3)
        pipe, fl, _ = _make_pipeline(tmp_path, failed_ids=["s0", "s1", "s2"])
        decision = fl.evaluate_fastlane(pipe, "spec-a")
        assert decision["eligible"] is False
        assert decision["path"] == "full-round"
        assert any("条件①" in r for r in decision["reasons"])

    def test_dispute_signal_falls_back(self, tmp_path):
        """结果文件 findings 含 dispute 条目 → 条件③不满足 → 回落整轮。"""
        self._seed_fastlane_fixtures(tmp_path, failed_count=1)
        (tmp_path / ".fenix" / ".fenix-run-result.json").write_text(
            json.dumps({"status": "success", "findings": [
                {"type": "deliverable-dispute", "element": "core/x.py"}
            ]}),
            encoding="utf-8",
        )
        pipe, fl, _ = _make_pipeline(tmp_path, failed_ids=["s0"])
        decision = fl.evaluate_fastlane(pipe, "spec-a")
        assert decision["eligible"] is False
        assert any("条件③" in r for r in decision["reasons"])

    def test_missing_attribution_conservatively_falls_back(self, tmp_path):
        """judge 归因产物缺失 → 条件②按不可判定保守回落（与③的 fail-open
        方向相反：证据缺失不误入优化通道）。"""
        self._seed_fastlane_fixtures(tmp_path, failed_count=1)
        (tmp_path / ".fenix" / "verify-progress" / "spec-a"
         / "judge_attribution.json").unlink()
        pipe, fl, _ = _make_pipeline(tmp_path, failed_ids=["s0"])
        decision = fl.evaluate_fastlane(pipe, "spec-a")
        assert decision["eligible"] is False
        assert any("条件②" in r for r in decision["reasons"])

    def test_decision_record_traceable(self, tmp_path):
        """判定过程与所选路径落盘可追溯（fastlane_decision.json）。"""
        self._seed_fastlane_fixtures(tmp_path, failed_count=1)
        pipe, fl, _ = _make_pipeline(tmp_path, failed_ids=["s0"])
        decision = fl.evaluate_fastlane(pipe, "spec-a")
        record_path = fl.fastlane_decision_path(tmp_path, "spec-a")
        assert record_path.exists()
        payload = json.loads(record_path.read_text(encoding="utf-8"))
        assert payload["path"] == decision["path"]
        assert set(payload["conditions"]) == {
            "single_failure", "affected_files", "no_dispute"
        }
        assert payload["conditions"]["no_dispute"]["evidence"], "fail-open 留痕应在场"

    def test_subset_reverify_converges_without_fix_spec(self, tmp_path):
        """承接闭环：code-fix 成功 + 子集重验全过 → 走 _apply_verified 收敛
        （不派生 fix SPEC）、streak 清零、收敛判定留痕。"""
        self._seed_fastlane_fixtures(tmp_path, failed_count=1)
        state: dict = {}
        pipe, fl, _ = _make_pipeline(tmp_path, failed_ids=["s0"], state=state)
        decision = fl.evaluate_fastlane(pipe, "spec-a")
        outcome = fl.dispatch_minor_defect_fastlane(pipe, "spec-a", decision)
        assert outcome["dispatched"] is True
        assert outcome["converged"] is True
        # 收敛走既有 verified 收口（门禁不豁免），judge_result.run_id=code-fix run
        assert len(pipe._apply_verified_results) == 1
        spec, judge_result, merged = pipe._apply_verified_results[0]
        assert judge_result.run_id.startswith("code-fix-fastlane-")
        # 重验报告含全量场景判定：未实跑者沿用上一轮通过结论并标注来源
        by_id = {sc["scenario_id"]: sc for sc in merged["scenarios"]}
        assert by_id["s-dep"]["source"].startswith("carried-over")
        assert merged["summary"]["carried_over"] == 1
        assert state.get(fl.FASTLANE_STREAK_FIELD) == 0

    def test_consecutive_two_failures_force_full_round(self, tmp_path):
        """同一验证轮连续 2 次 fastlane 失败 → 强制回落整轮（不再发起第 3 次）。"""
        self._seed_fastlane_fixtures(tmp_path, failed_count=1)
        state = {"_fastlane_fail_streak": 2, "_verify_fail_rounds": 4}
        pipe, fl, _ = _make_pipeline(tmp_path, failed_ids=["s0"], state=state)
        decision = fl.evaluate_fastlane(pipe, "spec-a")
        assert decision["eligible"] is True  # 三条件仍满足
        outcome = fl.dispatch_minor_defect_fastlane(pipe, "spec-a", decision)
        assert outcome["dispatched"] is False
        assert "强制回落" in outcome["reason"]
        # 已消耗的修复轮次计入预算：_verify_fail_rounds 不被回落清零
        assert state["_verify_fail_rounds"] == 4

    def test_fix_failure_bumps_streak_and_budget(self, tmp_path):
        """单次 fastlane 修复失败 → streak+1 且计入既有验证轮预算。"""
        self._seed_fastlane_fixtures(tmp_path, failed_count=1)
        pipe, fl, _ = _make_pipeline(tmp_path, failed_ids=["s0"])
        pipe._context.agent_runner._execute_agent = (
            lambda spec, agent_type, run_id: SimpleNamespace(
                success=False, run_id=run_id, error="boom"
            )
        )
        decision = fl.evaluate_fastlane(pipe, "spec-a")
        outcome = fl.dispatch_minor_defect_fastlane(pipe, "spec-a", decision)
        assert outcome["dispatched"] is False
        entry = pipe._context.state_machine.read_one("spec-a")
        assert entry[fl.FASTLANE_STREAK_FIELD] == 1
        assert entry["_verify_fail_rounds"] == 1  # 计入既有预算

    def test_subset_scenario_ids_chains(self):
        """子集纯函数：失败场景 ∪ depends_on 前置链（递归）∪ 下游（递归）。"""
        from core.pm_engine.verification.fastlane import subset_scenario_ids

        scenarios = [
            {"id": "a"},
            {"id": "b", "depends_on": ["a"]},
            {"id": "c", "depends_on": ["b"]},   # 前置链两跳
            {"id": "d", "depends_on": ["c"]},   # 下游
            {"id": "e"},                         # 无关
        ]
        assert set(subset_scenario_ids(scenarios, "c")) == {"a", "b", "c", "d"}

    def test_merge_subset_report_carries_over_passes(self):
        """重验报告含全量判定：未实跑场景沿用上一轮通过结论并标注来源。"""
        from core.pm_engine.verification.fastlane import merge_subset_report

        prev = {"scenarios": [
            {"scenario_id": "s1", "status": "pass"},
            {"scenario_id": "s2", "status": "pass"},
            {"scenario_id": "s3", "status": "pass"},
        ]}
        subset = {"scenarios": [
            {"scenario_id": "s1", "status": "pass"},
            {"scenario_id": "s3", "status": "fail"},
        ]}
        merged = merge_subset_report(prev, subset)
        by_id = {sc["scenario_id"]: sc for sc in merged["scenarios"]}
        assert by_id["s2"]["source"].startswith("carried-over")
        assert merged["summary"] == {
            "total": 3, "passed": 2, "failed": 1, "errors": 0,
            "warnings": 0, "blocked_env": 0, "carried_over": 1,
        }


# ════════════════════ 5. spec-review 打回理由结构化（任务 5.3）══════════════


class TestSpecReviewRejectionSchema:
    def test_format_and_substantive_classifications(self):
        """格式/实质打回带分类：合法枚举归一化原样保留（大小写容错）。"""
        assert normalize_rejection_class("format") == "format"
        assert normalize_rejection_class("substantive") == "substantive"
        assert normalize_rejection_class(" Substantive ") == "substantive"

    def test_pass_result_without_field_is_legal(self):
        """通过结果不要求该字段：approved/repaired 结果缺字段合法（读侧只对
        rejected 分桶）。"""
        root = tmp_root = None
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            review_dir = root / ".fenix" / "spec-review" / "spec-ok"
            review_dir.mkdir(parents=True)
            (review_dir / ".fenix-run-result.json").write_text(
                json.dumps({"status": "approved", "summary": "ok"}), encoding="utf-8"
            )
            assert rejection_class_stats(root) == {
                "format": 0, "substantive": 0, "unknown": 0
            }

    def test_legacy_result_without_field_maps_to_unknown(self):
        """存量结果缺字段（或非法值）按 unknown 兼容：解析不失败、归 unknown 桶。"""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            d1 = root / ".fenix" / "spec-review" / "spec-legacy"
            d1.mkdir(parents=True)
            # 存量打回：无 rejection_class 字段
            (d1 / ".fenix-run-result.json").write_text(
                json.dumps({"status": "rejected", "summary": "legacy"}), encoding="utf-8"
            )
            d2 = root / ".fenix" / "spec-review" / "spec-badvalue"
            d2.mkdir(parents=True)
            # 非法值 → unknown
            (d2 / ".fenix-run-result.json").write_text(
                json.dumps({"status": "rejected", "rejection_class": "weird"}),
                encoding="utf-8",
            )
            assert normalize_rejection_class(None) == "unknown"
            assert rejection_class_stats(root) == {
                "format": 0, "substantive": 0, "unknown": 2
            }

    def test_stats_buckets_correct_and_fail_open(self):
        """统计分桶正确：format/substantive/unknown 三桶计数；损坏文件跳过、
        无数据返回空不抛异常。"""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for spec, payload in [
                ("a", {"status": "rejected", "rejection_class": "format"}),
                ("b", {"status": "rejected", "rejection_class": "substantive"}),
                ("c", {"status": "rejected"}),  # 缺字段 → unknown
            ]:
                d = root / ".fenix" / "spec-review" / spec
                d.mkdir(parents=True)
                (d / ".fenix-run-result.json").write_text(
                    json.dumps(payload), encoding="utf-8"
                )
            # 损坏文件 fail-open 跳过
            d = root / ".fenix" / "spec-review" / "broken"
            d.mkdir(parents=True)
            (d / ".fenix-run-result.json").write_text("{not json", encoding="utf-8")
            # 非 rejected 不入桶
            d = root / ".fenix" / "spec-review" / "approved"
            d.mkdir(parents=True)
            (d / ".fenix-run-result.json").write_text(
                json.dumps({"status": "approved", "rejection_class": "format"}),
                encoding="utf-8",
            )
            stats = rejection_class_stats(root)
            assert stats == {"format": 1, "substantive": 1, "unknown": 1}
        # 无数据 spec 返回空值不抛异常
        assert rejection_class_stats(Path("/tmp/definitely-not-a-fenix-project")) == {}

    def test_review_prompt_injects_class_boundary(self):
        """评审 prompt 注入段下发两类边界定义（spec-review.md）。"""
        repo_root = Path(__file__).resolve().parents[1]
        prompt = (repo_root / "agents" / "spec-review.md").read_text(encoding="utf-8")
        assert "rejection_class" in prompt
        assert "`format`" in prompt and "`substantive`" in prompt
        assert "MUST" in prompt  # rejected 时必写的约束注入
