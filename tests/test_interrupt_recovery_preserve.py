"""interrupt-recovery-preserve — 中断恢复保全 单测。

覆盖 spec（interrupt-recovery-preserve）全部 Scenario：
  1. 规划性重启排水：排水等待在跑 run 终态 / 排水超时按现行流程收口 / 非计划零变化
  2. 终止前保全：sidecar 先于 terminate 落盘（spec/run_id/branch/worktree/ahead_commits）
  3. 恢复保留分支续做：有提交分支保留 / 零提交走现行清空 / worktree 缺失重建
  4. 清理协调：保全 worktree 不被误删（cleanup_orphans 保护集 + boot 保留判定先于清理）
  5. worktree 可用性单源：is_available 三态 + 三链路判定一致

基于真实 git 仓库 fixture（与 test_worktree_reuse 同构）+ 最小 Fake daemon
（shutdown 排水路径），不启动真实 daemon/子进程。
"""

import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import fenixd
from core.state_machine import StateMachine
from core.worktree_manager import (
    WorktreeManager,
    WT_AVAILABLE,
    WT_REBUILDABLE,
    WT_UNAVAILABLE,
)

from test_agent_runner import FakeLogger


# ── git repo fixture（与 test_worktree_reuse 同构） ──────────────────────────


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


def add_commit(root: Path, rel: str, content: str, msg: str) -> None:
    """在指定路径写文件并 commit（git -C root 工作区提交）。"""
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", msg)


def make_state_machine(root: Path, specs: dict) -> StateMachine:
    state_path = root / ".fenix" / "STATE.md"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    sm = StateMachine(state_path, FakeLogger())
    for name, entry in specs.items():
        sm.add_spec(name, entry)
    return sm


# ── Fake daemon 组件（shutdown 排水路径） ────────────────────────────────────


class FakeProc:
    """可控完成时机的伪进程：poll() 在 release 后返回非 None。"""

    def __init__(self, done: bool = False):
        self._done = done
        self.killed = False

    def poll(self):
        return None if not self._done else 0

    def kill(self):
        self.killed = True
        self._done = True

    def terminate(self):
        self._done = True


class FakeRunner:
    def __init__(self, running: dict | None = None):
        self._running_agents = dict(running or {})
        self._lane_processes = {}
        self.terminate_calls = 0
        self.drain_calls = []
        self.checkpoint_broadcasts = []
        self.lane_terminate_calls = []

    def broadcast_restart_checkpoint(self, reason="planned restart"):
        """对齐 runner 真实契约：向在飞 run 广播 checkpoint 旗标（写即返回）。"""
        dispatched = self.running_run_ids()
        self.checkpoint_broadcasts.append((reason, list(dispatched)))
        return dispatched

    def running_run_ids(self):
        return [rid for rid, p in self._running_agents.items() if p.poll() is None]

    # ── 车道登记 API（planned-restart-drain 2.1 契约镜像） ──────────────

    def register_lane_process(self, key, proc, done_event=None):
        self._lane_processes[key] = (proc, done_event)

    def unregister_lane_process(self, key):
        self._lane_processes.pop(key, None)

    def running_lane_ids(self):
        return [
            k for k, (p, _e) in self._lane_processes.items() if p.poll() is None
        ]

    def terminate_lane_processes(self, grace: float = 10):
        done = []
        for k, (p, _e) in list(self._lane_processes.items()):
            if p.poll() is None:
                p.terminate()
                done.append(k)
        self.lane_terminate_calls.append(done)
        return done

    def drain_wait(self, timeout: float):
        self.drain_calls.append(timeout)
        # 替身在飞 run 永不在窗内自然终态，全窗自旋只烧真时间不产生观感差异
        # （断言只看 drain_calls 记录的窗口值）——真实自旋封顶 0.2s。
        deadline = time.time() + min(max(0.0, timeout), 0.2)
        while time.time() < deadline:
            remaining = self.running_run_ids()
            if not remaining and not self.running_lane_ids():
                return []
            time.sleep(0.02)
        return self.running_run_ids()

    def wait_for_running_agents(self, timeout: int = 10):
        self.terminate_calls += 1

    def _v2_stop_all(self):
        pass


class FakeWM:
    def __init__(self, wt_by_branch: dict | None = None,
                 spec_to_wt: dict | None = None):
        self.wt_by_branch = dict(wt_by_branch or {})
        self.cleanup_protected = None
        # spec → (wt_path, branch) 映射：find_worktree_by_spec 回落查询用
        self._spec_to_wt = dict(spec_to_wt or {})

    def find_worktree_path(self, branch):
        return self.wt_by_branch.get(branch)

    def find_worktree_by_spec(self, spec_name):
        return self._spec_to_wt.get(spec_name)

    def cleanup_orphans(self, protected=None):
        self.cleanup_protected = protected or set()


class FakeSM:
    def __init__(self, entries: dict):
        self.entries = entries

    def read_one(self, spec):
        return self.entries.get(spec)


def make_daemon(monkeypatch, tmp_path, *, restart_request, drain_seconds,
                running: dict, sm_entries: dict, wt_by_branch: dict | None = None,
                spec_to_wt: dict | None = None, run_drain_seconds=None):
    """构造最小 FenixDaemon 并 patch 关键路径，返回 (daemon, fake_runner, fake_wm)。"""
    fake_root = tmp_path / "proj"
    fake_root.mkdir(parents=True, exist_ok=True)
    (fake_root / ".fenix").mkdir(parents=True, exist_ok=True)
    if restart_request:
        (fake_root / ".fenix" / "restart_request").write_text("1\n", encoding="utf-8")

    monkeypatch.setattr(fenixd, "PROJECT_ROOT", fake_root)
    monkeypatch.setattr(fenixd, "PRESERVE_SIDECAR", fake_root / ".fenix" / "interrupted_runs.json")
    monkeypatch.setattr(fenixd.sys, "exit", lambda code=0: (_ for _ in ()).throw(SystemExit(code)))

    daemon = fenixd.FenixDaemon()
    # restart 排水窗口单源 agents.run_drain_max_seconds（pipeline-throughput
    # 3.1），常规停机仍走 admin.shutdown_drain_seconds；夹紧规则下两值一致时
    # 窗口=传入值，语义与既有断言兼容。run_drain_seconds 显式给出时与
    # shutdown_drain_seconds 解耦（planned-restart-drain 3.2：规划性豁免分支
    # 需要两值独立取型）。
    daemon.config = {
        "admin": {"shutdown_drain_seconds": drain_seconds},
        "agents": {"run_drain_max_seconds":
                   drain_seconds if run_drain_seconds is None else run_drain_seconds},
    }
    daemon.logger = FakeLogger()
    daemon.state_machine = FakeSM(sm_entries)
    daemon.worktree_manager = FakeWM(wt_by_branch, spec_to_wt)
    daemon.agent_runner = FakeRunner(running)
    daemon.pm_engine = SimpleNamespace(shutting_down=False)
    daemon._admin_thread = None
    daemon._admin_executor = None
    daemon.event_bus = None
    return daemon, daemon.agent_runner, daemon.worktree_manager


# ── 1. worktree 可用性单源（is_available 三态） ─────────────────────────────


class TestIsAvailable:
    def test_available_in_place(self, tmp_path):
        """三态 available：目录在场 + git worktree 注册有效 + 分支可解析。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        branch = wm.get_branch_name(wt)
        assert wm.is_available(wt, branch) == WT_AVAILABLE
        assert wm.is_available(branch=branch) == WT_AVAILABLE

    def test_rebuildable_when_dir_removed(self, tmp_path):
        """三态 rebuildable：目录被外部删除但分支仍在 → 可从分支重建。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        branch = wm.get_branch_name(wt)
        import shutil
        shutil.rmtree(str(wt))
        # git worktree 注册已失效（目录删除后 prune 或按目录存在性判定）
        assert wm.is_available(wt, branch) == WT_REBUILDABLE

    def test_rebuildable_no_worktree_registered(self, tmp_path):
        """三态 rebuildable：分支在但从未建过 worktree。"""
        root = tmp_path / "repo"
        init_repo(root)
        git(root, "branch", "fenix/demo-123")
        wm = make_wm(root)
        assert wm.is_available(branch="fenix/demo-123") == WT_REBUILDABLE

    def test_unavailable_branch_gone(self, tmp_path):
        """三态 unavailable：分支不可解析。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        assert wm.is_available(branch="fenix/gone-999") == WT_UNAVAILABLE

    def test_unavailable_no_input(self, tmp_path):
        """无分支且无法从路径解析 → unavailable。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        assert wm.is_available() == WT_UNAVAILABLE

    def test_three_paths_consistent_judgment(self, tmp_path):
        """三链路判定一致：目录被外部删除、分支仍在 → 全部走到「可从分支重建」。

        recovery（resolve_resume_site）、resume 派发（同源 resolve）、复用认领
        （_take_reusable_worktree）共用 is_available，不存在任一链路按旧目录
        路径盲派发。
        """
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        branch = wm.get_branch_name(wt)
        # 登记为复用遗产（fast-track 打回现场）
        wm.keep_for_reuse("demo", wt)
        import shutil
        shutil.rmtree(str(wt))

        # 三链路经单源查询全部得到 rebuildable，且各自不按旧目录盲派发：
        # 1) recovery/resume：resolve_resume_site 在既有分支上重建载体
        resolved, rbranch = wm.resolve_resume_site("demo", branch)
        assert resolved is not None and resolved.exists()
        assert rbranch == branch
        assert wm.find_worktree_path(branch) == resolved
        # 2) 复用认领：旧目录已删 → 判无效回退，不返回已删路径
        taken = wm._take_reusable_worktree("demo")
        assert taken is None


# ── 2. recovery 保留判定（有提交分支续做 / 零提交清空 / worktree 重建） ──────


class TestRecoveryPreserve:
    def test_preserve_branch_with_commits(self, tmp_path):
        """有提交分支：保留 branch/implementer_run + _recovery_resume 标记。"""
        root = tmp_path / "repo"
        init_repo(root)
        git(root, "checkout", "-q", "-b", "fenix/demo-123")
        add_commit(root, "feat.py", "IMPL\n", "[fenix] demo: impl")
        git(root, "checkout", "-q", "main")
        sm = make_state_machine(root, {
            "demo": {"status": "implementing", "branch": "fenix/demo-123",
                     "implementer_run": "impl-demo-111"},
        })
        recovered = sm.recover_interrupted(project_root=root, worktree_manager=make_wm(root))
        assert "demo" in recovered
        entry = sm.read_one("demo")
        assert entry["status"] == "ready"
        assert entry["branch"] == "fenix/demo-123", "保留分支引用"
        assert entry["implementer_run"] == "impl-demo-111", "保留 implementer_run"
        assert entry["_recovery_resume"] is True, "标记恢复续做"
        assert entry["tester_run"] is None

    def test_zero_commit_clears(self, tmp_path):
        """零提交分支：走现行清空路径（branch/implementer_run 清空，无续做标记）。"""
        root = tmp_path / "repo"
        init_repo(root)
        # 分支存在但相对 main 零提交（= main 同一提交）
        git(root, "branch", "fenix/demo-123")
        sm = make_state_machine(root, {
            "demo": {"status": "implementing", "branch": "fenix/demo-123",
                     "implementer_run": "impl-demo-111"},
        })
        recovered = sm.recover_interrupted(project_root=root, worktree_manager=make_wm(root))
        assert "demo" in recovered
        entry = sm.read_one("demo")
        assert entry["status"] == "ready"
        assert entry["branch"] is None
        assert entry["implementer_run"] is None
        assert entry.get("_recovery_resume") is None

    def test_missing_branch_clears(self, tmp_path):
        """分支不存在：走现行清空路径（逐字节兼容）。"""
        root = tmp_path / "repo"
        init_repo(root)
        sm = make_state_machine(root, {
            "demo": {"status": "implementing", "branch": "fenix/gone-999",
                     "implementer_run": "impl-demo-111"},
        })
        recovered = sm.recover_interrupted(project_root=root, worktree_manager=make_wm(root))
        assert "demo" in recovered
        entry = sm.read_one("demo")
        assert entry["status"] == "ready"
        assert entry["branch"] is None
        assert entry.get("_recovery_resume") is None

    def test_worktree_rebuilt_when_missing(self, tmp_path):
        """worktree 缺失时从既有分支重建（复用 repair lane checkout 能力）。"""
        root = tmp_path / "repo"
        init_repo(root)
        git(root, "checkout", "-q", "-b", "fenix/demo-123")
        add_commit(root, "feat.py", "IMPL\n", "[fenix] demo: impl")
        git(root, "checkout", "-q", "main")
        wm = make_wm(root)
        sm = make_state_machine(root, {
            "demo": {"status": "implementing", "branch": "fenix/demo-123",
                     "implementer_run": "impl-demo-111"},
        })
        sm.recover_interrupted(project_root=root, worktree_manager=wm)
        wt = wm.find_worktree_path("fenix/demo-123")
        assert wt is not None, "缺失时须在既有分支上重建 worktree"
        assert wt.exists()
        branch = git(wt, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        assert branch == "fenix/demo-123", "重建载体检出保留分支，而非新建分支"
        entry = sm.read_one("demo")
        assert entry["branch"] == "fenix/demo-123"
        assert entry.get("_recovery_resume") is True

    def test_no_project_root_is_compatible(self, tmp_path):
        """旧签名（无 project_root/worktree_manager）行为逐字节兼容：清空路径。"""
        root = tmp_path / "repo"
        init_repo(root)
        git(root, "checkout", "-q", "-b", "fenix/demo-123")
        add_commit(root, "feat.py", "IMPL\n", "[fenix] demo: impl")
        git(root, "checkout", "-q", "main")
        sm = make_state_machine(root, {
            "demo": {"status": "implementing", "branch": "fenix/demo-123",
                     "implementer_run": "impl-demo-111"},
        })
        recovered = sm.recover_interrupted()  # 无参调用 = 旧语义
        assert "demo" in recovered
        entry = sm.read_one("demo")
        assert entry["branch"] is None
        assert entry.get("_recovery_resume") is None

    def test_testing_interrupted_unchanged(self, tmp_path):
        """testing 中断恢复语义不变（→ implemented 重验，branch 保留）。"""
        root = tmp_path / "repo"
        init_repo(root)
        git(root, "checkout", "-q", "-b", "fenix/demo-123")
        add_commit(root, "feat.py", "IMPL\n", "[fenix] demo: impl")
        git(root, "checkout", "-q", "main")
        sm = make_state_machine(root, {
            "demo": {"status": "testing", "branch": "fenix/demo-123",
                     "tester_run": "verify-demo-111"},
        })
        recovered = sm.recover_interrupted(project_root=root, worktree_manager=make_wm(root))
        assert "demo" in recovered
        entry = sm.read_one("demo")
        assert entry["status"] == "implemented"
        assert entry["branch"] == "fenix/demo-123"
        assert entry["tester_run"] is None


# ── 2.4/4.4: 三层回落链向后兼容 + 标记缺失回落 ─────────────────────────────────


class TestThreeLayerFallbackBackwardCompat:
    """9.7: 三层回落链向后兼容（STATE branch 在册时不触发第三层）、
    标记缺失时回落保留续做；零提交分支仍走现行清空。"""

    def test_state_branch_present_no_third_layer(self, tmp_path):
        """STATE branch 在册 → 不触发第三层（命名空间枚举）。"""
        root = tmp_path / "repo"
        init_repo(root)
        git(root, "checkout", "-q", "-b", "fenix/demo-123")
        add_commit(root, "feat.py", "IMPL\n", "[fenix] impl")
        git(root, "checkout", "-q", "main")
        sm = make_state_machine(root, {
            "demo": {"status": "implementing", "branch": "fenix/demo-123",
                     "implementer_run": "impl-demo-111"},
        })
        recovered = sm.recover_interrupted(project_root=root,
                                           worktree_manager=make_wm(root))
        assert "demo" in recovered
        entry = sm.read_one("demo")
        assert entry["status"] == "ready"
        assert entry["branch"] == "fenix/demo-123"
        assert entry.get("_recovery_resume") is True

    def test_mark_missing_falls_to_preserve(self, tmp_path):
        """_repair_awaiting_remerge 缺失时回落保留续做路径（逐字节兼容）。"""
        root = tmp_path / "repo"
        init_repo(root)
        git(root, "checkout", "-q", "-b", "fenix/demo-123")
        add_commit(root, "feat.py", "IMPL\n", "[fenix] impl")
        git(root, "checkout", "-q", "main")
        sm = make_state_machine(root, {
            "demo": {"status": "implementing", "branch": "fenix/demo-123",
                     "implementer_run": "impl-demo-111"},
        })
        recovered = sm.recover_interrupted(project_root=root,
                                           worktree_manager=make_wm(root))
        entry = sm.read_one("demo")
        assert entry["status"] == "ready"
        assert entry["branch"] == "fenix/demo-123"
        assert entry.get("_recovery_resume") is True

    def test_zero_commit_still_clears(self, tmp_path):
        """零提交分支（main..branch 为空）仍走现行清空路径（逐字节兼容）。"""
        root = tmp_path / "repo"
        init_repo(root)
        git(root, "branch", "fenix/demo-123")  # 零提交
        sm = make_state_machine(root, {
            "demo": {"status": "implementing", "branch": "fenix/demo-123",
                     "implementer_run": "impl-demo-111"},
        })
        recovered = sm.recover_interrupted(project_root=root,
                                           worktree_manager=make_wm(root))
        entry = sm.read_one("demo")
        assert entry["status"] == "ready"
        assert entry["branch"] is None
        assert entry.get("_recovery_resume") is None

    def test_layer3_remark_zero_commit_still_clears(self, tmp_path):
        """第三层（命名空间枚举）命中零提交候选 → 不判为可保留，走清空。"""
        root = tmp_path / "repo"
        init_repo(root)
        git(root, "branch", "fenix/demo-999")  # 零提交
        sm = make_state_machine(root, {
            "demo": {"status": "implementing", "branch": None,
                     "implementer_run": None},
        })
        recovered = sm.recover_interrupted(project_root=root,
                                           worktree_manager=make_wm(root))
        entry = sm.read_one("demo")
        # 零提交候选被剔除 → 无可用载体 → 清空
        assert entry["status"] == "ready"
        assert entry["branch"] is None


# ── 3. 清理协调：保全 worktree 不被误删 ─────────────────────────────────────


class TestCleanupCoordination:
    def test_cleanup_orphans_protected_skipped(self, tmp_path):
        """cleanup_orphans 保护集参数：保全在册 worktree 不被 shutdown 清理。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        # 保全在册：cleanup 跳过该 worktree
        wm.cleanup_orphans(protected={str(wt)})
        assert wt.exists(), "保护集中的 worktree 必须保留"
        # 未保护的照常清理
        wt2 = wm.create("other", "implementer")
        wm.cleanup_orphans()
        assert not wt2.exists(), "未保护 worktree 正常清理"
        assert wt.exists()

    def test_boot_recovery_protects_before_stale_cleanup(self, tmp_path):
        """boot 顺序：recovery 保留判定先于 stale cleanup，保全 worktree 不被误删。"""
        root = tmp_path / "repo"
        init_repo(root)
        git(root, "checkout", "-q", "-b", "fenix/demo-123")
        add_commit(root, "feat.py", "IMPL\n", "[fenix] demo: impl")
        git(root, "checkout", "-q", "main")
        wm = make_wm(root)
        # 模拟上次停机保全的现场：分支上有提交，worktree 已建
        wt = wm.create_worktree_on_branch("demo", "fenix/demo-123")
        sm = make_state_machine(root, {
            "demo": {"status": "implementing", "branch": "fenix/demo-123",
                     "implementer_run": "impl-demo-111"},
        })
        # 按 daemon.start() 顺序：先 recovery（登记保留载体入活动集），再 stale 清理
        sm.recover_interrupted(project_root=root, worktree_manager=wm)
        wm.cleanup_stale_worktrees()
        assert wt.exists(), "保全 worktree 在 stale 清理中不得被误删"
        entry = sm.read_one("demo")
        assert entry.get("_recovery_resume") is True

    def test_protected_dirs_survive_both_cleanups(self, tmp_path):
        """保全 worktree 同时经过 shutdown 与 boot 两条清理路径都存活。"""
        root = tmp_path / "repo"
        init_repo(root)
        git(root, "checkout", "-q", "-b", "fenix/demo-123")
        add_commit(root, "feat.py", "IMPL\n", "[fenix] demo: impl")
        git(root, "checkout", "-q", "main")
        wm = make_wm(root)
        wt = wm.create_worktree_on_branch("demo", "fenix/demo-123")
        # shutdown 路径（保护集）
        wm.cleanup_orphans(protected={str(wt)})
        assert wt.exists()
        # boot 路径（recovery 登记在活动集 → stale 清理跳过）
        wm._active_worktrees.add(str(wt))
        wm._wt_branches[str(wt)] = "fenix/demo-123"
        wm.cleanup_stale_worktrees()
        assert wt.exists()


# ── 4. 排水与终止前保全（daemon shutdown 路径） ────────────────────────────


class TestShutdownDrain:
    def test_drain_waits_for_natural_completion(self):
        """排水等待在跑 run 自然终态：全部完成后 drain_wait 返回空。"""
        runner = FakeRunner(running={"impl-demo-111-a1": FakeProc()})

        # 前若干次 poll 返回 None（仍在跑），之后 0（自然终态）——用计数替代
        # sleep 模拟「稍后完成」，避免真实墙钟等待。
        state = {"n": 0}

        def _poll():
            state["n"] += 1
            return None if state["n"] < 3 else 0

        runner._running_agents["impl-demo-111-a1"].poll = _poll
        remaining = runner.drain_wait(timeout=5)
        assert remaining == []
        assert state["n"] >= 3

    def test_drain_timeout_returns_remaining(self):
        """排水窗口到期仍残留：drain_wait 返回残留 run_id，不无限等待。"""
        runner = FakeRunner(running={"impl-demo-111-a1": FakeProc()})
        remaining = runner.drain_wait(timeout=0.05)
        assert remaining == ["impl-demo-111-a1"]

    def test_planned_restart_drains(self, monkeypatch, tmp_path):
        """restart_request 在册 → daemon 进入排水模式：调用 drain_wait、不立即 terminate。"""
        daemon, runner, wm = make_daemon(
            monkeypatch, tmp_path, restart_request=True, drain_seconds=1800,
            running={}, sm_entries={},
        )
        with pytest.raises(SystemExit):
            daemon.shutdown()
        assert runner.drain_calls == [1800], "排水窗口传入 drain_wait"
        assert runner.terminate_calls == 1, "终态收口仍会走 terminate（无残留则零终止）"

    def test_non_planned_restart_fast_path(self, monkeypatch, tmp_path):
        """非计划 SIGTERM（restart_request 不在册）→ 不排水（drain_wait 零调用）。"""
        daemon, runner, wm = make_daemon(
            monkeypatch, tmp_path, restart_request=False, drain_seconds=1800,
            running={"impl-demo-111-a1": FakeProc()}, sm_entries={},
        )
        with pytest.raises(SystemExit):
            daemon.shutdown()
        assert runner.drain_calls == [], "非计划停机不得进入排水"
        assert runner.terminate_calls == 1

    def test_drain_zero_fast_path(self, monkeypatch, tmp_path):
        """drain=0 快速停机语义收窄（planned-restart-drain 3.2）：仅非规划性
        关停走 fast path；规划性重启豁免 shutdown=0 夹紧，排水窗口取
        agents.run_drain_max_seconds 原值受 supervisor SIGKILL 等待上界约束
        （shutdown=0 → SIGKILL 等待回退 60s，减收口余量 10s → 上界 50s）。"""
        # 非规划性关停（无 restart_request）+ shutdown=0 → fast path 保留
        daemon, runner, wm = make_daemon(
            monkeypatch, tmp_path, restart_request=False, drain_seconds=0,
            running={"impl-demo-111-a1": FakeProc()}, sm_entries={},
        )
        with pytest.raises(SystemExit):
            daemon.shutdown()
        assert runner.drain_calls == [], "非规划性 drain=0 保持现行快速停机"
        assert runner.terminate_calls == 1

        # 规划性重启 + shutdown=0 + run_drain=60 → 豁免夹紧，窗口 = min(60, 50)
        daemon, runner, wm = make_daemon(
            monkeypatch, tmp_path, restart_request=True, drain_seconds=0,
            run_drain_seconds=60,
            running={"impl-demo-111-a1": FakeProc()}, sm_entries={},
        )
        with pytest.raises(SystemExit):
            daemon.shutdown()
        assert runner.drain_calls == [50.0], (
            "规划性重启不受 shutdown=0 夹紧（窗口=run_drain 原值受 supervisor 上界）"
        )
        assert runner.terminate_calls == 1

    def test_preserve_sidecar_before_terminate(self, monkeypatch, tmp_path):
        """排水超时终止前：sidecar 已包含该 spec 的 branch/worktree 引用。"""
        fake_wt = tmp_path / "proj" / ".claude" / "worktrees" / "impl-demo-111"
        fake_wt.parent.mkdir(parents=True, exist_ok=True)
        daemon, runner, wm = make_daemon(
            monkeypatch, tmp_path, restart_request=True, drain_seconds=0.05,
            running={"impl-demo-111-a1": FakeProc()},
            sm_entries={"demo": {"branch": "fenix/demo-123"}},
            wt_by_branch={"fenix/demo-123": fake_wt},
        )
        with pytest.raises(SystemExit):
            daemon.shutdown()
        # terminate 已经发生；sidecar 必须已落盘且包含引用（先于 terminate）
        sidecar = tmp_path / "proj" / ".fenix" / "interrupted_runs.json"
        assert sidecar.exists(), "sidecar 必须在 terminate 前落盘"
        entries = json.loads(sidecar.read_text(encoding="utf-8"))
        assert entries, "sidecar 不得为空"
        demo = [e for e in entries if e["spec"] == "demo"]
        assert demo, f"sidecar 应包含 spec demo：{entries}"
        assert demo[0]["branch"] == "fenix/demo-123"
        assert demo[0]["worktree"] == str(fake_wt)
        assert demo[0]["reason"] == "drain timeout"
        assert "timestamp" in demo[0]

    def test_preserve_sidecar_does_not_block_shutdown(self, monkeypatch, tmp_path):
        """sidecar 写入失败降级 WARNING 不阻塞停机（只读目录模拟写失败）。"""
        ro_dir = tmp_path / "ro"
        ro_dir.mkdir()
        import os
        os.chmod(str(ro_dir), 0o555)
        daemon, runner, wm = make_daemon(
            monkeypatch, tmp_path, restart_request=True, drain_seconds=0.05,
            running={"impl-demo-111-a1": FakeProc()},
            sm_entries={"demo": {"branch": "fenix/demo-123"}},
            wt_by_branch={},
        )
        # 把 PRESERVE_SIDECAR 指向只读目录下的文件
        monkeypatch.setattr(fenixd, "PRESERVE_SIDECAR", ro_dir / "interrupted_runs.json")
        with pytest.raises(SystemExit):
            daemon.shutdown()  # 不得因写失败抛异常阻塞停机
        os.chmod(str(ro_dir), 0o755)

    def test_cleanup_orphans_receives_protected_set(self, monkeypatch, tmp_path):
        """shutdown 清理协调：保全 worktree 传入 cleanup_orphans 保护集。"""
        fake_wt = tmp_path / "proj" / ".claude" / "worktrees" / "impl-demo-111"
        fake_wt.parent.mkdir(parents=True, exist_ok=True)
        daemon, runner, wm = make_daemon(
            monkeypatch, tmp_path, restart_request=True, drain_seconds=0.05,
            running={"impl-demo-111-a1": FakeProc()},
            sm_entries={"demo": {"branch": "fenix/demo-123"}},
            wt_by_branch={"fenix/demo-123": fake_wt},
        )
        with pytest.raises(SystemExit):
            daemon.shutdown()
        assert wm.cleanup_protected is not None
        assert str(fake_wt) in wm.cleanup_protected, "保全 worktree 进入保护集"


# ── 5. supervisor SIGKILL 等待可配（D2） ────────────────────────────────────


class TestSupervisorWait:
    def _load_supervisor(self):
        import importlib.util
        sup_path = Path(__file__).resolve().parent.parent / "bin" / "fenixd_supervisor.py"
        spec = importlib.util.spec_from_file_location("fenixd_supervisor", sup_path)
        sup = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sup)
        return sup

    @pytest.mark.parametrize(
        "config_text, expected",
        [
            (None, 60),                                        # 未配置/解析失败 → 回退 60
            ("admin:\n  shutdown_drain_seconds: 1800\n", 1800 + 120),  # drain + margin
            ("admin:\n  shutdown_drain_seconds: 0\n", 60),     # drain=0 快速停机回退 60
        ],
        ids=["default-60", "drain-plus-margin", "drain-zero-fallback"],
    )
    def test_sigkill_wait(self, config_text, expected, tmp_path, monkeypatch):
        """SIGKILL 等待 = drain + 120s margin；未配置 / drain=0 回退 60s。"""
        sup = self._load_supervisor()
        fake_fenix = tmp_path / ".fenix"
        fake_fenix.mkdir(parents=True, exist_ok=True)
        if config_text is not None:
            (fake_fenix / "config.yaml").write_text(config_text, encoding="utf-8")
        sup.FENIX_DIR = fake_fenix
        sup.PROJECT_ROOT = tmp_path
        assert sup._sigkill_wait_seconds() == expected


# ── 6. resume 派发复用继承语义（prompt 继承注记，2.3） ───────────────────────


class TestRecoveryResumePrompt:
    def _mk_spec_dir(self, proot: Path, name: str) -> None:
        d = proot / "spec" / "changes" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "tasks.md").write_text("# Tasks\n\n- [ ] 1.1 do it\n", encoding="utf-8")

    def test_resume_note_injected_when_marked_reused(self, tmp_path):
        """恢复续做注入继承注记（仅 resume 派发登记复用痕迹时注入）。"""
        from test_agent_runner import make_runner
        from unittest.mock import MagicMock

        proot = tmp_path / "proj"
        self._mk_spec_dir(proot, "demo")
        runner = make_runner(proot)
        wm = MagicMock()
        wm.get_reuse_record.return_value = {
            "path": str(proot / ".claude" / "worktrees" / "repair-demo-1"),
            "branch": "fenix/demo-123",
            # code-review item 82d4de9525cd 起 implementer 分支以
            # require_recovery=True 判据注入：复用记录须携带恢复来源标记
            "recovery": True,
        }
        runner.worktree_manager = wm
        prompt = runner._prompt_builder._build_prompt("demo", "implementer")
        assert "中断恢复续做" in prompt
        assert "不要重做已完成的工作" in prompt
        assert "fenix/demo-123" in prompt

    def test_no_resume_note_without_record(self, tmp_path):
        """无复用痕迹 → 不注入恢复续做注记（prompt 与现状逐字节一致）。"""
        from test_agent_runner import make_runner

        proot = tmp_path / "proj"
        self._mk_spec_dir(proot, "demo")
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_prompt("demo", "implementer")
        assert "中断恢复续做" not in prompt
        assert "Worktree 继承" not in prompt


# ── 7. spec → worktree 事实查询（fix-preserve-chain-first-round-gap 1.1-1.3） ──


class TestFindWorktreeBySpec:
    """spec → worktree/branch 事实查询：命名约定精确匹配、三态校验、歧义不可用。"""

    def test_basic_impl_match(self, tmp_path):
        """impl-<spec>-<ts> 目录命中，返回 (wt_path, branch)。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        branch = wm.get_branch_name(wt)
        resolved = wm.find_worktree_by_spec("demo")
        assert resolved is not None
        rpath, rbranch = resolved
        assert str(rpath) == str(wt)
        assert rbranch == branch

    def test_basic_verify_match(self, tmp_path):
        """verify-<spec>-<ts> 目录同样命中（verifier 分支）。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "verifier")
        branch = wm.get_branch_name(wt)
        resolved = wm.find_worktree_by_spec("demo")
        assert resolved is not None
        assert resolved[1] == branch
        assert str(resolved[0]) == str(wt)

    def test_no_substring_match(self, tmp_path):
        """spec 名互为前缀不误匹配（分隔符边界锚定，禁止子串包含）。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wm.create("fix-x", "implementer")
        wm.create("fix-x-y", "implementer")
        res_x = wm.find_worktree_by_spec("fix-x")
        assert res_x is not None
        assert "fix-x-y" not in str(res_x[0]), "fix-x 不得命中 fix-x-y 的目录"
        res_xy = wm.find_worktree_by_spec("fix-x-y")
        assert res_xy is not None
        assert "fix-x-y" in str(res_xy[0])

    def test_ambiguity_returns_none(self, tmp_path):
        """歧义：同一 spec 两个在册 worktree → None（不静默取首个）。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wm.create("demo", "implementer")
        # 手工再建第二个同 spec worktree（异常并行场景）
        ts2 = int(time.time()) - 500
        branch2 = f"fenix/demo-{ts2}"
        git(root, "branch", branch2)
        wt2 = wm.base_dir / f"impl-demo-{ts2}"
        git(root, "worktree", "add", str(wt2), branch2)
        assert wm.find_worktree_by_spec("demo") is None, "歧义不得静默取首个"

    def test_unavailable_branch_filtered(self, tmp_path):
        """非 available/rebuildable 候选不作依据：分支已删 → None。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        branch = wm.get_branch_name(wt)
        # 强制删除分支 ref（update-ref -d 绕过「分支检出中」护栏：worktree
        # 目录与注册仍在，但分支不可解析）
        git(root, "update-ref", "-d", f"refs/heads/{branch}")
        assert wm.find_worktree_by_spec("demo") is None, \
            "分支不可解析的候选不得作为保全/保留依据"

    def test_no_match_and_empty_input(self, tmp_path):
        """无在册 worktree / 空 spec → None。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        assert wm.find_worktree_by_spec("nonexistent") is None
        assert wm.find_worktree_by_spec("") is None
        assert wm.find_worktree_by_spec(None) is None

    def test_rebuildable_dir_removed_still_match(self, tmp_path):
        """目录被外部删除但分支在（rebuildable）→ 仍返回（recovery 重建依据）。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        branch = wm.get_branch_name(wt)
        import shutil
        shutil.rmtree(str(wt))
        resolved = wm.find_worktree_by_spec("demo")
        assert resolved is not None, "rebuildable（分支在）应命中"
        assert resolved[1] == branch


# ── 8. 首轮在飞 run 保全链回落（fix-preserve-chain-first-round-gap 2.x） ──────


class TestFirstRoundPreserve:
    def test_first_round_preserve_resolves_branch_and_worktree(self, monkeypatch, tmp_path):
        """首轮在飞 run（STATE branch=None、worktree 在册）被排水强杀：
        sidecar 条目 MUST 含事实查询解析出的 branch 与 worktree，不得为空串。"""
        fake_wt = tmp_path / "proj" / ".claude" / "worktrees" / "impl-demo-1750000000"
        fake_wt.parent.mkdir(parents=True, exist_ok=True)
        daemon, runner, wm = make_daemon(
            monkeypatch, tmp_path, restart_request=True, drain_seconds=0.05,
            running={"impl-demo-1750000000-a1": FakeProc()},
            sm_entries={"demo": {}},  # STATE branch 未写入（run 未到终态）
            spec_to_wt={"demo": (fake_wt, "fenix/demo-1750000000")},
        )
        with pytest.raises(SystemExit):
            daemon.shutdown()
        sidecar = tmp_path / "proj" / ".fenix" / "interrupted_runs.json"
        assert sidecar.exists()
        entries = json.loads(sidecar.read_text(encoding="utf-8"))
        demo = [e for e in entries if e["spec"] == "demo"]
        assert demo, f"sidecar 应包含 spec demo：{entries}"
        assert demo[0]["branch"] == "fenix/demo-1750000000", "分支不得为空串"
        assert demo[0]["worktree"] == str(fake_wt), "worktree 不得为空串"

    def test_first_round_protected_set_includes_resolved_worktree(self, monkeypatch, tmp_path):
        """首轮在飞 run 保全后：解析出的 worktree 进入保护集（不被 orphan 清理）。"""
        fake_wt = tmp_path / "proj" / ".claude" / "worktrees" / "impl-demo-1750000000"
        fake_wt.parent.mkdir(parents=True, exist_ok=True)
        daemon, runner, wm = make_daemon(
            monkeypatch, tmp_path, restart_request=True, drain_seconds=0.05,
            running={"impl-demo-1750000000-a1": FakeProc()},
            sm_entries={"demo": {}},
            spec_to_wt={"demo": (fake_wt, "fenix/demo-1750000000")},
        )
        with pytest.raises(SystemExit):
            daemon.shutdown()
        assert str(fake_wt) in wm.cleanup_protected, "回落解析的 worktree 必须进保护集"

    def test_protected_fallback_from_empty_sidecar_worktree(self, monkeypatch, tmp_path):
        """sidecar 条目 worktree 为空串但在册 worktree 存在：
        以事实查询回落补入保护集，MUST NOT 放行清理。"""
        fake_wt = tmp_path / "proj" / ".claude" / "worktrees" / "impl-demo-1750000000"
        fake_wt.parent.mkdir(parents=True, exist_ok=True)
        # 预置 sidecar：历史条目 worktree 为空串
        sidecar = tmp_path / "proj" / ".fenix" / "interrupted_runs.json"
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_text(json.dumps([
            {"spec": "demo", "run_id": "impl-demo-1", "branch": "",
             "worktree": "", "ahead_commits": 1, "reason": "drain timeout",
             "timestamp": "2026-09-12T00:00:00+00:00"},
        ]), encoding="utf-8")
        daemon, runner, wm = make_daemon(
            monkeypatch, tmp_path, restart_request=True, drain_seconds=0.05,
            running={}, sm_entries={},
            spec_to_wt={"demo": (fake_wt, "fenix/demo-1750000000")},
        )
        with pytest.raises(SystemExit):
            daemon.shutdown()
        assert str(fake_wt) in wm.cleanup_protected, \
            "sidecar 条目为空时必须经事实查询回落补入保护集"


class TestRecoveryStateBranchFallback:
    def test_state_branch_empty_but_worktree_has_commits(self, tmp_path):
        """STATE branch 为空但在册 worktree 分支有提交：
        判定保留续做，MUST NOT 走清空分支。"""
        root = tmp_path / "repo"
        init_repo(root)
        git(root, "checkout", "-q", "-b", "fenix/demo-123")
        add_commit(root, "feat.py", "IMPL\n", "[fenix] demo: impl")
        git(root, "checkout", "-q", "main")
        wm = make_wm(root)
        # 在册 worktree（分支有提交）
        wm.create_worktree_on_branch("demo", "fenix/demo-123")
        sm = make_state_machine(root, {
            "demo": {"status": "implementing", "implementer_run": "impl-demo-111"},
            # 注意：无 branch 字段（首轮在飞）
        })
        recovered = sm.recover_interrupted(project_root=root, worktree_manager=wm)
        assert "demo" in recovered
        entry = sm.read_one("demo")
        assert entry["branch"] == "fenix/demo-123", "经事实查询回落保留分支"
        assert entry["implementer_run"] == "impl-demo-111"
        assert entry.get("_recovery_resume") is True, "标记恢复续做而非清空重派"

    def test_state_branch_empty_but_zero_commit_clears(self, tmp_path):
        """STATE branch 为空且在册 worktree 分支零提交 → 仍走现行清空（无提交则无工作可丢）。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")  # 分支存在但相对 main 零提交
        sm = make_state_machine(root, {
            "demo": {"status": "implementing", "implementer_run": "impl-demo-111"},
        })
        recovered = sm.recover_interrupted(project_root=root, worktree_manager=wm)
        assert "demo" in recovered
        entry = sm.read_one("demo")
        assert entry["branch"] is None, "零提交仍走清空"
        assert entry.get("_recovery_resume") is None


# ── 9. 删除前置留档（fix-preserve-chain-first-round-gap 3.x） ─────────────────


class TestSnapshotBeforeDelete:
    def _mock_snapshot(self, wm, calls, dir_existed_at_call):
        def snap(wt_path, branch=None):
            calls.append(str(wt_path))
            dir_existed_at_call.append(Path(wt_path).exists())
            return ""
        wm._snapshot_dirty_worktree = snap

    def test_cleanup_orphans_snapshots_before_delete(self, tmp_path):
        """orphan 清理硬删前留档：快照调用发生在目录删除之前。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        (wt / "dirty.txt").write_text("WIP\n", encoding="utf-8")  # dirty 有快照价值
        calls, existed = [], []
        self._mock_snapshot(wm, calls, existed)
        wm.cleanup_orphans()
        assert calls, "删除前必须调用 _snapshot_dirty_worktree"
        assert existed == [True], "快照必须在目录尚存在（删除前）时调用"
        assert not wt.exists(), "清理后目录被删除"

    def test_cleanup_force_success_path_snapshots_before_delete(self, tmp_path):
        """`git worktree remove --force` 成功路径同样留档（不留档不再只挂在失败兜底）。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        # implementer 失败走遗产保留路径（不删除），--force 路径以 verifier 失败触发
        wt = wm.create("demo", "verifier")
        (wt / "dirty.txt").write_text("WIP\n", encoding="utf-8")
        calls, existed = [], []
        self._mock_snapshot(wm, calls, existed)
        wm.cleanup(wt, success=False)  # 带 --force，通常成功
        assert calls, "--force 成功路径也必须留档"
        assert existed == [True], "快照先于删除发生"
        assert not wt.exists(), "worktree 已删除（--force 成功）"

    def test_cleanup_no_double_snapshot(self, tmp_path):
        """同一次清理同 worktree 只产生一次快照（幂等/前置短路）。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "verifier")
        (wt / "dirty.txt").write_text("WIP\n", encoding="utf-8")
        calls, existed = [], []
        self._mock_snapshot(wm, calls, existed)
        wm.cleanup(wt, success=False)
        assert len(calls) == 1, "cleanup 内不得重复留档"


# ── 10. 端到端：首轮在飞 run 排水强杀 → 保全 → 重启恢复续做 ──────────────────


class TestFirstRoundEndToEnd:
    """真实 git 仓库 + 真实 WorktreeManager + daemon shutdown 排水路径 端到端。

    对应 spec 端到端验证（5.1/5.2）的核心断言：首轮在飞 run（STATE branch
    未写、worktree 在册且有提交）被排水强杀时，sidecar 含 branch/worktree、
    worktree 不被 orphan 清理删除；重启后 recovery 判定保留续做（resume），
    不从零重派新分支。
    """

    def _run_e2e(self, tmp_path, monkeypatch):
        root = tmp_path / "proj"
        init_repo(root)
        wm = make_wm(root)  # 真实 WorktreeManager + 真实 git
        wt = wm.create("demo", "implementer")
        branch = wm.get_branch_name(wt)
        # 在 worktree 内产生提交（分支相对 main 有提交 = 有工作可丢）
        (wt / "impl.py").write_text("CODE\n", encoding="utf-8")
        git(wt, "add", "-A")
        git(wt, "commit", "-q", "-m", "[fenix] demo: impl")

        # daemon 装配（复用 FakeRunner 替身，其余为真实组件）
        fake_root = root
        (fake_root / ".fenix").mkdir(parents=True, exist_ok=True)
        (fake_root / ".fenix" / "restart_request").write_text("1\n", encoding="utf-8")
        monkeypatch.setattr(fenixd, "PROJECT_ROOT", fake_root)
        monkeypatch.setattr(
            fenixd, "PRESERVE_SIDECAR",
            fake_root / ".fenix" / "interrupted_runs.json")
        monkeypatch.setattr(
            fenixd.sys, "exit",
            lambda code=0: (_ for _ in ()).throw(SystemExit(code)))

        daemon = fenixd.FenixDaemon()
        # 排水窗口单源 agents.run_drain_max_seconds（pipeline-throughput D3）：
        # 只配 admin 旧键时窗口回退缺省 60s，替身 drain_wait 真自旋 60s。
        # e2e 意图是「排水立即超时走保全路径」，窗口取亚秒值。
        daemon.config = {
            "admin": {"shutdown_drain_seconds": 1},
            "agents": {"run_drain_max_seconds": 0.05},
        }
        daemon.logger = FakeLogger()
        daemon.state_machine = FakeSM({"demo": {}})  # STATE branch 未写
        daemon.worktree_manager = wm
        daemon.agent_runner = FakeRunner(
            running={"impl-demo-1750000000-a1": FakeProc()})
        daemon.pm_engine = SimpleNamespace(shutting_down=False)
        daemon._admin_thread = None
        daemon._admin_executor = None
        daemon.event_bus = None

        with pytest.raises(SystemExit):
            daemon.shutdown()
        return root, wm, wt, branch

    def test_e2e_preserve_and_recovery_resume(self, tmp_path, monkeypatch):
        """排水强杀保全 + 重启 recovery 保留续做 端到端。"""
        root, wm, wt, branch = self._run_e2e(tmp_path, monkeypatch)

        # ── 强杀后：sidecar 含 branch/worktree，worktree 未被 orphan 清理 ──
        sidecar = root / ".fenix" / "interrupted_runs.json"
        entries = json.loads(sidecar.read_text(encoding="utf-8"))
        demo = [e for e in entries if e["spec"] == "demo"]
        assert demo, "sidecar 必须包含 demo 保全条目"
        assert demo[0]["branch"] == branch, "sidecar branch 不得为空串"
        assert demo[0]["worktree"] == str(wt), "sidecar worktree 不得为空串"
        assert wt.exists(), "保全 worktree 不得被 cleanup_orphans 删除"

        # ── 重启后：recovery 保留续做，不从零重派 ──
        sm = make_state_machine(root, {
            "demo": {"status": "implementing", "implementer_run": "impl-demo-1750000000"},
        })
        recovered = sm.recover_interrupted(project_root=root, worktree_manager=wm)
        assert "demo" in recovered
        entry = sm.read_one("demo")
        assert entry["branch"] == branch, "保留原分支（resume 续做）"
        assert entry.get("_recovery_resume") is True, "标记恢复续做"
        assert entry["implementer_run"] == "impl-demo-1750000000", "保留 implementer_run"
        # 载体在场：原地续做，worktree 仍在
        assert wt.exists()

    def test_e2e_zero_commit_still_clears(self, tmp_path, monkeypatch):
        """零提交分支（首轮未产生任何提交）：仍走现行清空重建（无工作可丢）。"""
        root = tmp_path / "proj"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")  # 分支在册但相对 main 零提交
        branch = wm.get_branch_name(wt)
        sm = make_state_machine(root, {
            "demo": {"status": "implementing", "implementer_run": "impl-demo-1750000000"},
        })
        recovered = sm.recover_interrupted(project_root=root, worktree_manager=wm)
        assert "demo" in recovered
        entry = sm.read_one("demo")
        assert entry["branch"] is None, "零提交分支仍走现行清空"
        assert entry.get("_recovery_resume") is None


# ── 11. fast-track 车道端到端续做（fix-fasttrack-recovery-resume） ─────────────


class TestFastTrackEndToEndResume:
    """fast-track 恢复续做端到端：recovery 保全 → 续做派发不新建 → prompt 注记。

    对应 capability `fasttrack-recovery-resume` 的端到端场景：interrupted
    implementing + 分支 ahead of main → recover 保留续做标记 → fast-track 派发
    消费标记、经 resolve_resume_site 命中既有 worktree（不新建）、prompt 注入
    恢复续做注记（且不重复注入 Worktree 继承段）。
    """

    def _setup_preserved(self, tmp_path):
        """构造「interrupted implementing + 分支 ahead of main」并走 recovery 保全。

        Returns: (root, wm, wt, branch, sm)
        """
        root = tmp_path / "proj"
        init_repo(root)
        wm = make_wm(root)  # 真实 WorktreeManager + 真实 git
        wt = wm.create("demo", "implementer")
        branch = wm.get_branch_name(wt)
        # 分支相对 main 有提交（有成果可续做）
        (wt / "impl.py").write_text("CODE\n", encoding="utf-8")
        git(wt, "add", "-A")
        git(wt, "commit", "-q", "-m", "[fenix] demo: impl")
        sm = make_state_machine(root, {
            "demo": {"status": "implementing", "implementer_run": "impl-demo-1750000000"},
        })
        recovered = sm.recover_interrupted(project_root=root, worktree_manager=wm)
        assert "demo" in recovered
        entry = sm.read_one("demo")
        assert entry["branch"] == branch, "保留原分支"
        assert entry.get("_recovery_resume") is True, "标记恢复续做"
        return root, wm, wt, branch, sm

    def test_e2e_fast_track_resume_no_new_worktree(self, tmp_path):
        """① 保全 + ② fast-track 派发：不新建 worktree，run_fast_track 收到载体。"""
        from unittest.mock import MagicMock

        from core.pm_engine import PMEngine

        root, wm, wt, branch, sm = self._setup_preserved(tmp_path)

        # ── 模拟 fast-track 派发（真实 dispatch 分支 + 真实 wm + 真实 SM） ──
        logger = FakeLogger()
        engine = PMEngine(sm, MagicMock(), {}, root, logger)
        engine.handle_event = MagicMock()
        engine._on_spec_verified = MagicMock()
        engine._increment_impl_run_budget_used = MagicMock()
        engine.agent_runner.worktree_manager = wm
        # spec 目录（tasks.md 1 条 → normal 档，不降级）
        spec_dir = root / "spec" / "changes" / "demo"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / ".spec.yaml").write_text(
            "schema: spec-driven\ncreated: 2026-09-18\nmode: fast-track\n",
            encoding="utf-8",
        )
        (spec_dir / "tasks.md").write_text("# Tasks\n\n- [ ] 1.1 do it\n", encoding="utf-8")
        from core.pm_engine.dispatch import Dispatcher

        dispatcher = Dispatcher(engine)
        dispatcher._enqueue = MagicMock()
        dispatcher._enqueue_front = MagicMock()
        engine.__dict__["_dispatcher_instance"] = dispatcher
        dispatcher._run_fast_track_worker = MagicMock()

        # 观测 worktree_manager.create：续做派发 MUST NOT 新建 worktree
        create_calls = {"count": 0}
        original_create = wm.create

        def _spy_create(*a, **k):
            create_calls["count"] += 1
            return original_create(*a, **k)

        wm.create = _spy_create

        engine._run_agent_worker("demo", "fast-track", 5)

        assert create_calls["count"] == 0, "续做派发 MUST NOT 新建 worktree"
        dispatcher._run_fast_track_worker.assert_called_once_with(
            "demo", pre_wt_path=wt
        )
        # 标记已消费、锚点保留
        entry = sm.read_one("demo")
        assert not entry.get("_recovery_resume"), "标记一次性消费（不再为真）"
        assert entry.get("branch") == branch, "续做命中不清锚点"

    def test_e2e_fast_track_resume_prompt_note(self, tmp_path):
        """③ fast-track 续做 prompt 含恢复续做注记，且不含 Worktree 继承重复段。"""
        from test_agent_runner import make_runner

        root, wm, wt, branch, _sm = self._setup_preserved(tmp_path)
        # 续做命中已经 mark_reused（recovery=True）登记——直接构造同源痕迹：
        # 真实 wm 上登记恢复来源复用记录，构建 fast-track prompt
        wm.mark_reused("demo", wt, branch, recovery=True)
        runner = make_runner(root)
        runner.worktree_manager = wm
        prompt = runner._prompt_builder._build_prompt("demo", "fast-track")
        assert "中断恢复续做" in prompt, "续做轮 prompt 必须含恢复续做注记"
        assert "不要重做已完成的工作" in prompt
        assert branch in prompt, "注记必须含当前分支名"
        # 不重复注入 _fast_track_reuse_note 的语义重叠段落
        assert "Worktree 继承（worktree-reuse）" not in prompt, \
            "恢复续做注记优先，MUST NOT 同时注入 Worktree 继承重复段"
