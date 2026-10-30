"""evo-night-window-guard-coverage-closure 守卫面测试（tasks 4.1/4.2/4.3）。

覆盖三块：
- 缺省多窗解析（「03:00-03:15,04:15-04:45」解析两窗、单窗输入行为不变、
  空串/off 禁用）；
- 自进化检查点跨窗顺延（stub 归档时长使预测入窗 → 跳过且水位/就绪扫描
  不动、prune 照常；预测不入窗 → 照常派发）；
- 派发前连通预检（stub getaddrinfo 失败 → 顺延＋跳过日志；stub 抛异常 →
  放行派发；白名单仅维护车道，dispatch 族不探测）。
"""

import json
import os
import shutil
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock


def _local(h, m, s=0):
    """注入用本地时刻 struct（2026-10-06 周二，tm_yday=279）。"""
    return time.struct_time((2026, 10, 6, h, m, s, 1, 279, -1))


class _RecLogger:
    """捕获日志的假 logger（按级别留痕供断言）。"""

    def __init__(self):
        self.records: list = []
        self._lock = threading.Lock()

    def _rec(self, level, *args):
        with self._lock:
            self.records.append((level, " | ".join(str(a) for a in args)))

    def debug(self, *args, **kwargs):
        self._rec("debug", *args)

    def info(self, *args, **kwargs):
        self._rec("info", *args)

    def warning(self, *args, **kwargs):
        self._rec("warning", *args)

    def error(self, *args, **kwargs):
        self._rec("error", *args)

    def by_level(self, level: str) -> list:
        return [msg for lv, msg in self.records if lv == level]


# ── tasks 4.1：缺省多窗解析 ────────────────────────────────────────────────


class TestDefaultMultiWindowParse(unittest.TestCase):
    """缺省「03:00-03:15,04:15-04:45」多窗解析（task 4.1）。"""

    def test_default_literal_parses_two_windows(self):
        from core.code_fix import _parse_night_quiet_windows

        self.assertEqual(
            _parse_night_quiet_windows("03:00-03:15,04:15-04:45"),
            [(180, 195, "03:00-03:15"), (255, 285, "04:15-04:45")],
        )

    def test_default_constant_literal_in_source(self):
        """生产缺省字面量以源码契约固定（conftest 会话级把运行时常量压成
        off，读源码不受影响）。"""
        root = Path(__file__).resolve().parents[1]
        src = (root / "core" / "code_fix.py").read_text(encoding="utf-8")
        self.assertIn(
            'NIGHT_QUIET_WINDOW_DEFAULT = "03:00-03:15,04:15-04:45"', src)

    def test_default_constant_resolves_two_windows_when_patched(self):
        import core.code_fix as cf

        with mock.patch.object(
                cf, "NIGHT_QUIET_WINDOW_DEFAULT",
                "03:00-03:15,04:15-04:45"):
            self.assertEqual(
                cf._parse_night_quiet_windows(cf.NIGHT_QUIET_WINDOW_DEFAULT),
                [(180, 195, "03:00-03:15"), (255, 285, "04:15-04:45")],
            )

    def test_single_window_input_unchanged(self):
        """单窗输入行为不变（多窗化对单窗形态向后兼容）。"""
        from core.code_fix import _parse_night_quiet_windows

        self.assertEqual(
            _parse_night_quiet_windows("04:15-04:45"),
            [(255, 285, "04:15-04:45")])

    def test_semicolon_separated_equivalent(self):
        from core.code_fix import _parse_night_quiet_windows

        self.assertEqual(
            _parse_night_quiet_windows("03:00-03:15; 04:15-04:45"),
            [(180, 195, "03:00-03:15"), (255, 285, "04:15-04:45")],
        )

    def test_empty_and_off_disable(self):
        """空串/off（大小写不敏感）/布尔 false 完全禁用：解析返回 None。"""
        from core.code_fix import _parse_night_quiet_windows

        for raw in ("", "   ", "off", "OFF", "Off", False):
            self.assertIsNone(_parse_night_quiet_windows(raw), repr(raw))

    def test_any_invalid_segment_rejects_whole_list(self):
        """任一段非法 → 整体 None（宁缺毋错，不部分生效）。"""
        from core.code_fix import _parse_night_quiet_windows

        for raw in ("03:00-03:15,bad", "03:15-03:00,04:15-04:45",
                    "04:15-04:45,,"):
            self.assertIsNone(_parse_night_quiet_windows(raw), repr(raw))


# ── tasks 4.2：自进化检查点跨窗顺延 ────────────────────────────────────────


class TestEvolutionCheckpointNightWindowDefer(unittest.TestCase):
    """自进化检查点派发前预计跨窗判定（task 4.2）。

    stub 归档时长使预测入窗 → 本轮跳过（worker 不投递、单飞标记不动、
    就绪扫描不发起、prune 照常）；预测不入窗 → 照常派发。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)
        (self.proot / ".fenix" / "evolution").mkdir(parents=True, exist_ok=True)
        import fenixd
        self.fenixd = fenixd
        self.daemon = fenixd.FenixDaemon.__new__(fenixd.FenixDaemon)
        self.daemon._evolution_in_flight = False
        self.daemon._evolution_host_guard_logged = False
        self.daemon.config = {
            "admin": {"code_review_fix": {
                "night_quiet_window": "03:00-03:15,04:15-04:45"}},
        }
        self.daemon.state_machine = None
        self.daemon.admin_store = None
        self.daemon.agent_runner = None
        self.daemon.pm_engine = None
        self.daemon._admin_executor = None
        self.daemon._evolution_warn = lambda *a, **k: None
        self.daemon.logger = _RecLogger()
        self.dispatches: list = []
        self.daemon._evolution_worker = (
            lambda ready, pending, snapshot_at: self.dispatches.append(snapshot_at))
        self.pruned: list = []
        self.scanned: list = []

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run_checkpoint(self, local_time, est):
        """打桩时钟/归档时长/就绪扫描后跑一次检查点，返回打桩记录。"""
        daemon = self.daemon
        daemon._evolution_archive_duration_mean = lambda proot: est
        daemon._evolution_framework_root = lambda: self.proot

        def _prune(root):
            self.pruned.append(str(root))
            return {"total": 0, "kept": 0, "deleted": 0, "failed": 0}

        def _scan(projects, root):
            self.scanned.append(str(root))
            return [{"name": "proj", "path": str(self.proot), "todo_md": ""}]

        with mock.patch.object(self.fenixd, "PROJECT_ROOT", self.proot), \
                mock.patch("fenixd.time.localtime", return_value=local_time), \
                mock.patch("core.evolution.prune_items", side_effect=_prune), \
                mock.patch("core.evolution.scan_ready_projects", side_effect=_scan), \
                mock.patch("core.evolution.parse_todo_entries",
                           return_value=[{"project": "proj",
                                          "date_section": "2026-10-06",
                                          "section": "浪费", "title": "t"}]), \
                mock.patch("core.evolution.known_ids", return_value=set()):
            daemon._check_evolution_checkpoint()

    def test_predicted_crossing_defers_dispatch(self):
        """02:16 + 预计 2h → 预计结束 04:16 跨 03:00 窗 → 跳过派发。"""
        self._run_checkpoint(_local(2, 16), 7200.0)
        self.assertEqual(self.dispatches, [], "命中窗本轮 MUST NOT 派发")
        self.assertFalse(self.daemon._evolution_in_flight,
                         "跳过不消费单飞标记")
        self.assertEqual(self.scanned, [], "跳过不发起就绪扫描（状态不动）")
        self.assertEqual(len(self.pruned), 1, "prune 不因窗顺延跳过")
        infos = " ".join(self.daemon.logger.by_level("info"))
        self.assertIn("night_quiet_window_deferred", infos)
        self.assertIn("03:00-03:15", infos)

    def test_true_in_window_defers_without_samples(self):
        """派发时刻已落窗（03:05 ∈ 03:00-03:15）、无实测样本 → 跳过。"""
        self._run_checkpoint(_local(3, 5), None)
        self.assertEqual(self.dispatches, [])
        self.assertFalse(self.daemon._evolution_in_flight)
        infos = " ".join(self.daemon.logger.by_level("info"))
        self.assertIn("night_quiet_window_deferred", infos)

    def test_predicted_not_crossing_dispatches(self):
        """02:16 + 预计 10min → 预计结束 02:26 早于窗起点 → 照常派发。"""
        self._run_checkpoint(_local(2, 16), 600.0)
        self.assertEqual(len(self.dispatches), 1, "预测不入窗照常派发")
        self.assertTrue(self.daemon._evolution_in_flight)
        infos = " ".join(self.daemon.logger.by_level("info"))
        self.assertNotIn("night_quiet_window_deferred", infos)

    def test_window_disabled_dispatches_in_window(self):
        """显式 off 禁用 → 窗内时刻照常派发（禁用语义不变）。"""
        self.daemon.config = {"admin": {"code_review_fix": {
            "night_quiet_window": "off"}}}
        self._run_checkpoint(_local(3, 5), None)
        self.assertEqual(len(self.dispatches), 1, "禁用后无窗可避让")

    def test_duration_sample_reads_archive_tail_metrics(self):
        """归档尾部 run_metrics duration_s 均值取样：近 3 轮均值、缺字段剔除。"""
        arch = self.proot / ".fenix" / "runs" / "archive"
        arch.mkdir(parents=True, exist_ok=True)
        rows = {
            "evo-1.jsonl": [
                {"type": "system"}, {"type": "run_metrics", "duration_s": 100.0},
            ],
            "evo-2.jsonl": [
                {"type": "run_metrics", "duration_s": 200.0},
            ],
            "evo-3.jsonl": [
                {"type": "run_metrics"},  # 缺 duration_s → 剔除
            ],
        }
        for name, lines in rows.items():
            (arch / name).write_text(
                "".join(json.dumps(l, ensure_ascii=False) + "\n" for l in lines),
                encoding="utf-8")
        mean = self.fenixd.FenixDaemon._evolution_archive_duration_mean(self.proot)
        self.assertEqual(mean, 150.0)

    def test_duration_sample_missing_archive_returns_none(self):
        mean = self.fenixd.FenixDaemon._evolution_archive_duration_mean(self.proot)
        self.assertIsNone(mean)


class TestHostLayerNightQuietContract(unittest.TestCase):
    """task 2.2：守卫与 reason 留在宿主层 fenixd.py。"""

    def test_reason_string_only_in_host_layer(self):
        root = Path(__file__).resolve().parents[1]
        fx = (root / "fenixd.py").read_text(encoding="utf-8")
        mr = (root / "core" / "agent_runner" / "maintenance_runs.py").read_text(
            encoding="utf-8")
        eb = (root / "core" / "event_bus.py").read_text(encoding="utf-8")
        self.assertIn("night_quiet_window_deferred", fx)
        self.assertNotIn("night_quiet_window", mr)
        self.assertNotIn("night_quiet_window", eb)


# ── tasks 4.3：派发前连通预检 ──────────────────────────────────────────────


class _SpawnReached(Exception):
    """Popen 替身标记：被抛出即证明派发已放行到 spawn 点。"""


class TestConnectivityPreflight(unittest.TestCase):
    """_run_agent 派发前连通预检（task 4.3）。

    stub getaddrinfo 失败（gaierror/超时）→ RuntimeError 顺延＋跳过日志、
    Popen 不触达；stub 抛非 DNS 异常 → fail-open 放行派发；白名单仅维护
    车道，dispatch 族/spec 名不探测。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)
        from core.agent_runner import AgentRunner

        runner = AgentRunner.__new__(AgentRunner)
        runner.config = {"agents": {"run_timeout_seconds": 3600}}
        runner.worktree_manager = None
        runner.state_machine = None
        runner.project_root = self.proot
        runner.logger = _RecLogger()
        runner._running_agents = {}
        self.runner = runner

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _dispatch_to_spawn_point(self, agent_type=None, spec_name=None, gai_side_effect=None,
                  env_overrides=None):
        """跑 _run_agent 至 spawn 点（Popen 以标记异常中止）。

        返回 ``(reached, probe_calls, deferred_exc)`` 三元组：reached=Popen
        触达（放行派发）；probe_calls=socket.getaddrinfo 调用参数列表（打桩
        时记录，证「探测发起/未发起」）；deferred_exc=顺延 RuntimeError（未
        顺延为 None）。gai_side_effect：getaddrinfo 桩（Exception 实例抛出 /
        可调用对象以返回值放行）。
        """
        calls: list = []

        def _gai(*a, **k):
            calls.append(a)
            if isinstance(gai_side_effect, Exception):
                raise gai_side_effect
            return gai_side_effect()

        env = (env_overrides if env_overrides is not None
               else {"ANTHROPIC_BASE_URL": "https://gw.example.com/v1"})
        reached, deferred = False, None
        try:
            if gai_side_effect is None:
                with mock.patch("subprocess.Popen",
                                side_effect=_SpawnReached):
                    self.runner._run_agent(
                        "prompt", self.proot, "run-1", None, env,
                        spec_name=spec_name, agent_type=agent_type)
            else:
                with mock.patch("subprocess.Popen",
                                side_effect=_SpawnReached), \
                        mock.patch("socket.getaddrinfo", side_effect=_gai):
                    self.runner._run_agent(
                        "prompt", self.proot, "run-1", None, env,
                        spec_name=spec_name, agent_type=agent_type)
        except _SpawnReached:
            reached = True
        except RuntimeError as exc:
            deferred = exc
        return reached, calls, deferred

    def test_gaierror_defers_and_logs_skip(self):
        """DNS 解析失败 → 顺延（Popen 不触达）＋含 reason 跳过日志。"""
        with mock.patch("subprocess.Popen", side_effect=_SpawnReached), \
                mock.patch("socket.getaddrinfo",
                           side_effect=socket.gaierror(-2, "Name or service "
                                                       "not known")):
            with self.assertRaises(RuntimeError) as ctx:
                self.runner._run_agent(
                    "prompt", self.proot, "run-1", None,
                    {"ANTHROPIC_BASE_URL": "https://gw.example.com/v1"},
                    spec_name="evolution")
        self.assertIn("dispatch deferred", str(ctx.exception))
        self.assertIn("dns_probe_failed", str(ctx.exception))
        self.assertIn("gw.example.com", str(ctx.exception))
        warns = " ".join(self.runner.logger.by_level("warning"))
        self.assertIn("dns_probe_failed", warns)
        self.assertIn("顺延", warns)

    def test_probe_timeout_defers(self):
        """join 超时按失败顺延（悬挂线程不阻断判定）。"""
        def _hang(host, port):
            time.sleep(1.0)
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                     ("127.0.0.1", 443))]

        from core.agent_runner.runner import AgentRunner as _AR
        with mock.patch.object(_AR, "_DISPATCH_PROBE_TIMEOUT_S", 0.2), \
                mock.patch("subprocess.Popen", side_effect=_SpawnReached), \
                mock.patch("socket.getaddrinfo", side_effect=_hang):
            with self.assertRaises(RuntimeError) as ctx:
                self.runner._run_agent(
                    "prompt", self.proot, "run-1", None,
                    {"ANTHROPIC_BASE_URL": "https://gw.example.com/v1"},
                    agent_type="code-fix")
        self.assertIn("timeout>", str(ctx.exception))

    def test_probe_infra_exception_fail_open_dispatches(self):
        """探测自身抛非 DNS 异常 → 记日志后照常派发（Popen 触达）。"""
        reached, calls, deferred = self._dispatch_to_spawn_point(
            agent_type="administrator",
            gai_side_effect=ValueError("probe infra boom"))
        self.assertTrue(reached, "探测自身异常 MUST NOT 阻断派发（fail-open）")
        self.assertEqual(len(calls), 1, "administrator 命中白名单、探测已发起")
        self.assertIsNone(deferred)
        warns = " ".join(self.runner.logger.by_level("warning"))
        self.assertIn("fail-open", warns)

    def test_whitelist_probe_by_spec_name_fallback(self):
        """未传 agent_type 的直调维护车道按 spec_name 归一（evolution 探测）。"""
        reached, calls, deferred = self._dispatch_to_spawn_point(
            agent_type=None, spec_name="evolution",
            gai_side_effect=socket.gaierror(-2, "no dns"))
        self.assertFalse(reached, "探测失败 → 顺延（Popen 不触达）")
        self.assertEqual(len(calls), 1, "spec_name 归一命中白名单、探测已发起")
        self.assertIsNotNone(deferred)
        self.assertIn("lane=evolution", str(deferred))

    def test_whitelist_maintenance_agent_types_probed(self):
        """administrator/code-fix 直传 agent_type 命中白名单（探测后顺延）。"""
        for agent_type in ("administrator", "code-fix"):
            with self.subTest(agent_type=agent_type):
                reached, calls, deferred = self._dispatch_to_spawn_point(
                    agent_type=agent_type,
                    gai_side_effect=socket.gaierror(-2, "no dns"))
                self.assertFalse(reached)
                self.assertEqual(len(calls), 1)
                self.assertIsNotNone(deferred)
                self.assertIn(f"lane={agent_type}", str(deferred))

    def test_dispatch_family_not_probed(self):
        """dispatch 族（agent_type=implementer 等）不探测——即使 spec_name
        撞白名单词（agent_type 优先归一）。"""
        reached, calls, deferred = self._dispatch_to_spawn_point(
            agent_type="implementer", spec_name="code-review",
            gai_side_effect=socket.gaierror(-2, "no dns"))
        self.assertTrue(reached, "dispatch 族 MUST NOT 做探测顺延")
        self.assertEqual(calls, [], "dispatch 族 MUST NOT 发起探测")
        self.assertIsNone(deferred)

    def test_dispatch_family_types_not_probed(self):
        for agent_type in ("spec-review", "dispute-judge", "verifier", None):
            with self.subTest(agent_type=agent_type):
                reached, calls, _ = self._dispatch_to_spawn_point(
                    agent_type=agent_type,
                    spec_name=("evo-some-user-spec"
                               if agent_type is None else None),
                    gai_side_effect=socket.gaierror(-2, "no dns"))
                self.assertTrue(reached)
                self.assertEqual(calls, [])

    def test_no_base_url_fail_open(self):
        """未配 ANTHROPIC_BASE_URL（spawn env 与 os.environ 皆空）→ 无探测
        目标，直接放行派发、不发起探测。"""
        with mock.patch.dict("os.environ",
                             {"ANTHROPIC_BASE_URL": ""}, clear=False):
            reached, calls, deferred = self._dispatch_to_spawn_point(
                agent_type="code-fix", env_overrides={},
                gai_side_effect=socket.gaierror(-2, "no dns"))
        self.assertTrue(reached, "无探测目标按 fail-open 放行派发")
        self.assertEqual(calls, [], "无探测目标 MUST NOT 发起探测")
        self.assertIsNone(deferred)


class TestApiProbeHost(unittest.TestCase):
    """_api_probe_host 域名提取单元。"""

    def test_https_url_hostname(self):
        from core.agent_runner.runner import AgentRunner

        self.assertEqual(
            AgentRunner._api_probe_host(
                {"ANTHROPIC_BASE_URL": "https://gw.example.com/v1"}),
            "gw.example.com")

    def test_bare_host_port(self):
        from core.agent_runner.runner import AgentRunner

        self.assertEqual(
            AgentRunner._api_probe_host(
                {"ANTHROPIC_BASE_URL": "gw.internal:8443"}),
            "gw.internal")

    def test_missing_or_blank(self):
        from core.agent_runner.runner import AgentRunner

        # 本用例验证「spawn env 无目标 → 空串」；_api_probe_host 对缺键会
        # 按设计回退 os.environ（test_falls_back_to_os_environ 钉死该回退），
        # 故须临时摘除环境变量保证用例封闭（daemon 以 ANTHROPIC_BASE_URL
        # 运行时，未摘除会误报 fallback 命中）。
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTHROPIC_BASE_URL", None)
            self.assertEqual(AgentRunner._api_probe_host({}), "")
            self.assertEqual(
                AgentRunner._api_probe_host({"ANTHROPIC_BASE_URL": "  "}), "")
            self.assertEqual(AgentRunner._api_probe_host(None), "")

    def test_falls_back_to_os_environ(self):
        from core.agent_runner.runner import AgentRunner

        with mock.patch.dict("os.environ",
                             {"ANTHROPIC_BASE_URL": "https://env.example.com"},
                             clear=False):
            self.assertEqual(
                AgentRunner._api_probe_host({}), "env.example.com")

    def test_env_override_wins_over_environ(self):
        from core.agent_runner.runner import AgentRunner

        with mock.patch.dict("os.environ",
                             {"ANTHROPIC_BASE_URL": "https://env.example.com"},
                             clear=False):
            self.assertEqual(
                AgentRunner._api_probe_host(
                    {"ANTHROPIC_BASE_URL": "https://ovr.example.com/v1"}),
                "ovr.example.com")


if __name__ == "__main__":
    unittest.main()
