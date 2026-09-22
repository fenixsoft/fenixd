"""add-quality-gates-visibility 1.x：质量门禁读侧解析与合成用例。

覆盖 specs/quality-gates-progress/spec.md 的读侧契约：
- 合法 quality-gates.json 解析（items 恒 6 道且顺序符合契约、done=passed+skipped、
  未写入条目 pending）；
- 容错（文件缺失/JSON 损坏/枚举外 status/契约外 gate-id → unknown/忽略，不抛异常
  无 error 字段）；
- 框架 3 项合成（result-artifact-gate 按 run 终态、deliverable-guard 按 STATE、
  code-review 按 ocr 车道产物三态 + 指纹校验）；
- worktree 优先读取策略（implementing 时 worktree 内文件优先、主树兜底）。
"""

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

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
