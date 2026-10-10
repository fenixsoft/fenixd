"""验证报告落盘即入库测试（evo-add-verification-report-commit-on-write）。

覆盖四类场景（design 测试节）：
  1. 报告落盘后触发单文件 git 提交（含 present 路径——Agent 已写报告、
     框架未落盘、闸门放行即入库；synthesized/resynthesized 两路同测）
  2. git 命令失败时仅 WARNING，闸门返回值与验证主流程不受影响
  3. 提交 pathspec 严格限于本报告文件（不卷入其它 spec 在途文件）
  4. 报告已入库且无变化时重复放行不落 WARNING（幂等静默跳过）
  5. 场景段写盘即入库（evo-verify-report-scenario-section-commit）：
     渲染写回后复用同一提交器补上次序缝（HEAD 含小节、pathspec 干净、
     隔离与幂等）
  6. 场景段渲染合并进闸门 pre-commit 挂点
     （evo-verification-report-closeout-single-commit）：闸门放行单次提交
     即含报告本体与「本轮场景集变更」（采纳流程内报告相关提交至多一次）、
     回调异常仅 WARNING 不阻断放行、放行后尾段二次渲染幂等零成本跳过

合成夹具沿用 add-verify-report-gate 的真实 report.json / .fenix-run-result.json。
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FIXTURES = Path(__file__).resolve().parent / "fixtures"

SPEC = "v2-shell-hash-router"


def _load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class _FakeLogger:
    """捕获 warning/error 的桩日志（verify_report 使用两参调用形式）。"""

    def __init__(self):
        self.records = []

    def warning(self, tag, msg):
        self.records.append(("WARNING", tag, msg))

    def error(self, tag, msg):
        self.records.append(("ERROR", tag, msg))

    def info(self, tag, msg):
        pass

    def debug(self, tag, msg):
        pass

    def warnings(self, contains=None):
        hits = [m for lvl, _tag, m in self.records if lvl == "WARNING"]
        if contains:
            hits = [m for m in hits if contains in m]
        return hits


def _seed_progress(root):
    """在项目根摆放验证引擎结构化数据（真实夹具）。"""
    progress = root / ".fenix" / "verify-progress" / SPEC
    progress.mkdir(parents=True, exist_ok=True)
    (progress / ".fenix-run-result.json").write_text(
        json.dumps(
            _load_fixture("v2-shell-hash-router-run-result.json"), ensure_ascii=False
        ),
        encoding="utf-8",
    )
    (progress / "report.json").write_text(
        json.dumps(_load_fixture("v2-shell-hash-router-report.json"), ensure_ascii=False),
        encoding="utf-8",
    )
    return progress


@unittest.skipIf(shutil.which("git") is None, "git 不可用")
class _CommitTestBase(unittest.TestCase):
    """公共夹具：临时项目根 + 独立 git 仓库（不污染本仓库）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.logger = _FakeLogger()
        self._git("init", "-q")
        self._git("config", "user.email", "fenix-test@example.com")
        self._git("config", "user.name", "fenix-test")
        self._git("config", "commit.gpgsign", "false")
        (self.project_root / "README.md").write_text("test repo\n", encoding="utf-8")
        self._git("add", "--", "README.md")
        self._git("commit", "-q", "-m", "init")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _git(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.project_root), *args],
            capture_output=True,
            text=True,
        )

    def _report_rel(self):
        return f"spec/changes/{SPEC}/verification-report.md"

    def _report_path(self):
        return self.project_root / self._report_rel()

    def _gate(self):
        from core.verify_report import ensure_verification_report

        return ensure_verification_report(self.project_root, SPEC, self.logger)

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


class TestCommitOnWrite(_CommitTestBase):
    """场景1：报告落盘后触发单文件 git 提交（两路生成均覆盖）。"""

    def test_synthesized_report_is_committed(self):
        self._seed = _seed_progress(self.project_root)
        result = self._gate()
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(result.get("action"), "synthesized")
        self.assertTrue(self._report_path().exists())
        subject, files = self._head_commit()
        self.assertEqual(subject, f"[fenix] {SPEC}: verification-report 入库")
        self.assertEqual(files, [self._report_rel()])
        # 落盘后工作区不再滞留：git status 不再显示其为未跟踪
        status = self._git("status", "--porcelain").stdout
        self.assertNotIn(self._report_rel(), status)

    def test_agent_written_report_committed_on_present(self):
        # present 主路径：Agent 已写报告、框架不落盘（不经写盘调用），
        # 无结构化数据可比对 → 不判残留 → 放行即入库
        self._report_path().parent.mkdir(parents=True, exist_ok=True)
        self._report_path().write_text("## 结论：✅ 通过\n\nAgent 叙述。\n", encoding="utf-8")
        result = self._gate()
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(result.get("action"), "present")
        subject, files = self._head_commit()
        self.assertEqual(subject, f"[fenix] {SPEC}: verification-report 入库")
        self.assertEqual(files, [self._report_rel()])

    def test_resynthesized_report_is_recommitted(self):
        _seed_progress(self.project_root)
        self.assertEqual(self._gate().get("action"), "synthesized")
        count1 = self._commit_count()

        # 新一轮裁决：report.json timestamp 变更 → 指纹变 → 旧报告判残留
        progress = self.project_root / ".fenix" / "verify-progress" / SPEC
        rp = progress / "report.json"
        data = json.loads(rp.read_text(encoding="utf-8"))
        data["timestamp"] = str(data.get("timestamp") or "") + "-next"
        rp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        result = self._gate()
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(result.get("action"), "resynthesized")
        self.assertEqual(self._commit_count(), count1 + 1)
        _subject, files = self._head_commit()
        self.assertEqual(files, [self._report_rel()])


class TestGitFailureDegradation(_CommitTestBase):
    """场景2：git 失败只落 WARNING，验证主流程与返回值不变。"""

    def test_git_add_lock_conflict_only_warning(self):
        _seed_progress(self.project_root)
        # 模拟并发争用（任务回写/归档提交同窗口）：index.lock 被占
        (self.project_root / ".git" / "index.lock").write_text("", encoding="utf-8")
        result = self._gate()
        self.assertTrue(result.get("ok"), result)  # 放行结论不变
        self.assertEqual(result.get("action"), "synthesized")
        self.assertTrue(self._report_path().exists())  # 报告保留在磁盘
        warns = self.logger.warnings(contains="验证报告入库失败")
        self.assertEqual(len(warns), 1)
        self.assertIn("git add 失败", warns[0])
        self.assertIn("index.lock", warns[0])

    def test_git_commit_failure_only_warning(self):
        _seed_progress(self.project_root)
        # add 成功、commit 失败：本地身份置空（空值优先于全局配置，不回退
        # 全局身份），git commit 因 Author identity unknown 非零退出
        self._git("config", "user.email", "")
        self._git("config", "user.name", "")
        result = self._gate()
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(result.get("action"), "synthesized")
        self.assertTrue(self._report_path().exists())
        warns = self.logger.warnings(contains="验证报告入库失败")
        self.assertEqual(len(warns), 1)
        self.assertIn("git commit 失败", warns[0])


class TestPathspecPrecision(_CommitTestBase):
    """场景3：提交 pathspec 严格单文件，不卷入其它 spec 在途文件。"""

    def test_commit_does_not_include_other_files(self):
        _seed_progress(self.project_root)
        # 其它 spec 的在途草案：未跟踪新文件（先 add 进暂存区模拟在途草案）
        other_dir = self.project_root / "spec" / "changes" / "other-spec-wip"
        other_dir.mkdir(parents=True, exist_ok=True)
        (other_dir / "tasks.md").write_text("WIP draft\n", encoding="utf-8")
        self._git("add", "--", "spec/changes/other-spec-wip/tasks.md")
        # 已跟踪文件的未暂存修改
        (self.project_root / "README.md").write_text("modified\n", encoding="utf-8")

        result = self._gate()
        self.assertTrue(result.get("ok"), result)
        _subject, files = self._head_commit()
        self.assertEqual(files, [self._report_rel()])
        # 无关内容未被吞：staged 草案保持 staged、工作区修改保持未暂存
        status = self._git("status", "--porcelain").stdout
        self.assertIn("A  spec/changes/other-spec-wip/tasks.md", status)
        self.assertIn(" M README.md", status)


class TestIdempotentSilentSkip(_CommitTestBase):
    """场景4：报告已入库且无变化时重复放行 → 无新提交、不落 WARNING。"""

    def test_repeated_gate_no_new_commit_no_warning(self):
        _seed_progress(self.project_root)
        self.assertEqual(self._gate().get("action"), "synthesized")
        count1 = self._commit_count()
        records_before = len(self.logger.records)

        # 第二次放行：报告已在（present）、内容未变 → nothing to commit 静默跳过
        result = self._gate()
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(result.get("action"), "present")
        self.assertEqual(self._commit_count(), count1)
        self.assertEqual(len(self.logger.records), records_before)
        self.assertEqual(self.logger.warnings(contains="验证报告入库失败"), [])


@unittest.skipIf(shutil.which("git") is None, "git 不可用")
class TestScenarioSectionCommit(_CommitTestBase):
    """场景5：场景段写盘即入库（evo-verify-report-scenario-section-commit）。

    桩 pipeline 上下文 + 真实渲染函数：_render_scenario_change_section_to_report
    只消费 _context.project_root/logger 与 _last_scenario_diff/_last_freeze_owner
    归属戳（跨 spec 残留戳不作渲染来源）。
    """

    def _make_pipeline(self, diff):
        from types import SimpleNamespace

        return SimpleNamespace(
            _context=SimpleNamespace(
                project_root=self.project_root, logger=self.logger
            ),
            _last_scenario_diff=diff,
            _last_freeze_owner=SPEC,
        )

    def _seed_report(self):
        """报告闸门次序语义的前置态：报告已落盘且已入库（尚无场景段）。"""
        self._report_path().parent.mkdir(parents=True, exist_ok=True)
        self._report_path().write_text("## 结论：✅ 通过\n\n叙述。\n", encoding="utf-8")
        self._git("add", "--", self._report_rel())
        self._git("commit", "-q", "-m", "gate: report")

    def _seed_diff(self):
        """真实 diff（照抄 test_verify_scenarios 超发拦截夹具：含新增变更行）。"""
        from core.verify_scenarios import (
            ScenarioEntry,
            ScenarioSet,
            diff_planner_output,
            save_scenario_set,
        )

        save_scenario_set(
            self.project_root,
            ScenarioSet(
                SPEC,
                1,
                [
                    ScenarioEntry(id="s1", description="场景一", added_in_round=1),
                    ScenarioEntry(id="s2", description="场景二", added_in_round=1),
                ],
            ),
        )
        return diff_planner_output(
            self.project_root,
            SPEC,
            {"_verify_fail_rounds": 1},
            [{"id": "s1"}, {"id": "s2"}, {"id": "s3"}],
            2,
        )

    def _render(self):
        from core.pm_engine.verification.scenario_gate import (
            _render_scenario_change_section_to_report,
        )

        _render_scenario_change_section_to_report(
            self._make_pipeline(self._seed_diff()), SPEC
        )

    def test_section_write_is_committed(self):
        self._seed_report()
        count_before = self._commit_count()

        self._render()

        # HEAD 已包含小节（写盘即入库，不再滞留工作区）
        head_content = self._git("show", f"HEAD:{self._report_rel()}").stdout
        self.assertIn("## 本轮场景集变更", head_content)
        self.assertIn("拦截 planner 超发", head_content)
        # 该 pathspec 对 HEAD 干净
        self.assertEqual(
            self._git(
                "diff", "HEAD", "--quiet", "--", self._report_rel()
            ).returncode,
            0,
        )
        status = self._git("status", "--porcelain").stdout
        self.assertNotIn(self._report_rel(), status)
        _subject, files = self._head_commit()
        self.assertEqual(files, [self._report_rel()])
        self.assertEqual(self._commit_count(), count_before + 1)

    def test_section_commit_is_pathspec_isolated(self):
        self._seed_report()
        # 其它 spec 的在途草案（staged）+ 已跟踪文件未暂存修改（照抄
        # TestPathspecPrecision 的保全断言）
        other_dir = self.project_root / "spec" / "changes" / "other-spec-wip"
        other_dir.mkdir(parents=True, exist_ok=True)
        (other_dir / "tasks.md").write_text("WIP draft\n", encoding="utf-8")
        self._git("add", "--", "spec/changes/other-spec-wip/tasks.md")
        (self.project_root / "README.md").write_text("modified\n", encoding="utf-8")

        self._render()

        _subject, files = self._head_commit()
        self.assertEqual(files, [self._report_rel()])
        status = self._git("status", "--porcelain").stdout
        self.assertIn("A  spec/changes/other-spec-wip/tasks.md", status)
        self.assertIn(" M README.md", status)

    def test_second_render_no_new_commit_no_warning(self):
        self._seed_report()
        self._render()
        count1 = self._commit_count()
        records_before = len(self.logger.records)

        # 小节已在库 → 渲染幂等判重跳过，无新提交、零 WARNING
        self._render()

        self.assertEqual(self._commit_count(), count1)
        self.assertEqual(len(self.logger.records), records_before)
        self.assertEqual(self.logger.warnings(contains="入库失败"), [])


@unittest.skipIf(shutil.which("git") is None, "git 不可用")
class TestGateMergedScenarioSectionCommit(_CommitTestBase):
    """场景6：场景段渲染合并进闸门 pre-commit 挂点
    （evo-verification-report-closeout-single-commit）。

    经真实闸门链路（report_gate._ensure_verification_report 注入闭包 →
    ensure_verification_report 执行回调）驱动，桩 pipeline 形态同
    TestScenarioSectionCommit；采纳流程内报告相关提交收敛至多一次。
    """

    def _make_pipeline(self, diff):
        from types import SimpleNamespace

        return SimpleNamespace(
            _context=SimpleNamespace(
                project_root=self.project_root, logger=self.logger
            ),
            _last_scenario_diff=diff,
            _last_freeze_owner=SPEC,
        )

    def _seed_diff(self):
        """真实 diff（照抄 TestScenarioSectionCommit._seed_diff 夹具）。"""
        from core.verify_scenarios import (
            ScenarioEntry,
            ScenarioSet,
            diff_planner_output,
            save_scenario_set,
        )

        save_scenario_set(
            self.project_root,
            ScenarioSet(
                SPEC,
                1,
                [
                    ScenarioEntry(id="s1", description="场景一", added_in_round=1),
                    ScenarioEntry(id="s2", description="场景二", added_in_round=1),
                ],
            ),
        )
        return diff_planner_output(
            self.project_root,
            SPEC,
            {"_verify_fail_rounds": 1},
            [{"id": "s1"}, {"id": "s2"}, {"id": "s3"}],
            2,
        )

    def _gate_via_report_gate(self, pipeline):
        """走 report_gate 真实注入路径放行（返回 None=放行）。"""
        from core.pm_engine.verification.report_gate import (
            _ensure_verification_report,
        )

        return _ensure_verification_report(pipeline, SPEC)

    def test_synthesized_gate_single_commit_includes_section(self):
        _seed_progress(self.project_root)
        pipeline = self._make_pipeline(self._seed_diff())
        count_before = self._commit_count()

        self.assertIsNone(self._gate_via_report_gate(pipeline))

        # 闸门放行后提交计数恰 +1：合并提交（本体+场景段）成功、外层提交器
        # 对已入库 pathspec 幂等静默跳过，不再产生第二次提交
        self.assertEqual(self._commit_count(), count_before + 1)
        subject, files = self._head_commit()
        self.assertEqual(subject, f"[fenix] {SPEC}: verification-report 入库")
        self.assertEqual(files, [self._report_rel()])
        head_content = self._git("show", f"HEAD:{self._report_rel()}").stdout
        self.assertIn("## 结论", head_content)  # 报告本体（合成产物）
        self.assertIn("## 本轮场景集变更", head_content)
        self.assertIn("拦截 planner 超发", head_content)
        # 报告不再滞留工作区
        status = self._git("status", "--porcelain").stdout
        self.assertNotIn(self._report_rel(), status)

    def test_present_gate_single_commit_includes_section(self):
        # present 主路径：Agent 已写报告在盘，闸门回调渲染场景段后一并入库
        self._report_path().parent.mkdir(parents=True, exist_ok=True)
        self._report_path().write_text("## 结论：✅ 通过\n\nAgent 叙述。\n", encoding="utf-8")
        pipeline = self._make_pipeline(self._seed_diff())
        count_before = self._commit_count()

        self.assertIsNone(self._gate_via_report_gate(pipeline))

        self.assertEqual(self._commit_count(), count_before + 1)
        _subject, files = self._head_commit()
        self.assertEqual(files, [self._report_rel()])
        head_content = self._git("show", f"HEAD:{self._report_rel()}").stdout
        self.assertIn("Agent 叙述", head_content)  # Agent 报告本体未被覆盖
        self.assertIn("## 本轮场景集变更", head_content)
        status = self._git("status", "--porcelain").stdout
        self.assertNotIn(self._report_rel(), status)

    def test_merged_commit_is_pathspec_isolated(self):
        _seed_progress(self.project_root)
        # 其它 spec 的在途草案（staged）+ 已跟踪文件未暂存修改
        other_dir = self.project_root / "spec" / "changes" / "other-spec-wip"
        other_dir.mkdir(parents=True, exist_ok=True)
        (other_dir / "tasks.md").write_text("WIP draft\n", encoding="utf-8")
        self._git("add", "--", "spec/changes/other-spec-wip/tasks.md")
        (self.project_root / "README.md").write_text("modified\n", encoding="utf-8")

        self.assertIsNone(self._gate_via_report_gate(self._make_pipeline(self._seed_diff())))

        _subject, files = self._head_commit()
        self.assertEqual(files, [self._report_rel()])
        status = self._git("status", "--porcelain").stdout
        self.assertIn("A  spec/changes/other-spec-wip/tasks.md", status)
        self.assertIn(" M README.md", status)

    def test_pre_commit_exception_degrades_to_warning_still_passes(self):
        # 回调异常契约（present 出口载体：闸门自身零 WARNING → WARNING 恰
        # 一条即回调异常本身）：闸门仍放行、报告本体照常入库
        self._report_path().parent.mkdir(parents=True, exist_ok=True)
        self._report_path().write_text("## 结论：✅ 通过\n\nAgent 叙述。\n", encoding="utf-8")
        count_before = self._commit_count()

        def _boom():
            raise RuntimeError("场景段渲染爆炸")

        from core.verify_report import ensure_verification_report

        result = ensure_verification_report(
            self.project_root, SPEC, self.logger, pre_commit=_boom
        )
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(result.get("action"), "present")
        self.assertEqual(self._commit_count(), count_before + 1)
        _subject, files = self._head_commit()
        self.assertEqual(files, [self._report_rel()])
        head_content = self._git("show", f"HEAD:{self._report_rel()}").stdout
        self.assertIn("Agent 叙述", head_content)
        self.assertNotIn("## 本轮场景集变更", head_content)
        warns = self.logger.warnings(contains="pre-commit 回调失败")
        self.assertEqual(len(warns), 1)
        self.assertIn("场景段渲染爆炸", warns[0])

    def test_tail_rerender_after_gate_no_new_commit_no_warning(self):
        # 末尾渲染点兜底幂等：闸门已合并提交后，采纳尾段二次渲染按「标题已
        # 存在即跳过」零成本跳过——提交计数不增、WARNING 零新增
        _seed_progress(self.project_root)
        pipeline = self._make_pipeline(self._seed_diff())
        self._gate_via_report_gate(pipeline)
        count1 = self._commit_count()
        records_before = len(self.logger.records)

        from core.pm_engine.verification.scenario_gate import (
            _render_scenario_change_section_to_report,
        )

        _render_scenario_change_section_to_report(pipeline, SPEC)

        self.assertEqual(self._commit_count(), count1)
        # records 计数不变即零新增（synthesized 出口闸门自带「报告缺失已合成」
        # WARNING 在放行前已计入 records_before，不算尾段渲染的新增）
        self.assertEqual(len(self.logger.records), records_before)
        self.assertEqual(self.logger.warnings(contains="入库失败"), [])


class TestNonGitProjectSilentSkip(unittest.TestCase):
    """被管项目无 git：入库机制不适用，静默跳过（不逐轮刷 WARNING）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_gate_skips_commit_silently_without_git_repo(self):
        from core.verify_report import ensure_verification_report

        _seed_progress(self.project_root)
        logger = _FakeLogger()
        result = ensure_verification_report(self.project_root, SPEC, logger)
        self.assertTrue(result.get("ok"), result)
        self.assertTrue(
            (self.project_root / "spec" / "changes" / SPEC / "verification-report.md").exists()
        )
        self.assertEqual(logger.warnings(contains="验证报告入库失败"), [])


if __name__ == "__main__":
    unittest.main()
