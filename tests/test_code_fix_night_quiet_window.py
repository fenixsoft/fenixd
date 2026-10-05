"""test_code_fix_night_quiet_window.py — code-fix 夜间静默窗投递守卫测试
（evo-codefix-night-quiet-window tasks 1.1/1.2/1.3/2.1）

覆盖：
- 2.1 窗内拦截 / 窗外放行 / 四点边界（04:14:59 放行、04:15:00 拦截、
  04:44:59 拦截、04:45:00 放行）——注入本地时钟（spec R6 本地时区）；
- 1.1 武装/解除告警形态与按窗次（含日期）幂等、窗末首个放行 checkpoint
  补写解除并清窗次标识（残留标识不拦截投递）；
- 1.2 与 switch_cooldown 叠加取更晚可投递时刻（reason 取更晚者对应守卫）、
  二者独立武装/解除互不复位；
- 1.2 配置关闭（空串/off）行为与现状一致；非法配置（含 end<=start 逆序）
  降级为无窗并 WARNING 一次；
- spec R5 四路触发经 checkpoint() 单点全覆盖（源码契约固定）；
- spec R7 / 1.3 窗内手动触发 checkpoint(override_enabled=True) 同被拦
  （守卫在公共路径），fenixd CODE_FIX_RESULT_MESSAGES 登记中文文案。

时间注入沿 tests/test_code_fix.py 既有形态 patch 模块 time 属性
（core.code_fix.time.localtime / time.time）。MUST NOT 真跑 agent——
worktree_manager=None 守卫早退替身驱动（沿冷却车道测试同款）。
"""

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# /tmp 可能被外部清扫进程周期性清空。统一用仓库内 .history/tmp（gitignored）。
_HISTORY_TMP = Path(__file__).resolve().parent.parent / ".history" / "tmp"
_HISTORY_TMP.mkdir(parents=True, exist_ok=True)


def _mkdtemp(prefix: str) -> str:
    return tempfile.mkdtemp(prefix=prefix, dir=str(_HISTORY_TMP))


def _local(h, m, s=0):
    """注入用本地时刻 struct（2026-10-06 周二，tm_yday=279）。"""
    return time.struct_time((2026, 10, 6, h, m, s, 1, 279, -1))


def _local_epoch(h, m, s=0):
    """同日本地墙钟 → epoch 秒（真实 mktime，供冷却 until 造值比对）。"""
    return time.mktime((2026, 10, 6, h, m, s, 1, 279, -1))


class _CapturingLogger:
    """捕获日志的假 logger（断言非法配置 WARNING 一次）。"""

    def __init__(self):
        self.records = []

    def _rec(self, level):
        def _w(channel, msg):
            self.records.append((level, channel, msg))
        return _w

    def __getattr__(self, name):
        return self._rec(name)


def _make_project_root() -> Path:
    td = Path(_mkdtemp("cfixnq-"))
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


def _cfg(**extra):
    seg = {"enabled": True}
    seg.update(extra)
    return {"admin": {"code_review_fix": seg}}


_WINDOW_CFG = _cfg(night_quiet_window="04:15-04:45")


class _GateRunner:
    """最小 runner 替身：仅承载 checkpoint 守卫链所需的属性。

    worktree_manager=None：守卫放行后批 worker 走 worktree_manager_missing
    halt 早退——本文件只断言 checkpoint 返回值与告警/进度面，不跑批链。
    """

    def __init__(self, project_root, config=None):
        self.project_root = Path(project_root)
        self.logger = _CapturingLogger()
        self._running_agents = {}
        self.worktree_manager = None
        self.config = dict(config or {})


def _window_alerts(proot):
    from core.admin_store import AdminStore

    recs = AdminStore(proot, logger=None).read_all()
    return [r for r in recs
            if r.get("signal_type") == "code_fix_night_quiet_window"]


class TestWindowParse(unittest.TestCase):
    """配置解析（task 1.1）：缺省值 / 禁用 / 非法降级与 WARNING 一次。"""

    def _orch(self, proot, config, logger=None):
        from core.code_fix import CodeFixOrchestrator

        return CodeFixOrchestrator(
            _GateRunner(proot, config), proot, config=config, logger=logger)

    def test_default_window_value(self):
        """缺省常量 04:15-04:45：conftest 会话级把运行时常量压成 off（防墙钟
        敏感 flakes），故以源码字面量固定生产缺省 + 显式 patch 断言解析。"""
        import core.code_fix as cf

        root = Path(__file__).resolve().parents[1]
        src = (root / "core" / "code_fix.py").read_text(encoding="utf-8")
        self.assertIn('NIGHT_QUIET_WINDOW_DEFAULT = "04:15-04:45"', src)
        proot = _make_project_root()
        with mock.patch.object(cf, "NIGHT_QUIET_WINDOW_DEFAULT", "04:15-04:45"):
            self.assertEqual(
                self._orch(proot, _cfg())._night_quiet_window(),
                (255, 285, "04:15-04:45"))

    def test_off_and_empty_disable(self):
        """空串/off（大小写不敏感）完全禁用：解析返回 None。"""
        proot = _make_project_root()
        for raw in ("off", "OFF", "Off", "", "   "):
            self.assertIsNone(
                self._orch(proot, _cfg(night_quiet_window=raw))
                ._night_quiet_window(),
                f"{raw!r} 须完全禁用")

    def test_invalid_shapes_return_none(self):
        """非法形态（end<=start 逆序/相等、越界、缺分隔符、多段）→ None。"""
        proot = _make_project_root()
        for bad in ("04:45-04:15", "04:15-04:15", "25:00-26:00",
                    "04:15-24:00", "0415-0445", "04:15", "abc",
                    "04:15-04:45-05:00", None):
            self.assertIsNone(
                self._orch(proot, _cfg(night_quiet_window=bad))
                ._night_quiet_window(),
                f"{bad!r} 须按无窗处理")

    def test_invalid_config_warns_once_per_value(self):
        """非法配置 WARNING 一次：同值不重复告警，值变更后重新告警。"""
        from core.code_fix import CodeFixOrchestrator

        proot = _make_project_root()
        cap = _CapturingLogger()
        orch = CodeFixOrchestrator(
            _GateRunner(proot), proot,
            config=_cfg(night_quiet_window="04:45-04:15"), logger=cap)
        for _ in range(3):
            self.assertIsNone(orch._night_quiet_window())
        warns = [r for r in cap.records
                 if r[0] == "warning" and "静默窗" in r[2]]
        self.assertEqual(len(warns), 1, "同一非法值只 WARNING 一次")
        # 值变更后重新告警
        orch._config["admin"]["code_review_fix"]["night_quiet_window"] = (
            "25:00-26:00")
        orch._night_quiet_window()
        warns = [r for r in cap.records
                 if r[0] == "warning" and "静默窗" in r[2]]
        self.assertEqual(len(warns), 2, "非法值变更后重新 WARNING")
        # 合法/禁用值不告警
        orch._config["admin"]["code_review_fix"]["night_quiet_window"] = "off"
        orch._night_quiet_window()
        warns = [r for r in cap.records
                 if r[0] == "warning" and "静默窗" in r[2]]
        self.assertEqual(len(warns), 2, "显式禁用属合法值，不告警")


class TestWindowGate(unittest.TestCase):
    """checkpoint 投递入口静默窗守卫（tasks 1.1/2.1）。"""

    def _orch(self, proot, config=None, logger=None):
        from core.code_fix import CodeFixOrchestrator

        return CodeFixOrchestrator(
            _GateRunner(proot, config), proot,
            config=config if config is not None else _WINDOW_CFG,
            logger=logger)

    def test_in_window_blocks_and_arms(self):
        """窗内：拒投递（reason=night_quiet_window）+ 武装告警（evidence 三要素）
        + 窗次标识持久化。"""
        from core.admin_store import SIGNAL
        from core.code_fix import _epoch_iso, read_progress

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        orch = self._orch(proot)
        with mock.patch("core.code_fix.time.localtime",
                        return_value=_local(4, 30)):
            res = orch.checkpoint()
        self.assertEqual(
            res, {"triggered": False, "reason": "night_quiet_window"})
        prog = read_progress(proot)
        self.assertEqual(prog["reason"], "night_quiet_window")
        self.assertIn("静默窗", prog["current"])
        self.assertEqual(prog["night_quiet_armed_date"], "2026-10-06")
        self.assertEqual(prog["night_quiet_armed_text"], "04:15-04:45")
        alerts = _window_alerts(proot)
        self.assertEqual(len(alerts), 1, "首次进入窗次武装告警恰一条")
        rec = alerts[0]
        self.assertEqual(rec["kind"], SIGNAL)
        self.assertEqual(rec["source"], "code-fix-lane")
        self.assertEqual(rec["severity"], "warning")
        ev = str(rec.get("evidence") or "")
        self.assertIn("窗次=2026-10-06", ev)
        self.assertIn("窗区间=04:15-04:45", ev)
        self.assertIn(
            f"下一可投递时刻={_epoch_iso(_local_epoch(4, 45))}", ev)

    def test_same_window_instance_arms_once(self):
        """同窗次（含日期）幂等：窗内多次 checkpoint 武装告警仍恰一条。"""
        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        orch = self._orch(proot)
        with mock.patch("core.code_fix.time.localtime",
                        return_value=_local(4, 20)):
            self.assertEqual(orch.checkpoint()["reason"], "night_quiet_window")
        with mock.patch("core.code_fix.time.localtime",
                        return_value=_local(4, 40)):
            self.assertEqual(orch.checkpoint()["reason"], "night_quiet_window")
        self.assertEqual(len(_window_alerts(proot)), 1)

    def test_four_boundaries(self):
        """四点边界：04:14:59 放行 / 04:15:00 拦截 / 04:44:59 拦截 / 04:45:00
        放行（start<=cur<end 左闭右开，spec R6 本地时区）。"""
        for h, m, s, blocked in [
            (4, 14, 59, False),
            (4, 15, 0, True),
            (4, 44, 59, True),
            (4, 45, 0, False),
        ]:
            with self.subTest(clock=f"{h:02d}:{m:02d}:{s:02d}"):
                proot = _make_project_root()
                _write_items(proot, {"a": _item("a")})
                _write_verify_yaml(proot)
                orch = self._orch(proot)
                with mock.patch("core.code_fix.time.localtime",
                                return_value=_local(h, m, s)):
                    res = orch.checkpoint()
                if blocked:
                    self.assertEqual(
                        res, {"triggered": False,
                              "reason": "night_quiet_window"})
                else:
                    self.assertEqual(
                        res, {"triggered": True, "reason": "dispatched"})

    def test_window_end_release_once_and_marker_cleanup(self):
        """窗末首个放行 checkpoint 补写解除告警恰一条并清窗次标识；此后不再
        重复解除；残留标识不拦截投递（放行即 dispatched）。"""
        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        orch = self._orch(proot)
        with mock.patch("core.code_fix.time.localtime",
                        return_value=_local(4, 20)):
            self.assertEqual(orch.checkpoint()["reason"], "night_quiet_window")
        with mock.patch("core.code_fix.time.localtime",
                        return_value=_local(5, 0)):
            self.assertEqual(
                orch.checkpoint(), {"triggered": True, "reason": "dispatched"})
        from core.code_fix import read_progress

        prog = read_progress(proot)
        self.assertIsNone(prog["night_quiet_armed_date"], "窗末须清窗次标识")
        self.assertIsNone(prog["night_quiet_armed_text"])
        alerts = _window_alerts(proot)
        self.assertEqual(len(alerts), 2, "武装 + 解除各一条")
        release = [r for r in alerts if "结束" in str(r.get("description"))]
        self.assertEqual(len(release), 1)
        ev = str(release[0].get("evidence") or "")
        self.assertIn("窗次=2026-10-06", ev)
        self.assertIn("窗区间=04:15-04:45", ev)
        # 再次窗外 checkpoint：解除幂等（不再追加）
        with mock.patch("core.code_fix.time.localtime",
                        return_value=_local(5, 10)):
            self.assertEqual(
                orch.checkpoint(), {"triggered": True, "reason": "dispatched"})
        self.assertEqual(len(_window_alerts(proot)), 2)

    def test_manual_override_blocked_in_window(self):
        """窗内手动触发（override_enabled=True）同被拦：守卫位于公共路径，
        手动授权仅越过 enabled 总开关（spec R7）。"""
        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        orch = self._orch(proot, _cfg(enabled=False,
                                      night_quiet_window="04:15-04:45"))
        with mock.patch("core.code_fix.time.localtime",
                        return_value=_local(4, 30)):
            res = orch.checkpoint(override_enabled=True)
        self.assertEqual(
            res, {"triggered": False, "reason": "night_quiet_window"})

    def test_armed_marker_persists_to_fresh_instance(self):
        """窗次标识持久化读回：新实例（模拟重启）在同窗次内不重复武装。"""
        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        with mock.patch("core.code_fix.time.localtime",
                        return_value=_local(4, 20)):
            self.assertEqual(
                self._orch(proot).checkpoint()["reason"], "night_quiet_window")
        # 全新 runner + 全新 orchestrator = 进程重启后的读回形态
        with mock.patch("core.code_fix.time.localtime",
                        return_value=_local(4, 40)):
            self.assertEqual(
                self._orch(proot).checkpoint()["reason"], "night_quiet_window")
        self.assertEqual(len(_window_alerts(proot)), 1)


class TestWindowCooldownCoexistence(unittest.TestCase):
    """静默窗与连接类失败冷却共存（task 1.2）：取更晚可投递时刻、互不复位。"""

    def _orch(self, proot, config=None):
        from core.code_fix import CodeFixOrchestrator

        return CodeFixOrchestrator(
            _GateRunner(proot, config), proot,
            config=config if config is not None else _WINDOW_CFG, logger=None)

    def _in_window(self):
        return (mock.patch("core.code_fix.time.time",
                           return_value=_local_epoch(4, 20)),
                mock.patch("core.code_fix.time.localtime",
                           return_value=_local(4, 20)))

    def test_window_later_than_cooldown(self):
        """冷却至 04:30、窗至 04:45：可投递时刻取更晚的窗末，
        reason=night_quiet_window。"""
        from core.code_fix import write_progress

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        write_progress(
            proot,
            switch_cooldown_until=_local_epoch(4, 30),
            switch_cooldown_from=_local_epoch(4, 20),
        )
        orch = self._orch(proot)
        t, lt = self._in_window()
        with t, lt:
            res = orch.checkpoint()
        self.assertEqual(
            res, {"triggered": False, "reason": "night_quiet_window"})

    def test_cooldown_later_than_window(self):
        """冷却至 04:50、窗至 04:45：可投递时刻取更晚的冷却到期，
        reason=switch_cooldown；窗武装照常独立发生（互不复位）。"""
        from core.code_fix import write_progress

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        write_progress(
            proot,
            switch_cooldown_until=_local_epoch(4, 50),
            switch_cooldown_from=_local_epoch(4, 20),
        )
        orch = self._orch(proot)
        t, lt = self._in_window()
        with t, lt:
            res = orch.checkpoint()
        self.assertEqual(
            res, {"triggered": False, "reason": "switch_cooldown"})
        self.assertEqual(len(_window_alerts(proot)), 1, "窗武装独立于冷却发生")

    def test_cooldown_expiry_releases_while_window_blocks(self):
        """冷却已到期：解除告警照写、冷却态清除；静默窗随后接管拦截——
        二者独立武装/解除，窗拦截不复位冷却、冷却解除不复位窗标识。"""
        from core.admin_store import AdminStore
        from core.code_fix import read_progress, write_progress

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        write_progress(
            proot,
            switch_cooldown_until=_local_epoch(4, 15),
            switch_cooldown_from=_local_epoch(4, 0),
            night_quiet_armed_date="2026-10-06",
            night_quiet_armed_text="04:15-04:45",
        )
        orch = self._orch(proot)
        t, lt = self._in_window()
        with t, lt:
            res = orch.checkpoint()
        self.assertEqual(
            res, {"triggered": False, "reason": "night_quiet_window"})
        prog = read_progress(proot)
        self.assertIsNone(prog["switch_cooldown_until"], "冷却到期须清态")
        self.assertEqual(
            prog["night_quiet_armed_date"], "2026-10-06",
            "窗标识不被冷却解除复位")
        recs = AdminStore(proot, logger=None).read_all()
        cooldown_release = [
            r for r in recs
            if r.get("signal_type") == "code_fix_switch_window_deferred"
            and "实际推迟" in str(r.get("evidence") or "")]
        self.assertEqual(len(cooldown_release), 1, "冷却解除告警照写")
        self.assertEqual(len(_window_alerts(proot)), 0, "同窗次不重复武装")


class TestDisabledAndDegradedConfig(unittest.TestCase):
    """配置关闭 / 非法降级（task 2.1）：行为与现状一致。"""

    def _orch(self, proot, config, logger=None):
        from core.code_fix import CodeFixOrchestrator

        return CodeFixOrchestrator(
            _GateRunner(proot, config), proot, config=config, logger=logger)

    def test_disabled_config_matches_status_quo(self):
        """off / 空串：窗内时刻照样放行 dispatched，零告警、零窗次标识。"""
        for raw in ("off", ""):
            with self.subTest(window=raw or "empty"):
                proot = _make_project_root()
                _write_items(proot, {"a": _item("a")})
                _write_verify_yaml(proot)
                orch = self._orch(
                    proot, _cfg(night_quiet_window=raw))
                with mock.patch("core.code_fix.time.localtime",
                                return_value=_local(4, 30)):
                    res = orch.checkpoint()
                self.assertEqual(
                    res, {"triggered": True, "reason": "dispatched"})
                self.assertEqual(_window_alerts(proot), [])

    def test_invalid_config_degrades_to_no_window_and_warns(self):
        """非法配置（含 end<=start 逆序）：窗内时刻降级为无窗照常放行，且
        WARNING 留痕（防配置错误静默吞掉）。"""
        for bad in ("04:45-04:15", "04:15-04:15", "25:00-26:00", "04:15"):
            with self.subTest(window=bad):
                proot = _make_project_root()
                _write_items(proot, {"a": _item("a")})
                _write_verify_yaml(proot)
                cap = _CapturingLogger()
                orch = self._orch(
                    proot, _cfg(night_quiet_window=bad), logger=cap)
                with mock.patch("core.code_fix.time.localtime",
                                return_value=_local(4, 30)):
                    res = orch.checkpoint()
                self.assertEqual(
                    res, {"triggered": True, "reason": "dispatched"})
                warns = [r for r in cap.records
                         if r[0] == "warning" and "静默窗" in r[2]]
                self.assertEqual(len(warns), 1, f"{bad!r} 须 WARNING 一次")


class TestSingleEntryInvariant(unittest.TestCase):
    """四路触发经 checkpoint() 单点全覆盖（spec R5，task 1.2）：源码契约。"""

    def test_four_trigger_sites_share_single_entry(self):
        """批收尾自驱动 _resubmit / 持有者终态回调（core/code_fix.py）、
        full-scan 兜底（core/event_bus.py）、审查收尾新条目激活
        （core/agent_runner/maintenance_runs.py）四路全部汇入 checkpoint()；
        静默窗判定只落 checkpoint 守卫，不散落在任一触发点。"""
        root = Path(__file__).resolve().parents[1]
        cf = (root / "core" / "code_fix.py").read_text(encoding="utf-8")
        eb = (root / "core" / "event_bus.py").read_text(encoding="utf-8")
        mr = (root / "core" / "agent_runner" / "maintenance_runs.py").read_text(
            encoding="utf-8")
        # 自驱动 _resubmit 与持有者终态回调两路（core/code_fix.py 内）
        self.assertGreaterEqual(
            cf.count("self.checkpoint()"), 2,
            "core/code_fix.py 须保有两路 self.checkpoint() 触发点")
        # full-scan 兜底与审查收尾新条目激活两路
        self.assertIn(".checkpoint()", eb)
        self.assertIn(".checkpoint()", mr)
        # 单点判定：窗守卫在公共入口，触发点零分散
        self.assertIn("night_quiet_window", cf)
        self.assertNotIn("night_quiet_window", eb)
        self.assertNotIn("night_quiet_window", mr)

    def test_manual_trigger_message_registered(self):
        """fenixd CODE_FIX_RESULT_MESSAGES 登记 night_quiet_window 中文文案
        （task 1.3）：窗内手动触发回链不再是裸 reason 串。"""
        import fenixd

        msg = fenixd.FenixDaemon.CODE_FIX_RESULT_MESSAGES["night_quiet_window"]
        self.assertIn("静默窗", msg)


if __name__ == "__main__":
    unittest.main()
