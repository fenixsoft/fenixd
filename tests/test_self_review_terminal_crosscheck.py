"""self-review 终态交叉守卫测试（evo-fix-self-review-phantom-failed-samples 3.1/3.2）。

夹具取自 2026-09-25 两幻影 run 的真实形态（design 实测复现）：
- impl-evo-fix-self-review-marker-match-window-1790242754-a1：收工摘要正文
  偏移 739 处提及「预算耗尽」（描述修复目标，非声明失败）
- planner-plan-evo-fix-self-review-marker-match-window-1790243612-a1：正文含
  测试场景表原文（「SPEC 内容缺失」断言词）

两 run 终态均 result（daemon 侧 run_metrics terminal=success），尾三行为
[assistant, run_metrics, result] 结构，assistant 行承载与 result 同源的收工
叙事回声——旧信号护栏扫 lines[:-1] 时失败词原路回流，误判 failed 且重启
daemon 不可消除。本文件锁定：
- 3.1 幻影形态分类 succeeded 且不入失败样本（1.1 信号护栏）
- 3.2 信号路径 failed × daemon 终态双源交叉守卫（2.1/2.2/2.3）：
  terminal=success 不计失败并产出 self_review_phantom_failure 告警
  （warning、不自动 handled）、marker= 命中不纳守卫、索引缺失维持现状、
  统计与样本口径一致。
"""

import json
from datetime import datetime

import pytest

from core.dashboard.data.runs import load_run_metric
from core.self_review import (
    _MARKER_DECLARATION_WINDOW,
    _business_fail_marker,
    _classify_run,
    _read_run_tail,
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


def _make_metric_log(root, terminals: dict, name: str = "fenixd.log"):
    """写 daemon 侧指标日志（run_metrics 结构化行）：terminals = {base_run_id: terminal}。

    形态对齐 runner._log_run_metrics 真实日志行（context 含 metric_type/
    run_id/terminal），read 侧 _load_run_metric_index 按 context.run_id 索引。
    """
    log = root / ".fenix" / "logs" / name
    log.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for rid, terminal in terminals.items():
        rows.append(
            json.dumps(
                {
                    "timestamp": "2026-09-25T00:00:00.000000Z",
                    "level": "INFO",
                    "component": "agent_runner",
                    "message": f"run metrics: terminal={terminal}",
                    "context": {
                        "metric_type": "run_metrics",
                        "run_id": rid,
                        "terminal": terminal,
                        "duration_seconds": 12.5,
                        "cost_usd": 0.1,
                    },
                },
                ensure_ascii=False,
            )
        )
    log.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return log


class _FakeStore:
    """AdminStore 形状替身：记录 append / mark_handled 调用。"""

    def __init__(self):
        self.appended = []
        self.handled = []

    def append(self, entry: dict) -> dict:
        rec = dict(entry)
        rec.setdefault("id", f"alert-{len(self.appended)}")
        self.appended.append(rec)
        return rec

    def mark_handled(self, alert_id: str) -> bool:
        self.handled.append(alert_id)
        return True


class _FakeLogger:
    """logger 形状替身：记录 warning 调用（store 未注入的降级通道）。"""

    def __init__(self):
        self.warnings = []

    def warning(self, component, message):
        self.warnings.append(str(message))

    def info(self, component, message):
        pass

    def error(self, component, message):
        pass


def _signal_failed_run(root, run_id: str):
    """信号路径 failed 夹具：信号词在终态邻近窗口内的独立（非 assistant 回声）
    事件行——1.1 收窄后残余的信号检出通道，detail=signal=<词>。"""
    return _make_run(root, run_id, [
        _line(type="system", subtype="start"),
        _line(type="system", subtype="tool_call", tool="Bash",
              argument="deploy", output="budget-exhausted detected in step"),
        _line(type="result", result="收工", num_turns=3),
    ])


class TestPhantomRunShape:
    """3.1：两幻影 run 真实形态 → succeeded 且不入失败样本。"""

    @staticmethod
    def _phantom_lines(run_id: str, word: str):
        """尾三行 [assistant, run_metrics, result]：失败词仅存在于 result 正文
        中段（声明区干净）与其 assistant 回声行（收工叙事同源）。"""
        filler = "过程中回归验证逐项通过，" * 12
        result_text = (
            "收工摘要：本轮针对该问题的护栏修复已全部完成并提交，"
            + filler
            + f"此前观察到的一次 {word} 告警属历史轮次回执，不影响交付。"
        )
        narrative = (
            f"最终收工叙事：修复已落地，验证全部通过并提交。正文提及的 {word} "
            "为被修复问题的描述性引用，非本轮失败声明。"
        )
        return [
            _line(type="assistant",
                  message={"role": "assistant",
                           "content": [{"type": "text", "text": narrative}]}),
            _line(type="run_metrics", run_id=run_id, turns=12, input_tokens=48000,
                  cache_read_input_tokens=120000, context_peak_tokens=90000,
                  per_turn_input_tokens=4000),
            _line(type="result", result=result_text, is_error=False,
                  subtype="success", num_turns=12),
        ], result_text

    @pytest.mark.parametrize("run_id, word", [
        ("impl-phantom-1790242754-a1", "预算耗尽"),
        ("planner-phantom-1790243612-a1", "SPEC 内容缺失"),
    ])
    def test_phantom_tail_succeeded_and_not_sampled(self, tmp_path, run_id, word):
        root = tmp_path / "proj"
        root.mkdir()
        lines, result_text = self._phantom_lines(run_id, word)
        _make_run(root, run_id, lines)

        # 声明区干净（marker 声明窗口语义不变，1.2）
        assert word not in result_text[:_MARKER_DECLARATION_WINDOW]
        assert _business_fail_marker(result_text) is None

        p = root / ".fenix" / "runs" / f"{run_id}.jsonl"
        tail = _read_run_tail(p, 3)
        # 真实形态：尾三行 [assistant, run_metrics, result]
        assert [l.get("type") for l in tail] == ["assistant", "run_metrics", "result"]
        # 失败词确实同时存在于 assistant 回声行与 result 正文——旧信号护栏
        # （扫 lines[:-1] 不排回声行）会经信号路径误判 failed，夹具非空洞
        assert word in json.dumps(tail[0], ensure_ascii=False)
        assert word in json.dumps(tail[2], ensure_ascii=False)

        category, detail = _classify_run(run_id, tail)
        assert category == "succeeded"
        assert detail == ""

        stats = collect_runs_stats(root, datetime(2000, 1, 1, 0, 0).astimezone())
        assert stats["total"] == 1
        assert stats["succeeded"] == 1
        assert stats["failed"] == 0

        samples = collect_failed_run_samples(root, datetime(2000, 1, 1, 0, 0).astimezone())
        assert samples == []


class TestTerminalCrossGuard:
    """3.2：信号路径 failed × daemon 终态双源交叉守卫。"""

    def test_signal_failed_terminal_success_excluded_and_alerted(self, tmp_path):
        """signal= failed 而 terminal=success → 不计失败、产出幻影告警不自动 handled。"""
        root = tmp_path / "proj"
        root.mkdir()
        run_id = "impl-sig-phantom-1790244001"
        _signal_failed_run(root, run_id)
        _make_metric_log(root, {run_id: "success"})

        store = _FakeStore()
        samples = collect_failed_run_samples(root, datetime(2000, 1, 1, 0, 0).astimezone(), store=store)
        assert samples == []
        assert len(store.appended) == 1
        alert = store.appended[0]
        assert alert["kind"] == "escalation"
        assert alert["signal_type"] == "self_review_phantom_failure"
        assert alert["severity"] == "warning"
        assert run_id in alert["evidence"]
        assert store.handled == []  # 不自动 mark_handled

        # 统计侧同步（2.3）：幻影不计失败统计（改计 succeeded）
        stats = collect_runs_stats(root, datetime(2000, 1, 1, 0, 0).astimezone())
        assert stats["total"] == 1
        assert stats["failed"] == 0
        assert stats["succeeded"] == 1

    def test_attempt_suffix_metric_alignment(self, tmp_path):
        """-a1 attempt 产物 stem 与基础 run_id 指标对齐（_strip_run_attempt_suffix）。"""
        root = tmp_path / "proj"
        root.mkdir()
        run_id = "impl-sig-phantom-1790244002-a1"
        _signal_failed_run(root, run_id)
        _make_metric_log(root, {"impl-sig-phantom-1790244002": "success"})
        samples = collect_failed_run_samples(
            root, datetime(2000, 1, 1, 0, 0).astimezone(), store=_FakeStore()
        )
        assert samples == []

    def test_rotated_log_fallback(self, tmp_path):
        """跨轮转旧 run：主日志无记录时回退 .fenixd.log.1，守卫仍生效。"""
        root = tmp_path / "proj"
        root.mkdir()
        run_id = "impl-rot-phantom-1790244003-a1"
        _signal_failed_run(root, run_id)
        _make_metric_log(
            root, {"impl-rot-phantom-1790244003": "success"}, name="fenixd.log.1"
        )
        store = _FakeStore()
        samples = collect_failed_run_samples(root, datetime(2000, 1, 1, 0, 0).astimezone(), store=store)
        assert samples == []
        assert len(store.appended) == 1
        assert store.appended[0]["signal_type"] == "self_review_phantom_failure"

    def test_marker_failed_terminal_success_still_counted(self, tmp_path):
        """marker= 命中即使 terminal=success 仍计失败（假成功抓取语义保持），无幻影告警。"""
        root = tmp_path / "proj"
        root.mkdir()
        run_id = "impl-marker-catch-1790244004"
        _make_run(root, run_id, [
            _line(type="result", result="预算已耗尽，无法继续实现",
                  is_error=False, subtype="success", num_turns=1),
        ])
        _make_metric_log(root, {run_id: "success"})

        store = _FakeStore()
        samples = collect_failed_run_samples(root, datetime(2000, 1, 1, 0, 0).astimezone(), store=store)
        assert [s["run_id"] for s in samples] == [run_id]
        assert samples[0]["detail"] == "marker=预算已耗尽"

        stats = collect_runs_stats(root, datetime(2000, 1, 1, 0, 0).astimezone())
        assert stats["failed"] == 1
        assert stats["succeeded"] == 0
        assert store.appended == []  # 不产生 self_review_phantom_failure 告警

    def test_missing_metric_keeps_failed(self, tmp_path):
        """索引查不到该 run 终态（日志轮转出窗）→ 维持现状计入，不因缺数据改判。"""
        root = tmp_path / "proj"
        root.mkdir()
        run_id = "impl-sig-nolog-1790244005"
        _signal_failed_run(root, run_id)
        # 不写任何指标日志（索引缺失形态）

        store = _FakeStore()
        samples = collect_failed_run_samples(root, datetime(2000, 1, 1, 0, 0).astimezone(), store=store)
        assert [s["run_id"] for s in samples] == [run_id]
        assert samples[0]["detail"].startswith("signal=")
        assert store.appended == []

        stats = collect_runs_stats(root, datetime(2000, 1, 1, 0, 0).astimezone())
        assert stats["failed"] == 1

    def test_store_absent_still_excludes_and_degrades_to_log(self, tmp_path):
        """store 未注入：仍排除幻影，跳过告警、降级 logger.warning。"""
        root = tmp_path / "proj"
        root.mkdir()
        run_id = "impl-sig-phantom-1790244006"
        _signal_failed_run(root, run_id)
        _make_metric_log(root, {run_id: "success"})

        logger = _FakeLogger()
        samples = collect_failed_run_samples(
            root, datetime(2000, 1, 1, 0, 0).astimezone(), store=None, logger=logger
        )
        assert samples == []
        assert any("幻影" in w for w in logger.warnings)

    def test_stats_failed_count_consistent_with_samples(self, tmp_path):
        """混合窗口：失败计数与样本列表口径一致（marker/真失败计入，幻影两处皆除）。"""
        root = tmp_path / "proj"
        root.mkdir()
        # 1. marker 抓取（terminal=success，照常计失败）
        _make_run(root, "impl-mix-marker-1790244010", [
            _line(type="result", result="预算已耗尽，零交付", num_turns=2),
        ])
        # 2. signal 幻影（terminal=success，守卫排除）
        _signal_failed_run(root, "impl-mix-phantom-1790244011")
        # 3. signal 但 daemon 终态 error（真实失败，守卫不改判）
        _signal_failed_run(root, "impl-mix-real-1790244012")
        # 4. 干净成功 run（无指标记录）
        _make_run(root, "impl-mix-ok-1790244013", [
            _line(type="result", result="任务完成，验证通过", num_turns=4),
        ])
        _make_metric_log(root, {
            "impl-mix-marker-1790244010": "success",
            "impl-mix-phantom-1790244011": "success",
            "impl-mix-real-1790244012": "error",
        })

        store = _FakeStore()
        stats = collect_runs_stats(root, datetime(2000, 1, 1, 0, 0).astimezone())
        assert stats["total"] == 4
        assert stats["failed"] == 2  # marker 抓取 + error 终态真实失败
        assert stats["succeeded"] == 2  # 干净成功 + 幻影改计

        samples = collect_failed_run_samples(root, datetime(2000, 1, 1, 0, 0).astimezone(), store=store)
        assert {s["run_id"] for s in samples} == {
            "impl-mix-marker-1790244010",
            "impl-mix-real-1790244012",
        }
        assert {s["run_id"] for s in samples}.isdisjoint({"impl-mix-phantom-1790244011"})
        # 幻影 run 恰产出一条告警；marker/真失败不产出
        assert len(store.appended) == 1
        assert store.appended[0]["evidence"].startswith("run_id=impl-mix-phantom-1790244011")


class TestLoadRunMetricAccessor:
    """2.1：run_metrics 指标公共访问器（主日志 / 轮转回退 / attempt 后缀对齐）。"""

    def test_primary_rotated_and_miss(self, tmp_path):
        root = tmp_path / "proj"
        root.mkdir()
        _make_metric_log(root, {"impl-pri-1790244030": "success"})
        _make_metric_log(root, {"impl-rot-1790244031": "error"}, name="fenixd.log.1")

        assert load_run_metric(root, "impl-pri-1790244030")["terminal"] == "success"
        # 主日志未命中 → 轮转回退命中
        assert load_run_metric(root, "impl-rot-1790244031")["terminal"] == "error"
        # 两处均未命中 → None（索引缺失维持现状的读源契约）
        assert load_run_metric(root, "impl-missing-1790244032") is None

    def test_attempt_suffix_stripped(self, tmp_path):
        root = tmp_path / "proj"
        root.mkdir()
        _make_metric_log(root, {"impl-sfx-1790244033": "success"})
        assert load_run_metric(root, "impl-sfx-1790244033-a1")["terminal"] == "success"
        assert load_run_metric(root, "impl-sfx-1790244033-a2-r1")["terminal"] == "success"
        assert load_run_metric(root, "") is None
        assert load_run_metric(root, "impl-sfx-1790244033") is not None
