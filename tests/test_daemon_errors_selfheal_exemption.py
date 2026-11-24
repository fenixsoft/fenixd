"""test_daemon_errors_selfheal_exemption.py — 自愈签名豁免与源头聚合测试
（evo-daemon-errors-selfheal-exemption tasks 1.1/1.2/2.1/3.1）

覆盖：
- ① WIP 重叠签名重复 ERROR 不产生 critical 且日志行保留（豁免只压制升级）。
- ② 非豁免签名（新错误形态 / 同前缀不同组件）仍正常升级。
- ③ merge-back 重试窗口内重复拦截聚合：3 次拦截仅 1 条 ERROR + 2 条聚合 INFO。
- ④ 豁免命中计数可读（get_selfheal_exempt_hit_counts 审计面）。

admin_monitor 经 __new__ 直构 + 日志 fixture 驱动（对齐
test_codefix_conn_error_cooldown / test_admin_dispatch_escalation 形态）；
_wip_overlap_gate 经 __new__ 直构 + 探针 stub 驱动（零真实 git 触达）。
"""

import json
import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.pm_engine.promotion import TASKS_LINT_MSG_PREFIX  # noqa: E402

# /tmp 可能被外部清扫进程周期性清空。统一用仓库内 .history/tmp（gitignored）。
_HISTORY_TMP = Path(__file__).resolve().parent.parent / ".history" / "tmp"
_HISTORY_TMP.mkdir(parents=True, exist_ok=True)


def _mkdtemp(prefix: str) -> str:
    import tempfile
    return tempfile.mkdtemp(prefix=prefix, dir=str(_HISTORY_TMP))


WIP_BLOCK_PREFIX = (
    "Merge-back blocked by WIP overlap precheck (policy=escalate)"
)
PROMOTION_LINT_PREFIX = "Promotion lint failed"


class _RecLogger:
    """收集 info/warning/error 调用的替身 logger（按级别分桶留断言基底）。"""

    def __init__(self):
        self.infos = []
        self.warnings = []
        self.errors = []

    def info(self, component, msg, *a, **k):
        self.infos.append((component, msg))

    def warning(self, component, msg, *a, **k):
        self.warnings.append((component, msg))

    def error(self, component, msg, *a, **k):
        self.errors.append((component, msg))


def _make_monitor(tmp_path):
    """__new__ 直构 AdminMonitor（对齐既有 daemon_errors 测试形态）。"""
    from core.admin_monitor import AdminMonitor
    from core.admin_store import AdminStore

    mon = AdminMonitor.__new__(AdminMonitor)
    mon.project_root = Path(tmp_path)
    mon.logger = _RecLogger()
    mon.store = AdminStore(Path(tmp_path), None)
    # _started_at 拨远：关闭重启冷却窗（长驻 daemon 常态），豁免分支直判
    mon._started_at = time.time() - 24 * 3600
    mon._daemon_fp_escalated_at = {}
    mon._daemon_fp_last_failure = {}
    return mon


def _write_error_log(tmp_path, entries):
    """写入 fenixd.log 形态的单行 JSON ERROR 序列（[(component, msg, ts)]）。"""
    log = Path(tmp_path) / ".fenix" / "logs" / "fenixd.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for component, msg, ts in entries:
        lines.append(json.dumps({
            "level": "ERROR",
            "timestamp": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
            "component": component,
            "message": msg,
        }, ensure_ascii=False))
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return log


class TestSelfHealSignatureExemption(unittest.TestCase):
    """daemon_errors 自愈签名豁免（spec R1/R3，tasks 1.1/1.2）。"""

    def test_1_wip_overlap_repeat_errors_exempted_and_log_kept(self):
        """①WIP 重叠签名窗口内复现 2 次：不升级、ERROR 日志行原样保留。"""
        now = time.time()
        msg = (
            f"{WIP_BLOCK_PREFIX}: 2 main-tree tracked file(s) with uncommitted "
            "changes overlap branch 'fenix/x-123' changes: ['a.py']. 处置：提交或 stash"
        )
        tmp = Path(_mkdtemp("selfheal-wip-"))
        _write_error_log(tmp, [
            ("worktree_manager", msg, now - 120),
            ("worktree_manager", msg, now - 25),
        ])
        mon = _make_monitor(tmp)

        signals = mon._detect_daemon_errors(now)

        self.assertEqual(signals, [], "豁免签名重复 ERROR MUST 跳过 critical 升级")
        # 1.2：日志行原样保留（豁免不删/不改写 daemon 日志）
        raw = (tmp / ".fenix" / "logs" / "fenixd.log").read_text(encoding="utf-8")
        self.assertEqual(raw.count('"level": "ERROR"'), 2, "ERROR 日志行 MUST 保留")
        self.assertEqual(raw.count(WIP_BLOCK_PREFIX), 2)
        # 升级面零产出：无 critical 文案经 logger 落痕
        self.assertFalse(mon.logger.errors)

    def test_2_non_exempt_new_signature_still_escalates(self):
        """②非豁免签名（构造新错误形态）窗口内复现 2 次：照常升级 critical。"""
        now = time.time()
        msg = "unrecognized_model provider=glm request_id=~ stream aborted"
        tmp = Path(_mkdtemp("selfheal-new-"))
        _write_error_log(tmp, [
            ("agent_runner", msg, now - 60),
            ("agent_runner", msg, now - 30),
        ])
        mon = _make_monitor(tmp)

        signals = mon._detect_daemon_errors(now)

        self.assertEqual(len(signals), 1, "非豁免签名 MUST 照常升级")
        sig = signals[0]
        self.assertEqual(sig["signal_type"], "daemon_errors")
        self.assertIn("建议检查根因并重启 daemon", sig["description"])
        for _c, m in mon.logger.infos:
            self.assertNotIn("自愈签名豁免", m, "非豁免指纹 MUST NOT 落豁免留痕")

    def test_2b_same_prefix_wrong_component_still_escalates(self):
        """②b 同前缀异组件（component 等值失配）：不命中豁免，照常升级。"""
        now = time.time()
        msg = f"{WIP_BLOCK_PREFIX}: overlap ['a.py']"
        tmp = Path(_mkdtemp("selfheal-comp-"))
        _write_error_log(tmp, [
            ("pm_engine", msg, now - 60),
            ("pm_engine", msg, now - 30),
        ])
        mon = _make_monitor(tmp)

        signals = mon._detect_daemon_errors(now)

        self.assertEqual(
            len(signals), 1,
            "组件不匹配（worktree_manager 之外）MUST NOT 享受豁免",
        )

    def test_2c_promotion_lint_signature_exempted(self):
        """②c promotion lint 签名（注册表第 2 条）：重复 ERROR 同样豁免。"""
        now = time.time()
        msg = f"{PROMOTION_LINT_PREFIX} 'spec-x': {TASKS_LINT_MSG_PREFIX}"
        tmp = Path(_mkdtemp("selfheal-plint-"))
        _write_error_log(tmp, [
            ("pm_engine", msg, now - 64),
            ("pm_engine", msg, now - 63),
        ])
        mon = _make_monitor(tmp)

        signals = mon._detect_daemon_errors(now)

        self.assertEqual(signals, [], "promotion lint 签名 MUST 豁免升级")
        self.assertTrue(
            any("promotion-lint-failed" in m for _c, m in mon.logger.infos),
            "豁免命中 MUST 落 INFO 留痕（含签名名）",
        )

    def test_4_exempt_hit_counter_readable(self):
        """④豁免命中计数可读：审计面按签名累计命中次数。"""
        now = time.time()
        wip_msg = f"{WIP_BLOCK_PREFIX}: overlap ['a.py']"
        lint_msg = f"{PROMOTION_LINT_PREFIX} 'spec-y': err"
        tmp = Path(_mkdtemp("selfheal-count-"))
        _write_error_log(tmp, [
            ("worktree_manager", wip_msg, now - 120),
            ("worktree_manager", wip_msg, now - 100),
            ("pm_engine", lint_msg, now - 60),
            ("pm_engine", lint_msg, now - 50),
        ])
        mon = _make_monitor(tmp)
        self.assertEqual(mon.get_selfheal_exempt_hit_counts(), {})

        mon._detect_daemon_errors(now)

        counts = mon.get_selfheal_exempt_hit_counts()
        # 命中语义 = 指纹级豁免决策（逐指纹循环内 append 前判定，每检测轮每
        # 指纹至多 +1），非按日志条数——窗口内 2 条同签名 ERROR 聚合为该指纹
        # 的一次豁免决策
        self.assertEqual(
            counts.get("wip-overlap-precheck-escalate"), 1,
            "WIP 签名该指纹本轮豁免决策计 1 次",
        )
        self.assertEqual(counts.get("promotion-lint-failed"), 1)
        # 只读副本：外部改写不回灌实例计数器
        counts["wip-overlap-precheck-escalate"] = 999
        self.assertEqual(
            mon.get_selfheal_exempt_hit_counts().get("wip-overlap-precheck-escalate"),
            1,
        )


class _GateStubManager:
    """_wip_overlap_gate 探针宿主：最小协作面 stub（零真实 git 触达）。"""

    def __init__(self, logger):
        self.logger = logger
        self.project_root = Path(_mkdtemp("selfheal-gate-"))
        self._wip_gate_aligned_artifacts = []

    # 探针协作面
    def _maybe_signal_build_artifact_paths_missing(self, branch):
        return None

    def _merge_precheck_bypass_enabled(self):
        return False

    def _detect_wip_overlap(self, branch):
        return ["docs/a.md"]

    def _wip_gate_policy(self):
        return "escalate"

    @property
    def _artifacts(self):
        class _A:
            @staticmethod
            def paths_in(overlap):
                return []

            @staticmethod
            def non_artifacts_in(overlap):
                return list(overlap)

        return _A()


class TestMergebackRetryCoalescing(unittest.TestCase):
    """merge-back 重试窗口内重复拦截聚合（spec R2，task 2.1）。"""

    def _gate(self):
        logger = _RecLogger()
        return _GateStubManager(logger), logger

    def test_3_three_interceptions_one_error_two_coalesced_infos(self):
        """③同次合回重试 3 次拦截：仅 1 条 ERROR + 2 条聚合 INFO。"""
        from core.worktree_manager.mergeback import G4MergebackMixin

        mgr, logger = self._gate()
        first_at = time.time() - 300
        gate = G4MergebackMixin._wip_overlap_gate

        r0 = gate(mgr, "fenix/x-123")
        r1 = gate(
            mgr, "fenix/x-123",
            merge_retry_count=1, merge_retry_first_at=first_at,
        )
        r2 = gate(
            mgr, "fenix/x-123",
            merge_retry_count=2, merge_retry_first_at=first_at,
        )

        # 拦截判定行为不变（3 次全部 wip_gate_blocked=True）
        for r in (r0, r1, r2):
            blocked, overlap = r
            self.assertIsNotNone(blocked)
            self.assertTrue(getattr(blocked, "wip_gate_blocked", False))
            self.assertEqual(overlap, ["docs/a.md"])
        # 日志分级：首条 ERROR（首阻取证）+ 2 条聚合 INFO
        self.assertEqual(len(logger.errors), 1, "首阻 MUST 保持 1 条 ERROR")
        self.assertIn(WIP_BLOCK_PREFIX, logger.errors[0][1])
        self.assertEqual(
            len(logger.infos), 2, "重试序号>0 的重复拦截 MUST 降级聚合 INFO",
        )
        self.assertIn("retry=1", logger.infos[0][1])
        self.assertIn("距首阻", logger.infos[0][1])
        self.assertIn("retry=2", logger.infos[1][1])
        # 聚合行保留完整拦截文案（grep 原前缀仍可检索）
        self.assertIn(WIP_BLOCK_PREFIX, logger.infos[0][1])

    def test_3b_missing_accounting_defaults_to_error(self):
        """③b 记账缺字段（0/None）= 首阻形态：保持 ERROR 落行。"""
        from core.worktree_manager.mergeback import G4MergebackMixin

        mgr, logger = self._gate()
        gate = G4MergebackMixin._wip_overlap_gate
        gate(mgr, "fenix/x-123", merge_retry_count=0)
        gate(mgr, "fenix/x-123", merge_retry_count=0, merge_retry_first_at=None)
        self.assertEqual(len(logger.errors), 2)
        self.assertFalse(logger.infos)


if __name__ == "__main__":
    unittest.main()
