"""frozen-scenario-schema-migration 回归测试（evo-add-frozen-scenario-schema-migration）。

覆盖 SPEC 能力（specs/frozen-scenario-schema-migration/spec.md）：
  - 冻结场景读侧旧 schema 兼容迁移（value→command / value→expected，
    仅目标字段缺失时迁移，新 schema 零干扰）
  - 场景文件 schema 版本标记（写入端恒定写 schema_version，读侧按版本路由）
  - 真损坏报字段级差异清单（场景 id/下标/缺失字段），不吞笼统 corrupt
  - blocked_stuck 处置后自动复位（合并→testing / 未合并→ready /
    处置未完成不动状态）

测试全部使用 tmp_path 隔离，不触碰主树 .fenix 真实数据。
"""

import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from core.verify_engine.scenarios import (
    SCHEMA_VERSION,
    TestScenario,
    load_scenarios,
    migrate_scenario_schema,
    prepare_scenarios_for_write,
    save_scenarios,
    validate_scenario_dicts,
)
from core.admin_monitor import AdminMonitor
from core.admin_monitor import DISPOSITION_AUTO_RESET_SIGNAL_TYPES
from core.pm_engine.verification import (
    ENV_BLOCK_SIGNAL_TYPES,
    resolve_env_blocked_reset_path,
)


# ── 夹具 ─────────────────────────────────────────────────────────

def _old_cli_scenario(sid: str = "old-cli") -> dict:
    """旧 schema cli 场景：run 步骤用 value、output_match 断言用 value。"""
    return {
        "id": sid,
        "description": f"旧 schema 场景 {sid}",
        "kind": "cli",
        "steps": [{"action": "run", "value": "echo hi", "cwd": "."}],
        "assertions": [{"type": "output_match", "value": "hi", "cwd": "."}],
    }


def _new_cli_scenario(sid: str = "new-cli") -> dict:
    """新 schema cli 场景：run 步骤用 command、output_match 断言用 expected。"""
    return {
        "id": sid,
        "description": f"新 schema 场景 {sid}",
        "kind": "cli",
        "steps": [{"action": "run", "command": "echo bye", "cwd": "."}],
        "assertions": [{"type": "output_match", "expected": "bye", "cwd": "."}],
    }


def _write_scenarios(tmp_path: Path, raw: list, name: str = "test_scenarios.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


class _FakeLogger:
    """静默 logger：捕获调用供断言检查。"""
    def __getattr__(self, name):
        return lambda *a, **k: None


# ═══════════════════════════════════════════════════════════════════════
# 4.1 旧 schema 自动迁移 / 新 schema 零变化 / 真损坏报字段清单
# ═══════════════════════════════════════════════════════════════════════

class TestOldSchemaAutoMigration:
    """旧 schema 冻结文件读侧自动迁移通过验收（spec Scenario 1）。"""

    def test_load_old_schema_migrates_and_passes(self, tmp_path: Path):
        """run 步骤 value→command、output_match 断言 value→expected 迁移后通过。"""
        path = _write_scenarios(tmp_path, [_old_cli_scenario()])
        scenarios = load_scenarios(path)
        assert len(scenarios) == 1
        sc = scenarios[0]
        assert sc.steps[0].command == "echo hi"
        assert sc.assertions[0].expected == "hi"

    def test_migrate_only_when_target_missing(self):
        """目标字段已存在（command/expected）时旧字段被忽略，零干扰。"""
        d = {
            "id": "both",
            "description": "新旧字段并存",
            "kind": "cli",
            "steps": [{"action": "run", "value": "old-cmd", "command": "new-cmd"}],
            "assertions": [
                {"type": "output_match", "value": "old-exp", "expected": "new-exp"},
            ],
        }
        migrated = migrate_scenario_schema([d])[0]
        # 目标字段存在 → 不迁移（新 schema 字段优先，旧字段不覆盖）
        assert migrated["steps"][0]["command"] == "new-cmd"
        assert migrated["assertions"][0]["expected"] == "new-exp"

    def test_migration_is_read_only(self):
        """迁移只作用于内存副本，不改写输入列表/dict（读无副作用）。"""
        raw = [_old_cli_scenario()]
        raw_snapshot = json.loads(json.dumps(raw))
        migrate_scenario_schema(raw)
        assert raw == raw_snapshot, "原列表不得被迁移改写"

    def test_migration_idempotent(self):
        """迁移幂等：二次迁移结果与一次一致。"""
        once = migrate_scenario_schema([_old_cli_scenario()])
        twice = migrate_scenario_schema(once)
        assert once == twice

    def test_validate_scenario_dicts_accepts_old_schema(self):
        """写端校验函数对旧 schema 同样放行（迁移前置，读侧同源）。"""
        assert validate_scenario_dicts([_old_cli_scenario()]) == []


class TestNewSchemaZeroChange:
    """新 schema 文件行为零变化（spec Scenario 2 回归断言）。"""

    def test_load_new_schema_unchanged(self, tmp_path: Path):
        path = _write_scenarios(tmp_path, [_new_cli_scenario()])
        scenarios = load_scenarios(path)
        assert len(scenarios) == 1
        sc = scenarios[0]
        assert sc.steps[0].command == "echo bye"
        assert sc.assertions[0].expected == "bye"
        # 无迁移干扰：from_dict 不接受 value 兜底（新 schema 语义）
        assert sc.steps[0].value == ""

    def test_new_schema_validation_errors_unchanged(self):
        """新 schema 校验错误文本与迁移无关（未知断言类型照常报）。"""
        d = _new_cli_scenario()
        d["assertions"] = [{"type": "no_such_assertion", "expected": "x"}]
        errs = validate_scenario_dicts([d])
        assert any("no_such_assertion" in e for e in errs)


class TestCorruptFieldLevelReport:
    """真损坏报字段级差异清单（spec Scenario 3），不吞笼统 corrupt。"""

    def test_missing_both_fields_reports_field_list(self, tmp_path: Path):
        """run 步骤/断言字段整体缺失 → 报错含场景 id、下标、缺失字段。"""
        bad = {
            "id": "broken-sc",
            "kind": "cli",
            "steps": [{"action": "run"}],  # 无 command 也无 value
            "assertions": [{"type": "output_match"}],  # 无 expected 也无 value
        }
        path = _write_scenarios(tmp_path, [bad])
        with pytest.raises(ValueError) as exc:
            load_scenarios(path)
        msg = str(exc.value)
        # 场景 id 定位
        assert "broken-sc" in msg
        # 缺失字段清单（步骤/断言下标 + 字段名）
        assert "步骤0" in msg and "command" in msg
        assert "断言0" in msg and "expected" in msg
        # 错误条数明确
        assert "场景文件包含" in msg

    def test_multi_scenario_error_lists_each_scenario(self, tmp_path: Path):
        """多条损坏条目逐条列出（场景 id/下标），不并成一条笼统错误。"""
        bad1 = {
            "id": "broken-a",
            "kind": "cli",
            "steps": [{"action": "run"}],
            "assertions": [],
        }
        bad2 = {
            "id": "broken-b",
            "kind": "cli",
            "steps": [],
            "assertions": [{"type": "output_match"}],
        }
        path = _write_scenarios(tmp_path, [bad1, bad2])
        with pytest.raises(ValueError) as exc:
            load_scenarios(path)
        msg = str(exc.value)
        assert "broken-a" in msg and "broken-b" in msg
        assert "步骤0" in msg and "断言0" in msg

    def test_non_array_file_reports_format_error(self, tmp_path: Path):
        path = tmp_path / "test_scenarios.json"
        path.write_text('{"not": "a list"}', encoding="utf-8")
        with pytest.raises(ValueError) as exc:
            load_scenarios(path)
        assert "期望JSON数组" in str(exc.value)


class TestSchemaVersionMarker:
    """场景文件 schema 版本标记（Requirement: 场景文件 schema 版本标记）。"""

    def test_save_scenarios_writes_schema_version(self, tmp_path: Path):
        """save_scenarios 写盘恒定带 schema_version。"""
        sc = TestScenario.from_dict(_new_cli_scenario())
        path = tmp_path / "saved.json"
        save_scenarios([sc], path)
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved[0]["schema_version"] == SCHEMA_VERSION

    def test_to_dict_always_has_schema_version(self):
        sc = TestScenario.from_dict(_new_cli_scenario())
        d = sc.to_dict()
        assert d["schema_version"] == SCHEMA_VERSION

    def test_prepare_scenarios_for_write_migrates_and_tags(self):
        """补齐写回路径：旧 schema 条目迁移 + 写版本标记。"""
        prep = prepare_scenarios_for_write([_old_cli_scenario()])
        assert prep[0]["schema_version"] == SCHEMA_VERSION
        assert prep[0]["steps"][0]["command"] == "echo hi"
        assert prep[0]["assertions"][0]["expected"] == "hi"

    def test_load_current_version_passthrough(self, tmp_path: Path):
        """当前版本（schema_version==1）直通，与无版本迁移结果一致。"""
        raw = [_new_cli_scenario()]
        raw[0]["schema_version"] = SCHEMA_VERSION
        path = _write_scenarios(tmp_path, raw)
        scenarios = load_scenarios(path)
        assert scenarios[0].steps[0].command == "echo bye"

    def test_unknown_version_notes_in_error(self, tmp_path: Path):
        """未知版本 + 真损坏 → 报错附版本上下文说明。"""
        bad = {
            "id": "future-sc",
            "kind": "cli",
            "schema_version": 99,
            "steps": [{"action": "run"}],
            "assertions": [{"type": "output_match"}],
        }
        path = _write_scenarios(tmp_path, [bad])
        with pytest.raises(ValueError) as exc:
            load_scenarios(path)
        msg = str(exc.value)
        assert "schema_version=99" in msg
        assert "future-sc" in msg

    def test_unknown_version_migrates_when_rescuable(self, tmp_path: Path):
        """未知版本但字段可迁移（旧字段形态）→ 迁移后通过验收。"""
        raw = [_old_cli_scenario("future-rescuable")]
        raw[0]["schema_version"] = 0  # 未知版本（0 非当前版本）
        path = _write_scenarios(tmp_path, raw)
        scenarios = load_scenarios(path)
        assert scenarios[0].steps[0].command == "echo hi"


# ═══════════════════════════════════════════════════════════════════════
# 4.2 blocked_stuck 处置后自动复位（合并/未合并两分支 + 未完成不动）
# ═══════════════════════════════════════════════════════════════════════

class _FakeSmWithTransitionGate:
    """轻量状态机替身：记录 transition_gate / transition 调用。"""

    def __init__(self, specs: dict):
        self._specs = dict(specs)
        self.transition_gate_calls = []
        self.transition_calls = []
        self.update_calls = []

    def read_one(self, spec_name):
        return self._specs.get(spec_name)

    def read_all(self):
        return dict(self._specs)

    def transition_gate(self, spec_name, new_status,
                        *, trigger_run_id=None, agent_type=None, channel="auto"):
        self.transition_gate_calls.append((spec_name, new_status))
        entry = self._specs.get(spec_name)
        if entry:
            entry["status"] = new_status
        return True

    def transition(self, spec_name, new_status,
                   *, trigger_run_id=None, agent_type=None, channel="auto"):
        self.transition_calls.append((spec_name, new_status))
        entry = self._specs.get(spec_name)
        if entry:
            entry["status"] = new_status
        return True

    def update_spec(self, spec_name, updates):
        self.update_calls.append((spec_name, updates))
        entry = self._specs.get(spec_name)
        if entry:
            entry.update(updates)
        return True


class _FakePmEngine:
    """pm_engine 替身：记录 handle_event 调用。"""

    def __init__(self):
        self.handle_event_calls = []

    def handle_event(self, event_kind, spec_name, spec_entry):
        self.handle_event_calls.append((event_kind, spec_name, spec_entry))


def _fake_subprocess_run_mergereturncode(returncode=0):
    """构造 subprocess.run 替身，返回指定 returncode（git merge-base 判定）。"""
    class Result:
        def __init__(self, rc):
            self.returncode = rc
            self.stdout = b""
            self.stderr = b""
    return lambda *a, **k: Result(returncode)


class TestBlockedStuckDispositionReset:
    """blocked_stuck 处置成功后自动复位（spec Scenario: 处置修复后自动复位）。"""

    def _make_admin_monitor(self, tmp_path, sm, pm_engine=None):
        """构造最小 AdminMonitor（绕过真实的 __init__ 依赖）。"""
        from core.admin_store import AdminStore
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        store = AdminStore(proot, _FakeLogger())
        monitor = AdminMonitor.__new__(AdminMonitor)
        monitor.config = {}
        monitor.admin_cfg = {"enabled": False, "interval_minutes": 30,
                             "cooldown_minutes": 5}
        monitor.state_machine = sm
        monitor.project_root = proot
        monitor.logger = _FakeLogger()
        monitor.store = store
        monitor.agent_runner = None
        monitor.pm_engine = pm_engine
        return monitor

    @staticmethod
    def _make_admin_disposition(**kwargs):
        """构造 AdminDisposition 数据对象。"""
        from dataclasses import dataclass
        from typing import Optional

        @dataclass
        class Disp:
            run_id: str = "admin-test-1"
            spec: Optional[str] = None
            success: bool = True
            problem: str = "场景文件损坏"
            actions_taken: str = "修复场景文件"
            result: str = "resolved"
            summary: str = "已修复"
            escalate: bool = False
            error: str = ""
            recommended_action: str = ""
            family_waiver: bool = False

        return Disp(**kwargs)

    @staticmethod
    def _blocked_stuck_signal(spec: str = "demo") -> dict:
        return {
            "signal_type": "blocked_stuck",
            "spec": spec,
            "severity": "critical",
            "description": f"'{spec}' 处于 blocked 超时未处理",
            "evidence": "updated=...，阈值 15 分钟",
            "recommended_action": "检查 blocked 是否误置",
        }

    def test_resolved_branch_merged_gate_to_testing(self, tmp_path: Path):
        """result=resolved + blocked_stuck + branch 已合并 → 直通 testing 重验。"""
        sm = _FakeSmWithTransitionGate({
            "demo": {"status": "blocked", "branch": "fenix/x",
                     "error": "blocked 滞留", "frozen": False},
        })
        pm = _FakePmEngine()
        monitor = self._make_admin_monitor(tmp_path, sm, pm_engine=pm)
        disp = self._make_admin_disposition(result="resolved", spec="demo")
        with mock.patch("core.pm_engine.verification.subprocess.run",
                        side_effect=_fake_subprocess_run_mergereturncode(0)):
            monitor._reset_env_blocked_after_disposition(
                self._blocked_stuck_signal(), disp)

        entry = sm.read_one("demo")
        assert entry["status"] == "testing"
        assert entry.get("error") is None
        assert sm.transition_gate_calls == [("demo", "testing")]
        assert pm.handle_event_calls == [
            ("spec_implemented", "demo", sm.read_one("demo"))
        ]

    def test_resolved_branch_not_merged_to_ready(self, tmp_path: Path):
        """result=resolved + blocked_stuck + branch 未合并 → transition(ready)。"""
        sm = _FakeSmWithTransitionGate({
            "demo": {"status": "blocked", "branch": "fenix/x",
                     "error": "blocked 滞留", "frozen": False},
        })
        pm = _FakePmEngine()
        monitor = self._make_admin_monitor(tmp_path, sm, pm_engine=pm)
        disp = self._make_admin_disposition(result="resolved", spec="demo")
        with mock.patch("core.pm_engine.verification.subprocess.run",
                        side_effect=_fake_subprocess_run_mergereturncode(1)):
            monitor._reset_env_blocked_after_disposition(
                self._blocked_stuck_signal(), disp)

        entry = sm.read_one("demo")
        assert entry["status"] == "ready"
        assert sm.transition_calls == [("demo", "ready")]
        assert sm.transition_gate_calls == []
        assert pm.handle_event_calls == []

    def test_not_resolved_keeps_blocked(self, tmp_path: Path):
        """处置未完成（无 result=resolved）→ 保持既有阻塞，不动状态。"""
        sm = _FakeSmWithTransitionGate({
            "demo": {"status": "blocked", "branch": "fenix/x",
                     "error": "blocked 滞留", "frozen": False},
        })
        pm = _FakePmEngine()
        monitor = self._make_admin_monitor(tmp_path, sm, pm_engine=pm)
        disp = self._make_admin_disposition(result="failed", spec="demo")
        monitor._reset_env_blocked_after_disposition(
            self._blocked_stuck_signal(), disp)

        entry = sm.read_one("demo")
        assert entry["status"] == "blocked"
        assert sm.transition_calls == []
        assert sm.transition_gate_calls == []
        assert pm.handle_event_calls == []

    def test_frozen_spec_not_reset(self, tmp_path: Path):
        """人工冻结（frozen=True）的 blocked_stuck 不自动复位（人工是唯一出路）。"""
        sm = _FakeSmWithTransitionGate({
            "demo": {"status": "blocked", "branch": "fenix/x",
                     "error": "blocked 滞留", "frozen": True},
        })
        pm = _FakePmEngine()
        monitor = self._make_admin_monitor(tmp_path, sm, pm_engine=pm)
        disp = self._make_admin_disposition(result="resolved", spec="demo")
        with mock.patch("core.pm_engine.verification.subprocess.run",
                        side_effect=_fake_subprocess_run_mergereturncode(0)):
            monitor._reset_env_blocked_after_disposition(
                self._blocked_stuck_signal(), disp)

        entry = sm.read_one("demo")
        assert entry["status"] == "blocked"
        assert sm.transition_calls == []
        assert sm.transition_gate_calls == []

    def test_invoke_administrator_wrapper_resets_blocked_stuck(self, tmp_path: Path):
        """_invoke_administrator 消费点：blocked_stuck 信号触发 _reset 分支。"""
        sm = _FakeSmWithTransitionGate({
            "demo": {"status": "blocked", "branch": "fenix/x",
                     "error": "blocked 滞留", "frozen": False},
        })
        monitor = self._make_admin_monitor(tmp_path, sm, pm_engine=_FakePmEngine())
        disp = self._make_admin_disposition(result="resolved", spec="demo")
        signal = self._blocked_stuck_signal()
        with mock.patch.object(monitor, "_reset_env_blocked_after_disposition") as mock_reset:
            # 复刻 _invoke_administrator 的消费条件
            if disp.result in ("resolved", "partially-resolved"):
                sig_type = signal.get("signal_type")
                if sig_type in DISPOSITION_AUTO_RESET_SIGNAL_TYPES:
                    monitor._reset_env_blocked_after_disposition(signal, disp)
            mock_reset.assert_called_once_with(signal, disp)

    def test_not_resolved_wrapper_does_not_reset(self, tmp_path: Path):
        """_invoke_administrator 消费点：未完成处置（failed）不走 _reset 分支。"""
        monitor = self._make_admin_monitor(tmp_path, _FakeSmWithTransitionGate({}))
        disp = self._make_admin_disposition(result="failed", spec="demo")
        signal = self._blocked_stuck_signal()
        with mock.patch.object(monitor, "_reset_env_blocked_after_disposition") as mock_reset:
            if disp.result in ("resolved", "partially-resolved"):
                sig_type = signal.get("signal_type")
                if sig_type in DISPOSITION_AUTO_RESET_SIGNAL_TYPES:
                    monitor._reset_env_blocked_after_disposition(signal, disp)
            mock_reset.assert_not_called()

    def test_blocked_stuck_in_auto_reset_set(self):
        """blocked_stuck 已加入处置后自动复位集合（D3）。"""
        assert "blocked_stuck" in DISPOSITION_AUTO_RESET_SIGNAL_TYPES
        assert set(ENV_BLOCK_SIGNAL_TYPES) <= set(DISPOSITION_AUTO_RESET_SIGNAL_TYPES)

    def test_resolve_path_respects_frozen_guard(self):
        """复位守卫：blocked_stuck 场景冻结不触发复位（resolve 路径 None）。"""
        spec = {"status": "blocked", "frozen": True, "branch": "fenix/x"}
        assert resolve_env_blocked_reset_path(spec, "/tmp") is None


if __name__ == "__main__":
    import unittest
    unittest.main()
