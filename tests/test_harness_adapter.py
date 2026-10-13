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
import subprocess

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
