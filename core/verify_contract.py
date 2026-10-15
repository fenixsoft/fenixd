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
      expect: 200                    # 期望 HTTP 状态码，缺省 200（仅 2xx 可命中：
                                     # 4xx/5xx 抛 HTTPError、3xx 被自动重定向
                                     # 跟随，非 2xx 期望等满 timeout 后报超时）
      timeout: 60                    # 就绪等待上限（秒），缺省 60
    # ── 可选。验证原始证据落位目录（add-verify-evidence-placement-contract
    # 1.1）。验证/核查 run 产生的原始证据（扫描结果/转储/探针产物）统一落
    # 消费项目**主树**（绝对路径 = 项目根/<evidence_dir>），与 worktree 生命
    # 周期解耦——worktree 销毁后报告引用不断链。报告本体只引用以主树根为
    # 基准的相对路径。绝对路径/".." 段等非法值记 warning 后回退缺省。
    evidence_dir: .fenix/verify-evidence/<spec>/   # 缺省如左（<spec> 按 SPEC 名替换）；
                                                   # 声明其它相对路径时以其为准

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

import errno
import fcntl
import json
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import yaml

from core.proc_utils import find_free_port, kill_process_group

CONTRACT_FILENAME = "verify.yaml"
PREPARE_STEP_TIMEOUT = 600  # 单条构建步骤上限（秒）：构建慢是常态，600s 内完不成应修构建
DEFAULT_READY_TIMEOUT = 60

# worktree node_modules 供给模式（verify.yaml deps_mode > config verify.deps_mode > 默认）
# 默认 hardlink：主树 node_modules 以 os.link 硬链接副本共享 inode，秒级且不占双倍空间。
DEPS_MODES = ("prefer-offline", "hardlink")
DEFAULT_DEPS_MODE = "hardlink"

# 验证证据落位契约（add-verify-evidence-placement-contract 1.1）：验证/核查
# 原始证据（扫描结果/转储/探针产物）统一落消费项目**主树**的目录模板，
# ``{spec}`` 按 spec 名替换。相对项目根声明；绝对路径 = 项目根/<evidence_dir>。
# 落点语义=主树：evidence 是「run 后人工核查」语义，落主树与 worktree 生命
# 周期解耦（worktree 销毁后报告引用不断链），且 .fenix/ 被消费项目忽略规则
# 覆盖、不产生 untracked 噪声——与框架既有主树运行时形态
# （.fenix/verify-progress/<spec>/report.json）一致。
DEFAULT_EVIDENCE_DIR_TEMPLATE = ".fenix/verify-evidence/{spec}"

# 验证证据分级留存阈值（verify-evidence-tiered-retention 1.2）：超过该字节数
# 的二进制证据不入 git，改以 sha256 sidecar + 复现命令 + 存放路径登记替代；
# 文本/JSON/哈希/小日志不受限直接入库。缺省 10485760（10MB）取保守值，且
# 可由契约 evidence_retention.max_binary_bytes 覆盖。
DEFAULT_EVIDENCE_MAX_BINARY_BYTES = 10485760


def default_evidence_dir(spec_name: str) -> str:
    """spec 的缺省证据目录（相对项目根的路径，POSIX 分隔符）。

    契约未声明 ``evidence_dir`` 时的回退值：``.fenix/verify-evidence/<spec>/``。
    """
    return DEFAULT_EVIDENCE_DIR_TEMPLATE.format(spec=spec_name)


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


def _prepare_run_valid(run) -> bool:
    """prepare.run 合法形态守卫：非空 str（shell）或全字符串非空 list（argv）。

    list 形态含非字符串元素（如 YAML ``run: [npm, run, 5]`` 的数字 5）时，
    run_prepare_steps 里 subprocess.Popen 直接抛 TypeError 从
    validate_contract / serving 调用链冒出，违背「构建失败返回人类可读错误
    串、按验证环境错误处理」的模块约定（code-review item 8a6f8440804e）
    ——判非法，走调用方「记 warning 忽略该步」惯例。
    """
    if isinstance(run, str):
        return bool(run)
    if isinstance(run, list):
        return bool(run) and all(isinstance(x, str) for x in run)
    return False


def _prepare_cwd_bad_reason(cwd) -> str:
    """prepare.cwd 非法判定（纯函数）：返回原因文案（合法为空串）。

    loader 与 _run_prepare_steps_unlocked 共用（code-review item
    75a115723804）：后者可被绕过 loader 的调用方（测试夹具、未来新入口）以
    手工构造的 VerifyContract 直达，run 已复检而 cwd 此前未复检——绝对路径/
    含 ".." 段的 cwd 会在 ``Path(project_root) / step.cwd`` 静默漂移到项目根
    之外执行构建。判定口径单点维护，绕过 loader 的调用方获得同等防护。
    """
    if cwd is not None and not isinstance(cwd, str):
        return "非字符串值（须为相对项目根的字符串路径）"
    cand = cwd.strip() if isinstance(cwd, str) else ""
    if cand.startswith("/"):
        return "绝对路径（须为相对项目根的路径）"
    if ".." in cand.split("/"):
        return '含 ".." 段（不得逃出项目根）'
    return ""


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
    """就绪探针：GET ``url`` 期待 ``expect`` 状态码，最长等 ``timeout`` 秒。

    expect 实际仅 2xx 取值可命中（code-review item 300c19e55fde）：探测基于
    urlopen，4xx/5xx 响应抛 HTTPError、3xx 被自动重定向跟随（比较的是重定向
    后终态码）——非 2xx 期望将轮询满 timeout 后报「就绪探针超时」。加载契约
    时对非 2xx 取值记 warning（对齐同段 url/timeout 的「告警＋回退」处理）。
    """

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
    long_test_threshold_seconds: int = 8  # 单用例耗时超过即计入长耗时表（正数）


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
    # 验证证据落位契约（add-verify-evidence-placement-contract 1.1）：相对
    # 项目根（消费项目主树）的证据目录；空=未声明（回退缺省
    # .fenix/verify-evidence/<spec>/，见 default_evidence_dir）。加载层对
    # 非法值（绝对路径/".." 段/非字符串）记 warning 后回退缺省。
    evidence_dir: str = ""
    # 验证证据分级留存阈值（verify-evidence-tiered-retention 1.2）：契约
    # evidence_retention.max_binary_bytes 的解析结果，字节为单位。加载层按
    # _positive_int_or_default 回退范式消费——缺失/非法值（负数/非整数/bool）
    # 静默回退 DEFAULT_EVIDENCE_MAX_BINARY_BYTES，不报错、不阻断契约加载。
    evidence_max_binary_bytes: int = DEFAULT_EVIDENCE_MAX_BINARY_BYTES

    def resolve_evidence_dir(self, spec_name: str) -> str:
        """该 spec 的证据目录（**相对项目根**的路径；落点语义=主树）。

        契约显式声明 ``evidence_dir`` 时以契约为准（spec delta「契约覆盖」
        场景），否则回退缺省 ``.fenix/verify-evidence/<spec>/``。返回相对
        路径：报告本体只引用以主树根为基准的相对路径，绝对路径由消费方
        join 项目根得到（项目根=消费项目主树，与 worktree 生命周期解耦）。
        """
        declared = (self.evidence_dir or "").strip()
        if not declared:
            return default_evidence_dir(spec_name)
        return declared


def load_verify_contract(project_root: Path, logger=None) -> Optional[VerifyContract]:
    """加载 ``.fenix/verify.yaml``；文件缺失/解析失败返回 None（回退旧行为）。

    解析失败属配置错误而非「无契约」：记 warning 提醒修复（静默吞掉会让
    用户以为契约生效了）。
    """
    return _load_verify_contract_with_raw(project_root, logger)[0]


def _load_verify_contract_with_raw(
    project_root: Path, logger=None
) -> tuple[Optional[VerifyContract], Optional[dict]]:
    """加载契约并同时返回原始 YAML dict：``(contract, raw_data)``。

    raw_data 与 contract 出自同一次 read_text + yaml.safe_load（code-review
    item f078ddc52b6b）：validate_contract 的 serve 段合法性判定需要原始
    YAML（本函数会静默丢弃无效 kind），单次读取两用消除「两次读取之间
    verify.yaml 被改写导致 serve 段判定与 contract 对象不是同一版本」的
    TOCTOU 窗口。契约缺失/解析失败时两者均为 None。解析行为与既有
    ``load_verify_contract`` 完全一致（后者即本函数的薄包装）。
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
        return None, None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        if logger:
            logger.warning("verify_contract", f"验证契约解析失败（按无契约回退）: {e}")
        return None, None
    if not isinstance(data, dict):
        # 顶层非映射（列表/标量/空文档）＝契约整体静默失效（prepare/serve/
        # ready 全回退旧行为），与模块「解析失败记 warning」承诺及同文件其余
        # 畸形片段「告警＋忽略该片段」哲学不一致（code-review item
        # f9617dc6f63c）——与解析异常分支同口径记 warning（原文 repr 截断）。
        if logger:
            logger.warning(
                "verify_contract",
                f"验证契约解析失败（顶层须为字段映射，按无契约回退）: "
                f"{repr(data)[:200]}",
            )
        return None, None

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
        # run 类型守卫（code-review item 716108a0bdb4）：run 为映射/数字等
        # 畸形值会在 run_prepare_steps 里被 str() 序列化成 Python 字面量形态
        # 经 shell=True 执行（垃圾命令甚至误执行片段）——先校验类型，非法
        # 按下方「记 warning 忽略该步」惯例处理。list 形态的逐元素校验见
        # _prepare_run_valid（item 8a6f8440804e）。
        elif isinstance(step, dict) and _prepare_run_valid(step.get("run")):
            # cwd 守卫（code-review item 39bd14b1b0d0）：绝对路径或含 ".." 段
            # 会让消费方 ``Path(项目根) / cwd``（_run_prepare_steps_unlocked、
            # npm 依赖预装）静默漂移到项目根之外执行构建，产物落点与
            # PrepareStep「cwd 相对项目根」的约定不符（对齐下方 serve.root/
            # evidence_dir 同款守卫口径与理由）——记 warning 后按空 cwd 回退
            # 项目根；prepare.run 本为任意 shell 命令，此非安全边界，只为保住
            # 失败归因与产物定位。
            raw_cwd = step.get("cwd")
            cand_cwd = raw_cwd.strip() if isinstance(raw_cwd, str) else ""
            # cwd 非法判定收口 _prepare_cwd_bad_reason（code-review item
            # 75a115723804）：与 _run_prepare_steps_unlocked 共用同一守卫口径
            # （非字符串值/绝对路径/含 ".." 段），文案单点维护。
            # cwd 类型守卫（code-review item 63d5e985b22d）：非字符串值
            # （如 ``cwd: 5`` 或缩进错误写成的映射）旧实现被 str() 强转成
            # "5"、"{'a': 1}" 字面量路径，随后以「第 N 步启动失败」等与
            # 根因无关的运行期错误暴露——记 warning 后按空 cwd 回退项目根
            # （走下方既有 bad_cwd_reason 路径），对齐 ready.url 同款
            # 「告警＋回退」口径（item b26b723c2ec8）。
            bad_cwd_reason = _prepare_cwd_bad_reason(raw_cwd)
            if bad_cwd_reason and logger:
                logger.warning(
                    "verify_contract",
                    f"verify.yaml prepare 第 {i} 步 cwd 非法（{bad_cwd_reason}，"
                    f"按空 cwd 回退项目根）: {raw_cwd!r}",
                )
            prepare.append(
                PrepareStep(
                    run=step["run"],
                    # 回写去空格 cand（code-review item 3f109de20d2e）：守卫按
                    # 去空格口径判定，通过后若保留未 strip 的原值，带首尾空白
                    # 的 cwd 会在消费方 ``Path(项目根) / cwd`` 处按字面空格路径
                    # 解析（npm 预装/步骤执行报与根因无关的启动失败）——与
                    # 下方 evidence_dir 分支回写 cand 同口径。
                    cwd="" if bad_cwd_reason else cand_cwd,
                )
            )
        elif logger:
            logger.warning(
                "verify_contract",
                f"verify.yaml prepare 第 {i} 步非法（须为字符串或含非空 run"
                f"（字符串/字符串列表）的映射，已忽略该步——构建步骤悄悄缺失"
                f"会验证陈旧产物）: "
                f"{repr(step)[:200]}",
            )
    serve = None
    serve_data = data.get("serve")
    # serve 段形态守卫（code-review item 48713cc5a8cb）：非 None 且非映射
    # （如 YAML 缩进错误写成 serve: myserver 标量）此前被静默落 serve=None、
    # 回退 commands.start 旧行为，用户声明了 serve 段却全链路无一处提示——
    # 记 warning（含原文 repr）对齐 prepare/ready/regression 段「告警＋忽略
    # 该片段」惯例。
    if serve_data is not None and not isinstance(serve_data, dict):
        if logger:
            logger.warning(
                "verify_contract",
                f"verify.yaml serve 段非法（须为映射，按无 serve 段处理）: "
                f"{serve_data!r}",
            )
        serve_data = None
    if isinstance(serve_data, dict) and serve_data.get("kind") in ("static", "command"):
        # serve.root 类型守卫（code-review item 63d5e985b22d）：非字符串值
        # （如 ``root: 5`` 或缩进错误写成的映射）旧实现被 str() 强转成 "5"、
        # "{'a': 1}" 字面量路径，随后以「serve.root 不存在」等与根因无关的
        # 运行期错误暴露（truthy 的非字符串也过不了 _raw_serve_section_errors
        # 的「为空」拦截）——记 warning（含原文 repr）后按空 root 回退，对齐
        # ready.url 同款「告警＋回退」口径（item b26b723c2ec8）；就地写回使
        # raw_data 与解析结果同口径（对齐下方 6e6a1c4d4f7a 守卫），static 缺
        # root 由既有链路大声失败。
        raw_root = serve_data.get("root")
        if raw_root is not None and not isinstance(raw_root, str):
            if logger:
                logger.warning(
                    "verify_contract",
                    f"verify.yaml serve.root 非法（须为字符串路径，按空 root "
                    f"处理）: {raw_root!r}",
                )
            serve_data["root"] = ""
        # serve.root 守卫（code-review item 6e6a1c4d4f7a）：kind=static 且 root
        # 为绝对路径或含 ".." 段时，消费方 ``Path(项目根) / root`` 会静默漂移到
        # 项目根之外（对齐上方 evidence_dir 同款守卫口径与理由）——记 warning
        # 后按空 root 处理：static 模式缺 root 由既有链路大声失败
        # （validate_contract 经 _raw_serve_section_errors 报「serve.root 为空」
        # 走 FAIL_SERVE_INVALID，selfcheck_contract_light 同文案自证失败且
        # fail-fast 阻断场景执行），不再进入静态服务。就地写回使 raw_data 与
        # 解析结果同口径（serve_data 即 data["serve"] 同一对象）。
        if serve_data["kind"] == "static":
            raw_root = serve_data.get("root")
            cand = raw_root.strip() if isinstance(raw_root, str) else ""
            bad_reason = ""
            if cand.startswith("/"):
                bad_reason = "绝对路径（须为相对项目根的路径）"
            elif ".." in cand.split("/"):
                bad_reason = '含 ".." 段（不得逃出项目根）'
            if bad_reason:
                if logger:
                    logger.warning(
                        "verify_contract",
                        f"verify.yaml serve.root 非法（{bad_reason}，按空 root "
                        f"处理——static 模式缺 root 走 serve 段非法失败路径）: "
                        f"{raw_root!r}",
                    )
                serve_data["root"] = ""
            else:
                # 回写去空格 cand（code-review item 3f109de20d2e）：守卫按去空
                # 格口径判定，通过后保留未 strip 原值会让带首尾空白的 root 在
                # 消费方 ``Path(项目根) / root`` 处按字面空格路径解析（误报
                # 「serve.root 不存在」），纯空白值还会凭 truthy 绕过
                # _raw_serve_section_errors 的「为空」拦截——与上方 evidence_dir
                # 分支回写 cand 同口径，就地写回兼使 raw_data 与解析结果一致。
                serve_data["root"] = cand
        # serve.cmd 类型守卫（code-review item d6154ca8743f）：非字符串值
        # （如 ``cmd: 123`` 或缩进错误写成的映射）旧实现被 str() 强转成
        # "123"、"{'a': 1}" 字面量命令，经 shell=True 启动后必然失败，只能
        # 等端口发现超时（缺省 60s）后报「注入端口未被消费」类与根因无关的
        # 错误（entry_preflight_error 对此类字面量也放行：exe 不在脚本运行
        # 时名单 → None）——记 warning（含原文 repr）后按空 cmd 回退，对齐
        # 上方 root 守卫同口径；就地写回使 raw_data 与解析结果同口径，空
        # cmd 由既有链路大声失败（validate_contract 经
        # _raw_serve_section_errors 报「serve.cmd 为空（kind=command 必填）」）。
        raw_cmd = serve_data.get("cmd")
        if raw_cmd is not None and not isinstance(raw_cmd, str):
            if logger:
                logger.warning(
                    "verify_contract",
                    f"verify.yaml serve.cmd 非法（须为字符串命令，按空 cmd "
                    f"处理）: {raw_cmd!r}",
                )
            serve_data["cmd"] = ""
        # port 是可选 legacy 端口提示：显式声明了非法值（非正整数，如
        # port: auto、port: -1）记 warning 后按无提示回退 None（item
        # 1ec46d9fe4b5，对齐同段 root/cmd 与 ready.expect/timeout 的
        # 「告警＋回退」口径；仅键缺失时保持静默）——邻近扫描兜底以该提示
        # 为锚，被静默吞掉后排查时看不到配置被忽略的证据。不得从
        # load_verify_contract 抛 ValueError——违背「解析失败按无契约回退」
        # 约定（复用 _positive_int_or_default 范式）。
        raw_port = serve_data.get("port")
        if (
            raw_port is not None
            and _positive_int_or_default(raw_port, 0) == 0
            and logger
        ):
            logger.warning(
                "verify_contract",
                f"verify.yaml serve.port 非法（须为正整数，按无 legacy 端口"
                f"提示处理）: {raw_port!r}",
            )
        port = _positive_int_or_default(raw_port, 0) or None
        serve = ServeSpec(
            kind=serve_data["kind"],
            root=str(serve_data.get("root") or ""),
            cmd=str(serve_data.get("cmd") or ""),
            port=port,
        )
    elif isinstance(serve_data, dict) and logger:
        # serve.kind 守卫（code-review item b976596e5edb）：serve 段为映射但
        # kind 非法（如大小写笔误 Static）此前整段静默落 serve=None、回退
        # commands.start 旧行为，单独使用 load_verify_contract 的调用方
        # （serving 运行时路径）零提示——记 warning（含原文 repr，文案对齐
        # _raw_serve_section_errors）对齐本函数其余片段「告警＋忽略该片段」
        # 口径；消费期 selfcheck_contract_light 的大声失败兜底不变。
        logger.warning(
            "verify_contract",
            f"verify.yaml serve 段非法（serve.kind 非法: "
            f"{serve_data.get('kind')}（应为 static 或 command），按无 serve "
            f"段处理）: {serve_data!r}",
        )
    # ready 段（code-review item c2d140a513b9）：先类型校验再取值——ready: 为
    # 标量/字符串（如 ready: /health）时 .get 抛 AttributeError 从本函数直接
    # 冒出，违背文档「解析失败按无契约处理并记 warning」约定
    # （selfcheck_contract_light 的调用不在 try 内，消费期会崩溃）。非法形态
    # 按缺省就绪探针回退（code-review item 6ac42b7af735：对齐 prepare/serve/
    # regression 段「告警＋只忽略该片段」惯例，不再整份契约作废——那会让
    # prepare 构建与 serve 声明一并静默失效，验证退回 commands.start 旧行为）；
    # expect/timeout 非法值回退缺省并记 warning（item 97f9f0e1a56e，见下方
    # 解析处）。
    ready_data = data.get("ready")
    if ready_data is not None and not isinstance(ready_data, dict):
        if logger:
            logger.warning(
                "verify_contract",
                f"verify.yaml ready 段非法（须为映射，按缺省就绪探针处理）: "
                f"{ready_data!r}",
            )
        ready_data = {}
    ready_data = ready_data or {}
    # expect/timeout 数值解析（code-review item 97f9f0e1a56e）：旧
    # ``int(... or 200)`` 让 bool 穿透——bool 是 int 子类，``expect: true`` 得
    # expect=1（探针状态码恒不匹配，静默等满 timeout 后误报「实例未就绪」）、
    # ``timeout: true`` 得 1 秒就绪窗口骤缩；``false`` 又因 falsy 被 or 静默
    # 换成缺省（配置笔误被吞）。改走 _positive_int_or_default（排除 bool，与
    # serve.port、regression 段数值解析同口径），显式给出非法值时记 warning
    # 后回退缺省。
    raw_expect = ready_data.get("expect")
    raw_timeout = ready_data.get("timeout")
    bad_ready_values = [
        f"{key}={raw!r}"
        for key, raw in (("expect", raw_expect), ("timeout", raw_timeout))
        if raw is not None and _positive_int_or_default(raw, 0) == 0
    ]
    if bad_ready_values and logger:
        logger.warning(
            "verify_contract",
            f"verify.yaml ready 段数值非法（回退缺省）: {', '.join(bad_ready_values)}",
        )
    # url 类型守卫（code-review item b26b723c2ec8）：非字符串值（如
    # ``url: 404`` 或缩进错误写成的映射）旧实现被 str() 强转成字面量形态路径
    # （"404"、"/{'a': 1}"），probe_ready 对着无意义路径轮询满 timeout 后报
    # 「就绪探针超时」，用户难定位到 ready.url 类型写错——记 warning（含原文
    # repr）后回退缺省 "/"，与同段 expect/timeout 的「告警＋回退缺省」处理
    # 同口径（item 97f9f0e1a56e）。显式声明为空串/纯空白同样处理（item
    # 64d8c89e428f）：旧实现是合法 str、通过类型守卫，随后下方
    # ``raw_url or "/"`` 静默换缺省、无任何留痕。
    raw_url = ready_data.get("url")
    if raw_url is not None and (
        not isinstance(raw_url, str) or not raw_url.strip()
    ):
        if logger:
            logger.warning(
                "verify_contract",
                f"verify.yaml ready.url 非法（须为非空字符串路径，回退缺省 "
                f"\"/\"）: {raw_url!r}",
            )
        raw_url = None
    # expect 取值可观测性（code-review item 300c19e55fde）：探测基于 urlopen，
    # 4xx/5xx 响应抛 HTTPError（probe_ready 的 status 比较不可达）、3xx 被
    # 自动重定向跟随（比较终态码）——expect 实际仅 2xx 取值能命中，配置
    # expect: 401/301 等会静默轮询满 timeout 后误报「就绪探针超时」。记
    # warning 留痕（对齐同段 url/timeout 的「告警＋回退」处理；数值本身
    # 合法故不回退，探测侧行为不变）。
    parsed_expect = _positive_int_or_default(raw_expect, 200)
    if not 200 <= parsed_expect < 300 and logger:
        logger.warning(
            "verify_contract",
            f"verify.yaml ready.expect={parsed_expect} 非 2xx（就绪探针基于 "
            f"urlopen：4xx/5xx 抛 HTTPError、3xx 被自动重定向跟随，非 2xx "
            f"期望无法命中，将等满 timeout 后报「就绪探针超时」），建议改探 "
            f"回 2xx 的真实 API 端点",
        )
    ready = ReadyProbe(
        url=raw_url or "/",
        expect=parsed_expect,
        timeout=_positive_int_or_default(raw_timeout, DEFAULT_READY_TIMEOUT),
    )
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
    # evidence_dir（add-verify-evidence-placement-contract 1.1）：可选。未
    # 声明/空 → ""（走缺省 .fenix/verify-evidence/<spec>/）。非法值（非字符串/
    # 绝对路径/含 ".." 段）记 warning 后回退缺省——绝对路径会让消费方
    # ``Path(项目根) / evidence_dir`` 静默漂移到项目根之外（Path("/p") /
    # "/abs" == /abs），".." 段同理逃出主树；「落点在主树内受控目录」的语义
    # 由加载层单点守卫（对齐 deps_mode「告警＋回退」惯例）。
    evidence_dir = ""
    raw_evidence_dir = data.get("evidence_dir")
    if raw_evidence_dir is not None:
        cand = raw_evidence_dir.strip() if isinstance(raw_evidence_dir, str) else ""
        bad_reason = ""
        if not cand:
            bad_reason = "空值或非字符串"
        elif cand.startswith("/"):
            bad_reason = "绝对路径（须为相对项目根的路径）"
        elif ".." in cand.split("/"):
            bad_reason = '含 ".." 段（不得逃出项目根）'
        if bad_reason:
            if logger:
                logger.warning(
                    "verify_contract",
                    f"verify.yaml evidence_dir 非法（{bad_reason}，回退缺省 "
                    f"{DEFAULT_EVIDENCE_DIR_TEMPLATE}）: {raw_evidence_dir!r}",
                )
        else:
            evidence_dir = cand
    # evidence_retention.max_binary_bytes（verify-evidence-tiered-retention
    # 1.2）：可选分级声明。缺失/非法值（负数/非整数/bool，含 evidence_retention
    # 整段非映射形态）一律经 _positive_int_or_default 静默回退缺省
    # 10485760——不报错、不阻断契约加载（spec 场景 2「非法值回退缺省」逐字
    # 语义）；解析结果落在 contract.evidence_max_binary_bytes，供落位指引
    # 渲染消费（load_verify_contract 与 validate_contract 经同一 loader 单源
    # 生效，后者不重复解析）。
    evidence_retention = data.get("evidence_retention")
    if isinstance(evidence_retention, dict):
        evidence_max_binary_bytes = _positive_int_or_default(
            evidence_retention.get("max_binary_bytes"),
            DEFAULT_EVIDENCE_MAX_BINARY_BYTES,
        )
    else:
        evidence_max_binary_bytes = DEFAULT_EVIDENCE_MAX_BINARY_BYTES
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
            # format 显式区分「未声明」与「声明了非法值」（item 4eef70b2b25a）：
            # 仅键缺失/显式 None 取缺省 junit；false/0 等 falsy 声明值不得经
            # or 缺省静默映射成 junit 放行——design D2 边界「声明其它值时整段
            # 视为无效」，交由下方 fmt != "junit" 分支记 WARNING 后按未配置处理。
            raw_format = reg_data.get("format")
            fmt = "junit" if raw_format is None else raw_format
            if not cmd or not output:
                if logger:
                    logger.warning(
                        "verify_contract",
                        "verify.yaml regression 段缺少必填字段 cmd/output"
                        f"（cmd={cmd!r}, output={output!r}，按未配置处理）",
                    )
            elif not _prepare_run_valid(cmd):
                # cmd 形态守卫（code-review item b7cabd40769b）：复用 prepare.run
                # 同款校验对齐口径——映射或含非字符串元素的列表（如
                # ``[npm, run, 5]`` 的数字 5）此前经真值校验放行进入
                # RegressionSpec，run_regression 里 subprocess.Popen 直接抛
                # TypeError 逃逸到调用方（下游只捕获 OSError），既拿不到结构化的
                # parse_error/launch_error 快照，错误信息也不指向契约写法问题
                # ——记 WARNING 整段按未配置处理（与缺字段/format 非法同惯例）。
                if logger:
                    logger.warning(
                        "verify_contract",
                        f"verify.yaml regression 段 cmd 非法（须为非空字符串或全"
                        f"字符串列表，整段按未配置处理）: {cmd!r}",
                    )
            elif not isinstance(output, str):
                # output 类型守卫（code-review item efb05e01fd87）：映射/数字
                # 等 truthy 非字符串值此前只经真值校验放行，被 str() 强转成
                # "{'a': 1}" 形态字面量路径存入 RegressionSpec.output，后续
                # JUnit XML 解析只能报「结果文件不存在」类与根因（类型写错）
                # 无关的 parse_error——记 warning 后整段按未配置处理，对齐
                # 上方 cmd 形态守卫与 serve.cmd 类型守卫（item d6154ca8743f）
                # 的「告警＋回退」口径。
                if logger:
                    logger.warning(
                        "verify_contract",
                        f"verify.yaml regression 段 output 非法（须为字符串"
                        f"路径，整段按未配置处理）: {output!r}",
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
                        reg_data.get("long_test_threshold_seconds"), 8
                    ),
                )
    return VerifyContract(
        prepare=prepare,
        serve=serve,
        ready=ready,
        deps_mode=deps_mode,
        regression=regression,
        evidence_dir=evidence_dir,
        evidence_max_binary_bytes=evidence_max_binary_bytes,
    ), data


def contract_file_unresolvable(project_root: Path) -> bool:
    """只读判定：契约是否处于「文件存在但不可解析」的模板态。

    add-verify-contract-preflight 1.1：fenix-init 会向每个新项目写全注释
    verify.yaml 模板——文件挂着却从未裁决，而消费期对「存在但解析为 None」
    fail-fast、对「文件缺失」放行，两者叠加使每个新项目首个 spec 必然在验证
    消费点卡 blocked。本判定供 admin_monitor 周期巡检在 spec 尚未进入验证
    消费（ready/implementing）时前置识别该形态，把契约起草前移到实现阶段
    并行完成。

    语义边界（与 ADR-080「缺失=合法无契约回退」一致）：
    - 文件缺失 → False（回退既定语义，前置预检不扩大触发面）；
    - 文件存在且 loader 返回 (None, None)（全注释模板/损坏 YAML/顶层非
      映射等「整体无效」形态）→ True。

    内部复用既有 ``_load_verify_contract_with_raw``（单次 read_text 同源），
    不二次读文件、不引入第二套解析口径；logger 传 None 保持静默（巡检周期
    会重复调用，具体解析原因由消费期路径大声告警即可）。
    """
    path = Path(project_root) / ".fenix" / CONTRACT_FILENAME
    if not path.is_file():
        return False
    contract, _raw = _load_verify_contract_with_raw(project_root, None)
    return contract is None


# valid=False 时的结构化失败原因枚举（code-review item fdb60ffde7a8）：CLI 按
# 枚举映射退出码，不再依赖人类可读文案的中文子串匹配——文案可自由调整而不
# 影响退出码语义。空串 = 非格式失败（valid=True，或失败属 prepare/serve/ready
# 运行时维度，退出码由对应段的 ok 标志决定）。
FAIL_CONTRACT_MISSING = "contract_missing"  # 契约文件不存在（exit 1）
FAIL_CONTRACT_PARSE = "contract_parse_error"  # 契约 YAML 解析失败（exit 1）
FAIL_SERVE_INVALID = "serve_invalid"  # serve 段非法（kind 非法/必填为空，exit 5）


def _raw_serve_section_errors(raw_serve) -> list:
    """serve 段静态合法性校验（纯函数）：返回错误文案列表（合法为空列表）。

    口径：kind ∈ static/command、static 模式 root 非空、command 模式 cmd
    非空。``validate_contract`` 的 valid 判定（D4）与
    ``selfcheck_contract_light`` 的消费期自证共用本函数——此前三条校验及
    错误文案在两处逐字复刻，任一侧调整口径（新增枚举值、改文案）都会与
    另一侧漂移（code-review item 13d93a1f9a25），文案单点维护。
    raw_serve 缺失（None）返回空列表（纯 cli 形态，两侧均不在此判定）；
    非 None 且非映射（如 YAML 缩进错误写成标量）返回一条形态错误——该形态
    此前与缺失同被静默当「纯 cli」放行（code-review item 48713cc5a8cb），
    验证退回 commands.start 旧行为而无任何提示。
    """
    if raw_serve is None:
        return []
    if not isinstance(raw_serve, dict):
        return [f"serve 段非法（须为映射）: {raw_serve!r}"]
    kind = raw_serve.get("kind", "")
    if kind not in ("static", "command"):
        return [f"serve.kind 非法: {kind}（应为 static 或 command）"]
    if kind == "static" and not raw_serve.get("root"):
        return ["serve.root 为空（kind=static 必填）"]
    if kind == "command" and not raw_serve.get("cmd"):
        return ["serve.cmd 为空（kind=command 必填）"]
    return []


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
    # serve 实例是否实际启动（code-review item 3d9623096956）：prepare 失败
    # 等路径下 serve 段整段跳过，而 serve_ok 保持初始 True，CLI 按其打印
    # 「✓ 通过」会向用户谎报未启动的 serve 段已通过。serve 段实际执行过才
    # 置 True，未执行段由 CLI 显示「未启动」；退出码与总体失败判定仍按
    # serve_ok，不受本标志影响。
    serve_ran: bool = False
    # prepare 构建步骤是否实际执行（code-review item f295bff223a0）：serve 段
    # 结构非法时 prepare 被跳过以省构建成本（item 82187038c510），而 prepare_ok
    # 保持初始 True——CLI 按其打印「✓ 通过」会向用户谎报从未执行的 prepare 段
    # 已通过（与 serve_ran/ready_ran 已修复的同一问题形态）。prepare 段实际
    # 执行过才置 True，未执行段由 CLI 显示「未执行」；退出码与总体失败判定
    # 仍按 prepare_ok，不受本标志影响。
    prepare_ran: bool = False
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

    # 1. 加载契约（YAML 解析）——单次读取同时取得契约对象与原始 YAML dict
    # （code-review item f078ddc52b6b：第 2 步 serve 段合法性判定复用同一份
    # raw_data，消除两次 read_text 之间 verify.yaml 被改写导致「serve 段判定
    # 基于新版本而 contract 仍是旧版本」的残留 TOCTOU 窗口）
    try:
        contract, raw_data = _load_verify_contract_with_raw(project_root, logger)
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
    # serve 段是否实际执行（供 CLI 区分「未启动」与「通过」，item 3d9623096956）
    serve_ran = False
    fail_kind = ""
    serve_kind = ""
    serve_port = None

    # 检查原始 YAML 中的 serve 段（load_verify_contract 会静默丢弃无效 kind）；
    # raw_data 与 contract 出自第 1 步同一次读取（item f078ddc52b6b），不再对
    # contract_path 二次 read_text + safe_load。校验口径与错误文案走共享的
    # _raw_serve_section_errors（与 selfcheck_contract_light 单点同源，
    # item 13d93a1f9a25）。
    if isinstance(raw_data, dict):
        serve_errors = _raw_serve_section_errors(raw_data.get("serve"))
        if serve_errors:
            valid = False
            serve_ok = False
            fail_kind = FAIL_SERVE_INVALID
            serve_error = serve_errors[0]

    # 从加载的契约中获取 serve 信息（用于输出）
    if contract.serve is not None:
        serve_kind = contract.serve.kind
        serve_port = contract.serve.port

    # 3. 执行 prepare 构建步骤
    prepare_ok = True
    prepare_error = ""
    # prepare 段是否实际执行（供 CLI 区分「未执行」与「通过」，item f295bff223a0）
    prepare_ran = False
    # prepare_steps_run 记录「声明步数」（code-review item 69f20b76f5a2）：
    # run_prepare_steps 签名仅返回错误串、无法回传实际执行到的步数（改签名
    # 会波及 serving/dist_conflicts 等调用方），CLI 据此显示「声明 N 步」，
    # 避免误读为已执行步数。
    prepare_steps_run = len(contract.prepare)
    # serve 段结构非法时跳过 prepare（code-review item 82187038c510）：此处
    # serve_ok 仅可能被第 2 步静态判定置 False（fail_kind=FAIL_SERVE_INVALID，
    # 如 kind 笔误 / root、cmd 为空），运行时 serve 失败发生在其后。此时
    # valid=False 已定，构建结果对结论无贡献，白付每步最长 600s 的构建成本
    # 只会拖慢 Administrator 草稿校验循环——结构错误先修，修好后再验 prepare。
    # 跳过后 prepare_ok/prepare_error 保持初始空态（无失败记录），
    # prepare_steps_run 仍为声明步数（item 69f20b76f5a2 口径「声明 N 步」本
    # 就不等于已执行步数）；serve/ready 段随既有 serve_ok 守卫与 base_url 判空
    # 自然跳过，返回结构不变。
    if contract.prepare and serve_ok:
        # prepare 段实际执行过——serve 段结构非法/无 prepare 步骤时跳过，
        # prepare_ran 保持 False，CLI 据此显示「未执行」而非「✓ 通过」
        # （item f295bff223a0）
        prepare_ran = True
        err = run_prepare_steps(contract, project_root, logger)
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
    # serve_ok 守卫（code-review item f0bf566bda6e）：第 2 步已判 serve 段结构
    # 非法（serve_ok=False，如 kind=static 缺 root / kind=command 缺 cmd）时
    # 不进入 serve 段——否则 static 空 root 会把项目根本体（含 .fenix/）短暂
    # 暴露在 127.0.0.1 HTTP 上，command 空 cmd 会 spawn 空 shell 命令；结构
    # 非法的契约不执行任何 serve 动作。serve_ok=True 的既有路径行为不变。
    if contract.serve is not None and prepare_ok and serve_ok:
        # serve 段实际执行过——prepare 失败/serve 段结构非法时整段跳过，
        # serve_ran 保持 False，CLI 据此显示「未启动」而非「✓ 通过」
        # （item 3d9623096956）
        serve_ran = True
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
                # 端口分配直接复用模块级 find_free_port（code-review item
                # 3e4ee4209a3d）：原函数内重复 import 与顶层 import、
                # _find_free_port 兼容包装三名字同指一函数，收敛为单一来源。
                injected_port = find_free_port()
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
                        if srv.port is not None:
                            # 端口已发现但进程已退出（ok = 端口命中且存活，此处必是
                            # poll() 非 None——如探针 GET 本身触发脆弱应用崩溃）：
                            # failure_note 只在发现阶段两条失败路径赋值，此时仍为
                            # 空串，默认文案「注入端口未被消费」会与真实根因相反
                            # （code-review item 40825790776f）——按端口是否已发现
                            # 区分两种形态，默认文案只留给端口未发现形态。
                            serve_error = (
                                f"serve 实例曾就绪（端口 {srv.port}）但进程已退出"
                                f"（exit={proc.returncode}）——检查 serve.cmd 为何在就绪后崩溃"
                            )
                        else:
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
                # 进程组照常收掉，防孤儿服务（同上 item）。组清扫纪律
                # （SIGTERM→wait→SIGKILL 补刀）单点实现在
                # core.proc_utils.kill_process_group（item 21d8a42c21c1 收口
                # 四处逐字复刻）；sigterm_only_if_alive 保持本处「leader 已退
                # 出（poll() 非 None）跳过 TERM 与宽限等待、仍补 SIGKILL」的
                # 原有口径。stdout/stderr 走 DEVNULL 无管道可排空，收尸 wait
                # 是本调用方差异化收尾，留在本处。
                kill_process_group(proc, sigterm_only_if_alive=True)
                # 收尸（code-review item 2c7a3051bb99，对齐 020ba8771283 收尸
                # 纪律）：SIGKILL 补刀后补一次 wait 回收 leader 退出状态——
                # stdout/stderr 走 DEVNULL 无管道可排空，wait 即可，不留
                # zombie 窗口靠本短命进程退出兜底。
                try:
                    proc.wait(timeout=2)
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
        serve_ran=serve_ran,
        ready_ran=ready_ran,
        prepare_ran=prepare_ran,
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


# ── 主树 prepare 主机级并发护栏（evo-add-verify-dispatch-single-flight 2.1）──
# 复用 full-suite.lock 形态（core/regression.py _SuiteLock 先例）：fcntl
# LOCK_EX 非阻塞轮询＋等待上限；获取成功后写入持有者 pid（锁残留可诊断）。
PREPARE_LOCK_REL = ".fenix/verify-prepare.lock"
PREPARE_LOCK_TIMEOUT = 600  # 锁等待下限（秒）：对齐 full-suite.lock 600s 先例。
# run_prepare_steps 按契约 prepare 步数扩展实际等待上限（至少
# N×PREPARE_STEP_TIMEOUT）——被保护段最坏持有时长逐步累加且步数无上限，
# 固定 600s 会让长构建下的并发车道等满上限后误判「锁等待超时」
# （code-review item 3d41eccb9b39）。


def _is_main_checkout(project_root) -> bool:
    """判定 project_root 是否 git 主检出（worktree 的 .git 是文件，主检出是目录）。

    verify 车道 worktree 复用（serving 方案 2）下 prepare 在 run 专属 worktree
    内执行，构建目录天然 run 级隔离；仅主检出上的 prepare 存在「两路验证并发
    擦写共享构建目录」的竞争面（neutralize-pack 事故：一路 clean 擦掉另一路刚
    归档的 .a 产物 → fail-fast 误报 blocked）。
    """
    try:
        return (Path(project_root) / ".git").is_dir()
    except OSError:
        return False


class _PrepareHostLock:
    """主树 prepare 主机级互斥（``.fenix/verify-prepare.lock`` fcntl 文件锁）。

    与 _SuiteLock 的语义差异：等待超时不按「放弃并跳过」降级——并发擦除正是
    本护栏的靶场景，无锁继续等于护栏不存在；调用方把未获锁映射为 prepare
    环境错误（fail-visible，交验证门禁拦截）。锁文件不可创建（权限等基础
    设施故障）才按无锁继续（bypassed，对齐 _SuiteLock 保守语义）。
    """

    def __init__(self, project_root, timeout: float = PREPARE_LOCK_TIMEOUT, log_fn=None):
        self._lock_path = Path(project_root) / PREPARE_LOCK_REL
        self._timeout = float(timeout)
        self._log = log_fn or (lambda msg: None)
        self._file = None
        self._acquired = False
        self._bypassed = False

    def acquire(self) -> bool:
        """尝试获取主机级锁；True=已持有，False=超时未获（bypassed 见属性）。"""
        try:
            self._lock_path.parent.mkdir(parents=True, exist_ok=True)
            # O_RDWR｜O_CREAT、MUST NOT O_TRUNC：等待方 open 截断会抹掉持有者
            # 刚写入的 pid，超时方 holder_pid() 即读到空（「未知」不可诊断）。
            fd = os.open(str(self._lock_path), os.O_RDWR | os.O_CREAT, 0o644)
            self._file = os.fdopen(fd, "r+")
        except OSError as e:
            self._bypassed = True
            self._log(f"verify-prepare: 无法创建主机级锁文件（跳过锁，无串行保证）: {e}")
            return False
        # 锁等待 deadline 用单调时钟（code-review item ee14c2595f61）：对齐
        # _discover_port/probe_ready 的既有纪律——墙上时钟在 NTP 校时回拨时
        # 会拉长并发 prepare 车道的锁等待窗、跳进时骤缩提前误判「锁等待
        # 超时」（未获锁被调用方映射为 prepare 环境错误拦截）。
        start = time.monotonic()
        while time.monotonic() - start < self._timeout:
            try:
                fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._acquired = True
                break
            except OSError:
                time.sleep(1)
        if not self._acquired:
            try:
                self._file.close()
            except OSError:
                pass
            self._file = None
            return False
        # pid 记录（design 风险项「锁残留/死锁：超时＋pid 记录」）：等待超时的
        # 后续调用经 holder_pid() 定位当前持有者（陈旧 pid 即锁残留排查线索）。
        try:
            self._file.seek(0)
            self._file.truncate()
            self._file.write(str(os.getpid()))
            self._file.flush()
        except OSError:
            pass
        self._log(
            f"verify-prepare: 主机级锁获取成功（wait={round(time.monotonic() - start, 1)}s）"
        )
        return True

    @property
    def bypassed(self) -> bool:
        """锁文件不可用而按「无锁继续」降级（区别于等待超时的未获锁）。"""
        return self._bypassed

    @property
    def timeout(self) -> float:
        return self._timeout

    def holder_pid(self) -> str:
        """读取锁文件当前内容（等待超时方定位持有者；读不到返回空串）。"""
        try:
            return self._lock_path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def release(self):
        if self._file is not None:
            try:
                if self._acquired:
                    fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                self._file.close()
            except OSError:
                pass
        self._file = None
        self._acquired = False


def run_prepare_steps(
    contract: VerifyContract, project_root: Path, logger=None
) -> Optional[str]:
    """在项目根逐条执行构建步骤。成功返回 None，失败返回人类可读错误说明。

    构建失败＝验证环境错误（调用方据此判不可达，交验证门禁拦截），不得
    静默跳过——带着陈旧产物继续验证正是本契约要消灭的场景。

    主树并发护栏（evo-add-verify-dispatch-single-flight 2.1）：project_root 为
    主检出时整个 prepare 段持主机级 fcntl 锁串行执行；锁等待超时按 prepare
    环境错误返回（fail-visible，附持有者 pid 供残留诊断）。worktree 调用
    （.git 为文件）构建目录天然 run 级隔离，不加锁零开销。per-run 隔离构建
    目录形态不采用：prepare 是 verify.yaml 声明的任意 shell 命令，框架无法
    通用重定向其产物输出路径（design 决策 3：不可行处落 fcntl 主机锁）。
    覆盖面：validate_contract（本文件）、serving 主树两调用点、
    dist_conflicts re-prepare——全部汇聚本函数，护栏单点生效。
    """
    root = Path(project_root)
    if not _is_main_checkout(root):
        return _run_prepare_steps_unlocked(contract, root, logger)
    log_fn = (lambda msg: logger.info("verify_contract", msg)) if logger else None
    # 锁等待上限按契约 prepare 步数动态取值（code-review item 3d41eccb9b39）：
    # 被保护段每步上限 PREPARE_STEP_TIMEOUT 且步数无上限，持有者可合法持锁
    # 远超固定 600s——等待上限至少覆盖 N×PREPARE_STEP_TIMEOUT 的最坏持有
    # 时长，长构建下的并发车道不再等满 600s 被误判「prepare 主机锁等待超时」
    # 而按验证环境错误拦截。步数（contract.prepare）在加锁前即已可得，锁的
    # 获取时序不变。
    lock = _PrepareHostLock(
        root,
        timeout=max(
            PREPARE_LOCK_TIMEOUT, len(contract.prepare) * PREPARE_STEP_TIMEOUT
        ),
        log_fn=log_fn,
    )
    if not lock.acquire():
        if lock.bypassed:
            # 锁基础设施故障（权限等）：按无锁继续（保守可用性，对齐
            # _SuiteLock bypassed 语义），竞争面回退原状但不断供验证。
            return _run_prepare_steps_unlocked(contract, root, logger)
        holder = lock.holder_pid()
        msg = (
            f"prepare 主机锁等待超时（>{lock.timeout:.0f}s，{PREPARE_LOCK_REL}"
            f" 持有者 pid={holder or '未知'}）— 并发 prepare 已被串行化保护，"
            "请按 pid 排查锁残留"
        )
        if logger:
            logger.warning("verify_contract", msg)
        return msg
    try:
        return _run_prepare_steps_unlocked(contract, root, logger)
    finally:
        lock.release()


def _run_prepare_steps_unlocked(
    contract: VerifyContract, project_root: Path, logger=None
) -> Optional[str]:
    """逐条执行构建步骤本体（run_prepare_steps 的无锁实现，护栏在其上游）。"""
    for i, step in enumerate(contract.prepare, 1):
        # run 形态守卫（code-review item 7525be4bf368）：loader 侧已用
        # _prepare_run_valid 拦掉映射/含非字符串元素的 list 形态 run
        # （item 716108a0bdb4/8a6f8440804e），但本函数可被绕过 loader 的调用方
        # （测试夹具、未来新入口）以手工构造的 VerifyContract 直达——dict 形态
        # run 此前经下方 str() 序列化成 Python 字面量进 shell=True 执行。判
        # 非法记 warning 忽略该步，与 loader 的「记告警忽略该步」惯例对齐。
        if not _prepare_run_valid(step.run):
            if logger:
                logger.warning(
                    "verify_contract",
                    f"prepare 第 {i} 步 run 非法（须为非空字符串或全字符串列表，"
                    f"已忽略该步——构建步骤悄悄缺失会验证陈旧产物）: "
                    f"{repr(step.run)[:200]}",
                )
            continue
        # cwd 形态守卫（code-review item 75a115723804）：本函数可被绕过
        # loader 的调用方（测试夹具、未来新入口）以手工构造的 VerifyContract
        # 直达（同上方 run 守卫动机），绝对路径/含 ".." 段的 cwd 会在
        # ``Path(project_root) / step.cwd`` 静默漂移到项目根之外执行构建——
        # 与 loader 共用 _prepare_cwd_bad_reason 判定，判非法记 warning 后
        # 按空 cwd 回退项目根，对齐 loader 的「告警＋回退」口径。
        bad_cwd_reason = _prepare_cwd_bad_reason(step.cwd)
        if bad_cwd_reason and logger:
            logger.warning(
                "verify_contract",
                f"prepare 第 {i} 步 cwd 非法（{bad_cwd_reason}，按空 cwd "
                f"回退项目根）: {step.cwd!r}",
            )
        cwd = (
            Path(project_root)
            if bad_cwd_reason or not step.cwd
            else (Path(project_root) / step.cwd)
        )
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
                # encoding/errors 固化（code-review item 3dc91dd631ad）：裸
                # text=True 按 locale 首选编码严格解码，构建输出含非 UTF-8
                # 字节（或 C/POSIX locale 下任何非 ASCII）时 communicate()
                # 抛 UnicodeDecodeError（ValueError 族）冲出本函数仅捕
                # TimeoutExpired 的 try，违背「prepare 失败返回人类可读错误
                # 串」契约——与 core/regression.py 同口径有损替换解码。
                text=True,
                encoding="utf-8",
                errors="replace",
                start_new_session=True,
            )
        # ValueError 与 OSError 同捕（code-review item c9a11de9d009）：cmd/cwd
        # 含空字节（YAML 双引号 ``\0`` 转义可过 _prepare_run_valid 的形态守卫）
        # 时 Popen 抛 ValueError 而非 OSError——不拦会从本函数冒出，冲垮只按
        # 返回值 err 串处理的验证管线与 dist rebuild 调用方。
        except (OSError, ValueError) as e:
            return f"第 {i} 步启动失败: {e}"
        try:
            out, err = p.communicate(timeout=PREPARE_STEP_TIMEOUT)
        except subprocess.TimeoutExpired:
            # 进程组清扫纪律（SIGTERM→wait→SIGKILL 补刀）单点实现在
            # core.proc_utils.kill_process_group（item 21d8a42c21c1 收口四处
            # 逐字复刻）。stdout/stderr 走 PIPE，收尸的管道排空是本调用方
            # 差异化收尾，留在本处。
            kill_process_group(p)
            # 收尸（code-review item 020ba8771283）：补一次 communicate 排空
            # stdout/stderr 管道并回收退出状态，不留 fd/僵尸窗口靠解释器 GC
            # 与下一次 Popen._cleanup 兜底。
            try:
                p.communicate(timeout=5)
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


# 静态实例端口 bind 尝试上限：find_free_port（探测即释放）与 ThreadingHTTPServer
# bind 之间存在端口被其他进程抢注的 TOCTOU 窗口（code-review item
# 657a2e747992）——bind 撞 EADDRINUSE 时重新分配再试（有限次数）；仍失败才
# 上抛，错误文案区分端口竞态与其他启动异常。
_STATIC_PORT_BIND_ATTEMPTS = 5


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
        # 端口竞态防护（item 657a2e747992）：EADDRINUSE＝探测到的端口在 bind
        # 前被抢注（HTTPServer 无法由既有 socket 构造接管，proc_utils 的
        # find_bound_socket/hold_free_port 均不适用于本类自绑定形态），换新
        # 端口重试；非竞态 OSError（权限等）不重试原样上抛，由 validate_contract
        # 归类「serve 启动异常」且文案可区分。
        last_err: Optional[OSError] = None
        for _ in range(_STATIC_PORT_BIND_ATTEMPTS):
            self._port = _find_free_port()
            try:
                self._httpd = ThreadingHTTPServer(("127.0.0.1", self._port), handler)
                break
            except OSError as e:
                if e.errno != errno.EADDRINUSE:
                    raise
                last_err = e
        else:
            raise OSError(
                f"静态实例端口连续 {_STATIC_PORT_BIND_ATTEMPTS} 次 bind 即被抢注"
                f"（EADDRINUSE，端口竞态），最后尝试端口 {self._port}"
            ) from last_err
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
        """端口活性探测：任何良构 HTTP 响应（含 401/404 等 4xx/5xx）＝有监听。

        发现语义是「端口被消费」（有无 HTTP 监听者），不是「应用就绪」——
        就绪判定是 probe_ready 的职责（期望状态码 + 鉴别力自检）。此前只认
        urlopen 成功（2xx）：鉴权型应用（dsh web 对 / 无凭据恒 401，browser-trust
        fence）即使完美启动，HTTPError 也会把探针吞成 False，端口发现必失败、
        实例被判「未就绪」（add-dsh-dashboard-bridge 验证环境事故 2026-10-14）。
        HTTPError 说明对端返回了完整 HTTP 响应＝监听者在场，与 serving.py
        _probe_url(http_error_ok=True) 的既有口径对齐；连接拒绝/超时仍判不活。
        """
        try:
            with urlopen(
                Request(url, headers={"User-Agent": "fenix-verify-probe"}), timeout=timeout
            ):
                return True
        except HTTPError:
            # 4xx/5xx 响应本身即监听证据（见 docstring）——就绪与否则交给
            # probe_ready 按契约期望值判定
            return True
        except Exception:
            return False

    @staticmethod
    def _owned_listening_ports(pgid: Optional[int], timeout: float = 5.0) -> list:
        """本进程组（start_new_session 进程森林）持有的 TCP 监听端口。

        经 ``ss -tlnp`` 属主 pid → pgid 匹配。ss 不可用/无匹配返回空列表
        （回退邻近扫描）；守护化脱离进程组的服务在此失明——那属病态部署，
        交由邻近扫描兜底。
        """
        if pgid is None:
            return []
        try:
            r = subprocess.run(
                ["ss", "-tlnp"], capture_output=True, text=True, timeout=timeout
            )
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
            # ss 调用同样受 deadline 预算钳制（code-review item 879a86c9c70a）：
            # 旧实现固定 timeout=5s，deadline 将尽的一轮仍可能阻塞满 5s，叠加
            # 尾部探针使端口发现总时长顶到 ready.timeout+5s，突破调用方声明的
            # 就绪等待上限——按剩余预算取 min（下限 0.5s 保 ss 自身有完成
            # 机会），对齐 _probe_in_budget 的预算纪律。
            for p in self._owned_listening_ports(
                pgid, timeout=min(5.0, max(0.5, deadline - time.monotonic()))
            ):
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
    def base_url(self) -> Optional[str]:
        """被测实例地址；端口未发现（启动即退出/发现超时）时返回 None。

        不得回落哨兵地址 ``http://127.0.0.1:0``——那是必探失败的非法 URL，
        单独使用（诊断脚本/新调用方）时拿不到任何根因提示（code-review
        item f2a86dbf1189）。既有调用方均先判 ``ok``／真值再取，不受影响。
        """
        if self._port is None:
            return None
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
        # 进程组清扫纪律（SIGTERM→wait→SIGKILL 补刀）单点实现在
        # core.proc_utils.kill_process_group（item 21d8a42c21c1 收口四处逐字
        # 复刻）；SIGKILL 补刀后的收尸 wait 与 boot.log 句柄关闭是本调用方
        # 差异化收尾，留在本处。
        kill_process_group(self._proc)
        # 收尸（code-review item 2c7a3051bb99，对齐 run_prepare_steps /
        # _run_npm_provision 的 020ba8771283 收尸纪律）：SIGKILL 补刀后被杀
        # leader 仍须 wait 回收退出状态——本类 stdout/stderr 走 DEVNULL 无管道
        # 可排空，补一次 wait(timeout=2) 即可，不留 zombie 窗口靠解释器 GC 与
        # 下一次 Popen._cleanup 兜底；wait(5) 已回收时立即返回。
        try:
            self._proc.wait(timeout=2)
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


def _cleanup_partial_node_modules(target: Path, logger=None) -> None:
    """供给失败后 best-effort 清理残缺的 node_modules（code-review item
    faa380dcc046）。

    hardlink copytree 中途 OSError 与 npm ci/install 失败都可能留下部分创建
    的 node_modules：供给入口的 ``exists()`` 短路下次会直接跳过，残缺依赖
    永久留存，后续 ``npm run build`` 报 ``tsc: not found`` 类错误且难以定位
    根因。清理失败只记 warning（不抛、不遮蔽原始失败日志）；目标不存在时
    静默返回（多数失败路径本就未创建目录）。
    """
    if not target.exists():
        return
    try:
        shutil.rmtree(target)
    except OSError as e:
        if logger:
            logger.warning(
                "verify_contract", f"残缺 node_modules 清理失败（{target}）: {e}"
            )


# npm 依赖供给命令上限（秒）：provision_worktree_node_modules /
# ensure_main_tree_deps 既有 timeout=900 语义收拢为常量（与 run_prepare_steps
# 的 PREPARE_STEP_TIMEOUT 分立——依赖安装与构建是两类步骤，口径不强行合并）。
NPM_PROVISION_TIMEOUT = 900


def _run_npm_provision(argv: list, cwd: Path) -> subprocess.CompletedProcess:
    """npm 供给命令执行（start_new_session + 超时进程组清扫）。

    subprocess.run 超时只 kill 直接子进程，npm 派生的 node 孙进程未经收组
    残留，可继续写 node_modules，与紧随的 ``_cleanup_partial_node_modules``
    的 rmtree 竞态（code-review item 79741f3caf63）——按
    ``run_prepare_steps`` 同款组清扫纪律（item 2fa170366d6b/7168a8391e06）：
    start_new_session 使 leader 即进程组长（pgid == p.pid），提前取定句柄
    防 wait 回收 leader 后 getpgid 失效；超时 SIGTERM 组 → wait(5) →
    SIGKILL 组补刀 → 补 communicate 排空管道收尸，随后按 subprocess.run 同
    约定向调用方抛 TimeoutExpired（由既有 ``except (SubprocessError,
    OSError)`` 清理路径接管）。Popen 的 OSError 同样交由调用方捕获。
    """
    p = subprocess.Popen(
        argv,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        # encoding/errors 固化（code-review item 3dc91dd631ad）：裸 text=True
        # 严格解码，npm 输出含非 UTF-8 字节时 communicate() 抛
        # UnicodeDecodeError（ValueError 族），调用方只捕
        # (SubprocessError, OSError) 接不住，异常冲出供给入口——与
        # core/regression.py 同口径有损替换解码。
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=True,
    )
    try:
        out, err = p.communicate(timeout=NPM_PROVISION_TIMEOUT)
    except subprocess.TimeoutExpired:
        # 进程组清扫纪律（SIGTERM→wait→SIGKILL 补刀）单点实现在
        # core.proc_utils.kill_process_group（item 21d8a42c21c1 收口四处
        # 逐字复刻）。stdout/stderr 走 PIPE，收尸的管道排空是本调用方
        # 差异化收尾，留在本处。
        kill_process_group(p)
        # 收尸：补一次 communicate 排空 stdout/stderr 管道并回收退出状态。
        try:
            p.communicate(timeout=5)
        except Exception:
            pass
        raise
    return subprocess.CompletedProcess(argv, p.returncode, out, err)


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
                    # copytree 中途失败会残留残缺 node_modules（item
                    # faa380dcc046）——降级前先清理，防 exists() 短路永久留存
                    _cleanup_partial_node_modules(wt_dir / "node_modules", logger)
        if not provisioned:
            try:
                r = _run_npm_provision(
                    ["npm", "ci", "--prefer-offline", "--no-audit", "--no-fund"],
                    wt_dir,
                )
                if r.returncode != 0:
                    r = _run_npm_provision(
                        ["npm", "install", "--prefer-offline", "--no-audit", "--no-fund"],
                        wt_dir,
                    )
                if r.returncode == 0:
                    done.append(str(sub))
                else:
                    if logger:
                        logger.warning(
                            "verify_contract",
                            f"node_modules 供给失败（{sub}）: "
                            f"{(r.stderr or r.stdout or '').strip()[-200:]}",
                        )
                    # npm ci/install 失败可能留下部分创建的 node_modules（item
                    # faa380dcc046）——清理后下次供给才会重装而非被短路跳过
                    _cleanup_partial_node_modules(wt_dir / "node_modules", logger)
            except (subprocess.SubprocessError, OSError) as e:
                if logger:
                    logger.warning("verify_contract", f"node_modules 供给异常（{sub}）: {e}")
                # 超时/异常中断同样可能残留半成品目录（item faa380dcc046）
                _cleanup_partial_node_modules(wt_dir / "node_modules", logger)
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
            r = _run_npm_provision(
                ["npm", "ci", "--prefer-offline", "--no-audit", "--no-fund"],
                target,
            )
            cmd = "npm ci --prefer-offline"
            if r.returncode != 0:
                r = _run_npm_provision(
                    ["npm", "install", "--prefer-offline", "--no-audit", "--no-fund"],
                    target,
                )
                cmd = "npm install --prefer-offline"
            if r.returncode == 0:
                done.append(str(sub))
                if logger:
                    logger.info(
                        "verify_contract",
                        f"主树依赖预装完成（{sub}，deps_mode={mode}）: {cmd}",
                    )
            else:
                if logger:
                    logger.warning(
                        "verify_contract",
                        f"主树依赖预装失败（{sub}）: " f"{(r.stderr or r.stdout or '').strip()[-200:]}",
                    )
                # npm 失败可能留下部分创建的 node_modules（item
                # faa380dcc046）——清理后下次预装才会重装而非被短路跳过
                _cleanup_partial_node_modules(target / "node_modules", logger)
        except (subprocess.SubprocessError, OSError) as e:
            if logger:
                logger.warning("verify_contract", f"主树依赖预装异常（{sub}）: {e}")
            # 超时/异常中断同样可能残留半成品目录（item faa380dcc046）
            _cleanup_partial_node_modules(target / "node_modules", logger)
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
    # deadline 用单调时钟（code-review item 95c98a055b78）：对齐
    # _discover_port/_probe_in_budget 的既有纪律——墙上时钟在 NTP 校时回拨时
    # 会拉长就绪等待窗、跳进时骤缩误报超时。
    deadline = time.monotonic() + max(1, ready.timeout)
    last_err = ""
    while time.monotonic() < deadline:
        # 轮询按时限钳制（code-review item 3898f0d542ad）：urlopen 超时按剩余
        # 预算取 min(3.0, …)、sleep 钳制为剩余预算，对齐 _discover_port.
        # _probe_in_budget 纪律（旧实现二者固定 3s/1s，timeout=60 时最坏约
        # 63-64s，突破声明时限）。
        budget = deadline - time.monotonic()
        try:
            req = Request(url, method="GET", headers={"User-Agent": "fenix-verify-contract"})
            with urlopen(req, timeout=min(3.0, budget)) as resp:
                if resp.status == ready.expect:
                    body = resp.read(4096)
                    vacuity = _probe_vacuity_note(base_url, ready, body)
                    if vacuity:
                        return False, vacuity
                    return True, f"就绪探针通过: {url}"
                last_err = f"状态码 {resp.status} != {ready.expect}"
        except Exception as e:
            last_err = str(e)[:120]
        time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
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


def _rewrite_origin_in_scenarios(raw, base_url: str, logger=None) -> tuple[list, int]:
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
        # userinfo/IPv6 形态守卫（code-review item 8aca6686700c）：
        # _URL_ORIGIN_RE 只界定 host[:port]——对 ``https://user:pass@host/path``
        # 匹配到 "https://user" 即止（``:pass`` 非 ``:数字``），前缀替换会产出
        # ``http://127.0.0.1:PORT:pass@host/path`` 的非法 URL，步骤必然失败且
        # 报错与根因（改写）无关；IPv6 字面量主机（``http://[::1]:8000/``）同样
        # 只吞到空串边界。按 authority 界定（scheme 后、首个 ``/`` 前）检测：
        # 含 ``@``（userinfo）或以 ``[`` 开头（IPv6）即跳过改写记 warning，保留
        # 原地址交运行时 rewrite_origin 通道兜底——仅路径/query 内嵌 ``@`` 的
        # 正常 URL 不受影响。
        authority = value.split("://", 1)[-1].split("/", 1)[0]
        if "@" in authority or authority.startswith("["):
            if logger:
                logger.warning(
                    "verify_contract",
                    f"场景目标含 userinfo/IPv6 形态地址，跳过 origin 改写"
                    f"（保留原地址）: {value[:120]}",
                )
            return value, 0
        # code-review item 5ea13f017c5c：只改写字符串起点锚定的目标 origin——
        # 全局 subn 会把 query/路径内嵌的其它绝对 URL（?redirect=、CDN 等
        # 跨域引用）一并改成被测实例地址。与运行时 ApiRunner.rewrite_origin
        # 同规则（只换目标自身 origin，其余原样保留）；requires_http_scheme
        # 已保证 value 以 http(s):// 开头，正常形态必命中起点 origin。
        m = _URL_ORIGIN_RE.match(value)
        if not m:
            return value, 0
        return prefix + value[m.end():], 1

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


def rewrite_scenarios_origin(scenarios_path: Path, base_url: str, logger=None) -> int:
    """把场景**目标地址**的 origin 改写为本次被测实例（BASE_URL 注入）。

    BASE_URL 铁律的执行点：无论 planner 生成什么地址，`navigate` /
    `http_request` / `sse_connect` 步骤一律打新鲜实例。只替换 scheme 锚定的
    origin（host[:port]），路径与 query 原样保留；其余字段（选择器、注入数据、
    mock 模式、断言期望）MUST NOT 触碰——详见 ``_rewrite_origin_in_scenarios``
    上方的作用域说明（2026-09-17 属性选择器毒化事故）。

    Args:
        scenarios_path: 场景文件路径
        base_url: 本次被测实例地址（空串按无需改写处理）
        logger: 可选日志记录器（写失败时记 WARNING 留痕）

    Returns:
        改写处数；0 = 文件缺失/非场景数组/无候选目标（本无需改写；场景文件
        存在但 JSON/UTF-8 解析失败或读取失败（OSError）同样返 0，但经 logger
        记 WARNING 留痕，code-review item 9f64a2a702bc/687c424565d9）；
        -1 = 已解析出候选目标但写盘失败——BASE_URL 铁律未落盘，与 0 可判别
        （code-review item 90ca963ad6e7：写失败与「本无需改写」同返 0 时，
        冻结场景集静默携带 planner 原地址且不可观测）。写失败经 logger 记
        WARNING（对齐模块「解析失败大声告警」哲学）但不抛异常——api 场景
        另有 ApiRunner 运行时 rewrite_origin 双通道兜底，文件级写失败不升级
        为整轮验证崩溃。
    """
    try:
        raw = json.loads(scenarios_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return 0
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        # 文件在但解析失败 ≠ 「本无需改写」（code-review item 9f64a2a702bc）：
        # 与缺失/非场景数组同返 0 会让冻结场景集静默携带 planner 原地址且
        # 不可观测，与本模块「解析失败大声告警」哲学不符——记 WARNING 留痕
        # 后仍返 0（调用方语义不变；api 场景另有 ApiRunner 运行时
        # rewrite_origin 双通道兜底，损坏文件也会在后续场景加载处暴露）。
        if logger:
            logger.warning(
                "verify_contract",
                f"场景文件解析失败（BASE_URL origin 改写跳过，文件在但非合法 "
                f"UTF-8 JSON）: {scenarios_path}: {e}",
            )
        return 0
    except OSError as e:
        # 读取失败（权限不足/IsADirectoryError 等非 FileNotFoundError 的
        # OSError）≠「本无需改写」（code-review item 687c424565d9）：与上方
        # JSON/UTF-8 解析失败分支同口径记 WARNING 留痕后仍返 0，避免落入
        # 「BASE_URL 改写未执行且不可观测」的静默形态。
        if logger:
            logger.warning(
                "verify_contract",
                f"场景文件读取失败（BASE_URL origin 改写跳过）: {scenarios_path}: {e}",
            )
        return 0
    if not isinstance(raw, list) or not base_url:
        return 0

    rewritten, n = _rewrite_origin_in_scenarios(raw, base_url, logger)
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
                # fsync 落盘后再 rename，断电才真正不会留下截断 JSON（对齐全仓原子写惯例）
                os.fsync(f.fileno())
            # mkstemp 产物固定 0600，还原原文件权限，避免 os.replace 后权限漂移
            try:
                os.chmod(tmp_path, scenarios_path.stat().st_mode & 0o777)
            except OSError:
                pass
            os.replace(tmp_path, scenarios_path)
        except OSError:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except OSError as e:
        # 写失败 ≠ 本无需改写：解析已完成、候选目标存在，BASE_URL 铁律静默
        # 未执行须可判别（code-review item 90ca963ad6e7）——返回可区分哨兵
        # -1 并记 WARNING 留痕（0 保留给「文件缺失/非场景数组/无候选目标」）。
        if logger:
            logger.warning(
                "verify_contract",
                f"场景 origin 改写写盘失败（BASE_URL 注入未落盘，场景集仍携带"
                f"原地址）: {scenarios_path}: {e}",
            )
        return -1
    return n


# 入口存在性预检（design D1） ────────────────────────────────────────────────

# 脚本型运行时可执行名（argv[0] 去目录后）
_SCRIPT_RUNTIME_EXECS = frozenset({"node", "nodejs", "tsx", "ts-node", "bun", "deno"})

# shell 元字符：出现任一则跳过预检（复合命令保守放行，零误杀）
_SHELL_METACHARS = ("&&", "||", "|", ";", ">", "<", "$(", "`")

# 内联代码 / REPL 形态：无文件入口，跳过预检（防把代码片段当路径误杀）
_INLINE_CODE_FLAGS = frozenset({"-e", "--eval", "-p", "--print", "-i", "--interactive"})

# 入口候选的脚本扩展名白名单：仅当候选以脚本扩展名结尾才判为入口，否则
# 跳过预检（零误杀优先，漏检交给既有探活兜底）。常见带独立取值的 flag 经
# 下方 _FLAGS_WITH_VALUE 连同紧随取值一并跳过；名单之外的未知取值 flag
# 由本后缀规则兜底。
_SCRIPT_ENTRY_SUFFIXES = frozenset(
    {".js", ".mjs", ".cjs", ".ts", ".mts", ".cts", ".tsx"}
)

# 带独立取值的 flag 名单（code-review item 30c2a89fa2a1）：预加载/加载器类
# flag 的取值同样以非 flag 形态出现且常以脚本扩展名结尾（`node -r
# ./polyfill.js dist/server.js` 的 polyfill.js 不是入口）——旧循环把首个非
# flag 参数当入口，取值文件不存在而真实入口存在时预检误报「入口不存在」
# 拦截本可正常启动的服务。命中名单连同紧随取值一并跳过后再找入口。
_FLAGS_WITH_VALUE = frozenset(
    {
        "-r", "--require",  # node -r ts-node/register
        "--import",  # node --import tsx
        "--loader", "--experimental-loader",  # node --loader tsx/esm
        "--preload",  # bun --preload ./preload.ts
    }
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
    >>> resolve_entry_path("node -r ts-node/register dist/server.js", Path("/prj"))
    PosixPath('/prj/dist/server.js')
    >>> resolve_entry_path("node -r ./polyfill.js dist/server.js", Path("/prj"))
    PosixPath('/prj/dist/server.js')
    >>> resolve_entry_path("node -r ./missing.js", Path("/prj")) is None
    True
    >>> resolve_entry_path("node $APP_DIR/server.js", Path("/prj")) is None
    True
    >>> resolve_entry_path("node ${SRC}/main.ts", Path("/prj")) is None
    True
    >>> resolve_entry_path("node ~/server.js", Path("/prj")) is None
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
    i = 0
    while i < len(rest):
        arg = rest[i]
        # 带独立取值的已知 flag（node -r ./polyfill.js 等）：连同紧随取值
        # 一并跳过——取值不是入口（code-review item 30c2a89fa2a1）
        if arg in _FLAGS_WITH_VALUE:
            i += 2
            continue
        if arg.startswith("-"):
            i += 1  # --flag=value 形态或无独立取值的 flag
            continue
        # $VAR/${VAR}/~ 形态（code-review item 836709d3af31）：serve.cmd 走
        # shell=True 启动时由 shell 展开，本可命中真实文件，静态存在性检查
        # 对字面路径必然落空——按「无法静态解析」跳过预检，与引号不配对
        # 分支同口径（零误杀，spawn 后交给既有探活兜底）。
        if "$" in arg or arg.startswith("~"):
            return None
        # 名单之外的未知取值 flag 兜底：非脚本扩展名结尾的候选无法机械判定
        # 为入口 → 跳过预检（零误杀）
        if Path(arg).suffix.lower() not in _SCRIPT_ENTRY_SUFFIXES:
            return None
        return (Path(cwd) / arg).resolve()
    return None  # 只有 flag 没有入口（如 node --version）


def _entry_candidates(entry: Path) -> list:
    """缺失入口的确定性候选：同名目录下 index.<ext> + 同目录脚本后缀文件。

    后缀口径与 ``_SCRIPT_ENTRY_SUFFIXES`` 白名单同源（code-review item
    880535661beb）：TS/ESM 项目写 ``node dist/server.ts`` 时，同目录 *.ts 与
    dist/server/index.ts 候选同样进入提示，不再只扫 *.js——提示覆盖面与
    入口后缀白名单保持一致。逐后缀扫描、组内字典序 + 去重，保持既有排序
    语义（排序确定性供调用方取前 3 候选展示）。
    """
    cands = []
    parent = entry.parent
    try:
        # 1. 同名目录下的 index.<ext>（如 dist/server.js → dist/server/index.js）
        named_dir = parent / entry.stem
        for ext in sorted(_SCRIPT_ENTRY_SUFFIXES):
            named_idx = named_dir / f"index{ext}"
            if named_idx.is_file() and named_idx not in cands:
                cands.append(named_idx)
        # 2. 同目录各脚本后缀文件（逐后缀 glob，组内字典序）
        for ext in sorted(_SCRIPT_ENTRY_SUFFIXES):
            for p in sorted(parent.glob(f"*{ext}")):
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

# 消费期 ready 鉴别力自检的探测窗口上限（秒）。契约 ready.timeout（缺省 60s）
# 是「起实例后等就绪」的预算，自证不起实例、只对现存实例做鉴别力抽查，窗口
# 按轻量定位单独钳制（code-review item bf322f67f5dd）。
SELFCHECK_READY_TIMEOUT = 5


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

    # 2. serve 段合法性（静态，同 validate_contract 第 2 步）。单次读取同时
    # 取得契约对象与原始 YAML dict（_load_verify_contract_with_raw，对齐
    # validate_contract 第 1 步口径，item f078ddc52b6b）：旧实现 load 后再对
    # verify.yaml 二次裸读复检 serve/ready 段，两次读取之间契约被改写时静态
    # 检查结论与已加载 contract 对象可能出自不同版本（code-review item
    # b64c1ac34f79）。
    contract, raw_data = _load_verify_contract_with_raw(project_root, logger)
    if contract is None:
        # 解析失败/顶层非映射等「契约整体无效」形态：具体原因
        # 已由 _load_verify_contract_with_raw 记 warning（单次读取下 raw_data
        # 与 contract 同为 None，无法也无需二次裸读判别具体形态），自证仍
        # 大声失败（不写快照，下轮 mtime 变化自动重证），否则验证无声落入
        # 无契约回退（commands.start）。
        return (
            "轻量自证失败（serve/ready 段）: 契约解析失败（按无契约回退）"
            "——详见 verify_contract 告警"
        )

    serve = contract.serve
    if serve is None:
        # serve 段解析为 None 有两种形态：真无 serve 段（纯 cli，放行）与
        # serve 段声明了但形态非法被「告警＋忽略」（code-review item
        # 48713cc5a8cb）——后者按同一次读取的 raw_data 复检 serve 段，否则
        # 用户声明了 serve 段却在此按「纯 cli 形态」静默放行、验证退回
        # commands.start 旧行为。复检口径与 validate_contract 第 2 步单点
        # 同源（_raw_serve_section_errors）。
        if isinstance(raw_data, dict) and raw_data.get("serve") is not None:
            errs = _raw_serve_section_errors(raw_data.get("serve"))
            if errs:
                return "轻量自证失败（serve 段）: " + "；".join(errs)
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
        # 消费期探测窗口钳制（code-review item bf322f67f5dd）：base_url 非空只
        # 代表上游记录过地址，实例可能已被回收——直接复用 probe_ready 会按契约
        # 声明的 ready.timeout（缺省 60s）整窗轮询，消费期自证在验证关键路径上
        # 退化成最长一分钟的阻塞。按自证「轻量」定位把探测窗口钳到
        # SELFCHECK_READY_TIMEOUT（仍足够判死实例与 SPA fallback 鉴别力）；
        # url/expect 原样保留，契约 ready.timeout 的完整语义只作用于起实例后
        # 的正式就绪等待（validate_contract / serving），不可达大声失败的既有
        # 语义（失败不写快照、下轮重证）不变。
        ready_probe = ReadyProbe(
            url=contract.ready.url,
            expect=contract.ready.expect,
            timeout=min(contract.ready.timeout, SELFCHECK_READY_TIMEOUT),
        )
        ok, note = probe_ready(base_url, ready_probe)
        if not ok:
            return f"轻量自证失败（ready 鉴别力）: {note}"

    # 4. 通过 → 写 mtime 快照
    try:
        (project_root / ".fenix" / "verify-serving").mkdir(parents=True, exist_ok=True)
        # 非原子写（本文件 rewrite_scenarios_origin 用 mkstemp+fsync+os.replace）：
        # 快照损坏由上方读取侧 except Exception 容错兜住（照常重证，代价仅多
        # 一轮自证），低价值快照不为此引入原子写复杂度（item 79fdee435fdc）。
        selfcheck_path.write_text(json.dumps({"mtime_ns": mtime_ns}), encoding="utf-8")
    except OSError as e:
        if logger:
            logger.warning("verify_contract", f"契约自证快照写入失败（下轮重证）: {e}")
    return None
