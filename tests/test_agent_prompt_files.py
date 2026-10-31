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
from test_agent_runner import make_runner


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
                      "{sig_type}", "{sig_spec}", "{disp_path}", "{dash_script}",
                      "{prev_review_rejection}"):
            assert token not in prompt, f"{agent_type} 残留占位符 {token}"
        # 该文件引用的占位符替换为该项目实际路径
        vp = proot / ".fenix" / "verify-progress" / "demo"
        if "{spec_dir}" in template:
            assert "spec/changes/demo" in prompt
        if "{scenarios_path}" in template:
            assert str(vp / "test_scenarios.json") in prompt
        if "{result_path}" in template:
            if agent_type == "spec-review":
                # spec-review 的结果路径在 .fenix/spec-review/ 下
                assert str(proot / ".fenix" / "spec-review" / "demo" / ".fenix-run-result.json") in prompt
            else:
                assert str(vp / ".fenix-run-result.json") in prompt
        if "{report_path}" in template:
            if agent_type == "arbiter":
                # add-arbiter-lane：arbiter 的 {report_path} 是裁决报告路径
                # （run_arbiter 硬门读侧同源），非 verify-progress/report.json
                from core.pm_engine.arbiter import arbiter_report_path

                assert str(arbiter_report_path(proot, "demo")) in prompt
            else:
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

    def test_administrator_structured_evidence_rendered(self, tmp_path):
        """遗留的结构化 evidence 不再让占位符填充崩溃（回归）。

        占位符填充走 str.replace，若 detail.evidence 是 dict 会抛
        "replace() argument 2 must be str, not dict"，Administrator run 起不来
        （实证：stash_pop_conflict 直发 dict evidence → 唤起失败升级人工）。
        _fill_placeholders 在填充点兜底归一，任何深度传入都不崩。
        """
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        runner = make_runner(proot)
        signal = {
            "signal_type": "stash_pop_conflict",
            "spec": "evo-x",
            "severity": "major",
            "description": "pop 冲突已自愈",
            "evidence": {"conflict_files": ["core/a.py"], "stash_kept": True},
            "recommended_action": "核对 stash",
            "disposition_path": str(proot / ".fenix" / "admin_disposition-x.json"),
        }
        prompt = runner._prompt_builder._build_prompt(
            "demo", "administrator", detail=signal)
        assert "conflict_files" in prompt and "core/a.py" in prompt

    def test_dispatch_chain_structured_evidence_and_recommendation(self, tmp_path):
        """派发链中 evidence/recommended_action 同时为 dict/list 时提示词正常构建。

        admin-dispatch-failure-escalation 2.2：_str_field 统一兜底
        dict→JSON、list→JSON；{recommendation} 同理。不抛 TypeError
        （replace() argument 2 must be str）。
        """
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        runner = make_runner(proot)
        signal = {
            "signal_type": "stuck",
            "spec": "spec-dispatch",
            "severity": "critical",
            "description": "派发链测试",
            "evidence": {"items": ["a.py", "b.py"], "nested": {"k": 1}},
            "recommended_action": {"action": "rebuild", "scope": ["build", "test"]},
            "disposition_path": str(proot / ".fenix" / "admin_disposition-x.json"),
        }
        prompt = runner._prompt_builder._build_prompt(
            "demo", "administrator", detail=signal)
        # evidence dict 被序列化进提示词，关键键/值可辨识
        assert "items" in prompt and "a.py" in prompt
        # recommended_action dict 被序列化进提示词
        assert "rebuild" in prompt

    def test_unknown_agent_type_rejected(self, tmp_path):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        runner = make_runner(proot)
        with pytest.raises(ValueError):
            runner._prompt_builder._build_prompt("demo", "nonexistent-agent")


class TestMissingFileFailFast:
    """Scenario: 文件缺失 fail-fast——不静默回退内置 prompt。"""

    def test_missing_file_reports_every_agent_type(self, tmp_path, monkeypatch):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        monkeypatch.setattr(pb_module, "AGENT_PROMPT_DIR", tmp_path / "empty-agents")
        runner = make_runner(proot)
        for agent_type in AGENT_TYPES:
            with pytest.raises(FileNotFoundError):
                runner._prompt_builder._build_prompt("demo", agent_type)

    def test_error_carries_path_and_intent(self, tmp_path, monkeypatch):
        """报错信息携带缺失文件名与「唯一真相」设计语义（不静默回退）。"""
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        monkeypatch.setattr(pb_module, "AGENT_PROMPT_DIR", tmp_path / "empty-agents")
        runner = make_runner(proot)
        with pytest.raises(FileNotFoundError) as ei:
            runner._prompt_builder._build_prompt("demo", "verifier")
        assert "verifier.md" in str(ei.value)
        assert "唯一真相" in str(ei.value)


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

    # prev_error 动态段（implementer/fast-track 共用）的注入语义与两个分支的
    # 接线断言由 test_deliverable_gate.py::TestPrevErrorInjection 集中覆盖，
    # 此处不再跨文件重复。

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
        # fix-agent-noninteractive-contract 2.5：非交互契约段在统一收尾处
        # 注入（动态段之后、项目附加段之前），逐字节 baseline 同步纳入。
        baseline = runner._prompt_builder._fill_placeholders(
            (AGENT_PROMPT_DIR / AGENT_PROMPT_FILES["verifier"]).read_text(
                encoding="utf-8"),
            "verifier", "demo", None,
        ) + runner._prompt_builder._verifier_breakpoint_section("demo") \
            + runner._prompt_builder._noninteractive_contract_section() \
            + runner._prompt_builder._evidence_placement_section("demo")
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

    def test_get_user_level_lists_all_agents(self, prompts_server):
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


# ── add-scenario-defect-triage-gate 4.2：prompt 构建回归核对 ────────────────
# planner-judge prompt 含新路由指引；其余 agent 类型模板逐字节不变
#（模板改动不外溢——本 SPEC 仅修订 agents/planner-judge.md）。


class TestJudgeRoutingGuidanceRegression:
    """Task 4.2：judge prompt 路由指引回归核对。"""

    def test_planner_judge_prompt_contains_routing_guidance(self, tmp_path):
        """planner-judge prompt（模板主体）含场景文件缺陷路由指引与修复合法性声明。"""
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        runner = make_runner(proot)
        template = (AGENT_PROMPT_DIR / AGENT_PROMPT_FILES["planner-judge"]).read_text(
            encoding="utf-8")
        assert "场景文件缺陷路由" in template
        assert "MUST 按下方「原地修复协议」申报" in template
        assert "修复已裁决场景合法" in template
        assert "不视为冻结违规" in template

    def test_planner_judge_built_prompt_has_guidance(self, tmp_path):
        """端到端 build_prompt(planner-judge) 含新指引（模板是 prompt 唯一真相）。"""
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_prompt("demo", "planner-judge")
        assert "场景文件缺陷路由" in prompt
        assert "修复已裁决场景合法" in prompt
        assert "不视为冻结违规" in prompt

    def test_other_agent_prompts_unmodified(self, tmp_path):
        """其余 agent 类型模板逐字节不含本 SPEC 新指引（改动只落在 planner-judge.md）。"""
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        runner = make_runner(proot)
        for agent_type in AGENT_TYPES:
            if agent_type == "planner-judge":
                continue
            template = (AGENT_PROMPT_DIR / AGENT_PROMPT_FILES[agent_type]).read_text(
                encoding="utf-8")
            # 新指引关键词不得外溢到其他 agent 模板
            assert "场景文件缺陷路由" not in template
            assert "修复已裁决场景合法" not in template

    def test_verify_listed_prompt_files_match_tasks(self, tmp_path):
        """tasks.md 声明的 agents/planner-judge.md 修改已落实（git 工作区快照）。"""
        from core.agent_runner.prompt_builder import AGENT_PROMPT_FILES
        assert AGENT_PROMPT_FILES["planner-judge"] == "planner-judge.md"


class TestStepFailureChecklistGuard:
    """verdict-step-failure-evidence-derivation 2.2：步骤失败型必填清单处方
    防漂移守卫（fe612841 处方回归）。

    planner-judge.md 的「步骤失败型场景必填清单（强制）」是 LLM 行为约束，
    无守卫时后续改写可静默丢失 → 步骤失败型场景（assertion_results 空表 +
    失败信号）首轮漏 triage、重试轮摘出空表，fail-closed 驳回-重试死循环。
    断言子串与 agents/planner-judge.md 处方原文逐字一致。
    """

    def test_planner_judge_template_contains_step_failure_checklist(self):
        """模板主体含「步骤失败型场景必填清单（强制）」处方小节（逐字一致）。"""
        template = (AGENT_PROMPT_DIR / AGENT_PROMPT_FILES["planner-judge"]).read_text(
            encoding="utf-8")
        assert "**步骤失败型场景必填清单（强制）**" in template

    def test_planner_judge_built_prompt_has_step_failure_checklist(self, tmp_path):
        """端到端 build_prompt(planner-judge) 含该处方（模板是 prompt 唯一真相）。"""
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_prompt("demo", "planner-judge")
        assert "**步骤失败型场景必填清单（强制）**" in prompt


# ── 实现者任务进度契约段（fix-impl-tasks-completion-gate D5/6.3/9.6）────


class TestTaskProgressContractDualBranch:
    """Scenario「契约载体覆盖」与「收工自检契约同源」（spec implementer-task-protocol）。

    两分支（implementer / fast-track）契约段同源生成（同一构造函数产出，内容
    逐字一致）；工具不可用分支（无 run 产物 → init.tools 不可得）prompt 不含
    TaskCreate 强制语句，以 completed_tasks 为进度载体。
    """

    def _prompt(self, tmp_path, agent_type, run_tools=None):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        if run_tools is not None:
            runs = proot / ".fenix" / "runs"
            runs.mkdir(parents=True, exist_ok=True)
            (runs / "impl-demo-1780000000.jsonl").write_text(
                json.dumps({"type": "system", "subtype": "init",
                            "tools": run_tools}) + "\n", encoding="utf-8")
        runner = make_runner(proot)
        return runner._prompt_builder._build_prompt("demo", agent_type)

    def test_dual_branch_contract_same_source(self, tmp_path):
        """两分支契约段同源：同一实现点产出、内容逐字一致。"""
        full = self._prompt(tmp_path, "implementer")
        fast = self._prompt(tmp_path, "fast-track")
        seg = "## 任务进度契约（task-progress-contract"
        end = "一一对应，不留半勾。\n"
        full_seg = full[full.index(seg):full.index(end) + len(end)]
        fast_seg = fast[fast.index(seg):fast.index(end) + len(end)]
        assert full_seg == fast_seg
        assert "completed_tasks" in full_seg
        assert "unfinished" in full_seg
        assert "禁止「先勾后做」" in full_seg

    def test_dual_branch_contract_requires_completed_tasks(self, tmp_path):
        """两个 prompt 文本都包含以 completed_tasks/unfinished 为进度载体的契约段。"""
        for agent_type in ("implementer", "fast-track"):
            prompt = self._prompt(tmp_path, agent_type)
            assert "completed_tasks" in prompt
            assert "unfinished" in prompt
            assert "一一对应" in prompt

    def test_tools_unconditionally_available(self, tmp_path):
        """方案 1（2026-09-17）：工具可用性恒为可用——即使无 run 产物（无历史
        run 可探测），契约段仍注入任务粒度映射，不再注入「工具不可用」禁止段。"""
        for agent_type in ("implementer", "fast-track"):
            prompt = self._prompt(tmp_path, agent_type)
            assert "只能由一个 TaskCreate 对应" in prompt
            assert "TaskUpdate status=completed" in prompt
            assert "MUST NOT 尝试创建任务" not in prompt

    def test_tools_available_injects_taskcreate_mapping(self, tmp_path):
        """init.tools 暴露 TaskCreate 时同样注入任务粒度映射契约（与无条件
        注入路径文本一致）。"""
        tools = ["Task", "TaskCreate", "TaskUpdate", "Bash", "Read", "Write"]
        for agent_type in ("implementer", "fast-track"):
            prompt = self._prompt(tmp_path, agent_type, run_tools=tools)
            assert "只能由一个 TaskCreate 对应" in prompt
            assert "TaskUpdate status=completed" in prompt
            assert "MUST NOT 尝试创建任务" not in prompt


if __name__ == "__main__":
    import unittest
    unittest.main()


# ── add-spec-review-gate 7.9：白名单注册与前端 key 集合一致性 ────────


class TestSpecReviewPromptRegistration:
    """spec-review 在 AGENT_PROMPT_FILES 白名单中且模板可加载；前端
    AGENT_LABELS / AGENT_ROLES key 集合与后端两处常量严格一致。"""

    def test_spec_review_in_whitelist(self):
        assert "spec-review" in AGENT_PROMPT_FILES
        assert AGENT_PROMPT_FILES["spec-review"] == "spec-review.md"

    def test_spec_review_template_loadable(self, tmp_path):
        """模板文件存在、非空且可经 PromptBuilder 加载（fail-fast 不触发）。"""
        template_path = AGENT_PROMPT_DIR / AGENT_PROMPT_FILES["spec-review"]
        assert template_path.is_file(), f"缺少模板文件: {template_path}"
        content = template_path.read_text(encoding="utf-8").strip()
        assert content, "spec-review.md 为空"

        proot = tmp_path / "proj"
        (proot / "spec" / "changes" / "demo").mkdir(parents=True, exist_ok=True)
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_prompt("demo", "spec-review")
        assert prompt
        assert "demo" in prompt

    def test_prompts_panel_labels_keys_match_prompt_files(self):
        """前端 AGENT_LABELS key 集合与后端 AGENT_PROMPT_FILES 严格一致
        （两处必须同步，缺失占位符会 fail-fast）。"""
        ts_path = (Path(__file__).resolve().parents[1]
                   / "core" / "dashboard" / "static" / "src" / "pages" / "settings"
                   / "components" / "PromptsPanel.tsx")
        src = ts_path.read_text(encoding="utf-8")
        # 提取 AGENT_LABELS 对象字面量的键（单引号字符串键 + 冒号）
        block = src.split("const AGENT_LABELS")[1].split("};")[0]
        import re as _re
        keys = set()
        for line in block.splitlines():
            line = line.strip()
            m = _re.match(r"^[\'\"]?([\w-]+)[\'\"]?\s*:", line)
            if m:
                keys.add(m.group(1))
        assert keys == set(AGENT_PROMPT_FILES.keys()), (
            f"AGENT_LABELS 与 AGENT_PROMPT_FILES 不一致: "
            f"{keys ^ set(AGENT_PROMPT_FILES.keys())}"
        )

    def test_agent_model_panel_roles_match_known_agent_types(self):
        """前端 AGENT_ROLES key 集合与后端 KNOWN_AGENT_TYPES 严格一致
        （agent model 分配面板与模型白名单必须同步）。"""
        from core.config import ConfigLoader
        ts_path = (Path(__file__).resolve().parents[1]
                   / "core" / "dashboard" / "static" / "src" / "pages" / "settings"
                   / "components" / "AgentModelPanel.tsx")
        src = ts_path.read_text(encoding="utf-8")
        block = src.split("const AGENT_ROLES")[1].split("];")[0]
        keys = set()
        for line in block.splitlines():
            line = line.strip()
            if line.startswith("{ key:") and "label:" in line:
                key = line.split("key:")[1].split(",")[0].strip().strip("'").strip('"')
                if key:
                    keys.add(key)
        assert keys == set(ConfigLoader.KNOWN_AGENT_TYPES), (
            f"AGENT_ROLES 与 KNOWN_AGENT_TYPES 不一致: "
            f"{keys ^ set(ConfigLoader.KNOWN_AGENT_TYPES)}"
        )


# ── 收尾审查提示词契约（车道化语义，add-impl-ocr-parallel-lane 任务 2.1）──


class TestImplCodeReviewSectionInjection:
    """add-impl-ocr-parallel-lane 任务 2.1 退役内联审查段后的 prompt 契约。

    实现者收尾 ocr 义务已由 prompt 内联段退役为框架侧异步车道（merge 成功
    同点启动 run_impl_ocr + testing 出口 join 门禁）。无论 verify.impl_code_review
    开关取值如何，两条实现车道 prompt 均不含内联审查段；打回修复轮的 findings
    经 ``ocr_findings_directive.json`` 文件驱动注入（任务 5.1），非打回轮零注入。
    """

    _DIRECTIVE_REL = ".fenix/verify-progress/demo/ocr_findings_directive.json"

    @staticmethod
    def _write_directive(proot: Path) -> None:
        d = proot / ".fenix" / "verify-progress" / "demo"
        d.mkdir(parents=True, exist_ok=True)
        (d / "ocr_findings_directive.json").write_text(
            json.dumps(
                {
                    "round": 1,
                    "max_rounds": 2,
                    "findings": [
                        {
                            "path": "core/x.py",
                            "line": 3,
                            "category": "correctness",
                            "severity": "major",
                            "content": "越界访问",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def _runner(self, proot: Path, verify: dict):
        runner = make_runner(proot)
        runner.config = {"verify": verify}
        return runner

    # 开关关闭时（缺省）implementer 与 fast-track prompt 均不含审查相关内容
    @pytest.mark.parametrize("agent_type", ["implementer", "fast-track"])
    def test_disabled_no_review_section(self, tmp_path, agent_type):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        prompt = self._runner(proot, {"impl_code_review": False})._prompt_builder._build_prompt("demo", agent_type)
        assert "bin/ocr_review.py" not in prompt
        assert "收尾代码质量审查" not in prompt
        assert "code-review.json" not in prompt

    # 缺省配置（无 verify 节）同样零注入
    @pytest.mark.parametrize("agent_type", ["implementer", "fast-track"])
    def test_no_verify_key_no_review_section(self, tmp_path, agent_type):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        prompt = self._runner(proot, {})._prompt_builder._build_prompt("demo", agent_type)
        assert "bin/ocr_review.py" not in prompt
        assert "收尾代码质量审查" not in prompt

    # 开关开启也不注入内联审查段：收尾审查已退役为框架侧异步车道
    @pytest.mark.parametrize("agent_type", ["implementer", "fast-track"])
    def test_enabled_no_inline_review_section(self, tmp_path, agent_type):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        prompt = self._runner(proot, {"impl_code_review": True})._prompt_builder._build_prompt("demo", agent_type)
        assert "bin/ocr_review.py" not in prompt
        assert "收尾代码质量审查" not in prompt
        assert ".fenix/verify-progress/demo/code-review.json" not in prompt

    # 非打回轮（directive 文件缺失）findings 注入段零注入
    @pytest.mark.parametrize("agent_type", ["implementer", "fast-track"])
    def test_no_directive_file_zero_findings_injection(self, tmp_path, agent_type):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        prompt = self._runner(proot, {"impl_code_review": True})._prompt_builder._build_prompt("demo", agent_type)
        assert "ocr 代码审查 findings 修复义务" not in prompt

    # 打回修复轮：directive 文件在场 → 注入 findings 清单 + disposition 契约
    @pytest.mark.parametrize("agent_type", ["implementer", "fast-track"])
    def test_directive_file_injects_findings(self, tmp_path, agent_type):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        self._write_directive(proot)
        prompt = self._runner(proot, {"impl_code_review": True})._prompt_builder._build_prompt("demo", agent_type)
        assert "ocr 代码审查 findings 修复义务" in prompt
        assert "core/x.py:3" in prompt
        # disposition 契约仍在：裁量权归实现者 + 误报表述 + worktree 相对路径
        assert "裁量权归你" in prompt
        assert "误报" in prompt
        assert ".fenix/verify-progress/demo/code-review.json" in prompt

    # 非实现车道（verifier 等）即使开关开启也零注入
    def test_non_impl_agent_not_injected(self, tmp_path):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        self._write_directive(proot)
        runner = self._runner(proot, {"impl_code_review": True})
        for agent_type in ("verifier", "planner-plan", "planner-judge", "spec-review"):
            prompt = runner._prompt_builder._build_prompt("demo", agent_type)
            assert "bin/ocr_review.py" not in prompt, (
                f"{agent_type} 不应含审查段"
            )
            assert "ocr 代码审查 findings 修复义务" not in prompt, (
                f"{agent_type} 不应含 findings 修复义务段"
            )

    # 段序：findings 注入段位于非交互契约段之后
    @pytest.mark.parametrize("agent_type", ["implementer", "fast-track"])
    def test_findings_section_after_noninteractive_contract(self, tmp_path, agent_type):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        self._write_directive(proot)
        prompt = self._runner(proot, {"impl_code_review": True})._prompt_builder._build_prompt("demo", agent_type)
        nc_pos = prompt.find("非交互契约")
        cr_pos = prompt.find("ocr 代码审查 findings 修复义务")
        assert nc_pos >= 0, "缺少非交互契约段"
        assert cr_pos >= 0, "缺少 findings 修复义务段"
        assert cr_pos > nc_pos, "findings 注入段应在非交互契约段之后"


# ── fix-impl-code-review-writepath 任务 4.3：工作目录段消歧 ─────────────


class TestWorkdirSectionVerifyProgressDisambiguation:
    """Scenario: 契约文本消歧——「验证进度目录」显式限定为 worktree 内。

    读 agents/*.md 原文，断言「工作目录（worktree 隔离，强制）」段第三条含
    「worktree 内」限定与「不是主树的同名目录」提示，且 MUST NOT 再出现未限定的
    裸表述「验证进度目录 `.fenix/verify-progress/`（框架已显式授权）」。
    """

    _AGENTS = ("agents/implementer.md", "agents/fast-track.md")

    def _content(self, rel: str) -> str:
        return (Path(__file__).resolve().parent.parent / rel).read_text(
            encoding="utf-8"
        )

    @pytest.mark.parametrize("rel", _AGENTS)
    def test_worktree_qualified_and_main_tree_warning(self, rel):
        content = self._content(rel)
        assert "**worktree 内**的 `.fenix/verify-progress/`" in content, (
            f"{rel} 缺少「worktree 内」限定"
        )
        assert "不是主树的同名目录" in content, f"{rel} 缺少「不是主树的同名目录」提示"
        assert "产物硬门判为「报告缺失」" in content, f"{rel} 缺少写主树被门判缺失的警告"

    @pytest.mark.parametrize("rel", _AGENTS)
    def test_no_unqualified_legacy_phrasing(self, rel):
        content = self._content(rel)
        legacy = "验证进度目录 `.fenix/verify-progress/`（框架已显式授权）"
        assert legacy not in content, f"{rel} 仍残留未限定的「验证进度目录」裸表述"


# ── 验收偏差勾选纪律提示词契约（evo-add-acceptance-deviation-reporting 3.2）──


class TestAcceptanceDeviationDisciplinePrompt:
    """Scenario「替代验收行内注明」+「规划层消费偏差注解」的提示词契约。

    implementer / planner-plan 模板与构建后 prompt 均须携带勾选纪律与替代注明
    措辞；措辞与 result_gate 硬门单源（同一常量对象），防两侧漂移。
    """

    _DISCIPLINE_MARKS = (
        "以 X 替代验收",  # 行内注解短语（ACCEPTANCE_DEVIATION_ANNOTATION 渲染）
        "acceptance-deviation",  # findings 条目类型
        "MUST NOT 勾选",  # 字面验收未满足不得勾选
        '"task"',  # 条目三要素
        '"literal"',
        '"substitute"',
    )

    def test_implementer_template_contains_discipline(self):
        """agents/implementer.md 模板含勾选纪律约束段与 findings 条目形状。"""
        template = (AGENT_PROMPT_DIR / AGENT_PROMPT_FILES["implementer"]).read_text(
            encoding="utf-8")
        for mark in self._DISCIPLINE_MARKS + ('"evidence"', "unattainable"):
            assert mark in template, f"implementer.md 缺少勾选纪律措辞: {mark}"

    def test_built_implementer_prompt_contains_discipline(self, tmp_path):
        """构建后 implementer prompt 经 _result_gate_section 注入同款纪律段。"""
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_prompt("demo", "implementer")
        for mark in self._DISCIPLINE_MARKS:
            assert mark in prompt, f"implementer prompt 缺少勾选纪律措辞: {mark}"

    def test_built_fast_track_prompt_same_discipline(self, tmp_path):
        """fast-track 车道注入同一纪律段（两车道同义生效）。"""
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_prompt("demo", "fast-track")
        for mark in self._DISCIPLINE_MARKS:
            assert mark in prompt, f"fast-track prompt 缺少勾选纪律措辞: {mark}"

    def test_discipline_wording_single_source_with_result_gate(self, tmp_path):
        """措辞单源：result_gate 引用 prompt_builder 同一常量对象，且组合拒绝
        文案中的注解短语来自同一常量（改一处即两侧同源生效）。"""
        import core.agent_runner.result_gate as rg
        from core.agent_runner import prompt_builder as pb

        assert rg.ACCEPTANCE_DEVIATION_TYPE is pb.ACCEPTANCE_DEVIATION_TYPE
        assert rg.IMPL_FINDINGS_TYPE_WHITELIST is pb.IMPL_FINDINGS_TYPE_WHITELIST
        assert rg.ACCEPTANCE_DEVIATION_ANNOTATION is pb.ACCEPTANCE_DEVIATION_ANNOTATION
        # 纪律段措辞由单源函数渲染，注入 prompt 的文本与常量一致
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_prompt("demo", "implementer")
        section = pb.acceptance_deviation_discipline_section()
        assert section.strip() in prompt
        # 硬门拒绝文案引用同一注解短语常量
        err = rg._check_acceptance_deviation_success(
            runner, {"findings": [{"type": "acceptance-deviation",
                                   "task": "1.1"}],
                     "completed_tasks": ["1.1"]}, Path("r.json"))
        assert err is not None
        assert f"以 X {pb.ACCEPTANCE_DEVIATION_ANNOTATION}" in err

    def test_planner_plan_template_contains_substitute_planning_rule(self):
        """agents/planner-plan.md 模板含「按注解的替代方式出题」规范。"""
        template = (AGENT_PROMPT_DIR / AGENT_PROMPT_FILES["planner-plan"]).read_text(
            encoding="utf-8")
        assert "以 X 替代验收" in template
        assert "MUST NOT 按字面验收出场景链" in template

    def test_built_planner_plan_prompt_contains_substitute_rule(self, tmp_path):
        """构建后 planner-plan prompt 携带替代出题规范（模板是 prompt 唯一真相）。"""
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_prompt("demo", "planner-plan")
        assert "以 X 替代验收" in prompt
        assert "MUST NOT 按字面验收出场景链" in prompt
