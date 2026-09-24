"""frozen-scenario-reservoir 回归测试（fix-frozen-scenario-orphan-reservoir）。

覆盖 SPEC 能力：
  - 场景三文件写端 schema 门（validate_scenario_dicts / validate_scenario_entries /
    save_scenario_set 写端拦截 / _apply_scenario_freeze 补齐写回拦截）
  - 补齐占位改弃场景（_scenarios_full.json 缺定义时不写占位，登记剔除）
  - 持久化集加载净化（load_scenario_set 剔除缺 kind 条目，不改文件）
  - 重跑消费硬门（错误清单相同/超集 → 拒绝重跑走升级；错误减少 → 允许重跑）
  - _escalate_env_blocked 冻结转人工附 planner run 成本

测试全部使用 tmp_path 隔离，不触碰主树 .fenix 真实数据。
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.verify_engine.scenarios import validate_scenario_dicts
from core.verify_scenarios import (
    ScenarioEntry,
    ScenarioSet,
    load_scenario_set,
    save_scenario_set,
    diff_planner_output,
    render_change_section,
)
from core.pm_engine.verification import VerificationPipeline
from core.state_machine import StateMachine


# ── 夹具 ─────────────────────────────────────────────────────────

def _valid_web_scenario(sid: str) -> dict:
    """构造一个合法的 web 场景 dict（通过 validate_scenario_dicts）。"""
    return {
        "id": sid,
        "description": f"场景 {sid} 描述",
        "kind": "web",
        "steps": [
            {"action": "navigate", "value": "http://127.0.0.1:8000/", "target": ""},
            {"action": "click", "target": f"#{sid}-btn", "value": ""},
        ],
        "assertions": [
            {"type": "element_visible", "selector": f"#{sid}-result", "label": "结果可见"},
        ],
    }


class _FakeLogger:
    """静默 logger：捕获调用供断言检查。"""
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


def _make_pm(project_root: Path) -> MagicMock:
    """构造轻量 mock PMEngine（仅满足 VerificationPipeline 需要的属性）。"""
    sm = StateMachine(project_root / ".fenix" / "STATE.md", _FakeLogger())
    pm = MagicMock()
    pm.project_root = project_root
    pm.logger = _FakeLogger()
    pm.state_machine = sm
    return pm, sm


def _setup_spec(tmp_path: Path, spec: str, planner_scenarios: list,
                persisted_entries: list = None, backup_scenarios: list = None,
                verify_fail_rounds: int = 0):
    """构建 freeze 所需的目录结构 + mock PM。"""
    vp = tmp_path / ".fenix" / "verify-progress" / spec
    vp.mkdir(parents=True)
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
    sm.update_spec(spec, {"status": "testing", "_verify_fail_rounds": verify_fail_rounds})
    # _current_verify_round 走 PMEngine 方法 → mock 返回固定值
    pm._current_verify_round.return_value = verify_fail_rounds + 1
    return pm, sm


# ── 1. 结构校验函数 ─────────────────────────────────────────────

class TestValidateScenarioDicts:
    """validate_scenario_dicts 单元测试（D1 单一来源）。"""

    def test_valid_scenario_no_errors(self):
        sc = _valid_web_scenario("s1")
        errs = validate_scenario_dicts([sc])
        assert errs == []

    def test_invalid_kind_gets_error(self):
        sc = _valid_web_scenario("s2")
        sc["kind"] = "nonexistent"
        errs = validate_scenario_dicts([sc])
        assert any("未知 kind" in e or "nonexistent" in e for e in errs)

    def test_missing_steps_gets_error(self):
        sc = {"id": "s3", "description": "desc", "kind": "web", "steps": [], "assertions": []}
        errs = validate_scenario_dicts([sc])
        assert any("navigate" in e for e in errs)

    def test_missing_kind_key_gets_error(self):
        # kind 缺省为 web（from_dict 语义），但缺 steps/navigate 校验失败
        sc = {"id": "s4", "description": "desc", "steps": [], "assertions": []}
        errs = validate_scenario_dicts([sc])
        assert len(errs) >= 1
        assert any("navigate" in e for e in errs)

    def test_non_dict_item_handled(self):
        errs = validate_scenario_dicts(["not-a-dict", 123])
        assert len(errs) >= 2

    def test_empty_list_ok(self):
        assert validate_scenario_dicts([]) == []


# ── 2. 持久化集加载净化 ──────────────────────────────────────────

class TestLoadScenarioSetPurification:
    """load_scenario_set 加载净化（D4：剔除无 kind 条目，不改文件）。"""

    def test_purges_no_kind_entries(self, tmp_path: Path):
        """缺/非法 kind 条目兜底归类 web 保留在集，不再剔除（b25b28a4ed8a：
        剔除会把存量无 kind 冻结集清成空集写回；仅非对象条目仍剔除）。"""
        spec = "test-purge"
        vp = tmp_path / ".fenix" / "verify-progress" / spec
        vp.mkdir(parents=True)
        raw = {
            "spec": spec,
            "round": 1,
            "scenarios": [
                {"id": "no-kind-1", "description": "兜底1", "added_in_round": 1},
                {"id": "no-kind-2", "description": "兜底2", "added_in_round": 1},
                {"id": "web-ok", "description": "正常web", "added_in_round": 1, "kind": "web"},
                {"id": "cli-ok", "description": "正常cli", "added_in_round": 1, "kind": "cli"},
            ],
        }
        (vp / "scenarios.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2))
        result = load_scenario_set(tmp_path, spec)
        assert result is not None
        assert result.ids == {"no-kind-1", "no-kind-2", "web-ok", "cli-ok"}
        assert len(result.scenarios) == 4
        by_id = {e.id: e for e in result.scenarios}
        assert by_id["no-kind-1"].kind == "web"
        assert by_id["no-kind-2"].kind == "web"
        assert by_id["cli-ok"].kind == "cli"

    def test_purification_does_not_modify_file(self, tmp_path: Path):
        """净化只影响内存集合，不改写 scenarios.json。"""
        spec = "test-no-modify"
        vp = tmp_path / ".fenix" / "verify-progress" / spec
        vp.mkdir(parents=True)
        raw = {
            "spec": spec,
            "round": 1,
            "scenarios": [
                {"id": "orphan", "description": "孤儿", "added_in_round": 1},
                {"id": "valid", "description": "正常", "added_in_round": 1, "kind": "web"},
            ],
        }
        fpath = vp / "scenarios.json"
        fpath.write_text(json.dumps(raw, ensure_ascii=False, indent=2))
        original_content = fpath.read_text()
        load_scenario_set(tmp_path, spec)
        assert fpath.read_text() == original_content, "文件不应被加载过程改写"

    def test_all_entries_valid_no_purge(self, tmp_path: Path):
        """所有条目都有 kind → 不剔除。"""
        spec = "test-all-valid"
        vp = tmp_path / ".fenix" / "verify-progress" / spec
        vp.mkdir(parents=True)
        raw = {
            "spec": spec,
            "round": 1,
            "scenarios": [
                {"id": "s1", "description": "d1", "added_in_round": 1, "kind": "web"},
                {"id": "s2", "description": "d2", "added_in_round": 1, "kind": "cli"},
            ],
        }
        (vp / "scenarios.json").write_text(json.dumps(raw))
        result = load_scenario_set(tmp_path, spec)
        assert result is not None
        assert result.ids == {"s1", "s2"}

    def test_missing_file_returns_none(self, tmp_path: Path):
        assert load_scenario_set(tmp_path, "nonexistent") is None


# ── 3. save_scenario_set 写端门 ──────────────────────────────────

class TestSaveScenarioSetSchemaGate:
    """save_scenario_set 写端校验：坏条目剔除，合法部分落盘。"""

    def test_rejects_invalid_kind_and_keeps_valid(self, tmp_path: Path):
        spec = "test-gate"
        entry_bad = ScenarioEntry("bad-entry", description="孤儿", added_in_round=1)
        # 构造 kind 字段非法的 ScenarioEntry
        object.__setattr__(entry_bad, "kind", "")
        entry_good = ScenarioEntry("good-entry", description="正常", added_in_round=1, kind="cli")
        ss = ScenarioSet(spec, 1, [entry_bad, entry_good])
        path = save_scenario_set(tmp_path, ss)
        data = json.loads(path.read_text())
        ids = {s["id"] for s in data["scenarios"]}
        assert ids == {"good-entry"}, "坏条目应被剔除，只留合法条目"
        # 重读验证 round-trip
        loaded = load_scenario_set(tmp_path, spec)
        assert loaded is not None
        assert loaded.ids == {"good-entry"}

    def test_all_valid_writes_normally(self, tmp_path: Path):
        spec = "test-all-valid-write"
        entries = [ScenarioEntry(f"s{i}", kind="web") for i in range(3)]
        ss = ScenarioSet(spec, 1, entries)
        path = save_scenario_set(tmp_path, ss)
        data = json.loads(path.read_text())
        assert len(data["scenarios"]) == 3
        # to_dict 现在总是写 kind
        for s in data["scenarios"]:
            assert "kind" in s


# ── 4. 写端门拦截 _apply_scenario_freeze ─────────────────────────

class TestApplyScenarioFreezeSchemaGate:
    """_apply_scenario_freeze 写端门：planner 产出含非法条目时剔除不整批拒绝。"""

    def _setup_spec(self, tmp_path: Path, spec: str, planner_scenarios: list,
                    persisted_entries: list = None, backup_scenarios: list = None,
                    verify_fail_rounds: int = 0):
        """构建 freeze 所需的目录结构。"""
        vp = tmp_path / ".fenix" / "verify-progress" / spec
        vp.mkdir(parents=True)
        (vp / "test_scenarios.json").write_text(
            json.dumps(planner_scenarios, ensure_ascii=False, indent=2))
        if persisted_entries is not None:
            ss = ScenarioSet(spec, 1, persisted_entries)
            save_scenario_set(tmp_path, ss)
        if backup_scenarios is not None:
            (vp / "_scenarios_full.json").write_text(
                json.dumps(backup_scenarios, ensure_ascii=False, indent=2))
        # STATE
        pm, sm = _make_pm(tmp_path)
        sm.add_spec(spec, {"priority": 5})
        sm.update_spec(spec, {"status": "testing", "_verify_fail_rounds": verify_fail_rounds})
        return pm, sm

    def test_invalid_planner_entries_rejected_not_crashing(self, tmp_path: Path):
        """planner 产出含非法条目时剔除（warn），不崩溃，change_lines 记录剔除。"""
        spec = "test-reject"
        valid = _valid_web_scenario("good")
        invalid = {"id": "bad", "description": "缺 kind/steps"}  # 缺 steps → 校验失败
        pm, sm = _setup_spec(tmp_path, spec, [valid, invalid])
        vpipe = VerificationPipeline(pm)
        result = vpipe._apply_scenario_freeze(spec)
        assert "diff" in result
        diff = result["diff"]
        # 应有剔除记录
        assert any("非法条目" in line for line in diff.change_lines)

    def test_backup_updated_only_when_all_valid(self, tmp_path: Path):
        """含非法条目时 _scenarios_full.json 不更新（保留旧备份）。"""
        spec = "test-backup-gate"
        valid = _valid_web_scenario("ok")
        bad = {"id": "bad", "description": "no kind"}
        old_backup = [_valid_web_scenario("old-backup")]
        pm, sm = _setup_spec(tmp_path, spec, [valid, bad],
                              backup_scenarios=old_backup)
        vp = tmp_path / ".fenix" / "verify-progress" / spec
        vpipe = VerificationPipeline(pm)
        vpipe._apply_scenario_freeze(spec)
        backup = json.loads((vp / "_scenarios_full.json").read_text())
        assert backup == old_backup, "备份未更新时应保留旧内容"

    def test_all_valid_planner_updates_backup(self, tmp_path: Path):
        """planner 产出全部合法时 _scenarios_full.json 正常更新。"""
        spec = "test-backup-ok"
        scenarios = [_valid_web_scenario(f"s{i}") for i in range(3)]
        pm, sm = _setup_spec(tmp_path, spec, scenarios)
        vpipe = VerificationPipeline(pm)
        vpipe._apply_scenario_freeze(spec)
        vp = tmp_path / ".fenix" / "verify-progress" / spec
        backup = json.loads((vp / "_scenarios_full.json").read_text())
        assert len(backup) == 3


# ── 5. 补齐占位改弃场景 ──────────────────────────────────────────

class TestReconcileUnrecoverableDrop:
    """_apply_scenario_freeze 补齐路径：备份缺定义时弃场景不写占位。"""

    def test_backup_lacks_definition_drops_no_placeholder(self, tmp_path: Path):
        """无理由缺失 + 备份缺定义 → 不写 {"id","description"} 占位，登记剔除。"""
        spec = "test-drop"
        planner = [_valid_web_scenario("s1")]
        persisted = [
            ScenarioEntry("s1", "场景一", added_in_round=1, kind="web"),
            ScenarioEntry("s2", "场景二", added_in_round=1, kind="web"),
        ]
        backup = [_valid_web_scenario("s1")]
        pm, sm = _setup_spec(tmp_path, spec, planner,
                              persisted_entries=persisted,
                              backup_scenarios=backup)
        vpipe = VerificationPipeline(pm)
        result = vpipe._apply_scenario_freeze(spec)
        diff = result["diff"]
        # 应有「定义不可恢复」剔除记录
        assert any("定义不可恢复" in line for line in diff.change_lines)
        vp = tmp_path / ".fenix" / "verify-progress" / spec
        reconciled = json.loads((vp / "test_scenarios.json").read_text())
        ids = {s.get("id") for s in reconciled}
        assert "s2" not in ids, "缺定义的场景不应被写入占位"

    def test_backup_has_definition_restores(self, tmp_path: Path):
        """无理由缺失 + 备份有完整定义 → 正常补回。"""
        spec = "test-restore"
        planner = [_valid_web_scenario("s1")]
        persisted = [
            ScenarioEntry("s1", "场景一", added_in_round=1, kind="web"),
            ScenarioEntry("s2", "场景二", added_in_round=1, kind="web"),
        ]
        backup = [_valid_web_scenario("s1"), _valid_web_scenario("s2")]
        pm, sm = _setup_spec(tmp_path, spec, planner,
                              persisted_entries=persisted,
                              backup_scenarios=backup)
        vpipe = VerificationPipeline(pm)
        result = vpipe._apply_scenario_freeze(spec)
        diff = result["diff"]
        assert any("无理由缺失" in line for line in diff.change_lines)
        vp = tmp_path / ".fenix" / "verify-progress" / spec
        reconciled = json.loads((vp / "test_scenarios.json").read_text())
        ids = {s.get("id") for s in reconciled}
        assert "s2" in ids, "有定义的缺失场景应被正常补回"


# ── 6. 消费硬门 ─────────────────────────────────────────────────

class TestReplanConsumptionGate:
    """重跑消费硬门（D5）：错误清单相同/超集 → 拒绝重跑走升级。"""

    def test_identical_errors_returns_true(self):
        prev = ["场景a缺少 navigate 步骤", "场景b断言1: 未知类型"]
        cur = ["场景a缺少 navigate 步骤", "场景b断言1: 未知类型"]
        assert VerificationPipeline._replan_errors_unconsumed(prev, cur) is True

    def test_superset_errors_returns_true(self):
        prev = ["错误1", "错误2"]
        cur = ["错误1", "错误2", "错误3"]
        assert VerificationPipeline._replan_errors_unconsumed(prev, cur) is True

    def test_reduced_errors_returns_false(self):
        prev = ["错误1", "错误2", "错误3"]
        cur = ["错误1"]
        assert VerificationPipeline._replan_errors_unconsumed(prev, cur) is False

    def test_changed_errors_returns_false(self):
        prev = ["错误1", "错误2"]
        cur = ["错误3", "错误4"]
        assert VerificationPipeline._replan_errors_unconsumed(prev, cur) is False

    def test_empty_prev_returns_false(self):
        assert VerificationPipeline._replan_errors_unconsumed([], ["x"]) is False

    def test_empty_cur_with_prev_returns_false(self):
        assert VerificationPipeline._replan_errors_unconsumed(["x"], []) is False


class TestExtractReplanErrorItems:
    """_extract_replan_error_items 解析：提取验收错误中的逐条清单。"""

    def test_extracts_bullets(self):
        text = (
            "场景文件包含 3 个错误:\n"
            "  - 场景'a'缺少 navigate 步骤\n"
            "  - 场景'b'断言0: 未知类型 foo\n"
            "  - 场景'c'步骤1: 需要 target 选择器\n"
        )
        items = VerificationPipeline._extract_replan_error_items(text)
        assert len(items) == 3
        assert "navigate" in items[0]

    def test_fallback_to_full_text(self):
        text = "应用仍不可达：已自动执行 commands.start"
        items = VerificationPipeline._extract_replan_error_items(text)
        assert items == [text]

    def test_empty_returns_empty(self):
        assert VerificationPipeline._extract_replan_error_items("") == []


# ── 7. 冻结转人工附 planner 成本 ─────────────────────────────────

class TestLastPlannerRunCost:
    """_last_planner_run_cost：从 STATE + run 记录提取成本摘要。"""

    def test_returns_cost_when_available(self, tmp_path: Path):
        spec = "test-cost"
        pm, sm = _make_pm(tmp_path)
        sm.add_spec(spec, {"priority": 1})
        sm.update_spec(spec, {
            "_cost_usd": 176.5,
            "_tokens_in": 261418932,
        })
        # 模拟 planner-plan run 记录
        runs_dir = tmp_path / ".fenix" / "runs"
        runs_dir.mkdir(parents=True)
        run_path = runs_dir / f"planner-plan-{spec}-1788950000-a1.jsonl"
        result_event = json.dumps({
            "type": "result",
            "total_cost_usd": 4.27,
            "duration_ms": 3661000,
            "num_turns": 49,
            "usage": {"input_tokens": 418963, "output_tokens": 41367},
        })
        run_path.write_text(result_event + "\n")
        vpipe = VerificationPipeline(pm)
        summary = vpipe._last_planner_run_cost(spec)
        assert "$176" in summary
        assert "261" in summary  # tokens in M
        assert "1.0 小时" in summary  # 3661s ≈ 1.0h

    def test_returns_empty_when_no_data(self, tmp_path: Path):
        spec = "no-data"
        pm, sm = _make_pm(tmp_path)
        sm.add_spec(spec, {"priority": 1})
        vpipe = VerificationPipeline(pm)
        assert vpipe._last_planner_run_cost(spec) == ""


if __name__ == "__main__":
    unittest.main()
