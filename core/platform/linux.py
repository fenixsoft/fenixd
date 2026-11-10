"""linux.py — PAL Linux 后端（既有行为逐条平移，core/ 唯一平台位面）。

本模块是 add-platform-abstraction-layer 的 Linux 后端实现：core/ 全部
平台敏感 syscall 与 /proc 读面的**单点归宿**。全部实现为既有代码的逐字
平移（含失败方向的注释语义），仅被平移模块自 W4/W5 起改为转发引用；
Linux 全部行为零变化是本 SPEC 的行为契约。

静态守卫（tests/test_platform_guard.py）以本文件为全库唯一豁免：
``fcntl`` / ``pwd`` / ``os.killpg`` / ``os.setsid`` / ``start_new_session=`` /
``prctl`` / ``/proc/`` 字面量 / ``sys.platform`` 分支在 core/ 业务侧零存在，
唯此文件可写。

纯 stdlib：MUST NOT import 任何 core 模块（消费方向恒为 core.* → pal，
反向依赖会成环——proc_utils / fs_utils / systemd_hosting 等将转发至此）。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
平移对照表（add-platform-abstraction-layer 7.2 自检锚，接口 → 平移源 → 说明）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

A 进程生命周期
- TERM_GRACE_SECONDS            ← core/proc_utils.py:39（值 5 平移；proc_utils
                                  侧常量保留原位，3.1 转发化时对齐）
- spawn_detached                ← 新聚合接口：Popen 的 start_new_session 形态
                                  收敛点名（new_session=True ≡ 既有各 spawn
                                  位点的 start_new_session=True 字面；W5 消费
                                  端逐点迁移，动态 passthrough 经 new_session
                                  显式传参保 runner.py:7030 语义）
- run_detached                  ← 新聚合接口：subprocess.run 同参形态（run ≡
                                  spawn + communicate + wait，保留调用方既有
                                  CompletedProcess 消费形态）
- spawn_detached_async          ← 新聚合接口：asyncio.create_subprocess_exec/
                                  shell 的 start_new_session 形态（W5 cli_runner
                                  两处迁移；shell=True 形态传 str 命令）
- terminate_graceful            ← 新聚合接口：单进程 SIGTERM→wait(grace)→SIGKILL
                                  纪律（proc_utils.kill_process_group 为进程组
                                  形态单点，其时序语义独立保留）
- kill_tree                     ← core/proc_utils.py:331 guard_killpg 逐字平移
                                  （自保护守卫两拒绝分支 + ESRCH 静默；WARNING
                                  文案逐字节保留）；os.killpg 全库唯一位点随迁
                                  至此（tests/test_killpg_self_guard.py 的
                                  _GUARD_MODULE/_GUARD_LOGGER 簿记同 commit
                                  同步，语义断言零修改）
- bind_to_parent                ← core/dashboard/server.py:593-599 PDEATHSIG
                                  纪律平移（ctypes prctl(1, sig, 0, 0, 0)，
                                  != 0 按 errno 抛）；stderr 告警与 PPID==1 拒
                                  启动策略留消费端（server.py 平移链）

B 进程情报
- read_cmdline_raw / cmdline_argv ← 聚合既有各消费点的 /proc/<pid>/cmdline
                                  读面（raw bytes / NUL 切 token 两形态；
                                  decode("utf-8", "replace") 口径）
- proc_stat_fields              ← core/proc_utils.py:76 逐字平移（bytes 读 +
                                  rpartition(")") 尾段解析；dashboard/server
                                  侧 read_text+rindex 同义变体并入本单点，
                                  comm 畸形字节以 replace 解码为更防御口径，
                                  数值字段消费面行为不变）
- proc_start_ticks              ← core/proc_utils.py:119 逐字平移（fields[19]；
                                  dashboard/server._proc_starttime 同义并入）
- pid_alive_stat                ← core/proc_utils.py:98 逐字平移（zombie_is_dead
                                  显式选择 Z 态语义）
- pid_alive_signal              ← core/proc_utils.py:136 逐字平移（EPERM=存活）
- readlink_cwd                  ← 聚合 v2_dev_server._pid_cwd / locks 侧
                                  readlink 位点（OSError→None；空串＝僵尸态
                                  原样返回，调用方按各自语义处置）
- parent_comm                   ← 聚合 dashboard/server.py:416 comm 读面
                                  （bytes+replace 解码+strip；OSError→None）
- proc_dir_mtime                ← core/v2_dev_server.py:587 平移（/proc/<pid>
                                  目录 mtime＝启动时刻近似；OSError→None）
- read_procfile                 ← 新聚合原语：任意 /proc/<relpath> 字节读
                                  （杂项消费点如 /proc/self/* 经此；relpath
                                  校验禁 ".." 与绝对形态）
- process_environ               ← core/systemd_hosting.py:184 read_process_env
                                  逐字平移（_ENV_KEY_RE + 换行值过滤）
- find_port_owner               ← core/dashboard/server.py:208
                                  _find_dashboard_occupant 逐字平移（含
                                  v4/v6 地址匹配形态、len(parts)<10 护栏、
                                  探测异常 stderr 留痕；starttime 经
                                  proc_start_ticks 单点）
- listen_inodes_for_port        ← core/v2_dev_server.py:399 _listen_inode 逐字
                                  平移（收集全部 LISTEN inode 非首条）
- proc_socket_links             ← core/v2_dev_server.py:444-457 fd 扫描平移
                                  （单 fd OSError 就地跳过；目录整体不可读
                                  →None；重试窗策略留消费端）
- process_tree_cpu_seconds      ← core/agent_runner/maintenance_runs.py:3710
                                  agent_process_cpu_seconds 逐字平移（stat
                                  utime+stime + task/<tid>/children 进程树
                                  汇总 + SC_CLK_TCK 缺省 100.0；形参保持
                                  「.pid 句柄」形态）
- is_alive_with_identity        ← 新聚合三态接口（serving_registry
                                  _harvest_identity_ok 的「锚定命中/失配/
                                  无法核实」三态语义一般化；备选字典列表＝
                                  析取，字典内锚＝合取；start_ticks/cwd_real/
                                  cwd_prefix 三锚；读不到→None，消费端保守
                                  方向各自保留）

C 文件锁
- flock_exclusive / flock_release ← core/fs_utils.py:167/181 逐字平移（W1
                                  收敛原语上收单源；fs_utils 3.1 起转发）
- exclusive_lock / try_lock     ← 新具名形态：fs_utils.with_file_lock 的
                                  锁文件布局（``.<name>.lock``）+ 轮询节奏
                                  （50ms）+ 两因分类（EAGAIN/EACCES 重试、
                                  其他 errno→FileLockUnavailable、超时→
                                  FileLockBusy）同源表达，无回调形态出口

D 托管（systemctl 缝）
- systemctl_available           ← core/systemd_hosting.py:96 逐字平移
- run_systemctl                 ← core/systemd_hosting.py:101 _run_systemctl
                                  逐字平移（shutil.which 探测 + list argv
                                  subprocess.run；SystemdHostingError 家于
                                  api.py，systemd_hosting 3.1 起再导出）
- unit 渲染（render_project_unit / render_dashboard_unit）保留
  core.systemd_hosting：其 HOME 基线经 core.git_env 三级解析（env→pwd→
  配置）、PATH 基线为承载语义常量——迁入 pal 破坏纯 stdlib 约束；渲染是
  systemd 指令模板而非平台 syscall，SPEC 验收（渲染输出与现行逐字段一致、
  既有 test_systemd_hosting 断言零修改通过）不受归宿影响。

E 环境/用户/文件系统
- home_dir                      ← core/git_env.py:50 _resolve_home 前两级
                                  平移（env 非空 HOME → pwd.getpwuid().pw_dir；
                                  配置级属业务语义留 git_env）
- current_user                  ← 新接口（pwd.getpwuid(os.getuid()).pw_name，
                                  KeyError/OSError→None），E 组契约面
- ensure_link                   ← core/agent_runner/harness/claude_adapter.py:
                                  183 _ensure_symlinks 单链接纪律平移
                                  （lexists 判定 + 悬空 unlink 自愈 + 有效
                                  不重建；src 缺席→False 跳过；OSError 上抛，
                                  告警文案留消费端）
- fsync_dir                     ← core/fs_utils.py:118-124 原子写尾部目录
                                  fsync 纪律平移（O_RDONLY|O_DIRECTORY，
                                  失败静默；fs_utils.fsync_parent_dir 3.1 起
                                  薄委托，统一 O_DIRECTORY 口径）

F 测试基建
- pytest_timeout_method         ← pytest.ini ``timeout_method = signal`` 的
                                  平台化锚点（linux 恒 "signal"，行为不变）
"""

import asyncio
import ctypes
import errno
import fcntl
import logging
import os
import pwd
import re
import shutil
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import List, Optional

from core.platform.api import (
    FileLockBusy,
    FileLockUnavailable,
    SystemdHostingError,
)

_logger = logging.getLogger("fenixd.platform.linux")

# 平台谓词（业务代码平台分支的唯一合法替身；守卫禁 sys.platform/os.name 于
# core/ 业务侧，唯 core/platform/ 可写）
IS_WINDOWS = False


# ═══════════════════════════════════════════════════════════════════════
# A 进程生命周期
# ═══════════════════════════════════════════════════════════════════════

# kill_tree 序列的 SIGTERM 优雅退出宽限参照值（平移自 proc_utils.TERM_GRACE
# _SECONDS；进程组清扫时序单点 kill_process_group 仍居 proc_utils，取值由
# tests/test_serving_registry_kill_timing.py 钉住）
TERM_GRACE_SECONDS = 5


def spawn_detached(cmd, cwd=None, env=None, *, new_session: bool = True,
                   **popen_kwargs) -> subprocess.Popen:
    """Popen 的独立进程组形态收敛点名（W5 spawn 面单源）。

    ``new_session=True`` ≡ 既有 spawn 位点的 ``start_new_session=True``
    字面（子进程 setsid 独立成组，超时强杀可带全组）；``new_session=False``
    平移 runner.py:7030 的动态 passthrough 语义（无独立进程组、SIGTERM 直杀
    直接子进程）。其余 kwargs（stdin/stdout/stderr/text 等）原样透传 Popen。
    """
    return subprocess.Popen(cmd, cwd=cwd, env=env,
                            start_new_session=new_session, **popen_kwargs)


def run_detached(cmd, cwd=None, env=None, *, new_session: bool = True,
                 **run_kwargs) -> subprocess.CompletedProcess:
    """subprocess.run 的独立进程组形态（run ≡ spawn + communicate + wait）。

    为既有 ``subprocess.run(..., start_new_session=True)`` 位点提供同参形态
    的收敛点名：CompletedProcess 消费形态、timeout 语义（超时杀子进程后抛
    TimeoutExpired）、capture_output/text 等 kwargs 逐位保留。
    """
    return subprocess.run(cmd, cwd=cwd, env=env,
                          start_new_session=new_session, **run_kwargs)


async def spawn_detached_async(cmd, cwd=None, env=None, *, new_session: bool = True,
                               shell: bool = False, **kwargs):
    """asyncio 子进程的独立进程组形态（W5 cli_runner 异步位点单源）。

    ``shell=True`` 接受 str 命令走 ``create_subprocess_shell``；缺省按 argv
    list 走 ``create_subprocess_exec``。``new_session`` 透传 asyncio 的
    start_new_session 语义（独立进程组：超时强杀可带全组）。stdin/stdout/
    stderr 等 kwargs 原样透传。
    """
    if shell:
        return await asyncio.create_subprocess_shell(
            cmd, cwd=cwd, env=env, start_new_session=new_session, **kwargs)
    return await asyncio.create_subprocess_exec(
        *cmd, cwd=cwd, env=env, start_new_session=new_session, **kwargs)


def terminate_graceful(proc, grace_s: float = TERM_GRACE_SECONDS) -> None:
    """单进程 SIGTERM→wait(grace)→SIGKILL 优雅终止纪律。

    进程组形态的单点是 proc_utils.kill_process_group（组内孙进程收整组），
    本接口为其单进程兜底形态：terminate 后限时等待，逾期 kill 补刀；收尾
    （communicate 排空等）差异化留调用方。
    """
    proc.terminate()
    try:
        proc.wait(timeout=grace_s)
    except subprocess.TimeoutExpired:
        proc.kill()


def kill_tree(target_pid: int, sig: int, *, caller: str, resolve: bool = False) -> bool:
    """守卫版 killpg：拒绝把信号发往调用者自身所在进程组（add-killpg-self-guard）。

    2026-10-07 两起同构事故：测试替身 proc 的 pid 怪值（0 等）流入产品清场
    代码，``os.killpg`` 命中调用者自身所在进程组，整个测试套件/批回归被团灭
    （ftrace 取证发送者＝pytest 主进程自身）。本守卫在任何清场击杀路径的
    信号发出前做统一校验，一次性根治所有替身 pid 怪值变体（含未来新增的）。

    两种入参形态（调用点按手上句柄显式选择，code review 逐点核对）：

    - ``resolve=True``（解析型）：``target_pid`` 为**组内成员 pid**（通常是
      ``Popen.pid``），先 ``os.getpgid(target_pid)`` 解析 pgid；解析失败
      （ProcessLookupError/OSError ＝ 组已不存在/权限不可判）走既有静默
      语义返回 False——该分支语义逐位不变，守卫不新增行为；
    - ``resolve=False``（直传型）：``target_pid`` 为**独立成组组长 pid**
      （spawn 侧 start_new_session=True 下 pgid==pid）或调用点已解析的
      pgid，直接作 pgid 使用。

    两个拒绝分支（命中即不发信号、记 WARNING（含调用点标识与目标 pgid）、
    按「组已不存在」语义返回 False；调用方对 False MUST NOT 再降级单 pid
    ``os.kill``——``os.kill(0, sig)`` 经同样折算是调用者自身组广播）：

    1. 解析结果 == ``os.getpgid(0)``（调用者自身所在进程组）——替身 pid 怪值
       解析到宿主组的事故形态（解析型 ``getpgid(0)`` 也返回自身组，同一
       分支拦截）；
    2. ``pgid <= 0``（仅直传型可达）——``os.killpg(0, sig)`` 经
       ``kill(-pgid)`` 折算等价 ``kill(0, sig)``＝向调用者自身进程组广播，
       数值上 ``0 != os.getpgid(0)`` 挡不住；负值折算为对任意 pid 的误投递
       （如 ``killpg(-1)`` ≡ ``kill(1)``）。

    返回 True＝信号已发出；False＝守卫拒绝或组已不存在（ESRCH 语义），
    调用方一律按既有「组已不存在」路径静默返回，不改变控制流。

    本实现为 core/proc_utils.py guard_killpg 的逐字平移（W3 上收 pal 单源）；
    os.killpg 的全库唯一直调位点随迁至此。
    """
    if resolve:
        try:
            pgid = os.getpgid(target_pid)
        except (ProcessLookupError, OSError):
            return False  # 组已不存在：既有静默语义，逐位保持
    else:
        pgid = target_pid
    own_pgid = os.getpgid(0)  # pid 0 ＝ 调用者自身，恒可解析
    if pgid == own_pgid:
        _logger.warning(
            "killpg self-guard: caller=%s 目标组=调用者自身进程组 (pgid=%d)"
            " — 拒绝发信号，按组不存在静默返回",
            caller,
            pgid,
        )
        return False
    if pgid <= 0:
        _logger.warning(
            "killpg self-guard: caller=%s 非正 pgid=%d（killpg(0)/负值 经"
            " kill(-pgid) 折算等价自身组广播或误投递）— 拒绝发信号，按组"
            "不存在静默返回",
            caller,
            pgid,
        )
        return False
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, OSError):
        return False  # 组已不存在：既有静默语义，逐位保持
    return True


def bind_to_parent(sig: int = signal.SIGTERM) -> bool:
    """PR_SET_PDEATHSIG：父进程死亡时内核自动向本进程发 sig（泄漏即死）。

    平移自 dashboard/server.py _bind_parent_lifecycle 的 PDEATHSIG 纪律
    （PR_SET_PDEATHSIG = 1，linux/sched.h）。返回 True＝已设置；False＝
    非 Linux / libc 不可用 / prctl 失败——stderr 告警与「孤儿启动拒绝」
    等承载策略属消费端（server.py 平移链），不在本接口。
    """
    try:
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        # PR_SET_PDEATHSIG = 1（linux/sched.h）
        if libc.prctl(1, sig, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "prctl(PR_SET_PDEATHSIG) failed")
        return True
    except Exception:  # noqa: BLE001 — 非 Linux/libc 不可用按失败返回，策略留消费端
        return False


# ═══════════════════════════════════════════════════════════════════════
# B 进程情报
# ═══════════════════════════════════════════════════════════════════════

def _proc_path(pid, leaf: str = "") -> Path:
    """/proc/<pid>[/<leaf>] 路径构造（pid 纯数字校验防路径分段注入）。"""
    pid_str = str(int(pid))
    if pid_str != str(pid).strip() or int(pid) <= 0:
        raise ValueError(f"非法 pid：{pid!r}")
    return Path("/proc", pid_str, leaf)


def read_cmdline_raw(pid: int) -> Optional[bytes]:
    """/proc/<pid>/cmdline 原始字节（NUL 分隔）；读不到（已退出/权限）→ None。

    消费形态分化留调用方：NUL→空格拼接（dashboard 占用者 cmdline）、NUL 切
    token（v2/fenix_session 的 argv 结构判据）等各按既有口径。
    """
    try:
        return _proc_path(pid, "cmdline").read_bytes()
    except (OSError, ValueError):
        return None


def cmdline_argv(pid: int) -> Optional[List[str]]:
    """/proc/<pid>/cmdline 切 argv token（NUL 分隔、utf-8 replace 解码、空段丢弃）。

    读不到 → None（调用方按各自保守方向处置）。
    """
    raw = read_cmdline_raw(pid)
    if raw is None:
        return None
    return [a.decode("utf-8", "replace") for a in raw.split(b"\0") if a]


def proc_stat_fields(pid: int) -> Optional[List[str]]:
    """读取 /proc/<pid>/stat，返回最后一个 ')' 之后的字段列表（首项即字段 3 state）。

    comm 字段（第 2 项）可含空格与括号，须从**最后一个** ')' 之后切分才是
    真正的状态字段区——这是 stat 解析的经典陷阱，此处单点收口，供存活判定
    （pid_alive_stat）与身份快照（proc_start_ticks）共用，避免同款解析在
    各模块漂移。

    读取失败（/proc 缺失、权限不足、非 Linux 等 OSError）或内容无右括号
    （畸形）返回 None。
    """
    try:
        with _proc_path(pid, "stat").open("rb") as f:
            data = f.read().decode("utf-8", "replace")
    except (OSError, ValueError):
        return None
    _, sep, tail = data.rpartition(")")
    if not sep:
        return None
    return tail.split()


def proc_start_ticks(pid: int) -> Optional[int]:
    """/proc/<pid>/stat 的 starttime 字段（字段 22，系统启动后的 tick 数），读不到返回 None。

    pid + starttime 唯一确定一个进程实例：原进程退出后 pid 被系统复用时，
    新进程的 starttime 必然不同——以此锚定登记项的收割目标（对 exec/argv
    变化免疫，starttime 在 fork 时即固定），serving_registry 登记制据此
    做 pid 复用防误杀。
    """
    fields = proc_stat_fields(pid)
    if fields is None or len(fields) < 20:
        return None
    try:
        return int(fields[19])
    except ValueError:
        return None


def pid_alive_stat(pid: int, zombie_is_dead: bool = False) -> bool:
    """/proc stat 口径的存活判定；僵尸态语义由 zombie_is_dead 显式选择。

    两种口径各有场景理由，由调用点显式参数选择而非隐式共享：

    - zombie_is_dead=True（v2_dev_server 孤儿清扫）：孤儿 dev-server 的父
      进程（已死 daemon 的 shell 链）可能不收尸，/proc 条目以 Z 态残留，
      须按已终止计，否则误补 SIGKILL 且漏计清理数；
    - zombie_is_dead=False：/proc 条目可读即存活（含 Z 态），与 kill(pid, 0)
      口径（pid_alive_signal）的「有主即活」保守方向一致。

    stat 不可读（/proc 缺失、权限、畸形）按已终止计（宁可少杀）。
    """
    fields = proc_stat_fields(pid)
    if fields is None:
        return False
    if zombie_is_dead and fields[:1] == ["Z"]:
        return False
    return True


def pid_alive_signal(pid: int) -> bool:
    """kill(pid, 0) 存在性判定：命中即存活（不区分僵尸态，够用）。

    EPERM 恰恰证明目标进程存在、仅属其他用户（无权发信号）——按存活。
    """
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, ValueError):
        return False


def readlink_cwd(pid: int) -> Optional[str]:
    """/proc/<pid>/cwd 符号链接目标；读取失败/进程已消亡 → None。

    空串（僵尸态 readlink 成功但目标为空）**原样返回不折算**——realpath("")
    会落到调用者自身 cwd，构成身份误锚；调用方须按「无法核实」处置。
    """
    try:
        return os.readlink(str(_proc_path(pid, "cwd")))
    except (OSError, ValueError):
        return None


def parent_comm(pid: int) -> Optional[str]:
    """/proc/<pid>/comm（进程名，可经 PR_SET_NAME 写任意字节）strip 后文本。

    字节读 + replace 解码：严格解码的 UnicodeDecodeError（ValueError）会
    逃逸 OSError 处理器、违反「读取失败 → None」契约（dashboard 侧
    code-review 发现的陷阱平移）。读取失败 → None。
    """
    try:
        return _proc_path(pid, "comm").read_bytes().decode(
            "utf-8", "replace").strip()
    except (OSError, ValueError):
        return None


def proc_dir_mtime(pid: int) -> Optional[float]:
    """/proc/<pid> 目录 mtime＝该 PID 当前进程创建时刻（秒级近似）；读不到 → None。

    v2_dev_server 启动宽限豁免（新启进程本轮跳过）的时间锚。
    """
    try:
        return _proc_path(pid).stat().st_mtime
    except (OSError, ValueError):
        return None


def read_procfile(relpath: str) -> Optional[bytes]:
    """读 /proc/<relpath> 原始字节（杂项消费点单点：/proc/self/* 等）。

    relpath 为相对 /proc 的多段路径（如 "self/status"、"meminfo"）；
    ".." 段与绝对形态拒绝（None），读取失败 → None。
    """
    rel = str(relpath).strip().lstrip("/")
    if not rel or ".." in rel.split("/") or not rel:
        return None
    try:
        return Path("/proc", *rel.split("/")).read_bytes()
    except OSError:
        return None


# 合法 env 键名（/proc/<pid>/environ 可能含 bash 导出的函数键 `BASH_FUNC_…%%`
# 等，写入 EnvironmentFile 会被 systemd 拒绝整行解析，跳过）。平移自
# systemd_hosting._ENV_KEY_RE（候选稿过滤同用此单点，3.1 起转发）。
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def process_environ(pid: int) -> dict:
    """读 /proc/<pid>/environ 为 dict（不可读/已退出 → 空 dict）。

    键集来源为在跑进程的实环境（design R1：非白名单凭记忆——漏掉 load-bearing
    键会让迁移后 agent run 全灭）。非法键名/含换行的值（bash 导出函数等）跳过：
    EnvironmentFile 行格式装不下，整行会被 systemd 拒解析。

    平移自 core.systemd_hosting.read_process_env（W3 D/B 组上收单源）。
    """
    try:
        raw = _proc_path(int(pid), "environ").read_bytes()
    except (OSError, ValueError):
        return {}
    env = {}
    for chunk in raw.split(b"\0"):
        if not chunk:
            continue
        key, sep, value = chunk.decode("utf-8", "replace").partition("=")
        if not sep or not _ENV_KEY_RE.match(key):
            continue
        if "\n" in value or "\r" in value:
            continue
        env[key] = value
    return env


def find_port_owner(port: int) -> Optional[dict]:
    """定位占用目标端口的进程。

    返回 {"pid": int, "cmdline": str, "starttime": int|None} 或 None
    （无占用 / 无法判定）。

    判定（inode 映射，避免 /proc/<pid>/net/tcp 按网络命名空间而非进程返回错误 PID）：
    1. 读 /proc/net/tcp（及 /proc/net/tcp6）找到监听目标端口的 socket inode，
       地址匹配 127.0.0.1 / 0.0.0.0 通配（IPv4）与 :: 通配 / ::1（IPv6）
       （code-review item 9df14cc4442f）；
    2. 遍历 /proc/<pid>/fd/* 软链接，匹配 socket:[inode] 得到真正持有该
       端口的 PID；
    3. 读取该进程 cmdline。

    平移自 core/dashboard/server.py _find_dashboard_occupant（含探测异常
    stderr 留痕与「匹配不上即不接管」保守语义）；starttime 经
    proc_start_ticks 单点（接管方 kill 前据此复核进程身份，防「查询后目标
    死亡、PID 被复用」误杀，code-review item 5612e191a8f5）。
    """
    try:
        port_hex = f"{port & 0xffff:04X}"
        # 匹配形态放宽（code-review item 9df14cc4442f）：bind 127.0.0.1:port 对
        # 0.0.0.0 通配、IPv6 通配（::）或 ::1 上的监听同样 EADDRINUSE，旧实现
        # 只扫 IPv4 表 /proc/net/tcp 且仅认 0100007F，此时定位不到占用者、
        # serve() 只能报「未知进程（PID ?）」。现补充扫描 /proc/net/tcp6（禁用
        # IPv6 的机器上该文件不存在，按无此表跳过）；IPv6 地址列 32 hex、按
        # 32 位字小端打印，通配 :: 为全零、::1 为 …01000000。匹配不上仍返回
        # None——「匹配不上即不接管」的保守语义不变。
        v4_addrs = ("0100007F", "00000000")  # 127.0.0.1 / 0.0.0.0 通配
        v6_addrs = (
            "0" * 32,  # :: 通配
            "00000000000000000000000001000000",  # ::1
        )
        inode = None
        for net_table, listen_addrs in (
            (Path("/proc/net/tcp"), v4_addrs),
            (Path("/proc/net/tcp6"), v6_addrs),
        ):
            if not net_table.exists():
                continue
            for line in net_table.read_text(
                encoding="utf-8", errors="replace"
            ).split("\n")[1:]:
                parts = line.split()
                # 字段数护栏按实际取用下标（inode 是第 10 列）判定（code-review item
                # aaf3f304a0de）：旧实现只查 `len(parts) < 4`，而下方读 `parts[9]`——
                # 4~9 个字段的截断/畸形行会抛 IndexError，被外层 `except Exception:
                # return None` 吞掉，使「解析失败」与「无占用者」不可区分；调用方据此
                # 打印误导性的「未知进程」并非 0 退出，而不是接管陈旧 dashboard 实例。
                if len(parts) < 10:
                    continue
                local = parts[1]
                state = parts[3]
                if state != "0A":  # 0A = LISTEN
                    continue
                if ":" not in local:
                    continue
                addr, p = local.split(":", 1)
                if p.upper() == port_hex and addr.upper() in listen_addrs:
                    inode = parts[9]
                    break
            if inode:
                break
        if not inode:
            return None
        # 通过 /proc/<pid>/fd 软链接匹配 inode → 真正持有端口的 PID
        for pid_dir in Path("/proc").glob("[0-9]*"):
            fd_dir = pid_dir / "fd"
            if not fd_dir.is_dir():
                continue
            try:
                for link in fd_dir.iterdir():
                    try:
                        target = os.readlink(str(link))
                    except OSError:
                        continue
                    if target == f"socket:[{inode}]":
                        try:
                            raw = (pid_dir / "cmdline").read_bytes()
                            cmdline = raw.replace(b"\x00", b" ").decode("utf-8", "replace").strip()
                        except OSError:
                            cmdline = ""
                        pid = int(pid_dir.name)
                        return {"pid": pid, "cmdline": cmdline,
                                "starttime": proc_start_ticks(pid)}
            except OSError:
                continue
    except Exception as e:  # noqa: BLE001 — 探测失败≠无占用者，兜底 None 保行为
        # 探测失败≠无占用者（code-review item 532de62ce081）：兜底仍返回 None
        # 保持行为不变，但写一行 stderr 留痕，与「端口确实空闲」区分，便于排查。
        sys.stderr.write(f"dashboard 端口占用者探测异常（按无占用者处理）: {e}\n")
        return None
    return None


def listen_inodes_for_port(port: int) -> List[str]:
    """取 port 当前全部 LISTEN socket 的 inode（/proc/net/tcp[6]；无则空表）。

    /proc/net/tcp 固定布局：local_address 形如 0100007F:4A38（IP:十六进制
    端口）、第 4 列 st=0A 即 LISTEN、第 10 列为 socket inode。收集该端口
    全部 LISTEN 条目而非首条：wildcard（00000000/::）与具体地址（如
    0100007F）可被不同进程同时 LISTEN 同一端口，只取首条可能命中他方
    socket 的 inode，导致身份收口误判。

    平移自 core/v2_dev_server.py _listen_inode。
    """
    inodes: List[str] = []
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            rows = Path(table).read_text().splitlines()[1:]
        except OSError:
            continue
        for row in rows:
            fields = row.split()
            try:
                if fields[3] == "0A" and int(fields[1].rsplit(":", 1)[1], 16) == port:
                    inodes.append(fields[9])
            except (IndexError, ValueError):
                continue
    return inodes


def proc_socket_links(pid: int) -> Optional[List[str]]:
    """/proc/<pid>/fd/* 全部软链接目标（socket:[inode] 等形态混含）。

    单个 fd 可能在遍历间隙被对端关闭（readlink 落 ENOENT）：跳过该 fd 继续
    扫余项；procfs 目录整体不可读 → None（调用方按「本轮放弃」处置，交由
    各自重试窗兜底）。平移自 v2_dev_server._port_listened_by 的扫描内层。
    """
    try:
        fd_dir = _proc_path(pid, "fd")
        links: List[str] = []
        for fd in fd_dir.iterdir():
            try:
                links.append(os.readlink(str(fd)))
            except OSError:
                continue
        return links
    except (OSError, ValueError):
        return None


def process_tree_cpu_seconds(proc) -> Optional[float]:
    """run 子进程进程树的累计 CPU 时间（秒），不可解析返回 None。

    decouple-codefix-review-lanes 看门狗判据 2（design D2）：网络僵死的 run
    表现为「进程活着但 CPU 停止增长」（09-24 事故：2h20m 仅 49s CPU），单
    mtime 判据会被这种形态欺骗，故看门狗以 mtime + CPU 双判据同时无进展
    才判定停滞。读 /proc/<pid>/stat 的 utime+stime（含其后代进程树——审查
    run 的 scan 子进程经 execvp 后以 node/ocr 形态挂在 CLI 子进程下，只看
    顶层 pid 会漏掉真实负载）；任一环节不可解析（进程已退出 / 非 Linux /
    权限不足）返回 None，调用方按 fail-open 不触发（看门狗宁可漏杀不可误杀，
    且无进程句柄时 cancel_run 也无从终止）。

    ``proc`` 为 subprocess.Popen 或等价句柄（只需 .pid 属性）；子进程遍历用
    内核提供的 /proc/<pid>/task/<tid>/children（比全表扫 /proc 匹配 ppid 便宜
    且无「孙进程在遍历间隙被收养」的误判面）。

    平移自 core/agent_runner/maintenance_runs.py agent_process_cpu_seconds。
    """
    pid = getattr(proc, "pid", None)
    if not pid or pid <= 0:
        return None
    ticks = 0.0
    read_any = False
    seen: set = set()
    queue = [int(pid)]
    try:
        clk_tck = os.sysconf("SC_CLK_TCK")
    except (ValueError, OSError, AttributeError):
        clk_tck = 100.0
    if not clk_tck:
        clk_tck = 100.0
    while queue:
        cur = queue.pop()
        if cur in seen:
            continue
        seen.add(cur)
        try:
            with open(f"/proc/{cur}/stat", "rb") as f:
                stat = f.read()
        except OSError:
            continue
        # stat 的 comm 字段可含空格/括号，以最后一个 ')' 切开取其后字段
        rparen = stat.rfind(b")")
        if rparen < 0:
            continue
        fields = stat[rparen + 2 :].split()
        # fields[11]=utime fields[12]=stime（14th/15th 列，state 从 fields[0] 起）
        if len(fields) < 13:
            continue
        try:
            ticks += int(fields[11]) + int(fields[12])
        except ValueError:
            continue
        read_any = True
        # 逐线程 children 汇总（同 pid 多线程时 children 记录在各 task 下）
        try:
            for tid_dir in os.scandir(f"/proc/{cur}/task"):
                try:
                    with open(f"/proc/{cur}/task/{tid_dir.name}/children", "rb") as f:
                        queue.extend(int(x) for x in f.read().split())
                except (OSError, ValueError):
                    continue
        except OSError:
            continue
    if not read_any:
        # 顶层 pid 就读不到（已退出/权限）→ 判据不可用，调用方 fail-open
        return None
    return ticks / clk_tck


# is_alive_with_identity 的合法锚键（未知锚键拒绝——锚定接口的静默漏锚会
# 把「应锚定」悄悄降级为无条件探活）
_IDENTITY_ANCHOR_KEYS = ("start_ticks", "cwd_real", "cwd_prefix")


def is_alive_with_identity(pid: int, identity) -> Optional[bool]:
    """身份锚定探活，fail-closed 三态：True＝锚定命中 / False＝失配 / None＝无法核实。

    ``identity`` 为锚定字典或其列表（列表＝备选析取，任一备选命中即 True；
    单字典即单锚合取）。合法锚键：

    - ``start_ticks``：/proc stat starttime 等值（pid 复用防护，对 exec/argv
      变化免疫）；
    - ``cwd_real``：cwd 经 realpath 归一后全等（消解符号链接/挂载拼写差异）；
    - ``cwd_prefix``：cwd realpath 位于该目录之下（前缀按目录边界
      ``+ os.sep`` 匹配，防同前缀更长目录名误归属——locks 侧
      worktrees-backup/ 先例）。

    三态语义（平移 serving_registry._harvest_identity_ok 的一般化）：备选内
    任一锚确定性失配 → 该备选 False；锚底层读面不可得（进程已退出、/proc
    不可读、僵尸态空 cwd）→ 该备选 None（无法核实）；全备选 False 且存在
    None → None；全备选 False 且无 None → False；任一备选 True → True。
    调用方对 None 按各自保守方向处置（登记制→视存活、清扫→跳过等），
    本接口不代选。
    """
    alternatives = [identity] if isinstance(identity, dict) else list(identity)
    if not alternatives:
        raise ValueError("identity 须为至少一个锚定字典（或其非空列表）")
    pid = int(pid)
    any_unknown = False
    for alt in alternatives:
        if not isinstance(alt, dict):
            raise ValueError(f"锚定备选须为 dict：{alt!r}")
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
            return None  # 读不到（已退出/权限）→ 无法核实
        if got != int(want):
            return False  # 确定性失配：starttime 在 fork 时固定，不等即换进程
    if "cwd_real" in alt or "cwd_prefix" in alt:
        link = readlink_cwd(pid)
        if not link:
            return None  # 空串（僵尸态）或读不到 → 无法核实（realpath("") 会
            # 落到调用者自身 cwd，绝不可折算，防身份误锚）
        cwd_real = os.path.realpath(link)
        if "cwd_real" in alt and cwd_real != os.path.realpath(str(alt["cwd_real"])):
            return False
        if "cwd_prefix" in alt:
            base_real = os.path.realpath(str(alt["cwd_prefix"]))
            if cwd_real != base_real and not cwd_real.startswith(base_real + os.sep):
                return False
    return True


# ═══════════════════════════════════════════════════════════════════════
# C 文件锁
# ═══════════════════════════════════════════════════════════════════════

def flock_exclusive(fileobj, *, nonblocking: bool = False) -> None:
    """对已打开的锁文件做单次 ``LOCK_EX``（nonblocking 时 | ``LOCK_NB``）flock。

    core/ 全部 flock syscall 的单源原语（C 组，平移自 fs_utils 同名原语）：
    需要自持 fd 管理锁生命周期的消费点各自保留既有轮询节奏 / errno 分类 /
    降级策略，syscall 调用收口于此。fileobj 接受文件对象或 fd（fcntl.flock
    两种形态均接受）。失败抛 OSError，errno 原样上抛。
    """
    flags = fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0)
    fcntl.flock(fileobj, flags)


def flock_release(fileobj) -> None:
    """``LOCK_UN`` 释放（close 亦隐式释放；失败处理策略归调用方，原样上抛）。"""
    fcntl.flock(fileobj, fcntl.LOCK_UN)


@contextmanager
def _lock_handle(lock_f):
    """持锁句柄：yield 锁内区间，退出时 LOCK_UN + close（与 with_file_lock 同纪律）。"""
    try:
        yield lock_f
    finally:
        flock_release(lock_f)
        lock_f.close()


def _open_companion_lock(path: Path):
    """``.<name>.lock`` 伴生锁文件打开（布局与 fs_utils.with_file_lock 同源）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return open(path.parent / f".{path.name}.lock", "w")


def try_lock(path):
    """单次 ``LOCK_EX | LOCK_NB`` 抢伴生锁；成功返回持锁句柄，他方持锁返回 None。

    fail-fast 形态出口（无轮询）：仅「锁被占」类 errno（EAGAIN/EACCES）→
    None；flock 本身不可用（特殊文件系统等其余 errno）→ 抛
    ``FileLockUnavailable``。用法::

        lock = pal.try_lock(path)
        if lock is None:
            ...  # 他方持锁降级路径
            return
        with lock:
            ...  # 锁内区间
    """
    lock_f = _open_companion_lock(path)
    try:
        flock_exclusive(lock_f, nonblocking=True)
    except OSError as e:
        lock_f.close()
        if e.errno in (errno.EACCES, errno.EAGAIN):
            return None
        raise FileLockUnavailable(f"文件系统不支持 flock（errno={e.errno}）") from e
    except BaseException:
        lock_f.close()
        raise
    return _lock_handle(lock_f)


def exclusive_lock(path, timeout_s: Optional[float] = None):
    """``LOCK_EX`` 抢伴生锁；``timeout_s=None`` 无限阻塞（现行缺省语义），有限值限时轮询。

    锁文件布局 / 轮询节奏（50ms）/ 两因分类与 fs_utils.with_file_lock 同源：
    仅 EAGAIN/EACCES 值得重试，其余 errno 立即抛 ``FileLockUnavailable``；
    限时未抢到抛 ``FileLockBusy``。成功返回持锁句柄（用法同 try_lock）。
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
                    if e.errno not in (errno.EACCES, errno.EAGAIN):
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
# D 托管（systemctl 缝）
# ═══════════════════════════════════════════════════════════════════════

def systemctl_available() -> bool:
    """systemctl 是否可执行（非 systemd 环境 → False，调用方拒绝并给可读错误）。"""
    return shutil.which("systemctl") is not None


def run_systemctl(args, timeout: float = 30) -> subprocess.CompletedProcess:
    """systemctl 调用单缝（subprocess.run，list argv 不经 shell）。

    systemctl 不可用时抛 SystemdHostingError（可读错误含「需要 systemd」指引），
    由调用方转成各自的错误返回形态（fenix_session 返回 dict，hook 记 failure）。

    平移自 core/systemd_hosting.py _run_systemctl（W3 D 组上收单源）。
    """
    if not systemctl_available():
        raise SystemdHostingError(
            "需要 systemd：systemctl 不可用（非 systemd 环境？）。"
            "fenixd 托管链已迁移 systemd unit 承载（tmux 路径退役），"
            "请在 systemd 环境运行或人工以旧配方恢复。"
        )
    try:
        return subprocess.run(
            ["systemctl", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.SubprocessError, OSError) as e:
        raise SystemdHostingError(f"systemctl {' '.join(args)} 执行失败: {e}") from e


# ═══════════════════════════════════════════════════════════════════════
# E 环境/用户/文件系统
# ═══════════════════════════════════════════════════════════════════════

def home_dir(env: Optional[dict] = None) -> Optional[str]:
    """HOME 两级解析：进程 env 非空 ``HOME`` → ``pwd.getpwuid(uid).pw_dir``。

    平移自 core/git_env.py _resolve_home 前两级（级内异常 fail-open 落下一
    级；三级解析中的配置覆盖级属业务语义，留 git_env 单点）。两级皆空返回
    None。``~`` 形态的展开由调用方按既有口径处理（git_env 侧 expanduser）。
    """
    if env is None:
        env = os.environ
    home = env.get("HOME")
    if isinstance(home, str) and home.strip():
        return home
    try:
        pw_dir = pwd.getpwuid(os.getuid()).pw_dir
        if isinstance(pw_dir, str) and pw_dir.strip():
            return pw_dir
    except (KeyError, OSError):
        # pwd 数据库无当前 uid 条目（极端容器环境）：两级皆空 → None
        pass
    return None


def current_user() -> Optional[str]:
    """当前 uid 的用户名（pwd.getpwuid().pw_name）；解析失败 → None。"""
    try:
        return pwd.getpwuid(os.getuid()).pw_name
    except (KeyError, OSError):
        return None


def ensure_link(src, dst) -> bool:
    """symlink 幂等补建（悬空自愈）；返回是否在位，OSError 上抛。

    纪律平移自 claude_adapter._ensure_symlinks 单链接形态：

    - 源缺席 → 返回 False（优雅降级，调用方跳过不告警）；
    - 存在性判定用 lexists（不跟随链接）：悬空 symlink（指向已清理的目标）
      的 exists() 返回 False，但路径项仍在，symlink_to 会抛 FileExistsError
      ——先 unlink 摘除旧链接项再重建，自愈语义才对悬空形态生效；
    - 有效链接或真实目录已在 → 返回 True（不重建）；
    - 建链失败 OSError 原样上抛（告警文案与降级策略留消费端）。

    目录链接（target_is_directory=True）语义固定平移。
    """
    src = Path(src)
    dst = Path(dst)
    if not src.is_dir():
        return False
    if os.path.lexists(dst):
        if dst.is_symlink() and not dst.exists():
            dst.unlink()
        else:
            # 有效链接或真实目录已在，不重建
            return True
    dst.symlink_to(src, target_is_directory=True)
    return True


def fsync_dir(path) -> None:
    """目录项 fsync 纪律（rename 后掉电持久化保证；尽力而为，失败静默）。

    平移自 fs_utils.atomic_write_text 尾部内联纪律（O_RDONLY|O_DIRECTORY
    口径）：临时文件 fsync 只保证文件内容落盘，rename 的目录项变更是否持久
    化取决于父目录是否刷盘。目录 fsync 在个别文件系统上不支持或失败
    （EINVAL 等），静默忽略，此时仍保留进程级崩溃安全保证。
    """
    try:
        dir_fd = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


# ═══════════════════════════════════════════════════════════════════════
# F 测试基建
# ═══════════════════════════════════════════════════════════════════════

def pytest_timeout_method() -> str:
    """pytest-timeout 超时机制的平台锚点：Linux 恒 ``"signal"``（现行不变）。

    pytest.ini 的 ``timeout_method`` 平台拆分（6.2）以此为准；win32 后端
    （SPEC-2）须换 ``"thread"``（Windows 无 SIGALRM）。
    """
    return "signal"


__all__ = [
    "IS_WINDOWS",
    "TERM_GRACE_SECONDS",
    "FileLockBusy",
    "FileLockUnavailable",
    "SystemdHostingError",
    # A
    "spawn_detached",
    "run_detached",
    "spawn_detached_async",
    "terminate_graceful",
    "kill_tree",
    "bind_to_parent",
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
    "process_environ",
    "find_port_owner",
    "listen_inodes_for_port",
    "proc_socket_links",
    "process_tree_cpu_seconds",
    "is_alive_with_identity",
    # C
    "flock_exclusive",
    "flock_release",
    "exclusive_lock",
    "try_lock",
    # D
    "systemctl_available",
    "run_systemctl",
    # E
    "home_dir",
    "current_user",
    "ensure_link",
    "fsync_dir",
    # F
    "pytest_timeout_method",
]
