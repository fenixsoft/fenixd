"""evo-add-maintree-stray-wip-sweep 单测（tasks.md 3.1）。

进程内真实 git 仓库夹具覆盖：
- 滞留 tracked 改动宽限耗尽恰发一次告警；重复盘点不重复告警
- mtime 被批量重写而内容不变时 first_seen 不归零（内容指纹计时口径）
- 在飞实现车道命中时不计时不告警（归因复用 identify_wip_occupant 真实现场）
- 改动消失后状态复位；主树锁被占用时本轮放弃
- 每次盘点/告警前后 ``git status --porcelain`` 输出逐字节一致（零触碰）
- admin_monitor 三表登记完备性（防摄取门漏登记回归）
"""

import os
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from core.admin_store import AdminStore, SIGNAL
from core.worktree_manager.stray_wip import (
    SIGNAL_TYPE,
    MainTreeStrayWipSweeper,
    grace_minutes,
)

# /tmp 可能被外部清扫进程周期性清空（test_code_fix 同款规避）。统一用仓库内
# .history/tmp（gitignored），MUST NOT 改写全局 tempfile.tempdir。
_HISTORY_TMP = Path(__file__).resolve().parent.parent / ".history" / "tmp"
_HISTORY_TMP.mkdir(parents=True, exist_ok=True)


def _mkdtemp(prefix: str) -> str:
    return tempfile.mkdtemp(prefix=prefix, dir=str(_HISTORY_TMP))


def _git(*args, cwd, check=True):
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=str(cwd), check=check, capture_output=True, text=True,
    )


def _status(repo) -> str:
    """主树工作区状态原文（零触碰对账基准，逐字节比较）。"""
    return subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo), check=True, capture_output=True, text=True,
    ).stdout


class _WmProbe:
    """WorktreeManager 探针壳：混入盘点/归因所需 mixin（真实实现，非替身）。

    sweep 依赖 _main_tree_lock（stash_guard 锁纪律）、_list_dirty_tracked_files
    （tracked-only 口径）与 identify_wip_occupant 及其 helper（mergeback +
    queries mixin，test_mergeback_wip_coordination._IdentifyProbe 同款装配），
    无需完整 WorktreeManager 装配。
    """

    from core.worktree_manager.mergeback import G4MergebackMixin as _G4
    from core.worktree_manager.queries import G8QueryMixin as _G8
    from core.worktree_manager.stash_guard import G6StashGuardMixin as _G6

    class Inner(_G4, _G6, _G8):
        def __init__(self, root):
            self.project_root = Path(root)
            self._main_tree_lock = threading.Lock()

    def __init__(self, root):
        self.impl = self.Inner(root)

    def __getattr__(self, name):
        return getattr(self.impl, name)


def _make_repo(spec: str = "spec-x", ts: int = 1700000000, with_holder=False):
    """主树仓（+ 可选在飞车道 worktree 分支现场）。

    - 主树 `a.tsx` 有未提交修改（散件 WIP）；
    - with_holder=True 时额外建 worktree 目录名 ``impl-<spec>-<ts>``、分支
      ``fenix/<spec>-<ts>``，分支上提交了对 `a.tsx` 的修改（车道分支改动侧，
      与主树散件求交命中）；
    - `b.tsx` 全场无改动（反例对照）。

    Returns: (主树 Path, worktree Path 或 None)
    """
    base = Path(_mkdtemp("stray-scene-"))
    repo = base / "proj"
    repo.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", cwd=repo)
    (repo / "a.tsx").write_text("base", encoding="utf-8")
    (repo / "b.tsx").write_text("base", encoding="utf-8")
    # 生产形态对齐：.fenix/ 运行时状态目录（AdminStore 告警落盘处）不入库
    # （主仓 .gitignore 同款），零触碰对账不被框架自身状态目录噪音污染。
    (repo / ".gitignore").write_text(".fenix/\n", encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "init", cwd=repo)
    wt = None
    if with_holder:
        wt = base / f"impl-{spec}-{ts}"
        branch = f"fenix/{spec}-{ts}"
        _git("worktree", "add", "-b", branch, str(wt), "HEAD", cwd=repo)
        (wt / "a.tsx").write_text("branch change", encoding="utf-8")
        _git("commit", "-aq", "-m", "branch wip", cwd=wt)
    # 主树未提交修改（散件 WIP）
    (repo / "a.tsx").write_text("main wip", encoding="utf-8")
    return repo, wt


def _make_sweeper(repo, grace=30.0, logger=None) -> MainTreeStrayWipSweeper:
    cfg = {"admin": {"maintree_stray_wip_grace_minutes": grace}}
    return MainTreeStrayWipSweeper(
        repo, _WmProbe(repo), config=cfg, logger=logger,
    )


def _stale_alerts(repo) -> list:
    return [
        r
        for r in AdminStore(repo).read_all()
        if r.get("kind") == SIGNAL and r.get("signal_type") == SIGNAL_TYPE
    ]


class TestGraceConfig(unittest.TestCase):
    """宽限配置解析（ConfigLoader 点号键，对齐 code_fix._orphan_grace_minutes）。"""

    def test_default_and_fallbacks(self):
        self.assertEqual(grace_minutes({}), 30.0)
        self.assertEqual(
            grace_minutes({"admin": {"maintree_stray_wip_grace_minutes": 0}}),
            0.0,
        )
        self.assertEqual(
            grace_minutes({"admin": {"maintree_stray_wip_grace_minutes": 45}}),
            45.0,
        )
        # 解析失败/负值/NaN/inf/超一天上限 → 缺省（禁「无限期静默等待」极端）
        for bad in ("x", None, -5, float("nan"), float("inf"), 24 * 60 + 1):
            self.assertEqual(
                grace_minutes({"admin": {"maintree_stray_wip_grace_minutes": bad}}),
                30.0,
                msg=f"bad={bad!r}",
            )


class TestSweepLifecycle(unittest.TestCase):
    """盘点主流程：建档 → 宽限 → 一次性告警 → 复位（真实 git 仓库现场）。"""

    def test_grace_exhausted_alerts_exactly_once(self):
        repo, _ = _make_repo()
        before = _status(repo)
        sw = _make_sweeper(repo, grace=30.0)

        # 宽限内：只建档不告警
        r1 = sw.sweep()
        self.assertEqual(r1["status"], "orphan-timed")
        self.assertEqual(_stale_alerts(repo), [])

        # 宽限耗尽：恰发一次告警
        fp = r1["fingerprint"]
        sw._registry[fp]["first_seen"] = time.time() - 3600
        r2 = sw.sweep()
        self.assertEqual(r2["status"], "alerted")
        alerts = _stale_alerts(repo)
        self.assertEqual(len(alerts), 1)
        rec = alerts[0]
        self.assertEqual(rec["severity"], "major")
        self.assertIsNone(rec["spec"])
        evidence = rec.get("evidence") or ""
        # evidence 含文件清单 / first_seen / 归因证据 / 盲区注记 / 零触碰注记
        self.assertIn("项目名=proj", evidence)
        self.assertIn("first_seen=", evidence)
        self.assertIn("a.tsx", evidence)
        self.assertIn("无主陈旧 WIP", evidence)
        from core.worktree_manager.types import WipOccupantInfo

        self.assertIn(WipOccupantInfo.BLIND_SPOT_NOTE, evidence)
        self.assertIn("未执行 stash/checkout/clean/reset", evidence)
        self.assertIn("git add/commit", rec.get("recommended_action") or "")

        # 重复盘点不重复告警（同指纹一次性去重）
        r3 = sw.sweep()
        self.assertEqual(r3["status"], "orphan-timed")
        self.assertEqual(len(_stale_alerts(repo)), 1)
        # 零触碰：全流程主树状态逐字节一致
        self.assertEqual(_status(repo), before)

    def test_grace_zero_escalates_immediately(self):
        repo, _ = _make_repo()
        sw = _make_sweeper(repo, grace=0.0)
        r = sw.sweep()
        self.assertEqual(r["status"], "alerted")
        self.assertEqual(len(_stale_alerts(repo)), 1)

    def test_mtime_batch_rewrite_keeps_first_seen(self):
        """mtime 被批量重写而内容不变：first_seen 不归零（D1 指纹计时口径）。"""
        repo, _ = _make_repo()
        sw = _make_sweeper(repo, grace=30.0)
        r1 = sw.sweep()
        fp = r1["fingerprint"]
        first_seen = sw._registry[fp]["first_seen"]
        self.assertGreater(first_seen, 0)

        # autostash pop 形态的批量 mtime 重写（纳秒级同刻，内容不变）
        same_ts = time.time() - 12345.678
        for f in ("a.tsx", "b.tsx"):
            os.utime(repo / f, (same_ts, same_ts))
        r2 = sw.sweep()
        self.assertEqual(r2["fingerprint"], fp)
        self.assertEqual(sw._registry[fp]["first_seen"], first_seen)
        self.assertEqual(_stale_alerts(repo), [])

    def test_content_change_new_fingerprint_fresh_timing(self):
        """内容变化 → 新指纹：旧条目清除、新条目重新起算（不沿用旧 first_seen）。"""
        repo, _ = _make_repo()
        sw = _make_sweeper(repo, grace=30.0)
        r1 = sw.sweep()
        old_fp = r1["fingerprint"]
        sw._registry[old_fp]["first_seen"] = time.time() - 3600

        (repo / "a.tsx").write_text("main wip v2", encoding="utf-8")
        r2 = sw.sweep()
        self.assertNotEqual(r2["fingerprint"], old_fp)
        self.assertNotIn(old_fp, sw._registry)
        self.assertEqual(len(sw._registry), 1)
        self.assertGreater(sw._registry[r2["fingerprint"]]["first_seen"], 0)
        # 新条目 fresh 起算（≈本轮盘点时刻），不沿用旧 first_seen
        self.assertGreater(
            sw._registry[r2["fingerprint"]]["first_seen"], time.time() - 60
        )
        self.assertEqual(_stale_alerts(repo), [])

    def test_change_disappears_resets_state(self):
        """改动消失（指纹不再出现）：注册表条目清除，不告警不残留。"""
        repo, _ = _make_repo()
        sw = _make_sweeper(repo, grace=30.0)
        r1 = sw.sweep()
        fp = r1["fingerprint"]
        sw._registry[fp]["first_seen"] = time.time() - 3600

        # 散件被人工提交（测试现场模拟处置；sweep 本身不触碰主树）
        _git("add", "-A", cwd=repo)
        _git("commit", "-q", "-m", "manual commit", cwd=repo)
        r2 = sw.sweep()
        self.assertEqual(r2["status"], "clean")
        self.assertEqual(sw._registry, {})
        self.assertEqual(_stale_alerts(repo), [])

    def test_untracked_only_change_not_counted(self):
        """tracked-only 口径：纯 untracked 散件不计入（空集直接返回 clean）。"""
        repo, _ = _make_repo()
        _git("checkout", "-q", "--", "a.tsx", cwd=repo)
        (repo / "build_noise.log").write_text("untracked", encoding="utf-8")
        sw = _make_sweeper(repo, grace=0.0)
        r = sw.sweep()
        self.assertEqual(r["status"], "clean")
        self.assertEqual(sw._registry, {})
        self.assertEqual(_stale_alerts(repo), [])

    def test_main_tree_lock_busy_abandons_round(self):
        """主树锁被占用（merge-back 临界区）：本轮放弃，条目保留交下轮。"""
        repo, _ = _make_repo()
        probe = _WmProbe(repo)
        sw = MainTreeStrayWipSweeper(repo, probe, config=None, logger=None)
        with probe._main_tree_lock:
            self.assertIsNone(sw.sweep())
        self.assertEqual(sw._registry, {})
        self.assertEqual(_stale_alerts(repo), [])
        # 锁释放后下一轮正常建档
        r = sw.sweep()
        self.assertEqual(r["status"], "orphan-timed")
        self.assertEqual(len(sw._registry), 1)


class TestHolderAttribution(unittest.TestCase):
    """在飞实现车道命中：不计时不告警（identify_wip_occupant 真实现场）。"""

    SPEC = "spec-x"
    TS = 1700000000

    def test_holder_hit_no_timing_no_alert(self):
        repo, _wt = _make_repo(spec=self.SPEC, ts=self.TS, with_holder=True)
        run_id = f"impl-{self.SPEC}-{self.TS}-a1"
        sw = _make_sweeper(repo, grace=0.0)
        # grace=0：若无主会立即告警——命中持有者则必须零告警零建档
        r = sw.sweep(running_run_ids=[run_id])
        self.assertEqual(r["status"], "holder")
        self.assertEqual(r["holder_run_ids"], [run_id])
        self.assertEqual(sw._registry, {})
        self.assertEqual(_stale_alerts(repo), [])
        # 重复盘点仍不计时
        r2 = sw.sweep(running_run_ids=[run_id])
        self.assertEqual(r2["status"], "holder")
        self.assertEqual(_stale_alerts(repo), [])

    def test_zero_hit_without_lanes_times_and_alerts(self):
        """同一现场、无在飞车道：零命中 → 按无主走宽限（盲区方向对照）。"""
        repo, _wt = _make_repo(spec=self.SPEC, ts=self.TS, with_holder=True)
        sw = _make_sweeper(repo, grace=0.0)
        r = sw.sweep(running_run_ids=[])
        self.assertEqual(r["status"], "alerted")
        self.assertEqual(len(_stale_alerts(repo)), 1)

    def test_engine_wrapper_supplies_run_ids_and_wm(self):
        """engine 包装方法供 run_ids 与 WorktreeManager 句柄（2.1 接线契约）。

        以未绑定调用最小装配 PMEngine.sweep_maintree_stray_wip：断言包装方法
        把 agent_runner._running_agents 的 run_ids 传入归因、句柄透传盘点器，
        且无 _active_runs 空闲预检（在飞场景仍执行盘点，design D2）。
        """
        from core.pm_engine.engine import PMEngine

        repo, _wt = _make_repo(spec=self.SPEC, ts=self.TS, with_holder=True)
        probe = _WmProbe(repo)

        class _FakeRunner:
            _running_agents = {f"impl-{self.SPEC}-{self.TS}-a1": object()}
            worktree_manager = probe

        class _FakeEngine:
            agent_runner = _FakeRunner()
            project_root = repo
            config = {"admin": {"maintree_stray_wip_grace_minutes": 0.0}}
            logger = None
            _stray_wip_sweeper = None

        fake = _FakeEngine()
        r = PMEngine.sweep_maintree_stray_wip(fake)
        self.assertEqual(r["status"], "holder")
        # 盘点器按 wm 句柄缓存（first_seen 注册表进程内持有）
        self.assertIs(fake._stray_wip_sweeper.worktree_manager, probe)
        # 缓存复用：再次调用不重建（注册表延续）
        sw_first = fake._stray_wip_sweeper
        PMEngine.sweep_maintree_stray_wip(fake)
        self.assertIs(fake._stray_wip_sweeper, sw_first)


class TestZeroTouch(unittest.TestCase):
    """零触碰契约：盘点/告警全程主树状态逐字节一致，无 stash 条目产生。"""

    def test_status_byte_identical_across_full_flow(self):
        repo, _ = _make_repo()
        before = _status(repo)
        stash_before = _git("stash", "list", cwd=repo).stdout
        head_before = _git("rev-parse", "HEAD", cwd=repo).stdout
        sw = _make_sweeper(repo, grace=30.0)

        seen = []
        seen.append(sw.sweep()["status"])
        self.assertEqual(_status(repo), before)
        fp = sw._registry and next(iter(sw._registry))
        sw._registry[fp]["first_seen"] = time.time() - 3600
        seen.append(sw.sweep()["status"])  # 告警轮
        self.assertEqual(_status(repo), before)
        seen.append(sw.sweep()["status"])
        self.assertEqual(_status(repo), before)
        self.assertEqual(seen, ["orphan-timed", "alerted", "orphan-timed"])
        # stash 栈零变化（未 stash）
        self.assertEqual(_git("stash", "list", cwd=repo).stdout, stash_before)
        # HEAD 未动（未 checkout/reset/commit）
        self.assertEqual(_git("rev-parse", "HEAD", cwd=repo).stdout, head_before)


class TestAdminMonitorRegistration(unittest.TestCase):
    """三表登记完备性（防摄取门漏登记回归：漏 STORED_SIGNAL_TYPES 则落空）。"""

    def test_three_tables_registered(self):
        from core.admin_monitor import (
            SIGNAL_RECOMMENDATION,
            SIGNAL_SEVERITY,
            STORED_SIGNAL_TYPES,
        )

        self.assertIn(SIGNAL_TYPE, SIGNAL_SEVERITY)
        self.assertEqual(SIGNAL_SEVERITY[SIGNAL_TYPE], "major")
        self.assertIn(SIGNAL_TYPE, SIGNAL_RECOMMENDATION)
        self.assertTrue(SIGNAL_RECOMMENDATION[SIGNAL_TYPE].strip())
        self.assertIn(SIGNAL_TYPE, STORED_SIGNAL_TYPES)
        # 姊妹信号同族对账：同为「无主陈旧 WIP 宽限耗尽」人工告警族
        self.assertEqual(
            SIGNAL_SEVERITY[SIGNAL_TYPE],
            SIGNAL_SEVERITY["mergeback_wip_orphan_stuck"],
        )

    def test_alert_record_ingestible_shape(self):
        """落盘记录满足摄取门前提：kind=SIGNAL、signal_type 收录、证据带项目名。"""
        repo, _ = _make_repo()
        _make_sweeper(repo, grace=0.0).sweep()
        recs = _stale_alerts(repo)
        self.assertEqual(len(recs), 1)
        rec = recs[0]
        self.assertEqual(rec["signal_type"], SIGNAL_TYPE)
        # evidence 以「项目名=」开头（admin_monitor._detect_family_explosion
        # 无 spec 形态按该字段解析，未解析出 spec 的记录会被丢弃）
        self.assertTrue((rec.get("evidence") or "").startswith("项目名="))
        from core.admin_store import evidence_project

        self.assertEqual(evidence_project(rec["evidence"]), "proj")


class TestSessionAttributionDowngrade(unittest.TestCase):
    """会话归因散件盘点侧降级（evo-add-maintree-interactive-session-attribution 3.2）。

    活会话归因命中 → 不发 major 告警、info 留痕（status=session-attributed）；
    配置 keep 回退（或非法值守卫）→ 视同零命中仍发 major（现状行为）。
    """

    def _make_session_repo(self):
        """主树仓：近窗提交（作者=本仓配置身份 isess <isess@t>，触碰 a.tsx）+ a.tsx 散件。"""
        repo, _wt = _make_repo()
        subprocess.run(["git", "config", "user.name", "isess"], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "isess@t"], cwd=str(repo), check=True, capture_output=True)
        # 近窗提交必须以仓库配置身份落作者（-c 注入会覆盖，归因身份判据失配）
        (repo / "a.tsx").write_text("session committed work", encoding="utf-8")
        subprocess.run(
            ["git", "add", "-A"], cwd=str(repo), check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-q", "-m", "session work"], cwd=str(repo),
            check=True, capture_output=True,
        )
        # 恢复散件脏态（与 _make_repo 后同内容：a.tsx 主树直改未提交）
        (repo / "a.tsx").write_text("main wip", encoding="utf-8")
        return repo

    def _sweeper(self, repo, grace=30.0, action=None):
        admin = {"maintree_stray_wip_grace_minutes": grace}
        if action is not None:
            admin["maintree_session_attribution_action"] = action
        return MainTreeStrayWipSweeper(
            repo, _WmProbe(repo), config={"admin": admin}, logger=None,
        )

    def test_session_hit_no_major_info_trace_only(self):
        """活会话归因命中：不发 major 告警，info 留痕（grace=0 反证零告警）。"""
        repo = self._make_session_repo()
        before = _status(repo)
        sw = self._sweeper(repo, grace=0.0)
        r = sw.sweep()
        self.assertEqual(r["status"], "session-attributed")
        self.assertEqual(_stale_alerts(repo), [])
        # 计时/复位与在飞车道命中分支同型：pop 计时条目、指纹消失即复位
        self.assertEqual(sw._registry, {})
        self.assertEqual(_status(repo), before)

    def test_keep_fallback_still_alerts_major(self):
        """配置 keep 回退：会话归因视同零命中，仍按现状发 major 告警。"""
        repo = self._make_session_repo()
        sw = self._sweeper(repo, grace=0.0, action="keep")
        self.assertEqual(sw.sweep()["status"], "alerted")
        alerts = _stale_alerts(repo)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["severity"], "major")
        # evidence 仍透传 describe() 会话线索（回退不吞线索）
        self.assertIn("主树活交互会话", alerts[0].get("evidence") or "")

    def test_invalid_action_guard_falls_back_to_keep(self):
        """非法配置值守卫回退 keep：配置事故 MUST NOT 静默吞 major。"""
        repo = self._make_session_repo()
        sw = self._sweeper(repo, grace=0.0, action="bogus")
        self.assertEqual(sw.sweep()["status"], "alerted")
        self.assertEqual(len(_stale_alerts(repo)), 1)


if __name__ == "__main__":
    unittest.main()
