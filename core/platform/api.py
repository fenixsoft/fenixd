"""api.py — PAL 六组接口契约与门面（platform-abstraction W3）。

本模块是平台抽象层的**契约面**：异常类型 + 六组接口的类型化签名
（``typing.Protocol`` 结构化契约，``runtime_checkable`` 供测试断言后端
形制一致），同时是业务代码的**唯一门面**——``__init__.py`` 按 sys.platform
选出的后端实现被注入本模块命名空间，业务代码一律：

    from core.platform import api as pal
    pal.spawn_detached(cmd, cwd=..., env=..., new_session=True)

六组接口（架构真相源
docs/superpowers/specs/2026-11-10-windows-native-support-pal-design.md §5）：

- A 进程生命周期：spawn_detached / run_detached / spawn_detached_async /
  terminate_graceful / kill_tree（killpg 自保护守卫内置）/ bind_to_parent
  （PR_SET_PDEATHSIG）
- B 进程情报：低位读原语（read_cmdline_raw / cmdline_argv / proc_stat_fields /
  proc_start_ticks / pid_alive_stat / pid_alive_signal / readlink_cwd /
  parent_comm / proc_dir_mtime / read_procfile / listen_inodes_for_port /
  proc_socket_links / process_tree_cpu_seconds）+ 具名高位接口
  （process_info / process_environ / find_port_owner /
  is_alive_with_identity）。探活类
  接口 fail-closed 三态：True＝锚定命中 / False＝失配（确定性否定）/
  None＝读不到、无法核实（调用方按各自保守方向处置）
- C 文件锁：flock_exclusive / flock_release 原语（自持 fd 形态出口）+
  exclusive_lock / try_lock 具名形态（锁文件布局 ``.<name>.lock`` 与
  fs_utils.with_file_lock 同源）
- D 托管：HostingProvider 六名操作面（install_unit / start / stop /
  is_running / env_file / logs_hint——Linux 后端转发 core.systemd_hosting
  既有业务实现，systemd 语义一字不动）+ run_systemctl 单缝（list argv
  不经 shell）/ systemctl_available / SystemdHostingError。unit 文本渲染
  属 systemd 语义模板（HOME 基线经 core.git_env 三级解析，非平台
  syscall），保留在 core.systemd_hosting
- E 环境/用户/文件系统：home_dir（env→pwd 两级）/ current_user /
  ensure_link（symlink 幂等补建，悬空自愈）/ fsync_dir（O_DIRECTORY 纪律）
- F 测试基建：pytest_timeout_method 平台化锚点（linux＝"signal"）

平台谓词 IS_WINDOWS 是业务代码平台分支的唯一合法替身（静态守卫禁
``sys.platform`` / ``platform.system`` / ``os.name`` 于 core/ 业务侧）。

纯 stdlib：本模块 MUST NOT import 任何 core 模块——消费方向恒为
core.* → pal，反向依赖会成环（fs_utils / state_machine / proc_utils 等
将 import pal）。
"""

import subprocess
from typing import (
    Any,
    Optional,
    Protocol,
    runtime_checkable,
)


# ── 异常类型（平台中立，Linux/win32 后端共用同一身份）─────────────────────

class FileLockBusy(Exception):
    """nonblocking 模式下限时内未抢到伴生锁（他方持锁）。

    与 FileLockUnavailable 两因可区分，供调用方分别降级留痕（对齐
    verify_scenarios._acquire_scenarios_lock 的现行两因分类口径）。原定义
    在 core.fs_utils（W1 收敛期），W3 起家于此，fs_utils 以同名字再导出
    保持既有引用身份不变。
    """


class FileLockUnavailable(Exception):
    """flock 本身不可用（特殊文件系统不支持等非 EAGAIN/EACCES errno）。"""


class SystemdHostingError(Exception):
    """systemd 承载操作失败（systemctl 不可用/无权限/unit 操作失败等）。

    携带可读中文错误信息，调用方（fenix_session/路由/hook）直接透传给用户，
    MUST NOT 静默降级为 tmux（承载层语义 BREAKING：tmux 路径已退役）。
    原定义在 core.systemd_hosting，D 组 systemctl 单缝上收后家于此，
    systemd_hosting 以同名字再导出保持既有引用身份不变。
    """


# ── A 进程生命周期 ──────────────────────────────────────────────────────

@runtime_checkable
class ProcessLifecycle(Protocol):
    """spawn / 击杀 / 父子绑定：全部经独立进程组（start_new_session）纪律。"""

    def spawn_detached(self, cmd, cwd=None, env=None, *, new_session: bool = True,
                       **popen_kwargs) -> subprocess.Popen: ...

    def run_detached(self, cmd, cwd=None, env=None, *, new_session: bool = True,
                     **run_kwargs) -> subprocess.CompletedProcess: ...

    def spawn_detached_async(self, cmd, cwd=None, env=None, *, new_session: bool = True,
                             shell: bool = False, **kwargs): ...

    def terminate_graceful(self, proc, grace_s: float = ...) -> None: ...

    def kill_tree(self, target_pid: int, sig: int, *, caller: str,
                  resolve: bool = False) -> bool: ...

    def bind_to_parent(self, sig: int = ...) -> bool: ...

    def kill_group_alive(self, pgid: int) -> Optional[bool]: ...

    def stdin_eof(self, proc) -> bool: ...

    def exit_code_signal_name(self, exit_code) -> Optional[str]: ...


# ── B 进程情报 ──────────────────────────────────────────────────────────

@runtime_checkable
class ProcessIntelligence(Protocol):
    """/proc 读面单点：低位原语 + 具名高位接口（三态 fail-closed）。"""

    def read_cmdline_raw(self, pid: int) -> Optional[bytes]: ...

    def cmdline_argv(self, pid: int) -> Optional[list]: ...

    def proc_stat_fields(self, pid: int) -> Optional[list]: ...

    def proc_start_ticks(self, pid: int) -> Optional[int]: ...

    def pid_alive_stat(self, pid: int, zombie_is_dead: bool = False) -> bool: ...

    def pid_alive_signal(self, pid: int) -> bool: ...

    def readlink_cwd(self, pid: int) -> Optional[str]: ...

    def parent_comm(self, pid: int) -> Optional[str]: ...

    def proc_dir_mtime(self, pid: int) -> Optional[float]: ...

    def read_procfile(self, relpath: str) -> Optional[bytes]: ...

    def proc_pids(self) -> list: ...

    def process_info(self, pid: int) -> Optional[dict]: ...

    def process_environ(self, pid: int) -> dict: ...

    def find_port_owner(self, port: int) -> Optional[dict]: ...

    def listen_inodes_for_port(self, port: int) -> list: ...

    def proc_socket_links(self, pid: int) -> Optional[list]: ...

    def process_tree_cpu_seconds(self, proc: Any) -> Optional[float]: ...

    def is_alive_with_identity(self, pid: int, identity: Any) -> Optional[bool]: ...

    def orphaned_process(self) -> bool: ...


# ── C 文件锁 ────────────────────────────────────────────────────────────

@runtime_checkable
class FileLocking(Protocol):
    """flock 单源：原语（自持 fd）+ 具名形态（锁文件布局 ``.<name>.lock``）。"""

    def flock_exclusive(self, fileobj, *, nonblocking: bool = False) -> None: ...

    def flock_release(self, fileobj) -> None: ...

    def exclusive_lock(self, path, timeout_s: Optional[float] = None): ...

    def try_lock(self, path): ...


# ── D 托管（HostingProvider 的 systemctl 缝）────────────────────────────

@runtime_checkable
class HostingSeam(Protocol):
    """systemd 承载的平台缝：systemctl 子进程单缝与可用性探测。

    SPEC-2 的 Windows 承载后端（计划任务等）实现同一缝位。unit 文本渲染
    （systemd 指令模板）属承载语义而非平台 syscall，保留在
    core.systemd_hosting。
    """

    def systemctl_available(self) -> bool: ...

    def run_systemctl(self, args, timeout: float = 30,
                      available: Optional[bool] = None) -> subprocess.CompletedProcess: ...


@runtime_checkable
class HostingProvider(Protocol):
    """托管承载操作面（SPEC 钉死六名，全部以项目根为键的统一家族）。

    与 HostingSeam（systemctl 子进程缝）分层：本协议是承载生命周期操作
    面，Linux 后端逐条转发 core.systemd_hosting 既有实现（unit 渲染与
    HOME/PATH 基线属承载业务语义留彼处，转发经函数内延迟 import，
    见 linux.py 对照表 D 组注记）；SPEC-2 Windows 后端同缝换计划任务/
    服务后端（journalctl 文案换事件日志形态）。
    """

    def install_unit(self, root) -> dict: ...

    def start(self, root) -> None: ...

    def stop(self, root) -> None: ...

    def is_running(self, root) -> bool: ...

    def env_file(self, root): ...

    def logs_hint(self, root) -> str: ...


# ── E 环境/用户/文件系统 ────────────────────────────────────────────────

@runtime_checkable
class EnvironmentUserFs(Protocol):
    """HOME/用户解析、symlink 幂等补建、目录 fsync 纪律的平台缝。"""

    def home_dir(self, env: Optional[dict] = None) -> Optional[str]: ...

    def current_user(self) -> Optional[str]: ...

    def ensure_link(self, src, dst) -> bool: ...

    def fsync_dir(self, path) -> None: ...

    def atomic_replace(self, src, dst) -> None: ...


# ── F 测试基建锚点 ──────────────────────────────────────────────────────

@runtime_checkable
class TestInfra(Protocol):
    """测试基建的平台化锚点（pytest 超时机制等在 win32 后端须换线程形态）。"""

    def pytest_timeout_method(self) -> str: ...


__all__ = [
    "FileLockBusy",
    "FileLockUnavailable",
    "SystemdHostingError",
    "ProcessLifecycle",
    "ProcessIntelligence",
    "FileLocking",
    "HostingSeam",
    "HostingProvider",
    "EnvironmentUserFs",
    "TestInfra",
]
