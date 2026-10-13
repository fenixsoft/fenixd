"""harness 适配层协议完整性测试（add-harness-adapter-layer task 1.2）。

覆盖：
- claude_adapter 实例满足协议成员完整性（HARNESS_ADAPTER_MEMBERS 单源七成员
  全部存在，方法可调用、name 为字符串标识）
- HarnessCapabilities 可 json.dumps 往返（SPEC-2 Bundle 侧对账前提）
- SpawnRequest/SpawnSpec/HarnessCapabilities 为独立数据类
- resolve_adapter 工厂：claude→ClaudeAdapter、dsh fail-fast（「dsh adapter
  未部署」）、未知值 fail-fast
- 进程级当前 adapter 持有：注入/读取/未注入回落 claude（变更前行为）
- SpawnSpec 形状可直接驱动 subprocess.Popen（形参名对账，不真 spawn）

字节级 argv/env/stdin 等价对照（快照）归 tests/test_harness_claude_snapshot.py
（task 2.4），本文件不重复。
"""

import dataclasses
import inspect
import json
import os
import subprocess
from unittest.mock import patch

import pytest

import core.agent_runner.harness as harness_pkg
from core.agent_runner.harness import (
    HARNESS_ADAPTER_MEMBERS,
    VALID_HARNESS_VALUES,
    ClaudeAdapter,
    HarnessAdapter,
    HarnessCapabilities,
    HarnessNotDeployedError,
    SpawnRequest,
    SpawnSpec,
    current_process_patterns,
    current_worktree_pgrep_patterns,
    get_current_adapter,
    resolve_adapter,
    resolve_adapter_from_config,
    set_current_adapter,
)
from core.agent_runner.harness.claude_adapter import build_env


@pytest.fixture(autouse=True)
def _restore_current_adapter():
    """进程级当前 adapter 是全局单例——用例前后复位，防跨用例污染。"""
    set_current_adapter(None)
    yield
    set_current_adapter(None)


# ── 协议完整性 ────────────────────────────────────────────────────────

class TestProtocolCompleteness:
    """spec agent-harness-adapter「HarnessAdapter 协议」Scenario：协议完整性。"""

    def test_members_single_source_matches_spec(self):
        # 协议成员清单与 spec 列举的七成员一致（name/build_spawn_spec/
        # normalize_event/classify_stderr/extract_result/process_patterns/
        # capabilities）
        assert HARNESS_ADAPTER_MEMBERS == (
            "name",
            "build_spawn_spec",
            "normalize_event",
            "classify_stderr",
            "extract_result",
            "process_patterns",
            "capabilities",
        )

    def test_claude_adapter_satisfies_protocol(self):
        adapter = resolve_adapter("claude")
        for member in HARNESS_ADAPTER_MEMBERS:
            assert hasattr(adapter, member), f"缺少协议成员：{member}"
        for member in HARNESS_ADAPTER_MEMBERS:
            if member == "name":
                assert isinstance(adapter.name, str) and adapter.name == "claude"
            else:
                assert callable(getattr(adapter, member)), f"{member} 不可调用"

    def test_base_class_declares_all_members(self):
        # 基类显式声明全部协议成员（缺成员的 adapter 在子类化时即见
        # NotImplementedError 契约，运行期可判）
        for member in HARNESS_ADAPTER_MEMBERS:
            if member == "name":
                assert hasattr(HarnessAdapter, member)
            else:
                assert callable(getattr(HarnessAdapter, member))

    def test_capabilities_json_roundtrip(self):
        adapter = resolve_adapter("claude")
        caps = adapter.capabilities()
        assert isinstance(caps, HarnessCapabilities)
        payload = json.dumps(caps.to_dict(), ensure_ascii=False)
        restored = json.loads(payload)
        assert restored == caps.to_dict()
        # 值全为纯 JSON 标量/列表（新字段 MUST 保持该性质）
        for value in restored.values():
            assert isinstance(value, (str, bool, list))

    def test_dataclasses_are_independent(self):
        assert dataclasses.is_dataclass(SpawnRequest)
        assert dataclasses.is_dataclass(SpawnSpec)
        assert dataclasses.is_dataclass(HarnessCapabilities)
        # 三者互不为彼此字段类型（独立数据类，非嵌套别名）
        req_fields = {f.type for f in dataclasses.fields(SpawnRequest)}
        assert "SpawnSpec" not in req_fields

    def test_spawn_request_carries_lane_shape_fields(self):
        # SpawnRequest 必须携带足以承载车道与一次性 spawn 形态差异的字段
        field_names = {f.name for f in dataclasses.fields(SpawnRequest)}
        for required in (
            "prompt",
            "cwd",
            "prompt_transport",
            "output_format",
            "model",
            "resume_session_id",
            "permission_mode",
            "env_mode",
            "env_overrides",
            "timeout",
        ):
            assert required in field_names, f"SpawnRequest 缺字段：{required}"

    def test_spawn_spec_directly_drives_popen(self):
        # SpawnSpec 字段名与 subprocess.Popen 形参对账（进程边界出侧可直接驱动）
        spec_fields = {f.name for f in dataclasses.fields(SpawnSpec)}
        popen_params = set(inspect.signature(subprocess.Popen.__init__).parameters)
        for required in ("argv", "env", "cwd"):
            assert required in spec_fields
        assert "stdin_payload" in spec_fields
        for popen_kw in ("start_new_session", "text", "encoding", "errors"):
            assert popen_kw in spec_fields and popen_kw in popen_params


# ── 工厂 ──────────────────────────────────────────────────────────────

class TestResolveAdapter:
    def test_claude_resolves(self):
        adapter = resolve_adapter("claude")
        assert isinstance(adapter, ClaudeAdapter)
        assert isinstance(adapter, HarnessAdapter)

    def test_dsh_fail_fast(self):
        # spec harness-config「dsh 值 fail-fast（本阶段）」：明确错误、不静默
        # 回退 claude 代跑
        with pytest.raises(HarnessNotDeployedError) as excinfo:
            resolve_adapter("dsh")
        assert "dsh adapter 未部署" in str(excinfo.value)

    def test_unknown_value_fail_fast(self):
        with pytest.raises(ValueError):
            resolve_adapter("codex")

    def test_valid_values_single_source(self):
        assert VALID_HARNESS_VALUES == ("claude", "dsh")

    def test_resolve_from_config_deferred(self):
        # resolve_adapter_from_config 的归一化语义（缺省/回退/告警）在
        # ConfigLoader.get_harness（task 6.1 交付），场景测试归
        # tests/test_harness_config.py；此处仅断言工厂入口已导出
        assert callable(resolve_adapter_from_config)


# ── 进程级当前 adapter 持有 ────────────────────────────────────────────

class TestCurrentAdapter:
    def test_fallback_is_claude_when_unset(self):
        # 未注入时惰性回落 claude（= 变更前行为，零行为变化）
        assert isinstance(get_current_adapter(), ClaudeAdapter)
        assert current_process_patterns() == ["claude", "claude.exe"]

    def test_set_and_get(self):
        custom = ClaudeAdapter()
        set_current_adapter(custom)
        assert get_current_adapter() is custom

    def test_worktree_pgrep_patterns_shape(self):
        # claude 值与现状 admin_monitor._pgrep_live_worktree 全等（车道前缀 +
        # re.escape(spec) + 尾连字符）
        patterns = current_worktree_pgrep_patterns("my.spec+na[me]")
        assert patterns == [
            "impl-my\\.spec\\+na\\[me\\]-",
            "verify-my\\.spec\\+na\\[me\\]-",
            "repair-my\\.spec\\+na\\[me\\]-",
        ]


# ── claude adapter 轻校验（详细等价归快照测试）─────────────────────────

class TestClaudeAdapterBasics:
    def test_build_spawn_spec_main_lane_shape(self):
        adapter = ClaudeAdapter()
        req = SpawnRequest(
            prompt="do things",
            cwd="/tmp/wt",
            add_dir_cwd=True,
            permission_mode="bypassPermissions",
            project_root="/tmp/proj",
        )
        spec = adapter.build_spawn_spec(req)
        assert isinstance(spec, SpawnSpec)
        assert spec.argv[0:2] == ["claude", "-p"]
        assert "--output-format" in spec.argv and "stream-json" in spec.argv
        assert "--verbose" in spec.argv
        assert spec.stdin_payload == "do things"
        assert spec.env is not None  # agent-run 口径必产 env
        assert spec.cwd == "/tmp/wt"

    def test_normalize_event_identity(self):
        adapter = ClaudeAdapter()
        raw = {"type": "assistant", "message": {"content": []}}
        assert adapter.normalize_event(raw) == [raw]

    def test_normalize_event_drops_thinking_tokens_telemetry(self):
        adapter = ClaudeAdapter()
        raw = {"type": "system", "subtype": "thinking_tokens", "tokens": 5}
        assert adapter.normalize_event(raw) == []

    def test_extract_result_unobserved(self):
        adapter = ClaudeAdapter()
        result = adapter.extract_result([])
        assert result["observed"] is False
        assert result["output"] == ""
        assert result["usage_info"].get("unobserved") is True

    def test_extract_result_observed(self):
        adapter = ClaudeAdapter()
        event = {
            "type": "result",
            "subtype": "success",
            "result": "done",
            "num_turns": 3,
            "session_id": "abc123",
            "is_error": False,
        }
        result = adapter.extract_result([event])
        assert result["observed"] is True
        assert result["output"] == "done"
        assert result["turns"] == 3
        assert result["session_id"] == "abc123"

    def test_clean_env_mode_strips_banned_keys(self):
        # AGENT_RUN_BANNED_ENV_KEYS 应用点（task 2.3）：clean 口径剔除三键，
        # env_overrides 仍合并
        from core.agent_runner.harness import ENV_MODE_CLEAN

        req = SpawnRequest(
            prompt="one shot",
            cwd="/tmp/wt",
            env_mode=ENV_MODE_CLEAN,
            env_overrides={"ANTHROPIC_BASE_URL": "https://api.example.com"},
        )
        with patch.dict(os.environ, {
            "PATH": "/usr/bin:/bin",
            "HOME": "/fixture-home",
            "FENIX_RUN_PROJECT_ROOT": "/leaked/project",
            "FENIX_RUN_WORKTREE": "/leaked/worktree",
            "CLAUDE_CODE_ENABLE_TODO_TOOLS": "1",
        }, clear=True):
            env = build_env(req)
        assert env is not None
        assert "FENIX_RUN_PROJECT_ROOT" not in env
        assert "FENIX_RUN_WORKTREE" not in env
        assert "CLAUDE_CODE_ENABLE_TODO_TOOLS" not in env
        assert env["ANTHROPIC_BASE_URL"] == "https://api.example.com"

    def test_inherit_env_mode_returns_none(self):
        # 叙事通道现状：Popen 不带 env 参数（完整继承）
        from core.agent_runner.harness import ENV_MODE_INHERIT

        req = SpawnRequest(prompt="narrate", cwd="/tmp", env_mode=ENV_MODE_INHERIT)
        assert build_env(req) is None

    def test_classify_stderr_wordlist(self):
        adapter = ClaudeAdapter()
        # 拒模型诊断行（归因口径，经 ProviderCircuit 委托判别）
        assert (
            adapter.classify_stderr(
                "[claude-code:unrecognized_model] model 'x-y3' not found"
            )
            == "unrecognized_model"
        )
        # `[claude-code:*]` 家族其余诊断行（降噪口径，D5）
        assert adapter.classify_stderr("[claude-code:info] startup hint") == "cli_noise"
        assert adapter.classify_stderr("") == "generic"
        # generic 行不误吞
        assert adapter.classify_stderr("Traceback (most recent call last)") == "generic"


# ── 隔离 settings 构造与落盘（task 2.2 平移）──────────────────────────

class TestIsolatedSettings:
    """build_isolated_settings / ensure_agent_config_dir 平移行为。"""

    @pytest.fixture(autouse=True)
    def _isolated_home(self, monkeypatch, tmp_path):
        # HOME 指向 tmp：宿主 ~/.claude/settings.json 不参与断言（确定性）
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        self.home = home
        self.project_root = tmp_path / "proj"
        (self.project_root / ".fenix").mkdir(parents=True)
        self.config_dir = self.project_root / ".fenix" / "agent-config" / "prov-a"

    def _write_home_settings(self, payload: dict):
        (self.home / ".claude").mkdir(parents=True, exist_ok=True)
        (self.home / ".claude" / "settings.json").write_text(
            json.dumps(payload), encoding="utf-8")

    def test_schema_version_constant(self):
        from core.agent_runner.harness import ISOLATED_SETTINGS_SCHEMA_VERSION

        assert ISOLATED_SETTINGS_SCHEMA_VERSION == 2

    def test_enabled_plugins_default_and_copy(self, monkeypatch):
        from core.agent_runner.harness import build_isolated_settings

        monkeypatch.setattr(
            "core.config.ConfigLoader.get_subagent_model_override",
            classmethod(lambda cls, config: ""),
        )
        # 宿主无 enabledPlugins → 缺省 superpowers
        settings = build_isolated_settings(self.project_root)
        assert settings["enabledPlugins"] == {
            "superpowers@claude-plugins-official": True}
        # 宿主有 → 原样复制
        self._write_home_settings({"enabledPlugins": {"plug-a": True}})
        settings = build_isolated_settings(self.project_root)
        assert settings["enabledPlugins"] == {"plug-a": True}
        # provider_model 为空 → 不写 env 段（行为与变更前逐字节一致）
        assert "env" not in settings

    def test_hooks_copied_from_agent_settings(self, monkeypatch):
        from core.agent_runner.harness import build_isolated_settings

        hooks = {"PreToolUse": [{"matcher": "Read", "hooks": []}]}
        (self.project_root / ".fenix" / "agent-settings.json").write_text(
            json.dumps({"hooks": hooks}), encoding="utf-8")
        settings = build_isolated_settings(self.project_root)
        assert settings["hooks"] == hooks

    def test_provider_env_subagent_mapping(self, monkeypatch):
        """provider_model 非空 → 四键 env 映射，override 优先于 provider model。"""
        from core.agent_runner.harness import build_isolated_settings

        monkeypatch.setattr(
            "core.config.ConfigLoader.get_subagent_model_override",
            classmethod(lambda cls, config: ""),
        )
        settings = build_isolated_settings(self.project_root, "glm-5.3-flash")
        assert settings["env"] == {
            "CLAUDE_CODE_SUBAGENT_MODEL": "glm-5.3-flash",
            "ANTHROPIC_DEFAULT_OPUS_MODEL": "glm-5.3-flash",
            "ANTHROPIC_DEFAULT_SONNET_MODEL": "glm-5.3-flash",
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": "glm-5.3-flash",
        }
        # agents.subagent_model_override 非空 → 优先
        monkeypatch.setattr(
            "core.config.ConfigLoader.get_subagent_model_override",
            classmethod(lambda cls, config: "override-model"),
        )
        settings = build_isolated_settings(
            self.project_root, "glm-5.3-flash", config={"agents": {}})
        assert settings["env"]["CLAUDE_CODE_SUBAGENT_MODEL"] == "override-model"

    def test_ensure_agent_config_dir_creates_and_idempotent(self, monkeypatch):
        from core.agent_runner.harness import ensure_agent_config_dir

        monkeypatch.setattr(
            "core.config.ConfigLoader.get_subagent_model_override",
            classmethod(lambda cls, config: ""),
        )
        # 首建：目录 + settings.json（含 _schema_version）
        cfg_dir = ensure_agent_config_dir(self.project_root, "prov-a", "glm-5.3-flash")
        assert cfg_dir == self.config_dir
        marker = cfg_dir / "settings.json"
        payload = json.loads(marker.read_text(encoding="utf-8"))
        assert payload["_schema_version"] == 2
        assert payload["env"]["CLAUDE_CODE_SUBAGENT_MODEL"] == "glm-5.3-flash"
        first_mtime = marker.stat().st_mtime_ns

        # 幂等：内容一致 → 不重写（mtime 不变）
        cfg_dir2 = ensure_agent_config_dir(self.project_root, "prov-a", "glm-5.3-flash")
        assert cfg_dir2 == cfg_dir
        assert marker.stat().st_mtime_ns == first_mtime

        # 内容不匹配（旧版无 env）→ 原子重写为最新映射
        marker.write_text(json.dumps({"enabledPlugins": {}}), encoding="utf-8")
        ensure_agent_config_dir(self.project_root, "prov-a", "glm-5.3-flash")
        payload = json.loads(marker.read_text(encoding="utf-8"))
        assert payload["env"]["CLAUDE_CODE_SUBAGENT_MODEL"] == "glm-5.3-flash"

    def test_ensure_agent_config_dir_symlinks(self, monkeypatch):
        """~/.claude/skills 存在 → symlink 建立；不存在 → 优雅跳过。"""
        from core.agent_runner.harness import ensure_agent_config_dir

        monkeypatch.setattr(
            "core.config.ConfigLoader.get_subagent_model_override",
            classmethod(lambda cls, config: ""),
        )
        (self.home / ".claude" / "skills").mkdir(parents=True)
        ensure_agent_config_dir(self.project_root, "prov-a")
        assert (self.config_dir / "skills").is_symlink()
        assert not (self.config_dir / "plugins").exists()  # 源缺失 → 跳过

    def test_runner_thin_delegation_parity(self, monkeypatch):
        """runner 保留薄委托：与 harness 模块函数产物一致（回归兼容面）。"""
        from tests.helpers import make_runner

        monkeypatch.setattr(
            "core.config.ConfigLoader.get_subagent_model_override",
            classmethod(lambda cls, config: ""),
        )
        runner = make_runner(self.project_root)
        runner.config = {"agents": {}}
        settings = runner._build_isolated_settings("glm-5.3-flash")
        assert settings["env"]["CLAUDE_CODE_SUBAGENT_MODEL"] == "glm-5.3-flash"
        cfg_dir = runner._ensure_agent_config_dir("prov-a", "glm-5.3-flash")
        assert cfg_dir == self.config_dir
        payload = json.loads(
            (cfg_dir / "settings.json").read_text(encoding="utf-8"))
        assert payload["_schema_version"] == 2
