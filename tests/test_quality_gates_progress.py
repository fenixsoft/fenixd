"""add-quality-gates-visibility 1.x：质量门禁读侧解析与合成用例。

覆盖 specs/quality-gates-progress/spec.md 的读侧契约：
- 合法 quality-gates.json 解析（items 恒 6 道且顺序符合契约、done=passed+skipped、
  未写入条目 pending）；
- 容错（文件缺失/JSON 损坏/枚举外 status/契约外 gate-id → unknown/忽略，不抛异常
  无 error 字段）；
- 框架 3 项合成（result-artifact-gate 按 run 终态、deliverable-guard 按 STATE、
  code-review 按 ocr 车道产物三态 + 指纹校验）；
- 车道总开关关闭（verify.impl_code_review）→ code-review 门合成 skipped 归因
  设置（TestOcrDisabledBySetting，fix-quality-gates-ocr-disabled-na）；
- worktree 优先读取策略（implementing 时 worktree 内文件优先、主树兜底）。

fix-quality-gates-flat-form-and-explainability 扩展覆盖：
- 读侧平铺形态容错（specs/quality-gates-form-tolerance：六分支，TestFlatFormTolerance）；
- pending/unknown 兜底归因文案（specs/quality-gates-explainability，
  TestFallbackAttributionDetail）；
- 宽松对账形态违规告警在 tests/test_quality_gates_soft_alert.py 单独成文。

自查结论（fix-quality-gates-flat-form-and-explainability 4.1）：本 SPEC 未触碰
前端，src/ 下 qualityGates 相关模块零改动（core/dashboard/static/ 与
qualityGates.test.mjs 既有断言零变化，detail 文案由读侧填充后经既有
gateDetailText 透传链渲染）。
"""

import json
import logging
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent_runner import result_gate
from core.dashboard.data import parse_quality_gates

# 契约固化顺序（specs/quality-gates-progress/spec.md）
EXPECTED_ORDER = [
    "full-suite",
    "frontend-build",
    "code-review",
    "interaction-contract",
    "result-artifact-gate",
    "deliverable-guard",
]
EXPECTED_DESCS = {
    "full-suite": "全量回归测试",
    "frontend-build": "前端构建与类型检查",
    "code-review": "ocr 代码审查与处置",
    "interaction-contract": "交互契约自查",
    "result-artifact-gate": "结果文件产物硬门",
    "deliverable-guard": "交付物守卫与格式复检",
}


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


class QualityGatesTestBase:
    """公共夹具：tmp 项目根 + spec 目录。"""

    SPEC = "demo"

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        (self.root / ".fenix").mkdir(parents=True, exist_ok=True)
        d = self.root / "spec" / "changes" / self.SPEC
        d.mkdir(parents=True, exist_ok=True)
        (d / ".spec.yaml").write_text(
            "schema: spec-driven\ncreated: 2026-09-05\n", encoding="utf-8")
        # 车道总开关统一置开：既有用例全部在「开关开启」语境断言 ocr 三态
        # 合成；该开关缺省即关（严格 bool，verify.impl_code_review 缺席=False），
        # 不 patch 则 code-review 门全部翻转为「设置不适用 skipped」。关闭
        # 场景（含真实读配置路径）由 TestOcrDisabledBySetting 单独覆盖。
        self._ocr_switch = patch(
            "core.config.ConfigLoader.get_impl_code_review_enabled",
            return_value=True)
        self._ocr_switch.start()

    def teardown_method(self):
        if self._ocr_switch is not None:
            self._ocr_switch.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _use_real_config_reader(self):
        """停用基类统一 patch，走真实 ConfigLoader 读路径（真实接线用例）。"""
        self._ocr_switch.stop()
        self._ocr_switch = None

    def _gates_path(self, proot: Path | None = None) -> Path:
        base = proot or self.root
        return base / ".fenix" / "verify-progress" / self.SPEC / "quality-gates.json"

    def _lane_path(self, proot: Path | None = None) -> Path:
        base = proot or self.root
        return base / ".fenix" / "verify-progress" / self.SPEC / "code-review.json"

    def _write_gates(self, gates: dict, proot: Path | None = None) -> Path:
        p = self._gates_path(proot)
        _write_json(p, {"gates": gates, "updated_at": "2026-09-22T00:00:00+00:00"})
        return p

    def _write_lane(self, data: dict, proot: Path | None = None) -> Path:
        p = self._lane_path(proot)
        _write_json(p, data)
        return p

    def _item(self, out: dict, gid: str) -> dict:
        return next(it for it in out["items"] if it["id"] == gid)


class TestValidFileParsing(QualityGatesTestBase):
    """1.1 合法 quality-gates.json 解析。"""

    def test_six_items_in_contract_order_with_fixed_descs(self):
        self._write_gates({
            "full-suite": {"status": "passed", "passed": 128, "failed": 0},
            "frontend-build": {"status": "skipped", "reason": "无前端改动"},
            "interaction-contract": {"status": "passed"},
        })
        out = parse_quality_gates(self.root, self.SPEC, {"status": "implementing"})
        assert [it["id"] for it in out["items"]] == EXPECTED_ORDER
        for it in out["items"]:
            assert it["desc"] == EXPECTED_DESCS[it["id"]]
        assert out["total"] == 6
        assert out["exists"] is True

    def test_done_counts_passed_and_skipped(self):
        self._write_gates({
            "full-suite": {"status": "passed", "passed": 128, "failed": 0},
            "frontend-build": {"status": "skipped", "reason": "无前端改动"},
            "interaction-contract": {"status": "passed"},
        })
        out = parse_quality_gates(self.root, self.SPEC, {"status": "implementing"})
        # 2 passed + 1 skipped 计入 done（框架 3 项 implementing 均.pending）
        assert out["done"] == 3
        assert self._item(out, "full-suite")["status"] == "passed"
        assert self._item(out, "frontend-build")["status"] == "skipped"
        assert self._item(out, "interaction-contract")["status"] == "passed"

    def test_full_suite_counts_surface_in_detail(self):
        self._write_gates({
            "full-suite": {"status": "passed", "passed": 128, "failed": 2},
        })
        out = parse_quality_gates(self.root, self.SPEC, {"status": "implementing"})
        detail = self._item(out, "full-suite")["detail"]
        assert "128" in detail and "2" in detail

    def test_unwritten_entries_pending(self):
        self._write_gates({
            "full-suite": {"status": "passed", "passed": 10, "failed": 0},
        })
        out = parse_quality_gates(self.root, self.SPEC, {"status": "implementing"})
        # 渐进落盘中间态：已写入的 passed，未写入的 pending
        assert self._item(out, "full-suite")["status"] == "passed"
        assert self._item(out, "frontend-build")["status"] == "pending"
        assert self._item(out, "interaction-contract")["status"] == "pending"

    def test_skipped_without_reason_falls_back_unknown(self):
        # skipped MUST 附非空 reason；缺 reason 的 skipped 按 unknown 容错
        self._write_gates({"frontend-build": {"status": "skipped"}})
        out = parse_quality_gates(self.root, self.SPEC, {"status": "implementing"})
        assert self._item(out, "frontend-build")["status"] == "unknown"


class TestFaultTolerance(QualityGatesTestBase):
    """1.2 容错：缺失/损坏/枚举外/契约外 gate-id。"""

    def test_missing_file_run_items_unknown_no_error_field(self):
        out = parse_quality_gates(self.root, self.SPEC, {"status": "drafted"})
        assert out["exists"] is False
        for gid in ("full-suite", "frontend-build", "interaction-contract"):
            assert self._item(out, gid)["status"] == "unknown"
        assert "error" not in out

    def test_corrupt_json_run_items_unknown(self):
        p = self._gates_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{not-json", encoding="utf-8")
        out = parse_quality_gates(self.root, self.SPEC, {"status": "implementing"})
        assert out["exists"] is True
        for gid in ("full-suite", "frontend-build", "interaction-contract"):
            assert self._item(out, gid)["status"] == "unknown"
        assert "error" not in out

    def test_out_of_enum_status_tolerated_as_unknown(self):
        self._write_gates({"full-suite": {"status": "ok"}})
        out = parse_quality_gates(self.root, self.SPEC, {"status": "implementing"})
        assert self._item(out, "full-suite")["status"] == "unknown"
        assert "error" not in out

    def test_out_of_contract_gate_ids_ignored(self):
        # 实现者误写 code-review 键 / 完全未知键 → 读侧忽略，不崩、不污染合成
        self._write_gates({
            "code-review": {"status": "passed"},
            "my-gate": {"status": "passed"},
            "interaction-contract": {"status": "passed"},
        })
        out = parse_quality_gates(self.root, self.SPEC, {"status": "implementing"})
        # code-review 门仍按 ocr 车道产物合成（无产物 → pending），不采信误写键
        assert self._item(out, "code-review")["status"] == "pending"
        assert self._item(out, "interaction-contract")["status"] == "passed"
        assert out["done"] == 1

    def test_non_dict_gates_value_tolerated(self):
        self._write_gates({"full-suite": "passed"})
        out = parse_quality_gates(self.root, self.SPEC, {"status": "implementing"})
        assert self._item(out, "full-suite")["status"] == "unknown"


class TestFlatFormTolerance(QualityGatesTestBase):
    """fix-quality-gates-flat-form-and-explainability 1.2：平铺形态容错六分支。

    契约源 specs/quality-gates-form-tolerance/spec.md：落盘契约的合法形态仍是
    嵌套 ``{"gates": {...}}``，平铺为读侧兼容采信（非合法写法）。
    """

    def _write_flat(self, data) -> None:
        _write_json(self._gates_path(), data)

    def test_nested_form_zero_regression_including_empty_gates_dict(self):
        # 嵌套形态（含空 gates dict）零回归：平铺判定不参与——顶层平铺键在
        # gates dict 在场时被忽略（最强判别：若误走平铺采信，passed 会被采信）
        _write_json(self._gates_path(), {
            "gates": {},
            "frontend-build": {"status": "passed"},
            "updated_at": "2026-09-24T00:00:00Z",
        })
        out = parse_quality_gates(self.root, self.SPEC, {"status": "implementing"})
        assert out["exists"] is True
        assert self._item(out, "frontend-build")["status"] == "pending"

    def test_pure_flat_form_adopted_with_string_metadata(self):
        self._write_flat({
            "full-suite": {"status": "passed", "passed": 128, "failed": 0},
            "frontend-build": {"status": "skipped", "reason": "无前端改动"},
            "interaction-contract": {"status": "passed"},
            "updated_at": "2026-09-24T00:00:00Z",
        })
        out = parse_quality_gates(self.root, self.SPEC, {"status": "implementing"})
        assert self._item(out, "full-suite")["status"] == "passed"
        assert "128" in self._item(out, "full-suite")["detail"]  # 计数透传与嵌套一致
        assert self._item(out, "frontend-build")["status"] == "skipped"
        assert self._item(out, "frontend-build")["detail"] == "无前端改动"
        assert self._item(out, "interaction-contract")["status"] == "passed"
        assert out["done"] == 3  # 2 passed + 1 skipped

    def test_flat_out_of_contract_gate_id_ignored(self):
        self._write_flat({
            "code-review": {"status": "passed"},  # 契约外键：ocr 门归框架侧合成
            "my-gate": {"status": "passed"},
            "interaction-contract": {"status": "passed"},
        })
        out = parse_quality_gates(self.root, self.SPEC, {"status": "implementing"})
        # 误写键被忽略：code-review 门仍按 ocr 车道产物合成（无产物 → pending）
        assert self._item(out, "code-review")["status"] == "pending"
        assert self._item(out, "interaction-contract")["status"] == "passed"
        assert out["done"] == 1

    def test_flat_out_of_enum_status_not_adopted(self):
        # 任一 dict 值 status 枚举外 → 整体不采信（宁可 pending 不误读半个文件）
        self._write_flat({
            "frontend-build": {"status": "passed"},
            "full-suite": {"status": "ok"},
        })
        out = parse_quality_gates(self.root, self.SPEC, {"status": "implementing"})
        assert self._item(out, "frontend-build")["status"] == "pending"
        assert self._item(out, "full-suite")["status"] == "pending"

    def test_flat_missing_status_not_adopted(self):
        # dict 值缺 status 同样整体不采信
        self._write_flat({
            "frontend-build": {"status": "passed"},
            "interaction-contract": {},
        })
        out = parse_quality_gates(self.root, self.SPEC, {"status": "implementing"})
        assert self._item(out, "frontend-build")["status"] == "pending"
        assert self._item(out, "interaction-contract")["status"] == "pending"

    def test_empty_top_level_dict_not_adopted(self):
        self._write_flat({})
        out = parse_quality_gates(self.root, self.SPEC, {"status": "implementing"})
        assert out["exists"] is True
        assert self._item(out, "full-suite")["status"] == "pending"

    def test_metadata_only_top_level_not_adopted(self):
        # 只有字符串型元数据键 → 候选门集为空，不采信
        self._write_flat({"updated_at": "2026-09-24T00:00:00Z"})
        out = parse_quality_gates(self.root, self.SPEC, {"status": "implementing"})
        assert self._item(out, "full-suite")["status"] == "pending"

    def test_corrupt_file_keeps_unknown_semantics(self):
        # 损坏文件（非法 JSON）→ unknown 语义不变，平铺判定不参与
        p = self._gates_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{not-json", encoding="utf-8")
        out = parse_quality_gates(self.root, self.SPEC, {"status": "implementing"})
        assert out["exists"] is True
        for gid in ("full-suite", "frontend-build", "interaction-contract"):
            assert self._item(out, gid)["status"] == "unknown"


class TestFallbackAttributionDetail(QualityGatesTestBase):
    """fix-quality-gates-flat-form-and-explainability 2.2：pending/unknown 兜底归因。"""

    def test_pending_empty_detail_filled(self):
        self._write_gates({"full-suite": {"status": "passed", "passed": 10, "failed": 0}})
        out = parse_quality_gates(self.root, self.SPEC, {"status": "implementing"})
        # 未写入键（渐进落盘中间态）→ pending 空 detail → 兜底文案，status 不变
        for gid in ("frontend-build", "interaction-contract"):
            it = self._item(out, gid)
            assert it["status"] == "pending"
            assert it["detail"] == "该门未了结（run 在飞或自查结果未落盘）"
        # ocr 车道产物不可见 → pending 空 detail → 兜底文案
        assert self._item(out, "code-review")["detail"] == \
            "该门未了结（run 在飞或自查结果未落盘）"

    def test_unknown_empty_detail_filled(self):
        out = parse_quality_gates(self.root, self.SPEC, {"status": "drafted"})
        # 文件缺失 → run 3 项 unknown → 兜底文案
        for gid in ("full-suite", "frontend-build", "interaction-contract"):
            it = self._item(out, gid)
            assert it["status"] == "unknown"
            assert it["detail"] == "门禁记录缺失或损坏"
        # 框架 2 项（drafted 且无 runs）→ unknown → 兜底文案
        for gid in ("result-artifact-gate", "deliverable-guard"):
            it = self._item(out, gid)
            assert it["status"] == "unknown"
            assert it["detail"] == "门禁记录缺失或损坏"

    def test_implementing_existing_attribution_preserved(self):
        # implementing 分支「实现 run 在飞，收尾门禁未了结」零覆盖
        runs_dir = self.root / ".fenix" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        (runs_dir / f"impl-{self.SPEC}-1758000000.jsonl").write_text(
            json.dumps({"type": "provider_marker", "model": "m", "provider": "p"}) + "\n",
            encoding="utf-8")
        out = parse_quality_gates(self.root, self.SPEC, {"status": "implementing"})
        for gid in ("result-artifact-gate", "deliverable-guard"):
            assert self._item(out, gid)["detail"] == "实现 run 在飞，收尾门禁未了结"

    def test_skipped_reason_and_passed_counts_preserved(self):
        self._write_gates({
            "frontend-build": {"status": "skipped", "reason": "无前端改动"},
            "full-suite": {"status": "passed", "passed": 7, "failed": 1},
        })
        out = parse_quality_gates(self.root, self.SPEC, {"status": "implementing"})
        assert self._item(out, "frontend-build")["detail"] == "无前端改动"
        detail = self._item(out, "full-suite")["detail"]
        assert "通过 7" in detail and "失败 1" in detail

    def test_terminal_exempt_text_preserved(self):
        # full-suite 终态豁免文案保留（skipped 不在兜底范围）
        out = parse_quality_gates(self.root, self.SPEC, {"status": "verified"})
        it = self._item(out, "full-suite")
        assert it["status"] == "skipped"
        assert it["detail"] == "SPEC 已终态，全量回归跟踪移交主树"

    def test_gate_blocked_failed_reason_preserved(self):
        # failed 归因原文零覆盖
        runs_dir = self.root / ".fenix" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        reason = "exit 0 但交付物声明对账缺件（deliverable-gate）: core/x.py"
        (runs_dir / f"impl-{self.SPEC}-1758000000.jsonl").write_text(
            json.dumps({"type": "provider_marker", "model": "m", "provider": "p"}) + "\n"
            + json.dumps({"type": "gate-blocked", "spec": self.SPEC,
                          "reason": "artifact_gate", "error": reason}) + "\n",
            encoding="utf-8")
        out = parse_quality_gates(self.root, self.SPEC, {"status": "implementing"})
        assert self._item(out, "result-artifact-gate")["detail"] == reason

    def test_done_unchanged_by_fallback(self):
        # done 口径不变：兜底只改 detail，不改任何门的 status
        self._write_gates({"full-suite": {"status": "passed", "passed": 1, "failed": 0}})
        out = parse_quality_gates(self.root, self.SPEC, {"status": "implementing"})
        assert out["done"] == 1
        assert all(it["status"] in ("passed", "pending") for it in out["items"])
        assert self._item(out, "full-suite")["status"] == "passed"


class TestFrameworkSynthesis(QualityGatesTestBase):
    """1.3 框架 3 项合成（result-artifact-gate / deliverable-guard / code-review）。"""

    def test_guard_items_passed_after_implemented_and_beyond(self):
        for status in ("implemented", "testing", "verified", "done", "pushed"):
            out = parse_quality_gates(self.root, self.SPEC, {"status": status})
            assert self._item(out, "result-artifact-gate")["status"] == "passed", status
            assert self._item(out, "deliverable-guard")["status"] == "passed", status

    def test_gate_blocked_run_failed_with_truncated_reason(self):
        runs_dir = self.root / ".fenix" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        reason = "exit 0 但交付物声明对账缺件（deliverable-gate）: core/x.py"
        (runs_dir / f"impl-{self.SPEC}-1758000000.jsonl").write_text(
            json.dumps({"type": "provider_marker", "model": "m", "provider": "p"}) + "\n"
            + json.dumps({"type": "gate-blocked", "spec": self.SPEC,
                          "reason": "artifact_gate", "error": reason}) + "\n",
            encoding="utf-8")
        out = parse_quality_gates(self.root, self.SPEC, {"status": "implementing"})
        item = self._item(out, "result-artifact-gate")
        assert item["status"] == "failed"
        assert "交付物声明对账缺件" in item["detail"]
        # failed 不计入 done
        assert out["done"] == 0

    def test_gate_blocked_detected_with_prescanned_runs(self):
        # 列表摘要路径：调用方预扫描的 runs 记录直接传入
        runs = [{"run_id": f"impl-{self.SPEC}-1758000000",
                 "agent_type": "implementer", "status": "gate-blocked"}]
        out = parse_quality_gates(self.root, self.SPEC, {"status": "implementing"},
                                  runs=runs)
        assert self._item(out, "result-artifact-gate")["status"] == "failed"

    def test_inflight_implementing_both_guards_pending(self):
        runs_dir = self.root / ".fenix" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        (runs_dir / f"impl-{self.SPEC}-1758000000.jsonl").write_text(
            json.dumps({"type": "provider_marker", "model": "m", "provider": "p"}) + "\n",
            encoding="utf-8")
        out = parse_quality_gates(self.root, self.SPEC, {"status": "implementing"})
        assert self._item(out, "result-artifact-gate")["status"] == "pending"
        assert self._item(out, "deliverable-guard")["status"] == "pending"

    def test_deliverable_guard_failed_on_blocked_with_keyword(self):
        entry = {"status": "blocked",
                 "error": "交付物守卫拦截: 缺 deliverable 声明 core/x.py"}
        out = parse_quality_gates(self.root, self.SPEC, entry)
        item = self._item(out, "deliverable-guard")
        assert item["status"] == "failed"
        assert "core/x.py" in item["detail"]

    def test_deliverable_guard_blocked_without_keyword_pending(self):
        entry = {"status": "blocked", "error": "预算耗尽"}
        out = parse_quality_gates(self.root, self.SPEC, entry)
        assert self._item(out, "deliverable-guard")["status"] == "pending"

    def test_unknown_state_guards_unknown(self):
        for status in ("drafted", "ready", "reviewing", "bug-found"):
            out = parse_quality_gates(self.root, self.SPEC, {"status": status})
            assert self._item(out, "result-artifact-gate")["status"] == "unknown", status
            assert self._item(out, "deliverable-guard")["status"] == "unknown", status

    # ── code-review（ocr 车道产物三态） ────────────────────────────

    def test_lane_product_running(self):
        self._write_lane({"status": "running"})
        out = parse_quality_gates(self.root, self.SPEC, {"status": "testing"})
        item = self._item(out, "code-review")
        assert item["status"] == "running"
        assert "进行中" in item["detail"]

    def test_lane_product_completed_passed_with_findings_count(self):
        self._write_lane({"status": "completed",
                          "findings": [{"path": "a.py"}, {"path": "b.py"}],
                          "dispositions": [{"disposition": "fixed"},
                                           {"disposition": "rejected",
                                            "reason": "误报"}]})
        out = parse_quality_gates(self.root, self.SPEC, {"status": "testing"})
        item = self._item(out, "code-review")
        assert item["status"] == "passed"
        assert "2" in item["detail"]

    def test_lane_product_unavailable_skipped_with_reason(self):
        self._write_lane({"status": "unavailable", "reason": "provider 不可达"})
        out = parse_quality_gates(self.root, self.SPEC, {"status": "testing"})
        item = self._item(out, "code-review")
        assert item["status"] == "skipped"
        assert "provider 不可达" in item["detail"]
        # skipped 计入 done（已了结而非未做）；testing 态框架守卫 2 项亦 passed
        assert out["done"] == 3
        assert self._item(out, "result-artifact-gate")["status"] == "passed"
        assert self._item(out, "deliverable-guard")["status"] == "passed"

    def test_lane_product_missing_pending(self):
        out = parse_quality_gates(self.root, self.SPEC, {"status": "testing"})
        assert self._item(out, "code-review")["status"] == "pending"

    def test_lane_product_corrupt_pending(self):
        p = self._lane_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{broken", encoding="utf-8")
        out = parse_quality_gates(self.root, self.SPEC, {"status": "testing"})
        assert self._item(out, "code-review")["status"] == "pending"


class TestLaneFingerprint(QualityGatesTestBase):
    """1.3 补充：code-review 产物指纹校验（fresh 采信 / stale 按不可见）。"""

    def _git(self, *args) -> str:
        out = subprocess.run(["git", "-C", str(self.root), *args],
                             capture_output=True, text=True)
        assert out.returncode == 0, out.stderr
        return out.stdout.strip()

    def setup_method(self):
        super().setup_method()
        subprocess.run(["git", "init", "-b", "main", str(self.root)],
                       capture_output=True, check=True)
        self._git("config", "user.email", "t@t")
        self._git("config", "user.name", "t")
        (self.root / "base.txt").write_text("base", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-m", "init")
        self._git("checkout", "-b", "fenix/demo")
        (self.root / "feat.txt").write_text("feat", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-m", "feat")
        self.entry = {"status": "testing", "branch": "fenix/demo"}
        from core.dashboard.data import current_lane_fingerprint
        self.fp = current_lane_fingerprint(self.root, self.entry)
        assert self.fp and self.fp["branch"] == "fenix/demo"
        assert self.fp["head_commit"]
        assert self.fp["merge_base"]

    def _write_lane_with_fp(self, data: dict, fp=None) -> None:
        payload = dict(data)
        payload["branch"] = (fp or self.fp)["branch"]
        payload["merge_base"] = (fp or self.fp)["merge_base"]
        payload["head_commit"] = (fp or self.fp)["head_commit"]
        self._write_lane(payload)

    def test_fresh_fingerprint_completed_accepted(self):
        self._write_lane_with_fp({"status": "completed", "findings": []})
        out = parse_quality_gates(self.root, self.SPEC, self.entry)
        assert self._item(out, "code-review")["status"] == "passed"

    def test_stale_fingerprint_treated_as_invisible(self):
        stale = dict(self.fp)
        stale["head_commit"] = "0" * 40
        self._write_lane_with_fp({"status": "completed", "findings": []}, fp=stale)
        out = parse_quality_gates(self.root, self.SPEC, self.entry)
        assert self._item(out, "code-review")["status"] == "pending"

    def test_missing_fingerprint_not_trusted_when_verifiable(self):
        self._write_lane({"status": "completed", "findings": []})
        out = parse_quality_gates(self.root, self.SPEC, self.entry)
        assert self._item(out, "code-review")["status"] == "pending"

    def test_nested_fingerprint_product_accepted(self):
        # add-timeline-ocr-lane-visibility 修复轮：真实车道产物（run_impl_ocr
        # 写侧）指纹嵌套在 fingerprint 子对象——须与顶层平铺形态同样采信
        self._write_lane({
            "status": "completed",
            "findings": [],
            "fingerprint": {"branch": self.fp["branch"],
                            "merge_base": self.fp["merge_base"],
                            "head_commit": self.fp["head_commit"]},
        })
        out = parse_quality_gates(self.root, self.SPEC, self.entry)
        assert self._item(out, "code-review")["status"] == "passed"

    def test_nested_fingerprint_stale_not_trusted(self):
        self._write_lane({
            "status": "completed",
            "findings": [],
            "fingerprint": {"branch": self.fp["branch"],
                            "merge_base": self.fp["merge_base"],
                            "head_commit": "0" * 40},
        })
        out = parse_quality_gates(self.root, self.SPEC, self.entry)
        assert self._item(out, "code-review")["status"] == "pending"

    def test_mergeback_fingerprint_completed_accepted(self):
        # fix-quality-gates-terminal-blindspot 1.2①：merge-back 后
        # merge-base 构造性前移到分支尖（merge_base == head_commit），产物
        # 记录的评审基线是 merge-back 前的 merge-base——结构性必现失配，
        # 豁免后 completed 产物照常采信
        self._git("checkout", "-q", "main")
        self._git("merge", "-q", "--ff-only", "fenix/demo")
        from core.dashboard.data import current_lane_fingerprint
        fp2 = current_lane_fingerprint(self.root, self.entry)
        assert fp2["merge_base"] == fp2["head_commit"]  # 分支已完整合入
        self._write_lane({
            "status": "completed",
            "findings": [{"id": "f1"}],
            "fingerprint": {"branch": self.fp["branch"],
                            "merge_base": self.fp["merge_base"],  # 评审时基线
                            "head_commit": self.fp["head_commit"]},
        })
        out = parse_quality_gates(self.root, self.SPEC, self.entry)
        assert self._item(out, "code-review")["status"] == "passed"

    def test_mergeback_head_moved_not_trusted(self):
        # 1.2②：豁免仅跳过 merge_base 比对——head 前移（修复轮重审）照旧拒采信
        self._git("checkout", "-q", "main")
        self._git("merge", "-q", "--ff-only", "fenix/demo")
        self._write_lane({
            "status": "completed",
            "findings": [],
            "fingerprint": {"branch": self.fp["branch"],
                            "merge_base": self.fp["merge_base"],
                            "head_commit": "0" * 40},
        })
        out = parse_quality_gates(self.root, self.SPEC, self.entry)
        assert self._item(out, "code-review")["status"] == "pending"

    def test_unmerged_merge_base_mismatch_not_trusted(self):
        # 1.2③：分支未合入（当前 merge_base ≠ head_commit）时 merge_base
        # 失配仍按不可见——既有 stale 拒采信语义不变
        self._write_lane({
            "status": "completed",
            "findings": [],
            "fingerprint": {"branch": self.fp["branch"],
                            "merge_base": "1" * 40,
                            "head_commit": self.fp["head_commit"]},
        })
        out = parse_quality_gates(self.root, self.SPEC, self.entry)
        assert self._item(out, "code-review")["status"] == "pending"


class TestOcrLaneInflight(QualityGatesTestBase):
    """add-timeline-ocr-lane-visibility 任务 1.3：ocr 门在飞检测补全。

    契约源 quality-gates-progress「车道在飞或产物 running 为 running」——
    车道仅在 run_impl_ocr 收尾一次性 tmp+replace 落盘 code-review.json
    （status 白名单 completed|unavailable），在飞窗口磁盘无 running 产物，
    读侧须以活跃 impl-ocr run（无终态事件）判在飞，且优先于磁盘产物状态。
    """

    @staticmethod
    def _run(run_id: str, status: str) -> dict:
        return {"run_id": run_id, "status": status, "agent_type": "impl-ocr"}

    def test_inflight_impl_ocr_run_is_running(self):
        out = parse_quality_gates(
            self.root, self.SPEC, {"status": "testing"},
            runs=[self._run("impl-ocr-demo-1770000000", "running")],
        )
        item = self._item(out, "code-review")
        assert item["status"] == "running"
        assert "进行中" in item["detail"]

    def test_inflight_empty_status_counts(self):
        # 无终态事件的另一读侧形态（空产物文件）同样在飞
        out = parse_quality_gates(
            self.root, self.SPEC, {"status": "testing"},
            runs=[self._run("impl-ocr-demo-1770000001", "empty")],
        )
        assert self._item(out, "code-review")["status"] == "running"

    def test_inflight_overrides_completed_product(self):
        # 在飞判据优先于磁盘产物：重审轮 head 前移后上一轮产物指纹陈旧不可采信
        self._write_lane({"status": "completed", "findings": []})
        out = parse_quality_gates(
            self.root, self.SPEC, {"status": "testing"},
            runs=[self._run("impl-ocr-demo-1770000002", "running")],
        )
        assert self._item(out, "code-review")["status"] == "running"

    def test_stale_run_not_inflight_falls_back_to_product(self):
        # mtime 兜底 stale（断尾弃置）非真实在飞：落回产物状态
        self._write_lane({"status": "completed", "findings": []})
        out = parse_quality_gates(
            self.root, self.SPEC, {"status": "testing"},
            runs=[self._run("impl-ocr-demo-1770000003", "stale")],
        )
        assert self._item(out, "code-review")["status"] == "passed"

    def test_non_ocr_running_run_not_inflight(self):
        # 非 impl-ocr 前缀（实现者/验证者等 run）不触发在飞
        out = parse_quality_gates(
            self.root, self.SPEC, {"status": "testing"},
            runs=[self._run("impl-demo-1770000004", "running")],
        )
        assert self._item(out, "code-review")["status"] == "pending"

    def test_terminal_ocr_run_not_inflight(self):
        # 已终态（done/error/...）的 impl-ocr run 非在飞 → 落回产物状态（缺失 pending）
        out = parse_quality_gates(
            self.root, self.SPEC, {"status": "testing"},
            runs=[self._run("impl-ocr-demo-1770000005", "done")],
        )
        assert self._item(out, "code-review")["status"] == "pending"

    def test_runs_none_keeps_original_tri_state(self):
        # runs 缺省（None，不判在飞）：completed/unavailable/缺失 → 原三态不回归
        self._write_lane({"status": "completed", "findings": []})
        out = parse_quality_gates(self.root, self.SPEC, {"status": "testing"})
        assert self._item(out, "code-review")["status"] == "passed"


class TestOcrDisabledBySetting(QualityGatesTestBase):
    """车道总开关关闭（verify.impl_code_review）→ code-review 门合成 skipped。

    fix-quality-gates-ocr-disabled-na：设置关闭后车道不再启动、code-review.json
    永不产生，此前合成 pending 落兜底文案「该门未了结（run 在飞或自查结果未
    落盘）」——归因错误（是设置关闭而非未了结）。关闭时合成 skipped（计入
    done，与 unavailable 同口径），detail 固定归因设置；开关优先级最高，先于
    在飞判据与磁盘产物（关闭后存量产物不再代表当前口径）。
    """

    _switch = "core.config.ConfigLoader.get_impl_code_review_enabled"

    def test_gate_skipped_with_setting_attribution(self):
        p = patch(self._switch, return_value=False)
        p.start()
        try:
            out = parse_quality_gates(self.root, self.SPEC, {"status": "testing"})
        finally:
            p.stop()
        item = self._item(out, "code-review")
        assert item["status"] == "skipped"
        # detail 归因设置（含键路径，UI 灰色辅助文案透传）
        assert "设置" in item["detail"]
        assert "verify.impl_code_review" in item["detail"]
        # skipped 计入 done（设置性不适用=已了结口径）；testing 态框架守卫
        # 2 项 passed 同 unavailable 用例口径 → done == 3
        assert out["done"] == 3
        # 兜底文案不再出现（归因不再误导）
        assert item["detail"] != "该门未了结（run 在飞或自查结果未落盘）"

    def test_disabled_overrides_inflight_and_product(self):
        # 开关最优先：在飞 impl-ocr run 与历史 completed 产物在场仍 skipped
        self._write_lane({"status": "completed", "findings": [{"path": "a.py"}]})
        p = patch(self._switch, return_value=False)
        p.start()
        try:
            out = parse_quality_gates(
                self.root, self.SPEC, {"status": "testing"},
                runs=[{"run_id": "impl-ocr-demo-1770000000",
                       "status": "running", "agent_type": "impl-ocr"}],
            )
        finally:
            p.stop()
        assert self._item(out, "code-review")["status"] == "skipped"

    def test_explicit_false_via_project_config(self):
        # 真实读配置路径：项目级 config.yaml 显式 false（不 patch 读侧）→ skipped
        self._use_real_config_reader()
        (self.root / ".fenix" / "config.yaml").write_text(
            "verify:\n  impl_code_review: false\n", encoding="utf-8")
        out = parse_quality_gates(self.root, self.SPEC, {"status": "testing"})
        assert self._item(out, "code-review")["status"] == "skipped"

    def test_enabled_true_via_project_config_keeps_tri_state(self):
        # 正向接线：项目级显式 true（真实读配置）+ completed 产物 → 既有三态
        self._use_real_config_reader()
        (self.root / ".fenix" / "config.yaml").write_text(
            "verify:\n  impl_code_review: true\n", encoding="utf-8")
        self._write_lane({"status": "completed", "findings": []})
        out = parse_quality_gates(self.root, self.SPEC, {"status": "testing"})
        assert self._item(out, "code-review")["status"] == "passed"


class TestFullSuiteTerminalExempt(QualityGatesTestBase):
    """fix-quality-gates-terminal-blindspot 2.2：full-suite 门终态豁免。

    终态（verified/done/pushed）后 main 持续前进，框架回归产物指纹必然
    陈旧不可见，且实现者默认不写 full-suite 自查键——终态 SPEC 该门恒
    pending 语义错误；豁免短路置于数据源优先级最前（确定性显示语义）。
    """

    def _git(self, *args) -> str:
        out = subprocess.run(["git", "-C", str(self.root), *args],
                             capture_output=True, text=True)
        assert out.returncode == 0, out.stderr
        return out.stdout.strip()

    def setup_method(self):
        super().setup_method()
        subprocess.run(["git", "init", "-b", "main", str(self.root)],
                       capture_output=True, check=True)
        self._git("config", "user.email", "t@t")
        self._git("config", "user.name", "t")
        (self.root / "base.txt").write_text("base", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-qm", "init")
        # run 自查文件可读但无 full-suite 键（add-impl-selfcheck-model-probe
        # 3.1 后实现者默认不写）——非终态时该门既有回落语义 = pending
        self._write_gates({"frontend-build": {"status": "skipped",
                                              "reason": "无前端改动"}})

    def _stale_snapshot(self) -> None:
        from core.regression import write_result
        write_result(self.root, {"status": "failed", "passed": 90, "failed": 10})
        (self.root / "g.txt").write_text("y", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-qm", "second")  # HEAD 前移 → 快照指纹陈旧

    def test_pushed_stale_product_no_selfcheck_skipped_counts_done(self):
        # 2.2①：pushed + 产物指纹陈旧 + 自查键缺 → skipped 固定文案、计入 done
        self._stale_snapshot()
        out = parse_quality_gates(self.root, self.SPEC,
                                  {"status": "pushed"}, runs=[])
        item = self._item(out, "full-suite")
        assert item["status"] == "skipped"
        assert item["detail"] == "SPEC 已终态，全量回归跟踪移交主树"
        # done 含 skipped 的 full-suite：2 框架守卫 passed + 2 skipped
        assert out["done"] == 4

    def test_pushed_fresh_failed_product_still_skipped(self):
        # 2.2②：产物指纹恰好匹配（且产物 failed）→ 仍 skipped（豁免优先于产物）
        from core.regression import write_result
        write_result(self.root, {"status": "failed", "passed": 1, "failed": 1})
        out = parse_quality_gates(self.root, self.SPEC,
                                  {"status": "pushed"}, runs=[])
        item = self._item(out, "full-suite")
        assert item["status"] == "skipped"
        assert item["detail"] == "SPEC 已终态，全量回归跟踪移交主树"

    def test_testing_same_stale_conditions_pending(self):
        # 2.2③：testing 非终态同等陈旧条件 → pending（既有回落行为不变）
        self._stale_snapshot()
        out = parse_quality_gates(self.root, self.SPEC,
                                  {"status": "testing"}, runs=[])
        assert self._item(out, "full-suite")["status"] == "pending"


class TestFullSuiteSubsetSnapshotInvisible(QualityGatesTestBase):
    """add-regression-issues-rerun 4.1：full-suite 门对子集快照（run_scope=="issues"）
    判本源不可见——子集通过 MUST NOT 使本门呈现 passed（防白洗通道，D6）。
    """

    def _git(self, *args) -> str:
        out = subprocess.run(["git", "-C", str(self.root), *args],
                             capture_output=True, text=True)
        assert out.returncode == 0, out.stderr
        return out.stdout.strip()

    def setup_method(self):
        super().setup_method()
        subprocess.run(["git", "init", "-b", "main", str(self.root)],
                       capture_output=True, check=True)
        self._git("config", "user.email", "t@t")
        self._git("config", "user.name", "t")
        (self.root / "base.txt").write_text("base", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-qm", "init")
        # run 自查文件可读但无 full-suite 键（add-impl-selfcheck-model-probe 3.1
        # 后实现者默认不写）——子集产物不可见时该门既有回落语义 = pending
        self._write_gates({"frontend-build": {"status": "skipped",
                                              "reason": "无前端改动"}})

    def _write_subset_snapshot(self, status="passed", passed=3, failed=0):
        from core.regression import write_result

        write_result(self.root, {
            "status": status, "total": 3, "passed": passed, "failed": failed,
            "errors": 0, "skipped": 0, "failures": [], "long_tests": [],
            "run_scope": "issues",
        })

    def test_subset_passed_snapshot_not_trusted_falls_back_pending(self):
        # 子集快照（issues + passed + 指纹匹配）+ 自查无 full-suite 键 →
        # 不呈现 passed，数据源③回落 pending；解析不抛异常
        self._write_subset_snapshot()
        out = parse_quality_gates(self.root, self.SPEC, {"status": "testing"}, runs=[])
        item = self._item(out, "full-suite")
        assert item["status"] == "pending"
        assert "passed" not in (item["detail"] or "")

    def test_subset_snapshot_falls_back_to_selfcheck_value(self):
        # 子集产物不可见 → 沿用既有 fail-open 逐级回落：采纳 run 自查值
        self._write_subset_snapshot()
        self._write_gates({
            "frontend-build": {"status": "skipped", "reason": "无前端改动"},
            "full-suite": {"status": "passed", "passed": 128, "failed": 0},
        })
        out = parse_quality_gates(self.root, self.SPEC, {"status": "testing"}, runs=[])
        assert self._item(out, "full-suite")["status"] == "passed"

    def test_full_snapshot_without_run_scope_unchanged(self):
        # 全量快照（无 run_scope 键）+ 指纹匹配 → 既有规则正常采信，行为零变化
        from core.regression import write_result

        write_result(self.root, {
            "status": "passed", "total": 5045, "passed": 5045, "failed": 0,
            "errors": 0, "skipped": 0, "failures": [], "long_tests": [],
        })
        out = parse_quality_gates(self.root, self.SPEC, {"status": "testing"}, runs=[])
        item = self._item(out, "full-suite")
        assert item["status"] == "passed"
        assert "5045" in item["detail"]

    def test_subset_failed_snapshot_not_trusted_either(self):
        # 子集快照无论什么状态都不采信（判定置于 status 白名单之前）：
        # failed 子集同样不可见回落，不让子集结论进 full-suite 门
        self._write_subset_snapshot(status="failed", passed=1, failed=2)
        out = parse_quality_gates(self.root, self.SPEC, {"status": "testing"}, runs=[])
        assert self._item(out, "full-suite")["status"] == "pending"

    def test_non_dict_payload_snapshot_invisible_no_exception(self):
        # read_result 对合法 JSON 非 dict 载荷归一为 parse_error（item
        # 222752de454d）——isinstance 守卫保持作纵深防御，非 dict 一并按
        # 不可见 (None, "") 处理，.get 直取会 AttributeError 穿透 fail-open
        # 契约
        d = self.root / ".fenix" / "regression"
        d.mkdir(parents=True, exist_ok=True)
        (d / "last-run.json").write_text('["not", "a", "dict"]', encoding="utf-8")
        out = parse_quality_gates(self.root, self.SPEC, {"status": "testing"}, runs=[])
        assert self._item(out, "full-suite")["status"] == "pending"


class TestWorktreePriority(QualityGatesTestBase):
    """1.4 worktree 优先读取策略。"""

    def _mk_worktree(self) -> Path:
        wt = self.root / ".claude" / "worktrees" / f"impl-{self.SPEC}-1"
        wt.mkdir(parents=True, exist_ok=True)
        return wt

    def test_worktree_version_wins_over_main(self):
        wt = self._mk_worktree()
        self._write_gates({"full-suite": {"status": "passed", "passed": 5, "failed": 0}},
                          proot=wt)
        # 主树是另一份（旧轮拷回）数据：full-suite failed
        self._write_gates({"full-suite": {"status": "failed", "reason": "3 failed"}})
        out = parse_quality_gates(self.root, self.SPEC, {"status": "implementing"})
        assert self._item(out, "full-suite")["status"] == "passed"

    def test_worktree_only_visible_when_main_missing(self):
        wt = self._mk_worktree()
        self._write_gates({"full-suite": {"status": "passed", "passed": 5, "failed": 0}},
                          proot=wt)
        out = parse_quality_gates(self.root, self.SPEC, {"status": "implementing"})
        assert out["exists"] is True
        assert self._item(out, "full-suite")["status"] == "passed"

    def test_no_worktree_reads_main(self):
        self._write_gates({"full-suite": {"status": "failed", "reason": "1 failed"}})
        out = parse_quality_gates(self.root, self.SPEC, {"status": "implementing"})
        assert out["exists"] is True
        assert self._item(out, "full-suite")["status"] == "failed"

    def test_worktree_without_file_falls_back_to_main(self):
        # fast-track 等车道直落主树形态：worktree 在但无文件，主树有
        self._mk_worktree()
        self._write_gates({"full-suite": {"status": "passed", "passed": 5, "failed": 0}})
        out = parse_quality_gates(self.root, self.SPEC, {"status": "implementing"})
        assert self._item(out, "full-suite")["status"] == "passed"

    def test_non_implementing_reads_main_even_with_worktree(self):
        wt = self._mk_worktree()
        self._write_gates({"full-suite": {"status": "passed", "passed": 5, "failed": 0}},
                          proot=wt)
        self._write_gates({"full-suite": {"status": "failed", "reason": "1 failed"}})
        out = parse_quality_gates(self.root, self.SPEC, {"status": "testing"})
        assert self._item(out, "full-suite")["status"] == "failed"

    def test_code_review_lane_product_worktree_priority(self):
        wt = self._mk_worktree()
        self._write_lane({"status": "running"}, proot=wt)
        self._write_lane({"status": "completed", "findings": []})
        out = parse_quality_gates(self.root, self.SPEC, {"status": "implementing"})
        assert self._item(out, "code-review")["status"] == "running"


class TestCurrentText(QualityGatesTestBase):
    """current 进展文案。"""

    def test_running_item_surfaces_current(self):
        self._write_gates({"full-suite": {"status": "running"}})
        out = parse_quality_gates(self.root, self.SPEC, {"status": "implementing"})
        assert "全量回归测试" in out["current"]
        assert "进行中" in out["current"]

    def test_lane_running_surfaces_current(self):
        self._write_lane({"status": "running"})
        out = parse_quality_gates(self.root, self.SPEC, {"status": "testing"})
        assert "ocr 代码审查与处置" in out["current"]

    def test_failed_item_surfaces_current_when_nothing_running(self):
        self._write_gates({"full-suite": {"status": "failed", "reason": "2 failed"}})
        out = parse_quality_gates(self.root, self.SPEC, {"status": "implementing"})
        assert "全量回归测试" in out["current"]

    def test_no_progress_empty_current(self):
        out = parse_quality_gates(self.root, self.SPEC, {"status": "drafted"})
        assert out["current"] == ""


# ── 写侧（任务 3.3）：prompt 注入契约断言 + result_gate 宽松对账 ──────────


def _mk_prompt(tmp_path: Path, agent_type: str) -> str:
    from test_agent_runner import make_runner

    proot = tmp_path / "proj"
    d = proot / "spec" / "changes" / "demo"
    d.mkdir(parents=True, exist_ok=True)
    (d / "tasks.md").write_text("# Tasks\n\n- [ ] 1.1 do it\n", encoding="utf-8")
    runner = make_runner(proot)
    return runner._prompt_builder._build_prompt("demo", agent_type)


class TestQualityGatesPromptSection:
    """3.3：注入段含契约路径与键名字面断言。"""

    @pytest.mark.parametrize("agent_type", ["implementer", "fast-track"])
    def test_contract_path_literal(self, tmp_path, agent_type):
        prompt = _mk_prompt(tmp_path, agent_type)
        assert ".fenix/verify-progress/demo/quality-gates.json" in prompt

    @pytest.mark.parametrize("agent_type", ["implementer", "fast-track"])
    def test_schema_gate_ids_and_enum_literals(self, tmp_path, agent_type):
        prompt = _mk_prompt(tmp_path, agent_type)
        assert '"gates"' in prompt
        assert "updated_at" in prompt
        for gid in ("full-suite", "frontend-build", "interaction-contract"):
            assert gid in prompt, gid
        for st in ("passed", "failed", "running", "skipped"):
            assert st in prompt, st

    @pytest.mark.parametrize("agent_type", ["implementer", "fast-track"])
    def test_progressive_mkdir_and_forbidden_code_review_key(self, tmp_path, agent_type):
        prompt = _mk_prompt(tmp_path, agent_type)
        # 渐进更新要求
        assert "渐进" in prompt
        # 写前创建父目录（mkdir -p 语义）
        assert "mkdir" in prompt
        # 无 code-review 键义务声明（ocr 归框架侧异步车道）
        assert "MUST NOT" in prompt and "code-review" in prompt
        # 与内联 ocr 段无耦合：本段不含 code-review.json 字样
        assert "code-review.json" not in prompt

    def test_non_impl_lanes_not_injected(self, tmp_path):
        for agent_type in ("verifier", "planner-plan", "spec-review"):
            prompt = _mk_prompt(tmp_path, agent_type)
            assert "quality-gates.json" not in prompt, agent_type


class TestResultGateSoftCheck:
    """3.3：result_gate 对 quality-gates.json 宽松对账（缺失零拦截、违规仅 WARNING）。"""

    def _setup(self, tmp_path):
        from test_agent_runner import make_runner

        proot = tmp_path / "proj"
        proot.mkdir()
        wt = tmp_path / "wt"
        wt.mkdir()
        return make_runner(proot), proot, wt

    def _gates_path(self, base: Path) -> Path:
        return base / ".fenix" / "verify-progress" / "demo" / "quality-gates.json"

    def test_missing_file_zero_warning_zero_interception(self, tmp_path, caplog):
        runner, proot, wt = self._setup(tmp_path)
        with caplog.at_level("WARNING", logger="fenixd.agent_runner.result_gate"):
            out = result_gate._check_quality_gates_soft(runner, "demo", wt)
        assert out is None
        assert not [r for r in caplog.records if "quality-gates" in r.getMessage()]

    def test_bad_json_warning_only_and_run_verdict_unaffected(self, tmp_path, caplog):
        runner, proot, wt = self._setup(tmp_path)
        p = self._gates_path(wt)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{broken", encoding="utf-8")
        with caplog.at_level("WARNING", logger="fenixd.agent_runner.result_gate"):
            out = result_gate._check_quality_gates_soft(runner, "demo", wt)
        assert out is None  # run 判定不受影响（无失败终态）
        warnings = [r for r in caplog.records if "quality-gates" in r.getMessage()]
        assert warnings and all(r.levelno == logging.WARNING for r in warnings)

    def test_out_of_enum_status_warns(self, tmp_path, caplog):
        runner, proot, wt = self._setup(tmp_path)
        p = self._gates_path(wt)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(
            {"gates": {"full-suite": {"status": "ok"}}}, ensure_ascii=False),
            encoding="utf-8")
        with caplog.at_level("WARNING", logger="fenixd.agent_runner.result_gate"):
            result_gate._check_quality_gates_soft(runner, "demo", wt)
        assert any("不在枚举" in r.getMessage() for r in caplog.records)

    def test_out_of_contract_gate_id_warns(self, tmp_path, caplog):
        runner, proot, wt = self._setup(tmp_path)
        p = self._gates_path(wt)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(
            {"gates": {"code-review": {"status": "passed"}}}, ensure_ascii=False),
            encoding="utf-8")
        with caplog.at_level("WARNING", logger="fenixd.agent_runner.result_gate"):
            result_gate._check_quality_gates_soft(runner, "demo", wt)
        assert any("契约外 gate-id" in r.getMessage() for r in caplog.records)

    def test_valid_file_no_warning(self, tmp_path, caplog):
        runner, proot, wt = self._setup(tmp_path)
        p = self._gates_path(wt)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(
            {"gates": {"full-suite": {"status": "passed", "passed": 1, "failed": 0}},
             "updated_at": "2026-09-22T00:00:00Z"}, ensure_ascii=False),
            encoding="utf-8")
        with caplog.at_level("WARNING", logger="fenixd.agent_runner.result_gate"):
            result_gate._check_quality_gates_soft(runner, "demo", wt)
        assert not [r for r in caplog.records if "quality-gates" in r.getMessage()]

    def test_soft_check_called_in_impl_chain_never_blocks(self, tmp_path, caplog):
        """impl 产物硬门链路接入点：软检查被链路调用且不改变判定（缺失零拦截）。"""
        from test_agent_runner import make_runner

        proot = tmp_path / "proj"
        wt = proot / "wt"
        (wt / "spec" / "changes" / "demo").mkdir(parents=True)
        (wt / "spec" / "changes" / "demo" / "tasks.md").write_text(
            "## 1. 阶段一\n\n- [x] 1.1 任务一\n", encoding="utf-8")
        (wt / ".fenix-run-result.json").write_text(json.dumps(
            {"status": "success", "spec": "demo", "completed_tasks": ["1.1"]},
            ensure_ascii=False),
            encoding="utf-8")
        runner = make_runner(proot)
        calls = []
        orig = runner._check_quality_gates_soft

        def _spy(spec, wt_path):
            calls.append((spec, wt_path))
            return orig(spec, wt_path)

        runner._check_quality_gates_soft = _spy
        with caplog.at_level("WARNING", logger="fenixd.agent_runner.result_gate"):
            err = runner._check_impl_result_artifact("demo", None, wt)
        assert err is None  # 链路放行
        assert calls and calls[0][0] == "demo"  # 软检查确实在链路中被调用
        # 文件缺失 → 零 WARNING 零拦截
        assert not [r for r in caplog.records if "quality-gates" in r.getMessage()]
