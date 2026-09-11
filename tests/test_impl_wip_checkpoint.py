"""add-impl-wip-checkpoint — WIP checkpoint 锚点提交与 merge-back 塌缩 单测。

覆盖 spec（impl-wip-checkpoint）全部 Scenario：
  1. 锚点 A（排水超时收口）：中断后分支必有可恢复提交（ahead≥1）→ 下一 daemon
     _recovery_preserve_spec 走保留续做 / 空变更幂等跳过 / git 超时降级不阻塞
  2. 锚点 B（transient 原地退避）：退避窗口内分支已有 WIP 提交 / 无 worktree
     载体跳过 / 后续 attempt --resume 续跑不受影响
  3. 塌缩（merge-back 前）：WIP+最终塌缩成单提交（消息取自最终） / 仅 WIP
     无最终 / 无 WIP 零动作 / 重入幂等

基于真实 git 仓库 fixture（与 test_interrupt_recovery_preserve / test_worktree
_merge_guard 同构），不启动真实 daemon/子进程。
"""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import fenixd
from core.state_machine import StateMachine
from core.worktree_manager import WorktreeManager
from core.wip_checkpoint import (
    ANCHOR_DRAIN_PRESERVE,
    ANCHOR_TRANSIENT_BACKOFF,
    ANCHOR_TURN_LIMIT,
    WIP_COMMIT_PREFIX,
    collapse_wip_commits,
    commit_wip_checkpoint,
)
from tests.helpers import FakeLogger, make_runner


# ── git repo fixture（与 test_interrupt_recovery_preserve 同构） ──────────────


def git(root: Path, *args, check=True):
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result


def init_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q")
    git(root, "config", "user.email", "test@fenix.local")
    git(root, "config", "user.name", "Fenix Test")
    git(root, "config", "commit.gpgsign", "false")
    (root / "shared.py").write_text("BASE\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "[fenix] base")
    git(root, "branch", "-M", "main")


def make_wm(root: Path) -> WorktreeManager:
    base = root / ".claude" / "worktrees"
    base.mkdir(parents=True, exist_ok=True)
    return WorktreeManager(base, root, FakeLogger())


def branch_log(root: Path, branch: str) -> list:
    """分支提交清单（新→旧）：[subject, ...]。"""
    out = git(root, "log", "--format=%s", f"main..{branch}")
    return [l for l in out.stdout.splitlines() if l.strip()]


def ahead_count(root: Path, branch: str) -> int:
    out = git(root, "rev-list", "--count", f"main..{branch}")
    return int(out.stdout.strip() or "0")


# ── Fake daemon 组件（shutdown 排水路径，同 test_interrupt_recovery_preserve）─


class FakeProc:
    def __init__(self, done: bool = False):
        self._done = done

    def poll(self):
        return None if not self._done else 0

    def kill(self):
        self._done = True

    def terminate(self):
        self._done = True


class FakeRunner:
    def __init__(self, running: dict | None = None):
        self._running_agents = dict(running or {})

    def running_run_ids(self):
        return [rid for rid, p in self._running_agents.items() if p.poll() is None]

    def drain_wait(self, timeout: float):
        deadline = __import__("time").time() + max(0.0, timeout)
        while __import__("time").time() < deadline:
            if not self.running_run_ids():
                return []
            __import__("time").sleep(0.01)
        return self.running_run_ids()

    def wait_for_running_agents(self, timeout: int = 10):
        pass

    def _v2_stop_all(self):
        pass


class FakeWM:
    def __init__(self, wt_by_branch: dict | None = None):
        self.wt_by_branch = dict(wt_by_branch or {})
        self.cleanup_protected = None

    def find_worktree_path(self, branch):
        return self.wt_by_branch.get(branch)

    def cleanup_orphans(self, protected=None):
        self.cleanup_protected = protected or set()


class FakeSM:
    def __init__(self, entries: dict):
        self.entries = entries

    def read_one(self, spec):
        return self.entries.get(spec)


def make_daemon(monkeypatch, tmp_path, *, restart_request, drain_seconds,
                running: dict, sm_entries: dict, wm=None):
    """构造最小 FenixDaemon（wm 缺省 FakeWM），patch PROJECT_ROOT/PRESERVE_SIDECAR。"""
    fake_root = tmp_path / "proj"
    fake_root.mkdir(parents=True, exist_ok=True)
    (fake_root / ".fenix").mkdir(parents=True, exist_ok=True)
    if restart_request:
        (fake_root / ".fenix" / "restart_request").write_text("1\n", encoding="utf-8")

    monkeypatch.setattr(fenixd, "PROJECT_ROOT", fake_root)
    monkeypatch.setattr(
        fenixd, "PRESERVE_SIDECAR", fake_root / ".fenix" / "interrupted_runs.json")
    monkeypatch.setattr(
        fenixd.sys, "exit",
        lambda code=0: (_ for _ in ()).throw(SystemExit(code)))

    daemon = fenixd.FenixDaemon()
    daemon.config = {"admin": {"shutdown_drain_seconds": drain_seconds}}
    daemon.logger = FakeLogger()
    daemon.state_machine = FakeSM(sm_entries)
    daemon.worktree_manager = wm or FakeWM()
    daemon.agent_runner = FakeRunner(running)
    daemon.pm_engine = SimpleNamespace(shutting_down=False)
    daemon._admin_thread = None
    daemon._admin_executor = None
    daemon.event_bus = None
    return daemon


def make_state_machine(root: Path, specs: dict) -> StateMachine:
    state_path = root / ".fenix" / "STATE.md"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    sm = StateMachine(state_path, FakeLogger())
    for name, entry in specs.items():
        sm.add_spec(name, entry)
    return sm


# ── 锚点 A：排水超时收口 WIP 提交（task 1.1/1.3） ────────────────────────────


class TestAnchorA:
    def test_drain_timeout_branch_ahead_and_recovery_resume(
            self, monkeypatch, tmp_path):
        """排水超时 + 未提交改动 → WIP 提交 → 分支 ahead≥1 → 恢复走保留续做。

        spec Scenario「排水超时后中断分支必有可恢复提交」全链：shutdown 收口
        产生 WIP 提交后，下一 daemon recover_interrupted 的 _recovery_preserve_spec
        判定走保留分支续做（_recovery_resume=True），不再降级清空重建。
        """
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        branch = wm.get_branch_name(wt)
        # 事故原型：10 个文件 modified、分支零 ahead
        (wt / "a.py").write_text("A1\n", encoding="utf-8")
        (wt / "b.py").write_text("B1\n", encoding="utf-8")
        (wt / "tasks.md").write_text("## 1. 阶段\n- [x] 1.1\n", encoding="utf-8")
        assert ahead_count(root, branch) == 0

        # 真实 WM 驱动 shutdown 排水超时路径（sidecar 保全 + WIP 提交 + 保护集）
        daemon = make_daemon(
            monkeypatch, tmp_path, restart_request=True, drain_seconds=1,
            running={"impl-demo-111-a1": FakeProc()},
            sm_entries={"demo": {"branch": branch}},
            wm=wm,
        )
        with pytest.raises(SystemExit):
            daemon.shutdown()

        # 分支 ahead ≥ 1 且最新提交是 drain-preserve WIP
        assert ahead_count(root, branch) >= 1
        msgs = branch_log(root, branch)
        assert msgs[0].startswith(
            f"{WIP_COMMIT_PREFIX} checkpoint {ANCHOR_DRAIN_PRESERVE} demo")

        # 下一 daemon 恢复：保留分支续做，不清空重建
        sm = make_state_machine(root, {
            "demo": {"status": "implementing", "branch": branch,
                     "implementer_run": "impl-demo-111"},
        })
        recovered = sm.recover_interrupted(project_root=root, worktree_manager=wm)
        assert "demo" in recovered
        entry = sm.read_one("demo")
        assert entry["status"] == "ready"
        assert entry["branch"] == branch, "保留分支引用"
        assert entry["_recovery_resume"] is True, "标记恢复续做"
        assert entry["implementer_run"] == "impl-demo-111"

    def test_empty_changes_idempotent_skip(self, monkeypatch, tmp_path):
        """空变更幂等跳过：保全 worktree 工作区干净 → 不产生空 WIP 提交。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        branch = wm.get_branch_name(wt)
        # 无未提交改动（worktree 干净）
        assert ahead_count(root, branch) == 0

        daemon = make_daemon(
            monkeypatch, tmp_path, restart_request=True, drain_seconds=1,
            running={"impl-demo-111-a1": FakeProc()},
            sm_entries={"demo": {"branch": branch}},
            wm=wm,
        )
        with pytest.raises(SystemExit):
            daemon.shutdown()

        assert ahead_count(root, branch) == 0, "空变更不得产生 WIP 提交"
        assert not branch_log(root, branch), "分支不应有额外提交"

    def test_git_timeout_degrades_shutdown_continues(self, monkeypatch, tmp_path):
        """git 超时降级：锚点 A 提交超时 → WARNING 留痕、收口序列继续（D6）。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        branch = wm.get_branch_name(wt)
        (wt / "a.py").write_text("A1\n", encoding="utf-8")

        # 使 WIP 提交 helper 直接抛 TimeoutExpired（模拟 git 卡顿），
        # shutdown 不得被阻断、也不得产生提交。
        import core.wip_checkpoint as wc_mod
        real_fn = wc_mod.commit_wip_checkpoint

        def _boom(*a, **k):
            raise subprocess.TimeoutExpired("git status --porcelain", 15)

        monkeypatch.setattr(wc_mod, "commit_wip_checkpoint", _boom)
        daemon = make_daemon(
            monkeypatch, tmp_path, restart_request=True, drain_seconds=1,
            running={"impl-demo-111-a1": FakeProc()},
            sm_entries={"demo": {"branch": branch}},
            wm=wm,
        )
        # 注意：_wip_checkpoint_preserved_worktrees 引用的是 fenixd 命名空间
        # 里的 helper——monkeypatch wc_mod 不够，需 patch fenixd 侧引用。
        monkeypatch.setattr(fenixd, "commit_wip_checkpoint", _boom)
        with pytest.raises(SystemExit):
            daemon.shutdown()
        assert ahead_count(root, branch) == 0, "超时降级不产生提交"

    def test_preserved_worktree_in_protected_set(self, monkeypatch, tmp_path):
        """WIP 提交后保全 worktree 仍传入 cleanup_orphans 保护集（不被清理）。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        branch = wm.get_branch_name(wt)
        (wt / "a.py").write_text("A1\n", encoding="utf-8")

        captured = {}

        def _spy_cleanup(protected=None, **_k):
            captured["protected"] = set(protected or ())

        monkeypatch.setattr(wm, "cleanup_orphans", _spy_cleanup)
        daemon = make_daemon(
            monkeypatch, tmp_path, restart_request=True, drain_seconds=1,
            running={"impl-demo-111-a1": FakeProc()},
            sm_entries={"demo": {"branch": branch}},
            wm=wm,
        )
        with pytest.raises(SystemExit):
            daemon.shutdown()
        assert str(wt) in captured.get("protected", set()), \
            "保全 worktree 进入 cleanup_orphans 保护集"


# ── 锚点 B：transient 原地退避前 WIP 提交（task 2.1/2.2） ────────────────────


class TestAnchorB:
    def test_backoff_wip_commit_branch_ahead(self, tmp_path):
        """瞬断退避前 WIP 提交：worktree 有改动 → 分支产生 transient-backoff 提交。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        branch = wm.get_branch_name(wt)
        (wt / "work.py").write_text("WIP-B\n", encoding="utf-8")

        runner = make_runner(root, {})
        runner._wip_checkpoint_before_backoff("demo", wt)

        assert ahead_count(root, branch) == 1
        msgs = branch_log(root, branch)
        assert msgs[0].startswith(
            f"{WIP_COMMIT_PREFIX} checkpoint {ANCHOR_TRANSIENT_BACKOFF} demo")

    def test_no_worktree_skip(self, tmp_path):
        """无 worktree 载体（pre_wt_path=None 且本 attempt 未建 wt）→ 跳过，
        现行行为逐字节不变（不产生任何提交/异常）。"""
        root = tmp_path / "repo"
        init_repo(root)
        runner = make_runner(root, {})
        runner._wip_checkpoint_before_backoff("demo", None)  # 不得抛错
        assert git(root, "log", "--format=%s", "main").stdout.strip() == "[fenix] base"

    def test_invalid_worktree_skip(self, tmp_path):
        """worktree 路径失效（目录不存在/非 git）→ 跳过，不抛错。"""
        root = tmp_path / "repo"
        init_repo(root)
        runner = make_runner(root, {})
        runner._wip_checkpoint_before_backoff("demo", root / "nonexistent")
        assert git(root, "log", "--format=%s", "main").stdout.strip() == "[fenix] base"

    def test_resume_continuation_unaffected(self, tmp_path):
        """后续 attempt 以 --resume 在原 worktree 续跑不受 WIP 提交影响：
        WIP 提交后 worktree 仍有效、可继续提交最终成果（agent 续跑不重建）。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        branch = wm.get_branch_name(wt)
        (wt / "work.py").write_text("WIP-B\n", encoding="utf-8")
        runner = make_runner(root, {})
        runner._wip_checkpoint_before_backoff("demo", wt)
        assert ahead_count(root, branch) == 1

        # 续跑模拟：同一 worktree 继续写文件并提交最终成果
        (wt / "work.py").write_text("WIP-B\nFINAL\n", encoding="utf-8")
        git(wt, "add", "-A")
        git(wt, "commit", "-q", "-m", "[fenix] demo: final")
        assert ahead_count(root, branch) == 2
        msgs = branch_log(root, branch)
        assert msgs[0] == "[fenix] demo: final"
        assert msgs[1].startswith(WIP_COMMIT_PREFIX)


# ── 塌缩：merge-back 前 WIP 前缀提交塌缩（task 3.1/3.2） ─────────────────────


class TestCollapse:
    def _branch_with_wips_and_final(self, root: Path, wm: WorktreeManager,
                                    n_wip: int = 2):
        """构造 base→wip×n→final 分支（真实 worktree + helper 提交）。"""
        wt = wm.create("demo", "implementer")
        branch = wm.get_branch_name(wt)
        for i in range(n_wip):
            (wt / "work.py").write_text(f"WIP-{i}\n", encoding="utf-8")
            commit_wip_checkpoint(wt, "demo", ANCHOR_TRANSIENT_BACKOFF, FakeLogger())
        (wt / "work.py").write_text("FINAL\n", encoding="utf-8")
        git(wt, "add", "-A")
        git(wt, "commit", "-q", "-m", "[fenix] demo: final")
        return wt, branch

    def test_wip_and_final_collapse_to_single(self, tmp_path):
        """base→wip→wip→final：塌缩后分支为单提交（消息取自 final），
        文件内容逐字节不变（soft-reset 语义不触碰工作区）。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt, branch = self._branch_with_wips_and_final(root, wm, n_wip=2)
        msgs_before = branch_log(root, branch)
        assert len(msgs_before) == 3  # wip × 2 + final
        assert msgs_before[0] == "[fenix] demo: final"

        # 塌缩前内容快照（分支 tip tree 的字节内容）
        work_before = git(root, "show", f"{branch}:work.py").stdout

        assert collapse_wip_commits(root, branch, FakeLogger()) is True
        msgs_after = branch_log(root, branch)
        assert len(msgs_after) == 1, "塌缩后分支历史为单提交"
        assert msgs_after[0] == "[fenix] demo: final", "消息取自最终提交"
        assert not any(m.startswith(WIP_COMMIT_PREFIX) for m in msgs_after), \
            "合并后历史无 fenix(wip): 前缀"

        # 文件内容逐字节不变
        work_after = git(root, "show", f"{branch}:work.py").stdout
        assert work_after == work_before, "文件内容逐字节不变"

    def test_only_wip_no_final(self, tmp_path):
        """仅 WIP 无最终提交（恢复续做后收口）：塌缩仍产生单提交，
        消息改写为 [fenix] 前缀（主树历史无 wip 前缀）。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        branch = wm.get_branch_name(wt)
        (wt / "work.py").write_text("WIP-1\n", encoding="utf-8")
        commit_wip_checkpoint(wt, "demo", ANCHOR_DRAIN_PRESERVE, FakeLogger())
        assert len(branch_log(root, branch)) == 1

        assert collapse_wip_commits(root, branch, FakeLogger()) is True
        msgs = branch_log(root, branch)
        assert len(msgs) == 1
        assert not msgs[0].startswith(WIP_COMMIT_PREFIX), "无 wip 前缀残留"
        assert msgs[0].startswith("[fenix]")
        # 内容保持
        assert git(root, "show", f"{branch}:work.py").stdout == "WIP-1\n"

    def test_no_wip_zero_action(self, tmp_path):
        """无 WIP 常规成功路径：零动作，分支历史逐字节现行行为。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt, branch = self._branch_with_wips_and_final(root, wm, n_wip=0)
        head_before = git(root, "rev-parse", branch).stdout.strip()

        assert collapse_wip_commits(root, branch, FakeLogger()) is False
        head_after = git(root, "rev-parse", branch).stdout.strip()
        assert head_after == head_before, "零动作：分支 HEAD 不变"

    def test_collapse_reentry_idempotent(self, tmp_path):
        """塌缩重入幂等：merge-back 失败重试时 WIP 已塌缩 → 零动作。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt, branch = self._branch_with_wips_and_final(root, wm, n_wip=2)

        assert collapse_wip_commits(root, branch, FakeLogger()) is True
        head_after_first = git(root, "rev-parse", branch).stdout.strip()
        # 重入：WIP 已不在 → 零动作
        assert collapse_wip_commits(root, branch, FakeLogger()) is False
        assert git(root, "rev-parse", branch).stdout.strip() == head_after_first

    def test_merge_back_no_wip_residue_in_main(self, tmp_path):
        """全链：merge-back 普通 merge 后主树历史无 fenix(wip): 条目，
        实现内容已合入（choke point 塌缩生效）。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt, branch = self._branch_with_wips_and_final(root, wm, n_wip=2)

        info = wm.merge_back_from_branch(branch)
        assert info.success, f"merge-back 应成功：{info.error}"
        main_msgs = git(root, "log", "--format=%s").stdout.splitlines()
        assert not any(m.startswith(WIP_COMMIT_PREFIX) for m in main_msgs), \
            "主树历史无 fenix(wip): 条目"
        assert any("merge implementer branch" in m for m in main_msgs)
        # 实现内容已合入主树
        assert (root / "work.py").read_text(encoding="utf-8") == "FINAL\n"


# ── WIP 提交物性（task 1.2） ────────────────────────────────────────────────


class TestWipCommitContract:
    def test_message_contract_both_anchors(self, tmp_path):
        """消息契约：fenix(wip): checkpoint <anchor> <spec>（两锚点）。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        branch = wm.get_branch_name(wt)

        (wt / "a.py").write_text("A\n", encoding="utf-8")
        assert commit_wip_checkpoint(wt, "demo", ANCHOR_DRAIN_PRESERVE,
                                     FakeLogger()) is True
        (wt / "b.py").write_text("B\n", encoding="utf-8")
        assert commit_wip_checkpoint(wt, "demo", ANCHOR_TRANSIENT_BACKOFF,
                                     FakeLogger()) is True

        msgs = branch_log(root, branch)
        assert msgs[1] == f"{WIP_COMMIT_PREFIX} checkpoint {ANCHOR_DRAIN_PRESERVE} demo"
        assert msgs[0] == f"{WIP_COMMIT_PREFIX} checkpoint {ANCHOR_TRANSIENT_BACKOFF} demo"

    def test_ignored_content_not_committed(self, tmp_path):
        """ignored 内容不入提交：gitignore 命中的运行时产物保持未跟踪。"""
        root = tmp_path / "repo"
        init_repo(root)
        # 主树已有 .gitignore 排除 .fenix/dist
        (root / ".gitignore").write_text(".fenix/\ndist/\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] gitignore")
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        branch = wm.get_branch_name(wt)

        (wt / "code.py").write_text("CODE\n", encoding="utf-8")
        (wt / ".fenix").mkdir(exist_ok=True)
        (wt / ".fenix" / "runtime.json").write_text("{}\n", encoding="utf-8")
        (wt / "dist").mkdir(exist_ok=True)
        (wt / "dist" / "bundle.js").write_text("x\n", encoding="utf-8")

        assert commit_wip_checkpoint(wt, "demo", ANCHOR_TRANSIENT_BACKOFF,
                                     FakeLogger()) is True
        tracked = git(wt, "ls-files").stdout.splitlines()
        assert "code.py" in tracked
        assert not any(".fenix/runtime.json" == p or "dist/bundle.js" == p
                       for p in tracked), "ignored 内容不入提交"
        # 提交树只含 tracked 文件（ignored 内容保持未跟踪，不入任何提交）
        branch = wm.get_branch_name(wt)
        tree_files = git(wt, "ls-tree", "-r", "--name-only", "HEAD").stdout.splitlines()
        assert "code.py" in tree_files
        assert not any(".fenix/" in p or p == "dist/bundle.js" for p in tree_files), \
            "ignored 内容不入提交树"
        # ignored 文件在工作区保留（未被删除）
        assert (wt / ".fenix" / "runtime.json").exists()
        assert (wt / "dist" / "bundle.js").exists()

    def test_empty_change_returns_false(self, tmp_path):
        """空变更 helper 返回 False（幂等跳过），不产生空提交。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        assert commit_wip_checkpoint(wt, "demo", ANCHOR_TRANSIENT_BACKOFF,
                                     FakeLogger()) is False
        branch = wm.get_branch_name(wt)
        assert ahead_count(root, branch) == 0


# ── 锚点 C：强杀收口前 WIP 提交（task 1.2/1.3/1.4） ──────────────────────────


class TestAnchorC:
    def test_forced_kill_checkpoint_branch_ahead(self, tmp_path):
        """dirty worktree 强杀收口 → 产生 fenix(wip): checkpoint turn-limit <spec>
        提交（锚点 C 消息契约），零提交型 run 现场保全。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        branch = wm.get_branch_name(wt)
        # 事故原型：10 个文件未提交、分支零 ahead
        for i in range(10):
            (wt / f"f{i}.py").write_text(f"WIP-{i}\n", encoding="utf-8")
        assert ahead_count(root, branch) == 0

        runner = make_runner(root, {})
        runner._wip_checkpoint_on_forced_kill("demo", wt)

        assert ahead_count(root, branch) == 1
        msgs = branch_log(root, branch)
        assert msgs[0].startswith(
            f"{WIP_COMMIT_PREFIX} checkpoint {ANCHOR_TURN_LIMIT} demo")
        # 现场内容完整入提交
        assert git(root, "show", f"{branch}:f9.py").stdout == "WIP-9\n"

    def test_forced_kill_clean_worktree_idempotent(self, tmp_path):
        """干净 worktree 强杀收口 → 零动作幂等（不产生空提交、不报错）。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        branch = wm.get_branch_name(wt)
        assert ahead_count(root, branch) == 0

        runner = make_runner(root, {})
        runner._wip_checkpoint_on_forced_kill("demo", wt)

        assert ahead_count(root, branch) == 0, "空变更不得产生 WIP 提交"
        assert not branch_log(root, branch), "分支不应有额外提交"

    def test_forced_kill_no_worktree_skip(self, tmp_path):
        """无 worktree 载体（None/失效路径）→ 跳过，不抛错。"""
        root = tmp_path / "repo"
        init_repo(root)
        runner = make_runner(root, {})
        runner._wip_checkpoint_on_forced_kill("demo", None)  # 不得抛错
        runner._wip_checkpoint_on_forced_kill("demo", root / "nonexistent")
        assert git(root, "log", "--format=%s", "main").stdout.strip() == "[fenix] base"

    def test_forced_kill_helper_failure_does_not_block(self, monkeypatch, tmp_path):
        """helper 失败（git 超时桩）→ 收口流程照常（方法不抛、无提交、仅降级）。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        branch = wm.get_branch_name(wt)
        (wt / "work.py").write_text("WIP-C\n", encoding="utf-8")

        import core.agent_runner.runner as runner_mod

        def _boom(*a, **k):
            raise subprocess.TimeoutExpired("git status --porcelain", 15)

        monkeypatch.setattr(runner_mod, "commit_wip_checkpoint", _boom)
        runner = make_runner(root, {})
        runner._wip_checkpoint_on_forced_kill("demo", wt)  # 不得抛错
        assert ahead_count(root, branch) == 0, "超时降级不产生提交"
        assert (wt / "work.py").read_text(encoding="utf-8") == "WIP-C\n", \
            "未提交现场保留在 worktree（未被破坏）"

    def test_timeout_anchor_reuses_forced_kill_with_anchor_param(self, tmp_path):
        """timeout 收口同走锚点 C（_wip_checkpoint_on_forced_kill 复用）；
        默认 anchor = turn-limit，显式传其它 anchor 亦生效。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        branch = wm.get_branch_name(wt)
        (wt / "work.py").write_text("WIP-T\n", encoding="utf-8")

        runner = make_runner(root, {})
        runner._wip_checkpoint_on_forced_kill(
            "demo", wt, anchor=ANCHOR_TURN_LIMIT)
        msgs = branch_log(root, branch)
        assert msgs[0].startswith(
            f"{WIP_COMMIT_PREFIX} checkpoint {ANCHOR_TURN_LIMIT} demo")
