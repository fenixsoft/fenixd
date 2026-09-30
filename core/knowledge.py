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

import logging
import os
import re
import signal
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.agent_env_keys import AGENT_RUN_BANNED_ENV_KEYS as _BANNED_ENV_KEYS
from core.knowledge_backfill import (
    append_todo_line,
    ledger_has_pending,
    register_archive_pending,
)

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
_KEBAB_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
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
    now = datetime.now().astimezone()
    total_min = round((now.utcoffset() or timedelta()).total_seconds() / 60)
    sign = "+" if total_min >= 0 else "-"
    hours, minutes = divmod(abs(total_min), 60)
    tz = f"UTC{sign}{hours}" + (f":{minutes:02d}" if minutes else "")
    return now.strftime("%Y-%m-%d %H:%M"), tz

# ADR 文件名与头部状态
_ADR_NAME_RE = re.compile(r"^ADR-(\d{3})-.+\.md$")
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


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        r = subprocess.run(
            ["git", "show", f"HEAD:{rel_path}"],
            cwd=str(proot),
            capture_output=True,
            text=True,
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


def validate_knowledge(project_root) -> list:
    """确定性校验 ``spec/knowledge/``（task 2.1）。

    Returns:
        违规字符串列表（空列表 = 全部通过）。目录不存在视为未初始化
        （首个蒸馏 run 前），不视为违规。
    """
    proot = Path(project_root)
    kroot = proot / KNOWLEDGE_DIR
    violations: list = []
    if not kroot.is_dir():
        return violations

    arch_root = proot / ARCHIVE_DIR

    def _check_links(text: str, rel_dir: Path, label: str) -> None:
        """index/_domain/adr 链接可解析且不越出真相源目录。"""
        for m in _LINK_RE.finditer(text):
            target = m.group(1)
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            path_part = target.split("#", 1)[0]
            if not path_part:
                continue  # 纯页内锚点
            resolved = (rel_dir / path_part).resolve()
            try:
                resolved.relative_to(kroot.resolve())
            except ValueError:
                violations.append(f"{label}: 链接越出真相源目录: {target}")
                continue
            if not resolved.exists():
                violations.append(f"{label}: 链接目标不存在: {target}")

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
                    if not _git_ref_resolvable(proot, am.group(1)):
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
            head_text = _git_show(proot, rel_posix)
            if head_text is not None and _adr_body(head_text) != _adr_body(text):
                violations.append(f"{label}: 已落盘 ADR 三段正文被改写（不可变契约）")

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
    now_local, tz = local_now_stamp()
    return (
        f"{tpl}\n\n---\n\n"
        f"## 本次任务（动态段）\n\n"
        f"项目根（当前工作目录）：{proot}\n"
        f"真相源目录：{proot / KNOWLEDGE_DIR}\n"
        f"当前本地时间：{now_local}（时区 {tz}）。index.md 与受影响域 _domain.md 的"
        f"「最后更新」盖戳行、各表更新时间列一律以此时间为准，盖戳行写为"
        f"`> 最后更新：{now_local} {tz}`\n\n"
        f"本次待蒸馏的归档：\n{archive_items}\n"
    )


def _build_spawn_env() -> dict:
    env = os.environ.copy()
    for key in _BANNED_ENV_KEYS:
        env.pop(key, None)
    return env


def _default_spawn(cmd: list, cwd: str):
    """spawn claude 子进程（独立会话组，超时可 killpg 整组清场）。"""
    return subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_build_spawn_env(),
        start_new_session=True,
    )


def _kill_process_group(proc: subprocess.Popen) -> None:
    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, OSError):
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
    try:
        proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        # SIGKILL 后 communicate 仍可能永久阻塞：蒸馏 run 派生的孙进程若重新
        # setsid 逃出进程组并继承 stdout/stderr 管道，管道不关闭——worker 线程
        # 卡死连带 knowledge-distill.lock 不释放，同项目后续批次全部滞留
        # （code-review 44d833e20470）。强杀直接子进程并弃管道，保底让
        # _run_with_lock 的 finally 能释放 flock。
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
    return subprocess.run(
        ["git"] + args,
        cwd=str(proot),
        capture_output=True,
        text=True,
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
        True = 已执行回滚清理；False = 保守跳过（含基线已有路径或基线不可用）。
    """
    after = _git_status_paths(proot)
    if before is None or after is None:
        logger.warning(
            "knowledge-distill 放弃产出：工作区基线快照不可用，跳过 "
            "spec/knowledge/ 回滚（避免吞掉用户未提交改动），请人工核查"
        )
        return False
    overlap = sorted(p for p in after if p.startswith(KNOWLEDGE_DIR + "/") and p in before)
    if overlap:
        logger.warning(
            "knowledge-distill 放弃产出：spec/knowledge/ 下改动含 run 前基线"
            "已有路径（疑似用户未提交的手工策展），跳过整目录回滚以免吞掉"
            "用户改动，请人工核查: %s",
            ", ".join(overlap),
        )
        return False
    try:
        _git(proot, ["restore", "--", KNOWLEDGE_DIR])
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("knowledge-distill git restore 失败: %s", e)
    try:
        # -d（code-review e2029f25ad5b）：clean 缺省不进未跟踪目录，run 新建的
        # 域目录（spec/knowledge/domains/<新域>/ 等）乃至整个 spec/knowledge/
        # 会整体滞留工作区，滞留半成品会被下批 _commit_output 的全目录
        # git add 一并提交进知识库真相源
        _git(proot, ["clean", "-fd", "--", KNOWLEDGE_DIR])
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("knowledge-distill git clean 失败: %s", e)
    # 残留复查（code-review e2029f25ad5b）：restore/clean 未覆盖的路径（如被
    # ignore 的文件）滞留即告警留痕，不让「不留半成品」静默失约
    residue = _git_status_paths(proot)
    left = sorted(p for p in (residue or ()) if p.startswith(KNOWLEDGE_DIR + "/"))
    if left:
        logger.warning(
            "knowledge-distill 放弃产出：回滚后 spec/knowledge/ 仍有残留半成品，"
            "请人工核查: %s",
            ", ".join(left),
        )
    return True


# 越界写面对账（code-review c8e789897144）：蒸馏 run 以 bypassPermissions 在主树
# 直跑，「写路径限定 spec/knowledge/」仅由提示词承载，validate_knowledge 与
# _discard_output 也只覆盖 KNOWLEDGE_DIR——run 越界改动主树其他路径（如被归档
# spec 内容提示注入后改产品代码）既不会被校验拦截也不会被回滚。蒸馏车道合法
# 写面 = 产出本体（KNOWLEDGE_DIR）+ .fenix/ 下框架运行时文件（distill flock
# 锁、todo.md 重试台账），对账时排除以免误报。
_STRAY_AUDIT_IGNORE_PREFIXES = (KNOWLEDGE_DIR + "/", ".fenix/")


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
    strays = sorted(
        p for p in after - before if not p.startswith(_STRAY_AUDIT_IGNORE_PREFIXES)
    )
    if strays:
        logger.warning(
            "knowledge-distill 越界写面告警（%s）: run 在蒸馏车道合法写面"
            "（%s、.fenix/）之外新增主树改动，未回滚（避免吞掉用户未提交改动），"
            "请人工核查: %s",
            label,
            KNOWLEDGE_DIR,
            ", ".join(strays),
        )


def _commit_output(proot: Path, archived_names: list) -> str | None:
    """pathspec 限定自动提交（复用 archive_commit 的 fail-open 哲学）。

    Returns:
        commit hash；``""``（工作区无变更，nothing to commit，视为 ok）；
        None（提交失败，已记 warning）。
    """
    names = ", ".join(archived_names)
    commit_msg = f"{COMMIT_PREFIX} {names}"
    try:
        add = _git(proot, ["add", "--", KNOWLEDGE_DIR])
        if add.returncode != 0:
            logger.warning("knowledge-distill git add 失败: %s", add.stderr.strip())
            return None
        commit = _git(proot, ["commit", "-m", commit_msg, "--", KNOWLEDGE_DIR], timeout=120)
        if commit.returncode != 0:
            # nothing to commit ≠ 提交失败：蒸馏判定无需新增/修改页面（如重复
            # 蒸馏同批归档），按无变更视为 ok，避免误报「产出滞留」+ 误登重试
            # 台账（code-review 1e83848b80f1）。
            status = _git(proot, ["status", "--porcelain", "--", KNOWLEDGE_DIR])
            if status.returncode == 0 and not status.stdout.strip():
                logger.info("knowledge-distill 无变更可提交（%s），跳过空提交", names)
                return ""
            _git(proot, ["reset", "--", KNOWLEDGE_DIR])
            logger.warning(
                "knowledge-distill git commit 失败: %s",
                commit.stderr.strip() or f"exit {commit.returncode}",
            )
            return None
        rev = _git(proot, ["log", "-1", "--format=%H", "--", KNOWLEDGE_DIR])
        return rev.stdout.strip() if rev.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("knowledge-distill 自动提交异常: %s", e)
        return None


class DistillManager:
    """蒸馏 run 管理器（进程内单例）。

    - 同 project 单飞：进程内 per-project 队列 + 单 worker 线程串行消费；
      积压条目合并为一次批量 run（spec 允许的实现裁量）。
    - 跨进程互斥：``.fenix/knowledge-distill.lock`` flock（daemon 与 dashboard
      --serve 分属两进程时仍保证同时至多一个蒸馏 run 在写 spec/knowledge/）。
    - spawn 可注入替身（task 2.4 单测 fake spawn 三支路）。
    """

    def __init__(self, spawn=None, max_fix_rounds: int = MAX_FIX_ROUNDS):
        self._spawn = spawn or _default_spawn
        self._max_fix_rounds = max_fix_rounds
        self._guard = threading.Lock()
        self._queues: dict = {}
        self._workers: dict = {}

    # ── 对外：入队（不阻塞归档主流程）───────────────────────────────
    def dispatch(self, proot: Path, archived_names: list) -> dict:
        key = str(Path(proot).resolve())
        names = list(archived_names)
        with self._guard:
            queue = self._queues.setdefault(key, [])
            worker = self._workers.get(key)
            queue.extend(names)
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
                _register_todo_retry(proot, batch, f"执行异常: {e}")

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
        # 整目录回滚吞掉手工策展。逐轮快照（status_before）仍供越界对账。
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
                commit = _commit_output(proot, archived_names)
                if commit is None:
                    # 提交失败当轮重试一次（index.lock 撞车等瞬态失败常可恢复）
                    commit = _commit_output(proot, archived_names)
                if commit is not None:
                    result["ok"] = True
                    result["commit"] = commit
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
                    "（请人工提交；注意后续放弃产出的清理会回滚工作区）",
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
        cmd = ["claude", "-p", prompt, "--permission-mode", "bypassPermissions"]
        try:
            proc = self._spawn(cmd, cwd=str(proot))
        except Exception as e:  # noqa: BLE001 — CLI 不存在等 spawn 失败
            return False, f"调用 claude CLI 失败: {e}"
        try:
            stdout, stderr = proc.communicate(timeout=RUN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            _kill_process_group(proc)
            return False, f"run 超时（>{RUN_TIMEOUT_SECONDS}s），已终止进程组"
        except Exception as e:  # noqa: BLE001
            _kill_process_group(proc)
            return False, f"claude 进程通信失败: {e}"
        if proc.returncode != 0:
            # 失败诊断：stdout/stderr 摘要进日志，stderr 尾部随 error 一路进
            # todo.md 台账 reason（否则蒸馏失败排障拿不到 claude 的报错，
            # code-review 0d6683c2b68d）。
            stdout_tail = (stdout or "").strip()[-500:]
            stderr_tail = (stderr or "").strip()[-500:]
            logger.warning(
                "knowledge-distill run 非零退出（exit=%s）stdout 摘要: %s | stderr 摘要: %s",
                proc.returncode,
                stdout_tail[:200] or "（空）",
                stderr_tail[:200] or "（空）",
            )
            detail = f"；stderr 尾部: {stderr_tail}" if stderr_tail else ""
            return False, f"claude 进程非零退出（exit={proc.returncode}）{detail}"
        return True, None

    def _give_up(self, proot: Path, archived_names: list, reason: str, before=None) -> None:
        """放弃产出：清理半成品 + 登重试台账（``before`` = run 前基线快照）。"""
        discarded = _discard_output(proot, before)
        _register_todo_retry(proot, archived_names, reason)
        if discarded:
            logger.warning(
                "knowledge-distill 放弃产出（%s）: %s；已清理 spec/knowledge/ 半成品并登重试台账",
                ", ".join(archived_names),
                reason,
            )
        else:
            logger.warning(
                "knowledge-distill 放弃产出（%s）: %s；spec/knowledge/ 回滚已保守跳过"
                "（详见前序告警），半成品滞留工作区请人工核查，已登重试台账",
                ", ".join(archived_names),
                reason,
            )


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
    except Exception as e:  # noqa: BLE001 — 配置解析失败按禁用处理（fail-open）
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

    mgr = dispatcher or _get_dispatcher()
    try:
        mgr.dispatch(proot, [archived_name])
        logger.info("knowledge-distill 已派发（archive=%s）", archived_name)
        return {"dispatched": True, "reason": None}
    except Exception as e:  # noqa: BLE001 — fail-open：不影响归档返回值
        logger.warning(
            "knowledge-distill 派发失败（archive=%s）: %s: %s",
            archived_name,
            type(e).__name__,
            e,
        )
        _register_todo_retry(proot, [archived_name], f"派发失败: {e}")
        return {"dispatched": False, "reason": f"error: {e}"}


# 兼容批量入口：auto_archive_check 一轮归档多条时可合并为一次批量 run
def dispatch_distill_batch(project_root, archived_names: list, config=None, *, dispatcher=None) -> dict:
    """批量派发（多条归档合并为一次 run，spec「实现裁量」）。"""
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
    mgr = dispatcher or _get_dispatcher()
    try:
        mgr.dispatch(proot, list(archived_names))
        return {"dispatched": True, "reason": None}
    except Exception as e:  # noqa: BLE001
        logger.warning("knowledge-distill 批量派发失败: %s", e)
        _register_todo_retry(proot, list(archived_names), f"派发失败: {e}")
        return {"dispatched": False, "reason": f"error: {e}"}
