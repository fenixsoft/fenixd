"""test-knowledge-e2e — 蒸馏管线端到端（add-knowledge-atlas 5.1）。

全链（真实代码路径，fake spawn 替身不触真实网关）：
构造 fixture change → shutil.move 归档 → commit_archive_move 真实挂载 →
dispatch_distill（knowledge.enabled 门控 + 归档存在性，config 缺省即 enabled）
→ DistillManager 队列/flock → spawn（fake：按 distill.md 契约写产物）→
validate_knowledge → pathspec 限定自动提交。

覆盖断言：
- dispatch_distill 被触发（result["distill"]["dispatched"]）
- 蒸馏产出经校验落盘（能力页 rev+1、规则更新、validate_knowledge 零违规）
- index/域清单同步更新（链接全部可解析）
- REMOVED 语义删规则留痕（溯源段「已随 <归档名> 废除：…」）
- ADR supersede 链（新 ADR-002 落盘、ADR-001 只标不改——git 双版本三段正文
  逐字相同、头部 status/Superseded by 变化）
- 提交信息 ``[fenix] knowledge: distill <归档名>`` 且 pathspec 限定 spec/knowledge/
- 提示词注入（模板铁律 + 归档绝对路径）

测试隔离：monkeypatch ``core.knowledge._in_pytest``（放行真实派发）与
``_MANAGER``（注入 fake spawn 的测试 manager）；本文件不 patch 会让守卫
拦截、既有套件不受影响。
"""

import os
import subprocess
import tempfile
import threading
import time
import unittest
import shutil
from datetime import date
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from unittest import mock

from core.knowledge import KNOWLEDGE_DIR, DistillManager

GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}

TODAY = date.today().isoformat()
ARCHIVE_NAME = f"{TODAY}-demo-spec"

# 既有能力页（rev1，含将被 REMOVED 废除的旧规则）
PAGE_V1 = """# 定时拣选

<!-- knowledge: capability=scheduled-spec-pickup rev=1
     sources=spec/archive/{archive_prev} -->

按周期把已完成 SPEC 拣选进归档。

## 规则

- 轮询间隔 600 秒。
- 拣选完成后立即归档提交。

## 溯源

- {today} {archive_prev} — 新建本页
"""

PAGE_V2 = """# 定时拣选

<!-- knowledge: capability=scheduled-spec-pickup rev=2
     sources=spec/archive/{archive_prev},spec/archive/{archive} -->

按周期把已完成 SPEC 拣选进归档。

## 规则

- 轮询间隔 300 秒。
- 拣选完成后立即归档提交。

## 溯源

- {today} {archive_prev} — 新建本页
- {today} {archive} — 轮询间隔调整为 300 秒；已随 {archive} 废除：轮询间隔 600 秒
"""

ADR_001 = """# ADR-001：旧提交口径

date: {today}
status: accepted

## Context

历史上下文原文。

## Decision

历史裁定原文。

## Consequences

历史后果原文。
"""

ADR_001_SUPERSEDED = ADR_001.replace(
    "status: accepted",
    "status: superseded\nSuperseded by: ADR-002(自动提交口径)",
)

ADR_002 = """# ADR-002：自动提交口径

date: {today}
status: accepted

## Context

归档事件需要即时落库。

## Decision

移动成功即 pathspec 限定提交。

## Consequences

提交粒度变细。
"""


def _git(proot: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(proot), *args],
        env=GIT_ENV, capture_output=True, text=True, timeout=60,
    )


class KnowledgeE2E(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        self.archive_prev = f"{TODAY}-seed-spec"
        self.prompts = []
        self.archive_committed = threading.Event()
        self._build_project()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ── fixture：既有真相源（rev1 + ADR-001）已入库 + 待归档 change ──
    def _build_project(self):
        (self.root / ".fenix" / "logs").mkdir(parents=True)
        # 既有真相源（模拟管线已运行过一轮）
        k = self.root / KNOWLEDGE_DIR
        (k / "domains" / "pickup").mkdir(parents=True)
        (k / "adr").mkdir()
        (k / "README.md").write_text("# 契约\n", encoding="utf-8")
        (k / "index.md").write_text(
            f"# 知识真相源\n> 最后更新：{TODAY} 15:02 UTC\n\n## 能力域\n\n"
            "| 能力域 | 简介 | 能力数量 | 更新时间 |\n"
            "| --- | --- | --- | --- |\n"
            f"| [pickup](domains/pickup/_domain.md) | 拣选 | 1 | {TODAY} 15:02 |\n",
            encoding="utf-8",
        )
        (k / "domains" / "pickup" / "_domain.md").write_text(
            f"# 拣选域\n> 最后更新：{TODAY} 15:02 UTC\n\n"
            "| 能力页 | 简介 |\n| --- | --- |\n"
            "| [定时拣选](scheduled-spec-pickup.md) | 按周期拣选 |\n",
            encoding="utf-8",
        )
        (k / "domains" / "pickup" / "scheduled-spec-pickup.md").write_text(
            PAGE_V1.format(
                archive_prev=self.archive_prev, today=TODAY
            ),
            encoding="utf-8",
        )
        (k / "adr" / "ADR-001-legacy.md").write_text(
            ADR_001.format(today=TODAY), encoding="utf-8"
        )
        (k / "adr" / "index.md").write_text(
            "- [ADR-001](ADR-001-legacy.md) accepted\n", encoding="utf-8"
        )
        (self.root / "spec" / "archive" / self.archive_prev).mkdir(
            parents=True, exist_ok=True
        )
        # 待归档 change：delta 含 MODIFIED（轮询间隔）与 REMOVED（600 秒旧规则）
        ch = self.root / "spec" / "changes" / "demo-spec"
        (ch / "specs" / "pickup").mkdir(parents=True)
        (ch / "proposal.md").write_text("# 提案：轮询间隔改 300 秒\n", encoding="utf-8")
        (ch / "design.md").write_text(
            "# 设计\n\n## Decisions\n\n- 归档移动成功即 pathspec 限定提交"
            "（跨 SPEC 架构级口径）。\n",
            encoding="utf-8",
        )
        (ch / "specs" / "pickup" / "spec.md").write_text(
            "# pickup delta\n\n"
            "## MODIFIED Requirements\n\n"
            "- 轮询间隔：600 秒 → 300 秒\n\n"
            "## REMOVED Requirements\n\n"
            "- 轮询间隔 600 秒\n",
            encoding="utf-8",
        )
        # git 基线（ADR 不可变性的对照版本）
        for cmd in (
            ["init", "-q"],
            ["config", "user.name", "t"],
            ["config", "user.email", "t@t"],
            ["add", "--", "."],
            ["commit", "-q", "-m", "init"],
        ):
            _git(self.root, *cmd)

    # ── fake spawn：扮演蒸馏 agent，读真实 delta 按契约写产物 ─────────
    def _fake_spawn(self, cmd, cwd):
        # 真实时序：claude run 耗时（分钟级）≫ 归档提交（毫秒级），蒸馏的
        # git add/commit 恒在归档提交之后；fake 瞬时完成会与主线程撞
        # index.lock（非产品缺陷，测试须布防真实时序）——等主线程受理方
        # commit_archive_move 返回后再开工。
        self.archive_committed.wait(timeout=30)
        self.prompts.append(cmd[2])
        proot = Path(cwd)
        archive = proot / "spec" / "archive" / ARCHIVE_NAME
        assert archive.is_dir(), "fake spawn 运行时归档目录必须已存在"
        delta = (archive / "specs" / "pickup" / "spec.md").read_text(encoding="utf-8")
        assert "轮询间隔 600 秒" in delta  # 原料确实可读
        k = proot / KNOWLEDGE_DIR
        # 能力页 rev+1 整体重写（规则段更新 + REMOVED 留痕）
        (k / "domains" / "pickup" / "scheduled-spec-pickup.md").write_text(
            PAGE_V2.format(
                archive_prev=self.archive_prev, archive=ARCHIVE_NAME, today=TODAY
            ),
            encoding="utf-8",
        )
        # index / 域清单同步（本轮无新增页，内容不变但随提交落库）
        (k / "adr" / "ADR-002-auto-commit.md").write_text(
            ADR_002.format(today=TODAY), encoding="utf-8"
        )
        # supersede 只标不改：ADR-001 头部两处标记
        (k / "adr" / "ADR-001-legacy.md").write_text(
            ADR_001_SUPERSEDED.format(today=TODAY), encoding="utf-8"
        )
        (k / "adr" / "index.md").write_text(
            "- [ADR-001](ADR-001-legacy.md) superseded\n"
            "- [ADR-002](ADR-002-auto-commit.md) accepted\n",
            encoding="utf-8",
        )
        return _Proc0()

    def _wait_distill_commit(self, deadline=30.0) -> bool:
        """worker 线程异步执行：有界轮询等蒸馏提交出现（或失败台账）。"""
        end = time.monotonic() + deadline
        while time.monotonic() < end:
            log = _git(self.root, "log", "-1", "--format=%s")
            if log.stdout.strip().startswith("[fenix] knowledge: distill"):
                return True
            todo = self.root / ".fenix" / "todo.md"
            if todo.is_file() and "knowledge-distill 重试" in todo.read_text(encoding="utf-8"):
                return False  # 失败已登记（快速失败路径）
            time.sleep(0.2)
        return False

    def test_archive_triggers_distill_pipeline(self):
        from core.archive_commit import commit_archive_move
        import core.knowledge as kn

        mgr = DistillManager()
        mgr._spawn = self._fake_spawn
        with mock.patch.object(kn, "_in_pytest", lambda: False), \
                mock.patch.object(kn, "_MANAGER", mgr):
            # 归档移动（真实 move + 真实挂载派发）
            archive_dir = self.root / "spec" / "archive" / ARCHIVE_NAME
            shutil.move(
                str(self.root / "spec" / "changes" / "demo-spec"), str(archive_dir)
            )
            r = commit_archive_move(self.root, "demo-spec", archive_dir)
        self.archive_committed.set()

        self.assertTrue(r["committed"], r)
        self.assertTrue(r["distill"]["dispatched"], r)
        self.assertTrue(
            self._wait_distill_commit(), "蒸馏 run 未在超时内提交成功"
        )

        # 提交信息与 pathspec 限定
        subject = _git(self.root, "log", "-1", "--format=%s").stdout.strip()
        self.assertEqual(subject, f"[fenix] knowledge: distill {ARCHIVE_NAME}")
        touched = {
            ln.strip()
            for ln in _git(self.root, "show", "--name-only", "--format=").stdout.splitlines()
            if ln.strip()
        }
        self.assertTrue(touched, "蒸馏提交无文件")
        self.assertTrue(all(t.startswith(KNOWLEDGE_DIR) for t in touched))

        # 产出落盘：rev+1、规则更新、REMOVED 留痕
        page = (
            self.root / KNOWLEDGE_DIR / "domains/pickup/scheduled-spec-pickup.md"
        ).read_text(encoding="utf-8")
        self.assertIn("rev=2", page)
        self.assertIn("轮询间隔 300 秒", page)
        self.assertIn(
            f"已随 {ARCHIVE_NAME} 废除：轮询间隔 600 秒", page
        )

        # index/域清单同步更新（链接全部可解析——确定性校验）
        self.assertEqual(kn.validate_knowledge(self.root), [])

        # ADR supersede 链：ADR-001 只标不改（git 双版本三段正文逐字比对）
        adr1_new = (
            self.root / KNOWLEDGE_DIR / "adr/ADR-001-legacy.md"
        ).read_text(encoding="utf-8")
        adr1_old = _git(
            self.root, "show", f"HEAD~1:{KNOWLEDGE_DIR}/adr/ADR-001-legacy.md"
        ).stdout
        split = "## Context"
        self.assertEqual(
            adr1_old.split(split, 1)[1], adr1_new.split(split, 1)[1],
            "ADR-001 三段正文被改写",
        )
        self.assertNotIn("Superseded by", adr1_old)
        self.assertIn("status: superseded", adr1_new)
        self.assertIn("Superseded by: ADR-002(自动提交口径)", adr1_new)
        self.assertTrue(
            (self.root / KNOWLEDGE_DIR / "adr/ADR-002-auto-commit.md").is_file()
        )

        # 提示词注入：模板铁律与归档绝对路径
        self.assertEqual(len(self.prompts), 1)
        self.assertIn("写路径限定", self.prompts[0])
        self.assertIn(str(self.root / "spec" / "archive" / ARCHIVE_NAME), self.prompts[0])

        # 队列排空
        self.assertEqual(mgr.pending(self.root), 0)

    def test_disabled_config_skips_dispatch(self):
        """knowledge.enabled=false：归档照常提交、蒸馏不派发。"""
        from core.archive_commit import commit_archive_move
        import core.knowledge as kn

        cfg = self.root / ".fenix" / "config.yaml"
        cfg.write_text("knowledge:\n  enabled: false\n", encoding="utf-8")

        mgr = DistillManager()
        mgr._spawn = self._fake_spawn
        with mock.patch.object(kn, "_in_pytest", lambda: False), \
                mock.patch.object(kn, "_MANAGER", mgr):
            archive_dir = self.root / "spec" / "archive" / ARCHIVE_NAME
            shutil.move(
                str(self.root / "spec" / "changes" / "demo-spec"), str(archive_dir)
            )
            r = commit_archive_move(self.root, "demo-spec", archive_dir)

        self.assertTrue(r["committed"])
        self.assertFalse(r["distill"]["dispatched"])
        self.assertEqual(r["distill"]["reason"], "disabled")
        self.assertEqual(self.prompts, [])


class _Proc0:
    returncode = 0

    def communicate(self, timeout=None):
        return "", ""


if __name__ == "__main__":
    unittest.main()
