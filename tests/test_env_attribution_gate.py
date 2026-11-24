"""
env 归因证据门测试（evo-env-attribution-evidence-gate SPEC 3.1）

覆盖四场景：
  1. 量测+对照齐全 → accept 且新字段（measurement_refs/control_samples）随
     条目落盘
  2. 缺量测或缺对照 → requeue 落盘且不落 accept（条目注明缺失项；文本回退
     匹配与「两轮同窗自测不构成对照」反例同测）
  3. 降级条目走回炉重检闭环（回炉清单收录 + 轻量重合成派发 + 补证后重新
     评估采纳），不触发豁免握手 / env-blocked inconclusive 通道
  4. 旧格式 judge_attribution.json 兼容读取（缺新字段按空处理）
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.pm_engine.engine import PMEngine
from core.state_machine import StateMachine
from core.agent_runner.runner import AgentRunResult
from core.verify_engine.judge_files import (
    load_attribution,
    save_attribution,
    attribution_refs,
    judge_env_evidence_gate,
    ATTRIBUTION_MEASUREMENT_REFS_FIELD,
    ATTRIBUTION_CONTROL_SAMPLES_FIELD,
)
from core.pm_engine.verification.verdict_evidence import _run_attribution_gate
from core.verdict_check import check_batch_attribution_dedup_scenario


class _FakeLogger:
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass
    def debug(self, *a, **k): pass


# ── helpers ────────────────────────────────────────────────────────────────

def _dup_scenario(sid: str) -> dict:
    """三个同文场景中的一个（查重组，env 分类、无证据门证据）。"""
    return {
        "scenario_id": sid, "status": "fail", "classification": "env",
        "evidence": {
            "first_failed_step": "步骤1: 初始化失败",
            "failed_assertions": [{"type": "element_visible", "selector": "#el",
                                   "expected": "可见", "actual": "不存在"}],
        },
        "assertion_triage": [{
            "assertion": "应用可访问", "classification": "env",
            "evidence": "网络不可达（截断）",
        }],
    }


def _env_scenario(sid: str, measurement=None, control=None, evidence_text=None) -> dict:
    """env 分类场景夹具（结构化证据字段可选注入）。"""
    sc = {
        "scenario_id": sid, "status": "fail", "classification": "env",
        "evidence": {
            "first_failed_step": evidence_text or f"步骤1: {sid} 应用不可达",
        },
        "assertion_triage": [{
            "assertion": f"断言-{sid}", "classification": "env",
            "evidence": evidence_text or "网络不可达（截断）",
        }],
    }
    if measurement is not None:
        sc["evidence"][ATTRIBUTION_MEASUREMENT_REFS_FIELD] = measurement
    if control is not None:
        sc["evidence"][ATTRIBUTION_CONTROL_SAMPLES_FIELD] = control
    return sc


class _BaseTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))
        (self.tmpdir / ".fenix").mkdir(parents=True, exist_ok=True)
        self.sm = StateMachine(self.tmpdir / ".fenix" / "STATE.md", _FakeLogger())
        self.agent_runner = mock.MagicMock()
        self.engine = PMEngine(self.sm, self.agent_runner, {},
                               self.tmpdir, _FakeLogger())
        self.sm.add_spec("demo", {"priority": 5})
        self.sm.update_spec("demo", {"status": "testing"})
        self.vp = self.tmpdir / ".fenix" / "verify-progress" / "demo"

    def _write_report(self, scenarios):
        self.vp.mkdir(parents=True, exist_ok=True)
        (self.vp / "report.json").write_text(
            json.dumps({"scenarios": scenarios}, ensure_ascii=False),
            encoding="utf-8")

    def _read_report(self):
        return json.loads((self.vp / "report.json").read_text(encoding="utf-8"))

    def _success_result(self):
        return AgentRunResult("test-run", "demo", "planner-judge",
                              success=True, duration_seconds=0.0)

    def _attr_file_exists(self) -> bool:
        return (self.vp / "judge_attribution.json").exists()

    def _read_attr(self) -> dict:
        return json.loads(
            (self.vp / "judge_attribution.json").read_text(encoding="utf-8"))

    def _manifest_exists(self) -> bool:
        return (self.vp / "requeue_manifest.json").exists()

    def _read_manifest(self) -> dict:
        return json.loads(
            (self.vp / "requeue_manifest.json").read_text(encoding="utf-8"))

    def _fixed_dual_evidence(self, sc: dict, idx: int = 0) -> dict:
        """重合成产物形态：同场景补齐结构化双证据（深拷贝防污染原夹具）。"""
        fixed = json.loads(json.dumps(sc, ensure_ascii=False))
        fixed.setdefault("evidence", {})
        fixed["evidence"][ATTRIBUTION_MEASUREMENT_REFS_FIELD] = [
            f"load1=5.0{idx}（宿主采样）"]
        fixed["evidence"][ATTRIBUTION_CONTROL_SAMPLES_FIELD] = [
            f"历史轮次 r-{idx}：同宿主窗口外重跑通过"]
        return fixed


# ── 0. 主判据单源（judge_env_evidence_gate）───────────────────────────────


class TestJudgeEnvEvidenceGate(unittest.TestCase):
    """证据门主判据：结构化字段优先、文本回退、同窗自测反例必拒。"""

    def test_structured_dual_evidence_passes(self):
        sc = _env_scenario("e", measurement=["load1=5.07（宿主采样）"],
                           control=["历史轮次 r-1 窗口外重跑通过"])
        ok, missing = judge_env_evidence_gate(sc)
        assert ok and missing == []

    def test_text_fallback_passes(self):
        text = ("load1=5.07~17.60 波动期间 fps 恒定 36.2~37.5；"
                "同宿主 20:17 历史轮重跑 51.8fps 12/12 PASS")
        sc = _env_scenario("e", evidence_text=text)
        ok, missing = judge_env_evidence_gate(sc)
        assert ok and missing == []

    def test_same_window_selftest_rejected(self):
        """proposal 反例：两轮同窗自测（37.4/38.6）有数值但无窗外对照 → 拒。"""
        sc = _env_scenario("e", evidence_text="两轮同窗自测 fps 37.4/38.6")
        ok, missing = judge_env_evidence_gate(sc)
        assert not ok
        assert missing == [ATTRIBUTION_CONTROL_SAMPLES_FIELD]

    def test_word_boundary_excludes_substring_matches(self):
        """文本回退正则词边界（code-review 9b8b0ac2d0fe / c36639c6d972）：

        普通词内部的标记子串不构成要件——"priority 1 handling" 不满足窗外
        对照（裸 prior 词内命中）；"position 1"/"version 2"/"download 5"
        不满足环境量测（ion/load 词内命中）。真实量测表述（独立词 load/IO
        邻接数值）仍命中。
        """
        # 对照要件：priority 类字样 ≠ 窗外对照标记
        sc = _env_scenario("e", measurement=["cpu 87%"],
                           evidence_text="priority 1 handling")
        ok, missing = judge_env_evidence_gate(sc)
        assert not ok
        assert missing == [ATTRIBUTION_CONTROL_SAMPLES_FIELD]
        # 量测要件：含 io/load 子串的普通词 + 数字不算量测
        for text in ("position 1", "version 2", "download 5"):
            sc = _env_scenario("e", control=["历史轮次 r-1"],
                               evidence_text=text)
            ok, missing = judge_env_evidence_gate(sc)
            assert not ok, text
            assert missing == [ATTRIBUTION_MEASUREMENT_REFS_FIELD], text
        # 真实量测表述仍命中（独立英文量测名邻接数值，无单位符号干扰）
        sc = _env_scenario("e", control=["历史轮次 r-1"],
                           evidence_text="load 12.3（宿主采样）；IO 45")
        ok, missing = judge_env_evidence_gate(sc)
        assert ok and missing == []

    def test_missing_measurement_rejected(self):
        sc = _env_scenario("e", control=["历史轮次 r-1"])
        ok, missing = judge_env_evidence_gate(sc)
        assert not ok
        assert missing == [ATTRIBUTION_MEASUREMENT_REFS_FIELD]

    def test_missing_both_rejected(self):
        ok, missing = judge_env_evidence_gate(_env_scenario("e"))
        assert not ok
        assert set(missing) == {
            ATTRIBUTION_MEASUREMENT_REFS_FIELD, ATTRIBUTION_CONTROL_SAMPLES_FIELD}

    def test_non_dict_rejected(self):
        ok, missing = judge_env_evidence_gate("not-a-dict")
        assert not ok

    def test_refs_reader_missing_field_treated_empty(self):
        """读取侧缺字段按空处理（向后兼容）。"""
        assert attribution_refs({"id": "s1"}, ATTRIBUTION_MEASUREMENT_REFS_FIELD) == []
        assert attribution_refs(
            {"id": "s1", "evidence": {}}, ATTRIBUTION_CONTROL_SAMPLES_FIELD) == []
        assert attribution_refs("not-a-dict", ATTRIBUTION_MEASUREMENT_REFS_FIELD) == []


# ── 1. 量测+对照齐全 → accept 且新字段落盘 ────────────────────────────────


class TestEnvWithDualEvidenceAccepted(_BaseTest):
    def test_env_with_dual_evidence_accepted_and_fields_persisted(self):
        trio = [_dup_scenario(f"d{i}") for i in range(3)]
        env_ok = _env_scenario(
            "e-ok",
            measurement=["load1=5.07~17.60（宿主采样）"],
            control=["历史轮次 20:17：同宿主窗口外重跑 12/12 PASS"],
        )
        self._write_report(trio + [env_ok])
        seen = {}

        def _side_effect(spec, mode):
            # 重合成派发瞬间取证：条目应已落盘
            if self._attr_file_exists():
                seen.setdefault("attr", self._read_attr())
            if self._manifest_exists():
                seen.setdefault("manifest", self._read_manifest())
            # 重合成产物：重复组差异化+补齐证据 → 查重与证据门双双放行 → 采纳
            fixed = []
            for i, sc in enumerate(trio):
                fx = self._fixed_dual_evidence(sc, i)
                fx["evidence"]["first_failed_step"] = (
                    f"步骤1: 重复场景 d{i} 独立错误 {i}")
                fixed.append(fx)
            fixed.append(env_ok)
            self._write_report(fixed)
            return self._success_result()

        self.agent_runner.run_planner.side_effect = _side_effect

        with mock.patch.object(self.engine, "_send_human_escalation_alert") as alert:
            self.engine._verification._handle_scenario_requeue(
                "demo", self._read_report(),
                check_batch_attribution_dedup_scenario(self._read_report()),
            )

        assert "attr" in seen, "judge_attribution.json 应已落盘"
        by_id = {e["id"]: e for e in seen["attr"]["scenarios"]}
        # 双要件齐全 → accept 且新字段随条目落盘（消费方可据此复核）
        assert by_id["e-ok"]["status"] == "accept"
        assert by_id["e-ok"]["measurement_refs"] == ["load1=5.07~17.60（宿主采样）"]
        assert by_id["e-ok"]["control_samples"] == [
            "历史轮次 20:17：同宿主窗口外重跑 12/12 PASS"]
        # 重复组照旧 requeue（查重语义不因证据门弱化）
        assert all(by_id[f"d{i}"]["status"] == "requeue" for i in range(3))
        # 补证后的重合成产物被采纳：回炉清单已清除（闭环收口）
        assert self.agent_runner.run_planner.call_count >= 1
        assert not self._manifest_exists(), "合规采纳后回炉清单应清除"
        assert not alert.called


# ── 2. 缺量测或缺对照 → requeue 落盘且不落 accept ─────────────────────────


class TestEnvMissingEvidenceRequeued(_BaseTest):
    def test_env_missing_evidence_requeued_with_missing_note(self):
        scenarios = [
            _env_scenario("e-no-measure",
                          control=["历史轮次 r-1 窗口外重跑通过"]),
            _env_scenario("e-no-control",
                          measurement=["load1=5.07（宿主采样）"]),
            _env_scenario("e-both-missing"),
            # 反例：有数值但对照是两轮同窗自测 → 仍缺窗外对照
            _env_scenario("e-same-window-only",
                          evidence_text="两轮同窗自测 fps 37.4/38.6"),
            # 文本回退：量测数值 + 窗外对照标记齐全 → 放行
            _env_scenario("e-text-fallback",
                          evidence_text=(
                              "load1=5.07~17.60 波动期间 fps 恒定 36.2~37.5；"
                              "同宿主 20:17 历史轮重跑 51.8fps 12/12 PASS")),
            _env_scenario("e-ok", measurement=["cpu 87%"],
                          control=["上一轮历史基线：同宿主通过"]),
        ]
        self._write_report(scenarios)
        seen = {}

        def _side_effect(spec, mode):
            if self._attr_file_exists():
                seen.setdefault("attr", self._read_attr())
            # 重合成产物全部补齐证据 → 采纳
            self._write_report([
                self._fixed_dual_evidence(sc, i)
                for i, sc in enumerate(scenarios)
            ])
            return self._success_result()

        self.agent_runner.run_planner.side_effect = _side_effect

        with mock.patch.object(self.engine, "_send_human_escalation_alert"):
            # 生产同源配对：统一入口证据门并入拒绝子集 → 场景级回炉收口
            gate = _run_attribution_gate(
                self.engine._verification, "demo", self._read_report(), " ")
            assert gate["ok"] is False, "缺证 env 条目应被证据门并入拒绝子集"
            self.engine._verification._handle_scenario_requeue(
                "demo", self._read_report(), gate)

        assert "attr" in seen, "judge_attribution.json 应已落盘"
        by_id = {e["id"]: e for e in seen["attr"]["scenarios"]}
        # 缺量测 → requeue 且注明缺失项
        assert by_id["e-no-measure"]["status"] == "requeue"
        assert by_id["e-no-measure"]["gate_missing"] == [
            ATTRIBUTION_MEASUREMENT_REFS_FIELD]
        assert "环境量测" in by_id["e-no-measure"]["gate_note"]
        # 缺对照 → requeue 且注明缺失项
        assert by_id["e-no-control"]["status"] == "requeue"
        assert by_id["e-no-control"]["gate_missing"] == [
            ATTRIBUTION_CONTROL_SAMPLES_FIELD]
        assert "对照样本" in by_id["e-no-control"]["gate_note"]
        # 双缺 → requeue 且两项都注
        assert by_id["e-both-missing"]["status"] == "requeue"
        assert set(by_id["e-both-missing"]["gate_missing"]) == {
            ATTRIBUTION_MEASUREMENT_REFS_FIELD, ATTRIBUTION_CONTROL_SAMPLES_FIELD}
        # 同窗自测反例 → 仍因缺窗外对照降级
        assert by_id["e-same-window-only"]["status"] == "requeue"
        assert by_id["e-same-window-only"]["gate_missing"] == [
            ATTRIBUTION_CONTROL_SAMPLES_FIELD]
        # 文本回退双要件齐全 → accept（不落降级注记）
        assert by_id["e-text-fallback"]["status"] == "accept"
        assert "gate_missing" not in by_id["e-text-fallback"]
        # 结构化双要件齐全 → accept 且字段落盘
        assert by_id["e-ok"]["status"] == "accept"
        assert by_id["e-ok"]["measurement_refs"] == ["cpu 87%"]
        # 统一入口证据门并入的回炉 id 留痕（分账防「模板化硬编码」误标）
        assert gate.get("env_gate_requeue_ids") is not None


# ── 3. 降级条目走回炉闭环、不触发豁免握手 ────────────────────────────────


class TestDegradedEnvEntersRecheckLoop(_BaseTest):
    def test_degraded_env_requeued_not_exemption_handshake(self):
        """单 env 条目证据门不过 → 回炉清单收录+重合成派发；补证后重评估采纳。

        不触发豁免握手（env-blocked inconclusive 通道）与 escalation 告警。
        """
        self._write_report([_env_scenario("e1")])
        seen = {}

        def _side_effect(spec, mode):
            if self._manifest_exists():
                seen.setdefault("manifest", self._read_manifest())
            if self._attr_file_exists():
                seen.setdefault("attr", self._read_attr())
            # 重合成产物补充证据 → 证据门重评估通过 → 采纳
            self._write_report([self._fixed_dual_evidence(_env_scenario("e1"))])
            return self._success_result()

        self.agent_runner.run_planner.side_effect = _side_effect

        with mock.patch.object(self.engine, "_send_human_escalation_alert") as alert, \
                mock.patch(
                    "core.pm_engine.verification.escalation."
                    "_handle_env_blocked_inconclusive") as env_inconclusive:
            gate = _run_attribution_gate(
                self.engine._verification, "demo", self._read_report(), " ")
            assert gate["ok"] is False, "证据门降级应并入拒绝子集（非旁路）"
            assert gate["requeue_ids"] == ["e1"]
            assert any(
                "env 归因证据门" in str(v.get("reason") or "")
                for v in gate["violations"]
            ), "拒绝清单应含证据门违规条目（驱动重合成定向补证）"
            self.engine._verification._handle_scenario_requeue(
                "demo", self._read_report(), gate)

        # 回炉清单收录降级条目（下轮 judge 只重做该子集）
        assert "manifest" in seen, "requeue_manifest.json 应已落盘"
        assert seen["manifest"]["requeue_scenario_ids"] == ["e1"]
        # 条目按 requeue 落盘、不落 accept，注明缺失项
        entry = {e["id"]: e for e in seen["attr"]["scenarios"]}["e1"]
        assert entry["status"] == "requeue"
        assert set(entry["gate_missing"]) == {
            ATTRIBUTION_MEASUREMENT_REFS_FIELD, ATTRIBUTION_CONTROL_SAMPLES_FIELD}
        # 重合成已派发（轻量重合成，非 tester 重跑）
        assert self.agent_runner.run_planner.call_count >= 1
        # 补证后重评估采纳：回炉清单清除 = 闭环收口
        assert not self._manifest_exists()
        # 不触发豁免握手 / env-blocked inconclusive 通道 / escalation
        env_inconclusive.assert_not_called()
        alert.assert_not_called()

    def test_gate_merge_skips_cascade_exempt_entries(self):
        """级联豁免场景（引擎合成条目）不参与证据门——豁免语义不被回炉改写。"""
        cascade = {
            "scenario_id": "c1", "status": "blocked-env", "classification": "env",
            "evidence": {"error": "依赖场景失败，未执行: gradle-setup"},
            "assertion_triage": [],
            "dependency_skipped": True,
            "skipped_depends_on": ["gradle-setup"],
        }
        self._write_report([cascade, cascade | {"scenario_id": "c2"},
                            cascade | {"scenario_id": "c3"}])
        gate = _run_attribution_gate(
            self.engine._verification, "demo", self._read_report(), " ")
        assert gate["ok"] is True, "纯级联组豁免不因证据门回炉"
        assert not gate.get("env_gate_requeue_ids")


# ── 4. 旧格式 judge_attribution.json 兼容读取 ────────────────────────────


class TestLegacyAttributionCompat(_BaseTest):
    def test_new_format_entry_without_new_fields_reads_back_compat(self):
        save_attribution(self.tmpdir, "demo", [
            {"id": "s1", "attribution": "归因1", "status": "accept",
             "timestamp": "t1"},
        ])
        entry = load_attribution(self.tmpdir, "demo")["scenarios"][0]
        assert entry.get(ATTRIBUTION_MEASUREMENT_REFS_FIELD) is None
        assert attribution_refs(
            entry, ATTRIBUTION_MEASUREMENT_REFS_FIELD) == []
        assert attribution_refs(
            entry, ATTRIBUTION_CONTROL_SAMPLES_FIELD) == []

    def test_legacy_block_format_migrated_entry_reads_compat(self):
        self.vp.mkdir(parents=True, exist_ok=True)
        legacy = {"attribution": "整块归因文本", "classification": "env"}
        (self.vp / "judge_attribution.json").write_text(
            json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
        data = load_attribution(self.tmpdir, "demo")
        assert data.get("migrated_from_legacy") is True
        entry = data["scenarios"][0]
        assert entry["id"] == "legacy_0"
        # 迁移条目缺新字段按空处理，证据门照常评估（保守降级）
        assert attribution_refs(
            entry, ATTRIBUTION_MEASUREMENT_REFS_FIELD) == []
        ok, missing = judge_env_evidence_gate(entry)
        assert not ok and len(missing) == 2

    def test_entries_with_new_fields_roundtrip_preserved(self):
        save_attribution(self.tmpdir, "demo", [
            {"id": "s2", "attribution": "归因2", "status": "accept",
             "timestamp": "t2",
             ATTRIBUTION_MEASUREMENT_REFS_FIELD: ["load1=5.07"],
             ATTRIBUTION_CONTROL_SAMPLES_FIELD: ["历史轮次 r-1"]},
        ])
        entry = load_attribution(self.tmpdir, "demo")["scenarios"][0]
        assert entry[ATTRIBUTION_MEASUREMENT_REFS_FIELD] == ["load1=5.07"]
        assert entry[ATTRIBUTION_CONTROL_SAMPLES_FIELD] == ["历史轮次 r-1"]


# ── 5. 提示词模板与辅门（截断恢复判据收紧）────────────────────────────────


class TestPromptSideGates(unittest.TestCase):
    def test_judge_template_declares_dual_evidence_requirement(self):
        from core.agent_runner.prompt_builder import AGENT_PROMPT_DIR

        template = (AGENT_PROMPT_DIR / "planner-judge.md").read_text(
            encoding="utf-8")
        assert "可复核环境量测" in template
        assert "验证窗口外的对照样本" in template
        assert "measurement_refs" in template
        assert "control_samples" in template
        assert "不构成对照" in template

    def test_scenario_classified_env_requires_dual_evidence(self):
        """辅门：env 条目缺双证据不视为「已归因存档」（截断恢复不沿用）。"""
        from core.agent_runner.prompt_builder import PromptBuilder

        ok = _env_scenario("e", measurement=["load1=5.07"],
                           control=["历史轮次 r-1"])
        assert PromptBuilder._scenario_classified(ok) is True
        bad = _env_scenario("e")
        assert PromptBuilder._scenario_classified(bad) is False
        # 非 env 分类不受证据门约束（既有判据不变）
        non_env = {"scenario_id": "p", "status": "fail",
                   "classification": "product-bug",
                   "evidence": {"first_failed_step": "断言失败"}}
        assert PromptBuilder._scenario_classified(non_env) is True


if __name__ == "__main__":
    unittest.main()
