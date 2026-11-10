"""platform-abstraction PAL 行为对齐单测。

按 core/platform/ 六组 PAL 接口组织（A 进程生命周期 / B 进程情报 /
C 文件锁 / D 托管 / E 环境用户文件系统 / F 测试基建锚点）。本文件随
W1 前置扩展先行建立（with_file_lock 三形态，tasks.md 1.1），W3 骨架
落地后补齐 A–E 组行为对齐断言（tasks.md 2.2）。

行为对齐口径（spec「Linux 行为零变化」）：每个接口断言与被平移源实现
等价的行为锚点，而非 PAL 内部实现细节。
"""
import errno
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import fs_utils


# ══════════════════════════════════════════════════════════════════
# C 组文件锁：with_file_lock 三形态（tasks.md 1.1）
# ══════════════════════════════════════════════════════════════════


def _hold_companion_lock(target: Path):
    """在目标伴生 ``.<name>.lock`` 上另开 fd 持锁（模拟他方持锁者）。

    flock 按打开文件描述符生效：同进程另开 fd 亦互斥（serving_registry /
    verify_report 既有注释口径），故本进程内即可模拟跨进程竞争。
    返回 (fd, lock_path)；调用方负责 close 释放。
    """
    lock_path = target.parent / f".{target.name}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
    import fcntl

    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd, lock_path


class TestWithFileLockDefaultForm:
    """默认形态：与现行阻塞 LOCK_EX 语义完全一致（spec Scenario「默认参数行为不变」）。"""

    def test_runs_fn_and_returns_result(self, tmp_path):
        target = tmp_path / "data.json"
        result = fs_utils.with_file_lock(target, lambda: {"ok": True})
        assert result == {"ok": True}

    def test_creates_companion_lock_file_layout(self, tmp_path):
        target = tmp_path / "data.json"
        fs_utils.with_file_lock(target, lambda: None)
        assert (tmp_path / ".data.json.lock").exists()

    def test_lock_released_after_return(self, tmp_path):
        target = tmp_path / "data.json"
        fs_utils.with_file_lock(target, lambda: None)
        # 释放后另开 fd 的 NB 尝试应立即成功（不抛 EAGAIN）
        fd = os.open(str(tmp_path / ".data.json.lock"), os.O_RDWR | os.O_CREAT)
        try:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)

    def test_lock_held_during_fn(self, tmp_path):
        target = tmp_path / "data.json"
        observed = {}

        # fn 执行期间锁被本调用持有：另开 fd 的 NB 抢锁应失败（EAGAIN）
        def probe_held():
            lock_path = tmp_path / ".data.json.lock"
            fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT)
            try:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                observed["held"] = False
            except OSError as e:
                observed["held"] = e.errno in (errno.EAGAIN, errno.EACCES)
            finally:
                os.close(fd)

        fs_utils.with_file_lock(target, probe_held)
        assert observed["held"] is True


class TestWithFileLockNonblockingForm:
    """nonblocking=True：锁被占时立即失败不阻塞（spec Scenario「NB fail-fast 语义保持」）。"""

    def test_nb_acquires_when_free(self, tmp_path):
        target = tmp_path / "data.json"
        result = fs_utils.with_file_lock(
            target, lambda: "ran", nonblocking=True
        )
        assert result == "ran"

    def test_nb_busy_fails_fast_without_running_fn(self, tmp_path):
        target = tmp_path / "data.json"
        fd, _ = _hold_companion_lock(target)
        try:
            ran = {"called": False}

            def fn():
                ran["called"] = True

            start = time.monotonic()
            with pytest.raises(fs_utils.FileLockBusy):
                fs_utils.with_file_lock(target, fn, nonblocking=True)
            elapsed = time.monotonic() - start
            # 立即返回失败：远小于任何阻塞等待（现行 NB 消费点口径）
            assert elapsed < 2.0
            assert ran["called"] is False
        finally:
            os.close(fd)

    def test_nb_busy_single_attempt_when_timeout_zero(self, tmp_path):
        target = tmp_path / "data.json"
        fd, _ = _hold_companion_lock(target)
        try:
            start = time.monotonic()
            with pytest.raises(fs_utils.FileLockBusy):
                fs_utils.with_file_lock(
                    target, lambda: None, nonblocking=True, timeout_s=0
                )
            assert time.monotonic() - start < 0.5
        finally:
            os.close(fd)


class TestWithFileLockTimeoutForm:
    """nonblocking=True + timeout_s：限时轮询后仍 busy 才失败。"""

    def test_timeout_waits_then_raises_busy(self, tmp_path):
        target = tmp_path / "data.json"
        fd, _ = _hold_companion_lock(target)
        try:
            start = time.monotonic()
            with pytest.raises(fs_utils.FileLockBusy):
                fs_utils.with_file_lock(
                    target, lambda: None, nonblocking=True, timeout_s=0.3
                )
            # 限时轮询确实等待了近似 timeout_s 才放弃
            assert time.monotonic() - start >= 0.25
        finally:
            os.close(fd)

    def test_timeout_acquires_when_holder_releases_midway(self, tmp_path):
        target = tmp_path / "data.json"
        fd, _ = _hold_companion_lock(target)

        import threading

        def release_soon():
            time.sleep(0.15)
            os.close(fd)

        t = threading.Thread(target=release_soon)
        t.start()
        try:
            result = fs_utils.with_file_lock(
                target, lambda: "after-wait", nonblocking=True, timeout_s=5.0
            )
            assert result == "after-wait"
        finally:
            t.join()


class TestFileLockUnavailableMapping:
    """非「锁被占」类 errno：立即抛 FileLockUnavailable（不轮询不降级）。"""

    def test_non_retryable_errno_maps_to_unavailable(self, tmp_path, monkeypatch):
        target = tmp_path / "data.json"

        def _raise_enolck(fileobj, *, nonblocking=False):
            raise OSError(errno.ENOLCK, "No locks available")

        monkeypatch.setattr(fs_utils, "flock_exclusive", _raise_enolck)
        with pytest.raises(fs_utils.FileLockUnavailable):
            fs_utils.with_file_lock(
                target, lambda: None, nonblocking=True, timeout_s=5.0
            )


class TestFlockPrimitives:
    """flock_exclusive / flock_release 单源原语（消费点自持 fd 形态）。"""

    def test_exclusive_then_release_roundtrip(self, tmp_path):
        p = tmp_path / "lockfile"
        fd = os.open(str(p), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fs_utils.flock_exclusive(fd, nonblocking=True)
            fs_utils.flock_release(fd)
            # 释放后另 fd 可再抢
            fd2 = os.open(str(p), os.O_RDWR | os.O_CREAT, 0o644)
            try:
                fs_utils.flock_exclusive(fd2, nonblocking=True)
            finally:
                os.close(fd2)
        finally:
            os.close(fd)

    def test_blocking_default_form(self, tmp_path):
        p = tmp_path / "lockfile"
        fd = os.open(str(p), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fs_utils.flock_exclusive(fd)
            fs_utils.flock_release(fd)
        finally:
            os.close(fd)

    def test_busy_raises_oserror_with_errno(self, tmp_path):
        p = tmp_path / "lockfile"
        fd1 = os.open(str(p), os.O_RDWR | os.O_CREAT, 0o644)
        fd2 = os.open(str(p), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fs_utils.flock_exclusive(fd1, nonblocking=True)
            with pytest.raises(OSError) as exc_info:
                fs_utils.flock_exclusive(fd2, nonblocking=True)
            assert exc_info.value.errno in (errno.EAGAIN, errno.EACCES)
        finally:
            os.close(fd1)
            os.close(fd2)


# ══════════════════════════════════════════════════════════════════
# W3 骨架（tasks.md 2.2）：A–E/F 组行为对齐 + 后端契约形制
# ══════════════════════════════════════════════════════════════════

import signal
import socket
import subprocess

from core.platform import api as pal
from core.platform import linux as pal_linux
from core.platform import win32 as pal_win32


def _pid_ceiling() -> int:
    """超出内核 pid_max 的必死 pid（ESRCH 判定用，杜绝 pid 复用竞态）。"""
    try:
        return int(Path("/proc/sys/kernel/pid_max").read_text().strip()) + 1
    except OSError:
        return 2 ** 22


def _spawn_sleeper(tmp_path=None):
    """独立进程组 sleep 子进程（A/B 组真进程锚），调用方负责终止+收尸。"""
    proc = pal.spawn_detached(["sleep", "30"], cwd=str(tmp_path) if tmp_path else None)
    return proc


def _reap(proc):
    if proc.poll() is None:
        proc.kill()
    proc.wait(timeout=5)


# ── 后端契约形制（api 六组 Protocol 结构化断言）───────────────────────

class TestBackendContractShape:
    def test_linux_conforms_to_all_six_protocols(self):
        from core.platform import api as api_contract

        for proto in (api_contract.ProcessLifecycle, api_contract.ProcessIntelligence,
                      api_contract.FileLocking, api_contract.HostingSeam,
                      api_contract.EnvironmentUserFs, api_contract.TestInfra):
            assert isinstance(pal_linux, proto), proto.__name__

    def test_win32_placeholder_conforms_to_all_six_protocols(self):
        # SPEC-2 占位后端同签名（调用面 NotImplementedError 导向），形制一致
        from core.platform import api as api_contract

        for proto in (api_contract.ProcessLifecycle, api_contract.ProcessIntelligence,
                      api_contract.FileLocking, api_contract.HostingSeam,
                      api_contract.EnvironmentUserFs, api_contract.TestInfra):
            assert isinstance(pal_win32, proto), proto.__name__

    def test_business_facade_is_injected_backend(self):
        # __init__.py 单点分发：门面属性即 linux 后端实现对象
        assert pal.spawn_detached is pal_linux.spawn_detached
        assert pal.kill_tree is pal_linux.kill_tree
        assert pal.IS_WINDOWS is False
        assert pal_win32.IS_WINDOWS is True


# ── A 组进程生命周期 ─────────────────────────────────────────────────

class TestSpawnDetached:
    def test_new_session_true_creates_session_leader(self):
        proc = _spawn_sleeper()
        try:
            # start_new_session=True 平移锚：子进程独立成组（pgid == pid）
            assert os.getpgid(proc.pid) == proc.pid
        finally:
            _reap(proc)

    def test_new_session_false_stays_in_caller_group(self):
        # runner.py:7030 动态 passthrough 语义锚：False = 无独立进程组
        proc = pal.spawn_detached(["sleep", "30"], new_session=False)
        try:
            assert os.getpgid(proc.pid) == os.getpgid(0)
        finally:
            _reap(proc)

    def test_kwargs_passthrough_and_cwd_env(self, tmp_path):
        proc = pal.spawn_detached(
            ["sleep", "30"], cwd=str(tmp_path), env={"PATH": os.environ["PATH"]},
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            assert pal.readlink_cwd(proc.pid) == str(tmp_path)
        finally:
            _reap(proc)


class TestRunDetached:
    def test_completed_process_form_preserved(self):
        cp = pal.run_detached([sys.executable, "-c", "print('ok')"],
                              capture_output=True, text=True)
        assert cp.returncode == 0
        assert cp.stdout.strip() == "ok"

    def test_new_session_leader_semantics(self):
        # run 形态同保独立进程组语义：子进程自报 pgid == pid（会话首进程）
        cp = pal.run_detached(
            [sys.executable, "-c", "import os; print(os.getpgid(0) == os.getpid())"],
            capture_output=True, text=True,
        )
        assert cp.returncode == 0
        assert cp.stdout.strip() == "True"


class TestSpawnDetachedAsync:
    def test_exec_form_new_session(self):
        import asyncio

        async def _go():
            proc = await pal.spawn_detached_async(["sleep", "30"])
            try:
                # asyncio.Process 与 Popen 形态差异：断言在 loop 内完成，
                # 收尸走 terminate + await wait（无 .poll()/.wait() 同步形态）
                return os.getpgid(proc.pid) == proc.pid
            finally:
                proc.terminate()
                await proc.wait()

        assert asyncio.run(_go()) is True

    def test_shell_form_returncode(self):
        import asyncio

        async def _go():
            proc = await pal.spawn_detached_async("exit 0", shell=True)
            await proc.wait()
            return proc.returncode

        assert asyncio.run(_go()) == 0


class TestTerminateGraceful:
    def test_sigterm_then_exit(self):
        proc = _spawn_sleeper()
        pal.terminate_graceful(proc, grace_s=2)
        assert proc.returncode == -signal.SIGTERM

    def test_timeout_escalates_to_sigkill(self):
        # 子进程打 ready 行后 SIGTERM IGNORE 才装好（否则 TERM 落在解释器
        # 启动窗内按默认动作即死，升级纪律无从验证）
        proc = pal.spawn_detached(
            [sys.executable, "-c",
             "import signal, sys; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
             "print('ready', flush=True); import time; time.sleep(30)"],
            stdout=subprocess.PIPE, text=True)
        try:
            assert proc.stdout.readline().strip() == "ready"
            pal.terminate_graceful(proc, grace_s=0.5)
            assert proc.wait(timeout=5) == -signal.SIGKILL
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)


class TestKillTreeGuard:
    """guard_killpg 语义锚（pal.kill_tree；执行跳宿主迁移后语义逐位一致）。"""

    def test_own_process_group_rejected(self):
        own_pgid = os.getpgid(0)
        assert pal.kill_tree(own_pgid, signal.SIGTERM, caller="t.pal", resolve=False) is False

    def test_nonpositive_pgid_rejected_both(self):
        assert pal.kill_tree(0, signal.SIGTERM, caller="t.pal", resolve=False) is False
        assert pal.kill_tree(-1, signal.SIGTERM, caller="t.pal", resolve=False) is False

    def test_resolve_form_esrch_silent_false(self):
        dead = _pid_ceiling()
        assert pal.kill_tree(dead, signal.SIGTERM, caller="t.pal", resolve=True) is False

    def test_resolve_form_hits_own_group_rejected(self):
        assert pal.kill_tree(os.getpid(), signal.SIGTERM, caller="t.pal", resolve=True) is False

    def test_direct_form_real_group_killed(self):
        proc = _spawn_sleeper()
        try:
            assert pal.kill_tree(proc.pid, signal.SIGTERM, caller="t.pal", resolve=False) is True
            assert proc.wait(timeout=5) == -signal.SIGTERM
        finally:
            _reap(proc)

    def test_probe_zero_signal_group_alive_semantics(self):
        # sig=0 探活：组在→True；组不在→False（kill_process_group 探活口径平移）
        proc = _spawn_sleeper()
        try:
            assert pal.kill_tree(proc.pid, 0, caller="t.pal", resolve=False) is True
            _reap(proc)
            dead = _pid_ceiling()
            assert pal.kill_tree(dead, 0, caller="t.pal", resolve=False) is False
        finally:
            _reap(proc)


class TestBindToParent:
    def test_pdeathsig_set_in_child(self, tmp_path):
        # prctl 须在被绑定进程内执行：子进程内调 bind_to_parent 并回传结果，
        # 不污染 pytest 自身（绑定 pytest 到其父会引入跨套件生命周期风险）
        code = (
            "import sys; sys.path.insert(0, r'%s'); "
            "from core.platform import api as pal; print(pal.bind_to_parent())"
            % Path(__file__).resolve().parent.parent
        )
        cp = pal.run_detached([sys.executable, "-c", code],
                              capture_output=True, text=True, cwd=str(tmp_path))
        assert cp.stdout.strip() == "True", cp.stderr


# ── B 组进程情报 ─────────────────────────────────────────────────────

class TestCmdlineReads:
    def test_raw_and_argv_forms(self):
        proc = _spawn_sleeper()
        try:
            raw = pal.read_cmdline_raw(proc.pid)
            assert raw is not None and raw.startswith(b"sleep")
            argv = pal.cmdline_argv(proc.pid)
            assert argv[0].endswith("sleep") and "30" in argv
        finally:
            _reap(proc)

    def test_dead_pid_returns_none(self):
        dead = _pid_ceiling()
        assert pal.read_cmdline_raw(dead) is None
        assert pal.cmdline_argv(dead) is None


class TestProcStatFamily:
    def test_fields_shape(self):
        fields = pal.proc_stat_fields(os.getpid())
        assert fields is not None and len(fields) >= 20
        assert fields[0] in ("R", "S", "D", "Z", "T", "I")

    def test_start_ticks_positive_int(self):
        st = pal.proc_start_ticks(os.getpid())
        assert isinstance(st, int) and st > 0

    def test_stat_malformed_returns_none(self, tmp_path):
        # 非法 pid 形态 fail-closed 映射 None（不读取他者路径，与读不到同口径）
        assert pal.proc_stat_fields("self/thread-self") is None
        assert pal.proc_stat_fields(0) is None

    def test_alive_stat_zombie_semantics(self):
        proc = pal.spawn_detached(["sleep", "30"])
        proc.kill()
        time.sleep(0.05)
        # 未收尸 → Z 态残留：zombie_is_dead 两口径各归其位（v2 清扫口径）
        assert pal.pid_alive_stat(proc.pid, zombie_is_dead=False) is True
        assert pal.pid_alive_stat(proc.pid, zombie_is_dead=True) is False
        proc.wait(timeout=5)

    def test_alive_stat_dead_pid(self):
        assert pal.pid_alive_stat(_pid_ceiling()) is False

    def test_alive_signal_forms(self):
        assert pal.pid_alive_signal(os.getpid()) is True
        assert pal.pid_alive_signal(_pid_ceiling()) is False


class TestCwdCommMtimeProcfile:
    def test_readlink_cwd(self, tmp_path):
        proc = pal.spawn_detached(["sleep", "30"], cwd=str(tmp_path))
        try:
            assert os.path.realpath(pal.readlink_cwd(proc.pid)) == os.path.realpath(tmp_path)
        finally:
            _reap(proc)

    def test_parent_comm_shape(self):
        comm = pal.parent_comm(os.getpid())
        assert isinstance(comm, str) and comm and "\n" not in comm

    def test_proc_dir_mtime_near_now(self):
        mtime = pal.proc_dir_mtime(os.getpid())
        assert isinstance(mtime, float) and abs(time.time() - mtime) < 300

    def test_read_procfile_and_traversal_guard(self):
        assert pal.read_procfile("self/status").startswith(b"Name:")
        assert pal.read_procfile("../etc/passwd") is None
        assert pal.read_procfile("/etc/passwd") is None

    def test_invalid_pid_forms_map_to_unreadable(self):
        # fail-closed：非正数/非数字 pid 一律按「读不到」→ None（防路径分段注入）
        assert pal.read_cmdline_raw(0) is None
        assert pal.readlink_cwd(-5) is None
        assert pal.read_cmdline_raw("self/thread-self") is None


class TestProcessEnviron:
    def test_self_environ_has_path(self):
        env = pal.process_environ(os.getpid())
        assert "PATH" in env

    def test_dead_pid_empty_dict(self):
        assert pal.process_environ(_pid_ceiling()) == {}


class TestPortOwner:
    def test_find_port_owner_loopback(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.listen(1)
        try:
            owner = pal.find_port_owner(port)
            assert owner is not None
            assert owner["pid"] == os.getpid()
            assert owner["cmdline"]
            assert owner["starttime"] == pal.proc_start_ticks(os.getpid())
            inodes = pal.listen_inodes_for_port(port)
            assert inodes
            links = pal.proc_socket_links(os.getpid())
            assert links is not None
            assert set(f"socket:[{i}]" for i in inodes) & set(links)
        finally:
            s.close()

    def test_find_port_owner_wildcard(self):
        s = socket.socket()
        s.bind(("0.0.0.0", 0))
        port = s.getsockname()[1]
        s.listen(1)
        try:
            owner = pal.find_port_owner(port)
            assert owner is not None and owner["pid"] == os.getpid()
        finally:
            s.close()

    def test_no_listener_returns_none(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        assert pal.find_port_owner(port) is None
        assert pal.listen_inodes_for_port(port) == []


class TestProcessTreeCpu:
    def test_live_child_returns_float(self):
        proc = pal.spawn_detached(
            [sys.executable, "-c", "sum(i*i for i in range(2000000)); import time; time.sleep(0.3)"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            value = pal.process_tree_cpu_seconds(proc)
            assert isinstance(value, float) and value >= 0.0
        finally:
            _reap(proc)

    def test_dead_handle_returns_none(self):
        class _H:
            pid = _pid_ceiling()

        assert pal.process_tree_cpu_seconds(_H()) is None
        assert pal.process_tree_cpu_seconds(object()) is None


class TestIsAliveWithIdentity:
    def test_start_ticks_true_false_none(self, tmp_path):
        proc = pal.spawn_detached(["sleep", "30"], cwd=str(tmp_path))
        try:
            st = pal.proc_start_ticks(proc.pid)
            assert pal.is_alive_with_identity(proc.pid, {"start_ticks": st}) is True
            assert pal.is_alive_with_identity(proc.pid, {"start_ticks": st + 1}) is False
            assert pal.is_alive_with_identity(proc.pid, {"start_ticks": None}) is None
            assert pal.is_alive_with_identity(_pid_ceiling(), {"start_ticks": 1}) is None
        finally:
            _reap(proc)

    def test_cwd_anchors(self, tmp_path):
        proc = pal.spawn_detached(["sleep", "30"], cwd=str(tmp_path))
        try:
            assert pal.is_alive_with_identity(proc.pid, {"cwd_real": str(tmp_path)}) is True
            assert pal.is_alive_with_identity(proc.pid, {"cwd_real": "/nonexistent-xyz"}) is False
            assert pal.is_alive_with_identity(proc.pid, {"cwd_prefix": str(tmp_path)}) is True
            # 目录边界：同前缀更长目录名不误归属（locks worktrees-backup/ 先例）
            assert pal.is_alive_with_identity(proc.pid, {"cwd_prefix": "/usr"}) is False
        finally:
            _reap(proc)

    def test_alternatives_disjunction(self, tmp_path):
        proc = pal.spawn_detached(["sleep", "30"], cwd=str(tmp_path))
        try:
            st = pal.proc_start_ticks(proc.pid)
            identity = [{"start_ticks": st + 999}, {"cwd_prefix": str(tmp_path)}]
            assert pal.is_alive_with_identity(proc.pid, identity) is True
        finally:
            _reap(proc)

    def test_anchor_validation(self):
        with pytest.raises(ValueError):
            pal.is_alive_with_identity(os.getpid(), [])
        with pytest.raises(ValueError):
            pal.is_alive_with_identity(os.getpid(), {})
        with pytest.raises(ValueError):
            pal.is_alive_with_identity(os.getpid(), [{}])
        with pytest.raises(ValueError):
            pal.is_alive_with_identity(os.getpid(), {"bogus_anchor": 1})


# ── C 组具名形态（try_lock / exclusive_lock）─────────────────────────

class TestNamedLockForms:
    def test_try_lock_free_then_context(self, tmp_path):
        target = tmp_path / "data.json"
        lock = pal.try_lock(target)
        assert lock is not None
        with lock:
            # 锁内区间：他方 fd NB 抢锁失败
            with pytest.raises(OSError):
                fs_utils.flock_exclusive(
                    os.open(str(tmp_path / ".data.json.lock"), os.O_RDWR | os.O_CREAT),
                    nonblocking=True)
        # 退出后可再抢
        assert pal.try_lock(target) is not None

    def test_try_lock_busy_returns_none(self, tmp_path):
        target = tmp_path / "data.json"
        fd, _ = _hold_companion_lock(target)
        try:
            assert pal.try_lock(target) is None
        finally:
            os.close(fd)

    def test_exclusive_lock_timeout_busy(self, tmp_path):
        target = tmp_path / "data.json"
        fd, _ = _hold_companion_lock(target)
        try:
            start = time.monotonic()
            with pytest.raises(pal.FileLockBusy):
                pal.exclusive_lock(target, timeout_s=0.3)
            assert time.monotonic() - start >= 0.25
        finally:
            os.close(fd)

    def test_exclusive_lock_blocking_until_release(self, tmp_path):
        import threading

        target = tmp_path / "data.json"
        fd, _ = _hold_companion_lock(target)

        def release_soon():
            time.sleep(0.15)
            os.close(fd)

        t = threading.Thread(target=release_soon)
        t.start()
        try:
            with pal.exclusive_lock(target):
                pass  # 阻塞形态在持锁者释放后进入
        finally:
            t.join()

    def test_exclusive_lock_non_retryable_errno(self, tmp_path, monkeypatch):
        def _raise_enolck(fileobj, *, nonblocking=False):
            raise OSError(errno.ENOLCK, "No locks available")

        monkeypatch.setattr(pal_linux, "flock_exclusive", _raise_enolck)
        with pytest.raises(pal.FileLockUnavailable):
            pal.exclusive_lock(tmp_path / "data.json", timeout_s=5.0)


# ── D 组 systemctl 缝 ────────────────────────────────────────────────

class TestSystemctlSeam:
    def test_unavailable_raises_hosting_error(self, monkeypatch):
        monkeypatch.setattr(pal_linux, "systemctl_available", lambda: False)
        with pytest.raises(pal.SystemdHostingError, match="需要 systemd"):
            pal.run_systemctl(["is-active", "nonexistent-unit-xyz"])

    def test_exception_identity_single_source(self):
        # 门面与后端同源；core.systemd_hosting 的副本在 3.1 转发化后并入
        assert pal.SystemdHostingError is pal_linux.SystemdHostingError

    @pytest.mark.skipif(not pal.systemctl_available(), reason="无 systemd 环境")
    def test_version_roundtrip(self):
        cp = pal.run_systemctl(["--version"])
        assert cp.returncode == 0
        assert "systemd" in cp.stdout

    def test_available_reflects_which(self, monkeypatch):
        monkeypatch.setattr(pal_linux.shutil, "which", lambda name: None)
        assert pal.systemctl_available() is False


# ── E 组环境/用户/文件系统 ────────────────────────────────────────────

class TestHomeAndUser:
    def test_env_tier(self):
        assert pal.home_dir({"HOME": "/tmp/pal-home-probe"}) == "/tmp/pal-home-probe"

    def test_pwd_fallback_on_blank_home(self):
        import pwd

        assert pal.home_dir({"HOME": ""}) == pwd.getpwuid(os.getuid()).pw_dir
        assert pal.home_dir({}) == pwd.getpwuid(os.getuid()).pw_dir

    def test_default_uses_process_environ(self):
        want = os.environ.get("HOME")
        if want and want.strip():
            assert pal.home_dir() == want

    def test_current_user(self):
        import pwd

        assert pal.current_user() == pwd.getpwuid(os.getuid()).pw_name


class TestEnsureLink:
    def test_create_and_idempotent(self, tmp_path):
        src = tmp_path / "skills-src"
        src.mkdir()
        dst = tmp_path / "skills"
        assert pal.ensure_link(src, dst) is True
        assert dst.is_symlink() and os.readlink(dst) == str(src)
        assert pal.ensure_link(src, dst) is True

    def test_missing_src_skipped(self, tmp_path):
        assert pal.ensure_link(tmp_path / "no-such-src", tmp_path / "dst") is False

    def test_dangling_link_self_heal(self, tmp_path):
        src1 = tmp_path / "src1"
        src1.mkdir()
        dst = tmp_path / "link"
        assert pal.ensure_link(src1, dst) is True
        src1.rmdir()  # 源清理 → 悬空
        assert dst.is_symlink() and not dst.exists()
        src2 = tmp_path / "src2"
        src2.mkdir()
        assert pal.ensure_link(src2, dst) is True
        assert os.readlink(dst) == str(src2)

    def test_real_dir_in_place_not_rebuilt(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dst = tmp_path / "dst"
        dst.mkdir()  # 真实目录已在
        assert pal.ensure_link(src, dst) is True
        assert dst.is_dir() and not dst.is_symlink()

    def test_fsync_dir_silent(self, tmp_path):
        pal.fsync_dir(tmp_path)  # 不抛即纪律成立（个别 FS 不支持时静默）


# ── F 组测试基建锚点 ─────────────────────────────────────────────────

class TestPytestTimeoutAnchor:
    def test_linux_is_signal(self):
        assert pal.pytest_timeout_method() == "signal"
