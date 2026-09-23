"""add-freeze-stop-inflight-agents 单测：冻结即停（轮询环）、独立终态与保持标记。

覆盖：
- 7.1 轮询环 frozen 命中：终止序列触发、frozen-terminated 终态行落盘、
  FrozenTerminatedError 抛出；未冻结零影响；STATE 读取异常 fail-open。
- 7.2 优先级与旗标清理：frozen 检查先于 cancel 检查；frozen 命中清理残留 cancel 旗标。
- 7.3 _frozen_hold 序列化往返与 mark_frozen_hold 原子写形态。
- 7.4 unfreeze_spec 续做接线（_frozen_hold + 保留分支 → resume；零提交/缺失 → 降级）。
- 7.5 共享判定零漂移：_recovery_preserve_spec 与 unfreeze_spec 续做同源。
- 7.9 分支保护扩展：frozen + _frozen_hold 的 blocked spec 的 branch 受保护。
"""
import json
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent_runner import runner as runner_module
from core.agent_runner import AgentRunner, AGENT_TERMINATE_GRACE_SECONDS, RunCancelledError
from core.agent_runner.result_gate import AgentRunResult, FrozenTerminatedError
from core.agent_runner.liveness import RUN_TERMINAL_EVENT_TYPES
from core.state_machine import (
    FROZEN_HOLD_FIELD,
    StateMachine,
    FROZEN_FIELD,
)


class FakeLogger:
    def info(self, *a, **kw):
        pass

    def warning(self, *a, **kw):
        pass

    def error(self, *a, **kw):
        pass

    def debug(self, *a, **kw):
        pass


def make_runner(proot: Path) -> AgentRunner:
    """构造最小 AgentRunner 实例（与 test_run_cancel 同款补丁缝对齐）。"""
    runner = AgentRunner.__new__(AgentRunner)
    runner.config = {}
    runner.worktree_manager = None
    runner.state_machine = None
    runner.project_root = proot
    runner.logger = FakeLogger()
    runner._running_agents = {}
    runner._daily_run_count = 0
    runner._provider_circuit._daily_reset_date = None
    runner._provider_circuit._daily_provider_attempts = {}
    runner._provider_circuit._daily_provider_warned = {}
    runner._provider_circuit.provider_circuits = {}
    return runner


def read_run_file(proot: Path, run_id: str) -> list:
    """读 run 产物 jsonl → 逐行 dict（与 test_run_cancel 同款）。"""
    p = proot / ".fenix" / "runs" / f"{run_id}.jsonl"
    lines = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        lines.append(json.loads(line))
    return lines


def _mk_sm(tmpdir: str) -> StateMachine:
    proot = Path(tmpdir)
    (proot / ".fenix").mkdir(parents=True, exist_ok=True)
    return StateMachine(proot / ".fenix" / "STATE.md", MagicMock())


def _spawn_polling(tmp_path, monkeypatch, *, frozen: bool = True,
                   cancel_requested: bool = False, state_read_error: bool = False):
    proot = tmp_path / "proj"
    (proot / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
    runner = make_runner(proot)
    runner.config = {"agents": {"run_timeout_seconds": 3600}}

    sm = MagicMock()

    # frozen 命中经「布防」门控：注册观察到位后才对轮询环暴露 frozen 态。
    # 直接 frozen=True 时，轮询环首圈即命中并在 60ms 内走完
    # terminate→注销→raise 全序列，下方「等注册」轮询（50ms 步长）大概率
    # 错过注册窗口（_running_agents 在 finally 段注销）→ 假失败。布防后
    # 注册窗口 ≥1 个轮询周期（1s），既可观察又保持 frozen 优先级语义。
    frozen_gate = {"armed": False}

    def fake_read_one(name):
        if state_read_error:
            raise RuntimeError("STATE 读取失败")
        if not frozen or not frozen_gate["armed"]:
            return {}
        return {"status": "blocked", "frozen": True}

    sm.read_one = fake_read_one
    runner.state_machine = sm

    orig_popen = runner_module.subprocess.Popen

    def fake_popen(cmd, **kw):
        # 只劫持 agent 主进程 spawn（claude CLI）。subprocess.Popen 是模块级
        # 全局——无差别替换会把 _run_claude 链路里其它 subprocess.run（如
        # 冻结命中路径上 _wip_checkpoint_on_forced_kill → _worktree_path_valid
        # 的 git 探测，timeout=10）也换成 sleep(30) 假进程，烧满超时
        # （2026-09-23 取证：冻结用例被拖到 10.0s）。非 agent 调用透传。
        if not (isinstance(cmd, list) and cmd and cmd[0] == "claude"):
            return orig_popen(cmd, **kw)
        kw.pop("text", None)
        kw.pop("bufsize", None)
        kw.pop("env", None)
        kw.pop("cwd", None)
        return orig_popen(["python3", "-c", "import time; time.sleep(30)"],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    monkeypatch.setattr(runner_module.subprocess, "Popen", fake_popen)

    outcome = {}

    def worker():
        try:
            runner._run_claude(
                "prompt", proot, "impl-x-123-a1",
                model_override="m", max_turns=50,
                spec_name="x", agent_type="implementer",
            )
            outcome["result"] = "returned"
        except FrozenTerminatedError as e:
            outcome["result"] = "frozen"
            outcome["reason"] = e.reason
        except RunCancelledError:
            outcome["result"] = "cancelled"
        except Exception as e:  # noqa: BLE001
            outcome["result"] = f"err:{e}"

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    deadline = time.time() + 5
    while time.time() < deadline and "impl-x-123-a1" not in runner._running_agents:
        time.sleep(0.05)
    assert "impl-x-123-a1" in runner._running_agents
    frozen_gate["armed"] = True  # 注册已观察 → 下一轮询周期命中 frozen

    if cancel_requested:
        runner.cancel_run("impl-x-123", reason="先取消", by="admin")
    return runner, t, outcome, proot


def test_frozen_hit_terminates_and_writes_frozen_terminal(tmp_path, monkeypatch):
    """7.1：frozen 命中 → 终止序列触发、frozen-terminated 终态行落盘、抛 FrozenTerminatedError。"""
    runner, t, outcome, proot = _spawn_polling(tmp_path, monkeypatch)
    t.join(timeout=AGENT_TERMINATE_GRACE_SECONDS + 5)
    assert outcome.get("result") == "frozen", outcome
    assert "frozen" in (outcome.get("reason") or "")

    lines = read_run_file(proot, "impl-x-123-a1")
    # 末行终态口径：以读侧 RUN_TERMINAL_EVENT_TYPES 反查最后终态行，
    # MUST NOT 断言物理末行字符串（run_metrics 行本就在终态行之后追加）。
    terminal_idx = None
    for i, line in enumerate(lines):
        if line.get("type") in RUN_TERMINAL_EVENT_TYPES:
            terminal_idx = i
    assert terminal_idx is not None
    last_terminal = lines[terminal_idx]
    assert last_terminal["type"] == "frozen-terminated"
    assert "frozen" in (last_terminal.get("reason") or "")
    assert last_terminal.get("by") == "admin"
    # 不得误写 cancelled 终态行
    assert not any(l.get("type") == "cancelled" for l in lines)
    # 进程消失（终止成功）
    assert "impl-x-123-a1" not in runner._running_agents


def test_not_frozen_zero_impact(tmp_path, monkeypatch):
    """7.1：未冻结 → 轮询环不触发冻结分支，run 自然收工零影响。"""
    proot = tmp_path / "proj"
    (proot / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
    runner = make_runner(proot)
    runner.config = {"agents": {"run_timeout_seconds": 3600}}
    sm = MagicMock()
    sm.read_one = lambda name: {"status": "implementing"}
    runner.state_machine = sm

    orig_popen = runner_module.subprocess.Popen

    def fake_popen(cmd, **kw):
        kw.pop("text", None)
        kw.pop("bufsize", None)
        kw.pop("env", None)
        kw.pop("cwd", None)
        return orig_popen(["python3", "-c", "import time; time.sleep(1)"],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    monkeypatch.setattr(runner_module.subprocess, "Popen", fake_popen)
    outcome = {}

    def worker():
        try:
            runner._run_claude(
                "prompt", proot, "impl-x-123-a1",
                model_override="m", max_turns=50,
                spec_name="x", agent_type="implementer",
            )
            outcome["result"] = "returned"
        except FrozenTerminatedError:
            outcome["result"] = "frozen"
        except Exception as e:  # noqa: BLE001
            outcome["result"] = f"err:{e}"

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout=15)
    assert outcome.get("result") == "returned", outcome
    lines = read_run_file(proot, "impl-x-123-a1")
    assert not any(l.get("type") == "frozen-terminated" for l in lines)


def test_state_read_error_fail_open(tmp_path, monkeypatch):
    """7.1：STATE 读取异常 → fail-open（返回 False），不终止。"""
    proot = tmp_path / "proj"
    (proot / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
    runner = make_runner(proot)
    runner.config = {"agents": {"run_timeout_seconds": 3600}}
    sm = MagicMock()

    def fake_read_one(name):
        raise RuntimeError("STATE 读取失败")

    sm.read_one = fake_read_one
    runner.state_machine = sm

    orig_popen = runner_module.subprocess.Popen

    def fake_popen(cmd, **kw):
        kw.pop("text", None)
        kw.pop("bufsize", None)
        kw.pop("env", None)
        kw.pop("cwd", None)
        return orig_popen(["python3", "-c", "import time; time.sleep(1)"],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    monkeypatch.setattr(runner_module.subprocess, "Popen", fake_popen)
    outcome = {}

    def worker():
        try:
            runner._run_claude(
                "prompt", proot, "impl-x-123-a1",
                model_override="m", max_turns=50,
                spec_name="x", agent_type="implementer",
            )
            outcome["result"] = "returned"
        except FrozenTerminatedError:
            outcome["result"] = "frozen"
        except Exception as e:  # noqa: BLE001
            outcome["result"] = f"err:{e}"

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout=15)
    # fail-open：不抛 FrozenTerminatedError（run 自然收工或其它终态）
    assert outcome.get("result") != "frozen", outcome
    lines = read_run_file(proot, "impl-x-123-a1")
    assert not any(l.get("type") == "frozen-terminated" for l in lines)


def test_frozen_precedes_cancel_and_clears_flag(tmp_path, monkeypatch):
    """7.2：frozen 检查先于 cancel 检查；frozen 命中清理残留 cancel 旗标。"""
    runner, t, outcome, proot = _spawn_polling(
        tmp_path, monkeypatch, frozen=True, cancel_requested=True)
    t.join(timeout=AGENT_TERMINATE_GRACE_SECONDS + 5)
    # frozen 优先：结果为 frozen 而非 cancelled
    assert outcome.get("result") == "frozen", outcome
    lines = read_run_file(proot, "impl-x-123-a1")
    assert not any(l.get("type") == "cancelled" for l in lines)
    # 残留 cancel 旗标被清理（防解冻后续做被残留旗标立即再终止）
    with runner._cancel_requested_lock:
        assert "impl-x-123" not in runner._cancel_requested


# ── 7.3：_frozen_hold 序列化往返与 mark_frozen_hold ───────────────


def test_frozen_hold_serialization_roundtrip(tmp_path):
    sm = _mk_sm(str(tmp_path))
    sm.add_spec("s1", {"priority": 5})
    # "True" / "False" 字符串正确转布尔、缺省 False
    sm.update_spec("s1", {FROZEN_HOLD_FIELD: True})
    assert sm.read_one("s1")[FROZEN_HOLD_FIELD] is True
    sm.update_spec("s1", {FROZEN_HOLD_FIELD: False})
    entry = sm.read_one("s1")
    assert entry[FROZEN_HOLD_FIELD] is False
    # 缺省（从未写）→ False
    sm.add_spec("s2", {"priority": 5})
    assert sm.read_one("s2").get(FROZEN_HOLD_FIELD, False) is False


def test_mark_frozen_hold_atomic_write(tmp_path):
    sm = _mk_sm(str(tmp_path))
    sm.add_spec("s1", {"priority": 5})
    sm.update_spec("s1", {"branch": "fenix/s1-123", "implementer_run": "impl-s1-1"})
    sm.transition("s1", "ready")
    sm.transition("s1", "implementing")
    sm.freeze_spec("s1", "人工冻结")
    ok = sm.mark_frozen_hold("s1", "run 因 spec 冻结被终止")
    assert ok
    entry = sm.read_one("s1")
    # 形态：_frozen_hold True + _cancelled_hold False + error；status 不改
    assert entry[FROZEN_HOLD_FIELD] is True
    assert entry["_cancelled_hold"] is False
    assert "冻结" in (entry.get("error") or "")
    assert entry.get("status") == "blocked"
    # 锚点保留
    assert entry.get("branch") == "fenix/s1-123"
    assert entry.get("implementer_run") == "impl-s1-1"


def test_cancelled_hold_and_cancelled_hold_not_both_true(tmp_path):
    sm = _mk_sm(str(tmp_path))
    sm.add_spec("s1", {"priority": 5})
    sm.transition("s1", "ready")
    sm.transition("s1", "implementing")
    sm.freeze_spec("s1", "人工冻结")
    sm.update_spec("s1", {"_cancelled_hold": True, "error": "取消保持"})
    sm.mark_frozen_hold("s1", "冻结终止")
    entry = sm.read_one("s1")
    assert entry[FROZEN_HOLD_FIELD] is True
    assert entry["_cancelled_hold"] is False
    assert not (entry[FROZEN_HOLD_FIELD] and entry["_cancelled_hold"])


def test_cancelled_hold_true_literal_count_unchanged():
    """7.3 补充：全库 core/ 下 '_cancelled_hold": True' 字面命中恰为 6 处。

    与既有 test_cancel_holdstate_recovery.py::test_no_new_holdstate_write_point_missed
    同口径（只扫 core/，不含测试自身字面量）：冻结终止 MUST 写 _frozen_hold:
    True + 清 _cancelled_hold 为 False（而非两字段同写 True）——本 SPEC 未
    新增任何 '_cancelled_hold": True' 字面写点。
    """
    repo = Path(__file__).resolve().parent.parent
    hits = 0
    for py in (repo / "core").rglob("*.py"):
        try:
            text = py.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        hits += sum(1 for ln in text.splitlines()
                    if '"_cancelled_hold": True' in ln)
    assert hits == 6, f"_cancelled_hold True 字面命中 {hits}（预期 6）"


# ── 7.4/7.5：解冻续做接线与共享判定零漂移 ────────────────────────


def _mk_resume_fixture(tmp_path, sm_name="s1"):
    """构造带 _frozen_hold + 保留分支（相对 main 有未合并提交）的 fixture。"""
    proot = Path(tmp_path) / "proj"
    proot.mkdir(parents=True, exist_ok=True)
    sm = StateMachine(proot / ".fenix" / "STATE.md", MagicMock())
    for c in (
        ["git", "-C", str(proot), "init", "-q"],
        ["git", "-C", str(proot), "config", "user.email", "t@t"],
        ["git", "-C", str(proot), "config", "user.name", "t"],
        ["git", "-C", str(proot), "checkout", "-q", "-b", "main"],
    ):
        subprocess.run(c, capture_output=True)
    (proot / "f.txt").write_text("m", encoding="utf-8")
    subprocess.run(["git", "-C", str(proot), "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", str(proot), "commit", "-q", "-m", "main"],
                   capture_output=True)
    subprocess.run(["git", "-C", str(proot), "checkout", "-q", "-b", "fenix/s1-123"],
                   capture_output=True)
    (proot / "f.txt").write_text("s1 work", encoding="utf-8")
    subprocess.run(["git", "-C", str(proot), "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", str(proot), "commit", "-q", "-m", "s1"],
                   capture_output=True)

    sm.add_spec(sm_name, {"priority": 5})
    sm.transition(sm_name, "ready")
    sm.transition(sm_name, "implementing")
    sm.update_spec(sm_name, {
        "branch": "fenix/s1-123",
        "implementer_run": "impl-s1-1",
    })
    sm.freeze_spec(sm_name, "冻结")
    sm.mark_frozen_hold(sm_name, "冻结终止")
    return proot, sm


def _mk_wt_mgr(proot, *, available: bool = True):
    wm = MagicMock()
    wm.find_worktree_by_spec = MagicMock(return_value=None)
    wm.find_branches_by_spec = MagicMock(return_value=[])
    if available:
        wm.resolve_resume_site = MagicMock(
            return_value=(proot / "wt", "fenix/s1-123"))
    else:
        wm.resolve_resume_site = MagicMock(return_value=(None, None))
    return wm


def test_unfreeze_resume_preserves_branch(tmp_path):
    proot, sm = _mk_resume_fixture(str(tmp_path))
    wm = _mk_wt_mgr(proot, available=True)
    ok = sm.unfreeze_spec("s1", status="implementing",
                          project_root=proot, worktree_manager=wm)
    assert ok
    entry = sm.read_one("s1")
    assert entry.get("status") == "implementing"
    assert entry.get("branch") == "fenix/s1-123"
    assert entry.get("implementer_run") == "impl-s1-1"
    assert entry.get("_recovery_resume") is True
    assert entry.get(FROZEN_HOLD_FIELD) is False
    assert entry.get("frozen") is False


def test_unfreeze_carrier_unavailable_keeps_anchor(tmp_path):
    """7.2（fix-relocation-writeback-layer）：载体三态不可用 MUST NOT 整体丢弃
    分支锚点——旧契约「载体不可用 → 不置 _recovery_resume」正是事故形态
    （worktree 清理 + 裸解冻 → 保留分支不再被枚举 → 6 提交实现被弃从零重做）。
    新契约：仍记录续做分支 + _recovery_resume，由 dispatch 按
    resolve_resume_site 三态重建载体。"""
    proot, sm = _mk_resume_fixture(str(tmp_path))
    wm = _mk_wt_mgr(proot, available=False)  # 载体不可用
    ok = sm.unfreeze_spec("s1", status="implementing",
                          project_root=proot, worktree_manager=wm)
    assert ok
    entry = sm.read_one("s1")
    assert entry.get(FROZEN_HOLD_FIELD) is False
    assert entry.get("branch") == "fenix/s1-123"
    assert entry.get("_recovery_resume") is True
    assert entry.get("status") == "implementing"


def test_unfreeze_no_resume_degrade(tmp_path):
    """7.4：分支不可解析/零提交（保留判定本身不通过，非载体问题）→ 清
    _frozen_hold、不置 _recovery_resume，降级落 WARNING 绝无静默。"""
    proot, sm = _mk_resume_fixture(str(tmp_path))
    # STATE.branch 指向不存在的分支 → rev-list 失败 → 保留判定不通过
    sm.update_spec("s1", {"branch": "fenix/s1-zero"})
    wm = _mk_wt_mgr(proot, available=False)
    ok = sm.unfreeze_spec("s1", status="implementing",
                          project_root=proot, worktree_manager=wm)
    assert ok
    entry = sm.read_one("s1")
    assert entry.get(FROZEN_HOLD_FIELD) is False
    assert entry.get("_recovery_resume") is not True
    assert entry.get("status") == "implementing"


def test_unfreeze_no_frozen_hold_unchanged(tmp_path):
    """7.4：无 _frozen_hold 时行为与改动前一致（回归断言）。"""
    proot = Path(tmp_path) / "proj"
    proot.mkdir(parents=True, exist_ok=True)
    sm = StateMachine(proot / ".fenix" / "STATE.md", MagicMock())
    sm.add_spec("s1", {"priority": 5})
    sm.transition("s1", "ready")
    sm.transition("s1", "implementing")
    sm.freeze_spec("s1", "人工冻结")
    ok = sm.unfreeze_spec("s1", status="implementing",
                          project_root=proot, worktree_manager=None)
    assert ok
    entry = sm.read_one("s1")
    assert entry.get("status") == "implementing"
    assert entry.get("frozen") is False
    assert entry.get(FROZEN_HOLD_FIELD) is False
    assert entry.get("_recovery_resume") is not True
    # 计数清零等既有解冻清理行为不变
    assert entry.get("error") is None


def test_shared_judgment_zero_drift(tmp_path):
    """7.5：_recovery_preserve_spec 与 unfreeze 续做经同一函数（同形结果）。"""
    proot, sm = _mk_resume_fixture(str(tmp_path))
    wm = _mk_wt_mgr(proot, available=True)
    entry = sm.read_one("s1")
    # 恢复保留路径
    recovered = sm._recovery_preserve_spec("s1", entry, proot, wm)
    assert recovered is True
    entry_r = sm.read_one("s1")
    # 重建同 fixture 再走解冻续做
    proot2, sm2 = _mk_resume_fixture(str(tmp_path) + "b")
    wm2 = _mk_wt_mgr(proot2, available=True)
    sm2.unfreeze_spec("s1", status="implementing",
                      project_root=proot2, worktree_manager=wm2)
    entry_u = sm2.read_one("s1")
    # 同形：branch 保留 + _recovery_resume True（解析出的分支一致）
    assert entry_r.get("branch") == entry_u.get("branch")
    assert entry_r.get("_recovery_resume") is True
    assert entry_u.get("_recovery_resume") is True


# ── 7.9：stale_sweep 分支保护扩展 ───────────────────────────────


def _mk_sweeper(tmp_path, states: dict):
    from core.worktree_manager import WorktreeManager

    proot = Path(tmp_path)
    wm = WorktreeManager.__new__(WorktreeManager)
    wm.project_root = proot
    wm.logger = FakeLogger()
    wm._state_reader = lambda: states
    return wm


def test_frozen_hold_branch_protected(tmp_path):
    from core.worktree_manager.stale_sweep import G7StaleSweepMixin

    wm = _mk_sweeper(tmp_path, {
        "s1": {
            "status": "blocked",
            "frozen": True,
            "_frozen_hold": True,
            "branch": "fenix/s1-123",
        },
    })
    kept, reason = G7StaleSweepMixin._branch_protected_by_state(
        wm, "fenix/s1-123")
    assert kept, f"frozen+_frozen_hold 的保留分支应受保护: {reason}"
    assert "冻结" in reason


def test_frozen_without_hold_not_protected(tmp_path):
    from core.worktree_manager.stale_sweep import G7StaleSweepMixin

    wm = _mk_sweeper(tmp_path, {
        "s1": {"status": "blocked", "frozen": True, "branch": "fenix/s1-123"},
    })
    kept, _ = G7StaleSweepMixin._branch_protected_by_state(wm, "fenix/s1-123")
    assert kept is False


def test_hold_without_frozen_not_protected(tmp_path):
    from core.worktree_manager.stale_sweep import G7StaleSweepMixin

    wm = _mk_sweeper(tmp_path, {
        "s1": {"status": "blocked", "_frozen_hold": True, "branch": "fenix/s1-123"},
    })
    kept, _ = G7StaleSweepMixin._branch_protected_by_state(wm, "fenix/s1-123")
    assert kept is False
