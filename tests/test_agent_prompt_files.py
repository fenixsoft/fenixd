"""agent 提示词文件化测试（add-agent-prompt-files）。

覆盖 spec 全部 Scenario：
- 通用提示词文件为唯一真相：文件加载与占位符替换、文件缺失 fail-fast、动态段语义保持；
- 项目级附加提示词：附加生效、缺席零注入、通用层重合布局防护；
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
    d = proot / "spec" / "changes" / name
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
            assert "spec/changes/demo" in prompt
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


class TestDeadKeywords:
    """Scenario: 死关键词断言——通用提示词不含 AMIS/dark-/面板清单死知识。"""

    DEAD_KEYWORDS = ("dark-SelectControl", "amis-dialog-widget",
                     "dark-Card", "sh600036")

    @pytest.mark.parametrize("agent_type", AGENT_TYPES)
    def test_no_dead_keywords_in_framework_prompts(self, agent_type):
        template = (AGENT_PROMPT_DIR / AGENT_PROMPT_FILES[agent_type]).read_text(
            encoding="utf-8")
        for kw in self.DEAD_KEYWORDS:
            assert kw not in template, f"{agent_type} 含死关键词: {kw}"

    def test_dead_keyword_example_replaced_by_testid_style(self):
        """选择器示例段（原 .dark-Card/dark-Card--link 大全）改为 data-testid 风格通用示例。"""
        planner_plan = (AGENT_PROMPT_DIR / AGENT_PROMPT_FILES["planner-plan"]).read_text(
            encoding="utf-8")
        assert "data-testid" in planner_plan
        verifier = (AGENT_PROMPT_DIR / AGENT_PROMPT_FILES["verifier"]).read_text(
            encoding="utf-8")
        # Step 3 面板清单改通用表述，但保留「交互必须有可见结果否则 BLOCKING BUG」
        assert "BLOCKING BUG" in verifier
        assert "点击遍历被测应用的每个主要界面" in verifier


# ── 项目通道与通用层隔离 ─────────────────────────────────────────────


class TestProjectAgentsDirResolution:
    """Scenario: fenixd 自身按普通项目处理；仅废弃软链布局（.fenix/agents
    解析为通用层目录）读取零注入、写入拒绝。

    2026-09-05 用户决策：不对 fenixd 特殊处理——其项目级提示词即
    <root>/.fenix/agents/（真实目录，与通用层 agents/ 互不相干），照常
    可编辑、派发时注入。原「自引用项目禁用编辑」（add-agent-prompt-files
    D4）语义退役，仅保留路径解析级防护（project_agents_dir）。
    """

    def test_self_project_extra_injected(self, tmp_path, monkeypatch):
        """项目根即框架根（fenixd 自身）→ 项目级附加照常注入（代码无任何分支）。"""
        proot = tmp_path / "selfproj"
        _mk_spec_dir(proot, "demo")
        extra = proot / ".fenix" / "agents"
        extra.mkdir(parents=True)
        (extra / "verifier.md").write_text("- 自身项目附加生效\n", encoding="utf-8")
        monkeypatch.setattr(pb_module, "FRAMEWORK_ROOT", proot)  # 语义标注：即框架根
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_prompt("demo", "verifier")
        assert "## 项目附加提示词" in prompt
        assert "自身项目附加生效" in prompt

    def test_helper_normal_project_returns_path(self, tmp_path):
        proot = tmp_path / "proj"
        agents = proot / ".fenix" / "agents"
        agents.mkdir(parents=True)
        assert pb_module.project_agents_dir(proot) == agents

    def test_symlink_into_universal_layer_zero_injection(self, tmp_path, monkeypatch):
        """.fenix 软链到框架根（废弃自引用布局）→ 项目通道解析为通用层，
        读取零注入（通用主体只出现一份，不把通用文件当附加叠加）。"""
        framework = tmp_path / "framework"
        (framework / "agents").mkdir(parents=True)
        (framework / "agents" / "verifier.md").write_text(
            "通用主体唯一行\n", encoding="utf-8")
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        (proot / ".fenix").symlink_to(framework)
        monkeypatch.setattr(pb_module, "AGENT_PROMPT_DIR", framework / "agents")
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_prompt("demo", "verifier")
        assert prompt.count("通用主体唯一行") == 1
        assert "项目附加提示词" not in prompt

    def test_helper_universal_collision_returns_none(self, tmp_path, monkeypatch):
        framework = tmp_path / "framework"
        (framework / "agents").mkdir(parents=True)
        proot = tmp_path / "proj"
        proot.mkdir()
        (proot / ".fenix").symlink_to(framework)
        monkeypatch.setattr(pb_module, "AGENT_PROMPT_DIR", framework / "agents")
        assert pb_module.project_agents_dir(proot) is None


# ── Dashboard「提示词」端点 ──────────────────────────────────────────


@pytest.fixture()
def prompts_server(tmp_path):
    """DashboardHTTPServer 测试实例（复用 test_dashboard_api 的夹具）。"""
    from test_dashboard_api import _TestServer, make_project
    from core.dashboard.registry import Registry
    proot = make_project(tmp_path)
    cfg = tmp_path / "dashboard.yaml"
    reg = Registry(config_path=cfg)
    reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
              "scan_dirs": [str(tmp_path / "scan-empty")]})
    srv = _TestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
    yield proot, srv
    srv.stop()


class TestPromptsAPI:
    """Scenario: 端点读写与白名单校验（任务 3.1）。"""

    def test_get_user_level_lists_six_agents(self, prompts_server):
        proot, srv = prompts_server
        status, data = srv.get("/api/prompts")
        assert status == 200
        assert [a["type"] for a in data["agents"]] == list(AGENT_PROMPT_FILES.keys())
        for a in data["agents"]:
            assert a["content"], f"{a['type']} 通用内容非空"
        assert "project" not in data

    def test_get_project_level_returns_extras(self, prompts_server):
        proot, srv = prompts_server
        status, data = srv.get("/api/prompts?project=proj-a")
        assert status == 200
        assert data["project"]["name"] == "proj-a"
        assert "self_referencing" not in data["project"]
        assert set(data["project"]["extras"].keys()) == set(AGENT_PROMPT_FILES.keys())
        assert data["project"]["extras"]["verifier"] == ""

    def test_get_project_extras_show_saved_content(self, prompts_server):
        proot, srv = prompts_server
        extra_dir = proot / ".fenix" / "agents"
        extra_dir.mkdir(parents=True)
        (extra_dir / "verifier.md").write_text("- 项目附加规则\n", encoding="utf-8")
        status, data = srv.get("/api/prompts?project=proj-a")
        assert status == 200
        assert "项目附加规则" in data["project"]["extras"]["verifier"]

    def test_post_saves_project_extra(self, prompts_server):
        proot, srv = prompts_server
        status, data = srv.post_json(
            "/api/prompts?project=proj-a",
            {"agent_type": "verifier", "content": "- 登录页路径 /login\n"})
        assert status == 200 and data["ok"] is True
        saved = proot / ".fenix" / "agents" / "verifier.md"
        assert saved.is_file()
        assert "/login" in saved.read_text(encoding="utf-8")

    def test_post_save_then_next_dispatch_appends(self, prompts_server):
        """Scenario「项目级编辑保存生效」完整链路：保存落盘 → 下次派发 prompt 附加该内容。"""
        proot, srv = prompts_server
        _mk_spec_dir(proot, "demo")
        srv.post_json(
            "/api/prompts?project=proj-a",
            {"agent_type": "verifier", "content": "- 登录页路径 /login\n"})
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_prompt("demo", "verifier")
        assert "## 项目附加提示词" in prompt
        assert "/login" in prompt

    def test_post_rejects_non_whitelisted_agent_type(self, prompts_server):
        proot, srv = prompts_server
        for bad in ("../evil", "unknown-type", None, ["verifier"]):
            status, data = srv.post_json(
                "/api/prompts?project=proj-a", {"agent_type": bad, "content": "x"})
            assert status == 400, f"agent_type={bad!r} 应被白名单拒绝"
        assert not (proot / ".fenix" / "agents").exists()

    def test_post_requires_project(self, prompts_server):
        _, srv = prompts_server
        status, data = srv.post_json(
            "/api/prompts", {"agent_type": "verifier", "content": "x"})
        assert status == 400

    def test_post_unknown_project_404(self, prompts_server):
        _, srv = prompts_server
        status, data = srv.post_json(
            "/api/prompts?project=nope", {"agent_type": "verifier", "content": "x"})
        assert status == 404

    def _register_universal_layer_project(self, tmp_path, srv, name: str):
        """注册一个 .fenix → 框架根软链项目（废弃自引用布局）并击穿 projects TTL 缓存。

        迁移后 add_project 校验 .fenix/STATE.md——经符号链接解析到真实框架根，
        存在性依赖开发环境（干净检出会挂）。夹具的意图是通用层重合布局防护
        而非注册校验，故直写 registry 配置绕过校验；显式注册本就不做项目标记检查。
        """
        selfroot = tmp_path / name
        selfroot.mkdir()
        (selfroot / "STATE.md").write_text("# Fenix Project State\n", encoding="utf-8")
        (selfroot / ".fenix").symlink_to(Path(__file__).resolve().parents[1])
        from core.dashboard.registry import Registry
        reg = Registry(config_path=tmp_path / "dashboard.yaml")
        reg.save({
            "port": 8787,
            "projects": [{"name": name, "path": str(selfroot)}],
            "scan_dirs": [],
            "ignored": [],
        })
        srv.httpd._projects_cache = []
        srv.httpd._cache_ts = 0.0
        return selfroot

    def test_post_rejects_universal_layer_collision(self, prompts_server, tmp_path):
        """项目 .fenix/agents 解析为通用层 agents/（废弃软链布局）→ POST 拒绝，通用文件不被改写。"""
        proot, srv = prompts_server
        selfroot = self._register_universal_layer_project(tmp_path, srv, "self-proj")
        # 通用层基准内容（确保未被写入破坏）
        generic = AGENT_PROMPT_DIR / AGENT_PROMPT_FILES["verifier"]
        before = generic.read_text(encoding="utf-8")

        status, data = srv.post_json(
            "/api/prompts?project=self-proj",
            {"agent_type": "verifier", "content": "- 覆盖通用层\n"})
        assert status == 403
        assert generic.read_text(encoding="utf-8") == before

    def test_get_universal_layer_collision_blank_extras(self, prompts_server, tmp_path):
        """废弃软链布局 GET：extras 为空串（不把通用层内容当项目附加回显）。"""
        _, srv = prompts_server
        self._register_universal_layer_project(tmp_path, srv, "self-proj-2")
        status, data = srv.get("/api/prompts?project=self-proj-2")
        assert status == 200
        assert "self_referencing" not in data["project"]
        assert data["project"]["extras"]["verifier"] == ""


if __name__ == "__main__":
    import unittest
    unittest.main()
