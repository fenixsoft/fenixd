"""
add-stale-code-selfheal 回归测试。

覆盖（与 tasks.md 一一对应）：
- Task 1.4：陈旧命中写告警、多周期持续为真不重复写未处置告警、
  状态转假不再产生新告警、持续为真期间日志不重复刷 WARNING
- Task 2.4：连续空闲达标触发（写入 restart_request）、活跃 run 出现时计时清零、
  admin 在途时判非空闲、restart_request 已存在不重复写、unmanaged 不触发、
  配置关闭不触发
- Task 3.5：缺省值生效、非法值回退不中断、enabled=false 时不自愈、
  /api/config 读写该节往返一致（非法写拒绝 400 语义）
- Task 4.4：连续 3 次短命退出触发熔断且不再拉起、存活超 60s 重置计数、
  清除标记后恢复拉起、熔断状态不被新 supervisor 进程继承（对 time.sleep /
  子进程退出做可注入替身，避免真实等待）
"""
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

# 模块级 import：pytest 执行期 sys.path 变化可能撞仓库根同名包，
# 模块级 import 绑定真实文件模块（test_daemon_lifecycle_races.py 同款处方）
import fenixd as _fenixd_mod
import bin.fenixd_supervisor as supervisor_mod
import core.fenix_session as fenix_session
from core.admin_store import AdminStore
from core.config import ConfigLoader


class _DaemonParts:
    """构造一个「尚未 initialize」的 FenixDaemon 裸对象并注入测试部件。"""

    def __init__(self, proot: Path):
        self.proot = proot
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        daemon = _fenixd_mod.FenixDaemon.__new__(_fenixd_mod.FenixDaemon)
        daemon.config = {}
        daemon.logger = mock.MagicMock()
        daemon.admin_store = AdminStore(proot, daemon.logger)
        daemon.pm_engine = mock.MagicMock()
        daemon.pm_engine._active_runs = 0
        daemon._admin_executor = None
        daemon._admin_pool_lock = threading.Lock()
        daemon._admin_pool_stats = {"submitted": 0, "completed": 0, "failed": 0}
        daemon._code_stale = False
        daemon._code_files = []
        daemon._code_baseline_ns = 0
        daemon._stale_idle_since = None
        daemon._heal_block_reason = None
        self.daemon = daemon

    def esca_signals(self):
        """admin_alerts 中 ESCALATION 的 (signal_type, description) 列表。"""
        recs = json.loads(self.proot.joinpath(
            ".fenix", "admin_alerts.json").read_text(encoding="utf-8"))
        return [(r.get("signal_type"), r.get("description", "")) for r in recs
                if r.get("kind") == "escalation"]

    def unhandled_stale(self):
        return [r for r in
                json.loads(self.proot.joinpath(
                    ".fenix", "admin_alerts.json").read_text(encoding="utf-8"))
                if r.get("kind") == "escalation"
                and r.get("signal_type") == "stale_code"
                and not r.get("handled")]


# ── 1.4 陈旧检测持续状态与可见性 ───────────────────────────────────

class TestStaleStatePersistence(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        proot = Path(self.tmpdir)
        self.parts = _DaemonParts(proot)
        self.d = self.parts.daemon
        # 一颗"代码文件"：mtime 随测试拨动，模拟磁盘代码更新
        self.codefile = proot / "core_sample.py"
        self.codefile.write_text("# v1\n", encoding="utf-8")
        self.d._code_files = [self.codefile]
        self.d._code_baseline_ns = self.codefile.stat().st_mtime_ns

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _touch_future(self):
        """磁盘代码更新：mtime 拨到未来 60s（严格大于 baseline）。"""
        later = time.time_ns() + 60_000_000_000
        os.utime(self.codefile, ns=(later, later))

    def test_stale_hit_writes_warning_and_alert(self):
        """陈旧命中：日志出现陈旧 WARNING + admin_alerts 新增 stale_code 告警。"""
        self._touch_future()
        self.d._update_stale_code_state()
        assert self.d._code_stale is True
        warnings = " ".join(str(c) for c in
                            self.d.logger.warning.call_args_list)
        assert "磁盘代码" in warnings
        stale = [s for s in self.parts.esca_signals() if s[0] == "stale_code"]
        assert stale, "陈旧命中后应写 stale_code escalation 告警"
        assert "连续空闲后触发重启" in stale[0][1]

    def test_continuous_stale_no_duplicate_alert_no_warning_spam(self):
        """多周期持续为真：不新增第二条未处置告警，也不重复刷 WARNING。"""
        self._touch_future()
        self.d._update_stale_code_state()
        assert len(self.parts.unhandled_stale()) == 1
        warned = len(self.d.logger.warning.call_args_list)
        for _ in range(3):
            self.d._update_stale_code_state()
        assert len(self.parts.unhandled_stale()) == 1
        assert len(self.d.logger.warning.call_args_list) == warned

    def test_true_to_false_no_new_alert_and_logged(self):
        """状态由真转假（磁盘代码回退/重启后 baseline 刷新）：不产生新告警，
        日志记录状态解除。"""
        self._touch_future()
        self.d._update_stale_code_state()
        assert len(self.parts.unhandled_stale()) == 1
        os.utime(self.codefile, ns=(
            self.d._code_baseline_ns - 1, self.d._code_baseline_ns - 1))
        self.d._update_stale_code_state()
        assert self.d._code_stale is False
        assert len(self.parts.unhandled_stale()) == 1
        infos = " ".join(str(c) for c in self.d.logger.info.call_args_list)
        assert "陈旧状态解除" in infos


# ── 2.4 空闲判定与自愈触发 ─────────────────────────────────────────

class TestIdleSelfhealTrigger(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        proot = Path(self.tmpdir)
        self.parts = _DaemonParts(proot)
        self.d = self.parts.daemon
        self.d._code_stale = True
        self.req = proot / ".fenix" / "restart_request"
        self._mp_root = mock.patch.object(_fenixd_mod, "PROJECT_ROOT", proot)
        self._mp_root.start()
        self._sup = mock.patch.object(
            fenix_session, "supervisor_running", return_value=True)
        self._sup.start()

    def tearDown(self):
        self._sup.stop()
        self._mp_root.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _tick(self):
        self.d._maybe_stale_selfheal_tick()

    def test_idle_threshold_triggers_write(self):
        """连续空闲达标（默认阈值 120s）→ 写入 restart_request + 触发日志。"""
        self._tick()  # 空闲开始计时
        assert not self.req.exists()
        # 模拟已连续空闲 130s（> 120s 阈值）
        self.d._stale_idle_since = time.time() - 130
        self._tick()
        assert self.req.exists()
        warns = " ".join(str(c) for c in self.d.logger.warning.call_args_list)
        assert "陈旧自愈触发" in warns
        assert "连续空闲" in warns

    def test_active_run_clears_timer(self):
        """活跃 run 出现时计时清零：90s 后派发新 run → 清零；run 收口后须
        重新累计满阈值才触发。"""
        self._tick()  # t0 开始计时
        assert self.d._stale_idle_since is not None
        self.d.pm_engine._active_runs = 1  # 新 run 派发
        self._tick()
        assert self.d._stale_idle_since is None, "活跃 run 应立即清零计时"
        assert not self.req.exists()
        self.d.pm_engine._active_runs = 0  # run 收口
        self._tick()  # 重新开始计时
        # 只累计 60s（< 120s 阈值）→ 不触发
        self.d._stale_idle_since = time.time() - 60
        self._tick()
        assert not self.req.exists()
        # 累计满 125s → 触发
        self.d._stale_idle_since = time.time() - 125
        self._tick()
        assert self.req.exists()

    def test_admin_inflight_not_idle(self):
        """无 agent run 但 admin 处置在途 → 判非空闲，持续不触发。"""
        from concurrent.futures import ThreadPoolExecutor
        self.d._admin_executor = ThreadPoolExecutor(max_workers=1)
        self.d._admin_pool_stats = {"submitted": 1, "completed": 0, "failed": 0}
        assert self.d._is_idle() is False
        self._tick()
        self.d._stale_idle_since = time.time() - 300
        self._tick()
        assert not self.req.exists()
        # 处置完成 → 恢复空闲判定
        self.d._admin_pool_stats = {"submitted": 1, "completed": 1, "failed": 0}
        assert self.d._is_idle() is True
        self.d._admin_executor.shutdown(wait=False)
        self.d._admin_executor = None

    def test_restart_request_exists_no_rewrite(self):
        """restart_request 已存在：不重复写入，也不重复记录触发日志。"""
        self.req.write_text("2026-09-12T00:00:00+00:00\n", encoding="utf-8")
        before = self.req.stat().st_mtime_ns
        for _ in range(5):
            self._tick()
        assert self.req.stat().st_mtime_ns == before
        warns = [str(c) for c in self.d.logger.warning.call_args_list]
        assert not any("陈旧自愈触发" in w for w in warns)

    def test_unmanaged_no_trigger(self):
        """unmanaged（无 supervisor）：不写入，日志明示跳过。"""
        self._sup.stop()
        self._sup = mock.patch.object(
            fenix_session, "supervisor_running", return_value=False)
        self._sup.start()
        self._tick()
        self.d._stale_idle_since = time.time() - 300
        self._tick()
        assert not self.req.exists()
        infos = " ".join(str(c) for c in self.d.logger.info.call_args_list)
        assert "未受" in infos and "托管" in infos and "跳过" in infos

    def test_config_disabled_no_trigger(self):
        """配置关闭：不写入，日志明示已被配置关闭（陈旧告警仍会由检测侧产生）。"""
        self.d.config = {"stale_code_selfheal": {"enabled": False}}
        self._tick()
        self.d._stale_idle_since = time.time() - 300
        self._tick()
        assert not self.req.exists()
        infos = " ".join(str(c) for c in self.d.logger.info.call_args_list)
        assert "已被配置关闭" in infos

    def test_both_sources_empty_is_idle(self):
        """双源皆空 → 空闲判定为真（无 agent run 且无 admin 在途）。"""
        assert self.d._is_idle() is True


# ── 3.5 配置与 /api/config 读写 ────────────────────────────────────

class TestStaleConfigDefaults(unittest.TestCase):
    def test_missing_section_defaults(self):
        """节缺失 → 缺省值生效：enabled: true / idle_confirm_seconds: 120。"""
        cfg = ConfigLoader.get_stale_code_selfheal_config({})
        assert cfg == {"enabled": True, "idle_confirm_seconds": 120}

    def test_invalid_values_fallback_no_raise(self):
        """非法值回退不中断：非布尔 / 非正整数 / bool 陷阱 / 非 dict 节均不抛异常。"""
        cases = [
            {"stale_code_selfheal": {"enabled": "yes", "idle_confirm_seconds": 42}},
            {"stale_code_selfheal": {"enabled": True, "idle_confirm_seconds": "快"}},
            {"stale_code_selfheal": {"enabled": True, "idle_confirm_seconds": -5}},
            {"stale_code_selfheal": {"enabled": True, "idle_confirm_seconds": 0}},
            {"stale_code_selfheal": {"enabled": True, "idle_confirm_seconds": True}},
            {"stale_code_selfheal": {"enabled": 1, "idle_confirm_seconds": 30.7}},
            {"stale_code_selfheal": "not-a-dict"},
        ]
        for raw in cases:
            cfg = ConfigLoader.get_stale_code_selfheal_config(raw)
            assert isinstance(cfg["enabled"], bool), raw
            assert isinstance(cfg["idle_confirm_seconds"], int) and \
                cfg["idle_confirm_seconds"] > 0, raw
        # 合法值透传（小数取整）
        assert ConfigLoader.get_stale_code_selfheal_config(
            {"stale_code_selfheal": {"enabled": False, "idle_confirm_seconds": 30}}
        ) == {"enabled": False, "idle_confirm_seconds": 30}

    def test_api_config_roundtrip(self):
        """/api/config 读写该节往返一致；非法写拒绝且不落盘。"""
        from core.dashboard import data as dash_data
        tmpdir = tempfile.mkdtemp()
        try:
            proot = Path(tmpdir) / "proj"
            (proot / ".fenix").mkdir(parents=True)
            (proot / ".fenix" / "config.yaml").write_text(
                "project:\n  name: proj\n", encoding="utf-8")
            ok = dash_data.write_config(
                proot, {"stale_code_selfheal": {"enabled": False,
                                               "idle_confirm_seconds": 45}},
                scope="project")
            assert ok["ok"], ok
            eff = dash_data.read_effective_config(proot)
            assert eff["stale_code_selfheal"] == {
                "enabled": False, "idle_confirm_seconds": 45}
            raw_view = dash_data.read_config(proot, scope="project")
            assert raw_view["stale_code_selfheal"] == {
                "enabled": False, "idle_confirm_seconds": 45}
            assert raw_view["sources"]["stale_code_selfheal.enabled"] == "project"
            assert raw_view["sources"][
                "stale_code_selfheal.idle_confirm_seconds"] == "project"
            # 非法写（非布尔 / 非正整数）→ 拒绝且不落盘
            bad = dash_data.write_config(
                proot, {"stale_code_selfheal": {"enabled": "yes"}},
                scope="project")
            assert not bad["ok"] and "must be a boolean" in bad["error"]
            bad2 = dash_data.write_config(
                proot, {"stale_code_selfheal": {"idle_confirm_seconds": -3}},
                scope="project")
            assert not bad2["ok"]
            eff2 = dash_data.read_effective_config(proot)
            assert eff2["stale_code_selfheal"] == {
                "enabled": False, "idle_confirm_seconds": 45}
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_disabled_config_blocks_selfheal(self):
        """enabled=false 时不自愈：_maybe_stale_selfheal_tick 不写 restart_request。"""
        tmpdir = tempfile.mkdtemp()
        try:
            proot = Path(tmpdir)
            parts = _DaemonParts(proot)
            d = parts.daemon
            d.config = {"stale_code_selfheal": {"enabled": False}}
            d._code_stale = True
            req = proot / ".fenix" / "restart_request"
            with mock.patch.object(
                    _fenixd_mod, "PROJECT_ROOT", proot), \
                    mock.patch.object(
                        fenix_session, "supervisor_running", return_value=True):
                d._maybe_stale_selfheal_tick()
            assert not req.exists()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


def test_api_config_http_roundtrip(server_fx):
    """/api/config（HTTP）读写 stale_code_selfheal 节往返一致；非法写 400。

    server_fx 为 pytest fixture（unittest.TestCase 无法接收），故放类外。
    """
    _proot, srv = server_fx
    # 写
    status, body = srv.post_json(
        "/api/config?project=proj-a",
        {"stale_code_selfheal": {"enabled": True, "idle_confirm_seconds": 90}},
    )
    assert status == 200 and body["saved"] is True
    assert body["stale_code_selfheal"] == {
        "enabled": True, "idle_confirm_seconds": 90}
    # 读回
    status, body = srv.get("/api/config?project=proj-a")
    assert status == 200
    assert body["stale_code_selfheal"] == {
        "enabled": True, "idle_confirm_seconds": 90}
    # 非法写 → 400 可读错误而非静默接受
    status, body = srv.post_json(
        "/api/config?project=proj-a",
        {"stale_code_selfheal": {"idle_confirm_seconds": -1}},
    )
    assert status == 400 and "positive integer" in body["error"]


# ── 4.4 supervisor 启动失败熔断 ────────────────────────────────────

class TestSupervisorFuse(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)
        (self.proot / ".fenix" / "logs").mkdir(parents=True)
        self._mp_root = mock.patch.object(
            supervisor_mod, "PROJECT_ROOT", self.proot)
        self._mp_fenix = mock.patch.object(
            supervisor_mod, "FENIX_DIR", self.proot / ".fenix")
        # log()/stop/restart 走模块级常量（import 时绑定），一并重定向到测试项目根
        self._mp_log = mock.patch.object(
            supervisor_mod, "LOG_FILE",
            self.proot / ".fenix" / "logs" / "supervisor.log")
        self._mp_stop = mock.patch.object(
            supervisor_mod, "STOP_FLAG", self.proot / ".fenix" / "stop")
        self._mp_req = mock.patch.object(
            supervisor_mod, "RESTART_REQUEST",
            self.proot / ".fenix" / "restart_request")
        self._mp_root.start()
        self._mp_fenix.start()
        self._mp_log.start()
        self._mp_stop.start()
        self._mp_req.start()

    def tearDown(self):
        self._mp_req.stop()
        self._mp_stop.stop()
        self._mp_log.stop()
        self._mp_fenix.stop()
        self._mp_root.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _marker(self):
        return self.proot / ".fenix" / "supervisor_fused"

    def test_three_short_lived_exits_fuse(self):
        """连续 3 次短命退出（< 60s）→ 达阈值；标记文件含时间戳/次数/pid。"""
        f = supervisor_mod._compute_startup_outcome
        n = f(5, 0)
        assert n == 1
        n = f(10, n)
        assert n == 2
        n = f(30, n)
        assert n == 3
        supervisor_mod._write_fuse_marker(n)
        assert self._marker().is_file()
        data = json.loads(self._marker().read_text(encoding="utf-8"))
        assert data["failures"] == 3
        assert data["created"]
        assert data["pid"] == os.getpid()
        assert supervisor_mod._fuse_blocked() is True

    def test_long_lived_resets_count(self):
        """存活 ≥ 60s 重置连续失败计数为 0（边界 60.0 按成功处理）。"""
        f = supervisor_mod._compute_startup_outcome
        n = f(5, 0)
        n = f(8, n)
        n = f(120, n)
        assert n == 0
        n = f(3, n)
        assert n == 1
        assert f(59.9, 2) == 3  # < 60s：继续累计
        assert f(60.0, 2) == 0  # = 60s：重置

    def test_cleared_marker_resumes(self):
        """清除标记后恢复拉起：_fuse_blocked 为假。"""
        supervisor_mod._write_fuse_marker(3)
        assert supervisor_mod._fuse_blocked() is True
        self._marker().unlink()
        assert supervisor_mod._fuse_blocked() is False

    def test_fuse_not_inherited_by_new_process(self):
        """熔断不被新 supervisor 进程继承：pid 不匹配 → 判定无效并清理旧标记。"""
        self._marker().write_text(json.dumps(
            {"pid": os.getpid() + 999999, "failures": 3,
             "created": "2026-09-12T00:00:00+00:00"}), encoding="utf-8")
        assert supervisor_mod._fuse_blocked() is False
        assert not self._marker().exists(), "无效标记应被顺带清理"

    def test_fuse_alert_content(self):
        """熔断经告警通道产出 critical：supervisor_fused / 处置指引三要素。"""
        written = {}

        class _FakeStore:
            def __init__(self, root, logger=None):
                written["root"] = root
            def append(self, entry):
                written["entry"] = entry
                return entry

        import core.admin_store as _store_mod
        with mock.patch.object(_store_mod, "AdminStore", _FakeStore):
            supervisor_mod._write_fuse_alert()
        entry = written.get("entry")
        assert entry is not None
        assert entry["signal_type"] == "supervisor_fused"
        assert entry["severity"] == "critical"
        assert "已停止自动拉起" in entry["description"]
        assert "supervisor_fused" in entry["recommended_action"]
        assert entry.get("recommended_action")  # 处置指引非空

    def test_main_loop_fuses_after_three_failures(self):
        """main 循环级：连续 3 次短命退出 → 熔断停止拉起，不再第 4 次 start。

        对 time.sleep / 子进程退出做可注入替身（FakeProc 立即终态 + sleep no-op），
        避免真实等待。
        """
        calls = []

        class _FakeProc:
            def __init__(self):
                self.pid = 424242
            def poll(self):
                return 1  # 启动后立即退出（短命）
            def wait(self, timeout=None):
                return 1
            def send_signal(self, sig):
                pass
            def kill(self):
                pass

        def _start():
            calls.append(time.time())
            return _FakeProc()

        with mock.patch.object(supervisor_mod, "start_daemon", _start), \
                mock.patch.object(
                    supervisor_mod.time, "sleep", lambda s: None), \
                mock.patch.object(supervisor_mod, "_write_fuse_alert") as alert, \
                mock.patch.object(supervisor_mod, "_write_supervisor_runtime"):
            supervisor_mod.main()
        assert len(calls) == 3, f"熔断后不应第 4 次拉起（实际 {len(calls)} 次）"
        assert alert.called, "熔断应产出 critical 告警"
        assert self._marker().is_file(), "熔断标记应落盘"
        # supervisor.log 中出现 critical 记录
        sup_log = self.proot / ".fenix" / "logs" / "supervisor.log"
        assert sup_log.is_file()
        assert "CRITICAL" in sup_log.read_text(encoding="utf-8")

    def test_main_loop_long_alive_resets_then_fuses(self):
        """main 循环级：存活 61s 意外退出重置计数，随后连续 3 次短命才熔断。

        共 4 次 start——验证「连续失败计数不跨存活边界继承」（首个 61s 存活把
        计数清零，后 3 次短命从 1 重新累计到阈值）。
        """
        fake_state = {"t": 1_000_000.0}
        start_times = []
        proc_holder = {}
        alive_seq = iter([61.0, 5.0, 8.0, 30.0])  # 各次 daemon 存活时长

        class _FakeProc:
            def __init__(self, alive_seconds):
                self.pid = 424242
                self.rc = 1
                self.exit_at = fake_state["t"] + alive_seconds
            def poll(self):
                return self.rc if fake_state["t"] >= self.exit_at else None
            def wait(self, timeout=None):
                return self.rc
            def send_signal(self, sig):
                pass
            def kill(self):
                pass

        def _start():
            start_times.append(fake_state["t"])
            proc_holder["p"] = _FakeProc(next(alive_seq))
            return proc_holder["p"]

        def _fake_sleep(_s):
            # 推进假时钟到下一个进程退出时刻（等价真实等待到 daemon 死）
            p = proc_holder.get("p")
            if p is not None and fake_state["t"] < p.exit_at:
                fake_state["t"] = p.exit_at

        with mock.patch.object(supervisor_mod, "start_daemon", _start), \
                mock.patch.object(
                    supervisor_mod.time, "time", lambda: fake_state["t"]), \
                mock.patch.object(supervisor_mod.time, "sleep", _fake_sleep), \
                mock.patch.object(supervisor_mod, "_write_fuse_alert"), \
                mock.patch.object(supervisor_mod, "_write_supervisor_runtime"):
            supervisor_mod.main()
        assert len(start_times) == 4, (
            f"存活 61s 应重置计数，随后 3 次短命才熔断（实际 {len(start_times)} 次）")
        assert (self.proot / ".fenix" / "supervisor_fused").is_file()


if __name__ == "__main__":
    unittest.main()