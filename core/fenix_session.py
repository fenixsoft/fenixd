"""
fenix_session.py — 为 Fenixd 项目计算唯一 tmux session 名并查询运行状态、
daemon 托管态（fix-supervisor-hosting-chain）。

早期框架用固定 tmux session 名 `fenixd`，同一台机器只能同时运行一个
fenixd daemon。本模块按「项目根路径」派生确定性、唯一的 session 名
（fenixd-<目录名>-<路径哈希6位>），使多个 Fenixd 项目可并行开发，
互不干扰（日志、STATE.md、config.yaml 本就按项目隔离，唯一冲突点
就是 session 名）。

托管态（supervisor-hosting）：daemon 自 fix-admin-self-heal 起由外部
supervisor（bin/fenixd_supervisor.py）托管启动；本模块提供 supervisor_running
与 hosting_state（managed / unmanaged / stopped）判定，供 dashboard、admin、
hook 区分「进程在跑但无人托管」与「完全未运行」。

纯函数（resolve_root / session_name / is_running / supervisor_running /
hosting_state）供 bin/fenix_session.py（CLI）与 core/dashboard/data.py
（daemon 健康检测）共享，避免两处重复实现。
"""

import hashlib
import os
import re
import shlex
import signal
import subprocess
import time
from pathlib import Path

LEGACY_SESSION = "fenixd"

# start_daemon 启动后轮询等待进程立起来的次数 × 步长（秒）。模块常量而非
# 字面量，供测试注入小值（is_running 被 mock 为假时否则真等 5s）。
START_DAEMON_PROBE_ATTEMPTS = 50
START_DAEMON_PROBE_INTERVAL_SECONDS = 0.1


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
    # 点号一并折叠为连字符（code-review item 12e5e201a1c3）：tmux 对会话名会
    # 静默把 `.` 替换为 `_`，且 has-session/kill-session 解析带点号目标时把点号
    # 当窗格分隔符而查找失败——派生名与 tmux 实际会话名必须同口径，否则
    # start_daemon 启动复核、is_running 的 tmux 回退与 stop_daemon 兜底全部误判。
    base = re.sub(r"[^A-Za-z0-9-]+", "-", proot.name).strip("-") or "project"
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


def _procs_matching(match) -> list:
    """扫描 /proc，返回命中 match(cwd: Path, argv: list) 的进程 pid 列表。

    fix-supervisor-hosting-chain 2.1：_daemon_procs_under / supervisor_running /
    _fenix_pids_under 共用同一套 process-cwd+cmdline 探测（读取
    /proc/<pid>/cwd 与 cmdline），不得复制粘贴出第二套解析。单个进程读取
    失败（OSError/ValueError，进程已退出/权限不足）跳过；调用方负责兜底
    整体异常。返回 pid 数字串列表，调用方自取 bool() 或按 pid 操作。

    子串假阳性事故（2026-09-13）后改为传 **argv token 列表**而非空格拼接的
    cmdline：拼接串只能做子串匹配，任何「命令行里提到 .fenix/fenixd.py 或
    fenixd_supervisor」的进程都会被误认成 daemon（sha256sum 该脚本、grep 该
    路径、agent 的 prompt 文本皆可触发）。token 化后判据可以要求「该 token
    就是被执行的脚本」。
    """
    # /proc 不可用（非 Linux 平台等）时抛 OSError 交调用方兜底——本函数 docstring
    # 即约定「调用方负责兜底整体异常」：is_running 的 except 路径据此回退 tmux
    # 判定，supervisor_running / _fenix_pids_under 各自降级（code-review
    # b7858abfd42b：此处吞成 [] 会让 tmux 回退不可达，无 /proc 环境恒判未运行）。
    pids = os.listdir("/proc")
    hits = []
    for pid in pids:
        if not pid.isdigit():
            continue
        try:
            cwd = os.readlink(f"/proc/{pid}/cwd")
            cwd_resolved = Path(cwd).expanduser().resolve()
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                raw = f.read().decode("utf-8", errors="replace")
        except (OSError, ValueError):
            continue
        argv = [token for token in raw.split("\x00") if token]
        if match(cwd_resolved, argv):
            hits.append(pid)
    return hits


def _normalize(path: Path) -> str:
    """路径词法归一化——**不跟随软链**。

    项目内 `.fenix/` 是指向框架主树的软链，`resolve()` 会把子项目的脚本路径
    牵回主树（fix-supervisor-hosting-chain 踩过的坑）；身份比对只需词法一致。
    """
    return os.path.normpath(str(path))


def _is_python_argv(argv) -> bool:
    """argv[0] 是否 Python 解释器（python / python3 / python3.10 / /usr/bin/python3）。"""
    if not argv:
        return False
    return Path(argv[0]).name.startswith("python")


def _argv_script_token(argv):
    """返回 argv 里「被执行的脚本」token；不是脚本调用时返回 None。

    `python3 <script> [args]` / `python3 -u <script>` → 返回首个非选项 token；
    出现 -c（代码串）/ -m（模块，本函数不支持 "-m xxx" 形式）时返回 None——
    否则 `python3 -c "...; time.sleep(30)" fenixd_supervisor` 这种「命令行里
    提到脚本名」的进程会被误判成正在执行该脚本（子串假阳性事故）。
    合并短选项写法（-uc / -im / 附着参数的 -c"<code>"）同样按 -c/-m 调用
    处理返回 None，堵住经合并写法绕过检测的旁路。
    """
    for token in argv[1:]:
        if token in ("-c", "-m"):
            return None
        if token.startswith("-"):
            # 短选项簇内可能藏着 -c/-m（如 -uc / -im / -c"<code>"）：按 Python
            # 选项解析语义逐字符扫旗标，见 c/m 即代码串/模块调用；遇取参旗标
            # （W/x/X）即止——其余字符是它的参数（如 -Ximporttime），不算旗标。
            if not token.startswith("--"):
                for ch in token[1:]:
                    if ch in ("c", "m"):
                        return None
                    if ch in ("W", "x", "X"):
                        break
            continue
        return token
    return None


def _is_daemon_proc(cwd: Path, argv, root: Path) -> bool:
    """该进程是否正在执行 root/.fenix/fenixd.py（daemon）。"""
    if not _is_python_argv(argv):
        return False
    script = _argv_script_token(argv)
    if script is None:
        return False
    return _normalize(cwd / script) == _normalize(root / ".fenix" / "fenixd.py")


def _is_supervisor_proc(cwd: Path, argv, root: Path) -> bool:
    """该进程是否正在执行 supervisor 脚本并锚定 root。

    两条路径：脚本位于 root/.fenix/bin/（cwd 内相对调用或绝对路径调用），
    或脚本是别处副本但以 `--project-root <root>` 显式锚定本项目。
    """
    if not _is_python_argv(argv):
        return False
    script = _argv_script_token(argv)
    if script is None or Path(script).name != "fenixd_supervisor.py":
        return False
    if _normalize(cwd / script) == _normalize(root / ".fenix" / "bin" / "fenixd_supervisor.py"):
        return True
    argv_root = _argv_option_root(argv)
    return argv_root is not None and argv_root == root


def _daemon_procs_under(root: Path) -> bool:
    """项目根下是否有活跃的 fenixd daemon 进程。

    daemon 自 fix-admin-self-heal 起由 supervisor 直启（不在 tmux 内），
    tmux session 判定会漏报；以 /proc 的 cwd+argv 匹配项目根的
    fenixd.py / fenixd_supervisor.py 进程为准，覆盖 tmux 与直启两种模式。
    """

    def _match(cwd: Path, argv) -> bool:
        return _is_daemon_proc(cwd, argv, root) or _is_supervisor_proc(cwd, argv, root)

    return bool(_procs_matching(_match))


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


def _argv_option_root(argv):
    """从 argv token 列表提取 `--project-root` 的值（绝对规范化）。

    fix-supervisor-hosting-chain 2.1：supervisor 可能经 cwd（默认）或显式
    --project-root 两种方式锚定项目根；提取参数值用于跨目录判定。
    匹配 `--project-root <值>` 与 `--project-root=<值>` 两种写法。
    """
    for i, token in enumerate(argv):
        value = None
        if token == "--project-root" and i + 1 < len(argv):
            value = argv[i + 1]
        elif token.startswith("--project-root="):
            value = token.split("=", 1)[1]
        if value is None:
            continue
        try:
            return Path(value).expanduser().resolve()
        except (OSError, ValueError):
            return None
    return None


def supervisor_running(root: str | None = None) -> bool:
    """该项目根是否有活跃 supervisor 进程（bin/fenixd_supervisor.py）。

    fix-supervisor-hosting-chain D3：扫描 /proc，命中条件为**正在执行**
    supervisor 脚本（Python 解释器 + 脚本 token，见 _is_supervisor_proc），
    且该脚本位于 root/.fenix/bin/ 或其 `--project-root` 值等于 root。
    /proc 不可读或任何异常返回 False 且不抛异常（与 is_running 的容错契约一致）。
    """
    proot = resolve_root(root)

    def _match(cwd: Path, argv) -> bool:
        return _is_supervisor_proc(cwd, argv, proot)

    try:
        return bool(_procs_matching(_match))
    except Exception:
        return False


def _fenix_pids_under(root: Path) -> list:
    """项目根下活跃的 fenixd daemon/supervisor 进程 pid 列表。

    fix-supervisor-hosting-chain 3.2：供 stop_daemon 定位 SIGTERM/SIGKILL
    目标。判定口径与 _daemon_procs_under 一致（见 _is_daemon_proc /
    _is_supervisor_proc：**正在执行**该脚本，而非命令行里提到该路径）。
    仅返回按此口径定位的 pid，禁止按 cmdline 裸匹配杀进程。
    """

    def _match(cwd: Path, argv) -> bool:
        return _is_daemon_proc(cwd, argv, root) or _is_supervisor_proc(cwd, argv, root)

    try:
        return _procs_matching(_match)
    except Exception:
        return []


def _is_daemon_cmdline(pid) -> bool:
    """pid 是否**正在执行** .fenix/fenixd.py（daemon，而非 supervisor）。

    fix-supervisor-hosting-chain 3.2：stop_daemon 的 SIGTERM 只发给 daemon
    （supervisor 见 stop flag 后自行退出，无需也不应杀它）。子串假阳性事故
    （2026-09-13）后判据同 _is_daemon_proc：Python 解释器 + 脚本 token 解析
    到该进程自己 cwd 下的 .fenix/fenixd.py——仅「命令行里提到该路径」的
    进程（grep/cat/sha256sum）不再满足。读取失败（进程已退出）返回 False。
    """
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            raw = f.read().decode("utf-8", errors="replace")
        cwd = Path(os.readlink(f"/proc/{pid}/cwd")).expanduser().resolve()
    except (OSError, ValueError):
        return False
    argv = [token for token in raw.split("\x00") if token]
    if not _is_python_argv(argv):
        return False
    script = _argv_script_token(argv)
    if script is None or Path(script).name != "fenixd.py":
        return False
    return _normalize(cwd / script) == _normalize(cwd / ".fenix" / "fenixd.py")


def hosting_state(root: str | None = None) -> str:
    """daemon 托管态三态判定：managed / unmanaged / stopped。

    fix-supervisor-hosting-chain D3：
    - managed   ：有活跃 supervisor 进程（daemon 受托管，restart_request /
                  approve_push_request 等文件信号有消费方）
    - unmanaged ：有活跃 daemon 进程但无 supervisor（裸 daemon——事故回归点，
                  进程在跑但文件信号无人消费）
    - stopped   ：两者皆无
    任一判定异常按 stopped 兜底，不抛异常。
    """
    proot = resolve_root(root)
    try:
        if supervisor_running(proot):
            return "managed"
    except Exception:
        pass
    try:
        if is_running(proot):
            return "unmanaged"
    except Exception:
        pass
    return "stopped"


def start_daemon(root: str | None = None) -> dict:
    """启动该项目的 fenixd daemon（supervisor 托管，fix-supervisor-hosting-chain）。

    以 supervisor 托管方式拉起：在项目唯一 tmux session 内执行
    `cd <root> && python3 .fenix/bin/fenixd_supervisor.py --project-root <root> >> .fenix/logs/supervisor.log 2>&1`，
    daemon 由 supervisor 作为子进程拉起（tmux 仅承担脱离终端，不再是 daemon
    的父进程）。与 `fenix-setup` 技能第 7 步的命令保持一致。

    启动前校验项目根存在 `.fenix`（框架软链接）与 `STATE.md`，缺失返回可读
    错误且不产生 daemon 进程。幂等：已运行则直接返回 already，不重复拉起。
    启动前清除陈旧 `.fenix/stop`（仅当 daemon 与 supervisor 均未在跑时删除，
    避免误删一次正在进行的停止操作留下的标记）。启动后轮询 `is_running`
    至多约 5 秒，命中再返回成功；窗口耗尽则经 `tmux has-session` 复核会话
    存活，并经 `list-panes` 校验会话确以 supervisor 命令启动——会话已退出
    （启动命令失败）或会话内是同名残留的无关窗格，均返回 ok=False。
    new-session 返回码非零（duplicate session 除外，维持既有「已存在」路径
    语义落回轮询复核）同样直接返回 ok=False 并附 stderr，不静默忽略。

    返回: {"ok": bool, "error": str|None, "session": str|None, "already": bool}
    任何 subprocess/tmux 异常均返回 ok=False 的错误对象，不抛异常。
    """
    proot = resolve_root(root)
    session = session_name(proot)
    if not (proot / ".fenix").exists():
        return {
            "ok": False,
            "error": f"项目根缺少 .fenix 框架软链接: {proot}",
            "session": session,
            "already": False,
        }
    if not (proot / ".fenix" / "STATE.md").is_file():
        return {
            "ok": False,
            "error": f"项目根缺少 STATE.md: {proot}",
            "session": session,
            "already": False,
        }
    if is_running(proot):
        return {"ok": True, "error": None, "session": session, "already": True}

    # 陈旧 stop 标记清理（3.3）：is_running 为假（已幂等返回）且 supervisor 也未
    # 在跑时删除——避免误删一次正在进行的停止操作留下的标记
    stop_flag = proot / ".fenix" / "stop"
    try:
        if stop_flag.exists() and not supervisor_running(proot):
            stop_flag.unlink()
    except OSError:
        pass

    try:
        # supervisor 日志重定向指向 .fenix/logs/supervisor.log，shell 会因目录
        # 不存在而重定向失败（全新项目首次拉起即触发），先确保目录存在，
        # 与其余日志写点的 mkdir 惯例对齐（code-review item 5fb92e285e94）。
        (proot / ".fenix" / "logs").mkdir(parents=True, exist_ok=True)
        # shell-quote 路径插值（code-review item 6333feb03e0c）：tmux 会把命令串
        # 交给 shell 执行，裸拼路径含空格时被拆词致启动失败、含 ;/$/反引号等
        # 元字符时构成命令注入面（路径来源含 CLI 入参与调用方传参）。
        proot_q = shlex.quote(str(proot))
        created = subprocess.run(
            [
                "tmux",
                "new-session",
                "-d",
                "-s",
                session,
                f"cd {proot_q} && python3 .fenix/bin/fenixd_supervisor.py --project-root {proot_q} >> .fenix/logs/supervisor.log 2>&1",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        # new-session 返回码校验（code-review item ed96126c1cdf）：非零说明会话
        # 根本没建起来，静默吞掉会让后续轮询必败、收口 has-session 又只看「会话
        # 存在」而可能撞上同名残留会话误报成功。duplicate session（同名会话已在，
        # 如并发 start 竞态）维持既有「已存在」路径语义，落回下方轮询 + 复核；
        # 其余失败（tmux server 异常等）直接 ok=False 并附 stderr。
        if created.returncode != 0 and "duplicate session" not in (created.stderr or ""):
            return {
                "ok": False,
                "error": f"tmux new-session 失败（rc={created.returncode}）: {(created.stderr or '').strip()}",
                "session": session,
                "already": False,
            }
    except Exception as e:
        return {
            "ok": False,
            "error": f"无法启动 daemon（tmux 不可用？）: {e}",
            "session": session,
            "already": False,
        }

    # 轮询等待进程真正起来（is_running 主判定为 /proc 进程检测）
    for _ in range(START_DAEMON_PROBE_ATTEMPTS):
        if is_running(proot):
            return {"ok": True, "error": None, "session": session, "already": False}
        time.sleep(START_DAEMON_PROBE_INTERVAL_SECONDS)
    # 探测窗口耗尽后区分两种情况：/proc 不可判但会话仍存活 → 维持宽容成功；
    # 会话已消失 → tmux 内命令失败退出（会话随命令退出关闭），不能误报成功。
    try:
        probe = subprocess.run(
            ["tmux", "has-session", "-t", session],
            capture_output=True,
            timeout=2,
        )
    except Exception as e:
        return {
            "ok": False,
            "error": f"无法确认 daemon 会话存活（tmux 异常）: {e}，请查看 .fenix/logs/supervisor.log",
            "session": session,
            "already": False,
        }
    if probe.returncode != 0:
        return {
            "ok": False,
            "error": "daemon 启动探测超时且 tmux 会话已退出（启动命令可能失败），请查看 .fenix/logs/supervisor.log",
            "session": session,
            "already": False,
        }
    # 会话存活 ≠ 本命令在跑（code-review item ed96126c1cdf）：同名残留会话可能
    # 装着无关窗格（如人工附着的交互 shell），只判「会话存在」会误报成功。经
    # list-panes 校验窗格确以 supervisor 命令启动才维持宽容成功；列表为空
    # （复核手段自身拿不到窗格信息）时维持既有宽容语义，不因校验失效改判失败。
    try:
        panes = subprocess.run(
            ["tmux", "list-panes", "-t", session, "-F", "#{pane_start_command}"],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception as e:
        return {
            "ok": False,
            "error": f"无法确认 daemon 会话内容（tmux 异常）: {e}，请查看 .fenix/logs/supervisor.log",
            "session": session,
            "already": False,
        }
    if panes.returncode != 0:
        # 会话恰在 has-session 与 list-panes 之间退出——等同会话已消失
        return {
            "ok": False,
            "error": "daemon 启动探测超时且 tmux 会话已退出（启动命令可能失败），请查看 .fenix/logs/supervisor.log",
            "session": session,
            "already": False,
        }
    start_cmds = [ln.strip() for ln in panes.stdout.splitlines() if ln.strip()]
    if start_cmds and not any("fenixd_supervisor.py" in cmd for cmd in start_cmds):
        return {
            "ok": False,
            "error": "daemon 启动探测超时且 tmux 会话内存活的不是 supervisor 命令（同名残留会话？），请查看 .fenix/logs/supervisor.log",
            "session": session,
            "already": False,
        }
    return {"ok": True, "error": None, "session": session, "already": False}


def stop_daemon(root: str | None = None) -> dict:
    """停止该项目的 fenixd daemon 及其 supervisor（fix-supervisor-hosting-chain）。

    托管语义：supervisor 是 daemon 的父进程，直接 kill daemon 会被 supervisor
    立即重新拉起；直接 kill session 会连带 SIGHUP 掉两者并丢失优雅清理。停止
    按序执行：
      ① 写 `.fenix/stop`（supervisor 见 daemon 退出后不再拉起）
      ② 经 /proc 定位该项目 daemon 进程并 SIGTERM（快速停机语义，秒级收口，
         不触发规划性排水；.fenix/restart_request 不在册时不走排水窗口）
      ③ 轮询等待 daemon 与 supervisor 双双退出（上限约 30 秒）
      ④ 超时 `tmux kill-session -t <session>` 强制终止，并对残留 daemon/
         supervisor 进程补发 SIGKILL 后短轮询复核（仍存活者计入 error，
         确保无孤儿）
      ⑤ finally 清除 `.fenix/stop`
    幂等：`is_running` 为假时直接返回 was_running=False，不写 stop 文件。

    SIGTERM/SIGKILL 只作用于 cwd 或 --project-root 等于该项目根的进程
    （经 _fenix_pids_under 定位），禁止按 cmdline 裸匹配杀进程。

    并发安全（fix-supervisor-hosting-chain 验证修复 BUG-01）：停止目标 pid
    在入口一次快照；SIGTERM 与超时 SIGKILL 只作用快照中的 pid（SIGKILL 前经
    kill(pid, 0) 探活），超时路径绝不重新扫描——否则一次并发的 stop/install
    在兜底时刻会把另一路刚拉起的新 supervisor/daemon 当作「残留」误杀，
    致托管永远无法成立。

    返回: {"ok": bool, "error": str|None, "session": str|None, "was_running": bool}
    任何 subprocess/信号异常均返回 ok=False 的错误对象，不抛异常。
    """
    proot = resolve_root(root)
    session = session_name(proot)
    stop_flag = proot / ".fenix" / "stop"
    if not is_running(proot):
        return {"ok": True, "error": None, "session": session, "was_running": False}

    # 入口快照停止目标（并发安全：超时兜底只杀快照 pid，不重扫）
    # [fenix-ignore:aea5d1c9400d] supervisor 拉起前后各有 stop 标记检查点（循环顶/监视循环/daemon 退出后）且监视循环见 stop 即主动 SIGTERM 当前 daemon，快照到写 stop 仅隔微秒级语句、spawn 不可能整体落入窗口，收口又以快照（含 supervisor pid）全退为前提，重生 daemon 无法在 stop 后存活；改为「写标记后等待再快照」反而会把并发 start 的新进程扫进快照被兜底误杀，重新引入 BUG-01「绝不重扫误杀」契约所禁止的行为。
    target_pids = _fenix_pids_under(proot)

    # ① 写 stop（supervisor 主循环开头与 daemon 退出后都会检查）
    try:
        stop_flag.parent.mkdir(parents=True, exist_ok=True)
        stop_flag.touch()
    except OSError as e:
        return {
            "ok": False,
            "error": f"写 .fenix/stop 失败: {e}",
            "session": session,
            "was_running": True,
        }

    try:
        # ② SIGTERM 该项目 daemon 进程（仅快照中的 cwd/--project-root 锚定且为
        # daemon 的进程——supervisor 见 stop flag 后自行退出，SIGTERM 不发给它）
        for pid in target_pids:
            if _is_daemon_cmdline(pid):
                try:
                    os.kill(int(pid), signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
        # ③ 轮询等待 daemon 与 supervisor 双双退出（上限约 30 秒）。
        # 只等快照 pid：并发时另一路新拉起的进程不在此列，不会让本路误等满窗。
        # 快照为空（/proc 不可用但 tmux 回退判定运行中）时退化为项目级轮询。
        deadline = time.time() + 30
        if target_pids:
            while time.time() < deadline:
                if not _alive_pids(target_pids):
                    break
                time.sleep(0.5)
        else:
            while time.time() < deadline:
                if not is_running(proot):
                    break
                time.sleep(0.5)
        # ④ 超时兜底：kill session 并对**快照中仍存活的残留**补 SIGKILL——
        # 不重新扫描项目（并发场景下新拉起的 supervisor 绝不被误杀）
        remaining = _alive_pids(target_pids)
        kill_errors = []
        if remaining or (not target_pids and is_running(proot)):
            try:
                subprocess.run(
                    ["tmux", "kill-session", "-t", session],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
            except Exception:
                pass
            sigkilled = []
            for pid in remaining:
                try:
                    os.kill(int(pid), signal.SIGKILL)
                    sigkilled.append(pid)
                except ProcessLookupError:
                    pass
                except PermissionError as e:
                    # 无权限发 SIGKILL＝目标仍存活（145eb8771dfc）：计入返回
                    # error，不谎报 ok=True。
                    kill_errors.append(f"SIGKILL pid {pid} 权限不足: {e}")
            # 补发后短轮询复核：D 态（不可中断 IO/NFS）进程暂不响应 SIGKILL
            # 时 kill 不报错、kill_errors 为空，不复核会向调用方谎报 ok=True。
            recheck_deadline = time.time() + 2
            while _alive_pids(sigkilled) and time.time() < recheck_deadline:
                time.sleep(0.2)
            for pid in _alive_pids(sigkilled):
                kill_errors.append(
                    f"SIGKILL pid {pid} 后仍存活（疑似不可中断态），daemon 可能未退出"
                )
        # ⑤ finally 清除 stop（无论成败）
        try:
            stop_flag.unlink()
        except OSError:
            pass
        return {
            "ok": not kill_errors,
            "error": "; ".join(kill_errors) if kill_errors else None,
            "session": session,
            "was_running": True,
        }
    except Exception as e:
        # finally 语义：异常路径也清除 stop，避免项目永久拒绝启动
        try:
            stop_flag.unlink()
        except OSError:
            pass
        return {
            "ok": False,
            "error": f"停止 daemon 失败: {e}",
            "session": session,
            "was_running": True,
        }


def _alive_pids(pids) -> list:
    """过滤仍存活的 pid（kill(pid, 0) 探测，0 号信号不改变目标）。

    fix-supervisor-hosting-chain 验证修复 BUG-01：stop_daemon 轮询/超时兜底
    均只面向「入口快照」的 pid——探测到进程已退出（ProcessLookupError）安全
    跳过，不抛异常。EPERM（PermissionError）语义是进程仍存在只是无权限发
    信号，按存活返回（145eb8771dfc），由兜底 SIGKILL 显式失败并计入 error。
    返回值仅含仍存活的 pid 串列表。
    """
    alive = []
    for pid in pids:
        try:
            os.kill(int(pid), 0)
            alive.append(pid)
        except ProcessLookupError:
            pass
        except PermissionError:
            # EPERM＝进程存在但本用户无权限发信号，按存活处理（145eb8771dfc）：
            # 吞掉会让等待窗提前判定全退、兜底跳过该 pid，stop_daemon 误报成功。
            alive.append(pid)
    return alive
