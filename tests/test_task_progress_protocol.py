"""implementer 任务进度协议测试（fix-implementer-task-progress）。

覆盖三个能力面：
  1. implementer-task-protocol：full / fast-track 双分支 prompt 注入任务编号契约段；
  2. task-progress-writeback：_sync_task_progress 三级回退（done_ids 精确 →
     flat_done + 弱一致性校验按创建序兜底 → 皆空跳过）；
  3. run-progress-observability：run_task_progress / spec_summary.run_progress
     字段语义（不依赖 tasks.md 编号，无 run 缺省 {0,0}）。
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_agent_runner import FakeLogger, make_runner
from test_pm_dispatch import _write_impl_run_for_spec


def _mk_spec_dir(proot: Path, name: str) -> None:
    d = proot / "spec" / "changes" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "tasks.md").write_text("# Tasks\n\n## 1. 实现\n\n- [ ] 1.1 a\n", encoding="utf-8")


class TestTaskProgressContractPrompt(unittest.TestCase):
    """implementer-task-protocol：双分支 prompt 均含任务编号契约段。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)
        _mk_spec_dir(self.proot, "demo")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _prompt(self, agent_type):
        runner = make_runner(self.proot)
        return runner._prompt_builder._build_prompt("demo", agent_type)

    def test_full_implementer_prompt_contains_contract(self):
        prompt = self._prompt("implementer")
        assert "任务进度契约" in prompt
        assert "task-progress-contract" in prompt
        # subject 格式示例断言（id 直取 tasks.md 分组号.任务号）
        assert "Task <id>: <标题>" in prompt
        assert "Task 1.3: 配置解析签名缓存" in prompt
        # 禁止归并 / 分组标题当任务
        assert "归并为一条" in prompt
        assert "分组（## 标题）当任务创建" in prompt
        # 完成即汇报，不得攒批
        assert "不得攒批到收尾" in prompt
        # 收尾逐项勾选与 TaskCreate/TaskUpdate 一一对应
        assert "一一对应，不留半勾" in prompt

    def test_fast_track_prompt_contains_contract(self):
        prompt = self._prompt("fast-track")
        assert "任务进度契约" in prompt
        assert "Task <id>: <标题>" in prompt
        assert "Task 1.3: 配置解析签名缓存" in prompt
        assert "不得攒批到收尾" in prompt
        assert "一一对应，不留半勾" in prompt

    def test_contract_text_shared_between_branches(self):
        """文本复用：两分支注入的契约段逐字节一致（独立构建路径各自注入）。"""
        full = self._prompt("implementer")
        fast = self._prompt("fast-track")
        seg = "## 任务进度契约（task-progress-contract"
        end = "一一对应，不留半勾。\n"

        def extract(prompt):
            start = prompt.index(seg)
            stop = prompt.index(end, start) + len(end)
            return prompt[start:stop]

        self.assertEqual(extract(full), extract(fast))

    def test_full_implementer_wrapup_step_strengthened(self):
        # implementer.md 已随 7958e50 中文化，断言跟随中文表述
        prompt = self._prompt("implementer")
        assert "与全部 TaskUpdate 记录一一对应" in prompt

    def test_fast_track_wrapup_step_strengthened(self):
        # fast-track.md 已随 7958e50 中文化，断言跟随中文表述
        prompt = self._prompt("fast-track")
        assert "与全部 TaskUpdate 记录一一对应" in prompt


class TestTaskProgressSyncFallback(unittest.TestCase):
    """task-progress-writeback：_sync_task_progress 三级回退。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "config", "user.name", "test"],
                       cwd=str(self.project_root), capture_output=True)
        (self.project_root / ".gitignore").write_text(".fenix/\n", encoding="utf-8")
        (self.project_root / "README.md").write_text("# test\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"],
                       cwd=str(self.project_root), capture_output=True)
        self.sm = MagicMock()
        self.sm.read_one = MagicMock(return_value={"status": "done"})
        self.sm.transition = MagicMock()
        self.sm.update_spec = MagicMock()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_engine(self, config=None):
        from core.pm_engine import PMEngine
        logger = MagicMock()
        for m in ("info", "warning", "error", "debug"):
            setattr(logger, m, MagicMock())
        ar = MagicMock()
        return PMEngine(self.sm, ar, config or {}, self.project_root, logger)

    def _write_spec_tasks(self, spec_name: str, n_tasks: int, checked: int = 0) -> Path:
        spec_dir = self.project_root / "spec" / "changes" / spec_name
        spec_dir.mkdir(parents=True, exist_ok=True)
        lines = [f"# Tasks: {spec_name}", "", "## 1. 实现", ""]
        for i in range(1, n_tasks + 1):
            mark = "x" if i <= checked else " "
            lines.append(f"- [{mark}] 1.{i} task {i}")
        p = spec_dir / "tasks.md"
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return p

    def _commit_spec(self, spec_name: str):
        subprocess.run(["git", "add", "--", "spec"],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", f"spec {spec_name}"],
                       cwd=str(self.project_root), capture_output=True)

    def _head(self):
        return subprocess.run(["git", "rev-parse", "HEAD"],
                              cwd=str(self.project_root), capture_output=True, text=True).stdout.strip()

    def _tasks_text(self, spec_name="demo"):
        return (self.project_root / "spec" / "changes" / spec_name / "tasks.md").read_text()

    def test_flat_fallback_checks_first_n(self):
        """spec 场景：无编号 run（created=6, flat={0,1,2,3}），27 项未完成 →
        弱校验通过（27 ≤ 6*5），前 4 项未完成勾选。"""
        self._write_spec_tasks("demo", 27)
        self._commit_spec("demo")
        _write_impl_run_for_spec(
            self.project_root, "demo", 1789000100,
            [f"Implement grouping {i}" for i in range(6)],  # subject 无编号
            [(1, "completed"), (2, "completed"),
             (3, "completed"), (4, "completed")],
        )
        engine = self._make_engine()
        engine._sync_task_progress("demo")
        text = self._tasks_text()
        for i in range(1, 5):
            self.assertIn(f"- [x] 1.{i} task {i}", text)
        self.assertIn("- [ ] 1.5 task 5", text)  # 前 4 之外不勾
        self.assertIn("- [ ] 1.27 task 27", text)
        res = subprocess.run(["git", "log", "--oneline"],
                             cwd=str(self.project_root), capture_output=True, text=True)
        self.assertIn("sync task progress from run record", res.stdout)

    def test_flat_fallback_weak_check_skips(self):
        """spec 场景：created=2 / 未完成 27 → 归并比超 1:5，弱校验不符 → 不回写。"""
        self._write_spec_tasks("demo", 27)
        self._commit_spec("demo")
        _write_impl_run_for_spec(
            self.project_root, "demo", 1789000200,
            ["do setup", "do rest"], [(1, "completed"), (2, "completed")],
        )
        engine = self._make_engine()
        head = self._head()
        engine._sync_task_progress("demo")
        self.assertIn("- [ ] 1.1 task 1", self._tasks_text())
        self.assertEqual(head, self._head())  # 无 commit

    def test_precise_path_ignores_flat(self):
        """done_ids 非空 → 精确路径，flat_done 不参与（既有行为零回归）。"""
        self._write_spec_tasks("demo", 3)
        self._commit_spec("demo")
        _write_impl_run_for_spec(
            self.project_root, "demo", 1789000300,
            ["Task 1.1: build", "Task 1.2: test", "Task 1.3: doc"],
            [(1, "completed")],  # 仅任务 1 完成
        )
        engine = self._make_engine()
        engine._sync_task_progress("demo")
        text = self._tasks_text()
        self.assertIn("- [x] 1.1 task 1", text)
        self.assertIn("- [ ] 1.2 task 2", text)  # flat={0} 不外溢
        self.assertIn("- [ ] 1.3 task 3", text)

    def _write_run_file(self, spec_name: str, ts: int, subjects: list,
                         completed_task_ids: list):
        """写 run 产物 fixture：TaskCreate 按 subjects 序，TaskUpdate 按 taskId 显式指定。"""
        runs_dir = self.project_root / ".fenix" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        lines = []
        for s in subjects:
            lines.append(json.dumps({
                "type": "assistant",
                "message": {"content": [{
                    "type": "tool_use", "name": "TaskCreate",
                    "input": {"subject": s},
                }]},
            }))
        for tid in completed_task_ids:
            lines.append(json.dumps({
                "type": "assistant",
                "message": {"content": [{
                    "type": "tool_use", "name": "TaskUpdate",
                    "input": {"taskId": tid, "status": "completed"},
                }]},
            }))
        (runs_dir / f"impl-{spec_name}-{ts}.jsonl").write_text(
            "\n".join(lines), encoding="utf-8")

    def test_flat_fallback_gap_marks_max_plus_one(self):
        """flat_done 有空洞（{0,2}）→ 按 max+1=3 勾前 3 个未完成项。"""
        self._write_spec_tasks("demo", 6)
        self._commit_spec("demo")
        self._write_run_file(
            "demo", 1789000400,
            [f"do {i}" for i in range(4)],
            [1, 3],  # taskId 1,3 → idx {0,2}
        )
        engine = self._make_engine()
        engine._sync_task_progress("demo")
        text = self._tasks_text()
        self.assertIn("- [x] 1.1 task 1", text)
        self.assertIn("- [x] 1.2 task 2", text)
        self.assertIn("- [x] 1.3 task 3", text)
        self.assertIn("- [ ] 1.4 task 4", text)

    def test_all_empty_skips(self):
        """done_ids/flat_done 皆空（只创建未完成）→ 第 3 级跳过，不误写。"""
        self._write_spec_tasks("demo", 3)
        self._commit_spec("demo")
        _write_impl_run_for_spec(
            self.project_root, "demo", 1789000500,
            ["do a", "do b"], [],  # 无任何 TaskUpdate completed
        )
        engine = self._make_engine()
        head = self._head()
        engine._sync_task_progress("demo")
        self.assertIn("- [ ] 1.1 task 1", self._tasks_text())
        self.assertEqual(head, self._head())

    def test_atomic_write_no_temp_leftover(self):
        """回写走临时文件 + replace：成功后 spec 目录无 .tmp 残留。"""
        self._write_spec_tasks("demo", 27)
        self._commit_spec("demo")
        _write_impl_run_for_spec(
            self.project_root, "demo", 1789000600,
            [f"Implement grouping {i}" for i in range(6)],
            [(1, "completed"), (2, "completed")],
        )
        engine = self._make_engine()
        engine._sync_task_progress("demo")
        spec_dir = self.project_root / "spec" / "changes" / "demo"
        leftovers = [p.name for p in spec_dir.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])
        self.assertIn("- [x] 1.1 task 1", self._tasks_text())


class TestRunProgressObservability(unittest.TestCase):
    """run-progress-observability：run_task_progress / spec_summary.run_progress。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)
        (self.proot / ".fenix").mkdir()
        _mk_spec_dir(self.proot, "demo")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_run(self, subjects, completed_task_ids, in_progress_task_ids=(),
                   terminal_event=None):
        runs_dir = self.proot / ".fenix" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        lines = []
        for s in subjects:
            lines.append(json.dumps({
                "type": "assistant",
                "message": {"content": [{
                    "type": "tool_use", "name": "TaskCreate",
                    "input": {"subject": s},
                }]},
            }))
        for tid in in_progress_task_ids:
            lines.append(json.dumps({
                "type": "assistant",
                "message": {"content": [{
                    "type": "tool_use", "name": "TaskUpdate",
                    "input": {"taskId": tid, "status": "in_progress"},
                }]},
            }))
        for tid in completed_task_ids:
            lines.append(json.dumps({
                "type": "assistant",
                "message": {"content": [{
                    "type": "tool_use", "name": "TaskUpdate",
                    "input": {"taskId": tid, "status": "completed"},
                }]},
            }))
        if terminal_event is not None:
            lines.append(json.dumps(terminal_event))
        (runs_dir / "impl-demo-1789001000.jsonl").write_text(
            "\n".join(lines), encoding="utf-8")

    def test_no_numbered_run_yields_progress(self):
        """spec 场景：6 个 TaskCreate、1 个 completed（subject 无编号）→
        run_progress = {"done": 1, "total": 6, "current": []}，而非全 0。"""
        from core.dashboard.data import run_task_progress
        self._write_run([f"grouped task {i}" for i in range(6)], [1])
        rp = run_task_progress(self.proot, "demo")
        self.assertEqual(rp, {"done": 1, "total": 6, "current": []})

    def test_no_run_defaults_zero(self):
        """spec 场景：无 impl run 记录 → {"done": 0, "total": 0, "current": []}，不报错。"""
        from core.dashboard.data import run_task_progress
        self.assertEqual(run_task_progress(self.proot, "demo"),
                         {"done": 0, "total": 0, "current": []})

    def test_spec_summary_has_run_progress(self):
        """spec_summary 含 run_progress 字段（/api/specs 列表项数据源）。"""
        from core.dashboard.data import spec_summary
        self._write_run([f"grouped task {i}" for i in range(6)], [1, 2])
        summary = spec_summary(self.proot, "demo", {"status": "implementing"})
        self.assertEqual(summary["run_progress"], {"done": 2, "total": 6, "current": []})

    def test_spec_summary_run_progress_default_without_run(self):
        from core.dashboard.data import spec_summary
        summary = spec_summary(self.proot, "demo", {"status": "drafted"})
        self.assertEqual(summary["run_progress"], {"done": 0, "total": 0, "current": []})

    def test_spec_detail_has_run_progress(self):
        """spec_detail 含 run_progress 字段（详情页统计卡片数据源）。"""
        from core.dashboard.data import spec_detail
        self._write_run([f"grouped task {i}" for i in range(6)], [1])
        detail = spec_detail(self.proot, "demo", {"status": "implementing"})
        self.assertEqual(detail["run_progress"], {"done": 1, "total": 6, "current": []})

    def test_run_progress_numbered_subjects_counted(self):
        """subject 带编号的合规 run：done 按 TaskUpdate 去重数（非 done_ids 数）。"""
        from core.dashboard.data import run_task_progress
        self._write_run(
            [f"Task 1.{i}: t{i}" for i in range(1, 4)], [1, 2, 3])
        rp = run_task_progress(self.proot, "demo")
        self.assertEqual(rp, {"done": 3, "total": 3, "current": []})

    def test_in_progress_ids_extracted(self):
        """run-progress-current：TaskUpdate in_progress 且未 completed →
        current 带出 tasks.md id（subject 编号），done 仍为 0。"""
        from core.dashboard.data import run_task_progress
        self._write_run(
            [f"Task 1.{i}: t{i}" for i in range(1, 3)],
            [], in_progress_task_ids=[1])
        rp = run_task_progress(self.proot, "demo")
        self.assertEqual(rp, {"done": 0, "total": 2, "current": ["1.1"]})

    def test_in_progress_then_completed_not_current(self):
        """run-progress-current：同一 taskId 先 in_progress 后 completed →
        最新状态胜出，不再计入 current。"""
        from core.dashboard.data import run_task_progress
        self._write_run(
            [f"Task 1.{i}: t{i}" for i in range(1, 3)],
            [1], in_progress_task_ids=[1])
        rp = run_task_progress(self.proot, "demo")
        self.assertEqual(rp, {"done": 1, "total": 2, "current": []})

    def test_in_progress_unnumbered_subject_fallback_id(self):
        """subject 无编号的进行中任务 → current 回退 "#创建序" 表示。"""
        from core.dashboard.data import run_task_progress
        self._write_run(
            [f"grouped task {i}" for i in range(3)],
            [], in_progress_task_ids=[2])
        rp = run_task_progress(self.proot, "demo")
        self.assertEqual(rp, {"done": 0, "total": 3, "current": ["#2"]})

    def test_terminal_run_current_suppressed(self):
        """终态 run（interrupted/cancelled/result/error）不携带进行中任务。

        run-progress-current 是实时线索，仅对仍在产事件的 run 有意义。被启动
        清扫补写 interrupted 终态的僵尸 run 曾把残留 in_progress 带成 pushed
        spec 的「进行中 1.2」（2026-09-06 实证：清扫追加终态行抬高 mtime 使
        find_impl_run_file 选中僵尸文件，残留 in_progress 外显到已推送 SPEC）。
        """
        from core.dashboard.data import run_task_progress
        for terminal in ({"type": "interrupted", "reason": "startup terminal-state sweep"},
                         {"type": "cancelled", "reason": "user cancel"},
                         {"type": "result", "result": "ok"},
                         {"type": "error", "error": "boom"}):
            with self.subTest(terminal=terminal["type"]):
                self._write_run(
                    [f"Task 1.{i}: t{i}" for i in range(1, 3)],
                    [], in_progress_task_ids=[1], terminal_event=terminal)
                rp = run_task_progress(self.proot, "demo")
                self.assertEqual(rp, {"done": 0, "total": 2, "current": []})


if __name__ == "__main__":
    unittest.main()
