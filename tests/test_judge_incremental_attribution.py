"""
judge-incremental-attribution 集成测试（add-judge-incremental-attribution SPEC 3.1）

覆盖：
  1. 部分重复仅回炉子集并保留已通过场景（accept 场景归因保留复用）
  2. 全量重复仍整批回炉+告警（escalation 沿既有预算路径照发）
  3. 旧整块结构向后兼容读（judge_files.py 兼容层）
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
    load_attribution, save_attribution, migrate_legacy_attribution_file,
)
from core.verdict_check import check_batch_attribution_dedup_scenario


class _FakeLogger:
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass
    def debug(self, *a, **k): pass


# ── helpers ────────────────────────────────────────────────────────────────

def _dup_scenario(sid: str, idx: int = 0) -> dict:
    """三个同文场景中的一个（查重组）。"""
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


def _diff_scenario(sid: str, idx: int) -> dict:
    """差异化场景（不在重复组内）。"""
    return {
        "scenario_id": sid, "status": "fail", "classification": "env",
        "evidence": {
            "first_failed_step": f"步骤{idx + 1}: 不同错误，场景 {sid} 独立",
        },
        "assertion_triage": [{
            "assertion": f"断言-{idx}", "classification": "env",
            "evidence": f"场景 {sid} 完整错误文本",
        }],
    }


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


# ── 1. 部分重复仅回炉子集并保留已通过场景 ──────────────────────────────────


class TestPartialRequeueKeepsAccepted(_BaseTest):
    """3 个重复 + 2 个差异化 → 仅重复组 requeue，差异化 accept 保留。"""

    def test_partial_requeue_preserves_accepted_scenarios(self):
        scenarios = (
            [_dup_scenario(f"d{i}") for i in range(3)]
            + [_diff_scenario(f"u{i}", i) for i in range(2)]
        )
        self._write_report(scenarios)
        seen = {}

        def _side_effect(spec, mode):
            # 重合成瞬间取证：accept 场景应已被标记 accept（不被重写）
            if self._attr_file_exists():
                attr = self._read_attr()
                seen["attr"] = attr
            if self._manifest_exists():
                seen["manifest"] = self._read_manifest()
            # 重合成产物：场景集保持全量（5 个），duplicate 组仍同文（预算耗尽），
            # 差异化场景 u0/u1 归因保持不变——框架不应重写已 accept 场景
            self._write_report(scenarios)
            return self._success_result()

        self.agent_runner.run_planner.side_effect = _side_effect

        with mock.patch.object(self.engine, "_send_human_escalation_alert") as alert:
            result = self.engine._verification._handle_scenario_requeue(
                "demo", self._read_report(),
                check_batch_attribution_dedup_scenario(self._read_report()),
            )

        # 判定：重复组 3 个 → requeue；差异化 2 个 → accept
        assert "attr" in seen, "judge_attribution.json 应已落盘"
        requeue_ids = [e["id"] for e in seen["attr"]["scenarios"]
                       if e["status"] == "requeue"]
        accept_ids = [e["id"] for e in seen["attr"]["scenarios"]
                      if e["status"] == "accept"]
        assert set(requeue_ids) == {"d0", "d1", "d2"}, f"重复组 requeue: {requeue_ids}"
        assert set(accept_ids) == {"u0", "u1"}, f"差异化 accept: {accept_ids}"
        # 回炉清单
        assert "manifest" in seen, "requeue_manifest.json 应已落盘"
        assert set(seen["manifest"]["requeue_scenario_ids"]) == {"d0", "d1", "d2"}
        # 预算机制保留：两次重合成后升级（call_count=2）
        assert self.agent_runner.run_planner.call_count >= 1


# ── 2. 全量重复仍整批回炉+告警 ────────────────────────────────────────────


class TestFullRequeueEscalates(_BaseTest):
    """全部场景同文（模板偷懒）→ requeue 覆盖全量，走预算升级。"""

    def test_full_requeue_escalation_on_budget_exhaustion(self):
        self._write_report([_dup_scenario(f"s{i}") for i in range(5)])

        def _side_effect(spec, mode):
            # 重合成仍同文（真偷懒修不好）
            self._write_report([_dup_scenario(f"s{i}") for i in range(5)])
            return self._success_result()

        self.agent_runner.run_planner.side_effect = _side_effect

        with mock.patch.object(self.engine, "_send_human_escalation_alert") as alert:
            result = self.engine._verification._handle_scenario_requeue(
                "demo", self._read_report(),
                check_batch_attribution_dedup_scenario(self._read_report()),
            )

        assert self._attr_file_exists(), "全量回炉也应写 judge_attribution.json"
        attr = self._read_attr()
        requeue_ids = [e["id"] for e in attr["scenarios"]
                       if e["status"] == "requeue"]
        assert len(requeue_ids) == 5, f"全量 requeue: {requeue_ids}"
        # 预算机制：2 次重合成后升级 blocked
        entry = self.sm.read_one("demo")
        assert entry["status"] == "blocked", "全量重复应最终 blocked"
        assert alert.called, "全量重复应发 escalation 告警"


# ── 3. 旧整块结构向后兼容读 ─────────────────────────────────────────────────


class TestLegacyAttributionCompat(_BaseTest):
    """旧格式 judge_attribution.json（无 scenarios 列表）可被回退解析。"""

    def test_legacy_block_format_read_compat(self):
        # 模拟旧格式：顶层 attribution 字段（整块）
        legacy = {
            "attribution": "整块归因文本",
            "classification": "env",
            "status": "verified",
        }
        self.vp.mkdir(parents=True, exist_ok=True)
        (self.vp / "judge_attribution.json").write_text(
            json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
        data = load_attribution(self.tmpdir, "demo")
        assert data is not None, "旧格式应可加载"
        assert data.get("migrated_from_legacy") is True, "应回退解析标记"
        assert len(data["scenarios"]) == 1, f"旧整块→单条目: {data['scenarios']}"
        assert data["scenarios"][0]["id"] == "legacy_0"
        assert data["scenarios"][0]["attribution"] == "整块归因文本"

    def test_migrate_legacy_returns_new_format(self):
        legacy = {"attribution": "归因", "classification": "test-defect"}
        self.vp.mkdir(parents=True, exist_ok=True)
        (self.vp / "judge_attribution.json").write_text(
            json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
        ok = migrate_legacy_attribution_file(self.tmpdir, "demo")
        assert ok, "迁移应成功"
        data = load_attribution(self.tmpdir, "demo")
        assert data.get("migrated_from_legacy") is not True, "迁移后不应再标记 legacy"
        assert data["scenarios"][0]["attribution"] == "归因"

    def test_new_format_roundtrip_preserves_scenarios(self):
        """新格式（含 scenarios 列表）直接读写 roundtrip。"""
        save_attribution(self.tmpdir, "demo", [
            {"id": "s1", "attribution": "归因1", "status": "accept", "timestamp": "t1"},
            {"id": "s2", "attribution": "归因2", "status": "requeue", "timestamp": "t2"},
        ])
        data = load_attribution(self.tmpdir, "demo")
        assert data["format_version"] == "1.0"
        assert len(data["scenarios"]) == 2
        assert data["scenarios"][0]["status"] == "accept"
        assert data["scenarios"][1]["status"] == "requeue"


# ── 4. 回炉清单 prompt 注入 ────────────────────────────────────────────────


class TestRequeueManifestPromptInjection(_BaseTest):
    def _builder(self):
        from core.agent_runner.prompt_builder import PromptBuilder
        return PromptBuilder(self.engine)

    def _write_manifest(self):
        self.vp.mkdir(parents=True, exist_ok=True)
        (self.vp / "requeue_manifest.json").write_text(
            json.dumps({"spec": "demo", "rejection_round": 2,
                        "requeue_scenario_ids": ["d0", "d1", "d2"]},
                       ensure_ascii=False), encoding="utf-8")

    def test_manifest_section_rendered_when_present(self):
        """回炉清单存在 → 注入 requeue 子集 + accept 保留纪律。"""
        self._write_manifest()
        section = self._builder()._requeue_manifest_section("demo")
        assert "回炉清单" in section
        assert "d0、d1、d2" in section
        assert "原样保留复用" in section
        assert "MUST NOT 重写/复现/改动任何字段" in section

    def test_manifest_section_empty_when_missing(self):
        """manifest 缺失 → 空串（普通裁决轮零注入）。"""
        section = self._builder()._requeue_manifest_section("demo")
        assert section == ""

    def test_manifest_section_empty_when_corrupt(self):
        """manifest 损坏 → 空串（fail-open）。"""
        self.vp.mkdir(parents=True, exist_ok=True)
        (self.vp / "requeue_manifest.json").write_text("{broken", encoding="utf-8")
        section = self._builder()._requeue_manifest_section("demo")
        assert section == ""

    def test_judge_template_has_incremental_attribution_contract(self):
        """agents/planner-judge.md 含归因逐场景增量落盘契约。"""
        from core.agent_runner.prompt_builder import AGENT_PROMPT_DIR
        template = (AGENT_PROMPT_DIR / "planner-judge.md").read_text(
            encoding="utf-8")
        assert "归因逐场景增量落盘" in template
        assert "{judge_attribution_path}" in template
        assert '{"id": "<场景ID>"' in template


if __name__ == "__main__":
    unittest.main()
