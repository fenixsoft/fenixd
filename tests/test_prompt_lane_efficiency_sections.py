"""tests/test_prompt_lane_efficiency_sections.py — fix-agent-lane-efficiency：三段效率契约段注入与顺序测试。

断言三条效率/取证深度/长任务段在对应车道的注入与顺序不变式。
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.agent_runner.prompt_builder import PromptBuilder


def _make_prompt_builder(tmp_path: Path) -> PromptBuilder:
    """构建最小的 PromptBuilder 实例（三个效率段为纯静态文本，零 IO，mock pm 即可）。"""
    proot = tmp_path / "project"
    proot.mkdir(parents=True)
    (proot / ".fenix").mkdir(parents=True)
    pm = MagicMock()
    pm.project_root = proot
    pm.config = {}
    return PromptBuilder(pm)


class TestToolCallEfficiencySection:
    """工具调用效率段注入测试。"""

    @pytest.mark.parametrize("agent_type", ["implementer", "fast-track", "spec-review"])
    def test_lanes_inject_efficiency(self, tmp_path, agent_type):
        """Scenario: 三车道 prompt 均含「工具调用效率」契约段。"""
        pb = _make_prompt_builder(tmp_path)
        section = pb._tool_call_efficiency_section(agent_type)
        assert "工具调用效率" in section
        assert "批量并行" in section
        assert "定向读取" in section
        assert "同 run 去重" in section

    def test_other_agent_zero_injection(self, tmp_path):
        """Scenario: 其它车道（planner-judge）零注入。"""
        pb = _make_prompt_builder(tmp_path)
        assert pb._tool_call_efficiency_section("planner-judge") == ""


class TestForensicDepthSection:
    """取证深度上限与输出裁剪段注入测试。"""

    @pytest.mark.parametrize("agent_type", ["implementer", "fast-track", "spec-review"])
    def test_lanes_inject_forensic(self, tmp_path, agent_type):
        """Scenario: 三车道 prompt 均含「取证深度上限与输出裁剪」段。"""
        pb = _make_prompt_builder(tmp_path)
        section = pb._forensic_depth_section(agent_type)
        assert "取证深度上限" in section
        assert "输出裁剪" in section
        assert "最小可判反证" in section

    def test_other_agent_zero_injection(self, tmp_path):
        """Scenario: planner-judge 零注入。"""
        pb = _make_prompt_builder(tmp_path)
        assert pb._forensic_depth_section("planner-judge") == ""


class TestLongTaskWaitSection:
    """长任务前台等待段注入测试。"""

    @pytest.mark.parametrize("agent_type", ["implementer", "fast-track"])
    def test_impl_lanes_inject_long_task(self, tmp_path, agent_type):
        """Scenario: 实现者两车道 prompt 含「长任务前台等待」段。

        2026-09-21 更正（writepath 冻结事故）：旧文案「后台完成通知真实可用」
        被证伪——非交互派发下一次 turn 结束即杀后台子进程。现文案 MUST 明确
        通知不送达 + 有界入口前台直跑。
        """
        pb = _make_prompt_builder(tmp_path)
        section = pb._long_task_wait_section(agent_type)
        assert "长任务前台等待" in section
        assert "run_in_background" in section
        assert "完成通知" in section
        assert "不会送达" in section  # 能力事实更正：通知不可依赖
        assert "ScheduleWakeup" in section
        assert "sleep" in section  # MUST NOT 用 sleep 自旋
        assert "启动即忘" in section  # 后台启动+等通知等价于启动即忘

    @pytest.mark.parametrize("agent_type", ["spec-review", "planner-judge", "planner-plan", "verifier"])
    def test_non_impl_lanes_zero_injection(self, tmp_path, agent_type):
        """Scenario: 非实现者车道零注入。"""
        pb = _make_prompt_builder(tmp_path)
        assert pb._long_task_wait_section(agent_type) == ""


class TestEfficiencyLaneList:
    """_EFFICIENCY_LANES 覆盖三车道。"""

    def test_efficiency_lanes_are_implementer_fast_track_spec_review(self, tmp_path):
        pb = _make_prompt_builder(tmp_path)
        assert "implementer" in pb._EFFICIENCY_LANES
        assert "fast-track" in pb._EFFICIENCY_LANES
        assert "spec-review" in pb._EFFICIENCY_LANES
        assert "planner-judge" not in pb._EFFICIENCY_LANES


class TestInjectionOrderInvariant:
    """动态段注入位置不变式：位于项目级附加段之前。"""

    def test_impl_sections_before_project_extra(self, tmp_path):
        """Scenario: 实现者 prompt 的动态契约段位于非交互契约段之后。"""
        proot = tmp_path / "project"
        proot.mkdir(parents=True)
        vp = proot / ".fenix" / "verify-progress" / "demo"
        vp.mkdir(parents=True)
        spec_dir = proot / "spec" / "changes" / "demo"
        spec_dir.mkdir(parents=True)
        pm = MagicMock()
        pm.project_root = proot
        pm.config = {}
        from core.agent_runner.prompt_builder import PromptBuilder

        pb = PromptBuilder(pm)
        wt = tmp_path / "wt-demo"
        wt.mkdir(parents=True)
        prompt = pb._build_prompt("demo", "implementer", wt_path=wt)
        # 动态契约段（工具调用效率/取证深度上限/长任务前台等待）
        # 注入位置：非交互契约段之后、项目级附加段之前。模板本体（agents/
        # implementer.md）可能含效率措辞（task 3.4 同步），故以非交互契约段
        # 之后的片段校验三段的相对顺序（动态段追加顺序：效率→取证→长任务）。
        # 使用 rfind() 定位动态注入段（模板中可能出现同名文本前缀，但动态段在
        # prompt 尾部、非交互契约之后，用 rfind 取最后出现即动态注入位置）。
        noninter_pos = prompt.rfind("非交互契约")
        assert noninter_pos > 0, "非交互契约段未找到"
        # 检查动态段全部出现在非交互契约段之后（使用 rfind 定位最后出现位置）
        assert prompt.rfind("工具调用效率") > noninter_pos
        assert prompt.rfind("取证深度上限") > noninter_pos
        assert prompt.rfind("长任务前台等待") > noninter_pos
        # 三段相对顺序：效率 → 取证 → 长任务
        assert prompt.rfind("工具调用效率") < prompt.rfind("取证深度上限") < prompt.rfind("长任务前台等待")
