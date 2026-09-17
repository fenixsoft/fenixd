"""
Tests for dashboard fault isolation (fix-dashboard-fault-isolation).

覆盖 2026-09-12 事故（/data 硬件故障 → discover() 整体失败 → /api/overview 500）
的修复契约：发现层逐子目录异常隔离、ignored 过滤前置、发现缓存异常语义、
聚合层逐项目隔离、前端降级展示。
"""
import errno
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conftest import _TestServer, make_project  # noqa: E402

from core.dashboard.registry import Registry  # noqa: E402


def _make_fenix_project(root: Path, name: str) -> Path:
    """在 root 下构造一个含 .fenix/STATE.md 的最小 Fenixd 项目目录。"""
    proot = root / name
    (proot / ".fenix").mkdir(parents=True, exist_ok=True)
    (proot / ".fenix" / "STATE.md").write_text("# State\n", encoding="utf-8")
    return proot


# ── 1. 发现层容错（project-discovery） ────────────────────────────────

class TestDiscoverFaultIsolation:
    def test_discover_skips_unreadable_subdir_and_keeps_rest(
            self, tmp_path, monkeypatch, caplog):
        """探测抛 OSError(EIO) 的子目录被跳过，discover() 不抛、其余项目照常。"""
        scan = tmp_path / "scan"
        good = _make_fenix_project(scan, "good-proj")
        bad = scan / "bad-dir"
        bad.mkdir(parents=True, exist_ok=True)
        explicit = _make_fenix_project(tmp_path, "explicit-proj")

        real_is_file = Path.is_file

        def is_file_eio(self, *a, **kw):
            # 对坏目录的任何 is_file 探测抛 EIO（模拟目录数据块不可读）
            if str(self).startswith(str(bad)):
                raise OSError(errno.EIO, "Input/output error")
            return real_is_file(self, *a, **kw)

        monkeypatch.setattr(Path, "is_file", is_file_eio)

        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({
            "port": 8787,
            "projects": [{"name": "explicit-proj", "path": str(explicit)}],
            "scan_dirs": [str(scan)],
        })

        with caplog.at_level(logging.WARNING, logger="fenixd.dashboard.registry"):
            result = reg.discover()

        assert isinstance(result, list)
        names = {p["name"] for p in result}
        assert "good-proj" in names, "同扫描根下正常 Fenixd 项目仍被发现"
        assert "explicit-proj" in names, "显式项目不受扫描异常影响"
        assert "bad-dir" not in names, "不可读目录不进入监控列表"
        # WARNING 日志含路径与 errno/异常摘要
        warn_records = [r for r in caplog.records
                        if r.levelno == logging.WARNING]
        assert any(str(bad) in r.getMessage() for r in warn_records)
        assert any("errno" in r.getMessage() for r in warn_records)

    def test_discover_is_dir_eio_isolated(self, tmp_path, monkeypatch, caplog):
        """目录类型判断（is_dir）抛 OSError 同样被隔离（spec 场景）。"""
        scan = tmp_path / "scan"
        good = _make_fenix_project(scan, "good-proj")
        bad = scan / "bad-dir"
        bad.mkdir(parents=True, exist_ok=True)

        real_is_dir = Path.is_dir

        def is_dir_eio(self, *a, **kw):
            if str(self) == str(bad):
                raise OSError(errno.EIO, "Input/output error")
            return real_is_dir(self, *a, **kw)

        monkeypatch.setattr(Path, "is_dir", is_dir_eio)

        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [], "scan_dirs": [str(scan)]})

        with caplog.at_level(logging.WARNING, logger="fenixd.dashboard.registry"):
            result = reg.discover()

        names = {p["name"] for p in result}
        assert "good-proj" in names
        assert "bad-dir" not in names

    def test_ignored_short_circuits_probe(self, tmp_path, monkeypatch):
        """同一子目录命中 ignored 后探测函数零调用（忽略过滤短路）。"""
        scan = tmp_path / "scan"
        bad = scan / "bad-dir"
        bad.mkdir(parents=True, exist_ok=True)

        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [], "scan_dirs": [str(scan)]})
        added, _ = reg.add_ignored(str(bad))
        assert added is True

        calls = []
        real_probe = Registry.probe_child

        def counting_probe(self, child):
            calls.append(child)
            return real_probe(self, child)

        monkeypatch.setattr(Registry, "probe_child", counting_probe)

        result = reg.discover()
        assert calls == [], "ignored 命中后探测函数 MUST NOT 被调用"
        assert result == [], "被忽略目录不得出现在监控列表"

    def test_add_ignored_works_for_paths_that_cannot_be_probed(self, tmp_path):
        """add_ignored 对不可读路径仍可成功写入（_norm 非 strict resolve）。"""
        scan = tmp_path / "scan"
        bad = scan / "bad-dir"
        bad.mkdir(parents=True, exist_ok=True)

        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [], "scan_dirs": []})

        added, msg = reg.add_ignored(str(bad))
        assert added is True
        assert "已加入忽略列表" in msg
        key = reg._norm(str(bad))
        assert key in reg.load()["ignored"]
        assert reg.is_ignored(str(bad))

    def test_unreadable_scan_root_skipped_others_kept(self, tmp_path, monkeypatch):
        """某个扫描根 iterdir() 抛 OSError 时被跳过，其余根与显式项目照常。"""
        bad_root = tmp_path / "bad-root"
        bad_root.mkdir(parents=True, exist_ok=True)
        good_root = tmp_path / "good-root"
        _make_fenix_project(good_root, "good-proj")
        explicit = _make_fenix_project(tmp_path, "explicit-proj")

        real_iterdir = Path.iterdir

        def iterdir_eio(self, *a, **kw):
            if str(self) == str(bad_root):
                raise OSError(errno.EIO, "Input/output error")
            return real_iterdir(self, *a, **kw)

        monkeypatch.setattr(Path, "iterdir", iterdir_eio)

        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({
            "port": 8787,
            "projects": [{"name": "explicit-proj", "path": str(explicit)}],
            "scan_dirs": [str(bad_root), str(good_root)],
        })

        result = reg.discover()
        names = {p["name"] for p in result}
        assert "good-proj" in names, "其余扫描根正常处理"
        assert "explicit-proj" in names, "显式项目不受影响"
        assert "bad-root" not in names

    def test_eio_subdir_does_not_affect_explicit_registered(self, tmp_path, monkeypatch):
        """扫描根下存在探测抛 OSError 的目录，显式注册项目仍 discovered=False 出现。"""
        scan = tmp_path / "scan"
        bad = scan / "bad-dir"
        bad.mkdir(parents=True, exist_ok=True)
        explicit = _make_fenix_project(tmp_path, "fenixd")

        real_is_file = Path.is_file

        def is_file_eio(self, *a, **kw):
            if str(self).startswith(str(bad)):
                raise OSError(errno.EIO, "Input/output error")
            return real_is_file(self, *a, **kw)

        monkeypatch.setattr(Path, "is_file", is_file_eio)

        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({
            "port": 8787,
            "projects": [{"name": "fenixd", "path": str(explicit)}],
            "scan_dirs": [str(scan)],
        })

        result = reg.discover()
        by_name = {p["name"]: p for p in result}
        assert by_name["fenixd"]["discovered"] is False
        assert by_name["fenixd"]["path"] == str(explicit.resolve())


# ── 2. 聚合层与服务层隔离（dashboard-server） ─────────────────────────

class TestAggregationIsolation:
    def _make_server(self, tmp_path, registry):
        return _TestServer(registry,
                           Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")

    def test_discover_exception_reuses_cache_and_ttl(self, tmp_path, monkeypatch):
        """discover() 持续抛异常时 TTL 内多次请求，discover() 只调 1 次且响应 200。"""
        proot = make_project(tmp_path)
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})

        calls = []
        real_discover = Registry.discover

        def flaky_discover(self):
            calls.append(1)
            # 第 1 次成功缓存，之后持续抛异常
            if len(calls) > 1:
                raise OSError(errno.EIO, "Input/output error")
            return real_discover(self)

        monkeypatch.setattr(Registry, "discover", flaky_discover)

        srv = self._make_server(tmp_path, reg)
        try:
            # 第 1 次：成功发现并缓存
            status, data = srv.get("/api/overview")
            assert status == 200
            assert data["projects"][0]["name"] == "proj-a"
            assert len(calls) == 1

            # 后续请求：discover() 抛异常 → 复用上次成功结果，不再重试
            status, data = srv.get("/api/overview")
            assert status == 200
            assert data["projects"][0]["name"] == "proj-a"
            assert len(calls) == 1, "TTL 内不得重复执行发现"
        finally:
            srv.stop()

    def test_first_discover_failure_returns_empty_200(self, tmp_path, monkeypatch):
        """服务器启动后首次 discover() 即抛异常 → 200 且项目列表为空。"""
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [], "scan_dirs": [str(tmp_path / "scan-empty")]})

        monkeypatch.setattr(
            Registry, "discover",
            lambda self: (_ for _ in ()).throw(OSError(errno.EIO, "Input/output error")))

        srv = self._make_server(tmp_path, reg)
        try:
            status, data = srv.get("/api/projects")
            assert status == 200
            assert data["projects"] == []
            status, data = srv.get("/api/overview")
            assert status == 200
            assert data["totals"]["spec_count"] == 0
            assert data["totals"]["active_runs"] == 0
        finally:
            srv.stop()

    def test_overview_single_project_failure_degrades(self, tmp_path, monkeypatch):
        """单项目摘要抛异常 → /api/overview 200，失败项目带 error，正常项目与 totals 不变。"""
        good_proot = make_project(tmp_path, name="good-proj")
        bad_proot = make_project(tmp_path, name="bad-proj")

        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [
            {"name": "good-proj", "path": str(good_proot)},
            {"name": "bad-proj", "path": str(bad_proot)},
        ], "scan_dirs": [str(tmp_path / "scan-empty")]})

        import core.dashboard.data as dash_data
        real_summary = dash_data.project_summary

        def flaky_summary(project_root, name, path):
            if name == "bad-proj":
                raise OSError(errno.EIO, "Input/output error")
            return real_summary(project_root, name, path)

        monkeypatch.setattr(dash_data, "project_summary", flaky_summary)

        srv = self._make_server(tmp_path, reg)
        try:
            status, data = srv.get("/api/overview")
            assert status == 200
            by_name = {p["name"]: p for p in data["projects"]}
            assert "bad-proj" in by_name, "失败项目 MUST 仍出现在概览中"
            assert by_name["bad-proj"]["error"], "失败项目摘要带非空 error 字段"
            assert by_name["bad-proj"]["exists"] is True, "exists 语义保持（路径可解析即 True）"
            assert "spec_count" not in by_name["bad-proj"], "失败项目不携带正常统计字段"
            assert by_name["good-proj"]["spec_count"] == 2, "正常项目字段与无故障时一致"
            # totals 只累计正常项目：good-proj spec_count=2
            assert data["totals"]["spec_count"] == 2, "失败项目不得计入 totals"
            assert data["totals"]["active_runs"] == 1
        finally:
            srv.stop()

    def test_api_projects_single_failure_degrades(self, tmp_path, monkeypatch):
        """_api_projects() 逐项目隔离 → /api/projects 200，失败项目带 error。"""
        good_proot = make_project(tmp_path, name="good-proj")
        bad_proot = make_project(tmp_path, name="bad-proj")

        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [
            {"name": "good-proj", "path": str(good_proot)},
            {"name": "bad-proj", "path": str(bad_proot)},
        ], "scan_dirs": [str(tmp_path / "scan-empty")]})

        import core.dashboard.data as dash_data
        real_summary = dash_data.project_summary

        def flaky_summary(project_root, name, path):
            if name == "bad-proj":
                raise OSError(errno.EIO, "Input/output error")
            return real_summary(project_root, name, path)

        monkeypatch.setattr(dash_data, "project_summary", flaky_summary)

        srv = self._make_server(tmp_path, reg)
        try:
            status, data = srv.get("/api/projects")
            assert status == 200
            by_name = {p["name"]: p for p in data["projects"]}
            assert by_name["bad-proj"]["error"]
            assert by_name["good-proj"]["spec_count"] == 2
        finally:
            srv.stop()

    def test_exists_semantics_preserved_for_unreadable_content(self, tmp_path):
        """路径可解析但内容不可读的项目仍 exists=True，失败原因只在 error 字段。"""
        proot = make_project(tmp_path, name="proj-a")

        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})

        import core.dashboard.data as dash_data
        srv = self._make_server(tmp_path, reg)
        try:
            status, data = srv.get("/api/overview")
            assert status == 200
            p = data["projects"][0]
            assert p["exists"] is True, "路径可解析（is_dir）即 exists=True"
            assert not p.get("error"), "正常项目无 error 字段"

            # 让 STATE.md 解析抛 EIO：项目路径本身可解析，内容不可读。
            # 直接调用 data.overview：project_summary 内 parse_state 读 STATE.md
            orig = dash_data.parse_state

            def flaky_parse_state(root):
                raise OSError(errno.EIO, "Input/output error")

            dash_data.parse_state = flaky_parse_state
            try:
                res = dash_data.overview(reg.discover())
                p2 = res["projects"][0]
                assert p2["exists"] is True, "内容不可读不改动 exists 语义"
                assert p2["error"], "失败原因只体现在 error 字段"
            finally:
                dash_data.parse_state = orig
        finally:
            srv.stop()
