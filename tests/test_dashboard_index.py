"""
Tests for dashboard spec summary index, config signature cache, and cleanup throttle
(dashboard-spec-summary-index capability).
"""
import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.dashboard import data as dash_data
from core.dashboard.data import SummaryIndex
from core.dashboard.data import signature as sigmod
from core.dashboard.data import summary as summary_mod


# ── 辅助：构造一个可用的 Fenixd 项目目录 ──────────────────────────────

def make_project(tmp_path: Path, name: str = "proj-a") -> Path:
    proot = tmp_path / name
    (proot / ".fenix" / "logs").mkdir(parents=True, exist_ok=True)
    (proot / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
    (proot / ".fenix" / "verify-progress" / "myspec" / "screenshots").mkdir(parents=True, exist_ok=True)
    (proot / "spec" / "changes" / "myspec" / "specs").mkdir(parents=True, exist_ok=True)
    (proot / "spec" / "changes" / "otherspec" / "specs").mkdir(parents=True, exist_ok=True)

    (proot / ".fenix" / "STATE.md").write_text(
        "# Fenix Project State\n\n## Specs\n\n"
        "### myspec\n- status: testing\n- priority: 2\n- created: 2026-01-01T00:00:00+00:00\n"
        "- updated: 2026-01-02T00:00:00+00:00\n- error: null\n- depends_on: null\n\n"
        "### otherspec\n- status: done\n- priority: 1\n- created: 2026-02-01T00:00:00+00:00\n"
        "- updated: 2026-02-02T00:00:00+00:00\n- error: null\n- depends_on: null\n",
        encoding="utf-8",
    )
    (proot / ".fenix" / "config.yaml").write_text("project:\n  name: fake\n", encoding="utf-8")

    (proot / "spec" / "changes" / "myspec" / "tasks.md").write_text(
        "## 1. 阶段一\n\n"
        "- [x] 1.1 任务一\n"
        "- [ ] 1.2 任务二\n\n"
        "## 2. 阶段二\n\n"
        "- [ ] 2.1 任务三\n",
        encoding="utf-8",
    )
    (proot / "spec" / "changes" / "myspec" / "specs" / "spec.md").write_text(
        "## ADDED Requirements\n\n### Requirement: 功能\n\n"
        "#### Scenario: 场景一\n- **WHEN** x\n- **THEN** y\n",
        encoding="utf-8",
    )
    (proot / "spec" / "changes" / "otherspec" / "tasks.md").write_text(
        "## 1. 完成\n\n- [x] 1.1 任务一\n",
        encoding="utf-8",
    )
    (proot / "spec" / "changes" / "otherspec" / "specs" / "spec.md").write_text(
        "## ADDED Requirements\n\n#### Scenario: 场景二\n- **WHEN** a\n- **THEN** b\n",
        encoding="utf-8",
    )
    # 验证产物
    (proot / ".fenix" / "verify-progress" / "myspec.json").write_text(
        json.dumps({"total": 3, "done": 1, "current": "场景二"}), encoding="utf-8"
    )
    return proot


def _state_sig(proot: Path):
    return dash_data._stat_sig(proot / ".fenix" / "STATE.md")


class TestSummaryIndex:
    def test_unchanged_hits_cache_zero_reads(self, tmp_path):
        proot = make_project(tmp_path)
        idx = SummaryIndex()
        first = idx.get(proot)
        names = {s["name"] for s in first}
        assert names == {"myspec", "otherspec"}

        calls = {"n": 0}
        orig = dash_data.spec_summary

        def counting(proot_, spec_name_, entry_, **kw):
            calls["n"] += 1
            return orig(proot_, spec_name_, entry_, **kw)

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

        def tracking(proot_, spec_name_, entry_, **kw):
            calls.append(spec_name_)
            return orig(proot_, spec_name_, entry_, **kw)

        tasks = proot / "spec" / "changes" / "myspec" / "tasks.md"
        # 等长改写：显式推进 mtime，避免同长度写入落在同一 mtime_ns 粒度内
        # （os.utime 已保证 mtime 前进，无需真实 sleep 等待时钟）
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

    def test_state_change_add_spec_recomputes_only_new(self, tmp_path):
        """STATE.md 新增一个 spec 条目 → 仅新 spec 被重算，其余命中缓存（增量失效）。"""
        proot = make_project(tmp_path)
        idx = SummaryIndex()
        idx.get(proot)

        calls = []
        orig = dash_data.spec_summary

        def tracking(proot_, spec_name_, entry_, **kw):
            calls.append(spec_name_)
            return orig(proot_, spec_name_, entry_, **kw)

        # STATE.md 新增一个 spec 条目
        state_path = proot / ".fenix" / "STATE.md"
        state_path.write_text(
            state_path.read_text(encoding="utf-8").replace(
                "### otherspec",
                "### newspec\n- status: ready\n- priority: 3\n- created: 2026-03-01T00:00:00+00:00\n"
                "- updated: 2026-03-02T00:00:00+00:00\n- error: null\n- depends_on: null\n\n"
                "### otherspec",
            ),
            encoding="utf-8",
        )
        dash_data.spec_summary = tracking
        try:
            items = idx.get(proot)
        finally:
            dash_data.spec_summary = orig
        names = {s["name"] for s in items}
        assert names == {"myspec", "otherspec", "newspec"}
        assert calls == ["newspec"], "新增 spec 只应重算它自己，其余 N-1 个命中缓存"

    def test_spec_deleted_removed_from_index(self, tmp_path):
        """STATE.md 删除一个 spec 条目 → 索引剔除该 spec，其余 spec 命中缓存（不重算）。"""
        proot = make_project(tmp_path)
        idx = SummaryIndex()
        idx.get(proot)

        calls = []
        orig = dash_data.spec_summary

        def tracking(proot_, spec_name_, entry_, **kw):
            calls.append(spec_name_)
            return orig(proot_, spec_name_, entry_, **kw)

        state_path = proot / ".fenix" / "STATE.md"
        state_path.write_text(
            state_path.read_text(encoding="utf-8").replace(
                "### otherspec\n- status: done\n- priority: 1\n- created: 2026-02-01T00:00:00+00:00\n"
                "- updated: 2026-02-02T00:00:00+00:00\n- error: null\n- depends_on: null\n",
                "",
            ),
            encoding="utf-8",
        )
        dash_data.spec_summary = tracking
        try:
            items = idx.get(proot)
        finally:
            dash_data.spec_summary = orig
        names = {s["name"] for s in items}
        assert names == {"myspec"}
        assert calls == [], "删除仅触发索引剔除与快照更新，不重算任何 spec"

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

        def tracking(proot_, spec_name_, entry_, **kw):
            calls.append(spec_name_)
            return orig(proot_, spec_name_, entry_, **kw)

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
        # 未挂 .spec.yaml → 默认 full；再次读取经缓存
        from core.spec_mode import read_spec_mode, _SPEC_MODE_CACHE
        assert read_spec_mode(proot, "myspec") == "full"
        before = dict(_SPEC_MODE_CACHE)
        assert read_spec_mode(proot, "myspec") == "full"
        assert _SPEC_MODE_CACHE == before, "第二次读取应命中缓存（键不变）"


# ── 分槽锁与同趟签名聚合（fix-specs-api-latency D1/D2）──────────────

class TestSummaryIndexSlotsAndSignature:
    """分槽锁并发语义（跨槽不阻塞/同槽互斥/可重入）与 get_with_signature
    同趟聚合的一致性守卫、零额外扫描证明。"""

    @staticmethod
    def _make_project_with_archive(tmp_path: Path, name: str = "proj-a") -> Path:
        """带归档态的项目夹具（一致性守卫须覆盖归档分支：STATE.archive.md
        缺失时 arch 签名组件不可得、签名位为 None，无法做逐字节等值比对）。"""
        proot = make_project(tmp_path, name)
        (proot / ".fenix" / "STATE.archive.md").write_text(
            "# Fenix Archive State\n\n## Specs\n\n"
            "### archspec\n- status: pushed\n- priority: 1\n"
            "- created: 2026-01-05T00:00:00+00:00\n- updated: 2026-01-05T00:00:00+00:00\n",
            encoding="utf-8",
        )
        arc = proot / "spec" / "archive" / "2026-01-05-archspec"
        (arc / "specs").mkdir(parents=True)
        (arc / "tasks.md").write_text("## 1. 完成\n\n- [x] 1.1 旧任务\n", encoding="utf-8")
        (arc / "specs" / "spec.md").write_text(
            "## ADDED Requirements\n\n#### Scenario: 归档场景\n- **WHEN** x\n- **THEN** y\n",
            encoding="utf-8",
        )
        return proot

    # ── 1.3 分槽锁并发语义 ──────────────────────────────────────────

    def test_cross_project_slots_do_not_block(self, tmp_path, monkeypatch):
        """项目 A 冷重建在飞（槽内慢速 IO 用替身拖延）时，项目 B 的读请求
        等待时间显著小于 A 的重建时长（跨槽互不阻塞，fix-specs-api-latency
        D2 场景「跨项目读不互斥」）。"""
        proot_a = make_project(tmp_path, "proj-a")
        proot_b = make_project(tmp_path, "proj-b")
        idx = SummaryIndex()

        slow_seconds = 1.0
        entered = threading.Event()
        orig = dash_data.spec_summary

        def slow_for_a(proot_, spec_name_, entry_, **kw):
            if Path(proot_).resolve() == proot_a.resolve():
                # 仅项目 A 的摘要重算被拖延（替身发生在槽锁内，等价慢速 IO）
                entered.set()
                time.sleep(slow_seconds)
            return orig(proot_, spec_name_, entry_, **kw)

        monkeypatch.setattr(dash_data, "spec_summary", slow_for_a)
        builder = threading.Thread(target=lambda: idx.get(proot_a), daemon=True)
        builder.start()
        assert entered.wait(timeout=5), "A 重建未进入摘要重算阶段（A 已持槽）"
        start = time.monotonic()
        items_b = idx.get(proot_b)
        elapsed_b = time.monotonic() - start
        builder.join(timeout=10)
        assert not builder.is_alive()
        assert {s["name"] for s in items_b} == {"myspec", "otherspec"}
        assert elapsed_b < slow_seconds / 2, (
            f"跨槽读被项目 A 重建阻塞：B 耗时 {elapsed_b:.3f}s "
            f"≥ A 单 spec 重算时长（{slow_seconds}s）的一半"
        )

    def test_same_project_concurrent_gets_serialize(self, tmp_path, monkeypatch):
        """同项目并发 get 仍互斥（中间态不可见）：并发第二请求等同槽重建
        完成后全命中缓存——摘要重算恰好一轮；并发双算会使命中计数翻倍。"""
        proot = make_project(tmp_path)
        idx = SummaryIndex()
        orig = dash_data.spec_summary
        lock = threading.Lock()
        calls = []

        def tracking(proot_, spec_name_, entry_, **kw):
            with lock:
                calls.append(spec_name_)
            time.sleep(0.02)  # 拉开并发窗口：若互斥失效，双算可被计数区分
            return orig(proot_, spec_name_, entry_, **kw)

        monkeypatch.setattr(dash_data, "spec_summary", tracking)
        results = {}

        def worker():
            results[threading.get_ident()] = idx.get(proot)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t_ in threads:
            t_.start()
        for t_ in threads:
            t_.join(timeout=10)
        assert len(results) == 2
        lists = list(results.values())
        assert lists[0] == lists[1], "并发读不应观察到重建中间态（两轮结果须一致）"
        assert sorted(calls) == sorted(["myspec", "otherspec"]), (
            f"同项目互斥失效：观察到 {len(calls)} 次摘要重算（应为 2 spec × 1 轮）"
        )

    def test_invalidation_signature_reentrant_no_deadlock(self, tmp_path):
        """invalidation_signature 在槽锁内调用 state_snapshot（同槽 RLock
        可重入）正常完成，不死锁（fix-specs-api-latency D2 场景）。"""
        proot = make_project(tmp_path)
        idx = SummaryIndex()
        done = threading.Event()
        result = {}

        def worker():
            result["sig"] = idx.invalidation_signature(proot)
            done.set()

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        assert done.wait(timeout=5), "同槽重入死锁：invalidation_signature 未返回"
        assert isinstance(result["sig"], str) and result["sig"]

    # ── 2.2 一致性守卫（design D3：两套签名防漂移）─────────────────

    def test_aggregate_signature_matches_invalidation_signature(self, tmp_path):
        """同一磁盘状态下 get_with_signature 聚合签名与 invalidation_signature
        逐字节等值（冷建轮与全命中轮都断言——命中轮聚合取 idx[name]["sigs"]
        存量，等值仍须成立）。"""
        proot = self._make_project_with_archive(tmp_path)
        idx = SummaryIndex()
        items1, sig1 = idx.get_with_signature(proot)
        assert sig1, "夹具含活跃 STATE 与归档清单，签名应可得"
        assert sig1 == idx.invalidation_signature(proot)
        # 全命中轮（缓存命中条目以存量 sigs 参与聚合）
        items2, sig2 = idx.get_with_signature(proot)
        assert [s["name"] for s in items1] == [s["name"] for s in items2]
        assert sig2 == idx.invalidation_signature(proot)
        # 归档条目在列（归档分支覆盖：归档 spec 的依赖签名参与聚合）
        assert any(s["archived"] for s in items1)

    def test_aggregate_signature_matches_invalidation_signature_without_archive_manifest(
        self, tmp_path
    ):
        """归档清单缺失（无 STATE.archive.md，多数项目的常态稳态）下两套签名
        仍逐字节等值（ba0ab737a591）：arch 组件以缺失哨兵 "missing" 同源参与
        聚合（_arch_manifest_sig），而非 None 使两方法签名分叉。"""
        proot = make_project(tmp_path)
        idx = SummaryIndex()
        items1, sig1 = idx.get_with_signature(proot)
        assert sig1, "清单缺失是稳定空态（哨兵参与聚合而非判不可得），签名应可得"
        assert sig1 == idx.invalidation_signature(proot)
        assert not any(s["archived"] for s in items1)
        # 全命中轮（缓存命中条目以存量 sigs 参与聚合）
        items2, sig2 = idx.get_with_signature(proot)
        assert sig2 == idx.invalidation_signature(proot)

    def test_signature_none_when_component_unavailable(self, tmp_path, monkeypatch):
        """签名组件不可得（state/arch stat 失败，monkeypatch _stat_sig 返回
        None）→ 返回 (列表, None)：摘要列表仍正常产出，签名位为 None。"""
        proot = self._make_project_with_archive(tmp_path)
        idx = SummaryIndex()
        monkeypatch.setattr(summary_mod, "_stat_sig", lambda p: None)
        items, sig = idx.get_with_signature(proot)
        assert sig is None
        assert {s["name"] for s in items} == {"myspec", "otherspec", "archspec"}

    # ── 2.3 聚合零额外扫描 ─────────────────────────────────────────

    def test_aggregation_adds_zero_extra_scans(self, tmp_path, monkeypatch):
        """索引全命中状态下二次调用 get_with_signature：聚合段（combine
        期间）新增 _stat_sig 计数为零——签名完全由内存中本轮签名集拼装
        （结构性证明「三趟并一趟」，不依赖绝对时间）。"""
        proot = self._make_project_with_archive(tmp_path)
        idx = SummaryIndex()

        calls = {"total": 0, "during_combine": 0}
        orig_stat = summary_mod._stat_sig
        orig_combine = sigmod.combine
        lock = threading.Lock()

        def counting_stat(p):
            with lock:
                calls["total"] += 1
            return orig_stat(p)

        def counting_combine(parts):
            with lock:
                snapshot = calls["total"]
            out = orig_combine(parts)
            with lock:
                calls["during_combine"] += calls["total"] - snapshot
            return out

        monkeypatch.setattr(summary_mod, "_stat_sig", counting_stat)
        monkeypatch.setattr(sigmod, "combine", counting_combine)

        idx.get_with_signature(proot)  # 首轮冷建：预热索引与归档树 memo
        calls["total"] = 0
        calls["during_combine"] = 0
        items, sig = idx.get_with_signature(proot)  # 全命中轮
        assert sig
        assert calls["total"] > 0, "计数器未生效（取数趟的失效键现算 stat 应被计入）"
        assert calls["during_combine"] == 0, (
            f"聚合段产生 {calls['during_combine']} 次新 stat："
            "签名未完全复用本轮内存签名集"
        )
