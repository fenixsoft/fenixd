"""add-freeze-stop-inflight-agents 单测：删除先停后删（数据层）。

覆盖：
- 7.6 running_run_ids_for_spec：全等归属（fix-x 不被 impl-fix-x-y-* 命中）、
  -a<n>/-r<n> 后缀正确剥离、末行为 frozen-terminated/cancelled/result/error
  判非在跑；末行为 superseded MUST 判仍在跑（superseded 不在
  RUN_TERMINAL_EVENT_TYPES 内——防误用 classify_run 口径）。
- 7.7 request_spec_delete：原子写与冲突（unmanaged/daemon_down 拒绝且不写文件）。
- 7.8 soft_delete_spec 先停后删：无在跑零等待直接删除（回归）；有在跑且停止
  回调使其中止 → 删除成功；停止后仍不落终态 → 超时返回 running 且 STATE/目录不变。
"""
import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.dashboard.data.admin_actions import (
    freeze_spec,
    running_run_ids_for_spec,
    request_spec_delete,
    SPEC_DELETE_REQUEST,
)
from core.dashboard.data.spec_archive import soft_delete_spec
from core.state_machine import StateMachine

TS = 1700000000

TERMINAL_SAMPLES = {
    # 末行均为 RUN_TERMINAL_EVENT_TYPES 内类型 → 判非在跑
    "result": {"type": "result", "result": "ok"},
    "cancelled": {"type": "cancelled", "reason": "user"},
    "error": {"type": "error", "error": "boom", "exit_code": 1},
    "interrupted": {"type": "interrupted", "reason": "shutdown"},
    "frozen-terminated": {"type": "frozen-terminated", "reason": "spec frozen"},
}


def _mk_project(tmp_path) -> Path:
    proot = Path(tmp_path)
    (proot / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
    (proot / "spec" / "changes").mkdir(parents=True, exist_ok=True)
    sm = StateMachine(proot / ".fenix" / "STATE.md", MagicMock())
    sm.add_spec("fix-x", {"priority": 5})
    return proot


def _write_run(proot: Path, stem: str, lines: list):
    p = proot / ".fenix" / "runs" / f"{stem}.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")


def _make_spec_dir(proot: Path, name: str = "fix-x"):
    d = proot / "spec" / "changes" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "proposal.md").write_text("# p", encoding="utf-8")


# ── 7.6：running_run_ids_for_spec 全等归属与终态判定 ─────────────


def test_full_equality_spec_attribution(tmp_path):
    proot = _mk_project(tmp_path)
    # fix-x 的在跑 run
    _write_run(proot, f"impl-fix-x-{TS}-a1", [
        {"type": "assistant", "message": {"content": []}},
        {"type": "user", "role": "user"},
    ])
    # 前缀相似的兄弟 spec impl-fix-x-y-* 不命中 fix-x
    _write_run(proot, f"impl-fix-x-y-{TS}-a1", [
        {"type": "assistant", "message": {"content": []}},
    ])
    running = running_run_ids_for_spec(proot, "fix-x")
    assert running == [f"impl-fix-x-{TS}-a1"], running


def test_suffix_stripping(tmp_path):
    proot = _mk_project(tmp_path)
    _write_run(proot, f"impl-fix-x-{TS}-a1-r2", [
        {"type": "assistant"},
    ])
    # -a<n>/-r<n> 后缀正确剥离 → 归属 fix-x
    running = running_run_ids_for_spec(proot, "fix-x")
    assert running == [f"impl-fix-x-{TS}-a1-r2"], running
    # 非该 spec（无前缀剥离后仍非全等）
    _write_run(proot, f"impl-fix-xy-{TS}-a1", [{"type": "assistant"}])
    running = running_run_ids_for_spec(proot, "fix-x")
    assert running == [f"impl-fix-x-{TS}-a1-r2"], running


def test_terminal_last_line_not_running(tmp_path):
    """末行为 result/cancelled/error/interrupted/frozen-terminated → 判非在跑。"""
    proot = _mk_project(tmp_path)
    for i, (key, line) in enumerate(TERMINAL_SAMPLES.items()):
        stem = f"impl-fix-x-{TS + i}-a1"
        _write_run(proot, stem, [{"type": "assistant"}, line])
    running = running_run_ids_for_spec(proot, "fix-x")
    assert running == [], f"全部终态 run 判非在跑，但返回 {running}"


def test_superseded_last_line_still_running(tmp_path):
    """7.6：末行为 superseded → MUST 判仍在跑（原地重试弃置，非终态）。"""
    proot = _mk_project(tmp_path)
    _write_run(proot, f"impl-fix-x-{TS}-a1", [
        {"type": "assistant"},
        {"type": "superseded", "spec": "fix-x", "timestamp": "..."},
    ])
    running = running_run_ids_for_spec(proot, "fix-x")
    assert running == [f"impl-fix-x-{TS}-a1"], (
        f"superseded 不在 RUN_TERMINAL_EVENT_TYPES 内，应判仍在跑: {running}")


# ── 7.7：request_spec_delete 原子写与冲突 ────────────────────────


def test_atomic_write_payload(tmp_path):
    proot = _mk_project(tmp_path)
    with patch("core.dashboard.data.admin_actions._hosting_state",
               return_value="managed"):
        res = request_spec_delete(proot, "fix-x", stopping=2)
    assert res.get("ok") is True, res
    req_path = proot / SPEC_DELETE_REQUEST
    assert req_path.exists()
    payload = json.loads(req_path.read_text(encoding="utf-8"))
    assert payload["spec"] == "fix-x"
    assert payload["source"] == "dashboard"
    assert payload["stopping"] == 2
    assert payload.get("created")


def test_conflict_existing_signal(tmp_path):
    proot = _mk_project(tmp_path)
    req_path = proot / SPEC_DELETE_REQUEST
    req_path.write_text(json.dumps({"spec": "fix-x", "source": "x",
                                    "created": "t"}), encoding="utf-8")
    with patch("core.dashboard.data.admin_actions._hosting_state",
               return_value="managed"):
        res = request_spec_delete(proot, "fix-x", stopping=1)
    assert res.get("conflict") is True
    assert res.get("ok") is False
    # 不覆盖既有信号
    payload = json.loads(req_path.read_text(encoding="utf-8"))
    assert payload["source"] == "x"


def test_unmanaged_rejects_no_file(tmp_path):
    proot = _mk_project(tmp_path)
    with patch("core.dashboard.data.admin_actions._hosting_state",
               return_value="unmanaged"):
        res = request_spec_delete(proot, "fix-x", stopping=1)
    assert res.get("unmanaged") is True
    assert res.get("ok") is False
    assert not (proot / SPEC_DELETE_REQUEST).exists()


def test_daemon_down_rejects_no_file(tmp_path):
    proot = _mk_project(tmp_path)
    with patch("core.dashboard.data.admin_actions._hosting_state",
               return_value="stopped"):
        res = request_spec_delete(proot, "fix-x", stopping=1)
    assert res.get("daemon_down") is True
    assert res.get("ok") is False
    assert not (proot / SPEC_DELETE_REQUEST).exists()


# ── 7.8：soft_delete_spec 先停后删 ───────────────────────────────


def test_no_running_direct_delete(tmp_path):
    """无在跑 run 时零等待直接删除（回归）。"""
    proot = _mk_project(tmp_path)
    _make_spec_dir(proot)
    result = soft_delete_spec(proot, "fix-x")
    assert result.get("found") is True
    assert result.get("running") is False
    assert result.get("archived") is True
    # STATE 条目移除、目录移入 archive
    sm = StateMachine(proot / ".fenix" / "STATE.md", MagicMock())
    assert sm.read_one("fix-x") is None
    assert not (proot / "spec" / "changes" / "fix-x").exists()


def test_stop_callback_terminates_then_delete(tmp_path):
    """有在跑 run 且停止回调使其终态 → 删除成功。"""
    proot = _mk_project(tmp_path)
    _make_spec_dir(proot)
    _write_run(proot, f"impl-fix-x-{TS}-a1", [{"type": "assistant"}])

    # 停止回调：把 run 文件追加 cancelled 终态行
    def stop_cb(run_ids):
        assert f"impl-fix-x-{TS}-a1" in run_ids
        _write_run(proot, f"impl-fix-x-{TS}-a1", [
            {"type": "assistant"},
            {"type": "cancelled", "reason": "spec 删除", "by": "admin"},
        ])

    result = soft_delete_spec(proot, "fix-x", stop_callback=stop_cb)
    assert result.get("found") is True
    assert result.get("running") is False, result
    assert result.get("archived") is True
    assert result.get("stopped") == 1


def test_timeout_still_running_no_delete(tmp_path):
    """停止后仍不落终态（模拟）→ 超时返回 running 且 STATE/目录不变。"""
    proot = _mk_project(tmp_path)
    _make_spec_dir(proot)
    _write_run(proot, f"impl-fix-x-{TS}-a1", [{"type": "assistant"}])

    # 停止回调什么都不做（run 保持非终态）→ 等待超时
    def stop_cb(run_ids):
        pass

    with patch("core.dashboard.data.spec_archive.SPEC_DELETE_STOP_WAIT_TOTAL_SECONDS",
               1):
        t0 = time.time()
        result = soft_delete_spec(proot, "fix-x", stop_callback=stop_cb)
        elapsed = time.time() - t0
    assert result.get("running") is True, result
    assert result.get("pending") == [f"impl-fix-x-{TS}-a1"], result
    # 超时窗口有界（≤2s），STATE/目录不变
    assert elapsed < 5, f"等待超时窗口异常: {elapsed}s"
    sm = StateMachine(proot / ".fenix" / "STATE.md", MagicMock())
    assert sm.read_one("fix-x") is not None
    assert (proot / "spec" / "changes" / "fix-x").exists()


def test_no_stop_callback_fallback_409(tmp_path):
    """stop_callback 缺省（None）→ 回退既有 409 拒绝语义。"""
    proot = _mk_project(tmp_path)
    _write_run(proot, f"impl-fix-x-{TS}-a1", [{"type": "assistant"}])
    result = soft_delete_spec(proot, "fix-x")
    assert result.get("running") is True
    assert result.get("error") == "spec 有进行中的运行"
    # 不改 STATE/目录
    sm = StateMachine(proot / ".fenix" / "STATE.md", MagicMock())
    assert sm.read_one("fix-x") is not None


# ── BUG-01 修复验证：freeze_spec 返回 stopped_agents 计数 ────────


def _setup_implementing_spec(tmp_path, spec_name="fix-x"):
    """创建一个处于 implementing 状态的 spec 的最小项目 fixture。"""
    proot = _mk_project(tmp_path)
    sm = StateMachine(proot / ".fenix" / "STATE.md", MagicMock())
    sm.add_spec(spec_name, {"priority": 5})
    sm.update_spec(spec_name, {"status": "implementing"})
    return proot


def test_freeze_spec_stopped_agents_counted(tmp_path):
    """BUG-01：冻结有在跑 agent 的 spec → stopped_agents 包含在跑 run 计数。"""
    proot = _setup_implementing_spec(tmp_path)
    _write_run(proot, f"impl-fix-x-{TS}-a1", [
        {"type": "assistant", "message": {"content": []}},
        {"type": "user", "role": "user"},
    ])
    result = freeze_spec(proot, "fix-x")
    assert result.get("ok") is True, result
    assert result.get("frozen") is True, result
    assert result.get("stopped_agents") == 1, result
    # freeze 后 spec 为 blocked（frozen）
    sm = StateMachine(proot / ".fenix" / "STATE.md", MagicMock())
    entry = sm.read_one("fix-x")
    assert entry.get("frozen") is True or (entry.get("error") or "").startswith("用户指令冻结：")


def test_freeze_spec_no_running_stopped_agents_zero(tmp_path):
    """BUG-01：冻结无在跑 agent 的 spec → stopped_agents 为 0。"""
    proot = _setup_implementing_spec(tmp_path)
    result = freeze_spec(proot, "fix-x")
    assert result.get("ok") is True, result
    assert result.get("frozen") is True, result
    assert result.get("stopped_agents") == 0, result


def test_freeze_spec_multiple_inflight_stopped_agents_count(tmp_path):
    """BUG-01：冻结有多个在跑 agent 的 spec → stopped_agents = 在跑 run 数。"""
    proot = _setup_implementing_spec(tmp_path)
    _write_run(proot, f"impl-fix-x-{TS}-a1", [{"type": "assistant"}])
    _write_run(proot, f"spec-review-fix-x-{TS}-a1", [{"type": "assistant"}])
    result = freeze_spec(proot, "fix-x")
    assert result.get("ok") is True, result
    assert result.get("frozen") is True, result
    assert result.get("stopped_agents") == 2, result


def test_freeze_spec_terminal_no_stopped_agents(tmp_path):
    """BUG-01：终态 spec 不可冻结 → frozen=False，stopped_agents 不出现（无需计数）。"""
    proot = _setup_implementing_spec(tmp_path)
    sm = StateMachine(proot / ".fenix" / "STATE.md", MagicMock())
    sm.update_spec("fix-x", {"status": "done"})
    result = freeze_spec(proot, "fix-x")
    assert result.get("frozen") is False, result
    assert "stopped_agents" not in result, "终态不可冻结时不应返回 stopped_agents"
