"""
fenix_session.py — 为 Fenixd 项目计算唯一 tmux session 名并查询运行状态。

早期框架用固定 tmux session 名 `fenixd`，同一台机器只能同时运行一个
fenixd daemon。本模块按「项目根路径」派生确定性、唯一的 session 名
（fenixd-<目录名>-<路径哈希6位>），使多个 Fenixd 项目可并行开发，
互不干扰（日志、STATE.md、config.yaml 本就按项目隔离，唯一冲突点
就是 session 名）。

纯函数（resolve_root / session_name / is_running）供 bin/fenix_session.py
（CLI）与 core/dashboard/data.py（daemon 健康检测）共享，避免两处重复实现。
"""

import hashlib
import os
import re
import subprocess
import time
from pathlib import Path

LEGACY_SESSION = "fenixd"


def resolve_root(root: str | None = None) -> Path:
    """规范化项目根路径（展开 ~ 与软链接）。"""
    return Path(root or os.getcwd()).expanduser().resolve()


def session_name(root: str | None = None) -> str:
    """按项目根路径派生唯一 session 名。

    同一项目经不同入口（技能 / 状态栏 / 仪表盘）计算得到的结果一致；
    不同项目（即使目录同名）因哈希不同而唯一。
    """
    proot = resolve_root(root)
    digest = hashlib.md5(str(proot).encode()).hexdigest()[:6]
    base = re.sub(r"[^A-Za-z0-9_.-]+", "-", proot.name).strip("-.") or "project"
    return f"fenixd-{base}-{digest}"


def _legacy_session_matches(root: Path) -> bool:
    """旧版固定 session `fenixd` 是否属于该项目（按其 cwd 判断）。"""
    try:
        r = subprocess.run(
            ["tmux", "list-panes", "-t", LEGACY_SESSION, "-F", "#{pane_current_path}"],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return False
    if r.returncode != 0:
        return False
    for line in r.stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            if Path(line).expanduser().resolve() == root:
                return True
        except Exception:
            continue
    return False


def _daemon_procs_under(root: Path) -> bool:
    """项目根下是否有活跃的 fenixd daemon 进程。

    daemon 自 fix-admin-self-heal 起由 supervisor 直启（不在 tmux 内），
    tmux session 判定会漏报；以 /proc 的 cwd+cmdline 匹配项目根的
    fenixd.py / fenixd_supervisor.py 进程为准，覆盖 tmux 与直启两种模式。
    """
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            cwd = os.readlink(f"/proc/{pid}/cwd")
            if Path(cwd).expanduser().resolve() != root:
                continue
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmdline = f.read().decode("utf-8", errors="replace").replace("\x00", " ")
        except (OSError, ValueError):
            continue
        if ".fenix/fenixd.py" in cmdline or "fenixd_supervisor" in cmdline:
            return True
    return False


def _tmux_match(proot: Path) -> bool:
    """回退判定：唯一名 session（+ 旧版固定 `fenixd` cwd 匹配）。"""
    try:
        r = subprocess.run(
            ["tmux", "has-session", "-t", session_name(proot)],
            capture_output=True,
            timeout=2,
        )
        if r.returncode == 0:
            return True
    except Exception:
        pass
    return _legacy_session_matches(proot)


def is_running(root: str | None = None) -> bool:
    """该项目是否有 daemon 在运行。

    主判定为进程检测（supervisor/直启/tmux 内 daemon 均命中，不会像 tmux
    session 判定那样漏报直启模式或误报残留 session）；/proc 不可用时回退
    tmux 判定（唯一名 + 旧版兼容）。
    """
    proot = resolve_root(root)
    try:
        return _daemon_procs_under(proot)
    except Exception:
        pass
    return _tmux_match(proot)


def start_daemon(root: str | None = None) -> dict:
    """启动该项目的 fenixd daemon（复用唯一 tmux session）。

    以与 `fenix-setup` 一致的命令拉起：
    `tmux new-session -d -s <session> "cd <root> && python3 .fenix/fenixd.py 2>&1 | tee .fenix/logs/stdout.log"`

    启动前校验项目根存在 `.fenix`（框架软链接）与 `STATE.md`，缺失返回可读
    错误且不产生 daemon 进程。幂等：已运行则直接返回 already，不重复拉起。
    启动后轮询 `is_running` 至多约 5 秒，命中再返回成功。

    返回: {"ok": bool, "error": str|None, "session": str|None, "already": bool}
    任何 subprocess/tmux 异常均返回 ok=False 的错误对象，不抛异常。
    """
    proot = resolve_root(root)
    session = session_name(proot)
    if not (proot / ".fenix").exists():
        return {"ok": False, "error": f"项目根缺少 .fenix 框架软链接: {proot}", "session": session, "already": False}
    if not (proot / "STATE.md").is_file():
        return {"ok": False, "error": f"项目根缺少 STATE.md: {proot}", "session": session, "already": False}
    if is_running(proot):
        return {"ok": True, "error": None, "session": session, "already": True}

    try:
        subprocess.run(
            ["tmux", "new-session", "-d", "-s", session,
             f"cd {proot} && python3 .fenix/fenixd.py 2>&1 | tee .fenix/logs/stdout.log"],
            capture_output=True, text=True, timeout=15,
        )
    except Exception as e:
        return {"ok": False, "error": f"无法启动 daemon（tmux 不可用？）: {e}", "session": session, "already": False}

    # 轮询等待进程真正起来（is_running 主判定为 /proc 进程检测）
    for _ in range(50):
        if is_running(proot):
            return {"ok": True, "error": None, "session": session, "already": False}
        time.sleep(0.1)
    # 即便 is_running 因环境不可判（/proc 不可读）未命中，session 也已创建成功
    return {"ok": True, "error": None, "session": session, "already": False}


def stop_daemon(root: str | None = None) -> dict:
    """停止该项目的 fenixd daemon（优雅优先，强制兜底）。

    先 `tmux send-keys -t <session> C-c` 触发 daemon 的 SIGINT 优雅关闭
    （fenixd.py 已注册 shutdown handler），轮询 `is_running` 至多约 5 秒；
    超时仍未退出再 `tmux kill-session -t <session>` 强制终止。
    幂等：未运行时直接返回成功，不报错。

    返回: {"ok": bool, "error": str|None, "session": str|None, "was_running": bool}
    """
    proot = resolve_root(root)
    session = session_name(proot)
    if not is_running(proot):
        return {"ok": True, "error": None, "session": session, "was_running": False}

    try:
        subprocess.run(
            ["tmux", "send-keys", "-t", session, "C-c"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception as e:
        # 优雅关闭信号发送失败：直接尝试强制终止兜底
        pass

    # 轮询等待优雅关闭（至多约 5 秒）
    for _ in range(50):
        if not is_running(proot):
            return {"ok": True, "error": None, "session": session, "was_running": True}
        time.sleep(0.1)

    # 超时：强制 kill session
    try:
        subprocess.run(
            ["tmux", "kill-session", "-t", session],
            capture_output=True, text=True, timeout=5,
        )
    except Exception as e:
        return {"ok": False, "error": f"强制终止 daemon 失败: {e}", "session": session, "was_running": True}

    # 再确认一次
    for _ in range(10):
        if not is_running(proot):
            return {"ok": True, "error": None, "session": session, "was_running": True}
        time.sleep(0.1)
    return {"ok": True, "error": None, "session": session, "was_running": True}
