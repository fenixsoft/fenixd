"""agent 非交互契约段测试（fix-agent-noninteractive-contract）。

覆盖 spec 全部 Scenario：
- 模板型 agent 的提示词含契约段（参数化遍历 AGENT_PROMPT_FILES 全键）；
- 独立构建路径的 agent 提示词含契约段（repair/self-review/evolution 直调）；
- 非交互契约段的关键语义（四组规范性语义逐串在场）；
- 契约段幂等可重复注入（同一 PromptBuilder 连调两次返回相等字符串）。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent_runner.prompt_builder import AGENT_PROMPT_FILES, PromptBuilder
from test_agent_runner import make_runner


# 契约段关键锚点串（与 _noninteractive_contract_section 文本一一对应）
CONTRACT_TITLE = "非交互契约"
ANCHORS = (
    "非交互契约",  # 标题
    "没有能回答你的人",  # 无人类可交互
    "无人值守",  # 无人值守运行
    "直接执行",  # 不请求批准
    "不请求批准",
    "等人回复",  # 禁止为等待回复而结束回合
    "end_turn",
    "失败出口",
    "interactive agent",  # 显式覆盖系统提示词默认框架
    "不适用",
)


def _mk_spec_dir(proot: Path, name: str) -> None:
    d = proot / "spec" / "changes" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "tasks.md").write_text("# Tasks\n\n- [ ] 1.1 do it\n", encoding="utf-8")


# ── 模板型 agent：_build_prompt 统一收尾注入 ───────────────────────────


class TestTemplateAgentsContainContract:
    """Scenario: 模板型 agent 的提示词含契约段。

    参数化遍历 AGENT_PROMPT_FILES 全键（含走独立构建路径的 self-review /
    evolution——两者同样在各自 return 前追加契约段），断言提示词含契约段
    关键锚点串。
    """

    @pytest.mark.parametrize("agent_type", sorted(AGENT_PROMPT_FILES))
    def test_every_template_agent_prompt_has_contract(self, tmp_path, agent_type):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_prompt("demo", agent_type)
        assert prompt
        assert CONTRACT_TITLE in prompt, f"{agent_type} 提示词缺契约段标题"
        assert "没有" in prompt, f"{agent_type} 提示词缺无人类语义串"
        assert "无人" in prompt, f"{agent_type} 提示词缺无人值守语义串"

    @pytest.mark.parametrize("agent_type", sorted(AGENT_PROMPT_FILES))
    def test_all_anchors_present(self, tmp_path, agent_type):
        """契约段全部锚点串在每类 agent 提示词中均在位。"""
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_prompt("demo", agent_type)
        for anchor in ANCHORS:
            assert anchor in prompt, f"{agent_type} 提示词缺锚点串: {anchor}"

    def test_project_extra_still_last(self, tmp_path):
        """项目级附加段仍位于 prompt 末尾（契约段不得插到其后）。"""
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        extra_dir = proot / ".fenix" / "agents"
        extra_dir.mkdir(parents=True)
        (extra_dir / "verifier.md").write_text(
            "- 项目附加规则：登录页用 /login 路径。\n", encoding="utf-8")
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_prompt("demo", "verifier")
        # 契约段在项目附加段之前：附加段内容须位于契约段内容之后
        assert prompt.index("项目附加提示词") > prompt.index(CONTRACT_TITLE)
        assert prompt.rstrip().endswith("/login 路径。")

    def test_contract_section_after_dynamic_section(self, tmp_path):
        """契约段位于动态段（verifier 断点续跑段）之后。"""
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        vp = proot / ".fenix" / "verify-progress"
        vp.mkdir(parents=True, exist_ok=True)
        (vp / "demo.json").write_text(
            '{"total": 5, "done": 2, "current": "场景2"}', encoding="utf-8")
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_prompt("demo", "verifier")
        assert prompt.index("RESUME CHECKPOINT") < prompt.index(CONTRACT_TITLE)


# ── 独立构建路径：repair / self-review / evolution ────────────────────


class TestIndependentBuildPathsContainContract:
    """Scenario: 独立构建路径的 agent 提示词含契约段。

    三条路径不走 _build_prompt 统一收尾，各自在 return 前追加契约段——
    直调构建函数断言契约段锚点串在场。
    """

    def test_repair_prompt_has_contract(self, tmp_path):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_repair_prompt(
            "demo", {"conflict_paths": ["core/a.py"], "repair_round": 1})
        assert CONTRACT_TITLE in prompt
        assert "没有能回答你的人" in prompt

    def test_self_review_prompt_has_contract(self, tmp_path):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_self_review_prompt(
            "2026-09-18", {})
        assert CONTRACT_TITLE in prompt
        assert "没有能回答你的人" in prompt

    def test_evolution_prompt_has_contract(self, tmp_path):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_evolution_prompt("demo", {})
        assert CONTRACT_TITLE in prompt
        assert "没有能回答你的人" in prompt


# ── 契约段关键语义：四组规范性语义逐串在场 ─────────────────────────────


class TestContractKeySemantics:
    """Scenario: 非交互契约段的关键语义（spec requirement 四组逐串在场）。"""

    SEMANTIC_MARKERS = {
        # 1. 无人类可交互 / 无人值守
        "no_human": ("无人值守", "没有能回答你的人"),
        # 2. 直接执行不请求批准
        "no_approval": ("直接执行", "不请求批准", "留痕"),
        # 3. 禁止为等待回复而结束回合
        "no_wait_for_reply": ("等人回复", "end_turn", "失败出口", "partial", "error"),
        # 4. 显式覆盖系统提示词默认框架
        "override_system_prompt": ("interactive agent", "难以撤销的操作先确认",
                                   "plan mode", "brainstorming", "不适用"),
    }

    def test_section_text_contains_all_semantics(self, tmp_path):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        runner = make_runner(proot)
        section = runner._prompt_builder._noninteractive_contract_section()
        for group, markers in self.SEMANTIC_MARKERS.items():
            for marker in markers:
                assert marker in section, f"语义组 {group} 缺串: {marker}"

    def test_built_prompt_contains_all_semantics(self, tmp_path):
        """端到端：任意 agent 类型提示词中的契约段覆盖全部四组语义。"""
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        runner = make_runner(proot)
        for agent_type in ("implementer", "repair", "self-review", "evolution"):
            if agent_type == "repair":
                prompt = runner._prompt_builder._build_repair_prompt("demo", {})
            elif agent_type == "self-review":
                prompt = runner._prompt_builder._build_self_review_prompt("2026-09-18", {})
            elif agent_type == "evolution":
                prompt = runner._prompt_builder._build_evolution_prompt("demo", {})
            else:
                prompt = runner._prompt_builder._build_prompt("demo", agent_type)
            for group, markers in self.SEMANTIC_MARKERS.items():
                for marker in markers:
                    assert marker in prompt, (
                        f"{agent_type} 契约段缺语义串 {marker}（组: {group}）")


# ── 幂等性：契约段可重复注入 ──────────────────────────────────────────


class TestContractSectionIdempotent:
    """Scenario: 契约段幂等——同一 PromptBuilder 连调两次返回相等字符串。"""

    def test_section_idempotent(self, tmp_path):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        runner = make_runner(proot)
        first = runner._prompt_builder._noninteractive_contract_section()
        second = runner._prompt_builder._noninteractive_contract_section()
        assert first == second
        assert first

    def test_section_stable_across_instances(self, tmp_path):
        """不同 PromptBuilder 实例产出相同契约段文本（纯静态、零状态）。"""
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        builder_a = make_runner(proot)._prompt_builder
        builder_b = make_runner(proot)._prompt_builder
        assert builder_a._noninteractive_contract_section() == \
            builder_b._noninteractive_contract_section()


if __name__ == "__main__":
    import unittest
    unittest.main()
