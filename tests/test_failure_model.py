"""run 失败建模与归因分类契约（fix-spawn-attribution-hardening 任务 1.2/D2/A4）。

infra-deterministic 分类：FileNotFoundError(2) → 终态语义、归因三型分立
（spawn_failed/nonzero_exit/result_missing）、result_missing 附转录 stderr
尾窗（截尾 2KB）。
"""

import json

import pytest

from core.agent_runner.failure_model import (
    INFRA_DETERMINISTIC_ERROR_MARKER,
    RESULT_MISSING_ATTRIBUTION_TAG,
    RUN_ATTRIBUTION_NONZERO_EXIT,
    RUN_ATTRIBUTION_RESULT_MISSING,
    RUN_ATTRIBUTION_SPAWN_FAILED,
    RUN_ATTRIBUTION_TYPES,
    STDERR_TAIL_WINDOW_LIMIT,
    classify_run_failure,
    infra_deterministic_error,
    is_deterministic_spawn_failure,
    latest_transcript_for_run,
    result_missing_attribution,
    stderr_tail_window,
    transcript_stderr_tail,
)


def _enoent(errno=2, msg="[WinError 2] 系统找不到指定的文件。"):
    return FileNotFoundError(errno, msg)


class TestDeterministicSpawnFailure:
    """spawn 缺件确定性闭集（errno 2/3）。"""

    def test_file_not_found_errno_2_is_deterministic(self):
        assert is_deterministic_spawn_failure(_enoent(2)) is True

    def test_file_not_found_errno_3_is_deterministic(self):
        assert is_deterministic_spawn_failure(_enoent(3)) is True

    def test_permission_error_not_in_closed_set(self):
        # 权限问题不在确定性闭集（design D2：不扩面，维持重试语义）
        assert is_deterministic_spawn_failure(
            PermissionError(13, "Permission denied")) is False

    def test_other_oserror_not_deterministic(self):
        assert is_deterministic_spawn_failure(
            OSError(5, "Input/output error")) is False

    def test_none_exc_safe(self):
        assert is_deterministic_spawn_failure(None) is False


class TestInfraDeterministicErrorText:
    """终态 error 文案：标记 + 根因 + 修复指引。"""

    def test_marker_and_repair_hint_present(self):
        text = infra_deterministic_error("claude", _enoent(2))
        assert text.startswith(INFRA_DETERMINISTIC_ERROR_MARKER)
        assert "claude 不在当前 PATH" in text
        assert "install.md §8" in text
        assert "nssm restart" in text

    def test_carries_exc_detail(self):
        text = infra_deterministic_error("claude", _enoent(2))
        assert "WinError 2" in text

    def test_none_executable_falls_back(self):
        text = infra_deterministic_error(None)
        assert "harness CLI 不在当前 PATH" in text


class TestClassifyRunFailure:
    """归因三型分立纯函数。"""

    def test_enum_covers_three_types(self):
        assert RUN_ATTRIBUTION_TYPES == (
            "spawn_failed", "nonzero_exit", "result_missing")

    def test_deterministic_spawn_exc_maps_spawn_failed(self):
        assert classify_run_failure(_enoent(2)) == RUN_ATTRIBUTION_SPAWN_FAILED

    def test_missing_result_maps_result_missing(self):
        assert classify_run_failure(
            has_result=False) == RUN_ATTRIBUTION_RESULT_MISSING

    def test_nonzero_exit_maps_nonzero_exit(self):
        assert classify_run_failure(
            exit_code=1, has_result=True) == RUN_ATTRIBUTION_NONZERO_EXIT

    def test_spawn_failure_takes_precedence_over_result_missing(self):
        assert classify_run_failure(
            _enoent(2), has_result=False) == RUN_ATTRIBUTION_SPAWN_FAILED


class TestStderrTailWindow:
    """stderr 尾窗截尾 2KB。"""

    def test_empty_lines_return_empty(self):
        assert stderr_tail_window([]) == ""
        assert stderr_tail_window(None) == ""

    def test_short_lines_joined(self):
        assert stderr_tail_window(["a", "b"]) == "a\nb"

    def test_truncated_to_limit_bytes(self):
        lines = [f"line-{i:04d} " + "x" * 50 for i in range(200)]
        out = stderr_tail_window(lines)
        assert len(out.encode("utf-8")) <= STDERR_TAIL_WINDOW_LIMIT
        # 尾窗语义：保留的是末尾内容
        assert "line-0199" in out
        assert "line-0000" not in out

    def test_multibyte_safe_at_boundary(self):
        line = "错" * 3000  # UTF-8 每字 3 字节，边界必劈
        out = stderr_tail_window([line])
        assert len(out.encode("utf-8")) <= STDERR_TAIL_WINDOW_LIMIT
        assert "�" not in out  # 防劈字容错，无替换符残留


class TestTranscriptStderrTail:
    """run 转录 stderr 尾窗提取。"""

    def _write_transcript(self, tmp_path, entries):
        p = tmp_path / "run-1.jsonl"
        p.write_text(
            "\n".join(json.dumps(e, ensure_ascii=False) for e in entries),
            encoding="utf-8")
        return p

    def test_extracts_stderr_lines(self, tmp_path):
        p = self._write_transcript(tmp_path, [
            {"type": "system", "subtype": "init"},
            {"type": "stderr", "line": "boom-1"},
            {"type": "assistant"},
            {"type": "stderr", "line": "boom-2"},
        ])
        out = transcript_stderr_tail(p)
        assert "boom-1" in out and "boom-2" in out

    def test_missing_file_fail_open_empty(self, tmp_path):
        assert transcript_stderr_tail(tmp_path / "absent.jsonl") == ""

    def test_corrupt_lines_skipped(self, tmp_path):
        p = tmp_path / "run-2.jsonl"
        p.write_text("not-json\n{\"type\": \"stderr\", \"line\": \"ok\"}\n",
                     encoding="utf-8")
        assert transcript_stderr_tail(p) == "ok"


class TestResultMissingAttribution:
    """result_missing 归因：类型标记 + stderr 尾窗（取证断链修复）。"""

    def test_tag_and_error_present(self):
        text = result_missing_attribution("Exit code: 1", stderr_tail="")
        assert text.startswith(RESULT_MISSING_ATTRIBUTION_TAG)
        assert "result_missing" in text
        assert "Exit code: 1" in text

    def test_stderr_tail_included_when_provided(self):
        text = result_missing_attribution(
            "err", stderr_tail="claude: command not found")
        assert "stderr 尾窗: claude: command not found" in text

    def test_transcript_fallback_when_summary_empty(self, tmp_path):
        # v0.1.1 实测 stderr_tail 为空串 → 回读转录取证（非空串断言）
        p = tmp_path / "run-3.jsonl"
        p.write_text(
            json.dumps({"type": "stderr", "line": "transcript-tail-evidence"},
                       ensure_ascii=False) + "\n",
            encoding="utf-8")
        text = result_missing_attribution("err", stderr_tail="", run_file=p)
        assert "transcript-tail-evidence" in text

    def test_no_evidence_omits_tail_honestly(self):
        text = result_missing_attribution("err", stderr_tail="", run_file=None)
        assert "stderr 尾窗" not in text


class TestLatestTranscriptForRun:
    def test_newest_matching_wins(self, tmp_path):
        import os
        old = tmp_path / "run-x-a1.jsonl"
        new = tmp_path / "run-x-a1-r1.jsonl"
        old.write_text("{}", encoding="utf-8")
        new.write_text("{}", encoding="utf-8")
        os.utime(old, (1, 1))
        os.utime(new, (2, 2))
        assert latest_transcript_for_run(tmp_path, "run-x") == new

    def test_no_match_returns_none(self, tmp_path):
        assert latest_transcript_for_run(tmp_path, "absent") is None
        assert latest_transcript_for_run(tmp_path, "") is None


class TestDispatchClassifierConsumption:
    """dispatch 终态分类按标记路由 infra-deterministic（任务 3.1 消费面）。"""

    def test_classify_run_terminal_failure_routes_marker(self):
        from core.pm_engine.dispatch.queue import (
            _classify_run_terminal_failure,
            RUN_TERMINAL_INFRA_DETERMINISTIC,
        )
        text = infra_deterministic_error("claude", _enoent(2))
        assert _classify_run_terminal_failure(
            text) == RUN_TERMINAL_INFRA_DETERMINISTIC

    def test_marker_not_shadowed_by_model_chain(self):
        # 标记优先级：infra-deterministic 判定先于 model_chain（同文本
        # 不含 harness 标记，此处锁路由不回归——harness 不可达标记仍路由
        # model_chain 持态）
        from core.pm_engine.dispatch.queue import (
            _classify_run_terminal_failure,
            RUN_TERMINAL_MODEL_CHAIN,
        )
        from core.agent_runner.harness import HARNESS_CLI_UNAVAILABLE_MARKER
        assert _classify_run_terminal_failure(
            f"{HARNESS_CLI_UNAVAILABLE_MARKER} x") == RUN_TERMINAL_MODEL_CHAIN


@pytest.mark.parametrize("errno", [2, 3])
def test_closed_set_parametrized(errno):
    assert is_deterministic_spawn_failure(_enoent(errno)) is True
