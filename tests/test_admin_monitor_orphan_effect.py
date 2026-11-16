"""admin-orphan-effect-generation-aware：生效核查代际感知 + 消解簿记测试。

对应 spec/changes/evo-admin-orphan-effect-generation-aware 的 tasks 2.1 / 2.2 / 2.3：
  - 2.1  三态锚定——处置后合法前移再冻结判「已生效、被新代际取代」不升级
        且回链新代际；处置真未生效（处置完成后无轨迹）仍升级人工；日志
        轮转缺失 fail-closed 仍升级
  - 2.2  轨迹匹配与时序门——``Gate transition:`` 复位行（channel=recovery）
        与普通 ``Transition:`` verified 行（channel=auto）均被识别；时间戳
        早于处置组完成锚点的轨迹不命中；Cannot/Invalid/Idempotent/
        Frozen-stripped 等非成功行不构成轨迹；非法 from→to / 他 spec 轨迹
        不命中
  - 2.3  消解簿记回归锚——已消解组重扫描不再重复转记/重开条目（旧信号已
        收口、新条目类型键独立于旧 sig_type）；未命中轨迹时旧组行为与现状
        一致（升级记录文案与 escalate=true 终结记录零漂移）
"""

from core.admin_monitor import _ORPHAN_SUPERSEDED_GENERATION_SIGNAL_TYPE
from core.admin_store import DISPOSITION, SIGNAL, HUMAN_SEVERITIES
from tests.helpers import iso_ago

from tests.test_admin_orphan_disposition_effect_check import (
    _append_signal,
    _backfills,
    _escalations,
    _make_final_group,
    _signal_by_id,
    make_monitor,
)


def _write_sm_log(proot, message, ts_iso, *, channel="auto", level="INFO",
                  filename="fenixd.log"):
    """写入一条 state_machine 留痕（fenixd.log JSON 行，形态随 message 自由）。"""
    import json

    log_dir = proot / ".fenix" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": ts_iso,
        "level": level,
        "component": "state_machine",
        "message": message,
        "context": {"channel": channel},
    }
    with (log_dir / filename).open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _superseded_entries(store):
    return [r for r in store.read_records()
            if r.get("kind") == SIGNAL
            and r.get("signal_type") == _ORPHAN_SUPERSEDED_GENERATION_SIGNAL_TYPE]


# ── 2.1 三态锚定 ────────────────────────────────────────


class TestGenerationAwareAnchoring:
    def test_advance_then_refreeze_superseded_no_escalation(self, tmp_path):
        """事故重放镜像：处置组终态后 spec 合法前移再冻结（STATE frozen=True）
        → 判「已生效、被新代际取代」：补记已消解、旧信号收口、新代际条目
        回链，不升级人工、无仲裁升级记录。"""
        proot, mon, store = make_monitor(
            tmp_path, {"spec-a": {"frozen": True, "status": "blocked"}}
        )
        sig = _append_signal(store, signal_type="stuck", spec="spec-a")
        _make_final_group(store, run_id="admin-gen-1", spec="spec-a",
                          signal_type="stuck")
        # 处置后轨迹（锚点 = 组内最新记录 created，130 分钟前）：复位直通道
        # blocked→testing（channel=recovery）→ 新一轮验证前移 testing→verified
        # （channel=auto）→ verified 洗白门禁再冻结（STATE frozen=True 现状）
        _write_sm_log(proot, "Gate transition: spec-a blocked → testing",
                      iso_ago(60), channel="recovery")
        _write_sm_log(proot, "Transition: spec-a testing → verified",
                      iso_ago(30), channel="auto")
        mon._recover_orphaned_dispositions()
        bfs = _backfills(store)
        assert len(bfs) == 1
        bf = bfs[0]
        assert bf["result"] == "resolved"
        assert bf["admin_run_id"] == "admin-gen-1"
        assert bf["spec"] == "spec-a"
        # 不带 escalate=true（终态留痕语义，非升级）
        assert not bf.get("escalate")
        # 轨迹证据行引用（补记与信号留痕均回链轨迹）
        ev = bf.get("evidence") or ""
        assert "推进轨迹" in ev and "Gate transition" in ev
        assert "新代际" in ev
        # 旧信号收口
        assert _signal_by_id(store, sig["id"])["handled"] is True
        # 新代际条目：开立即终态/handled 留痕形态，携带旧组引用与轨迹证据
        news = _superseded_entries(store)
        assert len(news) == 1
        ns = news[0]
        assert ns["handled"] is True
        assert not ns.get("escalated")
        assert ns["spec"] == "spec-a"
        assert ns["superseded_group"]["admin_run_id"] == "admin-gen-1"
        assert ns["superseded_group"]["signal_type"] == "stuck"
        assert "Gate transition" in (ns.get("evidence") or "")
        # 留痕形态不进未处理人工告警面（severity info ∉ HUMAN_SEVERITIES）
        assert ns["severity"] not in HUMAN_SEVERITIES
        # 不升级人工、不触发仲裁调查（零 ESCALATION 记录）
        assert _escalations(store) == []

    def test_frozen_without_trajectory_still_escalates(self, tmp_path):
        """处置真未生效（处置完成后无任何指向该 spec 的推进轨迹）→ 维持
        升级人工，行为与现状一致。"""
        proot, mon, store = make_monitor(
            tmp_path, {"spec-a": {"frozen": True, "status": "blocked"}}
        )
        sig = _append_signal(store, signal_type="stuck", spec="spec-a")
        _make_final_group(store, run_id="admin-gen-2", spec="spec-a",
                          signal_type="stuck")
        # 窗内只有他 spec 的轨迹（不锚定本组 spec）
        _write_sm_log(proot, "Transition: other-spec testing → verified",
                      iso_ago(30), channel="auto")
        mon._recover_orphaned_dispositions()
        assert _backfills(store) == []
        assert _superseded_entries(store) == []
        assert len(_escalations(store)) == 1
        assert _signal_by_id(store, sig["id"])["handled"] is False

    def test_missing_log_family_failclosed_escalates(self, tmp_path):
        """日志轮转缺失（logs 目录不存在/候选集全缺）→ 轨迹不可考维持
        fail-closed 升级，不因证据缺失放大豁免面。"""
        proot, mon, store = make_monitor(
            tmp_path, {"spec-a": {"frozen": True, "status": "blocked"}}
        )
        sig = _append_signal(store, signal_type="stuck", spec="spec-a")
        _make_final_group(store, run_id="admin-gen-3", spec="spec-a",
                          signal_type="stuck")
        assert not (proot / ".fenix" / "logs").exists()
        mon._recover_orphaned_dispositions()
        assert _backfills(store) == []
        assert len(_escalations(store)) == 1
        assert _signal_by_id(store, sig["id"])["handled"] is False


# ── 2.2 轨迹匹配与时序门 ────────────────────────────────


class TestTrajectoryMatchingAndTimeGate:
    def _frozen_scene(self, tmp_path, run_id):
        proot, mon, store = make_monitor(
            tmp_path, {"spec-a": {"frozen": True, "status": "blocked"}}
        )
        sig = _append_signal(store, signal_type="stuck", spec="spec-a")
        _make_final_group(store, run_id=run_id, spec="spec-a",
                          signal_type="stuck")
        return proot, mon, store, sig

    def test_gate_recovery_reset_line_recognized(self, tmp_path):
        """``Gate transition:`` 复位行（channel=recovery）单独即构成轨迹
        （解冻族谓词刻意排除 Gate 前缀——本契约必须命中）。"""
        proot, mon, store, sig = self._frozen_scene(tmp_path, "admin-traj-1")
        _write_sm_log(proot, "Gate transition: spec-a blocked → testing",
                      iso_ago(60), channel="recovery")
        mon._recover_orphaned_dispositions()
        assert len(_backfills(store)) == 1
        assert _signal_by_id(store, sig["id"])["handled"] is True

    def test_plain_auto_verified_line_recognized(self, tmp_path):
        """普通 ``Transition:`` verified 行（channel=auto）单独即构成轨迹
        （deliberate-channel 过滤排除 auto——本契约 channel 不限）。"""
        proot, mon, store, sig = self._frozen_scene(tmp_path, "admin-traj-2")
        _write_sm_log(proot, "Transition: spec-a testing → verified",
                      iso_ago(30), channel="auto")
        mon._recover_orphaned_dispositions()
        assert len(_backfills(store)) == 1
        assert _signal_by_id(store, sig["id"])["handled"] is True

    def test_trajectory_before_anchor_not_credited(self, tmp_path):
        """轨迹行时间戳早于处置组完成锚点（组内最新记录 created）→ 不构成
        轨迹证据，维持 fail-closed 判定。"""
        proot, mon, store, sig = self._frozen_scene(tmp_path, "admin-traj-3")
        # 锚点 = 组最新记录 created（130 分钟前）；行落 180 分钟前 < 锚点
        _write_sm_log(proot, "Gate transition: spec-a blocked → testing",
                      iso_ago(180), channel="recovery")
        mon._recover_orphaned_dispositions()
        assert _backfills(store) == []
        assert len(_escalations(store)) == 1
        assert _signal_by_id(store, sig["id"])["handled"] is False

    def test_non_success_lines_not_trajectory(self, tmp_path):
        """Cannot/Invalid/Idempotent/Frozen-stripped 等非成功形态（与
        _finish_transition 各非成功出口同文案）不构成轨迹。"""
        proot, mon, store, sig = self._frozen_scene(tmp_path, "admin-traj-4")
        _write_sm_log(proot, "Cannot transition nonexistent SPEC: spec-a",
                      iso_ago(60), level="WARNING")
        _write_sm_log(proot, "Invalid transition: spec-a blocked → testing",
                      iso_ago(58), level="ERROR")
        _write_sm_log(proot,
                      "Idempotent transition: spec-a blocked → blocked "
                      "(already in state, skipped)",
                      iso_ago(56), channel="recovery")
        _write_sm_log(proot,
                      "Frozen SPEC 'spec-a': transition blocked → testing "
                      "stripped — manual freeze intact, status unchanged",
                      iso_ago(54), channel="recovery", level="WARNING")
        mon._recover_orphaned_dispositions()
        assert _backfills(store) == []
        assert len(_escalations(store)) == 1
        assert _signal_by_id(store, sig["id"])["handled"] is False

    def test_illegal_transition_pair_not_trajectory(self, tmp_path):
        """from→to 不属合法迁移（implemented→verified 非法，
        VALID_TRANSITIONS[implemented] 仅 testing）→ 不构成轨迹。"""
        proot, mon, store, sig = self._frozen_scene(tmp_path, "admin-traj-5")
        _write_sm_log(proot, "Transition: spec-a implemented → verified",
                      iso_ago(60), channel="auto")
        mon._recover_orphaned_dispositions()
        assert _backfills(store) == []
        assert len(_escalations(store)) == 1

    def test_rotated_trajectory_recognized(self, tmp_path):
        """轨迹行已轮转进 fenixd.log.1（读面复用：轮转候选集 + mtime 剪枝
        同款）→ 仍被识别。"""
        proot, mon, store, sig = self._frozen_scene(tmp_path, "admin-traj-6")
        _write_sm_log(proot, "Transition: spec-a testing → verified",
                      iso_ago(60), channel="auto", filename="fenixd.log.1")
        mon._recover_orphaned_dispositions()
        assert len(_backfills(store)) == 1
        assert _signal_by_id(store, sig["id"])["handled"] is True


# ── 2.3 消解簿记回归锚 ──────────────────────────────────


class TestSupersededBookkeepingRegression:
    def test_resolved_group_rescan_no_double_bookkeeping(self, tmp_path):
        """已消解组重扫描：① 幂等（backfill 在场）+ ④ 门（旧信号已收口）
        双保险 → 不重复转记、不重复开立新代际条目；新条目类型键独立于旧
        sig_type（④ 门按旧键查询不再命中）。"""
        proot, mon, store = make_monitor(
            tmp_path, {"spec-a": {"frozen": True, "status": "blocked"}}
        )
        sig = _append_signal(store, signal_type="stuck", spec="spec-a")
        _make_final_group(store, run_id="admin-gen-4", spec="spec-a",
                          signal_type="stuck")
        _write_sm_log(proot, "Transition: spec-a testing → verified",
                      iso_ago(30), channel="auto")
        mon._recover_orphaned_dispositions()
        assert len(_backfills(store)) == 1
        assert len(_superseded_entries(store)) == 1
        # 重扫两轮：幂等
        mon._recover_orphaned_dispositions()
        mon._recover_orphaned_dispositions()
        assert len(_backfills(store)) == 1
        assert len(_superseded_entries(store)) == 1
        assert _escalations(store) == []
        assert _signal_by_id(store, sig["id"])["handled"] is True
        # ④ 门按旧 sig_type 查询不再命中（新条目类型键独立，且旧信号已收口）
        assert store.unhandled_signal_for("spec-a", "stuck") is None
        assert store.unhandled_signal_for(
            "spec-a", _ORPHAN_SUPERSEDED_GENERATION_SIGNAL_TYPE) is None

    def test_no_trajectory_legacy_escalation_shape_unchanged(self, tmp_path):
        """未命中轨迹时旧组行为与现状零漂移：升级记录文案、evidence、
        escalate=true 终结记录形态与既有收敛 ⑥ 出口一致。"""
        proot, mon, store = make_monitor(
            tmp_path, {"spec-a": {"frozen": True, "status": "blocked"}}
        )
        sig = _append_signal(store, signal_type="stuck", spec="spec-a")
        _make_final_group(store, run_id="admin-gen-5", spec="spec-a",
                          signal_type="stuck")
        mon._recover_orphaned_dispositions()
        escs = _escalations(store)
        assert len(escs) == 1
        esc = escs[0]
        assert esc["severity"] == "critical"
        assert esc["admin_run_id"] == "admin-gen-5"
        # 零漂移锚定：文案与既有收敛 ⑥ 出口逐字同款
        assert "生效核查未找到动作已实际生效的真实状态证据" in (
            esc.get("description") or "")
        assert "需人工介入" in (esc.get("description") or "")
        assert "维持滞留并升级人工" in (
            [r for r in store.read_records()
             if r.get("kind") == DISPOSITION
             and r.get("admin_run_id") == "admin-gen-5"
             and r.get("escalate") is True][0].get("actions_taken") or "")
        assert "未见解冻推进" in (esc.get("evidence") or "")
        # escalate=true 终结记录在场（本组此后整体进入 ② 豁免）
        group = [r for r in store.read_records()
                 if r.get("kind") == DISPOSITION
                 and r.get("admin_run_id") == "admin-gen-5"]
        assert any((r.get("status") or r.get("result")) == "escalated"
                   and r.get("escalate") is True for r in group)
        # 无新代际条目、无消解补记
        assert _superseded_entries(store) == []
        assert _backfills(store) == []
        assert _signal_by_id(store, sig["id"])["handled"] is False
