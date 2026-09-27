"""frozen-contract-versioning 回归测试（evo-frozen-scenario-contract-versioning）。

覆盖 SPEC 能力（specs/verification-scenario-freeze/spec.md）：
  - 冻结场景条目级 contract_version 字段（缺失/非整型视为 1）与写端恒定盖戳
  - migrate_frozen_contract 纯函数（v1→v2 navigate 补齐 / 幂等 / 跳版本 /
    未登记版本段 fail-closed / 空集与全过时语义）
  - pipeline._load_frozen_or_escalate 调用点（原始 JSON 读入 → 版本路由 →
    迁移 → 备份/写回 → 最后才 load_scenarios 验收；全场景过时回落出题通道）

测试全部使用 tmp_path 隔离，不触碰主树 .fenix 真实数据。
"""

import json
from pathlib import Path
from unittest import mock

import pytest

from core.verify_engine.scenarios import (
    CONTRACT_VERSION_FIELD,
    CURRENT_CONTRACT_VERSION,
    SCHEMA_VERSION,
    _migrate_contract_to_v2,
    frozen_contract_version,
    migrate_frozen_contract,
    prepare_scenarios_for_write,
    validate_scenario_dicts,
)
import core.verify_engine.scenarios as scenarios_mod
from core.pm_engine.verification import VerificationPipeline
from core.state_machine import StateMachine


# ── 夹具 ─────────────────────────────────────────────────────────

def _valid_web_scenario(sid: str, *, contract_version: int = 1) -> dict:
    """合法 web 场景（缺 navigate 时作为待迁移输入）。"""
    return {
        "id": sid,
        "description": f"场景 {sid}",
        "kind": "web",
        CONTRACT_VERSION_FIELD: contract_version,
        "steps": [{"action": "click", "target": f"#{sid}-btn"}],
        "assertions": [{"type": "element_visible", "selector": f"#{sid}-out"}],
    }


def _valid_cli_scenario(sid: str = "cli-ok", *, contract_version: int = 1) -> dict:
    return {
        "id": sid,
        "description": f"cli 场景 {sid}",
        "kind": "cli",
        CONTRACT_VERSION_FIELD: contract_version,
        "steps": [{"action": "run", "command": "echo hi"}],
        "assertions": [{"type": "exit_code", "expected": 0}],
    }


def _valid_api_scenario(sid: str = "api-ok", *, contract_version: int = 1) -> dict:
    return {
        "id": sid,
        "description": f"api 场景 {sid}",
        "kind": "api",
        CONTRACT_VERSION_FIELD: contract_version,
        "steps": [{"action": "http_request", "method": "GET", "url": "http://127.0.0.1:8000/api"}],
        "assertions": [{"type": "status_code", "expected": 200}],
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


def _make_pm(project_root: Path):
    """构造满足 VerificationPipeline 依赖的最小 PM mock（同 reservoir 夹具）。"""
    sm = StateMachine(project_root / ".fenix" / "STATE.md", _FakeLogger())
    pm = mock.MagicMock()
    pm.project_root = project_root
    pm.logger = _FakeLogger()
    pm.state_machine = sm
    return pm, sm


def _write_frozen(tmp_path: Path, spec: str, raw: list) -> Path:
    vp = tmp_path / ".fenix" / "verify-progress" / spec
    vp.mkdir(parents=True)
    path = vp / "test_scenarios.json"
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# ═══════════════════════════════════════════════════════════════════════
# 4.1 migrate_frozen_contract 纯函数级
# ═══════════════════════════════════════════════════════════════════════

class TestMigrateFrozenContractPure:
    """migrate_frozen_contract 纯函数（无 IO，无需 verify server）。"""

    def test_web_missing_navigate_gets_value_navigate_first(self):
        """(a) v1 web 缺 navigate + base_url → navigate 以 value 承载 URL、
        插 steps 首位、contract_version=2，迁移结果过 validate_scenario_dicts。"""
        raw = [_valid_web_scenario("web-a")]
        result = migrate_frozen_contract(raw, base_url="http://127.0.0.1:8000")
        assert result["aborted"] == ""
        assert result["pending_replan"] == []
        migrated = result["migrated"]
        assert len(migrated) == 1
        entry = migrated[0]
        assert entry[CONTRACT_VERSION_FIELD] == 2
        nav = entry["steps"][0]
        assert nav["action"] == "navigate"
        assert nav["value"] == "http://127.0.0.1:8000"  # 字段为 value（全链路读取口径）
        assert nav["description"] == "契约 v2 自动补齐（navigate 绝对 URL）"
        assert entry["steps"][1]["action"] == "click"  # 原步骤保持、顺序不变
        assert validate_scenario_dicts(migrated) == []

    def test_run_step_url_not_mined_uses_base_url(self):
        """(b) web 场景 steps 含 run+URL 但无 navigate → 不挖文本，改用 base_url。"""
        raw = [{
            "id": "web-run",
            "description": "带 run 的 web 场景",
            "kind": "web",
            CONTRACT_VERSION_FIELD: 1,
            "steps": [{"action": "run", "command": "echo https://evil.example.com/x"}],
            "assertions": [],
        }]
        result = migrate_frozen_contract(raw, base_url="http://127.0.0.1:8000")
        entry = result["migrated"][0]
        # navigate 目标取 base_url，MUST NOT 挖 steps 文本里的 URL
        assert entry["steps"][0]["action"] == "navigate"
        assert entry["steps"][0]["value"] == "http://127.0.0.1:8000"
        assert entry["steps"][1]["action"] == "run"
        assert entry["steps"][1]["command"] == "echo https://evil.example.com/x"

    def test_step_url_field_has_priority_over_base_url(self):
        """场景内 step 的 url 字段（api 形态残留）优先于 base_url（D2.2 顺序 a）。"""
        raw = [{
            "id": "web-urlfield",
            "description": "手写场景带 url 字段",
            "kind": "web",
            CONTRACT_VERSION_FIELD: 1,
            "steps": [
                {"action": "http_request", "method": "GET", "url": "https://first.example.com/a"},
                {"action": "click", "target": "#btn"},
            ],
            "assertions": [],
        }]
        result = migrate_frozen_contract(raw, base_url="http://127.0.0.1:8000")
        entry = result["migrated"][0]
        assert entry["steps"][0]["action"] == "navigate"
        assert entry["steps"][0]["value"] == "https://first.example.com/a"

    def test_non_http_step_url_not_taken(self):
        """step url 字段非 http(s)（如相对路径）不作为候选，回退 base_url。"""
        raw = [{
            "id": "web-relurl",
            "description": "url 字段为相对路径",
            "kind": "web",
            CONTRACT_VERSION_FIELD: 1,
            "steps": [{"action": "click", "target": "#a", "url": "/relative"}],
            "assertions": [],
        }]
        result = migrate_frozen_contract(raw, base_url="http://127.0.0.1:8000")
        entry = result["migrated"][0]
        assert entry["steps"][0]["action"] == "navigate"
        assert entry["steps"][0]["value"] == "http://127.0.0.1:8000"

    def test_no_url_goes_pending_replan_others_migrate(self):
        """(c) base_url 空且场景无 url 字段 → 该场景进 pending_replan，其余照常。"""
        raw = [
            _valid_web_scenario("web-no-url"),
            _valid_cli_scenario("cli-ok"),
        ]
        result = migrate_frozen_contract(raw, base_url="")
        assert result["aborted"] == ""
        assert result["pending_replan"] == ["web-no-url"]
        assert [m["id"] for m in result["migrated"]] == ["cli-ok"]
        assert result["migrated"][0][CONTRACT_VERSION_FIELD] == 2

    def test_all_pending_replan_stale(self):
        """(d) 全量 pending_replan → aborted='all_scenarios_stale'、migrated 为空。"""
        raw = [_valid_web_scenario("w1"), _valid_web_scenario("w2")]
        result = migrate_frozen_contract(raw, base_url="")
        assert result["aborted"] == "all_scenarios_stale"
        assert result["migrated"] == []
        assert set(result["pending_replan"]) == {"w1", "w2"}

    def test_empty_input_stale(self):
        """空集合 → 同「全量过时」语义：aborted='all_scenarios_stale'。"""
        result = migrate_frozen_contract([], base_url="")
        assert result["aborted"] == "all_scenarios_stale"
        assert result["migrated"] == []

    def test_existing_navigate_and_cli_api_stamp_only(self):
        """(e) 已有 navigate 的 web / cli / api 场景 → 只盖戳、步骤零变化。"""
        web_nav = {
            "id": "web-nav",
            "description": "已有 navigate",
            "kind": "web",
            CONTRACT_VERSION_FIELD: 1,
            "steps": [{"action": "navigate", "value": "http://existing.example.com/"}],
            "assertions": [],
        }
        raw = [web_nav, _valid_cli_scenario("cli-ok"), _valid_api_scenario("api-ok")]
        result = migrate_frozen_contract(raw, base_url="http://127.0.0.1:8000")
        assert result["aborted"] == ""
        assert result["pending_replan"] == []
        by_id = {m["id"]: m for m in result["migrated"]}
        # navigate 既有字段零变化（不重复插入、不改 URL）
        assert by_id["web-nav"]["steps"] == [{"action": "navigate", "value": "http://existing.example.com/"}]
        assert by_id["cli-ok"]["steps"] == [{"action": "run", "command": "echo hi"}]
        assert by_id["api-ok"]["steps"][0]["action"] == "http_request"
        for m in result["migrated"]:
            assert m[CONTRACT_VERSION_FIELD] == 2

    def test_idempotent_current_version_zero_op(self):
        """(f) 幂等：contract_version=2 的集合 → 零操作（返回原集合、无迁移标志）。"""
        raw = [{
            "id": "web-v2",
            "description": "已是 v2",
            "kind": "web",
            CONTRACT_VERSION_FIELD: 2,
            "steps": [{"action": "navigate", "value": "http://x.example.com/"}],
            "assertions": [],
        }]
        result = migrate_frozen_contract(raw, base_url="http://127.0.0.1:8000")
        assert result["aborted"] == ""
        assert result["pending_replan"] == []
        assert result["migrated"] is raw  # 原集合直接返回，零操作
        assert result["migrated"][0]["steps"] == [{"action": "navigate", "value": "http://x.example.com/"}]

    def test_frozen_contract_version_missing_or_nonint_is_1(self):
        """缺失/非整型 contract_version 视为 1；min 口径取最小值。"""
        assert frozen_contract_version([]) == 1
        assert frozen_contract_version([{"id": "a", "kind": "cli"}]) == 1
        assert frozen_contract_version([
            {"id": "a", "kind": "cli", CONTRACT_VERSION_FIELD: 2},
            {"id": "b", "kind": "cli", CONTRACT_VERSION_FIELD: "2"},  # 非整型 → 1
        ]) == 1
        assert frozen_contract_version([
            {"id": "a", "kind": "cli", CONTRACT_VERSION_FIELD: 2},
            {"id": "b", "kind": "cli", CONTRACT_VERSION_FIELD: 1},
        ]) == 1

    def test_jump_version_two_segments(self):
        """(g) 跳版本：current_version=3（登记表含 v2/v3 桩）→ v1 走两段迁移。"""
        raw = [_valid_web_scenario("web-jump")]

        def _v3_stub(scenarios, base_url=""):
            return [
                {**s, CONTRACT_VERSION_FIELD: 3} if isinstance(s, dict) else s
                for s in scenarios
            ], []

        with mock.patch.object(
            scenarios_mod, "_CONTRACT_MIGRATIONS",
            {2: _migrate_contract_to_v2, 3: _v3_stub},
        ):
            result = migrate_frozen_contract(raw, current_version=3, base_url="http://127.0.0.1:8000")
        assert result["aborted"] == ""
        entry = result["migrated"][0]
        # 第一段（v2）合成 navigate，第二段（v3）盖 3 戳——前段产物喂后段
        assert entry[CONTRACT_VERSION_FIELD] == 3
        assert entry["steps"][0]["action"] == "navigate"
        assert entry["steps"][0]["value"] == "http://127.0.0.1:8000"

    def test_unregistered_version_segment_fail_closed(self):
        """(g) 未登记版本段 → aborted='no_migration_path'（fail-closed）。"""
        raw = [_valid_web_scenario("web-nopath")]
        with mock.patch.object(
            scenarios_mod, "_CONTRACT_MIGRATIONS",
            {2: _migrate_contract_to_v2},
        ):
            result = migrate_frozen_contract(raw, current_version=3, base_url="http://127.0.0.1:8000")
        assert result["aborted"] == "no_migration_path"
        assert result["migrated"] == []

    def test_migrate_is_pure_no_input_mutation(self):
        """迁移不修改输入列表/dict（纯函数、读无副作用）。"""
        raw = [_valid_web_scenario("web-pure")]
        snapshot = json.loads(json.dumps(raw))
        migrate_frozen_contract(raw, base_url="http://127.0.0.1:8000")
        assert raw == snapshot


# ═══════════════════════════════════════════════════════════════════════
# 4.2 pipeline._load_frozen_or_escalate 调用点级
# ═══════════════════════════════════════════════════════════════════════

class TestLoadFrozenOrEscalate:
    """mock 冻结文件 + patch _current_instance_base_url / 升级通道。"""

    def _pipe(self, tmp_path: Path, spec: str):
        pm, sm = _make_pm(tmp_path)
        sm.add_spec(spec, {"priority": 5})
        pipe = VerificationPipeline(pm)
        pipe._escalate_env_blocked = mock.MagicMock()
        return pipe, pm, sm

    def test_v1_frozen_migrates_writes_back_and_backs_up(self, tmp_path: Path):
        """(h) v1 冻结文件 → 迁移 + 写回后 contract_version=2 持久化、
        .contract-v1.bak 存在。"""
        raw = [_valid_web_scenario("web-a")]
        _write_frozen(tmp_path, "spec-h", raw)
        pipe, pm, sm = self._pipe(tmp_path, "spec-h")
        vp = tmp_path / ".fenix" / "verify-progress" / "spec-h"
        with mock.patch.object(
            pipe, "_current_instance_base_url", return_value="http://127.0.0.1:8000"
        ):
            frozen, aborted = pipe._load_frozen_or_escalate("spec-h", vp)
        assert aborted is False
        assert len(frozen) == 1  # 迁移后过 load_scenarios 验收
        persisted = json.loads((vp / "test_scenarios.json").read_text(encoding="utf-8"))
        assert persisted[0][CONTRACT_VERSION_FIELD] == CURRENT_CONTRACT_VERSION
        assert persisted[0]["schema_version"] == SCHEMA_VERSION
        assert persisted[0]["steps"][0]["action"] == "navigate"
        assert persisted[0]["steps"][0]["value"] == "http://127.0.0.1:8000"
        # 备份存在且为迁移前原样
        bak = vp / "test_scenarios.json.contract-v1.bak"
        assert bak.is_file()
        bak_raw = json.loads(bak.read_text(encoding="utf-8"))
        assert bak_raw[0][CONTRACT_VERSION_FIELD] == 1
        assert "navigate" not in [s.get("action") for s in bak_raw[0]["steps"]]
        # 未升级人工
        pipe._escalate_env_blocked.assert_not_called()

    def test_all_stale_deletes_file_and_replans(self, tmp_path: Path):
        """(i) 全过时 → 返回 (None, False)、冻结文件被删除、未调用
        _escalate_env_blocked（本轮回落既有出题分支）。"""
        raw = [_valid_web_scenario("w1"), _valid_web_scenario("w2")]
        _write_frozen(tmp_path, "spec-i", raw)
        pipe, pm, sm = self._pipe(tmp_path, "spec-i")
        vp = tmp_path / ".fenix" / "verify-progress" / "spec-i"
        with mock.patch.object(pipe, "_current_instance_base_url", return_value=""):
            frozen, aborted = pipe._load_frozen_or_escalate("spec-i", vp)
        assert frozen is None
        assert aborted is False  # 未升级 → 主循环以 frozen=None 走出题分支
        assert not (vp / "test_scenarios.json").exists()
        pipe._escalate_env_blocked.assert_not_called()

    def test_empty_frozen_file_deleted_and_replans(self, tmp_path: Path):
        """空冻结集（[]）→ 同全过时：删除文件、回落出题、不升级人工。"""
        _write_frozen(tmp_path, "spec-empty", [])
        pipe, pm, sm = self._pipe(tmp_path, "spec-empty")
        vp = tmp_path / ".fenix" / "verify-progress" / "spec-empty"
        with mock.patch.object(pipe, "_current_instance_base_url", return_value=""):
            frozen, aborted = pipe._load_frozen_or_escalate("spec-empty", vp)
        assert frozen is None
        assert aborted is False
        assert not (vp / "test_scenarios.json").exists()
        pipe._escalate_env_blocked.assert_not_called()

    def test_current_version_zero_op_no_backup_no_rewrite(self, tmp_path: Path):
        """幂等：contract_version=2 的冻结集 → 零操作（不调 base_url、不写回、
        不备份）。"""
        raw = [{
            "id": "web-v2",
            "description": "已是 v2",
            "kind": "web",
            CONTRACT_VERSION_FIELD: 2,
            "steps": [{"action": "navigate", "value": "http://x.example.com/"}],
            "assertions": [],
        }]
        path = _write_frozen(tmp_path, "spec-zero", raw)
        before = path.read_text(encoding="utf-8")
        pipe, pm, sm = self._pipe(tmp_path, "spec-zero")
        vp = tmp_path / ".fenix" / "verify-progress" / "spec-zero"
        with mock.patch.object(pipe, "_current_instance_base_url") as base_mock:
            frozen, aborted = pipe._load_frozen_or_escalate("spec-zero", vp)
        assert aborted is False
        assert len(frozen) == 1
        base_mock.assert_not_called()  # 无需 base_url
        assert path.read_text(encoding="utf-8") == before  # 不写回
        assert not (vp / "test_scenarios.json.contract-v1.bak").exists()  # 不备份
        pipe._escalate_env_blocked.assert_not_called()

    def test_migration_then_acceptance_failure_escalates_with_option3(self, tmp_path: Path):
        """迁移后验收仍失败（未知断言类型）→ corrupt → env_blocked，处置选项
        含第③条回退指引（删除/恢复 .contract-v1.bak）。"""
        raw = [{
            "id": "web-badassert",
            "description": "迁移后仍失败的场景",
            "kind": "web",
            CONTRACT_VERSION_FIELD: 1,
            "steps": [{"action": "click", "target": "#btn"}],
            "assertions": [{"type": "no_such_assertion", "selector": "#x"}],
        }]
        _write_frozen(tmp_path, "spec-opt3", raw)
        pipe, pm, sm = self._pipe(tmp_path, "spec-opt3")
        vp = tmp_path / ".fenix" / "verify-progress" / "spec-opt3"
        with mock.patch.object(
            pipe, "_current_instance_base_url", return_value="http://127.0.0.1:8000"
        ):
            frozen, aborted = pipe._load_frozen_or_escalate("spec-opt3", vp)
        assert frozen is None
        assert aborted is True
        pipe._escalate_env_blocked.assert_called_once()
        call_args = pipe._escalate_env_blocked.call_args
        violations = call_args.args[1]
        opts = violations[0]
        assert "③" in opts and "contract-v1.bak" in opts
        # 迁移仍发生了（写回 + 备份），供人工凭差异清单处置
        persisted = json.loads((vp / "test_scenarios.json").read_text(encoding="utf-8"))
        assert persisted[0][CONTRACT_VERSION_FIELD] == CURRENT_CONTRACT_VERSION
        assert (vp / "test_scenarios.json.contract-v1.bak").is_file()

    def test_current_version_acceptance_failure_no_option3(self, tmp_path: Path):
        """未被迁移（contract_version >= 2）且验收失败 → 完全维持现状
        （不备份、不写回，告警文案不含第③条）。"""
        raw = [{
            "id": "web-badassert-v2",
            "description": "已是 v2 但损坏",
            "kind": "web",
            CONTRACT_VERSION_FIELD: 2,
            "steps": [{"action": "navigate", "value": "http://x.example.com/"}],
            "assertions": [{"type": "no_such_assertion", "selector": "#x"}],
        }]
        path = _write_frozen(tmp_path, "spec-nov3", raw)
        before = path.read_text(encoding="utf-8")
        pipe, pm, sm = self._pipe(tmp_path, "spec-nov3")
        vp = tmp_path / ".fenix" / "verify-progress" / "spec-nov3"
        with mock.patch.object(pipe, "_current_instance_base_url") as base_mock:
            frozen, aborted = pipe._load_frozen_or_escalate("spec-nov3", vp)
        assert frozen is None
        assert aborted is True
        base_mock.assert_not_called()
        pipe._escalate_env_blocked.assert_called_once()
        opts = pipe._escalate_env_blocked.call_args.args[1][0]
        assert "③" not in opts
        assert "contract-v1.bak" not in opts
        assert path.read_text(encoding="utf-8") == before
        assert not (vp / "test_scenarios.json.contract-v1.bak").exists()

    def test_corrupt_json_escalates_no_migration(self, tmp_path: Path):
        """JSON 语法错（不属契约漂移）→ 维持 corrupt → env_blocked，不备份不删除。"""
        vp = tmp_path / ".fenix" / "verify-progress" / "spec-json"
        vp.mkdir(parents=True)
        path = vp / "test_scenarios.json"
        path.write_text("{not-json", encoding="utf-8")
        pipe, pm, sm = self._pipe(tmp_path, "spec-json")
        with mock.patch.object(pipe, "_current_instance_base_url") as base_mock:
            frozen, aborted = pipe._load_frozen_or_escalate("spec-json", vp)
        assert frozen is None
        assert aborted is True
        base_mock.assert_not_called()
        pipe._escalate_env_blocked.assert_called_once()
        assert path.is_file()  # 不删除
        assert not (vp / "test_scenarios.json.contract-v1.bak").exists()  # 不备份

    def test_no_frozen_file_returns_none_false(self, tmp_path: Path):
        """无冻结文件 → (None, False) 走既有出题通道（行为不变）。"""
        pipe, pm, sm = self._pipe(tmp_path, "spec-nofile")
        vp = tmp_path / ".fenix" / "verify-progress" / "spec-nofile"
        vp.mkdir(parents=True)
        frozen, aborted = pipe._load_frozen_or_escalate("spec-nofile", vp)
        assert frozen is None
        assert aborted is False
        pipe._escalate_env_blocked.assert_not_called()


class TestWriteEndContractStamp:
    """(j) 写端回归：prepare_scenarios_for_write 恒定盖 contract_version 戳。"""

    def test_prepare_scenarios_for_write_stamps_contract_version(self):
        prep = prepare_scenarios_for_write([_valid_web_scenario("w")])
        assert prep[0][CONTRACT_VERSION_FIELD] == CURRENT_CONTRACT_VERSION
        assert prep[0]["schema_version"] == SCHEMA_VERSION

    def test_prepare_preserves_existing_navigate(self):
        """写端盖戳不改步骤内容（navigate 既有字段零变化）。"""
        sc = {
            "id": "w-nav",
            "description": "d",
            "kind": "web",
            "steps": [{"action": "navigate", "value": "http://x.example.com/"}],
            "assertions": [],
        }
        prep = prepare_scenarios_for_write([sc])
        assert prep[0]["steps"] == [{"action": "navigate", "value": "http://x.example.com/"}]


if __name__ == "__main__":
    import unittest

    unittest.main()
