"""self-review-run-semantics 测试：result 型终态的业务失败语义解析。

对应 tasks：
- 3.1 盲派 result-run 判 failed；真实成功 result-run 判 succeeded；
  标记/信号双源兜底；样本输出含依据

实证背景（scheduling-showcase）：12 个盲派 implementer run 因空 spec
失败，但进程正常终止（result 事件）被计为 succeeded——终止态 ≠ 成功态。
本测试锁定「result 文本命中业务失败标记 / 同 run 结构性失败信号 → failed」。
"""

import json
from datetime import datetime

import pytest

from core.self_review import (
    _BUSINESS_FAIL_PATTERNS,
    _classify_run,
    collect_failed_run_samples,
    collect_runs_stats,
)


def _line(**kw):
    """构造单行 run 产物事件。"""
    return dict(kw)


class TestClassifyResultBusinessSemantics:
    """2.1/2.2：_classify_run 的 result 分支业务失败解析。"""

    def test_blind_result_run_marker_failed(self):
        """盲派 run：result 文本含『SPEC 内容缺失，无法实现』→ failed。"""
        lines = [_line(type="result", result="SPEC 内容缺失，无法实现", num_turns=1)]
        category, detail = _classify_run("impl-blank-1", lines)
        assert category == "failed"
        assert "SPEC 内容缺失" in detail

    def test_real_success_result_run_succeeded(self):
        """真实成功 run：result 文本正常收尾 → succeeded。"""
        lines = [_line(
            type="result",
            result="任务完成，所有验证通过，产物已提交",
            num_turns=8,
        )]
        category, detail = _classify_run("impl-ok-1", lines)
        assert category == "succeeded"
        assert detail == ""

    def test_budget_exhausted_marker_failed(self):
        """预算耗尽短语命中 → failed。"""
        lines = [_line(type="result", result="本轮预算已耗尽，无法继续实现", num_turns=5)]
        category, detail = _classify_run("impl-budget-1", lines)
        assert category == "failed"
        assert "预算" in detail

    def test_signal_fallback_when_no_marker(self):
        """双源护栏：result 无标记但事件序列含 budget-exhausted 信号 → failed。"""
        lines = [
            _line(type="system", subtype="task_started", description="start"),
            _line(type="assistant", message="budget-exhausted terminated"),
            _line(type="result", result="进程退出", num_turns=1),
        ]
        category, detail = _classify_run("impl-sig-1", lines)
        assert category == "failed"
        assert detail.startswith("signal=")

    def test_marker_wins_without_signal(self):
        """保守路径：result 含标记但无信号 → 仍按文本判 failed。"""
        lines = [
            _line(type="system", subtype="task_started"),
            _line(type="result", result="SPEC 内容缺失，零交付", num_turns=1),
        ]
        category, detail = _classify_run("impl-marker-only-1", lines)
        assert category == "failed"
        assert detail.startswith("marker=")

    def test_error_terminal_unchanged(self):
        """error 终态路径不受影响（回归护栏）。"""
        lines = [_line(type="error", error="boom", exit_code=1)]
        category, _detail = _classify_run("impl-err-1", lines)
        assert category == "failed"

    def test_timeout_terminal_unchanged(self):
        """timeout 终态路径不受影响（回归护栏）。"""
        lines = [_line(type="error", error="Timeout after 120s — x", exit_code=-9)]
        category, _detail = _classify_run("impl-tout-1", lines)
        assert category == "timeout"

    def test_marker_list_contains_required_invariants(self):
        """标记清单覆盖 spec 要求的不变量短语。"""
        for expect in ("SPEC 内容缺失", "无法实现", "预算耗尽", "零交付"):
            assert any(expect in p for p in _BUSINESS_FAIL_PATTERNS)


class TestCollectStatsAndSamples:
    """2.3/3.1 集成：统计口径与失败样本可追溯输出。"""

    def _make_run(self, proot, run_id, lines):
        p = proot / ".fenix" / "runs" / f"{run_id}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            "".join(json.dumps(l, ensure_ascii=False) + "\n" for l in lines),
            encoding="utf-8",
        )
        return p

    def test_blind_run_counts_failed(self, tmp_path):
        """盲派 result-run 计入 failed 而非 succeeded。"""
        root = tmp_path / "proj"
        root.mkdir()
        self._make_run(root, "impl-blank-999", [
            _line(type="result", result="SPEC 内容缺失，无法实现", num_turns=1),
        ])
        stats = collect_runs_stats(root, datetime(2000, 1, 1, 0, 0))
        assert stats["failed"] == 1
        assert stats["succeeded"] == 0
        assert stats["total"] == 1

    def test_signal_fallback_counts_failed(self, tmp_path):
        """信号兜底：result 无标记但文件中部含 spec_content_missing → failed。"""
        root = tmp_path / "proj"
        root.mkdir()
        self._make_run(root, "impl-sig-999", [
            _line(type="system", subtype="start"),
            _line(type="assistant", message="spec_content_missing detected"),
            _line(type="result", result="已退出", num_turns=1),
        ])
        stats = collect_runs_stats(root, datetime(2000, 1, 1, 0, 0))
        assert stats["failed"] == 1
        assert stats["succeeded"] == 0

    def test_samples_include_run_id_and_evidence(self, tmp_path):
        """样本输出含 run_id + 命中依据（可追溯）。"""
        root = tmp_path / "proj"
        root.mkdir()
        self._make_run(root, "impl-blank-998", [
            _line(type="result", result="SPEC 内容缺失，无法实现", num_turns=1),
        ])
        self._make_run(root, "impl-sig-997", [
            _line(type="assistant", message="budget-exhausted terminated"),
            _line(type="result", result="已退出", num_turns=1),
        ])
        self._make_run(root, "impl-ok-996", [
            _line(type="result", result="任务完成，验证通过", num_turns=4),
        ])
        samples = collect_failed_run_samples(root, datetime(2000, 1, 1, 0, 0))
        assert len(samples) == 2
        by_id = {s["run_id"]: s["detail"] for s in samples}
        assert "impl-blank-998" in by_id
        assert by_id["impl-blank-998"].startswith("marker=")
        assert "impl-sig-997" in by_id
        assert by_id["impl-sig-997"].startswith("signal=")
        assert "impl-ok-996" not in by_id

    def test_samples_sorted_and_limited(self, tmp_path):
        """样本按时间倒序并受 limit 截断。"""
        root = tmp_path / "proj"
        root.mkdir()
        for i in range(5):
            self._make_run(root, f"impl-sig-{990 - i}", [
                _line(type="result", result="预算耗尽" if i % 2 else "SPEC 内容缺失",
                      num_turns=1),
            ])
        samples = collect_failed_run_samples(root, datetime(2000, 1, 1, 0, 0), limit=3)
        assert len(samples) == 3
        # 倒序：run_id 大（时间晚）的在前
        run_ids = [s["run_id"] for s in samples]
        assert run_ids == sorted(run_ids, reverse=True)

    def test_sample_scan_finds_midfile_signal(self, tmp_path):
        """全文件扫描兜底：信号在文件中部（尾部行不覆盖）仍能命中。"""
        root = tmp_path / "proj"
        root.mkdir()
        self._make_run(root, "impl-sig-995", [
            _line(type="system", subtype="start"),
            _line(type="assistant", message="impl_budget_exhausted alert raised"),
            _line(type="system", subtype="task_started"),
            _line(type="result", result="进程正常结束", num_turns=1),
        ])
        stats = collect_runs_stats(root, datetime(2000, 1, 1, 0, 0))
        assert stats["failed"] == 1

    def test_success_run_not_in_succeeded_with_review_excluded(self, tmp_path):
        """review- 自省 run 仍被排除。"""
        root = tmp_path / "proj"
        root.mkdir()
        self._make_run(root, "review-2026-09-13", [
            _line(type="result", result="ok", num_turns=2),
        ])
        stats = collect_runs_stats(root, datetime(2000, 1, 1, 0, 0))
        assert stats["total"] == 0