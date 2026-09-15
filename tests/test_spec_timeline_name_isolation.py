"""SPEC 详情时间轴名称隔离与方向保真（fix-timeline-substring-leak）。

根因：get_spec_timeline 的 `Updated SPEC` 行判定用子串匹配（`spec_name in msg`），
前缀名 spec（如 add-verify-contract-autodraft）会把姊妹 spec（…-ui）的
`Updated SPEC 'add-…-ui'` 状态更新整体吸收进自己的时间轴——泄漏项进入
status_updates → 打回重建分支按时间合流推演 current 指针 → 基 spec 的恢复
直写行 from 被推到 pushed，真实「实现中→就绪」重启恢复显示成「已推送→就绪」
假回退；就近 error 覆写再把恢复 error 贴满全部泄漏卡片（2026-09-08 实证）。

修复：带引号全匹配 `f"'{spec_name}'" in msg`（写点唯一于 state_machine
update_spec 的 `f"Updated SPEC '{spec_name}'"`，引号形态由 Task 1.1 全库
grep 核对）；打回重建分支按 _LIFECYCLE_ORDER 判定方向——前向节点无同行
error 时 reason 置空（不再落「状态回退」兜底文案），state 节点统一输出
backward 布尔（Transition 解析与打回重建两路一致）。
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path


def _line(ts: str, msg: str, **ctx) -> str:
    e = {"timestamp": ts, "level": "INFO",
         "component": "state_machine", "message": msg}
    if ctx:
        e["context"] = ctx
    return json.dumps(e, ensure_ascii=False)


class TestSpecTimelineNameIsolation(unittest.TestCase):
    """Updated SPEC 带引号全匹配：前缀名 spec 不吸收姊妹 spec 状态更新。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        logs_dir = Path(self.tmpdir) / ".fenix" / "logs"
        logs_dir.mkdir(parents=True)
        lines = [
            # add-foo：推进到 implementing（transition() 成对写）
            _line("2026-09-08T12:00:00.000000Z",
                  "Transition: add-foo ready → implementing"),
            _line("2026-09-08T12:00:00.010000Z", "Updated SPEC 'add-foo'",
                  updates={"status": "implementing"}),
            # 姊妹 spec add-foo-ui：implemented→testing→verified→done→pushed 级联
            _line("2026-09-08T12:01:00.000000Z",
                  "Transition: add-foo-ui implemented → testing"),
            _line("2026-09-08T12:01:00.010000Z", "Updated SPEC 'add-foo-ui'",
                  updates={"status": "testing"}),
            _line("2026-09-08T12:02:00.000000Z",
                  "Transition: add-foo-ui testing → verified"),
            _line("2026-09-08T12:02:00.010000Z", "Updated SPEC 'add-foo-ui'",
                  updates={"status": "verified"}),
            _line("2026-09-08T12:03:00.000000Z",
                  "Transition: add-foo-ui verified → done"),
            _line("2026-09-08T12:03:00.010000Z", "Updated SPEC 'add-foo-ui'",
                  updates={"status": "done"}),
            _line("2026-09-08T12:04:00.000000Z",
                  "Transition: add-foo-ui done → pushed"),
            _line("2026-09-08T12:04:00.010000Z", "Updated SPEC 'add-foo-ui'",
                  updates={"status": "pushed"}),
        ]
        (logs_dir / "fenixd.log").write_text("\n".join(lines) + "\n",
                                             encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_prefix_spec_zero_leak_from_sister_spec(self):
        from core.dashboard.data import get_spec_timeline
        timeline = get_spec_timeline(self.tmpdir, "add-foo")
        states = [e for e in timeline if e["kind"] == "state"]
        tos = [e["to"] for e in states]
        # -ui 级联的任何状态节点都不得出现在 add-foo 的时间轴
        for leaked in ("testing", "verified", "done", "pushed"):
            self.assertNotIn(leaked, tos,
                             f"姊妹 spec 状态 {leaked} 泄漏进 add-foo: {states}")
        # add-foo 自身唯一的推进节点仍在
        self.assertEqual([e["to"] for e in states], ["implementing"])

    def test_sister_spec_own_cascade_intact(self):
        from core.dashboard.data import get_spec_timeline
        timeline = get_spec_timeline(self.tmpdir, "add-foo-ui")
        states = [e for e in timeline if e["kind"] == "state"]
        # 连续前向状态节点折叠为一次（chain 全量下发）：
        # implemented→testing→verified→done→pushed 收敛为单节点、链完整
        self.assertEqual(len(states), 1, f"-ui 级联折叠节点缺失: {states}")
        self.assertEqual(states[0].get("chain"),
                         ["implemented", "testing", "verified", "done", "pushed"])


class TestFromInferenceFidelity(unittest.TestCase):
    """from 推演不被姊妹 spec 污染：恢复直写行 from=implementing→to=ready。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        logs_dir = Path(self.tmpdir) / ".fenix" / "logs"
        logs_dir.mkdir(parents=True)
        lines = [
            # add-foo：推进到 implementing（成对写，作为推演锚点）
            _line("2026-09-08T12:00:00.000000Z",
                  "Transition: add-foo ready → implementing"),
            _line("2026-09-08T12:00:00.010000Z", "Updated SPEC 'add-foo'",
                  updates={"status": "implementing"}),
            # 泄漏源：姊妹 spec -ui 的 pushed 更新在前（修复前把推演指针
            # 顶到 pushed，基 spec 恢复行被显示成 pushed→ready 假回退）
            _line("2026-09-08T12:05:00.010000Z", "Updated SPEC 'add-foo-ui'",
                  updates={"status": "pushed"}),
            # add-foo 恢复直写：取消中断后重启恢复（无 Transition 行）
            _line("2026-09-08T12:06:00.000000Z", "Updated SPEC 'add-foo'",
                  updates={"status": "ready",
                           "error": "Recovered from interrupted state: implementing"}),
        ]
        (logs_dir / "fenixd.log").write_text("\n".join(lines) + "\n",
                                             encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_recovery_node_from_inference_not_polluted(self):
        from core.dashboard.data import get_spec_timeline
        timeline = get_spec_timeline(self.tmpdir, "add-foo")
        recovery = [e for e in timeline
                    if e["kind"] == "state" and e["to"] == "ready"]
        self.assertEqual(len(recovery), 1,
                         f"恢复节点缺失或重复: {timeline}")
        self.assertEqual(recovery[0]["from"], "implementing",
                         f"from 被姊妹 spec 污染: {recovery[0]}")
        self.assertIn("Recovered from interrupted state",
                      recovery[0]["reason"])


class TestBackwardFieldAndReasonSemantics(unittest.TestCase):
    """state 节点 backward 字段与前向节点 reason 语义（Task 2.1/2.2/2.3）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        logs_dir = Path(self.tmpdir) / ".fenix" / "logs"
        logs_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, lines):
        logs_dir = Path(self.tmpdir) / ".fenix" / "logs"
        (logs_dir / "fenixd.log").write_text("\n".join(lines) + "\n",
                                             encoding="utf-8")

    def test_recovery_direct_write_backward_true(self):
        """恢复直写行（implementing→ready 带 error）：backward=true、reason 精确。"""
        from core.dashboard.data import get_spec_timeline
        self._write([
            _line("2026-09-08T12:00:00.000000Z",
                  "Transition: spec-x ready → implementing"),
            _line("2026-09-08T12:00:00.010000Z", "Updated SPEC 'spec-x'",
                  updates={"status": "implementing"}),
            _line("2026-09-08T12:06:00.000000Z", "Updated SPEC 'spec-x'",
                  updates={"status": "ready",
                           "error": "Recovered from interrupted state: implementing"}),
        ])
        timeline = get_spec_timeline(self.tmpdir, "spec-x")
        recovery = [e for e in timeline
                    if e["kind"] == "state" and e["to"] == "ready"]
        self.assertEqual(len(recovery), 1)
        self.assertEqual(recovery[0]["from"], "implementing")
        self.assertTrue(recovery[0]["backward"])
        self.assertIn("Recovered from interrupted state", recovery[0]["reason"])

    def test_forward_direct_write_no_reason_no_overwrite(self):
        """前向直写行（无 err，10 分钟内有别行 error）：reason 空 + backward=false。

        实现中（implementing）→ 已实现（implemented）属生命周期前向；无同行
        error 时 reason 必须为空（不再落「状态回退」兜底文案），且不被 10
        分钟窗口内的就近 error 覆写传染（D2：前向无 err 节点 reason 为空，
        天然不在覆写射程）。
        """
        from core.dashboard.data import get_spec_timeline
        self._write([
            _line("2026-09-08T12:00:00.000000Z",
                  "Transition: spec-x ready → implementing"),
            _line("2026-09-08T12:00:00.010000Z", "Updated SPEC 'spec-x'",
                  updates={"status": "implementing"}),
            # 前向直写（无 Transition 行、无同行 error）
            _line("2026-09-08T12:01:00.000000Z", "Updated SPEC 'spec-x'",
                  updates={"status": "implemented"}),
            # 10 分钟窗口内另一条带 error 的更新行（就近覆写射程内）
            _line("2026-09-08T12:03:00.000000Z", "Updated SPEC 'spec-x'",
                  updates={"status": "ready", "error": "验证失败，回退"}),
        ])
        timeline = get_spec_timeline(self.tmpdir, "spec-x")
        fwd = [e for e in timeline if e["kind"] == "state"
               and e["to"] == "implemented"]
        self.assertEqual(len(fwd), 1, f"前向直写节点缺失: {timeline}")
        self.assertEqual(fwd[0]["reason"], "",
                         f"前向节点被兜底文案/就近 error 污染: {fwd[0]}")
        self.assertFalse(fwd[0]["backward"])

    def test_transition_backward_node_regression(self):
        """既有 Transition 回退节点（testing→implementing）reason/backward 回归不变。"""
        from core.dashboard.data import get_spec_timeline
        self._write([
            _line("2026-09-08T12:00:00.000000Z",
                  "Transition: spec-x ready → implementing"),
            _line("2026-09-08T12:00:00.010000Z", "Updated SPEC 'spec-x'",
                  updates={"status": "implementing"}),
            _line("2026-09-08T12:01:00.000000Z",
                  "Transition: spec-x implementing → implemented"),
            _line("2026-09-08T12:01:00.010000Z", "Updated SPEC 'spec-x'",
                  updates={"status": "implemented"}),
            _line("2026-09-08T12:02:00.000000Z",
                  "Transition: spec-x implemented → testing"),
            _line("2026-09-08T12:02:00.010000Z", "Updated SPEC 'spec-x'",
                  updates={"status": "testing"}),
            # 真实回退：testing → implementing（兜底文案「验证失败/中断，回退实现」）
            _line("2026-09-08T12:03:00.000000Z",
                  "Transition: spec-x testing → implementing"),
            _line("2026-09-08T12:03:00.010000Z", "Updated SPEC 'spec-x'",
                  updates={"status": "implementing"}),
        ])
        timeline = get_spec_timeline(self.tmpdir, "spec-x")
        back = [e for e in timeline if e["kind"] == "state"
                and e["from"] == "testing" and e["to"] == "implementing"]
        self.assertEqual(len(back), 1, f"回退节点缺失: {timeline}")
        self.assertEqual(back[0]["reason"], "验证失败/中断，回退实现")
        self.assertTrue(back[0]["backward"])


class TestReviewGateDirection(unittest.TestCase):
    """评审门（reviewing）方向判定：drafted→reviewing→ready 为正常推进，非回退。

    add-spec-review-gate 新增 reviewing 状态时漏登记进 _LIFECYCLE_ORDER；
    .get(s, 9) 的哨兵 9 高于 pushed(7)，reviewing→ready 被误算 backward=True
    并落「状态回退」兜底文案（2026-09-15 evo-admin-dispatch-failure-escalation
    实测）。状态机文档明确 reviewing 位于 drafted 与 ready 之间。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        logs_dir = Path(self.tmpdir) / ".fenix" / "logs"
        logs_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, lines):
        logs_dir = Path(self.tmpdir) / ".fenix" / "logs"
        (logs_dir / "fenixd.log").write_text("\n".join(lines) + "\n",
                                             encoding="utf-8")

    def test_reviewing_to_ready_is_forward(self):
        """评审通过：drafted→reviewing→ready 全程前向，无回退徽标/兜底文案。"""
        from core.dashboard.data import get_spec_timeline
        self._write([
            _line("2026-09-15T01:29:41.481119Z",
                  "Transition: spec-x drafted → reviewing"),
            _line("2026-09-15T01:36:24.038674Z",
                  "Transition: spec-x reviewing → ready"),
        ])
        timeline = get_spec_timeline(self.tmpdir, "spec-x")
        states = [e for e in timeline if e["kind"] == "state"]
        for e in states:
            self.assertFalse(e["backward"], f"评审门正常推进被误判回退: {e}")
            self.assertEqual(e["reason"], "", f"前向节点不应带兜底文案: {e}")
        # 连续前向节点折叠为一条链，链中含 reviewing（途经状态不省略）
        ready = [e for e in states if e["to"] == "ready"]
        self.assertEqual(len(ready), 1, f"ready 节点缺失: {states}")
        self.assertIn("reviewing",
                      ready[0].get("chain", []) + [ready[0]["from"]])

    def test_reviewing_entries_not_backward(self):
        """进入评审（drafted→reviewing）与评审中阻塞（reviewing→blocked）均非回退。"""
        from core.dashboard.data import get_spec_timeline
        self._write([
            _line("2026-09-15T01:00:00.000000Z",
                  "Transition: spec-x drafted → reviewing"),
            _line("2026-09-15T01:10:00.000000Z",
                  "Transition: spec-x reviewing → blocked"),
        ])
        timeline = get_spec_timeline(self.tmpdir, "spec-x")
        for e in [x for x in timeline if x["kind"] == "state"]:
            self.assertFalse(e["backward"], f"评审进入/阻塞被误判回退: {e}")

    def test_blocked_to_ready_still_backward(self):
        """回归：blocked→ready（人工担责放行）仍判回退，方向判定不误伤存量行为。"""
        from core.dashboard.data import get_spec_timeline
        self._write([
            _line("2026-09-15T01:00:00.000000Z",
                  "Transition: spec-x implementing → blocked"),
            _line("2026-09-15T01:20:00.000000Z",
                  "Transition: spec-x blocked → ready"),
        ])
        timeline = get_spec_timeline(self.tmpdir, "spec-x")
        back = [e for e in timeline if e["kind"] == "state"
                and e["from"] == "blocked" and e["to"] == "ready"]
        self.assertEqual(len(back), 1, f"blocked→ready 节点缺失: {timeline}")
        self.assertTrue(back[0]["backward"])


if __name__ == "__main__":
    unittest.main()
