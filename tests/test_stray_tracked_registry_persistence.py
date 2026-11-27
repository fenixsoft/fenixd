"""evo-persist-stray-tracked-registry 单测（tasks.md 2.1）。

tracked 流散件注册表落盘与同指纹 24h 静默窗（进程内真实 git 仓库夹具，
装配参照 tests/test_maintree_stray_wip_sweep.py）：
- 落盘/重启恢复：两分区文件（tracked 计时 + alert_history 台账）、字段
  白名单、原子写（tmp+replace、无变更跳过）、重启后宽限与静默窗连续
- 静默窗：24h 内同指纹抑制（零 AdminStore 写入、suppressed_count 累计、
  60 分钟聚合 info）；满 24h 重告 evidence 携带抑制轮数；指纹演进重告
- 台账分账：归因分支 pop 计时条目后台账仍在；当轮不在场且超窗淘汰
- 容错：载入 OSError/字节层损坏置禁写哨兵（盘上文件不被覆写）；JSON 层
  真损坏回退空表覆写自愈，不阻断盘点
"""

import json
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from core.admin_store import AdminStore, SIGNAL
from core.worktree_manager import stray_wip
from core.worktree_manager.stray_wip import (
    ALERT_SILENCE_WINDOW_SECONDS,
    SIGNAL_TYPE,
    TRACKED_REGISTRY_RELPATH,
    MainTreeStrayWipSweeper,
)

# /tmp 可能被外部清扫进程周期性清空（test_maintree_stray_wip_sweep 同款
# 规避）。统一用仓库内 .history/tmp（gitignored），不改全局 tempdir。
_HISTORY_TMP = Path(__file__).resolve().parent.parent / ".history" / "tmp"
_HISTORY_TMP.mkdir(parents=True, exist_ok=True)

_TS = 1700000000


def _mkdtemp(prefix: str) -> str:
    return tempfile.mkdtemp(prefix=prefix, dir=str(_HISTORY_TMP))


def _git(*args, cwd, check=True):
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=str(cwd), check=check, capture_output=True, text=True,
    )


def _make_repo():
    """主树仓：a.tsx 未提交修改（散件 WIP）+ b.tsx 干净对照。"""
    base = Path(_mkdtemp("stray-track-reg-"))
    repo = base / "proj"
    repo.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", cwd=repo)
    (repo / "a.tsx").write_text("base", encoding="utf-8")
    (repo / "b.tsx").write_text("base", encoding="utf-8")
    (repo / ".gitignore").write_text(".fenix/\n", encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "init", cwd=repo)
    (repo / "a.tsx").write_text("main wip", encoding="utf-8")
    return repo


def _make_holder_repo():
    """主树仓 + 在飞车道现场（worktree 分支改动与主树散件求交命中）。"""
    repo = _make_repo()
    base = repo.parent
    wt = base / f"impl-holder-{_TS}"
    _git("worktree", "add", "-b", f"fenix/holder-{_TS}", str(wt), "HEAD",
         cwd=repo)
    (wt / "a.tsx").write_text("branch change", encoding="utf-8")
    _git("commit", "-aq", "-m", "branch wip", cwd=wt)
    return repo, wt


class _WmProbe:
    """WorktreeManager 探针壳（test_maintree_stray_wip_sweep 同款装配）。"""

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


def _make_sweeper(repo, grace=0.0, logger=None) -> MainTreeStrayWipSweeper:
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


def _registry_payload(repo) -> dict:
    return json.loads((repo / TRACKED_REGISTRY_RELPATH).read_text("utf-8"))


class _CaptureLogger:
    def __init__(self):
        self.infos: list = []
        self.warnings: list = []

    def info(self, channel, msg):
        self.infos.append(msg)

    def warning(self, channel, msg):
        self.warnings.append(msg)


class TestPersistenceRoundtrip(unittest.TestCase):
    """落盘/重启恢复：两分区、字段白名单、原子写、时钟连续。"""

    def test_two_sections_and_field_whitelist(self):
        repo = _make_repo()
        sw = _make_sweeper(repo)
        r1 = sw.sweep()
        self.assertEqual(r1["status"], "alerted")
        payload = _registry_payload(repo)
        self.assertEqual(
            sorted(payload.keys()), ["alert_history", "tracked"]
        )
        fp = r1["fingerprint"]
        self.assertIn(fp, payload["tracked"])
        self.assertIn(fp, payload["alert_history"])
        # 字段白名单：计时条目恰四字段（不写 escalated_signal_at——双档
        # 升级属 untracked 语义）；台账恰两字段。
        self.assertEqual(
            sorted(payload["tracked"][fp].keys()),
            ["escalated_at", "files", "first_seen", "first_seen_iso"],
        )
        self.assertEqual(
            sorted(payload["alert_history"][fp].keys()),
            ["last_alert_at", "suppressed_count"],
        )
        self.assertEqual(payload["alert_history"][fp]["suppressed_count"], 0)
        # 原子写：无半程临时文件残留（tmp 均经 os.replace 换入或清理）。
        leftovers = list((repo / ".fenix").glob(".stray_tracked_registry*"))
        self.assertEqual(leftovers, [])

    def test_restart_restores_first_seen_history_and_suppresses(self):
        """重启恢复：first_seen/escalated_at/台账跨重启连续，窗内抑制。"""
        repo = _make_repo()
        sw = _make_sweeper(repo)
        r1 = sw.sweep()
        fp = r1["fingerprint"]
        first_seen = sw._registry[fp]["first_seen"]
        escalated_at = sw._registry[fp]["escalated_at"]
        last_alert_at = sw._alert_history[fp]["last_alert_at"]
        self.assertTrue(escalated_at)
        # 重启模拟：全新 sweeper 实例（内存态清零，从盘上注册表恢复）。
        sw2 = _make_sweeper(repo)
        self.assertEqual(sw2._registry, {})
        self.assertEqual(sw2._alert_history, {})
        r2 = sw2.sweep()
        # 恢复的台账仍在 24h 窗内 → 抑制（重启不击穿静默窗去重）。
        self.assertEqual(r2["status"], "orphan-timed")
        self.assertEqual(len(_stale_alerts(repo)), 1)
        # first_seen/escalated_at 跨重启连续（恢复值＝落盘值，未以当轮
        # 时刻重登记）。
        self.assertEqual(sw2._registry[fp]["first_seen"], first_seen)
        self.assertEqual(sw2._registry[fp]["escalated_at"], escalated_at)
        self.assertEqual(
            sw2._alert_history[fp]["last_alert_at"], last_alert_at
        )
        self.assertEqual(sw2._alert_history[fp]["suppressed_count"], 1)

    def test_persist_skips_when_payload_unchanged(self):
        repo = _make_repo()
        sw = _make_sweeper(repo)
        sw.sweep()  # 建档落盘（payload 已缓存）
        reg = repo / TRACKED_REGISTRY_RELPATH
        stat1 = reg.stat()
        time.sleep(0.01)
        # 内存态即盘上镜像：再次落盘跳过（无变更不写盘）。
        sw._persist_tracked_registry()
        stat2 = reg.stat()
        self.assertEqual(stat1.st_mtime_ns, stat2.st_mtime_ns)
        self.assertEqual(stat1.st_size, stat2.st_size)


class TestSilenceWindow(unittest.TestCase):
    """24h 滚动静默窗：抑制/累计/满窗重告/指纹演进。"""

    def test_within_window_suppressed_and_counted(self):
        repo = _make_repo()
        log = _CaptureLogger()
        sw = _make_sweeper(repo, logger=log)
        r1 = sw.sweep()
        fp = r1["fingerprint"]
        self.assertEqual(r1["status"], "alerted")
        self.assertEqual(len(_stale_alerts(repo)), 1)

        # 24h 内同指纹重复盘点：抑制（零 AdminStore 写入），仅累计计数。
        for expected_count in (1, 2, 3):
            r = sw.sweep()
            self.assertEqual(r["status"], "orphan-timed")
            # 抑制轮返回键集不变（与告警轮同一契约，外加流附加键）。
            self.assertEqual(
                sorted(r.keys()),
                sorted(
                    ["status", "files", "fingerprint", "first_seen_iso",
                     "grace_minutes", "elapsed_minutes",
                     "whitelist_untracked"]
                ),
            )
            self.assertEqual(len(_stale_alerts(repo)), 1)
            hist = sw._alert_history[fp]
            self.assertEqual(hist["suppressed_count"], expected_count)
        # 抑制轮数随落盘持久化。
        self.assertEqual(
            _registry_payload(repo)["alert_history"][fp]["suppressed_count"], 3
        )
        # 60 分钟聚合日志：首次抑制落全量行，紧随抑制静默计数。
        suppress_lines = [
            m for m in log.infos if "静默窗抑制" in m and "不足 24h" in m
        ]
        self.assertEqual(len(suppress_lines), 1)
        # 回拨日志窗起点 → 聚合行（含累计计数＝观测轮数含本轮）且窗口重置。
        key, count, ts = sw._suppressed_log_state[fp]
        self.assertEqual(count, 2)
        sw._suppressed_log_state[fp] = (key, count, ts - 3601)
        sw.sweep()
        agg = [m for m in log.infos if "近 1h 累计" in m]
        self.assertEqual(len(agg), 1)
        self.assertIn("3 轮", agg[0])
        self.assertEqual(len(_stale_alerts(repo)), 1)

    def test_after_window_realerts_with_suppressed_rounds(self):
        repo = _make_repo()
        sw = _make_sweeper(repo)
        r1 = sw.sweep()
        fp = r1["fingerprint"]
        sw.sweep()
        sw.sweep()  # 抑制两轮
        self.assertEqual(sw._alert_history[fp]["suppressed_count"], 2)
        # 满 24h：last_alert_at 回拨超窗 → 重告且 evidence 携带抑制轮数。
        sw._alert_history[fp]["last_alert_at"] = (
            time.time() - ALERT_SILENCE_WINDOW_SECONDS - 60
        )
        r = sw.sweep()
        self.assertEqual(r["status"], "alerted")
        alerts = _stale_alerts(repo)
        self.assertEqual(len(alerts), 2)
        # read_all 新记录在前：首条是满窗重告（带复发注记与抑制轮数），
        # 末条是首次告警（两注记皆无）。
        self.assertIn("复发注记", alerts[0].get("evidence") or "")
        self.assertIn("静默窗抑制轮数=2", alerts[0].get("evidence") or "")
        self.assertNotIn("静默窗抑制轮数", alerts[-1].get("evidence") or "")
        # 重告后台账刷新（抑制计数归零）。
        hist = sw._alert_history[fp]
        self.assertEqual(hist["suppressed_count"], 0)
        self.assertGreater(hist["last_alert_at"], time.time() - 5)
        self.assertEqual(
            _registry_payload(repo)["alert_history"][fp]["suppressed_count"], 0
        )

    def test_fingerprint_evolution_realerts_and_resets_clock(self):
        repo = _make_repo()
        sw = _make_sweeper(repo)
        r1 = sw.sweep()
        fp1 = r1["fingerprint"]
        sw.sweep()  # fp1 抑制一轮
        # 内容演进 → 新指纹：按常规宽限正常告警（不受旧指纹台账抑制）。
        (repo / "a.tsx").write_text("main wip evolved", encoding="utf-8")
        r2 = sw.sweep()
        fp2 = r2["fingerprint"]
        self.assertNotEqual(fp1, fp2)
        self.assertEqual(r2["status"], "alerted")
        self.assertEqual(len(_stale_alerts(repo)), 2)
        # 计时复位：新条目自当轮重新起算。
        self.assertNotIn(fp1, sw._registry)
        self.assertGreater(sw._registry[fp2]["first_seen"], time.time() - 5)
        # 旧指纹台账保留至淘汰（指纹演进不清台账）。
        self.assertIn(fp1, sw._alert_history)
        self.assertIn(fp2, sw._alert_history)


class TestLedgerLifecycle(unittest.TestCase):
    """台账分账：归因 pop 不清台账；当轮不在场且超窗才淘汰。"""

    def test_attribution_pop_keeps_ledger(self):
        repo, _wt = _make_holder_repo()
        run_id = f"impl-holder-{_TS}-a1"
        sw = _make_sweeper(repo)
        r1 = sw.sweep(running_run_ids=[])  # 无车道命中 → 无主建档 + 立即告警
        fp = r1["fingerprint"]
        self.assertEqual(r1["status"], "alerted")
        # 在飞车道命中：计时条目 pop（holder 分支），台账必须仍在。
        r2 = sw.sweep(running_run_ids=[run_id])
        self.assertEqual(r2["status"], "holder")
        self.assertNotIn(fp, sw._registry)
        self.assertIn(fp, sw._alert_history)
        # 归因消失：重新建档（宽限重起算）仍受静默窗约束——不重告。
        r3 = sw.sweep(running_run_ids=[])
        self.assertEqual(r3["status"], "orphan-timed")
        self.assertEqual(len(_stale_alerts(repo)), 1)
        self.assertEqual(sw._alert_history[fp]["suppressed_count"], 1)
        # 台账随落盘持久化（重启后同指纹复现仍受窗约束）。
        self.assertEqual(
            _registry_payload(repo)["alert_history"][fp]["suppressed_count"], 1
        )

    def test_absent_and_expired_evicts_ledger(self):
        repo = _make_repo()
        sw = _make_sweeper(repo)
        r1 = sw.sweep()
        fp = r1["fingerprint"]
        # 在场但超窗：不淘汰（淘汰条件是「不在场且超窗」合取）——满窗重告。
        sw._alert_history[fp]["last_alert_at"] = (
            time.time() - ALERT_SILENCE_WINDOW_SECONDS - 60
        )
        sw.sweep()
        self.assertIn(fp, sw._alert_history)
        self.assertEqual(len(_stale_alerts(repo)), 2)
        # 散件消失（提交）＋台账超窗：淘汰。
        _git("add", "-A", cwd=repo)
        _git("commit", "-q", "-m", "commit stray", cwd=repo)
        sw._alert_history[fp]["last_alert_at"] = (
            time.time() - ALERT_SILENCE_WINDOW_SECONDS - 60
        )
        sw.sweep()  # clean 轮：指纹不在场且超窗 → 淘汰
        self.assertNotIn(fp, sw._alert_history)
        self.assertEqual(_registry_payload(repo)["alert_history"], {})
        # 对照：散件消失但台账窗内 → 保留（重启后同指纹复现不重告）。
        (repo / "a.tsx").write_text("reset content", encoding="utf-8")
        _git("add", "-A", cwd=repo)
        _git("commit", "-q", "-m", "baseline shift", cwd=repo)
        (repo / "a.tsx").write_text("main wip again", encoding="utf-8")
        sw2 = _make_sweeper(repo)
        r = sw2.sweep()
        self.assertEqual(r["status"], "alerted")  # 新指纹首次告警
        fp2 = r["fingerprint"]
        # 还原工作区（内容与 HEAD 一致＝clean，无需提交）。
        (repo / "a.tsx").write_text("reset content", encoding="utf-8")
        sw2.sweep()  # clean 轮：指纹不在场但台账窗内 → 保留
        self.assertIn(fp2, sw2._alert_history)


class TestLoadFaultTolerance(unittest.TestCase):
    """载入容错：OSError/字节层损坏禁写保盘；JSON 层损坏覆写自愈。"""

    @staticmethod
    def _poison_read(reg_path: Path):
        real_read_text = Path.read_text

        def _boom(self, *args, **kwargs):
            if self == reg_path:
                raise OSError(5, "EIO (simulated transient read fault)")
            return real_read_text(self, *args, **kwargs)

        return mock.patch.object(Path, "read_text", _boom)

    def test_load_oserror_suppresses_write_and_keeps_file(self):
        repo = _make_repo()
        sw = _make_sweeper(repo)
        sw.sweep()  # 首启建档落盘
        reg = repo / TRACKED_REGISTRY_RELPATH
        original = reg.read_bytes()
        # 重启模拟 + 载入 OSError：本进程禁写，盘上完好文件不被覆写。
        sw2 = _make_sweeper(repo)
        with self._poison_read(reg):
            r = sw2.sweep()  # 内存态空表 → 重新建档 + grace=0 告警
        self.assertEqual(r["status"], "alerted")
        self.assertTrue(sw2._tracked_persist_suppressed)
        self.assertEqual(reg.read_bytes(), original)  # 盘上文件原样保留
        # 告警链不阻断（fail-open）：AdminStore 照常落告警。
        self.assertEqual(len(_stale_alerts(repo)), 2)

    def test_byte_level_corruption_suppresses_write(self):
        repo = _make_repo()
        sw = _make_sweeper(repo)
        sw.sweep()
        reg = repo / TRACKED_REGISTRY_RELPATH
        reg.write_bytes(b"\xff\xfe\x00broken-utf8")  # 字节层损坏
        sw2 = _make_sweeper(repo)
        r = sw2.sweep()
        self.assertEqual(r["status"], "alerted")
        self.assertTrue(sw2._tracked_persist_suppressed)
        self.assertEqual(reg.read_bytes(), b"\xff\xfe\x00broken-utf8")
        # 告警不阻断（内存态照常建档告警，只跳过回写）。
        self.assertEqual(len(_stale_alerts(repo)), 2)

    def test_json_corruption_failopen_overwrite_selfheal(self):
        repo = _make_repo()
        sw = _make_sweeper(repo)
        sw.sweep()
        reg = repo / TRACKED_REGISTRY_RELPATH
        reg.write_text("{not json", encoding="utf-8")  # JSON 层真损坏
        log = _CaptureLogger()
        sw2 = _make_sweeper(repo, logger=log)
        r = sw2.sweep()  # 回退空表（fail-open）→ 照常盘点 + 落盘自愈
        self.assertEqual(r["status"], "alerted")
        self.assertFalse(sw2._tracked_persist_suppressed)
        self.assertTrue(any("损坏" in m for m in log.warnings))
        payload = _registry_payload(repo)  # 覆写自愈：盘上恢复合法两分区
        self.assertIn(r["fingerprint"], payload["tracked"])
        self.assertIn(r["fingerprint"], payload["alert_history"])

    def test_partial_entry_corruption_no_crossharm(self):
        """部分条目损坏不株连完好条目（条目级形态守卫剔除）。"""
        repo = _make_repo()
        probe = _make_sweeper(repo)
        fp = probe.sweep()["fingerprint"]  # 取真实指纹（fp 与夹具对齐）
        reg = repo / TRACKED_REGISTRY_RELPATH
        reg.write_text(
            json.dumps(
                {
                    "tracked": {
                        fp: {
                            "first_seen": time.time() - 3600,
                            "first_seen_iso": "2026-11-27T00:00:00Z",
                            "files": ["a.tsx"],
                            "escalated_at": "",
                        },
                        "b" * 64: "not-a-dict",  # 形态非法 → 剔除
                    },
                    "alert_history": {
                        fp: {
                            "last_alert_at": time.time() - 60,
                            "suppressed_count": 2,
                        },
                        "c" * 64: {"last_alert_at": "bad"},  # 非数值 → 剔除
                    },
                }
            ),
            encoding="utf-8",
        )
        sw = _make_sweeper(repo)
        sw.sweep()
        self.assertIn(fp, sw._registry)
        self.assertNotIn("b" * 64, sw._registry)
        self.assertIn(fp, sw._alert_history)
        self.assertEqual(sw._alert_history[fp]["suppressed_count"], 3)
        self.assertNotIn("c" * 64, sw._alert_history)
        # 完好条目窗内抑制生效（不因坏条目株连重告）。
        self.assertEqual(len(_stale_alerts(repo)), 1)


if __name__ == "__main__":
    unittest.main()
