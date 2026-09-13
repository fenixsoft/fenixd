"""tests/test_full_suite_runner.py — fix-run-hang-amplification 3.x

覆盖 5.6：
  - 模拟挂起套件 → 断言有界入口在超时内中止并报出挂起测试标识；
  - `--baseline` 归类在「存量-only / 引入-only / 混合」三态正确。
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bin.run_full_suite import (
    classify_baseline,
    classify_outcome,
    collect_failed_tests,
    extract_hanging_test,
    run_command,
    run_suite,
    suite_port_base,
)


# ── 5.6.1 extract_hanging_test 解析 ──────────────────────────────────

class TestExtractHangingTest:
    """解析 faulthandler 栈输出。"""

    def test_extracts_stack_top_function(self):
        stderr = (
            "Thread 0x7f1234567890 (most recent call first):\n"
            '  File "/repo/tests/test_dispatch_aging.py", line 142, in test_deadline_action\n'
            '    self._supervision_deadline_action(run_file, "spec", "run-1", started_at=time.time()-10000, extensions_used=0)\n'
            '  File "/repo/core/agent_runner/liveness.py", line 100, in _supervision_deadline_action\n'
            '    snapshot = self._liveness_snapshot(run_file, window)\n'
        )
        result = extract_hanging_test(stderr)
        assert result == "/repo/tests/test_dispatch_aging.py:test_deadline_action"

    def test_returns_none_when_no_stack(self):
        assert extract_hanging_test("") is None
        assert extract_hanging_test("some random log\n") is None


# ── 5.6.2 classify_baseline / classify_outcome ────────────────────────

class TestBaselineClassification:
    """三态归类正确。"""

    def test_pass_all_green(self):
        assert classify_baseline([], []) == "pass"
        assert classify_outcome([], []) == "pass（全绿）"

    def test_baseline_only(self):
        failures = ["tests/test_a.py::test_x", "tests/test_b.py::test_y"]
        assert classify_baseline(failures, failures) == "baseline_only"
        assert classify_outcome(failures, failures) == "存量"

    def test_introduced_only(self):
        cur = ["tests/test_new.py::test_z"]
        base = ["tests/test_old.py::test_x"]
        assert classify_baseline(cur, base) == "introduced"
        assert classify_outcome(cur, base) == "本次引入"

    def test_mixed(self):
        cur = ["tests/test_old.py::test_x", "tests/test_new.py::test_z"]
        base = ["tests/test_old.py::test_x"]
        assert classify_baseline(cur, base) == "mixed"
        assert classify_outcome(cur, base) == "存量 + 本次引入（混合，判存在本次引入回归）"


# ── 5.6.3 collect_failed_tests ─────────────────────────────────────────

class TestCollectFailedTests:
    def test_collects_from_pytest_output(self):
        stdout = ""
        stderr = (
            "FAILED tests/test_a.py::test_x - AssertionError\n"
            "FAILED tests/test_b.py::test_y - ValueError: boom\n"
            "===== 2 failed ... =====\n"
        )
        result = collect_failed_tests(stderr, stdout)
        assert "tests/test_a.py::test_x" in result
        assert "tests/test_b.py::test_y" in result
        assert len(result) == 2


# ── 5.6.4 run_command 超时 ────────────────────────────────────────────

class TestRunCommand:
    def test_timeout_kills_long_running(self):
        """sleep 999 + timeout=0.2 → timed_out=True，returncode=None。"""
        rc, out, err, timed_out = run_command(
            ["sleep", "999"], timeout=0.2, cwd=Path(tempfile.mkdtemp()))
        assert timed_out is True
        assert rc is None


# ── 5.6.5 run_suite 挂起模拟 ──────────────────────────────────────────

class TestRunSuite:
    def test_timeout_reports_hanging_test(self, tmp_path):
        """用 bash 输出 faulthandler 栈格式后挂起 → 超时内中止并提取挂起标识。"""
        # 构造一个自包含命令：写 faulthandler 栈到 stderr，然后 sleep 挂起
        script = (
            'python3 -c "'
            "import sys, time; "
            "sys.stderr.write('Thread 0x... (most recent call first):\\n'); "
            'sys.stderr.write(\'  File \\"/repo/tests/test_foo.py\\", line 10, in test_bar\\n\'); '
            "sys.stderr.flush(); "
            "time.sleep(999)"
            '"'
        )
        cmd = ["bash", "-c", script]
        result = run_suite(
            tmp_path, timeout=1.0, cmd_override=cmd)
        assert result["timed_out"] is True
        assert result["exit_code"] == 124
        assert result["hanging_test"] == "/repo/tests/test_foo.py:test_bar"


# ── 5.6.6 suite_port_base ────────────────────────────────────────────

class TestSuitePortBase:
    def test_pid_based_default(self):
        """默认基于 pid 派生端口段。"""
        base = suite_port_base()
        assert 31000 <= base < 32000
        assert (base - 31000) == (sys.modules['os'].getpid() % 1000)

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("FENIX_SUITE_PORT_BASE", "40000")
        assert suite_port_base() == 40000

    def test_invalid_env_falls_back(self, monkeypatch):
        monkeypatch.setenv("FENIX_SUITE_PORT_BASE", "not-a-number")
        base = suite_port_base()
        assert 31000 <= base < 32000
