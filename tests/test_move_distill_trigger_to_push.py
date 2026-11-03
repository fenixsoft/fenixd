"""move-distill-trigger-to-push — 蒸馏触发点迁移（push 触发）回归。

覆盖（对应 SPEC specs/distill-push-trigger/spec.md 三条 Requirement 的落地件）：
- 溯源改写器（task 3.1）：spec/changes/<名> → spec/archive/<date-name> 精确
  替换、名字右边界（前缀同名不误伤，真实在库例 merge-back ↔ merge-back-
  precheck）、返回替换文件清单、异常上抛调用方（fail-open 决策在调用方）；
- 归档接线（task 3.2）：archive_spec（daemon R1/R2/R3 自动归档主线）与
  bin/fenix_archive.py（CLI）移动成功后改写并与归档同一 ``[fenix] archive:``
  提交落库；改写异常 fail-open 归档照常；
- 链接门两态等价（task 3.3/3.4）：知识页链接指向 changes/ 时 validate_knowledge
  与 knowledge_audit（悬空溯源扫描/机械自修）均零违规零误删。

运行：python3 -m pytest tests/test_move_distill_trigger_to_push.py -q
"""

import importlib.util
import os
import subprocess
import tempfile
import unittest
import shutil
from datetime import date
from pathlib import Path
from unittest import mock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.knowledge import (
    KNOWLEDGE_DIR,
    rewrite_source_links_to_archive,
    validate_knowledge,
)

GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}

TODAY = date.today().isoformat()


def _git(proot: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(proot), *args],
        env=GIT_ENV, capture_output=True, text=True, timeout=60,
    )


def _make_git_project(root: Path, name: str = "demo-spec") -> None:
    """最小已入库 git 项目：spec/changes/<name>/ 提交在案。"""
    changes = root / "spec" / "changes" / name
    (changes / "specs" / "demo").mkdir(parents=True)
    (changes / "proposal.md").write_text("# demo", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "user.email", "t@t")
    _git(root, "add", "--", ".")
    _git(root, "commit", "-q", "-m", "init")


PAGE_TPL = """# 定时拣选

<!-- knowledge: capability=scheduled-spec-pickup rev=1
     sources=spec/changes/{name} -->

按周期把已完成 SPEC 拣选进归档。

## 规则

- 轮询间隔 300 秒。

## 溯源

- {today} {name}（spec/changes/{name}/） — 新建本页
- 关联规格见 spec/changes/{name}（正文纯文本引用）
"""


class RewriteTestBase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        self.spec = "demo-spec"
        (self.root / "spec" / "changes" / self.spec).mkdir(parents=True)
        self.page = self._write_page(
            "domains/pickup/scheduled-spec-pickup.md",
            PAGE_TPL.format(name=self.spec, today=TODAY),
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_page(self, rel, text):
        p = self.root / KNOWLEDGE_DIR / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def _archive_name(self, spec=None):
        return f"{TODAY}-{spec or self.spec}"


class TestRewriteSourceLinks(RewriteTestBase):
    """task 3.1：溯源改写器单函数。"""

    def test_sources_and_body_refs_rewritten(self):
        rewritten = rewrite_source_links_to_archive(
            self.root, self.spec, self._archive_name()
        )
        self.assertEqual(
            rewritten,
            ["spec/knowledge/domains/pickup/scheduled-spec-pickup.md"],
        )
        text = self.page.read_text(encoding="utf-8")
        arch = f"spec/archive/{self._archive_name()}"
        # sources 行与正文溯源行（全角括号纯文本）两种形态均命中
        self.assertIn(f"sources={arch}", text)
        self.assertIn(f"（{arch}/）", text)
        self.assertNotIn(f"spec/changes/{self.spec}", text)

    def test_prefix_same_name_not_hit(self):
        """名字右边界：merge-back 改写不得误伤 merge-back-precheck 的引用。"""
        other = "merge-back-precheck"
        page = self._write_page(
            "domains/git/merge-back.md",
            (
                "# merge-back\n\n"
                "<!-- knowledge: capability=merge-back rev=1\n"
                "     sources=spec/changes/merge-back -->\n\n"
                "## 溯源\n\n"
                f"- {TODAY} merge-back（spec/changes/merge-back/） — 新建\n"
                f"- 关联（spec/changes/{other}/） — 前缀同名 SPEC 不得被改写\n"
                f"- 正文中缀引用 spec/changes/{other} 亦不得被改写\n"
            ),
        )
        rewritten = rewrite_source_links_to_archive(
            self.root, "merge-back", f"{TODAY}-merge-back"
        )
        self.assertEqual(
            rewritten, ["spec/knowledge/domains/git/merge-back.md"]
        )
        text = page.read_text(encoding="utf-8")
        self.assertIn(f"spec/archive/{TODAY}-merge-back", text)
        # 前缀同名引用三处原样保留
        self.assertIn(f"spec/changes/{other}", text)
        self.assertEqual(text.count(f"spec/changes/{other}"), 2)

    def test_name_boundary_requires_non_name_char(self):
        """命中后随名字字符（连字符/点/字母）→ 否决；后随 / ）等或串尾 → 命中。"""
        self._write_page(
            "domains/git/boundary.md",
            (
                "# boundary\n\n"
                "spec/changes/demo 前缀截断不命中\n"
                "spec/changes/demo.spec 点后缀不命中\n"
                "spec/changes/demo-spec 完整名命中\n"
                "spec/changes/demo-spec/ 带斜杠命中\n"
            ),
        )
        rewrite_source_links_to_archive(
            self.root, "demo-spec", self._archive_name()
        )
        text = (self.root / KNOWLEDGE_DIR / "domains/git/boundary.md").read_text(
            encoding="utf-8"
        )
        arch = f"spec/archive/{self._archive_name()}"
        # 两处前缀截断/点后缀形态原样保留（右边界否决）
        self.assertIn("spec/changes/demo 前缀截断不命中", text)
        self.assertIn("spec/changes/demo.spec 点后缀不命中", text)
        # 完整名与带斜杠形态各命中一次
        self.assertEqual(text.count(arch), 2)

    def test_knowledge_dir_missing_returns_empty(self):
        shutil.rmtree(self.root / KNOWLEDGE_DIR)
        self.assertEqual(
            rewrite_source_links_to_archive(
                self.root, self.spec, self._archive_name()
            ),
            [],
        )

    def test_unrelated_pages_not_listed(self):
        page2 = self._write_page("domains/other/keep.md", "# 不相关\n\n保持原样\n")
        before = page2.read_text(encoding="utf-8")
        rewritten = rewrite_source_links_to_archive(
            self.root, self.spec, self._archive_name()
        )
        self.assertNotIn(
            "spec/knowledge/domains/other/keep.md", rewritten
        )
        self.assertEqual(page2.read_text(encoding="utf-8"), before)

    def test_write_error_propagates_to_caller(self):
        """写盘异常上抛调用方（fail-open 决策在调用方，本函数不吞）。

        写通道已收敛到 atomic_write_text（tmp+os.replace 原子落盘，code-review
        c03e0a119818），Path.write_text 不再是写路径原语——注入点移到其底层
        os.fdopen：mkstemp 占位成功后打开即失败，OSError 须原样上穿
        fs_utils 写实现与 atomic_write_text 门面抵达调用方，本函数不吞。
        """

        def _fdopen_raises(fd, *args, **kwargs):
            os.close(fd)
            raise OSError("disk full")

        with mock.patch("os.fdopen", side_effect=_fdopen_raises):
            with self.assertRaises(OSError):
                rewrite_source_links_to_archive(
                    self.root, self.spec, self._archive_name()
                )


class TestRewriteInboxExemption(RewriteTestBase):
    """add-knowledge-inbox-pipeline 5.1：归档溯源改写器对候选区与编年账豁免。

    候选原文「永久可考」要求逐字节冻结——含 ``spec/changes/<名>`` 历史形态
    文本的条目与 log.md 不改写（接受指向已消失目录的历史文本，静默改写才是
    真违背承诺）；能力页照常改写对照豁免不是整体失效。
    """

    def test_inbox_entry_log_and_done_frozen_byte_for_byte(self):
        entry = self._write_page(
            "_inbox/old-session-note.md",
            (
                "# 排查结论\n\n"
                "现场证据见 spec/changes/demo-spec/proposal.md；历史形态引用\n"
                f"spec/changes/{self.spec} 在归档后指向已消失目录，保持原样。\n"
            ),
        )
        done = self._write_page("_inbox/done/old-note.md", "# 已折叠原文（同样冻结）\n")
        log = self._write_page(
            "log.md",
            "## [%s 10:00 UTC+8] distill | demo-spec（第 1 轮，自动提交落库）\n"
            % TODAY,
        )
        before = {p: p.read_bytes() for p in (entry, done, log)}
        rewritten = rewrite_source_links_to_archive(
            self.root, self.spec, self._archive_name()
        )
        # 能力页照常改写；候选区与编年账不在改写清单
        self.assertEqual(
            rewritten,
            ["spec/knowledge/domains/pickup/scheduled-spec-pickup.md"],
        )
        for p, blob in before.items():
            self.assertEqual(p.read_bytes(), blob, f"{p} 应逐字节冻结")


class _ArchiveIntegrationBase(RewriteTestBase):
    """归档接线共用：git 项目 + STATE 条目 + 知识页（push 态 changes/ 溯源）。"""

    def setUp(self):
        super().setUp()
        _make_git_project(self.root, self.spec)
        # archive_spec 要求 STATE.md 有该条目（终态防御校验）
        (self.root / ".fenix").mkdir(exist_ok=True)
        (self.root / ".fenix" / "STATE.md").write_text(
            "# Fenix Project State\n\n## Specs\n\n"
            f"### {self.spec}\n- status: pushed\n"
            "- updated: 2026-01-01T00:00:00+00:00\n\n",
            encoding="utf-8",
        )
        _git(self.root, "add", "--", ".")
        _git(self.root, "commit", "-q", "-m", "knowledge")


class TestArchiveSpecRewritePass(_ArchiveIntegrationBase):
    """task 3.2/3.4：archive_spec（daemon 自动归档主线经此）改写接线。"""

    def test_archive_rewrites_and_commits_together(self):
        from core.dashboard.data.spec_archive import archive_spec

        result = archive_spec(self.root, self.spec)
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["committed"], result)
        arch = self._archive_name()
        # 改写落库：知识页指向实际归档目录
        text = self.page.read_text(encoding="utf-8")
        self.assertIn(f"spec/archive/{arch}", text)
        self.assertNotIn(f"spec/changes/{self.spec}", text)
        # 同一 [fenix] archive: 提交：归档两侧 + 知识页一并入库
        subject = _git(self.root, "log", "-1", "--format=%s").stdout.strip()
        self.assertEqual(subject, f"[fenix] archive: {self.spec} 归档入库")
        touched = {
            ln.strip()
            for ln in _git(self.root, "show", "--name-only", "--no-renames", "--format=").stdout.splitlines()
            if ln.strip()
        }
        self.assertIn(f"spec/archive/{arch}/proposal.md", touched)
        self.assertIn(
            "spec/knowledge/domains/pickup/scheduled-spec-pickup.md", touched
        )
        # 归档后链接门两态收敛：校验零违规
        self.assertEqual(validate_knowledge(self.root), [])

    def test_rewrite_failure_fail_open_archive_proceeds(self):
        """改写异常 → 归档照常完成 + 告警留痕（fail-open，不产生半提交）。"""
        import core.knowledge as kn
        from core.dashboard.data.spec_archive import archive_spec

        with mock.patch.object(
            kn,
            "rewrite_source_links_to_archive",
            side_effect=OSError("knowledge 不可写"),
        ):
            result = archive_spec(self.root, self.spec)
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["committed"], result)
        # 归档移动照常完成
        self.assertTrue(
            (self.root / "spec" / "archive" / self._archive_name()).is_dir()
        )
        # 知识页未被改写（死链由 knowledge audit 链接门下一轮兜底暴露）
        self.assertIn(f"spec/changes/{self.spec}", self.page.read_text(encoding="utf-8"))


class TestFenixArchiveScriptRewritePass(_ArchiveIntegrationBase):
    """task 3.2/3.4：bin/fenix_archive.py（CLI 路径）改写接线。"""

    def _script_mod(self):
        script = Path(__file__).resolve().parent.parent / "bin" / "fenix_archive.py"
        spec = importlib.util.spec_from_file_location("fenix_archive_mod_mdt", script)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_cli_archive_rewrites_and_commits_together(self):
        mod = self._script_mod()
        result = mod.archive_change(self.root, self.spec)
        self.assertTrue(result.get("committed"), result)
        self.assertNotIn("rewrite_warning", result)
        arch = self._archive_name()
        self.assertIn(f"spec/archive/{arch}", self.page.read_text(encoding="utf-8"))
        touched = {
            ln.strip()
            for ln in _git(self.root, "show", "--name-only", "--no-renames", "--format=").stdout.splitlines()
            if ln.strip()
        }
        self.assertIn(
            "spec/knowledge/domains/pickup/scheduled-spec-pickup.md", touched
        )

    def test_cli_rewrite_failure_fail_open(self):
        import core.knowledge as kn

        mod = self._script_mod()
        with mock.patch.object(
            kn,
            "rewrite_source_links_to_archive",
            side_effect=OSError("knowledge 不可写"),
        ):
            result = mod.archive_change(self.root, self.spec)
        self.assertTrue(result.get("committed"), result)
        self.assertIn("rewrite_warning", result)  # 告警留痕
        self.assertIn(
            f"spec/changes/{self.spec}", self.page.read_text(encoding="utf-8")
        )


class TestLinkGateTwoState(RewriteTestBase):
    """task 3.3/3.4：链接门两态等价（validate_knowledge 与 audit 零违规）。"""

    def _audit_scan(self):
        """run_audit 同款扫描装配：页扫描 + ADR 扫描（_apply_mechanical 入参）。"""
        from core.knowledge_audit import _scan_adrs, _scan_pages

        scan = _scan_pages(self.root)
        scan["adr"] = _scan_adrs(self.root)
        return scan

    def test_changes_state_validate_and_audit_clean(self):
        """push 态：链接/sources 指向 changes/（目录在盘）→ 两道门均零违规。"""
        self.assertEqual(validate_knowledge(self.root), [])
        scan = self._audit_scan()
        self.assertEqual(scan["dangling"], [])
        self.assertEqual(scan["dangling_suspect"], [])

    def test_audit_mechanical_keeps_changes_sources(self):
        """audit 机械自修不得误删 changes 态 sources（两态等价锁定）。"""
        from core.knowledge_audit import _apply_mechanical

        scan = self._audit_scan()
        fixed, manual, rewritten, cats = _apply_mechanical(self.root, scan)
        self.assertEqual(fixed, [])
        self.assertNotIn(
            "spec/knowledge/domains/pickup/scheduled-spec-pickup.md", rewritten
        )
        text = self.page.read_text(encoding="utf-8")
        self.assertIn(f"sources=spec/changes/{self.spec}", text)

    def test_after_rewrite_both_gates_still_clean(self):
        """归档改写 pass 后（archive 态）：两道门同样零违规（改写不改坏）。"""
        (self.root / "spec" / "archive" / self._archive_name()).mkdir(parents=True)
        rewrite_source_links_to_archive(self.root, self.spec, self._archive_name())
        self.assertEqual(validate_knowledge(self.root), [])
        scan = self._audit_scan()
        self.assertEqual(scan["dangling"], [])


if __name__ == "__main__":
    unittest.main()
