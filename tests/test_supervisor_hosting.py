"""
fix-supervisor-hosting-chain 回归测试。

覆盖（与 tasks.md 一一对应）：
- Task 1.4：supervisor 项目根解析（--project-root > env > cwd）三事故场景、
  无效目录拒绝启动、自报五字段完备与原子性
- Task 2.3：托管态三态判定（managed / unmanaged / stopped）、/proc 不可用容错
- Task 3.4：start/stop 托管语义（命令构造 / 幂等 / stop 清理 / 优雅收口 / 无孤儿）
- Task 4.5：drain=0 无 supervisor 告警（事故回归）、有 supervisor 静默、去重、
  restart-daemon hook 消费方校验、restart_failed 建议文案安全
- Task 5.4：/api/projects 与 /api/overview 三态暴露、install-hosting、restart 拦截
- Task 5.6：审批推送消费方校验（unmanaged 409 事故回归 / managed 放行 / stopped 文案）
"""
import http.client
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

from conftest import _TestServer, make_project

# 模块级 import（test_daemon_lifecycle_races.py 同款处方）：直接绑定守护
# 脚本模块 fenixd.py，供用例在测试执行期使用。
import fenixd as _fenixd_mod
import core.fenix_session as fenix_session
import bin.fenixd_supervisor as supervisor_mod


# ── 1.4 supervisor 项目根解析与启动守卫 ───────────────────────────────

def _reset_argv(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", argv)


class TestSupervisorRootResolution:
    def test_explicit_project_root_beats_cwd(self, tmp_path, monkeypatch):
        """显式 --project-root 优先于 cwd（D1 场景一）。"""
        win_cwd = tmp_path / "cwd-proj"
        win_cwd.mkdir()
        target = tmp_path / "target-proj"
        target.mkdir()
        _reset_argv(monkeypatch, ["fenixd_supervisor.py", "--project-root", str(target)])
        monkeypatch.setattr(Path, "cwd", lambda: win_cwd)
        root, source = supervisor_mod._resolve_project_root()
        assert root == target.resolve()
        assert "参数" in source

    def test_env_var_beats_cwd(self, tmp_path, monkeypatch):
        """FENIX_PROJECT_ROOT 环境变量优先于 cwd（无 --project-root 时）。"""
        win_cwd = tmp_path / "cwd-proj"
        win_cwd.mkdir()
        target = tmp_path / "env-proj"
        target.mkdir()
        _reset_argv(monkeypatch, ["fenixd_supervisor.py"])
        monkeypatch.delenv("FENIX_PROJECT_ROOT", raising=False)
        monkeypatch.setenv("FENIX_PROJECT_ROOT", str(target))
        monkeypatch.setattr(Path, "cwd", lambda: win_cwd)
        root, source = supervisor_mod._resolve_project_root()
        assert root == target.resolve()
        assert "环境变量" in source

    def test_cwd_fallback_under_symlinked_fenix_bin(self, tmp_path, monkeypatch):
        """软链子项目 cwd 兜底不被劫持（事故回归：场景二）。

        子项目 .fenix/bin 是指向别处的软链，解析只看 cwd，绝不跟随软链回主树。
        """
        # 模拟「主树 bin」目录（软链目标）
        main_tree_bin = tmp_path / "main-tree" / "bin"
        main_tree_bin.mkdir(parents=True)
        (main_tree_bin / "fenixd_supervisor.py").write_text("# fake", encoding="utf-8")
        # 子项目：.fenix/bin -> <主树>/bin（软链）
        subproj = tmp_path / "sub-proj"
        (subproj / ".fenix").mkdir(parents=True)
        os.symlink(main_tree_bin, subproj / ".fenix" / "bin")
        (subproj / ".fenix" / "STATE.md").write_text("# state\n", encoding="utf-8")
        _reset_argv(monkeypatch, ["fenixd_supervisor.py"])
        monkeypatch.delenv("FENIX_PROJECT_ROOT", raising=False)
        monkeypatch.setattr(Path, "cwd", lambda: subproj)
        root, _source = supervisor_mod._resolve_project_root()
        # 解析结果必须落在子项目根，而非软链跟随到的主树
        assert root == subproj.resolve()
        assert root != main_tree_bin.parent.resolve()

    def test_invalid_dir_guard_exits_nonzero_no_process(self, tmp_path):
        """无 .fenix/ 的目录拒绝启动（场景三）：非零退出、stderr 可读、无 runtime 文件。"""
        bad_dir = tmp_path / "no-fenix"
        bad_dir.mkdir()
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[1] / "bin" / "fenixd_supervisor.py")],
            cwd=str(bad_dir), capture_output=True, text=True, timeout=20,
        )
        assert proc.returncode != 0
        assert "FATAL" in proc.stderr
        assert "解析来源" in proc.stderr or "cwd" in proc.stderr
        assert not (bad_dir / ".fenix").exists()
        assert not (bad_dir / "supervisor_runtime.json").exists()

    def test_runtime_file_five_keys_atomic(self, tmp_path, monkeypatch):
        """自报五字段完备（sigkill_wait/started_at/pid/script_hash/project_root）与原子性。"""
        proot = tmp_path / "proj-five"
        (proot / ".fenix" / "logs").mkdir(parents=True)
        (proot / "bin").mkdir(parents=True)
        monkeypatch.setattr(supervisor_mod, "PROJECT_ROOT", proot)
        monkeypatch.setattr(supervisor_mod, "FENIX_DIR", proot / ".fenix")
        supervisor_mod._write_supervisor_runtime()
        data = json.loads((proot / ".fenix" / "supervisor_runtime.json").read_text(encoding="utf-8"))
        assert set(data) == {"sigkill_wait", "started_at", "pid", "script_hash", "project_root"}
        assert data["pid"] == os.getpid()
        assert Path(data["project_root"]).resolve() == proot
        assert data["script_hash"]
        # 原子性：无残留半截临时文件
        leftovers = list((proot / ".fenix").glob(".supervisor_runtime.*.tmp"))
        assert leftovers == []


# ── 2.3 托管态三态判定 ────────────────────────────────────────────────

class TestHostingState:
    def test_managed_state(self):
        """有 supervisor → hosting_state == managed。"""
        with mock.patch.object(fenix_session, "supervisor_running", return_value=True), \
             mock.patch.object(fenix_session, "is_running", return_value=True):
            assert fenix_session.hosting_state("/any/root") == "managed"

    def test_unmanaged_state_accident_regression(self):
        """有 daemon 进程但无 supervisor → unmanaged（事故回归）。"""
        with mock.patch.object(fenix_session, "supervisor_running", return_value=False), \
             mock.patch.object(fenix_session, "is_running", return_value=True):
            assert fenix_session.hosting_state("/any/root") == "unmanaged"

    def test_stopped_state(self):
        """两者皆无 → stopped。"""
        with mock.patch.object(fenix_session, "supervisor_running", return_value=False), \
             mock.patch.object(fenix_session, "is_running", return_value=False):
            assert fenix_session.hosting_state("/any/root") == "stopped"

    def test_supervisor_running_proc_unreadable_no_raise(self):
        """/proc 不可读 → supervisor_running 返回 False 且不抛异常。"""
        with mock.patch.object(fenix_session, "_procs_matching", side_effect=OSError("no /proc")):
            assert fenix_session.supervisor_running("/any/root") is False
        with mock.patch.object(fenix_session, "_procs_matching", return_value=[]):
            assert fenix_session.supervisor_running("/any/root") is False


class TestSessionNameNormalization:
    """session_name 归一化口径（code-review item 12e5e201a1c3）。"""

    def test_dot_in_dirname_folded_to_hyphen(self, tmp_path):
        """目录名含内部点号 → 派生名不含点号。

        tmux 对会话名静默把 `.` 替换为 `_`，且 has-session 解析带点号目标时
        把点号当窗格分隔符而查找失败——派生名与 tmux 实际会话名必须同口径，
        否则启动复核 / tmux 回退 / stop 兜底全部误判。
        """
        proot = tmp_path / "my.project"
        proot.mkdir()
        name = fenix_session.session_name(str(proot))
        assert "." not in name
        assert name.startswith("fenixd-my-project-")


# ── 3.4 唯一托管启停路径 ──────────────────────────────────────────────

def _fake_tmux_run(cmd, capture_output=False, text=False, timeout=None):
    return mock.Mock(returncode=0, stdout="", stderr="")


class TestStartStopHosted:
    def _make_proj(self, tmp_path, name="proj-a") -> Path:
        proot = tmp_path / name
        (proot / ".fenix" / "logs").mkdir(parents=True)
        (proot / "bin").mkdir(parents=True)
        (proot / ".fenix" / "STATE.md").write_text("# state\n", encoding="utf-8")
        return proot

    def test_start_daemon_uses_supervisor_command(self, tmp_path, monkeypatch):
        """start_daemon 在 tmux session 内拉起 supervisor 托管入口而非直启 fenixd.py。"""
        proot = self._make_proj(tmp_path)
        calls = []
        monkeypatch.setattr(fenix_session.subprocess, "run", lambda *a, **kw: calls.append(a[0]) or mock.Mock(returncode=0))
        monkeypatch.setattr(fenix_session, "is_running", lambda root=None: len(calls) > 0)
        result = fenix_session.start_daemon(str(proot))
        assert result["ok"] is True
        assert result["already"] is False
        assert len(calls) == 1
        cmd = calls[0]
        assert cmd[0] == "tmux"
        # 命令主体必须是 supervisor 托管入口，且显式携带 --project-root
        session_cmd = cmd[-1]
        assert "fenixd_supervisor.py" in session_cmd
        assert "--project-root" in session_cmd
        assert str(proot) in session_cmd
        # MUST NOT 再直启 .fenix/fenixd.py 作为 session 主命令
        assert "python3 .fenix/fenixd.py" not in session_cmd.split("&&")[-1]

    def test_start_daemon_idempotent_already(self, tmp_path, monkeypatch):
        """重复启动：is_running 为真 → already=True，不创建第二个 session。"""
        proot = self._make_proj(tmp_path)
        monkeypatch.setattr(fenix_session, "is_running", lambda root=None: True)
        calls = []
        monkeypatch.setattr(fenix_session.subprocess, "run", lambda *a, **kw: calls.append(a))
        result = fenix_session.start_daemon(str(proot))
        assert result["ok"] is True and result["already"] is True
        assert calls == []

    def test_start_daemon_invalid_project(self, tmp_path, monkeypatch):
        """缺少 .fenix/ → 返回可读错误且不产生进程。"""
        proot = tmp_path / "proj-invalid"
        proot.mkdir()
        calls = []
        monkeypatch.setattr(fenix_session.subprocess, "run", lambda *a, **kw: calls.append(a))
        result = fenix_session.start_daemon(str(proot))
        assert result["ok"] is False
        assert "缺少 .fenix" in (result["error"] or "")
        assert calls == []

    def test_start_daemon_clears_stale_stop_flag(self, tmp_path, monkeypatch):
        """陈旧 .fenix/stop 在「daemon 与 supervisor 均未在跑」时被启动清理。"""
        proot = self._make_proj(tmp_path)
        stop_flag = proot / ".fenix" / "stop"
        stop_flag.touch()
        monkeypatch.setattr(fenix_session, "is_running", lambda root=None: False)
        monkeypatch.setattr(fenix_session, "supervisor_running", lambda root=None: False)
        monkeypatch.setattr(fenix_session.subprocess, "run", _fake_tmux_run)
        # is_running 恒假 → 走满轮询等待；注入小步长避免真等 5s。
        monkeypatch.setattr(fenix_session, "START_DAEMON_PROBE_ATTEMPTS", 1)
        monkeypatch.setattr(fenix_session, "START_DAEMON_PROBE_INTERVAL_SECONDS", 0.01)
        result = fenix_session.start_daemon(str(proot))
        assert result["ok"] is True
        assert not stop_flag.exists()

    def test_start_daemon_keeps_stop_flag_when_supervisor_alive(self, tmp_path, monkeypatch):
        """正在进行的停止操作留下的 stop 标记（supervisor 仍在跑）不被误删。"""
        proot = self._make_proj(tmp_path)
        stop_flag = proot / ".fenix" / "stop"
        stop_flag.touch()
        monkeypatch.setattr(fenix_session, "is_running", lambda root=None: False)
        monkeypatch.setattr(fenix_session, "supervisor_running", lambda root=None: True)
        monkeypatch.setattr(fenix_session.subprocess, "run", _fake_tmux_run)
        monkeypatch.setattr(fenix_session, "START_DAEMON_PROBE_ATTEMPTS", 1)
        monkeypatch.setattr(fenix_session, "START_DAEMON_PROBE_INTERVAL_SECONDS", 0.01)
        fenix_session.start_daemon(str(proot))
        assert stop_flag.exists()

    def test_stop_daemon_idempotent_no_stop_file(self, tmp_path, monkeypatch):
        """daemon 未运行 → was_running=False、不写 .fenix/stop。"""
        proot = self._make_proj(tmp_path)
        monkeypatch.setattr(fenix_session, "is_running", lambda root=None: False)
        result = fenix_session.stop_daemon(str(proot))
        assert result["ok"] is True and result["was_running"] is False
        assert not (proot / ".fenix" / "stop").exists()

    def test_stop_daemon_graceful_order(self, tmp_path, monkeypatch):
        """优雅收口：写 stop → 仅 SIGTERM daemon（不 SIGTERM supervisor）→ 快照全退后清除 stop。"""
        proot = self._make_proj(tmp_path)
        stop_flag = proot / ".fenix" / "stop"
        daemon_pid, supervisor_pid = 41111, 42222
        # 调用序：入口快照（_fenix_pids_under）→ SIGTERM → 轮询 _alive_pids
        monkeypatch.setattr(fenix_session, "is_running", mock.Mock(return_value=True))
        monkeypatch.setattr(fenix_session, "_fenix_pids_under", lambda root: [str(daemon_pid), str(supervisor_pid)])
        # 41111 是 daemon（cmdline 含 .fenix/fenixd.py）；42222 是 supervisor
        monkeypatch.setattr(fenix_session, "_is_daemon_cmdline", lambda pid: pid == str(daemon_pid))
        # 模拟快照进程快速全退（首轮即空）→ 不触发 30s 真实等待
        monkeypatch.setattr(fenix_session, "_alive_pids", lambda pids: [])
        killed = []
        monkeypatch.setattr(fenix_session.os, "kill", lambda pid, sig: killed.append((int(pid), sig)))
        result = fenix_session.stop_daemon(str(proot))
        assert result["ok"] is True and result["was_running"] is True
        # 写 stop → SIGTERM 只发给 daemon，然后快照全退 → 清除 stop
        assert stop_flag.exists() is False  # 已在 finally 清除
        assert (int(daemon_pid), fenix_session.signal.SIGTERM) in killed
        assert not any(pid == supervisor_pid and sig == fenix_session.signal.SIGTERM for pid, sig in killed)

    def test_stop_daemon_waits_supervisor_exit_before_clearing_stop(self, tmp_path, monkeypatch):
        """stop 文件在快照（daemon 与其父 supervisor）全退前不得清除。

        竞态实证（BUG-01）：daemon 先退出、supervisor 尚在检查 stop flag 时提前
        清 stop，supervisor 会误判「非显式停止」重新拉起 daemon。stop_daemon 必须
        等快照（含 supervisor）全退才清 stop 文件。
        """
        proot = self._make_proj(tmp_path)
        stop_flag = proot / ".fenix" / "stop"
        daemon_pid, supervisor_pid = 44111, 44222
        monkeypatch.setattr(fenix_session, "is_running", mock.Mock(return_value=True))
        monkeypatch.setattr(fenix_session, "_fenix_pids_under", lambda root: [str(daemon_pid), str(supervisor_pid)])
        monkeypatch.setattr(fenix_session, "_is_daemon_cmdline", lambda pid: pid == str(daemon_pid))
        # 首轮：daemon 已死、supervisor 仍在（等它检查 stop flag 后退出）；次轮全退
        alive_seq = {"n": 0}

        def _alive(pids):
            alive_seq["n"] += 1
            if alive_seq["n"] == 1:
                return [str(supervisor_pid)]
            return []

        monkeypatch.setattr(fenix_session, "_alive_pids", _alive)
        killed = []
        monkeypatch.setattr(fenix_session.os, "kill", lambda pid, sig: killed.append((int(pid), sig)))
        result = fenix_session.stop_daemon(str(proot))
        assert result["ok"] is True
        # supervisor 仍存活期间 stop 文件必须保留（不被提前 unlink 诱发复活）
        assert not stop_flag.exists()  # 全退后才清除
        # SIGTERM 仅 daemon
        assert (int(daemon_pid), fenix_session.signal.SIGTERM) in killed
        assert not any(pid == supervisor_pid and sig == fenix_session.signal.SIGTERM for pid, sig in killed)

    def test_stop_daemon_timeout_kill_session_no_orphan(self, tmp_path, monkeypatch):
        """收口超时：kill-session + 仅对快照中仍存活的残留补 SIGKILL，无孤儿。"""
        proot = self._make_proj(tmp_path)
        stop_flag = proot / ".fenix" / "stop"
        daemon_pid, supervisor_pid = 43111, 43222
        monkeypatch.setattr(fenix_session, "is_running", mock.Mock(return_value=True))
        monkeypatch.setattr(fenix_session, "_fenix_pids_under",
                            lambda root: [str(daemon_pid), str(supervisor_pid)])
        monkeypatch.setattr(fenix_session, "_is_daemon_cmdline", lambda pid: pid == str(daemon_pid))
        # 替身语义：SIGKILL 命中即消亡。补杀后复核（SIGKILL 短轮询确认死亡）
        # 按替身状态判 ok；此前的恒存活替身会让复核把已补杀进程判成「仍存活」
        # → ok=False，替身失真而非产品缺陷。
        killed = []
        sigkilled = set()

        def _kill(pid, sig):
            killed.append((int(pid), sig))
            if sig == fenix_session.signal.SIGKILL:
                sigkilled.add(int(pid))

        monkeypatch.setattr(fenix_session.os, "kill", _kill)
        monkeypatch.setattr(fenix_session, "_alive_pids",
                            lambda pids: [p for p in pids if int(p) not in sigkilled])
        tmux_calls = []
        monkeypatch.setattr(fenix_session.subprocess, "run",
                            lambda *a, **kw: tmux_calls.append(a) or mock.Mock(returncode=0))
        # 时间推进：单调递增且步进 > 30s，让等待窗口（deadline=首调+30）即时常量耗尽，
        # 立即进入 kill-session + SIGKILL 兜底路径（不真实等待 30 秒）
        t0 = time.time()
        ticks = {"n": 0}

        def _time_side():
            ticks["n"] += 1
            return t0 + 31 + ticks["n"] * 40

        monkeypatch.setattr(fenix_session.time, "time", _time_side)
        result = fenix_session.stop_daemon(str(proot))
        assert result["ok"] is True
        # 超时路径：kill-session 被调、残留（快照中仍存活）补 SIGKILL
        assert any("kill-session" in c[0] for c in tmux_calls)
        assert (daemon_pid, fenix_session.signal.SIGKILL) in killed
        assert (supervisor_pid, fenix_session.signal.SIGKILL) in killed
        assert not stop_flag.exists()

    def test_stop_daemon_concurrent_does_not_kill_foreign_pids(self, tmp_path, monkeypatch):
        """并发防护（BUG-01 回归）：超时兜底只杀入口快照 pid，绝不重扫误杀他路进程。

        场景：一路 install 的 stop_daemon（快照 = 旧 D1/S1）；另一路已经 start_daemon
        拉起新的 D2/S2（不在快照中）。本路 stop 超时兜底 MUST NOT 对 D2/S2 发任何
        信号（旧实现重新 _fenix_pids_under 会误杀，致托管永远无法成立）。
        """
        proot = self._make_proj(tmp_path)
        stop_flag = proot / ".fenix" / "stop"
        old_daemon, old_supervisor = 45111, 45222       # 本路快照（旧进程）
        new_daemon, new_supervisor = 45333, 45444       # 他路新拉起（must not 被杀）
        monkeypatch.setattr(fenix_session, "is_running", mock.Mock(return_value=True))
        # 入口快照：只含旧进程；重扫（若发生）会返回 4 个——断言扫描只发生一次
        scan_calls = {"n": 0}

        def _scan(root):
            scan_calls["n"] += 1
            return [str(old_daemon), str(old_supervisor)]

        monkeypatch.setattr(fenix_session, "_fenix_pids_under", _scan)
        monkeypatch.setattr(fenix_session, "_is_daemon_cmdline", lambda pid: pid == str(old_daemon))
        # 快照进程在补杀前恒存活 → 走超时兜底路径；SIGKILL 命中即消亡
        # （补杀后复核按替身状态判 ok，恒存活替身会替成「仍存活」假失败）
        killed = []
        sigkilled = set()

        def _kill(pid, sig):
            killed.append((int(pid), sig))
            if sig == fenix_session.signal.SIGKILL:
                sigkilled.add(int(pid))

        monkeypatch.setattr(fenix_session.os, "kill", _kill)
        monkeypatch.setattr(fenix_session, "_alive_pids",
                            lambda pids: [p for p in pids if int(p) not in sigkilled])
        monkeypatch.setattr(fenix_session.subprocess, "run",
                            lambda *a, **kw: mock.Mock(returncode=0))
        t0 = time.time()
        ticks = {"n": 0}

        def _time_side():
            ticks["n"] += 1
            return t0 + 31 + ticks["n"] * 40

        monkeypatch.setattr(fenix_session.time, "time", _time_side)
        result = fenix_session.stop_daemon(str(proot))
        assert result["ok"] is True
        # 兜底 SIGKILL 只落在快照（旧进程）上，他路新进程零接触
        killed_pids = {pid for pid, _ in killed}
        assert old_daemon in killed_pids and old_supervisor in killed_pids
        assert new_daemon not in killed_pids and new_supervisor not in killed_pids
        # 入口只扫描一次（轮询不再重扫全项目）
        assert scan_calls["n"] == 1
        assert not stop_flag.exists()


# ── 4.5 检测、告警与建议 ──────────────────────────────────────────────

class TestDetectAndAlert:
    def _daemon(self, tmp_path):
        from core.admin_store import AdminStore
        d = _fenixd_mod.FenixDaemon()
        d.config = {}
        d.logger = mock.MagicMock()
        d.pm_engine = mock.MagicMock()
        d.admin_store = AdminStore(tmp_path, d.logger)
        return d

    def test_drain_zero_unmanaged_produces_alert(self, tmp_path, monkeypatch):
        """事故回归：drain=0 且无 supervisor → supervisor_missing major 告警。"""
        proot = tmp_path / "proj-drain0"
        (proot / ".fenix" / "logs").mkdir(parents=True)
        d = self._daemon(proot)
        monkeypatch.setattr(d, "_shutdown_drain_seconds", lambda: 0)
        monkeypatch.setattr(fenix_session, "supervisor_running", lambda root=None: False)
        d._check_supervisor_drain_consistency()
        alert = d.admin_store.unhandled_for(None, "supervisor_missing")
        assert alert is not None
        assert alert["severity"] == "major"
        assert "restart_request" in alert["description"]
        # WARNING 文案
        warn_texts = [str(c) for c in d.logger.warning.call_args_list]
        assert any("未受 supervisor 托管" in w for w in warn_texts)

    def test_dedup_no_second_unhandled_alert(self, tmp_path, monkeypatch):
        """重复启动：既有未处置 supervisor_missing → 不重复追加。"""
        proot = tmp_path / "proj-dedup"
        (proot / ".fenix" / "logs").mkdir(parents=True)
        d = self._daemon(proot)
        monkeypatch.setattr(d, "_shutdown_drain_seconds", lambda: 0)
        monkeypatch.setattr(fenix_session, "supervisor_running", lambda root=None: False)
        d._check_supervisor_drain_consistency()
        d._check_supervisor_drain_consistency()
        alerts = [a for a in d.admin_store.read_all()
                  if a.get("kind") == "escalation" and a.get("signal_type") == "supervisor_missing"
                  and not a.get("handled")]
        assert len(alerts) == 1

    def test_drain_positive_with_supervisor_silent(self, tmp_path, monkeypatch):
        """drain>0 且有 supervisor、runtime 一致 → 静默无告警。"""
        proot = tmp_path / "proj-drainpos"
        fenix_dir = proot / ".fenix"
        fenix_dir.mkdir(parents=True)
        (fenix_dir / "supervisor_runtime.json").write_text(json.dumps({
            "sigkill_wait": 1920, "started_at": "2026-09-12T00:00:00+00:00"}), encoding="utf-8")
        d = self._daemon(proot)
        monkeypatch.setattr(_fenixd_mod, "PROJECT_ROOT", proot)
        monkeypatch.setattr(d, "_shutdown_drain_seconds", lambda: 1800)
        monkeypatch.setattr(fenix_session, "supervisor_running", lambda root=None: True)
        d._check_supervisor_drain_consistency()
        assert d.admin_store.unhandled_for(None, "supervisor_missing") is None
        warn_texts = [str(c) for c in d.logger.warning.call_args_list]
        assert not any("supervisor" in w.lower() for w in warn_texts)

    def test_restart_daemon_hook_requires_supervisor(self, tmp_path, monkeypatch):
        """restart-daemon hook：无 supervisor → failure，detail 含「无 supervisor」。"""
        from core.hook_engine import HookEngine
        proot = tmp_path / "proj-hook"
        (proot / ".fenix").mkdir(parents=True)
        engine = HookEngine(proot, {}, logger=mock.MagicMock(), admin_store=None)
        with mock.patch.object(fenix_session, "supervisor_running", return_value=False):
            ok, detail = engine._action_restart_daemon()
        assert ok is False
        assert "无 supervisor" in detail
        assert "supervisor 将执行优雅重启" not in detail
        # MUST NOT 写入 restart_request
        assert not (proot / ".fenix" / "restart_request").exists()

    def test_restart_daemon_hook_with_supervisor_writes(self, tmp_path, monkeypatch):
        """restart-daemon hook：有 supervisor → 写入请求并返回成功。"""
        from core.hook_engine import HookEngine
        proot = tmp_path / "proj-hook-ok"
        (proot / ".fenix").mkdir(parents=True)
        engine = HookEngine(proot, {}, logger=mock.MagicMock(), admin_store=None)
        with mock.patch.object(fenix_session, "supervisor_running", return_value=True):
            ok, detail = engine._action_restart_daemon()
        assert ok is True
        assert (proot / ".fenix" / "restart_request").exists()

    def test_restart_failed_recommendation_unmanaged_safe(self, tmp_path, monkeypatch):
        """restart_failed 建议文案：unmanaged → 不含直接启动命令，含安装托管指引。"""
        from core.admin_store import AdminStore
        from core.admin_monitor import AdminMonitor
        proot = tmp_path / "proj-mon"
        (proot / ".fenix").mkdir(parents=True)
        store = AdminStore(proot, mock.MagicMock())
        monitor = AdminMonitor({}, mock.MagicMock(), proot, mock.MagicMock(), store=store)
        rr = proot / ".fenix" / "restart_request"
        rr.write_text("x", encoding="utf-8")
        old = time.time() - 11 * 60
        os.utime(rr, (old, old))
        with mock.patch.object(fenix_session, "hosting_state", return_value="unmanaged"):
            monitor._detect_restart_failure(time.time())
        alert = store.unhandled_for(None, "restart_failed")
        assert alert is not None
        action = alert["recommended_action"]
        assert ".fenix/bin/fenixd_supervisor.py" not in action
        assert "安装托管" in action

    def test_restart_failed_recommendation_managed(self, tmp_path, monkeypatch):
        """restart_failed 建议文案：managed → 指引检查 supervisor 与排水状态。"""
        from core.admin_store import AdminStore
        from core.admin_monitor import AdminMonitor
        proot = tmp_path / "proj-mon-managed"
        (proot / ".fenix").mkdir(parents=True)
        store = AdminStore(proot, mock.MagicMock())
        monitor = AdminMonitor({}, mock.MagicMock(), proot, mock.MagicMock(), store=store)
        rr = proot / ".fenix" / "restart_request"
        rr.write_text("x", encoding="utf-8")
        old = time.time() - 11 * 60
        os.utime(rr, (old, old))
        with mock.patch.object(fenix_session, "hosting_state", return_value="managed"):
            monitor._detect_restart_failure(time.time())
        alert = store.unhandled_for(None, "restart_failed")
        action = alert["recommended_action"]
        assert ".fenix/bin/fenixd_supervisor.py" not in action
        assert "排水" in action


# ── 5.4 / 5.6 Dashboard 暴露与管理操作 ───────────────────────────────

@pytest.fixture()
def three_projects_fx(tmp_path):
    """三个项目（managed / unmanaged / stopped）的 dashboard server。"""
    import core.dashboard.data as dashboard_data
    p_managed = make_project(tmp_path, name="p-managed")
    p_unmanaged = make_project(tmp_path, name="p-unmanaged")
    p_stopped = make_project(tmp_path, name="p-stopped")
    cfg = tmp_path / "dashboard.yaml"
    from core.dashboard.registry import Registry
    reg = Registry(config_path=cfg)
    reg.save({
        "port": 8787, "scan_dirs": [str(tmp_path / "scan-empty")],
        "projects": [
            {"name": "p-managed", "path": str(p_managed)},
            {"name": "p-unmanaged", "path": str(p_unmanaged)},
            {"name": "p-stopped", "path": str(p_stopped)},
        ],
    })
    srv = _TestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
    yield p_managed, p_unmanaged, p_stopped, srv
    srv.stop()


class TestDashboardHostingExposure:
    def test_api_projects_three_state_combination(self, three_projects_fx, monkeypatch):
        """/api/projects 返回 triple 的 daemon/hosting 组合。"""
        _pm, _pu, _ps, srv = three_projects_fx
        # daemon_health 判定 daemon 状态；hosting_state 判定托管态
        monkeypatch.setattr("core.dashboard.data.daemon_health",
                            lambda root: "running"
                            if "p-managed" in str(root) or "p-unmanaged" in str(root) else "stopped")
        monkeypatch.setattr("core.dashboard.data.hosting_state",
                            lambda root: "managed"
                            if "p-managed" in str(root)
                            else ("unmanaged" if "p-unmanaged" in str(root) else "stopped"))
        status, body = srv.get("/api/projects")
        assert status == 200
        by_name = {p["name"]: p for p in body["projects"]}
        assert by_name["p-managed"]["daemon"] == "running" and by_name["p-managed"]["hosting"] == "managed"
        assert by_name["p-unmanaged"]["daemon"] == "running" and by_name["p-unmanaged"]["hosting"] == "unmanaged"
        assert by_name["p-stopped"]["daemon"] == "stopped" and by_name["p-stopped"]["hosting"] == "stopped"

    def test_api_overview_three_state_combination(self, three_projects_fx, monkeypatch):
        """/api/overview 返回 triple 的 daemon/hosting 组合。"""
        _pm, _pu, _ps, srv = three_projects_fx
        monkeypatch.setattr("core.dashboard.data.daemon_health",
                            lambda root: "running"
                            if "p-managed" in str(root) or "p-unmanaged" in str(root) else "stopped")
        monkeypatch.setattr("core.dashboard.data.hosting_state",
                            lambda root: "managed"
                            if "p-managed" in str(root)
                            else ("unmanaged" if "p-unmanaged" in str(root) else "stopped"))
        status, body = srv.get("/api/overview")
        assert status == 200
        by_name = {p["name"]: p for p in body["projects"]}
        assert by_name["p-managed"]["hosting"] == "managed"
        assert by_name["p-unmanaged"]["hosting"] == "unmanaged"
        assert by_name["p-stopped"]["hosting"] == "stopped"

    def test_install_hosting_unmanaged_success(self, three_projects_fx, monkeypatch):
        """install-hosting：unmanaged → stop 裸 daemon + supervisor 启动 → 成功。"""
        _pm, pu, _ps, srv = three_projects_fx
        calls = []
        monkeypatch.setattr("core.fenix_session.hosting_state",
                            lambda root=None: "unmanaged")
        monkeypatch.setattr("core.dashboard.server.stop_daemon",
                            lambda root=None: calls.append(("stop", root)) or {"ok": True})
        monkeypatch.setattr("core.dashboard.server.start_daemon",
                            lambda root=None: calls.append(("start", root)) or {"ok": True})
        status, body = srv.post("/api/projects/p-unmanaged/install-hosting")
        assert status == 200
        assert body["ok"] is True
        assert ("stop", str(pu)) in calls and ("start", str(pu)) in calls

    def test_install_hosting_managed_idempotent(self, three_projects_fx, monkeypatch):
        """install-hosting：managed → 幂等返回已托管，不重启。"""
        _pm, _pu, _ps, srv = three_projects_fx
        monkeypatch.setattr("core.fenix_session.hosting_state",
                            lambda root=None: "managed")
        calls = []
        monkeypatch.setattr("core.dashboard.server.stop_daemon",
                            lambda root=None: calls.append(root) or {"ok": True})
        monkeypatch.setattr("core.dashboard.server.start_daemon",
                            lambda root=None: calls.append(root) or {"ok": True})
        status, body = srv.post("/api/projects/p-managed/install-hosting")
        assert status == 200
        assert body["ok"] is True
        assert calls == []  # stop/start 未被调用

    def test_install_hosting_unknown_project_400(self, three_projects_fx):
        """install-hosting：未监控项目 → 400。"""
        _pm, _pu, _ps, srv = three_projects_fx
        status, body = srv.post("/api/projects/ghost/install-hosting")
        assert status == 400

    def test_restart_unmanaged_rejected(self, three_projects_fx, monkeypatch):
        """restart：unmanaged → 可读错误且不写 restart_request。"""
        _pm, pu, _ps, srv = three_projects_fx
        monkeypatch.setattr("core.fenix_session.hosting_state",
                            lambda root=None: "unmanaged")
        status, body = srv.post("/api/projects/p-unmanaged/restart")
        assert status == 200
        assert body["ok"] is False
        assert "未受 supervisor 托管" in body["error"]
        assert not (pu / ".fenix" / "restart_request").exists()

    def test_approve_push_unmanaged_409_no_signal(self, three_projects_fx, monkeypatch):
        """事故回归：unmanaged 审批推送 → 409 且 approve_push_request.json 未创建。"""
        _pm, pu, _ps, srv = three_projects_fx
        monkeypatch.setattr("core.dashboard.data.admin_actions._hosting_state",
                            lambda root=None: "unmanaged")
        status, body = srv.post("/api/spec-approve-push?project=p-unmanaged&spec=otherspec")
        assert status == 409
        assert "未受 supervisor 托管" in body["error"]
        assert not (pu / ".fenix" / "approve_push_request.json").exists()

    def test_approve_push_managed_writes_signal(self, three_projects_fx, monkeypatch):
        """managed 审批推送 → 写入信号并返回成功。"""
        pm, _pu, _ps, srv = three_projects_fx
        monkeypatch.setattr("core.dashboard.data.admin_actions._hosting_state",
                            lambda root=None: "managed")
        status, body = srv.post("/api/spec-approve-push?project=p-managed&spec=otherspec")
        assert status == 200
        assert body["ok"] is True
        assert (pm / ".fenix" / "approve_push_request.json").exists()

    def test_approve_push_stopped_keeps_legacy_text(self, three_projects_fx, monkeypatch):
        """stopped 审批推送 → 409 且文案与既有 daemon_down 逐字一致。"""
        _pm, _pu, ps, srv = three_projects_fx
        monkeypatch.setattr("core.dashboard.data.admin_actions._hosting_state",
                            lambda root=None: "stopped")
        status, body = srv.post("/api/spec-approve-push?project=p-stopped&spec=otherspec")
        assert status == 409
        assert body["error"] == "daemon 未运行，请先启动 daemon"
        assert "未受 supervisor 托管" not in body["error"]
        assert not (ps / ".fenix" / "approve_push_request.json").exists()


# ── 进程身份判定（子串假阳性事故回归）────────────────────────────────
#
# 事故（2026-09-13）：判据原为「cwd == 项目根 且 argv 文本含 .fenix/fenixd.py
# 或 fenixd_supervisor」。任何在项目根目录下、命令行里**提到**这两个字符串的
# 无关进程（sha256sum 该脚本、grep 该路径、agent 的 prompt 文本）都被认成
# daemon/supervisor：start_daemon 因此静默返回 already、hosting_state 误报
# managed、stop_daemon 兜底 SIGKILL 可能打中无关进程。
#
# 本组用例刻意不 mock /proc 匹配（既有用例全部 mock 掉 _fenix_pids_under，
# 真实匹配零覆盖——正是漏网原因）：真起进程，断言「命令行提到」不算、
# 「正在执行该脚本」才算。


class TestProcessIdentityNotSubstring:
    """进程身份 = 正在执行该脚本，而非命令行里提到该路径。"""

    @staticmethod
    def _make_root(tmp_path) -> Path:
        root = (tmp_path / "proj").resolve()
        (root / ".fenix").mkdir(parents=True)
        (root / ".fenix" / "STATE.md").write_text("# state\n", encoding="utf-8")
        return root

    @staticmethod
    def _write_sleeper(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")

    @staticmethod
    def _spawn(argv, cwd, timeout: float = 5.0) -> subprocess.Popen:
        proc = subprocess.Popen(
            argv, cwd=str(cwd),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        # 轮询等 /proc/<pid>/cmdline 可读，而非固定 sleep(0.5)
        cmdline = Path("/proc") / str(proc.pid) / "cmdline"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if cmdline.read_bytes():
                    break
            except OSError:
                pass
            time.sleep(0.01)
        return proc

    # ── 假阳性方向 ────────────────────────────────────────────────

    def test_argv_mentioning_supervisor_is_not_a_daemon(self, tmp_path):
        """argv 提到 fenixd_supervisor（如 sha256sum/grep 该脚本）不算 daemon。"""
        root = self._make_root(tmp_path)
        decoy = self._spawn(
            ["python3", "-c", "import time; time.sleep(30)", "fenixd_supervisor"], root,
        )
        try:
            assert fenix_session.is_running(str(root)) is False
            assert fenix_session._fenix_pids_under(root) == []
        finally:
            decoy.kill()
            decoy.wait()

    def test_argv_mentioning_daemon_script_path_is_not_a_daemon(self, tmp_path):
        """argv 提到 .fenix/fenixd.py 字面量（未执行它）不算 daemon。"""
        root = self._make_root(tmp_path)
        decoy = self._spawn(
            ["python3", "-c", "import time; time.sleep(30)",
             str(root / ".fenix" / "fenixd.py")],
            root,
        )
        try:
            assert fenix_session.is_running(str(root)) is False
            assert fenix_session._fenix_pids_under(root) == []
        finally:
            decoy.kill()
            decoy.wait()

    def test_shell_mentioning_daemon_script_path_is_not_a_daemon(self, tmp_path):
        """shell 命令里带该路径（如 cat/grep）不算 daemon。"""
        root = self._make_root(tmp_path)
        decoy = self._spawn(
            ["sh", "-c", "sleep 30; :", str(root / ".fenix" / "fenixd.py")], root,
        )
        try:
            assert fenix_session.is_running(str(root)) is False
            assert fenix_session.hosting_state(str(root)) == "stopped"
        finally:
            decoy.kill()
            decoy.wait()

    def test_argv_mentioning_supervisor_is_not_supervisor(self, tmp_path):
        """argv 提到 fenixd_supervisor 不算 supervisor（不得误报 managed）。"""
        root = self._make_root(tmp_path)
        decoy = self._spawn(
            ["python3", "-c", "import time; time.sleep(30)", "fenixd_supervisor"], root,
        )
        try:
            assert fenix_session.supervisor_running(str(root)) is False
            assert fenix_session.hosting_state(str(root)) == "stopped"
        finally:
            decoy.kill()
            decoy.wait()

    # ── 真阳性方向（不得因收紧判据而漏报）────────────────────────

    def test_process_executing_daemon_script_is_detected(self, tmp_path):
        """真的在跑 .fenix/fenixd.py（cwd 相对路径）→ 判为 running。"""
        root = self._make_root(tmp_path)
        self._write_sleeper(root / ".fenix" / "fenixd.py")
        proc = self._spawn(["python3", ".fenix/fenixd.py"], root)
        try:
            assert fenix_session.is_running(str(root)) is True
            assert fenix_session._fenix_pids_under(root) == [str(proc.pid)]
        finally:
            proc.kill()
            proc.wait()
        assert fenix_session.is_running(str(root)) is False

    def test_process_executing_supervisor_script_is_detected(self, tmp_path):
        """真的在跑 .fenix/bin/fenixd_supervisor.py（cwd 内）→ supervisor_running。"""
        root = self._make_root(tmp_path)
        self._write_sleeper(root / ".fenix" / "bin" / "fenixd_supervisor.py")
        proc = self._spawn(
            ["python3", ".fenix/bin/fenixd_supervisor.py", "--project-root", str(root)],
            root,
        )
        try:
            assert fenix_session.supervisor_running(str(root)) is True
            assert fenix_session.hosting_state(str(root)) == "managed"
        finally:
            proc.kill()
            proc.wait()

    def test_supervisor_script_absolute_path_from_other_cwd_is_detected(self, tmp_path):
        """跨 cwd：绝对路径执行 supervisor 脚本 + --project-root 锚定 → 仍判 managed。"""
        root = self._make_root(tmp_path)
        script = root / ".fenix" / "bin" / "fenixd_supervisor.py"
        self._write_sleeper(script)
        elsewhere = (tmp_path / "elsewhere").resolve()
        elsewhere.mkdir()
        proc = self._spawn(
            ["python3", str(script), "--project-root", str(root)], elsewhere,
        )
        try:
            assert fenix_session.supervisor_running(str(root)) is True
        finally:
            proc.kill()
            proc.wait()
