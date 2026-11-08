"""Perf guards for /api/specs read path (fix-specs-api-latency 4.1/4.2).

结构性证明「三趟并一趟」（不依赖绝对时间）：/api/specs 单次 200 请求全链
（签名+取数同趟）的 ``_stat_sig`` 调用计数 ≤ 既有三趟形态
（handler 前独立签名 + get 取数 + 发头前复核签名）的 1/2。
另附跨项目互斥的 handler 层规模断言。
"""
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conftest import _TestServer  # noqa: E402

from core.dashboard import data as dash_data  # noqa: E402
from core.dashboard.data import summary as summary_mod  # noqa: E402
from core.dashboard.registry import Registry  # noqa: E402

# 规模下限（spec 4.1：活跃 + 归档目录各 ≥300，归档分支必须覆盖——
# changes.is_dir() 假阳性教训）
N_ACTIVE = 300
N_ARCHIVED = 300


def make_scale_project(
    tmp_path: Path, name: str = "perf-proj",
    n_active: int = N_ACTIVE, n_archived: int = N_ARCHIVED,
) -> Path:
    """构造规模夹具：活跃 spec 目录 + 归档 spec 目录各 ≥300。

    活跃侧 spec/changes/spec-<i>/（tasks.md + specs/spec.md）+ STATE.md 条目；
    归档侧 spec/archive/2026-01-01-arch-<i>/ + STATE.archive.md 清单条目
    （resolve_spec_dir 剥日期前缀后与清单名全等）。
    """
    proot = tmp_path / name
    (proot / ".fenix" / "runs").mkdir(parents=True)

    state_body = ["# Fenix Project State\n\n## Specs\n"]
    for i in range(n_active):
        d = proot / "spec" / "changes" / f"spec-{i}"
        (d / "specs").mkdir(parents=True)
        (d / "tasks.md").write_text(
            f"## 1. 阶段\n\n- [x] 1.1 任务a{i}\n- [ ] 1.2 任务b{i}\n", encoding="utf-8"
        )
        (d / "specs" / "spec.md").write_text(
            "## ADDED Requirements\n\n#### Scenario: 场景\n- **WHEN** x\n- **THEN** y\n",
            encoding="utf-8",
        )
        state_body.append(
            f"\n### spec-{i}\n- status: testing\n- priority: 2\n"
            f"- created: 2026-03-01T00:00:{i % 60:02d}+00:00\n"
            f"- updated: 2026-03-02T00:00:{i % 60:02d}+00:00\n"
            "- error: null\n- depends_on: null\n"
        )
    (proot / ".fenix" / "STATE.md").write_text("".join(state_body), encoding="utf-8")
    (proot / ".fenix" / "config.yaml").write_text(
        "project:\n  name: perf\n", encoding="utf-8"
    )

    arch_body = ["# Fenix Archive State\n\n## Specs\n"]
    for i in range(n_archived):
        d = proot / "spec" / "archive" / f"2026-01-01-arch-{i}"
        (d / "specs").mkdir(parents=True)
        (d / "tasks.md").write_text(f"## 1. 完成\n\n- [x] 1.1 旧任务{i}\n", encoding="utf-8")
        (d / "specs" / "spec.md").write_text(
            "## ADDED Requirements\n\n#### Scenario: 归档场景\n- **WHEN** x\n- **THEN** y\n",
            encoding="utf-8",
        )
        arch_body.append(
            f"\n### arch-{i}\n- status: pushed\n- priority: 1\n"
            "- created: 2026-01-01T00:00:00+00:00\n- updated: 2026-01-01T00:00:00+00:00\n"
        )
    (proot / ".fenix" / "STATE.archive.md").write_text("".join(arch_body), encoding="utf-8")
    return proot


def _start_server(tmp_path: Path, projects) -> _TestServer:
    cfg = tmp_path / "dashboard-perf.yaml"
    reg = Registry(config_path=cfg)
    reg.save({
        "port": 8787,
        "projects": [{"name": n, "path": str(p)} for n, p in projects],
        "scan_dirs": [],
    })
    return _TestServer(reg, tmp_path / "static-perf-missing")


class _SigCounter:
    """summary._stat_sig 线程安全计数替身（透传原函数，只加计数）。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._n = 0
        self._orig = summary_mod._stat_sig

    def __call__(self, p):
        with self._lock:
            self._n += 1
        return self._orig(p)

    def reset(self):
        with self._lock:
            self._n = 0

    def value(self):
        with self._lock:
            return self._n

    def install(self, monkeypatch):
        monkeypatch.setattr(summary_mod, "_stat_sig", self)


class TestSpecsApiPerfGuard:
    def test_single_pass_within_half_of_three_pass_shape(self, tmp_path, monkeypatch):
        """4.1：/api/specs 单次 200 请求全链（签名+取数同趟）的 _stat_sig
        调用计数 ≤ 既有三趟形态的 1/2（三趟并一趟的结构性证明，不依赖
        绝对时间）；耗时仅作信息性打印（热路径 < 300ms 量级观察，不作硬门
        防 CI 抖动误拦）。"""
        proot = make_scale_project(tmp_path)
        srv = _start_server(tmp_path, [("perf-proj", proot)])
        try:
            # 预热：首轮冷建（索引缓存 + 归档树 memo），让计数落在稳态热路径
            t0 = time.monotonic()
            status, first = srv.get("/api/specs?project=perf-proj")
            cold = time.monotonic() - t0
            assert status == 200
            assert len(first["specs"]) == N_ACTIVE + N_ARCHIVED

            counter = _SigCounter()
            counter.install(monkeypatch)

            # 新链：单次 200 请求全链（自含 handler：get_with_signature 同趟
            # 签名+取数，协商与 page 拼装零 stat）
            counter.reset()
            t0 = time.monotonic()
            status, _ = srv.get("/api/specs?project=perf-proj")
            hot = time.monotonic() - t0
            assert status == 200
            c_new = counter.value()

            # 旧链基线（三趟形态，design Context）：handler 前独立签名一趟
            # （invalidation_signature）+ get 取数一趟 + _json 发头前复核
            # 签名一趟（invalidation_signature again）
            idx = srv.httpd.summary_index
            counter.reset()
            idx.invalidation_signature(proot)
            idx.get(proot)
            idx.invalidation_signature(proot)
            c_old = counter.value()

            assert 2 * c_new <= c_old, (
                f"单趟聚合后 stat 计数未减半：new={c_new} old(三趟)={c_old}"
            )
            print(
                f"\n[perf] /api/specs 热路径 200：{hot * 1000:.0f}ms"
                f"（冷建 {cold * 1000:.0f}ms），stat 计数 new={c_new} 三趟形态={c_old}"
            )
        finally:
            srv.stop()

    def test_cross_project_rebuild_does_not_block_other_project_handler(
        self, tmp_path, monkeypatch
    ):
        """4.2：项目 A 冷重建在飞时项目 B 的 /api/specs 端到端响应不被阻塞
        （handler 层证据，配合 test_dashboard_index 的单测层证据——分槽锁
        跨槽互不阻塞）。单用例 10s 硬门：慢速替身只拖延首个 spec 重算一次
        （事件置位发生在槽锁内的 sleep 之前，B 的测量窗口与该 sleep 重叠，
        A 持槽状态对测量时刻确定）。"""
        slow_root = make_scale_project(tmp_path, "perf-slow", n_active=4, n_archived=2)
        fast_root = make_scale_project(tmp_path, "perf-fast", n_active=4, n_archived=2)
        srv = _start_server(
            tmp_path, [("perf-slow", slow_root), ("perf-fast", fast_root)]
        )
        try:
            slow_seconds = 1.0
            entered = threading.Event()
            orig = dash_data.spec_summary
            slowed_once = []

            def slow_for_slow(proot_, spec_name_, entry_, **kw):
                if (
                    Path(proot_).resolve() == slow_root.resolve()
                    and not slowed_once
                ):
                    # 仅项目 A 的首个 spec 重算被拖延（替身发生在槽锁内）
                    slowed_once.append(spec_name_)
                    entered.set()
                    time.sleep(slow_seconds)
                return orig(proot_, spec_name_, entry_, **kw)

            monkeypatch.setattr(dash_data, "spec_summary", slow_for_slow)
            builder = threading.Thread(
                target=lambda: srv.httpd.summary_index.get(slow_root), daemon=True
            )
            builder.start()
            assert entered.wait(timeout=5), "A 重建未进入摘要重算阶段（A 已持槽）"
            t0 = time.monotonic()
            status, body = srv.get("/api/specs?project=perf-fast")
            elapsed = time.monotonic() - t0
            builder.join(timeout=8)
            assert not builder.is_alive()
            assert status == 200
            assert body["project"] == "perf-fast"
            assert body["specs"]
            assert elapsed < slow_seconds / 2, (
                f"handler 层跨项目读被项目 A 重建阻塞：B 端到端耗时 {elapsed:.3f}s"
            )
        finally:
            srv.stop()
