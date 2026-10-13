"""转人工裁决告警四段式调查叙事（upgrade-narrative-to-investigation）测试。

覆盖 tasks 1.1 / 1.2 / 2.1 / 2.2 / 3.1 / 3.2 / 4.1 / 5.1：
- 四段契约与侧车字段形态（text/model/at，at 为 UTC ISO 可解析）；含缺段
  （旧三段输出）失败走兜底
- 验证材料采集器：四产物齐备/部分缺失/非 verify 族三态；16K 总预算分段
  截断（段界保留 + 截断标记）
- facts 注入与缺省跳过
- 熔断器：3 连败跳过调用、成功复位、enabled=false 旁路、冷却到期恢复
- 超时缺省 180（配置可覆盖）与至多 2 次尝试（终态侧车 model=null）
- 三处发射点接线：告警先以机械文案立即落盘（本体零 narrative 字段），后台
  补叙经侧车承载（alert_id 取落地记录 id），且开/关叙事时结构化字段逐字段
  一致（纯增强契约）

通道经模块级注入点注入假通道，配置经 ctx 显式注入——MUST NOT 真调网关、
配置源 MUST NOT 落 HOME。后台补叙线程经 wait_pending_narrative 确定性等待。
"""

import json
import subprocess
from datetime import datetime

import pytest

import core.adjudication_narrative as adj
from core.adjudication_narrative import (
    BREAKER_SKIP_TEXT,
    DEFAULT_TIMEOUT_SECONDS,
    GENERATION_FAILED_TEXT,
    REQUIRED_SECTIONS,
    VERIFY_FAMILY_SIGNALS,
    build_narrative,
    load_narrative_sidecars,
    reset_breaker,
    reset_channel,
    schedule_narrative,
    set_channel,
    wait_pending_narrative,
    write_narrative_sidecar,
)
from core.admin_store import AdminStore
from core.agent_runner.maintenance_runs import DEFAULT_GATEWAY_MODEL

# ── 夹具助手 ────────────────────────────────────────────

GOOD_TEXT = (
    "## 发生了什么\n"
    "spec 'spec-a' 的升级闸门连续失败第 4 轮，多轮修复均被判为真实缺陷。\n\n"
    "## 调查结论\n"
    "fail_history 显示三轮均为 real-bugs 且失败场景收敛到 web-freeze（材料"
    "内有据），根因判断：实现未覆盖该场景断言。\n\n"
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
    """每例前后复位通道注入点与熔断器：测试间零串扰、收尾不留假通道。"""
    reset_channel()
    reset_breaker()
    yield
    reset_channel()
    reset_breaker()
    wait_pending_narrative(timeout=10)


class _Forbidden:
    """哨兵通道：被调用即测试失败（零调用断言用）。"""

    def __call__(self, prompt, model, timeout):
        raise AssertionError("不应发起 LLM 叙事调用")


def make_verify_artifacts(root, spec="spec-a", report_md_chars=0):
    """布四产物：verification-report.md / report.json / verdict_stability.json /
    fail_history.json（task 1.1 采集器夹具）。report_md_chars>0 时报告正文
    撑到指定长度（截断预算用例）。"""
    spec_dir = root / "spec" / "changes" / spec
    spec_dir.mkdir(parents=True, exist_ok=True)
    body = "验证报告正文片段：env 豁免握手死循环复现路径。"
    if report_md_chars:
        body = (body + "填充") * (report_md_chars // len(body + "填充") + 1)
    (spec_dir / "verification-report.md").write_text(body, encoding="utf-8")
    vp = root / ".fenix" / "verify-progress" / spec
    vp.mkdir(parents=True, exist_ok=True)
    (vp / "report.json").write_text(
        json.dumps(
            {
                "spec": spec,
                "summary": {"total": 6, "passed": 4, "failed": 1, "warnings": 1,
                            "errors": 0, "blocked_env": 0},
                "scenarios": [
                    {"scenario_id": "s1", "status": "pass"},
                    {
                        "scenario_id": "s2",
                        "status": "fail",
                        "classification": "product",
                    },
                    {
                        "scenario_id": "s3",
                        "status": "fail",
                        "classification": "test-defect",
                    },
                    {
                        "scenario_id": "s4",
                        "status": "blocked_env",
                        "classification": "",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (vp / "verdict_stability.json").write_text(
        json.dumps(
            {
                "rounds": [
                    {"status": "bug-found", "failed_ids": ["s2"], "at": "2026-10-01T00:00:00+00:00"},
                    {"status": "bug-found", "failed_ids": ["s2", "s3"], "at": "2026-10-02T00:00:00+00:00"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (vp / "fail_history.json").write_text(
        json.dumps(
            [
                {"round": 1, "cause_type": "real-bugs",
                 "failed_scenarios": ["s2", "s3"], "failure_class": "product",
                 "run_id": "r1"},
                {"round": 2, "cause_type": "real-bugs",
                 "failed_scenarios": ["s2"], "failure_class": "product",
                 "run_id": "r2"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


# ── 通道未装配：整体惰性零调用 ──────────────────────────


class TestChannelNotArmed:
    """通道未装配（生产 daemon 未注册 / 测试进程未注入）时整体惰性零调用。

    spec「测试 MUST NOT 真调网关」由结构保证：schedule_narrative 首查注入点，
    None 即零线程零侧车——既有宿主测试（未感知本模块的用例）不注入通道也
    绝不触发 claude spawn、不产生后台线程。
    """

    def test_build_narrative_inert_without_channel(self, tmp_path):
        reset_channel()  # 确保未装配
        ctx = make_ctx(tmp_path)
        assert build_narrative(ctx, make_entry()) is None
        # 惰性非失败：不产生 WARNING 噪音
        assert ctx["logger"].records == []

    def test_schedule_inert_without_channel(self, tmp_path):
        reset_channel()
        ctx = make_ctx(tmp_path)
        assert schedule_narrative("alert-1", make_entry(), ctx) is None
        assert wait_pending_narrative(timeout=5)
        assert load_narrative_sidecars(tmp_path) == {}
        assert ctx["logger"].records == []


# ── 2.1 四段契约 + 3.2 侧车字段形态 ─────────────────────


class TestFourSectionContract:
    def test_schedule_writes_sidecar_four_sections(self, tmp_path):
        calls = []

        def channel(prompt, model, timeout):
            calls.append((prompt, model, timeout))
            return GOOD_TEXT

        set_channel(channel)
        ctx = make_ctx(tmp_path, sm_entries={"spec-a": {"status": "blocked", "error": "e1"}})
        entry = make_entry()
        t = schedule_narrative("alert-1", entry, ctx)
        assert t is not None
        assert wait_pending_narrative(timeout=10)

        sidecars = load_narrative_sidecars(tmp_path)
        nar = sidecars["alert-1"]
        assert set(nar) == {"alert_id", "text", "model", "at"}
        assert nar["alert_id"] == "alert-1"
        # 四段标题齐全且顺序固定
        pos = [nar["text"].find(h) for h in REQUIRED_SECTIONS]
        assert all(p >= 0 for p in pos)
        assert pos == sorted(pos)
        # at 为 UTC ISO 可解析
        datetime.fromisoformat(nar["at"])
        # 模型回退链落到底=框架默认网关模型（add-harness-adapter-layer 4.2：
        # --model 恒显式传递，不依赖 CLI 默认档）
        assert nar["model"] == DEFAULT_GATEWAY_MODEL
        # prompt 携带告警字段、choices 快照与 STATE 条目
        prompt, _model, timeout = calls[0]
        assert _model == DEFAULT_GATEWAY_MODEL
        assert "failure_profile" in prompt
        assert "continue_auto_fix" in prompt and "manual_fixed_reverify" in prompt
        assert "blocked" in prompt
        # 缺省硬超时 180（60→180，task 3.2）
        assert timeout == DEFAULT_TIMEOUT_SECONDS == 180
        # 本体不携带 narrative（侧车承载）：entry 未被改写
        assert "narrative" not in entry

    def test_build_narrative_returns_text_and_model(self, tmp_path):
        set_channel(lambda p, m, t: GOOD_TEXT)
        ctx = make_ctx(tmp_path)
        result = build_narrative(ctx, make_entry())
        # 回退链落到底=框架默认网关模型（4.2：不再记 "default"）
        assert result == {"text": GOOD_TEXT, "model": DEFAULT_GATEWAY_MODEL}

    def test_validate_structure_four_sections(self):
        assert adj._validate_structure(GOOD_TEXT) is True
        # 缺「调查结论」段（旧三段输出）→ 失败
        three = "\n".join(
            ln for ln in GOOD_TEXT.splitlines()
            if ln.strip() != "## 调查结论"
        )
        assert "## 调查结论" not in three
        assert adj._validate_structure(three) is False
        # 顺序倒置 → 失败
        swapped = GOOD_TEXT.replace(
            "## 为什么需要你决策\n自动链已连续重试 4 轮，升级闸门计数到顶，spec 已冻结；放任自动继续只会"
            "重复烧钱。\n\n",
            "",
        ) + "\n\n## 为什么需要你决策\n补段。"
        assert adj._validate_structure(swapped) is False
        # 空/无标题 → 失败
        assert adj._validate_structure("") is False
        assert adj._validate_structure("只有一段普通文字") is False


# ── 1.2 失败兜底 fail-open（含缺段走兜底）────────────────


class TestFailOpen:
    def test_llm_timeout_falls_back(self, tmp_path):
        def channel(prompt, model, timeout):
            raise subprocess.TimeoutExpired(cmd="claude", timeout=timeout)

        set_channel(channel)
        ctx = make_ctx(tmp_path)
        entry = make_entry()
        build_narrative(ctx, entry)  # 绝不抛出
        assert "narrative" not in entry
        assert ctx["logger"].has("叙事")
        # 既有字段与基线一致（未被动过）
        assert entry["description"] == "'spec-a' 升级闸门连续失败第 4 轮，已冻结等待人工裁决"
        assert entry["evidence"] == "failure_profile=round1:real-bugs; round3:repeat"
        assert entry["choices"] == CHOICES

    def test_llm_exception_falls_back(self, tmp_path):
        def channel(prompt, model, timeout):
            raise RuntimeError("gateway 5xx")

        set_channel(channel)
        ctx = make_ctx(tmp_path)
        assert build_narrative(ctx, make_entry()) is None
        assert ctx["logger"].has("叙事生成异常")

    def test_missing_section_falls_back(self, tmp_path):
        """模型仍按旧三段输出（缺调查结论）→ 校验失败走兜底 + WARNING。"""
        three = "\n".join(
            ln for ln in GOOD_TEXT.splitlines() if ln.strip() != "## 调查结论"
        )
        set_channel(lambda p, m, t: three)
        ctx = make_ctx(tmp_path)
        assert build_narrative(ctx, make_entry()) is None
        assert ctx["logger"].has("四段结构校验失败")

    def test_empty_output_falls_back(self, tmp_path):
        set_channel(lambda p, m, t: "  \n  ")
        ctx = make_ctx(tmp_path)
        assert build_narrative(ctx, make_entry()) is None
        assert ctx["logger"].has("叙事")


# ── 1.1 验证材料采集器三态 ──────────────────────────────


class TestCollector:
    def test_verify_family_all_artifacts_injected(self, tmp_path):
        make_verify_artifacts(tmp_path)
        set_channel(lambda p, m, t: GOOD_TEXT)
        ctx = make_ctx(tmp_path)
        entry = make_entry(signal_type="judge_rerun_cap")
        t = schedule_narrative("alert-m", entry, ctx)
        assert t is not None
        assert wait_pending_narrative(timeout=10)
        # 直接走 build_narrative 捕 prompt 断言材料段内容
        seen = {}
        set_channel(lambda p, m, t: (seen.setdefault("prompt", p), GOOD_TEXT)[1])
        build_narrative(ctx, entry)
        prompt = seen["prompt"]
        assert "【验证材料】" in prompt
        assert "验证报告正文片段" in prompt  # verification-report.md 正文
        assert "classification 分布" in prompt and "product=1" in prompt
        assert "test-defect=1" in prompt and "unclassified=1" in prompt
        assert "判定轮次" in prompt and "bug-found" in prompt  # verdict_stability
        assert "失败演进" in prompt and "cause=real-bugs" in prompt  # fail_history
        assert "s2: status=fail" in prompt  # report.json 失败场景表

    def test_partial_artifacts_fail_open(self, tmp_path):
        """部分产物缺失跳过该段，不阻断生成。"""
        (tmp_path / "spec" / "changes" / "spec-a").mkdir(parents=True)
        (tmp_path / "spec" / "changes" / "spec-a" / "verification-report.md").write_text(
            "只有报告正文。", encoding="utf-8"
        )
        seen = {}
        set_channel(lambda p, m, t: (seen.setdefault("prompt", p), GOOD_TEXT)[1])
        ctx = make_ctx(tmp_path)
        build_narrative(ctx, make_entry(signal_type="judge_rerun_cap"))
        prompt = seen["prompt"]
        assert "【验证材料】" in prompt
        assert "只有报告正文" in prompt
        assert "判定轮次" not in prompt  # 缺 verdict_stability.json → 段跳过
        assert "失败演进" not in prompt

    def test_non_verify_family_no_materials(self, tmp_path):
        """非验证族信号段跳过（与升级前行为兼容）。"""
        make_verify_artifacts(tmp_path)
        seen = {}
        set_channel(lambda p, m, t: (seen.setdefault("prompt", p), GOOD_TEXT)[1])
        ctx = make_ctx(tmp_path)
        build_narrative(ctx, make_entry(signal_type="spec-review-rejected"))
        # 独占一行的【验证材料】段未注入（指令句内提及不算）
        assert "\n【验证材料】\n" not in seen["prompt"]
        assert "[验证报告正文" not in seen["prompt"]

    def test_verify_family_missing_artifacts_no_materials(self, tmp_path):
        make_verify_artifacts(tmp_path)
        seen = {}
        set_channel(lambda p, m, t: (seen.setdefault("prompt", p), GOOD_TEXT)[1])
        ctx = make_ctx(tmp_path)
        # 验证族但 spec 无产物目录
        build_narrative(ctx, make_entry(signal_type="judge_rerun_cap", spec="spec-none"))
        assert "\n【验证材料】\n" not in seen["prompt"]
        assert "[验证报告正文" not in seen["prompt"]

    def test_corrupt_artifacts_skipped(self, tmp_path):
        make_verify_artifacts(tmp_path)
        vp = tmp_path / ".fenix" / "verify-progress" / "spec-a"
        (vp / "report.json").write_text("{broken json", encoding="utf-8")
        seen = {}
        set_channel(lambda p, m, t: (seen.setdefault("prompt", p), GOOD_TEXT)[1])
        ctx = make_ctx(tmp_path)
        build_narrative(ctx, make_entry(signal_type="judge_rerun_cap"))
        assert "【验证材料】" in seen["prompt"]  # 其余段仍在
        assert "classification 分布" not in seen["prompt"]  # 损坏段跳过


# ── 1.1 16K 总预算分段截断 ──────────────────────────────


class TestContextBudget:
    def test_total_budget_respected_with_truncation_marks(self, tmp_path):
        make_verify_artifacts(tmp_path, report_md_chars=40000)
        ctx = make_ctx(tmp_path)
        materials = adj._collect_verification_materials(
            tmp_path, "spec-a", "judge_rerun_cap"
        )
        assert materials is not None
        assert len(materials) <= adj._NARRATIVE_CONTEXT_MAX_CHARS
        # 段界保留：四个段头全部在场
        for head in ("[验证报告正文", "[场景结果", "[判定轮次", "[失败演进"):
            assert head in materials
        # 截断标记标注
        assert "…（截断）" in materials

    def test_single_segment_clipped_to_section_budget(self, tmp_path):
        make_verify_artifacts(tmp_path, report_md_chars=40000)
        seg = adj._read_text_material(
            tmp_path / "spec" / "changes" / "spec-a" / "verification-report.md",
            adj._MATERIAL_SECTION_MAX_CHARS,
        )
        assert seg is not None
        assert len(seg) <= adj._MATERIAL_SECTION_MAX_CHARS
        assert seg.endswith("…（截断）")


# ── 2.2 _clip_narrative 四段均摊 ────────────────────────


class TestClipNarrative:
    def test_four_sections_clipped_with_bounds_kept(self):
        long_seg = "很长的正文。" * 500  # 远超单段预算
        text = (
            f"## 发生了什么\n{long_seg}\n\n"
            f"## 调查结论\n{long_seg}\n\n"
            f"## 为什么需要你决策\n{long_seg}\n\n"
            f"## 决策选项\n{long_seg}"
        )
        assert len(text) > adj._NARRATIVE_MAX_CHARS
        clipped = adj._clip_narrative(text)
        assert len(clipped) <= adj._NARRATIVE_MAX_CHARS
        # 四段标题全保留且顺序不倒置（结构校验仍通过）
        assert adj._validate_structure(clipped) is True
        pos = [clipped.find(h) for h in REQUIRED_SECTIONS]
        assert pos == sorted(pos)
        assert clipped.count("…（截断）") == 4

    def test_short_text_untouched(self):
        assert adj._clip_narrative(GOOD_TEXT) == GOOD_TEXT


# ── 1.2 facts 注入与缺省跳过 ────────────────────────────


class TestFacts:
    def test_facts_injected_when_present(self, tmp_path):
        seen = {}
        set_channel(lambda p, m, t: (seen.setdefault("prompt", p), GOOD_TEXT)[1])
        ctx = make_ctx(tmp_path)
        facts = {
            "judge_dispatches": [
                {"round": i, "lane": f"lane-{i}", "reason": "env 豁免握手"}
                for i in range(1, 7)
            ],
            "note": "内存台账",
        }
        build_narrative(ctx, make_entry(signal_type="judge_rerun_cap"), facts=facts)
        prompt = seen["prompt"]
        assert "【补充事实】" in prompt
        assert "judge_dispatches" in prompt
        assert "env 豁免握手" in prompt
        assert "内存台账" in prompt

    def test_facts_skipped_by_default(self, tmp_path):
        seen = {}
        set_channel(lambda p, m, t: (seen.setdefault("prompt", p), GOOD_TEXT)[1])
        ctx = make_ctx(tmp_path)
        build_narrative(ctx, make_entry())
        # 独占一行的【补充事实】段未注入（指令句内提及不算）
        assert "\n【补充事实】\n" not in seen["prompt"]

    def test_notifier_facts_param_slot(self, tmp_path):
        """_send_human_escalation_alert 的 facts 参数位透传到后台补叙 prompt。"""
        seen = {}
        set_channel(lambda p, m, t: (seen.setdefault("prompt", p), GOOD_TEXT)[1])
        engine = _pm_engine(tmp_path)
        engine._family._send_human_escalation_alert(
            spec_name="spec-a",
            signal_type="judge_rerun_cap",
            severity="major",
            description="judge 重跑超上限（6/5 轮）",
            evidence="rounds=6/5",
            recommended_action="人工裁决",
            facts={"judge_dispatches": "6 次派发去向（内存台账）"},
        )
        rec = AdminStore(tmp_path).read_all()[0]
        assert "facts" not in rec  # facts 不落告警本体（纯增强、侧车承载）
        assert wait_pending_narrative(timeout=10)
        assert "judge_dispatches" in seen["prompt"]
        assert load_narrative_sidecars(tmp_path)[rec["id"]]["text"] == GOOD_TEXT


# ── 4.1 连续失败熔断器 ──────────────────────────────────


class TestBreaker:
    def test_three_consecutive_failures_open_gate(self):
        set_channel(lambda p, m, t: None)  # 恒超时
        ctx = {
            "config": {},
            "logger": RecordingLogger(),
            "project_root": None,
            "state_machine": FakeSM(),
        }
        for _ in range(adj.BREAKER_THRESHOLD):
            assert adj._breaker_gate() is False  # 熔断前放行
            assert build_narrative(ctx, make_entry()) is None
        assert adj._breaker_gate() is True  # 3 连败 → 熔断生效

    def test_schedule_skips_and_writes_terminal_sidecar(self, tmp_path):
        calls = {"n": 0}

        def channel(prompt, model, timeout):
            calls["n"] += 1
            return None  # 恒超时

        set_channel(channel)
        ctx = make_ctx(tmp_path)
        # alert-1：2 次尝试全败 → 终态侧车（生成失败）
        assert schedule_narrative("alert-1", make_entry(), ctx) is not None
        assert wait_pending_narrative(timeout=10)
        assert calls["n"] == 2
        sc1 = load_narrative_sidecars(tmp_path)["alert-1"]
        assert sc1["text"] == GENERATION_FAILED_TEXT
        assert sc1["model"] is None
        # alert-2：第 3 次失败触发熔断 → 尝试间隙跳过 → 终态侧车（熔断）
        assert schedule_narrative("alert-2", make_entry(), ctx) is not None
        assert wait_pending_narrative(timeout=10)
        assert calls["n"] == 3  # 只再试 1 次即触发熔断
        sc2 = load_narrative_sidecars(tmp_path)["alert-2"]
        assert sc2["text"] == BREAKER_SKIP_TEXT
        assert sc2["model"] is None
        # alert-3 起：调度口直接跳过（零调用零线程）
        assert schedule_narrative("alert-3", make_entry(), ctx) is None
        assert wait_pending_narrative(timeout=5)
        assert calls["n"] == 3
        sc3 = load_narrative_sidecars(tmp_path)["alert-3"]
        assert sc3["text"] == BREAKER_SKIP_TEXT

    def test_success_resets_streak(self):
        adj._breaker_record_failure()
        adj._breaker_record_failure()
        adj._breaker_record_success()
        assert adj._breaker_gate() is False
        adj._breaker_record_failure()
        assert adj._breaker_gate() is False  # 计数已清零，未达阈值

    def test_cooldown_expiry_releases(self, monkeypatch):
        for _ in range(adj.BREAKER_THRESHOLD):
            adj._breaker_record_failure()
        assert adj._breaker_gate() is True
        # 模拟冷却到期
        monkeypatch.setattr(
            adj.time, "monotonic", lambda: adj._breaker_open_until + 1.0
        )
        assert adj._breaker_gate() is False  # 解除并恢复尝试
        assert adj._breaker_gate() is False  # 已复位（无重复解除告警）

    def test_enabled_false_bypasses_breaker(self, tmp_path):
        set_channel(_Forbidden())
        ctx = make_ctx(tmp_path, config={"admin": {"narrative_enabled": False}})
        assert schedule_narrative("alert-x", make_entry(), ctx) is None
        assert wait_pending_narrative(timeout=5)
        assert load_narrative_sidecars(tmp_path) == {}
        assert adj._breaker_gate() is False  # 整体关闭优先，熔断器旁路

    def test_bucket0_no_choices_zero_thread(self, tmp_path):
        set_channel(_Forbidden())
        ctx = make_ctx(tmp_path)
        entry = make_entry()
        entry.pop("choices")
        assert schedule_narrative("alert-y", entry, ctx) is None
        assert load_narrative_sidecars(tmp_path) == {}


# ── 3.2 超时 180 与至多 2 次尝试 ────────────────────────


class TestTimeoutAndAttempts:
    def test_default_timeout_180(self, tmp_path):
        seen = {}
        set_channel(lambda p, m, t: (seen.setdefault("timeout", t), GOOD_TEXT)[1])
        schedule_narrative("alert-t", make_entry(), make_ctx(tmp_path))
        assert wait_pending_narrative(timeout=10)
        assert seen["timeout"] == 180

    def test_config_timeout_override(self, tmp_path):
        seen = {}
        set_channel(lambda p, m, t: (seen.setdefault("timeout", t), GOOD_TEXT)[1])
        ctx = make_ctx(tmp_path, config={"admin": {"narrative_timeout_seconds": 30}})
        schedule_narrative("alert-t2", make_entry(), ctx)
        assert wait_pending_narrative(timeout=10)
        assert seen["timeout"] == 30

    def test_retry_once_then_success(self, tmp_path):
        """第 1 次失败第 2 次成功 → 补叙侧车落盘（2 次尝试内）。"""
        calls = {"n": 0}

        def channel(prompt, model, timeout):
            calls["n"] += 1
            return None if calls["n"] == 1 else GOOD_TEXT

        set_channel(channel)
        schedule_narrative("alert-r", make_entry(), make_ctx(tmp_path))
        assert wait_pending_narrative(timeout=10)
        assert calls["n"] == 2
        sc = load_narrative_sidecars(tmp_path)["alert-r"]
        assert sc["text"] == GOOD_TEXT
        assert sc["model"] == DEFAULT_GATEWAY_MODEL

    def test_two_failures_then_give_up(self, tmp_path):
        calls = {"n": 0}

        def channel(prompt, model, timeout):
            calls["n"] += 1
            return "garbage without sections"

        set_channel(channel)
        schedule_narrative("alert-f", make_entry(), make_ctx(tmp_path))
        assert wait_pending_narrative(timeout=10)
        assert calls["n"] == 2  # 至多 2 次尝试，不重试风暴
        sc = load_narrative_sidecars(tmp_path)["alert-f"]
        assert sc["text"] == GENERATION_FAILED_TEXT
        assert sc["model"] is None

    def test_handled_after_append_still_gets_narrative(self, tmp_path):
        """人工已处置（handled）后补叙照常落盘（历史完整性优先）。"""
        set_channel(lambda p, m, t: GOOD_TEXT)
        ctx = make_ctx(tmp_path)
        schedule_narrative("alert-h", make_entry(), ctx)
        AdminStore(tmp_path, ctx["logger"]).append(make_entry())  # 占位无关记录
        assert wait_pending_narrative(timeout=10)
        assert load_narrative_sidecars(tmp_path)["alert-h"]["text"] == GOOD_TEXT


# ── 3.1 汇聚写入口接线（先落盘后补叙）───────────────────

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

    def test_escalation_alert_persisted_then_sidecar(self, tmp_path):
        rec = self._emit(tmp_path / "on", enabled=True)
        assert rec["choices"], "桶 2 信号应快照 choices"
        # 本体零 narrative 字段（机械文案立即落盘，侧车承载补叙）
        assert "narrative" not in rec
        assert wait_pending_narrative(timeout=10)
        sidecars = load_narrative_sidecars(tmp_path / "on")
        assert rec["id"] in sidecars
        assert REQUIRED_SECTIONS[0] in sidecars[rec["id"]]["text"]
        assert sidecars[rec["id"]]["alert_id"] == rec["id"]

    def test_severity_denoise_branch_unaffected(self, tmp_path):
        """warning 级降噪分支原行为不变：落盘后仍写 handled。"""
        root = tmp_path / "denoise"
        rec = self._emit(root, enabled=True)
        assert rec["severity"] == "major"  # 本例 major 进待办：handled=False
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
        assert wait_pending_narrative(timeout=10)
        # handled 告警补叙照常落盘
        assert rec2["id"] in load_narrative_sidecars(tmp_path / "denoise2")

    def test_pure_enhancement_baseline_identical(self, tmp_path):
        """纯增强契约：开/关叙事时结构化字段逐字段一致。"""
        rec_on = self._emit(tmp_path / "on", enabled=True)
        rec_off = self._emit(tmp_path / "off", enabled=False)
        assert {k: rec_on.get(k) for k in _BASELINE_KEYS} == {
            k: rec_off.get(k) for k in _BASELINE_KEYS
        }
        assert "narrative" not in rec_on and "narrative" not in rec_off


# ── 3.1 旁路发射点接线 ──────────────────────────────────


class TestBypassEmissionWiring:
    def test_token_budget_carries_sidecar(self, tmp_path):
        from core.agent_runner.token_budget import TokenAccountant

        set_channel(lambda p, m, t: GOOD_TEXT)
        accountant = TokenAccountant(_pm_engine(tmp_path))
        accountant._send_token_alert("spec-a", 4_000_000, 4.0, "warning", "预算 100% 告警")
        rec = _read_first(tmp_path)
        assert rec["signal_type"] == "token_budget"
        assert rec.get("choices"), "注册表内信号应快照 choices"
        assert "narrative" not in rec
        assert wait_pending_narrative(timeout=10)
        sidecars = load_narrative_sidecars(tmp_path)
        assert rec["id"] in sidecars
        assert REQUIRED_SECTIONS[1] in sidecars[rec["id"]]["text"]

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
            snapshots[enabled] = rec
        # id/created 为逐次落盘元数据不入对账；结构化字段逐字段一致
        assert {k: snapshots[True].get(k) for k in _BASELINE_KEYS} == {
            k: snapshots[False].get(k) for k in _BASELINE_KEYS
        }

    def test_mergeback_signal_carries_sidecar(self, tmp_path):
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
        assert "narrative" not in rec
        assert wait_pending_narrative(timeout=10)
        sidecars = load_narrative_sidecars(root)
        assert rec["id"] in sidecars
        assert REQUIRED_SECTIONS[2] in sidecars[rec["id"]]["text"]

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
            snapshots[enabled] = rec
        assert {k: snapshots[True].get(k) for k in _BASELINE_KEYS} == {
            k: snapshots[False].get(k) for k in _BASELINE_KEYS
        }


# ── 侧车路径与写读删 ────────────────────────────────────


class TestSidecarIO:
    def test_write_read_atomic_shape(self, tmp_path):
        assert write_narrative_sidecar(tmp_path, "abc123", "正文", "m1") is True
        sc = load_narrative_sidecars(tmp_path)
        assert set(sc["abc123"]) == {"alert_id", "text", "model", "at"}
        assert sc["abc123"]["model"] == "m1"
        # 目录结构 .fenix/admin_alerts_narrative/<id>.json
        p = tmp_path / ".fenix" / adj.SIDECAR_DIRNAME / "abc123.json"
        assert p.is_file()

    def test_load_skips_corrupt(self, tmp_path):
        d = tmp_path / ".fenix" / adj.SIDECAR_DIRNAME
        d.mkdir(parents=True)
        (d / "bad.json").write_text("{half", encoding="utf-8")
        write_narrative_sidecar(tmp_path, "good1", "t", None)
        sc = load_narrative_sidecars(tmp_path)
        assert set(sc) == {"good1"}

    def test_delete_cascade(self, tmp_path):
        write_narrative_sidecar(tmp_path, "del1", "t", None)
        write_narrative_sidecar(tmp_path, "keep1", "t", None)
        assert adj.delete_narrative_sidecars(tmp_path, ["del1", "nothere"]) == 1
        assert set(load_narrative_sidecars(tmp_path)) == {"keep1"}
        # 缺目录/空列表零异常
        assert adj.delete_narrative_sidecars(tmp_path / "none", ["x"]) == 0
        assert adj.delete_narrative_sidecars(tmp_path, []) == 0

    def test_unsafe_alert_id_sanitized(self, tmp_path):
        # 路径穿越成分收窄为安全文件名（不落子目录、不越界）
        assert write_narrative_sidecar(tmp_path, "../../etc/passwd", "t", None) is True
        sc = load_narrative_sidecars(tmp_path)
        assert set(sc) == {"etcpasswd"}
        assert not (tmp_path / "etc").exists()
        # 空 id 拒写
        assert write_narrative_sidecar(tmp_path, "", "t", None) is False
        assert write_narrative_sidecar(tmp_path, "///", "t", None) is False


# VERIFY_FAMILY_SIGNALS 注册表显式性（task 1.1：judge/verify/verdict/改道族在册）
def test_verify_family_registry_explicit():
    for s in (
        "judge_rerun_cap",
        "inconclusive_loop",
        "verify_fail_escalation",
        "verify_env_blocked",
        "verdict_result_unreadable",
        "scenario_defect_reroute_exhausted",
    ):
        assert s in VERIFY_FAMILY_SIGNALS
    # 非验证族不入册
    assert "spec-review-rejected" not in VERIFY_FAMILY_SIGNALS
    assert "token_budget" not in VERIFY_FAMILY_SIGNALS
