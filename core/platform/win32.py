"""win32.py — PAL Windows 后端（windows-native-support W8 全后端）。

本模块是 ``core/platform/`` 六组接口的 Windows 实现（SPEC-2 主体交付）。
与 ``linux.py`` 同名同签名同 ``__all__``：``__init__.py`` 按 ``sys.platform``
分发（win32 → 本模块），全部实现注入 ``core.platform.api`` 门面命名空间。

模块级导入面为 platform-neutral stdlib（与 linux.py 同纪律：MUST NOT
import 任何 core 模块；唯一例外 D 组 HostingProvider 门面在**函数体内**
延迟 import core.systemd_hosting 复用 unit 名与 env 文件单源）。全部
Windows 专属依赖（msvcrt / psutil / pywin32 形态的 ctypes API）均在
**函数体内**懒加载——本模块在 Linux 上可安全 import（tests/test_platform_pal.py
的 win32 契约测试以 mock 面在 Linux 运行，7.1）。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
平台语义总表（W8 对照 linux.py 逐组落位；显式差异 MUST 文档化不静默降级）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

A 进程生命周期
- spawn_detached / run_detached / spawn_detached_async
  ≙ ``CREATE_NEW_PROCESS_GROUP``（**不带** CREATE_NEW_CONSOLE——
  GenerateConsoleCtrlEvent 只能投递给与调用者同控制台的组，加
  CREATE_NEW_CONSOLE 会令 CTRL_BREAK 不可达）+ spawn 后建 Job Object
  （KILL_ON_JOB_CLOSE）assign 子进程：daemon 死亡 → 句柄表销毁 → job 关
  → 整树自杀（＝PDEATHSIG 泄漏即死的 spawn 侧等价物）。
- terminate_graceful：stdin-close（EOF 优雅层，claude/dsh CLI 以 stdin
  transport 收 prompt）→ CTRL_BREAK（有共享控制台时）→ wait(grace) →
  TerminateProcess 补刀。stdin-close 在 one_shot 车道天然先到
  （communicate 写完载荷即关闭），对残余 open 管道兜底。
- kill_tree：守卫语义与 linux 同构（拒自身/祖先链，WARNING 文案平台化）；
  SIGTERM → CTRL_BREAK（可达时）/ TerminateProcess（无控制台退化，显式
  文档化）；SIGKILL → Job Object 主（TerminateJobObject 整树）+ Toolhelp
  快照树杀兜底（弃 taskkill /T——评估实测 leader 已退出时静默漏杀
  rc=128）；SIGKILL 对已亡目标 ESRCH 静默语义逐位对齐。
- bind_to_parent ≙ PR_SET_PDEATHSIG：自建 KILL_ON_JOB_CLOSE job assign
  自身后把句柄 DuplicateHandle 进父进程并关闭自身副本——父死句柄表销毁
  → job 关 → 自杀。父已亡 / 打开父失败 → False（策略留消费端）。
- kill_group_alive：psutil 三态（True 存活 / False 已亡 / psutil 缺失
  None 无法核实）；Windows ``os.kill(pid, 0)`` 是 TerminateProcess
  （会杀进程！）——探活 MUST 走 psutil.pid_exists，本组绝不用 os.kill。

B 进程情报
- 全 psutil 7.x；``start_token`` = int(create_time() * 1000)（毫秒，
  pal 自产自销锚——跨后端不可比，SPEC 钉死换 CreationTime 同缝）。
- ``pid_alive_signal`` 与 ``pid_alive_stat`` 同走 psutil（前述
  os.kill(pid,0) 陷阱）；EPERM 形态（他主进程）psutil 侧 AccessDenied
  亦按存活——与 linux「EPERM=存活」保守方向同构。
- procfs 形态接口（proc_stat_fields / read_procfile / proc_socket_links）
  Windows 无 procfs → None（「无法核实」契约方向）；PROCFS_ROOT=None。
  ``pid_alive_stat`` 等具名接口不叠在 proc_stat_fields 上（避免
  fail-closed 翻转成全表误判死），全部原生 psutil 实现。
- listen_inodes_for_port → []（socket inode 概念 Windows 不存在；
  身份收口消费面「无监听」降级方向已文档化）。
- find_port_owner：psutil.net_connections（LISTEN + laddr.port 匹配）；
  无管理员权限时他人条目 pid=None → 视「无法判定」返回 None 并 stderr
  留痕（与 linux「探测异常≠无占用者」留痕语义同构）。
- exit_code_signal_name：退出码 → 信号死法标记名。Windows 退出码语义
  ≠ POSIX 信号（无 SIGTERM/SIGKILL 投递语义），闭集收编两类实证形态：
  0xC000013A STATUS_CONTROL_C_EXIT（控制台事件死法：CTRL_BREAK 默认处置
  /CTRL_CLOSE 关窗）→ "CTRL_BREAK"；0xFFFFFFFF（taskkill /F、
  Stop-Process 等 TerminateProcess 默认退出码）→ "SIGKILL"。其余退出码
  （含 143/128+N 数字形态——Windows 上是程序自选退出码，不构成信号死法
  证据）返回 None。

C 文件锁
- msvcrt.locking 1 字节纪律（offset 0，lock/unlock 前显式 lseek——
  locking 从**当前位置**起算的经典陷阱）；LK_NBLCK 单次 + blocking 形态
  以 50ms 步长无限重试表达。锁被占类 errno（EACCES/EAGAIN/EDEADLOCK）
  走 with_file_lock 既有两因分类；Windows LockFileEx 是强制锁
  （linux flock 建议锁）——伴生 ``.<name>.lock`` 布局与 1 字节纪律即
  为此设（design R3），跨平台语义一致。

D 托管：NSSM 服务后端（备选 WinSW；systemd 语义逐条映射，显式差异不静默）
- Restart=on-failure      → NSSM 缺省崩溃重启（AppExit=Default）；
- StartLimit/Burst 限频   → 无等价（NSSM 无 burst 限频）——显式差异；
- TimeoutStopSec=2100     → 无等价（NSSM 各停机方法缺省 1500ms）——显式差异；
- SuccessExitStatus=75    → 无等价（supervisor 退出码协议语义差异）——显式差异；
- EnvironmentFile 0600    → env 文件布局复用 project_env_file 单源
                            （<root>/.fenix/ 同位）；服务侧消费经 NSSM
                            AppEnvironmentExtra 由安装时逐行注入——差异；
- KillMode=mixed          → NSSM 停机树杀 ≈ 等价；
- journalctl              → AppStdout/AppStderr 文件日志（logs_hint 指向）。
- unit 名/路径单源：服务名 = systemd_hosting.unit_name_for(root) 去掉
  ``.service`` 后缀；supervisor 脚本路径同源
  ``<root>/.fenix/bin/fenixd_supervisor.py --project-root <root>``。
- systemctl 缝：systemctl_available() 恒 False；run_systemctl 抛
  SystemdHostingError（Windows 承载经 NSSM 指引文案）。

E 环境/用户/文件系统
- home_dir：env ``HOME``（unix-y 工具在 Windows 常设）→ ``USERPROFILE``
  → ``HOMEDRIVE+HOMEPATH`` → None。
- ensure_link：symlink（Developer Mode / SeCreateSymbolicLink 权限）→
  junction（``_winapi.CreateJunction``，目录等价、无特权要求）→ copy
  （``shutil.copytree`` 降级——**内容在位但非链接**，身份语义差异显式
  文档化，copy 失败 OSError 上抛）。幂等/悬空自愈纪律与 linux 同构。
- fsync_dir：``FlushFileBuffers``（FILE_FLAG_BACKUP_SEMANTICS 打开目录
  句柄）；尽力而为失败静默（linux 同契约）。
- atomic_replace：``os.replace`` 短重试（Windows 文件占用抖动——AV 扫描
  /并发读者短暂持有目标句柄时 replace 抛 PermissionError，按 20ms×5
  限时重试后原样上抛）；Linux 后端为 os.replace 直通。

F 测试基建
- pytest_timeout_method 恒 ``"thread"``（Windows 无 SIGALRM；pytest.ini
  timeout_method 平台拆分以此为准）。

信号常量面：Windows 无 ``signal.SIGKILL``（AttributeError）——本模块
导出 ``SIGTERM``/``SIGINT``（取 signal 模块）与 ``SIGKILL=9``（pal 逻辑
常量，kill_tree 分支用），业务侧经 pal 常量消费保证 Windows 可导入。
"""

import asyncio
import ctypes
import errno
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import List, Optional

from core.platform.api import (
    FileLockBusy,
    FileLockUnavailable,
    SystemdHostingError,
)

_logger = logging.getLogger("fenixd.platform.win32")

# 平台谓词（业务代码平台分支的唯一合法替身）
IS_WINDOWS = True


# 信号常量（pal 导出面；Windows 无 signal.SIGKILL，见模块 docstring）
SIGTERM = signal.SIGTERM
SIGINT = signal.SIGINT
SIGKILL = 9


# ═══════════════════════════════════════════════════════════════════════
# Win32 常量与 ctypes 结构（纯数据定义，Linux 上导入安全）
# ═══════════════════════════════════════════════════════════════════════

CREATE_NEW_PROCESS_GROUP = 0x00000200  # winbase.h（不带 CREATE_NEW_CONSOLE，见 docstring）
CTRL_BREAK_EVENT = 1  # GenerateConsoleCtrlEvent 的 dwCtrlEvent
JOB_OBJECT_EXTENDED_LIMIT = 9  # JOBOBJECTINFOCLASS JobObjectExtendedLimitInformation
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
TH32CS_SNAPPROCESS = 0x00000002
PROCESS_TERMINATE = 0x0001
PROCESS_DUP_HANDLE = 0x0040
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
DUPLICATE_SAME_ACCESS = 0x0002
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
STATUS_CONTROL_C_EXIT = 0xC000013A  # 控制台事件死法退出码（CTRL_BREAK/CTRL_CLOSE）
TERMINATE_EXIT_CODE_EXTERNAL = 0xFFFFFFFF  # taskkill /F、Stop-Process 等默认退出码

_INVALID_HANDLE = -1  # INVALID_HANDLE_VALUE（c_void_p 口径下为 2**64-1）


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
    )]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_uint32),
        ("cntUsage", ctypes.c_uint32),
        ("th32ProcessID", ctypes.c_uint32),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", ctypes.c_uint32),
        ("cntThreads", ctypes.c_uint32),
        ("th32ParentProcessID", ctypes.c_uint32),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.c_uint32),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


_K32 = None


def _configure_k32_prototypes(k32) -> None:
    """kernel32 句柄与指针参数原型声明（64 位 HANDLE 必须显式声明）。

    默认 ctypes 行为把返回值/参数按 ``c_int``（32 位）转换：
    ``GetCurrentProcess()`` 返回的伪句柄 ``-1`` 会被截成
    ``0x00000000FFFFFFFF``，``AssignProcessToJobObject`` 因此判
    ``ERROR_INVALID_HANDLE(6)``——dockur 过机（G1-24）实测捕到的真实缺陷；
    同一问题也会让大于 2**31 的真实句柄被截断。故本模块用到的每个
    kernel32 入口在此一次性声明 restype/argtypes（c_void_p 承载 HANDLE）。
    """
    from ctypes import wintypes

    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.GetCurrentProcess.argtypes = []

    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]

    k32.SetInformationJobObject.restype = wintypes.BOOL
    k32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
    ]

    k32.AssignProcessToJobObject.restype = wintypes.BOOL
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]

    k32.TerminateJobObject.restype = wintypes.BOOL
    k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]

    k32.DuplicateHandle.restype = wintypes.BOOL
    k32.DuplicateHandle.argtypes = [
        wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE,
        ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD, wintypes.BOOL,
        wintypes.DWORD,
    ]

    k32.CloseHandle.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [wintypes.HANDLE]

    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]

    k32.TerminateProcess.restype = wintypes.BOOL
    k32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]

    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]

    k32.Process32FirstW.restype = wintypes.BOOL
    k32.Process32FirstW.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W),
    ]

    k32.Process32NextW.restype = wintypes.BOOL
    k32.Process32NextW.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W),
    ]

    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]

    k32.FlushFileBuffers.restype = wintypes.BOOL
    k32.FlushFileBuffers.argtypes = [wintypes.HANDLE]


def _k32():
    """kernel32延迟绑定（ctypes.WinDLL 仅 Windows 存在，函数体内取）。"""
    global _K32
    if _K32 is None:
        _K32 = ctypes.WinDLL("kernel32", use_last_error=True)  # noqa: 平台专属惰性
        _configure_k32_prototypes(_K32)
    return _K32


def _handle_valid(h) -> bool:
    """句柄有效性判定：NULL 与 INVALID_HANDLE_VALUE 均无效。

    ctypes 声明 restype=HANDLE（c_void_p）后调用方拿到的是 c_void_p 对象，
    与 int ``-1`` 直接比较恒不等；此处归一 .value 后按无符号
    ``2**64-1`` 判定，兼容 c_void_p / int 双形态（原型声明前的调用方）。
    """
    if isinstance(h, ctypes.c_void_p):
        h = h.value
    if not h:
        return False
    return h not in (-1, 0xFFFFFFFFFFFFFFFF)


# spawn 时登记的 Job Object 句柄（pid → job handle）：kill_tree 的 SIGKILL
# 主路径（TerminateJobObject 整树）与收尾清理的依据。进程死亡后条目由
# 击杀/收尾路径摘除；daemon 自身死亡时句柄表销毁 → KILL_ON_JOB_CLOSE 兜底
# 整树自杀，注册表残留无泄漏面。
_JOB_REGISTRY = {}
_JOB_LOCK = threading.Lock()


def _registry_put(pid: int, job_handle) -> None:
    with _JOB_LOCK:
        _JOB_REGISTRY[int(pid)] = job_handle


def _registry_pop(pid: int):
    with _JOB_LOCK:
        return _JOB_REGISTRY.pop(int(pid), None)


def _registry_get(pid: int):
    with _JOB_LOCK:
        return _JOB_REGISTRY.get(int(pid))


def _make_kill_on_close_job():
    """创建 KILL_ON_JOB_CLOSE 空.job（句柄无效返回 None——尽力而为基座）。"""
    k32 = _k32()
    job = k32.CreateJobObjectW(None, None)
    if not _handle_valid(job):
        return None
    info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not k32.SetInformationJobObject(
        job, JOB_OBJECT_EXTENDED_LIMIT,
        ctypes.byref(info), ctypes.sizeof(info),
    ):
        k32.CloseHandle(job)
        return None
    return job


def _attach_job(popen) -> None:
    """spawn 后把子进程 assign 进新 KILL_ON_JOB_CLOSE job（尽力而为）。

    成功：daemon 死亡（句柄表销毁）→ job 关 → 子树自杀；kill_tree 的
    SIGKILL 主路径拿注册表句柄 TerminateJobObject 整树杀。失败（Win8 前
    嵌套 job 限制等）：记 WARNING 不阻断 spawn——Tree 杀仍有 Toolhelp
    兜底路径。
    """
    try:
        job = _make_kill_on_close_job()
        if job is None:
            _logger.warning(
                "spawn job attach: CreateJobObject/SetInformation 失败 "
                "(winerror=%d) — daemon 退出不联动子树（Toolhelp 兜底仍在）",
                ctypes.get_last_error(),
            )
            return
        if not _k32().AssignProcessToJobObject(job, int(popen.handle)):
            _logger.warning(
                "spawn job attach: AssignProcessToJobObject(pid=%d) 失败 "
                "(winerror=%d) — 子进程可能已嵌套于其他 job",
                popen.pid, ctypes.get_last_error(),
            )
            _k32().CloseHandle(job)
            return
        _registry_put(popen.pid, job)
    except Exception as e:  # noqa: BLE001 — attach 尽力而为，失败不阻断 spawn
        _logger.warning("spawn job attach 异常（忽略，Toolhelp 兜底仍在）: %s", e)


def _terminate_job_tree(pid: int) -> bool:
    """注册表有该 pid 的 job 句柄 → TerminateJobObject 整树杀并清理。"""
    job = _registry_get(pid)
    if job is None:
        return False
    try:
        _k32().TerminateJobObject(job, SIGKILL)
    finally:
        _k32().CloseHandle(job)
        _registry_pop(pid)
    return True


def _pid_alive(pid: int) -> bool:
    """psutil.pid_exists 探活（os.kill(pid,0) 在 Windows 是 TerminateProcess，
    本模块进程探活绝不用 os.kill）。psutil 缺失 → False（按不可核实弱化，
    击杀路径多打一发无害；三态语义接口 kill_group_alive 单独处理 None）。"""
    try:
        import psutil
    except ImportError:
        return False
    try:
        return psutil.pid_exists(int(pid))
    except (OSError, ValueError):
        return False


def _descendant_pids(root_pid: int) -> List[int]:
    """Toolhelp 快照遍历 root_pid 的全部后代 pid（直接+间接）。

    kill_tree 的 SIGKILL 兜底路径（Job Object 未登记时）：快照一次
    {pid: ppid}，BFS 收集后代（不保证拓扑序——TerminateProcess 相互独立，
    顺序无语义）。快照失败返回空表（调用方仍直接杀 root 本体）。
    """
    k32 = _k32()
    snapshot = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not _handle_valid(snapshot):
        return []
    edges = {}
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        ok = k32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            edges[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            ok = k32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snapshot)
    children = {}
    for pid, ppid in edges.items():
        children.setdefault(ppid, []).append(pid)
    out: List[int] = []
    queue = [int(root_pid)]
    while queue:
        cur = queue.pop()
        for child in children.get(cur, ()):
            if child != int(root_pid) and child not in out:
                out.append(child)
                queue.append(child)
    return out


def _is_self_or_ancestor(pid: int) -> bool:
    """目标是否调用者自身或自身祖先（击杀守卫；ppid 链上溯，深度上限防环）。

    psutil 缺失时 ppid 链断裂仅能判「自身命中」——祖先链不可上溯按不命中
    放行（Windows 上击杀自身祖先的替身怪值形态由 _pid_alive 探活与调用方
    装载纪律共同兜底；linux 侧同名守卫语义见 linux.kill_tree docstring）。
    """
    pid = int(pid)
    if pid == os.getpid():
        return True
    cur = os.getppid()
    for _ in range(64):  # 深度上限：链环/孤儿收养异常形态防御
        if not cur or cur <= 0:
            return False
        if cur == pid:
            return True
        try:
            import psutil
            cur = psutil.Process(cur).ppid()
        except Exception:  # noqa: BLE001 — 链断（psutil 缺失/进程亡）按不命中
            return False
    return False


def _open_process(pid: int, access: int):
    return _k32().OpenProcess(access, False, int(pid))


# ═══════════════════════════════════════════════════════════════════════
# A 进程生命周期
# ═══════════════════════════════════════════════════════════════════════

# kill_tree 序列的 SIGTERM 优雅退出宽限参照值（与 linux.TERM_GRACE_SECONDS
# 同值同语义：进程组/整树清扫时序常量，取值由守卫测试钉住）
TERM_GRACE_SECONDS = 5


def spawn_detached(cmd, cwd=None, env=None, *, new_session: bool = True,
                   **popen_kwargs) -> subprocess.Popen:
    """Popen 独立进程组形态：CREATE_NEW_PROCESS_GROUP + Job Object attach。

    ``new_session=True`` ≙ linux 的 start_new_session=True（独立控制台
    进程组，CTRL_BREAK 可按组投递 + spawn 后建 KILL_ON_JOB_CLOSE job）；
    ``new_session=False`` 为动态 passthrough（无组、无 job——信号直达直接
    子进程的既有语义）。``creation_flags`` 既有 kwargs 值按位并入不覆盖。
    不加 CREATE_NEW_CONSOLE：目标组须与调用者同控制台 CTRL_BREAK 才可达。
    """
    flags = int(popen_kwargs.pop("creation_flags", 0) or 0)
    if new_session:
        flags |= CREATE_NEW_PROCESS_GROUP
    popen = subprocess.Popen(cmd, cwd=cwd, env=env, creation_flags=flags,
                             **popen_kwargs)
    if new_session:
        _attach_job(popen)
    return popen


def run_detached(cmd, cwd=None, env=None, *, new_session: bool = True,
                 **run_kwargs) -> subprocess.CompletedProcess:
    """subprocess.run 独立进程组形态（run ≡ spawn + communicate + wait）。

    creation_flags 形态与 spawn_detached 同构；run 形态生命周期与调用方
    同步（等待返回），不做 Job Object attach（无孤儿泄漏面）。
    """
    flags = int(run_kwargs.pop("creation_flags", 0) or 0)
    if new_session:
        flags |= CREATE_NEW_PROCESS_GROUP
    return subprocess.run(cmd, cwd=cwd, env=env, creation_flags=flags,
                          **run_kwargs)


async def spawn_detached_async(cmd, cwd=None, env=None, *, new_session: bool = True,
                               shell: bool = False, **kwargs):
    """asyncio 子进程独立进程组形态（creation_flags 同步并入）。

    Windows 缺省事件循环为 Proactor（Python 3.8+），支持子进程；调用方
    显式 SelectorEventLoop 下 create_subprocess_* 会 RuntimeError 上抛
    （属调用方装配错误，不在本层吞）。asyncio.Process 无稳定句柄缝，
    不做 Job Object attach（整树兜底走 Toolhelp）。
    """
    flags = int(kwargs.pop("creation_flags", 0) or 0)
    if new_session:
        flags |= CREATE_NEW_PROCESS_GROUP
    kwargs["creation_flags"] = flags
    if shell:
        if not isinstance(cmd, str):
            cmd = cmd[0]
        return await asyncio.create_subprocess_shell(
            cmd, cwd=cwd, env=env, **kwargs)
    return await asyncio.create_subprocess_exec(
        *cmd, cwd=cwd, env=env, **kwargs)


def stdin_eof(proc) -> bool:
    """分层终止第一跳：关闭 stdin 管道投递 EOF（claude/dsh CLI 优雅层）。

    True＝管道在且本次关闭；False＝无管道/已关闭。one_shot 车道
    communicate 写完载荷即关闭（本接口对已关闭管道幂等返回 False），
    本兜底覆盖长持 stdin 的会话形态与残余管道。
    """
    stdin = getattr(proc, "stdin", None)
    if stdin is None or stdin.closed:
        return False
    try:
        stdin.close()
        return True
    except OSError:
        return False


def terminate_graceful(proc, grace_s: float = TERM_GRACE_SECONDS) -> None:
    """分层优雅终止：stdin-close → CTRL_BREAK → wait(grace) → TerminateProcess。

    分层顺序即 SPEC 钉死协议（stdin EOF 对 stdin-transport CLI 是无损
    优雅层；CTRL_BREAK 仅同控制台可达，失败静默落到补刀）。补刀后注册
    表残留的 job 句柄关闭（子树随 KILL_ON_JOB_CLOSE 收口）。收尾
    （communicate 排空等）差异化留调用方。
    """
    stdin_eof(proc)
    try:
        # CTRL_BREAK 按组投递（spawn 时 CREATE_NEW_PROCESS_GROUP 的组 id =
        # 子进程 pid）；无共享控制台（NSSM 服务等）时调用失败静默降级。
        _k32().GenerateConsoleCtrlEvent(CTRL_BREAK_EVENT, proc.pid)
    except Exception:  # noqa: BLE001 — 无控制台/句柄失效：优雅层静默缺席
        pass
    try:
        proc.wait(timeout=grace_s)
        _terminate_job_tree(proc.pid)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        proc.kill()  # TerminateProcess 直接子进程
    except OSError:
        pass
    if not _terminate_job_tree(proc.pid):
        # job 未登记（attach 失败形态）：Toolhelp 兜底整树
        for pid in _descendant_pids(proc.pid):
            _hard_kill_pid(pid)


def _hard_kill_pid(pid: int) -> bool:
    """TerminateProcess 单进程硬杀（exit code = SIGKILL 语义值 9）。"""
    try:
        h = _open_process(pid, PROCESS_TERMINATE)
        if not _handle_valid(h):
            return False
        try:
            return bool(_k32().TerminateProcess(h, SIGKILL))
        finally:
            _k32().CloseHandle(h)
    except Exception:  # noqa: BLE001 — 已亡/权限：ESRCH 静默语义
        return False


def kill_tree(target_pid: int, sig: int, *, caller: str, resolve: bool = False) -> bool:
    """守卫版整树击杀：拒自身/祖先链；SIGTERM 优雅层 / SIGKILL 整树硬杀。

    守卫两拒绝分支与 linux.kill_tree 同构（命中记 WARNING 含调用点标识、
    按「目标不存在」语义返回 False）：

    1. 目标为调用者自身或自身祖先链成员（Windows 无进程组概念，守卫以
       ppid 上溯链替代 linux 的 getpgid(0) 自身组判定）；
    2. ``target_pid <= 0``（替身怪值——os.kill 语义下负值/0 是全组广播
       形态，Windows 上等价误杀面，一律拒绝）。

    ``resolve`` 形态差异（显式文档化）：Windows 控制台进程组 id ＝ 组长
    pid（CREATE_NEW_PROCESS_GROUP 的入参即子进程 pid），本车道全部 spawn
    均为 new_session 组长形态，「成员 pid 解析组长」无独立语义——resolve
    形态下 target_pid 原样使用（与 linux 语义差异登记于知识页）。

    信号语义（返回 True＝击杀动作已发出；False＝守卫拒绝或目标不存在）：

    - SIGTERM：CTRL_BREAK 投递（同控制台可达；deliverable 探测即调用结果）
      → 不可达（无控制台）退化为 TerminateProcess（优雅层缺席显式降级，
      等价进程死亡，返回 True——信号「已发出」语义）；
    - SIGKILL：Job Object 主（注册表句柄 TerminateJobObject 整树）+
      Toolhelp 后代枚举兜底 + root 本体补刀；
    - SIGTERM/SIGKILL 之外的信号值（sig==0 探活形态等）：按存在性检查
      处理（True/False），不投递。

    ESRCH 静默：目标已亡（打不开/探测不到）按 False 返回，调用方既有
    「组已不存在」路径不变。
    """
    if int(target_pid) <= 0:
        _logger.warning(
            "kill_tree self-guard: caller=%s 非正目标 pid=%d（替身怪值误杀面）"
            " — 拒绝击杀，按目标不存在静默返回",
            caller, target_pid,
        )
        return False
    if _is_self_or_ancestor(target_pid):
        _logger.warning(
            "kill_tree self-guard: caller=%s 目标=调用者自身或祖先链成员 "
            "(pid=%d) — 拒绝击杀，按目标不存在静默返回",
            caller, target_pid,
        )
        return False
    if not _pid_alive(int(target_pid)):
        return False  # 已亡：ESRCH 静默语义，逐位对齐
    if sig == 0:
        return True  # 探活形态：存在即 True（未投递）
    if sig == SIGTERM:
        try:
            sent = bool(
                _k32().GenerateConsoleCtrlEvent(CTRL_BREAK_EVENT, int(target_pid)))
        except Exception:  # noqa: BLE001 — 无共享控制台：优雅层缺席
            sent = False
        if not sent:
            # CTRL_BREAK 不可达（NSSM 服务形态）：退化为 TerminateProcess。
            # 优雅层缺席是 Windows 无控制台承载的显式差异（知识页登记）。
            _hard_kill_pid(int(target_pid))
        return True
    if sig == SIGKILL:
        if _terminate_job_tree(int(target_pid)):
            return True
        killed_any = False
        for pid in _descendant_pids(int(target_pid)):
            killed_any = _hard_kill_pid(pid) or killed_any
        return _hard_kill_pid(int(target_pid)) or killed_any
    # 其余信号值：Windows 无投递语义，按存在性收口（真值=目标在）
    return True


def bind_to_parent(sig: int = SIGTERM) -> bool:
    """PR_SET_PDEATHSIG 的 Windows 等价：Job Object kill-on-close 句柄移交父进程。

    自建 KILL_ON_JOB_CLOSE job → assign 自身 → 句柄 DuplicateHandle 进
    父进程 → 关闭自身副本：父死句柄表销毁 → job 关 → 自杀（泄漏即死，
    消费方 dashboard serve 孤儿自护）。``sig`` 形参保留签名兼容（linux
    侧为投递信号；Windows 侧 job 关闭是进程终止，信号值无语义，接收但不
    使用——文档化差异）。

    False＝父已亡 / 打开父失败 / job 建设或 assign 失败（嵌套 job 限制等）
    ——stderr 告警与「孤儿启动拒绝」策略留消费端（与 linux 同契约）。
    """
    try:
        ppid = os.getppid()
        if not ppid or ppid <= 0 or not _pid_alive(ppid):
            return False
        h_parent = _open_process(ppid, PROCESS_DUP_HANDLE)
        if not _handle_valid(h_parent):
            return False
        try:
            job = _make_kill_on_close_job()
            if job is None:
                return False
            k32 = _k32()
            if not k32.AssignProcessToJobObject(job, k32.GetCurrentProcess()):
                k32.CloseHandle(job)
                return False
            dup = ctypes.c_void_p(0)
            if not k32.DuplicateHandle(
                k32.GetCurrentProcess(), job, h_parent, ctypes.byref(dup),
                0, False, DUPLICATE_SAME_ACCESS,
            ):
                k32.CloseHandle(job)
                return False
            # 自身副本关闭：job 句柄此后仅存于父进程（父亡 → 表销毁 → 自杀）
            k32.CloseHandle(job)
            return True
        finally:
            k32.CloseHandle(h_parent)
    except Exception:  # noqa: BLE001 — 非 Windows/句柄异常按失败返回
        return False


def kill_group_alive(pgid: int) -> Optional[bool]:
    """进程组探活三态（sig=0 等价存在性检查，不投递信号）。

    True＝组长存活且有权探测 / False＝已亡（确定性否定）/ None＝psutil
    缺失等无法核实（调用方按各自保守方向处置）。Windows 组 id ≙ 组长 pid
    （见 kill_tree resolve 差异注记）；``pgid <= 0`` 与 ESRCH 同向 False
    （linux 同契约）。
    """
    if int(pgid) <= 0:
        return False
    try:
        import psutil
    except ImportError:
        return None
    try:
        return psutil.pid_exists(int(pgid))
    except (OSError, ValueError):
        return None


# ═══════════════════════════════════════════════════════════════════════
# B 进程情报
# ═══════════════════════════════════════════════════════════════════════

def _psutil_process(pid: int):
    """psutil.Process 或 None（缺失/不存在/非法 pid——「读取失败」契约方向）。"""
    try:
        import psutil
    except ImportError:
        return None
    try:
        return psutil.Process(int(pid))
    except (psutil.Error, ValueError, OSError):
        return None


def read_cmdline_raw(pid: int) -> Optional[bytes]:
    """进程 cmdline 原始字节（NUL 分隔）；读不到（已退出/权限/psutil 缺失）→ None。

    与 linux 契约同形：消费方 NUL 切 token / NUL→空格还原两形态各按既有
    口径（proc_utils.is_claude_process 以 argv[0] 判 claude/claude.exe）。
    """
    proc = _psutil_process(pid)
    if proc is None:
        return None
    try:
        argv = proc.cmdline()
    except Exception:  # noqa: BLE001 — psutil.AccessDenied/ZombieProcess 族
        return None
    if not argv:
        return None
    return b"\0".join(str(a).encode("utf-8", "replace") for a in argv) + b"\0"


def cmdline_argv(pid: int) -> Optional[List[str]]:
    """cmdline 切 argv token（NUL 分隔、utf-8 replace 解码、空段丢弃）；读不到 → None。"""
    raw = read_cmdline_raw(pid)
    if raw is None:
        return None
    return [a.decode("utf-8", "replace") for a in raw.split(b"\0") if a]


def proc_stat_fields(pid: int) -> Optional[List[str]]:
    """Windows 无 procfs：恒 None（「读取失败」契约方向，形态兼容保留）。

    注意：探活/身份接口（pid_alive_stat / proc_start_ticks / process_info）
    在本后端**不叠本函数**（Windows 原生 psutil 实现），避免
    「读不到判死」的 fail-closed 翻转。
    """
    return None


def proc_start_ticks(pid: int) -> Optional[int]:
    """进程创建时刻（毫秒整，int(create_time()*1000)）；读不到 → None。

    pid + start_token 唯一确定一个进程实例（CreationTime 在进程创建时
    固定，对 exec/argv 变化免疫）——linux 侧 starttime 锚的平台同缝换。
    值为 pal 自产自销锚：跨后端（linux tick vs win32 毫秒）不可比，
    身份比对消费面两侧各自闭环。
    """
    proc = _psutil_process(pid)
    if proc is None:
        return None
    try:
        return int(proc.create_time() * 1000)
    except Exception:  # noqa: BLE001 — 读取竞态（进程恰亡）→ None
        return None


def pid_alive_stat(pid: int, zombie_is_dead: bool = False) -> bool:
    """进程存活判定；不可探测按已终止计（宁可少杀，linux 同方向）。

    ``zombie_is_dead`` 形参保留签名兼容：Windows 无僵尸态（无 Unix 父子
    收尸模型），两取值同语义（文档化差异）。
    """
    return _pid_alive(int(pid))


def pid_alive_signal(pid: int) -> bool:
    """kill(pid,0) 口径存在性判定（Windows 上 os.kill(pid,0)＝TerminateProcess，
    MUST 走 psutil —— 见模块 docstring A 组陷阱注记）。

    他主进程（AccessDenied）按存活——与 linux「EPERM=存活」保守方向同构。
    """
    return _pid_alive(int(pid))


def readlink_cwd(pid: int) -> Optional[str]:
    """进程 cwd；读取失败/已退出/权限不足 → None。

    linux 侧「空串＝僵尸态原样返回」形态在 Windows 不存在（无僵尸态）。
    """
    proc = _psutil_process(pid)
    if proc is None:
        return None
    try:
        cwd = proc.cwd()
    except Exception:  # noqa: BLE001 — AccessDenied/读取竞态
        return None
    return str(cwd) if cwd else None


def parent_comm(pid: int) -> Optional[str]:
    """进程名（``/proc/<pid>/comm`` 的 psutil 同缝换：Process.name strip）；读不到 → None。"""
    proc = _psutil_process(pid)
    if proc is None:
        return None
    try:
        name = proc.name()
    except Exception:  # noqa: BLE001 — 读取竞态
        return None
    return str(name).strip() if name else None


def proc_dir_mtime(pid: int) -> Optional[float]:
    """进程创建时刻（秒级浮点，create_time 原值）；读不到 → None。

    ＝ linux「/proc/<pid> 目录 mtime ≈ 创建时刻」的 Windows 同缝换
    （v2_dev_server 启动宽限豁免的时间锚语义一致）。
    """
    proc = _psutil_process(pid)
    if proc is None:
        return None
    try:
        return float(proc.create_time())
    except Exception:  # noqa: BLE001 — 读取竞态
        return None


def read_procfile(relpath: str) -> Optional[bytes]:
    """Windows 无 procfs：恒 None（杂项消费点「读取失败」契约方向）。"""
    return None


PROCFS_ROOT = None  # Windows 无 procfs（路径构造消费面只存在于 linux 侧）


def proc_pids() -> List[str]:
    """全量 pid 枚举（psutil.pids 数字字符串列表；枚举失败异常上抛不吞）。

    linux 契约「OSError 上抛不吞」逐位对齐：吞成空表会把「无法枚举」
    伪装成「无进程」，破坏调用方降级语义。
    """
    import psutil
    return [str(p) for p in psutil.pids()]


# 合法 env 键名（与 linux.ENV_KEY_RE 同值同语义：非法键/含换行值跳过）
ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def process_environ(pid: int) -> dict:
    """读进程实环境为 dict（不可读/已退出 → 空 dict）。

    键集为在跑进程的实环境（迁移链非白名单凭记忆）；非法键名/含换行的值
    跳过（EnvironmentFile 行格式契约，与 linux 同构）。psutil 缺失 → {}。
    """
    proc = _psutil_process(pid)
    if proc is None:
        return {}
    try:
        raw_env = proc.environ()
    except Exception:  # noqa: BLE001 — AccessDenied/读取竞态
        return {}
    env = {}
    for key, value in dict(raw_env or {}).items():
        if not isinstance(key, str) or not ENV_KEY_RE.match(key):
            continue
        if not isinstance(value, str) or "\n" in value or "\r" in value:
            continue
        env[key] = value
    return env


def find_port_owner(port: int) -> Optional[dict]:
    """定位 LISTEN 目标端口的进程。

    返回 {"pid": int, "cmdline": str, "starttime": int|None} 或 None
    （无占用 / 无法判定）。psutil.net_connections（inet + LISTEN +
    laddr.port 匹配）；无管理员权限时他人条目 pid=None——全部候选均无
    pid 视「无法判定」（探测失败≠无占用者）返回 None 并 stderr 留痕，
    与 linux「匹配不上即不接管」保守语义同构。starttime 即
    proc_start_ticks 单源（接管方 kill 前身份复核，防 PID 复用误杀）。
    """
    try:
        import psutil
    except ImportError:
        return None
    unknown_pid = False
    try:
        for conn in psutil.net_connections(kind="inet"):
            laddr = getattr(conn, "laddr", None)
            if laddr is None or getattr(laddr, "port", None) != int(port):
                continue
            if conn.status != psutil.CONN_LISTEN:
                continue
            pid = getattr(conn, "pid", None)
            if not pid:
                unknown_pid = True  # 无管理员权限形态：条目在、归属不可判
                continue
            argv = cmdline_argv(pid) or []
            return {"pid": int(pid), "cmdline": " ".join(argv).strip(),
                    "starttime": proc_start_ticks(pid)}
    except Exception as e:  # noqa: BLE001 — 探测异常≠无占用者，兜底 None + 留痕
        sys.stderr.write(f"dashboard 端口占用者探测异常（按无占用者处理）: {e}\n")
        return None
    if unknown_pid:
        sys.stderr.write(
            f"dashboard 端口 {int(port)} 存在监听但归属进程不可判（需要管理员"
            f"权限），按无占用者处理——接管语义保守跳过。\n")
    return None


def listen_inodes_for_port(port: int) -> List[str]:
    """Windows 无 socket inode 概念：恒 []（「无监听」降级方向已文档化）。

    身份收口消费面（v2_dev_server）以 inode 断 socket 身份——Windows 侧
    该判据不可用，消费面按「本轮无监听」处置（重试窗兜底不变）。
    """
    return []


def proc_socket_links(pid: int) -> Optional[List[str]]:
    """Windows 无 fd 软链接读面：恒 None（「无法核实」契约方向）。"""
    return None


def process_tree_cpu_seconds(proc) -> Optional[float]:
    """run 子进程进程树累计 CPU 时间（秒），不可解析返回 None（fail-open）。

    psutil Process.cpu_times()（user+system）+ children(recursive) 树汇总，
    对 execvp 形态的后代（node/ocr）覆盖与 linux 侧 /proc children 汇总
    同构。任一环节不可解析（psutil 缺失/进程亡/权限）→ None，看门狗
    fail-open 不触发（宁可漏杀不可误杀，linux 同方向）。
    """
    pid = getattr(proc, "pid", None)
    if not pid or int(pid) <= 0:
        return None
    try:
        import psutil
    except ImportError:
        return None
    try:
        root = psutil.Process(int(pid))
        procs = [root, *root.children(recursive=True)]
        total = 0.0
        for p in procs:
            try:
                times = p.cpu_times()
            except (psutil.Error, OSError):
                continue  # 遍历间隙消亡的后代跳过
            total += float(times.user) + float(times.system)
        return total
    except (psutil.Error, OSError, ValueError):
        return None  # 顶层 pid 读不到 → 判据不可用，调用方 fail-open


# is_alive_with_identity 的合法锚键（与 linux 同闭集；未知锚键拒绝）
_IDENTITY_ANCHOR_KEYS = ("start_ticks", "cwd_real", "cwd_prefix")


def is_alive_with_identity(pid: int, identity) -> Optional[bool]:
    """身份锚定探活，fail-closed 三态：True＝锚定命中 / False＝失配 / None＝无法核实。

    锚键、备选析取/合取、三态合并语义与 linux 逐位同构（start_ticks 锚
    在本后端即 start_token 毫秒值，pal 自产自销闭环）；``cwd_real`` /
    ``cwd_prefix`` 锚经 psutil cwd + realpath 归一。读不到 → None，消费
    端保守方向各自保留，本接口不代选。
    """
    alternatives = [identity] if isinstance(identity, dict) else list(identity)
    if not alternatives:
        raise ValueError("identity 须为至少一个锚定字典（或其非空列表）")
    pid = int(pid)
    any_unknown = False
    for alt in alternatives:
        if not isinstance(alt, dict) or not alt:
            raise ValueError(f"锚定备选须为非空 dict：{alt!r}")
        unknown_keys = set(alt) - set(_IDENTITY_ANCHOR_KEYS)
        if unknown_keys:
            raise ValueError(f"未知身份锚键：{sorted(unknown_keys)}（合法："
                             f"{list(_IDENTITY_ANCHOR_KEYS)}）")
        verdict = _identity_alternative_match(pid, alt)
        if verdict is True:
            return True
        if verdict is None:
            any_unknown = True
    return None if any_unknown else False


def _identity_alternative_match(pid: int, alt: dict) -> Optional[bool]:
    """单备选合取判定：任一锚确定性失配 → False；任一锚不可核实 → None。"""
    if "start_ticks" in alt:
        want = alt["start_ticks"]
        if want is None:
            return None
        got = proc_start_ticks(pid)
        if got is None:
            return None
        if got != int(want):
            return False
    if "cwd_real" in alt or "cwd_prefix" in alt:
        link = readlink_cwd(pid)
        if not link:
            return None  # 读不到 → 无法核实（不折算调用者 cwd，防身份误锚）
        cwd_real = os.path.realpath(link)
        if "cwd_real" in alt and cwd_real != os.path.realpath(str(alt["cwd_real"])):
            return False
        if "cwd_prefix" in alt:
            base_real = os.path.realpath(str(alt["cwd_prefix"]))
            if cwd_real != base_real and not cwd_real.startswith(base_real + os.sep):
                return False
    return True


def process_info(pid: int) -> Optional[dict]:
    """具名进程情报快照（SPEC 钉死形状 {alive, cmdline, exe, cwd, ppid,
    start_token}）；快照语义字段独立允许部分缺席；整体读不到 → None
    fail-closed 按死处置。``start_token`` 即 proc_start_ticks 单源。
    """
    proc = _psutil_process(pid)
    if proc is None:
        return None
    try:
        cmdline = cmdline_argv(pid)
        try:
            exe = str(proc.exe())
        except Exception:  # noqa: BLE001 — AccessDenied/已退出 → 缺席
            exe = None
        try:
            ppid = int(proc.ppid())
        except Exception:  # noqa: BLE001 — 读取竞态 → 缺席
            ppid = None
        try:
            cwd = proc.cwd()
        except Exception:  # noqa: BLE001 — AccessDenied → 缺席
            cwd = None
        return {
            "alive": _pid_alive(int(pid)),
            "cmdline": cmdline,
            "exe": exe,
            "cwd": str(cwd) if cwd else None,
            "ppid": ppid,
            "start_token": proc_start_ticks(pid),
        }
    except Exception:  # noqa: BLE001 — 快照中途进程消亡按 None（fail-closed）
        return None


def orphaned_process() -> bool:
    """孤儿启动判据（linux「PPID==1 已被收养」的 Windows 同缝换）。

    Windows 无 pid 1 收养模型：父进程亡后 ppid 残留死值——判据为
    「父进程已不存在」（ppid 空值/已亡）。psutil 缺失或父进程可探测失败
    按 False（不阻断启动——bind_to_parent 的 job 兜底仍在；显式文档化
    「无法核实不拒启动」差异）。linux 后端实现为 ``os.getppid() == 1``
    逐位等价（消费方 server.py 平移链）。
    """
    ppid = os.getppid()
    if not ppid or ppid <= 0 or ppid == 1:
        return True
    try:
        import psutil
    except ImportError:
        return False  # 无法核实 → 不阻断（job 兜底）
    try:
        return not psutil.pid_exists(ppid)
    except (OSError, ValueError):
        return False


def exit_code_signal_name(exit_code) -> Optional[str]:
    """退出码 → 信号死法标记名；非信号死法形态 → None。

    Windows 闭集（见模块 docstring B 组注记）：STATUS_CONTROL_C_EXIT →
    "CTRL_BREAK"；0xFFFFFFFF（taskkill /F、Stop-Process 默认形态）→
    "SIGKILL"。143/128+N/负值数字形态在 Windows 是程序自选退出码（无
    POSIX 信号投递语义），一律 None——runner 侧 [signal-kill:] 标签据此
    平台化（Linux 后端为 129..159/负信号闭集逐字平移）。
    """
    if not isinstance(exit_code, int) or exit_code == 0:
        return None
    if exit_code == STATUS_CONTROL_C_EXIT:
        return "CTRL_BREAK"
    if exit_code == TERMINATE_EXIT_CODE_EXTERNAL:
        return "SIGKILL"
    return None


# ═══════════════════════════════════════════════════════════════════════
# C 文件锁（msvcrt.locking 1 字节纪律）
# ═══════════════════════════════════════════════════════════════════════

# 「锁被占」类 errno（重试契约闭集）：EACCES/EAGAIN 与 linux 同闭集；
# EDEADLOCK（36，Windows msvcrt.locking 文档化返回码之一）平台补编。
_LOCK_BUSY_ERRNOS = frozenset({
    errno.EACCES, errno.EAGAIN, getattr(errno, "EDEADLOCK", 36),
})

_LOCK_NBYTES = 1  # 1 字节加锁纪律（强制锁面，design R3）


def _msvcrt():
    import msvcrt  # noqa: 平台专属惰性导入（Linux 上 import 本模块不触发）
    return msvcrt


def _lock_fd(fileobj) -> int:
    """fileobj/fd 双形态归一为 fd（msvcrt.locking 只收 fd）。"""
    fd = getattr(fileobj, "fileno", None)
    return int(fd()) if fd is not None else int(fileobj)


def _seek0(fd: int) -> None:
    # msvcrt.locking 从**当前位置**起算（经典陷阱）：lock/unlock 前显式回 0
    os.lseek(fd, 0, os.SEEK_SET)


def flock_exclusive(fileobj, *, nonblocking: bool = False) -> None:
    """单次排他锁（msvcrt.locking LK_NBLCK 1 字节纪律；失败抛 OSError）。

    ``nonblocking=False`` 的「阻塞」语义以 50ms 步长无限重试表达
    （msvcrt LK_LOCK 仅重试 10 次，不满足 linux 无限阻塞契约）。
    锁被占类 errno 原样上抛（两因分类归 try_lock/exclusive_lock）。
    """
    msvcrt = _msvcrt()
    fd = _lock_fd(fileobj)
    _seek0(fd)
    deadline = None if nonblocking else time.monotonic() + float("inf")
    while True:
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, _LOCK_NBYTES)
            return
        except OSError as e:
            if e.errno not in _LOCK_BUSY_ERRNOS:
                raise
            if nonblocking:
                raise
            if time.monotonic() >= deadline:  # pragma: no cover — inf 不可达
                raise
            time.sleep(0.05)


def flock_release(fileobj) -> None:
    """LK_UNLCK 释放（close 亦隐式释放；失败原样上抛，linux 同契约）。"""
    msvcrt = _msvcrt()
    fd = _lock_fd(fileobj)
    _seek0(fd)
    msvcrt.locking(fd, msvcrt.LK_UNLCK, _LOCK_NBYTES)


@contextmanager
def _lock_handle(lock_f):
    """持锁句柄：yield 锁内区间，退出时 unlock + close（与 with_file_lock 同纪律）。"""
    try:
        yield lock_f
    finally:
        try:
            flock_release(lock_f)
        finally:
            lock_f.close()


def _open_companion_lock(path: Path):
    """``.<name>.lock`` 伴生锁文件打开（布局与 fs_utils.with_file_lock 同源）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return open(path.parent / f".{path.name}.lock", "w")


def try_lock(path):
    """单次抢伴生锁；成功返回持锁句柄，他方持锁返回 None；锁不可用抛
    ``FileLockUnavailable``（两因可区分契约与 linux 同构）。"""
    lock_f = _open_companion_lock(path)
    try:
        flock_exclusive(lock_f, nonblocking=True)
    except OSError as e:
        lock_f.close()
        if e.errno in _LOCK_BUSY_ERRNOS:
            return None
        raise FileLockUnavailable(f"文件系统不支持 flock（errno={e.errno}）") from e
    except BaseException:
        lock_f.close()
        raise
    return _lock_handle(lock_f)


def exclusive_lock(path, timeout_s: Optional[float] = None):
    """抢伴生锁；``timeout_s=None`` 无限轮询（现行缺省语义），有限值 50ms 步长限时。

    仅锁被占类 errno 值得重试，其余立即抛 ``FileLockUnavailable``；限时
    未抢到抛 ``FileLockBusy``（两因分类契约与 linux 同构）。
    """
    lock_f = _open_companion_lock(path)
    acquired = False
    try:
        if timeout_s is None:
            flock_exclusive(lock_f)
        else:
            deadline = time.monotonic() + max(0.0, float(timeout_s))
            while True:
                try:
                    flock_exclusive(lock_f, nonblocking=True)
                    break
                except OSError as e:
                    if e.errno not in _LOCK_BUSY_ERRNOS:
                        raise FileLockUnavailable(
                            f"文件系统不支持 flock（errno={e.errno}）") from e
                    if time.monotonic() >= deadline:
                        raise FileLockBusy(
                            f"限时 {float(timeout_s):g}s 内未抢到锁（他方持锁）"
                        ) from e
                    time.sleep(0.05)
        acquired = True
    finally:
        if not acquired:
            lock_f.close()
    return _lock_handle(lock_f)


# ═══════════════════════════════════════════════════════════════════════
# D 托管（systemctl 缝 + NSSM 服务后端；systemd 语义映射见模块 docstring）
# ═══════════════════════════════════════════════════════════════════════

def _nssm_service_name(root) -> str:
    """服务名 = systemd_hosting.unit_name_for(root) 去 ``.service`` 后缀
    （命名单源跨平台一致；NSSM 服务名允许字母数字与连字符段）。"""
    import core.systemd_hosting as _hosting

    return _hosting.unit_name_for(root)[: -len(".service")]


def _require_nssm() -> str:
    """nssm.exe 路径探测；缺席抛 SystemdHostingError（含安装指引）。"""
    nssm = shutil.which("nssm")
    if not nssm:
        raise SystemdHostingError(
            "需要 NSSM：nssm.exe 不可用（Windows 承载后端为 NSSM 服务，"
            "备选 WinSW）。请安装 NSSM（winget install nssm 或 "
            "choco install nssm，或手动下载后加入 PATH）后重试。"
        )
    return nssm


def _sc_query(name: str) -> Optional[str]:
    """``sc query <name>`` 输出（服务不存在返回 None；locale 无关解析）。

    状态解析按数字段（STATE : 4 RUNNING）——sc 输出文案随系统 locale
    变化，数字态值稳定（4=SERVICE_RUNNING）。
    """
    try:
        proc = subprocess.run(["sc", "query", name], capture_output=True,
                              text=True, timeout=30)
    except (subprocess.SubprocessError, OSError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout or ""


_SERVICE_STATE_RUNNING = 4  # SERVICE_RUNNING（数字态值，locale 无关）


def _service_state(name: str) -> Optional[int]:
    out = _sc_query(name)
    if out is None:
        return None  # 服务不存在 / sc 不可用
    m = re.search(r"STATE\s*:\s*(\d+)", out)
    return int(m.group(1)) if m else None


def systemctl_available() -> bool:
    """Windows 无 systemd：恒 False（承载经 NSSM HostingProvider 六名）。"""
    return False


def run_systemctl(args, timeout: float = 30, *,
                  available: Optional[bool] = None) -> subprocess.CompletedProcess:
    """Windows 无 systemd：恒抛 SystemdHostingError（NSSM 承载指引文案）。"""
    raise SystemdHostingError(
        "需要 systemd：Windows 平台无 systemctl（非 systemd 环境）。"
        "fenixd Windows 承载链为 NSSM 服务后端（HostingProvider 六名），"
        "systemctl 缝在本平台恒不可用。"
    )


def _nssm_set(nssm: str, name: str, param: str, value: str) -> None:
    proc = subprocess.run([nssm, "set", name, param, value],
                          capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise SystemdHostingError(
            f"nssm set {name} {param} 失败: {(proc.stderr or proc.stdout or '').strip()}")


def install_unit(root) -> dict:
    """安装（如缺）并启动 NSSM 服务；幂等（已装且活跃不重建不重启）。

    Returns: {"ok": bool, "error": str|None, "already": bool, "unit": str}
    （形状与 linux 后端 install_project_unit 逐字段同构）。

    服务命令与 linux ExecStart 同源：``<python> <root>/.fenix/bin/
    fenixd_supervisor.py --project-root <root>``（AppDirectory=root）；
    日志经 AppStdout/AppStderr 落 ``<root>/.fenix/nssm/<服务名>.log``。
    supervisor 脚本缺席按失败返回（可读错误，不静默半装）。
    """
    import core.systemd_hosting as _hosting

    name = _nssm_service_name(root)
    proot = Path(root)
    supervisor = proot / ".fenix" / "bin" / "fenixd_supervisor.py"
    state = _service_state(name)
    if state is not None and state != 0:
        if state == _SERVICE_STATE_RUNNING:
            return {"ok": True, "error": None, "already": True, "unit": name}
        # 已安装未运行（STOPPED 等）→ 拉起即可（幂等不重建）
        try:
            start(root)
            return {"ok": True, "error": None, "already": True, "unit": name}
        except SystemdHostingError as e:
            return {"ok": False, "error": str(e), "already": True, "unit": name}
    if not supervisor.is_file():
        return {"ok": False, "error": (
            f"supervisor 脚本缺席：{supervisor} 不存在——先完成项目部署"
            f"（.fenix/bin 播种）再安装服务。"), "already": False, "unit": name}
    try:
        nssm = _require_nssm()
        proc = subprocess.run(
            [nssm, "install", name, sys.executable], capture_output=True,
            text=True, timeout=60)
        if proc.returncode != 0:
            raise SystemdHostingError(
                f"nssm install {name} 失败: "
                f"{(proc.stderr or proc.stdout or '').strip()}")
        log_path = proot / ".fenix" / "nssm" / f"{name}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        _nssm_set(nssm, name, "AppDirectory", str(proot))
        _nssm_set(nssm, name, "AppParameters",
                  f'"{sys.executable}" "{supervisor}" --project-root "{proot}"')
        _nssm_set(nssm, name, "AppStdout", str(log_path))
        _nssm_set(nssm, name, "AppStderr", str(log_path))
        _nssm_set(nssm, name, "AppStdoutCreationBytesToPreserve", "0")
        _nssm_set(nssm, name, "Start", "SERVICE_AUTO_START")
        _nssm_set(nssm, name, "AppExit", "Default")
        start(root)
        return {"ok": True, "error": None, "already": False, "unit": name}
    except SystemdHostingError as e:
        return {"ok": False, "error": str(e), "already": False, "unit": name}
    except (subprocess.SubprocessError, OSError) as e:
        return {"ok": False, "error": f"NSSM 服务安装失败: {e}",
                "already": False, "unit": name}


def start(root) -> None:
    """拉起项目服务（幂等：RUNNING 即返回；失败 SystemdHostingError 上抛）。"""
    name = _nssm_service_name(root)
    state = _service_state(name)
    if state is None:
        raise SystemdHostingError(
            f"服务 {name} 未安装（sc query 无响应）——先 install_unit。")
    if state == _SERVICE_STATE_RUNNING:
        return
    nssm = _require_nssm()
    proc = subprocess.run([nssm, "start", name], capture_output=True,
                          text=True, timeout=60)
    if proc.returncode != 0:
        raise SystemdHostingError(
            f"nssm start {name} 失败: "
            f"{(proc.stderr or proc.stdout or '').strip()}")


def stop(root) -> None:
    """停止项目服务（NSSM stop 同步等停——与 linux ``--no-block`` 即返的
    语义差异显式文档化；排水等待归消费端轮询的契约不变）。"""
    name = _nssm_service_name(root)
    if _service_state(name) is None:
        return  # 未安装：幂等静默（linux stop 对缺失 unit 的静默语义同构）
    nssm = _require_nssm()
    proc = subprocess.run([nssm, "stop", name], capture_output=True,
                          text=True, timeout=60)
    if proc.returncode != 0:
        raise SystemdHostingError(
            f"nssm stop {name} 失败: "
            f"{(proc.stderr or proc.stdout or '').strip()}")


def is_running(root) -> bool:
    """服务是否 RUNNING（sc query 数字态解析，locale 无关）。"""
    return _service_state(_nssm_service_name(root)) == _SERVICE_STATE_RUNNING


def env_file(root):
    """项目服务 env 文件路径（复用 project_env_file 单源：<root>/.fenix/
    同位布局；消费经安装时注入 AppEnvironmentExtra——差异见 docstring）。"""
    import core.systemd_hosting as _hosting

    return _hosting.project_env_file(root)


def logs_hint(root) -> str:
    """日志排查提示（NSSM 文件日志形态，替 linux journalctl）。"""
    return f"type {Path(root) / '.fenix' / 'nssm' / (_nssm_service_name(root) + '.log')}"


# ═══════════════════════════════════════════════════════════════════════
# E 环境/用户/文件系统
# ═══════════════════════════════════════════════════════════════════════

def home_dir(env: Optional[dict] = None) -> Optional[str]:
    """家目录三级解析：``HOME``（unix-y 工具常设）→ ``USERPROFILE`` →
    ``HOMEDRIVE+HOMEPATH`` → None（级内异常/空值落下一级，两级皆空 None）。
    ``~`` 展开由调用方按既有口径处理（git_env 侧 expanduser）。"""
    if env is None:
        env = os.environ
    home = env.get("HOME")
    if isinstance(home, str) and home.strip():
        return home
    profile = env.get("USERPROFILE")
    if isinstance(profile, str) and profile.strip():
        return profile
    drive = env.get("HOMEDRIVE")
    path_part = env.get("HOMEPATH")
    if isinstance(drive, str) and drive.strip() and isinstance(path_part, str) and path_part.strip():
        return drive + path_part
    return None


def current_user() -> Optional[str]:
    """当前用户名（getpass.getuser，env USERNAME 域内解析）；解析失败 → None。"""
    try:
        import getpass
        return getpass.getuser() or None
    except Exception:  # noqa: BLE001 — ImportError/无法解析（ linux 同契约 → None）
        return None


def ensure_link(src, dst) -> bool:
    """目录链接幂等补建：symlink → junction → copy 三级降级链。

    纪律与 linux 同构（src 缺席 → False；lexists 判定 + 悬空摘除自愈；
    有效链接/真实目录在位 → True 不重建；最终失败 OSError 上抛）。
    平台降级链差异：junction（``_winapi.CreateJunction``）目录等价无特权
    要求；copy（``shutil.copytree``）**内容在位但非链接**——身份语义
    （经链接读回同一文件）在 copy 态不成立，属显式文档化的最终降级
    （knowledge 页登记；消费面按「目录在位」语义消费不受影响）。
    """
    src = Path(src)
    dst = Path(dst)
    if not src.is_dir():
        return False
    if os.path.lexists(dst):
        # Windows 悬空判定：链接目标不存在（islink/is_junction 形态统一按
        # 「exists()==False 但 lexists()==True」识别）→ 摘除重建
        if (dst.is_symlink() or _is_junction(dst)) and not dst.exists():
            os.rmdir(str(dst)) if dst.is_dir() else dst.unlink()
        else:
            return True
    try:
        dst.symlink_to(src, target_is_directory=True)
        return True
    except OSError:
        pass
    try:
        import _winapi  # noqa: 平台专属惰性（Linux 测试面以 mock 替换）
        _winapi.CreateJunction(str(src), str(dst))
        return True
    except OSError:
        pass
    # 最终降级：copy（内容在位、非链接——显式文档化差异）
    shutil.copytree(str(src), str(dst), dirs_exist_ok=True)
    return True


def _is_junction(path: Path) -> bool:
    """目录 junction 判定（reparse point 中 IO_REPARSE_TAG_MOUNT_POINT）。"""
    try:
        import _winapi  # noqa: 平台专属惰性
        return bool(
            os.lstat(str(path)).st_file_attributes
            & _winapi.FILE_ATTRIBUTE_REPARSE_POINT
        ) and not path.is_symlink()
    except (OSError, AttributeError, ImportError, ValueError):
        return False


def fsync_dir(path) -> None:
    """目录项刷盘纪律（FlushFileBuffers + FILE_FLAG_BACKUP_SEMANTICS）；
    尽力而为失败静默（linux 同契约：个别文件系统不支持时保留进程级
    崩溃安全保证）。"""
    try:
        k32 = _k32()
        h = k32.CreateFileW(
            str(path), GENERIC_WRITE, 0x7, None, OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS, None)
        if not _handle_valid(h):
            return
        try:
            k32.FlushFileBuffers(h)
        finally:
            k32.CloseHandle(h)
    except Exception:  # noqa: BLE001 — 尽力而为静默
        return


def atomic_replace(src, dst) -> None:
    """``os.replace`` + Windows 占用抖动短重试（20ms×5 后原样上抛）。

    Windows 上目标被他人短暂持有句柄（AV 扫描/并发读者）时 replace 抛
    PermissionError——限时重试吸收抖动，重试耗尽原样上抛（不吞）。
    Linux 后端为 ``os.replace`` 直通（零行为变化）。
    """
    src = str(src)
    dst = str(dst)
    last_err: Optional[OSError] = None
    for attempt in range(5):
        try:
            os.replace(src, dst)
            return
        except PermissionError as e:
            last_err = e
            time.sleep(0.02)
    raise last_err  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════
# F 测试基建
# ═══════════════════════════════════════════════════════════════════════

def pytest_timeout_method() -> str:
    """pytest-timeout 超时机制平台锚点：Windows 恒 ``"thread"``（无 SIGALRM）。"""
    return "thread"


__all__ = [
    "IS_WINDOWS",
    "TERM_GRACE_SECONDS",
    "PROCFS_ROOT",
    "FileLockBusy",
    "FileLockUnavailable",
    "SystemdHostingError",
    "SIGTERM",
    "SIGINT",
    "SIGKILL",
    # A
    "spawn_detached",
    "run_detached",
    "spawn_detached_async",
    "terminate_graceful",
    "kill_tree",
    "bind_to_parent",
    "kill_group_alive",
    "stdin_eof",
    "exit_code_signal_name",
    # B
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
    "orphaned_process",
    # C
    "flock_exclusive",
    "flock_release",
    "exclusive_lock",
    "try_lock",
    # D
    "systemctl_available",
    "run_systemctl",
    "install_unit",
    "start",
    "stop",
    "is_running",
    "env_file",
    "logs_hint",
    # E
    "home_dir",
    "current_user",
    "ensure_link",
    "fsync_dir",
    "atomic_replace",
    # F
    "pytest_timeout_method",
    # D/B 支撑单源
    "ENV_KEY_RE",
]
