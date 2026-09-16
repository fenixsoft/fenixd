"""runs 保留策略用例（fix-dashboard-read-path-performance 任务 5.3）。

覆盖 spec.md「runs 产物保留上限未生效」的场景：
- 终态 run 被归档（活跃目录有界性由「终态即移出」保证）
- 运行中（running）run 不被误移
- stale 断尾尸体（末行非终态 + mtime 停更超阈值）移入归档
- 归档按 runs.keep 上限清理（最旧条目被删）
- 清理动作可观测（逐条日志含文件名）+ 单轮删除量批次上限（不静默大批量删除）
- runs.keep 缺失/非法回退缺省 50
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


def _mk(tmp_path: Path) -> Path:
    proot = tmp_path / "proj"
    (proot / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
    return proot


def _write_run(proot: Path, name: str, events) -> Path:
    p = proot / ".fenix" / "runs" / name
    p.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events), encoding="utf-8")
    return p


class TestTerminalRunArchived:
    def test_terminal_run_moved_to_archive(self, tmp_path):
        proot = _mk(tmp_path)
        _write_run(proot, "impl-spec-a-1788000000.jsonl", [{"type": "result", "result": "done"}])
        res = runs_retention_check(proot, config={"runs": {"keep": 50}})
        assert res["moved"] == 1
        runs_dir = proot / ".fenix" / "runs"
        assert (runs_dir / "archive" / "impl-spec-a-1788000000.jsonl").exists()
        assert not (runs_dir / "impl-spec-a-1788000000.jsonl").exists()

    def test_running_run_not_moved(self, tmp_path):
        proot = _mk(tmp_path)
        run_p = _write_run(
            proot, "impl-spec-b-1788000001.jsonl", [{"type": "assistant", "content": "wip"}]
        )
        res = runs_retention_check(proot, config={"runs": {"keep": 50}})
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
        res = runs_retention_check(proot, config={"runs": {"keep": 50}})
        assert res["moved"] == 1
        runs_dir = proot / ".fenix" / "runs"
        assert (runs_dir / "archive" / "impl-spec-c-1788000002.jsonl").exists()

    def test_all_terminal_types_archived(self, tmp_path):
        for i, etype in enumerate(("error", "interrupted", "cancelled", "superseded")):
            proot = _mk(tmp_path / str(i))
            _write_run(proot, f"impl-spec-{etype}-1788000003.jsonl", [{"type": etype}])
            res = runs_retention_check(proot, config={"runs": {"keep": 50}})
            assert res["moved"] == 1, f"{etype} 终态应移入归档"


def _mk_archive(proot: Path, n: int, base=1787000000):
    archive = proot / ".fenix" / "runs" / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    files = []
    for i in range(n):
        f = archive / f"impl-old-{base + i:010d}.jsonl"
        f.write_text('{"type": "result", "result": "done"}\n', encoding="utf-8")
        # mtime 单调递增，保证「最旧优先」判定确定
        ts = int(time.time()) - n * 60 + i * 60
        os.utime(f, (ts, ts))
        files.append(f)
    return archive


class TestArchiveCap:
    def _mk_archive(self, proot: Path, n: int, base=1787000000):
        return _mk_archive(proot, n, base=base)

    def test_over_cap_deletes_oldest(self, tmp_path):
        proot = _mk(tmp_path)
        archive = self._mk_archive(proot, 5)
        res = runs_retention_check(proot, config={"runs": {"keep": 2}})
        assert res["deleted"] == 3
        assert res["archive_total"] == 5
        assert res["keep"] == 2
        remaining = sorted(p.name for p in archive.glob("*.jsonl"))
        assert len(remaining) == 2, "清理后应收敛到 ≤ keep"
        # 最旧的 3 个被删（按 mtime 升序最旧优先）
        assert "impl-old-1787000003.jsonl" in remaining
        assert "impl-old-1787000004.jsonl" in remaining
        assert len(res["deleted_names"]) == 3

    def test_deleted_names_traceable_in_log(self, tmp_path):
        """5.1a：清理逐条记日志（删除数量 + 文件名可追溯）。"""
        proot = _mk(tmp_path)
        archive = self._mk_archive(proot, 3)
        log = _FakeLogger()
        res = runs_retention_check(proot, config={"runs": {"keep": 1}}, logger=log)
        assert res["deleted"] == 2
        del_msgs = [m for lvl, _c, m in log.lines if "删除归档产物" in m]
        assert len(del_msgs) == 2
        assert "impl-old-1787000000.jsonl" in del_msgs[0], "最旧条目先删，文件名可追溯"
        assert "impl-old-1787000001.jsonl" in del_msgs[1]

    def test_delete_batched_per_cycle(self, tmp_path):
        """5.1a：单轮删除量有批次上限，不静默大批量删除。"""
        proot = _mk(tmp_path)
        keep = 2
        n = keep + _RETENTION_DELETE_PER_CYCLE_MAX + 5
        archive = self._mk_archive(proot, n)
        res = runs_retention_check(proot, config={"runs": {"keep": keep}})
        assert res["deleted"] == _RETENTION_DELETE_PER_CYCLE_MAX
        assert res["archive_total"] == n
        assert len(list(archive.glob("*.jsonl"))) == n - _RETENTION_DELETE_PER_CYCLE_MAX

    def test_keep_default_when_config_missing(self, tmp_path):
        """runs.keep 缺省 50（无配置键时回退缺省，与设置页同源）。"""
        proot = _mk(tmp_path)
        self._mk_archive(proot, 60)
        res = runs_retention_check(proot)  # config=None → 内部解析（无 config.yaml → 缺省 50）
        assert res["keep"] == 50
        assert res["deleted"] == 10

    def test_keep_invalid_falls_back_default(self, tmp_path):
        proot = _mk(tmp_path)
        self._mk_archive(proot, 60)
        res = runs_retention_check(proot, config={"runs": {"keep": 0}})
        assert res["keep"] == 50, "非法 keep（<1）回退缺省 50"
        res2 = runs_retention_check(proot, config={"runs": {"keep": "abc"}})
        assert res2["keep"] == 50


class TestNoop:
    def test_missing_runs_dir_noop(self, tmp_path):
        proot = tmp_path / "noproj"
        res = runs_retention_check(proot, config={"runs": {"keep": 5}})
        assert res["moved"] == 0
        assert res["deleted"] == 0
        assert res["archive_total"] == 0

    def test_under_cap_no_delete(self, tmp_path):
        proot = _mk(tmp_path)
        archive = _mk_archive(proot, 3)
        res = runs_retention_check(proot, config={"runs": {"keep": 10}})
        assert res["deleted"] == 0
        assert len(list(archive.glob("*.jsonl"))) == 3