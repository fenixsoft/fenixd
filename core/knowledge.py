"""core/knowledge.py — 项目知识真相源（add-knowledge-atlas）。

蒸馏管线核心，三块职责：

1. **确定性收尾校验** ``validate_knowledge``（非 LLM）：对 ``spec/knowledge/``
   逐条契约对账——能力页 marker 可解析、sources 指向真实的 SPEC/归档目录
   （两态：``spec/changes/<名>`` 或 ``spec/archive/<名>``，move-distill-
   trigger-to-push 3.5）、单页 150 行硬顶、index/_domain/adr 链接可解析且不
   越界、ADR 三段式与不可变性（tracked ADR 正文与 HEAD diff）、Superseded by
   指向存在条目、retired 注记行齐备。返回违规字符串列表，空列表 = 通过。

2. **派发入口** ``dispatch_distill``：SPEC 经 ``PmEngine.approve_push`` 成功
   转移 done→pushed 后单点 fail-open 调用（move-distill-trigger-to-push 1.1，
   pushed=交付确认点；归档侧挂载已迁出）。``knowledge.enabled`` 门控、蒸馏源
   目录双态存在性检查（changes/ 优先、archive/ 兜底）、fail-open（异常只记
   日志与重试台账，不影响调用方返回值）。测试环境（PYTEST_CURRENT_TEST）恒
   不派发——既有单测不得触发真实蒸馏（替身经 dispatcher 参数注入）。

3. **执行器** ``DistillManager``（进程内单例 + 跨进程 flock 单飞）：后台
   线程 spawn ``claude -p``（cwd 主树、注入 agents/knowledge-distill.md
   提示词），run 结束跑 validate_knowledge，违规回反馈修正（≤2 轮），通过后
   pathspec 限定 ``spec/knowledge/`` 自动提交；修正轮耗尽仍违规则放弃产出
   （``git restore`` + 清理未跟踪新增，不留半成品）；失败登 todo.md 重试
   台账。同 project 蒸馏事件在队列中串行，积压条目合并为一次批量 run。

4. **溯源改写器** ``rewrite_source_links_to_archive``（move-distill-trigger-
   to-push 3.1）：归档移动成功后由归档链路（CLI / dashboard 双路径）调用，
   把 ``spec/knowledge/`` 全页中该 SPEC 的 ``spec/changes/<名>`` 溯源引用
   精确改写为实际归档目录 ``spec/archive/<date-name>``（带名字右边界，防前缀
   同名误伤），改写文件并入同一 ``[fenix] archive:`` 提交——知识页链接任何
   时刻指向真实存在的路径。

写路径限定 ``spec/knowledge/`` 一个目录（design D2 爆炸半径可控）；主树直跑
（spec 元数据层非产品代码，无 merge-back）。该写面约束除提示词承载外，run
前后还对主树做 ``git status`` 越界写面对账：合法写面之外的新增改动记 WARNING
留痕、不自动回滚（主树是用户工作区，restore 会吞掉用户未提交改动）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import urllib.parse
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

from core.platform import api as pal
from core.agent_env_keys import AGENT_RUN_BANNED_ENV_KEYS as _BANNED_ENV_KEYS
# add-harness-adapter-layer 4.1：一次性 spawn 收编入口（蒸馏 run）
from core.agent_runner.harness import (
    ENV_MODE_CLEAN,
    ClaudeAdapter,
    SpawnRequest,
)
from core.agent_runner.harness.one_shot import (
    OneShotCommunicateError,
    run_one_shot,
)
# evo-distill-model-name-fallback 1.2：拒识判别 pattern **只读复用**（裸子串
# 形态常量；其 agent 车道瞬态收窄分类语义不随导入迁移——蒸馏车道仅在非零
# 退出分支对 stderr 做裸子串判别，不改该常量任何语义）。
from core.agent_runner.provider_circuit import UNRECOGNIZED_MODEL_TEXT_PATTERNS
# add-distill-run-artifacts 1.1：蒸馏批 run 产物行追加复用既有原语（O_APPEND
# 单行原子性与 \udXXX UTF-8 预清洗防御同口径），MUST NOT 手写 open("a") 文本追加。
from core.agent_runner.run_files import append_run_error, append_run_line
from core.fs_utils import flock_exclusive, flock_release
from core.knowledge_backfill import (
    _commit_todo_after_write,
    _todo_write_lock,
    append_todo_line,
    atomic_write_text,
    ledger_has_pending,
    null_logger,
    register_archive_pending,
)
# todo.md 结构正则单源（code-review item 8455037f0c1f 口径：MUST NOT 另立
# 同值副本）——台账龄期扫描复用其日期节识别。
from core.todo_format import TODO_DATE_RE
from core.timelib import now_local, parse_ts
from core.proc_utils import guard_killpg

logger = logging.getLogger("fenixd.knowledge")

# ── 路径与契约常数 ────────────────────────────────────────────────────

KNOWLEDGE_DIR = "spec/knowledge"
ARCHIVE_DIR = "spec/archive"
CHANGES_DIR = "spec/changes"
PROMPT_FILE = "knowledge-distill.md"  # 相对仓库根 agents/（7.1 归位迁移）

# 知识候选区（add-knowledge-inbox-pipeline 1.2/2.1）：交互会话投递自由格式
# 候选的目录，validate/audit 扫描显式豁免；`done/` 为折叠成功后的溯源永久
# 保留区，marker sources 对该前缀放行（file 形态，2.1）。编年账 log.md 与
# 候选区同受归档改写豁免（5.1）。
INBOX_DIRNAME = "_inbox"
INBOX_DIR_PREFIX = f"{KNOWLEDGE_DIR}/{INBOX_DIRNAME}/"
INBOX_DONE_PREFIX = f"{KNOWLEDGE_DIR}/{INBOX_DIRNAME}/done/"
LOG_FILE_REL = f"{KNOWLEDGE_DIR}/log.md"
# 积压提醒阈值（6.1）：条目数或最老滞留天数任一命中即提醒
INBOX_BACKLOG_COUNT_THRESHOLD = 10
INBOX_BACKLOG_AGE_DAYS = 7

# 单页 150 行硬顶（spec knowledge-atlas-directory「单页行数硬顶」）。
# 仅约束能力页（domains/<域>/<能力>.md）——导航层 _domain.md 与 index.md
# 豁免（validate_knowledge 里行数检查位于能力页分支内，导航页另算）
MAX_PAGE_LINES = 150

# marker 字段合法性
# 结尾锚用 \Z 而非 $：$ 会放行带尾部换行的 capability/目录名/文件名
# （与 evolution.py bd2227732d7e 确立的 \Z 纪律对齐）
_KEBAB_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\Z")
_MARKER_RE = re.compile(r"<!--\s*knowledge:(.*?)-->", re.S)
_MARKER_FIELD_RE = re.compile(r"([A-Za-z_]+)=(\S+)")

# marker origin 取值（fix-knowledge-backfill-reconstruction：prehistoric 复原段）
ORIGIN_ARCHIVE = "archive"
ORIGIN_PREHISTORIC = "prehistoric"

# 史前锚点（design D4）：sources 项形如 git:44e1443b-..2026-09-02（起始ref-..截止日期）。
# 用 git: 前缀显式分流，与归档路径项在视觉/解析上均无歧义。
_GIT_ANCHOR_RE = re.compile(r"^git:([0-9a-f]{7,40})-\.\.(\d{4}-\d{2}-\d{2})$")

# markdown 链接（image/链接同形，只关心 .md 与目录目标）
_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")

# 宽松兜底形态：捕获组不排除空白/括号，专用于识别「形如链接但目标含空格
# 或嵌套括号」的非标准产出（蒸馏由 LLM 生成，不保证 %20 转义或尖括号包裹；
# 此类目标 _LINK_RE 匹配不到，死链/越界链接会静默逃过校验，code-review
# a89f0fcb03e7）
_LINK_LOOSE_RE = re.compile(r"\[[^\]]*\]\(([^)]*)\)")

# 更新时间盖戳（index 与 _domain 通用）：标准行 `> 最后更新：YYYY-MM-DD HH:MM UTC+8`，
# 本地时区（用户定调 2026-09-30：真相源面向人类读者，用本地时区展示）。由蒸馏/回填
# 管线以动态段注入的当前本地时间盖写，时区后缀随机器动态生成；表格单元格为同格式
# 去时区后缀。行尾偏移量兼容任意时区机器（UTC+8 / UTC-5 / UTC+5:30）。
_STAMP_LINE_RE = re.compile(r"^> 最后更新：\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC[+-]\d{1,2}(?::\d{2})?$")
_STAMP_CELL_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
_INDEX_TITLE = "知识真相源"
_INDEX_TABLE_HEADER = "| 编号 | 能力域 | 简介 | 能力数量 | 更新时间 |"
_DOMAIN_TABLE_HEADER = "| 能力页 | 简介 | 更新时间 |"
# 表格列数的中文数词（校验文案用：缺 N 列表与行违规文案同形）
_COL_COUNT_WORDS = {3: "三", 4: "四", 5: "五"}


def _distill_source_dir(proot: Path, name: str) -> "Path | None":
    """蒸馏源目录双态解析（move-distill-trigger-to-push D2）。

    push 触发时代蒸馏源是 ``spec/changes/<名>``（push 时刻 SPEC 恒在
    changes/，读到的即终态内容）；pending 台账恢复重派时 SPEC 可能已被时效
    归档，兜底 ``spec/archive/<名>``。changes/ 优先、archive/ 兜底，两态均
    缺返回 None（由调用方拒绝派发/展示兜底路径）。
    """
    changes = proot / CHANGES_DIR / name
    if changes.is_dir():
        return changes
    archive = proot / ARCHIVE_DIR / name
    if archive.is_dir():
        return archive
    return None


def local_now_stamp() -> tuple:
    """当前本地时间与展示后缀（``("2026-09-30 10:33", "UTC+8")``）。

    真相源盖戳统一时间源：蒸馏动态段与回填/史前车道占位共用，保证盖戳值
    只出自管线注入、不由 LLM 自报。
    """
    now = now_local()
    total_min = round((now.utcoffset() or timedelta()).total_seconds() / 60)
    sign = "+" if total_min >= 0 else "-"
    hours, minutes = divmod(abs(total_min), 60)
    tz = f"UTC{sign}{hours}" + (f":{minutes:02d}" if minutes else "")
    return now.strftime("%Y-%m-%d %H:%M"), tz

# ADR 文件名与头部状态（add-knowledge-anchor-lint-and-prune 1.1：词汇表扩
# retired——主体已从产品退役且无取代裁定，区别于 superseded 的「被新裁定推翻」；
# 合法形态=头部 status: retired + Retired: <YYYY-MM-DD> <一句话> 注记行，
# 三段正文不可变同 superseded 纪律）
_ADR_NAME_RE = re.compile(r"^ADR-(\d{3})-.+\.md\Z")  # 结尾锚 \Z 同 _KEBAB_RE
_ADR_STATUS_RE = re.compile(r"^status:\s*(accepted|superseded|retired)\s*$", re.M)
_SUPERSEDED_BY_RE = re.compile(r"Superseded by:\s*ADR-(\d{3})")
_RETIRED_NOTE_RE = re.compile(r"^Retired:\s*\d{4}-\d{2}-\d{2}\b", re.M)
_ADR_BODY_SPLIT = "## Context"

# 提交信息前缀（spec「蒸馏收尾确定性校验与自动提交」）
COMMIT_PREFIX = "[fenix] knowledge: distill"

# 单轮蒸馏 run 硬超时（秒）：对齐架构图两段总预算 1800s 量级
RUN_TIMEOUT_SECONDS = 1800
# 校验失败后的修正轮上限（spec：最多 2 轮）
MAX_FIX_ROUNDS = 2

# _BANNED_ENV_KEYS 单一来源见 core/agent_env_keys.py（与 SessionManager、
# architecture_routes 共用同一 frozenset）；蒸馏 run 与 agent-run 无关。


def _in_pytest() -> bool:
    """是否处于 pytest 运行环境（测试隔离保险层）。

    蒸馏派发是 push（approve_push）的自动副作用，MUST NOT 在单测里 spawn
    真实 claude；替身经 dispatcher/distill 参数注入（完全绕开本守卫），本
    守卫只防「测试直接调 approve_push / dispatch_distill 未注入替身」的
    误触发。
    """
    return "PYTEST_CURRENT_TEST" in os.environ


# ── marker 解析 ──────────────────────────────────────────────────────

def _marker_body_residue(body: str) -> bool:
    """marker 体经字段正则全量消费后是否残留非空白残片（code-review
    b15a737428e1，parse_marker 截断防御第二道）：残片意味着 marker 内存在
    未被任何 ``key=value`` 覆盖的裸 token——典型为空格分隔的多 sources 项
    后半段，宁可整 marker 判非法，也不让被截断丢弃的溯源项静默逃过校验。"""
    mask = list(body)
    for fm in _MARKER_FIELD_RE.finditer(body):
        for i in range(fm.start(), fm.end()):
            mask[i] = " "
    return re.search(r"\S", "".join(mask)) is not None


def parse_marker(text: str) -> dict | None:
    """解析能力页 marker（``<!-- knowledge: capability=... rev=... ... -->``）。

    Returns:
        dict：``{"capability": str, "rev": int, "sources": list[str],
        "part": str|None, "origin": str}``——origin 缺省 ``archive``，史前
        复原页显式声明 ``origin=prehistoric``。marker 缺失/字段非法时返回
        None（由调用方报具体违规）。
    """
    m = _MARKER_RE.search(text)
    if not m:
        return None
    body = m.group(1)
    fields = dict(_MARKER_FIELD_RE.findall(body))
    capability = fields.get("capability")
    rev_raw = fields.get("rev")
    sources_raw = fields.get("sources")
    if not capability or not rev_raw or not sources_raw:
        return None
    # 截断防御（code-review b15a737428e1）：``\S+`` 捕获组在 sources 逗号后
    # 带空格时只捕到首项（``sources=a, b`` → "a,"），被丢弃的项既不进
    # validate_knowledge 的两态存在性校验也不产生格式违规——悬空溯源静默
    # 逃过守卫。两道宁报不漏防线，判 None 由调用方报「marker 字段非法」：
    # 1) sources_raw 以逗号收尾 = 该项后被空白截断（或空尾项）；
    # 2) 字段解析全量消费后仍残留非空白残片（如空格分隔的多 sources 项
    #    后半段、或不成字段形态的散落 token）。
    if sources_raw.endswith(",") or _marker_body_residue(body):
        return None
    if not _KEBAB_RE.match(capability):
        return None
    try:
        rev = int(rev_raw)
    except ValueError:
        return None
    if rev < 1:
        return None
    sources = [s for s in sources_raw.split(",") if s]
    if not sources:
        return None
    return {
        "capability": capability,
        "rev": rev,
        "sources": sources,
        "part": fields.get("part"),
        "origin": fields.get("origin", ORIGIN_ARCHIVE),
    }


# ── 确定性收尾校验 ────────────────────────────────────────────────────

def _adr_body(text: str) -> str:
    """ADR 三段正文（自 ``## Context`` 起）；无该段时退化为全文。"""
    idx = text.find(_ADR_BODY_SPLIT)
    return text[idx:] if idx >= 0 else text


def _git_show(proot: Path, rel_path: str) -> str | None:
    """读 HEAD 版本文件内容；非 git / 未跟踪 / 失败 / 非 UTF-8 → None（跳过 diff 检查）。"""
    try:
        # encoding 固化 utf-8（与 _git 同口径，code-review 0f9cddb901b2）：裸
        # text=True 走 locale 编码，编码随环境漂移。errors 固化 strict 且解码
        # 失败在此显式捕获（code-review b7f077af256b）：不可变性比对两侧解码
        # 口径须对称——工作区侧 validate_knowledge 按 strict utf-8 读取（失败
        # 即记违规并跳过该 ADR），HEAD 侧此前 errors="replace" 会在历史 blob
        # 含非 UTF-8 字节而工作区后来仅做编码修复（语义不变）时带 U+FFFD、与
        # 工作区文本必然不等，误报「三段正文被改写」。HEAD blob 非 UTF-8 时
        # 跳过该 ADR 比对并 WARNING 留痕（与工作区侧 strict 失败跳过同口径），
        # UnicodeDecodeError 在此消化、不穿透调用方中断整个 validate_knowledge。
        r = subprocess.run(
            ["git", "show", f"HEAD:{rel_path}"],
            cwd=str(proot),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    except UnicodeDecodeError as e:
        logger.warning(
            "knowledge-distill 校验跳过 %s 的 HEAD 不可变性比对：HEAD blob "
            "非 UTF-8（%s），两侧 strict 解码口径下无法逐字比对，请人工核查",
            rel_path,
            e,
        )
        return None
    if r.returncode != 0:
        return None
    return r.stdout


def _git_ref_resolvable(proot: Path, ref: str) -> bool:
    """史前锚点起始 ref 可解析（``git cat-file -e <ref>^{commit}``）。

    非 git 目录 / ref 不存在 / 超时 → False（由调用方报违规）。
    """
    try:
        # encoding 固化 utf-8 + errors="replace"（code-review 007fab39fac2，
        # 与 _git/_git_show 0f9cddb901b2 纪律同口径）：裸 text=True 走 locale
        # 编码且 errors 隐含 strict，git 输出含当前 locale 无法解码的字节时
        # 抛 UnicodeDecodeError，不在下方 except 捕获面内、会穿透
        # validate_knowledge 使整轮校验异常、蒸馏批被误登「执行异常」台账。
        # 本处只消费 returncode，stdout/stderr 内容不参与裁决，replace 即可
        # 消除解码异常面。
        r = subprocess.run(
            ["git", "cat-file", "-e", f"{ref}^{{commit}}"],
            cwd=str(proot),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


# validate_knowledge 内 git 子进程总预算（code-review 4263215a1773）：逐 ADR
# _git_show 与逐 prehistoric 锚点 _git_ref_resolvable 都在 knowledge-distill
# 持锁的 worker 线程内串行执行，git 存储挂起/钩子卡死时最坏 n×30s，同项目
# 后续蒸馏批次全部在 flock 上排队。给整段设 120s 总预算：超时后对剩余
# ADR/锚点降级跳过 git 检查，WARNING 留痕（不落入 violations——降级不是
# 产出违规，落进去会让合法产出被误打回重写）。
_VALIDATE_GIT_BUDGET_SECONDS = 120.0


def validate_knowledge(project_root) -> list:
    """确定性校验 ``spec/knowledge/``（task 2.1）。

    Returns:
        违规字符串列表（空列表 = 全部通过）。目录不存在视为未初始化
        （首个蒸馏 run 前），不视为违规。
    """
    proot = Path(project_root)
    kroot = proot / KNOWLEDGE_DIR
    violations: list = []
    # git 检查总预算（code-review 4263215a1773）：覆盖 prehistoric ref 解析与
    # ADR HEAD 比对两段，超时降级跳过、文末 WARNING 留痕
    git_deadline = time.monotonic() + _VALIDATE_GIT_BUDGET_SECONDS
    degraded_git = {"ref": 0, "diff": 0}
    if not kroot.is_dir():
        return violations

    arch_root = proot / ARCHIVE_DIR

    def _check_links(text: str, rel_dir: Path, label: str) -> None:
        """index/_domain/adr 链接可解析且不越出真相源目录。"""
        # 先剔除围栏代码块与行内代码 span（code-review 648908c58646）：两通道
        # 同口径，避免文档里代码块内的示例链接被严格通道误报为死链。
        # [fenix-ignore:6262b72ec720] 非贪婪自左配对下未配对尾围栏之后的正文
        # 不会被剔除、仍参与两通道检查（实测），所述死链漏报不成立；按建议
        # 补闭合围栏反而错移配对、把末个真实闭合围栏之后的正文整段吞掉。
        scrubbed = re.sub(r"```.*?```", "", text, flags=re.S)
        scrubbed = re.sub(r"`[^`\n]+`", "", scrubbed)

        def _check_target_exists(target: str, path_part: str) -> None:
            """越界与存在性裁决（严格/兜底两通道共用，裁决口径一致）。"""
            resolved = (rel_dir / path_part).resolve()
            try:
                resolved.relative_to(kroot.resolve())
            except ValueError:
                violations.append(f"{label}: 链接越出真相源目录: {target}")
                return
            if not resolved.exists():
                violations.append(f"{label}: 链接目标不存在: {target}")

        for m in _LINK_RE.finditer(scrubbed):
            target = m.group(1)
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            # 尖括号完整包裹（code-review item 619958a1e296，对齐兜底通道
            # cc2ca6fe60b1 的合法形态放行）：_LINK_RE 捕获组不排除尖括号，
            # [x](<file.md>) 会按含尖括号的路径做解析与存在性检查、必然误报
            # 「链接目标不存在」；严格通道同样剥离成对尖括号包裹后再解析，
            # 两通道对该合法形态裁决一致。
            # 剥离前置、``#`` 锚点切分与 %xx 解码后置（code-review
            # 41b60536fe5a，管线排序与兜底通道 450-464 行对称）：先切分会让
            # ``<https://…#sec>`` 的 ``<``/``>`` 分居切分两侧、剥括号失败；
            # 剥后不复查外链会把 [x](<https://…>) / [x](<mailto:…>) 的剥后串
            # 当仓库相对路径做存在性检查、必然误报「链接目标不存在」，含该
            # 形态合法外链的知识页被记违规、2 轮修正耗尽后被 _give_up 整批
            # 回滚（868d1925dbca 两通道裁决一致性同型），剥后命中外链前缀与
            # 兜底通道 455-457 行同款放行。
            link = target
            if len(link) >= 2 and link.startswith("<") and link.endswith(">"):
                link = link[1:-1]
                if not link:
                    continue  # <> 空包裹按纯页内锚点同口径跳过
                if link.startswith(("http://", "https://", "mailto:")):
                    continue
            path_part = link.split("#", 1)[0]
            if not path_part:
                continue  # 纯页内锚点
            # %xx 转义解码（code-review 868d1925dbca）：兜底通道格式违规文案
            # 建议「%20 转义或 <目标> 尖括号包裹」自愈，若本通道不解码就判
            # 存在性，按文案修正后的合法产出反而报「链接目标不存在」，两通
            # 道裁决自相矛盾、2 轮修正耗尽后合法产出被 _give_up 回滚。无转
            # 义时 unquote 恒等、行为不变；解码可能引入 .. /绝对路径形态，
            # 故下方越界判定作用于解码后的值（先行复核），转义形态不得绕出
            # 真相源目录。
            path_part = urllib.parse.unquote(path_part)
            # %00 解码出 NUL 字节时下方 resolve 抛 ValueError（embedded
            # null byte），该调用位于 try 之外，异常会击穿整个
            # validate_knowledge（蒸馏批被 _worker 记「执行异常」误登台账，
            # knowledge_audit / knowledge_backfill 基线采集点同步被击穿），
            # 与本函数对 UnicodeDecodeError 的显式防护同口径按格式违规记
            # 条目（code-review 375576fcef79）。
            if "\x00" in path_part:
                violations.append(
                    f"{label}: 链接目标格式非法（含 NUL 字节）: {target}"
                )
                continue
            _check_target_exists(target, path_part)

        # 非标准目标兜底（code-review a89f0fcb03e7）：_LINK_RE 捕获组排除
        # 空白与右括号，目标含空格/嵌套括号的链接整体不参与上方越界/存在性
        # 检查——死链静默通过校验落库。对「形如链接但目标含空格或括号」显式
        # 报一条格式违规（此类目标对应的文件名违反 kebab-case 契约，落库必
        # 是死链）。外链与上方口径一致不参与检查。扫描基于上方已剔除代码块
        # 与行内代码的 scrubbed，避免文档里的示例链接文本误报。
        for m in _LINK_LOOSE_RE.finditer(scrubbed):
            target = m.group(1)
            if not target or not re.search(r"[\s(]", target):
                continue  # 空目标无路径语义；合法形态已由 _LINK_RE 检查
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            # <目标> 尖括号完整包裹为合法 markdown 形态（code-review
            # cc2ca6fe60b1）：此类目标正含空格/括号才落到本兜底，豁免「格式
            # 违规」上报，但不整体放行——剥掉成对尖括号（与严格通道
            # 619958a1e296 同款剥离口径）后继续做越界与存在性检查，含空格的
            # 死链/越界目标（如 <../../x y.md>）不得借合法形态逃过校验
            # （code-review 3c03f175bff0，堵 a89f0fcb03e7 自述问题在该形态
            # 上的残留面；两类合法尖括号形态校验强度恢复对称）。
            if target.startswith("<") and target.endswith(">"):
                # 先剥括号再判外链：<https://a b.com> 剥前以 ``<`` 开头命中不了
                # 上方外链豁免，剥后命中——该形态正是上方格式违规文案建议的
                # 自愈出路，不得反被下方存在性检查误伤（868d1925dbca 两通道
                # 裁决一致性同款纪律）。
                stripped = target[1:-1]
                if stripped.startswith(("http://", "https://", "mailto:")):
                    continue
                path_part = stripped.split("#", 1)[0]
                if not path_part:
                    continue  # <> 空包裹/纯页内锚点按严格通道同口径跳过
                # 与严格通道同序：%xx 解码后判越界（转义形态不得绕出真相源
                # 目录），NUL 字节按格式违规记条目防 resolve ValueError 击穿
                # 整个 validate_knowledge（375576fcef79 同口径）。
                path_part = urllib.parse.unquote(path_part)
                if "\x00" in path_part:
                    violations.append(
                        f"{label}: 链接目标格式非法（含 NUL 字节）: {target}"
                    )
                    continue
                _check_target_exists(target, path_part)
                continue
            violations.append(
                f"{label}: 链接目标格式非法（含空格或未转义括号，须 %20 转义"
                f"或 <目标> 尖括号包裹）: {target}"
            )

    # index.md 四列 / _domain.md 三列导航表的行校验共用一处（code-review
    # 238b61831c9d）：表格契约调整（时间列格式/新增列）只改本函数，不再
    # index/_domain 双处同步。
    def _check_stamp_table(
        lines: list, header: str, kind: str, ts_col_idx: int, label: str
    ) -> list:
        """定位 ``header`` 表头并逐行校验行末更新时间列，返回违规列表。"""
        expected_cols = ts_col_idx + 1
        num = _COL_COUNT_WORDS[expected_cols]
        positions = [i for i, l in enumerate(lines) if l == header]
        if not positions:
            return [f"{label}: 缺{kind}{num}列表（表头须为 {header}）"]
        out: list = []
        # index 分组导航后同形表头有多张（每域组一张），逐表校验到各自表格结束
        for header_pos in positions:
            for row in lines[header_pos + 1:]:
                if not row.startswith("|"):
                    break  # 表格结束
                # 切列豁免单元格内转义竖线（code-review 4de27e2e7876）：裸
                # split 按竖线逐字切开会把合法的 ``\\|`` 一并切开，列数虚增或
                # 时间列下标错位，合法表格被误判更新时间违规、白烧修正轮。
                cells = [c.strip() for c in re.split(r"(?<!\\)\|", row.strip().strip("|"))]
                # 分隔行判定放行对齐冒号（code-review 73885cc17ab7）：GFM 同样
                # 合法的 `| :--- | :---: |` 对齐分隔行（LLM 蒸馏产出常见变体）
                # 首列含 ``:``，只认纯 ``-`` 会把整行误判为数据行、末列时间必然
                # 失配而报「更新时间缺失或格式非法」，修正轮难以从文案定位到
                # 分隔行形态、白烧 2 轮修正预算；冒号无数据语义，豁免性质与上
                # 方切列豁免转义竖线同款。（首列非空，防空串误判）
                if cells and cells[0] and set(cells[0]) <= {"-", ":"}:
                    continue
                if len(cells) != expected_cols or not _STAMP_CELL_RE.match(cells[ts_col_idx]):
                    out.append(
                        f"{label}: {kind}行更新时间缺失或格式非法"
                        f"（{num}列，末列 YYYY-MM-DD HH:MM）: {row}"
                    )
        return out

    # 能力页收尾两查单点化（code-review b60cd28fa2f3）：150 行硬顶与链接
    # 可解析性在 marker 缺失/字段非法两分支提前 continue 前同样执行，单轮
    # 违规清单不缺报这两类（修正反馈信息完整）。
    def _check_page_cap_and_links(text: str, page: Path, label: str) -> None:
        """150 行硬顶 + 链接可解析性（marker 违规分支亦执行）。"""
        # 150 行硬顶
        line_count = len(text.splitlines())
        if line_count > MAX_PAGE_LINES:
            violations.append(
                f"{label}: 超过 {MAX_PAGE_LINES} 行硬顶（{line_count} 行），须拆页或精简"
            )
        _check_links(text, page.parent, label)

    # ── 能力页（domains/<域>/<能力>.md，_domain.md 为导航层另行处理）──
    domains_dir = kroot / "domains"
    if domains_dir.is_dir():
        for page in sorted(domains_dir.rglob("*.md")):
            rel = page.relative_to(kroot)
            if INBOX_DIRNAME in rel.parts:
                # 候选区显式豁免（add-knowledge-inbox-pipeline 1.2）：_inbox
                # 为自由格式区，不守能力页契约，扫描范围未来变更时本守卫钉死
                # 豁免不误伤（现状 domains/ rglob 天然不含，防的是误伤）
                continue
            label = f"{KNOWLEDGE_DIR}/{rel.as_posix()}"
            try:
                text = page.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                violations.append(f"{label}: 读取失败: {e}")
                continue
            if page.name == "_domain.md":
                # 布局契约：_domain.md 须位于域目录内（domains/<域>/_domain.md），
                # 散落在 domains 根下或更深层级均不合法（code-review 86eab4ae8b64）
                if len(rel.parts) != 3:
                    violations.append(
                        f"{label}: 目录结构违规（_domain.md 须位于 domains/<域>/ 域目录内）"
                    )
                # 域目录名 kebab 合法性（code-review fb4ffba988a3）：仅含 _domain.md
                # 而暂无能力页的域目录同样须拦——文件名固定不查，只查所属域目录，
                # 否则非 kebab 域名随导航页与 index 登记先行入库，到新增能力页时
                # 才被能力页分支拦下（与该分支裁决不对称）
                if not _KEBAB_RE.match(page.parent.name):
                    violations.append(f"{label}: 域目录名非 kebab-case")
                lines = text.splitlines()
                # 更新时间盖戳：首行须为 H1 标题、盖戳行紧随其上（第 2 行），
                # 格式 `> 最后更新：YYYY-MM-DD HH:MM UTC+8`——首行 H1 校验与
                # index.md 分支对称，否则「未紧随 H1」文案声称的契约不兑现
                if (
                    len(lines) < 2
                    or not lines[0].startswith("# ")
                    or not _STAMP_LINE_RE.match(lines[1])
                ):
                    violations.append(
                        f"{label}: 缺少「最后更新」盖戳行或未紧随 H1"
                        "（应形如 > 最后更新：YYYY-MM-DD HH:MM UTC+8）"
                    )
                # 能力页表三列：表头恒定，行末列更新时间格式合法
                violations.extend(
                    _check_stamp_table(lines, _DOMAIN_TABLE_HEADER, "能力页", 2, label)
                )
                _check_links(text, page.parent, label)
                continue
            # 布局契约：能力页须为 domains/<域>/<能力>.md 三级结构（code-review
            # 86eab4ae8b64）——domains 根目录名本身恰为 kebab 合法值，仅靠 kebab
            # 检查拦不住直放 domains 根下（缺域层级）或更深嵌套的能力页
            if len(rel.parts) != 3:
                violations.append(
                    f"{label}: 目录结构违规（能力页须为 domains/<域>/<能力>.md 三级布局）"
                )
            # 域/文件名 kebab 合法性
            if not _KEBAB_RE.match(page.parent.name) or not _KEBAB_RE.match(page.stem):
                violations.append(f"{label}: 域目录名或文件名非 kebab-case")
            # marker 须位于前 5 行内（有意放宽而非「紧随 H1」：存量页 marker
            # 常在 H1 前一行或与 H1 隔空行居第 3~4 行，收紧会打回九成页面）
            head = "\n".join(text.splitlines()[:5])
            if not _MARKER_RE.search(head):
                violations.append(f"{label}: marker 缺失或未紧随 H1（须位于前 5 行内）")
                _check_page_cap_and_links(text, page, label)
                continue
            marker = parse_marker(text)
            if marker is None:
                violations.append(f"{label}: marker 字段非法（capability/rev/sources）")
                _check_page_cap_and_links(text, page, label)
                continue
            # sources 按 origin 分支校验（fix-knowledge-backfill-reconstruction；
            # move-distill-trigger-to-push 3.5 两态放宽）
            origin = marker.get("origin") or ORIGIN_ARCHIVE
            if origin == ORIGIN_ARCHIVE:
                # 两态等价（move-distill-trigger-to-push 3.5）：push 触发蒸馏页
                # 的 sources 指向 spec/changes/<名>（push 时刻 SPEC 真实位置），
                # 归档改写 pass 之后指向 spec/archive/<date-name>——两前缀均
                # 合法。目录存在性与越界复核保留（防穿透强度不降）：缺失目录
                # 与 ".." 相对段越出两根目录的照样报违规。
                for src in marker["sources"]:
                    if src.startswith(INBOX_DONE_PREFIX):
                        # 候选原文溯源（add-knowledge-inbox-pipeline 2.1）：
                        # file 形态——目录存在性检查换文件存在性；越界复核
                        # 收口在 done/ 目录内（防 ".." 相对段穿透，与下方
                        # 归档/两态分支同强度）。
                        if not (proot / src).is_file():
                            violations.append(
                                f"{label}: sources 指向不存在的文件: {src}"
                            )
                            continue
                        resolved = (proot / src).resolve()
                        try:
                            resolved.relative_to((proot / INBOX_DONE_PREFIX).resolve())
                        except ValueError:
                            violations.append(
                                f"{label}: sources 越出候选溯源目录: {src}"
                            )
                        continue
                    if not src.startswith((ARCHIVE_DIR + "/", CHANGES_DIR + "/")):
                        violations.append(
                            f"{label}: sources 非归档/SPEC 路径（须 "
                            f"{ARCHIVE_DIR}/ 或 {CHANGES_DIR}/ 前缀）: {src}"
                        )
                        continue
                    if not (proot / src).is_dir():
                        violations.append(f"{label}: sources 指向不存在的目录: {src}")
                        continue
                    # 归一化复核（code-review b349a3a0000a）：src 含 ".." 相对
                    # 段时上两道检查均通过，OS 层解析后实际指向两根目录之外的
                    # 真实目录；resolve 后复核仍在归档或 changes 目录内（与本
                    # 函数 _check_links 的越界判定及 _gate_distill 拒绝 ".."
                    # 同强度）。
                    resolved = (proot / src).resolve()
                    in_root = False
                    for root in (arch_root, proot / CHANGES_DIR):
                        try:
                            resolved.relative_to(root.resolve())
                        except ValueError:
                            continue
                        in_root = True
                        break
                    if not in_root:
                        violations.append(
                            f"{label}: sources 越出归档/SPEC 目录: {src}"
                        )
            elif origin == ORIGIN_PREHISTORIC:
                # 史前页：sources 允许 git 区间锚点（不要求归档目录存在）
                for src in marker["sources"]:
                    am = _GIT_ANCHOR_RE.match(src)
                    if not am:
                        violations.append(
                            f"{label}: prehistoric sources 锚点格式非法"
                            f"（应形如 git:<ref>-..<日期>）: {src}"
                        )
                        continue
                    if time.monotonic() >= git_deadline:
                        degraded_git["ref"] += 1  # 预算耗尽：跳过 ref 解析（降级，文末 WARNING 留痕）
                    elif not _git_ref_resolvable(proot, am.group(1)):
                        violations.append(
                            f"{label}: prehistoric 锚点起始 ref 不可解析: {src}"
                        )
            else:
                violations.append(f"{label}: origin 非法: {origin}")
            _check_page_cap_and_links(text, page, label)

    # ── index.md（总目录，可选——首跑前允许缺席）────────────────────
    index_md = kroot / "index.md"
    if index_md.is_file():
        index_label = f"{KNOWLEDGE_DIR}/index.md"
        try:
            index_text = index_md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            violations.append(f"{index_label}: 读取失败: {e}")
        else:
            _check_links(index_text, kroot, index_label)
            # 更新时间盖戳三件套：标题、盖戳行、能力域四列表（行时间格式）
            index_lines = index_text.splitlines()
            if not index_lines or index_lines[0].strip() != f"# {_INDEX_TITLE}":
                violations.append(f"{index_label}: 标题须为「{_INDEX_TITLE}」")
            if len(index_lines) < 2 or not _STAMP_LINE_RE.match(index_lines[1]):
                violations.append(
                    f"{index_label}: 缺少「最后更新」盖戳行"
                    "（应形如 > 最后更新：YYYY-MM-DD HH:MM UTC+8，紧随标题）"
                )
            violations.extend(
                _check_stamp_table(index_lines, _INDEX_TABLE_HEADER, "能力域", 4, index_label)
            )

    # ── ADR（三段式 / 不可变 / supersede 链）────────────────────────
    adr_dir = kroot / "adr"
    if adr_dir.is_dir():
        seen_numbers: dict = {}
        for adr in sorted(adr_dir.glob("*.md")):
            label = f"{KNOWLEDGE_DIR}/adr/{adr.name}"
            try:
                text = adr.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                violations.append(f"{label}: 读取失败: {e}")
                continue
            # index 与 ADR-NNN 正文同口径校验（docstring 契约「index/_domain/adr
            # 链接可解析且不越界」，code-review 01488c0d6abc）：蒸馏产出的 ADR
            # 正文同样可能带死链或越出真相源的引用，不得静默过检落库。
            _check_links(text, adr.parent, label)
            if adr.name == "index.md":
                continue
            nm = _ADR_NAME_RE.match(adr.name)
            if not nm:
                violations.append(f"{label}: 文件名非 ADR-NNN-<标题>.md 形态")
                continue
            num = nm.group(1)
            if num in seen_numbers:
                violations.append(f"{label}: 编号 ADR-{num} 重复")
            seen_numbers[num] = adr.name
            status_m = _ADR_STATUS_RE.search(text.split(_ADR_BODY_SPLIT, 1)[0])
            if status_m is None:
                violations.append(f"{label}: 头部缺 status 行（accepted|superseded|retired）")
                continue
            status = status_m.group(1)
            if status == "superseded":
                sb = _SUPERSEDED_BY_RE.search(text)
                if not sb:
                    violations.append(f"{label}: superseded 条目缺 Superseded by 行")
                else:
                    target_num = sb.group(1)
                    if target_num == num or not any(adr_dir.glob(f"ADR-{target_num}-*.md")):
                        violations.append(
                            f"{label}: Superseded by 指向不存在条目: ADR-{target_num}"
                        )
            elif status == "retired":
                # add-knowledge-anchor-lint-and-prune 1.1：retired 须带日期锚定
                # 的 Retired: 注记行（同 Superseded by 先例置于头部段，三段正文
                # 不可变性比对不受影响）；正文改写检测走下方统一 HEAD 比对，与
                # superseded 同口径，无额外分支。
                if not _RETIRED_NOTE_RE.search(text):
                    violations.append(f"{label}: retired 条目缺 Retired: 注记行")
            # 不可变性：tracked ADR 三段正文与 HEAD 逐字比对（accepted 与
            # superseded 同样不可改写；未跟踪/非 git/读 HEAD 失败跳过）
            rel_posix = (Path(KNOWLEDGE_DIR) / "adr" / adr.name).as_posix()
            if time.monotonic() >= git_deadline:
                degraded_git["diff"] += 1  # 预算耗尽：跳过 HEAD 比对（降级，文末 WARNING 留痕）
            else:
                head_text = _git_show(proot, rel_posix)
                if head_text is not None and _adr_body(head_text) != _adr_body(text):
                    violations.append(f"{label}: 已落盘 ADR 三段正文被改写（不可变契约）")

    if degraded_git["ref"] or degraded_git["diff"]:
        # 降级留痕：本轮校验结论未做全量 git 检查，日志显式标注降级口径
        logger.warning(
            "validate_knowledge git 检查总预算（%.0fs）耗尽，本轮结论降级："
            "%d 个 prehistoric 锚点跳过起始 ref 解析、%d 个 ADR 跳过 HEAD "
            "不可变性比对（下一轮校验补全）",
            _VALIDATE_GIT_BUDGET_SECONDS,
            degraded_git["ref"],
            degraded_git["diff"],
        )
    return violations


# ── 锚点存活检查（add-knowledge-anchor-lint-and-prune 1.2）───────────────

# 「代码锚点」段标题（能力页契约：置于 ## 规则 之后、## 溯源 之前）
_ANCHOR_HEADING_RE = re.compile(r"^##\s+代码锚点\s*$", re.M)

# 锚点段内路径 token：含 / 的仓库相对路径形态，可带 ``:符号`` 尾形态
# （取路径部分校验）或 ``:<纯数字>`` 尾形态（行号必腐，格式违规）。起始
# lookbehind 排除前导路径字符，防 URL「https://…」中段与长 token 中段被
# 误命中（design D1：精确、零误报）。
_ANCHOR_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_./-])"
    r"(?P<path>[A-Za-z0-9_][A-Za-z0-9_./-]*/[A-Za-z0-9_./-]+)"
    r"(?::(?P<suffix>[A-Za-z0-9_][A-Za-z0-9_.]*))?"
)

# 锚点纪律豁免前缀（design D1）：历史归档/候选区/第三方目录不受锚点纪律约束
_ANCHOR_SKIP_PREFIXES = ("spec/archive/", "spec/knowledge/_inbox/", "node_modules/")


def _extract_anchor_section(text: str) -> str | None:
    """取能力页「## 代码锚点」段文本（段标题行至下一 ``## `` 标题或文末）。

    段不存在返回 None（段为可选，纯契约/流程类能力允许缺省）。
    """
    m = _ANCHOR_HEADING_RE.search(text)
    if not m:
        return None
    rest = text[m.end():]
    nxt = re.search(r"^##\s", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def check_anchor_references(project_root) -> list:
    """能力页「代码锚点」段存活检查（audit 车道病灶⑥数据源）。

    只扫各能力页（``domains/`` 全层级 ``*.md``；域导航页 ``_domain.md`` 与
    候选区 ``_inbox/`` 豁免除外）「## 代码锚点」段内的路径 token：
    ``路径:符号`` 形态取路径部分校验；
    ``路径:<纯数字>`` 尾形态报格式违规（行号必腐，与悬空并列两类发现）；
    尾斜杠目录级引用指向实存目录时放行不报（evo-knowledge-audit-
    pending-consumption 1.1，与 :func:`validate_knowledge` sources 目录放行
    口径对齐）；其余仓库相对路径逐一校验盘上文件存在性。``spec/archive/``、
    ``spec/knowledge/_inbox/``、``node_modules/`` 前缀跳过（design D1）。

    枚举面与 :func:`validate_knowledge` 对齐（rglob 全层级，code-review
    17377d16d975）：错位落更深层级的页（``domains/<域>/<子>/<能力>.md``）
    已被校验器记目录结构违规，其锚点段内的悬空/行号发现同样须进体检病灶⑥
    ——两车道扫描面对同一文件的覆盖须对称。

    独立于 :func:`validate_knowledge`（design D2：不并入硬门——防一处陈旧
    锚点阻塞全树折叠校验；悬空修复需语义判断，机械自删丢信息），供 audit
    车道消费，发现进体检报告「待人工」档（evo-knowledge-audit-pending-
    consumption 2.2：「定向转写」无实现通路，措辞已收敛）。

    Returns:
        发现字符串列表（空列表 = 零悬空零违例）。domains/ 目录不存在视为
        未初始化，返回空列表。
    """
    proot = Path(project_root)
    domains_dir = proot / KNOWLEDGE_DIR / "domains"
    findings: list = []
    if not domains_dir.is_dir():
        return findings
    for page in sorted(domains_dir.rglob("*.md")):
        if page.name == "_domain.md":
            continue
        if INBOX_DIRNAME in page.relative_to(domains_dir).parts:
            # 候选区豁免（对齐 validate_knowledge 同款防御）：_inbox 为自由
            # 格式区不守能力页契约
            continue
        try:
            text = page.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # 读取失败归既有病灶（①-⑤）管辖，不在本检查重复报告
        rel_page = page.relative_to(proot).as_posix()
        section = _extract_anchor_section(text)
        if section is None:
            continue
        # 围栏块覆盖行整行豁免（code-review dfb0985a6cbe，与 _check_links /
        # knowledge_audit._scan_pages 同款非贪婪配对口径）：锚点段内以 ``` 围
        # 栏代码块形态给出的示例路径（尤其 :行号 尾形态）不构成真实引用，不
        # 豁免会被判「行号必腐/锚点悬空」纯噪音，推高体检 pending_manual 计
        # 数并可能误导转写 run 派发。行内代码 span 不剔（对齐 _scan_pages 行
        # 级口径而非 _check_links 全文剔 span 口径）：能力页锚点段的现行真实
        # 引用即以反引号包裹形态书写（目录契约能力页锚点段自证），剔除会把
        # 真实引用一并抹掉、本检查整体空转。
        fence_lines: set[int] = set()
        for fm in re.finditer(r"```.*?```", section, flags=re.S):
            for li in range(
                section.count("\n", 0, fm.start()),
                section.count("\n", 0, fm.end()) + 1,
            ):
                fence_lines.add(li)
        scrubbed = "\n".join(
            ln for i, ln in enumerate(section.splitlines()) if i not in fence_lines
        )
        seen: set = set()  # 同页同路径去重（主实现与 :符号 两行指同一文件只报一条）
        for m in _ANCHOR_TOKEN_RE.finditer(scrubbed):
            path = m.group("path")
            suffix = m.group("suffix")
            # 豁免前置（code-review c0d9f6725337）：跳过前缀判定先于行号形态
            # 分支——spec/archive/ 等豁免目录内容冻结（design D1），其行号形态
            # token 不构成可处置发现，后置会给体检报告制造「行号必腐」噪音
            # 条目，与 docstring 声明的豁免语义矛盾。
            if path.startswith(_ANCHOR_SKIP_PREFIXES):
                continue
            if suffix is not None and suffix.isdigit():
                msg = (
                    f"{rel_page}: 锚点行号形态（行号必腐，改文件级路径+符号）:"
                    f" {path}:{suffix}"
                )
            elif path.endswith("/") and (proot / path).is_dir():
                # 目录级引用放行（evo-knowledge-audit-pending-consumption 1.1，
                # design D1）：能力页「代码锚点」段合法使用尾斜杠目录级引用
                # （如 ``core/platform/``），token 以 / 结尾且 (proot/path)
                # 实存目录时不算悬空——与 validate_knowledge 对 sources 的
                # is_dir 放行口径对齐（本文件 :647 附近）。放行收窄在判定
                # 分支：文件 token 判定与行号违例判定不变；目录形态 token
                # 指向不存在路径仍走下方悬空报（不漏报「引用了不存在的
                # 目录」）。
                continue
            elif not (proot / path).is_file():
                msg = f"{rel_page}: 锚点悬空: {path}"
            else:
                continue
            if msg not in seen:
                seen.add(msg)
                findings.append(msg)
    return findings


# ── 溯源改写器（move-distill-trigger-to-push 3.1）────────────────────

# 名字字符集与 archive_commit._SAFE_PATH_RE 同口径（SPEC 名/归档目录名的
# 合法字符集）；改写匹配在其上加名字右边界（见 rewrite_source_links_to_
# archive 的正则组装）。
_SOURCE_NAME_CLS = r"[A-Za-z0-9._-]"


def _fenix_file_lock_fh(proot: Path, filename: str):
    """取 ``.fenix/<filename>`` 锁文件上已 flock 的句柄（阻塞等待，薄工厂）。

    本模块全部知识车道锁（溯源改写 / 蒸馏串行 / 编年账 / pending 台账 /
    催办状态 / 蒸馏单飞）共用同一锁实现，对齐 knowledge_audit._file_write_lock
    口径（os.open + fdopen 自持 fd 管理锁生命周期）：锁文件自身无内容语义；
    各锁的竞态背景说明留在调用侧包装函数的 docstring。句柄形态供
    ``DistillManager._acquire_file_lock`` 这类「持锁窗口由调用方 try/finally
    显式收口」的调用点复用，加锁 / 释放 / 异常收尾单源，消除双实现漂移面
    （code-review e651c35d75fb）。
    """

    lock_dir = Path(proot) / ".fenix"
    lock_dir.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_dir / filename, os.O_RDWR | os.O_CREAT, 0o644)
    fh = os.fdopen(fd, "r+")  # noqa: SIM115 — 生命周期随调用方/上层 with
    try:
        flock_exclusive(fh.fileno())
    except BaseException:
        # flock 失败（EINTR 信号处理器抛出/文件系统不支持等）必须先关句柄
        # 再抛，否则常驻进程每次失败泄漏一个 fd（code-review 6302dcf20837）
        fh.close()
        raise
    return fh


@contextmanager
def _fenix_file_lock(proot: Path, filename: str):
    """``.fenix/<filename>`` 锁文件上的进程间互斥（flock）上下文（持锁 yield）。

    薄包装：加锁 / 释放 / 异常收尾全部复用 _fenix_file_lock_fh 单源实现
    （释放顺序 flock_release → close，flock 失败即关句柄不泄漏 fd）。
    """

    fh = _fenix_file_lock_fh(proot, filename)
    try:
        yield
    finally:
        try:
            flock_release(fh.fileno())
        finally:
            fh.close()


@contextmanager
def _source_rewrite_lock(proot: Path):
    """溯源改写逐页读改写窗口的进程间互斥（flock，``.fenix/knowledge-rewrite.lock``）。

    同 _pending_ledger_lock 口径（code-review c6002c057367）：tmp+os.replace
    只保证单次写不撕裂，不保证「读全文→sub→原子回写」的读改写原子性——
    本 pass 被 daemon 自动归档与 dashboard --serve 归档（spec_archive 壳层）
    两进程双路径调用，无锁时并发归档两个同页引用的 SPEC，后写者以改写前
    读到的旧文本整文回写，覆盖先写者刚落的 ``spec/archive/`` 改写（残留指
    向已消失 ``spec/changes/<名>`` 的死链）。持锁串行 + 锁内重读盘上最新
    文本，两轮改写叠加不丢。锁文件与 knowledge-log.lock 同目录不同文件、
    互不阻塞（改写窗口毫秒级，不值得与编年账追加互排队）。
    """

    with _fenix_file_lock(proot, "knowledge-rewrite.lock"):
        yield


@contextmanager
def _knowledge_distill_lock(proot: Path):
    """知识页写段与蒸馏批串行的进程间互斥（flock，``.fenix/knowledge-distill.lock``）。

    与 ``DistillManager._acquire_file_lock`` 同一锁文件：蒸馏 run 在批内
    flock 长期持有期间，claude 以自身陈旧视图整页重写知识页——其他知识页
    写段（归档溯源改写等）在本锁内执行即与其串行，防「一方基于读时快照的
    整页回写覆盖另一方刚写入的页面内容」（溯源改写被回退死链复活、或蒸馏
    产出被吞），与 run_audit 机械段/语义转写段/disputed 注记段的取蒸馏锁
    纪律同口径（code-review c47e5407501c）。阻塞等待语义与
    _acquire_file_lock 一致。注意 flock 跨 fd 不重入：已持有
    knowledge-distill.lock 的上下文（蒸馏批内部）MUST NOT 再进入本锁，
    同线程二次取锁自锁死；归档链路（CLI / dashboard）现状均在蒸馏锁外调用。
    """

    with _fenix_file_lock(proot, "knowledge-distill.lock"):
        yield


def rewrite_source_links_to_archive(project_root, spec_name: str, archive_dir_name: str) -> list:
    """归档溯源改写 pass：知识页中该 SPEC 的 changes/ 引用批量改到归档路径。

    归档移动成功后（单点、双路径共用本函数，禁复制粘贴实现）调用：扫描
    ``spec/knowledge/`` 全页（含 index/_domain/能力页/ADR/README），把
    ``spec/changes/<spec_name>`` 精确替换为 ``spec/archive/<archive_dir_name>``
    ——sources 行与正文溯源行（现行全角括号纯文本形态）均为纯文本命中，
    无须感知结构。

    匹配 MUST 带名字右边界：命中 ``spec/changes/<spec_name>`` 后随非名字
    字符（``[A-Za-z0-9._-]`` 之外）或串尾方算命中——防前缀同名 SPEC 误伤
    （真实在库例：``merge-back`` ↔ ``merge-back-precheck``，无边界时改写
    前者会把后者的引用串改坏）。

    Args:
        project_root: 项目根目录
        spec_name: SPEC 名（changes/ 下目录名）
        archive_dir_name: 当次实际归档目录名（``YYYY-MM-DD-<名>`` 或软删除
            ``<名>-<Unix秒>``——按实际注入，与命名方案无关）

    Returns:
        实际发生替换的文件相对路径清单（posix 形态、相对项目根），供调用方
        并入归档提交的 pathspec。无命中的知识页不改写不写盘（无 mtime 噪声）。
        命中页的读改写窗口持跨进程 flock（``_source_rewrite_lock``），并发
        归档对同一页的改写叠加不丢。整个改写 pass 外层另持蒸馏单飞锁
        （``_knowledge_distill_lock``，与 DistillManager 同一
        ``.fenix/knowledge-distill.lock``）：在飞蒸馏 run 以自身陈旧视图整页
        重写知识页，与本 pass 的读改写并发时后写者整页覆盖先写者——溯源改写
        被回退（死链复活）或蒸馏产出被吞；持蒸馏锁串行与 run_audit 写段同
        口径（code-review c47e5407501c）。取舍：归档主流程在长蒸馏批在飞时
        阻塞等待锁（flock 阻塞语义，与 _acquire_file_lock 一致；归档链路
        fail-open 语义不变，阻塞非异常），换取页内容不丢。

    Raises:
        读页/写盘等异常原样抛给调用方——fail-open（告警留痕、归档照常）的
        决策在调用方，本函数不做吞异常。中途失败（整批被某页异常中断）时
        在原异常对象上附加 ``partial`` 属性 = 抛出前已成功改写落盘的页面
        相对路径清单，异常类型与文本均不变——fail-open 调用方须把该清单
        并入归档提交的 extra_paths（改写与移动原子落库），否则已落盘改写页
        滞留为主树散件 WIP。
    """
    proot = Path(project_root)
    kroot = proot / KNOWLEDGE_DIR
    if not kroot.is_dir():
        return []
    # 整个改写 pass 持蒸馏单飞锁（code-review c47e5407501c，见 docstring）：
    # 与在飞蒸馏 run（flock 长期持有）串行，堵「整页读改写 vs 蒸馏整页重写」
    # 的丢失更新窗口；无知识目录的 no-op 路径不取锁不排队。
    with _knowledge_distill_lock(proot):
        # 右边界： (?![A-Za-z0-9._-]) ——命中名后随名字字符即否决（前缀同名保护）；
        # 边界零宽不消费，尾随的 ``/`` ``）`` ``，`` 或串尾均放行
        pattern = re.compile(
            re.escape(f"spec/changes/{spec_name}") + rf"(?!{_SOURCE_NAME_CLS})"
        )
        replacement = f"spec/archive/{archive_dir_name}"
        rewritten: list = []
        try:
            for page in sorted(kroot.rglob("*.md")):
                page_rel = page.relative_to(kroot)
                # 编年账与候选区显式豁免（add-knowledge-inbox-pipeline 5.1）：候选
                # 原文「永久可考」要求逐字节冻结——含 ``spec/changes/<名>`` 历史形态
                # 文本的条目不改写（接受指向已消失目录的历史文本，静默改写才是真
                # 违背承诺）；log.md 同冻结。
                if page_rel.as_posix() == "log.md" or INBOX_DIRNAME in page_rel.parts:
                    continue
                try:
                    text = page.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    # 单页不可读：与 validate_knowledge 的读取防御同口径按跳过处理，
                    # 不让一个坏页阻断整批改写（调用方的 fail-open 针对整体异常）
                    continue
                if f"spec/changes/{spec_name}" not in text:
                    continue  # 快速预筛：无命中不读写盘（不取锁）
                # 逐页读改写互斥（code-review c6002c057367）：上方预筛读到的是无锁
                # 快照，并发归档可能在预筛与取锁之间已改写本页（另一 SPEC 的
                # changes/ 引用）——持锁后重读盘上最新文本再做替换回写（同
                # _pending_ledger_lock 的持锁重读-回写纪律），后写者不再以旧文本
                # 覆盖先写者刚落的 ``spec/archive/`` 改写。
                with _source_rewrite_lock(proot):
                    try:
                        text = page.read_text(encoding="utf-8")
                    except (OSError, UnicodeDecodeError):
                        # 单页不可读：与预筛读取同口径按跳过处理，不让一个坏页
                        # 阻断整批改写（调用方的 fail-open 针对整体异常）
                        continue
                    new_text = pattern.sub(lambda _m: replacement, text)
                    if new_text == text:
                        continue  # 仅前缀同名命中（右边界全否决），不改写
                    # 写盘前再查父目录仍在（并发归档/清理移除目录时 fail-open 跳过单页）
                    if not page.is_file():
                        continue
                    # 原子落盘（tmp+os.replace）：与 _write_pending_ledger 同口径，避免
                    # 写入中途 SIGKILL/掉电留下截断知识页（code-review c03e0a119818）
                    atomic_write_text(page, new_text)
                rewritten.append(page.relative_to(proot).as_posix())
        except Exception as e:
            # 中途失败（整批被某页写盘/取锁等异常中断）：异常类型与文本原样上抛
            # （「本函数不做吞异常」契约不变），仅在原异常对象上附加 ``partial``
            # 属性 = 抛出前已成功改写落盘的页面清单——调用方 fail-open 分支据此
            # 把已落盘改写页并入归档提交（extra_paths），清单不随异常整体丢弃、
            # 已改写页不滞留为主树散件 WIP（改写与移动原子落库）。
            e.partial = list(rewritten)
            raise
        return rewritten


# ── 编年账 log.md（add-knowledge-inbox-pipeline 4.1）──────────────────
# 追加式编年账：distill/fold/backfill/lint 轮收尾由 daemon 代码侧追加一行
# （MUST NOT 依赖车道 LLM 在轮内直接写——写面纪律与并发安全在代码侧收口），
# 行前缀 `## [YYYY-MM-DD HH:MM UTC+8] <操作> | <主题>`，时间随真相源人类可读
# 惯例走本地时区显式标注（2026-11-03 裁决），运行时链路仍全链 UTC 不变。
# 并发安全：追加窗口持跨进程 flock（`.fenix/knowledge-log.lock`），与 pending
# 台账锁同款纪律、不同文件互不阻塞。

LOG_HEADER = (
    "# 知识真相源编年账\n"
    "\n"
    "> 追加式编年账：蒸馏/折叠/回填/体检轮收尾由 daemon 代码侧在本文件末尾追加\n"
    "> `## [YYYY-MM-DD HH:MM <时区>] <操作> | <主题>` 行（操作 ∈ distill/fold/\n"
    "> backfill/lint），时间随真相源人类可读惯例走本地时区。unix 工具可按日期\n"
    "> 前缀 grep；历史行禁删改。\n"
)
LOG_OPS = ("distill", "fold", "backfill", "lint")
LOG_LINE_RE = re.compile(
    r"^## \[\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC[+-]\d{1,2}(?::\d{2})?\] "
    r"(distill|fold|backfill|lint) \| "
)
# 编年账就地提交的信息前缀（失败/回滚收尾路径无法搭车产出提交时，log.md
# 追加以独立小提交落库，保持真相源工作区干净——滞留的脏 log.md 会污染后续
# 批次的基线甄别）
LOG_COMMIT_PREFIX = "[fenix] knowledge: log"


def knowledge_log_path(project_root) -> Path:
    return Path(project_root) / LOG_FILE_REL


@contextmanager
def _knowledge_log_lock(proot: Path):
    """log.md 追加窗口的进程间互斥（flock，``.fenix/knowledge-log.lock``）。

    追加模式单次小写入本身近原子，但「缺失建头 + 追加」是 check-then-act
    段，且 distill 与 audit 车道可能分属 daemon / dashboard --serve 两进程，
    持锁串行保证并发追加不丢行（4.1 契约）。
    """

    with _fenix_file_lock(proot, "knowledge-log.lock"):
        yield


def _log_subject_safe(text, limit: int = 160) -> str:
    """主题清洗：压平换行、去控制字符、截断——行前缀契约要求单行可 grep。"""
    cleaned = re.sub(r"[\x00-\x1f\x7f]+", " ", str(text)).strip()
    return cleaned[:limit] or "(空)"


def append_knowledge_log(project_root, op: str, subject: str, detail: "str | None" = None) -> bool:
    """追加一行编年账（flock 进程间互斥，并发追加不丢行）；fail-open。

    Args:
        op: 操作名（distill/fold/backfill/lint，越界 ValueError——调用方
            传错操作名属代码缺陷，不静默吞）。
        subject: 主题（单行，控制字符压平截断）。
        detail: 可选明细行（同样压平为单行，附在主题行下一行）。

    Returns:
        True=已追加；False=写失败（调用方照常继续主流程，编年账缺失不阻断
        任何车道）。
    """
    if op not in LOG_OPS:
        raise ValueError(f"log 操作非法: {op}（须为 {'/'.join(LOG_OPS)}）")
    proot = Path(project_root)
    stamp, tz = local_now_stamp()
    body = f"## [{stamp} {tz}] {op} | {_log_subject_safe(subject)}\n"
    if detail:
        body += _log_subject_safe(detail, 400) + "\n"
    path = knowledge_log_path(proot)
    try:
        with _knowledge_log_lock(proot):
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_text(path, LOG_HEADER)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(body)
        return True
    except OSError as e:
        logger.warning("knowledge-log 编年账追加失败（%s）: %s", _log_subject_safe(f"{op} {subject}", 80), e)
        return False


def _commit_log_line(proot: Path, subject: str) -> None:
    """编年账追加后的就地提交（pathspec 限定 log.md 单文件，fail-open）。

    蒸馏产出提交可搭车时（fold 行在折叠提交前追加）不经本函数；失败/回滚
    收尾路径产出已回滚或未生成，只能独立小提交。提交失败时 reset 退栈并
    WARNING 留痕（滞留脏 log.md 的代价 < staged 悬置），不阻断调用方。
    """
    try:
        st = _git(proot, ["--no-optional-locks", "status", "--porcelain", "--", LOG_FILE_REL])
        if st.returncode != 0 or not st.stdout.strip():
            return  # 干净（搭车提交已带走）或 status 不可用：无事可做
        add = _git(proot, ["add", "--", LOG_FILE_REL])
        if add.returncode != 0:
            logger.warning("knowledge-log 编年账 git add 失败: %s", add.stderr.strip())
            return
        commit = _git(
            proot,
            ["commit", "-m", f"{LOG_COMMIT_PREFIX} {_log_subject_safe(subject, 80)}", "--", LOG_FILE_REL],
            timeout=60,
        )
        if commit.returncode != 0:
            _git(proot, ["reset", "--", LOG_FILE_REL])
            logger.warning(
                "knowledge-log 编年账 git commit 失败（已 reset 退栈，log.md 滞留工作区）: %s",
                commit.stderr.strip() or f"exit {commit.returncode}",
            )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("knowledge-log 编年账提交异常: %s", e)


# 公开别名（core.knowledge_audit 复用，避免 import 私有名；须置于定义之后）
commit_log_line = _commit_log_line


# ── 候选区 _inbox（add-knowledge-inbox-pipeline 1.2/2.1/3.1/6.1）────────

def inbox_entries(project_root) -> list:
    """候选区存量条目（`_inbox/` 顶层 ``*.md``，排除 README 与 ``done/``）。

    目录缺失/不可读按空表 fail-open（折叠前置段、积压检测与面板计数都不因
    目录缺席报错）。"""
    inbox = Path(project_root) / KNOWLEDGE_DIR / INBOX_DIRNAME
    if not inbox.is_dir():
        return []
    try:
        return sorted(
            p for p in inbox.iterdir()
            if p.is_file() and p.suffix == ".md" and p.name != "README.md"
        )
    except OSError as e:
        logger.warning("knowledge-inbox 候选区列举失败，按空表处理: %s", e)
        return []


def inbox_backlog(project_root, now=None) -> dict:
    """候选区积压画像（6.1 提醒检测与 6.2 面板计数共用单源）。

    Returns:
        ``{"count": 条目数, "oldest_stay_days": 最老条目滞留整天数（mtime
        起算；空区恒 0）}``。
    """
    entries = inbox_entries(project_root)
    if not entries:
        return {"count": 0, "oldest_stay_days": 0}
    now_ts = (now or now_local()).timestamp()
    oldest = None
    for p in entries:
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue  # 单条 stat 失败不拖垮画像（该条不计入最老判定）
        if oldest is None or mtime < oldest:
            oldest = mtime
    if oldest is None:
        return {"count": len(entries), "oldest_stay_days": 0}
    return {
        "count": len(entries),
        "oldest_stay_days": max(0, int((now_ts - oldest) // 86400)),
    }


def inbox_backlog_hit(project_root, now=None) -> "dict | None":
    """积压提醒阈值判定（6.1）：≥10 条或最老条目滞留 ≥7 天任一命中。"""
    info = inbox_backlog(project_root, now=now)
    if (
        info["count"] >= INBOX_BACKLOG_COUNT_THRESHOLD
        or info["oldest_stay_days"] >= INBOX_BACKLOG_AGE_DAYS
    ):
        return info
    return None


def build_inbox_fold_prompt(proot: Path, entry_name: str) -> str:
    """组装 inbox 折叠前置 run 提示词：折叠模式动态段前置 + 蒸馏模板全文。

    模板全文复用（能力页契约/铁律/盖戳纪律单源，7.1 增补的折叠段与本动态段
    同源），动态段置顶声明本轮模式，SPEC 蒸馏任务段不适用。
    """
    tpl = load_distill_prompt()
    stamp, tz = local_now_stamp()
    entry_path = (proot / KNOWLEDGE_DIR / INBOX_DIRNAME / entry_name).resolve()
    done_rel = f"{KNOWLEDGE_DIR}/{INBOX_DIRNAME}/done/{entry_name}"
    return (
        f"## 本轮模式：inbox 折叠前置段（不做 SPEC 蒸馏）\n\n"
        f"本轮是蒸馏车道的折叠前置段（piggyback）：``spec/knowledge/_inbox/``\n"
        f"存量候选逐条折叠入库。本轮**只处理下面这一条**，完成后即收工；下方\n"
        f"模板中的「合并语义（ADDED/MODIFIED/REMOVED）/ ADR 抽取 / 首跑自举 /\n"
        f"原料缺失降级」等 SPEC 蒸馏任务段对本轮不适用，不要执行。\n\n"
        f"- 待折叠条目（自由格式 markdown 候选，绝对路径）：{entry_path}\n"
        f"- 折叠成功后条目移动到（``done/`` 为溯源永久保留区）：\n"
        f"  `{done_rel}`（mkdir -p 后 mv，不改写条目内容）\n"
        f"- 当前本地时间（盖戳用）：{stamp}（时区 {tz}）\n\n"
        f"折叠要求（模板铁律全部适用，写路径仍限定 ``spec/knowledge/``）：\n\n"
        f"1. 读条目，提取其中**仍然成立的当前业务规则**，按模板能力页契约折叠\n"
        f"   进最相关的能力页（无可挂靠页则新建能力页，并同步所在域\n"
        f"   `_domain.md` 与 index 表登记）。条目是自由格式，由你折叠成合规\n"
        f"   能力页内容；条目代表最新交互结论，与既有规则冲突时按「后写覆盖\n"
        f"   前写」覆盖旧规则，旧规则从规则段消失。新建能力页必带\n"
        f"   ``## 代码锚点`` 段（主实现/单源符号/消费方/守卫测试，文件级路径\n"
        f"   禁行号，置于规则段之后、溯源段之前；无实现载体写一行\n"
        f"   「无独立实现载体」）。\n"
        f"2. 散文重写、禁止历史叙述措辞、单页 ≤ 150 行（超顶拆主从分片互链）：\n"
        f"   与 SPEC 蒸馏同纪律。\n"
        f"3. 折叠涉及的每个能力页：marker ``rev`` +1、刷新盖戳行与所在域\n"
        f"   `_domain.md`/index 表的更新时间；marker ``sources`` 追加\n"
        f"   `{done_rel}`（file 形态，机器校验对该前缀只查文件真实存在）；\n"
        f"   溯源段追加一行（纯文本形态、不加链接）：\n"
        f"   `- <日期> <条目名>（{done_rel}） — <折叠了什么>`。\n"
        f"4. 折叠完成后把条目文件移动到 ``{done_rel}``。折叠中途失败时不要\n"
        f"   移动条目，并把已改动页面恢复原样（条目滞留原地待下轮重试）。\n"
        f"5. 自查（能力页 marker 紧随 H1、sources 路径逐一真实存在、行数、\n"
        f"   链接、盖戳，同模板完成标准）通过后，输出一行\n"
        f"   ``KNOWLEDGE_DISTILL_DONE``（stdout 最后一行）。\n"
        f"\n---\n\n{tpl}"
    )


# ── 派发与执行器 ──────────────────────────────────────────────────────

def load_distill_prompt() -> str:
    """读蒸馏提示词模板（agents/knowledge-distill.md）。"""
    path = Path(__file__).resolve().parent.parent / "agents" / PROMPT_FILE
    return path.read_text(encoding="utf-8")


def build_distill_prompt(proot: Path, archived_names: list) -> str:
    """组装蒸馏 run 提示词：模板全文 + 动态段（SPEC 清单与绝对路径）。

    形参名 ``archived_names`` 保留不改（跨 dispatch/mgr/worker/测试替身的
    签名面大，move-distill-trigger-to-push D2），语义已是「蒸馏源名」：push
    触发时代指 ``spec/changes/<名>`` 下的 SPEC 名，pending 恢复重派兜底指
    归档目录名。动态段按双态探测（``_distill_source_dir``）结果给真实绝对
    路径，蒸馏 agent 据此读取输入。
    """
    tpl = load_distill_prompt()
    items = []
    for name in archived_names:
        src = _distill_source_dir(proot, name)
        # 门控放行后两态必有一处；防御兜底展示 archive 路径（两态均缺时蒸馏
        # agent 读不到输入自然失败，不虚构存在的路径）
        path = src if src is not None else proot / ARCHIVE_DIR / name
        items.append(f"- {name}（目录：{path}）")
    archive_items = "\n".join(items)
    stamp, tz = local_now_stamp()
    return (
        f"{tpl}\n\n---\n\n"
        f"## 本次任务（动态段）\n\n"
        f"项目根（当前工作目录）：{proot}\n"
        f"真相源目录：{proot / KNOWLEDGE_DIR}\n"
        f"当前本地时间：{stamp}（时区 {tz}）。index.md 与受影响域 _domain.md 的"
        f"「最后更新」盖戳行、各表更新时间列一律以此时间为准，盖戳行写为"
        f"`> 最后更新：{stamp} {tz}`\n\n"
        f"本次待蒸馏的 SPEC：\n{archive_items}\n"
    )


def _build_spawn_env() -> dict:
    env = os.environ.copy()
    for key in _BANNED_ENV_KEYS:
        env.pop(key, None)
    return env


def _default_spawn(cmd: list, cwd: str, env=None):
    """spawn claude 子进程（独立会话组，超时可 killpg 整组清场）。

    提示词经 stdin 传入（spawn 带 ``stdin=subprocess.PIPE``，配合
    :meth:`DistillManager._spawn_and_wait` 的 ``communicate(prompt, ...)``），
    同 agent_runner / adjudication_narrative 既有口径——argv 全文驻留
    /proc/<pid>/cmdline 对同机其他用户可见，且单参数受 MAX_ARG_STRLEN 约束。

    ``env``：harness（run_one_shot）按 SpawnRequest.env_mode 算好经 popen
    kwargs 传入的环境（蒸馏车道声明 ENV_MODE_CLEAN，即 os.environ 副本剔除
    agent-run 专用键，code-review item 8c9e46ed49c2）；None（测试直呼等
    未经 harness 的调用形态）回落既有 _build_spawn_env() 全量口径。
    """
    return pal.spawn_detached(
        cmd,
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env if env is not None else _build_spawn_env(),
        new_session=True,
    )


def _kill_process_group(proc: subprocess.Popen) -> None:
    # 击杀经自保护守卫（add-killpg-self-guard，resolve 型）：守卫拒绝（自身组/
    # 非正 pgid）与组已不存在同样静默——MUST NOT 用无守卫单 pid 击杀降级
    # 替代本次 killpg（pid=0 经 os.kill 折算同为调用者自身组广播）；既有
    # ESRCH 场景该降级本就 no-op（目标已亡），收口后行为不变。该禁令只
    # 约束守卫击杀本身的降级替代，不含下方超时收尾对直接子进程的
    # proc.kill()：那是对自 spawn 直子的精确击杀（killpg 得手后等价 no-op，
    # 守卫拒绝场景则是唯一保底），无 pid=0 组广播风险——同款收尾见
    # core/hook_engine.py _terminate_proc_group（code-review d516e78585b6）。
    guard_killpg(
        proc.pid, signal.SIGKILL, caller="knowledge._kill_process_group", resolve=True
    )
    try:
        proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        # SIGKILL 后 communicate 仍可能永久阻塞：蒸馏 run 派生的孙进程若重新
        # setsid 逃出进程组并继承 stdout/stderr 管道，管道不关闭——worker 线程
        # 卡死连带 knowledge-distill.lock 不释放，同项目后续批次全部滞留
        # （code-review 44d833e20470）。强杀直接子进程并弃管道，保底让
        # _run_with_lock 的 finally 能释放 flock；收尾范式与 core/
        # hook_engine.py _terminate_proc_group 统一。
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
        try:
            for stream in (proc.stdout, proc.stderr):
                if stream is not None:
                    stream.close()
        except Exception:  # noqa: BLE001
            pass
        # 尽力收割：强杀后不 wait 会在常驻 daemon 进程内残留僵尸子进程
        # （每次超时清场累积一个）；孙进程仍持管道收不回时放弃，交由
        # init 兜底回收（与 core/knowledge_backfill.py 同款实现一致）
        try:
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        pass


def _register_todo_retry(proot: Path, archived_names: list, reason: str) -> None:
    """失败登 todo.md 重试台账（给人看的队列，不进任务门禁；fail-open）。

    写入经 ``knowledge_backfill.append_todo_line``（tmp+os.replace 原子回写
    + flock 串行读改写）：此前本处裸 write_text 截断重写，与回填车道并发
    时后写者会覆盖先写者的台账行（code-review 1bb1eacf2463）。

    台账行不含时间戳（code-review 607894da6cee）：append_todo_line 以整行
    文本精确包含做幂等去重，行内嵌时间戳每次不同会使重复失败（如 claude
    CLI 缺失）每次都追加重复行、去重分支恒死；登记时刻由 todo.md 归位的
    日期节（``## YYYY-MM-DD``）承载。
    """
    names = ", ".join(archived_names)
    try:
        appended = append_todo_line(
            proot,
            f"[ ] knowledge-distill 重试：归档 {names} — {reason}",
        )
        if not appended:
            logger.info("knowledge-distill 重试台账已存在同文本条目，跳过重复登记")
    except Exception as e:  # noqa: BLE001 — fail-open：台账失败不影响主流程
        logger.warning("knowledge-distill 重试台账登记失败（todo.md 写入异常）: %s", e)


# ── 拒识判别与裸模型名派生（evo-distill-model-name-fallback 1.2）───────────

# stderr 中被拒生效模型名的候选提取形态（容忍两种已知报错排布，提取失败不
# 阻断判别——只决定「能否派生裸名重试」）：
# 1) 标签/短语后直接跟名：[claude-code:unrecognized_model] glm-5.3-flash[1M]
# 2) 先名后短语：Model "glm-5.3-flash[1M]" is not recognized / unknown model
_UNRECOGNIZED_MODEL_NAME_RES = (
    re.compile(
        r"unrecognized[_ ]model\]?\s*[:：]?\s*[\"'`]?"
        r"([^\s\"'`，,；;）)】]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"[\"'`]?([^\s\"'`，,；;）)【]+)[\"'`]?\s+"
        r"(?:is\s+)?(?:unrecognized|unrecognised|unknown|not\s+recognized)",
        re.IGNORECASE,
    ),
)

# 生效名尾部的会话档位别名后缀（``[1M]`` 等）：剥掉即裸模型名（proposal 实测
# 形态 glm-5.3-flash[1M] → 裸名 glm-5.3-flash）。
_MODEL_ALIAS_SUFFIX_RE = re.compile(r"(?:\[[^\]\[\s]+\])+\s*$")


def _spawn_model_from_config(proot: Path) -> "str | None":
    """解析蒸馏车道显式裸模型名（``knowledge.model``；fail-open 回退 None）。

    None = 配置未提供可用名（未配置/非法/空值/解析失败），spawn 回退现行为
    不传名——回退告警由 ConfigLoader.get_knowledge_model 承担（回退必告警），
    解析异常在此留痕。
    """
    try:
        from core.config import ConfigLoader

        return ConfigLoader.get_knowledge_model(ConfigLoader.resolve_config(proot))
    except Exception as e:  # noqa: BLE001 — 配置面失败不阻蒸馏派发
        logger.warning("knowledge.model 配置解析失败（回退不传显式模型名）: %s", e)
        return None


def _stderr_hits_unrecognized_model(stderr_text: str) -> bool:
    """非零退出 stderr 是否命中拒识形态（UNRECOGNIZED_MODEL_TEXT_PATTERNS
    裸子串全量匹配，只读复用；仅在非零退出分支调用——该形态行在 glm/deepseek
    链成功 run 的启动期 stderr 同样在场，对全量 stderr 恒匹配会把一切失败误
    归因拒识，非零退出前置把误报面收窄到已失败 run）。"""
    if not stderr_text:
        return False
    low = stderr_text.lower()
    return any(p.lower() in low for p in UNRECOGNIZED_MODEL_TEXT_PATTERNS)


def _extract_rejected_model(stderr_text: str) -> "str | None":
    """从拒识 stderr 提取被拒生效模型名（提取不到返回 None，调用方按
    「无法派生裸名」收口不重试）。"""
    for rx in _UNRECOGNIZED_MODEL_NAME_RES:
        m = rx.search(stderr_text or "")
        if m:
            name = m.group(1).strip("\"'`，,；;)】")
            if name:
                return name
    return None


def _bare_model_name(rejected: str) -> "str | None":
    """剥掉生效名尾部会话档位别名后缀得裸模型名；无后缀（已是裸名形态，
    MERGE-NOTES 2026-10-30：裸名也会被网关拒识）返回 None——同因重试必然
    再拒，不构成可用兜底名。"""
    bare = _MODEL_ALIAS_SUFFIX_RE.sub("", rejected or "").strip()
    return bare if bare and bare != (rejected or "").strip() else None


# ── 重试台账龄期提醒（evo-distill-model-name-fallback 2.1）────────────────

# 登记龄期阈值：todo.md 重试行所在日期节超 24 小时未重试即提醒（R3）。登记
# 时刻由行归位的日期节（## YYYY-MM-DD）承载（_register_todo_retry 既有口径），
# 按日期节本地零点起算。
RETRY_STALE_AFTER = timedelta(hours=24)
# 升级阈值：欠账超 72 小时仍未处置时，催办在同一 kind=SIGNAL 通道内由
# warning 升为 major（evo-add-distill-retry-ledger-aging 1.2；不使用
# kind=ESCALATION——后者进 pending_escalations 人工升级队列并参与处置链
# 闭环对账，面向 run 失败处置语义，台账催办入链会误耗 admin 配额）。
# 24h 首警后留足约两个整天的人工处置窗口仍挂账才升级；具名常量与
# RETRY_STALE_AFTER 同款硬编码口径，后续可调整。≥ 判界（tasks.md 3.1
# 验收口径 <72h warning、≥72h major）：天粒度日期节的整点边界宁早勿晚。
RETRY_ESCALATE_AFTER = timedelta(hours=72)
# 应发级别序（2.1 穿透判据用）：warning < major。
_RETRY_SEVERITY_ORDER = {"warning": 0, "major": 1}
# 周期扫描节拍由挂载侧（fenixd.py 主循环 300s 检查点，对齐知识维护检查点
# 同款挂载）控制，本模块不设独立线程/定时器；dashboard --serve 不接入（对齐
# recover_pending 单进程口径）。MUST NOT 仅依赖新失败发生时顺带扫描——蒸馏
# 车道长期无新失败时欠账提醒仍须照常产生（恰为本 SPEC 主张实例的场景）。

# 同日幂等去重状态文件（evo-fix-distill-retry-ledger-auto-close 2.1）：记录
# 当日已发日期与 stale 集合指纹，daemon 重启读盘恢复——同日不重发；跨日或
# 指纹变化（新增欠账行）放行。原进程内模块属性标记已退役（重启即失效，
# 11-14 四次优雅重启对应四条重复告警实测）。形态对齐 knowledge_audit_state
# 的原子写 json；测试经删除本状态文件隔离。
RETRY_REMIND_STATE_RELPATH = ".fenix/knowledge-distill-retry-state.json"

# todo.md 重试行的归档名提取（_register_todo_retry 登记形态：
# "- [ ] knowledge-distill 重试：归档 {names} — {reason}"）。
_RETRY_LINE_NAMES_RE = re.compile(
    r"^- \[ \] knowledge-distill 重试：归档 (?P<names>.+?) — "
)


def _section_midnight(now, d: date):
    """日期节登记时刻起算点：该日期的本地零点（aware；日期节仅承载天粒度，
    零点起算为保守口径）。"""
    return datetime.combine(d, datetime.min.time(), tzinfo=now.tzinfo)


def _stale_distill_retry_lines(proot: Path) -> list:
    """解析 todo.md 未勾选的知识蒸馏重试行，返回 ``[(行文本, 登记日期)]``。

    登记日期取行归位的日期节（``## YYYY-MM-DD``，结构正则单源
    core.todo_format.TODO_DATE_RE）；已勾选（``[x]``）或已移除的行不计入
    （R3「行被勾选/移除后停止」）。文件缺失/不可读/行不在任何日期节下
    fail-open 返回空表。
    """
    todo_path = Path(proot) / ".fenix" / "todo.md"
    try:
        text = todo_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    cur: "date | None" = None
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        m = TODO_DATE_RE.match(line)
        if m:
            # 日期解析走 timelib 唯一原语（add-timelib-consolidation-layer
            # 守卫：fromisoformat 禁止出现在 timelib 之外——存量违例迁出。
            # parse_ts 纯日期串语义与裸 fromisoformat 等价：非法串归 None，
            # 合法 ``YYYY-MM-DD`` 归本地零点 aware，.date() 取回同一日历日）。
            parsed = parse_ts(m.group(1))
            cur = parsed.date() if parsed is not None else None
            continue
        if cur is not None and line.startswith("- [ ]") and (
            "knowledge-distill 重试：" in line
        ):
            out.append((line, cur))
    return out


# ── 产物存在性核验与自动闭环（evo-fix-distill-retry-ledger-auto-close 1.1/1.2）──

# 产物提交主题预过滤串：提交实况为 ``[fenix] knowledge: distill <name>``
# （9d5f616b9 实测吻合；多名形态以 ", " 连接，与子串预过滤兼容）。主题漂移
# 时核验 miss，退化为现行为（仍催办），无回归风险。
_DISTILL_COMMIT_GREP = "knowledge: distill"


def _retry_line_names(line: str) -> list:
    """台账行内归档名清单（登记形态 ``归档 {names} — {reason}``，多名以
    ``, `` 连接，与产物提交主题多名形态一致）。非登记模板形（解析失败）返回
    空表——调用方保持现行为仍催办。"""
    m = _RETRY_LINE_NAMES_RE.match(line)
    if not m:
        return []
    return [s.strip() for s in m.group("names").split(",") if s.strip()]


def _subject_names_hit(subject: str, name: str) -> bool:
    """提交主题是否含该 spec 名且名两侧均为模板定界。

    名后定界（行尾或 ``,``）防前缀互含误闭合：登记 ``fix-x`` 的行不得被
    ``fix-x-2`` 的产物提交闭合（名后为 ``-`` 非定界位置）。名前定界（串首
    或空白/逗号/冒号，code-review 301e155cd36d，与
    rewrite_source_links_to_archive 的名字右边界对称）防后缀互含：登记
    ``review`` 的行不得被 ``code-review`` 的产物提交闭合（名前为 ``-``
    非定界位置）——否则仍欠账的行被不相关主题误判已落库而勾掉，欠账被
    静默吞掉，方向与「缺失名的欠账不被静默吞掉」的闭环承诺相反。
    """
    if not name:
        return False
    idx = subject.find(name)
    while idx != -1:
        left_ok = idx == 0 or subject[idx - 1] in " ,，：:"
        end = idx + len(name)
        if left_ok and (end >= len(subject) or subject[end] == ","):
            return True
        idx = subject.find(name, idx + 1)
    return False


def _distill_commit_history(proot: Path, log=None) -> "list | None":
    """项目 git 历史中的蒸馏产物提交清单 ``[(主题, 提交时刻 epoch 秒)]``。

    ``git log -i -F --grep='knowledge: distill'`` 子串预过滤后逐条携带提交
    时刻（比较粒度到秒）。git 不可用（非仓库/命令失败/超时）返回 None——
    调用方 fail-open 保持现行为仍催办，不阻塞检查点（design：记 debug 日志）。
    """
    log = log or null_logger()
    try:
        proc = _git(
            proot,
            [
                "log",
                "-i",
                "-F",
                f"--grep={_DISTILL_COMMIT_GREP}",
                "--format=%ct:%s",
            ],
        )
    except Exception as e:  # noqa: BLE001 — fail-open：核验异常保留催办
        log.debug("knowledge", f"蒸馏产物核验 git 检索异常（fail-open 仍催办）: {e}")
        return None
    if proc.returncode != 0:
        # 非 git 仓库（128）等：与现状同款行为（仍催办），debug 留痕
        log.debug(
            "knowledge",
            "蒸馏产物核验 git 检索失败（fail-open 仍催办）: "
            f"{(proc.stderr or '').strip()[:200]}",
        )
        return None
    out = []
    for raw in proc.stdout.splitlines():
        ln = raw.strip()
        if not ln:
            continue
        # %ct 为纯数字 epoch，首个 ':' 即与主题分隔（主题自身可含 ':'）
        epoch_s, _, subject = ln.partition(":")
        if not epoch_s.isdigit():
            continue
        out.append((subject, int(epoch_s)))
    return out


def _check_off_todo_line(proot: Path, line_text: str, log=None) -> bool:
    """todo.md 对应重试行「[ ]」→「[x]」原地勾选（自动闭环回写，1.2）。

    按 ``_stale_distill_retry_lines`` 所得行文本（strip 形态）精确定位（登记
    侧 append_todo_line 以整行文本精确包含幂等，行文本唯一）；读改写持
    ``_todo_write_lock``（flock）+ ``atomic_write_text`` 原子回写，与登记/
    回填车道并发安全。实际写盘后在锁外经 ``_commit_todo_after_write`` 就地
    提交（tracked 未提交改动滞留会被 WIP 重叠闸门拦截，ADR-060 同款纪律；
    未跟踪/非 git 仓库提交自动跳过）。行已勾选/移除：幂等跳过零写盘，返回
    False。任何写异常 fail-open（返回 False，保留催办），不阻塞检查点。
    """
    log = log or null_logger()
    todo_path = Path(proot) / ".fenix" / "todo.md"
    try:
        wrote = False
        with _todo_write_lock(proot):
            try:
                text = todo_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                return False
            lines = text.splitlines()
            for i, raw in enumerate(lines):
                if raw.strip() != line_text or "[ ]" not in raw:
                    continue
                # 行首形态 "- [ ] …"，首个 "[ ]" 即复选框
                lines[i] = raw.replace("[ ]", "[x]", 1)
                wrote = True
            if not wrote:
                return False  # 已勾选/已移除：幂等零写盘
            atomic_write_text(todo_path, "\n".join(lines).rstrip("\n") + "\n")
        # 提交在锁外（同 append_todo_line：git 子命令不进 flock 临界区）
        _commit_todo_after_write(proot, line_text)
        return True
    except Exception as e:  # noqa: BLE001 — fail-open：勾选失败保留催办
        log.warning("knowledge", f"蒸馏重试台账勾选回写失败（保留催办）: {e}")
        return False


def _retry_remind_state_path(proot: Path) -> Path:
    return Path(proot) / RETRY_REMIND_STATE_RELPATH


def _load_retry_remind_state(proot: Path) -> dict:
    """催办去重状态读盘。缺失/损坏 fail-open 空表——当日视为未发，重发至多
    一条，与迁移前重启语义一致。"""
    try:
        data = json.loads(_retry_remind_state_path(proot).read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        # RecursionError 非 ValueError 子类（RuntimeError 系）：手编状态文件
        # 含数千层嵌套时 json 解析递归爆栈，同样按空表 fail-open——否则异常
        # 穿透 check_retry_ledger_age 的调用点（try 之外）令龄期扫描每个
        # 300s 检查点重复失败刷屏（code-review ec2f7257ae78，与
        # _read_pending_ledger 的 b100c02039bb 手编文件防御口径对齐）。
        return {}
    return data if isinstance(data, dict) else {}


@contextmanager
def _retry_state_write_lock(proot: Path):
    """催办去重状态读改写窗口的进程间互斥（flock，
    ``.fenix/knowledge-distill-retry-state.lock``）。

    对齐 pending 台账 / knowledge_audit 状态文件同款口径：原子回写只保单次
    写不撕裂，读改写窗口串行化防 daemon 与 dashboard --serve 两进程并发时
    后写者用旧快照覆盖先写者刚落盘的键。
    """

    with _fenix_file_lock(proot, "knowledge-distill-retry-state.lock"):
        yield


def _save_retry_remind_state(
    proot: Path, today_iso: str, fingerprint: str, severity: str = "warning"
) -> None:
    """催办去重状态落盘（读改写持锁 + 原子回写；未知键保留，前向兼容）。

    ``last_severity`` 记录上次实际发射级别（evo-add-distill-retry-ledger-aging
    2.1）：升级穿透判据与「发射成功回写新级别」的账本，缺省 warning 对齐
    升级前固定 warning 的存量状态文件语义。

    OSError 原样上抛——调用方（催办成功收口处）兜底降级：写失败不阻断
    返回，下一周期重发至多一条，与迁移前重启语义一致。
    """
    with _retry_state_write_lock(proot):
        data = _load_retry_remind_state(proot)
        data["last_reminded_date"] = today_iso
        data["last_stale_fingerprint"] = fingerprint
        data["last_severity"] = severity
        atomic_write_text(
            _retry_remind_state_path(proot),
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        )


def _stale_retry_fingerprint(stale: list) -> str:
    """stale 行集合的稳定指纹（跨进程可复算）：``sha256(排序后
    ``"登记日期|行文本"`` 逐行拼接)``。集合任一变化（新增/移除欠账行）即变，
    作为「指纹变化放行」的判据。"""
    payload = "\n".join(sorted(f"{d.isoformat()}|{line}" for line, d in stale))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _severity_rises(prev, new) -> bool:
    """应发级别是否高于状态文件记录的上次实际发射级别（2.1 升级穿透判据，
    级别序 warning < major）。

    穿透仅在提升边沿成立一次（2.2）：发射成功后 last_severity 随收口回写
    为应发级别，同级重复调用返回 False——后续发射回到现行日粒度节流，
    不回弹。prev 缺失/非法（升级前存量状态文件无 ``last_severity`` 键）按
    warning 兜底——存量文件只可能出自固定 warning 的旧版本，语义等价且
    保证升级首射在该形态下同样穿透。"""
    order = _RETRY_SEVERITY_ORDER
    return order.get(new, order["warning"]) > order.get(prev, order["warning"])


def _retry_display_names(entries: list) -> list:
    """stale/闭环条目的展示名清单（``归档名（登记 日期）``；行名解析失败
    回退行首 80 字符，对齐既有口径）。"""
    out = []
    for line, d in entries:
        m = _RETRY_LINE_NAMES_RE.match(line)
        out.append(
            f"{m.group('names') if m else line[:80]}（登记 {d.isoformat()}）"
        )
    return out


def _format_retry_age(age: timedelta) -> str:
    """欠账当前龄期展示：不足 48 小时以小时计，更长以天计（登记日期节仅
    承载天粒度，零点起算的保守口径下取整展示即可，不伪装分钟级精度）。"""
    hours = int(age.total_seconds() // 3600)
    if hours < 48:
        return f"{hours} 小时"
    return f"{age.days} 天"


def _retry_aged_display_names(entries: list, now) -> list:
    """stale 条目带当前龄期的展示名清单（``归档名（登记 日期，欠账
    小时/天）``）：龄期与 _retry_display_names 的登记日期同源——同一日期节
    零点（_section_midnight）起算，保证展示不出现第二套时钟。行名解析失败
    回退行首 80 字符，对齐既有口径。"""
    out = []
    for line, d in entries:
        m = _RETRY_LINE_NAMES_RE.match(line)
        age = now - _section_midnight(now, d)
        out.append(
            f"{m.group('names') if m else line[:80]}"
            f"（登记 {d.isoformat()}，欠账 {_format_retry_age(age)}）"
        )
    return out


def check_retry_ledger_age(project_root, logger=None) -> dict:
    """蒸馏重试台账龄期扫描（R3）：登记超 24 小时未重试时每日至多一条提醒。

    超期升级（evo-add-distill-retry-ledger-aging 1.2）：欠账龄期跨过
    RETRY_ESCALATE_AFTER（72h）仍未处置时，发射级别在同一 kind=SIGNAL
    通道内升为 major（24~72h 维持 warning）；升级态信号同样携带龄期展示，
    不使用 kind=ESCALATION（pending_escalations 处置链语义不符）。

    通道：``AdminStore.append(kind=SIGNAL)``（既有先例 core/code_fix.py
    write_regression_failed_alert，不发明新通道）；同日幂等以磁盘持久状态
    文件（.fenix/knowledge-distill-retry-state.json，2.1）承载——daemon 重启
    读盘恢复，同日不重发；跨日、stale 集合指纹变化（新增欠账行）或应发
    级别提升（欠账跨过 72h 阈值的首次升级发射，穿透立即发出）放行。
    扫描由 daemon 周期维护循环（fenixd.py 主循环 300s 检查点）触发，不依赖
    新失败发生；dashboard --serve 不接入。行被勾选/移除后无 stale 条目自然
    停发。拒写（AdminStore 返回 None）不更新状态文件，下一周期重试。

    催办前先做产物存在性核验与自动闭环（1.1/1.2）：行内 spec 名在项目 git
    历史中已有产物提交（主题含 ``knowledge: distill`` 且名后为模板定界，
    提交时刻不早于该行日期节零点——行内无时刻按零点保守起算）即判定产物已
    落库：跳过催办并回写 todo.md 勾选（幂等可重入）。git 不可用或核验/
    回写异常 fail-open：保持现行为仍催办，不阻塞检查点。

    Returns:
        {"reminded": bool, "stale": [names...], "closed": [names...]}，
        幂等跳过时附 ``"suppressed": True``。
    """
    proot = Path(project_root)
    log = logger or null_logger()
    now = now_local()
    stale = [
        (line, d)
        for line, d in _stale_distill_retry_lines(proot)
        if (now - _section_midnight(now, d)) > RETRY_STALE_AFTER
    ]
    closed = []
    if stale:
        # ── 产物存在性核验与自动闭环（1.1/1.2）──────────────────────
        # stale 判定后、发催办前：行内全部归档名均有「时刻不早于登记零点」
        # 的产物提交 → 产物已落库，跳过催办并勾选台账行。多名行取全命中
        # 才闭环（部分落库时催办保留——缺失名的欠账不能被静默吞掉，方向
        # 与 fail-open 一致）。
        history = _distill_commit_history(proot, log)
        if history is not None:
            for line, d in stale:
                names_in_line = _retry_line_names(line)
                if not names_in_line:
                    continue  # 行名解析失败：保持现行为仍催办
                since_epoch = int(_section_midnight(now, d).timestamp())
                landed = all(
                    any(
                        # [fenix-ignore:e9db259869ee] 已知取舍：同日同名先成功后失败确实可误闭合，但行内嵌登记时刻戳已被幂等去重否决（code-review 607894da6cee），收紧到 stale 门槛会复活立项动机的实测误催办（9d5f616b9 41 分钟形态）——增量基线判定留待立项
                        ts >= since_epoch and _subject_names_hit(subject, n)
                        for subject, ts in history
                    )
                    for n in names_in_line
                )
                if landed and _check_off_todo_line(proot, line, log):
                    closed.append((line, d))
        if closed:
            closed_set = {line for line, _ in closed}
            stale = [e for e in stale if e[0] not in closed_set]
            closed_disp = _retry_display_names(closed)
            brief = "；".join(closed_disp[:5]) + ("…" if len(closed_disp) > 5 else "")
            log.warning(
                "knowledge",
                f"蒸馏重试台账自动闭环（产物已落库，勾选 {len(closed)} 条）：{brief}",
            )
    out: dict = {"reminded": False, "stale": [], "closed": _retry_display_names(closed)}
    if not stale:
        return out
    names = _retry_display_names(stale)
    out["stale"] = names
    # 带龄期展示形态（evo-add-distill-retry-ledger-aging 1.1）：与 names
    # 的登记日期同源（日期节零点），仅发射文案使用，out["stale"] 既有
    # 契约（归档名（登记 日期））不变。
    aged_names = _retry_aged_display_names(stale, now)
    aged_brief = "；".join(aged_names[:5]) + ("…" if len(aged_names) > 5 else "")
    today = now.date()
    fingerprint = _stale_retry_fingerprint(stale)
    # 应发级别（1.2）：聚合信号取全部欠账条目中最高龄期——任一条目跨过
    # 升级阈值即升 major，24~72h 维持 warning；同一 kind=SIGNAL 通道内
    # 升级，通道语义不变。
    severity = (
        "major"
        if max(now - _section_midnight(now, d) for _, d in stale)
        >= RETRY_ESCALATE_AFTER
        else "warning"
    )
    state = _load_retry_remind_state(proot)
    # 跳过判据（2.1）：「同日且指纹未变」扩为「同日且指纹未变且应发级别
    # 未升」——级别提升（warning → major）的首次发射穿透日粒度节流立即
    # 发出，不被「同日且指纹未变」吞掉；同级发射仍被现行节流约束（2.2，
    # 见发射成功后的 last_severity 回写）。
    if (
        state.get("last_reminded_date") == today.isoformat()
        and state.get("last_stale_fingerprint") == fingerprint
        and not _severity_rises(state.get("last_severity"), severity)
    ):
        out["suppressed"] = True
        return out
    brief = "；".join(names[:5]) + ("…" if len(names) > 5 else "")
    description = (
        f"knowledge-distill 重试台账欠账超 24 小时未重试（{len(stale)} 条）："
        f"{aged_brief}"
    )
    if severity == "major":
        description += (
            f"；欠账已超 {_format_retry_age(RETRY_ESCALATE_AFTER)} 未处置，"
            "升级为 major"
        )
    recommended = (
        "按欠账根因处置：重发蒸馏时约束知识页链接范围（链接越出知识真相源"
        "目录即违规），或人工整理归档知识页后勾销 .fenix/todo.md 对应重试行"
    )
    try:
        from core.admin_store import AdminStore, SIGNAL

        rec = AdminStore(proot, logger=None).append(
            {
                "kind": SIGNAL,
                "signal_type": "knowledge_distill_retry_stale",
                "spec": None,
                "severity": severity,
                "description": description,
                "evidence": (
                    f"todo.md={proot / '.fenix' / 'todo.md'}; "
                    f"stale_entries={aged_brief}"
                ),
                "source": "knowledge-distill",
                "recommended_action": recommended,
            }
        )
    except Exception as e:  # noqa: BLE001 — 提醒失败不阻主循环
        log.warning("knowledge", f"蒸馏重试台账龄期提醒写入失败（不阻断）: {e}")
        return out
    if rec is None:
        # 拒写（文件损坏留底保护等）：不更新状态文件，下一周期重试
        log.warning("knowledge", "蒸馏重试台账龄期提醒被拒写（未落盘），下一周期重试")
        return out
    try:
        # 发射成功回写新级别（2.1/2.2）：穿透与常规发射同一收口，回写
        # 「本次实际发射级别」——
        #   · 升级首射后 last_severity=major，同级后续发射不再满足「级别
        #     未升」豁免，回到现行日粒度节流：穿透仅在级别提升边沿触发
        #     一次，不回弹、不构成第二条节流、不放宽「至多每日一条」；
        #   · 级别回落（欠账处置后新欠账经跨日/指纹变化放行、以 warning
        #     起步）随下一次发射自然覆盖，无升级态残留泄漏；
        #   · 拒写（rec is None）不走到这里，不回写，下一周期重试穿透。
        _save_retry_remind_state(proot, today.isoformat(), fingerprint, severity)
    except OSError as e:
        # 状态落盘失败不阻断返回：下一周期重发至多一条（迁移前重启语义）
        log.warning(
            "knowledge",
            f"蒸馏催办去重状态落盘失败（下一周期或重发至多一条）: {e}",
        )
    log.warning(
        "knowledge",
        f"蒸馏重试台账欠账提醒（{len(stale)} 条超 24h 未重试）：{brief}",
    )
    out["reminded"] = True
    return out


def _git(proot: Path, args: list, timeout: int = 60):
    # encoding/errors 固化（code-review 0f9cddb901b2）：裸 text=True 走 locale
    # 编码 + strict 解码，git status -z 对工作区非 UTF-8 文件名原样输出字节时
    # 抛 UnicodeDecodeError（ValueError 而非 OSError），穿透调用方
    # except (OSError, subprocess.TimeoutExpired) 捕获口径。对齐 _default_spawn。
    return subprocess.run(
        ["git"] + args,
        cwd=str(proot),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


# 回滚前侧档备份目录名（code-review db69ec83c724）：对齐 .fenix/ 下既有
# 运行时文件命名族（knowledge-distill.lock / -pending.json / -pending.lock）
# 的 knowledge-distill 前缀，目录本身被 .gitignore 的 .fenix/* 规则忽略、
# 不入 git status（stray 审计前缀已同步收录固化写面）。
_ROLLBACK_BACKUP_DIRNAME = "knowledge-distill-rollback-backup"


def _backup_knowledge_tracked(proot: Path, paths: list) -> tuple:
    """回滚前把 tracked 修改类路径的工作区内容备份到 .fenix 侧档（fail-open）。

    基线差集甄别不了写者（code-review db69ec83c724）：produced 中 tracked
    修改类路径可能混入 run 进行中用户对快照时点干净知识文件的未提交修改，
    restore 直接还原即静默数据丢失。restore 前逐文件复制到
    ``.fenix/<_ROLLBACK_BACKUP_DIRNAME>/<批戳>/<仓库相对路径>`` 留档，被
    还原吞掉的内容可人工找回。备份是兜底而非门：单文件失败 WARNING 留痕
    继续（不阻回滚链）；tracked 删除（工作区无内容可备份）跳过。

    Returns:
        ``(备份目录 Path, 备份成功的相对路径列表)``；无任何文件成功备份时
        不建目录，首项为 None。
    """
    backup_dir = None
    backed = []
    for rel in paths:
        try:
            src = Path(proot) / rel
            if not src.is_file():
                continue
            if backup_dir is None:
                stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
                backup_dir = (
                    Path(proot) / ".fenix" / _ROLLBACK_BACKUP_DIRNAME
                    / f"{stamp}-{time.time_ns() % 1000000:06d}"
                )
            dest = backup_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            backed.append(rel)
        except OSError as e:
            logger.warning("knowledge-distill 回滚前备份失败（%s）: %s", rel, e)
    return backup_dir, backed


def _discard_output(proot: Path, before=None, exclude=None) -> bool:
    """放弃产出：restore tracked + 清理未跟踪新增（不留半成品）。

    基线感知（code-review 4d1e46fa795c）：``before`` 为本次 run 前的基线
    快照（_knowledge_baseline_snapshot，祖先折叠条目已就地展开）。仅当
    spec/knowledge/ 下当前脏路径相对基线
    确为本次 run 新增（基线中不存在）时才回滚，且回滚收敛为文件粒度
    （code-review fb19dedc8045）——只对相对基线的差集（本次 run 产出路径集）
    restore/clean，不做整目录操作：蒸馏 run 可长达数十分钟，期间用户在
    知识目录的新改动同样不落在基线内、下方交集保护甄别不到，整目录口径
    会连带吞掉它们。基线中已有同路径改动说明用户在合法写面内有未提交的
    手工策展，回滚会连带吞掉——降级为 WARNING 留痕交人工处理（与
    _audit_stray_writes「不吞用户未提交改动」同一尺度）。基线不可用
    （git 失败/非 git 仓库）时同样保守跳过。

    ``exclude``（add-knowledge-inbox-pipeline 3.1）：从两侧快照中先行剔除的
    路径集（折叠失败回滚传条目原位路径——移动到 done/ 是任务语义而非用户
    策展，原位路径在条目未被移动时恒同时出现在基线与现状两侧，不剔除会
    触发 overlap 保守跳过、折叠半成品滞留）。

    候选区豁免（code-review a4dc2d9ac5f2）：``spec/knowledge/_inbox/`` 前缀
    路径不参与 overlap 甄别与 preserved 告警——候选条目不受 gitignore 覆盖、
    以 untracked 滞留候选区是框架常态（待折叠投递 / 折叠失败滞留原地）而非
    用户手工策展，详见下方实现注释。

    Returns:
        True = 本次 run 产出路径的回滚清理已执行且残留复查确认干净；False =
        保守跳过（基线已有路径或基线不可用）或回滚未确认（restore/clean
        失败、残留复查不可用、产出路径复查仍有残留）。调用方须把 False 按
        「回滚未确认」口径落日志与台账，不得当作已清理干净。基线之外非产出
        的新增路径（如 run 进行中的用户改动）不回滚、告警留痕，不影响 True。
    """
    after = _git_status_paths(proot)
    if before is None or after is None:
        logger.warning(
            "knowledge-distill 放弃产出：工作区基线快照不可用，跳过 "
            "spec/knowledge/ 回滚（避免吞掉用户未提交改动），请人工核查"
        )
        return False
    # 目录折叠展开（code-review item 0180bdeaf91d，对齐 _commit_output
    # 4d0b4682b40a 同款处理）：git status 把无任何已跟踪文件的整棵子树折叠
    # 为单条目录项（如 spec/ 全树未跟踪时基线只含 "spec/"），原始路径快照
    # 直接做交集时折叠发生在 spec/ 祖先层的基线里看不到用户未跟踪文件——
    # overlap 判空后 git clean -fd 会把 run 前已存在的手工文件一并删除。
    # 两侧快照先归一到 knowledge 表面文件粒度再做交集判定。
    after_k = _expand_knowledge_surface(proot, after)
    baseline_k = _expand_knowledge_surface(proot, before)
    if after_k is None or baseline_k is None:
        # 枚举失败时交集不可靠（折叠条目可能藏住基线已有路径），按基线
        # 不可用口径保守跳过回滚
        logger.warning(
            "knowledge-distill 放弃产出：spec/knowledge/ 未跟踪文件枚举失败，"
            "无法可靠甄别基线交集，跳过回滚，请人工核查"
        )
        return False
    if exclude:
        after_k = after_k - set(exclude)
        baseline_k = baseline_k - set(exclude)
    # 候选区豁免（code-review a4dc2d9ac5f2）：spec/knowledge/_inbox/ 候选条目
    # 不受 gitignore 覆盖（git check-ignore 不命中），以 untracked 滞留候选区
    # 是框架设计常态（等待折叠的投递候选、折叠失败滞留原地），会同时进入
    # 基线与现状两侧快照——把它们一律视作用户手工策展会使 overlap 恒非空，
    # 主蒸馏 _give_up 需要放弃产出时整个回滚被系统性保守跳过：半成品滞留
    # 工作区、后续批次将其视为基线已有路径永不自动清理，告警还误指「疑似
    # 用户未提交的手工策展」。候选区是框架管理面而非用户策展面，从 overlap
    # 甄别剔除（与 _rollback_failed_fold 的 exclude={origin_rel} 同款口径）；
    # exclude 参数是精确路径集差而调用点（_give_up）拿不到两侧快照路径集、
    # 无法枚举精确路径，故在此按前缀统一豁免。仅豁免甄别不放宽回滚面：候选
    # 区路径不因此进入 produced 差集，run 期间新增的候选路径（如折叠移入
    # done/ 的副本）仍按本次产出照常回滚。
    overlap = sorted(
        p
        for p in after_k
        if p in baseline_k and not p.startswith(INBOX_DIR_PREFIX)
    )
    if overlap:
        logger.warning(
            "knowledge-distill 放弃产出：spec/knowledge/ 下改动含 run 前基线"
            "已有路径（疑似用户未提交的手工策展），跳过回滚以免吞掉"
            "用户改动，请人工核查: %s",
            ", ".join(overlap),
        )
        return False
    # 回滚收敛为文件粒度（code-review fb19dedc8045）：仅对相对基线的差集
    # （本次 run 产出路径集）操作，不再整目录 restore/clean。run 进行中用户
    # 在知识目录的新增文件同样不落在基线内、上方交集保护甄别不到，整目录
    # 口径会连带吞掉它们；文件粒度把破坏面压到差集路径。残余风险面如实
    # 声明（code-review db69ec83c724）：差集并没有排除 run 中途出现的改动
    # ——基线只装快照时点已脏路径，run 期间用户对快照时点干净（未列入
    # 基线）的已跟踪文件做出未提交修改同样落入差集被 restore 还原；文件
    # 粒度只收窄了基线已脏路径的保护，并不兑现「快照之后的改动一律不碰」
    # （写者归属 git 不可甄别）。故 tracked 修改类路径 restore 前先备份
    # 工作区内容到侧档并 WARNING 留痕（下方 _backup_knowledge_tracked），
    # 不静默还原。
    produced = after_k - baseline_k
    if produced:
        # tracked 改动（含删除）与 untracked 新文件须各用各的命令口径：
        # restore 的 pathspec 混入 untracked 路径会报 pathspec 未命中并整体
        # 退出非零、tracked 一并漏回滚，先用 ls-files 把产出里的 tracked
        # 路径甄别出来。
        try:
            probe = _git(
                proot,
                ["--no-optional-locks", "ls-files", "-z", "--"] + sorted(produced),
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            logger.warning(
                "knowledge-distill 放弃产出：git ls-files 甄别 tracked 路径"
                "失败（%s），无法安全拆分 tracked/untracked 回滚口径，跳过"
                "本次回滚，请人工核查",
                e,
            )
            return False
        if probe.returncode != 0:
            logger.warning(
                "knowledge-distill 放弃产出：git ls-files 退出码 %d（stderr: %s），"
                "无法安全拆分 tracked/untracked 回滚口径，跳过本次回滚，"
                "请人工核查",
                probe.returncode,
                (probe.stderr or "").strip()[-300:] or "（空）",
            )
            return False
        tracked_set = set(probe.stdout.split("\0"))
        produced_tracked = sorted(p for p in produced if p in tracked_set)
        if produced_tracked:
            # 还原前侧档备份（code-review db69ec83c724）：差集甄别不了写者，
            # 其中可能混有 run 进行中用户对快照时点干净知识文件的未提交
            # 修改，先备份工作区内容再 restore，被吞内容可人工找回
            backup_dir, backed = _backup_knowledge_tracked(
                proot, produced_tracked
            )
            if backed:
                logger.warning(
                    "knowledge-distill 放弃产出：tracked 修改类产出路径 "
                    "restore 前已备份工作区内容到 %s（其中可能混有 run "
                    "进行中用户对快照时点干净知识文件的未提交修改，"
                    "请人工核查）: %s",
                    backup_dir,
                    ", ".join(backed),
                )
            try:
                restore = _git(proot, ["restore", "--"] + produced_tracked)
                if restore.returncode != 0:
                    # code-review 37565545ea29：非零退出（index.lock 占用、
                    # 路径规格异常等）必须留痕，是否「未确认」交由下方残留
                    # 复查裁决，不在此处直接判失败
                    logger.warning(
                        "knowledge-distill git restore 退出码 %d（stderr: %s），"
                        "tracked 改动回滚结果待残留复查确认",
                        restore.returncode,
                        (restore.stderr or "").strip()[-300:] or "（空）",
                    )
            except (OSError, subprocess.TimeoutExpired) as e:
                logger.warning("knowledge-distill git restore 失败: %s", e)
        try:
            # clean 只动未跟踪文件（tracked 路径入 pathspec 无副作用）；
            # -f 足够——produced 已是文件粒度路径，无需 -d 进未跟踪目录
            # （code-review e2029f25ad5b 的目录滞留关切对文件粒度不成立：
            # 清空后滞留的空目录壳不进 git status，不构成可提交半成品）
            clean = _git(proot, ["clean", "-f", "--"] + sorted(produced))
            if clean.returncode != 0:
                logger.warning(
                    "knowledge-distill git clean 退出码 %d（stderr: %s），"
                    "未跟踪半成品清理结果待残留复查确认",
                    clean.returncode,
                    (clean.stderr or "").strip()[-300:] or "（空）",
                )
        except (OSError, subprocess.TimeoutExpired) as e:
            logger.warning("knowledge-distill git clean 失败: %s", e)
    # 残留复查（code-review e2029f25ad5b）：restore/clean 未清干净的本次产出
    # 路径滞留即告警留痕，不让「不留半成品」静默失约
    residue = _git_status_paths(proot)
    if residue is None:
        # code-review 37565545ea29：复查不可用 ≠ 无残留，显式告警并按
        # 「回滚未确认」上报，不留静默
        logger.warning(
            "knowledge-distill 放弃产出：回滚后残留复查不可用（git status 失败），"
            "spec/knowledge/ 清理结果未确认，请人工核查"
        )
        return False
    # 残留复查同口径折叠展开（code-review item 0180bdeaf91d）：折叠条目
    # （如 "spec/"）不以 KNOWLEDGE_DIR 前缀开头，原始前缀过滤会把藏在其
    # 下的残留误判为「确认干净」。
    residue_k = _expand_knowledge_surface(proot, residue)
    if residue_k is None:
        logger.warning(
            "knowledge-distill 放弃产出：回滚后残留复查枚举失败，"
            "spec/knowledge/ 清理结果未确认，请人工核查"
        )
        return False
    # 残留只按本次产出路径集口径判定：快照之后才出现的路径（如 run 进行中
    # 用户的未提交改动）不回滚也不计入残留——它们不是半成品，回滚它们正是
    # 本函数要避免的「吞用户改动」
    left = sorted(residue_k & produced)
    if left:
        logger.warning(
            "knowledge-distill 放弃产出：回滚后本次产出路径仍有残留半成品，"
            "请人工核查: %s",
            ", ".join(left),
        )
        return False
    # 候选区豁免同口径（code-review a4dc2d9ac5f2）：基线既有候选条目在回滚后
    # 原位滞留是框架常态（待折叠 / 折叠失败滞留语义），run 进行中用户经既有
    # 投递通道向候选区落候选同样是框架设计工作流，均不入「疑似 run 进行中的
    # 用户未提交改动」告警以免误导排障；run 期间新增候选路径在 produced 内，
    # 残留仍走上方 left 判定，不受此豁免影响。
    preserved = sorted(
        p for p in residue_k - produced if not p.startswith(INBOX_DIR_PREFIX)
    )
    if preserved:
        logger.warning(
            "knowledge-distill 放弃产出：回滚后 spec/knowledge/ 下存在不属于"
            "本次产出的新增路径（疑似 run 进行中的用户未提交改动），未回滚"
            "留工作区，请人工核查: %s",
            ", ".join(preserved),
        )
    return True


# 越界写面对账（code-review c8e789897144）：蒸馏 run 以 bypassPermissions 在主树
# 直跑，「写路径限定 spec/knowledge/」仅由提示词承载，validate_knowledge 与
# _discard_output 也只覆盖 KNOWLEDGE_DIR——run 越界改动主树其他路径（如被归档
# spec 内容提示注入后改产品代码）既不会被校验拦截也不会被回滚。蒸馏车道合法
# 写面 = 产出本体（KNOWLEDGE_DIR）+ .fenix/ 下逐项列举的框架运行时文件，对账时
# 排除以免误报。豁免按具体文件路径而非 .fenix/ 整目录前缀（code-review
# d688334e0113）：整目录豁免会让 run 越界改写 .fenix/ 下其他文件（如入库的
# verify.yaml / config.template.yaml）不留任何 WARNING，监控承诺失真。列举口径：
# - .fenix/knowledge-distill.lock：跨进程单飞 flock 锁（_acquire_file_lock）
# - .fenix/knowledge-distill-pending.json：pending 台账（dispatch/收尾清除）
# - .fenix/knowledge-distill-pending.lock：pending 台账读改写 flock 锁
#   （_pending_ledger_lock，code-review 968bbb6b7458 收录）
# - .fenix/knowledge-log.lock：log.md 追加窗口 flock 锁（_knowledge_log_lock）
# - .fenix/knowledge-rewrite.lock：溯源改写读改写窗口 flock 锁
#   （_source_rewrite_lock）
# - .fenix/knowledge-distill-retry-state.json：催办去重状态
#   （RETRY_REMIND_STATE_RELPATH）
# - .fenix/knowledge-distill-retry-state.lock：催办状态读改写 flock 锁
#   （_retry_state_write_lock）
# - .fenix/todo.md 与伴生锁 .fenix/.todo.md.lock：todo.md 重试台账
#   （_register_todo_retry → append_todo_line）
# 这些运行时文件被 .gitignore 的 .fenix/* 规则忽略、本不进 git status，仍逐项
# 列出以固化真实写面（gitignore 规则变动时不静默变成误报源）。
# - .fenix/knowledge-distill-rollback-backup/：回滚前 tracked 修改类产出路径
#   的工作区内容侧档（_backup_knowledge_tracked，code-review db69ec83c724）
# 目录类豁免条目保留前缀形态（尾随 / 自带边界，覆盖目录下任意文件）；文件类
# 条目拆出 _STRAY_AUDIT_IGNORE_FILES 走完整串匹配（code-review 715c34b38772）：
# 裸前缀 startswith 无尾边界，".fenix/todo.md" 等会连带豁免同前缀加任意后缀
# 的变体路径（如 .fenix/todo.md.bak、.fenix/knowledge-distill.lockX），越界
# 对账对这些路径静默漏报，监控承诺出现缺口。
_STRAY_AUDIT_IGNORE_PREFIXES = (
    KNOWLEDGE_DIR + "/",
    ".fenix/knowledge-distill-rollback-backup/",
)
# 文件类豁免条目（完整串精确匹配，拆分理由见上注）。
_STRAY_AUDIT_IGNORE_FILES = (
    ".fenix/knowledge-distill.lock",
    ".fenix/knowledge-distill-pending.json",
    ".fenix/knowledge-distill-pending.lock",
    ".fenix/knowledge-log.lock",
    ".fenix/knowledge-rewrite.lock",
    ".fenix/knowledge-distill-retry-state.json",
    ".fenix/knowledge-distill-retry-state.lock",
    ".fenix/todo.md",
    ".fenix/.todo.md.lock",
)


def _git_status_paths(proot: Path):
    """主树 ``git status --porcelain -z`` 路径快照（含未跟踪文件）。

    Returns:
        路径集合；``None`` = git 不可用/非 git 仓库（无从对账，调用方跳过）。
    """
    try:
        # --no-optional-locks：本快照在蒸馏 worker 线程上先于 spawn 运行，与
        # 主线程 commit_archive_move 的 git add 并发；git status 的机会式索引
        # 刷新会短暂持有 index.lock，撞出 EEXIST 让归档提交误报失败
        # （tests/test_knowledge_e2e 回归）。只读快照不应写索引。
        # -z（code-review 3835ca8b25cd）：文本 porcelain 对非 ASCII/特殊路径
        # 默认按 core.quotePath 输出 C 风格引号（形如 "spec/knowledge/\346..."），
        # 前缀 startswith 判定失配——overlap 保护漏识别 spec/knowledge/ 下用户
        # 中文命名文件、越界对账误报。-z 格式不引号不转义；rename/copy 条目为
        # NUL 分隔两段（新路径带 XY 前缀在前，旧路径裸路径在后）。
        status = _git(
            proot, ["--no-optional-locks", "status", "--porcelain", "-z"]
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("knowledge-distill git status 失败，跳过越界写面对账: %s", e)
        return None
    if status.returncode != 0:
        return None
    paths = set()
    skip_from = False
    for tok in status.stdout.split("\0"):
        if not tok:
            continue
        if skip_from:
            # rename/copy 的旧路径段（无 XY 前缀）：与文本模式一致只取新路径侧
            skip_from = False
            continue
        if len(tok) <= 3 or tok[2] != " ":
            continue
        if tok[0] in "RC":  # rename/copy 条目：下一段是旧路径
            skip_from = True
        paths.add(tok[3:])
    return paths


def _knowledge_baseline_snapshot(proot: Path):
    """run 前基线快照（``_git_status_paths`` + 折叠条目就地展开）。

    祖先折叠条目（如首蒸项目 spec/ 全树未跟踪时 status 把整树折叠为
    ``spec/``）不能事后展开（code-review 86d88801917e）：基线快照取在
    run 开始前，而 ``_expand_knowledge_surface`` 的事后 ls-files 枚举发生
    在 run 结束后——此刻蒸馏产出已在盘上，把产出自身收进基线，run_new
    差集恒为空集（_commit_output 按「无变更」成功收尾并清 pending 台账，
    产出滞留工作区永不落库）、overlap 恒非空（_discard_output 把产出误判
    为用户 run 前手工策展而跳过回滚）。故须在快照时刻就地展开：产出尚未
    写入，此刻枚举即真实基线。折叠条目本身意味着其子树下无任何已跟踪
    文件、子树 untracked 面恰为枚举面的子集，不会过度收纳；折叠条目由
    枚举结果替代（保留会让下游展开仍走事后枚举分支）。

    knowledge 内部整树未跟踪折叠条目（code-review b480c04897d8）同理：
    祖先折叠只覆盖 kn_prefix 之前的层，knowledge 目录自身的子树折叠（如
    index.md/log.md 已跟踪而 domains/ 尚无已跟踪文件时折叠为 ``??
    spec/knowledge/domains/``）若原样留在快照里，下游 _expand_knowledge_
    surface 会按 run 结束后的盘面事后枚举该折叠子树——蒸馏产出（能力页
    恰落 domains/ 下）被并入基线，run_new 恒空集、pending 台账被清而产出
    滞留永不落库。与祖先折叠同口径在快照时刻就地展开。

    Returns:
        路径集合；``None`` = 快照或就地展开不可用（git 失败），调用方按
        「基线不可用」保守口径处置（不提交、登重试台账 / 跳过回滚），
        不得降级为空集或保留折叠条目事后展开（展开失败回退原折叠形态会
        重新打开上述产出充基线链，同样不可接受）。
    """
    paths = _git_status_paths(proot)
    if paths is None:
        return None
    kn_prefix = KNOWLEDGE_DIR + "/"
    ancestor_folds = {
        p for p in paths if p.endswith("/") and kn_prefix.startswith(p)
    }
    internal_folds = {
        p for p in paths if p.startswith(kn_prefix) and p.endswith("/")
    }
    if not ancestor_folds and not internal_folds:
        return paths
    try:
        probe = _git(
            proot,
            [
                "--no-optional-locks", "ls-files",
                "--others", "--exclude-standard", "-z",
                "--", KNOWLEDGE_DIR,
            ],
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning(
            "knowledge-distill 基线快照折叠条目就地展开失败（%s），"
            "按基线不可用处置",
            e,
        )
        return None
    if probe.returncode != 0:
        logger.warning(
            "knowledge-distill 基线快照折叠条目就地展开失败（git "
            "ls-files 退出码 %d，stderr: %s），按基线不可用处置",
            probe.returncode,
            (probe.stderr or "").strip()[-300:] or "（空）",
        )
        return None
    untracked = [tok for tok in probe.stdout.split("\0") if tok]
    expanded = paths - ancestor_folds - internal_folds
    if ancestor_folds:
        # 祖先折叠意味着 knowledge 全表面 untracked，枚举面恰为全表面，
        # 整体收纳（86d88801917e 原逻辑不变）
        expanded.update(untracked)
    else:
        # 内部折叠：只收纳折叠条目子树内的文件（对齐 _expand_knowledge_
        # surface 的 folded_inside 口径——枚举面是当下盘面，折叠子树外的
        # 文件级路径由快照原样承载，不靠当下枚举）
        expanded.update(
            f for f in untracked
            if any(f.startswith(d) for d in internal_folds)
        )
    return expanded


def _audit_stray_writes(proot: Path, before, label: str) -> None:
    """越界写面对账：``before``（run 前基线）之外新增的主树改动记 WARNING。

    基线取 run 前快照做差集，而非单一事后快照——主树是用户工作区，用户既有
    未提交改动不应被误报为 run 产物。只告警不 restore：restore 会吞掉用户
    在同一批路径上的未提交改动，风险大于收益（code-review c8e789897144）。
    """
    if before is None:
        return
    after = _git_status_paths(proot)
    if after is None:
        return
    # 目录折叠展开（code-review item 382b61405cd2，对齐 _discard_output /
    # _commit_output 经 _expand_knowledge_surface 的同款处理）：git status 把
    # 无任何已跟踪文件的整棵子树折叠为单条目录项——首蒸项目 spec/ 全树未
    # 跟踪时本次 run 的合法知识产出折叠为 "spec/"，该条目不以 KNOWLEDGE_DIR
    # 前缀开头，前缀过滤放行，run 自身产出被误报为越界写面。把折叠到
    # KNOWLEDGE_DIR 祖先层的条目用 ls-files 展开到文件粒度再参与过滤；不直
    # 接复用 _expand_knowledge_surface（其只归一 knowledge 表面、会丢折叠
    # 子树内 knowledge 之外的越界改动），枚举范围取折叠子树整体，子树内
    # knowledge 之外的新增仍被前缀过滤之外的口径上报。枚举失败时保留折叠
    # 条目原样参与过滤（宁冒误报噪音，不引入漏报）。
    diff = after - before
    expanded: set = set()
    for p in diff:
        if not (p.endswith("/") and (KNOWLEDGE_DIR + "/").startswith(p)):
            expanded.add(p)
            continue
        try:
            probe = _git(
                proot,
                [
                    "--no-optional-locks", "ls-files",
                    "--others", "--exclude-standard", "-z", "--", p,
                ],
            )
        except (OSError, subprocess.TimeoutExpired):
            expanded.add(p)
            continue
        if probe.returncode != 0:
            expanded.add(p)
            continue
        expanded.update(tok for tok in probe.stdout.split("\0") if tok)
    strays = sorted(
        p
        for p in expanded
        if p not in _STRAY_AUDIT_IGNORE_FILES
        and not p.startswith(_STRAY_AUDIT_IGNORE_PREFIXES)
    )
    if strays:
        logger.warning(
            "knowledge-distill 越界写面告警（%s）: run 在蒸馏车道合法写面"
            "（%s 及 .fenix/ 下蒸馏运行时文件）之外新增主树改动，未回滚"
            "（避免吞掉用户未提交改动），请人工核查: %s",
            label,
            KNOWLEDGE_DIR,
            ", ".join(strays),
        )


def _expand_knowledge_surface(proot: Path, paths) -> set | None:
    """把 status 路径快照展开到 ``spec/knowledge/`` 文件粒度。

    git status 对「目录下无任何已跟踪文件」的未跟踪子树按整目录折叠展示
    （如 ``?? spec/``），文件级基线差集对此是盲区：首蒸项目（spec/ 下尚无
    已跟踪文件）的全部产出会被折叠条目藏住，按文件路径过滤得空集而跳过
    提交。仅当快照含与 knowledge 表面相交的折叠条目（条目在 knowledge
    目录之下，或 knowledge 目录在其子树内）时，用 ls-files 枚举 knowledge
    表面实际未跟踪文件补全；其余路径原样保留。探测失败返回 None：若
    按空集降级，折叠条目藏住的未跟踪产出会被差集误判为「无本次 run
    新增」而按成功收尾（code-review 4d0b4682b40a 无账滞留链），调用方
    须按快照不可用口径处置（不提交、登重试台账）。
    """
    surface: set = set()
    kn_prefix = KNOWLEDGE_DIR + "/"
    folded_inside: list = []  # knowledge 目录内部的折叠条目（目录前缀）
    need_probe = False
    for p in paths:
        if p.startswith(kn_prefix):
            if p.endswith("/"):
                folded_inside.append(p)
                need_probe = True  # knowledge 目录内部整目录折叠
            else:
                surface.add(p)
        elif p.endswith("/") and kn_prefix.startswith(p):
            need_probe = True  # 祖先目录折叠（如 spec/ 全树未跟踪）：knowledge
            # 全表面都在折叠子树内，probe 结果原样收纳。注意本事后展开只对
            # 「现状」侧快照（after/residue——枚举即当下盘面）成立；基线侧
            # 快照经 _knowledge_baseline_snapshot 在快照时刻就地展开、不在
            # 此处事后枚举（run 结束后产出已在盘上，事后枚举会把产出自身
            # 充作基线，code-review 86d88801917e）
    if need_probe:
        # 探测点包裹口径（code-review e28a085720d7）：对齐 _discard_output /
        # _audit_stray_writes 同款 try/except——git 二进制缺失或 ls-files 超时
        # 抛异常会沿 _discard_output/_rollback_failed_fold 调用点无保护上抛，
        # 把保守降级路径升级成整批执行异常。docstring 契约是探测失败返回 None。
        try:
            probe = _git(
                proot,
                [
                    "--no-optional-locks", "ls-files",
                    "--others", "--exclude-standard", "-z",
                    "--", KNOWLEDGE_DIR,
                ],
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            logger.warning(
                "knowledge-distill 未跟踪文件枚举失败（%s），无法可靠判定基线差集",
                e,
            )
            return None
        if probe.returncode == 0:
            untracked = [tok for tok in probe.stdout.split("\0") if tok]
            if folded_inside:
                # 只收纳折叠条目子树内的文件（add-knowledge-inbox-pipeline
                # 3.1 回滚场景修复）：快照里的折叠条目只代表它自己子树的
                # untracked 面，ls-files 枚举的是**当下**盘面——折叠失败回滚
                # 展开基线快照时，run 产出（非折叠子树的文件级新增）会被误
                # 充基线，与现状快照恒交集 → overlap 保守跳过、半成品滞留。
                # 非折叠子树的文件级路径由快照原样承载，不靠当下枚举。
                surface.update(
                    f for f in untracked
                    if any(f.startswith(d) for d in folded_inside)
                )
            else:
                surface.update(untracked)
        else:
            logger.warning(
                "knowledge-distill 未跟踪文件枚举失败，无法可靠判定基线差集"
            )
            return None
    return surface


def _commit_output(proot: Path, archived_names: list, baseline=None, msg: "str | None" = None) -> str | None:
    """pathspec 限定自动提交（复用 archive_commit 的 fail-open 哲学）。

    ``msg``（add-knowledge-inbox-pipeline 3.1）：折叠前置段的逐条提交复用本
    函数的基线甄别与 fail-open 口径，仅换提交信息（``[fenix] knowledge: fold
    <条目>``）；缺省 None 保持蒸馏提交信息不变。

    基线甄别（code-review 50251dbfd0c1）：``baseline`` 为本批 run 前的
    基线快照（_run_batch_core 的 run_baseline，经 _knowledge_baseline_snapshot
    就地展开祖先折叠条目），与
    _discard_output / _audit_stray_writes「不吞用户未提交改动」同一尺度：
    仅 add/commit 相对基线确为本次 run 新增的 spec/knowledge/ 路径。此前
    整目录 ``git add -- spec/knowledge`` 是无基线的全路径面收纳，会把用户
    同窗口内在合法写面（spec/knowledge/）里的未提交手工策展一并卷进
    distill 提交落库，来源归属失真。基线已有路径不入提交、WARNING 留痕
    交人工；基线不可用（快照失败）时不收纳、按提交失败处置（重试 + 登
    台账），宁可滞留人工也不静默卷入用户改动。

    Returns:
        commit hash；``""``（无本次 run 新增改动可提交——空产出，或改动
        全落在基线已有路径上；或提交已落库但 hash 回读失败——后者已记
        warning，视为 ok）；None（提交失败，已记 warning）。
    """
    names = ", ".join(archived_names)
    commit_msg = msg or f"{COMMIT_PREFIX} {names}"
    try:
        # 基线差集（code-review 50251dbfd0c1）：after - baseline 即本次 run
        # 新增路径（含未跟踪新建与 tracked 改/删）；与 baseline 的交集疑似
        # 用户手工策展或 run 与用户同文件双写，排除不入提交（内容不丢，
        # 留工作区交人工，同 _discard_output 的 overlap 保守跳过口径）。
        after = _git_status_paths(proot)
        if baseline is None or after is None:
            logger.warning(
                "knowledge-distill 自动提交：工作区基线快照不可用，跳过 "
                "spec/knowledge/ 收纳（避免卷入用户未提交改动），按提交失败"
                "处置，请人工核查"
            )
            return None
        # 目录折叠展开：两侧快照先归一到 knowledge 表面文件粒度再做差集，
        # 否则折叠条目（如 spec/ 全树未跟踪时的 '?? spec/'）会把产出藏住
        after_k = _expand_knowledge_surface(proot, after)
        baseline_k = _expand_knowledge_surface(proot, baseline)
        if after_k is None or baseline_k is None:
            # 枚举失败时差集不可靠（折叠条目可能藏住产出，误判「无变更」
            # 会按 ok 收尾清 pending 让产出无账滞留），返回 None 走提交失败
            # 处置（_run_batch 短退避重试 + 登重试台账），与「基线快照不可
            # 用」同一口径（code-review 4d0b4682b40a）
            logger.warning(
                "knowledge-distill 自动提交：spec/knowledge/ 未跟踪文件枚举"
                "失败，无法可靠甄别基线差集，跳过收纳，按提交失败处置，"
                "请人工核查"
            )
            return None
        run_new = sorted(p for p in after_k if p not in baseline_k)
        overlap = sorted(p for p in after_k if p in baseline_k)
        if overlap:
            logger.warning(
                "knowledge-distill 自动提交：spec/knowledge/ 下改动含 run 前"
                "基线已有路径（疑似用户未提交的手工策展，或 run 与用户改动"
                "同文件），本次提交不含这些路径（避免 distill 提交信息来源"
                "归属失真），请人工核查: %s",
                ", ".join(overlap),
            )
        if not run_new:
            # 无可归属本轮的产出（空产出，或改动全落在基线已有路径）：按
            # 空产出 noop 返回 ""（即旧「pathspec 零命中」口径，
            # code-review 0acc8a12d881），避免误登「产出滞留」重试台账。
            logger.info(
                "knowledge-distill 无本次 run 新增的 spec/knowledge/ 改动"
                "（%s），跳过提交",
                names,
            )
            return ""
        # 快照时点干净、run 中途变脏的已跟踪路径留痕（code-review
        # db69ec83c724）：run_new 差集甄别不了写者——tracked 路径在快照
        # 时点干净（未列入基线），run 期间被写脏，可能是蒸馏产出、也可能
        # 是 run 进行中用户对原本干净知识文件的未提交修改，一并卷入蒸馏
        # 提交来源归属失真，WARNING 留痕不静默（甄别失败仅留痕不阻提交）。
        try:
            probe = _git(
                proot, ["--no-optional-locks", "ls-files", "-z", "--"] + run_new
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            logger.warning(
                "knowledge-distill 自动提交：git ls-files 甄别 run 新增路径"
                "中的 tracked 文件失败（%s），无法留痕快照时点干净路径的"
                "卷入面",
                e,
            )
        else:
            tracked_new = (
                sorted(
                    p
                    for p in run_new
                    if p in set(probe.stdout.split("\0"))
                )
                if probe.returncode == 0
                else []
            )
            if tracked_new:
                logger.warning(
                    "knowledge-distill 自动提交：run 新增路径含快照时点干净"
                    "的已跟踪文件（写者不可甄别——若含 run 进行中用户对知识"
                    "文件的未提交修改将被卷入本提交，来源归属失真，请人工"
                    "核查）: %s",
                    ", ".join(tracked_new),
                )
        # add 的 pathspec 即本次 run 新增路径集：均来自当前 status 快照
        # （文件在工区存在或为 tracked 删除），不存在旧整目录 add 的
        # 「pathspec 零命中」歧义，无需 ls-files 零命中探测。
        add = _git(proot, ["add", "--"] + run_new)
        if add.returncode != 0:
            logger.warning("knowledge-distill git add 失败: %s", add.stderr.strip())
            return None
        commit = _git(
            proot, ["commit", "-m", commit_msg, "--"] + run_new, timeout=120
        )
        if commit.returncode != 0:
            # nothing to commit ≠ 提交失败：蒸馏判定无需新增/修改页面（如重复
            # 蒸馏同批归档），按无变更视为 ok，避免误报「产出滞留」+ 误登重试
            # 台账（code-review 1e83848b80f1）。探测 pathspec 同样限定 run 新增
            # 路径：整目录探测会被基线已有路径（用户未提交改动）误判成
            # 「有变更」。
            # --no-optional-locks（code-review 4df445fc71e3）：本探测与归档主线程
            # commit_archive_move 的 git add 并发（同 _git_status_paths 场景），
            # status 的机会式索引刷新撞 index.lock 退出非零时会把「无变更可提交」
            # 误判为提交失败，走 reset + warning + None，白耗一轮重试并可能误登
            # 台账。只读探测不应写索引。
            status = _git(
                proot,
                ["--no-optional-locks", "status", "--porcelain", "--"] + run_new,
            )
            if status.returncode == 0 and not status.stdout.strip():
                logger.info("knowledge-distill 无变更可提交（%s），跳过空提交", names)
                return ""
            # reset 同样只落 run 新增路径：不触碰基线已有路径（含用户可能
            # 自行 staged 的条目）。
            _git(proot, ["reset", "--"] + run_new)
            logger.warning(
                "knowledge-distill git commit 失败: %s",
                commit.stderr.strip() or f"exit {commit.returncode}",
            )
            return None
        rev = _git(proot, ["log", "-1", "--format=%H", "--", KNOWLEDGE_DIR])
        if rev.returncode == 0:
            return rev.stdout.strip()
        # 走到这里 commit 已落库（上方 returncode == 0），仅 hash 回读瞬态
        # 失败（index.lock 撞车、git 钩子抖动等）。不能返回 None——调用方
        # 会把 None 一律按「提交失败」处理，误报「产出滞留工作区」并重复
        # 登重试台账、对同一批归档再跑一轮完整蒸馏（code-review
        # 46be2e75f49e）。降级按成功返回 ""（hash 未知），warning 留痕。
        logger.warning(
            "knowledge-distill git log 回读 commit hash 失败（提交已落库，"
            "hash 未知）: %s",
            rev.stderr.strip() or f"exit {rev.returncode}",
        )
        return ""
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("knowledge-distill 自动提交异常: %s", e)
        return None


# ── pending 台账（evo-knowledge-distill-resume-guard R1，design D1）──────

# 台账文件：``<proot>/.fenix/knowledge-distill-pending.json``，与既有
# knowledge-distill.lock 同目录不同文件、互不阻塞。结构
# ``{"batches": [{"names": [...], "queued_at": "<ISO8601>"}]}``（同批多归档
# 合并为一条）。
PENDING_LEDGER_NAME = "knowledge-distill-pending.json"

# 保留 pending 条目的三类滞留路径（提交失败/执行异常/回滚未确认）在既有
# todo 台账文案中统一追加的接管口径（R2：条目保留交 R3 恢复或人工兜底，
# 不得静默清除）。
_RESUME_TAKEOVER_NOTE = "pending 台账条目保留，将由 daemon 重启续跑接管"


def _pending_ledger_path(proot: Path) -> Path:
    return Path(proot) / ".fenix" / PENDING_LEDGER_NAME


def _read_pending_ledger(proot: Path) -> list:
    """读 pending 台账（缺失/损坏/不可读按空表 fail-open，R1）。

    宁可丢台账不可阻归档：台账丢失的后果是批次退回「内存态重启蒸发」的
    现状而非更糟（design D1）。条目须为 ``{"names": [非空 str, ...]}`` 形态，
    形态不合规的条目跳过（不影响其余条目）。
    """
    try:
        raw = _pending_ledger_path(proot).read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError) as e:
        # UnicodeDecodeError 非 OSError 子类：台账含非 UTF-8 字节时同样按
        # 空表 fail-open（否则异常穿到 recover_pending 使整批恢复放弃）。
        logger.warning("knowledge-distill pending 台账读取失败，按空表处理: %s", e)
        return []
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError) as e:
        # RecursionError 非 ValueError 子类（RuntimeError 系）：手工编辑的台账
        # 含数千层嵌套结构时 json 解析递归爆栈，同样按空表 fail-open——否则
        # 异常穿透 recover_pending 首读（try 之外）使整批恢复放弃（code-review
        # b100c02039bb，手编台账防御口径与 670ba45b05de 对齐）。
        logger.warning("knowledge-distill pending 台账损坏（解析失败），按空表处理: %s", e)
        return []
    batches = data.get("batches") if isinstance(data, dict) else None
    if not isinstance(batches, list):
        return []
    out = []
    for item in batches:
        if not isinstance(item, dict):
            continue
        names = item.get("names")
        if not isinstance(names, list):
            continue
        names = [n for n in names if isinstance(n, str) and n]
        if not names:
            continue
        out.append({"names": names, "queued_at": str(item.get("queued_at") or "")})
    return out


def _write_pending_ledger(proot: Path, batches: list) -> None:
    """整文件原子回写（tmp + os.replace，复用 knowledge_backfill 同款手法）。

    Raises:
        OSError 等写异常原样上抛——调用方（持 ``_guard`` 的单写者）按各自
        路径 fail-open（dispatch/清除）或放弃恢复（recover_pending）。
    """
    atomic_write_text(
        _pending_ledger_path(proot),
        json.dumps({"batches": batches}, ensure_ascii=False, indent=2) + "\n",
    )


@contextmanager
def _pending_ledger_lock(proot: Path):
    """pending 台账读改写窗口的进程间互斥（flock，``.fenix/knowledge-distill-pending.lock``）。

    同 knowledge_audit._findings_write_lock 口径（code-review 106b0cd5527d）：
    _write_pending_ledger 的 tmp + os.replace 只保证单次写不撕裂，不保证读改写
    原子性——daemon 与 dashboard --serve 各持一份 _MANAGER 单例，两进程都会走
    到派发（dashboard 侧 spec_archive → dispatch_distill，daemon 侧自动归档同
    链路），进程内 self._guard 挡不住跨进程：并发 append 时后写者以旧快照整文
    件覆盖先写者刚落的批次条目（崩溃续跑丢批）；append/remove 并发时 remove
    的整文件回写可吞掉刚 append 的条目、或复活已入库批次的条目（重启恢复对已
    入库归档触发重蒸，正是 _ledger_remove docstring 要防的）。写方一律持锁重读
    盘上最新 batches 再合并回写。锁文件自身无内容语义，与 knowledge-distill.lock
    同目录不同文件、互不阻塞（不复用后者——它被整个蒸馏 run 长期持有，append
    在 dispatch 归档主流程上，不得排队等 run 结束）。
    """

    with _fenix_file_lock(proot, "knowledge-distill-pending.lock"):
        yield


# ── 蒸馏批 run 产物（add-distill-run-artifacts 1.1）─────────────────────
# 一批 = 一个 run（对齐「1 run = 1 车道派发」口径）：批开始（首个 spawn 前）
# 在 .fenix/runs/ 建产物写开始事件行，批收尾按批结果写终态行（result/error）。
# 合成事件流形态（design D1 备选 B）：spawn stdout/stderr 保持裸文本不改诊断
# 摘要语义，读侧 classify_run 只看末行 type，合成行与原生行在读侧完全等价。
# 全链 fail-open（design D2 三道防线）：产物创建/事件行追加全吞 OSError，
# 终态行收口自身不抛——蒸馏结果与台账行为与无产物形态完全一致，蒸馏的正确性
# 优先级恒高于观测。单 worker 线程逐批消费；产物写者=worker 主线程 + 批级
# 心跳线程双写者（fix-distill-observation-gaps 2.1：spawn 等待期心跳保活，
# 防长跑批被读侧 mtime 停更判 stale、被 retention 提前移走致终态行写空），
# append_run_line 的 O_APPEND 原子追加契约覆盖并发写交错。


def _distill_run_artifact_open(proot: Path, archived_names: list) -> "Path | None":
    """创建蒸馏批 run 产物并写开始事件行；OSError fail-open 返回 None。

    run_id = ``knowledge-distiller-<首归档名>-<int(time.time())>``：一批多
    归档时中段取首归档名（人类可读溯源）、批内全名单进开始行 ``archived``
    字段数组；归档目录名自带日期前缀含点号。读侧 run_id 白名单
    ``_RUN_ID_RE``（``^[A-Za-z0-9._-]+`` 全串校验，实际定义于
    core/dashboard/data/runs.py 的 _resolve_run_file 前置）不接受非
    ASCII——_gate_distill 只拦路径分隔符与 ./.. 不拦非 ASCII 字符，SPEC
    目录名为中文等形态时原样拼入会被读侧判 invalid、`run_id=...` 直查恒
    返回哨兵路径、产物按 run_id 定位恒「不存在」，故首归档名先做白名单外
    字符归一（非白名单字符折叠为 ``_``，原始全名仍在开始行 ``archived``
    数组可溯源；code-review c9bd4a44a216）。
    """
    if not archived_names:
        # 空批防御（code-review f7fc0afca89d）：现役调用链（dispatch_distill
        # 单名入口、dispatch_distill_batch 空批早退、recover_pending 的 names
        # 判空、_worker 的空队列退出）均保证非空，属防御缺口而非现行缺陷；
        # 一旦未来入口放行空批，[0] 的 IndexError 会被 _worker 兜底 except
        # 捕获并误登「执行异常」重试台账、误导排障。与产物 fail-open 口径
        # 一致提前返回 None（产物缺席不阻蒸馏主流程）。
        return None
    # 归一字符集与读侧 _RUN_ID_RE 白名单（^[A-Za-z0-9._-]+\Z）保持一致
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", archived_names[0])
    run_file = (
        proot
        / ".fenix"
        / "runs"
        / f"knowledge-distiller-{stem}-{int(time.time())}.jsonl"
    )
    try:
        run_file.parent.mkdir(parents=True, exist_ok=True)
        run_file.touch(exist_ok=True)
        append_run_line(
            run_file,
            {
                "type": "started",
                "archived": list(archived_names),
                "rounds": 0,
                "timestamp": now_local().isoformat(timespec="seconds"),
            },
        )
    except OSError as e:  # 与 runner.py run_file.touch 既有防御口径一致
        logger.warning("knowledge-distill run 产物创建失败（fail-open）: %s", e)
        return None
    return run_file


def _distill_run_artifact_round(
    run_file: "Path | None", rounds: int, ok: bool, violations: int
) -> None:
    """批内单轮 spawn 收尾追加 round 事件行（产物行数随修正轮数递增）。

    非终态行：daemon 中途断尾时读侧按末行非终态 + mtime 停更 stale 兜底
    （design D2 防线 3）；正常路径由终态行收口，无 stale 窗口。
    """
    if run_file is None:
        return
    try:
        append_run_line(
            run_file,
            {
                "type": "round",
                "rounds": rounds,
                "ok": bool(ok),
                "violations": int(violations),
                "timestamp": now_local().isoformat(timespec="seconds"),
            },
        )
    except OSError as e:
        logger.warning("knowledge-distill run 产物轮次行写入失败（fail-open）: %s", e)


# add-distill-run-work-summary 1.2：主蒸馏工作总结提取参数——截断上限
# （字符）防 agent 输出失控刷爆时间轴总结盒；标记行是完成契约的剥离锚点。
_DISTILL_SUMMARY_MAX_CHARS = 2000
_DISTILL_SUMMARY_MARKER = "KNOWLEDGE_DISTILL_DONE"
_DISTILL_SUMMARY_TRUNCATED_SUFFIX = "…（截断）"


def _extract_distill_summary(stdout: str) -> str:
    """从主蒸馏 spawn stdout 提取工作总结（design D2，纯函数便于单测）。

    - 剥除尾部 ``KNOWLEDGE_DISTILL_DONE`` 标记行（标记从无消费方的提示词
      契约转正为剥离锚点；缺失时空转不报错——成功判据仍是退出码 + 校验
      脚本，标记仅作剥离锚，fail-open）；
    - 首尾空白归一；
    - 超 ``_DISTILL_SUMMARY_MAX_CHARS`` 尾部截断加「…（截断）」后缀；
    - 空输入/剥标记后为空 → 空串（调用方空串不写键）。
    """
    if not stdout:
        return ""
    lines = stdout.splitlines()
    # 尾部容错：标记行前后允许空白行（提示词只约束「最后一行」）
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and lines[-1].strip() == _DISTILL_SUMMARY_MARKER:
        lines.pop()
    text = "\n".join(lines).strip()
    if len(text) > _DISTILL_SUMMARY_MAX_CHARS:
        text = (
            text[:_DISTILL_SUMMARY_MAX_CHARS] + _DISTILL_SUMMARY_TRUNCATED_SUFFIX
        )
    return text


def _distill_run_artifact_close(run_file: "Path | None", result: dict) -> None:
    """按批结果写终态行（ok→``result`` / 其余→``error`` 附 reason 摘要）。

    四个 return 路径（成功/失败 give_up/提交失败滞留/校验违规放弃）统一在此
    收口（design D1：不逐点插桩）；终态行写入自身 MUST NOT 抛（design D2
    防线 2）——写失败静默放弃产物，蒸馏 result 照常返回。
    """
    if run_file is None:
        return
    try:
        if result.get("ok"):
            line = {
                "type": "result",
                "names": result.get("names"),
                "commit": result.get("commit"),
                "rounds": result.get("rounds"),
                # add-knowledge-inbox-pipeline 4.2：折叠前置段计数随终态
                # 行下发（读侧不解析未知键，纯增量观测）
                "folded": result.get("folded", 0),
                "fold_failed": result.get("fold_failed", 0),
                "timestamp": now_local().isoformat(timespec="seconds"),
            }
            # add-distill-run-work-summary 2.1：主蒸馏工作总结随终态行下发。
            # 字段名必须为 ``result``（读侧 _run_tail_insights 既有契约，
            # dict 内部键名用 summary 避免与行类型语义混淆）；非空字符串才
            # 写该键——stdout 空/仅标记行（fail-open）与历史产物一样按字段
            # 缺失渲染，时间轴与现状一致；error 分支不动。
            _summary = result.get("summary")
            if isinstance(_summary, str) and _summary:
                line["result"] = _summary
            append_run_line(run_file, line)
        else:
            append_run_error(
                run_file,
                str(result.get("error") or "蒸馏批失败（无错误摘要）"),
                exit_code=1,
            )
    except Exception as e:  # noqa: BLE001 — finally 收口不抛，写失败放弃产物
        logger.warning(
            "knowledge-distill run 产物终态行写入失败（fail-open）: %s", e
        )


# 心跳间隔（fix-distill-observation-gaps 2.1）：读侧 stale 阈值
# （runs.py ``_RUN_STALE_SECONDS``=1800s）的一半——任一 1800s 停更窗口内必有
# ≥1 次心跳写入，既不密到污染产物（900s × 30min spawn 超时上限 ≈ 每批 ≤3 行，
# 且读侧 ``_read_run_lines(max_lines=3)`` 只看尾窗）也不松到撞 stale。
_DISTILL_HEARTBEAT_SECONDS = 900


def _distill_run_artifact_heartbeat_loop(run_file: Path, stop: threading.Event) -> None:
    """批级心跳线程体（fix-distill-observation-gaps 2.1）：spawn 等待期间定期
    向批产物追加非终态 heartbeat 事件行保活。

    - 非终态：``type: "heartbeat"`` 不在读侧 ``_RUN_TERMINAL_STATUS_MAP`` →
      classify_run 判 running（在飞语义正确）；strip_run_id_suffixes/
      run_spec_part/时间线读侧不解析行内容，零影响。
    - fail-open：线程体内全捕获异常（OSError 与其余异常一致静默）——心跳是
      纯观测，绝不让观测线程杀死蒸馏批。
    - 可中断停：``Event.wait(interval)`` 语义，``stop.set()`` 立即打断当前
      等待、循环退出（批 finally 先停线程再写终态行，保证终态行为末行）。
    """
    while not stop.wait(_DISTILL_HEARTBEAT_SECONDS):
        try:
            append_run_line(
                run_file,
                {
                    "type": "heartbeat",
                    "timestamp": now_local().isoformat(timespec="seconds"),
                },
            )
        except Exception as e:  # noqa: BLE001 — 纯观测心跳全异常吞掉（fail-open）
            logger.warning(
                "knowledge-distill run 产物心跳行写入失败（fail-open）: %s", e
            )


class DistillManager:
    """蒸馏 run 管理器（进程内单例）。

    - 同 project 单飞：进程内 per-project 队列 + 单 worker 线程串行消费；
      积压条目合并为一次批量 run（spec 允许的实现裁量）。
    - 跨进程互斥：``.fenix/knowledge-distill.lock`` flock（daemon 与 dashboard
      --serve 分属两进程时仍保证同时至多一个蒸馏 run 在写 spec/knowledge/）。
    - 崩溃续跑（evo-knowledge-distill-resume-guard）：入队即落盘
      ``.fenix/knowledge-distill-pending.json`` pending 台账（R1），批次收尾
      对账清除/保留（R2）；daemon 重启经 ``recover_pending`` 先清空台账再逐条
      重派（R3，dashboard --serve 不接入）。
    - spawn 可注入替身（task 2.4 单测 fake spawn 三支路）。
    """

    def __init__(self, spawn=None, max_fix_rounds: int = MAX_FIX_ROUNDS):
        self._spawn = spawn or _default_spawn
        # 负值归一为 0（code-review 225bc28ee061）：max_fix_rounds 是公开构造
        # 参数，传负值会使 range(1 + max_fix_rounds) 为空循环，控制流落到循环
        # 外的 _audit_stray_writes(proot, status_before, ...) 时引用未赋值的
        # status_before 抛 NameError（被 _worker 兜底 except 捕获后误导性登记
        # 「执行异常」台账）。归一后循环至少执行一轮 run，循环不变式成立。
        self._max_fix_rounds = max(0, max_fix_rounds)
        self._guard = threading.Lock()
        self._queues: dict = {}
        self._workers: dict = {}

    # ── 对外：入队（不阻塞归档主流程）───────────────────────────────
    def dispatch(self, proot: Path, archived_names: list) -> dict:
        # 陈旧代码预检（evo-add-key-path-stale-code-preflight 2.2）：写点收在
        # dispatch 单汇聚点（单条 dispatch_distill / 批量 dispatch_distill_batch
        # 均经 _dispatch_via_mgr 到达此处，与本文件「台账写点收在 dispatch 单点」
        # 惯例一致；两入口重复插桩会让单条路径双告警）。陈旧时请求重启（一条
        # WARNING + restart_request 防重），入队与派发照常进行、不被预检阻塞。
        from core.code_stale_flag import request_restart

        request_restart(lambda msg: logger.warning("%s", msg), "知识蒸馏派发")
        key = str(Path(proot).resolve())
        names = list(archived_names)
        with self._guard:
            queue = self._queues.setdefault(key, [])
            worker = self._workers.get(key)
            queue.extend(names)
            # R1（evo-knowledge-distill-resume-guard）：入队即落盘 pending 台账。
            # 写点收在 dispatch 单点（单条/批量入口经 _dispatch_via_mgr 汇聚于
            # 此）；回填期排队与各门控拒绝路径不达此处，天然不写台账（R2）。
            # 单写者 = 持 self._guard 的本线程（追加在锁内；worker 收尾的台账
            # 清除在锁外执行，append/remove 的读改写互斥由 _pending_ledger_lock
            # flock 持锁重读-回写兜底，见 _ledger_remove）；台账写失败
            # fail-open 不阻派发。
            self._ledger_append(proot, names)
            if worker is None or not worker.is_alive():
                worker = threading.Thread(
                    target=self._worker,
                    args=(Path(proot), key),
                    daemon=True,
                    name=f"knowledge-distill-{Path(proot).name}",
                )
                self._workers[key] = worker
                worker.start()
        return {"dispatched": True, "queued": names}

    def pending(self, proot: Path) -> int:
        with self._guard:
            return len(self._queues.get(str(Path(proot).resolve()), []))

    # ── pending 台账读写（evo-knowledge-distill-resume-guard R1/R2）──
    # 调用锁纪律：_ledger_append 在 dispatch 持 self._guard 的锁内调用；
    # _ledger_remove 的调用点（_run_batch 收尾与 _give_up，经 _worker 在
    # with self._guard 块外执行）不持 self._guard。进程内与跨进程（daemon
    # 与 dashboard --serve 各持 _MANAGER 单例）的读改写互斥均由
    # _pending_ledger_lock flock 的持锁重读-回写兜底（code-review
    # 106b0cd5527d）——不得按「锁内单写者」口径省掉 remove 路径的持锁重读。
    def _ledger_append(self, proot: Path, names: list) -> None:
        """入队追加台账条目（持跨进程 flock 读-改-原子回写；fail-open 不阻派发）。"""
        try:
            with _pending_ledger_lock(proot):
                # 持锁重读盘上最新台账：self._guard 只是进程内单写者，双进程
                # 并发 append 时后写者不得以旧快照覆盖先写者刚落的批次条目。
                batches = _read_pending_ledger(proot)
                batches.append(
                    {
                        "names": list(names),
                        "queued_at": now_local().isoformat(timespec="seconds"),
                    }
                )
                _write_pending_ledger(proot, batches)
        except Exception as e:  # noqa: BLE001 — 宁可丢台账不可阻归档
            logger.warning(
                "knowledge-distill pending 台账追加失败（fail-open，不影响派发）: %s",
                e,
            )

    def _ledger_remove(self, proot: Path, archived_names: list) -> None:
        """按本批 names 并集从各条目差集收窄移除（持跨进程 flock 读-改-原子回写；fail-open）。

        整文件重读-改-回写而非「删一条重写全量快照」：避免并发归档入队的
        追加被整文件覆盖丢条目（design D2）。读改写窗口持 _pending_ledger_lock
        flock：双进程并发时 remove 的回写不得吞掉另一进程刚 append 的条目、
        或复活已入库批次的条目。移除粒度按「名字差集」而非「条目交集」
        （code-review 26d750c4c7e6）：worker 跑批 A=[a] 收尾期间另一入口并发
        入队部分重叠条目 [a,b] 时，按交集整条删除会把 b 连带抹掉——b 仅剩
        对方进程内存队列兜底，该进程在 worker 摘下该批前崩溃即重演 R1 要防
        的「批次重启蒸发」（recover_pending 因台账已无该条目而丢续跑）；按
        差集重写后只结清本批名字，b 留在册可续跑。条目内全部名字均已收尾
        （差集为空）才整条删除——worker 把同项目积压整体摘下合并为一次 run
        时仍一次清除全部已收尾条目，只清「最后一条」会漏清先入队条目，陈旧
        条目会在重启恢复时对已入库归档触发重蒸。
        """
        try:
            with _pending_ledger_lock(proot):
                batches = _read_pending_ledger(proot)
                done = set(archived_names)
                kept = []
                changed = False
                for b in batches:
                    rest = [n for n in b["names"] if n not in done]
                    if not rest:
                        # 本批已覆盖该条目全部名字：整条删除
                        changed = True
                        continue
                    if len(rest) != len(b["names"]):
                        # 部分重叠条目按差集保留其余名字在册（queued_at 沿用
                        # 原条目），重启恢复可对剩余名字续跑
                        b = {**b, "names": rest}
                        changed = True
                    kept.append(b)
                if changed:
                    _write_pending_ledger(proot, kept)
        except Exception as e:  # noqa: BLE001 — 清除失败退回现状，不阻主流程
            logger.warning(
                "knowledge-distill pending 台账清除失败（fail-open）: %s", e
            )

    # ── worker：串行消费 + 批量合并 ─────────────────────────────────
    def _worker(self, proot: Path, key: str) -> None:
        while True:
            with self._guard:
                queue = self._queues.get(key, [])
                batch, self._queues[key] = queue[:], []
                if not batch:
                    # 退出前必须在锁内摘除自己：dispatch 持同一把锁 extend
                    # 队列后按 _workers 判定是否补线程，若此处锁外退出，
                    # dispatch 会看到尚存活的线程而漏补，新归档名滞留队列
                    # 无人消费（code-review 64067e7181f6 竞态窗口）。
                    self._workers.pop(key, None)
                    return
            try:
                self._run_with_lock(proot, batch)
            except Exception as e:  # noqa: BLE001 — worker 不因单批异常死亡
                logger.warning(
                    "knowledge-distill 执行异常（%s）: %s: %s",
                    ", ".join(batch),
                    type(e).__name__,
                    e,
                )
                _register_todo_retry(
                    proot,
                    batch,
                    f"执行异常: {e}（{_RESUME_TAKEOVER_NOTE}）",
                )

    def _acquire_file_lock(self, proot: Path):
        """跨进程单飞锁（flock，阻塞等待——并发归档事件排队串行）。

        复用模块级 ``_fenix_file_lock_fh`` 单源锁实现（与 _fenix_file_lock /
        _knowledge_distill_lock 同源，code-review e651c35d75fb）：加锁 / 释放 /
        异常收尾不再双份维护。本方法只保留句柄形态，供 _run_with_lock 的
        try/finally 显式收口（flock_release → close，与工厂约定的释放顺序
        一致）。锁文件打开形态由 ``open("w")`` 截断写统一为 O_RDWR|O_CREAT
        （锁文件自身无内容语义，截断与否行为等价）。
        """
        return _fenix_file_lock_fh(proot, "knowledge-distill.lock")

    def _run_with_lock(self, proot: Path, batch: list) -> None:
        lock_fh = self._acquire_file_lock(proot)
        try:
            self._run_batch(proot, batch)
        finally:
            try:
                flock_release(lock_fh.fileno())
            finally:
                lock_fh.close()

    # ── 一批蒸馏：run → 校验 → 修正（≤2 轮）→ 提交/放弃 ─────────────
    def _run_batch(self, proot: Path, archived_names: list) -> dict:
        # add-distill-run-artifacts 1.1：批生命周期产物包装——批开始（首个
        # spawn 前）建产物写开始行；批唯一生命周期入口（_worker 与 pending
        # 台账恢复重派路径都汇聚于此），四个 return 路径与异常路径统一经
        # finally 收口终态行（design D1 不逐点插桩）。fail-open：产物缺失/
        # 写失败不影响蒸馏主流程（_distill_run_artifact_* 全吞 OSError）。
        # fix-distill-observation-gaps 2.1：spawn 等待期由批级心跳线程定期
        # 追加非终态 heartbeat 行保活（防长跑批被读侧判 stale、被 retention
        # 提前移走致收尾终态行写空）；产物创建 fail-open 失败（run_file=None）
        # 不启动心跳线程。所有 return/异常路径统一在 finally 先停心跳线程
        # （event.set + join，Event.wait 可中断必收敛）再写终态行——顺序保证
        # 终态行为末行（读侧 classify_run 只看末行，覆盖心跳的 running 判定）；
        # join 超时（心跳写盘卡顿 >10s）则让位跳过终态行，不与心跳并发写（见
        # finally 内注释）。
        run_file = _distill_run_artifact_open(proot, archived_names)
        result: dict | None = None
        hb_stop = threading.Event()
        hb_thread: threading.Thread | None = None
        if run_file is not None:
            hb_thread = threading.Thread(
                target=_distill_run_artifact_heartbeat_loop,
                args=(run_file, hb_stop),
                name="distill-run-heartbeat",
                daemon=True,  # 进程退出不阻塞（join 超时兜底极端 IO 卡顿）
            )
            hb_thread.start()
        try:
            result = self._run_batch_core(proot, archived_names, run_file)
            return result
        except BaseException as exc:  # noqa: BLE001 — 异常也落终态行后原样上抛
            # worker 层吞单批异常并登 todo.md 台账；此处只为产物补 error 终态
            # 行（断尾由读侧 stale 兜底，正常异常路径终态行照写不留 stale 窗口）。
            result = {
                "ok": False,
                "names": ", ".join(archived_names),
                "rounds": 0,
                "commit": None,
                "error": f"批执行异常: {exc}",
            }
            raise
        finally:
            hb_stop.set()
            # join 超时兜底（code-review ba3293d4b961）：心跳线程在 append_run_line
            # 的磁盘写入上阻塞超 10s 时 join 带超时返回，此时照写终态行会与仍在
            # 写的心跳行并发追加、末行可能仍是 heartbeat（读侧把已结束的批继续
            # 判 running）。超时即让位：跳过终态行写入，由读侧 mtime-stale 兜底
            # 收口（一个 _RUN_STALE_SECONDS 窗口）——「写终态行时心跳写者必已
            # 停」的不变式严格成立，杜绝并发交错面。
            hb_alive = False
            if hb_thread is not None:
                hb_thread.join(timeout=10)
                hb_alive = hb_thread.is_alive()
            if result is not None:
                # 编年账 distill 行（add-knowledge-inbox-pipeline 4.2）：成功批
                # 已在 _run_batch_core 提交前置行随产出搭车落库（_log_written
                # 置位即跳过，不留独立 log 提交顶掉蒸馏提交的 HEAD 位），此处
                # 只兜底失败/异常/提交失败批——追加失败行并独立小提交保持
                # spec/knowledge/ 工作区干净。先于终态行收口并吞异常，保证
                # 终态行必为末行（读侧 classify_run 只看末行）。折叠行已由
                # 前置段按条先行落账。
                try:
                    self._log_distill_finish(proot, result)
                except Exception as exc:  # noqa: BLE001 — 留痕失败不吞终态行
                    logger.warning("knowledge-distill 批收尾留痕异常: %s", exc)
                if hb_alive:
                    logger.warning(
                        "knowledge-distill run 产物终态行让位（心跳线程 join 超时"
                        "仍在写盘），读侧 stale 兜底收口"
                    )
                else:
                    _distill_run_artifact_close(run_file, result)

    # ── inbox 折叠前置段（add-knowledge-inbox-pipeline 3.1/3.2）──────────

    def _fold_inbox_entries(self, proot: Path) -> dict:
        """逐条消化 `_inbox/` 存量（按条目顺序、每条独立提交可中断）。

        每条：独立 spawn 折叠 run（动态段注入条目路径，模板铁律/能力页契约
        照常约束）→ 实时 ``validate_knowledge``（落库前校验门，3.2）→ 通过
        即独立提交（fold 行随提交搭车落库）；run 失败或校验违规即回滚本条
        改动、条目滞留原地不丢弃，继续消化后续条目。

        Returns:
            ``{"folded": 成功数, "fold_failed": 失败数, "entries": [明细]}``。
        """
        summary = {"folded": 0, "fold_failed": 0, "entries": []}
        entries = inbox_entries(proot)
        if not entries:
            return summary
        logger.info("knowledge-distill 折叠前置段：_inbox 存量 %d 条", len(entries))
        # 基线违规集（code-review 0f35416b70b7）：落库门采用违规差集口径——
        # 折叠车道无修正轮，spec/knowledge/ 若存在与本次折叠无关的存量违规
        # （手工直改坏页、历史滞留半成品），全树口径会把每条候选的折叠 run
        # 都判违规回滚滞留、下轮重复失败，每轮蒸馏批前置段逐条白烧折叠 run
        # （ac8b82fa4a61「条目滞留被重复折叠白烧 run」同型浪费）。基线在候选
        # 循环前取样一次，落库门只拦本次折叠新增的违规；存量违规非本次折叠
        # 引入、不据此回滚，交由周期 audit 体检车道处置。
        baseline_violations = set(validate_knowledge(proot))
        for entry in entries:
            name = entry.name
            origin_rel = f"{KNOWLEDGE_DIR}/{INBOX_DIRNAME}/{name}"
            # 条目名含空白字符提前跳过（code-review ab4e8fd06373）：done/
            # 溯源路径要写进能力页 marker sources，而 _MARKER_FIELD_RE 取值为
            # \S+ 且 parse_marker 经 _marker_body_residue 把空格残片整体判
            # 非法——含空白的文件名结构上写不进 marker，每轮折叠 run 必判
            # 「marker 字段非法」回滚滞留、逐轮白烧（ac8b82fa4a61 同型）。
            # 这里拒绝消化并告警提示改名（条目滞留原地不丢弃，由积压提醒
            # 6.1 浮出催办），不在每轮折叠前置段反复烧 run。
            if re.search(r"\s", name):
                reason = (
                    "条目名含空白字符，溯源路径无法写入 marker sources"
                    "（请改名为 kebab-case 文件名）"
                )
                logger.warning(
                    "knowledge-distill 折叠前置段：条目 %s 名含空白字符，"
                    "跳过折叠滞留原地: %s",
                    name,
                    reason,
                )
                summary["fold_failed"] += 1
                summary["entries"].append(
                    {"entry": name, "ok": False, "reason": _log_subject_safe(reason, 200)}
                )
                continue
            try:
                snapshot = entry.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                logger.warning(
                    "knowledge-distill 折叠前置段：条目 %s 不可读（%s），"
                    "本轮跳过滞留原地",
                    name,
                    e,
                )
                summary["fold_failed"] += 1
                summary["entries"].append({"entry": name, "ok": False, "reason": "条目不可读"})
                continue
            # 基线快照（祖先折叠条目就地展开，code-review 86d88801917e）：本
            # 快照供 _commit_output 基线甄别与折叠失败回滚，首蒸场景快照含
            # 祖先折叠条目时事后展开会把折叠产出误充基线，与 run_baseline
            # 同根因同口径
            status_before = _knowledge_baseline_snapshot(proot)
            # 折叠 run 越界写面对账快照（code-review 8eee244da029，与
            # _run_batch_core 主蒸馏轮同口径）：折叠前置段 run 经同一
            # _spawn_and_wait（同 bypassPermissions 权限）直跑主树，spawn 前
            # 取 git status 快照，成功与回滚两条收尾路径各调 _audit_stray_writes
            # 对账留痕（只告警不回滚，防吞用户未提交改动）——条目内容提示注入
            # 后越界改写主树其他路径不得零 WARNING 静默。
            spawn_status_before = _git_status_paths(proot)
            # add-distill-run-work-summary：折叠子 run stdout 不进总结
            # （design Non-Goal，folded 计数语义不变），第三位丢弃
            ok, err, _fold_stdout = self._spawn_and_wait(
                proot, build_inbox_fold_prompt(proot, name)
            )
            violations = validate_knowledge(proot) if ok else None
            # 差集口径落库门（0f35416b70b7）：只拦基线之外的本次新增违规，
            # 存量违规不据此回滚滞留
            new_violations = (
                [v for v in violations if v not in baseline_violations]
                if violations
                else None
            )
            if ok and not new_violations:
                # 确定性折叠成功判据（code-review ac8b82fa4a61）：提示词第 4 步
                # 要求条目移入 done/。run 退出码 0 但条目未移动（完全空跑或折叠
                # 了能力页漏移动）时，validate_knowledge 对未变状态恒通过、
                # _commit_output 空串也算成功，条目会滞留 _inbox/ 被下一批前置段
                # 重复折叠（能力页 rev 反复膨胀、逐批白烧折叠 run）。此处断言
                # 移动确实发生，未满足按折叠失败走滞留回滚路径。
                if (proot / origin_rel).exists() or not (
                    proot / INBOX_DONE_PREFIX / name
                ).exists():
                    err = "折叠成功判据不满足：条目未移动到 done/（空跑或半完成 run）"
                else:
                    # fold 行先追加（随本条折叠提交搭车落库，4.2 顺序契约：
                    # 折叠轮先 fold 行后 distill 行）。追加失败（flock 内
                    # OSError，如磁盘满/权限）不阻断折叠提交，提交成功后照实
                    # 补写一行（code-review e03815c96a2d）。
                    fold_line_ok = append_knowledge_log(proot, "fold", f"{name} 折叠入库")
                    commit = _commit_output(
                        proot,
                        [name],
                        baseline=status_before,
                        msg=f"{COMMIT_PREFIX.replace('distill', 'fold')} {name}",
                    )
                    if commit is not None:
                        if not fold_line_ok:
                            # fold 行缺失补写：独立小提交（与失败批留痕同款
                            # 手法），补写仍失败 WARNING 兜底留痕
                            if not append_knowledge_log(
                                proot,
                                "fold",
                                f"{name} 折叠入库（前置行追加失败，收尾补写）",
                            ):
                                logger.warning(
                                    "knowledge-distill 折叠编年账 fold 行补写仍失败"
                                    "（%s），本条折叠在编年账缺行",
                                    name,
                                )
                            _commit_log_line(proot, f"fold {name} 补写留痕")
                        summary["folded"] += 1
                        summary["entries"].append({"entry": name, "ok": True})
                        logger.info(
                            "knowledge-distill 折叠入库：%s（commit=%s）",
                            name,
                            commit or "无变更",
                        )
                        _audit_stray_writes(proot, spawn_status_before, name)
                        continue
                    err = "校验通过但自动提交失败"
            reason = err or "；".join(new_violations[:3])
            self._rollback_failed_fold(proot, status_before, name, snapshot, origin_rel)
            _audit_stray_writes(proot, spawn_status_before, name)
            append_knowledge_log(
                proot, "fold", f"{name} 折叠失败滞留：{_log_subject_safe(reason, 120)}"
            )
            _commit_log_line(proot, f"fold {name} 失败留痕")
            summary["fold_failed"] += 1
            summary["entries"].append(
                {"entry": name, "ok": False, "reason": _log_subject_safe(reason, 200)}
            )
            logger.warning(
                "knowledge-distill 折叠失败（%s），条目滞留原地待下轮重试: %s",
                name,
                _log_subject_safe(reason, 200),
            )
        return summary

    def _rollback_failed_fold(
        self, proot: Path, before, name: str, snapshot: str, origin_rel: str
    ) -> None:
        """折叠失败回滚：页面/落点恢复 + 条目原位恢复（滞留原地语义）。

        条目原位路径经 ``exclude`` 剔除出基线甄别（移动是任务语义非用户策展），
        ``done/`` 落点按 produced 集清理（untracked clean / tracked restore）；
        条目原位内容从快照恢复（未被移动时覆盖掉 run 内的原位改写）。回滚
        未确认时 WARNING 留痕交人工，与蒸馏放弃产出同一口径。
        """
        discarded = _discard_output(proot, before, exclude={origin_rel})
        origin = proot / origin_rel
        try:
            current = origin.read_text(encoding="utf-8") if origin.exists() else None
        except (OSError, UnicodeDecodeError):
            current = None
        if current != snapshot:
            try:
                origin.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_text(origin, snapshot)
            except OSError as e:
                logger.warning(
                    "knowledge-distill 折叠失败回滚：条目 %s 原位恢复失败: %s",
                    name,
                    e,
                )
        if not discarded:
            logger.warning(
                "knowledge-distill 折叠失败回滚未确认（%s），spec/knowledge/ "
                "可能残留半成品，请人工核查",
                name,
            )

    def _log_distill_finish(self, proot: Path, result: dict) -> None:
        """批收尾编年账 distill 行兜底（4.2）：daemon 代码侧留痕，fail-open。

        成功批由 ``_run_batch_core`` 在 ``_commit_output`` 前置行随产出提交
        搭车（经 pop 识别 ``_log_written`` 后跳过，避免独立 log 提交改变
        HEAD）；本方法兜底失败/异常/提交双失败批（追加失败行）与成功批前置
        行追加失败（code-review e03815c96a2d，措辞照实不冒充失败行）——均
        独立小提交，保持 spec/knowledge/ 工作区干净。
        """
        piggybacked = result.pop("_log_written", False)
        if piggybacked:
            return
        if result.get("ok"):
            subject = (
                f"{result.get('names', '')} 成功（前置 distill 行追加失败，收尾补写）"
            )
        else:
            subject = f"{result.get('names', '')} 失败：{result.get('error') or '未知原因'}"
        if append_knowledge_log(proot, "distill", subject):
            _commit_log_line(proot, f"distill {result.get('names', '')}")

    def _run_batch_core(
        self, proot: Path, archived_names: list, run_file: "Path | None"
    ) -> dict:
        names = ", ".join(archived_names)
        # 折叠前置段（add-knowledge-inbox-pipeline 3.1，piggyback-only）：每轮
        # distill 先消化 `_inbox/` 存量再蒸当轮 SPEC。挂点在批级 flock 单写者
        # 之内（_run_with_lock → _run_batch → 本方法），与队列台账单写者
        # （ADR-234）兼容，不引入双写者（3.2）；`_inbox` 非空不构成独立派发
        # 条件——本段只在已有蒸馏批内执行，无 fold-only run 形态。
        fold = self._fold_inbox_entries(proot)
        prompt = build_distill_prompt(proot, archived_names)
        violations = None
        result = {
            "ok": False,
            "names": names,
            "rounds": 0,
            "commit": None,
            "error": None,
            "folded": fold.get("folded", 0),
            "fold_failed": fold.get("fold_failed", 0),
        }

        # 批次级 run 前基线快照（code-review 4d1e46fa795c）：放弃产出时据此
        # 判别 spec/knowledge/ 下哪些改动是用户 run 前既有的未提交改动，避免
        # 整目录回滚吞掉手工策展；成功收尾时同快照供 _commit_output 做提交
        # 基线甄别（仅收纳本轮新增路径，code-review 50251dbfd0c1）。逐轮快照
        # （status_before）仍供越界对账。祖先折叠条目（首蒸项目 spec/ 全树
        # 未跟踪折叠为 "spec/"）在快照时刻就地展开为文件级集合（code-review
        # 86d88801917e）：事后展开发生在 run 结束后，会把已在盘上的蒸馏产出
        # 自身充作基线（run_new 差集恒空 → 按「无变更」成功收尾并清 pending
        # 台账，产出滞留永不落库；overlap 恒非空 → 放弃路径误跳过回滚），
        # 此刻产出尚未写入，枚举即真实基线。
        run_baseline = _knowledge_baseline_snapshot(proot)

        for round_no in range(1 + self._max_fix_rounds):
            result["rounds"] = round_no + 1
            if round_no > 0:
                # 修正轮：把违规清单回反馈给 run（design D2）
                prompt = build_distill_prompt(proot, archived_names) + (
                    "\n\n## 上一轮校验违规（必须逐条修正后重写相关文件）\n\n"
                    + "\n".join(f"- {v}" for v in violations)
                    + "\n"
                )
            status_before = _git_status_paths(proot)
            # add-distill-run-work-summary 1.1：第三位承接裸文本 stdout
            # （主蒸馏工作总结数据源，仅成功轮有效）
            ok, err, spawn_stdout = self._spawn_and_wait(proot, prompt)
            # add-distill-run-artifacts 1.1：批内单轮收尾 round 行（修正轮是
            # 同一派发的内部重试，不另开产物；产物行数随修正轮数递增）。
            _distill_run_artifact_round(
                run_file, result["rounds"], ok, len(violations) if violations else 0
            )
            if not ok:
                result["error"] = err
                self._give_up(proot, archived_names, f"run 失败: {err}", before=run_baseline)
                _audit_stray_writes(proot, status_before, names)
                return result
            violations = validate_knowledge(proot)
            if not violations:
                # distill 行随产出提交搭车落库（add-knowledge-inbox-pipeline
                # 4.2）：先写 log.md 再 _commit_output（baseline 甄别把 log.md
                # 收进本提交），不留独立 log 提交顶掉蒸馏提交的 HEAD 位；行内
                # 不落 commit 摘要（写入时 hash 未定，git 历史相邻可查）。
                extra = f"，折叠入库 {result['folded']} 条" if result["folded"] else ""
                # 按返回值置位（code-review e03815c96a2d）：追加失败（flock 内
                # OSError，如磁盘满/权限）时保持缺省，交 _log_distill_finish 收
                # 尾统一补写——编年账 4.1「每轮收尾恒有一行」不被静默吞掉。
                result["_log_written"] = append_knowledge_log(
                    proot,
                    "distill",
                    f"{names}（第 {result['rounds']} 轮，自动提交落库{extra}）",
                )
                commit = _commit_output(proot, archived_names, baseline=run_baseline)
                if commit is None:
                    # 提交失败当轮重试一次（index.lock 撞车等瞬态失败常可恢复）；
                    # 锁持有方通常毫秒到秒级才释放，零间隔重试命中率极低，先短
                    # 退避再重试（code-review 06141f417790）
                    time.sleep(1.0)
                    commit = _commit_output(proot, archived_names, baseline=run_baseline)
                if commit is not None:
                    result["ok"] = True
                    result["commit"] = commit
                    # add-distill-run-work-summary 1.3：主蒸馏工作总结装配
                    # （剥 KNOWLEDGE_DISTILL_DONE 标记 + 截断归一）；空串
                    # 不写键——产物/台账行为与现状一致，读侧按字段缺失渲染
                    summary = _extract_distill_summary(spawn_stdout)
                    if summary:
                        result["summary"] = summary
                    # R2：成功收尾（commit 含空串=无变更可提交）即移除 pending
                    # 条目——按本批 names 并集一次清除（合并批次防漏清陈旧条目）
                    self._ledger_remove(proot, archived_names)
                    logger.info(
                        "knowledge-distill 完成（%s，第 %d 轮，commit=%s）",
                        names,
                        round_no + 1,
                        commit or "无变更",
                    )
                    _audit_stray_writes(proot, status_before, names)
                    return result
                # 重试仍失败：产出已通过校验但未落库。不能标 ok=True 让它
                # 无台账滞留工作区——后续任一批 _give_up 的 _discard_output
                # 会把它连带回滚（code-review 0f5f648d54f4 静默丢失链）；
                # 登台账留痕，保持「未落库」状态由人工/重试兜底。
                result["error"] = "校验通过但自动提交失败（产出滞留工作区未落库）"
                # 清搭车 flag：前置的 distill 行（措辞「自动提交落库」）已随
                # 产出滞留 dirty log.md，交 finally 兜底追加失败行并独立提交
                # ——纠正行紧随其后落库，账面自洽（罕见瞬态路径，index.lock
                # 持续占用等）。
                result["_log_written"] = False
                logger.warning(
                    "knowledge-distill 校验通过但自动提交失败（%s），产出滞留"
                    "工作区未落库，已登重试台账",
                    names,
                )
                _register_todo_retry(
                    proot,
                    archived_names,
                    "校验通过但自动提交失败，产出滞留工作区未落库"
                    "（请人工提交；注意后续放弃产出的清理会回滚工作区；"
                    f"{_RESUME_TAKEOVER_NOTE}）",
                )
                _audit_stray_writes(proot, status_before, names)
                return result
            logger.warning(
                "knowledge-distill 校验违规（%s，第 %d 轮）：%s",
                names,
                round_no + 1,
                "; ".join(violations[:5]),
            )

        # 修正轮耗尽仍违规 → 放弃产出（rounds 为含首轮的总 run 次数）
        self._give_up(
            proot,
            archived_names,
            "校验违规经 %d 轮 run 仍未通过" % (result["rounds"]),
            before=run_baseline,
        )
        _audit_stray_writes(proot, status_before, names)
        result["error"] = "校验违规未通过"
        return result

    def _spawn_and_wait(self, proot: Path, prompt: str) -> tuple:
        """spawn 一轮 claude -p 并等待结束（硬超时 killpg）。

        Returns:
            (ok, error, stdout)：ok=True 进程已退出且退出码 0（产物合法性交
            校验脚本）；stdout=裸文本最终消息原文（add-distill-run-work-summary
            1.1，主蒸馏工作总结数据源；失败路径第三位恒 None）。
        """
        # evo-distill-model-name-fallback 1.1：spawn 恒传显式裸模型名（取
        # knowledge.model 配置；未配置/非法/空值回退现行为不传名并告警——
        # 告警在 ConfigLoader 读取器内），隔离宿主 ANTHROPIC_DEFAULT_*_MODEL
        # 别名毒化。1.2：非零退出且 stderr 命中 unrecognized_model 时，仅当
        # 本次未显式传名（生效名是宿主别名解析产物）且能从报错派生出与生效名
        # 不同的裸模型名，才以该裸名自动重试一次；显式传名仍被拒为确定性失败
        # （同因重试必然再拒），不重试。重试收拢在本方法内（对外仍是单一
        # (ok, err)），上游 give_up→登台账路径天然不重复登记。
        model = _spawn_model_from_config(proot)
        ok, err, stdout = self._spawn_once(proot, prompt, model)
        if ok:
            return True, None, stdout
        if not _stderr_hits_unrecognized_model(err or ""):
            return False, err, None
        # 拒识形态命中：无论是否重试，收场 error（随 give_up 进 todo.md 台账
        # reason）恒注明拒识形态与生效模型名——stderr 尾部截断后该事实不丢失。
        rejected = _extract_rejected_model(err or "")
        if model is not None:
            # 显式传名（含配置名）仍被拒：网关侧确定性拒识（provider_circuit
            # 既有结论：同一模型名再试必然再拒；MERGE-NOTES 2026-10-30 裸名
            # 形态先例），MUST NOT 同因重试，直接按终态收场。
            return False, (
                f"{err}；拒识形态 unrecognized_model（生效模型名 {model}，"
                "显式传名仍被拒属确定性失败），不重试"
            ), None
        bare = _bare_model_name(rejected) if rejected else None
        if bare:
            logger.warning(
                "knowledge-distill run 死于 unrecognized_model（生效模型名"
                " %s 疑为宿主别名解析产物），以裸模型名 %s 自动重试一次",
                rejected,
                bare,
            )
            ok_retry, err_retry, stdout_retry = self._spawn_once(proot, prompt, bare)
            if ok_retry:
                logger.info(
                    "knowledge-distill 以裸模型名 %s 重试成功", bare
                )
                return True, None, stdout_retry
            return False, (
                f"{err_retry}；拒识形态 unrecognized_model：首次拒识（生效模型"
                f"名 {rejected}）后已以裸模型名 {bare} 自动重试一次仍失败"
            ), None
        # 裸名形态（生效名已无可剥别名后缀）或未能提取生效名：同因重试
        # 必然再拒，直接按终态收场；reason 注明拒识形态与生效模型名。
        return False, (
            f"{err}；拒识形态 unrecognized_model（生效模型名 "
            f"{rejected or '未知'}），无可用更裸模型名可兜底，不重试"
        ), None

    def _spawn_once(self, proot: Path, prompt: str, model: "str | None") -> tuple:
        """单次 spawn claude -p 并等待结束（``model``=本次显式传名；None=不传）。

        Returns:
            (ok, error, stdout)：成功第三位为裸文本 stdout 原文
            （add-distill-run-work-summary 1.1）；失败路径第三位恒 None。
        """
        # 收编进 harness.run_one_shot（add-harness-adapter-layer 4.1）：claude
        # 命令构造唯一入口在 claude_adapter.build_spawn_spec——提示词经 stdin
        # 传入（SpawnRequest 缺省传输形态；不走 argv：argv 全文驻留
        # /proc/<pid>/cmdline 对同机其他用户可见，且单参数受 MAX_ARG_STRLEN
        # ≈128KB 约束）。超时清场回调传自有 _kill_process_group（直 SIGKILL+
        # 弃管道语义保持）；spawn 注入缝 self._spawn 保持（测试替身经
        # DistillManager(spawn=...) 注入 Popen 级替身）。
        def _popen(argv, **kwargs):
            # env 透传（code-review item 8c9e46ed49c2）：run_one_shot 按契约把
            # build_spawn_spec 依据 env_mode（此处 ENV_MODE_CLEAN）算出的 env
            # 经 popen kwargs 传入，垫片原先丢弃全部额外参数，清洁环境声明被
            # 静默忽略、实际回落 _default_spawn 的全量 os.environ 拷贝减禁用键。
            return self._spawn(argv, cwd=str(proot), env=kwargs.get("env"))

        try:
            outcome = run_one_shot(
                ClaudeAdapter(),
                SpawnRequest(
                    prompt=prompt,
                    cwd=str(proot),
                    # 现状形态无 --output-format（裸文本 stdout 留痕），显式
                    # None 压掉 SpawnRequest 的 stream-json 缺省
                    output_format=None,
                    # evo-distill-model-name-fallback 1.1：显式裸模型名经既有
                    # SpawnRequest.model→claude_adapter --model 透传链路下发；
                    # None = 不传 flag（回退现行为，生效名由 CLI 按别名解析）
                    model=model,
                    permission_mode="bypassPermissions",
                    env_mode=ENV_MODE_CLEAN,
                    project_root=str(proot),
                ),
                timeout=RUN_TIMEOUT_SECONDS,
                popen=_popen,
                on_timeout=_kill_process_group,
            )
        except OneShotCommunicateError as e:
            return False, f"claude 进程通信失败: {e.original}", None
        except Exception as e:  # noqa: BLE001 — CLI 不存在等 spawn 失败
            return False, f"调用 claude CLI 失败: {e}", None
        if outcome.timed_out:
            return False, f"run 超时（>{RUN_TIMEOUT_SECONDS}s），已终止进程组", None
        stdout, stderr = outcome.stdout, outcome.stderr
        if outcome.returncode != 0:
            # 失败诊断：stdout/stderr 摘要进日志，stderr 尾部随 error 一路进
            # todo.md 台账 reason（否则蒸馏失败排障拿不到 claude 的报错，
            # code-review 0d6683c2b68d）。
            stdout_tail = (stdout or "").strip()[-500:]
            stderr_tail = (stderr or "").strip()[-500:]
            logger.warning(
                "knowledge-distill run 非零退出（exit=%s）stdout 摘要: %s | stderr 摘要: %s",
                outcome.returncode,
                stdout_tail[:200] or "（空）",
                stderr_tail[:200] or "（空）",
            )
            detail = f"；stderr 尾部: {stderr_tail}" if stderr_tail else ""
            return (
                False,
                f"claude 进程非零退出（exit={outcome.returncode}）{detail}",
                None,
            )
        return True, None, stdout

    def _give_up(self, proot: Path, archived_names: list, reason: str, before=None) -> None:
        """放弃产出：清理半成品 + 登重试台账（``before`` = run 前基线快照）。"""
        discarded = _discard_output(proot, before)
        if discarded:
            # R2：清理确认（_discard_output=True）后 pending 条目即移除——
            # 该批已诚实收尾（无产出），重启续跑无意义
            self._ledger_remove(proot, archived_names)
            _register_todo_retry(proot, archived_names, reason)
            logger.warning(
                "knowledge-distill 放弃产出（%s）: %s；已清理 spec/knowledge/ 半成品并登重试台账",
                ", ".join(archived_names),
                reason,
            )
        else:
            # code-review 37565545ea29：回滚未确认（保守跳过 / restore、clean
            # 失败 / 残留复查不可用或仍有残留）时，台账 reason 同步带上该口径，
            # 人工排查不会误以为工作区已清理干净。
            # R2/design D2：pending 条目保留——工作区可能有残留半成品，重启
            # 续跑让校验链重新裁决比留死条目诚实。
            _register_todo_retry(
                proot,
                archived_names,
                f"{reason}（spec/knowledge/ 回滚未确认，半成品滞留工作区，"
                f"请人工核查；{_RESUME_TAKEOVER_NOTE}）",
            )
            logger.warning(
                "knowledge-distill 放弃产出（%s）: %s；spec/knowledge/ 回滚未确认"
                "（保守跳过或 git 清理失败，详见前序告警），半成品滞留工作区"
                "请人工核查，已登重试台账",
                ", ".join(archived_names),
                reason,
            )

    # ── daemon 启动恢复（evo-knowledge-distill-resume-guard R3，design D3）─
    def recover_pending(self, proot: Path) -> int:
        """重启恢复：读 pending 台账 → **先清空台账** → 逐条重派，返回恢复数。

        顺序 MUST 为「先清空后入队」：台账写点收在 dispatch 单点（R1），恢复
        重派本身会把门控放行的条目重新落盘；若先入队后清空，清空会把刚重写
        的条目一并抹掉，恢复 run 期间台账裸奔（此时崩溃即重演本 SPEC 要修的
        批次丢失）。先清空后：门控放行条目由 R1 立即重新落盘（生命周期交 R2
        接管——收尾前始终在册，运行中崩溃可再次恢复）；门控拒绝条目（归档
        目录缺失/disabled/回填期排队）随清空消失、不复活。清空与逐条重派之间
        的残差窗口（毫秒级）与读损坏 fail-open 同口径，不为该窗口引入跨文件
        事务。

        仅由 daemon 启动路径调用（dashboard --serve 不接入，避免双进程竞争）。
        本方法不执行蒸馏——实际 run 仍走既有 flock 单飞与 worker 串行消费。

        Returns:
            恢复重派的批次数（门控拒绝与派发失败条目不计）。
        """
        proot = Path(proot)
        batches = _read_pending_ledger(proot)
        if not batches:
            return 0
        try:
            # 清空写点持跨进程 flock（code-review 4bba473fbc23）：裸写空表若落
            # 在 dashboard --serve 侧持锁 _ledger_append 的重读与回写之间，刚落
            # 盘的批次条目会被 {"batches": []} 整文件覆盖丢失（进程随后崩溃即
            # 重演 R1 要防的批次重启蒸发）。与 _ledger_append/_ledger_remove 已
            # 确立的写纪律对齐：持锁重读盘上最新台账再回写空表，窗口内新到的
            # 条目并入下方逐条重派。
            with _pending_ledger_lock(proot):
                batches = _read_pending_ledger(proot)
                if batches:
                    _write_pending_ledger(proot, [])
        except Exception as e:  # noqa: BLE001 — 清空失败则放弃恢复（避免裸奔放大）
            logger.warning(
                "knowledge-distill 恢复放弃（pending 台账清空失败，"
                "避免恢复期台账裸奔）: %s",
                e,
            )
            return 0
        recovered = 0
        labels = []
        for item in batches:
            names = list(item.get("names") or [])
            if not names:
                continue
            gated = _gate_distill(proot, names)
            if gated is not None:
                logger.info(
                    "knowledge-distill 恢复跳过（%s）: %s",
                    ", ".join(names),
                    gated.get("reason"),
                )
                continue
            # 门控放行：经既有派发壳重入队（R1 写点随即把条目重新落盘）。
            # 派发失败（_dispatch_via_mgr except 分支）已登 todo 重试台账兜底，
            # 此处不计数——与运行期派发失败既有口径一致。
            res = _dispatch_via_mgr(self, proot, names)
            if res.get("dispatched"):
                recovered += 1
                labels.append(", ".join(names))
        if recovered:
            logger.info(
                "knowledge-distill 恢复重派（%d 批：%s）", recovered, "; ".join(labels)
            )
        return recovered


# 进程内单例（daemon / dashboard --serve 各进程一份；跨进程由 flock 兜底互斥）
_MANAGER = DistillManager()


def _get_dispatcher() -> DistillManager:
    return _MANAGER


def _gate_distill(proot: Path, archived_names: list, config=None) -> dict | None:
    """单条/批量派发共用的门控链（enabled → 蒸馏源目录存在 → 回填期排队）。

    双入口共用同一实现，避免门控规则漂移出现单条/批量行为不一致
    （code-review f58075519410）。目录存在性为双态解析（move-distill-
    trigger-to-push D2）：``spec/changes/<名>`` 优先、``spec/archive/<名>``
    兜底（push 后 3 天内失败的批恢复重派时可能已归档）。

    Returns:
        None = 全部放行；否则返回 ``{"dispatched": False, "reason": ...}``。
    """
    # knowledge.enabled 门控（task 1.1 读取器单源）
    try:
        from core.config import ConfigLoader

        effective = config
        if effective is None:
            effective = ConfigLoader.resolve_config(proot)
        if not ConfigLoader.get_knowledge_config(effective or {})["enabled"]:
            return {"dispatched": False, "reason": "disabled"}
    # 配置解析失败按禁用处理：对本车道是保守不派发（fail-closed，非降级放行
    # 的 fail-open）；归档主流程不受影响（code-review 6104aea75dbd 正名）。
    except Exception as e:  # noqa: BLE001
        logger.warning("knowledge-distill 配置解析失败，跳过派发: %s", e)
        return {"dispatched": False, "reason": f"config-error: {e}"}

    # 蒸馏源目录存在性（双态：changes/ 优先、archive/ 兜底——move-distill-
    # trigger-to-push D2）。防御（code-review b00585e3c85b）：蒸馏源名须为
    # 单一一路径成分——含路径分隔符或为 . / .. 时，存在性检查与蒸馏上下文
    # 拼出的路径会越出目录，一律按缺失拒绝。NUL 字节同列（code-review
    # 670ba45b05de）：Linux 文件名无法含 \x00，正常 SPEC 目录名到不了该
    # 状态、仅手工编辑过的 pending 台账可带入（_read_pending_ledger 只按
    # 非空 str 过滤），放行会在 _distill_source_dir 的 is_dir() 上抛
    # ValueError（embedded null byte）穿透恢复/派发链——判定置于双态解析
    # 之前（短路求值保证不触发解析），与目录缺失同一条拒绝路径。
    missing = [
        n
        for n in archived_names
        if not n
        or n in (".", "..")
        or os.sep in n
        or "/" in n
        or "\x00" in n
        or _distill_source_dir(proot, n) is None
    ]
    if missing:
        # reason 保留既有 archive-dir-missing 字面量兼容既有消费方（解析该
        # 值的台账/测试/文案）；双态说明走日志文案以资区分（两态均无目录
        # 才会到这，字面量本身是历史名）。
        logger.info(
            "knowledge-distill 拒绝派发（蒸馏源目录双态均缺失：changes/ 与 "
            "archive/ 均无该 SPEC 目录）: %s",
            ", ".join(missing),
        )
        if len(archived_names) == 1:
            return {"dispatched": False, "reason": "archive-dir-missing"}
        return {
            "dispatched": False,
            "reason": f"archive-dir-missing: {', '.join(missing)}",
        }

    # 回填期排队（fix-knowledge-backfill-reconstruction 3.1）：台账存在 pending
    # 时不派发增量 run，把归档登记进回填台账后返回——回填期 spec/knowledge/
    # 只有回填一个写者；收敛（台账无 pending）后此门自然放行，恢复即时派发。
    # 排队判定/登记故障 fail-open 放行原派发（不阻塞归档主流程）。
    try:
        if ledger_has_pending(proot):
            for name in archived_names:
                register_archive_pending(proot, name)
            label = (
                archived_names[0]
                if len(archived_names) == 1
                else "批量 " + ", ".join(archived_names)
            )
            logger.info("knowledge-distill 回填期排队（%s 登记回填台账）", label)
            return {"dispatched": False, "reason": "backfill-queued"}
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "knowledge-distill 回填排队判定失败，按即时派发继续: %s: %s",
            type(e).__name__,
            e,
        )
    return None


def _dispatch_via_mgr(mgr: DistillManager, proot: Path, names: list) -> dict:
    """派发壳层（单条/批量入口共用；code-review bc32bfabd7d9）。

    ``mgr.dispatch`` + 成功日志 + 失败 warning/登重试台账在单点维护，消除
    单条/批量两车道的观测与处置漂移（此前批量成功路径无任何成功日志、失败
    日志缺异常类型）；``names`` 由调用方传新拷贝。测试环境守卫
    （``_in_pytest``）留在各入口门控链之前——守卫先于门控是既有行为
    （替身注入语境不做配置解析/回填登记等副作用）。
    """
    label = names[0] if len(names) == 1 else "批量 " + ", ".join(names)
    try:
        mgr.dispatch(proot, names)
        logger.info("knowledge-distill 已派发（archive=%s）", label)
        return {"dispatched": True, "reason": None}
    except Exception as e:  # noqa: BLE001 — fail-open：不影响归档返回值
        logger.warning(
            "knowledge-distill 派发失败（archive=%s）: %s: %s",
            label,
            type(e).__name__,
            e,
        )
        _register_todo_retry(proot, names, f"派发失败: {e}")
        return {"dispatched": False, "reason": f"error: {e}"}


def dispatch_distill(project_root, archived_name, config=None, *, dispatcher=None) -> dict:
    """蒸馏派发入口（move-distill-trigger-to-push 1.1；approve_push 单点挂载）。

    Args:
        project_root: 项目根目录
        archived_name: 蒸馏源名（形参名保留不改，见 build_distill_prompt
            docstring）：push 触发时代 = ``spec/changes/<名>`` 的 SPEC 名；
            恢复重派兜底 = ``spec/archive/<日期-名>`` 的目录名（软删除路径
            的 ``<名>-<Unix秒>`` 同样兼容）——门控按双态解析，两态均放行。
        config: 有效配置 dict；None 时经 ``ConfigLoader.resolve_config``
            现场解析（派发低频，解析成本可接受）
        dispatcher: 注入替身（测试隔离用；None = 进程内单例）

    Returns:
        {"dispatched": bool, "reason": str|None}：
        - dispatched=True：已入队后台 run（结果经日志与 todo.md 观察）；
        - False：reason ∈ disabled / config-error:<...> / archive-dir-missing /
          backfill-queued / test-environment / error:<...>。
    """
    if _in_pytest() and dispatcher is None:
        # 测试环境守卫（task 2.3 测试隔离）：替身注入时绕开本守卫
        return {"dispatched": False, "reason": "test-environment"}

    proot = Path(project_root)
    gated = _gate_distill(proot, [archived_name], config)
    if gated is not None:
        return gated

    return _dispatch_via_mgr(dispatcher or _get_dispatcher(), proot, [archived_name])


# 兼容批量入口：auto_archive_check 一轮归档多条时可合并为一次批量 run
def dispatch_distill_batch(project_root, archived_names: list, config=None, *, dispatcher=None) -> dict:
    """批量派发（多条归档合并为一次 run，spec「实现裁量」）。

    当前仅测试消费（code-review 5d6705c37989）：docstring 所述
    auto_archive_check 批量合并接线未发生，生产代码零调用方；单条/批量
    行为一致性由共用的 _gate_distill / _dispatch_via_mgr 与测试锁定。
    """
    if not archived_names:
        return {"dispatched": False, "reason": "empty"}
    if len(archived_names) == 1:
        return dispatch_distill(project_root, archived_names[0], config, dispatcher=dispatcher)
    if _in_pytest() and dispatcher is None:
        return {"dispatched": False, "reason": "test-environment"}
    proot = Path(project_root)
    gated = _gate_distill(proot, list(archived_names), config)
    if gated is not None:
        return gated
    return _dispatch_via_mgr(
        dispatcher or _get_dispatcher(), proot, list(archived_names)
    )
