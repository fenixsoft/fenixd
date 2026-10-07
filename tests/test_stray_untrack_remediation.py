"""evo-recurring-stray-remediation 单测（tasks.md 3.2）。

进程内真实 git 仓库端到端覆盖：
- untrack_stray_wip 执行器：seed 被 track 的生成物文件 → 执行选项 → 文件
  脱离索引、.gitignore 增行（已存在/重复执行不重复写）、独立提交生成、
  结果含 untrack 清单与提交号；根治后同路径改动不再触发散件告警
- 守卫与回滚：非绑定信号零 git 写、清单外路径拒绝、外来 staged 条目中止
  后索引与 .gitignore 完整还原
- stray_wip 复发计数：同文件两次告警后 evidence 含「已 2 度处置」与根治
  指引（untrack 选项），首次告警维持「提交+建议」现状
"""

import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from core.admin_store import AdminStore, SIGNAL
from core.dashboard.data.admin_actions import execute_adjudication_choice
from core.dashboard.data.adjudication_choices import choices_for
from core.worktree_manager.stray_wip import SIGNAL_TYPE, MainTreeStrayWipSweeper

# /tmp 可能被外部清扫进程周期性清空（test_maintree_stray_wip_sweep 同款
# 规避）。统一用仓库内 .history/tmp（gitignored），MUST NOT 改写全局
# tempfile.tempdir。
_HISTORY_TMP = Path(__file__).resolve().parent.parent / ".history" / "tmp"
_HISTORY_TMP.mkdir(parents=True, exist_ok=True)

_BOUND_SIGNAL_TYPE = "maintree_stray_wip_stale"
_SIBLING_INFO_SIGNAL = "maintree_untracked_stray_stale"
_UNTRACKED_ESCALATED = "maintree_untracked_stray_escalated"


def _mkdtemp(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix, dir=str(_HISTORY_TMP)))


def _git(*args, cwd, check=True):
    r = subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=str(cwd), check=check, capture_output=True, text=True,
    )
    return r.stdout


def _head(repo) -> str:
    return _git("rev-parse", "HEAD", cwd=repo).strip()


def _status(repo) -> str:
    return _git("status", "--porcelain", cwd=repo)


def _ls_files(repo) -> set:
    return {p for p in _git("ls-files", "-z", cwd=repo).split("\0") if p}


def _make_repo(gitignore_extra: str = "") -> Path:
    """主树仓：被 track 的生成物日志 + .fenix 状态目录。

    - `build-win-configure.log` 已入库基线（生成物类复发散件原型）；
    - `keep.txt` 全场无改动（反例对照，永不被裹挟出库）；
    - gitignore_extra 供预置既有 ignore 规则（去重口径用例）；
    - 仓级提交身份（执行器裸 `git commit` 需要）与 `_git` 旗标身份刻意错开
      ——会话归因候选②按「仓级配置身份 ≈ 近窗提交身份」判命中，两身份
      一致会把测试散件误归因为交互会话（session-attributed 吞掉告警路径）。
    """
    repo = _mkdtemp("stray-untrack-") / "proj"
    repo.mkdir(parents=True)
    _git("init", "-q", cwd=repo)
    _git("config", "user.email", "config-bot@example.com", cwd=repo)
    _git("config", "user.name", "config-bot", cwd=repo)
    (repo / ".gitignore").write_text(".fenix/\n", encoding="utf-8")
    (repo / "build-win-configure.log").write_text("baseline", encoding="utf-8")
    (repo / "keep.txt").write_text("keep", encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "init", cwd=repo)
    if gitignore_extra:
        # 既有 ignore 规则在基线入库【之后】追加——先 ignore 后 add -A 会让
        # 生成物从未被 track，整个用例前提（被 track 的复发散件）不成立。
        with open(repo / ".gitignore", "a", encoding="utf-8") as f:
            f.write(gitignore_extra)
        _git("add", ".gitignore", cwd=repo)
        _git("commit", "-q", "-m", "gitignore rules", cwd=repo)
    (repo / ".fenix").mkdir()
    return repo


def _make_stray(repo: Path, files=("build-win-configure.log",)) -> None:
    """制造散件 WIP：生成物日志被构建重写（tracked 未提交改动）。"""
    for f in files:
        (repo / f).write_text(f"rebuilt-{time.time_ns()}", encoding="utf-8")


def _seed_stale_signal(repo, files, signal_type=_BOUND_SIGNAL_TYPE) -> None:
    """写入一条带「文件清单(N):」段的散件 WIP SIGNAL 记录（发射点同款 evidence）。"""
    AdminStore(repo).append({
        "kind": SIGNAL,
        "signal_type": signal_type,
        "spec": None,
        "severity": "major",
        "description": "主树散件 WIP 滞留",
        "evidence": (
            "项目名=proj; first_seen=2026-10-07T00:00:00+00:00; "
            f"文件清单({len(files)}): {', '.join(files) or '无'}; "
            "零触碰注记: 本盘点只读"
        ),
        "recommended_action": "",
    })


def _stale_alerts(repo) -> list:
    """SIGNAL_TYPE 告警记录（read_all 倒序返回 → 本列表最新在前）。"""
    return [
        r
        for r in AdminStore(repo).read_all()
        if r.get("kind") == SIGNAL and r.get("signal_type") == SIGNAL_TYPE
    ]


class _WmProbe:
    """WorktreeManager 探针壳：混入盘点所需 mixin（真实实现，非替身）。

    test_maintree_stray_wip_sweep._WmProbe 同款装配（sweep 依赖
    _main_tree_lock、_list_dirty_tracked_files 与 identify_wip_occupant）。
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


def _make_sweeper(repo, grace=30.0) -> MainTreeStrayWipSweeper:
    cfg = {"admin": {"maintree_stray_wip_grace_minutes": grace}}
    return MainTreeStrayWipSweeper(repo, _WmProbe(repo), config=cfg)


def _sweep_alert(repo, grace=30.0) -> dict:
    """把建档 first_seen 拨回宽限之外再盘一轮，返回本轮摘要（触发告警）。"""
    sw = _make_sweeper(repo, grace=grace)
    r = sw.sweep()
    assert r is not None and r["status"] in ("orphan-timed", "timed", "alerted"), r
    if r["status"] != "alerted":
        fp = r["fingerprint"]
        sw._registry[fp]["first_seen"] = time.time() - 3600
        r = sw.sweep()
    assert r["status"] == "alerted", r
    return r


class TestUntrackExecutorE2E(unittest.TestCase):
    """untrack_stray_wip 端到端（spec「一键根治生成物日志」场景）。"""

    def test_untrack_detaches_index_appends_gitignore_and_commits(self):
        repo = _make_repo()
        _make_stray(repo)
        _seed_stale_signal(repo, ["build-win-configure.log"])
        before_head = _head(repo)

        r = execute_adjudication_choice(
            str(repo), None, "untrack_stray_wip", signal_type=_BOUND_SIGNAL_TYPE,
        )
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["action"], "untrack_stray_wip")
        # 结果记录 untrack 文件清单与提交号（任务 1.2 契约）
        self.assertEqual(r["untracked_files"], ["build-win-configure.log"])
        self.assertEqual(r["gitignore_appended"], ["build-win-configure.log"])
        self.assertEqual(r["commit_hash"], _head(repo))
        self.assertNotEqual(r["commit_hash"], before_head)
        self.assertTrue(any(r["commit_hash"] in s for s in r["steps"]))
        # 文件脱离 git 索引，工作区内容原样保留（出库不删文件）
        self.assertNotIn("build-win-configure.log", _ls_files(repo))
        self.assertEqual(
            (repo / "build-win-configure.log").read_text(encoding="utf-8").startswith("rebuilt-"),
            True,
        )
        # .gitignore 增行（恰一条）+ 独立提交生成（不在 before_head 上）
        gi_lines = (repo / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertEqual(gi_lines.count("build-win-configure.log"), 1)
        # 此后该路径改动被 ignore 吸收：状态面无该文件、不再产生散件告警
        # （store 仅剩执行前 seed 的那一条 SIGNAL 记录，根治后盘点零新增）
        self.assertNotIn("build-win-configure.log", _status(repo))
        sw = _make_sweeper(repo)
        self.assertEqual(sw.sweep()["status"], "clean")
        self.assertEqual(len(_stale_alerts(repo)), 1)
        # 清单外文件 keep.txt 不被裹挟出库
        self.assertIn("keep.txt", _ls_files(repo))

    def test_preexisting_gitignore_line_not_duplicated(self):
        """「已存在则去重」：.gitignore 既有同名条目（或通配已覆盖）时不重复写。"""
        # 字面行已存在
        repo = _make_repo(gitignore_extra="build-win-configure.log\n")
        _make_stray(repo)
        _seed_stale_signal(repo, ["build-win-configure.log"])
        r = execute_adjudication_choice(
            str(repo), None, "untrack_stray_wip", signal_type=_BOUND_SIGNAL_TYPE,
        )
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["gitignore_appended"], [])
        gi_lines = (repo / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertEqual(gi_lines.count("build-win-configure.log"), 1)
        self.assertTrue(any("无需追加" in s for s in r["steps"]))

        # 通配规则已覆盖（check-ignore 口径去重）
        repo2 = _make_repo(gitignore_extra="*.log\n")
        _make_stray(repo2)
        _seed_stale_signal(repo2, ["build-win-configure.log"])
        r2 = execute_adjudication_choice(
            str(repo2), None, "untrack_stray_wip", signal_type=_BOUND_SIGNAL_TYPE,
        )
        self.assertTrue(r2["ok"], r2.get("error"))
        self.assertEqual(r2["gitignore_appended"], [])
        self.assertEqual(
            (repo2 / ".gitignore").read_text(encoding="utf-8").splitlines().count("*.log"), 1
        )

    def test_repeat_execution_rejected_without_duplicate_line(self):
        """重复执行（幂等重入）：清单内文件均已脱离索引 → 明确 error、零 git
        写、.gitignore 不重复增行。"""
        repo = _make_repo()
        _make_stray(repo)
        _seed_stale_signal(repo, ["build-win-configure.log"])
        first = execute_adjudication_choice(
            str(repo), None, "untrack_stray_wip", signal_type=_BOUND_SIGNAL_TYPE,
        )
        self.assertTrue(first["ok"], first.get("error"))
        head_after_first, status_after_first = _head(repo), _status(repo)

        _seed_stale_signal(repo, ["build-win-configure.log"])  # 在途新告警再选根治
        second = execute_adjudication_choice(
            str(repo), None, "untrack_stray_wip", signal_type=_BOUND_SIGNAL_TYPE,
        )
        self.assertFalse(second["ok"])
        self.assertIn("均已不在 git 索引", second["error"])
        self.assertEqual(_head(repo), head_after_first)   # 无空提交
        self.assertEqual(_status(repo), status_after_first)
        gi_lines = (repo / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertEqual(gi_lines.count("build-win-configure.log"), 1)

    def test_wrong_signal_type_rejected_zero_git_write(self):
        """signal_type 绑定守卫：姊妹 info 信号/未注册信号一律拒绝且零 git 写。"""
        repo = _make_repo()
        _make_stray(repo)
        _seed_stale_signal(repo, ["build-win-configure.log"])
        before_head, before_status = _head(repo), _status(repo)
        for st in (_SIBLING_INFO_SIGNAL, "daemon_errors", "random_unregistered", ""):
            r = execute_adjudication_choice(
                str(repo), None, "untrack_stray_wip", signal_type=st,
            )
            self.assertFalse(r["ok"], f"signal_type={st!r} 应拒绝")
            self.assertIn("仅限", r["error"])
        self.assertEqual(_head(repo), before_head)
        self.assertEqual(_status(repo), before_status)

    def test_out_of_manifest_paths_rejected(self):
        """程序化 paths 收窄：清单外路径拒绝，零 git 写。"""
        from core.dashboard.data.admin_actions import _exec_untrack_stray_wip

        repo = _make_repo()
        _make_stray(repo)
        _seed_stale_signal(repo, ["build-win-configure.log"])
        before_head, before_status = _head(repo), _status(repo)
        r = _exec_untrack_stray_wip(
            str(repo), signal_type=_BOUND_SIGNAL_TYPE, paths=["keep.txt"],
        )
        self.assertFalse(r["ok"])
        self.assertIn("清单外", r["error"])
        self.assertEqual(_head(repo), before_head)
        self.assertEqual(_status(repo), before_status)

    def test_foreign_staged_entry_aborts_and_rolls_back(self):
        """staged 子集守卫（stash_guard 骨架同口径）：索引存在本次作用面之外
        的暂存条目 → 中止，已 rm --cached 的索引态与 .gitignore 完整还原。"""
        repo = _make_repo()
        _make_stray(repo)
        _seed_stale_signal(repo, ["build-win-configure.log"])
        (repo / "keep.txt").write_text("foreign-staged", encoding="utf-8")
        _git("add", "keep.txt", cwd=repo)   # 外来 staged 条目
        before_head, before_status = _head(repo), _status(repo)
        before_gi = (repo / ".gitignore").read_bytes()

        r = execute_adjudication_choice(
            str(repo), None, "untrack_stray_wip", signal_type=_BOUND_SIGNAL_TYPE,
        )
        self.assertFalse(r["ok"])
        self.assertIn("已回滚", r["error"])
        self.assertIn("keep.txt", r["error"])
        self.assertEqual(_head(repo), before_head)                 # 无半程提交
        self.assertIn("build-win-configure.log", _ls_files(repo))  # 索引态还原
        self.assertEqual(_status(repo), before_status)             # 外来 staged 保留
        self.assertEqual((repo / ".gitignore").read_bytes(), before_gi)

    def test_stale_manifest_entry_skipped(self):
        """清单中已不在当刻 status 的文件跳过不报错（清单陈旧语义对齐 commit 执行器）。"""
        repo = _make_repo()
        _make_stray(repo)
        _seed_stale_signal(repo, ["build-win-configure.log", "gone.txt"])
        r = execute_adjudication_choice(
            str(repo), None, "untrack_stray_wip", signal_type=_BOUND_SIGNAL_TYPE,
        )
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["untracked_files"], ["build-win-configure.log"])
        self.assertTrue(any("gone.txt" in s for s in r["steps"]))

    def test_missing_signal_record_rejected_before_git_write(self):
        """无可解析清单的信号记录：明确 error，不执行 git 写。"""
        repo = _make_repo()
        _make_stray(repo)
        before_head, before_status = _head(repo), _status(repo)
        r = execute_adjudication_choice(
            str(repo), None, "untrack_stray_wip", signal_type=_BOUND_SIGNAL_TYPE,
        )
        self.assertFalse(r["ok"])
        self.assertIn("文件清单", r["error"])
        self.assertEqual(_head(repo), before_head)
        self.assertEqual(_status(repo), before_status)

    def test_alert_choices_snapshot_carries_both_options(self):
        """发射点 choices 快照含提交与根治两项（注册表单源，告警即历史事实）。"""
        repo = _make_repo()
        _make_stray(repo)
        _sweep_alert(repo)
        alerts = _stale_alerts(repo)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(
            [c.get("id") for c in alerts[0].get("choices") or []],
            [c["id"] for c in choices_for(_BOUND_SIGNAL_TYPE)],
        )


class TestRecurrenceCount(unittest.TestCase):
    """stray_wip 复发计数（任务 2.1）：同文件第 2 次告警带「已 N 度处置」。"""

    def test_first_alert_has_no_count(self):
        """首次告警维持现状：无复发注记，recommended_action 保持「提交+建议」。"""
        repo = _make_repo()
        _make_stray(repo)
        _sweep_alert(repo)
        alerts = _stale_alerts(repo)
        self.assertEqual(len(alerts), 1)
        self.assertNotIn("度处置", alerts[0]["evidence"])
        self.assertIn("git add/commit", alerts[0]["recommended_action"])

    def test_second_alert_carries_count_and_remediation_guidance(self):
        """同文件两次告警后 evidence 含「已 2 度处置」与根治指引（untrack 选项）。"""
        repo = _make_repo()
        # 第一轮：告警 → 模拟处置（提交散件，基线入库）
        _make_stray(repo)
        _sweep_alert(repo)
        self.assertEqual(len(_stale_alerts(repo)), 1)
        _git("add", "build-win-configure.log", cwd=repo)
        _git("commit", "-q", "-m", "fix: commit stray log", cwd=repo)

        # 第二轮：同文件再次被构建重写 → 复发再告警
        _make_stray(repo)
        _sweep_alert(repo)
        alerts = _stale_alerts(repo)
        self.assertEqual(len(alerts), 2)
        second = alerts[0]   # read_all 倒序 → 最新在前
        self.assertIn("已 2 度处置", second["evidence"])
        self.assertIn("untrack_stray_wip", second["evidence"])
        self.assertIn("根治", second["evidence"])
        self.assertIn("untrack_stray_wip", second["recommended_action"])
        self.assertIn("根治", second["recommended_action"])

    def test_third_alert_count_grows(self):
        """第三轮计数持续增长（已 3 度处置），不封顶不重置。"""
        repo = _make_repo()
        for _ in range(3):
            _make_stray(repo)
            _sweep_alert(repo)
            _git("add", "build-win-configure.log", cwd=repo)
            _git("commit", "-q", "-m", "fix: commit stray log", cwd=repo)
        alerts = _stale_alerts(repo)
        self.assertEqual(len(alerts), 3)
        # read_all 倒序 → alerts[0]=第 3 轮、alerts[1]=第 2 轮、alerts[2]=第 1 轮
        self.assertIn("已 3 度处置", alerts[0]["evidence"])
        self.assertIn("已 2 度处置", alerts[1]["evidence"])
        self.assertNotIn("度处置", alerts[2]["evidence"])

    def test_different_file_not_counted(self):
        """同文件口径：历史告警只对清单交集文件计数，异文件新敞口从 1 起算。"""
        repo = _make_repo()
        _make_stray(repo)
        _sweep_alert(repo)
        _git("add", "build-win-configure.log", cwd=repo)
        _git("commit", "-q", "-m", "fix", cwd=repo)
        (repo / "other-artifact.log").write_text("baseline", encoding="utf-8")
        _git("add", "other-artifact.log", cwd=repo)
        _git("commit", "-q", "-m", "add other artifact", cwd=repo)

        _make_stray(repo, files=("other-artifact.log",))
        _sweep_alert(repo)
        alerts = _stale_alerts(repo)
        self.assertEqual(len(alerts), 2)
        self.assertNotIn("度处置", alerts[0]["evidence"])   # 最新一条（异文件）


def _seed_escalation_signal(repo, files) -> None:
    """写入一条 untracked 升级 SIGNAL 记录（evidence 段级口径与发射点同款）。"""
    AdminStore(repo).append({
        "kind": SIGNAL,
        "signal_type": _UNTRACKED_ESCALATED,
        "spec": None,
        "severity": "major",
        "description": "主树 untracked 散件滞留升级",
        "evidence": (
            "项目名=proj; first_seen=2026-10-07T00:00:00+00:00; "
            f"文件清单({len(files)}): {', '.join(files) or '无'}; "
            "升级触发: 集合体积≥阈值"
        ),
        "recommended_action": "",
    })


def _write_untracked_stray(repo: Path, files) -> None:
    """制造 untracked 散件（纯新增文件，不触碰 tracked 基线）。"""
    for f in files:
        p = repo / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"stray-{time.time_ns()}", encoding="utf-8")


class TestUntrackedClaimExecutor(unittest.TestCase):
    """untracked 散件认领执行器（evo-stray-untracked-escalation 4.2）：
    tracked 桶信号拒绝零 git 写 + 归档/ignore/删除三裁决落盘行为。"""

    STRAYS = ["stray_dump.log", "sub/nested.log"]

    def _repo_with_strays(self, seed=True) -> Path:
        repo = _make_repo()
        _write_untracked_stray(repo, self.STRAYS)
        if seed:
            _seed_escalation_signal(repo, self.STRAYS)
        return repo

    # ── D4 绑定守卫：tracked 桶 / info / 未注册信号一律拒绝零写 ──────────

    def test_tracked_and_info_signals_rejected_zero_git_write(self):
        """spec 验收场景 1：以 tracked 桶信号调用认领执行器，在任何 git
        读/写之前 fail-closed 拒绝，零 git 写零文件触碰。三执行器逐一覆盖。"""
        from core.dashboard.data.admin_actions import (
            _exec_archive_untracked_stray,
            _exec_delete_untracked_stray,
            _exec_ignore_untracked_stray,
        )

        repo = self._repo_with_strays()
        # 同清单升级记录在册：拒绝只能来自绑定守卫，不能是「无记录」分支
        _seed_escalation_signal(repo, self.STRAYS)
        before_head, before_status = _head(repo), _status(repo)
        for st in (_BOUND_SIGNAL_TYPE, _SIBLING_INFO_SIGNAL,
                   "daemon_errors", "random_unregistered", ""):
            for exec_fn, cid in (
                (_exec_archive_untracked_stray, "archive_untracked_stray"),
                (_exec_ignore_untracked_stray, "ignore_untracked_stray"),
                (_exec_delete_untracked_stray, "delete_untracked_stray"),
            ):
                r = exec_fn(str(repo), signal_type=st)
                self.assertFalse(r["ok"], f"{cid} signal_type={st!r} 应拒绝")
                self.assertIn("仅限", r["error"])
        # 零 git 写（HEAD/status 逐字节一致）+ 零文件触碰
        self.assertEqual(_head(repo), before_head)
        self.assertEqual(_status(repo), before_status)
        for f in self.STRAYS:
            self.assertTrue((repo / f).exists(), f)

    def test_dispatch_level_guards(self):
        """dispatch 层双守卫：tracked 桶信号（已注册桶）在 resolve_choice
        阶段即拒 not-in-bucket；未注册信号经非作用域全表反查可达执行器，
        由执行器白名单收口（design D4 同款双层）。"""
        repo = self._repo_with_strays()
        before_head, before_status = _head(repo), _status(repo)
        # tracked 桶已注册桶内无本动作：resolve 层拒（错误含「不在信号」）
        r = execute_adjudication_choice(
            str(repo), None, "archive_untracked_stray",
            signal_type=_BOUND_SIGNAL_TYPE,
        )
        self.assertFalse(r["ok"])
        self.assertIn("选项集", r["error"])
        # 未注册信号反查可达：执行器白名单收口（错误含「仅限」）
        r2 = execute_adjudication_choice(
            str(repo), None, "delete_untracked_stray",
            signal_type="random_unregistered",
        )
        self.assertFalse(r2["ok"])
        self.assertIn("仅限", r2["error"])
        self.assertEqual(_head(repo), before_head)
        self.assertEqual(_status(repo), before_status)
        self.assertTrue((repo / self.STRAYS[0]).exists())

    # ── 裁决① 显式归档 ──────────────────────────────────────────────

    def test_archive_moves_files_into_registered_dir(self):
        repo = self._repo_with_strays()
        before_head = _head(repo)
        r = execute_adjudication_choice(
            str(repo), None, "archive_untracked_stray",
            signal_type=_UNTRACKED_ESCALATED,
        )
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["action"], "archive_untracked_stray")
        # 移入登记目录时间戳子目录，保留相对路径结构
        arch = repo / r["archive_dir"]
        self.assertTrue(arch.is_dir())
        self.assertTrue((arch / "stray_dump.log").is_file())
        self.assertTrue((arch / "sub" / "nested.log").is_file())
        for f in self.STRAYS:
            self.assertFalse((repo / f).exists())
        # 登记目录已被 .fenix/ 既有规则覆盖：去重不追加、无提交（HEAD 不动）
        self.assertEqual(r["gitignore_appended"], [])
        self.assertEqual(r["commit_hash"], "")
        self.assertEqual(_head(repo), before_head)
        self.assertIn(".fenix/stray-archive/", str(r["archive_dir"]))
        # 归档产物不计入后续 untracked 盘点（登记目录已被 ignore 覆盖）
        sw = _make_sweeper(repo)
        sweep = sw.sweep()
        self.assertNotIn("untracked", sweep)

    def test_archive_registers_dir_when_not_covered_by_rules(self):
        """无忽略规则项目：登记目录追加 .gitignore 并以 pathspec 独立提交
        （归档产物 MUST NOT 再进 untracked 盘点——裁决不自我循环）。"""
        repo = self._repo_with_strays(seed=False)
        _git("rm", "-q", "--cached", ".gitignore", cwd=repo)  # .gitignore 出库
        (repo / ".gitignore").unlink()
        _git("commit", "-q", "-am", "drop gitignore", cwd=repo)
        _seed_escalation_signal(repo, self.STRAYS)
        before_head = _head(repo)
        r = execute_adjudication_choice(
            str(repo), None, "archive_untracked_stray",
            signal_type=_UNTRACKED_ESCALATED,
        )
        self.assertTrue(r["ok"], r.get("error"))
        # 登记目录追加 + 独立提交落地
        self.assertEqual(r["gitignore_appended"], [".fenix/stray-archive/"])
        self.assertNotEqual(r["commit_hash"], before_head)
        self.assertTrue(any("独立提交" in s for s in r["steps"]))
        gi_lines = (repo / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertEqual(gi_lines.count(".fenix/stray-archive/"), 1)
        # 归档产物不再计入 untracked 盘点（登记目录 ignore 生效；.fenix/
        # 状态目录散件不在本用例豁免范围、按 below-threshold 计入属预期）
        sw = _make_sweeper(repo)
        sweep = sw.sweep()
        u = sweep.get("untracked") or {}
        self.assertNotIn(
            f"{r['archive_dir']}/stray_dump.log", u.get("files") or [],
        )

    def test_archive_stale_manifest_entries_skipped(self):
        """清单内已不在磁盘的文件跳过不报错（同指纹一次性告警，清单陈旧）。"""
        repo = self._repo_with_strays(seed=False)
        _seed_escalation_signal(repo, self.STRAYS + ["gone.txt"])
        r = execute_adjudication_choice(
            str(repo), None, "archive_untracked_stray",
            signal_type=_UNTRACKED_ESCALATED,
        )
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["archived_files"], self.STRAYS)
        self.assertTrue(any("gone.txt" in s for s in r["steps"]))

    def test_archive_all_missing_rejected(self):
        repo = self._repo_with_strays(seed=False)
        _seed_escalation_signal(repo, ["gone.txt"])
        r = execute_adjudication_choice(
            str(repo), None, "archive_untracked_stray",
            signal_type=_UNTRACKED_ESCALATED,
        )
        self.assertFalse(r["ok"])
        self.assertIn("均已不在磁盘", r["error"])

    # ── 裁决② 追加 .gitignore ────────────────────────────────────────

    def test_ignore_verdict_appends_dedups_and_commits(self):
        repo = self._repo_with_strays()
        before_head = _head(repo)
        r = execute_adjudication_choice(
            str(repo), None, "ignore_untracked_stray",
            signal_type=_UNTRACKED_ESCALATED,
        )
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["action"], "ignore_untracked_stray")
        # 去重追加（清单两路径各恰一条）+ 独立提交落地
        self.assertEqual(r["gitignore_appended"], self.STRAYS)
        self.assertNotEqual(r["commit_hash"], before_head)
        gi_lines = (repo / ".gitignore").read_text(encoding="utf-8").splitlines()
        for f in self.STRAYS:
            self.assertEqual(gi_lines.count(f), 1, f)
        # 此后散件被 ignore 吸收：不再计入 untracked 盘点（.fenix/ 状态
        # 目录散件不在本用例豁免范围，仍按 below-threshold 计入属预期）
        sw = _make_sweeper(repo)
        u = (sw.sweep().get("untracked") or {})
        for f in self.STRAYS:
            self.assertNotIn(f, u.get("files") or [])
        # 幂等重入：再次执行无新增、无空提交
        _seed_escalation_signal(repo, self.STRAYS)
        r2 = execute_adjudication_choice(
            str(repo), None, "ignore_untracked_stray",
            signal_type=_UNTRACKED_ESCALATED,
        )
        self.assertTrue(r2["ok"], r2.get("error"))
        self.assertEqual(r2["gitignore_appended"], [])
        self.assertTrue(any("无需追加" in s for s in r2["steps"]))
        self.assertEqual(_head(repo), r["commit_hash"])   # 无空提交

    def test_ignore_verdict_wildcard_covered_not_duplicated(self):
        """既有通配规则已覆盖：不重复写（check-ignore 口径去重）。"""
        repo = _make_repo(gitignore_extra="*.log\n")
        _write_untracked_stray(repo, ["stray_dump.log"])
        _seed_escalation_signal(repo, ["stray_dump.log"])
        r = execute_adjudication_choice(
            str(repo), None, "ignore_untracked_stray",
            signal_type=_UNTRACKED_ESCALATED,
        )
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["gitignore_appended"], [])
        self.assertEqual(
            (repo / ".gitignore").read_text(encoding="utf-8").splitlines().count("*.log"),
            1,
        )

    # ── 裁决③ 删除 ──────────────────────────────────────────────────

    def test_delete_verdict_removes_files_only(self):
        repo = self._repo_with_strays(seed=False)
        _seed_escalation_signal(repo, self.STRAYS + ["gone.txt"])
        before_head = _head(repo)
        r = execute_adjudication_choice(
            str(repo), None, "delete_untracked_stray",
            signal_type=_UNTRACKED_ESCALATED,
        )
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["action"], "delete_untracked_stray")
        self.assertEqual(r["deleted_files"], self.STRAYS)
        for f in self.STRAYS:
            self.assertFalse((repo / f).exists())
        # 陈旧清单条目跳过；清单外 tracked 文件不裹挟
        self.assertTrue(any("gone.txt" in s for s in r["steps"]))
        self.assertTrue((repo / "keep.txt").exists())
        # 零 git 写：HEAD 不动（删除 untracked 文件本就不经 git，status 的
        # 变化即裁决自身的落盘效果——散件行消失、keep.txt 无改动行）
        self.assertEqual(_head(repo), before_head)
        after = _status(repo)
        self.assertNotIn("stray_dump.log", after)
        self.assertNotIn("nested.log", after)
        self.assertNotIn("keep.txt", after)

    def test_delete_rejects_non_regular_file(self):
        """防御性收口：清单命中目录时拒绝删除（仅普通文件，不 rmtree）。"""
        from core.dashboard.data.admin_actions import _exec_delete_untracked_stray

        repo = self._repo_with_strays(seed=False)
        _seed_escalation_signal(repo, ["sub"])
        before_status = _status(repo)
        r = _exec_delete_untracked_stray(str(repo), signal_type=_UNTRACKED_ESCALATED)
        self.assertFalse(r["ok"])
        self.assertIn("非普通文件", r["error"])
        self.assertTrue((repo / "sub").is_dir())
        self.assertEqual(_status(repo), before_status)

    def test_delete_all_missing_rejected(self):
        repo = self._repo_with_strays(seed=False)
        _seed_escalation_signal(repo, ["gone.txt"])
        before_head = _head(repo)
        r = execute_adjudication_choice(
            str(repo), None, "delete_untracked_stray",
            signal_type=_UNTRACKED_ESCALATED,
        )
        self.assertFalse(r["ok"])
        self.assertIn("均已不在磁盘", r["error"])
        self.assertEqual(_head(repo), before_head)

    # ── 共用前置守卫 ─────────────────────────────────────────────────

    def test_out_of_manifest_paths_rejected(self):
        """程序化 paths 收窄：清单外路径拒绝，零 git 写零文件触碰。"""
        from core.dashboard.data.admin_actions import _exec_delete_untracked_stray

        repo = self._repo_with_strays()
        before_head, before_status = _head(repo), _status(repo)
        r = _exec_delete_untracked_stray(
            str(repo), signal_type=_UNTRACKED_ESCALATED, paths=["keep.txt"],
        )
        self.assertFalse(r["ok"])
        self.assertIn("清单外", r["error"])
        self.assertEqual(_head(repo), before_head)
        self.assertEqual(_status(repo), before_status)
        self.assertTrue((repo / "keep.txt").exists())

    def test_missing_signal_record_rejected_before_any_write(self):
        """无可解析清单的升级记录：明确 error，不执行任何写。"""
        repo = self._repo_with_strays(seed=False)
        before_head, before_status = _head(repo), _status(repo)
        r = execute_adjudication_choice(
            str(repo), None, "archive_untracked_stray",
            signal_type=_UNTRACKED_ESCALATED,
        )
        self.assertFalse(r["ok"])
        self.assertIn("文件清单", r["error"])
        self.assertEqual(_head(repo), before_head)
        self.assertEqual(_status(repo), before_status)
        self.assertTrue((repo / self.STRAYS[0]).exists())

    def test_escalation_choices_registered(self):
        """升级桶登记三裁决（注册表单源）：id/action 齐备、删除项 destructive、
        全部 spec_scoped=False（全局信号硬约束）。"""
        by_id = {c["id"]: c for c in choices_for(_UNTRACKED_ESCALATED)}
        self.assertEqual(
            sorted(by_id),
            ["archive_untracked_stray", "delete_untracked_stray",
             "ignore_untracked_stray"],
        )
        for c in by_id.values():
            self.assertTrue(c["label"].strip() and c["desc"].strip())
            self.assertFalse(c["spec_scoped"])
            self.assertEqual(c["action"], c["id"])
        self.assertTrue(by_id["delete_untracked_stray"].get("destructive") is True)
        self.assertFalse(by_id["archive_untracked_stray"].get("destructive", False))
        self.assertFalse(by_id["ignore_untracked_stray"].get("destructive", False))


if __name__ == "__main__":
    unittest.main()
