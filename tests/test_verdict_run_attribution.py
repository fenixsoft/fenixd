"""fix-verify-verdict-run-attribution 回归（任务 1.2 / 2.2 / 2.3 / 3.2）。

事故背景（add-command-center，2026-10-26）：共享 verdict 文件残留 in-chain
planner 的 plan-ready，两轮 verify 完成（各 39 分钟、16/18 pass）消费时均被
判「stale/foreign verifier result replayed」整体作废重派，verdict 断链导致
fix 链从未接手。

本套件钉住新语义三根支柱：
- 派发侧归属戳（任务 1.2）：verifier 出队派发原子预写三键归属戳、旧残留
  被覆盖、写入失败不阻断派发；
- 消费侧归属校验（任务 2.2/2.3）：预写戳原样 → 「本轮未产出裁决」
  fail-closed；无 role 戳新鲜 primary 白名单裁决照常采信（primary 豁免
  role 门不回退）；陈旧异归属残留 → 归档 .stale-<ts> + fail-closed，无
  「replayed」归因、不整轮重派；新鲜 plan-ready 照既有「验证未完成」通道；
- 成果保全（任务 3.2）：fail-closed 丢弃前新鲜 report.json 重命名保全
  report-<run_id>.json + 告警附路径；无/陈旧 report 不保全。
"""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.pm_engine import PMEngine
from core.state_machine import StateMachine

SPEC = "demo-spec"
RUN_ID = "verify-demo-spec-1750000000-a1"

# 派发侧预写归属戳（queue._prewrite_verifier_dispatch_stamp 写出形态）
DISPATCH_STAMP = {"role": "verifier", "spec": SPEC, "status": "dispatched"}


def _make_dispatch_engine(tmpdir: Path, status: str = "implemented"):
    """构造 PMEngine（spec 处于指定状态），stub 掉真实 worker 启动。"""
    (tmpdir / ".fenix").mkdir(parents=True, exist_ok=True)
    logger = MagicMock()
    sm = StateMachine(tmpdir / ".fenix" / "STATE.md", logger)
    engine = PMEngine(sm, MagicMock(), {}, tmpdir, logger)
    dispatched: list = []
    engine._run_agent_worker = lambda spec, atype, prio: dispatched.append((spec, atype))
    sm.add_spec("demo", {"status": status, "priority": 5})
    return sm, engine, dispatched


class _AttributionBase:
    """消费侧处置回归共用基础设施（spec 进入 testing、per-spec 进度目录就绪）。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        (self.tmpdir / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()
        self.sm = StateMachine(self.tmpdir / ".fenix" / "STATE.md", self.logger)
        self.engine = PMEngine(
            self.sm, MagicMock(), {}, self.tmpdir, self.logger,
        )
        self.engine._enqueue = MagicMock()
        self.engine._on_spec_verified = MagicMock()
        self.engine._on_spec_bug_found = MagicMock()
        self.engine._send_human_escalation_alert = MagicMock()
        self.sm.add_spec(SPEC, {"priority": 5})
        for s in ("ready", "implementing", "implemented", "testing"):
            self.sm.transition(SPEC, s)
        self.verify_dir = self.tmpdir / ".fenix" / "verify-progress" / SPEC
        self.verify_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @property
    def primary_path(self) -> Path:
        return self.verify_dir / ".fenix-run-result.json"

    @property
    def report_path(self) -> Path:
        return self.verify_dir / "report.json"

    def _write_primary(self, payload: dict, mtime: float | None = None) -> None:
        self.primary_path.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        if mtime is not None:
            os.utime(self.primary_path, (mtime, mtime))

    def _run_legacy(self, run_id: str = RUN_ID):
        """驱动 legacy 裁决消费链（run_verifier 替身返回指定 run_id）。"""
        self.engine._verification._ensure_verification_report = MagicMock(return_value=None)
        self.engine._verification._env_whitewash_gate = MagicMock(return_value=True)
        self.engine._verification._check_verification_gate = MagicMock(return_value=None)
        self.engine._verification._speculative_bug_found_gate = MagicMock(return_value=False)
        self.engine.agent_runner.run_verifier = MagicMock(
            return_value=SimpleNamespace(
                success=True, error=None, run_id=run_id))
        self.engine._run_legacy_verification(SPEC)

    def _escalation_texts(self) -> str:
        """汇总全部升级告警文案（description + evidence）便于断言。"""
        chunks = []
        for call in self.engine._send_human_escalation_alert.call_args_list:
            kwargs = call.kwargs
            chunks.append(str(kwargs.get("description", "")))
            chunks.append(str(kwargs.get("evidence", "")))
        return "\n".join(chunks)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. 派发侧归属戳（任务 1.2）
# ═══════════════════════════════════════════════════════════════════════════════

class TestDispatchStampPrewrite(unittest.TestCase):
    """verifier 出队派发原子预写归属戳（queue._prewrite_verifier_dispatch_stamp）。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _primary(self) -> Path:
        return self.tmpdir / ".fenix" / "verify-progress" / "demo" / ".fenix-run-result.json"

    def _dispatch_verifier(self, status: str = "implemented"):
        sm, engine, dispatched = _make_dispatch_engine(self.tmpdir, status)
        engine._dispatcher._enqueue("demo", "verifier")
        engine._dispatcher._process_queue()
        time.sleep(0.3)
        return sm, engine, dispatched

    def test_stamp_overwrites_stale_residue(self):
        """派发后文件为三键归属戳，旧残留（plan-ready 等）被覆盖。"""
        primary = self._primary()
        primary.parent.mkdir(parents=True, exist_ok=True)
        primary.write_text(
            json.dumps({"status": "plan-ready", "spec": "demo"}),
            encoding="utf-8")
        sm, engine, dispatched = self._dispatch_verifier()
        self.assertEqual(dispatched, [("demo", "verifier")], "verifier 未被派发")
        data = json.loads(primary.read_text(encoding="utf-8"))
        self.assertEqual(
            data, {"role": "verifier", "spec": "demo", "status": "dispatched"},
            "归属戳三键形态不符")
        self.assertEqual(
            set(data.keys()), {"role", "spec", "status"},
            "归属戳不得含 run_id 等额外键（派发点不可得）")

    def test_stamp_written_when_file_absent(self):
        """无残留时派发同样预写归属戳（首次验证轮）。"""
        self._primary().parent.mkdir(parents=True, exist_ok=True)
        sm, engine, dispatched = self._dispatch_verifier("testing")
        self.assertEqual(dispatched, [("demo", "verifier")])
        self.assertEqual(
            json.loads(self._primary().read_text(encoding="utf-8")),
            {"role": "verifier", "spec": "demo", "status": "dispatched"})

    def test_prewrite_failure_does_not_block_dispatch(self):
        """预写失败（目标不可写）→ WARNING 留痕、派发照常继续。"""
        primary = self._primary()
        primary.parent.mkdir(parents=True, exist_ok=True)
        # 目标位置替换为非空目录：os.replace 到目录上必然 OSError（EISDIR），
        # 与运行身份（root 下 chmod 失效）无关的确定性失败注入。
        primary.mkdir()
        (primary / "keep").write_text("x", encoding="utf-8")
        sm, engine, dispatched = self._dispatch_verifier()
        self.assertEqual(dispatched, [("demo", "verifier")], "预写失败不得阻断派发")
        warnings = "\n".join(
            str(c) for c in self._last_logger(engine).warning.call_args_list)
        self.assertIn("归属戳预写失败", warnings, "预写失败未落 WARNING 留痕")

    @staticmethod
    def _last_logger(engine) -> MagicMock:
        return engine.logger


# ═══════════════════════════════════════════════════════════════════════════════
# 2. 消费侧归属校验三分支（任务 2.2）
# ═══════════════════════════════════════════════════════════════════════════════

class TestReadVerdictAttribution(_AttributionBase, unittest.TestCase):
    """_read_verdict 三分支判据（读取层）。"""

    def test_dispatch_stamp_original_state_not_produced(self):
        """分支②：文件仍为派发预写戳原样 → not-produced（本轮未产出裁决）。"""
        self._write_primary(DISPATCH_STAMP)
        res = self.engine._read_verdict(SPEC)
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "not-produced")

    def test_foreign_spec_stamp_is_residue_not_not_produced(self):
        """异 spec 的同形态戳属残留（分支③），不判 not-produced。"""
        self._write_primary(
            {"role": "verifier", "spec": "other-spec", "status": "dispatched"})
        res = self.engine._read_verdict(SPEC)
        self.assertFalse(res.ok)
        self.assertNotEqual(res.reason, "not-produced")

    def test_fresh_no_role_primary_whitelist_accepted(self):
        """分支①：agent 正常写出的无 role 戳新鲜 primary 白名单裁决照常采信。

        primary 豁免 role 门（judge_gate 快道 D3 教训）不因归属戳引入回退：
        预写戳只覆盖 status=dispatched 形态，verifier/judge 正常覆盖写出的
        裁决（verified/bug-found 等）不受影响。
        """
        self._write_primary({
            "status": "bug-found", "spec": SPEC, "bugs": [{"id": "b1"}],
        })
        res = self.engine._read_verdict(SPEC)
        self.assertTrue(res.ok, "无 role 戳新鲜 primary 被误拒（role 门回退）")
        self.assertEqual(res.status, "bug-found")

    def test_verifier_role_verified_overwrites_stamp(self):
        """verifier 正常写出（含 role 戳、status=verified）→ 采信，不误判戳。"""
        self._write_primary({
            "role": "verifier", "spec": SPEC, "status": "verified", "bugs": [],
        })
        res = self.engine._read_verdict(SPEC)
        self.assertTrue(res.ok)
        self.assertEqual(res.status, "verified")


class TestLegacyDisposal(_AttributionBase, unittest.TestCase):
    """legacy 消费链处置三分支（blocked/采信/归档）。"""

    def test_stamp_not_produced_blocks_without_redispatch(self):
        """①预写戳原样 → blocked「本轮未产出裁决」，无 replayed 归因、不归档。"""
        self._write_primary(DISPATCH_STAMP)
        self._run_legacy()
        entry = self.sm.read_one(SPEC)
        self.assertEqual(entry["status"], "blocked")
        self.assertIn("本轮未产出机器可读裁决", entry.get("error", ""))
        self.assertNotIn("replayed", entry.get("error", ""))
        # 预写戳是本轮自己的产物：不作 .stale 归档（archive=False）
        self.assertTrue(self.primary_path.exists(), "预写戳被误归档")
        self.assertEqual(
            json.loads(self.primary_path.read_text(encoding="utf-8")),
            DISPATCH_STAMP)
        # fail-closed critical 告警已发
        self.engine._send_human_escalation_alert.assert_called()
        self.engine._on_spec_verified.assert_not_called()
        self.engine._on_spec_bug_found.assert_not_called()

    def test_stale_residue_archives_and_blocks_without_redispatch(self):
        """③陈旧残留 → 归档 .stale-<ts> + blocked，无 replayed、不重派。"""
        stale_epoch = 1750000000 - 100
        self._write_primary(
            {"status": "verified", "spec": SPEC, "bugs": []},
            mtime=stale_epoch)
        self._run_legacy()  # run_id 内嵌 epoch=1750000000，mtime 早 100s → stale
        entry = self.sm.read_one(SPEC)
        self.assertEqual(entry["status"], "blocked")
        self.assertNotIn("replayed", entry.get("error", ""))
        self.assertIn("本轮未产出机器可读裁决", entry.get("error", ""))
        # 残留已归档备份，原文件不再存在
        stale_backups = list(self.verify_dir.glob(".fenix-run-result.json.stale-*"))
        self.assertEqual(len(stale_backups), 1, "陈旧残留未归档备份")
        self.assertFalse(self.primary_path.exists())
        self.engine._send_human_escalation_alert.assert_called()
        self.engine._on_spec_verified.assert_not_called()
        self.engine._on_spec_bug_found.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# 3. in-chain planner plan-ready 两态（任务 2.3）
# ═══════════════════════════════════════════════════════════════════════════════

class TestPlanReadyTwoStates(_AttributionBase, unittest.TestCase):
    """新鲜 plan-ready 照既有「验证未完成」通道；陈旧残留归档 + fail-closed。"""

    def test_fresh_plan_ready_keeps_testing_channel(self):
        """本轮派发窗口内写出的 plan-ready → 保持 testing，产物不被归档覆盖。"""
        self._write_primary(
            {"status": "plan-ready", "spec": SPEC},
            mtime=time.time())
        self._run_legacy()  # epoch=1750000000 远早于 mtime(now) → 新鲜
        entry = self.sm.read_one(SPEC)
        self.assertEqual(entry["status"], "testing", "新鲜 plan-ready 不得 fail-closed")
        self.assertIn("验证未完成", entry.get("error", ""))
        # planner 当轮产物不被归档覆盖
        self.assertTrue(self.primary_path.exists())
        self.assertEqual(
            len(list(self.verify_dir.glob(".fenix-run-result.json.stale-*"))), 0)
        self.engine._send_human_escalation_alert.assert_not_called()

    def test_stale_plan_ready_residue_archives_and_blocks(self):
        """陈旧 plan-ready 残留（上一轮 planner）→ 归档 + blocked fail-closed。"""
        stale_epoch = 1750000000 - 100
        self._write_primary(
            {"status": "plan-ready", "spec": SPEC},
            mtime=stale_epoch)
        self._run_legacy()
        entry = self.sm.read_one(SPEC)
        self.assertEqual(entry["status"], "blocked")
        self.assertNotIn("replayed", entry.get("error", ""))
        self.assertEqual(
            len(list(self.verify_dir.glob(".fenix-run-result.json.stale-*"))), 1)
        self.assertFalse(self.primary_path.exists())
        self.engine._send_human_escalation_alert.assert_called()


# ═══════════════════════════════════════════════════════════════════════════════
# 4. fail-closed 丢弃前成果保全（任务 3.2）
# ═══════════════════════════════════════════════════════════════════════════════

class TestReportPreservation(_AttributionBase, unittest.TestCase):
    """判「残留 / 本轮未产出裁决」丢弃当轮成果前保全 report.json（D4）。"""

    def _write_fresh_report(self):
        self.report_path.write_text(
            json.dumps({
                "spec": SPEC,
                "summary": {"passed": 16, "failed": 2, "total": 18},
            }, ensure_ascii=False),
            encoding="utf-8")
        os.utime(self.report_path, (time.time(), time.time()))

    def test_fresh_report_preserved_on_stale_residue(self):
        """①新鲜 report + 残留判定 → 保全 report-<run_id>.json、告警含路径。"""
        self._write_fresh_report()
        self._write_primary(
            {"status": "verified", "spec": SPEC, "bugs": []},
            mtime=1750000000 - 100)
        self._run_legacy()  # epoch=1750000000，report mtime(now) ≥ 派发时刻 → 保全
        preserved = self.verify_dir / f"report-{RUN_ID}.json"
        self.assertTrue(preserved.exists(), "新鲜 report 未被保全")
        self.assertFalse(self.report_path.exists(), "原 report 应已重命名保全")
        texts = self._escalation_texts()
        self.assertIn(f"report-{RUN_ID}.json", texts, "升级告警未附保全路径")
        # fail-closed 照常进行
        self.assertEqual(self.sm.read_one(SPEC)["status"], "blocked")

    def test_fresh_report_preserved_on_not_produced(self):
        """「本轮未产出裁决」分支同样触发保全。"""
        self._write_fresh_report()
        self._write_primary(DISPATCH_STAMP)
        self._run_legacy()
        self.assertTrue((self.verify_dir / f"report-{RUN_ID}.json").exists())
        self.assertIn(f"report-{RUN_ID}.json", self._escalation_texts())
        self.assertEqual(self.sm.read_one(SPEC)["status"], "blocked")

    def test_stale_report_not_preserved(self):
        """②陈旧 report（mtime 早于本轮派发时刻）→ 不保全，fail-closed 照常。"""
        stale_epoch = 1750000000 - 200
        self.report_path.write_text("{}", encoding="utf-8")
        os.utime(self.report_path, (stale_epoch, stale_epoch))
        self._write_primary(
            {"status": "verified", "spec": SPEC, "bugs": []},
            mtime=1750000000 - 100)
        self._run_legacy()
        preserved = list(self.verify_dir.glob("report-*.json"))
        self.assertEqual(preserved, [], "陈旧 report 被误保全")
        self.assertEqual(self.sm.read_one(SPEC)["status"], "blocked")

    def test_missing_report_not_preserved(self):
        """②无 report → 不保全，fail-closed 照常。"""
        self._write_primary(
            {"status": "verified", "spec": SPEC, "bugs": []},
            mtime=1750000000 - 100)
        self._run_legacy()
        self.assertEqual(list(self.verify_dir.glob("report-*.json")), [])
        self.assertEqual(self.sm.read_one(SPEC)["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
