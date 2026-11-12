"""consolidate-alerts-to-ops-page：告警零后台派发契约测试（tasks 3.4 新建）。

调查叙事生成链退役（模块 core/adjudication_narrative 已删除）后的四块契约：
- 迁移后让位判定语义：链头派发判定迁居 core.pm_engine.family.yielded_to_arbiter
  （1.1，判定与叙事无关），侧车辅助函数迁居 core.admin_store（1.4）；
- 不让位与判定异常时零后台派发零 LLM 调用（1.2：告警机械文案落盘即可裁决，
  「调查生成中」占位随之退役）；
- 旁路发射点（mergeback 产物配置信号 / token_budget 预算告警）零叙事 attach（1.3）；
- 新告警无 narrative 字段、无新侧车目录。

存量 config 携带 narrative_* 残留键的 loader 容忍断言（2.1 附带）在
tests/test_system_settings_config.py；读侧合并/级联删除/原子写在
tests/test_narrative_sidecar.py（收缩版）。

假通道时代已终结：本文件全部零 LLM——subprocess.Popen 以 canary 打桩，
任何一次 spawn 即断言失败。
"""

import importlib
import subprocess

import pytest

from core.admin_store import (
    ESCALATION,
    AdminStore,
    SIDECAR_DIRNAME,
    delete_narrative_sidecars,
    load_narrative_sidecars,
    write_narrative_sidecar,
)
from core.pm_engine.arbiter import set_lane
from core.pm_engine.escalation_chain import reset_chain, set_chain
from core.pm_engine.family import FamilyGovernor, yielded_to_arbiter
from tests.test_arbiter_lane import FakeLogger, make_lane

SIGNAL = "verify_env_blocked"


class _RecLogger:
    """记录型 logger（family 咽喉口径：warning(component, message)）。"""

    def __init__(self):
        self.warnings = []
        self.errors = []

    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def warning(self, *a):
        self.warnings.append(a)

    def error(self, *a):
        self.errors.append(a)


class _FakePM:
    def __init__(self, root):
        self.project_root = root
        self.logger = _RecLogger()


@pytest.fixture(autouse=True)
def _isolated_singletons(tmp_path):
    """链/车道单例隔离：每个用例前后清空，防跨用例污染。"""
    set_lane(None)
    set_chain(None)
    reset_chain()
    yield
    set_lane(None)
    set_chain(None)
    reset_chain()


def _make_governor(root) -> FamilyGovernor:
    governor = FamilyGovernor.__new__(FamilyGovernor)
    governor._pm = _FakePM(root)
    return governor


def _no_llm(monkeypatch):
    """零 LLM canary：告警链路上任何一次进程 spawn 即断言失败。"""

    def _forbidden(*a, **k):
        raise AssertionError("零后台派发契约被破坏：告警路径出现了进程 spawn（LLM 调用）")

    monkeypatch.setattr(subprocess, "Popen", _forbidden)


# ── 迁移后让位判定语义（1.1）────────────────────────────


class TestMigratedYieldSemantics:
    def test_narrative_module_deleted(self):
        """生成链模块整体退役：import 即 ModuleNotFoundError（防回潮第一道）。"""
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("core.adjudication_narrative")

    def test_migrated_symbols_live_in_new_homes(self):
        """判定居 family、侧车辅助居 admin_store（拆分后新址）。"""
        import core.admin_store as admin_store

        assert callable(yielded_to_arbiter)
        assert callable(admin_store.write_narrative_sidecar)
        assert callable(admin_store.load_narrative_sidecars)
        assert callable(admin_store.delete_narrative_sidecars)
        assert admin_store.SIDECAR_DIRNAME == "admin_alerts_narrative"

    def test_chain_active_non_blacklist_yields(self, tmp_path):
        """链激活（enabled + 装配完备）∧ 非黑名单 → True（链头派发）。"""
        reset_chain()
        set_lane(make_lane(tmp_path))
        assert yielded_to_arbiter(
            SIGNAL, {"project_root": tmp_path, "logger": None}
        ) is True

    def test_no_chain_no_yield(self, tmp_path, monkeypatch):
        """链单例缺席（get_chain 返回 None）→ False（降级件零后台派发）。

        注：get_chain(显式 root) 会惰性建链，「无链」形态须在注册层面缺席
        （monkeypatch 返回 None）才是确定性环境。
        """
        import core.pm_engine.escalation_chain as chain_mod

        monkeypatch.setattr(chain_mod, "get_chain", lambda *a, **k: None)
        assert yielded_to_arbiter(
            SIGNAL, {"project_root": tmp_path, "logger": None}
        ) is False

    def test_disabled_config_no_yield(self, tmp_path):
        """arbiter.enabled=false → False（关闭态链头不接手）。"""
        (tmp_path / ".fenix").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".fenix" / "config.yaml").write_text(
            "arbiter:\n  enabled: false\n", encoding="utf-8"
        )
        set_lane(None)
        assert yielded_to_arbiter(
            SIGNAL, {"project_root": tmp_path, "logger": None}
        ) is False

    def test_blacklisted_signal_no_yield(self, tmp_path):
        """黑名单 kill switch：名单内信号留人类，链激活也让位 False。"""
        from core.pm_engine.escalation_chain import reset_chain as _rc

        set_lane(None)
        _rc()
        (tmp_path / ".fenix").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".fenix" / "config.yaml").write_text(
            "arbiter:\n  enabled: true\n"
            f"chain:\n  blacklist: [{SIGNAL}]\n",
            encoding="utf-8",
        )
        set_lane(make_lane(tmp_path))
        try:
            assert yielded_to_arbiter(
                SIGNAL, {"project_root": tmp_path, "logger": None}
            ) is False
        finally:
            set_lane(None)

    def test_missing_project_root_no_yield(self):
        """project_root 缺席（病态上下文）→ False（不让位降级）。"""
        set_lane(None)
        assert yielded_to_arbiter(SIGNAL, {"logger": None}) is False
        assert yielded_to_arbiter(SIGNAL, None) is False

    def test_judgment_exception_fails_open_to_no_yield(self, tmp_path, monkeypatch):
        """判定异常按不让位降级（fail-open）→ False。"""

        def boom(*a, **k):
            raise RuntimeError("chain registry corrupted")

        import core.pm_engine.escalation_chain as chain_mod

        monkeypatch.setattr(chain_mod, "get_chain", boom)
        assert yielded_to_arbiter(
            SIGNAL, {"project_root": tmp_path, "logger": None}
        ) is False

    def test_yield_decision_side_effect_free(self, tmp_path):
        """判定零副作用：判定动作不产生任何侧车文件。"""
        set_lane(None)
        assert yielded_to_arbiter(
            SIGNAL, {"project_root": tmp_path, "logger": None}
        ) is False
        assert not (tmp_path / ".fenix" / SIDECAR_DIRNAME).exists()


# ── 不让位/判定异常 → 零后台派发零 LLM（1.2）───────────


class TestThroatZeroBackgroundDispatch:
    def test_degraded_alert_lands_zero_background(self, tmp_path, monkeypatch):
        """链失能降级件：告警机械文案落盘、无 narrative 字段、无侧车、零 spawn。"""
        _no_llm(monkeypatch)
        set_lane(None)
        set_chain(None)
        governor = _make_governor(tmp_path)
        governor._send_human_escalation_alert(
            "spec-a", SIGNAL, "major", "验证环境阻塞", "env log", "修复环境",
        )
        recs = AdminStore(tmp_path, _RecLogger()).read_all()
        assert len(recs) == 1
        rec = recs[0]
        assert rec["kind"] == ESCALATION and rec["signal_type"] == SIGNAL
        assert "narrative" not in rec, "新告警 MUST NOT 携带 narrative 字段"
        assert load_narrative_sidecars(tmp_path) == {}, "零侧车（零后台派发）"
        assert not (tmp_path / ".fenix" / SIDECAR_DIRNAME).exists()

    def test_judgment_exception_zero_dispatch_alert_still_lands(
        self, tmp_path, monkeypatch
    ):
        """判定环节抛异常：告警照常落盘、零后台派发、判定异常 WARNING 留痕。"""
        _no_llm(monkeypatch)
        set_lane(None)
        set_chain(None)

        def boom(*a, **k):
            raise RuntimeError("yield decision exploded")

        import core.pm_engine.family as family_mod

        monkeypatch.setattr(family_mod, "yielded_to_arbiter", boom)
        governor = _make_governor(tmp_path)
        governor._send_human_escalation_alert(
            "spec-a", SIGNAL, "major", "d", "e", "r",
        )
        recs = AdminStore(tmp_path, _RecLogger()).read_all()
        assert len(recs) == 1 and "narrative" not in recs[0]
        assert load_narrative_sidecars(tmp_path) == {}
        assert any(
            "零后台派发" in str(w) for w in governor._pm.logger.warnings
        ), "判定异常 MUST 留痕（零后台派发口径）"

    def test_yielded_chain_path_still_dispatches_lane(self, tmp_path):
        """链可用时链头派发语义不变（守住判定迁移不破坏既有改道行为）。"""
        from core.pm_engine.escalation_chain import get_chain

        reset_chain()
        chain = get_chain(tmp_path, FakeLogger())
        captured = {}

        def fake_submit_entry(**kwargs):
            captured.update(kwargs)
            return "queued"

        chain.submit_entry = fake_submit_entry

        class _PM:
            project_root = tmp_path
            logger = FakeLogger()

        governor = FamilyGovernor.__new__(FamilyGovernor)
        governor._pm = _PM()
        try:
            governor._send_human_escalation_alert(
                "spec-a", SIGNAL, "major", "d", "e", "r",
            )
        finally:
            reset_chain()
        assert captured.get("spec") == "spec-a"
        # 链接单后零人工落盘（链内自动化处置零人工感知）
        assert AdminStore(tmp_path, FakeLogger()).read_all() == []


# ── 旁路发射点零叙事 attach（1.3）───────────────────────


class TestBypassEmittersZeroAttach:
    def test_mergeback_artifact_signal_no_narrative(self, tmp_path, monkeypatch):
        """mergeback 产物配置未裁决信号：记录零 narrative 字段、零侧车。"""
        from core.worktree_manager.mergeback import G4MergebackMixin

        class _UnresolvedArtifacts:
            @staticmethod
            def is_config_unresolved():
                return True

        mgr = G4MergebackMixin.__new__(G4MergebackMixin)
        mgr.project_root = tmp_path
        mgr.logger = _RecLogger()
        mgr._artifacts = _UnresolvedArtifacts()
        # _spec_from_branch 居 queries 混入类（G4MergebackMixin 不自带）——
        # 裸实例上直接绑规格名解析替身
        mgr._spec_from_branch = lambda branch: "spec-a"
        mgr._maybe_signal_build_artifact_paths_missing("fenix/spec-a")
        recs = AdminStore(tmp_path, _RecLogger()).read_all()
        assert len(recs) == 1, "信号照常落盘（发射行为本体不变）"
        assert "narrative" not in recs[0]
        assert load_narrative_sidecars(tmp_path) == {}

    def test_token_budget_alert_no_narrative(self, tmp_path, monkeypatch):
        """token_budget 预算告警（直写 AdminStore 旁路）：零 narrative、零侧车。"""
        from core.agent_runner.token_budget import TokenAccountant

        _no_llm(monkeypatch)
        accountant = TokenAccountant.__new__(TokenAccountant)
        accountant._pm = _FakePM(tmp_path)
        accountant._send_token_alert(
            "spec-a", 1_800_000, 2.0, "warning", "预算 80% 提醒告警"
        )
        recs = AdminStore(tmp_path, _RecLogger()).read_all()
        assert len(recs) == 1
        rec = recs[0]
        assert rec["signal_type"] == "token_budget"
        assert "narrative" not in rec
        assert load_narrative_sidecars(tmp_path) == {}


# ── 新告警无 narrative 字段无新侧车 ─────────────────────


class TestNewAlertsNoNarrative:
    def test_append_never_creates_sidecar_dir(self, tmp_path):
        """纯 append 不建侧车目录（目录只由写侧辅助函数按需创建）。"""
        store = AdminStore(tmp_path, _RecLogger())
        rec = store.append({
            "kind": ESCALATION,
            "signal_type": SIGNAL,
            "spec": "spec-a",
            "severity": "major",
            "description": "d",
        })
        assert "narrative" not in rec
        assert not (tmp_path / ".fenix" / SIDECAR_DIRNAME).exists()

    def test_read_side_never_derives_pending_marker(self, tmp_path):
        """读侧不派生 narrative_pending（占位退役）；历史侧车仍按 alert_id 合并。"""
        from core.dashboard.data import admin_alerts

        store = AdminStore(tmp_path, _RecLogger())
        rec = store.append({
            "kind": ESCALATION,
            "signal_type": SIGNAL,
            "spec": "spec-a",
            "severity": "major",
            "description": "d",
        })
        write_narrative_sidecar(tmp_path, rec["id"], "历史报告", "m")
        items = admin_alerts.get_alerts(tmp_path)
        assert all("narrative_pending" not in a for a in items)
        merged = next(a for a in items if a["id"] == rec["id"])
        assert merged["narrative"]["text"] == "历史报告"

    def test_cascade_delete_api_unchanged(self, tmp_path):
        """级联删除辅助迁址后契约不变：删 alert_ids 返回删除数。"""
        store = AdminStore(tmp_path, _RecLogger())
        r1 = store.append({"kind": ESCALATION, "signal_type": SIGNAL,
                           "spec": "a", "severity": "major", "description": "d"})
        r2 = store.append({"kind": ESCALATION, "signal_type": SIGNAL,
                           "spec": "b", "severity": "major", "description": "d"})
        for r in (r1, r2):
            assert write_narrative_sidecar(tmp_path, r["id"], "t", None)
        deleted = delete_narrative_sidecars(tmp_path, [r1["id"], r2["id"]])
        assert deleted == 2
        assert load_narrative_sidecars(tmp_path) == {}
