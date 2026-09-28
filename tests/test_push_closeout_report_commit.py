"""push 收口报告入库测试（evo-add-push-closeout-verification-report-commit）。

覆盖 tasks 2.1 / 2.2 全部分支：
  1. 报告在盘且未入库/有修改 → push 产生仅含该单文件的 commit（pathspec
     精确：其它 spec 在途草案与 staged 内容不受牵连）且 pushed 正常落定
  2. 幂等：报告已入库无变化 → 静默跳过零 WARNING，重入不重复提交
  3. 报告缺失 → 仅 verify_report 通道 WARNING，pushed 落定、零提交
  4. 非 git 项目 → 静默跳过（无 WARNING），pushed 落定
  5. git 失败 → verify_report 通道 WARNING，pushed 照常落定；
     函数本身外抛异常时 engine 侧 push-closeout 前缀 WARNING 兜底

引擎装配沿用 test_daemon_lifecycle_races.TestApprovePushSingleFlight 同款
（真实 PMEngine + 隔离 push 内部链路），临时项目根为独立 git 仓库（不污染
本仓库）；报告提交断言口径与 test_verification_report_commit 对齐。
"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import StateMachine

SPEC = "push-closeout-spec"
REPORT_REL = f"spec/changes/{SPEC}/verification-report.md"


@unittest.skipIf(shutil.which("git") is None, "git 不可用")
class _PushCloseoutBase(unittest.TestCase):
    """公共夹具：临时项目根 = 独立 git 仓库 + 真实 PMEngine（push 链路隔离）。"""

    def setUp(self):
        from core.pm_engine import PMEngine

        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self._git("init", "-q")
        self._git("config", "user.email", "fenix-test@example.com")
        self._git("config", "user.name", "fenix-test")
        self._git("config", "commit.gpgsign", "false")
        (self.project_root / "README.md").write_text("test repo\n", encoding="utf-8")
        self._git("add", "--", "README.md")
        self._git("commit", "-q", "-m", "init")
        # .fenix/ 运行时目录不入库（与真实项目 .gitignore 语义一致），
        # 保证 git status 断言只反映 spec/ 侧的夹具内容
        (self.project_root / ".gitignore").write_text(".fenix/\n", encoding="utf-8")
        self._git("add", "--", ".gitignore")
        self._git("commit", "-q", "-m", "gitignore")
        (self.project_root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()
        for m in ("info", "warning", "error", "debug"):
            setattr(self.logger, m, MagicMock())
        self.sm = StateMachine(self.project_root / ".fenix" / "STATE.md", self.logger)
        self.sm.add_spec(SPEC, {"status": "done", "branch": f"fenix/{SPEC}"})
        self.engine = PMEngine(self.sm, MagicMock(), {}, self.project_root, self.logger)
        # 隔离 push 内部链路：main push 假成功，归档收口替换为触发记录器
        # （归档替身保留触发时刻观测能力，见 test_report_commit_lands_before_…）
        self.archive_calls = []
        self.engine._is_push_backoffed = MagicMock(return_value=False)
        self.engine._resolve_push_branch = MagicMock(return_value=f"fenix/{SPEC}")
        self.engine._push_branch_best_effort = MagicMock()
        self.engine._archive_auto_commit = lambda: self.archive_calls.append(1)
        self.engine._append_project_log = MagicMock()
        self.engine._git_push_ref = MagicMock(return_value=(True, ""))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ── 夹具与观测助手 ──────────────────────────────────────────

    def _git(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.project_root), *args],
            capture_output=True,
            text=True,
        )

    def _report_path(self):
        return self.project_root / REPORT_REL

    def _write_report(self, content="## 结论：✅ 通过\n\npush 收口报告。\n"):
        self._report_path().parent.mkdir(parents=True, exist_ok=True)
        self._report_path().write_text(content, encoding="utf-8")

    def _head_commit(self):
        subject = self._git("log", "-1", "--format=%s").stdout.strip()
        files = [
            line
            for line in self._git("show", "--name-only", "--format=").stdout.splitlines()
            if line.strip()
        ]
        return subject, files

    def _commit_count(self):
        return int(self._git("rev-list", "--count", "HEAD").stdout.strip())

    def _warn_texts(self):
        return [
            str(c.args[1]) if len(c.args) >= 2 else str(c)
            for c in self.logger.warning.call_args_list
        ]

    def _push(self):
        ok = self.engine.approve_push(SPEC)
        spec = self.sm.read_one(SPEC) or {}
        return ok, spec.get("status")

    def _reenter_done(self):
        """pushed 复回 done（模拟重入/复验轮），验证重入不重复提交。"""
        self.sm.update_spec(SPEC, {"status": "done"})


class TestLingeringReportCommittedOnPush(_PushCloseoutBase):
    """tasks 2.1：滞留报告随收口入库（pathspec 精确单文件）。"""

    def test_untracked_report_committed_and_pushed_lands(self):
        self._write_report()
        ok, status = self._push()
        self.assertTrue(ok)
        self.assertEqual(status, "pushed")
        subject, files = self._head_commit()
        self.assertEqual(subject, f"[fenix] {SPEC}: verification-report 入库")
        self.assertEqual(files, [REPORT_REL])
        # 工作区不再滞留：git status 不再显示该报告
        status_out = self._git("status", "--porcelain").stdout
        self.assertNotIn(REPORT_REL, status_out)

    def test_modified_report_recommitted_on_push(self):
        self._write_report()
        ok, _status = self._push()
        self.assertTrue(ok)
        count1 = self._commit_count()

        # 报告落盘后有修改，重新收口 → 追加单文件 commit
        self._reenter_done()
        self._write_report("## 结论：✅ 通过\n\n第二轮修改后的报告。\n")
        ok2, status2 = self._push()
        self.assertTrue(ok2)
        self.assertEqual(status2, "pushed")
        self.assertEqual(self._commit_count(), count1 + 1)
        _subject, files = self._head_commit()
        self.assertEqual(files, [REPORT_REL])

    def test_pathspec_precision_other_drafts_not_swept(self):
        self._write_report()
        # 其它 spec 的在途草案：未跟踪新文件（预先 add 进暂存区模拟在途草案）
        other_dir = self.project_root / "spec" / "changes" / "other-spec-wip"
        other_dir.mkdir(parents=True, exist_ok=True)
        (other_dir / "tasks.md").write_text("WIP draft\n", encoding="utf-8")
        self._git("add", "--", "spec/changes/other-spec-wip/tasks.md")
        # 已跟踪文件的未暂存修改
        (self.project_root / "README.md").write_text("modified\n", encoding="utf-8")

        ok, status = self._push()
        self.assertTrue(ok)
        self.assertEqual(status, "pushed")
        _subject, files = self._head_commit()
        self.assertEqual(files, [REPORT_REL])
        # 无关内容未被吞：staged 草案保持 staged、工作区修改保持未暂存
        status_out = self._git("status", "--porcelain").stdout
        self.assertIn("A  spec/changes/other-spec-wip/tasks.md", status_out)
        self.assertIn(" M README.md", status_out)

    def test_report_commit_lands_before_archive_closeout(self):
        """设计要点：报告 commit 先于 _archive_auto_commit——归档收口尾部的
        _git_push_ref("main") 顺带把报告推上 origin。以归档替身触发时刻的
        HEAD 主题直接取证（而非靠调用顺序赌时序）。"""
        seen = {}

        def fake_archive():
            seen["head_at_archive"] = self._git("log", "-1", "--format=%s").stdout.strip()
            self.archive_calls.append(1)

        self.engine._archive_auto_commit = fake_archive
        self._write_report()
        ok, _status = self._push()
        self.assertTrue(ok)
        self.assertEqual(
            seen.get("head_at_archive"),
            f"[fenix] {SPEC}: verification-report 入库",
        )


class TestIdempotentSilentSkipOnPush(_PushCloseoutBase):
    """tasks 2.2（幂等分支）：已入库无变化 → 静默跳过零 WARNING，重入不重复提交。"""

    def test_repush_no_new_commit_no_warning(self):
        self._write_report()
        ok, _status = self._push()
        self.assertTrue(ok)
        count1 = self._commit_count()

        self._reenter_done()
        ok2, status2 = self._push()
        self.assertTrue(ok2)
        self.assertEqual(status2, "pushed")
        self.assertEqual(self._commit_count(), count1)
        # 零入库 WARNING：幂等静默跳过（verify_report 通道与 push-closeout 皆无）
        warns = [
            w for w in self._warn_texts() if "入库" in w or "push-closeout" in w
        ]
        self.assertEqual(warns, [])


class TestMissingReportOnlyWarning(_PushCloseoutBase):
    """tasks 2.2（缺失分支）：报告缺失 → 仅 verify_report 通道 WARNING，pushed 落定。"""

    def test_missing_report_warns_but_pushed_lands(self):
        ok, status = self._push()
        self.assertTrue(ok)
        self.assertEqual(status, "pushed")
        # 零提交：HEAD 仍停在夹具两笔（init + gitignore）
        self.assertEqual(self._commit_count(), 2)
        # WARNING 落 verify_report 既有通道（含 spec 名与 stderr 摘要），
        # 非 engine 侧 push-closeout 前缀（那是函数外抛异常的兜底通道）
        warns = self._warn_texts()
        self.assertTrue(
            any("验证报告入库失败" in w and SPEC in w and "git add 失败" in w for w in warns),
            warns,
        )
        # 非 engine 侧兜底通道（函数外抛异常才走 push-closeout 前缀；spec 名
        # 恰含 "push-closeout" 子串，故按兜底文案全文匹配而非裸子串）
        self.assertNotIn("push-closeout 报告入库异常", " ".join(warns))


@unittest.skipIf(shutil.which("git") is None, "git 不可用")
class TestNonGitProjectSilentSkip(unittest.TestCase):
    """tasks 2.2（非 git 分支）：无 git 仓库 → 静默跳过无 WARNING，pushed 落定。"""

    def setUp(self):
        from core.pm_engine import PMEngine

        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()
        for m in ("info", "warning", "error", "debug"):
            setattr(self.logger, m, MagicMock())
        self.sm = StateMachine(self.project_root / ".fenix" / "STATE.md", self.logger)
        self.sm.add_spec(SPEC, {"status": "done"})
        self.engine = PMEngine(self.sm, MagicMock(), {}, self.project_root, self.logger)
        self.engine._is_push_backoffed = MagicMock(return_value=False)
        self.engine._resolve_push_branch = MagicMock(return_value=f"fenix/{SPEC}")
        self.engine._push_branch_best_effort = MagicMock()
        self.engine._archive_auto_commit = MagicMock()
        self.engine._append_project_log = MagicMock()
        self.engine._git_push_ref = MagicMock(return_value=(True, ""))
        report = self.project_root / REPORT_REL
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("## 结论：✅ 通过\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_no_git_repo_silent_skip_pushed_lands(self):
        ok = self.engine.approve_push(SPEC)
        self.assertTrue(ok)
        self.assertEqual(self.sm.read_one(SPEC)["status"], "pushed")
        # 静默跳过：全程零 WARNING（不逐 push 刷入库噪声）
        self.assertEqual(self.logger.warning.call_args_list, [])
        # 报告保留在盘（非 git 项目报告仍可用，只是无入库机制）
        self.assertTrue((self.project_root / REPORT_REL).exists())


class TestGitFailureDegradationOnPush(_PushCloseoutBase):
    """tasks 2.2（git 失败分支）：入库失败仅 WARNING，pushed 照常落定。"""

    def test_index_lock_conflict_warning_pushed_lands(self):
        self._write_report()
        # 模拟并发争用（任务回写/归档提交同窗口）：index.lock 被占 → git add 失败
        (self.project_root / ".git" / "index.lock").write_text("", encoding="utf-8")
        ok, status = self._push()
        self.assertTrue(ok)
        self.assertEqual(status, "pushed")
        self.assertTrue(self._report_path().exists())  # 报告保留在磁盘
        warns = self._warn_texts()
        self.assertTrue(
            any("验证报告入库失败" in w and "git add 失败" in w for w in warns),
            warns,
        )
        self.assertNotIn("push-closeout 报告入库异常", " ".join(warns))

    def test_engine_side_exception_fallback_push_closeout_prefix(self):
        """函数本身外抛异常 → engine 外层兜底记 push-closeout 前缀 WARNING，
        pushed 照常落定（报告可丢，主链不可断）。"""
        import core.verify_report as vr

        self._write_report()
        original = vr._commit_verification_report

        def boom(project_root, spec_name, logger=None):
            raise RuntimeError("simulated closeout boom")

        vr._commit_verification_report = boom
        try:
            ok, status = self._push()
        finally:
            vr._commit_verification_report = original
        self.assertTrue(ok)
        self.assertEqual(status, "pushed")
        warns = self._warn_texts()
        self.assertTrue(
            any(w.startswith("push-closeout") and SPEC in w for w in warns),
            warns,
        )


if __name__ == "__main__":
    unittest.main()
