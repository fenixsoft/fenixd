"""
evo-stale-selfheal-restart-cooldown 回归测试。

覆盖（与 tasks.md 一一对应）：
- Task 1.1：冷却五键缺省值与非法值回退（bool 陷阱 / 0 / 负数 / 字符串）
- Task 1.2：窗口内重启 ≥ 阈值进入冷却（不写 restart_request、清零 idle 计时、
  边沿落一条 stale_selfheal_cooldown 告警且不随 tick 重复堆积）；冷却锁存期内
  即使窗口计数因条目老化回落仍保持冷却，锁存期满后恢复触发
- Task 1.3：成功触发重启后追加 restart_history.jsonl；写失败仅记日志不阻断重启；
  tick 入口清理 24h 前旧条目
- Task 1.4：自触发型 stale 识别（仅 WARNING 不写 restart_request）、跨重启
  streak 持久化累计（阈值可达）并升 stale_selfheal_loop critical 告警、
  过期重启使 streak 归零
- Task 2.1：_is_idle 含 _running_agents 时判非空闲；缺 agent_runner 属性 /
  缺 _running_agents / 空字典时不抛异常且判为空闲

时间不做真实等待：历史条目的 ts 按需「拨老」（_age_history），idle 计时用
_stale_idle_since 回拨，与 tests/test_stale_code_selfheal.py 同款替身范式。
"""
import json
import shutil
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import fenixd as _fenixd_mod
import core.fenix_session as fenix_session
from core.admin_store import AdminStore
from core.config import ConfigLoader

HISTORY_REL = Path(".fenix") / "restart_history.jsonl"


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


class _DaemonParts:
    """未走 initialize 的 FenixDaemon 裸对象 + 注入测试部件（既有测试同款形态）。

    ``bare=True`` 时**不**设置 _cooldown_started_at / _self_triggered_cycle——
    复现「既有裸对象形态」，用于校验新代码对缺属性的容忍（不得抛 AttributeError）。
    """

    def __init__(self, proot: Path, bare: bool = False, agent_runner=None):
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
        daemon._code_stale = True
        daemon._code_files = []
        daemon._code_baseline_ns = 0
        daemon._stale_idle_since = None
        daemon._heal_block_reason = None
        if not bare:
            daemon._cooldown_started_at = None
            daemon._self_triggered_cycle = False
        if agent_runner is not None:
            daemon.agent_runner = agent_runner
        self.daemon = daemon

    def esca_signals(self):
        """admin_alerts.json 中 ESCALATION 记录的 (signal_type, severity) 列表。"""
        path = self.proot / ".fenix" / "admin_alerts.json"
        if not path.exists():
            return []
        recs = json.loads(path.read_text(encoding="utf-8"))
        return [(r.get("signal_type"), r.get("severity")) for r in recs
                if r.get("kind") == "escalation"]

    def signals(self, signal_type: str):
        """按 signal_type 过滤的 escalation 记录。"""
        path = self.proot / ".fenix" / "admin_alerts.json"
        if not path.exists():
            return []
        recs = json.loads(path.read_text(encoding="utf-8"))
        return [r for r in recs
                if r.get("kind") == "escalation" and r.get("signal_type") == signal_type]


class _Fixture(unittest.TestCase):
    """公共夹具：受管项目 + 陈旧为真 + 可拨动的重启历史。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)
        self.parts = _DaemonParts(self.proot)
        self.d = self.parts.daemon
        self.req = self.proot / ".fenix" / "restart_request"
        self.history = self.proot / HISTORY_REL
        self._mp_root = mock.patch.object(_fenixd_mod, "PROJECT_ROOT", self.proot)
        self._mp_root.start()
        self._mp_sup = mock.patch.object(
            fenix_session, "supervisor_running", return_value=True)
        self._mp_sup.start()
        self.cfg()  # 基线：idle_confirm_seconds=120（钉住触发节奏，见 _CFG_BASE）

    def tearDown(self):
        self._mp_sup.stop()
        self._mp_root.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ── 夹具辅助 ────────────────────────────────────────────────────

    # evo-reduce-stale-code-selfheal-noise：idle 缺省 120→600。本文件聚焦
    # cooldown/自触发/历史语义（idle 缺省本身由 test_stale_selfheal_idle.py
    # 与 test_stale_code_selfheal.py 覆盖），夹具显式钉住旧缺省 120s 保持
    # 既有触发节奏（130s 空闲可达阈值），不随缺省漂移。
    _CFG_BASE = {"idle_confirm_seconds": 120}

    def cfg(self, **overrides):
        """写入 stale_code_selfheal 配置（未覆盖键回退夹具基线）。"""
        base = dict(self._CFG_BASE)
        base.update(overrides)
        self.d.config = {"stale_code_selfheal": base}

    def plant_history(self, ages_seconds, streak=0, self_triggered=False):
        """按「距今多少秒」写入历史条目（ages_seconds 可为单个或多个）。"""
        if isinstance(ages_seconds, (int, float)):
            ages_seconds = [ages_seconds]
        now = time.time()
        lines = [json.dumps({
            "ts": _iso(now - age),
            "self_triggered": self_triggered,
            "self_triggered_streak": streak,
        }) for age in ages_seconds]
        self.history.parent.mkdir(parents=True, exist_ok=True)
        self.history.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def age_history(self, seconds):
        """把所有历史条目的 ts 拨到距今 seconds 秒前（模拟窗口过期）。"""
        recs = self.read_history()
        self._rewrite_history([seconds] * len(recs))

    def set_history_ages(self, ages):
        """按索引逐条设置历史条目的「距今多少秒」（模拟真实的周期分布）。"""
        recs = self.read_history()
        assert len(recs) == len(ages), (len(recs), ages)
        self._rewrite_history(ages)

    def _rewrite_history(self, ages):
        recs = self.read_history()
        now = time.time()
        self.history.write_text("".join(
            json.dumps({**r, "ts": _iso(now - age)}) + "\n"
            for r, age in zip(recs, ages)), encoding="utf-8")

    def read_history(self):
        """磁盘上的历史记录（可解析 JSON 的行；损坏行原样跳过）。"""
        if not self.history.exists():
            return []
        recs = []
        for line in self.history.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                recs.append(json.loads(line))
            except ValueError:
                continue
        return recs

    def raw_history_line_count(self) -> int:
        """文件原始非空行数（含损坏行）。"""
        if not self.history.exists():
            return 0
        return len([ln for ln in
                    self.history.read_text(encoding="utf-8").splitlines() if ln.strip()])

    def tick(self, idle_seconds=None):
        """跑一次自愈 tick；idle_seconds 非空时先把 idle 起点回拨。"""
        if idle_seconds is not None:
            self.d._stale_idle_since = time.time() - idle_seconds
        self.d._maybe_stale_selfheal_tick()

    def warnings_text(self) -> str:
        return " ".join(str(c) for c in self.d.logger.warning.call_args_list)

    def infos_text(self) -> str:
        return " ".join(str(c) for c in self.d.logger.info.call_args_list)


# ── 1.1 配置键 ─────────────────────────────────────────────────────

class TestCooldownConfigKeys(unittest.TestCase):
    DEFAULTS = {
        "cooldown_window_seconds": 1800,
        "cooldown_threshold": 3,
        "cooldown_duration_seconds": 600,
        "self_triggered_window_seconds": 300,
        "self_triggered_threshold": 3,
    }

    def test_defaults_present_when_section_missing(self):
        """节缺失 → 冷却五键缺省生效。"""
        cfg = ConfigLoader.get_stale_code_selfheal_config({})
        for key, expected in self.DEFAULTS.items():
            assert cfg[key] == expected, (key, cfg)

    def test_legal_values_passthrough(self):
        """合法整数值透传（整值浮点 30.0 按整数接受；非整值浮点回退缺省，
        code-review item 2460e8a27c5d）。"""
        cfg = ConfigLoader.get_stale_code_selfheal_config({
            "stale_code_selfheal": {
                "cooldown_window_seconds": 60,
                "cooldown_threshold": 1,
                "cooldown_duration_seconds": 30.0,
                "self_triggered_window_seconds": 10,
                "self_triggered_threshold": 2,
            }
        })
        assert cfg["cooldown_window_seconds"] == 60
        assert cfg["cooldown_threshold"] == 1
        assert cfg["cooldown_duration_seconds"] == 30
        assert cfg["self_triggered_window_seconds"] == 10
        assert cfg["self_triggered_threshold"] == 2

    def test_bool_trap_and_non_positive_fallback(self):
        """bool 陷阱 / 0 / 负数 / 字符串 / None / 非整值浮点一律回退缺省，
        不抛异常（非整值浮点口径见 code-review item 2460e8a27c5d）。

        `0` **不等效关闭**（与 idle_confirm_seconds 一致：冷却无独立开关，
        整体关闭走 enabled: false）。
        """
        bad_values = [True, False, 0, -1, "60", None, [], {}, 30.7]
        for key, default in self.DEFAULTS.items():
            for value in bad_values:
                cfg = ConfigLoader.get_stale_code_selfheal_config(
                    {"stale_code_selfheal": {key: value}})
                assert cfg[key] == default, (key, value, cfg)
                assert isinstance(cfg[key], int) and not isinstance(cfg[key], bool)

    def test_non_dict_section_no_raise(self):
        """节非 dict → 全部缺省，不抛异常。"""
        cfg = ConfigLoader.get_stale_code_selfheal_config(
            {"stale_code_selfheal": "not-a-dict"})
        for key, expected in self.DEFAULTS.items():
            assert cfg[key] == expected


# ── 1.2 冷却：窗口计数 + 锁存 ──────────────────────────────────────

class TestCooldownWindow(_Fixture):
    def test_window_count_below_threshold_triggers_restart(self):
        """窗口内重启数 < 阈值 → 照常触发重启，并落一条历史。"""
        self.plant_history([120, 600])  # 2 条 < 阈值 3
        self.tick(idle_seconds=130)
        assert self.req.exists(), "未达阈值不应进入冷却"
        assert self.read_history()[-1]["self_triggered_streak"] == 0
        assert self.parts.esca_signals() == []

    def test_window_count_at_threshold_enters_cooldown(self):
        """窗口内重启数 ≥ 阈值 → 不触发、清零 idle、边沿落 stale_selfheal_cooldown。"""
        self.plant_history([60, 120, 180])  # 3 条 = 阈值（窗口 1800）
        self.tick(idle_seconds=300)
        assert not self.req.exists(), "冷却中不得写 restart_request"
        assert self.d._stale_idle_since is None, "冷却须清零 idle 计时"
        assert self.d._cooldown_started_at is not None
        sigs = self.parts.signals("stale_selfheal_cooldown")
        assert len(sigs) == 1, sigs
        assert sigs[0]["severity"] == "warning"
        assert "冷却" in sigs[0]["description"]
        assert "冷却" in self.infos_text()

    def test_cooldown_alert_is_edge_only(self):
        """冷却告警按边沿落一次：持续冷却的多轮 tick 不重复堆积。"""
        self.plant_history([60, 120, 180])
        for _ in range(5):
            self.tick(idle_seconds=300)
        assert len(self.parts.signals("stale_selfheal_cooldown")) == 1

    def test_entries_outside_window_not_counted(self):
        """窗口外（老化）条目不计入窗口计数 → 不进入冷却。"""
        self.plant_history([2000, 2200, 2400])  # 均 > 1800s 窗口
        self.tick(idle_seconds=130)
        assert self.req.exists()
        assert self.parts.signals("stale_selfheal_cooldown") == []

    def test_latch_holds_after_window_count_drops(self):
        """锁存：窗口计数因条目老化回落仍保持冷却（「冷却持续 10 分钟」成立）。"""
        self.plant_history([60, 120, 180])
        self.tick(idle_seconds=300)
        assert self.d._cooldown_started_at is not None
        assert not self.req.exists()
        # 历史被清空 → 窗口计数回落至 0，但锁存未到期
        self.history.write_text("", encoding="utf-8")
        self.tick(idle_seconds=300)
        assert not self.req.exists(), "锁存未到期不得因窗口计数回落而退出冷却"

    def test_latch_expiry_restores_trigger(self):
        """锁存期满（且窗口计数 < 阈值）→ 退出冷却，恢复正常触发。"""
        self.plant_history([60, 120, 180])
        self.tick(idle_seconds=300)
        self.history.write_text("", encoding="utf-8")
        self.d._cooldown_started_at = time.time() - 601  # 600s 锁存已过期
        self.tick(idle_seconds=130)
        assert self.req.exists(), "锁存期满后应恢复触发"
        assert self.d._cooldown_started_at is None

    def test_cooldown_does_not_fire_when_disabled(self):
        """enabled: false → 冷却逻辑不参与（阻断原因为 disabled，不落冷却告警）。"""
        self.cfg(enabled=False)
        self.plant_history([60, 120, 180])
        self.tick(idle_seconds=300)
        assert not self.req.exists()
        assert self.parts.signals("stale_selfheal_cooldown") == []
        assert "已被配置关闭" in self.infos_text()

    def test_cooldown_reentry_after_expiry_alerts_again(self):
        """冷却退出后再次进入 → 重新按边沿告警（不是一次性闩锁）。"""
        self.plant_history([60, 120, 180])
        self.tick(idle_seconds=300)
        self.history.write_text("", encoding="utf-8")
        self.d._cooldown_started_at = time.time() - 601
        self.tick(idle_seconds=130)  # 退出冷却并触发重启（历史新增一条）
        assert self.req.exists()
        self.req.unlink()
        self.plant_history([10, 20, 30])
        self.d._stale_idle_since = None
        self.tick(idle_seconds=300)
        assert not self.req.exists()
        assert len(self.parts.signals("stale_selfheal_cooldown")) == 2


# ── 1.3 重启历史持久化与清理 ──────────────────────────────────────

class TestRestartHistory(_Fixture):
    def test_restart_appends_history_entry(self):
        """成功触发重启后追加一条 {ts, self_triggered, self_triggered_streak}。"""
        self.tick(idle_seconds=130)
        assert self.req.exists()
        recs = self.read_history()
        assert len(recs) == 1
        rec = recs[0]
        assert set(rec) == {"ts", "self_triggered", "self_triggered_streak"}
        assert rec["self_triggered"] is False
        assert rec["self_triggered_streak"] == 0
        parsed = datetime.fromisoformat(rec["ts"])
        assert abs(parsed.timestamp() - time.time()) < 60

    def test_no_history_written_when_not_triggered(self):
        """未达 idle 阈值 / 冷却中 / 非空闲 → 不写历史。"""
        self.tick(idle_seconds=60)  # 未达阈值
        assert self.read_history() == []
        self.d.pm_engine._active_runs = 1
        self.tick(idle_seconds=300)
        assert self.read_history() == []

    def test_history_write_failure_is_non_blocking(self):
        """历史写失败（路径被目录占用）不阻断重启：restart_request 仍写入。"""
        self.history.mkdir(parents=True, exist_ok=True)  # 目录占位 → open('a') OSError
        self.tick(idle_seconds=130)
        assert self.req.exists(), "历史写失败不得阻断重启"
        assert "restart_history 追加失败" in self.warnings_text()

    def test_missing_and_corrupt_history_tolerated(self):
        """文件缺失 → 按空；行损坏 / 非对象行 / ts 不可解析 / streak 非法 → 该条/该字段忽略。"""
        self.history.unlink(missing_ok=True)
        assert self.d._read_restart_history(time.time()) == []
        self.history.write_text(
            "{\"ts\": \"not-a-ts\"}\n"
            "not-json\n"
            "[1, 2, 3]\n"
            "\n"
            "{\"ts\": \"%s\", \"self_triggered_streak\": \"x\"}\n" % _iso(time.time() - 600),
            encoding="utf-8")
        entries = self.d._read_restart_history(time.time())
        assert len(entries) == 1, entries
        assert entries[0]["self_triggered_streak"] == 0, "非法 streak 按 0 忽略"
        # 损坏行不阻断自愈：照常触发重启并追加一条
        self.tick(idle_seconds=130)
        assert self.req.exists()
        assert self.raw_history_line_count() == 5, "损坏行按该条忽略，但不主动修复文件"

    def test_prunes_entries_older_than_24h(self):
        """tick 入口清理 24h 前的旧条目（文件被重写，只留新鲜条目）。"""
        self.history.write_text(
            json.dumps({"ts": _iso(time.time() - 25 * 3600),
                        "self_triggered": False,
                        "self_triggered_streak": 2}) + "\n"
            + json.dumps({"ts": _iso(time.time() - 60),
                          "self_triggered": False,
                          "self_triggered_streak": 1}) + "\n",
            encoding="utf-8")
        self.tick(idle_seconds=60)  # 未达阈值即可触发清理
        recs = self.read_history()
        assert len(recs) == 1, recs
        assert recs[0]["self_triggered_streak"] == 1


# ── 1.4 自触发型 stale 与 streak 升级 ──────────────────────────────

class TestSelfTriggeredStale(_Fixture):
    def setUp(self):
        super().setUp()
        # 冷却阈值抬高：本组聚焦自触发语义，不让窗口计数提前介入
        self.cfg(idle_confirm_seconds=120, cooldown_threshold=99,
                 cooldown_window_seconds=1800,
                 self_triggered_window_seconds=300,
                 self_triggered_threshold=3)

    def test_within_window_only_warns_no_restart(self):
        """距上次重启 < 自触发窗口 → 只记 WARNING、不写 restart_request。"""
        self.plant_history([100])
        self.tick(idle_seconds=130)
        assert not self.req.exists(), "自触发窗口内不得触发重启"
        assert self.d._self_triggered_cycle is True
        warns = self.warnings_text()
        assert "自触发型陈旧" in warns
        assert "陈旧自愈触发" not in warns
        assert len(self.read_history()) == 1, "抑制周期不追加历史记录"

    def test_warning_logged_once_per_cycle(self):
        """同一重启周期内多次 tick 只落一次 WARNING。"""
        self.plant_history([100])
        for _ in range(4):
            self.tick(idle_seconds=130)
        assert self.warnings_text().count("自触发型陈旧") == 1

    def test_expired_window_triggers_and_marks_self_triggered(self):
        """窗口过期后的收尾重启：落历史 self_triggered=True、streak 累计 +1。"""
        self.plant_history([100], streak=0)
        self.tick(idle_seconds=130)          # 窗口内 → 抑制（本周期标记自触发）
        assert not self.req.exists()
        assert self.d._self_triggered_cycle is True
        self.age_history(400)                # 窗口过期
        self.tick(idle_seconds=130)          # 周期收尾重启
        assert self.req.exists()
        rec = self.read_history()[-1]
        assert rec["self_triggered"] is True
        assert rec["self_triggered_streak"] == 1
        assert self.d._self_triggered_cycle is False

    def test_streak_reaches_threshold_across_cycles(self):
        """跨重启循环 streak 可达阈值 → 升 stale_selfheal_loop critical 告警。

        每个周期：窗口内再判可触发（抑制）→ 窗口过期收尾重启（streak +1）。
        计数持久化在 restart_history.jsonl，故跨进程（新 daemon 对象）累计可达。
        """
        self.plant_history([100], streak=0)
        for _ in range(3):
            self.tick(idle_seconds=130)          # 窗口内 → 抑制，标记自触发
            assert not self.req.exists()
            self.age_history(400)                # 窗口过期
            self.tick(idle_seconds=130)          # 收尾重启
            assert self.req.exists()
            self.req.unlink()
        recs = self.read_history()
        assert [r["self_triggered_streak"] for r in recs] == [0, 1, 2, 3], recs
        assert all(r["self_triggered"] for r in recs[1:]), recs
        loops = self.parts.signals("stale_selfheal_loop")
        assert len(loops) == 1, loops
        assert loops[0]["severity"] == "critical"
        assert "自触发" in loops[0]["description"]

    def test_streak_not_alerted_below_threshold(self):
        """streak 未达阈值不落 critical 告警（1 < 3）。"""
        self.plant_history([100], streak=0)
        self.tick(idle_seconds=130)      # 抑制
        self.age_history(400)
        self.tick(idle_seconds=130)      # streak = 1 < 3
        assert self.read_history()[-1]["self_triggered_streak"] == 1
        assert self.parts.signals("stale_selfheal_loop") == []

    def test_expired_restart_resets_streak(self):
        """过期重启（非自触发周期）使 streak 归零——循环已断。"""
        self.plant_history([4000], streak=2)
        self.tick(idle_seconds=130)
        assert self.req.exists()
        rec = self.read_history()[-1]
        assert rec["self_triggered"] is False
        assert rec["self_triggered_streak"] == 0

    def test_no_history_no_suppression(self):
        """无历史（首次触发）→ 不受自触发窗口抑制。"""
        self.tick(idle_seconds=130)
        assert self.req.exists()
        assert "自触发型陈旧" not in self.warnings_text()

    def test_threshold_reachable_with_shipped_defaults(self):
        """缺省配置（cooldown_threshold=3 == self_triggered_threshold=3）下 streak 仍可达阈值。

        回归 ocr 评审发现：自触发标记若晚于冷却早退，窗口计数达冷却阈值后永远到不了
        标记分支，streak 上限 = cooldown_threshold - 1（= 2 < 3），stale_selfheal_loop
        critical 告警在缺省配置下永不触发。本用例按真实周期分布（每次重启后先在窗口内
        标记，随后窗口过期收尾）逐周期推进，冷却介入后仍须可达 streak = 3。
        """
        self.cfg()  # 全缺省：cooldown 1800/3/600，self_triggered 300/3
        # R1：无历史 → 首次重启，streak 0
        self.tick(idle_seconds=130)
        assert self.req.exists()
        self.req.unlink()
        assert self.read_history()[-1]["self_triggered_streak"] == 0
        # R2：重启后陈旧再现（窗口内）→ 标记自触发；窗口过期 → 收尾重启，streak 1
        self.tick()
        assert self.d._self_triggered_cycle is True
        self.age_history(301)
        self.tick(idle_seconds=130)
        assert self.req.exists()
        self.req.unlink()
        assert self.read_history()[-1]["self_triggered_streak"] == 1
        # R3：同上，streak 2（历史 3 条，窗口计数已到冷却阈值）
        self.tick()
        self.set_history_ages([602, 301])
        self.tick(idle_seconds=130)
        assert self.req.exists()
        self.req.unlink()
        assert self.read_history()[-1]["self_triggered_streak"] == 2
        # 冷却介入：3 条窗口内重启 → 不触发，且此前标记的自触发周期仍然有效
        self.tick()
        self.set_history_ages([903, 602, 301])
        self.tick(idle_seconds=130)
        assert not self.req.exists(), "窗口计数达阈值应进入冷却"
        assert len(self.parts.signals("stale_selfheal_cooldown")) == 1
        assert self.d._self_triggered_cycle is True, "冷却早退不得吞掉自触发周期标记"
        # 冷却锁存到期 + 窗口条目老化到阈值之下 → 收尾重启 → streak 3 → critical
        self.set_history_ages([1901, 1600, 1200])
        self.d._cooldown_started_at = time.time() - 601
        self.tick(idle_seconds=130)
        assert self.req.exists()
        rec = self.read_history()[-1]
        assert rec["self_triggered_streak"] == 3, rec
        assert rec["self_triggered"] is True
        loops = self.parts.signals("stale_selfheal_loop")
        assert len(loops) == 1, loops
        assert loops[0]["severity"] == "critical"

    def test_stale_release_resets_cycle_flag(self):
        """陈旧解除 → 自触发周期标记复位，不污染下一个陈旧周期。"""
        self.plant_history([100])
        self.tick(idle_seconds=130)
        assert self.d._self_triggered_cycle is True
        self.d._code_stale = False
        self.d._maybe_stale_selfheal_tick()
        assert self.d._self_triggered_cycle is False


# ── 2.1 _is_idle 补全 ──────────────────────────────────────────────

class _FakeAgentRunner:
    """最小替身：只带 _running_agents 属性（无需真实 AgentRunner）。"""

    def __init__(self, running=None):
        if running is not None:
            self._running_agents = running


class TestIsIdleWithRunningAgents(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _daemon(self, agent_runner="absent", bare=False, **kwargs):
        parts = _DaemonParts(self.proot, bare=bare, **kwargs)
        if agent_runner != "absent":
            parts.daemon.agent_runner = agent_runner
        return parts.daemon

    def test_running_agents_means_not_idle(self):
        """_running_agents 非空 → 非空闲（评审 run 只在此维度可见）。"""
        for running in ({"run-1": object()}, {"run-1": object(), "run-2": object()}):
            d = self._daemon(_FakeAgentRunner(running))
            assert d._is_idle() is False, running

    def test_empty_running_agents_is_idle(self):
        """_running_agents 为空 dict → 该维度视为空闲。"""
        d = self._daemon(_FakeAgentRunner({}))
        assert d._is_idle() is True

    def test_missing_attribute_is_idle_no_raise(self):
        """裸对象缺 agent_runner / agent_runner 缺 _running_agents → 判空闲且不抛异常。"""
        assert self._daemon("absent")._is_idle() is True
        assert self._daemon(_FakeAgentRunner())._is_idle() is True
        assert self._daemon(None)._is_idle() is True

    def test_bare_object_without_new_state_attrs_tolerated(self):
        """缺 _cooldown_started_at / _self_triggered_cycle 的裸对象：tick 不抛异常。"""
        d = self._daemon("absent", bare=True)
        # 本类不走 _Fixture（无 self.d/cfg 基线）：显式钉 idle 120s 保持
        # 既有触发节奏（缺省已提额 600，见 _CFG_BASE 注）
        d.config = {"stale_code_selfheal": {"idle_confirm_seconds": 120}}
        with mock.patch.object(_fenixd_mod, "PROJECT_ROOT", self.proot), \
                mock.patch.object(fenix_session, "supervisor_running", return_value=True):
            d._maybe_stale_selfheal_tick()  # 只开始计时，不触发
            d._stale_idle_since = time.time() - 130
            d._maybe_stale_selfheal_tick()
        assert (self.proot / ".fenix" / "restart_request").exists()

    def test_running_agents_blocks_tick_trigger(self):
        """在飞评审 run 期间 tick 不触发重启，且清零 idle 计时。"""
        parts = _DaemonParts(self.proot, agent_runner=_FakeAgentRunner({"r1": object()}))
        d = parts.daemon
        with mock.patch.object(_fenixd_mod, "PROJECT_ROOT", self.proot), \
                mock.patch.object(fenix_session, "supervisor_running", return_value=True):
            d._stale_idle_since = time.time() - 300
            d._maybe_stale_selfheal_tick()
        assert not (self.proot / ".fenix" / "restart_request").exists()
        assert d._stale_idle_since is None


if __name__ == "__main__":
    unittest.main()
