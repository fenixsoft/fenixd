"""evo-add-impl-wallclock-budget-sizing — impl 车道墙钟预算 sizing 单测。

覆盖（tasks 3.1；2.3 复核口径以测试锁定）：

- sizing 归一化（``get_impl_wallclock_sizing_config``）：非法类型 / 越界逐项
  回退缺省（风格对齐 ``get_turn_budget_sizing_config``，不抛异常）、缺省单源
  ``core.config.IMPL_WALLCLOCK_SIZING_DEFAULTS``；
- ``lifted_max_extensions_for_scale`` 档位：scale 等于阈值不抬（严格大于
  语义）、阈值+1 抬、只抬不压、disabled / 非法输入恒返回 base、同 scale
  幂等（档位入参只认启动同源总规模分，不认 remaining_tasks）；
- 扩容判定新分支（``_supervision_deadline_action`` 直调）：impl 车道按
  ``impl_scale`` 抬 max_extensions（base 2 → 4）、剩余任务非零照常扩容且
  extend/kill evidence 携带 remaining_tasks、预算耗尽击杀 reason 保留
  "extension budget exhausted" 子串（budget._is_exemptable_reason 豁免
  复核口径，remaining_tasks 只进 evidence 不进 reason）、absolute_max 仍
  封顶、档位幂等（推进中 remaining_tasks 递减不回撤已抬档位、剩余为零不
  新增提前击杀）、impl_scale=None / 非 implementer 车道不抬升（行为与引入
  前逐位一致）、STATE 覆盖键 impl_wallclock_extension_override 优先且只抬
  不压；
- 用量缺失注记（fake Popen 驱动真实 ``_run_agent`` 轮询环，装置仿
  tests/test_impl_run_budget_sizing.py 的 _BurstFakeProc，自足不跨文件
  import）：击杀且无 CLI result 的 run_metrics 行携带 usage_missing（原因 +
  transcript_bytes/turns 粗估维度）、成功路径（result 在场）与「击杀但
  result 在场」均不落注记；timeout_extension 事件携带 remaining_tasks。
"""

import io
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.config import IMPL_WALLCLOCK_SIZING_DEFAULTS
from core.fast_track_result import (
    estimate_spec_scale,
    get_impl_wallclock_sizing_config,
    lifted_max_extensions_for_scale,
)
from core.pm_engine.budget import ImplBudget
from core.state_machine import IMPL_WALLCLOCK_EXTENSION_OVERRIDE_FIELD
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
    """seed STATE.md per-spec 条目（impl_wallclock_extension_override 等）。"""
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
    runner._liveness._extension_baselines = {}
    return runner


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


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


def _write_run_file(proot: Path, run_id: str, events: list) -> Path:
    run_file = proot / ".fenix" / "runs" / f"{run_id}.jsonl"
    run_file.parent.mkdir(parents=True, exist_ok=True)
    with run_file.open("a", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return run_file


def _run_file_lines(proot: Path, run_id: str) -> list:
    run_file = proot / ".fenix" / "runs" / f"{run_id}.jsonl"
    try:
        return [ln for ln in run_file.read_text(encoding="utf-8").splitlines()
                if ln.strip()]
    except OSError:
        return []


def _recent_run_file(proot: Path, run_id: str = "impl-demo-1-a1") -> Path:
    """带 30s 前 assistant 事件的 run 流（snapshot 可读且窗口内非零事件）。"""
    return _write_run_file(proot, run_id, [{
        "type": "assistant",
        "timestamp": _iso(time.time() - 30),
        "message": {"content": [{"type": "tool_use", "name": "Edit"}]},
    }])


_ADVANCING = {"verdict": "advancing", "evidence": "still editing"}


def _decide(runner, run_file, *, extensions, agent_type="implementer",
            spec_name="demo", impl_scale=None, remaining_tasks=None,
            started_ago=6000, judge=None):
    """_supervision_deadline_action 直调包装（观测入参显式化）。"""
    return runner._supervision_deadline_action(
        run_file, spec_name, "impl-demo-1-a1",
        time.time() - started_ago, extensions,
        judge=judge, agent_type=agent_type,
        remaining_tasks=remaining_tasks, impl_scale=impl_scale)


# ── 1.1 sizing 归一化 ────────────────────────────────────────────────


class TestImplWallclockSizingConfig:
    """get_impl_wallclock_sizing_config 归一化：缺省单源、非法逐项回退。"""

    def test_defaults_match_single_source(self):
        cfg = get_impl_wallclock_sizing_config({})
        assert cfg == {
            "enabled": IMPL_WALLCLOCK_SIZING_DEFAULTS["enabled"],
            "full_scale_threshold":
                IMPL_WALLCLOCK_SIZING_DEFAULTS["full_scale_threshold"],
            "extra_extensions":
                IMPL_WALLCLOCK_SIZING_DEFAULTS["extra_extensions"],
        }
        assert cfg["enabled"] is True
        assert cfg["full_scale_threshold"] == 45
        assert cfg["extra_extensions"] == 2

    @pytest.mark.parametrize("bad_config", [None, "x", [], 42])
    def test_non_dict_config_falls_back(self, bad_config):
        assert (get_impl_wallclock_sizing_config(bad_config)
                == get_impl_wallclock_sizing_config({}))

    def test_non_dict_agents_or_section_falls_back(self):
        base = get_impl_wallclock_sizing_config({})
        assert get_impl_wallclock_sizing_config({"agents": "x"}) == base
        assert get_impl_wallclock_sizing_config(
            {"agents": {"impl_wallclock_sizing": "x"}}) == base

    @pytest.mark.parametrize("bad", [True, -1, 1.5, "45", 10001])
    def test_invalid_threshold_falls_back(self, bad):
        cfg = get_impl_wallclock_sizing_config(
            {"agents": {"impl_wallclock_sizing": {"full_scale_threshold": bad}}})
        assert cfg["full_scale_threshold"] == 45

    @pytest.mark.parametrize("bad", [True, -1, 2.5, "2", 10001])
    def test_invalid_extra_falls_back(self, bad):
        cfg = get_impl_wallclock_sizing_config(
            {"agents": {"impl_wallclock_sizing": {"extra_extensions": bad}}})
        assert cfg["extra_extensions"] == 2

    def test_zero_extra_is_legal_explicit_no_lift(self):
        cfg = get_impl_wallclock_sizing_config(
            {"agents": {"impl_wallclock_sizing": {"extra_extensions": 0}}})
        assert cfg["extra_extensions"] == 0

    @pytest.mark.parametrize("bad", ["yes", 1, None])
    def test_invalid_enabled_falls_back(self, bad):
        cfg = get_impl_wallclock_sizing_config(
            {"agents": {"impl_wallclock_sizing": {"enabled": bad}}})
        assert cfg["enabled"] is True

    def test_valid_section_applies(self):
        cfg = get_impl_wallclock_sizing_config(
            {"agents": {"impl_wallclock_sizing": {
                "enabled": True,
                "full_scale_threshold": 30,
                "extra_extensions": 3}}})
        assert cfg == {
            "enabled": True, "full_scale_threshold": 30, "extra_extensions": 3}

    def test_disabled_flag_respected(self):
        cfg = get_impl_wallclock_sizing_config(
            {"agents": {"impl_wallclock_sizing": {"enabled": False}}})
        assert cfg["enabled"] is False


# ── 1.1 档位函数：只抬不压 / 阈值边界 / 幂等 ──────────────────────────


class TestLiftedMaxExtensionsForScale:

    def test_threshold_boundary_strict_greater(self):
        cfg = get_impl_wallclock_sizing_config({})
        # 规模分等于阈值不抬（严格大于语义，与 budget_tier_for_scale 同源）
        assert lifted_max_extensions_for_scale(2, 45, cfg) == 2
        assert lifted_max_extensions_for_scale(2, 46, cfg) == 4

    def test_only_lift_never_lower(self):
        cfg = get_impl_wallclock_sizing_config({})
        assert lifted_max_extensions_for_scale(2, 100, cfg) == 4
        assert lifted_max_extensions_for_scale(10, 100, cfg) == 12

    def test_extra_zero_means_explicit_no_lift(self):
        cfg = dict(get_impl_wallclock_sizing_config({}), extra_extensions=0)
        assert lifted_max_extensions_for_scale(2, 100, cfg) == 2

    def test_disabled_returns_base(self):
        cfg = dict(get_impl_wallclock_sizing_config({}), enabled=False)
        assert lifted_max_extensions_for_scale(2, 1000, cfg) == 2

    @pytest.mark.parametrize("bad_scale", [None, "50", True, 1.5, -3])
    def test_non_int_scale_returns_base(self, bad_scale):
        cfg = get_impl_wallclock_sizing_config({})
        assert lifted_max_extensions_for_scale(2, bad_scale, cfg) == 2

    def test_non_dict_cfg_falls_back_to_defaults(self):
        """cfg 非 dict → 视为 {} → 单点缺省（enabled）参与判定，风格与
        suggested_turn_cap_for_scale 的容错同型。"""
        assert (lifted_max_extensions_for_scale(2, 1000, None)
                == lifted_max_extensions_for_scale(2, 1000, {}))

    def test_idempotent_for_same_scale(self):
        """同 run 各次 deadline 判定档位推导幂等：同一 scale 输入恒同输出。

        design「档位幂等」：规模入参取 run 启动同源总规模（estimate_spec_scale
        单点），函数签名不收 remaining_tasks——剩余数随推进递减不构成回撤
        档位的输入，extensions_used ≥ max_extensions 的伪击杀不会发生。
        """
        cfg = get_impl_wallclock_sizing_config({})
        outs = {lifted_max_extensions_for_scale(2, 120, cfg) for _ in range(20)}
        assert outs == {4}


# ── 1.2/2.1 扩容判定接入（_supervision_deadline_action 直调） ─────────


class TestSupervisionDeadlineSizing:
    """impl 车道 sizing 在封闭矩阵内的落点：只抬续期预算，其余分支不变。"""

    def setup_method(self):
        import tempfile
        self.tmpdir = Path(__import__("tempfile").mkdtemp())
        self.runner = make_sizing_runner(self.tmpdir)
        self.run_file = _recent_run_file(self.tmpdir)

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _judge_advancing(self):
        return MagicMock(return_value=dict(_ADVANCING))

    def test_impl_lane_lifts_budget_base2_to_4(self):
        """大规模 impl run：base 2 → 4，第 2/3 次续期不再被预算耗尽击杀。"""
        judge = self._judge_advancing()
        d = _decide(self.runner, self.run_file, extensions=1,
                    impl_scale=120, remaining_tasks=5, judge=judge)
        assert d["action"] == "extend"
        assert d["extension_index"] == 2
        d = _decide(self.runner, self.run_file, extensions=2,
                    impl_scale=120, remaining_tasks=5, judge=judge)
        # base max_extensions=2 下此处应为 kill——能 extend 即抬升生效
        assert d["action"] == "extend"
        assert d["extension_index"] == 3
        d = _decide(self.runner, self.run_file, extensions=3,
                    impl_scale=120, remaining_tasks=5, judge=judge)
        assert d["action"] == "extend"
        assert d["extension_index"] == 4

    def test_budget_exhausted_kill_keeps_reason_and_evidence(self):
        """抬升后预算（4）用尽才击杀：reason 保留豁免判据子串，
        remaining_tasks 进 evidence/返回字段、不进 reason。"""
        judge = MagicMock(side_effect=AssertionError("judge must not be called"))
        d = _decide(self.runner, self.run_file, extensions=4,
                    impl_scale=120, remaining_tasks=5, judge=judge)
        assert d["action"] == "kill"
        assert "extension budget exhausted (4/4)" in d["reason"]
        assert "remaining_tasks" not in d["reason"]
        assert d["evidence"].endswith("remaining_tasks=5")
        assert d["remaining_tasks"] == 5
        judge.assert_not_called()

    def test_no_lift_without_impl_scale_is_bitwise_compat(self):
        """impl_scale=None（既有直调/门面委托/解析回退）：行为与引入前逐位
        一致——base 2 用尽即杀，evidence 注 remaining_tasks=unavailable。"""
        judge = MagicMock(side_effect=AssertionError("judge must not be called"))
        d = _decide(self.runner, self.run_file, extensions=2,
                    impl_scale=None, remaining_tasks=None, judge=judge)
        assert d["action"] == "kill"
        assert "extension budget exhausted (2/2)" in d["reason"]
        assert d["evidence"].endswith("remaining_tasks=unavailable")
        assert d["remaining_tasks"] is None

    def test_non_implementer_lane_not_lifted(self):
        """fast-track 车道不叠加 sizing（其 higher 档 +2 先例语义不动）：
        无 STATE 标记时保持 base 2。"""
        judge = MagicMock(side_effect=AssertionError("judge must not be called"))
        d = _decide(self.runner, self.run_file, extensions=2,
                    agent_type="fast-track", impl_scale=120,
                    remaining_tasks=5, judge=judge)
        assert d["action"] == "kill"
        assert "extension budget exhausted (2/2)" in d["reason"]

    def test_absolute_max_still_caps_lifted_budget(self):
        """sizing 只扩续期预算：total 墙钟越过 absolute_max 无条件终止，
        不因剩余任务非零/预算未用尽而绕过封顶。"""
        judge = MagicMock(side_effect=AssertionError("judge must not be called"))
        d = _decide(self.runner, self.run_file, extensions=0,
                    impl_scale=120, remaining_tasks=16,
                    started_ago=10 ** 6, judge=judge)
        assert d["action"] == "kill"
        assert "absolute_max_seconds cap reached" in d["reason"]
        assert d["evidence"].endswith("remaining_tasks=16")

    def test_tier_idempotent_as_remaining_tasks_decreases(self):
        """档位幂等：同 run 逐 deadline 判定中 remaining_tasks 随推进递减，
        已抬档位不得回撤（否则 extensions_used ≥ 回撤后预算触发伪击杀）；
        剩余为零也不新增提前击杀（封闭矩阵不变）。"""
        judge = self._judge_advancing()
        for remaining in (5, 2, 0):
            d = _decide(self.runner, self.run_file, extensions=3,
                        impl_scale=120, remaining_tasks=remaining, judge=judge)
            # 若档位被回撤（base 2），extensions=3 会误判预算耗尽击杀
            assert d["action"] == "extend", (remaining, d)
            assert d["extension_index"] == 4

    def test_state_override_preferred_and_only_lifts(self):
        """STATE 覆盖键优先于规模推算，且只抬不压（override < base 时保持
        base）；覆写字段经 STATE.md 序列化往返不丢。"""
        sm = _seed_state(self.tmpdir, "demo",
                         **{IMPL_WALLCLOCK_EXTENSION_OVERRIDE_FIELD: 6})
        # 序列化往返：新建 StateMachine 从盘读回，覆写字段不在白名单会静默丢失
        from core.state_machine import StateMachine
        sm2 = StateMachine(self.tmpdir / ".fenix" / "STATE.md", FakeLogger())
        assert (sm2.read_one("demo") or {}).get(
            IMPL_WALLCLOCK_EXTENSION_OVERRIDE_FIELD) == 6
        self.runner.state_machine = sm

        judge = self._judge_advancing()
        d = _decide(self.runner, self.run_file, extensions=5,
                    impl_scale=None, remaining_tasks=2, judge=judge)
        assert d["action"] == "extend"
        assert d["extension_index"] == 6
        d = _decide(self.runner, self.run_file, extensions=6,
                    impl_scale=None, remaining_tasks=2, judge=judge)
        assert d["action"] == "kill"
        assert "extension budget exhausted (6/6)" in d["reason"]

        # 只抬不压：override=1 < base 2 → 生效预算仍为 base 2（第 2 次续期
        # 到点即杀，未被压低的 override=1 提前、也未把预算放大）
        sm.update_spec("demo", {IMPL_WALLCLOCK_EXTENSION_OVERRIDE_FIELD: 1})
        d = _decide(self.runner, self.run_file, extensions=2,
                    impl_scale=None, remaining_tasks=2, judge=judge)
        assert d["action"] == "kill"
        assert "extension budget exhausted (2/2)" in d["reason"]

    def test_override_read_tolerates_missing_state(self):
        """state_machine 缺失 → override=None（等价不覆写），不放大为监督故障。"""
        self.runner.state_machine = None
        assert self.runner._impl_wallclock_extension_override("demo") is None


class TestScaleAndRemainingHelpers:
    """runner 侧两个单点同源取数助手（1.2/2.1 的入参供给）。"""

    def setup_method(self):
        import tempfile
        self.tmpdir = Path(__import__("tempfile").mkdtemp())
        self.runner = make_sizing_runner(self.tmpdir)

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_impl_wallclock_scale_single_source(self):
        """规模分与轮数 sizing 同源（estimate_spec_scale 单点）：50 任务 = 50
        分 > 45 阈值；仅 implementer 车道取数；ghost spec 回退 0（不抬）。"""
        _seed_tasks_md(self.tmpdir, "big", total=50)
        assert self.runner._impl_wallclock_scale("big", "implementer") == 50
        assert self.runner._impl_wallclock_scale("big", "fast-track") is None
        assert self.runner._impl_wallclock_scale(None, "implementer") is None
        assert self.runner._impl_wallclock_scale("ghost", "implementer") == 0

    def test_impl_wallclock_scale_matches_estimate_spec_scale(self):
        _seed_tasks_md(self.tmpdir, "mid", total=10)
        expected = estimate_spec_scale(
            self.tmpdir / "spec" / "changes" / "mid")
        assert self.runner._impl_wallclock_scale("mid", "implementer") == expected

    def test_remaining_tasks_now_uses_parse_tasks_md(self):
        """与 finally run_metrics 同源（parse_tasks_md）：3 任务勾 1 → 剩 2；
        ghost/无 spec → None（观测面故障不改变判定）。"""
        _seed_tasks_md(self.tmpdir, "demo", total=3, checked=("1.1",))
        assert self.runner._remaining_tasks_now("demo") == 2
        assert self.runner._remaining_tasks_now("ghost") is None
        assert self.runner._remaining_tasks_now(None) is None


# ── 2.3 豁免口径复核（决策 5）：sizing 生效后仍不可豁免 ───────────────


class TestBudgetExemptStableAfterSizing:
    """sizing 只改 reason 括号内的次数（2/2 → 4/4），"extension budget
    exhausted" 子串不动——_is_exemptable_reason 不可豁免口径仍成立。"""

    @pytest.mark.parametrize("reason", [
        "Timeout after 12600s — extension budget exhausted (2/2)",
        "Timeout after 12600s — extension budget exhausted (4/4)",
        "absolute_max_seconds cap reached (18600s, extensions_used=2)",
        "run timeout reached (supervision disabled)",
        "judged stagnant",
    ])
    def test_non_exemptable_reasons(self, reason):
        assert ImplBudget._is_exemptable_reason(reason) is False

    @pytest.mark.parametrize("reason", [
        "process died unexpectedly (exit 1)",
        "provider circuit open",
        "daemon shutdown",
    ])
    def test_infra_reasons_still_exemptable(self, reason):
        assert ImplBudget._is_exemptable_reason(reason) is True


# ── 2.1/2.2 轮询环集成（fake Popen 驱动真实 _run_agent） ────────────


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


class _DoneFakeProc:
    """自然收工替身：首次 poll() 给读线程一拍时间，其后返回 rc=0。"""

    def __init__(self, events: list):
        self._events = [l for l in events if l is not None]
        self._polls = 0
        self.pid = 4243
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
        self._polls += 1
        return None if self._polls == 1 else 0

    def wait(self, timeout=None):
        return 0

    def terminate(self):
        pass

    def kill(self):
        pass


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


class _VirtualTime:
    """runner 模块级 time 替身：``sleep`` 把秒数计入虚拟偏移（真实仅让拍
    ``cap`` 秒给读线程），``time`` 返回真实时间 + 虚拟偏移——墙钟 deadline
    逐窗到点但不消耗真实墙钟。其余 time.* 委托真实模块（同构
    tests/test_impl_env_blocker_stop_loss.py 的 _FastTime，差异仅在虚拟推进）。
    liveness 决策侧自持真实 time.time()，其 mtime 新鲜度 / 事件窗口判定不受
    虚拟偏移影响。"""

    def __init__(self, real, cap: float = 0.01):
        self._real = real
        self._cap = cap
        self._offset = 0.0

    def __getattr__(self, name):
        return getattr(self._real, name)

    def time(self):
        return self._real.time() + self._offset

    def sleep(self, seconds):
        self._offset += float(seconds)
        self._real.sleep(self._cap)


class TestWallclockSizingRunLoop:
    """端到端：墙钟 deadline 判定按 sizing 抬续期预算、事件/证据携带
    remaining_tasks、击杀且无 CLI result 落用量缺失注记。"""

    def _sized_runner(self, proot):
        runner = make_sizing_runner(proot, {
            "agents": {
                "run_timeout_seconds": 1,
                "timeout_supervision": {
                    "extension_seconds": 1,
                    "max_extensions": 2,
                    "judge_window": 30,
                },
            }})
        # judge 恒 advancing（隔离 LLM 通道）：预算耗尽成为唯一击杀路径
        runner._liveness._judge_liveness = (
            lambda snapshot, spec, rid: dict(_ADVANCING))
        return runner

    # [fenix-ignore:ebe2fd4b1f9e] 5.02s 系修复前基线（轮询环 5×1s 真实 sleep 的指纹），
    # HEAD c749d120 已注入 _VirtualTime 虚拟墙钟（sleep 仅真实让拍 0.01s 推进虚拟
    # 偏移，runner.py:6215 唯一 sleep 已被拦截），当前耗时已压缩至亚秒级。
    def test_kill_loop_extends_lifted_budget_and_notes_usage(
            self, monkeypatch, tmp_path):
        proot = tmp_path / "proj"
        proot.mkdir()
        _seed_tasks_md(proot, "demo", total=50)  # 规模分 50 > 45 → +2 档
        runner = self._sized_runner(proot)
        events = [_now_evt("tool_result"), _now_tool_result_evt()]
        _patch_popen(monkeypatch, _BurstFakeProc(events))
        # 提速：轮询环 sleep 改为推进虚拟墙钟（1s 基础窗 + 4×1s 续期窗不消耗
        # 真实时间）。deadline 仍逐窗到点、extend/kill 记账语义逐位不变，
        # extension_seconds 事件值仍为配置地板 1.0，断言全部保持原期望。
        import core.agent_runner.runner as rmod
        monkeypatch.setattr(rmod, "time", _VirtualTime(time))

        with pytest.raises(RuntimeError) as cm:
            runner._run_agent(
                "prompt", proot, "impl-demo-1-a1",
                spec_name="demo", agent_type="implementer")
        # base max_extensions=2 下第 3 次 deadline 即杀——消息带 (4/4) 即抬升生效
        assert "extension budget exhausted (4/4)" in str(cm.value)

        lines = [json.loads(l)
                 for l in _run_file_lines(proot, "impl-demo-1-a1")]
        assert lines, "run 文件应非空"

        # timeout_extension 事件：4 次续期（> base 2），逐次携带 remaining_tasks
        ext = [l for l in lines if l.get("type") == "timeout_extension"]
        assert [e["extension"] for e in ext] == [1, 2, 3, 4]
        assert all(e["remaining_tasks"] == 50 for e in ext)
        assert all("remaining_tasks=50" in e["evidence"] for e in ext)
        # 既有字段保持（附加不替换）
        assert all(e["extension_seconds"] == 1.0 for e in ext)

        # 终态 error 行携带击杀 reason（豁免判据子串原样保留）
        err = [l for l in lines if l.get("type") == "error"]
        assert err and "extension budget exhausted (4/4)" in json.dumps(err[-1],
                                                                       ensure_ascii=False)

        # run_metrics：击杀且无 CLI result → usage_missing 注记在场
        metrics = [l for l in lines if l.get("type") == "run_metrics"]
        assert metrics and "usage_missing" in metrics[-1]
        note = metrics[-1]["usage_missing"]
        assert note["reason"].startswith("killed_without_cli_result")
        assert isinstance(note["transcript_bytes"], int) and note["transcript_bytes"] > 0
        assert note["turns"] == 0
        assert metrics[-1]["remaining_tasks"] == 50

    def test_success_run_has_no_usage_note(self, monkeypatch, tmp_path):
        """成功路径（result 事件在场）行为不变：run_metrics 无 usage_missing。"""
        proot = tmp_path / "proj"
        proot.mkdir()
        _seed_tasks_md(proot, "demo", total=3, checked=("1.1",))
        runner = make_sizing_runner(proot, {
            "agents": {"run_timeout_seconds": 3600}})
        events = [
            _now_evt("tool_result"),
            _now_tool_result_evt(),
            {"type": "result", "timestamp": time.time(), "result": "done",
             "num_turns": 1, "usage": {"input_tokens": 10},
             "total_cost_usd": 0.01},
        ]
        _patch_popen(monkeypatch, _DoneFakeProc(events))

        out = runner._run_agent(
            "prompt", proot, "impl-demo-2-a1",
            spec_name="demo", agent_type="implementer")
        assert out[0] == "done"

        lines = [json.loads(l) for l in _run_file_lines(proot, "impl-demo-2-a1")]
        metrics = [l for l in lines if l.get("type") == "run_metrics"]
        assert metrics and "usage_missing" not in metrics[-1]
        assert metrics[-1]["remaining_tasks"] == 2

    def test_turn_limit_kill_with_result_has_no_usage_note(
            self, monkeypatch, tmp_path):
        """击杀但 result 在场（轮次上限路径）：用量随 result 落盘，不落注记。"""
        proot = tmp_path / "proj"
        proot.mkdir()
        runner = make_sizing_runner(proot)
        events = (
            [_now_evt("tool_result"), _now_tool_result_evt()]
            + [{"type": "result", "timestamp": time.time(), "result": "partial",
                "num_turns": 1}]
            + [_evt("assistant", None) for _ in range(8)]
        )
        _patch_popen(monkeypatch, _BurstFakeProc(events))

        with pytest.raises(RuntimeError) as cm:
            runner._run_agent(
                "prompt", proot, "impl-demo-3-a1",
                max_turns=2, spec_name="ghost", agent_type="implementer")
        assert "Max turns" in str(cm.value)

        lines = [json.loads(l) for l in _run_file_lines(proot, "impl-demo-3-a1")]
        metrics = [l for l in lines if l.get("type") == "run_metrics"]
        assert metrics and "usage_missing" not in metrics[-1]
