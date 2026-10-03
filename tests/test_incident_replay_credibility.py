"""
事故回放验证（add-verdict-credibility-gate / tasks 6.2）

以 add-spec-status-modal-budget 事故（2026-09-09/10，烧 $163+）形状为夹具，
逐项验证本 SPEC 的新防线：

  1. 白屏标签命中：5 并发白屏 → screenshot 健全性判定产出 blank_screenshot
  2. registry ignored 归因被降级/改判 env：judge 闭眼归因到数据层 → 框架强制
     白屏方向约束改判 env
  3. 缓存归因带标：verdict_cache 指纹命中 → cached_from_previous_round
  4. 批量文案被拒：enrich_report.py 硬编码 CROSS_FIRST_FAILED 一次套 12 场景
     → 批量归因查重拒绝
  5. SIGNAL 写入：连续 4 轮 blocked-env → admin store 收到 inconclusive_loop

说明：原始 incident SPEC（add-spec-status-modal-budget）不在本仓库，夹具按
proposal.md 的事故形态编程构造——白屏截图（纯白 PNG）+ 全批 blocked-env +
硬编码归因常量 + 指纹缓存，逐项击穿各防线。
"""

import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

from core.admin_store import AdminStore, SIGNAL
from core.verdict_check import (
    ATTRIBUTION_LEVEL_EVIDENCE_BACKED,
    ATTRIBUTION_LEVEL_SPECULATIVE,
    check_batch_attribution_dedup,
    compute_attribution_level,
    enforce_blank_screenshot_direction,
    scenario_fingerprint,
    should_suppress_bug_found,
    tag_cached_attributions,
    validate_attribution_levels,
)
from core.verify_engine.screenshot_lab import classify_screenshot

# ── 事故形状构造 ───────────────────────────────────────────────


class IncidentReplayTest(unittest.TestCase):
    """以 add-spec-status-modal-budget 事故形状逐项验证新防线。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))
        # 事故形态 1：5 并发白屏截图（纯白 PNG）
        white = np.full((4714 // 16, 4714 // 16, 3), 255, dtype=np.uint8)
        # 与事故描述对齐：白屏被固化为视觉基线（4714B 纯白图）
        self.blank_png = self.tmpdir / "blank.png"
        Image.fromarray(white).save(str(self.blank_png))

    # ── G1 白屏标签命中 ────────────────────────────────────────

    def test_g1_blank_screenshot_label_hit(self):
        """事故第 1 道防线：白屏截图 → blank_screenshot 标签命中。"""
        labels = classify_screenshot(str(self.blank_png))
        self.assertTrue(labels.get("blank_screenshot"),
                        "白屏截图应命中 blank_screenshot 标签")

    def test_g1_blank_label_feeds_attribution_level(self):
        """白屏标签 → 归因机械判 evidence-backed（算法标签佐证）。"""
        sc = {
            "scenario_id": "s-white-1", "status": "fail",
            "classification": "product-bug",
            "screenshot_labels": classify_screenshot(str(self.blank_png)),
            "evidence": {},
        }
        self.assertEqual(compute_attribution_level(sc),
                         ATTRIBUTION_LEVEL_EVIDENCE_BACKED)

    # ── G2 registry ignored 归因被改判 env ─────────────────────

    def test_g2_registry_attribution_forced_env(self):
        """事故第 2 道防线：judge 归因「registry ignored」——白屏强制 env 方向。"""
        sc = {
            "scenario_id": "s-white-2", "status": "fail",
            "classification": "product-bug",
            "screenshot_labels": {"blank_screenshot": True},
            "evidence": {"first_failed_step": "assert 行选择器无匹配"},
            "assertion_triage": [{
                "assertion": "项目列表为空（行选择器无匹配）",
                "classification": "product-bug",
                "evidence": "registry ignored",
            }],
        }
        new_cls = enforce_blank_screenshot_direction(sc)
        self.assertEqual(new_cls, "env", "白屏场景归因到数据层必须改判 env")
        # 改判后归因级别为 evidence-backed（白屏标签佐证）
        sc["classification"] = new_cls
        self.assertEqual(compute_attribution_level(sc),
                         ATTRIBUTION_LEVEL_EVIDENCE_BACKED)

    def test_g2_all_speculative_suppressed(self):
        """事故第 3 道防线：纯推测归因不许打回 implementer。"""
        report = {"scenarios": []}
        for i in range(5):
            report["scenarios"].append({
                "scenario_id": f"s-{i}", "status": "fail",
                "classification": "product-bug",
                "evidence": {"first_failed_step": f"CROSS_FIRST_FAILED_{i}"},
                "screenshot_labels": {}, "screenshots": [],
                "assertion_triage": [],
            })
        validate_attribution_levels(report)
        # 无截图、无标签、无失败断言归因 → 全部 speculative → 抑制打回
        self.assertTrue(should_suppress_bug_found(report))

    # ── G3 缓存归因带标 ────────────────────────────────────────

    def test_g3_cached_attribution_tagged(self):
        """事故第 4 道防线：verdict_cache 命中 → cached_from_previous_round。"""
        sc = {
            "scenario_id": "s-cache-1", "status": "fail",
            "classification": "product-bug",
            "assertion_results": [{"type": "element_visible", "pass": False,
                                   "expected": "可见", "actual": "不可见"}],
            "assertion_triage": [{
                "assertion": "元素不可见", "classification": "product-bug",
                "evidence": "按钮未渲染",
            }],
            "screenshot_labels": {}, "screenshots": [],
        }
        fp = scenario_fingerprint(sc)
        cache = {"s-cache-1": {"fingerprint": fp,
                               "classification": "product-bug",
                               "evidence": {"first_failed_step": "旧轮归因"},
                               "source_round": 2}}
        report = {"scenarios": [sc]}
        validate_attribution_levels(report)
        tagged = tag_cached_attributions(report, cache, "spec")
        self.assertIn("s-cache-1", tagged)
        self.assertTrue(sc.get("cached_from_previous_round"))
        self.assertEqual(sc.get("cached_source_round"), 2)

    def test_g3_pure_cached_suppressed(self):
        """事故第 5 道防线：纯缓存归因不构成打回依据（按 speculative 口径门禁）。"""
        sc = {
            "scenario_id": "s-cache-2", "status": "fail",
            "classification": "product-bug",
            "assertion_results": [{"type": "element_visible", "pass": False,
                                   "expected": "可见", "actual": "不可见"}],
            "assertion_triage": [{
                "assertion": "元素不可见", "classification": "product-bug",
                "evidence": "旧轮缓存",
            }],
            "screenshot_labels": {}, "screenshots": [],
        }
        fp = scenario_fingerprint(sc)
        cache = {"s-cache-2": {"fingerprint": fp,
                               "classification": "product-bug",
                               "evidence": {"first_failed_step": "旧轮归因"}}}
        report = {"scenarios": [sc]}
        validate_attribution_levels(report)
        tag_cached_attributions(report, cache, "spec")
        self.assertEqual(sc.get("attribution_level"),
                         ATTRIBUTION_LEVEL_SPECULATIVE)
        self.assertTrue(sc.get("cached_from_previous_round"))
        # 纯缓存归因 → 全部打回依据为推测级 → 抑制 bug-found
        self.assertTrue(should_suppress_bug_found(report))

    # ── G4 批量文案被拒 ────────────────────────────────────────

    def test_g4_batch_hardcoded_attribution_rejected(self):
        """事故第 6 道防线：enrich_report.py 硬编码 CROSS_FIRST_FAILED 套 12 场景。"""
        report = {"scenarios": []}
        for i in range(12):
            report["scenarios"].append({
                "scenario_id": f"s-enrich-{i}", "status": "fail",
                "classification": "test-defect",
                "evidence": {"first_failed_step": "CROSS_FIRST_FAILED"},
                "assertion_triage": [{
                    "assertion": "CROSS_FIRST_FAILED",
                    "classification": "test-defect",
                    "evidence": "CROSS_FIRST_FAILED",
                }],
            })
        result = check_batch_attribution_dedup(report)
        self.assertFalse(result["ok"],
                         "批量硬编码归因必须被拒绝落盘")
        self.assertEqual(len(result["violations"]), 1)
        self.assertEqual(len(result["violations"][0]["scenario_ids"]), 12,
                         "12 个场景全部命中查重")
        self.assertIn("CROSS_FIRST_FAILED", result["violations"][0]["reason"])

    def test_g4_batch_report_rejected_in_pipeline(self):
        """事故第 7 道防线：管线级验证——批量查重同入口拒绝落盘。"""
        report = {"scenarios": []}
        for i in range(4):
            report["scenarios"].append({
                "scenario_id": f"s-enrich-{i}", "status": "fail",
                "classification": "test-defect",
                "evidence": {"first_failed_step": "SAME_HARDCODED_REASON"},
                "assertion_triage": [{
                    "assertion": "SAME_HARDCODED_REASON",
                    "classification": "test-defect",
                    "evidence": "SAME_HARDCODED_REASON",
                }],
            })
        # 管线先做批量查重（与 _verify_verdict_evidence 同入口）
        dedup = check_batch_attribution_dedup(report)
        self.assertFalse(dedup["ok"])
        # 若带上从整改后的逐场景归因（各场景有区分）→ 放行
        for i, sc in enumerate(report["scenarios"]):
            sc["evidence"]["first_failed_step"] = f"逐场景归因-{sc['scenario_id']}"
            sc["assertion_triage"][0]["evidence"] = f"逐场景归因-{sc['scenario_id']}"
        fixed = check_batch_attribution_dedup(report)
        self.assertTrue(fixed["ok"], "逐场景归因后放行")

    # ── G5 SIGNAL 写入 ─────────────────────────────────────────

    def test_g5_signal_written_at_threshold(self):
        """事故第 8 道防线：连续 4 轮 blocked-env → SIGNAL 写 admin store。"""
        from core.pm_engine.engine import PMEngine
        from core.state_machine import StateMachine

        class _FakeLogger:
            def info(self, *a): pass
            def warning(self, *a): pass
            def error(self, *a): pass
            def debug(self, *a): pass

        logger = _FakeLogger()
        (self.tmpdir / ".fenix").mkdir(parents=True, exist_ok=True)
        sm = StateMachine(self.tmpdir / ".fenix" / "STATE.md", logger)
        config = {"verify_engine": {
            "inconclusive_escalate_attempts": 4,
            "inconclusive_max_attempts": 10,
        }}
        engine = PMEngine(sm, mock.MagicMock(), config, self.tmpdir, logger)
        sm.add_spec("s1", {"priority": 5})
        sm.update_spec("s1", {"status": "implemented"})

        # 逐轮换 scenario_id（fix-env-exemption-exit-reachability 2.2 后签名
        # 一致会提前升级，第 2 轮即截停；本用例考察的是 4 轮计数路径）
        for i in range(4):
            report = {"summary": {"total": 5, "passed": 0, "warnings": 5,
                                  "failed": 0, "errors": 0, "blocked_env": 5},
                      "scenarios": [
                          {"scenario_id": f"s1-{i}", "status": "blocked-env",
                           "env_probe_detail": "HTTP 探测失联"},
                      ]}
            engine._verification._handle_env_blocked_inconclusive("s1", report)

        store = AdminStore(self.tmpdir, logger)
        signals = [r for r in store.read_all()
                   if r.get("kind") == SIGNAL
                   and r.get("signal_type") == "inconclusive_loop"]
        self.assertEqual(len(signals), 1, "第 4 轮应写入一条 inconclusive_loop SIGNAL")
        self.assertIn("s1", str(signals[0].get("spec")))
        self.assertIn("连续轮数=4", signals[0].get("evidence") or "")
        self.assertIn("末轮blocked_env数=5", signals[0].get("evidence") or "")
        self.assertIn("HTTP 探测失联", signals[0].get("evidence") or "")

    def test_g5_signal_ingested_by_admin_monitor(self):
        """事故第 9 道防线：admin_monitor 摄取 inconclusive_loop → 唤起。"""
        from core.admin_monitor import (
            AdminMonitor, STORED_SIGNAL_TYPES, SIGNAL_RECOMMENDATION)
        self.assertIn("inconclusive_loop", STORED_SIGNAL_TYPES)
        self.assertIn("验证环境核查清单",
                      SIGNAL_RECOMMENDATION.get("inconclusive_loop", ""))
        self.assertIn("解冻",
                      SIGNAL_RECOMMENDATION.get("inconclusive_loop", ""))


if __name__ == "__main__":
    unittest.main()