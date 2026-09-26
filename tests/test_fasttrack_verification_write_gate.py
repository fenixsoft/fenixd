"""fast-track 结果文件 verification 段写后硬门测试（add-fasttrack-verification-write-gate）。

覆盖 tasks：
- 1.1 run 末硬门：fast-track 的 success 结果缺 verification 段/结构不完整 →
  拦截；补写合规段 → 放行；partial/error（诚实退出）不误拦；full 车道
  （mode 非 fast-track / 缺 mode）不触发。
- 1.2 契约段同频：fast-track 车道注入文本含 verification 契约句；
  implementer（full 车道共用块）注入文本不含——两层契约口径一致，
  full 车道不被注入 fast-track 专属义务。
"""

import json
import sys
import tempfile
import shutil
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent_runner.prompt_builder import PromptBuilder
from test_agent_runner import make_runner

ALL_DONE_TASKS = "## 1. 阶段一\n\n- [x] 1.1 任务一\n- [x] 1.2 任务二\n"
PARTIAL_TASKS = "## 1. 阶段一\n\n- [x] 1.1 任务一\n- [ ] 1.2 任务二\n"

# 合法 verification 段（schema 单源 core/fast_track_result.py）
GOOD_VERIFICATION = {
    "scenarios": [
        {"scenario_id": "s1", "description": "场景一", "status": "pass"},
        {"scenario_id": "s2", "description": "场景二", "status": "fail",
         "evidence": "……", "category": "product-bug"},
    ],
    "verdict": "bug-found",
    "bugs": [{"id": "b1", "summary": "……"}],
}


def _mk_worktree(proot: Path, spec: str, *, tasks_text: str) -> Path:
    wt = proot / "wt"
    (wt / "spec" / "changes" / spec).mkdir(parents=True, exist_ok=True)
    (wt / "spec" / "changes" / spec / "tasks.md").write_text(
        tasks_text, encoding="utf-8")
    return wt


def _write_result(wt: Path, payload: dict) -> None:
    (wt / ".fenix-run-result.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class TestFastTrackVerificationWriteGate:
    """任务 1.1：_check_impl_result_artifact 的 fast-track verification 段分支。"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)
        self.runner = make_runner(self.proot)
        self.spec = "demo"

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _gate(self, payload: dict, *, tasks_text: str = ALL_DONE_TASKS,
              spec: str | None = None):
        wt = _mk_worktree(self.proot, spec or self.spec, tasks_text=tasks_text)
        _write_result(wt, payload)
        return self.runner._check_impl_result_artifact(
            spec or self.spec, None, wt)

    # ── 缺段拦截 ─────────────────────────────────────────────

    def test_fasttrack_success_missing_verification_blocked(self):
        """fast-track success 缺 verification 段 → 硬门拦截。"""
        err = self._gate({"status": "success", "spec": self.spec,
                          "mode": "fast-track",
                          "completed_tasks": ["1.1", "1.2"]})
        assert err is not None
        assert "verification 段缺失或结构不完整" in err

    def test_fasttrack_success_empty_scenarios_blocked(self):
        """scenarios 空数组 → 结构不完整 → 拦截。"""
        err = self._gate({"status": "success", "spec": self.spec,
                          "mode": "fast-track",
                          "completed_tasks": ["1.1", "1.2"],
                          "verification": {"scenarios": [],
                                           "verdict": "verified"}})
        assert err is not None
        assert "verification 段缺失或结构不完整" in err

    def test_fasttrack_success_bad_scenario_entry_blocked(self):
        """场景条目缺 description/status 非法 → 拦截。"""
        err = self._gate({"status": "success", "spec": self.spec,
                          "mode": "fast-track",
                          "completed_tasks": ["1.1", "1.2"],
                          "verification": {
                              "scenarios": [{"scenario_id": "s1"}],
                              "verdict": "verified"}})
        assert err is not None
        assert "verification 段缺失或结构不完整" in err

    def test_fasttrack_success_bad_verdict_blocked(self):
        """verdict 非枚举值 → 拦截。"""
        verification = json.loads(json.dumps(GOOD_VERIFICATION))
        verification["verdict"] = "looks-good"
        err = self._gate({"status": "success", "spec": self.spec,
                          "mode": "fast-track",
                          "completed_tasks": ["1.1", "1.2"],
                          "verification": verification})
        assert err is not None
        assert "verification 段缺失或结构不完整" in err

    # ── 补写放行 ─────────────────────────────────────────────

    def test_fasttrack_success_compliant_verification_passes(self):
        """补写合规 verification 段（含 bug-found 带非 pass 场景）→ 放行。"""
        err = self._gate({"status": "success", "spec": self.spec,
                          "mode": "fast-track",
                          "completed_tasks": ["1.1", "1.2"],
                          "verification": GOOD_VERIFICATION})
        assert err is None

    def test_fasttrack_success_verified_passes(self):
        """verdict=verified 全 pass 场景 → 放行。"""
        err = self._gate({"status": "success", "spec": self.spec,
                          "mode": "fast-track",
                          "completed_tasks": ["1.1", "1.2"],
                          "verification": {
                              "scenarios": [
                                  {"scenario_id": "s1",
                                   "description": "场景一", "status": "pass"},
                              ],
                              "verdict": "verified"}})
        assert err is None

    # ── partial / error 诚实退出不误拦 ────────────────────────

    def test_fasttrack_partial_without_verification_passes(self):
        """partial（诚实退出，本就不含 verification 段）→ 不误拦。"""
        err = self._gate({"status": "partial", "spec": self.spec,
                          "mode": "fast-track",
                          "completed_tasks": ["1.1"], "unfinished": ["1.2"]},
                         tasks_text=PARTIAL_TASKS)
        assert err is None

    def test_fasttrack_error_without_verification_passes(self):
        """error（诚实退出）→ 不误拦。"""
        err = self._gate({"status": "error", "spec": self.spec,
                          "mode": "fast-track", "error": "预算耗尽"})
        assert err is None

    # ── full 车道不触发 ──────────────────────────────────────

    def test_full_lane_success_without_mode_not_blocked(self):
        """full 车道（缺 mode 字段）success 无 verification 段 → 不触发。"""
        err = self._gate({"status": "success", "spec": self.spec,
                          "completed_tasks": ["1.1", "1.2"]})
        assert err is None

    def test_full_lane_success_other_mode_not_blocked(self):
        """mode 非 fast-track → 不触发。"""
        err = self._gate({"status": "success", "spec": self.spec,
                          "mode": "full",
                          "completed_tasks": ["1.1", "1.2"]})
        assert err is None


class TestVerificationContractSection:
    """任务 1.2：契约段同频——fast-track 注入契约句、implementer（full）不含。"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.pb = PromptBuilder(SimpleNamespace(project_root=Path(self.tmpdir)))
        self.spec = "demo"

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _section(self, agent_type: str) -> str:
        return self.pb._result_gate_section(
            self.spec, agent_type, wt_path=None)

    def test_fasttrack_prompt_contains_verification_contract(self):
        text = self._section("fast-track")
        assert "fast-track 车道专属" in text
        assert "verification 段" in text
        assert "verdict 属 verified/bug-found" in text

    def test_implementer_prompt_lacks_verification_contract(self):
        """full 车道共用块不注入 fast-track 专属义务。"""
        text = self._section("implementer")
        assert "fast-track 车道专属" not in text
        assert "verification" not in text
        # 共用基线段仍然在场（未被分支改坏）
        assert "结果文件硬门" in text
        assert ".fenix-run-result.json" in text
