"""tests/test_code_review_429_throttle.py — 审查子代理 429 节流与退避（evo-code-review-subagent-429-throttle）

覆盖 task 3.1：
- 未显式配置时在飞上限取 2（ConfigLoader 缺省 + 显式配置不受影响 + 脏值回退）
- prompt_builder fail-open 回退取 2（ConfigLoader 导入失败形态）
- 审查 prompt 渲染含 429 处置条款全文（串行降档/指数退避/止损转自审/标记格式）
- 完成统计行标记解析回填 CodeReviewResult（含漏报保持缺省 + run_code_review 收尾接线）
- 终态 review_429_storm=true 触发恰好一条告警且重复终态不重复告警（含负控制）
- QualityPanel REPO_REVIEW_DEFAULT_CONCURRENCY=2（与 ConfigLoader 缺省同源）
"""

import json
import logging
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# /tmp 可能被外部清扫进程周期性清空：临时目录统一落仓库内 .history/tmp
#（gitignored，与 test_code_review.py 同款惯例），MUST NOT 改写全局 tempfile.tempdir。
_HISTORY_TMP = Path(__file__).resolve().parent.parent / ".history" / "tmp"
_HISTORY_TMP.mkdir(parents=True, exist_ok=True)


def _mkdtemp(prefix: str) -> str:
    return tempfile.mkdtemp(prefix=prefix, dir=str(_HISTORY_TMP))


def _mk_repo() -> Path:
    root = Path(_mkdtemp("storm-throttle-"))
    (root / ".fenix" / "code-review").mkdir(parents=True, exist_ok=True)
    (root / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
    return root


class TestConcurrencyDefaultTwo(unittest.TestCase):
    """未显式配置时在飞上限取 2（task 1.1 / spec「未显式配置时生效 2」）。"""

    def test_default_two_without_explicit_config(self):
        from core.config import ConfigLoader

        self.assertEqual(ConfigLoader.get_repo_code_review_concurrency({}), 2)
        self.assertEqual(
            ConfigLoader.get_repo_code_review_concurrency({"verify": {}}), 2)

    def test_explicit_config_unaffected(self):
        # 显式配置 4 → 按 4 生效（与引入本需求前一致）
        from core.config import ConfigLoader

        self.assertEqual(ConfigLoader.get_repo_code_review_concurrency(
            {"verify": {"repo_code_review_concurrency": 4}}), 4)

    def test_dirty_values_fall_back_to_two(self):
        # str/bool/非整值 float/≤0/None 一律回退缺省 2（fail-open 判据不变，
        # 仅缺省值降档）；整值浮点按整数接受（4.0 → 4，口径见 _positive_int_reader）
        from core.config import ConfigLoader

        for bad in ("8", 0, -2, True, False, 1.5, None):
            self.assertEqual(
                ConfigLoader.get_repo_code_review_concurrency(
                    {"verify": {"repo_code_review_concurrency": bad}}),
                2, f"bad={bad!r}")
        self.assertEqual(ConfigLoader.get_repo_code_review_concurrency(
            {"verify": {"repo_code_review_concurrency": 4.0}}), 4)


class TestPromptClauseAndFallback(unittest.TestCase):
    """审查 prompt 渲染：429 处置条款全文 + fail-open 回退 2（task 1.2/1.3）。"""

    RUN_ID = "code-review-1790210000"

    def _build(self, config=None):
        from core.agent_runner.prompt_builder import PromptBuilder

        pm = type("P", (), {
            "project_root": Path(_mkdtemp("storm-prompt-")),
            "config": config or {},
        })()
        return PromptBuilder(pm), pm.project_root

    def _detail(self, **extra):
        detail = {
            "manifest": ["core/a.py"],
            "review_window": "（全仓）",
            "out_path": "/tmp/x.jsonl",
        }
        detail.update(extra)
        return detail

    def test_prompt_contains_429_clause(self):
        builder, proot = self._build()
        try:
            prompt = builder._build_code_review_prompt(
                self.RUN_ID, self._detail(repo_concurrency=2))
        finally:
            shutil.rmtree(str(proot), ignore_errors=True)
        # 条款全文四要素：串行降档 / 指数退避 / 止损转自审 / 完成统计行标记格式
        self.assertIn("429 处置", prompt)
        self.assertIn("串行派发", prompt)
        self.assertIn("60s → 120s → 240s", prompt)
        self.assertIn("自行逐文件审查", prompt)
        self.assertIn("[review_429_storm=true; failed_shards=", prompt)
        # 条款以既有的并行扇出上限条款为邻（紧跟其后新增）
        self.assertIn("并行扇出上限", prompt)
        self.assertNotIn("{repo_concurrency}", prompt)  # 占位符零残留

    def test_default_renders_two_when_detail_missing(self):
        # detail 未携带 repo_concurrency 且 pm.config 无显式配置 → 读取器缺省 2
        builder, proot = self._build()
        try:
            prompt = builder._build_code_review_prompt(
                self.RUN_ID, self._detail())
        finally:
            shutil.rmtree(str(proot), ignore_errors=True)
        self.assertIn("MUST ≤ `2`", prompt)

    def test_import_failopen_falls_back_to_two(self):
        # ConfigLoader 导入失败（fail-open 形态）→ 硬编码回退值 2（与读取器缺省一致）
        builder, proot = self._build()
        saved = sys.modules.get("core.config")
        sys.modules["core.config"] = None  # from-import 将抛 ImportError
        try:
            prompt = builder._build_code_review_prompt(
                self.RUN_ID, self._detail())
        finally:
            if saved is None:
                sys.modules.pop("core.config", None)
            else:
                sys.modules["core.config"] = saved
        shutil.rmtree(str(proot), ignore_errors=True)
        self.assertIn("MUST ≤ `2`", prompt)


class TestStormMarkerParsing(unittest.TestCase):
    """完成统计行风暴标记解析（task 2.1 纯函数面）。"""

    def test_marker_on_stats_line_parsed(self):
        from core.agent_runner.maintenance_runs import (
            _parse_review_429_storm_marker,
        )

        text = ("3 files reviewed -> .fenix/code-review/"
                "out-code-review-1.jsonl [review_429_storm=true; failed_shards=3]")
        self.assertEqual(_parse_review_429_storm_marker(text), (True, 3))

    def test_no_marker_keeps_defaults(self):
        from core.agent_runner.maintenance_runs import (
            _parse_review_429_storm_marker,
        )

        self.assertEqual(
            _parse_review_429_storm_marker("5 files reviewed -> out.jsonl"),
            (False, 0))
        self.assertEqual(_parse_review_429_storm_marker(""), (False, 0))

    def test_non_true_storm_value_not_matched(self):
        # 契约只定义 true 字面量：其它值视为未标记（缺省口径优先，不产生假阳性）
        from core.agent_runner.maintenance_runs import (
            _parse_review_429_storm_marker,
        )

        self.assertEqual(
            _parse_review_429_storm_marker(
                "x [review_429_storm=false; failed_shards=2]"),
            (False, 0))

    def test_result_fields_default_on_silence(self):
        # run 主体漏报 → CodeReviewResult 保持缺省 False/0
        from core.agent_runner.result_gate import CodeReviewResult

        result = CodeReviewResult(run_id="r1")
        self.assertFalse(result.review_429_storm)
        self.assertEqual(result.failed_shards, 0)

    def test_result_fields_wired(self):
        from core.agent_runner.result_gate import CodeReviewResult

        result = CodeReviewResult(run_id="r1", review_429_storm=True,
                                  failed_shards=3)
        self.assertTrue(result.review_429_storm)
        self.assertEqual(result.failed_shards, 3)


class _RecLogger:
    """记录式 logger 替身（车道收尾以 ``logger.<level>(tag, message)`` 双参调用，
    stdlib logging 形态不同——与 stall 车道测试同款惯例）。"""

    def __init__(self):
        self.records = []

    def debug(self, tag, message):
        self.records.append(f"DEBUG {tag} {message}")

    def info(self, tag, message):
        self.records.append(f"INFO {tag} {message}")

    def warning(self, tag, message):
        self.records.append(f"WARNING {tag} {message}")

    def error(self, tag, message):
        self.records.append(f"ERROR {tag} {message}")

    def has(self, keyword):
        return any(keyword in r for r in self.records)


class _StormRunner:
    """run_code_review 收尾链路最小 runner 替身（对齐 stall 车道 _CloseoutRunner 形态）。

    mode="success"：写产物 + 正常返回（output 可携带完成统计行与风暴标记）；
    mode="die"：写产物后抛 429 异常（run_ok=False，账户被打杀形态）。
    """

    def __init__(self, proot, run_id, output="2 files reviewed -> out.jsonl",
                 out_rows=None, mode="success"):
        self.project_root = Path(proot)
        self.logger = _RecLogger()
        self.config = {}
        self._run_id = run_id
        self._output = output
        self._out_rows = out_rows if out_rows is not None else [
            {"file": "src/a.py", "findings": []}]
        self._mode = mode

    def _unique_code_review_run_id(self):
        return self._run_id

    def _build_prompt(self, run_id, agent_type, detail=None):
        return "prompt"

    def _get_agent_model_assignment(self, name):
        return None

    def _get_admin_model(self):
        return "test-model"

    def _write_out(self):
        path = self.project_root / ".fenix" / "code-review" / f"out-{self._run_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        content = "".join(
            json.dumps(r, ensure_ascii=False) + "\n" for r in self._out_rows)
        path.write_text(content, encoding="utf-8")

    def _read_code_review_out(self, project_root, run_id):
        # 委托模块函数单源实现（聚合口径：分片 + 主产物，按 file 去重）
        from core.agent_runner.maintenance_runs import _read_code_review_out

        return _read_code_review_out(self, project_root, run_id)

    def _run_agent(self, prompt, root, run_id, model_override, env_overrides,
                   max_turns=None, spec_name=None, agent_type=None,
                   task_progress_snapshot=None):
        self._write_out()
        if self._mode == "die":
            raise RuntimeError(
                "API Error: Request rejected (429) · rate limit exceeded")
        # 正常返回 5 元组（末位 stall stats 零样本，不触发 stall 意图）
        return (self._output, 3, "session", {}, {"rounds": 1, "stalls": 0, "max": None})

    def _ratelimit_redispatch_on_terminal(self, run_id, error, provider_name,
                                          spec_name, api_error_status=None,
                                          result_text="", chain_len=None,
                                          failed_candidates=None):
        return None

    def _accumulate_code_review_tokens(self, run_id, usage_info):
        return None

    def _extract_usage_info(self, x):
        return {}


class TestRunCodeReviewStormBackfill(unittest.TestCase):
    """run_code_review 收尾接线（task 2.1）：标记解析回填 + 漏报保持缺省。"""

    def setUp(self):
        self.proot = _mk_repo()

    def tearDown(self):
        shutil.rmtree(str(self.proot), ignore_errors=True)

    def _run(self, runner):
        from core.agent_runner.maintenance_runs import run_code_review

        return run_code_review(
            runner, ["src/a.py"], review_kind="scheduled",
            window_start=None, scope="full")

    def test_storm_marker_backfilled_on_success(self):
        stats_line = ("1 files reviewed -> .fenix/code-review/"
                      "out-code-review-s1.jsonl "
                      "[review_429_storm=true; failed_shards=3]")
        runner = _StormRunner(self.proot, "code-review-s1", output=stats_line)
        result = self._run(runner)
        self.assertTrue(result.success)
        self.assertTrue(result.review_429_storm)
        self.assertEqual(result.failed_shards, 3)

    def test_missing_marker_keeps_defaults_on_success(self):
        runner = _StormRunner(self.proot, "code-review-s2")
        result = self._run(runner)
        self.assertTrue(result.success)
        self.assertFalse(result.review_429_storm, "漏报不产生假阳性")
        self.assertEqual(result.failed_shards, 0)

    def test_run_killed_by_429_keeps_defaults(self):
        # run 被打杀（not run_ok）：风暴标记无从产生，字段保持缺省
        runner = _StormRunner(self.proot, "code-review-s3", mode="die")
        result = self._run(runner)
        self.assertFalse(result.success)
        self.assertFalse(result.review_429_storm)
        self.assertEqual(result.failed_shards, 0)


class TestStormAlertConsumption(unittest.TestCase):
    """终态风暴标记的告警消费（task 2.2）：恰好一条 + 同 run 去重 + 负控制。"""

    def setUp(self):
        self.proot = _mk_repo()
        from core.admin_monitor import AdminMonitor

        self.monitor = AdminMonitor(
            {}, None, str(self.proot), logging.getLogger("test-storm-alert"),
            agent_runner=None)

    def tearDown(self):
        shutil.rmtree(str(self.proot), ignore_errors=True)

    def _result(self, **kw):
        from core.agent_runner.result_gate import CodeReviewResult

        params = dict(run_id="code-review-a1", success=True,
                      review_429_storm=True, failed_shards=3)
        params.update(kw)
        return CodeReviewResult(**params)

    def _storm_records(self):
        return [
            r for r in self.monitor.store.read_records()
            if r.get("kind") == "signal"
            and r.get("signal_type") == "review_429_storm"
        ]

    def test_storm_result_emits_exactly_one_alert_with_dedup(self):
        self.monitor._emit_review_429_storm_alert(self._result())
        self.monitor._emit_review_429_storm_alert(self._result())  # 重复终态
        recs = self._storm_records()
        self.assertEqual(len(recs), 1, "同 run 重复终态仅刷 last_seen 不新增")
        rec = recs[0]
        self.assertEqual(rec.get("severity"), "major")
        evidence = rec.get("evidence") or ""
        self.assertIn("failed_shards=3", evidence, "evidence 含死亡分片数")
        self.assertIn("timeline=", evidence, "evidence 含时间线")
        action = rec.get("recommended_action") or ""
        self.assertIn(
            "检查同账户并发：注意多项目全仓审查窗口重叠，建议错峰排程",
            action, "建议文案含 SPEC 固定句")

    def test_different_run_gets_own_record(self):
        self.monitor._emit_review_429_storm_alert(self._result())
        self.monitor._emit_review_429_storm_alert(
            self._result(run_id="code-review-a2"))
        self.assertEqual(len(self._storm_records()), 2, "不同 run 各自成条")

    def test_negative_controls_no_alert(self):
        # 无标记（缺省 False）→ 零告警；run 被打杀（success=False）→ 零告警
        self.monitor._emit_review_429_storm_alert(
            self._result(review_429_storm=False))
        self.monitor._emit_review_429_storm_alert(self._result(success=False))
        self.assertEqual(self._storm_records(), [])


class TestFrontendDefaultConstant(unittest.TestCase):
    """QualityPanel REPO_REVIEW_DEFAULT_CONCURRENCY 与 ConfigLoader 缺省同源取 2（task 1.4）。"""

    def test_frontend_default_two_and_same_source_as_configloader(self):
        from core.config import ConfigLoader

        p = (Path(__file__).resolve().parent.parent
             / "core/dashboard/static/src/pages/settings/components/QualityPanel.tsx")
        text = p.read_text(encoding="utf-8")
        match = re.search(r"REPO_REVIEW_DEFAULT_CONCURRENCY\s*=\s*(\d+)", text)
        self.assertIsNotNone(match, "缺省常量声明存在")
        frontend_val = int(match.group(1))
        backend_val = ConfigLoader.get_repo_code_review_concurrency({})
        self.assertEqual(frontend_val, 2, "前端缺省常量=2")
        self.assertEqual(
            frontend_val, backend_val, "与 ConfigLoader 缺省同源（不漂移）")


if __name__ == "__main__":
    unittest.main()
