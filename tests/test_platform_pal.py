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
