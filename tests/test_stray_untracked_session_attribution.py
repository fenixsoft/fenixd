"""evo-stray-untracked-session-attribution 单测（tasks.md 2.1/2.2）。

主树 untracked 散件管线越阈后的会话归因探测（design 落点
``_untracked_signal`` / ``_untracked_attribution_probe``）：
- 五态覆盖：会话归因命中（复位+session-attributed+零告警）/ 在飞车道
  holder 命中（复位+holder-attributed+零告警）/ keep 配置（照常计时）/
  零命中（宽限流不变+升级 evidence 注记）/ 低于阈值（归因器零调用）；
- 升级 evidence 注记措辞分档断言（零命中 vs keep 回退，不误述）；
- 复位语义（时钟复位非永久豁免：归因消失后重新建档计时并照常升级）。

stub 方式参考 tests/test_maintree_stray_wip_sweep.py 既有探针形态
（_WmProbe mixin 装配 + identify_wip_occupant 计数替身）；另附真实
归因器现场用例（在飞车道同名路径 / transcript 活跃提及）防替身漂移。
"""

import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from core.admin_store import SIGNAL, AdminStore
from core.worktree_manager.stray_wip import (
    UNTRACKED_ESCALATED_SIGNAL_TYPE,
    UNTRACKED_SIGNAL_TYPE,
    MainTreeStrayWipSweeper,
)
from core.worktree_manager.types import WipOccupantInfo

# /tmp 可能被外部清扫进程周期性清空（test_maintree_stray_wip_sweep 同款规避）。
# 统一用仓库内 .history/tmp（gitignored），MUST NOT 改写全局 tempfile.tempdir。
_HISTORY_TMP = Path(__file__).resolve().parent.parent / ".history" / "tmp"
_HISTORY_TMP.mkdir(parents=True, exist_ok=True)

# 缺省 entry 阈值 5（untracked_stray_threshold）：6 个散件越阈、2 个低于阈值。
NAMES = [f"stray_{i}.log" for i in range(6)]


def _mkdtemp(prefix: str) -> str:
    return tempfile.mkdtemp(prefix=prefix, dir=str(_HISTORY_TMP))


def _git(*args, cwd, check=True):
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=str(cwd), check=check, capture_output=True, text=True,
    )


def _make_untracked_repo(names=NAMES, sizes=None):
    """主树仓：tracked 干净 + names 列出的 untracked 散件（默认 6 个越阈）。"""
    base = Path(_mkdtemp("stray-attr-"))
    repo = base / "proj"
    repo.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", cwd=repo)
    (repo / "a.tsx").write_text("base", encoding="utf-8")
    (repo / ".gitignore").write_text(".fenix/\n", encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "init", cwd=repo)
    for n in names:
        size = int((sizes or {}).get(n, 32))
        (repo / n).write_text("x" * size, encoding="utf-8")
    return repo


class _WmProbe:
    """WorktreeManager 探针壳（test_maintree_stray_wip_sweep 同款 mixin 装配）。

    sweep 依赖 _main_tree_lock、_list_dirty_tracked_files 与
    identify_wip_occupant 及其 helper；identify 可注入计数替身（缺省用
    G4/G8 mixin 的真实现场）。
    """

    from core.worktree_manager.mergeback import G4MergebackMixin as _G4
    from core.worktree_manager.queries import G8QueryMixin as _G8
    from core.worktree_manager.stash_guard import G6StashGuardMixin as _G6

    class Inner(_G4, _G6, _G8):
        def __init__(self, root):
            self.project_root = Path(root)
            self._main_tree_lock = threading.Lock()

    def __init__(self, root, identify=None):
        self.impl = self.Inner(root)
        if identify is not None:
            self.identify_wip_occupant = identify

    def __getattr__(self, name):
        return getattr(self.impl, name)


class _CountingIdentify:
    """identify_wip_occupant 计数替身：记录入参、按剧本逐轮返回。"""

    def __init__(self, script):
        self.script = list(script)  # [WipOccupantInfo,...]（越界复用末位）
        self.calls = []

    def __call__(self, files, run_ids=()):
        self.calls.append({"files": list(files), "run_ids": list(run_ids)})
        idx = min(len(self.calls) - 1, len(self.script) - 1)
        return self.script[idx]


def _session_info(entries):
    """会话归因命中形态（source=maintree-interactive-session）。"""
    return WipOccupantInfo(
        True,
        [{
            "run_ids": [], "spec": "", "branch": "", "worktree": "/main",
            "files": sorted(entries)[:1],
            "kind": "interactive-session",
            "session": {
                "identity": "isess <isess@t>",
                "signals": ["transcript-active+path-mention"],
            },
        }],
        sorted(entries),
        source=WipOccupantInfo.SOURCE_MAINTREE_SESSION,
    )


def _lane_info(entries):
    """在飞实现车道 holder 命中形态（source=worktree-branch-diff 缺省）。"""
    return WipOccupantInfo(
        True,
        [{
            "run_ids": ["impl-spec-x-1700000000"], "spec": "spec-x",
            "branch": "fenix/spec-x-1700000000", "worktree": "/wt",
            "files": sorted(entries)[:1],
        }],
        sorted(entries),
    )


def _make_sweeper(repo, identify=None, grace=30.0, action=None):
    admin = {"maintree_stray_wip_grace_minutes": grace}
    if action is not None:
        admin["maintree_session_attribution_action"] = action
    return MainTreeStrayWipSweeper(
        repo, _WmProbe(repo, identify), config={"admin": admin}, logger=None,
    )


def _alerts(repo, signal_type) -> list:
    return [
        r
        for r in AdminStore(repo).read_all()
        if r.get("kind") == SIGNAL and r.get("signal_type") == signal_type
    ]


def _escalated(repo) -> list:
    return _alerts(repo, UNTRACKED_ESCALATED_SIGNAL_TYPE)


class TestUntrackedAttributionStates(unittest.TestCase):
    """五态覆盖（tasks.md 2.1）：归因器三态 × 阈值闸门 × keep 配置。"""

    def test_session_hit_resets_and_no_alert(self):
        """会话归因命中：条目复位 + session-attributed + 零告警。"""
        repo = _make_untracked_repo()
        identify = _CountingIdentify([_session_info(NAMES)])
        sw = _make_sweeper(repo, identify, grace=0.0)
        r = sw.sweep(running_run_ids=["impl-other-1"])
        u = r["untracked"]
        self.assertEqual(u["status"], "session-attributed")
        self.assertEqual(
            u["session_signals"], ["transcript-active+path-mention"]
        )
        # 计时条目复位（pop：宽限时钟复位；grace=0 反证未走宽限告警流）
        self.assertEqual(sw._untracked_registry, {})
        self.assertEqual(_alerts(repo, UNTRACKED_SIGNAL_TYPE), [])
        self.assertEqual(_escalated(repo), [])
        # 透传：归因器收到 untracked 清单与 running_run_ids（tracked 流同口径）
        self.assertEqual(identify.calls[0]["files"], sorted(NAMES))
        self.assertEqual(identify.calls[0]["run_ids"], ["impl-other-1"])

    def test_lane_holder_hit_resets_and_no_alert(self):
        """在飞车道 holder 命中：条目复位 + holder-attributed + 零告警。

        grace=0 反证：若误视同零命中走宽限流，grace=0 当轮即发 major。
        """
        repo = _make_untracked_repo()
        identify = _CountingIdentify([_lane_info(NAMES)])
        sw = _make_sweeper(repo, identify, grace=0.0)
        r = sw.sweep(running_run_ids=["impl-spec-x-1700000000"])
        u = r["untracked"]
        self.assertEqual(u["status"], "holder-attributed")
        self.assertEqual(
            u["holder_run_ids"], ["impl-spec-x-1700000000"]
        )
        self.assertEqual(sw._untracked_registry, {})
        self.assertEqual(_alerts(repo, UNTRACKED_SIGNAL_TYPE), [])
        self.assertEqual(_escalated(repo), [])

    def test_keep_config_times_normally(self):
        """keep 配置：会话归因命中也照常建档计时（完全回退现状行为）。"""
        repo = _make_untracked_repo()
        identify = _CountingIdentify([_session_info(NAMES)])
        sw = _make_sweeper(repo, identify, action="keep")
        r = sw.sweep()
        u = r["untracked"]
        self.assertEqual(u["status"], "timed")
        fp = u["fingerprint"]
        self.assertIn(fp, sw._untracked_registry)
        self.assertEqual(_escalated(repo), [])

    def test_zero_hit_keeps_grace_flow(self):
        """零命中：宽限流不变（建档计时 → 宽限耗尽照常升级）。"""
        repo = _make_untracked_repo()
        identify = _CountingIdentify([WipOccupantInfo(False, [], NAMES)])
        sw = _make_sweeper(repo, identify)
        r1 = sw.sweep()
        self.assertEqual(r1["untracked"]["status"], "timed")
        fp = r1["untracked"]["fingerprint"]
        self.assertIn(fp, sw._untracked_registry)
        self.assertEqual(_escalated(repo), [])
        sw._untracked_registry[fp]["first_seen"] = time.time() - 25 * 3600
        r2 = sw.sweep()
        self.assertEqual(r2["untracked"]["status"], "escalated")
        self.assertEqual(len(_escalated(repo)), 1)

    def test_below_threshold_never_calls_attribution(self):
        """低于阈值：归因器零调用（stub 计数断言，零子进程开销）。"""
        repo = _make_untracked_repo(names=["a.log", "b.log"])
        identify = _CountingIdentify([_session_info(["a.log", "b.log"])])
        sw = _make_sweeper(repo, identify, grace=0.0)
        r1 = sw.sweep()
        self.assertEqual(r1["untracked"]["status"], "below-threshold")
        r2 = sw.sweep()
        self.assertEqual(r2["untracked"]["status"], "below-threshold")
        self.assertEqual(identify.calls, [])


class TestEscalationEvidenceAnnotation(unittest.TestCase):
    """升级 evidence 注记断言（tasks.md 2.2）：措辞按探测结果分档、不误述。"""

    def test_zero_hit_annotation_present(self):
        """零命中升级：evidence 断言「归因探测已执行」「零命中」字样在场。"""
        repo = _make_untracked_repo()
        identify = _CountingIdentify([WipOccupantInfo(False, [], NAMES)])
        sw = _make_sweeper(repo, identify)
        r1 = sw.sweep()
        sw._untracked_registry[r1["untracked"]["fingerprint"]][
            "first_seen"
        ] = time.time() - 25 * 3600
        self.assertEqual(sw.sweep()["untracked"]["status"], "escalated")
        esc = _escalated(repo)
        self.assertEqual(len(esc), 1)
        evidence = esc[0].get("evidence") or ""
        self.assertIn("归因探测已执行", evidence)
        self.assertIn("零命中", evidence)
        self.assertIn(
            "归因探测已执行，零命中（判据：近窗提交路径交/活跃 transcript "
            "路径提及）",
            evidence,
        )

    def test_keep_fallback_annotation_not_misstated_as_zero_hit(self):
        """keep 回退升级：注记为「命中但配置 keep 回退」，不误述为零命中。"""
        repo = _make_untracked_repo()
        identify = _CountingIdentify([_session_info(NAMES)])
        sw = _make_sweeper(repo, identify, action="keep")
        r1 = sw.sweep()
        self.assertEqual(r1["untracked"]["status"], "timed")
        sw._untracked_registry[r1["untracked"]["fingerprint"]][
            "first_seen"
        ] = time.time() - 25 * 3600
        self.assertEqual(sw.sweep()["untracked"]["status"], "escalated")
        esc = _escalated(repo)
        self.assertEqual(len(esc), 1)
        evidence = esc[0].get("evidence") or ""
        self.assertIn("归因探测已执行", evidence)
        self.assertIn("命中但配置 keep 回退", evidence)
        # 零命中固定措辞缺席（「视同零命中」含字样但非零命中措辞——按完整
        # 固定措辞断言防「命中被误述为零命中」误导 admin 判读）
        self.assertNotIn("归因探测已执行，零命中", evidence)


class TestResetSemantics(unittest.TestCase):
    """复位语义（tasks.md 1.3）：时钟复位而非永久豁免。"""

    def test_attribution_gone_rearchives_and_escalates(self):
        """会话离场（归因消失）→ 重新建档计时 → 宽限耗尽照常升级。"""
        repo = _make_untracked_repo()
        identify = _CountingIdentify([
            _session_info(NAMES),
            WipOccupantInfo(False, [], NAMES),
        ])
        sw = _make_sweeper(repo, identify)
        r1 = sw.sweep()
        self.assertEqual(r1["untracked"]["status"], "session-attributed")
        self.assertEqual(sw._untracked_registry, {})
        # 归因消失：重新建档（first_seen 为本轮，不沿用旧计时）
        r2 = sw.sweep()
        self.assertEqual(r2["untracked"]["status"], "timed")
        entry = sw._untracked_registry[r2["untracked"]["fingerprint"]]
        self.assertLess(time.time() - entry["first_seen"], 60)
        # 豁免非永久：宽限耗尽照常升级
        entry["first_seen"] = time.time() - 25 * 3600
        self.assertEqual(sw.sweep()["untracked"]["status"], "escalated")
        self.assertEqual(len(_escalated(repo)), 1)

    def test_repeated_session_hit_keeps_resetting(self):
        """归因持续在场：每轮命中都复位计时，不升级不告警。"""
        repo = _make_untracked_repo()
        identify = _CountingIdentify([_session_info(NAMES)])
        sw = _make_sweeper(repo, identify, grace=0.0)
        for _ in range(3):
            r = sw.sweep()
            self.assertEqual(r["untracked"]["status"], "session-attributed")
        self.assertEqual(sw._untracked_registry, {})
        self.assertEqual(_escalated(repo), [])
        self.assertEqual(_alerts(repo, UNTRACKED_SIGNAL_TYPE), [])


class TestRealAttributionScenes(unittest.TestCase):
    """真实归因器现场（无 identify 替身，防替身与真实现场漂移）。"""

    def test_real_lane_holder_scene(self):
        """车道分支提交了与主树 untracked 同名的路径 → 真实现场 holder 命中。"""
        spec, ts = "spec-x", 1700000000
        run_id = f"impl-{spec}-{ts}"
        repo = _make_untracked_repo()
        base = repo.parent
        wt = base / run_id
        branch = f"fenix/{spec}-{ts}"
        _git("worktree", "add", "-b", branch, str(wt), "HEAD", cwd=repo)
        (wt / NAMES[0]).write_text("branch copy", encoding="utf-8")
        _git("add", "-A", cwd=wt)
        _git("commit", "-q", "-m", "branch stray", cwd=wt)
        sw = _make_sweeper(repo, grace=0.0)
        r = sw.sweep(running_run_ids=[run_id])
        u = r["untracked"]
        self.assertEqual(u["status"], "holder-attributed")
        self.assertEqual(u["holder_run_ids"], [run_id])
        self.assertEqual(sw._untracked_registry, {})
        self.assertEqual(_escalated(repo), [])

    def test_real_transcript_session_scene(self):
        """活跃 transcript 尾部路径提及 → 真实现场会话归因命中（mock home）。"""
        repo = _make_untracked_repo()
        home = Path(_mkdtemp("stray-attr-home-"))
        munged = str(repo).replace("/", "-").replace(".", "-")
        tdir = home / ".claude" / "projects" / munged
        tdir.mkdir(parents=True)
        (tdir / "session.jsonl").write_text(
            '{"text":"drafting ' + NAMES[1] + ' content"}', encoding="utf-8"
        )
        sw = _make_sweeper(repo, grace=0.0)
        with mock.patch(
            "core.worktree_manager.mergeback.Path.home", return_value=home
        ):
            r = sw.sweep()
        u = r["untracked"]
        self.assertEqual(u["status"], "session-attributed")
        self.assertEqual(
            u["session_signals"], ["transcript-active+path-mention"]
        )
        self.assertEqual(sw._untracked_registry, {})
        self.assertEqual(_escalated(repo), [])

    def test_real_zero_hit_escalation_annotates_and_manifest_parses(self):
        """真实现场零命中升级：evidence 注记在场、清单段解析不受追加段影响。"""
        repo = _make_untracked_repo()
        sw = _make_sweeper(repo)
        r1 = sw.sweep()
        sw._untracked_registry[r1["untracked"]["fingerprint"]][
            "first_seen"
        ] = time.time() - 25 * 3600
        self.assertEqual(sw.sweep()["untracked"]["status"], "escalated")
        esc = _escalated(repo)
        self.assertEqual(len(esc), 1)
        evidence = esc[0].get("evidence") or ""
        self.assertIn("归因探测已执行，零命中", evidence)
        from core.dashboard.data.admin_actions import parse_stray_wip_manifest

        self.assertEqual(parse_stray_wip_manifest(evidence), sorted(NAMES))


if __name__ == "__main__":
    unittest.main()
