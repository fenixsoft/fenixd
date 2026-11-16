"""test-distill-retry-ledger-aging — 蒸馏重试台账欠账龄期升级与节流穿透
（evo-add-distill-retry-ledger-aging 3.1）。

覆盖（对齐 SPEC 验收四条）：
- 龄期字段：description/evidence 携带登记日期 + 当前龄期，且龄期与
  _retry_display_names 登记日期同源（同一日期节零点 _section_midnight
  起算）——复算期望值回注断言，杜绝第二套时钟。
- 72h 升级边界：<72h warning、≥72h major（含整点边界，mock now_local
  精确构造两侧）；升级仍走 kind=SIGNAL 通道（不落 kind=ESCALATION）。
- 现行持久节流跨重启语义不回归：同日同指纹不重发（check_retry_ledger_age
  无任何进程内幂等缓存，_load_retry_remind_state 每次读盘——同进程两次
  调用与跨 daemon 重启等价）；未知键保留前向兼容。
- 升级穿透：同日且指纹未变但应发级别提升（warning → major，经状态文件
  构造 prev=warning 形态）首射穿透发出；发射成功回写 last_severity，
  同级后续发射回到日粒度节流（边沿一次、不回弹）；级别回落随下一次
  发射自然覆盖。

测试隔离：tmpdir 每用例新建（无状态文件 = 当日未发）；tmpdir 非 git
仓库时产物核验 fail-open（_distill_commit_history 返回 None，仍催办），
不构造产物提交即不触发自动闭环干扰。
"""

import json
import shutil
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from unittest import mock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.knowledge as kn

TODAY = date.today()
# 确定性边界：登记日期节零点起算的龄期随真实时刻落在确定区间——
# D_MID（前天）龄期恒在 (48h, 72h)：warning；D_OLD（大前天）恒在
# (72h, 96h)：major。零点整点边界另经 mock now_local 精确构造。
D_MID = (TODAY - timedelta(days=2)).isoformat()
D_OLD = (TODAY - timedelta(days=3)).isoformat()
N1 = "aging-alpha-spec"
N2 = "aging-beta-spec"

TZ = ZoneInfo("Asia/Shanghai")


def _line(names: str, reason: str = "run 失败: 链接越出知识真相源目录") -> str:
    return f"- [ ] knowledge-distill 重试：归档 {names} — {reason}"


class RetryAgingTestBase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        (self.root / ".fenix" / "logs").mkdir(parents=True)
        self.state_path = self.root / ".fenix" / "knowledge-distill-retry-state.json"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_todo(self, *lines_with_dates) -> None:
        """按 (日期节, 行) 序写 todo.md（行归位指定日期节）。"""
        chunks = []
        for d, line in lines_with_dates:
            chunks.append(f"## {d}\n\n### 知识真相源\n{line}\n")
        (self.root / ".fenix" / "todo.md").write_text(
            "\n".join(chunks), encoding="utf-8"
        )

    def _alerts(self) -> list:
        path = self.root / ".fenix" / "admin_alerts.json"
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8"))

    def _state(self) -> dict:
        return json.loads(self.state_path.read_text(encoding="utf-8"))


# ── 1.1 龄期展示 ─────────────────────────────────────────────────────


class TestAgingDisplay(RetryAgingTestBase):
    def test_description_and_evidence_carry_age(self):
        """发射文案携带「登记 日期，欠账 小时/天」——龄期与登记日期节零点
        同源（复算期望回注断言）。"""
        self._write_todo((D_OLD, _line(N1)))
        r = kn.check_retry_ledger_age(self.root)
        self.assertTrue(r["reminded"])
        alerts = self._alerts()
        self.assertEqual(len(alerts), 1)
        rec = alerts[0]
        # 同源复算：与发射同一 _section_midnight 原语推期望龄期展示
        reg_date = date.fromisoformat(D_OLD)
        now = kn.now_local()
        expected_age = kn._format_retry_age(now - kn._section_midnight(now, reg_date))
        aged = f"{N1}（登记 {D_OLD}，欠账 {expected_age}）"
        self.assertIn(aged, rec["description"], "description 缺同源龄期展示")
        self.assertIn(aged, rec["evidence"], "evidence 缺同源龄期展示")
        # 登记日期节零点口径未被第二套时钟污染：展示龄期与零点起算值一致
        self.assertNotIn("欠账 0 小时（登记", rec["description"])

    def test_recommended_action_drops_rejected_hypothesis(self):
        """recommended_action 移除已排除的 unrecognized_model 假说指引，
        改为 proposal 附节口径。"""
        self._write_todo((D_OLD, _line(N1)))
        self.assertTrue(kn.check_retry_ledger_age(self.root)["reminded"])
        action = self._alerts()[0]["recommended_action"]
        self.assertNotIn("unrecognized_model", action)
        self.assertNotIn("ANTHROPIC_DEFAULT", action)
        self.assertIn("链接范围", action)
        self.assertIn("勾销", action)

    def test_out_stale_contract_unchanged(self):
        """返回值 out["stale"] 保持既有契约形态（归档名（登记 日期）），
        龄期仅进发射文案。"""
        self._write_todo((D_OLD, _line(N1)))
        r = kn.check_retry_ledger_age(self.root)
        self.assertEqual(r["stale"], [f"{N1}（登记 {D_OLD}）"])

    def test_age_format_units(self):
        """龄期展示单位口径：<48h 以小时计，≥48h 以天计。"""
        self.assertEqual(kn._format_retry_age(timedelta(hours=5)), "5 小时")
        self.assertEqual(kn._format_retry_age(timedelta(hours=47, minutes=59)), "47 小时")
        self.assertEqual(kn._format_retry_age(timedelta(hours=48)), "2 天")
        self.assertEqual(kn._format_retry_age(timedelta(hours=72)), "3 天")


# ── 1.2 72h 升级边界 ─────────────────────────────────────────────────


class TestEscalationBoundary(RetryAgingTestBase):
    def test_under_72h_stays_warning(self):
        """龄期 (48h, 72h)（前天日期节，真实时钟恒落此区间）→ warning。"""
        self._write_todo((D_MID, _line(N1)))
        r = kn.check_retry_ledger_age(self.root)
        self.assertTrue(r["reminded"])
        rec = self._alerts()[0]
        self.assertEqual(rec["severity"], "warning")
        self.assertEqual(rec["kind"], "signal")
        self.assertNotIn("升级为 major", rec["description"])

    def test_beyond_72h_escalates_major(self):
        """龄期 (72h, 96h)（大前天日期节）→ major；升级态仍携带龄期且
        同走 kind=SIGNAL 通道（不使用 kind=ESCALATION）。"""
        self._write_todo((D_OLD, _line(N1)))
        r = kn.check_retry_ledger_age(self.root)
        self.assertTrue(r["reminded"])
        rec = self._alerts()[0]
        self.assertEqual(rec["severity"], "major")
        self.assertEqual(rec["kind"], "signal", "升级 MUST NOT 换 ESCALATION 通道")
        self.assertEqual(rec["signal_type"], "knowledge_distill_retry_stale")
        self.assertIn("欠账", rec["description"], "升级态信号须同样携带龄期")
        self.assertIn("升级为 major", rec["description"])

    def test_exact_72h_boundary(self):
        """≥ 判界整点：龄期恰 72h → major；差 1 分钟 → warning（mock
        now_local 精确构造两侧，行归位同一日期节）。"""
        reg = date(2026, 11, 10)
        line = _line(N1)
        # 登记日 + 3 天零点 = 龄期恰 72h 的时刻；其前 1 分钟 = 71h59m
        boundary = datetime.combine(reg + timedelta(days=3), datetime.min.time(), tzinfo=TZ)
        for shift, expected in ((timedelta(0), "major"),
                                (timedelta(minutes=-1), "warning")):
            with self.subTest(shift=shift):
                self.tearDown()
                self.setUp()
                self._write_todo((reg.isoformat(), line))
                with mock.patch.object(kn, "now_local", return_value=boundary + shift):
                    r = kn.check_retry_ledger_age(self.root)
                self.assertTrue(r["reminded"])
                self.assertEqual(self._alerts()[-1]["severity"], expected)

    def test_multi_entry_takes_worst_severity(self):
        """聚合信号取全部欠账条目最高级别：warning+major 并存 → major。"""
        self._write_todo((D_MID, _line(N1)), (D_OLD, _line(N2)))
        r = kn.check_retry_ledger_age(self.root)
        self.assertTrue(r["reminded"])
        self.assertEqual(len(r["stale"]), 2)
        self.assertEqual(self._alerts()[0]["severity"], "major")


# ── 节流回归 + 升级穿透（2.1/2.2）────────────────────────────────────


class TestThrottleAndPiercing(RetryAgingTestBase):
    def test_daily_throttle_survives_restart(self):
        """现行持久节流跨重启语义不回归：同日同指纹不重发。
        check_retry_ledger_age 无进程内幂等缓存（状态每次读盘），同进程
        两次调用与 daemon 重启后重扫等价。"""
        self._write_todo((D_MID, _line(N1)))
        self.assertTrue(kn.check_retry_ledger_age(self.root)["reminded"])
        self.assertEqual(len(self._alerts()), 1)
        r2 = kn.check_retry_ledger_age(self.root)
        self.assertFalse(r2["reminded"])
        self.assertTrue(r2.get("suppressed"))
        self.assertEqual(len(self._alerts()), 1, "同日重复发射")

    def test_state_file_unknown_keys_preserved(self):
        """前向兼容：发射回写保留状态文件未知键（升级不破坏既有语义）。"""
        self._write_todo((D_MID, _line(N1)))
        self.state_path.write_text(
            json.dumps({"future_key": "keep-me"}), encoding="utf-8"
        )
        self.assertTrue(kn.check_retry_ledger_age(self.root)["reminded"])
        self.assertEqual(self._state().get("future_key"), "keep-me")

    def test_escalation_pierces_throttle_once(self):
        """升级穿透主链：同日且指纹未变且应发级别提升（prev=warning →
        major）首射穿透发出；发射成功回写 last_severity=major；同级后续
        发射回到日粒度节流（边沿一次、不回弹）。

        prev=warning 形态经状态文件构造（升级前存量账本/同日已发 warning
        的持久记录——check_retry_ledger_age 本身读盘记账，无进程内副本）。"""
        self._write_todo((D_OLD, _line(N1)))
        fingerprint = kn._stale_retry_fingerprint([( _line(N1), date.fromisoformat(D_OLD))])
        self.state_path.write_text(
            json.dumps(
                {
                    "last_reminded_date": TODAY.isoformat(),
                    "last_stale_fingerprint": fingerprint,
                    "last_severity": "warning",
                }
            ),
            encoding="utf-8",
        )
        # 升级首射：不被「同日且指纹未变」吞掉，立即发出 major
        r1 = kn.check_retry_ledger_age(self.root)
        self.assertTrue(r1["reminded"], "升级首射被节流吞掉")
        self.assertEqual(len(self._alerts()), 1)
        self.assertEqual(self._alerts()[0]["severity"], "major")
        self.assertEqual(self._state().get("last_severity"), "major", "发射后未回写新级别")
        # 同级后续发射：回到现行日粒度节流（穿透仅在提升边沿触发一次）
        r2 = kn.check_retry_ledger_age(self.root)
        self.assertFalse(r2["reminded"])
        self.assertTrue(r2.get("suppressed"))
        self.assertEqual(len(self._alerts()), 1, "穿透后同级重发")

    def test_stale_major_state_does_not_resend_warning(self):
        """不回弹：同日同指纹且上次发射 major、现应发 warning → 仍节流
        （major 残留不放行低级别重发，无第二条节流亦不放宽日节流）。"""
        self._write_todo((D_MID, _line(N1)))
        fingerprint = kn._stale_retry_fingerprint([( _line(N1), date.fromisoformat(D_MID))])
        self.state_path.write_text(
            json.dumps(
                {
                    "last_reminded_date": TODAY.isoformat(),
                    "last_stale_fingerprint": fingerprint,
                    "last_severity": "major",
                }
            ),
            encoding="utf-8",
        )
        r = kn.check_retry_ledger_age(self.root)
        self.assertFalse(r["reminded"])
        self.assertTrue(r.get("suppressed"))
        self.assertEqual(self._alerts(), [])

    def test_severity_falls_back_with_next_emit(self):
        """级别回落随下一次发射自然覆盖：跨日新欠账（warning 起步）放行
        发射后 last_severity 回写 warning，无升级态残留泄漏。"""
        self._write_todo((D_MID, _line(N1)))
        self.state_path.write_text(
            json.dumps(
                {
                    "last_reminded_date": (TODAY - timedelta(days=1)).isoformat(),
                    "last_stale_fingerprint": "stale-from-yesterday",
                    "last_severity": "major",
                }
            ),
            encoding="utf-8",
        )
        r = kn.check_retry_ledger_age(self.root)
        self.assertTrue(r["reminded"])
        self.assertEqual(self._alerts()[0]["severity"], "warning")
        self.assertEqual(self._state().get("last_severity"), "warning")

    def test_rejected_write_keeps_throttle_state(self):
        """拒写（AdminStore 返回 None）不回写状态——下一周期重试穿透，
        现行「拒写不记账」语义在升级路径不回归。"""
        self._write_todo((D_OLD, _line(N1)))
        fingerprint = kn._stale_retry_fingerprint([( _line(N1), date.fromisoformat(D_OLD))])
        self.state_path.write_text(
            json.dumps(
                {
                    "last_reminded_date": TODAY.isoformat(),
                    "last_stale_fingerprint": fingerprint,
                    "last_severity": "warning",
                }
            ),
            encoding="utf-8",
        )
        with mock.patch.object(kn, "_save_retry_remind_state", side_effect=OSError("disk full")):
            r = kn.check_retry_ledger_age(self.root)
        self.assertTrue(r["reminded"], "发射本身成功")
        # last_severity 未回写 warning→major 穿透账本：状态仍记 prev
        self.assertEqual(self._state().get("last_severity"), "warning")
        # 下一周期：穿透账本仍在，再次调用重试穿透（不重复吞掉）
        r2 = kn.check_retry_ledger_age(self.root)
        self.assertTrue(r2["reminded"], "拒写后下一周期未重试穿透")


if __name__ == "__main__":
    unittest.main()
