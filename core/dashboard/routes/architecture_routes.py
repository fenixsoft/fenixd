"""architecture_routes.py — 项目架构图 (add-project-architecture-tab) routes。

承载 3 个端点：
- GET  /api/architecture/status  （query project）→ 生成状态（四态机）
- POST /api/architecture/refresh （query project）→ 受理触发生成（后台线程）
- GET  /api/architecture/diagram （query project）→ 下发 diagram.html（text/html）

端点 handler 走既有 mixin 形态（self._json / self._error），project 均从
query string 解析，不消费请求体（对齐 regression_routes POST 契约；残留
body 字节由派发层 _drain_remaining_request_body 排空）。

生成机制（换用 floorplan：单段式管线）：POST 只受理——起 daemon 守护线程
跑**单段** headless claude 管线，磁盘为唯一交接面：一个小 prompt 的 run
按 vendored floorplan skill（``vendor/floorplan``）的工作流出图——
scan.mjs 机械扫描 → 读 references 契约 → 写 architecture.json（分段小步
写）→ build.mjs 迭代构建至 clean → map 目录内 serve.mjs --export 导出单
文件 ``.fenix/architecture/diagram.html``。SKILL.md 与 references 均以包
根绝对路径引用、不内嵌全文，prompt 落在「小上下文 × 短输出」安全区
（bigmodel 网关对该形态之外的大请求存在静默丢弃）。MUST NOT 在 HTTP 线
程内同步等待。前端 generating 期间 3s 轮询 status。

（此前的两段式探索/出图与 evidence HEAD 指纹复用已随 floorplan 替换
移除：floorplan 的 scan 脚本本身即是便宜的机械取证，无材料可复用。）

产物与状态存储（沿用）：项目根 ``.fenix/architecture/{diagram.html,
status.json, floorplan/}``（gitignored 运行时产物；``floorplan/`` 为
floorplan 脚本产物目录——scan 缓存、architecture.json、graph.json、
index.html 及 build 生成的 serve.mjs/query.mjs，保留供排查）。status.json
每次状态迁移 tmp+rename 原子写，结构含存量六键 ``state/generated_at/
started_at/error/duration_ms/component_count`` 加可选键 ``stage``
（mapping/终态 null；component_count 语义为 architecture.json 顶层子系
统节点数）。dashboard 进程内模块级 ``ArchitectureManager`` 持 per-project
单飞锁与在飞进程句柄，为该目录的唯一写者（单写者原则）。
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

# add-harness-adapter-layer 4.1：一次性 spawn 收编入口（架构图 autodraft）
from core.agent_runner.harness import (
    ENV_MODE_CLEAN,
    PROMPT_TRANSPORT_ARGV,
    ClaudeAdapter,
    SpawnRequest,
)
from core.agent_runner.harness.one_shot import (
    OneShotCommunicateError,
    run_one_shot,
)
from core.proc_utils import guard_killpg

# ── 模块级 logger（code-review item 967909e7db47：refresh 先前以
# getattr(self, 'logger', None) 取值恒为 None（handler 未定义 logger
# 属性），生成管线日志分支全静默丢失；改传模块 logger 并保持
# warning/info 单参消息形态，spawn 失败/超时击杀/判定失败等路径
# 真实留痕）──────────────────────────────────────────────────────
logger = logging.getLogger("fenixd.dashboard.routes.architecture_routes")

# ── 模块常数（不新增配置项，对齐 autodraft 先例）─────────────────────

# 单段硬超时（秒）：沿用原两段式管线的总预算 1800s（floorplan 单段含机械
# scan/build，正常远快于此）；超时以进程组方式击杀（防孙进程残留）。
_GENERATE_TIMEOUT_SECONDS = 1800

# 击杀后排干上限（秒）：SIGKILL 进程组后直连子进程应立即退出、管道随即
# EOF；若孙进程曾重新 setsid 逃出进程组并继承 stdout/stderr 管道句柄，EOF
# 永不到来——无上限的 communicate() 会把生成线程永久卡在 _run_stage 内，
# 单飞锁不释放、该项目后续 refresh 全 409（reap_all docstring 承认的
# knowledge.py 同款已知形态，code-review item 4ac76808cb18）。超时即放弃
# 排干（对齐 reap_all 口径：管道回收交进程退出）。
_REAP_DRAIN_TIMEOUT_SECONDS = 10

# 生成完成 marker 协议（autodraft marker 范式）：生成 run stdout 末行
# ``FLOORPLAN_DONE <顶层节点数>``。
FLOORPLAN_MARKER_PREFIX = "FLOORPLAN_DONE"

# 形态契约：architecture.json 顶层子系统节点数允许区间（floorplan skill
# 自身契约即 3–9）。能提取节点数时越界判 failed；无法提取（marker 缺失）
# 记 component_count=null 放行（沿用原 design D5 口径）。
NODE_COUNT_MIN = 3
NODE_COUNT_MAX = 9

# 产物相对路径（项目根下，gitignored 运行时目录族）。
ARCHITECTURE_DIR = ".fenix/architecture"
STATUS_FILENAME = "status.json"
DIAGRAM_FILENAME = "diagram.html"
# floorplan 脚本产物目录（scan 缓存 / architecture.json / index.html /
# serve.mjs 等），位于 ARCHITECTURE_DIR 下、保留不清理。
MAP_DIRNAME = "floorplan"

# env 剔除口径（D1.11）：一次性架构图生成与 agent-run 无关，MUST NOT 注入
# agent-run 专用上下文。原 _build_spawn_env/_BANNED_ENV_KEYS 助手已随 spawn
# 链路收编进 harness.run_one_shot 删除（code-review item 4dd2fccdabd6），
# 口径由 SpawnRequest.env_mode=ENV_MODE_CLEAN 数据化承接（见 _run_stage）、
# 键集单一来源仍在 core/agent_env_keys.py。


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _vendored_skill_root() -> Path:
    """floorplan vendored 包根：``<repo>/vendor/floorplan``。

    以本文件位置锚定仓库根（routes → dashboard → core → 仓库根），脱离
    daemon 进程 cwd 依赖（worktree 内跑单测同样成立）。skill 以 vendored
    形式随库分发（VENDORED.md 溯源），生成链路零联网安装、零用户环境依赖。
    """
    return Path(__file__).resolve().parents[3] / "vendor" / "floorplan"


def _skill_ready() -> bool:
    """vendored 包完整性检查：SKILL.md 与关键脚本存在且非空。

    缺失/为空属部署损坏，由调用方判 failed（不触发任何安装动作）。
    """
    root = _vendored_skill_root()
    required = (
        root / "SKILL.md",
        root / "scripts" / "scan.mjs",
        root / "scripts" / "build.mjs",
        root / "scripts" / "lib" / "common.mjs",
    )
    try:
        return all(p.is_file() and p.stat().st_size > 0 for p in required)
    except OSError:
        return False


_SKILL_VENDORED_MISSING_ERROR = (
    "floorplan skill 包缺件（vendor/floorplan/SKILL.md 或关键脚本缺失/为空），"
    "属部署损坏，请对照 vendor/floorplan/VENDORED.md 恢复包后重试"
)


def _map_dir(proot: Path) -> Path:
    """floorplan 脚本产物目录（design：.fenix/architecture/floorplan/）。"""
    return proot / ARCHITECTURE_DIR / MAP_DIRNAME


def _build_generate_prompt(proot: Path, project_name: str) -> str:
    """单段生成提示词：~2KB 小 prompt——SKILL.md 与 references 以绝对路径
    引用（先读再开工，不内嵌全文）+ floorplan 工作流子集 + 形态约束 +
    分段小步写纪律 + FLOORPLAN_DONE marker 协议。所有脚本调用统一
    FLOORPLAN_UNATTENDED=1（unattended 模式只写 map 目录、不写
    CLAUDE.local.md、不动 .git/info/exclude、不起服务器不开浏览器）。"""
    skill_root = _vendored_skill_root()
    map_dir = _map_dir(proot).resolve()
    arch_json = (map_dir / "architecture.json").resolve()
    scan_json = (map_dir / ".cache" / "scan.json").resolve()
    diagram = (proot / ARCHITECTURE_DIR / DIAGRAM_FILENAME).resolve()
    return f"""为当前项目（{project_name}，项目根即当前工作目录）绘制一张高层**运行时架构图**，
使用 vendored 的 floorplan skill（随库分发、无需安装、全程无网络依赖）。

【第一步：先读再开工】完整阅读以下文件（均以绝对路径引用，不随本提示词内嵌）：
1. floorplan skill 指引：{skill_root / "SKILL.md"}
   - 指引原文中的 ${{CLAUDE_SKILL_DIR}} 占位符即包根 {skill_root}，相对路径均相对它解析；
2. {skill_root / "references" / "schema.md"}（architecture.json 契约）；
3. {skill_root / "references" / "choosing-boundaries.md"}（子系统边界划分方法）。

【执行步骤】严格按以下子集执行（全部脚本统一加 FLOORPLAN_UNATTENDED=1 前缀）：
1. 机械扫描：`FLOORPLAN_UNATTENDED=1 node {skill_root}/scripts/scan.mjs . --out {scan_json} --json`
2. 在项目根写 {arch_json}：按 schema 与边界方法划分 3–9 个顶层子系统节点
   （每个大节点可带 3–12 个子节点），配 1–3 条 flows 与 3–8 站 tour；
   第三方服务/外部存储用 external 节点表达（packages/hosts 字段）。
3. 构建：`FLOORPLAN_UNATTENDED=1 node {skill_root}/scripts/build.mjs . --out {map_dir} --json`，
   按报错迭代修复 architecture.json 直至 ok=true（unassigned < 10%）。
4. 导出最终产物：`node {map_dir}/serve.mjs --export {diagram}`。

【硬性约束】
- 节点 label/summary、flows、tour 与全部图面文字一律中文（白话、面向所有人）。
- 只抽象高层子系统，不穷举目录与文件；每个节点 summary 一句话讲清职责。
- 本项目禁跑 describe.mjs / recent.mjs / open.mjs / status.mjs / refresh.mjs /
  plan.mjs（逐文件描述与 Ask 服务器等交互特性不需要，导出产物开箱即用）。
- 除 .fenix/architecture/ 目录内文件外，MUST NOT 修改项目内任何其他文件。
- architecture.json 分段小步写，禁止单次巨量 Write：先写最小骨架文件
  （nodes 空数组占位），再逐段用 Edit 补全，每次只补一两个节点，写完即落盘。

【完成标记】导出成功后，stdout 的最后一行必须输出且仅输出一个 marker：
FLOORPLAN_DONE <顶层节点数>
其中 <顶层节点数> 为 architecture.json 顶层节点的实际数量（整数）。"""


# status.json 业务键（存量六键 + stage）单一来源：_status_payload 的载荷
# 键集与 status() 补键循环共用（code-review item 1f4de9307452），新增状态
# 键单点改此常量并同步 _status_payload 形参即可。
_STATUS_KEYS = (
    "started_at",
    "generated_at",
    "error",
    "duration_ms",
    "component_count",
    "stage",
)


def _status_payload(
    state: str,
    *,
    started_at: str | None = None,
    generated_at: str | None = None,
    error: str | None = None,
    duration_ms: int | None = None,
    component_count: int | None = None,
    stage: str | None = None,
) -> dict:
    """status.json 全字段形态：存量六键恒在（未 applicable 为 null），加可
    选键 ``stage``（单段编排运行态：mapping，终态与受理初态为 null——读侧
    容忍缺键/多键，向后兼容）。component_count 语义为 floorplan
    architecture.json 顶层子系统节点数。"""
    payload = {"state": state}
    # zip 两侧按 _STATUS_KEYS 与形参序一一对应（dict 保序，序列化形状不变）。
    payload.update(dict(zip(_STATUS_KEYS, (
        started_at, generated_at, error,
        duration_ms, component_count, stage,
    ))))
    return payload


def _write_status(proot: Path, payload: dict) -> None:
    """status.json 原子写（tmp + os.replace）。"""
    arch = proot / ARCHITECTURE_DIR
    arch.mkdir(parents=True, exist_ok=True)
    tmp = arch / (STATUS_FILENAME + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(tmp, arch / STATUS_FILENAME)


def _read_status(proot: Path) -> dict | None:
    """读 status.json；缺失/损坏/非 dict → None（读侧按 none 态兜底）。"""
    path = proot / ARCHITECTURE_DIR / STATUS_FILENAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _extract_component_count(stdout: str | None) -> int | None:
    """从 stdout 尾部提取 ``FLOORPLAN_DONE <顶层节点数>``（autodraft marker
    范式：claude 可能用代码块包裹输出，剥反引号后前缀匹配）；协议约定
    marker 为 stdout 最后一行，倒序扫描取最后一条可解析出整数的 marker 行
    （正文回显的协议说明文字不可解析，跳过不干扰判定）；缺失 → None。"""
    tail = (stdout or "")[-2000:]
    for line in reversed(tail.splitlines()):
        s = line.strip().strip("`").strip()
        if s.startswith(FLOORPLAN_MARKER_PREFIX):
            try:
                return int(s[len(FLOORPLAN_MARKER_PREFIX):].strip())
            except ValueError:
                continue
    return None


def _is_selfcontained_html(path: Path) -> bool:
    """自包含 HTML 特征：文件起始（允许 BOM/空白）为 ``<!DOCTYPE html`` 或
    ``<html`` 前缀（大小写不敏感；floorplan 导出产物起始为小写
    ``<!doctype html``，同判自包含）。"""
    try:
        with path.open("rb") as f:
            # code-review item 5806fa31b2b2：读取窗口取 4KB——前缀匹配只需
            # 覆盖「前导空白/BOM/注释」的容忍量级，512B 会把带超长前导空白
            # 的合法产物误判为非自包含；4KB 对文档头绰绰有余且远小于产物
            # 整体体积（超出 4KB 前导空白仍判非自包含，属可接受假设）。
            # BOM（U+FEFF）与空白同由下方 lstrip 消化，前缀匹配语义不变。
            head = f.read(4096)
    except OSError:
        return False
    text = head.decode("utf-8", errors="replace").lstrip("﻿ \t\r\n").lower()
    return text.startswith("<!doctype html") or text.startswith("<html")


def _judge_artifact(
    diagram_path: Path, returncode: int, stdout: str | None, logger=None
) -> tuple[str, str | None, int | None]:
    """产物权威判定链（不信 claude 自述）。

    退出码 → 产物存在且非空 → 自包含 HTML 特征 → 顶层节点数 ∈ [3,9]。
    返回 (state, error, component_count)；marker 缺失时节点数记 None 放行
    （形态校验尽力而为，产物可用性优先）。
    """
    if returncode != 0:
        return "failed", f"claude 进程非零退出（exit={returncode}），产物不可信", None
    # code-review item dbc757042726：is_file 与 stat 之间存在 TOCTOU，产物
    # 并发消失时 stat 抛 OSError，须与缺失分支同归同一文案，避免穿到
    # _run_generation 兜底误报「内部错误」。
    try:
        artifact_missing = (
            not diagram_path.is_file() or diagram_path.stat().st_size == 0
        )
    except OSError:
        artifact_missing = True
    if artifact_missing:
        return (
            "failed",
            f"生成产物缺失或为空（{ARCHITECTURE_DIR}/{DIAGRAM_FILENAME}）",
            None,
        )
    if not _is_selfcontained_html(diagram_path):
        return (
            "failed",
            "生成产物不是自包含 HTML（缺少 <!DOCTYPE html>/<html> 起始特征）",
            None,
        )
    count = _extract_component_count(stdout)
    if count is None:
        # marker 缺失 → 无法机械校验节点数，记 null 放行（沿用 design D5）
        return "ready", None, None
    if not (NODE_COUNT_MIN <= count <= NODE_COUNT_MAX):
        if logger is not None:
            logger.warning(
                f"架构图顶层节点数越界（count={count}，"
                f"allowed=[{NODE_COUNT_MIN}, {NODE_COUNT_MAX}]）",
            )
        return (
            "failed",
            f"架构图顶层子系统节点数为 {count}，超出允许范围 "
            f"[{NODE_COUNT_MIN}, {NODE_COUNT_MAX}]（floorplan 形态契约）",
            count,
        )
    return "ready", None, count


class ArchitectureManager:
    """架构图生成管理器（dashboard 进程内单例）。

    持 per-project 单飞锁与在飞进程句柄（design D2：唯一写者）；生成状态经
    status.json 原子写持久化，刷新页面/daemon 重启不丢态（重启残留的
    generating 由读侧合成 failed，spec「生成生命周期治理」）。
    """

    def __init__(self) -> None:
        self._guard = threading.Lock()
        # [fenix-ignore:fbcd65ba1a25] 锁按被访问过的项目惰性创建、每把开销字节级且项目数量级受控（上限假设：项目集有限），引入无在飞项目的惰性回收需新增加锁协议，并发风险大于收益
        self._locks: dict[str, threading.Lock] = {}
        self._procs: dict[str, subprocess.Popen] = {}

    def _key(self, proot: Path) -> str:
        return str(proot.resolve())

    def _lock_for(self, proot: Path) -> threading.Lock:
        key = self._key(proot)
        with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._locks[key] = lock
            return lock

    def in_flight(self, proot: Path) -> bool:
        """该项目是否有在飞生成（单飞锁被后台线程持有）。"""
        return self._lock_for(proot).locked()

    def status(self, proot: Path) -> dict:
        """读侧状态（四态机）。

        - status.json 缺失/损坏 → ``none``（全字段 null）；
        - 残留 ``generating`` 且在飞线程/进程不在（daemon 曾重启）→ 合成
          ``failed``（中断），MUST NOT 永久停留在 generating。

        在飞判定 MUST 先于读文件：终态写入严格先于锁释放（_run_generation
        各路径 _finish 后才在 finally 释放锁），故「锁未被持有」即终态必已
        落盘——此时读到 generating 只能是重启残留。反之先读后判存在竞态：
        读到 generating 后生成线程才完成「写终态+释放锁」，会把已完成的
        生成误合成为中断（实测假失败）。

        首判定为非在飞仍须复核（item cae05392adba）：判定与读文件两步之间
        他线程 refresh 可刚受理并写 generating（锁自受理起持有至终态落盘才
        释放），过期快照会把刚受理的生成误合成中断——故合成前按首判定同一
        「在飞先于读文件」纪律复核：先二次查在飞、后重读状态，仍非在飞才
        合成（item 6eaea59dd68a）。
        """
        alive = self._in_flight_alive(proot)
        data = _read_status(proot)
        if data is None:
            return _status_payload("none")
        state = str(data.get("state") or "")
        if state == "generating" and not alive:
            # code-review item cae05392adba：在飞判定与读文件两步之间存在
            # 间隙——另一线程的 refresh() 可在 alive 判定之后、读文件之前
            # 完成受理（acquire 单飞锁并写 generating），本次读到的
            # generating 配上过期快照 alive=False 会把刚受理的生成误合成
            # 为中断。单飞锁自受理起持有、终态写盘后才释放，故合成前按首
            # 判定同一纪律复核：先二次查在飞、后重读状态（code-review
            # item 6eaea59dd68a：旧序「先重读后查在飞」的两次动作之间若恰
            # 有新一轮 refresh 受理且其生成完整走完，重读捕获的 generating
            # 配上翻转后的 alive=False 会把刚 ready 的生成误合成为中断；
            # 对调后重读所见的 generating 若出自 T2 前受理的生成必已被在飞
            # 判定捕捉，不再与「判定后才完成」的终态翻转相撞）。复核已回
            # 到在飞 → 落到下方按正常 generating 返回；重读已非
            # generating → 以新读结果为准；仍 generating 且复核仍非在飞才
            # 合成 failed（残留缺口仅剩「二次在飞判定与重读之间恰好受理」
            # 的窄窗口，下一轮轮询按在飞正常返回即自愈）。
            alive = self._in_flight_alive(proot)
            data = _read_status(proot) or data
            state = str(data.get("state") or "")
            if state == "generating" and not alive:
                synth = _status_payload(
                    "failed",
                    started_at=data.get("started_at"),
                    error="生成被中断（daemon 重启或后台线程已不存在），请重新点击「刷新架构图」",
                )
                return synth
        # code-review item 31f86e2da065：state 四态白名单归一——文件为合法
        # JSON 但 state 是白名单外值（手改/半截写入映射漂移）时不得原样透传
        # 给前端，归一为 none 并附 error 标注（文件缺失/损坏/非 dict 已由
        # _read_status 走 none 兜底，此处只补「合法 JSON + 非法 state」档；
        # 空/缺失 state 维持既有 none 口径不额外标错）。
        invalid_state = bool(state) and state not in (
            "none", "generating", "ready", "failed",
        )
        if invalid_state:
            state = "none"
        # 补齐存量六键 + stage（旧版残留文件可能缺键；键集单一来源
        # _STATUS_KEYS，code-review item 1f4de9307452）
        full = _status_payload(state or "none")
        for key in _STATUS_KEYS:
            if key in data:
                full[key] = data.get(key)
        if invalid_state:
            full["error"] = "状态文件 state 值非法，已按未生成处理，请重新点击「刷新架构图」"
        return full

    def _in_flight_alive(self, proot: Path) -> bool:
        """在飞判定：单飞锁被持有，或在飞进程句柄仍存活。"""
        if self.in_flight(proot):
            return True
        with self._guard:
            proc = self._procs.get(self._key(proot))
        return proc is not None and proc.poll() is None

    def reap_all(self) -> None:
        """收割全部在飞生成进程（dashboard 退出链，serve() finally 调用）。

        _procs 登记的 claude 处于独立会话组（start_new_session=True），不随
        dashboard 进程退出而终止；退出后孤儿仍以 bypassPermissions 继续写
        diagram.html，并与用户重启后重新触发的下一轮生成并发写同一文件
        （code-review item dffc01af10fa）。退出链对每个登记句柄
        killpg(SIGKILL) 整组终止（killpg 先例：core/knowledge.py
        _kill_process_group）；目标已退出属可预期竞态，与守卫拒绝（自身组/
        非正 pgid）同样静默：ProcessLookupError/OSError 一律不降级单 pid
        proc.kill（对齐下方行内注释与 guard_killpg 的 resolve 语义）。不在
        此排干管道/清理 _procs：SIGKILL 后
        communicate 可能被逃出进程组的孙进程无限阻塞（knowledge.py 同款已知
        形态），收尾交由仍在飞的生成线程自身 finally 完成。
        """
        with self._guard:
            procs = list(self._procs.values())
        for proc in procs:
            # 击杀经自保护守卫（add-killpg-self-guard，resolve 型）：守卫拒绝
            # （自身组/非正 pgid）与组已不存在同样静默，不降级单 pid proc.kill
            # （pid=0 经 os.kill 折算同为调用者自身组广播）。
            guard_killpg(
                proc.pid, signal.SIGKILL, caller="architecture_routes.reap_all", resolve=True
            )

    def refresh(
        self, proot: Path, project_name: str, logger=None
    ) -> tuple[bool, bool, str | None]:
        """受理一次生成（POST refresh：只受理不同步等待）。

        返回 (accepted, conflict, error)：
        - 受理 → (True, False, None)：写入 generating 态并起 daemon 守护线程；
        - 单飞冲突（在飞时再触发）→ (False, True, msg)→调用方回 409；
        - 状态写盘失败 → (False, False, msg)→调用方回 500；
        - 线程启动失败 → (False, False, msg)→调用方回 500（回写 failed 终态
          并释放单飞锁，不留卡死 generating）。
        """
        lock = self._lock_for(proot)
        if not lock.acquire(blocking=False):
            return False, True, "该项目的架构图生成正在进行中，请稍候"
        started_at = _utcnow_iso()
        try:
            _write_status(proot, _status_payload("generating", started_at=started_at))
        except Exception as exc:  # noqa: BLE001 — item 7c1787f26168：只捕
            # OSError 会放走 _write_status 非 OSError 异常（如 json.dumps
            # 序列化类），此处持锁已成功则锁不释放、generating 终态也不落
            # 盘，后续该项目 refresh 恒 409 至 daemon 重启；口径对齐
            # _finish（item 1e7127422a27）。BaseException 仍照常穿出不吞。
            lock.release()
            # code-review item 955818ba1bd9：异常文本可携带内部绝对路径/
            # errno 属主细节，不得内嵌进响应体（对齐 regression_routes/
            # help_routes 既有口径）：客户端只收固定文案，细节降级服务端日志。
            if logger is not None:
                logger.warning(
                    f"架构图状态写入失败（project={project_name}）: "
                    f"{type(exc).__name__}: {exc!r}",
                )
            return False, False, "架构图状态写入失败"
        thread = threading.Thread(
            target=self._run_generation,
            args=(proot, project_name, started_at, lock, logger),
            daemon=True,
            name=f"floorplan-gen-{project_name}",
        )
        try:
            thread.start()
        except Exception as exc:  # noqa: BLE001 — 系统线程资源耗尽等 RuntimeError
            # code-review item 1295fb028cb4：start() 抛异常若放任逃逸，单飞锁
            # 不释放、status.json 恒卡 generating——同进程内 in_flight() 恒真，
            # refresh 全 409，仅 daemon 重启才由读侧合成 failed，不可自愈。
            # 终态写入 MUST 严格先于锁释放（status() 读侧契约：「锁未被持有」
            # 即终态必已落盘），故先 _finish 再 release；随后按既有失败形态
            # (False, False, msg) 交调用方回 500。
            if logger is not None:
                logger.warning(
                    f"架构图生成线程启动失败（project={project_name}）: "
                    f"{type(exc).__name__}: {exc!r}",
                )
            try:
                self._finish(
                    proot,
                    started_at,
                    time.monotonic(),
                    "failed",
                    error=f"后台生成线程启动失败（{type(exc).__name__}），请重试",
                    logger=logger,
                )
            finally:
                lock.release()
            return False, False, "架构图生成线程启动失败，请重试"
        return True, False, None

    def _write_stage(
        self, proot: Path, started_at: str, stage: str, logger=None
    ) -> None:
        """在飞阶段迁移落盘（state 仍 generating + stage 键）：生成 run
        spawn 前写，前端轮询可辨当前段。尽力而为：写失败不中断生成。"""
        try:
            _write_status(
                proot,
                _status_payload("generating", started_at=started_at, stage=stage),
            )
        except Exception as exc:  # noqa: BLE001 — item c51307f7d48d：只捕
            # OSError 会放走 _write_status 的非 OSError 异常（如 json.dumps
            # 序列化类），穿出后被 _run_generation 兜底把整轮生成判 failed，
            # 违背本助手「写失败不中断生成」承诺；宽捕口径对齐 refresh()/
            # _finish()（item 7c1787f26168/1e7127422a27），BaseException 仍
            # 照常穿出不吞，warning 留痕不静默。
            if logger is not None:
                logger.warning(
                    f"架构图阶段状态写入失败（stage={stage}）: "
                    f"{type(exc).__name__}: {exc!r}",
                )

    def _run_stage(
        self,
        proot: Path,
        project_name: str,
        key: str,
        *,
        prompt: str,
        timeout: int,
        stage_label: str,
        logger=None,
    ) -> tuple[bool, int | None, str | None, str | None, str | None]:
        """运行一段生成 run：spawn → communicate(timeout) → 超时进程组
        SIGKILL 击杀（既有 killpg 范式）。

        返回 (ok, returncode, stdout, stderr, error)：
        - ok=True：进程已退出（returncode 可能非零，交调用方判定链处理）；
        - ok=False：spawn 失败/通信异常/超时击杀，error 为带阶段前缀的
          失败文案，调用方直接 failed 短路。
        """
        # 收编进 harness.run_one_shot（add-harness-adapter-layer 4.1）：claude
        # 命令构造唯一入口在 claude_adapter.build_spawn_spec——prompt 经 argv
        # 传输（SpawnRequest.prompt_transport=argv，本车道现状形态）、无
        # --output-format、bypassPermissions、env 口径 ENV_MODE_CLEAN、独立
        # 会话组。进程组击杀/排干序列保留本文件自有助手（直 SIGKILL+短上限
        # 排干+wait(0) 收尸，不走缺省两段式）；登记锁 scope 对齐：spawn_guard
        # 只罩「Popen + on_spawn 登记」（item 69eb4844d0b5 临界区语义——
        # spawn 失败时不入集合，无悬挂占位句柄可供 reap_all 误杀），长等待
        # 留在锁外。
        def _reap_stage_proc(proc) -> None:
            # 进程组击杀（autodraft 同款）：claude 派生的 bash/node 写文件孙进程
            # 一并终止，锁释放后无在途写者。击杀经自保护守卫（add-killpg-
            # self-guard，resolve 型）：守卫拒绝（自身组/非正 pgid）与组已不
            # 存在同样静默，不降级单 pid proc.kill。
            guard_killpg(
                proc.pid, signal.SIGKILL,
                caller="architecture_routes._run_stage", resolve=True,
            )
            try:
                # 短上限排干（_REAP_DRAIN_TIMEOUT_SECONDS）：超时说明有孙进程
                # 逃出进程组占着管道，放弃排干保锁释放（进程退出兜底回收）
                proc.communicate(timeout=_REAP_DRAIN_TIMEOUT_SECONDS)
            except Exception:  # noqa: BLE001 — 含 TimeoutExpired（放弃排干）
                # 排干超时≠直连子进程未死：SIGKILL 已生效，超时只是孙进程
                # 逃出进程组占着管道。直连子进程此时已死但尚未 wait 收尸，
                # wait(0) 即刻收尸（regression_routes._reap_autodraft_proc
                # 同款，item 54b12852e6bd）：缺这一步则 dashboard 进程存续
                # 期内每次超时清场残留一个僵尸进程。
                try:
                    proc.wait(timeout=0)
                except Exception:  # noqa: BLE001
                    pass

        try:
            outcome = run_one_shot(
                ClaudeAdapter(),
                SpawnRequest(
                    prompt=prompt,
                    cwd=str(proot),
                    prompt_transport=PROMPT_TRANSPORT_ARGV,
                    output_format=None,
                    permission_mode="bypassPermissions",
                    env_mode=ENV_MODE_CLEAN,
                    project_root=str(proot),
                ),
                timeout=timeout,
                on_spawn=lambda proc: self._procs.__setitem__(key, proc),
                on_timeout=_reap_stage_proc,
                spawn_guard=self._guard,
            )
        except OneShotCommunicateError as exc:
            # 通信期异常兜底清场已在 run_one_shot 内复用超时分支序列
            # （code-review item 7ab006a03686：管道 OSError 等异常路径同样
            # 不得在 finally 摘除句柄并释放单飞锁后留下仍在飞的生成进程组）
            if logger is not None:
                logger.warning(
                    f"claude 进程通信异常（project={project_name}，"
                    f"{stage_label}）: {type(exc.original).__name__}: {exc.original!r}",
                )
            return False, None, None, None, f"claude 进程通信失败（{stage_label}）"
        except Exception as exc:  # noqa: BLE001 — CLI 不存在等 spawn 失败
            if logger is not None:
                logger.warning(
                    f"调用 claude CLI 异常（project={project_name}，"
                    f"{stage_label}）: {type(exc).__name__}: {exc!r}",
                )
            return False, None, None, None, "调用 claude CLI 失败"
        finally:
            with self._guard:
                self._procs.pop(key, None)
        if outcome.timed_out:
            if logger is not None:
                logger.warning(
                    f"架构图生成{stage_label}超时（>{timeout}s，"
                    f"project={project_name}）；已终止整个进程组",
                )
            return (
                False,
                None,
                None,
                None,
                f"{stage_label}超时（>{timeout}s 未完成），已终止生成进程",
            )
        return True, outcome.returncode, outcome.stdout, outcome.stderr, None

    def _run_generation(
        self,
        proot: Path,
        project_name: str,
        started_at: str,
        lock: threading.Lock,
        logger=None,
    ) -> None:
        """生成线程体（单段管线）：vendored 包完整性检查 → mapping 段标记
        → 清理旧图 → 生成 run → 权威判定链 → 状态落盘。锁在线程结束时
        释放（finally）。"""
        key = self._key(proot)
        t0 = time.monotonic()
        diagram_path = proot / ARCHITECTURE_DIR / DIAGRAM_FILENAME
        try:
            # ── 1) vendored floorplan 包完整性检查 ───────────────────
            if not _skill_ready():
                self._finish(
                    proot, started_at, t0, "failed",
                    error=_SKILL_VENDORED_MISSING_ERROR,
                    logger=logger,
                )
                return
            try:
                (proot / ARCHITECTURE_DIR).mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                # code-review item 9b347b701799：OSError 文本可携带内部绝对路径/
                # errno 属主细节，随 status.json 原样下发浏览器属口径漂移——对齐
                # refresh() 同款脱敏（item 955818ba1bd9）：客户端只收固定文案，
                # 异常细节降级服务端日志留痕。
                if logger is not None:
                    logger.warning(
                        f"架构图运行目录创建失败（project={project_name}）: "
                        f"{type(exc).__name__}: {exc!r}",
                    )
                self._finish(
                    proot, started_at, t0, "failed",
                    error="架构图运行目录创建失败",
                    logger=logger,
                )
                return

            # ── 2) 生成 run（单段）──────────────────────────────────
            self._write_stage(proot, started_at, "mapping", logger=logger)
            # code-review item 6271296f09ad：spawn 前清理上一轮残留的旧图，
            # 使「产物存在」本身即代表本轮写入——claude 自述完成（exit=0 +
            # FLOORPLAN_DONE marker）但写盘被静默拒绝时，判定链的缺失分支
            # 即判 failed，旧图不再原样穿链混入本轮 ready。清理尽力而为：
            # 失败不阻塞本轮（降级为修复前行为），细节留服务端日志；判
            # failed 后重新触发 refresh 即重出图（既有 failed 恢复语义）。
            try:
                diagram_path.unlink(missing_ok=True)
            except OSError as exc:
                if logger is not None:
                    logger.warning(
                        f"架构图旧产物清理失败（project={project_name}）: "
                        f"{type(exc).__name__}: {exc!r}",
                    )
            ok, rc, stdout, stderr, err = self._run_stage(
                proot, project_name, key,
                prompt=_build_generate_prompt(proot, project_name),
                timeout=_GENERATE_TIMEOUT_SECONDS,
                stage_label="生成",
                logger=logger,
            )
            if not ok:
                self._finish(
                    proot, started_at, t0, "failed", error=err, logger=logger
                )
                return

            # ── 3) 产物权威判定链 ───────────────────────────────────
            state, error, count = _judge_artifact(diagram_path, rc, stdout, logger)
            if logger is not None and state == "failed":
                logger.warning(
                    f"架构图生成判失败（project={project_name}，"
                    f"returncode={rc}）：{error}；"
                    f"stderr 尾部: {(stderr or '')[-400:] if isinstance(stderr, str) else ''}",
                )
            self._finish(
                proot, started_at, t0, state, error=error, component_count=count,
                logger=logger,
            )
        except Exception as exc:  # noqa: BLE001 — 兜底判定链等意外异常
            # code-review item 3f4adc8143f0：意外异常若放任穿出线程体，终态未
            # 落盘而锁已被 finally 释放，违反「终态写入 MUST 严格先于锁释放」
            # 读侧契约（同 refresh 线程启动失败路径 item 1295fb028cb4）。兜底
            # 只走本分支：正常成功/正常 failed 路径均提前 return，不经此处。
            if logger is not None:
                logger.warning(
                    f"架构图生成线程意外异常（project={project_name}）: "
                    f"{type(exc).__name__}: {exc!r}",
                )
            self._finish(
                proot, started_at, t0, "failed",
                error="架构图生成因内部错误终止，请重试",
                logger=logger,
            )
        finally:
            lock.release()

    def _finish(
        self,
        proot: Path,
        started_at: str,
        t0: float,
        state: str,
        *,
        error: str | None = None,
        component_count: int | None = None,
        logger=None,
    ) -> None:
        """终态落盘（ready/failed）：generated_at 仅 ready 填、duration_ms 全程。"""
        duration_ms = int((time.monotonic() - t0) * 1000)
        try:
            _write_status(
                proot,
                _status_payload(
                    state,
                    started_at=started_at,
                    generated_at=_utcnow_iso() if state == "ready" else None,
                    error=error,
                    duration_ms=duration_ms,
                    component_count=component_count,
                ),
            )
        except Exception as exc:
            # code-review item 1e7127422a27：只捕 OSError 会放走终态写入调用
            # （json.dumps/write_text/os.replace）抛出的非 OSError 异常，终态
            # 未落盘而锁随调用方 finally 释放，违反读侧「终态写入 MUST 严格
            # 先于锁释放」契约（严格度对齐 refresh 线程启动失败路径
            # item 1295fb028cb4）；BaseException 仍照常穿出不吞。
            # code-review item 79585a2bd0c7：不逃逸线程（读侧按残留态兜底）
            # 但须留痕服务端日志——残留 generating 合成的「生成被中断」无法
            # 与真实写盘故障区分，口径对齐本模块其余失败路径。
            if logger is not None:
                logger.warning(
                    f"架构图终态写盘失败（proot={proot}）: "
                    f"{type(exc).__name__}: {exc!r}",
                )


# dashboard 进程内单例（design D2 单写者）。测试经独立 tmp 项目隔离，
# 键为 resolve 后的项目根，互不串扰。
_MANAGER = ArchitectureManager()


class H13ArchitectureRoutesMixin:
    """H13 architecture（对齐 H12 Regression 汇聚方式；H12 已被占用）。"""

    def _architecture_manager(self) -> ArchitectureManager:
        return _MANAGER

    def _api_architecture_status(self, query):
        """GET /api/architecture/status?project=<name>

        返回生成状态：``{project, state, started_at, generated_at, error,
        duration_ms, component_count, stage}``，state ∈
        none|generating|ready|failed；stage 仅 generating 期间非 null
        （mapping，向后兼容可选键）。项目不存在 → 404。
        """
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        proot = Path(project["path"])
        data = self._architecture_manager().status(proot)
        self._json({"project": project["name"], **data})

    def _api_architecture_refresh(self, query):
        """POST /api/architecture/refresh?project=<name>

        受理触发生成（起后台线程，MUST NOT 在 HTTP 线程内同步等待）。
        受理 → 200 {ok, state: "generating"}；单飞冲突 → 409；状态写盘
        失败 → 500。
        """
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        proot = Path(project["path"])
        accepted, conflict, error = self._architecture_manager().refresh(
            proot, project["name"], logger=logger
        )
        if accepted:
            self._json({"ok": True, "state": "generating"})
            return
        self._error(409 if conflict else 500, error or "受理失败")

    def _api_architecture_diagram(self, query):
        """GET /api/architecture/diagram?project=<name>

        下发 diagram.html（Content-Type text/html）。未生成/非 ready →
        结构化错误（404 + 稳定 code ``architecture_not_generated``，前端
        控制流按 code 分支，不渲染 iframe）。
        """
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        proot = Path(project["path"])
        diagram_path = proot / ARCHITECTURE_DIR / DIAGRAM_FILENAME
        # code-review item 277eb5753256：diagram.html 由生成 run 原地写出（非
        # tmp+rename），落盘是生成侧提示词驱动、代码侧无法原子化，读侧收敛为
        # 「复核 state 仍为 ready 再下发」。claude 只在单飞锁持有期内写文件，
        # 而 refresh 持锁先落 generating 再起生成线程，故「读时 state 仍
        # ready」即覆写未在进行中（任何覆写必以 generating 落盘为先导，先于
        # 本复核前可见）；复核失败与首查同形（同 code，前端控制流不受影响）。
        # 产物完整性由本复核与 _send_file 的短窗口二次读取共同保证——_send_file
        # 实际读取与复核间隔极短（须在该间隙内受理刷新且覆写恰好落在其
        # stat/read 之间），残留窗口可忽略；缺失/不可读同样交 _send_file 按
        # 既有 404 形态处理。（曾有的 read_bytes 预读块读取结果被丢弃、对响应
        # 与控制流均无效果，已删——code-review item 34d118b04dcd。）
        if self._architecture_manager().status(proot).get("state") != "ready":
            self._json(
                {"error": "架构图尚未生成", "code": "architecture_not_generated"},
                404,
            )
            return
        # code-review item 9e7b4eb16804：diagram.html 由 claude 生成（floorplan
        # 导出为单文件、设计上内联全部 JS）、同源自直发/iframe 无 sandbox 即
        # 执行，得以携 dashboard 源调用各未鉴权管理 API。CSP ``sandbox
        # allow-scripts`` 使文档以不透明源运行：内联脚本照常渲染图（不依赖
        # 同源凭据），而 fetch/XHR/表单等同源管理 API 调用被浏览器隔离阻断；
        # 浏览器直接打开与 iframe 嵌入同样受控。
        self._send_file(
            diagram_path,
            "text/html; charset=utf-8",
            extra_headers=[
                ("Content-Security-Policy", "sandbox allow-scripts"),
            ],
        )
