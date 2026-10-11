"""tests/test_admin_disposition_merge_shared.py — admin disposition 归并单点与日志序位。

code-review item 55336c2a40af / 691c672d8ad5 防漂移锁定：

1. ``merge_dispositions_by_run``（core/dashboard/data/admin_alerts.py）是
   「按 admin_run_id 挑代表记录」的归并单点——运维记录页
   ``get_admin_activities`` 与 SPEC 时间轴 ``_admin_events_for_spec`` 共同
   委托（原两处逐行副本已收敛）。本文件锁定其归并规则，并以双视图对拍
   断言防止两视图归并结果分叉。
2. ``_rotated_log_files``（core/dashboard/data/timeline.py）对日期命名
   历史产物（fenixdYYYY-MM-DD.log）的序位必须排在全部轮转产物之前
   （更旧端）——旧实现与基底同序位时被当「最新」文件遍历，陈旧
   「开始验证」行会覆盖 verify_start_ts。
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from core.dashboard.data import (
    _admin_events_for_spec,
    get_admin_activities,
    merge_dispositions_by_run,
)
from core.dashboard.data.timeline import _rotated_log_files


def _disp(desc, created, run_id=None, spec="spec-a", **extra):
    """构造一条 disposition 记录（description 作对拍锚点）。"""
    rec = {
        "id": f"d-{desc}",
        "kind": "disposition",
        "spec": spec,
        "created": created,
        "description": desc,
    }
    if run_id is not None:
        rec["admin_run_id"] = run_id
    rec.update(extra)
    return rec


class TestMergeDispositionsByRun(unittest.TestCase):
    """归并单点行为锁定（pending 让位、同态取最新、无 run_id 独立）。"""

    def test_empty_input(self):
        self.assertEqual(merge_dispositions_by_run([]), {})

    def test_non_disposition_skipped(self):
        recs = [
            {"kind": "escalation", "admin_run_id": "run-1", "status": "pending"},
            {"kind": "signal", "admin_run_id": "run-1"},
        ]
        self.assertEqual(merge_dispositions_by_run(recs), {})

    def test_final_beats_pending_regardless_of_created(self):
        # 非 pending 让 pending 让位：pending created 更晚仍被替代
        pending = _disp("p", "2026-01-02T00:00:00+00:00", "run-1", status="pending")
        final = _disp("f", "2026-01-01T00:00:00+00:00", "run-1", result="success")
        merged = merge_dispositions_by_run([pending, final])
        self.assertFalse(merged["run-1"][0])
        self.assertIs(merged["run-1"][1], final)

    def test_same_state_takes_latest_created(self):
        old = _disp("old", "2026-01-01T00:00:00+00:00", "run-1", result="success")
        new = _disp("new", "2026-01-02T00:00:00+00:00", "run-1", result="failed")
        merged = merge_dispositions_by_run([new, old])
        self.assertIs(merged["run-1"][1], new)
        # 同为 pending 同理
        p_old = _disp("po", "2026-01-01T00:00:00+00:00", "run-2", status="pending")
        p_new = _disp("pn", "2026-01-02T00:00:00+00:00", "run-2", status="pending")
        merged = merge_dispositions_by_run([p_new, p_old])
        self.assertTrue(merged["run-2"][0])
        self.assertIs(merged["run-2"][1], p_new)

    def test_status_takes_priority_over_result(self):
        # status 优先口径（与单源 _merge_admin_runs 一致）：status=pending
        # 时即便 result 已是终结值也按 pending 参与归并
        rec = _disp("s", "2026-01-01T00:00:00+00:00", "run-1",
                    status="pending", result="success")
        merged = merge_dispositions_by_run([rec])
        self.assertTrue(merged["run-1"][0])

    def test_missing_run_id_independent_groups(self):
        a = _disp("a", "2026-01-01T00:00:00+00:00", None, result="resolved")
        b = _disp("b", "2026-01-02T00:00:00+00:00", None, result="resolved")
        merged = merge_dispositions_by_run([a, b])
        self.assertEqual(len(merged), 2)
        keys = set(merged)
        self.assertTrue(all(k.startswith("run-") for k in keys))
        self.assertEqual(
            {merged[k][1]["description"] for k in keys}, {"a", "b"}
        )


class TestDualViewParity(unittest.TestCase):
    """双视图对拍：运维记录页与 SPEC 时间轴的代表记录选择不分叉。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        # run-r1：pending（早）+ success（晚）→ 代表 = success
        # run-r2：仅 pending → 代表 = pending
        # d4：无 admin_run_id 独立；d5：他 spec 独立 run（不进 spec-a 时间轴）
        # e1：escalation（时间轴原样输出；activities 不含，仅作置顶关联）
        self.records = [
            _disp("desc-pending-r1", "2026-01-01T00:00:00+00:00", "run-r1",
                  status="pending"),
            _disp("desc-final-r1", "2026-01-02T00:00:00+00:00", "run-r1",
                  result="success"),
            _disp("desc-pending-r2", "2026-01-03T00:00:00+00:00", "run-r2",
                  status="pending"),
            _disp("desc-orphan", "2026-01-04T00:00:00+00:00", None,
                  result="resolved"),
            _disp("desc-other-spec", "2026-01-05T00:00:00+00:00", "run-r5",
                  spec="spec-b", result="failed"),
            {
                "id": "e1",
                "kind": "escalation",
                "admin_run_id": "run-r1",
                "handled": False,
                "spec": "spec-a",
                "created": "2026-01-01T00:00:00+00:00",
                "description": "desc-esc-r1",
            },
        ]
        path = Path(self.tmpdir) / ".fenix" / "admin_alerts.json"
        path.write_text(json.dumps(self.records), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_activities_and_timeline_pick_same_representatives(self):
        acts = {
            i["description"]
            for i in get_admin_activities(self.tmpdir)
            if i.get("kind") == "disposition"
        }
        nodes = {
            n["description"]
            for n in _admin_events_for_spec(self.tmpdir, "spec-a")
            if n["record_kind"] == "disposition"
        }
        # 被替代的 pending 不出现在任一侧
        self.assertNotIn("desc-pending-r1", acts)
        self.assertNotIn("desc-pending-r1", nodes)
        # 时间轴只见 spec-a；剔除他 spec 条目后两侧代表集必须一致
        self.assertEqual(acts - {"desc-other-spec"}, nodes)
        self.assertEqual(
            nodes, {"desc-final-r1", "desc-pending-r2", "desc-orphan"}
        )


class TestRotatedLogFileOrder(unittest.TestCase):
    """日期命名历史产物排最旧端（item 691c672d8ad5），轮转序号语义不变。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.logs_dir = Path(self.tmpdir) / ".fenix" / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, *names):
        for name in names:
            (self.logs_dir / name).write_text("", encoding="utf-8")

    def test_date_named_files_sort_oldest_before_rotations(self):
        self._write(
            "fenixd.log",
            "fenixd.log.1",
            "fenixd.log.2",
            "fenixd2026-01-01.log",
            "fenixd2025-12-31.log",
        )
        names = [p.name for p in _rotated_log_files(self.logs_dir)]
        # 旧→新：日期命名（组内按日期升序）→ 轮转备份（序号越大越旧）→ 基底
        self.assertEqual(
            names,
            [
                "fenixd2025-12-31.log",
                "fenixd2026-01-01.log",
                "fenixd.log.2",
                "fenixd.log.1",
                "fenixd.log",
            ],
        )

    def test_base_log_stays_newest_without_date_named_files(self):
        self._write("fenixd.log", "fenixd.log.1", "fenixd.log.5")
        names = [p.name for p in _rotated_log_files(self.logs_dir)]
        self.assertEqual(names, ["fenixd.log.5", "fenixd.log.1", "fenixd.log"])

    def test_non_log_names_excluded(self):
        self._write("fenixd.log", "fenixd.log.lock", "other.log")
        names = [p.name for p in _rotated_log_files(self.logs_dir)]
        self.assertEqual(names, ["fenixd.log"])
