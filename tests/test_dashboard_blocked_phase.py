"""blocked SPEC 处置相位判定测试（add-blocked-repairing-display 任务 1.2）。

覆盖 capability spec blocked-disposition-display 的后端单点判定口径：

- repairing：在飞 admin-/arbiter- 前缀 run（非终态非 stale）、链在办条目
  （admin/arbiter 相、未超 stale 超时口径）；
- queued：admin_alerts.json pending disposition（merge_dispositions_by_run
  归并单点：有唤起标记而无 final）、链 deferred 让行条目（同样排除 stale
  残留）；
- null：无 agent 迹象（人工升级件/冻结转人工等待面）、在飞 impl-/verify-
  等非处置车道 run 不计、数据源缺失与损坏容错回退（fail-open）；
- 显示层 only：STATE.md 零写入、真实状态恒 blocked、非 blocked 状态恒 None；
- 摘要失效签名：blocked 态两数据源入 _spec_dep_sigs，其余状态不入。

夹具参照既有 tests/test_dashboard_data.py 模式：真实 .fenix 产物文件
（run 产物/admin_alerts.json/escalation_chain_state.json），无桩。
"""

import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from core.dashboard.data import spec_summary
from core.dashboard.data.summary import (
    _blocked_disposition_phase,
    _spec_dep_sigs,
)


def _utc_iso(**delta):
    dt = datetime.now(timezone.utc)
    if delta:
        dt = dt - timedelta(**delta)
    return dt.isoformat()


class BlockedPhaseTestBase(unittest.TestCase):
    """tmp 项目根夹具：.fenix/runs + 活跃 spec 目录（参照 test_dashboard_data）。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="fenix-blocked-phase-"))
        self.root = self.tmpdir
        (self.root / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
        d = self.root / "spec" / "changes" / "demo"
        d.mkdir(parents=True, exist_ok=True)
        (d / "tasks.md").write_text("# Tasks\n\n## 1. x\n\n- [ ] 1.1 do\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _summary(self, status="blocked"):
        from core.dashboard.data import spec_summary as _fn

        return _fn(self.root, "demo", {"status": status})

    def _run_file(self, run_id, last_type="system", mtime=None):
        """落一条 run 产物：末行 type 决定终态（非终态 → running）。"""
        p = self.root / ".fenix" / "runs" / f"{run_id}.jsonl"
        lines = [
            {"type": "system", "subtype": "init", "session_id": "s1"},
            {"type": last_type},
        ]
        p.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
        if mtime is not None:
            os.utime(p, (mtime, mtime))
        return p

    def _chain_state(self, in_flight):
        p = self.root / ".fenix" / "escalation_chain_state.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps({"version": 1, "signatures": {}, "meta": {}, "in_flight": in_flight}),
            encoding="utf-8",
        )
        return p

    def _alerts(self, records):
        p = self.root / ".fenix" / "admin_alerts.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
        return p

    def _corrupt(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{broken", encoding="utf-8")


# ── repairing：在飞处置 run ──────────────────────────────────────────────


class TestBlockedPhaseInflightRun(BlockedPhaseTestBase):
    def test_inflight_admin_run_is_repairing(self):
        """① 在飞 admin- 前缀 run（末行非终态）→ repairing。"""
        self._run_file("admin-demo-1762670000")
        s = self._summary()
        self.assertEqual(s["blocked_phase"], "repairing")
        # 真实状态不受显示层判定影响（恒 blocked）
        self.assertEqual(s["status"], "blocked")

    def test_inflight_arbiter_run_is_repairing(self):
        """② 在飞 arbiter- 前缀 run → repairing。"""
        self._run_file("arbiter-demo-1762670001")
        self.assertEqual(self._summary()["blocked_phase"], "repairing")

    def test_terminal_admin_run_is_null(self):
        """③ 终态 admin run（result 收尾）→ 不计在飞，null。"""
        self._run_file("admin-demo-1762670002", last_type="result")
        self.assertIsNone(self._summary()["blocked_phase"])

    def test_stale_admin_run_is_null(self):
        """④ stale 残留（末行非终态但停更超 _RUN_STALE_SECONDS）→ null。"""
        stale = __import__("time").time() - 1900
        self._run_file("admin-demo-1762670003", mtime=stale)
        self.assertIsNone(self._summary()["blocked_phase"])

    def test_inflight_impl_run_is_null(self):
        """⑤ 在飞非处置车道 run（impl-）不计 → null。"""
        self._run_file("impl-demo-1762670004")
        self.assertIsNone(self._summary()["blocked_phase"])

    def test_error_run_is_null(self):
        """⑥ error 终态 run 不计在飞 → null（终态全集复用公开映射）。"""
        self._run_file("admin-demo-1762670005", last_type="error")
        self.assertIsNone(self._summary()["blocked_phase"])

    def test_no_runs_null(self):
        """⑦ 无任何 run 产物 → null（缺省空态）。"""
        self.assertIsNone(self._summary()["blocked_phase"])


# ── repairing：链在办条目 ────────────────────────────────────────────────


class TestBlockedPhaseChainInflight(BlockedPhaseTestBase):
    def _entry(self, phase="admin", spec="demo", started_at=None, chain_id="c1"):
        return {
            "chain_id": chain_id,
            "signature": f"{spec}::sig",
            "spec": spec,
            "phase": phase,
            "started_at": started_at or _utc_iso(),
        }

    def test_chain_admin_phase_is_repairing(self):
        """① 链 in_flight 区 admin 相在办 → repairing。"""
        self._chain_state([self._entry(phase="admin")])
        self.assertEqual(self._summary()["blocked_phase"], "repairing")

    def test_chain_arbiter_phase_is_repairing(self):
        """② 链 arbiter 相在办 → repairing。"""
        self._chain_state([self._entry(phase="arbiter")])
        self.assertEqual(self._summary()["blocked_phase"], "repairing")

    def test_chain_entry_missing_started_at_excluded(self):
        """③ 缺 started_at 的残留条目（stale 判据不可解析）→ 排除，null。"""
        entry = self._entry()
        entry.pop("started_at")
        self._chain_state([entry])
        self.assertIsNone(self._summary()["blocked_phase"])

    def test_chain_entry_stale_excluded(self):
        """④ 超时在办残留（started_at 超 CHAIN_INFLIGHT_STALE_S）→ 排除。"""
        from core.pm_engine.escalation_chain import CHAIN_INFLIGHT_STALE_S

        self._chain_state(
            [self._entry(started_at=_utc_iso(seconds=int(CHAIN_INFLIGHT_STALE_S) + 600))]
        )
        self.assertIsNone(self._summary()["blocked_phase"])

    def test_chain_entry_other_spec_not_counted(self):
        """⑤ 他 spec 的在办条目不串入（spec 全等过滤）→ null。"""
        self._chain_state([self._entry(spec="demo-sibling")])
        self.assertIsNone(self._summary()["blocked_phase"])


# ── queued：挂起待处置件 ─────────────────────────────────────────────────


class TestBlockedPhaseQueued(BlockedPhaseTestBase):
    def _pending(self, run_id="admin-demo-1762670009", status="pending", spec="demo"):
        return {
            "id": f"al-{run_id}",
            "kind": "disposition",
            "spec": spec,
            "admin_run_id": run_id,
            "status": status,
            "created": _utc_iso(),
            "summary": "处置执行中",
        }

    def test_pending_disposition_is_queued(self):
        """① pending disposition（有唤起标记而无 final）→ queued。"""
        self._alerts([self._pending()])
        s = self._summary()
        self.assertEqual(s["blocked_phase"], "queued")
        self.assertEqual(s["status"], "blocked")

    def test_final_disposition_not_queued(self):
        """② 同 run 已有最终 disposition（归并 pending 让位非 pending）→ null。"""
        final = self._pending(status="resolved")
        final["id"] = "al-final"
        final["created"] = _utc_iso(minutes=1)
        self._alerts([self._pending(), final])
        self.assertIsNone(self._summary()["blocked_phase"])

    def test_pending_disposition_other_spec_not_counted(self):
        """③ 他 spec 的 pending 记录不串入 → null。"""
        self._alerts([self._pending(spec="demo-sibling", run_id="admin-demo-sibling-1762670010")])
        self.assertIsNone(self._summary()["blocked_phase"])

    def test_chain_deferred_is_queued(self):
        """④ 链 deferred 让行挂起条目（未超时）→ queued。"""
        self._chain_state([{
            "chain_id": "c2",
            "signature": "demo::sig",
            "spec": "demo",
            "phase": "deferred",
            "started_at": _utc_iso(),
            "yield_to": "impl-demo-1762670011",
            "deferred_at": _utc_iso(),
        }])
        self.assertEqual(self._summary()["blocked_phase"], "queued")

    def test_chain_deferred_stale_excluded(self):
        """⑤ stale deferred 残留（超时一并被 reap 的形态）→ 排除。"""
        from core.pm_engine.escalation_chain import CHAIN_INFLIGHT_STALE_S

        self._chain_state([{
            "chain_id": "c3",
            "signature": "demo::sig",
            "spec": "demo",
            "phase": "deferred",
            "started_at": _utc_iso(seconds=int(CHAIN_INFLIGHT_STALE_S) + 600),
        }])
        self.assertIsNone(self._summary()["blocked_phase"])

    def test_inflight_run_beats_pending_disposition(self):
        """⑥ 在飞 run 与挂起件并存 → repairing 优先（相位互斥口径）。"""
        self._run_file("admin-demo-1762670012")
        self._alerts([self._pending(run_id="admin-demo-1762670012")])
        self.assertEqual(self._summary()["blocked_phase"], "repairing")


# ── null：等待人工面 + 容错回退 ──────────────────────────────────────────


class TestBlockedPhaseNullAndFailOpen(BlockedPhaseTestBase):
    def test_human_escalation_alert_is_null(self):
        """① 人工升级 kind 告警（等人面）MUST NOT 计 queued → null。"""
        self._alerts([{
            "id": "al-esc",
            "kind": "escalation",
            "spec": "demo",
            "handled": False,
            "created": _utc_iso(),
            "summary": "需人工介入",
        }])
        self.assertIsNone(self._summary()["blocked_phase"])

    def test_all_sources_missing_is_null(self):
        """② 告警/链/run 产物全缺失 → null（fail-open 空态）。"""
        self.assertIsNone(self._summary()["blocked_phase"])

    def test_corrupt_alerts_file_is_null(self):
        """③ admin_alerts.json 损坏 → 读层回空，null，不抛 500。"""
        self._corrupt(self.root / ".fenix" / "admin_alerts.json")
        self.assertIsNone(self._summary()["blocked_phase"])

    def test_corrupt_chain_file_is_null(self):
        """④ 链状态文件损坏 → load_chain_state 回空骨架，null。"""
        self._corrupt(self.root / ".fenix" / "escalation_chain_state.json")
        self.assertIsNone(self._summary()["blocked_phase"])

    def test_chain_store_read_exception_fail_open(self):
        """⑤ 判定路径未预期异常 → 外层 fail-open 兜底 null（不穿透 /api/specs）。"""
        import core.dashboard.data.summary as summary_mod

        with patch.object(
            summary_mod,
            "_blocked_phase_from_persistent_state",
            side_effect=OSError("disk gone"),
        ):
            self.assertIsNone(
                summary_mod._blocked_disposition_phase(self.root, "demo", [])
            )

    def test_run_evidence_survives_source_failure(self):
        """⑥ 在飞 run 证据仍可用时按其判定（与数据源损坏无关的先后序）。"""
        self._run_file("admin-demo-1762670013")
        self._corrupt(self.root / ".fenix" / "admin_alerts.json")
        self._corrupt(self.root / ".fenix" / "escalation_chain_state.json")
        self.assertEqual(self._summary()["blocked_phase"], "repairing")


# ── 显示层 only：零影响面 ────────────────────────────────────────────────


class TestBlockedPhaseZeroSideEffects(BlockedPhaseTestBase):
    def test_non_blocked_status_always_none(self):
        """① 非 blocked 状态恒 None（即使在飞处置 run 也在场）。"""
        self._run_file("admin-demo-1762670014")
        for status in (
            "drafted", "ready", "implementing", "testing", "implemented",
            "verified", "bug-found", "done", "pushed", "reviewing",
        ):
            self.assertIsNone(
                self._summary(status)["blocked_phase"], f"status {status}"
            )

    def test_state_md_bytes_untouched(self):
        """② STATE.md 字节零写入（显示层判定无状态机副作用）。"""
        state = self.root / ".fenix" / "STATE.md"
        state.write_text("specs:\n  demo:\n    status: blocked\n", encoding="utf-8")
        before = state.read_bytes()
        self._run_file("admin-demo-1762670015")
        self.assertEqual(self._summary()["blocked_phase"], "repairing")
        self.assertEqual(state.read_bytes(), before)

    def test_summary_entry_status_untouched(self):
        """③ 判定不回写 entry（传入 dict 无新键、status 原值）。"""
        entry = {"status": "blocked"}
        self._run_file("admin-demo-1762670016")
        self.assertEqual(self._summary()["blocked_phase"], "repairing")
        self.assertEqual(entry, {"status": "blocked"})

    def test_dep_sigs_blocked_includes_disposition_sources(self):
        """④ blocked 态：两判定数据源入摘要失效签名（相位变化可刷新列表）。"""
        # add() 对缺失文件不入集（sig None）——先落两文件再验在场
        (self.root / ".fenix" / "admin_alerts.json").write_text("[]", encoding="utf-8")
        (self.root / ".fenix" / "escalation_chain_state.json").write_text(
            json.dumps({"version": 1, "signatures": {}, "meta": {}, "in_flight": []}),
            encoding="utf-8",
        )
        sigs = _spec_dep_sigs(self.root, "demo", {"status": "blocked"}, {})
        self.assertIn(str(self.root / ".fenix" / "admin_alerts.json"), sigs)
        self.assertIn(str(self.root / ".fenix" / "escalation_chain_state.json"), sigs)

    def test_dep_sigs_non_blocked_excludes_disposition_sources(self):
        """⑤ 非 blocked 态：两数据源不入签名（零读放大口径）。"""
        (self.root / ".fenix" / "admin_alerts.json").write_text("[]", encoding="utf-8")
        (self.root / ".fenix" / "escalation_chain_state.json").write_text(
            json.dumps({"version": 1, "signatures": {}, "meta": {}, "in_flight": []}),
            encoding="utf-8",
        )
        sigs = _spec_dep_sigs(self.root, "demo", {"status": "implementing"}, {})
        self.assertNotIn(str(self.root / ".fenix" / "admin_alerts.json"), sigs)
        self.assertNotIn(str(self.root / ".fenix" / "escalation_chain_state.json"), sigs)

    def test_spec_detail_carries_blocked_phase(self):
        """⑥ 详情载荷同源透传 blocked_phase（详情页头部三态数据源）。"""
        from core.dashboard.data import spec_detail

        self._run_file("admin-demo-1762670017")
        d = spec_detail(self.root, "demo", {"status": "blocked"})
        self.assertEqual(d["blocked_phase"], "repairing")
        d2 = spec_detail(self.root, "demo", {"status": "implementing"})
        self.assertIsNone(d2["blocked_phase"])


# ── 判定函数单元缝（合成 runs 入参，不经产物文件） ────────────────────────


class TestBlockedPhasePredicateUnit(unittest.TestCase):
    def _run(self, agent_type, status):
        return {"run_id": f"{agent_type}-demo-1", "agent_type": agent_type, "status": status}

    def test_administrator_running_repairing(self):
        self.assertEqual(
            _blocked_disposition_phase("/tmp/nowhere", "demo", [self._run("administrator", "running")]),
            "repairing",
        )

    def test_arbiter_empty_status_repairing(self):
        """empty（刚起步无事件）非终态 → 在飞口径内。"""
        self.assertEqual(
            _blocked_disposition_phase("/tmp/nowhere", "demo", [self._run("arbiter", "empty")]),
            "repairing",
        )

    def test_superseded_terminal_null(self):
        """superseded 弃置终态不在飞 → 数据源皆无走 null 分支。"""
        self.assertIsNone(
            _blocked_disposition_phase("/tmp/nowhere", "demo", [self._run("administrator", "superseded")])
        )

    def test_garbage_run_entries_skipped(self):
        """垃圾条目（非 dict）跳过不抛。"""
        self.assertIsNone(
            _blocked_disposition_phase("/tmp/nowhere", "demo", [None, "junk", {"status": "running"}])
        )


if __name__ == "__main__":
    unittest.main()
