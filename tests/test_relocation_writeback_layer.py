"""fix-relocation-writeback-layer 回归：声明修正「写回层」与守卫读取基准对齐。

覆盖（tasks 1.1 判据 / 1.4 降级 / 2.1-2.2 judge 接线 / 3.2-3.3 复检 / 4.2-4.4
凭据核销 / 5.1-5.3 复发熔断 / 6.1 六态 / 6.4 装配预演 / 7.2-7.3 解冻锚点耐久）：

核心不变量（design D1/D3）：**修正被执行 ⇔ 下一次守卫读取能看到修正**。
写主树、守卫读分支的错层（add-code-review-auto-fix 31h 事故）在此被六态
夹具锁定为不可回归。
"""

import json
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent_runner import AgentRunResult
from core.admin_store import DisputeAuditStore
from core.deliverables import (
    relocation_credential_target,
    resolve_writeback_target,
    verify_correction_readback,
)
from core.pm_engine import PMEngine
from core.state_machine import StateMachine


class _FakeLogger:
    """轻量日志捕获器：记录 (level, name, message) 供断言。"""

    def __init__(self):
        self.records = []

    def _rec(self, level, name, message, *args, **kw):
        self.records.append((level, name, str(message)))

    def info(self, name, message, *args, **kw):
        self._rec("info", name, message)

    def warning(self, name, message, *args, **kw):
        self._rec("warning", name, message)

    def error(self, name, message, *args, **kw):
        self._rec("error", name, message)

    def debug(self, name, message, *args, **kw):
        pass

    def has(self, level, fragment):
        return any(
            lvl == level and fragment in msg for lvl, _n, msg in self.records
        )


def _decl_tasks(path, kind="new"):
    """单条 deliverable 声明的 tasks.md 文本。"""
    return (
        "# Tasks\n\n## Deliverables\n\n```yaml\n"
        f"- path: {path}\n  kind: {kind}\n```\n"
        "## 1. 分组\n\n- [ ] 1.1 产出\n"
    )


class _WbFixture(unittest.TestCase):
    """真实 git 主树 + mock runner：worktree/分支/主树三层声明夹具可组合。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.project_root = self.tmpdir / "main"
        self.project_root.mkdir(parents=True)
        (self.project_root / ".fenix").mkdir(exist_ok=True)
        self.git(self.project_root, "init", "-q")
        self.git(self.project_root, "config", "user.email", "test@fenix.local")
        self.git(self.project_root, "config", "user.name", "fenix-test")
        (self.project_root / "README.md").write_text("r\n", encoding="utf-8")
        self.git(self.project_root, "add", "-A")
        self.git(self.project_root, "commit", "-qm", "init")
        # rev-list/merge-base/枚举基准分支硬编码 main——初始分支强制归一
        self.git(self.project_root, "branch", "-M", "main")
        self.logger = _FakeLogger()
        self.sm = StateMachine(
            self.project_root / ".fenix" / "STATE.md", self.logger
        )
        self.runner = mock.MagicMock()
        self.runner.worktree_manager = mock.MagicMock()
        self.engine = PMEngine(
            self.sm, self.runner, {}, self.project_root, self.logger
        )
        self.wm = self.runner.worktree_manager
        # 缺省：无在册 worktree、分支交付物全缺失（MagicMock 真值会假放行）
        self.wm.find_worktree_path.return_value = None
        self.wm.file_exists_on_branch.return_value = False

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def git(self, cwd, *args, check=True):
        r = subprocess.run(
            ["git", "-C", str(cwd)] + list(args), capture_output=True, text=True
        )
        if check and r.returncode != 0:
            raise AssertionError(f"git {args} failed: {r.stderr.strip()}")
        return r

    def seed_spec(self, name="s1", status="ready"):
        self.sm.add_spec(name, {"priority": 5})
        self.sm.transition(name, status)
        return self.sm.read_one(name)

    def write_main_tasks(self, name, text):
        p = self.project_root / "spec" / "changes" / name
        p.mkdir(parents=True, exist_ok=True)
        (p / "tasks.md").write_text(text, encoding="utf-8")
        return p

    def main_tasks_text(self, name):
        f = self.project_root / "spec" / "changes" / name / "tasks.md"
        return f.read_text(encoding="utf-8") if f.exists() else None

    def make_branch_with_tasks(self, name, text, branch=None):
        """分支携带声明（source == "branch" 态）：主树无该文件。

        add 范围限定 spec/ —— .fenix/STATE.md 是运行态文件，MUST NOT 入库
        （否则 checkout main 时 git 会清空并移除 .fenix 目录，锁文件无处创建）。
        """
        branch = branch or f"fenix/{name}-{int(time.time())}"
        self.git(self.project_root, "checkout", "-q", "-b", branch)
        p = self.project_root / "spec" / "changes" / name
        p.mkdir(parents=True, exist_ok=True)
        (p / "tasks.md").write_text(text, encoding="utf-8")
        self.git(self.project_root, "add", "spec")
        self.git(self.project_root, "commit", "-qm", f"tasks: {name}")
        self.git(self.project_root, "checkout", "-q", "main")
        return branch

    def add_file_on_branch(self, branch, rel_path, content="x\n"):
        """在既有分支 HEAD 补一个文件（模拟交付物已在分支落地）。"""
        self.git(self.project_root, "checkout", "-q", branch)
        f = self.project_root / rel_path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content, encoding="utf-8")
        self.git(self.project_root, "add", rel_path)
        self.git(self.project_root, "commit", "-qm", f"add {rel_path}")
        self.git(self.project_root, "checkout", "-q", "main")

    def make_worktree_with_tasks(self, name, text, branch=None):
        """真实 git worktree 携带声明（source == "worktree" 态）。"""
        branch = branch or f"fenix/{name}-{int(time.time())}"
        self.git(self.project_root, "branch", branch)
        wt = self.tmpdir / "wt"
        self.git(self.project_root, "worktree", "add", str(wt), branch)
        p = wt / "spec" / "changes" / name
        p.mkdir(parents=True, exist_ok=True)
        (p / "tasks.md").write_text(text, encoding="utf-8")
        return wt, branch

    def make_result(self, spec="s1", branch="fenix/s1", run_id="impl-s1-1"):
        return AgentRunResult(
            run_id, spec, "implementer",
            success=True, duration_seconds=1.0, branch=branch,
        )

    def write_judge_result(self, spec, verdicts, status="success"):
        vp = self.project_root / ".fenix" / "verify-progress" / spec
        vp.mkdir(parents=True, exist_ok=True)
        (vp / "dispute_judge_result.json").write_text(
            json.dumps({"status": status, "verdicts": verdicts},
                       ensure_ascii=False),
            encoding="utf-8",
        )

    def stub_judge_run(self, run_id="dispute-judge-1"):
        self.runner.run_dispute_judge = (
            lambda spec_name, judge_input, run_id=None: AgentRunResult(
                run_id or run_id, spec_name, "dispute-judge",
                success=True, duration_seconds=1.0,
            )
        )

    def adjudicate(self, spec, result, missing_paths):
        return self.engine._adjudicate_deliverable_missing(
            spec, result, None, missing_paths
        )

    def audit_records(self):
        return DisputeAuditStore(self.project_root).read_all()

    def branch_contains(self, branch, rel_path):
        return (
            self.git(self.project_root, "cat-file", "-e",
                     f"{branch}:{rel_path}", check=False).returncode
            == 0
        )


class TestResolveWritebackTarget(_WbFixture):
    """Task 1.1：写回层判定四态（同源原则）。"""

    def test_worktree_hit_writable(self):
        self.seed_spec()
        wt, branch = self.make_worktree_with_tasks("s1", _decl_tasks("core/a.py"))
        r = resolve_writeback_target(
            "s1", branch=branch, worktree_path=wt,
            project_root=self.project_root,
        )
        self.assertTrue(r["writable"])
        self.assertEqual(r["source"], "worktree")
        self.assertEqual(Path(r["spec_dir"]), wt / "spec" / "changes" / "s1")
        self.assertEqual(Path(r["commit_root"]), wt)

    def test_main_hit_writable(self):
        self.seed_spec()
        self.write_main_tasks("s1", _decl_tasks("core/a.py"))
        r = resolve_writeback_target(
            "s1", branch="fenix/s1-1", worktree_path=None,
            project_root=self.project_root,
        )
        self.assertTrue(r["writable"])
        self.assertEqual(r["source"], "main")
        self.assertEqual(Path(r["commit_root"]), self.project_root)

    def test_branch_hit_not_writable(self):
        """事故态：声明只在分支对象库（spec_dir is None）→ 不可写。"""
        self.seed_spec()
        branch = self.make_branch_with_tasks("s1", _decl_tasks("core/a.py"))
        r = resolve_writeback_target(
            "s1", branch=branch, worktree_path=None,
            project_root=self.project_root,
        )
        self.assertFalse(r["writable"])
        self.assertEqual(r["source"], "branch")
        self.assertIsNone(r["spec_dir"])
        self.assertIsNone(r["commit_root"])

    def test_unavailable_not_writable(self):
        self.seed_spec()
        r = resolve_writeback_target(
            "ghost", branch=None, worktree_path=None,
            project_root=self.project_root,
        )
        self.assertFalse(r["writable"])
        self.assertIsNone(r["source"])


class TestJudgeTypoWritebackLayer(_WbFixture):
    """Task 2.1/1.4/3.2/6.1：judge typo 三层落点 + 冲突降级 + 复检闭环。"""

    def _typo_verdict(self, old, new):
        return [{"element": old, "verdict": "typo", "actual_path": new,
                 "reasoning": "唯一 basename 命中", "confidence": "high"}]

    def test_worktree_hit_writes_worktree_and_commits_branch(self):
        """六态 1：有 worktree → 修正写 worktree 并提交该分支；主树不动。"""
        self.seed_spec()
        wt, branch = self.make_worktree_with_tasks(
            "s1", _decl_tasks("core/old.py"))
        self.write_main_tasks("s1", _decl_tasks("core/old.py"))
        self.wm.find_worktree_path.return_value = wt
        self.wm.file_exists_on_branch.side_effect = (
            lambda b, p: p == "core/new.py")
        self.write_judge_result("s1", self._typo_verdict(
            "core/old.py", "core/new.py"))
        self.stub_judge_run()
        result = self.make_result(branch=branch)

        outcome = self.adjudicate("s1", result, ["core/old.py"])

        self.assertEqual(outcome["action"], "proceed")
        wt_text = (wt / "spec" / "changes" / "s1" / "tasks.md").read_text(
            encoding="utf-8")
        self.assertIn("core/new.py", wt_text)
        self.assertNotIn("core/old.py", wt_text)
        # 主树不被写（落点 = worktree 命中层）
        self.assertIn("core/old.py", self.main_tasks_text("s1"))
        self.assertNotIn("core/new.py", self.main_tasks_text("s1"))
        # 提交落该 worktree 的分支（HEAD 含修正 + 提交信息可溯）
        tip = self.git(wt, "log", "-1", "--format=%s").stdout.strip()
        self.assertIn("声明段修正", tip)
        self.assertTrue(self.branch_contains(
            branch, "spec/changes/s1/tasks.md"))
        shown = self.git(self.project_root, "show",
                         f"{branch}:spec/changes/s1/tasks.md").stdout
        self.assertIn("core/new.py", shown)
        # 复检通过 → 复发计数无残留（Task 5.1 清零语义）
        entry = self.sm.read_one("s1")
        self.assertEqual(int(entry.get("_writeback_recur_streak") or 0), 0)

    def test_main_hit_writes_main_tree_and_commits(self):
        """六态 2：source == "main" → 就地写主树并提交（同源，不得判错层）。"""
        self.seed_spec()
        self.write_main_tasks("s1", _decl_tasks("core/old.py"))
        self.wm.file_exists_on_branch.side_effect = (
            lambda b, p: p == "core/new.py")
        self.write_judge_result("s1", self._typo_verdict(
            "core/old.py", "core/new.py"))
        self.stub_judge_run()
        result = self.make_result(branch="fenix/nonexistent")

        outcome = self.adjudicate("s1", result, ["core/old.py"])

        self.assertEqual(outcome["action"], "proceed")
        text = self.main_tasks_text("s1")
        self.assertIn("core/new.py", text)
        self.assertNotIn("core/old.py", text)
        tip = self.git(self.project_root, "log", "-1", "--format=%s").stdout
        self.assertIn("声明段修正", tip)

    def test_branch_hit_never_writes_main_tree(self):
        """六态 3：source == "branch" → 不写主树；裁决落册（凭据）+ 转打回。"""
        self.seed_spec()
        branch = self.make_branch_with_tasks(
            "s1", _decl_tasks("core/old.py"))
        result = self.make_result(branch=branch)
        self.wm.file_exists_on_branch.return_value = False
        self.write_judge_result("s1", self._typo_verdict(
            "core/old.py", "core/new.py"))
        self.stub_judge_run()

        outcome = self.adjudicate("s1", result, ["core/old.py"])

        # MUST NOT 以主树 tasks.md 为落点假装修正
        self.assertIsNone(self.main_tasks_text("s1"))
        # 该条 typo 裁决（element + actual_path）MUST 落 dispute 审计流
        recs = [r for r in self.audit_records() if r.get("spec") == "s1"]
        self.assertTrue(recs, "branch 命中层的 typo 裁决必须落册")
        verdicts = [v for r in recs for v in (r.get("verdicts") or [])]
        self.assertTrue(any(
            v.get("element") == "core/old.py"
            and v.get("verdict") == "typo"
            and v.get("actual_path") == "core/new.py"
            for v in verdicts))
        # 替代路径不在分支 → 不核销 → 不放行（转打回/凭据通道）
        self.assertNotEqual(outcome["action"], "proceed")

    def test_worktree_commit_conflict_degrades(self):
        """六态 6 / Task 1.4：worktree 提交失败 → 降级打回，不落主树兜底。"""
        self.seed_spec()
        wt, branch = self.make_worktree_with_tasks(
            "s1", _decl_tasks("core/old.py"))
        self.write_main_tasks("s1", _decl_tasks("core/old.py"))
        self.wm.find_worktree_path.return_value = wt
        self.engine._git_commit = mock.MagicMock(return_value=(False, "index.lock"))
        self.write_judge_result("s1", self._typo_verdict(
            "core/old.py", "core/new.py"))
        self.stub_judge_run()
        result = self.make_result(branch=branch)

        outcome = self.adjudicate("s1", result, ["core/old.py"])

        # 不静默判修正成功：verdict 转 unclear、修正不落 executed 审计主记录
        self.assertNotEqual(outcome["action"], "proceed")
        # MUST NOT 改落主树「兜底」
        self.assertNotIn("core/new.py", self.main_tasks_text("s1"))
        # 降级裁决落册（供下一轮凭据核销）
        verdicts = [
            v for r in self.audit_records() if r.get("spec") == "s1"
            for v in (r.get("verdicts") or [])
        ]
        self.assertTrue(any(
            v.get("element") == "core/old.py"
            and v.get("actual_path") == "core/new.py"
            for v in verdicts))
        # 复检/复发链路：deferred 条目计入复发计数（守卫重跑仍判旧路径 missing）
        entry = self.sm.read_one("s1")
        self.assertEqual(
            int(entry.get("_writeback_recur_streak") or 0), 1,
            "提交失败降级后复发计数仍须累加（守卫重读回滚后的旧路径）")
        self.assertEqual(entry.get("_writeback_recur_path"), "core/old.py")


class TestReadbackMismatch(_WbFixture):
    """Task 3.1/3.3：修正只落主树、分支版本仍含旧路径 → 复检 False + 告警。"""

    def test_verify_readback_false_when_branch_stale(self):
        self.seed_spec()
        branch = self.make_branch_with_tasks(
            "s1", _decl_tasks("core/old.py"))
        # 主树已修正（旧事故态：修正只落主树）
        self.write_main_tasks("s1", _decl_tasks("core/new.py"))
        ok = verify_correction_readback(
            "s1", "core/old.py", branch=branch, worktree_path=None,
            project_root=self.project_root,
        )
        self.assertFalse(ok)
        # 对照：替代路径视角复检通过（新路径已在主树声明中）
        ok_new = verify_correction_readback(
            "s1", "core/new.py", branch=branch, worktree_path=None,
            project_root=self.project_root,
        )
        self.assertTrue(ok_new)

    def test_adjudicator_warns_not_silent(self):
        self.seed_spec()
        branch = self.make_branch_with_tasks(
            "s1", _decl_tasks("core/old.py"))
        self.write_main_tasks("s1", _decl_tasks("core/new.py"))
        result = self.make_result(branch=branch)
        ok, detail = self.engine._dispatcher._readback_correction(
            "s1", result, "core/old.py", kind="new")
        self.assertFalse(ok)
        self.assertEqual(detail.get("source"), "branch")
        self.assertTrue(self.logger.has(
            "warning", "声明修正复检不一致"),
            "复检不一致 MUST logger.warning（不静默销账）")

    def test_readback_true_after_effective_fix(self):
        self.seed_spec()
        self.write_main_tasks("s1", _decl_tasks("core/new.py"))
        ok = verify_correction_readback(
            "s1", "core/old.py", branch="fenix/none", worktree_path=None,
            project_root=self.project_root,
        )
        self.assertTrue(ok)


class TestGuardCredentialRedemption(_WbFixture):
    """Task 4.2/4.3/4.4 + 6.4 预演一：守卫缺件凭据核销。"""

    def _append_typo_credential(self, spec, old, new):
        DisputeAuditStore(self.project_root).append({
            "spec": spec, "trigger_run_id": "", "judge_run_id": "",
            "verdicts": [{"element": old, "verdict": "typo",
                          "actual_path": new,
                          "reasoning": "judge-typo-deferred"}],
            "diff": {},
        })

    def test_redeemed_when_target_exists_on_branch(self):
        """4.4-a + 6.4 预演一（脱困）：主树已修正、分支旧声明、凭据在册、
        替代路径在分支 HEAD 存在 → 守卫不再报 missing。"""
        self.seed_spec()
        branch = self.make_branch_with_tasks(
            "s1", _decl_tasks("core/old.py"))
        self.add_file_on_branch(branch, "core/new.py")
        self._append_typo_credential("s1", "core/old.py", "core/new.py")
        self.wm.file_exists_on_branch.side_effect = (
            lambda b, p: p == "core/new.py")
        result = self.make_result(branch=branch)

        violations = self.engine._verification._deliverable_gate_missing(
            "s1", result)

        self.assertEqual(violations, [])
        self.assertTrue(self.logger.has("info", "缺件凭据核销"),
                        "核销 MUST logger.info 留痕（Task 4.3）")

    def test_not_redeemed_when_target_missing(self):
        """4.4-b：替代路径不在分支 HEAD → 防空洞核销，仍报 missing。"""
        self.seed_spec()
        branch = self.make_branch_with_tasks(
            "s1", _decl_tasks("core/old.py"))
        self._append_typo_credential("s1", "core/old.py", "core/new.py")
        self.wm.file_exists_on_branch.return_value = False
        result = self.make_result(branch=branch)

        violations = self.engine._verification._deliverable_gate_missing(
            "s1", result)

        self.assertEqual(
            [v["violation"] for v in violations], ["missing"])
        self.assertEqual(violations[0]["path"], "core/old.py")
        self.assertFalse(self.logger.has("info", "缺件凭据核销"))

    def test_delete_undeleted_not_redeemed(self):
        """4.4-c：kind: delete 的 undeleted 条目即使有凭据也不被核销
        （守 missing 作用域，undeleted 豁免走既有收缩防护通道）。"""
        self.seed_spec()
        branch = self.make_branch_with_tasks(
            "s1", _decl_tasks("core/legacy.py", kind="delete"))
        # 分支 HEAD 仍有该 blob → undeleted
        self.add_file_on_branch(branch, "core/legacy.py")
        self._append_typo_credential(
            "s1", "core/legacy.py", "core/moved.py")
        # 分支 HEAD 仍有 legacy.py（→ undeleted）；moved.py 的存在性与本
        # 断言无关（undeleted 不进核销作用域）
        self.wm.file_exists_on_branch.side_effect = (
            lambda b, p: p == "core/legacy.py")
        result = self.make_result(branch=branch)

        violations = self.engine._verification._deliverable_gate_missing(
            "s1", result)

        self.assertEqual(
            [v["violation"] for v in violations], ["undeleted"])
        self.assertFalse(self.logger.has("info", "缺件凭据核销"))

    def test_credential_target_query_forms(self):
        """4.1：替代路径查询两形态（relocation 记录 / typo verdicts）。"""
        self.seed_spec()
        self.assertIsNone(relocation_credential_target(
            self.project_root, "core/old.py"))
        DisputeAuditStore(self.project_root).append({
            "spec": "s1", "type": "relocation",
            "old_path": "core/old.py", "new_path": "core/relocated.py",
        })
        self.assertEqual(
            relocation_credential_target(self.project_root, "core/old.py"),
            "core/relocated.py")


class TestWritebackRecurFuse(_WbFixture):
    """Task 5.1/5.2/5.3：复发熔断独立字段。"""

    def test_independent_field_not_cleared_by_ready_reset(self):
        """连续 N 轮复发（穿插 blocked→ready 复位）计数不被清零、第 N 轮封顶。"""
        self.seed_spec()
        d = self.engine._dispatcher
        self.assertFalse(d._writeback_recur_bump("s1", "core/old.py"))
        # dispatch 打回/复位只动 status——独立字段 MUST NOT 被清零
        self.sm.update_spec("s1", {"status": "ready", "error": None})
        self.assertFalse(d._writeback_recur_bump("s1", "core/old.py"))
        self.sm.update_spec("s1", {"status": "ready", "error": None})
        self.assertTrue(d._writeback_recur_bump("s1", "core/old.py"))
        entry = self.sm.read_one("s1")
        # STATE.md 行式存储读回为 str（既有 _retry_count 同惯例，读侧 int() 强转）
        self.assertEqual(int(entry["_writeback_recur_streak"]), 3)
        self.assertEqual(entry["_writeback_recur_path"], "core/old.py")
        # 恢复续做/重建分支路径清的是 _retry_count——独立字段同轮不受影响
        self.sm.update_spec("s1", {"_retry_count": 0})
        entry = self.sm.read_one("s1")
        self.assertEqual(int(entry["_writeback_recur_streak"]), 3)
        self.assertEqual(int(entry["_retry_count"] or 0), 0)

    def test_path_change_resets_streak(self):
        self.seed_spec()
        d = self.engine._dispatcher
        d._writeback_recur_bump("s1", "a.py")
        d._writeback_recur_bump("s1", "a.py")
        self.assertFalse(d._writeback_recur_bump("s1", "b.py"))
        entry = self.sm.read_one("s1")
        self.assertEqual(int(entry["_writeback_recur_streak"]), 1)
        self.assertEqual(entry["_writeback_recur_path"], "b.py")

    def test_reset_on_correction_verified(self):
        """typo 修正复检通过 → 计数清零（Task 5.3）。"""
        self.seed_spec()
        d = self.engine._dispatcher
        d._writeback_recur_bump("s1", "core/old.py")
        d._writeback_recur_bump("s1", "core/old.py")
        d._writeback_recur_reset("s1")
        entry = self.sm.read_one("s1")
        self.assertEqual(int(entry.get("_writeback_recur_streak") or 0), 0)
        # None 落盘读回 'null' 字符串（行式存储现实，语义等价已清）
        self.assertIn(entry.get("_writeback_recur_path"), (None, "null"))

    def test_fuse_blocks_after_max_rounds(self):
        """5.2/6.4 集成：branch 命中层 + 替代路径不在分支 → 连续 3 轮
        deferred 后置 blocked（「修正未生效于读取基准」形态文案）。"""
        self.seed_spec()
        branch = self.make_branch_with_tasks(
            "s1", _decl_tasks("core/old.py"))
        result = self.make_result(branch=branch)
        self.wm.file_exists_on_branch.return_value = False
        self.write_judge_result("s1", [{
            "element": "core/old.py", "verdict": "typo",
            "actual_path": "core/new.py",
            "reasoning": "唯一 basename 命中", "confidence": "high",
        }])
        self.stub_judge_run()
        for round_no in range(3):
            outcome = self.adjudicate("s1", result, ["core/old.py"])
            entry = self.sm.read_one("s1")
            self.assertEqual(
                int(entry.get("_writeback_recur_streak") or 0), round_no + 1,
                f"第 {round_no + 1} 轮独立计数必须累加（不被复位清零）")
            if round_no < 2:
                self.assertNotEqual(entry["status"], "blocked")
                # 模拟 blocked→ready 复位续走（env-blocked 复位旁路既有行为）
                self.sm.update_spec("s1", {"status": "ready"})
        entry = self.sm.read_one("s1")
        self.assertEqual(entry["status"], "blocked")
        self.assertIn("修正未生效", entry.get("error") or "")


class TestUnfreezeAnchorDurability(_WbFixture):
    """Task 7.1/7.2/7.3 + 6.4 预演三：解冻续做锚点耐久。"""

    def _frozen_spec(self, name="fs"):
        self.sm.add_spec(name, {"priority": 5})
        self.sm.transition(name, "implementing")
        self.sm.update_spec(name, {
            "_frozen_hold": True,
            "error": "frozen: inflight agent stopped",
        })

    def _preserve_branch(self, spec, branch):
        self.git(self.project_root, "checkout", "-q", "-b", branch)
        (self.project_root / "impl.txt").write_text("w\n", encoding="utf-8")
        # add 限定 impl.txt —— .fenix/ 运行态文件不入库（入库后 checkout main
        # 会把 .fenix 连目录一起清掉，update_spec 的锁文件无处落）。
        self.git(self.project_root, "add", "impl.txt")
        self.git(self.project_root, "commit", "-qm", "wip preserve")
        self.git(self.project_root, "checkout", "-q", "main")
        self.sm.update_spec(spec, {"branch": branch})

    def test_bare_unfreeze_preserves_branch_anchor(self):
        """7.3 主断言：裸 unfreeze_spec（不传上下文，worktree 已清理只剩分支）
        → 保留分支不被静默丢弃（branch 保留 + _recovery_resume 置位）。"""
        self._frozen_spec()
        self._preserve_branch("fs", "fenix/fs-1790039698")

        ok = self.sm.unfreeze_spec("fs", status="implementing")

        self.assertTrue(ok)
        entry = self.sm.read_one("fs")
        self.assertEqual(entry.get("branch"), "fenix/fs-1790039698",
                         "保留分支 MUST NOT 被丢弃（事故：6 提交实现被弃）")
        self.assertTrue(entry.get("_recovery_resume"))
        self.assertFalse(entry.get("_frozen_hold"))
        self.assertTrue(self.logger.has("warning", "Unfreeze resume"))

    def test_anchor_kept_when_carrier_unavailable(self):
        """7.2：载体三态不可用（resolve_resume_site 失败）MUST NOT 整体丢弃
        分支锚点——仍记录续做分支 + _recovery_resume，由 dispatch 重建载体。"""
        self._frozen_spec()
        self._preserve_branch("fs", "fenix/fs-1790039698")
        wm = mock.MagicMock()
        wm.find_worktree_by_spec.return_value = None
        wm.find_branches_by_spec.return_value = [
            {"branch": "fenix/fs-1790039698", "ahead": 3,
             "main_is_ancestor": False, "committerdate": 1}]
        wm.resolve_resume_site.return_value = (None, None)

        self.sm.unfreeze_spec(
            "fs", status="implementing",
            project_root=self.project_root, worktree_manager=wm)

        entry = self.sm.read_one("fs")
        self.assertEqual(entry.get("branch"), "fenix/fs-1790039698")
        self.assertTrue(entry.get("_recovery_resume"))
        self.assertTrue(self.logger.has("warning", "载体暂不可用"))

    def test_explicit_path_adopts_resume_branch(self):
        """7.3 对照：显式传参路径续做分支被采用（既有行为不回归）。"""
        self._frozen_spec()
        self._preserve_branch("fs", "fenix/fs-1790039698")
        wm = mock.MagicMock()
        wm.find_worktree_by_spec.return_value = None
        wm.find_branches_by_spec.return_value = []
        wm.resolve_resume_site.return_value = (
            self.tmpdir / "carrier-wt", "fenix/fs-1790039698")

        self.sm.unfreeze_spec(
            "fs", status="implementing",
            project_root=self.project_root, worktree_manager=wm)

        entry = self.sm.read_one("fs")
        self.assertEqual(entry.get("branch"), "fenix/fs-1790039698")
        self.assertTrue(entry.get("_recovery_resume"))

    def test_bare_unfreeze_degrade_is_loud_when_no_branch(self):
        """7.1 降级路径：分支确实不存在时走普通重派，但 MUST 落显式 WARNING
        （绝无静默）。"""
        self._frozen_spec()
        wm = mock.MagicMock()
        wm.find_worktree_by_spec.return_value = None
        wm.find_branches_by_spec.return_value = []
        wm.resolve_resume_site.return_value = (None, None)

        self.sm.unfreeze_spec(
            "fs", status="ready",
            project_root=self.project_root, worktree_manager=wm)

        entry = self.sm.read_one("fs")
        self.assertIsNone(entry.get("branch"))
        self.assertFalse(entry.get("_recovery_resume"))
        self.assertTrue(self.logger.has(
            "warning", "Unfreeze resume degrade"))


if __name__ == "__main__":
    unittest.main()
