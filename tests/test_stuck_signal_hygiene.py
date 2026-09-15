"""evo-stuck-signal-hygiene 测试。

覆盖：
  - D1 进程存活反证（_detect_stuck 中 agent_runner.running_run_ids() 判定）
    包括 -r<n> 瞬态重试后缀归属正确解析（防止 run_spec_part 回退）
  - D2 merge_signal 冷却窗口去重回归（锁定既有一行一记录行为）
  - D3 处置后静默期（resolved 暂不发信号，escalated 不触发静默）
  - 5.3 已有 stuck 断言回归通过（通过 make_monitor 复用测试辅助）
"""
import json
from pathlib import Path
from time import time

import pytest

from core.admin_store import AdminStore, SIGNAL, DISPOSITION
from core.admin_monitor import AdminMonitor
from tests.helpers import FakeLogger, utcnow_iso, iso_ago


# ── helpers ─────────────────────────────────────────────────────────────────

class _FakeSM:
    def __init__(self, specs: dict):
        self._specs = specs

    def read_all(self):
        return self._specs

    def read_one(self, name):
        return self._specs.get(name)


class _FakeRunner:
    """最小 AgentRunner 替身：仅暴露 running_run_ids()。"""

    def __init__(self, running_ids: list[str]):
        self._running_ids = list(running_ids)

    def running_run_ids(self) -> list:
        return [rid for rid in self._running_ids]


def _make_monitor(tmp_path: Path, specs: dict, *,
                   config: dict | None = None,
                   runner: _FakeRunner | None = None) -> tuple[Path, AdminMonitor]:
    proot = tmp_path / "proj"
    proot.mkdir(parents=True, exist_ok=True)
    mon = AdminMonitor(
        config or {},
        _FakeSM(specs),
        proot,
        FakeLogger(),
        store=AdminStore(proot, FakeLogger()),
        agent_runner=runner,
    )
    return proot, mon


def _write_run(proot: Path, run_id: str, terminal: str = "running"):
    """写入一个 run 产物文件（jsonl）。"""
    runs_dir = proot / ".fenix" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    if terminal == "error":
        lines = [
            {"type": "system", "subtype": "init"},
            {"type": "error", "message": "boom", "num_turns": 3},
        ]
    elif terminal == "done":
        lines = [
            {"type": "system", "subtype": "init"},
            {"type": "result", "result": "完成", "num_turns": 3},
        ]
    else:
        lines = [
            {"type": "assistant",
             "message": {"content": [{"type": "text", "text": "..."}]}},
        ]
    path = runs_dir / f"{run_id}.jsonl"
    path.write_text(
        "".join(json.dumps(l, ensure_ascii=False) + "\n" for l in lines),
        encoding="utf-8",
    )
    return path


def _write_disposition(store: AdminStore, spec: str, signal_type: str,
                       result: str, created_iso: str):
    """往 store 追加一条 disposition 记录（kind=DISPOSITION）。"""
    store.append({
        "kind": DISPOSITION,
        "signal_type": signal_type,
        "spec": spec,
        "result": result,
        "created": created_iso,
    })


# ── D1 进程存活反证 ────────────────────────────────────────────────────────

class TestStuckProcessAlive:
    """task 5.1：agent_runner.running_run_ids() 命中 → 0 误报。"""

    def test_running_agent_suppresses_stuck(self, tmp_path):
        """有存活 run → 不产 stuck 信号（即使文件 mtime 陈旧/无 run 文件）。"""
        proot, mon = _make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(200)},
        }, runner=_FakeRunner(["impl-spec-a-1789398956"]))
        signals = mon.run_once()
        assert all(s["signal_type"] != "stuck" for s in signals)

    def test_no_runner_falls_back_to_file(self, tmp_path):
        """agent_runner=None → 退回文件活跃度判据（有近期 run 文件不产信号）。"""
        proot, mon = _make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(200)},
        }, runner=None)
        _write_run(proot, "impl-spec-a-1789398956", "running")
        signals = mon.run_once()
        assert all(s["signal_type"] != "stuck" for s in signals)

    def test_no_runner_no_file_still_stuck(self, tmp_path):
        """agent_runner=None + 无近期 run 文件 → 仍产 stuck 信号。"""
        _, mon = _make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(200)},
        }, runner=None)
        signals = mon.run_once()
        assert any(s["signal_type"] == "stuck" for s in signals)

    def test_real_stuck_no_running_no_file(self, tmp_path):
        """真实 stuck：无存活 run + 无文件活跃 → 产生 stuck 信号。"""
        proot, mon = _make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(200)},
        }, runner=_FakeRunner([]))
        signals = mon.run_once()
        assert any(s["signal_type"] == "stuck" for s in signals)

    def test_stale_file_but_alive_run_no_stuck(self, tmp_path):
        """转录文件停止增长（mtime 陈旧）但 agent 子进程存活 → 不判 stuck。"""
        proot, mon = _make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(200)},
        }, runner=_FakeRunner(["impl-spec-a-1789398956"]))
        # 写 run 文件后手动把 mtime 拨远（模拟转录停止增长）
        p = _write_run(proot, "impl-spec-a-1789398956", "running")
        import os
        old_time = time() - 9999  # 远超宽限
        os.utime(str(p), (old_time, old_time))
        signals = mon.run_once()
        assert all(s["signal_type"] != "stuck" for s in signals)

    def test_retry_suffix_run_suppresses_stuck(self, tmp_path):
        """run_id 带 -r<n> 瞬态重试后缀（impl-spec-a-1789398956-a1-r1）+ 文件
        mtime 陈旧 → 仍 0 误报（锁 D1 的 _spec_from_run_id 解析，
        防 run_spec_part 回退引入 8e510a87 回归）。"""
        proot, mon = _make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(200)},
        }, runner=_FakeRunner(["impl-spec-a-1789398956-a1-r1"]))
        p = _write_run(proot, "impl-spec-a-1789398956-a1-r1", "running")
        import os
        old_time = time() - 9999
        os.utime(str(p), (old_time, old_time))
        signals = mon.run_once()
        assert all(s["signal_type"] != "stuck" for s in signals)

    def test_running_run_ids_exception_falls_back(self, tmp_path):
        """running_run_ids() 抛异常 → 容错退回文件判据，不崩溃。"""
        class _ExcRunner:
            def running_run_ids(self):
                raise RuntimeError("进程表损坏")
        proot, mon = _make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(200)},
        }, runner=_ExcRunner())
        _write_run(proot, "impl-spec-a-1789398956", "running")
        signals = mon.run_once()
        # 有近期 run → 文件判据命中 → 不产 stuck
        assert all(s["signal_type"] != "stuck" for s in signals)


# ── D2 merge_signal 冷却窗口去重回归 ────────────────────────────────────────

class TestMergeSignalDedup:
    """task 2.1：冷却窗口内同 (spec, signal_type, status_hash) 重复触发
    只保留 1 条 signal 记录、只刷 last_seen（09-14 连发防回退护栏）。"""

    def test_same_hash_creates_only_one_record(self, tmp_path):
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        store = AdminStore(proot, FakeLogger())
        status_hash = "abc123"
        rec1, is_new1 = store.merge_signal(
            {"kind": SIGNAL, "signal_type": "stuck", "spec": "spec-a",
             "description": "第一次"},
            status_hash,
        )
        assert is_new1 is True
        assert rec1.get("last_seen") == rec1.get("created")
        # 第二次同 hash：不新增、只刷 last_seen
        rec2, is_new2 = store.merge_signal(
            {"kind": SIGNAL, "signal_type": "stuck", "spec": "spec-a",
             "description": "第二次"},
            status_hash,
        )
        assert is_new2 is False
        assert rec1["id"] == rec2["id"]  # 同一记录
        assert rec2["last_seen"] >= rec1["last_seen"]  # last_seen 被刷新
        assert rec2["created"] == rec1["created"]  # created 不变
        # 只有 1 条记录
        all_recs = store.read_all()
        stuck_recs = [r for r in all_recs
                      if r.get("signal_type") == "stuck" and r.get("spec") == "spec-a"]
        assert len(stuck_recs) == 1

    def test_different_hash_creates_new_record(self, tmp_path):
        """不同 status_hash → 新记录（状态变化时应产生新条目）。"""
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        store = AdminStore(proot, FakeLogger())
        rec1, is_new1 = store.merge_signal(
            {"kind": SIGNAL, "signal_type": "stuck", "spec": "spec-a"},
            "hash1",
        )
        rec2, is_new2 = store.merge_signal(
            {"kind": SIGNAL, "signal_type": "stuck", "spec": "spec-a"},
            "hash2",
        )
        assert is_new1 is True and is_new2 is True
        assert rec1["id"] != rec2["id"]
        stuck_recs = [r for r in store.read_all()
                      if r.get("signal_type") == "stuck" and r.get("spec") == "spec-a"]
        assert len(stuck_recs) == 2

    def test_different_spec_creates_new_record(self, tmp_path):
        """不同 spec → 新记录（不跨 spec 合并）。"""
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        store = AdminStore(proot, FakeLogger())
        hash_ = "samehash"
        rec1, _ = store.merge_signal(
            {"kind": SIGNAL, "signal_type": "stuck", "spec": "spec-a"}, hash_)
        rec2, _ = store.merge_signal(
            {"kind": SIGNAL, "signal_type": "stuck", "spec": "spec-b"}, hash_)
        assert rec1["id"] != rec2["id"]


# ── D3 处置后静默期 ─────────────────────────────────────────────────────────

class TestDispositionSilence:
    """task 5.2：resolved 处置后静默期内不产信号；窗口外允许；
    escalated 不触发静默。"""

    def test_resolved_within_silence_no_signal(self, tmp_path):
        """resolved 处置 30 分钟前（silence=120）→ 不产 stuck 信号。"""
        proot, mon = _make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(200)},
        }, runner=_FakeRunner([]))
        # 写入 resolved disposition 30 分钟前
        _write_disposition(
            mon.store, "spec-a", "stuck", "resolved", iso_ago(30),
        )
        signals = mon.run_once()
        assert all(s["signal_type"] != "stuck" for s in signals)

    def test_resolved_outside_silence_allows_signal(self, tmp_path):
        """resolved 处置 200 分钟前（silence=120）→ 允许产 stuck 信号。"""
        proot, mon = _make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(200)},
        }, runner=_FakeRunner([]))
        _write_disposition(
            mon.store, "spec-a", "stuck", "resolved", iso_ago(200),
        )
        signals = mon.run_once()
        assert any(s["signal_type"] == "stuck" for s in signals)

    def test_partially_resolved_triggers_silence(self, tmp_path):
        """partially-resolved 同样触发静默。"""
        proot, mon = _make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(200)},
        }, runner=_FakeRunner([]))
        _write_disposition(
            mon.store, "spec-a", "stuck", "partially-resolved", iso_ago(30),
        )
        signals = mon.run_once()
        assert all(s["signal_type"] != "stuck" for s in signals)

    def test_escalated_does_not_trigger_silence(self, tmp_path):
        """result=escalated 不触发静默——人工处置是唯一出路。"""
        proot, mon = _make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(200)},
        }, runner=_FakeRunner([]))
        _write_disposition(
            mon.store, "spec-a", "stuck", "escalated", iso_ago(30),
        )
        signals = mon.run_once()
        assert any(s["signal_type"] == "stuck" for s in signals)

    def test_failed_disposition_does_not_trigger_silence(self, tmp_path):
        """result=failed 的处置不触发静默（不在 resolved/partially-resolved 集合中）。"""
        proot, mon = _make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(200)},
        }, runner=_FakeRunner([]))
        _write_disposition(
            mon.store, "spec-a", "stuck", "failed", iso_ago(30),
        )
        signals = mon.run_once()
        assert any(s["signal_type"] == "stuck" for s in signals)

    def test_silence_disabled_when_zero(self, tmp_path):
        """stuck_silence_minutes=0 → 静默禁用，resolved 也立即允许信号。"""
        proot, mon = _make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(200)},
        }, runner=_FakeRunner([]),
           config={"admin": {"stuck_silence_minutes": 0}})
        _write_disposition(
            mon.store, "spec-a", "stuck", "resolved", iso_ago(0.5),
        )
        signals = mon.run_once()
        assert any(s["signal_type"] == "stuck" for s in signals)

    def test_disposition_for_different_spec_not_silenced(self, tmp_path):
        """另一 spec 的处置不影响当前 spec 的静默判定。"""
        proot, mon = _make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(200)},
        }, runner=_FakeRunner([]))
        _write_disposition(
            mon.store, "spec-b", "stuck", "resolved", iso_ago(30),
        )
        signals = mon.run_once()
        assert any(s["signal_type"] == "stuck" for s in signals)

    def test_disposition_for_different_signal_type_not_silenced(self, tmp_path):
        """其他 signal_type 的处置不触发 stuck 静默。"""
        proot, mon = _make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(200)},
        }, runner=_FakeRunner([]))
        _write_disposition(
            mon.store, "spec-a", "flapping", "resolved", iso_ago(30),
        )
        signals = mon.run_once()
        assert any(s["signal_type"] == "stuck" for s in signals)
