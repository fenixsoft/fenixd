"""judge-repair-scenario-writeback-gate：judge 原地修复写回受理门回归测试。

覆盖四组行为（tasks 4.1/4.2）：

1. 词表违规拒收（fail-closed 整批校验门）：judge 修复写回的场景集任一条目
   含跨 kind 词表违规（``run`` 步骤入 api 场景）→ 本轮修复被拒收——error
   留痕含逐条错误清单、spec 保持 testing、不重入执行、记账 rejected=True、
   裁决产物照常保留；错误清单经 error 字段（既有 prev-error 注入链载体）
   回传下轮 judge。
2. 全部合法正常受理（行为零变化锚点）：合法集照常进入冻结收编与重入；
   文件缺失 / 解析失败不在此拒收（既有 corrupt → env_blocked 语义不变）；
   remove_reason 声明条目豁免逐条校验（planner-judge.md 协议明确允许）。
3. 受理采纳成对落盘：采纳后 ``test_scenarios.json`` 与 ``_scenarios_full.json``
   内容一致且同版本戳；声明移除轮备份跟随更新；写序先备份后主文件；
   planner 收编路径（不传 pair_writeback）备份语义零变化锚点。
4. 预算耗尽交互：耗尽持久态拒收优先于本门预检，「无修复纯归因模式」
   文案与记账行为不变。

测试全部使用 tmp_path 隔离，不触碰现存 verify-progress 数据。
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.state_machine import StateMachine
from core.verify_scenarios import ScenarioEntry, ScenarioSet, save_scenario_set


def _valid_web_scenario(sid: str) -> dict:
    """合法 web 场景 dict（通过 validate_scenario_dicts）。"""
    return {
        "id": sid,
        "description": f"场景 {sid}",
        "kind": "web",
        "steps": [
            {"action": "navigate", "value": "http://127.0.0.1:8000/", "target": ""},
            {"action": "click", "target": f"#{sid}-btn", "value": ""},
        ],
        "assertions": [
            {"type": "element_visible", "selector": f"#{sid}-result", "label": "可见"},
        ],
    }


def _legal_api_scenario(sid: str = "scn-api") -> dict:
    """合法 api 场景 dict（词表内动作 http_request + status_code 断言）。"""
    return {
        "id": sid,
        "description": "api 场景",
        "kind": "api",
        "steps": [
            {
                "action": "http_request",
                "method": "GET",
                "url": "http://127.0.0.1:8000/api/items",
                "value": "",
            },
        ],
        "assertions": [
            {"type": "status_code", "expected": 200, "label": "状态码"},
        ],
    }


def _vocab_violation_scenario(sid: str = "scn-bad") -> dict:
    """跨 kind 词表违规：api 场景 steps 携带 cli 专属 ``run`` 步骤（本次事故直接根因形态）。"""
    return {
        "id": sid,
        "description": "坏 api 场景",
        "kind": "api",
        "steps": [
            {"action": "run", "command": "echo hi", "value": ""},
            {
                "action": "http_request",
                "method": "GET",
                "url": "http://127.0.0.1:8000/api/items",
                "value": "",
            },
        ],
        "assertions": [
            {"type": "status_code", "expected": 200, "label": "状态码"},
        ],
    }


def _make_pipe(tmpdir: str, sm: StateMachine):
    """最小 VerificationPipeline 桩（同 test_judge_repair_budget_alignment）。"""
    from core.pm_engine.verification import VerificationPipeline

    pm = SimpleNamespace()
    pm.project_root = Path(tmpdir)
    pm.logger = MagicMock()
    pm.state_machine = sm
    pm.agent_runner = MagicMock()
    pm._send_human_escalation_alert = MagicMock()
    pm._enqueue = MagicMock()
    pm._process_queue = MagicMock()
    return VerificationPipeline(pm)


def _make_testing_spec(sm: StateMachine, name: str = "demo-spec") -> None:
    sm.add_spec(name, {"priority": 5})
    sm.transition(name, "ready")
    sm.transition(name, "implementing")
    sm.transition(name, "implemented")
    sm.transition(name, "testing")


def _write_report(verify_dir: Path) -> Path:
    """judge 裁决产物 report.json（含 test-defect 记录）——门拒收后照常保留。"""
    report_path = verify_dir / "report.json"
    report_path.write_text(json.dumps({
        "spec": "demo-spec",
        "summary": {"total": 1, "passed": 0, "failed": 1, "warnings": 0},
        "scenarios": [
            {
                "scenario_id": "scn-bad",
                "status": "failed",
                "classification": "test-defect",
                "evidence": {"first_failed_step": "run echo hi"},
            },
        ],
    }, ensure_ascii=False), encoding="utf-8")
    return report_path


class _GateTestBase(unittest.TestCase):
    """公共夹具：tmp_path 隔离 + testing 态 spec + verify-progress 场景文件。"""

    SPEC = "demo-spec"

    def setUp(self, scenarios=None):
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.sm = StateMachine(
            Path(self.tmpdir) / ".fenix" / "STATE.md", MagicMock())
        _make_testing_spec(self.sm, self.SPEC)
        self.verify_dir = (
            Path(self.tmpdir) / ".fenix" / "verify-progress" / self.SPEC
        )
        self.verify_dir.mkdir(parents=True)
        self.scenarios_path = self.verify_dir / "test_scenarios.json"
        if scenarios is not None:
            self.scenarios_path.write_text(
                json.dumps(scenarios, ensure_ascii=False, indent=2),
                encoding="utf-8")
        self.report_path = _write_report(self.verify_dir)
        self.pipe = _make_pipe(self.tmpdir, self.sm)
        self.pipe._apply_scenario_freeze = MagicMock(return_value={})
        self.pipe._run_three_stage_verification = MagicMock()
        self.pipe._apply_verified = MagicMock()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _entry(self):
        return self.sm.read_one(self.SPEC)


class TestVocabViolationRejected(_GateTestBase):
    """词表违规条目（run 步骤入 api 场景）→ 整批拒收本轮修复。"""

    def setUp(self):
        super().setUp(
            scenarios=[_valid_web_scenario("scn-ok"), _vocab_violation_scenario()])

    def test_violation_rejects_whole_repair(self):
        """任一条非法 → 拒收：不收编、不重入、error 含错误清单、保持 testing。"""
        rv = self.pipe._handle_scenario_repaired(self.SPEC, "scenario-repaired", 0)
        self.assertTrue(rv)
        self.pipe._apply_scenario_freeze.assert_not_called()
        self.pipe._run_three_stage_verification.assert_not_called()
        entry = self._entry()
        # error 留痕：含「写端校验失败拒收」文案 + 词表错误描述（该条目的
        # 违规定位与支持词表），截断口径前 3 条 + 总条数
        error = str(entry.get("error"))
        self.assertIn("写端校验失败拒收", error)
        self.assertIn("scn-bad", error)
        self.assertIn("run", error)
        self.assertIn("http_request", error)
        self.assertIn("共 1 条违规", error)
        # spec 保持 testing
        self.assertEqual(entry["status"], "testing")
        # 场景文件不被门改写（拒收不收编，盘上保留 judge 原样供下轮重修）
        disk = json.loads(self.scenarios_path.read_text(encoding="utf-8"))
        self.assertEqual([s["id"] for s in disk], ["scn-ok", "scn-bad"])
        # 记账：申报 +1、拒收 +1、摘要留痕（取自裁决产物非 PASS 场景 id）
        self.assertEqual(int(entry.get("_judge_repair_claim_rounds") or 0), 1)
        self.assertEqual(int(entry.get("_judge_repair_rejected_rounds") or 0), 1)
        self.assertEqual(entry.get("_judge_repair_last_summary"), "scn-bad")
        # WARNING 留痕
        warnings = [
            str(c.args[-1] if c.args else "")
            for c in self.pipe._context.logger.warning.call_args_list
        ]
        self.assertTrue(any("写端校验门拒收" in w for w in warnings))

    def test_rejection_returns_true_never_false(self):
        """拒收 MUST NOT 返回 False（防穿透平铺尾段假收敛 verified）。"""
        for depth in (0, 1):
            self.pipe._apply_scenario_freeze.reset_mock()
            self.pipe._run_three_stage_verification.reset_mock()
            rv = self.pipe._handle_scenario_repaired(
                self.SPEC, "scenario-repaired", depth)
            self.assertTrue(rv)
        self.pipe._apply_verified.assert_not_called()
        self.pipe._run_three_stage_verification.assert_not_called()

    def test_verdict_artifact_preserved(self):
        """裁决产物照常保留（test-defect 仅记录，门不删除不改写产物）。"""
        self.pipe._handle_scenario_repaired(self.SPEC, "scenario-repaired", 0)
        report = json.loads(self.report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["scenarios"][0]["classification"], "test-defect")

    def test_non_dict_item_rejected(self):
        """非对象条目混入 → 同样整批拒收（fail-closed 不剔除继续）。"""
        self.scenarios_path.write_text(
            json.dumps([_valid_web_scenario("scn-ok")])[:-1] + ', "garbage"]',
            encoding="utf-8")
        rv = self.pipe._handle_scenario_repaired(self.SPEC, "scenario-repaired", 0)
        self.assertTrue(rv)
        self.pipe._apply_scenario_freeze.assert_not_called()
        self.assertIn("非对象", str(self._entry().get("error")))


class TestAllLegalAccepted(_GateTestBase):
    """全部合法 → 照常受理进入既有冻结/重入流程（行为零变化锚点）。"""

    def setUp(self):
        super().setUp(
            scenarios=[_valid_web_scenario("scn-ok"), _legal_api_scenario()])

    def test_legal_set_accepted_into_existing_flow(self):
        """合法集 → 正常受理：冻结收编 + 尾递归重入，无拒收 error。"""
        rv = self.pipe._handle_scenario_repaired(self.SPEC, "scenario-repaired", 0)
        self.assertTrue(rv)
        # 受理采纳走成对落盘模式（design D3）
        self.pipe._apply_scenario_freeze.assert_called_once_with(
            self.SPEC, pair_writeback=True)
        self.pipe._run_three_stage_verification.assert_called_once()
        self.assertEqual(
            self.pipe._run_three_stage_verification.call_args.kwargs.get(
                "_repair_depth"),
            1)
        entry = self._entry()
        self.assertEqual(entry["status"], "testing")
        self.assertNotIn("写端校验失败拒收", str(entry.get("error") or ""))
        self.assertEqual(int(entry.get("_judge_repair_claim_rounds") or 0), 1)
        self.assertEqual(int(entry.get("_judge_repair_rejected_rounds") or 0), 0)

    def test_missing_file_skips_precheck(self):
        """文件不存在 → 预检不适用，既有受理路径不受阻。"""
        self.scenarios_path.unlink()
        rv = self.pipe._handle_scenario_repaired(self.SPEC, "scenario-repaired", 0)
        self.assertTrue(rv)
        self.pipe._apply_scenario_freeze.assert_called_once()
        self.pipe._run_three_stage_verification.assert_called_once()

    def test_unparseable_file_skips_precheck(self):
        """解析失败（坏 JSON）→ 预检不拒收，维持既有 corrupt → env_blocked 语义。"""
        self.scenarios_path.write_text("{broken json", encoding="utf-8")
        rv = self.pipe._handle_scenario_repaired(self.SPEC, "scenario-repaired", 0)
        self.assertTrue(rv)
        self.pipe._apply_scenario_freeze.assert_called_once()
        self.assertNotIn(
            "写端校验失败拒收", str(self._entry().get("error") or ""))

    def test_remove_reason_declaration_exempt(self):
        """remove_reason 声明条目豁免逐条校验（planner-judge.md 协议明确允许）。"""
        self.scenarios_path.write_text(json.dumps([
            _valid_web_scenario("scn-ok"),
            {"id": "scn-gone", "remove_reason": "对应测试已删除，场景失效"},
        ], ensure_ascii=False), encoding="utf-8")
        rv = self.pipe._handle_scenario_repaired(self.SPEC, "scenario-repaired", 0)
        self.assertTrue(rv)
        self.pipe._apply_scenario_freeze.assert_called_once()
        self.pipe._run_three_stage_verification.assert_called_once()
        self.assertNotIn(
            "写端校验失败拒收", str(self._entry().get("error") or ""))

    def test_non_repaired_status_passthrough(self):
        """非 scenario-repaired → False（调用方继续后续分支），零副作用。"""
        self.assertEqual(
            self.pipe._handle_scenario_repaired(self.SPEC, "verified", 0), False)
        self.pipe._apply_scenario_freeze.assert_not_called()


class _FreezeFixture:
    """real-freeze 夹具（同 test_frozen_scenario_reservoir 形态，unittest 适配）。"""

    SPEC = "pair-spec"

    def setup_freeze(self, tmpdir, planner_scenarios, persisted_entries=None,
                     backup_scenarios=None):
        (Path(tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.sm = StateMachine(
            Path(tmpdir) / ".fenix" / "STATE.md", MagicMock())
        _make_testing_spec(self.sm, self.SPEC)
        self.verify_dir = (
            Path(tmpdir) / ".fenix" / "verify-progress" / self.SPEC
        )
        self.verify_dir.mkdir(parents=True)
        self.scenarios_path = self.verify_dir / "test_scenarios.json"
        self.scenarios_path.write_text(
            json.dumps(planner_scenarios, ensure_ascii=False, indent=2),
            encoding="utf-8")
        if persisted_entries is not None:
            save_scenario_set(
                Path(tmpdir), ScenarioSet(self.SPEC, 1, persisted_entries))
        if backup_scenarios is not None:
            (self.verify_dir / "_scenarios_full.json").write_text(
                json.dumps(backup_scenarios, ensure_ascii=False, indent=2),
                encoding="utf-8")
        self.pipe = _make_pipe(tmpdir, self.sm)
        # 仅 mock 重入与 verified 收敛，冻结走真实实现
        self.pipe._run_three_stage_verification = MagicMock()
        self.pipe._apply_verified = MagicMock()

    def accept(self):
        return self.pipe._handle_scenario_repaired(
            self.SPEC, "scenario-repaired", 0)

    def _read(self, name):
        return json.loads(
            (self.verify_dir / name).read_text(encoding="utf-8"))

    def _assert_pair(self, main, backup):
        """主文件与备份内容一致且条目携带同一组版本戳。"""
        self.assertEqual(main, backup)
        for doc in (main, backup):
            self.assertTrue(doc)
            for item in doc:
                self.assertIn("schema_version", item)
                self.assertIn("contract_version", item)
        self.assertEqual(
            main[0]["schema_version"], backup[0]["schema_version"])
        self.assertEqual(
            main[0]["contract_version"], backup[0]["contract_version"])


class TestPairWritebackMainPath(_FreezeFixture, unittest.TestCase):
    """成对落盘·主路径：合法集受理后两文件成对一致（tasks 2.1/4.1）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.setup_freeze(self.tmpdir, planner_scenarios=[
            _valid_web_scenario("scn-a"),
            _legal_api_scenario("scn-b"),
        ])

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_accepted_pair_files_consistent(self):
        """受理采纳后 test_scenarios.json 与 _scenarios_full.json 成对同版本戳。"""
        self.assertTrue(self.accept())
        self.pipe._run_three_stage_verification.assert_called_once()
        main = self._read("test_scenarios.json")
        backup = self._read("_scenarios_full.json")
        self._assert_pair(main, backup)
        self.assertEqual(
            sorted(s["id"] for s in main), ["scn-a", "scn-b"])

    def test_write_order_backup_before_main(self):
        """写序纪律：先 _scenarios_full.json 后 test_scenarios.json（5b 同款）。"""
        from unittest.mock import patch
        import core.pm_engine.verification.scenario_gate as sg
        calls = []
        real = sg._atomic_write_text

        def spy(path, content, **kw):
            calls.append(Path(path).name)
            return real(path, content, **kw)

        with patch.object(sg, "_atomic_write_text", spy):
            self.assertTrue(self.accept())
        # 仅计冻结层两个成对写点（persisted scenarios.json 走独立写端）
        freeze_calls = [
            n for n in calls if n in ("_scenarios_full.json", "test_scenarios.json")
        ]
        self.assertEqual(
            freeze_calls, ["_scenarios_full.json", "test_scenarios.json"])


class TestPairWritebackDeclaredRemoval(_FreezeFixture, unittest.TestCase):
    """成对落盘·声明移除轮：judge 协议允许的 remove_reason 移除不撕裂备份。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # 持久化集含 scn-a + scn-b；judge 修复集 = 修复后的 scn-a + 声明移除
        # scn-b；旧备份停留修复前定义（scn-a 带旧端口 + scn-b）。
        self.setup_freeze(
            self.tmpdir,
            planner_scenarios=[
                _valid_web_scenario("scn-a"),
                {"id": "scn-b", "remove_reason": "对应用例已删除，场景失效"},
            ],
            persisted_entries=[
                ScenarioEntry("scn-a", "场景A", added_in_round=1, kind="web"),
                ScenarioEntry("scn-b", "场景B", added_in_round=1, kind="web"),
            ],
            backup_scenarios=[
                _valid_web_scenario("scn-a"),
                _valid_web_scenario("scn-b"),
            ],
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_pair_mode_updates_backup_on_removal_round(self):
        """受理成对模式：声明移除轮备份也更新为修复后集合（撕裂窗口消灭）。"""
        self.assertTrue(self.accept())
        main = self._read("test_scenarios.json")
        backup = self._read("_scenarios_full.json")
        self._assert_pair(main, backup)
        # 被移除场景不在两文件；修复后的 scn-a 两文件一致（旧备份定义被覆盖）
        self.assertEqual([s["id"] for s in main], ["scn-a"])

    def test_planner_path_keeps_backup_semantics(self):
        """planner 收编路径（缺省无 pair_writeback）零变化锚点：声明移除轮
        备份维持既有「有删减不更新」语义（保留最全历史定义）。"""
        from core.pm_engine.verification.scenario_gate import _apply_scenario_freeze
        old_backup = self._read("_scenarios_full.json")
        _apply_scenario_freeze(self.pipe, self.SPEC)
        backup = self._read("_scenarios_full.json")
        self.assertEqual(backup, old_backup)


class TestPairWritebackReconcileBranch(_FreezeFixture, unittest.TestCase):
    """成对落盘·补齐分支：无理由缺场景回补后按 5b 顺序成对覆盖。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # judge 修复集漏掉 scn-b 且未声明理由 → 框架按持久化集回补（回补后
        # 成对覆盖两文件）。旧备份含旧定义（scn-a 带旧 URL，judge 修复后
        # 的 scn-a 不应被回补覆盖）。
        self.setup_freeze(
            self.tmpdir,
            planner_scenarios=[_valid_web_scenario("scn-a")],
            persisted_entries=[
                ScenarioEntry("scn-a", "场景A", added_in_round=1, kind="web"),
                ScenarioEntry("scn-b", "场景B", added_in_round=1, kind="web"),
            ],
            backup_scenarios=[
                _valid_web_scenario("scn-a"),
                _valid_web_scenario("scn-b"),
            ],
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_reconcile_pair_order_and_consistency(self):
        from unittest.mock import patch
        import core.pm_engine.verification.scenario_gate as sg
        calls = []
        real = sg._atomic_write_text

        def spy(path, content, **kw):
            calls.append(Path(path).name)
            return real(path, content, **kw)

        with patch.object(sg, "_atomic_write_text", spy):
            self.assertTrue(self.accept())
        # 先备份后主文件（5b 固定顺序，仅计冻结层两写点）
        freeze_calls = [
            n for n in calls if n in ("_scenarios_full.json", "test_scenarios.json")
        ]
        self.assertEqual(
            freeze_calls, ["_scenarios_full.json", "test_scenarios.json"])
        main = self._read("test_scenarios.json")
        backup = self._read("_scenarios_full.json")
        self._assert_pair(main, backup)
        # 回补不覆盖 judge 修复：scn-b 补回、scn-a 仍为 judge 修复后集合
        self.assertEqual(
            sorted(s["id"] for s in main), ["scn-a", "scn-b"])


class TestExhaustedInteraction(_GateTestBase):
    """预算耗尽持久态交互：既有「无修复纯归因模式」语义优先于本门预检。"""

    def setUp(self):
        super().setUp(
            scenarios=[_valid_web_scenario("scn-ok"), _vocab_violation_scenario()])
        self.sm.update_spec(self.SPEC, {"_scenario_repair_exhausted_rounds": 1})

    def test_exhausted_gate_takes_precedence(self):
        """耗尽态 + 盘上非法集 → 走既有纯归因拒收，本门预检不消费该轮。"""
        rv = self.pipe._handle_scenario_repaired(self.SPEC, "scenario-repaired", 0)
        self.assertTrue(rv)
        self.pipe._apply_scenario_freeze.assert_not_called()
        self.pipe._run_three_stage_verification.assert_not_called()
        entry = self._entry()
        error = str(entry.get("error"))
        # 既有纯归因拒收文案不变；不含本门文案
        self.assertIn("纯归因", error)
        self.assertIn("拒收", error)
        self.assertNotIn("写端校验失败拒收", error)
        self.assertEqual(entry["status"], "testing")
        # 记账口径不变：申报 +1、耗尽后拒收 +1
        self.assertEqual(int(entry.get("_judge_repair_claim_rounds") or 0), 1)
        self.assertEqual(int(entry.get("_judge_repair_rejected_rounds") or 0), 1)
        # 耗尽字段未被本路径清除
        self.assertGreaterEqual(
            int(entry.get("_scenario_repair_exhausted_rounds") or 0), 1)

    def test_exhausted_rejection_independent_of_disk_state(self):
        """耗尽态下盘上集合法与否不影响拒收语义（门挂在预检之前）。"""
        self.scenarios_path.write_text(
            json.dumps([_valid_web_scenario("scn-ok")], ensure_ascii=False),
            encoding="utf-8")
        rv = self.pipe._handle_scenario_repaired(self.SPEC, "scenario-repaired", 0)
        self.assertTrue(rv)
        self.assertIn("纯归因", str(self._entry().get("error")))


if __name__ == "__main__":
    unittest.main()
