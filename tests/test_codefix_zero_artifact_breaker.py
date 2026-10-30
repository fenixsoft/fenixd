"""test_codefix_zero_artifact_breaker.py — code-fix 零产物止损测试

evo-codefix-zero-artifact-stop-loss：
- 1.1 信封类别透出：产物硬门零产物失败（run 正常退出但 out 缺失/零有效行）
  的 CodeFixResult 信封携带 failure_category="artifact_missing"、conn_error
  恒 False；非硬门失败（api_error/异常路径）信封 failure_category 保持缺省
  空串，既有语义逐位不变。
- 1.2/2.1/2.2 止损状态机：同批次指纹 artifact_missing 连败 1 次不触发
  （chain_skipped 瞬态重试行为不变）、连败 2 次即止损（指纹入进程内止损
  跳过集、下一链选批不再选中、恰发一条 WARNING 留痕含指纹/连败次数/最后
  失败 run id）、其他失败类别不计数、止损不影响其余指纹。
- 3.2 派发契约测试：按字面子串断言 agents/code-fix.md 含同步派发契约条款
  （「回合结束 = run 终止」「run_in_background: false」
  「MUST NOT 以「等待完成通知」」），防模板漂移（参照
  tests/test_prompt_lane_efficiency_sections.py 先例形态）。

MUST NOT 真跑 agent——全部用 fake runner / 临时目录（复用 test_code_fix 的
_FakeRunner/_FakeWM 夹具，对齐既有 code-fix 链路测试形态）。
"""

import types as _t
import unittest
from pathlib import Path

from test_code_fix import (
    _CFG_ON,
    _FakeRunner,
    _item,
    _make_project_root,
    _make_runner,
    _write_items,
    _write_verify_yaml,
)

ARTIFACT_MISSING = "artifact_missing"


class _RecordingLogger:
    """捕获日志的 fake logger（编排器 _log 形如 logger.warning(tag, msg)）。"""

    def __init__(self):
        self.records = []

    def debug(self, tag, msg, extra=None):
        self.records.append(("debug", tag, msg))

    def info(self, tag, msg, extra=None):
        self.records.append(("info", tag, msg))

    def warning(self, tag, msg, extra=None):
        self.records.append(("warning", tag, msg))

    def error(self, tag, msg, extra=None):
        self.records.append(("error", tag, msg))


class _EnvelopeFailRunner(_FakeRunner):
    """前 N 次 run_code_fix 以指定 failure_category 信封失败，其后走基类成功。

    ``fail_categories`` 逐 run 消费：第 i 次调用（1 基）i <= len 时返回带
    ``failure_category=fail_categories[i-1]`` 的失败信封，否则回落基类
    ``run_code_fix``（真实落 out 行 + git 提交，fix_statuses 默认全 fixed）
    ——成功路径合回核销，链正常收敛。
    """

    def __init__(self, project_root, fail_categories):
        super().__init__(project_root, fix_statuses=[["fixed"]])
        self._fail_categories = list(fail_categories)
        self.dispatched_ids = []   # 每次调用的条目 id 列表（选批指纹观测）
        self.envelopes = []        # 每次返回的失败信封（断言用）

    def run_code_fix(self, worktree_root, items, run_id=None, failure_summary=""):
        self.dispatched_ids.append([str(i["item_id"]) for i in items])
        no = len(self.dispatched_ids)
        if no <= len(self._fail_categories):
            rid = run_id or f"code-fix-zeroart-{no}"
            env = _t.SimpleNamespace(
                run_id=rid, success=False, fixed=0, skipped=0,
                error=f"exit 0 但产物缺失（code-fix 产物硬门）: run={rid}",
                output="", api_timeout=False, exit_code=None,
                stderr_summary="", conn_error=False, result_text="",
                failure_category=self._fail_categories[no - 1],
            )
            self.envelopes.append(env)
            return env
        return super().run_code_fix(
            worktree_root, items, run_id=run_id, failure_summary=failure_summary
        )


def _orch(runner, proot, logger=None, batch_size=None):
    """构造编排器（无 executor → checkpoint 同步自驱动整链）。"""
    from core.code_fix import CodeFixOrchestrator

    cfg = _CFG_ON
    if batch_size is not None:
        cfg = {"admin": {"code_review_fix": {
            "enabled": True, "batch_size": batch_size}}}
    return CodeFixOrchestrator(runner, proot, config=cfg, logger=logger)


def _run_chains(orch, n):
    """显式驱动 n 条链（生产形态：每链由外部节拍/full-scan 触发一次
    checkpoint——链内 chain_skipped 不重置，跨链重选靠新链启动）。"""
    for _ in range(n):
        orch.checkpoint()


def _stop_loss_warnings(logger) -> list:
    return [msg for level, _tag, msg in logger.records
            if level == "warning" and "零产物止损" in msg]


# ── 1.1 信封类别透出 ─────────────────────────────────────────────────


class TestEnvelopeFailureCategory(unittest.TestCase):
    """产物硬门零产物失败透出结构化类别；非硬门路径缺省空串零触碰。"""

    @staticmethod
    def _runner_with(proot, run_agent):
        runner = _make_runner(proot)
        runner._get_agent_model_assignment = lambda t: None
        runner._get_admin_model = lambda: "admin-model"
        runner._run_agent = run_agent
        return runner

    def test_gate_failure_carries_artifact_missing(self):
        """硬门零产物失败信封：success=False + failure_category + conn_error False。"""
        from core.agent_runner.maintenance_runs import run_code_fix

        def fake_agent(prompt, cwd, run_id, model, env, **kw):
            # run 正常退出但 out 缺失 → 产物硬门判零产物失败
            return ("done", 1, "sid", {}, {"rounds": 1, "stalls": 0, "max": 0.0})

        result = run_code_fix(
            self._runner_with(_make_project_root(), fake_agent),
            _make_project_root(), [_item("a")])
        self.assertFalse(result.success)
        self.assertEqual(
            result.failure_category, ARTIFACT_MISSING,
            "产物硬门零产物失败 MUST 携带 failure_category")
        self.assertFalse(
            result.conn_error, "硬门失败路径 conn_error 恒 False 的现状逐位保持")
        self.assertTrue(result.error, "error 沿用硬门既有 fail-closed 文案")

    def test_non_gate_failure_keeps_default_empty(self):
        """api_error/异常等既有失败路径（未触发硬门）failure_category 缺省空。"""
        from core.agent_runner.maintenance_runs import run_code_fix

        def fake_agent(prompt, cwd, run_id, model, env, **kw):
            raise RuntimeError("claude CLI failed: Exit code: 1")

        result = run_code_fix(
            self._runner_with(_make_project_root(), fake_agent),
            _make_project_root(), [_item("a")])
        self.assertFalse(result.success)
        self.assertEqual(
            result.failure_category, "",
            "非硬门失败 MUST NOT 携带类别标注（缺省空值）")
        self.assertIsNone(result.exit_code)

    def test_envelope_default_value(self):
        """新增字段带缺省值：未走硬门的既有构造点零触碰（缺省空串）。"""
        from core.agent_runner.result_gate import CodeFixResult

        self.assertEqual(CodeFixResult().failure_category, "")
        env = CodeFixResult(run_id="r", success=False, error="e")
        self.assertEqual(env.failure_category, "")


# ── 1.2/2.1/2.2 止损状态机 ───────────────────────────────────────────


class TestArtifactMissingBreaker(unittest.TestCase):
    """同指纹零产物止损：1 次不触发 / 2 次触发 / 其他类别不计数 / 触发后跳过留痕。"""

    def test_single_failure_transient_retry_unchanged(self):
        """Scenario「单次失败仍瞬态重试」：首次 artifact_missing 行为与现状
        逐位一致——chain_skipped 瞬态跳过、下一链重选同指纹、MUST NOT 止损。"""
        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        runner = _EnvelopeFailRunner(proot, [ARTIFACT_MISSING])  # 第 2 run 成功
        logger = _RecordingLogger()
        orch = _orch(runner, proot, logger=logger)

        _run_chains(orch, 2)  # 链 1 失败瞬态跳过；链 2 重选同指纹并成功收链

        fp = frozenset({"a"})
        self.assertEqual(orch._artifact_missing_streaks[fp]["count"], 1)
        self.assertNotIn(
            fp, orch._artifact_missing_skipped, "单次失败 MUST NOT 标记止损")
        # 瞬态重试行为不变：链 2 重选同指纹（未被止损排除）
        self.assertEqual(runner.dispatched_ids, [["a"], ["a"]])
        self.assertEqual(_stop_loss_warnings(logger), [])

    def test_second_failure_triggers_stop_loss(self):
        """Scenario「同指纹连败 2 次止损」：跨链连败 2 次（链 1 失败瞬态跳过
        收敛后，链 2 重选同指纹再次失败）→ 指纹入止损跳过集、下一链选批不再
        选中（停止重派）、恰发一条 WARNING 留痕。"""
        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        runner = _EnvelopeFailRunner(
            proot, [ARTIFACT_MISSING] * 5)  # 恒失败：止损后不再派发
        logger = _RecordingLogger()
        orch = _orch(runner, proot, logger=logger)

        _run_chains(orch, 3)  # 链 1/链 2 各失败一次；链 3 选批为空收敛

        fp = frozenset({"a"})
        self.assertIn(fp, orch._artifact_missing_skipped, "连败 2 次 MUST 止损")
        rec = orch._artifact_missing_streaks[fp]
        self.assertEqual(rec["count"], 2)
        self.assertTrue(rec["last_run_id"].startswith("code-fix-"))
        # 停止重派：恰好派发 2 次（链 1 + 链 2 重选），链 3 选批 MUST NOT 再选中
        self.assertEqual(
            runner.dispatched_ids, [["a"], ["a"]],
            "止损后 MUST NOT 再选中该指纹派发")
        # 恰发一条 WARNING，含指纹、连败次数、最后失败 run id
        warns = _stop_loss_warnings(logger)
        self.assertEqual(len(warns), 1, "止损 MUST 恰发一条 WARNING 留痕")
        self.assertIn("'a'", warns[0])
        self.assertIn("2", warns[0])
        self.assertIn(rec["last_run_id"], warns[0])

    def test_other_categories_do_not_count(self):
        """Scenario「其他失败类别不计数」：api_timeout / artifact_missing /
        api_error 先后发生 → 仅 artifact_missing 计 1，止损 MUST NOT 触发。"""
        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        runner = _EnvelopeFailRunner(
            proot, ["", ARTIFACT_MISSING, ""])  # 第 4 run 成功收链
        logger = _RecordingLogger()
        orch = _orch(runner, proot, logger=logger)

        _run_chains(orch, 2)
        # evo-align-codefix-skip-reason-enum 1.3 链级零进度护栏：连续 2 轮
        # 零核销链（含瞬态失败链，终局 rollup 口径统一）即熔断暂停自动重派
        # ——既有「瞬态失败跨链无限自动重试」语义按新护栏收窄：后续链经
        # 人工处置入口（override_enabled）解除后重派。护栏是投放闸，不改
        # 止损 streak 状态机，本用例的计数/不触发断言不受影响。
        from core.code_fix import read_progress
        self.assertTrue(
            read_progress(proot)["zero_progress_paused"],
            "连续 2 轮零核销链须熔断暂停（新护栏）")
        orch.checkpoint(override_enabled=True)  # 人工处置解除 → 第 3 链
        orch.checkpoint()                        # 第 4 链（成功收链）

        fp = frozenset({"a"})
        self.assertEqual(
            orch._artifact_missing_streaks[fp]["count"], 1,
            "仅 artifact_missing 计数")
        self.assertNotIn(fp, orch._artifact_missing_skipped, "MUST NOT 触发止损")
        self.assertEqual(_stop_loss_warnings(logger), [])
        # 三次失败全部重派（第 4 次成功收链；第 3 链经人工处置入口解除）
        self.assertEqual(len(runner.dispatched_ids), 4)

    def test_stop_loss_scoped_to_fingerprint(self):
        """Scenario「止损不影响其余指纹」：指纹 A 止损后，同调度周期内指纹 B
        的选批与派发不受影响（batch_size=1 分批：A 二次失败止损后，B 照常
        入选并成功核销）。"""
        proot = _make_project_root()
        _write_items(proot, {"a": _item("a"), "b": _item("b")})
        _write_verify_yaml(proot)
        runner = _EnvelopeFailRunner(
            proot, [ARTIFACT_MISSING, ARTIFACT_MISSING, ARTIFACT_MISSING])
        logger = _RecordingLogger()
        orch = _orch(runner, proot, logger=logger, batch_size=1)

        _run_chains(orch, 2)
        # 链 1：X 失败（{X}=1）→ 链内推进 Y 失败（{Y}=1）→ 选批为空收敛；
        # 链 2：重选 X 再失败（{X}=2 → 止损）→ 链内推进 Y 成功核销。
        # 派发序列 X→Y→X→Y，每批 batch_size=1。
        seq = [d[0] for d in runner.dispatched_ids]
        self.assertEqual(len(seq), 4, "派发序列：X→Y→X→Y")
        self.assertNotEqual(seq[0], seq[1], "链 1 内两指纹各自成批")
        self.assertEqual(seq[2], seq[0], "链 2 重选链 1 首个指纹")
        self.assertEqual(seq[3], seq[1], "X 止损后链内推进 Y")
        fp_x = frozenset(runner.dispatched_ids[0])
        fp_y = frozenset(runner.dispatched_ids[1])
        self.assertIn(fp_x, orch._artifact_missing_skipped, "连败 2 次 MUST 止损")
        self.assertNotIn(
            fp_y, orch._artifact_missing_skipped, "B 未触发 MUST NOT 连坐")
        self.assertEqual(orch._artifact_missing_streaks[fp_x]["count"], 2)
        self.assertEqual(orch._artifact_missing_streaks[fp_y]["count"], 1)
        # X 止损后链内仍推进 Y（Y 的选批与派发不受 A 止损影响）并成功核销
        from core.code_review import read_items
        y_id = sorted(fp_y)[0]
        self.assertEqual(read_items(proot)[y_id]["status"], "resolved")
        self.assertEqual(len(_stop_loss_warnings(logger)), 1)

    def test_stop_loss_item_ids_expand_and_block_selection(self):
        """2.2：止损指纹展开为条目 id 并入选批排除并集——同指纹条目不再
        入选，其余条目照常可选（排除口径与失败档案/chain_skipped 一致）。"""
        from core.code_fix import select_batch

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a"), "b": _item("b")})
        orch = _orch(_FakeRunner(proot), proot)
        orch._artifact_missing_skipped.add(frozenset({"a"}))
        batch = select_batch(proot, 20, exclude_ids=orch._stop_loss_item_ids())
        ids = {r["item_id"] for r in batch}
        self.assertNotIn("a", ids, "止损指纹条目 MUST NOT 入选")
        self.assertIn("b", ids, "其余指纹不受影响")


# ── 3.2 派发契约测试（agents/code-fix.md 字面子串锚定）────────────────


class TestCodeFixDispatchContract(unittest.TestCase):
    """同步派发契约条款字面锚定（9ccf90158/4c2fc3a9d 现状基线，防模板漂移）。

    任一子串被模板漂移删除或改写时测试 MUST 失败；子串为当前模板实文
    （「并行处置→等待与收集（headless 非交互，强制）」段），参照
    tests/test_prompt_lane_efficiency_sections.py「长任务前台等待」段先例。
    """

    def test_sync_dispatch_contract_clauses_present(self):
        path = Path(__file__).resolve().parent.parent / "agents" / "code-fix.md"
        text = path.read_text(encoding="utf-8")
        # 「回合结束 = run 终止」：headless 非交互能力事实（回合结束即 run 终止）
        self.assertIn("回合结束 = run 终止", text)
        # 同步并发派发：等待由派发方式本身完成
        self.assertIn("run_in_background: false", text)
        # MUST NOT 以「等待完成通知」结束回合（10-26 三连空转事故的止血条款）
        self.assertIn("MUST NOT 以「等待完成通知」", text)


if __name__ == "__main__":
    unittest.main()
