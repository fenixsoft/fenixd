"""
systemd_hosting.py — systemd 承载层（add-systemd-hosting）。

宿主机级事件（2026-11-04 全用户态 SIGKILL）实证：supervisor→daemon→dashboard
只住在 tmux、无任何 unit 时，「全部进程死亡」后无人拉回；进程内加固防不了
宿主机级事件，supervisor 看门狗自身也是链内进程（「看门狗没有看门狗」）。
systemd 是唯一能在该形态下拉回的进程外监督者。本模块承担承载层的全部机械面：

- unit 模板生成：每项目一条静态 unit ``fenixd-<项目名>.service``（ExecStart=
  supervisor --project-root，daemon 保持为 supervisor 子进程，systemd 监督对象
  是 supervisor 不是 daemon）+ 框架主树一条 ``fenix-dashboard.service``。
- 重启策略：两类 unit 均 ``Restart=on-failure`` + ``StartLimit`` 兜底；项目 unit
  以 ``SuccessExitStatus=75`` 声明 supervisor 有意放弃的专用码（熔断/放弃看护
  不被拉回，防熔断被架空为拉回风暴；退出码协议见 bin/fenixd_supervisor.py）。
  dashboard 无退出码协议：SIGTERM 干净收尾退出 0 在 on-failure 下本就不拉回。
- unit 运行环境：``EnvironmentFile``（0600）承载，密钥不裸写进 unit（全局可读）。
  env 捕获从在跑进程 ``/proc/<pid>/environ`` 机械捕获候选键集（非白名单凭记忆），
  套会话身份 denylist 前缀族过滤后落 0600 候选稿供人工审核。
- 幂等安装：unit 已存在且服务活跃时不重建不重启；systemctl 不可用（非 systemd
  环境）打印可读错误并拒绝，MUST NOT 静默降级为 tmux（tmux 承载已退役）。

本模块 MUST NOT import core.fenix_session（后者 import 本模块取 unit 名），
避免循环依赖；对 /proc 的进程扫描在此处自带最小实现。
"""

import hashlib
import os
import re
import subprocess
import tempfile
import threading
from pathlib import Path

from core.platform import api as pal
from core.platform.api import SystemdHostingError
from core.platform.linux import ENV_KEY_RE as _ENV_KEY_RE

# dashboard unit 固定名（框架主树唯一一条；hook_engine restart-dashboard、
# migrate 脚本、serve 接管豁免指引共用同一常量，防字面量漂移）
DASHBOARD_UNIT = "fenix-dashboard.service"

# systemd unit 安装目录（静态 unit；本模块假定以 root 运行——fenixd 宿主
# 即单用户 root 宿主机，与既有 tmux 承载同前提）
SYSTEMD_UNIT_DIR = Path("/etc/systemd/system")

# 项目 unit 停机上界：supervisor SIGTERM 转发收尾含排水窗（drain 缺省 1800s
# + 120s 余量）与 SIGKILL 等待，systemd 必须等它走完，不得提前 SIGKILL 打断
# 排水。2100s = 35min，覆盖 drain 上限 + 余量 + 启动期抖动。
TIMEOUT_STOP_SEC = 2100

# 重启间隔与 crash-loop 兜底：on-failure 覆盖崩溃主面，StartLimit 是
# 「秒崩循环」的最后防线（两类 unit 均配置）。
RESTART_SEC = "5s"
START_LIMIT_INTERVAL_SEC = "120s"
START_LIMIT_BURST = 5

# supervisor 有意放弃的专用退出码（熔断/放弃看护）：unit 模板以
# SuccessExitStatus 声明为成功——on-failure 不拉回。数值与
# bin/fenixd_supervisor.py 的 EXIT_GAVE_UP 成对维护，防字面量漂移。
SUPERVISOR_GAVE_UP_EXIT_CODE = 75

# 项目 unit 的 EnvironmentFile 路径（项目 .fenix 运行时目录，已被 gitignore
# 覆盖，密钥不入库）；dashboard unit 的在框架主树 .fenix 下。
ENV_FILE_BASENAME = "systemd.env"
DASHBOARD_ENV_BASENAME = "dashboard-systemd.env"
# env 候选稿后缀：捕获脚本只写候选稿，人工审核后提升为正式 EnvironmentFile
ENV_CANDIDATE_SUFFIX = ".candidate"


# SystemdHostingError 家址上收 core.platform.api（D 组契约面，见头部 import）
# ——W3 转发化后以同名字再导出，既有 ``core.systemd_hosting.SystemdHostingError``
# 引用（fenix_session/hook_engine 等）身份不变（is 同一类对象）。


# ── 会话身份 denylist（add-systemd-hosting：EnvironmentFile 候选稿过滤）─────
# 在跑进程的 environ 由启动它的 agent 会话透传（CLAUDE_PID 指向会话进程、
# CLAUDE_CODE_* 是会话元数据），systemd unit 承载的进程 MUST NOT 携带这些
# 键：CLAUDE_PID 会把 claude-watchdog 绑到早已退出的会话进程（自杀扳机）、
# CLAUDECODE=1 会改变子 agent 的自证行为。按前缀族过滤（错误码/键名会随
# CLI 版本演化，精确枚举防不住新形态；前缀族覆盖 CLAUDE_PID/CLAUDECODE/
# CLAUDE_CODE_SESSION_ID/CLAUDE_CODE_ENTRYPOINT 等全部会话身份键）。
SESSION_IDENTITY_DENYLIST_PREFIXES = (
    "CLAUDE_PID",
    "CLAUDECODE",
    "CLAUDE_CODE_",
    "AI_AGENT",
    "IS_SANDBOX",
    "GIT_ASKPASS",
)

# 合法 env 键名（/proc/<pid>/environ 可能含 bash 导出的函数键 `BASH_FUNC_…%%`
# 等，写入 EnvironmentFile 会被 systemd 拒绝整行解析，跳过）
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def systemctl_available() -> bool:
    """systemctl 是否可执行（非 systemd 环境 → False，调用方拒绝并给可读错误）。

    W3 起为 pal.systemctl_available 薄委托（D 组单缝上收 core.platform.linux）。
    """
    return pal.systemctl_available()


def _run_systemctl(args, timeout: float = 30) -> subprocess.CompletedProcess:
    """systemctl 调用单缝（subprocess.run，list argv 不经 shell）。

    systemctl 不可用时抛 SystemdHostingError（可读错误含「需要 systemd」指引），
    由调用方转成各自的错误返回形态（fenix_session 返回 dict，hook 记 failure）。

    W3 起为 pal.run_systemctl 薄委托（单缝实现逐字平移上收 pal，语义一字
    不动）；本文件内既有调用面（unit_installed/unit_active/install/stop/
    restart 等）零改动。可用性判定保留本模块先行（``systemctl_available``
    为既有 monkeypatch 缝，tests/test_systemd_hosting 缝契约），结论直传
    pal（``available=``），两因错误文案逐字不变。
    """
    return pal.run_systemctl(args, timeout=timeout, available=systemctl_available())


def _sanitize_unit_component(name: str) -> str:
    """项目名 → systemd unit 名安全段（[A-Za-z0-9-]，点号一并折叠）。

    unit 文件名里的点号会被 systemd 解析为后缀分隔符（``my.project.service``
    的「后缀」被读成 ``project.service``），与 tmux 会话名同患点号病——一律
    折叠为连字符；非法字符折叠后剩余空串回退 ``project``，掐头去尾的连字符
    去掉（``-proj-`` 会出现 ``fenixd--hash`` 双连字符名）。
    """
    folded = re.sub(r"[^A-Za-z0-9-]+", "-", name).strip("-")
    return folded or "project"


def unit_name_for(root) -> str:
    """项目根 → 唯一静态 unit 名 ``fenixd-<安全项目名>-<路径哈希6>.service``。

    安全化段取目录名（点号等非法字符折叠），追加以完整路径派生的 6 位哈希：
    不同扫描目录下的同名项目（unit 的 WorkingDirectory 各自指向自己的项目根）
    若只按目录名命名会在第二份安装时静默覆写第一份的 unit，哈希段保证跨路径
    唯一且同项目多入口计算结果一致（与退役的 tmux session 派生口径同构）。
    """
    proot = Path(root)
    digest = hashlib.md5(str(proot).encode()).hexdigest()[:6]
    base = _sanitize_unit_component(proot.name)
    return f"fenixd-{base}-{digest}.service"


def project_env_file(root) -> Path:
    """项目 unit 的正式 EnvironmentFile 路径（unit 模板引用同一函数，防漂移）。"""
    return Path(root) / ".fenix" / ENV_FILE_BASENAME


def dashboard_env_file(framework_root) -> Path:
    """dashboard unit 的正式 EnvironmentFile 路径（框架主树 .fenix 运行时目录）。"""
    return Path(framework_root) / ".fenix" / DASHBOARD_ENV_BASENAME


def _quoted_env_value(value: str) -> str:
    """EnvironmentFile 值落盘形态：含空白/引号/#/$/反斜杠的值以双引号包裹。

    转义形态经 systemd 249 真机实测（瞬态 unit + EnvironmentFile 往返探针，
    code-review item e63f37af8460）：双引号段内仅 ``\\\\`` 与 ``\\"`` 两个
    转义被折叠，其余 ``\\x``、单引号、``$``、``#`` 一律字面量且无变量展开，
    含单引号的值（代理网关 token/密码）以 ``"ab'cd"`` 裸放即往返等价；旧
    shell 风格单引号包裹 ``'ab'\\''cd'`` 同环境实测被解析成错误字面量
    ``ab''cd'``——单引号段没有字面单引号的表达，故含特殊字符的值一律改走
    双引号形态。纯安全字符的值裸写，保持文件可读可审。"""
    if value == "" or not re.search(r"[\s\"'#\\$]", value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def filter_session_identity(env: dict) -> dict:
    """按会话身份 denylist 前缀族过滤 env dict（返回新 dict，不改入参）。"""
    return {
        k: v
        for k, v in env.items()
        if not any(k.startswith(p) for p in SESSION_IDENTITY_DENYLIST_PREFIXES)
    }


def read_process_env(pid: int) -> dict:
    """读 /proc/<pid>/environ 为 dict（不可读/已退出 → 空 dict）。

    键集来源为在跑进程的实环境（design R1：非白名单凭记忆——漏掉 load-bearing
    键会让迁移后 agent run 全灭）。非法键名/含换行的值（bash 导出函数等）跳过：
    EnvironmentFile 行格式装不下，整行会被 systemd 拒解析。

    W3 起为 pal.process_environ 薄委托（B 组单点，含 _ENV_KEY_RE 同源，
    本模块以别名再导出供 :363 候选稿过滤共用）。
    """
    return pal.process_environ(pid)


# ── PATH 卫生基线（add-dispatch-precheck-true-fallback 3.1）─────────────────
# 基线目录集：会话 shell 常见具备而 systemd 承载进程常缺失的用户/系统 bin 目录。
# 比较与写入一律用展开后的绝对路径（env 文件值不做 ~ 展开——systemd 不展开
# 字面 ~，缺失会让保底/自愈 PATH 静默失效；``~/.local/bin`` 仅为文档记法）；
# Path.home() 在模块导入期取值（daemon 进程 HOME 即承载语义下的 home）。
PATH_BASELINE_DIRS: tuple = (
    str(Path.home() / ".local" / "bin"),
    "/usr/local/bin",
    "/usr/local/sbin",
    "/usr/sbin",
    "/usr/bin",
    "/sbin",
    "/bin",
)


def path_baseline_missing(path_value: str) -> list:
    """给定 PATH 值，返回其中缺失的基线目录（按基线序）。

    比较按展开后的绝对路径（见 PATH_BASELINE_DIRS 注）；空/缺席 PATH 视为
    全缺。migrate 摘要（3.3）与启动自检告警共用本判定单源。
    """
    present = {p for p in (path_value or "").split(":") if p}
    return [d for d in PATH_BASELINE_DIRS if d not in present]


def apply_path_baseline(env: dict) -> tuple:
    """env dict 的 PATH 值并集基线目录，返回 ``( healed dict, 追加目录清单 )``。

    add-dispatch-precheck-true-fallback 3.1：捕获源 PATH 缺失基线目录按序
    追加尾部；完整 PATH 逐字节不变（追加清单为空时原值原样返回）。留痕
    注释由调用方（render_env_file 的 path_note 形参）写入候选稿头部。
    """
    missing = path_baseline_missing(env.get("PATH", ""))
    if not missing:
        return env, []
    healed = dict(env)
    current = env.get("PATH", "")
    healed["PATH"] = (current + ":" if current else "") + ":".join(missing)
    return healed, missing


def resolve_baseline_home(env: dict | None = None) -> str | None:
    """HOME 基线取值（fix-push-credential-env-and-retry-rearm 3.1）。

    经 ``core.git_env.resolve_git_env`` 单源解析（env → pwd → 配置三级序），
    与推送子进程 env 注入共用同一判定，防承载层与运行时双源漂移。env 缺省
    取当前进程 environ。三级皆空返回 None（调用方不注入、不写保底值）。
    """
    from core.git_env import resolve_git_env

    return resolve_git_env(None, env=env if env is not None else None).resolved_home


def apply_home_baseline(env: dict) -> tuple:
    """env dict 的 HOME 基线补齐，返回 ``( healed dict, 补齐的 HOME 值或 None )``。

    fix-push-credential-env-and-retry-rearm 3.1（与 apply_path_baseline
    并列新增，PATH 产物逐字节不变）：捕获源 env 缺失或为空 HOME 时以
    ``resolve_baseline_home`` 单源补 ``HOME=<resolved>``；已含非空 HOME 时
    原值原样返回（补齐值为 None，产物与无此机制时逐字节一致）。三级解析
    全空时不注入（行为回退现状，补齐值为 None），由启动自检就该状态告警。
    """
    home = env.get("HOME")
    if isinstance(home, str) and home.strip():
        return env, None
    resolved = resolve_baseline_home(env)
    if not resolved:
        return env, None
    healed = dict(env)
    healed["HOME"] = resolved
    return healed, resolved


def append_env_path_dirs(env_file, dirs) -> list:
    """向既有 EnvironmentFile 的 PATH 行幂等追加目录（原子写）。

    add-dispatch-precheck-true-fallback 2.4 PATH 自愈写侧单源：仅当给定目录
    确有缺失才改写（幂等——重复调用不重复追加、无缺失零改写零 mtime 变化）；
    文件无 PATH 行时补行。写入经 write_env_file（tmp+rename、0600 保持）。
    返回实际追加目录清单（空 = 未改写）。
    """
    env_file = Path(env_file)
    text = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
    lines = text.splitlines()
    current = ""
    for line in lines:
        if line.startswith("PATH="):
            raw = line[len("PATH="):].strip()
            # 双引号形态反解（_quoted_env_value 的逆：仅 \\" 与 \\\\ 两个转义）
            if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
                raw = raw[1:-1].replace('\\"', '"').replace("\\\\", "\\")
            current = raw
            break
    present = {p for p in current.split(":") if p}
    missing = [d for d in dirs if d and d not in present]
    if not missing:
        return []
    new_path = (current + ":" if current else "") + ":".join(missing)
    out = []
    replaced = False
    for line in lines:
        if line.startswith("PATH="):
            out.append(f"PATH={_quoted_env_value(new_path)}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"PATH={_quoted_env_value(new_path)}")
    write_env_file("\n".join(out) + "\n", env_file)
    return missing


def render_env_file(env: dict, path_note=None, home_note=None) -> str:
    """env dict → EnvironmentFile 文本（渲染原语自含防线，不依赖唯一调用链）。

    denylist 过滤（filter_session_identity）、非法键名与含换行值的剔除在
    本函数原地兜底（code-review item 7a87a7581069）：read_process_env /
    capture_env_candidate 已各挡一道，但绕过 capture 链直调本函数的代码
    （如从配置文件读取 env 合成）不会再把坏行或会话身份键（CLAUDE_PID
    自杀扳机、CLAUDECODE 自证行为）写进 0600 EnvironmentFile。对已过滤
    入参幂等（重复过滤/剔除为无操作），capture 链现有行为不变。

    ``path_note``（add-dispatch-precheck-true-fallback 3.1）：传入实际追加
    的基线目录清单时在头部写留痕注释（已追加目录与原因）；空/缺席时不
    产生任何额外行——完整 PATH 产物逐字节不变。

    ``home_note``（fix-push-credential-env-and-retry-rearm 3.1）：传入实际
    补齐的 HOME 值时在头部写留痕注释（同 PATH 追加留痕格式）；None 时不
    产生任何额外行——已含 HOME 的候选稿产物逐字节不变。
    """
    filtered = filter_session_identity(env)
    lines = [
        "# fenixd systemd EnvironmentFile 候选稿（add-systemd-hosting）",
        "# 由在跑进程 /proc/<pid>/environ 机械捕获 + 会话身份 denylist 过滤生成，",
        "# 人工审核后提升为正式 EnvironmentFile（unit 引用路径见 unit 文件）。",
    ]
    if path_note:
        lines.extend([
            "# PATH 卫生（add-dispatch-precheck-true-fallback 3.1）：捕获源 PATH"
            f" 缺失基线目录，已按序追加尾部：{'、'.join(path_note)}",
            "# 原因：systemd 承载进程不继承会话 shell 的 PATH 拼装，缺基线目录会"
            "使 ~/.local/bin 等位置的 harness 可执行文件在服务环境不可达。",
        ])
    if home_note:
        lines.extend([
            "# HOME 卫生（fix-push-credential-env-and-retry-rearm 3.1）：捕获源"
            f" env 缺失 HOME，已以解析器单源补齐：HOME={home_note}",
            "# 原因：systemd 承载进程常缺失 HOME，git 找不到 ~/.git-credentials"
            "/~/.gitconfig 时推送凭证只剩 remote URL 内嵌单腿。",
        ])
    lines.append("")
    for key in sorted(filtered):
        # 键名/值形状校验与 read_process_env 同口径：EnvironmentFile 行格式
        # 装不下非法键名与含换行的值（整行被 systemd 拒解析），剔除而非渲染。
        if not _ENV_KEY_RE.match(key):
            continue
        value = filtered[key]
        if "\n" in value or "\r" in value:
            continue
        lines.append(f"{key}={_quoted_env_value(value)}")
    return "\n".join(lines) + "\n"


def write_env_file(text: str, target: Path) -> Path:
    """0600 落盘 EnvironmentFile（含候选稿）：原子写（tmp+rename）+ chmod 0600。

    密钥（ANTHROPIC_AUTH_TOKEN 等）只进 0600 文件，MUST NOT 裸写进 unit
    （unit 全局可读）；权限收紧失败（chmod 抛错）按写失败抛出——宽权限的
    密钥文件比没有文件更危险。
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    # mkstemp 唯一临时名（pid+tid 后缀、同目录）：固定 <name>.tmp 在两进程
    # 并发写同一目标时后写者截断先写者未替换完的临时文件，os.replace 可落盘
    # 交叉内容（对齐 state_machine._atomic_write_text / fs_utils 原子写惯例）。
    tmp = None
    try:
        tmp_fd, tmp_name = tempfile.mkstemp(
            prefix=f".{target.name}.{os.getpid()}.{threading.get_ident()}.",
            suffix=".tmp",
            dir=str(target.parent),
        )
        tmp = Path(tmp_name)
        # fdopen 失败路径显式接管（对齐 state_machine._atomic_write_text 先例
        # cbb57806fbfd）：with 的 close 只在 fdopen 成功后才生效，fdopen 自身
        # 抛错时裸 fd 无人关闭——f 为 None 时兜底 os.close。
        f = None
        try:
            f = os.fdopen(tmp_fd, "w", encoding="utf-8")
            f.write(text)
        finally:
            if f is not None:
                f.close()
            else:
                try:
                    os.close(tmp_fd)
                except OSError:
                    pass
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except OSError as e:
        if tmp is not None:
            try:
                tmp.unlink()
            except OSError:
                pass
        raise SystemdHostingError(f"写 EnvironmentFile {target} 失败: {e}") from e
    return target


def capture_env_candidate(pid: int, target: Path, path_report=None, home_report=None) -> dict:
    """从在跑进程捕获 env → denylist 过滤 → PATH/HOME 基线 → 写 0600 候选稿。

    返回过滤后的键集（供 migrate 预演打印摘要；PATH 已含基线并集，HOME
    缺失时已补齐）；进程不可读时抛 SystemdHostingError（候选稿是迁移验收
    的 env 冒烟基线，静默空稿会让人工审核无从下手）。

    PATH 卫生（add-dispatch-precheck-true-fallback 3.1）：捕获源 PATH 缺失
    基线目录（PATH_BASELINE_DIRS）按序追加尾部，候选稿头部留痕「已追加
    目录清单与原因」；完整 PATH 产物逐字节不变。``path_report`` 传 list 时
    收集实际追加目录（migrate 摘要 3.3「完整」/「补齐 <清单>」结论行的
    判定单源）。

    HOME 卫生（fix-push-credential-env-and-retry-rearm 3.1）：捕获源 env
    缺失 HOME 时以解析器单源补齐并留痕；已含 HOME 时产物逐字节不变。
    ``home_report`` 传 list 时收集补齐的 HOME 值（migrate 摘要 HOME 结论行
    的判定单源，与 PATH 结论并列）。
    """
    env = read_process_env(pid)
    if not env:
        raise SystemdHostingError(
            f"无法读取进程 {pid} 的 /proc/<pid>/environ（进程已退出或权限不足），"
            "env 候选稿捕获失败"
        )
    filtered = filter_session_identity(env)
    healed, appended = apply_path_baseline(filtered)
    if path_report is not None:
        path_report.extend(appended)
    healed, home_added = apply_home_baseline(healed)
    if home_report is not None:
        home_report.extend([home_added] if home_added else [])
    write_env_file(
        render_env_file(healed, path_note=appended, home_note=home_added),
        Path(f"{target}{ENV_CANDIDATE_SUFFIX}"),
    )
    return healed


# ── unit 模板 ────────────────────────────────────────────────────────────


def _validate_unit_path(path_value, label: str) -> None:
    """裸插值进 unit 文本的路径校验：含空白/引号即拒绝，不静默产出坏 unit。

    unit 名一侧已有 _sanitize_unit_component 折叠非法字符，文件内路径一侧
    的防线与之对称：systemd 的 ExecStart 按空白切分参数（含空格的路径被拆
    成多个参数、指向错误路径），unit 文本按行解析指令（含换行的路径会把
    换行后的文本当新指令行写入，同文件后段 Restart 等指令被移位），引号
    则破坏 systemd 自身的引号语义——模板侧无法安全转义，只能拒绝安装并
    给可读错误。派生路径（supervisor/env_file 等）继承 root 前缀，校验
    入口一处即覆盖 WorkingDirectory/ExecStart/EnvironmentFile/Description
    全部插值位。
    """
    text = str(path_value)
    if re.search(r"[\s\"']", text):
        raise SystemdHostingError(
            f"{label}含空白或引号字符，无法安全写入 systemd unit 文本"
            "（空格会拆错 ExecStart 参数、换行会注入新指令行），拒绝安装: "
            f"{text}"
        )


def render_project_unit(root, python_executable: str | None = None) -> str:
    """渲染 ``fenixd-<项目名>.service`` unit 文本。

    - ExecStart = supervisor --project-root：daemon 保持为 supervisor 子进程，
      systemd 监督对象是 supervisor（与「唯一托管启动路径」语义一致，daemon
      MUST NOT 被直启）。
    - Restart=on-failure + SuccessExitStatus=75：崩溃/异常退出被拉回；supervisor
      熔断与放弃看护（75）及停机收尾（0）不拉回——Restart=always 会结构性架空
      熔断（新 pid 清熔断标记→再拉→再熔断循环），被 design 决策 1 否决。
    - EnvironmentFile 用 ``-`` 前缀（候选稿未提升/未捕获时 unit 仍可启动，env
      缺失面由迁移验收的 env 冒烟兜底）。
    - KillMode=mixed：SIGTERM 只发主进程（supervisor 自己转发收尾 daemon 与
      排水窗），超时后 SIGKILL 才扩展到整个 cgroup。
    """
    proot = Path(root)
    _validate_unit_path(proot, "项目根路径")
    interpreter = python_executable or "python3"
    # ExecStart 裸插值位与项目根同防线（code-review item a42cfc33176e）：
    # 含空白的解释器路径（虚拟环境/自定义安装目录）会被 systemd 拆成多个
    # argv，服务无法启动且难回溯。
    _validate_unit_path(interpreter, "Python 解释器路径")
    supervisor = proot / ".fenix" / "bin" / "fenixd_supervisor.py"
    env_file = project_env_file(proot)
    # PATH 保底（add-dispatch-precheck-true-fallback 3.2）：恒为展开绝对路径
    # （systemd 不展开 ~，字面 ~ 目录项会使保底 PATH 静默失效）。
    fallback_path = ":".join(PATH_BASELINE_DIRS)
    # HOME 保底（fix-push-credential-env-and-retry-rearm 3.1）：经解析器单源
    # 取值（env → pwd → 配置三级序）；三级皆空时不写保底行（无值可写，
    # fail-open 回退现状），由启动自检就该状态告警。
    resolved_home = resolve_baseline_home()
    home_block = ""
    if resolved_home:
        home_block = (
            "# HOME 保底（fix-push-credential-env-and-retry-rearm 3.1）：EnvironmentFile 在场\n"
            "# 且含 HOME 时其值覆盖本行（systemd 加载顺序语义不变）；env 文件缺席/无\n"
            "# HOME 键时本行兜底，保证 git 凭证文件（~/.git-credentials）在服务环境可达。\n"
            f"Environment=HOME={resolved_home}\n"
        )
    return f"""\
[Unit]
Description=Fenixd daemon hosting (supervisor) for {proot}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={proot}
# PATH 保底（add-dispatch-precheck-true-fallback 3.2）：EnvironmentFile 在场时
# 其 PATH 行覆盖本行（systemd 语义：EnvironmentFile 晚于 Environment 读入，
# 同名变量以 EnvironmentFile 为准）；env 文件缺席/未提升时本行兜底，保证
# ~/.local/bin 等常见安装目录的 harness 可执行文件在服务环境可达。
Environment=PATH={fallback_path}
{home_block}ExecStart={interpreter} {supervisor} --project-root {proot}
EnvironmentFile=-{env_file}
Restart=on-failure
RestartSec={RESTART_SEC}
SuccessExitStatus={SUPERVISOR_GAVE_UP_EXIT_CODE}
TimeoutStopSec={TIMEOUT_STOP_SEC}
KillMode=mixed
StartLimitIntervalSec={START_LIMIT_INTERVAL_SEC}
StartLimitBurst={START_LIMIT_BURST}

[Install]
WantedBy=multi-user.target
"""


def render_dashboard_unit(framework_root, python_executable: str | None = None) -> str:
    """渲染 ``fenix-dashboard.service`` unit 文本。

    - Environment=FENIX_DASHBOARD_DETACH=1：serve 在 PPID==1 且缺该变量时
      exit(1)（孤儿启动拒绝），systemd 主进程 PPID 恒为 1——不设则无限崩溃
      循环，design 决策 3。
    - 无 SuccessExitStatus：dashboard 无熔断/放弃看护语义，SIGTERM 干净收尾
      退出 0 在 Restart=on-failure 下本就不拉回（不适用退出码协议）。
    """
    froot = Path(framework_root)
    _validate_unit_path(froot, "框架主树路径")
    interpreter = python_executable or "python3"
    # 同 render_project_unit：ExecStart 裸插值位拒绝空白/引号解释器路径
    # （code-review item a42cfc33176e）。
    _validate_unit_path(interpreter, "Python 解释器路径")
    entry = froot / "bin" / "fenix_dashboard.py"
    env_file = dashboard_env_file(froot)
    return f"""\
[Unit]
Description=Fenix Dashboard (framework main tree)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={froot}
ExecStart={interpreter} {entry} --serve
Environment=FENIX_DASHBOARD_DETACH=1
EnvironmentFile=-{env_file}
Restart=on-failure
RestartSec={RESTART_SEC}
TimeoutStopSec=60
KillMode=mixed
StartLimitIntervalSec={START_LIMIT_INTERVAL_SEC}
StartLimitBurst={START_LIMIT_BURST}

[Install]
WantedBy=multi-user.target
"""


# ── systemctl 查询与安装 ─────────────────────────────────────────────────


def unit_installed(unit: str) -> bool:
    """unit 是否已安装（list-unit-files 有该条目）。

    systemctl 不可用抛 SystemdHostingError——「装没装」在无 systemd 环境不可判，
    静默 False 会让 stop 双轨误走直接信号链，违反双轨判定语义。
    """
    r = _run_systemctl(["list-unit-files", "--no-legend", unit], timeout=15)
    return r.returncode == 0 and bool(r.stdout.strip())


def unit_active(unit: str) -> bool:
    """unit 服务是否活跃（is-active 返回 0）。"""
    return _run_systemctl(["is-active", unit], timeout=15).returncode == 0


def write_unit_file(unit: str, content: str) -> Path:
    """unit 文本写入 systemd 目录（0600 不需要——unit 本身无密钥，0644 全局可读）。

    公开原语：install_* = 本函数 + _enable_now；migrate_to_systemd 的 ① 阶段
    （写 unit 不 enable）单独消费本函数，enable 推迟到拆完旧链的 ③ 阶段，
    保证无双托管窗口（design 决策 5）。
    """
    target = SYSTEMD_UNIT_DIR / unit
    # mkstemp 唯一临时名（pid+tid 后缀、同目录）：与 write_env_file 同款并发
    # 互踩防线，对齐仓库既有原子写惯例；失败路径尽力清理临时文件（唯一名
    # 不会像固定名那样被下次写入自然覆盖，残留会积累）。
    tmp = None
    try:
        SYSTEMD_UNIT_DIR.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_name = tempfile.mkstemp(
            prefix=f".{target.name}.{os.getpid()}.{threading.get_ident()}.",
            suffix=".tmp",
            dir=str(SYSTEMD_UNIT_DIR),
        )
        tmp = Path(tmp_name)
        # fdopen 失败路径显式接管（对齐 state_machine._atomic_write_text 先例
        # cbb57806fbfd）：with 的 close 只在 fdopen 成功后才生效，fdopen 自身
        # 抛错时裸 fd 无人关闭——f 为 None 时兜底 os.close。
        f = None
        try:
            f = os.fdopen(tmp_fd, "w", encoding="utf-8")
            f.write(content)
        finally:
            if f is not None:
                f.close()
            else:
                try:
                    os.close(tmp_fd)
                except OSError:
                    pass
        os.chmod(tmp, 0o644)
        os.replace(tmp, target)
    except OSError as e:
        if tmp is not None:
            try:
                tmp.unlink()
            except OSError:
                pass
        raise SystemdHostingError(
            f"写 unit 文件 {target} 失败: {e}（需要 root 权限）"
        ) from e
    return target


def _enable_now(unit: str) -> None:
    """daemon-reload + enable --now（写完 unit 后使 systemd 识别并拉起）。"""
    r = _run_systemctl(["daemon-reload"], timeout=30)
    if r.returncode != 0:
        raise SystemdHostingError(
            f"systemctl daemon-reload 失败: {(r.stderr or r.stdout).strip()}"
        )
    r = _run_systemctl(["enable", "--now", unit], timeout=60)
    if r.returncode != 0:
        raise SystemdHostingError(
            f"systemctl enable --now {unit} 失败: {(r.stderr or r.stdout).strip()}"
        )


def install_project_unit(root) -> dict:
    """安装（如缺）并 enable --now 项目 unit；幂等：已装且活跃时不重建不重启。

    Returns: {"ok": bool, "error": str|None, "already": bool, "unit": str}
    """
    proot = Path(root)
    unit = unit_name_for(proot)
    if unit_installed(unit) and unit_active(unit):
        return {"ok": True, "error": None, "already": True, "unit": unit}
    write_unit_file(unit, render_project_unit(proot))
    _enable_now(unit)
    return {"ok": True, "error": None, "already": False, "unit": unit}


def install_dashboard_unit(framework_root) -> dict:
    """安装（如缺）并 enable --now ``fenix-dashboard.service``；幂等同上。"""
    froot = Path(framework_root)
    unit = DASHBOARD_UNIT
    if unit_installed(unit) and unit_active(unit):
        return {"ok": True, "error": None, "already": True, "unit": unit}
    write_unit_file(unit, render_dashboard_unit(froot))
    _enable_now(unit)
    return {"ok": True, "error": None, "already": False, "unit": unit}


def stop_unit_no_block(unit: str) -> None:
    """``systemctl stop --no-block``：只排队停机指令即刻返回。

    同步 ``systemctl stop`` 最坏等待为 TimeoutStopSec（排水上界量级），会挂死
    dashboard HTTP 线程，破坏现行有界契约（design 决策 4）——stop 路径一律
    --no-block，等待由调用方自己的 ≤30s 轮询承担。
    """
    r = _run_systemctl(["stop", "--no-block", unit], timeout=15)
    if r.returncode != 0:
        raise SystemdHostingError(
            f"systemctl stop --no-block {unit} 失败: {(r.stderr or r.stdout).strip()}"
        )


def restart_dashboard_unit() -> dict:
    """``systemctl restart --no-block fenix-dashboard``（restart-dashboard 动作执行侧）。

    Returns: {"status": "success"|"failure"|"skipped", "detail": str}
    unit 未安装 → skipped（与 tmux 无会话时的静默 skip 对齐，环境态非故障）。

    同步 ``systemctl restart`` 最坏等待为 dashboard unit 的 TimeoutStopSec=60
    （停机排水逼近上界时挂死 hook 线程，且 subprocess 超时按失败上报而 systemd
    侧重启可能实际完成，结果与事实相反）——与 stop 路径同款 ``--no-block``
    （design 决策 4），就绪确认由调用方（hook_engine restart-dashboard）既有的
    端口轮询探测承担。
    """
    if not systemctl_available():
        return {
            "status": "skipped",
            "detail": "systemctl 不可用（无 systemd 环境），restart-dashboard 静默跳过",
        }
    if not unit_installed(DASHBOARD_UNIT):
        return {
            "status": "skipped",
            "detail": f"{DASHBOARD_UNIT} unit 未安装（dashboard 未以 systemd 承载），静默跳过",
        }
    r = _run_systemctl(["restart", "--no-block", DASHBOARD_UNIT], timeout=15)
    if r.returncode != 0:
        return {
            "status": "failure",
            "detail": (
                f"systemctl restart --no-block {DASHBOARD_UNIT} 失败: "
                f"{(r.stderr or r.stdout).strip()}"
            ),
        }
    return {
        "status": "success",
        "detail": f"{DASHBOARD_UNIT} 重启指令已排队（--no-block），就绪由调用方端口探测确认",
    }


# ── /proc 最小进程扫描（本模块自带，不 import fenix_session 防循环）────────


def find_framework_dashboard_pid() -> int | None:
    """定位在跑的 fenix_dashboard.py --serve 进程 pid（env 捕获/搬迁验收用）。

    判据：Python 解释器执行 fenix_dashboard.py 且带 --serve；命中多个（理论
    上不应发生——serve 端口独占）返回首个。/proc 不可用返回 None。
    """
    try:
        pids = os.listdir("/proc")
    except OSError:
        return None
    for pid in pids:
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                raw = f.read().decode("utf-8", errors="replace")
        except (OSError, ValueError):
            continue
        argv = [t for t in raw.split("\x00") if t]
        if not argv or not Path(argv[0]).name.startswith("python"):
            continue
        if not any(t.endswith("fenix_dashboard.py") for t in argv):
            continue
        if "--serve" in argv:
            return int(pid)
    return None
