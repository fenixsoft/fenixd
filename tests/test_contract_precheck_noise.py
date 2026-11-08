"""契约预检降噪（add-provider-validation-alert-governance 3.x，design D4）。

覆盖 tasks 3.1 / 3.2：

- implementing/ready 期 verify_contract_missing 前置预检降 info（只沉淀不召唤，
  FakeRunner 零唤起）；
- 触发窗口只取 ready/implementing——spec 进入 testing 后检测器不发任何信号，
  验证期契约仍缺按既有 major 语义由消费期通道（_write_verify_contract_missing，
  severity=major）负责，两段互斥不双发；
- 契约已裁决（可解析）零信号；
- 一次性判据持久化随告警账本（store 未处理记录在场即跳过）——daemon 重启
  （重建 monitor 实例）不重发；
- 记录被处置（handled）后允许再次提示——「去重态复位」的人工出口；
- cause 注入：contract 封闭映射（4.1 的检测器侧证据）。
"""

import tempfile
import unittest
from pathlib import Path

from core.admin_monitor import SIGNAL_SEVERITY, AdminMonitor
from core.admin_store import AdminStore
from core.verify_contract import CONTRACT_FILENAME

from test_admin import FakeRunner, FakeSM, make_monitor
from tests.helpers import FakeLogger

# 全注释模板态（fenix-init 写入形态）：文件存在但解析为 None
_TEMPLATE_YAML = "# template: contract 未裁决\n# 由 Administrator 起草\n"


def _write_template_contract(proot: Path) -> None:
    fenix = proot / ".fenix"
    fenix.mkdir(parents=True, exist_ok=True)
    (fenix / CONTRACT_FILENAME).write_text(_TEMPLATE_YAML, encoding="utf-8")


def _write_resolved_contract(proot: Path) -> None:
    fenix = proot / ".fenix"
    fenix.mkdir(parents=True, exist_ok=True)
    (fenix / CONTRACT_FILENAME).write_text(
        "prepare:\n  - cmd: 'true'\n", encoding="utf-8"
    )


class ContractPrecheckNoiseTest(unittest.TestCase):
    """实现期契约预检降噪语义（D4：info + 一次性 + 窗口互斥）。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def _monitor(self, specs: dict):
        # 恒带 FakeRunner：唤起面可断言（info 分支零唤起即 calls 为空）
        proot, mon = make_monitor(self.tmp, specs, runner=FakeRunner())
        return proot, mon

    def _specs(self, status: str) -> dict:
        return {
            "spec-a": {
                "status": status,
                "error": None,
                "updated": "2026-11-08T00:00:00",
            }
        }

    def test_implementing_preflight_emits_info_not_invocation(self):
        proot, mon = self._monitor(self._specs("implementing"))
        _write_template_contract(proot)
        signals = mon._detect_verify_contract_unresolved(mon.state_machine.read_all())
        self.assertEqual(len(signals), 1)
        sig = signals[0]
        self.assertEqual(sig["severity"], "info")
        self.assertEqual(sig["spec"], "spec-a")
        # 4.1：产生方按封闭映射标注根因（检测器经 _make_signal 注入）
        self.assertEqual(sig["cause"], "contract")
        self.assertIn("前置预检", sig["description"])
        self.assertIn("勿复位 spec 状态", sig["description"])

        # info 只沉淀不召唤：handle 后 Administrator 零唤起、账本有记录
        mon._handle_signal(sig)
        runner = mon.agent_runner
        self.assertEqual(runner.calls, [])
        store = AdminStore(proot)
        unhandled = [
            r for r in store.read_all()
            if r.get("signal_type") == "verify_contract_missing" and not r.get("handled")
        ]
        self.assertEqual(len(unhandled), 1)

    def test_ready_status_also_in_window(self):
        proot, mon = self._monitor(self._specs("ready"))
        _write_template_contract(proot)
        signals = mon._detect_verify_contract_unresolved(mon.state_machine.read_all())
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["severity"], "info")

    def test_out_of_window_emits_nothing(self):
        # spec 进入 testing（及之后）后检测器不发任何信号（info 也不发）：
        # 验证期契约仍缺按既有 major 由消费期通道负责，两段互斥不双发
        _write_template_contract(self.tmp)
        for status in ("testing", "blocked", "implemented"):
            _, mon = self._monitor(self._specs(status))
            signals = mon._detect_verify_contract_unresolved(mon.state_machine.read_all())
            self.assertEqual(signals, [], f"status={status} 不应成条")
        # 消费期通道的既有 major 语义留证（SIGNAL_SEVERITY 权威映射不变）
        self.assertEqual(SIGNAL_SEVERITY["verify_contract_missing"], "major")

    def test_resolved_contract_emits_nothing(self):
        proot, mon = self._monitor(self._specs("implementing"))
        _write_resolved_contract(proot)
        signals = mon._detect_verify_contract_unresolved(mon.state_machine.read_all())
        self.assertEqual(signals, [])

    def test_missing_contract_emits_nothing(self):
        # 文件缺失 = 合法无契约回退（ADR-080），预检不扩大触发面
        _, mon = self._monitor(self._specs("implementing"))
        signals = mon._detect_verify_contract_unresolved(mon.state_machine.read_all())
        self.assertEqual(signals, [])

    def test_no_resend_after_restart(self):
        # 一次性判据持久化随账本：重建 monitor（daemon 重启形态）不重发
        proot, mon = self._monitor(self._specs("implementing"))
        _write_template_contract(proot)
        first = mon._detect_verify_contract_unresolved(mon.state_machine.read_all())
        self.assertEqual(len(first), 1)
        mon._handle_signal(first[0])

        # 同一 project_root 重建 monitor + 全新 store 实例（重启形态）
        mon2 = AdminMonitor(
            {},
            FakeSM(self._specs("implementing")),
            proot,
            FakeLogger(),
            store=AdminStore(proot, FakeLogger()),
            agent_runner=FakeRunner(),
        )
        second = mon2._detect_verify_contract_unresolved(mon2.state_machine.read_all())
        self.assertEqual(second, [])

    def test_resend_allowed_after_record_handled(self):
        # 记录被处置（handled）后允许再次提示——「去重态复位」的人工出口
        proot, mon = self._monitor(self._specs("implementing"))
        _write_template_contract(proot)
        first = mon._detect_verify_contract_unresolved(mon.state_machine.read_all())
        self.assertEqual(len(first), 1)
        mon._handle_signal(first[0])

        store = AdminStore(proot)
        for rec in store.read_all():
            if rec.get("signal_type") == "verify_contract_missing":
                store.mark_signal_handled(rec["id"])
        second = mon._detect_verify_contract_unresolved(mon.state_machine.read_all())
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0]["severity"], "info")


if __name__ == "__main__":
    unittest.main()
