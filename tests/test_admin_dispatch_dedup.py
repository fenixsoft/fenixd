"""daemon 级信号 spec 归属提取与派发去重测试（evo-add-daemon-signal-spec-attribution-dedup）。

背景：同源阻塞事件同时产生 spec 级信号（mergeback_wip_overlap 等）与 daemon 级
同指纹升级信号（daemon_errors），派发器 1:1 双派 administrator run 重复诊断
（实证两例：同秒双派 412.8s+449.9s；3117s 与 3831s 量级双开）。本能力让
daemon 级信号在派发判定前按 evidence 的 ERROR 原文摘录提取 spec 归属，与在飞
admin run 互查，命中即跳过（信号保持未消费、附「被在飞 run 覆盖、待重评」
注记），在飞 run 终态后自然重评；提取不到归属时行为与现状完全一致。

覆盖：
- 2.1 evidence 基底与归属提取（摘录附入/前缀不变/双线索/无线索兜底/不改写字段）
- 2.2 互查跳过与在飞 run 终态后重评
- 2.3 行为不变回归（无归属照常派发 / 合并与 spec 键互斥不回归 / _fp 稳定拼接）
"""

import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.admin_store import AdminStore, DISPOSITION
from core.admin_monitor import (
    AdminMonitor,
    DAEMON_SIGNAL_COVERED_NOTE,
    _error_fingerprint,
    _extract_spec_attribution_from_text,
    _format_error_excerpt,
)
from core.state_machine import StateMachine


class CapturingLogger:
    """记录 warning/info 文本，供断言使用。"""

    def __init__(self):
        self.warnings = []
        self.infos = []

    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        msg = a[1] if len(a) > 1 else (a[0] if a else "")
        if isinstance(msg, str):
            self.infos.append(msg)

    def warning(self, *a, **k):
        msg = a[1] if len(a) > 1 else (a[0] if a else "")
        if isinstance(msg, str):
            self.warnings.append(msg)

    def error(self, *a, **k):
        pass


def _make_monitor(tmp_path, store=None, specs=None):
    """最小上下文 AdminMonitor（__new__ 直构，同 TestBlockedStuckFrozenExemption 形态）。"""
    mon = AdminMonitor.__new__(AdminMonitor)
    mon.admin_cfg = {"escalation_cooldown_minutes": 0}
    mon.logger = CapturingLogger()
    mon.project_root = Path(tmp_path)
    mon.state_machine = MagicMock()
    mon.state_machine.read_all.return_value = dict(specs or {})
    mon.store = store if store is not None else MagicMock()
    mon.agent_runner = MagicMock()
    # _invoke_administrator 现经该 executor 投递后台执行（None → 同步回退）
    mon._code_review_executor = None
    mon._daemon_fp_escalated_at = {}
    mon._daemon_fp_last_failure = {}
    return mon


def _iso_now():
    return datetime.now(timezone.utc).isoformat()


def _write_error_log(tmp_path, entries):
    """写 .fenix/logs/fenixd.log：entries = [(component, message, iso_ts)]。"""
    log_dir = Path(tmp_path) / ".fenix" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            {
                "timestamp": ts,
                "level": "ERROR",
                "component": component,
                "message": message,
            },
            ensure_ascii=False,
        )
        for component, message, ts in entries
    ]
    (log_dir / "fenixd.log").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


BRANCH_MSG = (
    "Run fenix/pack2-live-stream-player-1791608995 failed: exit code 1"
)


class TestEvidenceExcerptAndAttribution:
    """2.1：evidence 基底（ERROR 原文摘录）与 spec 归属提取。"""

    def test_detect_attaches_excerpt_and_keeps_description_prefix(self, tmp_path):
        """升级信号 evidence 含最近一次同指纹 ERROR 原文摘录，description 前缀不变。"""
        now = _iso_now()
        _write_error_log(tmp_path, [("fenixd", BRANCH_MSG, now),
                                    ("fenixd", BRANCH_MSG, now)])
        mon = _make_monitor(tmp_path)
        signals = mon._detect_daemon_errors(time.time())

        assert len(signals) == 1
        sig = signals[0]
        assert sig["signal_type"] == "daemon_errors"
        assert sig["spec"] is None
        fp = _error_fingerprint("fenixd", BRANCH_MSG)
        assert sig["_fp"] == fp
        # description 仍以「指纹 <fp[:8]>」前缀子串开头（跨重启已知指纹对账依赖）
        assert sig["description"].startswith("fenixd 日志同错误（指纹 ")
        assert f"指纹 {fp[:8]}" in sig["description"]
        # evidence 含最近一次 ERROR 原文摘录（含组件名），分支名线索原样保留
        excerpt = _format_error_excerpt("fenixd", BRANCH_MSG)
        assert f"最近一次 ERROR 原文摘录：{excerpt}" in sig["evidence"]
        assert "fenixd" in excerpt
        assert "fenix/pack2-live-stream-player-1791608995" in sig["evidence"]
        # 归属提取端到端：分支名线索 → spec 归属
        assert mon._extract_daemon_signal_spec(sig) == "pack2-live-stream-player"

    def test_merged_signal_attaches_per_fp_excerpt(self, tmp_path):
        """同轮多指纹合并信号：逐指纹摘要与逐指纹摘录并存，_fp 稳定拼接不变。"""
        mon = _make_monitor(tmp_path)
        fp1 = _error_fingerprint("comp_a", "boom alpha")
        fp2 = _error_fingerprint("comp_b", "boom beta")
        ex1 = _format_error_excerpt("comp_a", "分支 fenix/foo-bar-1791608995 挂了")
        ex2 = _format_error_excerpt("comp_b", "普通错误无线索")
        sig = mon._make_daemon_error_signal_merged(
            [(fp1, 2, "t1", 0, None, ex1), (fp2, 3, "t2", 0, None, ex2)]
        )
        assert f"指纹 {fp1[:8]} 复现 2 次" in sig["evidence"]
        assert f"指纹 {fp2[:8]} 复现 3 次" in sig["evidence"]
        assert f"最近一次 ERROR 原文摘录：{ex1}" in sig["evidence"]
        assert f"最近一次 ERROR 原文摘录：{ex2}" in sig["evidence"]
        assert sig["_fp"] == "|".join(sorted([fp1, fp2]))
        assert f"指纹 {fp1[:8]}" in sig["description"]
        assert f"指纹 {fp2[:8]}" in sig["description"]
        # 合并信号 evidence 携带分支线索时同样可归属
        assert mon._extract_daemon_signal_spec(sig) == "foo-bar"

    def test_single_builder_legacy_shape_and_excerpt(self, tmp_path):
        """存量直构形态（不传 excerpt）不追加摘录子串；传参时附入且 description 不变。"""
        mon = _make_monitor(tmp_path)
        fp = "a" * 40
        legacy = mon._make_daemon_error_signal(fp, 2, "t", 0)
        assert "最近一次 ERROR 原文摘录" not in legacy["evidence"]
        assert legacy["_fp"] == fp
        with_ex = mon._make_daemon_error_signal(fp, 2, "t", 0, None, "[c] msg")
        assert "最近一次 ERROR 原文摘录：[c] msg" in with_ex["evidence"]
        assert with_ex["_fp"] == fp
        assert with_ex["description"] == legacy["description"]

    def test_extract_branch_clue_variants(self):
        """分支名 fenix/<spec>-<时间戳> 正则线索：常规/内嵌数字段/紧邻标点均命中。"""
        f = _extract_spec_attribution_from_text
        assert (
            f("ERROR: run fenix/pack2-live-stream-player-1791608995 failed")
            == "pack2-live-stream-player"
        )
        assert f("worktree fenix/evo-add-x-1791658313 crashed") == "evo-add-x"
        # spec 名内嵌数字段不误截（非贪婪回溯到末段纯数字之前）
        assert f("fenix/foo2bar-1791608995 boom") == "foo2bar"
        assert f("（fenix/spec-x-1791608995）") == "spec-x"
        # 无线索/空文本 → 空归属
        assert f("没有线索的普通错误文本") == ""
        assert f("") == ""
        assert f(None) == ""

    def test_extract_direct_name_clue_longest_first(self):
        """spec 名直接匹配线索：长名优先，短名前缀不抢先归属。"""
        known = ["foo", "foo-bar-baz"]
        assert (
            _extract_spec_attribution_from_text(
                "见 spec/changes/foo-bar-baz/proposal.md 失败", known
            )
            == "foo-bar-baz"
        )

    def test_extract_method_whitelist_and_no_mutation(self, tmp_path):
        """提取只读不改写信号字段；白名单外 None-spec 类型不套用；有 spec 原样返回。"""
        mon = _make_monitor(tmp_path, specs={"foo-bar": {"status": "ready"}})
        sig = {
            "signal_type": "daemon_errors",
            "spec": None,
            "evidence": "原文摘录：[fenixd] fenix/foo-bar-1791608995 failed",
            "description": "d",
            "severity": "critical",
            "_fp": "x",
        }
        before = dict(sig)
        assert mon._extract_daemon_signal_spec(sig) == "foo-bar"
        assert sig == before, "提取逻辑 MUST NOT 改写信号其余字段"
        # 白名单外（无检测循环重发生命周期）的 None-spec 类型不归属
        other = dict(sig, signal_type="maintree_stray_wip_stale")
        assert mon._extract_daemon_signal_spec(other) == ""
        # 有 spec 的信号原样返回自身 spec（互斥口径不变）
        specd = dict(sig, spec="sp-own")
        assert mon._extract_daemon_signal_spec(specd) == "sp-own"

    def test_extract_legacy_evidence_without_excerpt_empty(self, tmp_path):
        """evidence 无摘录的存量形态 → 空归属，兜底与现状一致。"""
        mon = _make_monitor(tmp_path)
        sig = mon._make_daemon_error_signal("a" * 40, 2, "t", 0)
        assert mon._extract_daemon_signal_spec(sig) == ""

    def test_format_error_excerpt_folds_and_truncates(self):
        """摘录含组件名、折叠空白、截断限长。"""
        out = _format_error_excerpt("admin_monitor", "line1\nline2   spaced\tend")
        assert out == "[admin_monitor] line1 line2 spaced end"
        long = _format_error_excerpt("c", "x" * 1000)
        assert len(long) <= 301
        assert long.endswith("…") and long.startswith("[c] ")
        assert _format_error_excerpt(None, "") == "[unknown]"


def _daemon_signal(fp: str, excerpt_msg: str = BRANCH_MSG) -> dict:
    """daemon_errors 升级信号（evidence 携带分支名线索的原文摘录）。"""
    return {
        "signal_type": "daemon_errors",
        "spec": None,
        "severity": "critical",
        "description": (
            f"fenixd 日志同错误（指纹 {fp[:8]}）在 10 分钟窗口内复现 2 次，"
            "建议检查根因并重启 daemon"
        ),
        "evidence": (
            "同指纹 ERROR 复现 2 次（最近一次 t）；升级条件：…；"
            f"最近一次 ERROR 原文摘录：{_format_error_excerpt('fenixd', excerpt_msg)}"
        ),
        "_fp": fp,
    }


class TestMutexSkipByAttribution:
    """2.2：归属 spec 有在飞 admin run 时跳过派发；终态后自然重评。"""

    SPEC = "pack2-live-stream-player"

    def _setup(self, tmp_path):
        (tmp_path / ".fenix").mkdir(parents=True, exist_ok=True)
        logger = CapturingLogger()
        store = AdminStore(tmp_path, logger=logger)
        sm = StateMachine(tmp_path / ".fenix" / "STATE.md", logger)
        sm.add_spec(self.SPEC, {"priority": 5})
        mon = AdminMonitor.__new__(AdminMonitor)
        mon.admin_cfg = {"escalation_cooldown_minutes": 0}
        mon.logger = logger
        mon.project_root = Path(tmp_path)
        mon.state_machine = sm
        mon.store = store
        mon.agent_runner = MagicMock()
        mon._code_review_executor = None
        mon._invoke_administrator = MagicMock()
        mon._daemon_fp_escalated_at = {}
        mon._daemon_fp_last_failure = {}
        return mon, store

    def _pending_run(self):
        return {
            "kind": DISPOSITION,
            "signal_type": "manual-intervention",
            "spec": self.SPEC,
            "admin_run_id": "admin-pack2-1",
            "status": "pending",
        }

    def test_skip_when_attributed_spec_has_active_run(self, tmp_path):
        """归属 spec 有在飞 run：跳过、不派发、信号未 handled、注记含「待重评」。"""
        mon, store = self._setup(tmp_path)
        fp = _error_fingerprint("fenixd", BRANCH_MSG)
        store.append(self._pending_run())

        delivered = mon._handle_signal(_daemon_signal(fp))

        assert not delivered, "互查命中必须跳过（未送达）"
        mon._invoke_administrator.assert_not_called()
        # 信号保持未消费：store 无任何 handled 记录
        assert all(
            not rec.get("handled") for rec in store.read_all()
        ), "跳过路径不得 mark handled"
        # 注记：result="skipped" 处置留痕，含「待重评」，spec 记归属 spec
        skipped = [
            r
            for r in store.read_all()
            if r.get("kind") == DISPOSITION and r.get("result") == "skipped"
        ]
        assert len(skipped) == 1
        assert "待重评" in skipped[0]["action_taken"]
        assert DAEMON_SIGNAL_COVERED_NOTE in skipped[0]["action_taken"]
        assert skipped[0]["spec"] == self.SPEC
        assert skipped[0]["signal_type"] == "daemon_errors"
        assert "归属" in " ".join(mon.logger.warnings)

    def test_reevaluation_after_active_run_terminal(self, tmp_path):
        """在飞 run 终态后：信号重新进入派发判定并被唤起。"""
        mon, store = self._setup(tmp_path)
        fp = _error_fingerprint("fenixd", BRANCH_MSG)
        store.append(self._pending_run())

        assert not mon._handle_signal(_daemon_signal(fp))
        mon._invoke_administrator.assert_not_called()

        # 在飞 run 达终态（pending → done）
        store.append(dict(self._pending_run(), status="done"))

        delivered = mon._handle_signal(_daemon_signal(fp))
        assert bool(delivered) is True, "在飞 run 终态后信号须可重新进入派发判定"
        mon._invoke_administrator.assert_called_once()

    def test_no_active_run_dispatches_normally(self, tmp_path):
        """归属 spec 无在飞 run：照常 1:1 派发（兜底现状）。"""
        mon, store = self._setup(tmp_path)
        fp = _error_fingerprint("fenixd", BRANCH_MSG)

        delivered = mon._handle_signal(_daemon_signal(fp))

        assert bool(delivered) is True
        mon._invoke_administrator.assert_called_once()
        skipped = [
            r
            for r in store.read_all()
            if r.get("kind") == DISPOSITION and r.get("result") == "skipped"
        ]
        assert skipped == []


class TestBehaviorUnchanged:
    """2.3：行为不变回归——无归属照常派发；合并与 spec 键互斥语义不回归。"""

    def _mock_throttle_pass(self, mon):
        mon.store.latest_signal.return_value = None
        mon.store.unhandled_for.return_value = None
        mon.store.merge_signal.return_value = (MagicMock(), True)
        disp = MagicMock()
        disp.spec = None
        mon.agent_runner.run_administrator.return_value = disp

    def test_no_attribution_dispatches_as_before(self, tmp_path):
        """无归属信号照常派发（检测/提取路径不改变派发行为）。"""
        mon = _make_monitor(tmp_path)
        self._mock_throttle_pass(mon)
        fp = _error_fingerprint("fenixd", "普通错误无线索 exit 1")
        sig = _daemon_signal(fp, excerpt_msg="普通错误无线索 exit 1")

        assert bool(mon._handle_signal(sig)) is True
        mon.agent_runner.run_administrator.assert_called_once()

    def test_merged_signal_dispatches_single_run(self, tmp_path):
        """同轮多指纹合并信号：仍是一条召唤信号、一次 Administrator run。"""
        mon = _make_monitor(tmp_path)
        self._mock_throttle_pass(mon)
        fp1 = _error_fingerprint("comp_a", "boom alpha")
        fp2 = _error_fingerprint("comp_b", "boom beta")
        sig = mon._make_daemon_error_signal_merged(
            [(fp1, 2, "t1", 0, None, ""), (fp2, 3, "t2", 0, None, "")]
        )

        assert bool(mon._handle_signal(sig)) is True
        mon.agent_runner.run_administrator.assert_called_once()

    def test_merged_fp_stable_concat_hash(self, tmp_path):
        """合并信号 _fp = 排序后稳定拼接，与指纹首现顺序无关；status_hash 判据不变。"""
        mon = _make_monitor(tmp_path)
        fps = [
            _error_fingerprint("comp_a", "boom alpha"),
            _error_fingerprint("comp_b", "boom beta"),
            _error_fingerprint("comp_c", "boom gamma"),
        ]
        s1 = mon._make_daemon_error_signal_merged(
            [(f, 2, "t", 0, None, "") for f in fps]
        )
        s2 = mon._make_daemon_error_signal_merged(
            [(f, 2, "t", 0, None, "") for f in reversed(fps)]
        )
        expect = "|".join(sorted(fps))
        assert s1["_fp"] == s2["_fp"] == expect
        assert mon._signal_status_hash(s1) == mon._signal_status_hash(s2)
        assert mon._signal_status_hash(s1) == hashlib.sha1(
            f"daemon:daemon_errors\x00{expect}".encode("utf-8")
        ).hexdigest()

    def test_spec_key_mutex_legacy_text_unchanged(self, tmp_path):
        """既有 D2b spec 键互斥：日志/留痕文案与字段逐字保留（重构不回归）。"""
        mon = _make_monitor(tmp_path)
        self._mock_throttle_pass(mon)
        mon.state_machine.read_one.return_value = {"status": "blocked"}
        mon._has_active_admin_run_for_spec = MagicMock(return_value=True)
        sig = {
            "signal_type": "blocked_stuck",
            "spec": "sp-a",
            "severity": "major",
            "description": "blocked 滞留",
        }

        assert not mon._handle_signal(sig)
        mon.agent_runner.run_administrator.assert_not_called()
        assert mon._has_active_admin_run_for_spec.call_args.args[0] == "sp-a"
        appended = [
            c.args[0] for c in mon.store.append.call_args_list if c.args
        ]
        skipped = [a for a in appended if a.get("result") == "skipped"]
        assert len(skipped) == 1
        assert skipped[0]["spec"] == "sp-a"
        assert "已有在飞 admin run，跳过重复唤起" in skipped[0]["action_taken"]

    def test_specd_signal_not_skipped_by_other_spec_inflight(self, tmp_path):
        """有 spec 信号只按自身 spec 互斥（归属提取不外溢）：他 spec 在飞不拦截。"""
        mon = _make_monitor(tmp_path)
        self._mock_throttle_pass(mon)
        mon.state_machine.read_one.return_value = {"status": "blocked"}
        mon._has_active_admin_run_for_spec = MagicMock(return_value=False)
        sig = {
            "signal_type": "blocked_stuck",
            "spec": "sp-a",
            "severity": "major",
            "description": "blocked 滞留",
            # evidence 即便携带他 spec 分支线索也不参与有 spec 信号的互斥口径
            "evidence": "fenix/sp-b-1791608995 in flight",
        }

        assert bool(mon._handle_signal(sig)) is True
        mon.agent_runner.run_administrator.assert_called_once()
        mon._has_active_admin_run_for_spec.assert_called_once_with("sp-a")

    def test_non_attributable_none_spec_type_not_extracted(self, tmp_path):
        """白名单外 None-spec 信号类型不套用归属互斥（跳过语义限定）。"""
        mon = _make_monitor(tmp_path)
        self._mock_throttle_pass(mon)
        mon._has_active_admin_run_for_spec = MagicMock(return_value=True)
        sig = {
            "signal_type": "maintree_stray_wip_stale",
            "spec": None,
            "severity": "major",
            "description": "项目级盘点信号",
            "evidence": "fenix/sp-x-1791608995 stray",
        }

        # 归属提取不生效 → _mutex_spec 为空 → 不进互斥分支，照常派发
        assert bool(mon._handle_signal(sig)) is True
        mon._has_active_admin_run_for_spec.assert_not_called()


if __name__ == "__main__":
    import unittest

    unittest.main()
