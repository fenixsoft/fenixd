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
    read_verify_fix_section,
)


def _tmp_project() -> Path:
    return Path(tempfile.mkdtemp())


def _seed_persisted(proot: Path, spec: str, ids):
    """写入首轮持久化集（round=1）。"""
    entries = [ScenarioEntry(id=sid, description=f"desc {sid}", added_in_round=1)
               for sid in ids]
    save_scenario_set(proot, ScenarioSet(spec, 1, entries))


def _write_tasks_fix_section(proot: Path, spec: str, body: str):
    p = proot / "openspec" / "changes" / spec / "tasks.md"
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
