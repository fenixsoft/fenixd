"""
tests/test_timeline_transition_context.py — fix-observability-gaps 3.2

验证 get_spec_timeline 时间轴重建：
- 新格式（带 channel context）走结构化解路径（含 Gate transition 覆盖）
- 旧格式（无 context）走正则兜底路径
- 混合窗口（新旧格式共存同一日志文件）：无重复节点、无丢失
- 逐行互斥：同一日志行不产出两个状态节点
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path


def _line(ts: str, msg: str, context: dict | None = None) -> str:
    """构造 fenixd.log 单行 JSON 事件。"""
    e = {"timestamp": ts, "level": "INFO",
         "component": "state_machine", "message": msg}
    if context is not None:
        e["context"] = context
    return json.dumps(e, ensure_ascii=False)


def _write_log(tmpdir: str, lines: list[str]) -> None:
    logs_dir = Path(tmpdir) / ".fenix" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / "fenixd.log").write_text("\n".join(lines) + "\n",
                                         encoding="utf-8")


class TestNewFormatStructuredPath:
    """Task 3.2：新格式 Transition 行（含 channel context）走结构化解路径。"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.spec = "spec-z"

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_transition_with_channel_parsed(self):
        """Transition 行含 channel context → 时间轴含 from/to 且 context 字段落节点。"""
        _write_log(self.tmpdir, [
            _line("2026-09-17T10:00:00Z",
                  f"Transition: {self.spec} ready → implementing",
                  context={"channel": "auto", "trigger_run_id": "run-1",
                           "agent_type": "implementer"}),
        ])
        from core.dashboard.data import get_spec_timeline
        timeline = get_spec_timeline(self.tmpdir, self.spec)
        states = [e for e in timeline if e.get("kind") == "state"]
        assert len(states) == 1
        n = states[0]
        assert n["from"] == "ready"
        assert n["to"] == "implementing"
        assert n["channel"] == "auto"
        assert n["trigger_run_id"] == "run-1"
        assert n["agent_type"] == "implementer"

    def test_gate_transition_with_channel_parsed(self):
        """Gate transition 行（小写 t）含 channel context → 时间轴正确解析。"""
        _write_log(self.tmpdir, [
            _line("2026-09-17T10:05:00Z",
                  f"Gate transition: {self.spec} verified → testing",
                  context={"channel": "recovery", "trigger_run_id": None,
                           "agent_type": None}),
        ])
        from core.dashboard.data import get_spec_timeline
        timeline = get_spec_timeline(self.tmpdir, self.spec)
        states = [e for e in timeline if e.get("kind") == "state"]
        assert len(states) == 1
        n = states[0]
        assert n["from"] == "verified"
        assert n["to"] == "testing"
        assert n["channel"] == "recovery"


class TestOldFormatRegexFallback:
    """Task 3.2：旧格式 Transition 行（无 context）走正则兜底路径。"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.spec = "spec-old"

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_old_format_parsed_by_regex(self):
        """无 context 的 Transition 行 → 正则兜底正确解析 from/to。"""
        _write_log(self.tmpdir, [
            _line("2026-09-17T09:00:00Z",
                  f"Transition: {self.spec} implementing → implemented"),
        ])
        from core.dashboard.data import get_spec_timeline
        timeline = get_spec_timeline(self.tmpdir, self.spec)
        states = [e for e in timeline if e.get("kind") == "state"]
        assert len(states) == 1
        n = states[0]
        assert n["from"] == "implementing"
        assert n["to"] == "implemented"
        # 无 context → 节点不含 channel 字段（或为 None）
        assert n.get("channel") is None


class TestMixedWindow:
    """Task 3.1a：混合窗口（新旧格式共存）→ 无重复节点、无丢失。"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.spec = "spec-mix"

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_mixed_window_no_duplicates_no_loss(self):
        """同日志文件既有新格式又有旧格式 → 所有节点重建、折叠后无重复、去重有效。"""
        _write_log(self.tmpdir, [
            # 旧格式 Transition（无 context）：implementing → implemented
            _line("2026-09-17T08:00:00Z",
                  f"Transition: {self.spec} implementing → implemented"),
            _line("2026-09-17T08:00:00.010Z",
                  f"Updated SPEC '{self.spec}'",
                  context={"updates": {"status": "implemented"}}),
            # 新格式 Transition（含 context）：implemented → testing
            _line("2026-09-17T09:00:00Z",
                  f"Transition: {self.spec} implemented → testing",
                  context={"channel": "auto", "trigger_run_id": "run-v1",
                           "agent_type": "verifier"}),
            _line("2026-09-17T09:00:00.010Z",
                  f"Updated SPEC '{self.spec}'",
                  context={"updates": {"status": "testing"}}),
            # 新格式 Gate transition（含 context）：testing → verified
            _line("2026-09-17T10:00:00Z",
                  f"Gate transition: {self.spec} testing → verified",
                  context={"channel": "auto"}),
            _line("2026-09-17T10:00:00.010Z",
                  f"Updated SPEC '{self.spec}'",
                  context={"updates": {"status": "verified"}}),
        ])
        from core.dashboard.data import get_spec_timeline
        timeline = get_spec_timeline(self.tmpdir, self.spec)
        states = [e for e in timeline if e.get("kind") == "state"]
        # 三条连续前向转换（implementing→implemented→testing→verified）折叠为单节点
        assert len(states) == 1, f"连续前向节点应折叠为 1 个节点，实际 {len(states)}: {states}"
        n = states[0]
        # chain 完整保留全部中间状态（含链首 from）
        assert n.get("chain") == ["implementing", "implemented", "testing", "verified"], \
            f"chain 不完整: {n}"
        # 新格式节点的 context 随折叠保留（取首节点 channel）
        assert n.get("channel") == "auto", "channel 应随折叠保留"
        # Updated SPEC 去重：同一次转换的 Updated SPEC 行被去重跳过，不产生重复节点
        assert n["from"] == "implementing"  # 起始状态正确
        assert n["to"] == "verified"        # 终态正确


class TestBackwardWithContext:
    """Task 3.2：回退转换含 context 时仍正确判定 backward。"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.spec = "spec-back"

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_backward_transition_with_context(self):
        """verified → testing（回退）含 context → backward=True 且 context 保留。"""
        _write_log(self.tmpdir, [
            _line("2026-09-17T11:00:00Z",
                  f"Transition: {self.spec} verified → testing",
                  context={"channel": "recovery", "trigger_run_id": None,
                           "agent_type": None}),
        ])
        from core.dashboard.data import get_spec_timeline
        timeline = get_spec_timeline(self.tmpdir, self.spec)
        states = [e for e in timeline if e.get("kind") == "state"]
        assert len(states) == 1
        n = states[0]
        assert n["backward"] is True
        assert n["channel"] == "recovery"
