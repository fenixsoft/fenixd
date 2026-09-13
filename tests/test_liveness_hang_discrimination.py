"""tests/test_liveness_hang_discrimination.py — fix-run-hang-amplification 1.x

覆盖：
  5.1 心跳/实质事件分离——构造「大量心跳 + 零实质事件」窗口 → 断言不得判 advancing 且
      走零事件停滞路径；构造「有持续实质事件」窗口 → 断言可判 advancing。
  5.2 零产出短路——三条件同时成立 → 断言短路返回 kill 且未调用 judge；输出文件不可观测
      → 断言不短路、走 LLM 路径；仅有重复调用形态（无零产出）→ 断言不短路。
  5.3 负向——断言无任何以「重复调用占比/结果重复度」为判据的分支（常量
      HANG_REPEAT_RATIO_THRESHOLD 不存在于实现）。
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.agent_runner.liveness import (
    LivenessSupervisor,
    HANG_BLOCKED_CALL_SECONDS,
    HANG_ZERO_GROWTH_WINDOW_SECONDS,
    HANG_MIN_TOOL_COMPLETIONS,
)


# ── Fixtures & helpers ────────────────────────────────────────────────

class FakePM:
    """LivenessSupervisor 的 _pm 最小实现（解析时间戳 + mock logger）。"""

    def __init__(self):
        self.project_root = Path(tempfile.mkdtemp())
        self._running_agents = {}
        self.logger = MagicMock()
        self._called_liveness_config = False

    def _parse_event_timestamp(self, entry):
        raw = entry.get("timestamp")
        if raw is None:
            return None
        if isinstance(raw, (int, float)):
            return float(raw)
        try:
            from datetime import datetime, timezone
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
        except Exception:
            return None

    def _get_config(self, key, default=None):
        return default

    def _effective_run_timeout(self, agent_type=None):
        return 3600

    def _send_human_escalation_alert(self, **kwargs):
        pass


def _write_event_line(path: Path, entry: dict):
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _make_run_file(events, now=None):
    """创建假 run jsonl，返回 Path。"""
    now = time.time() if now is None else now
    path = Path(tempfile.mktemp(suffix=".jsonl"))
    for ev in events:
        _write_event_line(path, ev)
    return path


def _assistant_block(tool_name="Read", tool_input=None, result=None, ts=None):
    blocks = [{"type": "tool_use", "name": tool_name,
               "input": tool_input or {}}]
    if result is not None:
        blocks.append({"type": "tool_result",
                        "content": [{"type": "text", "text": str(result)}]})
    entry = {
        "type": "assistant",
        "message": {"role": "assistant", "content": blocks},
    }
    if ts is not None:
        entry["timestamp"] = ts
    return entry


def _tool_result_block(ts=None):
    return {"type": "user",
            "message": {"role": "user",
                        "content": [{"type": "tool_result",
                                     "content": [{"type": "text", "text": "ok"}]}]},
            "timestamp": ts or time.time()}


def _heartbeat(ts=None):
    return {"type": "tool_progress",
            "timestamp": ts or time.time()}


def _assistant_block_text(text, ts=None):
    """只含文本内容的 assistant 消息（substantive event，无 tool_result）"""
    entry = {
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }
    if ts is not None:
        entry["timestamp"] = ts
    return entry


# ── 5.1 心跳/实质事件分离 ─────────────────────────────────────────────

class TestSubstantiveVsHeartbeat:
    """5.1 心跳/实质事件分离——快照与 supervisor 判定口径。"""

    def test_only_heartbeats_zero_substantive(self, tmp_path):
        """大量心跳 + 零实质事件窗口 → events_in_window == 0（进度为零）。"""
        now = time.time()
        events = [_heartbeat(ts=now - i * 30) for i in range(20)]
        run_file = _make_run_file(events)
        pm = FakePM()
        sup = LivenessSupervisor(pm)
        snap = sup._liveness_snapshot(run_file, window_seconds=600, now=now)
        assert snap["events_in_window"] == 0
        assert snap["substantive_events_in_window"] == 0
        assert snap["heartbeats_in_window"] == 20
        run_file.unlink(missing_ok=True)

    def test_mixed_events_substantive_only(self, tmp_path):
        """心跳 + 实质事件 → events_in_window 只计实质事件。"""
        now = time.time()
        events = [
            _heartbeat(ts=now - 100),
            _assistant_block(ts=now - 80),
            _tool_result_block(ts=now - 60),
            _heartbeat(ts=now - 40),
            _assistant_block(ts=now - 20),
        ]
        run_file = _make_run_file(events)
        pm = FakePM()
        sup = LivenessSupervisor(pm)
        snap = sup._liveness_snapshot(run_file, window_seconds=300, now=now)
        # 实质事件：assistant (80), tool_result (60), assistant (20) → 3
        # 心跳：2 (100, 40)
        assert snap["events_in_window"] == 3
        assert snap["heartbeats_in_window"] == 2
        run_file.unlink(missing_ok=True)

    def test_supervisor_kills_zero_substantive_events(self, tmp_path):
        """零实质事件窗口 → supervisor 走「zero substantive events」kill 路径。"""
        now = time.time()
        started = now - 4000
        events = [_heartbeat(ts=now - i * 30) for i in range(30)]
        run_file = _make_run_file(events)
        pm = FakePM()
        sup = LivenessSupervisor(pm)
        action = sup._supervision_deadline_action(
            run_file, "test-spec", "run-001",
            started_at=started, extensions_used=0,
            judge=lambda *a, **k: {"verdict": "advancing", "evidence": "no"})
        assert action["action"] == "kill"
        assert "zero substantive run events" in action["reason"]
        run_file.unlink(missing_ok=True)

    def test_advancing_with_sustained_substantive_events(self, tmp_path):
        """持续实质事件窗口 → 可判 advancing。"""
        now = time.time()
        started = now - 4000
        events = []
        for i in range(20):
            ts = now - (600 - i * 30)
            events.append(_assistant_block(ts=ts))
            events.append(_tool_result_block(ts=ts + 5))
        run_file = _make_run_file(events)
        pm = FakePM()
        sup = LivenessSupervisor(pm)

        def fake_judge(snap, spec, rid):
            # 有实质事件 → advancing
            assert snap["substantive_events_in_window"] >= 1
            return {"verdict": "advancing", "evidence": "substantive events present"}

        action = sup._supervision_deadline_action(
            run_file, "test-spec", "run-002",
            started_at=started, extensions_used=0,
            judge=fake_judge)
        assert action["action"] == "extend"
        run_file.unlink(missing_ok=True)


# ── 5.2 零产出短路 ────────────────────────────────────────────────────

class TestZeroOutputShortcut:
    """5.2 零产出确定性短路三条件判定。"""

    def test_shortcut_triggers_when_all_conditions_met(self, tmp_path):
        """三条件同时成立 → 短路返回 kill 且未调用 judge。"""
        import os
        now = time.time()
        started = now - 4000
        task_started_at = now - 400  # > HANG_BLOCKED_CALL_SECONDS(300)
        output_file = tmp_path / "pytest.output"
        output_file.write_text("x\n")  # size=2B
        # 设置文件的 mtime 为 task_started_at 之前，使零增长窗口 >= 300s
        os.utime(str(output_file), (task_started_at - 10, task_started_at - 10))
        # 构造 run 事件：task_started + assistant 文本事件（substantive events > 0，
        # 让零事件守卫不触发；无 tool_result，故 tool_completions_in_window == 0，
        # 满足短路的三条件）。
        events = [
            {"type": "system", "subtype": "task_started",
             "task_id": "task1", "output_file": str(output_file),
             "timestamp": task_started_at},
            _assistant_block_text("checking test status", ts=now - 100),
            _heartbeat(ts=now - 50),
        ]
        run_file = _make_run_file(events)
        pm = FakePM()
        sup = LivenessSupervisor(pm)

        judge_called = False
        def fake_judge(*a, **k):
            nonlocal judge_called
            judge_called = True
            return {"verdict": "advancing", "evidence": "impossible"}

        action = sup._supervision_deadline_action(
            run_file, "test-spec", "run-003",
            started_at=started, extensions_used=0,
            judge=fake_judge)
        assert action["action"] == "kill"
        assert "heuristic zero-output" in action["reason"] or "zero-output" in action["evidence"]
        assert not judge_called, "judge must not be called on zero-output shortcut"
        run_file.unlink(missing_ok=True)

    def test_no_shortcut_when_output_file_unobservable(self, tmp_path):
        """输出文件不可观测（不存在）→ 不短路，走 LLM 判定。"""
        now = time.time()
        started = now - 4000
        task_started_at = now - 400
        events = [
            {"type": "system", "subtype": "task_started",
             "task_id": "task2", "output_file": str(tmp_path / "nonexistent.output"),
             "timestamp": task_started_at},
            _assistant_block_text("investigating test failure", ts=now - 100),
            _heartbeat(ts=now - 50),
        ]
        run_file = _make_run_file(events)
        pm = FakePM()
        sup = LivenessSupervisor(pm)

        judge_called = False
        def fake_judge(*a, **k):
            nonlocal judge_called
            judge_called = True
            return {"verdict": "stagnant", "evidence": "no growth"}

        action = sup._supervision_deadline_action(
            run_file, "test-spec", "run-004",
            started_at=started, extensions_used=0,
            judge=fake_judge)
        assert judge_called, "judge must be called when output file unobservable"
        assert action["action"] == "kill"  # judge said stagnant
        run_file.unlink(missing_ok=True)

    def test_no_shortcut_with_only_duplicate_calls_no_zero_growth(self, tmp_path):
        """仅有重复调用形态（无 task_started / output_file）→ 不短路。"""
        now = time.time()
        started = now - 4000
        # 大量重复 Read 同一文件（无后台 task）
        events = []
        for i in range(30):
            ts = now - (600 - i * 5)
            events.append(_assistant_block(ts=ts, tool_name="Read",
                                            tool_input={"file_path": "x.py"}))
            events.append(_tool_result_block(ts=ts + 1))
        run_file = _make_run_file(events)
        pm = FakePM()
        sup = LivenessSupervisor(pm)

        judge_called = False
        def fake_judge(*a, **k):
            nonlocal judge_called
            judge_called = True
            # 有实质事件 + 有 tool_completions → 不应走短路
            assert k.get("snap") is None or True  # snapshot passed as first positional
            return {"verdict": "advancing", "evidence": "sustained activity"}

        action = sup._supervision_deadline_action(
            run_file, "test-spec", "run-005",
            started_at=started, extensions_used=0,
            judge=fake_judge)
        assert judge_called, "judge must be called (no zero-output shortcut possible)"
        assert action["action"] == "extend"
        run_file.unlink(missing_ok=True)

    def test_shortcut_writes_evidence_to_run_file(self, tmp_path):
        """短路判定证据写入 run jsonl（供审计）。"""
        import os
        now = time.time()
        started = now - 4000
        task_started_at = now - 400
        output_file = tmp_path / "out.log"
        output_file.write_text("")  # size=0B
        # 设置 mtime 使零增长窗口 >= 300s
        os.utime(str(output_file), (task_started_at - 10, task_started_at - 10))
        events = [
            {"type": "system", "subtype": "task_started",
             "task_id": "task3", "output_file": str(output_file),
             "timestamp": task_started_at},
            _assistant_block_text("checking status", ts=now - 100),
            _heartbeat(ts=now - 20),
        ]
        run_file = _make_run_file(events)
        pm = FakePM()
        sup = LivenessSupervisor(pm)
        action = sup._supervision_deadline_action(
            run_file, "test-spec", "run-006",
            started_at=started, extensions_used=0,
            judge=lambda *a, **k: {"verdict": "advancing"})
        # 检查 run_file 是否追加了 liveness_shortcut 事件
        lines = run_file.read_text().strip().splitlines()
        shortcut_events = [l for l in lines if '"liveness_shortcut"' in l]
        assert len(shortcut_events) == 1, f"expected exactly 1 shortcut event, got {len(shortcut_events)}"
        payload = json.loads(shortcut_events[0])
        assert payload["kind"] == "zero_output_heuristic"
        assert "output_file" in payload.get("evidence", "") or "zero growth" in payload.get("evidence", "")
        run_file.unlink(missing_ok=True)


# ── 5.3 负向：无重复占比/重复度判据 ────────────────────────────────────

class TestNegativeRepeatRatioNotUsed:
    """5.3 断言实现中不包含重复工具调用占比/结果重复度判据。"""

    def test_no_repeat_ratio_threshold_constant_in_liveness(self):
        """liveness.py 不含 HANG_REPEAT_RATIO_THRESHOLD 常量。"""
        import core.agent_runner.liveness as mod
        assert not hasattr(mod, "HANG_REPEAT_RATIO_THRESHOLD"), \
            "liveness.py must not define HANG_REPEAT_RATIO_THRESHOLD (repeat-ratio heuristic excluded)"
        assert not hasattr(mod, "HANG_RESULT_REPEAT_THRESHOLD"), \
            "liveness.py must not define HANG_RESULT_REPEAT_THRESHOLD"

    def test_no_repeat_ratio_branch_in_source(self):
        """liveness.py 源码中不存在 'repeat_ratio'/'result_repeat' 判据代码路径。"""
        src = Path(__file__).resolve().parents[1] / "core" / "agent_runner" / "liveness.py"
        text = src.read_text(encoding="utf-8")
        assert "repeat_ratio" not in text.lower(), \
            "liveness.py must not contain 'repeat_ratio' logic"
        assert "result_repeat" not in text.lower(), \
            "liveness.py must not contain 'result_repeat' logic"
        assert "相同工具调用占比" not in text, \
            "liveness.py must not contain '相同工具调用占比' as criterion"
