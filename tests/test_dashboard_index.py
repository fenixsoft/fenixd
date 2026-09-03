"""
Tests for dashboard spec summary index, config signature cache, and cleanup throttle
(dashboard-spec-summary-index capability).
"""
import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.dashboard import data as dash_data
from core.dashboard.data import SummaryIndex


# ── 辅助：构造一个可用的 Fenixd 项目目录 ──────────────────────────────

def make_project(tmp_path: Path, name: str = "proj-a") -> Path:
    proot = tmp_path / name
    (proot / ".fenix" / "logs").mkdir(parents=True, exist_ok=True)
    (proot / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
    (proot / ".fenix" / "verify-progress" / "myspec" / "screenshots").mkdir(parents=True, exist_ok=True)
    (proot / "openspec" / "changes" / "myspec" / "specs").mkdir(parents=True, exist_ok=True)
    (proot / "openspec" / "changes" / "otherspec" / "specs").mkdir(parents=True, exist_ok=True)

    (proot / "STATE.md").write_text(
        "# Fenix Project State\n\n## Specs\n\n"
        "### myspec\n- status: testing\n- priority: 2\n- created: 2026-01-01T00:00:00+00:00\n"
        "- updated: 2026-01-02T00:00:00+00:00\n- error: null\n- depends_on: null\n\n"
        "### otherspec\n- status: done\n- priority: 1\n- created: 2026-02-01T00:00:00+00:00\n"
        "- updated: 2026-02-02T00:00:00+00:00\n- error: null\n- depends_on: null\n",
        encoding="utf-8",
    )
    (proot / ".fenix" / "config.yaml").write_text("project:\n  name: fake\n", encoding="utf-8")

    (proot / "openspec" / "changes" / "myspec" / "tasks.md").write_text(
        "## 1. 阶段一\n\n"
        "- [x] 1.1 任务一\n"
        "- [ ] 1.2 任务二\n\n"
        "## 2. 阶段二\n\n"
        "- [ ] 2.1 任务三\n",
        encoding="utf-8",
    )
    (proot / "openspec" / "changes" / "myspec" / "specs" / "spec.md").write_text(
        "## ADDED Requirements\n\n### Requirement: 功能\n\n"
        "#### Scenario: 场景一\n- **WHEN** x\n- **THEN** y\n",
        encoding="utf-8",
    )
    (proot / "openspec" / "changes" / "otherspec" / "tasks.md").write_text(
        "## 1. 完成\n\n- [x] 1.1 任务一\n",
        encoding="utf-8",
    )
    (proot / "openspec" / "changes" / "otherspec" / "specs" / "spec.md").write_text(
        "## ADDED Requirements\n\n#### Scenario: 场景二\n- **WHEN** a\n- **THEN** b\n",
        encoding="utf-8",
    )
    # 验证产物
    (proot / ".fenix" / "verify-progress" / "myspec.json").write_text(
        json.dumps({"total": 3, "done": 1, "current": "场景二"}), encoding="utf-8"
    )
    return proot


def _state_sig(proot: Path):
    return dash_data._stat_sig(proot / "STATE.md")


class TestSummaryIndex:
    def test_unchanged_hits_cache_zero_reads(self, tmp_path):
        proot = make_project(tmp_path)
        idx = SummaryIndex()
        first = idx.get(proot)
        names = {s["name"] for s in first}
        assert names == {"myspec", "otherspec"}

        calls = {"n": 0}
        orig = dash_data.spec_summary

        def counting(proot_, spec_name_, entry_):
            calls["n"] += 1
            return orig(proot_, spec_name_, entry_)

        dash_data.spec_summary = counting
        try:
            second = idx.get(proot)
        finally:
            dash_data.spec_summary = orig
        assert calls["n"] == 0, "未变化时第二次请求应直接命中缓存，不重算任何 spec"
        assert second == first

    def test_single_spec_change_recomputes_only_that_spec(self, tmp_path):
        proot = make_project(tmp_path)
        idx = SummaryIndex()
        idx.get(proot)

        calls = []
        orig = dash_data.spec_summary

        def tracking(proot_, spec_name_, entry_):
            calls.append(spec_name_)
            return orig(proot_, spec_name_, entry_)

        tasks = proot / "openspec" / "changes" / "myspec" / "tasks.md"
        # 等长改写：强制推进 mtime，避免同长度写入落在同一 mtime_ns 粒度内
        time.sleep(0.01)
        os.utime(tasks, ns=(tasks.stat().st_atime_ns, tasks.stat().st_mtime_ns + 1_000_000))
        tasks.write_text(
            tasks.read_text(encoding="utf-8").replace("- [ ] 1.2 任务二", "- [x] 1.2 任务二"),
            encoding="utf-8",
        )
        dash_data.spec_summary = tracking
        try:
            items = idx.get(proot)
        finally:
            dash_data.spec_summary = orig
        assert calls == ["myspec"], "仅变更的 spec 应被重算，其余 N-1 个命中缓存"
        myspec = next(s for s in items if s["name"] == "myspec")
        assert myspec["task_done"] == 2
        assert myspec["task_total"] == 3

    def test_state_change_full_rebuild(self, tmp_path):
        proot = make_project(tmp_path)
        idx = SummaryIndex()
        idx.get(proot)

        # STATE.md 新增一个 spec 条目 → 全量重建
        state_path = proot / "STATE.md"
        state_path.write_text(
            state_path.read_text(encoding="utf-8").replace(
                "### otherspec",
                "### newspec\n- status: ready\n- priority: 3\n- created: 2026-03-01T00:00:00+00:00\n"
                "- updated: 2026-03-02T00:00:00+00:00\n- error: null\n- depends_on: null\n\n"
                "### otherspec",
            ),
            encoding="utf-8",
        )
        items = idx.get(proot)
        names = {s["name"] for s in items}
        assert names == {"myspec", "otherspec", "newspec"}

    def test_spec_deleted_removed_from_index(self, tmp_path):
        proot = make_project(tmp_path)
        idx = SummaryIndex()
        idx.get(proot)
        state_path = proot / "STATE.md"
        state_path.write_text(
            state_path.read_text(encoding="utf-8").replace(
                "### otherspec\n- status: done\n- priority: 1\n- created: 2026-02-01T00:00:00+00:00\n"
                "- updated: 2026-02-02T00:00:00+00:00\n- error: null\n- depends_on: null\n",
                "",
            ),
            encoding="utf-8",
        )
        items = idx.get(proot)
        names = {s["name"] for s in items}
        assert names == {"myspec"}

    def test_run_file_change_recomputes_that_spec(self, tmp_path):
        proot = make_project(tmp_path)
        idx = SummaryIndex()
        idx.get(proot)
        run_file = proot / ".fenix" / "runs" / "impl-myspec-1780000000.jsonl"
        run_file.write_text(
            json.dumps({"type": "result", "result": "ok"}) + "\n", encoding="utf-8"
        )
        calls = []
        orig = dash_data.spec_summary

        def tracking(proot_, spec_name_, entry_):
            calls.append(spec_name_)
            return orig(proot_, spec_name_, entry_)

        dash_data.spec_summary = tracking
        try:
            idx.get(proot)
        finally:
            dash_data.spec_summary = orig
        assert calls == ["myspec"]


class TestConfigCache:
    def test_config_cache_hit_skips_yaml_parse(self, tmp_path):
        proot = make_project(tmp_path)
        first = dash_data.read_effective_config(proot)
        assert first["description"] == ""

        yaml_calls = {"n": 0}
        orig_safe_load = dash_data.yaml.safe_load

        def counting(*a, **kw):
            yaml_calls["n"] += 1
            return orig_safe_load(*a, **kw)

        dash_data.yaml.safe_load = counting
        try:
            second = dash_data.read_effective_config(proot)
        finally:
            dash_data.yaml.safe_load = orig_safe_load
        assert second == first
        assert yaml_calls["n"] == 0, "缓存命中不应触发任何 YAML 解析"

    def test_config_write_naturally_invalidates(self, tmp_path):
        proot = make_project(tmp_path)
        dash_data.read_effective_config(proot)
        # 断言缓存有 1 个键（项目配置），写后 mtime 变化 → 键自然失效
        proj_path = proot / ".fenix" / "config.yaml"
        sig_before = dash_data._config_file_sig(proj_path)
        dash_data.write_config(proot, {"description": "新简介"}, scope="project")
        sig_after = dash_data._config_file_sig(proj_path)
        assert sig_after != sig_before
        cfg = dash_data.read_effective_config(proot)
        assert cfg["description"] == "新简介"

    def test_read_spec_mode_cache_hit(self, tmp_path):
        proot = make_project(tmp_path)
        assert dash_data.spec_summary(proot, "myspec", {"status": "testing"})["mode"] == "full"
        # 未挂 .openspec.yaml → 默认 full；再次读取经缓存
        from core.openspec_mode import read_spec_mode, _SPEC_MODE_CACHE
        assert read_spec_mode(proot, "myspec") == "full"
        before = dict(_SPEC_MODE_CACHE)
        assert read_spec_mode(proot, "myspec") == "full"
        assert _SPEC_MODE_CACHE == before, "第二次读取应命中缓存（键不变）"
