"""verify_contract.py — 声明式验证契约（``.fenix/verify.yaml``）加载与执行。

## 为什么需要这个文件（作用）

Fenix 是通用开发框架，被管项目形态各异：前端应用有构建产物（dist/build/…，
名字也不尽相同），服务端应用直接跑源码，CLI 工具可能没有 HTTP 入口。「最终
用户验证」必须测**被测实现 fresh 构建出的可运行形态**，但框架此前对「应用
如何构建、如何被服务、何时算就绪」没有任何声明：

- dashboard 型项目靠 planner 生成的场景 URL（常写 8787）+ ``commands.start``
  兜底 + 端口改写；合并后若产物未重建，验证测到的是**上一次构建的陈旧产物**
  （fast-track 死锁复盘：实现者每轮花 30+ 分钟手工重建 dist 并考古验证环境）。
- 「场景 URL 已可达即跳过自愈」的捷径对构建型应用是陷阱——8787 活着就直接
  用陈旧实例，新鲜实现从未被测过。

验证契约把三件事变成**项目内随仓库提交的声明**，框架在每轮验证前依次执行：

1. ``prepare``——构建（可选）：保证被服务产物包含最新合并实现；
2. ``serve``——被测实例如何启动：静态目录（框架内置服务器）或自定义命令；
3. ``ready``——就绪探针：确认实例可用后再跑场景。

随后把场景 URL **全量改写到本次服务实例**（BASE_URL 注入铁律：场景永远打
新鲜实例，不依赖 planner 生成的地址；planner 生成什么 URL 都会被覆盖）。

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
    # 通过后框架做一次鉴别力自检：再请求一个随机不存在路径，若响应（状态码
    # + body）与探针完全一致＝本实例对任意路径同响应（SPA fallback 形态），
    # 探针被吞掉、无法区分就绪/未就绪 → 判就绪失败并给处方（SPA 应用禁止
    # 探会被 fallback 兜底的路径，改探真实 API 端点；add-spec-hooks 白屏
    # env 事故 2026-09-06 防复发）。
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

## 多形态验证（verify-runner-engine，零新增字段）

serve/ready 是否必需由**本轮场景集的 kind 组成反推**（场景 kind ∈
web/cli/api，见 core/verify_engine/scenarios.py 词表）：

- **纯 cli 场景集**：serve/ready 全省——纯 CLI 交付没有可服务的 HTTP 形态，
  验证只依赖 prepare（构建/命令可用性）。**MUST NOT 回退 commands.start**
  （无人消费的实例不拉起）；``_ensure_app_reachable`` 无实例形态短路。
- **含 web 或 api 场景**：serve 段（或 commands.start 兜底）必须有效；
  缺失时验收报明确错误打回 plan，不静默跑空。
- **混合场景集**：serve 照常启动，cli 场景额外获得实例环境变量注入
  （``FENIX_VERIFY_BASE_URL`` / ``FENIX_VERIFY_PORT``，框架值优先）。

BASE_URL 注入范围扩展（design D4）：

- ``navigate``（web）：现状不变，场景 origin 全量改写。
- ``http_request`` / ``sse_connect``（api）：``url`` 字段 origin 全量改写
  （路径保留）——文件级 ``rewrite_scenarios_origin`` 与 ApiRunner 运行时
  ``rewrite_origin`` 双通道，planner 写什么都被覆盖。
- CLI ``run`` 步骤：执行环境自动注入 ``FENIX_VERIFY_BASE_URL`` 与
  ``FENIX_VERIFY_PORT``，且框架值优先——场景 ``env`` 中同名变量被覆盖
  （防 stale 地址事故同一防护逻辑）。

实例 base_url 由验证流程在开始时确定并**统一供给**各 Runner（探针与断言
上下文共用），取代旧「从候选场景 navigate 步骤文本正则考古 base_url」的
回退逻辑（该逻辑在场景失联时会漏判）。无实例形态下改写与注入为无害空操作。
"""

import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen

import yaml

from core.proc_utils import find_free_port

CONTRACT_FILENAME = "verify.yaml"
PREPARE_STEP_TIMEOUT = 600  # 单条构建步骤上限（秒）：构建慢是常态，600s 内完不成应修构建
DEFAULT_READY_TIMEOUT = 60

# worktree node_modules 供给模式（verify.yaml deps_mode > config verify.deps_mode > 默认）
# 默认 hardlink：主树 node_modules 以 os.link 硬链接副本共享 inode，秒级且不占双倍空间。
DEPS_MODES = ("prefer-offline", "hardlink")
DEFAULT_DEPS_MODE = "hardlink"


def _positive_int_or_default(value, default: int) -> int:
    """阈值/超时非法值（非正数、类型错误）回退缺省值。

    对齐 get_code_review_config 的缺省回退范式（task 1.3）：
    只认正整数（排除 bool——bool 是 int 子类），非法一律静默回退缺省。
    """
    if value is None:
        return default
    # 排除 bool（bool 是 int 子类，显式前判；否则 True 会被 int() 变 1）
    if isinstance(value, bool):
        return default
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    if n <= 0:
        return default
    return n


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
class RegressionSpec:
    """全量回归执行声明：``cmd`` 在项目根执行并产出 JUnit XML（``output``）。

    Fenix 是通用开发框架，被管项目不一定是 Python 项目——回归命令形态、
    测试目录、测试数量均由项目声明（design D1/D2），框架只按 JUnit XML 解析
    （跨语言事实标准：pytest --junit-xml、jest-junit、go-junit-report、
    maven-surefire 均可产出；``testcase@time`` 天然承载耗时，正是
    「长耗时用例」所需）。``format`` 本次只允许 ``junit`` 一值，声明其它值
    时整段视为无效（design D2 边界：不得静默按 junit 处理）。
    """

    cmd: object  # str（shell）或 list（argv）；cwd 为项目根
    output: str  # 命令产出的 JUnit XML 路径（相对项目根）
    timeout_seconds: int = 1800  # 硬超时（秒）；超过则中止进程并按超时归类
    format: str = "junit"  # 结果格式；本次仅支持 JUnit XML
    long_test_threshold_seconds: int = 10  # 单用例耗时超过即计入长耗时表（正数）


@dataclass
class VerifyContract:
    """验证契约：prepare（构建）→ serve（被测实例）→ ready（就绪探针）。"""

    prepare: list = field(default_factory=list)  # list[PrepareStep]
    serve: Optional[ServeSpec] = None
    ready: ReadyProbe = field(default_factory=ReadyProbe)
    deps_mode: str = ""  # worktree node_modules 供给模式；空=未指定（走 config/默认）
    # 全量回归执行声明（design D1：归 verify.yaml 而非 config.yaml——与
    # prepare/serve/ready 同属「项目如何被测」语义域；缺失=未配置回归，零迁移）
    regression: Optional[RegressionSpec] = None


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
            if root_yaml.is_file() and not (Path(project_root) / ".fenix").is_symlink():
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

    # prepare 步骤逐条解析（code-review item e892642d75db）：畸形条目（dict 缺
    # run／键名笔误／run 为空，或字符串与合法映射之外的其它形态）此前被静默
    # 丢弃——构建步骤悄悄缺失＝dist 不重建，验证测到陈旧产物，与本模块
    # 「prepare 失败要大声失败」哲学相悖。记 warning（含条目序号与原文）而非
    # 整份契约作废：其余合法步骤与 serve/ready 不受牵连（对齐 deps_mode/
    # regression「告警＋忽略该片段」惯例）。
    prepare = []
    prepare_data = data.get("prepare")
    # prepare 段整体形态守卫（code-review item 96b8f60efeea）：非列表（字符串/
    # 映射/标量）会被按字符或键名迭代误建出多条构建步骤，不可迭代标量更使
    # enumerate 直接抛 TypeError 从本函数冒出，违背「解析失败按无契约处理并
    # 记 warning」约定——记 warning（含原文 repr）并按空 prepare 处理，对齐
    # ready/regression 段「告警＋忽略该片段」惯例。
    if prepare_data is not None and not isinstance(prepare_data, list):
        if logger:
            logger.warning(
                "verify_contract",
                f"verify.yaml prepare 段非法（须为步骤列表，按空 prepare 处理）: "
                f"{prepare_data!r}",
            )
        prepare_data = []
    for i, step in enumerate(prepare_data or [], 1):
        if isinstance(step, str):
            prepare.append(PrepareStep(run=step))
        elif isinstance(step, dict) and step.get("run"):
            prepare.append(PrepareStep(run=step["run"], cwd=str(step.get("cwd") or "")))
        elif logger:
            logger.warning(
                "verify_contract",
                f"verify.yaml prepare 第 {i} 步非法（须为字符串或含非空 run 的"
                f"映射，已忽略该步——构建步骤悄悄缺失会验证陈旧产物）: "
                f"{repr(step)[:200]}",
            )
    serve = None
    serve_data = data.get("serve")
    if isinstance(serve_data, dict) and serve_data.get("kind") in ("static", "command"):
        # port 是可选 legacy 端口提示：非正整数（如 port: auto）按无提示
        # 回退 None，不得从 load_verify_contract 抛 ValueError——违背
        # 「解析失败按无契约回退」约定（复用 _positive_int_or_default 范式）。
        port = _positive_int_or_default(serve_data.get("port"), 0) or None
        serve = ServeSpec(
            kind=serve_data["kind"],
            root=str(serve_data.get("root") or ""),
            cmd=str(serve_data.get("cmd") or ""),
            port=port,
        )
    # ready 段（code-review item c2d140a513b9）：先类型校验再取值——ready: 为
    # 标量/字符串（如 ready: /health）时 .get 抛 AttributeError、expect/timeout
    # 为非数字时 int() 抛 ValueError，均从本函数直接冒出，违背文档「解析失败
    # 按无契约处理并记 warning」约定（selfcheck_contract_light 的调用不在 try
    # 内，消费期会崩溃）。非法映射/非法数值一律记 warning 并按无契约回退。
    ready_data = data.get("ready")
    if ready_data is not None and not isinstance(ready_data, dict):
        if logger:
            logger.warning(
                "verify_contract",
                f"verify.yaml ready 段非法（须为映射，按无契约回退）: {ready_data!r}",
            )
        return None
    ready_data = ready_data or {}
    try:
        ready = ReadyProbe(
            url=str(ready_data.get("url") or "/") or "/",
            expect=int(ready_data.get("expect") or 200),
            timeout=int(ready_data.get("timeout") or DEFAULT_READY_TIMEOUT),
        )
    except (TypeError, ValueError) as e:
        if logger:
            logger.warning(
                "verify_contract",
                f"verify.yaml ready 段数值非法（按无契约回退）: {e}",
            )
        return None
    # 端口注入迁移告警（不阻断）：cmd 未引用注入端口时实例会与既有实例
    # 争抢固定端口（dashboard 端口独占语义下 = 杀掉占用者接管，2026-09-05
    # 验证实例顺带杀主树 dashboard 事故的根源），由未消费注入的兜底发现
    # 链路续命。存量为零迁移原则只告警、不拒绝。
    if (
        serve is not None
        and serve.kind == "command"
        and serve.cmd
        and "{port}" not in serve.cmd
        and "$FENIX_VERIFY_PORT" not in serve.cmd
        and logger
    ):
        logger.warning(
            "verify_contract",
            "serve.cmd 未引用端口注入（{port} 占位符或 $FENIX_VERIFY_PORT "
            "环境变量），验证实例将与既有实例争抢固定端口；建议迁移：cmd 中"
            "的端口写作 {port}，框架自动分配空闲端口注入",
        )
    deps_mode = ""
    if data.get("deps_mode") is not None:
        if data["deps_mode"] in DEPS_MODES:
            deps_mode = data["deps_mode"]
        elif logger:
            logger.warning(
                "verify_contract",
                f"verify.yaml deps_mode 非法（忽略，可用值 {list(DEPS_MODES)}）: "
                f"{data['deps_mode']}",
            )
    # regression 段（design D1/D2）：可选。缺段 → regression=None（未配置回归，
    # 分面引导态、周期检查点跳过、触发端点 400，存量项目零迁移）。缺 cmd/output
    # 或 format 非 junit 均视整段无效 → None + WARNING——MUST NOT 静默按 junit
    # 去解析其它格式产物（那必然产出 parse_error 且无解释）。非法数值回退缺省
    # （对齐 get_code_review_config 的缺省回退范式，task 1.3）。
    regression = None
    reg_data = data.get("regression")
    if reg_data is not None:
        if not isinstance(reg_data, dict):
            if logger:
                logger.warning(
                    "verify_contract",
                    f"verify.yaml regression 段非法（非映射，按未配置处理）: {reg_data}",
                )
        else:
            cmd = reg_data.get("cmd")
            output = reg_data.get("output")
            fmt = reg_data.get("format") or "junit"
            if not cmd or not output:
                if logger:
                    logger.warning(
                        "verify_contract",
                        "verify.yaml regression 段缺少必填字段 cmd/output"
                        f"（cmd={cmd!r}, output={output!r}，按未配置处理）",
                    )
            elif fmt != "junit":
                # design D2 边界：只支持 junit 一值。声明其它格式整段无效，
                # 不得降级成 junit 去解析（会产出无解释的 parse_error）。
                if logger:
                    logger.warning(
                        "verify_contract",
                        "verify.yaml regression 段 format 仅支持 junit"
                        f"（声明为 {fmt!r}，整段按未配置处理）",
                    )
            else:
                regression = RegressionSpec(
                    cmd=cmd,
                    output=str(output),
                    timeout_seconds=_positive_int_or_default(
                        reg_data.get("timeout_seconds"), 1800
                    ),
                    format="junit",
                    long_test_threshold_seconds=_positive_int_or_default(
                        reg_data.get("long_test_threshold_seconds"), 10
                    ),
                )
    return VerifyContract(
        prepare=prepare,
        serve=serve,
        ready=ready,
        deps_mode=deps_mode,
        regression=regression,
    )


# valid=False 时的结构化失败原因枚举（code-review item fdb60ffde7a8）：CLI 按
# 枚举映射退出码，不再依赖人类可读文案的中文子串匹配——文案可自由调整而不
# 影响退出码语义。空串 = 非格式失败（valid=True，或失败属 prepare/serve/ready
# 运行时维度，退出码由对应段的 ok 标志决定）。
FAIL_CONTRACT_MISSING = "contract_missing"  # 契约文件不存在（exit 1）
FAIL_CONTRACT_PARSE = "contract_parse_error"  # 契约 YAML 解析失败（exit 1）
FAIL_SERVE_INVALID = "serve_invalid"  # serve 段非法（kind 非法/必填为空，exit 5）


@dataclass
class ValidateResult:
    """契约校验结果：逐段通过与否与错误详情，以及 valid 判定。

    valid 判定（design D4 权限边界）：YAML 可解析且 serve 段合法（kind ∈
    static/command 且对应必填字段非空）。Administrator 据此判定：valid →
    「契约有效、无需起草」结案；invalid → 修正路径。
    """

    valid: bool  # YAML 可解析 + serve 段合法（D4 权限边界判定）
    prepare_ok: bool
    prepare_error: str
    serve_ok: bool
    serve_error: str
    ready_ok: bool
    ready_error: str
    # 结构化失败原因枚举（仅 valid=False 时非空，取值见上方 FAIL_* 常量）；
    # prepare_error/serve_error 文案字段保留向后兼容。
    fail_kind: str = ""
    # 段级详细信息（供 CLI 输出）
    prepare_steps_run: int = 0
    serve_kind: str = ""
    serve_port: Optional[int] = None
    ready_url: str = ""
    ready_expect: int = 200
    # ready 探针是否实际执行（code-review item 944ef0f39f71）：prepare 失败/
    # serve.root 缺失/serve 启动失败等路径下探针从未运行，而 ready_ok 保持
    # 初始 True，CLI 按其打印「✓ 通过」会向用户谎报未执行的探针已通过。探针
    # 实际运行过才置 True，未执行段由 CLI 显示「未探测」；退出码与总体失败
    # 判定仍按 ready_ok，不受本标志影响。
    ready_ran: bool = False
    # 本次校验实际加载的契约对象（code-review item 73047bb4e140）：随结果一并
    # 返回，调用方（fenix_verify_contract.py CLI）全程复用同一份契约做跳过
    # 判定与 regression 自证，消除两次读取之间 verify.yaml 被改写导致「三段
    # 判定结论与自证所用契约不是同一版本」的 TOCTOU 窗口。契约缺失/解析失败
    # 的早退路径为 None。
    contract: Optional[VerifyContract] = None


def validate_contract(project_root: Path, logger=None) -> ValidateResult:
    """契约校验入口：逐段执行 prepare → serve → ready → 停 serve。

    返回各段通过与否与错误详情，同时输出 valid 判定（YAML 可解析且 serve 段
    合法，供 D4 权限边界判定）。Administrator 在草稿上运行此函数，全通才把
    文件落位 .fenix/verify.yaml（草稿先写临时路径，防半成品被
    load_verify_contract 当有效契约）。

    校验流程：
    1. 加载契约（YAML 解析失败 → valid=False，返回解析错误）
    2. 执行 prepare 构建步骤（复用 run_prepare_steps）
    3. 启动 serve 实例（static/command 两形态复用既有 Server 类）
    4. 探活 ready 就绪探针（复用 probe_ready 含鉴别力自检）
    5. 停 serve 实例
    6. 返回结果（全通 exit 0，任一段失败 exit 非 0）

    Args:
        project_root: 项目根目录（契约路径 = project_root/.fenix/verify.yaml）
        logger: 日志记录器（可选）

    Returns:
        ValidateResult：逐段结果与 valid 判定（含已加载的契约对象 contract，
        供调用方复用同一版本契约，见字段注释）
    """
    project_root = Path(project_root)
    contract_path = project_root / ".fenix" / CONTRACT_FILENAME

    # 1. 加载契约（YAML 解析）
    try:
        contract = load_verify_contract(project_root, logger)
    except Exception as e:
        return ValidateResult(
            valid=False,
            prepare_ok=False,
            prepare_error=f"契约解析失败: {e}",
            serve_ok=False,
            serve_error="",
            ready_ok=False,
            ready_error="",
            fail_kind=FAIL_CONTRACT_PARSE,
        )

    if contract is None:
        # 文件不存在或解析失败（load_verify_contract 返回 None）
        if not contract_path.is_file():
            return ValidateResult(
                valid=False,
                prepare_ok=False,
                prepare_error=f"契约文件不存在: {contract_path}",
                serve_ok=False,
                serve_error="",
                ready_ok=False,
                ready_error="",
                fail_kind=FAIL_CONTRACT_MISSING,
            )
        else:
            return ValidateResult(
                valid=False,
                prepare_ok=False,
                prepare_error="契约 YAML 解析失败",
                serve_ok=False,
                serve_error="",
                ready_ok=False,
                ready_error="",
                fail_kind=FAIL_CONTRACT_PARSE,
            )

    # 2. valid 判定（D4：YAML 可解析 + serve 段合法）
    valid = True
    serve_ok = True
    serve_error = ""
    fail_kind = ""
    serve_kind = ""
    serve_port = None

    # 检查原始 YAML 中的 serve 段（load_verify_contract 会静默丢弃无效 kind）
    try:
        raw_data = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
        if isinstance(raw_data, dict):
            raw_serve = raw_data.get("serve")
            if isinstance(raw_serve, dict):
                raw_kind = raw_serve.get("kind", "")
                if raw_kind not in ("static", "command"):
                    valid = False
                    serve_ok = False
                    fail_kind = FAIL_SERVE_INVALID
                    serve_error = f"serve.kind 非法: {raw_kind}（应为 static 或 command）"
                elif raw_kind == "static" and not raw_serve.get("root"):
                    valid = False
                    serve_ok = False
                    fail_kind = FAIL_SERVE_INVALID
                    serve_error = "serve.root 为空（kind=static 必填）"
                elif raw_kind == "command" and not raw_serve.get("cmd"):
                    valid = False
                    serve_ok = False
                    fail_kind = FAIL_SERVE_INVALID
                    serve_error = "serve.cmd 为空（kind=command 必填）"
    except Exception:
        pass  # YAML 解析失败已在上方处理

    # 从加载的契约中获取 serve 信息（用于输出）
    if contract.serve is not None:
        serve_kind = contract.serve.kind
        serve_port = contract.serve.port

    # 3. 执行 prepare 构建步骤
    prepare_ok = True
    prepare_error = ""
    prepare_steps_run = len(contract.prepare)
    if contract.prepare:
        err = run_prepare_steps(contract, project_root)
        if err:
            prepare_ok = False
            prepare_error = err
            # prepare 失败不改变 valid 判定：契约结构有效（YAML 正确 + serve 段合法），
            # 只是构建步骤失败——这是验证环境错误，不是契约格式问题。

    # 4. 启动 serve 实例 + 探活 ready
    server = None
    # command 形态的实例句柄：finally 统一 stop（先探 ready 再停，
    # validate_command_stop_order 修复）——须在 try 外声明，static 形态或
    # prepare 失败路径下 finally 才不致 UnboundLocalError（2026-09-09 修复）。
    srv = None
    # command 形态的 Popen 句柄（code-review item 14f978f49d7f）：构造
    # CommandVerifyServer 失败（srv 仍为 None）时，finally 据此兜底收掉
    # 进程组，防孤儿服务。
    proc = None
    ready_ok = True
    # 探针是否实际执行（供 CLI 区分「未探测」与「通过」，item 944ef0f39f71）
    ready_ran = False
    ready_error = ""
    ready_url = ""
    ready_expect = contract.ready.expect
    if contract.serve is not None and prepare_ok:
        base_url = ""
        try:
            if contract.serve.kind == "static":
                root_dir = project_root / contract.serve.root
                if not root_dir.is_dir():
                    serve_ok = False
                    serve_error = f"serve.root 不存在: {contract.serve.root}"
                    # serve.root 不存在是运行时问题，不是契约格式问题——契约结构有效
                else:
                    server = StaticVerifyServer(root_dir)
                    base_url = server.base_url
            elif contract.serve.kind == "command":
                # command 形态：分配端口、替换占位符、启动进程
                # srv 声明提前到此处，由 finally 统一 stop（先探 ready 再停）
                srv = None
                from core.proc_utils import find_free_port as _ffp

                injected_port = _ffp()
                cmd_str = contract.serve.cmd
                if "{port}" in cmd_str:
                    cmd_str = cmd_str.replace("{port}", str(injected_port))
                env = {**os.environ, "FENIX_VERIFY_PORT": str(injected_port)}
                # legacy_pre 存量快照（code-review item 92f6d9a36937）：与
                # 生产路径 serving.py 对齐，启动进程前先探测 legacy 邻近区间
                # （serve.port..+50）内已响应的存量端口——邻近扫描只认「启动
                # 后才出现监听」的端口，缺此快照时 serve.port 指向 8787 等
                # 常驻端口、serve.cmd 又未消费注入端口的契约会被扫描误判到
                # 常驻实例上，假判 serve_ok/ready_ok（陈旧实例污染验证）。
                legacy_pre = (
                    _probe_ports_responding(
                        range(contract.serve.port, contract.serve.port + 51)
                    )
                    if contract.serve.port
                    else set()
                )
                try:
                    proc = subprocess.Popen(
                        cmd_str,
                        shell=True,
                        cwd=str(project_root),
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                        env=env,
                    )
                except Exception as e:
                    serve_ok = False
                    serve_error = f"serve 命令启动失败: {e}"
                    # serve 命令启动失败是运行时问题，不是契约格式问题——契约结构有效
                if serve_ok:
                    # 使用 CommandVerifyServer 进行端口发现（注入端口精确探 +
                    # 进程归属发现 + 邻近扫描）。构造失败（端口发现内部异常）
                    # 时 srv 保持 None，进程兜底清理交 finally（本条为运行时
                    # 问题，不是契约格式问题——契约结构有效）。
                    try:
                        srv = CommandVerifyServer(
                            proc,
                            injected_port,
                            timeout=contract.ready.timeout or 60,
                            legacy_hint=contract.serve.port,
                            legacy_pre=legacy_pre,
                        )
                    except Exception as e:
                        srv = None
                        serve_ok = False
                        serve_error = f"serve 端口发现异常: {e}"
                    if srv is not None and not srv.ok:
                        serve_ok = False
                        serve_error = srv.failure_note or "serve 命令未就绪（注入端口未被消费）"
                        # serve 命令未就绪是运行时问题，不是契约格式问题——契约结构有效
                    elif srv is not None:
                        base_url = srv.base_url
                    # 注意：command 形态不在这里 stop——先探 ready 再统一 stop
                    # （validate_command_stop_order 2026-09-08 修复）

            # 5. 探活 ready 就绪探针（复用 probe_ready 含鉴别力自检）
            if base_url and serve_ok:
                ready_url = contract.ready.url
                ok, note = probe_ready(base_url, contract.ready)
                ready_ran = True
                ready_ok = ok
                ready_error = note if not ok else ""
                # ready 探针失败是运行时问题，不是契约格式问题——契约结构有效
        except Exception as e:
            serve_ok = False
            serve_error = f"serve 启动异常: {e}"
            # serve 启动异常是运行时问题，不是契约格式问题——契约结构有效
            ready_ok = False
            ready_error = ""
        finally:
            # 6. 停 serve 实例（static + command 统一收口，ready 探针已在上方执行）
            if server is not None:
                try:
                    server.stop()
                except Exception:
                    pass
            # command 形态：srv 在 finally 无条件 stop（先探 ready 再停实例，
            # 修复 validate_command_stop_order 2026-09-08）。不限定 srv.ok——
            # 端口发现超时（srv.ok=False 但进程仍存活）时进程组同样要收掉，
            # 否则泄漏孤儿服务（code-review item 14f978f49d7f）；stop 内部已
            # 对已退出/无权限进程分 try/except 兜底，重复调用安全。
            if srv is not None:
                try:
                    srv.stop()
                except Exception:
                    pass
            elif proc is not None:
                # 构造 CommandVerifyServer 失败（srv 仍为 None）的兜底：
                # 进程组照常收掉，防孤儿服务（同上 item）。
                try:
                    if proc.poll() is None:
                        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                        proc.wait(timeout=5)
                except Exception:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except Exception:
                        pass

    return ValidateResult(
        valid=valid,
        prepare_ok=prepare_ok,
        prepare_error=prepare_error,
        serve_ok=serve_ok,
        serve_error=serve_error,
        ready_ok=ready_ok,
        ready_error=ready_error,
        fail_kind=fail_kind,
        prepare_steps_run=prepare_steps_run,
        serve_kind=serve_kind,
        serve_port=serve_port,
        ready_url=ready_url,
        ready_expect=ready_expect,
        ready_ran=ready_ran,
        contract=contract,
    )


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
            # start_new_session+killpg 收整组进程（与 CommandVerifyServer.stop
            # 同一纪律）：subprocess.run 超时只 kill 直接子进程，npm/pnpm 派生
            # 的 node 构建孙进程会继续后台写 dist，与后续验证 serve/prepare
            # 并发污染被测产物目录（code-review item 2fa170366d6b）。
            p = subprocess.Popen(
                cmd,
                shell=use_shell,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
        except OSError as e:
            return f"第 {i} 步启动失败: {e}"
        try:
            out, err = p.communicate(timeout=PREPARE_STEP_TIMEOUT)
        except subprocess.TimeoutExpired:
            # 先 SIGTERM 整组留优雅退出机会，wait(5) 未退再 SIGKILL（同 stop 纪律）
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                pass
            try:
                p.wait(timeout=5)
            except Exception:
                try:
                    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                except Exception:
                    pass
            return f"第 {i} 步超时（>{PREPARE_STEP_TIMEOUT}s）: {cmd}"
        if p.returncode != 0:
            tail = (err or out or "").strip()[-300:]
            return f"第 {i} 步退出码 {p.returncode}: {cmd}\n{tail}"
    return None


def _find_free_port() -> int:
    # 兼容引用（verify-process-lifecycle D5）：实为共用助手 core.proc_utils.find_free_port
    # （v2_dev_server 端口分配路径与静态/命令实例同源）。
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
            *args, directory=str(self.root), **kw
        )
        self._port = _find_free_port()
        self._httpd = ThreadingHTTPServer(("127.0.0.1", self._port), handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
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

    def __init__(
        self,
        proc: subprocess.Popen,
        injected_port: Optional[int],
        timeout: int = 60,
        legacy_hint: Optional[int] = None,
        legacy_pre: Optional[set] = None,
        boot_log: Optional[object] = None,
    ):
        self._proc = proc
        self.failure_note = ""
        self._boot_log = boot_log
        self._port = self._discover_port(injected_port, timeout, legacy_hint, legacy_pre or set())

    @staticmethod
    def _probe(url: str, timeout: float = 1.0) -> bool:
        try:
            with urlopen(
                Request(url, headers={"User-Agent": "fenix-verify-probe"}), timeout=timeout
            ):
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
            r = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True, timeout=5)
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

    def _discover_port(
        self, injected: Optional[int], timeout: int, legacy_hint: Optional[int], legacy_pre: set
    ) -> Optional[int]:
        deadline = time.monotonic() + max(timeout, 5)

        def _probe_in_budget(url: str) -> bool:
            # deadline 下沉到探针粒度（code-review item 65a895e36c3d）：旧实现
            # 只在每轮循环顶部检查一次 deadline，单轮内可执行注入端口探（1s）
            # + 全部进程归属端口探（各 1s）+ 邻近扫描 51 次 1s 探（外加一次
            # ss timeout=5s），最坏单轮数十秒——调用方 ready.timeout（缺省
            # 60s）被突破，就绪判定等待时间不可控。现每个探针超时按剩余预算
            # 取 min；预算耗尽不再发起新探针，单轮总耗时被钳在 deadline 附近
            # （至多一个在飞探针的尾部）。
            budget = deadline - time.monotonic()
            if budget <= 0:
                return False
            return self._probe(url, timeout=min(1.0, budget))

        try:
            pgid = os.getpgid(self._proc.pid)
        except OSError:
            pgid = None
        while time.monotonic() < deadline:
            # 1) 注入端口精确探
            if injected and _probe_in_budget(f"http://127.0.0.1:{injected}/"):
                return injected
            # 2) 进程归属发现（实例无视注入端口自绑端口的兜底）
            for p in self._owned_listening_ports(pgid):
                if p != injected and _probe_in_budget(f"http://127.0.0.1:{p}/"):
                    return p
            # 3) 邻近扫描（legacy：服务自身上探邻近端口的存量契约）
            if legacy_hint:
                for p in range(legacy_hint, legacy_hint + 51):
                    if p in legacy_pre or p == injected:
                        continue
                    if _probe_in_budget(f"http://127.0.0.1:{p}/"):
                        return p
            if self._proc.poll() is not None:
                self.failure_note = (
                    f"验证命令实例启动即退出（exit={self._proc.returncode}）"
                    "——检查 serve.cmd 可执行性及端口注入引用"
                    "（{port} 占位符 / $FENIX_VERIFY_PORT 环境变量）"
                )
                return None
            # 睡眠同样不越过 deadline（剩余不足 1s 时按剩余睡）
            time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
        self.failure_note = (
            f"验证命令实例未就绪：注入端口 {injected} 未被消费，进程归属与"
            "邻近扫描亦未发现 HTTP 监听——检查 serve.cmd 是否引用 {port} "
            "占位符或 $FENIX_VERIFY_PORT 环境变量"
        )
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
        # 进程退出后关闭 boot.log 句柄（design D3：Popen 持句柄、退出后关闭）
        if self._boot_log is not None:
            try:
                self._boot_log.close()
            except Exception:
                pass


def _probe_ports_responding(ports) -> set:
    """并发探测一组端口，返回响应端口集合（legacy_pre 存量快照用）。

    与生产路径 pm_engine/verification/serving.py 的同名辅助同口径：同
    ThreadPoolExecutor max_workers=16、同每端口 HTTP 探测 timeout=1.0，
    端口先构造 ``http://127.0.0.1:{port}/`` 再探（_probe 收 url 不收端口，
    裸传 int 会被 Request 拒绝、恒判不响应，legacy_pre 恒空集失效）。
    不跨模块 import 复用：serving.py 已模块级反向 import 本模块，互引会
    成环，且 verify_contract 不应依赖 pipeline 层（code-review item
    92f6d9a36937）。
    """
    from concurrent.futures import ThreadPoolExecutor

    def _probe_port(port) -> bool:
        return CommandVerifyServer._probe(f"http://127.0.0.1:{port}/")

    with ThreadPoolExecutor(max_workers=16) as pool:
        return {p for p, ok in zip(ports, pool.map(_probe_port, ports)) if ok}


def provision_worktree_node_modules(
    worktree_root: Path,
    project_root: Path,
    sub_dirs: list,
    mode: str = DEFAULT_DEPS_MODE,
    logger=None,
) -> list:
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
                        main_nm,
                        wt_dir / "node_modules",
                        copy_function=os.link,
                        symlinks=True,
                        ignore_dangling_symlinks=True,
                    )
                    done.append(str(sub))
                    provisioned = True
                except OSError as e:
                    if logger:
                        logger.warning(
                            "verify_contract",
                            f"hardlink 供给失败（{sub}），降级 prefer-offline: {e}",
                        )
        if not provisioned:
            try:
                r = subprocess.run(
                    ["npm", "ci", "--prefer-offline", "--no-audit", "--no-fund"],
                    cwd=str(wt_dir),
                    capture_output=True,
                    text=True,
                    timeout=900,
                )
                if r.returncode != 0:
                    r = subprocess.run(
                        ["npm", "install", "--prefer-offline", "--no-audit", "--no-fund"],
                        cwd=str(wt_dir),
                        capture_output=True,
                        text=True,
                        timeout=900,
                    )
                if r.returncode == 0:
                    done.append(str(sub))
                elif logger:
                    logger.warning(
                        "verify_contract",
                        f"node_modules 供给失败（{sub}）: "
                        f"{(r.stderr or r.stdout or '').strip()[-200:]}",
                    )
            except (subprocess.SubprocessError, OSError) as e:
                if logger:
                    logger.warning("verify_contract", f"node_modules 供给异常（{sub}）: {e}")
    return done


def ensure_main_tree_deps(
    project_root: Path, sub_dirs: list, mode: str = DEFAULT_DEPS_MODE, logger=None
) -> list:
    """主树 prepare 前依赖预检与预装（main-tree-deps-provision D1）。

    git 不携带 node_modules，被管项目主树只被 merge-back 写入、无人手工
    ``npm install``——首次验证在 prepare（``npm run build``）时必踩
    ``tsc: not found`` 类 exit 127（add-ssh-foundation 事故，2026-09-10）。
    本入口在主树执行契约 prepare 前逐子目录预检：含 package.json 且缺
    node_modules 时按 prefer-offline 预装（主树自装 hardlink 无意义——源与
    目标重合即 self-copy，一律走 npm 安装；``mode`` 仅为与 worktree 供给同源
    的解析结果，供日志说明）。

    与 ``provision_worktree_node_modules`` 的关系（design D1）：worktree 供给
    （源=主树→目标=worktree）与主树自装（源=无，目标=主树）语义不同，独立
    入口各自可测；本函数不改造既有供给语义。

    best-effort：单目录失败记 WARNING 继续（不抛异常、不阻塞派发/验证——
    prepare 失败由既有「prepare 失败＝验证环境错误」门禁链路接管，design D3）。

    Args:
        project_root: 项目根目录（目标目录 = project_root/sub）
        sub_dirs: prepare 步骤 cwd 集合（相对 project_root；元素含 "." 表示根）
        mode: deps_mode 解析结果（调用方传 ``resolve_deps_mode`` 值；主树自装
            一律走 prefer-offline，此处仅供日志）
        logger: 日志记录器（可选）

    Returns:
        已预装依赖的目录列表（相对 project_root），供调用方记日志。
    """
    done = []
    for sub in sub_dirs:
        target = Path(project_root) / sub
        if not (target / "package.json").is_file():
            continue
        if (target / "node_modules").exists():
            continue
        try:
            r = subprocess.run(
                ["npm", "ci", "--prefer-offline", "--no-audit", "--no-fund"],
                cwd=str(target),
                capture_output=True,
                text=True,
                timeout=900,
            )
            cmd = "npm ci --prefer-offline"
            if r.returncode != 0:
                r = subprocess.run(
                    ["npm", "install", "--prefer-offline", "--no-audit", "--no-fund"],
                    cwd=str(target),
                    capture_output=True,
                    text=True,
                    timeout=900,
                )
                cmd = "npm install --prefer-offline"
            if r.returncode == 0:
                done.append(str(sub))
                if logger:
                    logger.info(
                        "verify_contract",
                        f"主树依赖预装完成（{sub}，deps_mode={mode}）: {cmd}",
                    )
            elif logger:
                logger.warning(
                    "verify_contract",
                    f"主树依赖预装失败（{sub}）: " f"{(r.stderr or r.stdout or '').strip()[-200:]}",
                )
        except (subprocess.SubprocessError, OSError) as e:
            if logger:
                logger.warning("verify_contract", f"主树依赖预装异常（{sub}）: {e}")
    return done


def _probe_vacuity_note(base_url: str, ready: ReadyProbe, probe_body: bytes) -> str:
    """就绪探针鉴别力自检：探针响应与任意不存在路径完全一致 → 无鉴别力。

    add-spec-hooks 第 1 轮 4 个 web 场景白屏 env 事故防复发（2026-09-06）：
    SPA fallback 对任意路径在 HTTP 服务一监听时即回同一 HTML，探针同秒通过
    而「就绪」未发生——探针被 fallback 吞掉，无法区分就绪/未就绪。判定法：
    探针通过后再请求一个随机不存在路径，状态码与 body（截断 4KB）完全一致
    即判探针无鉴别力（确定性无效形态，与晋升 lint 同哲学）。任意路径 404
    等 HTTPError ＝ 路径有鉴别力；自检自身异常一律放行（fail-open，不因自检
    网络抖动牵连主判定）。

    Returns:
        违规说明（探针无鉴别力时）；空串 = 有鉴别力或自检不可判。
    """
    rand_path = f"/__fenix_probe_{uuid.uuid4().hex[:12]}"
    try:
        req = Request(
            f"{base_url.rstrip('/')}{rand_path}",
            method="GET",
            headers={"User-Agent": "fenix-verify-contract"},
        )
        with urlopen(req, timeout=3) as resp:
            if resp.status != ready.expect:
                return ""
            body = resp.read(4096)
    except Exception:
        return ""
    if body != probe_body:
        return ""
    return (
        f"就绪探针无鉴别力: GET {ready.url} 与任意不存在路径（{rand_path}）响应"
        f"完全一致（status={ready.expect} 且 body 相同）——本实例对任意路径同响应"
        f"（SPA fallback 形态），探针通过≠应用就绪（add-spec-hooks 白屏 env 事故"
        f"根源，2026-09-06）。请把 ready.url 改为真实 API 端点（先例 /api/projects）。"
    )


def probe_ready(base_url: str, ready: ReadyProbe) -> tuple:
    """就绪探针：轮询 GET ``base_url + ready.url`` 直至期望状态码或超时。

    通过后做一次鉴别力自检（``_probe_vacuity_note``）：探针响应与任意不存
    在路径完全一致（SPA fallback 形态）→ 判就绪失败并给处方——探针通过但
    零鉴别力即假 ready，宁可在此大声失败也不把白屏实例推进断言窗口。

    Returns: (ok, note)
    """
    # 分隔符归一化（code-review item 223b2d551f24）：ready.url 不以 / 开头
    # （如 api/health）时直接拼接会得到 http://127.0.0.1:8080api/health 非法
    # URL，probe_ready 恒异常直至超时且用户难定位根因。
    ready_path = ready.url if ready.url.startswith("/") else f"/{ready.url}"
    url = f"{base_url.rstrip('/')}{ready_path}"
    deadline = time.time() + max(1, ready.timeout)
    last_err = ""
    while time.time() < deadline:
        try:
            req = Request(url, method="GET", headers={"User-Agent": "fenix-verify-contract"})
            with urlopen(req, timeout=3) as resp:
                if resp.status == ready.expect:
                    body = resp.read(4096)
                    vacuity = _probe_vacuity_note(base_url, ready, body)
                    if vacuity:
                        return False, vacuity
                    return True, f"就绪探针通过: {url}"
                last_err = f"状态码 {resp.status} != {ready.expect}"
        except Exception as e:
            last_err = str(e)[:120]
        time.sleep(1)
    return False, f"就绪探针超时（{ready.timeout}s）: {url} — {last_err}"


_URL_ORIGIN_RE = re.compile(r"https?://[A-Za-z0-9.\-_]+(?::\d+)?")

# ── 改写作用域（admin 修 2026-09-17：属性选择器毒化事故）──────────────
# 事故：quick-links-standalone-sync 连续 6 轮 judge 收敛到同一失败集，根因是
# 旧实现对 **test_scenarios.json 全文** 跑 origin 正则——正则落进 CSS 属性
# 选择器内部时，把「选择器字面量」当「导航目标」改写：
#     input[placeholder='https://example.com']  →  input[placeholder='http://127.0.0.1:55187']
# 该选择器从此永不匹配 DOM，6 个场景在第 5 步 type 集体超时；判官每轮正确
# 归类 test-defect 并原地修复，修复又被下一轮全文改写再次毒化 → 死循环至
# judge 重跑硬上限（6/5 轮）冻结 blocked。
#
# 改写的本来语义是 BASE_URL 铁律：`navigate`（web）与 `http_request`/
# `sse_connect`（api）的**目标地址**打新鲜实例。二者已各自有运行时通道
# （WebRunner.navigate 对扩展工程以 `self._base_url` 为准；ApiRunner 对
# step.url 走 rewrite_origin），故文件级改写只需覆盖这两类步骤的目标字段。
_ORIGIN_REWRITE_STEP_ACTIONS = {"navigate", "http_request", "sse_connect"}
_ORIGIN_TARGET_FIELDS = {
    # navigate：web 词表用 value，api 词表用 url（二者不共存，按存在者取）
    "navigate": ("value", "url"),
    "http_request": ("url",),
    "sse_connect": ("url",),
}


def _rewrite_origin_in_scenarios(raw, base_url: str) -> tuple[list, int]:
    """在场景 dict 列表上就地改写目标地址 origin，返回 (新列表, 改写处数)。

    只动作于 ``navigate`` / ``http_request`` / ``sse_connect`` 步骤的目标字段
    （见上方作用域说明）；其余字段——CSS 属性选择器（``target``）、注入
    localStorage 的测试数据（``seed.value``）、mock 的 URL 模式
    （``mock_api.target``）、断言 ``expected``——一律原样保留。

    字段值不是字符串或以非 http(s) 开头（如 ``example.com`` 裸域名、
    ``not a url`` 非法输入）时跳过：此类值是**产品行为要处理的输入**，
    不是导航目标。返回改写处数。
    """
    if not isinstance(raw, list):
        return raw, 0
    prefix = base_url.rstrip("/")

    def _rewrite_value(value: str) -> tuple[str, int]:
        return _URL_ORIGIN_RE.subn(prefix, value)

    return _rewrite_scenario_target_values(raw, requires_http_scheme=True,
                                           rewrite_value=_rewrite_value)


def _rewrite_scenario_target_values(raw, *, requires_http_scheme: bool,
                                    rewrite_value) -> tuple[list, int]:
    """改写 ``navigate`` / ``http_request`` / ``sse_connect`` 步骤目标字段的通用骨架。

    两个文件级改写点（BASE_URL 铁律的 ``rewrite_scenarios_origin`` 与端口换
    端口后的 ``_rewrite_scenario_port``）共用本骨架：只遍历导航类步骤的目标
    字段（见 ``_ORIGIN_TARGET_FIELDS``），其余字段——CSS 属性选择器
    （``target``）、注入数据（``seed.value``）、mock 模式（``mock_api.target``）、
    断言（``assertions``）——一律不触碰；非 dict/无 steps/畸形条目原样透传。

    ``rewrite_value(value) -> (new_value, n)`` 由调用方注入（origin 替换 vs
    端口替换）。``requires_http_scheme=True`` 时只处理以 http(s) 开头的值
    （裸域名、非法输入是产品行为要处理的输入，不是导航目标），
    ``False`` 时对任意字符串值调用 ``rewrite_value`` 由其自行判定。

    返回 (新列表, 改写处数合计)。
    """
    if not isinstance(raw, list):
        return raw, 0
    out: list = []
    n = 0
    for item in raw:
        if not isinstance(item, dict):
            out.append(item)
            continue
        steps = item.get("steps")
        if not isinstance(steps, list):
            out.append(item)
            continue
        new_steps: list = []
        for step in steps:
            if not isinstance(step, dict) or step.get("action") not in _ORIGIN_REWRITE_STEP_ACTIONS:
                new_steps.append(step)
                continue
            new_step = dict(step)
            for field in _ORIGIN_TARGET_FIELDS.get(step.get("action"), ()):
                if field not in new_step:
                    continue
                value = new_step[field]
                if not isinstance(value, str):
                    continue
                if requires_http_scheme and not value.startswith(("http://", "https://")):
                    continue
                new_value, k = rewrite_value(value)
                if k and new_value != value:
                    new_step[field] = new_value
                    n += k
            new_steps.append(new_step)
        out.append({**item, "steps": new_steps})
    return out, n


def rewrite_scenarios_origin(scenarios_path: Path, base_url: str) -> int:
    """把场景**目标地址**的 origin 改写为本次被测实例（BASE_URL 注入）。

    BASE_URL 铁律的执行点：无论 planner 生成什么地址，`navigate` /
    `http_request` / `sse_connect` 步骤一律打新鲜实例。只替换 scheme 锚定的
    origin（host[:port]），路径与 query 原样保留；其余字段（选择器、注入数据、
    mock 模式、断言期望）MUST NOT 触碰——详见 ``_rewrite_origin_in_scenarios``
    上方的作用域说明（2026-09-17 属性选择器毒化事故）。

    返回改写处数（0 = 文件缺失/非场景数组/无候选目标）。
    """
    try:
        raw = json.loads(scenarios_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return 0
    if not isinstance(raw, list) or not base_url:
        return 0

    rewritten, n = _rewrite_origin_in_scenarios(raw, base_url)
    if not n:
        return 0
    # 原子写回（同目录临时文件 + os.replace，与 verdict_check.save_report 同约定）：
    # 中途被杀/断电不会留下截断 JSON 损坏冻结场景集。
    import tempfile

    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=str(scenarios_path.parent), prefix=".scenarios.", suffix=".json.tmp"
        )
        try:
            with open(fd, "w", encoding="utf-8") as f:
                json.dump(rewritten, f, ensure_ascii=False, indent=2)
                f.flush()
            os.replace(tmp_path, scenarios_path)
        except OSError:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except OSError:
        return 0
    return n


# 入口存在性预检（design D1） ────────────────────────────────────────────────

# 脚本型运行时可执行名（argv[0] 去目录后）
_SCRIPT_RUNTIME_EXECS = frozenset({"node", "nodejs", "tsx", "ts-node", "bun", "deno"})

# shell 元字符：出现任一则跳过预检（复合命令保守放行，零误杀）
_SHELL_METACHARS = ("&&", "||", "|", ";", ">", "<", "$(", "`")

# 内联代码 / REPL 形态：无文件入口，跳过预检（防把代码片段当路径误杀）
_INLINE_CODE_FLAGS = frozenset({"-e", "--eval", "-p", "--print", "-i", "--interactive"})

# 入口候选的脚本扩展名白名单：带独立取值的 flag（如 node -r ts-node/register）
# 其取值同样以非 flag 形态出现，机械上无法与入口区分；仅当候选以脚本扩展名
# 结尾才判为入口，否则跳过预检（零误杀优先，漏检交给既有探活兜底）。
_SCRIPT_ENTRY_SUFFIXES = frozenset(
    {".js", ".mjs", ".cjs", ".ts", ".mts", ".cts", ".tsx"}
)


def resolve_entry_path(cmd: str, cwd: Path) -> Optional[Path]:
    """从 serve.cmd 机械解析脚本入口路径；无法解析返回 None（跳过预检）。

    确定性优先（design D1）：只拦「100% 是错误」的形态——脚本型运行时
    （node/nodejs/tsx/ts-node/bun/deno）+ 单入口 + 无 shell 元字符。
    复合命令、npm run、python -m 等其余形态一律返回 None 放行（零误杀，
    漏检交给既有探活兜底）。纯函数零 IO：文件存在性由调用方检查。

    Examples
    --------
    >>> resolve_entry_path("node dist/server.js", Path("/prj"))
    PosixPath('/prj/dist/server.js')
    >>> resolve_entry_path("npm run build && node x.js", Path("/prj")) is None
    True
    >>> resolve_entry_path("node -r ts-node/register dist/server.js", Path("/prj")) is None
    True
    """
    if not cmd or not isinstance(cmd, str):
        return None
    # shell 元字符检测（保守：出现任一即跳过）
    if any(mc in cmd for mc in _SHELL_METACHARS):
        return None
    try:
        argv = shlex.split(cmd)
    except ValueError:
        return None  # 引号不配对：无法可靠解析，跳过
    if not argv:
        return None
    exe = Path(argv[0]).name  # 去目录只看可执行名
    if exe not in _SCRIPT_RUNTIME_EXECS:
        return None  # 非脚本型运行时（npm/python/…）
    # 内联代码 / REPL 模式：无文件入口，跳过
    if any(arg in _INLINE_CODE_FLAGS for arg in argv[1:]):
        return None
    rest = argv[1:]
    # 子命令展开（deno 必带 run；bun run <script> 可能是 package.json 脚本名，保守跳过）
    if exe == "deno" and rest and rest[0] == "run":
        rest = rest[1:]
    elif exe == "bun" and rest and rest[0] == "run":
        return None
    for arg in rest:
        if arg.startswith("-"):
            continue
        # flag 的独立取值参数（node -r ts-node/register 等）不是入口：
        # 非脚本扩展名结尾的候选无法机械判定为入口 → 跳过预检（零误杀）
        if Path(arg).suffix.lower() not in _SCRIPT_ENTRY_SUFFIXES:
            return None
        return (Path(cwd) / arg).resolve()
    return None  # 只有 flag 没有入口（如 node --version）


def _entry_candidates(entry: Path) -> list:
    """缺失入口的确定性候选：同名目录下 index.js + 同目录 *.js 文件。"""
    cands = []
    parent = entry.parent
    try:
        # 1. 同名目录下的 index.js（如 dist/server.js → dist/server/index.js）
        named_dir = parent / entry.stem
        named_idx = named_dir / "index.js"
        if named_idx.is_file():
            cands.append(named_idx)
        # 2. 同目录 *.js 文件
        for p in sorted(parent.glob("*.js")):
            if p.is_file() and p not in cands:
                cands.append(p)
    except OSError:
        pass
    return cands


def entry_preflight_error(cmd: str, cwd: Path) -> Optional[str]:
    """serve.cmd 入口存在性预检；返回错误串或 None（放行）。

    调用 resolve_entry_path 解析出入口后校验文件存在性：不存在返回结构化
    错误（含缺失路径全文 + 同目录 *.js/index.js 存在候选提示），存在或
    无法解析返回 None。此为 spawn 前 fail-fast 的判定函数（design D1）。

    示例（结果依赖文件系统状态，非可执行 doctest）::

        entry_preflight_error("node dist/server.js", Path("/prj"))
        # dist/server.js 不存在时 →
        # '入口存在性预检失败: /prj/dist/server.js 不存在（候选: ... 存在）'
        entry_preflight_error("npm run build && node x.js", Path("/prj"))
        # 复合命令跳过 → None
    """
    entry = resolve_entry_path(cmd, cwd)
    if entry is None:
        return None
    if entry.is_file():
        return None
    candidates = _entry_candidates(entry)
    hint = ""
    if candidates:
        cand_strs = []
        for c in candidates[:3]:
            cand_strs.append(f"{c} 存在")
        hint = "（候选: " + "、".join(cand_strs) + "）"
    return f"入口存在性预检失败: {entry} 不存在{hint}"


# ── 契约消费期轻量自证（design D2） ─────────────────────────────────────────

SELFCHECK_FILENAME = "contract_selfcheck.json"


def selfcheck_contract_light(project_root: Path, logger=None, base_url: str = "") -> Optional[str]:
    """契约消费期轻量自证：mtime 快照门 + serve 段合法性 + ready 鉴别力自检。

    与 ``validate_contract`` 三段自证的关键差异：**不执行 prepare、不起实例**
    （消费期不承担构建/启动成本）——serve 段合法性为纯静态检查，ready 探针
    鉴别力自检仅在有现存可达实例（``base_url`` 非空）时执行。

    判定流程（design D2）：
    1. mtime 快照门：契约 mtime 与上次自证记录一致 → 返回 None（零开销）；
    2. serve 段合法性：kind 枚举、static 模式 root 目录存在、command 模式
       cmd 非空（复用 load 后的 VerifyContract + 原始 YAML serve 段，
       同 ``validate_contract`` 第 2 步口径）；
    3. ready 探测鉴别力自检：``base_url`` 非空时复用 ``probe_ready``
       （含 SPA fallback 无鉴别力判定）；为空则跳过（无实例，不起实例）；
    4. 通过 → 写 mtime 快照；失败 → 返回错误串（含段落与原因）且不写快照
       （下轮 mtime 仍落后，自动重证）。

    Returns:
        错误串（自证失败）或 None（快照命中 / 自证通过）。
    """
    project_root = Path(project_root)
    contract_path = project_root / ".fenix" / CONTRACT_FILENAME
    if not contract_path.is_file():
        return None  # 无契约：既有「无契约回退」路径处理，自证不相关
    try:
        mtime_ns = contract_path.stat().st_mtime_ns
    except OSError as e:
        return f"契约 mtime 读取失败: {e}"
    # 1. mtime 快照门
    selfcheck_path = project_root / ".fenix" / "verify-serving" / SELFCHECK_FILENAME
    try:
        if selfcheck_path.is_file():
            snap = json.loads(selfcheck_path.read_text(encoding="utf-8"))
            if isinstance(snap, dict) and snap.get("mtime_ns") == mtime_ns:
                return None  # 契约未变，零开销放行
    except Exception:
        pass  # 快照缺失/损坏 → 本次照常自证

    # 2. serve 段合法性（静态，同 validate_contract 第 2 步）
    contract = load_verify_contract(project_root, logger)
    if contract is None:
        errors = []
        try:
            raw = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                raw_serve = raw.get("serve")
                if isinstance(raw_serve, dict):
                    kind = raw_serve.get("kind", "")
                    if kind not in ("static", "command"):
                        errors.append(f"serve.kind 非法: {kind}（应为 static 或 command）")
                    elif kind == "static" and not raw_serve.get("root"):
                        errors.append("serve.root 为空（kind=static 必填）")
                    elif kind == "command" and not raw_serve.get("cmd"):
                        errors.append("serve.cmd 为空（kind=command 必填）")
        except Exception as e:
            errors.append(f"契约 YAML 解析失败: {e}")
        if errors:
            return "轻量自证失败（serve 段）: " + "；".join(errors)
        return None  # 无 serve 段（纯 cli 形态）不在消费期自证范围

    serve = contract.serve
    if serve is None:
        return None  # 无 serve 段：纯 cli 场景集，serve/ready 不相关
    if serve.kind == "static":
        if not serve.root:
            return "轻量自证失败（serve 段）: serve.root 为空（kind=static 必填）"
        root_dir = project_root / serve.root
        if not root_dir.is_dir():
            return f"轻量自证失败（serve 段）: serve.root 不存在: " f"{serve.root}（{root_dir}）"
    elif serve.kind == "command":
        if not serve.cmd:
            return "轻量自证失败（serve 段）: serve.cmd 为空（kind=command 必填）"

    # 3. ready 探针鉴别力自检（仅现存可达实例，不起实例）
    if base_url:
        ok, note = probe_ready(base_url, contract.ready)
        if not ok:
            return f"轻量自证失败（ready 鉴别力）: {note}"

    # 4. 通过 → 写 mtime 快照
    try:
        (project_root / ".fenix" / "verify-serving").mkdir(parents=True, exist_ok=True)
        selfcheck_path.write_text(json.dumps({"mtime_ns": mtime_ns}), encoding="utf-8")
    except OSError as e:
        if logger:
            logger.warning("verify_contract", f"契约自证快照写入失败（下轮重证）: {e}")
    return None
