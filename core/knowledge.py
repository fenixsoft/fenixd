"""core/knowledge.py — 项目知识真相源（add-knowledge-atlas）。

蒸馏管线核心，三块职责：

1. **确定性收尾校验** ``validate_knowledge``（非 LLM）：对 ``spec/knowledge/``
   逐条契约对账——能力页 marker 可解析、sources 指向真实归档目录、单页
   150 行硬顶、index/_domain/adr 链接可解析且不越界、ADR 三段式与不可变性
   （tracked ADR 正文与 HEAD diff）、Superseded by 指向存在条目。返回违规
   字符串列表，空列表 = 通过。

2. **派发入口** ``dispatch_distill``：归档移动成功后由
   ``core/archive_commit.commit_archive_move`` 单点调用（双路径共同漏斗）。
   ``knowledge.enabled`` 门控、归档目录存在性检查、fail-open（异常只记日志
   与重试台账，不影响归档返回值）。测试环境（PYTEST_CURRENT_TEST）恒不
   派发——既有单测直接调用 commit_archive_move 不得触发真实蒸馏（task 2.3
   测试隔离；替身经 dispatcher 参数注入）。

3. **执行器** ``DistillManager``（进程内单例 + 跨进程 flock 单飞）：后台
   线程 spawn ``claude -p``（cwd 主树、注入 core/knowledge_prompts/distill.md
   提示词），run 结束跑 validate_knowledge，违规回反馈修正（≤2 轮），通过后
   pathspec 限定 ``spec/knowledge/`` 自动提交；修正轮耗尽仍违规则放弃产出
   （``git restore`` + 清理未跟踪新增，不留半成品）；失败登 todo.md 重试
   台账。同 project 归档事件在队列中串行，积压条目合并为一次批量 run。

写路径限定 ``spec/knowledge/`` 一个目录（design D2 爆炸半径可控）；主树直跑
（spec 元数据层非产品代码，无 merge-back）。该写面约束除提示词承载外，run
前后还对主树做 ``git status`` 越界写面对账：合法写面之外的新增改动记 WARNING
留痕、不自动回滚（主树是用户工作区，restore 会吞掉用户未提交改动）。
"""

from __future__ import annotations

import json
import logging
import os
import re
import signal
import subprocess
import threading
import time
import urllib.parse
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

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
from core.knowledge_backfill import (
    append_todo_line,
    atomic_write_text,
    ledger_has_pending,
    register_archive_pending,
)
from core.timelib import now_local
from core.proc_utils import guard_killpg

logger = logging.getLogger("fenixd.knowledge")

# ── 路径与契约常数 ────────────────────────────────────────────────────

KNOWLEDGE_DIR = "spec/knowledge"
ARCHIVE_DIR = "spec/archive"
PROMPT_FILE = "knowledge_prompts/distill.md"  # 相对 core/ 包

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
_INDEX_TABLE_HEADER = "| 能力域 | 简介 | 能力数量 | 更新时间 |"
_DOMAIN_TABLE_HEADER = "| 能力页 | 简介 | 更新时间 |"


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

# ADR 文件名与头部状态
_ADR_NAME_RE = re.compile(r"^ADR-(\d{3})-.+\.md\Z")  # 结尾锚 \Z 同 _KEBAB_RE
_ADR_STATUS_RE = re.compile(r"^status:\s*(accepted|superseded)\s*$", re.M)
_SUPERSEDED_BY_RE = re.compile(r"Superseded by:\s*ADR-(\d{3})")
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

    蒸馏派发是归档动作的自动副作用，MUST NOT 在单测里 spawn 真实 claude；
    替身经 dispatcher 参数注入（完全绕开本守卫），本守卫只防「测试直接调
    commit_archive_move / dispatch_distill 未注入替身」的误触发。
    """
    return "PYTEST_CURRENT_TEST" in os.environ


# ── marker 解析 ──────────────────────────────────────────────────────

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
    fields = dict(_MARKER_FIELD_RE.findall(m.group(1)))
    capability = fields.get("capability")
    rev_raw = fields.get("rev")
    sources_raw = fields.get("sources")
    if not capability or not rev_raw or not sources_raw:
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
    """读 HEAD 版本文件内容；非 git / 未跟踪 / 失败 → None（跳过 diff 检查）。"""
    try:
        # encoding/errors 固化（与 _git 同口径，code-review 0f9cddb901b2）：裸
        # text=True 走 locale 编码 + strict 解码，HEAD blob 含非 UTF-8 字节时抛
        # UnicodeDecodeError（ValueError 而非 OSError），穿透调用方 except 捕获
        # 口径并中断整个 validate_knowledge。替换字符不会造成不可变性比对误报：
        # 工作区侧在 validate_knowledge 中已按 strict utf-8 读取（失败即记违规
        # 并跳过该 ADR），能到达比对的两侧文本若不一致即真实字节差异。
        r = subprocess.run(
            ["git", "show", f"HEAD:{rel_path}"],
            cwd=str(proot),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    return r.stdout


def _git_ref_resolvable(proot: Path, ref: str) -> bool:
    """史前锚点起始 ref 可解析（``git cat-file -e <ref>^{commit}``）。

    非 git 目录 / ref 不存在 / 超时 → False（由调用方报违规）。
    """
    try:
        r = subprocess.run(
            ["git", "cat-file", "-e", f"{ref}^{{commit}}"],
            cwd=str(proot),
            capture_output=True,
            text=True,
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
        for m in _LINK_RE.finditer(scrubbed):
            target = m.group(1)
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            path_part = target.split("#", 1)[0]
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
            # 尖括号完整包裹（code-review item 619958a1e296，对齐兜底通道
            # cc2ca6fe60b1 的合法形态放行）：_LINK_RE 捕获组不排除尖括号，
            # [x](<file.md>) 会按含尖括号的路径做解析与存在性检查、必然误报
            # 「链接目标不存在」；严格通道同样剥离成对尖括号包裹后再解析，
            # 两通道对该合法形态裁决一致。
            if (
                len(path_part) >= 2
                and path_part.startswith("<")
                and path_part.endswith(">")
            ):
                path_part = path_part[1:-1]
                if not path_part:
                    continue  # <> 空包裹按纯页内锚点同口径跳过
            resolved = (rel_dir / path_part).resolve()
            try:
                resolved.relative_to(kroot.resolve())
            except ValueError:
                violations.append(f"{label}: 链接越出真相源目录: {target}")
                continue
            if not resolved.exists():
                violations.append(f"{label}: 链接目标不存在: {target}")

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
            # <目标> 尖括号完整包裹为合法 markdown 形态（code-review
            # cc2ca6fe60b1）：此类目标正含空格/括号才落到本兜底，按报错文案
            # 承诺放行，不再判格式违规。_LINK_LOOSE_RE 原样捕获尖括号，此处
            # 只放行不参与后续检查，无去括号需求。
            if target.startswith("<") and target.endswith(">"):
                continue
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            violations.append(
                f"{label}: 链接目标格式非法（含空格或未转义括号，须 %20 转义"
                f"或 <目标> 尖括号包裹）: {target}"
            )

    # ── 能力页（domains/<域>/<能力>.md，_domain.md 为导航层另行处理）──
    domains_dir = kroot / "domains"
    if domains_dir.is_dir():
        for page in sorted(domains_dir.rglob("*.md")):
            rel = page.relative_to(kroot)
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
                lines = text.splitlines()
                # 更新时间盖戳：紧随 H1（第 2 行），格式 `> 最后更新：YYYY-MM-DD HH:MM UTC+8`
                if len(lines) < 2 or not _STAMP_LINE_RE.match(lines[1]):
                    violations.append(
                        f"{label}: 缺少「最后更新」盖戳行或未紧随 H1"
                        "（应形如 > 最后更新：YYYY-MM-DD HH:MM UTC+8）"
                    )
                # 能力页表三列：表头恒定，行末列更新时间格式合法
                try:
                    dom_header_pos = lines.index(_DOMAIN_TABLE_HEADER)
                except ValueError:
                    violations.append(
                        f"{label}: 缺能力页三列表（表头须为 {_DOMAIN_TABLE_HEADER}）"
                    )
                else:
                    for row in lines[dom_header_pos + 1:]:
                        if not row.startswith("|"):
                            break  # 表格结束
                        cells = [c.strip() for c in row.strip().strip("|").split("|")]
                        if cells and cells[0] and set(cells[0]) <= {"-"}:  # 分隔行（首列非空，防空串误判）
                            continue
                        if len(cells) != 3 or not _STAMP_CELL_RE.match(cells[2]):
                            violations.append(
                                f"{label}: 能力页行更新时间缺失或格式非法"
                                f"（三列，末列 YYYY-MM-DD HH:MM）: {row}"
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
            # marker 紧随 H1（契约：前 5 行内出现）
            head = "\n".join(text.splitlines()[:5])
            if not _MARKER_RE.search(head):
                violations.append(f"{label}: marker 缺失或未紧随 H1")
                continue
            marker = parse_marker(text)
            if marker is None:
                violations.append(f"{label}: marker 字段非法（capability/rev/sources）")
                continue
            # sources 按 origin 分支校验（fix-knowledge-backfill-reconstruction）
            origin = marker.get("origin") or ORIGIN_ARCHIVE
            if origin == ORIGIN_ARCHIVE:
                # 归档页：sources 指向真实归档目录
                for src in marker["sources"]:
                    if not src.startswith(ARCHIVE_DIR + "/"):
                        violations.append(f"{label}: sources 非归档路径: {src}")
                        continue
                    if not (proot / src).is_dir():
                        violations.append(f"{label}: sources 指向不存在的归档目录: {src}")
                        continue
                    # 归一化复核（code-review b349a3a0000a）：src 含 ".." 相对
                    # 段时上两道检查均通过，OS 层解析后实际指向归档目录之外的
                    # 真实目录；resolve 后复核仍在归档目录内（与本函数
                    # _check_links 的越界判定及 _gate_distill 拒绝 ".." 同强度）。
                    try:
                        (proot / src).resolve().relative_to(arch_root.resolve())
                    except ValueError:
                        violations.append(f"{label}: sources 越出归档目录: {src}")
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
            # 150 行硬顶
            line_count = len(text.splitlines())
            if line_count > MAX_PAGE_LINES:
                violations.append(
                    f"{label}: 超过 {MAX_PAGE_LINES} 行硬顶（{line_count} 行），须拆页或精简"
                )
            _check_links(text, page.parent, label)

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
            try:
                header_pos = index_lines.index(_INDEX_TABLE_HEADER)
            except ValueError:
                violations.append(
                    f"{index_label}: 缺能力域四列表（表头须为 {_INDEX_TABLE_HEADER}）"
                )
            else:
                for row in index_lines[header_pos + 1:]:
                    if not row.startswith("|"):
                        break  # 表格结束
                    cells = [c.strip() for c in row.strip().strip("|").split("|")]
                    if cells and cells[0] and set(cells[0]) <= {"-"}:  # 分隔行（首列非空，防空串误判）
                        continue
                    if len(cells) != 4 or not _STAMP_CELL_RE.match(cells[3]):
                        violations.append(
                            f"{index_label}: 能力域行更新时间缺失或格式非法"
                            f"（四列，末列 YYYY-MM-DD HH:MM）: {row}"
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
            if adr.name == "index.md":
                _check_links(text, adr.parent, label)
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
                violations.append(f"{label}: 头部缺 status 行（accepted|superseded）")
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


# ── 派发与执行器 ──────────────────────────────────────────────────────

def load_distill_prompt() -> str:
    """读蒸馏提示词模板（core/knowledge_prompts/distill.md）。"""
    path = Path(__file__).resolve().parent / PROMPT_FILE
    return path.read_text(encoding="utf-8")


def build_distill_prompt(proot: Path, archived_names: list) -> str:
    """组装蒸馏 run 提示词：模板全文 + 动态段（归档清单与绝对路径）。"""
    tpl = load_distill_prompt()
    archive_items = "\n".join(
        f"- {name}（目录：{proot / ARCHIVE_DIR / name}）" for name in archived_names
    )
    stamp, tz = local_now_stamp()
    return (
        f"{tpl}\n\n---\n\n"
        f"## 本次任务（动态段）\n\n"
        f"项目根（当前工作目录）：{proot}\n"
        f"真相源目录：{proot / KNOWLEDGE_DIR}\n"
        f"当前本地时间：{stamp}（时区 {tz}）。index.md 与受影响域 _domain.md 的"
        f"「最后更新」盖戳行、各表更新时间列一律以此时间为准，盖戳行写为"
        f"`> 最后更新：{stamp} {tz}`\n\n"
        f"本次待蒸馏的归档：\n{archive_items}\n"
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
    return subprocess.Popen(
        cmd,
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env if env is not None else _build_spawn_env(),
        start_new_session=True,
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


def _discard_output(proot: Path, before=None) -> bool:
    """放弃产出：restore tracked + 清理未跟踪新增（不留半成品）。

    基线感知（code-review 4d1e46fa795c）：``before`` 为本次 run 前的
    ``_git_status_paths`` 快照。仅当 spec/knowledge/ 下当前脏路径相对基线
    确为本次 run 新增（基线中不存在）时才整目录 restore/clean；基线中已有
    同路径改动说明用户在合法写面内有未提交的手工策展，整目录回滚会连带
    吞掉它们——降级为 WARNING 留痕交人工处理（与 _audit_stray_writes
    「不吞用户未提交改动」同一尺度）。基线不可用（git 失败/非 git 仓库）
    时同样保守跳过。

    Returns:
        True = 回滚清理已执行且残留复查确认干净；False = 保守跳过（基线已有
        路径或基线不可用）或回滚未确认（restore/clean 失败、残留复查不可用、
        复查仍有残留）。调用方须把 False 按「回滚未确认」口径落日志与台账，
        不得当作已清理干净。
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
    overlap = sorted(p for p in after_k if p in baseline_k)
    if overlap:
        logger.warning(
            "knowledge-distill 放弃产出：spec/knowledge/ 下改动含 run 前基线"
            "已有路径（疑似用户未提交的手工策展），跳过整目录回滚以免吞掉"
            "用户改动，请人工核查: %s",
            ", ".join(overlap),
        )
        return False
    try:
        restore = _git(proot, ["restore", "--", KNOWLEDGE_DIR])
        if restore.returncode != 0:
            # code-review 37565545ea29：非零退出（index.lock 占用、路径规格
            # 异常等）必须留痕。注意 pathspec 在索引零命中（产出全为新建
            # 未跟踪文件、无可 restore 的 tracked 改动）时 restore 也退出
            # 非零——这是良性态，是否「未确认」交由下方残留复查裁决，
            # 不在此处直接判失败
            logger.warning(
                "knowledge-distill git restore 退出码 %d（stderr: %s），"
                "tracked 改动回滚结果待残留复查确认",
                restore.returncode,
                (restore.stderr or "").strip()[-300:] or "（空）",
            )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("knowledge-distill git restore 失败: %s", e)
    try:
        # -d（code-review e2029f25ad5b）：clean 缺省不进未跟踪目录，run 新建的
        # 域目录（spec/knowledge/domains/<新域>/ 等）乃至整个 spec/knowledge/
        # 会整体滞留工作区，滞留半成品会被下批 _commit_output 一并提交进
        # 知识库真相源
        clean = _git(proot, ["clean", "-fd", "--", KNOWLEDGE_DIR])
        if clean.returncode != 0:
            logger.warning(
                "knowledge-distill git clean 退出码 %d（stderr: %s），"
                "未跟踪半成品清理结果待残留复查确认",
                clean.returncode,
                (clean.stderr or "").strip()[-300:] or "（空）",
            )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("knowledge-distill git clean 失败: %s", e)
    # 残留复查（code-review e2029f25ad5b）：restore/clean 未覆盖的路径（如被
    # ignore 的文件）滞留即告警留痕，不让「不留半成品」静默失约
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
    left = sorted(residue_k)
    if left:
        logger.warning(
            "knowledge-distill 放弃产出：回滚后 spec/knowledge/ 仍有残留半成品，"
            "请人工核查: %s",
            ", ".join(left),
        )
        return False
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
# - .fenix/todo.md 与伴生锁 .fenix/.todo.md.lock：todo.md 重试台账
#   （_register_todo_retry → append_todo_line）
# 这些运行时文件被 .gitignore 的 .fenix/* 规则忽略、本不进 git status，仍逐项
# 列出以固化真实写面（gitignore 规则变动时不静默变成误报源）。
_STRAY_AUDIT_IGNORE_PREFIXES = (
    KNOWLEDGE_DIR + "/",
    ".fenix/knowledge-distill.lock",
    ".fenix/knowledge-distill-pending.json",
    ".fenix/knowledge-distill-pending.lock",
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
        p for p in expanded if not p.startswith(_STRAY_AUDIT_IGNORE_PREFIXES)
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
    need_probe = False
    for p in paths:
        if p.startswith(kn_prefix):
            if p.endswith("/"):
                need_probe = True  # knowledge 目录内部整目录折叠
            else:
                surface.add(p)
        elif p.endswith("/") and kn_prefix.startswith(p):
            need_probe = True  # 祖先目录折叠（如 spec/ 全树未跟踪）
    if need_probe:
        probe = _git(
            proot,
            [
                "--no-optional-locks", "ls-files",
                "--others", "--exclude-standard", "-z",
                "--", KNOWLEDGE_DIR,
            ],
        )
        if probe.returncode == 0:
            surface.update(tok for tok in probe.stdout.split("\0") if tok)
        else:
            logger.warning(
                "knowledge-distill 未跟踪文件枚举失败，无法可靠判定基线差集"
            )
            return None
    return surface


def _commit_output(proot: Path, archived_names: list, baseline=None) -> str | None:
    """pathspec 限定自动提交（复用 archive_commit 的 fail-open 哲学）。

    基线甄别（code-review 50251dbfd0c1）：``baseline`` 为本批 run 前的
    ``_git_status_paths`` 快照（_run_batch 的 run_baseline），与
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
    commit_msg = f"{COMMIT_PREFIX} {names}"
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
    except ValueError:
        logger.warning("knowledge-distill pending 台账损坏（非法 JSON），按空表处理")
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
    import fcntl

    lock_dir = Path(proot) / ".fenix"
    lock_dir.mkdir(parents=True, exist_ok=True)
    fh = open(lock_dir / "knowledge-distill-pending.lock", "w")  # noqa: SIM115 — 生命周期=with
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


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
        """按本批 names 并集匹配移除台账条目（持跨进程 flock 读-过滤-原子回写；fail-open）。

        整文件重读-过滤-回写而非「删一条重写全量快照」：避免并发归档入队的
        追加被整文件覆盖丢条目（design D2）。读改写窗口持 _pending_ledger_lock
        flock：双进程并发时 remove 的回写不得吞掉另一进程刚 append 的条目、
        或复活已入库批次的条目。并集交集匹配一次清除多条——
        worker 把同项目积压整体摘下合并为一次 run 时，只清「最后一条」会漏清
        先入队条目，陈旧条目会在重启恢复时对已入库归档触发重蒸。
        """
        try:
            with _pending_ledger_lock(proot):
                batches = _read_pending_ledger(proot)
                kept = [
                    b
                    for b in batches
                    if not (set(b["names"]) & set(archived_names))
                ]
                if len(kept) != len(batches):
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
        """跨进程单飞锁（flock，阻塞等待——并发归档事件排队串行）。"""
        import fcntl

        lock_dir = proot / ".fenix"
        lock_dir.mkdir(parents=True, exist_ok=True)
        fh = open(lock_dir / "knowledge-distill.lock", "w")  # noqa: SIM115 — 生命周期=with
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        except BaseException:
            # flock 失败（EINTR 信号处理器抛出/文件系统不支持等）必须先关句柄
            # 再抛，否则常驻 daemon 每次失败泄漏一个 fd（code-review 6302dcf20837）
            fh.close()
            raise
        return fh

    def _run_with_lock(self, proot: Path, batch: list) -> None:
        lock_fh = self._acquire_file_lock(proot)
        try:
            self._run_batch(proot, batch)
        finally:
            import fcntl

            try:
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
            finally:
                lock_fh.close()

    # ── 一批蒸馏：run → 校验 → 修正（≤2 轮）→ 提交/放弃 ─────────────
    def _run_batch(self, proot: Path, archived_names: list) -> dict:
        names = ", ".join(archived_names)
        prompt = build_distill_prompt(proot, archived_names)
        violations = None
        result = {"ok": False, "names": names, "rounds": 0, "commit": None, "error": None}

        # 批次级 run 前基线快照（code-review 4d1e46fa795c）：放弃产出时据此
        # 判别 spec/knowledge/ 下哪些改动是用户 run 前既有的未提交改动，避免
        # 整目录回滚吞掉手工策展；成功收尾时同快照供 _commit_output 做提交
        # 基线甄别（仅收纳本轮新增路径，code-review 50251dbfd0c1）。逐轮快照
        # （status_before）仍供越界对账。
        run_baseline = _git_status_paths(proot)

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
            ok, err = self._spawn_and_wait(proot, prompt)
            if not ok:
                result["error"] = err
                self._give_up(proot, archived_names, f"run 失败: {err}", before=run_baseline)
                _audit_stray_writes(proot, status_before, names)
                return result
            violations = validate_knowledge(proot)
            if not violations:
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
            (ok, error)：ok=True 进程已退出且退出码 0（产物合法性交校验脚本）。
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
                    permission_mode="bypassPermissions",
                    env_mode=ENV_MODE_CLEAN,
                    project_root=str(proot),
                ),
                timeout=RUN_TIMEOUT_SECONDS,
                popen=_popen,
                on_timeout=_kill_process_group,
            )
        except OneShotCommunicateError as e:
            return False, f"claude 进程通信失败: {e.original}"
        except Exception as e:  # noqa: BLE001 — CLI 不存在等 spawn 失败
            return False, f"调用 claude CLI 失败: {e}"
        if outcome.timed_out:
            return False, f"run 超时（>{RUN_TIMEOUT_SECONDS}s），已终止进程组"
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
            return False, f"claude 进程非零退出（exit={outcome.returncode}）{detail}"
        return True, None

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
    """单条/批量派发共用的门控链（enabled → 归档存在 → 回填期排队）。

    双入口共用同一实现，避免门控规则漂移出现单条/批量行为不一致
    （code-review f58075519410）。

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

    # 归档目录存在性（蒸馏只读归档；软删除路径命名同样落 spec/archive/）。
    # 防御（code-review b00585e3c85b）：归档名须为单一路径成分——含路径
    # 分隔符或为 . / .. 时，存在性检查与蒸馏上下文拼出的路径会越出归档
    # 目录，一律按缺失拒绝。
    missing = [
        n
        for n in archived_names
        if not n
        or n in (".", "..")
        or os.sep in n
        or "/" in n
        or not (proot / ARCHIVE_DIR / n).is_dir()
    ]
    if missing:
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
    """归档蒸馏派发入口（task 2.1；commit_archive_move 单点挂载的漏斗）。

    Args:
        project_root: 项目根目录
        archived_name: 归档目录名（``spec/archive/<日期-名>`` 的目录名部分；
            软删除路径的 ``<名>-<Unix秒>`` 同样兼容）
        config: 有效配置 dict；None 时经 ``ConfigLoader.resolve_config``
            现场解析（归档低频，解析成本可接受）
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
