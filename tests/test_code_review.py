"""test_code_review.py — code-review 车道核心逻辑测试（add-code-review-agent-and-quality-tab）

覆盖 tasks 7.3-7.6：
- 7.3: 指纹稳定性（大小写/空白归一）、去重 upsert（同 fingerprint 不增条目、
  只更新 last_seen_at）、快照核销（manual_full 核销、window 不核销、不动
  in_spec/ignored）、窗口计算（有/无 last_run_at）、命名消解（基名/冲突后缀/
  仍冲突报错）、lint 不通过不半写、生成幂等、skipped 语义。
- 7.4: agent 类型四处注册一致性（AGENT_PROMPT_FILES / RUN_ID_AGENT_PREFIXES /
  KNOWN_AGENT_TYPES / agents/code-review.md 存在），infer_run_agent_type。
- 7.5: get_code_review_config（缺省 enabled=False、非法 max_files 回退缺省）；
  开关关闭时 checkpoint 零动作（不派发、不写产物）。
- 7.6: admin.code_review 的 Dashboard 读写链路——write_config 落盘后 read_config
  回显该子键；非法 enabled / max_files 被前置校验拒绝。
"""

import json
import logging
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

# /tmp 可能被外部清扫进程周期性清空（2026-09-19 实测），导致 mkdtemp 竞态失败。
# 本文件内统一用显式 dir= 指到仓库内 .history/tmp（gitignored）——MUST NOT
# 改写全局 tempfile.tempdir（会污染同进程内所有按字母序后置的测试文件）。
_HISTORY_TMP = Path(__file__).resolve().parent.parent / ".history" / "tmp"
_HISTORY_TMP.mkdir(parents=True, exist_ok=True)


def _mkdtemp(prefix: str) -> str:
    """在 .history/tmp 下建临时目录（显式 dir=，不触碰全局 tempfile 状态）。"""
    return tempfile.mkdtemp(prefix=prefix, dir=str(_HISTORY_TMP))


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo)] + list(args), capture_output=True, text=True)


def _make_repo() -> Path:
    """建一个带 core/a.py 等受控源码文件的临时 git 仓库（供 manifest/generate 测试）。"""
    td = _mkdtemp("cr-test-")
    repo = Path(td) / "proj"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    src = repo / "core"
    src.mkdir()
    (src / "a.py").write_text("x=1\n")
    (src / "b.py").write_text("y=2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return repo


# ── 7.3 指纹与去重 ────────────────────────────────────────────────


class TestFingerprint(unittest.TestCase):
    def test_stability_across_case_whitespace(self):
        from core.code_review import fingerprint

        fp1 = fingerprint("core/a.py", "correctness", "  Undefined  Variable  X  ")
        fp2 = fingerprint("core/a.py", "correctness", "undefined variable x")
        self.assertEqual(fp1, fp2)

    def test_different_file_different_fp(self):
        from core.code_review import fingerprint

        self.assertNotEqual(
            fingerprint("core/a.py", "correctness", "t"),
            fingerprint("core/b.py", "correctness", "t"),
        )

    def test_length_12(self):
        from core.code_review import fingerprint

        self.assertEqual(len(fingerprint("core/a.py", "c", "t")), 12)


class TestUpsertDedup(unittest.TestCase):
    def setUp(self):
        from core.code_review import read_items

        self.repo = _make_repo()
        self._read_items = read_items

    def tearDown(self):
        import shutil

        shutil.rmtree(str(self.repo.parent), ignore_errors=True)

    def test_insert_then_update_last_seen(self):
        from core.code_review import upsert_findings

        findings = [{
            "file": "core/a.py", "category": "correctness", "title": "Undefined variable x",
            "severity": "major", "description": "d", "suggestion": "s", "evidence": "e", "line": 3,
        }]
        r1 = upsert_findings(self.repo, findings, "code-review-1", "manual_full")
        self.assertEqual(r1, {"inserted": 1, "updated": 0})
        items = self._read_items(self.repo)
        self.assertEqual(len(items), 1)
        rec = next(iter(items.values()))
        self.assertEqual(rec["status"], "open")
        self.assertEqual(rec["first_seen_at"], rec["last_seen_at"])
        item_id = rec["item_id"]
        # 重复观测：只更新 last_seen_at（刷新），不增条目、不动 first_seen_at
        r2 = upsert_findings(self.repo, findings, "code-review-2", "scheduled")
        self.assertEqual(r2, {"inserted": 0, "updated": 1})
        items2 = self._read_items(self.repo)
        self.assertEqual(len(items2), 1)
        self.assertNotEqual(items2[item_id]["last_seen_at"], rec["last_seen_at"])
        self.assertEqual(items2[item_id]["first_seen_at"], rec["first_seen_at"])

    def test_review_kind_and_spec_map(self):
        from core.code_review import fingerprint, upsert_findings

        findings = [{
            "file": "core/a.py", "category": "perf", "title": "N+1",
            "severity": "info", "description": "", "suggestion": "", "evidence": "",
        }]
        upsert_findings(self.repo, findings, "code-review-3", "manual_window")
        items = self._read_items(self.repo)
        rec = next(iter(items.values()))
        self.assertEqual(rec["review_kind"], "manual_window")
        self.assertEqual(rec["review_id"], "code-review-3")


class TestNormalizeSeverity(unittest.TestCase):
    def test_drift_values_map_to_contract(self):
        # ocr scan 透传的漂移值域 high/medium/low → 契约四档（口径同
        # dashboard/data/artifacts.py 的 verify-bugs 归一）
        from core.code_review import normalize_severity

        self.assertEqual(normalize_severity("high"), "major")
        self.assertEqual(normalize_severity("medium"), "major")
        self.assertEqual(normalize_severity("low"), "minor")

    def test_contract_values_and_fallbacks(self):
        # 四档原样；空/缺失回 info（原 `or "info"` 缺省语义）；未知值透传
        # （fail-open，读侧/前端有兜底排序与色系）
        from core.code_review import normalize_severity

        for v in ("critical", "major", "minor", "info"):
            self.assertEqual(normalize_severity(v), v)
        self.assertEqual(normalize_severity(""), "info")
        self.assertEqual(normalize_severity(None), "info")
        self.assertEqual(normalize_severity("weird"), "weird")


class TestUpsertAndReadSeverityNormalize(unittest.TestCase):
    def setUp(self):
        self.repo = _make_repo()

    def tearDown(self):
        import shutil

        shutil.rmtree(str(self.repo.parent), ignore_errors=True)

    def test_upsert_normalizes_drift_severity(self):
        # 写侧：漂移 severity 落台账即归一（新写入路径）
        from core.code_review import read_items, upsert_findings

        findings = [{
            "file": "core/a.py", "category": "style", "title": "漂移条目",
            "severity": "high", "description": "d", "suggestion": "s", "evidence": "e",
        }]
        upsert_findings(self.repo, findings, "code-review-n", "scheduled")
        rec = next(iter(read_items(self.repo).values()))
        self.assertEqual(rec["severity"], "major")

    def test_read_side_normalizes_legacy_rows(self):
        # 读侧：盘上存量漂移行（写侧归一前落盘的）在 API 读出时归一——
        # 零数据迁移，消费端（排序/过滤/色系）按四档生效
        import json as _json

        from core.code_review import items_path
        from core.dashboard.data.code_review import read_code_review_items

        legacy = {
            "item_id": "legacy-1", "status": "open", "severity": "medium",
            "file": "core/b.py", "line": 1, "category": "style",
            "title": "存量漂移行", "fingerprint": "fp-legacy-1",
        }
        path = items_path(self.repo)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(_json.dumps(legacy) + "\n")
        rows = read_code_review_items(self.repo)
        row = next(r for r in rows if r["item_id"] == "legacy-1")
        self.assertEqual(row["severity"], "major")


class TestSnapshotResolution(unittest.TestCase):
    def setUp(self):
        self.repo = _make_repo()
        from core.code_review import upsert_findings

        self.upsert = upsert_findings
        # 两条 open 条目：a 仍在观测、b 不再观测
        self.upsert(self.repo, [
            {"file": "core/a.py", "category": "correctness", "title": "A issue",
             "severity": "major", "description": "", "suggestion": "", "evidence": ""},
            {"file": "core/b.py", "category": "perf", "title": "B issue",
             "severity": "minor", "description": "", "suggestion": "", "evidence": ""},
        ], "code-review-1", "manual_full")

    def tearDown(self):
        import shutil

        shutil.rmtree(str(self.repo.parent), ignore_errors=True)

    def _fp_of(self, category, title):
        from core.code_review import fingerprint

        return fingerprint("core/a.py", category, title)

    def test_full_snapshot_resolves_unobserved(self):
        # 观测记录集入参（evo-code-review-snapshot-writeoff-integrity 3.2
        # 迁移）：入参由指纹集合扩展为观测记录（file/category/title/新指纹），
        # 语义断言保持等价——a 命中保持 open、b 未观测被核销
        from core.code_review import read_items, resolve_snapshot

        a_fp = self._fp_of("correctness", "A issue")
        n = resolve_snapshot(self.repo, [
            {"file": "core/a.py", "category": "correctness", "title": "A issue",
             "fingerprint": a_fp},
        ])
        self.assertEqual(n, {"snapshot_closed": 1, "fixed": 0})
        items = read_items(self.repo)
        statuses = {it["status"] for it in items.values()}
        self.assertIn("resolved", statuses)
        self.assertIn("open", statuses)
        # resolved 的条目是 b（未再观测）
        resolved = [it for it in items.values() if it["status"] == "resolved"]
        self.assertEqual(resolved[0]["file"], "core/b.py")
        self.assertTrue(resolved[0].get("resolved_at"))
        # 快照核销统一带来源标记（R4），与合回核销 code-fix-auto 区分
        self.assertEqual(resolved[0].get("resolution"), "snapshot_closed")

    def test_does_not_touch_in_spec_ignored(self):
        from core.code_review import read_items, resolve_snapshot

        items = read_items(self.repo)
        # 把 a 置 in_spec、b 置 ignored（直接写记录模拟既有状态）
        for it in items.values():
            it["status"] = "in_spec" if it["file"] == "core/a.py" else "ignored"
        from core.code_review import write_items

        write_items(self.repo, items.values())
        # 空观测记录集（兼容裸指纹集合形态的旧调用方语义）
        n = resolve_snapshot(self.repo, [])
        self.assertEqual(n, {"snapshot_closed": 0, "fixed": 0})
        items2 = read_items(self.repo)
        for it in items2.values():
            self.assertIn(it["status"], ("in_spec", "ignored"))


class TestComputeWindow(unittest.TestCase):
    def test_with_last_run_at(self):
        import time as _time

        from datetime import datetime

        from core.code_review import compute_window

        td = _mkdtemp("cr-win-")
        try:
            fenix = Path(td) / ".fenix"
            fenix.mkdir()
            (fenix / "self_review_state.json").write_text(
                json.dumps({"last_run_at": "2026-09-01T10:00:00"}), encoding="utf-8"
            )
            ws, kind = compute_window(td)
            self.assertEqual(kind, "last_run")
            self.assertEqual(ws.day, 1)
            self.assertEqual(ws.hour, 10)
        finally:
            import shutil

            shutil.rmtree(td, ignore_errors=True)

    def test_fallback_24h(self):
        from datetime import datetime, timedelta

        from core.code_review import compute_window

        td = _mkdtemp("cr-win2-")
        try:
            ws, kind = compute_window(td)
            self.assertEqual(kind, "fallback")
            # SPEC-B 批④：window_start 迁 aware（本地表述）——对照钟同迁
            now = datetime.now().astimezone()
            self.assertLess(abs((now - ws).total_seconds() - 24 * 3600), 60)
        finally:
            import shutil

            shutil.rmtree(td, ignore_errors=True)


# ── 7.3 生成修复 SPEC ─────────────────────────────────────────────


class _FakeSM:
    def __init__(self, names=None):
        self.names = set(names or [])

    def read_all(self):
        return {n: {} for n in self.names}

    def add_spec(self, name, entry):
        if name in self.names:
            return False
        self.names.add(name)
        return True


class TestGenerateFixSpec(unittest.TestCase):
    def setUp(self):
        from core.code_review import read_items, upsert_findings

        self.repo = _make_repo()
        self.upsert = upsert_findings
        self.read_items = read_items
        self.sm = _FakeSM()
        self.upsert(self.repo, [
            # severity 用 major：本组用例覆盖 SPEC 生成机制而非 severity 门限
            #（evo-add-codefix-severity-batch-gate 起低于缺省门限 major 的
            # minor/info 条目在候选层挂起，会改写本组断言的候选集）
            {"file": "core/a.py", "category": "unused-import", "title": "Unused import os",
             "severity": "major", "description": "d", "suggestion": "s", "evidence": "e", "line": 1},
            {"file": "core/b.py", "category": "correctness", "title": "None deref",
             "severity": "major", "description": "d", "suggestion": "s", "evidence": "e", "line": 2},
            {"file": "core/missing.py", "category": "perf", "title": "Missing file issue",
             "severity": "info", "description": "d", "suggestion": "s", "evidence": "e"},
        ], "code-review-1", "manual_full")
        # 第 3 条指向不存在的文件：本用例用不到（skip 语义在单独用例覆盖）

    def tearDown(self):
        import shutil

        shutil.rmtree(str(self.repo.parent), ignore_errors=True)

    def _ids(self):
        items = self.read_items(self.repo)
        return {it["file"]: iid for iid, it in items.items()}

    def test_generate_success_sets_in_spec(self):
        from core.code_review import generate_fix_spec

        ids = self._ids()
        res = generate_fix_spec(self.repo, self.sm, [ids["core/a.py"], ids["core/b.py"]])
        self.assertTrue(res["ok"], res)
        self.assertTrue(res["spec_name"].startswith("fix-cr-"), res)
        self.assertIsNone(res["error"])
        # spec 目录 + 文件齐全
        spec_dir = self.repo / "spec" / "changes" / res["spec_name"]
        self.assertTrue(spec_dir.is_dir())
        for f in ("proposal.md", "design.md", "tasks.md", ".spec.yaml"):
            self.assertTrue((spec_dir / f).is_file(), f)
        tasks_text = (spec_dir / "tasks.md").read_text(encoding="utf-8")
        self.assertIn("## Deliverables", tasks_text)
        self.assertIn("core/a.py", tasks_text)
        self.assertIn("kind: modify", tasks_text)
        # 已提交
        log = _git(self.repo, "log", "--oneline", "-3").stdout
        self.assertIn(f"[fenix] spec: {res['spec_name']}", log)
        # 条目置 in_spec
        items = self.read_items(self.repo)
        for it in items.values():
            if it["file"] in ("core/a.py", "core/b.py"):
                self.assertEqual(it["status"], "in_spec")
                self.assertEqual(it["spec_name"], res["spec_name"])

    def test_idempotent_resubmit(self):
        from core.code_review import generate_fix_spec

        ids = self._ids()
        res1 = generate_fix_spec(self.repo, self.sm, [ids["core/a.py"], ids["core/b.py"]])
        self.assertTrue(res1["ok"])
        res2 = generate_fix_spec(self.repo, self.sm, [ids["core/a.py"], ids["core/b.py"]])
        self.assertTrue(res2["ok"], res2)
        self.assertEqual(res2["spec_name"], res1["spec_name"])
        self.assertTrue(res2.get("idempotent"), res2)

    def test_skip_non_open(self):
        from core.code_review import generate_fix_spec

        ids = self._ids()
        # 先成功生成 a
        res1 = generate_fix_spec(self.repo, self.sm, [ids["core/a.py"]])
        self.assertTrue(res1["ok"])
        # 再提交 [a(in_spec), b(open)] → a 进 skipped，只看 b
        res2 = generate_fix_spec(self.repo, self.sm, [ids["core/a.py"], ids["core/b.py"]])
        self.assertTrue(res2["ok"], res2)
        self.assertTrue(any(s.get("item_id") == ids["core/a.py"] for s in res2["skipped"]), res2)

    def test_missing_file_skipped_not_failed(self):
        from core.code_review import generate_fix_spec

        ids = self._ids()
        # core/missing.py 在主树不存在：modify 声明 lint 必拦 → 无有效条目确认 missing 进 skipped
        res = generate_fix_spec(self.repo, self.sm, [ids["core/missing.py"]])
        self.assertFalse(res["ok"], res)
        self.assertTrue(res["error"], res)

    def test_no_valid_items_error(self):
        from core.code_review import generate_fix_spec

        res = generate_fix_spec(self.repo, self.sm, ["nonexistent"])
        self.assertFalse(res["ok"])
        self.assertTrue(res["error"])
        self.assertEqual(len(res["skipped"]), 1)


class _RecordingSM(_FakeSM):
    """记录 add_spec 收到的 entry（供 start_after 透传断言）。"""

    def __init__(self, names=None):
        super().__init__(names)
        self.entries = {}

    def add_spec(self, name, entry):
        ok = super().add_spec(name, entry)
        if ok:
            self.entries[name] = dict(entry)
        return ok


class TestGenerateFixSpecContent(unittest.TestCase):
    """生成 SPEC 的正文必须带上问题内容（description/suggestion/evidence）。

    2026-09-20 用户反馈：原实现四份文档只写标题 + 文件:行，修复 agent 拿不到
    问题内容，无法正确理解要修什么。
    """

    def setUp(self):
        from core.code_review import upsert_findings

        self.repo = _make_repo()
        self.sm = _RecordingSM()
        upsert_findings(self.repo, [
            {"file": "core/a.py", "category": "correctness", "title": "None deref",
             "severity": "critical", "line": 7,
             "description": "Deref of possibly-None value at core/a.py:7.",
             "suggestion": "Guard with a None check.",
             "evidence": "core/a.py:7（ocr scan）"},
            {"file": "core/b.py", "category": "perf", "title": "Repeated IO",
             # severity 用 major：本组覆盖 SPEC 正文内容渲染而非 severity 门限
             #（evo-add-codefix-severity-batch-gate 起低于缺省门限的条目在
             # 候选层挂起，会改写本组断言的候选集）
             "severity": "major", "line": 3,
             "description": "File is read once per iteration.",
             "suggestion": "",  # suggestion 可为空：缺失时整段 MUST NOT 渲染
             "evidence": "core/b.py:3"},
        ], "code-review-c1", "manual_full")
        self.item_ids = self._ids()

    def tearDown(self):
        import shutil

        shutil.rmtree(str(self.repo.parent), ignore_errors=True)

    def _ids(self):
        from core.code_review import read_items

        return {it["file"]: iid for iid, it in read_items(self.repo).items()}

    def test_content_written_to_all_documents(self):
        from core.code_review import generate_fix_spec

        res = generate_fix_spec(self.repo, self.sm, list(self.item_ids.values()))
        self.assertTrue(res["ok"], res)
        spec_dir = self.repo / "spec" / "changes" / res["spec_name"]

        for doc in ("proposal.md", "design.md"):
            text = (spec_dir / doc).read_text(encoding="utf-8")
            self.assertIn("Deref of possibly-None value", text, doc)
            self.assertIn("Guard with a None check.", text, doc)
            self.assertIn("ocr scan", text, doc)
            self.assertIn("File is read once per iteration.", text, doc)

        # specs/<cap>/spec.md 同样带内容
        spec_md = next((spec_dir / "specs").rglob("spec.md"))
        spec_text = spec_md.read_text(encoding="utf-8")
        self.assertIn("Deref of possibly-None value", spec_text)
        self.assertIn("Guard with a None check.", spec_text)

        # tasks.md：完整内容以缩进子项挂在任务行下
        tasks = (spec_dir / "tasks.md").read_text(encoding="utf-8")
        self.assertIn("Deref of possibly-None value", tasks)
        self.assertIn("Guard with a None check.", tasks)

    def test_empty_suggestion_omits_section(self):
        from core.code_review import generate_fix_spec

        res = generate_fix_spec(self.repo, self.sm, list(self.item_ids.values()))
        self.assertTrue(res["ok"], res)
        proposal = (self.repo / "spec" / "changes" / res["spec_name"] / "proposal.md").read_text(
            encoding="utf-8"
        )
        # core/b.py 的 suggestion 为空：两份条目的「修复建议」段数 = 1（仅 a.py）
        self.assertEqual(proposal.count("**修复建议**"), 1, proposal)

    def test_tasks_md_still_parseable(self):
        """任务行 MUST 保持 `^- [ ] N.N <标题>` 行首形态（进度跟踪正则）。"""
        from core.code_review import generate_fix_spec
        from core.run_task_track import parse_tasks_md

        res = generate_fix_spec(self.repo, self.sm, list(self.item_ids.values()))
        self.assertTrue(res["ok"], res)
        all_ids, checked = parse_tasks_md(self.repo, res["spec_name"])
        self.assertEqual(all_ids, ["1.1", "1.2"], all_ids)
        self.assertEqual(checked, set())

    def test_deliverables_dedup_same_file(self):
        """多个问题指向同一文件时 Deliverables MUST NOT 重复声明。"""
        from core.code_review import upsert_findings, generate_fix_spec

        upsert_findings(self.repo, [
            {"file": "core/a.py", "category": "style", "title": "Second issue in a.py",
             "severity": "minor", "line": 9, "description": "d2",
             "suggestion": "", "evidence": "e2"},
        ], "code-review-c2", "manual_full")
        ids = self._ids()
        res = generate_fix_spec(self.repo, self.sm, [ids["core/a.py"]])
        self.assertTrue(res["ok"], res)
        tasks = (self.repo / "spec" / "changes" / res["spec_name"] / "tasks.md").read_text(
            encoding="utf-8"
        )
        decl = tasks.split("```")[1]
        self.assertEqual(decl.count("path: core/a.py"), 1, decl)


class TestGenerateFixSpecStartAfter(unittest.TestCase):
    """start_after 三态随 SPEC 注册透传（立即 / 定时 / 手工激活哨兵）。"""

    def setUp(self):
        from core.code_review import upsert_findings

        self.repo = _make_repo()
        self.sm = _RecordingSM()
        upsert_findings(self.repo, [
            {"file": "core/a.py", "category": "correctness", "title": "T",
             "severity": "major", "line": 1, "description": "d",
             "suggestion": "", "evidence": "e"},
        ], "code-review-sa", "manual_full")

    def tearDown(self):
        import shutil

        shutil.rmtree(str(self.repo.parent), ignore_errors=True)

    def _one_id(self):
        from core.code_review import read_items

        return next(iter(read_items(self.repo)))

    def test_immediate_leaves_no_start_after(self):
        from core.code_review import generate_fix_spec

        res = generate_fix_spec(self.repo, self.sm, [self._one_id()])
        self.assertTrue(res["ok"], res)
        self.assertIsNone(res["start_after"], res)
        entry = self.sm.entries[res["spec_name"]]
        self.assertNotIn("start_after", entry, entry)

    def test_scheduled_iso_persisted(self):
        from core.code_review import generate_fix_spec

        res = generate_fix_spec(
            self.repo, self.sm, [self._one_id()], "2026-12-01T02:00:00+00:00"
        )
        self.assertTrue(res["ok"], res)
        entry = self.sm.entries[res["spec_name"]]
        self.assertEqual(entry["start_after"], "2026-12-01T02:00:00+00:00", entry)
        self.assertEqual(res["start_after"], "2026-12-01T02:00:00+00:00", res)

    def test_manual_sentinel_persisted(self):
        from core.code_review import generate_fix_spec

        res = generate_fix_spec(self.repo, self.sm, [self._one_id()], "manual")
        self.assertTrue(res["ok"], res)
        self.assertEqual(self.sm.entries[res["spec_name"]]["start_after"], "manual")
        self.assertEqual(res["start_after"], "manual", res)

    def test_illegal_start_after_rejected_before_write(self):
        from core.code_review import generate_fix_spec, read_items

        res = generate_fix_spec(self.repo, self.sm, [self._one_id()], "not-a-time")
        self.assertFalse(res["ok"], res)
        self.assertIn("start_after", res["error"] or "", res)
        # 不半写：无 spec 目录、无注册、条目状态不变
        self.assertFalse((self.repo / "spec" / "changes").exists())
        self.assertEqual(self.sm.entries, {})
        self.assertEqual(read_items(self.repo)[self._one_id()]["status"], "open")

    def test_blank_start_after_is_immediate(self):
        from core.code_review import generate_fix_spec

        res = generate_fix_spec(self.repo, self.sm, [self._one_id()], "  ")
        self.assertTrue(res["ok"], res)
        self.assertNotIn("start_after", self.sm.entries[res["spec_name"]])


class TestNormalizeStartAfter(unittest.TestCase):
    def test_tristate(self):
        from core.code_review import _normalize_start_after

        self.assertEqual(_normalize_start_after(None), (True, None, ""))
        self.assertEqual(_normalize_start_after(""), (True, None, ""))
        self.assertEqual(_normalize_start_after("  "), (True, None, ""))
        self.assertEqual(_normalize_start_after("MANUAL"), (True, "manual", ""))
        ok, value, err = _normalize_start_after("2026-12-01T02:00:00+00:00")
        self.assertTrue(ok, err)
        self.assertTrue(value.startswith("2026-12-01T02:00:00"), value)
        ok, value, err = _normalize_start_after("garbage")
        self.assertFalse(ok)
        self.assertIn("start_after", err)


class TestSpecNameResolution(unittest.TestCase):
    def setUp(self):
        self.repo = _make_repo()
        self.sm = _FakeSM()

    def tearDown(self):
        import shutil

        shutil.rmtree(str(self.repo.parent), ignore_errors=True)

    def test_base_name(self):
        from core.code_review import _resolve_fix_spec_name

        name = _resolve_fix_spec_name(self.repo, self.sm, "unused-import", "abc123")
        self.assertEqual(name, "fix-cr-unused-import")

    def test_conflict_gets_suffix(self):
        from core.code_review import _resolve_fix_spec_name

        (# spec/changes 同名目录冲突
            self.repo / "spec" / "changes" / "fix-cr-unused-import").mkdir(parents=True)
        name = _resolve_fix_spec_name(self.repo, self.sm, "unused-import", "abc123def456")
        self.assertTrue(name.startswith("fix-cr-unused-import-"), name)
        self.assertNotEqual(name, "fix-cr-unused-import")

    def test_still_conflict_returns_none(self):
        from core.code_review import _resolve_fix_spec_name

        (# 基名 + 后缀都冲突
            self.repo / "spec" / "changes" / "fix-cr-unused-import").mkdir(parents=True)
        (# 断言后缀固定为 fingerprint 前 6 位
            self.repo / "spec" / "changes" / "fix-cr-unused-import-abc123").mkdir(parents=True)
        name = _resolve_fix_spec_name(self.repo, self.sm, "unused-import", "abc123")
        self.assertIsNone(name)


class TestLintNoHalfWrite(unittest.TestCase):
    def test_violation_returns_error_and_no_spec_dir(self):
        from core.code_review import generate_fix_spec, write_items

        repo = _make_repo()
        try:
            sm = _FakeSM()
            # 直接写一条指向不存在文件的 open 条目（lint 必拦 modify 不存在）
            write_items(repo, [{
                "item_id": "fake1",
                "project": "proj",
                "file": "core/not-exists.py",
                "category": "correctness",
                "title": "X",
                "severity": "major",
                "description": "",
                "suggestion": "",
                "evidence": "",
                "fingerprint": "fp123",
                "status": "open",
                "first_seen_at": "2026-09-01T00:00:00",
                "last_seen_at": "2026-09-01T00:00:00",
                "line": 1,
            }])
            res = generate_fix_spec(repo, sm, ["fake1"])
            self.assertFalse(res["ok"], res)
            self.assertTrue(res["error"] and "lint" in res["error"], res)
            # 不半写：spec/changes 无新目录、drafts 被清理、条目仍 open
            changes = repo / "spec" / "changes"
            self.assertFalse(
                any(p for p in changes.iterdir()) if changes.exists() else False
            )
            from core.code_review import read_items

            it = read_items(repo)["fake1"]
            self.assertEqual(it["status"], "open")
        finally:
            import shutil

            shutil.rmtree(str(repo.parent), ignore_errors=True)

# ── 7.4 agent 四处注册一致性 ────────────────────────────────────────


class TestAgentRegistration(unittest.TestCase):
    def test_four_registration_points(self):
        from core.agent_runner.prompt_builder import AGENT_PROMPT_FILES
        from core.agent_runner.run_files import RUN_ID_AGENT_PREFIXES
        from core.config import ConfigLoader

        # 1. AGENT_PROMPT_FILES
        self.assertEqual(AGENT_PROMPT_FILES.get("code-review"), "code-review.md")
        # 2. RUN_ID_AGENT_PREFIXES
        self.assertIn(("code-review-", "code-review"), RUN_ID_AGENT_PREFIXES)
        # 3. KNOWN_AGENT_TYPES
        self.assertIn("code-review", ConfigLoader.KNOWN_AGENT_TYPES)
        # 4. agents/code-review.md 存在
        from core.agent_runner.prompt_builder import AGENT_PROMPT_DIR

        self.assertTrue((AGENT_PROMPT_DIR / "code-review.md").is_file())

    def test_infer_run_agent_type(self):
        from core.agent_runner.run_files import infer_run_agent_type

        self.assertEqual(infer_run_agent_type("code-review-1758211200"), ("code-review", "1758211200"))


# ── 7.5 get_code_review_config + checkpoint 零动作 ──────────────────


class TestGetCodeReviewConfig(unittest.TestCase):
    def test_defaults(self):
        from core.config import ConfigLoader

        cfg = ConfigLoader.get_code_review_config({})
        self.assertEqual(
            cfg,
            {
                "enabled": False,
                "max_files": 500,
                "scope": "window",
                "stall_alert_minutes": 15,
                # evo-add-code-review-ratelimit-resume 4.1：手动 full 叠加防护
                # 阈值缺省 30（0 = 关闭守卫）
                "manual_full_open_warn": 30,
                # add-code-review-run-at：触发时点缺省回退自省 run_at（文档缺省 02:00）
                "run_at": "02:00",
            },
        )

    def test_invalid_max_files_fallback(self):
        from core.config import ConfigLoader

        for bad in (0, -1, "x", 1.5, True):
            cfg = ConfigLoader.get_code_review_config({"admin": {"code_review": {"max_files": bad}}})
            self.assertEqual(cfg["max_files"], 500, f"bad={bad!r}")

    def test_invalid_stall_alert_minutes_fallback(self):
        # add-code-review-sharded-out：停滞告警阈值非法回退 15（bool 是 int
        # 子类，与 max_files 同款显式排除）
        from core.config import ConfigLoader

        for bad in (0, -5, "x", 1.5, True):
            cfg = ConfigLoader.get_code_review_config(
                {"admin": {"code_review": {"stall_alert_minutes": bad}}}
            )
            self.assertEqual(cfg["stall_alert_minutes"], 15, f"bad={bad!r}")

    def test_explicit_values(self):
        from core.config import ConfigLoader

        cfg = ConfigLoader.get_code_review_config(
            {"admin": {"code_review": {"enabled": True, "max_files": 100, "stall_alert_minutes": 30}}}
        )
        self.assertEqual(
            cfg,
            {
                "enabled": True,
                "max_files": 100,
                "scope": "window",
                "stall_alert_minutes": 30,
                "manual_full_open_warn": 30,
                # add-code-review-run-at：键缺失回退自省 run_at 文档缺省
                "run_at": "02:00",
            },
        )

    def test_repo_concurrency_valid_value(self):
        # add-code-review-concurrency-and-429-resilience：合法正整数透传
        from core.config import ConfigLoader

        assert ConfigLoader.get_repo_code_review_concurrency(
            {"verify": {"repo_code_review_concurrency": 6}}
        ) == 6

    def test_repo_concurrency_defaults_and_fallbacks(self):
        # 缺省 4；str/bool/float/≤0/缺失 verify 节一律回退 4（与
        # get_impl_code_review_concurrency 同款 fail-open 判据）
        from core.config import ConfigLoader

        assert ConfigLoader.get_repo_code_review_concurrency({}) == 4
        assert ConfigLoader.get_repo_code_review_concurrency({"verify": {}}) == 4
        for bad in ("8", 0, -2, True, False, 4.0, 1.5, None):
            assert ConfigLoader.get_repo_code_review_concurrency(
                {"verify": {"repo_code_review_concurrency": bad}}
            ) == 4, f"bad={bad!r}"


class TestCheckpointDisabledZeroAction(unittest.TestCase):
    def _make_monitor(self, cfg, repo, runner):
        from core.admin_monitor import AdminMonitor

        logger = logging.getLogger("test-cr")
        return AdminMonitor(cfg, None, str(repo), logger, agent_runner=runner, code_review_executor=None)

    def test_disabled_no_dispatch_no_artifacts(self):
        repo = _make_repo()
        try:
            calls = {"n": 0}

            class _Runner:
                _running_agents = {}

                def run_code_review(self, *a, **k):
                    calls["n"] += 1
                    return MagicMockResult()

            class MagicMockResult:
                run_id = "code-review-1"
                success = True
                inserted = 0
                updated = 0
                resolved = 0
                error = ""

            mon = self._make_monitor({"admin": {"code_review": {"enabled": False}}}, repo, _Runner())
            result = mon._run_code_review_checkpoint()
            self.assertEqual(result, {"triggered": False, "reason": "disabled"})
            self.assertEqual(calls["n"], 0)
            # 不写任何 code-review 产物
            cr_dir = repo / ".fenix" / "code-review"
            self.assertFalse(cr_dir.exists())
            self.assertFalse((repo / ".fenix" / "code_review_state.json").exists())
        finally:
            import shutil

            shutil.rmtree(str(repo.parent), ignore_errors=True)

    def test_before_run_at_no_dispatch(self):
        from datetime import datetime, timedelta

        repo = _make_repo()
        try:
            calls = {"n": 0}

            class _Runner:
                _running_agents = {}

                def run_code_review(self, *a, **k):
                    calls["n"] += 1
                    return MagicMockResult()

            class MagicMockResult:
                run_id = "code-review-1"
                success = True
                inserted = 0
                updated = 0
                resolved = 0
                error = ""

            # run_at 在未来（23:59）→ before_run_at，不派发、不写产物
            mon = self._make_monitor(
                {
                    "admin": {
                        "code_review": {"enabled": True},
                        "self_review": {"enabled": True, "run_at": "23:59"},
                    }
                },
                repo,
                _Runner(),
            )
            result = mon._run_code_review_checkpoint()
            self.assertEqual(result, {"triggered": False, "reason": "before_run_at"})
            self.assertEqual(calls["n"], 0)
            self.assertFalse((repo / ".fenix" / "code_review_state.json").exists())
        finally:
            import shutil

            shutil.rmtree(str(repo.parent), ignore_errors=True)


# ── 7.6 Dashboard 读写链路 ─────────────────────────────────────────


class TestDashboardConfigRoundtrip(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(_mkdtemp("cr-cfg-"))
        (self.tmpdir / ".fenix").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        import shutil

        shutil.rmtree(str(self.tmpdir), ignore_errors=True)

    def test_write_echo_roundtrip(self):
        from core.dashboard.data import read_config, write_config

        result = write_config(
            self.tmpdir,
            {
                "code_review": {
                    "enabled": True,
                    "max_files": 200,
                    "stall_alert_minutes": 30,
                }
            },
        )
        self.assertTrue(result["ok"], result)
        echoed = read_config(self.tmpdir)
        self.assertEqual(
            echoed["code_review"],
            {
                "enabled": True,
                "max_files": 200,
                "scope": "window",
                "stall_alert_minutes": 30,
                # evo-add-code-review-ratelimit-resume 4.1：新键缺省回显
                "manual_full_open_warn": 30,
                # add-code-review-run-at：触发时点回显生效值（键未配置=回退自省
                # run_at 文档缺省 02:00）
                "run_at": "02:00",
            },
        )
        # 与 self_review 同形态：code_review 不在受管 admin 键集内
        self.assertNotIn("code_review", echoed["admin"])
        self.assertEqual(echoed["sources"].get("admin.code_review"), "project")

    def test_invalid_values_rejected(self):
        from core.dashboard.data import write_config

        r1 = write_config(self.tmpdir, {"code_review": {"enabled": "yes"}})
        self.assertFalse(r1["ok"])
        r2 = write_config(self.tmpdir, {"code_review": {"max_files": 0}})
        self.assertFalse(r2["ok"])
        r3 = write_config(self.tmpdir, {"code_review": {"max_files": -3}})
        self.assertFalse(r3["ok"])
        # add-code-review-sharded-out：停滞告警阈值非法直接拒绝
        r4 = write_config(self.tmpdir, {"code_review": {"stall_alert_minutes": 0}})
        self.assertFalse(r4["ok"])
        r5 = write_config(self.tmpdir, {"code_review": {"stall_alert_minutes": -5}})
        self.assertFalse(r5["ok"])
        r6 = write_config(self.tmpdir, {"code_review": {"stall_alert_minutes": "abc"}})
        self.assertFalse(r6["ok"])

    def test_default_echo_no_admin_section(self):
        from core.dashboard.data import read_config

        echoed = read_config(self.tmpdir)
        self.assertEqual(
            echoed["code_review"],
            {
                "enabled": False,
                "max_files": 500,
                "scope": "window",
                "stall_alert_minutes": 15,
                # add-code-review-run-at：触发时点回显生效值（未配置=回退自省
                # run_at 文档缺省 02:00）
                "run_at": "02:00",
            },
        )
        self.assertEqual(echoed["sources"].get("admin.code_review"), "user")


if __name__ == "__main__":
    unittest.main()


# ── 补充：read_progress / set_item_status 状态机 ────────────────────


class TestReadProgress(unittest.TestCase):
    def tearDown(self):
        import shutil

        if hasattr(self, "_td"):
            shutil.rmtree(str(self._td), ignore_errors=True)

    def _mk_progress(self, run_id, total, done, run_terminal=None, stale=False):
        import tempfile
        import time

        from core.code_review import code_review_dir, out_path

        self._td = _mkdtemp("cr-prog-")
        proot = Path(self._td)
        cr = code_review_dir(proot)
        cr.mkdir(parents=True)
        (cr / f"manifest-{run_id}.json").write_text(
            json.dumps({"files": [f"core/f{i}.py" for i in range(total)], "review_kind": "manual_full"}),
            encoding="utf-8",
        )
        with open(out_path(proot, run_id), "w", encoding="utf-8") as f:
            for i in range(done):
                f.write(json.dumps({"file": f"core/f{i}.py", "category": "c", "title": f"t{i}"}) + "\n")
        runs = proot / ".fenix" / "runs"
        runs.mkdir(parents=True)
        run_file = runs / f"{run_id}.jsonl"
        run_file.write_text(json.dumps({"type": "system", "message": "start"}) + "\n", encoding="utf-8")
        if run_terminal:
            run_file.write_text(json.dumps({"type": run_terminal}) + "\n", encoding="utf-8")
        if stale:
            os.utime(run_file, (1, 1))
        return proot, run_id

    def test_running(self):
        from core.code_review import read_progress

        proot, run_id = self._mk_progress("code-review-1758211200", 42, 17)
        p = read_progress(proot)
        self.assertTrue(p["running"])
        self.assertEqual(p["total"], 42)
        self.assertEqual(p["done"], 17)
        self.assertEqual(p["current"], "core/f16.py")
        self.assertEqual(p["review_kind"], "manual_full")

    def test_terminal_not_running(self):
        from core.code_review import read_progress

        for term in ("result", "error", "interrupted", "cancelled"):
            proot, _ = self._mk_progress(
                f"code-review-{abs(hash(term)) % 10**9}", 5, 3, run_terminal=term
            )
            p = read_progress(proot)
            self.assertFalse(p["running"], f"terminal={term}")
            import shutil

            shutil.rmtree(str(proot), ignore_errors=True)
            self._td = None

    def test_stale_not_running(self):
        from core.code_review import read_progress

        proot, _ = self._mk_progress("code-review-1758211200", 42, 5, stale=True)
        p = read_progress(proot)
        self.assertFalse(p["running"])

    def test_no_run_running_false(self):
        import tempfile

        from core.code_review import read_progress

        td = _mkdtemp("cr-prog2-")
        try:
            p = read_progress(td)
            self.assertFalse(p["running"])
            self.assertIsNone(p["review_id"])
            self.assertEqual(p["total"], 0)
            self.assertEqual(p["done"], 0)
        finally:
            import shutil

            shutil.rmtree(td, ignore_errors=True)


class TestSetItemStatus(unittest.TestCase):
    def setUp(self):
        from core.code_review import upsert_findings

        self.repo = _make_repo()
        upsert_findings(self.repo, [
            {"file": "core/a.py", "category": "correctness", "title": "X",
             "severity": "major", "description": "", "suggestion": "", "evidence": ""},
        ], "code-review-1", "manual_full")
        from core.code_review import read_items

        self.item_id = next(iter(read_items(self.repo)))

    def tearDown(self):
        import shutil

        shutil.rmtree(str(self.repo.parent), ignore_errors=True)

    def test_manual_statuses(self):
        from core.code_review import read_items, set_item_status

        r = set_item_status(self.repo, self.item_id, "ignored")
        self.assertTrue(r["ok"])
        self.assertEqual(read_items(self.repo)[self.item_id]["status"], "ignored")
        # 幂等
        r2 = set_item_status(self.repo, self.item_id, "ignored")
        self.assertTrue(r2["ok"])

    def test_resolved_not_manually_settable(self):
        from core.code_review import set_item_status

        r = set_item_status(self.repo, self.item_id, "resolved")
        self.assertFalse(r["ok"])

    def test_in_spec_not_manually_settable(self):
        from core.code_review import set_item_status

        r = set_item_status(self.repo, self.item_id, "in_spec", spec_name="fix-cr-x")
        self.assertFalse(r["ok"])

    def test_clear_attribution_from_in_spec(self):
        from core.code_review import read_items, set_item_status, write_items

        # 直接把条目置 in_spec + spec_name（生成链路置入）
        items = read_items(self.repo)
        items[self.item_id]["status"] = "in_spec"
        items[self.item_id]["spec_name"] = "fix-cr-x"
        write_items(self.repo, items.values())
        r = set_item_status(self.repo, self.item_id, "open")
        self.assertTrue(r["ok"])
        rec = read_items(self.repo)[self.item_id]
        self.assertEqual(rec["status"], "open")
        self.assertIsNone(rec.get("spec_name"))

    def test_unknown_item_error(self):
        from core.code_review import set_item_status

        r = set_item_status(self.repo, "no-such", "ignored")
        self.assertFalse(r["ok"])
        self.assertIn("不存在", r["error"])


# ── 2026-09-19 原地修复：manifest 范围与产物硬门 ──────────────────


class TestManifestScope(unittest.TestCase):
    """全仓 manifest 只收产品代码（用户决策 2026-09-19）。

    事故背景：全仓审查 manifest 收了 474 个文件，其中 tests/ 占 251（过半）
    ——断言细节而非产品逻辑，稀释了产品代码的审查预算，与「审查工程代码质量」
    的语义不符。修复后须排除 tests/ 与生成物文件。
    """

    def setUp(self):
        self.repo = _make_repo()
        # 追加各类非产品文件
        (self.repo / "tests").mkdir(exist_ok=True)
        (self.repo / "tests" / "test_x.py").write_text("def test(): pass\n")
        (self.repo / "tests" / "fixtures" / "demo").mkdir(parents=True, exist_ok=True)
        (self.repo / "tests" / "fixtures" / "demo" / "f.py").write_text("z=1\n")
        gen = self.repo / "core" / "dashboard" / "static" / "src"
        gen.mkdir(parents=True, exist_ok=True)
        (gen / "tailwind.gen.css").write_text(".a{}\n")
        (gen / "bundle.min.js").write_text("x\n")
        (gen / "types.d.ts").write_text("export {};\n")
        (self.repo / "core" / "ok.tsx").write_text("export default 1\n")
        # vendored 第三方目录（evo-code-review-vendored-scope）：三段目录名
        # 均须排除，其余源码收集行为不变。
        for vendored in ("thirdparty/x/a.py", "third_party/y/b.py", "vendor/z/c.py"):
            p = self.repo / vendored
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("q=1\n")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "more")

    def test_excludes_tests(self):
        from core.code_review import collect_manifest

        files = collect_manifest(self.repo, "full", None)
        self.assertNotIn("tests/test_x.py", files)
        self.assertNotIn("tests/fixtures/demo/f.py", files)
        self.assertTrue(all(not f.startswith("tests/") for f in files))

    def test_excludes_vendored_dirs(self):
        """vendored 第三方目录不入 manifest（evo-code-review-vendored-scope）。

        vendored 文件由上游同步流程承接（文件内自带上游同步注释与
        fenix-ignore 标注），入审查面只会逐轮全价重审。目录段精确匹配
        thirdparty / third_party / vendor；非 vendored 路径收集行为不变。
        """
        from core.code_review import collect_manifest

        files = collect_manifest(self.repo, "full", None)
        self.assertNotIn("thirdparty/x/a.py", files)
        self.assertNotIn("third_party/y/b.py", files)
        self.assertNotIn("vendor/z/c.py", files)
        self.assertTrue(
            all(
                not f.startswith(("thirdparty/", "third_party/", "vendor/"))
                and "/thirdparty/" not in f
                and "/third_party/" not in f
                and "/vendor/" not in f
                for f in files
            )
        )
        # 非 vendored 路径收集行为不变
        self.assertIn("core/a.py", files)
        self.assertIn("core/ok.tsx", files)

    def test_window_scope_excludes_vendored_dirs(self):
        """window 档收集同样排除 vendored 目录（共用 _is_source_file 消费点）。"""
        from datetime import datetime, timedelta

        from core.code_review import collect_manifest

        window_start = datetime.now().astimezone() - timedelta(hours=1)
        files = collect_manifest(self.repo, "window", window_start)
        self.assertNotIn("thirdparty/x/a.py", files)
        self.assertNotIn("third_party/y/b.py", files)
        self.assertNotIn("vendor/z/c.py", files)
        self.assertIn("core/a.py", files)

    def test_excludes_generated_artifacts(self):
        from core.code_review import collect_manifest

        files = collect_manifest(self.repo, "full", None)
        self.assertNotIn("core/dashboard/static/src/tailwind.gen.css", files)
        self.assertNotIn("core/dashboard/static/src/bundle.min.js", files)
        self.assertNotIn("core/dashboard/static/src/types.d.ts", files)

    def test_keeps_product_code(self):
        from core.code_review import collect_manifest

        files = collect_manifest(self.repo, "full", None)
        self.assertIn("core/a.py", files)
        self.assertIn("core/ok.tsx", files)


class TestRepoCodeReviewArtifactGate(unittest.TestCase):
    """code-review 产物硬门（2026-09-19 原地修复；聚合口径
    add-code-review-sharded-out 2.2）。

    事故背景：`run_code_review` 此前全链无任何产物门——run exit 0 但 agent
    从未写 out-<run_id>.jsonl，`_read_code_review_out` 对缺失文件返回空列表，
    落账 inserted=0 后仍 success=True：空跑被当成功。分片直写模式下升级为
    聚合口径：主产物与分片合计 ≥1 有效行即放行，合计零有效行判失败。
    """

    def setUp(self):
        self.proot = Path(_mkdtemp("cr-gate-"))
        self.crdir = self.proot / ".fenix" / "code-review"
        self.crdir.mkdir(parents=True)
        self.run_id = "code-review-1"
        self.out = self.crdir / f"out-{self.run_id}.jsonl"

    def tearDown(self):
        import shutil

        shutil.rmtree(str(self.proot), ignore_errors=True)

    def _gate(self, manifest):
        from core.agent_runner.result_gate import _check_repo_code_review_artifact

        return _check_repo_code_review_artifact(manifest, self.proot, self.run_id)

    def _shard(self, n, rows):
        p = self.crdir / f"out-{self.run_id}-b{n}.jsonl"
        p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        return p

    def test_empty_manifest_passes(self):
        # 空 manifest 调用方已前置跳过，此处不重复判定（避免误伤）
        self.assertIsNone(self._gate([]))

    def test_all_sources_missing_fails(self):
        err = self._gate(["core/a.py"])
        self.assertIsNotNone(err)
        self.assertIn("零有效行", err)
        self.assertIn(self.run_id, err)  # error 点名 run_id
        self.assertIn("分片", err)  # 聚合口径描述

    def test_missing_variant_marked_and_distinct_from_zero_rows(self):
        """缺失变体带「缺失」标注，与零有效行变体剔除 run id 后互异（BUG-02）。"""
        from core.agent_runner.result_gate import _repo_code_review_gate_face

        t_missing = self._gate(["core/a.py"]) or ""
        self.assertIn("缺失", t_missing, "产物缺失变体应标注缺失")
        # 三形态失败面：variant_label 中文标注（机器可消费的结构化标注）
        _, face_missing = _repo_code_review_gate_face(
            ["core/a.py"], self.proot, self.run_id)
        self.assertEqual(face_missing["variant"], "artifact_missing")
        self.assertEqual(face_missing["variant_label"], "产物缺失")
        self.assertEqual(face_missing["manifest_count"], 1)

    def test_variant_faces_distinct_labels(self):
        """三形态 fail_face 互异：缺失/读取失败/零有效行各自中文标注（BUG-01/02）。"""
        from core.agent_runner.result_gate import _repo_code_review_gate_face

        # 零有效行：主产物存在但空文件
        self.out.write_text("", encoding="utf-8")
        err_zero, face_zero = _repo_code_review_gate_face(
            ["core/a.py"], self.proot, self.run_id)
        self.assertEqual(face_zero["variant"], "zero_valid_rows")
        self.assertEqual(face_zero["variant_label"], "零有效行")
        self.assertIn("零有效行", err_zero)
        # 读取失败：主产物存在但 read_text 抛 OSError
        import pathlib
        orig_read = pathlib.Path.read_text

        def fake_read(self_p, *a, **k):
            if self_p.name == self.out.name:
                raise OSError(13, "Permission denied")
            return orig_read(self_p, *a, **k)

        pathlib.Path.read_text = fake_read
        try:
            err_unread, face_unread = _repo_code_review_gate_face(
                ["core/a.py"], self.proot, self.run_id)
        finally:
            pathlib.Path.read_text = orig_read
        self.assertEqual(face_unread["variant"], "unreadable_sources")
        self.assertEqual(face_unread["variant_label"], "读取失败")
        self.assertIn("读取失败", err_unread)
        # 缺失变体（无任何产物文件）
        self.out.unlink(missing_ok=True)
        err_missing, face_missing = _repo_code_review_gate_face(
            ["core/a.py"], self.proot, self.run_id)
        self.assertEqual(face_missing["variant"], "artifact_missing")
        self.assertEqual(face_missing["variant_label"], "产物缺失")
        self.assertIn("缺失", err_missing)
        # 三份文案剔除 run id 后互异（验证场景口径）
        norm = lambda t: t.replace(self.run_id, "<rid>")
        self.assertNotEqual(norm(err_missing), norm(err_zero))
        self.assertNotEqual(norm(err_missing), norm(err_unread))
        self.assertNotEqual(norm(err_zero), norm(err_unread))

    def test_empty_main_file_fails(self):
        self.out.write_text("")
        err = self._gate(["core/a.py"])
        self.assertIsNotNone(err)
        self.assertIn("零有效行", err)

    def test_garbage_lines_fail(self):
        # 防「写满垃圾行骗过门禁」：有效行判据不是裸行数
        self.out.write_text("not json\n\n{}\n")
        err = self._gate(["core/a.py"])
        self.assertIsNotNone(err)
        self.assertIn("零有效行", err)

    def test_no_findings_list_fails(self):
        # findings 非列表的行不算「该文件审完了」的登记形态
        self.out.write_text(json.dumps({"file": "core/a.py"}) + "\n")
        err = self._gate(["core/a.py"])
        self.assertIsNotNone(err)

    def test_valid_line_passes(self):
        self.out.write_text(json.dumps({"file": "core/a.py", "findings": []}) + "\n")
        self.assertIsNone(self._gate(["core/a.py"]))

    def test_clean_file_review_passes(self):
        # 空 findings 也是合法审查结论（文件干净），MUST NOT 判失败；
        # 多文件全覆盖同样放行
        self.out.write_text(
            json.dumps({"file": "core/a.py", "findings": []})
            + "\n"
            + json.dumps({"file": "core/b.py", "findings": []})
            + "\n"
        )
        self.assertIsNone(self._gate(["core/a.py", "core/b.py"]))

    def test_shard_only_passes(self):
        # 仅分片有行（主产物缺失）→ 放行（add-code-review-sharded-out 场景）
        self._shard(1, [{"file": "core/a.py", "findings": []}])
        self._shard(2, [{"file": "core/b.py", "findings": []}])
        self.assertIsNone(self._gate(["core/a.py", "core/b.py"]))

    def test_shard_garbage_only_fails(self):
        # 分片存在但全垃圾行 → 合计仍零有效行，判失败
        (self.crdir / f"out-{self.run_id}-b1.jsonl").write_text(
            "not json\n\n", encoding="utf-8"
        )
        err = self._gate(["core/a.py"])
        self.assertIsNotNone(err)
        self.assertIn("零有效行", err)

    def test_shard_and_main_mixed_pass(self):
        self._shard(1, [{"file": "core/a.py", "findings": []}])
        self.out.write_text(json.dumps({"file": "core/b.py", "findings": []}) + "\n")
        self.assertIsNone(self._gate(["core/a.py", "core/b.py"]))


if __name__ == "__main__":
    unittest.main()


# ── add-code-review-sharded-out：分片发现 / 聚合读取 / 停滞检测 ──────


class TestShardPaths(unittest.TestCase):
    """shard_paths：glob out-<run_id>-b*.jsonl 按 N 数值升序；非正整数 N、
    目录、他 run 分片 MUST NOT 被消费（add-code-review-sharded-out 1.1/D1）。"""

    def setUp(self):
        self.proot = Path(_mkdtemp("cr-shard-"))
        self.crdir = self.proot / ".fenix" / "code-review"
        self.crdir.mkdir(parents=True)
        self.run_id = "code-review-1790182831"

    def tearDown(self):
        import shutil

        shutil.rmtree(str(self.proot), ignore_errors=True)

    def _write(self, name):
        p = self.crdir / name
        p.write_text("", encoding="utf-8")
        return p

    def test_numeric_ascending_not_lexicographic(self):
        # 故意乱序创建：字典序 b10 < b2，数值升序应为 b1 < b2 < b10
        self._write(f"out-{self.run_id}-b10.jsonl")
        self._write(f"out-{self.run_id}-b2.jsonl")
        self._write(f"out-{self.run_id}-b1.jsonl")
        from core.code_review import shard_paths

        names = [p.name for p in shard_paths(self.proot, self.run_id)]
        self.assertEqual(
            names,
            [
                f"out-{self.run_id}-b1.jsonl",
                f"out-{self.run_id}-b2.jsonl",
                f"out-{self.run_id}-b10.jsonl",
            ],
        )

    def test_ignores_non_numeric_and_non_positive_and_dirs(self):
        self._write(f"out-{self.run_id}-babc.jsonl")
        self._write(f"out-{self.run_id}-b0.jsonl")
        self._write(f"out-{self.run_id}.jsonl")
        self._write(f"out-{self.run_id}-b1.txt")
        (self.crdir / f"out-{self.run_id}-b3.jsonl").mkdir()
        from core.code_review import shard_paths

        self.assertEqual([p.name for p in shard_paths(self.proot, self.run_id)], [])

    def test_other_run_shards_not_matched(self):
        self._write("out-code-review-999-b1.jsonl")
        from core.code_review import shard_paths

        self.assertEqual(shard_paths(self.proot, self.run_id), [])

    def test_missing_dir_returns_empty(self):
        from core.code_review import shard_paths

        self.assertEqual(shard_paths(self.proot / "nope", "code-review-1"), [])


class TestReadReviewOutRows(unittest.TestCase):
    """聚合读取（add-code-review-sharded-out 1.1/D2）：迭代顺序分片 N 升序
    →主产物、空行/坏行过滤、按 file 去重保留先见行、主产物缺失分片兜底。"""

    def setUp(self):
        self.proot = Path(_mkdtemp("cr-rows-"))
        self.crdir = self.proot / ".fenix" / "code-review"
        self.crdir.mkdir(parents=True)
        self.run_id = "code-review-1"

    def tearDown(self):
        import shutil

        shutil.rmtree(str(self.proot), ignore_errors=True)

    def _shard(self, n, rows):
        (self.crdir / f"out-{self.run_id}-b{n}.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
        )

    def _main(self, rows):
        (self.crdir / f"out-{self.run_id}.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
        )

    def test_order_shards_then_main_and_dedup_first_seen(self):
        self._main([{"file": "a.py"}, {"file": "d.py"}])
        self._shard(2, [{"file": "c.py"}])
        self._shard(1, [{"file": "b.py"}, {"file": "a.py"}])  # a.py 与主产物重复
        from core.code_review import read_review_out_rows

        rows = read_review_out_rows(self.proot, self.run_id)
        self.assertEqual([r["file"] for r in rows], ["b.py", "a.py", "c.py", "d.py"])

    def test_filters_blank_and_bad_lines(self):
        (self.crdir / f"out-{self.run_id}-b1.jsonl").write_text(
            "\nnot json\n[1,2]\n{\"no_file\": 1}\n" + json.dumps({"file": "a.py"}) + "\n",
            encoding="utf-8",
        )
        from core.code_review import read_review_out_rows

        rows = read_review_out_rows(self.proot, self.run_id)
        self.assertEqual([r["file"] for r in rows], ["a.py"])

    def test_main_missing_shard_fallback(self):
        self._shard(1, [{"file": "a.py"}])
        self._shard(2, [{"file": "b.py"}])
        from core.code_review import read_review_out_rows

        rows = read_review_out_rows(self.proot, self.run_id)
        self.assertEqual([r["file"] for r in rows], ["a.py", "b.py"])

    def test_all_missing_returns_empty(self):
        from core.code_review import read_review_out_rows

        self.assertEqual(read_review_out_rows(self.proot, self.run_id), [])


class TestReadProgressAggregated(unittest.TestCase):
    """read_progress 聚合口径（add-code-review-sharded-out 1.2）：
    分片 17+9 → done=26 running=true；主产物缺失不归零；重复行不虚增；
    响应字段形状与旧版一致。"""

    def _mk(self, run_id, total, main_rows, shard_rows_by_n):
        proot = Path(_mkdtemp("cr-prog-agg-"))
        cr = proot / ".fenix" / "code-review"
        cr.mkdir(parents=True)
        (cr / f"manifest-{run_id}.json").write_text(
            json.dumps(
                {
                    "files": [f"core/f{i}.py" for i in range(total)],
                    "review_kind": "manual_full",
                }
            ),
            encoding="utf-8",
        )
        if main_rows is not None:
            (cr / f"out-{run_id}.jsonl").write_text(
                "".join(json.dumps(r) + "\n" for r in main_rows), encoding="utf-8"
            )
        for n, rows in shard_rows_by_n.items():
            (cr / f"out-{run_id}-b{n}.jsonl").write_text(
                "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
            )
        runs = proot / ".fenix" / "runs"
        runs.mkdir(parents=True)
        (runs / f"{run_id}.jsonl").write_text(
            json.dumps({"type": "system", "message": "start"}) + "\n", encoding="utf-8"
        )
        return proot

    def tearDown(self):
        import shutil

        shutil.rmtree(str(self._proot), ignore_errors=True)

    def test_shards_aggregate_and_running(self):
        run_id = "code-review-1790182831"
        shard1 = [{"file": f"core/f{i}.py"} for i in range(17)]
        shard2 = [{"file": f"core/f{i}.py"} for i in range(17, 26)]
        self._proot = self._mk(run_id, 40, None, {1: shard1, 2: shard2})
        from core.code_review import read_progress

        p = read_progress(self._proot)
        self.assertTrue(p["running"])
        self.assertEqual(p["review_id"], run_id)
        self.assertEqual(p["total"], 40)
        self.assertEqual(p["done"], 26)
        # current 取 mtime 最晚来源（b2）末行的被审文件
        self.assertEqual(p["current"], "core/f25.py")
        # 响应字段形状与旧版一致
        self.assertEqual(
            set(p.keys()),
            {"running", "review_id", "review_kind", "total", "done", "current"},
        )

    def test_main_missing_done_not_zeroed(self):
        shard1 = [{"file": f"core/f{i}.py"} for i in range(26)]
        self._proot = self._mk("code-review-1790182832", 40, None, {1: shard1})
        from core.code_review import read_progress

        p = read_progress(self._proot)
        self.assertEqual(p["done"], 26)

    def test_duplicate_files_counted_once_shard_first(self):
        # 分片 b1 落 core/f0.py；主产物重复写 f0 + 新增 f1 → done=2 不是 3
        # （产物行须在 manifest 清单内：done 与清单求交，item 8369875cbabf）
        self._proot = self._mk(
            "code-review-1790182833",
            5,
            [{"file": "core/f0.py"}, {"file": "core/f1.py"}],
            {1: [{"file": "core/f0.py"}]},
        )
        from core.code_review import read_progress

        p = read_progress(self._proot)
        self.assertEqual(p["done"], 2)

    def test_out_of_manifest_rows_not_counted(self):
        # 清单外路径（agent 幻觉产物行）不计入进度：done=0 而非 1（done <= total 恒成立）
        self._proot = self._mk(
            "code-review-1790182834",
            5,
            [{"file": "ghost.py"}],
            {},
        )
        from core.code_review import read_progress

        p = read_progress(self._proot)
        self.assertEqual(p["done"], 0)


class TestIngestAggregated(unittest.TestCase):
    """收尾 ingest 聚合读侧（add-code-review-sharded-out 2.1）：分片行落账、
    同 file 去重保留分片先见行。"""

    def setUp(self):
        self.proot = Path(_mkdtemp("cr-ingest-"))
        self.crdir = self.proot / ".fenix" / "code-review"
        self.crdir.mkdir(parents=True)
        self.run_id = "code-review-1"

    def tearDown(self):
        import shutil

        shutil.rmtree(str(self.proot), ignore_errors=True)

    @staticmethod
    def _runner():
        class _R:
            logger = None

        return _R()

    def test_findings_from_shards_only(self):
        (self.crdir / f"out-{self.run_id}-b1.jsonl").write_text(
            json.dumps(
                {"file": "a.py", "findings": [{"title": "t1", "category": "c"}]}
            )
            + "\n",
            encoding="utf-8",
        )
        from core.agent_runner.maintenance_runs import _read_code_review_out

        out = _read_code_review_out(self._runner(), self.proot, self.run_id)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["file"], "a.py")
        self.assertEqual(out[0]["title"], "t1")

    def test_dedup_shard_first(self):
        # 同 file 分片与主产物都有行 → 只保留分片（先见）的 findings
        (self.crdir / f"out-{self.run_id}-b1.jsonl").write_text(
            json.dumps({"file": "a.py", "findings": [{"title": "from-shard"}]}) + "\n",
            encoding="utf-8",
        )
        (self.crdir / f"out-{self.run_id}.jsonl").write_text(
            json.dumps({"file": "a.py", "findings": [{"title": "from-main"}]}) + "\n",
            encoding="utf-8",
        )
        from core.agent_runner.maintenance_runs import _read_code_review_out

        out = _read_code_review_out(self._runner(), self.proot, self.run_id)
        self.assertEqual([f["title"] for f in out], ["from-shard"])


class TestCheckProgressStall(unittest.TestCase):
    """事中零进度停滞检测（add-code-review-sharded-out 1.3/D4）。"""

    def _mk(self, run_id, requested_min_ago, done=0, run_terminal=None,
            stall_alert_minutes=None):
        from datetime import datetime, timedelta, timezone

        proot = Path(_mkdtemp("cr-stall-"))
        cr = proot / ".fenix" / "code-review"
        cr.mkdir(parents=True)
        requested_at = datetime.now(timezone.utc) - timedelta(minutes=requested_min_ago)
        (cr / f"manifest-{run_id}.json").write_text(
            json.dumps(
                {
                    "files": [f"core/f{i}.py" for i in range(30)],
                    "review_kind": "manual_full",
                    "requested_at": requested_at.isoformat(),
                }
            ),
            encoding="utf-8",
        )
        if done:
            (cr / f"out-{run_id}.jsonl").write_text(
                "".join(
                    json.dumps({"file": f"core/f{i}.py"}) + "\n" for i in range(done)
                ),
                encoding="utf-8",
            )
        runs = proot / ".fenix" / "runs"
        runs.mkdir(parents=True)
        (runs / f"{run_id}.jsonl").write_text(
            json.dumps({"type": run_terminal or "system", "message": "start"}) + "\n",
            encoding="utf-8",
        )
        if stall_alert_minutes is not None:
            (proot / ".fenix" / "config.yaml").write_text(
                "project:\n  name: t\n  type: cli\n"
                "admin:\n  code_review:\n"
                f"    stall_alert_minutes: {stall_alert_minutes}\n",
                encoding="utf-8",
            )
        return proot

    def tearDown(self):
        import shutil

        shutil.rmtree(str(self._proot), ignore_errors=True)

    def test_zero_progress_over_threshold_returns_hit(self):
        from core.code_review import check_progress_stall

        self._proot = self._mk("code-review-1790182831", 16)
        hit = check_progress_stall(self._proot)
        self.assertIsNotNone(hit)
        self.assertEqual(hit["run_id"], "code-review-1790182831")
        self.assertGreaterEqual(hit["minutes"], 15)

    def test_normal_progress_returns_none(self):
        from core.code_review import check_progress_stall

        self._proot = self._mk("code-review-1790182832", 16, done=30)
        self.assertIsNone(check_progress_stall(self._proot))

    def test_terminal_run_short_circuit(self):
        # run 终态 → running=false 短路，超时也不再触发
        from core.code_review import check_progress_stall

        self._proot = self._mk("code-review-1790182833", 60, run_terminal="result")
        self.assertIsNone(check_progress_stall(self._proot))

    def test_under_threshold_returns_none(self):
        from core.code_review import check_progress_stall

        self._proot = self._mk("code-review-1790182834", 5)
        self.assertIsNone(check_progress_stall(self._proot))

    def test_illegal_threshold_falls_back_default(self):
        # stall_alert_minutes=-5（非法）→ 回退 15：16 分钟零进度仍触发
        from core.code_review import check_progress_stall

        self._proot = self._mk("code-review-1790182835", 16, stall_alert_minutes=-5)
        hit = check_progress_stall(self._proot)
        self.assertIsNotNone(hit)

    def test_explicit_threshold_respected(self):
        # stall_alert_minutes=30 → 16 分钟零进度不触发
        from core.code_review import check_progress_stall

        self._proot = self._mk("code-review-1790182836", 16, stall_alert_minutes=30)
        self.assertIsNone(check_progress_stall(self._proot))


class TestCodeReviewPromptShardInjection(unittest.TestCase):
    """分片路径框架注入（2026-09-24 429 事故连带发现）。

    事故：提示词让主 agent「从 {out_path} 文件名推导 <run_id>」，agent 截成
    纯 epoch（`out-1790204913-b1.jsonl`，丢 `code-review-` 段），6 个分片对
    读侧（进度/ingest/硬门）全盲，173 条发现仅 20 条可消费。根治：分片名
    由框架经 `{run_id}` 占位符注入具体值，提示词删除一切推导指令。
    """

    RUN_ID = "code-review-1790204913"

    def _build(self):
        from core.agent_runner.prompt_builder import PromptBuilder

        pm = type("P", (), {"project_root": Path(_mkdtemp("cr-prompt-"))})()
        return PromptBuilder(pm), pm.project_root

    def test_template_has_injected_placeholder_no_derivation(self):
        from core.agent_runner.prompt_builder import AGENT_PROMPT_DIR

        text = (AGENT_PROMPT_DIR / "code-review.md").read_text(encoding="utf-8")
        self.assertIn("{run_id}", text)
        self.assertNotIn("out-<run_id>", text)
        # 推导指令必须删除（LLM 做字符串推导不可靠）
        self.assertNotIn("去掉 `out-` 前缀", text)

    def test_filled_prompt_has_concrete_shard_path(self):
        import shutil

        builder, proot = self._build()
        try:
            prompt = builder._build_code_review_prompt(
                self.RUN_ID,
                {
                    "manifest": ["core/a.py"],
                    "review_window": "（全仓）",
                    "out_path": str(proot / ".fenix" / "code-review" / f"out-{self.RUN_ID}.jsonl"),
                },
            )
        finally:
            shutil.rmtree(str(proot), ignore_errors=True)
        self.assertIn(f"out-{self.RUN_ID}-b<N>.jsonl", prompt)  # run_id 已注入，批次号 N 仍由 agent 自选
        self.assertNotIn("{run_id}", prompt)
        self.assertNotIn("<run_id>", prompt)
        self.assertIn(f"out-{self.RUN_ID}.jsonl", prompt)  # 主产物路径不受影响


class TestRepoConcurrencyPromptInjection(unittest.TestCase):
    """全仓审查并发注入（add-code-review-concurrency-and-429-resilience）。

    键（verify.repo_code_review_concurrency）约束提示词侧子代理并行扇出
    上限条款（波内并行、波次滚动推进）。2026-09-24 429 事故成因之一即
    并发不受控；ocr scan 并发源已随该步骤移除（2026-09-24 用户决策：
    scan 网络僵死致 run 自旋 2h20m，LLM 逐文件审查已稳定覆盖）。
    """

    RUN_ID = "code-review-1790210000"

    def _build(self, config=None):
        from core.agent_runner.prompt_builder import PromptBuilder

        pm = type("P", (), {"project_root": Path(_mkdtemp("cr-conc-")), "config": config or {}})()
        return PromptBuilder(pm), pm.project_root

    def test_default_four_injected(self):
        # 缺省 4：上限条款与 --concurrency 4 均渲染
        import shutil

        builder, proot = self._build()
        try:
            prompt = builder._build_code_review_prompt(
                self.RUN_ID,
                {"manifest": ["core/a.py"], "review_window": "（全仓）", "out_path": "/tmp/x.jsonl"},
            )
        finally:
            shutil.rmtree(str(proot), ignore_errors=True)
        self.assertIn("MUST ≤ `4`", prompt)  # 波内扇出上限条款
        self.assertNotIn("--concurrency", prompt)  # ocr scan 步骤已移除（2026-09-24）

    def test_config_value_two_rendered(self):
        # 配置值为 2 → 渲染 2（run_code_review 经 detail 传 repo_concurrency）
        import shutil

        builder, proot = self._build()
        try:
            prompt = builder._build_code_review_prompt(
                self.RUN_ID,
                {
                    "manifest": ["core/a.py"],
                    "review_window": "（全仓）",
                    "out_path": "/tmp/x.jsonl",
                    "repo_concurrency": 2,
                },
            )
        finally:
            shutil.rmtree(str(proot), ignore_errors=True)
        self.assertIn("MUST ≤ `2`", prompt)
        self.assertNotIn("--concurrency", prompt)  # ocr scan 步骤已移除（2026-09-24）

    def test_pm_config_fallback_used_when_detail_missing(self):
        # detail 未携带时回退 pm.config 读取器（run_code_review 正常都传；
        # 兜底路径走 get_repo_code_review_concurrency 缺省）
        import shutil

        builder, proot = self._build({"verify": {"repo_code_review_concurrency": 7}})
        try:
            prompt = builder._build_code_review_prompt(
                self.RUN_ID,
                {"manifest": ["core/a.py"], "review_window": "（全仓）", "out_path": "/tmp/x.jsonl"},
            )
        finally:
            shutil.rmtree(str(proot), ignore_errors=True)
        self.assertIn("MUST ≤ `7`", prompt)

    def test_no_placeholder_residue(self):
        # {repo_concurrency} 残留为零（未解析占位符防护）
        import shutil

        builder, proot = self._build()
        try:
            prompt = builder._build_code_review_prompt(
                self.RUN_ID,
                {"manifest": ["core/a.py"], "review_window": "（全仓）", "out_path": "/tmp/x.jsonl"},
            )
        finally:
            shutil.rmtree(str(proot), ignore_errors=True)
        self.assertNotIn("{repo_concurrency}", prompt)


class TestShardPathsNearMissWarning(unittest.TestCase):
    """shard_paths 错名分片探测：同素材缺前缀文件存在时 WARNING 点名，
    不改变消费行为（读侧口径保持 fail-显式，2026-09-24 事故防线二）。"""

    def setUp(self):
        self.proot = Path(_mkdtemp("cr-stray-"))
        self.crdir = self.proot / ".fenix" / "code-review"
        self.crdir.mkdir(parents=True)

    def tearDown(self):
        import shutil

        shutil.rmtree(str(self.proot), ignore_errors=True)

    def test_stray_epoch_named_shard_warns(self):
        from core.code_review import shard_paths

        # 错名分片（agent 截断 run_id 前缀段的事故形态）
        stray = self.crdir / "out-1790204913-b1.jsonl"
        stray.write_text(json.dumps({"file": "core/a.py", "findings": []}) + "\n", encoding="utf-8")
        with self.assertLogs("fenixd.code_review", level="WARNING") as captured:
            self.assertEqual(shard_paths(self.proot, "code-review-1790204913"), [])
        joined = "\n".join(captured.output)
        self.assertIn("1790204913", joined)
        self.assertIn("错名", joined)

    def test_canonical_shards_no_warning(self):
        from core.code_review import shard_paths

        p = self.crdir / "out-code-review-1790204914-b1.jsonl"
        p.write_text(json.dumps({"file": "core/a.py", "findings": []}) + "\n", encoding="utf-8")
        self.assertEqual(
            shard_paths(self.proot, "code-review-1790204914"),
            [p],
        )


class TestRunCodeReviewErrorSalvage(unittest.TestCase):
    """error 收场抢救（2026-09-24 429 事故）。

    run 中途死亡（网关 429/超时/强杀）≠ 零产出：分片直写模式下死前已落盘的
    分片与主产物行是真实审查结论，run_ok 门曾把整条消费链跳过（173 条发现
    滞留分片零落账，$23.68 白烧）。抢救语义：仅 upsert 入台账；manual_full
    MUST NOT 快照核销（部分覆盖下会把未审文件存量条目误置 resolved）；
    MUST NOT 触发 code-fix 检查点。
    """

    def setUp(self):
        self.proot = Path(_mkdtemp("cr-salvage-"))
        self.crdir = self.proot / ".fenix" / "code-review"
        self.crdir.mkdir(parents=True)
        self.run_id = "code-review-1790204915"

    def tearDown(self):
        import shutil

        shutil.rmtree(str(self.proot), ignore_errors=True)

    def _shard(self, n, rows):
        p = self.crdir / f"out-{self.run_id}-b{n}.jsonl"
        p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    def _fake_runner(self):
        from core.agent_runner import maintenance_runs as mr

        runner = type("R", (), {})()
        runner.project_root = self.proot
        runner.logger = None
        runner._unique_code_review_run_id = lambda: self.run_id
        runner._build_prompt = lambda *a, **k: "PROMPT"
        runner._get_agent_model_assignment = lambda name: None
        runner._get_admin_model = lambda: "test-model"
        runner._extract_usage_info = lambda x: {}
        runner._accumulate_code_review_tokens = lambda run_id, usage: None
        runner._read_code_review_out = lambda project_root, rid: mr._read_code_review_out(
            runner, project_root, rid
        )

        def _boom(*a, **k):
            raise RuntimeError(
                "API Error: Request rejected (429) · [1302][您的账户已达到速率限制]"
            )

        runner._run_agent = _boom
        return runner

    def _run(self, review_kind="manual_window"):
        from core.agent_runner import maintenance_runs as mr

        return mr.run_code_review(self._fake_runner(), ["core/a.py", "core/b.py"], review_kind)

    def test_error_run_salvages_preexisting_findings(self):
        self._shard(1, [{"file": "core/a.py", "findings": [
            {"line": 3, "severity": "major", "category": "correctness",
             "title": "抢救测试发现一。", "description": "d", "suggestion": "s",
             "evidence": "core/a.py:3"},
        ]}])
        (self.crdir / f"out-{self.run_id}.jsonl").write_text(
            json.dumps({"file": "core/b.py", "findings": []}) + "\n", encoding="utf-8"
        )
        result = self._run()
        self.assertFalse(result.success)
        self.assertIn("429", result.error)
        self.assertEqual(result.inserted, 1)
        self.assertEqual(result.updated, 0)
        items = [
            json.loads(x)
            for x in (self.crdir / "items.jsonl").read_text(encoding="utf-8").splitlines()
            if x.strip()
        ]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["file"], "core/a.py")
        self.assertEqual(items[0]["status"], "open")

    def test_salvage_manual_full_skips_snapshot_resolution(self):
        from core.code_review import upsert_findings

        # 存量 open 条目：未被本轮（部分覆盖）观测的文件，抢救后 MUST 保持 open
        upsert_findings(
            self.proot,
            [{"file": "core/unreviewed.py", "category": "maintainability",
              "title": "存量未被本轮观测。", "severity": "minor", "description": "d",
              "suggestion": "s", "evidence": "e"}],
            review_id="code-review-1790204914",
            review_kind="manual_full",
        )
        self._shard(1, [{"file": "core/a.py", "findings": [
            {"line": 1, "severity": "minor", "category": "maintainability",
             "title": "本轮观测的新发现。", "description": "d", "suggestion": "s",
             "evidence": "e"},
        ]}])
        result = self._run("manual_full")
        self.assertFalse(result.success)
        self.assertEqual(result.resolved, 0)
        from core.code_review import read_items

        items = read_items(self.proot)
        seeded = [r for r in items.values() if r.get("file") == "core/unreviewed.py"]
        self.assertEqual(len(seeded), 1)
        self.assertEqual(seeded[0]["status"], "open")

    def test_salvage_without_artifacts_is_noop(self):
        result = self._run()
        self.assertFalse(result.success)
        self.assertEqual(result.inserted, 0)
        self.assertNotIn("抢救", result.error)
        self.assertFalse((self.crdir / "items.jsonl").exists())


# ── add-code-review-trigger-ack：回链写侧 / 读侧 / 窗口守卫 ────────────


class TestRequestResultWriteRead(unittest.TestCase):
    """回链结果写工具与读函数（task 1.1 / 4.1 payload 键与原子性 / 4.2 读侧）。"""

    _RESULT_REL = Path(".fenix") / "code_review_request_result.json"

    def test_write_started_keys_and_roundtrip(self):
        from core.code_review import read_request_result, write_request_result

        proot = Path(_mkdtemp("cr-req-"))
        try:
            ok = write_request_result(
                proot, "2026-09-24T00:00:00+00:00", "started", None, "审查已受理")
            self.assertTrue(ok)
            raw = json.loads((proot / self._RESULT_REL).read_text(encoding="utf-8"))
            # payload 键齐全：requested_at 回链 + status + reason + message +
            # finished_at（UTC ISO8601 写入时刻）
            self.assertEqual(
                set(raw.keys()),
                {"requested_at", "status", "reason", "message", "finished_at"},
            )
            self.assertEqual(raw["requested_at"], "2026-09-24T00:00:00+00:00")
            self.assertEqual(raw["status"], "started")
            self.assertIsNone(raw["reason"])
            self.assertTrue(raw["finished_at"])
            # 读侧原样透传
            self.assertEqual(read_request_result(proot), raw)
        finally:
            import shutil
            shutil.rmtree(str(proot), ignore_errors=True)

    def test_write_is_same_dir_tmp_plus_replace(self):
        """原子性（tmp + os.replace）：tmp 在同目录、经 replace 原子挂到目标。"""
        from unittest.mock import patch

        from core.code_review import write_request_result

        proot = Path(_mkdtemp("cr-req2-"))
        target = proot / self._RESULT_REL
        try:
            seen = []

            real_replace = os.replace

            def _spy_replace(src, dst, *a, **kw):
                seen.append((str(src), str(dst)))
                return real_replace(src, dst, *a, **kw)

            with patch("os.replace", side_effect=_spy_replace):
                self.assertTrue(write_request_result(proot, "r0", "dropped", "already_running"))
            self.assertEqual(len(seen), 1)
            src, dst = seen[0]
            self.assertEqual(Path(src).parent, target.parent, "tmp MUST 与目标同目录")
            # mkstemp 唯一临时名（.{name}.{rand}.tmp）：并发写方互不踩踏；
            # 旧「固定名 .tmp」断言已随 item 629d47de2b54 修复失效
            self.assertTrue(src.endswith(".tmp"))
            self.assertNotEqual(src, str(target) + ".tmp")
            self.assertEqual(Path(dst), target)
            self.assertFalse(list(target.parent.glob("*.tmp")), "replace 后无 tmp 残留")
        finally:
            import shutil
            shutil.rmtree(str(proot), ignore_errors=True)

    def test_write_failure_leaves_old_content_intact(self):
        """replace 失败（OSError）不半写：旧内容原样、无 tmp 残留、返回 False。"""
        from unittest.mock import patch

        from core.code_review import write_request_result

        proot = Path(_mkdtemp("cr-req3-"))
        target = proot / self._RESULT_REL
        target.parent.mkdir(parents=True, exist_ok=True)
        old = {"requested_at": "old", "status": "started", "reason": None,
               "message": "旧", "finished_at": "old"}
        target.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
        try:
            with patch("os.replace", side_effect=OSError("disk full")):
                self.assertFalse(write_request_result(proot, "new", "started"))
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), old)
            self.assertFalse(list(target.parent.glob("*.tmp")))
        finally:
            import shutil
            shutil.rmtree(str(proot), ignore_errors=True)

    def test_read_defaults_not_raise(self):
        """缺省态（task 4.2 读侧）：缺失/损坏/非 dict → 全 null 缺省态，不抛异常。"""
        from core.code_review import read_request_result

        default = {
            "requested_at": None, "status": None, "reason": None,
            "message": None, "finished_at": None,
        }
        proot = Path(_mkdtemp("cr-req4-"))
        try:
            # 缺失
            self.assertEqual(read_request_result(proot), default)
            # JSON 损坏
            (proot / self._RESULT_REL).parent.mkdir(parents=True, exist_ok=True)
            (proot / self._RESULT_REL).write_text("{broken", encoding="utf-8")
            self.assertEqual(read_request_result(proot), default)
            # 顶层非 dict
            (proot / self._RESULT_REL).write_text("[1,2]", encoding="utf-8")
            self.assertEqual(read_request_result(proot), default)
        finally:
            import shutil
            shutil.rmtree(str(proot), ignore_errors=True)


class _FakeDaemonLogger:
    def __getattr__(self, name):
        return lambda *a, **k: None


class _RecExecutor:
    """记录 submit 的假线程池（不执行任务——worker 由测试显式驱动）。"""

    def __init__(self):
        self.jobs = []

    def submit(self, fn, *args, **kwargs):
        self.jobs.append((fn, args, kwargs))


class _BoomExecutor:
    def submit(self, fn, *args, **kwargs):
        raise RuntimeError("pool closed")


class _InlineExecutor:
    """submit 内联同步执行 worker——复现真实线程池「worker 与主线程并发收尾、
    可领跑」的时序面（_RecExecutor 不执行任务，覆盖不到该时序）。"""

    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)


class _FakeMonitor:
    def __init__(self, in_flight=False):
        self._code_review_in_flight = in_flight


class _FakeRunner:
    def __init__(self):
        self._running_agents = {}


def _fresh_requested_at() -> str:
    """信号 requested_at 动态取「当前时刻 −5min」（测试侧时间炸弹修复）。

    时效分档守卫 _signal_created_is_stale（item 3213135bc86f）以消费方时钟
    判 stale：写死绝对时间戳会随真实时间流逝跨过 1h 阈值——原固定值
    2026-09-24T08:00Z 自写入后 1 小时起即被判 stale_created，fresh 路径
    用例全数落空。−5min 既稳在阈值内，又容忍导入到执行间的时钟差。
    """
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()


class TestCodeReviewTriggerConsume(unittest.TestCase):
    """daemon 消费端三态落盘（task 4.1）：started/dropped/failed、单飞旗标
    置位/复位顺序不变、守卫拒绝与 payload 非法不静默。"""

    _REQ_AT = _fresh_requested_at()

    def _mk_proot(self) -> Path:
        proot = Path(_mkdtemp("cr-consume-"))
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        return proot

    def _make_daemon(self, proot, executor):
        import fenixd

        daemon = fenixd.FenixDaemon.__new__(fenixd.FenixDaemon)
        daemon.running = True
        daemon.agent_runner = _FakeRunner()
        daemon.admin_monitor = _FakeMonitor()
        daemon._admin_executor = executor
        # 池统计字段（code-review item c979d0ffe6f8 后手动车道会维护池计数）：
        # 生产 __init__ 恒装配，__new__ 裸构替身须同步补齐（与 fenixd.py:449
        # 同构），否则池路径 submit 前递增即 AttributeError。
        daemon._admin_pool_lock = threading.Lock()
        daemon._admin_pool_stats = {"submitted": 0, "completed": 0, "failed": 0}
        daemon.config = {}
        daemon.logger = _FakeDaemonLogger()
        return daemon

    def _write_signal(self, proot, requested_at=None, raw=None):
        req = proot / ".fenix" / "code_review_request.json"
        req.write_text(
            raw if raw is not None else json.dumps(
                {"scope": "window", "source": "dashboard",
                 "requested_at": requested_at or self._REQ_AT}),
            encoding="utf-8")
        return req

    def _root_ctx(self, proot, hosting="managed"):
        """PROJECT_ROOT/hosting_state patch 上下文：消费与 worker 驱动必须在
        同一上下文内执行——worker 闭包在调用时读取 fenixd.PROJECT_ROOT 全局，
        上下文退出后驱动会把结果文件写到真实仓库根。"""
        import fenixd
        from unittest.mock import patch

        return patch.object(fenixd, "PROJECT_ROOT", proot), \
            patch("core.fenix_session.hosting_state", lambda p: hosting)

    def _consume(self, proot, daemon, hosting="managed"):
        ctx_root, ctx_host = self._root_ctx(proot, hosting)
        with ctx_root, ctx_host:
            daemon._check_code_review_requests()

    def _read_result(self, proot):
        path = proot / ".fenix" / "code_review_request_result.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def test_started_after_submit_and_flag_order(self):
        """投递成功 → started 结果（requested_at 回链）且旗标置位；worker 跑完
        复位旗标（置位/复位顺序与现状一致，落盘不改控制流）。"""
        proot = self._mk_proot()
        executor = _RecExecutor()
        daemon = self._make_daemon(proot, executor)
        self._write_signal(proot)
        self._consume(proot, daemon)

        res = self._read_result(proot)
        self.assertEqual(res["status"], "started")
        self.assertEqual(res["requested_at"], self._REQ_AT, "结果 MUST 回链信号 requested_at")
        self.assertIsNone(res["reason"])
        self.assertTrue(res["message"])
        self.assertTrue(res["finished_at"])
        self.assertFalse((proot / ".fenix" / "code_review_request.json").exists(),
                         "信号消费后删除")
        self.assertTrue(daemon.admin_monitor._code_review_in_flight,
                        "投递成功后单飞旗标处于置位态（与现状一致）")
        # 驱动 worker 跑完 → 旗标复位（置位/复位顺序与现状一致）；worker 内
        # manifest_empty 分支落盘覆盖 started。必须在 PROJECT_ROOT patch 上下文
        # 内驱动（闭包按调用时全局取根）；manifest 收集打桩为零——临时目录
        # 位于本仓库 .history/tmp 内，git 会上溯到真实仓库使收集结果不确定
        from unittest.mock import patch

        ctx_root, _ = self._root_ctx(proot)
        with patch("core.code_review.collect_manifest", lambda *a, **k: []), \
                patch("core.code_review.compute_window", lambda *a, **k: (None, None)), \
                ctx_root:
            executor.jobs[0][0]()
        self.assertFalse(daemon.admin_monitor._code_review_in_flight,
                         "worker 结束后旗标复位（与现状一致）")
        # worker 的 manifest_empty 落盘发生在 started 之后（覆盖写属预期：
        # 消费窗口内后到的判定覆盖前一条）
        self.assertEqual(self._read_result(proot)["status"], "failed")

    def test_worker_manifest_empty_failed(self):
        """manifest 为空 → worker 落 failed/manifest_empty，不静默跳过。"""
        from unittest.mock import patch

        from core.code_review import compute_window as _cw

        proot = self._mk_proot()
        executor = _RecExecutor()
        daemon = self._make_daemon(proot, executor)
        self._write_signal(proot)
        ctx_root, _ = self._root_ctx(proot)
        with patch("core.code_review.collect_manifest", lambda *a, **k: []), \
                patch("core.code_review.compute_window", lambda *a, **k: (None, None)), \
                ctx_root:
            self._consume(proot, daemon)
            executor.jobs[0][0]()

        res = self._read_result(proot)
        self.assertEqual(res["status"], "failed")
        self.assertEqual(res["reason"], "manifest_empty")
        self.assertEqual(res["requested_at"], self._REQ_AT)
        self.assertFalse(daemon.admin_monitor._code_review_in_flight)

    def test_worker_manifest_error_failed(self):
        """collect_manifest 抛异常 → worker 落 failed/manifest_error。"""
        from unittest.mock import patch

        def _boom(*a, **k):
            raise RuntimeError("git failed")

        proot = self._mk_proot()
        executor = _RecExecutor()
        daemon = self._make_daemon(proot, executor)
        self._write_signal(proot)
        ctx_root, _ = self._root_ctx(proot)
        with patch("core.code_review.collect_manifest", _boom), \
                patch("core.code_review.compute_window",
                      lambda *a, **k: (_cw_safe(), None)), \
                ctx_root:
            self._consume(proot, daemon)
            executor.jobs[0][0]()

        res = self._read_result(proot)
        self.assertEqual(res["status"], "failed")
        self.assertEqual(res["reason"], "manifest_error")
        self.assertFalse(daemon.admin_monitor._code_review_in_flight)

    def test_already_running_dropped_flag_untouched(self):
        """单飞在跑 → dropped/already_running，旗标保持置位（顺序不变）。"""
        proot = self._mk_proot()
        executor = _RecExecutor()
        daemon = self._make_daemon(proot, executor)
        daemon.admin_monitor._code_review_in_flight = True
        self._write_signal(proot)
        self._consume(proot, daemon)

        res = self._read_result(proot)
        self.assertEqual(res["status"], "dropped")
        self.assertEqual(res["reason"], "already_running")
        self.assertEqual(res["requested_at"], self._REQ_AT)
        self.assertIn("在跑", res["message"])
        self.assertTrue(daemon.admin_monitor._code_review_in_flight)
        self.assertEqual(executor.jobs, [], "单飞拒绝 MUST NOT 投递")

    def test_hosting_guard_dropped_distinct_reasons(self):
        """守卫拒绝（stopped/unmanaged）→ dropped，reason 区分两种状态。"""
        for hosting, reason in (("stopped", "daemon_not_running"),
                                ("unmanaged", "daemon_unmanaged")):
            proot = self._mk_proot()
            daemon = self._make_daemon(proot, _RecExecutor())
            self._write_signal(proot)
            self._consume(proot, daemon, hosting=hosting)
            res = self._read_result(proot)
            self.assertEqual(res["status"], "dropped", hosting)
            self.assertEqual(res["reason"], reason)
            self.assertEqual(res["requested_at"], self._REQ_AT)
            self.assertTrue(res["message"])

    def test_invalid_payload_dropped(self):
        """信号在场但 payload 损坏 → dropped/invalid_payload（不再静默）。"""
        proot = self._mk_proot()
        daemon = self._make_daemon(proot, _RecExecutor())
        self._write_signal(proot, raw="{not-json")
        self._consume(proot, daemon)

        res = self._read_result(proot)
        self.assertEqual(res["status"], "dropped")
        self.assertEqual(res["reason"], "invalid_payload")
        self.assertFalse(
            (proot / ".fenix" / "code_review_request.json").exists(),
            "损坏信号已被消费删除")

    def test_submit_error_failed_and_flag_reset(self):
        """投递异常 → failed/submit_error 且单飞旗标复位逻辑保持。"""
        proot = self._mk_proot()
        daemon = self._make_daemon(proot, _BoomExecutor())
        self._write_signal(proot)
        self._consume(proot, daemon)

        res = self._read_result(proot)
        self.assertEqual(res["status"], "failed")
        self.assertEqual(res["reason"], "submit_error")
        self.assertEqual(res["requested_at"], self._REQ_AT)
        self.assertFalse(daemon.admin_monitor._code_review_in_flight,
                         "submit 异常分支的既有复位逻辑不变")

    def test_started_receipt_before_submit_never_overwrites_fast_failed(self):
        """BUG-01 回归（验证场景 cli-consume-branches-inprocess 分支 f/g）：
        worker 池投递主路径 MUST 先落 started 受理回执再 submit——worker 快速
        失败（manifest 为空）后写盘的 failed 三态是最终态，MUST NOT 被主线程
        随后回写的 started 覆盖（否则前端把失败误显示为「正在启动」）。内联
        executor 使 worker 在 submit 调用内同步跑完，精确复现该时序。"""
        from unittest.mock import patch

        proot = self._mk_proot()
        daemon = self._make_daemon(proot, _InlineExecutor())
        self._write_signal(proot)
        ctx_root, _ = self._root_ctx(proot)
        with patch("core.code_review.collect_manifest", lambda *a, **k: []), \
                patch("core.code_review.compute_window", lambda *a, **k: (None, None)), \
                ctx_root:
            self._consume(proot, daemon)

        res = self._read_result(proot)
        self.assertEqual(res["status"], "failed",
                         "worker 快速失败的 failed MUST 是最终落盘态")
        self.assertEqual(res["reason"], "manifest_empty")
        self.assertEqual(res["requested_at"], self._REQ_AT)
        self.assertFalse(daemon.admin_monitor._code_review_in_flight)


def _cw_safe():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


class _FakeCodeReviewRoute:
    """H11CodeReviewRoutesMixin 最小宿主（窗口守卫/端点直呼测试，task 4.2）。"""

    def __init__(self, proot, body=None, exists=True):
        self._proot = str(proot)
        self._body = body if body is not None else {"scope": "window"}
        self._exists = exists
        self.response = None

    def _project_from_query(self, query):
        if not self._exists:
            return None
        return {"name": "proj-a", "path": self._proot, "exists": True}

    def _read_json_body(self):
        return self._body

    def _json(self, obj, status=200):
        self.response = (status, obj)

    def _error(self, status, msg):
        self.response = (status, {"error": msg})

    def _coded_error(self, status, msg, code):
        self.response = (status, {"error": msg, "code": code})


def _mk_progress_project(running=False, run_id="code-review-1758211200"):
    """构造带 review run 产物的项目根：running=True → 非 terminal 新鲜 run；
    running=False → 仅 manifest（running=false 但 review_id 在场）。"""
    import time as _time

    from core.code_review import code_review_dir, out_path

    proot = Path(_mkdtemp("cr-guard-"))
    cr = code_review_dir(proot)
    cr.mkdir(parents=True)
    (cr / f"manifest-{run_id}.json").write_text(
        json.dumps({"files": [f"core/f{i}.py" for i in range(3)],
                    "review_kind": "manual_full"}),
        encoding="utf-8")
    if running:
        with open(out_path(proot, run_id), "w", encoding="utf-8") as f:
            f.write(json.dumps({"file": "core/f0.py", "category": "c", "title": "t"}) + "\n")
        runs = proot / ".fenix" / "runs"
        runs.mkdir(parents=True)
        run_file = runs / f"{run_id}.jsonl"
        run_file.write_text(
            json.dumps({"type": "system", "message": "start"}) + "\n", encoding="utf-8")
        _time.sleep(0.01)  # mtime 新鲜（避开 stale 阈值边界）
    return proot


def _put_result(proot, payload):
    path = Path(proot) / ".fenix" / "code_review_request_result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class TestCodeReviewRunResultAPI(unittest.TestCase):
    """GET run-result 端点与 POST run 受理窗口守卫（task 4.2）。"""

    def _route(self, proot, exists=True):
        from core.dashboard.routes.code_review_routes import H11CodeReviewRoutesMixin

        cls = type(
            "_FakeRoute", (H11CodeReviewRoutesMixin,),
            {name: getattr(_FakeCodeReviewRoute, name)
             for name in ("__init__", "_project_from_query", "_read_json_body",
                          "_json", "_error", "_coded_error")},
        )
        return cls(proot, exists=exists)

    def _post_run(self, proot, hosting="managed"):
        from unittest.mock import patch

        h = self._route(proot)
        with patch("core.fenix_session.hosting_state", lambda p: hosting):
            h._api_code_review_run({})
        return h.response

    def _cleanup(self, proot):
        import shutil
        shutil.rmtree(str(proot), ignore_errors=True)

    # ── GET run-result ────────────────────────────────────────────

    def test_run_result_default_when_missing(self):
        from core.code_review import read_request_result

        proot = Path(_mkdtemp("cr-api-"))
        try:
            h = self._route(proot)
            h._api_code_review_run_result({})
            status, body = h.response
            self.assertEqual(status, 200)
            self.assertEqual(body, read_request_result(proot))
            self.assertIsNone(body["requested_at"])
            self.assertIsNone(body["status"])
        finally:
            self._cleanup(proot)

    def test_run_result_passthrough_and_corrupt_and_404(self):
        from core.code_review import write_request_result

        proot = Path(_mkdtemp("cr-api2-"))
        try:
            write_request_result(proot, "2026-09-24T00:00:00+00:00", "dropped",
                                 "already_running", "已有审查在跑")
            h = self._route(proot)
            h._api_code_review_run_result({})
            status, body = h.response
            self.assertEqual(status, 200)
            self.assertEqual(body["status"], "dropped")
            self.assertEqual(body["reason"], "already_running")

            # 损坏 → 缺省态 200 不 500
            (proot / ".fenix" / "code_review_request_result.json").write_text(
                "{broken", encoding="utf-8")
            h = self._route(proot)
            h._api_code_review_run_result({})
            status, body = h.response
            self.assertEqual(status, 200)
            self.assertIsNone(body["status"])

            # 项目不存在 → 404
            h = self._route(proot, exists=False)
            h._api_code_review_run_result({})
            self.assertEqual(h.response[0], 404)
        finally:
            self._cleanup(proot)

    # ── POST run 受理窗口守卫（design D3 四分支） ──────────────────

    def test_ack_window_409_when_started_pending(self):
        """started + 未 running + 新鲜 + 无更新 run → 409 code_review_ack_pending，
        信号文件不被写入。"""
        proot = _mk_progress_project(running=False)
        try:
            _put_result(proot, {"requested_at": "r0", "status": "started",
                                "reason": None, "message": "启动中",
                                "finished_at": _iso_now()})
            status, body = self._post_run(proot)
            self.assertEqual(status, 409)
            self.assertEqual(body.get("code"), "code_review_ack_pending")
            self.assertFalse(
                (proot / ".fenix" / "code_review_request.json").exists(),
                "守卫拒绝 MUST NOT 写信号")
        finally:
            self._cleanup(proot)

    def test_running_guard_wins_with_existing_code(self):
        """running=true → 既有 code_review_running 409 先命中（语义不变）。"""
        proot = _mk_progress_project(running=True)
        try:
            _put_result(proot, {"requested_at": "r0", "status": "started",
                                "reason": None, "message": "启动中",
                                "finished_at": _iso_now()})
            status, body = self._post_run(proot)
            self.assertEqual(status, 409)
            self.assertEqual(body.get("code"), "code_review_running")
        finally:
            self._cleanup(proot)

    def test_stale_result_passes_through(self):
        """陈旧结果（finished_at 距今 > 900s）→ 守卫放行，信号正常写入。"""
        from datetime import timedelta

        proot = _mk_progress_project(running=False)
        try:
            _put_result(proot, {"requested_at": "r0", "status": "started",
                                "reason": None, "message": "启动中",
                                "finished_at": _iso_now(timedelta(seconds=-1000))})
            status, body = self._post_run(proot)
            self.assertEqual(status, 200)
            self.assertTrue(body.get("ok"))
            self.assertTrue(
                (proot / ".fenix" / "code_review_request.json").exists())
        finally:
            self._cleanup(proot)

    def test_newer_run_epoch_passes_through(self):
        """run 已结束但 review_id epoch > finished_at（受理的 run 已跑完）→
        守卫放行，不误判「排队中」假 409。"""
        from datetime import timedelta

        # epoch 4102444800 = 2100-01-01，远晚于 finished_at（now-1s）
        proot = _mk_progress_project(running=False, run_id="code-review-4102444800")
        try:
            _put_result(proot, {"requested_at": "r0", "status": "started",
                                "reason": None, "message": "启动中",
                                "finished_at": _iso_now(timedelta(seconds=-1))})
            status, body = self._post_run(proot)
            self.assertEqual(status, 200)
            self.assertTrue(body.get("ok"))
            self.assertTrue(
                (proot / ".fenix" / "code_review_request.json").exists())
        finally:
            self._cleanup(proot)


def _iso_now(offset=None):
    from datetime import datetime, timedelta, timezone

    delta = offset if offset is not None else timedelta(0)
    return (datetime.now(timezone.utc) + delta).isoformat()


class _RecDaemonLogger:
    """可断言的 daemon logger 桩（fenixd 两参调用形态 info("fenixd", msg)）。"""

    def __init__(self):
        self.records = []

    def _rec(self, lvl, *a):
        self.records.append((lvl, a[1] if len(a) > 1 else str(a[0] if a else "")))

    def info(self, *a, **k):
        self._rec("info", *a)

    def warning(self, *a, **k):
        self._rec("warning", *a)

    def error(self, *a, **k):
        self._rec("error", *a)

    def has(self, text):
        return any(text in m for _lvl, m in self.records)


class _ScheduleRecorder:
    """手动 worker 上交意图的 admin_monitor 桩（记录 _schedule_ratelimit_redispatch）。"""

    def __init__(self, boom=False):
        self.calls = []
        self._boom = boom
        self._code_review_in_flight = False

    def _schedule_ratelimit_redispatch(self, manifest, review_kind, window_start,
                                       scope, intent):
        # 显式签名对齐 admin_monitor 同名方法（替身保真守卫禁 **kwargs 宽容替身）
        if self._boom:
            raise RuntimeError("timer arm failed")
        self.calls.append(dict(
            manifest=manifest, review_kind=review_kind,
            window_start=window_start, scope=scope, intent=intent,
        ))


class TestManualFullOpenBacklogGuard(unittest.TestCase):
    """手动 full 触发防叠加（evo-add-code-review-ratelimit-resume 4.1，task 5.2）。

    上一轮全仓审查未消化完（台账 open 超阈值）时手动 full 触发回 409 确认态
    （code=code_review_open_backlog，对齐 trigger-ack 409 守卫先例），body
    携带 confirm=true 的二次请求才放行；阈值入配置（缺省 30，显式 0 = 关闭）。
    """

    def setUp(self):
        self.proot = Path(_mkdtemp("cr-backlog-"))
        (self.proot / ".fenix").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        import shutil

        shutil.rmtree(str(self.proot), ignore_errors=True)

    def _seed_open(self, n):
        from core.code_review import upsert_findings

        upsert_findings(self.proot, [
            {"file": f"core/f{i}.py", "category": "maintainability",
             "title": f"存量条目 {i}。", "severity": "minor",
             "description": "d", "suggestion": "s", "evidence": "e"}
            for i in range(n)
        ], review_id="seed", review_kind="manual_full")

    def _post(self, body, cfg=None):
        from unittest.mock import patch

        from core.dashboard import data as dashboard_data
        from core.dashboard.routes.code_review_routes import (
            H11CodeReviewRoutesMixin,
        )

        route = _FakeCodeReviewRoute(self.proot, body=body)
        with patch.object(dashboard_data, "read_effective_config",
                          lambda p: cfg or {}), \
                patch("core.fenix_session.hosting_state", lambda p: "managed"):
            H11CodeReviewRoutesMixin._api_code_review_run(route, {})
        return route.response

    def test_config_threshold_default_invalid_and_zero(self):
        from core.config import ConfigLoader

        self.assertEqual(
            ConfigLoader.get_code_review_config({})["manual_full_open_warn"], 30)
        self.assertEqual(
            ConfigLoader.get_code_review_config(
                {"admin": {"code_review": {"manual_full_open_warn": 0}}}
            )["manual_full_open_warn"], 0)
        for bad in (-1, True, "40", 1.5):
            self.assertEqual(
                ConfigLoader.get_code_review_config(
                    {"admin": {"code_review": {"manual_full_open_warn": bad}}}
                )["manual_full_open_warn"], 30, bad)

    def test_over_threshold_full_returns_409_confirm_state(self):
        """open 超缺省阈值 30 → 409 确认态，未确认不派发（信号不落盘）。"""
        self._seed_open(31)
        status, body = self._post({"scope": "full"})
        self.assertEqual(status, 409)
        self.assertEqual(body.get("code"), "code_review_open_backlog")
        self.assertIn("confirm=true", body.get("error", ""))
        self.assertFalse(
            (self.proot / ".fenix" / "code_review_request.json").exists())

    def test_confirm_true_proceeds(self):
        """二次确认（confirm=true）→ 放行派发（信号文件落盘）。"""
        self._seed_open(31)
        status, body = self._post({"scope": "full", "confirm": True})
        self.assertEqual(status, 200)
        self.assertTrue(body.get("ok"))
        self.assertTrue(
            (self.proot / ".fenix" / "code_review_request.json").exists())

    def test_window_scope_not_guarded(self):
        """守卫只作用于 full 触发（window 审查不叠加全仓核销风险）。"""
        self._seed_open(31)
        status, _body = self._post({"scope": "window"})
        self.assertEqual(status, 200)

    def test_under_threshold_passes(self):
        self._seed_open(2)
        status, _body = self._post({"scope": "full"})
        self.assertEqual(status, 200)

    def test_zero_threshold_disables_guard(self):
        """显式 0 = 关闭守卫（回退历史行为）。"""
        self._seed_open(31)
        status, _body = self._post(
            {"scope": "full"},
            cfg={"admin": {"code_review": {"manual_full_open_warn": 0}}})
        self.assertEqual(status, 200)


class TestManualWorkerRatelimitConsume(unittest.TestCase):
    """手动 worker 消费 429 重派意图（evo-add-code-review-ratelimit-resume
    2.1/2.2，task 5.2）。

    手动车道与周期车道同源消费：上交同一 admin_monitor 实例的
    _schedule_ratelimit_redispatch（300 秒冷却延迟重投递、上限 1、单飞让位
    均在其内部实现，双车道共享计数防叠加）；admin_monitor 未装配（fallback）
    时记日志放弃并保持告警可见，不静默丢弃。
    """

    _REQ_AT = _fresh_requested_at()

    def setUp(self):
        self.proot = Path(_mkdtemp("cr-manual-rl-"))
        (self.proot / ".fenix").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        import shutil

        shutil.rmtree(str(self.proot), ignore_errors=True)

    @staticmethod
    def _mk_daemon(proot, monitor):
        from unittest.mock import MagicMock

        import fenixd

        daemon = fenixd.FenixDaemon.__new__(fenixd.FenixDaemon)
        daemon.running = True
        daemon.agent_runner = MagicMock()
        daemon.admin_monitor = monitor
        daemon._admin_executor = _RecExecutor()
        # 池统计字段（code-review item c979d0ffe6f8 后手动车道会维护池计数）：
        # 生产 __init__ 恒装配，__new__ 裸构替身须同步补齐（与 fenixd.py:449
        # 同构），否则池路径 submit 前递增即 AttributeError。
        daemon._admin_pool_lock = threading.Lock()
        daemon._admin_pool_stats = {"submitted": 0, "completed": 0, "failed": 0}
        daemon.config = {}
        daemon.logger = _RecDaemonLogger()
        return daemon

    def _signal(self):
        (self.proot / ".fenix" / "code_review_request.json").write_text(
            json.dumps({"scope": "full", "source": "dashboard",
                        "requested_at": self._REQ_AT}), encoding="utf-8")

    def _consume_and_drive(self, daemon, run_result):
        """消费信号并驱动手动 worker（均在 PROJECT_ROOT patch 上下文内）。"""
        from unittest.mock import patch

        import fenixd

        daemon.agent_runner.run_code_review.return_value = run_result
        with patch.object(fenixd, "PROJECT_ROOT", self.proot), \
                patch("core.fenix_session.hosting_state", lambda p: "managed"), \
                patch("core.code_review.collect_manifest",
                      lambda *a, **k: ["core/a.py", "core/b.py"]):
            daemon._check_code_review_requests()
            executor = daemon._admin_executor
            if executor.jobs:
                executor.jobs[0][0]()

    @staticmethod
    def _intent():
        import time

        return {"reason": "429 ratelimit", "provider": "inferaiapi.com",
                "run_id": "run-m", "max_redispatches": 1,
                "cooldown_until_epoch": time.time() + 300}

    @staticmethod
    def _run_result(intent):
        from unittest.mock import MagicMock

        return MagicMock(run_id="run-m", inserted=0, updated=0, resolved=0,
                         shards=2, error="429 ...",
                         ratelimit_redispatch=intent)

    def test_worker_hands_intent_to_admin_monitor(self):
        """手动审查死于 429 → 意图上交同一 admin_monitor 排程（300 秒冷却与
        上限 1 由其内部既有实现承接）。"""
        monitor = _ScheduleRecorder()
        daemon = self._mk_daemon(self.proot, monitor)
        self._signal()
        self._consume_and_drive(daemon, self._run_result(self._intent()))
        self.assertEqual(len(monitor.calls), 1, "窗口内不重复排程（上限 1）")
        call = monitor.calls[0]
        self.assertEqual(call["manifest"], ["core/a.py", "core/b.py"])
        self.assertEqual(call["review_kind"], "manual_full")
        self.assertIsNone(call["window_start"])
        self.assertEqual(call["scope"], "full")
        self.assertEqual(call["intent"]["run_id"], "run-m")

    def test_worker_without_intent_does_not_schedule(self):
        monitor = _ScheduleRecorder()
        daemon = self._mk_daemon(self.proot, monitor)
        self._signal()
        self._consume_and_drive(daemon, self._run_result(None))
        self.assertEqual(monitor.calls, [])

    def test_worker_without_monitor_logs_and_survives(self):
        """fallback 宿主（admin_monitor 未装配）→ 意图记日志放弃不静默。"""
        daemon = self._mk_daemon(self.proot, None)
        self._signal()
        self._consume_and_drive(daemon, self._run_result(self._intent()))
        self.assertTrue(daemon.logger.has("重派意图放弃"))

    def test_worker_schedule_error_resets_flag(self):
        """排程异常不吞 run 终态：日志 error 且单飞旗标复位。"""
        monitor = _ScheduleRecorder(boom=True)
        daemon = self._mk_daemon(self.proot, monitor)
        self._signal()
        self._consume_and_drive(daemon, self._run_result(self._intent()))
        self.assertTrue(daemon.logger.has("排程失败"))
        self.assertFalse(daemon.admin_monitor._code_review_in_flight)


# ── evo-review-empty-product-redispatch：零产物止损链路 ────────────────


class _MonitorFakeLogger:
    """(component, message) 签名的监控器日志替身（stdlib logging 对双参调用
    会把第二参当 % 格式参数——监控器生产注入的是项目 Logger 同签者）。"""

    def __init__(self):
        self.infos = []
        self.warns = []
        self.errors = []

    def info(self, component, message, *a, **k):
        self.infos.append(f"{component} {message}")

    def warning(self, component, message, *a, **k):
        self.warns.append(f"{component} {message}")

    def error(self, component, message, *a, **k):
        self.errors.append(f"{component} {message}")


class _EmptyFaceMixins:
    """零产物止损测试共用小工具（face 构造 / 结果桩 / 告警读取）。"""

    @staticmethod
    def _face(run_id, variant="zero_valid_rows", manifest_count=2):
        return {
            "run_id": run_id,
            "manifest_count": manifest_count,
            "variant": variant,
            "shards": 0,
            "sources_present": 0,
            "unreadable": [],
        }

    @staticmethod
    def _result(run_id, face=None, error=""):
        from types import SimpleNamespace

        return SimpleNamespace(
            run_id=run_id,
            success=face is None,
            inserted=0,
            updated=0,
            resolved=0,
            shards=0,
            error=error or (f"gate: {face['variant']}" if face else ""),
            fail_face=face,
            ratelimit_redispatch=None,
        )

    def _alerts(self, monitor):
        p = self.repo / ".fenix" / "admin_alerts.json"
        if not p.exists():
            return []
        text = p.read_text(encoding="utf-8").strip()
        if not text:
            return []
        data = json.loads(text)
        return [e for e in data if isinstance(e, dict)]


class TestEmptyProductRedispatchChain(_EmptyFaceMixins, unittest.TestCase):
    """零产物止损链路（evo-review-empty-product-redispatch 1.1，task 3.1）。

    钉住「零有效行拦截 → 自动重派恰 1 次 → 重派仍失败 → admin 升级信号且
    不再重派」全链（stub run 函数，不真实派发），以及零产物与 429 两通道
    限次合计语义、互不叠加调度同一 run 链。
    """

    def setUp(self):
        self.repo = Path(_mkdtemp("cr-empty-"))
        (self.repo / ".fenix").mkdir(parents=True, exist_ok=True)
        (self.repo / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        import shutil

        shutil.rmtree(str(self.repo), ignore_errors=True)

    def _monitor(self, runner):
        from core.admin_monitor import AdminMonitor

        cfg = {
            "admin": {
                "code_review": {"enabled": True, "run_at": "00:00"},
                "self_review": {"enabled": True, "run_at": "00:00"},
            }
        }
        return AdminMonitor(
            cfg, None, str(self.repo), _MonitorFakeLogger(),
            agent_runner=runner, code_review_executor=None,
        )

    def _checkpoint(self, monitor):
        from unittest.mock import patch

        with patch("core.code_review.collect_manifest",
                   lambda *a, **k: ["core/a.py", "core/b.py"]):
            return monitor._run_code_review_checkpoint()

    def _scripted_runner(self, outcomes):
        """stub run_code_review：按脚本依次返回结果并记录调用（不真实派发）。"""
        runner = type("R", (), {})()
        runner._running_agents = {}
        calls = []

        def run_code_review(manifest, review_kind="scheduled", window_start=None,
                            scope="window", **k):
            calls.append({
                "manifest": list(manifest), "kind": review_kind,
                "scope": scope, "window_start": window_start,
                "redispatch_of": k.get("redispatch_of"),
            })
            return outcomes.pop(0)

        runner.run_code_review = run_code_review
        runner.calls = calls
        return runner

    def test_zero_rows_redispatch_exactly_once_then_escalates(self):
        runner = self._scripted_runner([
            self._result("code-review-100", face=self._face("code-review-100")),
            self._result("code-review-101", face=self._face("code-review-101")),
        ])
        mon = self._monitor(runner)
        res = self._checkpoint(mon)
        self.assertTrue(res.get("triggered"))
        self.assertEqual(len(runner.calls), 2, "零产物自动重派恰 1 次")
        # 重派以原 manifest/参数复调（幂等保障既有）
        self.assertEqual(runner.calls[1]["manifest"], runner.calls[0]["manifest"])
        self.assertEqual(runner.calls[1]["kind"], runner.calls[0]["kind"])
        # 重派事件留痕：重派 run 自身 jsonl 追加 empty_product_redispatch 标注
        rl = self.repo / ".fenix" / "runs" / "code-review-101.jsonl"
        self.assertTrue(rl.exists(), "重派事件应落 run jsonl")
        lines = [json.loads(x) for x in rl.read_text(encoding="utf-8").splitlines()
                 if x.strip()]
        self.assertTrue(any(
            e.get("type") == "empty_product_redispatch"
            and e.get("redispatch_of") == "code-review-100"
            for e in lines), lines)
        # 升级信号：单条 ESCALATION，携带失败面摘要（run id/manifest 计数/变体）
        esc = [a for a in self._alerts(mon)
               if a.get("signal_type") == "code_review_empty_product"]
        self.assertEqual(len(esc), 1, esc)
        self.assertEqual(esc[0].get("kind"), "escalation")
        self.assertIn("code-review-101", esc[0]["description"])
        self.assertIn("zero_valid_rows", esc[0]["description"])
        self.assertIn("manifest_count=2", esc[0]["evidence"])
        # 升级记录同时点名重派链头（验证修复 BUG-03）：告警对账按首派 run id
        # 检索记录，只带重派 run id 会使升级信号与触发链对不上号。
        self.assertIn("code-review-100", esc[0]["description"],
                      "升级记录须携带链头（原 run）id")
        self.assertIn("redispatch_of=code-review-100", esc[0]["evidence"])
        # 升级后停止：标记置位 + 链登记齐全 + 配额恰耗 1
        self.assertTrue(mon._code_review_redispatch_escalated)
        self.assertEqual(mon._code_review_empty_redispatches, 1)
        self.assertIn("code-review-100", mon._code_review_redispatched_runs)
        self.assertIn("code-review-101", mon._code_review_redispatched_runs)
        # 升级后再来的硬门拦截不再重派（两通道均停）
        mon._handle_code_review_empty_product(
            manifest=["core/a.py"], review_kind="scheduled", window_start=None,
            scope="window", fail_face=self._face("code-review-999"))
        self.assertEqual(len(runner.calls), 2, "升级后两通道均不再自动重派")

    def test_chain_already_redispatched_escalates_without_new_run(self):
        """同一 run 链已被重派 → 再次硬门拦截只升级不再重派（双通道互不叠加）。"""
        runner = self._scripted_runner([])
        mon = self._monitor(runner)
        mon._code_review_redispatched_runs.add("code-review-200")
        mon._handle_code_review_empty_product(
            manifest=["core/a.py"], review_kind="scheduled", window_start=None,
            scope="window", fail_face=self._face("code-review-200"))
        self.assertEqual(runner.calls, [], "已被重派的链 MUST NOT 再次重派")
        esc = [a for a in self._alerts(mon)
               if a.get("signal_type") == "code_review_empty_product"]
        self.assertEqual(len(esc), 1)
        self.assertIn("code-review-200", esc[0]["description"])
        self.assertTrue(mon._code_review_redispatch_escalated)
        self.assertEqual(mon._code_review_empty_redispatches, 0, "升级路径不占重派配额")

    def test_lifetime_quota_exhausted_no_new_run_no_escalation(self):
        """生命周期合计配额耗尽（另一条链已用）→ 记日志收场，不重派不升级。"""
        runner = self._scripted_runner([])
        mon = self._monitor(runner)
        mon._code_review_empty_redispatches = 1
        mon._handle_code_review_empty_product(
            manifest=["core/a.py"], review_kind="scheduled", window_start=None,
            scope="window", fail_face=self._face("code-review-300"))
        self.assertEqual(runner.calls, [])
        self.assertEqual(
            [a for a in self._alerts(mon)
             if a.get("signal_type") == "code_review_empty_product"],
            [], "配额耗尽不是升级条件（升级条件是重派仍零有效行）")
        self.assertFalse(mon._code_review_redispatch_escalated)

    def test_escalated_flag_blocks_both_channels(self):
        """升级信号发出后两通道均不再自动重派（design 双通道配额约束第三条）。"""
        import time
        from unittest.mock import patch

        runner = self._scripted_runner([])
        mon = self._monitor(runner)
        mon._code_review_redispatch_escalated = True
        with patch("threading.Timer") as fake_timer:
            mon._schedule_ratelimit_redispatch(
                manifest=["core/a.py"], review_kind="scheduled",
                window_start=None, scope="window",
                intent={"run_id": "code-review-400",
                        "cooldown_until_epoch": time.time() + 300})
            fake_timer.assert_not_called()
        self.assertEqual(mon._code_review_ratelimit_redispatches, 0,
                         "升级后 429 通道不占配额")
        mon._handle_code_review_empty_product(
            manifest=["core/a.py"], review_kind="scheduled", window_start=None,
            scope="window", fail_face=self._face("code-review-401"))
        self.assertEqual(runner.calls, [], "升级后零产物通道不再重派")

    def test_429_channel_registers_chain_and_empty_channel_defers(self):
        """429 通道登记 run 链 → 同一链再遭硬门拦截只升级不再重派。"""
        import time
        from unittest.mock import patch

        runner = self._scripted_runner([])
        mon = self._monitor(runner)
        with patch("threading.Timer"):
            mon._schedule_ratelimit_redispatch(
                manifest=["core/a.py"], review_kind="scheduled",
                window_start=None, scope="window",
                intent={"run_id": "code-review-500",
                        "cooldown_until_epoch": time.time() + 300})
        self.assertIn("code-review-500", mon._code_review_redispatched_runs)
        self.assertEqual(mon._code_review_ratelimit_redispatches, 1,
                         "429 通道独立限次照常占用")
        mon._handle_code_review_empty_product(
            manifest=["core/a.py"], review_kind="scheduled", window_start=None,
            scope="window", fail_face=self._face("code-review-500"))
        self.assertEqual(runner.calls, [], "同一 run 链零产物通道不得叠加调度")
        esc = [a for a in self._alerts(mon)
               if a.get("signal_type") == "code_review_empty_product"]
        self.assertEqual(len(esc), 1)
        self.assertTrue(mon._code_review_redispatch_escalated)


class TestEmptyProductPromptAndEscalationFace(_EmptyFaceMixins, unittest.TestCase):
    """提示词自救指引契约与升级告警失败面字段（task 2.1/3.2，1.2 消费侧）。"""

    def setUp(self):
        self.repo = Path(_mkdtemp("cr-prompt-esc-"))
        (self.repo / ".fenix").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        import shutil

        shutil.rmtree(str(self.repo), ignore_errors=True)

    def _monitor(self):
        from core.admin_monitor import AdminMonitor

        return AdminMonitor(
            {"admin": {"code_review": {"enabled": True}}},
            None, str(self.repo), _MonitorFakeLogger(),
            agent_runner=None, code_review_executor=None,
        )

    def test_prompt_carries_self_rescue_discipline(self):
        """Scenario: 构造周期审查提示词 → 含自救指引（纪律三要素）。"""
        from core.agent_runner.prompt_builder import PromptBuilder

        pm = type("P", (), {
            "project_root": Path(_mkdtemp("cr-prompt-build-")), "config": {},
        })()
        builder = PromptBuilder(pm)
        prompt = builder._build_code_review_prompt(
            "code-review-1",
            {
                "manifest": ["core/a.py"],
                "review_window": "（全仓）",
                "out_path": "/tmp/x.jsonl",
            },
        )
        # ① ToolSearch 对基础工具回 No matches 属按设计，直接调用
        self.assertIn("No matches", prompt)
        self.assertIn("按设计", prompt)
        self.assertIn("直接调用", prompt)
        # ② select: 精确名探测
        self.assertIn("select:", prompt)
        # ③ TOOLFACE-MISSING fail-fast
        self.assertIn("TOOLFACE-MISSING", prompt)
        # 禁止凭「检索不到」推断工具缺失并放弃审查
        self.assertIn("检索不到", prompt)

    def test_escalation_alert_carries_failure_face_fields(self):
        """升级告警携带失败面摘要字段（run id/manifest 计数/变体/工具面）。"""
        mon = self._monitor()
        mon._escalate_code_review_empty_product({
            "run_id": "code-review-900",
            "manifest_count": 7,
            "variant": "artifact_missing",
            "shards": 0,
            "sources_present": 0,
            "unreadable": [],
            "toolface": {"declared": False, "tools": [],
                         "probe": "toolface-unrestricted"},
        })
        esc = [a for a in self._alerts(mon)
               if a.get("signal_type") == "code_review_empty_product"]
        self.assertEqual(len(esc), 1)
        self.assertEqual(esc[0].get("kind"), "escalation")
        self.assertIn("code-review-900", esc[0]["description"])
        self.assertIn("artifact_missing", esc[0]["description"])
        self.assertIn("manifest_count=7", esc[0]["evidence"])
        self.assertIn("toolface-unrestricted", esc[0]["evidence"])
        # 发出即封停两通道自动重派（去重命中与否不影响标记）
        self.assertTrue(mon._code_review_redispatch_escalated)
        # 同 run 二次调用去重（单 run 至多一条），标记保持
        mon._escalate_code_review_empty_product({
            "run_id": "code-review-900", "manifest_count": 7,
            "variant": "artifact_missing", "shards": 0,
            "sources_present": 0, "unreadable": [],
        })
        self.assertEqual(
            len([a for a in self._alerts(mon)
                 if a.get("signal_type") == "code_review_empty_product"]), 1)


class TestTerminalSalvageAndToolfaceTrace(unittest.TestCase):
    """终局消息结论行抢救红线（task 5.1/3.3）与工具面预检/留痕（task 4.1/6.1/3.3）。"""

    def setUp(self):
        self.proot = Path(_mkdtemp("cr-salvage2-"))
        self.crdir = self.proot / ".fenix" / "code-review"
        self.crdir.mkdir(parents=True)
        (self.proot / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
        self.run_id = "code-review-1790205000"

    def tearDown(self):
        import shutil

        shutil.rmtree(str(self.proot), ignore_errors=True)

    def _fake_runner(self):
        from core.agent_runner import maintenance_runs as mr

        runner = type("R", (), {})()
        runner.project_root = self.proot
        runner.logger = None
        runner._unique_code_review_run_id = lambda: self.run_id
        runner._build_prompt = lambda *a, **k: "PROMPT"
        runner._get_agent_model_assignment = lambda name: None
        runner._get_admin_model = lambda: "test-model"
        runner._extract_usage_info = lambda x: {}
        runner._accumulate_code_review_tokens = lambda run_id, usage: None
        runner._read_code_review_out = lambda project_root, rid: mr._read_code_review_out(
            runner, project_root, rid
        )
        return runner

    def _seed_terminal_message(self, text):
        rl = self.proot / ".fenix" / "runs" / f"{self.run_id}.jsonl"
        rl.write_text(
            json.dumps({"type": "result", "subtype": "error_max_turns",
                        "result": text}, ensure_ascii=False) + "\n",
            encoding="utf-8")

    def test_error_run_salvages_trace_without_result_text(self):
        """result 事件无 result 文本时回退末轮 assistant 文本 + 原文留痕（BUG-04）。

        error 收场转录形态：agent 中途死亡（429），result 事件无终局摘要，
        结论内容（标记行）只在末轮 assistant 消息里——抢救 MUST 经 assistant
        回退取到原文并落第二留痕（.fenix/code-review/terminal-salvage-<rid>.txt
        或日志节选），转录本体之外可 rg 命中；红线不触发核销/code-fix 检查点。
        """
        from core.agent_runner import maintenance_runs as mr

        marker = "REVIEW-CONCLUSION-MARKER-9d27"
        rl = self.proot / ".fenix" / "runs" / f"{self.run_id}.jsonl"
        rl.write_text(
            json.dumps({"type": "assistant", "message": {"content": [
                {"type": "text",
                 "text": f"逐文件审查中途被限流打断。结论：{marker} "
                         f"已审 1/2 文件，core/a.py 无缺陷"}]}}) + "\n"
            + json.dumps({"type": "result", "subtype": "error_during_execution",
                          "is_error": True}) + "\n",
            encoding="utf-8")
        checkpoint_calls = []
        runner = self._fake_runner()
        runner._code_fix_orchestrator = type(
            "O", (), {"checkpoint": staticmethod(
                lambda: checkpoint_calls.append(1))})()

        def _boom(*a, **k):
            raise RuntimeError("API Error: Request rejected (429)")

        runner._run_agent = _boom
        result = mr.run_code_review(runner, ["core/a.py"], "manual_full",
                                    window_start=None, scope="full")
        self.assertFalse(result.success)
        # 抢救留痕：原文文件落盘且含标记（转录本体之外）
        trace = self.crdir / f"terminal-salvage-{self.run_id}.txt"
        self.assertTrue(trace.exists(), "终局消息原文应留痕 terminal-salvage-<rid>.txt")
        self.assertIn(marker, trace.read_text(encoding="utf-8"))
        # 红线：MUST NOT 激活 code-fix 检查点
        self.assertEqual(checkpoint_calls, [],
                         "error 收场抢救不激活 code-fix 检查点")
        # 预置台账 open 条目不被误核销（无产物行 → 无 upsert → 无 resolved）
        ledger = self.crdir / "items.jsonl"
        if ledger.exists():
            rows = [json.loads(x) for x in
                    ledger.read_text(encoding="utf-8").splitlines() if x.strip()]
            self.assertFalse(
                [r for r in rows if r.get("status") == "resolved"
                 or r.get("resolved_at")],
                "error 收场 MUST NOT 触发全仓快照核销")

    def test_terminal_message_falls_back_to_last_assistant_text(self):
        """_read_terminal_message：result 文本缺失 → 回退末个 assistant 文本块。"""
        from core.agent_runner.maintenance_runs import _read_terminal_message

        marker = "ASSISTANT-FALLBACK-MARKER-4f10"
        rl = self.proot / ".fenix" / "runs" / f"{self.run_id}.jsonl"
        rl.write_text(
            json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "t1"},
                {"type": "text", "text": f"结论：{marker} 审查中断"}]}}) + "\n"
            + json.dumps({"type": "result", "subtype": "error_during_execution",
                          "is_error": True}) + "\n",
            encoding="utf-8")
        self.assertIn(marker, _read_terminal_message(self.proot, self.run_id))
        # result 事件带文本时仍以 result 文本为准（不回退）
        rl.write_text(
            json.dumps({"type": "assistant", "message": {"content": [
                {"type": "text", "text": f"结论：{marker} 审查中断"}]}}) + "\n"
            + json.dumps({"type": "result", "subtype": "success",
                          "result": "最终结论行文本"}) + "\n",
            encoding="utf-8")
        self.assertEqual(
            _read_terminal_message(self.proot, self.run_id), "最终结论行文本")
        # 文件缺失 → 空串（不伪造）
        self.assertEqual(
            _read_terminal_message(self.proot, "code-review-missing"), "")

    def test_error_run_salvages_terminal_conclusion_rows(self):
        """error 收场且终局消息携带结论行 → 结论行被抢救落账。"""
        from core.agent_runner import maintenance_runs as mr

        row = {"file": "core/a.py", "findings": [
            {"line": 2, "severity": "major", "category": "correctness",
             "title": "终局消息抢救发现。", "description": "d",
             "suggestion": "s", "evidence": "core/a.py:2"},
        ]}
        self._seed_terminal_message(
            "1 files reviewed\n" + json.dumps(row, ensure_ascii=False))
        checkpoint_calls = []
        runner = self._fake_runner()
        runner._code_fix_orchestrator = type(
            "O", (), {"checkpoint": staticmethod(
                lambda: checkpoint_calls.append(1))})()

        def _boom(*a, **k):
            raise RuntimeError("API Error: 429 · [1302] rate limit")

        runner._run_agent = _boom
        result = mr.run_code_review(runner, ["core/a.py"], "manual_window")
        self.assertFalse(result.success)
        self.assertEqual(result.inserted, 1, "终局消息结论行被抢救落账")
        # 抢救行补写进主产物（既有聚合读侧 upsert 消费）
        out = self.crdir / f"out-{self.run_id}.jsonl"
        rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()
                if x.strip()]
        self.assertEqual(rows[0]["file"], "core/a.py")
        # 红线：MUST NOT 触发 code-fix 检查点、MUST NOT 触发全仓快照核销
        self.assertEqual(checkpoint_calls, [], "error 收场抢救不激活 code-fix 检查点")
        self.assertEqual(result.resolved, 0, "error 收场抢救不做全仓快照核销")

    def test_gate_intercept_attaches_fail_face_with_toolface(self):
        """零有效行拦截 → 结果信封携带失败面摘要（含工具面预检，1.2 消费侧）。"""
        from core.agent_runner import maintenance_runs as mr

        runner = self._fake_runner()
        runner._run_toolface = {
            self.run_id: {"declared": False, "tools": [],
                          "probe": "toolface-unrestricted"}}
        runner._run_agent = lambda *a, **k: (
            "output", 1, "sid", {}, {"rounds": 0, "stalls": 0, "max": None})
        result = mr.run_code_review(runner, ["core/a.py", "core/b.py"], "scheduled")
        self.assertFalse(result.success, "零有效行整轮判失败（硬门既有口径）")
        self.assertIsNotNone(result.fail_face)
        self.assertEqual(result.fail_face["run_id"], self.run_id)
        self.assertEqual(result.fail_face["manifest_count"], 2)
        self.assertEqual(result.fail_face["variant"], "artifact_missing")
        self.assertEqual(result.fail_face["toolface"]["probe"],
                         "toolface-unrestricted")

    def test_toolface_probe_variants_and_registry(self):
        """spawn 工具面预检三态 + 登记键归一化（4.1）。"""
        from core.agent_runner.runner import AgentRunner

        runner = AgentRunner.__new__(AgentRunner)
        logger = type("L", (), {})()
        logger.infos = []
        logger.warnings = []
        logger.info = lambda *a, **k: logger.infos.append(a)
        logger.warning = lambda *a, **k: logger.warnings.append(a)
        runner.logger = logger
        # ① 无显式 allowedTools → unrestricted（现状默认）
        entry = runner._probe_spawn_toolface(
            "run-tf-1", ["claude", "-p", "--output-format", "stream-json"])
        self.assertEqual(entry["probe"], "toolface-unrestricted")
        self.assertFalse(entry["declared"])
        self.assertIn("run-tf-1", runner._run_toolface)
        # ② 显式白名单排除全部基础工具 → missing-basic-tools + WARNING
        entry = runner._probe_spawn_toolface(
            "run-tf-2-a1", ["claude", "-p", "--allowedTools", "TaskSearch,WebFetch"])
        self.assertEqual(entry["probe"], "toolface-missing-basic-tools")
        self.assertEqual(entry["tools"], ["TaskSearch", "WebFetch"])
        self.assertTrue(any("工具面预检" in str(w) for w in logger.warnings),
                        logger.warnings)
        # 登记键归一化（-a1 attempt 后缀剥离）
        self.assertIn("run-tf-2", runner._run_toolface)
        self.assertNotIn("run-tf-2-a1", runner._run_toolface)
        # ③ 显式白名单覆盖基础工具（空白分隔形态）→ declared
        entry = runner._probe_spawn_toolface(
            "run-tf-3", ["claude", "-p", "--allowedTools", "Bash Read"])
        self.assertEqual(entry["probe"], "toolface-declared")
        self.assertEqual(entry["tools"], ["Bash", "Read"])

    def _metric_runner(self):
        from core.agent_runner.runner import AgentRunner

        runner = AgentRunner.__new__(AgentRunner)
        logger = type("L", (), {})()
        logger.contexts = []
        logger.infos = []
        logger.info = lambda c, m, ctx=None, **k: (
            logger.infos.append((c, m)), (
                logger.contexts.append(ctx)
                if isinstance(ctx, dict) and ctx.get("metric_type") == "run_metrics"
                else None))[1]
        logger.warning = lambda *a, **k: None
        runner.logger = logger
        return runner, logger

    def test_run_metrics_carries_toolface_fields_and_consumes_registry(self):
        """run_metrics 收尾携带工具面字段；登记消费即摘除（6.1/4.1）。"""
        runner, logger = self._metric_runner()
        runner._probe_spawn_toolface("run-m1", ["claude", "-p"])
        runner._log_run_metrics(
            run_id="run-m1", spec_name="code-review", agent_type="code-review",
            duration_seconds=1.0, turns=1, usage_info={}, terminal="error",
            provider=None, toolface={"missing": True})
        self.assertEqual(len(logger.contexts), 1)
        ctx = logger.contexts[0]
        self.assertEqual(ctx["toolface_probe"], "toolface-unrestricted")
        self.assertFalse(ctx["toolface_declared"])
        self.assertTrue(ctx["toolface_missing"], "TOOLFACE-MISSING 分类随行留痕")
        self.assertNotIn("run-m1", runner._run_toolface, "登记消费即摘除")

    def test_run_metrics_without_toolface_unobserved_placeholders(self):
        """无预检登记且未传参（提前终态路径）→ 工具面键恒落、未观测占位。

        （验证修复 BUG-05 改约：省略键使「预检未跑」与「预检通过」在指标行
        上不可区分——四键恒落，未观测 None/[] 占位，事后取证零盲区。）
        """
        runner, logger = self._metric_runner()
        runner._log_run_metrics(
            run_id="run-m2", spec_name="spec-x", agent_type="implementer",
            duration_seconds=0.0, turns=0, usage_info={}, terminal="cancelled",
            provider=None)
        self.assertEqual(len(logger.contexts), 1)
        ctx = logger.contexts[0]
        self.assertIsNone(ctx["toolface_probe"], "未观测以 None 占位，不省略键")
        self.assertIsNone(ctx["toolface_declared"])
        self.assertIsNone(ctx["toolface_tools"])
        self.assertIsNone(ctx["toolface_missing"])

    def test_run_metrics_minimal_standin_still_writes_row(self):
        """最小替身（无 _normalize_run_id/无 _run_toolface）→ 行照常落盘。

        （验证修复 BUG-05 回归钉：此前 self._normalize_run_id 裸访问在最小
        替身上 AttributeError → except 吞成一条 warning，metric 行整体丢失，
        run_metrics 收尾行未落盘。登记缺失只意味无预检数据，MUST NOT 击穿
        指标落盘。形态对齐验证场景：直接以最小 self 调用未绑定方法。）
        """
        captured = []

        class _CapLogger:
            def info(self, component, message, context=None):
                captured.append((component, str(message), context))

            def warning(self, component, message, context=None):
                captured.append((component, str(message), None))

            error = warning

        class _FakeSelf:
            logger = _CapLogger()
            _run_harness = {}

        from core.agent_runner.runner import AgentRunner

        fs = _FakeSelf()
        AgentRunner._log_run_metrics(
            fs,
            run_id="code-review-17960001",
            spec_name="code-review",
            agent_type="code-review",
            duration_seconds=0.1,
            turns=2,
            usage_info={},
            terminal="error",
            provider=None,
        )
        rows = [ctx for _c, _m, ctx in captured
                if isinstance(ctx, dict)
                and ctx.get("metric_type") == "run_metrics"]
        self.assertEqual(len(rows), 1, "指标行 MUST NOT 被替身缺名击穿")
        ctx = rows[0]
        self.assertEqual(ctx["run_id"], "code-review-17960001")
        self.assertEqual(ctx["terminal"], "error")
        self.assertEqual(ctx["agent_type"], "code-review")
        tool_keys = [k for k in ctx if ("tool" in k.lower()
                                        or "precheck" in k.lower()
                                        or "face" in k.lower())]
        self.assertTrue(tool_keys, f"收尾行应携带工具面字段，实际键 {sorted(ctx)}")

    def test_lane_toolface_missing_classification_from_terminal_text(self):
        """TOOLFACE-MISSING 分类从终态文本补出，随车道收尾指标行转发（6.1）。"""
        from core.agent_runner import maintenance_runs as mr

        runner = self._fake_runner()
        metric_calls = []
        runner._log_run_metrics = lambda **kw: metric_calls.append(kw)
        runner._run_harness = {}

        def _boom(*a, **k):
            raise RuntimeError("TOOLFACE-MISSING: Bash, Read（工具面缺失，按纪律 fail-fast）")

        runner._run_agent = _boom
        mr.run_code_review(runner, ["core/a.py"], "manual_window")
        self.assertEqual(len(metric_calls), 1)
        self.assertTrue(metric_calls[0]["toolface"]["missing"],
                        "终态文本含 TOOLFACE-MISSING → 分类 True")
