"""add-knowledge-atlas 单测：validate_knowledge / dispatch_distill /
commit_archive_move 挂载 / DistillManager 执行器（fake spawn 三支路）。

运行：python3 -m pytest tests/test_knowledge.py -q
"""
import os
import json
import subprocess
import tempfile
import threading
import unittest
from datetime import date
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.knowledge import (
    KNOWLEDGE_DIR,
    DistillManager,
    parse_marker,
    validate_knowledge,
)

GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}

GOOD_PAGE = """# 定时拣选

<!-- knowledge: capability=scheduled-spec-pickup rev=1
     sources=spec/archive/{archive} -->

按周期把已完成 SPEC 拣选进归档。

## 规则

- 轮询间隔 300 秒。

## 溯源

- {today} {archive} — 新建本页
"""

GOOD_ADR = """# ADR-001：{title}

date: {today}
status: accepted

## Context

{body}

## Decision

{body}

## Consequences

{body}
"""

PREHISTORIC_PAGE = """# 史前基础能力

<!-- knowledge: capability=prehistoric-cap rev=1 origin=prehistoric
     sources=git:{ref}-..2026-09-02 -->

迁移期已存在的基础能力，现行规则如下。

## 规则

- 规则一句。

## 溯源

- 2026-09-02 史前复原（git:{ref}-..2026-09-02） — 迁移期已存在的基础规则
"""


class KnowledgeTestBase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        (self.root / "spec" / "archive" / self._archive_name()).mkdir(parents=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _archive_name(self):
        return f"{date.today().isoformat()}-demo-spec"

    def _write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def _git(self, *args):
        r = subprocess.run(
            ["git", "-C", str(self.root), *args],
            env=GIT_ENV, capture_output=True, text=True, timeout=60,
        )
        return r


class TestParseMarker(unittest.TestCase):
    def test_two_line_marker(self):
        text = (
            "# 定时拣选\n"
            "<!-- knowledge: capability=scheduled-spec-pickup rev=3\n"
            "     sources=spec/archive/a,spec/archive/b -->\n"
        )
        m = parse_marker(text)
        self.assertEqual(m["capability"], "scheduled-spec-pickup")
        self.assertEqual(m["rev"], 3)
        self.assertEqual(m["sources"], ["spec/archive/a", "spec/archive/b"])
        self.assertIsNone(m["part"])

    def test_part_field(self):
        m = parse_marker("<!-- knowledge: capability=x rev=1 part=2 sources=spec/archive/a -->")
        self.assertEqual(m["part"], "2")

    def test_origin_default_archive(self):
        m = parse_marker("<!-- knowledge: capability=x rev=1 sources=spec/archive/a -->")
        self.assertEqual(m["origin"], "archive")

    def test_origin_prehistoric(self):
        m = parse_marker(
            "<!-- knowledge: capability=x rev=1 origin=prehistoric"
            " sources=git:44e1443ba-..2026-09-02 -->"
        )
        self.assertEqual(m["origin"], "prehistoric")
        self.assertEqual(m["sources"], ["git:44e1443ba-..2026-09-02"])

    def test_invalid_returns_none(self):
        self.assertIsNone(parse_marker("no marker"))
        self.assertIsNone(parse_marker("<!-- knowledge: capability=X rev=1 sources=a -->"))
        self.assertIsNone(parse_marker("<!-- knowledge: capability=x rev=abc sources=a -->"))
        self.assertIsNone(parse_marker("<!-- knowledge: capability=x rev=0 sources=a -->"))
        self.assertIsNone(parse_marker("<!-- knowledge: capability=x rev=1 sources= -->"))


class TestValidateKnowledge(KnowledgeTestBase):
    def _good_page(self):
        archive = self._archive_name()
        self._write(
            f"{KNOWLEDGE_DIR}/domains/pickup/scheduled-spec-pickup.md",
            GOOD_PAGE.format(archive=archive, today=date.today().isoformat()),
        )

    def test_valid_minimal_dir_passes(self):
        self._good_page()
        self.assertEqual(validate_knowledge(self.root), [])

    def test_uninitialized_dir_passes(self):
        # 只有 README（首跑前）→ 不违规
        self._write(f"{KNOWLEDGE_DIR}/README.md", "# 契约\n")
        self.assertEqual(validate_knowledge(self.root), [])

    def test_missing_marker(self):
        self._write(f"{KNOWLEDGE_DIR}/domains/d/x.md", "# X\n\n内容\n")
        v = validate_knowledge(self.root)
        self.assertTrue(any("marker" in x for x in v))

    def test_marker_not_after_h1(self):
        self._write(
            f"{KNOWLEDGE_DIR}/domains/d/x.md",
            "前言\n\n\n\n\n\n# X\n<!-- knowledge: capability=x rev=1 sources=spec/archive/a -->\n",
        )
        v = validate_knowledge(self.root)
        self.assertTrue(any("紧随" in x for x in v))

    def test_dangling_source(self):
        self._write(
            f"{KNOWLEDGE_DIR}/domains/d/x.md",
            GOOD_PAGE.format(archive="1999-01-01-gone", today=date.today().isoformat()),
        )
        v = validate_knowledge(self.root)
        self.assertTrue(any("不存在的归档目录" in x for x in v))

    def test_over_150_lines(self):
        body = "\n".join(f"规则行 {i}" for i in range(160))
        self._write(
            f"{KNOWLEDGE_DIR}/domains/d/x.md",
            GOOD_PAGE.format(archive=self._archive_name(), today=date.today().isoformat())
            + body,
        )
        v = validate_knowledge(self.root)
        self.assertTrue(any("150" in x for x in v))

    def test_index_dangling_link(self):
        self._good_page()
        self._write(f"{KNOWLEDGE_DIR}/index.md", "# 总目录\n- [缺页](domains/pickup/missing.md)\n")
        v = validate_knowledge(self.root)
        self.assertTrue(any("链接目标不存在" in x for x in v))

    def test_index_outbound_link(self):
        self._good_page()
        self._write(f"{KNOWLEDGE_DIR}/index.md", "# 总目录\n- [越界](../../spec/archive/x.md)\n")
        v = validate_knowledge(self.root)
        self.assertTrue(any("越出真相源" in x for x in v))

    def test_non_kebab_domain(self):
        self._write(
            f"{KNOWLEDGE_DIR}/domains/Bad_Domain/x.md",
            GOOD_PAGE.format(archive=self._archive_name(), today=date.today().isoformat()),
        )
        v = validate_knowledge(self.root)
        self.assertTrue(any("kebab" in x for x in v))

    # ── origin 分支（fix-knowledge-backfill-reconstruction 任务 2.2） ──
    def _init_git_with_commit(self) -> str:
        # git 不跟踪空目录：先落一个文件保证首提交真实存在（ref 可解析）
        self._write("README.md", "# t\n")
        self._git("init", "-q")
        self._git("config", "user.name", "t")
        self._git("config", "user.email", "t@t")
        self._git("add", "--", ".")
        self._git("commit", "-q", "-m", "init")
        return self._git("rev-parse", "HEAD").stdout.strip()[:9]

    def test_prehistoric_page_valid_passes(self):
        ref = self._init_git_with_commit()
        self._write(
            f"{KNOWLEDGE_DIR}/domains/base/prehistoric-cap.md",
            PREHISTORIC_PAGE.format(ref=ref),
        )
        # 不要求归档目录存在（sources 是 git 锚点而非归档路径）
        self.assertEqual(validate_knowledge(self.root), [])

    def test_prehistoric_bad_anchor_format(self):
        self._init_git_with_commit()
        self._write(
            f"{KNOWLEDGE_DIR}/domains/base/prehistoric-cap.md",
            PREHISTORIC_PAGE.format(ref="HEAD"),  # 非 sha 短 ref → 格式非法
        )
        v = validate_knowledge(self.root)
        self.assertTrue(any("锚点格式非法" in x for x in v))

    def test_prehistoric_unresolvable_ref(self):
        self._init_git_with_commit()
        self._write(
            f"{KNOWLEDGE_DIR}/domains/base/prehistoric-cap.md",
            PREHISTORIC_PAGE.format(ref="deadbeef"),  # 格式合法但对象不存在
        )
        v = validate_knowledge(self.root)
        self.assertTrue(any("不可解析" in x for x in v))

    def test_prehistoric_archive_path_source_rejected(self):
        self._init_git_with_commit()
        text = PREHISTORIC_PAGE.format(ref="44e1443ba").replace(
            "sources=git:44e1443ba-..2026-09-02", "sources=spec/archive/whatever"
        )
        self._write(f"{KNOWLEDGE_DIR}/domains/base/prehistoric-cap.md", text)
        v = validate_knowledge(self.root)
        # git: 前缀强制分流：prehistoric 页不放行归档路径 sources
        self.assertTrue(any("锚点格式非法" in x for x in v))

    def test_invalid_origin_value_rejected(self):
        self._init_git_with_commit()
        text = GOOD_PAGE.format(
            archive=self._archive_name(), today=date.today().isoformat()
        ).replace("rev=1", "rev=1 origin=weird")
        self._write(f"{KNOWLEDGE_DIR}/domains/d/x.md", text)
        v = validate_knowledge(self.root)
        self.assertTrue(any("origin 非法" in x for x in v))

    def test_archive_page_origin_regression_zero(self):
        """archive 页（缺省 origin）行为零回归：归档缺失照旧报违规。"""
        self._write(
            f"{KNOWLEDGE_DIR}/domains/d/x.md",
            GOOD_PAGE.format(archive="1999-01-01-gone", today=date.today().isoformat()),
        )
        v = validate_knowledge(self.root)
        self.assertTrue(any("不存在的归档目录" in x for x in v))

    # ── ADR ──────────────────────────────────────────────────────────
    def _commit_all(self):
        self._git("init", "-q")
        self._git("config", "user.name", "t")
        self._git("config", "user.email", "t@t")
        self._git("add", "--", ".")
        self._git("commit", "-q", "-m", "init")

    def test_valid_adr_passes(self):
        today = date.today().isoformat()
        self._write(
            f"{KNOWLEDGE_DIR}/adr/ADR-001-spawn-injection.md",
            GOOD_ADR.format(title="spawn 注入", today=today, body="正文"),
        )
        self._write(f"{KNOWLEDGE_DIR}/adr/index.md", "- [ADR-001](ADR-001-spawn-injection.md) accepted\n")
        self.assertEqual(validate_knowledge(self.root), [])

    def test_adr_missing_status(self):
        self._write(f"{KNOWLEDGE_DIR}/adr/ADR-001-x.md", "# ADR-001：x\n\n## Context\nb\n")
        v = validate_knowledge(self.root)
        self.assertTrue(any("status" in x for x in v))

    def test_adr_bad_filename(self):
        today = date.today().isoformat()
        self._write(f"{KNOWLEDGE_DIR}/adr/decision.md", GOOD_ADR.format(title="t", today=today, body="b"))
        v = validate_knowledge(self.root)
        self.assertTrue(any("ADR-NNN" in x for x in v))

    def test_adr_superseded_without_link(self):
        today = date.today().isoformat()
        text = GOOD_ADR.format(title="t", today=today, body="b").replace(
            "status: accepted", "status: superseded"
        )
        self._write(f"{KNOWLEDGE_DIR}/adr/ADR-001-x.md", text)
        v = validate_knowledge(self.root)
        self.assertTrue(any("Superseded by" in x for x in v))

    def test_adr_superseded_dangling_target(self):
        today = date.today().isoformat()
        text = (
            GOOD_ADR.format(title="t", today=today, body="b")
            .replace("status: accepted", "status: superseded\nSuperseded by: ADR-009(新)")
        )
        self._write(f"{KNOWLEDGE_DIR}/adr/ADR-001-x.md", text)
        v = validate_knowledge(self.root)
        self.assertTrue(any("不存在条目" in x for x in v))

    def test_adr_body_immutable_after_commit(self):
        today = date.today().isoformat()
        path = self._write(
            f"{KNOWLEDGE_DIR}/adr/ADR-001-x.md",
            GOOD_ADR.format(title="t", today=today, body="原始正文"),
        )
        self._commit_all()
        # ADR-002 存在（supersede 指向目标须可解析）
        self._write(
            f"{KNOWLEDGE_DIR}/adr/ADR-002-y.md",
            GOOD_ADR.format(title="y", today=today, body="y 正文"),
        )
        # 只改头部 status（supersede 允许的两处标记之一）→ 不违规
        path.write_text(
            GOOD_ADR.format(title="t", today=today, body="原始正文").replace(
                "status: accepted", "status: superseded\nSuperseded by: ADR-002(y)"
            ),
            encoding="utf-8",
        )
        self.assertEqual(validate_knowledge(self.root), [])
        # 改写三段正文 → 违规
        path.write_text(
            GOOD_ADR.format(title="t", today=today, body="被篡改的正文"),
            encoding="utf-8",
        )
        v = validate_knowledge(self.root)
        self.assertTrue(any("不可变" in x for x in v))


class TestDispatchDistill(KnowledgeTestBase):
    def _cfg(self, enabled=True):
        return {"knowledge": {"enabled": enabled}}

    def test_pytest_guard_without_dispatcher(self):
        from core.knowledge import dispatch_distill

        r = dispatch_distill(self.root, self._archive_name(), self._cfg())
        self.assertFalse(r["dispatched"])
        self.assertEqual(r["reason"], "test-environment")

    def test_disabled_config_skips(self):
        from core.knowledge import dispatch_distill

        calls = []
        r = dispatch_distill(
            self.root, self._archive_name(), self._cfg(False),
            dispatcher=lambda proot, names: calls.append(names),
        )
        self.assertFalse(r["dispatched"])
        self.assertEqual(r["reason"], "disabled")
        self.assertEqual(calls, [])

    def test_dispatched_to_injected_dispatcher(self):
        from core.knowledge import dispatch_distill

        got = {}

        class Fake:
            def dispatch(self, proot, names):
                got["proot"], got["names"] = proot, names
                return {"dispatched": True}

        r = dispatch_distill(self.root, self._archive_name(), self._cfg(), dispatcher=Fake())
        self.assertTrue(r["dispatched"])
        self.assertEqual(got["names"], [self._archive_name()])
        self.assertEqual(Path(got["proot"]).resolve(), self.root.resolve())

    def test_archive_dir_missing(self):
        from core.knowledge import dispatch_distill

        r = dispatch_distill(self.root, "1999-01-01-gone", self._cfg(), dispatcher=object())
        self.assertFalse(r["dispatched"])
        self.assertEqual(r["reason"], "archive-dir-missing")

    def test_dispatcher_raise_fail_open_and_todo(self):
        from core.knowledge import dispatch_distill

        class Boom:
            def dispatch(self, proot, names):
                raise RuntimeError("网关不可用")

        r = dispatch_distill(self.root, self._archive_name(), self._cfg(), dispatcher=Boom())
        self.assertFalse(r["dispatched"])
        self.assertIn("error", r["reason"])
        todo = (self.root / ".fenix" / "todo.md").read_text(encoding="utf-8")
        self.assertIn("knowledge-distill 重试", todo)
        self.assertIn(self._archive_name(), todo)

    def test_batch_empty_and_merge(self):
        from core.knowledge import dispatch_distill_batch

        self.assertFalse(dispatch_distill_batch(self.root, [], self._cfg())["dispatched"])
        (self.root / "spec" / "archive" / "2026-01-01-b").mkdir(parents=True, exist_ok=True)
        got = {}

        class Fake:
            def dispatch(self, proot, names):
                got["names"] = names

        r = dispatch_distill_batch(
            self.root, [self._archive_name(), "2026-01-01-b"], self._cfg(), dispatcher=Fake()
        )
        self.assertTrue(r["dispatched"])
        self.assertEqual(got["names"], [self._archive_name(), "2026-01-01-b"])


class TestBackfillQueueGate(KnowledgeTestBase):
    """任务 3.1：回填期排队双漏斗（dispatch_distill / dispatch_distill_batch）。

    台账存在 pending → 不派发增量 run、归档登记进台账（终态 capability 条目
    重置 pending）；台账缺失/收敛 → 即时派发零回归。
    """

    def _cfg(self):
        return {"knowledge": {"enabled": True}}

    def _seed_ledger(self, entries):
        (self.root / ".fenix").mkdir(exist_ok=True)
        text = "\n".join(json.dumps(e, ensure_ascii=False) for e in entries)
        (self.root / ".fenix" / "knowledge_backfill.jsonl").write_text(
            text + "\n", encoding="utf-8"
        )

    def _ledger_text(self):
        return (self.root / ".fenix" / "knowledge_backfill.jsonl").read_text(
            encoding="utf-8"
        )

    def _fake_dispatcher(self, calls):
        class Fake:
            def dispatch(self, proot, names):
                calls.append(list(names))

        return Fake()

    def _touch_archive_capability(self):
        cap_dir = (
            self.root / "spec" / "archive" / self._archive_name() / "specs" / "pickup"
        )
        cap_dir.mkdir(parents=True, exist_ok=True)

    def test_single_entry_queued_and_registered(self):
        from core.knowledge import dispatch_distill

        self._seed_ledger([{"name": "capability:other-cap", "status": "pending"}])
        self._touch_archive_capability()
        calls = []
        r = dispatch_distill(
            self.root, self._archive_name(), self._cfg(), dispatcher=self._fake_dispatcher(calls)
        )
        self.assertFalse(r["dispatched"])
        self.assertEqual(r["reason"], "backfill-queued")
        self.assertEqual(calls, [])  # 未派发增量 run
        ledger = self._ledger_text()
        # 双维度登记：adr 条目新建 + 触碰的 capability 条目新建
        self.assertIn(f'"name": "adr:{self._archive_name()}"', ledger)
        self.assertIn('"name": "capability:pickup"', ledger)
        self.assertEqual(ledger.count('"status": "pending"'), 3)

    def test_terminal_capability_reset_to_pending(self):
        from core.knowledge import dispatch_distill

        # 既有 pending 触发排队门；归档触碰的 capability:pickup 已终态
        self._seed_ledger(
            [
                {"name": "capability:pickup", "status": "distilled"},
                {"name": f"adr:{self._archive_name()}", "status": "distilled"},
                {"name": "capability:other-cap", "status": "pending"},
            ]
        )
        self._touch_archive_capability()
        calls = []
        dispatch_distill(
            self.root, self._archive_name(), self._cfg(), dispatcher=self._fake_dispatcher(calls)
        )
        # 终态条目重置 pending：链索引重扫纳入新归档 delta 后重新聚合
        ledger = self._ledger_text()
        self.assertEqual(ledger.count('"status": "pending"'), 2)
        self.assertEqual(calls, [])

    def test_batch_entry_queued_and_registered(self):
        from core.knowledge import dispatch_distill_batch

        other = "2026-01-01-other-spec"
        (self.root / "spec" / "archive" / other).mkdir(parents=True, exist_ok=True)
        self._seed_ledger([{"name": "capability:other-cap", "status": "pending"}])
        calls = []
        r = dispatch_distill_batch(
            self.root,
            [self._archive_name(), other],
            self._cfg(),
            dispatcher=self._fake_dispatcher(calls),
        )
        self.assertFalse(r["dispatched"])
        self.assertEqual(r["reason"], "backfill-queued")
        self.assertEqual(calls, [])
        ledger = self._ledger_text()
        self.assertIn(f'"name": "adr:{self._archive_name()}"', ledger)
        self.assertIn(f'"name": "adr:{other}"', ledger)

    def test_converged_ledger_resumes_immediate_dispatch(self):
        from core.knowledge import dispatch_distill

        self._seed_ledger(
            [
                {"name": "capability:pickup", "status": "distilled"},
                {"name": f"adr:{self._archive_name()}", "status": "distilled"},
            ]
        )
        calls = []
        r = dispatch_distill(
            self.root, self._archive_name(), self._cfg(), dispatcher=self._fake_dispatcher(calls)
        )
        self.assertTrue(r["dispatched"])  # 收敛后恢复即时派发
        self.assertEqual(calls, [[self._archive_name()]])

    def test_missing_ledger_dispatches_immediately(self):
        from core.knowledge import dispatch_distill

        calls = []
        r = dispatch_distill(
            self.root, self._archive_name(), self._cfg(), dispatcher=self._fake_dispatcher(calls)
        )
        self.assertTrue(r["dispatched"])
        self.assertEqual(calls, [[self._archive_name()]])


class TestCommitArchiveMoveMount(KnowledgeTestBase):
    """task 2.3：commit_archive_move 单点挂载（注入替身 + 既有测试隔离）。

    fixture 复刻真实移动：spec/changes/<名>/ 已入库 → shutil.move 到
    spec/archive/<归档名>/（setUp 建的空目录先摘掉），再调 commit_archive_move
    ——两侧 pathspec 均有内容，提交必然成功。
    """

    def _prepare_moved_project(self):
        import shutil

        archive_path = self.root / "spec" / "archive" / self._archive_name()
        shutil.rmtree(archive_path)  # setUp 建的空目录换成真实移动产物
        changes = self.root / "spec" / "changes" / "demo-spec"
        (changes / "specs" / "demo").mkdir(parents=True)
        (changes / "proposal.md").write_text("# demo", encoding="utf-8")
        self._git("init", "-q")
        self._git("config", "user.name", "t")
        self._git("config", "user.email", "t@t")
        self._git("add", "--", ".")
        self._git("commit", "-q", "-m", "init")
        shutil.move(str(changes), str(archive_path))

    def test_injected_fake_receives_archive_name(self):
        from core.archive_commit import commit_archive_move

        self._prepare_moved_project()
        got = {}

        def fake_distill(proot, archived_name):
            got["name"] = archived_name
            return {"dispatched": True, "reason": None}

        r = commit_archive_move(self.root, "demo-spec", self.root / "spec" / "archive" / self._archive_name(), distill=fake_distill)
        self.assertTrue(r["committed"])
        self.assertEqual(got["name"], self._archive_name())
        self.assertEqual(r["distill"], {"dispatched": True, "reason": None})

    def test_distill_raise_does_not_block_commit(self):
        from core.archive_commit import commit_archive_move

        self._prepare_moved_project()

        def boom(proot, archived_name):
            raise RuntimeError("x")

        r = commit_archive_move(self.root, "demo-spec", self.root / "spec" / "archive" / self._archive_name(), distill=boom)
        self.assertTrue(r["committed"])  # 归档提交不受蒸馏异常影响
        self.assertFalse(r["distill"]["dispatched"])
        self.assertIn("error", r["distill"]["reason"])

    def test_existing_tests_isolated_by_pytest_guard(self):
        """既有 tests/test_spec_archive.py 直接调用（不注入替身）→ pytest
        环境守卫拦截真实派发，distill.reason = test-environment。"""
        from core.archive_commit import commit_archive_move

        self._prepare_moved_project()
        r = commit_archive_move(self.root, "demo-spec", self.root / "spec" / "archive" / self._archive_name())
        self.assertTrue(r["committed"])
        self.assertEqual(r["distill"]["reason"], "test-environment")


class _FakeProc:
    def __init__(self, returncode=0, timeout=None):
        self.returncode = returncode
        self.timeout = timeout

    def communicate(self, timeout=None):
        if self.timeout is not None:
            raise subprocess.TimeoutExpired(cmd="claude", timeout=timeout)
        return "", ""


class TestDistillManager(KnowledgeTestBase):
    """task 2.4：fake spawn 三支路（成功 / 校验失败两轮修正 / 放弃）。"""

    def _manager(self, on_spawn, returncode=0, max_fix_rounds=2):
        mgr = DistillManager(max_fix_rounds=max_fix_rounds)

        def spawn(cmd, cwd):
            on_spawn(cmd, cwd)
            return _FakeProc(returncode)

        mgr._spawn = spawn
        return mgr

    def _spawn_writer(self, versions):
        """按轮次写不同产物的 fake spawn：versions[0] 首轮、versions[1] 修正轮…"""
        state = {"round": 0}
        lock = threading.Lock()

        def on_spawn(cmd, cwd):
            with lock:
                rnd = min(state["round"], len(versions) - 1)
                state["round"] += 1
            for rel, text in versions[rnd].items():
                p = Path(cwd) / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text, encoding="utf-8")

        return on_spawn

    def _prompt(self):
        return GOOD_PAGE.format(archive=self._archive_name(), today=date.today().isoformat())

    def _index(self):
        return (
            f"# 总目录\n\n- [拣选域](domains/pickup/_domain.md)\n\n"
            f"- [定时拣选](domains/pickup/scheduled-spec-pickup.md)\n"
        )

    def _domain(self):
        return "# 拣选域\n\n- [定时拣选](scheduled-spec-pickup.md)\n"

    def test_success_path_commits(self):
        self._git("init", "-q")
        self._git("config", "user.name", "t")
        self._git("config", "user.email", "t@t")
        self._git("commit", "-q", "--allow-empty", "-m", "init")
        versions = [
            {
                f"{KNOWLEDGE_DIR}/index.md": self._index(),
                f"{KNOWLEDGE_DIR}/domains/pickup/_domain.md": self._domain(),
                f"{KNOWLEDGE_DIR}/domains/pickup/scheduled-spec-pickup.md": self._prompt(),
            }
        ]
        mgr = self._manager(self._spawn_writer(versions))
        result = mgr._run_batch(self.root, [self._archive_name()])
        self.assertTrue(result["ok"])
        self.assertEqual(result["rounds"], 1)
        self.assertTrue(result["commit"])
        msg = self._git("log", "-1", "--format=%s").stdout.strip()
        self.assertEqual(msg, f"[fenix] knowledge: distill {self._archive_name()}")
        # pathspec 限定：只动 spec/knowledge/
        stat = self._git("show", "--name-only", "--format=").stdout
        touched = {ln.strip() for ln in stat.splitlines() if ln.strip()}
        self.assertTrue(all(t.startswith(KNOWLEDGE_DIR) for t in touched))

    def test_two_round_fix_then_pass(self):
        self._git("init", "-q")
        self._git("config", "user.name", "t")
        self._git("config", "user.email", "t@t")
        self._git("commit", "-q", "--allow-empty", "-m", "init")
        bad = dict(
            {
                f"{KNOWLEDGE_DIR}/domains/pickup/scheduled-spec-pickup.md":
                    self._prompt().replace("rev=1", "rev=notanint"),
            }
        )
        good = {
            f"{KNOWLEDGE_DIR}/index.md": self._index(),
            f"{KNOWLEDGE_DIR}/domains/pickup/_domain.md": self._domain(),
            f"{KNOWLEDGE_DIR}/domains/pickup/scheduled-spec-pickup.md": self._prompt(),
        }
        prompts = []

        def on_spawn(cmd, cwd):
            prompts.append(cmd[2])
            rnd = len(prompts) - 1
            payload = bad if rnd == 0 else good
            for rel, text in payload.items():
                p = Path(cwd) / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text, encoding="utf-8")

        mgr = self._manager(on_spawn)
        result = mgr._run_batch(self.root, [self._archive_name()])
        self.assertTrue(result["ok"])
        self.assertEqual(result["rounds"], 2)
        # 修正轮提示词携带违规清单
        self.assertIn("上一轮校验违规", prompts[1])
        self.assertIn("marker", prompts[1])

    def test_give_up_discards_and_registers_todo(self):
        self._git("init", "-q")
        self._git("config", "user.name", "t")
        self._git("config", "user.email", "t@t")
        base = self._prompt()
        self._write(f"{KNOWLEDGE_DIR}/domains/pickup/scheduled-spec-pickup.md", base)
        self._git("add", "--", ".")
        self._git("commit", "-q", "-m", "with-knowledge")
        tracked_before = self._git("ls-files", KNOWLEDGE_DIR).stdout

        # 每轮都写违规文件（marker 被抹掉）+ 未跟踪新文件
        bad = {f"{KNOWLEDGE_DIR}/domains/pickup/scheduled-spec-pickup.md": "# 毁坏\n\n没有 marker\n"}
        versions = [dict(bad, **{f"{KNOWLEDGE_DIR}/stray.md": "半成品"})] * 3
        mgr = self._manager(self._spawn_writer(versions), max_fix_rounds=2)
        result = mgr._run_batch(self.root, [self._archive_name()])
        self.assertFalse(result["ok"])
        # 半成品被清理：tracked 回 HEAD 态、未跟踪新增被清
        self.assertEqual(self._git("status", "--porcelain", "--", KNOWLEDGE_DIR).stdout.strip(), "")
        self.assertEqual(self._git("ls-files", KNOWLEDGE_DIR).stdout, tracked_before)
        page = (self.root / KNOWLEDGE_DIR / "domains/pickup/scheduled-spec-pickup.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("scheduled-spec-pickup", page)  # 回到 HEAD 原样
        self.assertNotIn("没有 marker", page)
        todo = (self.root / ".fenix" / "todo.md").read_text(encoding="utf-8")
        self.assertIn("knowledge-distill 重试", todo)

    def test_spawn_failure_gives_up(self):
        self._git("init", "-q")
        self._git("config", "user.name", "t")
        self._git("config", "user.email", "t@t")
        self._git("commit", "-q", "--allow-empty", "-m", "init")
        mgr = self._manager(lambda cmd, cwd: None, returncode=1)
        result = mgr._run_batch(self.root, [self._archive_name()])
        self.assertFalse(result["ok"])
        self.assertIn("非零退出", result["error"])
        todo = (self.root / ".fenix" / "todo.md").read_text(encoding="utf-8")
        self.assertIn("knowledge-distill", todo)

    def test_single_flight_queue_serializes(self):
        """并发 dispatch 排队串行：同 project 同时至多一个 run 在写。
        第一批处理中再入队第二批（worker 取批时序保证两批分开消费）。"""
        active = {"n": 0, "max": 0}
        lock = threading.Lock()
        done = threading.Event()
        rounds = {"n": 0}
        fired = {"second": False}

        def payload(cwd):
            for rel, text in {
                f"{KNOWLEDGE_DIR}/index.md": self._index(),
                f"{KNOWLEDGE_DIR}/domains/pickup/_domain.md": self._domain(),
                f"{KNOWLEDGE_DIR}/domains/pickup/scheduled-spec-pickup.md": self._prompt(),
            }.items():
                p = Path(cwd) / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text, encoding="utf-8")

        mgr = DistillManager()

        def on_spawn(cmd, cwd):
            with lock:
                active["n"] += 1
                active["max"] = max(active["max"], active["n"])
            proc = _FakeProc()
            payload(cwd)
            if not fired["second"]:
                fired["second"] = True
                mgr.dispatch(self.root, [self._archive_name() + "-2"])  # 第二批入队
            with lock:
                active["n"] -= 1
                rounds["n"] += 1
                if rounds["n"] >= 2:
                    done.set()
            return proc

        mgr._spawn = on_spawn
        # 不初始化 git：提交 fail-open 走 warning，不影响串行断言
        (self.root / "spec" / "archive" / self._archive_name()).mkdir(parents=True, exist_ok=True)
        (self.root / "spec" / "archive" / (self._archive_name() + "-2")).mkdir(
            parents=True, exist_ok=True
        )
        mgr.dispatch(self.root, [self._archive_name()])
        self.assertTrue(done.wait(timeout=30), "两个 run 未在超时内完成")
        with lock:
            self.assertEqual(active["max"], 1, "出现并发写 spec/knowledge/")
        self.assertEqual(mgr.pending(self.root), 0)

    def test_run_timeout_kills(self):
        from unittest import mock

        mgr = DistillManager(max_fix_rounds=0)

        def spawn(cmd, cwd):
            return _FakeProc(timeout=0.05)

        mgr._spawn = spawn
        # _kill_process_group 是真进程组 OS 胶水（fake proc 无真实 pid），
        # mock 掉只验证「超时 → 触发进程组清理 → 判失败」语义
        with mock.patch("core.knowledge._kill_process_group") as killpg:
            result = mgr._run_batch(self.root, [self._archive_name()])
        killpg.assert_called_once()
        self.assertFalse(result["ok"])
        self.assertIn("超时", result["error"])
        todo = (self.root / ".fenix" / "todo.md").read_text(encoding="utf-8")
        self.assertIn("knowledge-distill", todo)


if __name__ == "__main__":
    unittest.main()
