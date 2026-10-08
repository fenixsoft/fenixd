"""test_codefix_failure_registration_closeout.py — 失败登记闭环核销测试

覆盖 add-codefix-failure-registration-closeout：
- 1.1/1.2: 全终态核销（记录记账 + 告警收口 + todo 重写一次完成）、部分终态
  只更新 open_remaining、重复核销幂等、台账读取失败 fail-open、告警按
  evidence ``item_ids=<清单>;`` 精确匹配不误收口前缀条目集。
- 1.3: release_failed_batch 结构化留痕（带外不传 logger 亦留痕、logger 传入
  时另写 daemon 日志、零命中无条件留痕）、todo 登记块重写式核销、多批登记
  块隔离、裸标题残骸兜底移除。

覆盖 codefix-release-consume-todo-block（解除路径对齐）：
- 1.1: 人工整批解除→登记块同步核销（注记含解除时刻与留痕行指引）、部分
  解除不核销且他批块原样保留、核销 needle 整行精确匹配（前缀扩展清单不
  误命中）、todo 写失败不阻断解除、裸标题壳兜底移除。
- 1.2: 预算内自动释放留痕（released_by=auto-budget）且不触 todo 登记块。
- 1.3: 留痕行携 todo 块处理结果字段（consumed / not_found）。

MUST NOT 真跑 agent——临时目录直调模块函数。
"""

import fcntl
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

# /tmp 可能被外部清扫进程周期性清空（2026-09-19 实测）。统一用仓库内
# .history/tmp（gitignored），MUST NOT 改写全局 tempfile.tempdir。
_HISTORY_TMP = Path(__file__).resolve().parent.parent / ".history" / "tmp"
_HISTORY_TMP.mkdir(parents=True, exist_ok=True)


def _mkdtemp(prefix: str) -> str:
    return tempfile.mkdtemp(prefix=prefix, dir=str(_HISTORY_TMP))


def _make_project_root() -> Path:
    """建一个带 .fenix/code-review 目录的临时项目根。"""
    td = Path(_mkdtemp("cfix-closeout-"))
    (td / ".fenix" / "code-review").mkdir(parents=True, exist_ok=True)
    return td


def _write_ledger(project_root, statuses):
    """按 {item_id: status} 写 items.jsonl 最小记录（read_items 兼容形态）。"""
    path = Path(project_root) / ".fenix" / "code-review" / "items.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(
        json.dumps({"item_id": k, "status": v}, ensure_ascii=False) + "\n"
        for k, v in sorted(statuses.items())
    )
    path.write_text(content, encoding="utf-8")


class _FakeLogger:
    """AdminStore 风格 logger.warning/info(channel, msg) 收集器。"""

    def __init__(self):
        self.records = []

    def info(self, channel, msg):
        self.records.append(("info", channel, msg))

    def warning(self, channel, msg):
        self.records.append(("warning", channel, msg))


def _read_trace_rows(proot):
    from core.code_fix import RELEASE_TRACE_REL

    trace_path = Path(proot) / RELEASE_TRACE_REL
    if not trace_path.exists():
        return None, []
    rows = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return trace_path, rows


class TestConsumeResolvedFailedBatches(unittest.TestCase):
    """失败登记闭环核销（add-codefix-failure-registration-closeout 1.1/1.2）。"""

    def _register_maxed(self, proot, item_ids, reason="regression_failed_twice"):
        """造一条达上限失败登记（真实路径：record_failed_batch × MAX，一次性
        告警 + todo 登记随达上限那次入档一并产生）。"""
        from core.code_fix import FAIL_RETRY_MAX, record_failed_batch

        for i in range(FAIL_RETRY_MAX):
            record_failed_batch(
                proot, list(item_ids), f"/tmp/wt-{i}",
                reason=reason, branch="br-x", tip_sha=f"sha-{i}")

    def _signals(self, proot, signal_type="code_fix_retry_budget_exhausted"):
        from core.admin_store import AdminStore

        store = AdminStore(proot, logger=None)
        return [
            r for r in store.read_all()
            if r.get("signal_type") == signal_type
        ]

    def _failed(self, proot):
        from core.code_fix import load_failed_batches

        return load_failed_batches(proot)

    def test_all_terminal_consumes_record_alert_and_todo(self):
        """全终态：核销记账 + 告警收口 + todo 重写一次完成。"""
        from core.code_fix import consume_resolved_failed_batches

        proot = _make_project_root()
        self._register_maxed(proot, ["a", "b"])
        _write_ledger(proot, {"a": "resolved", "b": "ignored"})
        self.assertEqual(consume_resolved_failed_batches(proot), 1)
        rec = self._failed(proot)[0]
        self.assertTrue(rec.get("consumed_at"))
        self.assertEqual(rec.get("consumed_note"), "1 resolved / 1 ignored")
        self.assertEqual(rec.get("open_remaining"), 0)
        # 告警收口：handled + action_taken 附终态分布
        alerts = self._signals(proot)
        self.assertEqual(len(alerts), 1)
        self.assertTrue(alerts[0].get("handled"))
        self.assertIn("1 resolved / 1 ignored", alerts[0].get("action_taken") or "")
        # todo 登记块重写为单行核销注记（原「保持 open」条目行消失）
        todo = (proot / ".fenix" / "todo.md").read_text(encoding="utf-8")
        self.assertNotIn("被跳过的条目集合（保持 open）", todo)
        self.assertIn("核销", todo)
        self.assertIn("1 resolved / 1 ignored", todo)

    def test_partial_terminal_updates_open_remaining_only(self):
        """部分终态：只更新 open_remaining，不核销、不收口、登记块保留。"""
        from core.code_fix import consume_resolved_failed_batches

        proot = _make_project_root()
        self._register_maxed(proot, ["a", "b"])
        _write_ledger(proot, {"a": "resolved", "b": "open"})
        self.assertEqual(consume_resolved_failed_batches(proot), 0)
        rec = self._failed(proot)[0]
        self.assertFalse(rec.get("consumed_at"), "部分终态 MUST NOT 标记核销")
        self.assertEqual(rec.get("open_remaining"), 1)
        alerts = self._signals(proot)
        self.assertEqual(len(alerts), 1)
        self.assertFalse(alerts[0].get("handled"), "部分终态 MUST NOT 收口告警")
        todo = (proot / ".fenix" / "todo.md").read_text(encoding="utf-8")
        self.assertIn(
            "被跳过的条目集合（保持 open）", todo, "登记块 MUST 原样保留")

    def test_partial_terminal_resync_on_second_pass(self):
        """部分终态 → 剩余条目随后终态 → 下轮对账完成核销（open_remaining
        从 1 同步到 0 并核销）。"""
        from core.code_fix import consume_resolved_failed_batches

        proot = _make_project_root()
        self._register_maxed(proot, ["a", "b"])
        _write_ledger(proot, {"a": "resolved", "b": "open"})
        self.assertEqual(consume_resolved_failed_batches(proot), 0)
        _write_ledger(proot, {"a": "resolved", "b": "ignored"})
        self.assertEqual(consume_resolved_failed_batches(proot), 1)
        rec = self._failed(proot)[0]
        self.assertEqual(rec.get("consumed_note"), "1 resolved / 1 ignored")
        self.assertEqual(rec.get("open_remaining"), 0)

    def test_repeat_consume_idempotent(self):
        """重复核销幂等：不重写记录、不重写告警、不报错。"""
        from core.code_fix import consume_resolved_failed_batches

        proot = _make_project_root()
        self._register_maxed(proot, ["a"])
        _write_ledger(proot, {"a": "resolved"})
        self.assertEqual(consume_resolved_failed_batches(proot), 1)
        rec_before = self._failed(proot)[0]
        alert_before = self._signals(proot)[0]
        self.assertEqual(consume_resolved_failed_batches(proot), 0)
        self.assertEqual(
            self._failed(proot)[0], rec_before, "重复核销 MUST NOT 重写记录")
        alert_after = self._signals(proot)[0]
        self.assertEqual(
            (alert_before.get("handled_at"), alert_before.get("action_taken")),
            (alert_after.get("handled_at"), alert_after.get("action_taken")),
            "重复核销 MUST NOT 重写告警")

    def test_ledger_read_failure_fail_open(self):
        """台账读取失败按空集 fail-open：跳过本轮核销，不误核销、不抛异常。"""
        from core.code_fix import consume_resolved_failed_batches

        proot = _make_project_root()
        self._register_maxed(proot, ["a"])
        # items.jsonl 位置替换为目录 → read_text 抛 OSError → 降级检出 → 跳过
        ledger_path = proot / ".fenix" / "code-review" / "items.jsonl"
        ledger_path.mkdir()
        self.assertEqual(consume_resolved_failed_batches(proot), 0)
        rec = self._failed(proot)[0]
        self.assertFalse(rec.get("consumed_at"), "读失败 MUST NOT 误判全终态核销")
        self.assertFalse(self._signals(proot)[0].get("handled"))

    def test_ledger_missing_entry_keeps_unconsumed(self):
        """台账中查不到的条目视为非终态（无法证明终态，保守不核销）。"""
        from core.code_fix import consume_resolved_failed_batches

        proot = _make_project_root()
        self._register_maxed(proot, ["a", "b"])
        _write_ledger(proot, {"a": "resolved"})  # b 不在台账
        self.assertEqual(consume_resolved_failed_batches(proot), 0)
        rec = self._failed(proot)[0]
        self.assertFalse(rec.get("consumed_at"))
        self.assertEqual(rec.get("open_remaining"), 1)

    def test_prefix_item_set_alert_not_false_matched(self):
        """告警按 ``item_ids=<清单>;`` 精确匹配：核销 [a] 不误收口 [a, b] 的
        告警（无分号后缀时 [a] 的 needle 是 [a, b] evidence 的前缀子串）。"""
        from core.code_fix import consume_resolved_failed_batches

        proot = _make_project_root()
        self._register_maxed(proot, ["a"])
        self._register_maxed(proot, ["a", "b"])
        _write_ledger(proot, {"a": "resolved", "b": "open"})
        # 仅 [a] 记录全终态核销；[a, b] 记录部分终态（open_remaining=1）
        self.assertEqual(consume_resolved_failed_batches(proot), 1)
        alerts = self._signals(proot)
        self.assertEqual(len(alerts), 2)
        single = next(r for r in alerts if "item_ids=a; " in r["evidence"])
        pair = next(r for r in alerts if "item_ids=a, b; " in r["evidence"])
        self.assertTrue(single.get("handled"), "[a] 登记核销应收口 [a] 告警")
        self.assertFalse(pair.get("handled"), "[a, b] 告警 MUST NOT 被前缀误收口")
        recs = {tuple(sorted(r["item_ids"])): r for r in self._failed(proot)}
        self.assertTrue(recs[("a",)].get("consumed_at"))
        self.assertFalse(recs[("a", "b")].get("consumed_at"))


class TestTodoRewriteScope(unittest.TestCase):
    """todo.md 消费侧弱化（add-codefix-failure-registration-closeout 1.3）：
    重写式核销按块体 item_ids 定位本记录登记块。"""

    def _register_maxed(self, proot, item_ids):
        from core.code_fix import FAIL_RETRY_MAX, record_failed_batch

        for i in range(FAIL_RETRY_MAX):
            record_failed_batch(
                proot, list(item_ids), f"/tmp/wt-{i}",
                reason="regression_failed_twice", branch="br-x",
                tip_sha=f"sha-{i}")

    def test_todo_rewrite_isolated_between_batches(self):
        """多批登记块共存：只重写本记录对应块，MUST NOT 波及他批登记块。"""
        from core.code_fix import (
            _TODO_ENTRY_TITLE,
            consume_resolved_failed_batches,
        )

        proot = _make_project_root()
        self._register_maxed(proot, ["a", "b"])
        self._register_maxed(proot, ["c"])
        _write_ledger(proot, {"a": "resolved", "b": "ignored", "c": "open"})
        self.assertEqual(consume_resolved_failed_batches(proot), 1)
        todo = (proot / ".fenix" / "todo.md").read_text(encoding="utf-8")
        # 批1 块已重写为单行核销注记
        self.assertIn("1 resolved / 1 ignored", todo)
        self.assertNotIn(
            "被跳过的条目集合（保持 open）：a, b", todo, "本批登记块已被消费")
        # 批2 完整登记块原样保留（标题 + 条目行）
        self.assertEqual(
            todo.count(_TODO_ENTRY_TITLE), 1, "他批登记块标题 MUST 保留")
        self.assertIn("被跳过的条目集合（保持 open）：c", todo)
        self.assertIn("sha-", todo, "他批块的追溯线索行 MUST 保留")

    def test_tombstone_title_removed_as_fallback(self):
        """登记块损毁成裸标题（proposal 残骸场景）：核销时按标题兜底移除。"""
        from core.code_fix import consume_resolved_failed_batches

        proot = _make_project_root()
        self._register_maxed(proot, ["a"])
        todo_path = proot / ".fenix" / "todo.md"
        # 手工复刻残骸：正文被后续重写吞掉，只剩裸标题
        todo_path.write_text(
            "# todo\n\n"
            "## [code-fix] 失败批已达自动重试上限，待人工排查"
            "（add-code-fix-batch-failure-selfheal）\n",
            encoding="utf-8",
        )
        _write_ledger(proot, {"a": "resolved"})
        self.assertEqual(consume_resolved_failed_batches(proot), 1)
        todo = todo_path.read_text(encoding="utf-8")
        self.assertNotIn(
            "失败批已达自动重试上限", todo, "裸标题残骸 MUST 被兜底移除")
        self.assertIn("# todo", todo, "残骸移除 MUST NOT 波及文件其余内容")

    def test_tombstone_removed_without_touching_other_batch(self):
        """裸标题残骸与他批完整块共存：残骸移除、他批块保留。"""
        from core.code_fix import (
            _TODO_ENTRY_TITLE,
            consume_resolved_failed_batches,
        )

        proot = _make_project_root()
        self._register_maxed(proot, ["a"])
        self._register_maxed(proot, ["c"])
        todo_path = proot / ".fenix" / "todo.md"
        # 把批1 的块体替换为裸标题（残骸），批2 保持完整
        text = todo_path.read_text(encoding="utf-8")
        head, _, tail = text.partition(_TODO_ENTRY_TITLE)
        _, _, rest = tail.partition("## ")
        todo_path.write_text(
            head + _TODO_ENTRY_TITLE + "（add-code-fix-batch-failure-selfheal）\n\n"
            "## " + rest,
            encoding="utf-8",
        )
        _write_ledger(proot, {"a": "resolved", "c": "open"})
        self.assertEqual(consume_resolved_failed_batches(proot), 1)
        todo = todo_path.read_text(encoding="utf-8")
        self.assertNotIn("失败批已达自动重试上限，待人工排查（add-code-fix-"
                         "batch-failure-selfheal）\n\n## ", todo)
        self.assertEqual(todo.count(_TODO_ENTRY_TITLE), 1)
        self.assertIn("被跳过的条目集合（保持 open）：c", todo)


class TestReleaseTrace(unittest.TestCase):
    """release_failed_batch 结构化留痕（add-codefix-failure-registration-closeout
    1.3）：带外直调不经 daemon logger 亦可追溯。"""

    def test_trace_written_even_without_logger(self):
        from core.code_fix import (
            load_failed_batches,
            record_failed_batch,
            release_failed_batch,
        )

        proot = _make_project_root()
        record_failed_batch(proot, ["a", "b"], "/tmp/wt-1", reason="r")
        # 带外形态：不传 logger（todo 登记正文的官方解除指引即此形态）
        released = release_failed_batch(proot, ["a"])
        self.assertEqual(released, 0, "部分解除不计整批条数")
        _, rows = _read_trace_rows(proot)
        self.assertEqual(len(rows), 1, "带外不传 logger 亦 MUST 留痕")
        self.assertEqual(rows[0]["released_records"], 0)
        self.assertEqual(rows[0]["item_ids"], ["a"])
        self.assertTrue(rows[0]["released_at"])
        # 整批解除：released_records=1，记录从档案移除
        self.assertEqual(release_failed_batch(proot, ["a", "b"]), 1)
        _, rows = _read_trace_rows(proot)
        self.assertEqual(rows[-1]["released_records"], 1)
        self.assertEqual(
            load_failed_batches(proot), [], "整批解除后档案为空")

    def test_trace_with_logger_also_writes_daemon_line(self):
        from core.code_fix import (
            record_failed_batch,
            release_failed_batch,
        )

        proot = _make_project_root()
        record_failed_batch(proot, ["a"], "/tmp/wt-1", reason="r")
        logger = _FakeLogger()
        release_failed_batch(proot, ["a"], logger=logger)
        info_lines = [r for r in logger.records if r[0] == "info"]
        self.assertTrue(
            any("item_ids=['a']" in r[2] for r in info_lines),
            "logger 传入时 MUST 另写一行 daemon 日志（含 item_ids 摘要）")
        _, rows = _read_trace_rows(proot)
        self.assertEqual(len(rows), 1, "留痕文件与 daemon 日志双载体并存")

    def test_trace_unconditional_on_zero_hit(self):
        """无条件留痕：空请求/零命中调用同样留一行痕（审计带外调用）。"""
        from core.code_fix import release_failed_batch

        proot = _make_project_root()
        self.assertEqual(release_failed_batch(proot, []), 0)
        _, rows = _read_trace_rows(proot)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["released_records"], 0)
        self.assertEqual(rows[0]["item_ids"], [])
        # 未命中任何记录的非空请求同样留痕
        self.assertEqual(release_failed_batch(proot, ["nope"]), 0)
        _, rows = _read_trace_rows(proot)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1]["item_ids"], ["nope"])


class TestReleaseConsumesTodoBlock(unittest.TestCase):
    """解除路径对齐（codefix-release-consume-todo-block）：整批删除注册表
    记录后的同一调用序列内 best-effort 核销 todo.md 登记块。"""

    def _register_maxed(self, proot, item_ids):
        from core.code_fix import FAIL_RETRY_MAX, record_failed_batch

        for i in range(FAIL_RETRY_MAX):
            record_failed_batch(
                proot, list(item_ids), f"/tmp/wt-{i}",
                reason="regression_failed_twice", branch="br-x",
                tip_sha=f"sha-{i}")

    def _todo(self, proot):
        return (proot / ".fenix" / "todo.md").read_text(encoding="utf-8")

    def test_manual_full_release_consumes_todo_block(self):
        """整批解除→登记块同步核销：注记含解除时刻与留痕行指引，
        留痕记 consumed；带外不传 logger 亦照常核销+留痕。"""
        from core.code_fix import load_failed_batches, release_failed_batch

        proot = _make_project_root()
        self._register_maxed(proot, ["a", "b"])
        # 带外形态：不传 logger（todo 登记正文的官方解除指引即此形态）
        self.assertEqual(release_failed_batch(proot, ["a", "b"]), 1)
        self.assertEqual(load_failed_batches(proot), [], "整批解除后档案为空")
        todo = self._todo(proot)
        self.assertNotIn(
            "被跳过的条目集合（保持 open）：a, b", todo, "登记块已被核销")
        self.assertIn("人工解除核销", todo, "核销注记 MUST 写明解除动作")
        self.assertIn(
            "fix-failed-release.jsonl", todo, "核销注记 MUST 指向留痕行")
        _, rows = _read_trace_rows(proot)
        self.assertEqual(rows[-1]["todo_result"], "consumed")
        # 注记与留痕行同一解除时刻值（可互相对账）
        self.assertIn(rows[-1]["released_at"], todo)

    def test_partial_release_keeps_todo_block_and_other_batch(self):
        """部分解除（收缩）→登记块不核销（剩余条目仍在册仍跳过），
        他批块原样保留；留痕记 not_found。"""
        from core.code_fix import (
            _TODO_ENTRY_TITLE,
            load_failed_batches,
            release_failed_batch,
        )

        proot = _make_project_root()
        self._register_maxed(proot, ["a", "b"])
        self._register_maxed(proot, ["c"])
        self.assertEqual(release_failed_batch(proot, ["a"]), 0, "收缩不计整批")
        recs = load_failed_batches(proot)
        self.assertEqual(len(recs), 2)
        self.assertIn(["b"], [r["item_ids"] for r in recs], "余量仍在册")
        todo = self._todo(proot)
        self.assertIn("被跳过的条目集合（保持 open）：a, b", todo,
                      "收缩批登记块 MUST 原样保留（留待既有 consume 闭环）")
        self.assertIn("被跳过的条目集合（保持 open）：c", todo,
                      "他批登记块 MUST 原样保留")
        self.assertEqual(todo.count(_TODO_ENTRY_TITLE), 2)
        self.assertNotIn("人工解除核销", todo, "部分解除 MUST NOT 核销登记块")
        _, rows = _read_trace_rows(proot)
        self.assertEqual(rows[-1]["todo_result"], "not_found")

    def test_needle_not_false_matched_on_prefix_extended_block(self):
        """核销 needle 整行精确匹配：本批 [a] 与他批 [a, b]（清单为本批的
        前缀扩展）共存，解除 [a] 只核销本批块，他批块不被子串误命中。"""
        from core.code_fix import (
            _TODO_ENTRY_TITLE,
            load_failed_batches,
            release_failed_batch,
        )

        proot = _make_project_root()
        self._register_maxed(proot, ["a"])
        self._register_maxed(proot, ["a", "b"])
        self.assertEqual(release_failed_batch(proot, ["a"]), 1)
        recs = load_failed_batches(proot)
        self.assertEqual(
            [r["item_ids"] for r in recs], [["b"]], "他批收缩为 [b] 在册")
        todo = self._todo(proot)
        # 子串包含口径下 needle「：a」会同时命中「：a, b」块并误重写；
        # 整行锚后本批块核销、他批块原样保留。
        self.assertIn("被跳过的条目集合（保持 open）：a, b", todo,
                      "前缀扩展的他批登记块 MUST NOT 被误命中")
        self.assertEqual(
            todo.count(_TODO_ENTRY_TITLE), 1, "仅本批块被核销移除")
        self.assertEqual(todo.count("人工解除核销"), 1)
        _, rows = _read_trace_rows(proot)
        self.assertEqual(rows[-1]["todo_result"], "consumed")

    def test_auto_budget_release_traces_without_touching_todo(self):
        """预算内自动释放：留痕 released_by=auto-budget、不触 todo 登记块
        （墓碑在册，既有 consume 闭环覆盖；预算内记录本无登记块）。"""
        from core.code_fix import (
            load_failed_batches,
            record_failed_batch,
            release_retryable_failed_batches,
        )

        proot = _make_project_root()
        self._register_maxed(proot, ["a"])  # 达上限：有登记块，不属预算内
        record_failed_batch(proot, ["c"], "/tmp/wt-c", reason="r",
                            branch="br", tip_sha="sha-c")  # 预算内，无登记块
        self.assertEqual(release_retryable_failed_batches(proot), 1)
        recs = {r["item_ids"][0]: r for r in load_failed_batches(proot)}
        self.assertTrue(recs["c"].get("released"), "预算内记录打墓碑释放")
        self.assertFalse(recs["a"].get("released"), "达上限记录保持跳过")
        todo = self._todo(proot)
        self.assertIn("被跳过的条目集合（保持 open）：a", todo,
                      "自动释放 MUST NOT 触达他批登记块")
        self.assertNotIn("人工解除核销", todo)
        _, rows = _read_trace_rows(proot)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["released_records"], 1)
        self.assertEqual(rows[0]["released_by"], "auto-budget")
        self.assertEqual(rows[0]["item_ids"], ["c"])
        self.assertEqual(rows[0]["todo_result"], "not_found")

    def test_todo_write_failure_not_blocking_trace_not_found(self):
        """todo 写失败（todo.md 为目录→OSError）不阻断解除主流程，
        留痕记 not_found 保证「解除未核销」可审计。"""
        from core.code_fix import load_failed_batches, release_failed_batch

        proot = _make_project_root()
        self._register_maxed(proot, ["a"])
        todo_path = proot / ".fenix" / "todo.md"
        todo_path.unlink()
        todo_path.mkdir()  # todo 写入/读取必 OSError
        self.assertEqual(release_failed_batch(proot, ["a"]), 1,
                         "todo 失败 MUST NOT 阻断解除")
        self.assertEqual(load_failed_batches(proot), [], "解除已落盘")
        _, rows = _read_trace_rows(proot)
        self.assertEqual(rows[-1]["todo_result"], "not_found")
        self.assertEqual(rows[-1]["released_records"], 1)

    def test_bare_title_shell_removed_on_release_keeps_other_batch(self):
        """登记块已损毁成裸标题壳：解除核销时按既有兜底移除残骸，
        他批完整块原样保留。"""
        from core.code_fix import (
            _TODO_ENTRY_TITLE,
            release_failed_batch,
        )

        proot = _make_project_root()
        self._register_maxed(proot, ["a"])
        self._register_maxed(proot, ["c"])
        todo_path = proot / ".fenix" / "todo.md"
        # 把批1 的块体替换为裸标题（复刻 proposal 残骸场景），批2 保持完整
        text = todo_path.read_text(encoding="utf-8")
        head, _, tail = text.partition(_TODO_ENTRY_TITLE)
        _, _, rest = tail.partition("## ")
        todo_path.write_text(
            head + _TODO_ENTRY_TITLE + "（add-code-fix-batch-failure-selfheal）\n\n"
            "## " + rest,
            encoding="utf-8",
        )
        self.assertEqual(release_failed_batch(proot, ["a"]), 1)
        todo = todo_path.read_text(encoding="utf-8")
        self.assertEqual(
            todo.count(_TODO_ENTRY_TITLE), 1,
            "裸标题残骸被兜底移除，他批块标题保留")
        self.assertIn("被跳过的条目集合（保持 open）：c", todo)
        self.assertNotIn(
            "待人工排查（add-code-fix-batch-failure-selfheal）\n\n## ", todo,
            "批1 裸标题残骸 MUST 被移除")
        _, rows = _read_trace_rows(proot)
        self.assertEqual(rows[-1]["released_records"], 1)
        self.assertEqual(rows[-1]["todo_result"], "consumed")

    def test_trace_without_logger_contains_todo_result_field(self):
        """带外无 logger 调用留痕照写，且行内含 todo 处理结果与来源字段
        （零命中未触发核销 → not_found / manual）。"""
        from core.code_fix import release_failed_batch

        proot = _make_project_root()
        self.assertEqual(release_failed_batch(proot, []), 0)
        _, rows = _read_trace_rows(proot)
        self.assertEqual(len(rows), 1, "带外不传 logger 亦 MUST 留痕")
        self.assertEqual(rows[0]["item_ids"], [])
        self.assertEqual(rows[0]["todo_result"], "not_found")
        self.assertEqual(rows[0]["released_by"], "manual")
        self.assertTrue(rows[0]["released_at"])


class TestReviveClearsConsumedBookkeeping(unittest.TestCase):
    """复燃清核销记账（add-codefix-failure-registration-closeout 1.1）：
    已核销记录同条目集再次失败即回到未核销，open_remaining 恢复同步。"""

    def test_revive_clears_consumed_fields(self):
        from core.code_fix import (
            FAIL_RETRY_MAX,
            consume_resolved_failed_batches,
            load_failed_batches,
            record_failed_batch,
        )

        proot = _make_project_root()
        for i in range(FAIL_RETRY_MAX):
            record_failed_batch(
                proot, ["a"], f"/tmp/wt-{i}", reason="r",
                branch="br", tip_sha=f"s{i}")
        _write_ledger(proot, {"a": "resolved"})
        self.assertEqual(consume_resolved_failed_batches(proot), 1)
        rec = load_failed_batches(proot)[0]
        self.assertTrue(rec.get("consumed_at"))
        # 条目重新 open 且同条目集再次失败：复燃清核销记账
        _write_ledger(proot, {"a": "open"})
        record_failed_batch(
            proot, ["a"], "/tmp/wt-again", reason="r",
            branch="br", tip_sha="s-again")
        rec = load_failed_batches(proot)[0]
        self.assertNotIn("consumed_at", rec, "复燃 MUST 清核销记账")
        self.assertNotIn("consumed_note", rec)
        self.assertNotIn("open_remaining", rec)
        self.assertEqual(rec["fail_count"], FAIL_RETRY_MAX + 1)
        # 复燃后对账恢复：open 条目不再终态 → open_remaining 同步、不核销
        self.assertEqual(consume_resolved_failed_batches(proot), 0)
        rec = load_failed_batches(proot)[0]
        self.assertEqual(rec.get("open_remaining"), 1)


if __name__ == "__main__":
    unittest.main()
