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
      # cmd: python3 -m http.server 8787   # kind=command 必填。shell 命令，项目根为 cwd
      # port: 8787                         # kind=command 可选。端口提示（供端口改写
                                     # 扫描）；缺省时从 cmd 的 --port/-p 参数提取
    # ── 可选。就绪探针；缺省探被测实例根路径、期望 200、等待 60 秒。
    ready:
      url: /#/overview               # 探针路径（相对被测实例），缺省 /
      expect: 200                    # 期望 HTTP 状态码，缺省 200
      timeout: 60                    # 就绪等待上限（秒），缺省 60

## 语义要点

- **static 模式无条件新鲜服务**：不做「已可达即跳过」——场景 origin 全量改写
  到本次实例。这是对陈旧产物陷阱的结构性修复，不是可选项。
- **command 模式**沿用既有自愈语义（探活 → 启动 → 端口改写），仅把启动命令
  的来源从 ``commands.start`` 换为 ``serve.cmd``（优先）。
- ``prepare`` 失败＝验证环境错误（返回不可达 + 说明），验证门禁会拦截、
  不会判 verified/bug-found——构建失败不是产品缺陷。
"""

import re
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

CONTRACT_FILENAME = "verify.yaml"
PREPARE_STEP_TIMEOUT = 600  # 单条构建步骤上限（秒）：构建慢是常态，600s 内完不成应修构建
DEFAULT_READY_TIMEOUT = 60


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
    cmd: str = ""  # kind=command：shell 命令
    port: Optional[int] = None  # kind=command：端口提示（供端口改写扫描）


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


def load_verify_contract(project_root: Path, logger=None) -> Optional[VerifyContract]:
    """加载 ``.fenix/verify.yaml``；文件缺失/解析失败返回 None（回退旧行为）。

    解析失败属配置错误而非「无契约」：记 warning 提醒修复（静默吞掉会让
    用户以为契约生效了）。
    """
    path = Path(project_root) / ".fenix" / CONTRACT_FILENAME
    if not path.is_file():
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
    return VerifyContract(prepare=prepare, serve=serve, ready=ready)


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
    with socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


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


def provision_worktree_node_modules(worktree_root: Path, project_root: Path,
                                    sub_dirs: list) -> list:
    """worktree 服务范围（方案 2）的构建环境供给：把主树 node_modules 链入 worktree。

    git worktree 不含 gitignore 的 node_modules，worktree 内 ``npm run build``
    必失败——这是实现者每轮手工 symlink 的摩擦来源（fast-track 复盘）。
    对 ``sub_dirs`` 中每个含 package.json 且缺 node_modules 的目录，自动建立
    指向主树对应 node_modules 的符号链接（构建只读依赖，共享安全）。

    Returns: 已建立链接的目录列表（相对 worktree 根），供日志说明。
    """
    linked = []
    for sub in sub_dirs:
        wt_dir = Path(worktree_root) / sub
        main_dir = Path(project_root) / sub
        if not (wt_dir / "package.json").is_file():
            continue
        if (wt_dir / "node_modules").exists():
            continue
        main_nm = main_dir / "node_modules"
        if not main_nm.is_dir():
            continue
        try:
            (wt_dir / "node_modules").symlink_to(main_nm, target_is_directory=True)
            linked.append(str(sub))
        except OSError:
            continue
    return linked


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
