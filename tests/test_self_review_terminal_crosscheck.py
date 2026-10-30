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
  （warning、不自动 handled）、索引缺失维持现状、统计与样本口径一致。
- evo-self-review-phantom-failure-dual-source-veto 1.1/1.2/3.1/3.2：
  守卫扩界为「daemon 终态权威裁决」——error 终态 Exit code 形态与
  marker= 失败词复述同纳双源否决（terminal=success 改计 success 并写
  self_review_phantom_failure 告警），查无账面行/daemon=error 反例保守
  保持 failed；原「marker= 与 error 终态 MUST NOT 纳入守卫」pin 断言
  由本轮翻转取代。
- evo-self-review-phantom-failure-dual-source-veto 2.1：salvage/产物直读
  路径指标透传（turns ← context metrics 行、cost ← 档案 result 事件）。
"""

import json
import os
import types
from datetime import datetime

import pytest

from core.agent_runner.maintenance_runs import _backfill_salvage_run_metrics
from core.dashboard.data.runs import RUN_STALE_SECONDS, load_run_metric
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

    def test_marker_failed_terminal_success_vetoed_and_alerted(self, tmp_path):
        """marker= 命中 × terminal=success → 改计 success 并写幻影告警
        （evo-self-review-phantom-failure-dual-source-veto 1.2/3.2 同轮翻转：
        原「假成功抓取仍计失败、无幻影告警」pin 由 daemon 终态权威裁决
        取代——marker= 失败词复述同为幻影源）。"""
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
        assert samples == []
        assert len(store.appended) == 1
        alert = store.appended[0]
        assert alert["kind"] == "escalation"
        assert alert["signal_type"] == "self_review_phantom_failure"
        assert alert["severity"] == "warning"
        assert "marker=预算已耗尽" in alert["evidence"]
        assert store.handled == []  # 不自动 mark_handled

        # 统计侧同步：幻影不计失败统计（改计 succeeded）
        stats = collect_runs_stats(root, datetime(2000, 1, 1, 0, 0).astimezone())
        assert stats["failed"] == 0
        assert stats["succeeded"] == 1

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
        """混合窗口：失败计数与样本列表口径一致（真失败计入，幻影两处皆除）。

        evo-self-review-phantom-failure-dual-source-veto 3.2 同轮翻转：marker
        抓取（terminal=success）由「照常计失败」改为守卫否决改计 success。
        """
        root = tmp_path / "proj"
        root.mkdir()
        # 1. marker 抓取（terminal=success，扩界后守卫否决改计 success）
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
        assert stats["failed"] == 1  # 仅 error 终态真实失败保持计数
        assert stats["succeeded"] == 3  # 干净成功 + signal 幻影 + marker 否决改计

        samples = collect_failed_run_samples(root, datetime(2000, 1, 1, 0, 0).astimezone(), store=store)
        assert {s["run_id"] for s in samples} == {"impl-mix-real-1790244012"}
        assert {s["run_id"] for s in samples}.isdisjoint({
            "impl-mix-phantom-1790244011",
            "impl-mix-marker-1790244010",
        })
        # 幻影两源各产出一条告警（signal 幻影 + marker 否决）；真失败不产出
        assert len(store.appended) == 2
        assert {a["evidence"].split()[0] for a in store.appended} == {
            "run_id=impl-mix-phantom-1790244011",
            "run_id=impl-mix-marker-1790244010",
        }


def _error_terminal_run(root, run_id: str):
    """error 终态夹具（evo-1792692791 实拍尾行形态）：CLI 死于收尾交换、
    产物直读按成功落地（terminal=success），转录尾行为
    {"type":"error","error":"Exit code: 1","exit_code":1}。"""
    return _make_run(root, run_id, [
        _line(type="system", subtype="start"),
        _line(type="assistant", message={"role": "assistant",
                                         "content": [{"type": "text", "text": "分析进行中"}]}),
        _line(type="error", error="Exit code: 1", exit_code=1),
    ])


class TestDualSourceVetoExpansion:
    """evo-self-review-phantom-failure-dual-source-veto 3.1/3.2：守卫扩界。

    error 终态 Exit code 形态与 marker= 失败词复述同纳双源否决（daemon
    终态权威裁决：terminal=success 改计 success 并写幻影告警）；查无账面
    行与 daemon=error 反例保守保持 failed（宁可不拦不可误伤）。
    """

    def test_error_exit_code_terminal_success_vetoed_and_alerted(self, tmp_path):
        """3.1：error 终态（Exit code: 1）× terminal=success → 改计 success + 幻影告警。"""
        root = tmp_path / "proj"
        root.mkdir()
        run_id = "evo-1792692791"
        _error_terminal_run(root, run_id)
        _make_metric_log(root, {run_id: "success"})

        # 分类侧：error 分支判 failed，detail 为 Exit code 前缀实拍形态
        p = root / ".fenix" / "runs" / f"{run_id}.jsonl"
        category, detail = _classify_run(run_id, _read_run_tail(p, 3))
        assert category == "failed"
        assert detail == "Exit code: 1"

        store = _FakeStore()
        samples = collect_failed_run_samples(root, datetime(2000, 1, 1, 0, 0).astimezone(), store=store)
        assert samples == []
        assert len(store.appended) == 1
        alert = store.appended[0]
        assert alert["signal_type"] == "self_review_phantom_failure"
        assert alert["severity"] == "warning"
        assert f"detail={detail}" in alert["evidence"]
        assert store.handled == []  # 不自动 mark_handled

        # 统计侧同步：改计 succeeded
        stats = collect_runs_stats(root, datetime(2000, 1, 1, 0, 0).astimezone())
        assert stats["total"] == 1
        assert stats["failed"] == 0
        assert stats["succeeded"] == 1

    def test_error_exit_code_missing_metric_keeps_failed(self, tmp_path):
        """3.2：error 终态 + 查无账面行 → 保守保持 failed，不写告警。"""
        root = tmp_path / "proj"
        root.mkdir()
        run_id = "evo-nolog-1792692792"
        _error_terminal_run(root, run_id)
        # 不写任何指标日志（索引缺失形态）

        store = _FakeStore()
        samples = collect_failed_run_samples(root, datetime(2000, 1, 1, 0, 0).astimezone(), store=store)
        assert [s["run_id"] for s in samples] == [run_id]
        assert samples[0]["detail"] == "Exit code: 1"
        assert store.appended == []

        stats = collect_runs_stats(root, datetime(2000, 1, 1, 0, 0).astimezone())
        assert stats["failed"] == 1
        assert stats["succeeded"] == 0

    def test_error_exit_code_daemon_error_keeps_failed(self, tmp_path):
        """3.2：daemon terminal=error 反例 → 真实失败保持 failed，不写幻影告警。"""
        root = tmp_path / "proj"
        root.mkdir()
        run_id = "evo-real-1792692793"
        _error_terminal_run(root, run_id)
        _make_metric_log(root, {run_id: "error"})

        store = _FakeStore()
        samples = collect_failed_run_samples(root, datetime(2000, 1, 1, 0, 0).astimezone(), store=store)
        assert [s["run_id"] for s in samples] == [run_id]
        assert store.appended == []

        stats = collect_runs_stats(root, datetime(2000, 1, 1, 0, 0).astimezone())
        assert stats["failed"] == 1
        assert stats["succeeded"] == 0

    def test_error_terminal_arbitrary_text_not_matched(self, tmp_path):
        """MUST NOT 空泛匹配任意 error 文本：非 Exit code 前缀的 error detail
        即使 terminal=success 也不改判（形态锚定约束）。"""
        root = tmp_path / "proj"
        root.mkdir()
        run_id = "evo-arb-1792692794"
        _make_run(root, run_id, [
            _line(type="system", subtype="start"),
            _line(type="error", error="provider 429 rate limited"),
        ])
        _make_metric_log(root, {run_id: "success"})

        store = _FakeStore()
        samples = collect_failed_run_samples(root, datetime(2000, 1, 1, 0, 0).astimezone(), store=store)
        assert [s["run_id"] for s in samples] == [run_id]
        assert samples[0]["detail"] == "provider 429 rate limited"
        assert store.appended == []


class _BackfillLogger:
    """logger 形状替身：记录 debug 调用（透传查无留痕通道）。"""

    def __init__(self):
        self.debugs = []

    def debug(self, component, message):
        self.debugs.append(str(message))

    def info(self, component, message):
        pass

    def warning(self, component, message):
        pass

    def error(self, component, message):
        pass


class TestSalvageMetricsBackfill:
    """2.1：产物直读/salvage 登记路径分源回填真实 turns 与 total_cost_usd。

    场景「指标行与档案侧一致」：档案 result 事件含 total_cost_usd、daemon
    日志含该 run 的 context metrics 行 → 回填值逐字段相等；任一源查无保持
    现状（turns=0/cost=None）并 DEBUG 留痕；MUST NOT 经 load_run_metric
    合并索引取 turns（lane 行 turns=0 后写会覆盖 context 行 turns=197）。
    """

    @staticmethod
    def _write_context_metrics_log(root, run_id: str, turns: int,
                                   name: str = "fenixd.log"):
        """形态对齐 runner._run_agent 收尾的 context metrics 行（daemon 日志）。"""
        log = root / ".fenix" / "logs" / name
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            json.dumps({
                "timestamp": "2026-10-22T18:44:17.146155Z",
                "level": "INFO",
                "component": "agent_runner",
                "message": (
                    f"context metrics: turns={turns} inp=48000 peak=90000 "
                    "per_turn=4000 cr=120000 tools=210 text_turns=21"
                ),
                "context": {
                    "metric_type": "run_metrics",
                    "run_id": run_id,
                    "turns": turns,
                    "text_turns": 21,
                },
            }, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _write_transcript_with_result_event(root, run_id: str, cost_usd):
        """档案转录：result 终态事件最后落盘（文件最后一行，runner 契约）。"""
        _make_run(root, run_id, [
            _line(type="system", subtype="start"),
            _line(type="assistant", message="analyzing"),
            _line(type="result", result="收工", num_turns=21,
                  total_cost_usd=cost_usd, is_error=False, subtype="success"),
        ])

    def test_backfill_turns_and_cost_from_sources(self, tmp_path):
        """双源齐备：turns=197 ← context metrics 行、cost ← 档案 result 事件。"""
        root = tmp_path / "proj"
        root.mkdir()
        run_id = "evo-1792692791"
        self._write_context_metrics_log(root, run_id, 197)
        self._write_transcript_with_result_event(root, run_id, 6.756237)
        logger = _BackfillLogger()
        runner = types.SimpleNamespace(project_root=root, logger=logger)

        turns, usage = _backfill_salvage_run_metrics(runner, run_id, 0, {})

        assert turns == 197
        assert usage["cost_usd"] == pytest.approx(6.756237)
        assert logger.debugs == []  # 双源命中无留痕

    def test_backfill_misses_keep_zero_and_debug(self, tmp_path):
        """双源查无：保持 turns=0/cost=None 并 DEBUG 留痕，不抛异常。"""
        root = tmp_path / "proj"
        root.mkdir()
        run_id = "evo-nosrc-1792692795"
        logger = _BackfillLogger()
        runner = types.SimpleNamespace(project_root=root, logger=logger)

        turns, usage = _backfill_salvage_run_metrics(runner, run_id, 0, {})

        assert turns == 0
        assert usage.get("cost_usd") is None
        assert len(logger.debugs) == 2
        assert any("turns" in d for d in logger.debugs)
        assert any("total_cost_usd" in d for d in logger.debugs)

    def test_backfill_turns_rotated_log_fallback(self, tmp_path):
        """主日志查无 → .fenixd.log.1 轮转回退命中（约定同 load_run_metric）；
        档案 result 事件 total_cost_usd=null → cost 保持 None。"""
        root = tmp_path / "proj"
        root.mkdir()
        run_id = "evo-rot-1792692796"
        self._write_context_metrics_log(root, run_id, 197, name="fenixd.log.1")
        self._write_transcript_with_result_event(root, run_id, None)
        runner = types.SimpleNamespace(project_root=root, logger=_BackfillLogger())

        turns, usage = _backfill_salvage_run_metrics(runner, run_id, 0, {})

        assert turns == 197
        assert usage.get("cost_usd") is None

    def test_normal_run_not_touched(self, tmp_path):
        """正常收尾（turns>0 且 cost 已归）不触发任何读盘回填。"""
        root = tmp_path / "proj"  # 无日志、无转录
        root.mkdir()
        logger = _BackfillLogger()
        runner = types.SimpleNamespace(project_root=root, logger=logger)

        turns, usage = _backfill_salvage_run_metrics(
            runner, "evo-normal-1792692797", 12, {"cost_usd": 0.5}
        )

        assert turns == 12
        assert usage["cost_usd"] == 0.5
        assert logger.debugs == []


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


# ═══════════════════════════════════════════════════════════════════
# evo-fix-self-review-phantom-running：新桶位计数与残余 stale 对账
# ═══════════════════════════════════════════════════════════════════


class TestNewBucketMixedWindow:
    """3.2：collect_runs_stats 混合夹具（result/superseded/ended/running 各一）。

    counts 初始 dict 缺新键即 counts[category] += 1 KeyError（本条最大回归点）；
    失败样本列表不含 superseded/ended/running 类 run（口径锁定）。
    """

    def test_mixed_window_counts_and_no_keyerror(self, tmp_path):
        root = tmp_path / "proj"
        root.mkdir()
        # 1. result 成功
        _make_run(root, "impl-new-ok-1791500000", [
            _line(type="result", result="任务完成，验证通过", num_turns=2),
        ])
        # 2. superseded（原地重试弃置件：末两行 transient_retry + superseded 实拍形态）
        _make_run(root, "impl-new-sup-1791500001-a1", [
            _line(type="transient_retry", backoff_seconds=5, retry_number=1),
            _line(type="superseded"),
        ])
        # 3. ended（取消路径最后落盘）
        _make_run(root, "impl-new-end-1791500002", [
            _line(type="system", subtype="tool_call", tool="Bash", argument="pytest"),
            _line(type="cancelled"),
        ])
        # 4. running（新鲜 mtime，无终态）
        _make_run(root, "impl-new-run-1791500003", [
            _line(type="system", subtype="start"),
            _line(type="assistant", message="in flight"),
        ])

        stats = collect_runs_stats(root, datetime(2000, 1, 1, 0, 0).astimezone())
        assert stats["total"] == 4
        assert stats["succeeded"] == 1
        assert stats["superseded"] == 1  # 新桶落计数无 KeyError
        assert stats["ended"] == 1
        assert stats["running"] == 1
        assert stats["stale"] == 0
        assert stats["failed"] == 0

        # 失败样本不含 superseded/ended/running 类 run
        samples = collect_failed_run_samples(root, datetime(2000, 1, 1, 0, 0).astimezone())
        assert samples == []


class TestStaleReconciliation:
    """3.3：残余无终态的 stale 对账四态（phantom-running-guard D4）。

    mtime 以 os.utime 注入控制（测试不 sleep）；window_end 显式贯穿（对齐
    生产调度侧「一次冻结、全节共用」契约，夹具落盘后冻结）。对账仅触达
    running 判定的 run；「宁可不拦不可误伤」：数据缺失不按成功提升。
    """

    @staticmethod
    def _running_run(root, run_id):
        return _make_run(root, run_id, [
            _line(type="system", subtype="start"),
            _line(type="assistant", message="in flight"),
        ])

    @staticmethod
    def _backdate(p, window_end, seconds_past_stale=60):
        mtime = window_end.timestamp() - RUN_STALE_SECONDS - seconds_past_stale
        os.utime(p, (mtime, mtime))

    def test_stale_mtime_without_terminal_counts_stale(self, tmp_path):
        """mtime 陈旧 + 指标索引查无（fenixd.log 无该 run 终态，_run_terminal_success
        返回 None=未返回 True）→ stale（无终态残留），不维持 running。"""
        root = tmp_path / "proj"
        root.mkdir()
        p = self._running_run(root, "impl-stale-orphan")
        window_end = datetime.now().astimezone()
        self._backdate(p, window_end)

        stats = collect_runs_stats(
            root, datetime(2000, 1, 1, 0, 0).astimezone(), window_end=window_end
        )
        assert stats["stale"] == 1
        assert stats["running"] == 0
        assert stats["succeeded"] == 0
        assert stats["failed"] == 0

    def test_stale_mtime_non_success_terminal_still_stale(self, tmp_path):
        """mtime 陈旧 + 指标 terminal=failure（查得非 success 终态，False 路径）
        → 同走 stale 通道：MUST NOT 按成功提升计 succeeded、MUST NOT 改计
        failed（失败样本归因以产物 marker/信号为源，防计数与失败样本分叉）。"""
        root = tmp_path / "proj"
        root.mkdir()
        run_id = "impl-stale-failure"
        p = self._running_run(root, run_id)
        _make_metric_log(root, {run_id: "failure"})
        window_end = datetime.now().astimezone()
        self._backdate(p, window_end)

        stats = collect_runs_stats(
            root, datetime(2000, 1, 1, 0, 0).astimezone(), window_end=window_end
        )
        assert stats["stale"] == 1
        assert stats["failed"] == 0
        assert stats["succeeded"] == 0

        # 失败样本同样不入选（stale 不入失败样本口径锁定）
        samples = collect_failed_run_samples(
            root, datetime(2000, 1, 1, 0, 0).astimezone(), window_end=window_end
        )
        assert samples == []

    def test_stale_mtime_terminal_success_promotes_succeeded(self, tmp_path):
        """mtime 陈旧 + 指标 terminal=success → succeeded（run 实际收尾、产物
        断尾——daemon 崩溃截断收尾形态），不混入在跑也不落 stale。"""
        root = tmp_path / "proj"
        root.mkdir()
        run_id = "impl-stale-but-done"
        p = self._running_run(root, run_id)
        _make_metric_log(root, {run_id: "success"})
        window_end = datetime.now().astimezone()
        self._backdate(p, window_end)

        stats = collect_runs_stats(
            root, datetime(2000, 1, 1, 0, 0).astimezone(), window_end=window_end
        )
        assert stats["succeeded"] == 1
        assert stats["stale"] == 0
        assert stats["running"] == 0

    def test_fresh_mtime_without_terminal_stays_running(self, tmp_path):
        """mtime 新鲜（刚写入）+ 无终态 → 维持 running 不改判（真实在跑或
        近瞬状态，宁可不拦不可误伤）。"""
        root = tmp_path / "proj"
        root.mkdir()
        self._running_run(root, "impl-fresh-running")
        window_end = datetime.now().astimezone()

        stats = collect_runs_stats(
            root, datetime(2000, 1, 1, 0, 0).astimezone(), window_end=window_end
        )
        assert stats["running"] == 1
        assert stats["stale"] == 0
        assert stats["succeeded"] == 0
