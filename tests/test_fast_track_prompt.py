"""fast-track prompt 契约注入测试（worktree-reuse / scenario-id-contract）。

fix-implementer-task-progress 三连打回事故治理：
  1. fast-track prompt 注入场景 ID 契约（设计集 ⊆ 执行集，逐字一致）
  2. 注入当前设计集 ID 清单（硬校验比对基准的 prompt 侧可见性）
  3. prev_error 注入对齐 implementer 分支（打回原因可见）
  4. worktree 继承说明（仅复用 worktree 时注入）
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import StateMachine
from test_agent_runner import FakeLogger, make_runner


def _mk_spec_dir(proot: Path, name: str) -> None:
    d = proot / "spec" / "changes" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "tasks.md").write_text("# Tasks\n\n- [ ] 1.1 do it\n", encoding="utf-8")


class TestFastTrackPromptScenarioContract:
    def test_prompt_contains_scenario_id_contract(self, tmp_path):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_prompt("demo", "fast-track")
        assert "场景 ID 契约" in prompt
        assert "逐字一致" in prompt
        assert "test_scenarios.json" in prompt
        assert "打回重派" in prompt

    def test_prompt_injects_designed_ids(self, tmp_path):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        vp = proot / ".fenix" / "verify-progress" / "demo"
        vp.mkdir(parents=True, exist_ok=True)
        (vp / "test_scenarios.json").write_text(json.dumps([
            {"id": "detail-run-clue-ahead", "description": "d", "steps": [], "assertions": []},
            {"id": "run-hint-list-visible", "description": "d", "steps": [], "assertions": []},
        ]), encoding="utf-8")
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_prompt("demo", "fast-track")
        assert "detail-run-clue-ahead" in prompt
        assert "run-hint-list-visible" in prompt

    def test_no_designed_ids_line_when_file_missing(self, tmp_path):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_prompt("demo", "fast-track")
        assert "当前设计集（上一轮遗留" not in prompt


class TestFastTrackPromptPrevError:
    def test_prev_error_injected(self, tmp_path):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        sm = StateMachine(tmp_path / "STATE.md", FakeLogger())
        sm.add_spec("demo", {"priority": 5})
        sm.update_spec("demo", {"error": "场景静默遗漏：s1（设计集存在但执行集缺失）"})
        runner = make_runner(proot)
        runner.state_machine = sm
        prompt = runner._prompt_builder._build_prompt("demo", "fast-track")
        assert "Previous run error" in prompt
        assert "场景静默遗漏：s1" in prompt

    def test_no_prev_error_when_clean(self, tmp_path):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        sm = StateMachine(tmp_path / "STATE.md", FakeLogger())
        sm.add_spec("demo", {"priority": 5})
        runner = make_runner(proot)
        runner.state_machine = sm
        prompt = runner._prompt_builder._build_prompt("demo", "fast-track")
        assert "Previous run error" not in prompt


class TestFastTrackPromptReuseNote:
    def test_reuse_note_injected_when_reuse_recorded(self, tmp_path):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        runner = make_runner(proot)
        wm = MagicMock()
        wm.get_reuse_record.return_value = {
            "path": "/tmp/wt-demo", "branch": "fenix/demo-1",
        }
        runner.worktree_manager = wm
        prompt = runner._prompt_builder._build_prompt("demo", "fast-track")
        assert "Worktree 继承" in prompt
        assert "不要重做已完成的工作" in prompt

    def test_no_reuse_note_without_record(self, tmp_path):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_prompt("demo", "fast-track")
        assert "Worktree 继承" not in prompt

    def test_reuse_note_without_recovery_marker(self, tmp_path):
        """复用痕迹存在但**无恢复来源标记**（普通打回重派/瞬断重试轮）：
        fast-track prompt 仍含「Worktree 继承」段、MUST NOT 含「中断恢复续做」
        ——不以来源判据区分时该用例会假绿（design D6），此处为回归用例。"""
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        runner = make_runner(proot)
        wm = MagicMock()
        wm.get_reuse_record.return_value = {
            "path": "/tmp/wt-demo", "branch": "fenix/demo-1",
        }
        runner.worktree_manager = wm
        prompt = runner._prompt_builder._build_prompt("demo", "fast-track")
        assert "Worktree 继承" in prompt, "普通复用轮必须保留既有继承注记"
        assert "中断恢复续做" not in prompt, \
            "无恢复来源标记时不得注入「曾因 daemon 重启被中断」的错误归因"

    def test_recovery_note_when_recovery_marker(self, tmp_path):
        """记录带恢复来源标记：fast-track prompt 注入「中断恢复续做」，
        「Worktree 继承」段不出现（语义重叠，择一注入）。"""
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        runner = make_runner(proot)
        wm = MagicMock()
        wm.get_reuse_record.return_value = {
            "path": "/tmp/wt-demo",
            "branch": "fenix/demo-1",
            "recovery": True,
        }
        runner.worktree_manager = wm
        prompt = runner._prompt_builder._build_prompt("demo", "fast-track")
        assert "中断恢复续做" in prompt
        assert "不要重做已完成的工作" in prompt
        assert "Worktree 继承" not in prompt, "恢复续做注记优先，不得重复注入"
