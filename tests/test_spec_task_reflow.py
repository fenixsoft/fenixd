"""task-gap 滞留 SPEC 的人工回炉测试（fix-impl-tasks-completion-gate P1′/D8）。

覆盖 spec「task-gap 滞留 SPEC 的回炉动作」全部 Scenario：
- 合规形态复位为 ready（ok:true、status=ready、error 清空）；
- spec 不存在 → found:false；
- 非 verified 状态被拒绝（明确原因）；
- error 非 task-gap 前缀被拒绝；
- 冻结态被拒绝；
- 幂等重复调用被拒绝（第二次当前状态 ready，不在可回炉形态）；
- 不触碰预算计数与冻结计数器（frozen/frozen_until/start_after 不变）；
- PROJECT_LOG 留痕（SPEC 名、原状态、缺口任务清单、动作来源）。
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.pm_engine.task_reflow import reflow_spec
from core.state_machine import StateMachine
from test_agent_runner import FakeLogger


def _write_state(proot: Path, body: str) -> None:
    (proot / ".fenix").mkdir(parents=True, exist_ok=True)
    (proot / ".fenix" / "STATE.md").write_text(body, encoding="utf-8")


def _state_body(spec_name="myspec", status="verified", error="task-gap:未完成任务：4.5、5.1",
                frozen=False, extra: str = "") -> str:
    frozen_line = "- frozen: true\n" if frozen else ""
    return (
        "# Fenix Project State\n\n## Specs\n\n"
        f"### {spec_name}\n- status: {status}\n- priority: 5\n"
        f"- error: {error}\n- depends_on: null\n"
        f"- _impl_run_budget_used: 3\n"
        f"{frozen_line}"
        f"- frozen_until: null\n- start_after: null\n"
        f"{extra}"
    )


class TestSpecTaskReflow(unittest.TestCase):
    """回炉动作：判定与执行单一实现点（API/CLI 共用同一函数）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)
        self.logger = FakeLogger()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _sm(self) -> StateMachine:
        return StateMachine(self.proot / ".fenix" / "STATE.md", None)

    def _reflow(self, spec="myspec", source="api") -> dict:
        return reflow_spec(self.proot, spec, state_machine=self._sm(),
                           logger=self.logger, source=source)

    def test_compliant_reset_to_ready(self):
        """合规形态（verified + task-gap 前缀 + 未冻结）→ ok:true、status=ready。"""
        _write_state(self.proot, _state_body())
        result = self._reflow()
        assert result["ok"] is True
        assert result["status"] == "ready"
        entry = self._sm().read_one("myspec")
        assert entry["status"] == "ready"
        assert entry["error"] in (None, "")

    def test_missing_spec_found_false(self):
        """spec 不存在 → found:false（不产生状态写入）。"""
        _write_state(self.proot, _state_body())
        result = self._reflow("ghost")
        assert result["ok"] is False
        assert result["found"] is False
        assert "not found" in result["reason"]

    def test_non_verified_rejected(self):
        """非 verified 状态（ready/implementing/testing/blocked/done）→ 拒绝。"""
        for status in ("ready", "implementing", "testing", "blocked", "done", "pushed"):
            _write_state(self.proot, _state_body(status=status))
            result = self._reflow()
            assert result["ok"] is False, status
            assert "当前状态为" in result["reason"], status
            # 不产生状态写入
            assert self._sm().read_one("myspec")["status"] == status

    def test_error_not_task_gap_rejected(self):
        """verified 但 error 非 task-gap 前缀（空/其它前缀）→ 拒绝。"""
        for error in ("", "spec-review-rejected: x", "冻结：人工"):
            _write_state(self.proot, _state_body(error=error))
            result = self._reflow()
            assert result["ok"] is False, error
            assert "task-gap" in result["reason"], error

    def test_frozen_rejected(self):
        """冻结态 → 拒绝（须先解冻）。"""
        _write_state(self.proot, _state_body(frozen=True))
        result = self._reflow()
        assert result["ok"] is False
        assert "冻结" in result["reason"]

    def test_idempotent_second_call_rejected(self):
        """幂等重复调用：第二次（已复位 ready）→ 拒绝且不产生第二次写入。"""
        _write_state(self.proot, _state_body())
        first = self._reflow()
        assert first["ok"] is True
        log_before = (self.proot / ".fenix" / "PROJECT_LOG.md").read_text(
            encoding="utf-8") if (self.proot / ".fenix" / "PROJECT_LOG.md").exists() else ""
        second = self._reflow()
        assert second["ok"] is False
        assert "当前状态为 'ready'" in second["reason"]
        # 无重复日志
        log_after = (self.proot / ".fenix" / "PROJECT_LOG.md").read_text(
            encoding="utf-8") if (self.proot / ".fenix" / "PROJECT_LOG.md").exists() else ""
        assert log_after == log_before

    def test_budget_and_freeze_counters_untouched(self):
        """回炉不触碰 _impl_run_budget_used / frozen / frozen_until / start_after。"""
        extra = "- _zero_change_attempts: 2\n"
        _write_state(self.proot, _state_body(extra=extra))
        result = self._reflow()
        assert result["ok"] is True
        entry = self._sm().read_one("myspec")
        assert int(entry["_impl_run_budget_used"]) == 3
        assert entry.get("frozen") in (None, False)
        assert entry.get("frozen_until") in (None, "null")
        assert entry.get("start_after") in (None, "null")
        assert entry.get("_zero_change_attempts") == "2" or int(entry.get("_zero_change_attempts") or 0) == 2

    def test_project_log_appended_with_traceability(self):
        """PROJECT_LOG 留痕：SPEC 名、原状态、缺口任务清单、动作来源。"""
        _write_state(self.proot, _state_body())
        self._reflow(source="cli")
        log = (self.proot / ".fenix" / "PROJECT_LOG.md").read_text(encoding="utf-8")
        assert "回炉" in log
        assert "myspec" in log
        assert "verified→ready" in log
        assert "4.5" in log and "5.1" in log
        assert "来源=cli" in log

    def test_api_and_cli_share_single_entrypoint(self):
        """API 与 CLI 共用 reflow_spec 单一实现点（source 参数区分留痕来源）。"""
        _write_state(self.proot, _state_body())
        assert self._reflow(source="api")["ok"] is True
        _write_state(self.proot, _state_body())
        assert self._reflow(source="cli")["ok"] is True


if __name__ == "__main__":
    unittest.main()