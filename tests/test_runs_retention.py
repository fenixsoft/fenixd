"""runs 保留策略用例（fix-dashboard-read-path-performance 5.3 + fix-run-cleanup-attach-spec-archive 2.3）。

覆盖：
- 终态 run 被归档（活跃目录有界性由「终态即移出」保证）
- 运行中（running）run 不被误移
- stale 断尾尸体（末行非终态 + mtime 停更超阈值）移入归档
- 无主车道归档产物天龄兜底（runs.keep 已取消）：超龄删 / 未超龄留 /
  活跃 SPEC 超龄留 / 活跃集扫描失败 fail-closed 不删 / 批次上限
- 清理动作可观测（逐条日志含文件名）
- config 残留 runs.keep 死键对行为零影响
"""
import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.dashboard.data import runs_retention_check
from core.dashboard.data.runs import (
    _LANE_RUN_RETENTION_DAYS,
    _RETENTION_DELETE_PER_CYCLE_MAX,
    _RUN_STALE_SECONDS,
)


class _FakeLogger:
    """记录 retention 日志行的假 logger（对齐 fenixd Logger 的 info/warning 签名）。"""

    def __init__(self):
        self.lines = []

    def info(self, component, msg):
        self.lines.append(("info", component, msg))

    def warning(self, component, msg):
        self.lines.append(("warning", component, msg))


def _mk(tmp_path: Path, active_specs=("foo",), changes_missing: bool = False) -> Path:
    proot = tmp_path / "proj"
    (proot / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
    (proot / "spec" / "changes").mkdir(parents=True, exist_ok=True)
    for s in active_specs:
        (proot / "spec" / "changes" / s).mkdir(parents=True, exist_ok=True)
    if changes_missing:
        (proot / "spec" / "changes").rmdir()
    return proot


def _write_run(proot: Path, name: str, events) -> Path:
    p = proot / ".fenix" / "runs" / name
    p.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events), encoding="utf-8")
    return p


def _mk_archive_file(proot: Path, name: str, age_days: float) -> Path:
    archive = proot / ".fenix" / "runs" / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    f = archive / name
    f.write_text('{"type": "result", "result": "done"}\n', encoding="utf-8")
    ts = time.time() - age_days * 86400
    os.utime(f, (ts, ts))
    return f


class TestTerminalRunArchived:
    def test_terminal_run_moved_to_archive(self, tmp_path):
        proot = _mk(tmp_path)
        _write_run(proot, "impl-spec-a-1788000000.jsonl", [{"type": "result", "result": "done"}])
        res = runs_retention_check(proot)
        assert res["moved"] == 1
        runs_dir = proot / ".fenix" / "runs"
        assert (runs_dir / "archive" / "impl-spec-a-1788000000.jsonl").exists()
        assert not (runs_dir / "impl-spec-a-1788000000.jsonl").exists()

    def test_running_run_not_moved(self, tmp_path):
        proot = _mk(tmp_path)
        run_p = _write_run(
            proot, "impl-spec-b-1788000001.jsonl", [{"type": "assistant", "content": "wip"}]
        )
        res = runs_retention_check(proot)
        assert res["moved"] == 0
        assert run_p.exists(), "运行中 run 不得移入归档"

    def test_stale_run_moved_to_archive(self, tmp_path):
        """stale 断尾尸体（末行非终态 + mtime 停更超阈值）视为不可复活，移入归档。"""
        proot = _mk(tmp_path)
        run_p = _write_run(
            proot, "impl-spec-c-1788000002.jsonl", [{"type": "assistant", "content": "zombie"}]
        )
        stale_ts = int(time.time() - _RUN_STALE_SECONDS - 10)
        os.utime(run_p, (stale_ts, stale_ts))
        res = runs_retention_check(proot)
        assert res["moved"] == 1
        runs_dir = proot / ".fenix" / "runs"
        assert (runs_dir / "archive" / "impl-spec-c-1788000002.jsonl").exists()

    def test_all_terminal_types_archived(self, tmp_path):
        for i, etype in enumerate(("error", "interrupted", "cancelled", "superseded")):
            proot = _mk(tmp_path / str(i))
            _write_run(proot, f"impl-spec-{etype}-1788000003.jsonl", [{"type": etype}])
            res = runs_retention_check(proot)
            assert res["moved"] == 1, f"{etype} 终态应移入归档"


class TestOrphanAgeFallback:
    """无主车道归档产物天龄兜底（fix-run-cleanup-attach-spec-archive 2.3）。"""

    def test_orphan_overage_deleted(self, tmp_path):
        proot = _mk(tmp_path, active_specs=("foo",))
        victim = _mk_archive_file(proot, "code-fix-lane1-1788000000.jsonl", age_days=_LANE_RUN_RETENTION_DAYS + 1)
        log = _FakeLogger()
        res = runs_retention_check(proot, logger=log)
        assert res["deleted"] == 1
        assert not victim.exists()
        assert res["archive_total"] == 1
        del_msgs = [m for lvl, _c, m in log.lines if "删除无主归档产物" in m]
        assert len(del_msgs) == 1
        assert "code-fix-lane1-1788000000.jsonl" in del_msgs[0], "文件名可追溯"

    def test_orphan_under_age_kept(self, tmp_path):
        proot = _mk(tmp_path, active_specs=("foo",))
        keep_p = _mk_archive_file(proot, "code-fix-lane2-1788000001.jsonl", age_days=_LANE_RUN_RETENTION_DAYS - 1)
        res = runs_retention_check(proot)
        assert res["deleted"] == 0
        assert keep_p.exists(), "未超龄无主产物保留"

    def test_active_spec_overage_kept(self, tmp_path):
        proot = _mk(tmp_path, active_specs=("foo",))
        keep_p = _mk_archive_file(proot, "impl-foo-1788000002-a1.jsonl", age_days=30)
        res = runs_retention_check(proot)
        assert res["deleted"] == 0
        assert keep_p.exists(), "活跃 SPEC 归档产物只由 SPEC 归档清理，兜底不碰"

    def test_archived_spec_not_in_active_set(self, tmp_path):
        """spec/archive/ 已归档 SPEC 不计入活跃集——残留产物按无主天龄清理。"""
        proot = _mk(tmp_path, active_specs=("foo",))
        # 目录在 spec/archive/ 下（非 spec/changes/），视为已归档 SPEC
        (proot / "spec" / "archive" / "done-spec").mkdir(parents=True, exist_ok=True)
        victim = _mk_archive_file(proot, "impl-done-spec-1788000003-a1.jsonl", age_days=_LANE_RUN_RETENTION_DAYS + 1)
        res = runs_retention_check(proot)
        assert res["deleted"] == 1
        assert not victim.exists()

    def test_changes_scan_fail_closed_deletes_nothing(self, tmp_path):
        """spec/changes/ 扫描失败 fail-closed：不删任何文件，仅记 WARNING。"""
        proot = _mk(tmp_path, active_specs=(), changes_missing=True)
        (proot / "spec" / "changes").write_text("not a dir", encoding="utf-8")
        a = _mk_archive_file(proot, "code-fix-lane3-1788000004.jsonl", age_days=_LANE_RUN_RETENTION_DAYS + 5)
        b = _mk_archive_file(proot, "admin-global-1788000005.jsonl", age_days=_LANE_RUN_RETENTION_DAYS + 5)
        log = _FakeLogger()
        res = runs_retention_check(proot, logger=log)
        assert res["deleted"] == 0
        assert a.exists() and b.exists(), "fail-closed：活跃集未知时零删除"
        warn_msgs = [m for lvl, _c, m in log.lines if lvl == "warning" and "跳过无主产物兜底" in m]
        assert len(warn_msgs) == 1

    def test_missing_changes_dir_fail_closed(self, tmp_path):
        """spec/changes/ 整目录缺失同样 fail-closed（无法证明无主）。"""
        proot = _mk(tmp_path, active_specs=(), changes_missing=True)
        victim = _mk_archive_file(proot, "code-review-1788000006.jsonl", age_days=_LANE_RUN_RETENTION_DAYS + 5)
        res = runs_retention_check(proot)
        assert res["deleted"] == 0
        assert victim.exists()

    def test_delete_batched_per_cycle(self, tmp_path):
        """单轮删除量有批次上限，不静默大批量删除（5.1a 语义沿用）。"""
        proot = _mk(tmp_path, active_specs=("foo",))
        n = _RETENTION_DELETE_PER_CYCLE_MAX + 5
        for i in range(n):
            _mk_archive_file(proot, f"code-fix-bulk-{1788001000 + i}.jsonl", age_days=_LANE_RUN_RETENTION_DAYS + 1)
        res = runs_retention_check(proot)
        assert res["deleted"] == _RETENTION_DELETE_PER_CYCLE_MAX
        assert res["archive_total"] == n
        remaining = len(list((proot / ".fenix" / "runs" / "archive").glob("*.jsonl")))
        assert remaining == n - _RETENTION_DELETE_PER_CYCLE_MAX

    def test_config_residual_keep_key_no_effect(self, tmp_path):
        """config 残留 runs.keep 死键对行为零影响（runs.keep 已取消，返回无 keep 键）。"""
        proot = _mk(tmp_path, active_specs=("foo",))
        orphan = _mk_archive_file(proot, "code-fix-lane4-1788000007.jsonl", age_days=_LANE_RUN_RETENTION_DAYS + 1)
        active = _mk_archive_file(proot, "impl-foo-1788000008-a1.jsonl", age_days=30)
        res = runs_retention_check(proot, config={"runs": {"keep": 0}})
        assert "keep" not in res, "keep 键已从返回契约移除"
        assert res["deleted"] == 1
        assert not orphan.exists()
        assert active.exists()
        # keep 值不影响删除量：再跑一轮（无更多超龄无主产物）deleted == 0
        res2 = runs_retention_check(proot, config={"runs": {"keep": 120}})
        assert res2["deleted"] == 0


class TestNoop:
    def test_missing_runs_dir_noop(self, tmp_path):
        proot = tmp_path / "noproj"
        res = runs_retention_check(proot, config={"runs": {"keep": 5}})
        assert res["moved"] == 0
        assert res["deleted"] == 0
        assert res["archive_total"] == 0
        assert "keep" not in res
