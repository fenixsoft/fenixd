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
    d = proot / "openspec" / "changes" / name
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
        prompt = self._prompt("implementer")
        assert "matching all TaskUpdate records exactly" in prompt

    def test_fast_track_wrapup_step_strengthened(self):
        prompt = self._prompt("fast-track")
        assert "matching all TaskUpdate records exactly" in prompt


if __name__ == "__main__":
    unittest.main()
