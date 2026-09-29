"""转人工裁决告警三段式叙事（add-adjudication-alert-narrative）测试。

覆盖 tasks 1.2 / 2.3：
- 三段契约与 narrative 字段形态（text/model/at，at 为 UTC ISO 可解析）
- LLM 超时回退（告警照常落盘无 narrative + WARNING 留痕）
- LLM 异常回退（至多一次尝试）、三段结构校验失败回退、空输出回退
- narrative_enabled=false 零调用零延迟、桶 0（choices 空）零调用
- 模型回退链三档（admin.narrative_model → admin.agent_model → 框架默认）
- 三处发射点接线：_send_human_escalation_alert / token_budget /
  build_artifact_paths_missing 落盘告警含 narrative，且与关闭叙事时的
  基线形态逐字段一致（纯增强契约）

通道经模块级注入点注入假通道，配置经 ctx 显式注入——MUST NOT 真调网关、
配置源 MUST NOT 落 HOME。
"""

import subprocess
from datetime import datetime
from pathlib import Path

import pytest

import core.adjudication_narrative as adj
from core.adjudication_narrative import (
    REQUIRED_SECTIONS,
    attach_narrative,
    build_narrative,
    reset_channel,
    set_channel,
)
from core.admin_store import AdminStore

# ── 夹具助手 ────────────────────────────────────────────

GOOD_TEXT = (
    "## 发生了什么\n"
    "spec 'spec-a' 的升级闸门连续失败第 4 轮，多轮修复均被判为真实缺陷。\n\n"
    "## 为什么需要你决策\n"
    "自动链已连续重试 4 轮，升级闸门计数到顶，spec 已冻结；放任自动继续只会"
    "重复烧钱。\n\n"
    "## 决策选项\n"
    "**continue_auto_fix（继续自动修复）**：解冻重置预算继续修（建议倾向仅供参考，"
    "最终由你决定）。\n\n"
    "**manual_fixed_reverify（人工已修复·重置验证重跑）**：你已手工修复后走重验"
    "（建议倾向仅供参考，最终由你决定）。"
)

CHOICES = [
    {
        "id": "continue_auto_fix",
        "label": "继续自动修复",
        "desc": "解冻并重置实现预算计数，继续自动修复",
        "action": "continue_auto_fix",
    },
    {
        "id": "manual_fixed_reverify",
        "label": "人工已修复·重置验证重跑",
        "desc": "人工已修复问题：清场景与验证计数器后重置验证重跑",
        "action": "reset_verification",
    },
]


class RecordingLogger:
    """记录型 logger（断言 WARNING 留痕用）。"""

    def __init__(self):
        self.records = []

    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        self.records.append(("warning", a[1] if len(a) > 1 else ""))

    def error(self, *a, **k):
        self.records.append(("error", a[1] if len(a) > 1 else ""))

    def has(self, text):
        return any(text in m for _lvl, m in self.records)


class FakeSM:
    """STATE 读取器假件（read_one 口径同 StateMachine）。"""

    def __init__(self, entries=None):
        self._entries = entries or {}

    def read_one(self, spec):
        return self._entries.get(spec)


def make_ctx(tmp_path, config=None, sm_entries=None):
    """显式 ctx（dict 形态）：config 走内存 dict——配置源不落 HOME。"""
    return {
        "config": config if config is not None else {},
        "logger": RecordingLogger(),
        "project_root": tmp_path,
        "state_machine": FakeSM(sm_entries),
    }


def make_entry(**over):
    entry = {
        "kind": "escalation",
        "signal_type": "verify_fail_escalation",
        "spec": "spec-a",
        "severity": "major",
        "description": "'spec-a' 升级闸门连续失败第 4 轮，已冻结等待人工裁决",
        "evidence": "failure_profile=round1:real-bugs; round3:repeat",
        "recommended_action": "人工裁决后选择处置",
        "choices": list(CHOICES),
    }
    entry.update(over)
    return entry


@pytest.fixture(autouse=True)
def _channel_cleanup():
    """每例前后复位通道注入点：测试间零串扰、收尾不留假通道。"""
    reset_channel()
    yield
    reset_channel()


class _Forbidden:
    """哨兵通道：被调用即测试失败（零调用断言用）。"""

    def __call__(self, prompt, model, timeout):
        raise AssertionError("不应发起 LLM 叙事调用")


class TestChannelNotArmed:
    """通道未装配（生产 daemon 未注册 / 测试进程未注入）时整体惰性零调用。

    spec「测试 MUST NOT 真调网关」由结构保证：build_narrative 首查注入点，
    None 即静默返回——既有宿主测试（test_alert_lifecycle 等未感知本模块的
    用例）不注入通道也绝不触发 claude spawn。
    """

    def test_build_narrative_inert_without_channel(self, tmp_path):
        reset_channel()  # 确保未装配
        ctx = make_ctx(tmp_path)
        assert build_narrative(ctx, make_entry()) is None
        # 惰性非失败：不产生 WARNING 噪音
        assert ctx["logger"].records == []

    def test_attach_inert_without_channel(self, tmp_path):
        reset_channel()
        ctx = make_ctx(tmp_path)
        entry = make_entry()
        attach_narrative(entry, ctx)
        assert "narrative" not in entry
        assert ctx["logger"].records == []


# ── 1.2 三段契约与字段形态 ──────────────────────────────


class TestNarrativeContract:
    def test_attach_writes_three_section_field(self, tmp_path):
        calls = []

        def channel(prompt, model, timeout):
            calls.append((prompt, model, timeout))
            return GOOD_TEXT

        set_channel(channel)
        ctx = make_ctx(tmp_path, sm_entries={"spec-a": {"status": "blocked", "error": "e1"}})
        entry = make_entry()
        attach_narrative(entry, ctx)

        nar = entry["narrative"]
        assert set(nar) == {"text", "model", "at"}
        # 三段标题齐全且顺序固定
        pos = [nar["text"].find(h) for h in REQUIRED_SECTIONS]
        assert all(p >= 0 for p in pos)
        assert pos == sorted(pos)
        # at 为 UTC ISO 可解析
        datetime.fromisoformat(nar["at"])
        # 模型回退链落到底=框架默认 → 记 "default"
        assert nar["model"] == "default"
        # prompt 携带告警字段、choices 快照与 STATE 条目
        prompt, _model, timeout = calls[0]
        assert "failure_profile" in prompt
        assert "continue_auto_fix" in prompt and "manual_fixed_reverify" in prompt
        assert "blocked" in prompt
        # 缺省硬超时 60
        assert timeout == 60

    def test_timeout_config_passed_through(self, tmp_path):
        seen = {}

        def channel(prompt, model, timeout):
            seen["timeout"] = timeout
            return GOOD_TEXT

        set_channel(channel)
        ctx = make_ctx(tmp_path, config={"admin": {"narrative_timeout_seconds": 30}})
        entry = make_entry()
        attach_narrative(entry, ctx)
        assert entry["narrative"]["text"]
        assert seen["timeout"] == 30

    def test_build_narrative_returns_text_and_model(self, tmp_path):
        set_channel(lambda p, m, t: GOOD_TEXT)
        ctx = make_ctx(tmp_path)
        result = build_narrative(ctx, make_entry())
        assert result == {"text": GOOD_TEXT, "model": "default"}


# ── 1.2 失败兜底 fail-open ──────────────────────────────


class TestFailOpen:
    def test_llm_timeout_falls_back(self, tmp_path):
        def channel(prompt, model, timeout):
            raise subprocess.TimeoutExpired(cmd="claude", timeout=timeout)

        set_channel(channel)
        ctx = make_ctx(tmp_path)
        entry = make_entry()
        attach_narrative(entry, ctx)  # 绝不抛出
        assert "narrative" not in entry
        assert ctx["logger"].has("叙事")
        # 既有字段与基线一致（未被动过）
        assert entry["description"] == "'spec-a' 升级闸门连续失败第 4 轮，已冻结等待人工裁决"
        assert entry["evidence"] == "failure_profile=round1:real-bugs; round3:repeat"
        assert entry["choices"] == CHOICES

    def test_llm_exception_falls_back_single_attempt(self, tmp_path):
        calls = {"n": 0}

        def channel(prompt, model, timeout):
            calls["n"] += 1
            raise RuntimeError("gateway 5xx")

        set_channel(channel)
        ctx = make_ctx(tmp_path)
        entry = make_entry()
        attach_narrative(entry, ctx)
        assert "narrative" not in entry
        assert calls["n"] == 1  # 至多一次尝试
        assert ctx["logger"].has("叙事生成异常")

    def test_structure_validation_failure_falls_back(self, tmp_path):
        set_channel(lambda p, m, t: "只有一段普通文字，没有固定三段标题")
        ctx = make_ctx(tmp_path)
        entry = make_entry()
        attach_narrative(entry, ctx)
        assert "narrative" not in entry
        assert ctx["logger"].has("三段结构校验失败")

    def test_empty_output_falls_back(self, tmp_path):
        set_channel(lambda p, m, t: "  \n  ")
        ctx = make_ctx(tmp_path)
        entry = make_entry()
        attach_narrative(entry, ctx)
        assert "narrative" not in entry
        assert ctx["logger"].has("叙事")


# ── 1.2 开关与桶 0 ──────────────────────────────────────


class TestSwitchAndBucket0:
    def test_disabled_zero_calls(self, tmp_path):
        set_channel(_Forbidden())
        ctx = make_ctx(tmp_path, config={"admin": {"narrative_enabled": False}})
        entry = make_entry()
        attach_narrative(entry, ctx)
        assert "narrative" not in entry
        # 关闭时行为退化为现状：结构化字段零扰动
        assert entry["choices"] == CHOICES
        assert entry["recommended_action"] == "人工裁决后选择处置"

    def test_bucket0_no_choices_zero_calls(self, tmp_path):
        set_channel(_Forbidden())
        ctx = make_ctx(tmp_path)
        entry = make_entry()
        entry.pop("choices")  # 桶 0（choices_for 返回空集不写该字段）
        attach_narrative(entry, ctx)
        assert "narrative" not in entry


# ── 1.2 模型回退链三档 ──────────────────────────────────


class TestModelFallbackChain:
    def _run(self, tmp_path, admin):
        seen = {}

        def channel(prompt, model, timeout):
            seen["model"] = model
            return GOOD_TEXT

        set_channel(channel)
        ctx = make_ctx(tmp_path, config={"admin": admin})
        entry = make_entry()
        attach_narrative(entry, ctx)
        return seen["model"], entry["narrative"]["model"]

    def test_narrative_model_first(self, tmp_path):
        resolved, recorded = self._run(
            tmp_path, {"narrative_model": "m-nar", "agent_model": "m-agent"}
        )
        assert resolved == "m-nar"
        assert recorded == "m-nar"

    def test_agent_model_second(self, tmp_path):
        resolved, recorded = self._run(tmp_path, {"narrative_model": "", "agent_model": "m-agent"})
        assert resolved == "m-agent"
        assert recorded == "m-agent"

    def test_framework_default_third(self, tmp_path):
        resolved, recorded = self._run(tmp_path, {})
        assert resolved is None  # 通道不传 --model → CLI/网关默认
        assert recorded == "default"


# ── 2.1/2.3 汇聚写入口接线 ──────────────────────────────

# 纯增强契约对账字段（created/id 等落盘元数据不入对账）
_BASELINE_KEYS = (
    "kind",
    "signal_type",
    "spec",
    "severity",
    "description",
    "evidence",
    "recommended_action",
    "trigger",
    "choices",
)


def _pm_engine(tmp_path, config=None):
    """最小 PMEngine（test_alert_lifecycle 同款 __new__ 姿势）。"""
    from core.pm_engine import PMEngine

    engine = PMEngine.__new__(PMEngine)
    engine.project_root = tmp_path
    engine.logger = RecordingLogger()
    engine.config = config if config is not None else {}
    engine.state_machine = FakeSM()
    return engine


def _read_first(root):
    return AdminStore(root, RecordingLogger()).read_all()[0]


class TestEscalationEntryWiring:
    def _emit(self, root, enabled):
        if enabled:
            set_channel(lambda p, m, t: GOOD_TEXT)
        else:
            set_channel(_Forbidden())
        engine = _pm_engine(root, config={"admin": {"narrative_enabled": enabled}})
        engine._family._send_human_escalation_alert(
            spec_name="spec-a",
            signal_type="verify_fail_escalation",
            severity="major",
            description="验证连续失败 3 轮，已冻结等待人工裁决",
            evidence="failure_profile=round1:real-bugs",
            recommended_action="人工裁决后选择处置",
        )
        return _read_first(root)

    def test_escalation_alert_carries_narrative(self, tmp_path):
        rec = self._emit(tmp_path / "on", enabled=True)
        assert rec["choices"], "桶 2 信号应快照 choices"
        assert "narrative" in rec
        assert REQUIRED_SECTIONS[0] in rec["narrative"]["text"]
        assert rec["narrative"]["at"]

    def test_severity_denoise_branch_unaffected(self, tmp_path):
        """warning 级降噪分支原行为不变：叙事后仍写 handled。"""
        root = tmp_path / "denoise"
        rec = self._emit(root, enabled=True)
        assert rec["severity"] == "major"  # 本例 major 进待办：handled=False
        # warning/minor 写入即 mark_handled 的既有分支在叙事存在时同样收口
        set_channel(lambda p, m, t: GOOD_TEXT)
        engine = _pm_engine(tmp_path / "denoise2")
        engine._family._send_human_escalation_alert(
            spec_name="spec-b",
            signal_type="verify_fail_escalation",
            severity="warning",
            description="d",
            evidence="e",
            recommended_action="r",
        )
        rec2 = _read_first(tmp_path / "denoise2")
        assert rec2["handled"] is True
        assert "narrative" in rec2

    def test_pure_enhancement_baseline_identical(self, tmp_path):
        """纯增强契约：开/关叙事时结构化字段逐字段一致。"""
        rec_on = self._emit(tmp_path / "on", enabled=True)
        rec_off = self._emit(tmp_path / "off", enabled=False)
        assert {k: rec_on.get(k) for k in _BASELINE_KEYS} == {
            k: rec_off.get(k) for k in _BASELINE_KEYS
        }
        assert "narrative" in rec_on and "narrative" not in rec_off


# ── 2.2/2.3 旁路发射点接线 ──────────────────────────────


class TestBypassEmissionWiring:
    def test_token_budget_carries_narrative(self, tmp_path):
        from core.agent_runner.token_budget import TokenAccountant

        set_channel(lambda p, m, t: GOOD_TEXT)
        accountant = TokenAccountant(_pm_engine(tmp_path))
        accountant._send_token_alert("spec-a", 4_000_000, 4.0, "warning", "预算 100% 告警")
        rec = _read_first(tmp_path)
        assert rec["signal_type"] == "token_budget"
        assert rec.get("choices"), "注册表内信号应快照 choices"
        assert "narrative" in rec
        assert REQUIRED_SECTIONS[1] in rec["narrative"]["text"]

    def test_token_budget_baseline_identical(self, tmp_path):
        from core.agent_runner.token_budget import TokenAccountant

        snapshots = {}
        for enabled in (True, False):
            root = tmp_path / (f"on{enabled}" if enabled else "off")
            if enabled:
                set_channel(lambda p, m, t: GOOD_TEXT)
            else:
                set_channel(_Forbidden())
            accountant = TokenAccountant(
                _pm_engine(root, config={"admin": {"narrative_enabled": enabled}})
            )
            accountant._send_token_alert("spec-a", 4_000_000, 4.0, "warning", "预算 100% 告警")
            rec = _read_first(root)
            rec.pop("narrative", None)
            snapshots[enabled] = rec
        # id/created 为逐次落盘元数据不入对账；结构化字段逐字段一致
        assert {k: snapshots[True].get(k) for k in _BASELINE_KEYS} == {
            k: snapshots[False].get(k) for k in _BASELINE_KEYS
        }

    def test_mergeback_signal_carries_narrative(self, tmp_path):
        from core.worktree_manager import WorktreeManager
        from test_worktree_merge_guard import init_repo

        root = tmp_path / "repo"
        init_repo(root)
        base = root / ".claude" / "worktrees"
        base.mkdir(parents=True, exist_ok=True)
        wm = WorktreeManager(base, root, RecordingLogger())
        set_channel(lambda p, m, t: GOOD_TEXT)
        wm._maybe_signal_build_artifact_paths_missing("fenix/impl-spec-a")
        rec = _read_first(root)
        assert rec["signal_type"] == "build_artifact_paths_missing"
        assert rec.get("choices"), "注册表内信号应快照 choices"
        assert "narrative" in rec
        assert REQUIRED_SECTIONS[2] in rec["narrative"]["text"]

    def test_mergeback_signal_baseline_identical(self, tmp_path):
        from core.worktree_manager import WorktreeManager
        from test_worktree_merge_guard import init_repo

        snapshots = {}
        for enabled in (True, False):
            # 同名 repo 放不同父目录：description/evidence 内嵌项目名（root.name），
            # 基线对账要求两侧字面一致
            root = tmp_path / ("on" if enabled else "off") / "repo"
            init_repo(root)
            base = root / ".claude" / "worktrees"
            base.mkdir(parents=True, exist_ok=True)
            wm = WorktreeManager(base, root, RecordingLogger())
            # WorktreeManager 无 config 属性（旁路宿主）；显式挂上走 ctx 自带
            # config 路径（config.template 缺文件场景由 _resolve_admin_config
            # fail-open 兜底，在模块单测已覆盖）
            wm.config = {"admin": {"narrative_enabled": enabled}}
            if enabled:
                set_channel(lambda p, m, t: GOOD_TEXT)
            else:
                set_channel(_Forbidden())
            wm._maybe_signal_build_artifact_paths_missing("fenix/impl-spec-a")
            rec = _read_first(root)
            rec.pop("narrative", None)
            snapshots[enabled] = rec
        assert {k: snapshots[True].get(k) for k in _BASELINE_KEYS} == {
            k: snapshots[False].get(k) for k in _BASELINE_KEYS
        }
