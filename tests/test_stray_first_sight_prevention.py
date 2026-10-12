"""evo-stray-first-sight-prevention 单测（tasks.md 3.1/3.2）。

覆盖：
- 首现触发（3.1）：新目录集合首现提示（低于 entry 阈值也提示——below_
  threshold 静默缺口填补）、gitignore 已覆盖目录不提示、顶层散文件与既有
  tracked 目录内散文件不在首现面
- 去重与复位（3.1）：同目录仅提示一次（集合内容增长/跨阈值档指纹漂移后
  仍不重提示）、目录整轮不再贡献条目复位后再现重提示（逐目录粒度）、
  跨 daemon 重启不重复提示、持久化文件 legacy 扁平形态迁移
- 非回归（3.2）：既有 maintree_untracked_stray_stale/escalated 升级路径与
  阈值语义不变（首现提示在场不改变判定），首现提示不进入 STORED_SIGNAL_
  TYPES 自动唤起收录、两表登记在册
"""

import json
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from core.admin_monitor import (
    SIGNAL_RECOMMENDATION,
    SIGNAL_SEVERITY,
    STORED_SIGNAL_TYPES,
)
from core.admin_store import AdminStore, SIGNAL
from core.worktree_manager.stray_wip import (
    UNTRACKED_ESCALATED_SIGNAL_TYPE,
    UNTRACKED_FIRST_SIGHT_SIGNAL_TYPE,
    UNTRACKED_REGISTRY_RELPATH,
    UNTRACKED_SIGNAL_TYPE,
    MainTreeStrayWipSweeper,
)

# /tmp 可能被外部清扫进程周期性清空（test_verify_evidence_placement 同款规避）。
_HISTORY_TMP = Path(__file__).resolve().parent.parent / ".history" / "tmp"
_HISTORY_TMP.mkdir(parents=True, exist_ok=True)


def _mkdtemp(prefix: str) -> str:
    return tempfile.mkdtemp(prefix=prefix, dir=str(_HISTORY_TMP))


def _git(*args, cwd, check=True):
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=str(cwd), check=check, capture_output=True, text=True,
    )


class _WmProbe:
    """WorktreeManager 探针壳（test_verify_evidence_placement 同款装配）。"""

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


def _make_repo(ignore_rules: str = ".fenix/*\n!.fenix/verify.yaml\n") -> Path:
    """主树仓：a/b.tsx 已提交；.gitignore 可定制（判据现场）。"""
    base = Path(_mkdtemp("first-sight-scene-"))
    repo = base / "proj"
    repo.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", cwd=repo)
    (repo / "a.tsx").write_text("base", encoding="utf-8")
    (repo / "b.tsx").write_text("base", encoding="utf-8")
    (repo / ".gitignore").write_text(ignore_rules, encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "init", cwd=repo)
    return repo


def _make_sweeper(repo, grace=30.0, threshold=None) -> MainTreeStrayWipSweeper:
    cfg = {"admin": {"maintree_stray_wip_grace_minutes": grace}}
    if threshold is not None:
        cfg["admin"]["maintree_untracked_stray_threshold"] = threshold
    return MainTreeStrayWipSweeper(repo, _WmProbe(repo), config=cfg, logger=None)


def _write_strays(repo, names):
    for n in names:
        p = repo / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"stray {n}\n", encoding="utf-8")


def _first_sight_alerts(repo) -> list:
    return [
        r
        for r in AdminStore(repo).read_all()
        if r.get("kind") == SIGNAL
        and r.get("signal_type") == UNTRACKED_FIRST_SIGHT_SIGNAL_TYPE
    ]


def _registry(repo) -> dict:
    return json.loads(
        (repo / UNTRACKED_REGISTRY_RELPATH).read_text(encoding="utf-8")
    )


def _write_registry(repo, data: dict) -> None:
    (repo / UNTRACKED_REGISTRY_RELPATH).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


class TestFirstSightTrigger(unittest.TestCase):
    """首现触发（3.1）：新目录集合、低于阈值也提示、豁免形态不提示。"""

    def test_new_dir_collection_prompted_below_threshold(self):
        """新目录集合首现：2 entry（低于缺省阈值 5）也提示，evidence 齐备。"""
        repo = _make_repo()
        _write_strays(repo, [".debug/a.log", ".debug/b.log"])
        sw = _make_sweeper(repo, grace=30.0)
        r = sw.sweep()
        self.assertEqual(r["untracked"]["status"], "below-threshold")
        fs = r["untracked"]["first_sight"]
        self.assertEqual(fs["status"], "prompted")
        self.assertEqual(fs["dirs"], [".debug"])
        alerts = _first_sight_alerts(repo)
        self.assertEqual(len(alerts), 1)
        rec = alerts[0]
        self.assertEqual(rec["severity"], "info")
        evidence = rec.get("evidence") or ""
        self.assertIn("项目名=proj", evidence)
        self.assertIn("目录集合=.debug", evidence)
        self.assertIn("文件清单(2): .debug/a.log, .debug/b.log", evidence)
        self.assertIn("体积合计=", evidence)
        # 预防性 gitignore 草案行 + 成因注释
        self.assertIn("gitignore草案: .debug/", evidence)
        self.assertIn("成因注释:", evidence)
        self.assertIn("预防性 ignore", evidence)
        # 首现登记随持久化落盘（目录键分区），同轮不重复提示
        persisted = _registry(repo)
        self.assertIn(".debug", persisted["first_sight_dirs"])
        self.assertEqual(
            persisted["first_sight_dirs"][".debug"]["files"],
            [".debug/a.log", ".debug/b.log"],
        )
        fs2 = sw.sweep()["untracked"]["first_sight"]
        self.assertEqual(fs2["status"], "clean")
        self.assertEqual(len(_first_sight_alerts(repo)), 1)

    def test_ignored_dir_not_prompted(self):
        """已被 .gitignore 覆盖的目录：不入散件清单（豁免②），不计首现。"""
        repo = _make_repo(ignore_rules=".fenix/*\n!.fenix/verify.yaml\nbuild/\n")
        _write_strays(repo, ["build/x.log", "build/y.log"])
        r = _make_sweeper(repo, grace=30.0).sweep()
        self.assertIsNone(r.get("untracked"))  # 零散件＝无 untracked 键
        self.assertEqual(_first_sight_alerts(repo), [])
        self.assertEqual(_registry(repo)["first_sight_dirs"], {})

    def test_top_level_and_tracked_dir_strays_not_in_surface(self):
        """顶层散文件与既有 tracked 目录内散文件不在首现面（仍走既有阈值流）。"""
        repo = _make_repo()
        (repo / "src").mkdir()
        (repo / "src" / "main.ts").write_text("code", encoding="utf-8")
        _git("add", "-A", cwd=repo)
        _git("commit", "-q", "-m", "add src", cwd=repo)
        _write_strays(repo, ["loose.log", "src/notes.txt"])
        sw = _make_sweeper(repo, grace=30.0)
        r = sw.sweep()
        # 两个散件仍入既有阈值流（below-threshold 计时）
        self.assertEqual(r["untracked"]["status"], "below-threshold")
        self.assertEqual(r["untracked"]["count"], 2)
        fs = r["untracked"]["first_sight"]
        self.assertEqual(fs["status"], "clean")
        self.assertEqual(fs["dirs"], [])
        self.assertEqual(_first_sight_alerts(repo), [])

    def test_nested_new_dir_uses_shallowest_untracked_ancestor(self):
        """嵌套新建目录：规范化根目录取最浅全 untracked 祖先（归组单键）。"""
        repo = _make_repo()
        _write_strays(repo, ["dist/js/a.js", "dist/js/sub/b.js", "dist/css/c.css"])
        r = _make_sweeper(repo, grace=30.0).sweep()
        fs = r["untracked"]["first_sight"]
        self.assertEqual(fs["status"], "prompted")
        self.assertEqual(fs["dirs"], ["dist"])
        evidence = (_first_sight_alerts(repo)[0]).get("evidence") or ""
        self.assertIn("文件清单(3):", evidence)
        self.assertIn("gitignore草案: dist/", evidence)


class TestFirstSightDedupAndReset(unittest.TestCase):
    """去重与复位（3.1）：同目录一次、增长不重提示、复位后再现、跨重启。"""

    def test_same_dir_once_across_growth_and_threshold_crossing(self):
        """同目录仅提示一次：条目增长与跨阈值档（指纹漂移）都不重提示。"""
        repo = _make_repo()
        _write_strays(repo, [".debug/a.log"])
        sw = _make_sweeper(repo, grace=30.0, threshold=2)
        r1 = sw.sweep()
        self.assertEqual(r1["untracked"]["status"], "below-threshold")
        self.assertEqual(r1["untracked"]["first_sight"]["status"], "prompted")
        # 条目增长跨过阈值档：fp 由路径级升级为内容级（指纹漂移），不重提示
        _write_strays(repo, [".debug/b.log"])
        r2 = sw.sweep()
        self.assertNotEqual(r2["untracked"]["status"], "below-threshold")
        self.assertEqual(r2["untracked"]["first_sight"]["status"], "clean")
        self.assertEqual(len(_first_sight_alerts(repo)), 1)
        # 内容演化（内容级指纹漂移）与继续增长同样不重提示
        (repo / ".debug" / "a.log").write_text("grown\n", encoding="utf-8")
        _write_strays(repo, [".debug/c.log"])
        r3 = sw.sweep()
        self.assertEqual(r3["untracked"]["first_sight"]["status"], "clean")
        self.assertEqual(len(_first_sight_alerts(repo)), 1)

    def test_full_absence_resets_then_new_first_sight(self):
        """目录整轮不再贡献条目即复位（零散件轮），复位后再现视为新首现。"""
        repo = _make_repo()
        _write_strays(repo, [".debug/a.log", ".debug/b.log"])
        r1 = _make_sweeper(repo, grace=30.0).sweep()
        self.assertEqual(r1["untracked"]["first_sight"]["status"], "prompted")
        # 全部删除 → 零散件轮：首现登记整表复位（目录消失走既有复位逻辑）
        for n in (".debug/a.log", ".debug/b.log"):
            (repo / n).unlink()
        r2 = _make_sweeper(repo, grace=30.0).sweep()
        self.assertIsNone(r2.get("untracked"))
        self.assertEqual(_registry(repo)["first_sight_dirs"], {})
        # 复位后再现 → 新首现、再次提示（复发场景正是提示价值所在）
        _write_strays(repo, [".debug/a.log", ".debug/b.log"])
        r3 = _make_sweeper(repo, grace=30.0).sweep()
        self.assertEqual(r3["untracked"]["first_sight"]["status"], "prompted")
        self.assertEqual(len(_first_sight_alerts(repo)), 2)

    def test_per_dir_reset_only_when_dir_stops_contributing(self):
        """复位粒度为目录：仅消失目录复位、其余目录登记保留不重提示。"""
        repo = _make_repo()
        _write_strays(repo, [".debug/a.log", ".cache/x.log"])
        r1 = _make_sweeper(repo, grace=30.0).sweep()
        self.assertEqual(sorted(r1["untracked"]["first_sight"]["dirs"]),
                         [".cache", ".debug"])
        self.assertEqual(len(_first_sight_alerts(repo)), 2)
        # 仅 .cache 消失：.cache 复位，.debug 登记保留
        (repo / ".cache" / "x.log").unlink()
        _make_sweeper(repo, grace=30.0).sweep()
        self.assertEqual(set(_registry(repo)["first_sight_dirs"]), {".debug"})
        # .cache 再现 → 新首现；.debug 不重提示
        _write_strays(repo, [".cache/y.log"])
        r3 = _make_sweeper(repo, grace=30.0).sweep()
        fs = r3["untracked"]["first_sight"]
        self.assertEqual(fs["status"], "prompted")
        self.assertEqual(fs["prompted"], [".cache"])
        self.assertEqual(len(_first_sight_alerts(repo)), 3)

    def test_no_reprompt_across_restart(self):
        """跨 daemon 重启（新 sweeper 实例＝新进程内存态）不重复提示。"""
        repo = _make_repo()
        _write_strays(repo, [".debug/a.log"])
        r1 = _make_sweeper(repo, grace=30.0).sweep()
        self.assertEqual(r1["untracked"]["first_sight"]["status"], "prompted")
        self.assertEqual(len(_first_sight_alerts(repo)), 1)
        # 重启：登记自持久化分区恢复，同目录不因重启而再次提示
        r2 = _make_sweeper(repo, grace=30.0).sweep()
        self.assertEqual(r2["untracked"]["first_sight"]["status"], "clean")
        self.assertEqual(len(_first_sight_alerts(repo)), 1)

    def test_legacy_flat_registry_file_migrates(self):
        """旧版扁平形态（顶层即指纹→条目）载入按 legacy 适配：时钟连续。"""
        repo = _make_repo()
        _write_strays(repo, [f"verify-evidence/r{i}.md" for i in range(6)])
        sw = _make_sweeper(repo, grace=30.0)
        fp = sw.sweep()["untracked"]["fingerprint"]
        new_format = _registry(repo)
        # 回写旧版扁平形态（evo-stray-first-sight-prevention 之前的文件形态）
        _write_registry(repo, new_format["untracked"])
        sw2 = _make_sweeper(repo, grace=30.0)
        r2 = sw2.sweep()
        self.assertEqual(r2["untracked"]["fingerprint"], fp)
        # 时钟连续：first_seen 自 legacy 形态恢复（未重新起算）
        self.assertEqual(
            r2["untracked"]["first_seen_iso"],
            new_format["untracked"][fp]["first_seen_iso"],
        )
        # 首现登记 legacy 迁移后空表起步（旧文件无此分区）→ 该目录按新首现
        # 重新登记一次（迁移语义：旧文件不携带首现知识，重启后补一次提示）
        self.assertEqual(sorted(sw2._first_sight_dirs), ["verify-evidence"])
        self.assertEqual(r2["untracked"]["first_sight"]["status"], "prompted")


class TestNonRegressionPins(unittest.TestCase):
    """非回归钉住（3.2）：升级路径与阈值语义不变、不进自动唤起收录。"""

    def test_stale_and_escalated_paths_unchanged_with_first_sight(self):
        """首现提示在场不改变既有 info→24h 升级判定：stale/escalated 照常。"""
        repo = _make_repo()
        _write_strays(repo, [f"verify-evidence/r{i}.md" for i in range(6)])
        sw = _make_sweeper(repo, grace=30.0)
        r1 = sw.sweep()
        fp = r1["untracked"]["fingerprint"]
        # 首现提示与既有流并存：新目录集合同轮提示一次
        self.assertEqual(r1["untracked"]["first_sight"]["status"], "prompted")
        self.assertEqual(len(_first_sight_alerts(repo)), 1)
        self.assertEqual(r1["untracked"]["status"], "timed")  # 宽限内
        # 注入超宽限旧时钟 → 一次性 info 告警照常（阈值/宽限语义不变）
        data = _registry(repo)
        data["untracked"][fp]["first_seen"] = time.time() - 2 * 3600
        _write_registry(repo, data)
        r2 = _make_sweeper(repo, grace=30.0).sweep()
        self.assertEqual(r2["untracked"]["status"], "alerted")
        stale_alerts = [
            x for x in AdminStore(repo).read_all()
            if x.get("signal_type") == UNTRACKED_SIGNAL_TYPE
        ]
        self.assertEqual(len(stale_alerts), 1)
        # 注入 ≥24h 旧时钟 → 第二档升级照常；首现提示不重发、不影响判定
        data = _registry(repo)
        data["untracked"][fp]["first_seen"] = (
            time.time() - (24 * 60 + 5) * 60
        )
        _write_registry(repo, data)
        r3 = _make_sweeper(repo, grace=30.0).sweep()
        self.assertEqual(r3["untracked"]["status"], "escalated")
        self.assertTrue(r3["untracked"]["escalated_signal"])
        escalated = [
            x for x in AdminStore(repo).read_all()
            if x.get("signal_type") == UNTRACKED_ESCALATED_SIGNAL_TYPE
        ]
        self.assertEqual(len(escalated), 1)
        self.assertEqual(len(_first_sight_alerts(repo)), 1)  # 仅首现那一次

    def test_first_sight_not_stored_and_registered_in_two_tables(self):
        """首现提示两表登记在册（info），MUST NOT 收录 STORED_SIGNAL_TYPES。"""
        self.assertIn(
            UNTRACKED_FIRST_SIGHT_SIGNAL_TYPE, SIGNAL_SEVERITY
        )
        self.assertEqual(
            SIGNAL_SEVERITY[UNTRACKED_FIRST_SIGHT_SIGNAL_TYPE], "info"
        )
        self.assertIn(
            UNTRACKED_FIRST_SIGHT_SIGNAL_TYPE, SIGNAL_RECOMMENDATION
        )
        self.assertNotIn(
            UNTRACKED_FIRST_SIGHT_SIGNAL_TYPE, STORED_SIGNAL_TYPES
        )


if __name__ == "__main__":
    unittest.main()
