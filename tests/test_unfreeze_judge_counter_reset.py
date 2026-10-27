"""fix-unfreeze-judge-counter-reset：人工解冻清零 judge 重跑计数与硬上限旗标。

judge 重跑超上限（``count > _MAX_JUDGE_RERUNS``=5）冻结后，``unfreeze_spec``
清零集 MUST 成对清零/清除 ``_judge_rerun_count`` 与 ``_judge_cap_frozen``（与
既有验证计数同一原子写）——``_judge_cap_frozen`` 只停递增不挡冻结判定，
只清计数不清旗标会让计数恒 0、judge 预算失明；只清旗标不清计数则解冻后
首次 judge 派发 ``count(6) > 5`` 原样再冻（2026-10-27 add-command-center
监视期实证），人工裁决出口形同虚设。
"""

import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from core.state_machine import (
    ENV_BLOCK_ROUNDS_FIELD,
    JUDGE_CAP_FROZEN_FIELD,
    JUDGE_RERUN_COUNT_FIELD,
    SCENARIO_REPAIR_EXHAUSTED_FIELD,
    StateMachine,
)
from core.pm_engine.verification import judge_gate
from core.pm_engine.verification.judge_gate import _MAX_JUDGE_RERUNS


class _FakeLogger:
    """静默日志桩（StateMachine 与 judge_gate 读侧共用形态）。"""

    def _noop(self, *args, **kwargs):
        pass

    info = warning = error = debug = _noop


def _mk_frozen_spec(sm: StateMachine, spec: str, extra: dict = None) -> None:
    """构造「judge hard cap 冻结态」条目：count=6 + cap_frozen=True + 冻结。"""
    sm.add_spec(spec, {"priority": 5})
    updates = {
        "status": "implemented",
        JUDGE_RERUN_COUNT_FIELD: 6,
        JUDGE_CAP_FROZEN_FIELD: True,
    }
    updates.update(extra or {})
    sm.update_spec(spec, updates)
    sm.freeze_spec(spec)


class TestUnfreezeJudgeCounterReset(unittest.TestCase):
    """unfreeze_spec 清零集补齐 judge 两字段（同一原子写）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))
        self.root = Path(self.tmpdir)
        (self.root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.sm = StateMachine(
            self.root / ".fenix" / "STATE.md", _FakeLogger()
        )

    def _fake_pipeline(self):
        """judge_gate._judge_rerun_count 所需的最小 pipeline 形态。"""
        return SimpleNamespace(
            _context=SimpleNamespace(state_machine=self.sm, logger=_FakeLogger())
        )

    def test_unfreeze_clears_judge_fields_with_existing_reset_fields(self):
        """① 冻结条目解冻 → 两字段归零/清除，且与既有清零字段同写落盘。"""
        _mk_frozen_spec(
            self.sm, "s1",
            {SCENARIO_REPAIR_EXHAUSTED_FIELD: 2, ENV_BLOCK_ROUNDS_FIELD: 3},
        )
        # 前置：解冻前 judge 读侧确实处于冻结态（delta=1 不递增，恒 6）
        pre = judge_gate._judge_rerun_count(self._fake_pipeline(), "s1", delta=1)
        self.assertEqual(pre, 6, "冻结态下计数不应递增（cap_frozen 停递增）")

        self.sm.unfreeze_spec("s1", status="implemented")

        entry = self.sm.read_one("s1")
        self.assertEqual(int(entry[JUDGE_RERUN_COUNT_FIELD]), 0)
        self.assertFalse(entry[JUDGE_CAP_FROZEN_FIELD])
        # 既有清零字段仍在同一解冻写内归零（清零集未被本改动破坏）
        self.assertEqual(int(entry[ENV_BLOCK_ROUNDS_FIELD]), 0)
        self.assertEqual(int(entry[SCENARIO_REPAIR_EXHAUSTED_FIELD]), 0)
        # 同写落盘证据：全新 StateMachine 实例从磁盘读回一致（非内存态）
        disk = StateMachine(
            self.root / ".fenix" / "STATE.md", _FakeLogger()
        ).read_one("s1")
        self.assertEqual(int(disk[JUDGE_RERUN_COUNT_FIELD]), 0)
        self.assertFalse(disk[JUDGE_CAP_FROZEN_FIELD])

    def test_judge_gate_after_unfreeze_counts_from_1_no_hard_cap(self):
        """② 解冻后模拟 judge 派发门 delta=1 → count=1 ≤ 上限，不触发 hard cap。"""
        _mk_frozen_spec(self.sm, "s1")
        self.sm.unfreeze_spec("s1", status="implemented")

        count = judge_gate._judge_rerun_count(
            self._fake_pipeline(), "s1", delta=1
        )
        self.assertEqual(count, 1, "解冻后派发门应从 1 重新起算")
        self.assertLessEqual(count, _MAX_JUDGE_RERUNS,
                             "count=1 不应触发 hard cap 再冻结")
        entry = self.sm.read_one("s1")
        self.assertEqual(int(entry[JUDGE_RERUN_COUNT_FIELD]), 1)
        self.assertFalse(entry[JUDGE_CAP_FROZEN_FIELD],
                         "派发后旗标不得复活（否则下一轮递增恒失效）")

    def test_unfreeze_legacy_entry_missing_fields_is_zero_fill(self):
        """③ 存量条目缺两键 → 解冻等价补零，无异常、无其他字段被扰动。"""
        self.sm.add_spec("legacy", {"priority": 5})
        self.sm.update_spec("legacy", {"status": "implemented", "priority": 5})
        entry = self.sm.read_one("legacy")
        self.assertNotIn(JUDGE_RERUN_COUNT_FIELD, entry)
        self.assertNotIn(JUDGE_CAP_FROZEN_FIELD, entry)
        self.sm.freeze_spec("legacy")

        self.sm.unfreeze_spec("legacy", status="implemented")

        entry = self.sm.read_one("legacy")
        self.assertEqual(int(entry.get(JUDGE_RERUN_COUNT_FIELD, 0)), 0)
        self.assertFalse(entry.get(JUDGE_CAP_FROZEN_FIELD))
        # 无其他字段被扰动
        self.assertEqual(int(entry["priority"]), 5)
        self.assertEqual(entry["status"], "implemented")
        self.assertIsNone(entry.get("error"))


if __name__ == "__main__":
    unittest.main()
