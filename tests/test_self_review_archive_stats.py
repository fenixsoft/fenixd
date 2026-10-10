"""self-review-runs-archive-stats 测试：归档目录并集统计。

对应 tasks：
- 2.1 归档目录内窗口内完成 run 计入 total/succeeded
- 2.2 当前目录（在飞）与归档跨窗口 run 的窗口归属判定正确，同 run_id 去重生效
- 2.3 归档目录内 review-<date> 产物被排除；archive 目录缺失时行为与现状一致
- 2.4 回归（既有 collect_runs_stats 用例只造顶层目录，并集不得改变其结论）

背景（evo-self-review-runs-archive-stats）：每日自省 run 统计只统计
.fenix/runs/ 当前目录、不读归档，终态 run 一旦归档即从窗口统计消失。
本测试锁定「当前目录 + 归档目录」并集口径与同 run_id 去重（当前目录优先）。
"""

import json
from datetime import datetime

from core.self_review import (
    _collect_run_files,
    collect_failed_run_samples,
    collect_runs_stats,
)


def _line(**kw):
    """构造单行 run 产物事件。"""
    return dict(kw)


def _make_run(proot, run_id, lines, in_archive=False):
    """写入一条 run 产物；in_archive=True 时落入 runs/archive/。"""
    base = proot / ".fenix" / "runs" / ("archive" if in_archive else "")
    p = base / f"{run_id}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "".join(json.dumps(l, ensure_ascii=False) + "\n" for l in lines),
        encoding="utf-8",
    )
    return p


class TestCollectRunFilesUnion:
    """并集文件集合：当前目录 + 归档目录，同 run_id 当前目录优先去重。"""

    def test_archive_missing_falls_back_to_current_only(self, tmp_path):
        """archive 目录不存在 → 仅当前目录文件。"""
        root = tmp_path / "proj"
        root.mkdir()
        _make_run(root, "impl-a-1", [_line(type="result", result="ok")])
        files = _collect_run_files(root / ".fenix" / "runs")
        assert [f.stem for f in files] == ["impl-a-1"]

    def test_union_includes_both_dirs(self, tmp_path):
        """当前目录 + 归档目录文件并入同一集合。"""
        root = tmp_path / "proj"
        root.mkdir()
        _make_run(root, "impl-cur-1", [_line(type="result", result="ok")])
        _make_run(root, "impl-arc-1", [_line(type="result", result="ok")], in_archive=True)
        files = _collect_run_files(root / ".fenix" / "runs")
        stems = {f.stem for f in files}
        assert stems == {"impl-cur-1", "impl-arc-1"}

    def test_dedup_current_wins(self, tmp_path):
        """同 run_id 两目录同存 → 去重且当前目录优先。"""
        root = tmp_path / "proj"
        root.mkdir()
        cur = _make_run(root, "impl-same-1", [_line(type="result", result="ok")])
        arc = _make_run(
            root, "impl-same-1", [_line(type="result", result="SPEC 内容缺失")], in_archive=True
        )
        files = _collect_run_files(root / ".fenix" / "runs")
        assert len(files) == 1
        assert files[0] == cur
        assert files[0] != arc


class TestCollectRunsStatsArchive:
    """2.1/2.2：归档并集统计的窗口归属与去重。"""

    def _stats(self, root):
        return collect_runs_stats(root, datetime(2000, 1, 1, 0, 0).astimezone())

    def test_archived_in_window_run_counted(self, tmp_path):
        """归档目录内窗口内完成 run 计入 total/succeeded。"""
        root = tmp_path / "proj"
        root.mkdir()
        # 窗口起点 2000-01-01 00:00，_in_window 上界为函数入口 now 快照
        # （真实当前时间），故任何写入文件均落在窗口内。
        _make_run(root, "impl-archived-ok-1", [
            _line(type="result", result="任务完成，验证通过", num_turns=4),
        ], in_archive=True)
        stats = self._stats(root)
        assert stats["total"] == 1
        assert stats["succeeded"] == 1

    def test_archived_failed_run_counted_failed(self, tmp_path):
        """归档目录内失败 run 计入 failed（计数与状态分类与归档一致）。"""
        root = tmp_path / "proj"
        root.mkdir()
        _make_run(root, "impl-archived-bad-1", [
            _line(type="result", result="SPEC 内容缺失，无法实现", num_turns=1),
        ], in_archive=True)
        stats = self._stats(root)
        assert stats["failed"] == 1
        assert stats["succeeded"] == 0

    def test_cross_window_attribution_current_vs_archive(self, tmp_path, monkeypatch):
        """当前目录与归档跨窗口 run 归属判定一致（run_id 内嵌时间戳）。"""
        root = tmp_path / "proj"
        root.mkdir()
        # run_id 内嵌时间戳（本地时区 fromtimestamp 口径）决定窗口归属
        ts_in = int(datetime(2000, 1, 1, 0, 0, 1).timestamp())   # 窗口内
        ts_out = int(datetime(2000, 1, 1, 0, 0, 0).timestamp()) - 1  # 窗口外
        _make_run(root, f"impl-inflight-{ts_out}", [
            _line(type="result", result="ok", num_turns=1),
        ])
        _make_run(root, f"impl-archived-in-{ts_in}", [
            _line(type="result", result="ok", num_turns=1),
        ], in_archive=True)
        _make_run(root, f"impl-archived-out-{ts_out}", [
            _line(type="result", result="ok", num_turns=1),
        ], in_archive=True)

        import core.self_review as sr

        # 冻结 now：窗口 [2000-01-01 00:00:00, 2000-01-01 00:00:10]（本地墙钟；
        # 批① aware 接缝——now_utc 注入同一瞬时的 aware 值）
        monkeypatch.setattr(
            sr, "now_utc", lambda: datetime(2000, 1, 1, 0, 0, 10).astimezone()
        )
        stats = collect_runs_stats(root, datetime(2000, 1, 1, 0, 0).astimezone())
        # 当前目录窗口外 run（ts_out）不计入；归档目录 +1s run（ts_in）计入；
        # 归档目录窗口外 run（ts_out）不计入 → 只计 1
        assert stats["total"] == 1
        assert stats["succeeded"] == 1

    def test_dedup_between_current_and_archive(self, tmp_path):
        """同 run_id 当前目录与归档同存 → 只计一次（当前目录优先）。"""
        root = tmp_path / "proj"
        root.mkdir()
        # 当前目录副本失败、归档副本成功：当前目录优先 → 计为 failed 且 total=1
        _make_run(root, "impl-dup-1", [
            _line(type="result", result="SPEC 内容缺失", num_turns=1),
        ])
        _make_run(root, "impl-dup-1", [
            _line(type="result", result="任务完成", num_turns=4),
        ], in_archive=True)
        stats = self._stats(root)
        assert stats["total"] == 1
        assert stats["failed"] == 1
        assert stats["succeeded"] == 0


class TestArchiveReviewExclusionAndMissing:
    """2.3：归档侧 review- 前缀排除不回归；archive 缺失退化为仅当前目录。"""

    def test_archived_review_excluded(self, tmp_path):
        """归档目录内 review-<date> 产物被排除（自省不审视自身）。"""
        root = tmp_path / "proj"
        root.mkdir()
        _make_run(root, "review-2026-09-20", [
            _line(type="result", result="ok", num_turns=2),
        ], in_archive=True)
        _make_run(root, "impl-arc-1", [
            _line(type="result", result="ok", num_turns=2),
        ], in_archive=True)
        stats = collect_runs_stats(root, datetime(2000, 1, 1, 0, 0).astimezone())
        assert stats["total"] == 1
        assert stats["succeeded"] == 1

    def test_spec_review_prefix_still_included(self, tmp_path):
        """spec-review-/code-review- 前缀（区别于 review-）仍计入。"""
        root = tmp_path / "proj"
        root.mkdir()
        _make_run(root, "spec-review-1", [
            _line(type="result", result="ok", num_turns=2),
        ], in_archive=True)
        _make_run(root, "code-review-2", [
            _line(type="result", result="ok", num_turns=2),
        ], in_archive=True)
        stats = collect_runs_stats(root, datetime(2000, 1, 1, 0, 0).astimezone())
        assert stats["total"] == 2

    def test_missing_archive_current_only(self, tmp_path):
        """archive 目录缺失 → 行为与现状一致（仅当前目录）。"""
        root = tmp_path / "proj"
        root.mkdir()
        _make_run(root, "impl-cur-1", [
            _line(type="result", result="ok", num_turns=2),
        ])
        stats = collect_runs_stats(root, datetime(2000, 1, 1, 0, 0).astimezone())
        assert stats["total"] == 1
        assert stats["succeeded"] == 1

    def test_no_runs_dir_returns_zero(self, tmp_path):
        """runs 目录缺失 → 全零（与现状一致）。"""
        root = tmp_path / "proj"
        root.mkdir()
        stats = collect_runs_stats(root, datetime(2000, 1, 1, 0, 0).astimezone())
        assert stats == {
            "total": 0,
            "succeeded": 0,
            "failed": 0,
            "instant_hang": 0,
            "timeout": 0,
            "dropped": 0,
            "running": 0,
            # evo-fix-self-review-phantom-running 1.2：新桶位预先入 dict
            # （弃置/重试件 / 其他终态 / 无终态残留）
            "superseded": 0,
            "ended": 0,
            "stale": 0,
        }


class TestCollectFailedRunSamplesArchive:
    """1.4 同口径：失败样本与计数同源（计数含归档、样本亦含归档）。"""

    def test_archived_failed_sample_included(self, tmp_path):
        """归档目录失败 run 入选失败样本（计数与样本同源）。"""
        root = tmp_path / "proj"
        root.mkdir()
        _make_run(root, "impl-arc-bad-1", [
            _line(type="result", result="SPEC 内容缺失，无法实现", num_turns=1),
        ], in_archive=True)
        samples = collect_failed_run_samples(root, datetime(2000, 1, 1, 0, 0).astimezone())
        assert len(samples) == 1
        assert samples[0]["run_id"] == "impl-arc-bad-1"
        assert samples[0]["detail"].startswith("marker=")

    def test_archived_review_excluded_from_samples(self, tmp_path):
        """归档目录 review- 产物不入失败样本。"""
        root = tmp_path / "proj"
        root.mkdir()
        _make_run(root, "review-2026-09-20", [
            _line(type="result", result="SPEC 内容缺失", num_turns=1),
        ], in_archive=True)
        samples = collect_failed_run_samples(root, datetime(2000, 1, 1, 0, 0).astimezone())
        assert samples == []

    def test_dedup_in_samples(self, tmp_path):
        """同 run_id 两目录同存 → 样本去重（当前目录优先）。"""
        root = tmp_path / "proj"
        root.mkdir()
        _make_run(root, "impl-dup-s-1", [
            _line(type="result", result="预算耗尽", num_turns=1),
        ])
        _make_run(root, "impl-dup-s-1", [
            _line(type="result", result="任务完成", num_turns=4),
        ], in_archive=True)
        samples = collect_failed_run_samples(root, datetime(2000, 1, 1, 0, 0).astimezone())
        assert len(samples) == 1
        assert samples[0]["run_id"] == "impl-dup-s-1"
        assert samples[0]["detail"].startswith("marker=")

    def test_missing_archive_samples_current_only(self, tmp_path):
        """archive 目录缺失 → 失败样本仅当前目录（与现状一致）。"""
        root = tmp_path / "proj"
        root.mkdir()
        _make_run(root, "impl-cur-bad-1", [
            _line(type="result", result="SPEC 内容缺失", num_turns=1),
        ])
        samples = collect_failed_run_samples(root, datetime(2000, 1, 1, 0, 0).astimezone())
        assert len(samples) == 1
        assert samples[0]["run_id"] == "impl-cur-bad-1"
