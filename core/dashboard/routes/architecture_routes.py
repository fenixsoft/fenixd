"""architecture_routes.py — 项目架构图 (add-project-architecture-tab) routes。

承载 3 个端点：
- GET  /api/architecture/status  （query project）→ 生成状态（四态机）
- POST /api/architecture/refresh （query project）→ 受理触发生成（后台线程）
- GET  /api/architecture/diagram （query project）→ 下发 diagram.html（text/html）

端点 handler 走既有 mixin 形态（self._json / self._error），project 均从
query string 解析，不消费请求体（对齐 regression_routes POST 契约；残留
body 字节由派发层 _drain_remaining_request_body 排空）。

生成机制（add-architecture-two-stage-generation，design D1/D3）：POST 只
受理——起 daemon 守护线程跑**两段式** headless claude 管线，磁盘为唯一
交接面：阶段1 探索 run（小 prompt，只读取证写
``.fenix/architecture/evidence.md``，marker ``ARCHIFY_EVIDENCE_DONE``）→
阶段2 出图 run（SKILL.md 与 evidence 均以包根绝对路径引用、不内嵌全文，
候选 JSON 分段小步写，marker ``ARCHIFY_DONE``）→ 既有产物权威判定链。
evidence.md 头部盖 repo HEAD 指纹，refresh 受理时 HEAD 一致则跳过阶段1
（重试只付出图成本），HEAD 变化自动重探索。两段 prompt 均落在「小上下文
× 短输出」安全区（bigmodel 网关对该形态之外的大请求存在静默丢弃），
MUST NOT 在 HTTP 线程内同步等待。前端 generating 期间 3s 轮询 status。

产物与状态存储（design D2）：项目根 ``.fenix/architecture/{diagram.html,
evidence.md, status.json}``（gitignored 运行时产物）；status.json 每次
状态迁移 tmp+rename 原子写，结构含存量六键 ``state/generated_at/
started_at/error/duration_ms/component_count`` 加可选键 ``stage``
（exploring/authoring/终态 null）。dashboard 进程内模块级
``ArchitectureManager`` 持 per-project 单飞锁与在飞进程句柄，为该目录的
唯一写者（单写者原则）。
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

from core.agent_env_keys import AGENT_RUN_BANNED_ENV_KEYS

# ── 模块级 logger（code-review item 967909e7db47：refresh 先前以
# getattr(self, 'logger', None) 取值恒为 None（handler 未定义 logger
# 属性），两段式管线日志分支全静默丢失；改传模块 logger 并保持
# warning/info 单参消息形态，spawn 失败/超时击杀/判定失败等路径
# 真实留痕）──────────────────────────────────────────────────────
logger = logging.getLogger("fenixd.dashboard.routes.architecture_routes")

# ── 模块常数（不新增配置项，对齐 autodraft 先例）─────────────────────

# 分段硬超时（秒，design D3）：总预算 1800s 不变，拆为阶段1 探索 ≤720s、
# 阶段2 出图 ≤1080s；超时以进程组方式击杀（防孙进程残留），error 文案
# 区分阶段。
_EXPLORE_TIMEOUT_SECONDS = 720
_AUTHOR_TIMEOUT_SECONDS = 1080

# 击杀后排干上限（秒）：SIGKILL 进程组后直连子进程应立即退出、管道随即
# EOF；若孙进程曾重新 setsid 逃出进程组并继承 stdout/stderr 管道句柄，EOF
# 永不到来——无上限的 communicate() 会把生成线程永久卡在 _run_stage 内，
# 单飞锁不释放、该项目后续 refresh 全 409（reap_all docstring 承认的
# knowledge.py 同款已知形态，code-review item 4ac76808cb18）。超时即放弃
# 排干（对齐 reap_all 口径：管道回收交进程退出）。
_REAP_DRAIN_TIMEOUT_SECONDS = 10

# 生成完成 marker 协议（autodraft marker 范式）：阶段2 stdout 末行
# ``ARCHIFY_DONE <组件数>``。
ARCHIFY_MARKER_PREFIX = "ARCHIFY_DONE"

# 阶段1 探索 run 完成 marker（stdout 末行）：与 ``ARCHIFY_DONE`` 无前缀
# 交集（``ARCHIFY_EVIDENCE_DONE`` 不以 ``ARCHIFY_DONE`` 开头），两段判定
# 互不干扰；测试 fake 亦按该 marker 区分阶段。
EVIDENCE_MARKER_PREFIX = "ARCHIFY_EVIDENCE_DONE"

# 形态契约：核心组件数允许区间（spec「图形态契约」）。能提取组件数时越界
# 判 failed；无法提取（marker 缺失）记 component_count=null 放行（design D5）。
COMPONENT_COUNT_MIN = 8
COMPONENT_COUNT_MAX = 16

# 产物相对路径（项目根下，gitignored 运行时目录族）。
ARCHITECTURE_DIR = ".fenix/architecture"
STATUS_FILENAME = "status.json"
DIAGRAM_FILENAME = "diagram.html"
EVIDENCE_FILENAME = "evidence.md"

# evidence.md 头部 HEAD 指纹行前缀（design D2）：``evidence-head: <sha> | <ISO 时间戳>``。
EVIDENCE_HEAD_PREFIX = "evidence-head:"

# env 剔除口径（D1.11）：一次性架构图生成与 agent-run 无关，MUST NOT 注入
# agent-run 专用上下文。键集单一来源见 core/agent_env_keys.py（与
# SessionManager、core.knowledge 共用同一 frozenset）。
_BANNED_ENV_KEYS = AGENT_RUN_BANNED_ENV_KEYS


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_spawn_env() -> dict[str, str]:
    """构建 claude 子进程环境：os.environ.copy() 减 agent-run 专用键。"""
    env = os.environ.copy()
    for key in _BANNED_ENV_KEYS:
        env.pop(key, None)
    return env


def _vendored_skill_root() -> Path:
    """archify vendored 包根（design D2）：``<repo>/vendor/archify``。

    以本文件位置锚定仓库根（routes → dashboard → core → 仓库根），脱离
    daemon 进程 cwd 依赖（worktree 内跑单测同样成立）。skill 以 vendored
    形式随库分发（VENDORED.md 溯源），生成链路零联网安装、零用户环境依赖。
    """
    return Path(__file__).resolve().parents[3] / "vendor" / "archify"


def _skill_ready() -> bool:
    """vendored 包完整性检查（design D3）：SKILL.md 存在且非空。

    缺失/为空属部署损坏，由调用方判 failed（不触发任何安装动作）。
    """
    skill_md = _vendored_skill_root() / "SKILL.md"
    try:
        return skill_md.is_file() and skill_md.stat().st_size > 0
    except OSError:
        return False


_SKILL_VENDORED_MISSING_ERROR = (
    "archify skill 包缺件（vendor/archify/SKILL.md 缺失或为空），属部署损坏，"
    "请对照 vendor/archify/VENDORED.md 恢复包后重试"
)


def _evidence_path(proot: Path) -> Path:
    """阶段1 取证材料落盘绝对路径（design D1：两段唯一交接面）。"""
    return proot / ARCHITECTURE_DIR / EVIDENCE_FILENAME


def _build_explore_prompt(proot: Path, project_name: str) -> str:
    """阶段1 探索提示词（design D1）：~1KB 小 prompt——四项取证维度 +
    evidence.md 写盘绝对路径 + ARCHIFY_EVIDENCE_DONE marker 契约。

    不注入 archify SKILL.md 全文（大上下文请求在 bigmodel 网关实测静默
    丢弃，两段编排把每轮请求压回「小上下文 × 短输出」安全区）；只读分析，
    不修改项目任何文件。"""
    evidence = _evidence_path(proot).resolve()
    return f"""对当前项目（{project_name}，项目根即当前工作目录）的代码做一次只读
取证，为后续绘制运行时架构图准备材料。只读分析，MUST NOT 修改项目内任何文件。

【取证维度】把以下四项调查清楚并写成材料：
1. 核心组件：8–16 个高层抽象（模块/服务/数据层等），各配一句职责说明；
2. 主链路：一条最核心的运行链路，从入口到落点分步说明；
3. 外部依赖：第三方服务/外部存储/网关等，注明各自用途；
4. 信任边界：进程/网络/权限分界，哪些输入不可信、在哪里校验。

【产出要求】把取证材料写成自包含的 Markdown，写入绝对路径（覆盖写）：
  {evidence}
- 只写代码里可验证的事实，不引入猜测；材料里注明关键结论对应的代码位置。

【完成标记】写盘成功后，stdout 的最后一行必须输出且仅输出一个 marker：
{EVIDENCE_MARKER_PREFIX}"""


def _build_author_prompt(proot: Path, project_name: str) -> str:
    """阶段2 出图提示词（design D1/D6）：~2KB 小 prompt——SKILL.md 与
    evidence 均以绝对路径引用（先读再开工，不内嵌全文）+ 五项形态约束 +
    候选 JSON 分段小步写纪律 + ARCHIFY_DONE marker 协议。"""
    out = (proot / ARCHITECTURE_DIR / DIAGRAM_FILENAME).resolve()
    skill_root = _vendored_skill_root()
    evidence = _evidence_path(proot).resolve()
    return f"""基于已完成的架构取证材料，为项目（{project_name}，项目根即当前工作
目录）绘制一张高层**运行时架构图**。

【第一步：先读再开工】开工前必须完整阅读以下两个文件（均以绝对路径引用，
不随本提示词内嵌）：
1. archify skill 指引（vendored 随库分发，无需安装，全程无网络依赖）：
   {skill_root / "SKILL.md"}
   - 指引原文中出现的相对路径均相对包根目录 {skill_root} 解析；
   - 指引中的校验步骤用 `node bin/archify.mjs validate …` 本地执行（无网络）。
2. 取证材料（阶段1 已写盘）：
   {evidence}
   - 架构事实以该材料为准；如有关键信息缺口，允许少量定向查证补齐，
     但不要重新做全库探索。

【产物要求】
- 输出为单个自包含 HTML 文件（全部 CSS/JS 内联，不引用任何外部资源），写入绝对路径：
  {out}
- 图形形态必须同时满足以下五项约束：
  1. 只保留 8–16 个核心组件（模块/服务/数据层等高层抽象），不要穷举目录与文件；
  2. 突出且仅突出一条主要路径（主链路高亮，其余连线弱化处理）；
  3. 标出外部依赖（第三方服务/外部存储等）与信任边界；
  4. 辅助信息放进说明卡片（note card）承载，不要为承载说明而继续增加连线；
  5. 节点与说明文字全部使用中文标注。

【写盘纪律（MUST 遵守）】候选 JSON 分段小步写，禁止单次巨量 Write：
- 先写最小骨架文件（nodes/edges/notes 空数组占位），再逐段用 Edit 补全；
- 每次写盘只补一两个组件的条目，写完即落盘；
- 中间观察与草稿随时落盘到临时文件，不靠上下文携带。

【完成标记】写盘成功后，stdout 的最后一行必须输出且仅输出一个 marker：
ARCHIFY_DONE <组件数>
其中 <组件数> 为图中核心组件的实际数量（整数）。"""


def _repo_head(proot: Path) -> str | None:
    """目标项目 repo 当前 HEAD sha（design D2）：以 proot 为 cwd 执行
    ``git rev-parse HEAD``（daemon 进程 cwd 与 proot 不同，MUST NOT 用
    进程 cwd 取 HEAD）。

    detached HEAD / 非 git 项目 / 命令异常一律返回 None（读侧判不匹配，
    每次 refresh 重新探索）。"""
    try:
        rev = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(proot),
            capture_output=True,
            text=True,
            timeout=15,
        )
        if rev.returncode != 0:
            return None
        # detached HEAD（symbolic-ref 失败）按不可复用口径处理
        sym = subprocess.run(
            ["git", "symbolic-ref", "-q", "HEAD"],
            cwd=str(proot),
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if sym.returncode != 0:
        return None
    sha = (rev.stdout or "").strip()
    return sha or None


def _stamp_evidence_head(proot: Path) -> bool:
    """阶段1 成功后给 evidence.md 头部盖 HEAD 指纹（sha + UTC 时间戳，
    design D2）。已存在旧指纹头则剥离后重盖（重探索场景旧指纹已失效）。
    尽力而为：写失败返回 False，不阻断阶段2（下次 refresh 最多多付一次
    探索成本）。"""
    path = _evidence_path(proot)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    lines = text.splitlines(keepends=True)
    if lines and lines[0].startswith(EVIDENCE_HEAD_PREFIX):
        lines = lines[1:]
        while lines and not lines[0].strip():  # 旧头部留下的空行一并清掉
            lines = lines[1:]
    sha = _repo_head(proot) or "unknown"
    stamped = f"{EVIDENCE_HEAD_PREFIX} {sha} | {_utcnow_iso()}\n\n" + "".join(lines)
    # code-review item 25f170558fdc：对齐 _write_status 的 tmp+os.replace
    # 原子写纪律，避免写中途崩溃留下半截 evidence.md（单写者原则下固定
    # .tmp 后缀即可）。
    tmp = path.parent / (path.name + ".tmp")
    try:
        tmp.write_text(stamped, encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        return False
    return True


def _evidence_head_matches(proot: Path) -> bool:
    """evidence.md 是否可复用（design D2）：存在、非空、带指纹头且记录的
    HEAD sha 与当前 repo HEAD 一致。缺失/损坏（含解码失败）/无指纹头/
    取不到当前 HEAD 一律判不匹配 → 重探索。"""
    try:
        text = _evidence_path(proot).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    if not text.strip() or not text.startswith(EVIDENCE_HEAD_PREFIX):
        return False
    first = text.splitlines()[0].strip()
    sha = first[len(EVIDENCE_HEAD_PREFIX):].split("|")[0].strip()
    if not sha or sha == "unknown":
        return False
    current = _repo_head(proot)
    return current is not None and sha == current


def _evidence_ready(proot: Path) -> bool:
    """阶段1 判定链的产物侧：evidence.md 存在且非空（design D4，不信
    claude 自述）。"""
    path = _evidence_path(proot)
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


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
    """status.json 全字段形态（task 1.1）：存量六键恒在（未 applicable 为
    null），加可选键 ``stage``（两段编排运行态：exploring/authoring，终态
    与受理初态为 null——读侧容忍缺键/多键，向后兼容）。"""
    return {
        "state": state,
        "started_at": started_at,
        "generated_at": generated_at,
        "error": error,
        "duration_ms": duration_ms,
        "component_count": component_count,
        "stage": stage,
    }


def _write_status(proot: Path, payload: dict) -> None:
    """status.json 原子写（tmp + os.replace，design D2）。"""
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
    """从 stdout 尾部提取 ``ARCHIFY_DONE <组件数>``（autodraft marker 范式：
    claude 可能用代码块包裹输出，剥反引号后前缀匹配）；协议约定 marker 为
    stdout 最后一行，倒序扫描取最后一条可解析出整数的 marker 行（正文回显
    的协议说明文字不可解析，跳过不干扰判定）；缺失 → None。"""
    tail = (stdout or "")[-2000:]
    for line in reversed(tail.splitlines()):
        s = line.strip().strip("`").strip()
        if s.startswith(ARCHIFY_MARKER_PREFIX):
            try:
                return int(s[len(ARCHIFY_MARKER_PREFIX):].strip())
            except ValueError:
                continue
    return None


def _is_selfcontained_html(path: Path) -> bool:
    """自包含 HTML 特征（task 1.5）：文件起始（允许 BOM/空白）为
    ``<!DOCTYPE html`` 或 ``<html`` 前缀（大小写不敏感）。"""
    try:
        with path.open("rb") as f:
            head = f.read(512)
    except OSError:
        return False
    text = head.decode("utf-8", errors="replace").lstrip("﻿ \t\r\n").lower()
    return text.startswith("<!doctype html") or text.startswith("<html")


def _judge_artifact(
    diagram_path: Path, returncode: int, stdout: str | None, logger=None
) -> tuple[str, str | None, int | None]:
    """产物权威判定链（design D5，不信 claude 自述）。

    退出码 → 产物存在且非空 → 自包含 HTML 特征 → 组件数 ∈ [8,16]。
    返回 (state, error, component_count)；marker 缺失时组件数记 None 放行
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
        # marker 缺失 → 无法机械校验组件数，记 null 放行（design D5）
        return "ready", None, None
    if not (COMPONENT_COUNT_MIN <= count <= COMPONENT_COUNT_MAX):
        if logger is not None:
            logger.warning(
                f"架构图组件数越界（count={count}，"
                f"allowed=[{COMPONENT_COUNT_MIN}, {COMPONENT_COUNT_MAX}]）",
            )
        return (
            "failed",
            f"架构图组件数为 {count}，超出允许范围 "
            f"[{COMPONENT_COUNT_MIN}, {COMPONENT_COUNT_MAX}]（形态契约）",
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
        释放），过期快照会把刚受理的生成误合成中断——故合成前重读状态并
        二次复核在飞，仍非在飞才合成。
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
            # 为中断。单飞锁自受理起持有、终态写盘后才释放，故合成前重读
            # 一次状态并复核在飞：复核已回到在飞 → 落到下方按正常
            # generating 返回；重读已非 generating → 以新读结果为准；仍
            # generating 且仍非在飞才合成 failed（首判定已把「读到
            # generating 后生成才完成」的既有反向竞态挡在门外）。
            data = _read_status(proot) or data
            state = str(data.get("state") or "")
            if state == "generating" and not self._in_flight_alive(proot):
                synth = _status_payload(
                    "failed",
                    started_at=data.get("started_at"),
                    error="生成被中断（daemon 重启或后台线程已不存在），请重新点击「刷新架构图」",
                )
                return synth
        # 补齐存量六键 + stage（旧版残留文件可能缺键）
        full = _status_payload(state or "none")
        for key in ("started_at", "generated_at", "error", "duration_ms",
                    "component_count", "stage"):
            if key in data:
                full[key] = data.get(key)
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
        diagram.html/evidence.md，并与用户重启后重新触发的下一轮生成并发写
        同一文件（code-review item dffc01af10fa）。退出链对每个登记句柄
        killpg(SIGKILL) 整组终止（killpg 先例：core/knowledge.py
        _kill_process_group）；目标已退出属可预期竞态（ProcessLookupError/
        OSError 降级 proc.kill）。不在此排干管道/清理 _procs：SIGKILL 后
        communicate 可能被逃出进程组的孙进程无限阻塞（knowledge.py 同款已知
        形态），收尾交由仍在飞的生成线程自身 finally 完成。
        """
        with self._guard:
            procs = list(self._procs.values())
        for proc in procs:
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass

    def refresh(
        self, proot: Path, project_name: str, logger=None
    ) -> tuple[bool, bool, str | None]:
        """受理一次生成（POST refresh，design D1：只受理不同步等待）。

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
        except OSError as exc:
            lock.release()
            # code-review item 955818ba1bd9：OSError 文本可携带内部绝对路径/
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
            name=f"archify-gen-{project_name}",
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
                )
            finally:
                lock.release()
            return False, False, "架构图生成线程启动失败，请重试"
        return True, False, None

    def _write_stage(self, proot: Path, started_at: str, stage: str) -> None:
        """在飞阶段迁移落盘（state 仍 generating + stage 键）：阶段1/阶段2
        spawn 前写，前端轮询可辨当前段。尽力而为：写失败不中断生成。"""
        try:
            _write_status(
                proot,
                _status_payload("generating", started_at=started_at, stage=stage),
            )
        except OSError:
            pass

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
        """运行一段生成 run（design D1/D3）：spawn → communicate(timeout)
        → 超时进程组 SIGKILL 击杀（既有 killpg 范式）。

        返回 (ok, returncode, stdout, stderr, error)：
        - ok=True：进程已退出（returncode 可能非零，交调用方判定链处理）；
        - ok=False：spawn 失败/通信异常/超时击杀，error 为带阶段前缀的
          失败文案，调用方直接 failed 短路。
        """
        try:
            # 持登记锁完成 spawn + 登记（item 69eb4844d0b5）：登记原来在
            # Popen 返回之后才执行，两句之间（含 Popen 内部 fork/exec 释放
            # GIL 的窗口，子进程彼时已以 start_new_session 独立组存在）若
            # serve() finally 走 reap_all()，本进程组不在快照集合里、不会被
            # killpg——孤儿以 bypassPermissions 继续写 diagram.html/
            # evidence.md。临界区罩住整个 Popen 后，退出链 reap_all 在锁上
            # 排队：要么在本进程组入集合之后才快照（必然收割），要么在本
            # 进程组 spawn 之前就已快照（无可收割对象，残余竞态固有不可闭
            # 合）。communicate 的长等待必须留在锁外。spawn 失败时不入集合
            # （with 体未执行到登记行），无悬挂占位句柄可供 reap_all 误杀。
            with self._guard:
                # [fenix-ignore:002d0de5aed2] 本地无鉴权管理 API + 全权限 agent 为产品系统性固有形态（threat model item 9e7b4eb16804），收敛须在 base.py 派发层统一 Origin/Host 校验或 loopback token，不在各端点逐个修补
                proc = subprocess.Popen(
                    ["claude", "-p", prompt, "--permission-mode", "bypassPermissions"],
                    cwd=str(proot),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    # 显式 UTF-8：text=True 缺省按 locale 解码，LC_ALL=C 启动的
                    # daemon 下 claude -p 的非 ASCII 回复会 decode 失败被误判
                    # 通信失败（同 ocr_status 修复，code-review item 7ddf7e2b3ed9）
                    encoding="utf-8",
                    errors="replace",
                    env=_build_spawn_env(),
                    # 独立会话组（autodraft 同款）：超时可 killpg 整组清场，
                    # 杜绝只杀直接子进程留下的孤儿孙进程
                    start_new_session=True,
                )
                self._procs[key] = proc
        except Exception as exc:  # noqa: BLE001 — CLI 不存在等 spawn 失败
            if logger is not None:
                logger.warning(
                    f"调用 claude CLI 异常（project={project_name}，"
                    f"{stage_label}）: {type(exc).__name__}: {exc!r}",
                )
            return False, None, None, None, "调用 claude CLI 失败"
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            # 进程组击杀（autodraft 同款）：claude 派生的 bash/写文件孙进程
            # 一并终止，锁释放后无在途写者
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass
            try:
                # 短上限排干（_REAP_DRAIN_TIMEOUT_SECONDS）：超时说明有孙进程
                # 逃出进程组占着管道，放弃排干保锁释放（进程退出兜底回收）
                proc.communicate(timeout=_REAP_DRAIN_TIMEOUT_SECONDS)
            except Exception:  # noqa: BLE001 — 含 TimeoutExpired（放弃排干）
                pass
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
        except Exception as exc:  # noqa: BLE001 — communicate 其它异常
            # 兜底清场复用超时分支的序列（code-review item 7ab006a03686）：
            # 管道 OSError 等异常路径同样不得在 finally 摘除句柄并释放单飞
            # 锁后留下仍在飞的生成进程组——残留进程稍后自行写 evidence.md /
            # diagram.html 会造成「已报 failed 但产物事后出现」，并与用户
            # 重试的新生成进程并发写同一产物（正是单飞锁要防的踩踏）
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass
            try:
                # 短上限排干（_REAP_DRAIN_TIMEOUT_SECONDS）：超时说明有孙进程
                # 逃出进程组占着管道，放弃排干保锁释放（进程退出兜底回收）
                proc.communicate(timeout=_REAP_DRAIN_TIMEOUT_SECONDS)
            except Exception:  # noqa: BLE001 — 含 TimeoutExpired（放弃排干）
                pass
            if logger is not None:
                logger.warning(
                    f"claude 进程通信异常（project={project_name}，"
                    f"{stage_label}）: {type(exc).__name__}: {exc!r}",
                )
            return False, None, None, None, f"claude 进程通信失败（{stage_label}）"
        finally:
            with self._guard:
                self._procs.pop(key, None)
        return True, proc.returncode, stdout, stderr, None

    def _run_generation(
        self,
        proot: Path,
        project_name: str,
        started_at: str,
        lock: threading.Lock,
        logger=None,
    ) -> None:
        """生成线程体（两段式管线，design D1–D5）：vendored 包完整性检查
        （两段共用一次，先于阶段1）→ 阶段1 探索 run（evidence HEAD 指纹
        命中则跳过）→ 阶段1 判定（rc==0 且 evidence 非空）→ 阶段2 出图
        run → 权威判定链 → 状态落盘。锁在线程结束时释放（finally）。"""
        key = self._key(proot)
        t0 = time.monotonic()
        diagram_path = proot / ARCHITECTURE_DIR / DIAGRAM_FILENAME
        try:
            # ── 1) vendored archify 包完整性检查（design D3）─────────
            if not _skill_ready():
                self._finish(
                    proot, started_at, t0, "failed",
                    error=_SKILL_VENDORED_MISSING_ERROR,
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
                )
                return

            # ── 2) 阶段1 探索 run：evidence HEAD 命中则跳过（design D2）──
            if _evidence_head_matches(proot):
                if logger is not None:
                    logger.info(
                        f"evidence HEAD 指纹命中，跳过阶段1 探索"
                        f"（project={project_name}），只付出图成本",
                    )
            else:
                self._write_stage(proot, started_at, "exploring")
                ok, rc, _stdout, stderr, err = self._run_stage(
                    proot, project_name, key,
                    prompt=_build_explore_prompt(proot, project_name),
                    timeout=_EXPLORE_TIMEOUT_SECONDS,
                    stage_label="阶段1 探索",
                    logger=logger,
                )
                if not ok:
                    # spawn 失败/通信异常/超时：failed 短路，不 spawn 阶段2
                    self._finish(proot, started_at, t0, "failed", error=err)
                    return
                # 阶段1 判定链（design D4，不信 claude 自述）：rc==0 且
                # evidence 非空，任一不满足直接 failed 短路
                if rc != 0:
                    if logger is not None:
                        logger.warning(
                            f"架构图阶段1 探索失败（project={project_name}，"
                            f"returncode={rc}）；stderr 尾部: "
                            f"{(stderr or '')[-400:] if isinstance(stderr, str) else ''}",
                        )
                    self._finish(
                        proot, started_at, t0, "failed",
                        error=f"阶段1 探索失败（claude 非零退出 exit={rc}），"
                              f"取证材料未产出",
                    )
                    return
                if not _evidence_ready(proot):
                    self._finish(
                        proot, started_at, t0, "failed",
                        error=f"阶段1 探索失败（{ARCHITECTURE_DIR}/"
                              f"{EVIDENCE_FILENAME} 缺失或为空），取证材料未产出",
                    )
                    return
                _stamp_evidence_head(proot)

            # ── 3) 阶段2 出图 run ────────────────────────────────────
            self._write_stage(proot, started_at, "authoring")
            ok, rc, stdout, stderr, err = self._run_stage(
                proot, project_name, key,
                prompt=_build_author_prompt(proot, project_name),
                timeout=_AUTHOR_TIMEOUT_SECONDS,
                stage_label="阶段2 出图",
                logger=logger,
            )
            if not ok:
                self._finish(proot, started_at, t0, "failed", error=err)
                return

            # ── 4) 产物权威判定链（design D5，行为与改造前一致）──────
            state, error, count = _judge_artifact(diagram_path, rc, stdout, logger)
            if logger is not None and state == "failed":
                logger.warning(
                    f"架构图生成判失败（project={project_name}，"
                    f"returncode={rc}）：{error}；"
                    f"stderr 尾部: {(stderr or '')[-400:] if isinstance(stderr, str) else ''}",
                )
            self._finish(
                proot, started_at, t0, state, error=error, component_count=count
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
        except OSError:
            pass  # 终态写盘失败不逃逸线程；读侧按残留态兜底


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
        （exploring/authoring，向后兼容可选键）。项目不存在 → 404。
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

        受理触发生成（design D1：起后台线程，MUST NOT 在 HTTP 线程内同步
        等待）。受理 → 200 {ok, state: "generating"}；单飞冲突 → 409；
        状态写盘失败 → 500。
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
        state = self._architecture_manager().status(proot).get("state")
        if state != "ready":
            self._json(
                {"error": "架构图尚未生成", "code": "architecture_not_generated"},
                404,
            )
            return
        # code-review item 9e7b4eb16804：diagram.html 由 claude 生成、设计上内联
        # 全部 JS（同源自直发/iframe 无 sandbox 即执行），得以携 dashboard 源调用
        # 各未鉴权管理 API。CSP ``sandbox allow-scripts`` 使文档以不透明源运行：
        # 内联脚本照常渲染图（不依赖同源凭据），而 fetch/XHR/表单等同源管理 API
        # 调用被浏览器隔离阻断；浏览器直接打开与 iframe 嵌入同样受控。
        self._send_file(
            proot / ARCHITECTURE_DIR / DIAGRAM_FILENAME,
            "text/html; charset=utf-8",
            extra_headers=[
                ("Content-Security-Policy", "sandbox allow-scripts"),
            ],
        )
