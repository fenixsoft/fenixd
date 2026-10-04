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
from datetime import datetime, timedelta, timezone
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

    def stale_alerts(self):
        """全部 stale_code escalation 记录（含已自动标记已处理的）。"""
        return [r for r in
                json.loads(self.proot.joinpath(
                    ".fenix", "admin_alerts.json").read_text(encoding="utf-8"))
                if r.get("kind") == "escalation"
                and r.get("signal_type") == "stale_code"]

    def stale_records(self):
        """全部 stale_code 记录（info + escalation，evo-reduce-stale-code-
        selfheal-noise 后写入侧两口径并存，读侧按 kind 区分）。"""
        return [r for r in
                json.loads(self.proot.joinpath(
                    ".fenix", "admin_alerts.json").read_text(encoding="utf-8"))
                if r.get("signal_type") == "stale_code"]

    def stale_info(self):
        """stale_code info 级留痕记录。"""
        return [r for r in self.stale_records() if r.get("kind") == "info"]


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

    def test_stale_hit_writes_info_record_when_selfheal_healthy(self):
        """evo-reduce-stale-code-selfheal-noise 2.2：自愈健康（enabled 且未
        悬空超限）时陈旧命中写 info 级留痕 + 日计数日志；不写 escalation、
        不进人工待处理队列。"""
        self._touch_future()
        self.d._update_stale_code_state()
        assert self.d._code_stale is True
        warnings = " ".join(str(c) for c in
                            self.d.logger.warning.call_args_list)
        assert "磁盘代码" in warnings
        recs = self.parts.stale_records()
        assert len(recs) == 1, "陈旧命中后应写 stale_code 留痕记录"
        rec = recs[0]
        assert rec["kind"] == "info", "健康路径必须 info 级留痕而非 escalation"
        assert rec["severity"] == "info"
        # info 级无处理生命周期：写入 payload 自带 handled=true + handled_at
        # （不经 mark_handled 接口），避免呈现为永久未处理
        assert rec.get("handled") is True
        assert rec.get("handled_at")
        assert "无需人工干预" in rec.get("recommended_action", "")
        # 日计数：日志附当日累计（含本条）
        infos = " ".join(str(c) for c in self.d.logger.info.call_args_list)
        assert "当日累计 1 条" in infos
        # 不进 escalation 流，也不进 pending_escalations 同口径清单
        assert self.parts.stale_alerts() == []
        assert self.parts.unhandled_stale() == []
        assert self.d.admin_store.unhandled() == []

    def test_stale_hit_daily_count_survives_restart_and_accumulates(self):
        """日计数跨重启存活：第二次陈旧周期成条后，当日累计按存储当日记录数
        递增（进程内计数器会随重启归零，撑不起「当日」语义）。去重窗置 0 使
        第二周期即刻成条，两条记录 created 同为当日——避免回拨时间戳跨 UTC
        日界的脆弱性。"""
        self._touch_future()
        self.d._update_stale_code_state()
        assert len(self.parts.stale_records()) == 1
        # 模拟重启：新进程（进程内计数归零），去重窗置 0 → 新周期即刻成条
        self.d._code_stale = False
        self.d._dangling_timeout_fired = False
        self.d._stale_check_fresh_seen = True
        with mock.patch.object(_fenixd_mod, "STALE_ALERT_DEDUP_MINUTES", 0):
            self._touch_future()
            self.d._update_stale_code_state()
        assert len(self.parts.stale_records()) == 2
        infos = " ".join(str(c) for c in self.d.logger.info.call_args_list)
        assert "当日累计 2 条" in infos

    def test_continuous_stale_no_duplicate_alert_no_warning_spam(self):
        """多周期持续为真：不新增第二条留痕（60 分钟去重对 info 级同样生效），
        也不重复刷 WARNING。"""
        self._touch_future()
        self.d._update_stale_code_state()
        assert len(self.parts.stale_records()) == 1
        warned = len(self.d.logger.warning.call_args_list)
        for _ in range(3):
            self.d._update_stale_code_state()
        assert len(self.parts.stale_records()) == 1
        assert len(self.d.logger.warning.call_args_list) == warned

    def test_true_to_false_no_new_alert_and_logged(self):
        """状态由真转假（磁盘代码回退/重启后 baseline 刷新）：不产生新告警，
        日志记录状态解除。"""
        self._touch_future()
        self.d._update_stale_code_state()
        assert len(self.parts.stale_records()) == 1
        os.utime(self.codefile, ns=(
            self.d._code_baseline_ns - 1, self.d._code_baseline_ns - 1))
        self.d._update_stale_code_state()
        assert self.d._code_stale is False
        assert len(self.parts.stale_records()) == 1
        infos = " ".join(str(c) for c in self.d.logger.info.call_args_list)
        assert "陈旧状态解除" in infos

    # ── evo-reduce-stale-code-selfheal-noise 2.3：escalation 分流反面 ──

    def test_selfheal_disabled_writes_escalation(self):
        """selfheal disabled：无自动收敛通道 → 沿用 escalation 写入路径
        （warning 级 + 写入即 mark_handled），不写 info 留痕。"""
        self.d.config = {"stale_code_selfheal": {"enabled": False}}
        self._touch_future()
        self.d._update_stale_code_state()
        recs = self.parts.stale_records()
        assert len(recs) == 1
        assert recs[0]["kind"] == "escalation"
        assert recs[0]["severity"] == "warning"
        assert recs[0].get("handled") is True, "warning 级写入即自动标记已处理"
        assert self.parts.stale_info() == []

    def test_dangling_timeout_fired_writes_escalation_not_info(self):
        """悬空超限（_dangling_timeout_fired 已触发）：健康谓词为假 → 写入块
        走 escalation 分支；悬空升级本身由 _alert_dangling_timeout 以独立
        signal_type 承接，写入块不越权代写该类型（不双重升级）。"""
        self.d._dangling_timeout_fired = True
        self._touch_future()
        self.d._update_stale_code_state()
        recs = self.parts.stale_records()
        assert len(recs) == 1
        assert recs[0]["kind"] == "escalation"
        # 写入块只写 signal_type=stale_code；stale_code_dangling_timeout 由
        # 悬空超时分支独立落点（本测试不经该分支，故不应出现）
        assert [r for r in json.loads(
            self.parts.proot.joinpath(".fenix", "admin_alerts.json")
            .read_text(encoding="utf-8"))
            if r.get("signal_type") == "stale_code_dangling_timeout"] == []

    def test_info_record_not_in_pending_escalations_view(self):
        """info 级记录不出现在 pending_escalations 同口径清单
        （kind=ESCALATION 且未处理，AdminStore.unhandled）——mark_handled/
        unhandled 的 ESCALATION 锚定口径不受新 kind 影响。"""
        self._touch_future()
        self.d._update_stale_code_state()
        assert len(self.parts.stale_records()) == 1
        assert self.parts.stale_records()[0]["kind"] == "info"
        assert self.d.admin_store.unhandled() == []

    # ── evo-add-stale-code-dangling-deadline 2.1：悬空起点计量 ─────────

    def test_stale_since_recorded_on_false_to_true_edge(self):
        """假→真边沿记录 _code_stale_since（UTC、tz-aware），既有边沿告警不变。"""
        self._touch_future()
        self.d._update_stale_code_state()
        assert self.d._code_stale is True
        since = self.d._code_stale_since
        assert since is not None
        assert since.tzinfo is not None, "悬空起点应为带时区（UTC）的 datetime"
        assert abs((datetime.now(timezone.utc) - since).total_seconds()) < 60

    def test_stale_since_cleared_on_recover(self):
        """基线恢复新鲜（真→假）→ _code_stale_since 清零；此后再陈旧的边沿
        取检测时刻（非启动时刻）。"""
        self._touch_future()
        self.d._update_stale_code_state()
        assert self.d._code_stale_since is not None
        os.utime(self.codefile, ns=(
            self.d._code_baseline_ns - 1, self.d._code_baseline_ns - 1))
        self.d._update_stale_code_state()
        assert self.d._code_stale is False
        assert self.d._code_stale_since is None, "恢复新鲜后悬空起点应清零"
        # 已见过新鲜检测，第二轮边沿取当前检测时刻
        startup = datetime.now(timezone.utc) - timedelta(seconds=3600)
        self.d._proc_started_utc = startup
        self._touch_future()
        self.d._update_stale_code_state()
        assert self.d._code_stale_since is not None
        assert self.d._code_stale_since > startup, "后续边沿应取检测时刻而非启动时刻"

    def test_stale_since_takes_startup_time_when_stale_at_start(self):
        """进程启动时基线即已陈旧（首检即超 baseline）：_code_stale_since 取
        进程启动时刻（SPEC 场景 AND 子句）。"""
        self.d._proc_started_utc = datetime.now(timezone.utc) - timedelta(seconds=100)
        self._touch_future()
        self.d._update_stale_code_state()
        assert self.d._code_stale is True
        assert self.d._code_stale_since == self.d._proc_started_utc


# ── stale-code-alert-window-dedup 2.1：告警跨重启窗口去重 ──────────

class TestStaleAlertWindowDedup(unittest.TestCase):
    """60 分钟窗口去重：写入前查 latest_signal，同窗命中跳过写入降级为日志。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        proot = Path(self.tmpdir)
        self.parts = _DaemonParts(proot)
        self.d = self.parts.daemon
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

    def _simulate_restart(self):
        """模拟 daemon 重启后新进程：_code_stale 从假开始，再次检测命中。"""
        self.d._code_stale = False

    def _backdate_first_alert(self, minutes_ago: int):
        """把已落盘的 stale_code 记录 created 拨回 minutes_ago 分钟前。"""
        path = self.parts.proot / ".fenix" / "admin_alerts.json"
        recs = json.loads(path.read_text(encoding="utf-8"))
        old = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
        recs[0]["created"] = old.isoformat()
        path.write_text(json.dumps(recs), encoding="utf-8")

    def test_within_window_no_duplicate_entry(self):
        """窗口内重启（新进程再次「首次变陈旧」）：不新增条目，降级为日志。
        evo-reduce-stale-code-selfheal-noise：健康路径 info 级留痕同受窗口
        去重约束（latest_signal kind 白名单已含 INFO）。"""
        self._touch_future()
        self.d._update_stale_code_state()
        assert len(self.parts.stale_records()) == 1
        # 模拟重启：新进程边沿重新假→真，但存储 60 分钟内已有同信号记录
        self._simulate_restart()
        self._update_and_assert_deduped(expected=1)

    def _update_and_assert_deduped(self, expected: int):
        self.d._update_stale_code_state()
        assert self.d._code_stale is True
        assert len(self.parts.stale_records()) == expected, (
            "窗口内命中去重不应新增同文条目")
        infos = " ".join(str(c) for c in self.d.logger.info.call_args_list)
        assert "窗口去重" in infos and "跳过写入" in infos

    def test_beyond_window_new_cycle_writes_new_entry(self):
        """超窗新周期：距上次留痕超过 60 分钟再次进入陈旧态照常成条。"""
        self._touch_future()
        self.d._update_stale_code_state()
        assert len(self.parts.stale_records()) == 1
        self._backdate_first_alert(minutes_ago=61)
        self._simulate_restart()
        self.d._update_stale_code_state()
        assert self.d._code_stale is True
        records = self.parts.stale_records()
        assert len(records) == 2, "超窗新周期应照常写入新留痕"
        # 新条目沿用「写入即视同已处理」语义（info 级 payload 自带 handled）
        assert records[1].get("handled") is True
        # 超窗路径不走去重分支
        infos = " ".join(str(c) for c in self.d.logger.info.call_args_list)
        assert "窗口去重命中" not in infos
        assert "跳过写入" not in infos

    def test_info_and_escalation_share_dedup_window(self):
        """info 留痕与 escalation 升级共用 60 分钟去重窗（同 signal_type）：
        窗内 info 已成条时，disabled 升级不得重复成条（同窗互斥成条）。"""
        self._touch_future()
        self.d._update_stale_code_state()  # 健康 → info 留痕
        assert len(self.parts.stale_info()) == 1
        # 项目切到 disabled 后新陈旧周期：escalation 意图被同窗 info 压制
        self.d.config = {"stale_code_selfheal": {"enabled": False}}
        self.d._code_stale = False
        self._touch_future()
        self.d._update_stale_code_state()
        assert self.parts.stale_alerts() == [], "同窗内 escalation 不得重复成条"
        infos = " ".join(str(c) for c in self.d.logger.info.call_args_list)
        assert "窗口去重命中" in infos

    def test_empty_storage_first_report_unchanged(self):
        """空存储首报：无任何 stale_code 记录时照常写入（首报不受去重影响）。"""
        alerts_path = self.parts.proot / ".fenix" / "admin_alerts.json"
        assert not alerts_path.exists(), "前置：存储为空（尚无落盘文件）"
        self._touch_future()
        self.d._update_stale_code_state()
        records = self.parts.stale_records()
        assert len(records) == 1
        assert records[0].get("handled") is True
        infos = " ".join(str(c) for c in self.d.logger.info.call_args_list)
        assert "跳过写入" not in infos


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
        """连续空闲达标（缺省阈值 600s，evo-reduce-stale-code-selfheal-noise）
        → 写入 restart_request + 触发日志。"""
        self._tick()  # 空闲开始计时
        assert not self.req.exists()
        # 模拟已连续空闲 650s（> 600s 阈值）
        self.d._stale_idle_since = time.time() - 650
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
        # 只累计 60s（< 600s 阈值）→ 不触发
        self.d._stale_idle_since = time.time() - 60
        self._tick()
        assert not self.req.exists()
        # 累计满 650s → 触发
        self.d._stale_idle_since = time.time() - 650
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

    # ── fix-fasttrack-implemented-deadstate 2.3：在飞 ocr 车道维度 ──────

    def test_ocr_lane_inflight_not_idle_and_blocks_selfheal(self):
        """车道在飞 120s+ 不触发 restart_request：空闲第五维判非空闲 +
        阻断原因体系 reason="ocr-lane"（车道线程不进 _active_runs/
        _running_agents，缺本维度时自愈 SIGTERM 杀在飞车道 run）。"""
        self.d.pm_engine.ocr_lane_busy = mock.MagicMock(return_value=True)
        assert self.d._is_idle() is False
        self._tick()  # 开始计时（此前应已被 ocr-lane 阻断清零）
        self.d._stale_idle_since = time.time() - 300  # 远超 120s 阈值
        self._tick()
        assert not self.req.exists()
        infos = " ".join(str(c) for c in self.d.logger.info.call_args_list)
        assert "impl-ocr 车道在飞" in infos and "自愈跳过" in infos

    def test_ocr_lane_finish_resumes_idle_accumulation(self):
        """车道收尾（登记清理）后空闲判定恢复为真，重新累计满阈值照常触发。"""
        self.d.pm_engine.ocr_lane_busy = mock.MagicMock(return_value=True)
        self._tick()
        assert self.d._stale_idle_since is None  # 在飞期间计时清零
        self.d.pm_engine.ocr_lane_busy = mock.MagicMock(return_value=False)
        assert self.d._is_idle() is True
        self._tick()  # 车道收尾后重新开始计时
        assert self.d._stale_idle_since is not None
        # 重新累计满阈值 → 正常触发
        self.d._stale_idle_since = time.time() - 650
        self._tick()
        assert self.req.exists()

    def test_ocr_lane_busy_exception_not_idle(self):
        """ocr_lane_busy 判定异常 → 按非空闲处理（宁紧勿松，不触发自愈）。"""
        self.d.pm_engine.ocr_lane_busy = mock.MagicMock(
            side_effect=RuntimeError("boom"))
        assert self.d._is_idle() is False
        self.d._stale_idle_since = time.time() - 300
        self._tick()
        assert not self.req.exists()
        warns = " ".join(str(c) for c in self.d.logger.warning.call_args_list)
        assert "ocr 车道在飞判定异常" in warns

    # ── 09-23 code-fix 批在飞维度（批5/6 烧毁事故热修）─────────────────

    def test_codefix_inflight_blocks_selfheal(self):
        """code-fix 批在飞（progress.running=true）→ 阻断自愈不写 restart_request。

        supervisor 优雅重启会 SIGKILL 排水中的批 worker：回归进行中/合回
        核销前的批被杀，agent 已落盘的 result（success）随 worktree 孤儿
        清扫整批作废（09-23 批5/6 双烧实证）。
        """
        with mock.patch("core.code_fix.read_progress",
                        return_value={"running": True}):
            self._tick()  # 阻断清零，不开始计时
            assert self.d._stale_idle_since is None
            self.d._stale_idle_since = time.time() - 300  # 远超阈值
            self._tick()
        assert not self.req.exists()
        infos = " ".join(str(c) for c in self.d.logger.info.call_args_list)
        assert "code-fix 批在飞" in infos and "自愈跳过" in infos

    def test_codefix_finish_resumes_idle_accumulation(self):
        """批收尾（running=false）后恢复空闲累计，重新满阈值照常触发。"""
        with mock.patch("core.code_fix.read_progress",
                        return_value={"running": False}):
            self._tick()
            assert self.d._stale_idle_since is not None  # 非阻断，正常计时
            self.d._stale_idle_since = time.time() - 650
            self._tick()
            assert self.req.exists()


# ── evo-reduce-stale-code-selfheal-noise 2.3：自愈动作失败升级 ──────

class TestSelfhealWriteFailureEscalation(unittest.TestCase):
    """restart_request 写失败（OSError）→ escalation 升级 + 60 分钟去重。

    夹具沿用 TestIdleSelfhealTrigger 形态；写失败以「仅对 restart_request
    抛 OSError 的 write_text 包装」构造（不占位目录——Path.exists() 对目录
    也为真会先命中 in-flight 阻断，到不了写入点），不 mock 内部实现。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        proot = Path(self.tmpdir)
        self.parts = _DaemonParts(proot)
        self.d = self.parts.daemon
        self.d._code_stale = True
        self.req = proot / ".fenix" / "restart_request"
        self.history_path = proot / ".fenix" / "restart_history.jsonl"
        self._mp_root = mock.patch.object(_fenixd_mod, "PROJECT_ROOT", proot)
        self._mp_root.start()
        self._sup = mock.patch.object(
            fenix_session, "supervisor_running", return_value=True)
        self._sup.start()

    def tearDown(self):
        self._sup.stop()
        self._mp_root.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _broken_write_text(self):
        """返回上下文管理器：仅 restart_request 的 write_text 抛 OSError。"""
        real_write_text = Path.write_text

        def wrapper(path_self, data, *args, **kwargs):
            if path_self.name == "restart_request":
                raise OSError(28, "No space left on device")
            return real_write_text(path_self, data, *args, **kwargs)

        return mock.patch.object(Path, "write_text", wrapper)

    def _escalations(self):
        return [r for r in self.parts.stale_records()
                if r.get("kind") == "escalation"]

    def _tick_ready(self):
        self.d._stale_idle_since = time.time() - 650
        self.d._maybe_stale_selfheal_tick()

    def test_write_failure_escalates_unhandled(self):
        """空闲确认达成但写失败：error 日志之外补一条 stale_code escalation，
        保持未处理（进人工待处理视图）；不落重启历史。"""
        with self._broken_write_text():
            self._tick_ready()
        assert not self.req.exists(), "写失败后不应有 request 文件"
        alerts = self._escalations()
        assert len(alerts) == 1, "写失败必须升级 escalation（原先仅 logger.error）"
        assert alerts[0]["signal_type"] == "stale_code"
        assert alerts[0]["severity"] == "warning"
        assert alerts[0].get("handled") is False, "升级须留在人工待处理视图"
        assert self.d.admin_store.unhandled(), "pending_escalations 同口径可见"
        assert not self.history_path.exists(), "写失败不得落重启历史"

    def test_repeat_failure_deduped_within_window(self):
        """60 分钟窗口内重复写失败：升级不重复成条（append + latest_signal
        去重范式）。"""
        with self._broken_write_text():
            self._tick_ready()
            assert len(self._escalations()) == 1
            self._tick_ready()
        assert len(self._escalations()) == 1, "同窗重复失败不得重复成条"
        infos = " ".join(str(c) for c in self.d.logger.info.call_args_list)
        assert "去重命中" in infos


# ── evo-reduce-stale-code-selfheal-noise 3.3：未知 kind=info 前端兼容 ──

class TestDashboardInfoKindTolerance(unittest.TestCase):
    """kind=info 记录对 dashboard 消费链路不可见且不致渲染报错。

    design「兼容与风险」核定的 kind 过滤消费方清单：告警列表/已解决折叠区/
    摘要（admin_alerts.py，仅 ESCALATION）、运维活动（disposition）、SPEC
    时间轴 admin 事件（timeline._admin_events_for_spec，ESCALATION+
    DISPOSITION）。info 记录在场时各读取函数不抛异常，且 info 不进未处理/
    已解决视图（pending_escalations 同口径即 unhandled()，已在 3.2 用例锁定）。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)
        (self.proot / ".fenix").mkdir(parents=True)
        store = AdminStore(self.proot)
        # 生产同形 info 留痕（evo-reduce-stale-code-selfheal-noise 写入口产物）
        store.append({
            "kind": "info",
            "signal_type": "stale_code",
            "spec": None,
            "severity": "info",
            "description": "daemon 进程持旧代码，陈旧自愈已启用且链路健康",
            "handled": True,
            "handled_at": datetime.now(timezone.utc).isoformat(),
        })
        store.append({
            "kind": "escalation",
            "signal_type": "token_budget",
            "spec": "demo",
            "severity": "major",
            "description": "对照用未处理升级（进人工队列）",
        })

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_alert_views_ignore_info_records(self):
        """告警列表/未处理/已解决/摘要均不受 info 记录影响且不抛异常。"""
        from core.dashboard.data import admin_alerts as aa

        alerts = aa.get_alerts(self.proot)
        assert len(alerts) == 2, "原始列表原样可读（不因未知 kind 抛异常）"
        unhandled = aa.get_unhandled_alerts(self.proot)
        assert [a["signal_type"] for a in unhandled] == ["token_budget"]
        resolved = aa.get_resolved_alerts(self.proot)
        assert [a["signal_type"] for a in resolved] == []
        summary = aa.alerts_summary(self.proot)
        assert summary["unhandled_count"] == 1
        assert summary["latest"]["signal_type"] == "token_budget"

    def test_admin_activities_and_timeline_ignore_info_records(self):
        """运维活动（disposition 口径）与 SPEC 时间轴 admin 事件
        （ESCALATION+DISPOSITION 口径）均不出现 info 记录。"""
        from core.dashboard.data import admin_alerts as aa
        from core.dashboard.data.timeline import _admin_events_for_spec

        acts = aa.get_admin_activities(self.proot, spec="demo")
        assert acts == [], "无 disposition 记录时运维活动为空（info 不入列）"
        events = _admin_events_for_spec(self.proot, "demo")
        assert [e.get("signal_type") for e in events] == ["token_budget"], (
            "时间轴 admin 事件不收录 info 级留痕")
        # daemon 级 info 记录（spec=None）也不误挂到任何 SPEC
        events_any = _admin_events_for_spec(self.proot, "other-spec")
        assert events_any == []


# ── evo-add-stale-code-dangling-deadline：悬空超时升级 ──────────────

class TestStaleDanglingTimeout(unittest.TestCase):
    """悬空超时不等空闲强推规划性重启（2.2/2.3）+ 升级告警（3.1）。

    夹具沿用 TestIdleSelfhealTrigger 形态：_code_stale 置真 + supervisor 托管
    + PROJECT_ROOT 指向临时项目；悬空起点直接拨 _code_stale_since（UTC）。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        proot = Path(self.tmpdir)
        self.parts = _DaemonParts(proot)
        self.d = self.parts.daemon
        self.d._code_stale = True
        self.req = proot / ".fenix" / "restart_request"
        self.history_path = proot / ".fenix" / "restart_history.jsonl"
        self._mp_root = mock.patch.object(_fenixd_mod, "PROJECT_ROOT", proot)
        self._mp_root.start()
        self._sup = mock.patch.object(
            fenix_session, "supervisor_running", return_value=True)
        self._sup.start()

    def tearDown(self):
        self._sup.stop()
        self._mp_root.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _set_dangling(self, seconds: float):
        """拨悬空起点：已悬空 seconds 秒（UTC datetime，与生产写入同形）。"""
        self.d._code_stale_since = (
            datetime.now(timezone.utc) - timedelta(seconds=seconds))

    def _tick(self):
        self.d._maybe_stale_selfheal_tick()

    def _write_history(self, entries):
        """写 restart_history.jsonl：[(ts_iso, self_triggered), ...]。"""
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        with self.history_path.open("w", encoding="utf-8") as f:
            for ts_iso, self_triggered in entries:
                f.write(json.dumps({
                    "ts": ts_iso,
                    "self_triggered": self_triggered,
                    "self_triggered_streak": 1 if self_triggered else 0,
                }, ensure_ascii=False) + "\n")

    def _dangling_alerts(self):
        path = self.parts.proot.joinpath(".fenix", "admin_alerts.json")
        if not path.exists():
            return []
        return [r for r in json.loads(path.read_text(encoding="utf-8"))
                if r.get("kind") == "escalation"
                and r.get("signal_type") == "stale_code_dangling_timeout"]

    def _history_tail(self):
        lines = self.history_path.read_text(encoding="utf-8").strip().splitlines()
        return json.loads(lines[-1])

    def test_busy_dangling_timeout_writes_request_without_idle(self):
        """忙时（在飞 run）悬空超时 → 不等空闲直接写 restart_request，
        重启历史如实记录 self_triggered=False（超时分支不强制置真）。"""
        self.d.pm_engine._active_runs = 1  # 非空闲（既有空闲路径在此清零计时）
        self._set_dangling(14401)  # 超过缺省 14400s
        self._tick()
        assert self.req.exists(), "悬空超时后忙时也应写入 restart_request"
        assert self.d._self_triggered_cycle is False, "超时分支不得置真自触发标志"
        tail = self._history_tail()
        assert tail["self_triggered"] is False
        assert tail["self_triggered_streak"] == 0

    def test_not_yet_timed_out_no_trigger(self):
        """悬空未超时（≤ max_dangling_seconds）：忙时不触发，行为与现状一致。"""
        self.d.pm_engine._active_runs = 1
        self._set_dangling(3600)  # 1 小时 < 4 小时缺省
        self._tick()
        assert not self.req.exists()
        assert self._dangling_alerts() == []

    def test_zero_disables_upgrade(self):
        """max_dangling_seconds=0：关闭升级，悬空再久也不走超时分支。"""
        self.d.config = {"stale_code_selfheal": {"max_dangling_seconds": 0}}
        self.d.pm_engine._active_runs = 1
        self._set_dangling(10 ** 7)  # 远超任何非零时限
        self._tick()
        assert not self.req.exists()
        assert self._dangling_alerts() == []

    def test_timeout_alert_unhandled_and_deduped(self):
        """升级告警保持未处理（进人工待处理视图）；60 分钟内重复触发去重
        跳过写入仅留日志（不写即 handled 的 stale_code 语义不复用）。"""
        self._set_dangling(14401)
        self._tick()
        alerts = self._dangling_alerts()
        assert len(alerts) == 1
        assert alerts[0]["severity"] == "warning"
        assert alerts[0].get("handled") is False, "升级告警不得写入即 handled"
        # 模拟「request 已被 supervisor 消费、进程尚未终止」窗口内的重复 tick：
        # 复位防重复标志后再次进入超时分支 → 告警 60 分钟去重命中不重复成条
        self.req.unlink()
        self.d._dangling_timeout_fired = False
        self._tick()
        assert len(self._dangling_alerts()) == 1, "60 分钟窗口内不得重复写告警"
        infos = " ".join(str(c) for c in self.d.logger.info.call_args_list)
        assert "去重命中" in infos

    def test_cooldown_gate_still_blocks(self):
        """cooldown 闸门仍生效：窗口内重启数达阈值时悬空超时也不触发。"""
        now_iso = datetime.now(timezone.utc).isoformat()
        self._write_history([(now_iso, False)] * 3)  # cooldown_threshold=3
        self._set_dangling(14401)
        self._tick()
        assert not self.req.exists(), "冷却窗口内悬空超时不得触发重启"

    def test_self_triggered_gate_not_forced_true(self):
        """self-triggered 闸门：距上次重启超窗的历史下触发，记录按既有语义
        记否（streak 归零），超时分支不置真自触发标志。"""
        old_iso = (datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat()
        self._write_history([(old_iso, True)])
        self._set_dangling(14401)
        self._tick()
        assert self.req.exists()
        tail = self._history_tail()
        assert tail["self_triggered"] is False
        assert tail["self_triggered_streak"] == 0

    def test_repeat_tick_no_rewrite_after_fired(self):
        """触发成功后置位防重复标志：supervisor 已消费 request（文件被删）
        但进程尚未终止的窗口内，1s tick 不得重复 touch/重复告警。"""
        self._set_dangling(14401)
        self._tick()
        assert self.req.exists()
        alerts_before = len(self._dangling_alerts())
        self.req.unlink()  # 模拟 supervisor 消费掉 request
        self._tick()
        self._tick()
        assert not self.req.exists(), "防重复标志置位后不得重写 request"
        assert len(self._dangling_alerts()) == alerts_before


def _panel_pair(section: dict) -> dict:
    """stale_code_selfheal 节中**面板受管**的两键。

    冷却五键（evo-stale-selfheal-restart-cooldown）经配置文件 + 30s 热更新生效、
    不在 Dashboard 面板暴露，但读视图（read_config / read_effective_config）经
    get_stale_code_selfheal_config 一并回显其生效值——本断言只锁定面板受管两键
    的往返一致，不因冷却键的回显而失真。
    """
    return {k: section[k] for k in ("enabled", "idle_confirm_seconds")}


# ── 3.5 配置与 /api/config 读写 ────────────────────────────────────

class TestStaleConfigDefaults(unittest.TestCase):
    def test_missing_section_defaults(self):
        """节缺失 → 缺省值生效：enabled: true / idle_confirm_seconds: 600
        （evo-reduce-stale-code-selfheal-noise 3.2，原 120；冷却五键于
        evo-stale-selfheal-restart-cooldown 1.1 加入，缺省一并生效；
        max_dangling_seconds 于 evo-add-stale-code-dangling-deadline 1.1 加入）。"""
        cfg = ConfigLoader.get_stale_code_selfheal_config({})
        assert cfg == {
            "enabled": True,
            "idle_confirm_seconds": 600,
            "cooldown_window_seconds": 1800,
            "cooldown_threshold": 3,
            "cooldown_duration_seconds": 600,
            "self_triggered_window_seconds": 300,
            "self_triggered_threshold": 3,
            "max_dangling_seconds": 14400,
        }

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
        # 合法值透传（小数取整）；未配置的冷却五键回退缺省
        passthrough = ConfigLoader.get_stale_code_selfheal_config(
            {"stale_code_selfheal": {"enabled": False, "idle_confirm_seconds": 30}}
        )
        assert passthrough["enabled"] is False
        assert passthrough["idle_confirm_seconds"] == 30
        assert (passthrough["cooldown_window_seconds"],
                passthrough["cooldown_threshold"],
                passthrough["cooldown_duration_seconds"],
                passthrough["self_triggered_window_seconds"],
                passthrough["self_triggered_threshold"]) == (1800, 3, 600, 300, 3)

    def test_max_dangling_seconds_semantics(self):
        """max_dangling_seconds 校验语义（evo-add-stale-code-dangling-deadline
        1.1）：0 合法（关闭升级）；负值/非整数/bool 回退缺省；合法值透传。"""
        # 0 = 关闭升级（合法值原样返回，不回退缺省——与正整数键语义相反）
        zero = ConfigLoader.get_stale_code_selfheal_config(
            {"stale_code_selfheal": {"max_dangling_seconds": 0}})
        assert zero["max_dangling_seconds"] == 0
        # 合法值透传（整值浮点 90.0 按整数接受 90）
        passthrough = ConfigLoader.get_stale_code_selfheal_config(
            {"stale_code_selfheal": {"max_dangling_seconds": 90.0}})
        assert passthrough["max_dangling_seconds"] == 90
        # 非整值浮点回退缺省 14400（item 6a69eac80f8a：旧 int() 截断把正小数
        # 翻转成「0=关闭升级」语义，现与 _normalize_transient_seconds 同口径）
        default = ConfigLoader.STALE_CODE_SELFHEAL_MAX_DANGLING_SECONDS_DEFAULT
        noninteger = ConfigLoader.get_stale_code_selfheal_config(
            {"stale_code_selfheal": {"max_dangling_seconds": 90.7}})
        assert noninteger["max_dangling_seconds"] == default
        # 负值 / bool / 字符串 / None → 回退缺省 14400
        for bad in (-5, True, False, "快", None, [3600]):
            cfg = ConfigLoader.get_stale_code_selfheal_config(
                {"stale_code_selfheal": {"max_dangling_seconds": bad}})
            assert cfg["max_dangling_seconds"] == default, bad

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
            assert _panel_pair(eff["stale_code_selfheal"]) == {
                "enabled": False, "idle_confirm_seconds": 45}
            raw_view = dash_data.read_config(proot, scope="project")
            assert _panel_pair(raw_view["stale_code_selfheal"]) == {
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
            assert _panel_pair(eff2["stale_code_selfheal"]) == {
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
    assert _panel_pair(body["stale_code_selfheal"]) == {
        "enabled": True, "idle_confirm_seconds": 90}
    # 读回
    status, body = srv.get("/api/config?project=proj-a")
    assert status == 200
    assert _panel_pair(body["stale_code_selfheal"]) == {
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