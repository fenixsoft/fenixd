"""
增量失效用例（fix-dashboard-read-path-performance 任务 1.2 / 1.4）。

- 1.2：仅 1 个 spec 变化时，其余 N-1 个 spec 命中缓存（spy 计数重算次数）。
- 1.4（关键，2.1a 的跨快照用例）：依赖文件全未变、仅 STATE.md 中该 spec 的
  条目字段（status/error/priority 等）变化 → 该 spec MUST 被重算且摘要反映
  新值。spec.md 的「缓存结果与全量重建等价」是同快照对比——两条路径读同一
  entry，即便漏了条目指纹也必然一致，故不能防住「条目变、文件没变」的陈旧
  摘要，必须由本类用例独立覆盖。
- 等价性：同一 STATE 快照上「增量路径」与「全量重建路径」产物逐条一致
  （spec.md 的 Scenario：缓存结果与全量重建等价）。
"""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.dashboard import data as dash_data
from core.dashboard.data import SummaryIndex


def make_project(tmp_path: Path, name: str = "proj-a") -> Path:
    """3-spec 夹具（myspec / otherspec / thirdspec），供「其余 N-1 个」断言。"""
    proot = tmp_path / name
    (proot / ".fenix" / "logs").mkdir(parents=True, exist_ok=True)
    (proot / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
    (proot / ".fenix" / "verify-progress" / "myspec" / "screenshots").mkdir(
        parents=True, exist_ok=True
    )
    (proot / "spec" / "changes" / "myspec" / "specs").mkdir(parents=True, exist_ok=True)
    (proot / "spec" / "changes" / "otherspec" / "specs").mkdir(parents=True, exist_ok=True)
    (proot / "spec" / "changes" / "thirdspec" / "specs").mkdir(parents=True, exist_ok=True)

    (proot / ".fenix" / "STATE.md").write_text(
        "# Fenix Project State\n\n## Specs\n\n"
        "### myspec\n- status: testing\n- priority: 2\n- created: 2026-01-01T00:00:00+00:00\n"
        "- updated: 2026-01-02T00:00:00+00:00\n- error: null\n- depends_on: null\n\n"
        "### otherspec\n- status: done\n- priority: 1\n- created: 2026-02-01T00:00:00+00:00\n"
        "- updated: 2026-02-02T00:00:00+00:00\n- error: null\n- depends_on: null\n\n"
        "### thirdspec\n- status: ready\n- priority: 3\n- created: 2026-03-01T00:00:00+00:00\n"
        "- updated: 2026-03-02T00:00:00+00:00\n- error: null\n- depends_on: null\n",
        encoding="utf-8",
    )
    (proot / ".fenix" / "config.yaml").write_text("project:\n  name: fake\n", encoding="utf-8")

    for spec, tasks_content in (
        ("myspec", "## 1. 阶段一\n\n- [x] 1.1 任务一\n- [ ] 1.2 任务二\n\n"),
        ("otherspec", "## 1. 完成\n\n- [x] 1.1 任务一\n"),
        ("thirdspec", "## 1. 准备\n\n- [ ] 1.1 任务一\n"),
    ):
        (proot / "spec" / "changes" / spec / "tasks.md").write_text(
            tasks_content, encoding="utf-8"
        )
        (proot / "spec" / "changes" / spec / "specs" / "spec.md").write_text(
            "## ADDED Requirements\n\n### Requirement: 功能\n\n"
            "#### Scenario: 场景一\n- **WHEN** x\n- **THEN** y\n",
            encoding="utf-8",
        )
    (proot / ".fenix" / "verify-progress" / "myspec.json").write_text(
        json.dumps({"total": 3, "done": 1, "current": "场景二"}), encoding="utf-8"
    )
    return proot


def _bump_mtime(path: Path) -> None:
    """显式前推 mtime 1ms：等长/同 tick 内写入可能不推进文件 mtime。"""
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))


def _rewrite_state(proot: Path, old: str, new: str) -> None:
    path = proot / ".fenix" / "STATE.md"
    content = path.read_text(encoding="utf-8")
    assert old in content, f"STATE.md 未找到待替换片段: {old!r}"
    path.write_text(content.replace(old, new), encoding="utf-8")
    _bump_mtime(path)


class TestIncrementalIndex:
    def test_single_spec_change_recomputes_only_that_spec(self, tmp_path):
        """1.2：仅 1 个 spec 变化 → 只重算它，其余 N-1 个命中缓存。"""
        proot = make_project(tmp_path)
        idx = SummaryIndex()
        idx.get(proot)

        calls = []
        orig = dash_data.spec_summary

        def tracking(proot_, spec_name_, entry_, **kw):
            calls.append(spec_name_)
            return orig(proot_, spec_name_, entry_, **kw)

        tasks = proot / "spec" / "changes" / "myspec" / "tasks.md"
        _bump_mtime(tasks)
        tasks.write_text(
            tasks.read_text(encoding="utf-8").replace("- [ ] 1.2 任务二", "- [x] 1.2 任务二"),
            encoding="utf-8",
        )
        dash_data.spec_summary = tracking
        try:
            items = idx.get(proot)
        finally:
            dash_data.spec_summary = orig
        assert calls == ["myspec"], f"仅变更的 spec 应被重算，实际重算: {calls}"
        myspec = next(s for s in items if s["name"] == "myspec")
        assert myspec["task_done"] == 2
        assert myspec["task_total"] == 2

    def test_entry_status_change_recomputes_that_spec(self, tmp_path):
        """1.4（关键）：依赖文件全未变、仅 STATE 条目 status 变化 → 重算且反映新值。"""
        proot = make_project(tmp_path)
        idx = SummaryIndex()
        first = idx.get(proot)
        assert next(s for s in first if s["name"] == "myspec")["status"] == "testing"

        # 仅 STATE.md 中 myspec 条目的 status 变化（tasks.md/specs/run 产物全未动）
        _rewrite_state(
            proot,
            "### myspec\n- status: testing",
            "### myspec\n- status: blocked",
        )
        calls = []
        orig = dash_data.spec_summary

        def tracking(proot_, spec_name_, entry_, **kw):
            calls.append(spec_name_)
            return orig(proot_, spec_name_, entry_, **kw)

        dash_data.spec_summary = tracking
        try:
            second = idx.get(proot)
        finally:
            dash_data.spec_summary = orig
        assert calls == ["myspec"], f"条目字段变化也应只重算该 spec，实际: {calls}"
        myspec = next(s for s in second if s["name"] == "myspec")
        assert myspec["status"] == "blocked", "摘要 status 必须反映新值，不得返回陈旧摘要"
        # 其余 spec 摘要不受影响（缓存命中，值不变）
        otherspec = next(s for s in second if s["name"] == "otherspec")
        assert otherspec["status"] == "done"

    def test_entry_error_change_recomputes_that_spec(self, tmp_path):
        """1.4：仅 STATE 条目 error 字段变化 → 重算且摘要 error 为新值。"""
        proot = make_project(tmp_path)
        idx = SummaryIndex()
        idx.get(proot)

        _rewrite_state(
            proot,
            "### myspec\n- status: testing\n- priority: 2\n- created: 2026-01-01T00:00:00+00:00\n"
            "- updated: 2026-01-02T00:00:00+00:00\n- error: null",
            "### myspec\n- status: testing\n- priority: 2\n- created: 2026-01-01T00:00:00+00:00\n"
            "- updated: 2026-01-02T00:00:00+00:00\n- error: budget exhausted",
        )
        calls = []
        orig = dash_data.spec_summary

        def tracking(proot_, spec_name_, entry_, **kw):
            calls.append(spec_name_)
            return orig(proot_, spec_name_, entry_, **kw)

        dash_data.spec_summary = tracking
        try:
            items = idx.get(proot)
        finally:
            dash_data.spec_summary = orig
        assert calls == ["myspec"]
        myspec = next(s for s in items if s["name"] == "myspec")
        assert myspec["error"] == "budget exhausted"

    def test_entry_priority_change_recomputes_that_spec(self, tmp_path):
        """1.4：仅 STATE 条目 priority 变化 → 重算。"""
        proot = make_project(tmp_path)
        idx = SummaryIndex()
        idx.get(proot)

        _rewrite_state(
            proot,
            "### myspec\n- status: testing\n- priority: 2",
            "### myspec\n- status: testing\n- priority: 5",
        )
        calls = []
        orig = dash_data.spec_summary

        def tracking(proot_, spec_name_, entry_, **kw):
            calls.append(spec_name_)
            return orig(proot_, spec_name_, entry_, **kw)

        dash_data.spec_summary = tracking
        try:
            items = idx.get(proot)
        finally:
            dash_data.spec_summary = orig
        assert calls == ["myspec"]
        myspec = next(s for s in items if s["name"] == "myspec")
        assert myspec["priority"] == 5

    def test_incremental_equals_full_rebuild_same_snapshot(self, tmp_path):
        """等价性：同一 STATE 快照上增量路径产物 ≡ 全量重建路径产物（逐条一致）。"""
        proot = make_project(tmp_path)
        idx = SummaryIndex()
        idx.get(proot)  # 先冷构建

        # 经历一次条目变化后得到最终快照
        _rewrite_state(
            proot,
            "### myspec\n- status: testing",
            "### myspec\n- status: blocked",
        )
        inc = idx.get(proot)
        inc_by_name = {s["name"]: s for s in inc}

        # 全量重建路径：同一快照上新索引冷构建
        full = SummaryIndex().get(proot)
        full_by_name = {s["name"]: s for s in full}

        assert set(inc_by_name) == set(full_by_name)
        for name in full_by_name:
            assert inc_by_name[name] == full_by_name[name], f"{name} 摘要增量与全量重建不一致"

    def test_get_runs_preselected_equals_glob(self, tmp_path):
        """3.1：get_runs 预选文件集路径与 glob 路径产出等价（含同 run_id 活跃优先去重）。"""
        from core.dashboard.data import _runs_by_spec_sigs, get_runs

        proot = make_project(tmp_path)
        runs_dir = proot / ".fenix" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        archive = runs_dir / "archive"
        archive.mkdir(parents=True, exist_ok=True)
        # live 与 archive 同 run_id（活跃优先）+ archive 独有旧 run
        (runs_dir / "impl-myspec-1788000000.jsonl").write_text(
            '{"type": "result", "result": "live"}\n', encoding="utf-8"
        )
        (archive / "impl-myspec-1788000000.jsonl").write_text(
            '{"type": "result", "result": "archived-dup"}\n', encoding="utf-8"
        )
        (archive / "impl-myspec-1787000000.jsonl").write_text(
            '{"type": "result", "result": "archived-old"}\n', encoding="utf-8"
        )

        runs_sigs = _runs_by_spec_sigs(proot)
        spec_files = [Path(p) for p in (runs_sigs.get("myspec") or {})]
        a = get_runs(proot, "myspec", include_archive=True, files=spec_files)
        b = get_runs(proot, "myspec", include_archive=True)
        assert [r["run_id"] for r in a] == [r["run_id"] for r in b]
        assert len(a) == 2, "同 run_id 活跃优先去重后应为 2 条（活跃 + 归档独有）"

    def test_runs_dir_glob_count_constant(self, tmp_path, monkeypatch):
        """3.2：单轮 runs 目录 glob 次数为常数（不随 spec 数量增长）。

        变化触发一轮 get()：预扫描（_runs_by_spec_sigs）glob 2 次（runs 根 +
        archive），其余 spec 摘要计算（get_runs/任务进度/存活心跳）全部复用
        预扫描文件集，不再各自 glob。
        """
        import pathlib

        proot = make_project(tmp_path)
        idx = SummaryIndex()
        idx.get(proot)  # 冷构建（不计数）

        # 归档目录存在 → 预扫描 glob 2 次（runs 根 + archive）
        archive = proot / ".fenix" / "runs" / "archive"
        archive.mkdir(parents=True, exist_ok=True)
        (archive / "impl-otherspec-1789000000.jsonl").write_text(
            '{"type": "result", "result": "archived"}\n', encoding="utf-8"
        )

        real_glob = pathlib.Path.glob
        counts = {"n": 0, "calls": []}

        def counting_glob(self, pattern):
            # 只统计 .fenix/runs 目录（含 archive 子目录）上的 glob
            if ".fenix/runs" in str(self):
                counts["n"] += 1
                counts["calls"].append((str(self), pattern))
            return real_glob(self, pattern)

        tasks = proot / "spec" / "changes" / "myspec" / "tasks.md"
        _bump_mtime(tasks)
        tasks.write_text(
            tasks.read_text(encoding="utf-8").replace("- [ ] 1.2 任务二", "- [x] 1.2 任务二"),
            encoding="utf-8",
        )
        monkeypatch.setattr(pathlib.Path, "glob", counting_glob)
        try:
            idx.get(proot)
        finally:
            monkeypatch.undo()
        assert counts["n"] == 2, (
            f"单轮目录 glob 应为常数 2（仅预扫描），实际 {counts['n']}: {counts['calls']}"
        )
