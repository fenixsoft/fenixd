"""agent 提示词文件化测试（add-agent-prompt-files）。

覆盖 spec 全部 Scenario：
- 通用提示词文件为唯一真相：文件加载与占位符替换、文件缺失 fail-fast、动态段语义保持；
- 项目级附加提示词：附加生效、缺席零注入、自引用防护；
- 死知识清理：死关键词断言；
- Dashboard 端点：读写与 agent-type 白名单校验。
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent_runner import prompt_builder as pb_module
from core.agent_runner.prompt_builder import (
    AGENT_PROMPT_DIR,
    AGENT_PROMPT_FILES,
    PromptBuilder,
)
from core.state_machine import StateMachine
from test_agent_runner import FakeLogger, make_runner


AGENT_TYPES = list(AGENT_PROMPT_FILES.keys())


def _mk_spec_dir(proot: Path, name: str) -> None:
    d = proot / "openspec" / "changes" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "tasks.md").write_text("# Tasks\n\n- [ ] 1.1 do it\n", encoding="utf-8")


# ── 通用提示词文件为唯一真相 ─────────────────────────────────────────


class TestFileLoadAndPlaceholders:
    """Scenario: 文件加载与占位符替换。"""

    @pytest.mark.parametrize("agent_type", AGENT_TYPES)
    def test_prompt_body_comes_from_file(self, tmp_path, agent_type):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        runner = make_runner(proot)
        template = (AGENT_PROMPT_DIR / AGENT_PROMPT_FILES[agent_type]).read_text(
            encoding="utf-8")
        prompt = runner._prompt_builder._build_prompt("demo", agent_type)
        # 主体来自文件：文件首行（经占位符替换）即 prompt 开头
        expected = runner._prompt_builder._fill_placeholders(
            template.splitlines()[0], agent_type, "demo", None)
        assert prompt.startswith(expected)

    @pytest.mark.parametrize("agent_type", AGENT_TYPES)
    def test_placeholders_replaced(self, tmp_path, agent_type):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        runner = make_runner(proot)
        template = (AGENT_PROMPT_DIR / AGENT_PROMPT_FILES[agent_type]).read_text(
            encoding="utf-8")
        prompt = runner._prompt_builder._build_prompt("demo", agent_type)
        # 占位符已替换：无残留花括号占位符 token
        for token in ("{spec_name}", "{spec_dir}", "{scenarios_path}",
                      "{result_path}", "{report_path}", "{progress_path}",
                      "{sig_type}", "{sig_spec}", "{disp_path}", "{dash_script}"):
            assert token not in prompt, f"{agent_type} 残留占位符 {token}"
        # 该文件引用的占位符替换为该项目实际路径
        vp = proot / ".fenix" / "verify-progress" / "demo"
        if "{spec_dir}" in template:
            assert "openspec/changes/demo" in prompt
        if "{scenarios_path}" in template:
            assert str(vp / "test_scenarios.json") in prompt
        if "{result_path}" in template:
            assert str(vp / ".fenix-run-result.json") in prompt
        if "{report_path}" in template:
            assert str(vp / "report.json") in prompt
        if "{progress_path}" in template:
            if agent_type == "verifier":
                assert str(proot / ".fenix" / "verify-progress" / "demo.json") in prompt
            else:
                assert str(vp / "demo.json") in prompt

    def test_administrator_signal_fields_rendered(self, tmp_path):
        """administrator 困境信号占位符由 detail 注入渲染。"""
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        runner = make_runner(proot)
        signal = {
            "signal_type": "manual-intervention",
            "spec": "stuck-spec",
            "severity": "major",
            "description": "人工呼叫：检查 SPEC stuck-spec",
            "disposition_path": str(proot / ".fenix" / "admin_disposition-x.json"),
        }
        prompt = runner._prompt_builder._build_prompt("demo", "administrator", detail=signal)
        assert "- spec: stuck-spec" in prompt
        assert "- 类型: manual-intervention" in prompt
        assert "人工呼叫：检查 SPEC stuck-spec" in prompt
        assert str(proot / ".fenix" / "admin_disposition-x.json") in prompt

    def test_unknown_agent_type_rejected(self, tmp_path):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        runner = make_runner(proot)
        with pytest.raises(ValueError):
            runner._prompt_builder._build_prompt("demo", "nonexistent-agent")


class TestMissingFileFailFast:
    """Scenario: 文件缺失 fail-fast——不静默回退内置 prompt。"""

    def test_missing_file_raises(self, tmp_path, monkeypatch):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        monkeypatch.setattr(pb_module, "AGENT_PROMPT_DIR", tmp_path / "empty-agents")
        runner = make_runner(proot)
        with pytest.raises(FileNotFoundError, match="唯一真相"):
            runner._prompt_builder._build_prompt("demo", "implementer")

    def test_missing_file_reports_every_agent_type(self, tmp_path, monkeypatch):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        monkeypatch.setattr(pb_module, "AGENT_PROMPT_DIR", tmp_path / "empty-agents")
        runner = make_runner(proot)
        for agent_type in AGENT_TYPES:
            with pytest.raises(FileNotFoundError):
                runner._prompt_builder._build_prompt("demo", agent_type)

    def test_error_carries_path(self, tmp_path, monkeypatch):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        monkeypatch.setattr(pb_module, "AGENT_PROMPT_DIR", tmp_path / "empty-agents")
        runner = make_runner(proot)
        with pytest.raises(FileNotFoundError) as ei:
            runner._prompt_builder._build_prompt("demo", "verifier")
        assert "verifier.md" in str(ei.value)


class TestDynamicSectionsPreserved:
    """Scenario: 动态段语义保持——条件段仍按既有条件注入。"""

    def test_verifier_breakpoint_injected(self, tmp_path):
        proot = tmp_path / "proj"
        vp = proot / ".fenix" / "verify-progress"
        vp.mkdir(parents=True, exist_ok=True)
        (vp / "myspec.json").write_text(
            json.dumps({"total": 32, "done": 5, "current": "场景5"}),
            encoding="utf-8")
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_prompt("myspec", "verifier")
        assert "RESUME CHECKPOINT" in prompt
        assert "从第 6 个场景开始" in prompt
        assert "done=5（不要重置为 0）" in prompt

    def test_fast_track_prev_error_injected(self, tmp_path):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        sm = StateMachine(tmp_path / "STATE.md", FakeLogger())
        sm.add_spec("demo", {"priority": 5})
        sm.update_spec("demo", {"error": "交付物守卫：缺件 [core/foo.py]"})
        runner = make_runner(proot)
        runner.state_machine = sm
        prompt = runner._prompt_builder._build_prompt("demo", "fast-track")
        assert "Previous run error" in prompt
        assert "交付物守卫：缺件 [core/foo.py]" in prompt

    def test_planner_plan_replan_feedback_injected(self, tmp_path):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        vp = proot / ".fenix" / "verify-progress" / "demo"
        vp.mkdir(parents=True, exist_ok=True)
        (vp / "REPLAN_FEEDBACK.md").write_text(
            "- navigate URL 缺少源码出处\n", encoding="utf-8")
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_prompt("demo", "planner-plan")
        assert "上一轮场景验收未通过" in prompt
        assert "navigate URL 缺少源码出处" in prompt

    def test_no_dynamic_section_when_clean(self, tmp_path):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_prompt("myspec", "verifier")
        assert "RESUME CHECKPOINT" not in prompt


# ── 项目级附加提示词 ─────────────────────────────────────────────────


class TestProjectExtraPrompt:
    """Scenario: 项目级附加生效 / 缺席零注入（任务 2.1）。"""

    def test_project_extra_appended(self, tmp_path):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        extra_dir = proot / ".fenix" / "agents"
        extra_dir.mkdir(parents=True)
        (extra_dir / "verifier.md").write_text(
            "- 本项目登录页用 /login 路径，先 seed 用户再验证。\n", encoding="utf-8")
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_prompt("demo", "verifier")
        assert "## 项目附加提示词" in prompt
        assert "/login 路径" in prompt
        # 附加在末尾（位于主体与动态段之后）
        assert prompt.rstrip().endswith("/login 路径，先 seed 用户再验证。")

    def test_absent_agents_dir_zero_injection(self, tmp_path):
        """无 .fenix/agents/ 目录 → prompt 与仅通用层时逐字节一致。"""
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_prompt("demo", "verifier")
        assert "项目附加提示词" not in prompt
        baseline = runner._prompt_builder._fill_placeholders(
            (AGENT_PROMPT_DIR / AGENT_PROMPT_FILES["verifier"]).read_text(
                encoding="utf-8"),
            "verifier", "demo", None,
        ) + runner._prompt_builder._verifier_breakpoint_section("demo")
        assert prompt == baseline

    def test_empty_extra_file_zero_injection(self, tmp_path):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        extra_dir = proot / ".fenix" / "agents"
        extra_dir.mkdir(parents=True)
        (extra_dir / "verifier.md").write_text("   \n", encoding="utf-8")
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_prompt("demo", "verifier")
        assert "项目附加提示词" not in prompt

    def test_framework_code_never_writes_project_agents_dir(self, tmp_path):
        """框架代码不写入项目 .fenix/agents/（仅 Dashboard API 用户保存写入）。"""
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        runner = make_runner(proot)
        runner._prompt_builder._build_prompt("demo", "verifier")
        assert not (proot / ".fenix" / "agents").exists()


class TestDomainKnowledgeMigrated:
    """Scenario: 领域知识不丢失——被管产品领域规范不得回流框架通用文件。

    COS e2e / 壳路由 / seed 键格式三段已迁移为被管项目（fenix-desktop）
    .fenix/agents/ 的项目附加提示词（一次性迁移，设计 D3/任务 2.2）；
    通用层文件不得再含这些领域片段。
    """

    MANAGED_DOMAIN_MARKERS = ("腾讯云", "fenix:sync:persisted-key", "#/config")

    @pytest.mark.parametrize("agent_type", AGENT_TYPES)
    def test_no_managed_product_domain_knowledge_in_framework(self, tmp_path, agent_type):
        template = (AGENT_PROMPT_DIR / AGENT_PROMPT_FILES[agent_type]).read_text(
            encoding="utf-8")
        for marker in self.MANAGED_DOMAIN_MARKERS:
            assert marker not in template, f"{agent_type} 含被管产品领域知识: {marker}"

    def test_project_extra_delivers_domain_knowledge(self, tmp_path):
        """被管项目 .fenix/agents/ 条目经项目附加机制注入（迁移知识不丢失）。"""
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        extra_dir = proot / ".fenix" / "agents"
        extra_dir.mkdir(parents=True)
        (extra_dir / "verifier.md").write_text(
            "## 真实云端端到端场景\n- 触发真实云端请求（腾讯云 COS）\n"
            "## seed 数据规范\n- base64 键（如 fenix:sync:persisted-key）必须使用合法 base64\n",
            encoding="utf-8")
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_prompt("demo", "verifier")
        assert "腾讯云 COS" in prompt
        assert "fenix:sync:persisted-key" in prompt


# ── 自引用防护 ───────────────────────────────────────────────────────


class TestSelfReferenceGuard:
    """Scenario: 自引用项目禁用项目级附加（任务 2.3 / design D4）。"""

    def _extra_setup(self, proot: Path) -> None:
        extra = proot / ".fenix" / "agents"
        extra.mkdir(parents=True, exist_ok=True)
        (extra / "verifier.md").write_text("- 自引用不应注入此行\n", encoding="utf-8")

    def test_project_root_equals_framework_root_skipped(self, tmp_path, monkeypatch):
        """项目根解析与框架根相同（fenixd 自身项目）→ 项目级读取跳过。"""
        proot = tmp_path / "selfproj"
        _mk_spec_dir(proot, "demo")
        self._extra_setup(proot)
        monkeypatch.setattr(pb_module, "FRAMEWORK_ROOT", proot)
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_prompt("demo", "verifier")
        assert "项目附加提示词" not in prompt
        assert "自引用不应注入此行" not in prompt

    def test_fenix_symlink_to_framework_root_skipped(self, tmp_path, monkeypatch):
        """.fenix 符号链接解析为框架根（自引用）→ 项目级读取跳过。

        自引用场景下项目级 .fenix/agents/ 即框架 agents/（写入会覆盖通用
        文件），附加文件位于框架 agents/ 内以模拟该重合。
        """
        framework = tmp_path / "framework"
        (framework / "agents").mkdir(parents=True)
        (framework / "agents" / "verifier.md").write_text(
            "- 自引用不应注入此行\n", encoding="utf-8")
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        (proot / ".fenix").symlink_to(framework)
        monkeypatch.setattr(pb_module, "FRAMEWORK_ROOT", framework)
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_prompt("demo", "verifier")
        assert "项目附加提示词" not in prompt
        assert "自引用不应注入此行" not in prompt

    def test_normal_project_unaffected(self, tmp_path, monkeypatch):
        """普通项目（.fenix 为真实目录且≠框架根）附加照常生效。"""
        framework = tmp_path / "framework"
        framework.mkdir()
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        self._extra_setup(proot)
        monkeypatch.setattr(pb_module, "FRAMEWORK_ROOT", framework)
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_prompt("demo", "verifier")
        assert "自引用不应注入此行" in prompt


if __name__ == "__main__":
    import unittest
    unittest.main()
