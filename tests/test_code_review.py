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
        from core.code_review import read_items, resolve_snapshot

        a_fp = self._fp_of("correctness", "A issue")
        n = resolve_snapshot(self.repo, {a_fp})
        self.assertEqual(n, 1)
        items = read_items(self.repo)
        statuses = {it["status"] for it in items.values()}
        self.assertIn("resolved", statuses)
        self.assertIn("open", statuses)
        # resolved 的条目是 b（未再观测）
        resolved = [it for it in items.values() if it["status"] == "resolved"]
        self.assertEqual(resolved[0]["file"], "core/b.py")
        self.assertTrue(resolved[0].get("resolved_at"))

    def test_does_not_touch_in_spec_ignored(self):
        from core.code_review import read_items, resolve_snapshot

        items = read_items(self.repo)
        # 把 a 置 in_spec、b 置 ignored（直接写记录模拟既有状态）
        for it in items.values():
            it["status"] = "in_spec" if it["file"] == "core/a.py" else "ignored"
        from core.code_review import write_items

        write_items(self.repo, items.values())
        n = resolve_snapshot(self.repo, set())
        self.assertEqual(n, 0)
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
            now = datetime.now()
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
            {"file": "core/a.py", "category": "unused-import", "title": "Unused import os",
             "severity": "minor", "description": "d", "suggestion": "s", "evidence": "e", "line": 1},
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
             "severity": "minor", "line": 3,
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
        self.assertEqual(all_ids, ["1.1", "2.2"], all_ids)
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
            },
        )


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
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "more")

    def test_excludes_tests(self):
        from core.code_review import collect_manifest

        files = collect_manifest(self.repo, "full", None)
        self.assertNotIn("tests/test_x.py", files)
        self.assertNotIn("tests/fixtures/demo/f.py", files)
        self.assertTrue(all(not f.startswith("tests/") for f in files))

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
        # 分片 b1 落 a.py；主产物重复写 a.py + 新增 b.py → done=2 不是 3
        self._proot = self._mk(
            "code-review-1790182833",
            5,
            [{"file": "a.py"}, {"file": "b.py"}],
            {1: [{"file": "a.py"}]},
        )
        from core.code_review import read_progress

        p = read_progress(self._proot)
        self.assertEqual(p["done"], 2)


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
