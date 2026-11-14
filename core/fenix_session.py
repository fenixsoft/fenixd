"""
fenix_session.py — Fenixd 项目托管启停与运行状态判定
（fix-supervisor-hosting-chain / add-systemd-hosting）。

托管承载（add-systemd-hosting BREAKING）：daemon 由 systemd unit
``fenixd-<项目名>.service`` 承载的 supervisor 托管运行（ExecStart=supervisor
--project-root，daemon 保持为 supervisor 子进程）；tmux 从托管链退役
（session 名体系随之退役，unit 名派生见 core/systemd_hosting.unit_name_for）。
本模块承担 start_daemon（unit 缺失即生成安装并 enable --now）/ stop_daemon
（systemctl 双轨）/ 运行状态判定的共享实现。

托管态（supervisor-hosting）：本模块提供 supervisor_running 与
hosting_state（managed / unmanaged / stopped）判定，供 dashboard、admin、
hook 区分「进程在跑但无人托管」与「完全未运行」。

纯函数（resolve_root / is_running / supervisor_running / hosting_state）供
bin/fenix_session.py（CLI）与 core/dashboard/data.py（daemon 健康检测）共享，
避免两处重复实现。
"""

import os
import signal
import time
from pathlib import Path

from core.platform import api as pal

from .systemd_hosting import (
    SystemdHostingError,
    install_project_unit,
    stop_unit_no_block,
    unit_active,
    unit_installed,
    unit_name_for,
)

# start_daemon 启动后轮询等待进程立起来的次数 × 步长（秒）。模块常量而非
# 字面量，供测试注入小值（is_running 被 mock 为假时否则真等 5s）。
START_DAEMON_PROBE_ATTEMPTS = 50
START_DAEMON_PROBE_INTERVAL_SECONDS = 0.1

# 「supervisor 在跑但 daemon 本体缺席」警示文案：幂等门分支与新拉起轮询
# 复核分支共用（两处口径成对维护，见 code-review item e17df2678564 /
# 87bdc3d2f2b9），提常量防只改一处致文案漂移（item ee095cec8da0）。
SUPERVISOR_ONLY_WARNING = "supervisor 在跑但未检测到 daemon 进程（可能处于启动退避、熔断或停止流程中），请查看 .fenix/logs/supervisor.log"


def resolve_root(root: str | None = None) -> Path:
    """规范化项目根路径（展开 ~ 与软链接）。"""
    return Path(root or os.getcwd()).expanduser().resolve()


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
    # 即约定「调用方负责兜底整体异常」：is_running 的 except 路径据此判未运行
    # （tmux 回退已随 systemd 承载退役，fail-closed），supervisor_running /
    # _fenix_pids_under 各自降级。
    # 4.1：枚举经 pal.proc_pids 单点（OSError 上抛语义不变——本函数约定
    # 「调用方负责兜底整体异常」，is_running 的 except 路径据此判未运行）；
    # cwd/cmdline 读经 pal.readlink_cwd / pal.read_cmdline_raw（None ＝
    # 原读取失败，跳过该 pid）。
    pids = pal.proc_pids()
    hits = []
    for pid in pids:
        try:
            cwd = pal.readlink_cwd(int(pid))
            if cwd is None:
                continue
            cwd_resolved = Path(cwd).expanduser().resolve()
            argv = pal.cmdline_argv(int(pid))
            if argv is None:
                continue
        except (OSError, ValueError):
            continue
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
    合并短选项写法（-uc / -xc / -im / 附着参数的 -c"<code>"）同样按 -c/-m 调用
    处理返回 None，堵住经合并写法绕过检测的旁路。分离式取参旗标的参数
    （`python3 -X faulthandler <script>` / `python3 -W ignore <script>` 中的
    faulthandler / ignore）按 Python 选项语义消费、不当作脚本 token。
    不支持长选项带分离式参数的形态（如 `python3 --check-hash-based-pycs
    always <script>`）：其参数 token 会被误当作脚本 token，真正的脚本 token
    永不被考察，该形态启动的 daemon 会被判活漏检（stop 停不掉、start 可能
    重复拉起）。实际启动链路不使用该形态，故不为带值长选项维护取参清单
    （code-review item 176b3879d182）。
    """
    rest = argv[1:]
    i = 0
    while i < len(rest):
        token = rest[i]
        if token in ("-c", "-m"):
            return None
        if token.startswith("-"):
            if not token.startswith("--"):
                # 短选项簇内可能藏着 -c/-m（如 -xc / -uc / -im / -c"<code>"）：按 Python
                # 选项解析语义逐字符扫旗标，见 c/m 即代码串/模块调用；遇取参旗标
                # （W/X）即止——其余字符是它的参数（如 -Ximporttime），不算旗标。
                # -x（跳过源码首行）是布尔旗标、不取参，须继续向后扫 c/m
                # （code-review item 5110e20da1dd：否则 -xc/-xm 绕过 -c/-m 判定）。
                for ch in token[1:]:
                    if ch in ("c", "m"):
                        return None
                    if ch in ("W", "X"):
                        break
                # 分离式取参旗标以 W/X 收尾（裸 -W/-X 单字符，或簇尾形态如
                # `python3 -xW ignore <script>` 的 -xW）时，其参数是下一个 argv
                # token，一并跳过：否则真正的脚本 token 永远不被考察，判活原语
                # （_is_daemon_proc/_is_supervisor_proc → is_running /
                # supervisor_running/_fenix_pids_under）漏检该形态 daemon
                # （code-review item 35d975aaafb2；簇尾形态 item a65e14674c66）。
                # 参数附着在旗标后（-Ximporttime / -Wignore）则 W/X 非收尾字符，
                # 无需跳过。
                if token[-1] in ("W", "X") and i + 1 < len(rest):
                    i += 1
            i += 1
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


def _daemon_proc_running(root: Path) -> bool:
    """项目根下是否有 daemon 本体进程（仅 _is_daemon_proc 口径，不含 supervisor）。

    start_daemon 幂等门细分判定（code-review item e17df2678564）：is_running
    主判定命中 daemon 或 supervisor 任一，仅托管壳（supervisor）在跑而 daemon
    本体缺席（如 supervisor 拉起连续失败进入退避/熔断计数）时，不能把「壳在
    跑」当成「daemon 已就绪」。/proc 不可用时返回 True——复核手段自身失效时
    保守沿用既有 already 语义，不因探测降级改变幂等行为。
    """

    def _match(cwd: Path, argv) -> bool:
        return _is_daemon_proc(cwd, argv, root)

    try:
        return bool(_procs_matching(_match))
    except Exception:
        return True


def is_running(root: str | None = None) -> bool:
    """该项目是否有 daemon 在运行。

    判定为 /proc 进程检测（supervisor 托管与裸 daemon 均命中，按「正在执行
    fenixd.py / fenixd_supervisor.py」结构化识别，不误报命令行提及）。
    /proc 不可用时判未运行（fail-closed）：tmux 回退已随 systemd 承载退役，
    无 /proc 环境无从判定进程存在性，宁可误判 stopped 也不误判 running
    （误判 running 会让 start 幂等门吞掉启动、stop 谎报成功）。
    """
    proot = resolve_root(root)
    try:
        return _daemon_procs_under(proot)
    except Exception:
        return False


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


def _is_daemon_cmdline(pid, root: Path | None = None) -> bool:
    """pid 是否**正在执行** .fenix/fenixd.py（daemon，而非 supervisor）。

    fix-supervisor-hosting-chain 3.2：stop_daemon 的 SIGTERM 只发给 daemon
    （supervisor 见 stop flag 后自行退出，无需也不应杀它）。子串假阳性事故
    （2026-09-13）后判据同快照侧 _is_daemon_proc：Python 解释器 + 脚本 token
    解析——仅「命令行里提到该路径」的进程（grep/cat/sha256sum）不再满足；
    supervisor 脚本名是 fenixd_supervisor.py，不会误中。

    传入 root 时补项目根锚定复核（code-review item 33a5a217f420）：入口快照
    （_fenix_pids_under）到 SIGTERM 之间快照 pid 可能已退出并被内核复用为
    另一项目的 daemon，快照侧锚定管不住复用后的进程，仅凭「脚本名
    fenixd.py 且父目录 .fenix」的结构判据会把复用者误判为本项目目标杀掉。
    锚定判据与快照侧完全同款（cwd + 脚本 token 归一化比较
    root/.fenix/fenixd.py，复用者 cwd/脚本不指向本项目必判不过），与超时
    SIGKILL 路径 _is_snapshot_proc_cmdline 的复核口径对齐，消除两条杀灭
    路径的防护差。daemon 以非项目根 cwd + 绝对脚本路径启动时
    Path(cwd) / 绝对路径 仍归一化到脚本自身，不回归此前「SIGTERM 被跳过、
    优雅停机降级为 30 秒空等 + 强杀」的事故（code-review item
    9f0426156676）。cwd/cmdline 读取失败（进程可能已退出）返回 False：
    确已退出则无需信号，仍存活则由超时兜底路径复核补杀。root 缺省 None
    时保留纯结构判据，兼容既有无 root 调用点。
    """
    # 4.1：cmdline 经 pal.cmdline_argv 单点（None ＝ 原读取失败 → False）
    argv = pal.cmdline_argv(int(pid)) if str(pid).isdigit() else None
    if argv is None:
        return False
    if not _is_python_argv(argv):
        return False
    script = _argv_script_token(argv)
    if script is None:
        return False
    script_path = Path(script)
    if not (script_path.name == "fenixd.py" and script_path.parent.name == ".fenix"):
        return False
    if root is None:
        return True
    # 项目根锚定（item 33a5a217f420）：_is_daemon_proc 的 cwd/script 归一化
    # 判据与快照侧逐字同款，绝对脚本路径启动仍能通过（item 9f0426156676）。
    cwd_link = pal.readlink_cwd(int(pid))
    if cwd_link is None:
        return False
    cwd = Path(cwd_link).expanduser().resolve()
    return _is_daemon_proc(cwd, argv, root)


def _is_snapshot_proc_cmdline(pid, root: Path):
    """快照 pid 补杀前复核：cmdline 是否仍是本项目 daemon/supervisor 形态。

    stop_daemon 超时 SIGKILL 兜底专用（code-review item 8cf4db59080d）：
    30 秒等待窗内快照进程退出、pid 被内核复用给无关进程（含另一项目的
    daemon/supervisor）时，_alive_pids 的 kill(pid, 0) 探活仍判存活，盲杀
    会误杀复用者。判据与入口快照 _fenix_pids_under 完全同款
    （_is_daemon_proc / _is_supervisor_proc：cwd + argv 结构化解析 + 项目根
    锚定，故复用者为另一项目 daemon 时同样判不过）；只对快照 pid 自身
    复核、不重扫项目（不违反 aea5d1c9400d 契约）。返回三态：
    True＝仍是本项目 daemon/supervisor，可补杀；False＝/proc 可读但已非
    本项目形态（疑似 pid 复用），跳过补杀；None＝/proc 读取失败（进程已
    退出/不可读），复核不可判——照旧尝试补杀，进程确已退出由 os.kill 的
    ProcessLookupError 兜底，无害。
    """
    # 4.1：cwd/cmdline 经 pal.readlink_cwd / pal.cmdline_argv 单点
    # （None ＝ 原读取失败 → 复核不可判 None，照旧尝试补杀）
    if not str(pid).isdigit():
        return None
    cwd_link = pal.readlink_cwd(int(pid))
    argv = pal.cmdline_argv(int(pid))
    if cwd_link is None or argv is None:
        return None
    cwd = Path(cwd_link).expanduser().resolve()
    return _is_daemon_proc(cwd, argv, root) or _is_supervisor_proc(cwd, argv, root)


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
    """启动该项目的 fenixd daemon（systemd unit 承载的 supervisor 托管，add-systemd-hosting）。

    唯一托管启动路径：确保 ``fenixd-<项目名>.service`` unit 在位（缺失时生成
    安装）并 ``systemctl enable --now`` 拉起；unit 的 ExecStart 为 supervisor
    ``--project-root <root>``（daemon 由 supervisor 作为子进程拉起，systemd
    监督对象是 supervisor 不是 daemon）。tmux session 创建已退役（承载层
    BREAKING，MUST NOT 回退 tmux；systemctl 不可用返回可读错误并拒绝）。

    启动前校验项目根存在 `.fenix`（框架软链接）与 `STATE.md`，缺失返回可读
    错误且不产生 daemon 进程、不写 unit。幂等：daemon 或 supervisor 已在跑则
    不重复拉起——daemon 本体在跑直接返回 already；仅 supervisor 在跑（daemon
    本体缺席，如 supervisor 启动退避/熔断计数中）同样不重复拉起，但返回值
    追加 warning 说明未检测到 daemon（code-review item e17df2678564）。unit
    已安装且服务活跃时重复调用不重建 unit、不重启服务（systemd_hosting
    幂等安装语义）。
    启动前清除陈旧 `.fenix/stop`（仅当 daemon 与 supervisor 均未在跑时删除，
    避免误删一次正在进行的停止操作留下的标记）。安装后轮询 `is_running`
    至多约 5 秒，命中再返回成功；命中后以 `_daemon_proc_running` 复核 daemon
    本体，仅 supervisor 先到场（daemon 未检测到）时同样附 warning（code-review
    item 87bdc3d2f2b9）；窗口耗尽经 `systemctl is-active` 复核——unit 活跃
    （/proc 探测失效）维持宽容成功并附 warning，unit 不活跃（enable --now
    拉起的启动命令失败退出）返回 ok=False。

    返回: {"ok": bool, "error": str|None, "already": bool}；「仅 supervisor
    在跑、daemon 本体未检测到」的分支（幂等门与新拉起轮询命中）额外附
    warning: str。
    任何 systemctl 异常均返回 ok=False 的错误对象，不抛异常。
    """
    proot = resolve_root(root)
    if not (proot / ".fenix").exists():
        return {
            "ok": False,
            "error": f"项目根缺少 .fenix 框架软链接: {proot}",
            "already": False,
        }
    if not (proot / ".fenix" / "STATE.md").is_file():
        return {
            "ok": False,
            "error": f"项目根缺少 STATE.md: {proot}",
            "already": False,
        }
    if is_running(proot):
        if _daemon_proc_running(proot):
            return {"ok": True, "error": None, "already": True}
        # 幂等门细分判定（code-review item e17df2678564）：is_running 主判定命中
        # daemon 或 supervisor 任一——仅托管壳在跑、daemon 本体缺席（如 supervisor
        # 拉起连续失败进入退避/熔断计数，daemon 不会被重新拉起）时，不得谎报
        # daemon 已就绪；也不走下方 enable --now 拉起（unit 活跃即 supervisor
        # 在跑，重复 enable --now 不重建不重启，落回轮询后 is_running 仍会因
        # supervisor 在跑立即判真，同样谎报成功）。维持既有 ok/already 键结构，
        # 追加 warning 供调用方区分「daemon 在跑」与「仅托管壳在跑」。
        return {
            "ok": True,
            "error": None,
            "already": True,
            "warning": SUPERVISOR_ONLY_WARNING,
        }

    # 陈旧 stop 标记清理（3.3）：is_running 为假（已幂等返回）且 supervisor 也未
    # 在跑时删除——避免误删一次正在进行的停止操作留下的标记
    stop_flag = proot / ".fenix" / "stop"
    try:
        if stop_flag.exists() and not supervisor_running(proot):
            stop_flag.unlink()
    except OSError:
        pass

    try:
        # supervisor 日志写点在 .fenix/logs/supervisor.log，目录不存在时全新
        # 项目首次拉起会写失败（supervisor 内部吞 OSError 但日志无痕），先确保
        # 目录存在，与其余日志写点的 mkdir 惯例对齐（code-review item
        # 5fb92e285e94 沿用）。
        (proot / ".fenix" / "logs").mkdir(parents=True, exist_ok=True)
        result = install_project_unit(proot)
        if not result.get("ok"):
            return {"ok": False, "error": result.get("error"), "already": False}
    except SystemdHostingError as e:
        return {
            "ok": False,
            "error": str(e),
            "already": False,
        }
    except Exception as e:
        return {
            "ok": False,
            "error": f"无法启动 daemon（systemd 承载安装失败）: {e}",
            "already": False,
        }
    unit = result["unit"]

    # 轮询等待进程真正起来（is_running 主判定为 /proc 进程检测）
    for _ in range(START_DAEMON_PROBE_ATTEMPTS):
        if is_running(proot):
            # 与幂等门细分判定（code-review item e17df2678564）口径对齐
            # （code-review item 87bdc3d2f2b9）：is_running 命中 daemon 或
            # supervisor 任一，新拉起路径同样可能只等到 supervisor 先立起来
            # （daemon 随后拉起连续失败进入退避/熔断，永不到场），不能无声
            # 报成功；复核 daemon 本体，仅托管壳在场时附同样的 warning。
            if _daemon_proc_running(proot):
                return {"ok": True, "error": None, "already": False}
            return {
                "ok": True,
                "error": None,
                "already": False,
                "warning": SUPERVISOR_ONLY_WARNING,
            }
        time.sleep(START_DAEMON_PROBE_INTERVAL_SECONDS)
    # 探测窗口耗尽后经 systemctl 复核区分两种情况：unit 活跃 → /proc 探测
    # 失效（procfs 不可读等），supervisor 实际在跑，维持宽容成功并附 warning；
    # unit 不活跃 → enable --now 拉起的启动命令失败退出（systemd 已放弃），
    # 不能误报成功。
    try:
        if unit_active(unit):
            return {
                "ok": True,
                "error": None,
                "already": False,
                "warning": SUPERVISOR_ONLY_WARNING,
            }
        return {
            "ok": False,
            "error": (
                f"daemon 启动探测超时且 unit {unit} 不处于活跃态（启动命令可能失败），"
                f"请查看 .fenix/logs/supervisor.log 与 journalctl -u {unit}"
            ),
            "already": False,
        }
    except SystemdHostingError as e:
        return {
            "ok": False,
            "error": f"无法确认 daemon unit 存活（systemctl 异常）: {e}，请查看 .fenix/logs/supervisor.log",
            "already": False,
        }


def stop_daemon(root: str | None = None) -> dict:
    """停止该项目的 fenixd daemon 及其 supervisor（systemd 双轨，add-systemd-hosting）。

    托管语义：supervisor 是 daemon 的父进程，直接 kill daemon 会被 supervisor
    立即重新拉起。stop 按 unit 接管状态双轨执行（design 决策 4）：
      unit 已安装（systemd 承载，主轨）：
        ① 写 `.fenix/stop`（supervisor 见 daemon 退出后不再拉起，与 systemd
           SIGTERM 收尾链双保险）
        ② `systemctl stop --no-block`——同步 `systemctl stop` 最坏等待为排水
           上界量级（TimeoutStopSec=2100），会挂死 dashboard HTTP 线程，破坏
           现行有界契约，MUST NOT 同步等待；systemd 向 supervisor 发 SIGTERM，
           走既有转发收尾（SIGTERM daemon → 排水窗）
        ③ 轮询等待 daemon 与 supervisor 双双退出（上限约 30 秒）
        ④ 超时对入口快照中仍存活的残留补 SIGKILL
      unit 未安装但进程在跑（managed-but-no-unit 态：迁移期 / 人工直启 /
      unit 被手工卸载）：
        ②' 保留既有直接信号链——经 /proc 定位向该项目 daemon 发 SIGTERM。
        `systemctl stop` 对未启动 unit 是 no-op，不能以此谎报成功。
      两条轨共用 ③④ 与 ⑤ finally 清除 `.fenix/stop`（无论成败）。
    幂等：`is_running` 为假时直接返回 was_running=False，不写 stop 文件。
    tmux kill-session 兜底已退役（tmux 承载退役，无回退）。

    SIGTERM/SIGKILL 只作用于 cwd 或 --project-root 等于该项目根的进程
    （经 _fenix_pids_under 定位），禁止按 cmdline 裸匹配杀进程。

    并发安全（fix-supervisor-hosting-chain 验证修复 BUG-01，保持）：停止目标
    pid 在入口一次快照；SIGTERM 与超时 SIGKILL 只作用快照中的 pid（SIGKILL
    前经 kill(pid, 0) 探活＋cmdline 结构化复核，防等待窗内 pid 复用误杀，见
    _is_snapshot_proc_cmdline），超时路径绝不重新扫描——否则一次并发的
    stop/install 在兜底时刻会把另一路刚拉起的新 supervisor/daemon 当作
    「残留」误杀，致托管永远无法成立。

    返回: {"ok": bool, "error": str|None, "was_running": bool}
    任何 systemctl/信号异常均返回 ok=False 的错误对象，不抛异常。
    """
    proot = resolve_root(root)
    unit = unit_name_for(proot)
    stop_flag = proot / ".fenix" / "stop"
    if not is_running(proot):
        return {"ok": True, "error": None, "was_running": False}

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
            "was_running": True,
        }

    kill_errors = []
    try:
        # ② 双轨启动停机：unit 已装走 systemctl stop --no-block（systemd 对
        # supervisor 发 SIGTERM，转发收尾链照走）；未装走既有直接信号链。
        hosted = False
        try:
            hosted = unit_installed(unit)
        except SystemdHostingError:
            # systemctl 不可用：unit 承载无从判定，视同未安装走直接信号链
            # （managed-but-no-unit 态语义）；systemctl 不可用不阻断直接信号
            # 收口，可读错误由下方停止结果承载。
            hosted = False
        if hosted:
            try:
                stop_unit_no_block(unit)
            except SystemdHostingError as e:
                # 排队停机指令失败：等待+兜底仍执行，残留由快照补杀收口
                kill_errors.append(f"systemctl stop --no-block 失败: {e}")
        else:
            # ②' 直接信号链：SIGTERM 该项目 daemon 进程（仅快照中的
            # cwd/--project-root 锚定且为 daemon 的进程——supervisor 见 stop
            # flag 后自行退出，SIGTERM 不发给它；复核传 proot 做项目根锚定，
            # 防快照到 SIGTERM 之间 pid 被复用为其他项目 daemon 时误杀，
            # code-review item 33a5a217f420）
            for pid in target_pids:
                if _is_daemon_cmdline(pid, proot):
                    try:
                        os.kill(int(pid), signal.SIGTERM)
                    except (ProcessLookupError, PermissionError):
                        pass
        # ③ 轮询等待 daemon 与 supervisor 双双退出（上限约 30 秒）。
        # 只等快照 pid：并发时另一路新拉起的进程不在此列，不会让本路误等满窗。
        # 快照为空（/proc 不可用）时退化为项目级轮询。
        deadline = time.time() + 30
        # 退化路径终止判据（item b681fa8c8fd1）：is_running 在 /proc 不可用
        # 时按 fail-closed 恒 False，不能当作「进程已退出」的证据；改用一次
        # 独立的 /proc 可读性探测——不可枚举即无法复核，绝不据此判退出。
        # 异常口径取 Exception 与 is_running 的兜底宽度对齐（win32 侧
        # psutil 异常非 OSError）。
        def _proc_enumerable() -> bool:
            try:
                pal.proc_pids()
            except Exception:
                return False
            return True

        if target_pids:
            while time.time() < deadline:
                if not _alive_pids(target_pids):
                    break
                time.sleep(0.5)
        else:
            while time.time() < deadline:
                if not _proc_enumerable() or not is_running(proot):
                    break
                time.sleep(0.5)
        # ④ 超时兜底：对**快照中仍存活的残留**补 SIGKILL——不重新扫描项目
        # （并发场景下新拉起的 supervisor 绝不被误杀）
        remaining = _alive_pids(target_pids)
        sigkilled = []
        for pid in remaining:
            # 补杀前复核（code-review item 8cf4db59080d）：kill(pid, 0) 探活
            # 分不清「快照进程仍在」与「pid 已被复用给无关进程」，复核判
            # False（cmdline 已非本项目 daemon/supervisor，疑似 pid 复用）
            # 时跳过并计入 error，不盲杀；None（进程已退出/不可读）照旧
            # 尝试，由 ProcessLookupError 兜底。
            if _is_snapshot_proc_cmdline(pid, proot) is False:
                kill_errors.append(
                    f"SIGKILL pid {pid} 补杀前复核失败"
                    "（cmdline 已非本项目 daemon/supervisor，疑似 pid 复用），跳过补杀"
                )
                continue
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
        # 快照为空的退化路径（/proc 不可用）无快照 pid 可补杀/复核，只能依赖
        # ③ 的等待；超时仍判定运行中、或 /proc 已不可读无法复核停止结果时，
        # 均计入 error 不谎报 ok=True（kill-session 兜底已退役，该退化路径
        # 不再有强制清理手段）。
        if not target_pids:
            if not _proc_enumerable():
                kill_errors.append(
                    "无法定位停止目标（快照为空）且 /proc 已不可读，无法复核停止结果，"
                    "daemon 可能仍在运行"
                )
            elif is_running(proot):
                kill_errors.append(
                    "无法定位停止目标（/proc 不可用）且项目仍判定为运行中，daemon 可能未退出"
                )
        # ⑤ finally 清除 stop（无论成败）
        try:
            stop_flag.unlink()
        except OSError:
            pass
        return {
            "ok": not kill_errors,
            "error": "; ".join(kill_errors) if kill_errors else None,
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
