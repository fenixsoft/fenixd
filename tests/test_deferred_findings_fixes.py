"""
Deferred findings fixes tests (fix-deferred-findings SPEC).

覆盖设计 D1 逐条账目的独立验证：
- 端口并发探测（P1 性能）：并发结果与原串行结果 pre 集逐元素一致
- 截断标注 / 坏 baseline 告警（P3 健壮性）
- pm_engine 侧不 import core.dashboard.data 守卫断言（阶段 4，CYC-1）
"""
import io
import json
import re
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _make_urlopen_side_effect(ok_ports):
    """构造 urlopen side_effect：根据端口号决定 200 还是 OSError。"""
    def side_effect(request, *args, **kwargs):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        m = re.search(r"127\.0\.0\.1:(\d+)/", url)
        port = int(m.group(1)) if m else 0
        if port in ok_ports:
            return io.BytesIO(b"ok")
        raise OSError(f"Connection refused: {port}")
    return side_effect


class TestConcurrentPortProbing(unittest.TestCase):
    """阶段 2（P1 性能）：_probe_ports_responding 并发探测与原串行
    pre 端口集合语义逐元素一致。"""

    def _run_probe_comparison(self, legacy_hint, ok_ports):
        """并发探测结果与串行 {p ... if _port_responds(p)} 对比的通用框架。"""
        from core.pm_engine.verification.serving import (
            _port_responds,
            _probe_ports_responding,
        )
        se = _make_urlopen_side_effect(ok_ports)
        with patch.object(urllib.request, "urlopen", side_effect=se):
            serial = {
                p
                for p in range(legacy_hint, legacy_hint + 51)
                if _port_responds(p)
            }
            concurrent = _probe_ports_responding(range(legacy_hint, legacy_hint + 51))
        return serial, concurrent

    def test_concurrent_probe_matches_serial_pre_set(self):
        """同一端口占用场景：并发探测返回集合 == 串行 {p ... if _port_responds(p)}。"""
        ok_ports = {8000, 8015, 8033, 8049, 8050}
        serial, concurrent = self._run_probe_comparison(8000, ok_ports)
        self.assertEqual(concurrent, ok_ports)
        self.assertEqual(serial, concurrent)

    def test_concurrent_probe_no_responding_ports(self):
        """无任何端口响应时并发与串行一致返回空集。"""
        serial, concurrent = self._run_probe_comparison(5000, set())
        self.assertEqual(concurrent, set())
        self.assertEqual(serial, concurrent)

    def test_probe_all_ports_responding(self):
        """全部端口响应时并发返回完整 51 端口集合（不丢元素）。"""
        ok = set(range(9000, 9051))
        serial, concurrent = self._run_probe_comparison(9000, ok)
        self.assertEqual(concurrent, ok)
        self.assertEqual(serial, concurrent)


class _FakeContext:
    """escalation_notifier / state_machine / logger 最小替身（与 pipeline 同构）。"""

    def __init__(self):
        self.notifier_calls = []
        self.state_updates = []
        self.warnings = []
        self.errors = []
        self.project_root = str(Path(tempfile.mkdtemp()))


def _make_pipeline(ctx):
    """构造 _escalate_env_blocked 所需的 pipeline 替身。"""
    pipeline = object.__new__(type("P", (), {}))
    pipeline._context = ctx
    sm = type("SM", (), {})()

    def read_one(name):
        return {"_env_block_rounds": 0}

    def bump_counters(name, deltas):
        # 对齐真实 StateMachine.bump_counters 契约（code-review 3a39bcdb19d0
        # 起 _escalate_env_blocked 经该原语锁内原子递增计数并落盘，替代旧
        # 「快照读 +1 后随 update_spec 回写」路径）：读当前值→逐字段 int
        # 累加→返回 {field: 新值} 快照。替身缺该方法会 AttributeError 被
        # _escalate_env_blocked 函数级 except 吞掉，升级通道整体静默跳过。
        cur = dict(read_one(name) or {})
        out = {}
        for field, delta in deltas.items():
            try:
                out[field] = int(cur.get(field, 0) or 0) + int(delta)
            except (TypeError, ValueError):
                out[field] = int(delta)
        return out

    sm.read_one = read_one
    sm.bump_counters = bump_counters
    sm.update_spec = lambda name, entry: ctx.state_updates.append((name, entry))
    ctx.state_machine = sm
    ctx.logger = type("L", (), {})()

    def warn(*a):
        ctx.warnings.append(a)

    ctx.logger.warning = warn
    ctx.logger.error = lambda *a: ctx.errors.append(a)
    ctx.logger.info = lambda *a: None
    pipeline._record_infra_failure = lambda *a, **k: None
    pipeline._last_planner_run_cost = lambda spec: ""
    pipeline._context.escalation_notifier = lambda **kw: ctx.notifier_calls.append(kw)
    pipeline._context.scenario_set_fingerprint = lambda spec: ""
    return pipeline


class TestEscalationTruncationMarker(unittest.TestCase):
    """阶段 3.2：_escalate_env_blocked 的 error_msg[:300] 截断加省略号标注。"""

    def test_long_violation_message_gets_ellipsis_marker(self):
        """>300 字符的 error_msg 截断后带 '...' 标注。"""
        from core.pm_engine.verification.escalation import _escalate_env_blocked

        ctx = _FakeContext()
        pipeline = _make_pipeline(ctx)
        long_violation = "环境错误细节" + "x" * 400  # 足够长触发截断
        with patch("core.dashboard.data.request_admin_invoke", return_value={}):
            _escalate_env_blocked(pipeline, "spec-x", [long_violation])
        self.assertTrue(ctx.notifier_calls, "escalation_notifier 应被调用")
        desc = ctx.notifier_calls[0]["description"]
        self.assertEqual(len(desc), 300 + 3)
        self.assertTrue(desc.endswith("..."), f"截断应带省略号标注: {desc[-10:]!r}")

    def test_short_message_without_ellipsis(self):
        """短消息不截断、不带 '...' 标注（行为不变）。"""
        from core.pm_engine.verification.escalation import _escalate_env_blocked

        ctx = _FakeContext()
        pipeline = _make_pipeline(ctx)
        with patch("core.dashboard.data.request_admin_invoke", return_value={}):
            _escalate_env_blocked(pipeline, "spec-x", ["连接超时"])
        desc = ctx.notifier_calls[0]["description"]
        self.assertFalse(desc.endswith("..."), f"短消息不应截断: {desc!r}")
        self.assertLessEqual(len(desc), 300)


class TestBadTokenBaselineWarns(unittest.TestCase):
    """阶段 3.3：_record_verdict_adoption 对坏 _judge_token_baseline 补告警。"""

    def test_corrupt_baseline_triggers_warning(self):
        """坏 baseline（非合法 JSON）→ logger.warning，保留 fallback 行为。"""
        import core.verify_report as vr

        ctx = _FakeContext()
        pipeline = _make_pipeline(ctx)
        sm_read_one_data = {"status": "verified", "_judge_token_baseline": "not-json{"}
        # state_machine.read_one 返回坏 baseline
        pipeline._context.state_machine.read_one_data = sm_read_one_data
        pipeline._context.state_machine.read_one = lambda name: sm_read_one_data
        # token 合计返回非空（触发差量记账路径）；patch 公开别名——
        # _record_verdict_adoption 按模块边界约定消费公开名而非私有符号
        with patch.object(vr, "sum_verify_chain_tokens", return_value={"input": 10, "output": 5}), \
             patch.object(vr, "record_verdict_round", return_value=None), \
             patch.object(vr, "verdict_failed_ids", return_value=[]):
            from core.pm_engine.verification.verdict_evidence import _record_verdict_adoption

            _record_verdict_adoption(pipeline, "spec-x", "verified", report={})
        # 告警已补（不再静默 fallback）
        self.assertTrue(
            any("_judge_token_baseline" in str(w) for w in ctx.warnings),
            f"坏 baseline 应触发告警，实际 warnings={ctx.warnings}",
        )
        # 保留 fallback：差量按当前累计全额记账（prev=None → max(0, cur-0)）
        # state_updates[-2] = _judge_token_delta 更新，[-1] = verified 清零更新
        delta_entry = pipeline._context.state_updates[-2][1]
        self.assertEqual(delta_entry["_judge_token_delta"], '{"input": 10, "output": 5}')


class TestPmEngineNoDashboardDataImport(unittest.TestCase):
    """阶段 4.4（CYC-1）：pm_engine 侧（除 engine.py 转移清单外）MUST NOT
    直接 import core.dashboard.data（分层倒置守卫）。"""

    @staticmethod
    def _scan_reverse_imports():
        """扫描 core/pm_engine/ 下除 engine.py 外所有 .py 的顶部导入。"""
        import ast
        results = []
        pm_dir = Path(__file__).resolve().parent.parent / "core" / "pm_engine"
        for f in sorted(pm_dir.rglob("*.py")):
            if f.name == "engine.py":
                continue
            if "__pycache__" in str(f):
                continue
            try:
                tree = ast.parse(f.read_text(encoding="utf-8"), f.name)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "core.dashboard.data":
                            results.append((f"import {alias.name}", f))
                elif isinstance(node, ast.ImportFrom):
                    if (node.module or "") == "core.dashboard.data":
                        results.append((f"from {node.module} import ...", f))
        return results

    def test_no_direct_import_in_pm_engine_submodules(self):
        """除 engine.py 外，pm_engine 子模块 MUST NOT import core.dashboard.data。"""
        violations = self._scan_reverse_imports()
        self.assertEqual(
            violations,
            [],
            f"pm_engine 子模块发现反向 import core.dashboard.data: {violations}",
        )

    def test_signals_functions_accessible_from_pm_engine(self):
        """中性模块 core.signals 提供 request_admin_invoke 和 parse_verify_progress。"""
        from core.signals import request_admin_invoke, parse_verify_progress

        self.assertTrue(callable(request_admin_invoke))
        self.assertTrue(callable(parse_verify_progress))


if __name__ == "__main__":
    unittest.main()
