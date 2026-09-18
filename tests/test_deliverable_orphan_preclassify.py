"""deliverable-dispute-orphan-preclassify 回归测试。

覆盖（spec.md「回归测试」六个 Scenario + 边界用例）：

1. (3.1) kind: new 三方（规则 1/3）零引用 → 机械删除 + 审计留痕 + spec 不 blocked
2. (3.2) 存在任一引用（源码/任务清单）→ 非孤儿 → 维持 blocked 待人工（fallback）
3. (3.3) kind: modify 规则 2 命中（路径历史存在过）→ 非孤儿，维持人工裁决；
         kind: delete → 不参与预分类
4. (3.4) 排除面用例：仅 .fenix 记账面（todo.md/admin 记录）文本提及 → 仍判孤儿
         （观测面不算引用）；另证负向 pathspec 生效——排除面之外的 tracked 文件
         提及 → 非孤儿（若 pathspec 误写成包含语义则本用例必失败，防「恒零命中」回归）
5. (3.5) lint_declared 孤儿检查：kind: new 孤儿拒绝晋升、正常声明放行、
         basename 多命中放行
6. (3.6) 续走契约：删除后重跑守卫全清 → spec 置 implementing 且放行 merge
         （不被 merge 指纹熔断）；删除后主树 tasks.md 已提交（merge-back 无
         dirty 死锁）；重跑后仍有非异议缺件 → 交既有终审；判定异常 → 回退
         blocked 待人工
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.deliverables import (
    is_orphan_declaration,
    lint_declared,
    remove_declared_entry,
)
from core.pm_engine import PMEngine
from core.pm_engine.dispatch import Dispatcher
from core.state_machine import StateMachine
from core.agent_runner import AgentRunResult


def _git(root: Path, *args, check=True):
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result


# ── 纯函数夹具（is_orphan_declaration / remove_declared_entry / lint_declared）──

class _GitRepoFixture(unittest.TestCase):
    """临时 git 仓库夹具（孤儿判定需要真实 git 仓库以运行 git grep / git log）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.pr = Path(self.tmpdir) / "repo"
        self.pr.mkdir(parents=True, exist_ok=True)
        _git(self.pr, "init", "-q")
        _git(self.pr, "config", "user.email", "test@fenix.local")
        _git(self.pr, "config", "user.name", "Fenix Test")
        _git(self.pr, "config", "commit.gpgsign", "false")
        (self.pr / ".gitignore").write_text(
            "dist/\n.history/\n", encoding="utf-8",
        )
        # 基础 tracked 文件（供源码面引用 / basename 匹配用）
        (self.pr / "core").mkdir(parents=True, exist_ok=True)
        (self.pr / "core" / "data.py").write_text("x", encoding="utf-8")
        _git(self.pr, "add", "-A")
        _git(self.pr, "commit", "-q", "-m", "base")
        self.spec_dir = self.pr / "spec" / "changes" / "demo"
        self.spec_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def write_tasks_md(self, yaml_block: str,
                       task_lines: str = "- [ ] 1.1 do it"):
        (self.spec_dir / "tasks.md").write_text(
            "# Tasks\n\n## Deliverables\n\n```yaml\n"
            + yaml_block + "```\n\n## 1. x\n\n" + task_lines + "\n",
            encoding="utf-8",
        )


# ── 调度器夹具（_preclassify_orphan via Dispatcher，含真实 git 仓库）─────────

class _OrphanDispatchFixture(unittest.TestCase):
    """真实 git 仓库 + StateMachine + mock runner，驱动 _preclassify_orphan。

    与 test_deliverable_declaration_premechanize._GuardPreclassifyFixture 同构：
    真实 git 仓库（git grep / git log 需要）、真实 Dispatcher（VAdjudicationMixin
    MRO 命中）、mock runner + worktree_manager（守卫 gate 重跑可控）。
    """

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.project_root = self.tmpdir / "repo"
        self.project_root.mkdir(parents=True, exist_ok=True)
        _git(self.project_root, "init", "-q")
        _git(self.project_root, "config", "user.email", "test@fenix.local")
        _git(self.project_root, "config", "user.name", "Fenix Test")
        _git(self.project_root, "config", "commit.gpgsign", "false")
        (self.project_root / ".gitignore").write_text(
            "dist/\n.history/\n", encoding="utf-8",
        )
        (self.project_root / ".fenix").mkdir(exist_ok=True)
        # 基础 tracked 文件
        (self.project_root / "core").mkdir(parents=True, exist_ok=True)
        (self.project_root / "core" / "data.py").write_text("x", encoding="utf-8")
        _git(self.project_root, "add", "-A")
        _git(self.project_root, "commit", "-q", "-m", "base")
        self.logger = mock.MagicMock()
        self.sm = StateMachine(
            self.project_root / ".fenix" / "STATE.md", self.logger,
        )
        self.runner = mock.MagicMock()
        self.runner.worktree_manager = mock.MagicMock()
        self.config = {}
        self.engine = PMEngine(
            self.sm, self.runner, self.config, self.project_root, self.logger,
        )
        self.dispatcher = Dispatcher(self.engine)
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.transition("s1", "ready")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def write_spec_dir(self, yaml_block: str,
                       task_lines: str = "- [ ] 1.1 do it"):
        spec_dir = self.project_root / "spec" / "changes" / "s1"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "tasks.md").write_text(
            "# Tasks\n\n## Deliverables\n\n```yaml\n"
            + yaml_block + "```\n\n## 1. x\n\n" + task_lines + "\n",
            encoding="utf-8",
        )
        return spec_dir

    def make_result(self, branch="fenix/s1", run_id="impl-s1-1-a1"):
        return AgentRunResult(
            run_id, "s1", "implementer",
            success=True, duration_seconds=1.0, branch=branch,
        )

    def _stub_gate_rerun(self, remaining=None):
        """mock 守卫 gate 重跑：remaining 为重跑后的缺件列表（空=全清）。"""
        self.engine._verification._deliverable_gate_missing = mock.MagicMock(
            return_value=remaining or [],
        )


# ══════════════════════════════════════════════════════════════════════════════
# TestOrphanDetection：is_orphan_declaration 纯函数判定
# ══════════════════════════════════════════════════════════════════════════════

class TestOrphanDetection(_GitRepoFixture):
    """规则 1/2/3 合成判定：按 kind 分化的孤儿声明检测。"""

    def test_new_no_refs_is_orphan(self):
        """3.1 核心用例：kind: new，规则 1/3 零引用 → 孤儿。"""
        self.write_tasks_md("- path: tests/orphan_file.py\n  kind: new\n")
        oc = is_orphan_declaration(
            self.pr, "demo", {"path": "tests/orphan_file.py", "kind": "new"},
            self.spec_dir,
        )
        self.assertTrue(oc["orphan"], f"应判定为孤儿: {oc['evidence']}")
        ev = oc["evidence"]
        self.assertIn("git_grep", ev)
        self.assertFalse(ev["git_grep"].get("hit", True))

    def test_new_task_mentions_full_path_not_orphan(self):
        """3.2 用例：任务行提及全路径 → 非孤儿。"""
        self.write_tasks_md(
            "- path: tests/target.py\n  kind: new\n",
            task_lines="- [ ] 1.1 实现 tests/target.py 文件\n",
        )
        oc = is_orphan_declaration(
            self.pr, "demo", {"path": "tests/target.py", "kind": "new"},
            self.spec_dir,
        )
        self.assertFalse(oc["orphan"], f"任务行提及全路径不应判定孤儿: {oc['evidence']}")
        self.assertTrue(len(oc["evidence"].get("task_lines", [])) >= 1)

    def test_new_task_mentions_basename_not_orphan(self):
        """3.2 边界：任务行仅提及 basename → 非孤儿（basename 计入规则 3）。"""
        self.write_tasks_md(
            "- path: core/pm_engine/ArchitectPanel.tsx\n  kind: new\n",
            task_lines="- [ ] 1.1 新增 ArchitectPanel.tsx 文件\n",
        )
        oc = is_orphan_declaration(
            self.pr, "demo",
            {"path": "core/pm_engine/ArchitectPanel.tsx", "kind": "new"},
            self.spec_dir,
        )
        self.assertFalse(oc["orphan"], f"basename 提及不应判定孤儿: {oc['evidence']}")
        self.assertTrue(len(oc["evidence"].get("task_lines", [])) >= 1)

    def test_new_source_ref_in_tracked_file_not_orphan(self):
        """3.2 用例：源码面（排除观测面外）tracked 文件引用 → 非孤儿。"""
        self.write_tasks_md("- path: tests/real_ref.py\n  kind: new\n")
        # tracked 源码文件引用（排除面外 → 非零命中）
        (self.pr / "core" / "usage.py").write_text(
            "# referencing tests/real_ref.py (literal path)\n", encoding="utf-8",
        )
        _git(self.pr, "add", "-A")
        _git(self.pr, "commit", "-q", "-m", "ref")
        oc = is_orphan_declaration(
            self.pr, "demo", {"path": "tests/real_ref.py", "kind": "new"},
            self.spec_dir,
        )
        self.assertFalse(oc["orphan"], f"源码面引用不应判定孤儿: {oc['evidence']}")
        self.assertTrue(oc["evidence"].get("git_grep", {}).get("hit", False))

    def test_new_gitignored_path_not_preclassified(self):
        """gitignored 路径不参与孤儿判定（design 边界：运行时产物路径 → 走人工）。"""
        self.write_tasks_md("- path: dist/index.html\n  kind: new\n")
        oc = is_orphan_declaration(
            self.pr, "demo", {"path": "dist/index.html", "kind": "new"},
            self.spec_dir,
        )
        self.assertFalse(oc["orphan"], "gitignored 路径不应参与孤儿判定")
        self.assertEqual(oc["evidence"].get("skipped"), "gitignored-or-outside-root")

    def test_new_outside_root_path_not_preclassified(self):
        """仓库外路径不参与孤儿判定（design 边界）。"""
        self.write_tasks_md("- path: ~/configs/secret.yaml\n  kind: new\n")
        oc = is_orphan_declaration(
            self.pr, "demo",
            {"path": "~/configs/secret.yaml", "kind": "new"},
            self.spec_dir,
        )
        self.assertFalse(oc["orphan"], "仓库外路径不应参与孤儿判定")
        self.assertEqual(oc["evidence"].get("skipped"), "gitignored-or-outside-root")

    def test_modify_history_hit_not_orphan(self):
        """3.3 用例：kind: modify，规则 2 命中（路径历史存在过）→ 非孤儿。"""
        # 写入 + 提交 → 删除（路径有历史记录）
        (self.pr / "core" / "legacy.py").write_text("x", encoding="utf-8")
        _git(self.pr, "add", "-A")
        _git(self.pr, "commit", "-q", "-m", "add legacy")
        _git(self.pr, "rm", "-f", "core/legacy.py")
        _git(self.pr, "commit", "-q", "-m", "del legacy")
        self.write_tasks_md("- path: core/legacy.py\n  kind: modify\n")
        oc = is_orphan_declaration(
            self.pr, "demo",
            {"path": "core/legacy.py", "kind": "modify"},
            self.spec_dir,
        )
        self.assertFalse(oc["orphan"], f"历史命中不应判定孤儿: {oc['evidence']}")
        self.assertTrue(oc["evidence"].get("git_log", {}).get("hit", False))

    def test_modify_no_history_is_orphan(self):
        """3.3 边界：kind: modify，规则 2 零命中 → 孤儿。"""
        self.write_tasks_md("- path: core/never_existed.py\n  kind: modify\n")
        oc = is_orphan_declaration(
            self.pr, "demo",
            {"path": "core/never_existed.py", "kind": "modify"},
            self.spec_dir,
        )
        self.assertTrue(oc["orphan"], "无历史 modify 不应放行")

    def test_delete_never_preclassified(self):
        """3.3 用例：kind: delete → 不参与孤儿预分类。"""
        self.write_tasks_md("- path: core/data.py\n  kind: delete\n")
        oc = is_orphan_declaration(
            self.pr, "demo",
            {"path": "core/data.py", "kind": "delete"},
            self.spec_dir,
        )
        self.assertFalse(oc["orphan"], "delete 不应参与孤儿判定")


# ══════════════════════════════════════════════════════════════════════════════
# TestExclusionSurface：排除面与负向 pathspec 生效验证
# ══════════════════════════════════════════════════════════════════════════════

class TestExclusionSurface(_GitRepoFixture):
    """3.4 排除面用例：观测面（.fenix）命中 → 仍判孤儿；引用面外 tracked 文件
    命中 → 非孤儿（防「恒零命中」回归——pathspec 误写成包含语义时本用例必失败）。
    """

    def test_fenix_accounting_mention_still_orphan(self):
        """仅 .fenix 记账面（todo.md）提及路径 → 仍判孤儿。"""
        self.write_tasks_md("- path: tests/orphan_file.py\n  kind: new\n")
        # .fenix/ 在排除面内，不应被计为引用
        (self.pr / ".fenix").mkdir(exist_ok=True)
        (self.pr / ".fenix" / "todo.md").write_text(
            "记录 tests/orphan_file.py 是孤儿声明\n", encoding="utf-8",
        )
        _git(self.pr, "add", "-A")
        _git(self.pr, "commit", "-q", "-m", "fenix mention")
        oc = is_orphan_declaration(
            self.pr, "demo",
            {"path": "tests/orphan_file.py", "kind": "new"},
            self.spec_dir,
        )
        self.assertTrue(oc["orphan"], ".fenix 记账面命中不应影响孤儿判定")

    def test_tracked_file_outside_exclusion_not_orphan(self):
        """排除面外 tracked 文件引用 → 非孤儿（防「恒零命中」回归）。

        若 git grep 负向 pathspec 误写为包含语义（-- 'tests/x/**' 而非
        ':!tests/x/**'），则 git grep 仅在 tests/x/** 面搜索，外面的 tracked
        文件引用无法命中 → 恒零命中 → 本用例将误报孤儿（失败）。
        """
        self.write_tasks_md("- path: tests/real_ref.py\n  kind: new\n")
        (self.pr / "src").mkdir(parents=True, exist_ok=True)
        (self.pr / "src" / "consumer.py").write_text(
            "# referencing tests/real_ref.py (tracked consumer)\n", encoding="utf-8",
        )
        _git(self.pr, "add", "-A")
        _git(self.pr, "commit", "-q", "-m", "tracked ref")
        oc = is_orphan_declaration(
            self.pr, "demo",
            {"path": "tests/real_ref.py", "kind": "new"},
            self.spec_dir,
        )
        self.assertFalse(
            oc["orphan"],
            "排除面外 tracked 文件引用不应判孤儿（pathspec 负向 magic 验证）",
        )
        self.assertTrue(oc["evidence"].get("git_grep", {}).get("hit", False))

    def test_exclusion_spec_dir_self_reference_not_counted(self):
        """声明面（spec/changes/<本 spec>/**）自引用不计入引用面。"""
        self.write_tasks_md("- path: tests/self_ref.py\n  kind: new\n")
        # tasks.md 自身的声明行不算引用——排除面生效
        oc = is_orphan_declaration(
            self.pr, "demo",
            {"path": "tests/self_ref.py", "kind": "new"},
            self.spec_dir,
        )
        # 仅 spec 自身存在声明，外面无引用 → 孤儿
        self.assertTrue(oc["orphan"], "声明自引用应被排除面过滤")

    def test_history_exclusion_pathspec_not_hurts_non_orphan(self):
        """历史判据路径（git log --all -- <path>）不受排除面影响。"""
        # 写入 + 提交（历史记录存在）但不被 git grep 命中 → modify 规则 2 命中 → 非孤儿
        (self.pr / "core" / "vanished.py").write_text("x", encoding="utf-8")
        _git(self.pr, "add", "-A")
        _git(self.pr, "commit", "-q", "-m", "add then remove")
        _git(self.pr, "rm", "-f", "core/vanished.py")
        _git(self.pr, "commit", "-q", "-m", "remove vanished")
        self.write_tasks_md("- path: core/vanished.py\n  kind: modify\n")
        oc = is_orphan_declaration(
            self.pr, "demo",
            {"path": "core/vanished.py", "kind": "modify"},
            self.spec_dir,
        )
        self.assertFalse(
            oc["orphan"],
            "历史判据不受排除面影响——历史命中即非孤儿",
        )


# ══════════════════════════════════════════════════════════════════════════════
# TestRemoveDeclaredEntry：机械删除声明条目
# ══════════════════════════════════════════════════════════════════════════════

class TestRemoveDeclaredEntry(_GitRepoFixture):
    """机械删除 tasks.md 声明段 path+kind 两行（其余内容不动）。"""

    def test_removes_path_and_kind_lines_preserves_rest(self):
        """删除仅移除目标条目 path+kind 两行，保留分组/任务行等内容。"""
        self.write_tasks_md(
            "- path: tests/orphan_a.py\n  kind: new\n"
            "- path: core/data.py\n  kind: modify\n",
            task_lines="- [ ] 1.1 do something\n- [ ] 1.2 do another thing\n",
        )
        diff = remove_declared_entry(self.spec_dir, "tests/orphan_a.py")
        text = (self.spec_dir / "tasks.md").read_text(encoding="utf-8")
        self.assertNotIn("tests/orphan_a.py", text, "orphan 条目应被删除")
        self.assertIn("core/data.py", text, "正常条目应被保留")
        self.assertIn("kind: modify", text)
        self.assertIn("- [ ] 1.1 do something", text, "任务行应被保留")
        self.assertIn("## 1. x", text, "分组标题应被保留")
        self.assertIn("tests/orphan_a.py", diff["before"], "before 应含被删条目")
        self.assertNotIn("tests/orphan_a.py", diff["after"], "after 不含被删条目")

    def test_removes_exactly_one_entry_not_multi(self):
        """多条目声明只删除目标，不影响同名 basename 不同目录的条目。"""
        self.write_tasks_md(
            "- path: core/old/ConfigPanel.tsx\n  kind: new\n"
            "- path: core/new/ConfigPanel.tsx\n  kind: new\n",
        )
        diff = remove_declared_entry(self.spec_dir, "core/old/ConfigPanel.tsx")
        text = (self.spec_dir / "tasks.md").read_text(encoding="utf-8")
        self.assertNotIn("core/old/ConfigPanel.tsx", text)
        self.assertIn("core/new/ConfigPanel.tsx", text, "另一条不应受影响")


# ══════════════════════════════════════════════════════════════════════════════
# TestPreclassifyOrphan：_preclassify_orphan 调度器集成
# ══════════════════════════════════════════════════════════════════════════════

class TestPreclassifyOrphan(_OrphanDispatchFixture):
    """3.1/3.2/3.3/3.6：_preclassify_orphan 裁决行为回归。"""

    def test_orphan_new_deleted_gate_clear_proceed(self):
        """3.1 + 3.6 核心路径：kind: new 孤儿 → 声明删除 → 审计 → gate 全清 → proceed。"""
        self.write_spec_dir(
            "- path: tests/orphan_file.py\n  kind: new\n",
        )
        result = self.make_result()
        missing = [{"path": "tests/orphan_file.py", "kind": "new", "violation": "missing"}]
        disputed = ["tests/orphan_file.py"]
        impl_result = {
            "findings": [
                {
                    "type": "deliverable-dispute",
                    "element": "tests/orphan_file.py",
                    "current": "不存在且无引用",
                    "suggestion": "孤儿声明，建议删除",
                }
            ],
        }
        self._stub_gate_rerun(remaining=[])
        outcome = self.dispatcher._preclassify_orphan(
            "s1", result, impl_result, disputed, missing,
        )
        self.assertEqual(outcome["action"], "proceed", f"孤儿全清应放行: {outcome}")
        # tasks.md 声明条目已删除
        text = (
            self.project_root / "spec" / "changes" / "s1" / "tasks.md"
        ).read_text(encoding="utf-8")
        self.assertNotIn("tests/orphan_file.py", text)
        # spec 状态已置 implementing（gate 全清分支设定）
        entry = self.sm.read_one("s1")
        self.assertEqual(entry["status"], "implementing")
        self.assertIsNone(entry.get("error"))

    def test_orphan_deleted_tasks_committed(self):
        """3.6 用例：删除后主树 tasks.md 已提交（merge-back 无 dirty 死锁）。"""
        self.write_spec_dir(
            "- path: tests/orphan_commit.py\n  kind: new\n",
        )
        result = self.make_result()
        missing = [{"path": "tests/orphan_commit.py", "kind": "new", "violation": "missing"}]
        disputed = ["tests/orphan_commit.py"]
        self._stub_gate_rerun(remaining=[])
        self.dispatcher._preclassify_orphan(
            "s1", result, {}, disputed, missing,
        )
        # tasks.md 改动已被提交（git log 路径限定命中）——merge-back 的 autostash
        # 显式排除 spec/changes，残留 dirty 会让「主树改了 tasks.md + 实现分支也
        # 改了 tasks.md」的 merge 被 git 拒绝（fix-merge-back-deadlock）。
        proc = _git(
            self.project_root,
            "log", "--oneline", "-1", "--", "spec/changes/s1/tasks.md",
            check=False,
        )
        self.assertEqual(
            proc.returncode, 0, "tasks.md 应已被提交（防 merge-back dirty 死锁）",
        )
        self.assertIn("声明段修正", proc.stdout, "提交消息应表明声明段改写")
        # 工作区 spec 文件无未提交改动（merge-back 无 dirty）
        status = _git(
            self.project_root, "status", "--short", "--", "spec/changes/s1/tasks.md",
            check=False,
        )
        self.assertEqual(status.stdout.strip(), "", "tasks.md 不应残留未提交改动")

    def test_orphan_deleted_audit_entry(self):
        """3.1 审计留痕：DisputeAuditStore 含 orphan-preclassify verdict。"""
        self.write_spec_dir(
            "- path: tests/orphan_audit.py\n  kind: new\n",
        )
        result = self.make_result()
        missing = [{"path": "tests/orphan_audit.py", "kind": "new", "violation": "missing"}]
        self._stub_gate_rerun(remaining=[])
        self.dispatcher._preclassify_orphan(
            "s1", result, {}, ["tests/orphan_audit.py"], missing,
        )
        # 审计文件存在且含 orphan-preclassify 条目
        audit_path = self.project_root / ".fenix" / "dispute_audits.jsonl"
        self.assertTrue(audit_path.exists(), "dispute_audits.jsonl 应被创建")
        with open(audit_path, encoding="utf-8") as f:
            records = [json.loads(ln) for ln in f if ln.strip()]
        orphan_records = [
            r for r in records
            if any(
                v.get("verdict") == "orphan-preclassify"
                for v in r.get("verdicts", [])
            )
        ]
        self.assertTrue(
            len(orphan_records) >= 1,
            f"应至少有一条 orphan-preclassify 审计记录，实际: {records}",
        )
        v0 = orphan_records[0]["verdicts"][0]
        self.assertEqual(v0["element"], "tests/orphan_audit.py")
        self.assertEqual(v0["verdict"], "orphan-preclassify")
        self.assertIn("orphan-preclassify:", v0.get("reasoning", ""))

    def test_not_orphan_source_ref_fallback(self):
        """3.2 用例：源码面引用存在 → 非孤儿 → fallback（调用方维持 blocked 待人工）。"""
        self.write_spec_dir(
            "- path: tests/real_ref.py\n  kind: new\n",
        )
        (self.project_root / "core" / "usage.py").write_text(
            "# referencing tests/real_ref.py (tracked ref)\n", encoding="utf-8",
        )
        _git(self.project_root, "add", "-A")
        _git(self.project_root, "commit", "-q", "-m", "ref")
        result = self.make_result()
        missing = [{"path": "tests/real_ref.py", "kind": "new", "violation": "missing"}]
        outcome = self.dispatcher._preclassify_orphan(
            "s1", result, {}, ["tests/real_ref.py"], missing,
        )
        # fallback → 调用方应回退 blocked（保留原始 disputed 给人工）
        self.assertEqual(
            outcome["action"], "fallback",
            "源码面引用存在应 fallback 到 blocked 待人工",
        )
        # tasks.md 声明未被删除（不误删真实交付物）
        text = (
            self.project_root / "spec" / "changes" / "s1" / "tasks.md"
        ).read_text(encoding="utf-8")
        self.assertIn("tests/real_ref.py", text)

    def test_not_orphan_task_mention_fallback(self):
        """3.2 用例：任务行提及全路径 → 非孤儿 → fallback。"""
        self.write_spec_dir(
            "- path: tests/mentioned.py\n  kind: new\n",
            task_lines="- [ ] 1.1 新增 tests/mentioned.py 文件\n",
        )
        result = self.make_result()
        missing = [{"path": "tests/mentioned.py", "kind": "new", "violation": "missing"}]
        outcome = self.dispatcher._preclassify_orphan(
            "s1", result, {}, ["tests/mentioned.py"], missing,
        )
        self.assertEqual(outcome["action"], "fallback")

    def test_modify_history_hit_fallback(self):
        """3.3 用例：kind: modify 路径历史命中 → 非孤儿 → fallback。"""
        (self.project_root / "core" / "legacy.py").write_text("x", encoding="utf-8")
        _git(self.project_root, "add", "-A")
        _git(self.project_root, "commit", "-q", "-m", "add")
        _git(self.project_root, "rm", "-f", "core/legacy.py")
        _git(self.project_root, "commit", "-q", "-m", "rm")
        self.write_spec_dir("- path: core/legacy.py\n  kind: modify\n")
        result = self.make_result()
        missing = [{"path": "core/legacy.py", "kind": "modify", "violation": "missing"}]
        outcome = self.dispatcher._preclassify_orphan(
            "s1", result, {}, ["core/legacy.py"], missing,
        )
        self.assertEqual(
            outcome["action"], "fallback",
            "modify 历史命中应 fallback 到人工裁决",
        )

    def test_delete_not_participating_fallback(self):
        """3.3 用例：kind: delete → 不参与孤儿预分类 → fallback。"""
        self.write_spec_dir("- path: core/data.py\n  kind: delete\n")
        result = self.make_result()
        missing = [{"path": "core/data.py", "kind": "delete", "violation": "undeleted"}]
        outcome = self.dispatcher._preclassify_orphan(
            "s1", result, {}, ["core/data.py"], missing,
        )
        self.assertEqual(
            outcome["action"], "fallback",
            "delete 不应参与孤儿预分类",
        )


# ══════════════════════════════════════════════════════════════════════════════
# TestExclusionSurfaceDispatch：排除面在调度器路径的端到端验证
# ══════════════════════════════════════════════════════════════════════════════

class TestExclusionSurfaceDispatch(_OrphanDispatchFixture):
    """3.4 排除面用例在 _preclassify_orphan 路径的端到端行为。"""

    def test_fenix_only_mention_still_orphan_deleted(self):
        """3.4 用例：仅 .fenix 记账面提及 → 仍判孤儿 → 声明删除 + gate 清 → proceed。"""
        self.write_spec_dir(
            "- path: tests/fenix_only.py\n  kind: new\n",
        )
        # .fenix 排除面内文件提及（观测面不算引用）
        (self.project_root / ".fenix").mkdir(exist_ok=True)
        (self.project_root / ".fenix" / "todo.md").write_text(
            "tests/fenix_only.py 是孤儿声明\n", encoding="utf-8",
        )
        _git(self.project_root, "add", "-A")
        _git(self.project_root, "commit", "-q", "-m", "fenix todo")
        result = self.make_result()
        missing = [{"path": "tests/fenix_only.py", "kind": "new", "violation": "missing"}]
        self._stub_gate_rerun(remaining=[])
        outcome = self.dispatcher._preclassify_orphan(
            "s1", result, {}, ["tests/fenix_only.py"], missing,
        )
        self.assertEqual(
            outcome["action"], "proceed",
            ".fenix 排除面提及仍应判定孤儿并删除放行",
        )

    def test_non_excluded_file_mention_not_orphan(self):
        """3.4 验证负向 pathspec：排除面外 tracked 文件引用 → 非孤儿。

        若 pathspec 误写成包含语义（-- 'tests/x/**'）而非排除语义（
        ':!tests/x/**'），git grep 仅在排除面上搜索，外部引用无法命中 →
        恒零命中 → 误判孤儿（失败）。
        """
        self.write_spec_dir(
            "- path: tests/pattern_ref.py\n  kind: new\n",
        )
        (self.project_root / "src").mkdir(parents=True, exist_ok=True)
        (self.project_root / "src" / "main.py").write_text(
            "# 反例引用 tests/pattern_ref.py (tracked)\n", encoding="utf-8",
        )
        _git(self.project_root, "add", "-A")
        _git(self.project_root, "commit", "-q", "-m", "anti-pattern ref")
        result = self.make_result()
        missing = [{"path": "tests/pattern_ref.py", "kind": "new", "violation": "missing"}]
        outcome = self.dispatcher._preclassify_orphan(
            "s1", result, {}, ["tests/pattern_ref.py"], missing,
        )
        self.assertEqual(
            outcome["action"], "fallback",
            "排除面外 tracked 文件引用应判非孤儿（负向 pathspec 生效验证）",
        )


# ══════════════════════════════════════════════════════════════════════════════
# TestLintDeclaredOrphanCheck：lint_declared 的孤儿检查（3.5）
# ══════════════════════════════════════════════════════════════════════════════

class TestLintDeclaredOrphanCheck(_GitRepoFixture):
    """3.5 lint_declared 孤儿检查：晋升期拦截 kind: new 孤儿声明。"""

    def test_orphan_blocks_promotion(self):
        """3.5 用例：kind: new 孤儿（源码/任务清单皆零命中）→ 拒绝晋升。"""
        self.write_tasks_md("- path: tests/orphan_lint.py\n  kind: new\n")
        violations = lint_declared(self.spec_dir, self.pr)
        self.assertEqual(
            len(violations), 1,
            f"孤儿声明应被拒绝晋升，实际: {violations}",
        )
        self.assertIn("孤儿声明", violations[0])
        self.assertIn("tests/orphan_lint.py", violations[0])
        self.assertIn("git grep", violations[0], "违规消息应包含源码面证据")

    def test_normal_declaration_passes(self):
        """3.5 用例：kind: new 正常声明（任务行提及）→ 放行晋升。"""
        self.write_tasks_md(
            "- path: tests/normal_declare.py\n  kind: new\n",
            task_lines="- [ ] 1.1 新增 tests/normal_declare.py\n",
        )
        violations = lint_declared(self.spec_dir, self.pr)
        self.assertEqual(violations, [], "正常声明应被放行")

    def test_basename_unique_hit_passes(self):
        """3.5 用例：basename 唯一命中 → 规则 4 疑似笔误拦截（非孤儿检查覆盖）。"""
        # 主树存在 core/pm_engine/verification.py（basename 与声明 core/verification.py
        # 唯一命中）→ 规则 4 判疑似笔误（孤儿检查不触发，basename 命中已由规则 4 拦）
        (self.pr / "core" / "pm_engine").mkdir(parents=True, exist_ok=True)
        (self.pr / "core" / "pm_engine" / "verification.py").write_text("x", encoding="utf-8")
        _git(self.pr, "add", "-A")
        _git(self.pr, "commit", "-q", "-m", "basename hit")
        self.write_tasks_md("- path: core/verification.py\n  kind: new\n")
        violations = lint_declared(self.spec_dir, self.pr)
        self.assertEqual(
            len(violations), 1,
            "basename 唯一命中应由规则 4 拦截（疑似笔误）",
        )
        self.assertIn("疑似笔误", violations[0])

    def test_basename_multiple_hits_passes(self):
        """3.5 用例：basename 多命中 → 放行（语义矛盾需 LLM 裁决，lint 不拦）。"""
        # 主树存在 core/a/verification.py 与 core/b/verification.py（basename 多命中）
        # → 规则 4 fail-open 放行（孤儿检查不触发，design 与规则 4 的边界）
        (self.pr / "core" / "a").mkdir(parents=True, exist_ok=True)
        (self.pr / "core" / "a" / "verification.py").write_text("x", encoding="utf-8")
        (self.pr / "core" / "b").mkdir(parents=True, exist_ok=True)
        (self.pr / "core" / "b" / "verification.py").write_text("x", encoding="utf-8")
        _git(self.pr, "add", "-A")
        _git(self.pr, "commit", "-q", "-m", "multi basename")
        self.write_tasks_md("- path: core/verification.py\n  kind: new\n")
        violations = lint_declared(self.spec_dir, self.pr)
        self.assertEqual(
            violations, [],
            "basename 多命中应放行（语义矛盾交 LLM）",
        )


# ══════════════════════════════════════════════════════════════════════════════
# TestPreclassifyContinuationContract：续走契约（3.6）
# ══════════════════════════════════════════════════════════════════════════════

class TestPreclassifyContinuationContract(_OrphanDispatchFixture):
    """3.6 续走契约：删除后 gate 重跑行为 + 异常 fail-open。"""

    def test_rerun_still_missing_continue(self):
        """3.6 用例：重跑后仍有缺件（非孤儿争议项）→ continue + remaining。"""
        self.write_spec_dir(
            "- path: tests/orphan_a.py\n  kind: new\n"
            "- path: tests/real_target.py\n  kind: new\n",
        )
        result = self.make_result()
        missing = [
            {"path": "tests/orphan_a.py", "kind": "new", "violation": "missing"},
            {"path": "tests/real_target.py", "kind": "new", "violation": "missing"},
        ]
        # gate 重跑仍缺 real_target（非孤儿，但非本次 disputed 项——走终审）
        self._stub_gate_rerun(
            remaining=[{"path": "tests/real_target.py", "kind": "new", "violation": "missing"}],
        )
        outcome = self.dispatcher._preclassify_orphan(
            "s1", result, {},
            ["tests/orphan_a.py"],  # only orphan is disputed
            missing,
        )
        self.assertEqual(outcome["action"], "continue", f"仍有缺件应 continue: {outcome}")
        self.assertEqual(len(outcome.get("remaining_missing", [])), 1)

    def test_all_disputed_deleted_no_remaining_disputed_continue(self):
        """3.6 用例：所有 disputed 项为孤儿已删除，gate 重跑剩余非争议项 →
        continue + remaining_disputed 为空（调用方不 blocked，继续走终审）。"""
        self.write_spec_dir(
            "- path: tests/orphan_only.py\n  kind: new\n"
            "- path: tests/other_missing.py\n  kind: new\n",
        )
        result = self.make_result()
        missing = [
            {"path": "tests/orphan_only.py", "kind": "new", "violation": "missing"},
            {"path": "tests/other_missing.py", "kind": "new", "violation": "missing"},
        ]
        self._stub_gate_rerun(
            remaining=[{"path": "tests/other_missing.py", "kind": "new", "violation": "missing"}],
        )
        outcome = self.dispatcher._preclassify_orphan(
            "s1", result, {},
            ["tests/orphan_only.py"],
            missing,
        )
        self.assertEqual(outcome["action"], "continue")
        self.assertEqual(outcome["remaining_disputed"], [], "deleted orphans not in disputed")

    def test_exception_in_orphan_check_falls_back(self):
        """3.6 用例：孤儿判定异常 → 全量回退 blocked 待人工（fail-open）。"""
        self.write_spec_dir(
            "- path: tests/orphan_err.py\n  kind: new\n",
        )
        result = self.make_result()
        missing = [{"path": "tests/orphan_err.py", "kind": "new", "violation": "missing"}]
        with mock.patch(
            "core.deliverables.is_orphan_declaration",
            side_effect=RuntimeError("git is broken"),
        ):
            outcome = self.dispatcher._preclassify_orphan(
                "s1", result, {}, ["tests/orphan_err.py"], missing,
            )
        self.assertEqual(
            outcome["action"], "fallback",
            "判定异常应 fallback 到 blocked 待人工",
        )

    def test_exception_in_deletion_falls_back(self):
        """3.6 用例：删除异常 → 全量回退 blocked 待人工（fail-open）。"""
        self.write_spec_dir(
            "- path: tests/orphan_del_err.py\n  kind: new\n",
        )
        result = self.make_result()
        missing = [{"path": "tests/orphan_del_err.py", "kind": "new", "violation": "missing"}]
        with mock.patch(
            "core.deliverables.remove_declared_entry",
            side_effect=RuntimeError("disk full"),
        ):
            outcome = self.dispatcher._preclassify_orphan(
                "s1", result, {}, ["tests/orphan_del_err.py"], missing,
            )
        self.assertEqual(outcome["action"], "fallback")

    def test_gate_rerun_exception_falls_back(self):
        """3.6 用例：gate 重跑异常 → 全量回退 blocked 待人工。"""
        self.write_spec_dir(
            "- path: tests/orphan_gate_err.py\n  kind: new\n",
        )
        result = self.make_result()
        missing = [{"path": "tests/orphan_gate_err.py", "kind": "new", "violation": "missing"}]
        self.engine._verification._deliverable_gate_missing = mock.MagicMock(
            side_effect=RuntimeError("gate module broken"),
        )
        outcome = self.dispatcher._preclassify_orphan(
            "s1", result, {}, ["tests/orphan_gate_err.py"], missing,
        )
        self.assertEqual(
            outcome["action"], "fallback",
            "gate 重跑异常应 fallback 到 blocked 待人工",
        )


if __name__ == "__main__":
    unittest.main()
