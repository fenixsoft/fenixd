"""unfreeze-retry-counter-reset：解冻/复位清零调度重试计数 + 冻结文案真实计数 + 人工重推记账去重。

四场景（tasks.md 3.1）：
1. 3/3 冻结 → 解冻 → 首轮失败计数 1/3 不冻结（unfreeze_spec 清零集补
   ``_retry_count``——解冻前残留使首轮 bump 到 4 ≥ 3 立即越限再冻结）；
2. 两处复位键集合含 ``_retry_count``（unfreeze_spec 清零集行为级 +
   dashboard ``_RETRY_COUNTER_RESETS`` 集合级）；
3. 越限冻结文案计数与日志一致（``freeze_counter_note`` 真实计数 + 越限
   注明；两车道五处共用单一落点，硬编码形态反回归）；
4. 人工重推达上限后信号去重（同 spec 未决 push_failed 在册即跳过，
   不重复喂 daemon_errors 升级链；``[push_source=...]`` 来源标注落账）。
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.admin_store import SIGNAL, AdminStore
from core.state_machine import PUSH_ATTEMPTS_FIELD, StateMachine
from core.pm_engine import PMEngine
from core.pm_engine.dispatch.queue import freeze_counter_note
import core.pm_engine.dispatch.fast_track as fast_track_mod
import core.pm_engine.dispatch.queue as queue_mod
from core.dashboard.data.admin_actions import _RETRY_COUNTER_RESETS

REPO_ROOT = Path(__file__).resolve().parent.parent
QUEUE_FILE = REPO_ROOT / "core" / "pm_engine" / "dispatch" / "queue.py"
FAST_TRACK_FILE = REPO_ROOT / "core" / "pm_engine" / "dispatch" / "fast_track.py"

DEFAULT_MAX_RETRIES = 3


def _count_push_failed_signals(store: AdminStore, spec: str = None) -> list:
    """统计 admin store 中 push_failed 信号（可按 spec 过滤）。"""
    return [
        r
        for r in store.read_all()
        if r.get("kind") == SIGNAL
        and r.get("signal_type") == "push_failed"
        and (spec is None or r.get("spec") == spec)
    ]


class TestUnfreezeResetsRetryCounter(unittest.TestCase):
    """场景 1/2a：unfreeze_spec 清零集补 _retry_count（行为级）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))
        self.root = Path(self.tmpdir)
        (self.root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.sm = StateMachine(self.root / ".fenix" / "STATE.md", MagicMock())

    def _mk_frozen_spec(self, spec: str, retry_count: int) -> None:
        """构造「重试耗尽冻结态」条目：_retry_count=N + 冻结。"""
        self.sm.add_spec(spec, {"priority": 5})
        self.sm.update_spec(spec, {"status": "implementing", "_retry_count": retry_count})
        self.sm.freeze_spec(spec)

    def test_frozen_at_cap_unfreeze_first_failure_counts_1_no_refreeze(self):
        """① 3/3 冻结 → 解冻 → 首轮失败 bump 为 1/3，不触发再冻结。"""
        self._mk_frozen_spec("s1", retry_count=3)
        self.assertTrue(self.sm.read_one("s1").get("frozen"))

        self.sm.unfreeze_spec("s1", status="implementing")

        entry = self.sm.read_one("s1")
        self.assertEqual(int(entry["_retry_count"]), 0, "解冻必须清零 _retry_count")
        self.assertFalse(entry.get("frozen"))
        # 解冻后首轮派发失败：bump_counters 锁内原子递增返回写后值
        retries = self.sm.bump_counters("s1", {"_retry_count": 1}).get("_retry_count", 0)
        self.assertEqual(
            retries, 1,
            "解冻后首轮失败计数必须从 1 起算（残留 3 会 bump 到 4 立即越限）",
        )
        self.assertLess(
            retries, DEFAULT_MAX_RETRIES, "计数 1/3 不应触发重试耗尽冻结",
        )
        self.assertFalse(self.sm.read_one("s1").get("frozen"))
        # 磁盘级证据：全新 StateMachine 实例读回一致（非内存态）
        disk = StateMachine(
            self.root / ".fenix" / "STATE.md", MagicMock()
        ).read_one("s1")
        self.assertEqual(int(disk["_retry_count"]), 1)

    def test_unfreeze_legacy_entry_without_counter_is_zero_fill(self):
        """② 存量条目缺 _retry_count 键 → 解冻补零，无异常。"""
        self.sm.add_spec("legacy", {"priority": 5})
        self.sm.update_spec("legacy", {"status": "implementing"})
        self.assertNotIn("_retry_count", self.sm.read_one("legacy"))
        self.sm.freeze_spec("legacy")

        self.sm.unfreeze_spec("legacy", status="implementing")

        entry = self.sm.read_one("legacy")
        self.assertEqual(int(entry.get("_retry_count", 0)), 0)
        self.assertEqual(entry["status"], "implementing")


class TestResetSetsContainRetryCount(unittest.TestCase):
    """场景 2b：两处复位键集合含 _retry_count。"""

    def test_admin_retry_counter_resets_contains_retry_count_zero(self):
        """dashboard 管理复位清零集必须含 _retry_count 且置 0。"""
        self.assertIn("_retry_count", _RETRY_COUNTER_RESETS)
        self.assertEqual(_RETRY_COUNTER_RESETS["_retry_count"], 0)

    def test_unfreeze_updates_set_contains_retry_count_zero(self):
        """unfreeze_spec updates 清零集必须含 _retry_count 且置 0（源级钉住）。

        行为级由 TestUnfreezeResetsRetryCounter 覆盖；本断言钉住写点本身，
        防清零键被后续重构从 updates 集静默移出。
        """
        import inspect

        src = inspect.getsource(StateMachine.unfreeze_spec)
        self.assertIn('updates["_retry_count"] = 0', src)


class TestFreezeCounterNote(unittest.TestCase):
    """场景 3：越限冻结文案计数与日志一致（真实计数 + 越限注明）。"""

    def test_normal_form_shows_real_counter(self):
        self.assertEqual(freeze_counter_note(3, 3), "3/3 轮")
        self.assertEqual(freeze_counter_note(1, 3), "1/3 轮")

    def test_over_limit_form_annotated_and_honest(self):
        self.assertEqual(freeze_counter_note(4, 3), "4/3 轮，已越限")
        self.assertEqual(freeze_counter_note(6, 3), "6/3 轮，已越限")

    def test_both_lanes_share_single_helper_and_real_counter(self):
        """两车道共用同一 helper（模块属性同一对象）且硬编码形态绝迹。"""
        self.assertIs(
            fast_track_mod.freeze_counter_note,
            queue_mod.freeze_counter_note,
            "fast_track 必须消费 queue 的同一 helper 对象（单一落点）",
        )
        queue_src = QUEUE_FILE.read_text(encoding="utf-8")
        fast_src = FAST_TRACK_FILE.read_text(encoding="utf-8")
        # 硬编码反回归：used/max 同槽位硬编码不得复活
        self.assertNotIn("{max_r}/{max_r}", queue_src)
        self.assertNotIn("{max_r}/{max_r}", fast_src)
        # 五处冻结站点全部经 helper 消费真实计数（queue 2 处 + fast_track 3 处）
        self.assertEqual(queue_src.count("freeze_counter_note(retries, max_r)"), 2)
        self.assertEqual(fast_src.count("freeze_counter_note(retries, max_r)"), 3)


class TestManualRepushAccountingAndSignalDedup(unittest.TestCase):
    """场景 4：人工重推来源标注 + 达上限后 push_failed 信号去重。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))
        self.root = Path(self.tmpdir)
        (self.root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()
        self.sm = StateMachine(self.root / ".fenix" / "STATE.md", self.logger)
        self.engine = PMEngine(self.sm, MagicMock(), {}, self.root, self.logger)
        self.sm.add_spec("s1", {"priority": 5})

    def _spec_entry(self, attempts: int) -> dict:
        return {PUSH_ATTEMPTS_FIELD: attempts}

    def test_signal_push_failed_dedup_while_pending(self):
        """同 spec 未决 push_failed 在册 → 去重跳过，不重复写入。"""
        store = AdminStore(self.root, self.logger)
        self.engine._signal_push_failed("s1", "第 1 次超限 detail")
        self.assertEqual(len(_count_push_failed_signals(store, "s1")), 1)

        # 人工重推再次失败（未决旧信号在场）：去重跳过 + INFO 可对账
        self.engine._signal_push_failed("s1", "人工重推后再次超限 detail")
        self.assertEqual(
            len(_count_push_failed_signals(store, "s1")), 1,
            "未决 push_failed 在册时不得重复写入（daemon_errors 升级链防重烧）",
        )
        info_texts = [str(c.args) for c in self.logger.info.call_args_list]
        self.assertTrue(
            any("去重跳过" in t for t in info_texts),
            f"去重跳过应 INFO 留痕可对账：{info_texts}",
        )

    def test_signal_push_failed_rearms_after_handled(self):
        """旧信号被处置（handled）后，新一轮超限可再次告警。"""
        store = AdminStore(self.root, self.logger)
        self.engine._signal_push_failed("s1", "第一次超限")
        first = _count_push_failed_signals(store, "s1")[0]
        self.assertTrue(store.mark_signal_handled(first["id"]))

        self.engine._signal_push_failed("s1", "处置后新一轮超限")
        self.assertEqual(
            len(_count_push_failed_signals(store, "s1")), 2,
            "handled 后必须能再次告警（去重不得演变为永久静默）",
        )

    def test_signal_push_failed_not_deduped_across_specs(self):
        """去重按 spec 隔离：他 spec 超限不受本 spec 未决信号影响。"""
        store = AdminStore(self.root, self.logger)
        self.engine._signal_push_failed("s1", "s1 超限")
        self.engine._signal_push_failed("s2", "s2 超限")
        self.assertEqual(len(_count_push_failed_signals(store, "s1")), 1)
        self.assertEqual(len(_count_push_failed_signals(store, "s2")), 1)

    def test_handle_push_failure_annotates_source_manual(self):
        """人工重推失败计账标注 [push_source=manual]，计数照常递增。"""
        self.sm.update_spec("s1", {"status": "done"})
        self.engine._handle_push_failure(
            "s1", self._spec_entry(0), "auth fail", "main", source="manual"
        )
        error = self.sm.read_one("s1").get("error") or ""
        self.assertIn("[push_source=manual]", error)
        self.assertIn("[push_attempts=1]", error, "计数如实递增")
        self.assertIn("[push_backoff", error, "未达上限走退避语义（不变）")

    def test_handle_push_failure_default_source_auto(self):
        """自动链（缺省 source=auto）标注 [push_source=auto]。"""
        self.sm.update_spec("s1", {"status": "done"})
        self.engine._handle_push_failure("s1", self._spec_entry(0), "boom", "main")
        error = self.sm.read_one("s1").get("error") or ""
        self.assertIn("[push_source=auto]", error)

    def test_handle_push_failure_exhausted_manual_dedups_signal(self):
        """人工重推达上限：计数/文案如实递增标注 manual，信号只发一次。"""
        store = AdminStore(self.root, self.logger)
        self.sm.update_spec("s1", {"status": "done"})
        # 已失败 2 次（_push_attempts=2）→ 本次第 3 次 >= 上限 3：超限分支
        self.engine._handle_push_failure(
            "s1", self._spec_entry(2), "auth fail", "main", source="manual"
        )
        error = self.sm.read_one("s1").get("error") or ""
        self.assertIn("[push_source=manual]", error)
        self.assertIn("[push_attempts=3]", error)
        self.assertIn("[push_failed", error)
        # push_failed 信号 detail 带人工来源标注
        signals = _count_push_failed_signals(store, "s1")
        self.assertEqual(len(signals), 1)
        self.assertIn("来源=manual", str(signals[0].get("evidence")))
        # 达上限后人工再重推再失败：计数文案如实，但不重复发信号
        self.engine._handle_push_failure(
            "s1", self._spec_entry(3), "auth fail", "main", source="manual"
        )
        self.assertIn("[push_attempts=4]", self.sm.read_one("s1").get("error") or "")
        self.assertEqual(
            len(_count_push_failed_signals(store, "s1")), 1,
            "达上限后同 spec 重复 push_failed 信号必须去重",
        )


if __name__ == "__main__":
    unittest.main()
