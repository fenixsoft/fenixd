"""tests/test_harness_default_fallback.py — add-harness-default-key-fallback

覆盖 spec（specs/harness-default-fallback/spec.md）三个 Requirement 全部
Scenario：

1. 无分配时按 harness 自身配置启动（对称回落）——dsh 无分配 spawn 成功且
   不带 patch / dsh 部分链仍报错 / claude 无分配 spawn 成功；
2. 回落 WARN 观察钩子（一次性，进程×adapter 去重）；
3. 归因降级标记（run metrics ``provider_source: "harness-default"`` 两形态）。

背景（proposal Why）：任一 Agent 无 ``agents.models`` 分配时，claude 形态靠
环境继承天然工作，dsh 形态却在适配器预检处 fail-fast（2026-11-02 dsh-plugins
arbiter run 0.001s/0 tokens 秒败）——回落语义对 harness 对称（2026-11-03
用户裁定），取代原「绝不回退 dsh 默认档」纪律（D9）。
"""

import json
import logging
import os
from pathlib import Path

import pytest
import yaml

from core.agent_runner import AgentRunner
from core.agent_runner.harness import (
    ENV_MODE_AGENT_RUN,
    ClaudeAdapter,
    DshAdapter,
    DshAdapterConfig,
    DshSpawnConfigError,
    SpawnRequest,
    reset_harness_default_fallback_warned,
)
from core.agent_runner.harness.dsh_adapter import DSH_API_KEY_ENV
from core.logger import Logger

_HARNESS_LOGGER = "fenixd.agent_runner.harness"


# ── 基座（与 test_harness_dsh_adapter._make_request 同构）────────────────


def _make_request(**overrides) -> SpawnRequest:
    """显式 provider 链形态的 SpawnRequest（runner 既有 Provider 路由渲染）。"""
    fields = dict(
        prompt="无分配回落验证",
        cwd="/tmp/wt/spec-fallback",
        output_format="stream-json",
        model="glm-5.3-flash",
        resume_session_id=None,
        env_overrides={
            "ANTHROPIC_BASE_URL": "http://127.0.0.1:18787/v1",
            "ANTHROPIC_API_KEY": "sk-test-key",
            "ANTHROPIC_MODEL": "glm-5.3-flash",
            "CLAUDE_CONFIG_DIR": "/tmp/claude-agent-config",
        },
        env_mode=ENV_MODE_AGENT_RUN,
        project_root="/repo",
        add_dir_cwd=True,
        max_turns=300,
    )
    fields.update(overrides)
    return SpawnRequest(**fields)


def _make_dsh_adapter(**config_overrides) -> DshAdapter:
    cfg = dict(profile="fenix", dsh_home="")
    cfg.update(config_overrides)
    return DshAdapter(DshAdapterConfig(**cfg))


@pytest.fixture(autouse=True)
def _reset_fallback_warned():
    """进程级 WARN 去重登记测试间复位（单进程内收集顺序隔离）。"""
    reset_harness_default_fallback_warned()
    yield
    reset_harness_default_fallback_warned()


# ── Requirement 1：无分配时按 harness 自身配置启动（对称回落）────────────


class TestSymmetricFallback:
    def test_dsh_unassigned_spawn_success_no_patch(self, monkeypatch):
        """Scenario「dsh 无分配 spawn 成功且不带 patch」：env_overrides 无
        provider 链键 → build_spawn_spec 正常返回 SpawnSpec，argv 不含
        --patch，环境不含 FENIX_DSH_PROVIDER_API_KEY，不抛 DshSpawnConfigError。"""
        monkeypatch.setenv("FENIX_DSH_PROVIDER_API_KEY", "sk-stale")
        spec = _make_dsh_adapter().build_spawn_spec(
            _make_request(env_overrides={}, model=None))
        assert isinstance(spec.argv, list)
        assert "--patch" not in spec.argv
        assert DSH_API_KEY_ENV not in spec.env
        assert spec.argv[0] == "dsh"
        assert "--profile" in spec.argv

    def test_dsh_partial_chain_still_raises(self):
        """Scenario「dsh 部分链仍报错」：env_overrides 仅含 ANTHROPIC_BASE_URL
        （缺 apikey/model）→ 抛 DshSpawnConfigError（笔误防护语义不变）。"""
        with pytest.raises(DshSpawnConfigError):
            _make_dsh_adapter().build_spawn_spec(_make_request(env_overrides={
                "ANTHROPIC_BASE_URL": "http://127.0.0.1:18787/v1"}))

    def test_claude_unassigned_spawn_success(self, monkeypatch):
        """Scenario「claude 无分配 spawn 成功」：无分配 → spawn 成功，env 按
        既有 env_mode 语义继承（agent-run 口径=os.environ 副本+FENIX_RUN_*
        注入），行为与本 SPEC 合入前一致（argv 无 --patch 本就是 claude 形态；
        显式链 argv/env 快照由 test_harness_claude_snapshot 锁定）。"""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-inherited")
        # ambient 链键先清（claude 口径无反串扰剔除、env=os.environ 副本，
        # ambient 存量键会原样继承——断言「无链覆盖」须以无 ambient 为前提）
        for key in ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY"):
            monkeypatch.delenv(key, raising=False)
        spec = ClaudeAdapter().build_spawn_spec(
            _make_request(env_overrides={}, model=None))
        assert spec.argv[0] == "claude"
        assert "-p" in spec.argv
        assert "--patch" not in spec.argv
        # agent-run 口径既有 env 语义不变：FENIX_RUN_* 注入、无链键不覆盖
        assert spec.env["FENIX_RUN_PROJECT_ROOT"] == "/repo"
        assert "ANTHROPIC_BASE_URL" not in spec.env
        assert "ANTHROPIC_API_KEY" not in spec.env

    def test_dsh_unassigned_full_env_crosstalk_cleanup_intact(
            self, monkeypatch):
        """回落形态反串扰语义不变：ambient ANTHROPIC_* 仍被剔除、FENIX_RUN_*
        照常注入（tasks 1.2「--profile 与反串扰环境清除语义不变」）。"""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-inherited")
        spec = _make_dsh_adapter().build_spawn_spec(
            _make_request(env_overrides={}, model=None))
        assert "ANTHROPIC_API_KEY" not in spec.env
        assert spec.env["FENIX_RUN_PROJECT_ROOT"] == "/repo"
        assert spec.env["FENIX_RUN_WORKTREE"] == "/tmp/wt/spec-fallback"


# ── Requirement 2：回落 WARN 观察钩子（一次性）───────────────────────────


class TestFallbackWarn:
    def test_dsh_warn_once_per_process(self, caplog):
        """Scenario「回落 WARN 每进程仅一次」：同进程连续 3 次无分配 spawn
        （同 harness）→ 仅第 1 次产生 WARNING，第 2/3 次静默且正常 spawn。"""
        adapter = _make_dsh_adapter()
        with caplog.at_level(logging.WARNING, logger=_HARNESS_LOGGER):
            specs = [
                adapter.build_spawn_spec(
                    _make_request(env_overrides={}, model=None))
                for _ in range(3)
            ]
        # 3 次全部正常 spawn（不拒 spawn）
        assert len(specs) == 3
        assert all("--patch" not in s.argv for s in specs)
        warns = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and "未分配 provider 链" in r.message
        ]
        assert len(warns) == 1

    def test_claude_warn_once_per_process(self, caplog):
        """claude 侧对称：3 次无分配 spawn 仅 1 条 WARNING（进程×adapter
        去重粒度——与 dsh 各自独立计数）。"""
        adapter = ClaudeAdapter()
        with caplog.at_level(logging.WARNING, logger=_HARNESS_LOGGER):
            for _ in range(3):
                adapter.build_spawn_spec(
                    _make_request(env_overrides={}, model=None))
        warns = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and "未分配 provider 链" in r.message
        ]
        assert len(warns) == 1

    def test_warn_dedup_per_adapter_not_global(self, caplog):
        """去重键=adapter 名（进程×adapter）：dsh 触发过一次后 claude 首次
        回落仍各有各的一次（两 harness 对称留痕，不互相 prime）。"""
        with caplog.at_level(logging.WARNING, logger=_HARNESS_LOGGER):
            _make_dsh_adapter().build_spawn_spec(
                _make_request(env_overrides={}, model=None))
            ClaudeAdapter().build_spawn_spec(
                _make_request(env_overrides={}, model=None))
        warns = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and "未分配 provider 链" in r.message
        ]
        assert len(warns) == 2

    def test_warn_message_semantics_and_role(self, caplog):
        """WARNING 文案含「未分配 provider 链，回落 harness 默认配置」语义
        与角色名（SpawnRequest.agent_role 透传）。"""
        with caplog.at_level(logging.WARNING, logger=_HARNESS_LOGGER):
            _make_dsh_adapter().build_spawn_spec(
                _make_request(
                    env_overrides={}, model=None, agent_role="arbiter"))
        warns = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and "未分配 provider 链" in r.message
        ]
        assert len(warns) == 1
        assert "回落 harness 默认配置" in warns[0].getMessage()
        assert "arbiter" in warns[0].getMessage()

    def test_explicit_chain_no_warn(self, caplog):
        """显式全链形态不触发回落 WARN（回落判定=链键缺席，非全量告警）。"""
        with caplog.at_level(logging.WARNING, logger=_HARNESS_LOGGER):
            _make_dsh_adapter().build_spawn_spec(_make_request())
            ClaudeAdapter().build_spawn_spec(_make_request())
        warns = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and "未分配 provider 链" in r.message
        ]
        assert warns == []


# ── Requirement 3：归因降级标记（run metrics provider_source）────────────


def _make_metrics_runner(tmp_path) -> AgentRunner:
    """最小 AgentRunner（__new__ 替身）：仅装配 _log_run_metrics 依赖面。"""
    runner = AgentRunner.__new__(AgentRunner)
    runner.logger = Logger(tmp_path / ".fenix" / "logs", "DEBUG")
    return runner


def _read_metric_contexts(tmp_path) -> list:
    """从 Logger JSON 行读全部 run_metrics context（对齐
    test_run_metrics_persistence 读法）。"""
    log_file = tmp_path / ".fenix" / "logs" / "fenixd.log"
    if not log_file.exists():
        return []
    results = []
    for raw in log_file.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            entry = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        ctx = entry.get("context") or {}
        if ctx.get("metric_type") == "run_metrics":
            results.append(ctx)
    return results


class TestProviderSourceMarker:
    def test_fallback_run_metrics_carries_marker(self, tmp_path):
        """Scenario「回落 run metrics 带标记」：无分配 spawn 的 run 落
        metrics → context 含 provider_source="harness-default"。"""
        runner = _make_metrics_runner(tmp_path)
        # 登记（_run_agent spawn 装配段同款调用；attempt 子 id 归一化到 base）
        runner._register_run_provider_source(
            "impl-spec-a-1-a1", {"FENIX_OCR_BIN": "/x/ocr"})
        runner._log_run_metrics(
            run_id="impl-spec-a-1-a1", spec_name="spec-a",
            agent_type="implementer", duration_seconds=1.0, turns=2,
            usage_info={}, terminal="success", provider=None, model=None,
        )
        ctxs = _read_metric_contexts(tmp_path)
        assert len(ctxs) == 1
        assert ctxs[0]["provider_source"] == "harness-default"

    def test_explicit_chain_run_metrics_lacks_marker(self, tmp_path):
        """显式链 run（登记缺席）→ metrics 行不含 provider_source 键
        （读侧缺省=显式链，不重载既有 provider/model 键语义）。"""
        runner = _make_metrics_runner(tmp_path)
        # 显式链：env_overrides 含链键 → 不登记
        runner._register_run_provider_source("impl-spec-b-1", {
            "ANTHROPIC_BASE_URL": "http://127.0.0.1:18787/v1",
            "ANTHROPIC_API_KEY": "sk-x",
        })
        runner._log_run_metrics(
            run_id="impl-spec-b-1", spec_name="spec-b",
            agent_type="implementer", duration_seconds=1.0, turns=2,
            usage_info={}, terminal="success",
            provider="chain-a", model="glm-5.3-flash",
        )
        ctxs = _read_metric_contexts(tmp_path)
        assert len(ctxs) == 1
        assert "provider_source" not in ctxs[0]

    def test_marker_consumed_once_per_attempt(self, tmp_path):
        """消费即摘除：同一登记只进一条 metrics 行；重试 attempt 每次 spawn
        重新登记，行与行不串（对齐 _run_toolface 口径）。"""
        runner = _make_metrics_runner(tmp_path)
        runner._register_run_provider_source("impl-spec-c-1-a1", {})
        runner._log_run_metrics(
            run_id="impl-spec-c-1-a1", spec_name="spec-c",
            agent_type="implementer", duration_seconds=1.0, turns=1,
            usage_info={}, terminal="error",
        )
        runner._log_run_metrics(
            run_id="impl-spec-c-1-a1", spec_name="spec-c",
            agent_type="implementer", duration_seconds=2.0, turns=2,
            usage_info={}, terminal="error",
        )
        ctxs = _read_metric_contexts(tmp_path)
        assert len(ctxs) == 2
        assert ctxs[0].get("provider_source") == "harness-default"
        assert "provider_source" not in ctxs[1]

    def test_register_judgment_two_forms(self, tmp_path):
        """登记判定两形态（tasks 2.3）：无链键（含仅非链覆写键）登记、
        显式链不登记；attempt 子 id 归一化到 base run_id。"""
        runner = _make_metrics_runner(tmp_path)
        # 形态一：完全无链键（纯空与仅非链覆写键等价）→ 登记
        runner._register_run_provider_source("impl-spec-d-1-a1", {})
        # 形态二：显式链 → 不登记
        runner._register_run_provider_source("impl-spec-e-1", {
            "ANTHROPIC_BASE_URL": "http://127.0.0.1:18787/v1",
            "ANTHROPIC_API_KEY": "sk-x",
        })
        registry = runner.__dict__["_run_provider_source"]
        assert registry == {"impl-spec-d-1": "harness-default"}


# ── env 段补充：无桥接断言的 stale 环境形态（Requirement 1 细化）──────────


class TestFallbackEnvBridge:
    def test_dsh_unassigned_no_bridge_with_stale_ambient(self, monkeypatch):
        """ambient 残留桥接键不回灌：无 apikey 桥接分支不写
        FENIX_DSH_PROVIDER_API_KEY（build_env 无 apikey 不桥接，tasks 1.2）；
        os.environ 副本里的 stale 值随 dsh banned 口径剔除。"""
        monkeypatch.setenv("FENIX_DSH_PROVIDER_API_KEY", "sk-stale")
        spec = _make_dsh_adapter().build_spawn_spec(
            _make_request(env_overrides={}, model=None))
        assert DSH_API_KEY_ENV not in spec.env
        # 反串扰：dsh banned 口径对 ambient 的 ANTHROPIC_* 剔除不变
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://10.0.0.1:9/v1")
        spec2 = _make_dsh_adapter().build_spawn_spec(
            _make_request(env_overrides={}, model=None))
        assert "ANTHROPIC_BASE_URL" not in spec2.env

    def test_claude_unassigned_inherits_environment(self, monkeypatch):
        """claude 回落=环境继承（现状行为）：ambient 的 KEEP_ME 原样进子进程
        env（agent-run 口径=os.environ 副本+overrides 合并，无额外清除）。"""
        monkeypatch.setenv("KEEP_ME", "yes")
        spec = ClaudeAdapter().build_spawn_spec(
            _make_request(env_overrides={}, model=None))
        assert spec.env["KEEP_ME"] == "yes"
        assert os.environ.get("KEEP_ME") == "yes"


# ── bundle 侧联动断言（add-dispatch-precheck-true-fallback 4.1）──────────
#
# 「无 patch → 存活」的 spawn 侧形态由上方 TestSymmetricFallback 锁定
# （argv 不含 --patch）；本段锁定随 bundle 出货的 dsh-bundle/cordis.patch.yml
# 装配结构：agent-default-model 双行互补（D1 真对称回落）——无分配（回落
# 形态）时 dsh-base 原生行以自身默认档供数保 dsh 存活，显式链形态由插入行
# 以 fenix 三要素供数。与 dsh-bundle/tests/modelConfig.test.ts 的结构锁
# 同构（pytest 侧独立复核，防单侧漂移）。


class _JsExpr:
    """cordis.patch.yml ``!!js`` 标签的解析替身（同构 vitest JsExpr）。"""

    def __init__(self, expr: str):
        self.expr = expr


def _js_constructor(loader, node):
    return _JsExpr(loader.construct_scalar(node))


_JsLoader = type("_JsLoader", (yaml.SafeLoader,), {})
_JsLoader.add_constructor("tag:yaml.org,2002:js", _js_constructor)

_BUNDLE_PATCH = (
    Path(__file__).resolve().parent.parent / "dsh-bundle" / "cordis.patch.yml"
)


def _load_bundle_entries() -> list:
    doc = yaml.load(_BUNDLE_PATCH.read_text(encoding="utf-8"), Loader=_JsLoader)
    entries = []
    for item in doc:
        if isinstance(item, dict) and "insert" in item:
            entries.extend(item["insert"])
        else:
            entries.append(item)
    return entries


def _by_id(entries, entry_id):
    return next(e for e in entries if e.get("id") == entry_id)


def _disabled_in_mode(entry, mode: str) -> bool:
    """模拟 loader disabledOf 对 ``!!js`` disabled 的按形态求值。"""
    return f"mode === '{mode}'" in entry["disabled"].expr


class TestBundlePatchTwoRowFallback:
    def test_two_row_complementary_assembly(self):
        """双行互补装配结构：原生行无 config 键（patch 逐键覆盖语义下
        dsh-base 原生默认档原样保留）、插入行以 fenixModelConfig 三要素
        供数，两行 disabled 判定互斥。"""
        entries = _load_bundle_entries()
        native = _by_id(entries, "agent-default-model")
        inserted = _by_id(entries, "fenix-agent-default-model")
        # 原生行：只追加 inject 与互补 disabled，不携带 config 键
        assert native.get("inject") == ["fenixModelConfig"]
        assert "config" not in native
        assert "mode === 'explicit'" in native["disabled"].expr
        # 插入行：同插件名 + 三要素 !!js 取值 + 反相 disabled
        assert inserted["name"] == "@deepseek-ai/dsh-agent-default-model"
        assert inserted.get("inject") == ["fenixModelConfig"]
        assert "mode === 'fallback'" in inserted["disabled"].expr
        assert inserted["config"]["provider"].expr == "ctx.fenixModelConfig.provider"
        assert inserted["config"]["model"].expr == "ctx.fenixModelConfig.model"
        # 互斥：同一形态下两行 disabled 判定必然一真一假
        for mode in ("explicit", "fallback"):
            assert _disabled_in_mode(native, mode) != _disabled_in_mode(inserted, mode)

    def test_fallback_mode_native_row_alive(self):
        """回落形态（config.model 整体缺席）：原生行激活、插入行禁用——
        dsh 以自身默认档供数存活（无分配 spawn 不再 StartupError 的装配级
        形态；插件失败时两行一起 pending → StartupError 语义仍由 1.3 锁定）。"""
        entries = _load_bundle_entries()
        native = _by_id(entries, "agent-default-model")
        inserted = _by_id(entries, "fenix-agent-default-model")
        assert _disabled_in_mode(native, "fallback") is False
        assert _disabled_in_mode(inserted, "fallback") is True

    def test_explicit_mode_inserted_row_alive(self):
        """显式链形态：插入行激活、原生行禁用——fenix 三要素供数（与
        重构前显式链 spawn 产物语义一致）。"""
        entries = _load_bundle_entries()
        native = _by_id(entries, "agent-default-model")
        inserted = _by_id(entries, "fenix-agent-default-model")
        assert _disabled_in_mode(inserted, "explicit") is False
        assert _disabled_in_mode(native, "explicit") is True

    def test_required_plugins_unconditional_in_both_modes(self):
        """headless-runner（required 启动条目）与 llm-pi-ai 不随形态禁用：
        回落形态 providers 插值 undefined → schema 缺省 {}（dsh 零路由的
        原生休眠形态），headless-runner 两形态都激活。"""
        entries = _load_bundle_entries()
        headless = _by_id(entries, "headless-runner")
        assert "fenixModelConfig" in headless.get("inject", [])
        assert "disabled" not in headless
        llm = _by_id(entries, "llm-pi-ai")
        assert "disabled" not in llm
        assert llm["config"]["providers"].expr == "ctx.fenixModelConfig.providers"
