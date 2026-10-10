"""test_code_review_salvage_writeoff.py — error 收场抢救 pending 锚与
scheduled 全仓核销放宽测试（evo-add-review-night-defer-snapshot-writeoff
3.1/3.2/3.3 / 4.3）

覆盖：
- error 收场抢救落账写 pending-writeoff 锚（覆盖写形态）；零落账不写锚；
  一切 error 收场绝不核销（resolved==0，台账 open 不动）；
- scheduled 全仓 run（window_start=None）成功且累计覆盖完整 → 核销解锁
  （resolved>0）并清锚；
- agent 静默少审（累计覆盖不全）→ 核销锁定（resolved==0、open 不动）、
  锚保持（等剩余文件重派补齐）；
- 窗口档 scheduled（window_start 非 None）与 manual_window 绝不核销
  （「窗口审查只增不核销」不变量）；
- admin_monitor 完成日志在读到锚时追加「部分覆盖待核销（run_id=…）」
  标注。

run_code_review 经最小 runner 替身驱动（_run_claude 替身写真实 out 产物
文件，聚合读取/落账/核销/锚链路全走生产代码）；台账断言走
core.code_review.read_items 真实读侧。
"""

import json
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from core.code_review import (
    clear_pending_writeoff,
    fingerprint as cr_fingerprint,
    read_items,
    read_pending_writeoff,
    write_items,
    write_pending_writeoff,
)
from core.agent_runner.maintenance_runs import run_code_review


def _make_repo() -> Path:
    root = Path(tempfile.mkdtemp(prefix="cr-writeoff-"))
    (root / ".fenix" / "code-review").mkdir(parents=True, exist_ok=True)
    return root


class _FakeLogger:
    def __init__(self):
        self.records = []

    def info(self, tag, message):
        self.records.append(f"INFO {tag} {message}")

    def warning(self, tag, message):
        self.records.append(f"WARNING {tag} {message}")

    def error(self, tag, message):
        self.records.append(f"ERROR {tag} {message}")


def _finding(category="correctness", title="bug", file_key=None, severity="major"):
    f = {
        "category": category,
        "title": title,
        "severity": severity,
        "description": f"desc {title}",
        "suggestion": f"fix {title}",
    }
    if file_key:
        f["file"] = file_key
    return f


class _Runner:
    """最小 runner 替身：_run_claude 按剧本写真实 out 产物后返回/抛出。

    out_rows：``[{"file": ..., "findings": [...]}]`` 聚合行形态（agent 逐
    文件写一行，含零发现文件）。异常剧本（die_after_write=True）先写产物
    再抛——模拟「run 中途死亡，死前已落盘的分片是真实审查结论」。
    """

    def __init__(self, proot, run_id, out_rows=None, die_after_write=False):
        self.project_root = Path(proot)
        self.logger = _FakeLogger()
        self.config = {}
        self._run_id = run_id
        self._out_rows = out_rows or []
        self._die = die_after_write

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

    def _run_claude(self, prompt, root, run_id, model_override, env_overrides,
                    max_turns=None, spec_name=None, agent_type=None):
        self._write_out()
        if self._die:
            raise RuntimeError("Exit code: 1 (gateway 429)")
        return ("output", 3, "session", {})

    def _extract_usage_info(self, x):
        return {}

    def _accumulate_code_review_tokens(self, run_id, usage):
        return None

    def _read_code_review_out(self, project_root, run_id):
        # 委托真实模块函数：聚合读取/行级展开链路全走生产代码
        from core.agent_runner import maintenance_runs

        return maintenance_runs._read_code_review_out(self, project_root, run_id)


def _seed_open_item(proot, file_key="src/old.py", category="correctness",
                    title="old bug", fp=None):
    """预置台账 open 条目（指纹可显式指定，缺省按真实指纹口径现算）。"""
    fp = fp or cr_fingerprint(file_key, category, title)
    rec = {
        "item_id": f"seed-{fp[:8]}",
        "project": Path(proot).name,
        "status": "open",
        "fingerprint": fp,
        "file": file_key,
        "line": 1,
        "severity": "major",
        "category": category,
        "title": title,
        "description": "seed",
        "suggestion": "seed",
    }
    write_items(proot, {rec["item_id"]: rec})
    return fp


class TestErrorSalvageWritesAnchor(unittest.TestCase):
    """error 收场抢救落账写锚（task 3.2 写入点）。"""

    def setUp(self):
        self.proot = _make_repo()

    def tearDown(self):
        shutil.rmtree(str(self.proot), ignore_errors=True)

    def test_salvage_writes_anchor_and_upserts_ledger(self):
        out_rows = [
            {"file": "src/a.py", "findings": [_finding(title="bug a")]},
            {"file": "src/b.py", "findings": [_finding(title="bug b", category="style")]},
        ]
        runner = _Runner(self.proot, "code-review-1000",
                         out_rows=out_rows, die_after_write=True)
        result = run_code_review(
            runner, ["src/a.py", "src/b.py"],
            review_kind="scheduled", window_start=None, scope="full")
        self.assertFalse(result.success)
        self.assertIn("error 收场抢救落账", result.error)
        self.assertEqual(result.inserted, 2)
        # 锚内容：{run_id, inserted, updated, at}
        anchor = read_pending_writeoff(self.proot)
        self.assertEqual(anchor.get("run_id"), "code-review-1000")
        self.assertEqual(anchor.get("inserted"), 2)
        self.assertEqual(anchor.get("updated"), 0)
        self.assertTrue(anchor.get("at"))
        # 抢救落账真实进台账
        items = read_items(self.proot)
        self.assertEqual(len(items), 2)
        # 红线：error 收场绝不核销
        self.assertEqual(result.resolved, 0)

    def test_salvage_overwrites_previous_anchor(self):
        # 覆盖写：新事故顶旧锚，只留最近一次待核销现场
        write_pending_writeoff(self.proot, {
            "run_id": "code-review-old", "inserted": 9, "updated": 9,
            "at": "2026-10-01T00:00:00+00:00"})
        runner = _Runner(self.proot, "code-review-1001",
                         out_rows=[{"file": "src/a.py",
                                    "findings": [_finding(title="new a")]}],
                         die_after_write=True)
        result = run_code_review(
            runner, ["src/a.py"],
            review_kind="scheduled", window_start=None, scope="full")
        self.assertFalse(result.success)
        anchor = read_pending_writeoff(self.proot)
        self.assertEqual(anchor.get("run_id"), "code-review-1001")
        self.assertEqual(anchor.get("inserted"), 1)

    def test_salvage_zero_rows_writes_no_anchor(self):
        # 无产物（死前零落盘）→ 无落账 → 不写锚、error 不带抢救后缀
        runner = _Runner(self.proot, "code-review-1002",
                         out_rows=[], die_after_write=True)
        result = run_code_review(
            runner, ["src/a.py"],
            review_kind="scheduled", window_start=None, scope="full")
        self.assertFalse(result.success)
        self.assertNotIn("error 收场抢救落账", result.error)
        self.assertEqual(read_pending_writeoff(self.proot), {})

    def test_error_finish_never_resolves_preexisting_open(self):
        # 双红线之一：error 收场（即使全仓档）绝不核销既有 open 条目
        seed_fp = _seed_open_item(self.proot)
        runner = _Runner(self.proot, "code-review-1003",
                         out_rows=[{"file": "src/a.py",
                                    "findings": [_finding(title="bug a")]}],
                         die_after_write=True)
        result = run_code_review(
            runner, ["src/a.py"],
            review_kind="scheduled", window_start=None, scope="full")
        self.assertFalse(result.success)
        self.assertEqual(result.resolved, 0)
        items = read_items(self.proot)
        seeded = [r for r in items.values() if r.get("fingerprint") == seed_fp]
        self.assertEqual(len(seeded), 1)
        self.assertEqual(seeded[0]["status"], "open", "既有 open 不被 error 收场核销")


class TestScheduledFullWriteoff(unittest.TestCase):
    """scheduled 全仓核销资格放宽与覆盖守卫（task 3.2）。"""

    def setUp(self):
        self.proot = _make_repo()

    def tearDown(self):
        shutil.rmtree(str(self.proot), ignore_errors=True)

    def test_full_coverage_unlocks_and_clears_anchor(self):
        # 全覆盖 + 台账存在本轮未观测条目 → resolved>0 且锚清除
        seed_fp = _seed_open_item(self.proot, file_key="src/gone.py",
                                  title="stale issue")
        write_pending_writeoff(self.proot, {
            "run_id": "code-review-prior", "inserted": 1, "updated": 0,
            "at": "2026-10-01T00:00:00+00:00"})
        runner = _Runner(
            self.proot, "code-review-2000",
            out_rows=[{"file": "src/a.py",
                       "findings": [_finding(title="fresh issue")]}])
        result = run_code_review(
            runner, ["src/a.py"],
            review_kind="scheduled", window_start=None, scope="full")
        self.assertTrue(result.success)
        self.assertGreaterEqual(result.resolved, 1, "全仓 scheduled 解锁核销")
        items = read_items(self.proot)
        seeded = [r for r in items.values() if r.get("fingerprint") == seed_fp]
        self.assertEqual(seeded[0]["status"], "resolved",
                         "未再观测的存量 open 条目被核销")
        self.assertEqual(read_pending_writeoff(self.proot), {},
                         "核销解锁分支走完须清锚")

    def test_partial_coverage_locks_and_keeps_anchor(self):
        # agent 静默少审（manifest 2 文件产物只覆盖 1）→ 核销锁定、open 不动、
        # 锚保持（等剩余文件重派补齐）
        seed_fp = _seed_open_item(self.proot, file_key="src/b.py",
                                  title="uncovered issue")
        write_pending_writeoff(self.proot, {
            "run_id": "code-review-prior", "inserted": 3, "updated": 1,
            "at": "2026-10-01T00:00:00+00:00"})
        runner = _Runner(
            self.proot, "code-review-2001",
            out_rows=[{"file": "src/a.py",
                       "findings": [_finding(title="fresh issue")]}])
        result = run_code_review(
            runner, ["src/a.py", "src/b.py"],
            review_kind="scheduled", window_start=None, scope="full")
        self.assertTrue(result.success)
        self.assertEqual(result.resolved, 0, "部分覆盖维持抢救红线不核销")
        items = read_items(self.proot)
        seeded = [r for r in items.values() if r.get("fingerprint") == seed_fp]
        self.assertEqual(seeded[0]["status"], "open")
        anchor = read_pending_writeoff(self.proot)
        self.assertEqual(anchor.get("run_id"), "code-review-prior",
                         "锁定分支不清锚")
        joined = "\n".join(runner.logger.records)
        self.assertIn("全仓快照核销锁定", joined)

    def test_full_coverage_without_prior_anchor_still_clears_idempotent(self):
        # 无锚时解锁路径清锚＝幂等 no-op（不抛、不残留半态）
        _seed_open_item(self.proot, file_key="src/gone.py", title="stale issue")
        runner = _Runner(
            self.proot, "code-review-2002",
            out_rows=[{"file": "src/a.py",
                       "findings": [_finding(title="fresh issue")]}])
        result = run_code_review(
            runner, ["src/a.py"],
            review_kind="scheduled", window_start=None, scope="full")
        self.assertTrue(result.success)
        self.assertGreaterEqual(result.resolved, 1)
        self.assertEqual(read_pending_writeoff(self.proot), {})


class TestWindowScheduledNeverWriteoff(unittest.TestCase):
    """「窗口审查只增不核销」不变量（task 3.2 红线注释固定）。"""

    def setUp(self):
        self.proot = _make_repo()

    def tearDown(self):
        shutil.rmtree(str(self.proot), ignore_errors=True)

    def _run_window(self, review_kind):
        seed_fp = _seed_open_item(self.proot, file_key="src/gone.py",
                                  title="stale issue")
        write_pending_writeoff(self.proot, {
            "run_id": "code-review-prior", "inserted": 1, "updated": 0,
            "at": "2026-10-01T00:00:00+00:00"})
        runner = _Runner(
            self.proot, "code-review-3000",
            out_rows=[{"file": "src/a.py",
                       "findings": [_finding(title="fresh issue")]}])
        result = run_code_review(
            runner, ["src/a.py"],
            review_kind=review_kind,
            window_start=datetime(2026, 10, 11, 2, 0, 0),
            scope="window")
        return result, seed_fp, runner

    def test_window_scheduled_full_coverage_still_no_writeoff(self):
        # 窗口档 scheduled 即使本轮产物「恰好」覆盖 manifest 全集也绝不核销
        result, seed_fp, runner = self._run_window("scheduled")
        self.assertTrue(result.success)
        self.assertEqual(result.resolved, 0)
        items = read_items(self.proot)
        seeded = [r for r in items.values() if r.get("fingerprint") == seed_fp]
        self.assertEqual(seeded[0]["status"], "open")
        self.assertNotEqual(read_pending_writeoff(self.proot), {},
                            "窗口档不进核销资格门，锚保持原样")

    def test_manual_window_no_writeoff(self):
        result, seed_fp, _ = self._run_window("manual_window")
        self.assertTrue(result.success)
        self.assertEqual(result.resolved, 0)
        items = read_items(self.proot)
        seeded = [r for r in items.values() if r.get("fingerprint") == seed_fp]
        self.assertEqual(seeded[0]["status"], "open")


class TestClearPendingWriteoff(unittest.TestCase):
    """锚三辅助函数的基本语义（task 3.1）。"""

    def setUp(self):
        self.proot = _make_repo()

    def tearDown(self):
        shutil.rmtree(str(self.proot), ignore_errors=True)

    def test_write_read_clear_roundtrip(self):
        self.assertEqual(read_pending_writeoff(self.proot), {}, "缺失返回空 dict")
        write_pending_writeoff(self.proot, {
            "run_id": "code-review-x", "inserted": 1, "updated": 2,
            "at": "2026-10-11T00:00:00+00:00"})
        anchor = read_pending_writeoff(self.proot)
        self.assertEqual(anchor["run_id"], "code-review-x")
        self.assertEqual(anchor["updated"], 2)
        clear_pending_writeoff(self.proot)
        self.assertEqual(read_pending_writeoff(self.proot), {})
        # 幂等：重复清除不抛
        clear_pending_writeoff(self.proot)


class TestCompletionLogAnnotation(unittest.TestCase):
    """完成日志待核销标注（task 3.3）。"""

    def _harness(self):
        from core.admin_monitor import AdminMonitor

        proot = _make_repo()
        logger = _FakeLogger()

        class _R:
            _running_agents = {}

            def run_code_review(self, *args, **kwargs):
                from core.agent_runner.result_gate import CodeReviewResult

                return CodeReviewResult(
                    run_id="code-review-live", success=True,
                    inserted=0, updated=0, resolved=0, shards=0)

        runner = _R()
        mon = AdminMonitor(
            {"admin": {
                "code_review": {"enabled": True},
                "self_review": {"enabled": True, "run_at": "00:00"},
            }},
            None, str(proot), logger,
            agent_runner=runner, code_review_executor=None)
        patches = [
            mock.patch("core.code_review.compute_window",
                       return_value=(datetime(2026, 10, 11, 2, 0, 0), "self_review")),
            mock.patch("core.code_review.collect_manifest",
                       return_value=["src/a.py"]),
            mock.patch("core.code_review.read_code_review_state", return_value={}),
            mock.patch("core.code_review.save_code_review_state"),
        ]
        return proot, mon, logger, patches

    def test_log_appends_annotation_with_anchor(self):
        proot, mon, logger, patches = self._harness()
        try:
            for p in patches:
                p.start()
            write_pending_writeoff(proot, {
                "run_id": "code-review-anchor-9", "inserted": 4, "updated": 1,
                "at": "2026-10-11T00:00:00+00:00"})
            result = mon._run_code_review_checkpoint()
            self.assertEqual(result["reason"], "scheduled")
            joined = "\n".join(logger.records)
            self.assertIn("部分覆盖待核销（run_id=code-review-anchor-9）", joined)
        finally:
            for p in patches:
                p.stop()
            shutil.rmtree(str(proot), ignore_errors=True)

    def test_log_without_anchor_has_no_annotation(self):
        proot, mon, logger, patches = self._harness()
        try:
            for p in patches:
                p.start()
            result = mon._run_code_review_checkpoint()
            self.assertEqual(result["reason"], "scheduled")
            joined = "\n".join(logger.records)
            self.assertNotIn("部分覆盖待核销", joined)
        finally:
            for p in patches:
                p.stop()
            shutil.rmtree(str(proot), ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
