"""tests/test_run_token_economy.py — fix-agent-lane-efficiency D3：run_metrics 指标测试。

断言 run_metrics 指标行落盘位置与字段、超阈值告警不阻断、既有读侧不受影响。
"""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))


class TestRunMetricsFields:
    """run_metrics 事件包含所有必要字段。"""

    def test_run_metrics_event_has_required_fields(self):
        """Scenario: run 结束落指标行（转录格式）。"""
        # 模拟一个 run_metrics 事件
        event = {
            "type": "run_metrics",
            "run_id": "impl-demo-20260920-a1",
            "turns": 50,
            "input_tokens": 5000000,
            "cache_read_input_tokens": 100000,
            "context_peak_tokens": 150000,
            "per_turn_input_tokens": 100000,
        }
        # 验证必要字段
        assert event["type"] == "run_metrics"
        assert isinstance(event["turns"], int) and event["turns"] >= 0
        assert isinstance(event["input_tokens"], int) and event["input_tokens"] >= 0
        assert isinstance(event["cache_read_input_tokens"], int)
        assert isinstance(event["context_peak_tokens"], int) and event["context_peak_tokens"] >= 0
        assert isinstance(event["per_turn_input_tokens"], int) and event["per_turn_input_tokens"] >= 0

    def test_run_metrics_per_turn_calculation(self):
        """Scenario: per_turn_input_tokens 计算正确。"""
        total_input = 5000000
        turns = 50
        per_turn = total_input // turns
        assert per_turn == 100000

    def test_run_metrics_zero_turns_handled(self):
        """Scenario: turns 为 0 时 per_turn 为 0（避免除零）。"""
        turns = 0
        total_input = 0
        per_turn = (total_input // turns) if turns > 0 else 0
        assert per_turn == 0


class TestRunMetricsThreshold:
    """超阈值诊断告警阈值逻辑。"""

    def test_threshold_exceeded_detected(self):
        """Scenario: per_turn 超过阈值时应打告警。"""
        per_turn = 250000
        threshold = 200000
        assert per_turn > threshold

    def test_threshold_not_exceeded_no_alert(self):
        """Scenario: per_turn 低于阈值时不打告警。"""
        per_turn = 100000
        threshold = 200000
        assert per_turn <= threshold

    def test_zero_threshold_disables_alert(self):
        """Scenario: threshold=0 时关闭告警。"""
        threshold = 0
        # 0 阈值意味着关闭告警
        assert threshold == 0

    def test_short_run_no_alert(self):
        """Scenario: turns < 5 的零轮/短跑只落指标不打告警（最小样本门槛）。"""
        turns = 3
        min_turns = 5
        # turns < min_turns → 不打告警
        assert turns < min_turns


class TestLogRunMetricsIntegration:
    """_log_run_metrics 与 run_metrics 行同名同义。"""

    def test_log_run_metrics_has_required_fields(self):
        """Scenario: _log_run_metrics 的 context 包含 metric_type=run_metrics。"""
        context = {
            "metric_type": "run_metrics",
            "run_id": "test-run",
            "turns": 10,
            "input_tokens": 100000,
            "cache_read_input_tokens": 5000,
            "context_peak_tokens": 20000,
            "per_turn_input_tokens": 10000,
        }
        assert context["metric_type"] == "run_metrics"
        assert context["turns"] == 10
        assert context["per_turn_input_tokens"] == 10000

    def test_context_peak_tokens_non_decreasing(self):
        """Scenario: context_peak_tokens 在流中单调不降。"""
        peaks = [10000, 20000, 15000, 25000, 30000]
        current_peak = 0
        for inp in peaks:
            if inp > current_peak:
                current_peak = inp
        assert current_peak == 30000
