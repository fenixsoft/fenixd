"""
Tests for SPEC 软删除与告警台账联动（add-spec-softdelete-alert-linkage）。

四组场景：
1. 软删除成功关闭双 kind 未处理告警（注记含归档目录）；
2. 已 handled 告警与 disposition 台账逐位不动；
3. 告警写回失败时删除本体仍成功且如实回报（fail-open）；
4. ``found=False`` 幂等成功与存量 spec 丢弃行为不变。
"""
import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.admin_store import AdminStore
from core.dashboard.data.admin_actions import _exec_abandon
from core.dashboard.data.spec_archive import soft_delete_spec


def _make_project(root: Path, specs: dict) -> Path:
    """构造最小可用项目：.fenix/STATE.md + spec/changes/<name>/ 目录。

    specs: {name: {"status": ...}}；entry 为 None 时只建 STATE 条目不建目录
    （目录缺失仅清状态形态的夹具）。
    """
    (root / "spec" / "changes").mkdir(parents=True, exist_ok=True)
    (root / ".fenix").mkdir(parents=True, exist_ok=True)
    lines = ["# Fenix Project State", "", "## Specs", ""]
    for name, entry in specs.items():
        if entry is not None:
            (root / "spec" / "changes" / name).mkdir(exist_ok=True)
            (root / "spec" / "changes" / name / "tasks.md").write_text(
                "# T", encoding="utf-8")
        lines.append(f"### {name}")
        lines.append(f"- status: {entry['status'] if entry else 'implementing'}")
        lines.append("- updated: 2026-01-01T00:00:00+00:00")
        lines.append("")
    (root / ".fenix" / "STATE.md").write_text("\n".join(lines), encoding="utf-8")
    return root


def _seed_alert(root: Path, **kw) -> dict:
    """经 AdminStore 正常写入口落一条告警（默认未处理 escalation、spec 指定）。"""
    entry = {
        "kind": "escalation",
        "signal_type": "spec-review-rejected",
        "severity": "major",
        "description": "测试告警",
    }
    entry.update(kw)
    rec = AdminStore(root).append(entry)
    assert rec is not None, "夹具告警落盘失败"
    return rec


def _unhandled(root: Path) -> list:
    return [r for r in AdminStore(root).read_all() if not r.get("handled")]


class _LinkageBase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class TestSoftDeleteClosesUnhandledAlerts(_LinkageBase):
    """组 1：软删除成功联动关闭双 kind 未处理告警，注记按删除形态。"""

    def test_softdelete_closes_escalation_and_signal(self):
        _make_project(self.root, {"spec-doomed": {"status": "implementing"}})
        esc = _seed_alert(self.root, kind="escalation", spec="spec-doomed")
        sig = _seed_alert(self.root, kind="signal", spec="spec-doomed",
                          signal_type="blocked_stuck")
        other = _seed_alert(self.root, kind="escalation", spec="spec-keeper")
        before = len(_unhandled(self.root))

        result = soft_delete_spec(self.root, "spec-doomed")

        self.assertIsNone(result["error"])
        self.assertTrue(result["archived"])
        self.assertEqual(result["alerts_closed"], 2)
        self.assertNotIn("alert_link_error", result)
        # 目录已迁移至 spec/archive/<名>-<Unix秒>/
        self.assertFalse((self.root / "spec" / "changes" / "spec-doomed").is_dir())
        archive_dir = next((self.root / "spec" / "archive").iterdir())
        self.assertTrue(archive_dir.name.startswith("spec-doomed-"))
        recs = {r["id"]: r for r in AdminStore(self.root).read_all()}
        for aid in (esc["id"], sig["id"]):
            r = recs[aid]
            self.assertTrue(r["handled"])
            self.assertEqual(r["handled_by"], "spec-softdeleted")
            self.assertTrue(r["handled_at"])
            # 注记含归档目录名（目录迁移形态）
            self.assertIn(f"spec/archive/{archive_dir.name}", r["resolve_note"])
            self.assertIn("关联告警联动关闭", r["resolve_note"])
        # 未处理告警计数随之减少；他 spec 告警不受牵连
        self.assertEqual(len(_unhandled(self.root)), before - 2)
        self.assertFalse(recs[other["id"]]["handled"])

    def test_softdelete_note_no_dir_form(self):
        # 条目在 STATE 而目录缺失：仅清状态形态，注记如实无目录
        _make_project(self.root, {"spec-nodir": None})
        alert = _seed_alert(self.root, kind="escalation", spec="spec-nodir")

        result = soft_delete_spec(self.root, "spec-nodir")

        self.assertIsNone(result["error"])
        self.assertFalse(result["archived"])
        self.assertEqual(result["alerts_closed"], 1)
        recs = {r["id"]: r for r in AdminStore(self.root).read_all()}
        note = recs[alert["id"]]["resolve_note"]
        self.assertIn("无目录，仅清理状态登记", note)
        self.assertNotIn("归档至", note)
        self.assertEqual(recs[alert["id"]]["handled_by"], "spec-softdeleted")

    def test_close_alerts_zero_hit_zero_write(self):
        _make_project(self.root, {"spec-a": {"status": "implementing"}})
        _seed_alert(self.root, kind="escalation", spec="other-spec")
        store = AdminStore(self.root)
        alerts_path = self.root / ".fenix" / "admin_alerts.json"
        mtime_before = alerts_path.stat().st_mtime_ns

        closed = store.close_alerts_for_deleted_spec("spec-a", "注记")

        self.assertEqual(closed, 0)
        self.assertEqual(alerts_path.stat().st_mtime_ns, mtime_before)

    def test_close_alerts_skips_global_entries(self):
        _make_project(self.root, {"spec-a": {"status": "implementing"}})
        empty = _seed_alert(self.root, kind="escalation", spec=None)
        glob = _seed_alert(self.root, kind="signal", spec="global")

        closed = AdminStore(self.root).close_alerts_for_deleted_spec("spec-a", "注记")

        self.assertEqual(closed, 0)
        recs = {r["id"]: r for r in AdminStore(self.root).read_all()}
        self.assertFalse(recs[empty["id"]]["handled"])
        self.assertFalse(recs[glob["id"]]["handled"])
        # 全局形态直接短路，返回 0 且零写回
        self.assertEqual(AdminStore(self.root).close_alerts_for_deleted_spec("", "n"), 0)
        self.assertEqual(
            AdminStore(self.root).close_alerts_for_deleted_spec("global", "n"), 0)

    def test_softdelete_with_zero_alerts_reports_zero(self):
        _make_project(self.root, {"spec-quiet": {"status": "implementing"}})
        result = soft_delete_spec(self.root, "spec-quiet")
        self.assertIsNone(result["error"])
        self.assertEqual(result["alerts_closed"], 0)
        self.assertNotIn("alert_link_error", result)


class TestHandledAndDispositionUntouched(_LinkageBase):
    """组 2：已 handled 告警与 disposition 台账逐位不动；全 handled 零写回。"""

    def test_handled_alert_and_disposition_untouched(self):
        _make_project(self.root, {"spec-mixed": {"status": "implementing"}})
        handled = _seed_alert(
            self.root, kind="escalation", spec="spec-mixed",
            handled=True, handled_by="resolved",
            handled_at="2026-01-02T03:04:05+00:00",
            resolve_note="人工处置记录")
        disp = _seed_alert(
            self.root, kind="disposition", spec="spec-mixed",
            result="resolved", action_taken="abandon")
        fresh = _seed_alert(self.root, kind="signal", spec="spec-mixed")
        snapshot = copy.deepcopy(AdminStore(self.root).read_all())

        result = soft_delete_spec(self.root, "spec-mixed")

        self.assertIsNone(result["error"])
        # 仅未处理 signal 被关闭；人工历史与 disposition 本体逐位不动
        self.assertEqual(result["alerts_closed"], 1)
        recs = {r["id"]: r for r in AdminStore(self.root).read_all()}
        by_id = {r["id"]: r for r in snapshot}
        self.assertEqual(recs[handled["id"]], by_id[handled["id"]])
        self.assertEqual(recs[disp["id"]], by_id[disp["id"]])
        self.assertTrue(recs[fresh["id"]]["handled"])

    def test_all_handled_zero_write(self):
        _make_project(self.root, {"spec-done": {"status": "implementing"}})
        _seed_alert(self.root, kind="escalation", spec="spec-done", handled=True)
        alerts_path = self.root / ".fenix" / "admin_alerts.json"
        mtime_before = alerts_path.stat().st_mtime_ns

        result = soft_delete_spec(self.root, "spec-done")

        self.assertIsNone(result["error"])
        self.assertEqual(result["alerts_closed"], 0)
        # 已 handled 条目逐位不动 = 零命中零写回（mtime 不变）
        self.assertEqual(alerts_path.stat().st_mtime_ns, mtime_before)


class TestFailOpenOnAlertWriteFailure(_LinkageBase):
    """组 3：告警写回失败不阻断删除本体，返回对象如实回报。"""

    def test_alert_write_failure_keeps_delete_success(self):
        _make_project(self.root, {"spec-fail": {"status": "implementing"}})
        _seed_alert(self.root, kind="escalation", spec="spec-fail")

        real = AdminStore.close_alerts_for_deleted_spec

        def boom(self_store, spec, resolve_note):
            raise RuntimeError("simulated write refusal")

        AdminStore.close_alerts_for_deleted_spec = boom
        try:
            result = soft_delete_spec(self.root, "spec-fail")
        finally:
            AdminStore.close_alerts_for_deleted_spec = real

        # 删除本体成功：目录迁移、STATE 迁出不变，无未捕获异常逸出
        self.assertIsNone(result["error"])
        self.assertTrue(result["found"])
        self.assertTrue(result["archived"])
        self.assertFalse((self.root / "spec" / "changes" / "spec-fail").is_dir())
        self.assertNotIn("spec-fail",
                         (self.root / ".fenix" / "STATE.md").read_text(encoding="utf-8"))
        # 联动失败如实回落独立字段，不占用顶层 error
        self.assertEqual(result["alerts_closed"], 0)
        self.assertIn("告警联动关闭失败", result["alert_link_error"])
        self.assertIn("simulated write refusal", result["alert_link_error"])


class TestAbandonIdempotency(_LinkageBase):
    """组 4：found=False 幂等成功；存量在册 spec 丢弃行为不变。"""

    def test_abandon_absent_spec_is_idempotent_success(self):
        # spec 既不在活跃 STATE、也不在归档清单（软删除墓碑已清）
        _make_project(self.root, {"spec-alive": {"status": "implementing"}})

        r = _exec_abandon(self.root, "spec-gone", note="人工拍板")

        self.assertTrue(r["ok"])
        self.assertIsNone(r["error"])
        self.assertTrue(any("spec 已不存在（STATE 与归档清单均无记录），视为已丢弃"
                            in s for s in r["steps"]))
        self.assertFalse(any("spec not found" in s for s in r["steps"]))
        self.assertFalse(r["archived"])
        self.assertIsNone(r["archive_path"])

    def test_abandon_active_spec_unchanged_with_linkage(self):
        # 存量在册 spec：丢弃执行软删除成功，并经联动关闭该告警（行为不变）
        _make_project(self.root, {"spec-live": {"status": "implementing"}})
        alert = _seed_alert(self.root, kind="escalation", spec="spec-live")

        r = _exec_abandon(self.root, "spec-live")

        self.assertTrue(r["ok"])
        self.assertIsNone(r["error"])
        self.assertTrue(r["archived"])
        self.assertTrue(any("STATE.md 条目已移除" in s for s in r["steps"]))
        recs = {rec["id"]: rec for rec in AdminStore(self.root).read_all()}
        self.assertTrue(recs[alert["id"]]["handled"])
        self.assertEqual(recs[alert["id"]]["handled_by"], "spec-softdeleted")


if __name__ == "__main__":
    unittest.main()
