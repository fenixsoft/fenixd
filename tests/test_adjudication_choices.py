"""add-human-adjudication-choices 全链路测试。

覆盖 tasks.md 7.1 五块：
1. 注册表完整性（8 类信号选项集、未注册空集、字段四件套）；
2. 告警记录 choices 写入与无字段兼容（AdminStore 归一化 / 去重不因新字段误判）；
3. 三个新裁决动词（reset_verification / force_advance / skip_review_gate）
   的前置校验拒绝 / 成功路径 / 留痕断言；
4. alert-resolve 端点闭环（成功 / 非法 choice / 重复处置 / 动作失败不假成功）；
5. 发射点逐信号断言（注册表覆盖的 signal_type 写告警必含 choices；
   build_artifact_paths_missing 断言 mergeback SIGNAL 记录携 choices）；
   另覆盖 4.2 Administrator 处置 choice_id 执行路径。
"""
import http.client
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.admin_store import AdminStore, DISPOSITION, ESCALATION, SIGNAL
from core.dashboard.data.adjudication_choices import (
    ADJUDICATION_CHOICES,
    SIGNAL_CHANNEL_SIGNAL_TYPES,
    choices_for,
    is_adjudicable,
    registered_signal_types,
)

from tests.helpers import FakeLogger

# 注册表覆盖的 8 类信号（与 proposal 信号表一致；id 集断言逐信号精确匹配）
_EXPECTED_CHOICE_IDS = {
    "impl_budget_exhausted": {"continue_auto_fix", "manual_fixed_reverify", "force_advance", "abandon"},
    "judge_rerun_cap": {"manual_fixed_reverify", "force_advance", "abandon"},
    "verify_fail_escalation": {"continue_auto_fix", "manual_fixed_reverify", "force_advance", "abandon"},
    "redispatch_loop_detected": {"continue_auto_fix", "manual_fixed_reverify", "force_advance", "abandon"},
    "spec-review-rejected": {"revise_reproposal", "force_advance", "abandon"},
    "spec-review-incomplete": {"retry_review", "skip_review_gate", "abandon"},
    "token_budget": {"ignore", "freeze_stop_loss", "raise_budget"},
    # fix-global-signal-choice-execution 1.3：桶尾追加非作用域收口 ack_self_heal
    "build_artifact_paths_missing": {"open_config", "declare_no_artifacts", "ack_self_heal"},
    # fix-env-exemption-exit-reachability 4.1：env 豁免握手 inconclusive 停车族
    # evo-fix-env-exemption-gate-conflict-… 2.1：追加场景修订重验出口
    "inconclusive_loop": {"grant_env_exemption", "revise_scenario_reverify",
                          "manual_fixed_reverify", "abandon"},
}
# 桶 0（知情/自愈类）：注册表不覆盖，告警不携 choices
_BUCKET0_SIGNAL_TYPES = ("stale_code", "transient_break_storm", "run_infra_failure", "run_cancelled")


def _write_state(proot: Path, specs: dict) -> None:
    """最小 STATE.md（同 test_dashboard_freeze 夹具形态）。"""
    lines = ["# Fenix Project State", "", "## Specs", ""]
    for name, fields in specs.items():
        lines.append(f"### {name}")
        for k, v in fields.items():
            lines.append(f"- {k}: {v}")
        lines.append("")
    (proot / ".fenix" / "STATE.md").write_text("\n".join(lines), encoding="utf-8")


_STATE_FIELDS = lambda status, error="null": {
    "status": status,
    "priority": 2,
    "created": "2026-01-01T00:00:00+00:00",
    "updated": "2026-01-02T00:00:00+00:00",
    "error": error,
    "depends_on": "null",
}


def _make_proot(tmp_path: Path) -> Path:
    proot = tmp_path / "proj-adj"
    (proot / ".fenix").mkdir(parents=True)
    _write_state(proot, {
        "spec-frozen": _STATE_FIELDS("blocked", "placeholder"),
        "spec-rejected": _STATE_FIELDS("blocked", "placeholder"),
        "spec-normal": _STATE_FIELDS("implementing"),
        "spec-done": _STATE_FIELDS("done"),
    })
    return proot


def _freeze(proot: Path, spec: str, error: str, **extra):
    """模拟 freeze_for_human 冻结形态（blocked + frozen 标记 + 站点 error 文案）。"""
    from core.state_machine import StateMachine, project_state_logger

    sm = StateMachine(proot / ".fenix" / "STATE.md", project_state_logger(proot))
    updates = {"frozen": True, "status": "blocked", "error": error}
    updates.update(extra)
    sm.update_spec(spec, updates)


def _entry(proot: Path, spec: str) -> dict:
    from core.dashboard.data import parse_state

    return parse_state(proot)[spec]


# ── 1. 注册表完整性 ──────────────────────────────────────────────────────


class TestRegistry:
    def test_covers_exactly_9_signal_types(self):
        assert set(registered_signal_types()) == set(_EXPECTED_CHOICE_IDS)
        assert len(ADJUDICATION_CHOICES) == len(_EXPECTED_CHOICE_IDS) == 9

    def test_per_signal_choice_id_sets(self):
        for sig, expected in _EXPECTED_CHOICE_IDS.items():
            got = {c["id"] for c in choices_for(sig)}
            assert got == expected, f"{sig} 选项集漂移: {got}"

    def test_choice_fields_four_piece_and_unique_ids(self):
        for sig, choices in ADJUDICATION_CHOICES.items():
            ids = [c["id"] for c in choices]
            assert len(ids) == len(set(ids)), f"{sig} 内选项 id 不唯一"
            for c in choices:
                for field in ("id", "label", "desc", "action"):
                    assert isinstance(c.get(field), str) and c[field].strip(), (
                        f"{sig}/{c.get('id')} 缺字段 {field}"
                    )

    def test_spec_scoped_declared_per_choice(self):
        """fix-global-signal-choice-execution 1.1：逐项作用域显式声明。"""
        for sig, choices in ADJUDICATION_CHOICES.items():
            for c in choices:
                assert isinstance(c.get("spec_scoped"), bool), (
                    f"{sig}/{c.get('id')} 缺 spec_scoped 显式声明"
                )
        # spec 作用域（动作语义针对具体 spec 状态机）：retry_review 等
        assert choices_for("spec-review-incomplete")[0]["spec_scoped"] is True
        assert choices_for("impl_budget_exhausted")[3]["spec_scoped"] is True  # abandon
        # 非作用域（仅确认/观察/写项目配置）：全局信号唯一可执行面
        nonscoped = {
            c["action"] for chs in ADJUDICATION_CHOICES.values() for c in chs
            if not c["spec_scoped"]
        }
        assert nonscoped == {
            "ignore", "raise_budget", "open_config",
            "declare_no_artifacts", "ack_self_heal",
        }

    def test_unregistered_returns_empty_tuple(self):
        for sig in _BUCKET0_SIGNAL_TYPES + ("unknown_type",):
            assert choices_for(sig) == ()
            assert not is_adjudicable(sig)
        assert choices_for(None) == ()
        assert choices_for("") == ()

    def test_signal_channel_only_build_artifact_paths_missing(self):
        assert SIGNAL_CHANNEL_SIGNAL_TYPES == ("build_artifact_paths_missing",)


# ── 2. 告警记录 choices 写入与无字段兼容 ─────────────────────────────────


class TestAdminStoreChoices:
    @pytest.fixture()
    def store(self, tmp_path):
        proot = tmp_path / "proj-store"
        (proot / ".fenix").mkdir(parents=True)
        return AdminStore(proot, FakeLogger())

    def test_append_with_choices_roundtrip(self, store):
        choices = list(choices_for("impl_budget_exhausted"))
        rec = store.append({
            "kind": ESCALATION, "signal_type": "impl_budget_exhausted",
            "spec": "spec-a", "severity": "critical", "choices": choices,
        })
        got = [r for r in store.read_all() if r["id"] == rec["id"]][0]
        assert got["choices"] == choices

    def test_append_illegal_choices_normalized_to_none(self, store):
        for bad in ("not-a-list", {"k": "v"}, ["str-elem"], [1, 2]):
            rec = store.append({
                "kind": ESCALATION, "signal_type": "token_budget",
                "spec": "spec-a", "severity": "warning", "choices": bad,
            })
            got = [r for r in store.read_all() if r["id"] == rec["id"]][0]
            assert got["choices"] is None, f"非法 choices {bad!r} 应归一为 None"

    def test_record_without_choices_field_compatible(self, store):
        rec = store.append({
            "kind": ESCALATION, "signal_type": "stuck",
            "spec": "spec-a", "severity": "critical",
        })
        got = [r for r in store.read_all() if r["id"] == rec["id"]][0]
        assert not got.get("choices")  # 无字段按无选项处理，不抛异常

    def test_merge_signal_dedup_ignores_choices(self, store):
        """去重只比对 (spec, signal_type, status_hash)：choices 差异不判为新状态。"""
        base = {"kind": SIGNAL, "signal_type": "stuck", "spec": "spec-a"}
        rec1, is_new1 = store.merge_signal({**base, "choices": list(choices_for("token_budget"))}, "h1")
        rec2, is_new2 = store.merge_signal({**base, "choices": None}, "h1")
        assert is_new1 is True and is_new2 is False
        assert rec1["id"] == rec2["id"]
        same = [r for r in store.read_all() if r["id"] == rec1["id"]]
        assert len(same) == 1  # 不产生重复记录

    def test_mark_signal_handled_only_matches_signal_kind(self, store):
        sig = store.append({"kind": SIGNAL, "signal_type": "stuck", "spec": "spec-a"})
        esc = store.append({"kind": ESCALATION, "signal_type": "stuck", "spec": "spec-b"})
        assert store.mark_signal_handled(sig["id"]) is True
        assert store.mark_signal_handled(sig["id"]) is False  # 幂等
        assert store.mark_signal_handled(esc["id"]) is False  # ESCALATION 不匹配
        assert store.mark_handled(esc["id"]) is True
        records = {r["id"]: r for r in store.read_all()}
        assert records[sig["id"]]["handled"] is True
        assert records[esc["id"]]["handled"] is True


# ── 3. 发射点接线（中心 + 直写两处 + 桶 0 确认） ─────────────────────────


class TestEmissionWiring:
    @pytest.fixture()
    def proot(self, tmp_path):
        proot = tmp_path / "proj-emit"
        (proot / ".fenix").mkdir(parents=True)
        return proot

    def _latest(self, proot: Path, signal_type: str) -> dict:
        recs = [r for r in AdminStore(proot, FakeLogger()).read_all()
                if r.get("signal_type") == signal_type]
        assert recs, f"未找到 signal_type={signal_type} 的告警记录"
        return recs[0]

    def test_center_wired_signals_carry_choices(self, proot):
        """桶 2 升级族全部经 family._send_human_escalation_alert 中心接线：
        注册表覆盖的 signal_type 写告警必含 choices（覆盖 2.1/2.3/2.4/2.5）。"""
        from core.pm_engine.family import FamilyGovernor

        gov = FamilyGovernor.__new__(FamilyGovernor)
        gov._pm = SimpleNamespace(project_root=proot, logger=FakeLogger())
        wired = [s for s in registered_signal_types()
                 if s not in ("token_budget", "build_artifact_paths_missing")]
        for sig in wired:
            gov._send_human_escalation_alert(
                "spec-x", sig, "critical", "d", "e", "r",
            )
            rec = self._latest(proot, sig)
            assert rec.get("choices") == list(choices_for(sig)), f"{sig} 告警未携 choices"
            assert rec["kind"] == ESCALATION

    def test_bucket0_signal_no_choices_key(self, proot):
        """桶 0 确认（2.7 后半）：非注册表信号写告警不携带 choices。"""
        from core.pm_engine.family import FamilyGovernor

        gov = FamilyGovernor.__new__(FamilyGovernor)
        gov._pm = SimpleNamespace(project_root=proot, logger=FakeLogger())
        for sig in _BUCKET0_SIGNAL_TYPES:
            gov._send_human_escalation_alert("spec-x", sig, "major", "d", "e", "r")
            rec = self._latest(proot, sig)
            assert not rec.get("choices"), f"桶 0 信号 {sig} 不应携 choices"

    def test_token_budget_alert_carries_choices(self, proot):
        """2.6：token 预算告警直写 AdminStore，携 choices；记录保持未处理进
        待办队列（item ded34cd04dc5）——born-handled 会让选项永不可裁决。"""
        from core.agent_runner.token_budget import TokenAccountant

        ta = TokenAccountant(SimpleNamespace(project_root=proot, logger=FakeLogger()))
        ta._send_token_alert("spec-x", 60_000_000, 50.0, "warning", "预算 100% 警告")
        rec = self._latest(proot, "token_budget")
        assert rec.get("choices") == list(choices_for("token_budget"))
        assert not rec.get("handled")

    def test_mergeback_signal_carries_choices(self, proot):
        """2.7 前半：build_artifact_paths_missing 写 kind=SIGNAL 记录携 choices。"""
        from core.worktree_manager.mergeback import G4MergebackMixin

        mgr = G4MergebackMixin.__new__(G4MergebackMixin)
        mgr.project_root = proot
        mgr.logger = FakeLogger()
        mgr._artifacts = SimpleNamespace(is_config_unresolved=lambda: True)
        mgr._spec_from_branch = lambda branch: "spec-x"
        mgr._maybe_signal_build_artifact_paths_missing("worktree/spec-x")
        rec = self._latest(proot, "build_artifact_paths_missing")
        assert rec["kind"] == SIGNAL
        assert rec.get("choices") == list(choices_for("build_artifact_paths_missing"))


# ── 4. 三个新裁决动词 ────────────────────────────────────────────────────


class TestResetVerification:
    def test_rejects_non_frozen_spec(self, tmp_path):
        proot = _make_proot(tmp_path)
        from core.dashboard.data import reset_verification

        r = reset_verification(proot, "spec-normal", signal_type="judge_rerun_cap")
        assert not r["ok"]
        assert "未处于冻结/blocked" in r["error"]
        assert _entry(proot, "spec-normal")["status"] == "implementing"

    def test_rejects_non_verify_chain_signal(self, tmp_path):
        proot = _make_proot(tmp_path)
        _freeze(proot, "spec-frozen", "spec-review-incomplete: 评审尝试已达上限")
        from core.dashboard.data import reset_verification

        r = reset_verification(proot, "spec-frozen", signal_type="spec-review-incomplete")
        assert not r["ok"]
        assert "不属验证链" in r["error"]
        assert _entry(proot, "spec-frozen")["status"] == "blocked"

    def test_rejects_review_rejected_freeze_by_error_text(self, tmp_path):
        proot = _make_proot(tmp_path)
        _freeze(proot, "spec-frozen", "spec-review-rejected: 方向不成立（原状态 reviewing）")
        from core.dashboard.data import reset_verification

        r = reset_verification(proot, "spec-frozen")  # 无 signal_type → error 文本判别
        assert not r["ok"]
        assert "不属验证链" in r["error"]

    def test_success_on_judge_rerun_cap_freeze(self, tmp_path):
        proot = _make_proot(tmp_path)
        vp = proot / ".fenix" / "verify-progress" / "spec-frozen"
        vp.mkdir(parents=True)
        (vp / "test_scenarios.json").write_text("{}", encoding="utf-8")
        (vp / "_scenarios_full.json").write_text("{}", encoding="utf-8")
        (vp / "tokens.json").write_text("{}", encoding="utf-8")
        _freeze(proot, "spec-frozen", "judge_rerun_cap: judge 重跑达上限（原状态 testing）",
                _judge_rerun_count=3, _judge_cap_frozen=True, _verify_fail_rounds=2)
        from core.dashboard.data import reset_verification

        r = reset_verification(proot, "spec-frozen", note="环境已修复",
                               signal_type="judge_rerun_cap")
        assert r["ok"] is True
        assert r["target_status"] == "ready"  # 无 branch → BLOCKED→READY 回实现
        entry = _entry(proot, "spec-frozen")
        assert entry["status"] == "ready"
        assert not entry.get("frozen")
        assert entry["error"] is None
        # 计数器复位按 StateMachine 读语义断言（布尔归一在生产读者侧完成；
        # dashboard parse_state 对 _ 前缀键保留原始字符串，勿用其断言真值）
        from core.state_machine import StateMachine, project_state_logger

        raw = StateMachine(proot / ".fenix" / "STATE.md",
                           project_state_logger(proot)).read_one("spec-frozen")
        assert int(raw.get("_judge_rerun_count") or 0) == 0
        assert not raw.get("_judge_cap_frozen")
        assert int(raw.get("_verify_fail_rounds") or 0) == 0
        # 场景/进度文件被删（精确 spec 名），生命周期审计侧车 tokens.json 保留
        assert not (vp / "test_scenarios.json").exists()
        assert not (vp / "_scenarios_full.json").exists()
        assert (vp / "tokens.json").exists()
        # 执行步骤明细 + note 留痕
        assert any("已删除" in s for s in r["steps"])
        assert any("计数" in s for s in r["steps"])
        assert any("裁决依据：环境已修复" in s for s in r["steps"])


class TestForceAdvance:
    def test_rejects_normal_state_spec(self, tmp_path):
        proot = _make_proot(tmp_path)
        from core.dashboard.data import force_advance

        r = force_advance(proot, "spec-normal", note="x")
        assert not r["ok"]
        assert "未处于冻结/blocked" in r["error"]
        assert _entry(proot, "spec-normal")["status"] == "implementing"

    def test_rejects_unsupported_target(self, tmp_path):
        proot = _make_proot(tmp_path)
        _freeze(proot, "spec-frozen", "impl_budget_exhausted: 预算耗尽")
        from core.dashboard.data import force_advance

        r = force_advance(proot, "spec-frozen", target_status="pushed")
        assert not r["ok"]
        assert "不支持的目标状态" in r["error"]
        assert _entry(proot, "spec-frozen")["status"] == "blocked"

    def test_advance_frozen_to_done_with_trace(self, tmp_path):
        proot = _make_proot(tmp_path)
        _freeze(proot, "spec-frozen", "impl_budget_exhausted: 预算耗尽（原状态 implementing）")
        from core.dashboard.data import force_advance

        r = force_advance(proot, "spec-frozen", note="缺口可接受")
        assert r["ok"] is True
        assert r["status"] == "done"
        entry = _entry(proot, "spec-frozen")
        assert entry["status"] == "done"
        assert not entry.get("frozen")
        assert entry["error"] is None
        # 留痕：步骤明细 + STATE 日志通道含人工豁免标记与 note 原文
        assert any("人工豁免推进" in s and "缺口可接受" in s for s in r["steps"])
        log_text = (proot / ".fenix" / "logs" / "fenixd.log").read_text(encoding="utf-8")
        assert "Transition: spec-frozen blocked → done" in log_text
        assert "人工豁免推进" in log_text and "缺口可接受" in log_text


class TestSkipReviewGate:
    def test_rejects_review_rejected_freeze(self, tmp_path):
        proot = _make_proot(tmp_path)
        _freeze(proot, "spec-rejected", "spec-review-rejected: 方向不成立（原状态 reviewing）")
        from core.dashboard.data import skip_review_gate

        r = skip_review_gate(proot, "spec-rejected", note="x")
        assert not r["ok"]
        assert "不支持跳过" in r["error"]
        assert _entry(proot, "spec-rejected")["status"] == "blocked"

    def test_rejects_non_review_freeze(self, tmp_path):
        proot = _make_proot(tmp_path)
        _freeze(proot, "spec-frozen", "judge_rerun_cap: judge 重跑达上限")
        from core.dashboard.data import skip_review_gate

        r = skip_review_gate(proot, "spec-frozen", note="x")
        assert not r["ok"]
        assert "spec-review-incomplete" in r["error"]

    def test_success_on_review_incomplete_freeze(self, tmp_path):
        proot = _make_proot(tmp_path)
        _freeze(proot, "spec-frozen", "spec-review-incomplete: 评审尝试已达上限（原状态 reviewing）",
                _review_attempts=3, reviewer_run="run-x")
        from core.dashboard.data import skip_review_gate

        r = skip_review_gate(proot, "spec-frozen", note="模型链已修复")
        assert r["ok"] is True
        assert r["status"] == "ready"
        entry = _entry(proot, "spec-frozen")
        assert entry["status"] == "ready"
        assert not entry.get("frozen")
        assert entry["error"] is None
        assert int(entry.get("_review_attempts") or 0) == 0
        assert not entry.get("reviewer_run")
        assert entry.get("reviewer_run") is None
        # 留痕：人工授权跳过评审 + note
        assert any("人工授权跳过评审" in s and "模型链已修复" in s for s in r["steps"])

    def test_success_on_reviewing_structured_frozen(self, tmp_path):
        """BUG-01 回归：结构化 frozen=True 是独立判据，reviewing+frozen 可跳过。

        SPEC 语义形态（specs/adjudication-actions「状态 reviewing + frozen」）：
        冻结起源态 reviewing 直接携结构化冻结标记时，原实现首行
        ``status != 'blocked'`` 提前返回误判未冻结，CLI/API/Web 三条消费
        通道全被拒（验证 5 场景聚合 Bug）。
        """
        proot = _make_proot(tmp_path)
        _freeze(proot, "spec-frozen", "spec-review-incomplete: 评审尝试已达上限",
                status="reviewing", _review_attempts=3, reviewer_run="run-x")
        from core.dashboard.data import skip_review_gate

        r = skip_review_gate(proot, "spec-frozen", note="模型链已修复")
        assert r["ok"] is True
        assert r["status"] == "ready"
        entry = _entry(proot, "spec-frozen")
        assert entry["status"] == "ready"
        assert not entry.get("frozen")
        assert entry["error"] is None
        assert int(entry.get("_review_attempts") or 0) == 0

    def test_reject_rejected_freeze_on_reviewing_structured_frozen(self, tmp_path):
        """BUG-01 回归：reviewing+frozen 的评审否决冻结走专属拒绝分支而非「未冻结」。"""
        proot = _make_proot(tmp_path)
        _freeze(proot, "spec-rejected", "spec-review-rejected: 方向不成立（原状态 reviewing）",
                status="reviewing")
        from core.dashboard.data import skip_review_gate

        r = skip_review_gate(proot, "spec-rejected", note="x")
        assert not r["ok"]
        assert "不支持跳过" in r["error"]
        entry = _entry(proot, "spec-rejected")
        assert entry["status"] == "reviewing"
        assert entry.get("frozen") is True


# ── 5. choice 映射执行器（含 4.2 消费路径） ──────────────────────────────


class TestExecuteAdjudicationChoice:
    def test_illegal_choice_for_registered_signal_rejected(self, tmp_path):
        proot = _make_proot(tmp_path)
        from core.dashboard.data import execute_adjudication_choice

        r = execute_adjudication_choice(proot, "spec-frozen", "force_advance",
                                        signal_type="token_budget")
        assert not r["ok"]
        assert "不在信号 'token_budget' 的选项集内" in r["error"]

    def test_force_advance_via_executor(self, tmp_path):
        proot = _make_proot(tmp_path)
        _freeze(proot, "spec-frozen", "impl_budget_exhausted: 预算耗尽")
        from core.dashboard.data import execute_adjudication_choice

        r = execute_adjudication_choice(proot, "spec-frozen", "force_advance",
                                        note="缺口可接受", signal_type="impl_budget_exhausted")
        assert r["ok"] is True
        assert r["action"] == "force_advance"
        assert _entry(proot, "spec-frozen")["status"] == "done"

    def test_ignore_noop_success(self, tmp_path):
        proot = _make_proot(tmp_path)
        from core.dashboard.data import execute_adjudication_choice

        r = execute_adjudication_choice(proot, "spec-normal", "ignore",
                                        signal_type="token_budget")
        assert r["ok"] is True
        assert _entry(proot, "spec-normal")["status"] == "implementing"

    def test_freeze_stop_loss_action_failure_not_fake_success(self, tmp_path):
        """动作失败不假成功：终态 spec 冻结止损被拒（ok=False + error）。"""
        proot = _make_proot(tmp_path)
        from core.dashboard.data import execute_adjudication_choice

        r = execute_adjudication_choice(proot, "spec-done", "freeze_stop_loss",
                                        signal_type="token_budget")
        assert r["ok"] is False
        assert r["error"]
        assert _entry(proot, "spec-done")["status"] == "done"  # 状态不变

    def test_abandon_soft_deletes(self, tmp_path):
        proot = _make_proot(tmp_path)
        _freeze(proot, "spec-frozen", "spec-review-incomplete: 评审尝试已达上限")
        from core.dashboard.data import execute_adjudication_choice

        r = execute_adjudication_choice(proot, "spec-frozen", "abandon",
                                        note="不要了", signal_type="spec-review-incomplete")
        assert r["ok"] is True
        from core.dashboard.data import parse_state

        assert "spec-frozen" not in parse_state(proot)

    def test_apply_choice_execution_admin_path(self, tmp_path):
        """4.2：Administrator 处置记录 choice_id 非空 → 同一执行路径生效。"""
        proot = _make_proot(tmp_path)
        _freeze(proot, "spec-frozen", "impl_budget_exhausted: 预算耗尽")
        from core.agent_runner.result_gate import AdminDisposition
        from core.admin_monitor import AdminMonitor

        mon = AdminMonitor.__new__(AdminMonitor)
        mon.project_root = proot
        mon.logger = FakeLogger()
        disp = AdminDisposition(run_id="r1", choice_id="force_advance",
                                actions_taken="缺口可接受的依据")
        mon._apply_choice_execution(
            {"signal_type": "impl_budget_exhausted", "spec": "spec-frozen"}, disp)
        assert _entry(proot, "spec-frozen")["status"] == "done"

    def test_apply_choice_execution_empty_choice_noop(self, tmp_path):
        """choice_id 缺省（存量处置记录）不触发任何动作。"""
        proot = _make_proot(tmp_path)
        _freeze(proot, "spec-frozen", "impl_budget_exhausted: 预算耗尽")
        from core.agent_runner.result_gate import AdminDisposition
        from core.admin_monitor import AdminMonitor

        mon = AdminMonitor.__new__(AdminMonitor)
        mon.project_root = proot
        mon.logger = FakeLogger()
        mon._apply_choice_execution(
            {"signal_type": "impl_budget_exhausted", "spec": "spec-frozen"},
            AdminDisposition(run_id="r1"))
        assert _entry(proot, "spec-frozen")["status"] == "blocked"  # 未动

    def test_apply_choice_execution_global_signal_scoped_choice_skipped(self, tmp_path):
        """fix-global-signal-choice-execution 2.1：全局信号 × spec 作用域 choice
        被跳过（not-ok + skipped），spec 状态机未被触碰——终态回写按 not-ok
        拦截，信号不回写 resolved。spec=None 与占位 'global' 两形态均覆盖。"""
        proot = _make_proot(tmp_path)
        _freeze(proot, "spec-frozen", "spec-review-incomplete: 评审尝试已达上限")
        from core.agent_runner.result_gate import AdminDisposition
        from core.admin_monitor import AdminMonitor
        from core.dashboard.data.adjudication_choices import is_global_spec

        mon = AdminMonitor.__new__(AdminMonitor)
        mon.project_root = proot
        mon.logger = FakeLogger()
        for gspec in (None, "global"):
            assert is_global_spec(gspec)
            outcome = mon._apply_choice_execution(
                {"signal_type": "spec-review-incomplete", "spec": gspec},
                AdminDisposition(run_id="r1", choice_id="retry_review"),
            )
            assert outcome is not None and outcome["ok"] is False
            assert outcome.get("skipped") is True
            assert outcome.get("action") == "retry_review"
            # 真实 spec 状态机未被触碰（retry_review 的解冻未发生）
            assert _entry(proot, "spec-frozen")["status"] == "blocked"

    def test_apply_choice_execution_global_signal_nonscoped_choice_executes(self, tmp_path):
        """fix-global-signal-choice-execution 1.3：全局信号保留非作用域收口
        ——未注册 signal_type（daemon_errors）经非 spec_scoped 全表反查放行，
        ack_self_heal 照常执行，全局信号收口不断路。"""
        proot = _make_proot(tmp_path)
        from core.agent_runner.result_gate import AdminDisposition
        from core.admin_monitor import AdminMonitor

        mon = AdminMonitor.__new__(AdminMonitor)
        mon.project_root = proot
        mon.logger = FakeLogger()
        outcome = mon._apply_choice_execution(
            {"signal_type": "daemon_errors", "spec": "global"},
            AdminDisposition(run_id="r1", choice_id="ack_self_heal"),
        )
        assert outcome["ok"] is True
        assert outcome["action"] == "ack_self_heal"


# ── 6. alert-resolve 端点闭环 ────────────────────────────────────────────


class _AdjTestServer:
    """真实 DashboardHTTPServer + JSON POST 助手（对齐 test_admin._AlertTestServer）。"""

    def __init__(self, proot: Path, tmp_path: Path):
        from core.dashboard.registry import Registry
        from core.dashboard.server import DashboardHTTPServer, find_free_port

        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787,
                  "projects": [{"name": "proj-adj", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        static_dir = Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static"
        self.port = find_free_port(30000)
        self.httpd = DashboardHTTPServer(("127.0.0.1", self.port), reg, static_dir)
        self.thread = threading.Thread(
            target=lambda: self.httpd.serve_forever(poll_interval=0.05), daemon=True)
        self.thread.start()

    def post_json(self, path: str, payload: dict):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        body = json.dumps(payload).encode("utf-8")
        try:
            conn.request("POST", path, body=body,
                         headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            return resp.status, json.loads(resp.read())
        finally:
            conn.close()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture()
def resolve_fx(tmp_path):
    proot = _make_proot(tmp_path)
    _freeze(proot, "spec-frozen", "impl_budget_exhausted: 预算耗尽（原状态 implementing）",
            _impl_run_budget_used=5)
    store = AdminStore(proot, FakeLogger())
    esc = store.append({
        "kind": ESCALATION, "signal_type": "impl_budget_exhausted",
        "spec": "spec-frozen", "severity": "critical",
        "description": "实现预算耗尽", "evidence": "n=5",
        "choices": list(choices_for("impl_budget_exhausted")),
    })
    srv = _AdjTestServer(proot, tmp_path)
    try:
        yield proot, store, srv, esc
    finally:
        srv.stop()


class TestAlertResolveEndpoint:
    def _post(self, srv, esc_id, choice_id, note="", project="proj-adj"):
        return srv.post_json("/api/alert-resolve", {
            "project": project, "alert_id": esc_id, "choice_id": choice_id,
            "note": note,
        })

    def test_full_loop_success(self, resolve_fx):
        """一次选择 = 动作执行 + 状态推进 + handled + 处置留痕。"""
        proot, store, srv, esc = resolve_fx
        status, data = self._post(srv, esc["id"], "force_advance", note="缺口可接受")
        assert status == 200
        assert data["ok"] is True
        assert data["action"] == "force_advance"
        entry = _entry(proot, "spec-frozen")
        assert entry["status"] == "done" and not entry.get("frozen")
        records = store.read_all()
        alert = [r for r in records if r["id"] == esc["id"]][0]
        assert alert["handled"] is True
        disps = [r for r in records if r.get("kind") == DISPOSITION
                 and r.get("source") == "alert-resolve"]
        assert len(disps) == 1
        assert disps[0]["choice_id"] == "force_advance"
        assert disps[0]["note"] == "缺口可接受"
        assert "冻结解除" in disps[0]["action_taken"]

    def test_illegal_choice_rejected_400_with_legal_set(self, resolve_fx):
        proot, store, srv, esc = resolve_fx
        status, data = self._post(srv, esc["id"], "nope")
        assert status == 400
        assert "合法选项" in data["error"]
        assert "force_advance" in data["error"]  # 错误说明合法选项集
        # 告警未 handled、spec 状态不变
        alert = [r for r in store.read_all() if r["id"] == esc["id"]][0]
        assert not alert.get("handled")
        assert _entry(proot, "spec-frozen")["status"] == "blocked"

    def test_cross_signal_choice_rejected(self, resolve_fx):
        """choice 不在告警 signal_type 选项集内 → 400（记录内 choices 优先校验）。"""
        proot, store, srv, esc = resolve_fx
        status, data = self._post(srv, esc["id"], "skip_review_gate")
        assert status == 400
        assert not _entry(proot, "spec-frozen").get("status") == "ready"

    def test_duplicate_resolve_conflict_409(self, resolve_fx):
        proot, store, srv, esc = resolve_fx
        status, _ = self._post(srv, esc["id"], "force_advance")
        assert status == 200
        status2, data2 = self._post(srv, esc["id"], "force_advance")
        assert status2 == 409
        disps = [r for r in store.read_all()
                 if r.get("kind") == DISPOSITION and r.get("source") == "alert-resolve"]
        assert len(disps) == 1  # 不重复执行动作

    def test_action_failure_not_marked_handled(self, tmp_path):
        """动作失败：结构化错误含已执行步骤说明，告警保持未处理。"""
        proot = _make_proot(tmp_path)
        store = AdminStore(proot, FakeLogger())
        esc = store.append({
            "kind": ESCALATION, "signal_type": "token_budget",
            "spec": "spec-done", "severity": "warning",  # 终态 spec：止损动作必败
            "description": "预算 100%", "evidence": "ratio=120%",
            "choices": list(choices_for("token_budget")),
        })
        srv = _AdjTestServer(proot, tmp_path)
        try:
            status, data = srv.post_json("/api/alert-resolve", {
                "project": "proj-adj", "alert_id": esc["id"],
                "choice_id": "freeze_stop_loss", "note": "",
            })
            assert status == 400
            assert "终态" in data["error"]
            alert = [r for r in store.read_all() if r["id"] == esc["id"]][0]
            assert not alert.get("handled")  # 不假成功
            assert _entry(proot, "spec-done")["status"] == "done"
        finally:
            srv.stop()

    def test_unknown_alert_404_and_unknown_project_404(self, resolve_fx):
        proot, store, srv, esc = resolve_fx
        status, _ = self._post(srv, "nonexistent-id", "force_advance")
        assert status == 404
        status2, _ = self._post(srv, esc["id"], "force_advance", project="nope")
        assert status2 == 404
