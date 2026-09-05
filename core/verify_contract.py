"""verify_contract.py — 声明式验证契约（``.fenix/verify.yaml``）加载与执行。

## 为什么需要这个文件（作用）

Fenix 是通用开发框架，被管项目形态各异：前端应用有构建产物（dist/build/…，
名字也不尽相同），服务端应用直接跑源码，CLI 工具可能没有 HTTP 入口。「最终
用户验证」必须测**被测实现 fresh 构建出的可运行形态**，但框架此前对「应用
如何构建、如何被服务、何时算就绪」没有任何声明：

- dashboard 型项目靠 planner 臆测场景 URL（常写 8787）+ ``commands.start``
  兜底 + 端口改写；合并后若产物未重建，验证测到的是**上一次构建的陈旧产物**
  （fast-track 死锁复盘：实现者每轮花 30+ 分钟手工重建 dist 并考古验证环境）。
- 「场景 URL 已可达即跳过自愈」的捷径对构建型应用是陷阱——8787 活着就直接
  用陈旧实例，新鲜实现从未被测过。

验证契约把三件事变成**项目内随仓库提交的声明**，框架在每轮验证前依次执行：

1. ``prepare``——构建（可选）：保证被服务产物包含最新合并实现；
2. ``serve``——被测实例如何启动：静态目录（框架内置服务器）或自定义命令；
3. ``ready``——就绪探针：确认实例可用后再跑场景。

随后把场景 URL **全量改写到本次服务实例**（BASE_URL 注入铁律：场景永远打
新鲜实例，不依赖 planner 臆测的地址；planner 生成什么 URL 都会被覆盖）。

契约缺失时全部回退旧行为（``commands.start`` + 端口改写），存量项目零迁移。

## 文件位置与形态

- 路径：``<项目根>/.fenix/verify.yaml``，随仓库提交、对 agent 与人类可读。
  （历史注：``.fenix`` 曾是项目根的自引用符号链接，彼时该路径物理上即项目根
  ``verify.yaml``；现 ``.fenix`` 为实体目录，状态文件均已迁入其中。）
- 顶层就是字段映射，无包裹层。YAML 解析失败按「无契约」处理并记 warning。

## 字段说明（模板即本文档，逐字段语义如下）

.. code-block:: yaml

    # ── 可选。构建步骤列表：验证前在项目根（主树）逐条执行，保证被服务
    # 产物包含最新合并的实现。无构建步骤的应用（纯源码运行型）整段省略。
    prepare:
      - run: npm run build            # 必填。字符串=经 shell 执行；列表=argv 直接执行
        cwd: core/dashboard/static    # 可选。相对项目根的工作目录，缺省=项目根
    # ── 可选。被测实例的启动方式。缺省回退 config commands.start（旧行为）。
    serve:
      kind: static                   # static=框架内置静态服务器（服务 root 目录）
                                     # command=启动长驻服务命令（同 commands.start 形态）
      root: core/dashboard/static    # kind=static 必填。**URL 空间的根目录**（相对
                                     # 项目根）：选目录时保证场景路径在其下成立——
                                     # 例如应用以 /dist/ 路径访问时，root 应取其
                                     # 父目录（static）而非 dist 本身
      # cmd: python3 -m http.server {port}  # kind=command 必填。shell 命令，项目根
                                     # 为 cwd。端口写 {port} 占位符：框架启动前
                                     # 分配空闲端口替换，并同值导出
                                     # FENIX_VERIFY_PORT 环境变量（二选一引用）
      # port: 8787                         # kind=command 可选。legacy 端口提示（仅
                                     # 未迁移契约的邻近扫描兜底用；引用 {port}
                                     # 后无需再填）
    # ── 可选。就绪探针；缺省探被测实例根路径、期望 200、等待 60 秒。
    ready:
      url: /#/overview               # 探针路径（相对被测实例），缺省 /
      expect: 200                    # 期望 HTTP 状态码，缺省 200
      timeout: 60                    # 就绪等待上限（秒），缺省 60

## 语义要点

- **static 模式无条件新鲜服务**：不做「已可达即跳过」——场景 origin 全量改写
  到本次实例。这是对陈旧产物陷阱的结构性修复，不是可选项。
- **command 模式端口注入**：框架分配空闲端口，经 ``{port}`` 占位符与
  ``FENIX_VERIFY_PORT`` 环境变量注入 serve.cmd——实例永不与既有实例争抢
  端口（与 static 模式「框架分配、实例消费」同范式）。未消费注入的存量
  契约由进程归属/邻近扫描兜底发现并记迁移告警。
- ``prepare`` 失败＝验证环境错误（返回不可达 + 说明），验证门禁会拦截、
  不会判 verified/bug-found——构建失败不是产品缺陷。
"""

import os
import re
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socket import socket
from typing import Optional
from urllib.request import Request, urlopen

import yaml

from core.proc_utils import find_free_port

CONTRACT_FILENAME = "verify.yaml"
PREPARE_STEP_TIMEOUT = 600  # 单条构建步骤上限（秒）：构建慢是常态，600s 内完不成应修构建
DEFAULT_READY_TIMEOUT = 60

# worktree node_modules 供给模式（verify.yaml deps_mode > config verify.deps_mode > 默认）
DEPS_MODES = ("prefer-offline", "hardlink")
DEFAULT_DEPS_MODE = "prefer-offline"


@dataclass
class PrepareStep:
    """一条构建步骤：``run`` 在 ``cwd``（相对项目根）下执行。"""

    run: object  # str（shell）或 list（argv）
    cwd: str = ""


@dataclass
class ServeSpec:
    """被测实例启动方式：``static``（内置静态服务器）或 ``command``（自定义命令）。"""

    kind: str  # "static" | "command"
    root: str = ""  # kind=static：URL 空间根目录（相对项目根）
    cmd: str = ""  # kind=command：shell 命令；端口写作 {port} 占位符（框架
    # 分配空闲端口替换，并同值导出 FENIX_VERIFY_PORT 环境变量）
    port: Optional[int] = None  # kind=command：legacy 端口提示（仅未迁移
    # 契约的邻近扫描兜底用；引用 {port} 后无需再填）


@dataclass
class ReadyProbe:
    """就绪探针：GET ``url`` 期待 ``expect`` 状态码，最长等 ``timeout`` 秒。"""

    url: str = "/"
    expect: int = 200
    timeout: int = DEFAULT_READY_TIMEOUT


@dataclass
class VerifyContract:
    """验证契约：prepare（构建）→ serve（被测实例）→ ready（就绪探针）。"""

    prepare: list = field(default_factory=list)  # list[PrepareStep]
    serve: Optional[ServeSpec] = None
    ready: ReadyProbe = field(default_factory=ReadyProbe)
    deps_mode: str = ""  # worktree node_modules 供给模式；空=未指定（走 config/默认）


def load_verify_contract(project_root: Path, logger=None) -> Optional[VerifyContract]:
    """加载 ``.fenix/verify.yaml``；文件缺失/解析失败返回 None（回退旧行为）。

    解析失败属配置错误而非「无契约」：记 warning 提醒修复（静默吞掉会让
    用户以为契约生效了）。
    """
    path = Path(project_root) / ".fenix" / CONTRACT_FILENAME
    if not path.is_file():
        # 旧布局守卫：.fenix 为实体目录而契约文件仍在项目根 = 契约静默失效
        # （help-center 洗白事故的根因形态）。大声告警而非吞掉，仍按无契约回退。
        if logger:
            root_yaml = Path(project_root) / CONTRACT_FILENAME
            if (root_yaml.is_file()
                    and not (Path(project_root) / ".fenix").is_symlink()):
                logger.warning(
                    "verify_contract",
                    f"检测到旧布局：{CONTRACT_FILENAME} 位于项目根而 .fenix 为"
                    "实体目录，验证契约不会被加载。请迁移到 .fenix/"
                    f"{CONTRACT_FILENAME}（状态文件已统一迁入 .fenix/，见 932a078）",
                )
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        if logger:
            logger.warning("verify_contract", f"验证契约解析失败（按无契约回退）: {e}")
        return None
    if not isinstance(data, dict):
        return None

    prepare = []
    for step in data.get("prepare") or []:
        if isinstance(step, str):
            prepare.append(PrepareStep(run=step))
        elif isinstance(step, dict) and step.get("run"):
            prepare.append(PrepareStep(run=step["run"], cwd=str(step.get("cwd") or "")))
    serve = None
    serve_data = data.get("serve")
    if isinstance(serve_data, dict) and serve_data.get("kind") in ("static", "command"):
        port = serve_data.get("port")
        serve = ServeSpec(
            kind=serve_data["kind"],
            root=str(serve_data.get("root") or ""),
            cmd=str(serve_data.get("cmd") or ""),
            port=int(port) if port else None,
        )
    ready_data = data.get("ready") or {}
    ready = ReadyProbe(
        url=str(ready_data.get("url") or "/") or "/",
        expect=int(ready_data.get("expect") or 200),
        timeout=int(ready_data.get("timeout") or DEFAULT_READY_TIMEOUT),
    )
    # 端口注入迁移告警（不阻断）：cmd 未引用注入端口时实例会与既有实例
    # 争抢固定端口（dashboard 端口独占语义下 = 杀掉占用者接管，2026-09-05
    # 验证实例顺带杀主树 dashboard 事故的根源），由未消费注入的兜底发现
    # 链路续命。存量为零迁移原则只告警、不拒绝。
    if (serve is not None and serve.kind == "command" and serve.cmd
            and "{port}" not in serve.cmd
            and "$FENIX_VERIFY_PORT" not in serve.cmd and logger):
        logger.warning(
            "verify_contract",
            "serve.cmd 未引用端口注入（{port} 占位符或 $FENIX_VERIFY_PORT "
            "环境变量），验证实例将与既有实例争抢固定端口；建议迁移：cmd 中"
            "的端口写作 {port}，框架自动分配空闲端口注入")
    deps_mode = ""
    if data.get("deps_mode") is not None:
        if data["deps_mode"] in DEPS_MODES:
            deps_mode = data["deps_mode"]
        elif logger:
            logger.warning(
                "verify_contract",
                f"verify.yaml deps_mode 非法（忽略，可用值 {list(DEPS_MODES)}）: "
                f"{data['deps_mode']}")
    return VerifyContract(prepare=prepare, serve=serve, ready=ready,
                          deps_mode=deps_mode)


def resolve_deps_mode(contract=None, config_value=None) -> str:
    """deps_mode 解析优先级：verify.yaml deps_mode > config verify.deps_mode > 默认。"""
    if contract is not None and getattr(contract, "deps_mode", "") in DEPS_MODES:
        return contract.deps_mode
    if config_value in DEPS_MODES:
        return config_value
    return DEFAULT_DEPS_MODE


def read_config_deps_mode(project_root) -> str:
    """从项目 .fenix/config.yaml 读 verify.deps_mode（轻量直读，容错返回空串）。

    供无 pm 配置通道的调用方（worktree_manager）使用；非法值/缺失返回空串
    （由 resolve_deps_mode 落到默认）。
    """
    try:
        path = Path(project_root) / ".fenix" / "config.yaml"
        if not path.is_file():
            return ""
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        verify_raw = raw.get("verify")
        val = verify_raw.get("deps_mode") if isinstance(verify_raw, dict) else None
        return val if val in DEPS_MODES else ""
    except Exception:
        return ""


def run_prepare_steps(contract: VerifyContract, project_root: Path) -> Optional[str]:
    """在项目根逐条执行构建步骤。成功返回 None，失败返回人类可读错误说明。

    构建失败＝验证环境错误（调用方据此判不可达，交验证门禁拦截），不得
    静默跳过——带着陈旧产物继续验证正是本契约要消灭的场景。
    """
    for i, step in enumerate(contract.prepare, 1):
        cwd = (Path(project_root) / step.cwd) if step.cwd else Path(project_root)
        cmd = step.run if isinstance(step.run, list) else str(step.run)
        use_shell = not isinstance(step.run, list)
        try:
            r = subprocess.run(
                cmd, shell=use_shell, cwd=str(cwd),
                capture_output=True, text=True, timeout=PREPARE_STEP_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return f"第 {i} 步超时（>{PREPARE_STEP_TIMEOUT}s）: {cmd}"
        except OSError as e:
            return f"第 {i} 步启动失败: {e}"
        if r.returncode != 0:
            tail = (r.stderr or r.stdout or "").strip()[-300:]
            return f"第 {i} 步退出码 {r.returncode}: {cmd}\n{tail}"
    return None


def _find_free_port() -> int:
    # 兼容引用（verify-process-lifecycle D5）：实为共用助手 core.proc_utils.find_free_port
    #（v2_dev_server 端口分配路径与静态/命令实例同源）。
    return find_free_port()


class StaticVerifyServer:
    """内置静态被测实例：服务 ``root`` 目录，可探活、可停止。

    服务范围由配置 ``verify.static_scope`` 决定（main=主树，默认；
    worktree=验证 worktree，方案 2）——本类只负责"服务一个目录"，
    目录在哪由调用方决定。
    """

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        handler = lambda *args, **kw: SimpleHTTPRequestHandler(  # noqa: E731
            *args, directory=str(self.root), **kw)
        self._port = _find_free_port()
        self._httpd = ThreadingHTTPServer(("127.0.0.1", self._port), handler)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._port}"

    def stop(self):
        try:
            self._httpd.shutdown()
            self._httpd.server_close()
        except OSError:
            pass


class CommandVerifyServer:
    """命令型被测实例（serve.kind=command 的 worktree 隔离）。

    full-stack 场景的解法：以 serving worktree 为 cwd 启动真实服务命令——
    Python 后端 API 与前端静态产物同为本次实现的真实形态。static 模式只有
    静态文件，交付物 API 会被迫 mock（假阴性放大器）。本类持进程组句柄、
    可探活、可停止（进程组 SIGTERM→SIGKILL）。

    端口发现三段式（每轮按序尝试，任一命中即返回）：
    1. 注入端口精确探（主路径）：框架启动前分配空闲端口，经 ``{port}``
       占位符替换与 ``FENIX_VERIFY_PORT`` 环境变量双通道注入——实例消费
       注入端口即命中，永不与既有实例（主树常驻实例等）争抢端口。
    2. 进程归属发现：实例无视注入端口自绑端口时，经 ``ss -tlnp`` 找
       「属主进程组 = 本次实例进程组」的监听端口（不依赖端口数字约定，
       服务绑任何端口都能找到）。
    3. 邻近扫描（legacy 兜底）：serve.port 提示基准 hint..hint+50 中
       「启动后才出现监听」的端口——要求服务自身上探邻近端口，仅供
       未迁移契约平滑过渡。

    失败时 ``failure_note`` 记人类可读原因（区分启动即退出/未消费注入）。
    """

    def __init__(self, proc: subprocess.Popen, injected_port: Optional[int],
                 timeout: int = 60, legacy_hint: Optional[int] = None,
                 legacy_pre: Optional[set] = None):
        self._proc = proc
        self.failure_note = ""
        self._port = self._discover_port(
            injected_port, timeout, legacy_hint, legacy_pre or set())

    @staticmethod
    def _probe(url: str, timeout: float = 1.0) -> bool:
        try:
            with urlopen(Request(url, headers={"User-Agent": "fenix-verify-probe"}),
                         timeout=timeout):
                return True
        except Exception:
            return False

    @staticmethod
    def _owned_listening_ports(pgid: Optional[int]) -> list:
        """本进程组（start_new_session 进程森林）持有的 TCP 监听端口。

        经 ``ss -tlnp`` 属主 pid → pgid 匹配。ss 不可用/无匹配返回空列表
        （回退邻近扫描）；守护化脱离进程组的服务在此失明——那属病态部署，
        交由邻近扫描兜底。
        """
        if pgid is None:
            return []
        try:
            r = subprocess.run(["ss", "-tlnp"], capture_output=True,
                               text=True, timeout=5)
        except Exception:
            return []
        ports = []
        for line in (r.stdout or "").splitlines():
            parts = line.split()
            if len(parts) < 4 or parts[0] != "LISTEN":
                continue
            try:
                port = int(parts[3].rsplit(":", 1)[1])
            except (IndexError, ValueError):
                continue
            for m in re.findall(r"pid=(\d+)", line):
                try:
                    if os.getpgid(int(m)) == pgid:
                        ports.append(port)
                        break
                except OSError:
                    continue
        return ports

    def _discover_port(self, injected: Optional[int], timeout: int,
                       legacy_hint: Optional[int], legacy_pre: set) -> Optional[int]:
        deadline = time.monotonic() + max(timeout, 5)
        try:
            pgid = os.getpgid(self._proc.pid)
        except OSError:
            pgid = None
        while time.monotonic() < deadline:
            # 1) 注入端口精确探
            if injected and self._probe(f"http://127.0.0.1:{injected}/"):
                return injected
            # 2) 进程归属发现（实例无视注入端口自绑端口的兜底）
            for p in self._owned_listening_ports(pgid):
                if p != injected and self._probe(f"http://127.0.0.1:{p}/"):
                    return p
            # 3) 邻近扫描（legacy：服务自身上探邻近端口的存量契约）
            if legacy_hint:
                for p in range(legacy_hint, legacy_hint + 51):
                    if p in legacy_pre or p == injected:
                        continue
                    if self._probe(f"http://127.0.0.1:{p}/"):
                        return p
            if self._proc.poll() is not None:
                self.failure_note = (
                    f"验证命令实例启动即退出（exit={self._proc.returncode}）"
                    "——检查 serve.cmd 可执行性及端口注入引用"
                    "（{port} 占位符 / $FENIX_VERIFY_PORT 环境变量）")
                return None
            time.sleep(1)
        self.failure_note = (
            f"验证命令实例未就绪：注入端口 {injected} 未被消费，进程归属与"
            "邻近扫描亦未发现 HTTP 监听——检查 serve.cmd 是否引用 {port} "
            "占位符或 $FENIX_VERIFY_PORT 环境变量")
        return None

    @property
    def base_url(self) -> str:
        if self._port is None:
            return f"http://127.0.0.1:{0}"
        return f"http://127.0.0.1:{self._port}"

    @property
    def port(self) -> Optional[int]:
        """发现后的实际监听端口（未发现/启动失败为 None）。"""
        return self._port

    @property
    def pid(self) -> int:
        """被测实例进程 PID（servers.json 登记按此 liveness 收割）。"""
        return self._proc.pid

    @property
    def ok(self) -> bool:
        return self._port is not None and self._proc.poll() is None

    def stop(self):
        try:
            os.killpg(os.getpgid(self._proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            self._proc.wait(timeout=5)
        except Exception:
            try:
                os.killpg(os.getpgid(self._proc.pid), signal.SIGKILL)
            except Exception:
                pass


def provision_worktree_node_modules(worktree_root: Path, project_root: Path,
                                    sub_dirs: list, mode: str = DEFAULT_DEPS_MODE,
                                    logger=None) -> list:
    """worktree 构建环境供给：按 deps_mode 两种方式把依赖装进 worktree。

    git worktree 不含 gitignore 的 node_modules，worktree 内 ``npm run build``
    必失败——这是实现者每轮手工安装的摩擦来源（fast-track 复盘）。供给方式
    由 deps_mode 决定（解析见 ``resolve_deps_mode``）：

    - ``hardlink``：主树 node_modules 的 ``os.link`` 硬链接副本（秒级、共享
      inode 不占双倍空间）。npm 更新包 = unlink + 重新解包（新 inode），主树
      原件不受影响；但任何 in-place 写入（构建缓存、postinstall 改文件）会
      穿透共享 inode——避免主树与 worktree 并发构建。主树无 node_modules 时
      自动降级 prefer-offline。
    - ``prefer-offline``：worktree 内 ``npm ci --prefer-offline``（锁文件严格
      安装，走用户级 npm 缓存），失败回退 ``npm install --prefer-offline``。

    对 ``sub_dirs`` 中每个含 package.json 且缺 node_modules 的目录供给；
    单目录失败记日志并继续（不阻塞 worktree 创建/验证准备）。

    Returns: 已供给的目录列表（相对 worktree 根），供日志说明。
    """
    if mode not in DEPS_MODES:
        mode = DEFAULT_DEPS_MODE
    done = []
    for sub in sub_dirs:
        wt_dir = Path(worktree_root) / sub
        main_dir = Path(project_root) / sub
        if not (wt_dir / "package.json").is_file():
            continue
        if (wt_dir / "node_modules").exists():
            continue
        provisioned = False
        if mode == "hardlink":
            main_nm = main_dir / "node_modules"
            if main_nm.is_dir():
                try:
                    shutil.copytree(
                        main_nm, wt_dir / "node_modules",
                        copy_function=os.link, symlinks=True,
                        ignore_dangling_symlinks=True,
                    )
                    done.append(str(sub))
                    provisioned = True
                except OSError as e:
                    if logger:
                        logger.warning(
                            "verify_contract",
                            f"hardlink 供给失败（{sub}），降级 prefer-offline: {e}")
        if not provisioned:
            try:
                r = subprocess.run(
                    ["npm", "ci", "--prefer-offline", "--no-audit", "--no-fund"],
                    cwd=str(wt_dir), capture_output=True, text=True, timeout=900,
                )
                if r.returncode != 0:
                    r = subprocess.run(
                        ["npm", "install", "--prefer-offline", "--no-audit",
                         "--no-fund"],
                        cwd=str(wt_dir), capture_output=True, text=True,
                        timeout=900,
                    )
                if r.returncode == 0:
                    done.append(str(sub))
                elif logger:
                    logger.warning(
                        "verify_contract",
                        f"node_modules 供给失败（{sub}）: "
                        f"{(r.stderr or r.stdout or '').strip()[-200:]}")
            except (subprocess.SubprocessError, OSError) as e:
                if logger:
                    logger.warning(
                        "verify_contract", f"node_modules 供给异常（{sub}）: {e}")
    return done


def probe_ready(base_url: str, ready: ReadyProbe) -> tuple:
    """就绪探针：轮询 GET ``base_url + ready.url`` 直至期望状态码或超时。

    Returns: (ok, note)
    """
    url = f"{base_url.rstrip('/')}{ready.url}"
    deadline = time.time() + max(1, ready.timeout)
    last_err = ""
    while time.time() < deadline:
        try:
            req = Request(url, method="GET",
                          headers={"User-Agent": "fenix-verify-contract"})
            with urlopen(req, timeout=3) as resp:
                if resp.status == ready.expect:
                    return True, f"就绪探针通过: {url}"
                last_err = f"状态码 {resp.status} != {ready.expect}"
        except Exception as e:
            last_err = str(e)[:120]
        time.sleep(1)
    return False, f"就绪探针超时（{ready.timeout}s）: {url} — {last_err}"


_URL_ORIGIN_RE = re.compile(r"https?://[A-Za-z0-9.\-_]+(?::\d+)?")


def rewrite_scenarios_origin(scenarios_path: Path, base_url: str) -> int:
    """把场景文件中所有 http(s) URL 的 origin 改写为本次被测实例（BASE_URL 注入）。

    BASE_URL 铁律的执行点：无论 planner 生成什么地址，场景一律打新鲜实例。
    只替换 scheme 锚定的 origin（host[:port]），路径与 query 原样保留。
    返回改写处数（0 = 文件缺失或无 URL）。
    """
    try:
        content = scenarios_path.read_text(encoding="utf-8")
    except OSError:
        return 0
    new_content, n = _URL_ORIGIN_RE.subn(base_url.rstrip("/"), content)
    if n and new_content != content:
        try:
            scenarios_path.write_text(new_content, encoding="utf-8")
        except OSError:
            return 0
    return n
