"""proc_utils.py — 进程/端口判定的公共助手（verify-process-lifecycle D4/D5）。

从 worktree_manager（_is_claude_process）与 verify_contract（_find_free_port）
上移共用的无状态判定函数，避免模块间循环依赖：

- ``is_claude_process``：进程 argv[0] 是否为 claude agent（存活判定与清扫豁免锚点）；
- ``proc_stat_fields``：/proc/<pid>/stat 尾段单点解析（comm 可含括号与空格的陷阱在此收口）；
- ``pid_alive_stat``：/proc stat 口径存活判定，僵尸态语义由 zombie_is_dead 显式选择；
- ``proc_start_ticks``：starttime 身份快照（pid 复用防护锚点）；
- ``pid_alive_signal``：kill(pid, 0) 存在性判定（不区分僵尸态）；
- ``find_free_port``：向系统申请一个临时空闲端口（bind 0 + getsockname）；
- ``find_bound_socket``：保留已绑定 socket 的 contextmanager（消除 TOCTOU 竞态窗口，
  concurrent-suite-isolation 4.1），绑定失败时按可重试策略重取；
- ``kill_process_group``：start_new_session 进程组清扫纪律的单点实现
  （SIGTERM 整组 → wait 宽限 → SIGKILL 补刀；可选探活口径组清空免补刀），
  收尸等差异化收尾留调用方；
- ``guard_killpg``：清场击杀自保护守卫（add-killpg-self-guard）——目标组为
  调用者自身所在进程组、或非正 pgid 时拒绝发信号，按「组已不存在」静默降级。

以下助手均只依赖 stdlib，任何 core 模块均可安全导入。
"""

import logging
import os
import signal
import socket
import subprocess
import time
from contextlib import contextmanager
from typing import List, Optional

_logger = logging.getLogger("fenixd.proc_utils")


def is_claude_process(pid_str: str) -> bool:
    """进程 argv[0] 是否为 claude agent 可执行文件（basename claude / claude.exe）。

    存活判定与残留清扫都以「agent 进程」为锚：implementer 起的测试子进程
    （v2 dev-server 等）cmdline 同样携带 worktree 路径，若按路径匹配会把
    agent 退出后的永生孤儿误判为持锁者（add-fast-track-mode 派发死锁，
    2026-09-02）。清扫豁免（worktree_manager._kill_worktree_strays 与
    v2_dev_server._worktree_has_live_referencing_process）共用此判定。
    """
    # add-harness-adapter-layer 5.1：识别名集合经 current adapter
    # （process_patterns，claude 值与原字面量 ("claude", "claude.exe") 全等）。
    # 函数内延迟解析：core.agent_runner 包初始化即拉入 runner 重链，本模块是
    # 纯工具层不可成为其导入下游（harness.one_shot 的 guard_killpg 反向 lazy
    # import 同此理由）。
    from core.agent_runner.harness import current_process_patterns

    try:
        with open(f"/proc/{pid_str}/cmdline", "rb") as f:
            argv0 = f.read().split(b"\0", 1)[0]
        return os.path.basename(argv0.decode("utf-8", "replace")) in tuple(
            current_process_patterns()
        )
    except (OSError, IndexError):
        return False


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
        with open(f"/proc/{pid}/stat", "rb") as f:
            data = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    _, sep, tail = data.rpartition(")")
    if not sep:
        return None
    return tail.split()


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


def pid_alive_signal(pid: int) -> bool:
    """kill(pid, 0) 存在性判定：命中即存活（不区分僵尸态，够用）。

    EPERM 恰恰证明目标进程存在、仅属其他用户（无权发信号）——按存活，
    与 kill_process_group 对 getpgid EPERM 的显式处理同口径。
    """
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def find_free_port() -> int:
    """向系统申请一个临时空闲端口（探测即释放，向后兼容现有调用方）。"""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _bind_retry(host: str = "127.0.0.1", retries: int = 3) -> socket.socket:
    """尝试 bind 0 端口（OS 分配），绑定失败时重试（消除 TOCTOU）。"""
    last_err = None
    s = None
    attempts = max(1, retries)
    for i in range(attempts):
        try:
            s = socket.socket()
            s.bind((host, 0))
            return s
        except OSError as e:
            # bind 失败时显式释放已创建的 socket（与 find_bound_socket 的
            # 释放纪律对齐；非引用计数实现下避免 fd 积累）
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass
                s = None
            last_err = e
            if i < attempts - 1:
                time.sleep(0.05)
    raise last_err  # type: ignore[misc]


@contextmanager
def find_bound_socket(host: str = "127.0.0.1", retries: int = 3):
    """保留已绑定 socket 的 contextmanager（concurrent-suite-isolation 4.1）。

    退出时释放 socket（无条件关闭）。绑定失败时按可重试策略重取（最多 retries
    次，间隔 50ms），彻底消除「探测到的端口被他人抢占」的 TOCTOU 窗口。

    Usage::

        with find_bound_socket() as s:
            port = s.getsockname()[1]
            # port 在 contextmanager 存活期间被持有
            run_server(port)
        # 退出时 socket 被释放

    既有的 ``find_free_port()`` API 不变（返回 int，立即释放）；当前仓库内
    消费方为测试入口（tests/test_port_allocation.py），套件入口
    （bin/run_full_suite.py）暂经 FENIX_SUITE_PORT_BASE 端口段约定分配，
    尚未接入本函数。
    """
    s = _bind_retry(host, retries)
    try:
        yield s
    finally:
        try:
            s.close()
        except OSError:
            pass


def hold_free_port(host: str = "127.0.0.1", retries: int = 3) -> socket.socket:
    """返回一个已绑定匿名端口的占位 socket（调用方持有至 spawn 前再关闭）。

    ``find_free_port`` 探测即释放，「探测 → 实际使用」之间存在 TOCTOU 窗口，
    端口可被并发进程抢占；本助手返回的 socket 在被关闭前一直占住该端口，
    把「分配端口 → 子进程绑定」之间的空窗压缩到 close→spawn 一瞬
    （code-review item eb7fb0c8d239）。适用于进程为任意命令、无法经 fd
    移交继承绑定的场景；可直接移交 socket 的场景用 ``find_bound_socket``。

    Usage::

        holder = hold_free_port()
        port = holder.getsockname()[1]
        ...  # 准备命令行/预检等耗时步骤，端口始终被占住
        holder.close()
        spawn(cmd_with_port)
    """
    return _bind_retry(host, retries)


def kill_process_group(
    popen: "subprocess.Popen",
    term_grace: float = 5,
    sigterm_only_if_alive: bool = False,
    sigkill_only_if_group_alive: bool = False,
    caller: str = "proc_utils.kill_process_group",
) -> None:
    """start_new_session 进程组清扫纪律的单点实现（SIGTERM→wait→SIGKILL 补刀）。

    subprocess.run/Popen 的超时处理只 kill 直接子进程；shell 包装命令（npm 等）
    收到 SIGTERM 即退时，忽略 SIGTERM 的孙进程（npm 派生的 node）仍残留组内
    继续写产物目录，须按进程组收整组。该纪律此前在 verify_contract 四处逐字
    复刻（prepare 步骤超时、validate_contract finally 的 proc 兜底、
    CommandVerifyServer.stop、_run_npm_provision 超时），任一处修订都需同步
    四处、历史上已多次多点修复（item 7168a8391e06/2c7a3051bb99/
    020ba8771283）——收口为单一实现（code-review item 21d8a42c21c1）；
    item b090579ac5a0 把 regression 车道的「探活后补刀」变体并入本单点。

    时序（与收口前四处逐字等价）：

    1. pgid 提前取定（start_new_session=True 下即 popen.pid）——wait 回收
       leader 后 getpgid 将失效，补刀须用此句柄；取不到回退 popen.pid；
    2. SIGTERM 整组留优雅退出机会（``sigterm_only_if_alive=True`` 时仅
       leader 尚存活才发——validate_contract finally 的 proc 兜底口径）；
    3. wait(term_grace) 等优雅退出（leader 已被回收则立即返回）；
    4. （仅 ``sigkill_only_if_group_alive=True``）探活整组再决定补刀：
       经守卫单点执行跳发信号 0（不投递、纯存在性检查），组已清空即免
       补刀收口；不以直接子进程是否在窗口内退出为前提（regression 车道
       item 72a90eb6cb2e 的既有口径）。配合该口径，SIGTERM 守卫拒绝
       （＝「组已不存在」语义）时提前收口——后续探活只会得到同一拒绝/
       ESRCH。缺省 False＝无条件补刀，既有调用方语义逐位不变；
    5. 无论 wait 成败都补一次组 SIGKILL；ProcessLookupError＝组已清空，
       静默即可。

    ``caller``：守卫告警中的调用点标识，缺省即本函数名；收口适配器（如
    regression._kill_process_group）传回自身标识，保留守卫 WARNING 的
    取证锚点。

    收尸（SIGKILL 补刀后的收尾）不在本助手内：PIPE 的 communicate 管道排空
    与 DEVNULL 的 wait(timeout=2)、boot.log 句柄关闭是调用方差异化收尾，
    留在调用方。
    """
    try:
        pgid = os.getpgid(popen.pid)
    except ProcessLookupError:
        # leader pid 已被 reap。ESRCH 只证明 pid 空闲，组内孤儿仍可能存活，
        # 故按 start_new_session 口径回退 popen.pid 补刀（语义不变）；但记
        # WARNING 留取证线索——若该 pid 在 reap 后被 OS 复用且新进程独立成
        # 组，killpg 会误杀无关组（guard_killpg 只拦自身组与非正 pgid）。
        _logger.warning(
            "kill_process_group: getpgid(%d) ProcessLookupError（leader 已被"
            " reap），回退 pgid=pid 补刀整组 — 存在 pid 复用误杀他人组的极窄"
            "窗口",
            popen.pid,
        )
        pgid = popen.pid
    except (PermissionError, OSError):
        # 权限不可判等情形：目标大概率仍在，回退口径同上。
        pgid = popen.pid
    if not (sigterm_only_if_alive and popen.poll() is not None):
        # 击杀最后一跳经自保护守卫（add-killpg-self-guard）：pgid 已提前取定
        # 直传（resolve=False）；守卫拒绝（自身组/非正 pgid）与组已不存在
        # 同样静默，序列语义不变。
        term_sent = guard_killpg(pgid, signal.SIGTERM, caller=caller, resolve=False)
        try:
            popen.wait(timeout=term_grace)
        except Exception:
            pass
        if not term_sent and sigkill_only_if_group_alive:
            # 探活口径专用提前收口：守卫拒绝＝「组已不存在」语义（含替身
            # 怪值命中自身组），补刀无事可做。仅探活口径返回；缺省口径
            # 保持既有序列（SIGKILL 守卫同样拒绝、静默）逐位不变。
            return
    if sigkill_only_if_group_alive and not guard_killpg(
        pgid, 0, caller=caller, resolve=False
    ):
        # 探活后补刀（item b090579ac5a0）：信号 0 不投递，经守卫单点执行跳
        # 做整组存在性检查——组已清空（SIGTERM 已清干净）即免补刀；仍有
        # 成员（忽略 SIGTERM 的孙进程：自守护的测试 runner、xdist worker
        # 残留）才落到下方 SIGKILL。探活不以直接子进程是否在窗口内退出为
        # 前提（item 72a90eb6cb2e 语义保持）。到此处 pgid 已被 SIGTERM 守卫
        # 放行（非自身组、非正），探活至多落 ESRCH 静默 False。
        return
    guard_killpg(pgid, signal.SIGKILL, caller=caller, resolve=False)


def guard_killpg(target_pid: int, sig: int, *, caller: str, resolve: bool = False) -> bool:
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
