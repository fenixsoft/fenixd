"""
场景修订重验出口全链单元测试（evo-fix-env-exemption-gate-conflict-… 3.3）

覆盖：
  - 修订全链（2.1）：inconclusive 停车 → revise_scenario_reverify 修订场景集
    与夹具供给层文件 → 成对覆盖场景定义文件 → 置 re-entry 旗标 + 解冻 +
    testing + 调度唤醒；修订后首轮仍失败的 re-entry 先于升级（消费旗标追加
    一次重验，2.2）
  - 白名单（2.1）：产品代码路径 / 绝对路径 / 穿越拒绝，非法场景集拒绝
  - 修订上限（2.1）：达上限（默认 2）拒绝修订并冻结转人工
  - env 归因证据门（2.3）：声称媒体管线类失败却缺送帧/解码两段证据引用 →
    级二判定降级 inconclusive（不触发豁免/升级语义）；非媒体 env 归因不受约束
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# 确保 tests 目录在 import 路径（兼容直接执行）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.dashboard.data.admin_actions import execute_adjudication_choice
from core.dashboard.data.adjudication_choices import (
    SCENARIO_REVISION_ALLOWED_DIRS,
    validate_scenario_revision_paths,
)
from core.pm_engine.engine import PMEngine
from core.state_machine import SCENARIO_REVISION_MAX_COUNT, StateMachine


class _FakeLogger:
    def __init__(self):
        self.messages = []

    def _log(self, level, *args):
        self.messages.append((level,) + tuple(str(a) for a in args))

    def info(self, *args):
        self._log("info", *args)

    def warning(self, *args):
        self._log("warning", *args)

    def error(self, *args):
        self._log("error", *args)

    def debug(self, *args):
        self._log("debug", *args)


def _mk_engine(tmpdir, config=None):
    """构造 PMEngine 实例（临时 STATE + 真实 StateMachine + AdminStore）。"""
    project_root = Path(tmpdir)
    (project_root / ".fenix").mkdir(parents=True, exist_ok=True)
    logger = _FakeLogger()
    sm = StateMachine(project_root / ".fenix" / "STATE.md", logger)
    config = dict(config or {})
    engine = PMEngine(sm, mock.MagicMock(), config, project_root, logger)
    sm.add_spec("s1", {"priority": 5})
    sm.update_spec("s1", {"status": "testing"})
    return engine, sm, logger


def _pass_scenarios(n=19):
    return [{"scenario_id": f"pass-{i}", "status": "pass"} for i in range(n)]


def _env_fail_scenario(sid="fail-env-0", n_assertions=1):
    """断言级 triage 全 env、场景级 classification 未标 env 的失败场景。"""
    return {
        "scenario_id": sid,
        "status": "failed",
        "assertion_triage": [
            {
                "assertion": f"text=空态文案 {i}",
                "classification": "env",
                "evidence": "served dist 为中间态构建",
            }
            for i in range(n_assertions)
        ],
    }


def _mixed_env_report(passed=19, failed=2, blocked=1):
    """judge 已裁决全 env 的混合形态（add-session-composer 事故同形态）。"""
    scenarios = _pass_scenarios(passed)
    scenarios.extend(
        _env_fail_scenario(sid=f"fail-env-{i}", n_assertions=3) for i in range(failed)
    )
    for i in range(blocked):
        scenarios.append({
            "scenario_id": f"blk-{i}",
            "status": "blocked-env",
            "env_probe_detail": "HTTP 探测失联",
        })
    return {
        "summary": {
            "total": len(scenarios), "passed": passed,
            "warnings": blocked, "failed": failed, "errors": 0,
            "blocked_env": blocked,
        },
        "scenarios": scenarios,
    }


def _revised_scenarios():
    """修订后的合法场景集（绝对 URL navigate + 合法断言原语）。"""
    return [
        {
            "id": "s-1",
            "name": "列表页加载",
            "kind": "web",
            "steps": [
                {"action": "navigate", "value": "http://127.0.0.1:8787/list"},
            ],
            "assertions": [
                # 断言键须用运行层实际消费的规范形态（fix_scope=test，回归重试轮）：
                # _assert_text_contains 只读 text/expected（二选一）、元素定位读
                # selector；target/value 从不消费，场景定义校验（item ea8d6a657ca4
                # 前移运行层缺参守卫）按「缺 text/expected」打回属预期行为
                {"type": "text_contains", "selector": "body", "expected": "共"},
            ],
            "depends_on": [],
        },
    ]


def _revision_payload(scenarios=None, fixture_files=None, reason="断言文本随数据量变化"):
    payload = {"scenarios": _revised_scenarios() if scenarios is None else scenarios}
    if reason:
        payload["reason"] = reason
    if fixture_files is not None:
        payload["fixture_files"] = fixture_files
    return json.dumps(payload, ensure_ascii=False)


def _parse_state_entry(tmpdir, spec="s1"):
    from core.dashboard.data.state import parse_state

    return parse_state(Path(tmpdir)).get(spec) or {}


def _park(tmpdir):
    """构造级二停车形态（生产时序：report.json 先落盘再停车）。"""
    engine, sm, logger = _mk_engine(tmpdir)
    report = _mixed_env_report()
    vp = Path(tmpdir) / ".fenix" / "verify-progress" / "s1"
    vp.mkdir(parents=True, exist_ok=True)
    (vp / "report.json").write_text(
        json.dumps(report, ensure_ascii=False), encoding="utf-8"
    )
    handled = engine._verification._handle_env_exemption_handshake("s1", report)
    assert handled, "前置：级二命中应停车"
    return engine, sm


# ── 2.1：修订执行器全链 ──────────────────────────────────────────────────


class TestReviseScenarioReverifyExecutor(unittest.TestCase):
    """Scenario: 场景不可行 → 修订 → 重验 → 解冻的出口全链。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))

    def test_full_revision_cycle(self):
        """停车 → 修订 → 成对落盘 + 旗标置位 + 解冻 + testing + 唤醒。"""
        engine, sm = _park(self.tmpdir)
        # 冻结形态起步也应被修订出口解冻（重验前从冻结集合摘除）
        sm.update_spec("s1", {"frozen": True})
        with mock.patch.object(engine, "_enqueue") as enq:
            r = execute_adjudication_choice(
                Path(self.tmpdir), "s1", "revise_scenario_reverify",
                note=_revision_payload(
                    fixture_files=[{"path": ".fenix/fixtures/seed.json",
                                    "content": "{\"rows\": 42}"}],
                ),
                signal_type="inconclusive_loop",
            )
        self.assertTrue(r.get("ok"), f"修订应成功：{r.get('error')}")
        # 夹具供给层文件按 project_root 锚定落盘
        fixture = Path(self.tmpdir) / ".fenix" / "fixtures" / "seed.json"
        self.assertTrue(fixture.exists(), "夹具文件应落盘")
        self.assertEqual(json.loads(fixture.read_text(encoding="utf-8")),
                         {"rows": 42})
        # 场景定义成对同覆盖（防对账回填旧定义）
        vp = Path(self.tmpdir) / ".fenix" / "verify-progress" / "s1"
        for name in ("test_scenarios.json", "_scenarios_full.json"):
            self.assertTrue((vp / name).exists(), f"{name} 应落盘")
            saved = json.loads((vp / name).read_text(encoding="utf-8"))
            self.assertEqual([s["id"] for s in saved], ["s-1"])
            self.assertEqual(saved[0].get("contract_version"), 2,
                             "修订落盘应为当前契约版本")
        # STATE：计数 +1、re-entry 旗标置位、解冻、testing
        entry = _parse_state_entry(self.tmpdir)
        self.assertEqual(int(entry.get("_scenario_revision_count") or 0), 1)
        self.assertEqual(
            str(entry.get("_scenario_revision_reverify_pending") or "").lower(),
            "true", "修订 re-entry 旗标应置位",
        )
        self.assertFalse(entry.get("frozen"), "重验前应从冻结集合摘除")
        self.assertEqual(entry.get("status"), "testing", "应重入验证车道")
        self.assertIsNone(entry.get("error"), "停车 error 应清")
        self.assertIn("已写调度唤醒信号", "；".join(r.get("steps") or []),
                      "应写调度唤醒信号重派 verifier")

    def test_revision_reentry_consumed_before_escalation(self):
        """修订后首轮仍失败：re-entry 先于升级——消费旗标追加一次重验。"""
        engine, sm = _park(self.tmpdir)
        r = execute_adjudication_choice(
            Path(self.tmpdir), "s1", "revise_scenario_reverify",
            note=_revision_payload(), signal_type="inconclusive_loop",
        )
        self.assertTrue(r.get("ok"))
        # 修订后重验仍失败 → 再次到达升级停车入口（级二命中）
        report = _mixed_env_report()
        with mock.patch.object(engine, "_enqueue") as enq:
            handled = engine._verification._handle_env_exemption_handshake(
                "s1", report
            )
        self.assertTrue(handled, "入口仍按已处置返回 True")
        enq.assert_called_once()
        args = enq.call_args[0]
        self.assertEqual(args[0], "s1")
        self.assertEqual(args[1], "verifier", "应追加派发 verifier 重验")
        entry = _parse_state_entry(self.tmpdir)
        self.assertEqual(
            str(entry.get("_scenario_revision_reverify_pending") or "").lower(),
            "false", "re-entry 旗标应单次消费",
        )
        self.assertEqual(entry.get("status"), "implemented",
                         "追加轮停车 implemented 等待（再失败将升级转人工）")

    def test_invalid_scenario_set_rejected(self):
        """非法场景集（校验器报错）：拒绝执行，不落盘不改 STATE。"""
        _park(self.tmpdir)
        bad = [{"id": "s-1", "name": "缺步骤", "kind": "web", "steps": []}]
        r = execute_adjudication_choice(
            Path(self.tmpdir), "s1", "revise_scenario_reverify",
            note=_revision_payload(scenarios=bad, fixture_files=[]),
            signal_type="inconclusive_loop",
        )
        self.assertFalse(r.get("ok"), "非法场景集应被拒绝")
        self.assertIn("校验失败", r.get("error") or "")
        vp = Path(self.tmpdir) / ".fenix" / "verify-progress" / "s1"
        self.assertFalse((vp / "test_scenarios.json").exists(),
                         "拒绝时不得落盘")
        entry = _parse_state_entry(self.tmpdir)
        self.assertIsNone(entry.get("_scenario_revision_count"),
                          "拒绝时不得计入修订次数")


class TestRevisionPathWhitelist(unittest.TestCase):
    """Scenario: 修订文件路径白名单——产品代码路径拒绝。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))

    def test_product_code_path_rejected(self):
        """产品代码路径（core/ 下）：拒绝执行，夹具与 STATE 均不动。"""
        engine, sm = _park(self.tmpdir)
        r = execute_adjudication_choice(
            Path(self.tmpdir), "s1", "revise_scenario_reverify",
            note=_revision_payload(fixture_files=[
                {"path": "core/state_machine.py", "content": "# pwned"},
            ]),
            signal_type="inconclusive_loop",
        )
        self.assertFalse(r.get("ok"), "产品代码路径应被拒绝")
        self.assertIn("白名单", r.get("error") or "")
        self.assertEqual(
            Path(self.tmpdir, "core", "state_machine.py").exists(), False,
            "拒绝时不得写任何文件",
        )
        entry = _parse_state_entry(self.tmpdir)
        self.assertIsNone(entry.get("_scenario_revision_count"))
        self.assertNotEqual(entry.get("status"), "testing",
                            "拒绝时不得重入验证车道")

    def test_absolute_and_traversal_rejected(self):
        """绝对路径与穿越路径拒绝（project_root 锚定）。"""
        for bad in ("/etc/passwd", "../../etc/passwd", "~/.ssh/id_rsa",
                    "fixtures/../../escape.yaml"):
            msg = validate_scenario_revision_paths(self.tmpdir, [bad])
            self.assertTrue(msg, f"{bad} 应被拒绝")
        for good in (".fenix/fixtures/a.json", "fixtures/b.yaml",
                     "tests/fixtures/c.json", ".fenix/verify.yaml"):
            msg = validate_scenario_revision_paths(self.tmpdir, [good])
            self.assertEqual(msg, "", f"{good} 应在白名单内：{msg}")
        self.assertTrue(
            all(d.startswith(".fenix/fixtures") or d in
                ("fixtures", "tests/fixtures", "test/fixtures")
                for d in SCENARIO_REVISION_ALLOWED_DIRS),
            "白名单目录应限于夹具供给层",
        )


class TestRevisionBudgetFreeze(unittest.TestCase):
    """Scenario: 修订次数上限——超限拒绝并冻结转人工。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))

    def test_over_limit_rejected_and_frozen(self):
        """已达上限（默认 2）：拒绝修订 + 冻结转人工（修订出口耗尽）。"""
        engine, sm = _park(self.tmpdir)
        sm.update_spec("s1", {"_scenario_revision_count": SCENARIO_REVISION_MAX_COUNT})
        r = execute_adjudication_choice(
            Path(self.tmpdir), "s1", "revise_scenario_reverify",
            note=_revision_payload(), signal_type="inconclusive_loop",
        )
        self.assertFalse(r.get("ok"), "超限应拒绝")
        self.assertTrue(r.get("frozen_manual"), "应标记转人工冻结")
        entry = _parse_state_entry(self.tmpdir)
        self.assertTrue(entry.get("frozen"), "spec 应被冻结")
        self.assertEqual(entry.get("status"), "blocked", "冻结应转 blocked")
        self.assertIn("达上限", entry.get("error") or "",
                      "冻结原因应含修订上限语义")
        # 计数不被刷高：拒绝轮不计新次数
        self.assertEqual(int(entry.get("_scenario_revision_count") or 0),
                         SCENARIO_REVISION_MAX_COUNT)

    def test_under_limit_still_allowed(self):
        """未达上限：修订通道开放（预算前置不误拦）。"""
        engine, sm = _park(self.tmpdir)
        sm.update_spec("s1", {"_scenario_revision_count": SCENARIO_REVISION_MAX_COUNT - 1})
        r = execute_adjudication_choice(
            Path(self.tmpdir), "s1", "revise_scenario_reverify",
            note=_revision_payload(), signal_type="inconclusive_loop",
        )
        self.assertTrue(r.get("ok"), f"未达上限应放行：{r.get('error')}")
        entry = _parse_state_entry(self.tmpdir)
        self.assertEqual(int(entry.get("_scenario_revision_count") or 0),
                         SCENARIO_REVISION_MAX_COUNT)


# ── 2.3：env 归因证据门 ──────────────────────────────────────────────────


class TestEnvAttributionEvidenceGate(unittest.TestCase):
    """Scenario: env 归因结论须附送帧/解码两段证据引用，缺失降级 inconclusive。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))

    def _level2(self, scenario_extra):
        """构造单失败场景的级二判定输入并返回判定结果。"""
        engine, _, _ = _mk_engine(self.tmpdir)
        report = {
            "summary": {"total": 1, "passed": 0, "warnings": 0,
                        "failed": 1, "errors": 0, "blocked_env": 0},
            "scenarios": [dict({
                "scenario_id": "s-cam",
                "status": "failed",
                "classification": "env",
            }, **scenario_extra)],
        }
        return engine._verification._verdict_env_exemption_level2("s1", report)

    def test_media_attribution_without_evidence_downgrades(self):
        """声称解码失败却只有一句现象描述：降级 inconclusive（级二不命中）。"""
        verdict = self._level2({
            "evidence": {"first_failed_step": "推流预览"},
        })
        self.assertFalse(verdict["hit"], "缺两段证据引用不得命中级二豁免")
        self.assertEqual(len(verdict["non_env"]), 1)
        self.assertEqual(verdict["non_env"][0]["classification"], "inconclusive")

    def test_media_attribution_with_both_evidences_keeps_env(self):
        """送帧计数 + 解码输出两段证据齐备：维持 env（级二正常命中）。"""
        verdict = self._level2({
            "evidence": {
                "failed_assertions": [],
                "note": "已送帧 120 帧（frame_count=120），解码输出 0 帧",
            },
        })
        self.assertTrue(verdict["hit"], "两段证据齐备应维持 env 命中")
        self.assertEqual(verdict["env_entries"], 1)

    def test_non_media_env_attribution_unaffected(self):
        """非媒体词汇 env 归因不受证据门约束（既有车道零行为变化）。"""
        verdict = self._level2({
            "evidence": {"first_failed_step": "HTTP 探测失联，端口未监听"},
        })
        self.assertTrue(verdict["hit"], "普通 env 归因应直通命中")

    def test_gate_pure_function(self):
        """证据门纯函数：非 env 原样、媒体缺证据降级、齐备维持。"""
        from core.dashboard.data.admin_actions import (
            env_attribution_evidence_gate,
        )

        self.assertEqual(
            env_attribution_evidence_gate("product-bug", "解码失败"),
            "product-bug", "非 env 归因原样返回",
        )
        self.assertEqual(
            env_attribution_evidence_gate("env", "解码失败"),
            "inconclusive", "媒体词缺两段证据应降级",
        )
        self.assertEqual(
            env_attribution_evidence_gate("env", "已送帧 90 帧，软解无输出"),
            "env", "送帧+解码两段齐备维持 env",
        )
        self.assertEqual(
            env_attribution_evidence_gate("env", "依赖服务未启动"),
            "env", "非媒体词汇直通",
        )


# ── 2.2：豁免有效命中轮不计冻结轮次 ──────────────────────────────────────


class TestExemptionEffectiveRoundNotCounted(unittest.TestCase):
    """Scenario: 豁免有效命中的 env 阻塞轮不计入 ENV_BLOCK_FREEZE_THRESHOLD。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))

    def test_exemption_effective_round_keeps_rounds_and_unfrozen(self):
        """exemption_effective=True：轮次不递增、不冻结（豁免不滑向冻结）。"""
        from core.state_machine import ENV_BLOCK_FREEZE_THRESHOLD, ENV_BLOCK_ROUNDS_FIELD

        engine, sm, _ = _mk_engine(self.tmpdir)
        sm.update_spec("s1", {
            ENV_BLOCK_ROUNDS_FIELD: ENV_BLOCK_FREEZE_THRESHOLD - 1,
        })
        engine._verification._escalate_env_blocked(
            "s1", ["env 失败场景不得判 verified: s-1"], exemption_effective=True,
        )
        entry = sm.read_one("s1")
        self.assertEqual(int(entry.get(ENV_BLOCK_ROUNDS_FIELD) or 0),
                         ENV_BLOCK_FREEZE_THRESHOLD - 1,
                         "豁免有效命中轮不递增冻结轮次")
        self.assertFalse(entry.get("frozen"), "豁免有效命中轮不冻结")
        # 阻塞 + 自动呼叫 Administrator 仍在（env 阻塞升级语义保留）——
        # 豁免只免去「滑向冻结」，不免去「呼叫人工处置环境」
        self.assertEqual(entry.get("status"), "blocked",
                         "阻塞升级语义保留（呼叫 Administrator 处置环境）")

    def test_non_effective_round_still_counts(self):
        """exemption_effective=False（缺省）：既有计数/冻结语义不变。"""
        from core.state_machine import ENV_BLOCK_FREEZE_THRESHOLD, ENV_BLOCK_ROUNDS_FIELD

        engine, sm, _ = _mk_engine(self.tmpdir)
        sm.update_spec("s1", {
            ENV_BLOCK_ROUNDS_FIELD: ENV_BLOCK_FREEZE_THRESHOLD - 1,
        })
        engine._verification._escalate_env_blocked(
            "s1", ["env 失败场景不得判 verified: s-1"],
        )
        entry = sm.read_one("s1")
        self.assertEqual(int(entry.get(ENV_BLOCK_ROUNDS_FIELD) or 0),
                         ENV_BLOCK_FREEZE_THRESHOLD,
                         "非豁免轮照常递增")
        self.assertTrue(entry.get("frozen"), "达阈值照常冻结转人工")


if __name__ == "__main__":
    unittest.main()
