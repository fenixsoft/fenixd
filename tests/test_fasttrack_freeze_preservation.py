"""fix-fasttrack-freeze-branch-preservation 回归测试。

覆盖（tasks 4.1/4.2/4.3）：

- S1 事故复现：fast-track 冻结前现场保全 → 冻结后分支 / ``_frozen_hold`` /
  branch + implementer_run 锚点 / pre-rmtree 快照 / 告警 evidence 保全摘要俱在
- S2 解冻续做闭环：``unfreeze_spec`` → ``_recovery_resume: True``、锚点保留、
  ``_frozen_hold`` 清除、分支未被弃
- S3 清理守护：孤儿清扫目录级守卫 + legacy 宽限期兜底回收守卫（冻结现场不被
  ``branch -D`` / rmtree，对照组照常回收证明删除链活性）
- S4 零提交退化：零未合并提交时不置 hold、不产快照，冻结照常完成
- S5 保全 IO 异常不阻断冻结：fail-open ERROR 审计 + 冻结/告警完整

夹具为真实 git 主树 + 真实 WorktreeManager（分支解析 / 快照 / 清扫 / 回收链
全走 git 真相），仅 fast-track lane 以最小壳对象承载 ``FFastTrackMixin``。
"""

import subprocess
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.pm_engine import PMEngine
from core.pm_engine.dispatch.fast_track import FFastTrackMixin
from core.state_machine import FROZEN_HOLD_FIELD, StateMachine
from core.worktree_manager import WorktreeManager


class _FakeLogger:
    """轻量日志捕获器：记录 (level, name, message) 供断言。"""

    def __init__(self):
        self.records = []

    def _rec(self, level, name, message, *args, **kw):
        self.records.append((level, name, str(message)))

    def info(self, name, message, *args, **kw):
        self._rec("info", name, message)

    def warning(self, name, message, *args, **kw):
        self._rec("warning", name, message)

    def error(self, name, message, *args, **kw):
        self._rec("error", name, message)

    def debug(self, name, message, *args, **kw):
        pass

    def has(self, level, fragment):
        return any(
            lvl == level and fragment in msg for lvl, _n, msg in self.records
        )


class _Lane(FFastTrackMixin):
    """最小 lane 壳：保全助手只消费 ``self._pm`` 四属性，不触及其他 mixin 方法。"""

    def __init__(self, pm):
        self._pm = pm


def _git(cwd, *args, check=True):
    r = subprocess.run(
        ["git", "-C", str(cwd)] + list(args), capture_output=True, text=True
    )
    if check and r.returncode != 0:
        raise AssertionError(f"git {args} failed: {r.stderr.strip()}")
    return r


def branch_exists(project_root, branch):
    return (
        subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "--verify", "--quiet",
             f"refs/heads/{branch}"],
            capture_output=True,
        ).returncode
        == 0
    )


class _Env:
    """真实 git 主树 + 真实 WorktreeManager + 最小 fast-track lane。"""

    def __init__(self, tmp_path: Path):
        self.project_root = tmp_path / "proj"
        self.project_root.mkdir()
        (self.project_root / ".fenix").mkdir()
        _git(self.project_root, "init", "-q")
        _git(self.project_root, "config", "user.email", "test@fenix.local")
        _git(self.project_root, "config", "user.name", "fenix-test")
        (self.project_root / "README.md").write_text("r\n", encoding="utf-8")
        _git(self.project_root, "add", "-A")
        _git(self.project_root, "commit", "-qm", "init")
        # rev-list/基线解析按 main 候选——初始分支强制归一（与既有夹具同口径）
        _git(self.project_root, "branch", "-M", "main")
        self.logger = _FakeLogger()
        self.sm = StateMachine(
            self.project_root / ".fenix" / "STATE.md", self.logger
        )
        base_dir = self.project_root / ".fenix" / "worktrees"
        base_dir.mkdir()
        # 进程扫描注入替身（无任何存活进程），避免 pgrep 环境依赖
        self.wm = WorktreeManager(
            base_dir, self.project_root, self.logger,
            process_scanner=lambda *a, **k: False,
        )
        runner = mock.MagicMock()
        runner.worktree_manager = self.wm
        self.engine = PMEngine(
            self.sm, runner, {}, self.project_root, self.logger
        )
        self.lane = _Lane(self.engine)
        self.alerts: list = []

    # ── 夹具动作 ──────────────────────────────────────────────────────
    def make_impl_worktree(self, spec, ts=1794000000, commits=1, dirty=False):
        """创建 ``impl-<spec>-<ts>`` worktree（fenix/<spec>-<ts> 分支，含实现提交）。"""
        wt_dir = self.wm.base_dir / f"impl-{spec}-{ts}"
        branch = f"fenix/{spec}-{ts}"
        _git(self.project_root, "worktree", "add", "-b", branch, str(wt_dir))
        for i in range(commits):
            (wt_dir / f"work_{i}.py").write_text(f"# impl {i}\n", encoding="utf-8")
            _git(wt_dir, "add", "-A")
            _git(wt_dir, "commit", "-qm", f"impl c{i}")
        if dirty and commits >= 1:
            # dirty 须含**已跟踪文件改动**：stash create 只快照已跟踪改动，
            # 纯 untracked 不产出快照 commit（lifecycle._snapshot_dirty_worktree）
            (wt_dir / "work_0.py").write_text("# impl 0 modified\n", encoding="utf-8")
            (wt_dir / "wip_untracked.txt").write_text("wip\n", encoding="utf-8")
        return wt_dir, branch

    def seed_spec(self, spec):
        self.sm.add_spec(spec, {"priority": 5})
        self.sm.transition(spec, "ready")
        self.sm.transition(spec, "implementing")

    def preserve(self, spec, wt, run_id="run-test"):
        result = mock.MagicMock()
        result.run_id = run_id
        result.worktree_path = str(wt)
        return self.lane.preserve_impl_site_before_freeze(spec, result=result)

    def preserve_note(self, spec, wt, run_id="run-test"):
        result = mock.MagicMock()
        result.run_id = run_id
        result.worktree_path = str(wt)
        return self.lane._freeze_preserve_note(spec, result=result)

    def freeze(self, spec, evidence):
        """机器冻结站点（四处 freeze_for_human 站点的同参形态），告警就地捕获。"""
        ok = self.sm.freeze_for_human(
            spec,
            error="fast-track 重试耗尽：连续 3 轮均失败",
            signal_type="fast_track_failure",
            severity="high",
            description="fast-track 失败重试耗尽，冻结转人工",
            evidence=evidence,
            recommended_action="人工排查实现分支并裁决解冻",
            alert_callback=lambda **kw: self.alerts.append(kw),
        )
        return ok

    def frozen_site(self, spec, run_id="run-test", commits=2, dirty=True):
        """保全 + 冻结的完整现场（S2/S3 复用）。Returns (wt_dir, branch)。"""
        wt, branch = self.make_impl_worktree(spec, commits=commits, dirty=dirty)
        self.seed_spec(spec)
        note = self.preserve_note(spec, wt, run_id=run_id)
        assert "现场保全" in note
        self.freeze(spec, evidence=f"失败现场; {note}")
        return wt, branch


# ── S1/S2（tasks 4.1，R1/R2/R4） ──────────────────────────────────────────────


class TestFreezePreservesImplSite:
    def test_s1_freeze_keeps_branch_hold_anchor_snapshot_alert(self, tmp_path):
        """冻结前保全 → 冻结后分支/hold/锚点/快照/告警证据俱在（事故不再复现）。"""
        env = _Env(tmp_path)
        wt, branch = env.make_impl_worktree("ftz1", commits=2, dirty=True)
        env.seed_spec("ftz1")

        summary = env.preserve("ftz1", wt, run_id="run-111")
        assert summary["preserved"] is True
        assert summary["branch"] == branch
        assert summary["ahead"] == 2
        assert summary["hold_written"] is True
        # dirty worktree → pre-rmtree 快照产出且对象库可达
        assert summary["snapshot_sha"]
        assert _git(
            env.project_root, "cat-file", "-t", summary["snapshot_sha"]
        ).stdout.strip() == "commit"

        # 单次原子写：hold + 锚点三键同窗落盘
        entry = env.sm.read_one("ftz1")
        assert entry[FROZEN_HOLD_FIELD] is True
        assert entry["branch"] == branch
        assert entry["implementer_run"] == "run-111"

        # 幂等：登记在册后重复保全不重复快照/写，note 走幂等分支
        note = env.preserve_note("ftz1", wt, run_id="run-111")
        assert "现场保全（幂等）" in note and branch in note

        # 冻结（evidence 按生产四站点同款拼装保全摘要）
        assert env.freeze("ftz1", evidence=f"重试耗尽失败现场; {note}") is True
        entry = env.sm.read_one("ftz1")
        assert entry["status"] == "blocked"
        assert entry["frozen"] is True
        # 冻结原子写不剥离保全标记与锚点（对照事故：branch 空 + 无 hold）
        assert entry[FROZEN_HOLD_FIELD] is True
        assert entry["branch"] == branch
        assert branch_exists(env.project_root, branch)

        # 告警 evidence 合并了保全摘要（人工可见 branch 定位）
        assert len(env.alerts) == 1
        assert branch in env.alerts[0]["evidence"]
        assert "现场保全" in env.alerts[0]["evidence"]

    def test_s2_unfreeze_resumes_on_preserved_branch(self, tmp_path):
        """解冻续做闭环：_recovery_resume 置位、锚点保留、hold 清除、分支未弃。"""
        env = _Env(tmp_path)
        spec = "ftz2"
        wt, branch = env.frozen_site(spec, run_id="run-222")

        assert env.sm.unfreeze_spec(
            spec, status="implementing",
            project_root=env.project_root, worktree_manager=env.wm,
        ) is True

        entry = env.sm.read_one(spec)
        assert entry["_recovery_resume"] is True
        assert entry[FROZEN_HOLD_FIELD] is False
        # 锚点保留：续做在同一分支而非从零新建（事故 13 提交的保住形态）
        assert entry["branch"] == branch
        assert entry["implementer_run"] == "run-222"
        assert entry["status"] == "implementing"
        assert entry["frozen"] is False
        assert branch_exists(env.project_root, branch)
        assert env.logger.has("warning", "Unfreeze resume")


# ── S3（tasks 4.2，R3） ───────────────────────────────────────────────────────


class TestCleanupGuardsKeepFrozenSite:
    def test_s3_stale_sweep_keeps_frozen_site(self, tmp_path):
        """孤儿清扫：冻结保全现场整目录保留（含分支），对照组照常清扫。"""
        env = _Env(tmp_path)
        spec = "ftz3"
        wt, branch = env.frozen_site(spec, run_id="run-333")
        # 对照组：非冻结 spec 的孤儿 impl 目录（无 STATE 条目）
        ctrl_wt, _ctrl_branch = env.make_impl_worktree(
            "orphanc", ts=1794000001, commits=0
        )

        env.wm.cleanup_stale_worktrees()

        assert wt.exists(), "冻结保全现场目录被孤儿清扫误删"
        assert branch_exists(env.project_root, branch)
        assert not ctrl_wt.exists(), "对照组未被清扫——守卫测试失去删除链活性证明"
        assert env.logger.has("warning", "冻结保全现场")
        assert env.logger.has(
            "warning", f"Skip stale worktree cleanup for 'impl-{spec}-1794000000'"
        )
        assert env.logger.has("info", "Cleaning up stale worktree")

    def test_s3_legacy_reclaim_keeps_frozen_site(self, tmp_path):
        """legacy 宽限期兜底回收：冻结现场过期遗产不被回收、记录保持在册。

        事故删除者即本链（findings 入口 1）：守护必须在出册前——记录被 pop
        即永久丢失、目录失去豁免反被孤儿清扫拾取。
        """
        env = _Env(tmp_path)
        spec = "ftz4"
        wt, branch = env.frozen_site(spec, run_id="run-444", dirty=False)
        env.wm.register_legacy(spec, wt, branch)
        env.wm._legacy[spec]["registered_at"] = time.time() - 3600
        # 对照组：非冻结 spec 的过期遗产 → 照常兜底回收
        ctrl_wt, ctrl_branch = env.make_impl_worktree(
            "orphanc2", ts=1794000003, commits=1
        )
        env.wm.register_legacy("orphanc2", ctrl_wt, ctrl_branch)
        env.wm._legacy["orphanc2"]["registered_at"] = time.time() - 3600

        reclaimed = env.wm._reclaim_expired_legacy()

        assert "ftz4" not in reclaimed
        assert "orphanc2" in reclaimed
        # 守卫在出册前：记录保持在册（豁免持续生效，解冻后自然放行）
        assert spec in env.wm._legacy
        assert wt.exists()
        assert branch_exists(env.project_root, branch)
        # 对照组删除链活性证明：目录与分支真被回收
        assert not ctrl_wt.exists()
        assert not branch_exists(env.project_root, ctrl_branch)
        assert env.logger.has("warning", f"Skip legacy reclaim for '{spec}'")


# ── S4/S5（tasks 4.3，R1 退化条款 / fail-open 条款） ─────────────────────────


class TestDegenerationAndFailOpen:
    def test_s4_zero_commit_degenerates_without_hold(self, tmp_path):
        """零未合并提交：不置 hold、不产快照、不写锚点，冻结照常完成。"""
        env = _Env(tmp_path)
        spec = "ftz5"
        wt, branch = env.make_impl_worktree(spec, commits=0, dirty=True)
        env.seed_spec(spec)

        summary = env.preserve(spec, wt, run_id="run-555")
        assert summary["preserved"] is False
        assert summary["ahead"] == 0
        assert summary["hold_written"] is False
        assert summary["snapshot_sha"] == ""

        entry = env.sm.read_one(spec)
        assert not entry.get(FROZEN_HOLD_FIELD)
        assert not entry.get("branch")

        note = env.preserve_note(spec, wt, run_id="run-555")
        assert "现场保全未执行" in note
        assert "零未合并提交" in note

        # 退化不阻断冻结链
        assert env.freeze(spec, evidence=f"失败现场; {note}") is True
        entry = env.sm.read_one(spec)
        assert entry["status"] == "blocked"
        assert entry["frozen"] is True
        assert len(env.alerts) == 1

    def test_s5_preserve_io_error_does_not_block_freeze(self, tmp_path):
        """保全 IO 异常：fail-open ERROR 审计后冻结/告警照常完整。"""
        env = _Env(tmp_path)
        spec = "ftz6"
        wt, _branch = env.make_impl_worktree(spec, commits=2, dirty=True)
        env.seed_spec(spec)

        with mock.patch.object(
            env.wm, "find_worktree_by_spec",
            side_effect=RuntimeError("git IO boom"),
        ):
            note = env.preserve_note(spec, wt, run_id="run-666")

        assert "现场保全失败" in note
        assert env.logger.has("error", "现场保全失败")
        entry = env.sm.read_one(spec)
        assert not entry.get(FROZEN_HOLD_FIELD)

        # 冻结与人工告警不受保全故障影响
        assert env.freeze(spec, evidence=f"失败现场; {note}") is True
        entry = env.sm.read_one(spec)
        assert entry["status"] == "blocked"
        assert entry["frozen"] is True
        assert len(env.alerts) == 1
        assert "现场保全失败" in env.alerts[0]["evidence"]
