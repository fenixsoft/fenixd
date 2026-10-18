"""harness/one_shot.py — 一次性 spawn 收编入口（add-harness-adapter-layer 4.1）。

五处一次性 spawn 点（监督 judge / 知识蒸馏 / 知识回填 / 架构图 autodraft /
项目简介）与告警叙事通道的「构造命令 + Popen + stdin 载荷 + 定时收割 +
进程组清场」共性收编为一个入口；各自的 CLI 参数形态差异（judge 走
``--output-format json``、autodraft/describe 走 argv 传 prompt、蒸馏/回填/
叙事走 stdin 传 prompt）全部是 :class:`~core.agent_runner.harness.protocol.
SpawnRequest` 字段——lane 语义数据化（design D6），换 harness 只换 adapter。

超时清场语义（与既有各点一致）：超时先 SIGTERM 整个进程组、宽限
``terminate_grace_seconds`` 后 SIGKILL 整组，再 communicate() 收割——对应
knowledge._kill_process_group / liveness guard_killpg(SIGTERM→SIGKILL) 的
既有两段式；start_new_session 保证 pgid == 子进程 pid，孙进程随组收割。

依赖方向（design D8）：只依赖 stdlib 与本包 protocol，MUST NOT import
runner/event_bus/admin_monitor。
"""

from __future__ import annotations

import contextlib
import signal
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Optional

from core.agent_runner.harness.protocol import (
    PROMPT_TRANSPORT_STDIN,
    HarnessAdapter,
    SpawnRequest,
    SpawnSpec,
)

__all__ = ["OneShotResult", "run_one_shot"]

# SIGTERM → SIGKILL 两段式宽限（与 AGENT_TERMINATE_GRACE_SECONDS 同量级）
TERMINATE_GRACE_SECONDS = 5.0


class OneShotCommunicateError(Exception):
    """communicate 阶段非超时异常（清场后包装上抛）。

    与 spawn 阶段异常（原样上抛）区分，供站点保持既有两段文案（如 knowledge
    蒸馏「调用 claude CLI 失败」vs「claude 进程通信失败」）；``original``
    保留原异常对象，需要严格类型语义的调用方（如 knowledge_backfill 的
    fail-open 透传）可 re-raise ``original``。
    """

    def __init__(self, original: BaseException):
        self.original = original
        super().__init__(str(original))


@dataclass
class OneShotResult:
    """run_one_shot 终态：退出码 + 两管道全文 + 是否超时收割。"""

    returncode: Optional[int]
    stdout: str
    stderr: str
    # True = 超时路径（SIGTERM→SIGKILL 强杀后收割；returncode 为负信号值或 None）
    timed_out: bool = False


def _kill_process_group(proc: subprocess.Popen, grace: float) -> None:
    """SIGTERM 整组 → 宽限 → SIGKILL 整组（两段式，幂等容错）。

    击杀经自保护守卫 ``core.proc_utils.guard_killpg``（add-killpg-self-guard，
    resolve 型——替身 pid 怪值/组已消亡静默；仓库级源码守卫
    test_killpg_self_guard 强制清场击杀收口至此）。
    """
    from core.proc_utils import guard_killpg

    for sig in (signal.SIGTERM, signal.SIGKILL):
        # resolve 型：proc.pid 为组内成员 pid（start_new_session 下 pgid==pid）
        if not guard_killpg(
            proc.pid, sig, caller="harness.one_shot._kill_process_group",
            resolve=True,
        ):
            return  # 组已消亡/守卫拒绝：静默收口
        if sig is signal.SIGTERM:
            try:
                proc.wait(timeout=grace)
                return  # 宽限内自行退出，不升级 SIGKILL
            except subprocess.TimeoutExpired:
                continue


def run_one_shot(
    adapter: HarnessAdapter,
    request: SpawnRequest,
    *,
    timeout: Optional[float] = None,
    on_spawn: Optional[Callable[[Any], None]] = None,
    on_timeout: Optional[Callable[[Any], None]] = None,
    spawn_guard: Any = None,
    terminate_grace_seconds: float = TERMINATE_GRACE_SECONDS,
    popen: Optional[Callable[..., Any]] = None,
) -> OneShotResult:
    """一次性 agent spawn：build_spawn_spec → Popen → communicate → 定时收割。

    Args:
        adapter: harness adapter（命令构造唯一入口，task 8.2 grep 核查锚点）。
        request: 一次性 spawn 请求（prompt 传输形态/output_format/env 口径/
            timeout 描述等全是字段）。
        timeout: communicate 超时秒数；None = 无限等。超时走两段式进程组清场
            后收割，``timed_out=True``。
        on_spawn: Popen 返回后立即回调（进程登记锚点——architecture autodraft
            借此在 _guard 锁内登记可取消句柄）。
        on_timeout: 超时清场回调（缺省两段式 SIGTERM→SIGKILL 整组；knowledge
            蒸馏传自有 _kill_process_group 保持既有直 SIGKILL+弃管道语义）。
        spawn_guard: 包住「Popen + on_spawn」的上下文管理器（锁_scope 对齐：
            architecture_routes 现状只在 Popen+登记段持 _guard，communicate 在
            锁外）；None = 空 context。
        terminate_grace_seconds: SIGTERM → SIGKILL 升级宽限。
        popen: 测试替身注入口（缺省 subprocess.Popen）。

    Returns:
        :class:`OneShotResult`。管道解码口径随 SpawnSpec（显式 utf-8/replace
        或调用方声明的 Popen 缺省）；stdin_payload 为 None 时子进程 stdin 接
        DEVNULL（argv 传 prompt 的 autodraft/describe 现状形态）。
    """
    spec: SpawnSpec = adapter.build_spawn_spec(request)
    popen_fn = popen or subprocess.Popen
    popen_kwargs: dict = {
        "stdin": subprocess.PIPE if spec.stdin_payload is not None
        else subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": spec.text,
        "cwd": spec.cwd,
        "start_new_session": spec.start_new_session,
    }
    if spec.env is not None:
        popen_kwargs["env"] = spec.env
    if spec.encoding is not None:
        popen_kwargs["encoding"] = spec.encoding
        popen_kwargs["errors"] = spec.errors

    guard = spawn_guard if spawn_guard is not None else contextlib.nullcontext()
    with guard:
        proc = popen_fn(
            spec.argv,
            **popen_kwargs,
        )
        if on_spawn is not None:
            try:
                on_spawn(proc)
            except BaseException:
                # 回调失败同样不遗留活子进程：先按超时同径两段式清场再原样
                # 上抛（清场自身异常不吞原异常），否则已 spawn 的子进程
                # （start_new_session 独立进程组）无人登记、无人收割成孤儿
                with contextlib.suppress(Exception):
                    _kill_process_group(proc, terminate_grace_seconds)
                raise

    timed_out = False
    try:
        # stdin 载荷按位置传参（与既有各点 communicate(prompt, timeout=...)
        # 形态一致——替身以 prompt 命名形参）；argv 传输（载荷 None）走
        # communicate(timeout=...) 形态（project/architecture 替身签名如此）
        if spec.stdin_payload is not None:
            stdout, stderr = proc.communicate(spec.stdin_payload, timeout=timeout)
        else:
            stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        if on_timeout is not None:
            on_timeout(proc)
        else:
            _kill_process_group(proc, terminate_grace_seconds)
        try:
            stdout, stderr = proc.communicate(timeout=terminate_grace_seconds + 5)
        except (subprocess.TimeoutExpired, ValueError):
            stdout, stderr = "", ""
    except Exception as e:  # noqa: BLE001
        # 通信期非超时异常：按超时同径清场后包装上抛（spawn 阶段异常已在
        # 上方原样穿透，站点据此区分两段文案）
        if on_timeout is not None:
            on_timeout(proc)
        else:
            _kill_process_group(proc, terminate_grace_seconds)
        raise OneShotCommunicateError(e) from e
    return OneShotResult(
        returncode=proc.returncode,
        stdout=stdout or "",
        stderr=stderr or "",
        timed_out=timed_out,
    )
