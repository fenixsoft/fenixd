"""self-review-result-based-classification 测试：自省失败判定以 run 终态为准。

对应 tasks：
- 2.1 夹具「成功 result + 正文含预算耗尽/impl_budget_exhausted/spec_content_missing」
  → 断言 succeeded 且不入失败样本（复现 2026-09-17 5/7 误报场景：5 个误报 run
  终态 result 均成功，全文件命中信号词 2/9/1/1/39 次被 _scan_run_signals 翻转）
- 2.2 夹具「error 终态 + 信号词」→ 断言 failed(signal=...)；「无 result 终态 +
  信号词」→ 断言兜底归因生效（扫描机制保留、不改写 category）
- 2.3 夹具「result 文本命中业务失败标记」→ 断言 failed(marker=...) 维持
- 2.5 夹具「result 终态 + 信号词仅出现在终态邻近 3 行之外」→ 断言 succeeded 且
  不入失败样本；夹具「无 result 终态（running/dropped）+ 信号词」→ 断言 category
  桶位不变、stats["failed"] 不因该 run 增加
- evo-fix-self-review-marker-match-window 2.1/2.2：marker 匹配窗口收敛——
  失败声明仅认 result 文本开头声明区（前 _MARKER_DECLARATION_WINDOW 字符），
  摘要中段功能词复述（实拍「预算耗尽发一次性 warning」形态）不降级；开头
  声明形态仍判 failed，窗口边界成对锁定；result 终态正文不再作信号源
- evo-fix-self-review-phantom-failed-samples 1.1/1.3：信号护栏排除终态邻近
  窗口（尾三行 [assistant, run_metrics, result]）中的 assistant 收工叙事
  回声行（result 正文正是其同源副本，失败词必然同现——2026-09-25 两幻影
  误报实拍）；窗口外的独立事件行仍是信号证据通道（有意推翻 698a9a0d
  「兜底通道不收窄」决策）

判定口径（result-based classification）：succeeded 以 _classify_run 的 result
分支判定结果为准——result 文本未命中 _business_fail_marker 且终态邻近 3 行未命中
_signal_evidence 即计为 succeeded，不引入成功语义文本白名单（朴素文本如「已退出」
同样计为 succeeded）；信号扫描仅作失败归因 detail 补充，MUST NOT 改写 category。
"""

import json
from datetime import datetime

import pytest

from core.self_review import (
    _MARKER_DECLARATION_WINDOW,
    _business_fail_marker,
    _classify_run,
    _read_run_tail,
    _scan_run_signals,
    collect_failed_run_samples,
    collect_runs_stats,
)


def _line(**kw):
    """构造单行 run 产物事件。"""
    return dict(kw)


def _make_run(proot, run_id, lines):
    p = proot / ".fenix" / "runs" / f"{run_id}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "".join(json.dumps(l, ensure_ascii=False) + "\n" for l in lines),
        encoding="utf-8",
    )
    return p


def _make_success_run_with_topic_words(root, run_id, signal_word):
    """成功终态 run：信号词只出现在文件头部（终态邻近 3 行之外）。

    run 转录正文讨论预算/缺失类主题（repair/planner/evo 轮常见）——这正是
    2026-09-17 误报的构造：_classify_run 返回 succeeded，但旧聚合层全文件
    扫描 _scan_run_signals 把成功 run 翻转误判为 failed。
    """
    _make_run(root, run_id, [
        _line(type="assistant", message=f"阅读源码，正文讨论 {signal_word} 的失败分类主题"),
        _line(type="system", subtype="task_started", description=f"实现修复，mention {signal_word}"),
        _line(type="system", subtype="tool_call", tool="Read", argument="core/self_review.py"),
        _line(type="system", subtype="tool_call", tool="Write", argument="core/self_review.py"),
        _line(type="result", result="合并冲突已解决并提交，全部验证通过", num_turns=8),
    ])


class TestSuccessTerminalWithTopicWords:
    """2.1/2.5：成功终态不被正文主题词降级（复现 2026-09-17 5/7 误报）。"""

    @pytest.mark.parametrize(
        "signal_word", ["budget-exhausted", "impl_budget_exhausted", "spec_content_missing"]
    )
    def test_success_result_with_topic_signal_stays_succeeded(self, tmp_path, signal_word):
        root = tmp_path / "proj"
        root.mkdir()
        _make_success_run_with_topic_words(root, "evo-false-positive-2026", signal_word)

        # 全文件扫描确实能命中信号（旧代码的误报路径依然可复现）
        p = root / ".fenix" / "runs" / "evo-false-positive-2026.jsonl"
        assert _scan_run_signals(p) == f"signal={signal_word}"

        stats = collect_runs_stats(root, datetime(2000, 1, 1, 0, 0))
        assert stats["succeeded"] == 1
        assert stats["failed"] == 0
        assert stats["total"] == 1

        samples = collect_failed_run_samples(root, datetime(2000, 1, 1, 0, 0))
        assert samples == []

    def test_signal_word_beyond_terminal_3_lines_stays_succeeded(self, tmp_path):
        """2.5：信号词仅在终态邻近 3 行之外 → succeeded 且不入失败样本。

        尾 3 行为 tool_call/result 纯终态行，信号词位于文件头部（终态邻近
        3 行之外）——_signal_evidence 不命中、_classify_run 判 succeeded，
        聚合层不再做全文件主题词扫描降级。
        """
        root = tmp_path / "proj"
        root.mkdir()
        run_id = "impl-success-topic-3lines"
        _make_run(root, run_id, [
            _line(type="system", subtype="task_started", description="预算耗尽 主题"),
            _line(type="assistant", message="impl_budget_exhausted 判定边界 / spec_content_missing 常见失败模式，本次未触发"),
            _line(type="system", subtype="tool_call", tool="Bash", argument="git push"),
            _line(type="system", subtype="tool_call", tool="Bash", argument="pytest tests/ -q"),
            _line(type="system", subtype="task_started", description="验证通过"),
            _line(type="result", result="已退出", num_turns=6),
        ])

        p = root / ".fenix" / "runs" / f"{run_id}.jsonl"
        assert _scan_run_signals(p) is not None  # 全文件扫描确实命中（旧路径可翻转）

        category, detail = _classify_run(run_id, [
            {"type": "tool_call", "tool": "Bash", "argument": "git push"},
            {"type": "result", "result": "已退出", "num_turns": 6},
        ])
        assert category == "succeeded"
        assert detail == ""

        stats = collect_runs_stats(root, datetime(2000, 1, 1, 0, 0))
        assert stats["succeeded"] == 1
        assert stats["failed"] == 0

        samples = collect_failed_run_samples(root, datetime(2000, 1, 1, 0, 0))
        assert samples == []


class TestFallbackOnlyForFailureAttribution:
    """2.2：信号扫描兜底仅补失败归因 detail，不改写 category。"""

    def test_error_terminal_with_empty_text_supplement_signal(self, tmp_path):
        """error 终态缺省 error 文本（detail 为空）→ 全文件扫描拼 signal=<词>。

        _classify_run 仍给出 failed（error 终态语义不变），归因 detail 由
        兜底扫描补充——真失败不丢，且归因可追溯。
        """
        root = tmp_path / "proj"
        root.mkdir()
        run_id = "impl-error-empty-detail"
        _make_run(root, run_id, [
            _line(type="assistant", message="impl_budget_exhausted alert raised"),
            _line(type="system", subtype="task_started"),
            _line(type="error"),  # 缺省 error 文本 → detail=""
        ])

        category, detail = _classify_run(run_id, [
            {"type": "assistant", "message": "impl_budget_exhausted alert raised"},
            {"type": "system", "subtype": "task_started"},
            {"type": "error"},
        ])
        assert category == "failed"

        stats = collect_runs_stats(root, datetime(2000, 1, 1, 0, 0))
        assert stats["failed"] == 1

        samples = collect_failed_run_samples(root, datetime(2000, 1, 1, 0, 0))
        assert len(samples) == 1
        assert samples[0]["run_id"] == run_id
        assert samples[0]["detail"] == "signal=impl_budget_exhausted"

    def test_error_terminal_prefers_classify_detail(self, tmp_path):
        """error 终态已给 detail → 以 _classify_run 的 detail 为准，不覆盖。"""
        root = tmp_path / "proj"
        root.mkdir()
        run_id = "impl-error-has-detail"
        _make_run(root, run_id, [
            _line(type="assistant", message="spec_content_missing 主题讨论"),
            _line(type="error", error="boom", exit_code=1),
        ])

        samples = collect_failed_run_samples(root, datetime(2000, 1, 1, 0, 0))
        assert len(samples) == 1
        assert samples[0]["detail"] == "boom"  # 不是 signal=...（以前者为准）

    def test_no_result_terminal_signal_not_reclassified(self, tmp_path):
        """无 result 终态（在飞 run）+ 信号词 → 兜底归因机制保留但分类不改写。

        在飞 run 转录正文必含被修改源码字面量（如「预算耗尽」），若改写为
        failed 将制造与本次修复同源的新误报——category 桶位必须保持不变。
        断言 _scan_run_signals 仍能探测信号（真失败不丢的探测机制保留），
        同时 stats 桶位与失败样本清单均不因该 run 改变。
        """
        root = tmp_path / "proj"
        root.mkdir()
        run_id = "impl-inflight-signal"
        p = _make_run(root, run_id, [
            _line(type="system", subtype="task_started"),
            _line(type="assistant", message="正在实施，涉及预算耗尽/impl_budget_exhausted 讨论"),
            _line(type="system", subtype="tool_call", tool="Read", argument="core/self_review.py"),
        ])
        assert _scan_run_signals(p) == "signal=impl_budget_exhausted"

        category, detail = _classify_run(run_id, [
            {"type": "system", "subtype": "task_started"},
            {"type": "assistant", "message": "正在实施，涉及预算耗尽/impl_budget_exhausted 讨论"},
            {"type": "system", "subtype": "tool_call", "tool": "Read"},
        ])
        assert category == "running"
        assert detail == "no-terminal"

        stats = collect_runs_stats(root, datetime(2000, 1, 1, 0, 0))
        assert stats["running"] == 1
        assert stats["failed"] == 0
        assert stats["succeeded"] == 0

        samples = collect_failed_run_samples(root, datetime(2000, 1, 1, 0, 0))
        assert samples == []


class TestMarkerRegression:
    """2.3：result 文本命中业务失败标记 → failed(marker=...) 维持（既有语义）。"""

    def test_result_marker_failed_maintained(self, tmp_path):
        root = tmp_path / "proj"
        root.mkdir()
        run_id = "impl-marker-regression"
        _make_run(root, run_id, [
            _line(type="system", subtype="task_started"),
            _line(type="result", result="SPEC 内容缺失，无法实现", num_turns=1),
        ])

        category, detail = _classify_run(
            run_id,
            [{"type": "system", "subtype": "task_started"},
             {"type": "result", "result": "SPEC 内容缺失，无法实现", "num_turns": 1}],
        )
        assert category == "failed"
        assert detail.startswith("marker=")

        stats = collect_runs_stats(root, datetime(2000, 1, 1, 0, 0))
        assert stats["failed"] == 1
        assert stats["succeeded"] == 0

        samples = collect_failed_run_samples(root, datetime(2000, 1, 1, 0, 0))
        assert len(samples) == 1
        assert samples[0]["run_id"] == run_id
        assert samples[0]["detail"].startswith("marker=")


class TestBucketUnchangedNoFalseIncrease:
    """2.5：无 result 终态（running/dropped）+ 信号词 → 桶位不变、failed 不增加。"""

    def test_running_with_signal_bucket_unchanged(self, tmp_path):
        root = tmp_path / "proj"
        root.mkdir()
        _make_run(root, "impl-running-sig", [
            _line(type="system", subtype="task_started"),
            _line(type="assistant", message="预算耗尽 主题出现但 run 仍在飞"),
            _line(type="system", subtype="tool_call", tool="Read"),
        ])
        stats = collect_runs_stats(root, datetime(2000, 1, 1, 0, 0))
        assert stats["running"] == 1
        assert stats["failed"] == 0

    def test_dropped_empty_bucket_unchanged(self, tmp_path):
        root = tmp_path / "proj"
        root.mkdir()
        _make_run(root, "impl-dropped-empty", [])  # 空文件 → dropped
        stats = collect_runs_stats(root, datetime(2000, 1, 1, 0, 0))
        assert stats["dropped"] == 1
        assert stats["failed"] == 0

    def test_mixed_window_failed_only_real_failures(self, tmp_path):
        """混合窗口：主题词 run 一律不注入 failed，统计/样本只认真失败。"""
        root = tmp_path / "proj"
        root.mkdir()
        # 成功终态 + 正文主题词（误报场景）
        _make_success_run_with_topic_words(root, "evo-topic-success", "预算耗尽")
        # 在飞 run + 信号词
        _make_run(root, "impl-inflight-topic", [
            _line(type="system", subtype="task_started"),
            _line(type="assistant", message="impl_budget_exhausted 讨论"),
        ])
        # 空文件（dropped）
        _make_run(root, "impl-empty-file", [])
        # 真失败：result 文本命中 marker
        _make_run(root, "impl-real-fail", [
            _line(type="result", result="预算已耗尽，零交付", num_turns=3),
        ])

        stats = collect_runs_stats(root, datetime(2000, 1, 1, 0, 0))
        assert stats["total"] == 4
        assert stats["succeeded"] == 1
        assert stats["running"] == 1
        assert stats["dropped"] == 1
        assert stats["failed"] == 1  # 仅真失败计入

        samples = collect_failed_run_samples(root, datetime(2000, 1, 1, 0, 0))
        assert [s["run_id"] for s in samples] == ["impl-real-fail"]
        assert samples[0]["detail"].startswith("marker=")


class TestMarkerWindowConvergence:
    """窗口收敛（evo-fix-self-review-marker-match-window 2.1/2.2）。

    实拍（2026-09-24 日报）：完全成功的 run 被误计 failed（marker=预算耗尽）
    ——成功摘要中段的功能词复述「预算耗尽发一次性 warning」（第 692/1382 字符）
    被全文裸词匹配当成失败声明。失败声明仅认 result 文本开头声明区。
    """

    @staticmethod
    def _result_with_budget_word_at(offset: int) -> str:
        """构造「预算耗尽」首现于 offset 的 result 文本（成功摘要叙事形态）。"""
        return (
            "前情摘要。" * (offset // 5)
            + "预算耗尽发一次性 warning 属调度器一次性提示，不影响交付，"
            "全部任务已完成并提交。"
        )

    def test_midsummary_word_succeeded_and_not_in_samples(self, tmp_path):
        """2.1：中段功能词复述（is_error=False/subtype=success）→ succeeded 且不入失败样本。

        marker 声明在窗口外不命中；终态邻近事件行干净、result 正文不再作
        信号源——两条路径都不再降级，统计与失败样本随之自然修正。
        """
        root = tmp_path / "proj"
        root.mkdir()
        run_id = "impl-midtext-marker-success"
        result_text = self._result_with_budget_word_at(300)
        assert result_text.index("预算耗尽") >= _MARKER_DECLARATION_WINDOW

        _make_run(root, run_id, [
            _line(type="system", subtype="task_started", description="evo-fix 实施"),
            _line(type="system", subtype="tool_call", tool="Bash", argument="git push"),
            _line(type="result", result=result_text, is_error=False,
                  subtype="success", num_turns=9),
        ])

        # marker 路径：命中词位于声明窗口外，不再返回命中
        assert _business_fail_marker(result_text) is None

        p = root / ".fenix" / "runs" / f"{run_id}.jsonl"
        category, detail = _classify_run(run_id, _read_run_tail(p, 3))
        assert category == "succeeded"
        assert detail == ""

        stats = collect_runs_stats(root, datetime(2000, 1, 1, 0, 0))
        assert stats["succeeded"] == 1
        assert stats["failed"] == 0

        samples = collect_failed_run_samples(root, datetime(2000, 1, 1, 0, 0))
        assert samples == []

    def test_signal_guardrail_skips_echo_line_keeps_independent_lines(self):
        """护栏语义（evo-fix-self-review-phantom-failed-samples 1.1）：终态邻近
        窗口内的 assistant 回声行不再是信号源，窗口外独立事件行仍是；
        result 终态正文从来不是。

        回声行排除：result 正文正是窗口内 assistant 消息的同源副本，失败词
        必然同现——不排除则 marker 声明窗口收窄被信号路径原路绕过（2026-09-25
        两幻影误报实拍；有意推翻 698a9a0d「兜底通道不收窄」决策）。信号词仅
        出现在 result 正文中段同样不二次降级（实拍误判的第二源）。
        """
        # 回声行：终态邻近窗口内的 assistant 事件行不再作信号源
        category, detail = _classify_run("impl-sig-echo-line", [
            {"type": "system", "subtype": "task_started"},
            {"type": "assistant", "message": "budget-exhausted terminated"},
            {"type": "result", "result": "进程退出", "num_turns": 1},
        ])
        assert category == "succeeded"
        assert detail == ""

        # 独立事件行：窗口外（尾三行窗口之外）的 assistant 事件行仍是信号源
        category, detail = _classify_run("impl-sig-independent-line", [
            {"type": "assistant", "message": "budget-exhausted terminated"},
            {"type": "system", "subtype": "step", "description": "step-1"},
            {"type": "system", "subtype": "step", "description": "step-2"},
            {"type": "result", "result": "进程退出", "num_turns": 1},
        ])
        assert category == "failed"
        assert detail.startswith("signal=")

        prose = "前情摘要。" * 24 + "中途 impl_budget_exhausted 提示一次，不影响交付，全部任务已完成。"
        assert prose.index("impl_budget_exhausted") >= _MARKER_DECLARATION_WINDOW
        category, detail = _classify_run("impl-sig-result-prose", [
            {"type": "system", "subtype": "task_started"},
            {"type": "result", "result": prose, "is_error": False,
             "subtype": "success", "num_turns": 1},
        ])
        assert category == "succeeded"
        assert detail == ""

    @pytest.mark.parametrize("offset, expect_failed", [
        (0, True),     # 开头声明：假成功抓取语义保持（evo-add-self-review-run-semantics）
        (95, True),    # 声明起于窗口内（95..99 全落在前 100 字符）→ failed
        (100, False),  # 声明起于窗口边界之外 → 中段复述，不降级
        (300, False),  # 实拍量级（中段）
    ])
    def test_declaration_window_boundary(self, offset, expect_failed):
        """2.2 成对锁边界：窗口内声明仍判 failed(marker=...)，窗口外复述不降级。"""
        text = self._result_with_budget_word_at(offset)
        assert text.index("预算耗尽") == offset
        category, detail = _classify_run(
            f"impl-marker-window-{offset}",
            [{"type": "result", "result": text, "is_error": False,
              "subtype": "success", "num_turns": 3}],
        )
        if expect_failed:
            assert category == "failed"
            assert detail == "marker=预算耗尽"
        else:
            assert category == "succeeded"
            assert detail == ""

    def test_head_declaration_failed_pair(self, tmp_path):
        """2.2 成对：与 2.1 中段成功形态镜像的开头声明形态仍判 failed 且入样本。

        subtype=success 不豁免 marker 判定（非目标：不跳过成功终态的 marker
        判定，02d6cf1c 的假成功抓取语义不推翻）。
        """
        root = tmp_path / "proj"
        root.mkdir()
        run_id = "impl-head-decl-failed"
        _make_run(root, run_id, [
            _line(type="result", result="预算已耗尽，无法继续实现",
                  is_error=False, subtype="success", num_turns=1),
        ])

        stats = collect_runs_stats(root, datetime(2000, 1, 1, 0, 0))
        assert stats["failed"] == 1
        assert stats["succeeded"] == 0

        samples = collect_failed_run_samples(root, datetime(2000, 1, 1, 0, 0))
        assert [s["run_id"] for s in samples] == [run_id]
        assert samples[0]["detail"] == "marker=预算已耗尽"