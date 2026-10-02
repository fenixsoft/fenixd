"""test_codefix_conn_error_cooldown.py — code-fix 连接类失败冷却车道测试
（evo-add-codefix-conn-error-cooldown tasks 4.1/4.2/4.3）

覆盖：
- 4.1: 分类判据——ENOTFOUND 文本命中、单轮超时文本不误判、成功信封
  （exit 0）与 stderr 定噪行均不触发；共享词表不被扩充；CodeFixResult
  信封透传（conn_error/result_text）。
- 4.2: 冷却闸门——冷却内置态后 checkpoint 拒投递（含手动 override 路径）、
  到期恢复投递、配置覆盖与非法值回退、持久化读回（新实例=重启后仍拦）。
- 4.3: 告警与跨日指纹——SIGNAL 告警字段断言、24h±5 分钟命中升级（绕过
  已知指纹 30 分钟冷却）、10 分钟内同指纹不重复升级。

MUST NOT 真跑 agent——编排器经最小替身/守卫早退路径驱动，admin_monitor
经 __new__ 直构 + 日志 fixture 驱动。
"""

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# /tmp 可能被外部清扫进程周期性清空。统一用仓库内 .history/tmp（gitignored）。
_HISTORY_TMP = Path(__file__).resolve().parent.parent / ".history" / "tmp"
_HISTORY_TMP.mkdir(parents=True, exist_ok=True)


def _mkdtemp(prefix: str) -> str:
    return tempfile.mkdtemp(prefix=prefix, dir=str(_HISTORY_TMP))


class _FakeLogger:
    def __getattr__(self, name):
        return lambda *a, **k: None


def _make_project_root() -> Path:
    td = Path(_mkdtemp("cfixcd-"))
    (td / ".fenix" / "code-review").mkdir(parents=True, exist_ok=True)
    return td


def _write_items(project_root, records):
    path = Path(project_root) / ".fenix" / "code-review" / "items.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(
        json.dumps(records[k], ensure_ascii=False) + "\n" for k in sorted(records)
    )
    path.write_text(content, encoding="utf-8")


def _item(item_id, status="open"):
    return {"item_id": item_id, "status": status,
            "file": f"{item_id}/{item_id}.py", "line": 1, "severity": "major",
            "category": "correctness", "title": f"title {item_id}",
            "description": f"desc {item_id}", "suggestion": f"sug {item_id}",
            "fingerprint": f"fp-{item_id}"}


def _write_verify_yaml(proot: Path):
    body = (
        "prepare:\n  - run: 'true'\n"
        "serve:\n  kind: static\n  root: site\n"
        "ready:\n  url: /\n  expect: 200\n"
        "regression:\n"
        "  cmd: \"true\"\n"
        "  output: \".fenix/regression/junit.xml\"\n"
    )
    (proot / ".fenix" / "verify.yaml").write_text(body, encoding="utf-8")


_CFG_ON = {"admin": {"code_review_fix": {"enabled": True, "batch_size": 20}}}

_ENOTFOUND_TEXT = "API Error: Can't reach the API server (ENOTFOUND)"


class _GateRunner:
    """最小 runner 替身：仅承载 checkpoint 守卫链所需的属性。

    worktree_manager=None：守卫放行后批 worker 走 worktree_manager_missing
    halt 早退——本文件只断言 checkpoint 返回值与告警/进度面，不跑批链。
    """

    def __init__(self, project_root, config=None):
        self.project_root = Path(project_root)
        self.logger = _FakeLogger()
        self._running_agents = {}
        self.worktree_manager = None
        self.config = dict(config or {})


def _conn_error_exc(**extra):
    """携带连接类签名的 _run_claude 失败异常（runner 挂载层产物的信封形态）。"""
    e = RuntimeError(f"claude CLI failed: {_ENOTFOUND_TEXT}")
    e.conn_error = True
    e.api_timeout = True  # api_error 是 api_timeout 宽判分支：两布尔可同时为真
    e.exit_code = 1
    e.stderr_lines = ["[claude-code:unrecognized_model] Invalid model name"]
    e.result_text = _ENOTFOUND_TEXT
    for k, v in extra.items():
        setattr(e, k, v)
    return e


# ── 4.1 分类判据 ────────────────────────────────────────────────────


class TestConnErrorClassification(unittest.TestCase):
    """连接类 api_error 三判据（spec R1）：词表命中 / 超时不误判 / 成功不触发。"""

    def test_enotfound_text_hits(self):
        """实测死因文本命中：ENOTFOUND + Can't reach the API server。"""
        from core.agent_runner.provider_circuit import (
            is_code_fix_conn_error,
            match_code_fix_conn_error_text,
        )

        self.assertTrue(match_code_fix_conn_error_text(_ENOTFOUND_TEXT))
        self.assertTrue(match_code_fix_conn_error_text(
            "enotfound: getaddrinfo failed"))  # 大小写无关
        self.assertTrue(is_code_fix_conn_error(
            {"terminal_reason": "api_error", "result": _ENOTFOUND_TEXT}, 1))

    def test_timeout_text_not_misjudged(self):
        """单轮 API 超时文本（terminal_reason=api_error 同落宽判）不判连接类。"""
        from core.agent_runner.provider_circuit import is_code_fix_conn_error
        from core.agent_runner.runner import API_TIMEOUT_RESULT_TEXT

        result = {"terminal_reason": "api_error",
                  "result": f"API Error: {API_TIMEOUT_RESULT_TEXT}"}
        self.assertFalse(is_code_fix_conn_error(result, 1),
                         "Request timed out 无连接类签名，MUST NOT 误判（scenario 2）")

    def test_success_envelope_not_triggered(self):
        """成功信封（exit 0）恒不触发：exit_code!=0 是必要判据。"""
        from core.agent_runner.provider_circuit import is_code_fix_conn_error

        result = {"terminal_reason": "api_error", "result": _ENOTFOUND_TEXT}
        self.assertFalse(is_code_fix_conn_error(result, 0))
        self.assertFalse(is_code_fix_conn_error(result, None))
        # 成功 run 的 result_text 不带连接类签名 → 词表本身也不命中
        self.assertFalse(is_code_fix_conn_error(
            {"terminal_reason": "", "result": "done"}, 0))

    def test_stderr_noise_line_not_triggered(self):
        """stderr unrecognized_model 定噪行不构成判据（词表只匹配 result 文本）。"""
        from core.agent_runner.provider_circuit import (
            CLI_STDERR_NOISE_TEXT_PATTERNS,
            is_cli_stderr_noise,
            is_code_fix_conn_error,
            match_code_fix_conn_error_text,
        )

        noise = "[claude-code:unrecognized_model] Invalid model name"
        self.assertTrue(is_cli_stderr_noise(noise), "定噪行先例判别须仍成立")
        self.assertFalse(match_code_fix_conn_error_text(noise),
                         "定噪行 MUST NOT 被车道本地词表命中")
        # result 文本无连接类签名 → 即使 stderr 有定噪也判 False（判据不读 stderr）
        self.assertFalse(is_code_fix_conn_error(
            {"terminal_reason": "api_error", "result": "some other failure"}, 1))
        # 词表常量 MUST NOT 收入 unrecognized_model 形态
        for pat in (
            __import__("core.agent_runner.provider_circuit", fromlist=["x"])
            .CODE_FIX_CONN_ERROR_PATTERNS
        ):
            self.assertNotIn("unrecognized_model", pat)

    def test_empty_or_non_api_error_result_false(self):
        """崩溃/强杀路径（无 result 事件）与 terminal_reason 缺失恒 False。"""
        from core.agent_runner.provider_circuit import is_code_fix_conn_error

        self.assertFalse(is_code_fix_conn_error(None, 1))
        self.assertFalse(is_code_fix_conn_error({}, 1))
        self.assertFalse(is_code_fix_conn_error(
            {"terminal_reason": "turn_limit", "result": _ENOTFOUND_TEXT}, 1))

    def test_shared_wordlist_not_extended(self):
        """共享 SWITCH_ERROR_CONN_PATTERNS 对实测死因文本仍不命中（Non-Goal 守卫）。"""
        from core.agent_runner.provider_circuit import ProviderCircuit

        self.assertFalse(
            ProviderCircuit.classify_switch_error(_ENOTFOUND_TEXT),
            "共享词表被扩充会改变 spec/impl 车道切换行为（proposal Non-Goal）",
        )

    def test_codefix_result_passthrough(self):
        """CodeFixResult 信封透传：conn_error/result_text 逐字透传，api_timeout 不动。"""
        from core.agent_runner.maintenance_runs import run_code_fix

        proot = _make_project_root()
        wt = proot / "wt"
        wt.mkdir(parents=True, exist_ok=True)

        class _ConnFailRunner:
            def __init__(self, exc):
                self.project_root = proot
                self.logger = _FakeLogger()
                self.config = {}
                self._exc = exc

            def _get_agent_model_assignment(self, name):
                return None

            def _get_admin_model(self):
                return None

            def _build_prompt(self, *a, **k):
                return "prompt"

            def _run_claude(self, *a, **k):
                raise self._exc

        items = [_item("a")]
        res = run_code_fix(_ConnFailRunner(_conn_error_exc()), wt, items,
                           run_id="code-fix-conn-1")
        self.assertFalse(res.success)
        self.assertTrue(res.conn_error)
        self.assertTrue(res.api_timeout, "两布尔可同时为真（design D2 互不掣肘）")
        self.assertEqual(res.exit_code, 1)
        self.assertEqual(res.result_text, _ENOTFOUND_TEXT)

        # 普通 RuntimeError（无挂载属性）→ conn_error False / result_text 空
        res2 = run_code_fix(
            _ConnFailRunner(RuntimeError("boom")), wt, items,
            run_id="code-fix-conn-2")
        self.assertFalse(res2.conn_error)
        self.assertEqual(res2.result_text, "")
        self.assertFalse(res2.api_timeout)


# ── 4.2 冷却闸门 ────────────────────────────────────────────────────


class TestCooldownGate(unittest.TestCase):
    """checkpoint 投递入口冷却守卫（spec R2）：拒投递/到期恢复/配置/持久化。"""

    def _orch(self, proot, config=None):
        from core.code_fix import CodeFixOrchestrator

        return CodeFixOrchestrator(
            _GateRunner(proot, config), proot,
            config=config if config is not None else _CFG_ON, logger=None)

    def _arm(self, proot, until_offset=300.0, frm_offset=None):
        """直接置冷却态（持久化写，模拟失败收尾产物）。"""
        from core.code_fix import write_progress

        now = time.time()
        write_progress(
            proot,
            switch_cooldown_until=now + until_offset,
            switch_cooldown_from=(
                now if frm_offset is None else now + frm_offset),
        )

    def test_cooldown_blocks_checkpoint(self):
        """冷却内置态：checkpoint 拒投递（reason=switch_cooldown），进度面提示。"""
        from core.code_fix import read_progress

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        self._arm(proot, until_offset=300)
        orch = self._orch(proot)
        res = orch.checkpoint()
        self.assertEqual(res, {"triggered": False, "reason": "switch_cooldown"})
        prog = read_progress(proot)
        self.assertEqual(prog["reason"], "switch_cooldown")
        self.assertIn("冷却", prog["current"])

    def test_cooldown_blocks_manual_override_path(self):
        """手动路径（override_enabled=True）同被拦：守卫在全部激活路径共入口。"""
        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        self._arm(proot, until_offset=300)
        res = self._orch(proot).checkpoint(override_enabled=True)
        self.assertEqual(res, {"triggered": False, "reason": "switch_cooldown"})

    def test_expired_cooldown_releases_and_dispatches(self):
        """冷却到期：首个通过守卫的 checkpoint 恢复投递并补写解除告警、清冷却态。"""
        from core.admin_store import AdminStore
        from core.code_fix import read_progress

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        self._arm(proot, until_offset=-1.0)
        orch = self._orch(proot)
        res = orch.checkpoint()
        self.assertEqual(res, {"triggered": True, "reason": "dispatched"})
        prog = read_progress(proot)
        self.assertIsNone(prog["switch_cooldown_until"], "到期放行后冷却态须清除")
        self.assertIsNone(prog["switch_cooldown_from"])
        recs = AdminStore(proot, logger=None).read_all()
        release = [r for r in recs
                   if r.get("signal_type") == "code_fix_switch_window_deferred"
                   and "实际推迟" in str(r.get("evidence") or "")]
        self.assertEqual(len(release), 1, "解除告警恰发一条")

    def test_persistence_blocks_fresh_instance(self):
        """持久化读回：冷却态落盘后新实例（模拟重启）在冷却期内仍拦。"""
        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        self._arm(proot, until_offset=300)
        # 全新 runner + 全新 orchestrator = 进程重启后的读回形态
        res = self._orch(proot).checkpoint()
        self.assertEqual(res, {"triggered": False, "reason": "switch_cooldown"})

    def test_no_open_items_bypasses_release_alert(self):
        """台账清空空转：checkpoint 在守卫前早退，不写解除告警（design D5）。"""
        from core.code_fix import write_progress

        proot = _make_project_root()
        self._arm(proot, until_offset=-1.0)
        # 台账为空 + 已有 idle 进度（no_open_items 早退分支的写盘前提）
        write_progress(proot, running=False, phase="idle")
        res = self._orch(proot).checkpoint()
        self.assertEqual(res, {"triggered": False, "reason": "no_open_items"})
        from core.admin_store import AdminStore

        recs = AdminStore(proot, logger=None).read_all()
        self.assertEqual(
            [r for r in recs
             if r.get("signal_type") == "code_fix_switch_window_deferred"],
            [], "台账空转不写解除告警")

    def _seconds(self, config):
        proot = _make_project_root()
        return self._orch(proot, config)._switch_cooldown_seconds()

    def test_config_override_and_zero_disables(self):
        """配置键覆盖：60 生效为 60；0 合法=关闭。"""
        base = {"admin": {"code_review_fix": {"enabled": True}}}
        self.assertEqual(self._seconds(base), 300.0, "缺省复用 300s")
        self.assertEqual(
            self._seconds({"admin": {"code_review_fix": {
                "switch_cooldown_seconds": 60}}}), 60.0)
        self.assertEqual(
            self._seconds({"admin": {"code_review_fix": {
                "switch_cooldown_seconds": 0}}}), 0.0, "0 合法=关闭冷却")

    def test_config_invalid_falls_back(self):
        """非法值（负数/NaN/inf/非数）回退缺省 300。"""
        base = {"admin": {"code_review_fix": {"enabled": True}}}
        for bad in (-5, float("nan"), float("inf"), "abc", None, [], {}):
            cfg = {"admin": {"code_review_fix": {
                "enabled": True, "switch_cooldown_seconds": bad}}}
            self.assertEqual(self._seconds(cfg), 300.0, f"{bad!r} 应回退 300")

    def test_arm_writes_persistent_cooldown_and_alert(self):
        """_arm_switch_cooldown：写持久化冷却字段 + 触发告警（evidence 三要素）。"""
        from core.admin_store import AdminStore, SIGNAL
        from core.code_fix import read_progress

        proot = _make_project_root()
        orch = self._orch(proot)
        before = time.time()
        result = SimpleNamespace(
            run_id="code-fix-arm-1", conn_error=True,
            result_text=_ENOTFOUND_TEXT, error="claude CLI failed: ...")
        orch._arm_switch_cooldown(result)
        prog = read_progress(proot)
        self.assertIsNotNone(prog["switch_cooldown_until"])
        self.assertTrue(
            before + 295 <= prog["switch_cooldown_until"] <= before + 305,
            f"到期时刻≈now+300s: {prog['switch_cooldown_until']}")
        self.assertIsNotNone(prog["switch_cooldown_from"])
        recs = AdminStore(proot, logger=None).read_all()
        alerts = [r for r in recs
                  if r.get("signal_type") == "code_fix_switch_window_deferred"]
        self.assertEqual(len(alerts), 1)
        rec = alerts[0]
        self.assertEqual(rec["kind"], SIGNAL)
        self.assertEqual(rec["source"], "code-fix-lane")
        self.assertEqual(rec["severity"], "warning")
        ev = str(rec.get("evidence") or "")
        self.assertIn("run_id=code-fix-arm-1", ev)
        self.assertIn("死因=", ev)
        self.assertIn(_ENOTFOUND_TEXT, ev)
        self.assertIn("冷却到期=", ev)

    def test_arm_zero_config_skips_cooldown(self):
        """配置关闭（0）：_arm_switch_cooldown 不置冷却、不写告警。"""
        from core.admin_store import AdminStore
        from core.code_fix import read_progress

        proot = _make_project_root()
        cfg = {"admin": {"code_review_fix": {
            "enabled": True, "switch_cooldown_seconds": 0}}}
        orch = self._orch(proot, cfg)
        orch._arm_switch_cooldown(SimpleNamespace(
            run_id="code-fix-arm-2", conn_error=True,
            result_text=_ENOTFOUND_TEXT, error="x"))
        prog = read_progress(proot)
        self.assertIsNone(prog["switch_cooldown_until"])
        recs = AdminStore(proot, logger=None).read_all()
        self.assertEqual(
            [r for r in recs
             if r.get("signal_type") == "code_fix_switch_window_deferred"], [])


# ── 4.3 告警与跨日指纹 ──────────────────────────────────────────────


class _RecLogger:
    """记录 info/warning 文案的假 logger（冷却决策留痕断言用）。"""

    def __init__(self):
        self.infos = []
        self.warnings = []

    def info(self, component, msg, *a, **k):
        self.infos.append(msg)

    def warning(self, component, msg, *a, **k):
        self.warnings.append(msg)

    def error(self, component, msg, *a, **k):
        pass


def _make_monitor(tmp_path, store):
    """__new__ 直构 AdminMonitor（对齐 test_admin_dispatch_escalation 形态）。"""
    from core.admin_monitor import AdminMonitor
    from core.admin_store import AdminStore

    mon = AdminMonitor.__new__(AdminMonitor)
    mon.project_root = Path(tmp_path)
    mon.logger = _RecLogger()
    mon.store = store if store is not None else AdminStore(tmp_path, None)
    mon._started_at = time.time()
    mon._daemon_fp_escalated_at = {}
    mon._daemon_fp_last_failure = {}
    return mon


def _write_error_log(tmp_path, entries):
    """写入 fenixd.log 形态的单行 JSON ERROR 序列（[(msg, ts_epoch)]）。"""
    from datetime import datetime, timezone

    log = Path(tmp_path) / ".fenix" / "logs" / "fenixd.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for msg, ts in entries:
        lines.append(json.dumps({
            "level": "ERROR",
            "timestamp": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
            "component": "pm_engine",
            "message": msg,
        }, ensure_ascii=False))
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return log


class TestCrossdayFingerprintEscalation(unittest.TestCase):
    """daemon_errors 指纹记账跨日同刻复发维度（spec R3 / design D6）。"""

    def _arm_known_store(self, tmp_path, fp):
        """store 预置「已知指纹」记录（description 内嵌指纹前缀对账）。"""
        from core.admin_store import AdminStore, SIGNAL

        store = AdminStore(tmp_path, None)
        store.append({
            "kind": SIGNAL,
            "signal_type": "daemon_errors",
            "spec": None,
            "description": (
                f"fenixd 日志同错误（指纹 {fp[:8]}）在 10 分钟窗口内复现 2 次"
            ),
            "escalated": True,
        })
        return store

    def test_crossday_same_time_escalates_bypassing_known_cooldown(self):
        """24h±5min 内同刻复发：单次在窗也升级，已知指纹 30 分钟冷却不吞。"""
        from core.admin_monitor import _error_fingerprint

        tmp = Path(_mkdtemp("crossday-"))
        now = time.time()
        msg = "API Error: Can't reach the API server (ENOTFOUND)"
        fp = _error_fingerprint("pm_engine", msg)
        self._arm_known_store(tmp, fp)
        mon = _make_monitor(tmp, None)  # 刚启动 → 重启冷却窗内
        _write_error_log(tmp, [
            (msg, now - 24 * 3600 + 30),  # 昨日同刻
            (msg, now - 60),              # 今日一次（在窗计数 1 < 阈值 2）
        ])

        signals = mon._detect_daemon_errors(now)

        self.assertEqual(len(signals), 1, "跨日同刻复发 MUST 绕过已知指纹冷却")
        sig = signals[0]
        self.assertEqual(sig["_fp"], fp)
        self.assertIn(fp[:8], sig["description"], "指纹前缀对账子串 MUST 保留")
        self.assertIn("跨日同刻复发", sig["description"])
        self.assertIn("跨日同刻复发", str(sig.get("evidence") or ""))

    def test_crossday_outside_tolerance_not_escalated(self):
        """跨日差超出 24h±5min 容差：不判复发，单次在窗不升级。"""
        from core.admin_monitor import _error_fingerprint

        tmp = Path(_mkdtemp("crossday2-"))
        now = time.time()
        msg = "gateway window failure (attempt 1)"
        fp = _error_fingerprint("pm_engine", msg)
        self._arm_known_store(tmp, fp)
        mon = _make_monitor(tmp, None)
        _write_error_log(tmp, [
            (msg, now - 24 * 3600 - 600),  # 差 10 分钟：超出容差
            (msg, now - 60),
        ])

        self.assertEqual(mon._detect_daemon_errors(now), [])

    def test_no_repeat_escalation_within_10min(self):
        """同一 last_ts 的后续扫描不重复升级（恰发一次语义）。"""
        tmp = Path(_mkdtemp("crossday3-"))
        now = time.time()
        msg = "gateway window failure (attempt 1)"
        mon = _make_monitor(tmp, None)
        _write_error_log(tmp, [
            (msg, now - 24 * 3600 + 30),
            (msg, now - 60),
        ])

        first = mon._detect_daemon_errors(now)
        self.assertEqual(len(first), 1)
        second = mon._detect_daemon_errors(now)
        self.assertEqual(second, [], "10 分钟内同指纹 MUST NOT 重复升级")

    def test_new_failure_next_day_re_escalates_once(self):
        """新失败到来（跨日）重新判别并恰发一次；同日内在窗 ≥2 次照常升级。"""
        from core.admin_monitor import _error_fingerprint

        tmp = Path(_mkdtemp("crossday4-"))
        now = time.time()
        msg = "gateway window failure (attempt 1)"
        fp = _error_fingerprint("pm_engine", msg)
        mon = _make_monitor(tmp, None)
        # 第一天：单条（不升级）
        _write_error_log(tmp, [(msg, now)])
        self.assertEqual(mon._detect_daemon_errors(now), [])
        # 第二天同刻：新失败 → 恰发一次
        ts2 = now + 24 * 3600
        _write_error_log(tmp, [(msg, now), (msg, ts2)])
        sigs = mon._detect_daemon_errors(ts2 + 60)
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0]["_fp"], fp)
        self.assertIn("跨日同刻复发", sigs[0]["description"])
        # 同一 last_ts 重扫：不再发
        self.assertEqual(mon._detect_daemon_errors(ts2 + 120), [])

    def test_same_day_double_occurrence_still_escalates(self):
        """既有第一维度不回退：同指纹 10 分钟窗内 2 次、间隔 ≤5 分钟照常升级。"""
        from core.admin_monitor import (
            DAEMON_ERROR_RESTART_COOLDOWN_MINUTES,
            _error_fingerprint,
        )

        tmp = Path(_mkdtemp("crossday5-"))
        now = time.time()
        msg = "ordinary repeated failure (attempt 1)"
        fp = _error_fingerprint("pm_engine", msg)
        mon = _make_monitor(tmp, None)
        # 启动锚点拨到冷却窗外（既有 3.3 路径语义保形）
        mon._started_at = now - (DAEMON_ERROR_RESTART_COOLDOWN_MINUTES + 5) * 60
        _write_error_log(tmp, [(msg, now - 60), (msg, now - 30)])

        signals = mon._detect_daemon_errors(now)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["_fp"], fp)
        self.assertNotIn("跨日同刻复发", signals[0]["description"])


if __name__ == "__main__":
    unittest.main()
