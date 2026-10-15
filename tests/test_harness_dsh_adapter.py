"""tests/test_harness_dsh_adapter.py — DshAdapter 契约测试
（add-dsh-adapter-integration 1.4 spawn 快照 + 3.2 分类 + 4.2/4.3 usage 与
resume 判别 + 5.1/5.2 健康检查 fail-fast）。

契约源：dsh-bundle/docs/probe-findings.md（真机探针结论）与
dsh-bundle/tests/fixtures/headless-events.jsonl（事件形状）。argv 形态依据
dsh-bundle/README.md L118 部署命令：``dsh --profile <p> --patch <yml> headless
--json [app-args...]``。
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

from core.agent_runner.harness import (
    ENV_MODE_AGENT_RUN,
    ENV_MODE_CLEAN,
    STDERR_CLASS_CLI_NOISE,
    STDERR_CLASS_GENERIC,
    STDERR_CLASS_UNRECOGNIZED_MODEL,
    DshAdapter,
    DshAdapterConfig,
    DshSpawnConfigError,
    HarnessHealthError,
    SpawnRequest,
    resolve_adapter,
)
from core.agent_runner.harness.dsh_adapter import (
    DSH_API_KEY_ENV,
    DSH_APP_NAME,
    DSH_BUNDLE_MOUNT_MARKER,
    DSH_HEADLESS_ENTRY_MARKER,
    DSH_INIT_TOOLS,
    DSH_VERSION_WHITELIST,
    DshEventProjector,
    render_model_patch_yaml,
)
from core.agent_env_keys import dsh_banned_env_keys

# ── 代表 lane 的 SpawnRequest（provider 链分配形态，与 runner 1462-1476
#    env_overrides 组装同构）────────────────────────────────────────────────


def _make_request(**overrides) -> SpawnRequest:
    fields = dict(
        prompt="实现任务 1.1：build_spawn_spec",
        cwd="/tmp/wt/spec-abc",
        output_format="stream-json",
        model="glm-5.3-flash",
        resume_session_id=None,
        env_overrides={
            "ANTHROPIC_BASE_URL": "http://127.0.0.1:18787/v1",
            "ANTHROPIC_API_KEY": "sk-test-key",
            "ANTHROPIC_MODEL": "glm-5.3-flash",
            "CLAUDE_CONFIG_DIR": "/tmp/claude-agent-config",
            "MY_CUSTOM_OVERRIDE": "1",
        },
        env_mode=ENV_MODE_AGENT_RUN,
        project_root="/repo",
        add_dir_cwd=True,
        max_turns=300,
    )
    fields.update(overrides)
    return SpawnRequest(**fields)


def _make_adapter(**config_overrides) -> DshAdapter:
    cfg = dict(profile="fenix", dsh_home="")
    cfg.update(config_overrides)
    return DshAdapter(DshAdapterConfig(**cfg))


# ── 1.1/1.4：spawn 契约快照 ──────────────────────────────────────────────


class TestSpawnContract:
    def test_spawn_snapshot_fresh_session(self, tmp_path):
        """场景「spawn 契约快照」：argv 含 headless 与 --json、stdin 为完整
        prompt、cwd 为 worktree、env 无 ANTHROPIC_* 残留、Bundle 模型配置含
        显式 model。"""
        adapter = _make_adapter()
        spec = adapter.build_spawn_spec(_make_request(cwd=str(tmp_path / "wt")))
        # argv：dsh --profile fenix --patch <yml> --json（全新会话
        # MUST NOT 传 --session-id——严格采纳语义，未知 id 秒挂）
        assert spec.argv[0] == "dsh"
        assert spec.argv[1:3] == ["--profile", "fenix"]
        patch_idx = spec.argv.index("--patch")
        assert patch_idx == 3
        patch_path = spec.argv[patch_idx + 1]
        # 裸 "headless" MUST NOT 出现（会占用任务 positional 槽位，stdin
        # prompt 被忽略——run4 实证）；--patch 后直接接 --json
        assert DSH_APP_NAME not in spec.argv
        assert "--json" in spec.argv
        assert spec.argv.index("--json") == patch_idx + 2
        assert "--session-id" not in spec.argv
        # prompt 全文经 stdin 载荷；cwd 为 worktree
        assert spec.stdin_payload == "实现任务 1.1：build_spawn_spec"
        assert spec.cwd == str(tmp_path / "wt")
        assert spec.start_new_session is True
        # Bundle 模型配置：patch 文件含显式 model/baseURL/apiKeyEnv（绝不回退
        # dsh 默认档）；patch 落系统临时目录（仓树外）
        patch_text = Path(patch_path).read_text(encoding="utf-8")
        assert "- id: fenix-model-config" in patch_text
        assert "fenix-model-config" in patch_text
        assert "glm-5.3-flash" in patch_text
        assert "http://127.0.0.1:18787/v1" in patch_text
        assert DSH_API_KEY_ENV in patch_text
        assert str(patch_path).startswith("/tmp")
        os.unlink(patch_path)

    def test_spawn_snapshot_resume(self):
        """resume 传真实 dsh session id（--session-id 在 app args 段）。"""
        spec = _make_adapter().build_spawn_spec(
            _make_request(resume_session_id="session-659dbd1d"))
        idx = spec.argv.index("--session-id")
        assert spec.argv[idx + 1] == "session-659dbd1d"
        assert idx > spec.argv.index("--json")

    def test_spawn_env_no_crosstalk_and_bridging(self, monkeypatch):
        """env 段：ANTHROPIC_*/CLAUDE_* 防串扰剔除（含继承值）、非禁用
        override 透传、FENIX_RUN_* 注入、凭据桥接。"""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-inherited")
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok-inherited")
        monkeypatch.setenv("CLAUDE_CODE_ENABLE_TODO_TOOLS", "1")
        monkeypatch.setenv("DSH_HOME", "/inherited-dsh-home")
        monkeypatch.setenv("FENIX_DSH_PROVIDER_API_KEY", "sk-stale")
        monkeypatch.setenv("KEEP_ME", "yes")
        spec = _make_adapter().build_spawn_spec(_make_request())
        env = spec.env
        for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
                    "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL",
                    "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_ENABLE_TODO_TOOLS"):
            assert key not in env
        # DSH_HOME 继承值剔除（配置单一来源；本 adapter 未配置 dsh_home）
        assert "DSH_HOME" not in env
        # 凭据桥接：provider 链 apikey → apiKeyEnv 指名变量（非继承/stale 值）
        assert env[DSH_API_KEY_ENV] == "sk-test-key"
        # agent-run 注入 + 非禁用 override 透传
        assert env["FENIX_RUN_PROJECT_ROOT"] == "/repo"
        assert env["FENIX_RUN_WORKTREE"] == "/tmp/wt/spec-abc"
        assert env["MY_CUSTOM_OVERRIDE"] == "1"
        assert env["KEEP_ME"] == "yes"

    def test_spawn_env_override_banned_dropped_without_ambient(
            self, monkeypatch):
        """BUG-01 回归：覆写键按**键自身**匹配 dsh banned 口径剔除，不依赖
        ambient 是否恰好存在同名键（ambient 无 ANTHROPIC_* 时覆写的
        ANTHROPIC_AUTH_TOKEN/ANTHROPIC_MODEL 曾原样回灌子进程环境）。"""
        for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
                    "ANTHROPIC_MODEL", "ANTHROPIC_BASE_URL",
                    "ANTHROPIC_API_KEY", "CLAUDE_CONFIG_DIR",
                    "CLAUDE_CODE_ENABLE_TODO_TOOLS"):
            monkeypatch.delenv(key, raising=False)
        spec = _make_adapter().build_spawn_spec(_make_request(env_overrides={
            "ANTHROPIC_BASE_URL": "http://127.0.0.1:18787/v1",
            "ANTHROPIC_API_KEY": "sk-test-key",
            "ANTHROPIC_AUTH_TOKEN": "tok-override",
            "ANTHROPIC_MODEL": "glm-5.3-flash",
            "CLAUDE_CONFIG_DIR": "/tmp/claude-agent-config",
            "MY_CUSTOM_OVERRIDE": "1",
        }))
        env = spec.env
        for key in ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY",
                    "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_MODEL",
                    "CLAUDE_CONFIG_DIR"):
            assert key not in env, key
        # 非禁用覆写键照常透传；凭据桥接不受影响
        assert env["MY_CUSTOM_OVERRIDE"] == "1"
        assert env[DSH_API_KEY_ENV] == "sk-test-key"

    def test_spawn_dsh_home_config_injected(self, monkeypatch):
        monkeypatch.setenv("DSH_HOME", "/inherited-dsh-home")
        spec = _make_adapter(dsh_home="/opt/dsh-home").build_spawn_spec(
            _make_request())
        assert spec.env["DSH_HOME"] == "/opt/dsh-home"

    def test_spawn_clean_mode_no_fenix_run_keys(self):
        """clean 口径（一次性 spawn）：无 FENIX_RUN_* 注入，凭据桥接保留。"""
        spec = _make_adapter().build_spawn_spec(
            _make_request(env_mode=ENV_MODE_CLEAN))
        assert "FENIX_RUN_PROJECT_ROOT" not in spec.env
        assert "FENIX_RUN_WORKTREE" not in spec.env
        assert spec.env[DSH_API_KEY_ENV] == "sk-test-key"

    def test_spawn_fail_fast_missing_provider_chain(self):
        """三要素缺失 fail-fast（绝不回退 dsh 默认档，错误含修复指引）。"""
        with pytest.raises(DshSpawnConfigError) as ei:
            _make_adapter().build_spawn_spec(
                _make_request(env_overrides={}))
        assert "provider" in str(ei.value)
        assert "claude" in str(ei.value)

    def test_spawn_fail_fast_missing_model(self):
        with pytest.raises(DshSpawnConfigError):
            _make_adapter().build_spawn_spec(_make_request(model=None))

    def test_spawn_same_request_byte_stable(self):
        """对同一请求逐字节稳定（protocol SpawnSpec 契约；patch 文件路径除
        外——同实例多次 spawn 按 _last_patch_path 回收：下一次 spawn 前 unlink
        上一次 patch 文件，故先建 spec 的路径可能已被回收，清理须去重+判存）。"""
        adapter = _make_adapter()
        spec_a = adapter.build_spawn_spec(_make_request())
        spec_b = adapter.build_spawn_spec(_make_request())
        assert spec_a.argv[:3] == spec_b.argv[:3]
        assert spec_a.argv[5:] == spec_b.argv[5:]  # patch 路径之后逐字节相等
        assert spec_a.stdin_payload == spec_b.stdin_payload
        assert spec_a.env == spec_b.env
        for path in {spec_a.argv[4], spec_b.argv[4]}:
            if os.path.exists(path):
                os.unlink(path)

    def test_render_model_patch_yaml_shape(self):
        text = render_model_patch_yaml(
            model="m-1", base_url="http://h:1/v1",
            api_key_env="K", provider_name="fenix-dsh")
        data = None
        try:
            import yaml
            data = yaml.safe_load(text)
        except ImportError:
            data = None
        if data is not None:
            seg = data[0]["config"]["model"]
            assert seg == {
                "provider": "fenix-dsh",
                "baseURL": "http://h:1/v1",
                "apiKeyEnv": "K",
                "model": "m-1",
            }
        else:
            assert '- id: fenix-model-config' in text
            assert 'model: "m-1"' in text

    def test_render_model_patch_yaml_api_field(self):
        """api 非空渲染线协议行（anthropic-messages 场景）；空不渲染
        （Bundle 端缺省 openai-completions，向后兼容）。"""
        text = render_model_patch_yaml(
            model="m-1", base_url="https://gw/api/anthropic",
            api_key_env="K", api="anthropic-messages")
        assert 'api: "anthropic-messages"' in text
        text_plain = render_model_patch_yaml(
            model="m-1", base_url="http://h:1/v1", api_key_env="K")
        assert "\n      api:" not in text_plain

    def test_spawn_config_api_threaded_into_patch(self, monkeypatch):
        """DshAdapterConfig.api 经 _write_model_patch 渲染进 spawn patch。"""
        adapter = _make_adapter(api="anthropic-messages")
        spec = adapter.build_spawn_spec(_make_request())
        assert spec.argv.count("--patch") == 1
        patch_path = spec.argv[spec.argv.index("--patch") + 1]
        with open(patch_path, encoding="utf-8") as fh:
            content = fh.read()
        assert 'api: "anthropic-messages"' in content
        assert 'baseURL: "http://127.0.0.1:18787/v1"' in content

    def test_patch_recycling_age_based_not_slot_based(self):
        """并发 spawn 不互踩：刚写未读的 patch 不被下一次 spawn unlink
        （单槽回收在全局 adapter 单例下曾致 a1 ENOENT 秒死）。"""
        import os
        import time as _time
        adapter = _make_adapter()
        first = adapter.build_spawn_spec(_make_request())
        first_path = first.argv[first.argv.index("--patch") + 1]
        second = adapter.build_spawn_spec(_make_request())
        second_path = second.argv[second.argv.index("--patch") + 1]
        assert first_path != second_path
        assert os.path.exists(first_path), "新鲜 patch 被槽位回收互踩"
        assert os.path.exists(second_path)
        # 到龄回收：把首个条目改成超龄，第三次 spawn 应清掉它、保留新鲜的两个
        adapter._patch_files[0] = (
            first_path, _time.monotonic() - 3601.0)
        third = adapter.build_spawn_spec(_make_request())
        third_path = third.argv[third.argv.index("--patch") + 1]
        assert not os.path.exists(first_path), "超龄 patch 未被回收"
        assert os.path.exists(second_path), "未到期 patch 被误回收"
        assert os.path.exists(third_path)


# ── 1.2：process_patterns 与 capabilities ────────────────────────────────


class TestCapabilities:
    def test_process_patterns(self):
        assert _make_adapter().process_patterns() == ["dsh", "dsh.exe"]

    def test_capabilities_per_probe(self):
        caps = _make_adapter().capabilities()
        d = caps.to_dict()
        json.dumps(d)  # 纯 JSON 可序列化（协议 Scenario）
        assert d["name"] == "dsh"
        assert d["stream_json_output"] is True
        assert d["resume_supported"] is True
        assert d["isolated_settings_supported"] is False
        assert d["max_turns_enforcement"] == "daemon-side"
        assert d["process_patterns"] == ["dsh", "dsh.exe"]

    def test_worktree_pgrep_patterns_escaped(self):
        pats = _make_adapter().worktree_pgrep_patterns("my.spec+1")
        assert pats == [
            f"{prefix}-{pats and __import__('re').escape('my.spec+1')}-"
            for prefix in ("impl", "verify", "repair")
        ]


# ── 3.1/3.2：stderr 分类（dsh 错误码表 → 既有枚举；claude 行为不变）──────


class TestClassifyStderr:
    def test_dsh_unknown_model_line(self):
        line = ('dsh: UNKNOWN_MODEL: pi-ai provider "fenix-mock" has no '
                'configured model "no-such-model"')
        assert _make_adapter().classify_stderr(line) == (
            STDERR_CLASS_UNRECOGNIZED_MODEL)

    def test_dsh_ratelimit_maps_through_translation(self):
        """场景「dsh 429 归因到 ratelimit」：限流类错误行经改写命中
        classify_ratelimit_error → 走与 claude 一致的熔断/退避治理路径。"""
        from core.agent_runner.provider_circuit import ProviderCircuit

        line = "dsh: RATE_LIMIT: 您的账户已达到速率限制"
        assert ProviderCircuit.classify_ratelimit_error(line) is True
        assert ProviderCircuit.classify_switch_error(line) is True
        # 行级分类不误报拒模型（限流非确定性死因）
        assert _make_adapter().classify_stderr(line) == STDERR_CLASS_GENERIC

    def test_dsh_transport_conservative_transient(self):
        """粗化族（自定义端点 HTTP 错误一律 TRANSPORT）保守按连接类处理，
        不伪造 HTTP 状态码（probe 建议）。"""
        from core.agent_runner.provider_circuit import ProviderCircuit

        line = "dsh: TRANSPORT: Connection error."
        assert ProviderCircuit.classify_switch_error(line) is True
        assert ProviderCircuit.parse_api_error_status(line) is None
        assert ProviderCircuit.classify_ratelimit_error(line) is False

    def test_dsh_missing_credential_not_in_circuit(self):
        """MISSING_CREDENTIAL 是部署配置错误：不改写 → 不命中任何分类器
        （不入熔断，generic 失败收场）。"""
        from core.agent_runner.provider_circuit import ProviderCircuit

        line = ('dsh: MISSING_CREDENTIAL: no credential for provider route '
                '"fenix-mock"; its profile resolves FENIX_MOCK_KEY, which is not set')
        assert ProviderCircuit.classify_switch_error(line) is False
        assert ProviderCircuit.classify_ratelimit_error(line) is False
        assert ProviderCircuit.classify_unrecognized_model_error(line) is False
        assert ProviderCircuit.parse_api_error_status(line) is None
        assert _make_adapter().classify_stderr(line) == STDERR_CLASS_GENERIC

    def test_dsh_startup_failed_generic(self):
        assert _make_adapter().classify_stderr(
            "dsh: startup failed: profile boot error") == STDERR_CLASS_GENERIC

    def test_claude_shaped_lines_parity_with_claude_adapter(self):
        """claude 形状 stderr 行：dsh adapter 分类与 ClaudeAdapter 判定全等
        （同序委托——拒模型判别先于降噪口径，claude 通道行为零变化）。"""
        from core.agent_runner.harness import ClaudeAdapter

        claude = ClaudeAdapter().classify_stderr
        dsh = _make_adapter().classify_stderr
        lines = [
            "[claude-code:unrecognized_model] Model \"x\" not found",
            "unrecognized model \"glm-x\"",
            "API Error: Request rejected (429)",
            "HTTP 500 Internal Server Error",
            "connect ECONNREFUSED 127.0.0.1:8787",
            "",
        ]
        for line in lines:
            assert dsh(line) == claude(line), line
        assert dsh("") == STDERR_CLASS_GENERIC

    def test_claude_classifier_snapshot_equality(self):
        """场景「claude 分类行为不变」：既有 stderr 用例回放分类结果全等
        （翻译对非 dsh 签名恒等）。"""
        from core.agent_runner.provider_circuit import ProviderCircuit

        cases = [
            ("API Error: Request rejected (429) · [1302][rate limit]",
             {"ratelimit": True, "switch": True, "status": 429}),
            ("[claude-code:unrecognized_model] Model not found",
             {"ratelimit": False, "switch": True, "status": None}),
            ("HTTP 404 Not Found", {"ratelimit": False, "switch": False,
                                    "status": 404}),
            ("HTTP 500 Internal Server Error", {"ratelimit": False,
                                                "switch": True, "status": 500}),
            ("connect ECONNREFUSED 127.0.0.1:8787", {"ratelimit": False,
                                                     "switch": True,
                                                     "status": None}),
        ]
        for text, want in cases:
            assert ProviderCircuit.classify_ratelimit_error(text) is want["ratelimit"], text
            assert ProviderCircuit.classify_switch_error(text) is want["switch"], text
            assert ProviderCircuit.parse_api_error_status(text) == want["status"], text
            # 翻译恒等
            from core.agent_runner.provider_circuit import translate_dsh_error_text
            assert translate_dsh_error_text(text) == text


# ── 4.2：extract_result 与 usage 分支 ────────────────────────────────────


def _replay_fixture(tmp_path: Path, extra_lines=()):
    """以 SPEC-2 fixtures 为契约源回放投影，返回（投影器, 投影事件列表）。"""
    fixture = (
        Path(__file__).resolve().parents[1]
        / "dsh-bundle" / "tests" / "fixtures" / "headless-events.jsonl"
    )
    projector = DshEventProjector("replay", str(tmp_path))
    projected = []
    with fixture.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            projected.extend(projector.ingest(line, json.loads(line)))
    for line in extra_lines:
        projected.extend(projector.ingest(line, json.loads(line)))
    return projector, projected


class TestExtractResult:
    def test_extract_from_projected_final(self, tmp_path):
        """session_id/num_turns/final 文本提取；usage 按 step_end 求和
        （usage_source: available——probe 结论）。"""
        _, projected = _replay_fixture(tmp_path)
        results = [e for e in projected if e["type"] == "result"]
        assert len(results) == 1
        out = _make_adapter().extract_result(results)
        assert out["observed"] is True
        assert out["session_id"].startswith("session-")
        assert out["turns"] == 1  # fixtures 单 turn_end
        assert out["output"]  # final 文本
        usage = out["usage_info"]
        assert usage["input_tokens"] == 256  # 128 + 128（两 step_end 求和）
        assert usage["output_tokens"] == 64  # 32 + 32
        assert usage["cost_usd"] is None  # 不伪造成本
        assert usage["usage_source"] == "available"

    def test_unobserved_returns_zero_not_fabricated(self):
        out = _make_adapter().extract_result([])
        assert out["observed"] is False
        assert out["usage_info"]["input_tokens"] == 0
        assert out["usage_info"]["unobserved"] is True
        assert out["usage_info"]["usage_source"] == "unobserved"
        # unobserved 归因方向与 claude 通道有意分歧（dsh 契约「error 无
        # final」→ 无 result 即异常终态，见 extract_result docstring）——
        # 锚定防后续按「键形状全等」顺手统一改错方向
        assert out["is_error"] is True
        assert out["subtype"] == ""

    def test_usage_unavailable_marked_not_fabricated(self, tmp_path):
        """无 step_end usage 的流（error 先于任何 step_end）→ usage_source
        unavailable（不伪造数值）。"""
        lines = [
            json.dumps({"type": "session", "sessionId": "session-u1",
                        "cwd": "/w"}),
            json.dumps({"type": "final", "text": "done",
                        "reason": {"kind": "completed"}}),
        ]
        projector = DshEventProjector("u1", str(tmp_path))
        projected = []
        for line in lines:
            projected.extend(projector.ingest(line, json.loads(line)))
        out = _make_adapter().extract_result(
            [e for e in projected if e["type"] == "result"])
        assert out["usage_info"]["usage_source"] == "unavailable"
        assert out["usage_info"]["input_tokens"] == 0


# ── 4.1：session 命名空间与 resume 采纳失败判别 ──────────────────────────


class TestSessionBinding:
    def test_session_bookkeeping_key_namespace(self):
        from core.agent_runner.session import SessionTracker

        assert SessionTracker.dsh_session_key("r-1a2b") == "fenix-r-1a2b"
        assert _make_adapter().session_bookkeeping_key("r-1a2b") == (
            "fenix-r-1a2b")

    def test_is_resume_dead_error_unknown_id(self):
        """场景「resume 失败回退不悬挂」判别面：未知 id（探针实测文案）。"""
        err = ('session "session-dead" does not exist; omit --session-id '
               'to start a new Session')
        assert _make_adapter().is_resume_dead_error(err) is True

    def test_is_resume_dead_error_negative(self):
        assert _make_adapter().is_resume_dead_error(
            "dsh: RATE_LIMIT: 429") is False
        assert _make_adapter().is_resume_dead_error("") is False
        # claude 通道文案不误判（runner 既有字面判定覆盖它）
        assert _make_adapter().is_resume_dead_error(
            "No conversation found with session ID") is False

    def test_is_resume_dead_error_fallback_branches(self):
        """宽松兜底分支锚点：held/refus/mismatch（错误文本签名未逐字实测
        ——本用例固化当前行为快照；探针实测签名回收并收窄
        DSH_SESSION_ADOPT_FALLBACK_PATTERN 时同步改写本锚点）。"""
        adapter = _make_adapter()
        assert adapter.is_resume_dead_error(
            'session "session-x" is held by another process') is True
        assert adapter.is_resume_dead_error(
            "session adoption refused by owner") is True
        assert adapter.is_resume_dead_error(
            "session cwd mismatch: /a != /b") is True
        # 大小写不敏感（re.IGNORECASE）
        assert adapter.is_resume_dead_error(
            "SESSION HELD by another run") is True

    def test_is_resume_dead_error_fallback_hit_surface(self):
        """兜底命中面边界（已知取舍的锚定）：需同时含 session 词干与否定
        词——只含其一不判死（误判代价仅是新会话回退重跑一次）。"""
        adapter = _make_adapter()
        assert adapter.is_resume_dead_error(
            "cwd mismatch for worktree /w") is False
        assert adapter.is_resume_dead_error(
            "held by another process") is False
        assert adapter.is_resume_dead_error(
            "session resumed successfully") is False

    def test_fresh_session_never_passes_session_id(self):
        """全新会话 MUST NOT 传 --session-id（严格采纳语义）。"""
        spec = _make_adapter().build_spawn_spec(_make_request())
        assert "--session-id" not in spec.argv


# ── 5.1/5.2：健康检查 fail-fast（mock subprocess，无真 dsh 依赖）─────────


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestCheckHealth:
    def test_healthy_passes(self, monkeypatch):
        def fake_run(argv, **kwargs):
            if "--version" in argv:
                return _FakeCompleted(0, stdout="0.2.0-rc.2\n")
            assert "--dump-config" in argv
            assert "--profile" in argv
            return _FakeCompleted(
                0, stdout=(f"# == @deepseek-ai/dsh-base\n"
                           f"{DSH_HEADLESS_ENTRY_MARKER}\n"
                           f"{DSH_BUNDLE_MOUNT_MARKER}\n"))

        monkeypatch.setattr(subprocess, "run", fake_run)
        _make_adapter().check_health()  # 不抛即通过

    def test_missing_binary_fail_fast(self, monkeypatch):
        def fake_run(argv, **kwargs):
            raise FileNotFoundError("dsh not found")

        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(HarnessHealthError) as ei:
            _make_adapter().check_health()
        msg = str(ei.value)
        assert "npm install" in msg or "README" in msg  # 修复指引
        assert "claude" in msg  # 回退出口指引

    def test_version_mismatch_fail_fast(self, monkeypatch):
        def fake_run(argv, **kwargs):
            return _FakeCompleted(0, stdout="0.9.9\n")

        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(HarnessHealthError) as ei:
            _make_adapter().check_health()
        msg = str(ei.value)
        assert "0.9.9" in msg
        assert "版本" in msg
        assert list(DSH_VERSION_WHITELIST)[0] in msg  # 白名单指引

    def test_bundle_not_mounted_fail_fast(self, monkeypatch):
        def fake_run(argv, **kwargs):
            if "--version" in argv:
                return _FakeCompleted(0, stdout="0.2.0-rc.2\n")
            return _FakeCompleted(0, stdout="# == @deepseek-ai/dsh-base\n")

        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(HarnessHealthError) as ei:
            _make_adapter().check_health()
        msg = str(ei.value)
        assert "fenix-dsh-bundle" in msg
        assert DSH_BUNDLE_MOUNT_MARKER in msg

    def test_headless_runtime_missing_fail_fast(self, monkeypatch):
        """bundle 清单缺 @deepseek-ai/dsh-headless（全新 home 实测 hang 形态）：
        dump 有 fenix-model-config 但无 headless-runner 条目 → 当场拦截，
        不放出注定在 loader.await() 静默永等的 spawn。"""
        def fake_run(argv, **kwargs):
            if "--version" in argv:
                return _FakeCompleted(0, stdout="0.2.0-rc.2\n")
            return _FakeCompleted(
                0, stdout=f"# == @deepseek-ai/dsh-base\n{DSH_BUNDLE_MOUNT_MARKER}\n")

        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(HarnessHealthError) as ei:
            _make_adapter().check_health()
        msg = str(ei.value)
        assert DSH_HEADLESS_ENTRY_MARKER in msg
        assert "dsh-headless" in msg  # 修复指引点名缺失的 bundle
        assert "bundles" in msg  # 指到登记处

    def test_version_command_failure_fail_fast(self, monkeypatch):
        def fake_run(argv, **kwargs):
            return _FakeCompleted(1, stdout="", stderr="command not found")

        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(HarnessHealthError):
            _make_adapter().check_health()

    def test_version_on_stderr_fallback(self, monkeypatch):
        """版本走 stderr 的 CLI 惯例差异：stdout 空时回退 stderr 首行做白
        名单比对（不把输出通道差异误报成「版本不在白名单」）。"""
        def fake_run(argv, **kwargs):
            if "--version" in argv:
                return _FakeCompleted(0, stdout="", stderr="0.2.0-rc.2\n")
            return _FakeCompleted(
                0, stdout=(f"# == @deepseek-ai/dsh-base\n"
                           f"{DSH_HEADLESS_ENTRY_MARKER}\n"
                           f"{DSH_BUNDLE_MOUNT_MARKER}\n"))

        monkeypatch.setattr(subprocess, "run", fake_run)
        _make_adapter().check_health()  # 不抛即通过

    def test_version_output_absent_reports_empty_version(self, monkeypatch):
        """两通道皆空（真实的「无版本输出」而非通道差异）：version '' 仍
        落白名单失败分支，报错文案呈现空版本号属预期。"""
        def fake_run(argv, **kwargs):
            if "--version" in argv:
                return _FakeCompleted(0, stdout="", stderr="")
            return _FakeCompleted(
                0, stdout=(f"# == @deepseek-ai/dsh-base\n"
                           f"{DSH_HEADLESS_ENTRY_MARKER}\n"
                           f"{DSH_BUNDLE_MOUNT_MARKER}\n"))

        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(HarnessHealthError) as ei:
            _make_adapter().check_health()
        assert "版本" in str(ei.value)
        assert "''" in str(ei.value)


# ── patch 临时文件回收（_write_model_patch /tmp 累积治理）────────────────


class TestModelPatchRecycle:
    def test_next_spawn_unlinks_previous_patch(self):
        """（改版）回收按龄不按槽：同实例多次 spawn 各自 patch 均在保留期
        内共存（并发派发不互踩）；仅超龄条目在下一次 spawn 前被回收
        （best-effort）——旧「单槽 unlink 上一份」契约在全局 adapter 单例
        下会互踩刚写未读的 patch，已废（2026-10-14 夹具 a1 ENOENT 实证）。
        年龄边界行为见 TestDshSpawnContract.test_patch_recycling_age_based_not_slot_based。"""
        adapter = _make_adapter()
        first = adapter.build_spawn_spec(
            _make_request(resume_session_id="session-r1"))
        p1 = first.argv[first.argv.index("--patch") + 1]
        assert os.path.exists(p1)
        second = adapter.build_spawn_spec(
            _make_request(resume_session_id="session-r2"))
        p2 = second.argv[second.argv.index("--patch") + 1]
        assert p1 != p2
        assert os.path.exists(p1)  # 保留期内共存（不再按槽回收）
        assert os.path.exists(p2)
        os.unlink(p1)
        os.unlink(p2)


class TestFactoryRegistration:
    def test_resolve_dsh_registered(self):
        """5.1：工厂注册 dsh（解除 SPEC-1 fail-fast），不静默回退 claude。"""
        adapter = resolve_adapter("dsh")
        assert isinstance(adapter, DshAdapter)
        assert adapter.name == "dsh"
        assert adapter.profile == "fenix"  # 缺省 profile（README 部署约定）

    def test_resolve_dsh_config_keys(self):
        adapter = resolve_adapter(
            "dsh", {"agent": {"dsh_profile": "p2", "dsh_home": "/h"}})
        assert adapter.profile == "p2"
        assert adapter.dsh_home == "/h"

    def test_resolve_claude_identity(self):
        from core.agent_runner.harness import ClaudeAdapter

        assert isinstance(resolve_adapter("claude"), ClaudeAdapter)

    def test_resolve_unknown_fail_fast(self):
        import pytest as _pytest

        with _pytest.raises(ValueError):
            resolve_adapter("codex")


# ── 6.3：harness_notes 注入文本 ──────────────────────────────────────────


class TestHarnessNotes:
    def test_harness_notes_headless_model(self):
        notes = _make_adapter().harness_notes()
        assert "stdin" in notes
        assert "result gate" in notes
        # 与 claude 现状文本（prompt_builder 常量）不同（差异仅落在
        # harness_notes 段——快照测试在 test_prompt_harness_notes.py 对账）
        from core.agent_runner.prompt_builder import CLAUDE_HARNESS_NOTES
        assert notes != CLAUDE_HARNESS_NOTES

    def test_prompt_tool_contract_untouched_by_adapter(self):
        """Task 工具族契约段属 prompt_builder 静态主体，adapter 注入面仅
        harness_notes——注入值不携带 Task 契约改写（该段一字不改）。"""
        notes = _make_adapter().harness_notes()
        assert "TaskCreate" not in notes
        assert "TaskUpdate" not in notes


# ── dsh banned env 口径（1.3）────────────────────────────────────────────


class TestDshBannedEnvKeys:
    def test_prefix_and_exact_matches(self):
        env = {
            "ANTHROPIC_API_KEY": "x",
            "ANTHROPIC_CUSTOM_HEADERS": "y",
            "CLAUDE_CODE_ENABLE_TODO_TOOLS": "1",
            "CLAUDE_CONFIG_DIR": "/c",
            "DSH_HOME": "/d",
            "FENIX_DSH_PROVIDER_API_KEY": "k",
            "PATH": "/bin",
            "FENIX_RUN_PROJECT_ROOT": "/r",
        }
        banned = set(dsh_banned_env_keys(env))
        assert banned == {
            "ANTHROPIC_API_KEY", "ANTHROPIC_CUSTOM_HEADERS",
            "CLAUDE_CODE_ENABLE_TODO_TOOLS", "CLAUDE_CONFIG_DIR",
            "DSH_HOME", "FENIX_DSH_PROVIDER_API_KEY",
        }

    def test_claude_agent_run_banned_keys_unchanged(self):
        from core.agent_env_keys import AGENT_RUN_BANNED_ENV_KEYS

        assert AGENT_RUN_BANNED_ENV_KEYS == frozenset({
            "FENIX_RUN_PROJECT_ROOT", "FENIX_RUN_WORKTREE",
            "CLAUDE_CODE_ENABLE_TODO_TOOLS",
        })


# ── 投影器健全性（工具表/事件词表常量与探针对账）─────────────────────────


class TestProjectionConstants:
    def test_init_tools_include_task_family(self):
        for tool in ("TaskCreate", "TaskGet", "TaskList", "TaskUpdate"):
            assert tool in DSH_INIT_TOOLS
        assert len(DSH_INIT_TOOLS) == 28  # 4 Task 工具 + 24 原生工具

    def test_version_whitelist_pinned(self):
        assert DSH_VERSION_WHITELIST == ("0.2.0-rc.2",)
