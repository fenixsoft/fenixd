"""task-track 三层治理测试（tasks-md-tracking）：

R1 写入端格式契约：schema tasks instruction 的 MUST 约定（编号 + 点号）
R2 晋升 lint：lint_tasks_parseable 单元行为 + engine 并列调用语义
R3 解析端显式提示：CLI 警告行 + dashboard tasks_note 字段
附带：存量 spec tasks.md 零误拔回归（spec/changes/ 含 archive 全量枚举）。
"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.deliverables import lint_tasks_parseable
from core.spec_gen import instructions, new_change, status

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _mk_change(root: Path, name: str) -> Path:
    new_change(root, name)
    return root / "spec" / "changes" / name


def _write_tasks(spec_dir: Path, text: str) -> None:
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "tasks.md").write_text(text, encoding="utf-8")


# ── R1 写入端格式契约 ──────────────────────────────────────────────────


class TestInstructionContract(unittest.TestCase):
    """tasks 生成指引必须固化 `## <编号>. <标题>` MUST 约定（task-track R1）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.pr = Path(self.tmpdir)
        self.change = "demo"
        _mk_change(self.pr, self.change)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _ins(self):
        return instructions(self.pr, "tasks", self.change)

    def test_instruction_contains_must_number_dot(self):
        ins = self._ins()
        text = ins["instruction"]
        self.assertIn("MUST", text)
        self.assertIn("编号", text)
        self.assertIn("点号", text)
        self.assertIn("## 1.", text)

    def test_template_group_headings_are_numbered_dotted(self):
        template = self._ins()["template"]
        headings = [
            line for line in template.split("\n") if line.startswith("## ")
        ]
        self.assertTrue(headings, "template 应含分组标题示例")
        for line in headings:
            self.assertRegex(line, r"^## \d+\. ")

    def test_instructions_and_status_zero_regression(self):
        # 存量契约：字段结构与既有调用方（fenix_spec.py CLI / fenix-new skill）不变
        ins = self._ins()
        for key in ("changeName", "artifactId", "outputPath", "instruction",
                    "template", "dependencies", "unlocks"):
            self.assertIn(key, ins)
        self.assertEqual(ins["outputPath"], "tasks.md")
        self.assertEqual(ins["changeName"], self.change)
        st = status(self.pr, self.change)
        self.assertIn("artifacts", st)
        ids = {a["id"] for a in st["artifacts"]}
        self.assertIn("tasks", ids)


# ── R2 晋升 lint ───────────────────────────────────────────────────────


class TestLintTasksParseable(unittest.TestCase):
    """lint_tasks_parseable 单元行为（与下游解析正则同源，点号可选双格式）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.pr = Path(self.tmpdir)
        self.spec_dir = self.pr / "spec" / "changes" / "demo"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_missing_tasks_md_passes(self):
        self.assertEqual(lint_tasks_parseable(self.spec_dir, self.pr), [])

    def test_unnumbered_group_is_violation(self):
        _write_tasks(self.spec_dir, "# Tasks\n\n## 事项\n\n- [ ] 1.1 do it\n")
        violations = lint_tasks_parseable(self.spec_dir, self.pr)
        self.assertEqual(len(violations), 1)
        self.assertIn("tasks.md", violations[0])

    def test_empty_file_is_violation(self):
        _write_tasks(self.spec_dir, "")
        violations = lint_tasks_parseable(self.spec_dir, self.pr)
        self.assertEqual(len(violations), 1)
        self.assertIn("tasks.md", violations[0])

    def test_prose_only_is_violation(self):
        _write_tasks(self.spec_dir, "# Tasks\n\n随便写点说明，没有分组标题。\n")
        violations = lint_tasks_parseable(self.spec_dir, self.pr)
        self.assertEqual(len(violations), 1)

    def test_dotted_historical_format_passes(self):
        _write_tasks(
            self.spec_dir,
            "## 1. Setup\n\n- [ ] 1.1 a\n\n## 2. Core\n\n- [ ] 2.1 b\n",
        )
        self.assertEqual(lint_tasks_parseable(self.spec_dir, self.pr), [])

    def test_undotted_historical_format_passes(self):
        _write_tasks(
            self.spec_dir,
            "## 1 Setup\n\n- [ ] 1.1 a\n\n## 2 Core\n\n- [ ] 2.1 b\n",
        )
        self.assertEqual(lint_tasks_parseable(self.spec_dir, self.pr), [])

    def test_damaged_prefix_with_valid_groups_is_violation(self):
        """分组存在但任务行全部带损伤前缀（^- [x]）应触发违规（task-track R2 relint）。"""
        _write_tasks(
            self.spec_dir,
            "# Tasks\n\n## 1. Setup\n\n^- [x] 1.1 a\n^- [x] 1.2 b\n\n"
            "## 2. Core\n\n^- [x] 2.1 c\n",
        )
        violations = lint_tasks_parseable(self.spec_dir, self.pr)
        self.assertEqual(len(violations), 1)
        self.assertIn("tasks.md", violations[0])
        self.assertIn("任务分组", violations[0])
        # 修正处方须提及 `- [ ]` 或 `- [x]` 行首形态
        self.assertIn("- [ ]", violations[0])
        self.assertIn("- [x]", violations[0])
        # 点名损伤特征 `^-`
        self.assertIn("^-", violations[0])

    def test_damaged_prefix_no_tasks_is_violation(self):
        """分组存在但任务行为空（无 checkbox）也应触发违规。"""
        _write_tasks(
            self.spec_dir,
            "# Tasks\n\n## 1. Setup\n\nsome prose\n\n## 2. Core\n\nmore prose\n",
        )
        violations = lint_tasks_parseable(self.spec_dir, self.pr)
        self.assertEqual(len(violations), 1)
        self.assertIn("tasks.md", violations[0])

    def test_deliverables_block_with_numbered_groups_passes(self):
        # 本仓库 tasks.md 既有形态：## Deliverables 声明段 + 编号分组
        _write_tasks(
            self.spec_dir,
            "# Tasks\n\n## Deliverables\n\n```yaml\n"
            "- path: core/x.py\n  kind: new\n```\n\n## 1. 实现\n\n- [ ] 1.1 a\n",
        )
        self.assertEqual(lint_tasks_parseable(self.spec_dir, self.pr), [])


class TestPromotionLintTasks(unittest.TestCase):
    """engine._on_spec_drafted 并列调用 tasks.md 可解析性 lint（task-track R2）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.pr = Path(self.tmpdir)
        from core.pm_engine import PMEngine
        from core.state_machine import StateMachine
        self.logger = MagicMock()
        (self.pr / ".fenix").mkdir(parents=True, exist_ok=True)
        self.sm = StateMachine(self.pr / ".fenix" / "STATE.md", self.logger)
        self.engine = PMEngine(self.sm, MagicMock(), {}, self.pr, self.logger)
        self.engine._on_spec_ready = MagicMock()
        self.spec_dir = self.pr / "spec" / "changes" / "demo"
        self.sm.add_spec("demo", {"priority": 5})

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _entry(self):
        return self.sm.read_one("demo")

    def test_unparseable_tasks_md_blocks_promotion(self):
        _write_tasks(self.spec_dir, "# Tasks\n\n## 事项\n\n- [ ] 1.1 x\n")

        self.engine._on_spec_drafted("demo")

        entry = self._entry()
        self.assertEqual(entry["status"], "drafted")
        self.assertIn("tasks.md", entry["error"])
        self.engine._on_spec_ready.assert_not_called()

    def test_dual_historical_formats_promote(self):
        # 点号可选双历史格式均不拦（分两个 change 验证）
        for name, heading in (("demo-dotted", "## 1. 标题"),
                              ("demo-undotted", "## 1 标题")):
            self.sm.add_spec(name, {"priority": 5})
            _write_tasks(self.pr / "spec" / "changes" / name,
                         f"{heading}\n\n- [ ] 1.1 a\n")
            self.engine._on_spec_drafted(name)
            self.assertEqual(self.sm.read_one(name)["status"], "ready", name)

    def test_fix_then_repromote_succeeds(self):
        _write_tasks(self.spec_dir, "## 事项\n\n- [ ] 1.1 x\n")
        self.engine._on_spec_drafted("demo")
        self.assertEqual(self._entry()["status"], "drafted")

        _write_tasks(self.spec_dir, "## 1. 修正后\n\n- [ ] 1.1 x\n")
        self.engine._on_spec_drafted("demo")
        self.assertEqual(self._entry()["status"], "ready")
        self.engine._on_spec_ready.assert_called_once_with("demo")

    def test_lint_crash_fails_open(self):
        _write_tasks(self.spec_dir, "## 事项\n")
        with patch("core.deliverables.lint_tasks_parseable",
                   side_effect=OSError("disk gone")):
            self.engine._on_spec_drafted("demo")
        self.assertEqual(self._entry()["status"], "ready")
        self.engine._on_spec_ready.assert_called_once_with("demo")
        self.logger.warning.assert_called()

    def test_missing_tasks_md_promotes(self):
        self.engine._on_spec_drafted("demo")
        self.assertEqual(self._entry()["status"], "ready")


class TestExistingSpecsZeroMisfire(unittest.TestCase):
    """存量 spec tasks.md 全量回归：lint 零误拦（task-track 2.4）。"""

    def test_all_existing_tasks_md_pass_lint(self):
        changes_dir = PROJECT_ROOT / "spec" / "changes"
        tasks_files = sorted(changes_dir.rglob("tasks.md"))
        self.assertTrue(tasks_files, "仓库应存在存量 tasks.md")
        misfired = []
        for tf in tasks_files:
            violations = lint_tasks_parseable(tf.parent, PROJECT_ROOT)
            if violations:
                misfired.append((str(tf.relative_to(PROJECT_ROOT)), violations))
        self.assertEqual(
            misfired, [],
            f"存量 spec 存在 lint 误拦: {misfired}",
        )


# ── R3 解析端显式提示 ──────────────────────────────────────────────────


class TestCliWarning(unittest.TestCase):
    """fenix_process.py CLI 三态：正常解析 / 空解析警告 / 无文件静默。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.pr = Path(self.tmpdir)
        # fenix_process.py 的 PROJECT_ROOT 按 `.fenix/bin/` 部署布局推断
        # （__file__.parent.parent.parent），夹具复刻同构布局。
        # tui-triage-revamp 起脚本复用 core/dashboard/data.py 数据层——
        # 真实部署每个项目都有 .fenix/core（agent-config 部署），夹具同构补齐。
        (self.pr / ".fenix" / "bin").mkdir(parents=True)
        shutil.copy(PROJECT_ROOT / "bin" / "fenix_process.py",
                    self.pr / ".fenix" / "bin" / "fenix_process.py")
        try:
            (self.pr / ".fenix" / "core").symlink_to(
                PROJECT_ROOT / ".fenix" / "core", target_is_directory=True)
        except OSError:
            shutil.copytree(PROJECT_ROOT / ".fenix" / "core",
                            self.pr / ".fenix" / "core",
                            ignore=shutil.ignore_patterns("__pycache__"))
        (self.pr / ".fenix" / "STATE.md").write_text(
            "# Fenixd State\n\n## Specs\n\n"
            "### cli-a\n\n- status: drafted\n- priority: 5\n\n"
            "### cli-b\n\n- status: drafted\n- priority: 5\n\n"
            "### cli-c\n\n- status: drafted\n- priority: 5\n",
            encoding="utf-8",
        )
        changes = self.pr / "spec" / "changes"
        _write_tasks(changes / "cli-a",
                     "## 1. 分组\n\n- [ ] 1.1 任务项\n")
        _write_tasks(changes / "cli-b",
                     "# Tasks\n\n## 事项\n\n- [ ] 1.1 任务项\n")
        # cli-c：无 tasks.md

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run(self, spec: str) -> str:
        result = subprocess.run(
            [sys.executable, str(self.pr / ".fenix" / "bin" / "fenix_process.py"), spec],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_unparseable_tasks_md_prints_warning(self):
        out = self._run("cli-b")
        self.assertIn("tasks.md", out)
        self.assertIn("未解析出任务", out)
        # 其余区块不受影响
        self.assertIn("下一步", out)

    def test_parseable_tasks_md_no_warning(self):
        out = self._run("cli-a")
        self.assertIn("tasks.md 进展", out)
        self.assertNotIn("未解析出任务", out)

    def test_missing_tasks_md_silent(self):
        out = self._run("cli-c")
        self.assertNotIn("tasks.md 进展", out)
        self.assertNotIn("未解析出任务", out)

    def test_undotted_format_still_parses(self):
        # 点号可选兼容：无点号分组正常展示任务区块（不触发警告）
        _write_tasks(self.pr / "spec" / "changes" / "cli-a",
                     "## 1 分组\n\n- [ ] 1.1 任务项\n")
        out = self._run("cli-a")
        self.assertIn("tasks.md 进展", out)
        self.assertNotIn("未解析出任务", out)


class TestDashboardTasksNote(unittest.TestCase):
    """dashboard tasks_note 字段：三态（正常 None / 空解析提示 / 无文件 None）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.pr = Path(self.tmpdir)
        (self.pr / ".fenix").mkdir(parents=True, exist_ok=True)
        changes = self.pr / "spec" / "changes"
        _write_tasks(changes / "a",
                     "## 1. 分组\n\n- [ ] 1.1 任务项\n")
        _write_tasks(changes / "b",
                     "# Tasks\n\n## 事项\n\n- [ ] 1.1 任务项\n")
        _write_tasks(changes / "d",
                     "## 1 分组\n\n- [ ] 1.1 任务项\n")
        # c：无 tasks.md

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _note(self, spec: str):
        from core.dashboard.data import tasks_note
        return tasks_note(self.pr, spec)

    def test_parseable_is_none(self):
        self.assertIsNone(self._note("a"))

    def test_unparseable_gets_note(self):
        note = self._note("b")
        self.assertIsNotNone(note)
        self.assertIn("未解析出任务", note)

    def test_missing_is_none(self):
        self.assertIsNone(self._note("c"))

    def test_undotted_format_is_none(self):
        self.assertIsNone(self._note("d"))

    def test_spec_detail_includes_tasks_note(self):
        from core.dashboard.data import spec_detail
        from core.state_machine import StateMachine
        sm = StateMachine(self.pr / ".fenix" / "STATE.md", MagicMock())
        sm.add_spec("b", {"priority": 5})
        entry = sm.read_one("b")
        detail = spec_detail(self.pr, "b", entry)
        self.assertIn("tasks_note", detail)
        self.assertIn("未解析出任务", detail["tasks_note"])
        self.assertEqual(detail["tasks"], [])


if __name__ == "__main__":
    unittest.main()
