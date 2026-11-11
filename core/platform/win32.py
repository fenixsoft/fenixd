"""win32.py — PAL Windows 后端占位（SPEC-2 范围，本 SPEC 仅落 Linux）。

add-platform-abstraction-layer（SPEC-1）交付 Linux 后端并把既有平台敏感
实现收敛为 pal 单源；Windows 原生支持（windows-native-support，SPEC-2）
在此文件落第二个后端。占位接口与 linux.py 同名同签名（六组契约面一致），
调用即抛 ``NotImplementedError``——分发的可达性由 ``__init__.py`` 的
sys.platform 单点分支保证（非 Windows 环境本模块不被导入）。

实现指引（SPEC-2 起点清单，对应架构真相源 §5）：

- A 组：``spawn_detached`` 换 ``CREATE_NEW_PROCESS_GROUP | CREATE_NEW_CONSOLE``
  形态、``kill_tree`` 换 taskkill /T 树杀、``bind_to_parent`` 无 PDEATHSIG
  等价物（Job Object 方案）；
- B 组：/proc 读面换 Windows API（psutil 或 Win32 Toolhelp 快照），
  ``is_alive_with_identity`` 锚键换 CreationTime（等价 starttime）；
- C 组：flock 换 ``msvcrt.locking``（语义差异须在 exclusive_lock 层吸收）；
- D 组：systemctl 缝换计划任务（schtasks）或服务后端，HostingProvider
  六名（install_unit/start/stop/is_running/env_file/logs_hint）同缝；
  ``run_systemctl`` 带 keyword-only ``available``（调用方已判可用性直传，
  None＝本缝自行探测，见 HostingSeam 协议与 systemd_hosting 转发形态）；
- E 组：``home_dir`` 换 ``USERPROFILE``、``ensure_link`` 换
  ``os.symlink``（需开发者模式或特权）；
- F 组：``pytest_timeout_method`` 恒 ``"thread"``（Windows 无 SIGALRM）。
"""

import signal
import subprocess
from typing import Optional

from core.platform.api import (
    FileLockBusy,
    FileLockUnavailable,
    SystemdHostingError,
)

# 平台谓词（业务代码平台分支的唯一合法替身）
IS_WINDOWS = True

TERM_GRACE_SECONDS = 5

# procfs 挂载根占位（Windows 无 procfs；SPEC-2 按实际进程情报后端另定）
PROCFS_ROOT = None


def _spec2(name: str) -> NotImplementedError:
    return NotImplementedError(
        f"core.platform.{name}：win32 后端为 SPEC-2（windows-native-support）"
        "范围，当前交付（add-platform-abstraction-layer）仅落 Linux 后端"
    )


# ── A 进程生命周期 ──────────────────────────────────────────────────────

def spawn_detached(cmd, cwd=None, env=None, *, new_session: bool = True,
                   **popen_kwargs) -> subprocess.Popen:
    raise _spec2("win32.spawn_detached")


def run_detached(cmd, cwd=None, env=None, *, new_session: bool = True,
                 **run_kwargs) -> subprocess.CompletedProcess:
    raise _spec2("win32.run_detached")


async def spawn_detached_async(cmd, cwd=None, env=None, *, new_session: bool = True,
                               shell: bool = False, **kwargs):
    raise _spec2("win32.spawn_detached_async")


def terminate_graceful(proc, grace_s: float = TERM_GRACE_SECONDS) -> None:
    raise _spec2("win32.terminate_graceful")


def kill_tree(target_pid: int, sig: int, *, caller: str,
              resolve: bool = False) -> bool:
    raise _spec2("win32.kill_tree")


def bind_to_parent(sig: int = signal.SIGTERM) -> bool:
    raise _spec2("win32.bind_to_parent")


def kill_group_alive(pgid: int) -> Optional[bool]:
    raise _spec2("win32.kill_group_alive")


# ── B 进程情报 ──────────────────────────────────────────────────────────

def read_cmdline_raw(pid: int) -> Optional[bytes]:
    raise _spec2("win32.read_cmdline_raw")


def cmdline_argv(pid: int) -> Optional[list]:
    raise _spec2("win32.cmdline_argv")


def proc_stat_fields(pid: int) -> Optional[list]:
    raise _spec2("win32.proc_stat_fields")


def proc_start_ticks(pid: int) -> Optional[int]:
    raise _spec2("win32.proc_start_ticks")


def pid_alive_stat(pid: int, zombie_is_dead: bool = False) -> bool:
    raise _spec2("win32.pid_alive_stat")


def pid_alive_signal(pid: int) -> bool:
    raise _spec2("win32.pid_alive_signal")


def readlink_cwd(pid: int) -> Optional[str]:
    raise _spec2("win32.readlink_cwd")


def parent_comm(pid: int) -> Optional[str]:
    raise _spec2("win32.parent_comm")


def proc_dir_mtime(pid: int) -> Optional[float]:
    raise _spec2("win32.proc_dir_mtime")


def read_procfile(relpath: str) -> Optional[bytes]:
    raise _spec2("win32.read_procfile")


def proc_pids() -> list:
    raise _spec2("win32.proc_pids")


def process_environ(pid: int) -> dict:
    raise _spec2("win32.process_environ")


def find_port_owner(port: int) -> Optional[dict]:
    raise _spec2("win32.find_port_owner")


def listen_inodes_for_port(port: int) -> list:
    raise _spec2("win32.listen_inodes_for_port")


def proc_socket_links(pid: int) -> Optional[list]:
    raise _spec2("win32.proc_socket_links")


def process_tree_cpu_seconds(proc) -> Optional[float]:
    raise _spec2("win32.process_tree_cpu_seconds")


def is_alive_with_identity(pid: int, identity) -> Optional[bool]:
    raise _spec2("win32.is_alive_with_identity")


def process_info(pid: int) -> Optional[dict]:
    raise _spec2("win32.process_info")


# ── C 文件锁 ────────────────────────────────────────────────────────────

def flock_exclusive(fileobj, *, nonblocking: bool = False) -> None:
    raise _spec2("win32.flock_exclusive")


def flock_release(fileobj) -> None:
    raise _spec2("win32.flock_release")


def try_lock(path):
    raise _spec2("win32.try_lock")


def exclusive_lock(path, timeout_s: Optional[float] = None):
    raise _spec2("win32.exclusive_lock")


# ── D 托管 ──────────────────────────────────────────────────────────────

def systemctl_available() -> bool:
    return False  # 非 systemd 环境：与 linux 后端在无 systemd 主机同语义


def run_systemctl(args, timeout: float = 30, *,
                  available: Optional[bool] = None) -> subprocess.CompletedProcess:
    raise _spec2("win32.run_systemctl")


# HostingProvider 六名（SPEC 钉死托管操作面；SPEC-2 换计划任务/服务后端，
# journalctl 文案换事件日志形态）

def install_unit(root) -> dict:
    raise _spec2("win32.install_unit")


def start(root) -> None:
    raise _spec2("win32.start")


def stop(root) -> None:
    raise _spec2("win32.stop")


def is_running(root) -> bool:
    raise _spec2("win32.is_running")


def env_file(root):
    raise _spec2("win32.env_file")


def logs_hint(root) -> str:
    raise _spec2("win32.logs_hint")


# ── E 环境/用户/文件系统 ────────────────────────────────────────────────

def home_dir(env: Optional[dict] = None) -> Optional[str]:
    raise _spec2("win32.home_dir")


def current_user() -> Optional[str]:
    raise _spec2("win32.current_user")


def ensure_link(src, dst) -> bool:
    raise _spec2("win32.ensure_link")


def fsync_dir(path) -> None:
    raise _spec2("win32.fsync_dir")


# ── F 测试基建 ──────────────────────────────────────────────────────────

def pytest_timeout_method() -> str:
    # Windows 无 SIGALRM：线程形态（SPEC-2 落地时与 pytest.ini 平台拆分联动）
    return "thread"


__all__ = [
    "IS_WINDOWS",
    "TERM_GRACE_SECONDS",
    "PROCFS_ROOT",
    "FileLockBusy",
    "FileLockUnavailable",
    "SystemdHostingError",
    "spawn_detached",
    "run_detached",
    "spawn_detached_async",
    "terminate_graceful",
    "kill_tree",
    "bind_to_parent",
    "kill_group_alive",
    "read_cmdline_raw",
    "cmdline_argv",
    "proc_stat_fields",
    "proc_start_ticks",
    "pid_alive_stat",
    "pid_alive_signal",
    "readlink_cwd",
    "parent_comm",
    "proc_dir_mtime",
    "read_procfile",
    "proc_pids",
    "process_environ",
    "find_port_owner",
    "listen_inodes_for_port",
    "proc_socket_links",
    "process_tree_cpu_seconds",
    "is_alive_with_identity",
    "process_info",
    "flock_exclusive",
    "flock_release",
    "try_lock",
    "exclusive_lock",
    "systemctl_available",
    "run_systemctl",
    "install_unit",
    "start",
    "stop",
    "is_running",
    "env_file",
    "logs_hint",
    "home_dir",
    "current_user",
    "ensure_link",
    "fsync_dir",
    "pytest_timeout_method",
]
