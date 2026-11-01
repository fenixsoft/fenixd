"""SPEC 时间轴 arbiter 节点可见性与处置台账联查（add-arbiter-quality-display 任务 2.4）。

get_spec_timeline 对 agent_type=arbiter 的 run 节点按 run_id 联查处置台账
``.fenix/arbiter_ledger.jsonl``（读侧复用 core.pm_engine.arbiter.
load_arbiter_ledger 单源；kind 限 disposition/escalation；同 run_id 多条取
created 最新；root_cause/action_or_upgrade 截断 200 字符下发；fail-open）。

fixture 形态参照 tests/test_spec_timeline_origin_request.py（假项目 +
伪造 run 产物 + 伪造台账），覆盖七类场景：
1. disposition 命中 → 节点附 ``arbiter`` 块、长文本截断 200 字符；
2. escalation 命中 → 同上（kind=escalation）；
3. spec-proposed（run_id 空）/ 非 disposition/escalation kind 不挂任何节点；
4. 台账文件缺失 → fail-open 静默省字段、零报错；
5. 损坏行容错跳过 → 有效条目照常命中；
6. 同 run_id 多条 → 取 created 最新一条；
7. 非 arbiter run 节点零新增字段（arbiter 字段不扩散到其它 agent_type）。
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT_CAUSE_LONG = "根因实证：" + "链路细节" * 150  # 600+ 字符，验证 200 截断
ACTION_LONG = "处置动作：" + "步骤描述" * 150


def _run_file(proot: Path, run_id: str, start_iso: str, outcome: str = "done") -> Path:
    """伪造 run 产物（.fenix/runs/<run_id>.jsonl）：start 带时间戳（started
    取首个带 timestamp 的事件），末行 result/error 终态（classify_run 判定）。"""
    events = [
        {"type": "start", "timestamp": start_iso, "message": f"{run_id} 启动"},
    ]
    if outcome == "done":
        events.append({"type": "result", "result": "ok"})
    elif outcome == "error":
        events.append({"type": "error", "error": "boom"})
    else:  # frozen-terminated 场景：无终态行（非终态 → running）
        events.append({"type": "progress"})
    path = proot / ".fenix" / "runs" / f"{run_id}.jsonl"
    path.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n",
        encoding="utf-8",
    )
    return path


def _ledger_entry(
    run_id: str | None,
    kind: str,
    created: str,
    root_cause: str = "根因",
    action_or_upgrade: str = "动作",
    signal_type: str = "gate",
) -> dict:
    """台账条目（_write_ledger 五段结构的关键投影字段）。"""
    return {
        "id": f"arb-ledger-{created}",
        "created": created,
        "kind": kind,
        "spec": "demo",
        "signal_type": signal_type,
        "signature": f"demo::{signal_type}",
        "run_id": run_id,
        "scene_snapshot": "现场",
        "root_cause": root_cause,
        "action_or_upgrade": action_or_upgrade,
        "evidence_refs": [f".fenix/runs/{run_id}.jsonl"] if run_id else [],
    }


class TestTimelineArbiterVisibility(unittest.TestCase):
    """get_spec_timeline 的 arbiter 台账联查七类场景。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        (self.root / ".fenix" / "logs").mkdir(parents=True)
        (self.root / ".fenix" / "runs").mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _seed_ledger(self, entries: list) -> None:
        (self.root / ".fenix" / "arbiter_ledger.jsonl").write_text(
            "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _run_nodes(timeline) -> list:
        return [e for e in timeline if e.get("kind") == "run"]

    @staticmethod
    def _node_of(timeline, run_id: str):
        hits = [e for e in timeline if e.get("kind") == "run" and e.get("run_id") == run_id]
        assert len(hits) == 1, f"run 节点缺失或重复: {run_id} in {timeline}"
        return hits[0]

    def test_1_disposition_hit_attaches_block_with_truncation(self):
        """disposition 命中：节点附 arbiter 块，长文本截断 200 字符下发。"""
        from core.dashboard.data import get_spec_timeline

        rid = "arbiter-demo-1793464000"
        _run_file(self.root, rid, "2026-11-01T08:00:00+00:00")
        self._seed_ledger(
            [
                _ledger_entry(
                    rid,
                    "disposition",
                    "2026-11-01T09:00:00+00:00",
                    root_cause=ROOT_CAUSE_LONG,
                    action_or_upgrade=ACTION_LONG,
                    signal_type="gate",
                )
            ]
        )
        timeline = get_spec_timeline(self.root, "demo")
        node = self._node_of(timeline, rid)
        arb = node.get("arbiter")
        self.assertIsInstance(arb, dict, f"命中条目必须附 arbiter 块: {node}")
        self.assertEqual(arb["kind"], "disposition")
        self.assertEqual(arb["signal_type"], "gate")
        self.assertEqual(len(arb["root_cause"]), 200, "root_cause 必须截断 200 字符")
        self.assertEqual(arb["root_cause"], ROOT_CAUSE_LONG[:200])
        self.assertEqual(len(arb["action_or_upgrade"]), 200)
        self.assertEqual(arb["action_or_upgrade"], ACTION_LONG[:200])

    def test_2_escalation_hit_attaches_block(self):
        """escalation 命中：节点附 kind=escalation 块（与 disposition 同构）。"""
        from core.dashboard.data import get_spec_timeline

        rid = "arbiter-demo-1793464001"
        _run_file(self.root, rid, "2026-11-01T08:01:00+00:00", outcome="error")
        self._seed_ledger(
            [_ledger_entry(rid, "escalation", "2026-11-01T09:01:00+00:00",
                           action_or_upgrade="需人工审批重启 daemon")]
        )
        timeline = get_spec_timeline(self.root, "demo")
        arb = self._node_of(timeline, rid)["arbiter"]
        self.assertEqual(arb["kind"], "escalation")
        self.assertEqual(arb["action_or_upgrade"], "需人工审批重启 daemon")

    def test_3_spec_proposed_and_other_kinds_not_attached(self):
        """spec-proposed（run_id 空）与 dead-man/failed 等其余 kind 不挂任何节点。"""
        from core.dashboard.data import get_spec_timeline

        rid = "arbiter-demo-1793464002"
        _run_file(self.root, rid, "2026-11-01T08:02:00+00:00")
        self._seed_ledger(
            [
                _ledger_entry(None, "spec-proposed", "2026-11-01T09:02:00+00:00"),
                _ledger_entry(rid, "dead-man", "2026-11-01T09:03:00+00:00"),
                _ledger_entry(rid, "failed", "2026-11-01T09:04:00+00:00"),
            ]
        )
        timeline = get_spec_timeline(self.root, "demo")
        carrying = [e for e in timeline if "arbiter" in e]
        self.assertEqual(carrying, [], f"非 disposition/escalation 条目不得挂节点: {timeline}")

    def test_4_missing_ledger_fail_open(self):
        """台账文件缺失：arbiter run 节点零新增字段、零报错（fail-open）。"""
        from core.dashboard.data import get_spec_timeline

        rid = "arbiter-demo-1793464003"
        _run_file(self.root, rid, "2026-11-01T08:03:00+00:00", outcome="error")
        timeline = get_spec_timeline(self.root, "demo")  # 不抛异常
        node = self._node_of(timeline, rid)
        self.assertNotIn("arbiter", node, "无台账命中不得下发 arbiter 字段")
        # 既有字段不受影响（标签/状态/时间仍在）
        self.assertEqual(node["agent_type"], "arbiter")
        self.assertEqual(node["status"], "error")
        self.assertEqual(node["time"], "2026-11-01T08:03:00+00:00")

    def test_5_corrupt_lines_skipped_valid_entry_hits(self):
        """损坏行容错跳过：夹杂非 JSON/非 dict 行的台账，有效条目照常命中。"""
        from core.dashboard.data import get_spec_timeline

        rid = "arbiter-demo-1793464004"
        _run_file(self.root, rid, "2026-11-01T08:04:00+00:00")
        good = json.dumps(
            _ledger_entry(rid, "disposition", "2026-11-01T09:05:00+00:00",
                          root_cause="损坏行容错"),
            ensure_ascii=False,
        )
        (self.root / ".fenix" / "arbiter_ledger.jsonl").write_text(
            "{corrupt json line\n" + good + "\n[\"bare-array\"]\n\n",
            encoding="utf-8",
        )
        timeline = get_spec_timeline(self.root, "demo")
        arb = self._node_of(timeline, rid).get("arbiter")
        self.assertIsInstance(arb, dict, f"有效条目必须穿透损坏行命中: {timeline}")
        self.assertEqual(arb["root_cause"], "损坏行容错")

    def test_6_same_run_id_latest_created_wins(self):
        """同 run_id 多条：取 created 最新一条（防重放/修补条目翻倍渲染）。"""
        from core.dashboard.data import get_spec_timeline

        rid = "arbiter-demo-1793464005"
        _run_file(self.root, rid, "2026-11-01T08:05:00+00:00")
        self._seed_ledger(
            [
                _ledger_entry(rid, "disposition", "2026-11-01T09:06:00+00:00",
                              root_cause="旧条目"),
                _ledger_entry(rid, "escalation", "2026-11-01T10:06:00+00:00",
                              root_cause="新条目", action_or_upgrade="最新升级理由"),
            ]
        )
        timeline = get_spec_timeline(self.root, "demo")
        arb = self._node_of(timeline, rid)["arbiter"]
        self.assertEqual(arb["kind"], "escalation")
        self.assertEqual(arb["root_cause"], "新条目")
        self.assertEqual(arb["action_or_upgrade"], "最新升级理由")

    def test_7_non_arbiter_nodes_zero_new_fields(self):
        """非 arbiter run 节点零新增字段：ledger 命中 impl- run_id 也不挂
        （联查仅对 agent_type=arbiter 生效）；同时间轴 arbiter 节点照常命中。"""
        from core.dashboard.data import get_spec_timeline

        arb_rid = "arbiter-demo-1793464006"
        impl_rid = "impl-demo-1793464000"
        _run_file(self.root, arb_rid, "2026-11-01T08:06:00+00:00")
        _run_file(self.root, impl_rid, "2026-11-01T07:00:00+00:00")
        self._seed_ledger(
            [
                _ledger_entry(arb_rid, "disposition", "2026-11-01T09:07:00+00:00"),
                _ledger_entry(impl_rid, "escalation", "2026-11-01T09:08:00+00:00"),
            ]
        )
        timeline = get_spec_timeline(self.root, "demo")
        impl_node = self._node_of(timeline, impl_rid)
        self.assertNotIn("arbiter", impl_node, "arbiter 字段不得扩散到非 arbiter 节点")
        arb_node = self._node_of(timeline, arb_rid)
        self.assertIn("arbiter", arb_node)


if __name__ == "__main__":
    unittest.main()
