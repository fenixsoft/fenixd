"""Characterization tests for core/pm_engine/verification.py 目标方法（tasks 1.2）。

锁定以下方法的可观测行为（输入/输出/副作用），作为重构后的回归基线：
  - _apply_scenario_freeze
  - _env_whitewash_gate
  - _verified_gate_refuses
  - _record_verdict_adoption
  - _handle_env_blocked_inconclusive
  - _run_scenario_static_check

只记录可观测行为，不写实现逻辑断言——重构时保证这些行为不变。
"""

import json
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.pm_engine.verification import VerificationPipeline, VerdictReadResult


# ── 夹具 ────────────────────────────────────────────────────────────────────────


class _FakeLogger:
    """最小 logger：记录所有调用供断言检查。"""
    def __init__(self):
        self.warnings = []
        self.errors = []
        self.infos = []
        self.calls = []

    def debug(self, *a, **k):
        self.calls.append(("debug", a, k))

    def warning(self, *a, **k):
        self.warnings.append((a, k))
        self.calls.append(("warning", a, k))

    def error(self, *a, **k):
        self.errors.append((a, k))
        self.calls.append(("error", a, k))

    def info(self, *a, **k):
        self.infos.append((a, k))
        self.calls.append(("info", a, k))


def _make_pm(project_root: Path):
    """构造最小 PMEngine mock，满足 VerificationPipeline 对 self._pm 的所有访问。"""
    from core.state_machine import StateMachine
    sm_state_path = project_root / ".fenix" / "STATE.md"
    sm_state_path.parent.mkdir(parents=True, exist_ok=True)
    logger = _FakeLogger()
    sm = StateMachine(sm_state_path, logger)
    pm = MagicMock()
    pm.project_root = project_root
    pm.logger = logger
    pm.state_machine = sm
    pm.agent_runner = MagicMock()
    pm._get_config = MagicMock(return_value=3)
    return pm, sm, logger


def _base_setup(spec="my-spec"):
    """返回 (tmpdir, project_root, pm, sm, logger, verify_dir)。"""
    tmpdir = tempfile.mkdtemp()
    project_root = Path(tmpdir)
    (project_root / ".fenix").mkdir(parents=True, exist_ok=True)
    (project_root / "spec" / "changes" / spec / "specs" / "cap-a").mkdir(
        parents=True, exist_ok=True
    )
    (project_root / "spec" / "changes" / spec / "specs" / "cap-a" / "spec.md"
    ).write_text("# Spec\nInitial.", encoding="utf-8")
    pm, sm, logger = _make_pm(project_root)
    sm.add_spec(spec, {"priority": 5})
    for s in ("ready", "implementing", "implemented", "testing"):
        sm.transition(spec, s)
    vp = project_root / ".fenix" / "verify-progress" / spec
    vp.mkdir(parents=True, exist_ok=True)
    # scenarios.json（spec 戳需要）
    (vp / "scenarios.json").write_text(
        json.dumps({
            "spec": spec, "round": 1,
            "scenarios": [{"id": "s1", "kind": "cli",
                           "description": "场景1", "added_in_round": 1}],
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    # mock _current_verify_round（save_scenario_set 序列化时需要）
    pm._current_verify_round = MagicMock(return_value=1)
    return tmpdir, project_root, pm, sm, logger, vp


def _teardown(tmpdir):
    shutil.rmtree(tmpdir, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════════
# _handle_env_blocked_inconclusive characterization
# ═══════════════════════════════════════════════════════════════════════════════

class TestHandleEnvBlockedInconclusive:
    """锁定 _handle_env_blocked_inconclusive 的可观测行为。"""

    def test_non_inconclusive_returns_false(self):
        """有真实失败（failed>0）→ 非 inconclusive，返回 False。"""
        tmpdir, root, pm, sm, lg, vp = _base_setup()
        try:
            pipe = VerificationPipeline(pm)
            report = {
                "summary": {"blocked_env": 2, "failed": 1, "errors": 0},
                "scenarios": [],
            }
            result = pipe._handle_env_blocked_inconclusive("my-spec", report)
            assert result is False
            # spec 应保持 testing 状态（未被修改）
            entry = sm.read_one("my-spec")
            assert entry["status"] == "testing"
        finally:
            _teardown(tmpdir)

    def test_zero_blocked_env_returns_false(self):
        """blocked_env=0 → 非 inconclusive，返回 False。"""
        tmpdir, root, pm, sm, lg, vp = _base_setup()
        try:
            pipe = VerificationPipeline(pm)
            report = {"summary": {"blocked_env": 0, "failed": 0, "errors": 0}}
            result = pipe._handle_env_blocked_inconclusive("my-spec", report)
            assert result is False
        finally:
            _teardown(tmpdir)

    def test_first_inconclusive_sets_implemented_requeues(self):
        """首轮 inconclusive：status 回 implemented，_inconclusive_attempts=1，
        enqueue verifier（返回 True 表示已处理）。"""
        tmpdir, root, pm, sm, lg, vp = _base_setup()
        try:
            pm._enqueue = MagicMock()
            pipe = VerificationPipeline(pm)
            report = {
                "summary": {"blocked_env": 3, "failed": 0, "errors": 0},
                "scenarios": [
                    {"status": "blocked-env", "env_probe_detail": "port unreachable"},
                ],
            }
            result = pipe._handle_env_blocked_inconclusive("my-spec", report)
            assert result is True
            entry = sm.read_one("my-spec")
            assert entry["status"] == "implemented"
            assert entry.get("_inconclusive_attempts") == "1"
            pm._enqueue.assert_called_once_with("my-spec", "verifier")
        finally:
            _teardown(tmpdir)

    def test_second_inconclusive_parallel_decreases(self):
        """第二轮 inconclusive：attempts=2 → _verify_parallel_override
        按 base>>1 降档（base=3，降后 1）。"""
        tmpdir, root, pm, sm, lg, vp = _base_setup()
        try:
            pm._enqueue = MagicMock()
            pm._get_config = MagicMock(return_value=5)  # base=5
            sm.update_spec("my-spec", {"_inconclusive_attempts": 1})
            pipe = VerificationPipeline(pm)
            report = {"summary": {"blocked_env": 3, "failed": 0, "errors": 0}}
            result = pipe._handle_env_blocked_inconclusive("my-spec", report)
            assert result is True
            entry = sm.read_one("my-spec")
            assert entry.get("_inconclusive_attempts") == "2"
            # base=5, attempts=2 → max(1, 5>>1) = max(1,2) = 2。
            # evo-fix-verify-parallel-override-type 3.2：parse 侧 int|None 归一
            # 后 STATE.md 往返读值为 int 2（原为 str "2"）。
            assert entry.get("_verify_parallel_override") == 2
        finally:
            _teardown(tmpdir)

    def test_health_round_resets_parallel_override(self):
        """真实失败（非 inconclusive）→ 复位 _verify_parallel_override=None。"""
        tmpdir, root, pm, sm, lg, vp = _base_setup()
        try:
            sm.update_spec("my-spec", {
                "_inconclusive_attempts": 2,
                "_verify_parallel_override": 1,
            })
            pipe = VerificationPipeline(pm)
            report = {"summary": {"blocked_env": 1, "failed": 1, "errors": 0}}
            result = pipe._handle_env_blocked_inconclusive("my-spec", report)
            assert result is False
            entry = sm.read_one("my-spec")
            assert entry.get("_verify_parallel_override") is None
        finally:
            _teardown(tmpdir)


# ═══════════════════════════════════════════════════════════════════════════════
# _env_whitewash_gate characterization
# ═══════════════════════════════════════════════════════════════════════════════

class TestEnvWhitewashGate:
    """锁定 _env_whitewash_gate 的可观测行为。"""

    def test_no_violations_returns_true(self):
        """洗白无违规 → True（放行）。"""
        tmpdir, root, pm, sm, lg, vp = _base_setup()
        try:
            pipe = VerificationPipeline(pm)
            with patch("core.verdict_check.load_report") as mock_lr, \
                 patch("core.verdict_check.whitewash_violations") as mock_wv:
                mock_lr.return_value = {"scenarios": [{"id": "s1"}]}
                mock_wv.return_value = []  # 无违规
                result = pipe._env_whitewash_gate("my-spec")
            assert result is True
        finally:
            _teardown(tmpdir)

    def test_violations_returns_false_and_escalates(self):
        """洗白有违规 → False（已处置），调用 _escalate_env_blocked。"""
        tmpdir, root, pm, sm, lg, vp = _base_setup()
        try:
            pipe = VerificationPipeline(pm)
            pipe._escalate_env_blocked = MagicMock()
            with patch("core.verdict_check.load_report") as mock_lr, \
                 patch("core.verdict_check.whitewash_violations") as mock_wv:
                mock_lr.return_value = {"scenarios": [{"id": "s1"}]}
                mock_wv.return_value = ["无真实通过场景"]
                result = pipe._env_whitewash_gate("my-spec")
            assert result is False
            # exemption_effective：豁免有效命中轮标记（evo-fix-env-exemption-gate-conflict
            # 1.3/2.2）——本用例 STATE 无豁免登记 → False（既有的计冻结轮语义不变）
            pipe._escalate_env_blocked.assert_called_once_with(
                "my-spec", ["无真实通过场景"], exemption_effective=False
            )
            # logger.warning 被调用（洗白拦截）
            assert any("洗白门禁拦截" in str(c) for c in lg.warnings)
        finally:
            _teardown(tmpdir)

    def test_empty_scenarios_returns_true_conservatively(self):
        """report 缺位/无场景数据 → 保守放行（True）。"""
        tmpdir, root, pm, sm, lg, vp = _base_setup()
        try:
            pipe = VerificationPipeline(pm)
            with patch("core.verdict_check.load_report") as mock_lr:
                mock_lr.return_value = None
                result = pipe._env_whitewash_gate("my-spec")
            assert result is True
        finally:
            _teardown(tmpdir)


# ═══════════════════════════════════════════════════════════════════════════════
# _verified_gate_refuses characterization
# ═══════════════════════════════════════════════════════════════════════════════

class TestVerifiedGateRefuses:
    """锁定 _verified_gate_refuses 的可观测行为。"""

    def test_no_stability_data_returns_false(self):
        """无 verdict_stability.json → 门不生效（返回 False）。"""
        tmpdir, root, pm, sm, lg, vp = _base_setup()
        try:
            pipe = VerificationPipeline(pm)
            result = pipe._verified_gate_refuses("my-spec", "bug-found")
            assert result is False
        finally:
            _teardown(tmpdir)

    def test_verified_and_stamp_matches_refuses(self):
        """verified 落盘 + spec 戳匹配 → 拒绝降级（返回 True）。"""
        from core.verify_report import (
            compute_spec_stamp, record_verdict_round,
            VERDICT_STABILITY_FILENAME,
        )
        tmpdir, root, pm, sm, lg, vp = _base_setup()
        try:
            stamp = compute_spec_stamp(root, "my-spec")
            data = {
                "stamp": stamp,
                "report_mtime_ns": 123456789,
                "rounds": [{"status": "verified", "failed_ids": [], "at": "2026-09-01"}],
            }
            (vp / VERDICT_STABILITY_FILENAME).write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8")
            pipe = VerificationPipeline(pm)
            result = pipe._verified_gate_refuses("my-spec", "bug-found")
            assert result is True
            # logger.warning 被调用（拒绝降级）
            assert any("拒绝被覆盖" in str(c) for c in lg.warnings)
        finally:
            _teardown(tmpdir)

    def test_stamp_changed_returns_false(self):
        """场景集变更（stamp 不匹配）→ 门失效（返回 False）。"""
        from core.verify_report import (
            compute_spec_stamp, VERDICT_STABILITY_FILENAME,
        )
        tmpdir, root, pm, sm, lg, vp = _base_setup()
        try:
            old_stamp = compute_spec_stamp(root, "my-spec")
            data = {
                "stamp": old_stamp,
                "rounds": [{"status": "verified", "failed_ids": [], "at": "2026-09-01"}],
            }
            (vp / VERDICT_STABILITY_FILENAME).write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8")
            # 修改场景使 stamp 变化
            (vp / "scenarios.json").write_text(
                json.dumps({
                    "spec": "my-spec", "round": 2,
                    "scenarios": [
                        {"id": "s1", "kind": "cli",
                         "description": "场景1", "added_in_round": 1},
                        {"id": "s2", "kind": "cli",
                         "description": "新增场景", "added_in_round": 2},
                    ],
                }, ensure_ascii=False), encoding="utf-8")
            pipe = VerificationPipeline(pm)
            result = pipe._verified_gate_refuses("my-spec", "bug-found")
            assert result is False
        finally:
            _teardown(tmpdir)


# ═══════════════════════════════════════════════════════════════════════════════
# _record_verdict_adoption characterization
# ═══════════════════════════════════════════════════════════════════════════════

class TestRecordVerdictAdoption:
    """锁定 _record_verdict_adoption 的可观测行为。"""

    def test_verified_clears_judge_rerun_count(self):
        """verified 落定 → judge_rerun_count 归零，_judge_cap_frozen=False。"""
        from core.verify_report import VERDICT_STABILITY_FILENAME
        tmpdir, root, pm, sm, lg, vp = _base_setup()
        try:
            sm.update_spec("my-spec", {
                "_judge_rerun_count": 3,
                "_judge_cap_frozen": True,
            })
            pipe = VerificationPipeline(pm)
            pipe._record_verdict_adoption("my-spec", "verified", report={})
            entry = sm.read_one("my-spec")
            assert entry.get("_judge_rerun_count") == "0"
            assert entry.get("_judge_cap_frozen") is False
            # verdict_stability.json 被写入
            assert (vp / VERDICT_STABILITY_FILENAME).exists()
        finally:
            _teardown(tmpdir)

    def test_bug_found_does_not_clear_judge_count(self):
        """bug-found 落定 → judge_rerun_count 不清零（失败链中计数跨轮累计）。"""
        from core.verify_report import VERDICT_STABILITY_FILENAME
        tmpdir, root, pm, sm, lg, vp = _base_setup()
        try:
            sm.update_spec("my-spec", {
                "_judge_rerun_count": 2,
                "_judge_cap_frozen": False,
            })
            pipe = VerificationPipeline(pm)
            pipe._record_verdict_adoption("my-spec", "bug-found", report={})
            entry = sm.read_one("my-spec")
            assert entry.get("_judge_rerun_count") == "2"  # 未清零
            assert entry.get("_judge_cap_frozen") is False
        finally:
            _teardown(tmpdir)


# ═══════════════════════════════════════════════════════════════════════════════
# _run_scenario_static_check characterization
# ═══════════════════════════════════════════════════════════════════════════════

class TestRunScenarioStaticCheck:
    """锁定 _run_scenario_static_check 的可观测行为（fail-open 不阻断）。"""

    def test_missing_scenarios_file_does_not_raise(self):
        """test_scenarios.json 不存在 → 静默返回，不写 findings。"""
        tmpdir, root, pm, sm, lg, vp = _base_setup()
        try:
            pipe = VerificationPipeline(pm)
            pipe._run_scenario_static_check("my-spec")
            # 无异常抛出（fail-open）
        finally:
            _teardown(tmpdir)

    def test_non_list_content_does_not_raise(self):
        """test_scenarios.json 内容非 list → 静默返回。"""
        tmpdir, root, pm, sm, lg, vp = _base_setup()
        try:
            (vp / "test_scenarios.json").write_text(
                json.dumps({"not": "a list"}), encoding="utf-8")
            pipe = VerificationPipeline(pm)
            pipe._run_scenario_static_check("my-spec")
        finally:
            _teardown(tmpdir)

    def test_valid_scenarios_calls_scan_scenarios(self):
        """合法场景文件 → 调用 scan_scenarios + write_findings。"""
        tmpdir, root, pm, sm, lg, vp = _base_setup()
        try:
            scenarios = [
                {"id": "s1", "kind": "web", "description": "场景1",
                 "steps": [
                     {"action": "navigate", "value": "http://localhost:19099/"},
                     {"action": "wait", "target": ".x", "description": "等待"},
                 ],
                 "assertions": [
                     {"type": "element_visible", "selector": ".x", "label": "可见"},
                 ]},
            ]
            (vp / "test_scenarios.json").write_text(
                json.dumps(scenarios, ensure_ascii=False), encoding="utf-8")
            pipe = VerificationPipeline(pm)
            with patch("core.verify_engine.scenario_static_check.scan_scenarios") as mock_scan, \
                 patch("core.verify_engine.scenario_static_check.write_findings") as mock_wf:
                mock_scan.return_value = []  # 无 findings
                pipe._run_scenario_static_check("my-spec")
            mock_scan.assert_called_once()
            mock_wf.assert_called_once_with(root, "my-spec", [])
        finally:
            _teardown(tmpdir)

    def test_exception_does_not_raise_fail_open(self):
        """scan_scenarios 抛异常 → WARNING 记录，不阻断（fail-open）。"""
        tmpdir, root, pm, sm, lg, vp = _base_setup()
        try:
            scenarios = [{"id": "s1", "kind": "web", "description": "场景1",
                          "steps": [{"action": "navigate",
                                     "value": "http://localhost:19099/"}],
                          "assertions": []}]
            (vp / "test_scenarios.json").write_text(
                json.dumps(scenarios, ensure_ascii=False), encoding="utf-8")
            pipe = VerificationPipeline(pm)
            with patch("core.verify_engine.scenario_static_check.scan_scenarios",
                       side_effect=RuntimeError("boom")):
                pipe._run_scenario_static_check("my-spec")
            # 异常被吞掉，WARNING 记录
            assert any("fail-open" in str(c) for c in lg.warnings)
        finally:
            _teardown(tmpdir)


# ═══════════════════════════════════════════════════════════════════════════════
# _apply_scenario_freeze characterization (补充)
# ═══════════════════════════════════════════════════════════════════════════════

class TestApplyScenarioFreeze:
    """锁定 _apply_scenario_freeze 的可观测行为。"""

    def test_missing_scenarios_returns_empty(self):
        """test_scenarios.json 不存在 → 返回空 dict。"""
        tmpdir, root, pm, sm, lg, vp = _base_setup()
        try:
            # 删除 test_scenarios.json（不在首次出题场景下）
            (vp / "test_scenarios.json").unlink(missing_ok=True)
            sm.update_spec("my-spec", {"status": "testing"})
            pipe = VerificationPipeline(pm)
            result = pipe._apply_scenario_freeze("my-spec")
            assert result == {}
        finally:
            _teardown(tmpdir)

    def test_invalid_json_returns_empty(self):
        """test_scenarios.json 非法 JSON → 返回空 dict。"""
        tmpdir, root, pm, sm, lg, vp = _base_setup()
        try:
            (vp / "test_scenarios.json").write_text("NOT JSON", encoding="utf-8")
            sm.update_spec("my-spec", {"status": "testing"})
            pipe = VerificationPipeline(pm)
            result = pipe._apply_scenario_freeze("my-spec")
            assert result == {}
        finally:
            _teardown(tmpdir)

    def test_all_invalid_returns_aborted(self):
        """全部条目非法 → 返回 aborted + rejected 列表，不写空文件。"""
        tmpdir, root, pm, sm, lg, vp = _base_setup()
        try:
            bad_scenarios = [
                {"id": "a", "description": "缺 kind/steps"},
                {"id": "b", "description": "也缺"},
            ]
            (vp / "test_scenarios.json").write_text(
                json.dumps(bad_scenarios, ensure_ascii=False), encoding="utf-8")
            sm.update_spec("my-spec", {"status": "testing"})
            pipe = VerificationPipeline(pm)
            result = pipe._apply_scenario_freeze("my-spec")
            assert result.get("aborted") == "no_valid_scenarios"
            assert len(result.get("rejected", [])) == 2
            # test_scenarios.json 未被覆写
            final = json.loads((vp / "test_scenarios.json").read_text(encoding="utf-8"))
            assert len(final) == 2
        finally:
            _teardown(tmpdir)

    def test_partial_invalid_filters_and_returns_diff(self):
        """混合合法/非法 → 合法条目进入 diff，非法被剔除。"""
        tmpdir, root, pm, sm, lg, vp = _base_setup()
        try:
            scenarios = [
                {"id": "good1", "kind": "web", "description": "好场景1",
                 "steps": [{"action": "navigate",
                            "value": "http://localhost:19099/"}],
                 "assertions": []},
                {"id": "bad1", "description": "缺 kind/steps"},
            ]
            (vp / "test_scenarios.json").write_text(
                json.dumps(scenarios, ensure_ascii=False), encoding="utf-8")
            sm.update_spec("my-spec", {"status": "testing"})
            pipe = VerificationPipeline(pm)
            result = pipe._apply_scenario_freeze("my-spec")
            assert "diff" in result
            assert result["diff"].scenario_set is not None
            ids = {e.id for e in result["diff"].scenario_set.scenarios}
            assert "good1" in ids
            assert "bad1" not in ids
        finally:
            _teardown(tmpdir)

    def test_sets_last_scenario_diff(self):
        """冻结后 self._last_scenario_diff 被设置（供报告渲染读取）。"""
        tmpdir, root, pm, sm, lg, vp = _base_setup()
        try:
            scenarios = [{"id": "g1", "kind": "web", "description": "OK",
                          "steps": [{"action": "navigate",
                                     "value": "http://localhost:19099/"}],
                          "assertions": []}]
            (vp / "test_scenarios.json").write_text(
                json.dumps(scenarios, ensure_ascii=False), encoding="utf-8")
            sm.update_spec("my-spec", {"status": "testing"})
            pipe = VerificationPipeline(pm)
            result = pipe._apply_scenario_freeze("my-spec")
            assert pipe._last_scenario_diff is result["diff"]
        finally:
            _teardown(tmpdir)
