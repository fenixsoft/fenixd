"""tests/test_prompt_harness_notes.py — add-dsh-adapter-integration 6.3 快照测试。

两条字面验收：
1. **claude 通道组装 prompt 与改造前逐字节一致**。改造面恰三处：
   ``_noninteractive_contract_section`` / ``_long_task_wait_bullets`` 的
   ``{harness_notes}`` 替换位、``agents/implementer.md`` 长任务等待节占位符化。
   本测试把三处分别与 git HEAD（改造前）版本做字节等值对照（模板差异锁定为
   单行占位符替换 + claude 注入值逐字节还原原句）；其余 prompt 表面未改动
   （同模块同函数体），组合即得「组装 prompt 逐字节一致」。
2. **claude/dsh 两通道同车道 prompt 差异仅落 harness_notes 段**：把 dsh 注入
   值回替成 claude 注入值后，两通道各段输出逐字节相等；任务进度契约段（Task
   工具族契约）两通道一字不改。
"""

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent

from core.agent_runner.harness import ClaudeAdapter, DshAdapter, set_current_adapter
from core.agent_runner.prompt_builder import CLAUDE_HARNESS_NOTES, PromptBuilder


def _head_text(rel: str) -> str:
    """git HEAD（改造前基线）版本的文件原文。"""
    out = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=ROOT,
                         capture_output=True, check=True)
    return out.stdout.decode("utf-8")


def _load_head_prompt_builder(tmp_path: Path):
    """加载 HEAD 版 prompt_builder 模块（独立模块名，不污染 sys.modules）。"""
    src = tmp_path / "_prompt_builder_at_head.py"
    src.write_text(_head_text("core/agent_runner/prompt_builder.py"),
                   encoding="utf-8")
    spec = importlib.util.spec_from_file_location("_prompt_builder_at_head", src)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_pb(tmp_path: Path) -> PromptBuilder:
    proot = tmp_path / "project"
    proot.mkdir(parents=True, exist_ok=True)
    (proot / ".fenix").mkdir(parents=True, exist_ok=True)
    pm = MagicMock()
    pm.project_root = proot
    pm.config = {}
    return PromptBuilder(pm)


class TestClaudeByteIdentity(unittest.TestCase):
    """claude 通道零差异快照（对照 git HEAD 改造前版本）。"""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.mkdtemp(prefix="harness-notes-snap-")
        self.tmp_path = Path(self._tmp)
        self.old_mod = _load_head_prompt_builder(self.tmp_path)
        self.new_pb = _make_pb(self.tmp_path)
        self.old_pb = self.old_mod.PromptBuilder(
            MagicMock(project_root=self.new_pb._pm.project_root, config={}))
        # claude 通道：显式注入 ClaudeAdapter（无 harness_notes 成员 → 回落
        # CLAUDE_HARNESS_NOTES 常量），防其他用例泄漏 dsh 进程级持有
        self._prev = None
        from core.agent_runner.harness import get_current_adapter
        self._prev = get_current_adapter()
        set_current_adapter(ClaudeAdapter())

    def tearDown(self):
        set_current_adapter(self._prev)
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_noninteractive_contract_section_bytes(self):
        self.assertEqual(self.new_pb._noninteractive_contract_section(),
                         self.old_pb._noninteractive_contract_section())
        # 注入值逐字节 = 改造前原文
        self.assertEqual(CLAUDE_HARNESS_NOTES, "`claude -p`")
        self.assertIn("headless agent**（`claude -p`）：",
                      self.new_pb._noninteractive_contract_section())

    def test_long_task_wait_bullets_bytes(self):
        self.assertEqual(self.new_pb._long_task_wait_bullets(),
                         self.old_pb._long_task_wait_bullets())
        self.assertIn("非交互派发（`claude -p`）下",
                      self.new_pb._long_task_wait_bullets())

    def test_implementer_md_diff_confined_to_placeholder(self):
        """agents/implementer.md 改造前后差异锁定为单行占位符替换。"""
        old_md = _head_text("agents/implementer.md")
        new_md = (ROOT / "agents" / "implementer.md").read_text(encoding="utf-8")
        self.assertEqual(
            new_md,
            old_md.replace("在非交互派发（`claude -p`）下不产生唤醒",
                           "在非交互派发（{harness_notes}）下不产生唤醒"),
        )
        self.assertEqual(new_md.count("{harness_notes}"), 1)

    def test_fill_placeholders_restores_original_line(self):
        """claude 注入值填充后逐字节还原改造前原句，且无占位符残留。"""
        new_md = (ROOT / "agents" / "implementer.md").read_text(encoding="utf-8")
        filled = self.new_pb._fill_placeholders(new_md, "implementer",
                                                "demo-spec", None)
        self.assertIn("在非交互派发（`claude -p`）下不产生唤醒", filled)
        self.assertNotIn("{harness_notes}", filled)


class TestDshDiffConfinedToNotes(unittest.TestCase):
    """claude/dsh 两通道差异仅落 {harness_notes} 替换位。"""

    NOTES_DSH = DshAdapter().harness_notes()

    def setUp(self):
        import tempfile
        self._tmp = tempfile.mkdtemp(prefix="harness-notes-dsh-")
        self.tmp_path = Path(self._tmp)
        self.pb = _make_pb(self.tmp_path)
        from core.agent_runner.harness import get_current_adapter
        self._prev = get_current_adapter()
        set_current_adapter(DshAdapter())

    def tearDown(self):
        set_current_adapter(self._prev)
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_notes_values_differ(self):
        self.assertNotEqual(self.NOTES_DSH, CLAUDE_HARNESS_NOTES)
        self.assertIn("dsh headless --json", self.NOTES_DSH)

    def _assert_diff_confined(self, claude_section: str, dsh_section: str):
        # 注入位同形替换（「非交互派发（<notes>）下」等）：dsh 值回替成 claude
        # 值后两通道逐字节相等 ⇒ 差异全部收敛在 harness_notes 替换位
        self.assertNotEqual(claude_section, dsh_section)
        self.assertEqual(dsh_section.replace(self.NOTES_DSH, CLAUDE_HARNESS_NOTES),
                         claude_section)

    def test_noninteractive_contract_section_diff(self):
        self._assert_diff_confined(
            _claude_section(self.tmp_path, "noninteractive"),
            self.pb._noninteractive_contract_section())

    def test_long_task_wait_bullets_diff(self):
        self._assert_diff_confined(_claude_section(self.tmp_path, "longtask"),
                                   self.pb._long_task_wait_bullets())

    def test_task_progress_contract_identical_across_channels(self):
        """Task 工具族契约段一字不改：两通道字节相等（6.1 约束）。"""
        set_current_adapter(ClaudeAdapter())
        claude_tp = self.pb._task_progress_contract_section("demo-spec")
        set_current_adapter(DshAdapter())
        dsh_tp = self.pb._task_progress_contract_section("demo-spec")
        self.assertEqual(claude_tp, dsh_tp)
        self.assertIn("任务进度契约", claude_tp)
        # 该段不携带 harness 注入位（差异面外）
        self.assertNotIn(self.NOTES_DSH, claude_tp)

    def test_filled_template_carries_dsh_notes(self):
        new_md = (ROOT / "agents" / "implementer.md").read_text(encoding="utf-8")
        filled = self.pb._fill_placeholders(new_md, "implementer",
                                            "demo-spec", None)
        self.assertIn(f"在非交互派发（{self.NOTES_DSH}）下不产生唤醒", filled)
        self.assertNotIn("{harness_notes}", filled)


def _claude_section(tmp_path: Path, which: str) -> str:
    """claude 通道输出同段（独立 builder，规避用例间进程级状态耦合）。"""
    prev_adapter = None
    from core.agent_runner.harness import get_current_adapter
    prev_adapter = get_current_adapter()
    set_current_adapter(ClaudeAdapter())
    try:
        pb = _make_pb(tmp_path)
        if which == "noninteractive":
            return pb._noninteractive_contract_section()
        return pb._long_task_wait_bullets()
    finally:
        set_current_adapter(prev_adapter)


if __name__ == "__main__":
    unittest.main()
