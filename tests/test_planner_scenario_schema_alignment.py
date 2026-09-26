"""场景 schema 单源化回归测试（evo-planner-scenario-schema-alignment）。

覆盖 SPEC 能力 scenario-schema-single-source 的全部 Scenario：
- 4.1 生成侧样例与校验规则一致性（断言必填字段由单源表派生）
- 4.2 单条非法剔除留痕、阶段2 不整轮失败、空集显式退回、预算耗尽显式结束
- 4.3 单源化等价性回归（既有判空语义不变，status_code/latency_under/include_zero）
- 4.4 注入覆盖面回归（planner-plan/fast-track/planner-judge 含 schema 段；
  administrator 不含；改单源常量 → 三分支注入随之变化）
- 4.5 交互契约去噪回归（被剔除场景覆盖的候选归为「条目非法剔除」缺口）
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.verify_engine.scenarios import (
    ASSERTION_REQUIRED_FIELDS,
    ACTION_REQUIRED_FIELDS,
    _field_missing,
    _assert_lookup_value,
    _step_lookup_value,
    validate_scenario_dicts,
    prepare_scenarios_for_write,
    TestStep,
    Assertion,
    TestScenario,
)
from core.verify_scenarios import (
    ScenarioEntry,
    ScenarioSet,
    load_scenario_set,
    save_scenario_set,
    diff_planner_output,
)
from core.pm_engine.verification import VerdictReadResult, VerificationPipeline
from core.state_machine import StateMachine


# ── 夹具 ─────────────────────────────────────────────────────────

class _FakeLogger:
    def __init__(self):
        self.warnings = []
        self.errors = []
        self.infos = []
    def warning(self, *a, **k):
        self.warnings.append((a, k))
    def error(self, *a, **k):
        self.errors.append((a, k))
    def info(self, *a, **k):
        self.infos.append((a, k))


def _make_pm(project_root: Path) -> tuple:
    sm = StateMachine(project_root / ".fenix" / "STATE.md", _FakeLogger())
    pm = MagicMock()
    pm.project_root = project_root
    pm.logger = _FakeLogger()
    pm.state_machine = sm
    return pm, sm


def _setup_spec(tmp_path: Path, spec: str, planner_scenarios: list,
                persisted_entries=None, backup_scenarios=None,
                verify_fail_rounds: int = 0):
    vp = tmp_path / ".fenix" / "verify-progress" / spec
    vp.mkdir(parents=True, exist_ok=True)
    (vp / "test_scenarios.json").write_text(
        json.dumps(planner_scenarios, ensure_ascii=False, indent=2))
    if persisted_entries is not None:
        ss = ScenarioSet(spec, 1, persisted_entries)
        save_scenario_set(tmp_path, ss)
    if backup_scenarios is not None:
        (vp / "_scenarios_full.json").write_text(
            json.dumps(backup_scenarios, ensure_ascii=False, indent=2))
    pm, sm = _make_pm(tmp_path)
    sm.add_spec(spec, {"priority": 5})
    sm.update_spec(spec, {"status": "testing",
                          "_verify_fail_rounds": verify_fail_rounds})
    pm._current_verify_round.return_value = verify_fail_rounds + 1
    return pm, sm


def _valid_web(sid: str) -> dict:
    return {
        "id": sid, "description": f"场景{sid}", "kind": "web",
        "steps": [{"action": "navigate", "value": "http://127.0.0.1:8000/"},
                  {"action": "click", "target": f"#{sid}"}],
        "assertions": [{"type": "element_visible", "selector": f"#{sid}"}],
    }


def _valid_cli(sid: str) -> dict:
    return {
        "id": sid, "description": f"cli 场景{sid}", "kind": "cli",
        "steps": [{"action": "run", "command": "echo hello"}],
        "assertions": [{"type": "output_match", "expected": "hello"}],
    }


# ── 4.1 生成侧样例与校验规则一致性 ────────────────────────────

class TestSchemaSingleSourceConsistency:
    """断言必填字段规则与校验逻辑同源：改单源表 → 校验随之变化。"""

    def test_output_match_requires_expected(self):
        """output_match 缺 expected → 校验拒绝。"""
        errs = validate_scenario_dicts([{
            "id": "x", "kind": "cli",
            "steps": [{"action": "run", "command": "echo x"}],
            "assertions": [{"type": "output_match"}],
        }])
        assert errs
        assert any("output_match" in e and "expected" in e for e in errs)

    def test_json_output_requires_step_and_path(self):
        """json_output 缺 step + path → 两条报错。"""
        errs = validate_scenario_dicts([{
            "id": "x", "kind": "cli",
            "steps": [{"action": "run", "command": "echo x"}],
            "assertions": [{"type": "json_output"}],
        }])
        assert errs
        joined = "；".join(errs)
        assert "step" in joined
        assert "path" in joined

    def test_file_content_requires_path_and_expected(self):
        """file_content 缺 path + expected → 两条报错。"""
        errs = validate_scenario_dicts([{
            "id": "x", "kind": "cli",
            "steps": [{"action": "run", "command": "cat /etc/hosts"}],
            "assertions": [{"type": "file_content"}],
        }])
        assert errs
        joined = "；".join(errs)
        assert "path" in joined
        assert "expected" in joined

    def test_status_code_requires_expected(self):
        """status_code 缺 expected → 报错。"""
        errs = validate_scenario_dicts([{
            "id": "x", "kind": "api",
            "steps": [{"action": "http_request", "method": "GET",
                       "url": "http://localhost/"}],
            "assertions": [{"type": "status_code"}],
        }])
        assert errs
        assert any("status_code" in e and "expected" in e for e in errs)

    def test_api_step_requires_method_and_url(self):
        """http_request 缺 method + url → 两条报错。"""
        errs = validate_scenario_dicts([{
            "id": "x", "kind": "api",
            "steps": [{"action": "http_request"}],
            "assertions": [{"type": "status_code", "expected": 200}],
        }])
        assert errs
        joined = "；".join(errs)
        assert "method" in joined
        assert "url" in joined

    def test_cli_run_requires_command(self):
        """run 步骤缺 command → 报错。"""
        errs = validate_scenario_dicts([{
            "id": "x", "kind": "cli",
            "steps": [{"action": "run"}],
            "assertions": [{"type": "exit_code", "expected": 0}],
        }])
        assert errs
        assert any("command" in e for e in errs)

    def test_valid_complete_scenarios_pass(self):
        """合法完整场景通过校验（所有必填字段齐全）。"""
        errs = validate_scenario_dicts([_valid_cli("c1"), _valid_web("w1")])
        assert errs == []

    def test_field_tables_cover_all_assertion_types(self):
        """单源表覆盖 CLI+API 全部断言类型（无遗漏）。"""
        from core.verify_engine.scenarios import CLI_ASSERTIONS, API_ASSERTIONS
        for atype in CLI_ASSERTIONS:
            assert atype in ASSERTION_REQUIRED_FIELDS or ASSERTION_REQUIRED_FIELDS.get(atype) == (), \
                f"cli 断言 {atype} 未在 ASSERTION_REQUIRED_FIELDS 中登记"
        for atype in API_ASSERTIONS:
            assert atype in ASSERTION_REQUIRED_FIELDS or ASSERTION_REQUIRED_FIELDS.get(atype) == (), \
                f"api 断言 {atype} 未在 ASSERTION_REQUIRED_FIELDS 中登记"

    def test_field_tables_cover_all_action_types(self):
        """ACTION_REQUIRED_FIELDS 覆盖 cli run / api http_request / sse_connect。"""
        assert ("cli", "run") in ACTION_REQUIRED_FIELDS
        assert ("api", "http_request") in ACTION_REQUIRED_FIELDS
        assert ("api", "sse_connect") in ACTION_REQUIRED_FIELDS

    def test_schema_version_written_after_validation(self):
        """合法场景写回后带 schema_version 标记。"""
        raw = [_valid_cli("c1")]
        written = prepare_scenarios_for_write(raw)
        assert all(d.get("schema_version") == 1 for d in written)


# ── 4.3 单源化等价性回归（判空语义不变）───────────────────────

class TestEquivalenceRegression:
    """既有校验的细节差异须原样保留（4.3 锁定）。"""

    def test_status_code_zero_legal(self):
        """status_code expected=0 合法（include_zero 语义：0 非空串/None）。"""
        errs = validate_scenario_dicts([{
            "id": "x", "kind": "api",
            "steps": [{"action": "http_request", "method": "GET",
                       "url": "http://localhost/"}],
            "assertions": [{"type": "status_code", "expected": 0}],
        }])
        assert errs == [], f"expected=0 应合法（HTTP 204 等场景），实际报错: {errs}"

    def test_status_code_empty_invalid(self):
        """status_code expected="" 非法。"""
        errs = validate_scenario_dicts([{
            "id": "x", "kind": "api",
            "steps": [{"action": "http_request", "method": "GET",
                       "url": "http://localhost/"}],
            "assertions": [{"type": "status_code", "expected": ""}],
        }])
        assert errs
        assert any("status_code" in e for e in errs)

    def test_status_code_none_invalid(self):
        """status_code expected=None 非法。"""
        errs = validate_scenario_dicts([{
            "id": "x", "kind": "api",
            "steps": [{"action": "http_request", "method": "GET",
                       "url": "http://localhost/"}],
            "assertions": [{"type": "status_code"}],
        }])
        assert errs

    def test_latency_under_zero_legal(self):
        """latency_under expected=0 合法（include_zero 语义）。"""
        errs = validate_scenario_dicts([{
            "id": "x", "kind": "api",
            "steps": [{"action": "http_request", "method": "GET",
                       "url": "http://localhost/"}],
            "assertions": [{"type": "latency_under", "expected": 0}],
        }])
        assert errs == []

    def test_latency_under_empty_invalid(self):
        """latency_under expected="" 非法。"""
        errs = validate_scenario_dicts([{
            "id": "x", "kind": "api",
            "steps": [{"action": "http_request", "method": "GET",
                       "url": "http://localhost/"}],
            "assertions": [{"type": "latency_under", "expected": ""}],
        }])
        assert errs

    def test_body_contains_empty_expected_invalid(self):
        """body_contains expected="" 非法（post 语义）。"""
        errs = validate_scenario_dicts([{
            "id": "x", "kind": "api",
            "steps": [{"action": "http_request", "method": "GET",
                       "url": "http://localhost/"}],
            "assertions": [{"type": "body_contains", "expected": ""}],
        }])
        assert errs

    def test_sse_event_count_min_zero_legal(self):
        """sse_event_count extra.min=0 合法（include_zero 语义）。"""
        errs = validate_scenario_dicts([{
            "id": "x", "kind": "api",
            "steps": [{"action": "sse_connect", "url": "http://localhost/events"}],
            "assertions": [{"type": "sse_event_count", "min": 0}],
        }])
        assert errs == []

    def test_sse_event_count_min_none_invalid(self):
        """sse_event_count 缺 min → 非法。"""
        errs = validate_scenario_dicts([{
            "id": "x", "kind": "api",
            "steps": [{"action": "sse_connect", "url": "http://localhost/events"}],
            "assertions": [{"type": "sse_event_count"}],
        }])
        assert errs

    def test_file_exists_requires_path_post_semantics(self):
        """file_exists 缺 path → post 语义（缺失即非法）。"""
        errs = validate_scenario_dicts([{
            "id": "x", "kind": "cli",
            "steps": [{"action": "run", "command": "true"}],
            "assertions": [{"type": "file_exists"}],
        }])
        assert errs
        assert any("path" in e for e in errs)

    def test_dir_requires_glob(self):
        """dir_contains 缺 glob → 非法。"""
        errs = validate_scenario_dicts([{
            "id": "x", "kind": "cli",
            "steps": [{"action": "run", "command": "ls"}],
            "assertions": [{"type": "dir_contains"}],
        }])
        assert errs
        assert any("glob" in e for e in errs)

    def test_json_path_requires_path(self):
        """json_path 缺 path → 非法。"""
        errs = validate_scenario_dicts([{
            "id": "x", "kind": "api",
            "steps": [{"action": "http_request", "method": "GET",
                       "url": "http://localhost/"}],
            "assertions": [{"type": "json_path"}],
        }])
        assert errs
        assert any("path" in e for e in errs)

    def test_response_header_requires_header(self):
        """response_header 缺 header → 非法。"""
        errs = validate_scenario_dicts([{
            "id": "x", "kind": "api",
            "steps": [{"action": "http_request", "method": "GET",
                       "url": "http://localhost/"}],
            "assertions": [{"type": "response_header"}],
        }])
        assert errs
        assert any("header" in e for e in errs)

    def test_json_schema_requires_schema(self):
        """json_schema 缺 schema → 非法。"""
        errs = validate_scenario_dicts([{
            "id": "x", "kind": "api",
            "steps": [{"action": "http_request", "method": "GET",
                       "url": "http://localhost/"}],
            "assertions": [{"type": "json_schema"}],
        }])
        assert errs
        assert any("schema" in e for e in errs)

    def test_output_match_valid_with_expected(self):
        """output_match 含 expected → 合法。"""
        errs = validate_scenario_dicts([{
            "id": "x", "kind": "cli",
            "steps": [{"action": "run", "command": "echo hi"}],
            "assertions": [{"type": "output_match", "expected": "hi"}],
        }])
        assert errs == []

    def test_remove_reason_declaration_not_valid(self):
        """纯移除声明条目过不了 validate_scenario_dicts（缺 steps 等），
        但应在 _apply_scenario_freeze 中被特殊保留（3.3 豁免）。"""
        errs = validate_scenario_dicts([{
            "id": "drop-me",
            "remove_reason": "功能已按任务书移除",
        }])
        # 纯移除声明过不了校验——这正是 3.3 豁免的意义
        assert errs


# ── 4.2 预校验剔除与空集兜底 ────────────────────────────────────

class TestPreValidationAndEmptyGuard:
    """4.2：单条非法剔除留痕、阶段2 不整轮失败、空集显式退回、预算耗尽显式结束。"""

    def test_single_invalid_entry_rejected_not_crashing(self):
        """单条非法条目被剔除，其余合法条目照常通过（不整批失败）。"""
        import shutil
        tmp = Path("/tmp/schema-align-test1")
        shutil.rmtree(tmp, ignore_errors=True)
        spec = "test"
        vp = tmp / ".fenix" / "verify-progress" / spec
        vp.mkdir(parents=True, exist_ok=True)
        (vp / "test_scenarios.json").write_text(json.dumps(
            [_valid_web("w1"), {"id": "bad", "description": "缺 steps"}],
            ensure_ascii=False, indent=2))
        try:
            pm, sm = _make_pm(tmp)
            sm.add_spec(spec, {"priority": 5})
            sm.update_spec(spec, {"status": "testing", "_verify_fail_rounds": 0})
            pm._current_verify_round.return_value = 1
            vpipe = VerificationPipeline(pm)
            result = vpipe._apply_scenario_freeze(spec)
            assert "diff" in result
            # 非法条目被剔除，合法 w1 照常在 diff 中
            assert result["diff"].scenario_set is not None
            ids = {e.id for e in result["diff"].scenario_set.scenarios}
            assert "w1" in ids
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_all_invalid_returns_aborted(self):
        """全部条目非法 → 返回 aborted 信号，不写空文件。"""
        import shutil
        tmp = Path("/tmp/schema-align-empty-test")
        shutil.rmtree(tmp, ignore_errors=True)
        vp = tmp / ".fenix" / "verify-progress" / "test"
        vp.mkdir(parents=True, exist_ok=True)
        (vp / "test_scenarios.json").write_text(json.dumps([
            {"id": "a", "description": "缺 kind/steps"},
            {"id": "b", "description": "也缺"},
        ], ensure_ascii=False, indent=2))
        try:
            pm, sm = _make_pm(tmp)
            sm.add_spec("test", {"priority": 5})
            sm.update_spec("test", {"status": "testing", "_verify_fail_rounds": 0})
            pm._current_verify_round.return_value = 1
            vpipe = VerificationPipeline(pm)
            result = vpipe._apply_scenario_freeze("test")
            assert isinstance(result, dict)
            assert result.get("aborted") == "no_valid_scenarios"
            assert "rejected" in result
            assert len(result["rejected"]) == 2
            # 空集判定先于 save_scenario_set：test_scenarios.json 不应被覆写
            final_content = json.loads((vp / "test_scenarios.json").read_text())
            # 原始非法条目仍保留（未被写空或被过滤条目覆盖）
            assert len(final_content) == 2
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_empty_aborted_has_rejected_ids(self):
        """aborted 返回中 rejected 包含场景 id + 缺失字段。"""
        import shutil
        tmp = Path("/tmp/schema-align-reject-detail")
        shutil.rmtree(tmp, ignore_errors=True)
        vp = tmp / ".fenix" / "verify-progress" / "test"
        vp.mkdir(parents=True, exist_ok=True)
        (vp / "test_scenarios.json").write_text(json.dumps([
            # web 场景无 navigate 步骤 → 校验必拒（真正非法条目）
            {"id": "no-navigate", "kind": "web", "steps": []},
        ], ensure_ascii=False, indent=2))
        try:
            pm, sm = _make_pm(tmp)
            sm.add_spec("test", {"priority": 5})
            sm.update_spec("test", {"status": "testing", "_verify_fail_rounds": 0})
            pm._current_verify_round.return_value = 1
            vpipe = VerificationPipeline(pm)
            result = vpipe._apply_scenario_freeze("test")
            assert result.get("aborted") == "no_valid_scenarios"
            assert len(result["rejected"]) == 1
            # rejected 描述应包含场景 id 和错误信息
            desc = result["rejected"][0]
            assert "no-navigate" in desc
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_empty_guard_persisted_set_unchanged(self):
        """空集时持久化集 scenarios.json 保持不变（3.8）。"""
        import shutil
        tmp = Path("/tmp/schema-align-persist-unchanged")
        shutil.rmtree(tmp, ignore_errors=True)
        spec = "test"
        # 预置持久化集
        persisted = [ScenarioEntry("existing", "既有场景", added_in_round=1, kind="web")]
        ss = ScenarioSet(spec, 1, persisted)
        save_scenario_set(tmp, ss)
        # 写非法 planner 产出
        vp = tmp / ".fenix" / "verify-progress" / spec
        vp.mkdir(parents=True, exist_ok=True)
        (vp / "test_scenarios.json").write_text(json.dumps([
            {"id": "bad", "description": "非法"},
        ], ensure_ascii=False, indent=2))
        try:
            pm, sm = _make_pm(tmp)
            sm.add_spec(spec, {"priority": 5})
            sm.update_spec(spec, {"status": "testing", "_verify_fail_rounds": 0})
            pm._current_verify_round.return_value = 1
            vpipe = VerificationPipeline(pm)
            result = vpipe._apply_scenario_freeze(spec)
            assert result.get("aborted") == "no_valid_scenarios"
            # 持久化集不变
            ps = load_scenario_set(tmp, spec)
            assert ps is not None
            assert [e.id for e in ps.scenarios] == ["existing"]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_rejected_ids_and_covers_stored_for_interaction_contract(self):
        """剔除条目 id 与 covers 留痕供交互契约消费（3.10）。"""
        import shutil
        tmp = Path("/tmp/schema-align-rejected-covers")
        shutil.rmtree(tmp, ignore_errors=True)
        spec = "test"
        vp = tmp / ".fenix" / "verify-progress" / spec
        vp.mkdir(parents=True, exist_ok=True)
        (vp / "test_scenarios.json").write_text(json.dumps([
            _valid_web("w1"),
            {"id": "bad", "description": "非法",
             "kind": "web", "covers": ["card-link"]},  # covers 登记
        ], ensure_ascii=False, indent=2))
        try:
            pm, sm = _make_pm(tmp)
            sm.add_spec(spec, {"priority": 5})
            sm.update_spec(spec, {"status": "testing", "_verify_fail_rounds": 0})
            pm._current_verify_round.return_value = 1
            vpipe = VerificationPipeline(pm)
            vpipe._apply_scenario_freeze(spec)
            assert hasattr(vpipe, "_last_freeze_rejected")
            assert "bad" in vpipe._last_freeze_rejected
            assert "card-link" in vpipe._last_freeze_rejected_covers
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_invalid_entry_change_lines_recorded(self):
        """第一遍剔除记录写入 diff.change_lines（报告渲染用）。"""
        import shutil
        tmp = Path("/tmp/schema-align-change-lines")
        shutil.rmtree(tmp, ignore_errors=True)
        spec = "test"
        vp = tmp / ".fenix" / "verify-progress" / spec
        vp.mkdir(parents=True, exist_ok=True)
        (vp / "test_scenarios.json").write_text(json.dumps([
            _valid_web("w1"), {"id": "bad", "description": "非法"},
        ], ensure_ascii=False, indent=2))
        try:
            pm, sm = _make_pm(tmp)
            sm.add_spec(spec, {"priority": 5})
            sm.update_spec(spec, {"status": "testing", "_verify_fail_rounds": 0})
            pm._current_verify_round.return_value = 1
            vpipe = VerificationPipeline(pm)
            result = vpipe._apply_scenario_freeze(spec)
            diff = result["diff"]
            assert any("非法条目" in line for line in diff.change_lines)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_main_path_writeback_writes_valid_subset(self):
        """3.2 主路径写回：剔除后合法子集整体重写 test_scenarios.json，
        阶段2 load_scenarios 不因个别非法条目整轮失败。"""
        import shutil
        from core.verify_engine.scenarios import load_scenarios
        tmp = Path("/tmp/schema-align-main-writeback")
        shutil.rmtree(tmp, ignore_errors=True)
        spec = "test"
        vp = tmp / ".fenix" / "verify-progress" / spec
        vp.mkdir(parents=True, exist_ok=True)
        (vp / "test_scenarios.json").write_text(json.dumps([
            _valid_web("w1"),
            _valid_cli("c1"),
            {"id": "bad", "description": "非法", "kind": "web", "steps": []},
        ], ensure_ascii=False, indent=2))
        try:
            pm, sm = _make_pm(tmp)
            sm.add_spec(spec, {"priority": 5})
            sm.update_spec(spec, {"status": "testing", "_verify_fail_rounds": 0})
            pm._current_verify_round.return_value = 1
            vpipe = VerificationPipeline(pm)
            vpipe._apply_scenario_freeze(spec)
            # 写回文件 = 合法子集（不含 bad）
            written = json.loads((vp / "test_scenarios.json").read_text())
            ids = {s.get("id") for s in written}
            assert ids == {"w1", "c1"}
            # 写回文件必过 load_scenarios 验收（阶段2 不再整轮失败）
            loaded = load_scenarios(vp / "test_scenarios.json")
            assert [s.id for s in loaded] == ["w1", "c1"]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_remove_reason_declaration_preserved_in_diff(self):
        """3.3 移除声明豁免：带 remove_reason 的声明条目不过滤，
        移除理由照常生效（既有场景判 reasoned removed，不判 unreasoned）。"""
        import shutil
        tmp = Path("/tmp/schema-align-remove-reason")
        shutil.rmtree(tmp, ignore_errors=True)
        spec = "test"
        persisted = [ScenarioEntry("keep", "保留", added_in_round=1, kind="web"),
                     ScenarioEntry("drop", "移除", added_in_round=1, kind="web")]
        ss = ScenarioSet(spec, 1, persisted)
        save_scenario_set(tmp, ss)
        vp = tmp / ".fenix" / "verify-progress" / spec
        vp.mkdir(parents=True, exist_ok=True)
        # planner 产出：保留 keep + 声明移除 drop（纯移除声明条目，缺 steps）
        (vp / "test_scenarios.json").write_text(json.dumps([
            _valid_web("keep"),
            {"id": "drop", "remove_reason": "功能已按任务书移除"},
        ], ensure_ascii=False, indent=2))
        try:
            pm, sm = _make_pm(tmp)
            sm.add_spec(spec, {"priority": 5})
            sm.update_spec(spec, {"status": "testing",
                                  "_verify_fail_rounds": 1})
            pm._current_verify_round.return_value = 2
            vpipe = VerificationPipeline(pm)
            result = vpipe._apply_scenario_freeze(spec)
            diff = result["diff"]
            # drop 判为有理由移除，不判 unreasoned_missing（无补齐分支触发）
            assert not diff.unreasoned_missing
            assert any(e.id == "drop" for e, _ in diff.removed)
            assert diff.ok
            # 写回文件 = keep（drop 移除声明不参与写回）
            written = json.loads((vp / "test_scenarios.json").read_text())
            ids = {s.get("id") for s in written}
            assert ids == {"keep"}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ── 4.4 注入覆盖面回归 ──────────────────────────────────────────

# ── 4.2 调用点消费：空集显式退回 plan / 预算耗尽显式结束 ──────

class TestEmptyAbortCallerConsumption(unittest.TestCase):
    """4.2/3.7：阶段1 主路径消费 aborted 信号——
    预算内退回 plan 重排；重排预算耗尽时显式结束本轮（implemented + error），
    0 场景报告不进入裁决路径（洗白路径防线）。"""

    def setUp(self):
        from types import SimpleNamespace
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()
        self.sm = StateMachine(Path(self.tmpdir) / ".fenix" / "STATE.md", self.logger)
        self.engine = PMEngine(self.sm, MagicMock(), {}, Path(self.tmpdir), self.logger)
        self.verify_dir = Path(self.tmpdir) / ".fenix" / "verify-progress" / "demo-spec"
        self.verify_dir.mkdir(parents=True)
        self.scenarios_path = self.verify_dir / "test_scenarios.json"
        self.sm.add_spec("demo-spec", {"priority": 5})
        self.sm.transition("demo-spec", "ready")
        self.sm.transition("demo-spec", "implementing")
        self.sm.transition("demo-spec", "implemented")
        self.sm.transition("demo-spec", "testing")
        self.engine._enqueue = MagicMock()
        # planner 每轮成功出题但产出全部非法（写前预校验整批拒绝）
        self.engine.agent_runner.run_planner = MagicMock(
            return_value=SimpleNamespace(success=True, error=None,
                                         run_id="planner-plan-demo-spec-1-a1"))
        self.engine._verification._read_planner_result = MagicMock(
            return_value=VerdictReadResult.success("plan-ready"))
        self.engine._verification._apply_interaction_contract = MagicMock(return_value=None)
        # 首轮出题前无冻结文件（e3841db4c1c7 删除死函数 _load_frozen_scenarios
        # 后冻结读取已由 _load_frozen_or_escalate 内联承担，无文件自然返回
        # (None, False) 走 replan 循环，无需再桩拦截）

        def _write_invalid_planner(spec_name, agent_type):
            # planner 出题：写入全部非法条目（web 场景缺 navigate 步骤）
            self.scenarios_path.write_text(json.dumps([
                {"id": "bad-1", "kind": "web", "steps": []},
                {"id": "bad-2", "kind": "web", "steps": []},
            ], ensure_ascii=False, indent=2), encoding="utf-8")
            return SimpleNamespace(success=True, error=None,
                                   run_id="planner-plan-demo-spec-1-a1")

        self.engine.agent_runner.run_planner.side_effect = _write_invalid_planner

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_all_invalid_replans_until_budget_then_ends(self):
        """全部非法 → 预算内退回 plan 重排；预算耗尽 → 显式结束 implemented。

        断言 0 场景报告不进入裁决路径：预算耗尽分支置 implemented + error
        （重排预算耗尽），而非继续以 0 场景执行。
        """
        with patch("importlib.reload", lambda m: m):
            self.engine._run_three_stage_verification("demo-spec")
        entry = self.sm.read_one("demo-spec") or {}
        # 预算耗尽显式结束：implemented + error 留痕
        self.assertEqual(entry.get("status"), "implemented", entry)
        self.assertIn("重排预算耗尽", entry.get("error", ""), entry)
        # REPLAN_FEEDBACK.md 已落盘（planner 可见整批拒绝原因）
        fb = self.verify_dir / "REPLAN_FEEDBACK.md"
        self.assertTrue(fb.exists())
        content = fb.read_text(encoding="utf-8")
        self.assertIn("场景写前预校验整批拒绝", content)


class TestSchemaInjectionCoverage:
    """4.4：planner-plan、fast-track、planner-judge 三分支均含 schema 段；
    administrator 不含；改单源常量 → 三分支注入随之变化。"""

    @staticmethod
    def _make_prompt_builder(tmp_path):
        """构造可构建 prompt 的最小 PromptBuilder（含 schema 注入所需单源表）。"""
        proot = tmp_path / "proj"
        proot.mkdir(exist_ok=True)
        (proot / "spec" / "changes" / "test").mkdir(parents=True, exist_ok=True)
        (proot / "spec" / "changes" / "test" / "tasks.md").write_text(
            "# Tasks\n- [ ] 1.1 do it\n")
        from test_agent_runner import make_runner
        runner = make_runner(proot)
        return runner._prompt_builder, proot

    def _build(self, pb_fixture, agent_type: str) -> str:
        """在最小工作目录下构建指定 agent_type 的 prompt。"""
        pb, proot = pb_fixture
        vp = proot / ".fenix" / "verify-progress" / "test"
        vp.mkdir(parents=True, exist_ok=True)
        return pb._build_prompt("test", agent_type)

    def test_planner_plan_injects_schema_section(self, tmp_path):
        """planner-plan prompt 含「场景断言/操作必填字段」注入段。"""
        pb = self._make_prompt_builder(tmp_path)
        prompt = self._build(pb, "planner-plan")
        assert "场景断言/操作必填字段" in prompt
        assert "ASSERTION_REQUIRED_FIELDS" in prompt
        assert "output_match" in prompt

    def test_planner_judge_injects_schema_section(self, tmp_path):
        """planner-judge prompt 含注入段（第三条写入车道）。"""
        pb = self._make_prompt_builder(tmp_path)
        prompt = self._build(pb, "planner-judge")
        assert "场景断言/操作必填字段" in prompt
        assert "json_output" in prompt
        assert "step" in prompt

    def test_fast_track_injects_schema_section(self, tmp_path):
        """fast-track prompt 含注入段（第二条写入车道）。"""
        pb = self._make_prompt_builder(tmp_path)
        prompt = self._build(pb, "fast-track")
        assert "场景断言/操作必填字段" in prompt
        assert "status_code" in prompt

    def test_administrator_does_not_inject_schema_section(self, tmp_path):
        """administrator prompt 不含 schema 注入段（2.4 边界）。"""
        pb = self._make_prompt_builder(tmp_path)
        prompt = self._build(pb, "administrator")
        assert "场景断言/操作必填字段" not in prompt

    def test_schema_section_contains_sample_json(self, tmp_path):
        """注入段含每个必填字段的合法 JSON 样例。"""
        pb = self._make_prompt_builder(tmp_path)
        prompt = self._build(pb, "planner-plan")
        # output_match 样例（合法 JSON 形态：键逗号分隔、无多余引号）
        assert '"expected"' in prompt
        assert '"step"' in prompt
        assert '"method"' in prompt
        assert '"command"' in prompt
        # 样例为合法 JSON 片段：output_match 样例形态
        assert ('{"type": "output_match", "expected": "期望的输出内容"}' in prompt
                or '{"type": "output_match", "expected": "期望的输出内容"}' in prompt)

    def test_sample_json_wellformed(self, tmp_path):
        """每个类型渲染的样例片段均为可解析的合法 JSON 值（键逗号分隔）。"""
        pb = self._make_prompt_builder(tmp_path)
        prompt = self._build(pb, "planner-plan")
        # 样例应含 "type": "..." 合法形态（而非 ""type"" 双引号错误）
        assert '""type""' not in prompt
        # output_match 样例键间有逗号
        assert '"output_match", "expected"' in prompt
        # json_output 样例 step/path 键逗号分隔
        assert '"json_output", "step"' in prompt
        assert '"step": "<run 步骤的 as 命名>", "path"' in prompt

    def test_mutation_to_single_source_table_changes_injection(self, tmp_path):
        """改动 ASSERTION_REQUIRED_FIELDS → 三分支注入文本随之变化（4.4）。"""
        pb = self._make_prompt_builder(tmp_path)
        prompt_before = self._build(pb, "planner-plan")
        orig = ASSERTION_REQUIRED_FIELDS.get("exit_code", ())
        try:
            ASSERTION_REQUIRED_FIELDS["exit_code"] = (
                {"key": "extra.foobar", "short": "foobar",
                 "help": "测试注入同步", "example": '"x"', "mode": "post"},
            )
            prompt_after = self._build(pb, "planner-plan")
            assert "foobar" in prompt_after
            assert "测试注入同步" in prompt_after
            judge_after = self._build(pb, "planner-judge")
            assert "foobar" in judge_after
        finally:
            ASSERTION_REQUIRED_FIELDS["exit_code"] = orig


# ── 4.5 交互契约去噪回归 ────────────────────────────────────────

class TestInteractionContractRejectionDenoise:
    """4.5：被 schema 预校验剔除的场景覆盖的候选归为「条目非法剔除」缺口，
    不触发退回（避免「重排-剔除」循环）。"""

    def _make_vpipe(self, tmpdir: Path):
        """构造带真实目录的 VerificationPipeline（仅消费侧路径）。"""
        vp = tmpdir / ".fenix" / "verify-progress" / "spec-demo"
        vp.mkdir(parents=True, exist_ok=True)
        (vp / "test_scenarios.json").write_text(
            json.dumps([_valid_web("w1")], ensure_ascii=False))
        pm, sm = _make_pm(tmpdir)
        sm.add_spec("spec-demo", {"priority": 5})
        sm.update_spec("spec-demo", {"status": "testing", "_verify_fail_rounds": 0})
        return VerificationPipeline(pm)

    def test_denoise_removes_rejected_covers_from_uncovered(self, tmp_path):
        """被剔除场景 covers 登记的候选从 uncovered 移除，契约判定恢复 ok。"""
        from core.interaction_contract import ContractResult
        with patch(
            "core.interaction_contract.validate_interaction_coverage"
        ) as mock_validate:
            mock_validate.return_value = self._result_with_uncovered(
                ["card-link", "other-link"])
            vpipe = self._make_vpipe(tmp_path)
            # 冻结处留痕：被剔除场景 bad 覆盖了 card-link
            # （3dd5194ce79b 后缓存携带 spec 归属戳，直写缓存需同步登记所有者）
            vpipe._last_freeze_owner = "spec-demo"
            vpipe._last_freeze_rejected = ["bad"]
            vpipe._last_freeze_rejected_covers = {"card-link"}
            ret = vpipe._apply_interaction_contract("spec-demo")
        # card-link 归为「条目非法剔除」缺口 → 从覆盖缺口移除，不再退回；
        # other-link 仍是设计漏项缺口（uncovered 保留）。
        assert ret.get("ok") is False, ret
        assert "other-link" in ret.get("uncovered")
        assert "card-link" not in ret.get("uncovered")

    def test_denoise_only_when_covers_registered(self, tmp_path):
        """未登记 covers 的候选不受剔除去噪影响（按设计漏项判定）。"""
        from core.interaction_contract import ContractResult
        with patch(
            "core.interaction_contract.validate_interaction_coverage"
        ) as mock_validate:
            mock_validate.return_value = self._result_with_uncovered(
                ["click-card"])
            vpipe = self._make_vpipe(tmp_path)
            vpipe._last_freeze_owner = "spec-demo"
            vpipe._last_freeze_rejected = ["bad"]
            vpipe._last_freeze_rejected_covers = {"card-link"}  # 不含 click-card
            ret = vpipe._apply_interaction_contract("spec-demo")
        assert ret.get("ok") is False
        assert "click-card" in ret.get("uncovered")

    @staticmethod
    def _result_with_uncovered(uncovered):
        """构造校验失败结论（未覆盖指定候选）。"""
        from core.interaction_contract import ContractResult
        r = ContractResult()
        r.ok = False
        r.uncovered = list(uncovered)
        r.candidates = []
        return r

    def test_rejected_covers_stored_for_contract(self):
        """冻结处理剔除条目后，covers 留痕可被交互契约消费（集成）。"""
        import shutil
        tmp = Path("/tmp/schema-align-contract-denoise")
        shutil.rmtree(tmp, ignore_errors=True)
        spec = "test"
        vp = tmp / ".fenix" / "verify-progress" / spec
        vp.mkdir(parents=True, exist_ok=True)
        (vp / "test_scenarios.json").write_text(json.dumps([
            _valid_web("w1"),
            {"id": "bad", "description": "非法", "kind": "web",
             "covers": ["card-link"]},
        ], ensure_ascii=False, indent=2))
        try:
            pm, sm = _make_pm(tmp)
            sm.add_spec(spec, {"priority": 5})
            sm.update_spec(spec, {"status": "testing", "_verify_fail_rounds": 0})
            pm._current_verify_round.return_value = 1
            vpipe = VerificationPipeline(pm)
            vpipe._apply_scenario_freeze(spec)
            assert "card-link" in vpipe._last_freeze_rejected_covers
            assert "bad" in vpipe._last_freeze_rejected
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
