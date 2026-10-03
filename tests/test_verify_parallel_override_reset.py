"""Tests for evo-fix-verify-parallel-override-type：_verify_parallel_override 类型契约归位。

覆盖 tasks.md 3.1：
- 人工裁决（reset_verification / continue_auto_fix）后字段为 null，
  STATE.md 往返读回 null（1.1 写侧归位的端到端验证）
- 非法形状（布尔 / 字符串）写入被写侧守卫拒绝并告警留痕，
  不静默序列化进 STATE.md（2.1a）
- parse 侧 int|None 归一：存量 STATE.md 'False' 坏写首读清洗为 null、
  int 往返读回 int（2.1b）
- 读端解析失败告警含 repr 形态与字段来源（2.2，不退化）

既有 tests/test_verify_parallel_backoff.py 零回退由全量回归保证（int() 包裹
断言对 str/int 双形态兼容）；parse 归一的可观察类型变化（"2"→2）已同步更新
tests/test_characterization_verification.py:177（3.2）。
"""
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import StateMachine

_OVERRIDE_FIELD = "_verify_parallel_override"


# ── 共享夹具（同 test_adjudication_choices 形态）─────────────────────────


def _write_state(proot: Path, specs: dict) -> None:
    """最小 STATE.md。"""
    lines = ["# Fenix Project State", "", "## Specs", ""]
    for name, fields in specs.items():
        lines.append(f"### {name}")
        for k, v in fields.items():
            lines.append(f"- {k}: {v}")
        lines.append("")
    (proot / ".fenix").mkdir(parents=True, exist_ok=True)
    (proot / ".fenix" / "STATE.md").write_text("\n".join(lines), encoding="utf-8")


_STATE_FIELDS = lambda status, error="null": {
    "status": status,
    "priority": 2,
    "created": "2026-01-01T00:00:00+00:00",
    "updated": "2026-01-02T00:00:00+00:00",
    "error": error,
    "depends_on": "null",
}


def _freeze(proot: Path, spec: str, error: str, **extra):
    """模拟冻结形态（blocked + frozen 标记 + 站点 error 文案）。"""
    sm = StateMachine(proot / ".fenix" / "STATE.md", _QuietLogger())
    updates = {"frozen": True, "status": "blocked", "error": error}
    updates.update(extra)
    sm.update_spec(spec, updates)


class _QuietLogger:
    """静默 logger。"""

    def warning(self, tag, msg, *a, **k):
        pass

    def info(self, tag, msg, *a, **k):
        pass

    def error(self, tag, msg, *a, **k):
        pass

    def debug(self, tag, msg, *a, **k):
        pass


def _read_entry(proot: Path, spec: str) -> dict:
    """生产读者口径的单条目读（StateMachine.read_one，含 parse 归一）。"""
    return StateMachine(proot / ".fenix" / "STATE.md", _QuietLogger()).read_one(spec) or {}


def _override_lines(proot: Path) -> list:
    """STATE.md 中该字段的落盘行（判 null 字面量 / 坏值字面量）。"""
    txt = (proot / ".fenix" / "STATE.md").read_text(encoding="utf-8")
    return [ln for ln in txt.splitlines() if ln.startswith(f"- {_OVERRIDE_FIELD}:")]


# ── 3.1a 人工裁决复位写 null 且 STATE.md 往返读回 null ───────────────────


class TestAdjudicationResetsOverrideToNull:
    def test_reset_verification_writes_null_override(self, tmp_path):
        """reset_verification 后字段为 null，STATE.md 落盘 null 字面量。"""
        proot = tmp_path / "proj-rst"
        _write_state(proot, {"spec-rst": _STATE_FIELDS("implementing")})
        _freeze(proot, "spec-rst", "judge_rerun_cap: judge 重跑达上限（原状态 testing）",
                _judge_rerun_count=3, _judge_cap_frozen=True,
                **{_OVERRIDE_FIELD: 2})
        from core.dashboard.data import reset_verification

        r = reset_verification(proot, "spec-rst", signal_type="judge_rerun_cap")
        assert r["ok"] is True, r
        entry = _read_entry(proot, "spec-rst")
        assert entry[_OVERRIDE_FIELD] is None, (
            "reset_verification 复位 MUST 写 null 而非 False（契约 int|None）")
        assert _override_lines(proot) == [f"- {_OVERRIDE_FIELD}: null"], _override_lines(proot)

    def test_continue_auto_fix_writes_null_override(self, tmp_path):
        """continue_auto_fix 后字段为 null，STATE.md 落盘 null 字面量。"""
        proot = tmp_path / "proj-caf"
        _write_state(proot, {"spec-caf": _STATE_FIELDS("implementing")})
        _freeze(proot, "spec-caf", "verify_fail_escalation: 验证失败升级（原状态 testing）",
                **{_OVERRIDE_FIELD: 1})
        from core.dashboard.data.admin_actions import _exec_continue_auto_fix

        r = _exec_continue_auto_fix(proot, "spec-caf")
        assert r["ok"] is True, r
        entry = _read_entry(proot, "spec-caf")
        assert entry[_OVERRIDE_FIELD] is None
        assert _override_lines(proot) == [f"- {_OVERRIDE_FIELD}: null"], _override_lines(proot)


# ── 3.1b 写侧守卫：非法形状拒绝并告警，不序列化进 STATE.md ────────────────


class _RecorderLogger:
    """记录消息的假 logger（守卫告警断言用）。"""

    def __init__(self):
        self.messages = []

    def _log(self, tag, msg):
        self.messages.append(f"[{tag}] {msg}")

    def debug(self, tag, msg, *a, **k):
        self._log(tag, msg)

    def info(self, tag, msg, *a, **k):
        self._log(tag, msg)

    def warning(self, tag, msg, *a, **k):
        self._log(tag, msg)

    def error(self, tag, msg, *a, **k):
        self._log(tag, msg)


class TestWriteSideShapeGuard(unittest.TestCase):
    """2.1a：布尔/字符串形状在 _apply_updates_entry 单字段守卫处拒绝。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.logger = _RecorderLogger()
        self.sm = StateMachine(
            Path(self.tmpdir) / ".fenix" / "STATE.md", self.logger)
        self.sm.add_spec("s1", {"priority": 5})

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _reject_warnings(self):
        return [m for m in self.logger.messages
                if "非法形状" in m and _OVERRIDE_FIELD in m]

    def test_bool_false_rejected_with_repr_warning(self):
        self.sm.update_spec("s1", {_OVERRIDE_FIELD: False})
        assert _OVERRIDE_FIELD not in self.sm.read_one("s1")
        warns = self._reject_warnings()
        assert len(warns) == 1, warns
        assert f"{_OVERRIDE_FIELD}=False" in warns[0], warns[0]
        assert "契约 int|None" in warns[0]
        # 坏值字面量不得进 STATE.md
        assert _override_lines(Path(self.tmpdir)) == []

    def test_bool_true_rejected(self):
        self.sm.update_spec("s1", {_OVERRIDE_FIELD: True})
        assert _OVERRIDE_FIELD not in self.sm.read_one("s1")
        assert self._reject_warnings()

    def test_string_shapes_rejected(self):
        for bad in ("False", "true", "null"):
            self.sm.update_spec("s1", {_OVERRIDE_FIELD: bad})
            assert _OVERRIDE_FIELD not in self.sm.read_one("s1"), bad
        warns = self._reject_warnings()
        assert len(warns) == 3, warns
        assert f"{_OVERRIDE_FIELD}='False'" in warns[0], warns[0]

    def test_int_and_none_pass_through(self):
        self.sm.update_spec("s1", {_OVERRIDE_FIELD: 2})
        assert self.sm.read_one("s1")[_OVERRIDE_FIELD] == 2
        assert not self._reject_warnings()
        self.sm.update_spec("s1", {_OVERRIDE_FIELD: None})
        assert self.sm.read_one("s1")[_OVERRIDE_FIELD] is None
        assert not self._reject_warnings()

    def test_rejection_scopes_to_single_field(self):
        """守卫只剥该字段：同批其余更新照常应用，既有合法值保留。"""
        self.sm.update_spec("s1", {_OVERRIDE_FIELD: 2})
        self.sm.update_spec("s1", {_OVERRIDE_FIELD: "False", "priority": 7})
        entry = self.sm.read_one("s1")
        assert entry["priority"] == 7, "同批其余字段 MUST 照常应用"
        assert entry[_OVERRIDE_FIELD] == 2, "既有合法值保留（拒绝≠清空）"
        assert self._reject_warnings()


# ── 3.1c parse 侧 int|None 归一（存量坏写首读清洗）────────────────────────


class TestParseSideNormalization(unittest.TestCase):
    """2.1b：parse 侧登记 int|None 归一（null 兼容），幂等清洗存量 STATE.md。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        _write_state(Path(self.tmpdir), {"s1": _STATE_FIELDS("implemented")})
        self.sm = StateMachine(self.state_path, _QuietLogger())
        # 先落一行合法 null，供 _set_raw 做字面量替换
        self.sm.update_spec("s1", {_OVERRIDE_FIELD: None})

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _set_raw(self, literal: str) -> None:
        txt = self.state_path.read_text(encoding="utf-8")
        txt = re.sub(rf"- {_OVERRIDE_FIELD}:.*", f"- {_OVERRIDE_FIELD}: {literal}", txt)
        self.state_path.write_text(txt, encoding="utf-8")

    def test_legacy_false_first_read_cleaned_to_null(self):
        """存量 STATE.md 的 'False' 坏写（布尔值字符串化落盘）首读清洗为 null。"""
        self._set_raw("False")
        assert self.sm.read_one("s1")[_OVERRIDE_FIELD] is None
        # 幂等：二读仍 null，不抖动
        assert self.sm.read_one("s1")[_OVERRIDE_FIELD] is None

    def test_legacy_true_string_cleaned_to_null(self):
        self._set_raw("'true'")
        assert self.sm.read_one("s1")[_OVERRIDE_FIELD] is None

    def test_unquoted_true_literal_cleaned_to_null(self):
        self._set_raw("true")
        assert self.sm.read_one("s1")[_OVERRIDE_FIELD] is None

    def test_int_literal_round_trips_as_int(self):
        self._set_raw("2")
        v = self.sm.read_one("s1")[_OVERRIDE_FIELD]
        assert v == 2 and isinstance(v, int), repr(v)

    def test_null_literal_reads_none(self):
        self._set_raw("null")
        assert self.sm.read_one("s1")[_OVERRIDE_FIELD] is None

    def test_none_literal_reads_none(self):
        self._set_raw("None")
        assert self.sm.read_one("s1")[_OVERRIDE_FIELD] is None


# ── 3.1d 读端告警：repr 形态 + 字段来源，不做布尔→并行度映射 ───────────────


def _make_pm_engine(tmpdir, max_parallel=5, logger=None):
    """读端 harness（同 test_verify_parallel_backoff._make_pm_engine 形态）。"""
    from core.pm_engine import PMEngine

    project_root = Path(tmpdir)
    (project_root / ".fenix").mkdir(parents=True, exist_ok=True)
    sm = StateMachine(project_root / ".fenix" / "STATE.md", logger)
    engine = PMEngine(
        sm, mock.MagicMock(),
        {"verify_engine": {
            "max_parallel": max_parallel,
            "inconclusive_max_attempts": 3,
            "inconclusive_escalate_attempts": 4,
        }},
        project_root, logger,
    )
    return engine, sm


class TestReadSideWarningKeepsRepr(unittest.TestCase):
    """2.2：读端解析失败告警含 repr 与字段来源（spec attrs），沿用配置并行度。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.logger = _RecorderLogger()
        self.engine, self.sm = _make_pm_engine(self.tmpdir, max_parallel=5,
                                               logger=self.logger)
        self.verify_dir = (Path(self.tmpdir) / ".fenix" / "verify-progress"
                           / "demo-spec")
        self.verify_dir.mkdir(parents=True, exist_ok=True)
        (self.verify_dir / "test_scenarios.json").write_text(json.dumps([
            {
                "id": "scn-a",
                "description": "场景A",
                "steps": [
                    {"action": "navigate", "value": "http://localhost:8787/#/projects/demo"},
                    {"action": "wait", "target": ".x", "description": "等待"},
                ],
                "assertions": [{"type": "element_visible", "selector": ".x", "label": "可见"}],
            },
        ], ensure_ascii=False), encoding="utf-8")
        self.sm.add_spec("demo-spec", {"priority": 5})
        for st in ("ready", "implementing", "implemented", "testing"):
            self.sm.transition("demo-spec", st)

        # 三段式验证链旁路 mock（同 test_verify_parallel_backoff 读端用例形态）
        self.engine._enqueue = mock.MagicMock()
        self.engine.agent_runner.run_planner = mock.MagicMock(
            return_value=SimpleNamespace(success=True, error=None,
                                         run_id="planner-judge-1"))
        self.engine._verification._apply_scenario_freeze = mock.MagicMock(return_value={})
        self.engine._verification._apply_interaction_contract = mock.MagicMock(return_value=None)
        self.engine._verification._verify_verdict_evidence = mock.MagicMock(return_value={
            "ok": True, "cause": "pass", "violations": [], "dispatch_error": "",
        })
        self.engine._verification._update_warning_streaks = mock.MagicMock(return_value=[])
        self.engine._verification._ensure_app_reachable = mock.MagicMock(
            return_value=(True, False, ""))
        self.engine._verification._env_whitewash_gate = mock.MagicMock(return_value=True)
        self.engine._verification._ensure_verification_report = mock.MagicMock(return_value=None)
        self.engine._verification._check_verification_gate = mock.MagicMock(return_value=None)
        self.engine._verification._render_scenario_change_section_to_report = mock.MagicMock()
        self.engine._on_spec_verified = mock.MagicMock()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_unparseable_value_warns_with_repr_and_source(self):
        """旁路坏值（绕过写侧守卫的内存写形态）触发读端告警：含 repr 与来源。"""
        from core.pm_engine.verification import VerdictReadResult

        self.engine._verification._read_verdict = mock.MagicMock(
            return_value=VerdictReadResult.success("verified"))
        captured = {}

        class FakeEngine:
            def __init__(self, spec_name, project_root, logger=None, config=None,
                         scenario_root=None):
                self.max_parallel = 5
                self._parallel_override_active = False

            async def run(self, scenarios):
                captured["max_parallel"] = self.max_parallel
                captured["active"] = getattr(self, "_parallel_override_active", False)
                return {
                    "spec": "demo-spec",
                    "summary": {
                        "total": 2, "passed": 1, "warnings": 0,
                        "failed": 1, "errors": 0, "blocked_env": 0,
                    },
                    "scenarios": [],
                }

        real_read_one = self.sm.read_one

        def _bad_read_one(name):
            entry = dict(real_read_one(name) or {})
            entry[_OVERRIDE_FIELD] = "False"  # 旁路坏值：int() 不可解析
            return entry

        with mock.patch.object(self.sm, "read_one", side_effect=_bad_read_one), \
                mock.patch("importlib.reload", lambda m: m), \
                mock.patch("core.verify_engine.VerifyEngine", FakeEngine):
            self.engine._run_three_stage_verification("demo-spec")

        # 不把布尔语义映射为特定并行度：沿用配置并行度 5
        assert captured["max_parallel"] == 5, captured
        assert captured["active"] is False
        warns = [m for m in self.logger.messages if "降档并行度解析失败" in m]
        assert len(warns) == 1, warns
        assert f"{_OVERRIDE_FIELD}='False'" in warns[0], warns[0]
        assert "取自 spec attrs" in warns[0], warns[0]
