"""evo-add-impl-run-budget-sizing — impl run 轮数预算 sizing 与守卫 单测。

覆盖（tasks 4.1 / 4.2）：
- 4.1 ``get_turn_budget_sizing_config`` 归一化：非法类型 / 越界逐项回退缺省
  （风格对齐 ``get_scale_precheck_config``，不抛异常）；
  ``suggested_turn_cap_for_scale`` 边界：scale 等于阈值不抬（严格大于语义）、
  阈值+1 抬、suggested 小于 base 时取 base（只抬不压）、disabled / 非法输入
  恒返回 base。STATE ``impl_turn_cap_override`` 的优先序见装配级
  TestImplTurnBudgetAssembly（override 优先于规模推算）。
- 4.2 装配级（仿 tests/test_turn_limit_lifecycle 既有装置：``__new__`` 绕过
  ``__init__`` 的最小实例态 + fake Popen 驱动真实 ``_run_claude`` 轮询环，
  不启动真实 daemon/子进程）：
  - 启动 sizing：大规模 spec 生效上限为 suggested_turn_cap、小规模等于
    base、override 优先、tasks.md/规模解析失败回退 base 不阻断派发；
  - ``_turn_limit_action``：extend 与 kill 两分支 evidence 均含
    ``remaining_tasks=<n|unavailable>``、簿记占比超阈只注记不改判（WARNING
    在场）；turn_extension 事件落盘含 ``remaining_tasks`` 字段（run_metrics
    同键断言）；
  - kill_early 末位扩容拆停守卫：关闭（含缺省）时同输入同输出逐位一致、
    开启且全条件满足时提前 kill（evidence 含 early-split 与
    remaining_tasks）、进度健康仍 extend、剩余任务数低于阈值不判、评审/
    裁决车道 agent_type 不触发守卫。
"""

import io
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from core.agent_runner.runner import (
    TURN_EXTENSION_MAX,
    TURN_EXTENSION_STEP_FRACTION,
)
from core.fast_track_result import (
    get_turn_budget_sizing_config,
    suggested_turn_cap_for_scale,
)
from tests.helpers import FakeLogger, make_runner


# ── 共用小装置（自足，不跨测试文件 import） ───────────────────────────


def _seed_tasks_md(proot: Path, spec: str, total: int,
                   checked: tuple = ()) -> Path:
    """seed ``<root>/spec/changes/<spec>/tasks.md``（数字任务勾选态可控）。"""
    spec_dir = proot / "spec" / "changes" / spec
    spec_dir.mkdir(parents=True, exist_ok=True)
    lines = [f"# {spec}", "", "## Tasks", ""]
    checked = set(checked)
    for i in range(1, total + 1):
        tid = f"1.{i}"
        mark = "x" if tid in checked else " "
        lines.append(f"- [{mark}] {tid} 任务 {i}")
    (spec_dir / "tasks.md").write_text("\n".join(lines) + "\n",
                                       encoding="utf-8")
    return spec_dir / "tasks.md"


def _seed_state(proot: Path, spec: str, **fields):
    """seed STATE.md per-spec 条目（impl_turn_cap_override 覆写键等）。"""
    from core.state_machine import StateMachine
    (proot / ".fenix").mkdir(parents=True, exist_ok=True)
    sm = StateMachine(proot / ".fenix" / "STATE.md", FakeLogger())
    sm.add_spec(spec, {"priority": 5})
    if fields:
        sm.update_spec(spec, fields)
    return sm


def make_sizing_runner(proot: Path, config: dict | None = None,
                       state_machine=None):
    runner = make_runner(
        proot, config or {"agents": {"run_timeout_seconds": 3600}})
    runner.state_machine = state_machine
    return runner


def _evt(etype: str, ts: float | None) -> dict:
    d: dict = {"type": etype}
    if ts is not None:
        d["timestamp"] = ts
    return d


def _now_evt(etype: str) -> dict:
    return _evt(etype, time.time())


def _now_tool_result_evt() -> dict:
    """真实 stream-json 形态的流量事件（user 包裹 tool_result block）。"""
    return {
        "type": "user",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message": {"content": [
            {"type": "tool_result", "tool_use_id": "tu_0",
             "content": "result-0"},
        ]},
    }


class _BurstFakeProc:
    """Popen 替身：stdout 一次性产出全部流事件；kill 前 poll() 恒 None。"""

    def __init__(self, events: list, killed_rc: int = -9):
        self._events = [l for l in events if l is not None]
        self._killed = False
        self._killed_rc = killed_rc
        self.pid = 4242
        self.returncode = None

    @property
    def stdout(self):
        return io.StringIO(
            "".join(json.dumps(e, ensure_ascii=False) + "\n"
                    for e in self._events))

    @property
    def stderr(self):
        return io.StringIO("")

    def poll(self):
        return self._killed_rc if self._killed else None

    def wait(self, timeout=None):
        return self._killed_rc if self._killed else None

    def terminate(self):
        self._killed = True

    def kill(self):
        self._killed = True


def _patch_popen(monkeypatch, proc):
    import subprocess as real_subprocess
    import core.agent_runner.runner as rmod
    ns = SimpleNamespace(
        Popen=lambda *a, **k: proc,
        PIPE=real_subprocess.PIPE,
        TimeoutExpired=real_subprocess.TimeoutExpired,
        SubprocessError=real_subprocess.SubprocessError,
        run=real_subprocess.run,
    )
    monkeypatch.setattr(rmod, "subprocess", ns)
    return ns


def _run_file_lines(proot: Path, run_id: str) -> list:
    run_file = proot / ".fenix" / "runs" / f"{run_id}.jsonl"
    try:
        return [ln for ln in run_file.read_text(encoding="utf-8").splitlines()
                if ln.strip()]
    except OSError:
        return []


def _write_run_file(proot: Path, run_id: str, events: list) -> Path:
    run_file = proot / ".fenix" / "runs" / f"{run_id}.jsonl"
    run_file.parent.mkdir(parents=True, exist_ok=True)
    with run_file.open("a", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return run_file


class _RecordingLogger(FakeLogger):
    """记录 warning 消息的 logger（簿记占比告警在场断言）。"""

    def __init__(self):
        self.warnings: list = []

    def warning(self, *a, **k):
        self.warnings.append(a[1] if a else "")


# ── 4.1 归一化 ─────────────────────────────────────────────────────────

_SIZE_DEFAULTS = {
    "enabled": True,
    "full_scale_threshold": 45,
    "suggested_turn_cap": 800,
    "bookkeeping_share_threshold": 0.5,
    "kill_early": {
        "enabled": False,
        "remaining_tasks_threshold": 10,
        "progress_floor": 0.1,
    },
}


class TestTurnBudgetSizingConfig:
    """``get_turn_budget_sizing_config`` 归一化（tasks 4.1）。"""

    def test_empty_config_returns_all_defaults(self):
        assert get_turn_budget_sizing_config({}) == _SIZE_DEFAULTS

    def test_none_config_returns_all_defaults(self):
        # config 非 dict 时与 scale_precheck 同风格：不抛异常、全缺省
        assert get_turn_budget_sizing_config(None) == _SIZE_DEFAULTS

    def test_non_dict_agents_section_returns_all_defaults(self):
        assert get_turn_budget_sizing_config(
            {"agents": "oops"}) == _SIZE_DEFAULTS

    def test_non_dict_sizing_section_returns_all_defaults(self):
        assert get_turn_budget_sizing_config(
            {"agents": {"turn_budget_sizing": "on"}}) == _SIZE_DEFAULTS

    def test_invalid_values_fallback_per_key(self):
        """非法类型 / 越界逐项回退缺省（其余合法键不受牵连）。"""
        cfg = get_turn_budget_sizing_config({"agents": {"turn_budget_sizing": {
            "enabled": "yes",                    # 非布尔 → True
            "full_scale_threshold": "45",        # 非整数 → 45
            "suggested_turn_cap": True,          # bool 不算 int → 800
            "bookkeeping_share_threshold": 1.5,  # 越界 (>1) → 0.5
            "kill_early": {
                "enabled": 1,                    # 非布尔 → False
                "remaining_tasks_threshold": 0,  # 越界 (<1) → 10
                "progress_floor": -0.5,          # 越界 (<0) → 0.1
            },
        }}})
        assert cfg == _SIZE_DEFAULTS

    def test_int_keys_bool_and_float_and_bounds_rejected(self):
        cfg = get_turn_budget_sizing_config({"agents": {"turn_budget_sizing": {
            "full_scale_threshold": 0,        # <1 → 缺省
            "suggested_turn_cap": 10001,      # >10000 → 缺省
        }}})
        assert cfg["full_scale_threshold"] == 45
        assert cfg["suggested_turn_cap"] == 800

    def test_ratio_boundaries_and_float_coercion(self):
        cfg = get_turn_budget_sizing_config({"agents": {"turn_budget_sizing": {
            "bookkeeping_share_threshold": 0,      # 下界合法 → 0.0
            "kill_early": {"progress_floor": 1},   # 上界合法 → 1.0
        }}})
        assert cfg["bookkeeping_share_threshold"] == 0.0
        assert cfg["kill_early"]["progress_floor"] == 1.0
        assert isinstance(cfg["bookkeeping_share_threshold"], float)

    def test_valid_values_pass_through(self):
        cfg = get_turn_budget_sizing_config({"agents": {"turn_budget_sizing": {
            "enabled": False,
            "full_scale_threshold": 60,
            "suggested_turn_cap": 900,
            "bookkeeping_share_threshold": 0.7,
            "kill_early": {
                "enabled": True,
                "remaining_tasks_threshold": 25,
                "progress_floor": 0.25,
            },
        }}})
        assert cfg == {
            "enabled": False,
            "full_scale_threshold": 60,
            "suggested_turn_cap": 900,
            "bookkeeping_share_threshold": 0.7,
            "kill_early": {
                "enabled": True,
                "remaining_tasks_threshold": 25,
                "progress_floor": 0.25,
            },
        }

    def test_non_dict_kill_early_section_defaults(self):
        """kill_early 段非 dict → 整段按缺省（enabled=False），不抛异常。"""
        cfg = get_turn_budget_sizing_config(
            {"agents": {"turn_budget_sizing": {"kill_early": True}}})
        assert cfg["kill_early"] == _SIZE_DEFAULTS["kill_early"]


class TestSuggestedTurnCapForScale:
    """``suggested_turn_cap_for_scale`` 边界（tasks 4.1）。"""

    def _cfg(self, **overrides):
        section = {"agents": {"turn_budget_sizing": dict(overrides)}}
        return get_turn_budget_sizing_config(section)

    def test_scale_equal_threshold_no_lift(self):
        """scale 等于阈值不抬（严格大于语义，与 budget_tier_for_scale 同源）。"""
        assert suggested_turn_cap_for_scale(
            300, 45, self._cfg()) == 300

    def test_scale_above_threshold_lifts(self):
        """阈值+1 即抬到 suggested_turn_cap。"""
        assert suggested_turn_cap_for_scale(
            300, 46, self._cfg()) == 800

    def test_suggested_below_base_takes_base(self):
        """suggested 小于 base 时取 base（推算只抬不压）。"""
        cfg = self._cfg(suggested_turn_cap=100)
        assert suggested_turn_cap_for_scale(300, 100, cfg) == 300

    def test_disabled_returns_base(self):
        cfg = self._cfg(enabled=False)
        assert suggested_turn_cap_for_scale(300, 1000, cfg) == 300

    def test_non_int_scale_rejected(self):
        for bad in ("50", True, None, 50.0):
            assert suggested_turn_cap_for_scale(300, bad, self._cfg()) == 300

    def test_non_dict_cfg_treated_as_defaults(self):
        # 非 dict 容错归一为空 dict → 按缺省启用语义（enabled 缺省 True）；
        # 契约是调用方先归一化，此处锁容错路径的确定性
        assert suggested_turn_cap_for_scale(300, 100, None) == 800
        assert suggested_turn_cap_for_scale(300, 100, {}) == 800


# ── 4.2 装配级：启动 sizing ────────────────────────────────────────────


class TestImplTurnBudgetAssembly:
    """实现车道启动点轮数上限 sizing（1.2 装配行为，tasks 4.2）。"""

    def test_large_scale_spec_gets_suggested_cap(self, tmp_path):
        """大规模 spec（scale > full_scale_threshold）生效上限为
        suggested_turn_cap（缺省 800）。"""
        proot = tmp_path
        _seed_tasks_md(proot, "big", total=50)  # scale = 50 > 45
        runner = make_sizing_runner(
            proot, {"agents": {"max_turns": 300, "run_timeout_seconds": 3600}})
        effective, snap = runner._impl_turn_budget("big", "implementer")
        assert effective == 800
        assert snap == {
            "checked_ids": frozenset(),
            "unchecked": 50,
        }

    def test_small_scale_spec_keeps_base(self, tmp_path):
        """小规模 spec（scale <= 阈值）维持 base。"""
        proot = tmp_path
        _seed_tasks_md(proot, "small", total=2)  # scale = 2
        runner = make_sizing_runner(
            proot, {"agents": {"max_turns": 300, "run_timeout_seconds": 3600}})
        effective, _ = runner._impl_turn_budget("small", "implementer")
        assert effective == 300

    def test_state_override_beats_scale_estimate(self, tmp_path):
        """STATE ``impl_turn_cap_override`` 优先于规模推算（生效序 D3）。"""
        proot = tmp_path
        _seed_tasks_md(proot, "big", total=50)  # 推算会抬到 800
        sm = _seed_state(proot, "big", impl_turn_cap_override=1200)
        runner = make_sizing_runner(
            proot, {"agents": {"max_turns": 300, "run_timeout_seconds": 3600}},
            state_machine=sm)
        effective, _ = runner._impl_turn_budget("big", "implementer")
        assert effective == 1200

    def test_tasks_md_parse_failure_falls_back_to_base(self, monkeypatch,
                                                       tmp_path):
        """tasks.md/规模解析异常 → WARNING 回退 base，不阻断派发。"""
        import core.fast_track_result as ftr

        proot = tmp_path
        _seed_tasks_md(proot, "big", total=50)

        def _boom(spec_dir, logger=None):
            raise RuntimeError("tasks.md unreadable")

        monkeypatch.setattr(ftr, "estimate_spec_scale", _boom)
        logger = _RecordingLogger()
        runner = make_sizing_runner(
            proot, {"agents": {"max_turns": 300, "run_timeout_seconds": 3600}})
        runner.logger = logger
        effective, _ = runner._impl_turn_budget("big", "implementer")
        assert effective == 300
        assert any("回退 base" in w for w in logger.warnings)

    def test_missing_tasks_md_does_not_block_dispatch(self, tmp_path):
        """tasks.md 缺失 → 规模分低档、生效上限维持 base，不抛异常。"""
        proot = tmp_path  # 无 spec/changes/<spec>/tasks.md
        runner = make_sizing_runner(
            proot, {"agents": {"max_turns": 300, "run_timeout_seconds": 3600}})
        effective, snap = runner._impl_turn_budget("ghost", "implementer")
        assert effective == 300
        assert snap is None  # 无数字任务 → 无 kill_early 基线

    def test_sizing_disabled_keeps_base(self, tmp_path):
        """turn_budget_sizing.enabled=False → 推算关闭，大规模也维持 base。"""
        proot = tmp_path
        _seed_tasks_md(proot, "big", total=50)
        runner = make_sizing_runner(proot, {
            "agents": {"max_turns": 300, "run_timeout_seconds": 3600,
                       "turn_budget_sizing": {"enabled": False}}})
        effective, _ = runner._impl_turn_budget("big", "implementer")
        assert effective == 300

    def test_review_lane_keeps_base_and_no_snapshot(self, tmp_path):
        """评审/裁决车道不参与推算（runner 其余 max_turns 读点零改动）。"""
        proot = tmp_path
        _seed_tasks_md(proot, "big", total=50)
        runner = make_sizing_runner(
            proot, {"agents": {"max_turns": 300, "run_timeout_seconds": 3600}})
        for lane in ("spec-review", "dispute-judge", None):
            effective, snap = runner._impl_turn_budget("big", lane)
            assert effective == 300
            assert snap is None


# ── 4.2 判定面：remaining_tasks 观测与簿记注记 ─────────────────────────


class TestTurnLimitActionObservation:
    """``_turn_limit_action`` 的 remaining_tasks 观测与簿记占比注记（2.1/2.2）。"""

    def _runner(self, proot, **config_extra):
        return make_sizing_runner(
            proot, dict({"agents": {"run_timeout_seconds": 3600}},
                        **config_extra))

    def test_extend_evidence_carries_remaining_tasks(self, tmp_path):
        proot = tmp_path
        _seed_tasks_md(proot, "demo", total=5)
        run_file = _write_run_file(
            proot, "impl-demo-1-a1", [_now_tool_result_evt()])
        action = self._runner(proot)._turn_limit_action(
            run_file, "demo", "impl-demo-1-a1", 0, None, max_turns=400)
        assert action["action"] == "extend"
        assert action["remaining_tasks"] == 5
        assert "remaining_tasks=5" in action["evidence"]

    def test_kill_evidence_carries_remaining_tasks(self, tmp_path):
        proot = tmp_path
        _seed_tasks_md(proot, "demo", total=5)
        run_file = _write_run_file(proot, "impl-demo-1-a1", [])  # 无活性
        action = self._runner(proot)._turn_limit_action(
            run_file, "demo", "impl-demo-1-a1", 0, None, max_turns=400)
        assert action["action"] == "kill"
        assert action["remaining_tasks"] == 5
        assert "remaining_tasks=5" in action["evidence"]

    def test_missing_tasks_md_marks_unavailable(self, tmp_path):
        proot = tmp_path
        run_file = _write_run_file(
            proot, "impl-demo-1-a1", [_now_tool_result_evt()])
        action = self._runner(proot)._turn_limit_action(
            run_file, None, "impl-demo-1-a1", 0, None, max_turns=400)
        assert action["action"] == "extend"
        assert action["remaining_tasks"] is None
        assert "remaining_tasks=unavailable" in action["evidence"]

    def test_bookkeeping_share_annotated_without_verdict_change(self, tmp_path):
        """簿记占比超阈：evidence 注记 + WARNING，但 extend/kill 结论不变。"""
        proot = tmp_path
        run_file = _write_run_file(
            proot, "impl-demo-1-a1", [_now_tool_result_evt()])
        logger = _RecordingLogger()
        runner = self._runner(proot)
        runner.logger = logger
        action = runner._turn_limit_action(
            run_file, "demo", "impl-demo-1-a1", 0, None, max_turns=400,
            bookkeeping_share=0.9)
        assert action["action"] == "extend"
        assert "bookkeeping_share=0.90>=0.50" in action["evidence"]
        assert any("bookkeeping share" in w for w in logger.warnings)

    def test_bookkeeping_below_threshold_not_annotated(self, tmp_path):
        proot = tmp_path
        run_file = _write_run_file(
            proot, "impl-demo-1-a1", [_now_tool_result_evt()])
        action = self._runner(proot)._turn_limit_action(
            run_file, "demo", "impl-demo-1-a1", 0, None, max_turns=400,
            bookkeeping_share=0.3)
        assert action["action"] == "extend"
        assert "bookkeeping_share" not in action["evidence"]


# ── 4.2 守卫：kill_early（缺省关闭） ───────────────────────────────────


def _ke_config(enabled=True, remaining=10, floor=0.1):
    return {"agents": {
        "run_timeout_seconds": 3600,
        "turn_budget_sizing": {"enabled": True, "kill_early": {
            "enabled": enabled,
            "remaining_tasks_threshold": remaining,
            "progress_floor": floor,
        }}


    }}


class TestKillEarlyGuard:
    """末位扩容拆停守卫（3.1，tasks 4.2）。"""

    def test_disabled_bitwise_identical_with_legacy(self, tmp_path):
        """enabled=False（含缺省无键）时同输入同输出逐位一致——输入满足守卫
        全部其余条件，仅开关分出两种配置，结论必须逐位相等。"""
        proot = tmp_path
        # 12 任务勾 1 → remaining=11 ≥ 10；启动快照未勾 12、当前勾 1.1
        _seed_tasks_md(proot, "demo", total=12, checked=("1.1",))
        run_file = _write_run_file(proot, "impl-demo-1-a1", [])  # 无活性
        kwargs = dict(
            spec_name="demo", run_id="impl-demo-1-a1", turn_extensions_used=1,
            wt_path=None, agent_type="implementer", max_turns=400,
            task_progress_snapshot={
                "checked_ids": frozenset({"1.1"}), "unchecked": 12})
        by_default = make_sizing_runner(proot)._turn_limit_action(
            run_file, **kwargs)
        by_explicit_off = make_sizing_runner(
            proot, _ke_config(enabled=False))._turn_limit_action(
            run_file, **kwargs)
        assert by_default == by_explicit_off
        assert by_default["action"] == "kill"
        assert "no liveness" in by_default["evidence"]

    def test_enabled_hits_early_kill_on_last_extension(self, tmp_path):
        """开启 + 末位扩容 + 剩余足量 + 进度停滞 → 提前 kill（即便有活性
        证据在场——守卫先于活性矩阵判定）。"""
        proot = tmp_path
        # 当前勾 1.1、1.2 → remaining=10（恰在阈值上，≥ 语义）；启动后新勾 1 个
        _seed_tasks_md(proot, "demo", total=12, checked=("1.1", "1.2"))
        run_file = _write_run_file(
            proot, "impl-demo-1-a1", [_now_tool_result_evt()])
        action = make_sizing_runner(proot, _ke_config())._turn_limit_action(
            run_file, "demo", "impl-demo-1-a1", 1, None,
            agent_type="implementer", max_turns=400,
            task_progress_snapshot={
                "checked_ids": frozenset({"1.1"}), "unchecked": 12})
        assert action["action"] == "kill"
        assert "early-split" in action["evidence"]
        assert "remaining_tasks=10" in action["evidence"]

    def test_remaining_below_threshold_no_early_kill(self, tmp_path):
        """剩余任务数低于阈值 → 不触发守卫（落既有活性矩阵）。"""
        proot = tmp_path
        # 13 任务勾 4 → remaining=9 < 10
        _seed_tasks_md(proot, "demo", total=13,
                       checked=("1.1", "1.2", "1.3", "1.4"))
        run_file = _write_run_file(proot, "impl-demo-1-a1", [])  # 无活性
        action = make_sizing_runner(proot, _ke_config())._turn_limit_action(
            run_file, "demo", "impl-demo-1-a1", 1, None,
            agent_type="implementer", max_turns=400,
            task_progress_snapshot={
                "checked_ids": frozenset({"1.1"}), "unchecked": 13})
        assert action["action"] == "kill"
        assert "early-split" not in action["evidence"]
        assert "no liveness" in action["evidence"]

    def test_not_last_extension_no_early_kill(self, tmp_path):
        """非最后一次可用扩容（used+1 != TURN_EXTENSION_MAX）→ 不触发。"""
        proot = tmp_path
        _seed_tasks_md(proot, "demo", total=12, checked=("1.1", "1.2"))
        run_file = _write_run_file(
            proot, "impl-demo-1-a1", [_now_tool_result_evt()])
        action = make_sizing_runner(proot, _ke_config())._turn_limit_action(
            run_file, "demo", "impl-demo-1-a1", 0, None,
            agent_type="implementer", max_turns=400,
            task_progress_snapshot={
                "checked_ids": frozenset({"1.1"}), "unchecked": 12})
        assert action["action"] == "extend"
        assert "early-split" not in action["evidence"]

    def test_healthy_progress_still_extends(self, tmp_path):
        """进度健康（新勾占比 > progress_floor）→ 仍 extend：唯一挡守卫的
        是进度条件（remaining 仍在阈值上）。"""
        proot = tmp_path
        # 20 任务：启动未勾 20；当前勾 5 → remaining=15 ≥ 10，进度 5/20=0.25
        _seed_tasks_md(proot, "demo", total=20,
                       checked=("1.1", "1.2", "1.3", "1.4", "1.5"))
        run_file = _write_run_file(
            proot, "impl-demo-1-a1", [_now_tool_result_evt()])
        action = make_sizing_runner(proot, _ke_config())._turn_limit_action(
            run_file, "demo", "impl-demo-1-a1", 1, None,
            agent_type="implementer", max_turns=400,
            task_progress_snapshot={
                "checked_ids": frozenset(), "unchecked": 20})
        assert action["action"] == "extend"
        assert "early-split" not in action["evidence"]

    def test_review_lane_agent_type_never_triggers(self, tmp_path):
        """评审/裁决车道 agent_type 不触发守卫（勾选进度恒零，开启项目内
        不限车道必被误杀——design D6）。"""
        proot = tmp_path
        _seed_tasks_md(proot, "demo", total=12, checked=("1.1", "1.2"))
        run_file = _write_run_file(
            proot, "impl-demo-1-a1", [_now_tool_result_evt()])
        for lane in ("spec-review", "dispute-judge", None):
            action = make_sizing_runner(
                proot, _ke_config())._turn_limit_action(
                run_file, "demo", "impl-demo-1-a1", 1, None,
                agent_type=lane, max_turns=400,
                task_progress_snapshot={
                    "checked_ids": frozenset({"1.1"}), "unchecked": 12})
            assert action["action"] == "extend", lane
            assert "early-split" not in action["evidence"]

    def test_no_baseline_snapshot_conservative_skip(self, tmp_path):
        """无启动基线（快照缺失/无数字任务）→ 不判不济（保守不误杀）。"""
        proot = tmp_path
        _seed_tasks_md(proot, "demo", total=12, checked=("1.1", "1.2"))
        run_file = _write_run_file(proot, "impl-demo-1-a1", [])  # 无活性
        action = make_sizing_runner(proot, _ke_config())._turn_limit_action(
            run_file, "demo", "impl-demo-1-a1", 1, None,
            agent_type="implementer", max_turns=400,
            task_progress_snapshot=None)
        assert action["action"] == "kill"
        assert "early-split" not in action["evidence"]

    def test_extension_max_exhausted_still_kills_first(self, tmp_path):
        """封顶语义优先：used >= TURN_EXTENSION_MAX 时无条件 kill（守卫与
        活性矩阵都不再参与），evidence 为封顶文案。"""
        proot = tmp_path
        _seed_tasks_md(proot, "demo", total=12, checked=("1.1", "1.2"))
        run_file = _write_run_file(
            proot, "impl-demo-1-a1", [_now_tool_result_evt()])
        action = make_sizing_runner(proot, _ke_config())._turn_limit_action(
            run_file, "demo", "impl-demo-1-a1", TURN_EXTENSION_MAX, None,
            agent_type="implementer", max_turns=400,
            task_progress_snapshot={
                "checked_ids": frozenset({"1.1"}), "unchecked": 12})
        assert action["action"] == "kill"
        assert "budget exhausted" in action["evidence"]


# ── 4.2 轮询环端到端：turn_extension / run_metrics 事件携带字段 ────────


class TestTurnExtensionEventLoop:
    """fake Popen 驱动真实 ``_run_claude`` 轮询环（tasks 4.2）：流量活性
    续期留痕事件新增 ``remaining_tasks`` 字段、既有字段不丢；run_metrics
    行同键在场。"""

    def test_turn_extension_event_carries_remaining_tasks(self, monkeypatch,
                                                          tmp_path):
        proot = tmp_path / "proj"
        proot.mkdir()
        _seed_tasks_md(proot, "demo", total=5)  # 全未勾 → remaining=5
        runner = make_sizing_runner(proot)
        max_turns = 5
        # 8 个 assistant（足够触发 3 次判定：extend、extend、封顶 kill）
        # + 1 个流量 tool_result
        events = ([_now_evt("tool_result"), _now_tool_result_evt()]
                  + [_evt("assistant", None) for _ in range(8)])
        proc = _BurstFakeProc(events)
        _patch_popen(monkeypatch, proc)

        with pytest.raises(RuntimeError) as cm:
            runner._run_claude(
                "prompt", proot, "impl-demo-1-a1",
                max_turns=max_turns, spec_name="demo",
                agent_type="implementer")
        assert "Max turns" in str(cm.value)

        lines = _run_file_lines(proot, "impl-demo-1-a1")
        assert lines, "run 文件应非空"
        ext_events = [
            json.loads(l) for l in lines
            if json.loads(l).get("type") == "turn_extension"
        ]
        assert len(ext_events) == 2
        step = int(max_turns * TURN_EXTENSION_STEP_FRACTION)
        # 新增字段：remaining_tasks 随事件落盘
        assert ext_events[0]["remaining_tasks"] == 5
        assert ext_events[1]["remaining_tasks"] == 5
        assert "remaining_tasks=5" in ext_events[0]["evidence"]
        # 既有字段保持不变（附加不替换）
        assert ext_events[0]["extension"] == 1
        assert ext_events[1]["extension"] == 2
        assert ext_events[0]["turn_step"] == step
        assert ext_events[0]["new_turn_cap"] == max_turns + step

        # run_metrics 行同键在场（run 收尾时点快照）
        metrics = [
            json.loads(l) for l in lines
            if json.loads(l).get("type") == "run_metrics"
        ]
        assert metrics, "run_metrics 行应落盘"
        assert metrics[-1]["remaining_tasks"] == 5

    def test_turn_extension_event_remaining_unavailable_without_tasks_md(
            self, monkeypatch, tmp_path):
        """tasks.md 缺失 → 事件 remaining_tasks=None、evidence 注
        unavailable，续期决策不受影响。"""
        proot = tmp_path / "proj"
        proot.mkdir()
        runner = make_sizing_runner(proot)
        events = ([_now_evt("tool_result"), _now_tool_result_evt()]
                  + [_evt("assistant", None) for _ in range(8)])
        proc = _BurstFakeProc(events)
        _patch_popen(monkeypatch, proc)

        with pytest.raises(RuntimeError):
            runner._run_claude(
                "prompt", proot, "impl-demo-2-a1",
                max_turns=5, spec_name="ghost", agent_type="implementer")

        ext_events = [
            json.loads(l) for l in _run_file_lines(proot, "impl-demo-2-a1")
            if json.loads(l).get("type") == "turn_extension"
        ]
        assert ext_events, "无 tasks.md 也不得影响续期留痕"
        assert ext_events[0]["remaining_tasks"] is None
        assert "remaining_tasks=unavailable" in ext_events[0]["evidence"]
