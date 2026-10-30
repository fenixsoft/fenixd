"""test_code_review_night_resume.py — writeoff-pending 锚驱动剃余续审测试
（evo-review-night-window-resume-hardening 2.1/2.2/2.3）

覆盖：

- 锚存在时剩余清单组装正确：周期审查派发以「全量清单 − 抢救已落账覆盖
  文件」的剩余清单派发，经既有 ``redispatch_of`` 形参标注死 run id
  （MUST NOT 新形参——收尾守卫仅在 redispatch_of 非空时按链式累计覆盖
  判定），并写结构化日志（reason=writeoff_resume、剩余文件数）；
- 无锚时全量清单行为不变（无 redispatch_of、无 writeoff_resume 日志）；
- 锚驱动续审收尾累计覆盖完整时核销清锚（既有 _writeoff_coverage_guard
  链式分支，收尾链路全走生产代码）；链式部分覆盖维持抢救红线不核销、
  不清锚；
- 剩余清单为空（当前清单已被抢救落账全覆盖）跳过派发不空跑。

checkpoint 路径替身注入形态沿 tests/test_code_review_night_defer.py；
收尾链路驱动形态沿 tests/test_code_review_salvage_writeoff.py（最小
runner 替身写真实 out 产物，聚合读取/落账/核销/锚链路全走生产代码）。
"""

import json
import shutil
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from core.code_review import (
    fingerprint as cr_fingerprint,
    read_items,
    read_pending_writeoff,
    write_items,
    write_pending_writeoff,
)
from core.agent_runner.maintenance_runs import run_code_review

_DEAD_RUN = "code-review-900"


def _make_repo() -> Path:
    root = Path(tempfile.mkdtemp(prefix="cr-resume-"))
    (root / ".fenix" / "code-review").mkdir(parents=True, exist_ok=True)
    return root


def _local(h, m, s=0):
    """注入用本地时刻 struct（2026-10-11 周日，午后恒窗外）。"""
    return time.struct_time((2026, 10, 11, h, m, s, 6, 284, -1))


class _FakeLogger:
    def __init__(self):
        self.records = []

    def info(self, tag, message):
        self.records.append(f"INFO {tag} {message}")

    def warning(self, tag, message):
        self.records.append(f"WARNING {tag} {message}")

    def error(self, tag, message):
        self.records.append(f"ERROR {tag} {message}")


class _CaptureResult:
    run_id = "code-review-live"
    success = True
    inserted = 0
    updated = 0
    resolved = 0
    error = ""


class _CaptureRunner:
    """fake agent_runner：捕获 run_code_review 实参（对齐 night_defer）。"""

    _running_agents = {}

    def __init__(self):
        self.calls = []

    def run_code_review(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        return _CaptureResult()


class _CheckpointHarness:
    """AdminMonitor + 核心替身注入（对齐 night_defer _MonitorHarness）。"""

    def __init__(self, manifest):
        from core.admin_monitor import AdminMonitor

        self.repo = _make_repo()
        self.logger = _FakeLogger()
        self.runner = _CaptureRunner()
        self.mon = AdminMonitor(
            {
                "admin": {
                    "code_review": {"enabled": True},
                    "self_review": {"enabled": True, "run_at": "00:00"},
                    "code_review_fix": {"night_quiet_window": "off"},
                }
            },
            None,
            str(self.repo),
            self.logger,
            agent_runner=self.runner,
            code_review_executor=None,
        )
        self._patches = [
            mock.patch("core.code_review.compute_window",
                       return_value=(datetime(2026, 10, 11, 2, 0, 0), "self_review")),
            mock.patch("core.code_review.collect_manifest",
                       return_value=list(manifest)),
            mock.patch("core.code_review.read_code_review_state", return_value={}),
            mock.patch("core.code_review.save_code_review_state"),
        ]
        self.mocks = [p.start() for p in self._patches]

    def dispose(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(str(self.repo), ignore_errors=True)

    def write_dead_run(self, manifest_files, covered_files):
        """写死 run 现场：manifest-<id>.json + 已落账分片（覆盖 covered_files）。

        模拟 49/52 形态：派发 manifest 落盘（收尾守卫的 origin 权威来源）、
        agent 死前已落分片是真实审查结论（每文件一行，含零发现文件）。
        """
        cr_dir = self.repo / ".fenix" / "code-review"
        (cr_dir / f"manifest-{_DEAD_RUN}.json").write_text(
            json.dumps({"run_id": _DEAD_RUN, "scope": "full",
                        "files": list(manifest_files)}, ensure_ascii=False),
            encoding="utf-8")
        shard = cr_dir / f"out-{_DEAD_RUN}-b1.jsonl"
        shard.write_text(
            "".join(
                json.dumps({"file": f, "findings": []}, ensure_ascii=False) + "\n"
                for f in covered_files),
            encoding="utf-8")

    def write_anchor(self):
        write_pending_writeoff(self.repo, {
            "run_id": _DEAD_RUN, "inserted": 2, "updated": 0,
            "at": "2026-10-15T20:32:00+00:00"})

    def checkpoint(self):
        with mock.patch("core.admin_monitor.time.localtime",
                        return_value=_local(14, 0)):
            return self.mon._run_code_review_checkpoint()


class TestAnchorTrimsManifest(unittest.TestCase):
    """锚存在时剩余清单组装正确（task 2.3 例①）。"""

    def test_resume_dispatches_remaining_with_redispatch_of(self):
        # 死 run 抢救落账覆盖 a/b，全量清单 a/b/c/d → 续审只派 c/d，
        # redispatch_of 标注死 run id（既有形参，MUST NOT 新形参）
        h = _CheckpointHarness(["src/a.py", "src/b.py", "src/c.py", "src/d.py"])
        try:
            h.write_dead_run(
                ["src/a.py", "src/b.py", "src/c.py"],
                ["src/a.py", "src/b.py"])
            h.write_anchor()
            result = h.checkpoint()
            self.assertEqual(
                result, {"triggered": True, "ok": True, "reason": "scheduled",
                         "date": result["date"]})
            self.assertEqual(len(h.runner.calls), 1)
            call = h.runner.calls[0]
            self.assertEqual(
                call["args"][0], ["src/c.py", "src/d.py"],
                "只审「全量清单 − 抢救已落账覆盖文件」的剩余清单，已落分片不重烧")
            self.assertEqual(
                call["kwargs"].get("redispatch_of"), _DEAD_RUN,
                "链路标注 MUST 复用既有 redispatch_of 形参传死 run id")
            self.assertEqual(call["kwargs"].get("review_kind"), "scheduled")
            # 同日防重照写（与普通派发同口径）
            h.mocks[3].assert_called_once()
            # 结构化续审日志（spec「续审路径可观测」）
            joined = "\n".join(h.logger.records)
            self.assertIn("reason=writeoff_resume", joined)
            self.assertIn(f"resume_of={_DEAD_RUN}", joined)
            self.assertIn("剩余 2/4 文件", joined)
        finally:
            h.dispose()

    def test_empty_remaining_skips_dispatch(self):
        # 剩余清单为空（当前清单已被抢救落账全覆盖）→ 跳过派发不空跑，
        # 防重照写、单飞复位、锚保持（核销解锁仍由收尾守卫判定）
        h = _CheckpointHarness(["src/a.py", "src/b.py"])
        try:
            h.write_dead_run(
                ["src/a.py", "src/b.py"], ["src/a.py", "src/b.py"])
            h.write_anchor()
            result = h.checkpoint()
            self.assertEqual(
                result,
                {"triggered": True, "ok": True,
                 "reason": "writeoff_resume_no_remaining",
                 "date": result["date"]})
            self.assertEqual(len(h.runner.calls), 0)
            h.mocks[3].assert_called_once()
            self.assertFalse(h.mon._code_review_in_flight, "单飞标志已复位")
            self.assertNotEqual(read_pending_writeoff(h.repo), {}, "锚保持")
            joined = "\n".join(h.logger.records)
            self.assertIn("reason=writeoff_resume", joined)
        finally:
            h.dispose()


class TestNoAnchorUnchanged(unittest.TestCase):
    """无锚时全量清单行为不变（task 2.3 例②）。"""

    def test_no_anchor_dispatches_full_manifest_without_redispatch(self):
        h = _CheckpointHarness(["src/a.py", "src/b.py"])
        try:
            result = h.checkpoint()
            self.assertEqual(
                result, {"triggered": True, "ok": True, "reason": "scheduled",
                         "date": result["date"]})
            self.assertEqual(len(h.runner.calls), 1)
            call = h.runner.calls[0]
            self.assertEqual(call["args"][0], ["src/a.py", "src/b.py"],
                             "无锚：全量清单派发，行为不变")
            self.assertIsNone(
                call["kwargs"].get("redispatch_of"),
                "无锚：MUST NOT 携带 redispatch_of 标注")
            joined = "\n".join(h.logger.records)
            self.assertNotIn("writeoff_resume", joined)
        finally:
            h.dispose()


class _CloseRunner:
    """最小 runner 替身（对齐 salvage_writeoff._Runner）：按剧本写真实 out
    产物后返回成功；聚合读取/落账/核销/锚链路全走生产代码。"""

    def __init__(self, proot, run_id, out_files):
        self.project_root = Path(proot)
        self.logger = _FakeLogger()
        self.config = {}
        self._run_id = run_id
        self._out_files = list(out_files)

    def _unique_code_review_run_id(self):
        return self._run_id

    def _build_prompt(self, run_id, agent_type, detail=None):
        return "prompt"

    def _get_agent_model_assignment(self, name):
        return None

    def _get_admin_model(self):
        return "test-model"

    def _run_agent(self, prompt, root, run_id, model_override, env_overrides,
                   max_turns=None, spec_name=None, agent_type=None):
        # 每文件一行真实 finding（核销「observed 非空」门以指纹口径消费本轮
        # 观测集——零发现行过不了存在性产物门下的 observed 门）
        path = (self.project_root / ".fenix" / "code-review"
                / f"out-{run_id}.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = []
        for f in self._out_files:
            rows.append({
                "file": f,
                "findings": [{
                    "category": "correctness",
                    "title": f"resume issue {f}",
                    "severity": "minor",
                    "description": f"desc {f}",
                    "suggestion": f"fix {f}",
                }],
            })
        path.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
            encoding="utf-8")
        return ("output", 3, "session", {}, None)

    def _extract_usage_info(self, x):
        return {}

    def _accumulate_code_review_tokens(self, run_id, usage):
        return None

    def _read_code_review_out(self, project_root, run_id):
        from core.agent_runner import maintenance_runs

        return maintenance_runs._read_code_review_out(self, project_root, run_id)


def _seed_open_item(proot, file_key="src/gone.py", title="stale issue"):
    fp = cr_fingerprint(file_key, "correctness", title)
    rec = {
        "item_id": f"seed-{fp[:8]}",
        "project": Path(proot).name,
        "status": "open",
        "fingerprint": fp,
        "file": file_key,
        "line": 1,
        "severity": "major",
        "category": "correctness",
        "title": title,
        "description": "seed",
        "suggestion": "seed",
    }
    write_items(proot, {rec["item_id"]: rec})
    return fp


class TestResumeCloseWriteoff(unittest.TestCase):
    """续审收尾累计覆盖守卫（task 2.3 例③；收尾链路走生产代码）。"""

    def setUp(self):
        self.proot = _make_repo()

    def tearDown(self):
        shutil.rmtree(str(self.proot), ignore_errors=True)

    def _seed_dead_run(self, manifest_files, covered_files):
        (self.proot / ".fenix" / "code-review"
         / f"manifest-{_DEAD_RUN}.json").write_text(
            json.dumps({"run_id": _DEAD_RUN, "scope": "full",
                        "files": list(manifest_files)}, ensure_ascii=False),
            encoding="utf-8")
        (self.proot / ".fenix" / "code-review"
         / f"out-{_DEAD_RUN}-b1.jsonl").write_text(
            "".join(
                json.dumps({"file": f, "findings": []}, ensure_ascii=False) + "\n"
                for f in covered_files),
            encoding="utf-8")
        write_pending_writeoff(self.proot, {
            "run_id": _DEAD_RUN, "inserted": len(covered_files), "updated": 0,
            "at": "2026-10-15T20:32:00+00:00"})

    def test_chain_full_coverage_unlocks_and_clears_anchor(self):
        # 死 run 覆盖 a/b（抢救落账），续审（redispatch_of 标注）补 c →
        # 链式累计覆盖 ⊇ 原 manifest → 核销解锁 + 清锚
        seed_fp = _seed_open_item(self.proot)
        self._seed_dead_run(
            ["src/a.py", "src/b.py", "src/c.py"], ["src/a.py", "src/b.py"])
        runner = _CloseRunner(self.proot, "code-review-901", ["src/c.py"])
        result = run_code_review(
            runner, ["src/c.py"],
            review_kind="scheduled", window_start=None, scope="full",
            redispatch_of=_DEAD_RUN)
        self.assertTrue(result.success)
        self.assertGreaterEqual(
            result.resolved, 1, "链式累计覆盖完整 → 解锁全仓核销")
        items = read_items(self.proot)
        seeded = [r for r in items.values() if r.get("fingerprint") == seed_fp]
        self.assertEqual(seeded[0]["status"], "resolved")
        self.assertEqual(
            read_pending_writeoff(self.proot), {},
            "覆盖完整解锁核销后锚被清除")
        joined = "\n".join(runner.logger.records)
        self.assertNotIn("全仓快照核销锁定", joined)

    def test_chain_partial_coverage_locks_and_keeps_anchor(self):
        # 死 run 覆盖 a/b，原 manifest a/b/c/d，续审只补 c → 链式累计
        # {a,b,c} ⊉ {a,b,c,d} → 核销锁定（抢救红线）、锚保持
        seed_fp = _seed_open_item(self.proot, file_key="src/d.py",
                                  title="uncovered issue")
        self._seed_dead_run(
            ["src/a.py", "src/b.py", "src/c.py", "src/d.py"],
            ["src/a.py", "src/b.py"])
        runner = _CloseRunner(self.proot, "code-review-902", ["src/c.py"])
        result = run_code_review(
            runner, ["src/c.py", "src/d.py"],
            review_kind="scheduled", window_start=None, scope="full",
            redispatch_of=_DEAD_RUN)
        self.assertTrue(result.success)
        self.assertEqual(
            result.resolved, 0, "链式部分覆盖维持抢救红线不核销")
        items = read_items(self.proot)
        seeded = [r for r in items.values() if r.get("fingerprint") == seed_fp]
        self.assertEqual(seeded[0]["status"], "open")
        anchor = read_pending_writeoff(self.proot)
        self.assertEqual(anchor.get("run_id"), _DEAD_RUN, "锁定分支不清锚")
        joined = "\n".join(runner.logger.records)
        self.assertIn("全仓快照核销锁定", joined)


if __name__ == "__main__":
    unittest.main()
