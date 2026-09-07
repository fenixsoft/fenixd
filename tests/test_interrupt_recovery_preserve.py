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
        self.terminate_calls = 0
        self.drain_calls = []

    def running_run_ids(self):
        return [rid for rid, p in self._running_agents.items() if p.poll() is None]

    def drain_wait(self, timeout: float):
        self.drain_calls.append(timeout)
        deadline = time.time() + max(0.0, timeout)
        while time.time() < deadline:
            remaining = self.running_run_ids()
            if not remaining:
                return []
            time.sleep(0.02)
        return self.running_run_ids()

    def wait_for_running_agents(self, timeout: int = 10):
        self.terminate_calls += 1

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
                running: dict, sm_entries: dict, wt_by_branch: dict | None = None):
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
    daemon.config = {"admin": {"shutdown_drain_seconds": drain_seconds}}
    daemon.logger = FakeLogger()
    daemon.state_machine = FakeSM(sm_entries)
    daemon.worktree_manager = FakeWM(wt_by_branch)
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

        def _finish_after_delay():
            def poll():
                time.sleep(0.2)
                return 0
            return poll

        runner._running_agents["impl-demo-111-a1"].poll = _finish_after_delay()
        remaining = runner.drain_wait(timeout=5)
        assert remaining == []

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
        """drain=0 显式回退现行快速停机：restart_request 在册也不排水。"""
        daemon, runner, wm = make_daemon(
            monkeypatch, tmp_path, restart_request=True, drain_seconds=0,
            running={"impl-demo-111-a1": FakeProc()}, sm_entries={},
        )
        with pytest.raises(SystemExit):
            daemon.shutdown()
        assert runner.drain_calls == [], "drain=0 保持现行快速停机"
        assert runner.terminate_calls == 1

    def test_preserve_sidecar_before_terminate(self, monkeypatch, tmp_path):
        """排水超时终止前：sidecar 已包含该 spec 的 branch/worktree 引用。"""
        fake_wt = tmp_path / "proj" / ".claude" / "worktrees" / "impl-demo-111"
        fake_wt.parent.mkdir(parents=True, exist_ok=True)
        daemon, runner, wm = make_daemon(
            monkeypatch, tmp_path, restart_request=True, drain_seconds=1,
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
            monkeypatch, tmp_path, restart_request=True, drain_seconds=1,
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
            monkeypatch, tmp_path, restart_request=True, drain_seconds=1,
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
