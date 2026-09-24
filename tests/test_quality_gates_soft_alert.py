"""fix-quality-gates-flat-form-and-explainability 3.x：宽松对账形态违规告警用例。

覆盖 specs/quality-gates-soft-gate-alerts/spec.md：
- 四类违规（missing-gates / bad-json / out-of-contract-gate-id /
  out-of-enum-status）各产生一条 admin_alerts 告警且字段齐全（kind=SIGNAL、
  signal_type=quality-gates-form-drift、severity=info、spec、文件相对路径、
  violation_class），闭环端点 mark_signal_handled 可达；
- append_if_absent 去重：同 spec 同类别未处理期间不重复、异类别不互相抑制；
- 写入异常 fail-open：告警通道故障不影响对账收尾主流程；
- 软约束边界零回归：违规仅告警放行，对账后无任何失败终态信号。

自查结论：本 SPEC 未触碰前端，src/ 下 qualityGates 相关模块零改动
（core/dashboard/static/ 及 qualityGates.test.mjs 既有断言零变化，detail
文案由读侧填充、经既有 gateDetailText 透传链渲染）。
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.admin_store import SIGNAL, AdminStore
from core.agent_runner import result_gate

SPEC = "demo"
DRIFT = "quality-gates-form-drift"


class SoftAlertBase:
    """公共夹具：tmp 项目根 + worktree + 最小 runner（make_runner 先例）。"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir) / "proj"
        self.proot.mkdir()
        self.wt = Path(self.tmpdir) / "wt"
        self.wt.mkdir()
        from test_agent_runner import make_runner

        self.runner = make_runner(self.proot)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _gates_path(self, base: Path | None = None) -> Path:
        return (base or self.wt) / ".fenix" / "verify-progress" / SPEC / "quality-gates.json"

    def _write_gates(self, data) -> None:
        p = self._gates_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            data if isinstance(data, str) else json.dumps(data, ensure_ascii=False),
            encoding="utf-8",
        )

    def _drift_alerts(self) -> list:
        return [
            r for r in AdminStore(self.proot).read_all()
            if r.get("signal_type") == DRIFT
        ]


class TestFourViolationClassesAlert(SoftAlertBase):
    """四类违规各产生一条告警且字段齐全（含 kind=SIGNAL 与 violation_class）。"""

    def test_missing_gates_flat_form_alerts_with_full_fields(self, caplog):
        # 平铺形态（顶层缺 gates）——读侧容错兜底后，写侧偏离契约仍要让人工可见
        self._write_gates({
            "frontend-build": {"status": "passed"},
            "interaction-contract": {"status": "passed"},
            "updated_at": "2026-09-24T00:00:00Z",
        })
        with caplog.at_level("WARNING", logger="fenixd.agent_runner.result_gate"):
            assert result_gate._check_quality_gates_soft(self.runner, SPEC, self.wt) is None
        alerts = self._drift_alerts()
        assert len(alerts) == 1
        a = alerts[0]
        assert a["kind"] == SIGNAL  # 显式 kind：闭环端点只认 SIGNAL
        assert a["severity"] == "info"
        assert a["spec"] == SPEC
        assert a["violation_class"] == "missing-gates"
        assert a["file"] == f".fenix/verify-progress/{SPEC}/quality-gates.json"
        assert "顶层缺 gates 对象" in a["description"] and SPEC in a["description"]
        # 既有 WARNING 日志保留（可见性增强是叠加，不是替换）
        assert any("顶层缺 gates 对象" in r.getMessage() for r in caplog.records)
        # 闭环端点可达（mark_alert_handled → mark_signal_handled 分派）
        assert AdminStore(self.proot).mark_signal_handled(a["id"]) is True

    def test_bad_json_alerts(self):
        self._write_gates("{broken")
        assert result_gate._check_quality_gates_soft(self.runner, SPEC, self.wt) is None
        alerts = self._drift_alerts()
        assert len(alerts) == 1
        assert alerts[0]["violation_class"] == "bad-json"
        assert alerts[0]["kind"] == SIGNAL and alerts[0]["severity"] == "info"

    def test_out_of_contract_gate_id_alerts(self):
        self._write_gates({"gates": {"code-review": {"status": "passed"}}})
        assert result_gate._check_quality_gates_soft(self.runner, SPEC, self.wt) is None
        alerts = self._drift_alerts()
        assert len(alerts) == 1
        assert alerts[0]["violation_class"] == "out-of-contract-gate-id"
        assert "code-review" in alerts[0]["description"]

    def test_out_of_enum_status_alerts(self):
        self._write_gates({"gates": {"full-suite": {"status": "ok"}}})
        assert result_gate._check_quality_gates_soft(self.runner, SPEC, self.wt) is None
        alerts = self._drift_alerts()
        assert len(alerts) == 1
        assert alerts[0]["violation_class"] == "out-of-enum-status"
        assert "full-suite" in alerts[0]["description"]


class TestDedup(SoftAlertBase):
    """append_if_absent 去重：同 spec 同类别未处理期间不重复、异类别不互相抑制。"""

    def test_same_class_not_duplicated_while_unhandled(self):
        self._write_gates({"frontend-build": {"status": "passed"}})
        for _ in range(3):
            assert result_gate._check_quality_gates_soft(self.runner, SPEC, self.wt) is None
        assert len(self._drift_alerts()) == 1

    def test_handled_alert_allows_new_occurrence(self):
        self._write_gates({"frontend-build": {"status": "passed"}})
        result_gate._check_quality_gates_soft(self.runner, SPEC, self.wt)
        first = self._drift_alerts()[0]
        assert AdminStore(self.proot).mark_signal_handled(first["id"]) is True
        assert result_gate._check_quality_gates_soft(self.runner, SPEC, self.wt) is None
        assert len(self._drift_alerts()) == 2  # 已处理后再现 → 新告警

    def test_different_classes_not_suppressed(self):
        # 先落一条 missing-gates（平铺形态）
        self._write_gates({"frontend-build": {"status": "passed"}})
        result_gate._check_quality_gates_soft(self.runner, SPEC, self.wt)
        # 换嵌套形态但含契约外 gate-id + 枚举外 status——异类别不互相抑制
        self._write_gates({"gates": {
            "code-review": {"status": "passed"},
            "full-suite": {"status": "ok"},
        }})
        result_gate._check_quality_gates_soft(self.runner, SPEC, self.wt)
        classes = sorted(a["violation_class"] for a in self._drift_alerts())
        assert classes == [
            "missing-gates", "out-of-contract-gate-id", "out-of-enum-status",
        ]


class TestFailOpen(SoftAlertBase):
    """写入异常 fail-open：仅记 WARNING，run 收尾与对账主流程零影响。"""

    def test_store_failure_swallowed(self, caplog, monkeypatch):
        self._write_gates({"frontend-build": {"status": "passed"}})

        def _boom(self, entry, is_inflight):
            raise OSError("disk full")

        monkeypatch.setattr(AdminStore, "append_if_absent", _boom)
        with caplog.at_level("WARNING", logger="fenixd.agent_runner.result_gate"):
            out = result_gate._check_quality_gates_soft(self.runner, SPEC, self.wt)
        assert out is None  # 对账主流程零影响
        assert any("fail-open" in r.getMessage() for r in caplog.records)


class TestSoftBoundaryZeroRegression(SoftAlertBase):
    """软约束边界零回归：对账后无任何失败终态信号。"""

    def test_all_violations_only_alert_never_block(self):
        # 三轮违规齐发（missing-gates / bad-json / out-of-contract+out-of-enum）
        self._write_gates({"frontend-build": {"status": "passed"}})
        assert result_gate._check_quality_gates_soft(self.runner, SPEC, self.wt) is None
        self._write_gates("{broken")
        assert result_gate._check_quality_gates_soft(self.runner, SPEC, self.wt) is None
        self._write_gates({"gates": {
            "code-review": {"status": "passed"},
            "full-suite": {"status": "ok"},
        }})
        assert result_gate._check_quality_gates_soft(self.runner, SPEC, self.wt) is None
        store = AdminStore(self.proot)
        for a in self._drift_alerts():
            assert a["kind"] == SIGNAL  # 仅可见不需裁决：不进 ESCALATION 桶
            assert a["severity"] == "info"
            assert "choices" not in a  # 不注册 choices（不可裁决桶）
        assert store.unhandled() == []  # 无升级告警 → 无失败终态/自动唤起

    def test_missing_file_zero_alert_zero_interception(self):
        assert result_gate._check_quality_gates_soft(self.runner, SPEC, self.wt) is None
        assert self._drift_alerts() == []

    def test_valid_file_zero_alert(self):
        self._write_gates({
            "gates": {"full-suite": {"status": "passed", "passed": 1, "failed": 0}},
            "updated_at": "2026-09-24T00:00:00Z",
        })
        assert result_gate._check_quality_gates_soft(self.runner, SPEC, self.wt) is None
        assert self._drift_alerts() == []
