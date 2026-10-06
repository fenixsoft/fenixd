"""verify_scenarios 单元测试（add-verify-scenario-freeze）。

覆盖 spec 需求 verify-scenario-freeze 的三类场景：
  - 场景集持久化（首轮写入、已有文件不覆盖）
  - 修复轮复用持久化集（不扩容 / 新增范围合法追加 / 无理由删减被补齐）
  - 删减须有理由并留痕（有理由移除记录 / 无理由缺场景被拦截）
  - 验证报告「本轮场景集变更」小节渲染
并以 v2-config-page 真实 11→17 场景数据作夹具回归（3.2）。
"""

import json
import tempfile
from pathlib import Path

from core.verify_scenarios import (
    ScenarioSet,
    ScenarioEntry,
    diff_planner_output,
    load_scenario_set,
    save_scenario_set,
    render_change_section,
    render_first_write_section,
    is_repair_round,
    declares_new_delivery,
)


def _tmp_project() -> Path:
    return Path(tempfile.mkdtemp())


def _seed_persisted(proot: Path, spec: str, ids):
    """写入首轮持久化集（round=1）。"""
    entries = [ScenarioEntry(id=sid, description=f"desc {sid}", added_in_round=1)
               for sid in ids]
    save_scenario_set(proot, ScenarioSet(spec, 1, entries))


def _write_tasks_fix_section(proot: Path, spec: str, body: str):
    p = proot / "spec" / "changes" / spec / "tasks.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# tasks\n\n" + body, encoding="utf-8")


# ── 1. 场景集持久化 ────────────────────────────────────────────────

class TestScenarioPersistence:
    def test_first_write_records_ids_and_round(self):
        proot = _tmp_project()
        ss = ScenarioSet("demo", 1, [
            ScenarioEntry("s1", "场景一", 1),
            ScenarioEntry("s2", "场景二", 1),
        ])
        save_scenario_set(proot, ss)
        got = load_scenario_set(proot, "demo")
        assert got is not None
        assert got.round == 1
        assert sorted(got.ids) == ["s1", "s2"]
        assert all(e.added_in_round == 1 for e in got.scenarios)

    def test_atomic_write_no_half_file(self):
        # 原子写：写完文件是合法 JSON（临时文件 rename 覆盖）
        proot = _tmp_project()
        ss = ScenarioSet("demo", 1, [ScenarioEntry("s1")])
        path = save_scenario_set(proot, ss)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["spec"] == "demo"
        assert data["scenarios"][0]["id"] == "s1"

    def test_existing_file_not_overwritten_blindly(self):
        # 已有文件时，外部再 save 会覆盖——但语义上「不无条件覆盖」由 diff 流程
        # 保证：直接调用 diff_planner_output（已有持久化集）走 diff 而非覆盖。
        proot = _tmp_project()
        _seed_persisted(proot, "demo", ["s1", "s2", "s3"])
        # planner 仅产出 s1,s2（修复轮无新增交付）→ s3 无理由缺失，被补齐
        # （ok=False，final 仍含全集，验证不中断）
        diff = diff_planner_output(proot, "demo", {"_verify_fail_rounds": 1},
                                   [{"id": "s1"}, {"id": "s2"}], 2)
        assert diff.ok is False
        assert sorted(diff.scenario_set.ids) == ["s1", "s2", "s3"]
        # 显式写回后读盘确认仍保留全集（非盲覆盖只取 planner 子集）
        save_scenario_set(proot, diff.scenario_set)
        assert sorted(load_scenario_set(proot, "demo").ids) == ["s1", "s2", "s3"]


# ── 2. 修复轮复用持久化集 ──────────────────────────────────────────

class TestRepairRoundReuse:
    def test_repair_round_not_expanded(self):
        # 修复轮不扩容：planner 超发 17 个中的额外 6 个被拦截，收敛回 11
        proot = _tmp_project()
        base = [f"sc-{i}" for i in range(1, 12)]  # 11 个
        _seed_persisted(proot, "demo", base)
        extra = [f"sc-{i}" for i in range(12, 18)]  # 17 个
        planner = [{"id": s} for s in base + extra]
        diff = diff_planner_output(proot, "demo", {"_verify_fail_rounds": 1},
                                   planner, 2)
        assert diff.extended is False
        assert sorted(diff.scenario_set.ids) == sorted(base)
        assert len(diff.added) == 0

    def test_new_scope_legal_append_written_back(self):
        # 修复段声明新增交付 → 允许为新增范围追加，合并写回并记轮次
        proot = _tmp_project()
        base = [f"sc-{i}" for i in range(1, 12)]
        _seed_persisted(proot, "demo", base)
        _write_tasks_fix_section(
            proot, "demo",
            "## 验证修复（第1轮失败）\n\n- [ ] 新增交付：导入导出功能\n",
        )
        planner = [{"id": s} for s in base] + [{"id": "sc-import-1"}]
        diff = diff_planner_output(proot, "demo", {"_verify_fail_rounds": 1},
                                   planner, 2)
        assert diff.extended is True
        assert "sc-import-1" in diff.scenario_set.ids
        assert len(diff.added) == 1
        assert diff.added[0].added_in_round == 2
        # 写回后读盘确认
        save_scenario_set(proot, diff.scenario_set)
        got = load_scenario_set(proot, "demo")
        assert "sc-import-1" in got.ids

    def test_unreasoned_missing_backfilled(self):
        # 无理由缺场景被补齐（ok=False，final 仍含全集）
        proot = _tmp_project()
        base = ["s1", "s2", "s3"]
        _seed_persisted(proot, "demo", base)
        diff = diff_planner_output(proot, "demo", {"_verify_fail_rounds": 1},
                                   [{"id": "s1"}, {"id": "s2"}], 2)
        assert diff.ok is False
        assert [e.id for e in diff.unreasoned_missing] == ["s3"]
        assert sorted(diff.scenario_set.ids) == ["s1", "s2", "s3"]


# ── 3. 删减须有理由并留痕 ──────────────────────────────────────────

class TestReasonedRemoval:
    def test_reasoned_removal_recorded(self):
        proot = _tmp_project()
        _seed_persisted(proot, "demo", ["s1", "s2"])
        diff = diff_planner_output(
            proot, "demo", {"_verify_fail_rounds": 1},
            [{"id": "s2"}, {"id": "s1", "remove_reason": "功能已移除"}], 2)
        assert diff.ok is True
        assert [(e.id, r) for e, r in diff.removed] == [("s1", "功能已移除")]
        assert "s1" not in diff.scenario_set.ids
        # 写回确认 scenarios.json 同步移除
        save_scenario_set(proot, diff.scenario_set)
        got = load_scenario_set(proot, "demo")
        assert "s1" not in got.ids

    def test_reasoned_removal_change_section(self):
        proot = _tmp_project()
        _seed_persisted(proot, "demo", ["s1", "s2"])
        diff = diff_planner_output(
            proot, "demo", {"_verify_fail_rounds": 1},
            [{"id": "s2"}, {"id": "s1", "remove_reason": "功能已移除"}], 2)
        section = render_change_section(diff)
        assert "## 本轮场景集变更" in section
        assert "移除场景 s1（理由：功能已移除）" in section


# ── 4. 报告变更小节渲染 ────────────────────────────────────────────

class TestReportChangeSection:
    def test_first_write_section(self):
        proot = _tmp_project()
        ss = ScenarioSet("demo", 1, [ScenarioEntry("s1"), ScenarioEntry("s2")])
        section = render_first_write_section(ss)
        assert "## 本轮场景集变更" in section
        assert "首轮写入 2 个场景" in section

    def test_change_section_no_change(self):
        proot = _tmp_project()
        _seed_persisted(proot, "demo", ["s1", "s2"])
        diff = diff_planner_output(proot, "demo", {"_verify_fail_rounds": 1},
                                   [{"id": "s1"}, {"id": "s2"}], 2)
        section = render_change_section(diff)
        assert "场景集与持久化集一致，无变更" in section

    def test_change_section_overissue_intercept(self):
        proot = _tmp_project()
        _seed_persisted(proot, "demo", ["s1"])
        diff = diff_planner_output(proot, "demo", {"_verify_fail_rounds": 1},
                                   [{"id": "s1"}, {"id": "s2"}, {"id": "s3"}], 2)
        section = render_change_section(diff)
        assert "拦截 planner 超发" in section


# ── 修复轮判定（D1）──────────────────────────────────────────────

class TestRepairRoundDetection:
    def test_fail_rounds_signal(self):
        proot = _tmp_project()
        assert is_repair_round(proot, "demo", {"_verify_fail_rounds": 1}) is True
        assert is_repair_round(proot, "demo", {"_verify_fail_rounds": 0}) is False
        assert is_repair_round(proot, "demo", None) is False

    def test_fix_section_signal(self):
        proot = _tmp_project()
        assert is_repair_round(proot, "demo", {}) is False
        _write_tasks_fix_section(proot, "demo", "## 验证修复（第2轮失败）\n")
        assert is_repair_round(proot, "demo", {}) is True

    def test_declares_new_delivery(self):
        assert declares_new_delivery(None) is False
        assert declares_new_delivery("## 验证修复\n- [ ] 修复 bug") is False
        assert declares_new_delivery(
            "## 验证修复\n- [ ] 新增交付：导入导出") is True
        assert declares_new_delivery(
            "## 验证修复\n- [ ] 追加新功能支持") is True

    def test_declares_new_delivery_repair_phrase_variants(self):
        # 修复语境常见变体：动词与「对…的修复」之间隔着「了」「针对」等
        # 衔接字，不得误判为新增交付声明（否则修复轮扩容闸门被无声放开）
        assert declares_new_delivery(
            "## 验证修复\n- [ ] 追加了针对场景 s1 的修复") is False
        assert declares_new_delivery(
            "## 验证修复\n- [ ] 增加了对于旧版导入功能的修复") is False
        # 排除只应命中修复语境，真新增交付仍须计为扩容声明
        assert declares_new_delivery(
            "## 验证修复\n- [ ] 新增交付：历史错误的修复向导") is True

    def test_declares_new_delivery_negation(self):
        # 否定句式（code-review cec71a4419ae）：动词前同条款紧邻否定前缀
        # ＝未声明新增交付，不得误开修复轮扩容闸门
        assert declares_new_delivery(
            "## 验证修复\n- [ ] 未新增场景") is False
        assert declares_new_delivery(
            "## 验证修复\n- [ ] 无新增交付范围") is False
        assert declares_new_delivery(
            "## 验证修复\n- [ ] 不增加功能") is False
        # 否定排除限定同条款：前半句否定不得吞掉跨句读的真实声明
        assert declares_new_delivery(
            "## 验证修复\n- [ ] 上一轮无新增，本次新增 2 个场景") is True


# ── 3.2 v2-config-page 真实 11→17 夹具回归 ────────────────────────

class TestV2ConfigPageFixture:
    """v2-config-page 实证：首轮 11 场景，修复轮 planner 膨胀到 17，
    修复段未声明新增交付 → 收敛回 11（超发的 6 个被拦截）。"""

    BASE_11 = [f"cfg-{i:02d}" for i in range(1, 12)]
    ROUND2_17 = [f"cfg-{i:02d}" for i in range(1, 18)]

    def test_first_round_writes_11(self):
        proot = _tmp_project()
        planner = [{"id": s, "description": f"配置场景 {s}"}
                   for s in self.BASE_11]
        diff = diff_planner_output(proot, "v2-config-page", None, planner, 1)
        assert diff.scenario_set.round == 1
        assert len(diff.scenario_set.scenarios) == 11
        save_scenario_set(proot, diff.scenario_set)
        got = load_scenario_set(proot, "v2-config-page")
        assert len(got.scenarios) == 11

    def test_round2_no_new_scope_converges_to_11(self):
        proot = _tmp_project()
        # 首轮写入 11
        _seed_persisted(proot, "v2-config-page", self.BASE_11)
        # 修复轮：planner 膨胀到 17，但修复段未声明新增交付
        planner = [{"id": s} for s in self.ROUND2_17]
        diff = diff_planner_output(
            proot, "v2-config-page", {"_verify_fail_rounds": 1}, planner, 2)
        # 超发被拦截，收敛回 11
        assert sorted(diff.scenario_set.ids) == sorted(self.BASE_11)
        assert len(diff.added) == 0
        assert diff.extended is False

    def test_round2_with_new_scope_keeps_extra(self):
        proot = _tmp_project()
        _seed_persisted(proot, "v2-config-page", self.BASE_11)
        _write_tasks_fix_section(
            proot, "v2-config-page",
            "## 验证修复（第1轮失败）\n\n- [ ] 新增交付：主题定制\n",
        )
        planner = [{"id": s} for s in self.ROUND2_17]
        diff = diff_planner_output(
            proot, "v2-config-page", {"_verify_fail_rounds": 1}, planner, 2)
        # 声明新增交付：17 个全部保留（11 既有 + 6 新增范围）
        assert sorted(diff.scenario_set.ids) == sorted(self.ROUND2_17)
        assert len(diff.added) == 6


# ── 4. multi-kind-report-compat：冻结条目 kind 携带 ───────────────

class TestScenarioEntryKind:
    def test_kind_default_web(self):
        e = ScenarioEntry("s1")
        assert e.kind == "web"
        e2 = ScenarioEntry.from_dict({"id": "s1"})
        assert e2.kind == "web"

    def test_kind_serialized_when_non_web(self):
        e = ScenarioEntry("s1", kind="cli")
        d = e.to_dict()
        assert d.get("kind") == "cli"

    def test_roundtrip_kind(self):
        proot = _tmp_project()
        ss = ScenarioSet("demo", 1, [
            ScenarioEntry("web-s", kind="web"),
            ScenarioEntry("cli-s", kind="cli"),
            ScenarioEntry("api-s", kind="api"),
        ])
        save_scenario_set(proot, ss)
        got = load_scenario_set(proot, "demo")
        by_id = {e.id: e.kind for e in got.scenarios}
        assert by_id == {"web-s": "web", "cli-s": "cli", "api-s": "api"}

    def test_legacy_freeze_zero_migration(self):
        """存量冻结文件无 kind → 读侧缺省 web，diff 与写回兼容。"""
        proot = _tmp_project()
        ss = ScenarioSet("demo", 1, [ScenarioEntry("legacy-s1")])
        save_scenario_set(proot, ss)
        # 读回缺省 web
        got = load_scenario_set(proot, "demo")
        assert got.scenarios[0].kind == "web"
        # planner 产出无 kind → 合并后条目仍 web
        diff = diff_planner_output(proot, "demo", None,
                                   [{"id": "legacy-s1"}], 2)
        assert {e.id: e.kind for e in diff.scenario_set.scenarios} == {
            "legacy-s1": "web"}

    def test_first_round_carries_kind(self):
        """首轮冻结：planner 产出的 cli/api 场景 kind 写入 scenarios.json。"""
        proot = _tmp_project()
        planner = [
            {"id": "w1"},
            {"id": "c1", "kind": "cli"},
            {"id": "a1", "kind": "api"},
        ]
        diff = diff_planner_output(proot, "demo", None, planner, 1)
        save_scenario_set(proot, diff.scenario_set)
        got = load_scenario_set(proot, "demo")
        by_id = {e.id: e.kind for e in got.scenarios}
        assert by_id == {"w1": "web", "c1": "cli", "a1": "api"}

    def test_missing_backfill_carries_kind(self):
        """无理由缺场景补齐：持久化集的 cli 条目被补齐后仍为 cli。"""
        proot = _tmp_project()
        _seed_persisted(proot, "demo", ["s1"])
        # 手动改写持久化集为 cli（模拟混合集）
        ss = load_scenario_set(proot, "demo")
        ss.scenarios[0].kind = "cli"
        save_scenario_set(proot, ss)
        # 非修复轮（state=None）允许新增条目
        diff = diff_planner_output(proot, "demo", None,
                                   [{"id": "other"}], 2)
        assert diff.ok is False  # s1 无理由缺失 → 补齐
        by_id = {e.id: e.kind for e in diff.scenario_set.scenarios}
        assert by_id == {"s1": "cli", "other": "web"}


# ── 顶层门与拯救助手（evo-scenario-product-toplevel-contract 3.1）───────────

import pytest

from core.verify_engine.scenarios import (
    load_scenarios,
    salvage_scenarios_file,
    unwrap_scenarios_dict,
)


def _engine_valid_web(sid: str) -> dict:
    """引擎读端（load_scenarios 校验链）认可的最小合法 web 场景。"""
    return {
        "id": sid, "description": f"场景{sid}", "kind": "web",
        "steps": [{"action": "navigate", "value": "http://127.0.0.1:8000/"},
                  {"action": "click", "target": f"#{sid}"}],
        "assertions": [{"type": "element_visible", "selector": f"#{sid}"}],
    }


def _write_scenarios_file(obj) -> Path:
    d = Path(tempfile.mkdtemp())
    p = d / "test_scenarios.json"
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return p


class TestTopLevelGateAndSalvage:
    """test_scenarios.json 顶层非数组硬门 + dict 包裹拯救助手（3.1）。"""

    def test_non_array_top_level_rejected_by_load_scenarios(self):
        """顶层 {"spec":…,"scenarios":[…]} dict 被 load_scenarios 整份拒收。"""
        p = _write_scenarios_file(
            {"spec": "demo", "scenarios": [_engine_valid_web("s1")]})
        with pytest.raises(ValueError, match="期望JSON数组"):
            load_scenarios(p)

    def test_string_top_level_rejected_by_load_scenarios(self):
        """其余非数组顶层（字符串等）照常拒收，不拯救。"""
        p = _write_scenarios_file("not-a-list")
        with pytest.raises(ValueError, match="期望JSON数组"):
            load_scenarios(p)

    def test_pure_array_input_unaffected(self):
        """纯数组顶层照常加载（load_scenarios 本体语义不变）。"""
        p = _write_scenarios_file(
            [_engine_valid_web("s1"), _engine_valid_web("s2")])
        scenarios = load_scenarios(p)
        assert [s.id for s in scenarios] == ["s1", "s2"]

    def test_unwrap_salvageable_dict_returns_array(self):
        """{"scenarios":[…]} 唯一形态解包返回数组。"""
        entries = [_engine_valid_web("s1"), _engine_valid_web("s2")]
        assert unwrap_scenarios_dict(
            {"spec": "demo", "scenarios": entries}) == entries

    def test_unwrap_rejects_dict_without_scenarios_key(self):
        with pytest.raises(ValueError, match="不可解包"):
            unwrap_scenarios_dict({"spec": "demo", "entries": []})

    def test_unwrap_rejects_non_list_scenarios_value(self):
        with pytest.raises(ValueError, match="不可解包"):
            unwrap_scenarios_dict({"scenarios": {"a": 1}})

    def test_unwrap_rejects_empty_scenarios_array(self):
        with pytest.raises(ValueError, match="不可解包"):
            unwrap_scenarios_dict({"scenarios": []})

    def test_unwrap_rejects_non_dict_top_level(self):
        """非 dict 顶层（数组/标量）无解包面，原样报错。"""
        with pytest.raises(ValueError, match="非 dict 包裹形态"):
            unwrap_scenarios_dict([_engine_valid_web("s1")])
        with pytest.raises(ValueError, match="非 dict 包裹形态"):
            unwrap_scenarios_dict("just-a-string")

    def test_salvage_rewrites_pure_array_and_reports_info(self):
        """解包 → 重验通过 → 原子重写为纯数组落地，留痕 info 齐全。"""
        entries = [_engine_valid_web("s1")]
        p = _write_scenarios_file({"spec": "demo", "scenarios": entries})
        scenarios, info = salvage_scenarios_file(p)
        assert [s.id for s in scenarios] == ["s1"]
        assert info["top_keys"] == ["scenarios", "spec"]
        assert info["entry_count"] == 1
        assert info["rewritten"] is True
        # 落地为纯数组：其余 load_scenarios 读端按既有语义直接可读，
        # 且原始条目字段零丢失（raw 落地而非 to_dict 回环）
        on_disk = json.loads(p.read_text(encoding="utf-8"))
        assert isinstance(on_disk, list)
        assert on_disk[0] == entries[0]
        assert [s.id for s in load_scenarios(p)] == ["s1"]

    def test_salvage_rejects_invalid_unwrapped_entries_without_rewrite(self):
        """解包后条目未过既有校验 → 原样拒收，不落地。"""
        p = _write_scenarios_file(
            {"scenarios": [{"id": "bad", "description": "非法"}]})
        with pytest.raises(ValueError):
            salvage_scenarios_file(p)
        assert isinstance(json.loads(p.read_text(encoding="utf-8")), dict)

    def test_salvage_rejects_non_salvageable_shapes(self):
        """缺 scenarios 键 / scenarios 非数组 / 标量 / 列表套标量均不拯救。"""
        for obj in ({"spec": "demo"}, {"scenarios": {}}, "string", [1, 2]):
            p = _write_scenarios_file(obj)
            with pytest.raises(ValueError):
                salvage_scenarios_file(p)

    def test_salvage_missing_file_raises_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            salvage_scenarios_file(Path(tempfile.mkdtemp()) / "nope.json")
