"""evo-stale-selfheal-restart-coalescing 回归测试。

覆盖（与 tasks.md 一一对应）：
- Task 2.1：首启陈旧按 600s 基础闸重启（同时开启合流期）；基础闸重启后
  静止期内第二批边沿按 1800s 合流闸（10-18 形态：批间隔 20-28 分钟、各批
  落于上批重启后 1800s 内）；末批后连续空闲达 1800s 收敛为一次重启；悬置
  消化且静止期届满后合流复位（下次陈旧重回基础闸）；preflight 请求通道
  不受合流闸延迟；悬空满 4h 强转兜底仍生效（含持续连发下合流闸不满足由
  强转收尾）。
- Task 2.2：配置键项目级覆盖缺省值；合流等待日志留痕字段（边沿序号与
  闸值）；restart_history 幂等推导（进程更替后内存态丢失：记录在窗内
  延续合流态、超窗/无记录回退基础闸）。

时间不做真实等待：历史条目 ts 按需拨老（age_history / plant_history），
idle 计时用 _stale_idle_since 回拨，合流静止期参考时刻直接拨内存属性——
与 tests/test_stale_selfheal_cooldown.py 同款替身范式。「进程更替致内存
合流态丢失」以新建裸 daemon 对象（不携任何 _coalesce_* 属性）模拟。
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
import core.code_stale_flag as code_stale_flag
import core.fenix_session as fenix_session
from core.admin_store import AdminStore
from core.config import ConfigLoader

HISTORY_REL = Path(".fenix") / "restart_history.jsonl"


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


class _Fixture(unittest.TestCase):
    """公共夹具：受管项目 + 陈旧为真 + 可拨动的重启历史与内存合流态。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)
        (self.proot / ".fenix").mkdir(parents=True, exist_ok=True)
        self.d = self._new_daemon()
        self.req = self.proot / ".fenix" / "restart_request"
        self.history = self.proot / HISTORY_REL
        self._mp_root = mock.patch.object(_fenixd_mod, "PROJECT_ROOT", self.proot)
        self._mp_root.start()
        self._mp_sup = mock.patch.object(
            fenix_session, "supervisor_running", return_value=True)
        self._mp_sup.start()

    def tearDown(self):
        self._mp_sup.stop()
        self._mp_root.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ── 夹具辅助 ────────────────────────────────────────────────

    def _new_daemon(self, config=None):
        """未走 initialize 的裸 daemon：不携任何 _coalesce_* 内存合流态。

        「进程更替」场景以本构造模拟——新进程只有磁盘事实（restart_history），
        合流态须由 _coalesce_derive_from_history 幂等推导恢复。
        """
        daemon = _fenixd_mod.FenixDaemon.__new__(_fenixd_mod.FenixDaemon)
        daemon.config = config if config is not None else {}
        daemon.logger = mock.MagicMock()
        daemon.admin_store = AdminStore(self.proot, daemon.logger)
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
        daemon._cooldown_started_at = None
        daemon._self_triggered_cycle = False
        return daemon

    def cfg(self, **overrides):
        """写入 stale_code_selfheal 配置（基线 = 两闸缺省，覆盖键按需传入）。"""
        base = {"idle_confirm_seconds": 600}
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
        """把所有历史条目的 ts 拨到距今 seconds 秒前（模拟时间推进）。"""
        recs = self.read_history()
        now = time.time()
        self.history.write_text("".join(
            json.dumps({**r, "ts": _iso(now - seconds)}) + "\n"
            for r in recs), encoding="utf-8")

    def read_history(self):
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

    def tick(self, idle_seconds=None):
        """跑一次自愈 tick；idle_seconds 非空时先把 idle 起点回拨。"""
        if idle_seconds is not None:
            self.d._stale_idle_since = time.time() - idle_seconds
        self.d._maybe_stale_selfheal_tick()

    def warnings_text(self) -> str:
        return " ".join(str(c) for c in self.d.logger.warning.call_args_list)

    def infos_text(self) -> str:
        return " ".join(str(c) for c in self.d.logger.info.call_args_list)


# ── Task 2.1：合流行为场景 ─────────────────────────────────────────

class TestFirstStaleUsesBaseGate(_Fixture):
    def test_first_startup_stale_triggers_at_base_gate(self):
        """首启陈旧按 600s 基础闸重启，同时开启合流期（记录最近重启时刻）。"""
        self.cfg()  # 两闸缺省：600 / 1800
        self.tick(idle_seconds=599)
        assert not self.req.exists(), "首个陈旧边沿按基础闸确认，599s 不得提前触发"
        assert self.d._coalesce_edge_count == 1, "首个边沿开启合流期"
        self.tick(idle_seconds=600)
        assert self.req.exists(), "连续空闲达基础闸 600s 后触发重启"
        assert len(self.read_history()) == 1
        assert self.d._coalesce_last_restart_ts is not None, (
            "按闸重启须记录最近重启时刻（合流静止期参考）")

    def test_first_edge_not_retriggered_by_stale_continuation(self):
        """陈旧持续为真不产生新边沿：闸值保持基础闸，不逐 tick 递增。"""
        self.cfg()
        for waited in (100, 300, 599):
            self.tick(idle_seconds=waited)
            assert self.d._coalesce_edge_count == 1
            assert not self.req.exists()
        self.tick(idle_seconds=600)
        assert self.req.exists()


class TestCoalesceGateAfterRestart(_Fixture):
    def test_second_batch_edge_uses_coalesce_gate_1018_shape(self):
        """10-18 形态：基础闸重启后，静止期内第二批（距上批重启 20 分钟）
        边沿按 1800s 合流闸；第三批落于等待窗内被同一轮吸收；末批后连续
        空闲达 1800s 收敛为一次重启（三批连发只两轮重启）。"""
        self.cfg()
        # R1：首批 → 基础闸 600s 重启
        self.tick(idle_seconds=600)
        assert self.req.exists()
        self.req.unlink()
        # 进程更替：新进程 baseline 刷新 → 悬置消化；restart_history 在
        # 静止窗内 → 幂等延续合流态
        self.d = self._new_daemon(self.d.config)
        self.d._code_stale = False
        self.tick()
        assert self.d._coalesce_edge_count == 1, "窗内重启记录须延续合流态"
        assert self.d._coalesce_last_restart_ts is not None
        # 第二批：距上批重启 1200s（< 1800s，10-18 实测 9-17 分钟量级）
        self.age_history(1200)
        self.d._code_stale = True
        self.tick()
        assert self.d._coalesce_edge_count == 2, "静止期内再检出边沿须计数"
        # 合流闸 1800s：600s 空闲不得触发（基础闸下早已触发——10-18 五连
        # 重启的病根即在此回退）
        self.tick(idle_seconds=600)
        assert not self.req.exists(), "合流期内后续边沿 MUST NOT 回退基础闸"
        # 第三批落于等待窗内：stale 持续为真（无新边沿）、空闲不清零 → 吸收
        self.tick(idle_seconds=1200)
        assert not self.req.exists()
        # 末批后连续空闲达 1800s → 收敛为一次重启
        self.tick(idle_seconds=1800)
        assert self.req.exists(), "末批后空闲达合流闸须收敛触发"
        assert len(self.read_history()) == 2, (
            f"三批连发只应两轮重启（首批+合流收敛轮），实际 {len(self.read_history())} 条")


class TestCoalesceReset(_Fixture):
    def test_resolved_and_quiescence_expired_resets_to_base_gate(self):
        """悬置消化且静止期届满后合流复位：下次陈旧重回基础闸。"""
        self.cfg()
        # 开启合流期：首轮基础闸重启 + 第二批边沿（count=2，合流闸生效）
        self.tick(idle_seconds=600)
        self.req.unlink()
        self.d._code_stale = False  # 重启后 baseline 刷新 → 悬置消化
        self.tick()
        assert self.d._coalesce_edge_count == 1, "按闸重启导致的消化不复位合流态"
        self.d._code_stale = True
        self.tick()
        assert self.d._coalesce_edge_count == 2
        # 悬置消化（代码回退）但静止期未届满 → 合流态保留
        self.d._code_stale = False
        self.tick()
        assert self.d._coalesce_edge_count == 2, "静止期未届满不得复位"
        # 静止期届满（距最近边沿/重启达 1800s 无新边沿）→ 复位
        self.d._coalesce_last_edge_ts = time.time() - 1801
        self.d._coalesce_last_restart_ts = time.time() - 1801
        self.tick()
        assert self.d._coalesce_edge_count == 0, "消化且静止期届满须复位合流态"
        assert self.d._coalesce_last_restart_ts is None
        assert "合流期复位" in self.infos_text()
        # 下一次陈旧重新按基础闸确认
        self.age_history(1900)  # 拨老历史：排除自触发窗/冷却对收尾闸 tick 的干扰
        self.d._code_stale = True
        self.tick(idle_seconds=599)
        assert not self.req.exists(), "复位后首个边沿须按基础闸 600s 确认"
        self.tick(idle_seconds=600)
        assert self.req.exists(), "复位后首个陈旧重回基础闸触发"


class TestPreflightBypass(_Fixture):
    def test_request_restart_not_delayed_by_coalesce_gate(self):
        """关键路径 preflight 显式请求重启（request_restart）按既有语义立即
        执行，不受合流闸延迟。"""
        self.cfg()
        self.plant_history(400)  # 静止窗内（< 1800）→ 推导延续合流态
        self.tick()  # 边沿 2 → 合流闸
        assert self.d._coalesce_edge_count == 2
        self.tick(idle_seconds=600)
        assert not self.req.exists(), "前置：合流闸等待中自愈 600s 空闲不得触发"
        # 关键路径 preflight 请求重启 → 立即成写
        with mock.patch.object(code_stale_flag, "RESTART_REQUEST", self.req):
            code_stale_flag.register(lambda: True)
            try:
                wrote = code_stale_flag.request_restart(lambda msg: None, "unit-test")
            finally:
                code_stale_flag.unregister()
        assert wrote is True
        assert self.req.exists(), "preflight 请求 MUST NOT 被合流闸延迟"
        # 后续自愈 tick 识别 in-flight，不重复写入、不产生第二轮重启
        before = self.req.stat().st_mtime_ns
        self.tick(idle_seconds=1800)
        assert self.req.stat().st_mtime_ns == before, "请求已在场不得重复写入"
        assert len(self.read_history()) == 1, "preflight 旁路不产生自愈重启历史"


class TestDanglingForceBypassesCoalesce(_Fixture):
    def test_dangling_timeout_wins_over_coalesce_gate(self):
        """合流闸等待中悬空满 4h → 按既有强转逻辑立即重启，合流闸不得拦截。"""
        self.cfg()
        self.plant_history(400)
        self.tick()  # count=2 → 合流闸 1800
        self.tick(idle_seconds=600)
        assert not self.req.exists(), "前置：合流闸等待中"
        self.d._code_stale_since = (
            datetime.now(timezone.utc) - timedelta(seconds=14401))
        self.tick()
        assert self.req.exists(), "4h 悬空强转优先于合流闸"
        assert "悬空超时触发" in self.warnings_text()

    def test_continuous_batching_ends_in_dangling_force(self):
        """持续连发（批间隔恒 < 合流闸）下合流闸持续不满足 → 由 4h 强转收尾
        （修复生效延迟的绝对上界是 max_dangling_seconds）。"""
        self.cfg()
        self.plant_history(400)
        self.tick()  # 合流闸生效
        for waited in (600, 1200, 1700):
            self.tick(idle_seconds=waited)
            assert not self.req.exists(), (
                f"合流闸未满足（{waited}s < 1800s）不得重启")
        # 悬空时长达 4h（首边沿起算）→ 强转兜底
        self.d._code_stale_since = (
            datetime.now(timezone.utc) - timedelta(seconds=14401))
        self.tick(idle_seconds=1700)
        assert self.req.exists(), "合流闸不满足时由悬空强转兜底收尾"


# ── Task 2.2：配置覆盖 / 日志留痕 / 幂等推导 ───────────────────────

class TestCoalesceConfigKey(unittest.TestCase):
    def test_default_1800_and_project_override(self):
        """缺省 1800；项目级显式覆盖优先（沿用 idle_confirm_seconds 覆盖模式）。"""
        assert ConfigLoader.STALE_CODE_SELFHEAL_COALESCE_IDLE_SECONDS_DEFAULT == 1800
        assert ConfigLoader.get_stale_code_selfheal_config({})[
            "coalesce_idle_seconds"] == 1800
        cfg = ConfigLoader.get_stale_code_selfheal_config(
            {"stale_code_selfheal": {"coalesce_idle_seconds": 900}})
        assert cfg["coalesce_idle_seconds"] == 900

    def test_invalid_values_fallback_default(self):
        """bool 陷阱 / 0 / 负数 / 字符串 / None / 非整值浮点一律回退缺省
        （0 不等效关闭，与 idle_confirm_seconds 同口径）。"""
        for bad in (0, -1, True, False, "x", None, [], {}, 30.7):
            cfg = ConfigLoader.get_stale_code_selfheal_config(
                {"stale_code_selfheal": {"coalesce_idle_seconds": bad}})
            value = cfg["coalesce_idle_seconds"]
            assert value == 1800 and isinstance(value, int) \
                and not isinstance(value, bool), (bad, cfg)

    def test_non_dict_section_no_raise(self):
        """节非 dict → 缺省，不抛异常。"""
        cfg = ConfigLoader.get_stale_code_selfheal_config(
            {"stale_code_selfheal": "not-a-dict"})
        assert cfg["coalesce_idle_seconds"] == 1800


class TestProjectOverrideBehavior(_Fixture):
    def test_override_900_shrinks_coalesce_gate(self):
        """项目级覆盖 900s：第二批边沿按 900s 合流闸等待（非缺省 1800）。"""
        self.cfg(coalesce_idle_seconds=900)
        self.plant_history(400)
        self.tick()  # count=2 → 合流闸 900
        assert self.d._coalesce_edge_count == 2
        self.tick(idle_seconds=899)
        assert not self.req.exists()
        self.tick(idle_seconds=900)
        assert self.req.exists(), "项目级覆盖合流闸 900s 必须生效"


class TestEdgeAndConvergenceLogs(_Fixture):
    def test_edge_log_records_ordinal_and_gate(self):
        """合流等待日志留痕：每次边沿记 info（第 N 次边沿、当前生效闸值）。"""
        self.cfg()
        self.tick(idle_seconds=10)  # 边沿 1：闸值 600（基础闸）
        self.d._code_stale = False
        self.tick()
        self.d._code_stale = True
        self.tick()  # 边沿 2：闸值 1800（合流闸）
        infos = self.infos_text()
        assert "stale coalesce" in infos
        assert "第 1 次边沿" in infos and "600" in infos
        assert "第 2 次边沿" in infos and "1800" in infos

    def test_edge_not_relogged_without_transition(self):
        """陈旧持续为真不重记边沿日志（每次边沿恰一条，不逐 tick 刷屏）。"""
        self.cfg()
        for _ in range(3):
            self.tick(idle_seconds=100)
        assert self.infos_text().count("第 1 次边沿") == 1
        assert "第 2 次边沿" not in self.infos_text()

    def test_convergence_log_on_coalesced_restart(self):
        """执行重启时记合流收敛结果：本周期共 N 次边沿、合并为 1 次重启。"""
        self.cfg()
        self.plant_history(400)
        self.tick()  # count=2 → 合流闸
        self.tick(idle_seconds=1800)
        assert self.req.exists()
        warns = self.warnings_text()
        assert "合流收敛" in warns
        assert "共 2 次陈旧边沿" in warns
        assert "合并为 1 次重启" in warns


class TestRestartHistoryDerivation(_Fixture):
    def test_recent_record_continues_coalesce_after_process_replacement(self):
        """重启后进程更替、内存合流态丢失：restart_history 最近记录在静止窗
        内 → 新进程把该窗内新边沿按合流闸处理（不回退基础闸）。"""
        self.cfg()
        self.plant_history(400)  # 400s 前按闸自愈重启（< 1800s 窗内）
        self.d = self._new_daemon(self.d.config)  # 进程更替：内存态丢失
        self.d._code_stale = False  # 新 baseline → 悬置消化
        self.tick()  # 消化期 tick：推导生效
        assert self.d._coalesce_edge_count == 1, "窗内记录须推导延续合流态"
        assert self.d._coalesce_last_restart_ts is not None
        self.d._code_stale = True
        self.tick()  # 窗内新边沿 → count=2 → 合流闸
        assert self.d._coalesce_edge_count == 2
        self.tick(idle_seconds=600)
        assert not self.req.exists(), "窗内记录须把新边沿按合流闸处理（不回退 600s）"
        self.tick(idle_seconds=1800)
        assert self.req.exists(), "合流闸满足后照常收敛重启"

    def test_aged_record_falls_back_to_base_gate(self):
        """记录超窗（> coalesce_idle_seconds）→ 按新周期基础闸（防把陈旧重启
        史误算进当前合流期）。"""
        self.cfg()
        self.plant_history(1900)
        self.d = self._new_daemon(self.d.config)
        self.tick(idle_seconds=600)
        assert self.req.exists(), "超窗记录不得延续合流态，首个边沿按基础闸触发"
        assert self.d._coalesce_edge_count == 1

    def test_no_record_falls_back_to_base_gate(self):
        """无记录（首启）→ 按新周期基础闸确认。"""
        self.cfg()
        self.d = self._new_daemon(self.d.config)
        self.tick(idle_seconds=599)
        assert not self.req.exists()
        self.tick(idle_seconds=600)
        assert self.req.exists()

    def test_derivation_not_reapplied_after_in_memory_reset(self):
        """推导每进程至多一次：内存合流态复位后，同进程后续 tick 不因旧历史
        重新置位（防重启史被再次算进新周期）。"""
        self.cfg()
        self.plant_history(400)
        self.tick()  # 推导 count=1，同 tick 检出首个边沿 → count=2
        assert self.d._coalesce_edge_count == 2
        # 模拟合流态复位（悬置消化且静止期届满后的终态）
        self.d._coalesce_edge_count = 0
        self.d._coalesce_last_edge_ts = None
        self.d._coalesce_last_restart_ts = None
        self.d._coalesce_prev_stale = False
        self.d._code_stale = False
        self.tick()  # 消化期 tick：不再重新推导
        assert self.d._coalesce_edge_count == 0, "推导至多一次，复位后不得复活"
        # 复位后的新边沿按新周期基础闸（而非窗内旧记录的合流闸）
        self.d._code_stale = True
        self.tick(idle_seconds=600)
        assert self.req.exists(), (
            "复位后首个边沿按基础闸 600s 触发（未被窗内旧记录推回合流闸）")


if __name__ == "__main__":
    unittest.main()
