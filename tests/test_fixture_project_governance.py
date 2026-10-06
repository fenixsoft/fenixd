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


# ═══════════════════════════════════════════════════════════════════
# alert-noise-governance 5：召唤通道 fixture 抑制（消费端 ②）
# ═══════════════════════════════════════════════════════════════════

import time  # noqa: E402

from core.admin_monitor import (  # noqa: E402
    AdminMonitor,
    _error_fingerprint,
    _is_fixture_project,
)
from core.admin_store import SIGNAL  # noqa: E402
from core.agent_runner.runner import AdminDisposition  # noqa: E402


class RecordingRunner:
    """记录型 runner：消费 run_administrator 并返回最小合法处置。"""

    def __init__(self):
        self.calls = []

    def run_administrator(self, signal):
        self.calls.append(signal)
        return AdminDisposition(
            run_id=f"admin-test-{len(self.calls)}",
            spec=signal.get("spec"),
            success=True,
            problem=signal.get("description", ""),
            actions_taken="测试处置",
            result="resolved",
            summary="诊断结论：测试处置；处置时间线：测试处置；结果：已解决。",
        )


class RecordingMonitorLogger:
    def __init__(self):
        self.infos = []

    def debug(self, *a, **k):
        pass

    def info(self, component, message, **k):
        self.infos.append(str(message))

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


class FakeStates:
    def read_all(self):
        return {}

    def read_one(self, name):
        return None


def _make_fixture_monitor(proot, fixture_true, monkeypatch):
    """构造 AdminMonitor（记录型 runner/logger），并按参打 fixture 标记桩。"""
    monkeypatch.setattr("core.admin_monitor._is_fixture_project",
                        lambda root: fixture_true)
    runner = RecordingRunner()
    logger = RecordingMonitorLogger()
    mon = AdminMonitor(
        {}, FakeStates(), proot, logger,
        store=AdminStore(proot, logger), agent_runner=runner,
    )
    return mon, runner, logger


def _daemon_error_signal(fp):
    return {
        "signal_type": "daemon_errors",
        "spec": None,
        "severity": "critical",
        "description": f"fenixd 日志同错误（指纹 {fp[:8]}）在 10 分钟窗口内复现 2 次",
        "evidence": "同指纹 ERROR 复现 2 次",
        "recommended_action": "检查根因并重启 daemon",
        "_fp": fp,
    }


class TestFixtureInvocationSuppression:
    """tasks.md 5.1/5.2/6.4：fixture 项目达升级条件不召唤，人工不受限。"""

    def test_helper_reads_registry_fixture_true(self, tmp_path, monkeypatch):
        """_is_fixture_project 经 Registry 权威源读取 fixture:true 条目。"""
        cfg = tmp_path / "dashboard.yaml"
        proot = tmp_path / "proj"
        proot.mkdir()
        cfg.write_text(
            yaml.safe_dump({
                "projects": [{"path": str(proot), "fixture": True}],
                "scan_dirs": [str(tmp_path / "scan-empty")],
            }),
            encoding="utf-8",
        )
        monkeypatch.setattr("core.dashboard.registry.DEFAULT_CONFIG", cfg)
        assert _is_fixture_project(proot) is True
        assert _is_fixture_project(tmp_path / "other") is False

    def test_helper_failopen_on_missing_config(self, tmp_path, monkeypatch):
        """fail-open：配置不存在 / 损坏 / 项目不在册 → 按非夹具。"""
        monkeypatch.setattr("core.dashboard.registry.DEFAULT_CONFIG",
                            tmp_path / "no-such.yaml")
        assert _is_fixture_project(tmp_path) is False
        bad = tmp_path / "bad.yaml"
        bad.write_text("projects: [::::not-yaml", encoding="utf-8")
        monkeypatch.setattr("core.dashboard.registry.DEFAULT_CONFIG", bad)
        assert _is_fixture_project(tmp_path) is False

    def test_fixture_project_no_admin_global_run(self, tmp_path, monkeypatch):
        """fixture 项目 daemon_errors 达升级条件：不建 admin-global run，INFO 留痕。"""
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True)
        mon, runner, logger = _make_fixture_monitor(proot, True, monkeypatch)
        fp = _error_fingerprint("pm_engine", "some fixture gate error (attempt 1)")

        mon._handle_signal(_daemon_error_signal(fp))

        assert runner.calls == [], "夹具项目不得自动召唤 Administrator"
        assert any("抑制自动召唤" in m and fp[:8] in m for m in logger.infos), logger.infos

    def test_suppression_keeps_alert_records_visible(self, tmp_path, monkeypatch):
        """5.2：抑制只阻断召唤——信号沉淀入库（escalated=False），既有记录不动。"""
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True)
        mon, runner, logger = _make_fixture_monitor(proot, True, monkeypatch)
        seed = AdminStore(proot, logger).append({
            "kind": ESCALATION,
            "signal_type": "spec_content_missing",
            "spec": "c-x",
            "severity": "major",
            "description": "seed alert",
            "handled": False,
        })
        fp = _error_fingerprint("pm_engine", "noise (attempt 1)")

        mon._handle_signal(_daemon_error_signal(fp))

        recs = AdminStore(proot, logger).read_all()
        # 既有告警原样保留（不删除/不改写）
        seeded = [r for r in recs if r.get("id") == seed["id"]][0]
        assert seeded["description"] == "seed alert"
        assert not seeded.get("handled")
        # 本次信号仍沉淀入库（看板可见），但未虚报已唤起
        sig_recs = [r for r in recs if r.get("kind") == SIGNAL
                    and r.get("signal_type") == "daemon_errors"]
        assert len(sig_recs) == 1
        assert not sig_recs[0].get("escalated")

    def test_manual_invocation_unrestricted(self, tmp_path, monkeypatch):
        """人工显式触发不受限：抑制判定不在 _invoke_administrator 本体。"""
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True)
        mon, runner, _ = _make_fixture_monitor(proot, True, monkeypatch)
        fp = _error_fingerprint("pm_engine", "manual noise (attempt 1)")

        mon._invoke_administrator(_daemon_error_signal(fp), None)

        assert len(runner.calls) == 1, "人工显式触发必须照常执行"

    def test_non_fixture_project_invokes_normally(self, tmp_path, monkeypatch):
        """非 fixture 项目照常召唤（fail-open 语义回归）。"""
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True)
        mon, runner, _ = _make_fixture_monitor(proot, False, monkeypatch)
        fp = _error_fingerprint("pm_engine", "real failure (attempt 1)")

        mon._handle_signal(_daemon_error_signal(fp))

        assert len(runner.calls) == 1


# ═══════════════════════════════════════════════════════════════════
# verify-fixture-guard：场景夹具注册静态扫描情报 + 规范固化存在性断言
# ═══════════════════════════════════════════════════════════════════

from core.verify_engine.scenario_static_check import (  # noqa: E402
    PATTERN_TABLE,
    scan_scenarios,
)

KNOWLEDGE_DOC_PATH = (
    Path(__file__).resolve().parents[1]
    / "spec" / "knowledge" / "domains" / "test-engineering"
    / "fixture-project-governance.md"
)
PLANNER_PLAN_PATH = (
    Path(__file__).resolve().parents[1] / "agents" / "planner-plan.md"
)


def _fixture_reg_scenario(command=None, stdin_text=None, kind="cli", sid="fx-scan-1"):
    """构造含场景命令注册夹具的 cli 场景（run 步骤）。"""
    step = {"action": "run"}
    if command is not None:
        step["command"] = command
    if stdin_text is not None:
        step["stdin"] = stdin_text
    return {"id": sid, "kind": kind, "steps": [step]}


class TestUnmarkedFixtureAddProjectScan:
    """tasks.md 3.1：add_project( 未带 fixture=True 产出静态扫描情报。"""

    def _findings(self, sc, serving_port="6000"):
        return [
            f for f in scan_scenarios([sc], serving_port=serving_port)
            if f.rule_id == "unmarked_fixture_add_project"
        ]

    def test_explicit_fixture_false_detected(self):
        # 本次事故形态：显式 fixture=False（selfheal-scratch-verify 同型）
        sc = _fixture_reg_scenario(
            stdin_text=(
                'import reg\n'
                'reg.add_project(SROOT, name="selfheal-scratch-verify", '
                'fixture=False)\n'
            ),
        )
        finds = self._findings(sc)
        assert len(finds) == 1
        assert finds[0].scenario_id == "fx-scan-1"
        assert finds[0].location == "steps[0].stdin"
        assert "fixture=True" in finds[0].message
        assert "fixture=False" in finds[0].message  # 情报引用原调用片段

    def test_default_omitted_detected(self):
        # 缺省不传 fixture：Registry.add_project 缺省 False，同属未打标
        sc = _fixture_reg_scenario(
            command="python3 -c \"import reg; reg.add_project('/tmp/probe')\"",
        )
        finds = self._findings(sc)
        assert len(finds) == 1
        assert finds[0].location == "steps[0].command"

    def test_explicit_fixture_true_not_flagged(self):
        sc = _fixture_reg_scenario(
            stdin_text='reg.add_project(SROOT, name="probe", fixture=True)\n',
        )
        assert self._findings(sc) == []

    def test_fixture_true_with_spaces_not_flagged(self):
        # fixture = True（等号带空白）同认已打标，不产误报
        sc = _fixture_reg_scenario(
            stdin_text="reg.add_project( SROOT, name='probe', fixture = True )\n",
        )
        assert self._findings(sc) == []

    def test_mark_fixture_call_not_flagged(self):
        # mark_fixture 补标调用不是 add_project 注册，不产情报
        sc = _fixture_reg_scenario(
            stdin_text="reg.mark_fixture(SROOT, fixture=True)\n",
        )
        assert self._findings(sc) == []

    def test_list_command_form_joined_and_scanned(self):
        # cli command 支持 str/list 双形态：argv 逐项拼接后扫（同
        # stale_literal_port 手法），argv 项内嵌调用不漏报
        sc = _fixture_reg_scenario(
            command=[
                "python3", "-c",
                "reg.add_project(SROOT, name='p', fixture=False)",
            ],
        )
        finds = self._findings(sc)
        assert len(finds) == 1
        assert finds[0].location == "steps[0].command"

    def test_web_kind_not_scanned(self):
        # kinds 只覆盖 cli（本次事故形态）；web 场景无场景命令注册面
        sc = _fixture_reg_scenario(
            stdin_text="reg.add_project(SROOT, fixture=False)\n", kind="web",
        )
        assert self._findings(sc) == []

    def test_runs_without_serving_port(self):
        # need_port=False：serving 端口未知（None）时本规则仍执行
        sc = _fixture_reg_scenario(
            stdin_text="reg.add_project(SROOT, fixture=False)\n",
        )
        finds = self._findings(sc, serving_port=None)
        assert len(finds) == 1

    def test_pattern_table_entry_contract(self):
        # 表项约定：kinds 至少覆盖 cli；need_port=False（与端口无关）
        entry = next(
            r for r in PATTERN_TABLE
            if r["rule_id"] == "unmarked_fixture_add_project"
        )
        assert "cli" in entry["kinds"]
        assert entry["need_port"] is False


class TestGovernanceDocMustEntry:
    """领域文档新增 MUST 条目的存在性断言（沿用领域文档断言惯例）。"""

    def _doc_text(self):
        return KNOWLEDGE_DOC_PATH.read_text(encoding="utf-8")

    def test_must_rule_present(self):
        text = self._doc_text()
        assert "## 现行规则" in text
        assert "MUST" in text
        assert "fixture=True" in text
        assert "Registry.add_project" in text

    def test_rationale_and_incident_reference_present(self):
        text = self._doc_text()
        # 依据与降噪面两个依据点都要在场：ADR-163 + 直写不经摄取抑制、
        # 聚合分支 fixture 过滤是唯一降噪面
        assert "ADR-163" in text
        assert "摄取抑制" in text
        assert "唯一降噪面" in text
        assert "selfheal-scratch-verify" in text
        assert "arch-scratch-verify" in text

    def test_planner_prompt_carries_rule_with_examples(self):
        # 出题端触达（spec：规范可被出题端与知识层触达）：planner-plan.md
        # 载明 MUST 规则与正反示例
        text = PLANNER_PLAN_PATH.read_text(encoding="utf-8")
        assert "fixture=True" in text
        assert "MUST" in text
        assert "reg.add_project(SROOT" in text  # 正例/反例调用形态
