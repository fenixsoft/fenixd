"""
add-systemd-hosting 承载层回归测试（core/systemd_hosting.py + 迁移面消费方）。

覆盖（与 tasks.md 6.1 一一对应）：
- unit 模板字段与安全化（unit_name_for 唯一性/点号折叠/非法字符折叠）
- unit 幂等安装（已装且活跃 already / 未装写+enable / enable 失败拒绝）
- supervisor 退出码协议（EXIT_CLEAN=0 / EXIT_GAVE_UP=75 与 unit SuccessExitStatus 成对）
- 会话身份 denylist 过滤与 0600 EnvironmentFile 落盘
- stop 双轨（unit 已装 systemctl stop --no-block / managed-but-no-unit 直接信号链 /
  systemctl 不可用退化直接信号链 / 快照补杀复核）
- dashboard 接管豁免（_parent_is_pid1 判定）
- restart-dashboard skip（unit 未装/systemctl 不可用静默跳过、legacy target 类型守卫）

全部经 monkeypatch 假 systemctl（不触真 systemd、不触真 tmux、不动真进程）。
"""
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pytest

import core.systemd_hosting as sh
import core.fenix_session as fenix_session
import bin.fenixd_supervisor as supervisor_mod


def _completed(rc=0, out="", err=""):
    return subprocess.CompletedProcess([], rc, out, err)


# ── unit 模板字段与安全化 ────────────────────────────────────────────────


class TestUnitNaming:
    def test_same_basename_different_paths_unique(self, tmp_path):
        """同名目录不同路径 unit 名唯一（哈希段，防覆写）。"""
        a = tmp_path / "repos" / "web"
        b = tmp_path / "other" / "web"
        assert sh.unit_name_for(a) != sh.unit_name_for(b)
        assert sh.unit_name_for(a) == sh.unit_name_for(tmp_path / "repos" / "web")

    def test_dots_folded_to_hyphen(self, tmp_path):
        """点号折叠为连字符（unit 后缀解析歧义防御）。"""
        name = sh.unit_name_for(tmp_path / "my.project")
        assert "my-project" in name
        assert ".service" in name
        assert name.count(".") == 1  # 仅后缀一个点

    def test_illegal_chars_folded_empty_fallback(self, tmp_path):
        d = tmp_path / "a b/c"
        d.mkdir(parents=True)
        name = sh.unit_name_for(tmp_path / "a b" / "c")
        assert name.startswith("fenixd-c-")
        assert sh.unit_name_for(tmp_path / "???") == f"fenixd-project-{__import__('hashlib').md5(str(tmp_path / '???').encode()).hexdigest()[:6]}.service"

    def test_stable_across_calls(self, tmp_path):
        assert sh.unit_name_for(tmp_path) == sh.unit_name_for(tmp_path)


class TestUnitTemplates:
    def test_project_unit_fields(self, tmp_path):
        text = sh.render_project_unit(tmp_path)
        assert f"WorkingDirectory={tmp_path}" in text
        assert f"ExecStart=python3 {tmp_path / '.fenix' / 'bin' / 'fenixd_supervisor.py'} --project-root {tmp_path}" in text
        assert "Restart=on-failure" in text
        assert f"SuccessExitStatus={sh.SUPERVISOR_GAVE_UP_EXIT_CODE}" in text
        assert f"TimeoutStopSec={sh.TIMEOUT_STOP_SEC}" in text
        assert "KillMode=mixed" in text
        assert f"EnvironmentFile=-{sh.project_env_file(tmp_path)}" in text
        assert f"StartLimitIntervalSec={sh.START_LIMIT_INTERVAL_SEC}" in text
        assert f"StartLimitBurst={sh.START_LIMIT_BURST}" in text
        assert "WantedBy=multi-user.target" in text

    def test_dashboard_unit_fields(self, tmp_path):
        text = sh.render_dashboard_unit(tmp_path)
        assert "ExecStart=python3" in text and "fenix_dashboard.py --serve" in text
        assert "Environment=FENIX_DASHBOARD_DETACH=1" in text
        assert "Restart=on-failure" in text
        # dashboard 无退出码协议：不声明 SuccessExitStatus
        assert "SuccessExitStatus" not in text
        assert f"EnvironmentFile=-{sh.dashboard_env_file(tmp_path)}" in text
        assert "WantedBy=multi-user.target" in text


# ── supervisor 退出码协议 ────────────────────────────────────────────────


class TestExitCodeProtocol:
    def test_supervisor_constants_pairing(self):
        """EXIT_GAVE_UP=75 与 systemd_hosting.SUPERVISOR_GAVE_UP_EXIT_CODE 成对（字面量漂移防线）。"""
        assert supervisor_mod.EXIT_CLEAN == 0
        assert supervisor_mod.EXIT_GAVE_UP == 75
        assert sh.SUPERVISOR_GAVE_UP_EXIT_CODE == 75

    def test_unit_declares_gave_up_as_success(self, tmp_path):
        """75 在 unit 模板声明为成功退出——on-failure 不拉回熔断/放弃看护。"""
        text = sh.render_project_unit(tmp_path)
        assert f"SuccessExitStatus={supervisor_mod.EXIT_GAVE_UP}" in text

    def test_on_failure_not_always(self, tmp_path):
        """Restart=on-failure 而非 always：always 会结构性架空熔断（design 决策 1）。"""
        text = sh.render_project_unit(tmp_path)
        assert "Restart=on-failure" in text
        assert "Restart=always" not in text


# ── 会话身份 denylist 与 0600 EnvironmentFile ───────────────────────────


class TestSessionIdentityDenylist:
    def test_denylist_prefixes_stripped(self):
        env = {
            "CLAUDE_PID": "12345",
            "CLAUDECODE": "1",
            "CLAUDE_CODE_SESSION_ID": "abc",
            "CLAUDE_CODE_ENTRYPOINT": "cli",
            "AI_AGENT": "claude",
            "IS_SANDBOX": "1",
            "GIT_ASKPASS": "/tmp/askpass",
            "ANTHROPIC_AUTH_TOKEN": "sk-secret",
            "ANTHROPIC_BASE_URL": "https://gw.example.com",
            "HTTPS_PROXY": "http://127.0.0.1:20122",
            "PATH": "/root/.local/bin:/usr/bin",
            "HOME": "/root",
            "API_TIMEOUT_MS": "600000",
        }
        filtered = sh.filter_session_identity(env)
        for key in ("CLAUDE_PID", "CLAUDECODE", "CLAUDE_CODE_SESSION_ID",
                    "CLAUDE_CODE_ENTRYPOINT", "AI_AGENT", "IS_SANDBOX", "GIT_ASKPASS"):
            assert key not in filtered
        for key in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "HTTPS_PROXY",
                    "PATH", "HOME", "API_TIMEOUT_MS"):
            assert filtered[key] == env[key]
        # 入参不被修改
        assert "CLAUDE_PID" in env

    def test_read_process_env_skips_invalid_lines(self, monkeypatch):
        """非法键名/含换行值跳过（EnvironmentFile 整行拒解析防御）。"""
        raw = b"GOOD=1\x00BASH_FUNC_x%%=(){ 0;}\x00BAD\nKEY=v\x00MULTI=a\nb\x00OK=2\x00"
        real_read_bytes = Path.read_bytes

        def fake_read_bytes(self):
            if str(self) == "/proc/4242/environ":
                return raw
            return real_read_bytes(self)

        monkeypatch.setattr(Path, "read_bytes", fake_read_bytes)
        env = sh.read_process_env(4242)
        assert env == {"GOOD": "1", "OK": "2"}

    def test_write_env_file_0600(self, tmp_path):
        target = tmp_path / "env"
        sh.write_env_file("K=V\n", target)
        assert (target.stat().st_mode & 0o777) == 0o600
        assert target.read_text() == "K=V\n"

    def test_render_env_file_quoting(self):
        text = sh.render_env_file({"PLAIN": "abc", "HASH": "a#b", "DOLLAR": "$X", "SQUOTE": "ab'cd"})
        assert "PLAIN=abc" in text
        # 双引号包裹形态（systemd 249 真机实测往返等价，item e63f37af8460）：
        # #/$/单引号在双引号段内均为字面量；旧 shell 风格 '\'' 序列同环境
        # 实测解析为错误字面量，不再采用。
        assert 'HASH="a#b"' in text
        assert 'DOLLAR="$X"' in text
        assert 'SQUOTE="ab\'cd"' in text

    def test_render_env_file_skips_invalid_entries(self):
        """渲染原语自含防线（item 7a87a7581069）：非法键名/含换行值/会话身份键
        不落 EnvironmentFile——防线不依赖唯一调用链（read_process_env +
        capture_env_candidate）自觉，绕过 capture 链直调同样安全。"""
        text = sh.render_env_file({
            "GOOD": "1",
            "WITH SPACE": "a b",
            "BASH_FUNC_x%%": "() { 0;}",
            "MULTI": "a\nb",
            "CRCHECK": "a\rb",
            "CLAUDE_PID": "9",
            "CLAUDECODE": "1",
        })
        assert "GOOD=1" in text
        assert "WITH SPACE" not in text
        assert "BASH_FUNC" not in text
        assert "MULTI=" not in text
        assert "CRCHECK=" not in text
        assert "CLAUDE_PID" not in text
        assert "CLAUDECODE" not in text

    def test_capture_env_candidate_writes_candidate_suffix(self, tmp_path):
        target = tmp_path / "systemd.env"
        # PATH 给全基线（add-dispatch-precheck-true-fallback 3.1）：基线并集
        # 对完整 PATH 零改写，本用例聚焦 denylist 过滤 + 后缀 + 0600 原语义；
        # 缺失补齐/留痕/逐字节不变情形由 tests/test_systemd_env_path_hygiene.py 覆盖。
        complete_path = ":".join(sh.PATH_BASELINE_DIRS)
        with mock.patch.object(
            sh, "read_process_env",
            return_value={"A": "1", "CLAUDE_PID": "9", "PATH": complete_path},
        ):
            keys = sh.capture_env_candidate(100, target)
        assert keys == {"A": "1", "PATH": complete_path}
        cand = Path(f"{target}{sh.ENV_CANDIDATE_SUFFIX}")
        assert cand.exists()
        assert "A=1" in cand.read_text()
        assert "CLAUDE_PID" not in cand.read_text()
        assert (cand.stat().st_mode & 0o777) == 0o600

    def test_capture_env_candidate_unreadable_pid_raises(self, tmp_path):
        with mock.patch.object(sh, "read_process_env", return_value={}):
            with pytest.raises(sh.SystemdHostingError):
                sh.capture_env_candidate(100, tmp_path / "x.env")


# ── systemctl 单缝与幂等安装 ─────────────────────────────────────────────


class TestSystemctlUnavailable:
    def test_unavailable_raises_readable_error(self, tmp_path):
        with mock.patch.object(sh, "systemctl_available", return_value=False):
            with pytest.raises(sh.SystemdHostingError) as ei:
                sh.install_project_unit(tmp_path)
            assert "需要 systemd" in str(ei.value)

    def test_unit_installed_unavailable_raises(self):
        with mock.patch.object(sh, "systemctl_available", return_value=False):
            with pytest.raises(sh.SystemdHostingError):
                sh.unit_installed("fenixd-x.service")

    def test_restart_dashboard_unavailable_skipped(self):
        """systemctl 不可用 → restart-dashboard 静默 skip（环境态非故障）。"""
        with mock.patch.object(sh, "systemctl_available", return_value=False):
            r = sh.restart_dashboard_unit()
        assert r["status"] == "skipped"


class TestIdempotentInstall:
    def _patch_run(self, monkeypatch, calls):
        def fake_run(args, timeout=30):
            calls.append(list(args))
            if args[0] == "list-unit-files":
                return _completed(0, "fenixd-x-abcdef.service enabled enabled\n" if self._installed else "", "")
            if args[0] == "is-active":
                return _completed(0 if self._active else 3, "active\n" if self._active else "inactive\n", "")
            return _completed(0, "", "")

        monkeypatch.setattr(sh, "_run_systemctl", fake_run)

    def test_already_installed_active_no_rewrite(self, tmp_path, monkeypatch):
        """已装且活跃重复安装：already=True，不重建不重启。"""
        self._installed = True
        self._active = True
        calls = []
        self._patch_run(monkeypatch, calls)
        writes = []
        monkeypatch.setattr(sh, "write_unit_file", lambda u, c: writes.append(u))
        r = sh.install_project_unit(tmp_path)
        assert r == {"ok": True, "error": None, "already": True, "unit": sh.unit_name_for(tmp_path)}
        assert writes == []
        assert not any(c[0] == "enable" for c in calls)

    def test_not_installed_writes_and_enables(self, tmp_path, monkeypatch):
        self._installed = False
        self._active = False
        calls = []
        self._patch_run(monkeypatch, calls)
        r = sh.install_project_unit(tmp_path)
        assert r["ok"] is True and r["already"] is False
        assert ["daemon-reload"] in calls
        assert ["enable", "--now", sh.unit_name_for(tmp_path)] in calls

    def test_enable_failure_raises(self, tmp_path, monkeypatch):
        self._installed = False
        self._active = False
        calls = []

        def fake_run(args, timeout=30):
            calls.append(list(args))
            if args[0] == "list-unit-files":
                return _completed(0, "", "")
            if args[0] == "enable":
                return _completed(1, "", "Failed to enable unit")
            return _completed(0, "", "")

        monkeypatch.setattr(sh, "_run_systemctl", fake_run)
        with pytest.raises(sh.SystemdHostingError) as ei:
            sh.install_project_unit(tmp_path)
        assert "enable" in str(ei.value)

    def test_write_unit_file_goes_to_unit_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sh, "SYSTEMD_UNIT_DIR", tmp_path)
        p = sh.write_unit_file("fenixd-t.service", "[Unit]\n")
        assert p == tmp_path / "fenixd-t.service"
        assert (tmp_path / "fenixd-t.service").read_text() == "[Unit]\n"
        assert (tmp_path / "fenixd-t.service").stat().st_mode & 0o777 == 0o644


# ── stop 双轨（fenix_session.stop_daemon）────────────────────────────────


class TestStopDualTrack:
    def _mkproj(self, tmp_path):
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True)
        (proot / ".fenix" / "STATE.md").write_text("# s\n", encoding="utf-8")
        return proot

    def _base_patches(self, monkeypatch, proot, pids=("111", "222"), alive_seq=None):
        """alive_seq：_alive_pids 按 _alive_pids 调用序出响应（耗尽后恒 []）。

        响应序即 stop 主流程时序：轮询（1 次，空=立即全退）→ 残留复核 →
        补杀后复核（轮询/终判）。空轮询 + 非空残留 = 「等待窗内退出又复活」
        的人工快进，等效 30s 超时路径。
        """
        monkeypatch.setattr(fenix_session, "is_running", lambda root=None: True)
        monkeypatch.setattr(fenix_session, "_fenix_pids_under", lambda root: list(pids))
        seq = list(alive_seq or [])
        monkeypatch.setattr(
            fenix_session, "_alive_pids", lambda pids_: seq.pop(0) if seq else []
        )
        monkeypatch.setattr(fenix_session.time, "sleep", lambda s: None)
        return pids

    def test_hosted_track_uses_systemctl_stop_no_block(self, tmp_path, monkeypatch):
        """unit 已装主轨：systemctl stop --no-block，不走直接信号链。"""
        proot = self._mkproj(tmp_path)
        self._base_patches(monkeypatch, proot)
        unit = sh.unit_name_for(proot)
        monkeypatch.setattr(fenix_session, "unit_installed", lambda u: True)
        stop_calls = []
        monkeypatch.setattr(fenix_session, "stop_unit_no_block",
                            lambda u: stop_calls.append(u))
        sigterms = []
        monkeypatch.setattr(fenix_session, "_is_daemon_cmdline", lambda pid, root: False)
        monkeypatch.setattr(os, "kill", lambda pid, sig: sigterms.append((pid, sig)))
        r = fenix_session.stop_daemon(str(proot))
        assert r == {"ok": True, "error": None, "was_running": True}
        assert stop_calls == [unit]
        assert sigterms == []
        # ⑤ 无论成败清 stop
        assert not (proot / ".fenix" / "stop").exists()

    def test_no_unit_track_direct_signal_chain(self, tmp_path, monkeypatch):
        """managed-but-no-unit：直接信号链 SIGTERM daemon，MUST NOT systemctl no-op 假成功。"""
        proot = self._mkproj(tmp_path)
        self._base_patches(monkeypatch, proot)
        monkeypatch.setattr(fenix_session, "unit_installed", lambda u: False)
        stop_calls = []
        monkeypatch.setattr(fenix_session, "stop_unit_no_block",
                            lambda u: stop_calls.append(u))
        sigterms = []
        monkeypatch.setattr(fenix_session, "_is_daemon_cmdline", lambda pid, root: pid == "111")
        monkeypatch.setattr(os, "kill", lambda pid, sig: sigterms.append((int(pid), sig)))
        r = fenix_session.stop_daemon(str(proot))
        assert r["ok"] is True
        assert stop_calls == []
        assert (111, signal.SIGTERM) in sigterms
        assert not (proot / ".fenix" / "stop").exists()

    def test_systemctl_unavailable_falls_back_direct_chain(self, tmp_path, monkeypatch):
        """systemctl 不可用：unit 判定退化，走直接信号链不阻断收口。"""
        proot = self._mkproj(tmp_path)
        self._base_patches(monkeypatch, proot)

        def raise_err(u):
            raise sh.SystemdHostingError("需要 systemd：systemctl 不可用")

        monkeypatch.setattr(fenix_session, "unit_installed", raise_err)
        sigterms = []
        monkeypatch.setattr(fenix_session, "_is_daemon_cmdline", lambda pid, root: pid == "222")
        monkeypatch.setattr(os, "kill", lambda pid, sig: sigterms.append((int(pid), sig)))
        r = fenix_session.stop_daemon(str(proot))
        assert r["ok"] is True
        assert (222, signal.SIGTERM) in sigterms

    def test_hosted_timeout_snapshot_sigkill(self, tmp_path, monkeypatch):
        """主轨超时兜底：只杀快照残留（不重扫），补杀前复核。"""
        proot = self._mkproj(tmp_path)
        monkeypatch.setattr(fenix_session, "is_running", lambda root=None: True)
        monkeypatch.setattr(fenix_session, "_fenix_pids_under", lambda root: ["111", "222"])
        monkeypatch.setattr(fenix_session.time, "sleep", lambda s: None)
        monkeypatch.setattr(fenix_session, "unit_installed", lambda u: True)
        monkeypatch.setattr(fenix_session, "stop_unit_no_block", lambda u: None)
        # 111 已退；222 残留。_alive_pids 响应序即主流程时序：轮询见残留继续
        # 等 → 轮询空退出 → 超时兜底 remaining 复核仍见残留 → 补杀 → 补杀后
        # 复核全退（耗尽恒 []）。
        alive_seq = [["222"], [], ["222"]]
        monkeypatch.setattr(
            fenix_session, "_alive_pids", lambda pids: alive_seq.pop(0) if alive_seq else []
        )
        monkeypatch.setattr(fenix_session, "_is_snapshot_proc_cmdline", lambda pid, root: None)
        kills = []
        monkeypatch.setattr(os, "kill", lambda pid, sig: kills.append((int(pid), sig)))
        r = fenix_session.stop_daemon(str(proot))
        assert r["ok"] is True
        assert (222, signal.SIGKILL) in kills
        assert not any(sig == signal.SIGKILL and pid == 111 for pid, sig in kills)
        assert not (proot / ".fenix" / "stop").exists()

    def test_sigkill_recheck_pid_reuse_skipped(self, tmp_path, monkeypatch):
        """补杀前复核 False（疑似 pid 复用）：跳过补杀计入 error，不盲杀。"""
        proot = self._mkproj(tmp_path)
        monkeypatch.setattr(fenix_session, "is_running", lambda root=None: True)
        monkeypatch.setattr(fenix_session, "_fenix_pids_under", lambda root: ["333"])
        monkeypatch.setattr(fenix_session.time, "sleep", lambda s: None)
        monkeypatch.setattr(fenix_session, "unit_installed", lambda u: True)
        monkeypatch.setattr(fenix_session, "stop_unit_no_block", lambda u: None)
        # 响应序：轮询见残留 → 轮询空退出 → remaining 复核仍残留（拟超时快进）
        alive_seq = [["333"], [], ["333"]]
        monkeypatch.setattr(
            fenix_session, "_alive_pids", lambda pids: alive_seq.pop(0) if alive_seq else []
        )
        monkeypatch.setattr(fenix_session, "_is_snapshot_proc_cmdline", lambda pid, root: False)
        kills = []
        monkeypatch.setattr(os, "kill", lambda pid, sig: kills.append((int(pid), sig)))
        r = fenix_session.stop_daemon(str(proot))
        assert r["ok"] is False
        assert "疑似 pid 复用" in r["error"]
        assert (333, signal.SIGKILL) not in kills

    def test_stop_not_running_idempotent(self, tmp_path, monkeypatch):
        """停止未运行项目：幂等成功，不写 stop 文件。"""
        proot = self._mkproj(tmp_path)
        monkeypatch.setattr(fenix_session, "is_running", lambda root=None: False)
        r = fenix_session.stop_daemon(str(proot))
        assert r == {"ok": True, "error": None, "was_running": False}
        assert not (proot / ".fenix" / "stop").exists()


# ── dashboard 接管豁免（_parent_is_pid1）─────────────────────────────────


class TestParentIsPid1:
    # _parent_is_pid1 经 Path.read_text() 读取（内部 io.open，非 builtins.open），
    # patch builtins.open 无效；须类级 patch pathlib.Path.read_text 并按路径
    # 条件转发真实实现，否则读到宿主真 /proc 判定漂移。
    def _fake_stat_read(self, monkeypatch, pid, stat_line):
        import pathlib
        real_read_text = pathlib.Path.read_text

        def fake_read_text(self, *a, **kw):
            if str(self) == f"/proc/{pid}/stat":
                return stat_line
            return real_read_text(self, *a, **kw)

        monkeypatch.setattr(pathlib.Path, "read_text", fake_read_text)

    def test_ppid1_true(self, monkeypatch):
        """ppid==1 → True（unit 承载常驻实例形态）。comm 含空格/括号走 rindex 解析。"""
        self._fake_stat_read(monkeypatch, 1234, "1234 (fenix dash) S 1 1234 1 0 -1 4194560 0 0 0 0 0 0 0 0 20 0 1 0 12345 6553600 100 18446744073709551615 0 0 0 0 0 0 0 16781315 1 0 0 0 17 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n")
        from core.dashboard.server import _parent_is_pid1
        assert _parent_is_pid1(1234) is True

    def test_ppid_not1_false(self, monkeypatch):
        self._fake_stat_read(monkeypatch, 1234, "1234 (python3) S 99999 1234 1 0 -1 4194560 0 0 0 0 0 0 0 0 20 0 1 0 12345 6553600 100 18446744073709551615 0 0 0 0 0 0 0 16781315 1 0 0 0 17 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n")
        from core.dashboard.server import _parent_is_pid1
        assert _parent_is_pid1(1234) is False

    def test_unreadable_false(self, monkeypatch):
        """/proc 读取失败 → False（偏向放行接管路径，不自伤）。"""
        import pathlib
        real_read_text = pathlib.Path.read_text

        def fake_read_text(self, *a, **kw):
            if str(self) == "/proc/999999/stat":
                raise OSError("no such process")
            return real_read_text(self, *a, **kw)

        monkeypatch.setattr(pathlib.Path, "read_text", fake_read_text)
        from core.dashboard.server import _parent_is_pid1
        assert _parent_is_pid1(999999) is False

    def test_real_child_is_not_pid1_child(self):
        """真进程对照：子进程父进程是本测试进程，非 1。"""
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
        try:
            from core.dashboard.server import _parent_is_pid1
            assert _parent_is_pid1(proc.pid) is False
        finally:
            proc.kill()
            proc.wait()


# ── restart-dashboard（hook_engine 执行侧）───────────────────────────────


class TestRestartDashboardAction(unittest.TestCase):
    def _eng(self):
        from core.hook_engine import HookEngine

        return HookEngine(Path(tempfile.mkdtemp()) / "proj", {"project": {"name": "t"}},
                          logger=mock.MagicMock(), admin_store=mock.MagicMock())

    def test_unit_not_installed_silent_skip(self):
        """unit 未安装 → skipped（环境态，与旧 tmux 无会话语义对齐）。"""
        eng = self._eng()
        with mock.patch("core.systemd_hosting.restart_dashboard_unit",
                        return_value={"status": "skipped", "detail": "unit 未安装"}):
            status, detail = eng._action_restart_dashboard({})
        assert status == "skipped"

    def test_systemctl_unavailable_silent_skip(self):
        eng = self._eng()
        with mock.patch("core.systemd_hosting.restart_dashboard_unit",
                        return_value={"status": "skipped", "detail": "systemctl 不可用"}):
            status, _ = eng._action_restart_dashboard({})
        assert status == "skipped"

    def test_restart_failure_reported(self):
        eng = self._eng()
        with mock.patch("core.systemd_hosting.restart_dashboard_unit",
                        return_value={"status": "failure", "detail": "restart 失败"}):
            status, detail = eng._action_restart_dashboard({})
        assert status == "failure"
        assert "restart 失败" in detail

    def test_success_probes_port_and_stamps_debounce(self):
        eng = self._eng()
        with mock.patch("core.systemd_hosting.restart_dashboard_unit",
                        return_value={"status": "success", "detail": "已重启"}), \
             mock.patch.object(type(eng), "_probe_dashboard", return_value=True):
            status, _ = eng._action_restart_dashboard({})
        assert status == "success"
        assert eng._dashboard_restart_ok_monotonic > 0
        # 去抖窗口内二次触发幂等跳过
        status2, detail2 = eng._action_restart_dashboard({})
        assert status2 == "skipped"
        assert "去抖" in detail2

    def test_legacy_target_non_string_rejected(self):
        """legacy target 键类型守卫：非字符串按配置非法记 failure（防归因降级）。"""
        eng = self._eng()
        status, detail = eng._action_restart_dashboard({"target": 123})
        assert status == "failure"
        assert "配置非法" in detail

    def test_legacy_target_string_tolerated_not_consumed(self):
        """legacy target 字符串值容忍存在不消费：正常走 restart 流程。"""
        eng = self._eng()
        with mock.patch("core.systemd_hosting.restart_dashboard_unit",
                        return_value={"status": "skipped", "detail": "unit 未安装"}) as m:
            status, _ = eng._action_restart_dashboard({"target": "old-session"})
        assert m.call_count == 1  # target 值未参与任何执行面
        assert status == "skipped"


# ── 迁移脚本编排单元（migrate_to_systemd 纯逻辑面）───────────────────────


class TestMigrateScriptHelpers:
    def _load_mig(self):
        import importlib.util

        root = Path(__file__).resolve().parent.parent
        spec = importlib.util.spec_from_file_location(
            "migrate_to_systemd", root / "bin" / "migrate_to_systemd.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_retired_session_name_matches_old_derivation(self, tmp_path):
        """旧 session 名派生与退役实现逐字同口径（拆链打中真实会话的前提）。"""
        import hashlib
        import re

        mig = self._load_mig()
        proot = tmp_path / "my.proj"
        expected = (
            "fenixd-"
            + (re.sub(r"[^A-Za-z0-9-]+", "-", proot.name).strip("-") or "project")
            + "-"
            + hashlib.md5(str(proot).encode()).hexdigest()[:6]
        )
        assert mig.retired_session_name(proot) == expected

    def test_teardown_old_chain_snapshot_empty_noop(self, tmp_path):
        mig = self._load_mig()
        with mock.patch.object(mig, "_fenix_pids_under", return_value=[]):
            r = mig.teardown_old_project_chain(tmp_path, dry_run=False)
        assert r["was_running"] is False and r["ok"] is True

    def test_teardown_old_chain_dry_run_no_signals(self, tmp_path):
        """dry-run 拆链只打印计划：零信号、零文件副作用。"""
        mig = self._load_mig()
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True)
        with mock.patch.object(mig, "_fenix_pids_under", return_value=["111", "222"]), \
             mock.patch.object(mig.os, "kill") as kill_mock, \
             mock.patch.object(mig.subprocess, "run") as run_mock:
            r = mig.teardown_old_project_chain(proot, dry_run=True)
        assert r["was_running"] is True and "[dry-run]" in r["detail"]
        kill_mock.assert_not_called()
        run_mock.assert_not_called()
        assert not (proot / ".fenix" / "stop").exists()

    def test_teardown_old_dashboard_no_proc_noop(self):
        mig = self._load_mig()
        with mock.patch.object(mig.sh, "find_framework_dashboard_pid", return_value=None):
            r = mig.teardown_old_dashboard(Path("/tmp"), dry_run=False)
        assert r["was_running"] is False and r["ok"] is True

    def test_teardown_old_dashboard_dry_run_no_kill(self):
        mig = self._load_mig()
        with mock.patch.object(mig.sh, "find_framework_dashboard_pid", return_value=4242), \
             mock.patch.object(mig, "dashboard_port", return_value=8787), \
             mock.patch.object(mig.os, "kill") as kill_mock, \
             mock.patch.object(mig, "port_occupied", return_value=True):
            r = mig.teardown_old_dashboard(Path("/tmp"), dry_run=True)
        assert "[dry-run]" in r["detail"]
        kill_mock.assert_not_called()

    def test_stage1_dry_run_writes_nothing(self, tmp_path):
        """① 阶段 dry-run：不写 unit、不落 env 候选稿（零副作用）。"""
        mig = self._load_mig()
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True)
        with mock.patch.object(mig, "_project_hosting_pid", return_value=100), \
             mock.patch.object(mig.sh, "read_process_env", return_value={"A": "1"}), \
             mock.patch.object(mig.sh, "find_framework_dashboard_pid", return_value=None), \
             mock.patch.object(mig.sh, "write_unit_file") as wu, \
             mock.patch.object(mig.sh, "write_env_file") as we:
            r = mig.stage1_write_units_and_env(proot, tmp_path, dry_run=True)
        assert r["ok"] is True
        wu.assert_not_called()
        we.assert_not_called()

    def test_stage3_promotes_candidate_only_when_formal_missing(self, tmp_path):
        """正式 env 缺失以候选稿补位（0600）；已有正式以正式为准不覆盖。"""
        mig = self._load_mig()
        env_path = sh.project_env_file(tmp_path)
        cand = Path(f"{env_path}{sh.ENV_CANDIDATE_SUFFIX}")
        cand.parent.mkdir(parents=True)
        cand.write_text("A=1\n", encoding="utf-8")
        os.chmod(cand, 0o600)
        calls = []

        def fake_install(root):
            calls.append(root)
            return {"ok": True, "error": None, "already": False, "unit": "u"}

        with mock.patch.object(mig.sh, "install_project_unit", fake_install), \
             mock.patch.object(mig.sh, "install_dashboard_unit", fake_install):
            r = mig.stage3_enable_units(tmp_path, tmp_path, dry_run=False)
        assert r["ok"] is True
        assert env_path.exists() and not cand.exists()
        assert (env_path.stat().st_mode & 0o777) == 0o600
        # 已有正式 env：候选稿不覆盖
        env_path.write_text("FORMAL=1\n", encoding="utf-8")
        cand.write_text("A=1\n", encoding="utf-8")
        with mock.patch.object(mig.sh, "install_project_unit", fake_install), \
             mock.patch.object(mig.sh, "install_dashboard_unit", fake_install):
            mig.stage3_enable_units(tmp_path, tmp_path, dry_run=False)
        assert env_path.read_text() == "FORMAL=1\n"


class TestMigrateFullOrchestrationDryRun(TestMigrateScriptHelpers):
    """全编排 migrate(dry_run=True) 对 fixture 项目根零副作用（tasks 6.3）。

    宿主实跑预演（exit 0 + fixture 零新增文件 + 在跑进程零信号 + 无 unit
    落盘）已在实现 run 完成并留档（.fenix/verify-evidence/add-systemd-hosting/
    migrate-dry-run-fixture-2026-11-04.log）；此处以假 systemctl/env mock 固化
    同一断言，防后续编排改动漂移副作用语义。
    """

    def test_dry_run_full_orchestration_no_side_effects(self, tmp_path, monkeypatch):
        mig = self._load_mig()
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True)
        (proot / ".fenix" / "STATE.md").write_text("# s\n", encoding="utf-8")
        before = sorted(str(p.relative_to(proot)) for p in proot.rglob("*"))
        monkeypatch.setattr(sh, "systemctl_available", lambda: True)
        monkeypatch.setattr(sh, "unit_installed", lambda unit: False)
        monkeypatch.setattr(sh, "read_process_env",
                            lambda pid: {"PATH": "/usr/bin", "HOME": "/root"})
        monkeypatch.setattr(sh, "find_framework_dashboard_pid", lambda: None)
        # 模拟「项目在跑」（迁移前置门要求非 stopped）：快照与 hosting pid 指向假 pid
        monkeypatch.setattr(mig, "_fenix_pids_under", lambda root: ["419000"])
        monkeypatch.setattr(mig, "_project_hosting_pid", lambda root: 419000)
        rc = mig.migrate(proot, tmp_path / "froot", True)
        assert rc == 0
        after = sorted(str(p.relative_to(proot)) for p in proot.rglob("*"))
        assert before == after, (
            "dry-run 不得在项目根落任何文件（unit/env 候选稿/.fenix/stop 旗标）"
        )

    def test_dry_run_rejects_stopped_project(self, tmp_path, monkeypatch):
        """stopped 态且 unit 未装 → 退出码 1（design Non-Goals：env 无源可捕）。"""
        mig = self._load_mig()
        proot = tmp_path / "proj-stopped"
        (proot / ".fenix").mkdir(parents=True)
        (proot / ".fenix" / "STATE.md").write_text("# s\n", encoding="utf-8")
        monkeypatch.setattr(sh, "systemctl_available", lambda: True)
        monkeypatch.setattr(sh, "unit_installed", lambda unit: False)
        monkeypatch.setattr(mig, "_fenix_pids_under", lambda root: [])
        rc = mig.migrate(proot, tmp_path / "froot", True)
        assert rc == 1
