"""test_review_snapshot_resolution.py — 快照核销前对账与核销来源分列测试
（evo-code-review-snapshot-writeoff-integrity 3.1）

覆盖（specs/review-writeoff-integrity R1-R5）：
- 同缺陷措辞漂移（相似度 ≥0.55）对账后保持 open 并迁移指纹，不计 resolved；
- 迁移去重（孪生合并）：同指纹仅一条台账条目、first_seen_at 保留、孪生被删；
- 对账 1:1 领用：两条未命中条目争同一观测只迁移一条（相似度最高者，
  并列取 last_seen_at 更近者）；
- 孪生非 open（in_spec/ignored）放弃迁移、旧条目按未命中语义核销；
- 真消失条目正常核销且 resolution='snapshot_closed'；
- 相似度低于阈值不误保（真缺陷不永久挂 open）；
- 完成行两计数分列（CodeReviewResult 字段 + admin_monitor 完成行格式）；
- snapshot_closed 核销不改变 code_fix 进度 done 与 chain_rollup 计数
  （code-fix 链 rollup/done 仅由 mark_resolved 真实命中累积，R4 不改码口径）；
- dashboard 投影透出 resolution；存量 resolution=None 条目按 snapshot_closed
  口径解读、不回填改写。

run 级链路（findings→观测记录传递→结果装配）经最小 runner 替身驱动真实
run_code_review；台账断言走 core.code_review.read_items 真实读侧。
"""

import difflib
import json
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from core.code_review import (
    SNAPSHOT_CLOSED_RESOLUTION,
    WRITEOFF_TITLE_SIMILARITY_THRESHOLD,
    fingerprint as cr_fingerprint,
    normalize_title,
    read_items,
    upsert_findings,
    write_items,
)
from core.dashboard.data.code_review import read_code_review_items


def _make_repo() -> Path:
    root = Path(tempfile.mkdtemp(prefix="cr-snapres-"))
    (root / ".fenix" / "code-review").mkdir(parents=True, exist_ok=True)
    return root


OLD_TITLE = "unused variable pid_int"
DRIFT_TITLE = "unused variable pid_int in loop"


def _sim(a: str, b: str) -> float:
    return difflib.SequenceMatcher(
        None, normalize_title(a), normalize_title(b)).ratio()


def _obs(file_key, category, title, **extra):
    """观测记录（与 maintenance_runs 收尾现算同口径：findings 即观测记录）。"""
    rec = {
        "file": file_key,
        "category": category,
        "title": title,
        "fingerprint": cr_fingerprint(file_key, category, title),
        "severity": "major",
        "description": f"desc {title}",
        "suggestion": f"fix {title}",
    }
    rec.update(extra)
    return rec


def _seed_item(proot, file_key, category, title, *, item_id=None, status="open",
               fp=None, last_seen_at=None, first_seen_at=None, **extra):
    """直写台账条目（绕过 upsert 的指纹去重，供多孪生/同题条目场景）。"""
    fp = fp or cr_fingerprint(file_key, category, title)
    rec = {
        "item_id": item_id or f"seed-{fp[:8]}",
        "project": Path(proot).name,
        "review_id": "run-seed",
        "review_kind": "manual_full",
        "reviewed_at": "2026-10-01T00:00:00+00:00",
        "status": status,
        "fingerprint": fp,
        "file": file_key,
        "line": 1,
        "severity": "major",
        "category": category,
        "title": title,
        "description": "seed",
        "suggestion": "seed",
        "first_seen_at": first_seen_at or "2026-10-01T00:00:00+00:00",
        "last_seen_at": last_seen_at or "2026-10-01T00:00:00+00:00",
    }
    rec.update(extra)
    # write_items 是全量替换语义：合并既有台账后回写，多条 seed 共存
    items = read_items(proot)
    items[rec["item_id"]] = rec
    write_items(proot, items.values())
    return rec


class TestDriftReconciliation(unittest.TestCase):
    """核销前对账（R1/R5）：resolve_snapshot 直驱。"""

    def setUp(self):
        self.proot = _make_repo()

    def tearDown(self):
        shutil.rmtree(str(self.proot), ignore_errors=True)

    def test_drift_title_reconciled_keeps_open_and_migrates_fingerprint(self):
        # 同缺陷措辞漂移（≥0.55）：本轮只观测到新措辞 → 旧条目不核销、
        # 指纹迁移为新指纹、保持 open、不产生 snapshot_closed 计数
        seed = _seed_item(self.proot, "src/a.py", "correctness", OLD_TITLE)
        self.assertGreaterEqual(
            _sim(OLD_TITLE, DRIFT_TITLE), WRITEOFF_TITLE_SIMILARITY_THRESHOLD)
        counts = resolve_snapshot(
            self.proot, [_obs("src/a.py", "correctness", DRIFT_TITLE)])
        self.assertEqual(counts, {"snapshot_closed": 0, "fixed": 0})
        items = read_items(self.proot)
        self.assertEqual(len(items), 1)
        rec = items[seed["item_id"]]
        self.assertEqual(rec["status"], "open", "漂移对账命中 MUST NOT 核销")
        new_fp = cr_fingerprint("src/a.py", "correctness", DRIFT_TITLE)
        self.assertEqual(rec["fingerprint"], new_fp, "指纹迁移为本轮新指纹")
        self.assertNotIn("resolution", rec)
        self.assertNotIn("resolved_at", rec)
        self.assertEqual(rec["first_seen_at"], seed["first_seen_at"],
                         "对账迁移不改写首见时间（龄期稳定）")

    def test_migration_dedup_merges_twin_deletes_twin(self):
        # 迁移去重（design 决策 5）：本轮 upsert 已插入同新指纹的 open 孪生 →
        # 迁移合并：保留存量条目（item_id/first_seen_at 稳定）、以观测记录
        # 刷新展示字段、删除孪生；同一 fingerprint 至多一条台账条目
        seed = _seed_item(self.proot, "src/a.py", "correctness", OLD_TITLE,
                          description="seed", suggestion="seed")
        new_fp = cr_fingerprint("src/a.py", "correctness", DRIFT_TITLE)
        _seed_item(self.proot, "src/a.py", "correctness", DRIFT_TITLE,
                   item_id="twin-1", fp=new_fp, first_seen_at="2026-10-29T00:00:00+00:00")
        obs = _obs("src/a.py", "correctness", DRIFT_TITLE, line=42, severity="critical")
        counts = resolve_snapshot(self.proot, [obs])
        self.assertEqual(counts, {"snapshot_closed": 0, "fixed": 0})
        items = read_items(self.proot)
        self.assertEqual(len(items), 1, "孪生合并后同指纹仅一条台账条目")
        rec = items[seed["item_id"]]
        self.assertEqual(rec["status"], "open")
        self.assertEqual(rec["fingerprint"], new_fp)
        self.assertEqual(rec["first_seen_at"], seed["first_seen_at"],
                         "保留存量条目（first_seen_at 稳定）")
        self.assertNotIn("twin-1", items, "本轮 upsert 插入的孪生条目被删除")
        # 展示字段随观测记录刷新
        self.assertEqual(rec["title"], DRIFT_TITLE)
        self.assertEqual(rec["line"], 42)
        self.assertEqual(rec["severity"], "critical")

    def test_one_to_one_claim_two_items_compete_for_one_observation(self):
        # 1:1 领用：一条观测至多对账一条存量条目（相似度最高者优先），
        # 被领用观测不得复用——落选者按未命中语义核销
        near_title = "unused variable pid_int maybe"  # 与观测相似度最高
        far_title = "unused variable pid_int"         # 相似度较低但仍 ≥0.55
        obs_title = "unused variable pid_int after loop"
        self.assertGreater(_sim(near_title, obs_title), _sim(far_title, obs_title))
        self.assertGreaterEqual(_sim(far_title, obs_title),
                                WRITEOFF_TITLE_SIMILARITY_THRESHOLD)
        near = _seed_item(self.proot, "src/a.py", "correctness", near_title,
                          item_id="near-1", fp="fp-near-0001")
        far = _seed_item(self.proot, "src/a.py", "correctness", far_title,
                         item_id="far-1", fp="fp-far-00001")
        counts = resolve_snapshot(
            self.proot, [_obs("src/a.py", "correctness", obs_title)])
        self.assertEqual(counts, {"snapshot_closed": 1, "fixed": 0})
        items = read_items(self.proot)
        self.assertEqual(items[near["item_id"]]["status"], "open",
                         "相似度最高者优先领用观测、迁移保持 open")
        self.assertEqual(items[near["item_id"]]["fingerprint"],
                         cr_fingerprint("src/a.py", "correctness", obs_title))
        far_rec = items[far["item_id"]]
        self.assertEqual(far_rec["status"], "resolved",
                         "观测被领用后不得复用，落选者按未命中核销")
        self.assertEqual(far_rec["resolution"], SNAPSHOT_CLOSED_RESOLUTION)

    def test_tie_breaks_by_recent_last_seen_at(self):
        # 并列（同相似度）取 last_seen_at 更近者领用观测
        obs_title = "shared drift title body"
        old = _seed_item(self.proot, "src/a.py", "correctness", "shared drift title",
                         item_id="old-1", fp="fp-old-00001",
                         last_seen_at="2026-10-01T00:00:00+00:00")
        recent = _seed_item(self.proot, "src/a.py", "correctness", "shared drift title",
                            item_id="new-1", fp="fp-new-00001",
                            last_seen_at="2026-10-28T00:00:00+00:00")
        counts = resolve_snapshot(
            self.proot, [_obs("src/a.py", "correctness", obs_title)])
        self.assertEqual(counts, {"snapshot_closed": 1, "fixed": 0})
        items = read_items(self.proot)
        self.assertEqual(items[recent["item_id"]]["status"], "open",
                         "并列时 last_seen_at 更近者领用观测")
        self.assertEqual(items[old["item_id"]]["status"], "resolved")

    def test_non_open_twin_abandons_migration_and_resolves(self):
        # 孪生非 open（in_spec，缺陷已由他条承载）→ 放弃迁移，旧条目按未命中
        # 语义核销（缺陷不失踪）；in_spec 孪生不触碰
        seed = _seed_item(self.proot, "src/a.py", "correctness", OLD_TITLE)
        new_fp = cr_fingerprint("src/a.py", "correctness", DRIFT_TITLE)
        _seed_item(self.proot, "src/a.py", "correctness", DRIFT_TITLE,
                   item_id="twin-in-spec", fp=new_fp, status="in_spec")
        counts = resolve_snapshot(
            self.proot, [_obs("src/a.py", "correctness", DRIFT_TITLE)])
        self.assertEqual(counts, {"snapshot_closed": 1, "fixed": 0})
        items = read_items(self.proot)
        self.assertEqual(items["twin-in-spec"]["status"], "in_spec",
                         "非 open 孪生不触碰")
        rec = items[seed["item_id"]]
        self.assertEqual(rec["status"], "resolved", "放弃迁移按未命中核销")
        self.assertEqual(rec["fingerprint"], seed["fingerprint"],
                         "放弃迁移不迁移指纹")
        self.assertEqual(rec["resolution"], SNAPSHOT_CLOSED_RESOLUTION)

    def test_truly_gone_item_resolved_with_snapshot_closed_marker(self):
        # 真消失（无相似观测）：正常核销且带 snapshot_closed 来源标记
        seed = _seed_item(self.proot, "src/gone.py", "perf", "totally unrelated issue")
        counts = resolve_snapshot(
            self.proot, [_obs("src/a.py", "correctness", DRIFT_TITLE)])
        self.assertEqual(counts, {"snapshot_closed": 1, "fixed": 0})
        rec = read_items(self.proot)[seed["item_id"]]
        self.assertEqual(rec["status"], "resolved")
        self.assertEqual(rec["resolution"], "snapshot_closed")
        self.assertTrue(rec.get("resolved_at"))
        self.assertEqual(rec["last_seen_at"], seed["last_seen_at"],
                         "last_seen_at 保持最后观测时刻不动")

    def test_below_threshold_not_falsely_kept_open(self):
        # R5 安全边界：相似度低于阈值不误保——真不同缺陷不被对账救回、正常核销
        weak_title = "naming convention violation for helper fn"
        self.assertLess(_sim(OLD_TITLE, weak_title),
                        WRITEOFF_TITLE_SIMILARITY_THRESHOLD)
        seed = _seed_item(self.proot, "src/a.py", "correctness", OLD_TITLE)
        counts = resolve_snapshot(
            self.proot, [_obs("src/a.py", "correctness", weak_title)])
        self.assertEqual(counts, {"snapshot_closed": 1, "fixed": 0})
        rec = read_items(self.proot)[seed["item_id"]]
        self.assertEqual(rec["status"], "resolved", "低相似度不误保")
        self.assertEqual(rec["resolution"], SNAPSHOT_CLOSED_RESOLUTION)

    def test_different_file_same_title_not_reconciled(self):
        # 对账分组键为同 file+category：同题不同文件不跨组领用
        seed = _seed_item(self.proot, "src/other.py", "correctness", OLD_TITLE)
        counts = resolve_snapshot(
            self.proot, [_obs("src/a.py", "correctness", DRIFT_TITLE)])
        self.assertEqual(counts, {"snapshot_closed": 1, "fixed": 0})
        self.assertEqual(read_items(self.proot)[seed["item_id"]]["status"], "resolved")

    def test_return_shape_fixed_placeholder_and_legacy_string_obs(self):
        # 返回值口径（design 决策 6）：{'snapshot_closed': n, 'fixed': 0}（本
        # 函数不产生合回核销，fixed 恒 0 占位）；兼容裸指纹字符串观测形态
        # （无 file/title 的记录不参与对账、仅按指纹命中）
        hit = _seed_item(self.proot, "src/a.py", "correctness", OLD_TITLE,
                         item_id="hit-1", fp="fp-hit-0000001")
        gone = _seed_item(self.proot, "src/gone.py", "perf", "unrelated issue",
                          item_id="gone-1", fp="fp-gone-0000001")
        counts = resolve_snapshot(self.proot, [hit["fingerprint"]])
        self.assertEqual(counts, {"snapshot_closed": 1, "fixed": 0})
        items = read_items(self.proot)
        self.assertEqual(items["hit-1"]["status"], "open",
                         "裸指纹命中的条目保持 open")
        self.assertEqual(items["gone-1"]["status"], "resolved")

    def test_fingerprint_less_open_item_kept_open(self):
        # fingerprint 缺失的 open 条目不参与比对：跳过核销保持 open（既有红线）
        _seed_item(self.proot, "src/a.py", "correctness", OLD_TITLE, fp="")
        counts = resolve_snapshot(
            self.proot, [_obs("src/a.py", "correctness", DRIFT_TITLE)])
        self.assertEqual(counts, {"snapshot_closed": 0, "fixed": 0})
        items = read_items(self.proot)
        self.assertEqual(list(items.values())[0]["status"], "open")


class TestEndToEndDriftRun(unittest.TestCase):
    """run 级链路（findings→观测记录→核销→结果装配，R2/R3）经真实
    run_code_review 收尾链驱动。"""

    def setUp(self):
        self.proot = _make_repo()

    def tearDown(self):
        shutil.rmtree(str(self.proot), ignore_errors=True)

    def _run_full(self, run_id, out_rows, manifest):
        from core.agent_runner.maintenance_runs import run_code_review

        runner = _Runner(self.proot, run_id, out_rows=out_rows)
        return run_code_review(
            runner, manifest,
            review_kind="scheduled", window_start=None, scope="full")

    def test_drift_run_migrates_and_reports_zero_snapshot_closed(self):
        # 措辞漂移夜：upsert 先插新指纹孪生 → 核销对账合并迁移 → 台账仅存量
        # 条目保持 open；结果信封 snapshot_closed=0（不产生假清零）
        seed = _seed_item(self.proot, "src/a.py", "correctness", OLD_TITLE)
        result = self._run_full(
            "code-review-drift-1",
            [{"file": "src/a.py",
              "findings": [{"category": "correctness", "title": DRIFT_TITLE,
                            "severity": "major", "description": "d",
                            "suggestion": "s", "line": 9}]}],
            ["src/a.py"])
        self.assertTrue(result.success)
        # 两计数分列字段（R3）：漂移夜零快照核销
        self.assertEqual(result.snapshot_closed, 0)
        self.assertEqual(result.fixed, 0)
        self.assertEqual(result.resolved, 0, "resolved 兼容别名与分列计数一致")
        items = read_items(self.proot)
        self.assertEqual(len(items), 1, "漂移夜不产生新条目（孪生合并）")
        rec = items[seed["item_id"]]
        self.assertEqual(rec["status"], "open")
        self.assertEqual(rec["fingerprint"],
                         cr_fingerprint("src/a.py", "correctness", DRIFT_TITLE))
        self.assertEqual(rec["first_seen_at"], seed["first_seen_at"])
        # 下一轮同措辞直接命中：正常观测刷新，不核销、不迁移
        result2 = self._run_full(
            "code-review-drift-2",
            [{"file": "src/a.py",
              "findings": [{"category": "correctness", "title": DRIFT_TITLE,
                            "severity": "major", "description": "d",
                            "suggestion": "s", "line": 9}]}],
            ["src/a.py"])
        self.assertEqual(result2.snapshot_closed, 0)
        items2 = read_items(self.proot)
        self.assertEqual(len(items2), 1)
        self.assertEqual(items2[seed["item_id"]]["status"], "open")

    def test_gone_item_run_resolves_with_split_counts(self):
        # 真消失夜：未再观测条目核销，结果信封两计数分列（snapshot_closed=1,
        # fixed=0）
        _seed_item(self.proot, "src/gone.py", "perf", "stale issue gone")
        result = self._run_full(
            "code-review-gone-1",
            [{"file": "src/a.py",
              "findings": [{"category": "correctness", "title": "fresh issue",
                            "severity": "major", "description": "d",
                            "suggestion": "s"}]}],
            ["src/a.py"])
        self.assertTrue(result.success)
        self.assertEqual(result.snapshot_closed, 1)
        self.assertEqual(result.fixed, 0)
        self.assertEqual(result.resolved, 1)
        items = read_items(self.proot)
        resolved = [r for r in items.values() if r["status"] == "resolved"]
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["resolution"], SNAPSHOT_CLOSED_RESOLUTION)


class _FakeLogger:
    def __init__(self):
        self.records = []

    def info(self, tag, message):
        self.records.append(f"INFO {tag} {message}")

    def warning(self, tag, message):
        self.records.append(f"WARNING {tag} {message}")

    def error(self, tag, message):
        self.records.append(f"ERROR {tag} {message}")


class _Runner:
    """最小 runner 替身（同 test_code_review_salvage_writeoff 形态）：
    _run_agent 写真实 out 产物文件，聚合读取/落账/核销链路全走生产代码。"""

    def __init__(self, proot, run_id, out_rows=None):
        self.project_root = Path(proot)
        self.logger = _FakeLogger()
        self.config = {}
        self._run_id = run_id
        self._out_rows = out_rows or []

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
        path.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in self._out_rows),
            encoding="utf-8")

    def _run_agent(self, prompt, root, run_id, model_override, env_overrides,
                   max_turns=None, spec_name=None, agent_type=None):
        self._write_out()
        return ("output", 3, "session", {}, None)

    def _extract_usage_info(self, x):
        return {}

    def _accumulate_code_review_tokens(self, run_id, usage):
        return None

    def _read_code_review_out(self, project_root, run_id):
        from core.agent_runner import maintenance_runs

        return maintenance_runs._read_code_review_out(self, project_root, run_id)


class TestWriteoffCountsSplit(unittest.TestCase):
    """完成行两计数分列（R3）：CodeReviewResult 字段与 admin_monitor 完成行格式。"""

    def test_code_review_result_carries_split_fields(self):
        from core.agent_runner.result_gate import CodeReviewResult

        r = CodeReviewResult(run_id="r1", inserted=2, updated=1,
                             resolved=3, snapshot_closed=3, fixed=1)
        self.assertEqual(r.snapshot_closed, 3)
        self.assertEqual(r.fixed, 1)
        # 兼容别名：缺省 0，老构造方（既有测试/消费方）不受影响
        r2 = CodeReviewResult(run_id="r2", resolved=2)
        self.assertEqual(r2.snapshot_closed, 0)
        self.assertEqual(r2.fixed, 0)
        self.assertEqual(r2.resolved, 2)

    def test_completion_line_note_splits_counts(self):
        from core.admin_monitor import code_review_writeoff_counts_note
        from core.agent_runner.result_gate import CodeReviewResult

        note = code_review_writeoff_counts_note(
            CodeReviewResult(run_id="r", snapshot_closed=214, fixed=7))
        self.assertEqual(note, "snapshot_closed=214, fixed=7")
        self.assertNotIn("resolved=", note, "完成行不再输出单值 resolved")

    def test_admin_monitor_completion_line_format(self):
        # 真实巡检收尾链：fake runner 返回分列计数 → 完成行按
        # snapshot_closed/fixed 两计数输出
        from core.admin_monitor import AdminMonitor
        from core.agent_runner.result_gate import CodeReviewResult

        proot = _make_repo()
        logger = _FakeLogger()

        class _R:
            _running_agents = {}

            def run_code_review(self, *args, **kwargs):
                return CodeReviewResult(
                    run_id="code-review-live", success=True,
                    inserted=0, updated=0, resolved=2,
                    snapshot_closed=2, fixed=0, shards=0)

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
                       return_value=(datetime(2026, 10, 30, 2, 0, 0), "self_review")),
            mock.patch("core.code_review.collect_manifest",
                       return_value=["src/a.py"]),
            mock.patch("core.code_review.read_code_review_state", return_value={}),
            mock.patch("core.code_review.save_code_review_state"),
        ]
        try:
            for p in patches:
                p.start()
            mon._run_code_review_checkpoint()
            joined = "\n".join(logger.records)
            self.assertIn("snapshot_closed=2, fixed=0", joined)
            self.assertNotIn("resolved=2", joined, "完成行不再单值输出 resolved")
        finally:
            for p in patches:
                p.stop()
            shutil.rmtree(str(proot), ignore_errors=True)


class TestCodeFixCountsUnaffected(unittest.TestCase):
    """R4 不改码口径锁定：snapshot_closed 核销不改变 code_fix 进度 done 与
    chain_rollup 计数（链 rollup/done 仅由 mark_resolved 真实命中累积）。"""

    def setUp(self):
        self.proot = _make_repo()

    def tearDown(self):
        shutil.rmtree(str(self.proot), ignore_errors=True)

    def test_snapshot_writeoff_leaves_fix_progress_and_rollup_untouched(self):
        from core.code_fix import read_progress, write_progress

        # 预置在飞的 code_fix 进度现场（done=5 / chain_resolved=3 / rollup 在位）
        write_progress(
            self.proot,
            running=True, phase="fixing", total=10, done=5,
            chain_resolved=3, chain_ignored=1,
            chain_rollup={"runs": 2, "resolved": 3, "ignored": 1, "turns": 30},
        )
        before = read_progress(self.proot)
        # 快照核销一轮：未观测条目批量置 resolved（snapshot_closed）
        _seed_item(self.proot, "src/a.py", "correctness", "issue one")
        _seed_item(self.proot, "src/b.py", "perf", "issue two")
        counts = resolve_snapshot(self.proot, [])
        self.assertEqual(counts, {"snapshot_closed": 2, "fixed": 0})
        items = read_items(self.proot)
        self.assertEqual(
            {r["resolution"] for r in items.values()}, {SNAPSHOT_CLOSED_RESOLUTION})
        # code_fix 进度 done 与 chain_rollup 计数零变化（核销不入修复成果）
        after = read_progress(self.proot)
        self.assertEqual(after["done"], before["done"])
        self.assertEqual(after["done"], 5)
        self.assertEqual(after["chain_resolved"], before["chain_resolved"])
        self.assertEqual(after["chain_resolved"], 3)
        self.assertEqual(after["chain_rollup"], before["chain_rollup"])
        self.assertEqual(after["chain_rollup"]["resolved"], 3)
        self.assertEqual(after["running"], True)

    def test_fresh_project_writeoff_creates_no_fix_progress(self):
        # 空项目快照核销不产生 code_fix 进度文件（无链激活、无计数泄漏）
        from core.code_fix import read_progress

        _seed_item(self.proot, "src/a.py", "correctness", "issue one")
        counts = resolve_snapshot(self.proot, [])
        self.assertEqual(counts, {"snapshot_closed": 1, "fixed": 0})
        progress_file = self.proot / ".fenix" / "code-review" / "fix-progress.json"
        self.assertFalse(progress_file.exists(), "核销 MUST NOT 触发 code_fix 进度写入")
        progress = read_progress(self.proot)
        self.assertEqual(progress["done"], 0)
        self.assertEqual(progress["chain_resolved"], 0)
        self.assertIsNone(progress["chain_rollup"])


class TestDashboardResolutionProjection(unittest.TestCase):
    """R4 消费口径：dashboard 投影透出 resolution；存量 None 不回填。"""

    def setUp(self):
        self.proot = _make_repo()

    def tearDown(self):
        shutil.rmtree(str(self.proot), ignore_errors=True)

    def test_resolution_field_passthrough(self):
        # 台账投影 rows 为完整记录 dict：resolution 字段随行透出
        _seed_item(self.proot, "src/gone.py", "perf", "stale issue")
        resolve_snapshot(self.proot, [])
        rows = read_code_review_items(self.proot, statuses=["resolved"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["resolution"], SNAPSHOT_CLOSED_RESOLUTION)

    def test_legacy_none_resolution_reads_as_snapshot_closed_without_backfill(self):
        # 存量 resolution=None 历史条目：投影原样透出（None），按快照关闭
        # 口径解读；落盘文件不被回填改写
        fp = cr_fingerprint("src/legacy.py", "style", "legacy issue")
        rec = {
            "item_id": "legacy-1",
            "project": Path(self.proot).name,
            "status": "resolved",
            "fingerprint": fp,
            "file": "src/legacy.py",
            "line": 3,
            "severity": "minor",
            "category": "style",
            "title": "legacy issue",
            "description": "",
            "suggestion": "",
            "first_seen_at": "2026-09-01T00:00:00+00:00",
            "last_seen_at": "2026-09-01T00:00:00+00:00",
            "resolved_at": "2026-10-19T18:36:50+00:00",
            # 2026-10-19 假核销夜的存量形态：无 resolution 字段
        }
        write_items(self.proot, [rec])
        items_path = self.proot / ".fenix" / "code-review" / "items.jsonl"
        raw_before = items_path.read_text(encoding="utf-8")
        rows = read_code_review_items(self.proot, statuses=["resolved"])
        self.assertEqual(len(rows), 1)
        self.assertNotIn("resolution", rows[0], "存量条目投影原样透出（None 语义）")
        # 投影读取不回填落盘：文件内容逐字节不变
        self.assertEqual(items_path.read_text(encoding="utf-8"), raw_before)
        # 后续核销轮次也不回填存量（resolve_snapshot 只写未命中 open 条目）
        _seed_item(self.proot, "src/new.py", "perf", "another issue")
        resolve_snapshot(self.proot, [])
        self.assertIn("legacy-1", read_items(self.proot))
        raw_after = items_path.read_text(encoding="utf-8")
        legacy_rows = [json.loads(l) for l in raw_after.splitlines()
                       if l.strip() and json.loads(l).get("item_id") == "legacy-1"]
        self.assertEqual(len(legacy_rows), 1)
        self.assertNotIn("resolution", legacy_rows[0], "存量 resolution=None 不回填改写")


# resolve_snapshot 延迟导入（模块级 import 会与文件头 from-import 并存冗余；
# 统一放类外供两类共用）
from core.code_review import resolve_snapshot  # noqa: E402


if __name__ == "__main__":
    unittest.main()
