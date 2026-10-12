"""模块级代码陈旧旗标共享通道（evo-add-key-path-stale-code-preflight 1.1）。

daemon 侧既有陈旧判定（fenixd.py::_update_stale_code_state，每 30s 重算的
``self._code_stale``）经本注册表以只读查询形式暴露给 core/ 各关键路径模块
（verification-report 收尾提交、知识蒸馏派发、admin choice 执行），供其在
动作执行前预检——发现陈旧即请求重启加速装载，消除「修复已合并主树、车道
仍按旧代码执行数小时」的复发敞口。

约定：

- import 方向 core←daemon 单向：注册表落在 core/ 侧，daemon 只写入（同
  core/git_base_branch.py 成文约定，core 反向 import fenixd 会成环）；
- 线程安全：daemon 检测线程写、车道线程读；锁内仅指针/布尔读写，
  ``is_stale()`` 查询本身不产生任何 IO；
- fail-open：未注册（pytest / 非 daemon 语境 / 冷启动窗口）时查询返回
  「不陈旧」，关键路径零感知，行为与不预检时完全一致。
"""

import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

# daemon 自身仓库根（core/ 的上一级；与 fenixd.py 的 PROJECT_ROOT 同源——
# fenixd.py: FENIX_DIR = Path(__file__).absolute().parent，PROJECT_ROOT = 其
# 上一级）。restart_request 锚定 daemon 仓库而非被管项目 project_root：
# 治理第三方项目时 supervisor 只读 daemon 侧该文件（.fenix/bin/
# fenixd_supervisor.py 的 RESTART_REQUEST 同一文件）。测试经 mock.patch.object
# 把本常量指到临时目录，避免用例触碰真实仓库的 .fenix/。
DAEMON_ROOT = Path(__file__).absolute().parent.parent
RESTART_REQUEST = DAEMON_ROOT / ".fenix" / "restart_request"

_lock = threading.Lock()
# request_restart 写文件段专用锁：_lock 按模块约定只护指针/布尔读写（锁内
# 零 IO），文件存在性检查→写入的 check-then-act 段由本锁串行化
_write_lock = threading.Lock()
_callback: Optional[Callable[[], bool]] = None


def register(callback: Callable[[], bool]) -> None:
    """注册陈旧判定回调（daemon 启动初始化一次性调用，重复注册覆盖）。

    回调在每次 ``is_stale()`` 查询时现场调用（读 daemon 侧最新判定值），
    MUST 无 IO、快速返回。注册即镜像：daemon 每 30s 检测点对
    ``self._code_stale`` 的重算经回调直读即时可见（检测点同步语义由
    「注册回调直读活值」实现，注册表不落第二份状态——推送值兜底形态
    会让「未注册 → SHALL 返回不陈旧」的 fail-open 条款被推送历史破坏，
    并造成跨测试进程内污染，见 tests/test_key_path_stale_preflight.py
    模块注释）。
    """
    global _callback
    if not callable(callback):
        raise TypeError("code_stale_flag callback must be callable")
    with _lock:
        _callback = callback


def unregister() -> None:
    """注销回调（测试隔离用；daemon 生命周期内不调用）。"""
    global _callback
    with _lock:
        _callback = None


def is_stale() -> bool:
    """查询当前进程代码是否陈旧（关键路径预检唯一入口）。

    fail-open：未注册返回 False（不陈旧，无论此前有任何写入历史）；
    回调异常同样返回 False——陈旧预检不得让关键路径因判定通道故障而
    行为漂移。
    """
    with _lock:
        callback = _callback
    if callback is None:
        return False
    try:
        return bool(callback())
    except Exception:  # noqa: BLE001 — 判定通道故障 fail-open
        return False


def request_restart(log: Callable[[str], None], action: str) -> bool:
    """陈旧预检动作（三个关键路径插入点同款语义，单点收敛防漂移）。

    发现陈旧时按序：记一条 WARNING（含陈旧状态与已请求重启的事实）→ 确保
    daemon 仓库 ``.fenix/restart_request`` 存在（已存在不重复写、不刷 mtime，
    与既有自愈「restart_request 已在，重启在途，不重复写入」语义一致）→
    返回 True，调用方照常执行当前动作（预检不阻塞、不中断任何关键路径，
    也不改变其返回值与产物）。

    本函数不向调用方抛异常：判定、文件操作、日志通道逐一兜底，预检自身
    故障只降级为「未成写/未成日志」，绝不反噬关键路径动作。

    Args:
        log: 单参数日志 callable（str → None），由调用方适配各自 logger
            通道（engine/admin_monitor 为双参通道 logger，knowledge 为
            stdlib logger）。
        action: 关键路径动作名（入日志，定位哪条车道触发）。

    Returns:
        是否发现陈旧：False = 新鲜/未注册（零副作用，调用方零感知）。
    """
    if not is_stale():
        return False
    try:
        # check-then-act 段须持锁：并发车道线程（验证收尾/知识蒸馏/admin
        # choice）同时检测到陈旧时，无锁会让双方都看到 existed=False 并各自
        # 写一次、刷新 mtime，违反「已存在不重复写、不刷 mtime」不变量。
        # 调用方均在 daemon 同进程内（dashboard 未注册回调、fail-open 返回
        # 不陈旧、零副作用），线程锁即闭合，无需跨进程 flock。
        with _write_lock:
            existed = RESTART_REQUEST.exists()
            if not existed:
                RESTART_REQUEST.parent.mkdir(parents=True, exist_ok=True)
                # 写入格式与既有自愈 touch 一致（ISO 时间戳行）；仅在缺席时写，
                # 已在时不触碰（supervisor 侧只关心存在性，2s 轮询命中即
                # SIGTERM → 排水 → 重启）
                RESTART_REQUEST.write_text(
                    datetime.now(timezone.utc).isoformat() + "\n", encoding="utf-8"
                )
                detail = "已写入 .fenix/restart_request 请求重启"
            else:
                detail = "已请求重启（restart_request 已在、重启在途，不重复写入）"
    except Exception as e:  # noqa: BLE001 — 写失败只降级说明，不抛出
        detail = f"请求重启失败（{type(e).__name__}: {e}），supervisor 未获请求"
    try:
        log(
            f"{action}：检测到进程代码陈旧（磁盘代码较进程启动时已更新，"
            f"关键路径正以旧代码执行），{detail}；当前动作照常完成"
        )
    except Exception:  # noqa: BLE001 — 日志通道故障不得反噬关键路径动作
        pass
    return True
