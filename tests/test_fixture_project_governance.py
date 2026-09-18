"""
Tests for fixture-project-governance（夹具项目标识 + 读侧跨项目聚合过滤）。

覆盖 registry 的 `fixture` 字段读写透出、告警/运维记录缺省聚合对夹具项目的
跳过、显式查询保留，以及夹具供给脚本的告警基线复位与登记辅助。
"""
import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conftest import _TestServer, make_project  # noqa: E402

from core.admin_store import AdminStore, ESCALATION, DISPOSITION  # noqa: E402
from core.dashboard.registry import Registry  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static"


def _empty_scan(tmp_path) -> list:
    """返回不存在的扫描根（scan_dirs 为空会触发主目录自动扫描，测试须隔离）。"""
    return [str(tmp_path / "scan-empty")]


def _seed_escalation(proot, spec="fixture-spec", severity="major", handled=False):
    """向项目 seed 一条升级告警（AdminStore 真实写入，验证数据形态）。"""
    rec = AdminStore(proot).append(
        {
            "kind": ESCALATION,
            "spec": spec,
            "severity": severity,
            "handled": handled,
            "description": f"seed escalation {spec}",
            "evidence": f"seed-evidence-{spec}",
            "signal_type": "verify_fail",
        }
    )
    return rec


def _seed_disposition(proot, spec="fixture-spec"):
    """向项目 seed 一条处置记录。"""
    return AdminStore(proot).append(
        {
            "kind": DISPOSITION,
            "spec": spec,
            "status": "resolved",
            "result": "resolved",
            "admin_run_id": f"admin-run-{spec}",
            "description": f"seed disposition {spec}",
            "evidence": f"seed-disposition-evidence-{spec}",
        }
    )


# ── 5.1 discover() 的 fixture 透出 ──────────────────────────────────

class TestDiscoverFixtureFlag:
    def test_explicit_fixture_true(self, tmp_path):
        proot = make_project(tmp_path / "fx", name="fixture-proj")
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save(
            {
                "port": 8787,
                "projects": [
                    {"name": "fixture-proj", "path": str(proot), "fixture": True}
                ],
                "scan_dirs": _empty_scan(tmp_path),
            }
        )
        by_path = {p["path"]: p for p in reg.discover()}
        assert by_path[str(proot)]["fixture"] is True

    def test_explicit_without_fixture_key_defaults_false(self, tmp_path):
        proot = make_project(tmp_path / "normal", name="normal-proj")
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save(
            {
                "port": 8787,
                "projects": [{"name": "normal-proj", "path": str(proot)}],
                "scan_dirs": _empty_scan(tmp_path),
            }
        )
        by_path = {p["path"]: p for p in reg.discover()}
        assert by_path[str(proot)]["fixture"] is False

    def test_scanned_project_defaults_false(self, tmp_path):
        # 扫描根下构造一个 Fenixd 项目（仅需 .fenix/STATE.md）
        scan_root = tmp_path / "scanroot"
        scanned = scan_root / "scanned-proj"
        (scanned / ".fenix").mkdir(parents=True)
        (scanned / ".fenix" / "STATE.md").write_text("# State\n", encoding="utf-8")
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [], "scan_dirs": [str(scan_root)]})
        by_path = {p["path"]: p for p in reg.discover()}
        assert str(scanned) in by_path, "扫描应发现 scanned-proj"
        assert by_path[str(scanned)]["fixture"] is False

    def test_non_boolean_fixture_value_treated_false(self, tmp_path):
        # 非布尔值按假处理（消费点 bool(p.get("fixture"))）
        proot = make_project(tmp_path / "weird", name="weird-proj")
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save(
            {
                "port": 8787,
                "projects": [
                    {"name": "weird-proj", "path": str(proot), "fixture": "yes"}
                ],
                "scan_dirs": _empty_scan(tmp_path),
            }
        )
        by_path = {p["path"]: p for p in reg.discover()}
        assert by_path[str(proot)]["fixture"] is False


# ── 5.2 add_project / mark_fixture ──────────────────────────────────

class TestAddProjectAndMarkFixture:
    def test_add_project_with_fixture_true(self, tmp_path):
        proot = make_project(tmp_path, name="fixture-proj")
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [], "scan_dirs": _empty_scan(tmp_path)})
        added, _ = reg.add_project(str(proot), fixture=True)
        assert added
        data = reg.load()
        entry = next(p for p in data["projects"] if p["path"] == str(proot))
        assert entry["fixture"] is True
        by_path = {p["path"]: p for p in reg.discover()}
        assert by_path[str(proot)]["fixture"] is True

    def test_add_project_default_fixture_false(self, tmp_path):
        proot = make_project(tmp_path, name="normal-proj")
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [], "scan_dirs": _empty_scan(tmp_path)})
        added, _ = reg.add_project(str(proot))
        assert added
        entry = next(p for p in reg.load()["projects"] if p["path"] == str(proot))
        assert entry["fixture"] is False

    def test_mark_fixture_updates_existing_entry(self, tmp_path):
        proot = make_project(tmp_path, name="fixture-proj")
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save(
            {
                "port": 8787,
                "projects": [{"name": "fixture-proj", "path": str(proot)}],
                "scan_dirs": _empty_scan(tmp_path),
            }
        )
        updated, _ = reg.mark_fixture(str(proot), fixture=True)
        assert updated
        entry = next(p for p in reg.load()["projects"] if p["path"] == str(proot))
        assert entry["fixture"] is True
        by_path = {p["path"]: p for p in reg.discover()}
        assert by_path[str(proot)]["fixture"] is True

    def test_mark_fixture_unknown_path_returns_unchanged(self, tmp_path):
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [], "scan_dirs": _empty_scan(tmp_path)})
        updated, msg = reg.mark_fixture(str(tmp_path / "ghost"), fixture=True)
        assert updated is False
        assert "未" in msg or "不在" in msg

    def test_add_project_existing_skips_and_does_not_mutate_flag(self, tmp_path):
        # 已存在同路径条目：add_project 跳过（不重复添加），也不静默改标记
        proot = make_project(tmp_path, name="fixture-proj")
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save(
            {
                "port": 8787,
                "projects": [{"name": "fixture-proj", "path": str(proot)}],
                "scan_dirs": _empty_scan(tmp_path),
            }
        )
        added, msg = reg.add_project(str(proot), fixture=True)
        assert added is False
        assert "已在监控列表" in msg
        entry = next(p for p in reg.load()["projects"] if p["path"] == str(proot))
        assert "fixture" not in entry, "跳过时不得静默改标记"


# ── 5.3 /api/alerts 缺省聚合跳过夹具项目 ────────────────────────────

class TestAlertsAggregationFilter:
    def _two_project_server(self, tmp_path):
        """构造 fixture:true 与 fixture:false 两个项目（后者带未处理告警）。"""
        fx = make_project(tmp_path / "fx", name="fixture-proj")
        normal = make_project(tmp_path / "normal", name="normal-proj")
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save(
            {
                "port": 8787,
                "projects": [
                    {"name": "fixture-proj", "path": str(fx), "fixture": True},
                    {"name": "normal-proj", "path": str(normal)},
                ],
                "scan_dirs": _empty_scan(tmp_path),
            }
        )
        return fx, normal, _TestServer(reg, STATIC_DIR)

    def test_default_aggregation_excludes_fixture_alerts(self, tmp_path):
        fx, normal, srv = self._two_project_server(tmp_path)
        try:
            _seed_escalation(fx, spec="fx-spec", severity="major")
            _seed_escalation(normal, spec="normal-spec", severity="critical")
            status, data = srv.get("/api/alerts")
            assert status == 200
            names = {p["name"] for p in data["projects"]}
            assert "fixture-proj" not in names
            assert "normal-proj" in names
            assert all(a.get("project") != "fixture-proj" for a in data["alerts"])
            assert all(a.get("project") != "fixture-proj" for a in data["resolved"])
            assert data["total_unhandled"] == 1  # 仅 normal-proj 的 critical
            alert_specs = [a.get("spec") for a in data["alerts"]]
            assert "normal-spec" in alert_specs
            assert "fx-spec" not in alert_specs
        finally:
            srv.stop()

    def test_explicit_query_returns_fixture_alerts(self, tmp_path):
        fx, normal, srv = self._two_project_server(tmp_path)
        try:
            seeded = _seed_escalation(fx, spec="fx-spec", severity="major")
            status, data = srv.get("/api/alerts?project=fixture-proj")
            assert status == 200
            assert data["project"] == "fixture-proj"
            assert len(data["alerts"]) == 1
            rec = data["alerts"][0]
            assert rec["id"] == seeded["id"]
            assert rec["spec"] == "fx-spec"
            assert rec["severity"] == "major"
            assert rec["handled"] is False
            assert rec["evidence"] == "seed-evidence-fx-spec"
        finally:
            srv.stop()


# ── 5.4 /api/admin-activities 缺省聚合跳过夹具项目 ──────────────────

class TestAdminActivitiesAggregationFilter:
    def _two_project_server(self, tmp_path):
        fx = make_project(tmp_path / "fx", name="fixture-proj")
        normal = make_project(tmp_path / "normal", name="normal-proj")
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save(
            {
                "port": 8787,
                "projects": [
                    {"name": "fixture-proj", "path": str(fx), "fixture": True},
                    {"name": "normal-proj", "path": str(normal)},
                ],
                "scan_dirs": _empty_scan(tmp_path),
            }
        )
        return fx, normal, _TestServer(reg, STATIC_DIR)

    def test_default_aggregation_excludes_fixture_dispositions(self, tmp_path):
        fx, normal, srv = self._two_project_server(tmp_path)
        try:
            _seed_disposition(fx, spec="fx-spec")
            _seed_disposition(normal, spec="normal-spec")
            status, data = srv.get("/api/admin-activities")
            assert status == 200
            names = {p["name"] for p in data["projects"]}
            assert "fixture-proj" not in names
            assert "normal-proj" in names
        finally:
            srv.stop()

    def test_explicit_query_returns_fixture_dispositions(self, tmp_path):
        fx, normal, srv = self._two_project_server(tmp_path)
        try:
            seeded = _seed_disposition(fx, spec="fx-spec")
            status, data = srv.get("/api/admin-activities?project=fixture-proj")
            assert status == 200
            assert data["project"] == "fixture-proj"
            recs = data["activities"]
            assert len(recs) >= 1
            assert any(r.get("spec") == "fx-spec" for r in recs)
            assert any(r.get("evidence") == "seed-disposition-evidence-fx-spec" for r in recs)
        finally:
            srv.stop()


# ── 5.5 夹具供给脚本：告警基线复位 + 登记辅助幂等 ───────────────────

class TestResetAlertsBaseline:
    def _import_script(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
        import fixture_scheduling_showcase as fss

        return fss

    def test_reset_clears_seed_alerts_and_is_idempotent(self, tmp_path, monkeypatch):
        fss = self._import_script()
        fixture_root = tmp_path / "scheduling-showcase"
        (fixture_root / ".fenix").mkdir(parents=True)
        (fixture_root / ".fenix" / "STATE.md").write_text("# State\n", encoding="utf-8")
        # 指向临时夹具根（脚本内 ROOT 常量替换为测试夹具）
        monkeypatch.setattr(fss, "ROOT", fixture_root)

        store = AdminStore(fixture_root)
        store.append(
            {
                "kind": ESCALATION,
                "spec": "fx-spec",
                "severity": "major",
                "handled": False,
                "description": "上一轮 seed",
                "evidence": "seed",
                "signal_type": "verify_fail",
            }
        )
        assert len(store.read_all()) == 1

        fss._reset_alerts_baseline()
        alerts_path = fixture_root / ".fenix" / "admin_alerts.json"
        assert alerts_path.exists()
        assert json.loads(alerts_path.read_text(encoding="utf-8")) == []
        assert AdminStore(fixture_root).read_all() == []

        # 幂等：连续两次复位仍为空基线
        store.append(
            {
                "kind": ESCALATION,
                "spec": "fx-spec-2",
                "severity": "critical",
                "handled": False,
                "description": "再一轮 seed",
                "signal_type": "verify_fail",
            }
        )
        fss._reset_alerts_baseline()
        fss._reset_alerts_baseline()
        assert json.loads(alerts_path.read_text(encoding="utf-8")) == []
        assert fss._alerts_count() == 0

    def test_reset_missing_file_is_noop(self, tmp_path, monkeypatch):
        fss = self._import_script()
        fixture_root = tmp_path / "scheduling-showcase"
        (fixture_root / ".fenix").mkdir(parents=True)
        monkeypatch.setattr(fss, "ROOT", fixture_root)
        fss._reset_alerts_baseline()  # 无既有文件：直接建立空基线
        alerts_path = fixture_root / ".fenix" / "admin_alerts.json"
        assert json.loads(alerts_path.read_text(encoding="utf-8")) == []

    def test_ensure_registered_no_duplicate_and_keeps_flag(self, tmp_path, monkeypatch):
        fss = self._import_script()
        fixture_root = tmp_path / "scheduling-showcase"
        (fixture_root / ".fenix").mkdir(parents=True)
        (fixture_root / ".fenix" / "STATE.md").write_text("# State\n", encoding="utf-8")
        monkeypatch.setattr(fss, "ROOT", fixture_root)
        cfg = tmp_path / "dashboard.yaml"
        monkeypatch.setattr(
            "core.dashboard.registry.DEFAULT_CONFIG", cfg
        )  # Registry() 无参时解析模块级 DEFAULT_CONFIG
        # 预置隔离扫描根：scan_dirs 为空会默认扫主目录 ~，将 /root 下真实项目
        # 一并 discover，干扰「不产生重复条目」的断言
        Registry().save({"port": 8787, "projects": [], "scan_dirs": _empty_scan(tmp_path)})

        # 先登记（add_project(fixture=True)）
        reg = Registry()
        added, _ = reg.add_project(str(fixture_root), fixture=True)
        assert added
        # 执行登记辅助（已存在 → mark_fixture 补标记）
        fss._ensure_registered()
        projects = reg.discover()
        assert len(projects) == 1
        assert projects[0]["fixture"] is True
        # 再次执行登记辅助仍不产生重复条目
        fss._ensure_registered()
        assert len(reg.discover()) == 1


# ── 5.6 回归：fixture 标记不影响项目可见性 ──────────────────────────

class TestFixtureVisibility:
    def test_discover_still_returns_fixture_project(self, tmp_path):
        proot = make_project(tmp_path / "fx", name="fixture-proj")
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save(
            {
                "port": 8787,
                "projects": [
                    {"name": "fixture-proj", "path": str(proot), "fixture": True}
                ],
                "scan_dirs": _empty_scan(tmp_path),
            }
        )
        by_path = {p["path"]: p for p in reg.discover()}
        assert str(proot) in by_path
        assert by_path[str(proot)]["exists"] is True
        assert by_path[str(proot)]["discovered"] is False
        assert by_path[str(proot)]["fixture"] is True

    def test_overview_still_includes_fixture_card(self, tmp_path):
        proot = make_project(tmp_path / "fx", name="fixture-proj")
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save(
            {
                "port": 8787,
                "projects": [
                    {"name": "fixture-proj", "path": str(proot), "fixture": True}
                ],
                "scan_dirs": _empty_scan(tmp_path),
            }
        )
        srv = _TestServer(reg, STATIC_DIR)
        try:
            status, data = srv.get("/api/overview")
            assert status == 200
            names = {p["name"] for p in data["projects"]}
            assert "fixture-proj" in names
        finally:
            srv.stop()
