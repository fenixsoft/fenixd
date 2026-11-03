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
    LOG_HEADER,
    LOG_LINE_RE,
    DistillManager,
    INBOX_DONE_PREFIX,
    _log_subject_safe,
    append_knowledge_log,
    build_distill_prompt,
    knowledge_log_path,
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

# 更新时间盖戳标准行（index 与 _domain 通用；index 第 2 行 / _domain 紧随 H1；
# 本地时区展示，时区后缀随机器动态生成）
STAMP = "> 最后更新：2026-09-29 15:02 UTC+8"

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
        self.assertTrue(any("不存在的目录" in x for x in v))

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

    # ── 更新时间盖戳（index 标题/盖戳行/四列表 + _domain 盖戳行）─────────

    def _good_domain_nav(self, domain="pickup"):
        self._write(
            f"{KNOWLEDGE_DIR}/domains/{domain}/_domain.md",
            f"# 拣选域\n{STAMP}\n\n| 能力页 | 简介 | 更新时间 |\n"
            "| --- | --- | --- |\n"
            "| scheduled-spec-pickup | 按周期拣选 | 2026-09-29 15:02 |\n",
        )

    def _good_index(self):
        self._write(
            f"{KNOWLEDGE_DIR}/index.md",
            f"# 知识真相源\n{STAMP}\n\n## 能力域\n\n"
            "| 能力域 | 简介 | 能力数量 | 更新时间 |\n"
            "| --- | --- | --- | --- |\n"
            "| pickup | 拣选 | 1 | 2026-09-29 15:02 |\n",
        )

    def test_valid_full_tree_with_stamps_passes(self):
        self._good_page()
        self._good_domain_nav()
        self._good_index()
        self.assertEqual(validate_knowledge(self.root), [])

    def test_domain_nav_missing_stamp(self):
        self._good_page()
        self._write(f"{KNOWLEDGE_DIR}/domains/pickup/_domain.md", "# 拣选域\n\n内容\n")
        v = validate_knowledge(self.root)
        self.assertTrue(any("_domain.md" in x and "最后更新" in x for x in v))

    def test_domain_nav_stamp_bad_format(self):
        self._good_page()
        self._write(
            f"{KNOWLEDGE_DIR}/domains/pickup/_domain.md",
            "# 拣选域\n> 最后更新：昨天\n",
        )
        v = validate_knowledge(self.root)
        self.assertTrue(any("最后更新" in x for x in v))

    def test_domain_nav_stamp_not_after_h1(self):
        self._good_page()
        self._write(
            f"{KNOWLEDGE_DIR}/domains/pickup/_domain.md",
            f"# 拣选域\n\n简介段\n\n{STAMP}\n",
        )
        v = validate_knowledge(self.root)
        self.assertTrue(any("最后更新" in x for x in v))

    def test_domain_nav_missing_page_table(self):
        self._good_page()
        self._write(
            f"{KNOWLEDGE_DIR}/domains/pickup/_domain.md",
            f"# 拣选域\n{STAMP}\n\n正文无表格\n",
        )
        v = validate_knowledge(self.root)
        self.assertTrue(any("能力页" in x and "三列" in x for x in v))

    def test_domain_nav_page_table_two_columns(self):
        self._good_page()
        self._write(
            f"{KNOWLEDGE_DIR}/domains/pickup/_domain.md",
            f"# 拣选域\n{STAMP}\n\n"
            "| 能力页 | 简介 |\n| --- | --- |\n| scheduled-spec-pickup | 拣选 |\n",
        )
        v = validate_knowledge(self.root)
        self.assertTrue(any("能力页" in x and "三列" in x for x in v))

    def test_domain_nav_page_row_bad_time_format(self):
        self._good_page()
        self._write(
            f"{KNOWLEDGE_DIR}/domains/pickup/_domain.md",
            f"# 拣选域\n{STAMP}\n\n"
            "| 能力页 | 简介 | 更新时间 |\n| --- | --- | --- |\n"
            "| scheduled-spec-pickup | 拣选 | 昨天 |\n",
        )
        v = validate_knowledge(self.root)
        self.assertTrue(any("更新时间" in x for x in v))

    def test_index_title_must_be_truth_source(self):
        self._good_page()
        self._write(f"{KNOWLEDGE_DIR}/index.md", f"# 总目录\n{STAMP}\n")
        v = validate_knowledge(self.root)
        self.assertTrue(any("知识真相源" in x for x in v))

    def test_index_missing_stamp(self):
        self._good_page()
        self._write(f"{KNOWLEDGE_DIR}/index.md", "# 知识真相源\n\n正文\n")
        v = validate_knowledge(self.root)
        self.assertTrue(any("index.md" in x and "最后更新" in x for x in v))

    def test_index_missing_domain_table(self):
        self._good_page()
        self._write(f"{KNOWLEDGE_DIR}/index.md", f"# 知识真相源\n{STAMP}\n\n正文无表格\n")
        v = validate_knowledge(self.root)
        self.assertTrue(any("能力域" in x for x in v))

    def test_index_table_missing_update_column(self):
        self._good_page()
        self._write(
            f"{KNOWLEDGE_DIR}/index.md",
            f"# 知识真相源\n{STAMP}\n\n## 能力域\n\n"
            "| 能力域 | 简介 | 能力数量 |\n"
            "| --- | --- | --- |\n"
            "| pickup | 拣选 | 1 |\n",
        )
        v = validate_knowledge(self.root)
        self.assertTrue(any("能力域" in x and "四列" in x for x in v))

    def test_index_row_bad_time_format(self):
        self._good_page()
        self._write(
            f"{KNOWLEDGE_DIR}/index.md",
            f"# 知识真相源\n{STAMP}\n\n## 能力域\n\n"
            "| 能力域 | 简介 | 能力数量 | 更新时间 |\n"
            "| --- | --- | --- | --- |\n"
            "| pickup | 拣选 | 1 | 09-29 |\n",
        )
        v = validate_knowledge(self.root)
        self.assertTrue(any("更新时间" in x for x in v))

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
        self.assertTrue(any("不存在的目录" in x for x in v))

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


class TestCommitArchiveMoveNoDispatch(KnowledgeTestBase):
    """move-distill-trigger-to-push 1.2：归档不再触发蒸馏。

    蒸馏挂载迁至 approve_push 后：commit_archive_move 不再调用
    dispatch_distill，返回结构保留 ``distill: None`` 键兼容既有消费方；
    ``extra_paths``（知识页溯源改写产物）并入同一 ``[fenix] archive:`` 提交。
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

    def test_distill_key_is_none_and_no_dispatch(self):
        from core.archive_commit import commit_archive_move

        self._prepare_moved_project()
        r = commit_archive_move(
            self.root, "demo-spec", self.root / "spec" / "archive" / self._archive_name()
        )
        self.assertTrue(r["committed"])
        self.assertIsNone(r["distill"])  # 键保留（消费方兼容），恒 None

    def test_extra_paths_commit_in_same_archive_commit(self):
        from core.archive_commit import commit_archive_move

        self._prepare_moved_project()
        page = self.root / KNOWLEDGE_DIR / "domains" / "x" / "cap.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text("# 拣选\n", encoding="utf-8")
        r = commit_archive_move(
            self.root,
            "demo-spec",
            self.root / "spec" / "archive" / self._archive_name(),
            extra_paths=["spec/knowledge/domains/x/cap.md"],
        )
        self.assertTrue(r["committed"])
        touched = {
            ln.strip()
            for ln in self._git("show", "--name-only", "--no-renames", "--format=").stdout.splitlines()
            if ln.strip()
        }
        self.assertIn("spec/knowledge/domains/x/cap.md", touched)

    def test_extra_paths_unsafe_or_missing_dropped_not_blocking(self):
        """附加路径非法/已消失 → 剔除留痕，归档提交照常（fail-open）。"""
        from core.archive_commit import commit_archive_move

        self._prepare_moved_project()
        r = commit_archive_move(
            self.root,
            "demo-spec",
            self.root / "spec" / "archive" / self._archive_name(),
            extra_paths=["../evil", "spec/knowledge/gone.md"],
        )
        self.assertTrue(r["committed"])
        touched = {
            ln.strip()
            for ln in self._git("show", "--name-only", "--no-renames", "--format=").stdout.splitlines()
            if ln.strip()
        }
        self.assertNotIn("../evil", touched)
        self.assertNotIn("spec/knowledge/gone.md", touched)


class _FakeProc:
    def __init__(self, returncode=0, timeout=None):
        self.returncode = returncode
        self.timeout = timeout
        # 无真实进程：pid 取非法值，_kill_process_group 的 getpgid 会走
        # ProcessLookupError 兜底分支，不会误杀测试自身进程组
        self.pid = -1

    def communicate(self, prompt=None, timeout=None):
        # 与产品 _spawn_and_wait 的 stdin 传参口径一致：首参为提示词
        if self.timeout is not None:
            raise subprocess.TimeoutExpired(cmd="claude", timeout=timeout)
        return "", ""


class TestDistillManager(KnowledgeTestBase):
    """task 2.4：fake spawn 三支路（成功 / 校验失败两轮修正 / 放弃）。"""

    def _manager(self, on_spawn, returncode=0, max_fix_rounds=2):
        mgr = DistillManager(max_fix_rounds=max_fix_rounds)

        def spawn(cmd, cwd, env=None):
            on_spawn(cmd, cwd)
            return _FakeProc(returncode)

        mgr._spawn = spawn
        return mgr

    def _spawn_writer(self, versions):
        """按轮次写不同产物的 fake spawn：versions[0] 首轮、versions[1] 修正轮…"""
        state = {"round": 0}
        lock = threading.Lock()

        def on_spawn(cmd, cwd, env=None):
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
            f"# 知识真相源\n{STAMP}\n\n## 能力域\n\n"
            "| 能力域 | 简介 | 能力数量 | 更新时间 |\n"
            "| --- | --- | --- | --- |\n"
            "| [pickup](domains/pickup/_domain.md) | 拣选 | 1 | 2026-09-29 15:02 |\n"
        )

    def _domain(self):
        return (
            f"# 拣选域\n{STAMP}\n\n| 能力页 | 简介 | 更新时间 |\n| --- | --- | --- |\n"
            "| [定时拣选](scheduled-spec-pickup.md) | 按周期拣选 | 2026-09-29 15:02 |\n"
        )

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
        # add-knowledge-inbox-pipeline 4.2：distill 行随产出提交搭车——touched
        # 含 log.md，且无独立 log 提交顶掉蒸馏提交的 HEAD 位
        self.assertIn(f"{KNOWLEDGE_DIR}/log.md", touched)
        log_text = (self.root / KNOWLEDGE_DIR / "log.md").read_text(encoding="utf-8")
        self.assertTrue(
            any(LOG_LINE_RE.match(ln) and "distill |" in ln for ln in log_text.splitlines())
        )
        self.assertNotIn("[fenix] knowledge: log", self._git("log", "--format=%s").stdout)
        # add-distill-run-artifacts 4.1：批生命周期产物断言——批成功 → 产物
        # 落盘（恰一个），首行 started 带 timestamp、末行 result 终态
        artifacts = list((self.root / ".fenix" / "runs").glob("knowledge-distiller-*.jsonl"))
        self.assertEqual(len(artifacts), 1)
        lines = [
            json.loads(l)
            for l in artifacts[0].read_text(encoding="utf-8").splitlines()
            if l.strip()
        ]
        self.assertEqual(lines[0]["type"], "started")
        self.assertIn("timestamp", lines[0])
        self.assertEqual(lines[-1]["type"], "result")
        from core.dashboard.data.runs import classify_run

        self.assertEqual(classify_run(lines), "done")

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

        class _PromptCaptureProc(_FakeProc):
            # 提示词已改经 stdin 传入（不再在 argv），捕获点随接口同步
            def communicate(self, prompt=None, timeout=None):
                prompts.append(prompt)
                return super().communicate(prompt, timeout)

        def on_spawn(cmd, cwd, env=None):
            rnd = len(prompts)
            payload = bad if rnd == 0 else good
            for rel, text in payload.items():
                p = Path(cwd) / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text, encoding="utf-8")
            return _PromptCaptureProc()

        mgr = DistillManager(max_fix_rounds=2)
        mgr._spawn = on_spawn
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
        # 半成品被清理：tracked 回 HEAD 态、未跟踪新增被清。
        # add-knowledge-inbox-pipeline 4.2：失败批由 daemon 代码侧兜底追加
        # distill 失败行并独立小提交（保持工作区干净），tracked 集恰新增
        # 编年账 log.md。
        self.assertEqual(self._git("status", "--porcelain", "--", KNOWLEDGE_DIR).stdout.strip(), "")
        self.assertEqual(
            self._git("ls-files", KNOWLEDGE_DIR).stdout,
            tracked_before + f"{KNOWLEDGE_DIR}/log.md\n",
        )
        log_text = (self.root / KNOWLEDGE_DIR / "log.md").read_text(encoding="utf-8")
        self.assertIn("distill", log_text)
        self.assertIn("失败", log_text)
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

        def on_spawn(cmd, cwd, env=None):
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

        def spawn(cmd, cwd, env=None):
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


class TestKnowledgeLog(KnowledgeTestBase):
    """add-knowledge-inbox-pipeline 4.1：spec/knowledge/log.md 编年账机制。

    缺失建头（恰一次）、并发 flock 串行不丢行、越界 op 拒绝（代码缺陷不
    静默吞）、主题清洗单行契约（行前缀可 grep）。
    """

    def test_append_creates_header_once_then_appends(self):
        p = knowledge_log_path(self.root)
        self.assertTrue(append_knowledge_log(self.root, "distill", "首条"))
        self.assertTrue(append_knowledge_log(self.root, "fold", "第二条"))
        text = p.read_text(encoding="utf-8")
        self.assertTrue(text.startswith(LOG_HEADER))
        self.assertEqual(text.count(LOG_HEADER), 1)
        rows = [ln for ln in text.splitlines() if LOG_LINE_RE.match(ln)]
        self.assertEqual(len(rows), 2)
        self.assertIn("distill | 首条", rows[0])
        self.assertIn("fold | 第二条", rows[1])

    def test_append_concurrent_no_lost_lines(self):
        # flock 进程间互斥（同进程不同 fd 亦互斥）：16 线程 × 4 次 = 64 行全在
        n_threads, per_thread = 16, 4

        def worker(tid):
            for i in range(per_thread):
                self.assertTrue(append_knowledge_log(self.root, "lint", f"t{tid}-{i}"))

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        text = knowledge_log_path(self.root).read_text(encoding="utf-8")
        rows = [ln for ln in text.splitlines() if LOG_LINE_RE.match(ln)]
        self.assertEqual(len(rows), n_threads * per_thread)
        for t in range(n_threads):
            for i in range(per_thread):
                self.assertIn(f"lint | t{t}-{i}", text)

    def test_append_invalid_op_rejected(self):
        with self.assertRaises(ValueError):
            append_knowledge_log(self.root, "fold-only", "x")

    def test_append_detail_and_subject_sanitized(self):
        # 主题/明细压平为单行（换行/控制字符→空格），行前缀契约要求单行可 grep
        self.assertTrue(
            append_knowledge_log(
                self.root, "backfill", "主题一\n主题二\x07尾", detail="明一\n明二"
            )
        )
        text = knowledge_log_path(self.root).read_text(encoding="utf-8")
        self.assertIn("backfill | 主题一 主题二 尾", text)
        self.assertIn("明一 明二", text)
        rows = [ln for ln in text.splitlines() if "backfill |" in ln]
        self.assertEqual(len(rows), 1)

    def test_subject_safe_helper(self):
        self.assertEqual(_log_subject_safe("a\nb\x00c"), "a b c")
        self.assertEqual(_log_subject_safe("x" * 300), "x" * 160)
        self.assertEqual(_log_subject_safe("   \n\t "), "(空)")


class TestInboxCandidateArea(KnowledgeTestBase):
    """add-knowledge-inbox-pipeline 1.2/2.1：候选区 _inbox 扫描豁免与 done/
    溯源 file 形态。豁免守卫钉死扫描范围未来变更不误伤（marker/盖戳/行数
    顶/链接检查均不适用自由格式候选）。"""

    def _seed_good_core(self):
        self._write(
            f"{KNOWLEDGE_DIR}/index.md",
            (
                f"# 知识真相源\n{STAMP}\n\n## 能力域\n\n"
                "| 能力域 | 简介 | 能力数量 | 更新时间 |\n"
                "| --- | --- | --- | --- |\n"
                "| [pickup](domains/pickup/_domain.md) | 拣选 | 1 | 2026-09-29 15:02 |\n"
            ),
        )
        self._write(
            f"{KNOWLEDGE_DIR}/domains/pickup/_domain.md",
            (
                f"# 拣选域\n{STAMP}\n\n| 能力页 | 简介 | 更新时间 |\n| --- | --- | --- |\n"
                "| [定时拣选](scheduled-spec-pickup.md) | 按周期拣选 | 2026-09-29 15:02 |\n"
            ),
        )
        return self._write(
            f"{KNOWLEDGE_DIR}/domains/pickup/scheduled-spec-pickup.md",
            GOOD_PAGE.format(archive=self._archive_name(), today=date.today().isoformat()),
        )

    def _page_with_sources(self, sources):
        page = GOOD_PAGE.format(archive=self._archive_name(), today=date.today().isoformat())
        return page.replace(
            f"sources=spec/archive/{self._archive_name()}", f"sources={sources}"
        )

    # ── 1.2 扫描豁免 ─────────────────────────────────────────────────────

    def test_inbox_subdir_freeform_exempt_from_domain_scan(self):
        # 域目录内嵌 _inbox（守卫真实命中路径）：自由格式候选零违规
        self._seed_good_core()
        self._write(
            f"{KNOWLEDGE_DIR}/domains/pickup/_inbox/raw-note.md",
            "# 无 marker 无盖戳的自由候选\n\n"
            + "- 填充规则\n" * 160
            + "溯源：spec/changes/ghost-spec（不存在目录）\n",
        )
        self.assertEqual(validate_knowledge(self.root), [])

    def test_inbox_toplevel_freeform_not_validated(self):
        # 真实候选区位置（KNOWLEDGE_DIR/_inbox/）：同样零违规
        self._seed_good_core()
        self._write(
            f"{KNOWLEDGE_DIR}/_inbox/raw-note.md",
            "自由文本，无 marker：候选区不受能力页契约约束。\n",
        )
        self.assertEqual(validate_knowledge(self.root), [])

    # ── 2.1 sources 放行/拒绝 ────────────────────────────────────────────

    def test_sources_inbox_done_accepted_when_file_exists(self):
        self._seed_good_core()
        self._write(f"{INBOX_DONE_PREFIX}raw-note.md", "# 已折叠候选原文\n")
        self._write(
            f"{KNOWLEDGE_DIR}/domains/pickup/scheduled-spec-pickup.md",
            self._page_with_sources(f"{INBOX_DONE_PREFIX}raw-note.md"),
        )
        self.assertEqual(validate_knowledge(self.root), [])

    def test_sources_mixed_archive_and_done_accepted(self):
        # 折叠真实形态：归档目录 + done 文件并存（sources 追加语义）
        self._seed_good_core()
        self._write(f"{INBOX_DONE_PREFIX}raw-note.md", "# 已折叠候选原文\n")
        self._write(
            f"{KNOWLEDGE_DIR}/domains/pickup/scheduled-spec-pickup.md",
            self._page_with_sources(
                f"spec/archive/{self._archive_name()},{INBOX_DONE_PREFIX}raw-note.md"
            ),
        )
        self.assertEqual(validate_knowledge(self.root), [])

    def test_sources_inbox_done_missing_rejected(self):
        self._seed_good_core()
        self._write(
            f"{KNOWLEDGE_DIR}/domains/pickup/scheduled-spec-pickup.md",
            self._page_with_sources(f"{INBOX_DONE_PREFIX}ghost-note.md"),
        )
        violations = validate_knowledge(self.root)
        self.assertTrue(any("不存在" in v for v in violations), violations)

    def test_sources_inbox_done_escape_rejected(self):
        # ".." 相对段穿透：目标文件真实在盘但 resolve 后越出 done/ 目录 →
        # 越界违规（与归档分支同强度）
        self._seed_good_core()
        self._write(f"{INBOX_DONE_PREFIX}raw-note.md", "# 已折叠候选原文\n")
        escape = f"{INBOX_DONE_PREFIX}../../domains/pickup/scheduled-spec-pickup.md"
        self._write(
            f"{KNOWLEDGE_DIR}/domains/pickup/scheduled-spec-pickup.md",
            self._page_with_sources(escape),
        )
        violations = validate_knowledge(self.root)
        self.assertTrue(any("越出" in v for v in violations), violations)


class TestInboxFoldStage(KnowledgeTestBase):
    """add-knowledge-inbox-pipeline 3.1/3.2/3.3：distill 折叠前置段。

    fake spawn 按调用序分流（折叠前置段先于蒸馏轮，单条目即 spawn#1=fold、
    spawn#2=distill），覆盖折叠闭环（独立提交 + done/ 移动 + 行序）、校验
    失败滞留（条目原位不丢弃）、超顶产物被校验门拦下、无条目零动作、
    piggyback-only（候选区非空不产生独立 run）。
    """

    def _seed(self):
        """已入库知识基线三件套 + 一个候选条目。"""
        self._git("init", "-q")
        self._git("config", "user.name", "t")
        self._git("config", "user.email", "t@t")
        self._seed_good_core()
        self._git("add", "--", ".")
        self._git("commit", "-q", "-m", "init")
        self._write(
            f"{KNOWLEDGE_DIR}/_inbox/raw-note.md",
            "# 候选：排查结论\n\n结论：轮询间隔 300 秒是当前事实。\n",
        )

    def _seed_good_core(self):
        self._write(
            f"{KNOWLEDGE_DIR}/index.md",
            (
                f"# 知识真相源\n{STAMP}\n\n## 能力域\n\n"
                "| 能力域 | 简介 | 能力数量 | 更新时间 |\n"
                "| --- | --- | --- | --- |\n"
                "| [pickup](domains/pickup/_domain.md) | 拣选 | 1 | 2026-09-29 15:02 |\n"
            ),
        )
        self._write(
            f"{KNOWLEDGE_DIR}/domains/pickup/_domain.md",
            (
                f"# 拣选域\n{STAMP}\n\n| 能力页 | 简介 | 更新时间 |\n| --- | --- | --- |\n"
                "| [定时拣选](scheduled-spec-pickup.md) | 按周期拣选 | 2026-09-29 15:02 |\n"
            ),
        )
        self._write(
            f"{KNOWLEDGE_DIR}/domains/pickup/scheduled-spec-pickup.md",
            GOOD_PAGE.format(archive=self._archive_name(), today=date.today().isoformat()),
        )

    def _distill_versions(self):
        return {
            f"{KNOWLEDGE_DIR}/index.md": (
                f"# 知识真相源\n{STAMP}\n\n## 能力域\n\n"
                "| 能力域 | 简介 | 能力数量 | 更新时间 |\n"
                "| --- | --- | --- | --- |\n"
                "| [pickup](domains/pickup/_domain.md) | 拣选 | 1 | 2026-09-29 16:02 |\n"
            ),
            f"{KNOWLEDGE_DIR}/domains/pickup/_domain.md": (
                f"# 拣选域\n{STAMP}\n\n| 能力页 | 简介 | 更新时间 |\n| --- | --- | --- |\n"
                "| [定时拣选](scheduled-spec-pickup.md) | 按周期拣选 | 2026-09-29 16:02 |\n"
            ),
            f"{KNOWLEDGE_DIR}/domains/pickup/scheduled-spec-pickup.md": GOOD_PAGE.format(
                archive=self._archive_name(), today=date.today().isoformat()
            ),
        }

    def _fold_ok(self, root):
        """折叠成功替身：既有页追加 done/ 溯源 + 条目移 done/。"""
        page = root / f"{KNOWLEDGE_DIR}/domains/pickup/scheduled-spec-pickup.md"
        arch = self._archive_name()
        text = page.read_text(encoding="utf-8")
        text = text.replace(
            f"sources=spec/archive/{arch}",
            f"sources=spec/archive/{arch},{INBOX_DONE_PREFIX}raw-note.md",
        )
        text = text.replace(
            f"- {date.today().isoformat()} {arch} — 新建本页",
            f"- {date.today().isoformat()} {arch} — 新建本页\n"
            f"- {date.today().isoformat()} raw-note（{INBOX_DONE_PREFIX}raw-note.md）"
            " — 折叠候选规则",
        )
        page.write_text(text, encoding="utf-8")
        done = root / INBOX_DONE_PREFIX
        done.mkdir(parents=True, exist_ok=True)
        (root / f"{KNOWLEDGE_DIR}/_inbox/raw-note.md").rename(done / "raw-note.md")

    def _manager_split(self, fold_fn, distill_fn):
        """spawn 按调用序分流：spawn#1 折叠前置段、spawn#2+ 蒸馏轮。"""
        state = {"n": 0}
        lock = threading.Lock()

        def on_spawn(cmd, cwd, env=None):
            with lock:
                n = state["n"]
                state["n"] += 1
            (fold_fn if n == 0 else distill_fn)(Path(cwd))
            return _FakeProc(0)

        mgr = DistillManager(max_fix_rounds=2)

        def spawn(cmd, cwd, env=None):
            return on_spawn(cmd, cwd, env)

        mgr._spawn = spawn
        return mgr

    def _log_text(self):
        return (self.root / KNOWLEDGE_DIR / "log.md").read_text(encoding="utf-8")

    def test_fold_success_closed_loop(self):
        self._seed()
        mgr = self._manager_split(self._fold_ok, lambda root: None)
        versions = self._distill_versions()

        def distill(root):
            for rel, text in versions.items():
                p = root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text, encoding="utf-8")

        mgr = self._manager_split(self._fold_ok, distill)
        result = mgr._run_batch(self.root, [self._archive_name()])
        self.assertTrue(result["ok"])
        self.assertEqual(result["folded"], 1)
        self.assertEqual(result["fold_failed"], 0)
        # 条目移 done/，原位消失
        self.assertFalse((self.root / KNOWLEDGE_DIR / "_inbox" / "raw-note.md").exists())
        self.assertTrue((self.root / INBOX_DONE_PREFIX / "raw-note.md").is_file())
        # 折叠独立提交在蒸馏提交之前（HEAD 仍是 distill 本体）
        subjects = self._git("log", "--format=%s").stdout.splitlines()
        self.assertEqual(subjects[0], f"[fenix] knowledge: distill {self._archive_name()}")
        self.assertIn("[fenix] knowledge: fold raw-note.md", subjects[1:])
        # 4.2 行序契约：fold 行先于 distill 行
        log = self._log_text()
        self.assertLess(log.index("fold |"), log.index("distill |"))

    def test_fold_validate_fail_entry_stays(self):
        self._seed()
        snapshot = (self.root / KNOWLEDGE_DIR / "_inbox" / "raw-note.md").read_text(
            encoding="utf-8"
        )

        def fold_bad(root):
            # 毁页且不移动条目：实时校验违规 → 回滚
            page = root / f"{KNOWLEDGE_DIR}/domains/pickup/scheduled-spec-pickup.md"
            page.write_text("# 毁坏\n\n没有 marker\n", encoding="utf-8")

        versions = self._distill_versions()

        def distill(root):
            for rel, text in versions.items():
                p = root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text, encoding="utf-8")

        mgr = self._manager_split(fold_bad, distill)
        result = mgr._run_batch(self.root, [self._archive_name()])
        # 折叠失败不阻断批：蒸馏照常收工
        self.assertTrue(result["ok"])
        self.assertEqual(result["folded"], 0)
        self.assertEqual(result["fold_failed"], 1)
        # 条目滞留原地且内容未被改动
        entry = self.root / KNOWLEDGE_DIR / "_inbox" / "raw-note.md"
        self.assertTrue(entry.is_file())
        self.assertEqual(entry.read_text(encoding="utf-8"), snapshot)
        # 工作区干净（失败行已独立小提交，不污染后续批基线甄别）；候选条目
        # untracked（?? _inbox/）是自由区常态，豁免不计
        residual = [
            ln
            for ln in self._git("status", "--porcelain", "--", KNOWLEDGE_DIR).stdout.splitlines()
            if "_inbox" not in ln
        ]
        self.assertEqual(residual, [])
        log = self._log_text()
        self.assertIn("折叠失败滞留", log)
        # 失败留痕独立提交在案
        self.assertIn("[fenix] knowledge: log", self._git("log", "--format=%s").stdout)

    def test_fold_overcap_rejected_and_entry_stays(self):
        self._seed()
        snapshot = (self.root / KNOWLEDGE_DIR / "_inbox" / "raw-note.md").read_text(
            encoding="utf-8"
        )

        def fold_overcap(root):
            # 新建超 150 行页：150 行硬顶在校验门拦下（拆页指令被无视的形态）
            body = (
                "<!-- knowledge: capability=overflow-cap rev=1\n"
                f"     sources=spec/archive/{self._archive_name()} -->\n"
                "# overflow\n\n## 规则\n\n" + "- 填充规则\n" * 160
            )
            p = root / f"{KNOWLEDGE_DIR}/domains/pickup/overflow-cap.md"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")

        versions = self._distill_versions()

        def distill(root):
            for rel, text in versions.items():
                p = root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text, encoding="utf-8")

        mgr = self._manager_split(fold_overcap, distill)
        result = mgr._run_batch(self.root, [self._archive_name()])
        self.assertTrue(result["ok"])
        self.assertEqual(result["fold_failed"], 1)
        entry = self.root / KNOWLEDGE_DIR / "_inbox" / "raw-note.md"
        self.assertEqual(entry.read_text(encoding="utf-8"), snapshot)
        # 超顶产物被清理，无残留半成品
        self.assertFalse(
            (self.root / KNOWLEDGE_DIR / "domains/pickup/overflow-cap.md").exists()
        )
        self.assertIn("150", self._log_text())

    def test_no_inbox_no_fold(self):
        self._git("init", "-q")
        self._git("config", "user.name", "t")
        self._git("config", "user.email", "t@t")
        self._seed_good_core()
        self._git("add", "--", ".")
        self._git("commit", "-q", "-m", "init")
        versions = self._distill_versions()

        def distill(root):
            for rel, text in versions.items():
                p = root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text, encoding="utf-8")

        mgr = self._manager_split(lambda root: None, distill)
        result = mgr._run_batch(self.root, [self._archive_name()])
        self.assertTrue(result["ok"])
        self.assertEqual(result["folded"], 0)
        self.assertNotIn("[fenix] knowledge: fold", self._git("log", "--format=%s").stdout)

    def test_fold_prompt_pins_split_and_done_directives(self):
        from core.knowledge import build_inbox_fold_prompt

        prompt = build_inbox_fold_prompt(self.root, "raw-note.md")
        # 拆页指令与 done/ 语义、收尾标记在折叠提示词单源钉死
        self.assertIn("150 行", prompt)
        self.assertIn("拆主从分片", prompt)
        self.assertIn(f"{KNOWLEDGE_DIR}/_inbox/done/raw-note.md", prompt)
        self.assertIn("KNOWLEDGE_DISTILL_DONE", prompt)
        self.assertIn("本轮模式：inbox 折叠前置段", prompt)

    def test_backlog_alone_triggers_no_run(self):
        # piggyback-only（3.3）：_inbox 非空 + 无蒸馏批次 → 不产生任何 run
        from core.knowledge import dispatch_distill_batch

        self._seed()
        dispatched = []

        class Fake:
            def dispatch(self, proot, names):
                dispatched.append(names)
                return {"dispatched": True}

        cfg = {"knowledge_distill_enabled": True}
        r = dispatch_distill_batch(self.root, [], cfg, dispatcher=Fake())
        self.assertFalse(r["dispatched"])
        self.assertEqual(dispatched, [])

    def test_e2e_fold_then_distill_full_chain(self):
        """add-knowledge-inbox-pipeline 8.1：端到端闭环。

        合成夹具 `_inbox` 条目 → 驱动 distill 轮（真实编排：折叠前置段 →
        实时校验门 → 折叠独立提交 → 蒸馏轮 → 代码侧编年账）→ 断言能力页
        折叠内容在场、marker sources 机器校验通过（``validate_knowledge``
        全树零违规）、条目移 `done/`、`log.md` fold+distill 行齐备。
        """
        self._seed()
        arch = self._archive_name()
        fold_rule = "- 折叠规则：候选区条目按顺序逐条消化入库。"

        def fold_ok(root):
            # LLM 子进程字节替身：能力页规则段追加折叠规则句 + sources 追加
            # done/ 前缀溯源 + 变更记录行 + 条目移 done/（与真实折叠产出同构）
            self._fold_ok(root)
            page = root / f"{KNOWLEDGE_DIR}/domains/pickup/scheduled-spec-pickup.md"
            text = page.read_text(encoding="utf-8")
            text = text.replace("- 轮询间隔 300 秒。", f"- 轮询间隔 300 秒。\n{fold_rule}")
            page.write_text(text, encoding="utf-8")

        versions = self._distill_versions()

        def distill(root):
            # 真实蒸馏是增量修改（拿到含折叠内容的当前树），替身只更新
            # index/_domain 盖戳版本，不重写能力页——保留折叠内容
            for rel in (f"{KNOWLEDGE_DIR}/index.md", f"{KNOWLEDGE_DIR}/domains/pickup/_domain.md"):
                p = root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(versions[rel], encoding="utf-8")

        mgr = self._manager_split(fold_ok, distill)
        result = mgr._run_batch(self.root, [arch])
        self.assertTrue(result["ok"])
        self.assertEqual(result["folded"], 1)
        self.assertEqual(result["fold_failed"], 0)

        # ① 条目移 done/：原位消失、done/ 落位、原文逐字节保留
        self.assertFalse((self.root / KNOWLEDGE_DIR / "_inbox" / "raw-note.md").exists())
        done_entry = self.root / INBOX_DONE_PREFIX / "raw-note.md"
        self.assertTrue(done_entry.is_file())
        self.assertIn("轮询间隔 300 秒是当前事实", done_entry.read_text(encoding="utf-8"))

        # ② 能力页折叠内容在场：规则段新句 + sources done/ 溯源 + 变更行
        page = (self.root / f"{KNOWLEDGE_DIR}/domains/pickup/scheduled-spec-pickup.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(fold_rule, page)
        self.assertIn(f"sources=spec/archive/{arch},{INBOX_DONE_PREFIX}raw-note.md", page)
        self.assertIn("折叠候选规则", page)

        # ③ marker sources 机器校验通过：全树 validate_knowledge 零违规
        self.assertEqual(validate_knowledge(self.root), [])

        # ④ log.md fold+distill 行齐备：行前缀形态合法（LOG_LINE_RE）、
        # 本地时区显式标注、行序 fold 先于 distill（4.2 顺序契约）
        log = self._log_text()
        fold_line = next(ln for ln in log.splitlines() if "fold |" in ln)
        distill_line = next(ln for ln in log.splitlines() if "distill |" in ln)
        self.assertLess(log.index(fold_line), log.index(distill_line))
        self.assertTrue(LOG_LINE_RE.match(fold_line), fold_line)
        self.assertTrue(LOG_LINE_RE.match(distill_line), distill_line)
        self.assertIn("raw-note.md 折叠入库", fold_line)
        self.assertIn("折叠入库 1 条", distill_line)

        # ⑤ 提交序：蒸馏提交在 HEAD，折叠独立提交在先
        subjects = self._git("log", "--format=%s").stdout.splitlines()
        self.assertEqual(subjects[0], f"[fenix] knowledge: distill {arch}")
        self.assertIn("[fenix] knowledge: fold raw-note.md", subjects[1:])


if __name__ == "__main__":
    unittest.main()


class TestDistillSourceDoubleState(KnowledgeTestBase):
    """move-distill-trigger-to-push 2.3：蒸馏输入目录双态解析。

    push 态（changes/ 存在）门控放行 + prompt 路径正确；归档态（仅 archive/
    存在，恢复重派兜底）放行 + prompt 路径兜底；双缺拒绝 reason 保留
    archive-dir-missing 字面量。
    """

    def _cfg(self):
        return {"knowledge": {"enabled": True}}

    def _make_changes_spec(self, name="demo-spec"):
        (self.root / "spec" / "changes" / name).mkdir(parents=True, exist_ok=True)

    def test_push_state_gate_passes_and_prompt_points_to_changes(self):
        import shutil

        # 摘掉 archive 目录，模拟 push 态（SPEC 只在 changes/）
        shutil.rmtree(self.root / "spec" / "archive" / self._archive_name())
        self._make_changes_spec()
        got = {}

        class Fake:
            def dispatch(self, proot, names):
                got["names"] = list(names)

        from core.knowledge import dispatch_distill

        r = dispatch_distill(
            self.root, "demo-spec", self._cfg(), dispatcher=Fake()
        )
        self.assertTrue(r["dispatched"])
        self.assertEqual(got["names"], ["demo-spec"])
        prompt = build_distill_prompt(self.root, ["demo-spec"])
        self.assertIn("本次待蒸馏的 SPEC", prompt)
        self.assertIn(str(self.root / "spec" / "changes" / "demo-spec"), prompt)
        self.assertNotIn("spec/archive/demo-spec", prompt)

    def test_archive_state_fallback_gate_passes_and_prompt_fallback(self):
        """归档态（changes/ 无、archive/ 有，恢复重派兜底）放行 + 路径兜底。"""
        import shutil

        shutil.rmtree(self.root / "spec" / "archive" / self._archive_name())
        # setUp 重建 archive 目录（changes/ 不建）——直接用 setUp 既有目录
        (self.root / "spec" / "archive" / self._archive_name()).mkdir(parents=True)
        got = {}

        class Fake:
            def dispatch(self, proot, names):
                got["names"] = list(names)

        from core.knowledge import dispatch_distill

        r = dispatch_distill(
            self.root, self._archive_name(), self._cfg(), dispatcher=Fake()
        )
        self.assertTrue(r["dispatched"])
        prompt = build_distill_prompt(self.root, [self._archive_name()])
        self.assertIn(
            str(self.root / "spec" / "archive" / self._archive_name()), prompt
        )

    def test_both_missing_rejected_with_literal_reason(self):
        from core.knowledge import dispatch_distill

        r = dispatch_distill(
            self.root, "1999-01-01-gone", self._cfg(), dispatcher=object()
        )
        self.assertFalse(r["dispatched"])
        self.assertEqual(r["reason"], "archive-dir-missing")  # 字面量兼容消费方

    def test_both_missing_batch_reason_lists_names(self):
        from core.knowledge import _gate_distill

        r = _gate_distill(
            self.root, ["gone-a", "gone-b"], self._cfg()
        )
        self.assertFalse(r["dispatched"])
        self.assertEqual(r["reason"], "archive-dir-missing: gone-a, gone-b")


class TestTemplateCheckerConsistency(KnowledgeTestBase):
    """move-distill-trigger-to-push 2.3：模板契约段与 _check_links 一致性。

    模板是蒸馏 agent 的唯一契约载体：溯源行保持全角括号纯文本形态、路径段
    指 spec/changes/<名>/；不得引入 markdown 链接形态的 spec/ 路径（_check_links
    按页面相对路径解析必然误报死链）。按模板示例写出的页面过校验零违规。
    """

    def _template(self):
        from core.knowledge import load_distill_prompt

        return load_distill_prompt()

    def test_template_no_markdown_link_to_spec_paths(self):
        """模板内不得出现 ](spec/...) markdown 链接形态（防第三种链接形态）。"""
        import re

        for m in re.finditer(r"\[[^\]]*\]\(([^)]*)\)", self._template()):
            self.assertFalse(
                m.group(1).startswith("spec/"),
                f"模板引入了 markdown 链接形态的 spec 路径: {m.group(0)}",
            )

    def test_template_trace_form_is_plain_text_with_changes_path(self):
        import re

        tpl = self._template()
        self.assertIn("spec/changes/<SPEC名>/", tpl)
        self.assertIn("sources=spec/changes/<SPEC名1>", tpl)
        # 溯源行纪律段要求纯文本 + 只写真实存在目录
        self.assertIn("纯文本", tpl)
        self.assertIn("真实存在", tpl)
        # 模板不再教 agent 写 archive 路径（改写 pass 负责归档态迁移）
        self.assertNotIn("](spec/archive/", tpl)

    def test_page_per_template_example_passes_validate_changes_state(self):
        """按模板溯源行示例（changes 态）写出的页面过 validate_knowledge 零违规。"""
        name = "demo-spec"
        (self.root / "spec" / "changes" / name).mkdir(parents=True, exist_ok=True)
        self._write(
            f"{KNOWLEDGE_DIR}/domains/pickup/scheduled-spec-pickup.md",
            (
                "# 定时拣选\n\n"
                f"<!-- knowledge: capability=scheduled-spec-pickup rev=1\n"
                f"     sources=spec/changes/{name} -->\n\n"
                "按周期把已完成 SPEC 拣选进归档。\n\n"
                "## 规则\n\n- 轮询间隔 300 秒。\n\n"
                "## 溯源\n\n"
                f"- {date.today().isoformat()} {name}（spec/changes/{name}/） — 新建本页\n"
            ),
        )
        self.assertEqual(validate_knowledge(self.root), [])

    def test_changes_state_sources_pass_and_archive_state_unchanged(self):
        """3.5 两态 sources：changes 态过校验；archive 态行为不变（存量锁定）。"""
        name = "demo-spec"
        (self.root / "spec" / "changes" / name).mkdir(parents=True, exist_ok=True)
        self._write(
            f"{KNOWLEDGE_DIR}/domains/d/changes-sourced.md",
            (
                "# 变更源能力\n\n"
                f"<!-- knowledge: capability=changes-sourced rev=1\n"
                f"     sources=spec/changes/{name} -->\n\n"
                "规则一句。\n\n## 溯源\n\n"
                f"- {date.today().isoformat()} {name}（spec/changes/{name}/） — 新建\n"
            ),
        )
        self.assertEqual(validate_knowledge(self.root), [])
        # archive 态（setUp 已建 archive/<date-demo-spec>）：既有形态零回归
        self._write(
            f"{KNOWLEDGE_DIR}/domains/d/archive-sourced.md",
            GOOD_PAGE.format(archive=self._archive_name(), today=date.today().isoformat()),
        )
        self.assertEqual(validate_knowledge(self.root), [])

    def test_sources_two_state_boundary_still_enforced(self):
        """两态放宽不降防穿透强度：目录缺失与 ".." 越界照样报违规。"""
        name = "demo-spec"
        self._write(
            f"{KNOWLEDGE_DIR}/domains/d/dangling-changes.md",
            (
                "# 悬空源\n\n"
                "<!-- knowledge: capability=dangling-changes rev=1\n"
                f"     sources=spec/changes/{name} -->\n\n"
                "规则一句。\n\n## 溯源\n\n- x\n"
            ),
        )
        v = validate_knowledge(self.root)
        self.assertTrue(any("不存在的目录" in x for x in v))
        # changes 态 ".." 越界复核（changes/ 与 archive/ 均在盘也不放行）：
        # demo-spec/../../../ = 项目根（changes→spec→根），elsewhere 在根下
        (self.root / "spec" / "changes" / name).mkdir(parents=True, exist_ok=True)
        escaped = self.root / "elsewhere"
        escaped.mkdir(exist_ok=True)
        self._write(
            f"{KNOWLEDGE_DIR}/domains/d/escape-changes.md",
            (
                "# 越界源\n\n"
                "<!-- knowledge: capability=escape-changes rev=1\n"
                f"     sources=spec/changes/{name}/../../../elsewhere -->\n\n"
                "规则一句。\n\n## 溯源\n\n- x\n"
            ),
        )
        v = validate_knowledge(self.root)
        self.assertTrue(any("越出" in x for x in v))
