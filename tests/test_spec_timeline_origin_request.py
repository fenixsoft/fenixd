"""SPEC 立项原话时间轴附着（add-timeline-origin-request 任务 2.2 / 4.1）。

request.md（用户 /fenix-new 立项原话，写侧唯一入口 fenix-new SKILL §3.1.3）
在 get_spec_timeline 排序+折叠完成后附到首个 state 节点的 origin_request 字段；
fixture 形态参照 tests/test_spec_timeline_name_isolation.py（假项目 +
.fenix/logs/fenixd.log 伪日志行）。

覆盖七类场景：
1. 有 request.md → 首个 state 节点附原话全文，其余节点不携带；
2. 无 request.md → 全部节点不携带字段、接口零报错；
3. 归档目录路径解析（spec/archive/<date>-<name>/request.md，无活跃目录）；
4. 折叠链首节点附着（chain 节点即首个 state 节点）；
5. 读异常 fail-open（request.md 为目录 → IsADirectoryError 静默省字段）；
6. 空文件（strip 后为空）省字段；
7. 有 request.md 但时间轴无 state 节点不附着（MUST NOT 退化挂到 admin 等
   其它 kind 节点）。

另有 TestSpecDetailOriginRequestE2E：fixture 项目端到端（任务 4.1）——
经 spec_detail 组装函数断言 origin_request 的出现/缺席与归档路径可达
（dashboard fixture 配方：假项目 + 伪造 STATE.md + spec 目录）。
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _line(ts: str, msg: str, **ctx) -> str:
    e = {"timestamp": ts, "level": "INFO",
         "component": "state_machine", "message": msg}
    if ctx:
        e["context"] = ctx
    return json.dumps(e, ensure_ascii=False)


REQUEST_TEXT = "给时间轴加上立项原话展示，让 SPEC 能回看当初用户随口说的那句话\n第二行原文保持换行\n"


class _TimelineFixtureBase(unittest.TestCase):
    """公共 fixture：假项目根 + .fenix/logs 目录 + spec 目录助手。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        (self.root / ".fenix" / "logs").mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_log(self, lines):
        (self.root / ".fenix" / "logs" / "fenixd.log").write_text(
            "\n".join(lines) + "\n", encoding="utf-8")

    def _mk_active_spec(self, name, request_text=None):
        """创建活跃 spec 目录；request_text 非 None 时写 request.md。"""
        d = self.root / "spec" / "changes" / name
        d.mkdir(parents=True, exist_ok=True)
        if request_text is not None:
            (d / "request.md").write_text(request_text, encoding="utf-8")
        return d

    def _mk_archive_spec(self, name, date_prefix, request_text=None):
        """创建归档 spec 目录 spec/archive/<date>-<name>/。"""
        d = self.root / "spec" / "archive" / f"{date_prefix}-{name}"
        d.mkdir(parents=True, exist_ok=True)
        if request_text is not None:
            (d / "request.md").write_text(request_text, encoding="utf-8")
        return d

    @staticmethod
    def _states(timeline):
        return [e for e in timeline if e["kind"] == "state"]

    @staticmethod
    def _carrying(timeline):
        return [e for e in timeline if "origin_request" in e]


class TestOriginRequestAttachment(_TimelineFixtureBase):
    """get_spec_timeline 的 origin_request 附着七类场景。"""

    def test_1_request_md_attached_to_first_state_node_only(self):
        """场景 1：有 request.md → 首个 state 节点附原文全文，其余节点不携带。"""
        from core.dashboard.data import get_spec_timeline
        self._mk_active_spec("origin-spec", request_text=REQUEST_TEXT)
        self._write_log([
            _line("2026-09-08T12:00:00.000000Z",
                  "Transition: origin-spec ready → implementing"),
            _line("2026-09-08T12:01:00.000000Z",
                  "Transition: origin-spec implementing → implemented"),
            _line("2026-09-08T12:02:00.000000Z",
                  "Transition: origin-spec implemented → testing"),
            # 回退节点打断折叠，时间轴出现第二个 state 节点
            _line("2026-09-08T12:03:00.000000Z",
                  "Transition: origin-spec testing → implementing"),
        ])
        timeline = get_spec_timeline(self.root, "origin-spec")
        states = self._states(timeline)
        self.assertEqual(len(states), 2, f"折叠后应有 2 个 state 节点: {timeline}")
        carrying = self._carrying(timeline)
        self.assertEqual(len(carrying), 1,
                         f"仅首个 state 节点可携带 origin_request: {timeline}")
        self.assertIs(carrying[0], states[0], "携带节点必须是首个 state 节点")
        self.assertEqual(carrying[0]["origin_request"], REQUEST_TEXT,
                         "origin_request 必须是 request.md 原文全文")
        self.assertEqual(states[0]["from"], "ready", "首个节点即折叠链/首个转移")

    def test_2_missing_request_md_omits_field(self):
        """场景 2：无 request.md（存量 SPEC）→ 全节点不携带、零报错。"""
        from core.dashboard.data import get_spec_timeline
        self._mk_active_spec("origin-spec")  # 目录在，request.md 不在
        self._write_log([
            _line("2026-09-08T12:00:00.000000Z",
                  "Transition: origin-spec drafted → reviewing"),
        ])
        timeline = get_spec_timeline(self.root, "origin-spec")
        self.assertEqual(self._carrying(timeline), [],
                         f"无 request.md 不得携带 origin_request: {timeline}")
        self.assertEqual(len(self._states(timeline)), 1, "state 节点照常产出")

    def test_3_archived_spec_dir_resolution(self):
        """场景 3：归档 SPEC（无活跃目录）经 resolve_spec_dir 归档回退可达。"""
        from core.dashboard.data import get_spec_timeline
        self._mk_archive_spec("arch-spec", "2026-01-02", request_text=REQUEST_TEXT)
        self._write_log([
            _line("2025-12-30T10:00:00.000000Z",
                  "Transition: arch-spec reviewing → ready"),
        ])
        timeline = get_spec_timeline(self.root, "arch-spec")
        states = self._states(timeline)
        self.assertEqual(len(states), 1, f"归档 SPEC state 节点缺失: {timeline}")
        self.assertEqual(states[0].get("origin_request"), REQUEST_TEXT,
                         "归档路径下 request.md 原话必须附着到首个 state 节点")

    def test_4_collapsed_chain_first_node_attachment(self):
        """场景 4：首个 state 节点为折叠链（chain）时原话附在链节点上。"""
        from core.dashboard.data import get_spec_timeline
        self._mk_active_spec("origin-spec", request_text=REQUEST_TEXT)
        # fast-track 式连跳：连续前向转移折叠为单 chain 节点
        self._write_log([
            _line("2026-09-08T12:00:00.000000Z",
                  "Transition: origin-spec implemented → testing"),
            _line("2026-09-08T12:01:00.000000Z",
                  "Transition: origin-spec testing → verified"),
            _line("2026-09-08T12:02:00.000000Z",
                  "Transition: origin-spec verified → done"),
            _line("2026-09-08T12:03:00.000000Z",
                  "Transition: origin-spec done → pushed"),
        ])
        timeline = get_spec_timeline(self.root, "origin-spec")
        states = self._states(timeline)
        self.assertEqual(len(states), 1, f"连跳应折叠为单节点: {timeline}")
        chain = states[0].get("chain")
        self.assertEqual(chain,
                         ["implemented", "testing", "verified", "done", "pushed"])
        self.assertEqual(states[0].get("origin_request"), REQUEST_TEXT,
                         "折叠链首节点必须携带 origin_request")

    def test_5_read_error_fail_open(self):
        """场景 5：读取异常 fail-open——request.md 为目录时静默省字段不崩。"""
        from core.dashboard.data import get_spec_timeline
        d = self._mk_active_spec("origin-spec")
        # request.md 是目录：read_text 抛 IsADirectoryError（OSError 子类）
        (d / "request.md").mkdir()
        self._write_log([
            _line("2026-09-08T12:00:00.000000Z",
                  "Transition: origin-spec ready → implementing"),
        ])
        timeline = get_spec_timeline(self.root, "origin-spec")  # 不抛异常
        self.assertEqual(self._carrying(timeline), [],
                         f"读异常必须静默省字段: {timeline}")
        self.assertEqual(len(self._states(timeline)), 1, "state 节点不受影响")

    def test_6_empty_request_md_omits_field(self):
        """场景 6：空文件/纯空白内容 → strip 后为空，省字段。"""
        from core.dashboard.data import get_spec_timeline
        self._mk_active_spec("origin-spec", request_text="   \n\t\n")
        self._write_log([
            _line("2026-09-08T12:00:00.000000Z",
                  "Transition: origin-spec drafted → reviewing"),
        ])
        timeline = get_spec_timeline(self.root, "origin-spec")
        self.assertEqual(self._carrying(timeline), [],
                         f"空白 request.md 不得携带 origin_request: {timeline}")

    def test_7_no_state_nodes_not_attached(self):
        """场景 7：有 request.md 但时间轴无 state 节点 → 任何节点不携带。

        state 节点唯一来源是日志窗口；此处日志窗口无该 spec 的转移行，时间轴
        仅剩 admin 节点——原话 MUST NOT 退化挂到 admin/run/verify 等其它 kind。
        """
        from core.dashboard.data import get_spec_timeline
        self._mk_active_spec("origin-spec", request_text=REQUEST_TEXT)
        # 日志窗口只有别的 spec 的转移行（本 spec 超窗/清理后无 state 节点）
        self._write_log([
            _line("2026-09-08T12:00:00.000000Z",
                  "Transition: other-spec ready → implementing"),
        ])
        # 时间轴仍有一个非 state 节点（admin 运维事件）——证明「无 state 节点
        # 但时间轴非空」时原话不退化挂靠
        alerts = self.root / ".fenix" / "admin_alerts.json"
        alerts.write_text(json.dumps([{
            "id": "esc-1", "kind": "escalation", "spec": "origin-spec",
            "created": "2026-09-08T13:00:00+00:00", "signal_type": "gate",
            "severity": "major", "description": "产物硬门失败",
            "handled": False,
        }], ensure_ascii=False), encoding="utf-8")
        timeline = get_spec_timeline(self.root, "origin-spec")
        kinds = {e["kind"] for e in timeline}
        self.assertNotIn("state", kinds, f"fixture 应无 state 节点: {timeline}")
        self.assertIn("admin", kinds, f"admin 节点应在场（非空时间轴）: {timeline}")
        self.assertEqual(self._carrying(timeline), [],
                         f"无 state 节点时任何 kind 不得携带 origin_request: {timeline}")


class TestSpecDetailOriginRequestE2E(_TimelineFixtureBase):
    """任务 4.1：spec_detail 组装函数端到端（活跃/归档/缺失三形态）。"""

    def _entry(self, **kw):
        return {"status": "done", "priority": 5, "created": "", **kw}

    def test_active_spec_with_request_md(self):
        """活跃 SPEC：spec_detail.timeline 首个 state 节点携带原话。"""
        from core.dashboard.data import spec_detail
        self._mk_active_spec("origin-spec", request_text=REQUEST_TEXT)
        (self.root / "spec" / "changes" / "origin-spec" / ".spec.yaml").write_text(
            "schema: spec-driven\ncreated: 2026-09-08\nmode: full\n", encoding="utf-8")
        (self.root / "spec" / "changes" / "origin-spec" / "tasks.md").write_text(
            "# Tasks\n\n## 1. x\n\n- [ ] 1.1 do\n", encoding="utf-8")
        self._write_log([
            _line("2026-09-08T12:00:00.000000Z",
                  "Transition: origin-spec reviewing → ready"),
        ])
        d = spec_detail(self.root, "origin-spec", self._entry())
        states = [e for e in d["timeline"] if e["kind"] == "state"]
        self.assertEqual(states[0].get("origin_request"), REQUEST_TEXT,
                         f"详情接口首个 state 节点必须携带原话: {d['timeline']}")

    def test_archived_spec_request_md_reachable(self):
        """归档 SPEC（无活跃目录）：归档路径下 request.md 经详情接口可达。"""
        from core.dashboard.data import spec_detail
        self._mk_archive_spec("arch-spec", "2026-01-02", request_text=REQUEST_TEXT)
        (self.root / "spec" / "archive" / "2026-01-02-arch-spec" / "proposal.md"
         ).write_text("# Proposal\n", encoding="utf-8")
        self._write_log([
            _line("2025-12-30T10:00:00.000000Z",
                  "Transition: arch-spec reviewing → ready"),
        ])
        d = spec_detail(self.root, "arch-spec", self._entry())
        states = [e for e in d["timeline"] if e["kind"] == "state"]
        self.assertTrue(states, f"归档 SPEC 详情时间轴应有 state 节点: {d['timeline']}")
        self.assertEqual(states[0].get("origin_request"), REQUEST_TEXT,
                         "归档路径的 request.md 原话必须可达")

    def test_spec_without_request_md_absent_and_zero_error(self):
        """无 request.md 的 SPEC：详情接口字段缺席、零报错（fail-open）。"""
        from core.dashboard.data import spec_detail
        self._mk_active_spec("legacy-spec")
        (self.root / "spec" / "changes" / "legacy-spec" / "tasks.md").write_text(
            "# Tasks\n\n## 1. x\n\n- [ ] 1.1 do\n", encoding="utf-8")
        self._write_log([
            _line("2026-09-08T12:00:00.000000Z",
                  "Transition: legacy-spec reviewing → ready"),
        ])
        d = spec_detail(self.root, "legacy-spec", self._entry())
        carrying = [e for e in d["timeline"] if "origin_request" in e]
        self.assertEqual(carrying, [],
                         f"无 request.md 详情时间轴不得携带字段: {d['timeline']}")


if __name__ == "__main__":
    unittest.main()
